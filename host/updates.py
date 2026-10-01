# -*- coding: utf-8 -*-
"""Signed plugin packages (.vsepkg): verify, stage, activate on restart, roll back.

包格式（zip）：
- ``package.json``：``{"format": 1, "id", "version", "hostApi", "files": {相对路径: sha256}}``
- ``package.sig``：``{"keyId", "signature"}``，Ed25519 签名覆盖 ``package.json`` 的原始字节
- ``files/<相对路径>``：插件目录内容（必须含 ``plugin.json``）

签名覆盖清单、清单覆盖每个文件的 sha256，所以任何文件被改动都会被拒绝。

目录布局（位于可写数据目录 ``<data>/plugin-updates/``，宿主升级时随 ``data/`` 一起迁移）：
- ``staging/<id>/<version>/``：已验证、等待重启生效
- ``installed/<id>/<version>/``：已生效过的版本（保留用于回滚）
- ``active.json``：``{"format": 1, "plugins": {id: {"version", "previous"}}, "events": [...]}``

规则（勿破）：
- 只在启动时切换版本（导入只做暂存），用户可见的是“重启后生效”，绝不强制。
- ``active.json`` 用临时文件 + ``os.replace`` 原子写入。
- 插件只能装进自己的 ``installed/<id>/``，不能覆盖宿主文件或其他插件。
- 新版本启动失败时自动切回上一个版本（无上一版本则回到随包内置版本）。
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from host.plugin import (
    HOST_API_VERSION,
    MANIFEST_FILE_NAME,
    PluginManifestError,
    host_api_compatible,
    load_manifest,
)

PACKAGE_FORMAT = 1
PACKAGE_SUFFIX = ".vsepkg"
_MAX_PACKAGE_BYTES = 16 * 1024 * 1024
_MAX_UNPACKED_BYTES = 64 * 1024 * 1024
_MAX_FILES = 2000
_MAX_EVENTS = 50
_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,39}$")
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
_SKIP_PARTS = frozenset({"__pycache__", ".pytest_cache", "tests"})
TRUSTED_KEYS_FILE = Path(__file__).resolve().parent / "trusted_keys.json"


class PackageError(ValueError):
    """A package was rejected; the message is safe to show to the user."""


def version_tuple(version: str) -> tuple[int, int, int]:
    if not _VERSION_PATTERN.match(version or ""):
        raise PackageError(f"版本号无效: {version}")
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── keys ─────────────────────────────────────────────────────────────


def load_trusted_keys(path: Path | None = None) -> dict[str, bytes]:
    """Return ``{keyId: raw 32-byte Ed25519 public key}``; empty if none configured."""
    path = path or TRUSTED_KEYS_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    keys: dict[str, bytes] = {}
    for item in raw.get("keys", []):
        key_id = str(item.get("keyId") or "")
        public = base64.b64decode(str(item.get("publicKey") or ""), validate=True)
        if key_id and len(public) == 32:
            keys[key_id] = public
    return keys


def key_id_for(public_key: bytes) -> str:
    return _sha256(public_key)[:16]


def sign_manifest(manifest_bytes: bytes, private_key_pem: bytes) -> dict[str, str]:
    """Build the ``package.sig`` payload (build machine only)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(private, Ed25519PrivateKey):
        raise PackageError("私钥不是 Ed25519")
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return {
        "keyId": key_id_for(public),
        "signature": base64.b64encode(private.sign(manifest_bytes)).decode("ascii"),
    }


def _verify_signature(manifest_bytes: bytes, sig: Mapping[str, Any], keys: Mapping[str, bytes]) -> str:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if not keys:
        raise PackageError("宿主未配置可信公钥，无法导入插件包（见 tools/plugin_keys.py）")
    key_id = str(sig.get("keyId") or "")
    public = keys.get(key_id)
    if public is None:
        raise PackageError("插件包的签名密钥不受信任")
    try:
        signature = base64.b64decode(str(sig.get("signature") or ""), validate=True)
        Ed25519PublicKey.from_public_bytes(public).verify(signature, manifest_bytes)
    except (InvalidSignature, ValueError):
        raise PackageError("插件包签名校验失败") from None
    return key_id


# ── build ────────────────────────────────────────────────────────────


def iter_plugin_files(plugin_dir: Path) -> list[tuple[str, Path]]:
    files = []
    for path in sorted(Path(plugin_dir).rglob("*")):
        if not path.is_file() or path.suffix == ".pyc":
            continue
        relative = path.relative_to(plugin_dir).as_posix()
        if any(part in _SKIP_PARTS for part in PurePosixPath(relative).parts):
            continue
        files.append((relative, path))
    return files


