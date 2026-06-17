# -*- coding: utf-8 -*-
"""
tests/test_excel_toolbox.py — ExcelToolbox 单元测试（E3）

策略: monkeypatch _get_win32com，注入 MagicMock 伪 Excel.Application，
      验证 COM 调用序列、备份/回滚、高亮、图例、Quit、PermissionError 等行为，
      无需启动真实 Excel 进程。
"""

from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

import services.excel_toolbox as et_module
from services.excel_toolbox import ExcelToolbox, MORANDI_PALETTE


# ────────────────────────── helpers ──────────────────────────────

def _make_fake_sheet(sheet_data: list[list]) -> MagicMock:
    """构造伪 Sheet，Cells 按 sheet_data 返回对应 Value，白色底色（不与莫兰迪撞色）。"""
    mock_sheet = MagicMock()
    mock_sheet.UsedRange.Rows.Count = len(sheet_data)
    mock_sheet.UsedRange.Columns.Count = len(sheet_data[0]) if sheet_data else 1

    def cells_side_effect(r, c):
        cell = MagicMock()
        cell.Value = sheet_data[r - 1][c - 1] if r <= len(sheet_data) and c <= len(sheet_data[0]) else None
        cell.Formula = ""
        cell.Interior.Color = 0xFFFFFF
        return cell

    mock_sheet.Cells.side_effect = cells_side_effect
    return mock_sheet


def _make_fake_workbook(sheet: MagicMock) -> MagicMock:
    """构造伪 Workbook。"""
    mock_wb = MagicMock()
    mock_wb.ActiveSheet = sheet
    mock_wb.Sheets.return_value = sheet
    return mock_wb


def _make_excel_with_open_map(
    add_data: list[list],
    open_map: dict[str, list[list]] | None = None,
) -> MagicMock:
    """
    构造伪 Excel.Application，支持区分 Workbooks.Open 的不同文件路径。

    add_data:  Workbooks.Add() 返回的工作簿数据（输出簿）
    open_map:  {绝对路径字符串: sheet_data}，按调用顺序通过 side_effect 分发。
               若为 None，则所有 Open 调用均返回同一个空数据簿。
    """
    add_sheet = _make_fake_sheet(add_data)
    add_wb = _make_fake_workbook(add_sheet)

    mock_excel = MagicMock()
    mock_excel.Workbooks.Add.return_value = add_wb

    if open_map:
        # 按路径字符串匹配返回对应工作簿
        def open_side_effect(path_str):
            for key, data in open_map.items():
                if key in path_str:
                    sheet = _make_fake_sheet(data)
                    wb = _make_fake_workbook(sheet)
                    return wb
            sheet = _make_fake_sheet([])
            return _make_fake_workbook(sheet)

        mock_excel.Workbooks.Open.side_effect = open_side_effect
    else:
        empty_sheet = _make_fake_sheet([])
        empty_wb = _make_fake_workbook(empty_sheet)
        mock_excel.Workbooks.Open.return_value = empty_wb

    return mock_excel, add_wb


def _inject_excel(monkeypatch, mock_excel: MagicMock) -> None:
    """将 mock_excel 注入为 _get_win32com() 的返回值。"""
    monkeypatch.setattr(
        et_module, "_get_win32com",
        lambda: MagicMock(Dispatch=lambda _: mock_excel)
    )


# ────────────────────────── fixtures ─────────────────────────────

@pytest.fixture
def toolbox(tmp_path, monkeypatch) -> ExcelToolbox:
    """返回使用 tmp_path 作为 BACKUP_DIR/OUTPUT_DIR 的 ExcelToolbox 实例。"""
    monkeypatch.setattr(et_module, "BACKUP_DIR", tmp_path / ".backup")
    monkeypatch.setattr(et_module, "OUTPUT_DIR", tmp_path / "output")
    (tmp_path / ".backup").mkdir()
    (tmp_path / "output").mkdir()
    return ExcelToolbox()


