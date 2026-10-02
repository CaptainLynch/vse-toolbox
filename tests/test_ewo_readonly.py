"""Unit tests for services.ewo_readonly pure association and state summary functions."""
from __future__ import annotations

import copy
import pytest

from services.ewo_readonly import associate_export_rows, summarize_states


def test_unique_match_and_reordered_rows() -> None:
    headers = ["EWO编号", "状态", "科室"]
    base_rows = [
        {"id": "base-1", "_no": "EWO-001", "state": "OPEN"},
        {"id": "base-2", "_no": "EWO-002", "state": "CLOSE"},
        {"id": "base-3", "_no": "EWO-003", "state": "DRAFT1"},
    ]
    # export rows reordered relative to base_rows
    export_rows = [
        ["EWO-003", "草案", "车身"],
        ["EWO-001", "打开", "车身"],
        ["EWO-002", "关闭", "底盘"],
    ]

    result = associate_export_rows(base_rows, headers, export_rows)

    assert result["base_count"] == 3
    assert result["export_count"] == 3
    assert result["matched_count"] == 3
    assert result["unmatched_count"] == 0
    assert result["ambiguous_count"] == 0
    assert result["blank_number_count"] == 0

    assocs = result["associations"]
    assert len(assocs) == 3

    assert assocs[0]["row_index"] == 1
    assert assocs[0]["status"] == "matched"
    assert assocs[0]["source_item_id"] == "base-3"
    assert assocs[0]["business_number"] == "EWO-003"
    assert assocs[0]["fields"] == {"EWO编号": "EWO-003", "状态": "草案", "科室": "车身"}

    assert assocs[1]["row_index"] == 2
    assert assocs[1]["status"] == "matched"
    assert assocs[1]["source_item_id"] == "base-1"
    assert assocs[1]["business_number"] == "EWO-001"

    assert assocs[2]["row_index"] == 3
    assert assocs[2]["status"] == "matched"
    assert assocs[2]["source_item_id"] == "base-2"
    assert assocs[2]["business_number"] == "EWO-002"


def test_both_side_duplicates_ambiguous() -> None:
    headers = ["项目", "EWO编号"]
    # Base has duplicate EWO-DUP
    base_rows = [
        {"id": "b1", "_no": "EWO-DUP"},
        {"id": "b2", "_no": "EWO-DUP"},
        {"id": "b3", "_no": "EWO-UNIQUE-BASE"},
    ]
    # Export has duplicate EWO-EXP-DUP and single EWO-DUP
    export_rows = [
        ["P1", "EWO-DUP"],        # duplicate on base side -> ambiguous
        ["P2", "EWO-EXP-DUP"],    # duplicate on export side -> ambiguous
        ["P3", "EWO-EXP-DUP"],    # duplicate on export side -> ambiguous
        ["P4", "EWO-ABSENT"],     # absent -> unmatched
    ]

    result = associate_export_rows(base_rows, headers, export_rows)

    assert result["matched_count"] == 0
    assert result["unmatched_count"] == 1
    assert result["ambiguous_count"] == 3
    assert result["blank_number_count"] == 0

    assert result["associations"][0]["status"] == "ambiguous"
    assert result["associations"][0]["source_item_id"] is None
    assert result["associations"][1]["status"] == "ambiguous"
    assert result["associations"][1]["source_item_id"] is None
    assert result["associations"][2]["status"] == "ambiguous"
    assert result["associations"][2]["source_item_id"] is None
    assert result["associations"][3]["status"] == "unmatched"
    assert result["associations"][3]["source_item_id"] is None


def test_empty_missing_and_blank_business_number() -> None:
    headers = ["EWO编号", "备注"]
    base_rows = [
        {"id": "b1", "_no": "  "},
        {"id": "b2", "_no": None},
        {"id": "b3", "_no": 12345},  # non-str treated as blank
        {"id": "b4", "_no": "EWO-REAL"},
    ]
    export_rows = [
        ["", "empty"],
        ["   ", "whitespace"],
        [None, "none"],
        [999, "integer"],
        ["EWO-REAL", "real"],
    ]

    result = associate_export_rows(base_rows, headers, export_rows)

    assert result["base_count"] == 4
    assert result["export_count"] == 5
    assert result["matched_count"] == 1
    assert result["unmatched_count"] == 0
    assert result["ambiguous_count"] == 0
    assert result["blank_number_count"] == 4

    for i in range(4):
        assert result["associations"][i]["status"] == "blank_number"
        assert result["associations"][i]["source_item_id"] is None
        assert result["associations"][i]["business_number"] == ""

    assert result["associations"][4]["status"] == "matched"
    assert result["associations"][4]["source_item_id"] == "b4"
    assert result["associations"][4]["business_number"] == "EWO-REAL"


