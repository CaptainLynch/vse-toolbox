# -*- coding: utf-8 -*-
"""Signed ``.vsepkg`` format 2 (``kind: "app"``): build, verify, stage.

Same signature scheme as format 1 plugin packages (``host/updates.py``):
Ed25519 over the raw bytes of ``package.json``, which lists the sha256 of
every payload file. Format 1 packages are still handled by the app's own
plugin updater; :func:`peek_format` lets callers route a file to the right
installer without trusting its content.

Layout of a format 2 zip::

    package.json   {"format": 2, "kind": "app", "version", "requires": {"runtime"},
                    "notes", "migrations": [...], "files": {path: sha256}}
    package.sig    {"keyId", "signature"}
    files/<path>   payload
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import sys
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from vse_boot.layout import InstallLayout, version_tuple

PACKAGE_FORMAT = 2
PACKAGE_SUFFIX = ".vsepkg"
APP_ENTRY = "webui.py"
#: Tag of the interpreter running this code: what an installed runtime accepts.
RUNTIME_TAG = f"cp{sys.version_info.major}{sys.version_info.minor}"
#: Tag of the runtime we ship (VSE-Launcher.spec asserts its build Python matches).
#: Release builds stamp packages with this, not with the packager's own Python.
TARGET_RUNTIME_TAG = "cp312"
_MAX_PACKAGE_BYTES = 32 * 1024 * 1024
_MAX_UNPACKED_BYTES = 256 * 1024 * 1024
_MAX_FILES = 20000


class PackageError(ValueError):
    """A package was rejected; the message is safe to show to the user."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── keys and signatures ──────────────────────────────────────────────


def key_id_for(public_key: bytes) -> str:
    return _sha256(public_key)[:16]


def load_trusted_keys(paths: Iterable[Path]) -> dict[str, bytes]:
    """Merge ``{"keys": [{"keyId", "publicKey"}]}`` files; missing files are skipped."""
    keys: dict[str, bytes] = {}
    for path in paths:
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        for item in raw.get("keys", []):
            key_id = str(item.get("keyId") or "")
            public = base64.b64decode(str(item.get("publicKey") or ""), validate=True)
            if key_id and len(public) == 32:
                keys[key_id] = public
    return keys


def sign_manifest(manifest_bytes: bytes, private_key_pem: bytes) -> dict[str, str]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(private, Ed25519PrivateKey):
        raise PackageError("私钥不是 Ed25519")
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return {"keyId": key_id_for(public), "signature": base64.b64encode(private.sign(manifest_bytes)).decode("ascii")}


def _verify_signature(manifest_bytes: bytes, sig: Mapping[str, Any], keys: Mapping[str, bytes]) -> str:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if not keys:
        raise PackageError("程序未配置可信公钥，无法安装更新包")
    key_id = str(sig.get("keyId") or "")
    public = keys.get(key_id)
    if public is None:
        raise PackageError("更新包的签名密钥不受信任")
    try:
        signature = base64.b64decode(str(sig.get("signature") or ""), validate=True)
        Ed25519PublicKey.from_public_bytes(public).verify(signature, manifest_bytes)
    except (InvalidSignature, ValueError):
        raise PackageError("更新包签名校验失败，文件可能被改动过") from None
    return key_id


def _safe_relative(name: str) -> str:
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or name.startswith("/")
        or ":" in name
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise PackageError(f"更新包包含非法路径: {name[:80]}")
    return path.as_posix()


# ── build ────────────────────────────────────────────────────────────


