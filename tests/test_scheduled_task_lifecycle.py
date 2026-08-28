# -*- coding: utf-8 -*-
"""Focused tests for scheduled archive task lifecycle: template creation, copy, configuration, soft-archive, and history retention."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import web.app as web_app
from core.archive_store import ArchiveSafetyError
from core.db_manager import (
    ARCHIVE_JOB_CONTRACTS,
    DatabaseManager,
)
from services.scheduled_archive_admin import (
    ArchiveAdminValidationError,
    ScheduledArchiveAdminService,
)
from services.scheduled_archive_runner import (
    ArchiveJobRunResult,
    ArchiveRunOnceResult,
    ArchiveSyncRunner,
)


def _runtime_opaque() -> str:
    return f"opq-{uuid.uuid4().hex}"


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseManager:
    """Isolated temporary SQLite database with initialized schema."""
    manager = DatabaseManager(db_path=tmp_path / "scheduled_lifecycle_test.db")
    manager.init_database()
    return manager


@pytest.fixture()
def fake_runner() -> MagicMock:
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
    return ScheduledArchiveAdminService(
        db=db,
        runner_factory=lambda _db: fake_runner,
        clock=lambda: datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc),
    )


# ── 1. Approved Template Creation and Arbitrary Template Rejection ────────────


@pytest.mark.parametrize("template_key", list(ARCHIVE_JOB_CONTRACTS.keys()))
def test_create_task_from_approved_template(service: ScheduledArchiveAdminService, template_key: str) -> None:
    """Tasks created from approved templates initialize as non-builtin, disabled, with expected contracts."""
    display_name = f"Fictional Task for {template_key}"
    created = service.create_job({"templateKey": template_key, "displayName": display_name})

    assert created["builtin"] is False
    assert created["templateKey"] == template_key
    assert created["displayName"] == display_name
    assert created["jobKey"].startswith(f"{template_key}_")
    assert created["enabled"] is False
    assert created["intervalMinutes"] == 60
    assert created["archivedAt"] is None
    assert created["syncState"] == "idle"


def test_create_task_rejects_arbitrary_unapproved_templates(
    service: ScheduledArchiveAdminService,
    db: DatabaseManager,
) -> None:
    """Arbitrary template keys outside ARCHIVE_JOB_CONTRACTS are strictly rejected."""
    arbitrary_keys = ("unapproved_custom_report", "arbitrary_script", "unknown_source_report")

    for bad_key in arbitrary_keys:
        with pytest.raises(ArchiveAdminValidationError) as exc_info:
            service.create_job({"templateKey": bad_key, "displayName": "Invalid Task"})
        assert "templateKey" in exc_info.value.fields
        assert "approved templates" in exc_info.value.fields["templateKey"]

        # Direct DB layer also rejects unapproved template key
        with pytest.raises(KeyError):
            db.create_archive_job_from_template(bad_key, display_name="Direct DB Fail")


def test_create_task_requires_non_empty_display_name(service: ScheduledArchiveAdminService) -> None:
    """Missing or whitespace-only display name raises validation error."""
    for invalid_name in ("", "   ", None):
        with pytest.raises(ArchiveAdminValidationError) as exc_info:
            service.create_job({"templateKey": "aras_ewo", "displayName": invalid_name})
        assert "displayName" in exc_info.value.fields


# ── 2. Task Copy Contract ──────────────────────────────────────────────────────


def test_create_task_copies_configuration_from_source_job(service: ScheduledArchiveAdminService) -> None:
    """Creating a task with copyFromJobKey copies interval, filters, and outputSubdir from source."""
    # First customize source job with valid PAA filter
    source_job = next(j for j in service.list_jobs() if j["jobKey"] == "aras_paa")
    updated_source = service.update_job(
        "aras_paa",
        {
            "enabled": False,
            "intervalMinutes": 120,
            "filters": {"paaNo": "PAA-2026-FICTIONAL-001"},
            "outputSubdir": "fictional_paa_folder",
            "updatedAt": source_job["updatedAt"],
        },
    )
    assert updated_source["intervalMinutes"] == 120
    assert updated_source["filters"] == {"paaNo": "PAA-2026-FICTIONAL-001"}
    assert updated_source["outputSubdir"] == "fictional_paa_folder"

    # Create new task copying from source
    copied = service.create_job(
        {
            "templateKey": "aras_paa",
            "displayName": "Fictional Copied PAA Task",
            "copyFromJobKey": "aras_paa",
        }
    )
    assert copied["builtin"] is False
    assert copied["templateKey"] == "aras_paa"
    assert copied["displayName"] == "Fictional Copied PAA Task"
    assert copied["intervalMinutes"] == 120
    assert copied["filters"] == {"paaNo": "PAA-2026-FICTIONAL-001"}
    assert copied["outputSubdir"] == "fictional_paa_folder"


def test_create_task_rejects_copy_with_mismatched_template(service: ScheduledArchiveAdminService) -> None:
    """Copying from a source job with a different templateKey raises KeyError."""
    with pytest.raises(KeyError):
        service.create_job(
            {
                "templateKey": "aras_ewo",  # mismatched with aras_paa
                "displayName": "Mismatched Copy",
                "copyFromJobKey": "aras_paa",
            }
        )


# ── 3. Editable Interval, Filters, Output Folder, and Validation ───────────────


def test_update_job_interval_filters_and_folder_success(service: ScheduledArchiveAdminService) -> None:
    """Updating a task's interval, allowed filters, and outputSubdir succeeds and audits change."""
    job = next(j for j in service.list_jobs() if j["jobKey"] == "aras_ewo")

    updated = service.update_job(
        "aras_ewo",
        {
            "enabled": False,
            "intervalMinutes": 180,
            "filters": {"projectCode": "FICTIONAL_PROJ_X"},
            "outputSubdir": "fictional_ewo_output",
            "updatedAt": job["updatedAt"],
        },
    )
    assert updated["intervalMinutes"] == 180
    assert updated["filters"] == {"projectCode": "FICTIONAL_PROJ_X"}
    assert updated["outputSubdir"] == "fictional_ewo_output"

    # Verify audit record
    audit_entries = service.list_audit(job_key="aras_ewo")
    assert len(audit_entries) >= 1
    latest_audit = audit_entries[0]
    assert "intervalMinutes" in latest_audit["changes"]["fields"]
    assert "filters" in latest_audit["changes"]["fields"]
    assert "outputSubdir" in latest_audit["changes"]["fields"]


