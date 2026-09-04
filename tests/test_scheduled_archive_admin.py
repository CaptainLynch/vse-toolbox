# -*- coding: utf-8 -*-
"""Focused offline tests for ScheduledArchiveAdminService contracts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.archive_store import ArchiveSafetyError
from core.db_manager import (
    ARCHIVE_CREDENTIAL_UNCHANGED,
    ARCHIVE_JOB_CONTRACTS,
    ArchiveJobNotReadyError,
    ArchiveLeaseBusyError,
    DatabaseManager,
)
from services.scheduled_archive_admin import (
    ArchiveAdminValidationError,
    ScheduledArchiveAdminService,
)
from services.scheduled_archive_connectors import archive_filter_names
from services.scheduled_archive_runner import (
    ArchiveJobRunResult,
    ArchiveRunOnceResult,
    ArchiveSyncRunner,
)


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseManager:
    """Provide an isolated temporary SQLite database initialized with schema v3."""
    manager = DatabaseManager(db_path=tmp_path / "admin_service_test.db")
    manager.init_database()
    return manager


@pytest.fixture()
def fake_runner() -> MagicMock:
    """Provide a mock runner that returns a canned ArchiveRunOnceResult without I/O."""
    runner = MagicMock(spec=ArchiveSyncRunner)
    runner.run_once.return_value = ArchiveRunOnceResult(
        results=(
            ArchiveJobRunResult(
                job_id=1,
                job_key="aras_ewo",
                outcome="completed",
                run_id=101,
                final_state="success",
            ),
        ),
        dry_run=False,
    )
    return runner


@pytest.fixture()
def service(db: DatabaseManager, fake_runner: MagicMock) -> ScheduledArchiveAdminService:
    """Provide ScheduledArchiveAdminService bound to test db and fake runner."""
    return ScheduledArchiveAdminService(
        db=db,
        runner_factory=lambda _db: fake_runner,
        clock=lambda: datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc),
    )


# ── 1. list_jobs Contract & Freshness ─────────────────────────────────────────


def test_list_jobs_returns_exactly_six_fixed_jobs(service: ScheduledArchiveAdminService) -> None:
    """list_jobs returns exactly six predefined jobs with expected keys, fixed interval, and parsed contracts."""
    jobs = service.list_jobs()
    assert len(jobs) == 6
    job_keys = [j["jobKey"] for j in jobs]
    assert set(job_keys) == set(ARCHIVE_JOB_CONTRACTS)

    for job in jobs:
        key = str(job["jobKey"])
        assert job["intervalMinutes"] == 60
        assert isinstance(job["enabled"], bool)
        assert isinstance(job["credentialConfigured"], bool)
        assert "credential_ref" not in job
        assert "credentialRef" not in job
        assert "lease_token" not in job
        assert "leaseToken" not in job
        expected_filters = {
            "aras_ewo": {"responsibleDepartment": "技术中心_车体工程"},
            "aras_paa": {"department": "技术中心_车体工程"},
        }.get(key, {})
        assert job["filters"] == expected_filters
        assert job["retryPolicy"] == {"max_attempts": 2, "backoff_seconds": 1}
        assert job["allowedFilterNames"] == list(archive_filter_names(key))
        assert job["freshness"] in {"unknown", "fresh", "stale"}


@pytest.mark.parametrize(
    ("last_success_offset", "expected_freshness"),
    [
        (None, "unknown"),
        (timedelta(hours=0), "fresh"),
        (timedelta(hours=12), "fresh"),
        (timedelta(hours=24), "fresh"),
        (timedelta(hours=24, seconds=1), "stale"),
        (timedelta(days=2), "stale"),
    ],
)
def test_job_freshness_boundary(
    db: DatabaseManager,
    last_success_offset: timedelta | None,
    expected_freshness: str,
) -> None:
    """Freshness reports unknown/fresh/stale evaluated against the 24-hour boundary."""
    fixed_now = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)
    service = ScheduledArchiveAdminService(
        db=db,
        runner_factory=lambda _db: MagicMock(),
        clock=lambda: fixed_now,
    )

    if last_success_offset is not None:
        last_success = (fixed_now - last_success_offset).isoformat()
        with db.get_connection() as conn:
            conn.execute(
                "UPDATE scheduled_archive_jobs SET last_success_at = ? WHERE job_key = 'aras_ewo'",
                (last_success,),
            )

    jobs = {j["jobKey"]: j for j in service.list_jobs()}
    assert jobs["aras_ewo"]["freshness"] == expected_freshness


def test_job_freshness_naive_clock_handling(db: DatabaseManager) -> None:
    """Naive datetime returned by clock is safely handled as UTC."""
    fixed_now_naive = datetime(2026, 8, 22, 12, 0, 0)
    service = ScheduledArchiveAdminService(
        db=db,
        runner_factory=lambda _db: MagicMock(),
        clock=lambda: fixed_now_naive,
    )
    last_success = (fixed_now_naive - timedelta(hours=2)).replace(tzinfo=timezone.utc).isoformat()
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE scheduled_archive_jobs SET last_success_at = ? WHERE job_key = 'aras_ewo'",
            (last_success,),
        )
    jobs = {j["jobKey"]: j for j in service.list_jobs()}
    assert jobs["aras_ewo"]["freshness"] == "fresh"


def test_update_job_accepts_task_retry_policy_override(service: ScheduledArchiveAdminService) -> None:
    """A task can choose one or two total attempts without changing the default contract."""
    job = next(item for item in service.list_jobs() if item["jobKey"] == "aras_ewo")
    updated = service.update_job(
        "aras_ewo",
        {
            "enabled": False,
            "filters": {},
            "outputSubdir": "",
            "intervalMinutes": 60,
            "retryPolicy": {"max_attempts": 1},
            "updatedAt": job["updatedAt"],
        },
    )
    assert updated["retryPolicy"] == {"max_attempts": 1, "backoff_seconds": 1}


def test_update_job_checks_production_credential_availability_before_enable(
    db: DatabaseManager,
) -> None:
    """An enabled production task cannot be marked ready with an unavailable vault reference."""
    provider = MagicMock()
    provider.is_available.return_value = False
    service = ScheduledArchiveAdminService(db, credential_provider=provider)
    job = next(item for item in service.list_jobs() if item["jobKey"] == "aras_ewo")
    with pytest.raises(ArchiveAdminValidationError) as exc_info:
        service.update_job(
            "aras_ewo",
            {
                "enabled": True,
                "credentialRef": "domain",
                "filters": {},
                "outputSubdir": "",
                "intervalMinutes": 60,
                "updatedAt": job["updatedAt"],
            },
        )
    assert "credentialRef" in exc_info.value.fields
    provider.is_available.assert_called_once_with("domain")


# ── 2. update_job Validation & Opaque Alias Handling ──────────────────────────


def test_update_job_rejects_unknown_job_key(service: ScheduledArchiveAdminService) -> None:
    """Updating a non-existent job key raises KeyError."""
    with pytest.raises(KeyError):
        service.update_job("unknown_job_key", {})


def test_update_job_rejects_non_mapping_payload(service: ScheduledArchiveAdminService) -> None:
    """Updating with non-mapping payload raises ArchiveAdminValidationError."""
    with pytest.raises(ArchiveAdminValidationError) as exc_info:
        service.update_job("aras_ewo", "invalid_string_payload")  # type: ignore[arg-type]
    assert exc_info.value.fields == {"request": "JSON object body is required"}


def test_update_job_rejects_unknown_top_level_fields(service: ScheduledArchiveAdminService) -> None:
    """Updating with extraneous fields raises ArchiveAdminValidationError."""
    payload = {
        "enabled": True,
        "filters": {},
        "outputSubdir": "",
        "updatedAt": "2026-08-22T00:00:00.000000Z",
        "unsupportedExtra": 123,
    }
    with pytest.raises(ArchiveAdminValidationError) as exc_info:
        service.update_job("aras_ewo", payload)
    assert exc_info.value.fields == {"request": "contains unsupported fields"}


@pytest.mark.parametrize(
    ("bad_field_payload", "expected_error_key", "expected_error_msg"),
    [
        # Missing required fields
        (
            {"filters": {}, "outputSubdir": "", "updatedAt": "2026-08-22T00:00:00Z"},
            "enabled",
            "must be a boolean",
        ),
        (
            {"enabled": True, "outputSubdir": "", "updatedAt": "2026-08-22T00:00:00Z"},
            "filters",
            "must be an object",
        ),
        (
            {"enabled": True, "filters": {}, "updatedAt": "2026-08-22T00:00:00Z"},
            "outputSubdir",
            "must be a string",
        ),
        (
            {"enabled": True, "filters": {}, "outputSubdir": ""},
            "updatedAt",
            "is required",
        ),
        # Malformed required fields
        (
            {"enabled": "yes", "filters": {}, "outputSubdir": "", "updatedAt": "2026-08-22T00:00:00Z"},
            "enabled",
            "must be a boolean",
        ),
        (
            {"enabled": 1, "filters": {}, "outputSubdir": "", "updatedAt": "2026-08-22T00:00:00Z"},
            "enabled",
            "must be a boolean",
        ),
        (
            {"enabled": None, "filters": {}, "outputSubdir": "", "updatedAt": "2026-08-22T00:00:00Z"},
            "enabled",
            "must be a boolean",
        ),
        (
            {
                "enabled": False,
                "filters": ["not_dict"],
                "outputSubdir": "",
                "updatedAt": "2026-08-22T00:00:00Z",
            },
            "filters",
            "must be an object",
        ),
        (
            {"enabled": False, "filters": "string_not_dict", "outputSubdir": "", "updatedAt": "2026-08-22T00:00:00Z"},
            "filters",
            "must be an object",
        ),
        (
            {"enabled": False, "filters": {}, "outputSubdir": 123, "updatedAt": "2026-08-22T00:00:00Z"},
            "outputSubdir",
            "must be a string",
        ),
        (
            {"enabled": False, "filters": {}, "outputSubdir": None, "updatedAt": "2026-08-22T00:00:00Z"},
            "outputSubdir",
            "must be a string",
        ),
        (
            {"enabled": False, "filters": {}, "outputSubdir": "", "updatedAt": ""},
            "updatedAt",
            "is required",
        ),
        (
            {"enabled": False, "filters": {}, "outputSubdir": "", "updatedAt": "   "},
            "updatedAt",
            "is required",
        ),
        (
            {"enabled": False, "filters": {}, "outputSubdir": "", "updatedAt": None},
            "updatedAt",
            "is required",
        ),
        (
            {
                "enabled": False,
                "filters": {},
                "outputSubdir": "",
                "updatedAt": "2026-08-22T00:00:00Z",
                "credentialRef": 12345,
            },
            "credentialRef",
            "must be a string or null",
        ),
        (
            {
                "enabled": False,
                "filters": {},
                "outputSubdir": "",
                "updatedAt": "2026-08-22T00:00:00Z",
                "credentialRef": ["alias_in_list"],
            },
            "credentialRef",
            "must be a string or null",
        ),
    ],
)
def test_update_job_rejects_malformed_and_missing_required_fields(
    service: ScheduledArchiveAdminService,
    bad_field_payload: dict[str, Any],
    expected_error_key: str,
    expected_error_msg: str,
) -> None:
    """Type, presence, and omission checks catch missing or malformed top-level update fields."""
    with pytest.raises(ArchiveAdminValidationError) as exc_info:
        service.update_job("aras_ewo", bad_field_payload)
    assert exc_info.value.fields.get(expected_error_key) == expected_error_msg


@pytest.mark.parametrize(
    ("job_key", "invalid_filters"),
    [
        ("aras_ewo", {"unsupportedField": "value"}),
        ("tdc_data_model", {"ewoNo": "EWO123"}),
        ("aras_ewo", {"changeType": 123}),
        ("aras_ewo", {"changeType": "val" + chr(0) + "null"}),
        ("aras_ewo", {"changeType": "val" + chr(31) + "ctrl"}),
        ("aras_ewo", {"changeType": "a" * 513}),
        ("aras_ncr_progress", {"projectNames": "not_a_list"}),
        ("aras_ncr_progress", {"projectNames": ["valid", 123]}),
        ("aras_ncr_progress", {"projectNames": ["valid", "bad" + chr(0) + "null"]}),
        ("aras_ncr_progress", {"projectNames": ["valid", "bad" + chr(31) + "ctrl"]}),
        ("aras_ncr_progress", {"projectNames": ["valid", "a" * 513]}),
        ("aras_ncr_progress", {"projectNames": [f"p{i}" for i in range(101)]}),
    ],
)
def test_update_job_rejects_invalid_filter_shapes(
    service: ScheduledArchiveAdminService,
    job_key: str,
    invalid_filters: dict[str, Any],
) -> None:
    """Job-specific filter rules reject unsupported keys, bad scalar/list shapes, and control chars."""
    jobs = {j["jobKey"]: j for j in service.list_jobs()}
    payload = {
        "enabled": False,
        "filters": invalid_filters,
        "outputSubdir": "",
        "updatedAt": jobs[job_key]["updatedAt"],
    }
    with pytest.raises(ArchiveAdminValidationError) as exc_info:
        service.update_job(job_key, payload)
    assert "filters" in exc_info.value.fields


def test_update_job_passes_opaque_alias_and_updates_config(
    service: ScheduledArchiveAdminService,
    db: DatabaseManager,
) -> None:
    """Successful update configures alias, filters, outputSubdir and passes alias only to DatabaseManager."""
    job_key = "aras_ewo"
    initial_jobs = {j["jobKey"]: j for j in service.list_jobs()}
    initial_job = initial_jobs[job_key]
    alias = "fake_mock_alias_001"

    spy_db_update = MagicMock(wraps=db.update_archive_job_config)
    db.update_archive_job_config = spy_db_update  # type: ignore[assignment]

    updated = service.update_job(
        job_key,
        {
            "enabled": True,
            "credentialRef": alias,
            "filters": {"changeType": "ECR"},
            "outputSubdir": "aras/ewo",
            "updatedAt": initial_job["updatedAt"],
        },
    )

    spy_db_update.assert_called_once_with(
        job_key,
        enabled=True,
        credential_ref=alias,
        filters={"changeType": "ECR"},
        output_subdir="aras/ewo",
        expected_updated_at=initial_job["updatedAt"],
        actor="local_web",
        interval_minutes=60,
    )

    assert updated["enabled"] is True
    assert updated["credentialConfigured"] is True
    assert "credential_ref" not in updated
    assert "credentialRef" not in updated
    assert updated["outputSubdir"] == "aras/ewo"
    assert updated["filters"] == {"changeType": "ECR"}
    assert updated["updatedAt"] != initial_job["updatedAt"]

    # Update again omitting credentialRef: passes ARCHIVE_CREDENTIAL_UNCHANGED and preserves alias
    spy_db_update.reset_mock()
    second_updated = service.update_job(
        job_key,
        {
            "enabled": True,
            "filters": {"changeType": "ECO"},
            "outputSubdir": "aras/ewo",
            "updatedAt": updated["updatedAt"],
        },
    )
    spy_db_update.assert_called_once_with(
        job_key,
        enabled=True,
        credential_ref=ARCHIVE_CREDENTIAL_UNCHANGED,
        filters={"changeType": "ECO"},
        output_subdir="aras/ewo",
        expected_updated_at=updated["updatedAt"],
        actor="local_web",
        interval_minutes=60,
    )
    assert second_updated["credentialConfigured"] is True
    assert second_updated["filters"] == {"changeType": "ECO"}


def test_update_job_propagates_db_domain_exceptions(
    service: ScheduledArchiveAdminService,
    db: DatabaseManager,
) -> None:
    """update_job lets db domain exceptions (not ready, lease busy, stale lock, safety) bubble up."""
    job_key = "tdc_sor"
    jobs = {j["jobKey"]: j for j in service.list_jobs()}
    current_job = jobs[job_key]

    # 1. Enabling unconfigured job without credentialRef -> ArchiveJobNotReadyError
    with pytest.raises(ArchiveJobNotReadyError):
        service.update_job(
            job_key,
            {
                "enabled": True,
                "filters": {},
                "outputSubdir": "",
                "updatedAt": current_job["updatedAt"],
            },
        )

    # 2. Stale updatedAt -> RuntimeError
    with pytest.raises(RuntimeError, match="has changed"):
        service.update_job(
            job_key,
            {
                "enabled": False,
                "filters": {},
                "outputSubdir": "",
                "updatedAt": "2020-01-01T00:00:00.000000Z",
            },
        )

    # 3. Unsafe outputSubdir path traversal -> ArchiveSafetyError
    with pytest.raises(ArchiveSafetyError):
        service.update_job(
            job_key,
            {
                "enabled": False,
                "filters": {},
                "outputSubdir": "../escaped_path",
                "updatedAt": current_job["updatedAt"],
            },
        )


def test_update_job_during_active_lease_raises_lease_busy(
    service: ScheduledArchiveAdminService,
    db: DatabaseManager,
) -> None:
    """Updating a job during active lease raises ArchiveLeaseBusyError."""
    job_key = "aras_ewo"
    initial_job = {j["jobKey"]: j for j in service.list_jobs()}[job_key]
    alias = "mock_lease_alias"
    res = service.update_job(
        job_key,
        {
            "enabled": True,
            "credentialRef": alias,
            "filters": {},
            "outputSubdir": "",
            "updatedAt": initial_job["updatedAt"],
        },
    )
    db.acquire_archive_job_lease(int(res["id"]), "sync_now", lease_seconds=900)
    leased_job = {j["jobKey"]: j for j in service.list_jobs()}[job_key]

    with pytest.raises(ArchiveLeaseBusyError):
        service.update_job(
            job_key,
            {
                "enabled": False,
                "filters": {},
                "outputSubdir": "",
                "updatedAt": leased_job["updatedAt"],
            },
        )


# ── 3. list_runs, list_artifacts, list_audit Serializers & Limits ─────────────


def test_list_runs_serialization_and_privacy(
    service: ScheduledArchiveAdminService,
    db: DatabaseManager,
) -> None:
    """list_runs transforms snake_case db columns to camelCase, forwards limits, and omits sensitive tokens."""
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO scheduled_archive_runs
                (job_id, job_key, trigger_type, run_state, attempt, record_count,
                 result_summary, error_type, error_message, created_at, started_at, finished_at)
            VALUES (1, 'aras_ewo', 'scheduled', 'success', 1, 42,
                    'Fetched 42 records', NULL, NULL,
                    '2026-08-22T10:00:00Z', '2026-08-22T10:00:01Z', '2026-08-22T10:00:05Z')
            """
        )

    spy_list_runs = MagicMock(wraps=db.list_archive_runs)
    db.list_archive_runs = spy_list_runs  # type: ignore[assignment]

    runs = service.list_runs(job_key="aras_ewo", limit=5)
    spy_list_runs.assert_called_once_with("aras_ewo", 5)

    assert len(runs) >= 1
    target = [r for r in runs if r["jobKey"] == "aras_ewo"][0]

    assert target["jobId"] == 1
    assert target["jobKey"] == "aras_ewo"
    assert target["triggerType"] == "scheduled"
    assert target["runState"] == "success"
    assert target["attempt"] == 1
    assert target["recordCount"] == 42
    assert target["resultSummary"] == "Fetched 42 records"
    assert target["createdAt"] == "2026-08-22T10:00:00Z"
    assert target["startedAt"] == "2026-08-22T10:00:01Z"
    assert target["finishedAt"] == "2026-08-22T10:00:05Z"

    assert "lease_token" not in target
    assert "leaseToken" not in target
    assert "credential_ref" not in target
    assert "credentialRef" not in target

    # Unknown job_key raises KeyError
    with pytest.raises(KeyError):
        service.list_runs(job_key="unknown_job_key")


