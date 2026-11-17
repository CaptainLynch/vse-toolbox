# -*- coding: utf-8 -*-
"""清理保护边界（契约 C6）：活跃任务产物不进清理候选；历史原件与运行中下载不受影响。"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.excel_tasks import ExcelTaskRepository


@pytest.fixture()
def repo(tmp_path: Path):
    db_path = tmp_path / "cleanup.db"
    from core.db_manager import DatabaseManager

    db = DatabaseManager(db_path=db_path)
    db.init_database()
    from core.excel_tasks import ApprovedExcelRoots

    root_dir = tmp_path / "excel-root"
    root_dir.mkdir(parents=True, exist_ok=True)
    roots = ApprovedExcelRoots({"root": root_dir})
    return ExcelTaskRepository(db, roots), db


def _insert_task_with_artifact(conn, *, task_id: int, status: str, artifact_id: int, created_at: str) -> None:
    conn.execute(
        """
        INSERT INTO excel_tasks (id, operation, status, idempotency_key_hash, request_fingerprint, created_at, updated_at)
        VALUES (?, 'merge_append', ?, ?, ?, ?, ?)
        """,
        (task_id, status, format(task_id, '064x'), format(task_id, '064x'), created_at, created_at),
    )
    conn.execute(
        """
        INSERT INTO excel_task_runs (id, task_id, attempt, run_state, created_at)
        VALUES (?, ?, 1, 'succeeded', ?)
        """,
        (task_id, task_id, created_at),
    )
    conn.execute(
        """
        INSERT INTO excel_task_artifacts (id, task_id, run_id, artifact_type, root_id, relative_path,
                                          display_name, size_bytes, sha256, created_at)
        VALUES (?, ?, ?, 'output', 'root', ?, 'out.xlsx', 10, ?, ?)
        """,
        (artifact_id, task_id, task_id, f"out-{artifact_id}.xlsx", 'c' * 64, created_at),
    )


def test_retention_excludes_active_task_artifacts(repo) -> None:
    """运行中/租约/排队任务的产物绝不进清理候选（契约 C6 清理保护）。"""
    repository, db = repo
    old = "2026-01-01T00:00:00.000Z"
    with db.get_connection() as conn:
        _insert_task_with_artifact(conn, task_id=1, status="succeeded", artifact_id=1, created_at=old)
        _insert_task_with_artifact(conn, task_id=2, status="running", artifact_id=2, created_at=old)
        _insert_task_with_artifact(conn, task_id=3, status="leased", artifact_id=3, created_at=old)
        _insert_task_with_artifact(conn, task_id=4, status="queued", artifact_id=4, created_at=old)
        conn.commit()

    candidates, _ = repository.list_retention_candidates(old, 200)
    ids = {c["id"] for c in candidates}
    assert 1 in ids, "已完成任务的旧产物应可清理"
    assert not ({2, 3, 4} & ids), "活跃任务的产物必须在保护边界内"


def test_retention_respects_cutoff(repo) -> None:
    repository, db = repo
    with db.get_connection() as conn:
        _insert_task_with_artifact(conn, task_id=10, status="succeeded", artifact_id=10,
                                   created_at="2026-06-01T00:00:00.000Z")
        conn.commit()

    before, _ = repository.list_retention_candidates("2026-07-01T00:00:00.000Z", 200)
    after, _ = repository.list_retention_candidates("2026-01-01T00:00:00.000Z", 200)
    assert {c["id"] for c in before} == {10}
    assert {c["id"] for c in after} == set()
