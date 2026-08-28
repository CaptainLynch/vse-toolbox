# -*- coding: utf-8 -*-
"""Focused tests for report tabular contracts, column counts, header hierarchy, and row normalization."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.report_contracts import report_contracts, table_payload
from services.aras_crawler import ArasCrawlerClient


# ── 1. Report Contracts Structural Invariants ─────────────────────────────────


def test_report_contracts_contains_all_approved_types() -> None:
    """Contract registry contains the approved Aras and TDC report types."""
    contracts = report_contracts()
    assert set(contracts.keys()) == {
        "ewo",
        "paa",
        "ncr_progress",
        "ncr_detail",
        "tdc_data_model",
        "tdc_sor",
    }


def test_tdc_data_model_report_contract_matches_official_export_shape() -> None:
    contract = report_contracts()["tdc_data_model"]
    assert contract["columnCount"] == 47
    assert contract["defaultVisibleCount"] == 47
    assert len(contract["headerRows"]) == 1
    assert len(contract["headerRows"][0]) == 47
    assert contract["headerRows"][0][:3] == ["实例号", "流程名", "流水单号"]
    assert contract["headerRows"][0][-6:] == ["应签人数", "已签人数", "未签人数", "签署率", "待审批人员", "状态"]


def test_tdc_sor_report_contract_matches_production_csv_shape() -> None:
    contract = report_contracts()["tdc_sor"]
    expected_headers = [
        "流水单号",
        "车型项目",
        "类型",
        "SOR号",
        "版本号",
        "标题",
        "零件号",
        "零件名称",
        "申请人",
        "部门",
        "科室",
        "申请日期",
        "最新完成节点",
        "审批状态",
        "当前待办人",
    ]

    assert contract["columnCount"] == 15
    assert contract["defaultVisibleCount"] == 15
    assert contract["headerRows"] == [expected_headers]


def test_ewo_report_contract_invariants() -> None:
    """EWO contract defines exactly 111 columns, 1 header row, defaultVisibleCount 12, and no internal titles."""
    contract = report_contracts()["ewo"]
    assert contract["columnCount"] == 111
    assert contract["defaultVisibleCount"] == 12

    header_rows = contract["headerRows"]
    assert len(header_rows) == 1
    assert len(header_rows[0]) == 111

    # Verify absence of internal visible titles like _no or _subject
    for label in header_rows[0]:
        assert label is not None
        clean_label = str(label).strip()
        assert not clean_label.startswith("_")
        assert not clean_label.endswith("_no")
        assert not clean_label.endswith("_subject")


def test_paa_report_contract_invariants() -> None:
    """PAA contract defines exactly 113 columns, 1 header row, defaultVisibleCount 12, and no internal titles."""
    contract = report_contracts()["paa"]
    assert contract["columnCount"] == 113
    assert contract["defaultVisibleCount"] == 12

    header_rows = contract["headerRows"]
    assert len(header_rows) == 1
    assert len(header_rows[0]) == 113

    # Verify absence of internal visible titles like _no or _subject
    for label in header_rows[0]:
        assert label is not None
        clean_label = str(label).strip()
        assert not clean_label.startswith("_")
        assert not clean_label.endswith("_no")
        assert not clean_label.endswith("_subject")


def test_ncr_progress_report_contract_invariants() -> None:
    """NCR progress defines 64 columns, 2 header rows, data header at row 2 (index 1), and defaultVisibleCount 12."""
    contract = report_contracts()["ncr_progress"]
    assert contract["columnCount"] == 64
    assert contract["defaultVisibleCount"] == 12
    assert contract.get("dataHeaderRow", 0) == 1  # 2nd header row (0-indexed 1)

    header_rows = contract["headerRows"]
    assert len(header_rows) == 2
    assert len(header_rows[1]) == 64

    # Data header row contains meaningful labels
    labels = [str(label or "").strip() for label in header_rows[1]]
    assert "状态" in labels
    assert "NCR编号" in labels


def test_ncr_detail_report_contract_invariants() -> None:
    """NCR detail defines 65 columns, five header rows, data header at row 5 (index 4), and defaultVisibleCount 17."""
    contract = report_contracts()["ncr_detail"]
    assert contract["columnCount"] == 65
    assert contract["defaultVisibleCount"] == 17
    assert contract.get("dataHeaderRow", 0) == 4  # 5th header row (0-indexed 4)

    header_rows = contract["headerRows"]
    assert len(header_rows) == 5  # Five header rows
    assert len(header_rows[4]) == 65


# ── 2. table_payload Source-Key Normalization ─────────────────────────────────


def test_table_payload_rejects_unsupported_report_type() -> None:
    """Unsupported report types raise ValueError."""
    with pytest.raises(ValueError, match="unsupported report contract: invalid_type_xyz"):
        table_payload("invalid_type_xyz", [])


@pytest.mark.parametrize(
    ("report_type", "expected_col_count", "expected_visible_count"),
    [
        ("ewo", 111, 12),
        ("paa", 113, 12),
        ("ncr_progress", 64, 12),
        ("ncr_detail", 65, 17),
        ("tdc_data_model", 47, 47),
        ("tdc_sor", 15, 15),
    ],
)
def test_table_payload_normalization_with_fictional_rows(
    report_type: str,
    expected_col_count: int,
    expected_visible_count: int,
) -> None:
    """Unknown fields never populate a workbook column by dictionary position."""
    fictional_input_rows = [
        {
            "invented_col_a": "fictional_val_1",
            "invented_col_b": "fictional_val_2",
            "invented_col_c": 12345,
        },
        {
            "invented_col_a": "fictional_val_3",
            "invented_col_d": True,
        },
    ]

    result = table_payload(report_type, fictional_input_rows)

    assert "headerRows" in result
    assert "columns" in result
    assert "rows" in result
    assert result["defaultVisibleCount"] == expected_visible_count

    columns = result["columns"]
    assert len(columns) == expected_col_count
    for index, col in enumerate(columns):
        assert col["key"] == f"column_{index + 1}"
        assert col["index"] == index
        assert isinstance(col["label"], str)

    rows = result["rows"]
    assert len(rows) == 2

    # There is no positional fallback: every column is explicitly unmapped.
    first_row = rows[0]
    assert len(first_row) == expected_col_count
    assert all(value is None for value in first_row)

    second_row = rows[1]
    assert len(second_row) == expected_col_count
    assert all(value is None for value in second_row)
    if report_type == "tdc_sor":
        assert result["unmappedColumns"] == []
        assert result["mappingComplete"] is True
    else:
        assert result["unmappedColumns"]

    # Verify internal dictionary keys are not present in the columns or rows
    raw_str = str(result)
    assert "invented_col_a" not in raw_str
    assert "invented_col_b" not in raw_str
    assert "invented_col_c" not in raw_str
    assert "invented_col_d" not in raw_str


def test_table_payload_empty_input_rows() -> None:
    """table_payload returns empty normalized rows list when input rows are empty."""
    result = table_payload("ewo", [])
    assert result["rows"] == []
    assert len(result["columns"]) == 111
    assert result["defaultVisibleCount"] == 12


def test_table_payload_truncates_oversized_rows() -> None:
    """Oversized unknown dictionaries do not leak positional values into the table."""
    contract = report_contracts()["ncr_progress"]
    col_count = contract["columnCount"]  # 64

    # Invent a row with 100 values
    oversized_input = [{f"invented_key_{i}": f"val_{i}" for i in range(100)}]
    result = table_payload("ncr_progress", oversized_input)

    assert len(result["rows"]) == 1
    normalized_row = result["rows"][0]
    assert len(normalized_row) == col_count
    assert all(value is None for value in normalized_row)


def test_ewo_table_payload_uses_source_keys_and_xml_display_names() -> None:
    source = {
        "state": "DRAFT1",
        "_subject": "subject",
        "_sort_sub_type": "PWO-EWO定点",
        "created_by_id__keyed_name": "起草人(user)",
        "_rsp_smt": "视觉工程科",
        "_rsp_name": "责任工程师(user)",
        "_no": "EWO-TEST",
    }

    row = table_payload("ewo", [source])["rows"][0]
    assert row[0] == "EWO-TEST"
    assert row[1] == "EWO定点"
    assert row[2] == "起草人(user)"
    assert row[3] == "责任工程师(user)"
    assert row[4] == "视觉工程科"
    assert row[5] == "subject"
    assert row[9] == "DRAFT1"


def test_real_ewo_fixture_is_not_positionally_shifted() -> None:
    fixture = Path(__file__).parent / "fixtures" / "crawler" / "ewo_query_response.xml"
    page = ArasCrawlerClient.parse_ewo_report_response(fixture.read_text(encoding="utf-8"))

    result = table_payload("ewo", page.rows)
    first = result["rows"][0]
    assert first[0] == "EWO-047840"
    assert first[1] == "EWO定点"
    assert first[2] == "龚鹏(g22400718)"
    assert first[3] == "龚鹏(g22400718)"
    assert first[5] == "N300P&PS迭代座椅设计发布"
    assert first[9] == "DRAFT1"
    assert first[17] == "批量生产 PRODUCTION TYPE"
    assert first[20] == "整车or变速箱"
    assert first[23] == "N"
    assert first[36] == "2026-12-10"


def test_real_paa_fixture_is_not_positionally_shifted() -> None:
    fixture = Path(__file__).parent / "fixtures" / "crawler" / "paa_query_page_1.xml"
    page = ArasCrawlerClient.parse_paa_report_response(fixture.read_text(encoding="utf-8"))

    result = table_payload("paa", page.rows)
    first = result["rows"][0]
    assert first[0] == "PAA000001"
    assert first[1] == "让步和偏离许可使用"
    assert first[2] == "USER_SAMPLE"
    assert first[8] == "DRAFT1"
    assert first[23] == "EWO000001"
    assert first[18] == "整车or变速箱"
    assert first[22] == "Y"
    assert first[39] == "N/A不适用"
    assert first[43] == "天数"


def test_tdc_data_model_table_payload_uses_explicit_list_field_mapping() -> None:
    source = {
        "incident": "INC-1",
        "processName": "T2发布",
        "documentNo": "F610M-3D-0001",
        "publishProperty": "T2发布",
        "applicant": "申请人",
        "department": "外饰科",
        "superDepartment": "车体工程",
        "requestDate": "2026-01-09 14:31:33",
        "projectModel": "F610M",
        "partNumber": "PART-1",
        "modelNumber": "MODEL-1",
        "partName": "零件",
        "versionNumber": "001",
        "ewosorNumber": "N/A",
        "latestApproveLog": "审批完成",
        "esSectionApprover": "造型专家",
        "designEngineerApprover": "设计工程师",
        "chiefEngineerApprover": "主任工程师",
        "sectionManagerApprover": "专家经理",
        "platformEngineerApprover": "首席总监",
        "status": "4",
    }

    result = table_payload("tdc_data_model", [source])
    row = result["rows"][0]

    assert row[0:11] == [
        "INC-1",
        "T2发布",
        "F610M-3D-0001",
        "T2发布",
        "申请人",
        "外饰科",
        "2026-01-09 14:31:33",
        "F610M",
        "PART-1",
        "MODEL-1",
        "零件",
    ]
    assert row[11] is None
    assert row[14] == "001"
    assert row[16] == "N/A"
    assert row[17] == "审批完成"
    assert row[34] == "造型专家"
    assert row[37:41] == ["设计工程师", "主任工程师", "专家经理", "首席总监"]
    assert row[46] == "已完成"
    assert result["mappingComplete"] is False
    assert "数量" in result["unmappedColumns"]


def test_tdc_sor_table_payload_uses_production_column_order() -> None:
    source = {
        "processNo": "SOR-1",
        "carTypeProject": "E262S",
        "processType": "发布流程",
        "sorNo": "SOR-9",
        "version": "A",
        "title": "座椅 SOR",
        "sorPartNo": "PART-1",
        "sorPartName": "座椅",
        "startUserName": "申请人",
        "deptName": "车体工程",
        "sectionName": "内饰科",
        "startTime": "2026-08-26 10:00:00",
        "latestCompletedNode": "审核",
        "processInstanceStatus": "审批中",
        "currentAssigneeNameList": "张三、李四",
    }

    result = table_payload("tdc_sor", [source])

    assert result["rows"] == [[
        "SOR-1",
        "E262S",
        "发布流程",
        "SOR-9",
        "A",
        "座椅 SOR",
        "PART-1",
        "座椅",
        "申请人",
        "车体工程",
        "内饰科",
        "2026-08-26 10:00:00",
        "审核",
        "审批中",
        "张三、李四",
    ]]
    assert result["mappingComplete"] is True
    assert result["unmappedColumns"] == []