def build_package(plugin_dir: Path, private_key_pem: bytes) -> tuple[str, bytes]:
    """Return ``(file name, package bytes)`` for a plugin directory."""
    manifest = load_manifest(plugin_dir)
    entries = iter_plugin_files(plugin_dir)
    contents = {relative: path.read_bytes() for relative, path in entries}
    package_manifest = {
        "format": PACKAGE_FORMAT,
        "id": manifest.id,
        "version": manifest.version,
        "hostApi": manifest.host_api,
        "files": {relative: _sha256(data) for relative, data in contents.items()},
    }
    manifest_bytes = json.dumps(package_manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    signature = sign_manifest(manifest_bytes, private_key_pem)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("package.json", manifest_bytes)
        archive.writestr("package.sig", json.dumps(signature).encode("utf-8"))
        for relative, data in contents.items():
            archive.writestr(f"files/{relative}", data)
    return f"{manifest.id}-{manifest.version}{PACKAGE_SUFFIX}", buffer.getvalue()


# ── verify ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class VerifiedPackage:
    id: str
    version: str
    host_api: str
    key_id: str
    files: Mapping[str, bytes]


def _safe_relative(name: str) -> str:
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or name.startswith("/")
        or ":" in name
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise PackageError(f"插件包包含非法路径: {name[:80]}")
    return path.as_posix()


def verify_package(data: bytes, keys: Mapping[str, bytes], *, host_api_version: str = HOST_API_VERSION) -> VerifiedPackage:
    if len(data) > _MAX_PACKAGE_BYTES:
        raise PackageError("插件包过大")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise PackageError("不是有效的插件包（zip 格式错误）") from None
    with archive:
        infos = archive.infolist()
        if len(infos) > _MAX_FILES + 2:
            raise PackageError("插件包文件数量过多")
        if sum(info.file_size for info in infos) > _MAX_UNPACKED_BYTES:
            raise PackageError("插件包解压后过大")
        names = {info.filename: info for info in infos if not info.is_dir()}
        for name in names:
            _safe_relative(name)
        if "package.json" not in names or "package.sig" not in names:
            raise PackageError("插件包缺少 package.json 或 package.sig")
        manifest_bytes = archive.read("package.json")
        try:
            sig = json.loads(archive.read("package.sig"))
        except json.JSONDecodeError:
            raise PackageError("package.sig 无法解析") from None
        key_id = _verify_signature(manifest_bytes, sig, keys)
        # 只有签名通过后才解析清单内容。
        manifest = json.loads(manifest_bytes)
        if manifest.get("format") != PACKAGE_FORMAT:
            raise PackageError("不支持的插件包格式版本")
        plugin_id = str(manifest.get("id") or "")
        version = str(manifest.get("version") or "")
        host_api = str(manifest.get("hostApi") or "")
        if not _ID_PATTERN.match(plugin_id):
            raise PackageError("插件包 id 无效")
        version_tuple(version)
        try:
            compatible = host_api_compatible(host_api, host_api_version)
        except PluginManifestError as exc:
            raise PackageError(str(exc)) from None
        if not compatible:
            raise PackageError(f"插件包需要宿主 API {host_api}，当前为 {host_api_version}，请先升级宿主")
        listed = manifest.get("files")
        if not isinstance(listed, dict) or MANIFEST_FILE_NAME not in listed:
            raise PackageError("插件包清单缺少文件列表或 plugin.json")
        payload_names = {name[len("files/"):] for name in names if name.startswith("files/")}
        extra = set(names) - {"package.json", "package.sig"} - {f"files/{n}" for n in payload_names}
        if extra or payload_names != set(listed):
            raise PackageError("插件包内容与签名清单不一致")
        files: dict[str, bytes] = {}
        for relative, digest in listed.items():
            content = archive.read(f"files/{_safe_relative(relative)}")
            if _sha256(content) != digest:
                raise PackageError(f"文件校验失败: {relative}")
            files[relative] = content
    inner = json.loads(files[MANIFEST_FILE_NAME])
    if inner.get("id") != plugin_id or inner.get("version") != version or inner.get("hostApi") != host_api:
        raise PackageError("plugin.json 与插件包清单的 id/version/hostApi 不一致")
    return VerifiedPackage(id=plugin_id, version=version, host_api=host_api, key_id=key_id, files=files)


# ── install state ────────────────────────────────────────────────────


class PluginUpdates:
    """Owns ``<data>/plugin-updates``: staging, installed versions and active.json."""

    def __init__(self, root: Path, *, trusted_keys: Mapping[str, bytes] | None = None) -> None:
        self.root = Path(root)
        self.trusted_keys = dict(trusted_keys if trusted_keys is not None else load_trusted_keys())

    # state file

    @property
    def active_path(self) -> Path:
        return self.root / "active.json"

    def read_state(self) -> dict[str, Any]:
        try:
            state = json.loads(self.active_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            state = {}
        state.setdefault("format", 1)
        state.setdefault("plugins", {})
        state.setdefault("events", [])
        return state

    def _write_state(self, state: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        state["events"] = state.get("events", [])[-_MAX_EVENTS:]
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".active-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2)
            os.replace(tmp, self.active_path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    @staticmethod
    def _event(state: dict[str, Any], kind: str, plugin_id: str, **extra: Any) -> None:
        state["events"].append({"at": _utc_now(), "kind": kind, "plugin": plugin_id, **extra})

    def _dir(self, area: str, plugin_id: str, version: str) -> Path:
        return self.root / area / plugin_id / version

    # import

    def stage(self, data: bytes, *, current_version: str | None = None) -> VerifiedPackage:
        """Verify a package and stage it for the next start. Never touches running code."""
        package = verify_package(data, self.trusted_keys)
        if current_version and version_tuple(package.version) <= version_tuple(current_version):
            raise PackageError(f"已是 {current_version}，插件包版本 {package.version} 不高于当前版本")
        target = self._dir("staging", package.id, package.version)
        staging_root = self.root / "staging" / package.id
        if staging_root.exists():
            shutil.rmtree(staging_root)  # 同一插件只保留最新一次暂存
        tmp = Path(tempfile.mkdtemp(dir=self._ensure(self.root / "staging"), prefix=".tmp-"))
        try:
            for relative, content in package.files.items():
                path = tmp / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            load_manifest(tmp)  # 最终用宿主同一套清单校验
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(tmp, target)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        state = self.read_state()
        self._event(state, "staged", package.id, version=package.version, keyId=package.key_id)
        self._write_state(state)
        return package

    @staticmethod
    def _ensure(path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        return path

    def pending(self) -> list[dict[str, str]]:
        staging = self.root / "staging"
        if not staging.is_dir():
            return []
        items = []
        for plugin_dir in sorted(p for p in staging.iterdir() if p.is_dir() and not p.name.startswith(".")):
            for version_dir in sorted(p for p in plugin_dir.iterdir() if p.is_dir()):
                items.append({"id": plugin_dir.name, "version": version_dir.name})
        return items

    def discard_pending(self, plugin_id: str) -> bool:
        path = self.root / "staging" / plugin_id
        if not _ID_PATTERN.match(plugin_id) or not path.is_dir():
            return False
        shutil.rmtree(path)
        state = self.read_state()
        self._event(state, "discarded", plugin_id)
        self._write_state(state)
        return True

    # startup

    def apply_pending(self) -> list[dict[str, str]]:
        """Move staged packages to installed/ and activate them. Called once at startup."""
        applied = []
        state = self.read_state()
        for item in self.pending():
            plugin_id, version = item["id"], item["version"]
            source = self._dir("staging", plugin_id, version)
            target = self._dir("installed", plugin_id, version)
            if target.exists():
                shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
            shutil.rmtree(self.root / "staging" / plugin_id, ignore_errors=True)
            previous = (state["plugins"].get(plugin_id) or {}).get("version")
            state["plugins"][plugin_id] = {"version": version, "previous": previous}
            self._event(state, "activated", plugin_id, version=version, previous=previous)
            applied.append({"id": plugin_id, "version": version})
        if applied:
            self._write_state(state)
        return applied

    def active_dirs(self) -> dict[str, Path]:
        dirs = {}
        for plugin_id, entry in self.read_state()["plugins"].items():
            version = str((entry or {}).get("version") or "")
            path = self._dir("installed", plugin_id, version)
            if version and (path / MANIFEST_FILE_NAME).is_file():
                dirs[plugin_id] = path
        return dirs

    def rollback(self, plugin_id: str, *, reason: str) -> str | None:
        """Activate the previous installed version (None = fall back to the bundled one)."""
        state = self.read_state()
        entry = state["plugins"].get(plugin_id)
        if not entry:
            return None
        failed = entry.get("version")
        previous = entry.get("previous")
        if previous and (self._dir("installed", plugin_id, previous) / MANIFEST_FILE_NAME).is_file():
            state["plugins"][plugin_id] = {"version": previous, "previous": None}
        else:
            previous = None
            state["plugins"].pop(plugin_id, None)
        self._event(state, "rolled_back", plugin_id, version=failed, to=previous or "bundled", reason=reason[:300])
        self._write_state(state)
        return previous

    def supersede(self, plugin_id: str, *, bundled_version: str) -> None:
        """Drop an installed package that the (upgraded) host's bundled copy has caught up with."""
        state = self.read_state()
        entry = state["plugins"].pop(plugin_id, None)
        if entry is None:
            return
        self._event(state, "superseded", plugin_id, version=entry.get("version"), to=bundled_version)
        self._write_state(state)

    def status(self) -> dict[str, Any]:
        state = self.read_state()
        return {
            "active": state["plugins"],
            "pending": self.pending(),
            "events": list(reversed(state["events"][-20:])),
            "trustedKeys": sorted(self.trusted_keys),
        }
