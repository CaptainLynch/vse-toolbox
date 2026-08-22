# -*- coding: utf-8 -*-
"""One-shot orchestration for fixed scheduled archive jobs.

This module is framework-independent.  Windows Task Scheduler invokes a CLI
entry point; no permanent scheduler is hosted in Flask.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Protocol

from core.archive_store import ArchiveArtifact
from core.credential_provider import (
    CredentialProvider,
    CredentialProviderError,
    ResolvedCredential,
)
from core.db_manager import (
    ARCHIVE_JOB_CONTRACTS,
    ArchiveJobNotReadyError,
    ArchiveLeaseBusyError,
    ArchiveLeaseLostError,
    DatabaseManager,
)
from core.redaction import redact_sensitive_text

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_ATTENTION = 2
EXIT_INTERRUPTED = 130
_TEXT_LIMIT = 1000
_TRANSIENT_ERRORS = (ConnectionError, TimeoutError, OSError)


def _safe_text(value: object, *, limit: int = _TEXT_LIMIT) -> str:
    return redact_sensitive_text(
        value,
        limit=limit,
        collapse_newlines=True,
    )


def _error_type(exc: BaseException) -> str:
    if isinstance(exc, ArchiveLeaseBusyError):
        return "lease_busy"
    if isinstance(exc, ArchiveLeaseLostError):
        return "lease_lost"
    if isinstance(exc, ArchiveJobNotReadyError):
        return "job_not_ready"
    if isinstance(exc, CredentialProviderError):
        return "credential_unavailable"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ConnectionError):
        return "connection_error"
    if isinstance(exc, OSError):
        return "io_error"
    if isinstance(exc, ValueError):
        return "invalid_data"
    if isinstance(exc, KeyError):
        return "missing_job"
    return "connector_error"


def _safe_exception_message(exc: BaseException) -> str:
    """Return a stable diagnostic without reflecting external exception text."""
    messages = {
        "lease_busy": "archive job already has an active lease",
        "lease_lost": "archive job lease was lost",
        "job_not_ready": "archive job configuration is not ready",
        "credential_unavailable": "credential reference is unavailable",
        "timeout": "external archive request timed out",
        "connection_error": "external archive connection failed",
        "io_error": "archive input/output operation failed",
        "invalid_data": "archive connector returned invalid data",
        "missing_job": "archive job was not found",
        "connector_error": "archive connector failed",
    }
    return messages[_error_type(exc)]


def _required_int(values: Mapping[str, object], key: str) -> int:
    value = values[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"archive {key} is invalid")
    return value


def _required_mapping(
    values: Mapping[str, object],
    key: str,
) -> Mapping[str, object]:
    value = values[key]
    if not isinstance(value, Mapping):
        raise ValueError(f"archive {key} is invalid")
    return value


@dataclass(frozen=True)
class ArchiveJobContext:
    """Secret-free, fixed-contract input visible to one connector."""

    job_id: int
    job_key: str
    source_type: str
    report_type: str
    filters: Mapping[str, object]
    output_subdir: str
    run_id: int


@dataclass(frozen=True)
class ArchiveCollection:
    """A completed collection ready for atomic database finalization."""

    record_count: int
    artifacts: tuple[ArchiveArtifact, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.record_count, int)
            or isinstance(self.record_count, bool)
            or self.record_count < 0
        ):
            raise ValueError("record_count must be a non-negative int")
        if not self.artifacts or any(
            not isinstance(item, ArchiveArtifact) for item in self.artifacts
        ):
            raise ValueError("archive collection requires artifacts")


class ArchiveConnector(Protocol):
    """Read-only external collector; it cannot receive a database handle."""

    def collect(
        self,
        context: ArchiveJobContext,
        credential: ResolvedCredential,
    ) -> ArchiveCollection:
        ...


class ArchiveConnectorRegistry:
    """Explicit registry restricted to the six approved stable job keys."""

    def __init__(self) -> None:
        self._connectors: dict[str, ArchiveConnector] = {}

    def register(self, job_key: str, connector: ArchiveConnector) -> None:
        if job_key not in ARCHIVE_JOB_CONTRACTS:
            raise ValueError("archive connector job key is not approved")
        self._connectors[job_key] = connector

    def get(self, job_key: str) -> ArchiveConnector | None:
        if job_key not in ARCHIVE_JOB_CONTRACTS:
            return None
        return self._connectors.get(job_key)

    @property
    def registered_job_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._connectors))


@dataclass(frozen=True)
class ArchiveJobRunResult:
    job_id: int | None
    job_key: str
    outcome: str
    run_id: int | None = None
    final_state: str | None = None
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class ArchiveRunOnceResult:
    results: tuple[ArchiveJobRunResult, ...]
    dry_run: bool = False

    @property
    def exit_code(self) -> int:
        if any(item.outcome == "failed" for item in self.results):
            return EXIT_FAILED
        if any(
            item.outcome in {"needs_attention", "not_ready"}
            for item in self.results
        ):
            return EXIT_ATTENTION
        return EXIT_OK


class ArchiveSyncRunner:
    """Execute fixed archive jobs once, with lease and retry enforcement."""

    def __init__(
        self,
        db: DatabaseManager,
        credentials: CredentialProvider,
        registry: ArchiveConnectorRegistry,
        *,
        max_attempts: int = 2,
        backoff_seconds: float = 1.0,
        lease_seconds: int = 900,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if max_attempts < 1 or max_attempts > 2:
            raise ValueError("max_attempts must be between 1 and 2")
        if backoff_seconds < 0:
            raise ValueError("backoff_seconds must be non-negative")
        self._db = db
        self._credentials = credentials
        self._registry = registry
        self._max_attempts = max_attempts
        self._backoff_seconds = float(backoff_seconds)
        self._lease_seconds = lease_seconds
        self._sleeper = sleeper
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def run_job(
        self,
        job_id: int,
        *,
        trigger_type: str = "scheduled",
    ) -> ArchiveJobRunResult:
        lease: dict[str, object] | None = None
        try:
            lease = self._db.acquire_archive_job_lease(
                job_id,
                trigger_type,
                lease_seconds=self._lease_seconds,
            )
            run_id = _required_int(lease, "run_id")
            lease_token = str(lease["lease_token"])
            job_key = str(lease["job_key"])
            self._db.start_archive_run(job_id, run_id, lease_token)

            connector = self._registry.get(job_key)
            if connector is None:
                return self._finalize_attention(
                    job_id,
                    job_key,
                    run_id,
                    lease_token,
                    "connector_unavailable",
                    "approved archive connector is unavailable",
                )

            context = ArchiveJobContext(
                job_id=job_id,
                job_key=job_key,
                source_type=str(lease["source_type"]),
                report_type=str(lease["report_type"]),
                filters=dict(_required_mapping(lease, "filters")),
                output_subdir=str(lease["output_subdir"]),
                run_id=run_id,
            )
            credential_ref = self._db.get_archive_job_credential_ref(job_id)
            collection = self._collect_with_retry(
                connector,
                context,
                credential_ref,
            )
            self._db.finalize_archive_run(
                job_id,
                run_id,
                lease_token,
                "success",
                record_count=collection.record_count,
                artifacts=tuple(
                    item.as_metadata() for item in collection.artifacts
                ),
                result_summary=(
                    f"archived {collection.record_count} records in "
                    f"{len(collection.artifacts)} artifacts"
                ),
            )
            return ArchiveJobRunResult(
                job_id,
                job_key,
                "completed",
                run_id,
                "success",
            )
        except KeyboardInterrupt:
            if lease is not None:
                self._safe_finalize_failure(lease, "interrupted", "run interrupted")
            raise
        except ArchiveLeaseBusyError as exc:
            return ArchiveJobRunResult(
                job_id,
                "",
                "skipped",
                error_type=_error_type(exc),
                error_message=_safe_exception_message(exc),
            )
        except ArchiveJobNotReadyError as exc:
            return ArchiveJobRunResult(
                job_id,
                "",
                "not_ready",
                error_type=_error_type(exc),
                error_message=_safe_exception_message(exc),
            )
        except Exception as exc:
            if lease is None:
                return ArchiveJobRunResult(
                    job_id,
                    "",
                    "failed",
                    error_type=_error_type(exc),
                    error_message=_safe_exception_message(exc),
                )
            return self._finalize_exception(lease, exc)

    def run_once(
        self,
        *,
        trigger_type: str = "scheduled",
        job_key: str | None = None,
        dry_run: bool = False,
    ) -> ArchiveRunOnceResult:
        if trigger_type not in {"scheduled", "sync_now"}:
            raise ValueError("unsupported archive trigger_type")
        jobs = self._db.list_archive_jobs(enabled_only=True)
        if job_key is not None:
            jobs = [item for item in jobs if item["job_key"] == job_key]
            if not jobs:
                return ArchiveRunOnceResult(
                    (
                        ArchiveJobRunResult(
                            None,
                            job_key,
                            "not_ready",
                            error_type="missing_job",
                            error_message="enabled archive job was not found",
                        ),
                    ),
                    dry_run,
                )

        results: list[ArchiveJobRunResult] = []
        for job in jobs:
            key = str(job["job_key"])
            job_id = _required_int(job, "id")
            if trigger_type == "scheduled" and not self._is_due(job):
                results.append(ArchiveJobRunResult(job_id, key, "not_due"))
                continue
            if dry_run:
                ready = bool(job["credential_configured"]) and (
                    self._registry.get(key) is not None
                )
                results.append(
                    ArchiveJobRunResult(
                        job_id,
                        key,
                        "ready" if ready else "not_ready",
                        error_type=None if ready else "job_not_ready",
                    )
                )
                continue
            results.append(
                self.run_job(job_id, trigger_type=trigger_type)
            )
        return ArchiveRunOnceResult(tuple(results), dry_run)

    def _collect_with_retry(
        self,
        connector: ArchiveConnector,
        context: ArchiveJobContext,
        credential_ref: str,
    ) -> ArchiveCollection:
        for attempt in range(1, self._max_attempts + 1):
            try:
                with self._credentials.resolve(credential_ref) as credential:
                    return connector.collect(context, credential)
            except _TRANSIENT_ERRORS:
                if attempt >= self._max_attempts:
                    raise
                self._sleeper(
                    self._backoff_seconds * (2 ** (attempt - 1))
                )
        raise AssertionError("unreachable")

    def _finalize_attention(
        self,
        job_id: int,
        job_key: str,
        run_id: int,
        lease_token: str,
        error_type: str,
        message: str,
    ) -> ArchiveJobRunResult:
        safe_message = _safe_text(message)
        self._db.finalize_archive_run(
            job_id,
            run_id,
            lease_token,
            "needs_attention",
            error_type=error_type,
            error_message=safe_message,
            result_summary=safe_message,
        )
        return ArchiveJobRunResult(
            job_id,
            job_key,
            "needs_attention",
            run_id,
            "needs_attention",
            error_type,
            safe_message,
        )

    def _finalize_exception(
        self,
        lease: Mapping[str, object],
        exc: BaseException,
    ) -> ArchiveJobRunResult:
        job_id = _required_int(lease, "job_id")
        job_key = str(lease["job_key"])
        run_id = _required_int(lease, "run_id")
        lease_token = str(lease["lease_token"])
        category = _error_type(exc)
        message = _safe_exception_message(exc)
        final_state = (
            "needs_attention"
            if isinstance(
                exc,
                (CredentialProviderError, ArchiveJobNotReadyError),
            )
            else "failed"
        )
        try:
            self._db.finalize_archive_run(
                job_id,
                run_id,
                lease_token,
                final_state,
                error_type=category,
                error_message=message,
                result_summary=message,
            )
        except ArchiveLeaseLostError as lost:
            return ArchiveJobRunResult(
                job_id,
                job_key,
                "failed",
                run_id,
                error_type="lease_lost",
                error_message=_safe_exception_message(lost),
            )
        return ArchiveJobRunResult(
            job_id,
            job_key,
            "needs_attention" if final_state == "needs_attention" else "failed",
            run_id,
            final_state,
            category,
            message,
        )

    def _safe_finalize_failure(
        self,
        lease: Mapping[str, object],
        category: str,
        message: str,
    ) -> None:
        try:
            self._db.finalize_archive_run(
                _required_int(lease, "job_id"),
                _required_int(lease, "run_id"),
                str(lease["lease_token"]),
                "failed",
                error_type=category,
                error_message=_safe_text(message),
                result_summary=_safe_text(message),
            )
        except Exception:
            pass

    def _is_due(self, job: Mapping[str, object]) -> bool:
        value = job.get("last_attempt_at")
        if not value:
            return True
        try:
            text = str(value).strip()
            parsed = datetime.fromisoformat(
                text[:-1] + "+00:00" if text.endswith("Z") else text
            )
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            now = self._clock()
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            interval = _required_int(job, "interval_minutes")
            elapsed = (
                now.astimezone(timezone.utc)
                - parsed.astimezone(timezone.utc)
            ).total_seconds()
            return elapsed >= interval * 60
        except (KeyError, TypeError, ValueError, OverflowError):
            return True


def create_production_archive_runner(
    db: DatabaseManager,
) -> ArchiveSyncRunner:
    """Construct the one-shot production runner with the fixed registry."""
    from core.credential_provider import WindowsCredentialManagerProvider
    from services.scheduled_archive_connectors import (
        create_production_archive_registry,
    )

    return ArchiveSyncRunner(
        db,
        WindowsCredentialManagerProvider(),
        create_production_archive_registry(),
    )
