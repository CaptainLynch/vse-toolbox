"""User-visible tabular contracts derived from approved report workbooks.

The workbook headers and the Aras/TDC response fields are deliberately kept as
two separate contracts.  Response dictionaries are not ordered data: Aras may
omit null properties and the XML child order can change between records.  A
column therefore has to name its source fields explicitly; an unverified column
is returned as ``None`` instead of receiving a value from a neighbouring field.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence, cast


_CONTRACT_PATH = Path(__file__).with_name("report_headers.json")

# These are the source fields that have been verified from the captured Aras
# XML/HTML.  The remaining workbook columns are workflow-derived or need an
# additional relationship query; they intentionally stay unmapped until that
# source contract is confirmed.
_EWO_SOURCE_FIELDS: dict[int, tuple[str, ...]] = {
    0: ("_no", "keyed_name"),
    1: ("_sort_sub_type",),
    2: ("created_by_id__keyed_name",),
    3: ("_rsp_name",),
    4: ("_rsp_smt",),
    5: ("_subject",),
    6: ("_modelinfo",),
    8: ("created_on",),
    9: ("state", "current_state__name", "current_state__keyed_name"),
    10: ("eplmwriteneplcode",),
    12: ("_submit_time",),
    13: ("_rsp_phone",),
    14: ("_rsp_department",),
    15: ("_division",),
    16: ("_required_date",),
    17: ("_wo_type",),
    18: ("_sort_type",),
    19: ("_change_purpose",),
    20: ("_project_type",),
    21: ("_change_reason_description",),
    22: ("_change_description",),
    23: ("_coordinated_change",),
    24: ("_coordinated_part_name",),
    25: ("_coordinated_implement_comments",),
    26: ("_coordinated_wo",),
    28: ("_coordinated_paa",),
    30: ("_mockup",),
    31: ("_test_lab",),
    32: ("_road_test",),
    33: ("_ptr",),
    34: ("_affect_manufacture",),
    35: ("_affect_ots",),
    36: ("_affect_ots_time",),
    37: ("_affect_fe",),
    38: ("_affect_ppap",),
    39: ("_affect_ppap_time",),
    40: ("_affect_service",),
    41: ("_affect_service_type",),
    42: ("_vehicle_param",),
    43: ("_affect_notice",),
    44: ("_affect_green",),
    45: ("_affect_3c",),
    46: ("_affect_3c_cert",),
    47: ("_cvcev",),
    48: ("_is_self_made",),
    49: ("_is_buy",),
    50: ("_kdlc_strategy",),
    51: ("_affect_online_config",),
    52: ("_affect_vehicle_basic_data",),
    53: ("_affect_appearance",),
    56: ("_area",),
}

_PAA_SOURCE_FIELDS: dict[int, tuple[str, ...]] = {
    0: ("_no", "keyed_name"),
    1: ("_auth_type",),
    2: ("created_by_id__keyed_name",),
    3: ("_requester_smt",),
    4: ("_requester_department",),
    5: ("_requester_phone",),
    6: ("_reason",),
    7: ("_vehicles",),
    8: ("state", "current_state__name", "current_state__keyed_name"),
    9: ("created_on",),
    10: ("_submit_date",),
    11: ("_issue_date",),
    12: ("_pe_tdc_name", "_pe_tdc__keyed_name"),
    13: ("_pe_tdc_smt",),
    14: ("_pe_tdc_department",),
    15: ("_pe_tdc_phone",),
    18: ("_project_type",),
    19: ("_base",),
    20: ("_area",),
    21: ("_model_year",),
    22: ("_support_ewo_concession",),
    23: ("_ewo_no",),
    24: ("_emis_related",),
    25: ("_mass_impact",),
    26: ("_key_part",),
    27: ("_license_tag",),
    28: ("_effect_consistency",),
    29: ("_change_description",),
    30: ("_affect_vehicle_photo",),
    31: ("_affect_certificate",),
    32: ("_validation_statement",),
    33: ("_stakeholder_buy_in",),
    34: ("_rework_place",),
    35: ("_resp_unit",),
    36: ("_est_cost",),
    37: ("_charge_to",),
    38: ("_mtl_rq_date",),
    39: ("_stock_disp",),
    40: ("_spcl_instr",),
    41: ("_pp_comments",),
    43: ("_days_or_qty",),
    44: ("_days",),
    45: ("_quantity",),
    46: ("_est_cmpl_date",),
    47: ("_exted_reason",),
}

# The TDC list endpoint is a detail-level response: one workflow may contain
# several part/model rows.  These are the fields verified against the
# official 47-column export.  Export-only approval/detail columns stay
# unmapped for list responses instead of being filled from a neighbouring
# JSON property.
_TDC_DATA_MODEL_SOURCE_FIELDS: dict[int, tuple[str, ...]] = {
    0: ("incident",),
    1: ("processName",),
    2: ("documentNo",),
    3: ("publishProperty",),
    4: ("applicant",),
    5: ("department",),
    6: ("requestDate",),
    7: ("projectModel",),
    8: ("partNumber",),
    9: ("modelNumber",),
    10: ("partName",),
    14: ("versionNumber",),
    16: ("ewosorNumber",),
    17: ("latestApproveLog",),
    34: ("esSectionApprover",),
    37: ("designEngineerApprover",),
    38: ("chiefEngineerApprover",),
    39: ("sectionManagerApprover",),
    40: ("platformEngineerApprover",),
    46: ("status",),
}

_TDC_SOR_SOURCE_FIELDS: dict[int, tuple[str, ...]] = {
    0: ("processNo",),
    1: ("carTypeProject",),
    2: ("processType", "bizName", "type"),
    3: ("sorNo",),
    4: ("version",),
    5: ("title",),
    6: ("sorPartNo",),
    7: ("sorPartName",),
    8: ("startUserName",),
    9: ("deptName",),
    10: ("sectionName",),
    11: ("startTime",),
    12: ("latestCompletedNode",),
    13: ("processInstanceStatus",),
    14: ("currentAssigneeNameList",),
}

_SOURCE_FIELDS_BY_REPORT: dict[str, dict[int, tuple[str, ...]]] = {
    "ewo": _EWO_SOURCE_FIELDS,
    "paa": _PAA_SOURCE_FIELDS,
    "tdc_data_model": _TDC_DATA_MODEL_SOURCE_FIELDS,
    "tdc_sor": _TDC_SOR_SOURCE_FIELDS,
}

_TRANSFORMS_BY_REPORT_INDEX: dict[tuple[str, int], str] = {
    ("ewo", 1): "aras_sub_sort",
    ("ewo", 15): "division_label",
    ("ewo", 8): "date_only",
    ("ewo", 12): "date_only",
    ("ewo", 16): "date_only",
    ("ewo", 17): "ewo_wo_type",
    ("ewo", 20): "project_type_label",
    ("ewo", 23): "yn_label",
    ("ewo", 30): "yn_label",
    ("ewo", 31): "yn_label",
    ("ewo", 32): "yn_label",
    ("ewo", 33): "yn_label",
    ("ewo", 34): "yn_label",
    ("ewo", 35): "yn_label",
    ("ewo", 37): "yn_label",
    ("ewo", 38): "yn_label",
    ("ewo", 40): "yn_label",
    ("ewo", 42): "yn_label",
    ("ewo", 43): "yn_label",
    ("ewo", 44): "yn_label",
    ("ewo", 45): "yn_label",
    ("ewo", 46): "yn_label",
    ("ewo", 48): "yn_label",
    ("ewo", 49): "yn_label",
    ("ewo", 51): "yn_label",
    ("ewo", 52): "yn_label",
    ("ewo", 53): "yn_label",
    ("ewo", 36): "date_only",
    ("ewo", 39): "date_only",
    ("paa", 1): "paa_auth_type",
    ("paa", 9): "date_only",
    ("paa", 10): "date_only",
    ("paa", 11): "date_only",
    ("paa", 18): "project_type_label",
    ("paa", 22): "yn_label",
    ("paa", 24): "yn_label",
    ("paa", 25): "yn_label",
    ("paa", 26): "yn_label",
    ("paa", 27): "yn_label",
    ("paa", 28): "yn_label",
    ("paa", 30): "yn_label",
    ("paa", 31): "yn_label",
    ("paa", 38): "date_only",
    ("paa", 39): "paa_stock_disp",
    ("paa", 43): "paa_days_or_qty",
    ("paa", 46): "date_only",
    ("tdc_data_model", 6): "date_time",
    ("tdc_data_model", 46): "tdc_status",
}

_ENUM_LABELS: dict[str, dict[str, str]] = {
    "ewo_wo_type": {
        "1": "批量生产 PRODUCTION TYPE",
    },
    "paa_auth_type": {
        "1": "让步和偏离许可使用",
    },
    "project_type_label": {"1": "整车or变速箱"},
    "paa_stock_disp": {"3": "N/A不适用"},
    "paa_days_or_qty": {"0": "天数"},
    "tdc_status": {
        "4": "已完成",
    },
}


@lru_cache(maxsize=1)
def report_contracts() -> dict[str, dict[str, Any]]:
    return cast(dict[str, dict[str, Any]], json.loads(_CONTRACT_PATH.read_text(encoding="utf-8")))


def _transform_value(report_type: str, index: int, value: object | None) -> object | None:
    if value is None:
        return None
    transform = _TRANSFORMS_BY_REPORT_INDEX.get((report_type, index))
    if transform == "aras_sub_sort":
        text = str(value).strip()
        text = re.sub(r"^[A-Za-z]+-", "", text)
        return re.sub(r"\(全新EPL\)$", "", text)
    if transform == "division_label":
        return {"1": "SGMW"}.get(str(value), value)
    if transform == "date_only":
        match = re.match(r"^(\d{4}-\d{2}-\d{2})", str(value).strip())
        return match.group(1) if match else value
    if transform == "date_time":
        return str(value).strip()
    if transform == "yn_label":
        return {"0": "N", "1": "Y"}.get(str(value), value)
    if transform in _ENUM_LABELS:
        return _ENUM_LABELS[transform].get(str(value), value)
    return value


def _column_specs(report_type: str, contract: Mapping[str, Any]) -> tuple[list[dict[str, object]], list[str]]:
    header_rows = contract["headerRows"]
    data_header_row = int(contract.get("dataHeaderRow", 0))
    labels = header_rows[data_header_row]
    source_map = _SOURCE_FIELDS_BY_REPORT.get(report_type, {})
    columns: list[dict[str, object]] = []
    unmapped: list[str] = []
    for index, label in enumerate(labels):
        source_fields = source_map.get(index, ())
        label_text = str(label or "").strip()
        columns.append(
            {
                "key": f"column_{index + 1}",
                "label": label_text,
                "index": index,
                "sourceFields": list(source_fields),
            }
        )
        if not source_fields and label_text:
            unmapped.append(label_text)
    return columns, unmapped


def table_payload(report_type: str, rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Return a stable table shape using explicit source-field lookups."""
    try:
        contract = report_contracts()[report_type]
    except KeyError as exc:
        raise ValueError(f"unsupported report contract: {report_type}") from exc
    header_rows = contract["headerRows"]
    columns, unmapped = _column_specs(report_type, contract)
    normalized_rows: list[list[object | None]] = []
    for source in rows:
        normalized: list[object | None] = []
        for column in columns:
            index = cast(int, column["index"])
            source_fields = cast(list[str], column["sourceFields"])
            value = next((source.get(field) for field in source_fields if field in source), None)
            normalized.append(_transform_value(report_type, index, value))
        normalized_rows.append(normalized)
    return {
        "headerRows": header_rows,
        "columns": columns,
        "rows": normalized_rows,
        "defaultVisibleCount": int(contract["defaultVisibleCount"]),
        "unmappedColumns": unmapped,
        "mappingComplete": not unmapped,
    }


def matrix_payload(report_type: str, rows: Sequence[Sequence[object]]) -> dict[str, object]:
    """Build the same table shape from rows already read from an official workbook."""
    try:
        contract = report_contracts()[report_type]
    except KeyError as exc:
        raise ValueError(f"unsupported report contract: {report_type}") from exc
    header_rows = contract["headerRows"]
    columns, unmapped = _column_specs(report_type, contract)
    width = len(columns)
    normalized_rows = [list(row[:width]) + [None] * max(0, width - len(row)) for row in rows]
    return {
        "headerRows": header_rows,
        "columns": columns,
        "rows": normalized_rows,
        "defaultVisibleCount": int(contract["defaultVisibleCount"]),
        "unmappedColumns": [],
        "mappingComplete": True,
    }