def test_extra_headers_and_extra_columns_kept() -> None:
    headers = ["ColA", "EWO编号", "ColB", "ColC"]
    base_rows = [{"id": "b1", "_no": "E-1"}]
    # Export row length matches headers
    export_rows = [
        ["valA", " E-1 ", "valB", "valC"],
        # shorter export row fills missing fields with None
        ["valA2", "E-100"],
    ]

    result = associate_export_rows(base_rows, headers, export_rows)

    assert result["matched_count"] == 1
    assert result["unmatched_count"] == 1
    assoc0 = result["associations"][0]
    assert assoc0["status"] == "matched"
    assert assoc0["business_number"] == "E-1"
    assert assoc0["fields"] == {
        "ColA": "valA",
        "EWO编号": " E-1 ",
        "ColB": "valB",
        "ColC": "valC",
    }

    assoc1 = result["associations"][1]
    assert assoc1["status"] == "unmatched"
    assert assoc1["business_number"] == "E-100"
    assert assoc1["fields"] == {
        "ColA": "valA2",
        "EWO编号": "E-100",
        "ColB": None,
        "ColC": None,
    }


def test_invalid_structure_and_bounds() -> None:
    # 1. Row wider than headers
    with pytest.raises(ValueError, match="exceeds headers length"):
        associate_export_rows([], ["EWO编号"], [["val1", "val2"]])

    # 2. Missing EWO编号
    with pytest.raises(ValueError, match="Missing required header"):
        associate_export_rows([], ["编号", "状态"], [])

    # 3. Duplicate headers
    with pytest.raises(ValueError, match="Duplicate header"):
        associate_export_rows([], ["EWO编号", "状态", "状态"], [])

    # 4. Empty header
    with pytest.raises(ValueError, match="Headers must be nonempty strings"):
        associate_export_rows([], ["EWO编号", ""], [])

    # 5. Non-str header
    with pytest.raises(ValueError, match="Headers must be nonempty strings"):
        associate_export_rows([], ["EWO编号", 123], [])  # type: ignore

    # 6. Exceed max columns (>200)
    huge_headers = [f"Col{i}" for i in range(200)] + ["EWO编号"]
    with pytest.raises(ValueError, match="headers count 201 exceeds limit 200"):
        associate_export_rows([], huge_headers, [])

    # 7. Exceed max base rows (>5000)
    huge_base = [{"id": f"id-{i}", "_no": f"no-{i}"} for i in range(5001)]
    with pytest.raises(ValueError, match="base_rows count 5001 exceeds limit 5000"):
        associate_export_rows(huge_base, ["EWO编号"], [])

    # 8. Exceed max export rows (>5000)
    huge_export = [["no"] for _ in range(5001)]
    with pytest.raises(ValueError, match="export_rows count 5001 exceeds limit 5000"):
        associate_export_rows([], ["EWO编号"], huge_export)

    # 9. Missing base id
    with pytest.raises(ValueError, match="Base row missing required 'id' key"):
        associate_export_rows([{"_no": "1"}], ["EWO编号"], [])

    # 10. Non-string base id
    with pytest.raises(ValueError, match="Base row 'id' must be a string"):
        associate_export_rows([{"id": 123, "_no": "1"}], ["EWO编号"], [])

    # 11. Duplicate base id
    with pytest.raises(ValueError, match="Duplicate base id"):
        associate_export_rows(
            [{"id": "dup-id", "_no": "1"}, {"id": "dup-id", "_no": "2"}],
            ["EWO编号"],
            [],
        )

    # 12. Empty/whitespace base id
    with pytest.raises(ValueError, match="Base row 'id' cannot be empty"):
        associate_export_rows([{"id": "   ", "_no": "1"}], ["EWO编号"], [])


def test_inputs_not_mutated() -> None:
    headers = ["EWO编号", "状态"]
    base_rows = [{"id": "b-1", "_no": " E-1 ", "state": "OPEN"}]
    export_rows = [[" E-1 ", "进行中"]]

    base_copy = copy.deepcopy(base_rows)
    headers_copy = copy.deepcopy(headers)
    export_copy = copy.deepcopy(export_rows)

    associate_export_rows(base_rows, headers, export_rows)

    assert base_rows == base_copy
    assert headers == headers_copy
    assert export_rows == export_copy


