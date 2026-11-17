# -*- coding: utf-8 -*-
"""
tests/test_excel_path_integration.py — DSH-V2-26 Excel 路径安全实际执行边界集成测试。

走真实调用链：真实 sqlite DatabaseManager + ExcelTaskRepository +
ApprovedExcelRoots + 真实 ExcelTaskWorker.run_once()；executor 使用注入的假实现，
不启动 COM/Excel。

覆盖契约 P1/P4/P5：
1. 正常任务成功，且 source/target/baseline 原件字节与 mtime 不变；
2. 提交期输出父目录已是指向根外的 junction → 提交被拒；
3. 提交后、执行前输出父目录被替换为指向根外的 junction → 执行被拒；
4. 执行中（假 executor 写完临时文件后）输出父目录改名 + 同名 junction → 提交前复核失败；
5. 执行中 source 父目录被替换为 junction → 失败；
6. resolve_ref 在提交与执行两处都实际被消费。
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest

from core.db_manager import DatabaseManager
from core.excel_tasks import (
    ApprovedExcelRoots,
    ExcelPathSafetyError,
    ExcelTaskFileRef,
    ExcelTaskRepository,
)
from core.excel_worker import ExcelTaskRunStatus, ExcelTaskWorker


# ── junction helpers（仅 Windows；创建失败则 skip 并说明原因）──────────
def _create_junction(link: Path, target: Path) -> None:
    """Create a directory junction at ``link`` pointing at ``target``."""
    if os.name != "nt":
        pytest.skip("junction replacement scenarios require Windows")
    assert target.is_dir(), f"junction target must be an existing directory: {target}"
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
    )
    output = (completed.stdout + completed.stderr).decode(errors="replace").strip()
    if completed.returncode != 0 or not link.is_dir():
        pytest.skip(f"cannot create junction {link} -> {target}: {output}")
    if not ApprovedExcelRoots.is_reparse_point(link):
        pytest.skip(f"created junction is not reported as a reparse point: {link}")


def _replace_dir_with_junction(link: Path, target: Path) -> None:
    """Replace the empty real directory at ``link`` with a junction to ``target``."""
    if link.exists() or link.is_symlink():
        os.rmdir(link)  # only removes the empty directory itself
    _create_junction(link, target)


def _remove_junction(link: Path) -> None:
    """Remove a junction link only (never its target)."""
    try:
        if link.is_dir() and ApprovedExcelRoots.is_reparse_point(link):
            os.rmdir(link)
    except OSError:
        pass


# ── 假 executor（不启动 COM/Excel）────────────────────────────────
class RecordingExecutor:
    """Fake Excel toolbox that writes the temp output then runs a test callback."""

    def __init__(self, after_write: Callable[[Path], None] | None = None) -> None:
        self.after_write = after_write
        self.calls: list[dict[str, Any]] = []

    def _emit(self, output_path: Path, payload: bytes) -> Path:
        output_path.write_bytes(payload)
        if self.after_write is not None:
            self.after_write(output_path)
        return output_path

    def merge_append(
        self,
        sources: list[Path],
        output_path: Path,
        baseline: Path | None = None,
    ) -> Path:
        self.calls.append(
            {
                "operation": "merge_append",
                "sources": list(sources),
                "output_path": output_path,
                "baseline": baseline,
            }
        )
        return self._emit(output_path, b"fake_merge_append_content")

    def merge_overlay(
        self,
        sources: list[Path],
        target: Path,
        output_path: Path,
        baseline: Path | None = None,
    ) -> Path:
        self.calls.append(
            {
                "operation": "merge_overlay",
                "sources": list(sources),
                "target": target,
                "output_path": output_path,
                "baseline": baseline,
            }
        )
        return self._emit(output_path, b"fake_merge_overlay_content")

    def diff_against_baseline(
        self,
        target: Path,
        baseline: Path,
        output_path: Path,
    ) -> Path:
        self.calls.append(
            {
                "operation": "diff_against_baseline",
                "target": target,
                "baseline": baseline,
                "output_path": output_path,
            }
        )
        return self._emit(output_path, b"fake_diff_content")


@dataclass
class ExcelSandbox:
    """Real sqlite + repository + approved roots rooted entirely under tmp_path."""

    root: Path
    outside: Path
    roots: ApprovedExcelRoots
    repo: ExcelTaskRepository


@pytest.fixture
def sandbox(tmp_path: Path) -> ExcelSandbox:
    root = tmp_path / "excel_root"
    root.mkdir()
    outside = tmp_path / "outside_root"
    outside.mkdir()
    db = DatabaseManager(db_path=tmp_path / "excel_path_integration.db")
    db.init_database()
    roots = ApprovedExcelRoots({"default": root})
    return ExcelSandbox(
        root=root,
        outside=outside,
        roots=roots,
        repo=ExcelTaskRepository(db, roots),
    )


def _worker(sandbox: ExcelSandbox, executor: RecordingExecutor) -> ExcelTaskWorker:
    return ExcelTaskWorker(sandbox.repo, executor_factory=executor)


# ── 1. 正常任务成功，用户输入原件保持不变 ───────────────────────────
def test_successful_task_keeps_input_files_unchanged(sandbox: ExcelSandbox) -> None:
    src_a = sandbox.root / "src_a.xlsx"
    src_b = sandbox.root / "src_b.xlsx"
    target = sandbox.root / "target.xlsx"
    baseline = sandbox.root / "baseline.xlsx"
    inputs = {
        src_a: b"src-a-bytes",
        src_b: b"src-b-bytes",
        target: b"target-bytes",
        baseline: b"baseline-bytes",
    }
    for path, payload in inputs.items():
        path.write_bytes(payload)
    snapshot = {
        path: (path.read_bytes(), path.stat().st_mtime_ns) for path in inputs
    }

    refs = [
        ExcelTaskFileRef("source", "default", "src_a.xlsx", ordinal=0),
        ExcelTaskFileRef("source", "default", "src_b.xlsx", ordinal=1),
        ExcelTaskFileRef("target", "default", "target.xlsx", ordinal=0),
        ExcelTaskFileRef("baseline", "default", "baseline.xlsx", ordinal=0),
        ExcelTaskFileRef("output", "default", "out.xlsx", ordinal=0),
    ]
    task = sandbox.repo.create_task("merge_overlay", refs, "key_success_keep_inputs")
    task_id = int(task["id"])

    executor = RecordingExecutor()
    result = _worker(sandbox, executor).run_once()

    assert result.status is ExcelTaskRunStatus.SUCCEEDED
    assert result.task_id == task_id
    assert result.output_committed is True
    assert isinstance(result.artifact_id, int)
    assert len(executor.calls) == 1

    output = sandbox.root / "out.xlsx"
    assert output.read_bytes() == b"fake_merge_overlay_content"
    assert list(sandbox.root.glob(".tmp_*")) == []

    # 用户输入原件：字节与 mtime 均未变化
    for path, (payload, mtime_ns) in snapshot.items():
        assert path.read_bytes() == payload, f"input bytes changed: {path.name}"
        assert path.stat().st_mtime_ns == mtime_ns, f"input mtime changed: {path.name}"

    updated = sandbox.repo.get_task(task_id)
    assert updated is not None
    assert updated["status"] == "succeeded"
    artifacts = sandbox.repo.list_task_artifacts(task_id)
    assert len(artifacts) == 1
    assert artifacts[0]["relative_path"] == "out.xlsx"


# ── 2. 提交期：输出父目录已是 junction（指向根外）→ 提交被拒 ──────────
def test_submit_rejects_output_parent_junction_to_outside(
    sandbox: ExcelSandbox,
) -> None:
    source = sandbox.root / "source.xlsx"
    source.write_bytes(b"source")
    sub = sandbox.root / "sub"
    sub.mkdir()

    _replace_dir_with_junction(sub, sandbox.outside)
    try:
        with pytest.raises(ExcelPathSafetyError, match="reparse point"):
            sandbox.repo.create_task(
                "merge_append",
                [
                    ExcelTaskFileRef("source", "default", "source.xlsx"),
                    ExcelTaskFileRef("output", "default", "sub/out.xlsx"),
                ],
                "key_submit_junction",
            )
        assert sandbox.repo.list_tasks() == []
        assert list(sandbox.outside.iterdir()) == []
    finally:
        _remove_junction(sub)


# ── 3. 提交后、执行前替换输出父目录 → 执行被拒 ─────────────────────
def test_execution_rejects_output_parent_replaced_after_submit(
    sandbox: ExcelSandbox,
) -> None:
    source = sandbox.root / "source.xlsx"
    source.write_bytes(b"source")
    sub = sandbox.root / "sub"
    sub.mkdir()

    task = sandbox.repo.create_task(
        "merge_append",
        [
            ExcelTaskFileRef("source", "default", "source.xlsx"),
            ExcelTaskFileRef("output", "default", "sub/out.xlsx"),
        ],
        "key_exec_output_parent_swap",
    )
    task_id = int(task["id"])

    moved = sandbox.root / "sub_moved"
    sub.rename(moved)
    _create_junction(sub, sandbox.outside)
    try:
        executor = RecordingExecutor()
        result = _worker(sandbox, executor).run_once()
    finally:
        _remove_junction(sub)

    assert result.status is ExcelTaskRunStatus.FAILED
    assert result.succeeded is False
    assert result.task_id == task_id
    assert result.output_committed is False
    assert result.error_type == "ExcelPathSafetyError"
    assert executor.calls == []
    assert not (sandbox.outside / "out.xlsx").exists()
    assert list(sandbox.outside.iterdir()) == []

    updated = sandbox.repo.get_task(task_id)
    assert updated is not None
    assert updated["status"] == "failed"
    assert updated["error_type"] == "ExcelPathSafetyError"
    assert sandbox.repo.list_task_artifacts(task_id) == []


# ── 4. 执行中替换输出父目录（同名 junction 指向根外）→ 提交前复核失败 ──
def test_commit_rejected_when_output_parent_swapped_during_execution(
    sandbox: ExcelSandbox,
) -> None:
    source = sandbox.root / "source.xlsx"
    source.write_bytes(b"source")
    sub = sandbox.root / "sub"
    sub.mkdir()

    task = sandbox.repo.create_task(
        "merge_append",
        [
            ExcelTaskFileRef("source", "default", "source.xlsx"),
            ExcelTaskFileRef("output", "default", "sub/out.xlsx"),
        ],
        "key_race_output_parent",
    )
    task_id = int(task["id"])

    moved = sandbox.root / "sub_moved"

    def swap_output_parent(_output_path: Path) -> None:
        sub.rename(moved)
        _create_junction(sub, sandbox.outside)

    executor = RecordingExecutor(after_write=swap_output_parent)
    try:
        result = _worker(sandbox, executor).run_once()
    finally:
        _remove_junction(sub)

    assert result.status is ExcelTaskRunStatus.FAILED
    assert result.succeeded is False
    assert result.task_id == task_id
    assert result.output_committed is False
    assert result.error_type == "ExcelPathSafetyError"
    assert "输出目录在执行期间被替换" in (result.error_message or "")
    assert len(executor.calls) == 1

    # 根外目录不得出现输出文件，也不得出现任何写入
    assert not (sandbox.outside / "out.xlsx").exists()
    assert list(sandbox.outside.iterdir()) == []
    # 输出未提交到根内任何位置
    assert not (moved / "out.xlsx").exists()

    updated = sandbox.repo.get_task(task_id)
    assert updated is not None
    assert updated["status"] == "failed"
    assert updated["error_type"] == "ExcelPathSafetyError"
    assert sandbox.repo.list_task_artifacts(task_id) == []


# ── 5. 执行中替换 source 父目录 → 失败 ─────────────────────────────
def test_commit_rejected_when_source_parent_swapped_during_execution(
    sandbox: ExcelSandbox,
) -> None:
    sub = sandbox.root / "sub"
    sub.mkdir()
    source = sub / "source.xlsx"
    source.write_bytes(b"source")

    task = sandbox.repo.create_task(
        "merge_append",
        [
            ExcelTaskFileRef("source", "default", "sub/source.xlsx"),
            ExcelTaskFileRef("output", "default", "out.xlsx"),
        ],
        "key_race_source_parent",
    )
    task_id = int(task["id"])

    moved = sandbox.root / "sub_moved"

    def swap_source_parent(_output_path: Path) -> None:
        sub.rename(moved)
        _create_junction(sub, sandbox.outside)

    executor = RecordingExecutor(after_write=swap_source_parent)
    try:
        result = _worker(sandbox, executor).run_once()
    finally:
        _remove_junction(sub)

    assert result.status is ExcelTaskRunStatus.FAILED
    assert result.succeeded is False
    assert result.task_id == task_id
    assert result.output_committed is False
    assert result.error_type == "ExcelPathSafetyError"
    assert "source[0]" in (result.error_message or "")
    assert "was replaced during execution" in (result.error_message or "")

    assert not (sandbox.root / "out.xlsx").exists()
    assert list(sandbox.outside.iterdir()) == []
    assert list(sandbox.root.glob(".tmp_*")) == []

    updated = sandbox.repo.get_task(task_id)
    assert updated is not None
    assert updated["status"] == "failed"
    assert updated["error_type"] == "ExcelPathSafetyError"
    assert sandbox.repo.list_task_artifacts(task_id) == []


# ── 6. 证明消费位置：提交与执行两处都实际调用 resolve_ref ─────────────
def test_resolve_ref_consumed_at_submit_and_execution(sandbox: ExcelSandbox) -> None:
    source = sandbox.root / "source.xlsx"
    target = sandbox.root / "target.xlsx"
    baseline = sandbox.root / "baseline.xlsx"
    source.write_bytes(b"source")
    target.write_bytes(b"target")
    baseline.write_bytes(b"baseline")

    calls: list[tuple[str, int, bool]] = []
    original_resolve = sandbox.roots.resolve_ref

    def spy_resolve(file_ref: ExcelTaskFileRef, *, check_role: bool = True) -> Path:
        calls.append((file_ref.role, file_ref.ordinal, check_role))
        return original_resolve(file_ref, check_role=check_role)

    sandbox.roots.resolve_ref = spy_resolve  # type: ignore[method-assign]

    refs = [
        ExcelTaskFileRef("source", "default", "source.xlsx", ordinal=0),
        ExcelTaskFileRef("target", "default", "target.xlsx", ordinal=0),
        ExcelTaskFileRef("baseline", "default", "baseline.xlsx", ordinal=0),
        ExcelTaskFileRef("output", "default", "out.xlsx", ordinal=0),
    ]
    sandbox.repo.create_task("merge_overlay", refs, "key_resolve_ref_consumption")
    submit_calls = list(calls)
    calls.clear()

    executor = RecordingExecutor()
    result = _worker(sandbox, executor).run_once()
    execution_calls = list(calls)

    assert result.status is ExcelTaskRunStatus.SUCCEEDED
    assert ("source", 0, True) in submit_calls
    assert ("output", 0, True) in submit_calls
    assert ("source", 0, True) in execution_calls
    assert ("target", 0, True) in execution_calls
    assert ("baseline", 0, True) in execution_calls
    # 执行期 output 至少被解析两次：初次解析 + os.replace 前复核
    output_execution_calls = [c for c in execution_calls if c[0] == "output"]
    assert len(output_execution_calls) >= 2
    assert all(check_role is True for _, _, check_role in execution_calls)
