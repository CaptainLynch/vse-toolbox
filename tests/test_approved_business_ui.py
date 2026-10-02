# -*- coding: utf-8 -*-
"""Backend contracts behind the approved business-language UI.

The pages themselves are plugins now (project-overview, settings, scheduled-archive)
with their own tests; these keep the API smoke checks the legacy UI tests carried.
"""
from __future__ import annotations

from pathlib import Path
import pytest

import web.app as web_app


@pytest.fixture()
def client(monkeypatch, tmp_path: Path):
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "approved-ui-test.db"))
    app = web_app.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_phase_metadata_and_milestones_patch_endpoints(client) -> None:
    # Smoke test backend phase PATCH
    get_res = client.get("/api/project-status?phase=VPI-T2")
    assert get_res.status_code == 200
    data = get_res.get_json()["data"]
    current_updated_at = data["phase"]["updatedAt"]

    patch_res = client.patch(
        "/api/project-status/phases/VPI-T2",
        json={
            "displayName": "VPI-T2 阶段主计划（测试更新）",
            "status": "进行中",
            "startDate": "2026-03-01",
            "endDate": "2026-10-30",
            "updatedAt": current_updated_at,
        },
    )
    assert patch_res.status_code == 200
    patch_data = patch_res.get_json()["data"]
    assert patch_data["projectStatus"]["phase"]["displayName"] == "VPI-T2 阶段主计划（测试更新）"


def test_project_status_returns_current_stage(client) -> None:
    # Smoke test API returns currentStage
    res = client.get("/api/project-status?phase=VPI-T2")
    assert res.status_code == 200
    data = res.get_json()["data"]
    assert "currentStage" in data
    assert "→" in data["currentStage"]


def test_deliverable_analysis_endpoints(client) -> None:
    # Smoke test deliverable analysis endpoints
    analysis_res = client.get("/api/project-status/deliverables/VPI-T2-D1/analysis")
    assert analysis_res.status_code == 200
    assert "summary" in analysis_res.get_json()["data"]

    items_res = client.get("/api/project-status/deliverables/VPI-T2-D1/analysis/items")
    assert items_res.status_code == 200
    assert "items" in items_res.get_json()["data"]


def test_scheduled_archive_jobs_and_folders_endpoints(client) -> None:
    # 定时任务页面已迁为插件页；此处只保留后端接口冒烟。
    jobs_res = client.get("/api/scheduled-archive/jobs")
    assert jobs_res.status_code == 200

    folders_res = client.get("/api/scheduled-archive/folders")
    assert folders_res.status_code == 200
    data = folders_res.get_json()["data"]
    assert "current" in data
    assert "folders" in data


def test_settings_api_roundtrip(client) -> None:
    get_res = client.get("/api/settings")
    assert get_res.status_code == 200
    s_data = get_res.get_json()["data"]
    assert "settings" in s_data
    assert "sessions" in s_data

    patch_res = client.patch(
        "/api/settings",
        json={
            "defaultDownloadMinutes": 45,
            "retryCount": 3,
        },
    )
    assert patch_res.status_code == 200
    assert patch_res.get_json()["data"]["settings"]["defaultDownloadMinutes"] == 45
