from __future__ import annotations

import builtins
import zipfile
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

import pytest

import services.aras_report_export as export_service
from services.aras_crawler import EWOReportFilters, EWOReportPage
from services.aras_report_export import ArasReportExportError


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


class FakeComError(Exception):
    def __init__(self, hresult: int) -> None:
        super().__init__("private COM detail")
        self.hresult = hresult


class DispatchRuntime:
    def __init__(self, outcome) -> None:  # type: ignore[no-untyped-def]
        self.outcome = outcome
        self.calls = 0

    def DispatchEx(self, _name: str):  # type: ignore[no-untyped-def]
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    Dispatch = DispatchEx


class FailingWorkbooks:
    def Add(self):  # type: ignore[no-untyped-def]
        raise OSError("private workbook failure")


class ExcelWithFailingWorkbooks:
    Visible = True
    DisplayAlerts = True
    Workbooks = FailingWorkbooks()

    def Quit(self) -> None:
        pass


class SaveFailWorkbook:
    def __init__(self) -> None:
        self.ActiveSheet = type(
            "Sheet",
            (),
            {
                "Name": "",
                "Cells": staticmethod(lambda row, column: (row, column)),
                "Range": lambda _self, *_args: type(
                    "Range",
                    (),
                    {
                        "Value": None,
                        "NumberFormat": None,
                        "Font": type("Font", (), {"Bold": False})(),
                    },
                )(),
                "Columns": type("Columns", (), {"AutoFit": lambda _self: None})(),
            },
        )()

    def SaveAs(self, *_args, **_kwargs) -> None:  # noqa: N802
        raise OSError("private SaveAs/DLP detail")

    def Close(self, **_kwargs) -> None:  # noqa: N802
        pass


class ExcelWithFailingSave:
    Visible = True
    DisplayAlerts = True

    def __init__(self) -> None:
        workbook = SaveFailWorkbook()
        self.Workbooks = type("Workbooks", (), {"Add": lambda _self: workbook})()

    def Quit(self) -> None:
        pass


class OnePageEwoClient:
    timeout = 30.0
    _request_deadline = None

    @staticmethod
    def query_ewo_report(
        _filters,
        *,
        page: int,
        page_size: int,
        max_records: int,
    ) -> EWOReportPage:
        assert (page, page_size, max_records) == (1, 50, 12000)
        return EWOReportPage(
            rows=[{"_no": "SYNTHETIC", "state": "Open"}],
            page=1,
            item_ids=["SYNTHETIC-ID"],
            raw_xml="<synthetic/>",
        )


def _read_sheet(path: Path) -> tuple[str, list[list[str]], ElementTree.Element]:
    with zipfile.ZipFile(path) as archive:
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        sheet = workbook.find(f"{{{MAIN_NS}}}sheets/{{{MAIN_NS}}}sheet")
        assert sheet is not None
        name = sheet.attrib["name"]
        root = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    values: list[list[str]] = []
    for row in root.findall(f".//{{{MAIN_NS}}}row"):
        values.append(
            [
                "".join(cell.itertext())
                for cell in row.findall(f"{{{MAIN_NS}}}c")
            ]
        )
    return name, values, root


def test_com_success_remains_primary_and_never_calls_fallback(monkeypatch, tmp_path) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        export_service,
        "_write_xlsx_with_excel_com",
        lambda *_args: calls.append("com"),
    )
    monkeypatch.setattr(
        export_service,
        "_write_xlsx_with_stdlib_ooxml",
        lambda *_args: calls.append("fallback"),
    )

    export_service._write_xlsx(tmp_path / "primary.xlsx", "ewo", ("_no",), [])

    assert calls == ["com"]


def test_import_capability_failure_uses_stdlib_fallback(monkeypatch, tmp_path) -> None:
    calls: list[str] = []

    def unavailable(*_args) -> None:  # type: ignore[no-untyped-def]
        raise export_service._ExcelComCapabilityUnavailable()

    monkeypatch.setattr(export_service, "_write_xlsx_with_excel_com", unavailable)
    monkeypatch.setattr(
        export_service,
        "_write_xlsx_with_stdlib_ooxml",
        lambda *_args: calls.append("fallback"),
    )

    export_service._write_xlsx(tmp_path / "fallback.xlsx", "paa", ("_no",), [])

    assert calls == ["fallback"]


def test_real_win32com_import_error_is_classified_for_fallback(monkeypatch) -> None:
    real_import = builtins.__import__

    def import_without_win32com(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "win32com.client":
            raise ModuleNotFoundError("private import detail")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_win32com)

    with pytest.raises(export_service._ExcelComCapabilityUnavailable):
        export_service._excel_runtime()


