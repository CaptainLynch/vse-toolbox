# -*- coding: utf-8 -*-
"""ARAS NCR 官方工作簿的共享解析与准入契约。

守护目标（用户 2026-09-25 架构定案）：
1. 同步路径与归档路径共用同一解析实现，产出同一「按已批准表头标签命名」的行；
2. 官方工作簿没有声明总数 → 准入策略为「表头契约 + 逐行归类核对 + 未截断」，
   任一疑点 fail-closed，不得把可能的部分数据当完整；
3. 簿记事实（读取/解析/空行/表头/未归类/契约外单元格）随结果披露。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.report_contracts import report_contracts
from services.aras_ncr_workbook import (
    NcrWorkbookError,
    parse_ncr_workbook,
    require_complete_workbook,
)
from services.xlsx_preview import XLSXPreviewError


def _preview(name: str, rows: list[list[object]], truncated: bool = False) -> SimpleNamespace:
    return SimpleNamespace(sheet_name=name, rows=rows, truncated=truncated)


def _patch_reader(monkeypatch: pytest.MonkeyPatch, *previews: SimpleNamespace) -> None:
    monkeypatch.setattr(
        "services.aras_ncr_workbook.read_xlsx_workbook_preview",
        lambda *args, **kwargs: tuple(previews),
    )


def _labels(report_type: str) -> list[str]:
    contract = report_contracts()[report_type]
    header_index = 1 if report_type == "ncr_progress" else 0
    return [str(value or "").strip() for value in contract["headerRows"][header_index]]


def _progress_rows(count: int = 1, **overrides: object) -> list[list[object]]:
    labels = _labels("ncr_progress")
    rows: list[list[object]] = [[None] * len(labels), labels]
    for index in range(count):
        row: list[object] = [""] * len(labels)
        row[0] = str(overrides.get("状态", "审批中"))
        row[4] = str(overrides.get("项目", "F610S"))
        row[6] = str(overrides.get("区域", "车体工程科"))
        row[7] = f"NCR-SYNTH-{index + 1}"
        rows.append(row)
    return rows


def test_progress_workbook_parses_into_label_named_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """按已批准表头标签命名的行：与同步路径同形，簿记平衡即准入。"""
    _patch_reader(monkeypatch, _preview("Sheet1", _progress_rows(2)))

    outcome = parse_ncr_workbook(tmp_path / "ncr.xlsx", "ncr_progress")

    assert outcome.complete is True
    assert outcome.stop_reason == "workbook_rows"
    assert outcome.projection_error is None
    rows = outcome.named_rows()
    assert [row["NCR编号"] for row in rows] == ["NCR-SYNTH-1", "NCR-SYNTH-2"]
    assert rows[0]["状态"] == "审批中"
    assert rows[0]["sheetName"] == "Sheet1"
    facts = outcome.bookkeeping_facts()
    assert facts["rowsRead"] == 2 + 2
    assert facts["rowsParsed"] == 2
    assert facts["rowsHeader"] == 2
    assert facts["rowsUnclassified"] == 0


def test_progress_workbook_skips_secondary_summary_sheets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """NCR 进度的第二张表是过滤摘要：按契约跳过并计入表头行。"""
    _patch_reader(
        monkeypatch,
        _preview("Sheet1", _progress_rows(1)),
        _preview("过滤摘要", [["过滤条件"], ["项目", "F610S"]]),
    )

    outcome = parse_ncr_workbook(tmp_path / "ncr.xlsx", "ncr_progress")

    assert outcome.complete is True
    assert len(outcome.named_rows()) == 1
    assert outcome.bookkeeping_facts()["rowsHeader"] == 2 + 2


def test_unclassified_row_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """非空但契约列内没有任何值 → 未归类 → fail-closed，不得静默丢行。"""
    labels = _labels("ncr_progress")
    rows = _progress_rows(1)
    wide: list[object] = [""] * (len(labels) + 3)
    wide[-1] = "契约外内容"
    rows.append(wide)
    _patch_reader(monkeypatch, _preview("Sheet1", rows))

    outcome = parse_ncr_workbook(tmp_path / "ncr.xlsx", "ncr_progress")

    assert outcome.stop_reason == "workbook_rows_unclassified"
    assert outcome.complete is False
    assert outcome.bookkeeping_facts()["rowsUnclassified"] == 1
    with pytest.raises(NcrWorkbookError, match="workbook_rows_unclassified"):
        require_complete_workbook(outcome)


def test_structural_row_error_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """出现非行结构（无法逐列对齐）→ workbook_rows_rejected。"""
    rows = _progress_rows(1)
    rows.append("not-a-row")  # type: ignore[arg-type]
    _patch_reader(monkeypatch, _preview("Sheet1", rows))

    outcome = parse_ncr_workbook(tmp_path / "ncr.xlsx", "ncr_progress")

    assert outcome.stop_reason == "workbook_rows_rejected"
    assert outcome.complete is False
    # 被读取却无法归类的行仍要计入账目，避免"读了但哪里都没算"的缺口。
    facts = outcome.bookkeeping_facts()
    assert facts["rowsUnclassified"] == 1
    assert outcome.bookkeeping.accounted_rows() == outcome.bookkeeping.read_rows


def test_truncated_and_empty_workbooks_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """截断与空表（仅表头）都必须 fail-closed，并有明确停机原因。"""
    _patch_reader(monkeypatch, _preview("Sheet1", _progress_rows(1), truncated=True))
    truncated = parse_ncr_workbook(tmp_path / "ncr.xlsx", "ncr_progress")
    assert truncated.stop_reason == "workbook_truncated"
    assert truncated.projection_error == "official_workbook_truncated"

    labels = _labels("ncr_progress")
    _patch_reader(monkeypatch, _preview("Sheet1", [[None] * len(labels), labels]))
    empty = parse_ncr_workbook(tmp_path / "ncr.xlsx", "ncr_progress")
    assert empty.stop_reason == "workbook_empty"
    assert empty.named_rows() == ()


def test_header_mismatch_is_reported_not_silently_projected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """NCR 进度表头必须与已批准契约全等，否则 fail-closed 并给出契约错误码。"""
    labels = _labels("ncr_progress")
    broken = list(labels)
    broken[0] = "未批准的状态列"
    _patch_reader(monkeypatch, _preview("Sheet1", [[None] * len(labels), broken]))

    outcome = parse_ncr_workbook(tmp_path / "ncr.xlsx", "ncr_progress")

    assert outcome.stop_reason == "workbook_header_mismatch"
    assert outcome.projection_error == "official_workbook_contract_invalid"


def test_unreadable_workbook_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """不可读（非 XLSX / 损坏）→ workbook_unreadable，不抛未分类异常。"""

    def _raise(*args: object, **kwargs: object) -> None:
        raise XLSXPreviewError("broken")

    monkeypatch.setattr(
        "services.aras_ncr_workbook.read_xlsx_workbook_preview", _raise
    )

    outcome = parse_ncr_workbook(tmp_path / "ncr.xlsx", "ncr_progress")

    assert outcome.stop_reason == "workbook_unreadable"
    assert outcome.projection_error == "official_workbook_unreadable"
    assert outcome.complete is False


def test_detail_engine_sheet_aligns_by_approved_labels(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """NCR 明细的整车/发动机两种表头按标签对齐到同一套命名列。"""
    vehicle_labels = _labels("ncr_detail")
    engine_labels = list(vehicle_labels[:17]) + list(vehicle_labels[34:])
    values_by_label = {
        "状态": "已完成",
        "NCR编号": "NCR-DET-1",
        "项目": "F888Y",
        "区域": "车身工程科",
        "当前节点": "CLOSE",
        "测算工程工装费用(万元)": "10",
    }

    def row_for(labels: list[str]) -> list[object]:
        return [values_by_label.get(label, "") for label in labels]

    vehicle_rows = [list(vehicle_labels)]
    vehicle_rows.extend([[""] * len(vehicle_labels) for _ in range(4)])
    vehicle_rows.append(row_for(vehicle_labels))
    engine_rows = [list(engine_labels), row_for(engine_labels)]
    _patch_reader(
        monkeypatch,
        _preview("整车", vehicle_rows),
        _preview("发动机", engine_rows),
    )

    outcome = parse_ncr_workbook(tmp_path / "ncr.xlsx", "ncr_detail")

    assert outcome.complete is True
    rows = outcome.named_rows()
    assert [row["sheetName"] for row in rows] == ["整车", "发动机"]
    for row in rows:
        assert row["NCR编号"] == "NCR-DET-1"
        assert row["测算工程工装费用(万元)"] == "10"


#: 与已批准契约一致的 11 个角色标签（各出现两次：办理时间 / 执行人）。
_ROLE_LABELS = (
    "NCR管理员", "PE科室经理", "价值工程师", "价值工程经理", "PE部门总监",
    "财务工程师", "平台项目管理专家", "海外项目总监", "平台首席",
    "动力平台首席", "财务部总监",
)
#: 数据表头里重复标签的「办理时间」组起点与「执行人」组起点。
_ROLE_DATE_START = 37
_ROLE_OWNER_START = 52


def _progress_rows_with_role_groups() -> list[list[object]]:
    """真实契约形状的一行：11 个办理时间日期 + 11 个执行人姓名（标签同名）。"""
    labels = _labels("ncr_progress")
    row: list[object] = [""] * len(labels)
    row[0] = "审批中"
    row[4] = "F610S"
    row[6] = "车体工程科"
    row[7] = "NCR-SYNTH-ROLE-1"
    row[36] = "2026-08-20"
    for offset, _role in enumerate(_ROLE_LABELS):
        row[_ROLE_DATE_START + offset] = f"2026-08-{21 + offset:02d}"
        row[_ROLE_OWNER_START + offset] = f"执行人{offset + 1}"
    return [[None] * len(labels), labels, row]


def test_named_row_carries_authoritative_positional_view_for_duplicate_labels(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """重复标签行：标签字典必然合并同名键，位置视图才是权威值来源。

    契约里 11 个角色标签各出现两次（列 37..47 办理时间，列 52..62 执行人）。
    标签字典只能保留后写入的一个；命名行必须同时携带契约顺序的 `values`，
    否则 11 个办理时间日期会被执行人姓名静默覆盖。
    """
    _patch_reader(
        monkeypatch, _preview("Sheet1", _progress_rows_with_role_groups())
    )

    outcome = parse_ncr_workbook(tmp_path / "ncr.xlsx", "ncr_progress")

    assert outcome.complete is True
    row = outcome.named_rows()[0]
    values = row["values"]
    assert len(values) == len(_labels("ncr_progress")) == 64
    for offset, role in enumerate(_ROLE_LABELS):
        # 位置视图：日期组与执行人组各自保留自己的值。
        assert values[_ROLE_DATE_START + offset] == f"2026-08-{21 + offset:02d}"
        assert values[_ROLE_OWNER_START + offset] == f"执行人{offset + 1}"
        # 标签字典是同名键合并后的结果（历史行为：后写覆盖先写）。
        assert row[role] == f"执行人{offset + 1}"
    assert row["PE填写"] == "2026-08-20"
    assert row["sheetName"] == "Sheet1"


def test_unsupported_report_type_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(NcrWorkbookError, match="unsupported"):
        parse_ncr_workbook(tmp_path / "x.xlsx", "ewo")