def build_app_package(
    files: Mapping[str, bytes],
    *,
    version: str,
    private_key_pem: bytes,
    notes: str = "",
    runtime_tag: str = RUNTIME_TAG,
    migrations: Iterable[str] = (),
) -> tuple[str, bytes]:
    """Return ``(file name, package bytes)``; ``files`` maps posix paths to content."""
    version_tuple(version)
    for name in files:
        _safe_relative(name)
    if APP_ENTRY not in files:
        raise PackageError(f"app 包缺少入口 {APP_ENTRY}")
    manifest = {
        "format": PACKAGE_FORMAT,
        "kind": "app",
        "id": "app",
        "version": version,
        "requires": {"runtime": runtime_tag},
        "notes": notes,
        "migrations": list(migrations),
        "files": {name: _sha256(data) for name, data in sorted(files.items())},
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    signature = sign_manifest(manifest_bytes, private_key_pem)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("package.json", manifest_bytes)
        archive.writestr("package.sig", json.dumps(signature).encode("utf-8"))
        for name, data in sorted(files.items()):
            archive.writestr(f"files/{name}", data)
    return f"vse-app-{version}{PACKAGE_SUFFIX}", buffer.getvalue()


# ── verify ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class VerifiedApp:
    version: str
    notes: str
    runtime: str
    key_id: str
    migrations: tuple[str, ...]
    files: Mapping[str, bytes] = field(repr=False)


def peek_manifest(data: bytes) -> dict[str, Any] | None:
    """Unverified ``package.json`` (only for routing and ordering; never trust its content)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            manifest = json.loads(archive.read("package.json"))
    except (zipfile.BadZipFile, KeyError, ValueError, json.JSONDecodeError):
        return None
    return manifest if isinstance(manifest, dict) else None


def peek_format(data: bytes) -> int | None:
    """Unverified ``package.json`` format number, only for routing to an installer."""
    manifest = peek_manifest(data)
    try:
        return int(manifest.get("format")) if manifest else None
    except (TypeError, ValueError):
        return None


def verify_app_package(data: bytes, keys: Mapping[str, bytes], *, runtime_tag: str = RUNTIME_TAG) -> VerifiedApp:
    """Verify signature, manifest and every file; any defect raises :class:`PackageError`."""
    try:
        return _verify_app_package(data, keys, runtime_tag=runtime_tag)
    except PackageError:
        raise
    except (zipfile.BadZipFile, zlib.error, EOFError, OSError, KeyError, ValueError, TypeError, AttributeError):
        # 下载不完整、传输中损坏：zip/deflate 层面的错误也必须变成可读的拒绝原因。
        raise PackageError("更新包已损坏（可能没有下载完整），请重新下载") from None


def _verify_app_package(data: bytes, keys: Mapping[str, bytes], *, runtime_tag: str) -> VerifiedApp:
    if len(data) > _MAX_PACKAGE_BYTES:
        raise PackageError("更新包过大")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise PackageError("不是有效的更新包（zip 格式错误）") from None
    with archive:
        infos = archive.infolist()
        if len(infos) > _MAX_FILES + 2:
            raise PackageError("更新包文件数量过多")
        if sum(info.file_size for info in infos) > _MAX_UNPACKED_BYTES:
            raise PackageError("更新包解压后过大")
        names = {info.filename for info in infos if not info.is_dir()}
        for name in names:
            _safe_relative(name)
        if "package.json" not in names or "package.sig" not in names:
            raise PackageError("更新包缺少 package.json 或 package.sig")
        manifest_bytes = archive.read("package.json")
        try:
            sig = json.loads(archive.read("package.sig"))
        except json.JSONDecodeError:
            raise PackageError("package.sig 无法解析") from None
        key_id = _verify_signature(manifest_bytes, sig, keys)
        # 只有签名通过后才解析清单内容。
        manifest = json.loads(manifest_bytes)
        if manifest.get("format") != PACKAGE_FORMAT or manifest.get("kind") != "app":
            raise PackageError("这不是程序更新包（可能是插件包）")
        version = str(manifest.get("version") or "")
        try:
            version_tuple(version)
        except ValueError as exc:
            raise PackageError(str(exc)) from None
        runtime = str((manifest.get("requires") or {}).get("runtime") or "")
        if runtime != runtime_tag:
            raise PackageError(f"更新包需要运行环境 {runtime}，当前为 {runtime_tag}，请先安装新的运行环境包")
        listed = manifest.get("files")
        if not isinstance(listed, dict) or APP_ENTRY not in listed:
            raise PackageError("更新包清单缺少文件列表或程序入口")
        payload = {name[len("files/"):] for name in names if name.startswith("files/")}
        extra = names - {"package.json", "package.sig"} - {f"files/{n}" for n in payload}
        if extra or payload != set(listed):
            raise PackageError("更新包内容与签名清单不一致")
        files: dict[str, bytes] = {}
        for relative, digest in listed.items():
            content = archive.read(f"files/{_safe_relative(relative)}")
            if _sha256(content) != digest:
                raise PackageError(f"文件校验失败: {relative}")
            files[relative] = content
    return VerifiedApp(
        version=version,
        notes=str(manifest.get("notes") or ""),
        runtime=runtime,
        key_id=key_id,
        migrations=tuple(str(m) for m in manifest.get("migrations") or ()),
        files=files,
    )


# ── stage ────────────────────────────────────────────────────────────


def stage_app(verified: VerifiedApp, layout: InstallLayout) -> Path:
    """Write a verified package to ``state/staging/app-<v>/``; it installs at the next start."""
    layout.staging_dir.mkdir(parents=True, exist_ok=True)
    final = layout.staging_dir / f"app-{verified.version}"
    temp = layout.staging_dir / f".tmp-app-{verified.version}"
    shutil.rmtree(temp, ignore_errors=True)
    for relative, content in verified.files.items():
        target = temp / "files" / Path(*PurePosixPath(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    meta = {
        "kind": "app",
        "version": verified.version,
        "notes": verified.notes,
        "runtime": verified.runtime,
        "keyId": verified.key_id,
        "migrations": list(verified.migrations),
    }
    (temp / "staged.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(final, ignore_errors=True)
    temp.rename(final)
    return final
