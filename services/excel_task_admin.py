"""Framework-independent administration for local Excel tasks."""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from core.excel_tasks import (
    ALLOWED_TASK_STATUSES,
    ExcelIdempotencyConflictError,
    ExcelPathSafetyError,
    ExcelTaskFileRef,
    ExcelTaskRepository,
)
from core.redaction import redact_sensitive_text

logger = logging.getLogger("vse_toolbox.excel_task_admin")

_CREATE_FIELDS = {"operation", "files", "idempotencyKey", "options", "maxAttempts"}
_FILE_FIELDS = {"role", "rootId", "relativePath", "ordinal"}


class ExcelArtifactUnavailableError(RuntimeError):
    """Artifact file is absent, unsafe, or no longer matches recorded metadata."""


@dataclass(frozen=True)
class ExcelArtifactDownload:
    """Verified in-memory artifact prepared for the Flask adapter."""

    data: bytes
    display_name: str
    mimetype: str


class ExcelTaskAdminValidationError(ValueError):
    """Bounded request validation failure suitable for an HTTP field response."""

    def __init__(self, fields: Mapping[str, str]) -> None:
        super().__init__("Excel task administration request is invalid")
        self.fields = dict(fields)


class ExcelTaskAdminService:
    """Expose safe creation and read-only history contracts for Excel tasks."""

    def __init__(
        self,
        repository: ExcelTaskRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def list_roots(self) -> list[dict[str, str]]:
        """Return sorted canonical root ID objects without filesystem or path details."""
        return [{"rootId": rid} for rid in self._repository.roots.root_ids]

    def create_task(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        fields: dict[str, str] = {}
        unknown = set(payload) - _CREATE_FIELDS
        if unknown:
            fields["request"] = "contains unsupported fields"

        operation = payload.get("operation")
        if not isinstance(operation, str) or not operation.strip():
            fields["operation"] = "must be a non-empty string"

        idempotency_key = payload.get("idempotencyKey")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            fields["idempotencyKey"] = "must be a non-empty string"

        options = payload.get("options", {})
        if not isinstance(options, Mapping):
            fields["options"] = "must be an object"
        elif options:
            fields["options"] = "must be empty in this phase"

        max_attempts = payload.get("maxAttempts", 1)
        if (
            not isinstance(max_attempts, int)
            or isinstance(max_attempts, bool)
            or max_attempts != 1
        ):
            fields["maxAttempts"] = "must be 1 until Excel transformations are retry-safe"

        raw_files = payload.get("files")
        refs: list[ExcelTaskFileRef] = []
        if not isinstance(raw_files, list) or not raw_files:
            fields["files"] = "must be a non-empty array"
        else:
            for index, item in enumerate(raw_files):
                key = f"files[{index}]"
                if not isinstance(item, Mapping):
                    fields[key] = "must be an object"
                    continue
                if set(item) - _FILE_FIELDS:
                    fields[key] = "contains unsupported fields"
                    continue
                try:
                    role_value = item.get("role")
                    root_value = item.get("rootId")
                    path_value = item.get("relativePath")
                    if not isinstance(role_value, str):
                        raise ValueError("role must be a string")
                    if not isinstance(root_value, str):
                        raise ValueError("rootId must be a string")
                    if not isinstance(path_value, str):
                        raise ValueError("relativePath must be a string")
                    refs.append(
                        ExcelTaskFileRef(
                            role=role_value,
                            root_id=root_value,
                            relative_path=path_value,
                            ordinal=item.get("ordinal", 0),
                        )
                    )
                except (TypeError, ValueError) as exc:
                    fields[key] = self._safe_message(exc)

        if fields:
            raise ExcelTaskAdminValidationError(fields)

        try:
            task = self._repository.create_task(
                str(operation),
                refs,
                str(idempotency_key),
                options=dict(options),
                max_attempts=1,
            )
        except ExcelIdempotencyConflictError:
            raise
        except (ExcelPathSafetyError, TypeError, ValueError) as exc:
            raise ExcelTaskAdminValidationError(
                {"request": self._safe_message(exc)}
            ) from exc
        return self._task_payload(task)

    def list_tasks(self, status: str | None, limit: object) -> list[dict[str, Any]]:
        normalized_status = status.strip() if isinstance(status, str) else None
        if normalized_status == "":
            normalized_status = None
        if normalized_status is not None and normalized_status not in ALLOWED_TASK_STATUSES:
            raise ExcelTaskAdminValidationError({"status": "is not a valid task status"})
        bounded_limit = self._limit(limit)
        return [
            self._task_payload(task)
            for task in self._repository.list_tasks(normalized_status, bounded_limit)
        ]

    def get_task(self, task_id: int) -> dict[str, Any]:
        task = self._repository.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        return self._task_payload(task)

    def list_runs(self, task_id: int) -> list[dict[str, Any]]:
        if self._repository.get_task(task_id) is None:
            raise KeyError(task_id)
        return [self._run_payload(run) for run in self._repository.list_task_runs(task_id)]

    def list_artifacts(self, task_id: int) -> list[dict[str, Any]]:
        if self._repository.get_task(task_id) is None:
            raise KeyError(task_id)
        return [
            self._artifact_payload(item)
            for item in self._repository.list_task_artifacts(task_id)
        ]

    def get_artifact(self, artifact_id: int) -> dict[str, Any]:
        artifact = self._repository.get_artifact(artifact_id)
        if artifact is None:
            raise KeyError(artifact_id)
        return self._artifact_payload(artifact)

    def _record_audit_best_effort(
        self,
        artifact_id: int,
        task_id: int,
        result: str,
        reason_code: str,
        served_size_bytes: int | None = None,
    ) -> None:
        try:
            self._repository.record_artifact_download_audit(
                artifact_id=artifact_id,
                task_id=task_id,
                result=result,
                reason_code=reason_code,
                served_size_bytes=served_size_bytes,
            )
        except Exception:
            logger.warning(
                "Failed to persist artifact download audit (artifact_id=%s, task_id=%s, result=%s, reason_code=%s)",
                artifact_id,
                task_id,
                result,
                reason_code,
            )

    def prepare_artifact_download(self, artifact_id: int) -> ExcelArtifactDownload:
        artifact = self._repository.get_artifact(artifact_id)
        if artifact is None:
            raise KeyError(artifact_id)

        task_id = int(artifact["task_id"])

        try:
            ref = ExcelTaskFileRef(
                role="output",
                root_id=artifact["root_id"],
                relative_path=artifact["relative_path"],
            )
        except ExcelPathSafetyError as exc:
            reason = "reparse_point_detected" if "reparse" in str(exc).lower() else "unsafe_path"
            self._record_audit_best_effort(artifact_id, task_id, "rejected", reason)
            raise ExcelArtifactUnavailableError("artifact is unavailable") from exc
        except (TypeError, ValueError) as exc:
            self._record_audit_best_effort(artifact_id, task_id, "rejected", "unsafe_path")
            raise ExcelArtifactUnavailableError("artifact is unavailable") from exc

        try:
            path = self._repository.roots.resolve_ref(ref, check_role=False)
        except ExcelPathSafetyError as exc:
            reason = "reparse_point_detected" if "reparse" in str(exc).lower() else "unsafe_path"
            self._record_audit_best_effort(artifact_id, task_id, "rejected", reason)
            raise ExcelArtifactUnavailableError("artifact is unavailable") from exc
        except (TypeError, ValueError, OSError) as exc:
            self._record_audit_best_effort(artifact_id, task_id, "rejected", "unsafe_path")
            raise ExcelArtifactUnavailableError("artifact is unavailable") from exc

        if not path.exists():
            self._record_audit_best_effort(artifact_id, task_id, "rejected", "file_missing")
            raise ExcelArtifactUnavailableError("artifact is unavailable")
        if not path.is_file():
            self._record_audit_best_effort(artifact_id, task_id, "rejected", "unsafe_path")
            raise ExcelArtifactUnavailableError("artifact is unavailable")

        try:
            data = path.read_bytes()
        except OSError:
            self._record_audit_best_effort(artifact_id, task_id, "rejected", "read_error")
            raise ExcelArtifactUnavailableError("artifact is unavailable")

        actual_digest = hashlib.sha256(data).hexdigest()
        expected_digest = str(artifact["sha256"])
        if len(data) != int(artifact["size_bytes"]) or not hmac.compare_digest(
            actual_digest,
            expected_digest,
        ):
            self._record_audit_best_effort(artifact_id, task_id, "rejected", "integrity_mismatch")
            raise ExcelArtifactUnavailableError("artifact integrity validation failed")

        self._record_audit_best_effort(
            artifact_id,
            task_id,
            "succeeded",
            "verified",
            served_size_bytes=len(data),
        )

        suffix = Path(ref.relative_path).suffix.lower()
        mimetype = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if suffix == ".xlsx"
            else "application/vnd.ms-excel"
        )
        return ExcelArtifactDownload(
            data=data,
            display_name=str(artifact["display_name"]),
            mimetype=mimetype,
        )

    def list_artifact_download_audits(
        self,
        artifact_id: int,
        limit: object = None,
    ) -> list[dict[str, Any]]:
        if self._repository.get_artifact(artifact_id) is None:
            raise KeyError(artifact_id)
        bounded_limit = self._limit(limit)
        return [
            self._download_audit_payload(item)
            for item in self._repository.list_artifact_download_audits(
                artifact_id,
                bounded_limit,
            )
        ]

    def plan_retention(
        self,
        *,
        retention_days: object,
        limit: object = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Produce a deterministic read-only artifact retention plan based on metadata timestamps.

        Validates parameters, performs no filesystem access, and leaks no paths beyond stored metadata.
        """
        if retention_days in (None, "") or isinstance(retention_days, bool):
            raise ExcelTaskAdminValidationError(
                {"retentionDays": "must be an integer between 1 and 3650"}
            )
        try:
            parsed_days = int(str(retention_days))
        except (TypeError, ValueError) as exc:
            raise ExcelTaskAdminValidationError(
                {"retentionDays": "must be an integer between 1 and 3650"}
            ) from exc
        if not 1 <= parsed_days <= 3650:
            raise ExcelTaskAdminValidationError(
                {"retentionDays": "must be between 1 and 3650"}
            )

        if limit in (None, ""):
            bounded_limit = 200
        else:
            if isinstance(limit, bool):
                raise ExcelTaskAdminValidationError(
                    {"limit": "must be an integer between 1 and 500"}
                )
            try:
                parsed_limit = int(str(limit))
            except (TypeError, ValueError) as exc:
                raise ExcelTaskAdminValidationError(
                    {"limit": "must be an integer"}
                ) from exc
            if not 1 <= parsed_limit <= 500:
                raise ExcelTaskAdminValidationError(
                    {"limit": "must be between 1 and 500"}
                )
            bounded_limit = parsed_limit

        current = now if now is not None else self._clock()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        else:
            current = current.astimezone(timezone.utc)

        cutoff_dt = current - timedelta(days=parsed_days)
        cutoff_iso = (
            f"{cutoff_dt.strftime('%Y-%m-%dT%H:%M:%S')}."
            f"{cutoff_dt.microsecond // 1000:03d}Z"
        )

        candidates, truncated = self._repository.list_retention_candidates(
            cutoff_iso,
            bounded_limit,
        )
        return {
            "cutoffAt": cutoff_iso,
            "truncated": truncated,
            "artifacts": [self._artifact_payload(item) for item in candidates],
        }

    @staticmethod
    def _limit(value: object) -> int:
        if value in (None, ""):
            return 50
        try:
            parsed = int(str(value))
        except (TypeError, ValueError) as exc:
            raise ExcelTaskAdminValidationError({"limit": "must be an integer"}) from exc
        if isinstance(value, bool) or not 1 <= parsed <= 200:
            raise ExcelTaskAdminValidationError({"limit": "must be between 1 and 200"})
        return parsed

    def _safe_message(self, value: object) -> str:
        safe = redact_sensitive_text(value, limit=400, collapse_newlines=True)
        for root_id in self._repository.roots.root_ids:
            root_text = str(self._repository.roots.get_root(root_id))
            replacement = f"<approved-root:{root_id}>"
            safe = re.sub(re.escape(root_text), replacement, safe, flags=re.IGNORECASE)
            safe = re.sub(
                re.escape(root_text.replace("\\", "/")),
                replacement,
                safe,
                flags=re.IGNORECASE,
            )
        return safe

    def _task_payload(self, task: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "id": int(task["id"]),
            "operation": str(task["operation"]),
            "status": str(task["status"]),
            "options": dict(task.get("options") or {}),
            "attemptCount": int(task["attempt_count"]),
            "maxAttempts": int(task["max_attempts"]),
            "errorType": task.get("error_type"),
            "errorMessage": (
                self._safe_message(task["error_message"])
                if task.get("error_message")
                else None
            ),
            "createdAt": str(task["created_at"]),
            "updatedAt": str(task["updated_at"]),
            "startedAt": task.get("started_at"),
            "finishedAt": task.get("finished_at"),
            "files": [
                {
                    "role": ref.role,
                    "rootId": ref.root_id,
                    "relativePath": ref.relative_path,
                    "ordinal": ref.ordinal,
                }
                for ref in task.get("files", [])
            ],
        }

    def _run_payload(self, run: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "id": int(run["id"]),
            "taskId": int(run["task_id"]),
            "attempt": int(run["attempt"]),
            "runState": str(run["run_state"]),
            "errorType": run.get("error_type"),
            "errorMessage": (
                self._safe_message(run["error_message"])
                if run.get("error_message")
                else None
            ),
            "createdAt": str(run["created_at"]),
            "startedAt": run.get("started_at"),
            "finishedAt": run.get("finished_at"),
        }

    @staticmethod
    def _artifact_payload(artifact: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "id": int(artifact["id"]),
            "taskId": int(artifact["task_id"]),
            "runId": int(artifact["run_id"]),
            "artifactType": str(artifact["artifact_type"]),
            "rootId": str(artifact["root_id"]),
            "relativePath": str(artifact["relative_path"]),
            "displayName": str(artifact["display_name"]),
            "sizeBytes": int(artifact["size_bytes"]),
            "sha256": str(artifact["sha256"]),
            "createdAt": str(artifact["created_at"]),
        }

    @staticmethod
    def _download_audit_payload(item: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "id": int(item["id"]),
            "artifactId": int(item["artifact_id"]),
            "taskId": int(item["task_id"]),
            "result": str(item["result"]),
            "reasonCode": str(item["reason_code"]),
            "servedSizeBytes": (
                int(item["served_size_bytes"])
                if item.get("served_size_bytes") is not None
                else None
            ),
            "createdAt": str(item["created_at"]),
        }
