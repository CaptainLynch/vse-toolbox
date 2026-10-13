# -*- coding: utf-8 -*-
"""Tests for auto-sync deliverable by car model anchor (以车型名称为锚点自动同步交付物)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from core.db_manager import DatabaseManager, SyncBindingNotReadyError
from services.project_status_sync_runner import (
    ConnectorRegistry,
    ProjectStatusSyncRunner,
)
from services.project_status_updates import (
    ConnectorCandidate,
    ConnectorSnapshot,
    ProjectStatusUpdateService,
)
import web.app as web_app


class DummyConnector:
    """Mock connector returning predetermined application rows for testing."""

    def __init__(self, rows: list[dict[str, str]] | None = None) -> None:
        self.rows = rows or [
            {"incident": "1001", "documentNo": "3D-01", "department": "车身科", "applicant": "张三", "status": "已完成", "latestApproveLog": "通过"},
            {"incident": "1002", "documentNo": "3D-02", "department": "内饰科", "applicant": "李四", "status": "审批中", "latestApproveLog": "审核中"},
        ]

    def collect(self, context) -> ConnectorSnapshot:
        fetched = "2026-10-09T10:00:00Z"
        version = "v1"
        candidate = ConnectorCandidate(
            external_key=context.external_key or "agg_anchor",
            external_version=version,
            field_values={"note": "测试聚合备注"},
            fetched_at=fetched,
        )
        return ConnectorSnapshot(
            match_state="matched",
            candidates=(candidate,),
            external_version=version,
            fetched_at=fetched,
            expected_deliverable_updated_at=context.expected_deliverable_updated_at,
            analysis_rows=self.rows,
        )


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(tmp_path / "test_anchor.db")
    manager.init_database()
    return manager


@pytest.fixture()
def runner(db: DatabaseManager) -> ProjectStatusSyncRunner:
    update_service = ProjectStatusUpdateService(db)
    registry = ConnectorRegistry()
    registry.register("tdc", DummyConnector())
    registry.register("aras", DummyConnector())
    return ProjectStatusSyncRunner(db, update_service, registry)


def test_service_sync_by_car_type_validation(runner: ProjectStatusSyncRunner) -> None:
    # 1. Empty / whitespace car_type
    with pytest.raises(ValueError, match="不能为空"):
        runner.sync_by_car_type("VPI-T2-D5", "")
    with pytest.raises(ValueError, match="不能为空"):
        runner.sync_by_car_type("VPI-T2-D5", "   ")

    # 2. Too long car_type (> 80 chars)
    with pytest.raises(ValueError, match="不能超过 80 个字符"):
        runner.sync_by_car_type("VPI-T2-D5", "A" * 85)

    # 3. Control characters
    with pytest.raises(ValueError, match="包含非法控制字符"):
        runner.sync_by_car_type("VPI-T2-D5", "F610M\n")

    # 4. Unknown deliverable
    with pytest.raises(KeyError):
        runner.sync_by_car_type("NON-EXISTENT-ID", "F610M")

    # 5. Manual-only deliverable
    with pytest.raises(SyncBindingNotReadyError, match="手工维护"):
        runner.sync_by_car_type("VPI-T2-D1", "F610M")


def test_service_sync_by_car_type_tdc_data_model(db: DatabaseManager, runner: ProjectStatusSyncRunner) -> None:
    res = runner.sync_by_car_type("VPI-T2-D5", "F610M")
    assert res["deliverableId"] == "VPI-T2-D5"
    assert res["carType"] == "F610M"
    assert res["matchRule"]["reportType"] == "data_model"
    assert res["matchRule"]["projectModel"] == "F610M"
    assert res["matchRule"]["aggregate"] is True
    assert res["outcome"] == "completed"

    # Verify policy in DB is updated and enabled
    policy = db.get_project_status_update_policy("VPI-T2-D5")
    assert policy is not None
    binding = policy["binding"]
    assert binding["mode"] == "automatic"
    assert binding["enabled"] == 1
    rule = json.loads(binding["match_rule_json"])
    assert rule["projectModel"] == "F610M"

    # Verify analysis cache published
    snapshots = db.list_project_status_analysis_snapshots("VPI-T2-D5", 5)
    assert len(snapshots) >= 1
    assert snapshots[0]["total_count"] == 2
    assert snapshots[0]["completed_count"] == 1


def test_service_sync_by_car_type_tdc_sor(db: DatabaseManager, runner: ProjectStatusSyncRunner) -> None:
    res = runner.sync_by_car_type("VPI-T2-D2", "E262S")
    assert res["deliverableId"] == "VPI-T2-D2"
    assert res["carType"] == "E262S"
    assert res["matchRule"]["reportType"] == "sor"
    assert res["matchRule"]["carTypeProject"] == "E262S"
    assert res["matchRule"]["aggregate"] is True
    assert res["outcome"] == "completed"


def test_service_sync_by_car_type_aras_ewo(db: DatabaseManager, runner: ProjectStatusSyncRunner) -> None:
    res = runner.sync_by_car_type("VPI-T2-D3", "F710S")
    assert res["deliverableId"] == "VPI-T2-D3"
    assert res["carType"] == "F710S"
    assert res["matchRule"]["reportType"] == "ewo"
    assert res["matchRule"]["projectCode"] == "F710S"
    assert res["matchRule"]["modelInfo"] == "F710S"
    assert res["matchRule"]["aggregate"] is True


@pytest.fixture()
def client(monkeypatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    db_instance = DatabaseManager(tmp_path / "test_api_anchor.db")
    db_instance.init_database()
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_instance)

    # Monkeypatch create_production_registry to return dummy connectors
    def mock_registry():
        reg = ConnectorRegistry()
        reg.register("tdc", DummyConnector())
        reg.register("aras", DummyConnector())
        return reg

    monkeypatch.setattr("web.app.create_production_registry", mock_registry)

    app = web_app.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_api_sync_by_car_type_endpoint(client) -> None:
    # 1. Happy path: TDC Data Model VPI-T2-D5
    res = client.post(
        "/api/project-status/deliverables/VPI-T2-D5/sync-by-car-type",
        json={"carType": "F610M"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body["data"]["carType"] == "F610M"
    assert body["data"]["deliverableId"] == "VPI-T2-D5"

    # 2. Missing carType -> 422
    assert client.post("/api/project-status/deliverables/VPI-T2-D5/sync-by-car-type", json={}).status_code == 422
    assert client.post("/api/project-status/deliverables/VPI-T2-D5/sync-by-car-type", json={"carType": ""}).status_code == 422
    assert client.post("/api/project-status/deliverables/VPI-T2-D5/sync-by-car-type", json={"carType": "A" * 90}).status_code == 422
    assert client.post("/api/project-status/deliverables/VPI-T2-D5/sync-by-car-type", json={"carType": "Bad\nCar"}).status_code == 422

    # 3. Non-existent deliverable -> 404
    assert client.post("/api/project-status/deliverables/NOT-FOUND/sync-by-car-type", json={"carType": "F610M"}).status_code == 404

    # 4. Manual-only deliverable -> 409
    assert client.post("/api/project-status/deliverables/VPI-T2-D1/sync-by-car-type", json={"carType": "F610M"}).status_code == 409


def test_api_sync_now_with_car_type_payload(client) -> None:
    # sync-now delegates to car-type sync when carType is present in JSON body
    res = client.post(
        "/api/project-status/deliverables/VPI-T2-D5/sync-now",
        json={"carType": "F610M"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body["data"]["carType"] == "F610M"
    assert body["data"]["deliverableId"] == "VPI-T2-D5"


def test_frontend_car_type_anchor_static_contract() -> None:
    js_text = Path("plugins/project_overview/static/deliverable/analysis.js").read_text(encoding="utf-8")
    assert "CarModelAnchorBar" in js_text
    assert "analysis-anchor-box" in js_text
    assert "按此车型立即同步" in js_text
    assert "/sync-by-car-type" in js_text
    assert "innerHTML" not in js_text
    assert "insertAdjacentHTML" not in js_text

    css_text = Path("plugins/project_overview/static/deliverable.css").read_text(encoding="utf-8")
    assert ".overview-deliverable-detail-view .analysis-anchor-box" in css_text
    assert ".overview-deliverable-detail-view .analysis-anchor-grid" in css_text
    assert ".overview-deliverable-detail-view .analysis-anchor-chip" in css_text
    assert ".overview-deliverable-detail-view .analysis-anchor-sync-btn" in css_text
