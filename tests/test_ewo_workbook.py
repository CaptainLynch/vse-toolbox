from __future__ import annotations

import pathlib
from typing import Any
from xml.sax.saxutils import escape
import zipfile

import pytest

from services.ewo_workbook import (
    REQUIRED_HEADERS,
    read_ewo_workbook,
)


def col_letter(col_idx: int) -> str:
    """Convert 0-based column index to Excel column name (0 -> A, 25 -> Z, 26 -> AA)."""
    chars: list[str] = []
    col_idx += 1
    while col_idx > 0:
        col_idx, rem = divmod(col_idx - 1, 26)
        chars.append(chr(65 + rem))
    return "".join(reversed(chars))


def create_minimal_xlsx(
    path: pathlib.Path,
    rows: list[list[Any]],
    sheet_name: str = "Innovator",
    dimension_ref: str | None = None,
    sheet_names: list[str] | None = None,
) -> pathlib.Path:
    """Create a minimal valid XLSX file using zipfile and standard OOXML XML."""
    if sheet_names is None:
        sheet_names = [sheet_name]

    sst_map: dict[str, int] = {}
    sst_list: list[str] = []

    def get_sst_idx(text: str) -> int:
        if text not in sst_map:
            sst_map[text] = len(sst_list)
            sst_list.append(text)
        return sst_map[text]

    # Pre-scan strings in rows to populate shared strings
    sheet1_rows_xml: list[str] = []
    for r_idx, row in enumerate(rows, start=1):
        cell_xmls: list[str] = []
        for c_idx, cell in enumerate(row):
            cref = f"{col_letter(c_idx)}{r_idx}"
            if cell is None:
                cell_xmls.append(f'<c r="{cref}"/>')
            elif isinstance(cell, bool):
                cell_xmls.append(f'<c r="{cref}" t="b"><v>{1 if cell else 0}</v></c>')
            elif isinstance(cell, (int, float)):
                cell_xmls.append(f'<c r="{cref}"><v>{cell}</v></c>')
            elif isinstance(cell, str):
                s_idx = get_sst_idx(cell)
                cell_xmls.append(f'<c r="{cref}" t="s"><v>{s_idx}</v></c>')
            else:
                s_idx = get_sst_idx(str(cell))
                cell_xmls.append(f'<c r="{cref}" t="s"><v>{s_idx}</v></c>')
        sheet1_rows_xml.append(f'<row r="{r_idx}">{"".join(cell_xmls)}</row>')

    # Determine dimension ref
    if dimension_ref is not None:
        dim_tag = f'<dimension ref="{dimension_ref}"/>'
    elif rows:
        max_c = max((len(r) for r in rows), default=1)
        dim_tag = f'<dimension ref="A1:{col_letter(max(max_c - 1, 0))}{len(rows)}"/>'
    else:
        dim_tag = '<dimension ref="A1"/>'

    sheet1_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">\n'
        f"  {dim_tag}\n"
        "  <sheetData>\n"
        f"    {''.join(sheet1_rows_xml)}\n"
        "  </sheetData>\n"
        "</worksheet>"
    )

    # sharedStrings.xml
    sst_entries: list[str] = []
    for s in sst_list:
        esc = escape(s)
        if s.startswith(" ") or s.endswith(" "):
            sst_entries.append(f'<si><t xml:space="preserve">{esc}</t></si>')
        else:
            sst_entries.append(f"<si><t>{esc}</t></si>")
    sst_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(sst_list)}" uniqueCount="{len(sst_list)}">\n'
        f"  {''.join(sst_entries)}\n"
        "</sst>"
    )

    # [Content_Types].xml
    sheet_overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, len(sheet_names) + 1)
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        '  <Default Extension="xml" ContentType="application/xml"/>\n'
        '  <Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>\n'
        f"  {sheet_overrides}\n"
        '  <Override PartName="/xl/sharedStrings.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>\n'
        "</Types>"
    )

    # _rels/.rels
    root_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>\n'
        "</Relationships>"
    )

    # xl/_rels/workbook.xml.rels
    wb_rels_entries = "".join(
        f'<Relationship Id="rId{i}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(sheet_names) + 1)
    )
    wb_rels_entries += (
        f'<Relationship Id="rId{len(sheet_names) + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" '
        'Target="sharedStrings.xml"/>'
    )
    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        f"  {wb_rels_entries}\n"
        "</Relationships>"
    )

    # xl/workbook.xml
    sheets_xml = "".join(
        f'<sheet name="{escape(sname)}" sheetId="{i}" r:id="rId{i}"/>'
        for i, sname in enumerate(sheet_names, start=1)
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">\n'
        f"  <sheets>{sheets_xml}</sheets>\n"
        "</workbook>"
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", root_rels_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/sharedStrings.xml", sst_xml)
        zf.writestr("xl/worksheets/sheet1.xml", sheet1_xml)
        for i in range(2, len(sheet_names) + 1):
            dummy_sheet = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">\n'
                '  <dimension ref="A1"/>\n'
                "  <sheetData/>\n"
                "</worksheet>"
            )
            zf.writestr(f"xl/worksheets/sheet{i}.xml", dummy_sheet)

    return path


