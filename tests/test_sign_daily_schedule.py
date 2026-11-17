# -*- coding: utf-8 -*-
"""日报工作日 08:30 生成与当天补生成（DSH-V2-23，C4 调度契约的日报部分）。

覆盖主控冻结的契约：

1. 工作日 08:30 到点生成一次；周末不产槽；
2. 重复 tick / 新调度器实例（模拟重启）不重复生成；
3. 未保存 form -> ``not_configured`` 失败，不刷新、不写表；
4. 刷新会话失效 -> ``session_required`` 退避 300 秒；第二次成功则 succeeded，
   第二次仍失效则 failed（不伪报成功）；
5. 刷新成功但数据日期仍早于当天 -> 不用旧数据冒充当天（refresh_failed）；
6. 生成失败保留上次成功日报（同槽 INSERT OR IGNORE，latest 不变）；
7. 状态门禁 blocked 仍记录生成，``exportBlocked=true``；
8. 只生成不发送：不调用 ``mail.build_eml``、不产生 .eml 文件；
9. 日报 fixed 绑定不关闭 interval 同步；SYNC 绑定仍然替换 interval；
10. 未注册 job 的残留槽 -> ``job_unavailable``；
11. ``GET/PUT /api/p/sign-daily/schedule`` 与 ``GET .../scheduled/latest``。

全部使用真实 SQLite（``tmp_path``）+ 真实插件迁移 + 真实 ``SlotStore`` 租约 +
真实 ``services.project_status_scheduler`` 调度器 + 真实 sign_daily compose；
抓取任务用假 runner（同步执行真实 ``make_refresh_worker``）与假归档结果，
不读真实数据库、不访问网络、不发邮件。
"""

from __future__ import annotations

import importlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import web.app as web_app
from core.db_manager import DatabaseManager
from core.time_rules import BEIJING_OFFSET, to_beijing
from services import schedule_jobs
from services import schedule_policy as SP
from services.deliverable_form_analysis import build_form_snapshot, form_definition
from services.project_status_scheduler import ProjectStatusSyncScheduler
from services.schedule_slots import SYNC_CONTROL_TABLE_PREFIX, SlotStore, utc_text

REPO_ROOT = Path(__file__).resolve().parent.parent
API = "/api/p/sign-daily"
DAILY_PROJECT = "sign-daily"
DAILY_JOB = SP.DAILY_REPORT_JOB_ID
HEADERS = form_definition("tdc_data_model")["headerRows"][0]
SCOPE = {"projects": ["F610M"], "departments": [], "region": "车体区域"}
MONDAY = date(2024, 5, 6)
TUESDAY = date(2024, 5, 7)
SATURDAY = date(2024, 5, 11)
BEIJING = BEIJING_OFFSET
REPORTS_TABLE = "p_sign_daily_scheduled_reports"


def bj(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    """构造北京时间 aware datetime。"""
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=BEIJING)


class Clock:
    """可推进的注入时钟（aware datetime，不读全局时钟）。"""

    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def set(self, value: datetime) -> None:
        self.value = value


