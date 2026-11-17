# -*- coding: utf-8 -*-
"""执行槽持久化与租约边界测试（DSH-V2-19，C4 调度契约的持久化部分）。

覆盖主控冻结的存储契约：

1. 唯一键 ``(projectId, jobId, date, time)`` 与 ``'9:00'``/``'09:00'`` 规范化去重；
2. ``host.table_prefix`` + 增量迁移：重复执行幂等、旧库（无新表）可升级且既有表数据不变；
3. 租约边界：最早槽领取、attempt 递增、续租、token fencing、失败不写成 succeeded；
4. 崩溃恢复：租约过期当天重入队一次（``retry_of``），第二次失败（``lease_expired``）；
5. 只补当天：跨天 pending/leased 槽标 expired，不补跑；
6. 暂停：``paused_skipped`` 直接落库，暂停/interval 绑定的槽不被领取；
7. 真实插件宿主加载（真实 ``register``）：只有一条只读路由，信封 + no-store。

全部使用真实 SQLite（``tmp_path``）+ 真实迁移 + 注入时钟；不读真实数据库、不访问网络。
"""

from __future__ import annotations

import ast
import importlib
import sqlite3
import sys
import types
from datetime import date, datetime, time
from pathlib import Path

import pytest

import services.schedule_policy as sp
from core.db_manager import DatabaseManager
from core.time_rules import BEIJING_OFFSET

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO_ROOT / "plugins" / "sync_control"
PACKAGE = "vse_plugins.sync_control"
PLUGIN_ID = "sync-control"
PREFIX = "p_sync_control_"

#: 北京时间固定偏移（中国自 1992 年起无夏令时）。
BEIJING = BEIJING_OFFSET

MONDAY = date(2024, 5, 6)
TUESDAY = date(2024, 5, 7)
PROJECT = "proj-1"
JOB = sp.SYNC_JOB_ID

#: 契约 1 冻结的槽表列集合（逐列对照，防止实现漂移）。
SLOT_COLUMNS = {
    "project_id",
    "job_id",
    "business_date",
    "scheduled_time",
    "status",
    "attempt",
    "retry_of",
    "lease_owner",
    "lease_token",
    "lease_expires_at",
    "next_attempt_at",
    "last_error_code",
    "created_at",
    "updated_at",
}
BINDING_COLUMNS = {"project_id", "job_id", "mode", "times", "paused", "updated_at"}


# ── 夹具与工具 ────────────────────────────────────────────────────────────────


def _plugin_module(name: str):
    """按宿主的装载方式导入插件模块（同目录、同包名 ``vse_plugins.<id>``）。"""
    namespace = sys.modules.get("vse_plugins")
    if namespace is None:
        namespace = types.ModuleType("vse_plugins")
        namespace.__path__ = []  # type: ignore[attr-defined]
        sys.modules["vse_plugins"] = namespace
    if PACKAGE not in sys.modules:
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(PLUGIN_DIR)]  # type: ignore[attr-defined]
        sys.modules[PACKAGE] = package
    return importlib.import_module(f"{PACKAGE}.{name}")


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


class Env:
    """一个真实 SQLite 库 + 已执行迁移的 SlotStore。"""

    def __init__(self, db: DatabaseManager, store, clock: Clock, module) -> None:
        self.db = db
        self.store = store
        self.clock = clock
        self.module = module


@pytest.fixture()
def env(tmp_path: Path) -> Env:
    module = _plugin_module("store")
    db = DatabaseManager(tmp_path / "slots.db")
    db.init_database()
    clock = Clock(bj(MONDAY, 8, 0))
    store = module.SlotStore(db, PREFIX, clock=clock)
    assert db.apply_plugin_migrations(PLUGIN_ID, store.migrations()) == 1
    return Env(db, store, clock, module)


def due_slots(day: date = MONDAY, *, at: tuple[int, int] = (16, 0), paused: bool = False):
    """当天已到点的固定时刻槽（09:00 / 16:00）。"""
    return sp.compute_due_slots(sp.sync_binding(PROJECT, paused=paused), now=bj(day, *at))


def single_slot(day: date = MONDAY, hour: int = 9):
    """只含一个 09:00 槽的入队项。"""
    return sp.SlotKey(PROJECT, JOB, day, time(hour, 0))


