# -*- coding: utf-8 -*-
from pathlib import Path
from types import SimpleNamespace

import pytest

import services.excel_toolbox as et_module
from services.excel_toolbox import ExcelToolbox, MORANDI_PALETTE


class FakeRange:
    def __init__(self, value=None, formula="", color=0xFFFFFF):
        self.value = value
        self.formula = formula
        self.api = SimpleNamespace(
            Interior=SimpleNamespace(Color=color),
            Font=SimpleNamespace(Bold=False),
        )


class FakeUsedRange:
    def __init__(self, rows: int, cols: int):
        self.Rows = SimpleNamespace(Count=rows)
        self.Columns = SimpleNamespace(Count=cols)


class FakeSheet:
    def __init__(self, data=None):
        self.name = ""
        self._ranges: dict[tuple[int, int], FakeRange] = {}
        data = data or []
        for r, row in enumerate(data, start=1):
            for c, value in enumerate(row, start=1):
                self._ranges[(r, c)] = FakeRange(value=value)
        self._rows = len(data) or 1
        self._cols = max((len(row) for row in data), default=1)
        self.api = SimpleNamespace(UsedRange=FakeUsedRange(self._rows, self._cols))

    def range(self, address):
        return self._ranges.setdefault(tuple(address), FakeRange())


class FakeSheets:
    def __init__(self, sheet: FakeSheet):
        self._items = [sheet]

    def __getitem__(self, index):
        return self._items[index]

    def add(self, name=None, after=None):
        sheet = FakeSheet()
        sheet.name = name or ""
        self._items.append(sheet)
        return sheet

    @property
    def active(self):
        return self._items[0]


class FakeBook:
    def __init__(self, data=None):
        self.sheets = FakeSheets(FakeSheet(data))
        self.api = SimpleNamespace()
        self.api.SaveAs = self._save_as
        self.save_as_calls = []
        self.closed = False

    def _save_as(self, *args, **kwargs):
        self.save_as_calls.append((args, kwargs))

    def close(self):
        self.closed = True


class FakeBooks:
    def __init__(self, app, open_map=None, fail_add=False):
        self.app = app
        self.open_map = open_map or {}
        self.fail_add = fail_add
        self.added: list[FakeBook] = []
        self.opened: list[tuple[str, dict]] = []

    def add(self):
        if self.fail_add:
            raise RuntimeError("Excel error")
        book = FakeBook()
        self.added.append(book)
        self.app.books_created.append(book)
        return book

    def open(self, path, **kwargs):
        self.opened.append((path, kwargs))
        data = []
        for key, mapped_data in self.open_map.items():
            if key in str(path):
                data = mapped_data
                break
        book = FakeBook(data)
        self.app.books_created.append(book)
        return book


class FakeApp:
    instances = []

    def __init__(self, visible=False, add_book=False, open_map=None, fail_add=False):
        self.visible = visible
        self.add_book = add_book
        self.api = SimpleNamespace(DisplayAlerts=True, ScreenUpdating=True, EnableEvents=True)
        self.books_created: list[FakeBook] = []
        self.books = FakeBooks(self, open_map=open_map, fail_add=fail_add)
        self.quit_called = False
        FakeApp.instances.append(self)

    def quit(self):
        self.quit_called = True


def _inject_xlwings(monkeypatch, open_map=None, fail_add=False):
    FakeApp.instances = []

    class FakeXlwings:
        @staticmethod
        def App(visible=False, add_book=False):
            return FakeApp(
                visible=visible,
                add_book=add_book,
                open_map=open_map,
                fail_add=fail_add,
            )

    monkeypatch.setattr(et_module, "_get_xlwings", lambda: FakeXlwings)
    return FakeApp


@pytest.fixture
def toolbox(tmp_path, monkeypatch) -> ExcelToolbox:
    monkeypatch.setattr(et_module, "BACKUP_DIR", tmp_path / ".backup")
    monkeypatch.setattr(et_module, "OUTPUT_DIR", tmp_path / "output")
    (tmp_path / ".backup").mkdir()
    (tmp_path / "output").mkdir()
    return ExcelToolbox()