def test_dimension_says_a1_while_actual_410_data_rows_and_111_columns(
    tmp_path: pathlib.Path,
) -> None:
    # 1 header row + 410 data rows = 411 rows total, with 111 columns
    headers = list(REQUIRED_HEADERS) + [f"ExtraCol_{i}" for i in range(6, 112)]
    assert len(headers) == 111

    rows: list[list[Any]] = [headers]
    for r_idx in range(1, 411):
        row = [
            f"EWO-{r_idx:04d}",
            f"Engineer_{r_idx}",
            "2026-10-01",
            "In Review",
            f"Signer_{r_idx}",
        ]
        row.extend([f"val_{r_idx}_{c_idx}" for c_idx in range(6, 112)])
        rows.append(row)

    wb_path = tmp_path / "dimension_a1_large.xlsx"
    create_minimal_xlsx(wb_path, rows, sheet_name="Innovator", dimension_ref="A1")

    res = read_ewo_workbook(wb_path)

    assert res["sheet_name"] == "Innovator"
    assert res["truncated"] is False
    assert len(res["headers"]) == 111
    assert res["headers"] == headers
    assert len(res["rows"]) == 410
    assert res["rows"][0][0] == "EWO-0001"
    assert res["rows"][409][0] == "EWO-0410"
    assert len(res["rows"][0]) == 111


def test_preserve_four_empty_business_number_rows_whose_other_fields_nonempty(
    tmp_path: pathlib.Path,
) -> None:
    headers = list(REQUIRED_HEADERS)
    rows: list[list[Any]] = [
        headers,
        # Normal row 1
        ["EWO-001", "Engineer A", "2026-09-01", "Active", "Approver 1"],
        # Empty business number row 1 (None)
        [None, "Engineer B", "2026-09-02", "Pending", "Approver 2"],
        # Entirely empty row (should be ignored)
        [None, None, "", "   ", None],
        # Empty business number row 2 (empty string)
        ["", "Engineer C", "2026-09-03", "Draft", "Approver 3"],
        # Entirely empty row (should be ignored)
        [],
        # Empty business number row 3 (whitespace)
        ["   ", "Engineer D", "2026-09-04", "Closed", "Approver 4"],
        # Empty business number row 4 (None)
        [None, "Engineer E", "2026-09-05", "Hold", "Approver 5"],
    ]

    wb_path = tmp_path / "empty_biz_no.xlsx"
    create_minimal_xlsx(wb_path, rows, sheet_name="Innovator")

    res = read_ewo_workbook(wb_path)

    assert res["headers"] == headers
    # 1 normal + 4 empty business number rows = 5 rows total
    assert len(res["rows"]) == 5
    # Check preserved empty business-number rows
    assert res["rows"][1][0] is None
    assert res["rows"][1][1] == "Engineer B"
    assert res["rows"][2][0] == ""
    assert res["rows"][2][1] == "Engineer C"
    assert res["rows"][3][0] == "   "
    assert res["rows"][3][1] == "Engineer D"
    assert res["rows"][4][0] is None
    assert res["rows"][4][1] == "Engineer E"


