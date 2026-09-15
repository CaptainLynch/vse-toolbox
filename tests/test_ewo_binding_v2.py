"""Synthetic unit tests for deterministic EWO v2 rule normalizer and row identity helper."""

from __future__ import annotations

import copy
import pytest

from core.ewo_binding_v2 import (
    EwoBindingV2Error,
    identified_ewo_v2_rows,
    normalize_ewo_v2_rule,
)

_VALID_HEX_32 = "0123456789abcdef0123456789abcdef"
_VALID_HEX_32_UPPER = _VALID_HEX_32.upper()
_ANOTHER_HEX_32 = "ffffffffffffffffaaaaaaaaaaaaaaaa"
_ANOTHER_HEX_32_UPPER = _ANOTHER_HEX_32.upper()


# ---------------------------------------------------------------------------
# normalize_ewo_v2_rule tests
# ---------------------------------------------------------------------------

def test_normalize_rule_non_dict_rejects() -> None:
    for invalid in [None, "not_a_dict", 42, [1, 2, 3], True]:
        with pytest.raises((ValueError, TypeError)):
            normalize_ewo_v2_rule(invalid)  # type: ignore[arg-type]


def test_normalize_rule_missing_version_rejects() -> None:
    rule = {
        "reportType": "ewo",
        "bindingMode": "record_set",
        "aggregate": True,
        "ewoNo": "EWO-001",
    }
    with pytest.raises(ValueError):
        normalize_ewo_v2_rule(rule)


def test_normalize_rule_legacy_and_unknown_versions_reject() -> None:
    for bad_version in ["1", "v2", "3", "0", "", " 2 "]:
        rule = {
            "contractVersion": bad_version,
            "reportType": "ewo",
            "bindingMode": "record_set",
            "aggregate": True,
            "ewoNo": "EWO-001",
        }
        with pytest.raises(ValueError):
            normalize_ewo_v2_rule(rule)


def test_normalize_rule_numeric_and_bool_version_rejects() -> None:
    for bad_version in [2, True, False, 2.0, 1]:
        rule = {
            "contractVersion": bad_version,
            "reportType": "ewo",
            "bindingMode": "record_set",
            "aggregate": True,
            "ewoNo": "EWO-001",
        }
        with pytest.raises(ValueError):
            normalize_ewo_v2_rule(rule)


def test_normalize_rule_report_type_invalid_or_missing_rejects() -> None:
    for bad_report_type in [None, "ecn", "EWO", "ewo_v2", 123]:
        rule = {
            "contractVersion": "2",
            "reportType": bad_report_type,
            "bindingMode": "record_set",
            "aggregate": True,
            "ewoNo": "EWO-001",
        }
        with pytest.raises(ValueError):
            normalize_ewo_v2_rule(rule)

    rule_no_report = {
        "contractVersion": "2",
        "bindingMode": "record_set",
        "aggregate": True,
        "ewoNo": "EWO-001",
    }
    with pytest.raises(ValueError):
        normalize_ewo_v2_rule(rule_no_report)


def test_normalize_rule_mode_mismatch_rejects() -> None:
    # single_record requires aggregate=False
    with pytest.raises(ValueError):
        normalize_ewo_v2_rule({
            "contractVersion": "2",
            "reportType": "ewo",
            "bindingMode": "single_record",
            "aggregate": True,
            "sourceItemId": _VALID_HEX_32,
            "ewoNo": "EWO-001",
        })

    # record_set requires aggregate=True
    with pytest.raises(ValueError):
        normalize_ewo_v2_rule({
            "contractVersion": "2",
            "reportType": "ewo",
            "bindingMode": "record_set",
            "aggregate": False,
            "ewoNo": "EWO-001",
        })

    # Unknown bindingMode
    with pytest.raises(ValueError):
        normalize_ewo_v2_rule({
            "contractVersion": "2",
            "reportType": "ewo",
            "bindingMode": "individual",
            "aggregate": False,
            "ewoNo": "EWO-001",
        })

    # aggregate non-boolean (1/0/"true"/None)
    for bad_aggregate in [1, 0, "true", "True", None]:
        with pytest.raises(ValueError):
            normalize_ewo_v2_rule({
                "contractVersion": "2",
                "reportType": "ewo",
                "bindingMode": "record_set",
                "aggregate": bad_aggregate,
                "ewoNo": "EWO-001",
            })


