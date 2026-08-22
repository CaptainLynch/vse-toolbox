# -*- coding: utf-8 -*-
"""Framework-independent administration for fixed scheduled archive jobs."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Callable, Mapping

from core.db_manager import (
    ARCHIVE_CREDENTIAL_UNCHANGED,
    ARCHIVE_JOB_CONTRACTS,
    DatabaseManager,
)
from services.scheduled_archive_connectors import (
    archive_filter_names,
    validate_archive_filters,
)
from services.scheduled_archive_runner import (
    ArchiveRunOnceResult,
    ArchiveSyncRunner,
    create_production_archive_runner,
)

_UPDATE_FIELDS = {
    "enabled",
    "credentialRef",
    "filters",
    "outputSubdir",
    "updatedAt",
}


class ArchiveAdminValidationError(ValueError):
    """A bounded validation failure suitable for an HTTP field response."""

    def __init__(self, fields: Mapping[str, str]) -> None:
        super().__init__("archive administration request is invalid")
        self.fields = dict(fields)


def _json_object(value: object) -> dict[str, object]:
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_utc(value: object) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).strip()
        parsed = datetime.fromisoformat(
            text[:-1] + "+00:00" if text.endswith("Z") else text
        )
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


class ScheduledArchiveAdminService:
    """Expose safe configuration, history, and one-shot execution contracts."""

    def __init__(
        self,
        db: DatabaseManager,
        *,
        runner_factory: Callable[[DatabaseManager], ArchiveSyncRunner] = (
            create_production_archive_runner
        ),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._runner_factory = runner_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def list_jobs(self) -> list[dict[str, object]]:
        return [self._job_payload(row) for row in self._db.list_archive_jobs()]

    def update_job(
        self,
        job_key: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        if job_key not in ARCHIVE_JOB_CONTRACTS:
            raise KeyError(job_key)
        if not isinstance(payload, Mapping):
            raise ArchiveAdminValidationError(
                {"request": "JSON object body is required"}
            )
        unknown = set(payload) - _UPDATE_FIELDS
        if unknown:
            raise ArchiveAdminValidationError(
                {"request": "contains unsupported fields"}
            )

        errors: dict[str, str] = {}
        enabled = payload.get("enabled")
        filters = payload.get("filters")
        output_subdir = payload.get("outputSubdir")
        updated_at = payload.get("updatedAt")
        if not isinstance(enabled, bool):
            errors["enabled"] = "must be a boolean"
        if not isinstance(filters, Mapping):
            errors["filters"] = "must be an object"
        if not isinstance(output_subdir, str):
            errors["outputSubdir"] = "must be a string"
        if not isinstance(updated_at, str) or not updated_at.strip():
            errors["updatedAt"] = "is required"
        credential_ref: object = ARCHIVE_CREDENTIAL_UNCHANGED
        if "credentialRef" in payload:
            credential_ref = payload["credentialRef"]
            if credential_ref is not None and not isinstance(
                credential_ref, str
            ):
                errors["credentialRef"] = "must be a string or null"
        if errors:
            raise ArchiveAdminValidationError(errors)

        assert isinstance(enabled, bool)
        assert isinstance(filters, Mapping)
        assert isinstance(output_subdir, str)
        assert isinstance(updated_at, str)
        try:
            checked_filters = validate_archive_filters(job_key, filters)
        except (TypeError, ValueError) as exc:
            raise ArchiveAdminValidationError(
                {"filters": str(exc)}
            ) from exc

        row = self._db.update_archive_job_config(
            job_key,
            enabled=enabled,
            credential_ref=credential_ref,
            filters=checked_filters,
            output_subdir=output_subdir,
            expected_updated_at=updated_at,
            actor="local_web",
        )
        return self._job_payload(row)

    def list_runs(
        self,
        job_key: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        if job_key is not None and job_key not in ARCHIVE_JOB_CONTRACTS:
            raise KeyError(job_key)
        return [
            {
                "id": row["id"],
                "jobId": row["job_id"],
                "jobKey": row["job_key"],
                "triggerType": row["trigger_type"],
                "runState": row["run_state"],
                "attempt": row["attempt"],
                "recordCount": row["record_count"],
                "resultSummary": row["result_summary"],
                "errorType": row["error_type"],
                "errorMessage": row["error_message"],
                "createdAt": row["created_at"],
                "startedAt": row["started_at"],
                "finishedAt": row["finished_at"],
            }
            for row in self._db.list_archive_runs(job_key, limit)
        ]

    def list_artifacts(self, run_id: int) -> list[dict[str, object]]:
        return [
            {
                "id": row["id"],
                "runId": row["run_id"],
                "artifactType": row["artifact_type"],
                "relativePath": row["relative_path"],
                "displayName": row["display_name"],
                "sizeBytes": row["size_bytes"],
                "sha256": row["sha256"],
                "createdAt": row["created_at"],
            }
            for row in self._db.list_archive_artifacts(run_id)
        ]

    def list_audit(
        self,
        job_key: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        if job_key is not None and job_key not in ARCHIVE_JOB_CONTRACTS:
            raise KeyError(job_key)
        result: list[dict[str, object]] = []
        for row in self._db.list_archive_config_audit(job_key, limit):
            changes = _json_object(row["changes_json"])
            result.append(
                {
                    "id": row["id"],
                    "jobId": row["job_id"],
                    "jobKey": row["job_key"],
                    "actor": row["actor"],
                    "eventType": row["event_type"],
                    "changes": changes,
                    "createdAt": row["created_at"],
                }
            )
        return result

    def sync_now(self, job_key: str) -> dict[str, object]:
        if job_key not in ARCHIVE_JOB_CONTRACTS:
            raise KeyError(job_key)
        result = self._runner_factory(self._db).run_once(
            trigger_type="sync_now",
            job_key=job_key,
        )
        return self._run_once_payload(result)

    def _job_payload(self, row: Mapping[str, object]) -> dict[str, object]:
        last_success = _parse_utc(row.get("last_success_at"))
        if last_success is None:
            freshness = "unknown"
        else:
            now = self._clock()
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            elapsed = now.astimezone(timezone.utc) - last_success
            freshness = (
                "stale"
                if elapsed > timedelta(hours=24)
                else "fresh"
            )
        job_key = str(row["job_key"])
        return {
            "id": row["id"],
            "jobKey": job_key,
            "sourceType": row["source_type"],
            "reportType": row["report_type"],
            "deliverableId": row["project_status_deliverable_id"],
            "enabled": bool(row["enabled"]),
            "credentialConfigured": bool(row["credential_configured"]),
            "intervalMinutes": 60,
            "filters": _json_object(row["filters_json"]),
            "allowedFilterNames": list(archive_filter_names(job_key)),
            "outputSubdir": row["output_subdir"] or "",
            "retryPolicy": _json_object(row["retry_policy_json"]),
            "syncState": row["sync_state"],
            "freshness": freshness,
            "lastAttemptAt": row["last_attempt_at"],
            "lastSuccessAt": row["last_success_at"],
            "lastErrorType": row["last_error_type"],
            "lastErrorMessage": row["last_error_message"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _run_once_payload(result: ArchiveRunOnceResult) -> dict[str, object]:
        return {
            "dryRun": result.dry_run,
            "exitCode": result.exit_code,
            "results": [
                {
                    "jobId": item.job_id,
                    "jobKey": item.job_key,
                    "outcome": item.outcome,
                    "runId": item.run_id,
                    "finalState": item.final_state,
                    "errorType": item.error_type,
                    "errorMessage": item.error_message,
                }
                for item in result.results
            ],
        }
