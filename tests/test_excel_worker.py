# -*- coding: utf-8 -*-
"""
tests/test_excel_worker.py — Excel Phase B serial task worker unit tests and contract verification.
"""

from __future__ import annotations

import hashlib
import multiprocessing
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from core.db_manager import DatabaseManager
from core.excel_tasks import (
    ApprovedExcelRoots,
    ExcelLeaseLostError,
    ExcelTaskArtifactMetadata,
    ExcelTaskFileRef,
    ExcelTaskRepository,
)
from core.excel_worker import (
    ExcelTaskRunResult,
    ExcelTaskRunStatus,
    ExcelTaskWorker,
    ExcelWorkerRunSummary,
)


class FakeExecutor:
    """Fake Excel toolbox executor for worker tests."""

    def __init__(
        self,
        failure: Exception | None = None,
        delay: float = 0.0,
        produce_file: bool = True,
    ) -> None:
        self.failure = failure
        self.delay = delay
        self.produce_file = produce_file
        self.calls: list[dict[str, Any]] = []

    def merge_append(
        self, sources: list[Path], output_path: Path, baseline: Path | None = None
    ) -> Path:
        self.calls.append({
            "operation": "merge_append",
            "sources": sources,
            "output_path": output_path,
            "baseline": baseline,
        })
        if self.delay > 0:
            time.sleep(self.delay)
        if self.produce_file:
            output_path.write_bytes(b"fake_merge_append_content")
        if self.failure:
            raise self.failure
        return output_path

    def merge_overlay(
        self,
        sources: list[Path],
        target: Path,
        output_path: Path,
        baseline: Path | None = None,
    ) -> Path:
        self.calls.append({
            "operation": "merge_overlay",
            "sources": sources,
            "target": target,
            "output_path": output_path,
            "baseline": baseline,
        })
        if self.delay > 0:
            time.sleep(self.delay)
        if self.produce_file:
            output_path.write_bytes(b"fake_merge_overlay_content")
        if self.failure:
            raise self.failure
        return output_path

    def diff_against_baseline(
        self, target: Path, baseline: Path, output_path: Path
    ) -> Path:
        self.calls.append({
            "operation": "diff_against_baseline",
            "target": target,
            "baseline": baseline,
            "output_path": output_path,
        })
        if self.delay > 0:
            time.sleep(self.delay)
        if self.produce_file:
            output_path.write_bytes(b"fake_diff_content")
        if self.failure:
            raise self.failure
        return output_path


def _lease_from_process(
    db_path: str,
    root_path: str,
    start_event: Any,
    result_queue: Any,
) -> None:
    try:
        database = DatabaseManager(db_path=Path(db_path))
        roots = ApprovedExcelRoots({"default": Path(root_path)})
        start_event.wait(timeout=20)
        lease = ExcelTaskRepository(database, roots).lease_next(lease_seconds=300)
        result_queue.put(None if lease is None else int(lease["task_id"]))
    except BaseException as exc:
        result_queue.put((exc.__class__.__name__, str(exc)))


@pytest.fixture
def roots_dir(tmp_path: Path) -> tuple[Path, ApprovedExcelRoots]:
    root_path = tmp_path / "excel_root"
    root_path.mkdir(parents=True, exist_ok=True)
    roots = ApprovedExcelRoots({"default": root_path})
    return root_path, roots


@pytest.fixture
def repo(tmp_path: Path, roots_dir: tuple[Path, ApprovedExcelRoots]) -> ExcelTaskRepository:
    _, roots = roots_dir
    db_path = tmp_path / "test_worker.db"
    db = DatabaseManager(db_path=db_path)
    db.init_database()
    return ExcelTaskRepository(db, roots)


def test_worker_init_validation(repo: ExcelTaskRepository) -> None:
    with pytest.raises(ValueError, match="repository cannot be None"):
        ExcelTaskWorker(None)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="lease_seconds must be between"):
        ExcelTaskWorker(repo, lease_seconds=10)

    with pytest.raises(ValueError, match="lease_seconds must be between"):
        ExcelTaskWorker(repo, lease_seconds=100000)

    with pytest.raises(ValueError, match="lease_seconds must be between"):
        ExcelTaskWorker(repo, lease_seconds=True)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="renew_interval_seconds must be a positive number"):
        ExcelTaskWorker(repo, renew_interval_seconds=-1.0)

    with pytest.raises(ValueError, match="renew_interval_seconds must be a positive number"):
        ExcelTaskWorker(repo, renew_interval_seconds=0)

    worker = ExcelTaskWorker(repo)
    assert worker._lease_seconds == 900
    assert worker._renew_interval_seconds == 300.0
    assert worker._repository.roots is repo._roots