@pytest.fixture
def toolbox_with_mock_excel(toolbox, tmp_path, monkeypatch):
    """
    返回 (toolbox, mock_excel, out_wb) 三元组，mock 已注入到 _get_win32com。
    适用于只需验证 SaveAs/Quit 等基础调用的测试，无需区分多源文件。
    """
    mock_excel, out_wb = _make_excel_with_open_map([["A"]])
    _inject_excel(monkeypatch, mock_excel)
    return toolbox, mock_excel, out_wb


# ────────────────────────── collect_sources ─────────────────────

def test_collect_sources_explicit_paths(toolbox, tmp_path):
    """显式路径列表去重排序返回。"""
    f1 = tmp_path / "a.xlsx"
    f2 = tmp_path / "b.xlsx"
    f1.touch()
    f2.touch()
    result = toolbox.collect_sources(paths=[f2, f1, f1])
    assert result == sorted([f1.resolve(), f2.resolve()])


def test_collect_sources_directory(toolbox, tmp_path):
    """目录扫描返回 .xlsx/.xls 文件。"""
    (tmp_path / "x.xlsx").touch()
    (tmp_path / "y.xls").touch()
    (tmp_path / "z.txt").touch()
    result = toolbox.collect_sources(directory=tmp_path)
    names = {p.name for p in result}
    assert "x.xlsx" in names
    assert "y.xls" in names
    assert "z.txt" not in names


# ────────────────────────── _auto_output_name ───────────────────

def test_auto_output_name(toolbox):
    """_auto_output_name 生成路径在 OUTPUT_DIR 下，含 suffix。"""
    src = Path("foo.xlsx")
    result = ExcelToolbox._auto_output_name(src)
    assert result.name == "foo-汇总.xlsx"


# ────────────────────────── _backup / _rollback ─────────────────

def test_backup_creates_bak_file(toolbox, tmp_path):
    """_backup 在 BACKUP_DIR 下生成 .bak 文件并返回路径。"""
    target = tmp_path / "file.xlsx"
    target.write_text("content")
    backup = toolbox._backup(target)
    assert backup.exists()
    assert backup.suffix == ".bak"
    assert "file.xlsx" in backup.name


def test_backup_raises_if_target_missing(toolbox, tmp_path):
    """_backup 在 target 不存在时抛 FileNotFoundError。"""
    with pytest.raises(FileNotFoundError):
        toolbox._backup(tmp_path / "nonexistent.xlsx")


def test_rollback_restores_file(toolbox, tmp_path):
    """_rollback 将 backup 内容复制回 target。"""
    target = tmp_path / "file.xlsx"
    target.write_text("original")
    backup = toolbox._backup(target)
    target.write_text("modified")
    toolbox._rollback(target, backup)
    assert target.read_text() == "original"


def test_rollback_silent_if_backup_missing(toolbox, tmp_path):
    """_rollback 在 backup 不存在时静默返回（不抛异常）。"""
    target = tmp_path / "file.xlsx"
    target.write_text("x")
    toolbox._rollback(target, tmp_path / "ghost.bak")


# ────────────────────────── _highlight_cell ─────────────────────

def test_highlight_cell_assigns_morandi_color(toolbox):
    """_highlight_cell 给新 source_tag 分配色板中的颜色。"""
    mock_sheet = MagicMock()
    mock_sheet.Cells.return_value.Interior.Color = 0xFFFFFF
    toolbox._highlight_cell(mock_sheet, 1, 1, "src_A")
    assert "src_A" in toolbox._color_map
    assert toolbox._color_map["src_A"] in MORANDI_PALETTE