def test_list_artifacts_serialization_and_relative_paths_only(
    service: ScheduledArchiveAdminService,
    db: DatabaseManager,
) -> None:
    """list_artifacts exposes relativePath only, never server absolute paths."""
    with db.get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO scheduled_archive_runs
                (job_id, job_key, trigger_type, run_state, attempt, created_at)
            VALUES (1, 'aras_ewo', 'scheduled', 'success', 1, '2026-08-22T10:00:00Z')
            """
        )
        run_id = cursor.lastrowid
        conn.execute(
            """
            INSERT INTO scheduled_archive_artifacts
                (run_id, artifact_type, relative_path, display_name, size_bytes, sha256, created_at)
            VALUES (?, 'normalized_csv', 'aras/ewo/20260822/ewo.csv', 'ewo.csv', 1024, 'abc123sha',
                    '2026-08-22T10:00:05Z')
            """,
            (run_id,),
        )

    artifacts = service.list_artifacts(run_id)
    assert len(artifacts) == 1
    item = artifacts[0]

    assert item["runId"] == run_id
    assert item["artifactType"] == "normalized_csv"
    assert item["relativePath"] == "aras/ewo/20260822/ewo.csv"
    assert item["displayName"] == "ewo.csv"
    assert item["sizeBytes"] == 1024
    assert item["sha256"] == "abc123sha"

    assert "absolute_path" not in item
    assert "absolutePath" not in item
    assert "server_root" not in item


def test_list_audit_serialization_and_parsed_changes(
    service: ScheduledArchiveAdminService,
    db: DatabaseManager,
) -> None:
    """list_audit parses changes_json into changes dict, forwards limits, and maps camelCase fields."""
    job_key = "aras_ewo"
    jobs = {j["jobKey"]: j for j in service.list_jobs()}
    service.update_job(
        job_key,
        {
            "enabled": False,
            "filters": {"state": "Released"},
            "outputSubdir": "aras/ewo",
            "updatedAt": jobs[job_key]["updatedAt"],
        },
    )

    spy_list_audit = MagicMock(wraps=db.list_archive_config_audit)
    db.list_archive_config_audit = spy_list_audit  # type: ignore[assignment]

    audit_records = service.list_audit(job_key=job_key, limit=7)
    spy_list_audit.assert_called_once_with(job_key, 7)

    assert len(audit_records) >= 1
    record = audit_records[0]

    assert record["jobKey"] == job_key
    assert record["actor"] == "local_web"
    assert record["eventType"] == "configuration_updated"
    assert isinstance(record["changes"], dict)
    assert "fields" in record["changes"]
    assert "credentialConfigured" in record["changes"]

    assert "credential_ref" not in record
    assert "credentialRef" not in record

    # Unknown job_key raises KeyError
    with pytest.raises(KeyError):
        service.list_audit(job_key="unknown_job_key")


# ── 4. sync_now Contract ──────────────────────────────────────────────────────


def test_sync_now_triggers_runner_and_serializes_result(
    service: ScheduledArchiveAdminService,
    fake_runner: MagicMock,
) -> None:
    """sync_now triggers runner with trigger_type sync_now and serializes RunOnceResult."""
    result = service.sync_now("aras_ewo")

    fake_runner.run_once.assert_called_once_with(
        trigger_type="sync_now",
        job_key="aras_ewo",
    )
    assert result["dryRun"] is False
    assert result["exitCode"] == 0
    assert len(result["results"]) == 1
    first = result["results"][0]
    assert first["jobKey"] == "aras_ewo"
    assert first["outcome"] == "completed"
    assert first["runId"] == 101
    assert first["finalState"] == "success"


def test_sync_now_rejects_unknown_job_key(service: ScheduledArchiveAdminService) -> None:
    """sync_now with non-existent job key raises KeyError."""
    with pytest.raises(KeyError):
        service.sync_now("unknown_job_key")
