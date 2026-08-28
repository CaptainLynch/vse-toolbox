# -*- coding: utf-8 -*-
"""Framework-independent administration for fixed scheduled archive jobs."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping

from core.archive_store import ArchiveStore
from core.credential_provider import CredentialProvider
from core.native_folder_picker import choose_native_folder
from core.db_manager import (
    ARCHIVE_CREDENTIAL_UNCHANGED,
    ARCHIVE_RETRY_UNCHANGED,
    ARCHIVE_OUTPUT_DIRECTORY_UNCHANGED,
    ARCHIVE_JOB_CONTRACTS,
    DatabaseManager,
    _normalize_archive_retry_policy,
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
    "outputDirectory",
    "intervalMinutes",
    "retryPolicy",
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
        archive_store: ArchiveStore | None = None,
        native_picker: Callable[[Path], Path | None] = choose_native_folder,
        credential_provider: CredentialProvider | None = None,
    ) -> None:
        self._db = db
        self._runner_factory = runner_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._archive_store = archive_store
        self._native_picker = native_picker
        self._credential_provider = credential_provider

    def set_credential_provider(self, provider: CredentialProvider | None) -> None:
        """Attach the production provider after the app has initialized its vault."""
        self._credential_provider = provider

    def _store(self) -> ArchiveStore:
        if self._archive_store is not None:
            return self._archive_store
        configured = self._db.get_app_settings().get("archiveDirectory")
        if isinstance(configured, str) and configured.strip():
            return ArchiveStore({"default": configured.strip()})
        return ArchiveStore()

    def list_folders(self, relative_path: str = "") -> dict[str, object]:
        store = self._store()
        normalized = store.validate_output_subdir(relative_path)
        parent = normalized.rsplit("/", 1)[0] if "/" in normalized else ""
        return {
            "current": normalized,
            "parent": parent,
            "folders": store.list_subdirectories(normalized),
        }

    def pick_native_folder(self, initial_directory: str = "") -> dict[str, object]:
        """Open a local picker and return the selected absolute task directory."""
        store = self._store()
        normalized = ArchiveStore.validate_output_directory(initial_directory)
        initial = Path(normalized) if normalized else store.root()
        selected = self._native_picker(initial)
        if selected is None:
            return {"path": None, "cancelled": True}
        return {
            "path": ArchiveStore.validate_output_directory(str(selected)),
            "cancelled": False,
        }

    def list_jobs(self) -> list[dict[str, object]]:
        return [self._job_payload(row) for row in self._db.list_archive_jobs()]

    def update_job(
        self,
        job_key: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        existing = next((item for item in self._db.list_archive_jobs() if item["job_key"] == job_key), None)
        if existing is None:
            raise KeyError(job_key)
        template_key = str(existing["template_key"] or job_key)
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
        output_directory: object = ARCHIVE_OUTPUT_DIRECTORY_UNCHANGED
        updated_at = payload.get("updatedAt")
        interval_minutes = payload.get("intervalMinutes", existing["interval_minutes"])
        retry_policy: object = ARCHIVE_RETRY_UNCHANGED
        if not isinstance(enabled, bool):
            errors["enabled"] = "must be a boolean"
        if not isinstance(filters, Mapping):
            errors["filters"] = "must be an object"
        if not isinstance(output_subdir, str):
            errors["outputSubdir"] = "must be a string"
        if "outputDirectory" in payload:
            output_directory = payload["outputDirectory"]
            if not isinstance(output_directory, str):
                errors["outputDirectory"] = "must be a string"
            else:
                try:
                    output_directory = ArchiveStore.validate_output_directory(
                        output_directory
                    )
                except (TypeError, ValueError) as exc:
                    errors["outputDirectory"] = str(exc)
        if not isinstance(updated_at, str) or not updated_at.strip():
            errors["updatedAt"] = "is required"
        if isinstance(interval_minutes, bool) or not isinstance(interval_minutes, int) or not 5 <= interval_minutes <= 10080:
            errors["intervalMinutes"] = "must be an integer between 5 and 10080"
        credential_ref: object = ARCHIVE_CREDENTIAL_UNCHANGED
        if "credentialRef" in payload:
            credential_ref = payload["credentialRef"]
            if credential_ref is not None and not isinstance(
                credential_ref, str
            ):
                errors["credentialRef"] = "must be a string or null"
        if "retryPolicy" in payload:
            try:
                retry_policy = _normalize_archive_retry_policy(payload["retryPolicy"])
            except (TypeError, ValueError) as exc:
                errors["retryPolicy"] = str(exc)
        if errors:
            raise ArchiveAdminValidationError(errors)

        assert isinstance(enabled, bool)
        assert isinstance(filters, Mapping)
        assert isinstance(output_subdir, str)
        assert isinstance(updated_at, str)
        try:
            checked_filters = validate_archive_filters(template_key, filters)
        except (TypeError, ValueError) as exc:
            raise ArchiveAdminValidationError(
                {"filters": str(exc)}
            ) from exc

        if (
            isinstance(output_directory, str)
            and output_directory
            and output_subdir
        ):
            raise ArchiveAdminValidationError(
                {
                    "outputSubdir": (
                        "选择独立归档目录后不能同时保留旧版子目录，请清空该字段"
                    )
                }
            )

        if enabled and self._credential_provider is not None:
            ref_to_check: str | None = None
            if credential_ref is ARCHIVE_CREDENTIAL_UNCHANGED:
                if existing.get("credential_configured"):
                    ref_to_check = self._db.get_archive_job_credential_ref(int(existing["id"]))
            elif isinstance(credential_ref, str):
                ref_to_check = credential_ref.strip()
            if not ref_to_check:
                raise ArchiveAdminValidationError(
                    {"credentialRef": "启用前必须先在系统设置保存统一域账号凭据"}
                )
            if not self._credential_provider.is_available(ref_to_check):
                raise ArchiveAdminValidationError(
                    {"credentialRef": "统一域账号凭据不可用，请重新登录并保存至凭据保护库"}
                )

        update_kwargs = {
            "enabled": enabled,
            "credential_ref": credential_ref,
            "filters": checked_filters,
            "output_subdir": output_subdir,
            "expected_updated_at": updated_at,
            "actor": "local_web",
            "interval_minutes": interval_minutes,
        }
        if output_directory is not ARCHIVE_OUTPUT_DIRECTORY_UNCHANGED:
            update_kwargs["output_directory"] = output_directory
        if retry_policy is not ARCHIVE_RETRY_UNCHANGED:
            update_kwargs["retry_policy"] = retry_policy
        row = self._db.update_archive_job_config(job_key, **update_kwargs)
        return self._job_payload(row)

    def create_job(self, payload: Mapping[str, object]) -> dict[str, object]:
        template_key = payload.get("templateKey")
        display_name = payload.get("displayName")
        copy_from = payload.get("copyFromJobKey")
        errors: dict[str, str] = {}
        if not isinstance(template_key, str) or template_key not in ARCHIVE_JOB_CONTRACTS:
            errors["templateKey"] = "must be one of the approved templates"
        if not isinstance(display_name, str) or not display_name.strip():
            errors["displayName"] = "is required"
        if copy_from is not None and not isinstance(copy_from, str):
            errors["copyFromJobKey"] = "must be a string"
        if errors:
            raise ArchiveAdminValidationError(errors)
        row = self._db.create_archive_job_from_template(
            template_key,
            display_name=display_name,
            copy_from_job_key=copy_from,
        )
        return self._job_payload(row)

    def archive_job(self, job_key: str, updated_at: object) -> dict[str, object]:
        if not isinstance(updated_at, str) or not updated_at:
            raise ArchiveAdminValidationError({"updatedAt": "is required"})
        return self._job_payload(self._db.archive_archive_job(job_key, updated_at))

    def list_runs(
        self,
        job_key: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        if job_key is not None and not any(
            item["job_key"] == job_key for item in self._db.list_archive_jobs(include_archived=True)
        ):
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
        if job_key is not None and not any(
            item["job_key"] == job_key for item in self._db.list_archive_jobs(include_archived=True)
        ):
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
        if not any(item["job_key"] == job_key for item in self._db.list_archive_jobs()):
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
        template_key = str(row.get("template_key") or job_key)
        contract = ARCHIVE_JOB_CONTRACTS[template_key]
        credential_available = bool(row["credential_configured"])
        if credential_available and self._credential_provider is not None:
            try:
                credential_ref = self._db.get_archive_job_credential_ref(int(row["id"]))
                credential_available = self._credential_provider.is_available(credential_ref)
            except Exception:
                credential_available = False
        return {
            "id": row["id"],
            "jobKey": job_key,
            "sourceType": row["source_type"],
            "reportType": contract[1],
            "displayName": row.get("display_name") or job_key,
            "templateKey": template_key,
            "builtin": bool(row.get("builtin")),
            "archivedAt": row.get("archived_at"),
            "deliverableId": row["project_status_deliverable_id"],
            "enabled": bool(row["enabled"]),
            "credentialConfigured": bool(row["credential_configured"]),
            "credentialAvailable": credential_available,
            "intervalMinutes": row["interval_minutes"],
            "filters": _json_object(row["filters_json"]),
            "allowedFilterNames": list(archive_filter_names(template_key)),
            "outputSubdir": row["output_subdir"] or "",
            "outputDirectory": row.get("output_directory") or "",
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