def key_of(leased: dict) -> sp.SlotKey:
    return sp.slot_key_from_mapping(leased)


def rows(env: Env, day: date = MONDAY) -> list[dict]:
    return env.store.list_slots(PROJECT, day)


# ── 1. 唯一键与规范化 ────────────────────────────────────────────────────────


def test_unique_key_normalizes_time_and_dedupes(env: Env) -> None:
    slots = due_slots()
    assert [slot.key.as_text() for slot in slots] == [
        "proj-1/project_status_sync/2024-05-06/09:00",
        "proj-1/project_status_sync/2024-05-06/16:00",
    ]
    assert env.store.ensure_slots(slots) == 2

    # 重复入队：Slot / SlotKey / '9:00' 文本键 / 行映射都不新增行
    assert env.store.ensure_slots(slots) == 0
    assert env.store.ensure_slots(["proj-1/project_status_sync/2024-05-06/9:00"]) == 0
    assert env.store.ensure_slots([sp.SlotKey(PROJECT, JOB, MONDAY, time(9, 0))]) == 0
    assert (
        env.store.ensure_slots(
            [
                {
                    "projectId": PROJECT,
                    "jobId": JOB,
                    "businessDate": "2024-05-06",
                    "scheduledTime": "09:00",
                    "status": sp.STATUS_DUE,
                }
            ]
        )
        == 0
    )

    stored = rows(env)
    assert [row["scheduledTime"] for row in stored] == ["09:00", "16:00"]
    assert all(row["status"] == "pending" and row["attempt"] == 0 for row in stored)
    assert stored[0]["retryOf"] is None and stored[0]["leaseToken"] is None


def test_slots_table_enforces_the_four_part_unique_key(env: Env) -> None:
    env.store.ensure_slots([single_slot()])
    with pytest.raises(sqlite3.IntegrityError):
        with env.db.get_connection() as conn:
            conn.execute(
                f"INSERT INTO {env.store.slots_table} "
                "(project_id, job_id, business_date, scheduled_time, status) "
                "VALUES (?, ?, ?, ?, 'pending')",
                (PROJECT, JOB, MONDAY.isoformat(), "09:00"),
            )
    # 不同 projectId 是不同槽：不设全局单例
    assert env.store.ensure_slots([sp.SlotKey("proj-2", JOB, MONDAY, time(9, 0))]) == 1
    assert len(rows(env)) == 1
    assert len(env.store.list_slots("proj-2", MONDAY)) == 1


# ── 2. 迁移：表结构、幂等、旧库升级 ──────────────────────────────────────────


def test_migrations_create_frozen_schema(env: Env) -> None:
    with env.db.get_connection() as conn:
        slot_columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({PREFIX}slots)")}
        binding_columns = {
            row["name"] for row in conn.execute(f"PRAGMA table_info({PREFIX}bindings)")
        }
    assert slot_columns == SLOT_COLUMNS
    assert binding_columns == BINDING_COLUMNS
    assert env.db.get_plugin_schema_version(PLUGIN_ID) == 1


def test_migrations_are_idempotent_and_keep_legacy_data(tmp_path: Path) -> None:
    module = _plugin_module("store")
    db = DatabaseManager(tmp_path / "legacy.db")
    db.init_database()
    with db.get_connection() as conn:
        conn.execute("INSERT INTO projects (name, manager) VALUES (?, ?)", ("旧库项目", "张三"))
        conn.execute("CREATE TABLE IF NOT EXISTS legacy_notes (id INTEGER PRIMARY KEY, note TEXT)")
        conn.execute("INSERT INTO legacy_notes (note) VALUES ('旧表数据')")
        before = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]

    store = module.SlotStore(db, PREFIX, clock=lambda: bj(MONDAY, 8, 0))
    assert db.apply_plugin_migrations(PLUGIN_ID, store.migrations()) == 1
    # 重复执行：不报错、版本不变、不重建表
    assert db.apply_plugin_migrations(PLUGIN_ID, store.migrations()) == 1
    assert db.get_plugin_schema_version(PLUGIN_ID) == 1

    with db.get_connection() as conn:
        # 既有表数据一行不少、一列不改
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == before
        legacy = conn.execute("SELECT name, manager FROM projects WHERE name = ?", ("旧库项目",)).fetchone()
        assert legacy is not None and legacy["manager"] == "张三"
        assert conn.execute("SELECT note FROM legacy_notes").fetchone()["note"] == "旧表数据"
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {f"{PREFIX}slots", f"{PREFIX}bindings"} <= tables
    # 升级后的库可以正常入队与领取
    assert store.ensure_slots([single_slot()]) == 1


