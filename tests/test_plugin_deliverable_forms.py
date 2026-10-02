# -*- coding: utf-8 -*-
"""deliverable-forms plugin (SOR pilot) and the core/form_registry single source."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import core.db_manager as db_manager
import services.deliverable_form_analysis as form_analysis
import web.app as web_app
from core import form_registry
from services.deliverable_form_analysis import build_form_snapshot, form_definition

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO_ROOT / "plugins" / "deliverable_forms"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "forms-plugin.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=["deliverable-forms"])
    app.config.update(TESTING=True)
    return app.test_client(), db_cls(tmp_path / "forms-plugin.db")


def _sor_snapshot(snapshot_at: str) -> object:
    headers = form_definition("tdc_sor")["headerRows"][0]

    def row(**labeled: object) -> dict[str, object]:
        values: list[object | None] = [None] * len(headers)
        for label, value in labeled.items():
            values[headers.index(label)] = value
        return {"values": values, "sheetName": "Sheet1"}

    return build_form_snapshot(
        "tdc_sor",
        [
            row(流水单号="F999X-SOR-001", 车型项目="F999X", 类型="定点", 科室="车身科",
                部门="车身开发部", 申请日期="2026-08-20", 审批状态="Completed"),
            row(流水单号="F888Y-SOR-002", 车型项目="F888Y", 类型="变更", 科室="内饰科",
                申请日期="2026-08-01", 审批状态="审批中", 当前待办人="13900139000"),
            row(流水单号="E50-SOR-003", 车型项目="E50", 科室="底盘科",
                申请日期="2026-08-01", 审批状态="Terminated"),
        ],
        snapshot_at=snapshot_at,
        source_run_id=1,
        source="test archive",
    )


def test_plugin_loads_with_sor_page(client) -> None:
    http, _ = client
    data = http.get("/api/host/manifest").get_json()["data"]
    record = next(p for p in data["plugins"] if p["id"] == "deliverable-forms")
    assert record["status"] == "loaded", record.get("error")
    assert {"plugin": "deliverable-forms", "page": "index"}.items() <= data["nav"][0].items()
    assert http.get("/plugins/deliverable-forms/static/pages/tdc_sor.json").status_code == 200
    assert http.get("/plugins/deliverable-forms/static/index.js").status_code == 200


def test_forms_endpoint_lists_registry(client) -> None:
    http, _ = client
    forms = http.get("/api/p/deliverable-forms/forms").get_json()["data"]
    assert [item["formKey"] for item in forms] == [spec.form_key for spec in form_registry.FORMS]


def test_sor_rows_are_flattened_by_key_columns(client) -> None:
    http, db = client
    assert http.get("/api/p/deliverable-forms/forms/tdc_sor/rows").get_json()["data"] == {
        "rows": [],
        "updatedAt": None,
    }
    db.publish_deliverable_form_snapshot(_sor_snapshot("2026-09-06T10:00:00Z"))

    body = http.get("/api/p/deliverable-forms/forms/tdc_sor/rows").get_json()
    assert body["ok"] is True
    data = body["data"]
    assert data["updatedAt"] == "2026-09-06T10:00:00Z"
    by_no = {row["流水单号"]: row for row in data["rows"]}
    done, pending = by_no["F999X-SOR-001"], by_no["F888Y-SOR-002"]
    assert done["_status"] == "已完成"  # 英文状态归一为中文
    assert done["_completed"] is True
    assert done["_overdue"] == "已完成 / 不适用"
    assert pending["_completed"] is False
    assert pending["_overdue"] == "逾期风险"
    assert pending["科室"] == "内饰科"
    terminated = by_no["E50-SOR-003"]
    assert terminated["_status"] == "已终止"
    assert terminated["_completed"] is None  # 终态：与旧汇总口径一致，不计入未完成
    # 当前待办人不是关键列，联系方式不会出现在插件接口里
    assert "13900139000" not in json.dumps(data, ensure_ascii=False)


def test_unknown_form_is_404(client) -> None:
    http, _ = client
    response = http.get("/api/p/deliverable-forms/forms/nope/rows")
    assert response.status_code == 404
    assert response.get_json()["ok"] is False


def test_sor_schema_columns_exist_in_plugin_rows() -> None:
    schema = json.loads((PLUGIN_DIR / "static" / "pages" / "tdc_sor.json").read_text(encoding="utf-8"))
    labels = set(form_registry.get_form("tdc_sor").key_column_labels) | {"_status", "_completed", "_overdue"}
    referenced = {c["key"] for c in schema["columns"]} | {f["key"] for f in schema["filters"]}
    referenced |= {c["groupBy"] for c in schema["charts"]} | {c["doneField"] for c in schema["charts"]}
    assert referenced <= labels


# ── core/form_registry.py 单一来源 ───────────────────────────────────


def test_legacy_form_dicts_are_derived_from_registry() -> None:
    specs = form_registry.FORMS
    assert form_analysis.FORM_KEYS == db_manager._FORM_SNAPSHOT_KEYS == form_registry.FORM_KEYS
    assert form_analysis._REPORT_BY_FORM_KEY == {s.form_key: s.report for s in specs}
    assert db_manager._FORM_SNAPSHOT_REPORTS == form_analysis._REPORT_BY_FORM_KEY
    assert form_analysis._CONTACT_INDEXES == {"ewo": (13,), "paa": (5, 15), "tdc_sor": (14,)}
    assert form_analysis._TDC_DWELL_REPORTS == frozenset({"tdc_data_model", "tdc_sor"})
    assert set(form_analysis._OVERDUE_RULES) == {"ewo", "paa", "ncr_progress", "tdc_data_model", "tdc_sor"}
    assert form_analysis._SHEET_NAMES_BY_FORM_KEY["aras_ncr_detail"] == ["整车", "发动机"]


def test_snapshot_table_has_no_form_key_check() -> None:
    # Sprint 2 移除了 form_key 的 SQL CHECK：新增表单只改 core/form_registry.py。
    assert re.search(r"form_key\s+IN", db_manager._DELIVERABLE_FORM_SNAPSHOTS_DDL) is None


def test_plugin_counts_match_legacy_view_summary(client) -> None:
    """新页面图表按 _completed 三态统计，必须与旧 /view 汇总口径一致。"""
    http, db = client
    db.publish_deliverable_form_snapshot(_sor_snapshot("2026-09-06T10:00:00Z"))
    legacy = http.get("/api/deliverable-forms/tdc_sor/view").get_json()["data"]["summary"]
    rows = http.get("/api/p/deliverable-forms/forms/tdc_sor/rows").get_json()["data"]["rows"]
    assert len(rows) == legacy["total"]
    assert sum(row["_completed"] is True for row in rows) == legacy["completed"]
    assert sum(row["_completed"] is False for row in rows) == legacy["incomplete"]


def test_every_form_has_a_schema_page_using_flattened_fields(client) -> None:
    """每张注册表单都有分析页，且页面引用的字段都在展平行里出现。"""
    http, _ = client
    manifest = json.loads((PLUGIN_DIR / "plugin.json").read_text(encoding="utf-8"))
    page_ids = {page["id"] for page in manifest["pages"]}
    forms = http.get("/api/p/deliverable-forms/forms").get_json()["data"]
    meta_fields = {"id", "_status", "_completed", "_overdue", "_submitted"} | {
        "_" + dimension for dimension in ("department", "section", "model", "stage")
    }
    for form in forms:
        spec = form_registry.get_form(form["formKey"])
        assert form["page"] in page_ids
        schema = json.loads((PLUGIN_DIR / "static" / "pages" / f"{form['page']}.json").read_text(encoding="utf-8"))
        assert schema["source"] == f"forms/{spec.form_key}/rows"
        allowed = meta_fields | set(spec.page_columns)
        used = {f["key"] for f in schema["filters"]} | {c["key"] for c in schema["columns"]}
        used |= {chart["groupBy"] for chart in schema["charts"]}
        assert used <= allowed, (spec.form_key, used - allowed)
        definition = form_definition(spec.form_key)
        labels = {str(column.get("label") or "") for column in definition["columns"]}
        assert set(spec.page_columns) <= labels, spec.form_key


def test_registry_endpoint_carries_ui_metadata(client) -> None:
    http, _ = client
    entries = {e["formKey"]: e for e in http.get("/api/p/deliverable-forms/registry").get_json()["data"]}
    assert set(entries) == set(form_registry.FORM_KEYS)
    assert entries["tdc_sor"]["dimensionLabels"]["stage"] == "车型项目"
    assert entries["tdc_sor"]["terminalStatuses"] == sorted(form_registry.get_form("tdc_sor").terminal_statuses)
    assert entries["VPI-T2-D3"]["dimensionLabels"]["status"] == "状态"


def test_rows_carry_dimensions_and_forms_list_snapshot_info(client) -> None:
    http, db = client
    db.publish_deliverable_form_snapshot(_sor_snapshot("2026-09-06T10:00:00Z"))
    rows = http.get("/api/p/deliverable-forms/forms/tdc_sor/rows").get_json()["data"]["rows"]
    by_no = {row["流水单号"]: row for row in rows}
    assert by_no["F999X-SOR-001"]["_stage"] == "F999X"
    assert by_no["F999X-SOR-001"]["_section"] == "车身科"
    assert by_no["F999X-SOR-001"]["_submitted"] == "2026-08-20"
    forms = {f["formKey"]: f for f in http.get("/api/p/deliverable-forms/forms").get_json()["data"]}
    assert forms["tdc_sor"]["rowCount"] == 3
    assert forms["tdc_sor"]["updatedAt"] == "2026-09-06T10:00:00Z"
    assert forms["aras_paa"]["updatedAt"] is None