def test_normalize_rule_record_set_rejects_source_item_id() -> None:
    rule = {
        "contractVersion": "2",
        "reportType": "ewo",
        "bindingMode": "record_set",
        "aggregate": True,
        "sourceItemId": _VALID_HEX_32,
        "ewoNo": "EWO-001",
    }
    with pytest.raises(ValueError):
        normalize_ewo_v2_rule(rule)


def test_normalize_rule_single_record_requires_id_and_filter() -> None:
    # Missing sourceItemId
    with pytest.raises(ValueError):
        normalize_ewo_v2_rule({
            "contractVersion": "2",
            "reportType": "ewo",
            "bindingMode": "single_record",
            "aggregate": False,
            "ewoNo": "EWO-001",
        })

    # Has sourceItemId but no actual filter
    with pytest.raises(ValueError):
        normalize_ewo_v2_rule({
            "contractVersion": "2",
            "reportType": "ewo",
            "bindingMode": "single_record",
            "aggregate": False,
            "sourceItemId": _VALID_HEX_32,
        })


def test_normalize_rule_record_set_requires_at_least_one_filter() -> None:
    with pytest.raises(ValueError):
        normalize_ewo_v2_rule({
            "contractVersion": "2",
            "reportType": "ewo",
            "bindingMode": "record_set",
            "aggregate": True,
        })


def test_normalize_rule_unknown_key_rejects() -> None:
    rule = {
        "contractVersion": "2",
        "reportType": "ewo",
        "bindingMode": "record_set",
        "aggregate": True,
        "ewoNo": "EWO-001",
        "unknownKey": "unexpected",
    }
    with pytest.raises(ValueError):
        normalize_ewo_v2_rule(rule)


def test_normalize_rule_invalid_filter_types_reject() -> None:
    for invalid_val in [123, True, False, None, ["a"], {"k": "v"}]:
        rule = {
            "contractVersion": "2",
            "reportType": "ewo",
            "bindingMode": "record_set",
            "aggregate": True,
            "ewoNo": invalid_val,
        }
        with pytest.raises(ValueError):
            normalize_ewo_v2_rule(rule)


def test_normalize_rule_blank_and_empty_filters_reject() -> None:
    for empty_val in ["", "   ", "\t  \n"]:
        rule = {
            "contractVersion": "2",
            "reportType": "ewo",
            "bindingMode": "record_set",
            "aggregate": True,
            "ewoNo": empty_val,
        }
        with pytest.raises(ValueError):
            normalize_ewo_v2_rule(rule)


def test_normalize_rule_filter_length_boundary() -> None:
    # 1000 characters is allowed
    long_val = "A" * 1000
    rule = {
        "contractVersion": "2",
        "reportType": "ewo",
        "bindingMode": "record_set",
        "aggregate": True,
        "subjectKeyword": long_val,
    }
    result = normalize_ewo_v2_rule(rule)
    assert result["subjectKeyword"] == long_val

    # 1001 characters rejects
    rule_over = copy.deepcopy(rule)
    rule_over["subjectKeyword"] = "A" * 1001
    with pytest.raises(ValueError):
        normalize_ewo_v2_rule(rule_over)


def test_normalize_rule_control_characters_reject() -> None:
    control_chars = ["\x00", "\x1f", "\n", "\r", "\t", "\x7f", "\x85"]
    for ch in control_chars:
        rule = {
            "contractVersion": "2",
            "reportType": "ewo",
            "bindingMode": "record_set",
            "aggregate": True,
            "ewoNo": f"EWO{ch}001",
        }
        with pytest.raises(ValueError):
            normalize_ewo_v2_rule(rule)


def test_normalize_rule_invalid_source_item_id_rejects() -> None:
    invalid_ids = [
        "0123456789abcdef0123456789abcde",      # 31 chars
        "0123456789abcdef0123456789abcdef0",     # 33 chars
        "0123456789abcdef0123456789abcdeg",     # 'g' is not hex
        f" {_VALID_HEX_32}",                     # Leading whitespace (do not trim ID beyond hex contract)
        f"{_VALID_HEX_32} ",                     # Trailing whitespace
        12345678901234567890123456789012,        # Int
        None,
    ]
    for bad_id in invalid_ids:
        rule = {
            "contractVersion": "2",
            "reportType": "ewo",
            "bindingMode": "single_record",
            "aggregate": False,
            "sourceItemId": bad_id,
            "ewoNo": "EWO-001",
        }
        with pytest.raises(ValueError):
            normalize_ewo_v2_rule(rule)


