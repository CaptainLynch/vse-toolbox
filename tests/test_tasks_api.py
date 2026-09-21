# -*- coding: utf-8 -*-
"""Comprehensive tests for Unified Tasks API facade and Task Center endpoints."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

import web.app as web_app
from core.db_manager import DatabaseManager
from core.excel_tasks import ApprovedExcelRoots, ExcelTaskRepository
from core.ewo_export_jobs import EWOExportJobs
from services.crawl_task_runner import prune_old_artifacts


@pytest.fixture()
def test_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_file = tmp_path / "tasks_api_test.db"
    db = DatabaseManager(db_path=db_file)
    db.init_database()

    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)

    ewo_dir = tmp_path / "ewo-downloads"
    ewo_dir.mkdir(parents=True, exist_ok=True)

    root_dir = tmp_path / "excel_root"
    root_dir.mkdir(parents=True, exist_ok=True)
    roots = ApprovedExcelRoots({"default": root_dir})
    excel_repo = ExcelTaskRepository(db, roots)

    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db)
    monkeypatch.setattr("core.runtime_paths.app_root", lambda: tmp_path)

    app = web_app.create_app(
        excel_repository=excel_repo,
        allowed_hosts=["aras.example"],
        tdc_allowed_hosts=["tdc.example"],
    )
    app.config.update(TESTING=True)
    client = app.test_client()

    return {
        "db": db,
        "client": client,
        "app": app,
        "downloads_dir": downloads_dir,
        "ewo_dir": ewo_dir,
        "excel_repo": excel_repo,
        "root_dir": root_dir,
    }


def test_api_tasks_empty(test_env) -> None:
    client = test_env["client"]
    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    data = payload["data"]
    assert data["tasks"] == []
    assert data["active_count"] == 0
    assert data["total_count"] == 0


def test_api_tasks_aggregation_and_active_count(test_env) -> None:
    db = test_env["db"]
    client = test_env["client"]

    # 1. Create a crawl task (queued)
    db.create_crawl_task("c1", "ewo_query", "aras")

    # 2. Create another crawl task (succeeded with artifact)
    db.create_crawl_task("c2", "model_export", "tdc")
    db.update_crawl_task_status("c2", "succeeded", artifact_path="model_data.xlsx")
    art_file = test_env["downloads_dir"] / "model_data.xlsx"
    art_file.write_bytes(b"dummy_model_bytes")

    # 3. Create an EWO export job (queued)
    ewo_jobs = EWOExportJobs(db.db_path)
    ewo_jobs.create("default", ["1" * 32, "2" * 32])

    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    data = payload["data"]

    # 2 active tasks: c1 (queued), ewo job (queued)
    assert data["active_count"] == 2
    assert data["total_count"] == 3

    tasks = data["tasks"]
    task_ids = [t["raw_id"] for t in tasks]
    assert "c1" in task_ids
    assert "c2" in task_ids

    # Check c2 has artifact download enabled
    c2_task = next(t for t in tasks if t["raw_id"] == "c2")
    assert c2_task["status"] == "succeeded"
    assert c2_task["can_download"] is True
    assert c2_task["has_artifact"] is True
    assert c2_task["can_cancel"] is False


def test_api_tasks_filtering(test_env) -> None:
    db = test_env["db"]
    client = test_env["client"]

    db.create_crawl_task("c1", "query", "aras")  # active (queued)
    db.create_crawl_task("c2", "query", "tdc")
    db.update_crawl_task_status("c2", "succeeded")  # finished
    db.create_crawl_task("c3", "query", "tdc")
    db.update_crawl_task_status("c3", "failed", error_message="Network error")  # finished

    # Filter active
    resp_active = client.get("/api/tasks?status=active")
    assert resp_active.status_code == 200
    active_tasks = resp_active.get_json()["data"]["tasks"]
    assert len(active_tasks) == 1
    assert active_tasks[0]["raw_id"] == "c1"

    # Filter history
    resp_history = client.get("/api/tasks?status=history")
    assert resp_history.status_code == 200
    history_tasks = resp_history.get_json()["data"]["tasks"]
    assert len(history_tasks) == 2
    history_ids = {t["raw_id"] for t in history_tasks}
    assert history_ids == {"c2", "c3"}

    # Filter category
    resp_crawl = client.get("/api/tasks?category=crawl")
    assert resp_crawl.status_code == 200
    assert len(resp_crawl.get_json()["data"]["tasks"]) == 3

    resp_excel = client.get("/api/tasks?category=excel")
    assert resp_excel.status_code == 200
    assert len(resp_excel.get_json()["data"]["tasks"]) == 0


def test_api_tasks_cancel_crawl_task(test_env) -> None:
    db = test_env["db"]
    client = test_env["client"]

    db.create_crawl_task("crawl_cancel_me", "query", "aras")

    # Cancel via unified API
    resp = client.post("/api/tasks/crawl_cancel_me/cancel")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    # Verify status in DB
    task = db.get_crawl_task("crawl_cancel_me")
    assert task["status"] == "cancelled"

    # Cancelling again should return 409 Conflict
    resp2 = client.post("/api/tasks/crawl_cancel_me/cancel")
    assert resp2.status_code == 409
    assert "already cancelled" in resp2.get_json()["error"]["message"]


def test_api_tasks_cancel_nonexistent_returns_404(test_env) -> None:
    client = test_env["client"]
    resp = client.post("/api/tasks/no_such_task/cancel")
    assert resp.status_code == 404


def test_api_tasks_download_crawl_artifact(test_env) -> None:
    db = test_env["db"]
    client = test_env["client"]
    downloads_dir = test_env["downloads_dir"]

    # Write dummy artifact file
    art_filename = "report_export_2026.xlsx"
    art_file = downloads_dir / art_filename
    art_file.write_bytes(b"PK\x03\x04fake_excel_binary_data")

    db.create_crawl_task("crawl_dl", "export", "aras")
    db.update_crawl_task_status("crawl_dl", "succeeded", artifact_path=art_filename)

    resp = client.get("/api/tasks/crawl_dl/download")
    assert resp.status_code == 200
    assert resp.data == b"PK\x03\x04fake_excel_binary_data"
    assert "attachment" in resp.headers.get("Content-Disposition", "")
    assert art_filename in resp.headers.get("Content-Disposition", "")


def test_api_tasks_download_path_traversal_blocked(test_env) -> None:
    db = test_env["db"]
    client = test_env["client"]

    # Evil task with path traversal
    db.create_crawl_task("crawl_evil", "export", "aras")
    db.update_crawl_task_status("crawl_evil", "succeeded", artifact_path="../../secret.txt")

    resp = client.get("/api/tasks/crawl_evil/download")
    assert resp.status_code in (403, 404)


def test_api_tasks_download_missing_file_returns_404(test_env) -> None:
    db = test_env["db"]
    client = test_env["client"]

    db.create_crawl_task("crawl_missing", "export", "aras")
    db.update_crawl_task_status("crawl_missing", "succeeded", artifact_path="ghost_file.xlsx")

    resp = client.get("/api/tasks/crawl_missing/download")
    assert resp.status_code == 404


def test_api_tasks_cancel_rejects_cross_site(test_env) -> None:
    client = test_env["client"]
    # Sec-Fetch-Site: cross-site should be blocked by _local_web_mutation_error
    resp = client.post(
        "/api/tasks/c1/cancel",
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert resp.status_code == 403


def test_api_tasks_cancel_excel_task(test_env) -> None:
    excel_repo = test_env["excel_repo"]
    client = test_env["client"]
    root_dir = test_env["root_dir"]

    # Create dummy files
    (root_dir / "src.xlsx").write_bytes(b"data")

    from core.excel_tasks import ExcelTaskFileRef
    files = [
        ExcelTaskFileRef("source", "default", "src.xlsx", 0),
        ExcelTaskFileRef("output", "default", "out.xlsx", 0),
    ]
    task = excel_repo.create_task("merge_append", files, "cancel_test_key_1")
    task_id = task["id"]

    # Cancel via unified API using excel_{id}
    resp = client.post(f"/api/tasks/excel_{task_id}/cancel")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    # Check status
    reloaded = excel_repo.get_task(task_id)
    assert reloaded["status"] == "cancelled"


def test_api_tasks_cancel_ewo_job(test_env) -> None:
    db = test_env["db"]
    client = test_env["client"]
    ewo_jobs = EWOExportJobs(db.db_path)
    job = ewo_jobs.create("default", ["3" * 32, "4" * 32])
    job_id = job["id"]

    # Cancel via unified API using ewo_{id}
    resp = client.post(f"/api/tasks/ewo_{job_id}/cancel")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    # Check status in ewo_jobs
    reloaded = ewo_jobs.get(job_id, "default")
    assert reloaded["state"] == "interrupted"

    # Cancelling an already-completed/interrupted job returns 409 Conflict
    resp2 = client.post(f"/api/tasks/ewo_{job_id}/cancel")
    assert resp2.status_code == 409
    assert "already interrupted" in resp2.get_json()["error"]["message"]


def test_api_tasks_download_directory_prefix_collision_blocked(test_env) -> None:
    """A path like downloads_other/foo.txt must be rejected by is_relative_to."""
    db = test_env["db"]
    client = test_env["client"]
    tmp_path = test_env["downloads_dir"].parent
    evil_sibling = tmp_path / "downloads_sibling"
    evil_sibling.mkdir(parents=True, exist_ok=True)
    evil_file = evil_sibling / "secret.txt"
    evil_file.write_text("evil", encoding="utf-8")

    db.create_crawl_task("crawl_prefix_attack", "export", "aras")
    db.update_crawl_task_status(
        "crawl_prefix_attack",
        "succeeded",
        artifact_path="../downloads_sibling/secret.txt",
    )

    resp = client.get("/api/tasks/crawl_prefix_attack/download")
    assert resp.status_code == 403


def test_api_tasks_download_ewo_empty_or_wildcard_rejected(test_env) -> None:
    """Ensure ewo_ or wildcards cannot trigger arbitrary file downloads."""
    client = test_env["client"]
    resp1 = client.get("/api/tasks/ewo_/download")
    assert resp1.status_code == 404

    resp2 = client.get("/api/tasks/ewo_*/download")
    assert resp2.status_code == 404


def test_api_tasks_active_count_accurate_with_small_limit(test_env) -> None:
    """Active count must reflect the true database total even when limit is small."""
    db = test_env["db"]
    client = test_env["client"]

    # Create 5 active crawl tasks
    for i in range(5):
        db.create_crawl_task(f"active_crawl_{i}", "query", "aras")

    # Create 5 finished crawl tasks
    for i in range(5):
        db.create_crawl_task(f"done_crawl_{i}", "query", "aras")
        db.update_crawl_task_status(f"done_crawl_{i}", "succeeded")

    resp = client.get("/api/tasks?limit=2")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert len(data["tasks"]) == 2
    assert data["active_count"] == 5


def test_api_tasks_retry_endpoints(test_env) -> None:
    """Test unified task retry endpoint for crawl, excel, and ewo tasks."""
    db = test_env["db"]
    client = test_env["client"]
    app = test_env["app"]
    runner = app.extensions.get("crawl_task_runner")

    # Register handler for crawl tasks
    if runner is not None:
        runner.register_handler("query", lambda ctx: ctx.update_progress(percent=100))

    # 1. Retry failed crawl task
    db.create_crawl_task("crawl_fail_1", "query", "aras")
    db.update_crawl_task_status("crawl_fail_1", "failed", error_message="timeout")

    resp = client.post("/api/tasks/crawl_fail_1/retry")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["taskId"] == "crawl_fail_1"
    assert data["status"] == "queued"
    assert "newTaskId" in data

    # 2. Retrying a running task returns 409 Conflict
    db.create_crawl_task("crawl_running_1", "query", "aras")
    db.update_crawl_task_status("crawl_running_1", "running")
    resp2 = client.post("/api/tasks/crawl_running_1/retry")
    assert resp2.status_code == 409

    # 3. Retrying an Excel batch task returns 400 (not retry-safe per policy)
    resp3 = client.post("/api/tasks/excel_1/retry")
    assert resp3.status_code in (400, 404)


def test_api_tasks_ewo_retry_frozen_semantics(test_env) -> None:
    """红线：generation_unknown 严禁自动重发（仅人工核查）；interrupted 允许重建任务。"""
    db = test_env["db"]
    client = test_env["client"]
    ewo_jobs = EWOExportJobs(db.db_path)

    # 构造 generation_unknown：claim 进入 generating 后中断
    job = ewo_jobs.create("default", ["5" * 32])
    claimed = ewo_jobs.claim(job["id"], "default")
    ewo_jobs.interrupted(job["id"], "default", claimed["lease_token"])
    assert ewo_jobs.get(job["id"], "default")["state"] == "generation_unknown"

    resp = client.post(f"/api/tasks/ewo_{job['id']}/retry")
    assert resp.status_code == 409
    err = resp.get_json()["error"]
    assert err["type"] == "ManualCheckRequired"

    # 统一列表不得对 generation_unknown 提供自动重试入口
    listing = client.get("/api/tasks").get_json()["data"]["tasks"]
    gen_task = next(t for t in listing if t["raw_id"] == job["id"])
    assert gen_task["can_retry"] is False

    # interrupted（用户在生成前取消）允许重建新任务
    job2 = ewo_jobs.create("otherscope", ["6" * 32])
    ewo_jobs.cancel(job2["id"], "otherscope")
    resp2 = client.post(f"/api/tasks/ewo_{job2['id']}/retry")
    assert resp2.status_code == 200
    data2 = resp2.get_json()["data"]
    assert data2["newTaskId"] != f"ewo_{job2['id']}"
    new_state = ewo_jobs.get_job(data2["newTaskId"].removeprefix("ewo_"))
    assert new_state["state"] == "queued"


def _wait_for_task_terminal(client, task_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/tasks/{task_id}")
        assert resp.status_code == 200
        task = resp.get_json()["data"]
        if not task["is_active"]:
            return task
        time.sleep(0.02)
    raise AssertionError("background task did not finish in time")


def test_async_endpoints_reject_credential_modes(test_env) -> None:
    """凭据红线：密码/Cookie 模式禁止进入后台任务（凭据不入库）。"""
    client = test_env["client"]
    cases = [
        ("/api/aras/paa/crawl-all", {"auth_mode": "password", "username": "u", "password": "SUPERSECRET123"}),
        ("/api/aras/paa/crawl-all", {"cookie": "sid=SECRET-COOKIE"}),
        ("/api/aras/ewo/export", {"auth_mode": "password", "username": "u", "password": "SUPERSECRET123"}),
        ("/api/aras/paa/export", {"headers": {"Authorization": "Bearer SECRET-TOKEN"}}),
        ("/api/tdc/data-model/crawl-all", {"auth_mode": "password", "username": "u", "password": "SUPERSECRET123"}),
        ("/api/tdc/sor/export", {"cookie": "sid=SECRET-COOKIE"}),
    ]
    for endpoint, extra in cases:
        resp = client.post(endpoint, json={"base_url": "http://aras.example" if "aras" in endpoint else "https://tdc.example", **extra})
        assert resp.status_code == 400, endpoint
        err = resp.get_json()["error"]
        assert err["type"] == "AsyncAuthUnsupported", endpoint
        text = resp.get_data(as_text=True)
        assert "SUPERSECRET123" not in text
        assert "SECRET-COOKIE" not in text
        assert "SECRET-TOKEN" not in text


def test_async_endpoints_require_domain_session(test_env) -> None:
    client = test_env["client"]
    resp = client.post("/api/aras/paa/crawl-all", json={"base_url": "http://aras.example", "filters": {}})
    assert resp.status_code == 401
    assert resp.get_json()["error"]["type"] == "DomainSessionRequired"


def test_async_crawl_task_cooperative_cancellation(test_env, monkeypatch) -> None:
    """集成：取消运行中的全量抓取任务，分页边界协作式中止。"""
    app = test_env["app"]
    client = test_env["client"]
    registry = app.extensions.get("domain_sessions")
    assert isinstance(registry, web_app.DomainSessionRegistry)
    registry.mark_authenticated("aras", object())

    class LoopingCrawler:
        def __init__(self, base_url, session=None, timeout=30.0, **kwargs):  # type: ignore[no-untyped-def]
            pass

        def crawl_paa_report_all(  # type: ignore[no-untyped-def]
            self,
            filters=None,
            page_size=50,
            max_pages=20,
            max_records=2000,
            should_stop=None,
            on_page=None,
        ):
            for page in range(1, 500):
                if should_stop is not None and should_stop():
                    raise RuntimeError(f"cancelled at page {page}")
                time.sleep(0.02)
            raise AssertionError("crawl loop should have been cancelled")

    monkeypatch.setattr(web_app, "ArasCrawlerClient", LoopingCrawler)

    resp = client.post("/api/aras/paa/crawl-all", json={"base_url": "http://aras.example", "filters": {}})
    assert resp.status_code == 202
    task_id = resp.get_json()["data"]["taskId"]

    # 等待任务进入运行态后取消
    deadline = time.time() + 5
    status = ""
    while time.time() < deadline:
        status = client.get(f"/api/tasks/{task_id}").get_json()["data"]["status"]
        if status == "running":
            break
        time.sleep(0.02)
    assert status == "running"

    cancel = client.post(f"/api/tasks/{task_id}/cancel")
    assert cancel.status_code == 200

    task = _wait_for_task_terminal(client, task_id)
    assert task["status"] == "cancelled"


def test_async_crawl_task_success_writes_result_artifact(test_env, monkeypatch) -> None:
    """集成：全量抓取任务成功后结果工件可经 /result 端点读取。"""
    app = test_env["app"]
    client = test_env["client"]
    registry = app.extensions.get("domain_sessions")
    assert isinstance(registry, web_app.DomainSessionRegistry)
    registry.mark_authenticated("aras", object())

    class InstantCrawler:
        def __init__(self, base_url, session=None, timeout=30.0, **kwargs):  # type: ignore[no-untyped-def]
            pass

        def crawl_paa_report_all(  # type: ignore[no-untyped-def]
            self,
            filters=None,
            page_size=50,
            max_pages=20,
            max_records=2000,
            should_stop=None,
            on_page=None,
        ):
            if on_page is not None:
                on_page(1, 1)
            from services.aras_crawler import PAAReportPage

            return PAAReportPage(
                rows=[{"_no": "PAA-9", "_auth_type": "Open"}],
                page=1,
                item_ids=["PAAX-1"],
                raw_xml="<xml/>",
            )

    monkeypatch.setattr(web_app, "ArasCrawlerClient", InstantCrawler)

    resp = client.post("/api/aras/paa/crawl-all", json={"base_url": "http://aras.example", "filters": {}})
    assert resp.status_code == 202
    task_id = resp.get_json()["data"]["taskId"]

    task = _wait_for_task_terminal(client, task_id)
    assert task["status"] == "succeeded"
    assert (task.get("progress") or {}).get("percent") == 100

    result = client.get(f"/api/tasks/{task_id}/result")
    assert result.status_code == 200
    data = result.get_json()["data"]
    assert data["count"] == 1
    assert data["item_ids"] == ["PAAX-1"]

    # 结果读取仅限成功任务：查询一个排队任务应得到 409
    db = test_env["db"]
    db.create_crawl_task("crawl_queued_probe", "query", "aras")
    conflict = client.get("/api/tasks/crawl_queued_probe/result")
    assert conflict.status_code == 409


def test_prune_old_artifacts_rotates_downloads(test_env) -> None:
    """W3-2：7 天自动轮换清理仅删除过期工件，保留新文件。"""
    runner = test_env["app"].extensions["crawl_task_runner"]
    downloads = runner.downloads_dir
    old_file = downloads / "old_artifact.csv"
    old_file.write_bytes(b"old")
    fresh_file = downloads / "fresh_artifact.csv"
    fresh_file.write_bytes(b"fresh")
    two_weeks_ago = time.time() - 14 * 86400
    os.utime(old_file, (two_weeks_ago, two_weeks_ago))

    removed = prune_old_artifacts(downloads)
    assert removed == 1
    assert not old_file.exists()
    assert fresh_file.exists()

    # 子目录不受影响
    sub = downloads / "nested"
    sub.mkdir(exist_ok=True)
    (sub / "keep.txt").write_text("keep")
    assert prune_old_artifacts(downloads) == 0
    assert (sub / "keep.txt").exists()


def test_task_center_drawer_ui_structure() -> None:
    """Verify HTML markup for persistent top-bar button and task drawer elements."""
    html_text = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")

    # Persistent top-right button with badge
    assert 'id="task-center-btn"' in html_text
    assert 'id="task-center-badge"' in html_text

    # Slide-out drawer structure
    assert 'id="task-center-drawer-container"' in html_text
    assert 'id="task-center-drawer"' in html_text
    assert 'id="task-drawer-title"' in html_text
    assert 'id="task-drawer-active-count"' in html_text
    assert 'id="task-drawer-refresh-btn"' in html_text
    assert 'id="task-drawer-close-btn"' in html_text

    # Tabs and content containers
    assert 'id="task-tab-active"' in html_text
    assert 'id="task-tab-history"' in html_text
    assert 'id="task-tab-all"' in html_text
    assert 'id="task-drawer-items"' in html_text
    assert 'id="task-drawer-empty"' in html_text


def test_task_center_drawer_js_contract() -> None:
    """Verify JavaScript controller adherence to 1.5s adaptive polling, Safe DOM, elapsed time, and retry."""
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    # Module initialization
    assert "setupTaskCenterDrawer" in js_text

    # Find the setupTaskCenterDrawer function body
    fn_start = js_text.find("function setupTaskCenterDrawer()")
    assert fn_start != -1
    fn_end = js_text.find("document.addEventListener(\"DOMContentLoaded\"", fn_start)
    assert fn_end != -1
    fn_body = js_text[fn_start:fn_end]

    # 1.5s adaptive polling: 1500ms timer
    assert "1500" in fn_body
    assert "setInterval" in fn_body
    assert "clearInterval" in fn_body

    # API endpoints called
    assert 'fetch("/api/tasks?limit=100")' in fn_body
    assert "/cancel" in fn_body
    assert "/retry" in fn_body

    # Elapsed time calculation
    assert "formatElapsed" in fn_body

    # Action buttons: retry and view result
    assert "btn-retry" in fn_body
    assert "btn-view" in fn_body

    # Safe DOM: NO innerHTML used in task drawer controller
    assert "innerHTML" not in fn_body
    assert "replaceChildren" in fn_body
    assert "createElement" in fn_body
    assert "textContent" in fn_body
