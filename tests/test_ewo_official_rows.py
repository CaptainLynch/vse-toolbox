"""官方 EWO 工作簿投影与对账的门禁契约（纯离线、合成夹具）。"""
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from services.ewo_official_rows import (
    E_EXTRA_COLUMN_DATA,
    E_HEADER_MISMATCH,
    E_RECONCILE_MISMATCH,
    E_WORKBOOK_INVALID,
    EwoExportGateError,
    contract_labels,
    label_rows,
    project_official_ewo_rows,
    read_official_ewo_rows,
    reconcile_official_rows,
)


def _column_letters(index: int) -> str:
    letters = ""
    value = index + 1
    while value:
        value, remainder = divmod(value - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def write_workbook(path: Path, headers, rows, *, sheet_name="Innovator") -> Path:
    """构造最小可读 xlsx（全部单元格为共享字符串，无第三方依赖）。"""
    strings: list[str] = []
    lookup: dict[str, int] = {}

    def sid(text: str) -> int:
        if text not in lookup:
            lookup[text] = len(strings)
            strings.append(text)
        return lookup[text]

    sheet_rows = []
    all_rows = [list(headers)] + [list(row) for row in rows]
    for row_index, values in enumerate(all_rows, start=1):
        cells = []
        for column, value in enumerate(values):
            if value is None or str(value) == "":
                continue
            reference = f"{_column_letters(column)}{row_index}"
            cells.append(f'<c r="{reference}" t="s"><v>{sid(str(value))}</v></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    shared = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(strings)}" uniqueCount="{len(strings)}">'
        + "".join(f"<si><t>{escape(text)}</t></si>" for text in strings)
        + "</sst>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/sharedStrings.xml", shared)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return path


def _marked_row(business_no: str) -> list[str]:
    """每个单元格写成「标签|业务编号」，用来证明取值按列语义而非位置。

    业务编号列写纯值，才能与对账函数使用的 ``_no`` 键匹配。
    """
    row = [f"{label}|{business_no}" for label in contract_labels()]
    row[0] = business_no
    return row


def test_columns_after_57_are_populated_from_official_workbook(tmp_path):
    labels = contract_labels()
    workbook = write_workbook(tmp_path / "official.xlsx", labels, [_marked_row("E-1")])
    rows = read_official_ewo_rows(workbook)
    assert len(rows) == 1
    row = rows[0]
    assert len(row) == 111
    # 第 58 列（BF，索引 57）起的 54 列必须来自工作簿，而不是空值。
    for index in range(57, 111):
        assert row[labels[index]] == f"{labels[index]}|E-1"
    # 第 12/30/51 列在真实件里常为空，这里同样按标记值透传（不做内容阈值判断）。
    for index in (11, 29, 50):
        assert row[labels[index]] == f"{labels[index]}|E-1"


def test_header_mismatch_and_missing_columns_are_rejected(tmp_path):
    labels = contract_labels()
    swapped = list(labels)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    workbook = write_workbook(tmp_path / "swapped.xlsx", swapped, [_marked_row("E-1")])
    with pytest.raises(EwoExportGateError) as error:
        read_official_ewo_rows(workbook)
    assert error.value.code == E_HEADER_MISMATCH

    short = list(labels[:-1])
    workbook = write_workbook(tmp_path / "short.xlsx", short, [_marked_row("E-1")[:-1]])
    with pytest.raises(EwoExportGateError) as error:
        read_official_ewo_rows(workbook)
    assert error.value.code == E_HEADER_MISMATCH


def test_extra_columns_are_allowed_only_when_empty(tmp_path):
    labels = contract_labels()
    headers = list(labels) + ["额外列"]
    empty_extra = [list(_marked_row("E-1")) + [""]]
    workbook = write_workbook(tmp_path / "extra-empty.xlsx", headers, empty_extra)
    assert len(read_official_ewo_rows(workbook)) == 1

    filled_extra = [list(_marked_row("E-1")) + ["有值"]]
    workbook = write_workbook(tmp_path / "extra-filled.xlsx", headers, filled_extra)
    with pytest.raises(EwoExportGateError) as error:
        read_official_ewo_rows(workbook)
    assert error.value.code == E_EXTRA_COLUMN_DATA


def test_reader_shape_errors_are_wrapped(tmp_path):
    labels = contract_labels()
    workbook = write_workbook(tmp_path / "wrong-sheet.xlsx", labels, [_marked_row("E-1")],
                              sheet_name="Sheet1")
    with pytest.raises(EwoExportGateError) as error:
        read_official_ewo_rows(workbook)
    assert error.value.code == E_WORKBOOK_INVALID


def test_projection_is_label_based_not_positional():
    labels = contract_labels()
    row = {label: f"{label}|E-1" for label in labels}
    shuffled = list(reversed(labels))
    matrix = project_official_ewo_rows([row], shuffled)
    assert matrix[0] == [f"{label}|E-1" for label in shuffled]


def test_reconcile_requires_matching_rows_and_unique_numbers():
    base = [{"id": "1" * 32, "_no": "E-1"}, {"id": "2" * 32, "_no": "E-2"}]
    exports = [list(_marked_row("E-1")), list(_marked_row("E-2"))]
    result = reconcile_official_rows(base, exports)
    assert result["matched_count"] == 2

    with pytest.raises(EwoExportGateError) as error:
        reconcile_official_rows(base, exports[:1])
    assert error.value.code == E_RECONCILE_MISMATCH

    duplicate = [list(_marked_row("E-1")), list(_marked_row("E-1"))]
    with pytest.raises(EwoExportGateError) as error:
        reconcile_official_rows(base, duplicate)
    assert error.value.code == E_RECONCILE_MISMATCH

    blank_row = list(_marked_row("E-2"))
    blank_row[0] = ""
    blank = [blank_row, list(_marked_row("E-2"))]
    with pytest.raises(EwoExportGateError) as error:
        reconcile_official_rows(base, blank)
    assert error.value.code == E_RECONCILE_MISMATCH


def test_label_rows_rejects_duplicate_headers():
    labels = contract_labels()
    duplicated = list(labels)
    duplicated[1] = duplicated[0]
    with pytest.raises(EwoExportGateError) as error:
        label_rows(duplicated, [_marked_row("E-1")])
    assert error.value.code == E_HEADER_MISMATCH