# ── 3. 租约领取、续租、fencing ────────────────────────────────────────────────


def test_lease_next_claims_earliest_slot_and_increments_attempt(env: Env) -> None:
    env.clock.set(bj(MONDAY, 16, 0))
    env.store.ensure_slots(due_slots())
    env.store.set_binding(PROJECT, JOB, "fixed", ["9:00", "16:00"], False)

    leased = env.store.lease_next("tray-1", lease_seconds=600, business_date=MONDAY)
    assert leased is not None
    assert leased["scheduledTime"] == "09:00"
    assert leased["businessDate"] == "2024-05-06"
    assert leased["status"] == "leased"
    assert leased["attempt"] == 1
    assert leased["retryOf"] is None
    assert leased["leaseOwner"] == "tray-1"
    assert isinstance(leased["leaseToken"], str) and len(leased["leaseToken"]) == 32
    assert leased["leaseExpiresAt"] == env.module.utc_text(bj(MONDAY, 16, 10))

    second = env.store.lease_next("tray-1", lease_seconds=600, business_date=MONDAY)
    assert second is not None and second["scheduledTime"] == "16:00"
    assert second["attempt"] == 1
    assert second["leaseToken"] != leased["leaseToken"]
    assert env.store.lease_next("tray-1", lease_seconds=600, business_date=MONDAY) is None


def test_renew_extends_only_with_matching_token(env: Env) -> None:
    env.clock.set(bj(MONDAY, 9, 0))
    env.store.ensure_slots([single_slot()])
    env.store.set_binding(PROJECT, JOB, "fixed", ["09:00"], False)
    leased = env.store.lease_next("tray-1", lease_seconds=60, business_date=MONDAY)
    assert leased is not None
    key, token = key_of(leased), leased["leaseToken"]

    assert env.store.renew(key, "not-the-token", 600) is False
    env.clock.set(bj(MONDAY, 9, 0, 30))
    assert env.store.renew(key, token, 600) is True
    [row] = rows(env)
    assert row["leaseExpiresAt"] == env.module.utc_text(bj(MONDAY, 9, 10, 30))

    # 续租生效：原 60 秒租约已过期时也不会被重入队
    env.clock.set(bj(MONDAY, 9, 2))
    assert env.store.lease_next("tray-1", lease_seconds=60, business_date=MONDAY) is None
    [row] = rows(env)
    assert row["status"] == "leased" and row["attempt"] == 1


def test_finish_fences_on_token_mismatch_and_succeeds_once(env: Env) -> None:
    env.clock.set(bj(MONDAY, 9, 0))
    env.store.ensure_slots([single_slot()])
    env.store.set_binding(PROJECT, JOB, "fixed", ["09:00"], False)
    leased = env.store.lease_next("tray-1", lease_seconds=600, business_date=MONDAY)
    assert leased is not None
    key, token = key_of(leased), leased["leaseToken"]

    assert env.store.finish(key, "deadbeef", ok=True) is False
    [row] = rows(env)
    assert row["status"] == "leased" and row["attempt"] == 1 and row["leaseToken"] == token

    assert env.store.finish(key, token, ok=True) is True
    [row] = rows(env)
    assert row["status"] == "succeeded"
    assert row["leaseToken"] is None and row["leaseOwner"] is None
    assert row["lastErrorCode"] is None

    # 重放同一 token 不再改行
    assert env.store.finish(key, token, ok=True) is False
    assert env.store.finish(key, token, ok=False, error_code="late") is False
    [row] = rows(env)
    assert row["status"] == "succeeded"


# ── 4. 崩溃恢复与失败重试 ────────────────────────────────────────────────────


