# -*- coding: utf-8 -*-
"""
core/excel_worker.py — Excel Phase B serial task worker core.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Sequence

from core.excel_tasks import (
    DEFAULT_LEASE_SECONDS,
    LEASE_MAX_SECONDS,
    LEASE_MIN_SECONDS,
    ExcelInvalidStateError,
    ExcelLeaseLostError,
    ExcelPathSafetyError,
    ExcelTaskArtifactMetadata,
    ExcelTaskFileRef,
    ExcelTaskRepository,
)
from services.excel_toolbox import ExcelToolbox

logger = logging.getLogger("vse_toolbox.excel_worker")


class ExcelTaskRunStatus(str, Enum):
    """Outcome of one worker polling/execution attempt."""

    IDLE = "idle"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    LEASE_LOST = "lease_lost"


@dataclass(frozen=True)
class ExcelTaskRunResult:
    status: ExcelTaskRunStatus
    task_id: int | None = None
    run_id: int | None = None
    operation: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    output_committed: bool = False
    artifact_id: int | None = None

    @property
    def processed(self) -> bool:
        return self.status is not ExcelTaskRunStatus.IDLE

    @property
    def succeeded(self) -> bool:
        return self.status is ExcelTaskRunStatus.SUCCEEDED


@dataclass(frozen=True)
class ExcelWorkerRunSummary:
    processed: int
    succeeded: int
    failed: int
    lease_lost: int


def _is_same_or_alias(path1: Path, path2: Path) -> bool:
    try:
        if path1.resolve() == path2.resolve():
            return True
    except (OSError, RuntimeError):
        pass
    if path1.exists() and path2.exists():
        try:
            if path1.samefile(path2):
                return True
        except (OSError, RuntimeError):
            pass
    return False


def _cleanup_temp(path: Path | None) -> None:
    if path is not None:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


def _file_integrity(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
        size_bytes = os.fstat(stream.fileno()).st_size
    return int(size_bytes), digest.hexdigest()


class ExcelTaskWorker:
    """Excel offline task local serial worker."""

    def __init__(
        self,
        repository: ExcelTaskRepository,
        executor_factory: Any = ExcelToolbox,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        renew_interval_seconds: float | None = None,
        poll_interval_seconds: float = 0.1,
    ) -> None:
        if repository is None:
            raise ValueError("repository cannot be None")
        if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or not (
            LEASE_MIN_SECONDS <= lease_seconds <= LEASE_MAX_SECONDS
        ):
            raise ValueError(f"lease_seconds must be between {LEASE_MIN_SECONDS} and {LEASE_MAX_SECONDS}")
        if renew_interval_seconds is not None:
            if not isinstance(renew_interval_seconds, (int, float)) or renew_interval_seconds <= 0:
                raise ValueError("renew_interval_seconds must be a positive number or None")

        self._repository = repository
        self._executor_factory = executor_factory
        self._lease_seconds = lease_seconds
        # Keep long-running COM work leased by default while allowing callers
        # to choose a tighter interval for tests or unusually short leases.
        self._renew_interval_seconds = (
            float(renew_interval_seconds)
            if renew_interval_seconds is not None
            else max(1.0, lease_seconds / 3.0)
        )
        self._poll_interval = max(0.01, float(poll_interval_seconds))

    def _get_executor(self) -> Any:
        if callable(self._executor_factory):
            return self._executor_factory()
        return self._executor_factory

    def run_once(self) -> ExcelTaskRunResult:
        lease_info = self._repository.lease_next(lease_seconds=self._lease_seconds)
        if lease_info is None:
            return ExcelTaskRunResult(status=ExcelTaskRunStatus.IDLE)

        task_id = int(lease_info["task_id"])
        run_id = int(lease_info["run_id"])
        lease_token = str(lease_info["lease_token"])
        task_data = lease_info["task"]
        operation = str(task_data["operation"])
        file_refs: Sequence[ExcelTaskFileRef] = task_data["files"]

        temp_path: Path | None = None
        lease_lost = threading.Event()
        stop_renewal = threading.Event()
        renewal_thread: threading.Thread | None = None
        output_committed = False

        try:
            self._repository.start(task_id, run_id, lease_token)

            if self._renew_interval_seconds is not None and self._renew_interval_seconds > 0:
                def _renew_loop() -> None:
                    while not stop_renewal.wait(timeout=self._renew_interval_seconds):
                        try:
                            self._repository.renew(
                                task_id,
                                run_id,
                                lease_token,
                                lease_seconds=self._lease_seconds,
                            )
                        except (ExcelLeaseLostError, ExcelInvalidStateError) as exc:
                            logger.warning("Lease lost during background renew for task %s: %s", task_id, exc)
                            lease_lost.set()
                            break
                        except Exception as exc:
                            logger.warning("Unexpected error during lease renew for task %s: %s", task_id, exc)
                            lease_lost.set()
                            break

                renewal_thread = threading.Thread(
                    target=_renew_loop,
                    name=f"excel-worker-renew-{task_id}-{run_id}",
                    daemon=True,
                )
                renewal_thread.start()

            roots = getattr(self._repository, "roots", None)
            # Keep injected fake repositories usable without weakening the
            # production repository's public path-resolution contract.
            if roots is None:
                roots = getattr(self._repository, "_roots", None)
            if roots is None:
                raise ExcelPathSafetyError("repository does not have approved roots configured")

            sources: list[Path] = []
            target_path: Path | None = None
            baseline_path: Path | None = None
            output_path: Path | None = None
            output_ref: ExcelTaskFileRef | None = None

            sorted_refs = sorted(file_refs, key=lambda r: (r.role, r.ordinal))
            for ref in sorted_refs:
                resolved = roots.resolve_ref(ref, check_role=True)
                if ref.role == "source":
                    sources.append(resolved)
                elif ref.role == "target":
                    target_path = resolved
                elif ref.role == "baseline":
                    baseline_path = resolved
                elif ref.role == "output":
                    output_path = resolved
                    output_ref = ref

            if output_path is None or output_ref is None:
                raise ExcelPathSafetyError("task request is missing required output file reference")

            for src in sources:
                if _is_same_or_alias(output_path, src):
                    raise ExcelPathSafetyError(f"output path aliases with source file: {output_path}")

            if target_path is not None:
                if _is_same_or_alias(output_path, target_path):
                    if operation == "merge_overlay":
                        raise ExcelPathSafetyError(
                            "in-place merge_overlay is not allowed; output cannot equal target"
                        )
                    raise ExcelPathSafetyError(f"output path aliases with target file: {output_path}")

            if baseline_path is not None:
                if _is_same_or_alias(output_path, baseline_path):
                    raise ExcelPathSafetyError(f"output path aliases with baseline file: {output_path}")

            token = secrets.token_hex(8)
            temp_path = output_path.parent / f".tmp_{task_id}_{run_id}_{token}{output_path.suffix}"
            _cleanup_temp(temp_path)

            executor = self._get_executor()
            if operation == "merge_append":
                executor.merge_append(sources, output_path=temp_path, baseline=baseline_path)
            elif operation == "merge_overlay":
                if target_path is None:
                    raise ExcelPathSafetyError("merge_overlay requires a target file")
                executor.merge_overlay(sources, target_path, output_path=temp_path, baseline=baseline_path)
            elif operation == "diff_against_baseline":
                if target_path is None:
                    raise ExcelPathSafetyError("diff_against_baseline requires a target file")
                if baseline_path is None:
                    raise ExcelPathSafetyError("diff_against_baseline requires a baseline file")
                executor.diff_against_baseline(target_path, baseline_path, output_path=temp_path)
            else:
                raise ValueError(f"unsupported operation: {operation}")

            if not temp_path.exists() or not temp_path.is_file():
                raise FileNotFoundError(f"executor failed to produce temporary output file: {temp_path}")

            if lease_lost.is_set():
                raise ExcelLeaseLostError(f"lease lost during execution for task {task_id}")

            os.replace(temp_path, output_path)
            output_committed = True

            if lease_lost.is_set():
                raise ExcelLeaseLostError(f"lease lost before finish for task {task_id}")

            size_bytes, sha256 = _file_integrity(output_path)
            artifact = self._repository.finish_success_with_artifact(
                task_id,
                run_id,
                lease_token,
                ExcelTaskArtifactMetadata(
                    output_ref=output_ref,
                    size_bytes=size_bytes,
                    sha256=sha256,
                ),
            )
            return ExcelTaskRunResult(
                status=ExcelTaskRunStatus.SUCCEEDED,
                task_id=task_id,
                run_id=run_id,
                operation=operation,
                output_committed=True,
                artifact_id=int(artifact["id"]),
            )

        except ExcelLeaseLostError as exc:
            logger.warning("Lease lost for task %s: %s", task_id, exc)
            _cleanup_temp(temp_path)
            return ExcelTaskRunResult(
                status=ExcelTaskRunStatus.LEASE_LOST,
                task_id=task_id,
                run_id=run_id,
                operation=operation,
                error_type=exc.__class__.__name__,
                error_message=str(exc),
                output_committed=output_committed,
            )

        except (KeyboardInterrupt, SystemExit) as exc:
            logger.warning("Task %s interrupted: %s", task_id, exc)
            _cleanup_temp(temp_path)
            if not lease_lost.is_set():
                try:
                    self._repository.finish(
                        task_id,
                        run_id,
                        lease_token,
                        "failed",
                        error_type=exc.__class__.__name__,
                        error_message=str(exc),
                    )
                except Exception:
                    pass
            raise

        except BaseException as exc:
            if not isinstance(exc, Exception):
                logger.warning("Task %s terminated by BaseException: %s", task_id, exc)
                _cleanup_temp(temp_path)
                if not lease_lost.is_set():
                    try:
                        self._repository.finish(
                            task_id,
                            run_id,
                            lease_token,
                            "failed",
                            error_type=exc.__class__.__name__,
                            error_message=str(exc),
                        )
                    except Exception:
                        pass
                raise

            logger.error("Task %s failed: %s", task_id, exc, exc_info=True)
            _cleanup_temp(temp_path)
            if not lease_lost.is_set() and not output_committed:
                try:
                    self._repository.finish(
                        task_id,
                        run_id,
                        lease_token,
                        "failed",
                        error_type=exc.__class__.__name__,
                        error_message=str(exc),
                    )
                except Exception as finish_exc:
                    logger.warning("Failed to record failure for task %s: %s", task_id, finish_exc)
            return ExcelTaskRunResult(
                status=(
                    ExcelTaskRunStatus.LEASE_LOST
                    if lease_lost.is_set()
                    else ExcelTaskRunStatus.FAILED
                ),
                task_id=task_id,
                run_id=run_id,
                operation=operation,
                error_type=exc.__class__.__name__,
                error_message=str(exc),
                output_committed=output_committed,
            )

        finally:
            stop_renewal.set()
            if renewal_thread is not None and renewal_thread.is_alive():
                renewal_thread.join(timeout=2.0)
            _cleanup_temp(temp_path)

    def run(self, stop_event: threading.Event | None = None) -> ExcelWorkerRunSummary:
        processed = succeeded = failed = lease_lost_count = 0
        while not (stop_event is not None and stop_event.is_set()):
            result = self.run_once()
            if result.status is ExcelTaskRunStatus.IDLE:
                if stop_event is None:
                    break
                stop_event.wait(timeout=self._poll_interval)
                continue
            processed += 1
            if result.status is ExcelTaskRunStatus.SUCCEEDED:
                succeeded += 1
            elif result.status is ExcelTaskRunStatus.FAILED:
                failed += 1
            else:
                lease_lost_count += 1
        return ExcelWorkerRunSummary(processed, succeeded, failed, lease_lost_count)
