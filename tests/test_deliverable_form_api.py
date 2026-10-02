# -*- coding: utf-8 -*-
"""Offline API and persistence tests for unified deliverable form snapshots."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import web.app as web_app
from core.db_manager import DatabaseManager
from core.section_rollup import SectionRollupStore
from services.deliverable_form_analysis import build_form_snapshot, form_definition


def _save_rollup_rules(db: DatabaseManager, *, aliases: dict[str, list[str]] | None = None) -> dict:
    """登记默认五个目标科室；aliases 提供各目标的历史值（测试用对照）。"""
    merged = aliases or {}
    targets = [
        {"target": "车身科", "aliases": merged.get("车身科", [])},
        {"target": "车体科", "aliases": merged.get("车体科", [])},
        {"target": "内饰科", "aliases": merged.get("内饰科", [])},
        {"target": "外饰科", "aliases": merged.get("外饰科", [])},
        {"target": "车体架构集成科", "aliases": merged.get("车体架构集成科", [])},
    ]
    return SectionRollupStore(db).save({"targets": targets})


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
    # 归集激活后 section 筛选按归集口径：登记「车体工程」为车身科历史值。
    _save_rollup_rules(db, aliases={"车身科": ["车体工程"]})

    response = http.get(
        "/api/deliverable-forms/aras_paa/rows",
        query_string={
            "department": "车身开发部",
            "section": "车身科",
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
    # 「车体工程」作为车身科历史别名被归集筛选命中。
    assert data["items"][0]["dimensions"]["section"] == "车体工程"
    assert data["items"][0]["sectionRollupTarget"] == "车身科"

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
    # 归集激活后 section 筛选按归集口径：登记「车体工程」为车身科历史值。
    _save_rollup_rules(db, aliases={"车身科": ["车体工程"]})

    response = http.get(
        "/api/deliverable-forms/aras_paa/view",
        query_string={"section": "车身科", "model": "F610S"},
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["summary"]["total"] == 1
    assert data["summary"]["completed"] == 1
    # sectionStatus 保持原始值口径（筛选命中的是「车体工程」别名行）。
    assert data["charts"]["sectionStatus"][0]["label"] == "车体工程"
    assert all(point["total"] == 1 for point in data["charts"]["quantityTrend"])
    assert data["filters"]["applied"] == {
        "section": "车身科",
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
    assert data["schema"]["defaultVisibleCount"] == 16
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


# ── SOR 定点流程（tdc_sor） ──────────────────────────────────────────────────


def _sor_snapshot(*, snapshot_at: str, source_run_id: int) -> object:
    definition = form_definition("tdc_sor")
    headers = definition["headerRows"][0]

    def _row(**labeled: object) -> dict[str, object]:
        values: list[object | None] = [None] * len(headers)
        for label, value in labeled.items():
            values[headers.index(label)] = value
        return {"values": values, "sheetName": "Sheet1"}

    return build_form_snapshot(
        "tdc_sor",
        [
            _row(
                流水单号="F999X-SOR-001",
                车型项目="F999X",
                类型="定点",
                科室="车身科",
                部门="车身开发部",
                申请日期="2026-08-20",
                审批状态="已完成",
            ),
            _row(
                流水单号="F888Y-SOR-002",
                车型项目="F888Y",
                类型="变更",
                科室="内饰科",
                申请日期="2026-08-01",
                审批状态="审批中",
                当前待办人="13900139000",
            ),
        ],
        snapshot_at=snapshot_at,
        source_run_id=source_run_id,
        source="test archive",
    )


def test_tdc_sor_form_view_endpoint_returns_schema_charts_and_filters(client) -> None:
    http, db = client
    db.publish_deliverable_form_snapshot(
        _sor_snapshot(snapshot_at="2026-09-01T18:00:00Z", source_run_id=5)
    )

    response = http.get("/api/deliverable-forms/tdc_sor/view")

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    data = body["data"]
    assert data["formKey"] == "tdc_sor"
    assert data["reportType"] == "tdc_sor"
    assert len(data["schema"]["columns"]) == 15
    assert data["summary"]["total"] == 2
    assert data["summary"]["completed"] == 1
    assert "departmentStatus" in data["charts"]
    assert data["sync"]["jobKey"] == "tdc_sor"
    serialized = json.dumps(data, ensure_ascii=False)
    assert "13900139000" not in serialized
    assert "credentialRef" not in serialized


def test_tdc_sor_rows_endpoint_supports_section_filter(client) -> None:
    http, db = client
    db.publish_deliverable_form_snapshot(
        _sor_snapshot(snapshot_at="2026-09-01T18:00:00Z", source_run_id=6)
    )

    response = http.get("/api/deliverable-forms/tdc_sor/rows?section=%E8%BD%A6%E8%BA%AB%E7%A7%91")

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["dimensions"]["section"] == "车身科"


def test_publish_deliverable_form_snapshot_optimistic_lock(client) -> None:
    """publish_deliverable_form_snapshot 校验 expected_sync_config_revision：换绑时拒绝发布。"""
    _, db = client
    # 模拟设置 VPI-T2-D6 (aras_paa) 的修订号为 5
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET sync_config_revision = 5 WHERE deliverable_id = 'VPI-T2-D6'"
        )

    snap = _paa_snapshot(snapshot_at="2026-09-01T20:00:00Z", source_run_id=10)

    # 1. 预期修订号不一致 (4 != 5) → 拒绝发布，返回 0
    res_mismatch = db.publish_deliverable_form_snapshot(snap, expected_sync_config_revision=4)
    assert res_mismatch == 0

    # 2. 预期修订号一致 (5 == 5) → 允许发布，返回 snapshot_id > 0
    res_match = db.publish_deliverable_form_snapshot(snap, expected_sync_config_revision=5)
    assert res_match > 0

    # 3. 交付物绑定不存在 (binding_row 为 None) 且指定了修订号 → 拒绝发布，返回 0 (fail-closed)
    snap_unknown = build_form_snapshot(
        "aras_paa",
        (),
        snapshot_at="2026-09-01T21:00:00Z",
        source_run_id=11,
        source="project_status_sync",
    )
    with db.get_connection() as conn:
        conn.execute("DELETE FROM project_status_update_bindings WHERE deliverable_id = 'VPI-T2-D6'")
    res_deleted = db.publish_deliverable_form_snapshot(snap_unknown, expected_sync_config_revision=5)
    assert res_deleted == 0


# ===== 科室归集：规则端点 + 双分页矩阵 + 归集筛选（读时归集口径） =====


def test_section_rollup_endpoints_roundtrip_and_validation(client) -> None:
    http, _ = client

    default = http.get("/api/project-status/section-rollup")
    assert default.status_code == 200
    body = default.get_json()
    assert body["ok"] is True
    assert [entry["target"] for entry in body["data"]["targets"]] == [
        "车身科", "车体科", "内饰科", "外饰科", "车体架构集成科",
    ]

    saved = http.put(
        "/api/project-status/section-rollup",
        json={"targets": [{"target": "车身科", "aliases": ["结构工程科"]}]},
    )
    assert saved.status_code == 200
    saved_body = saved.get_json()
    assert saved_body["ok"] is True
    assert saved_body["data"]["targets"][0]["aliases"] == ["结构工程科"]
    assert saved_body["data"]["updatedAt"]

    refetched = http.get("/api/project-status/section-rollup")
    assert refetched.get_json()["data"]["targets"][0]["aliases"] == ["结构工程科"]

    invalid = http.put(
        "/api/project-status/section-rollup",
        json={
            "targets": [
                {"target": "车身科", "aliases": ["结构工程科"]},
                {"target": "内饰科", "aliases": ["结构工程科"]},
            ],
        },
    )
    assert invalid.status_code == 422
    fields = invalid.get_json()["error"]["fields"]
    assert "只能归属一个目标科室" in fields["targets.2.aliases"]

    non_object = http.put(
        "/api/project-status/section-rollup",
        data=json.dumps(["x"]),
        content_type="application/json",
    )
    assert non_object.status_code == 400


def test_form_view_matrix_and_rollup_filtered_rows(client) -> None:
    http, db = client
    db.publish_deliverable_form_snapshot(
        _paa_snapshot(snapshot_at="2026-09-01T18:00:00Z", source_run_id=2)
    )
    _save_rollup_rules(db, aliases={"车身科": ["车体工程"]})

    view = http.get("/api/deliverable-forms/aras_paa/view")
    data = view.get_json()["data"]
    matrix = data["charts"]["sectionStageMatrix"]
    assert [entry["label"] for entry in matrix["sections"]] == [
        "车身科", "车体科", "内饰科", "外饰科", "车体架构集成科", "未归集",
    ]
    body_section = next(entry for entry in matrix["sections"] if entry["label"] == "车身科")
    assert body_section["total"] == 1  # 「车体工程」归集到车身科
    unassigned_section = matrix["sections"][-1]
    assert unassigned_section["total"] == 1  # 「动力总成」未登记 → 未归集
    assert matrix["stages"][0]["label"] == "DRAFT1"
    assert data["sectionRollup"]["targets"][0]["aliases"] == ["车体工程"]

    # 归集筛选：选目标科室 = 含历史别名行；「未归集」= 未登记行。
    filtered = http.get(
        "/api/deliverable-forms/aras_paa/view",
        query_string={"section": "车身科"},
    )
    assert filtered.get_json()["data"]["summary"]["total"] == 1
    unassigned_view = http.get(
        "/api/deliverable-forms/aras_paa/view",
        query_string={"section": "未归集"},
    )
    assert unassigned_view.get_json()["data"]["summary"]["total"] == 1

    rows = http.get("/api/deliverable-forms/aras_paa/rows", query_string={"section": "车身科"})
    rows_data = rows.get_json()["data"]
    assert rows_data["total"] == 1
    assert rows_data["items"][0]["sectionRollupTarget"] == "车身科"
    assert rows_data["items"][0]["dimensions"]["section"] == "车体工程"


def test_form_rows_attach_rollup_target_and_tdc_data_model_joins_rollup(client) -> None:
    http, db = client
    db.publish_deliverable_form_snapshot(
        _paa_snapshot(snapshot_at="2026-09-01T18:00:00Z", source_run_id=2)
    )
    db.publish_deliverable_form_snapshot(
        _tdc_snapshot(snapshot_at="2026-09-02T18:00:00Z", source_run_id=3)
    )
    _save_rollup_rules(db, aliases={"车身科": ["车体工程"]})

    rows = http.get("/api/deliverable-forms/aras_paa/rows")
    items = rows.get_json()["data"]["items"]
    assert {item["sectionRollupTarget"] for item in items} == {"车身科", "未归集"}

    tdc_view = http.get("/api/deliverable-forms/tdc_data_model/view")
    tdc_data = tdc_view.get_json()["data"]
    assert "sectionStageMatrix" not in tdc_data["charts"]
    assert tdc_data.get("sectionRollup")
    assert tdc_data["charts"]["sectionCounts"] == [
        {"label": "车身科", "total": 1},
        {"label": "车体科", "total": 0},
        {"label": "内饰科", "total": 1},
        {"label": "外饰科", "total": 0},
        {"label": "车体架构集成科", "total": 0},
        {"label": "未归集", "total": 0},
    ]
    tdc_rows = http.get("/api/deliverable-forms/tdc_data_model/rows")
    tdc_items = tdc_rows.get_json()["data"]["items"]
    assert tdc_items and {item["sectionRollupTarget"] for item in tdc_items} == {
        "内饰科",
        "车身科",
    }


def test_rollup_rule_change_takes_effect_without_resync(client) -> None:
    http, db = client
    db.publish_deliverable_form_snapshot(
        _paa_snapshot(snapshot_at="2026-09-01T18:00:00Z", source_run_id=2)
    )
    _save_rollup_rules(db, aliases={"车身科": ["车体工程"]})

    before = http.get(
        "/api/deliverable-forms/aras_paa/view",
        query_string={"section": "车身科"},
    )
    assert before.get_json()["data"]["summary"]["total"] == 1

    http.put(
        "/api/project-status/section-rollup",
        json={"targets": [{"target": "车身科", "aliases": []}]},
    )

    after = http.get(
        "/api/deliverable-forms/aras_paa/view",
        query_string={"section": "车身科"},
    )
    assert after.get_json()["data"]["summary"]["total"] == 0
    # 不带筛选的视图矩阵：别名移除后两行都落入「未归集」，无需重新同步。
    unfiltered = http.get("/api/deliverable-forms/aras_paa/view")
    matrix = unfiltered.get_json()["data"]["charts"]["sectionStageMatrix"]
    assert next(entry for entry in matrix["sections"] if entry["label"] == "未归集")["total"] == 2
    assert next(entry for entry in matrix["sections"] if entry["label"] == "车身科")["total"] == 0


def test_rows_section_filter_combined_with_threshold_override(client) -> None:
    """审计钉住：SQL 预筛(非 section) → 阈值重算 → 归集筛选 → 切片 的组合路径。"""
    http, db = client
    db.publish_deliverable_form_snapshot(
        _paa_snapshot(snapshot_at="2026-09-01T18:00:00Z", source_run_id=2)
    )
    _save_rollup_rules(db, aliases={"车身科": ["车体工程"]})

    # 已完成的「车体工程」行（归集为车身科）在阈值重算后为 not_applicable，
    # 逾期筛选必须将其排除；分页 total 在归集筛选之后计算。
    combined = http.get(
        "/api/deliverable-forms/aras_paa/rows",
        query_string={
            "section": "车身科",
            "overdueDaysStage": "1",
            "overdueState": "overdue",
        },
    )
    assert combined.status_code == 200
    combined_data = combined.get_json()["data"]
    assert combined_data["total"] == 0
    assert combined_data["items"] == []

    section_only = http.get(
        "/api/deliverable-forms/aras_paa/rows",
        query_string={"section": "车身科", "overdueDaysStage": "1"},
    )
    assert section_only.status_code == 200
    section_data = section_only.get_json()["data"]
    assert section_data["total"] == 1
    assert section_data["items"][0]["sectionRollupTarget"] == "车身科"
    assert section_data["items"][0]["dimensions"]["section"] == "车体工程"

    unassigned_only = http.get(
        "/api/deliverable-forms/aras_paa/rows",
        query_string={"section": "未归集", "overdueDaysStage": "1"},
    )
    assert unassigned_only.get_json()["data"]["total"] == 1
