# -*- coding: utf-8 -*-
"""Focused tests for the VSE Toolbox 定时归档管理 (Scheduled Archive Admin UI).

Covers:
1. Index page integration (legacy overview/deliverables panels plus the plugin host).
2. Unique static IDs and cache-buster versions in dashboard.html.
3. Backend API smoke for /api/scheduled-archive endpoints.

The scheduled-archive page itself is the scheduled-archive plugin; its UI
contracts live in tests/test_plugin_*.py.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import web.app as web_app
from core.db_manager import DatabaseManager
from services.scheduled_archive_admin import ScheduledArchiveAdminService
from services.scheduled_archive_runner import (
    ArchiveJobRunResult,
    ArchiveRunOnceResult,
    ArchiveSyncRunner,
)


@pytest.fixture()
def test_db(monkeypatch, tmp_path: Path) -> DatabaseManager:
    """Provide an isolated temporary SQLite database for web client tests."""
    db_file = tmp_path / "archive_ui_test.db"
    db_instance = DatabaseManager(db_path=db_file)
    db_instance.init_database()
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_instance)
    return db_instance


@pytest.fixture()
def fake_runner() -> MagicMock:
    """Provide a fake runner without external network calls or scheduling loops."""
    runner = MagicMock(spec=ArchiveSyncRunner)
    runner.run_once.return_value = ArchiveRunOnceResult(
        results=(
            ArchiveJobRunResult(
                job_id=1,
                job_key="aras_ewo",
                outcome="completed",
                run_id=101,
                final_state="success",
            ),
        ),
        dry_run=False,
    )
    return runner


@pytest.fixture()
def client(monkeypatch, test_db: DatabaseManager, fake_runner: MagicMock):
    """Provide a Flask test client configured with isolated DB and fake runner."""
    monkeypatch.setattr(
        web_app,
        "ScheduledArchiveAdminService",
        lambda db: ScheduledArchiveAdminService(db, runner_factory=lambda _db: fake_runner),
    )
    app = web_app.create_app()
    # The production app attaches the DPAPI provider; this isolated API test
    # uses arbitrary opaque aliases and a fake runner instead.
    app.extensions["scheduled_archive_admin"].set_credential_provider(None)
    app.config.update(TESTING=True)
    return app.test_client()


# ── 1. Navigation & Static HTML Structure ────────────────────────────────────


def test_dashboard_static_ids_are_unique() -> None:
    """Verify static DOM element IDs in dashboard.html are unique."""
    html_text = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")
    all_ids = re.findall(r'id="([^"]+)"', html_text)
    assert len(all_ids) == len(set(all_ids)), "Duplicate element IDs found in dashboard.html"


# ── 4. End-to-End Endpoint Smoke Test with Client ────────────────────────────


def test_scheduled_archive_api_smoke(client, test_db: DatabaseManager) -> None:
    """Smoke test client interaction with backend API routes."""
    # 1. GET jobs
    resp = client.get("/api/scheduled-archive/jobs")
    assert resp.status_code == 200
    jobs = resp.get_json()["data"]
    assert len(jobs) == 6
    job_map = {j["jobKey"]: j for j in jobs}
    assert "aras_ewo" in job_map
    assert job_map["aras_ewo"]["intervalMinutes"] == 60
    assert "credentialRef" not in job_map["aras_ewo"]

    # 2. PATCH job with write-only alias
    headers = {"Host": "localhost:5000", "Origin": "http://localhost:5000", "Sec-Fetch-Site": "same-origin"}
    environ = {"REMOTE_ADDR": "127.0.0.1", "HTTP_HOST": "localhost:5000"}

    patch_resp = client.patch(
        "/api/scheduled-archive/jobs/aras_ewo",
        json={
            "enabled": True,
            "credentialRef": "vault_alias_test",
            "filters": {"state": "Released"},
            "outputSubdir": "aras/ewo",
            "updatedAt": job_map["aras_ewo"]["updatedAt"],
        },
        headers=headers,
        environ_base=environ,
    )
    assert patch_resp.status_code == 200
    patched_job = patch_resp.get_json()["data"]
    assert patched_job["enabled"] is True
    assert patched_job["credentialConfigured"] is True
    assert "vault_alias_test" not in patch_resp.get_data(as_text=True)

    # 3. POST sync-now
    sync_resp = client.post(
        "/api/scheduled-archive/jobs/aras_ewo/sync-now",
        headers=headers,
        environ_base=environ,
    )
    assert sync_resp.status_code == 200
    assert sync_resp.get_json()["ok"] is True

    # 4. GET runs
    runs_resp = client.get("/api/scheduled-archive/runs?jobKey=aras_ewo")
    assert runs_resp.status_code == 200
    assert isinstance(runs_resp.get_json()["data"], list)

    # 5. GET config-audit
    audit_resp = client.get("/api/scheduled-archive/config-audit?jobKey=aras_ewo")
    assert audit_resp.status_code == 200
    audits = audit_resp.get_json()["data"]
    assert len(audits) >= 1
    assert "vault_alias_test" not in audit_resp.get_data(as_text=True)

    # 6. GET folders
    folders_resp = client.get("/api/scheduled-archive/folders")
    assert folders_resp.status_code == 200
    folders_data = folders_resp.get_json()["data"]
    assert "current" in folders_data
    assert "folders" in folders_data
