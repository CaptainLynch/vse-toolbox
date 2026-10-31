# -*- coding: utf-8 -*-
"""DSH-V2-45：任务中心 → /api/tasks → crawl_task_runner 的产物 7 天清理真实链路。

覆盖的契约（docs/refactor-v2/CONTRACTS.md C5/C6）：
- 7 天清理只删「已过期（>7 天）且非活跃任务」的产物：6 天保留、8 天删除；
- 活跃任务（queued/leased/running）产物、历史原件（ArchiveStore 独立根）与用户文件不删；
- 清理失败保留产物并明确报错（report + 日志），不静默吞掉；
- /api/tasks 的 ``progress`` 保持原始值，不定进度用 ``progressIndeterminate``，
  前端派生值（effectiveProgress）不回写 ``progress``。

测试走真实入口：``CrawlTaskRunner.submit_task`` 完成路径（内部触发清理）、
``CrawlTaskRunner.cleanup_expired_artifacts``、以及 Flask ``GET /api/tasks``。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import web.app as web_app
from core.db_manager import DatabaseManager
from services.crawl_task_runner import (
    ArtifactPruneReport,
    CrawlTaskContext,
    CrawlTaskRunner,
    prune_old_artifacts,
)

DAY = 86400.0

REPO_ROOT = Path(__file__).resolve().parent.parent
HOST_STATIC = REPO_ROOT / "web" / "static" / "host"
RUNNER_LOGGER = "vse_toolbox.crawl_task_runner"


def _aged(path: Path, mtime: float, payload: bytes = b"artifact") -> Path:
    """写一个产物文件并把 mtime 固定到指定时刻（真实文件系统边界，不 mock stat）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture()
def chain(tmp_path: Path):
    """真实 runner + 真实 sqlite 任务表 + 可注入时钟的产物目录。"""
    db = DatabaseManager(db_path=tmp_path / "cleanup_chain.db")
    db.init_database()
    downloads = tmp_path / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    now = time.time()
    runner = CrawlTaskRunner(
        db=db, downloads_dir=downloads, max_workers=1, clock=lambda: now
    )
    env = SimpleNamespace(db=db, downloads=downloads, runner=runner, tmp=tmp_path, now=now)
    try:
        yield env
    finally:
        runner.shutdown(wait=True)


def _write_own_artifact(ctx: CrawlTaskContext) -> None:
    """任务真实产物：命名带 task_id，落盘后登记为 artifact_path。"""
    own = ctx.downloads_dir / f"{ctx.task_id}.result.json"
    own.write_text("{}", encoding="utf-8")
    ctx.set_artifact(own)


def _submit_and_wait(
    runner: CrawlTaskRunner,
    worker=_write_own_artifact,
    task_type: str = "paa_export",
    source: str = "aras",
    timeout: float = 10.0,
) -> tuple[str, dict, ArtifactPruneReport]:
    """提交任务并等到「终态 + 本轮清理报告」，走 runner 的真实完成路径。"""
    before = runner.last_cleanup_report
    task_id = runner.submit_task(task_type, source, {}, worker)
    deadline = time.time() + timeout
    task: dict | None = None
    while time.time() < deadline:
        task = runner.get_task(task_id)
        if (
            task
            and task["status"] in ("succeeded", "failed", "cancelled", "interrupted")
            and runner.last_cleanup_report is not before
        ):
            break
        time.sleep(0.02)
    else:  # pragma: no cover - 只在 runner 卡死时触发
        raise AssertionError(f"task {task_id} did not finish with a cleanup report: {task}")
    report = runner.last_cleanup_report
    assert report is not None
    return task_id, task, report


# ── 1. 6 天保留 / 8 天删除边界（runner 完成路径） ──────────────────────────


def test_cleanup_keeps_6_day_and_removes_8_day_artifacts(chain) -> None:
    downloads, now = chain.downloads, chain.now
    expired_id = "crawl_exp0000000001"
    fresh_id = "crawl_fresh00000002"
    for tid in (expired_id, fresh_id):
        chain.db.create_crawl_task(tid, "paa_export", "aras")
        chain.db.update_crawl_task_status(tid, "succeeded", artifact_path=f"{tid}.csv")
    expired = _aged(downloads / f"{expired_id}.csv", now - 8 * DAY)
    fresh = _aged(downloads / f"{fresh_id}.csv", now - 6 * DAY)

    task_id, task, report = _submit_and_wait(chain.runner)

    assert task["status"] == "succeeded"
    assert report.ok, report
    assert report.removed == (expired.name,)
    assert not expired.exists(), "超过 7 天的非活跃任务产物必须删除"
    assert fresh.exists(), "6 天的产物必须保留"
    assert (downloads / f"{task_id}.result.json").exists(), "本次任务产物（mtime=now）不得删除"
    assert fresh.name in report.retained


