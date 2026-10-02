# -*- coding: utf-8 -*-
"""
tests/test_excel_tasks.py — Excel Phase A 核心任务功能单元测试与契约验证
"""

import hashlib
import json
import sqlite3
import threading
from pathlib import Path

import pytest

from core.db_manager import DatabaseManager
from core.excel_tasks import (
    ApprovedExcelRoots,
    ExcelIdempotencyConflictError,
    ExcelInvalidStateError,
    ExcelLeaseLostError,
    ExcelPathSafetyError,
    ExcelTaskArtifactMetadata,
    ExcelTaskFileRef,
    ExcelTaskRepository,
    compute_request_fingerprint,
    load_production_excel_roots,
    parse_excel_roots_json,
    validate_task_request,
)


def _start_artifact_task(
    root_path: Path,
    repo: ExcelTaskRepository,
    key: str,
) -> tuple[int, int, str, ExcelTaskFileRef, bytes]:
    source = root_path / f"{key}_source.xlsx"
    output = root_path / f"{key}_output.xlsx"
    source.write_bytes(b"source")
    output_bytes = f"artifact:{key}".encode("utf-8")
    output_ref = ExcelTaskFileRef("output", "default", output.name)
    task = repo.create_task(
        "merge_append",
        [ExcelTaskFileRef("source", "default", source.name), output_ref],
        key,
    )
    lease = repo.lease_next(lease_seconds=300)
    assert lease is not None
    repo.start(lease["task_id"], lease["run_id"], lease["lease_token"])
    output.write_bytes(output_bytes)
    return (
        int(task["id"]),
        int(lease["run_id"]),
        str(lease["lease_token"]),
        output_ref,
        output_bytes,
    )


@pytest.fixture
def roots_dir(tmp_path: Path) -> tuple[Path, ApprovedExcelRoots]:
    root_path = tmp_path / "excel_root"
    root_path.mkdir(parents=True, exist_ok=True)
    roots = ApprovedExcelRoots({"default": root_path})
    return root_path, roots


@pytest.fixture
def repo(tmp_path: Path, roots_dir: tuple[Path, ApprovedExcelRoots]) -> ExcelTaskRepository:
    _, roots = roots_dir
    db_path = tmp_path / "test_excel.db"
    db = DatabaseManager(db_path=db_path)
    db.init_database()
    return ExcelTaskRepository(db, roots)


# ── ApprovedExcelRoots & Path Safety Tests ──────────────────────
def test_approved_roots_init_validation(tmp_path: Path) -> None:
    with pytest.raises(ExcelPathSafetyError):
        ApprovedExcelRoots({})

    with pytest.raises(ExcelPathSafetyError):
        ApprovedExcelRoots({"non_existent": tmp_path / "does_not_exist"})

    with pytest.raises(ExcelPathSafetyError):
        ApprovedExcelRoots({"CON": tmp_path})

    with pytest.raises(ExcelPathSafetyError):
        ApprovedExcelRoots({"invalid/name": tmp_path})


def test_approved_roots_path_normalization(roots_dir: tuple[Path, ApprovedExcelRoots]) -> None:
    _, roots = roots_dir

    valid = roots.normalize_relative_path("sub/folder/file.xlsx")
    assert valid == "sub/folder/file.xlsx"

    # Backslash
    with pytest.raises(ExcelPathSafetyError):
        roots.normalize_relative_path("sub\file.xlsx")

    # Colon / drive
    with pytest.raises(ExcelPathSafetyError):
        roots.normalize_relative_path("C:/file.xlsx")

    with pytest.raises(ExcelPathSafetyError):
        roots.normalize_relative_path("file:stream.xlsx")

    # Absolute
    with pytest.raises(ExcelPathSafetyError):
        roots.normalize_relative_path("/root/file.xlsx")

    # Traversal
    with pytest.raises(ExcelPathSafetyError):
        roots.normalize_relative_path("../file.xlsx")

    with pytest.raises(ExcelPathSafetyError):
        roots.normalize_relative_path("sub/../../file.xlsx")

    with pytest.raises(ExcelPathSafetyError):
        roots.normalize_relative_path("./file.xlsx")

    # Trailing dot/space
    with pytest.raises(ExcelPathSafetyError):
        roots.normalize_relative_path("file.xlsx ")

    with pytest.raises(ExcelPathSafetyError):
        roots.normalize_relative_path("sub./file.xlsx")

    # Windows reserved device names
    with pytest.raises(ExcelPathSafetyError):
        roots.normalize_relative_path("CON.xlsx")

    with pytest.raises(ExcelPathSafetyError):
        roots.normalize_relative_path("sub/NUL.xlsx")

    with pytest.raises(ExcelPathSafetyError):
        roots.normalize_relative_path("com1.xlsx")

    # Extension restrictions
    with pytest.raises(ExcelPathSafetyError):
        roots.normalize_relative_path("file.xlsm")

    with pytest.raises(ExcelPathSafetyError):
        roots.normalize_relative_path("file.csv")

    with pytest.raises(ExcelPathSafetyError):
        roots.normalize_relative_path("file.txt")

    # Case-insensitive valid extensions
    assert roots.normalize_relative_path("file.XLSX") == "file.XLSX"
    assert roots.normalize_relative_path("file.XLS") == "file.XLS"


def test_approved_roots_resolve_ref(roots_dir: tuple[Path, ApprovedExcelRoots]) -> None:
    root_path, roots = roots_dir
    src_file = root_path / "source.xlsx"
    src_file.write_bytes(b"dummy")

    ref = ExcelTaskFileRef(role="source", root_id="default", relative_path="source.xlsx")
    resolved = roots.resolve_ref(ref)
    assert resolved == src_file.resolve()

    # Missing input file
    missing_ref = ExcelTaskFileRef(role="source", root_id="default", relative_path="missing.xlsx")
    with pytest.raises(ExcelPathSafetyError):
        roots.resolve_ref(missing_ref)

    # Output file: absent is fine if parent exists
    out_ref = ExcelTaskFileRef(role="output", root_id="default", relative_path="out.xlsx")
    out_resolved = roots.resolve_ref(out_ref)
    assert out_resolved == (root_path / "out.xlsx").resolve()

    # Output file: parent does not exist
    out_missing_parent = ExcelTaskFileRef(role="output", root_id="default", relative_path="non_dir/out.xlsx")
    with pytest.raises(ExcelPathSafetyError):
        roots.resolve_ref(out_missing_parent)