def test_expired_lease_requeues_once_then_fails(env: Env) -> None:
    env.clock.set(bj(MONDAY, 9, 0))
    env.store.ensure_slots([single_slot()])
    env.store.set_binding(PROJECT, JOB, "fixed", ["09:00"], False)

    first = env.store.lease_next("tray-1", lease_seconds=60, business_date=MONDAY)
    assert first is not None and first["attempt"] == 1

    env.clock.set(bj(MONDAY, 9, 1))  # 租约到期（<= now）
    second = env.store.lease_next("tray-1", lease_seconds=60, business_date=MONDAY)
    assert second is not None
    assert second["scheduledTime"] == "09:00"
    assert second["attempt"] == 2
    assert second["retryOf"] == 1
    assert second["leaseToken"] != first["leaseToken"]

    env.clock.set(bj(MONDAY, 9, 2))  # 第二次租约也过期：不再重入队
    assert env.store.lease_next("tray-1", lease_seconds=60, business_date=MONDAY) is None
    [row] = rows(env)
    assert row["status"] == "failed"
    assert row["lastErrorCode"] == "lease_expired"
    assert row["attempt"] == 2
    assert row["leaseToken"] is None and row["leaseOwner"] is None


def test_failure_retries_once_after_backoff_then_fails(env: Env) -> None:
    env.clock.set(bj(MONDAY, 9, 0))
    env.store.ensure_slots([single_slot()])
    env.store.set_binding(PROJECT, JOB, "fixed", ["09:00"], False)

    first = env.store.lease_next("tray-1", lease_seconds=600, business_date=MONDAY)
    assert first is not None
    assert (
        env.store.finish(
            key_of(first), first["leaseToken"], ok=False, error_code="crawl_failed",
            retry_after_seconds=300,
        )
        is True
    )
    [row] = rows(env)
    assert row["status"] == "pending"
    assert row["attempt"] == 1
    assert row["nextAttemptAt"] == env.module.utc_text(bj(MONDAY, 9, 5))
    assert row["lastErrorCode"] == "crawl_failed"
    assert row["leaseToken"] is None

    # 退避未到：不领取
    env.clock.set(bj(MONDAY, 9, 4, 59))
    assert env.store.lease_next("tray-1", lease_seconds=600, business_date=MONDAY) is None

    env.clock.set(bj(MONDAY, 9, 5))
    second = env.store.lease_next("tray-1", lease_seconds=600, business_date=MONDAY)
    assert second is not None and second["attempt"] == 2
    assert (
        env.store.finish(
            key_of(second), second["leaseToken"], ok=False, error_code="crawl_failed",
            retry_after_seconds=300,
        )
        is True
    )
    [row] = rows(env)
    assert row["status"] == "failed"
    assert row["attempt"] == 2
    assert row["lastErrorCode"] == "crawl_failed"
    assert row["nextAttemptAt"] is None
    assert row["status"] != "succeeded"


def test_failure_without_backoff_fails_immediately(env: Env) -> None:
    env.clock.set(bj(MONDAY, 9, 0))
    env.store.ensure_slots([single_slot()])
    env.store.set_binding(PROJECT, JOB, "fixed", ["09:00"], False)
    leased = env.store.lease_next("tray-1", lease_seconds=600, business_date=MONDAY)
    assert leased is not None

    assert env.store.finish(key_of(leased), leased["leaseToken"], ok=False, error_code="boom") is True
    [row] = rows(env)
    assert row["status"] == "failed"
    assert row["attempt"] == 1
    assert row["lastErrorCode"] == "boom"
    assert env.store.lease_next("tray-1", lease_seconds=600, business_date=MONDAY) is None


def test_finish_rejects_backoff_below_five_minutes(env: Env) -> None:
    env.clock.set(bj(MONDAY, 9, 0))
    env.store.ensure_slots([single_slot()])
    env.store.set_binding(PROJECT, JOB, "fixed", ["09:00"], False)
    leased = env.store.lease_next("tray-1", lease_seconds=600, business_date=MONDAY)
    assert leased is not None
    key, token = key_of(leased), leased["leaseToken"]

    with pytest.raises(ValueError, match="300"):
        env.store.finish(key, token, ok=False, error_code="boom", retry_after_seconds=60)
    [row] = rows(env)
    assert row["status"] == "leased" and row["attempt"] == 1

    assert env.store.finish(key, token, ok=False, error_code="boom", retry_after_seconds=300) is True
    [row] = rows(env)
    assert row["status"] == "pending"
    assert row["nextAttemptAt"] == env.module.utc_text(bj(MONDAY, 9, 5))