def test_wrong_sheet_name_rejected(tmp_path: pathlib.Path) -> None:
    headers = list(REQUIRED_HEADERS)
    rows = [headers, ["EWO-001", "Eng", "2026-09-01", "Open", "Role"]]
    wb_path = tmp_path / "wrong_sheet.xlsx"

    create_minimal_xlsx(wb_path, rows, sheet_name="Sheet1")
    with pytest.raises(ValueError, match="must be named 'Innovator'"):
        read_ewo_workbook(wb_path)


def test_missing_required_headers_rejected(tmp_path: pathlib.Path) -> None:
    # Missing "状态"
    headers = ["EWO编号", "责任工程师名称", "要求完成时间", "当前阶段未签署的角色&人员"]
    rows = [headers, ["EWO-001", "Eng", "2026-09-01", "Role"]]
    wb_path = tmp_path / "missing_header.xlsx"

    create_minimal_xlsx(wb_path, rows, sheet_name="Innovator")
    with pytest.raises(ValueError, match="missing required headers"):
        read_ewo_workbook(wb_path)


def test_duplicate_headers_rejected(tmp_path: pathlib.Path) -> None:
    headers = list(REQUIRED_HEADERS) + ["状态"]
    rows = [headers, ["EWO-001", "Eng", "2026-09-01", "Open", "Role", "Extra"]]
    wb_path = tmp_path / "duplicate_header.xlsx"

    create_minimal_xlsx(wb_path, rows, sheet_name="Innovator")
    with pytest.raises(ValueError, match="duplicate headers"):
        read_ewo_workbook(wb_path)


def test_empty_or_whitespace_headers_rejected(tmp_path: pathlib.Path) -> None:
    # Empty string header
    headers1 = list(REQUIRED_HEADERS) + [""]
    rows1 = [headers1, ["EWO-001", "Eng", "2026-09-01", "Open", "Role", "Val"]]
    wb_path1 = tmp_path / "empty_header.xlsx"
    create_minimal_xlsx(wb_path1, rows1, sheet_name="Innovator")
    with pytest.raises(ValueError, match="must be a non-empty string"):
        read_ewo_workbook(wb_path1)

    # Whitespace-only header
    headers2 = list(REQUIRED_HEADERS) + ["   "]
    rows2 = [headers2, ["EWO-001", "Eng", "2026-09-01", "Open", "Role", "Val"]]
    wb_path2 = tmp_path / "whitespace_header.xlsx"
    create_minimal_xlsx(wb_path2, rows2, sheet_name="Innovator")
    with pytest.raises(ValueError, match="must be a non-empty string"):
        read_ewo_workbook(wb_path2)


def test_normal_reorder_and_extra_fields(tmp_path: pathlib.Path) -> None:
    headers = [
        "优先级",
        "状态",
        "EWO编号",
        "备注",
        "当前阶段未签署的角色&人员",
        "责任工程师名称",
        "要求完成时间",
    ]
    rows = [
        headers,
        [
            "High",
            "Active",
            "EWO-1001",
            "Priority item",
            "Role Lead",
            "Engineer X",
            "2026-12-31",
        ],
    ]
    wb_path = tmp_path / "reordered.xlsx"
    create_minimal_xlsx(wb_path, rows, sheet_name="Innovator")

    res = read_ewo_workbook(wb_path)
    assert res["headers"] == headers
    assert len(res["rows"]) == 1
    assert res["rows"][0] == [
        "High",
        "Active",
        "EWO-1001",
        "Priority item",
        "Role Lead",
        "Engineer X",
        "2026-12-31",
    ]
    assert res["sheet_name"] == "Innovator"
    assert res["truncated"] is False