@pytest.mark.parametrize(
    "hresult",
    [0x800401F3, -2147221005, 0x80040154, -2147221164],
)
def test_approved_predispatch_hresult_uses_fallback(
    monkeypatch,
    tmp_path,
    hresult: int,
) -> None:
    runtime = DispatchRuntime(FakeComError(hresult))
    fallback_calls: list[Path] = []
    monkeypatch.setattr(export_service, "_excel_runtime", lambda: (runtime, None))
    monkeypatch.setattr(
        export_service,
        "_write_xlsx_with_stdlib_ooxml",
        lambda path, *_args: fallback_calls.append(path),
    )

    path = tmp_path / "approved.xlsx"
    export_service._write_xlsx(path, "ewo", ("_no",), [])

    assert runtime.calls == 1
    assert fallback_calls == [path]


def test_unknown_dispatch_error_fails_closed_without_fallback(monkeypatch, tmp_path) -> None:
    runtime = DispatchRuntime(FakeComError(0x80004005))
    fallback_calls: list[object] = []
    monkeypatch.setattr(export_service, "_excel_runtime", lambda: (runtime, None))
    monkeypatch.setattr(
        export_service,
        "_write_xlsx_with_stdlib_ooxml",
        lambda *_args: fallback_calls.append(object()),
    )

    with pytest.raises(ArasReportExportError) as excinfo:
        export_service._write_xlsx(tmp_path / "closed.xlsx", "ewo", ("_no",), [])

    assert excinfo.value.code == "FILE_WRITE_FAILED"
    assert "private COM detail" not in str(excinfo.value)
    assert fallback_calls == []


def test_excel_object_created_then_workbook_failure_never_falls_back(monkeypatch, tmp_path) -> None:
    runtime = DispatchRuntime(ExcelWithFailingWorkbooks())
    fallback_calls: list[object] = []
    monkeypatch.setattr(export_service, "_excel_runtime", lambda: (runtime, None))
    monkeypatch.setattr(
        export_service,
        "_write_xlsx_with_stdlib_ooxml",
        lambda *_args: fallback_calls.append(object()),
    )

    with pytest.raises(ArasReportExportError) as excinfo:
        export_service._write_xlsx(tmp_path / "closed.xlsx", "paa", ("_no",), [])

    assert excinfo.value.code == "FILE_WRITE_FAILED"
    assert fallback_calls == []


def test_excel_object_created_then_save_failure_never_falls_back(monkeypatch, tmp_path) -> None:
    runtime = DispatchRuntime(ExcelWithFailingSave())
    fallback_calls: list[object] = []
    monkeypatch.setattr(export_service, "_excel_runtime", lambda: (runtime, None))
    monkeypatch.setattr(
        export_service,
        "_write_xlsx_with_stdlib_ooxml",
        lambda *_args: fallback_calls.append(object()),
    )

    with pytest.raises(ArasReportExportError) as excinfo:
        export_service._write_xlsx(
            tmp_path / "closed.xlsx",
            "ewo",
            ("_no",),
            [{"_no": "safe synthetic row"}],
        )

    assert excinfo.value.code == "FILE_WRITE_FAILED"
    assert "private SaveAs/DLP detail" not in str(excinfo.value)
    assert fallback_calls == []


def test_fallback_failure_is_stable_and_safe(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        export_service,
        "_write_xlsx_with_excel_com",
        lambda *_args: (_ for _ in ()).throw(
            export_service._ExcelComCapabilityUnavailable()
        ),
    )
    monkeypatch.setattr(
        export_service,
        "_write_xlsx_with_stdlib_ooxml",
        lambda *_args: (_ for _ in ()).throw(OSError("private disk secret")),
    )

    with pytest.raises(ArasReportExportError) as excinfo:
        export_service._write_xlsx(tmp_path / "failed.xlsx", "ewo", ("_no",), [])

    assert excinfo.value.code == "FILE_WRITE_FAILED"
    assert "private disk secret" not in str(excinfo.value)