def test_update_job_accepts_absolute_output_directory_and_can_reset_to_default(
    service: ScheduledArchiveAdminService,
    tmp_path: Path,
) -> None:
    """A task may override the global archive root and an empty value restores the default."""
    job = next(j for j in service.list_jobs() if j["jobKey"] == "aras_ewo")
    selected = tmp_path / "chosen-archive"
    selected.mkdir()

    updated = service.update_job(
        "aras_ewo",
        {
            "enabled": False,
            "filters": {},
            "outputSubdir": "",
            "outputDirectory": str(selected),
            "updatedAt": job["updatedAt"],
        },
    )

    assert Path(str(updated["outputDirectory"])).resolve() == selected.resolve()
    assert updated["outputSubdir"] == ""
    assert "outputDirectory" in service.list_audit("aras_ewo")[0]["changes"]["fields"]

    reset_job = service.update_job(
        "aras_ewo",
        {
            "enabled": False,
            "filters": {},
            "outputSubdir": "",
            "outputDirectory": "",
            "updatedAt": updated["updatedAt"],
        },
    )
    assert reset_job["outputDirectory"] == ""


def test_update_job_rejects_absolute_directory_with_legacy_subdir(
    service: ScheduledArchiveAdminService,
    tmp_path: Path,
) -> None:
    """An explicit directory and legacy relative subdirectory cannot be ambiguous."""
    job = next(j for j in service.list_jobs() if j["jobKey"] == "aras_ewo")
    selected = tmp_path / "chosen-archive"
    selected.mkdir()

    with pytest.raises(ArchiveAdminValidationError) as exc_info:
        service.update_job(
            "aras_ewo",
            {
                "enabled": False,
                "filters": {},
                "outputSubdir": "legacy",
                "outputDirectory": str(selected),
                "updatedAt": job["updatedAt"],
            },
        )
    assert "outputSubdir" in exc_info.value.fields


@pytest.mark.parametrize("invalid_interval", [4, 10081, "120", True, False, -1])
def test_update_job_rejects_invalid_interval(service: ScheduledArchiveAdminService, invalid_interval: Any) -> None:
    """Interval outside [5, 10080] or non-integer is rejected."""
    job = next(j for j in service.list_jobs() if j["jobKey"] == "aras_ewo")
    with pytest.raises(ArchiveAdminValidationError) as exc_info:
        service.update_job(
            "aras_ewo",
            {
                "enabled": False,
                "intervalMinutes": invalid_interval,
                "filters": {},
                "outputSubdir": "",
                "updatedAt": job["updatedAt"],
            },
        )
    assert "intervalMinutes" in exc_info.value.fields


