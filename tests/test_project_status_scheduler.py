# -*- coding: utf-8 -*-
"""
tests/test_project_status_scheduler.py — 常驻项目状态同步调度线程（C）。

确定性测试：假 clock / 假 runner / 假 stop_event，不触碰真实数据库与网络。
覆盖：
    1. 陈旧绑定（last_success_at 超过 interval 或为空）被执行，
       run_once 收到 deliverable_id / trigger_type='scheduled' /
       validate_runtime_prerequisites=False；
    2. 新鲜绑定（last_success_at 距今不足 interval）被零网络跳过；
    3. 单绑定异常（含 SyncLeaseBusyError）记录后继续，不中断循环；
    4. stop_event 置位后 run_forever 退出；
    5. 无启用绑定时 tick 为 no-op。
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone

import pytest

from core.db_manager import SyncLeaseBusyError
from services.project_status_scheduler import (
    DEFAULT_SYNC_INTERVAL_SECONDS,
    SYNC_INTERVAL_ENV_VAR,
    ProjectStatusSyncScheduler,
    resolve_sync_interval,
    set_global_scheduler,
)


@pytest.fixture(autouse=True)
def _reset_global_scheduler():
    set_global_scheduler(None)
    yield
    set_global_scheduler(None)


class FakeDb:
    """list_eligible_sync_bindings 的最小桩。"""

    def __init__(self, bindings):
        self._bindings = list(bindings)
        self.calls: list[str | None] = []

    def list_eligible_sync_bindings(self, deliverable_id=None):
        self.calls.append(deliverable_id)
        return list(self._bindings)


class FakeRunner:
    """记录 run_once 调用参数；可注入逐 deliverable 的异常。"""

    def __init__(self, errors: dict[str, BaseException] | None = None):
        self.calls: list[dict] = []
        self._errors = errors or {}

    def run_once(self, deliverable_id=None, dry_run=False,
                 trigger_type="scheduled", validate_runtime_prerequisites=True):
        self.calls.append(
            {
                "deliverable_id": deliverable_id,
                "trigger_type": trigger_type,
                "validate_runtime_prerequisites": validate_runtime_prerequisites,
            }
        )
        error = self._errors.get(str(deliverable_id))
        if error is not None:
            raise error


class FakeClock:
    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class ImmediateStopEvent:
    """is_set 恒 False、wait 立即置位的假事件：run_forever 恰好跑一轮。"""

    def __init__(self):
        self.set_calls = 0

    def is_set(self) -> bool:
        return False

    def wait(self, timeout=None) -> bool:
        self.set_calls += 1
        return True

    def set(self) -> None:
        pass


def _binding(deliverable_id: str, last_success_at: str | None) -> dict:
    return {
        "id": len(deliverable_id),
        "deliverable_id": deliverable_id,
        "source_type": "tdc",
        "last_success_at": last_success_at,
    }


def test_stale_and_never_synced_bindings_are_executed_with_cli_contract() -> None:
    """陈旧绑定被执行，参数对齐 main.py CLI 定时先例。"""
    # clock 落在 2026-09-20T12:00:00Z：2026-01-01 的成功时间远超 interval。
    clock = FakeClock(start=1789905600.0)
    db = FakeDb(
        [
            _binding("VPI-T2-D2", "2026-01-01T00:00:00.000Z"),  # 远超 interval
            _binding("VPI-T2-D3", None),  # 从未成功
        ]
    )
    runner = FakeRunner()
    scheduler = ProjectStatusSyncScheduler(db, runner, clock=clock, interval=900)

    scheduler.tick()

    assert [call["deliverable_id"] for call in runner.calls] == [
        "VPI-T2-D2",
        "VPI-T2-D3",
    ]
    for call in runner.calls:
        assert call["trigger_type"] == "scheduled"
        assert call["validate_runtime_prerequisites"] is False
    assert db.calls == [None]


def test_fresh_bindings_are_skipped_without_network() -> None:
    """last_success_at 距今不足 interval 的绑定被跳过（零网络，不调用 runner）。"""
    # clock = 2026-09-20T12:00:00Z；绑定 300 秒前成功（< 900 秒 interval）。
    clock = FakeClock(start=1789905600.0)
    fresh_iso = "2026-09-20T11:55:00.000Z"
    db = FakeDb([_binding("VPI-T2-D2", fresh_iso)])
    runner = FakeRunner()
    scheduler = ProjectStatusSyncScheduler(db, runner, clock=clock, interval=900)

    scheduler.tick()

    assert runner.calls == []
    assert db.calls == [None]


def test_interval_boundary_and_staleness_transition() -> None:
    """同一绑定：刚成功时跳过；clock 前进超过 interval 后变为陈旧并执行。"""
    clock = FakeClock()
    db = FakeDb([_binding("VPI-T2-D5", None)])
    runner = FakeRunner()
    interval = 900
    # 预写一个"刚刚成功"的 last_success_at：直接以当前 clock 对齐。
    success_epoch = clock.now - 100
    db._bindings = [
        _binding(
            "VPI-T2-D5",
            _format_epoch(success_epoch),
        )
    ]
    scheduler = ProjectStatusSyncScheduler(db, runner, clock=clock, interval=interval)

    scheduler.tick()
    assert runner.calls == []  # 新鲜：跳过

    clock.advance(1000)  # 超过 interval：陈旧
    scheduler.tick()
    assert len(runner.calls) == 1
    assert runner.calls[0]["deliverable_id"] == "VPI-T2-D5"


def test_scheduler_respects_individual_binding_interval_minutes() -> None:
    """绑定自定义 interval_minutes 优先于全局调度周期生效。"""
    clock = FakeClock()
    runner = FakeRunner()
    # 绑定配置了 30 分钟 (1800 秒) 周期；全局调度器为 900 秒
    binding = _binding("VPI-T2-D3", _format_epoch(clock.now - 1000))
    binding["interval_minutes"] = 30
    db = FakeDb([binding])

    scheduler = ProjectStatusSyncScheduler(db, runner, clock=clock, interval=900)
    scheduler.tick()
    assert runner.calls == []  # 距上次成功 1000s < 1800s，判定为新鲜跳过

    clock.advance(900)  # 距上次成功 1900s > 1800s，变为陈旧
    scheduler.tick()
    assert len(runner.calls) == 1
    assert runner.calls[0]["deliverable_id"] == "VPI-T2-D3"


def _format_epoch(epoch: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:-3] + "Z"


def test_single_binding_exception_does_not_break_the_loop() -> None:
    """单绑定异常（含 SyncLeaseBusyError）记录后继续处理其余绑定。"""
    clock = FakeClock()
    db = FakeDb(
        [
            _binding("VPI-T2-D2", None),
            _binding("VPI-T2-D3", None),
            _binding("VPI-T2-D5", None),
        ]
    )
    runner = FakeRunner(
        errors={
            "VPI-T2-D2": SyncLeaseBusyError("binding already has an unexpired lease"),
            "VPI-T2-D3": RuntimeError("connector exploded"),
        }
    )
    scheduler = ProjectStatusSyncScheduler(db, runner, clock=clock, interval=900)

    scheduler.tick()  # 不得抛出

    assert [call["deliverable_id"] for call in runner.calls] == [
        "VPI-T2-D2",
        "VPI-T2-D3",
        "VPI-T2-D5",
    ]


def test_no_eligible_bindings_is_a_no_op() -> None:
    db = FakeDb([])
    runner = FakeRunner()
    scheduler = ProjectStatusSyncScheduler(
        db, runner, clock=FakeClock(), interval=900
    )

    scheduler.tick()

    assert runner.calls == []


def test_db_listing_error_is_swallowed_and_tick_returns() -> None:
    """list_eligible_sync_bindings 抛错（如 DB 暂不可用）不让线程消亡。"""
    class BrokenDb:
        def list_eligible_sync_bindings(self, deliverable_id=None):
            raise RuntimeError("database is locked")

    runner = FakeRunner()
    scheduler = ProjectStatusSyncScheduler(
        BrokenDb(), runner, clock=FakeClock(), interval=900
    )

    scheduler.tick()  # 不得抛出

    assert runner.calls == []


def test_run_forever_exits_when_stop_event_set() -> None:
    """stop_event 置位后 run_forever 退出；退出前陈旧绑定已被调度执行。"""
    stop_event = threading.Event()
    db = FakeDb([_binding("VPI-T2-D2", None)])
    runner = FakeRunner()
    scheduler = ProjectStatusSyncScheduler(
        db, runner, clock=FakeClock(), interval=0.01, stop_event=stop_event
    )

    thread = threading.Thread(target=scheduler.run_forever, daemon=True)
    thread.start()
    # 等到第一个 tick 执行完陈旧绑定后停止。
    _wait_until(lambda: len(runner.calls) >= 1, 2.0)
    stop_event.set()
    thread.join(timeout=2.0)

    assert not thread.is_alive(), "scheduler thread did not exit after stop_event"
    assert runner.calls  # 陈旧绑定确实被调度执行


def _wait_until(predicate, timeout: float) -> bool:
    import time

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def test_scheduler_stop_is_idempotent() -> None:
    scheduler = ProjectStatusSyncScheduler(
        FakeDb([]), FakeRunner(), clock=FakeClock(), interval=900
    )
    scheduler.stop()
    scheduler.stop()  # 幂等，不抛出


def test_resolve_interval_env_override_and_fallback(monkeypatch) -> None:
    """环境变量 VSE_PROJECT_STATUS_SYNC_INTERVAL 覆盖默认 900 秒；
    非法值回落默认。"""
    monkeypatch.delenv(SYNC_INTERVAL_ENV_VAR, raising=False)
    assert DEFAULT_SYNC_INTERVAL_SECONDS == 900
    assert resolve_sync_interval() == 900

    monkeypatch.setenv(SYNC_INTERVAL_ENV_VAR, "300")
    assert resolve_sync_interval() == 300

    monkeypatch.setenv(SYNC_INTERVAL_ENV_VAR, "not-a-number")
    assert resolve_sync_interval() == 900

    monkeypatch.setenv(SYNC_INTERVAL_ENV_VAR, "-5")
    assert resolve_sync_interval() == 900

    # 显式参数优先于环境变量。
    assert resolve_sync_interval({"VSE_PROJECT_STATUS_SYNC_INTERVAL": "60"}) == 60


def test_scheduler_default_interval_comes_from_env(monkeypatch) -> None:
    monkeypatch.setenv(SYNC_INTERVAL_ENV_VAR, "60")
    scheduler = ProjectStatusSyncScheduler(FakeDb([]), FakeRunner())
    assert scheduler.interval == 60


def test_scheduler_rejects_non_positive_interval() -> None:
    with pytest.raises(ValueError):
        ProjectStatusSyncScheduler(
            FakeDb([]), FakeRunner(), clock=FakeClock(), interval=0
        )


def test_immediate_stop_event_contract_for_run_forever() -> None:
    """注入"等待即置位"的假 stop_event 时，run_forever 恰好执行一轮 tick
    后退出（不真实休眠，测试确定性）。"""
    db = FakeDb([_binding("VPI-T2-D2", None)])
    runner = FakeRunner()
    scheduler = ProjectStatusSyncScheduler(
        db,
        runner,
        clock=FakeClock(),
        interval=900,
        stop_event=ImmediateStopEvent(),
    )

    scheduler.run_forever()

    assert len(runner.calls) == 1
    assert runner.calls[0]["deliverable_id"] == "VPI-T2-D2"


def test_scheduler_pause_and_resume() -> None:
    db = FakeDb([_binding("VPI-T2-D2", None)])
    runner = FakeRunner()
    scheduler = ProjectStatusSyncScheduler(
        db, runner, clock=FakeClock(), interval=900
    )
    assert not scheduler.is_paused

    scheduler.pause()
    assert scheduler.is_paused
    scheduler.tick()
    assert len(runner.calls) == 0  # 暂停时跳过执行

    scheduler.resume()
    assert not scheduler.is_paused
    scheduler.tick()
    assert len(runner.calls) == 1  # 恢复后正常执行


def test_scheduler_dynamic_interval() -> None:
    scheduler = ProjectStatusSyncScheduler(
        FakeDb([]), FakeRunner(), clock=FakeClock(), interval=900
    )
    assert scheduler.interval == 900
    scheduler.set_interval(300)
    assert scheduler.interval == 300
    with pytest.raises(ValueError):
        scheduler.set_interval(-1)


def test_scheduler_get_status() -> None:
    clock = FakeClock(1_000_000.0)
    db = FakeDb([_binding("VPI-T2-D2", None), _binding("VPI-T2-D3", None)])
    scheduler = ProjectStatusSyncScheduler(
        db, FakeRunner(), clock=clock, interval=900
    )
    status = scheduler.get_status()
    assert status["running"] is True
    assert status["paused"] is False
    assert status["intervalSeconds"] == 900
    assert status["eligibleCount"] == 2
    assert status["nextRunSeconds"] == 900

    scheduler.pause()
    assert scheduler.get_status()["paused"] is True
    assert scheduler.get_status()["nextRunSeconds"] is None


def test_scheduler_trigger_sync_all() -> None:
    db = FakeDb([_binding("VPI-T2-D2", None), _binding("VPI-T2-D3", None)])
    runner = FakeRunner()
    scheduler = ProjectStatusSyncScheduler(
        db, runner, clock=FakeClock(), interval=900
    )
    results = scheduler.trigger_sync_all(force=True)
    assert len(results) == 2
    assert len(runner.calls) == 2
    ids = {c["deliverable_id"] for c in runner.calls}
    assert ids == {"VPI-T2-D2", "VPI-T2-D3"}
    # Contract: trigger_type must be "sync_now" to conform to ProjectStatusSyncRunner contract
    assert all(c["trigger_type"] == "sync_now" for c in runner.calls)


def test_scheduler_trigger_sync_all_contract_compliance() -> None:
    """Verifies that trigger_sync_all does not pass illegal trigger_type to a contract-enforcing runner."""
    class ContractEnforcingRunner:
        def __init__(self):
            self.calls = []

        def run_once(self, deliverable_id: str, trigger_type: str, validate_runtime_prerequisites: bool = True):
            if trigger_type not in {"scheduled", "sync_now"}:
                raise ValueError(f"unsupported project-status trigger_type: {trigger_type}")
            self.calls.append({"deliverable_id": deliverable_id, "trigger_type": trigger_type})
            return None

    db = FakeDb([_binding("VPI-T2-D2", None)])
    runner = ContractEnforcingRunner()
    scheduler = ProjectStatusSyncScheduler(db, runner, interval=900)
    results = scheduler.trigger_sync_all(force=True)
    assert len(results) == 1
    assert results[0]["status"] == "success"
    assert results[0]["deliverableId"] == "VPI-T2-D2"
    assert runner.calls[0]["trigger_type"] == "sync_now"


def test_global_scheduler_registry() -> None:
    from services.project_status_scheduler import (
        get_global_scheduler,
        set_global_scheduler,
    )
    set_global_scheduler(None)
    assert get_global_scheduler() is None

    scheduler = ProjectStatusSyncScheduler(
        FakeDb([]), FakeRunner(), clock=FakeClock(), interval=900
    )
    assert get_global_scheduler() is scheduler
    set_global_scheduler(None)
    assert get_global_scheduler() is None


# ── DSH-V2-20：slot_store 注入（fixed 槽接线） ───────────────────────────────


class BrokenSlotStore:
    """list_bindings 直接抛错的槽存储桩：其余方法一旦被调用即为越界。"""

    def __init__(self, error: BaseException) -> None:
        self._error = error
        self.calls: list[str | None] = []

    def list_bindings(self, mode=None):
        self.calls.append(mode)
        raise self._error

    def list_slots(self, project_id, business_date):
        raise AssertionError("list_slots must not be called when bindings fail")

    def ensure_slots(self, slots):
        raise AssertionError("ensure_slots must not be called when bindings fail")

    def lease_next(self, owner, *, lease_seconds, business_date):
        raise AssertionError("lease_next must not be called when bindings fail")

    def finish(self, key, token, *, ok, error_code=None, retry_after_seconds=None):
        raise AssertionError("finish must not be called when bindings fail")


class RecordingSlotStore:
    """记录 fixed 绑定与入队槽的内存桩（真实槽行为由 test_schedule_dispatch 覆盖）。"""

    def __init__(self, fixed_bindings: list[dict]) -> None:
        self._fixed = list(fixed_bindings)
        self.ensured: list = []
        self.lease_calls = 0

    def list_bindings(self, mode=None):
        return [row for row in self._fixed if mode is None or row["mode"] == mode]

    def list_slots(self, project_id, business_date):
        return []

    def ensure_slots(self, slots):
        self.ensured.extend(slots)
        return len(slots)

    def lease_next(self, owner, *, lease_seconds, business_date):
        self.lease_calls += 1
        return None

    def finish(self, key, token, *, ok, error_code=None, retry_after_seconds=None):
        raise AssertionError("finish must not be called when nothing was leased")


def _fixed_binding(project_id: str = "proj-1") -> dict:
    return {
        "projectId": project_id,
        "jobId": "project_status_sync",
        "mode": "fixed",
        "times": ["09:00", "16:00"],
        "paused": False,
        "updatedAt": "2026-09-20T00:00:00.000000Z",
    }


def test_slot_store_none_keeps_legacy_status_and_interval_path() -> None:
    """slot_store=None：get_status 报 fixedMode=off，interval 路径与旧版一致。"""
    db = FakeDb([_binding("VPI-T2-D2", None)])
    runner = FakeRunner()
    scheduler = ProjectStatusSyncScheduler(db, runner, clock=FakeClock(), interval=900)

    status = scheduler.get_status()
    assert status["fixedBindings"] == 0
    assert status["fixedMode"] == "off"

    scheduler.tick()
    assert [call["deliverable_id"] for call in runner.calls] == ["VPI-T2-D2"]


def test_missing_slot_tables_warn_once_and_keep_interval_path(caplog) -> None:
    """槽表不存在：一次 warning、纯 interval，不建表/不迁移；缺表判定被缓存。"""
    store = BrokenSlotStore(
        sqlite3.OperationalError("no such table: p_sync_control_bindings")
    )
    db = FakeDb([_binding("VPI-T2-D2", None)])
    runner = FakeRunner()
    scheduler = ProjectStatusSyncScheduler(
        db, runner, clock=FakeClock(), interval=900, slot_store=store
    )

    with caplog.at_level(logging.WARNING, logger="vse_toolbox.sync_scheduler"):
        scheduler.tick()
        scheduler.tick()

    # 缺表判定缓存后不再查询（避免每 tick / 每次状态轮询都打 SQLite 错误日志）。
    assert store.calls == ["fixed"]
    warnings = [r for r in caplog.records if "fixed slot tables are missing" in r.message]
    assert len(warnings) == 1
    assert [call["deliverable_id"] for call in runner.calls] == [
        "VPI-T2-D2",
        "VPI-T2-D2",
    ]
    assert scheduler.get_status()["fixedMode"] == "off"


def test_slot_store_listing_error_keeps_interval_path(caplog) -> None:
    """非 no-such-table 的槽表错误同样只降级 fixed，不影响 interval 派发。"""
    store = BrokenSlotStore(RuntimeError("disk I/O error"))
    db = FakeDb([_binding("VPI-T2-D3", None)])
    runner = FakeRunner()
    scheduler = ProjectStatusSyncScheduler(
        db, runner, clock=FakeClock(), interval=900, slot_store=store
    )

    with caplog.at_level(logging.WARNING, logger="vse_toolbox.sync_scheduler"):
        scheduler.tick()

    assert [call["deliverable_id"] for call in runner.calls] == ["VPI-T2-D3"]
    assert any("could not list fixed sync bindings" in r.message for r in caplog.records)


def test_fixed_bindings_disable_interval_dispatch_and_count_in_status() -> None:
    """有 fixed 绑定 → get_status fixedMode=on；interval 路径跳过（替换而非并存）。"""
    clock_utc = lambda: datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)  # noqa: E731
    store = RecordingSlotStore([_fixed_binding("proj-1")])
    db = FakeDb([_binding("VPI-T2-D2", None)])
    runner = FakeRunner()
    scheduler = ProjectStatusSyncScheduler(
        db,
        runner,
        clock=FakeClock(start=1789905600.0),
        interval=900,
        slot_store=store,
        clock_utc=clock_utc,
    )

    status = scheduler.get_status()
    assert status["fixedBindings"] == 1
    assert status["fixedMode"] == "on"

    scheduler.tick()

    assert runner.calls == []  # fixed 项目的交付物不再走 interval 路径
    assert [slot.key.as_text() for slot in store.ensured] == [
        "proj-1/project_status_sync/2026-09-20/09:00",
        "proj-1/project_status_sync/2026-09-20/16:00",
    ]
    assert store.lease_calls == 1  # 无槽可领取：只尝试一次即停止


def test_webui_start_sync_scheduler_injects_slot_store(monkeypatch, tmp_path) -> None:
    """webui 入口把 SlotStore（sync-control 表前缀）注入唯一后台调度器。"""
    import types as _types

    import webui
    from core.db_manager import DatabaseManager
    from services.schedule_slots import SYNC_CONTROL_TABLE_PREFIX, SlotStore

    captured = []

    class FakeThread:
        def __init__(self, target=None, args=(), kwargs=None, name=None, daemon=None):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self):
            self._target(*self._args, **self._kwargs)

    class TempDatabaseManager(DatabaseManager):
        """把默认库重定向到 tmp_path；保留类内静态方法引用（不能替换成函数）。"""

        def __init__(self, db_path=None):
            super().__init__(db_path or (tmp_path / "webui.db"))

    monkeypatch.setattr(webui, "threading", _types.SimpleNamespace(Thread=FakeThread))
    monkeypatch.setattr(
        webui, "_run_sync_scheduler_safely", lambda scheduler: captured.append(scheduler)
    )
    monkeypatch.setattr("core.db_manager.DatabaseManager", TempDatabaseManager)
    monkeypatch.setattr(
        "services.project_status_sync_runner.create_production_registry", lambda: None
    )

    webui._start_sync_scheduler()

    assert len(captured) == 1
    scheduler = captured[0]
    assert isinstance(scheduler, ProjectStatusSyncScheduler)
    assert isinstance(scheduler._slot_store, SlotStore)
    assert scheduler._slot_store.prefix == SYNC_CONTROL_TABLE_PREFIX
    # 插件未加载（本测试不建插件表）：状态显示未开启，且不建表。
    status = scheduler.get_status()
    assert status["fixedBindings"] == 0
    assert status["fixedMode"] == "off"
    with scheduler._slot_store.db.get_connection() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert not {name for name in tables if name.startswith(SYNC_CONTROL_TABLE_PREFIX)}