def test_collect_sources_explicit_paths(toolbox, tmp_path):
    f1 = tmp_path / "a.xlsx"
    f2 = tmp_path / "b.xlsx"
    f1.touch()
    f2.touch()
    result = toolbox.collect_sources(paths=[f2, f1, f1])
    assert result == sorted([f1.resolve(), f2.resolve()])


def test_collect_sources_directory(toolbox, tmp_path):
    (tmp_path / "x.xlsx").touch()
    (tmp_path / "y.xls").touch()
    (tmp_path / "z.txt").touch()
    names = {p.name for p in toolbox.collect_sources(directory=tmp_path)}
    assert {"x.xlsx", "y.xls"} <= names
    assert "z.txt" not in names


def test_auto_output_name(toolbox):
    result = ExcelToolbox._auto_output_name(Path("foo.xlsx"))
    assert result.name == "foo-汇总.xlsx"


def test_backup_creates_bak_file(toolbox, tmp_path):
    target = tmp_path / "file.xlsx"
    target.write_text("content")
    backup = toolbox._backup(target)
    assert backup.exists()
    assert backup.suffix == ".bak"
    assert "file.xlsx" in backup.name


def test_backup_raises_if_target_missing(toolbox, tmp_path):
    with pytest.raises(FileNotFoundError):
        toolbox._backup(tmp_path / "nonexistent.xlsx")


def test_rollback_restores_file(toolbox, tmp_path):
    target = tmp_path / "file.xlsx"
    target.write_text("original")
    backup = toolbox._backup(target)
    target.write_text("modified")
    toolbox._rollback(target, backup)
    assert target.read_text() == "original"


def test_rollback_silent_if_backup_missing(toolbox, tmp_path):
    target = tmp_path / "file.xlsx"
    target.write_text("x")
    toolbox._rollback(target, tmp_path / "ghost.bak")


def test_highlight_cell_assigns_morandi_color(toolbox):
    sheet = FakeSheet()
    toolbox._highlight_cell(sheet, 1, 1, "src_A")
    assert "src_A" in toolbox._color_map
    assert toolbox._color_map["src_A"] in MORANDI_PALETTE
    assert sheet.range((1, 1)).api.Interior.Color == toolbox._color_map["src_A"]


def test_highlight_cell_collision_skips_to_next(toolbox):
    sheet = FakeSheet()
    sheet.range((1, 1)).api.Interior.Color = MORANDI_PALETTE[0]
    toolbox._palette_idx = 0
    toolbox._highlight_cell(sheet, 1, 1, "src_B")
    assert toolbox._color_map["src_B"] != MORANDI_PALETTE[0]


def test_write_legend_creates_sheet(toolbox):
    book = FakeBook()
    toolbox._write_legend(book, {"source_A": 0xC5B8C8})
    assert book.sheets[-1].name == "图例说明"
    assert book.sheets[-1].range((2, 1)).value == "source_A"


def test_merge_append_uses_xlwings_app_saveas_and_quit(toolbox, tmp_path, monkeypatch):
    src = tmp_path / "src.xlsx"
    src.touch()
    fake_app_cls = _inject_xlwings(monkeypatch, open_map={"src": [["A"]]})

    out = tmp_path / "output" / "result.xlsx"
    toolbox.merge_append([src], output_path=out)

    app = fake_app_cls.instances[0]
    out_book = app.books.added[0]
    assert app.visible is False
    assert app.add_book is False
    assert app.api.DisplayAlerts is False
    assert app.api.ScreenUpdating is False
    assert app.api.EnableEvents is False
    assert out_book.save_as_calls[0][1]["FileFormat"] == 51
    assert app.quit_called is True
    assert all(book.closed for book in app.books_created)


