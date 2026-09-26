# -*- coding: utf-8 -*-
"""Offline tests for the unified deliverable form analysis contract."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from zipfile import ZipFile

import pytest

from core.section_rollup import build_rollup_index
from services.aras_ncr_workbook import NcrWorkbookRow
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


_NCR_ROLE_LABELS = (
    "NCR管理员", "PE科室经理", "价值工程师", "价值工程经理", "PE部门总监",
    "财务工程师", "平台项目管理专家", "海外项目总监", "平台首席",
    "动力平台首席", "财务部总监",
)


def _column_indexes(form_key: str, label: str) -> list[int]:
    return [
        int(column["index"])
        for column in form_definition(form_key)["columns"]
        if column["label"] == label
    ]


def _ncr_progress_role_values() -> list[object | None]:
    """真实契约形状的位置值：11 个办理时间日期 + 11 个执行人姓名（标签同名）。"""
    values = _ncr_values(
        "aras_ncr_progress",
        {
            "状态": "审批中",
            "项目": "F610S",
            "区域": "标准架构集成科",
            "当前节点及通知时间": "PE科室经理",
            "NCR编号": "NCR-2026-001",
            "PE填写": "2026-08-20",
        },
    )
    for offset, role in enumerate(_NCR_ROLE_LABELS):
        date_index, owner_index = _column_indexes("aras_ncr_progress", role)
        values[date_index] = f"2026-08-{21 + offset:02d}"
        values[owner_index] = f"执行人{offset + 1}"
    return values


def _ncr_named_row(values: list[object | None]) -> dict[str, object]:
    """按已批准表头标签命名并携带位置视图的行（sync / archive 两条路径的实际形状）。"""
    labels = {
        str(column["label"]): values[index]
        for index, column in enumerate(form_definition("aras_ncr_progress")["columns"])
        if column.get("label")
    }
    return NcrWorkbookRow(
        values=tuple(values), labels=labels, sheet_name="Sheet1"
    ).named_row()


def test_duplicate_label_ncr_rows_restore_all_stage_dates_via_positional_view() -> None:
    """重复标签行必须靠位置视图还原：11 个办理时间日期不得被执行人姓名覆盖。

    契约里 11 个角色标签各出现两次（办理时间 / 执行人），标签字典只能保留一个。
    命名行携带契约顺序的 `values`，读取侧位置优先，因此阶段日期与位置行路径同源。
    """
    values = _ncr_progress_role_values()
    named = _ncr_named_row(values)

    rows = normalize_form_rows(
        "aras_ncr_progress", [named], snapshot_at="2026-09-01T10:00:00Z"
    )
    positional = normalize_form_rows(
        "aras_ncr_progress",
        [{"values": values, "sheet_name": "Sheet1"}],
        snapshot_at="2026-09-01T10:00:00Z",
    )

    # 11 组日期与执行人各自保留（同名标签不再互相覆盖）。
    restored = rows[0]["values"]
    for offset, role in enumerate(_NCR_ROLE_LABELS):
        date_index, owner_index = _column_indexes("aras_ncr_progress", role)
        assert restored[date_index] == f"2026-08-{21 + offset:02d}"
        assert restored[owner_index] == f"执行人{offset + 1}"

    # 阶段口径与位置行路径一致（当前节点 PE科室经理 → 起点 08-22、下一节点 08-23）。
    assert rows[0]["dimensions"] == positional[0]["dimensions"]
    assert rows[0]["stageStart"] == positional[0]["stageStart"] == "2026-08-22"
    assert rows[0]["stageEnd"] == positional[0]["stageEnd"] == "2026-08-23"
    assert rows[0]["overdueState"] == positional[0]["overdueState"] == "on_time"
    assert rows[0]["isCompleted"] == positional[0]["isCompleted"] is False

    # 行身份保持修复前语义：带位置视图不改变按 NCR编号计算的 rowKey。
    labels_only = dict(named)
    labels_only.pop("values")
    legacy = normalize_form_rows(
        "aras_ncr_progress", [labels_only], snapshot_at="2026-09-01T10:00:00Z"
    )
    assert legacy[0]["rowKey"] == rows[0]["rowKey"]


def test_legacy_label_only_ncr_rows_disclose_ambiguous_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只带标签键的历史行：同名标签列已不可逆合并，必须披露而不是静默降级。

    历史（旧版写入）命名行没有位置视图。这里锁定三件事：
    ① 不崩坏（维度仍可读）；
    ② 同名列**不还原**——绝不把执行人姓名写进办理时间列（列渲染按位置取值，
       旧版就是靠"复制同一个值到每一列"把姓名塞进日期列的）；
    ③ 发出有界诊断，载荷键落在录制白名单内（可被运维读到）。
    """
    values = _ncr_progress_role_values()
    legacy_row = _ncr_named_row(values)
    legacy_row.pop("values")

    events: list[tuple[str, object, str]] = []
    monkeypatch.setattr(
        "services.deliverable_form_analysis.emit",
        lambda kind, data=None, *, name="", exception=None: events.append(
            (kind, data, name)
        ),
    )

    legacy = normalize_form_rows(
        "aras_ncr_progress", [legacy_row], snapshot_at="2026-09-01T10:00:00Z"
    )

    # ① 维度仍可读；本节点到达日丢失（退回 PE填写 日期 08-20），下一节点为空。
    assert legacy[0]["dimensions"]["stage"] == "PE科室经理"
    assert legacy[0]["stageStart"] == "2026-08-20"  # PE填写，并非本节点到达日
    assert legacy[0]["stageEnd"] is None

    # ② 同名列一律留空：办理时间列不得出现执行人姓名。
    restored = legacy[0]["values"]
    for offset, role in enumerate(_NCR_ROLE_LABELS):
        date_index, owner_index = _column_indexes("aras_ncr_progress", role)
        assert restored[date_index] is None, (role, restored[date_index])
        assert restored[owner_index] is None
    assert "执行人" not in legacy[0]["searchText"]

    # ③ 诊断存在且载荷键可被录制层转发（非白名单键会被整体丢弃）。
    assert [event[0] for event in events] == ["forms.ambiguous_header_labels"]
    kind, data, name = events[0]
    assert data == {
        "report_type": "ncr_progress",
        "row_count": 1,
        "remedy": "reproject_from_archived_workbook",
    }
    assert name == "forms.normalize_form_rows"

    # 同一数据带位置视图时不再产生诊断，且日期可还原。
    events.clear()
    fixed = normalize_form_rows(
        "aras_ncr_progress",
        [_ncr_named_row(values)],
        snapshot_at="2026-09-01T10:00:00Z",
    )
    assert events == []
    assert fixed[0]["stageStart"] == "2026-08-22"


