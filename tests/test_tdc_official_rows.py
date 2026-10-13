# -*- coding: utf-8 -*-
"""官方 TDC 工作簿读取（`services/tdc_official_rows.py`）回归。

单一来源契约：官方导出工作簿是全部官方列的唯一数据源，归档连接器与
「导出合并结果」共用同一套读取语义；表头不符 / 行数超限必须 fail-closed，
绝不产出"少几行但看起来正常"的行集。
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZipFile

import pytest

from core.report_contracts import report_contracts
from services.tdc_official_rows import (
    OfficialWorkbookContractError,
    OfficialWorkbookTruncated,
    OfficialWorkbookUnreadable,
    official_contract_headers,
    project_official_rows,
    read_official_tdc_rows,
)


def _cell_ref(column: int, row: int) -> str:
    result = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        result = chr(65 + remainder) + result
    return f"{result}{row}"


def _write_xlsx(path: Path, rows: list[list[object]]) -> None:
    def row_xml(values: list[object], row_number: int) -> str:
        cells = []
        for index, value in enumerate(values, 1):
            if value in (None, ""):
                continue
            cells.append(
                f'<c r="{_cell_ref(index, row_number)}" t="inlineStr">'
                f"<is><t>{escape(str(value))}</t></is></c>"
            )
        return f'<row r="{row_number}">{"".join(cells)}</row>'

    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        + "".join(row_xml(values, index) for index, values in enumerate(rows, 1))
        + "</sheetData></worksheet>"
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


def _official_workbook(tmp_path: Path, *, extra_rows: int = 0) -> Path:
    headers = official_contract_headers("data_model")
    rows: list[list[object]] = [list(headers)]
    rows.append(["50738964", "流程A", "3D-00001012"] + [""] * (len(headers) - 3))
    for index in range(extra_rows):
        rows.append(["5073896" + str(index % 10), "流程B", f"3D-000010{index}"] + [""] * (len(headers) - 3))
    path = tmp_path / "official.xlsx"
    _write_xlsx(path, rows)
    return path


def test_reads_rows_keyed_by_contract_labels(tmp_path: Path) -> None:
    rows = read_official_tdc_rows(_official_workbook(tmp_path), "data_model", max_rows=50)

    assert len(rows) == 1
    assert rows[0]["实例号"] == "50738964"
    assert rows[0]["流水单号"] == "3D-00001012"
    assert list(rows[0]) == official_contract_headers("data_model")   # 47 列全在
    assert len(rows[0]) == 47


def test_blank_rows_are_skipped(tmp_path: Path) -> None:
    headers = official_contract_headers("data_model")
    path = tmp_path / "blank.xlsx"
    _write_xlsx(path, [list(headers), [""] * len(headers), ["50667733"] + [""] * (len(headers) - 1)])

    rows = read_official_tdc_rows(path, "data_model", max_rows=50)

    assert len(rows) == 1
    assert rows[0]["实例号"] == "50667733"


def test_header_only_workbook_yields_no_rows(tmp_path: Path) -> None:
    path = tmp_path / "empty.xlsx"
    _write_xlsx(path, [official_contract_headers("data_model")])

    assert read_official_tdc_rows(path, "data_model", max_rows=50) == ()


def test_truncated_workbook_fails_closed(tmp_path: Path) -> None:
    """读到上限即失败：绝不返回部分行（调用方据此拒绝导出/投影）。"""
    path = _official_workbook(tmp_path, extra_rows=5)

    with pytest.raises(OfficialWorkbookTruncated):
        read_official_tdc_rows(path, "data_model", max_rows=3)


def test_contract_mismatch_fails_closed(tmp_path: Path) -> None:
    headers = official_contract_headers("data_model")
    path = tmp_path / "wrong-header.xlsx"
    _write_xlsx(path, [["错误表头"] + list(headers[1:]), ["50738964"] + [""] * (len(headers) - 1)])

    with pytest.raises(OfficialWorkbookContractError):
        read_official_tdc_rows(path, "data_model", max_rows=50)


def test_extra_trailing_header_column_fails_closed(tmp_path: Path) -> None:
    headers = official_contract_headers("data_model")
    path = tmp_path / "extra-column.xlsx"
    _write_xlsx(path, [list(headers) + ["多余列"], ["50738964"] + [""] * len(headers)])

    with pytest.raises(OfficialWorkbookContractError):
        read_official_tdc_rows(path, "data_model", max_rows=50)


def test_unreadable_workbook_is_reported_not_guessed(tmp_path: Path) -> None:
    path = tmp_path / "broken.xlsx"
    path.write_bytes(b"not-an-xlsx")

    with pytest.raises(OfficialWorkbookUnreadable):
        read_official_tdc_rows(path, "data_model", max_rows=50)


def test_unsupported_report_type_is_a_contract_error() -> None:
    with pytest.raises(OfficialWorkbookContractError):
        official_contract_headers("ewo")


def test_project_official_rows_keeps_column_order_and_missing_as_none() -> None:
    rows = [{"实例号": "1", "流水单号": "3D-1"}, {"流水单号": "3D-2"}]

    assert project_official_rows(rows, ["流水单号", "实例号", "状态"]) == [
        ["3D-1", "1", None],
        ["3D-2", None, None],
    ]


def test_contract_headers_match_report_contract() -> None:
    assert official_contract_headers("data_model") == [
        str(value or "").strip()
        for value in report_contracts()["tdc_data_model"]["headerRows"][0]
    ]
    assert len(official_contract_headers("sor")) == 15
