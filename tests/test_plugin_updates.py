# -*- coding: utf-8 -*-
"""Signed plugin packages: verification, staging, activation on restart and rollback."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

import host.updates as updates_module
import web.app as web_app
from host.updates import PackageError, PluginUpdates, build_package, verify_package

cryptography = pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402


def _keypair() -> tuple[bytes, dict[str, bytes]]:
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return pem, {updates_module.key_id_for(public): public}


def _plugin(root: Path, version: str, *, greeting: str = "hi", broken: bool = False) -> Path:
    plugin_dir = root / f"demo-{version}"
    (plugin_dir / "static").mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(json.dumps({
        "id": "demo", "name": "演示", "version": version, "hostApi": ">=1,<2",
        "pages": [{"id": "main", "title": "演示"}], "nav": [{"title": "演示", "page": "main"}],
    }), encoding="utf-8")
    body = "    raise RuntimeError('boom')\n" if broken else (
        "    @host.blueprint.get('/hello')\n"
        "    def hello():\n"
        f"        return host.context.json_ok({{'greeting': {greeting!r}}})\n"
    )
    (plugin_dir / "backend.py").write_text("def register(host):\n" + body, encoding="utf-8")
    (plugin_dir / "static" / "page.js").write_text("export default () => null;\n", encoding="utf-8")
    (plugin_dir / "__pycache__").mkdir()
    (plugin_dir / "__pycache__" / "backend.cpython-311.pyc").write_bytes(b"junk")
    return plugin_dir


def _rezip(data: bytes, mutate) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(data))
    entries = {name: src.read(name) for name in src.namelist()}
    mutate(entries)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return out.getvalue()


@pytest.fixture()
def signer():
    return _keypair()


def test_build_and_verify_roundtrip(tmp_path: Path, signer) -> None:
    pem, keys = signer
    name, data = build_package(_plugin(tmp_path, "1.2.0"), pem)
    assert name == "demo-1.2.0.vsepkg"
    package = verify_package(data, keys)
    assert (package.id, package.version) == ("demo", "1.2.0")
    assert set(package.files) == {"plugin.json", "backend.py", "static/page.js"}  # 缓存目录不打包


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda e: e.__setitem__("files/backend.py", b"def register(host): pass\n"), "文件校验失败"),
        (lambda e: e.__setitem__("package.json", e["package.json"].replace(b"1.2.0", b"9.9.9")), "签名校验失败"),
        (lambda e: e.__setitem__("files/extra.py", b"x = 1\n"), "不一致"),
        (lambda e: e.__setitem__("files/../evil.py", b"x = 1\n"), "非法路径"),
        (lambda e: e.pop("package.sig"), "缺少"),
    ],
)
def test_tampered_packages_are_rejected(tmp_path: Path, signer, mutate, message: str) -> None:
    pem, keys = signer
    _, data = build_package(_plugin(tmp_path, "1.2.0"), pem)
    with pytest.raises(PackageError, match=message):
        verify_package(_rezip(data, mutate), keys)


def test_untrusted_or_missing_keys_are_rejected(tmp_path: Path, signer) -> None:
    pem, _ = signer
    _, data = build_package(_plugin(tmp_path, "1.2.0"), pem)
    with pytest.raises(PackageError, match="不受信任"):
        verify_package(data, _keypair()[1])
    with pytest.raises(PackageError, match="未配置可信公钥"):
        verify_package(data, {})
    with pytest.raises(PackageError, match="zip"):
        verify_package(b"not a zip", _keypair()[1])


def test_incompatible_host_api_is_rejected(tmp_path: Path, signer) -> None:
    pem, keys = signer
    plugin_dir = _plugin(tmp_path, "1.2.0")
    manifest = json.loads((plugin_dir / "plugin.json").read_text(encoding="utf-8"))
    manifest["hostApi"] = ">=2,<3"
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    _, data = build_package(plugin_dir, pem)
    with pytest.raises(PackageError, match="请先升级宿主"):
        verify_package(data, keys)


def test_stage_apply_and_rollback_state(tmp_path: Path, signer) -> None:
    pem, keys = signer
    updates = PluginUpdates(tmp_path / "updates", trusted_keys=keys)
    updates.stage(build_package(_plugin(tmp_path, "1.1.0"), pem)[1], current_version="1.0.0")
    assert updates.pending() == [{"id": "demo", "version": "1.1.0"}]
    assert updates.active_dirs() == {}  # 导入只暂存，不影响正在运行的版本
    assert updates.apply_pending() == [{"id": "demo", "version": "1.1.0"}]
    assert updates.active_dirs()["demo"].name == "1.1.0"

    with pytest.raises(PackageError, match="不高于当前版本"):
        updates.stage(build_package(_plugin(tmp_path / "again", "1.1.0"), pem)[1], current_version="1.1.0")

    updates.stage(build_package(_plugin(tmp_path, "1.2.0"), pem)[1], current_version="1.1.0")
    updates.apply_pending()
    assert updates.read_state()["plugins"]["demo"] == {"version": "1.2.0", "previous": "1.1.0"}
    assert updates.rollback("demo", reason="test") == "1.1.0"
    assert updates.active_dirs()["demo"].name == "1.1.0"
    assert updates.rollback("demo", reason="test") is None  # 再退一步回到随包内置版本
    assert updates.active_dirs() == {}
    kinds = [event["kind"] for event in updates.read_state()["events"]]
    assert kinds.count("rolled_back") == 2


# ── create_app integration ───────────────────────────────────────────


@pytest.fixture()
def host_env(monkeypatch, tmp_path: Path, signer):  # type: ignore[no-untyped-def]
    pem, keys = signer
    key_file = tmp_path / "trusted_keys.json"
    key_file.write_text(json.dumps({"keys": [
        {"keyId": k, "publicKey": __import__("base64").b64encode(v).decode()} for k, v in keys.items()
    ]}), encoding="utf-8")
    monkeypatch.setattr(updates_module, "TRUSTED_KEYS_FILE", key_file)
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "data" / "host.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    _plugin(bundled, "1.0.0", greeting="bundled")

    def start():
        app = web_app.create_app(plugin_dirs=[bundled])
        app.config.update(TESTING=True)
        return app.test_client()

    return start, pem, tmp_path


def _upload(client, data: bytes, **headers):
    return client.post(
        "/api/host/updates/import",
        data={"file": (io.BytesIO(data), "demo.vsepkg")},
        content_type="multipart/form-data",
        headers=headers,
    )


def test_import_activates_after_restart_and_broken_update_rolls_back(host_env) -> None:
    start, pem, tmp_path = host_env
    client = start()
    assert client.get("/api/p/demo/hello").get_json()["data"]["greeting"] == "bundled"

    response = _upload(client, build_package(_plugin(tmp_path / "v2", "1.1.0", greeting="v2"), pem)[1])
    body = response.get_json()
    assert response.status_code == 200, body
    assert body["data"]["previous"] == "1.0.0"
    assert "重启" in body["data"]["message"]
    assert client.get("/api/p/demo/hello").get_json()["data"]["greeting"] == "bundled"  # 不热替换

    client = start()  # 重启
    assert client.get("/api/p/demo/hello").get_json()["data"]["greeting"] == "v2"
    plugins = {p["id"]: p for p in client.get("/api/host/updates").get_json()["data"]["plugins"]}
    assert plugins["demo"]["source"] == "installed" and plugins["demo"]["version"] == "1.1.0"

    _upload(client, build_package(_plugin(tmp_path / "v3", "1.2.0", broken=True), pem)[1])
    client = start()  # 新版本启动失败 → 自动切回 1.1.0
    assert client.get("/api/p/demo/hello").get_json()["data"]["greeting"] == "v2"
    status = client.get("/api/host/updates").get_json()["data"]
    assert status["active"]["demo"]["version"] == "1.1.0"
    assert status["events"][0]["kind"] == "rolled_back"
    assert "boom" in status["events"][0]["reason"]

    rollback = client.post("/api/host/updates/demo/rollback")
    assert rollback.status_code == 200
    client = start()
    assert client.get("/api/p/demo/hello").get_json()["data"]["greeting"] == "bundled"


def test_import_rejections_and_local_guard(host_env) -> None:
    start, pem, tmp_path = host_env
    client = start()
    older = build_package(_plugin(tmp_path / "old", "1.0.0"), pem)[1]
    rejected = _upload(client, older)
    assert rejected.status_code == 422
    assert "不高于当前版本" in rejected.get_json()["error"]["message"]

    _, foreign = _keypair()
    _, untrusted_pem = None, _keypair()[0]
    unsigned = build_package(_plugin(tmp_path / "x", "2.0.0"), untrusted_pem)[1]
    assert _upload(client, unsigned).status_code == 422

    blocked = _upload(
        client,
        build_package(_plugin(tmp_path / "y", "2.0.0"), pem)[1],
        **{"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"},
    )
    assert blocked.status_code == 403
    assert client.get("/api/host/updates").get_json()["data"]["pending"] == []

    assert client.post("/api/host/updates/demo/discard").status_code == 404
