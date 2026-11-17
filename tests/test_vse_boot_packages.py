# -*- coding: utf-8 -*-
"""v2 app packages: build/verify roundtrip, rejection paths, staging, discovery."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from vse_boot.discover import find_updates  # noqa: E402
from vse_boot.layout import InstallLayout  # noqa: E402
from vse_boot.packages import (  # noqa: E402
    RUNTIME_TAG,
    PackageError,
    build_app_package,
    key_id_for,
    load_trusted_keys,
    peek_format,
    stage_app,
    verify_app_package,
)

FILES = {"webui.py": b"def main(argv=None):\n    return 0\n", "core/__init__.py": b"", "web/static/a.js": b"x"}


def keypair() -> tuple[bytes, dict[str, bytes]]:
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return pem, {key_id_for(public): public}


@pytest.fixture()
def signer():
    return keypair()


def rezip(data: bytes, mutate) -> bytes:  # type: ignore[no-untyped-def]
    entries = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            entries[info.filename] = archive.read(info.filename)
    mutate(entries)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return out.getvalue()


def test_roundtrip_and_peek(signer) -> None:
    pem, keys = signer
    name, data = build_app_package(FILES, version="2.0.1", private_key_pem=pem, notes="修复", migrations=["m1"])
    assert name == "vse-app-2.0.1.vsepkg"
    assert peek_format(data) == 2
    verified = verify_app_package(data, keys)
    assert (verified.version, verified.notes, verified.migrations, verified.runtime) == ("2.0.1", "修复", ("m1",), RUNTIME_TAG)
    assert dict(verified.files) == FILES


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda e: e.__setitem__("files/webui.py", b"evil"), "文件校验失败"),
        (lambda e: e.__setitem__("files/extra.py", b"x"), "不一致"),
        (lambda e: e.pop("files/core/__init__.py"), "不一致"),
        (lambda e: e.__setitem__("package.json", e["package.json"].replace(b"2.0.1", b"2.0.9")), "签名校验失败"),
        (lambda e: e.__setitem__("files/../escape.py", b"x"), "非法路径"),
        (lambda e: e.pop("package.sig"), "缺少"),
    ],
)
def test_tampering_is_rejected(signer, mutate, message: str) -> None:
    pem, keys = signer
    _, data = build_app_package(FILES, version="2.0.1", private_key_pem=pem)
    with pytest.raises(PackageError, match=message):
        verify_app_package(rezip(data, mutate), keys)


def test_untrusted_key_runtime_mismatch_and_missing_entry(signer) -> None:
    pem, keys = signer
    _, data = build_app_package(FILES, version="2.0.1", private_key_pem=pem)
    with pytest.raises(PackageError, match="不受信任"):
        verify_app_package(data, keypair()[1])
    with pytest.raises(PackageError, match="未配置可信公钥"):
        verify_app_package(data, {})
    with pytest.raises(PackageError, match="运行环境"):
        verify_app_package(data, keys, runtime_tag="cp399")
    with pytest.raises(PackageError, match="入口"):
        build_app_package({"core/x.py": b""}, version="2.0.1", private_key_pem=pem)
    with pytest.raises(PackageError, match="非法路径"):
        build_app_package({**FILES, "C:/x.py": b""}, version="2.0.1", private_key_pem=pem)


def test_stage_writes_complete_directory_then_renames(signer, tmp_path: Path) -> None:
    pem, keys = signer
    layout = InstallLayout(tmp_path).ensure()
    _, data = build_app_package(FILES, version="2.0.1", private_key_pem=pem)
    staged = stage_app(verify_app_package(data, keys), layout)
    assert staged.name == "app-2.0.1"
    assert (staged / "files" / "web" / "static" / "a.js").read_bytes() == b"x"
    assert json.loads((staged / "staged.json").read_text(encoding="utf-8"))["version"] == "2.0.1"
    assert not list(layout.staging_dir.glob(".tmp-*"))


def test_load_trusted_keys_merges_and_skips_missing(signer, tmp_path: Path) -> None:
    import base64

    _, keys = signer
    key_id, public = next(iter(keys.items()))
    path = tmp_path / "keys.json"
    path.write_text(json.dumps({"keys": [{"keyId": key_id, "publicKey": base64.b64encode(public).decode()}]}), encoding="utf-8")
    assert load_trusted_keys([tmp_path / "missing.json", path]) == keys


def test_discovery_offers_newest_valid_app_once_and_ignores_others(signer, tmp_path: Path) -> None:
    pem, keys = signer
    inbox = tmp_path / "Downloads"
    inbox.mkdir()
    for version, suffix in (("2.0.1", ""), ("2.0.2", ""), ("2.0.2", "(1)"), ("1.9.0", "")):
        _, data = build_app_package(FILES, version=version, private_key_pem=pem, notes=f"n{version}")
        (inbox / f"vse-app-{version}{suffix}.vsepkg").write_bytes(data)
    _, foreign = build_app_package(FILES, version="9.9.9", private_key_pem=keypair()[0])
    (inbox / "foreign.vsepkg").write_bytes(foreign)
    (inbox / "plugin.vsepkg").write_bytes(rezip(foreign, lambda e: e.__setitem__("package.json", b'{"format": 1}')))
    (inbox / "notes.txt").write_text("not a package", encoding="utf-8")

    found = find_updates([inbox, tmp_path / "missing"], keys, current_app_version="2.0.1")

    assert [(c.kind, c.version) for c in found] == [("app", "2.0.2"), ("plugin", None)]
    assert found[0].notes == "n2.0.2"


def test_corrupted_download_is_a_readable_rejection(signer) -> None:
    pem, keys = signer
    _, data = build_app_package({**FILES, "web/static/big.js": b"x" * 50000}, version="2.0.1", private_key_pem=pem)
    for position in (len(data) // 3, len(data) // 2, len(data) - 30):
        broken = bytearray(data)
        broken[position] ^= 0xFF
        with pytest.raises(PackageError):
            verify_app_package(bytes(broken), keys)
    with pytest.raises(PackageError):
        verify_app_package(data[: len(data) // 2], keys)  # 没下载完