def test_stdlib_ooxml_is_valid_round_trippable_inline_text(monkeypatch, tmp_path) -> None:
    path = tmp_path / "roundtrip.xlsx"
    columns = ("_no", "unicode", "date", "number", "xml", "formula", "spaces", "control")
    rows = [
        {
            "_no": "EWO-1",
            "unicode": "中文🙂",
            "date": date(2026, 7, 26),
            "number": 42,
            "xml": "& <tag> >",
            "formula": "=HYPERLINK(\"bad\")",
            "spaces": "  kept  ",
            "control": "before\x00\x01after",
        }
    ]

    export_service._write_xlsx_with_stdlib_ooxml(path, "ewo", columns, rows)  # type: ignore[arg-type]

    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == export_service._OOXML_REQUIRED_MEMBERS
        assert all(
            not name.startswith(("/", "\\")) and ".." not in Path(name).parts
            for name in archive.namelist()
        )
        assert all(
            ElementTree.fromstring(archive.read(name)) is not None
            for name in archive.namelist()
        )
    name, values, root = _read_sheet(path)
    assert name == "EWO"
    assert values == [
        list(columns),
        [
            "EWO-1",
            "中文🙂",
            "2026-07-26",
            "42",
            "& <tag> >",
            "'=HYPERLINK(\"bad\")",
            "  kept  ",
            "beforeafter",
        ],
    ]
    assert root.findall(f".//{{{MAIN_NS}}}f") == []
    assert all(
        cell.attrib.get("t") == "inlineStr"
        for cell in root.findall(f".//{{{MAIN_NS}}}c")
    )


def test_stdlib_ooxml_empty_result_has_stable_header_only(tmp_path) -> None:
    path = tmp_path / "empty.xlsx"

    export_service._write_xlsx_with_stdlib_ooxml(
        path,
        "paa",
        ("_no", "state", "_vehicles"),
        [],
    )

    name, values, _root = _read_sheet(path)
    assert name == "PAA"
    assert values == [["_no", "state", "_vehicles"]]


def test_full_export_fallback_keeps_atomic_publish_and_lock_cleanup(
    monkeypatch,
    tmp_path,
) -> None:
    runtime = DispatchRuntime(FakeComError(0x800401F3))
    monkeypatch.setattr(export_service, "_excel_runtime", lambda: (runtime, None))
    monkeypatch.setattr(export_service, "OUTPUT_DIR", tmp_path)

    result = export_service.export_ewo_report(  # type: ignore[arg-type]
        OnePageEwoClient(),
        EWOReportFilters(),
    )

    assert result.saved_path.exists()
    assert result.saved_path.parent == tmp_path.resolve()
    assert result.status == "completed"
    assert result.count == 1
    assert result.stop_reason == "short_page"
    assert not list(tmp_path.glob("*.lock"))
    assert not list(tmp_path.glob(".*.tmp.xlsx"))
    with zipfile.ZipFile(result.saved_path) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == export_service._OOXML_REQUIRED_MEMBERS


def test_stdlib_ooxml_truncates_cells_and_neutralizes_every_formula_prefix(tmp_path) -> None:
    path = tmp_path / "formula.xlsx"
    long_value = "界" * 40000
    columns = ("equals", "plus", "minus", "at", "long")
    row = {
        "equals": "=" + ("1" * 40000),
        "plus": "+" + ("2" * 40000),
        "minus": "-" + ("3" * 40000),
        "at": "@" + ("4" * 40000),
        "long": long_value,
    }

    export_service._write_xlsx_with_stdlib_ooxml(path, "ewo", columns, [row])

    _name, values, root = _read_sheet(path)
    for value, prefix in zip(values[1][:4], ("=", "+", "-", "@")):
        assert value.startswith("'" + prefix)
        assert len(value) == 32767
    assert len(values[1][4]) == 32767
    assert root.findall(f".//{{{MAIN_NS}}}f") == []


def test_column_name_boundaries() -> None:
    assert export_service._xlsx_column_name(1) == "A"
    assert export_service._xlsx_column_name(26) == "Z"
    assert export_service._xlsx_column_name(27) == "AA"
    assert export_service._xlsx_column_name(16384) == "XFD"
    with pytest.raises(ValueError):
        export_service._xlsx_column_name(16385)


def test_stdlib_writer_handles_production_maximum_rows(tmp_path) -> None:
    path = tmp_path / "large.xlsx"
    columns = tuple(f"field_{index}" for index in range(24))
    shared_row = {column: f"value-{index}" for index, column in enumerate(columns)}
    rows = [shared_row] * 12000

    export_service._write_xlsx_with_stdlib_ooxml(path, "paa", columns, rows)

    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    assert len(sheet.findall(f".//{{{MAIN_NS}}}row")) == 12001
    assert len(sheet.findall(f".//{{{MAIN_NS}}}c")) == (12001 * len(columns))