def test_cleanup_boundary_is_strictly_older_than_retention(chain) -> None:
    """>7 天才删：未满 7 天（cutoff 内侧 60 秒）仍保留。"""
    downloads, now = chain.downloads, chain.now
    edge_id = "crawl_edge0000000001"
    chain.db.create_crawl_task(edge_id, "paa_export", "aras")
    chain.db.update_crawl_task_status(edge_id, "succeeded", artifact_path=f"{edge_id}.csv")
    edge = _aged(downloads / f"{edge_id}.csv", now - 7 * DAY + 60)

    _, _, report = _submit_and_wait(chain.runner, task_type="query", source="tdc")

    assert report.removed == ()
    assert edge.exists()


# ── 2. 活跃任务排除 ────────────────────────────────────────────────────────


def test_active_task_artifact_is_excluded_until_terminal(chain) -> None:
    db, downloads, now = chain.db, chain.downloads, chain.now
    active_id = "crawl_act0000000001"
    db.create_crawl_task(active_id, "paa_export", "aras")
    db.update_crawl_task_status(active_id, "running")
    running_artifact = _aged(downloads / f"{active_id}.csv", now - 9 * DAY)

    done_id = "crawl_done000000002"
    db.create_crawl_task(done_id, "paa_export", "aras")
    db.update_crawl_task_status(done_id, "succeeded", artifact_path=f"{done_id}.csv")
    done_artifact = _aged(downloads / f"{done_id}.csv", now - 9 * DAY)

    _, _, report = _submit_and_wait(chain.runner, task_type="query", source="tdc")

    assert report.ok, report
    assert report.removed == (done_artifact.name,)
    assert not done_artifact.exists()
    assert running_artifact.exists(), "运行中任务的产物必须在清理保护边界内"
    assert running_artifact.name in report.retained

    # 任务进入终态后，同一产物才进入清理范围（保护是状态驱动，不是永久豁免）。
    db.update_crawl_task_status(active_id, "succeeded", artifact_path=f"{active_id}.csv")
    _, _, second = _submit_and_wait(chain.runner, task_type="query", source="tdc")
    assert second.removed == (running_artifact.name,)
    assert not running_artifact.exists()


def test_queued_and_leased_tasks_are_protected(chain) -> None:
    db, downloads, now = chain.db, chain.downloads, chain.now
    protected: dict[str, Path] = {}
    for task_id, status in (
        ("crawl_q000000000001", "queued"),
        ("crawl_l000000000001", "leased"),
    ):
        db.create_crawl_task(task_id, "paa_export", "aras")
        db.update_crawl_task_status(task_id, status)
        protected[task_id] = _aged(downloads / f"{task_id}.csv", now - 20 * DAY)

    _, _, report = _submit_and_wait(chain.runner, task_type="query", source="tdc")

    assert report.removed == ()
    for task_id, path in protected.items():
        assert path.exists(), f"{task_id} 的产物被误删"


# ── 3. 历史原件与用户文件隔离 ─────────────────────────────────────────────


def test_history_originals_and_user_files_are_isolated(chain) -> None:
    downloads, now = chain.downloads, chain.now
    # 历史原件根（ArchiveStore 独立目录）：同名同 ID 也不得被任务清理波及。
    hist_id = "crawl_hist000000001"
    chain.db.create_crawl_task(hist_id, "paa_export", "aras")
    chain.db.update_crawl_task_status(hist_id, "succeeded", artifact_path=f"{hist_id}.csv")
    archive_root = chain.tmp / "data" / "output" / "exports"
    original = _aged(archive_root / f"{hist_id}.csv", now - 30 * DAY)
    user_file = _aged(chain.tmp / "user-notes.txt", now - 30 * DAY)
    nested = downloads / "nested"
    nested_old = _aged(nested / f"{hist_id}.csv", now - 30 * DAY)
    partial = _aged(downloads / f"{hist_id}.csv.part", now - 30 * DAY)
    unowned = _aged(downloads / "用户导出_2020.csv", now - 30 * DAY)

    _, _, report = _submit_and_wait(chain.runner, task_type="query", source="tdc")

    assert report.removed == ()
    assert original.exists(), "历史原件（ArchiveStore 根）不得删除"
    assert user_file.exists(), "用户文件不得删除"
    assert nested_old.exists(), "子目录不递归清理"
    assert partial.exists(), "下载中的临时文件不得删除"
    assert unowned.exists(), "无法归属为任务产物的文件按用户文件保留"