def test_zero_data_rows(tmp_path: pathlib.Path) -> None:
    # Valid headers, but zero data rows
    headers = list(REQUIRED_HEADERS)
    rows = [headers]
    wb_path = tmp_path / "zero_data.xlsx"
    create_minimal_xlsx(wb_path, rows, sheet_name="Innovator")

    res = read_ewo_workbook(wb_path)
    assert res["headers"] == headers
    assert res["rows"] == []
    assert res["sheet_name"] == "Innovator"
    assert res["truncated"] is False

    # Also test where data rows exist but are entirely empty
    rows_with_empty_data = [headers, [], [None, None, None, None, None]]
    wb_path_empty_rows = tmp_path / "only_empty_data_rows.xlsx"
    create_minimal_xlsx(wb_path_empty_rows, rows_with_empty_data, sheet_name="Innovator")

    res2 = read_ewo_workbook(wb_path_empty_rows)
    assert res2["rows"] == []


def test_damaged_zip_rejected(tmp_path: pathlib.Path) -> None:
    wb_path = tmp_path / "damaged.xlsx"
    wb_path.write_bytes(b"PK\x03\x04not_a_valid_zip_archive_data")

    with pytest.raises(ValueError) as exc_info:
        read_ewo_workbook(wb_path)
    assert "Failed to read Excel workbook" in str(exc_info.value)
    # Ensure source exception text is not leaked
    assert "BadZipFile" not in str(exc_info.value)


def test_5001_data_rows_rejected(tmp_path: pathlib.Path) -> None:
    headers = list(REQUIRED_HEADERS)
    # 1 header + 5001 data rows = 5002 total rows
    rows: list[list[Any]] = [headers]
    for r in range(1, 5002):
        rows.append([f"EWO-{r}", "Eng", "2026-09-01", "Open", "Role"])

    wb_path = tmp_path / "overflow_rows.xlsx"
    create_minimal_xlsx(wb_path, rows, sheet_name="Innovator")

    with pytest.raises(ValueError, match="exceeds maximum"):
        read_ewo_workbook(wb_path)


def test_201_columns_rejected(tmp_path: pathlib.Path) -> None:
    # 201 headers: 5 required + 196 extras
    headers = list(REQUIRED_HEADERS) + [f"Col_{i}" for i in range(6, 202)]
    assert len(headers) == 201

    rows: list[list[Any]] = [headers]
    wb_path = tmp_path / "overflow_cols.xlsx"
    create_minimal_xlsx(wb_path, rows, sheet_name="Innovator")

    with pytest.raises(ValueError, match="exceeds maximum"):
        read_ewo_workbook(wb_path)


def test_empty_workbook_rejected(tmp_path: pathlib.Path) -> None:
    wb_path = tmp_path / "empty.xlsx"
    create_minimal_xlsx(wb_path, [], sheet_name="Innovator")

    with pytest.raises(ValueError, match="Workbook is empty"):
        read_ewo_workbook(wb_path)


def test_wider_row_rejected(tmp_path: pathlib.Path) -> None:
    headers = list(REQUIRED_HEADERS)  # 5 columns
    rows = [
        headers,
        ["EWO-001", "Eng", "2026-09-01", "Open", "Role", "ExtraData1", "ExtraData2"],
    ]
    wb_path = tmp_path / "wider_row.xlsx"
    create_minimal_xlsx(wb_path, rows, sheet_name="Innovator")

    with pytest.raises(ValueError, match="exceeding header width"):
        read_ewo_workbook(wb_path)


def test_short_row_padded_to_header_width(tmp_path: pathlib.Path) -> None:
    headers = list(REQUIRED_HEADERS)  # 5 columns
    rows = [
        headers,
        ["EWO-001", "Eng", "2026-09-01"],  # only 3 columns
    ]
    wb_path = tmp_path / "short_row.xlsx"
    create_minimal_xlsx(wb_path, rows, sheet_name="Innovator")

    res = read_ewo_workbook(wb_path)
    assert len(res["rows"]) == 1
    assert res["rows"][0] == ["EWO-001", "Eng", "2026-09-01", None, None]