def test_update_job_rejects_unallowed_and_sensitive_filters(service: ScheduledArchiveAdminService) -> None:
    """Unallowed filter names or sensitive names (password, token, etc.) are rejected."""
    job = next(j for j in service.list_jobs() if j["jobKey"] == "aras_ewo")

    for bad_key in (
        "unsupported_filter",
        "password",
        "token",
        "cookie",
        "authorization",
    ):
        with pytest.raises(ArchiveAdminValidationError) as exc_info:
            service.update_job(
                "aras_ewo",
                {
                    "enabled": False,
                    "filters": {bad_key: _runtime_opaque()},
                    "outputSubdir": "",
                    "updatedAt": job["updatedAt"],
                },
            )
        assert "filters" in exc_info.value.fields


def test_update_job_rejects_traversal_output_subdir(service: ScheduledArchiveAdminService) -> None:
    """Traversal segments in outputSubdir are rejected."""
    job = next(j for j in service.list_jobs() if j["jobKey"] == "aras_ewo")
    for bad_subdir in ("../escaped", r"C:\absolute", "sub/../../traversal"):
        with pytest.raises((ArchiveAdminValidationError, ArchiveSafetyError)):
            service.update_job(
                "aras_ewo",
                {
                    "enabled": False,
                    "filters": {},
                    "outputSubdir": bad_subdir,
                    "updatedAt": job["updatedAt"],
                },
            )


def test_update_job_optimistic_concurrency_conflict(service: ScheduledArchiveAdminService) -> None:
    """Providing a stale updatedAt timestamp raises RuntimeError conflict."""
    job = next(j for j in service.list_jobs() if j["jobKey"] == "aras_ewo")

    # Make one successful update
    service.update_job(
        "aras_ewo",
        {
            "enabled": False,
            "intervalMinutes": 90,
            "filters": {},
            "outputSubdir": "",
            "updatedAt": job["updatedAt"],
        },
    )

    # Trying to update again with original stale updatedAt
    with pytest.raises(RuntimeError, match="archive job configuration has changed"):
        service.update_job(
            "aras_ewo",
            {
                "enabled": False,
                "intervalMinutes": 120,
                "filters": {},
                "outputSubdir": "",
                "updatedAt": job["updatedAt"],  # stale
            },
        )


# ── 4. Built-in and Non-Built-in Soft Archive ─────────────────────────────────


def test_builtin_tasks_can_be_deleted_with_history_preserved(
    service: ScheduledArchiveAdminService,
    db: DatabaseManager,
) -> None:
    """Built-in tasks may be soft-archived while their history remains queryable."""
    builtin_job = next(j for j in service.list_jobs() if j["jobKey"] == "aras_ewo")
    assert builtin_job["builtin"] is True

    # Can be updated/disabled
    updated = service.update_job(
        "aras_ewo",
        {
            "enabled": False,
            "filters": {},
            "outputSubdir": "",
            "updatedAt": builtin_job["updatedAt"],
        },
    )
    assert updated["enabled"] is False

    archived = service.archive_job("aras_ewo", updated_at=updated["updatedAt"])
    assert archived["archivedAt"] is not None
    assert archived["enabled"] is False
    assert all(item["jobKey"] != "aras_ewo" for item in service.list_jobs())

    retained = db.list_archive_jobs(include_archived=True)
    retained_row = next(item for item in retained if item["job_key"] == "aras_ewo")
    assert retained_row["archived_at"] is not None


def test_non_builtin_tasks_can_be_soft_archived(
    service: ScheduledArchiveAdminService,
    db: DatabaseManager,
) -> None:
    """Non-builtin tasks can be soft-archived, removing them from active job listings."""
    created = service.create_job({"templateKey": "aras_ewo", "displayName": "Custom Archive Target"})
    custom_key = str(created["jobKey"])

    active_jobs_before = [j["jobKey"] for j in service.list_jobs()]
    assert custom_key in active_jobs_before

    # Soft archive the custom job
    archived = service.archive_job(custom_key, updated_at=created["updatedAt"])
    assert archived["archivedAt"] is not None
    assert archived["enabled"] is False

    # Excluded from default list_jobs()
    active_jobs_after = [j["jobKey"] for j in service.list_jobs()]
    assert custom_key not in active_jobs_after

    # Still present in full DB list when include_archived=True
    all_db_jobs = db.list_archive_jobs(include_archived=True)
    matching = next(j for j in all_db_jobs if j["job_key"] == custom_key)
    assert matching["archived_at"] is not None


# ── 5. Archived History and Audit Retention ───────────────────────────────────


