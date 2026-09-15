"""Deterministic EWO v2 rule normalizer and row identity helper."""

from __future__ import annotations

import unicodedata
from typing import Any

__all__ = [
    "EwoBindingV2Error",
    "normalize_ewo_v2_rule",
    "identified_ewo_v2_rows",
]

_HEX_CHARS = frozenset("0123456789abcdefABCDEF")

_REQUIRED_CORE_KEYS = frozenset({
    "contractVersion",
    "reportType",
    "bindingMode",
    "aggregate",
})

_ACTUAL_FILTER_KEYS = frozenset({
    "ewoNo",
    "projectCode",
    "subjectKeyword",
    "changeType",
    "changeSubType",
    "area",
    "state",
    "rspDepartment",
    "rspSmt",
    "submitStart",
    "submitEnd",
    "modelInfo",
})

_ALLOWED_KEYS = _REQUIRED_CORE_KEYS | _ACTUAL_FILTER_KEYS | {"sourceItemId"}


class EwoBindingV2Error(ValueError):
    """Raised when an EWO v2 rule or row payload fails contract validation."""


def _is_exact_32_hex(val: str) -> bool:
    return len(val) == 32 and all(c in _HEX_CHARS for c in val)


def _has_control_chars(val: str) -> bool:
    for ch in val:
        if unicodedata.category(ch).startswith("C") or ord(ch) < 32 or (127 <= ord(ch) <= 159):
            return True
    return False


def normalize_ewo_v2_rule(rule: dict[str, Any]) -> dict[str, Any]:
    """Normalize and validate an EWO v2 rule contract.

    Parameters
    ----------
    rule : dict
        Raw rule specification dictionary.

    Returns
    -------
    dict
        Normalized copy of the rule dictionary with field names preserved.
    """
    if not isinstance(rule, dict):
        raise EwoBindingV2Error(f"rule must be a dict, got {type(rule).__name__}")

    # Check for unknown fields
    unknown_keys = set(rule.keys()) - _ALLOWED_KEYS
    if unknown_keys:
        raise EwoBindingV2Error(f"Unknown fields in rule: {sorted(unknown_keys)}")

    # contractVersion: string exactly '2'
    if "contractVersion" not in rule:
        raise EwoBindingV2Error("Missing required field 'contractVersion'")
    version = rule["contractVersion"]
    if type(version) is not str or version != "2":
        raise EwoBindingV2Error(f"contractVersion must be string '2', got {version!r}")

    # reportType: string exactly 'ewo'
    if "reportType" not in rule:
        raise EwoBindingV2Error("Missing required field 'reportType'")
    report_type = rule["reportType"]
    if type(report_type) is not str or report_type != "ewo":
        raise EwoBindingV2Error(f"reportType must be 'ewo', got {report_type!r}")

    # bindingMode: 'single_record' or 'record_set'
    if "bindingMode" not in rule:
        raise EwoBindingV2Error("Missing required field 'bindingMode'")
    binding_mode = rule["bindingMode"]
    if type(binding_mode) is not str or binding_mode not in ("single_record", "record_set"):
        raise EwoBindingV2Error(
            f"bindingMode must be 'single_record' or 'record_set', got {binding_mode!r}"
        )

    # aggregate: boolean equal to (bindingMode == 'record_set')
    if "aggregate" not in rule:
        raise EwoBindingV2Error("Missing required field 'aggregate'")
    aggregate = rule["aggregate"]
    if type(aggregate) is not bool:
        raise EwoBindingV2Error(f"aggregate must be a boolean, got {type(aggregate).__name__}")
    expected_aggregate = binding_mode == "record_set"
    if aggregate is not expected_aggregate:
        raise EwoBindingV2Error(
            f"aggregate mismatch: expected {expected_aggregate} for bindingMode {binding_mode!r}, got {aggregate!r}"
        )

    # Validate filter fields and sourceItemId
    actual_filters_present: list[str] = []
    for key in rule:
        if key in _ACTUAL_FILTER_KEYS:
            val = rule[key]
            if type(val) is not str:
                raise EwoBindingV2Error(
                    f"Filter field {key!r} must be a string, got {type(val).__name__}"
                )
            trimmed = val.strip()
            if not trimmed:
                raise EwoBindingV2Error(f"Filter field {key!r} must not be blank or empty")
            if len(trimmed) > 1000:
                raise EwoBindingV2Error(
                    f"Filter field {key!r} length {len(trimmed)} exceeds maximum 1000 characters"
                )
            if _has_control_chars(val):
                raise EwoBindingV2Error(f"Filter field {key!r} contains forbidden control characters")
            actual_filters_present.append(key)

    # Mode-specific constraints
    if binding_mode == "single_record":
        if "sourceItemId" not in rule:
            raise EwoBindingV2Error("bindingMode 'single_record' requires 'sourceItemId'")
        source_item_id = rule["sourceItemId"]
        if type(source_item_id) is not str:
            raise EwoBindingV2Error(
                f"'sourceItemId' must be a string, got {type(source_item_id).__name__}"
            )
        if not _is_exact_32_hex(source_item_id):
            raise EwoBindingV2Error(
                f"'sourceItemId' must be exact 32 hexadecimal characters, got {source_item_id!r}"
            )
        if not actual_filters_present:
            raise EwoBindingV2Error(
                "bindingMode 'single_record' requires at least one actual filter"
            )
    else:  # record_set
        if "sourceItemId" in rule:
            raise EwoBindingV2Error("bindingMode 'record_set' rejects 'sourceItemId'")
        if not actual_filters_present:
            raise EwoBindingV2Error(
                "bindingMode 'record_set' requires at least one actual filter"
            )

    # Construct normalized copy preserving key presence and field names
    normalized: dict[str, Any] = {}
    for key in rule:
        if key == "contractVersion":
            normalized[key] = "2"
        elif key == "reportType":
            normalized[key] = "ewo"
        elif key == "bindingMode":
            normalized[key] = binding_mode
        elif key == "aggregate":
            normalized[key] = aggregate
        elif key == "sourceItemId":
            normalized[key] = rule["sourceItemId"].upper()
        elif key in _ACTUAL_FILTER_KEYS:
            normalized[key] = rule[key].strip()

    return normalized