def test_zero_rows_accepted_with_valid_headers() -> None:
    headers = ["EWO编号", "项目"]
    result = associate_export_rows([], headers, [])
    assert result == {
        "base_count": 0,
        "export_count": 0,
        "matched_count": 0,
        "unmatched_count": 0,
        "ambiguous_count": 0,
        "blank_number_count": 0,
        "associations": [],
    }


def test_counts_sum_to_export_count() -> None:
    headers = ["EWO编号"]
    base_rows = [
        {"id": "b1", "_no": "MATCH1"},
        {"id": "b2", "_no": "DUP"},
        {"id": "b3", "_no": "DUP"},
    ]
    export_rows = [
        ["MATCH1"],   # matched
        ["DUP"],      # ambiguous (dup in base)
        ["UNMATCH"],  # unmatched
        [""],         # blank_number
        ["  "],       # blank_number
    ]
    res = associate_export_rows(base_rows, headers, export_rows)
    assert res["export_count"] == 5
    assert (
        res["matched_count"]
        + res["unmatched_count"]
        + res["ambiguous_count"]
        + res["blank_number_count"]
        == res["export_count"]
    )
    assert res["matched_count"] == 1
    assert res["unmatched_count"] == 1
    assert res["ambiguous_count"] == 1
    assert res["blank_number_count"] == 2


def test_synthetic_410_rows_yields_406_matched_4_blank() -> None:
    headers = ["EWO编号", "描述"]
    # 406 unique nonblank base rows
    base_rows = [
        {"id": f"base-id-{i}", "_no": f"SYN-EWO-{i:04d}", "state": "OPEN"}
        for i in range(1, 407)
    ]
    # 410 export rows: 406 matching unique numbers + 4 blanks
    export_rows = [[f"SYN-EWO-{i:04d}", f"Desc {i}"] for i in range(1, 407)]
    export_rows.extend([
        ["", "blank 1"],
        ["   ", "blank 2"],
        [None, "blank 3"],
        ["", "blank 4"],
    ])

    res = associate_export_rows(base_rows, headers, export_rows)

    assert res["base_count"] == 406
    assert res["export_count"] == 410
    assert res["matched_count"] == 406
    assert res["blank_number_count"] == 4
    assert res["unmatched_count"] == 0
    assert res["ambiguous_count"] == 0
    assert len(res["associations"]) == 410


def test_summarize_states_partitions_and_independent_missing() -> None:
    rows = [
        {"_no": "E1", "state": "OPEN"},
        {"_no": "E2", "state": " open "},
        {"_no": "E3", "state": "CLOSE"},
        {"_no": "E4", "state": "close"},
        {"_no": "E5", "state": "CANCEL"},
        {"_no": "E6", "state": "cancel"},
        {"_no": "E7", "state": "DRAFT1"},
        {"_no": "E8", "state": "draft2"},
        {"_no": "E9", "state": "EDIT1"},
        {"_no": "E10", "state": "edit2"},
        {"_no": "E11", "state": "PROC"},
        {"_no": "E12", "state": "impl"},
        {"_no": "E13", "state": "SOMETHING_ELSE"},
        {"_no": "E14", "state": None},
        {"_no": "E15", "state": ""},
        {"_no": "  ", "state": "OPEN"},          # missing _no
        {"_no": None, "state": "CLOSE"},         # missing _no
        {"state": "CANCEL"},                     # missing _no
        {"_no": 12345, "state": "DRAFT1"},       # non-str missing _no
    ]

    summary = summarize_states(rows)

    assert summary["total"] == 19
    assert summary["completed"] == 2
    assert summary["cancelled"] == 2
    assert summary["open"] == 2
    assert summary["other"] == 4
    assert summary["unknown"] == 9

    # Total partition check
    assert (
        summary["completed"]
        + summary["cancelled"]
        + summary["open"]
        + summary["other"]
        + summary["unknown"]
        == summary["total"]
    )

    # Independent missing_business_number count: rows without valid string _no
    # E16 ("  "), E17 (None), E18 (missing key), E19 (12345) -> 4
    assert summary["missing_business_number"] == 4


def test_summarize_states_empty() -> None:
    summary = summarize_states([])
    assert summary == {
        "total": 0,
        "completed": 0,
        "cancelled": 0,
        "open": 0,
        "other": 0,
        "unknown": 0,
        "missing_business_number": 0,
    }
