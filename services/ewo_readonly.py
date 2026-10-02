"""Pure Python helpers for matching synthetic tabular rows and counting EWO states.

This module uses only the Python standard library.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

_MAX_ROWS = 5000
_MAX_COLS = 200
_BUSINESS_KEY_HEADER = "EWO编号"

_OTHER_STATES = frozenset({"DRAFT1", "DRAFT2", "EDIT1", "EDIT2", "PROC", "IMPL"})


def associate_export_rows(
    base_rows: List[Dict[str, Any]],
    headers: List[str],
    export_rows: List[List[Any]],
) -> Dict[str, Any]:
    """Associate tabular export rows with base rows using strict unique matching.

    Inputs:
    - base_rows: list of base dicts with 'id' and '_no'
    - headers: list of unique nonempty str headers containing 'EWO编号'
    - export_rows: list of lists of export cells

    Raises ValueError for:
    - >5000 base_rows or export_rows
    - >200 columns (headers length)
    - duplicate or empty (or non-string) headers
    - missing 'EWO编号' header
    - export rows wider than headers
    - missing or duplicate base id, or non-string base id
    """
    if len(base_rows) > _MAX_ROWS:
        raise ValueError(f"base_rows count {len(base_rows)} exceeds limit {_MAX_ROWS}")
    if len(export_rows) > _MAX_ROWS:
        raise ValueError(f"export_rows count {len(export_rows)} exceeds limit {_MAX_ROWS}")
    if len(headers) > _MAX_COLS:
        raise ValueError(f"headers count {len(headers)} exceeds limit {_MAX_COLS}")

    # Validate headers: must be list of unique nonempty str containing 'EWO编号'
    seen_headers = set()
    for h in headers:
        if not isinstance(h, str) or not h:
            raise ValueError("Headers must be nonempty strings")
        if h in seen_headers:
            raise ValueError(f"Duplicate header: {h!r}")
        seen_headers.add(h)

    if _BUSINESS_KEY_HEADER not in seen_headers:
        raise ValueError(f"Missing required header: {_BUSINESS_KEY_HEADER!r}")

    ewo_col_idx = headers.index(_BUSINESS_KEY_HEADER)
    header_len = len(headers)

    # Validate and index base_rows
    # Missing or duplicate base id -> ValueError
    # IDs accept str only, trim whitespace
    seen_base_ids = set()
    base_by_no: Dict[str, List[str]] = {}

    for row in base_rows:
        if not isinstance(row, dict):
            raise ValueError("Each base row must be a dictionary")
        if "id" not in row:
            raise ValueError("Base row missing required 'id' key")
        raw_id = row["id"]
        if not isinstance(raw_id, str):
            raise ValueError(f"Base row 'id' must be a string, got {type(raw_id).__name__}")
        base_id = raw_id.strip()
        if not base_id:
            raise ValueError("Base row 'id' cannot be empty or whitespace only")
        if base_id in seen_base_ids:
            raise ValueError(f"Duplicate base id: {base_id!r}")
        seen_base_ids.add(base_id)

        raw_no = row.get("_no")
        # Non-str business number treated as blank
        if isinstance(raw_no, str):
            clean_no = raw_no.strip()
        else:
            clean_no = ""

        if clean_no:
            base_by_no.setdefault(clean_no, []).append(base_id)

    # Validate export rows and prepare association candidates
    # Row wider than headers -> ValueError
    prepared_exports: List[Dict[str, Any]] = []
    export_counts_by_no: Dict[str, int] = {}

    for row_idx, row in enumerate(export_rows, start=1):
        if not isinstance(row, list):
            raise ValueError(f"Export row {row_idx} must be a list")
        if len(row) > header_len:
            raise ValueError(
                f"Export row {row_idx} length {len(row)} exceeds headers length {header_len}"
            )

        # Nonblank business number
        raw_cell = row[ewo_col_idx] if ewo_col_idx < len(row) else None
        if isinstance(raw_cell, str):
            clean_cell_no = raw_cell.strip()
        else:
            clean_cell_no = ""

        if clean_cell_no:
            export_counts_by_no[clean_cell_no] = export_counts_by_no.get(clean_cell_no, 0) + 1

        fields: Dict[str, Any] = {}
        for h_idx, h_name in enumerate(headers):
            fields[h_name] = row[h_idx] if h_idx < len(row) else None

        prepared_exports.append(
            {
                "row_index": row_idx,
                "business_number": clean_cell_no,
                "fields": fields,
            }
        )

    # Classify associations
    associations: List[Dict[str, Any]] = []
    matched_count = 0
    unmatched_count = 0
    ambiguous_count = 0
    blank_number_count = 0

    for exp in prepared_exports:
        b_no = exp["business_number"]
        row_index = exp["row_index"]
        fields = exp["fields"]

        if not b_no:
            status = "blank_number"
            source_item_id: Optional[str] = None
            blank_number_count += 1
        elif export_counts_by_no[b_no] > 1 or len(base_by_no.get(b_no, [])) > 1:
            # Repeated numbers on either side ambiguous even if same values
            status = "ambiguous"
            source_item_id = None
            ambiguous_count += 1
        elif len(base_by_no.get(b_no, [])) == 1:
            # Unique on both sides
            status = "matched"
            source_item_id = base_by_no[b_no][0]
            matched_count += 1
        else:
            # Not found in base
            status = "unmatched"
            source_item_id = None
            unmatched_count += 1

        associations.append(
            {
                "row_index": row_index,
                "status": status,
                "source_item_id": source_item_id,
                "business_number": b_no,
                "fields": fields,
            }
        )

    return {
        "base_count": len(base_rows),
        "export_count": len(export_rows),
        "matched_count": matched_count,
        "unmatched_count": unmatched_count,
        "ambiguous_count": ambiguous_count,
        "blank_number_count": blank_number_count,
        "associations": associations,
    }


def summarize_states(base_rows: List[Dict[str, Any]]) -> Dict[str, int]:
    """Summarize counts of EWO states from base rows.

    Partition of total:
    - completed: CLOSE
    - cancelled: CANCEL
    - open: OPEN
    - other: DRAFT1, DRAFT2, EDIT1, EDIT2, PROC, IMPL
    - unknown: everything else

    missing_business_number is an independent count (non-string or whitespace-only _no).
    Exact uppercase states after trim; do not alias or silently close unknown.
    """
    total = len(base_rows)
    completed = 0
    cancelled = 0
    open_count = 0
    other = 0
    unknown = 0
    missing_business_number = 0

    for row in base_rows:
        raw_no = row.get("_no") if isinstance(row, dict) else None
        if not isinstance(raw_no, str) or not raw_no.strip():
            missing_business_number += 1

        raw_state = row.get("state") if isinstance(row, dict) else None
        if isinstance(raw_state, str):
            clean_state = raw_state.strip()
        else:
            clean_state = None

        if clean_state == "CLOSE":
            completed += 1
        elif clean_state == "CANCEL":
            cancelled += 1
        elif clean_state == "OPEN":
            open_count += 1
        elif clean_state in _OTHER_STATES:
            other += 1
        else:
            unknown += 1

    return {
        "total": total,
        "completed": completed,
        "cancelled": cancelled,
        "open": open_count,
        "other": other,
        "unknown": unknown,
        "missing_business_number": missing_business_number,
    }
