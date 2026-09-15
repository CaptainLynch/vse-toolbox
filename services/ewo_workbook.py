from __future__ import annotations

import pathlib
from typing import Any

from services.xlsx_preview import XLSXPreviewError, read_xlsx_preview

REQUIRED_HEADERS: tuple[str, ...] = (
    "EWO编号",
    "责任工程师名称",
    "要求完成时间",
    "状态",
    "当前阶段未签署的角色&人员",
)

MAX_ROWS: int = 5001
MAX_COLUMNS: int = 200
MAX_DATA_ROWS: int = 5000


def _is_empty_cell(cell: Any) -> bool:
    if cell is None:
        return True
    if isinstance(cell, str) and not cell.strip():
        return True
    return False


def _is_empty_row(row: list[Any]) -> bool:
    return all(_is_empty_cell(c) for c in row)


def read_ewo_workbook(path: pathlib.Path) -> dict[str, Any]:
    if not isinstance(path, pathlib.Path):
        path = pathlib.Path(path)

    try:
        preview = read_xlsx_preview(path, max_rows=MAX_ROWS, max_columns=MAX_COLUMNS)
    except XLSXPreviewError:
        raise ValueError("Failed to read Excel workbook.") from None

    if preview.truncated:
        raise ValueError("Workbook exceeds maximum allowed limits or is truncated.")

    if not preview.sheet_names or preview.sheet_names[0] != "Innovator":
        raise ValueError("The first sheet of the workbook must be named 'Innovator'.")

    if preview.sheet_name != "Innovator":
        raise ValueError("The first sheet of the workbook must be named 'Innovator'.")

    if not preview.rows:
        raise ValueError("Workbook is empty.")

    raw_headers = preview.rows[0]
    if not raw_headers:
        raise ValueError("Workbook header row is empty.")

    if len(raw_headers) > MAX_COLUMNS:
        raise ValueError(f"Workbook exceeds maximum column limit of {MAX_COLUMNS}.")

    headers: list[str] = []
    for col_idx, h in enumerate(raw_headers):
        if not isinstance(h, str):
            raise ValueError(
                f"Header at column {col_idx + 1} must be a non-empty string."
            )
        stripped = h.strip()
        if not stripped:
            raise ValueError(
                f"Header at column {col_idx + 1} must be a non-empty string."
            )
        headers.append(stripped)

    if len(headers) != len(set(headers)):
        raise ValueError("Workbook contains duplicate headers.")

    missing_headers = [req for req in REQUIRED_HEADERS if req not in headers]
    if missing_headers:
        raise ValueError(
            f"Workbook is missing required headers: {', '.join(missing_headers)}."
        )

    header_len = len(headers)
    cleaned_rows: list[list[Any]] = []

    for row_idx, raw_row in enumerate(preview.rows[1:], start=2):
        if _is_empty_row(raw_row):
            continue

        if len(raw_row) > header_len:
            raise ValueError(
                f"Row {row_idx} has {len(raw_row)} columns, exceeding header width of {header_len}."
            )

        if len(raw_row) < header_len:
            padded_row = list(raw_row) + [None] * (header_len - len(raw_row))
        else:
            padded_row = list(raw_row)

        cleaned_rows.append(padded_row)

    if len(cleaned_rows) > MAX_DATA_ROWS:
        raise ValueError(
            f"Workbook exceeds maximum data rows limit of {MAX_DATA_ROWS}."
        )

    return {
        "headers": headers,
        "rows": cleaned_rows,
        "sheet_name": preview.sheet_name,
        "truncated": False,
    }