def test_label_named_ncr_detail_rows_keep_cost_and_sheet() -> None:
    """NCR 明细的命名行同样保留六个成本字段（与位置行一致）。"""
    common = {
        "状态": "已完成",
        "项目": "F888Y",
        "区域": "车身工程科",
        "NCR编号": "NCR-D-1",
        "当前节点": "CLOSE",
        "测算工程工装费用(万元)": "10",
        "批准工程工装费用（万元）": "9",
        "实际工程工装费用(万元)": "8",
        "测算单件成本变化（元）": "3",
        "批准单件成本变化（元）": "2",
        "实际单件成本变化（元）": "-1",
    }
    positional = normalize_form_rows(
        "aras_ncr_detail",
        [{"values": _ncr_values("aras_ncr_detail", common), "sheet_name": "整车"}],
        snapshot_at="2026-09-01T10:00:00Z",
    )
    named = normalize_form_rows(
        "aras_ncr_detail",
        [{**common, "sheetName": "整车"}],
        snapshot_at="2026-09-01T10:00:00Z",
    )

    assert named[0]["cost"] == positional[0]["cost"]
    assert named[0]["cost"]["vehicleChangeDirection"] == "decrease"
    assert named[0]["dimensions"] == positional[0]["dimensions"]
    assert named[0]["sheetName"] == "整车"


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


