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
    # 主计划名称即车型锚点，种子默认 F610S。
    assert before["phase"]["displayName"] == "F610S"
    assert before["phase"]["riskCount"] == 3
    assert before["summary"]["risk"] == "EWO 流程已逾期 1 天"

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


def test_analysis_car_type_anchor_falls_back_to_phase_display_name(client_and_db) -> None:
    """未显式传 carType 时，分析接口回显主计划名称作为车型锚点，且跟随手动修改。"""
    client, _ = client_and_db
    analysis = client.get("/api/project-status/deliverables/VPI-T2-D3/analysis")
    assert analysis.status_code == 200
    assert analysis.get_json()["data"]["carType"] == "F610S"

    items = client.get("/api/project-status/deliverables/VPI-T2-D3/analysis/items")
    assert items.status_code == 200
    assert items.get_json()["data"]["carType"] == "F610S"

    before = client.get("/api/project-status").get_json()["data"]
    renamed = client.patch(
        "/api/project-status/phases/VPI-T2",
        json={
            "displayName": "G610M",
            "status": "进行中",
            "startDate": "2026-04-08",
            "endDate": "2026-09-05",
            "updatedAt": before["phase"]["updatedAt"],
        },
    )
    assert renamed.status_code == 200

    renamed_analysis = client.get("/api/project-status/deliverables/VPI-T2-D3/analysis")
    assert renamed_analysis.get_json()["data"]["carType"] == "G610M"

    explicit = client.get(
        "/api/project-status/deliverables/VPI-T2-D3/analysis?carType=F710S"
    )
    # 显式参数仍优先于锚点回退。
    assert explicit.get_json()["data"]["carType"] == "F710S"


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


def test_analysis_api_accepts_repeated_department_and_stage_filters(client_and_db) -> None:
    client, db = client_and_db
    service = ProjectStatusDeliverableAnalysisService(db, clock=lambda: date(2026, 8, 23))
    service.publish(
        "VPI-T2-D3",
        88,
        [
            {"_no": "EWO-1", "_rsp_smt": "车身科", "state": "IMPL", "_required_date": "2026-08-20"},
            {"_no": "EWO-2", "_rsp_smt": "内饰科", "state": "CLOSE", "_required_date": "2026-08-20"},
            {"_no": "EWO-3", "_rsp_smt": "外饰科", "state": "OPEN", "_required_date": "2026-08-20"},
        ],
        source_type="aras",
        snapshot_at="2026-08-23T00:00:00Z",
    )

    response = client.get(
        "/api/project-status/deliverables/VPI-T2-D3/analysis/items"
        "?departments=%E8%BD%A6%E8%BA%AB%E7%A7%91&departments=%E5%86%85%E9%A5%B0%E7%A7%91"
        "&stages=impl&stages=close"
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["total"] == 2
    assert {row["stage"] for row in data["items"]} == {"impl", "close"}

    unknown = client.get(
        "/api/project-status/deliverables/VPI-T2-D3/analysis/items?departments=%E6%9C%AA%E7%9F%A5%E7%A7%91%E5%AE%A4"
    )
    assert unknown.status_code == 200
    assert unknown.get_json()["data"]["total"] == 0

    invalid_stage = client.get(
        "/api/project-status/deliverables/VPI-T2-D3/analysis/items?stages=not-a-stage"
    )
    assert invalid_stage.status_code == 422


def test_analysis_api_serializes_pending_signer_lines_and_close_alert(client_and_db) -> None:
    """API 输出每条一行 ROLE:person；CLOSE 永远无逾期提醒；stage 保持小写规范值。"""
    client, db = client_and_db
    service = ProjectStatusDeliverableAnalysisService(db, clock=lambda: date(2026, 8, 23))
    service.publish(
        "VPI-T2-D3",
        91,
        [
            {
                "_no": "EWO-SIGN",
                "_rsp_smt": "车身科",
                "state": "IMPL",
                "_required_date": "2026-08-20",
                "当前阶段未签署的角色&人员": "PE:张三;LEADER:李四，SQE:赵六",
            },
            {
                "_no": "EWO-CLOSE",
                "_rsp_smt": "车体科",
                "state": "CLOSE",
                "_required_date": "2026-08-01",
            },
        ],
        source_type="aras",
        snapshot_at="2026-08-23T00:00:00Z",
    )

    response = client.get("/api/project-status/deliverables/VPI-T2-D3/analysis/items?stage=all")
    assert response.status_code == 200
    data = response.get_json()["data"]
    by_number = {row["itemNumber"]: row for row in data["items"]}
    assert by_number["EWO-SIGN"]["pendingSigners"] == "PE:张三\nLEADER:李四\nSQE:赵六"
    # CLOSE 是流程终点：无提醒（前端据此显示 未超期），阶段值保持小写
    assert by_number["EWO-CLOSE"]["alertType"] is None
    assert by_number["EWO-CLOSE"]["stage"] == "close"
