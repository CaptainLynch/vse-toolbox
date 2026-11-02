# -*- coding: utf-8 -*-
"""固定时刻执行槽接入唯一后台调度器（DSH-V2-20，C4）。

覆盖主控冻结的调度接线契约：

1. fixed 到点槽派发一次；重复 tick 不重复派发；
2. 模拟重启（新调度器实例 + 新租约持有者，同库）不重复派发；
3. 绑定暂停：``paused_skipped`` 照常落库且不派发（interval 路径也不得绕过暂停）；
4. fixed 项目被 interval 路径跳过（替换而非并存）；0 个 fixed 绑定 → 纯 interval；
5. 槽表不存在（插件未加载/未迁移）→ 一次 warning + 纯 interval，不建表不迁移；
6. run_once 失败 → pending 退避 300 秒 → 第二次失败 failed；非抛出型失败同样落失败；
7. 收尾被 fencing（token 不匹配）只记日志、不重跑；
8. 切换当前项目（另一数据根/库）不重复派发第一个项目的槽；
9. ``SlotStore.list_bindings`` 契约与表前缀等于 ``host.registry.plugin_table_prefix``。

全部使用真实 SQLite（``tmp_path``）+ 真实迁移（``store.migrations()`` 的 v1）+
假 runner + 注入时钟；不读真实数据库、不访问网络。
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

import pytest

import host.registry as host_registry
import services.schedule_policy as sp
from core.db_manager import DatabaseManager
from core.time_rules import BEIJING_OFFSET
from services.project_status_scheduler import ProjectStatusSyncScheduler
from services.schedule_slots import SYNC_CONTROL_TABLE_PREFIX, SlotStore, utc_text

PLUGIN_ID = "sync-control"
PROJECT = "main"
JOB = sp.SYNC_JOB_ID
MONDAY = date(2024, 5, 6)
BEIJING = BEIJING_OFFSET


def bj(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    """构造北京时间 aware datetime。"""
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=BEIJING)


class Clock:
    """可推进的注入时钟（返回 aware datetime，不读全局时钟）。"""

    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def set(self, value: datetime) -> None:
        self.value = value


class FakeRunner:
    """记录 run_once 调用；可注入逐 deliverable 的异常或返回值。"""

    def __init__(
        self,
        errors: dict[str, BaseException] | None = None,
        results: dict[str, Any] | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._errors = errors or {}
        self._results = results or {}

    def run_once(
        self,
        deliverable_id: str | None = None,
        dry_run: bool = False,
        trigger_type: str = "scheduled",
        validate_runtime_prerequisites: bool = True,
    ) -> Any:
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
        return self._results.get(str(deliverable_id))

    @property
    def deliverable_ids(self) -> list[str]:
        return [str(call["deliverable_id"]) for call in self.calls]


class Env:
    """一个真实 SQLite 库 + 已执行迁移的 SlotStore。"""

    def __init__(self, db: DatabaseManager, store: SlotStore, clock: Clock) -> None:
        self.db = db
        self.store = store
        self.clock = clock


def _enable_binding(db: DatabaseManager, deliverable_id: str) -> None:
    """把种子交付物绑定置为可自动同步（enabled=1 + automatic）。"""
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET enabled = 1, mode = 'automatic', "
            "last_success_at = NULL WHERE deliverable_id = ?",
            (deliverable_id,),
        )


def _make_env(tmp_path, name: str = "dispatch.db", *, migrate: bool = True) -> Env:
    db = DatabaseManager(tmp_path / name)
    db.init_database()
    clock = Clock(bj(MONDAY, 9, 30))
    store = SlotStore(db, SYNC_CONTROL_TABLE_PREFIX, clock=clock)
    if migrate:
        assert db.apply_plugin_migrations(PLUGIN_ID, store.migrations()) == 1
    return Env(db, store, clock)


@pytest.fixture()
def env(tmp_path) -> Env:
    """启用 D2/D3 两个交付物绑定的真实库（fixed 派发目标）。"""
    environment = _make_env(tmp_path)
    _enable_binding(environment.db, "VPI-T2-D2")
    _enable_binding(environment.db, "VPI-T2-D3")
    return environment


def make_scheduler(env: Env, runner: FakeRunner, **kwargs: Any) -> ProjectStatusSyncScheduler:
    """用注入时钟构造调度器：epoch clock 与 UTC clock 由同一时刻驱动。"""
    return ProjectStatusSyncScheduler(
        env.db,
        runner,
        clock=lambda: env.clock.value.timestamp(),
        interval=900,
        register_global=False,
        slot_store=env.store,
        clock_utc=env.clock,
        lease_owner=kwargs.pop("lease_owner", "test-owner"),
        **kwargs,
    )


def slots(env: Env, project: str = PROJECT, day: date = MONDAY) -> list[dict[str, Any]]:
    return env.store.list_slots(project, day)


# ── 1. 到点派发一次 + 重复 tick 不重复 ───────────────────────────────────────


def test_due_fixed_slot_dispatches_all_enabled_deliverables_once(env: Env) -> None:
    env.store.set_binding(PROJECT, JOB, "fixed", ["09:00", "16:00"], False)
    runner = FakeRunner()
    scheduler = make_scheduler(env, runner)

    scheduler.tick()

    assert runner.deliverable_ids == ["VPI-T2-D2", "VPI-T2-D3"]
    for call in runner.calls:
        # runner 的 trigger_type 是闭集 {"scheduled", "sync_now"}，不接受 scheduled_fixed。
        assert call["trigger_type"] == "scheduled"
        assert call["validate_runtime_prerequisites"] is False
    stored = slots(env)
    assert [row["scheduledTime"] for row in stored] == ["09:00"]
    assert stored[0]["status"] == "succeeded"
    assert stored[0]["attempt"] == 1
    assert stored[0]["leaseToken"] is None


def test_pause_mid_slot_fails_without_retry_and_never_reruns(env: Env) -> None:
    """暂停打断执行中的槽：落 failed(scheduler_stopped)，恢复后不重跑已执行项。"""
    env.store.set_binding(PROJECT, JOB, "fixed", ["09:00"], False)
    holder: dict[str, Any] = {}

    class PausingRunner(FakeRunner):
        def run_once(self, *args: Any, **kwargs: Any) -> Any:
            result = super().run_once(*args, **kwargs)
            holder["scheduler"].pause()
            return result

    runner = PausingRunner()
    scheduler = make_scheduler(env, runner)
    holder["scheduler"] = scheduler

    scheduler.tick()
    assert runner.deliverable_ids == ["VPI-T2-D2"]
    stored = slots(env)
    assert stored[0]["status"] == "failed"
    assert stored[0]["lastErrorCode"] == "scheduler_stopped"
    assert stored[0]["nextAttemptAt"] is None

    scheduler.resume()
    scheduler.tick()
    assert runner.deliverable_ids == ["VPI-T2-D2"]


def test_repeated_tick_does_not_redispatch(env: Env) -> None:
    env.store.set_binding(PROJECT, JOB, "fixed", ["09:00", "16:00"], False)
    runner = FakeRunner()
    scheduler = make_scheduler(env, runner)

    scheduler.tick()
    scheduler.tick()
    scheduler.tick()

    assert runner.deliverable_ids == ["VPI-T2-D2", "VPI-T2-D3"]
    assert [row["status"] for row in slots(env)] == ["succeeded"]


def test_restart_with_new_scheduler_and_owner_does_not_redispatch(env: Env) -> None:
    """模拟重启：新调度器实例 + 新租约持有者，同一库不得重复派发。"""
    env.store.set_binding(PROJECT, JOB, "fixed", ["09:00", "16:00"], False)
    first = FakeRunner()
    make_scheduler(env, first).tick()
    assert first.deliverable_ids == ["VPI-T2-D2", "VPI-T2-D3"]

    restarted_store = SlotStore(env.db, SYNC_CONTROL_TABLE_PREFIX, clock=env.clock)
    restarted_env = Env(env.db, restarted_store, env.clock)
    second = FakeRunner()
    make_scheduler(restarted_env, second, lease_owner="restarted-owner").tick()

    assert second.calls == []
    assert [row["status"] for row in slots(env)] == ["succeeded"]


# ── 2. 暂停：paused_skipped 落库且不派发 ─────────────────────────────────────


def test_paused_binding_records_paused_skipped_and_never_dispatches(env: Env) -> None:
    env.store.set_binding(PROJECT, JOB, "fixed", ["09:00", "16:00"], True)
    runner = FakeRunner()
    scheduler = make_scheduler(env, runner)

    scheduler.tick()
    scheduler.tick()

    assert runner.calls == []
    stored = slots(env)
    assert [row["status"] for row in stored] == ["paused_skipped"]
    assert stored[0]["attempt"] == 0
    assert stored[0]["leaseToken"] is None


# ── 3. 替换 interval 主路径：fixed 项目跳过、0 个 fixed 走旧路径 ──────────────


def test_fixed_project_is_skipped_by_interval_path(env: Env) -> None:
    """fixed 项目即使当天没有到点槽，interval 路径也不得再派发它的交付物。"""
    env.store.set_binding(PROJECT, JOB, "fixed", ["16:00"], False)
    runner = FakeRunner()
    scheduler = make_scheduler(env, runner)

    scheduler.tick()

    assert runner.calls == []
    assert slots(env) == []


def test_zero_fixed_bindings_is_off_and_interval_path_unchanged(env: Env) -> None:
    runner = FakeRunner()
    scheduler = make_scheduler(env, runner)

    status = scheduler.get_status()
    assert status["fixedBindings"] == 0
    assert status["fixedMode"] == "off"
    assert status["eligibleCount"] == 2

    scheduler.tick()

    # 与 DSH-V2-20 之前完全一致：陈旧绑定逐个补偿同步，不产生任何槽。
    assert runner.deliverable_ids == ["VPI-T2-D2", "VPI-T2-D3"]
    assert all(call["trigger_type"] == "scheduled" for call in runner.calls)
    assert slots(env) == []


def test_status_reports_fixed_mode_on_with_bindings(env: Env) -> None:
    env.store.set_binding(PROJECT, JOB, "fixed", ["09:00"], False)
    scheduler = make_scheduler(env, FakeRunner())

    status = scheduler.get_status()

    assert status["fixedBindings"] == 1
    assert status["fixedMode"] == "on"


# ── 4. 槽表不存在：降级为纯 interval，不建表不迁移 ──────────────────────────


def test_missing_slot_tables_degrade_to_interval_without_migration(
    tmp_path, caplog
) -> None:
    env = _make_env(tmp_path, "no-migrations.db", migrate=False)
    _enable_binding(env.db, "VPI-T2-D2")
    _enable_binding(env.db, "VPI-T2-D3")
    runner = FakeRunner()
    scheduler = make_scheduler(env, runner)

    with caplog.at_level(logging.WARNING, logger="vse_toolbox.sync_scheduler"):
        scheduler.tick()
        scheduler.tick()

    # 纯 interval 路径照常工作（每个 tick 各补偿一次；假 runner 不写 last_success_at）。
    assert runner.deliverable_ids == [
        "VPI-T2-D2",
        "VPI-T2-D3",
        "VPI-T2-D2",
        "VPI-T2-D3",
    ]
    warnings = [r for r in caplog.records if "fixed slot tables are missing" in r.message]
    assert len(warnings) == 1
    assert scheduler.get_status()["fixedMode"] == "off"

    # 不建表、不调用迁移：库内没有 sync-control 的表，插件版本仍是 0。
    with env.db.get_connection() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert not {name for name in tables if name.startswith(SYNC_CONTROL_TABLE_PREFIX)}
    assert env.db.get_plugin_schema_version(PLUGIN_ID) == 0


# ── 5. 失败退避 300 秒 → 第二次失败 failed ───────────────────────────────────


def test_failure_backs_off_then_fails_on_second_attempt(env: Env) -> None:
    env.store.set_binding(PROJECT, JOB, "fixed", ["09:00"], False)
    runner = FakeRunner(errors={"VPI-T2-D2": RuntimeError("connector exploded")})
    scheduler = make_scheduler(env, runner)

    scheduler.tick()

    # 任一失败即停止本槽后续交付物，槽回到 pending 并退避 300 秒。
    assert runner.deliverable_ids == ["VPI-T2-D2"]
    [row] = slots(env)
    assert row["status"] == "pending"
    assert row["attempt"] == 1
    assert row["lastErrorCode"] == "RuntimeError"
    assert row["nextAttemptAt"] == utc_text(bj(MONDAY, 9, 35))
    assert row["leaseToken"] is None

    # 退避未到：不领取、不重跑。
    env.clock.set(bj(MONDAY, 9, 34, 59))
    scheduler.tick()
    assert runner.deliverable_ids == ["VPI-T2-D2"]
    assert slots(env)[0]["status"] == "pending"

    # 退避到期：第二次尝试仍失败 → attempt 用尽，failed（绝不写 succeeded）。
    env.clock.set(bj(MONDAY, 9, 35))
    scheduler.tick()
    assert runner.deliverable_ids == ["VPI-T2-D2", "VPI-T2-D2"]
    [row] = slots(env)
    assert row["status"] == "failed"
    assert row["attempt"] == 2
    assert row["lastErrorCode"] == "RuntimeError"
    assert row["nextAttemptAt"] is None


def test_non_raising_failed_result_is_recorded_as_failure(env: Env) -> None:
    """真实 runner 会把连接器异常吞成 outcome='failed'，槽不得因此写成成功。"""
    env.store.set_binding(PROJECT, JOB, "fixed", ["09:00"], False)
    failed = SimpleNamespace(
        results=(SimpleNamespace(outcome="failed", final_state="failed", error_type="ConnectorError"),)
    )
    runner = FakeRunner(results={"VPI-T2-D2": failed})
    scheduler = make_scheduler(env, runner)

    scheduler.tick()

    assert runner.deliverable_ids == ["VPI-T2-D2"]
    [row] = slots(env)
    assert row["status"] == "pending"
    assert row["lastErrorCode"] == "ConnectorError"
    assert row["nextAttemptAt"] == utc_text(bj(MONDAY, 9, 35))


def test_fenced_finish_is_logged_and_never_rerun(env: Env, monkeypatch) -> None:
    env.store.set_binding(PROJECT, JOB, "fixed", ["09:00"], False)
    runner = FakeRunner()
    scheduler = make_scheduler(env, runner)
    monkeypatch.setattr(env.store, "finish", lambda *a, **k: False)

    scheduler.tick()
    scheduler.tick()

    assert runner.deliverable_ids == ["VPI-T2-D2", "VPI-T2-D3"]
    [row] = slots(env)
    assert row["status"] == "leased"
    assert row["attempt"] == 1


def test_malformed_leased_row_does_not_raise_or_duplicate(env: Env, monkeypatch) -> None:
    """槽行损坏（缺 businessDate）：tick 不得抛出，也不得执行任何交付物。"""
    env.store.set_binding(PROJECT, JOB, "fixed", ["09:00"], False)
    monkeypatch.setattr(
        env.store,
        "lease_next",
        lambda *a, **k: {"projectId": PROJECT, "jobId": JOB, "leaseToken": "deadbeef"},
    )
    runner = FakeRunner()
    scheduler = make_scheduler(env, runner)

    scheduler.tick()  # 不得抛出（调度线程不能因单条坏数据消亡）

    assert runner.calls == []


# ── 6. 切换当前项目不派发 ────────────────────────────────────────────────────


def test_switching_project_does_not_redispatch_the_other_database(tmp_path) -> None:
    """切换当前项目 = 新数据根/新库；旧库的槽不会被再次派发，新库各派发一次。"""
    main_env = _make_env(tmp_path, "main.db")
    _enable_binding(main_env.db, "VPI-T2-D2")
    _enable_binding(main_env.db, "VPI-T2-D3")
    main_env.store.set_binding("main", JOB, "fixed", ["09:00"], False)
    main_runner = FakeRunner()
    main_scheduler = make_scheduler(main_env, main_runner)

    main_scheduler.tick()
    assert main_runner.deliverable_ids == ["VPI-T2-D2", "VPI-T2-D3"]

    # 切到另一个项目：自己的库、自己的槽，派发自己的交付物。
    p2_env = _make_env(tmp_path, "p2.db")
    _enable_binding(p2_env.db, "VPI-T2-D2")
    p2_env.store.set_binding("p2", JOB, "fixed", ["09:00"], False)
    p2_runner = FakeRunner()
    make_scheduler(p2_env, p2_runner, lease_owner="p2-owner").tick()
    assert p2_runner.deliverable_ids == ["VPI-T2-D2"]

    # 再切回第一个项目（同一库、新实例）：不重复派发。
    main_runner_after = FakeRunner()
    make_scheduler(main_env, main_runner_after, lease_owner="back-to-main").tick()
    assert main_runner_after.calls == []
    assert main_runner.deliverable_ids == ["VPI-T2-D2", "VPI-T2-D3"]
    assert [row["status"] for row in slots(main_env)] == ["succeeded"]


# ── 7. SlotStore.list_bindings 契约与表前缀 ─────────────────────────────────


def test_list_bindings_shape_filter_and_order(env: Env) -> None:
    env.store.set_binding(PROJECT, JOB, "fixed", ["9:00", "16:00"], False)
    env.store.set_binding(PROJECT, sp.DAILY_REPORT_JOB_ID, "interval", [])

    everything = env.store.list_bindings()
    assert [row["jobId"] for row in everything] == [sp.DAILY_REPORT_JOB_ID, JOB]
    fixed = env.store.list_bindings("fixed")
    assert len(fixed) == 1
    assert fixed[0] == env.store.get_binding(PROJECT, JOB)
    assert fixed[0]["times"] == ["09:00", "16:00"]
    assert env.store.list_bindings("interval")[0]["mode"] == "interval"

    with pytest.raises(ValueError):
        env.store.list_bindings("cron")


def test_list_bindings_raises_operational_error_when_table_missing(tmp_path) -> None:
    env = _make_env(tmp_path, "no-table.db", migrate=False)
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        env.store.list_bindings("fixed")


def test_table_prefix_matches_plugin_host_contract() -> None:
    assert SYNC_CONTROL_TABLE_PREFIX == host_registry.plugin_table_prefix("sync-control")