# ── 5. 只补当天：跨天不补跑 ──────────────────────────────────────────────────


def test_previous_day_slots_expire_without_catch_up(env: Env) -> None:
    env.store.ensure_slots([single_slot(MONDAY), single_slot(TUESDAY)])
    env.store.set_binding(PROJECT, JOB, "fixed", ["09:00"], False)

    env.clock.set(bj(TUESDAY, 9, 5))
    leased = env.store.lease_next("tray-1", lease_seconds=60, business_date=TUESDAY)
    assert leased is not None
    assert leased["businessDate"] == "2024-05-07"
    assert leased["scheduledTime"] == "09:00"

    monday = rows(env, MONDAY)
    assert [row["status"] for row in monday] == ["expired"]
    assert monday[0]["leaseToken"] is None
    tuesday = rows(env, TUESDAY)
    assert [row["status"] for row in tuesday] == ["leased"]


# ── 6. 暂停与 interval 绑定不被领取 ──────────────────────────────────────────


def test_paused_slots_are_stored_skipped_and_never_leased(env: Env) -> None:
    slots = due_slots(paused=True)
    assert {slot.status for slot in slots} == {sp.STATUS_PAUSED_SKIPPED}
    env.store.ensure_slots(slots)
    assert [row["status"] for row in rows(env)] == ["paused_skipped", "paused_skipped"]

    env.clock.set(bj(MONDAY, 16, 0))
    env.store.set_binding(PROJECT, JOB, "fixed", ["09:00", "16:00"], True)
    assert env.store.lease_next("tray-1", lease_seconds=60, business_date=MONDAY) is None
    assert [row["status"] for row in rows(env)] == ["paused_skipped", "paused_skipped"]


def test_interval_binding_is_never_leased(env: Env) -> None:
    env.clock.set(bj(MONDAY, 9, 0))
    env.store.ensure_slots([single_slot()])
    env.store.set_binding(PROJECT, JOB, "interval", [], False)
    binding = env.store.get_binding(PROJECT, JOB)
    assert binding is not None and binding["mode"] == "interval" and binding["times"] == []

    assert env.store.lease_next("tray-1", lease_seconds=60, business_date=MONDAY) is None
    [row] = rows(env)
    assert row["status"] == "pending" and row["attempt"] == 0

    # 切回 fixed 后才允许新调度领取
    env.store.set_binding(PROJECT, JOB, "fixed", ["09:00"], False)
    leased = env.store.lease_next("tray-1", lease_seconds=60, business_date=MONDAY)
    assert leased is not None and leased["scheduledTime"] == "09:00"


def test_slot_without_fixed_binding_is_not_leased(env: Env) -> None:
    env.clock.set(bj(MONDAY, 9, 0))
    env.store.ensure_slots([single_slot()])
    assert env.store.get_binding(PROJECT, JOB) is None
    # 没有显式 fixed 绑定：新调度不接管（禁止旧新两套调度同时执行）
    assert env.store.lease_next("tray-1", lease_seconds=60, business_date=MONDAY) is None

    env.store.set_binding(PROJECT, JOB, "fixed", ["09:00"], True)
    assert env.store.lease_next("tray-1", lease_seconds=60, business_date=MONDAY) is None

    env.store.set_binding(PROJECT, JOB, "fixed", ["9:00"], False)
    assert env.store.lease_next("tray-1", lease_seconds=60, business_date=MONDAY) is not None


def test_set_binding_rejects_mixed_or_unknown_modes(env: Env) -> None:
    with pytest.raises(ValueError):
        env.store.set_binding(PROJECT, JOB, "cron", ["09:00"], False)
    with pytest.raises(ValueError):
        env.store.set_binding(PROJECT, JOB, "interval", ["09:00"], False)
    with pytest.raises(ValueError):
        env.store.set_binding(PROJECT, JOB, "fixed", [], False)
    with pytest.raises(TypeError):
        env.store.set_binding(PROJECT, JOB, "fixed", ["09:00"], "yes")  # type: ignore[arg-type]