def test_tdc_data_model_completed_statuses_exact_match() -> None:
    """数模设计审核扩充完成态词表（严格全等，杜绝子串误判）。"""
    from services.deliverable_form_analysis import TDC_DATA_MODEL_COMPLETED_STATUSES

    expected_completed = {
        "4", "已完成", "完成", "审批完成", "审批通过", "已归档", "归档", "已发布", "流程结束", "已生效"
    }
    assert TDC_DATA_MODEL_COMPLETED_STATUSES == expected_completed

    # 1. 验证全部合法完成态均判定为 isCompleted=True，且逾期状态为 not_applicable
    for status in sorted(expected_completed):
        rows = normalize_form_rows(
            "tdc_data_model",
            [{"values": _tdc_values(status), "sheetName": "Sheet1"}],
            snapshot_at="2026-09-02T00:00:00Z",
        )
        assert len(rows) == 1
        assert rows[0]["isCompleted"] is True, f"status {status} should be completed"
        assert rows[0]["overdueState"] == "not_applicable"

    # 2. 严格全等断言：杜绝子串匹配，含“通过”的“审核不通过”严禁被误判为完成！
    negative_statuses = ["审核不通过", "不通过", "审批未通过", "未完成", "已拒绝", "通过审核中", "退回"]
    for status in negative_statuses:
        rows = normalize_form_rows(
            "tdc_data_model",
            [{"values": _tdc_values(status), "sheetName": "Sheet1"}],
            snapshot_at="2026-09-02T00:00:00Z",
        )
        assert len(rows) == 1
        assert rows[0]["isCompleted"] is False, f"status {status} must NOT be completed"
        assert rows[0]["overdueState"] != "not_applicable"


def test_tdc_data_model_status_extracted_from_flowstatus_and_flow_status_keys() -> None:
    """数模设计审核支持从 status、flowStatus、流程状态多别名取值。"""
    for key in ("status", "flowStatus", "流程状态"):
        row_dict = {
            "incident": "90000301",
            "requestDate": "2026-08-30",
            "projectModel": "F610S",
            key: "审批通过",
        }
        rows = normalize_form_rows(
            "tdc_data_model",
            [row_dict],
            snapshot_at="2026-09-02T00:00:00Z",
        )
        assert len(rows) == 1
        assert rows[0]["isCompleted"] is True
        assert rows[0]["dimensions"]["status"] == "审批通过"


def test_tdc_data_model_no_actual_date_written() -> None:
    """Field Authority 隔离：严禁生成或回写 actual_date。"""
    rows = normalize_form_rows(
        "tdc_data_model",
        [{"values": _tdc_values("审批通过"), "sheetName": "Sheet1"}],
        snapshot_at="2026-09-02T00:00:00Z",
    )
    assert len(rows) == 1
    assert "actualDate" not in rows[0]
    assert "actual_date" not in rows[0]
    assert rows[0]["plannedDate"] is None


# ── SOR 定点流程（tdc_sor，TDC 15 列导出） ────────────────────────────────────


def _sor_row_values(**labeled: object) -> list[object | None]:
    """构造一条合成的 15 列 SOR 位置行（全部为虚构数据）。"""
    headers = form_definition("tdc_sor")["headerRows"][0]
    values: list[object | None] = [None] * len(headers)
    for label, value in labeled.items():
        values[headers.index(label)] = value
    return values


