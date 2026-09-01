# -*- coding: utf-8 -*-
"""Offline tests for the unified deliverable form analysis contract."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from zipfile import ZipFile

import pytest

from services.deliverable_form_analysis import (
    FormSnapshotInput,
    aggregate_daily_trend,
    classify_overdue,
    form_definition,
    normalize_form_rows,
    summarize_form_rows,
)
from services.xlsx_preview import read_xlsx_workbook_preview


def _column_index(form_key: str, label: str) -> int:
    return next(
        int(column["index"])
        for column in form_definition(form_key)["columns"]
        if column["label"] == label
    )


def _ncr_values(form_key: str, values: dict[str, object]) -> list[object | None]:
    result: list[object | None] = [None] * len(form_definition(form_key)["columns"])
    for label, value in values.items():
        result[_column_index(form_key, label)] = value
    return result


def _cell_ref(column: int, row: int) -> str:
    result = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        result = chr(65 + remainder) + result
    return f"{result}{row}"


def _write_two_sheet_xlsx(path: Path) -> None:
    def row_xml(row_number: int, values: list[str]) -> str:
        cells = "".join(
            f'<c r="{_cell_ref(index, row_number)}" t="inlineStr">'
            f"<is><t>{escape(value)}</t></is></c>"
            for index, value in enumerate(values, 1)
        )
        return f'<row r="{row_number}">{cells}</row>'

    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="整车" sheetId="1" r:id="rId1"/>'
        '<sheet name="发动机" sheetId="2" r:id="rId2"/></sheets></workbook>'
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet2.xml"/></Relationships>'
    )

    def sheet(value: str) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            + row_xml(1, ["状态", "项目"])
            + row_xml(2, [value, "F610S"])
            + "</sheetData></worksheet>"
        )
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", sheet("关闭"))
        archive.writestr("xl/worksheets/sheet2.xml", sheet("审批中"))


def test_form_definitions_match_approved_report_contracts() -> None:
    expected = {
        "VPI-T2-D3": (111, 1),
        "aras_paa": (113, 1),
        "aras_ncr_progress": (64, 2),
        "aras_ncr_detail": (65, 5),
    }
    for form_key, (width, header_count) in expected.items():
        definition = form_definition(form_key)
        assert len(definition["columns"]) == width
        assert len(definition["headerRows"]) == header_count
        assert definition["formKey"] == form_key

    detail = form_definition("aras_ncr_detail")
    assert detail["sheetNames"] == ["整车", "发动机"]


def test_all_sheet_xlsx_preview_preserves_sheet_names_and_limits(tmp_path: Path) -> None:
    path = tmp_path / "two-sheet.xlsx"
    _write_two_sheet_xlsx(path)

    previews = read_xlsx_workbook_preview(path, max_rows=2, max_columns=2)

    assert [item.sheet_name for item in previews] == ["整车", "发动机"]
    assert [item.rows for item in previews] == [
        [["状态", "项目"], ["关闭", "F610S"]],
        [["状态", "项目"], ["审批中", "F610S"]],
    ]


def test_ewo_and_paa_rows_keep_dimensions_and_mask_contacts() -> None:
    rows = normalize_form_rows(
        "VPI-T2-D3",
        [
            {
                "_no": "EWO-TEST-1",
                "_modelinfo": "F610S",
                "_rsp_department": "车身开发部",
                "_rsp_smt": "车体工程",
                "_rsp_phone": "13800138000",
                "state": "PROC",
                "_required_date": "2026-09-10",
            }
        ],
        snapshot_at="2026-09-01T10:00:00Z",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["dimensions"]["department"] == "车身开发部"
    assert row["dimensions"]["section"] == "车体工程"
    assert row["dimensions"]["model"] == "F610S"
    assert row["dimensions"]["stage"] == "PROC"
    assert "13800138000" not in json.dumps(row, ensure_ascii=False)
    assert "****" in json.dumps(row, ensure_ascii=False)


def test_ncr_detail_preserves_six_cost_fields_and_sheet_name() -> None:
    values = _ncr_values(
        "aras_ncr_detail",
        {
            "状态": "审批中",
            "项目": "F610S",
            "区域": "动力底盘附件集成科",
            "测算工程工装费用(万元)": "120",
            "批准工程工装费用（万元）": "110",
            "实际工程工装费用(万元)": "105",
            "测算单件成本变化（元）": "35",
            "批准单件成本变化（元）": "28",
            "实际单件成本变化（元）": "-12",
        },
    )

    rows = normalize_form_rows(
        "aras_ncr_detail",
        [{"values": values, "sheet_name": "整车"}],
        snapshot_at="2026-09-01T10:00:00Z",
    )

    assert rows[0]["sheetName"] == "整车"
    assert rows[0]["cost"]["investment"] == {
        "estimate": 120.0,
        "approved": 110.0,
        "actual": 105.0,
    }
    assert rows[0]["cost"]["vehicleChange"] == {
        "estimate": 35.0,
        "approved": 28.0,
        "actual": -12.0,
    }
    assert rows[0]["cost"]["vehicleChangeDirection"] == "decrease"


def test_ncr_progress_uses_current_node_header_for_stage_status() -> None:
    values = _ncr_values(
        "aras_ncr_progress",
        {
            "状态": "审批中",
            "项目": "F610S",
            "区域": "标准架构集成科",
            "当前节点及通知时间": "NCR管理员",
            "是否审批完成": "否",
        },
    )

    rows = normalize_form_rows(
        "aras_ncr_progress",
        [{"values": values, "sheet_name": "Sheet1"}],
        snapshot_at="2026-09-01T10:00:00Z",
    )

    assert rows[0]["dimensions"]["stage"] == "NCR管理员"


def test_ncr_progress_uses_each_approval_node_arrival_date_for_due_rule() -> None:
    values = _ncr_values(
        "aras_ncr_progress",
        {
            "状态": "审批中",
            "项目": "F610S",
            "区域": "标准架构集成科",
            "当前节点及通知时间": "PE科室经理",
            "PE填写": "2026-08-20",
            "NCR管理员": "2026-08-21",
            "PE科室经理": "2026-08-30",
        },
    )

    rows = normalize_form_rows(
        "aras_ncr_progress",
        [{"values": values, "sheet_name": "Sheet1"}],
        snapshot_at="2026-09-01T10:00:00Z",
    )

    assert rows[0]["stageStart"] == "2026-08-30"
    assert rows[0]["stageEnd"] is None
    assert rows[0]["overdueState"] == "on_time"


def test_paa_chart_uses_proc_stage_and_ncr_node_prefix_is_normalized() -> None:
    paa_stages = form_definition("aras_paa")["chartFields"]
    assert paa_stages == ["DRAFT1", "DRAFT2", "EDIT", "PROC", "IMPL", "CLOSE"]

    values = _ncr_values(
        "aras_ncr_progress",
        {
            "状态": "审批中",
            "项目": "F610S",
            "区域": "标准架构集成科",
            "当前节点及通知时间": "NCR管理员（2026-09-01）",
            "PE填写": "2026-08-20",
            "是否审批完成": "否",
        },
    )
    rows = normalize_form_rows(
        "aras_ncr_progress",
        [{"values": values, "sheet_name": "Sheet1"}],
        snapshot_at="2026-09-01T10:00:00Z",
    )
    assert rows[0]["dimensions"]["stage"] == "NCR管理员"
    assert rows[0]["stageStart"] == "2026-08-20"


@pytest.mark.parametrize(
    ("form_key", "row", "snapshot_at", "expected"),
    [
        (
            "VPI-T2-D3",
            {"stage": "DRAFT1", "stageStart": "2026-08-01"},
            "2026-08-09T00:00:00Z",
            "overdue",
        ),
        (
            "VPI-T2-D3",
            {"stage": "PROC", "stageStart": "2026-01-31"},
            "2026-03-01T00:00:00Z",
            "overdue",
        ),
        (
            "VPI-T2-D3",
            {"stage": "IMPL", "plannedDate": "2026-09-10"},
            "2026-09-01T00:00:00Z",
            "on_time",
        ),
        (
            "aras_paa",
            {"stage": "EDIT", "stageStart": "2026-08-01"},
            "2026-08-05T00:00:00Z",
            "overdue",
        ),
        (
            "aras_ncr_progress",
            {"stage": "NCR管理员", "stageStart": "2026-08-01"},
            "2026-08-05T00:00:00Z",
            "overdue",
        ),
        (
            "aras_ncr_detail",
            {"stage": "审批中", "stageStart": "2026-01-01"},
            "2026-09-01T00:00:00Z",
            "not_applicable",
        ),
    ],
)
def test_classify_overdue_uses_approved_form_rules(
    form_key: str,
    row: dict[str, object],
    snapshot_at: str,
    expected: str,
) -> None:
    assert classify_overdue(form_key, row, snapshot_at=snapshot_at) == expected


def test_summary_aggregates_department_and_section_status() -> None:
    rows = [
        {"dimensions": {"department": "部门A", "section": "科室A", "stage": "PROC"}, "overdueState": "on_time", "isCompleted": False},
        {"dimensions": {"department": "部门A", "section": "科室B", "stage": "PROC"}, "overdueState": "overdue", "isCompleted": False},
        {"dimensions": {"department": "部门B", "section": "科室A", "stage": "CLOSE"}, "overdueState": "on_time", "isCompleted": True},
    ]

    summary = summarize_form_rows(
        "VPI-T2-D3",
        rows,
        snapshot_at="2026-09-01T10:00:00Z",
    )

    assert summary["total"] == 3
    assert summary["incomplete"] == 2
    assert summary["overdue"] == 1
    assert summary["departmentStatus"]["stages"][4] == {
        "label": "PROC",
        "onTime": 1,
        "overdue": 1,
        "unknown": 0,
    }
    assert summary["sectionStatus"][0]["label"] == "科室A"
    assert summary["sectionStatus"][0]["total"] == 2


def test_stage_status_keeps_unknown_dates_visible_and_completed_ncr_is_close() -> None:
    stage_summary = summarize_form_rows(
        "VPI-T2-D3",
        [
            {
                "dimensions": {"department": "部门A", "section": "科室A", "stage": "DRAFT1"},
                "overdueState": "unknown",
                "isCompleted": False,
            },
        ],
        snapshot_at="2026-09-01T10:00:00Z",
    )
    assert stage_summary["departmentStatus"]["stages"][0] == {
        "label": "DRAFT1",
        "onTime": 0,
        "overdue": 0,
        "unknown": 1,
    }

    values = _ncr_values(
        "aras_ncr_progress",
        {
            "状态": "已完成",
            "项目": "F610S",
            "区域": "标准架构集成科",
            "当前节点及通知时间": "财务部总监",
            "是否审批完成": "是",
        },
    )
    rows = normalize_form_rows(
        "aras_ncr_progress",
        [{"values": values, "sheet_name": "Sheet1"}],
        snapshot_at="2026-09-01T10:00:00Z",
    )
    assert rows[0]["dimensions"]["stage"] == "CLOSE"
    assert rows[0]["isCompleted"] is True


def test_daily_trend_keeps_last_snapshot_of_each_day() -> None:
    snapshots = [
        {"snapshotAt": "2026-08-30T08:00:00Z", "summary": {"total": 10, "incomplete": 7, "overdue": 2}},
        {"snapshotAt": "2026-08-30T18:00:00Z", "summary": {"total": 12, "incomplete": 6, "overdue": 1}},
        {"snapshotAt": "2026-08-31T09:00:00Z", "summary": {"total": 13, "incomplete": 5, "overdue": 1}},
    ]

    trend = aggregate_daily_trend(snapshots, limit=30)

    assert trend == [
        {
            "day": "2026-08-30",
            "snapshotAt": "2026-08-30T18:00:00Z",
            "total": 12,
            "incomplete": 6,
            "overdue": 1,
        },
        {
            "day": "2026-08-31",
            "snapshotAt": "2026-08-31T09:00:00Z",
            "total": 13,
            "incomplete": 5,
            "overdue": 1,
        },
    ]


def test_snapshot_input_is_secret_free() -> None:
    snapshot = FormSnapshotInput(
        form_key="aras_paa",
        report_type="paa",
        source_run_id=7,
        snapshot_at="2026-09-01T10:00:00Z",
        schema={"columns": []},
        rows=(
            {
                "rowKey": "PAA-1",
                "values": ["PAA-1", "CLOZ"],
                "dimensions": {"department": "部门A"},
            },
        ),
        summary={"total": 1},
        charts={},
        artifacts=({"display_name": "paa.json", "relative_path": "aras/paa/paa.json"},),
    )

    serialized = json.dumps(snapshot.to_dict(), ensure_ascii=False)
    assert "password" not in serialized.casefold()
    assert "cookie" not in serialized.casefold()
    assert "authorization" not in serialized.casefold()
    assert "lease" not in serialized.casefold()