def test_highlight_cell_collision_skips_to_next(toolbox):
    """_highlight_cell 撞色时顺延取下一色。"""
    conflicting_color = MORANDI_PALETTE[0]
    mock_sheet = MagicMock()
    cell_mock = MagicMock()
    cell_mock.Interior.Color = conflicting_color
    mock_sheet.Cells.return_value = cell_mock

    toolbox._palette_idx = 0
    toolbox._highlight_cell(mock_sheet, 1, 1, "src_B")
    assigned = toolbox._color_map["src_B"]
    assert assigned != conflicting_color or len(MORANDI_PALETTE) == 1


# ────────────────────────── _write_legend ───────────────────────

def test_write_legend_creates_sheet(toolbox):
    """_write_legend 在 workbook 新增名为「图例说明」的 Sheet。"""
    mock_wb = MagicMock()
    mock_legend_sheet = MagicMock()
    mock_wb.Sheets.Add.return_value = mock_legend_sheet

    color_map = {"来源A": 0xC5B8C8, "来源B": 0xC4B8A8}
    toolbox._write_legend(mock_wb, color_map)

    mock_wb.Sheets.Add.assert_called_once()
    assert mock_legend_sheet.Name == "图例说明"


# ────────────────────────── merge_append ────────────────────────

def test_merge_append_calls_saveas_and_quit(toolbox_with_mock_excel, tmp_path):
    """merge_append 调用 SaveAs(FileFormat=51) 且 finally 调用 Quit。"""
    toolbox, mock_excel, out_wb = toolbox_with_mock_excel
    src = tmp_path / "src.xlsx"
    src.touch()

    out = tmp_path / "output" / "result.xlsx"
    toolbox.merge_append([src], output_path=out)

    out_wb.SaveAs.assert_called_once()
    ca = out_wb.SaveAs.call_args
    assert ca.args[1:2] == (51,) or ca.kwargs.get("FileFormat") == 51
    mock_excel.Quit.assert_called()


def test_merge_append_multi_source_distinct_workbooks(toolbox, tmp_path, monkeypatch):
    """T2 修复：多源文件时，Workbooks.Open 对 baseline 和各 source 返回不同工作簿。"""
    src1 = tmp_path / "src1.xlsx"
    src2 = tmp_path / "src2.xlsx"
    baseline_file = tmp_path / "baseline.xlsx"
    src1.touch()
    src2.touch()
    baseline_file.touch()

    open_map = {
        "src1": [["S1R1C1", "S1R1C2"]],
        "src2": [["S2R1C1", "S2R1C2"]],
        "baseline": [["BR1C1", "BR1C2"]],
    }
    mock_excel, out_wb = _make_excel_with_open_map([[]], open_map=open_map)
    _inject_excel(monkeypatch, mock_excel)

    out = tmp_path / "output" / "merged.xlsx"
    toolbox.merge_append([src1, src2], output_path=out, baseline=baseline_file)

    # Open 被调用了 3 次：1 次 baseline + 2 次 source
    assert mock_excel.Workbooks.Open.call_count == 3
    opened_paths = [str(c.args[0]) for c in mock_excel.Workbooks.Open.call_args_list]
    assert any("baseline" in p for p in opened_paths)
    assert any("src1" in p for p in opened_paths)
    assert any("src2" in p for p in opened_paths)


def test_merge_append_backup_before_overwrite(toolbox, tmp_path, monkeypatch):
    """merge_append 改写已存在的 output 前先调用 _backup。"""
    src = tmp_path / "src.xlsx"
    src.touch()
    out = tmp_path / "output" / "existing.xlsx"
    out.write_text("old")

    mock_excel, out_wb = _make_excel_with_open_map([[]])
    _inject_excel(monkeypatch, mock_excel)

    backup_calls = []
    original_backup = toolbox._backup

    def spy_backup(target):
        backup_calls.append(target)
        return original_backup(target)

    toolbox._backup = spy_backup
    toolbox.merge_append([src], output_path=out)

    assert len(backup_calls) == 1
    assert backup_calls[0] == out


