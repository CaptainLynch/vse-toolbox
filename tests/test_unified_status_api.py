from __future__ import annotations

from pathlib import Path

import pytest

import web.app as web_app
from core.db_manager import DatabaseManager


@pytest.fixture()
def client(monkeypatch, tmp_path: Path):
    db = DatabaseManager(db_path=tmp_path / "unified_status.db")
    db.init_database()
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db)
    app = web_app.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_unified_status_exposes_ewo_paa_ncr_with_public_states(client):
    response = client.get("/api/project-status/deliverables/VPI-T2-D5/unified-status")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    objects = payload["data"]["objects"]
    assert {item["kind"] for item in objects} == {"ewo", "paa", "ncr"}
    for item in objects:
        assert set(item) >= {
            "kind", "id", "source", "external_key", "auth_state",
            "query_state", "sync_state", "stage", "matched_fields",
            "errors", "last_updated",
        }
        assert "token" not in str(item).lower()
    for item in objects:
        if item["kind"] in {"paa", "ncr"}:
            assert "content" in item
            assert set(item["content"]) >= {"report_type", "sync_state", "last_success_at", "error"}


def test_unified_status_rejects_unknown_deliverable(client):
    response = client.get("/api/project-status/deliverables/UNKNOWN/unified-status")
    assert response.status_code == 404
