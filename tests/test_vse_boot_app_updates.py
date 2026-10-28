# -*- coding: utf-8 -*-
"""Settings plugin「程序更新」routes on top of vse_boot.api (v2 launcher)."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

import web.app as web_app  # noqa: E402
from tests.test_vse_boot_packages import FILES, keypair  # noqa: E402
from vse_boot import api  # noqa: E402
from vse_boot.layout import InstallLayout  # noqa: E402
from vse_boot.packages import build_app_package  # noqa: E402
from vse_boot.state import BootState  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture()
def env(monkeypatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    pem, keys = keypair()
    key_file = tmp_path / "runtime_keys.json"
    key_file.write_text(
        json.dumps({"keys": [{"keyId": k, "publicKey": base64.b64encode(v).decode()} for k, v in keys.items()]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(api, "RUNTIME_KEYS", key_file)
    root = tmp_path / "VSE-Toolbox"
    layout = InstallLayout(root).ensure()
    layout.app_dir("2.0.0").mkdir(parents=True)
    state = BootState(layout)
    state.app["current"] = "2.0.0"
    state.save()
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    monkeypatch.setattr(api, "watch_dirs", lambda _layout: [downloads])
    monkeypatch.setenv("VSE_INSTALL_ROOT", str(root))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "data" / "host.db"))
    app = web_app.create_app(plugin_dirs=[REPO / "plugins"], plugin_only=["settings"])
    app.config.update(TESTING=True)
    return app.test_client(), layout, downloads, pem


def package(pem: bytes, version: str) -> bytes:
    return build_app_package(FILES, version=version, private_key_pem=pem, notes=f"说明 {version}")[1]


def test_lists_newer_packages_and_installs_one_then_restarts(env) -> None:  # type: ignore[no-untyped-def]
    client, layout, downloads, pem = env
    (downloads / "vse-app-2.0.1.vsepkg").write_bytes(package(pem, "2.0.1"))
    (downloads / "vse-app-1.9.0.vsepkg").write_bytes(package(pem, "1.9.0"))
    data = client.get("/api/p/settings/app-updates").get_json()["data"]
    assert data["managed"] is True and data["current"] == "2.0.0"
    assert [a["version"] for a in data["available"]] == ["2.0.1"]

    assert client.post("/api/p/settings/app-updates/install", json={"file": "../../etc/passwd"}).status_code == 404
    response = client.post("/api/p/settings/app-updates/install", json={"file": "vse-app-2.0.1.vsepkg"})
    assert response.status_code == 200 and response.get_json()["data"]["version"] == "2.0.1"
    assert client.get("/api/p/settings/app-updates").get_json()["data"]["staged"] == ["2.0.1"]

    assert client.post("/api/p/settings/app-updates/restart").status_code == 200
    assert layout.restart_request.exists()


def test_upload_rejects_tampered_and_accepts_valid(env) -> None:  # type: ignore[no-untyped-def]
    client, layout, _downloads, pem = env
    good = package(pem, "2.0.2")
    bad = bytearray(good)
    bad[len(bad) // 2] ^= 0xFF
    reply = client.post(
        "/api/p/settings/app-updates/upload",
        data={"file": (io.BytesIO(bytes(bad)), "x.vsepkg")},
        content_type="multipart/form-data",
    )
    assert reply.status_code == 400 and reply.get_json()["error"]["type"] == "PackageRejected"
    reply = client.post(
        "/api/p/settings/app-updates/upload",
        data={"file": (io.BytesIO(good), "x.vsepkg")},
        content_type="multipart/form-data",
    )
    assert reply.status_code == 200 and api.staged_versions(layout) == ["2.0.2"]


def test_mutations_need_local_requests(env) -> None:  # type: ignore[no-untyped-def]
    client, layout, _downloads, _pem = env
    reply = client.post("/api/p/settings/app-updates/restart", environ_base={"REMOTE_ADDR": "10.0.0.8"})
    assert reply.status_code == 403
    assert not layout.restart_request.exists()


def test_rollback_without_previous_is_refused(env) -> None:  # type: ignore[no-untyped-def]
    client, _layout, _downloads, _pem = env
    assert client.post("/api/p/settings/app-updates/rollback").status_code == 409


def test_source_run_reports_unmanaged(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client, _layout, _downloads, _pem = env
    monkeypatch.delenv("VSE_INSTALL_ROOT")
    assert client.get("/api/p/settings/app-updates").get_json()["data"] == {"managed": False}
    assert client.post("/api/p/settings/app-updates/restart").status_code == 409