def test_merge_append_multi_source_distinct_workbooks(toolbox, tmp_path, monkeypatch):
    src1 = tmp_path / "src1.xlsx"
    src2 = tmp_path / "src2.xlsx"
    baseline = tmp_path / "baseline.xlsx"
    for path in (src1, src2, baseline):
        path.touch()
    fake_app_cls = _inject_xlwings(
        monkeypatch,
        open_map={
            "src1": [["S1R1C1", "S1R1C2"]],
            "src2": [["S2R1C1", "S2R1C2"]],
            "baseline": [["BR1C1", "BR1C2"]],
        },
    )

    toolbox.merge_append([src1, src2], output_path=tmp_path / "output" / "merged.xlsx", baseline=baseline)

    opened = fake_app_cls.instances[0].books.opened
    assert len(opened) == 3
    assert any("baseline" in path for path, _ in opened)
    assert any("src1" in path for path, _ in opened)
    assert any("src2" in path for path, _ in opened)
    assert all(kwargs["update_links"] is False for _, kwargs in opened)
    assert all(kwargs["read_only"] is True for _, kwargs in opened)


def test_merge_append_backup_before_overwrite(toolbox, tmp_path, monkeypatch):
    src = tmp_path / "src.xlsx"
    src.touch()
    out = tmp_path / "output" / "existing.xlsx"
    out.write_text("old")
    _inject_xlwings(monkeypatch, open_map={"src": [["A"]]})
    calls = []
    original_backup = toolbox._backup

    def spy_backup(target):
        calls.append(target)
        return original_backup(target)

    toolbox._backup = spy_backup
    toolbox.merge_append([src], output_path=out)
    assert calls == [out]


def test_merge_append_rollback_and_quit_on_xlwings_error(toolbox, tmp_path, monkeypatch):
    src = tmp_path / "src.xlsx"
    src.touch()
    out = tmp_path / "output" / "will_fail.xlsx"
    out.write_text("original content")
    fake_app_cls = _inject_xlwings(monkeypatch, fail_add=True)
    calls = []
    original_rollback = toolbox._rollback

    def spy_rollback(target, backup):
        calls.append((target, backup))
        return original_rollback(target, backup)

    toolbox._rollback = spy_rollback
    with pytest.raises(RuntimeError, match="Excel error"):
        toolbox.merge_append([src], output_path=out)
    assert len(calls) == 1
    assert fake_app_cls.instances[0].quit_called is True


def test_merge_overlay_saveas_and_quit(toolbox, tmp_path, monkeypatch):
    src = tmp_path / "src.xlsx"
    target = tmp_path / "target.xlsx"
    src.touch()
    target.write_text("target content")
    fake_app_cls = _inject_xlwings(monkeypatch, open_map={"target": [["T1"]], "src": [["S1"]]})

    out = tmp_path / "output" / "overlay.xlsx"
    toolbox.merge_overlay([src], target, output_path=out)

    app = fake_app_cls.instances[0]
    out_book = app.books_created[0]
    assert out_book.save_as_calls[0][1]["FileFormat"] == 51
    assert app.quit_called is True


def test_diff_saveas_and_quit(toolbox, tmp_path, monkeypatch):
    target = tmp_path / "current.xlsx"
    baseline = tmp_path / "baseline.xlsx"
    target.write_text("t")
    baseline.write_text("b")
    fake_app_cls = _inject_xlwings(monkeypatch, open_map={"current": [["old"]], "baseline": [["new"]]})

    out = tmp_path / "output" / "diff.xlsx"
    toolbox.diff_against_baseline(target, baseline, output_path=out)

    app = fake_app_cls.instances[0]
    assert app.books_created[0].save_as_calls[0][1]["FileFormat"] == 51
    assert app.quit_called is True


def test_merge_append_raises_permission_error_when_locked(toolbox, tmp_path, monkeypatch):
    src = tmp_path / "src.xlsx"
    src.touch()
    out = tmp_path / "output" / "locked.xlsx"
    out.touch()
    monkeypatch.setattr(toolbox, "_check_file_not_locked", lambda p: False)
    with pytest.raises(PermissionError):
        toolbox.merge_append([src], output_path=out)