def identified_ewo_v2_rows(
    rows: list[dict[str, Any]] | tuple[dict[str, Any], ...]
) -> list[tuple[str, dict[str, Any]]]:
    """Validate and canonize row identity for EWO v2 rows.

    Parameters
    ----------
    rows : list[dict] or tuple[dict]
        Input rows collection (maximum 5000 items).

    Returns
    -------
    list[tuple[str, dict]]
        List of (canonical_id, row_copy) pairs sorted by canonical ID.
    """
    if not isinstance(rows, (list, tuple)):
        raise EwoBindingV2Error(f"rows must be a list or tuple, got {type(rows).__name__}")
    if len(rows) > 5000:
        raise EwoBindingV2Error(f"rows exceeds maximum batch size of 5000 (got {len(rows)})")
    if not rows:
        return []

    seen_ids: set[str] = set()
    result: list[tuple[str, dict[str, Any]]] = []

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise EwoBindingV2Error(f"Row at index {index} must be a dict, got {type(row).__name__}")
        if "_source_item_id" not in row:
            raise EwoBindingV2Error(
                f"Row at index {index} is missing required '_source_item_id'"
            )
        raw_id = row["_source_item_id"]
        if type(raw_id) is not str:
            raise EwoBindingV2Error(
                f"Row at index {index} '_source_item_id' must be a string, got {type(raw_id).__name__}"
            )
        if not _is_exact_32_hex(raw_id):
            raise EwoBindingV2Error(
                f"Row at index {index} '_source_item_id' must be exact 32 hexadecimal characters"
            )
        canonical_id = raw_id.upper()
        if canonical_id in seen_ids:
            raise EwoBindingV2Error(
                f"Duplicate canonical _source_item_id detected: {canonical_id}"
            )
        seen_ids.add(canonical_id)

        row_copy = dict(row)
        row_copy["_source_item_id"] = canonical_id
        result.append((canonical_id, row_copy))

    result.sort(key=lambda item: item[0])
    return result
