# -*- coding: utf-8 -*-
"""Dependency-free XLSX preview reader tests."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

import services.xlsx_preview as xlsx_preview
from services.xlsx_preview import XLSXPreviewError, read_xlsx_preview


def _write_minimal_xlsx(path: Path, *, large_sheet: bool = False) -> None:
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    shared_strings = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="2" uniqueCount="2">'
        '<si><t>Header</t></si><si><t>Value</t></si></sst>'
    )
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr"><is><t>Inline</t></is></c></row>'
        '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2"><v>42</v></c></row>'
        '</sheetData></worksheet>'
    )
    if large_sheet:
        sheet = sheet.replace("<sheetData>", "<!--" + ("x" * (33 * 1024 * 1024)) + "--><sheetData>")
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/sharedStrings.xml", shared_strings)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


def test_read_xlsx_preview_reads_shared_inline_and_numeric_cells(tmp_path: Path) -> None:
    workbook = tmp_path / "preview.xlsx"
    _write_minimal_xlsx(workbook)

    result = read_xlsx_preview(workbook, max_rows=2, max_columns=2)

    assert result.sheet_name == "Sheet1"
    assert result.sheet_names == ("Sheet1",)
    assert result.rows == [["Header", "Inline"], ["Value", "42"]]
    assert result.truncated is False


def test_read_xlsx_preview_marks_row_limit_truncation(tmp_path: Path) -> None:
    workbook = tmp_path / "preview.xlsx"
    _write_minimal_xlsx(workbook)

    result = read_xlsx_preview(workbook, max_rows=1)

    assert result.rows == [["Header", "Inline"]]
    assert result.truncated is True


def test_read_xlsx_preview_rejects_non_xlsx(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.xlsx"
    invalid.write_bytes(b"not a zip")

    with pytest.raises(XLSXPreviewError):
        read_xlsx_preview(invalid)


def test_read_xlsx_preview_rejects_oversized_xml_member(tmp_path: Path, monkeypatch) -> None:
    workbook = tmp_path / "preview.xlsx"
    _write_minimal_xlsx(workbook)
    monkeypatch.setattr(xlsx_preview, "_MAX_MEMBER_BYTES", 1)

    with pytest.raises(XLSXPreviewError, match="member is too large"):
        read_xlsx_preview(workbook)


def test_read_xlsx_preview_accepts_large_official_sheet_member(tmp_path: Path) -> None:
    workbook = tmp_path / "large-official-preview.xlsx"
    _write_minimal_xlsx(workbook, large_sheet=True)

    result = read_xlsx_preview(workbook, max_rows=2, max_columns=2)

    assert result.rows == [["Header", "Inline"], ["Value", "42"]]
