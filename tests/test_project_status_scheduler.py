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

import threading

import pytest

from core.db_manager import SyncLeaseBusyError
from services.project_status_scheduler import (
    DEFAULT_SYNC_INTERVAL_SECONDS,
    SYNC_INTERVAL_ENV_VAR,
    ProjectStatusSyncScheduler,
    resolve_sync_interval,
)


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
