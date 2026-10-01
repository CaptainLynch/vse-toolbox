# -*- coding: utf-8 -*-
"""settings plugin: manifest/nav contract, module assets, and the legacy
/api/settings endpoints the page relies on (shapes the frontend reads)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import web.app as web_app

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO_ROOT / "plugins" / "settings"
MODULES = ("general.js", "client.js", "error-card.js", "settings-form.js", "sessions.js", "service-status.js")


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "settings-plugin.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=["settings"])
    app.config.update(TESTING=True)
    return app.test_client()


def test_plugin_loads_with_general_module_page(client) -> None:
    data = client.get("/api/host/manifest").get_json()["data"]
    record = next(p for p in data["plugins"] if p["id"] == "settings")
    assert record["status"] == "loaded", record.get("error")
    assert {"id": "general", "kind": "module", "module": "general.js"}.items() <= record["pages"][0].items()
    nav = next(item for item in data["nav"] if item["plugin"] == "settings")
    assert nav["page"] == "general"
    assert nav["title"] == "设置（新）"
    assert nav["order"] == 90


@pytest.mark.parametrize("name", MODULES)
def test_static_modules_served_as_javascript(client, name: str) -> None:
    response = client.get(f"/plugins/settings/static/{name}")
    assert response.status_code == 200
    assert response.mimetype == "text/javascript"


def test_stylesheet_served(client) -> None:
    response = client.get("/plugins/settings/static/settings.css")
    assert response.status_code == 200
    assert response.mimetype == "text/css"


def test_module_imports_resolve_to_shipped_files() -> None:
    static = PLUGIN_DIR / "static"
    for name in MODULES:
        source = (static / name).read_text(encoding="utf-8")
        for target in re.findall(r'from "\./([^"]+)"', source):
            assert (static / target).is_file(), f"{name} imports missing {target}"
        assert "/static/app.js" not in source
        # 凭据只能放请求体：不得出现在 URL/查询串，也不得写日志。
        assert "console.log" not in source
        assert "?password" not in source and "password=" not in source


def test_settings_roundtrip_and_validation_shape(client, tmp_path: Path) -> None:
    body = client.get("/api/settings").get_json()
    assert body["ok"] is True
    data = body["data"]
    assert {"settings", "sessions", "credentialVaultConfigured", "excelService"} <= set(data)
    assert set(data["sessions"]) == {"aras", "tdc"}

    target = tmp_path / "archive"
    target.mkdir()
    saved = client.patch("/api/settings", json={"archiveDirectory": str(target), "retryCount": 3}).get_json()
    assert saved["ok"] is True
    again = client.get("/api/settings").get_json()["data"]["settings"]
    assert again["archiveDirectory"] == str(target.resolve())
    assert again["retryCount"] == 3

    bad = client.patch("/api/settings", json={"excelDirectory": "relative/dir", "retryCount": 99})
    assert bad.status_code == 422
    fields = bad.get_json()["error"]["fields"]
    assert set(fields) == {"excelDirectory", "retryCount"}


def test_native_picker_unavailable_returns_503(client) -> None:
    response = client.post("/api/settings/folders/native", json={"path": ""})
    assert response.status_code == 503


def test_domain_login_requires_credentials_without_echoing_them(client) -> None:
    response = client.post("/api/settings/domain-login", json={"username": "", "password": "s3cret-value"})
    assert response.status_code == 422
    assert "s3cret-value" not in response.get_data(as_text=True)
