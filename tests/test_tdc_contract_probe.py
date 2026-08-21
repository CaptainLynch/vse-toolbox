# -*- coding: utf-8 -*-
"""
tests/test_tdc_contract_probe.py — TDC contract probe module unit tests.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.project_status_sync_runner import create_production_registry
from services.tdc_contract_probe import (
    ABSOLUTE_MAX_RECORDS,
    CANDIDATE_KEY_FIELDS,
    DEFAULT_MAX_PAGES,
    DEFAULT_MAX_RECORDS,
    DEFAULT_PAGE_SIZE,
    MAX_CATEGORICAL_FIELDS,
    MAX_CATEGORICAL_VALUES_PER_FIELD,
    MAX_MAX_PAGES,
    MAX_PAGE_SIZE,
    CandidateKeyProfile,
    CategoricalValueSummary,
    FieldProfile,
    StabilityProfile,
    TDCContractProbeOptions,
    TDCContractProbeResult,
    VersionFieldCandidate,
    build_report,
    check_report_safety,
    compare_stability,
    extract_categorical_values,
    get_filter_field_labels,
    identify_version_candidates,
    profile_candidate_keys,
    profile_rows,
    save_report,
    serialize_report_json,
    serialize_report_markdown,
    validate_categorical_fields,
    validate_filters_non_empty,
    validate_options,
)


def _fake_rows() -> list[dict[str, str]]:
    return [
        {
            "formId": "F1",
            "incident": "WF-1",
            "documentNo": "D1",
            "approvalStatus": "审批中",
            "currentNode": "节点A",
            "updatedAt": "2026-08-20T10:00:00Z",
            "applicant": "张三",
            "requestDate": "2026-08-01",
        },
        {
            "formId": "F2",
            "incident": "WF-2",
            "documentNo": "D2",
            "approvalStatus": "已完成",
            "currentNode": "节点B",
            "updatedAt": "2026-08-20T11:00:00Z",
            "applicant": "李四",
            "requestDate": "2026-08-02",
        },
        {
            "formId": "F3",
            "incident": "WF-3",
            "documentNo": "D3",
            "approvalStatus": "审批中",
            "currentNode": "节点A",
            "updatedAt": "2026-08-20T12:00:00Z",
            "applicant": "王五",
            "requestDate": "2026-08-03",
        },
    ]


# 1. field profile stats
def test_field_profile_stats() -> None:
    rows = _fake_rows()
    profiles, distinct_values, value_lists = profile_rows(rows)

    assert "approvalStatus" in profiles
    status_prof = profiles["approvalStatus"]
    assert status_prof.present_count == 3
    assert status_prof.non_empty_count == 3
    assert status_prof.null_count == 0
    assert status_prof.distinct_count == 2
    assert status_prof.duplicate_count == 1
    assert status_prof.observed_types == ("str",)

    assert "currentNode" in profiles
    node_prof = profiles["currentNode"]
    assert node_prof.present_count == 3
    assert node_prof.non_empty_count == 3
    assert node_prof.null_count == 0
    assert node_prof.distinct_count == 2
    assert node_prof.duplicate_count == 1


# 2. candidate key no actual values
def test_candidate_key_no_actual_values() -> None:
    rows = _fake_rows()
    profiles, _, _ = profile_rows(rows)
    key_profiles = profile_candidate_keys(rows, profiles)

    assert len(key_profiles) == len(CANDIDATE_KEY_FIELDS)
    for kp in key_profiles:
        assert isinstance(kp, CandidateKeyProfile)
        assert kp.field_exists is True
        assert kp.non_empty_count == 3
        assert kp.distinct_count == 3
        assert kp.duplicate_count == 0
        assert kp.one_per_workflow is True

        # Assert no actual formId/incident/documentNo values appear in any field of any CandidateKeyProfile
        for val in ("F1", "F2", "F3", "WF-1", "WF-2", "WF-3", "D1", "D2", "D3"):
            assert val not in str(kp.__dict__)


# 3. empty filters rejected
def test_empty_filters_rejected() -> None:
    empty_filters = SimpleNamespace(
        serial_number=None,
        applicant=None,
        department=None,
        section=None,
        application_start=None,
        application_end=None,
        project_model=None,
        part_number=None,
        model_number=None,
    )
    with pytest.raises(ValueError, match="at least one non-empty filter condition is required"):
        validate_filters_non_empty(empty_filters)

    with pytest.raises(ValueError, match="filters are required"):
        validate_filters_non_empty(None)


# 4. page/record limits
def test_page_record_limits() -> None:
    with pytest.raises(ValueError, match="page_size must be between 1 and"):
        validate_options(TDCContractProbeOptions(page_size=MAX_PAGE_SIZE + 1))

    with pytest.raises(ValueError, match="page_size must be between 1 and"):
        validate_options(TDCContractProbeOptions(page_size=0))

    with pytest.raises(ValueError, match="max_pages must be between 1 and"):
        validate_options(TDCContractProbeOptions(max_pages=MAX_MAX_PAGES + 1))

    with pytest.raises(ValueError, match="max_records must be between 1 and"):
        validate_options(TDCContractProbeOptions(max_records=ABSOLUTE_MAX_RECORDS + 1))

    with pytest.raises(ValueError, match="at most 5 categorical fields allowed"):
        validate_options(
            TDCContractProbeOptions(categorical_fields=("f1", "f2", "f3", "f4", "f5", "f6"))
        )


# 5. no raw field values by default
def test_no_raw_field_values_by_default() -> None:
    rows = _fake_rows()
    opts = TDCContractProbeOptions()
    result = build_report(rows, opts, filter_fields_used=["incident"])

    assert result.categorical_values == ()


# 6. user-approved categorical fields only
def test_user_approved_categorical_fields_only() -> None:
    rows = _fake_rows()
    opts = TDCContractProbeOptions(categorical_fields=("approvalStatus",))
    result = build_report(rows, opts, filter_fields_used=["incident"])

    assert len(result.categorical_values) == 1
    summary = result.categorical_values[0]
    assert summary.field_name == "approvalStatus"
    assert summary.user_approved is True
    assert set(summary.values) == {"审批中", "已完成"}


# 7. forbidden fields rejected
def test_forbidden_fields_rejected() -> None:
    available = ["applicant", "formId", "incident", "documentNo", "user_password", "approvalStatus"]

    for forbidden in ["applicant", "formId", "incident", "documentNo", "user_password"]:
        with pytest.raises(ValueError, match="is not allowed: contains sensitive, identity, or personnel keywords"):
            validate_categorical_fields([forbidden], available)


# 8. categorical values sanitized and length-limited
def test_categorical_values_sanitized_and_length_limited() -> None:
    rows = [
        {"approvalStatus": "status password=secret safe_part"},
        {"approvalStatus": "status2 cookie=abc123456 safe_part2"},
    ]
    summaries = extract_categorical_values(rows, ["approvalStatus"])
    assert len(summaries) == 1
    values = summaries[0].values
    assert len(values) == 2
    assert "secret" not in values[0]
    assert "password=[redacted]" in values[0] or "[redacted]" in values[0]
    assert "abc123456" not in values[1]
    assert "[redacted]" in values[1]


# 9. 30 distinct value truncation
def test_categorical_values_truncation() -> None:
    rows = [{"approvalStatus": f"Status_{i}"} for i in range(35)]
    summaries = extract_categorical_values(rows, ["approvalStatus"])
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.truncated is True
    assert len(summary.values) == MAX_CATEGORICAL_VALUES_PER_FIELD


# 10. stability outputs counts only
def test_stability_outputs_counts_only() -> None:
    rows1 = _fake_rows()
    rows2 = _fake_rows()

    stability = compare_stability(rows1, rows2, first_truncated=False, second_truncated=False)
    assert stability.conclusion == "stable"
    assert stability.stable_count == 3
    assert stability.added_count == 0
    assert stability.removed_count == 0
    assert stability.duplicate_count == 0
    assert stability.row_count_match is True

    # Assert no actual key values appear in StabilityProfile fields
    for val in ("F1", "F2", "F3", "WF-1", "WF-2", "WF-3", "D1", "D2", "D3"):
        assert val not in str(stability.__dict__)


# 11. truncated stability = inconclusive
def test_truncated_stability_inconclusive() -> None:
    rows1 = _fake_rows()
    rows2 = _fake_rows()

    stability1 = compare_stability(rows1, rows2, first_truncated=True, second_truncated=False)
    assert stability1.conclusion == "inconclusive"

    stability2 = compare_stability(rows1, rows2, first_truncated=False, second_truncated=True)
    assert stability2.conclusion == "inconclusive"


# 12. version candidates names only
def test_version_candidates_names_only() -> None:
    rows = _fake_rows()
    profiles, _, _ = profile_rows(rows)
    candidates = identify_version_candidates(profiles)

    # Check that updatedAt was found as directly_observed
    observed = [c for c in candidates if c.field_name == "updatedAt"]
    assert len(observed) == 1
    assert observed[0].category == "directly_observed"

    # Check candidates have only field_name, category, reason and no actual row values
    for c in candidates:
        assert isinstance(c, VersionFieldCandidate)
        for val in ("2026-08-20T10:00:00Z", "2026-08-20T11:00:00Z", "2026-08-20T12:00:00Z", "张三", "李四"):
            assert val not in str(c.__dict__)


# 13. report no filter values/rows/headers/URL/passwords
def test_report_no_filter_values_or_credentials() -> None:
    rows = _fake_rows()
    opts = TDCContractProbeOptions()
    result = build_report(rows, opts, filter_fields_used=["incident", "projectModel"])
    text = serialize_report_json(result)

    assert "WF-1" not in text
    assert "F1" not in text
    assert "张三" not in text
    assert "tdc.sgmw" not in text.lower()
    assert "password" not in text.lower()
    assert "cookie" not in text.lower()
    assert "authorization" not in text.lower()


# 14. malicious fixture blocked
def test_malicious_fixture_blocked() -> None:
    rows = [
        {
            "formId": "F1",
            "incident": "WF-1",
            "approvalStatus": "Cookie=abc123 Authorization=Bearer xyz password=hunter2",
        }
    ]
    opts = TDCContractProbeOptions(categorical_fields=("approvalStatus",))
    result = build_report(rows, opts, filter_fields_used=["incident"])
    serialized = serialize_report_json(result)

    assert "abc123" not in serialized
    assert "xyz" not in serialized
    assert "hunter2" not in serialized
    assert "Bearer" not in serialized

    # Because "password" still appears literally in the redacted text "password=[redacted]",
    # the second safety barrier check_report_safety detects the forbidden pattern and blocks saving.
    safe, reason = check_report_safety(serialized)
    assert safe is False
    assert reason is not None and "forbidden pattern matched" in reason


# 15. report saves to .runtime
def test_report_saves_to_runtime(tmp_path: Path) -> None:
    rows = _fake_rows()
    opts = TDCContractProbeOptions()
    result = build_report(rows, opts, filter_fields_used=["incident"])

    saved = save_report(result, tmp_path)
    assert saved is not None
    json_path, md_path = saved
    assert json_path.exists()
    assert md_path.exists()
    assert json_path.suffix == ".json"
    assert md_path.suffix == ".md"


# 19. no binding/sync_runs/audit/cursor/deliverable writes
def test_no_database_manager_import() -> None:
    import services.tdc_contract_probe as probe_mod

    assert not hasattr(probe_mod, "DatabaseManager")
    assert "core.db_manager" not in probe_mod.__dict__
    assert not hasattr(probe_mod, "db_manager")


# 20. production ConnectorRegistry still empty
def test_production_connector_registry_empty() -> None:
    registry = create_production_registry()
    assert registry.registered_types == ()


# 21. field not present in sample rejected
def test_field_not_present_in_sample_rejected() -> None:
    available_fields = ["approvalStatus", "currentNode"]
    with pytest.raises(ValueError, match="is not present in the sample"):
        validate_categorical_fields(["nonExistentField"], available_fields)


# 22. filter field labels
def test_filter_field_labels() -> None:
    filters = SimpleNamespace(
        serial_number="WF-12345",
        project_model="MODEL-X",
        applicant=None,
        department=None,
        section=None,
        application_start=None,
        application_end=None,
        part_number=None,
        model_number=None,
    )
    labels = get_filter_field_labels(filters)

    assert labels == ("incident", "projectModel")
    # Assert values are NOT in the labels
    assert "WF-12345" not in labels
    assert "MODEL-X" not in labels


def test_variant_name_forbidden_fields_rejected() -> None:
    rows = [
        {
            "applicantTel": "13800000000",
            "incidentNo": "INC-001",
            "formIdDesc": "Form Description",
            "startUserName": "user1",
            "approvalStatus": "审批中",
        }
    ]
    available_fields = list(rows[0].keys())
    variants = ["applicantTel", "incidentNo", "formIdDesc", "startUserName"]
    for field_name in variants:
        with pytest.raises(
            ValueError,
            match="is not allowed: contains sensitive, identity, or personnel keywords",
        ):
            validate_categorical_fields([field_name], available_fields)


def test_markdown_safety_check_blocks_forbidden_content() -> None:
    rows = _fake_rows()
    opts = TDCContractProbeOptions()
    result = build_report(rows, opts, filter_fields_used=["incident"])
    clean_md = serialize_report_markdown(result)

    is_safe, reason = check_report_safety(clean_md)
    assert is_safe is True
    assert reason is None

    modified_md = f"{clean_md}\npassword=secret"
    is_safe, reason = check_report_safety(modified_md)
    assert is_safe is False
    assert reason is not None
    assert "forbidden pattern matched" in reason


def test_exactly_30_distinct_values_not_truncated() -> None:
    rows_30 = [{"approvalStatus": f"status_{i}"} for i in range(30)]
    summaries_30 = extract_categorical_values(rows_30, ["approvalStatus"])
    assert len(summaries_30) == 1
    assert summaries_30[0].truncated is False
    assert len(summaries_30[0].values) == 30

    rows_31 = [{"approvalStatus": f"status_{i}"} for i in range(31)]
    summaries_31 = extract_categorical_values(rows_31, ["approvalStatus"])
    assert len(summaries_31) == 1
    assert summaries_31[0].truncated is True
    assert len(summaries_31[0].values) == 30