def test_normalize_rule_whitespace_filter_trimmed() -> None:
    rule = {
        "contractVersion": "2",
        "reportType": "ewo",
        "bindingMode": "record_set",
        "aggregate": True,
        "ewoNo": "  EWO-12345 \t ",
        "projectCode": " PRJ-99  ",
    }
    # Note: control character check applies to the trimmed content.
    # If the input has tab at ends that get trimmed, wait, let's verify tab inside vs ends.
    # In test, test pure spaces trimming:
    clean_rule = {
        "contractVersion": "2",
        "reportType": "ewo",
        "bindingMode": "record_set",
        "aggregate": True,
        "ewoNo": "   EWO-12345   ",
        "projectCode": "  PRJ-99  ",
    }
    normalized = normalize_ewo_v2_rule(clean_rule)
    assert normalized["ewoNo"] == "EWO-12345"
    assert normalized["projectCode"] == "PRJ-99"


def test_normalize_rule_lowercase_id_normalized() -> None:
    rule = {
        "contractVersion": "2",
        "reportType": "ewo",
        "bindingMode": "single_record",
        "aggregate": False,
        "sourceItemId": _VALID_HEX_32,  # lowercase
        "ewoNo": "EWO-001",
    }
    normalized = normalize_ewo_v2_rule(rule)
    assert normalized["sourceItemId"] == _VALID_HEX_32_UPPER


def test_normalize_rule_caller_not_mutated() -> None:
    original = {
        "contractVersion": "2",
        "reportType": "ewo",
        "bindingMode": "single_record",
        "aggregate": False,
        "sourceItemId": _VALID_HEX_32,
        "ewoNo": "  EWO-001  ",
        "projectCode": "  PRJ-01  ",
    }
    snapshot = copy.deepcopy(original)
    result = normalize_ewo_v2_rule(original)

    assert original == snapshot
    assert result is not original
    assert result["sourceItemId"] == _VALID_HEX_32_UPPER
    assert result["ewoNo"] == "EWO-001"
    assert original["sourceItemId"] == _VALID_HEX_32
    assert original["ewoNo"] == "  EWO-001  "


def test_normalize_rule_all_actual_filters_accepted() -> None:
    rule = {
        "contractVersion": "2",
        "reportType": "ewo",
        "bindingMode": "record_set",
        "aggregate": True,
        "ewoNo": "EWO-100",
        "projectCode": "PRJ-200",
        "subjectKeyword": "Chassis",
        "changeType": "Design",
        "changeSubType": "Wiring",
        "area": "Body",
        "state": "In Review",
        "rspDepartment": "EE",
        "rspSmt": "SMT-1",
        "submitStart": "2026-01-01",
        "submitEnd": "2026-09-15",
        "modelInfo": "Model-X",
    }
    normalized = normalize_ewo_v2_rule(rule)
    assert normalized["contractVersion"] == "2"
    assert normalized["reportType"] == "ewo"
    assert normalized["bindingMode"] == "record_set"
    assert normalized["aggregate"] is True
    assert normalized["ewoNo"] == "EWO-100"
    assert normalized["submitEnd"] == "2026-09-15"


# ---------------------------------------------------------------------------
# identified_ewo_v2_rows tests
# ---------------------------------------------------------------------------

def test_identified_rows_empty_returns_empty() -> None:
    assert identified_ewo_v2_rows([]) == []
    assert identified_ewo_v2_rows(()) == []


def test_identified_rows_non_sequence_rejects() -> None:
    for invalid in [None, "string", {"_source_item_id": _VALID_HEX_32}, 123]:
        with pytest.raises((ValueError, TypeError)):
            identified_ewo_v2_rows(invalid)  # type: ignore[arg-type]


def test_identified_rows_non_dict_row_rejects() -> None:
    with pytest.raises(ValueError):
        identified_ewo_v2_rows(["not_a_dict"])  # type: ignore[list-item]


def test_identified_rows_missing_id_with_business_number_rejects() -> None:
    rows = [
        {"_no": "EWO-2026-0001", "name": "Item 1"},
    ]
    with pytest.raises(ValueError):
        identified_ewo_v2_rows(rows)


def test_identified_rows_invalid_id_format_rejects() -> None:
    bad_ids = [
        "A" * 31,
        "A" * 33,
        "G" * 32,
        f" {_VALID_HEX_32}",
        f"{_VALID_HEX_32} ",
        12345,
        None,
    ]
    for bad_id in bad_ids:
        rows = [{"_source_item_id": bad_id, "_no": "EWO-1"}]
        with pytest.raises(ValueError):
            identified_ewo_v2_rows(rows)