def test_merge_append_rollback_on_com_error(toolbox, tmp_path, monkeypatch):
    """merge_append COM 异常时调用 _rollback 并上抛异常。"""
    src = tmp_path / "src.xlsx"
    src.touch()
    out = tmp_path / "output" / "will_fail.xlsx"
    out.write_text("original content")

    mock_wc = MagicMock()
    mock_excel = MagicMock()
    mock_excel.Workbooks.Add.side_effect = RuntimeError("COM error")
    mock_wc.Dispatch.return_value = mock_excel
    monkeypatch.setattr(et_module, "_get_win32com", lambda: mock_wc)

    rollback_calls = []
    original_rollback = toolbox._rollback

    def spy_rollback(target, backup):
        rollback_calls.append((target, backup))
        return original_rollback(target, backup)

    toolbox._rollback = spy_rollback

    with pytest.raises(RuntimeError, match="COM error"):
        toolbox.merge_append([src], output_path=out)

    assert len(rollback_calls) == 1


def test_merge_append_quit_called_on_exception(toolbox, tmp_path, monkeypatch):
    """merge_append 即便异常也确保 Quit 在 finally 中被调用。"""
    src = tmp_path / "src.xlsx"
    src.touch()

    mock_excel = MagicMock()
    mock_excel.Workbooks.Add.side_effect = RuntimeError("fail")
    monkeypatch.setattr(et_module, "_get_win32com", lambda: MagicMock(Dispatch=lambda _: mock_excel))

    with pytest.raises(RuntimeError):
        toolbox.merge_append([src], output_path=tmp_path / "output" / "out.xlsx")

    mock_excel.Quit.assert_called()


# ────────────────────────── merge_overlay ───────────────────────

def test_merge_overlay_saveas_and_quit(toolbox, tmp_path, monkeypatch):
    """merge_overlay 调用 SaveAs(FileFormat=51) 且 finally Quit。"""
    src = tmp_path / "src.xlsx"
    target = tmp_path / "target.xlsx"
    src.touch()
    target.write_text("target content")

    open_map = {
        "target": [["T1"]],
        "src": [["S1"]],
    }
    mock_excel, out_wb = _make_excel_with_open_map([[]], open_map=open_map)
    _inject_excel(monkeypatch, mock_excel)

    out = tmp_path / "output" / "overlay.xlsx"
    toolbox.merge_overlay([src], target, output_path=out)

    out_wb.SaveAs.assert_called_once()
    ca = out_wb.SaveAs.call_args
    assert ca.args[1:2] == (51,) or ca.kwargs.get("FileFormat") == 51
    mock_excel.Quit.assert_called()


# ────────────────────────── diff_against_baseline ───────────────

def test_diff_saveas_and_quit(toolbox, tmp_path, monkeypatch):
    """diff_against_baseline 调用 SaveAs(FileFormat=51) 且 finally Quit。"""
    target = tmp_path / "current.xlsx"
    baseline = tmp_path / "baseline.xlsx"
    target.write_text("t")
    baseline.write_text("b")

    open_map = {
        "current": [["old"]],
        "baseline": [["new"]],
    }
    mock_excel, out_wb = _make_excel_with_open_map([[]], open_map=open_map)
    _inject_excel(monkeypatch, mock_excel)

    out = tmp_path / "output" / "diff.xlsx"
    toolbox.diff_against_baseline(target, baseline, output_path=out)

    out_wb.SaveAs.assert_called()
    mock_excel.Quit.assert_called()


# ────────────────────────── PermissionError ─────────────────────

def test_merge_append_raises_permission_error_when_locked(toolbox, tmp_path, monkeypatch):
    """占用文件时 merge_append 抛 PermissionError。"""
    src = tmp_path / "src.xlsx"
    src.touch()
    out = tmp_path / "output" / "locked.xlsx"
    out.touch()

    monkeypatch.setattr(toolbox, "_check_file_not_locked", lambda p: False)
    with pytest.raises(PermissionError):
        toolbox.merge_append([src], output_path=out)
