# -*- coding: utf-8 -*-
"""部署清单（MANIFEST.json）：构建时生成、宿主启动时以**自身视图**校验。

为什么需要：公司终端 DLP 会把「经 PowerShell 复制 / 资源管理器粘贴 / 编辑器保存」
落地到运行目录的文件容器化（明文 + 1024 字节头，头部 16 字节固定魔数）。此时
`VSE-WebUI.exe` 读到的是容器，插件源码在导入期直接以
`SyntaxError/ValueError: source code string cannot contain null bytes` 崩掉，用户
只看到裸栈。本模块把「装错了」变成一句可读错误，并拒绝加载对应插件。

口径（方案 §2.4）：

- 校验范围 = 部署后**由 Python 直接读取**的文件：`plugins/`、`web/static/`、
  `web/templates/`、`core/report_headers.json`、`host/trusted_keys.json`；
  可执行体与 `_internal/` 下的二进制 DLL 不在清单内。
- 只做前缀嗅探 + sha256 比对，**不做任何解密/剥头**。
- 清单缺失（开发态、旧包）不算失败：`status="absent"`，页面显示「未提供部署清单」。
- 校验失败不改业务：只拒绝加载被改动的插件并告警其余差异。
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from services.xlsx_preview import (
    FILE_KIND_ENCRYPTED_CONTAINER,
    SNIFF_BYTES,
    sniff_file_kind,
)

MANIFEST_NAME = "MANIFEST.json"
MANIFEST_SCHEMA = 1

#: 需要校验的部署子树（相对部署根，或在 onedir 的 `_internal/` 下）。
MANIFEST_TREES: tuple[str, ...] = ("plugins", "web/static", "web/templates")
#: 需要校验的单文件。
MANIFEST_FILES: tuple[str, ...] = ("core/report_headers.json", "host/trusted_keys.json")
#: 不属部署内容的目录/后缀（运行期会变，进清单只会假报警）。
_SKIP_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache"}
_SKIP_SUFFIXES = {".pyc", ".pyo"}
#: 单文件上限：超过即视为异常部署（清单只用于源码/资源，不该有超大文件）。
_MAX_FILE_BYTES = 32 * 1024 * 1024
#: onedir 构建里 web/、core/ 等被打进 `_internal/`；清单路径按逻辑路径记录，
#: 校验时依次在部署根与 `_internal/` 下找。
_NESTED_PREFIX = "_internal"


def deploy_root() -> Path:
    """代码部署根：冻结包是 exe 所在目录，源码态是仓库根。"""
    if getattr(sys, "frozen", False):
        try:
            return Path(sys.executable).resolve().parent
        except OSError:  # pragma: no cover - 极端环境
            return Path.cwd()
    return Path(__file__).resolve().parent.parent


def manifest_path(root: Path | None = None) -> Path:
    return Path(root or deploy_root()) / MANIFEST_NAME


def _iter_tree(base: Path, prefix: str) -> Iterable[tuple[str, Path]]:
    if not base.is_dir():
        return
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in _SKIP_SUFFIXES:
            continue
        yield f"{prefix}/{path.relative_to(base).as_posix()}", path


def iter_deploy_files(root: Path | None = None) -> list[tuple[str, Path]]:
    """列出应进清单的文件（逻辑相对路径, 真实路径）。"""
    base = Path(root or deploy_root())
    found: list[tuple[str, Path]] = []
    for tree in MANIFEST_TREES:
        for candidates_root in (base, base / _NESTED_PREFIX):
            tree_path = candidates_root / tree
            if tree_path.is_dir():
                found.extend(_iter_tree(tree_path, tree))
                break
    for relative in MANIFEST_FILES:
        for candidates_root in (base, base / _NESTED_PREFIX):
            candidate = candidates_root / relative
            if candidate.is_file():
                found.append((relative, candidate))
                break
    return found


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    root: Path | None = None,
    *,
    version: str = "",
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """生成清单载荷（确定性：不含时间戳，同一内容两次生成逐字节一致）。"""
    base = Path(root or deploy_root())
    files: list[dict[str, Any]] = []
    for relative, path in iter_deploy_files(base):
        try:
            info = path.stat()
        except OSError:
            continue
        if info.st_size > _MAX_FILE_BYTES:
            continue
        files.append(
            {
                "path": relative,
                "size": int(info.st_size),
                "sha256": sha256_file(path),
            }
        )
    payload: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "version": str(version or ""),
        "fileCount": len(files),
        "files": files,
    }
    if extra:
        payload.update({str(key): value for key, value in extra.items()})
    return payload


def write_manifest(
    root: Path | None = None,
    *,
    version: str = "",
    target: Path | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Path:
    base = Path(root or deploy_root())
    destination = Path(target) if target is not None else manifest_path(base)
    payload = build_manifest(base, version=version, extra=extra)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return destination


@dataclass(frozen=True)
class ManifestCheck:
    """一次启动自检结果。`status`：ok / absent / mismatch / error。"""

    status: str
    ok: bool
    version: str = ""
    checked: int = 0
    mismatched: tuple[str, ...] = ()
    containerized: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    extra_plugins: tuple[str, ...] = ()
    message: str = ""

    def to_payload(self) -> dict[str, Any]:
        """页面/健康接口用的有界载荷（不含绝对路径、不含哈希）。"""
        return {
            "status": self.status,
            "ok": self.ok,
            "version": self.version,
            "checked": self.checked,
            "containerized": len(self.containerized),
            "mismatched": len(self.mismatched),
            "missing": len(self.missing),
            "extraPlugins": len(self.extra_plugins),
            "message": self.message,
        }

    def blocked_plugin_ids(self) -> frozenset[str]:
        """清单校验失败的插件目录名（拒绝加载），其余插件照旧。"""
        blocked: set[str] = set()
        for relative in (*self.mismatched, *self.containerized, *self.missing):
            parts = Path(relative).parts
            if len(parts) >= 2 and parts[0] == "plugins":
                blocked.add(parts[1])
        return frozenset(blocked)


def _read_head(path: Path) -> bytes:
    try:
        with Path(path).open("rb") as handle:
            return handle.read(SNIFF_BYTES)
    except OSError:
        return b""


def _resolve(base: Path, relative: str) -> Path | None:
    for candidates_root in (base, base / _NESTED_PREFIX):
        candidate = candidates_root / relative
        if candidate.is_file():
            return candidate
    return None


def _manifest_containerized(path: Path) -> bool:
    try:
        size = path.stat().st_size
    except OSError:
        return False
    return sniff_file_kind(_read_head(path), size) == FILE_KIND_ENCRYPTED_CONTAINER


def is_containerized_file(path: Path) -> bool:
    """本进程视图下该文件是否为公司终端加密容器（只读前 16 字节，不解密）。"""
    return _manifest_containerized(Path(path))


def _extra_plugin_sources(base: Path, listed: set[str]) -> tuple[str, ...]:
    extras: list[str] = []
    for candidates_root in (base, base / _NESTED_PREFIX):
        plugins_root = candidates_root / "plugins"
        if not plugins_root.is_dir():
            continue
        for path in sorted(plugins_root.rglob("*.py")):
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            relative = f"plugins/{path.relative_to(plugins_root).as_posix()}"
            if relative not in listed:
                extras.append(relative)
        break
    return tuple(extras)


def verify_manifest(
    root: Path | None = None,
    *,
    target: Path | None = None,
) -> ManifestCheck:
    """以**本进程视图**逐文件校验清单；哈希不符时再嗅探容器头。"""
    base = Path(root or deploy_root())
    path = Path(target) if target is not None else manifest_path(base)
    try:
        raw = path.read_bytes()
    except OSError:
        return ManifestCheck(
            status="absent",
            ok=True,
            message="未提供部署清单（开发工作区或旧部署包）",
        )
    if _manifest_containerized(path):
        return ManifestCheck(
            status="mismatch",
            ok=False,
            containerized=(MANIFEST_NAME,),
            message="部署清单本身被容器化（不是明文 JSON）：本次部署不完整",
        )
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return ManifestCheck(
            status="error",
            ok=False,
            message="部署清单无法解析（内容不是合法的 UTF-8 JSON）",
        )
    if not isinstance(data, dict) or not isinstance(data.get("files"), Sequence):
        return ManifestCheck(status="error", ok=False, message="部署清单结构不正确")
    entries = [entry for entry in data["files"] if isinstance(entry, Mapping)]
    mismatched: list[str] = []
    containerized: list[str] = []
    missing: list[str] = []
    listed: set[str] = set()
    checked = 0
    for entry in entries:
        relative = str(entry.get("path") or "")
        if not relative:
            continue
        listed.add(relative)
        resolved = _resolve(base, relative)
        if resolved is None:
            missing.append(relative)
            continue
        checked += 1
        try:
            size = resolved.stat().st_size
        except OSError:
            missing.append(relative)
            continue
        expected_size = entry.get("size")
        expected_digest = str(entry.get("sha256") or "")
        if isinstance(expected_size, int) and expected_size != int(size):
            mismatched.append(relative)
            continue
        if expected_digest and sha256_file(resolved) != expected_digest:
            mismatched.append(relative)
            continue
    # 哈希不符的文件再判一次「是不是容器化」：容器化是环境问题，不是内容被改。
    still_mismatched: list[str] = []
    for relative in mismatched:
        resolved = _resolve(base, relative)
        if resolved is not None and _manifest_containerized(resolved):
            containerized.append(relative)
        else:
            still_mismatched.append(relative)
    for relative in missing:
        resolved = _resolve(base, relative)
        if resolved is not None and _manifest_containerized(resolved):
            containerized.append(relative)
    missing = [item for item in missing if item not in containerized]
    extras = _extra_plugin_sources(base, listed)
    bad = len(still_mismatched) + len(containerized) + len(missing)
    version = str(data.get("version") or "")
    if bad == 0:
        message = f"部署清单校验通过（{checked} 个文件）"
        if extras:
            message += f"；另有 {len(extras)} 个未入清单的插件源文件（请确认来源）"
        return ManifestCheck(
            status="ok",
            ok=True,
            version=version,
            checked=checked,
            extra_plugins=extras,
            message=message,
        )
    detail = f"{bad} 个文件被容器化或被改动"
    if containerized:
        detail += f"（其中 {len(containerized)} 个是加密容器）"
    if extras:
        detail += f"；另有 {len(extras)} 个未入清单的插件源文件"
    return ManifestCheck(
        status="mismatch",
        ok=False,
        version=version,
        checked=checked,
        mismatched=tuple(still_mismatched),
        containerized=tuple(containerized),
        missing=tuple(missing),
        extra_plugins=extras,
        message=detail,
    )


def containerized_hint(relative: str) -> str:
    """给用户看的一句话（不含魔数/十六进制）。"""
    return (
        f"部署文件被容器化：{relative} 在程序视图里是公司终端加密容器，"
        "不是明文源码。请用**解压工具直接解压**整包覆盖到运行目录"
        "（不要用 PowerShell 复制、资源管理器粘贴或编辑器保存），然后重启。"
    )


__all__ = [
    "MANIFEST_FILES",
    "MANIFEST_NAME",
    "MANIFEST_SCHEMA",
    "MANIFEST_TREES",
    "ManifestCheck",
    "build_manifest",
    "containerized_hint",
    "deploy_root",
    "is_containerized_file",
    "iter_deploy_files",
    "manifest_path",
    "sha256_file",
    "verify_manifest",
    "write_manifest",
]