def test_identified_rows_duplicate_case_ids_reject() -> None:
    # One row has lowercase ID, one row has uppercase identical ID
    rows = [
        {"_source_item_id": _VALID_HEX_32, "_no": "EWO-001"},
        {"_source_item_id": _VALID_HEX_32_UPPER, "_no": "EWO-002"},
    ]
    with pytest.raises(ValueError):
        identified_ewo_v2_rows(rows)


def test_identified_rows_exact_duplicate_ids_reject() -> None:
    rows = [
        {"_source_item_id": _VALID_HEX_32, "_no": "EWO-001"},
        {"_source_item_id": _VALID_HEX_32, "_no": "EWO-002"},
    ]
    with pytest.raises(ValueError):
        identified_ewo_v2_rows(rows)


def test_identified_rows_exceeding_5000_rejects() -> None:
    oversized = [{"_source_item_id": f"{i:032X}"} for i in range(5001)]
    with pytest.raises(ValueError):
        identified_ewo_v2_rows(oversized)


def test_identified_rows_up_to_5000_succeeds() -> None:
    # Test boundary of 5000 items
    batch_5000 = [{"_source_item_id": f"{i:032X}"} for i in range(5000)]
    identified = identified_ewo_v2_rows(batch_5000)
    assert len(identified) == 5000
    assert identified[0][0] == f"{0:032X}"
    assert identified[-1][0] == f"{4999:032X}"


def test_identified_rows_blank_and_duplicate_business_numbers_retained() -> None:
    id_1 = "11111111111111111111111111111111"
    id_2 = "22222222222222222222222222222222"
    id_3 = "33333333333333333333333333333333"

    rows = [
        {"_source_item_id": id_1, "_no": ""},              # blank business number
        {"_source_item_id": id_2, "_no": "EWO-SAME"},      # duplicate business number
        {"_source_item_id": id_3, "_no": "EWO-SAME"},      # duplicate business number
    ]
    result = identified_ewo_v2_rows(rows)
    assert len(result) == 3
    assert result[0] == (id_1, {"_source_item_id": id_1, "_no": ""})
    assert result[1] == (id_2, {"_source_item_id": id_2, "_no": "EWO-SAME"})
    assert result[2] == (id_3, {"_source_item_id": id_3, "_no": "EWO-SAME"})


def test_identified_rows_missing_business_number_retained() -> None:
    id_1 = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    rows = [{"_source_item_id": id_1, "other_field": "val"}]
    result = identified_ewo_v2_rows(rows)
    assert len(result) == 1
    assert result[0][0] == id_1
    assert "_no" not in result[0][1]
    assert result[0][1]["other_field"] == "val"


def test_identified_rows_order_independent() -> None:
    id_a = "11111111111111111111111111111111"
    id_b = "55555555555555555555555555555555"
    id_c = "99999999999999999999999999999999"

    # Pass in descending order
    rows = [
        {"_source_item_id": id_c, "_no": "C"},
        {"_source_item_id": id_a, "_no": "A"},
        {"_source_item_id": id_b, "_no": "B"},
    ]
    result = identified_ewo_v2_rows(rows)
    assert [item[0] for item in result] == [id_a, id_b, id_c]
    assert [item[1]["_no"] for item in result] == ["A", "B", "C"]


def test_identified_rows_caller_not_mutated_and_canonical_id() -> None:
    original_row_1 = {"_source_item_id": _VALID_HEX_32, "_no": "EWO-1", "extra": 42}
    original_row_2 = {"_source_item_id": _ANOTHER_HEX_32, "_no": "EWO-2", "extra": 99}
    rows = [original_row_1, original_row_2]
    snapshot_rows = copy.deepcopy(rows)

    result = identified_ewo_v2_rows(rows)

    # Caller input unchanged
    assert rows == snapshot_rows
    assert original_row_1["_source_item_id"] == _VALID_HEX_32
    assert original_row_2["_source_item_id"] == _ANOTHER_HEX_32

    # Canonical ID normalized to uppercase in result
    for canon_id, row_dict in result:
        assert canon_id == canon_id.upper()
        assert row_dict["_source_item_id"] == canon_id

    # Mutating returned dictionary does not mutate original row
    result[0][1]["extra"] = 9999
    assert original_row_1["extra"] == 42
    assert original_row_2["extra"] == 99