def test_tdc_sor_is_registered_with_15_column_contract() -> None:
    """SOR 按官方 15 列合同注册，无隐藏列，默认全部可见。"""
    assert "tdc_sor" in FORM_KEYS

    definition = form_definition("tdc_sor")

    assert definition["reportType"] == "tdc_sor"
    assert definition["sheetNames"] == ["Sheet1"]
    assert len(definition["headerRows"][0]) == 15
    assert len(definition["columns"]) == 15
    assert definition["defaultVisibleCount"] == 15
    assert definition["chartFields"] == []
    assert definition["overdueRules"]["stageDays"] == 7


def test_tdc_sor_header_rows_keep_dimensions_and_mask_contacts() -> None:
    """官方中文表头行恢复位置行：维度正确、联系人列脱敏。"""
    rows = normalize_form_rows(
        "tdc_sor",
        [
            {
                "流水单号": "F999X-SOR-001",
                "车型项目": "F999X",
                "类型": "定点",
                "部门": "车身开发部",
                "科室": "车身科",
                "零件号": "27000001",
                "零件名称": "组件A",
                "申请日期": "2026-08-20",
                "审批状态": "已完成",
                "当前待办人": "13800138000",
            }
        ],
        snapshot_at="2026-09-01T10:00:00Z",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["dimensions"]["section"] == "车身科"
    assert row["dimensions"]["department"] == "车身开发部"
    assert row["dimensions"]["model"] == "定点"
    assert row["dimensions"]["stage"] == "F999X"
    assert row["dimensions"]["status"] == "已完成"
    assert row["isCompleted"] is True
    assert "13800138000" not in json.dumps(row, ensure_ascii=False)
    assert "****" in json.dumps(row, ensure_ascii=False)


def test_tdc_sor_api_rows_normalize_status_and_overdue() -> None:
    """API 字典行同样可归一：英文状态转中文，审批中滞留记为逾期。"""
    rows = normalize_form_rows(
        "tdc_sor",
        [
            {
                "processNo": "F999X-SOR-002",
                "carTypeProject": "F999X",
                "processType": "变更",
                "deptName": "内饰开发部",
                "sectionName": "内饰科",
                "startTime": "2026-08-01",
                "processInstanceStatus": "审批中",
            },
            {
                "processNo": "E50-SOR-003",
                "carTypeProject": "E50",
                "sectionName": "底盘科",
                "startTime": "2026-08-28",
                "processInstanceStatus": "Completed",
            },
            {
                "processNo": "E50-SOR-004",
                "carTypeProject": "E50",
                "sectionName": "底盘科",
                "startTime": "2026-08-01",
                "processInstanceStatus": "Terminated",
            },
        ],
        snapshot_at="2026-09-06T10:00:00Z",
    )

    assert [row["dimensions"]["status"] for row in rows] == [
        "审批中", "已完成", "已终止",
    ]
    assert rows[0]["overdueState"] == "overdue"
    assert rows[0]["isCompleted"] is False
    assert rows[1]["isCompleted"] is True
    assert rows[1]["overdueState"] == "not_applicable"
    # 已终止为终态：不计完成、不判逾期、不计入未完成。
    assert rows[2]["isCompleted"] is False
    assert rows[2]["overdueState"] == "not_applicable"

    snapshot = build_form_snapshot(
        "tdc_sor",
        rows,
        snapshot_at="2026-09-06T10:00:00Z",
        source_run_id=1,
        source="test",
    )
    assert snapshot.summary["total"] == 3
    assert snapshot.summary["completed"] == 1
    assert snapshot.summary["incomplete"] == 1
    assert snapshot.summary["overdue"] == 1


# ===== 部门总状态双分页看板：科室归集矩阵 / NCR明细科室计数 =====


def _rollup_index() -> dict[str, str]:
    return build_rollup_index(
        {
            "targets": [
                {"target": "车身科", "aliases": ["结构工程科", "车门附件科"]},
                {"target": "内饰科", "aliases": []},
            ],
        }
    )


def test_section_stage_matrix_pivots_share_rollup_cells() -> None:
    rows = [
        {"dimensions": {"section": "车身科", "stage": "PROC"}, "overdueState": "on_time", "isCompleted": False},
        {"dimensions": {"section": "结构工程科", "stage": "PROC"}, "overdueState": "overdue", "isCompleted": False},
        {"dimensions": {"section": "内饰科", "stage": "CLOSE"}, "overdueState": "on_time", "isCompleted": True},
        {"dimensions": {"section": "车身科", "stage": "OPEN"}, "overdueState": "on_time", "isCompleted": False},
        {"dimensions": {"section": "神秘历史科室", "stage": "PROC"}, "overdueState": "unknown", "isCompleted": False},
        {"dimensions": {"section": "车门附件科", "stage": ""}, "overdueState": "on_time", "isCompleted": False},
    ]

    summary = summarize_form_rows(
        "VPI-T2-D3",
        rows,
        snapshot_at="2026-09-01T10:00:00Z",
        section_rollup=_rollup_index(),
    )

    matrix = summary["sectionStageMatrix"]
    # 科室行 = 规则目标顺序 + 「未归集」；空 stage 行不计入矩阵。
    assert [entry["label"] for entry in matrix["sections"]] == ["车身科", "内饰科", "未归集"]
    assert [entry["total"] for entry in matrix["sections"]] == [3, 1, 1]
    # 节点列 = EWO 官方全量（含零计数）+「其他状态」收尾。
    assert [entry["label"] for entry in matrix["stages"]] == [
        "DRAFT1", "DRAFT2", "EDIT1", "EDIT2", "PROC", "IMPL", "CLOSE", "其他状态",
    ]
    proc_stage = matrix["stages"][4]
    assert proc_stage["total"] == 3
    assert [cell["count"] for cell in proc_stage["cells"]] == [2, 0, 1]
    other_stage = matrix["stages"][7]
    assert other_stage["total"] == 1
    assert [cell["count"] for cell in other_stage["cells"]] == [1, 0, 0]
    close_stage = matrix["stages"][6]
    assert [cell["count"] for cell in close_stage["cells"]] == [0, 1, 0]
    # 两个透视的 cells 互相严格对齐（同一份数据）。
    body_section = matrix["sections"][0]
    assert [cell["count"] for cell in body_section["cells"]] == [0, 0, 0, 0, 2, 0, 0, 1]
    # 按期/逾期旧口径键保持不变；sectionStatus 仍为原始值口径。
    assert summary["departmentStatus"]["stages"][4]["onTime"] == 1
    assert {entry["label"] for entry in summary["sectionStatus"]} == {
        "车身科", "结构工程科", "内饰科", "神秘历史科室", "车门附件科",
    }


def test_summary_without_rollup_omits_matrix_and_counts() -> None:
    rows = [
        {"dimensions": {"section": "科室A", "stage": "PROC"}, "overdueState": "on_time", "isCompleted": False},
    ]

    summary = summarize_form_rows("VPI-T2-D3", rows, snapshot_at="2026-09-01T10:00:00Z")

    assert "sectionStageMatrix" not in summary
    assert "sectionCounts" not in summary


def test_ncr_detail_section_counts_with_unassigned_bucket() -> None:
    rows = [
        {"dimensions": {"section": "车身科", "ncrNumber": "N1"}, "overdueState": "on_time", "isCompleted": False},
        {"dimensions": {"section": "车门附件科", "ncrNumber": "N2"}, "overdueState": "on_time", "isCompleted": False},
        {"dimensions": {"section": "未知科室", "ncrNumber": "N3"}, "overdueState": "on_time", "isCompleted": False},
    ]

    summary = summarize_form_rows(
        "aras_ncr_detail",
        rows,
        snapshot_at="2026-09-01T10:00:00Z",
        section_rollup=_rollup_index(),
    )

    assert summary["sectionCounts"] == [
        {"label": "车身科", "total": 2},
        {"label": "内饰科", "total": 0},
        {"label": "未归集", "total": 1},
    ]
