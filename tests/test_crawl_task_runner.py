# -*- coding: utf-8 -*-
"""Focused unit tests for CrawlTaskRunner and crawl_tasks table."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from core.db_manager import DatabaseManager
from services.crawl_task_runner import (
    CrawlTaskContext,
    CrawlTaskRunner,
    sanitize_task_params,
)


@pytest.fixture()
def runner_fixture(tmp_path: Path) -> tuple[DatabaseManager, CrawlTaskRunner]:
    db_file = tmp_path / "runner_test.db"
    downloads_dir = tmp_path / "downloads"
    db = DatabaseManager(db_path=db_file)
    db.init_database()
    runner = CrawlTaskRunner(db=db, downloads_dir=downloads_dir, max_workers=2)
    return db, runner


def test_sanitize_task_params_removes_sensitive_keys() -> None:
    raw = {
        "report_type": "ewo",
        "domainPassword": "secret_password_123",
        "token": "bearer_abc",
        "auth_cookie": "sess_xyz",
        "normal_field": "12345",
        "nested": {
            "password": "inner_pass",
            "safe_val": "hello",
        },
    }
    clean = sanitize_task_params(raw)
    assert "report_type" in clean
    assert "normal_field" in clean
    assert "domainPassword" not in clean
    assert "token" not in clean
    assert "auth_cookie" not in clean
    assert "password" not in clean["nested"]
    assert clean["nested"]["safe_val"] == "hello"


def test_sanitize_task_params_preserves_legitimate_keys() -> None:
    business_params = {
        "job_key": "aras_ewo",
        "template_key": "aras_ewo_template",
        "keyword": "brake pad",
        "author": "engineer_chen",
        "sort_key": "created_at",
        "author_id": 42,
        "api_key": "sensitive_api_key_secret",
        "authorization": "Bearer eyJxyz",
    }
    clean = sanitize_task_params(business_params)
    assert clean["job_key"] == "aras_ewo"
    assert clean["template_key"] == "aras_ewo_template"
    assert clean["keyword"] == "brake pad"
    assert clean["author"] == "engineer_chen"
    assert clean["sort_key"] == "created_at"
    assert clean["author_id"] == 42
    # Ensure secrets are still stripped
    assert "api_key" not in clean
    assert "authorization" not in clean


def test_startup_sweep_marks_orphans_as_interrupted(runner_fixture: tuple[DatabaseManager, CrawlTaskRunner]) -> None:
    db, runner = runner_fixture
    db.create_crawl_task("t1", "query", "aras")
    db.create_crawl_task("t2", "crawl", "tdc")
    db.update_crawl_task_status("t2", "running")
    db.create_crawl_task("t3", "done_task", "aras")
    db.update_crawl_task_status("t3", "succeeded")

    swept = runner.startup_sweep()
    assert swept == 2

    t1 = db.get_crawl_task("t1")
    assert t1 is not None
    assert t1["status"] == "interrupted"
    assert "restart" in t1["error_message"].lower()

    t2 = db.get_crawl_task("t2")
    assert t2 is not None
    assert t2["status"] == "interrupted"

    t3 = db.get_crawl_task("t3")
    assert t3 is not None
    assert t3["status"] == "succeeded"


def test_task_execution_success_and_artifact(runner_fixture: tuple[DatabaseManager, CrawlTaskRunner]) -> None:
    db, runner = runner_fixture

    def worker(ctx: CrawlTaskContext) -> None:
        ctx.update_progress(percent=50, stage="processing")
        artifact_file = ctx.downloads_dir / f"{ctx.task_id}.xlsx"
        artifact_file.write_text("dummy artifact content", encoding="utf-8")
        ctx.set_artifact(artifact_file)

    task_id = runner.submit_task("export", "aras", {"query": "test"}, worker)

    # Wait for completion
    for _ in range(50):
        t = runner.get_task(task_id)
        if t and t["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)

    task = runner.get_task(task_id)
    assert task is not None
    assert task["status"] == "succeeded"
    assert task["artifact_path"] == f"{task_id}.xlsx"
    assert "50" in task["progress_json"]
    runner.shutdown(wait=True)


def test_task_cooperative_cancellation(runner_fixture: tuple[DatabaseManager, CrawlTaskRunner]) -> None:
    db, runner = runner_fixture
    started = threading.Event()

    def long_worker(ctx: CrawlTaskContext) -> None:
        started.set()
        for _ in range(100):
            if ctx.is_cancelled:
                return
            time.sleep(0.05)

    task_id = runner.submit_task("long_task", "aras", {}, long_worker)
    assert started.wait(timeout=2.0)

    # Cancel while running
    cancelled = runner.cancel_task(task_id)
    assert cancelled is True

    # Wait for task state
    for _ in range(50):
        t = runner.get_task(task_id)
        if t and t["status"] == "cancelled":
            break
        time.sleep(0.05)

    task = runner.get_task(task_id)
    assert task is not None
    assert task["status"] == "cancelled"
    runner.shutdown(wait=True)


def test_per_source_mutual_exclusion(runner_fixture: tuple[DatabaseManager, CrawlTaskRunner]) -> None:
    """Aras tasks must run with single concurrency: task 2 waits until task 1 finishes."""
    db, runner = runner_fixture
    execution_order: list[str] = []
    t1_started = threading.Event()
    t1_finish_allowed = threading.Event()

    def worker_1(ctx: CrawlTaskContext) -> None:
        execution_order.append("t1_start")
        t1_started.set()
        t1_finish_allowed.wait(timeout=2.0)
        execution_order.append("t1_end")

    def worker_2(ctx: CrawlTaskContext) -> None:
        execution_order.append("t2_start")
        execution_order.append("t2_end")

    runner.submit_task("t1", "aras", {}, worker_1)
    assert t1_started.wait(timeout=2.0)
    # While t1 is holding the aras lock, submit t2 with same source
    tid2 = runner.submit_task("t2", "aras", {}, worker_2)

    # Short delay to ensure t2 has arrived and is waiting on the lock
    time.sleep(0.1)
    assert "t2_start" not in execution_order

    # Now let t1 finish
    t1_finish_allowed.set()

    # Wait for both to complete
    for _ in range(50):
        t2 = runner.get_task(tid2)
        if t2 and t2["status"] == "succeeded":
            break
        time.sleep(0.05)

    assert execution_order == ["t1_start", "t1_end", "t2_start", "t2_end"]
    runner.shutdown(wait=True)


def test_no_thread_pool_starvation_across_sources(runner_fixture: tuple[DatabaseManager, CrawlTaskRunner]) -> None:
    """
    Submitting multiple tasks for 'aras' must not block a 'tdc' task from executing
    concurrently on the second thread of ThreadPoolExecutor(max_workers=2).
    """
    db, runner = runner_fixture
    events: list[str] = []
    aras1_started = threading.Event()
    tdc_finished = threading.Event()
    aras1_allow_finish = threading.Event()

    def aras_worker1(ctx: CrawlTaskContext) -> None:
        events.append("aras1_start")
        aras1_started.set()
        aras1_allow_finish.wait(timeout=2.0)
        events.append("aras1_end")

    def aras_worker2(ctx: CrawlTaskContext) -> None:
        events.append("aras2_start")
        events.append("aras2_end")

    def tdc_worker(ctx: CrawlTaskContext) -> None:
        events.append("tdc_start")
        events.append("tdc_end")
        tdc_finished.set()

    # Submit 2 Aras tasks
    runner.submit_task("a1", "aras", {}, aras_worker1)
    assert aras1_started.wait(timeout=2.0)
    runner.submit_task("a2", "aras", {}, aras_worker2)

    # Now submit TDC task - it MUST execute immediately without waiting for aras1 to finish!
    runner.submit_task("t1", "tdc", {}, tdc_worker)
    assert tdc_finished.wait(timeout=2.0)

    # Verify TDC finished while aras1 was still running
    assert "tdc_start" in events
    assert "tdc_end" in events
    assert "aras1_end" not in events
    assert "aras2_start" not in events

    # Allow aras1 to finish
    aras1_allow_finish.set()

    for _ in range(50):
        if "aras2_end" in events:
            break
        time.sleep(0.05)

    assert "aras2_end" in events
    runner.shutdown(wait=True)


def test_cancel_queued_source_task_instant(runner_fixture: tuple[DatabaseManager, CrawlTaskRunner]) -> None:
    """Cancelling a task waiting in the source queue should cancel it before it ever runs."""
    db, runner = runner_fixture
    t1_started = threading.Event()
    t1_finish = threading.Event()
    t2_executed = threading.Event()

    def worker_1(ctx: CrawlTaskContext) -> None:
        t1_started.set()
        t1_finish.wait(timeout=2.0)

    def worker_2(ctx: CrawlTaskContext) -> None:
        t2_executed.set()

    runner.submit_task("t1", "aras", {}, worker_1)
    assert t1_started.wait(timeout=2.0)

    # Submit t2 (which will wait in queue for aras)
    tid2 = runner.submit_task("t2", "aras", {}, worker_2)

    # Cancel t2 while it is in the queue
    cancelled = runner.cancel_task(tid2)
    assert cancelled is True

    # Allow t1 to finish
    t1_finish.set()

    time.sleep(0.1)
    assert not t2_executed.is_set()

    t2_row = runner.get_task(tid2)
    assert t2_row is not None
    assert t2_row["status"] == "cancelled"
    runner.shutdown(wait=True)


def test_cancel_of_executor_queued_task_keeps_source_usable(tmp_path: Path) -> None:
    """Cancelling a task whose future is still pending in a saturated executor
    must release its source slot; otherwise the source would queue forever."""
    db = DatabaseManager(db_path=tmp_path / "executor_queue_test.db")
    db.init_database()
    runner = CrawlTaskRunner(db=db, downloads_dir=tmp_path / "downloads", max_workers=1)

    started = threading.Event()
    release = threading.Event()

    def blocker(ctx: CrawlTaskContext) -> None:
        started.set()
        release.wait(timeout=2.0)

    runner.submit_task("block", "aras", {}, blocker)
    assert started.wait(timeout=2.0)

    # The executor is saturated: this future stays pending and never starts.
    queued_tid = runner.submit_task("queued", "tdc", {}, lambda ctx: None)
    assert runner.cancel_task(queued_tid) is True
    release.set()

    done = threading.Event()

    def quick(ctx: CrawlTaskContext) -> None:
        done.set()

    runner.submit_task("after", "tdc", {}, quick)
    assert done.wait(timeout=2.0), "tdc source stuck after cancelling an executor-queued task"
    runner.shutdown(wait=True)


def test_task_handler_registration_and_retry(runner_fixture: tuple[DatabaseManager, CrawlTaskRunner]) -> None:
    """Test registering task handlers and retrying a failed task."""
    db, runner = runner_fixture
    attempts = 0

    def export_handler(ctx: CrawlTaskContext) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("First run network failure")
        ctx.update_progress(percent=100)

    runner.register_handler("model_export", export_handler)

    # Submit initial task
    tid1 = runner.submit_task("model_export", "tdc", {"model_id": "M100"})

    # Wait for failure
    for _ in range(50):
        t1 = runner.get_task(tid1)
        if t1 and t1["status"] == "failed":
            break
        time.sleep(0.05)

    t1 = runner.get_task(tid1)
    assert t1 is not None
    assert t1["status"] == "failed"
    assert "First run network failure" in (t1.get("error_message") or "")

    # Retry the failed task
    tid2 = runner.retry_task(tid1)
    assert tid2 != tid1

    # Wait for retry to succeed
    for _ in range(50):
        t2 = runner.get_task(tid2)
        if t2 and t2["status"] == "succeeded":
            break
        time.sleep(0.05)

    t2 = runner.get_task(tid2)
    assert t2 is not None
    assert t2["status"] == "succeeded"
    assert attempts == 2
    runner.shutdown(wait=True)
