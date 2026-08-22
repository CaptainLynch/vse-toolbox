# -*- coding: utf-8 -*-
"""Unit tests for ProjectStatusAnalyticsService covering saved evidence summaries and redaction."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from core.db_manager import DatabaseManager
from services.project_status_analytics import ProjectStatusAnalyticsService


@pytest.fixture
def test_db(tmp_path) -> DatabaseManager:
    db = DatabaseManager(db_path=tmp_path / "analytics_test.db")
    db.init_database()
    return db


@pytest.fixture
def service(test_db: DatabaseManager) -> ProjectStatusAnalyticsService:
    return ProjectStatusAnalyticsService(test_db)


def test_overview_no_evidence_defaults(service: ProjectStatusAnalyticsService) -> None:
    data = service.overview()
    assert data["phaseId"] == "VPI-T2"
    assert data["staleAfterHours"] == 24
    deliverables = data["deliverables"]
    assert len(deliverables) == 5

    expected_restrictions = {
        "VPI-T2-D1": "manual_only",
        "VPI-T2-D2": None,
        "VPI-T2-D3": None,
        "VPI-T2-D4": "contract_blocked",
        "VPI-T2-D5": None,
    }

    for item in deliverables:
        d_id = item["deliverableId"]
        assert item["externalRecordCount"] is None
        assert item["mappingEvidence"] is None
        assert item["confirmedDifference"] is None
        assert item["confirmedFieldDifferences"] is None
        assert item["mappingStability"] == {"confirmed": 0, "required": 2, "ready": False}
        assert item["freshness"] == "unknown"
        assert item["syncRestriction"] == expected_restrictions[d_id]
        assert item["needsAttention"] is False
        assert item["riskSummary"] is None
        assert item["failureCount"] == 0
        assert item["runTrend"] == {}


def test_overview_matched_and_zero_candidate_count(
    test_db: DatabaseManager, service: ProjectStatusAnalyticsService
) -> None:
    test_db.record_mapping_observation(
        deliverable_id="VPI-T2-D5",
        source_type="tdc",
        result_state="matched",
        external_key="FLOW-001",
        candidate_fingerprint="fp1",
        candidate_count=0,
        candidate_summary_json=json.dumps([{"incident": "FLOW-001", "secret": "hide"}]),
        field_report_json=json.dumps({"fields": ["owner", "status"]}),
    )
    test_db.record_mapping_observation(
        deliverable_id="VPI-T2-D5",
        source_type="tdc",
        result_state="matched",
        external_key="FLOW-001",
        candidate_fingerprint="fp2",
        candidate_count=0,
        candidate_summary_json=json.dumps([]),
        field_report_json=json.dumps({}),
    )

    data = service.overview()
    item = next(d for d in data["deliverables"] if d["deliverableId"] == "VPI-T2-D5")

    assert item["externalRecordCount"] == 0
    assert item["mappingEvidence"] is not None
    assert item["mappingEvidence"]["state"] == "matched"
    assert item["mappingEvidence"]["externalKey"] == "FLOW-001"
    assert item["mappingEvidence"]["candidateCount"] == 0
    assert isinstance(item["mappingEvidence"]["observedAt"], str)

    # Ensure no candidate samples or field report in mappingEvidence
    assert "candidate_summary" not in item["mappingEvidence"]
    assert "candidateSummary" not in item["mappingEvidence"]
    assert "fieldReport" not in item["mappingEvidence"]
    assert "field_report" not in item["mappingEvidence"]
    assert "secret" not in json.dumps(item["mappingEvidence"])

    assert item["mappingStability"] == {"confirmed": 2, "required": 2, "ready": True}
    assert item["needsAttention"] is False
    assert item["riskSummary"] is None


def test_overview_ambiguous_evidence_and_derived_risk_summary(
    test_db: DatabaseManager, service: ProjectStatusAnalyticsService
) -> None:
    test_db.record_mapping_observation(
        deliverable_id="VPI-T2-D3",
        source_type="aras",
        result_state="ambiguous",
        external_key=None,
        candidate_fingerprint="fp-multi",
        candidate_count=4,
        candidate_summary_json=json.dumps([{"id": 1}, {"id": 2}]),
        field_report_json=json.dumps({}),
    )

    data = service.overview()
    item = next(d for d in data["deliverables"] if d["deliverableId"] == "VPI-T2-D3")

    assert item["externalRecordCount"] == 4
    assert item["mappingEvidence"] == {
        "state": "ambiguous",
        "externalKey": None,
        "candidateCount": 4,
        "observedAt": item["mappingEvidence"]["observedAt"],
    }
    assert item["mappingStability"] == {"confirmed": 0, "required": 2, "ready": False}
    assert item["needsAttention"] is True
    assert item["riskSummary"] == "mapping observation: ambiguous"


def test_overview_audit_key_only_summaries_excluding_sensitive_unknown_keys(
    test_db: DatabaseManager, service: ProjectStatusAnalyticsService
) -> None:
    with test_db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO project_status_update_audit (
                deliverable_id, trigger_type, source_type, external_version,
                proposed_changes_json, applied_changes_json, skipped_fields_json,
                result, error_summary, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "VPI-T2-D5",
                "sync_now",
                "tdc",
                "v100",
                json.dumps({
                    "owner": "Alice Secret",
                    "plannedDate": "2026-09-01",
                    "credentialRef": "cred-999",
                    "internalSecret": "sensitive_password",
                    "unknownField": "bad_data",
                }),
                json.dumps({
                    "owner": "Alice Secret",
                    "status": "已完成",
                    "auth_token": "token_value",
                }),
                json.dumps({
                    "plannedDate": "manually locked",
                    "note": "rejected by policy",
                    "leakSecret": "should_not_appear",
                }),
                "applied",
                None,
                "2026-08-22T10:00:00.000Z",
            ),
        )

    data = service.overview()
    item = next(d for d in data["deliverables"] if d["deliverableId"] == "VPI-T2-D5")

    assert item["confirmedDifference"] == "applied"
    diff = item["confirmedFieldDifferences"]
    assert diff is not None
    assert diff["proposedFields"] == ["owner", "plannedDate"]
    assert diff["appliedFields"] == ["owner", "status"]
    assert diff["skippedFields"] == ["note", "plannedDate"]
    assert diff["result"] == "applied"
    assert diff["observedAt"] == "2026-08-22T10:00:00.000Z"

    serialized = json.dumps(diff)
    for forbidden in [
        "Alice Secret",
        "2026-09-01",
        "credentialRef",
        "internalSecret",
        "sensitive_password",
        "unknownField",
        "bad_data",
        "已完成",
        "auth_token",
        "token_value",
        "manually locked",
        "rejected by policy",
        "leakSecret",
        "should_not_appear",
    ]:
        assert forbidden not in serialized


def test_overview_freshness_stale_fresh_and_unknown(
    test_db: DatabaseManager, service: ProjectStatusAnalyticsService
) -> None:
    now = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)
    fresh_time = (now - timedelta(hours=2)).isoformat()
    stale_time = (now - timedelta(hours=25)).isoformat()

    with test_db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET last_success_at = ? WHERE deliverable_id = ?",
            (fresh_time, "VPI-T2-D2"),
        )
        conn.execute(
            "UPDATE project_status_update_bindings SET last_success_at = ? WHERE deliverable_id = ?",
            (stale_time, "VPI-T2-D3"),
        )
        conn.execute(
            "UPDATE project_status_update_bindings SET last_success_at = NULL WHERE deliverable_id = ?",
            ("VPI-T2-D5",),
        )

    data = service.overview(now=now)
    items = {d["deliverableId"]: d for d in data["deliverables"]}

    assert items["VPI-T2-D2"]["freshness"] == "fresh"
    assert items["VPI-T2-D3"]["freshness"] == "stale"
    assert items["VPI-T2-D5"]["freshness"] == "unknown"


def test_overview_saved_error_redaction_and_precedence_over_mapping_state(
    test_db: DatabaseManager, service: ProjectStatusAnalyticsService
) -> None:
    test_db.record_mapping_observation(
        deliverable_id="VPI-T2-D5",
        source_type="tdc",
        result_state="not_found",
        external_key="FLOW-999",
        candidate_fingerprint="fp-none",
        candidate_count=0,
        candidate_summary_json=json.dumps([]),
        field_report_json=json.dumps({}),
    )

    sensitive_error = "Failed to authenticate with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9 token=sec123"
    with test_db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET last_error_message = ? WHERE deliverable_id = ?",
            (sensitive_error, "VPI-T2-D5"),
        )

    data = service.overview()
    item = next(d for d in data["deliverables"] if d["deliverableId"] == "VPI-T2-D5")

    assert item["riskSummary"] is not None
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in item["riskSummary"]
    assert "sec123" not in item["riskSummary"]
    assert "[redacted]" in item["riskSummary"]

    with test_db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET last_error_message = NULL WHERE deliverable_id = ?",
            ("VPI-T2-D5",),
        )

    data2 = service.overview()
    item2 = next(d for d in data2["deliverables"] if d["deliverableId"] == "VPI-T2-D5")
    assert item2["riskSummary"] == "mapping observation: not_found"


def test_overview_needs_attention_logic(
    test_db: DatabaseManager, service: ProjectStatusAnalyticsService
) -> None:
    with test_db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET sync_state = 'needs_attention' WHERE deliverable_id = ?",
            ("VPI-T2-D2",),
        )

    test_db.record_mapping_observation(
        deliverable_id="VPI-T2-D2",
        source_type="tdc",
        result_state="matched",
        external_key="SOR-001",
        candidate_fingerprint="fp1",
        candidate_count=1,
        candidate_summary_json=json.dumps([]),
        field_report_json=json.dumps({}),
    )

    test_db.record_mapping_observation(
        deliverable_id="VPI-T2-D3",
        source_type="aras",
        result_state="key_changed",
        external_key="EWO-200",
        candidate_fingerprint="fp2",
        candidate_count=1,
        candidate_summary_json=json.dumps([]),
        field_report_json=json.dumps({}),
    )

    test_db.record_mapping_observation(
        deliverable_id="VPI-T2-D5",
        source_type="tdc",
        result_state="matched",
        external_key="FLOW-100",
        candidate_fingerprint="fp3",
        candidate_count=1,
        candidate_summary_json=json.dumps([]),
        field_report_json=json.dumps({}),
    )

    data = service.overview()
    items = {d["deliverableId"]: d for d in data["deliverables"]}

    assert items["VPI-T2-D2"]["needsAttention"] is True
    assert items["VPI-T2-D3"]["needsAttention"] is True
    assert items["VPI-T2-D5"]["needsAttention"] is False
    assert items["VPI-T2-D1"]["needsAttention"] is False


def test_runs_redaction_and_filtering(
    test_db: DatabaseManager, service: ProjectStatusAnalyticsService
) -> None:
    with test_db.get_connection() as conn:
        binding = conn.execute(
            "SELECT id FROM project_status_update_bindings WHERE deliverable_id = 'VPI-T2-D5'"
        ).fetchone()
        assert binding is not None
        binding_id = binding["id"]

        conn.execute(
            """
            INSERT INTO project_status_sync_runs (
                binding_id, deliverable_id, trigger_type, run_state,
                attempt, external_version, result_summary, error_type,
                error_message, created_at, started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                binding_id,
                "VPI-T2-D5",
                "sync_now",
                "failed",
                1,
                "v1",
                "Summary with token=sensitive_jwt_token_12345",
                "AuthError",
                "Auth failed for password=secret_password_value",
                "2026-08-22T10:00:00.000Z",
                "2026-08-22T10:00:01.000Z",
                "2026-08-22T10:00:02.000Z",
            ),
        )

    all_runs = service.runs()
    assert all_runs["total"] >= 1
    target_run = next(r for r in all_runs["runs"] if r["deliverable_id"] == "VPI-T2-D5")

    assert "sensitive_jwt_token_12345" not in target_run["result_summary"]
    assert "secret_password_value" not in target_run["error_message"]
    assert "password=[redacted]" in target_run["error_message"]

    filtered_runs = service.runs(deliverable_id="VPI-T2-D5")
    assert all(r["deliverable_id"] == "VPI-T2-D5" for r in filtered_runs["runs"])

    empty_runs = service.runs(deliverable_id="NON-EXISTENT")
    assert empty_runs["total"] == 0
    assert empty_runs["runs"] == []
