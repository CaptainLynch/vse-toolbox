from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

import web.app as web_app
from core.db_manager import DatabaseManager
from services.project_status_deliverable_analysis import (
    ProjectStatusDeliverableAnalysisService,
)


@pytest.fixture()
def client_and_db(monkeypatch, tmp_path: Path):
    db = DatabaseManager(tmp_path / "analysis-api.db")
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db)
    app = web_app.create_app(project_status_clock=lambda: date(2026, 8, 23))
    app.config.update(TESTING=True)
    return app.test_client(), db


def test_phase_metadata_update_and_dynamic_today(client_and_db) -> None:
    client, _ = client_and_db
    before = client.get("/api/project-status").get_json()["data"]
    assert before["phase"]["today"] == "2026-08-23"
    assert before["phase"]["displayName"] == "VPI-T2 主计划时间轴"
    assert before["phase"]["riskCount"] == 3
    assert before["summary"]["risk"] == "EWO 定点流程已逾期 1 天"

    response = client.patch(
        "/api/project-status/phases/VPI-T2",
        json={
            "displayName": "VPI-T2 整车交付主计划",
            "status": "进行中",
            "startDate": "2026-04-08",
            "endDate": "2026-09-05",
            "updatedAt": before["phase"]["updatedAt"],
        },
    )
    assert response.status_code == 200
    phase = response.get_json()["data"]["projectStatus"]["phase"]
    assert phase["displayName"] == "VPI-T2 整车交付主计划"
    assert phase["endDate"] == "2026-09-05"

    stale = client.patch(
        "/api/project-status/phases/VPI-T2",
        json={
            "displayName": "stale",
            "status": "进行中",
            "startDate": "2026-04-08",
            "endDate": "2026-09-05",
            "updatedAt": before["phase"]["updatedAt"],
        },
    )
    assert stale.status_code == 409


def test_analysis_api_returns_cache_departments_trend_and_warnings(client_and_db) -> None:
    client, db = client_and_db
    service = ProjectStatusDeliverableAnalysisService(
        db,
        clock=lambda: date(2026, 8, 23),
    )
    service.publish(
        "VPI-T2-D5",
        77,
        [
            {
                "id": "task-1",
                "name": "冻结发布单确认",
                "department": "质量科",
                "owner": "赵岩",
                "status": "进行中",
                "dueDate": "2026-08-18",
            },
            {
                "id": "task-2",
                "name": "A 面数据确认",
                "department": "车身设计科",
                "owner": "陈璇",
                "status": "进行中",
                "dueDate": "2026-08-25",
            },
            {
                "id": "task-3",
                "name": "审批关闭",
                "department": "项目管理科",
                "status": "已完成",
                "dueDate": "2026-08-20",
            },
        ],
        snapshot_at="2026-08-23T06:00:00Z",
    )

    analysis = client.get(
        "/api/project-status/deliverables/VPI-T2-D5/analysis"
    )
    assert analysis.status_code == 200
    data = analysis.get_json()["data"]
    assert data["summary"]["total"] == 3
    assert data["summary"]["completed"] == 1
    assert data["departments"]["质量科"]["incomplete"] == 1
    assert len(data["trend"]) == 1

    overdue = client.get(
        "/api/project-status/deliverables/VPI-T2-D5/analysis/items?alert=overdue"
    )
    assert overdue.status_code == 200
    assert overdue.get_json()["data"]["items"][0]["days"] == 5

    invalid = client.get(
        "/api/project-status/deliverables/VPI-T2-D5/analysis/items?alert=unknown"
    )
    assert invalid.status_code == 422