def test_archived_task_retains_execution_and_audit_history(
    service: ScheduledArchiveAdminService,
    db: DatabaseManager,
) -> None:
    """Soft archiving a custom task preserves its run history and configuration audit records."""
    # 1. Create a custom task
    created = service.create_job({"templateKey": "tdc_data_model", "displayName": "Historical Task"})
    custom_key = str(created["jobKey"])
    job_id = int(created["id"])

    # 2. Update config to generate audit records (using valid tdc_data_model filter 'incident')
    updated = service.update_job(
        custom_key,
        {
            "enabled": False,
            "intervalMinutes": 120,
            "filters": {"incident": "INC-2026-FICTIONAL-001"},
            "outputSubdir": "fictional_history_subdir",
            "updatedAt": created["updatedAt"],
        },
    )

    # 3. Simulate run records in database
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO scheduled_archive_runs
                (job_id, job_key, trigger_type, run_state, attempt, record_count, result_summary, created_at, finished_at)
            VALUES (?, ?, 'sync_now', 'success', 1, 42, 'Fictional sync completed', '2026-08-23T10:00:00Z', '2026-08-23T10:05:00Z')
            """,
            (job_id, custom_key),
        )

    runs_before = service.list_runs(job_key=custom_key)
    audit_before = service.list_audit(job_key=custom_key)
    assert len(runs_before) == 1
    assert len(audit_before) >= 1

    # 4. Soft archive the custom job
    service.archive_job(custom_key, updated_at=updated["updatedAt"])

    # 5. Verify history is fully retained
    runs_after = service.list_runs(job_key=custom_key)
    audit_after = service.list_audit(job_key=custom_key)

    assert len(runs_after) == 1
    assert runs_after[0]["recordCount"] == 42
    assert runs_after[0]["runState"] == "success"
    assert runs_after[0]["resultSummary"] == "Fictional sync completed"

    assert len(audit_after) >= 1
    assert audit_after[0]["jobKey"] == custom_key


# ── 6. Web API Integration Tests for Task Lifecycle ────────────────────────────


def _loopback_headers() -> dict[str, str]:
    return {"Host": "localhost:5000", "Origin": "http://localhost:5000", "Sec-Fetch-Site": "same-origin"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, db: DatabaseManager, fake_runner: MagicMock) -> Any:
    monkeypatch.setattr(
        web_app,
        "ScheduledArchiveAdminService",
        lambda _db: ScheduledArchiveAdminService(_db, runner_factory=lambda __db: fake_runner),
    )
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db)
    app = web_app.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_api_task_lifecycle_create_update_archive_flow(client: Any) -> None:
    """Full HTTP API lifecycle test: create, update, soft-archive, and check history retention."""
    # 1. Reject arbitrary template
    bad_create = client.post(
        "/api/scheduled-archive/jobs",
        json={"templateKey": "arbitrary_bad_template", "displayName": "Invalid"},
        headers=_loopback_headers(),
    )
    assert bad_create.status_code == 422

    # 2. Create custom job from approved template
    create_resp = client.post(
        "/api/scheduled-archive/jobs",
        json={"templateKey": "aras_ncr_progress", "displayName": "HTTP Custom Task"},
        headers=_loopback_headers(),
    )
    assert create_resp.status_code == 201
    created_data = create_resp.get_json()["data"]
    job_key = created_data["jobKey"]
    assert created_data["builtin"] is False

    # 3. Update job configuration (using valid aras_ncr_progress filter 'sectionCode')
    update_resp = client.patch(
        f"/api/scheduled-archive/jobs/{job_key}",
        json={
            "enabled": False,
            "intervalMinutes": 150,
            "filters": {"sectionCode": "FICTIONAL_SEC_01"},
            "outputSubdir": "fictional_http_folder",
            "updatedAt": created_data["updatedAt"],
        },
        headers=_loopback_headers(),
    )
    assert update_resp.status_code == 200
    updated_data = update_resp.get_json()["data"]
    assert updated_data["intervalMinutes"] == 150

    # 4. Built-in task deletion is a soft archive and keeps the fixed row/history
    builtin_del = client.delete(
        "/api/scheduled-archive/jobs/aras_ewo",
        json={"updatedAt": "2026-08-23T10:00:00Z"},
        headers=_loopback_headers(),
    )
    assert builtin_del.status_code == 409

    # 5. Soft-archive custom job succeeds
    archive_resp = client.delete(
        f"/api/scheduled-archive/jobs/{job_key}",
        json={"updatedAt": updated_data["updatedAt"]},
        headers=_loopback_headers(),
    )
    assert archive_resp.status_code == 200
    archived_data = archive_resp.get_json()["data"]
    assert archived_data["archivedAt"] is not None

    # 6. Verify custom job is excluded from active GET /api/scheduled-archive/jobs
    jobs_resp = client.get("/api/scheduled-archive/jobs")
    active_keys = [j["jobKey"] for j in jobs_resp.get_json()["data"]]
    assert job_key not in active_keys