def test_run_once_no_task_returns_idle(repo: ExcelTaskRepository) -> None:
    executor = FakeExecutor()
    worker = ExcelTaskWorker(repo, executor_factory=executor)
    result = worker.run_once()
    assert isinstance(result, ExcelTaskRunResult)
    assert result.status is ExcelTaskRunStatus.IDLE
    assert result.processed is False
    assert result.succeeded is False
    assert result.task_id is None
    assert result.run_id is None
    assert result.operation is None
    assert result.output_committed is False
    assert len(executor.calls) == 0


def test_dispatch_merge_append_success(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    s1 = root_path / "s1.xlsx"
    s2 = root_path / "s2.xlsx"
    base = root_path / "base.xlsx"
    s1.write_bytes(b"s1")
    s2.write_bytes(b"s2")
    base.write_bytes(b"base")

    ref1 = ExcelTaskFileRef("source", "default", "s1.xlsx", ordinal=0)
    ref2 = ExcelTaskFileRef("source", "default", "s2.xlsx", ordinal=1)
    base_ref = ExcelTaskFileRef("baseline", "default", "base.xlsx", ordinal=0)
    out_ref = ExcelTaskFileRef("output", "default", "out.xlsx", ordinal=0)

    task = repo.create_task("merge_append", [ref1, ref2, base_ref, out_ref], "key_append")
    task_id = task["id"]

    executor = FakeExecutor()
    worker = ExcelTaskWorker(repo, executor_factory=executor)

    result = worker.run_once()
    assert isinstance(result, ExcelTaskRunResult)
    assert result.status is ExcelTaskRunStatus.SUCCEEDED
    assert result.processed is True
    assert result.succeeded is True
    assert result.task_id == task_id
    assert result.operation == "merge_append"
    assert result.output_committed is True
    assert result.error_type is None
    assert result.error_message is None
    assert isinstance(result.artifact_id, int)

    assert len(executor.calls) == 1
    call = executor.calls[0]
    assert call["operation"] == "merge_append"
    assert call["sources"] == [s1.resolve(), s2.resolve()]
    assert call["baseline"] == base.resolve()

    out_file = root_path / "out.xlsx"
    assert out_file.exists()
    assert out_file.read_bytes() == b"fake_merge_append_content"

    # Temporary files should be cleaned up
    tmp_files = list(root_path.glob(".tmp_*"))
    assert tmp_files == []

    updated = repo.get_task(task_id)
    assert updated is not None
    assert updated["status"] == "succeeded"
    assert updated["finished_at"] is not None
    artifacts = repo.list_task_artifacts(task_id)
    assert len(artifacts) == 1
    assert artifacts[0]["id"] == result.artifact_id
    assert artifacts[0]["run_id"] == result.run_id
    assert artifacts[0]["relative_path"] == "out.xlsx"
    assert artifacts[0]["size_bytes"] == len(b"fake_merge_append_content")
    assert artifacts[0]["sha256"] == hashlib.sha256(
        b"fake_merge_append_content"
    ).hexdigest()


def test_dispatch_merge_overlay_success(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    s1 = root_path / "s1.xlsx"
    tgt = root_path / "tgt.xlsx"
    base = root_path / "base.xlsx"
    s1.write_bytes(b"s1")
    tgt.write_bytes(b"tgt")
    base.write_bytes(b"base")

    ref1 = ExcelTaskFileRef("source", "default", "s1.xlsx")
    tgt_ref = ExcelTaskFileRef("target", "default", "tgt.xlsx")
    base_ref = ExcelTaskFileRef("baseline", "default", "base.xlsx")
    out_ref = ExcelTaskFileRef("output", "default", "out_overlay.xlsx")

    task = repo.create_task("merge_overlay", [ref1, tgt_ref, base_ref, out_ref], "key_overlay")
    task_id = task["id"]

    executor = FakeExecutor()
    worker = ExcelTaskWorker(repo, executor_factory=executor)

    result = worker.run_once()
    assert isinstance(result, ExcelTaskRunResult)
    assert result.status is ExcelTaskRunStatus.SUCCEEDED
    assert result.processed is True
    assert result.succeeded is True
    assert result.task_id == task_id
    assert result.operation == "merge_overlay"
    assert result.output_committed is True

    assert len(executor.calls) == 1
    call = executor.calls[0]
    assert call["operation"] == "merge_overlay"
    assert call["sources"] == [s1.resolve()]
    assert call["target"] == tgt.resolve()
    assert call["baseline"] == base.resolve()

    out_file = root_path / "out_overlay.xlsx"
    assert out_file.exists()
    assert out_file.read_bytes() == b"fake_merge_overlay_content"

    updated = repo.get_task(task_id)
    assert updated is not None
    assert updated["status"] == "succeeded"


def test_dispatch_diff_against_baseline_success(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    tgt = root_path / "tgt.xlsx"
    base = root_path / "base.xlsx"
    tgt.write_bytes(b"tgt")
    base.write_bytes(b"base")

    tgt_ref = ExcelTaskFileRef("target", "default", "tgt.xlsx")
    base_ref = ExcelTaskFileRef("baseline", "default", "base.xlsx")
    out_ref = ExcelTaskFileRef("output", "default", "out_diff.xlsx")

    task = repo.create_task("diff_against_baseline", [tgt_ref, base_ref, out_ref], "key_diff")
    task_id = task["id"]

    executor = FakeExecutor()
    worker = ExcelTaskWorker(repo, executor_factory=executor)

    result = worker.run_once()
    assert isinstance(result, ExcelTaskRunResult)
    assert result.status is ExcelTaskRunStatus.SUCCEEDED
    assert result.processed is True
    assert result.succeeded is True
    assert result.task_id == task_id
    assert result.operation == "diff_against_baseline"
    assert result.output_committed is True

    assert len(executor.calls) == 1
    call = executor.calls[0]
    assert call["operation"] == "diff_against_baseline"
    assert call["target"] == tgt.resolve()
    assert call["baseline"] == base.resolve()

    out_file = root_path / "out_diff.xlsx"
    assert out_file.exists()
    assert out_file.read_bytes() == b"fake_diff_content"

    updated = repo.get_task(task_id)
    assert updated is not None
    assert updated["status"] == "succeeded"


def test_revalidation_failure_marks_task_failed(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    s1 = root_path / "s1.xlsx"
    s1.write_bytes(b"s1")

    ref1 = ExcelTaskFileRef("source", "default", "s1.xlsx")
    out_ref = ExcelTaskFileRef("output", "default", "out.xlsx")
    task = repo.create_task("merge_append", [ref1, out_ref], "key_reval_fail")
    task_id = task["id"]

    # Delete source before worker executes task
    s1.unlink()

    executor = FakeExecutor()
    worker = ExcelTaskWorker(repo, executor_factory=executor)

    result = worker.run_once()
    assert isinstance(result, ExcelTaskRunResult)
    assert result.status is ExcelTaskRunStatus.FAILED
    assert result.processed is True
    assert result.succeeded is False
    assert result.task_id == task_id
    assert result.operation == "merge_append"
    assert result.output_committed is False
    assert result.error_type == "ExcelPathSafetyError"
    assert "does not exist" in (result.error_message or "")
    assert len(executor.calls) == 0

    updated = repo.get_task(task_id)
    assert updated is not None
    assert updated["status"] == "failed"
    assert updated["error_type"] == "ExcelPathSafetyError"
    assert "does not exist" in (updated["error_message"] or "")


def test_output_alias_rejection_with_source(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    s1 = root_path / "s1.xlsx"
    s1.write_bytes(b"s1")

    ref1 = ExcelTaskFileRef("source", "default", "s1.xlsx")
    dummy_out = ExcelTaskFileRef("output", "default", "out.xlsx")
    task = repo.create_task("merge_append", [ref1, dummy_out], "key_alias_src")
    task_id = task["id"]

    with repo._db.get_connection() as conn:
        conn.execute(
            "UPDATE excel_task_files SET relative_path = 's1.xlsx' WHERE task_id = ? AND role = 'output'",
            (task_id,),
        )

    executor = FakeExecutor()
    worker = ExcelTaskWorker(repo, executor_factory=executor)

    result = worker.run_once()
    assert isinstance(result, ExcelTaskRunResult)
    assert result.status is ExcelTaskRunStatus.FAILED
    assert result.processed is True
    assert result.succeeded is False
    assert result.task_id == task_id
    assert result.operation == "merge_append"
    assert result.output_committed is False
    assert result.error_type == "ExcelPathSafetyError"
    assert "output path aliases with source file" in (result.error_message or "")
    assert len(executor.calls) == 0

    updated = repo.get_task(task_id)
    assert updated is not None
    assert updated["status"] == "failed"
    assert updated["error_type"] == "ExcelPathSafetyError"
    assert "output path aliases with source file" in (updated["error_message"] or "")


def test_output_alias_rejection_with_baseline(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    s1 = root_path / "s1.xlsx"
    base = root_path / "base.xlsx"
    s1.write_bytes(b"s1")
    base.write_bytes(b"base")

    ref1 = ExcelTaskFileRef("source", "default", "s1.xlsx")
    base_ref = ExcelTaskFileRef("baseline", "default", "base.xlsx")
    dummy_out = ExcelTaskFileRef("output", "default", "out.xlsx")
    task = repo.create_task("merge_append", [ref1, base_ref, dummy_out], "key_alias_base")
    task_id = task["id"]

    with repo._db.get_connection() as conn:
        conn.execute(
            "UPDATE excel_task_files SET relative_path = 'base.xlsx' WHERE task_id = ? AND role = 'output'",
            (task_id,),
        )

    executor = FakeExecutor()
    worker = ExcelTaskWorker(repo, executor_factory=executor)

    result = worker.run_once()
    assert isinstance(result, ExcelTaskRunResult)
    assert result.status is ExcelTaskRunStatus.FAILED
    assert result.processed is True
    assert result.succeeded is False
    assert result.task_id == task_id
    assert result.operation == "merge_append"
    assert result.output_committed is False
    assert result.error_type == "ExcelPathSafetyError"
    assert "output path aliases with baseline file" in (result.error_message or "")
    assert len(executor.calls) == 0

    updated = repo.get_task(task_id)
    assert updated is not None
    assert updated["status"] == "failed"
    assert updated["error_type"] == "ExcelPathSafetyError"
    assert "output path aliases with baseline file" in (updated["error_message"] or "")


def test_merge_overlay_inplace_rejection(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    s1 = root_path / "s1.xlsx"
    tgt = root_path / "tgt.xlsx"
    s1.write_bytes(b"s1")
    tgt.write_bytes(b"tgt")

    ref1 = ExcelTaskFileRef("source", "default", "s1.xlsx")
    tgt_ref = ExcelTaskFileRef("target", "default", "tgt.xlsx")
    dummy_out = ExcelTaskFileRef("output", "default", "out.xlsx")
    task = repo.create_task("merge_overlay", [ref1, tgt_ref, dummy_out], "key_inplace_overlay")
    task_id = task["id"]

    with repo._db.get_connection() as conn:
        conn.execute(
            "UPDATE excel_task_files SET relative_path = 'tgt.xlsx' WHERE task_id = ? AND role = 'output'",
            (task_id,),
        )

    executor = FakeExecutor()
    worker = ExcelTaskWorker(repo, executor_factory=executor)

    result = worker.run_once()
    assert isinstance(result, ExcelTaskRunResult)
    assert result.status is ExcelTaskRunStatus.FAILED
    assert result.processed is True
    assert result.succeeded is False
    assert result.task_id == task_id
    assert result.operation == "merge_overlay"
    assert result.output_committed is False
    assert result.error_type == "ExcelPathSafetyError"
    assert "in-place merge_overlay is not allowed; output cannot equal target" in (result.error_message or "")
    assert len(executor.calls) == 0

    updated = repo.get_task(task_id)
    assert updated is not None
    assert updated["status"] == "failed"
    assert updated["error_type"] == "ExcelPathSafetyError"
    assert "in-place merge_overlay is not allowed; output cannot equal target" in (updated["error_message"] or "")


def test_atomic_replace_and_temp_cleanup_on_executor_failure(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    s1 = root_path / "s1.xlsx"
    s1.write_bytes(b"s1")

    ref1 = ExcelTaskFileRef("source", "default", "s1.xlsx")
    out_ref = ExcelTaskFileRef("output", "default", "out.xlsx")
    task = repo.create_task("merge_append", [ref1, out_ref], "key_fail_cleanup")
    task_id = task["id"]

    executor = FakeExecutor(failure=RuntimeError("Excel COM crash"))
    worker = ExcelTaskWorker(repo, executor_factory=executor)

    result = worker.run_once()
    assert isinstance(result, ExcelTaskRunResult)
    assert result.status is ExcelTaskRunStatus.FAILED
    assert result.processed is True
    assert result.succeeded is False
    assert result.task_id == task_id
    assert result.operation == "merge_append"
    assert result.output_committed is False
    assert result.error_type == "RuntimeError"
    assert "Excel COM crash" in (result.error_message or "")

    updated = repo.get_task(task_id)
    assert updated is not None
    assert updated["status"] == "failed"
    assert updated["error_type"] == "RuntimeError"
    assert "Excel COM crash" in (updated["error_message"] or "")

    # Output file was not created, temp files cleaned up
    assert not (root_path / "out.xlsx").exists()
    assert list(root_path.glob(".tmp_*")) == []


def test_atomic_replace_preserves_existing_output_until_success(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    source = root_path / "source.xlsx"
    output = root_path / "out.xlsx"
    source.write_bytes(b"source")
    output.write_bytes(b"old")

    source_ref = ExcelTaskFileRef("source", "default", source.name)
    output_ref = ExcelTaskFileRef("output", "default", output.name)
    task = repo.create_task("merge_append", [source_ref, output_ref], "key_atomic_replace")
    task_id = task["id"]

    executor = FakeExecutor()
    worker = ExcelTaskWorker(repo, executor_factory=executor)

    result = worker.run_once()
    assert isinstance(result, ExcelTaskRunResult)
    assert result.status is ExcelTaskRunStatus.SUCCEEDED
    assert result.processed is True
    assert result.succeeded is True
    assert result.task_id == task_id
    assert result.operation == "merge_append"
    assert result.output_committed is True

    assert output.read_bytes() == b"fake_merge_append_content"
    assert list(root_path.glob(".tmp_*")) == []


def test_temp_cleanup_when_executor_produces_no_file(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    s1 = root_path / "s1.xlsx"
    s1.write_bytes(b"s1")

    ref1 = ExcelTaskFileRef("source", "default", "s1.xlsx")
    out_ref = ExcelTaskFileRef("output", "default", "out.xlsx")
    task = repo.create_task("merge_append", [ref1, out_ref], "key_no_file")
    task_id = task["id"]

    executor = FakeExecutor(produce_file=False)
    worker = ExcelTaskWorker(repo, executor_factory=executor)

    result = worker.run_once()
    assert isinstance(result, ExcelTaskRunResult)
    assert result.status is ExcelTaskRunStatus.FAILED
    assert result.processed is True
    assert result.succeeded is False
    assert result.task_id == task_id
    assert result.operation == "merge_append"
    assert result.output_committed is False
    assert result.error_type == "FileNotFoundError"

    updated = repo.get_task(task_id)
    assert updated is not None
    assert updated["status"] == "failed"
    assert updated["error_type"] == "FileNotFoundError"


def test_lease_renewal_background_thread(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    s1 = root_path / "s1.xlsx"
    s1.write_bytes(b"s1")

    ref1 = ExcelTaskFileRef("source", "default", "s1.xlsx")
    out_ref = ExcelTaskFileRef("output", "default", "out.xlsx")
    task = repo.create_task("merge_append", [ref1, out_ref], "key_renew_test")
    task_id = task["id"]

    renew_calls: list[tuple[int, int, str]] = []
    orig_renew = repo.renew

    def spy_renew(tid: int, rid: int, token: str, lease_seconds: int = 900) -> str:
        renew_calls.append((tid, rid, token))
        return orig_renew(tid, rid, token, lease_seconds)

    repo.renew = spy_renew  # type: ignore[assignment]

    # Executor delay 0.15s, renew interval 0.04s -> should renew ~2-4 times
    executor = FakeExecutor(delay=0.15)
    worker = ExcelTaskWorker(repo, executor_factory=executor, renew_interval_seconds=0.04)

    result = worker.run_once()
    assert isinstance(result, ExcelTaskRunResult)
    assert result.status is ExcelTaskRunStatus.SUCCEEDED
    assert result.processed is True
    assert result.succeeded is True
    assert result.task_id == task_id
    assert result.operation == "merge_append"
    assert result.output_committed is True
    assert len(renew_calls) >= 1

    updated = repo.get_task(task_id)
    assert updated is not None
    assert updated["status"] == "succeeded"


def test_lease_lost_during_renewal_aborts_finish(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    s1 = root_path / "s1.xlsx"
    s1.write_bytes(b"s1")

    ref1 = ExcelTaskFileRef("source", "default", "s1.xlsx")
    out_ref = ExcelTaskFileRef("output", "default", "out.xlsx")
    task = repo.create_task("merge_append", [ref1, out_ref], "key_lease_lost")
    task_id = task["id"]

    finish_called = False
    orig_finish = repo.finish

    def spy_finish(*args: Any, **kwargs: Any) -> None:
        nonlocal finish_called
        finish_called = True
        orig_finish(*args, **kwargs)

    repo.finish = spy_finish  # type: ignore[assignment]

    # Mock renew to raise ExcelLeaseLostError
    def mock_renew(*args: Any, **kwargs: Any) -> str:
        raise ExcelLeaseLostError("lease stolen by another worker")

    repo.renew = mock_renew  # type: ignore[assignment]

    executor = FakeExecutor(delay=0.08)
    worker = ExcelTaskWorker(repo, executor_factory=executor, renew_interval_seconds=0.02)

    result = worker.run_once()
    assert isinstance(result, ExcelTaskRunResult)
    assert result.status is ExcelTaskRunStatus.LEASE_LOST
    assert result.processed is True
    assert result.succeeded is False
    assert result.task_id == task_id
    assert result.operation == "merge_append"
    assert result.output_committed is False
    assert result.error_type == "ExcelLeaseLostError"
    assert "lease lost" in (result.error_message or "").lower()
    assert finish_called is False

    # Task remains in running state for stale recovery
    raw_task = repo.get_task(task_id)
    assert raw_task is not None
    assert raw_task["status"] == "running"


def test_finish_failure_after_output_committed_returns_failed_without_second_finish(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    s1 = root_path / "s1.xlsx"
    s1.write_bytes(b"s1")

    ref1 = ExcelTaskFileRef("source", "default", "s1.xlsx")
    out_ref = ExcelTaskFileRef("output", "default", "out.xlsx")
    task = repo.create_task("merge_append", [ref1, out_ref], "key_finish_fail")
    task_id = task["id"]

    finish_calls: list[tuple[Any, ...]] = []

    def spy_finish(*args: Any, **kwargs: Any) -> dict[str, Any]:
        finish_calls.append(args)
        raise RuntimeError("database error during finish")

    repo.finish_success_with_artifact = spy_finish  # type: ignore[assignment]

    executor = FakeExecutor()
    worker = ExcelTaskWorker(repo, executor_factory=executor)

    result = worker.run_once()

    assert isinstance(result, ExcelTaskRunResult)
    assert result.status is ExcelTaskRunStatus.FAILED
    assert result.processed is True
    assert result.succeeded is False
    assert result.task_id == task_id
    assert result.operation == "merge_append"
    assert result.output_committed is True
    assert result.error_type == "RuntimeError"
    assert "database error during finish" in (result.error_message or "")

    # Output file was committed to final destination
    assert (root_path / "out.xlsx").exists()
    assert (root_path / "out.xlsx").read_bytes() == b"fake_merge_append_content"

    # Atomic success/artifact finalization was attempted once; no failed finish follows.
    assert len(finish_calls) == 1
    assert finish_calls[0][0] == task_id
    assert finish_calls[0][1] == result.run_id
    assert isinstance(finish_calls[0][3], ExcelTaskArtifactMetadata)


def test_background_renewal_lease_loss_returns_lease_lost(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    s1 = root_path / "s1.xlsx"
    s1.write_bytes(b"s1")

    ref1 = ExcelTaskFileRef("source", "default", "s1.xlsx")
    out_ref = ExcelTaskFileRef("output", "default", "out.xlsx")
    task = repo.create_task("merge_append", [ref1, out_ref], "key_bg_renew_loss")
    task_id = task["id"]

    finish_calls: list[tuple[Any, ...]] = []

    def spy_finish(*args: Any, **kwargs: Any) -> None:
        finish_calls.append(args)

    repo.finish = spy_finish  # type: ignore[assignment]

    def mock_renew(*args: Any, **kwargs: Any) -> str:
        raise ExcelLeaseLostError("lease stolen by another worker")

    repo.renew = mock_renew  # type: ignore[assignment]

    executor = FakeExecutor(delay=0.08)
    worker = ExcelTaskWorker(repo, executor_factory=executor, renew_interval_seconds=0.02)

    result = worker.run_once()

    assert isinstance(result, ExcelTaskRunResult)
    assert result.status is ExcelTaskRunStatus.LEASE_LOST
    assert result.processed is True
    assert result.succeeded is False
    assert result.task_id == task_id
    assert result.operation == "merge_append"
    assert result.output_committed is False
    assert result.error_type == "ExcelLeaseLostError"
    assert "lease lost" in (result.error_message or "").lower()
    assert len(finish_calls) == 0

    # Output file was not committed
    assert not (root_path / "out.xlsx").exists()


def test_keyboard_interrupt_best_effort_finish_and_reraise(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    s1 = root_path / "s1.xlsx"
    s1.write_bytes(b"s1")

    ref1 = ExcelTaskFileRef("source", "default", "s1.xlsx")
    out_ref = ExcelTaskFileRef("output", "default", "out.xlsx")
    task = repo.create_task("merge_append", [ref1, out_ref], "key_interrupt")
    task_id = task["id"]

    executor = FakeExecutor(failure=KeyboardInterrupt("user interrupt"))
    worker = ExcelTaskWorker(repo, executor_factory=executor)

    with pytest.raises(KeyboardInterrupt):
        worker.run_once()

    updated = repo.get_task(task_id)
    assert updated is not None
    assert updated["status"] == "failed"
    assert updated["error_type"] == "KeyboardInterrupt"


def test_base_exception_best_effort_finish_and_reraise(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    s1 = root_path / "s1.xlsx"
    s1.write_bytes(b"s1")

    ref1 = ExcelTaskFileRef("source", "default", "s1.xlsx")
    out_ref = ExcelTaskFileRef("output", "default", "out.xlsx")
    task = repo.create_task("merge_append", [ref1, out_ref], "key_sysexit")
    task_id = task["id"]

    executor = FakeExecutor(failure=SystemExit(2))
    worker = ExcelTaskWorker(repo, executor_factory=executor)

    with pytest.raises(SystemExit) as exc_info:
        worker.run_once()
    assert exc_info.value.code == 2

    updated = repo.get_task(task_id)
    assert updated is not None
    assert updated["status"] == "failed"
    assert updated["error_type"] == "SystemExit"


def test_worker_run_processes_all_queued_tasks(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    s1 = root_path / "s1.xlsx"
    s1.write_bytes(b"s1")

    for i in range(3):
        ref = ExcelTaskFileRef("source", "default", "s1.xlsx")
        out = ExcelTaskFileRef("output", "default", f"out_{i}.xlsx")
        repo.create_task("merge_append", [ref, out], f"key_run_{i}")

    executor = FakeExecutor()
    worker = ExcelTaskWorker(repo, executor_factory=executor)

    summary = worker.run(stop_event=None)
    assert isinstance(summary, ExcelWorkerRunSummary)
    assert summary.processed == 3
    assert summary.succeeded == 3
    assert summary.failed == 0
    assert summary.lease_lost == 0
    assert len(executor.calls) == 3

    # Running again on empty queue returns 0 for all counters
    empty_summary = worker.run(stop_event=None)
    assert isinstance(empty_summary, ExcelWorkerRunSummary)
    assert empty_summary.processed == 0
    assert empty_summary.succeeded == 0
    assert empty_summary.failed == 0
    assert empty_summary.lease_lost == 0


def test_worker_run_with_stop_event(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    s1 = root_path / "s1.xlsx"
    s1.write_bytes(b"s1")

    stop_event = threading.Event()

    class StopTriggerExecutor(FakeExecutor):
        def merge_append(self, sources: list[Path], output_path: Path, baseline: Path | None = None) -> Path:
            res = super().merge_append(sources, output_path, baseline)
            if len(self.calls) == 2:
                stop_event.set()
            return res

    for i in range(5):
        ref = ExcelTaskFileRef("source", "default", "s1.xlsx")
        out = ExcelTaskFileRef("output", "default", f"out_stop_{i}.xlsx")
        repo.create_task("merge_append", [ref, out], f"key_stop_{i}")

    executor = StopTriggerExecutor()
    worker = ExcelTaskWorker(repo, executor_factory=executor)

    summary = worker.run(stop_event=stop_event)
    assert isinstance(summary, ExcelWorkerRunSummary)
    assert summary.processed == 2
    assert summary.succeeded == 2
    assert summary.failed == 0
    assert summary.lease_lost == 0
    assert len(executor.calls) == 2

    # Remaining 3 tasks should still be queued
    queued_tasks = repo.list_tasks(status="queued")
    assert len(queued_tasks) == 3


def test_worker_run_stopped_before_start(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    s1 = root_path / "s1.xlsx"
    s1.write_bytes(b"s1")

    ref = ExcelTaskFileRef("source", "default", "s1.xlsx")
    out = ExcelTaskFileRef("output", "default", "out.xlsx")
    repo.create_task("merge_append", [ref, out], "key_stopped_early")

    stop_event = threading.Event()
    stop_event.set()

    executor = FakeExecutor()
    worker = ExcelTaskWorker(repo, executor_factory=executor)

    summary = worker.run(stop_event=stop_event)
    assert isinstance(summary, ExcelWorkerRunSummary)
    assert summary.processed == 0
    assert summary.succeeded == 0
    assert summary.failed == 0
    assert summary.lease_lost == 0
    assert len(executor.calls) == 0


def test_executor_factory_types(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    s1 = root_path / "s1.xlsx"
    s1.write_bytes(b"s1")

    # 1. As class
    ref = ExcelTaskFileRef("source", "default", "s1.xlsx")
    out1 = ExcelTaskFileRef("output", "default", "out1.xlsx")
    repo.create_task("merge_append", [ref, out1], "key_factory_class")
    worker1 = ExcelTaskWorker(repo, executor_factory=FakeExecutor)
    res1 = worker1.run_once()
    assert isinstance(res1, ExcelTaskRunResult)
    assert res1.status is ExcelTaskRunStatus.SUCCEEDED
    assert res1.succeeded is True

    # 2. As zero-argument callable / lambda
    out2 = ExcelTaskFileRef("output", "default", "out2.xlsx")
    repo.create_task("merge_append", [ref, out2], "key_factory_callable")
    worker2 = ExcelTaskWorker(repo, executor_factory=lambda: FakeExecutor())
    res2 = worker2.run_once()
    assert isinstance(res2, ExcelTaskRunResult)
    assert res2.status is ExcelTaskRunStatus.SUCCEEDED
    assert res2.succeeded is True

    # 3. As instance
    out3 = ExcelTaskFileRef("output", "default", "out3.xlsx")
    repo.create_task("merge_append", [ref, out3], "key_factory_instance")
    worker3 = ExcelTaskWorker(repo, executor_factory=FakeExecutor())
    res3 = worker3.run_once()
    assert isinstance(res3, ExcelTaskRunResult)
    assert res3.status is ExcelTaskRunStatus.SUCCEEDED
    assert res3.succeeded is True


def test_run_continues_after_failed_task(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    source = root_path / "source.xlsx"
    source.write_bytes(b"source")
    source_ref = ExcelTaskFileRef("source", "default", source.name)
    repo.create_task(
        "merge_append",
        [source_ref, ExcelTaskFileRef("output", "default", "failed.xlsx")],
        "key_fail_then_continue_1",
    )
    repo.create_task(
        "merge_append",
        [source_ref, ExcelTaskFileRef("output", "default", "success.xlsx")],
        "key_fail_then_continue_2",
    )

    class FailOnceExecutor(FakeExecutor):
        def merge_append(
            self,
            sources: list[Path],
            output_path: Path,
            baseline: Path | None = None,
        ) -> Path:
            self.failure = RuntimeError("first task failed") if not self.calls else None
            return super().merge_append(sources, output_path, baseline)

    summary = ExcelTaskWorker(repo, executor_factory=FailOnceExecutor()).run()
    assert summary == ExcelWorkerRunSummary(
        processed=2,
        succeeded=1,
        failed=1,
        lease_lost=0,
    )
    assert not (root_path / "failed.xlsx").exists()
    assert (root_path / "success.xlsx").exists()


def test_multiple_processes_lease_one_task_exclusively(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    source = root_path / "source.xlsx"
    source.write_bytes(b"source")
    task = repo.create_task(
        "merge_append",
        [
            ExcelTaskFileRef("source", "default", source.name),
            ExcelTaskFileRef("output", "default", "output.xlsx"),
        ],
        "key_process_exclusive_lease",
    )

    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_lease_from_process,
            args=(str(repo._db.db_path), str(root_path), start_event, result_queue),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    start_event.set()
    results = [result_queue.get(timeout=30) for _ in processes]
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0
    result_queue.close()

    assert results.count(task["id"]) == 1
    assert results.count(None) == 1