def test_approved_roots_reparse_detection(
    monkeypatch: pytest.MonkeyPatch, roots_dir: tuple[Path, ApprovedExcelRoots]
) -> None:
    root_path, roots = roots_dir
    src_file = root_path / "sym_source.xlsx"
    src_file.write_bytes(b"data")

    # Mock _is_reparse to simulate symlink / reparse point detection
    monkeypatch.setattr(ApprovedExcelRoots, "_is_reparse", staticmethod(lambda path: True))

    ref = ExcelTaskFileRef(role="source", root_id="default", relative_path="sym_source.xlsx")
    with pytest.raises(ExcelPathSafetyError) as exc_info:
        roots.resolve_ref(ref)
    assert "reparse point detected" in str(exc_info.value)


def test_path_resolution_does_not_mutate_filesystem(
    roots_dir: tuple[Path, ApprovedExcelRoots],
) -> None:
    root_path, roots = roots_dir
    out_ref = ExcelTaskFileRef(role="output", root_id="default", relative_path="non_existing_out.xlsx")
    resolved = roots.resolve_ref(out_ref)
    assert not resolved.exists()
    assert list(root_path.iterdir()) == []


def test_reparse_intermediate_components_rejection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root_path = tmp_path / "root"
    root_path.mkdir()
    sub_dir = root_path / "sub"
    sub_dir.mkdir()
    (sub_dir / "file.xlsx").write_bytes(b"data")

    # Simulate intermediate parent being a reparse point
    def fake_is_reparse(p: Path) -> bool:
        return p.resolve() == sub_dir.resolve()

    monkeypatch.setattr(ApprovedExcelRoots, "_is_reparse", staticmethod(fake_is_reparse))

    roots = ApprovedExcelRoots({"default": root_path})
    ref = ExcelTaskFileRef(role="source", root_id="default", relative_path="sub/file.xlsx")

    with pytest.raises(ExcelPathSafetyError) as exc_info:
        roots.resolve_ref(ref)
    assert "reparse point detected in parent path" in str(exc_info.value)


# ── Operation Contracts Tests ───────────────────────────────────
def test_validate_task_request_contracts() -> None:
    src = ExcelTaskFileRef(role="source", root_id="default", relative_path="s1.xlsx", ordinal=0)
    src2 = ExcelTaskFileRef(role="source", root_id="default", relative_path="s2.xlsx", ordinal=1)
    tgt = ExcelTaskFileRef(role="target", root_id="default", relative_path="tgt.xlsx", ordinal=0)
    base = ExcelTaskFileRef(role="baseline", root_id="default", relative_path="base.xlsx", ordinal=0)
    out = ExcelTaskFileRef(role="output", root_id="default", relative_path="out.xlsx", ordinal=0)

    # 1. merge_append
    validate_task_request("merge_append", [src, out])
    validate_task_request("merge_append", [src, src2, base, out])
    # Invalid: no source
    with pytest.raises(ValueError):
        validate_task_request("merge_append", [out])
    # Invalid: has target
    with pytest.raises(ValueError):
        validate_task_request("merge_append", [src, tgt, out])

    # 2. merge_overlay
    validate_task_request("merge_overlay", [src, tgt, out])
    validate_task_request("merge_overlay", [src, src2, tgt, base, out])
    # Invalid: missing target
    with pytest.raises(ValueError):
        validate_task_request("merge_overlay", [src, out])

    # 3. diff_against_baseline
    validate_task_request("diff_against_baseline", [tgt, base, out])
    # Invalid: has source
    with pytest.raises(ValueError):
        validate_task_request("diff_against_baseline", [src, tgt, base, out])
    # Invalid: missing baseline
    with pytest.raises(ValueError):
        validate_task_request("diff_against_baseline", [tgt, out])

    # Duplicate ordinals
    src_dup = ExcelTaskFileRef(role="source", root_id="default", relative_path="s2.xlsx", ordinal=0)
    with pytest.raises(ValueError):
        validate_task_request("merge_append", [src, src_dup, out])

    # Non-empty options rejected in Phase A
    with pytest.raises(ValueError):
        validate_task_request("merge_append", [src, out], options={"unsupported": True})

    # Invalid max_attempts
    with pytest.raises(ValueError):
        validate_task_request("merge_append", [src, out], max_attempts=0)
    with pytest.raises(ValueError):
        validate_task_request("merge_append", [src, out], max_attempts=6)


# ── Idempotency & Request Fingerprint Tests ─────────────────────
def test_compute_request_fingerprint_sensitivity() -> None:
    ref1 = ExcelTaskFileRef(role="source", root_id="default", relative_path="s1.xlsx", ordinal=0)
    ref2 = ExcelTaskFileRef(role="source", root_id="default", relative_path="s2.xlsx", ordinal=1)
    out = ExcelTaskFileRef(role="output", root_id="default", relative_path="out.xlsx", ordinal=0)

    fp1 = compute_request_fingerprint("merge_append", [ref1, ref2, out])
    # Fingerprint is invariant to input list ordering (canonicalized by role, ordinal)
    fp2 = compute_request_fingerprint("merge_append", [out, ref2, ref1])
    assert fp1 == fp2

    # Fingerprint changes if operation changes
    fp3 = compute_request_fingerprint("merge_overlay", [ref1, ref2, out])
    assert fp1 != fp3