def test_cleanup_does_not_follow_links_out_of_artifact_dir(chain) -> None:
    """产物目录里的链接指向历史原件根时，清理不得穿透删除目标文件。"""
    downloads, now = chain.downloads, chain.now
    archive_root = chain.tmp / "archive-root"
    archive_root.mkdir(parents=True, exist_ok=True)
    original = _aged(archive_root / "original.csv", now - 30 * DAY)
    link = downloads / "crawl_link000000001.csv"
    try:
        os.symlink(original, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink unavailable on this platform")

    _, _, report = _submit_and_wait(chain.runner, task_type="query", source="tdc")

    assert report.removed == ()
    assert original.exists()
    assert link.name in report.retained


# ── 4. 清理失败：保留产物并明确报错 ───────────────────────────────────────


def test_cleanup_failure_keeps_artifact_and_reports_error(
    chain, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    db, downloads, now = chain.db, chain.downloads, chain.now
    victim_id = "crawl_lock000000001"
    ok_id = "crawl_ok00000000002"
    for tid in (victim_id, ok_id):
        db.create_crawl_task(tid, "paa_export", "aras")
        db.update_crawl_task_status(tid, "succeeded", artifact_path=f"{tid}.csv")
    victim = _aged(downloads / f"{victim_id}.csv", now - 8 * DAY)
    removable = _aged(downloads / f"{ok_id}.csv", now - 8 * DAY)

    real_unlink = Path.unlink

    def deny(self: Path, *args, **kwargs):
        if self.name == victim.name:
            raise PermissionError(13, "artifact is locked by another process")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", deny)

    with caplog.at_level(logging.WARNING, logger=RUNNER_LOGGER):
        report = chain.runner.cleanup_expired_artifacts()

    assert victim.exists(), "删除失败必须保留产物"
    assert not removable.exists(), "单个文件失败不得中断其余产物的清理"
    assert report.ok is False
    assert [name for name, _ in report.failures] == [victim.name]
    assert "locked" in report.failures[0][1]
    messages = [record.getMessage() for record in caplog.records]
    assert any(victim.name in message and "locked" in message for message in messages), messages


def test_cleanup_fails_closed_when_ownership_snapshot_unavailable(
    chain, monkeypatch: pytest.MonkeyPatch
) -> None:
    downloads, now = chain.downloads, chain.now
    task_id = "crawl_orphan0000001"
    chain.db.create_crawl_task(task_id, "paa_export", "aras")
    chain.db.update_crawl_task_status(task_id, "succeeded", artifact_path=f"{task_id}.csv")
    old = _aged(downloads / f"{task_id}.csv", now - 9 * DAY)

    def boom() -> None:
        raise RuntimeError("crawl_tasks snapshot failed")

    monkeypatch.setattr(chain.runner, "_artifact_registry", boom)

    report = chain.runner.cleanup_expired_artifacts()

    assert report.ok is False
    assert report.error and "snapshot" in report.error
    assert report.removed == ()
    assert old.exists(), "归属未知时必须 fail-closed，不删除任何产物"


def test_prune_report_counts_removed_files(tmp_path: Path) -> None:
    """计数入口（app 启动清理用）仍返回删除数量，且过期判定基于注入时钟。"""
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    now = 1_800_000_000.0
    old = _aged(downloads / "old_artifact.csv", now - 8 * DAY)
    fresh = _aged(downloads / "fresh_artifact.csv", now - 6 * DAY)

    assert prune_old_artifacts(downloads, now=now) == 1
    assert not old.exists()
    assert fresh.exists()


# ── 5. /api/tasks 真实入口：progress 原样 + 产物生命周期 ──────────────────


@pytest.fixture()
def api_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = DatabaseManager(db_path=tmp_path / "api_chain.db")
    db.init_database()
    downloads = tmp_path / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db)
    monkeypatch.setattr("core.runtime_paths.app_root", lambda: tmp_path)
    app = web_app.create_app(
        allowed_hosts=["aras.example"],
        tdc_allowed_hosts=["tdc.example"],
    )
    app.config.update(TESTING=True)
    return SimpleNamespace(
        app=app, client=app.test_client(), db=db, downloads=downloads, now=time.time()
    )


def test_api_tasks_keeps_progress_raw_and_drops_expired_artifact(api_env) -> None:
    db, client = api_env.db, api_env.client
    downloads, now = api_env.downloads, api_env.now
    runner = api_env.app.extensions["crawl_task_runner"]

    active_id = "crawl_apact00000001"
    db.create_crawl_task(active_id, "paa_crawl", "aras")  # queued → 活跃且无 progress
    done_id = "crawl_apdone0000002"
    db.create_crawl_task(done_id, "paa_export", "aras")
    db.update_crawl_task_status(done_id, "succeeded", artifact_path=f"{done_id}.csv")
    artifact = _aged(downloads / f"{done_id}.csv", now - 8 * DAY)

    response = client.get("/api/tasks")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    tasks = {task["raw_id"]: task for task in payload["data"]["tasks"]}

    active = tasks[active_id]
    assert active["is_active"] is True
    assert active["progress"] == {}, "progress 必须保持原始值，不伪造百分比"
    assert active["progressIndeterminate"] is True, "未知总量走不定进度"
    done = tasks[done_id]
    assert done["progress"] == {}
    assert done["has_artifact"] is True and done["can_download"] is True

    report = runner.cleanup_expired_artifacts()  # 与任务完成时同一清理入口
    assert report.ok, report
    assert artifact.name in report.removed
    assert not artifact.exists()

    after = client.get(f"/api/tasks/{done_id}").get_json()["data"]
    assert after["has_artifact"] is False and after["can_download"] is False
    assert after["progress"] == {}, "派生显示值不得回写 progress"
    assert "effectiveProgress" not in after


# ── 6. TaskCenter.js：effectiveProgress 派生值只读 ────────────────────────


def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.match(r"v(\d+)", out.strip())
    return int(match.group(1)) if match else 0


needs_node = pytest.mark.skipif(
    _node_major() < 22, reason="needs Node 22+ to import ES modules without a package.json"
)

_NODE_SCRIPT = r"""
const [base] = process.argv.slice(1);
const tasks = await import(base + "/chrome/TaskCenter.js");
const running = {id: "crawl_x", status: "running", is_active: true,
                 progress: {percent: 42, stage: "抓取第 2 页", total: 10}};
const snapshot = JSON.stringify(running);
const view = tasks.effectiveProgress(running);
console.log(JSON.stringify({
  view,
  unchanged: JSON.stringify(running) === snapshot,
  clamp: tasks.effectiveProgress({status: "running", is_active: true, progress: {percent: 250}}).percent,
  negative: tasks.effectiveProgress({status: "running", is_active: true, progress: {percent: -5}}).percent,
  numeric: tasks.effectiveProgress({status: "running", is_active: true, progress: {percent: "37"}}).percent,
  garbage: tasks.effectiveProgress({status: "running", is_active: true, progress: {percent: "abc"}}).percent,
  unknown: tasks.effectiveProgress({id: "crawl_y", status: "queued", is_active: true,
                                    progress: {}, progressIndeterminate: true}),
  finished: tasks.effectiveProgress({status: "succeeded", is_active: false, progress: {}}),
  missing: tasks.effectiveProgress(null),
}));
"""


@needs_node
def test_task_center_effective_progress_is_display_only() -> None:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", _NODE_SCRIPT, HOST_STATIC.as_uri()],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    data = json.loads(result.stdout.strip().splitlines()[-1])

    assert data["view"]["percent"] == 42
    assert data["view"]["stage"] == "抓取第 2 页"
    assert data["unchanged"] is True, "effectiveProgress 不得改写 task.progress"
    assert data["clamp"] == 100
    assert data["negative"] == 0
    assert data["numeric"] == 37
    assert data["garbage"] is None
    assert data["unknown"]["percent"] is None
    assert data["unknown"]["indeterminate"] is True
    assert data["finished"]["indeterminate"] is False
    assert data["finished"]["percent"] is None
    assert data["missing"]["percent"] is None
