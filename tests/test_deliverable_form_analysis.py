# -*- coding: utf-8 -*-
"""Offline tests for the unified deliverable form analysis contract."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from zipfile import ZipFile

import pytest

from services.deliverable_form_analysis import (
    FORM_KEYS,
    FormSnapshotInput,
    aggregate_daily_trend,
    build_form_snapshot,
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


def test_numeric_and_short_contacts_are_masked_in_stored_values() -> None:
    rows = normalize_form_rows(
        "VPI-T2-D3",
        [
            {
                "_no": "EWO-CONTACT-1",
                "_rsp_phone": 13800138000,
                "state": "PROC",
            },
            {
                "_no": "EWO-CONTACT-2",
                "_rsp_phone": "1234567",
                "state": "PROC",
            },
        ],
        snapshot_at="2026-09-01T10:00:00Z",
    )

    assert rows[0]["values"][13] == "138****8000"
    assert rows[1]["values"][13] == "[contact masked]"
    serialized = json.dumps(rows, ensure_ascii=False)
    assert "13800138000" not in serialized
    assert "1234567" not in serialized


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


def test_ncr_completion_status_text_is_normalized_to_close() -> None:
    values = _ncr_values(
        "aras_ncr_progress",
        {
            "状态": "完成",
            "项目": "F610S",
            "区域": "标准架构集成科",
            "当前节点及通知时间": "LEADER审核",
            "是否审批完成": "否",
        },
    )

    rows = normalize_form_rows(
        "aras_ncr_progress",
        [{"values": values, "sheet_name": "Sheet1"}],
        snapshot_at="2026-09-01T10:00:00Z",
    )

    assert rows[0]["dimensions"]["stage"] == "CLOSE"
    assert rows[0]["isCompleted"] is True
    assert rows[0]["overdueState"] == "not_applicable"


def test_ncr_progress_summary_counts_each_ncr_number_once() -> None:
    """NCR progress status metrics use unique NCR numbers, not physical rows."""
    values = _ncr_values(
        "aras_ncr_progress",
        {
            "状态": "审批中",
            "序号": "1",
            "项目": "F610S",
            "区域": "标准架构集成科",
            "NCR编号": "NCR-UNIQUE-1",
            "当前节点及通知时间": "NCR管理员",
            "PE填写": "2026-08-20",
            "NCR管理员": "2026-08-20",
            "是否审批完成": "否",
        },
    )
    rows = normalize_form_rows(
        "aras_ncr_progress",
        [
            {"values": values, "sheet_name": "Sheet1"},
            {"values": values, "sheet_name": "Sheet1"},
        ],
        snapshot_at="2026-08-25T00:00:00Z",
    )

    summary = summarize_form_rows(
        "aras_ncr_progress",
        rows,
        snapshot_at="2026-08-25T00:00:00Z",
    )

    assert summary["total"] == 1
    assert summary["incomplete"] == 1
    assert summary["overdue"] == 1
    assert summary["departmentStatus"]["stages"][1]["overdue"] == 1
    assert summary["sectionStatus"] == [
        {"label": "标准架构集成科", "onTime": 0, "overdue": 1, "unknown": 0, "total": 1}
    ]


def test_ncr_rows_without_numbers_remain_separate_metric_entities() -> None:
    first = _ncr_values(
        "aras_ncr_progress",
        {
            "状态": "审批中",
            "序号": "1",
            "项目": "F610S",
            "区域": "标准架构集成科",
            "当前节点及通知时间": "NCR管理员",
            "是否审批完成": "否",
        },
    )
    second = _ncr_values(
        "aras_ncr_progress",
        {
            "状态": "审批中",
            "序号": "2",
            "项目": "F610S",
            "区域": "标准架构集成科",
            "当前节点及通知时间": "NCR管理员",
            "是否审批完成": "否",
        },
    )

    rows = normalize_form_rows(
        "aras_ncr_progress",
        [
            {"values": first, "sheet_name": "Sheet1"},
            {"values": second, "sheet_name": "Sheet1"},
        ],
        snapshot_at="2026-08-25T00:00:00Z",
    )

    assert all("ncrNumber" not in row["dimensions"] for row in rows)
    assert summarize_form_rows(
        "aras_ncr_progress",
        rows,
        snapshot_at="2026-08-25T00:00:00Z",
    )["total"] == 2


def test_summary_recovers_completion_from_legacy_ncr_status_dimension() -> None:
    summary = summarize_form_rows(
        "aras_ncr_progress",
        [
            {
                "dimensions": {
                    "department": "",
                    "section": "标准架构集成科",
                    "model": "F610S",
                    "status": "完成",
                    "stage": "LEADER审核",
                },
                "overdueState": "unknown",
                "isCompleted": False,
            }
        ],
        snapshot_at="2026-09-02T00:00:00Z",
    )

    assert summary["completed"] == 1
    assert summary["incomplete"] == 0
    assert summary["overdue"] == 0
    assert summary["departmentStatus"]["stages"][-1] == {
        "label": "CLOSE",
        "onTime": 1,
        "overdue": 0,
        "unknown": 0,
    }


def test_summary_recovers_completion_from_legacy_tdc_status_code() -> None:
    summary = summarize_form_rows(
        "tdc_data_model",
        [
            {
                "dimensions": {
                    "department": "",
                    "section": "内饰科",
                    "model": "T2发布",
                    "status": "4",
                    "stage": "F999X",
                },
                "overdueState": "overdue",
                "isCompleted": False,
            }
        ],
        snapshot_at="2026-09-02T00:00:00Z",
    )

    assert summary["completed"] == 1
    assert summary["incomplete"] == 0
    assert summary["overdue"] == 0


def test_ncr_detail_status_is_unique_but_costs_sum_detail_rows() -> None:
    """NCR detail status counts unique NCRs while cost charts keep row grain."""
    common = {
        "状态": "审批中",
        "项目": "F610S",
        "区域": "标准架构集成科",
        "NCR编号": "NCR-UNIQUE-2",
        "测算工程工装费用(万元)": "10",
        "批准工程工装费用（万元）": "9",
        "实际工程工装费用(万元)": "8",
        "测算单件成本变化（元）": "3",
        "批准单件成本变化（元）": "2",
        "实际单件成本变化（元）": "-1",
    }
    rows = normalize_form_rows(
        "aras_ncr_detail",
        [
            {"values": _ncr_values("aras_ncr_detail", common), "sheet_name": "整车"},
            {
                "values": _ncr_values(
                    "aras_ncr_detail",
                    {**common, "实际工程工装费用(万元)": "12"},
                ),
                "sheet_name": "整车",
            },
        ],
        snapshot_at="2026-08-25T00:00:00Z",
    )

    summary = summarize_form_rows(
        "aras_ncr_detail",
        rows,
        snapshot_at="2026-08-25T00:00:00Z",
    )

    assert summary["total"] == 1
    assert summary["sectionStatus"][0]["total"] == 1
    assert summary["departmentCost"][0]["investment"] == {
        "estimate": 20.0,
        "approved": 18.0,
        "actual": 20.0,
    }
    assert summary["sectionCost"][0]["vehicleChange"] == {
        "estimate": 6.0,
        "approved": 4.0,
        "actual": -2.0,
    }


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


# ── 数模设计审核流程（tdc_data_model，TDC 47 列导出） ─────────────────────────


def _tdc_values(
    status: str = "审批中",
    *,
    request_date: str = "2026-08-20 10:00:00",
    project: str = "F999X",
    section: str = "内饰科",
) -> list[object | None]:
    """构造一条合成的 47 列数模设计审核位置行（全部为虚构数据）。

    以完整表头行（含隐藏的“重量（单件）”“零件合计”索引 12/13）建立
    标签到下标的映射，未列出的列保持空值。
    """
    headers = form_definition("tdc_data_model")["headerRows"][0]
    values: list[object | None] = [None] * len(headers)
    labeled: dict[str, object] = {
        "实例号": "90000101",
        "流程名": "T2发布-组件A",
        "流水单号": "F999X-3D-0001",
        "发布属性": "T2发布",
        "申请人": "测试员甲",
        "部门": section,
        "申请日期": request_date,
        "项目/车型": project,
        "零件号": "27000001",
        "数模号": "27000001",
        "零件名称": "组件A",
        "数量": 1,
        "重量（单件）": 0.8,
        "零件合计": 0.8,
        "版本号": "001.0001",
        "对应IA号": "IA000001",
        "EWO/SOR号": "EWO-000001",
        "应签人数": 13,
        "已签人数": 13,
        "未签人数": 0,
        "签署率": "100.00%",
        "状态": status,
    }
    for label, value in labeled.items():
        values[headers.index(label)] = value
    return values


def test_tdc_data_model_is_registered_with_hidden_columns_contract() -> None:
    """数模表单注册后按 47 列合同暴露，但隐藏两个重量列并固定默认可见数。"""
    assert "tdc_data_model" in FORM_KEYS

    definition = form_definition("tdc_data_model")

    assert definition["reportType"] == "tdc_data_model"
    assert definition["sheetNames"] == ["Sheet1"]
    assert len(definition["headerRows"][0]) == 47
    assert len(definition["columns"]) == 45
    assert all(column["index"] not in {12, 13} for column in definition["columns"])
    assert definition["defaultVisibleCount"] == 15
    assert definition["chartFields"] == []
    assert definition["filterFields"] == [
        "keyword",
        "status",
        "department",
        "section",
        "model",
        "stage",
        "dateStart",
        "dateEnd",
    ]


def test_tdc_positional_rows_extract_dimensions_and_overdue_integration() -> None:
    """位置行按标签抽取维度；申请日期同时是提交日期与逾期判定起点。"""
    rows = normalize_form_rows(
        "tdc_data_model",
        [{"values": _tdc_values("审批中"), "sheetName": "Sheet1"}],
        snapshot_at="2026-09-02T00:00:00Z",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["dimensions"] == {
        "department": "",
        "section": "内饰科",
        "model": "T2发布",
        "status": "审批中",
        "stage": "F999X",
    }
    assert row["submittedDate"] == "2026-08-20"
    assert row["stageStart"] == "2026-08-20"
    assert row["isCompleted"] is False
    assert row["overdueState"] == "overdue"
    assert row["sheetName"] == "Sheet1"
    assert len(row["values"]) == 47
    assert row["values"][12] == 0.8
    assert row["values"][13] == 0.8
    assert "27000001" in row["searchText"]


def test_tdc_terminal_states_are_not_applicable() -> None:
    """“已完成”是完成态，“已废弃”是终态；两者都不参与逾期判定。"""
    rows = normalize_form_rows(
        "tdc_data_model",
        [
            {"values": _tdc_values("已完成"), "sheetName": "Sheet1"},
            {"values": _tdc_values("已废弃"), "sheetName": "Sheet1"},
        ],
        snapshot_at="2026-09-02T00:00:00Z",
    )

    assert rows[0]["isCompleted"] is True
    assert rows[0]["overdueState"] == "not_applicable"
    assert rows[1]["isCompleted"] is False
    assert rows[1]["overdueState"] == "not_applicable"


@pytest.mark.parametrize(
    ("request_date", "expected"),
    [
        ("2026-08-26 08:00:00", "on_time"),
        ("2026-08-25 08:00:00", "overdue"),
        ("", "unknown"),
    ],
)
def test_tdc_overdue_dwell_boundary_is_seven_days(
    request_date: str,
    expected: str,
) -> None:
    """审批中记录以申请日期起滞留超过 7 天记逾期；无申请日期记 unknown。"""
    rows = normalize_form_rows(
        "tdc_data_model",
        [{"values": _tdc_values("审批中", request_date=request_date), "sheetName": "Sheet1"}],
        snapshot_at="2026-09-02T00:00:00Z",
    )

    assert rows[0]["overdueState"] == expected


@pytest.mark.parametrize(
    ("request_date", "expected"),
    [
        ("2026-08-20 10:00:00", "overdue"),
        ("", "unknown"),
    ],
)
def test_tdc_overdue_does_not_depend_on_project_value(
    request_date: str,
    expected: str,
) -> None:
    """项目/车型为空的审批中记录仍按申请日期滞留判定，不被 stage 守卫短路。"""
    rows = normalize_form_rows(
        "tdc_data_model",
        [
            {
                "values": _tdc_values("审批中", request_date=request_date, project=""),
                "sheetName": "Sheet1",
            }
        ],
        snapshot_at="2026-09-02T00:00:00Z",
    )

    assert rows[0]["overdueState"] == expected


def test_tdc_summary_aggregates_observed_stages_and_section_buckets() -> None:
    """数模汇总按观察到的项目/车型聚合阶段；已废弃行不落入逾期或按期桶。"""
    rows = normalize_form_rows(
        "tdc_data_model",
        [
            {"values": _tdc_values("已完成"), "sheetName": "Sheet1"},
            {
                "values": _tdc_values("审批中", project="F888Y"),
                "sheetName": "Sheet1",
            },
            {"values": _tdc_values("已废弃"), "sheetName": "Sheet1"},
        ],
        snapshot_at="2026-09-02T00:00:00Z",
    )

    summary = summarize_form_rows(
        "tdc_data_model",
        rows,
        snapshot_at="2026-09-02T00:00:00Z",
    )

    assert summary["total"] == 3
    assert summary["completed"] == 1
    assert summary["incomplete"] == 1
    assert summary["overdue"] == 1
    assert summary["departmentStatus"]["stages"] == [
        {"label": "F888Y", "onTime": 0, "overdue": 1, "unknown": 0},
        {"label": "F999X", "onTime": 1, "overdue": 0, "unknown": 1},
    ]
    assert summary["sectionStatus"] == [
        {"label": "内饰科", "onTime": 1, "overdue": 1, "unknown": 1, "total": 3},
    ]


def test_tdc_dict_rows_extract_dimensions_and_incident_identity() -> None:
    """TDC 爬取字典行按 JSON 键名抽取维度；实例号参与行身份。"""
    base = {
        "incident": "90000201",
        "documentNo": "F888Y-3D-0002",
        "requestDate": "2026-08-30 09:30:00",
        "projectModel": "F888Y",
        "department": "车身科",
        "publishProperty": "T2发布",
        "status": "审批中",
    }

    rows = normalize_form_rows(
        "tdc_data_model",
        [dict(base)],
        snapshot_at="2026-09-02T00:00:00Z",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["dimensions"] == {
        "department": "",
        "section": "车身科",
        "model": "T2发布",
        "status": "审批中",
        "stage": "F888Y",
    }
    assert row["submittedDate"] == "2026-08-30"
    assert row["stageStart"] == "2026-08-30"
    assert row["isCompleted"] is False
    assert row["overdueState"] == "on_time"

    other = normalize_form_rows(
        "tdc_data_model",
        [{**base, "incident": "90000202"}],
        snapshot_at="2026-09-02T00:00:00Z",
    )
    assert other[0]["rowKey"] != row["rowKey"]


def test_tdc_numeric_completion_status_is_normalized_for_mapping_rows() -> None:
    rows = normalize_form_rows(
        "tdc_data_model",
        [
            {
                "incident": "90000203",
                "requestDate": "2026-08-30",
                "projectModel": "F888Y",
                "status": "4",
            }
        ],
        snapshot_at="2026-09-02T00:00:00Z",
    )

    assert rows[0]["dimensions"]["status"] == "已完成"
    assert rows[0]["isCompleted"] is True
    assert rows[0]["overdueState"] == "not_applicable"


def test_tdc_numeric_completion_status_is_normalized_for_positional_rows() -> None:
    rows = normalize_form_rows(
        "tdc_data_model",
        [{"values": _tdc_values("4"), "sheetName": "Sheet1"}],
        snapshot_at="2026-09-02T00:00:00Z",
    )

    assert rows[0]["dimensions"]["status"] == "已完成"
    assert rows[0]["values"][46] == "已完成"
    assert rows[0]["isCompleted"] is True
    assert rows[0]["overdueState"] == "not_applicable"


def test_tdc_official_header_mapping_rows_preserve_values_and_dimensions() -> None:
    """Official TDC export dictionaries use Chinese contract headers, not API keys."""
    headers = form_definition("tdc_data_model")["headerRows"][0]
    values = _tdc_values("审批中", request_date="2026-08-30 09:30:00")
    source = {str(header): value for header, value in zip(headers, values)}

    rows = normalize_form_rows(
        "tdc_data_model",
        [source],
        snapshot_at="2026-09-02T00:00:00Z",
        sheet_name="Sheet1",
    )

    assert rows[0]["dimensions"] == {
        "department": "",
        "section": "内饰科",
        "model": "T2发布",
        "status": "审批中",
        "stage": "F999X",
    }
    assert rows[0]["submittedDate"] == "2026-08-30"
    assert rows[0]["values"][6] == "2026-08-30 09:30:00"
    assert rows[0]["values"][16] == "EWO-000001"


def test_tdc_build_form_snapshot_returns_publishable_contract() -> None:
    """位置行构建的快照携带 45 列 schema、汇总与两个状态图表。"""
    snapshot = build_form_snapshot(
        "tdc_data_model",
        [
            {
                "values": _tdc_values("审批中", request_date="2026-08-30 09:30:00"),
                "sheetName": "Sheet1",
            },
            {"values": _tdc_values("已完成"), "sheetName": "Sheet1"},
        ],
        snapshot_at="2026-09-02T00:00:00Z",
        source_run_id=11,
        source="tdc",
    )

    assert snapshot.form_key == "tdc_data_model"
    assert snapshot.report_type == "tdc_data_model"
    assert snapshot.source == "tdc"
    assert snapshot.source_run_id == 11
    assert len(snapshot.schema["columns"]) == 45
    assert snapshot.summary["total"] == 2
    assert snapshot.summary["completed"] == 1
    assert set(snapshot.charts) == {"departmentStatus", "sectionStatus"}
    assert snapshot.rows[0]["overdueState"] == "on_time"
    assert snapshot.rows[1]["isCompleted"] is True