def test_create_task_idempotency_and_conflict(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    (root_path / "s1.xlsx").write_bytes(b"data1")
    (root_path / "s2.xlsx").write_bytes(b"data2")

    ref1 = ExcelTaskFileRef(role="source", root_id="default", relative_path="s1.xlsx", ordinal=0)
    ref2 = ExcelTaskFileRef(role="source", root_id="default", relative_path="s2.xlsx", ordinal=0)
    out_ref = ExcelTaskFileRef(role="output", root_id="default", relative_path="out.xlsx", ordinal=0)

    task1 = repo.create_task("merge_append", [ref1, out_ref], idempotency_key="key_123")
    assert task1["id"] is not None
    assert task1["status"] == "queued"

    # Replay with exact same parameters -> returns same task
    task1_replay = repo.create_task("merge_append", [ref1, out_ref], idempotency_key="key_123")
    assert task1_replay["id"] == task1["id"]
    assert task1_replay["request_fingerprint"] == task1["request_fingerprint"]

    # Replay with same key but different request -> raises ExcelIdempotencyConflictError
    with pytest.raises(ExcelIdempotencyConflictError):
        repo.create_task("merge_append", [ref2, out_ref], idempotency_key="key_123")


def test_no_raw_idempotency_or_lease_in_reads(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    (root_path / "s1.xlsx").write_bytes(b"data")
    ref = ExcelTaskFileRef(role="source", root_id="default", relative_path="s1.xlsx", ordinal=0)
    out = ExcelTaskFileRef(role="output", root_id="default", relative_path="out.xlsx", ordinal=0)

    raw_key = "secret_raw_idempotency_key_456"
    task = repo.create_task("merge_append", [ref, out], idempotency_key=raw_key)

    # get_task
    fetched = repo.get_task(task["id"])
    assert fetched is not None
    assert "lease_token" not in fetched
    assert raw_key not in json.dumps(fetched, default=str)
    assert hashlib.sha256(raw_key.encode("utf-8")).hexdigest() not in json.dumps(fetched, default=str)

    # list_tasks
    tasks_list = repo.list_tasks()
    assert len(tasks_list) >= 1
    assert "lease_token" not in tasks_list[0]
    assert raw_key not in json.dumps(tasks_list[0], default=str)


def test_idempotent_replay_after_input_deleted(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    s1 = root_path / "s1.xlsx"
    s1.write_bytes(b"data")
    ref = ExcelTaskFileRef(role="source", root_id="default", relative_path="s1.xlsx")
    out = ExcelTaskFileRef(role="output", root_id="default", relative_path="out.xlsx")

    task1 = repo.create_task("merge_append", [ref, out], idempotency_key="key_replay_del")

    # Delete input file from filesystem
    s1.unlink()
    assert not s1.exists()

    # Replay with exact same parameters must succeed and return original task
    task1_replay = repo.create_task("merge_append", [ref, out], idempotency_key="key_replay_del")
    assert task1_replay["id"] == task1["id"]
    assert task1_replay["request_fingerprint"] == task1["request_fingerprint"]

    # Replay with same key but different parameters must raise conflict
    tgt_ref = ExcelTaskFileRef(role="target", root_id="default", relative_path="tgt.xlsx")
    base_ref = ExcelTaskFileRef(role="baseline", root_id="default", relative_path="base.xlsx")
    with pytest.raises(ExcelIdempotencyConflictError):
        repo.create_task(
            "diff_against_baseline",
            [tgt_ref, base_ref, out],
            idempotency_key="key_replay_del",
        )


# ── Cascading Deletion Tests ────────────────────────────────────
def test_cascading_deletion(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    (root_path / "s1.xlsx").write_bytes(b"data")
    ref = ExcelTaskFileRef(role="source", root_id="default", relative_path="s1.xlsx", ordinal=0)
    out = ExcelTaskFileRef(role="output", root_id="default", relative_path="out.xlsx", ordinal=0)

    task = repo.create_task("merge_append", [ref, out], idempotency_key="cascade_test")
    tid = task["id"]

    lease = repo.lease_next()
    assert lease is not None

    with repo._db.get_connection() as conn:
        files = conn.execute("SELECT COUNT(*) FROM excel_task_files WHERE task_id = ?", (tid,)).fetchone()[0]
        runs = conn.execute("SELECT COUNT(*) FROM excel_task_runs WHERE task_id = ?", (tid,)).fetchone()[0]
        assert files == 2
        assert runs == 1

        # Delete parent task
        conn.execute("DELETE FROM excel_tasks WHERE id = ?", (tid,))

        # Verify cascade
        files_after = conn.execute("SELECT COUNT(*) FROM excel_task_files WHERE task_id = ?", (tid,)).fetchone()[0]
        runs_after = conn.execute("SELECT COUNT(*) FROM excel_task_runs WHERE task_id = ?", (tid,)).fetchone()[0]
        assert files_after == 0
        assert runs_after == 0


# ── Lifecycle State Machine & Leases Tests ──────────────────────
def test_lease_start_renew_finish_lifecycle(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    (root_path / "s1.xlsx").write_bytes(b"data")
    ref = ExcelTaskFileRef(role="source", root_id="default", relative_path="s1.xlsx", ordinal=0)
    out = ExcelTaskFileRef(role="output", root_id="default", relative_path="out.xlsx", ordinal=0)

    task = repo.create_task("merge_append", [ref, out], idempotency_key="lifecycle_test_1")

    # 1. Lease task
    lease_info = repo.lease_next(lease_seconds=300)
    assert lease_info is not None
    assert lease_info["task_id"] == task["id"]
    assert lease_info["attempt"] == 1
    assert lease_info["lease_token"] is not None
    run_id = lease_info["run_id"]
    token = lease_info["lease_token"]

    task_read = repo.get_task(task["id"])
    assert task_read["status"] == "leased"

    # Second lease_next finds nothing
    assert repo.lease_next() is None

    # 2. Invalid start with wrong token or run_id
    with pytest.raises(ExcelLeaseLostError):
        repo.start(task["id"], run_id, "wrong_token")

    with pytest.raises(ExcelLeaseLostError):
        repo.start(task["id"], 99999, token)

    # 3. Start task -> moves to running
    repo.start(task["id"], run_id, token)
    task_read = repo.get_task(task["id"])
    assert task_read["status"] == "running"
    assert task_read["started_at"] is not None

    # Cannot start again while running
    with pytest.raises(ExcelInvalidStateError):
        repo.start(task["id"], run_id, token)

    # 4. Renew lease
    new_expires = repo.renew(task["id"], run_id, token, lease_seconds=600)
    assert new_expires is not None

    # 5. Finish task with error redaction
    sensitive_error = "Authorization: Bearer my_secret_token_123 failed to connect"
    repo.finish(
        task["id"],
        run_id,
        token,
        "failed",
        error_type="AuthError",
        error_message=sensitive_error,
    )

    final_task = repo.get_task(task["id"])
    assert final_task["status"] == "failed"
    assert "my_secret_token_123" not in final_task["error_message"]
    assert "[redacted]" in final_task["error_message"]
    assert final_task["finished_at"] is not None

    # Runs history
    runs = repo.list_task_runs(task["id"])
    assert len(runs) == 1
    assert runs[0]["run_state"] == "failed"
    assert "[redacted]" in runs[0]["error_message"]

    # Cannot renew or finish already finalized task
    with pytest.raises(ExcelInvalidStateError):
        repo.renew(task["id"], run_id, token)

    with pytest.raises(ExcelInvalidStateError):
        repo.finish(task["id"], run_id, token, "succeeded")


def test_lease_renewal_vs_stale_recovery_race(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    (root_path / "s1.xlsx").write_bytes(b"data")
    ref = ExcelTaskFileRef(role="source", root_id="default", relative_path="s1.xlsx")
    out = ExcelTaskFileRef(role="output", root_id="default", relative_path="out.xlsx")

    task = repo.create_task("merge_append", [ref, out], idempotency_key="race_test", max_attempts=3)
    lease1 = repo.lease_next(lease_seconds=60)
    assert lease1 is not None
    token1 = lease1["lease_token"]
    run_id_1 = lease1["run_id"]

    # Stale recovery reclaims task into queued and issues attempt 2
    with repo._db.get_connection() as conn:
        conn.execute(
            "UPDATE excel_tasks SET lease_expires_at = '2000-01-01T00:00:00.000Z' WHERE id = ?",
            (task["id"],),
        )

    lease2 = repo.lease_next(lease_seconds=300)
    assert lease2 is not None
    assert lease2["attempt"] == 2
    token2 = lease2["lease_token"]

    # Old holder of attempt 1 cannot renew, start, or finish
    with pytest.raises((ExcelInvalidStateError, ExcelLeaseLostError)):
        repo.renew(task["id"], run_id_1, token1)

    with pytest.raises((ExcelInvalidStateError, ExcelLeaseLostError)):
        repo.start(task["id"], run_id_1, token1)

    with pytest.raises((ExcelInvalidStateError, ExcelLeaseLostError)):
        repo.finish(task["id"], run_id_1, token1, "succeeded")

    # Verify attempt 2 remains intact
    task_curr = repo.get_task(task["id"])
    assert task_curr["status"] == "leased"
    assert task_curr["attempt_count"] == 2

    runs = repo.list_task_runs(task["id"])
    assert runs[0]["run_state"] == "expired"
    assert runs[1]["run_state"] == "leased"

    # Holder 2 can finish successfully
    repo.start(task["id"], lease2["run_id"], token2)
    repo.finish(task["id"], lease2["run_id"], token2, "succeeded")
    final_task = repo.get_task(task["id"])
    assert final_task["status"] == "succeeded"


def test_cas_failure_leaves_database_unmutated(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    (root_path / "s1.xlsx").write_bytes(b"data")
    ref = ExcelTaskFileRef(role="source", root_id="default", relative_path="s1.xlsx")
    out = ExcelTaskFileRef(role="output", root_id="default", relative_path="out.xlsx")

    task = repo.create_task("merge_append", [ref, out], idempotency_key="cas_unmutated")
    lease = repo.lease_next(lease_seconds=300)
    assert lease is not None
    run_id = lease["run_id"]

    # 1. Invalid start token
    with pytest.raises(ExcelLeaseLostError):
        repo.start(task["id"], run_id, "wrong_token")

    task_read = repo.get_task(task["id"])
    assert task_read["status"] == "leased"
    assert task_read["started_at"] is None

    # 2. A leased task cannot skip start and move directly to a terminal state.
    with pytest.raises(ExcelInvalidStateError):
        repo.finish(task["id"], run_id, lease["lease_token"], "failed")

    repo.start(task["id"], run_id, lease["lease_token"])

    # 3. Invalid finish token cannot mutate the running task or run.
    with pytest.raises(ExcelLeaseLostError):
        repo.finish(task["id"], run_id, "wrong_token", "failed", error_message="should not persist")

    task_read = repo.get_task(task["id"])
    assert task_read["status"] == "running"
    assert task_read["finished_at"] is None
    assert task_read["error_message"] is None

    runs = repo.list_task_runs(task["id"])
    assert runs[0]["run_state"] == "running"
    assert runs[0]["error_message"] is None


def test_stale_recovery_requires_matching_active_run(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    (root_path / "source.xlsx").write_bytes(b"data")
    ref = ExcelTaskFileRef("source", "default", "source.xlsx")
    out = ExcelTaskFileRef("output", "default", "output.xlsx")
    task = repo.create_task(
        "merge_append", [ref, out], "missing-active-run", max_attempts=2
    )
    lease = repo.lease_next(lease_seconds=60)
    assert lease is not None

    with repo._db.get_connection() as conn:
        conn.execute("DELETE FROM excel_task_runs WHERE id = ?", (lease["run_id"],))
        conn.execute(
            "UPDATE excel_tasks SET lease_expires_at = "
            "'2000-01-01T00:00:00.000Z' WHERE id = ?",
            (task["id"],),
        )

    with pytest.raises(ExcelInvalidStateError, match="exactly one active run"):
        repo.lease_next()

    unchanged = repo.get_task(task["id"])
    assert unchanged is not None
    assert unchanged["status"] == "leased"
    assert unchanged["attempt_count"] == 1


# ── Stale Recovery & Retry Exhaustion Tests ─────────────────────
def test_stale_recovery_requeue_and_exhaustion(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    (root_path / "s1.xlsx").write_bytes(b"data")
    ref = ExcelTaskFileRef(role="source", root_id="default", relative_path="s1.xlsx", ordinal=0)
    out = ExcelTaskFileRef(role="output", root_id="default", relative_path="out.xlsx", ordinal=0)

    # Create task with max_attempts = 2
    task = repo.create_task("merge_append", [ref, out], idempotency_key="stale_test", max_attempts=2)

    # Attempt 1: Lease
    lease1 = repo.lease_next(lease_seconds=60)
    assert lease1 is not None
    assert lease1["attempt"] == 1

    # Simulate expired lease in database (attempts < max_attempts branch: requeue)
    with repo._db.get_connection() as conn:
        conn.execute(
            "UPDATE excel_tasks SET lease_expires_at = '2000-01-01T00:00:00.000Z' WHERE id = ?",
            (task["id"],),
        )

    # Next lease_next should reclaim stale task, mark run 1 expired, and requeue/re-lease as attempt 2
    lease2 = repo.lease_next(lease_seconds=60)
    assert lease2 is not None
    assert lease2["task_id"] == task["id"]
    assert lease2["attempt"] == 2

    # Verify run 1 is expired and run 2 is leased
    runs = repo.list_task_runs(task["id"])
    assert len(runs) == 2
    assert runs[0]["run_state"] == "expired"
    assert runs[1]["run_state"] == "leased"

    # Simulate expired lease on attempt 2 (attempts >= max_attempts branch: exhaustion / permanent failure)
    with repo._db.get_connection() as conn:
        conn.execute(
            "UPDATE excel_tasks SET lease_expires_at = '2000-01-01T00:00:00.000Z' WHERE id = ?",
            (task["id"],),
        )

    # Next lease_next should permanently fail the exhausted task
    lease3 = repo.lease_next()
    assert lease3 is None

    final_task = repo.get_task(task["id"])
    assert final_task["status"] == "failed"
    assert final_task["error_type"] == "LeaseExpired"
    assert "exceeded maximum retry attempts" in final_task["error_message"]
    assert final_task["finished_at"] is not None

    runs = repo.list_task_runs(task["id"])
    assert len(runs) == 2
    assert runs[0]["run_state"] == "expired"
    assert runs[1]["run_state"] == "expired"
    assert runs[1]["error_type"] == "LeaseExpired"


def test_stale_recovery_running_state_requeue_and_exhaustion(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    (root_path / "s1.xlsx").write_bytes(b"data")
    ref = ExcelTaskFileRef(role="source", root_id="default", relative_path="s1.xlsx")
    out = ExcelTaskFileRef(role="output", root_id="default", relative_path="out.xlsx")

    # 1. Requeue branch from running state
    task = repo.create_task("merge_append", [ref, out], idempotency_key="running_stale_test", max_attempts=2)
    lease1 = repo.lease_next(lease_seconds=60)
    assert lease1 is not None
    repo.start(task["id"], lease1["run_id"], lease1["lease_token"])

    curr_task = repo.get_task(task["id"])
    assert curr_task["status"] == "running"

    # Expire lease in running state
    with repo._db.get_connection() as conn:
        conn.execute(
            "UPDATE excel_tasks SET lease_expires_at = '2000-01-01T00:00:00.000Z' WHERE id = ?",
            (task["id"],),
        )

    # Next lease_next should recover the running task into queued, mark run 1 expired, and lease as attempt 2
    lease2 = repo.lease_next(lease_seconds=60)
    assert lease2 is not None
    assert lease2["task_id"] == task["id"]
    assert lease2["attempt"] == 2

    runs = repo.list_task_runs(task["id"])
    assert len(runs) == 2
    assert runs[0]["run_state"] == "expired"
    assert runs[1]["run_state"] == "leased"

    # 2. Exhaustion branch from running state (attempt 2 reached max_attempts=2)
    repo.start(task["id"], lease2["run_id"], lease2["lease_token"])
    with repo._db.get_connection() as conn:
        conn.execute(
            "UPDATE excel_tasks SET lease_expires_at = '2000-01-01T00:00:00.000Z' WHERE id = ?",
            (task["id"],),
        )

    lease3 = repo.lease_next()
    assert lease3 is None

    final_task = repo.get_task(task["id"])
    assert final_task["status"] == "failed"
    assert final_task["error_type"] == "LeaseExpired"
    assert "exceeded maximum retry attempts" in final_task["error_message"]
    assert final_task["finished_at"] is not None

    runs = repo.list_task_runs(task["id"])
    assert len(runs) == 2
    assert runs[0]["run_state"] == "expired"
    assert runs[1]["run_state"] == "expired"
    assert runs[1]["error_type"] == "LeaseExpired"


# ── Canonical Unicode & Root Collision Tests ────────────────────
def test_canonical_root_collision_and_bounds(tmp_path: Path) -> None:
    p1 = tmp_path / "root1"
    p2 = tmp_path / "root2"
    p1.mkdir()
    p2.mkdir()

    # Collision after NFKC normalization
    with pytest.raises(ExcelPathSafetyError) as exc_info:
        ApprovedExcelRoots({"root_1": p1, "ｒｏｏｔ_1": p2})
    assert "duplicate or colliding canonical root_id" in str(exc_info.value)

    # Length bounds
    with pytest.raises(ExcelPathSafetyError):
        ApprovedExcelRoots.canonicalize_root_id("a" * 129)

    with pytest.raises(ExcelPathSafetyError):
        ApprovedExcelRoots.normalize_relative_path("a/" * 513 + "file.xlsx")


def test_canonical_unicode_path_and_root_persistence(tmp_path: Path) -> None:
    root_path = tmp_path / "unicode_root"
    root_path.mkdir()
    sub = root_path / "sub"
    sub.mkdir()
    (sub / "file.xlsx").write_bytes(b"excel_data")

    # Fullwidth "default" -> "ｄｅｆａｕｌｔ"
    fullwidth_root = "ｄｅｆａｕｌｔ"
    fullwidth_rel = "sub/ｆｉｌｅ.xlsx"

    roots = ApprovedExcelRoots({fullwidth_root: root_path})
    assert roots.root_ids == ("default",)

    ref = ExcelTaskFileRef(role="source", root_id=fullwidth_root, relative_path=fullwidth_rel)
    assert ref.root_id == "default"
    assert ref.relative_path == "sub/file.xlsx"

    out_ref = ExcelTaskFileRef(role="output", root_id="default", relative_path="out.xlsx")

    db = DatabaseManager(db_path=tmp_path / "db_unicode.db")
    db.init_database()
    repo = ExcelTaskRepository(db, roots)

    task = repo.create_task("merge_append", [ref, out_ref], idempotency_key="unicode_key")
    src_file = next(f for f in task["files"] if f.role == "source")
    out_file = next(f for f in task["files"] if f.role == "output")
    assert src_file.root_id == "default"
    assert src_file.relative_path == "sub/file.xlsx"
    assert out_file.root_id == "default"
    assert out_file.relative_path == "out.xlsx"

    # get_task returns canonical strings
    read_task = repo.get_task(task["id"])
    assert read_task is not None
    read_src = next(f for f in read_task["files"] if f.role == "source")
    assert read_src.root_id == "default"
    assert read_src.relative_path == "sub/file.xlsx"


# ── Concurrency & CAS Integrity Tests ───────────────────────────
def test_concurrent_task_creation_idempotency(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    import concurrent.futures

    root_path, _ = roots_dir
    (root_path / "s1.xlsx").write_bytes(b"data")
    ref = ExcelTaskFileRef(role="source", root_id="default", relative_path="s1.xlsx")
    out = ExcelTaskFileRef(role="output", root_id="default", relative_path="out.xlsx")

    def create() -> int:
        res = repo.create_task("merge_append", [ref, out], idempotency_key="concurrent_key_1")
        return int(res["id"])

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: create(), range(8)))

    assert len(set(results)) == 1, "All concurrent creation requests should return the same task ID"
    with repo._db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM excel_tasks").fetchone()[0]
        assert count == 1


def test_concurrent_task_leasing_mutual_exclusion(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    import concurrent.futures

    root_path, _ = roots_dir
    (root_path / "s1.xlsx").write_bytes(b"data")
    ref = ExcelTaskFileRef(role="source", root_id="default", relative_path="s1.xlsx")
    out = ExcelTaskFileRef(role="output", root_id="default", relative_path="out.xlsx")

    repo.create_task("merge_append", [ref, out], idempotency_key="single_task")

    def lease() -> dict | None:
        return repo.lease_next(lease_seconds=300)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: lease(), range(8)))

    non_none = [r for r in results if r is not None]
    assert len(non_none) == 1, "Exactly one thread must acquire the lease"


# ── Deterministic Concurrency & Write Lock Tests ────────────────
def test_begin_immediate_seam_invoked_on_create_and_lease(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    (root_path / "s1.xlsx").write_bytes(b"data")
    ref = ExcelTaskFileRef(role="source", root_id="default", relative_path="s1.xlsx")
    out = ExcelTaskFileRef(role="output", root_id="default", relative_path="out.xlsx")

    called_count = 0
    orig_begin = repo._begin_immediate

    def tracking_begin(conn: sqlite3.Connection) -> None:
        nonlocal called_count
        called_count += 1
        orig_begin(conn)

    repo._begin_immediate = tracking_begin

    task = repo.create_task("merge_append", [ref, out], idempotency_key="seam_track_key")
    assert called_count == 1
    assert task["status"] == "queued"

    # Replay does not perform insert transaction, so _begin_immediate is not called again
    repo.create_task("merge_append", [ref, out], idempotency_key="seam_track_key")
    assert called_count == 1

    lease = repo.lease_next()
    assert lease is not None
    assert called_count == 2


def test_deterministic_concurrent_identical_create_task_serialization(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    (root_path / "s1.xlsx").write_bytes(b"data")
    ref = ExcelTaskFileRef(role="source", root_id="default", relative_path="s1.xlsx")
    out = ExcelTaskFileRef(role="output", root_id="default", relative_path="out.xlsx")

    barrier = threading.Barrier(4)
    orig_begin = repo._begin_immediate

    def hooked_begin(conn: sqlite3.Connection) -> None:
        barrier.wait(timeout=5)
        orig_begin(conn)

    repo._begin_immediate = hooked_begin

    results: list[dict] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            res = repo.create_task("merge_append", [ref, out], idempotency_key="det_identical_key")
            with lock:
                results.append(res)
        except Exception as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"Unexpected errors during concurrent identical creation: {errors}"
    assert len(results) == 4
    task_ids = {r["id"] for r in results}
    assert len(task_ids) == 1, "All concurrent identical requests must return the same task ID"

    with repo._db.get_connection() as conn:
        task_count = conn.execute("SELECT COUNT(*) FROM excel_tasks").fetchone()[0]
        file_count = conn.execute("SELECT COUNT(*) FROM excel_task_files").fetchone()[0]
        assert task_count == 1
        assert file_count == 2


def test_deterministic_concurrent_conflicting_create_task_serialization(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    (root_path / "s1.xlsx").write_bytes(b"data1")
    (root_path / "s2.xlsx").write_bytes(b"data2")
    ref1 = ExcelTaskFileRef(role="source", root_id="default", relative_path="s1.xlsx")
    ref2 = ExcelTaskFileRef(role="source", root_id="default", relative_path="s2.xlsx")
    out = ExcelTaskFileRef(role="output", root_id="default", relative_path="out.xlsx")

    barrier = threading.Barrier(2)
    orig_begin = repo._begin_immediate

    def hooked_begin(conn: sqlite3.Connection) -> None:
        barrier.wait(timeout=5)
        orig_begin(conn)

    repo._begin_immediate = hooked_begin

    results: list[dict] = []
    conflicts: list[ExcelIdempotencyConflictError] = []
    other_errors: list[Exception] = []
    lock = threading.Lock()

    def worker(ref: ExcelTaskFileRef) -> None:
        try:
            res = repo.create_task("merge_append", [ref, out], idempotency_key="det_conflict_key")
            with lock:
                results.append(res)
        except ExcelIdempotencyConflictError as exc:
            with lock:
                conflicts.append(exc)
        except Exception as exc:
            with lock:
                other_errors.append(exc)

    t1 = threading.Thread(target=worker, args=(ref1,))
    t2 = threading.Thread(target=worker, args=(ref2,))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not other_errors, f"Unexpected errors during concurrent conflicting creation: {other_errors}"
    assert len(results) == 1
    assert len(conflicts) == 1
    assert "idempotency key reused with different request fingerprint" in str(conflicts[0])

    with repo._db.get_connection() as conn:
        task_count = conn.execute("SELECT COUNT(*) FROM excel_tasks").fetchone()[0]
        file_count = conn.execute("SELECT COUNT(*) FROM excel_task_files").fetchone()[0]
        assert task_count == 1
        assert file_count == 2


def test_deterministic_concurrent_lease_next_serialization(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    (root_path / "s1.xlsx").write_bytes(b"data")
    ref = ExcelTaskFileRef(role="source", root_id="default", relative_path="s1.xlsx")
    out = ExcelTaskFileRef(role="output", root_id="default", relative_path="out.xlsx")

    task = repo.create_task("merge_append", [ref, out], idempotency_key="det_lease_single")

    barrier = threading.Barrier(3)
    orig_begin = repo._begin_immediate

    def hooked_begin(conn: sqlite3.Connection) -> None:
        barrier.wait(timeout=5)
        orig_begin(conn)

    repo._begin_immediate = hooked_begin

    results: list[dict | None] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            lease = repo.lease_next(lease_seconds=300)
            with lock:
                results.append(lease)
        except Exception as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"Unexpected errors during concurrent leasing: {errors}"
    assert len(results) == 3

    non_nones = [r for r in results if r is not None]
    nones = [r for r in results if r is None]

    assert len(non_nones) == 1
    assert len(nones) == 2
    assert non_nones[0]["task_id"] == task["id"]
    assert non_nones[0]["attempt"] == 1

    with repo._db.get_connection() as conn:
        runs = conn.execute("SELECT COUNT(*) FROM excel_task_runs WHERE task_id = ?", (task["id"],)).fetchone()[0]
        assert runs == 1


def test_deterministic_concurrent_lease_next_multiple_tasks(
    roots_dir: tuple[Path, ApprovedExcelRoots], repo: ExcelTaskRepository
) -> None:
    root_path, _ = roots_dir
    (root_path / "s1.xlsx").write_bytes(b"data1")
    (root_path / "s2.xlsx").write_bytes(b"data2")
    ref1 = ExcelTaskFileRef(role="source", root_id="default", relative_path="s1.xlsx")
    ref2 = ExcelTaskFileRef(role="source", root_id="default", relative_path="s2.xlsx")
    out1 = ExcelTaskFileRef(role="output", root_id="default", relative_path="out1.xlsx")
    out2 = ExcelTaskFileRef(role="output", root_id="default", relative_path="out2.xlsx")

    task1 = repo.create_task("merge_append", [ref1, out1], idempotency_key="det_multi_lease_1")
    task2 = repo.create_task("merge_append", [ref2, out2], idempotency_key="det_multi_lease_2")

    barrier = threading.Barrier(2)
    orig_begin = repo._begin_immediate

    def hooked_begin(conn: sqlite3.Connection) -> None:
        barrier.wait(timeout=5)
        orig_begin(conn)

    repo._begin_immediate = hooked_begin

    results: list[dict | None] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            lease = repo.lease_next(lease_seconds=300)
            with lock:
                results.append(lease)
        except Exception as exc:
            with lock:
                errors.append(exc)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, f"Unexpected errors: {errors}"
    assert len(results) == 2
    assert all(r is not None for r in results)

    leased_task_ids = {r["task_id"] for r in results if r is not None}
    assert leased_task_ids == {task1["id"], task2["id"]}

    with repo._db.get_connection() as conn:
        runs_count = conn.execute("SELECT COUNT(*) FROM excel_task_runs").fetchone()[0]
        assert runs_count == 2


def test_finish_success_records_artifact_atomically(
    roots_dir: tuple[Path, ApprovedExcelRoots],
    repo: ExcelTaskRepository,
) -> None:
    root_path, _ = roots_dir
    task_id, run_id, lease_token, output_ref, output_bytes = _start_artifact_task(
        root_path,
        repo,
        "artifact_success",
    )
    metadata = ExcelTaskArtifactMetadata(
        output_ref=output_ref,
        size_bytes=len(output_bytes),
        sha256=hashlib.sha256(output_bytes).hexdigest(),
    )

    artifact = repo.finish_success_with_artifact(
        task_id,
        run_id,
        lease_token,
        metadata,
    )

    assert artifact["task_id"] == task_id
    assert artifact["run_id"] == run_id
    assert artifact["root_id"] == "default"
    assert artifact["relative_path"] == output_ref.relative_path
    assert artifact["display_name"] == Path(output_ref.relative_path).name
    assert artifact["size_bytes"] == len(output_bytes)
    assert artifact["sha256"] == hashlib.sha256(output_bytes).hexdigest()
    assert repo.get_task(task_id)["status"] == "succeeded"  # type: ignore[index]
    assert repo.list_task_runs(task_id)[0]["run_state"] == "succeeded"
    assert repo.get_artifact(artifact["id"]) == artifact
    assert repo.list_task_artifacts(task_id) == [artifact]


def test_finish_success_artifact_failure_rolls_back_task_and_run(
    roots_dir: tuple[Path, ApprovedExcelRoots],
    repo: ExcelTaskRepository,
) -> None:
    root_path, _ = roots_dir
    task_id, run_id, lease_token, output_ref, output_bytes = _start_artifact_task(
        root_path,
        repo,
        "artifact_rollback",
    )
    metadata = ExcelTaskArtifactMetadata(
        output_ref=output_ref,
        size_bytes=len(output_bytes),
        sha256=hashlib.sha256(output_bytes).hexdigest(),
    )

    with pytest.raises(ExcelLeaseLostError):
        repo.finish_success_with_artifact(
            task_id,
            run_id + 999,
            lease_token,
            metadata,
        )

    task = repo.get_task(task_id)
    assert task is not None and task["status"] == "running"
    assert repo.list_task_runs(task_id)[0]["run_state"] == "running"
    assert repo.list_task_artifacts(task_id) == []


@pytest.mark.parametrize(
    "metadata",
    [
        ExcelTaskArtifactMetadata(
            ExcelTaskFileRef("output", "default", "ok.xlsx"),
            0,
            "0" * 64,
        ),
    ],
)
def test_artifact_metadata_normalizes_digest(metadata: ExcelTaskArtifactMetadata) -> None:
    assert metadata.sha256 == "0" * 64


def test_artifact_metadata_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        ExcelTaskArtifactMetadata(
            ExcelTaskFileRef("source", "default", "source.xlsx"),
            1,
            "0" * 64,
        )
    with pytest.raises(ValueError):
        ExcelTaskArtifactMetadata(
            ExcelTaskFileRef("output", "default", "out.xlsx"),
            -1,
            "0" * 64,
        )
    with pytest.raises(ValueError):
        ExcelTaskArtifactMetadata(
            ExcelTaskFileRef("output", "default", "out.xlsx"),
            1,
            "not-a-digest",
        )


# ── Excel Artifact Download Audit & Production Roots Tests ────────
def test_repo_record_and_list_artifact_download_audit(
    roots_dir: tuple[Path, ApprovedExcelRoots],
    repo: ExcelTaskRepository,
) -> None:
    root_path, _ = roots_dir
    task_id, run_id, lease_token, output_ref, data = _start_artifact_task(
        root_path,
        repo,
        "audit_repo_test",
    )
    artifact = repo.finish_success_with_artifact(
        task_id,
        run_id,
        lease_token,
        ExcelTaskArtifactMetadata(
            output_ref=output_ref,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        ),
    )
    artifact_id = int(artifact["id"])

    # 1. Record a succeeded download audit
    audit1 = repo.record_artifact_download_audit(
        artifact_id=artifact_id,
        task_id=task_id,
        result="succeeded",
        reason_code="verified",
        served_size_bytes=len(data),
    )
    assert audit1["artifact_id"] == artifact_id
    assert audit1["task_id"] == task_id
    assert audit1["result"] == "succeeded"
    assert audit1["reason_code"] == "verified"
    assert audit1["served_size_bytes"] == len(data)

    # 2. Record a rejected download audit
    audit2 = repo.record_artifact_download_audit(
        artifact_id=artifact_id,
        task_id=task_id,
        result="rejected",
        reason_code="integrity_mismatch",
    )
    assert audit2["artifact_id"] == artifact_id
    assert audit2["task_id"] == task_id
    assert audit2["result"] == "rejected"
    assert audit2["reason_code"] == "integrity_mismatch"
    assert audit2["served_size_bytes"] is None

    # 3. List audits newest-first
    audits = repo.list_artifact_download_audits(artifact_id, limit=50)
    assert len(audits) == 2
    assert audits[0]["id"] == audit2["id"]
    assert audits[1]["id"] == audit1["id"]

    # 4. Unknown artifact returns empty list
    assert repo.list_artifact_download_audits(999999) == []
    assert repo.list_artifact_download_audits(-1) == []


def test_repo_record_artifact_download_audit_validation(
    roots_dir: tuple[Path, ApprovedExcelRoots],
    repo: ExcelTaskRepository,
) -> None:
    root_path, _ = roots_dir
    task_id, run_id, lease_token, output_ref, data = _start_artifact_task(
        root_path,
        repo,
        "audit_repo_val_test",
    )
    artifact = repo.finish_success_with_artifact(
        task_id,
        run_id,
        lease_token,
        ExcelTaskArtifactMetadata(
            output_ref=output_ref,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        ),
    )
    artifact_id = int(artifact["id"])

    # Invalid artifact_id
    with pytest.raises(ValueError):
        repo.record_artifact_download_audit(0, task_id, "succeeded", "verified", served_size_bytes=10)

    # Invalid task_id
    with pytest.raises(ValueError):
        repo.record_artifact_download_audit(artifact_id, 0, "succeeded", "verified", served_size_bytes=10)

    # Invalid result
    with pytest.raises(ValueError):
        repo.record_artifact_download_audit(artifact_id, task_id, "unknown_result", "verified")

    # Invalid reason_code
    with pytest.raises(ValueError):
        repo.record_artifact_download_audit(artifact_id, task_id, "rejected", "")
    with pytest.raises(ValueError):
        repo.record_artifact_download_audit(artifact_id, task_id, "rejected", "r" * 65)

    # Invalid served_size_bytes on success
    with pytest.raises(ValueError):
        repo.record_artifact_download_audit(artifact_id, task_id, "succeeded", "verified", served_size_bytes=None)
    with pytest.raises(ValueError):
        repo.record_artifact_download_audit(artifact_id, task_id, "succeeded", "verified", served_size_bytes=-1)


def test_parse_excel_roots_json_valid(tmp_path: Path) -> None:
    root1 = (tmp_path / "root1").resolve()
    root2 = (tmp_path / "root2").resolve()

    # None and empty strings
    assert parse_excel_roots_json(None) is None
    assert parse_excel_roots_json("") is None
    assert parse_excel_roots_json("   ") is None
    assert parse_excel_roots_json("{}") is None

    # Valid single root
    raw = json.dumps({"business": str(root1)})
    parsed = parse_excel_roots_json(raw)
    assert parsed == {"business": root1}

    # Valid multi roots
    raw_multi = json.dumps({"root_a": str(root1), "root_b": str(root2)})
    parsed_multi = parse_excel_roots_json(raw_multi)
    assert parsed_multi == {"root_a": root1, "root_b": root2}


def test_parse_excel_roots_json_rejections(tmp_path: Path) -> None:
    # Malformed JSON
    with pytest.raises(ExcelPathSafetyError):
        parse_excel_roots_json("not valid json {")

    # Non-object JSON
    with pytest.raises(ExcelPathSafetyError):
        parse_excel_roots_json('["not", "an", "object"]')
    with pytest.raises(ExcelPathSafetyError):
        parse_excel_roots_json('"just a string"')
    with pytest.raises(ExcelPathSafetyError):
        parse_excel_roots_json("12345")
    with pytest.raises(ExcelPathSafetyError):
        parse_excel_roots_json("true")

    # Non-string input
    with pytest.raises(ExcelPathSafetyError):
        parse_excel_roots_json(123)  # type: ignore

    # Empty root ID
    with pytest.raises(ExcelPathSafetyError):
        parse_excel_roots_json(json.dumps({"": str(tmp_path)}))

    # Empty root path
    with pytest.raises(ExcelPathSafetyError):
        parse_excel_roots_json(json.dumps({"valid_id": ""}))

    # Non-absolute path
    with pytest.raises(ExcelPathSafetyError):
        parse_excel_roots_json(json.dumps({"rel_id": "relative/path/dir"}))

    # Duplicate canonical root IDs
    with pytest.raises(ExcelPathSafetyError):
        parse_excel_roots_json(json.dumps({"root1": str(tmp_path), "root１": str(tmp_path)}))

    # More than 16 roots
    too_many = {f"root_{i}": str(tmp_path) for i in range(17)}
    with pytest.raises(ExcelPathSafetyError):
        parse_excel_roots_json(json.dumps(too_many))


def test_load_production_excel_roots_from_env(tmp_path: Path) -> None:
    root = (tmp_path / "prod_root").resolve()
    env_mapping = {"VSE_EXCEL_ROOTS_JSON": json.dumps({"prod": str(root)})}
    loaded = load_production_excel_roots(env=env_mapping)
    assert loaded == {"prod": root}

    # Unset in env
    assert load_production_excel_roots(env={}) is None


def test_repo_list_retention_candidates(
    roots_dir: tuple[Path, ApprovedExcelRoots],
    repo: ExcelTaskRepository,
) -> None:
    root_path, _ = roots_dir
    # Create 3 artifact records
    t1, r1, tok1, out1, d1 = _start_artifact_task(root_path, repo, "ret_1")
    art1 = repo.finish_success_with_artifact(
        t1, r1, tok1,
        ExcelTaskArtifactMetadata(output_ref=out1, size_bytes=len(d1), sha256=hashlib.sha256(d1).hexdigest()),
    )
    t2, r2, tok2, out2, d2 = _start_artifact_task(root_path, repo, "ret_2")
    art2 = repo.finish_success_with_artifact(
        t2, r2, tok2,
        ExcelTaskArtifactMetadata(output_ref=out2, size_bytes=len(d2), sha256=hashlib.sha256(d2).hexdigest()),
    )
    t3, r3, tok3, out3, d3 = _start_artifact_task(root_path, repo, "ret_3")
    art3 = repo.finish_success_with_artifact(
        t3, r3, tok3,
        ExcelTaskArtifactMetadata(output_ref=out3, size_bytes=len(d3), sha256=hashlib.sha256(d3).hexdigest()),
    )

    # Seed deterministic timestamps
    with repo._db.get_connection() as conn:
        conn.execute(
            "UPDATE excel_task_artifacts SET created_at = '2026-01-01T00:00:00.000Z' WHERE id = ?",
            (art1["id"],),
        )
        conn.execute(
            "UPDATE excel_task_artifacts SET created_at = '2026-01-02T00:00:00.000Z' WHERE id = ?",
            (art2["id"],),
        )
        conn.execute(
            "UPDATE excel_task_artifacts SET created_at = '2026-01-03T00:00:00.000Z' WHERE id = ?",
            (art3["id"],),
        )

    # Query cutoff at 2026-01-02T12:00:00.000Z -> should return art1 and art2
    candidates, truncated = repo.list_retention_candidates("2026-01-02T12:00:00.000Z", limit=10)
    assert len(candidates) == 2
    assert not truncated
    assert candidates[0]["id"] == art1["id"]
    assert candidates[1]["id"] == art2["id"]

    # Query with limit=1 -> should return art1 and truncated=True
    c_lim, trunc_lim = repo.list_retention_candidates("2026-01-02T12:00:00.000Z", limit=1)
    assert len(c_lim) == 1
    assert trunc_lim is True
    assert c_lim[0]["id"] == art1["id"]

    # Query cutoff before all -> should return empty
    c_empty, trunc_empty = repo.list_retention_candidates("2025-12-31T23:59:59.999Z", limit=10)
    assert c_empty == []
    assert trunc_empty is False

    # Invalid cutoff raises ValueError
    with pytest.raises(ValueError):
        repo.list_retention_candidates("")
    with pytest.raises(ValueError):
        repo.list_retention_candidates("   ")