class FakeSyncRunner:
    """项目状态同步 runner 桩：只记录 interval 路径的 run_once 调用。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_once(
        self,
        deliverable_id: str | None = None,
        dry_run: bool = False,
        trigger_type: str = "scheduled",
        validate_runtime_prerequisites: bool = True,
    ) -> Any:
        self.calls.append(str(deliverable_id))
        return None


class FakeArchive:
    """归档服务桩：``result`` 就是 ``sync_now`` 的返回值（假 refresh 结果）。"""

    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.result = result or {"exitCode": 0, "results": [{"outcome": "completed"}]}
        self.calls: list[str] = []

    def sync_now(self, job_key: str) -> dict[str, Any]:
        self.calls.append(job_key)
        return self.result


class _TaskContext:
    """抓取任务上下文桩（make_refresh_worker 只用到这两样）。"""

    def __init__(self, task: dict[str, Any]) -> None:
        self._task = task
        self.is_cancelled = False

    def update_progress(self, **values: Any) -> None:
        self._task["progress_json"] = json.dumps(values)


class FakeCrawlRunner:
    """抓取任务执行器桩：同步执行真实 worker_fn，任务状态由归档结果决定。"""

    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, Any]] = {}
        self.submitted: list[dict[str, Any]] = []
        self._seq = 0

    def list_tasks(self, status: str | None = None, source: str | None = None, limit: int = 50):
        return [
            task
            for task in self.tasks.values()
            if (source is None or task.get("source") == source)
            and task.get("status") in ("queued", "running")
        ][:limit]

    def submit_task(self, task_type, source, params, worker_fn=None, *, task_id=None):
        self._seq += 1
        tid = task_id or f"crawl_test_{self._seq}"
        task = {
            "task_id": tid,
            "task_type": task_type,
            "source": source,
            "status": "queued",
            "progress_json": "{}",
            "error_message": None,
        }
        self.tasks[tid] = task
        self.submitted.append({"task_type": task_type, "source": source, "worker_fn": worker_fn})
        try:
            worker_fn(_TaskContext(task))
        except Exception as exc:  # 真实 runner 把 worker 异常落成 failed + error_message
            task["status"] = "failed"
            task["error_message"] = str(exc)
        else:
            task["status"] = "succeeded"
        return tid

    def get_task(self, task_id: str):
        return self.tasks.get(task_id)

    def add_running(self, source: str = "sign-daily") -> str:
        tid = f"crawl_running_{len(self.tasks) + 1}"
        self.tasks[tid] = {
            "task_id": tid,
            "task_type": "sign_daily_refresh",
            "source": source,
            "status": "running",
            "progress_json": "{}",
            "error_message": None,
        }
        return tid


def _row(serial: str, **values: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "流水单号": serial,
        "项目/车型": "F610M",
        "部门": "车身科",
        "申请人": "林锦辉",  # 花名册：车身科
        "申请日期": "2024-05-01 10:00:00",
        "零件号": f"{serial}-P1",
        "零件名称": "前门铰链",
        "应签人数": 2,
        "已签人数": 1,
        "未签人数": 1,
        "签署率": "50.00%",
        "状态": "进行中",
        "冲压": "冲压丁(未签)",
        "待审批人员": "冲压丁",
    }
    base.update(values)
    return base


def _rows(status: str = "进行中") -> list[dict[str, Any]]:
    return [
        _row("S1", 零件名称="前门内板", 状态=status),
        _row("S2", 零件号="S2-P1", 零件名称="前门铰链", 状态=status),
    ]


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """真实库 + 真实插件（sign-daily + sync-control）+ 注入时钟/假抓取。"""
    db_cls = web_app.DatabaseManager
    db_path = tmp_path / "sign-daily-schedule.db"
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(db_path))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(
        plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=["sign-daily", "sync-control"]
    )
    app.config.update(TESTING=True)

    backend = sys.modules["vse_plugins.sign_daily.backend"]
    clock = Clock(bj(MONDAY, 8, 0))
    monkeypatch.setattr(backend, "_DATA_TZ", timezone.utc)
    # /generate 的「今天」跟随注入时钟，保证种下的快照与 form 是同一天。
    monkeypatch.setattr(backend, "_today", lambda: to_beijing(clock.value).date())

    db = db_cls(db_path)
    store = SlotStore(db, SYNC_CONTROL_TABLE_PREFIX, clock=clock)
    crawl = FakeCrawlRunner()
    archive = FakeArchive()
    app.extensions["crawl_task_runner"] = crawl
    app.extensions["scheduled_archive_admin"] = archive

    environment = SimpleNamespace(
        app=app,
        http=app.test_client(),
        db=db,
        clock=clock,
        store=store,
        crawl=crawl,
        archive=archive,
        sync_runner=FakeSyncRunner(),
        backend=backend,
        scheduled=importlib.import_module("vse_plugins.sign_daily.scheduled"),
        mail=importlib.import_module("vse_plugins.sign_daily.mail"),
    )
    try:
        yield environment
    finally:
        # 进程内注册表必须清理，避免测试之间串味。
        schedule_jobs.unregister_job(DAILY_JOB)


def _ok(response):  # type: ignore[no-untyped-def]
    payload = response.get_json()
    assert payload["ok"] is True, payload
    return payload["data"]


def _publish(env: SimpleNamespace, rows: list[dict[str, Any]], snapshot_at: str) -> None:
    positional = [
        {"values": [row.get(header) for header in HEADERS], "sheetName": "Sheet1"}
        for row in rows
    ]
    env.db.publish_deliverable_form_snapshot(
        build_form_snapshot(
            "tdc_data_model", positional, snapshot_at=snapshot_at, source_run_id=1, source="test"
        )
    )


def _save_form(env: SimpleNamespace, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """用 /generate 保存 form（与用户操作同一条路径）。"""
    return _ok(env.http.post(f"{API}/generate", json=payload or SCOPE))


def _bind(env: SimpleNamespace, times: tuple[str, ...] = ("08:30",), paused: bool = False) -> None:
    env.store.set_binding(DAILY_PROJECT, DAILY_JOB, "fixed", list(times), paused)


def _scheduler(env: SimpleNamespace, **kwargs: Any) -> ProjectStatusSyncScheduler:
    return ProjectStatusSyncScheduler(
        env.db,
        kwargs.pop("runner", env.sync_runner),
        clock=lambda: env.clock.value.timestamp(),
        interval=900,
        register_global=False,
        slot_store=kwargs.pop("store", env.store),
        clock_utc=env.clock,
        lease_owner=kwargs.pop("lease_owner", "test-owner"),
        **kwargs,
    )


def _slots(env: SimpleNamespace) -> list[dict[str, Any]]:
    return env.store.list_slots(DAILY_PROJECT, to_beijing(env.clock.value).date())


def _reports(env: SimpleNamespace) -> list[dict[str, Any]]:
    with env.db.get_connection() as conn:
        return [
            dict(row)
            for row in conn.execute(
                f"SELECT * FROM {REPORTS_TABLE} ORDER BY generated_at ASC, rowid ASC"
            ).fetchall()
        ]


def _enable_sync_binding(db: DatabaseManager, deliverable_id: str) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET enabled = 1, mode = 'automatic', "
            "last_success_at = NULL WHERE deliverable_id = ?",
            (deliverable_id,),
        )


# ── 1. 工作日 08:30 生成一次，只生成不发送 ──────────────────────────────────


def test_workday_0830_generates_once_and_never_sends(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _publish(env, _rows(), "2024-05-06T00:10:00Z")
    _save_form(env)
    _bind(env)

    eml_calls: list[dict[str, Any]] = []

    def _forbidden_eml(**kwargs: Any) -> bytes:
        eml_calls.append(kwargs)
        raise AssertionError("定时生成不得构造 .eml")

    monkeypatch.setattr(env.mail, "build_eml", _forbidden_eml)

    env.clock.set(bj(MONDAY, 8, 30))
    _scheduler(env).tick()

    [slot] = _slots(env)
    assert (slot["scheduledTime"], slot["status"], slot["attempt"]) == ("08:30", "succeeded", 1)
    assert slot["leaseToken"] is None

    [report] = _reports(env)
    assert report["slot_key"] == "sign-daily/daily_report/2024-05-06/08:30"
    assert report["data_date"] == "2024-05-06"
    assert report["subject"] == "F610M项目3D单签署进展-车体区域-20240506"
    assert report["html"] and report["text"]
    assert json.loads(report["status_gate_json"])["blocked"] is False
    assert report["export_blocked"] in (0, 1)
    assert json.loads(report["result_json"])["html"] == report["html"]

    # 生成前先刷新：真实 make_refresh_worker 被提交并执行了一次。
    assert [item["task_type"] for item in env.crawl.submitted] == ["sign_daily_refresh"]
    assert env.crawl.submitted[0]["worker_fn"] is not None
    assert env.archive.calls == ["tdc_data_model"]

    # 只生成不发送。
    assert eml_calls == []
    assert list(Path(env.db.db_path).parent.rglob("*.eml")) == []

    # 路由：latest 返回完整结果，schedule 返回摘要与当天槽（不含租约凭据）。
    latest = _ok(env.http.get(f"{API}/scheduled/latest"))
    assert latest["html"] == report["html"] and latest["text"] == report["text"]
    schedule = _ok(env.http.get(f"{API}/schedule"))
    assert schedule["latest"]["slotKey"] == report["slot_key"]
    assert schedule["latest"]["subject"] == report["subject"]
    assert schedule["today"] == [
        {
            "jobId": DAILY_JOB,
            "scheduledTime": "08:30",
            "status": "succeeded",
            "attempt": 1,
            "lastErrorCode": None,
            "nextAttemptAt": None,
        }
    ]
    assert "leaseToken" not in json.dumps(schedule["today"])
    assert "leaseOwner" not in json.dumps(schedule["today"])


# ── 2. 周末不产槽 ────────────────────────────────────────────────────────────


def test_weekend_produces_no_slots(env: SimpleNamespace) -> None:
    _publish(env, _rows(), "2024-05-06T00:10:00Z")
    _save_form(env)
    _bind(env)

    env.clock.set(bj(SATURDAY, 9, 0))
    _scheduler(env).tick()

    assert _slots(env) == []
    assert _reports(env) == []
    assert env.crawl.submitted == []


# ── 3. 重复 tick / 重启不重复生成 ───────────────────────────────────────────


def test_repeated_tick_and_restart_do_not_generate_twice(env: SimpleNamespace) -> None:
    _publish(env, _rows(), "2024-05-06T00:10:00Z")
    _save_form(env)
    _bind(env)
    env.clock.set(bj(MONDAY, 8, 30))

    scheduler = _scheduler(env)
    scheduler.tick()
    scheduler.tick()

    [slot] = _slots(env)
    assert (slot["status"], slot["attempt"]) == ("succeeded", 1)
    assert len(_reports(env)) == 1
    assert len(env.crawl.submitted) == 1

    # 模拟重启：新 SlotStore + 新调度器实例 + 新租约持有者，同一库。
    restarted_store = SlotStore(env.db, SYNC_CONTROL_TABLE_PREFIX, clock=env.clock)
    _scheduler(env, store=restarted_store, lease_owner="restarted-owner").tick()

    [slot] = _slots(env)
    assert (slot["status"], slot["attempt"]) == ("succeeded", 1)
    assert len(_reports(env)) == 1
    assert len(env.crawl.submitted) == 1


# ── 4. 未保存 form -> not_configured（不刷新、不写表）──────────────────────


def test_missing_saved_form_fails_not_configured(env: SimpleNamespace) -> None:
    _publish(env, _rows(), "2024-05-06T00:10:00Z")
    _bind(env)
    env.clock.set(bj(MONDAY, 8, 30))

    _scheduler(env).tick()

    [slot] = _slots(env)
    assert (slot["status"], slot["attempt"], slot["lastErrorCode"]) == ("failed", 1, "not_configured")
    assert slot["nextAttemptAt"] is None
    assert _reports(env) == []
    assert env.crawl.submitted == []


# ── 5. 会话失效：300 秒退避，第二次成功 / 第二次仍失败 ─────────────────────


def _session_failure(env: SimpleNamespace) -> None:
    env.archive.result = {"exitCode": 1, "results": [{"outcome": "failed", "errorType": "credential_invalid"}]}


def test_session_required_backs_off_then_succeeds(env: SimpleNamespace) -> None:
    _publish(env, _rows(), "2024-05-06T00:10:00Z")
    _save_form(env)
    _bind(env)
    _session_failure(env)
    env.clock.set(bj(MONDAY, 8, 30))

    scheduler = _scheduler(env)
    scheduler.tick()

    [slot] = _slots(env)
    assert (slot["status"], slot["attempt"], slot["lastErrorCode"]) == (
        "pending", 1, "session_required"
    )
    assert slot["nextAttemptAt"] == utc_text(bj(MONDAY, 8, 35))
    assert _reports(env) == []

    # 退避未到：不领取、不重试。
    env.clock.set(bj(MONDAY, 8, 34, 59))
    scheduler.tick()
    assert len(env.crawl.submitted) == 1
    assert _reports(env) == []

    # 用户登录后第二次成功。
    env.archive.result = {"exitCode": 0, "results": [{"outcome": "completed"}]}
    env.clock.set(bj(MONDAY, 8, 35))
    scheduler.tick()

    [slot] = _slots(env)
    assert (slot["status"], slot["attempt"], slot["lastErrorCode"]) == ("succeeded", 2, None)
    assert len(_reports(env)) == 1


def test_session_required_twice_fails_without_faking_success(env: SimpleNamespace) -> None:
    _publish(env, _rows(), "2024-05-06T00:10:00Z")
    _save_form(env)
    _bind(env)
    _session_failure(env)
    env.clock.set(bj(MONDAY, 8, 30))

    scheduler = _scheduler(env)
    scheduler.tick()
    env.clock.set(bj(MONDAY, 8, 35))
    scheduler.tick()

    [slot] = _slots(env)
    assert (slot["status"], slot["attempt"], slot["lastErrorCode"]) == (
        "failed", 2, "session_required"
    )
    assert slot["nextAttemptAt"] is None
    assert _reports(env) == []


# ── 6. 刷新成功但数据仍旧：不得用旧数据冒充当天 ────────────────────────────


def test_refresh_success_with_stale_data_is_not_accepted(env: SimpleNamespace) -> None:
    _publish(env, _rows(), "2024-05-06T00:10:00Z")
    _save_form(env)
    _bind(env)

    # 第二天抓取「成功」，但没有产出当天的新快照。
    env.clock.set(bj(TUESDAY, 8, 30))
    scheduler = _scheduler(env)
    scheduler.tick()

    [slot] = _slots(env)
    assert (slot["status"], slot["attempt"], slot["lastErrorCode"]) == (
        "pending", 1, "refresh_failed"
    )
    assert slot["nextAttemptAt"] == utc_text(bj(TUESDAY, 8, 35))
    assert _reports(env) == []

    env.clock.set(bj(TUESDAY, 8, 35))
    scheduler.tick()
    [slot] = _slots(env)
    assert (slot["status"], slot["attempt"]) == ("failed", 2)
    assert _reports(env) == []


# ── 7. 刷新超时 -> refresh_timeout（≤15 分钟）──────────────────────────────


def test_refresh_timeout_retries(env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    _publish(env, _rows(), "2024-05-06T00:10:00Z")
    _save_form(env)
    _bind(env)
    env.crawl.add_running()  # 复用正在运行的任务，永不结束

    job = schedule_jobs.get_job(DAILY_JOB).handler.__self__  # type: ignore[union-attr]
    ticks = iter([0.0, 100.0])
    monkeypatch.setattr(job, "_monotonic", lambda: next(ticks))
    monkeypatch.setattr(job, "_timeout", 1.0)
    monkeypatch.setattr(job, "_sleep", lambda _seconds: None)

    env.clock.set(bj(MONDAY, 8, 30))
    _scheduler(env).tick()

    [slot] = _slots(env)
    assert (slot["status"], slot["attempt"], slot["lastErrorCode"]) == (
        "pending", 1, "refresh_timeout"
    )
    assert slot["nextAttemptAt"] == utc_text(bj(MONDAY, 8, 35))
    assert env.crawl.submitted == []  # 复用在跑的任务，不重复抓取
    assert _reports(env) == []


# ── 8. 生成失败保留上次成功日报 ─────────────────────────────────────────────


def test_generation_failure_keeps_previous_success(env: SimpleNamespace) -> None:
    _publish(env, _rows(), "2024-05-06T00:10:00Z")
    _save_form(env)
    _bind(env)
    env.clock.set(bj(MONDAY, 8, 30))
    _scheduler(env).tick()
    [first] = _reports(env)

    # 第二天：新快照里只有别的项目 -> 范围内没有单（EmptyScope），生成失败。
    _publish(env, [_row("E1", **{"项目/车型": "E50"})], "2024-05-07T00:10:00Z")
    env.clock.set(bj(TUESDAY, 8, 30))
    _scheduler(env).tick()

    [slot] = _slots(env)
    assert (slot["status"], slot["attempt"], slot["lastErrorCode"]) == ("failed", 1, "EmptyScope")
    [kept] = _reports(env)
    assert kept["slot_key"] == first["slot_key"]
    assert kept["generated_at"] == first["generated_at"]
    assert kept["html"] == first["html"]
    latest = _ok(env.http.get(f"{API}/scheduled/latest"))
    assert latest["slotKey"] == first["slot_key"]


# ── 9. 状态门禁 blocked 仍记录生成（exportBlocked=true）────────────────────


def test_status_gate_blocked_still_records_generation(env: SimpleNamespace) -> None:
    _publish(env, _rows(status="3"), "2024-05-06T00:10:00Z")
    _save_form(env)
    _bind(env)
    env.clock.set(bj(MONDAY, 8, 30))

    _scheduler(env).tick()

    [slot] = _slots(env)
    assert slot["status"] == "succeeded"
    [report] = _reports(env)
    gate = json.loads(report["status_gate_json"])
    assert gate["blocked"] is True and gate["codes"] == [{"code": "3", "flows": 2}]
    assert report["export_blocked"] == 1
    latest = _ok(env.http.get(f"{API}/scheduled/latest"))
    assert latest["exportBlocked"] is True and latest["statusGate"]["blocked"] is True


# ── 10. 日报绑定不关闭 interval 同步；SYNC 绑定仍然替换 interval ────────────


def test_daily_binding_does_not_disable_interval_sync(env: SimpleNamespace) -> None:
    _publish(env, _rows(), "2024-05-06T00:10:00Z")
    _save_form(env)
    _bind(env)
    _enable_sync_binding(env.db, "VPI-T2-D2")
    env.clock.set(bj(MONDAY, 8, 30))

    scheduler = _scheduler(env)
    scheduler.tick()
    assert env.sync_runner.calls == ["VPI-T2-D2"]  # 日报 fixed 绑定不关闭 interval

    # SYNC 的 fixed 绑定才替换 interval：当天 16:00 未到点，interval 不再派发。
    env.store.set_binding("main", SP.SYNC_JOB_ID, "fixed", ["16:00"], False)
    env.clock.set(bj(MONDAY, 8, 31))
    scheduler.tick()
    assert env.sync_runner.calls == ["VPI-T2-D2"]
    assert [row["jobId"] for row in _slots(env)] == [DAILY_JOB]


# ── 11. 未注册 job 的残留槽 -> job_unavailable ─────────────────────────────


def test_unregistered_job_leftover_slot_fails_job_unavailable(env: SimpleNamespace) -> None:
    env.store.set_binding("ghost", "ghost_job", "fixed", ["08:30"], False)
    slot = SP.Slot(
        key=SP.SlotKey("ghost", "ghost_job", MONDAY, "08:30"),
        scheduled_at=bj(MONDAY, 8, 30),
    )
    env.store.ensure_slots([slot])
    env.clock.set(bj(MONDAY, 8, 30))

    _scheduler(env).tick()

    [stored] = env.store.list_slots("ghost", MONDAY)
    assert (stored["status"], stored["attempt"], stored["lastErrorCode"]) == (
        "failed", 1, "job_unavailable"
    )
    assert stored["nextAttemptAt"] is None
    assert _reports(env) == []


# ── 12. 路由：GET/PUT /schedule ─────────────────────────────────────────────


def test_schedule_routes_read_write_and_validate(env: SimpleNamespace) -> None:
    initial = _ok(env.http.get(f"{API}/schedule"))
    assert initial["enabled"] is False
    assert initial["time"] == "08:30"
    assert initial["paused"] is False
    assert initial["nextRunAt"] is None
    assert initial["today"] == []
    assert initial["latest"] is None

    enabled = _ok(env.http.put(f"{API}/schedule", json={"enabled": True}))
    assert enabled["enabled"] is True and enabled["time"] == "08:30"
    assert enabled["nextRunAt"] is not None and enabled["nextRunAt"].endswith("+08:00")
    assert env.store.get_binding(DAILY_PROJECT, DAILY_JOB)["mode"] == "fixed"

    paused = _ok(env.http.put(f"{API}/schedule", json={"enabled": True, "time": "07:45", "paused": True}))
    assert (paused["enabled"], paused["time"], paused["paused"]) == (True, "07:45", True)
    assert paused["nextRunAt"] is None

    invalid = env.http.put(f"{API}/schedule", json={"enabled": True, "time": "8点半"})
    assert invalid.status_code == 400
    error = invalid.get_json()["error"]
    assert error["type"] == "ValidationError"
    assert error["message"].startswith("time ")

    assert env.http.put(f"{API}/schedule", json={"enabled": "yes"}).status_code == 400
    assert env.http.put(f"{API}/schedule", json={"enabled": True, "paused": "no"}).status_code == 400

    disabled = _ok(env.http.put(f"{API}/schedule", json={"enabled": False}))
    assert disabled["enabled"] is False and disabled["nextRunAt"] is None
    binding = env.store.get_binding(DAILY_PROJECT, DAILY_JOB)
    assert (binding["mode"], binding["times"]) == ("interval", [])

    assert env.http.get(f"{API}/scheduled/latest").status_code == 404


# ── 13. 注册表契约 ─────────────────────────────────────────────────────────


def test_registry_rejects_sync_job_and_outcome_contract() -> None:
    with pytest.raises(ValueError):
        schedule_jobs.register_job(
            SP.SYNC_JOB_ID,
            make_binding=lambda project_id, times, paused: SP.sync_binding(project_id),
            handler=lambda slot: schedule_jobs.JobOutcome(True),
        )
    with pytest.raises(ValueError):
        schedule_jobs.JobOutcome(True, "boom")
    with pytest.raises(ValueError):
        schedule_jobs.JobOutcome(True, retry=True)
    assert schedule_jobs.JobOutcome(False, "session_required", retry=True).error_code == "session_required"
