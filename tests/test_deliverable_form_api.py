# -*- coding: utf-8 -*-
"""Offline API and persistence tests for unified deliverable form snapshots."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import web.app as web_app
from core.db_manager import DatabaseManager
from services.deliverable_form_analysis import build_form_snapshot, form_definition


def _paa_snapshot(*, snapshot_at: str, source_run_id: int) -> object:
    return build_form_snapshot(
        "aras_paa",
        [
            {
                "_no": "PAA-API-1",
                "_department": "车身开发部",
                "_pe_tdc_smt": "车体工程",
                "_vehicles": "F610S",
                "state": "CLOZ",
                "_ewo_no": "EWO-REL-1",
                "_requester_phone": "13800138000",
                "_submit_date": "2026-08-30",
            },
            {
                "_no": "PAA-API-2",
                "_department": "动力总成部",
                "_pe_tdc_smt": "动力总成",
                "_vehicles": "F510S",
                "state": "APPRL1",
                "_ewo_no": "EWO-REL-2",
                "_submit_date": "2026-08-31",
            },
        ],
        snapshot_at=snapshot_at,
        source_run_id=source_run_id,
        source="test archive",
        artifacts=(
            {
                "display_name": "paa.json",
                "relative_path": "aras/paa/paa.json",
                "artifact_type": "normalized_json",
            },
        ),
    )


def _ncr_values(*, ncr_number: str) -> list[object | None]:
    definition = form_definition("aras_ncr_progress")
    headers = definition["headerRows"][int(definition["dataHeaderRow"])]
    values: list[object | None] = [None] * len(headers)
    for label, value in {
        "状态": "审批中",
        "项目": "F610S",
        "区域": "标准架构集成科",
        "NCR编号": ncr_number,
        "当前节点及通知时间": "NCR管理员",
        "PE填写": "2026-08-20",
        "是否审批完成": "否",
    }.items():
        values[headers.index(label)] = value
    return values


def _ncr_snapshot(*, snapshot_at: str, source_run_id: int) -> object:
    return build_form_snapshot(
        "aras_ncr_progress",
        [
            {"values": _ncr_values(ncr_number="NCR-LEGACY-1"), "sheetName": "Sheet1"},
            {"values": _ncr_values(ncr_number="NCR-LEGACY-1"), "sheetName": "Sheet1"},
        ],
        snapshot_at=snapshot_at,
        source_run_id=source_run_id,
        source="test archive",
    )


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseManager:
    database = DatabaseManager(tmp_path / "form-api.db")
    database.init_database()
    return database


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(
        web_app,
        "DatabaseManager",
        lambda: db_cls(tmp_path / "form-web.db"),
    )
    app = web_app.create_app()
    app.config.update(TESTING=True)
    return app.test_client(), db_cls(tmp_path / "form-web.db")


def test_database_persists_latest_snapshot_and_bounded_rows(db: DatabaseManager) -> None:
    snapshot = _paa_snapshot(
        snapshot_at="2026-09-01T18:00:00Z",
        source_run_id=2,
    )

    snapshot_id = db.publish_deliverable_form_snapshot(snapshot)
    latest = db.get_latest_deliverable_form_snapshot("aras_paa")
    page = db.list_deliverable_form_rows(
        "aras_paa",
        {"section": "车体工程"},
        offset=0,
        limit=1,
    )

    assert snapshot_id > 0
    assert latest is not None
    assert latest["form_key"] == "aras_paa"
    assert latest["row_count"] == 2
    assert page["total"] == 1
    assert len(page["items"]) == 1
    serialized = json.dumps(latest, ensure_ascii=False)
    assert "13800138000" not in serialized
    assert "form-api.db" not in serialized


def test_daily_trend_keeps_latest_snapshot_when_same_day_has_two_runs(
    db: DatabaseManager,
) -> None:
    db.publish_deliverable_form_snapshot(
        _paa_snapshot(snapshot_at="2026-09-01T08:00:00Z", source_run_id=1)
    )
    db.publish_deliverable_form_snapshot(
        _paa_snapshot(snapshot_at="2026-09-01T18:00:00Z", source_run_id=2)
    )

    snapshots = db.list_deliverable_form_snapshots("aras_paa", limit=30)

    assert len(snapshots) == 2
    assert snapshots[0]["snapshot_at"] == "2026-09-01T18:00:00Z"


def test_form_view_endpoint_returns_schema_summary_charts_and_artifacts(
    client,
) -> None:
    http, db = client
    db.publish_deliverable_form_snapshot(
        _paa_snapshot(snapshot_at="2026-09-01T18:00:00Z", source_run_id=2)
    )

    response = http.get("/api/deliverable-forms/aras_paa/view")

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    data = body["data"]
    assert data["formKey"] == "aras_paa"
    assert len(data["schema"]["columns"]) == 113
    assert data["summary"]["total"] == 2
    assert "departmentStatus" in data["charts"]
    assert data["sync"]["jobKey"] == "aras_paa"
    assert "credentialRef" not in json.dumps(data, ensure_ascii=False)
    assert data["artifacts"][0]["display_name"] == "paa.json"
    assert "form-api.db" not in json.dumps(data, ensure_ascii=False)


def test_form_view_uses_current_schema_and_recomputes_legacy_ncr_trend(client) -> None:
    http, db = client
    snapshot_id = db.publish_deliverable_form_snapshot(
        _ncr_snapshot(snapshot_at="2026-09-01T18:00:00Z", source_run_id=4)
    )
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE deliverable_form_snapshots SET schema_json = ?, summary_json = ? WHERE id = ?",
            (
                json.dumps({"columns": [], "defaultVisibleCount": 10}),
                json.dumps({"total": 2, "incomplete": 2, "completed": 0, "overdue": 0}),
                snapshot_id,
            ),
        )

    response = http.get("/api/deliverable-forms/aras_ncr_progress/view")

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["schema"]["keyColumns"] == form_definition("aras_ncr_progress")["keyColumns"]
    assert data["summary"]["total"] == 1
    assert data["charts"]["quantityTrend"][0]["total"] == 1


def test_form_view_filter_options_keep_unselected_values_available(client) -> None:
    http, db = client
    db.publish_deliverable_form_snapshot(
        _paa_snapshot(snapshot_at="2026-09-01T18:00:00Z", source_run_id=2)
    )

    response = http.get(
        "/api/deliverable-forms/aras_paa/view",
        query_string={"department": "车身开发部"},
    )

    assert response.status_code == 200
    options = response.get_json()["data"]["filters"]["options"]
    assert options["department"] == ["动力总成部", "车身开发部"]


def test_form_rows_endpoint_accepts_only_allowlisted_filters(client) -> None:
    http, db = client
    db.publish_deliverable_form_snapshot(
        _paa_snapshot(snapshot_at="2026-09-01T18:00:00Z", source_run_id=2)
    )

    response = http.get(
        "/api/deliverable-forms/aras_paa/rows",
        query_string={
            "department": "车身开发部",
            "section": "车体工程",
            "model": "F610S",
            "status": "CLOSE",
            "offset": "0",
            "limit": "1",
        },
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["dimensions"]["model"] == "F610S"

    invalid = http.get(
        "/api/deliverable-forms/aras_paa/rows",
        query_string={"unsupported": "x"},
    )
    assert invalid.status_code == 422


def test_form_view_filters_charts_and_daily_trend_from_same_snapshot_rows(client) -> None:
    http, db = client
    db.publish_deliverable_form_snapshot(
        _paa_snapshot(snapshot_at="2026-08-31T18:00:00Z", source_run_id=1)
    )
    db.publish_deliverable_form_snapshot(
        _paa_snapshot(snapshot_at="2026-09-01T18:00:00Z", source_run_id=2)
    )

    response = http.get(
        "/api/deliverable-forms/aras_paa/view",
        query_string={"section": "车体工程", "model": "F610S"},
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["summary"]["total"] == 1
    assert data["summary"]["completed"] == 1
    assert data["charts"]["sectionStatus"][0]["label"] == "车体工程"
    assert all(point["total"] == 1 for point in data["charts"]["quantityTrend"])
    assert data["filters"]["applied"] == {
        "section": "车体工程",
        "model": "F610S",
    }


def test_form_rows_repeated_dimension_filters_are_or_and_relation_ewo_is_supported(client) -> None:
    http, db = client
    db.publish_deliverable_form_snapshot(
        _paa_snapshot(snapshot_at="2026-09-01T18:00:00Z", source_run_id=2)
    )

    response = http.get(
        "/api/deliverable-forms/aras_paa/rows",
        query_string=[
            ("department", "车身开发部"),
            ("department", "动力总成部"),
            ("relationEwo", "EWO-REL-2"),
        ],
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["dimensions"]["department"] == "动力总成部"


def test_form_view_threshold_override_recomputes_current_summary_but_not_trend(client) -> None:
    http, db = client
    db.publish_deliverable_form_snapshot(
        _tdc_snapshot(snapshot_at="2026-09-01T18:00:00Z", source_run_id=3)
    )

    response = http.get(
        "/api/deliverable-forms/tdc_data_model/view",
        query_string={"overdueDaysStage": "1"},
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["overdueThresholds"] == {"overdueDaysStage": 1}
    assert data["summary"]["overdue"] == 1
    # The historical snapshot summary keeps the stored seven-day口径.
    assert data["charts"]["quantityTrend"][0]["overdue"] == 0

    rows_response = http.get(
        "/api/deliverable-forms/tdc_data_model/rows",
        query_string={"overdueDaysStage": "1", "overdueState": "overdue"},
    )
    assert rows_response.status_code == 200
    rows_data = rows_response.get_json()["data"]
    assert rows_data["total"] == 1
    assert rows_data["items"][0]["overdueState"] == "overdue"


def test_form_view_rejects_out_of_range_overdue_threshold(client) -> None:
    http, _ = client

    response = http.get(
        "/api/deliverable-forms/tdc_data_model/view",
        query_string={"overdueDaysStage": "1000"},
    )

    assert response.status_code == 422


def test_form_view_keeps_thirty_calendar_days_when_runs_are_more_frequent(client) -> None:
    http, db = client
    for day in range(1, 32):
        db.publish_deliverable_form_snapshot(
            _paa_snapshot(
                snapshot_at=f"2026-08-{day:02d}T18:00:00Z",
                source_run_id=day,
            )
        )

    response = http.get("/api/deliverable-forms/aras_paa/view")

    assert response.status_code == 200
    trend = response.get_json()["data"]["charts"]["quantityTrend"]
    assert len(trend) == 30
    assert trend[0]["day"] == "2026-08-02"
    assert trend[-1]["day"] == "2026-08-31"


@pytest.mark.parametrize(
    "form_key",
    ["VPI-T2-D3", "aras_paa", "aras_ncr_progress", "aras_ncr_detail"],
)
def test_form_view_endpoint_accepts_each_allowlisted_key(
    client,
    form_key: str,
) -> None:
    http, _ = client

    response = http.get(f"/api/deliverable-forms/{form_key}/view")

    assert response.status_code == 200
    assert response.get_json()["data"]["formKey"] == form_key


def test_form_view_endpoint_rejects_unknown_key(client) -> None:
    http, _ = client

    response = http.get("/api/deliverable-forms/not-approved/view")

    assert response.status_code == 404


# ── 数模设计审核流程（tdc_data_model） ────────────────────────────────────────


def _tdc_row_values(
    status: str,
    request_date: str,
    *,
    project: str,
    section: str,
) -> list[object | None]:
    """One synthetic 47-column TDC data-model row (all values fabricated)."""
    definition = form_definition("tdc_data_model")
    headers = definition["headerRows"][0]
    values: list[object | None] = [None] * len(headers)
    for label, value in {
        "实例号": "90000101",
        "流水单号": "F999X-3D-0001",
        "发布属性": "T2发布",
        "部门": section,
        "申请日期": request_date,
        "项目/车型": project,
        "零件号": "27000001",
        "数模号": "27000001",
        "零件名称": "组件A",
        "状态": status,
    }.items():
        values[headers.index(label)] = value
    return values


def _tdc_snapshot(*, snapshot_at: str, source_run_id: int) -> object:
    return build_form_snapshot(
        "tdc_data_model",
        [
            {
                "values": _tdc_row_values("审批中", "2026-08-30 09:30:00", project="F999X", section="内饰科"),
                "sheetName": "Sheet1",
            },
            {
                "values": _tdc_row_values("已完成", "2026-08-20 10:00:00", project="F888Y", section="车身科"),
                "sheetName": "Sheet1",
            },
        ],
        snapshot_at=snapshot_at,
        source_run_id=source_run_id,
        source="test archive",
    )


def test_tdc_form_view_endpoint_returns_schema_charts_and_filter_options(client) -> None:
    http, db = client
    db.publish_deliverable_form_snapshot(
        _tdc_snapshot(snapshot_at="2026-09-01T18:00:00Z", source_run_id=3)
    )

    response = http.get("/api/deliverable-forms/tdc_data_model/view")

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    data = body["data"]
    assert data["formKey"] == "tdc_data_model"
    assert data["reportType"] == "tdc_data_model"
    assert len(data["schema"]["columns"]) == 45
    assert data["schema"]["defaultVisibleCount"] == 15
    assert all(column["index"] not in (12, 13) for column in data["schema"]["columns"])
    assert data["summary"]["total"] == 2
    assert data["summary"]["completed"] == 1
    for chart_key in ("departmentStatus", "sectionStatus", "quantityTrend"):
        assert chart_key in data["charts"]
    # 数模不使用 department 维度，选项必须为空列表。
    assert data["filters"]["options"]["department"] == []
    assert data["sync"]["jobKey"] == "tdc_data_model"
    assert "form-web.db" not in json.dumps(data, ensure_ascii=False)


def test_tdc_form_rows_endpoint_returns_items_and_rejects_unknown_filters(client) -> None:
    http, db = client
    db.publish_deliverable_form_snapshot(
        _tdc_snapshot(snapshot_at="2026-09-01T18:00:00Z", source_run_id=3)
    )

    response = http.get(
        "/api/deliverable-forms/tdc_data_model/rows",
        query_string={"section": "内饰科", "offset": "0", "limit": "1"},
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["dimensions"]["section"] == "内饰科"
    assert data["items"][0]["dimensions"]["model"] == "T2发布"

    invalid = http.get(
        "/api/deliverable-forms/tdc_data_model/rows",
        query_string={"unsupported": "x"},
    )
    assert invalid.status_code == 422


def test_tdc_form_view_accepts_empty_snapshot_and_rejects_unknown_key(client) -> None:
    http, _ = client

    response = http.get("/api/deliverable-forms/tdc_data_model/view")

    assert response.status_code == 200
    assert response.get_json()["data"]["formKey"] == "tdc_data_model"

    unknown = http.get("/api/deliverable-forms/unknown-form/view")
    assert unknown.status_code == 404