# ── 7. 真实插件宿主加载：路由面（DSH-V2-21 起含绑定读写） ────────────────────


def test_plugin_registers_slots_and_binding_routes(monkeypatch, tmp_path: Path) -> None:
    import web.app as web_app

    db_cls = web_app.DatabaseManager
    db_file = tmp_path / "plugin.db"
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(db_file))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)

    app = web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=[PLUGIN_ID])
    app.config.update(TESTING=True)
    client = app.test_client()

    manifest = client.get("/api/host/manifest").get_json()["data"]
    record = next(item for item in manifest["plugins"] if item["id"] == PLUGIN_ID)
    assert record["status"] == "loaded", record.get("error")

    plugin_rules = {
        rule.rule: set(rule.methods or ())
        for rule in app.url_map.iter_rules()
        if rule.rule.startswith(f"/api/p/{PLUGIN_ID}/")
    }
    # DSH-V2-21 增加绑定读写路由：/slots 与 /binding 仍只读，写入口只有 PUT binding。
    assert set(plugin_rules) == {
        f"/api/p/{PLUGIN_ID}/slots",
        f"/api/p/{PLUGIN_ID}/binding",
        f"/api/p/{PLUGIN_ID}/binding/<project_id>",
    }
    assert plugin_rules[f"/api/p/{PLUGIN_ID}/slots"] == {"GET", "HEAD", "OPTIONS"}
    assert plugin_rules[f"/api/p/{PLUGIN_ID}/binding"] == {"GET", "HEAD", "OPTIONS"}
    assert plugin_rules[f"/api/p/{PLUGIN_ID}/binding/<project_id>"] == {"PUT", "OPTIONS"}

    # 插件迁移已在本库执行：写入两个项目的槽，只读路由按 projectId 隔离返回
    module = _plugin_module("store")
    writer = module.SlotStore(db_cls(db_file), PREFIX, clock=lambda: bj(MONDAY, 8, 0))
    writer.ensure_slots([sp.SlotKey(PROJECT, JOB, MONDAY, time(9, 0))])
    writer.ensure_slots([sp.SlotKey("proj-2", JOB, MONDAY, time(16, 0))])

    response = client.get(f"/api/p/{PLUGIN_ID}/slots?projectId={PROJECT}&date=2024-05-06")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    body = response.get_json()
    assert body["ok"] is True
    assert body["data"]["projectId"] == PROJECT
    assert body["data"]["businessDate"] == "2024-05-06"
    assert [row["scheduledTime"] for row in body["data"]["slots"]] == ["09:00"]
    assert body["data"]["slots"][0]["status"] == "pending"
    # 租约 token 是收尾 fencing 凭据，只读路由不外露（字段整体缺席，与取值无关）。
    assert "leaseToken" not in body["data"]["slots"][0]

    empty = client.get(f"/api/p/{PLUGIN_ID}/slots?projectId=proj-2&date=2024-05-07").get_json()
    assert empty["data"]["slots"] == []


def test_slots_route_validates_parameters(monkeypatch, tmp_path: Path) -> None:
    import web.app as web_app

    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "plugin.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=[PLUGIN_ID])
    app.config.update(TESTING=True)
    client = app.test_client()

    missing = client.get(f"/api/p/{PLUGIN_ID}/slots")
    assert missing.status_code == 400
    assert missing.get_json()["error"]["type"] == "ValidationError"
    assert missing.headers["Cache-Control"] == "no-store"

    bad_date = client.get(f"/api/p/{PLUGIN_ID}/slots?projectId={PROJECT}&date=2024-5-6")
    assert bad_date.status_code == 400
    assert bad_date.get_json()["error"]["type"] == "ValidationError"

    # 省略 date：默认北京时间当天
    today = client.get(f"/api/p/{PLUGIN_ID}/slots?projectId={PROJECT}").get_json()["data"]
    assert len(today["businessDate"]) == 10


def test_backend_wires_no_scheduler_or_timer() -> None:
    tree = ast.parse((PLUGIN_DIR / "backend.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module)
    assert not any(name.startswith(("threading", "sched", "asyncio", "apscheduler")) for name in imported)
    assert not any("scheduler" in name for name in imported)
    assert not any(name == "web" or name.startswith("web.") for name in imported)
