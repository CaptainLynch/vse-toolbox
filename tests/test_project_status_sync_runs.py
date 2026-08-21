# -*- coding: utf-8 -*-
"""M1 调度领域模型：迁移、租约、同步运行、artifact 与脱敏测试。"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest

from core.db_manager import (
    CURRENT_SCHEMA_VERSION,
    DatabaseManager,
    SyncBindingNotReadyError,
    SyncLeaseBusyError,
    SyncLeaseLostError,
)
from services.project_status_updates import (
    ConnectorCandidate,
    ConnectorSnapshot,
    ProjectStatusUpdateService,
    SyncResult,
)


# ── 公共 fixture ────────────────────────────────────────────────


@pytest.fixture()
def db(tmp_path) -> DatabaseManager:
    manager = DatabaseManager(db_path=tmp_path / "sync.db")
    manager.init_database()
    return manager


@pytest.fixture()
def service(db: DatabaseManager) -> ProjectStatusUpdateService:
    return ProjectStatusUpdateService(db)


def _enable_pilot_binding(service: ProjectStatusUpdateService) -> int:
    """启用 VPI-T2-D5 试点绑定并返回 binding_id。"""
    service.update_update_policy(
        "VPI-T2-D5",
        {
            "mode": "hybrid",
            "enabled": True,
            "externalKey": "FM-1",
            "matchRule": {"incident": "FM-1"},
            "mapping": {"owner": "currentApprover", "note": "approvalComment"},
            "fieldAuthority": {"owner": "automatic", "note": "automatic"},
        },
    )
    binding = _get_binding(db := service._db, "VPI-T2-D5")
    return int(binding["id"])


def _get_binding(db: DatabaseManager, deliverable_id: str):
    return db.get_sync_binding_by_deliverable(deliverable_id)


def _current_updated_at(db: DatabaseManager, deliverable_id: str) -> str:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT updated_at FROM project_status_deliverables WHERE id = ?",
            (deliverable_id,),
        ).fetchone()
    assert row is not None
    return str(row["updated_at"])


def _matched_snapshot(db: DatabaseManager, **field_values) -> ConnectorSnapshot:
    return ConnectorSnapshot(
        match_state="matched",
        candidates=[
            ConnectorCandidate(
                external_key="FM-1",
                external_version="v-001",
                field_values=field_values,
                fetched_at="2026-08-20T00:00:00.000Z",
            )
        ],
        external_version="v-001",
        fetched_at="2026-08-20T00:00:00.000Z",
        expected_deliverable_updated_at=_current_updated_at(db, "VPI-T2-D5"),
    )


# ── 1. 新数据库直接初始化最终 schema ───────────────────────────


def test_new_db_has_final_schema(db: DatabaseManager) -> None:
    with db.get_connection() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == CURRENT_SCHEMA_VERSION

        columns = {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(project_status_update_bindings)"
            )
        }
        for expected in (
            "cursor_json",
            "credential_ref",
            "lease_token",
            "lease_acquired_at",
            "lease_expires_at",
            "retry_policy_json",
        ):
            assert expected in columns

        tables = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "project_status_sync_runs" in tables
        assert "project_status_sync_artifacts" in tables


# ── 2. 旧 schema 增量升级不丢数据 ──────────────────────────────


def test_old_schema_upgrade_preserves_data(tmp_path) -> None:
    legacy = tmp_path / "legacy.db"
    # 用旧字段集合手工建库，模拟迁移前状态。
    with sqlite3.connect(str(legacy)) as conn:
        conn.executescript(
            """
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                manager TEXT, status TEXT DEFAULT 'active',
                created_at TEXT DEFAULT (datetime('now','localtime')),
                updated_at TEXT DEFAULT (datetime('now','localtime')));
            CREATE TABLE project_status_phases (
                id TEXT PRIMARY KEY, status TEXT NOT NULL, start_date TEXT NOT NULL,
                end_date TEXT NOT NULL, simulated_today TEXT NOT NULL,
                overall_progress INTEGER NOT NULL, planned_progress INTEGER NOT NULL,
                updated_at TEXT NOT NULL);
            CREATE TABLE project_status_deliverables (
                id TEXT PRIMARY KEY, phase_id TEXT NOT NULL, name TEXT NOT NULL,
                status TEXT NOT NULL, owner TEXT NOT NULL, planned_date TEXT NOT NULL,
                actual_date TEXT, progress INTEGER NOT NULL, remark TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL, sort_order INTEGER NOT NULL, updated_at TEXT NOT NULL,
                FOREIGN KEY (phase_id) REFERENCES project_status_phases(id) ON DELETE CASCADE);
            CREATE TABLE project_status_update_bindings (
                id INTEGER PRIMARY KEY AUTOINCREMENT, deliverable_id TEXT NOT NULL UNIQUE,
                mode TEXT NOT NULL DEFAULT 'manual', source_type TEXT NOT NULL DEFAULT 'tdc',
                external_key TEXT, match_rule_json TEXT NOT NULL DEFAULT '{}',
                mapping_json TEXT NOT NULL DEFAULT '{}', enabled INTEGER NOT NULL DEFAULT 0,
                interval_minutes INTEGER, last_attempt_at TEXT, last_success_at TEXT,
                sync_state TEXT NOT NULL DEFAULT 'idle', last_error_type TEXT,
                last_error_message TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                FOREIGN KEY (deliverable_id)
                    REFERENCES project_status_deliverables(id) ON DELETE CASCADE);
            CREATE TABLE project_status_field_authority (
                deliverable_id TEXT NOT NULL, field_name TEXT NOT NULL,
                authority TEXT NOT NULL, source_type TEXT, locked_at TEXT,
                updated_at TEXT NOT NULL, PRIMARY KEY (deliverable_id, field_name));
            CREATE TABLE project_status_update_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, deliverable_id TEXT NOT NULL,
                trigger_type TEXT NOT NULL, source_type TEXT, external_version TEXT,
                proposed_changes_json TEXT NOT NULL DEFAULT '{}',
                applied_changes_json TEXT NOT NULL DEFAULT '{}',
                skipped_fields_json TEXT NOT NULL DEFAULT '{}',
                result TEXT NOT NULL, error_summary TEXT, created_at TEXT NOT NULL);
            INSERT INTO projects (id, name, status) VALUES (1,'未归类','active');
            INSERT INTO project_status_phases
                (id,status,start_date,end_date,simulated_today,overall_progress,
                 planned_progress,updated_at)
                VALUES ('VPI-T2','进行中','2026-04-08','2026-08-30','2026-08-13',
                        64,80,'2026-08-13 09:42:00.000');
            INSERT INTO project_status_deliverables
                (id,phase_id,name,status,owner,planned_date,actual_date,progress,
                 remark,source,sort_order,updated_at)
                VALUES ('VPI-T2-D5','VPI-T2','数模审批流程','已逾期','赵岩',
                        '2026-08-08',NULL,82,'逾期 5 天','内网',5,
                        '2026-08-13 09:42:00.000');
            INSERT INTO project_status_update_bindings
                (deliverable_id,mode,source_type,enabled,sync_state,
                 created_at,updated_at)
                VALUES ('VPI-T2-D5','manual','tdc',0,'idle',
                        '2026-08-13 09:42:00.000','2026-08-13 09:42:00.000');
            INSERT INTO project_status_update_audit
                (deliverable_id,trigger_type,source_type,external_version,
                 proposed_changes_json,applied_changes_json,skipped_fields_json,
                 result,error_summary,created_at)
                VALUES ('VPI-T2-D5','manual','none',NULL,'{}','{}','{}',
                        'applied',NULL,'2026-08-13 09:42:00.000');
            PRAGMA user_version = 0;
            """
        )
        conn.commit()

    # 用 DatabaseManager 打开旧库 → 触发增量迁移。
    manager = DatabaseManager(db_path=legacy)
    manager.init_database()

    with manager.get_connection() as conn:
        # 原有绑定数据保留。
        binding = conn.execute(
            "SELECT mode, source_type, enabled, sync_state, cursor_json, "
            "       retry_policy_json FROM project_status_update_bindings "
            "WHERE deliverable_id='VPI-T2-D5'"
        ).fetchone()
        assert binding["mode"] == "manual"
        assert binding["cursor_json"] == "{}"
        assert json.loads(binding["retry_policy_json"])["max_attempts"] == 1
        # 原有审计保留。
        audit = conn.execute(
            "SELECT COUNT(*) AS c FROM project_status_update_audit "
            "WHERE deliverable_id='VPI-T2-D5'"
        ).fetchone()
        assert audit["c"] == 1
        # 版本提升。
        assert conn.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION
        # 新表存在。
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='project_status_sync_runs'"
        ).fetchone() is not None


# ── 3. init_database 重复执行幂等 ──────────────────────────────


def test_init_database_idempotent(db: DatabaseManager) -> None:
    db.init_database()
    db.init_database()
    with db.get_connection() as conn:
        # 绑定行不重复。
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM project_status_update_bindings "
            "WHERE deliverable_id='VPI-T2-D5'"
        ).fetchone()["c"]
        assert count == 1
        assert conn.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION


def test_higher_schema_version_rejected(tmp_path) -> None:
    future = tmp_path / "future.db"
    with sqlite3.connect(str(future)) as conn:
        conn.execute("PRAGMA user_version = 999")
        conn.commit()
    manager = DatabaseManager(db_path=future)
    with pytest.raises(sqlite3.DatabaseError):
        manager.init_database()


def test_concurrent_lease_acquire_only_one_succeeds(
    service: ProjectStatusUpdateService, db: DatabaseManager
) -> None:
    """两个并发运行器竞争同一 binding：有且仅有一个拿到租约。"""
    import threading

    binding_id = _enable_pilot_binding(service)
    results: list[Any] = []
    lock = threading.Lock()

    def attempt():
        try:
            lease = service.acquire_sync_lease("VPI-T2-D5", "scheduled")
            with lock:
                results.append(("ok", lease["lease_token"]))
        except SyncLeaseBusyError:
            with lock:
                results.append(("busy", None))

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ok_count = sum(1 for tag, _ in results if tag == "ok")
    busy_count = sum(1 for tag, _ in results if tag == "busy")
    assert ok_count == 1
    assert busy_count == 3


# ── 4/5. 租约获取与过期抢占 ────────────────────────────────────


def test_acquiring_second_lease_fails(service: ProjectStatusUpdateService, db: DatabaseManager) -> None:
    binding_id = _enable_pilot_binding(service)
    lease = service.acquire_sync_lease("VPI-T2-D5", "scheduled")
    assert lease["binding_id"] == binding_id
    assert lease["lease_token"]
    assert lease["run_id"] > 0

    with pytest.raises(SyncLeaseBusyError):
        service.acquire_sync_lease("VPI-T2-D5", "scheduled")


def test_expired_lease_preemption(service: ProjectStatusUpdateService, db: DatabaseManager) -> None:
    binding_id = _enable_pilot_binding(service)
    old_lease = service.acquire_sync_lease("VPI-T2-D5", "scheduled", lease_seconds=60)

    # 手工把租约过期。
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET lease_expires_at='2020-01-01T00:00:00.000Z' "
            "WHERE id=?",
            (binding_id,),
        )
        conn.commit()

    new_lease = service.acquire_sync_lease("VPI-T2-D5", "scheduled")
    assert new_lease["lease_token"] != old_lease["lease_token"]
    assert new_lease["run_id"] != old_lease["run_id"]

    old_run = db.get_sync_run(old_lease["run_id"])
    assert old_run["run_state"] == "expired"


# ── 6. 错误 token / run_id / 过期不能启动或提交 ─────────────────


def test_wrong_token_cannot_start(service: ProjectStatusUpdateService, db: DatabaseManager) -> None:
    binding_id = _enable_pilot_binding(service)
    lease = service.acquire_sync_lease("VPI-T2-D5", "scheduled")
    with pytest.raises(SyncLeaseLostError):
        db.start_sync_run(binding_id, lease["run_id"], "wrong-token")


def test_wrong_run_id_cannot_start(service: ProjectStatusUpdateService, db: DatabaseManager) -> None:
    binding_id = _enable_pilot_binding(service)
    lease = service.acquire_sync_lease("VPI-T2-D5", "scheduled")
    with pytest.raises(SyncLeaseLostError):
        db.start_sync_run(binding_id, 999999, lease["lease_token"])


def test_expired_token_cannot_finalize(service: ProjectStatusUpdateService, db: DatabaseManager) -> None:
    binding_id = _enable_pilot_binding(service)
    lease = service.acquire_sync_lease("VPI-T2-D5", "scheduled", lease_seconds=60)
    snapshot = _matched_snapshot(db, owner="新负责人")

    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET lease_expires_at='2020-01-01T00:00:00.000Z' "
            "WHERE id=?",
            (binding_id,),
        )
        conn.commit()

    with pytest.raises(SyncLeaseLostError):
        service.apply_sync_update(int(lease["binding_id"]), int(lease["run_id"]),
                                  lease["lease_token"], snapshot, "scheduled")


# ── 前置校验 ────────────────────────────────────────────────────


def test_acquire_rejects_unready_binding(service: ProjectStatusUpdateService, db: DatabaseManager) -> None:
    # 未启用的默认绑定。
    with pytest.raises(SyncBindingNotReadyError):
        service.acquire_sync_lease("VPI-T2-D5", "scheduled")

    # 非试点交付物。
    service.update_update_policy("VPI-T2-D3", {"mode": "manual"})
    with pytest.raises(SyncBindingNotReadyError):
        service.acquire_sync_lease("VPI-T2-D3", "scheduled")


def test_acquire_rejects_invalid_lease_duration(service: ProjectStatusUpdateService, db: DatabaseManager) -> None:
    _enable_pilot_binding(service)
    with pytest.raises(ValueError):
        service.acquire_sync_lease("VPI-T2-D5", "scheduled", lease_seconds=10)
    with pytest.raises(ValueError):
        service.acquire_sync_lease("VPI-T2-D5", "scheduled", lease_seconds=100000)


def test_acquire_rejects_invalid_trigger(service: ProjectStatusUpdateService, db: DatabaseManager) -> None:
    _enable_pilot_binding(service)
    with pytest.raises(ValueError):
        service.acquire_sync_lease("VPI-T2-D5", "manual")


# ── 7/8/9. 成功同步、人工锁、partial ───────────────────────────


def test_successful_sync_updates_automatic_fields(service: ProjectStatusUpdateService, db: DatabaseManager) -> None:
    binding_id = _enable_pilot_binding(service)
    lease = service.acquire_sync_lease("VPI-T2-D5", "scheduled")
    snapshot = _matched_snapshot(db, owner="赵岩2", note="审批通过")

    result = service.apply_sync_update(
        int(lease["binding_id"]), int(lease["run_id"]),
        lease["lease_token"], snapshot, "scheduled",
    )
    assert isinstance(result, SyncResult)
    assert result.final_state == "success"
    assert set(result.applied_fields) == {"owner", "note"}
    assert result.updated_at is not None

    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT owner, remark FROM project_status_deliverables WHERE id='VPI-T2-D5'"
        ).fetchone()
        assert row["owner"] == "赵岩2"
        assert row["remark"] == "审批通过"
        binding = conn.execute(
            "SELECT sync_state, last_success_at, cursor_json, lease_token "
            "FROM project_status_update_bindings WHERE id=?",
            (binding_id,),
        ).fetchone()
        assert binding["sync_state"] == "success"
        assert binding["lease_token"] is None
        assert binding["last_success_at"] is not None
        cursor = json.loads(binding["cursor_json"])
        assert "v-001" in cursor["processed_versions"]


def test_manually_locked_field_not_overwritten(service: ProjectStatusUpdateService, db: DatabaseManager) -> None:
    binding_id = _enable_pilot_binding(service)
    # 手动保存 note 字段 → 建立人工锁。
    service.update_update_policy(
        "VPI-T2-D5",
        {"fieldAuthority": {"note": "manual"}},
    )
    lease = service.acquire_sync_lease("VPI-T2-D5", "scheduled")
    snapshot = _matched_snapshot(db, owner="赵岩2", note="应被跳过")

    result = service.apply_sync_update(
        int(lease["binding_id"]), int(lease["run_id"]),
        lease["lease_token"], snapshot, "scheduled",
    )
    assert result.final_state == "partial"
    assert "owner" in result.applied_fields

    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT owner, remark FROM project_status_deliverables WHERE id='VPI-T2-D5'"
        ).fetchone()
        assert row["owner"] == "赵岩2"
        assert row["remark"] == "逾期 5 天"  # 人工值保留


def test_all_fields_locked_yields_partial_and_cursor_advances(
    service: ProjectStatusUpdateService, db: DatabaseManager
) -> None:
    _enable_pilot_binding(service)
    service.update_update_policy(
        "VPI-T2-D5",
        {"fieldAuthority": {"owner": "manual", "note": "manual"}},
    )
    binding = _get_binding(db, "VPI-T2-D5")
    lease = service.acquire_sync_lease("VPI-T2-D5", "scheduled")
    snapshot = _matched_snapshot(db, owner="x", note="y")

    result = service.apply_sync_update(
        int(lease["binding_id"]), int(lease["run_id"]),
        lease["lease_token"], snapshot, "scheduled",
    )
    assert result.final_state == "partial"
    assert result.applied_fields == ()

    # cursor 仍推进（成功处理过）。
    with db.get_connection() as conn:
        cursor = json.loads(
            conn.execute(
                "SELECT cursor_json FROM project_status_update_bindings WHERE id=?",
                (int(binding["id"]),),
            ).fetchone()["cursor_json"]
        )
        assert "v-001" in cursor["processed_versions"]


# ── 10. external_version 幂等跳过 ──────────────────────────────


def test_idempotent_external_version_skipped(service: ProjectStatusUpdateService, db: DatabaseManager) -> None:
    binding_id = _enable_pilot_binding(service)
    lease = service.acquire_sync_lease("VPI-T2-D5", "scheduled")
    snapshot = _matched_snapshot(db, owner="第一次")

    first = service.apply_sync_update(
        int(lease["binding_id"]), int(lease["run_id"]),
        lease["lease_token"], snapshot, "scheduled",
    )
    assert first.final_state == "success"

    # 第二次同版本。
    lease2 = service.acquire_sync_lease("VPI-T2-D5", "scheduled")
    snapshot2 = ConnectorSnapshot(
        match_state="matched",
        candidates=[ConnectorCandidate(
            external_key="FM-1", external_version="v-001",
            field_values={"owner": "第二次"}, fetched_at="2026-08-20T00:00:00.000Z")],
        external_version="v-001",
        fetched_at="2026-08-20T00:00:00.000Z",
        expected_deliverable_updated_at=_current_updated_at(db, "VPI-T2-D5"),
    )
    second = service.apply_sync_update(
        int(lease2["binding_id"]), int(lease2["run_id"]),
        lease2["lease_token"], snapshot2, "scheduled",
    )
    assert second.final_state == "success"
    # 业务值不变（第一次的值）。
    with db.get_connection() as conn:
        owner = conn.execute(
            "SELECT owner FROM project_status_deliverables WHERE id='VPI-T2-D5'"
        ).fetchone()["owner"]
        assert owner == "第一次"


# ── 11. 乐观锁冲突 ─────────────────────────────────────────────


def test_optimistic_conflict_preserves_manual(service: ProjectStatusUpdateService, db: DatabaseManager) -> None:
    _enable_pilot_binding(service)
    lease = service.acquire_sync_lease("VPI-T2-D5", "scheduled")

    # 快照在人工修改前抓取 → expected_updated_at 为旧值。
    old_updated_at = _current_updated_at(db, "VPI-T2-D5")
    snapshot = ConnectorSnapshot(
        match_state="matched",
        candidates=[ConnectorCandidate(
            external_key="FM-1", external_version="v-conflict",
            field_values={"owner": "自动值"}, fetched_at="2026-08-20T00:00:00.000Z")],
        external_version="v-conflict",
        fetched_at="2026-08-20T00:00:00.000Z",
        expected_deliverable_updated_at=old_updated_at,
    )

    # 在同步提交前，人工修改业务行 → updated_at 变化。
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_deliverables SET owner='人工改', "
            "updated_at=strftime('%Y-%m-%d %H:%M:%f','now','localtime') "
            "WHERE id='VPI-T2-D5'"
        )
        conn.commit()

    result = service.apply_sync_update(
        int(lease["binding_id"]), int(lease["run_id"]),
        lease["lease_token"], snapshot, "scheduled",
    )
    assert result.final_state == "failed"
    assert result.updated_at is None

    # 人工值保留，cursor 不推进。
    with db.get_connection() as conn:
        owner = conn.execute(
            "SELECT owner FROM project_status_deliverables WHERE id='VPI-T2-D5'"
        ).fetchone()["owner"]
        assert owner == "人工改"
        cursor = json.loads(
            conn.execute(
                "SELECT cursor_json FROM project_status_update_bindings "
                "WHERE deliverable_id='VPI-T2-D5'"
            ).fetchone()["cursor_json"]
        )
        assert cursor == {} or "processed_versions" not in cursor or "v-001" not in cursor.get(
            "processed_versions", []
        )


# ── 12. not_found / ambiguous 不写业务表 ───────────────────────


@pytest.mark.parametrize("state", ["not_found", "ambiguous"])
def test_no_match_does_not_write_business(
    service: ProjectStatusUpdateService, db: DatabaseManager, state: str
) -> None:
    binding_id = _enable_pilot_binding(service)
    lease = service.acquire_sync_lease("VPI-T2-D5", "scheduled")
    snapshot = ConnectorSnapshot(
        match_state=state,
        candidates=[],
        external_version="v-002",
        fetched_at="2026-08-20T00:00:00.000Z",
        expected_deliverable_updated_at=_current_updated_at(db, "VPI-T2-D5"),
    )
    result = service.apply_sync_update(
        int(lease["binding_id"]), int(lease["run_id"]),
        lease["lease_token"], snapshot, "scheduled",
    )
    assert result.final_state == "needs_attention"

    with db.get_connection() as conn:
        owner = conn.execute(
            "SELECT owner FROM project_status_deliverables WHERE id='VPI-T2-D5'"
        ).fetchone()["owner"]
        assert owner == "赵岩"  # 种子值不变
        cursor = json.loads(
            conn.execute(
                "SELECT cursor_json FROM project_status_update_bindings WHERE id=?",
                (binding_id,),
            ).fetchone()["cursor_json"]
        )
        assert "v-002" not in cursor.get("processed_versions", [])


def test_external_key_mismatch_yields_needs_attention(
    service: ProjectStatusUpdateService, db: DatabaseManager
) -> None:
    _enable_pilot_binding(service)
    lease = service.acquire_sync_lease("VPI-T2-D5", "scheduled")
    snapshot = ConnectorSnapshot(
        match_state="matched",
        candidates=[ConnectorCandidate(
            external_key="WRONG", external_version="v-003",
            field_values={"owner": "x"}, fetched_at="2026-08-20T00:00:00.000Z")],
        external_version="v-003",
        fetched_at="2026-08-20T00:00:00.000Z",
        expected_deliverable_updated_at=_current_updated_at(db, "VPI-T2-D5"),
    )
    result = service.apply_sync_update(
        int(lease["binding_id"]), int(lease["run_id"]),
        lease["lease_token"], snapshot, "scheduled",
    )
    assert result.final_state == "needs_attention"


# ── 13. connector 失败保留最后成功数据 ─────────────────────────


def test_connector_failure_preserves_last_success(
    service: ProjectStatusUpdateService, db: DatabaseManager
) -> None:
    binding_id = _enable_pilot_binding(service)
    # 先成功一次。
    lease = service.acquire_sync_lease("VPI-T2-D5", "scheduled")
    service.apply_sync_update(
        int(lease["binding_id"]), int(lease["run_id"]),
        lease["lease_token"], _matched_snapshot(db, owner="成功值"), "scheduled",
    )

    # 再失败一次。
    lease2 = service.acquire_sync_lease("VPI-T2-D5", "scheduled")
    result = service.finalize_sync_failure(
        int(lease2["binding_id"]), int(lease2["run_id"]),
        lease2["lease_token"], "connector_error",
        "HTTP 500 password=secret cookie=session123",
    )
    assert result.final_state == "failed"

    with db.get_connection() as conn:
        owner = conn.execute(
            "SELECT owner FROM project_status_deliverables WHERE id='VPI-T2-D5'"
        ).fetchone()["owner"]
        assert owner == "成功值"  # 最后成功值保留
        binding = conn.execute(
            "SELECT last_success_at, cursor_json, lease_token, sync_state "
            "FROM project_status_update_bindings WHERE id=?",
            (binding_id,),
        ).fetchone()
        assert binding["lease_token"] is None
        assert binding["sync_state"] == "failed"
        # cursor 与 last_success_at 不变。
        cursor = json.loads(binding["cursor_json"])
        assert "v-001" in cursor["processed_versions"]


# ── 14. 成功事务任一步骤异常整体回滚 ───────────────────────────


def test_success_transaction_rollback_on_internal_error(
    service: ProjectStatusUpdateService, db: DatabaseManager, monkeypatch
) -> None:
    binding_id = _enable_pilot_binding(service)
    lease = service.acquire_sync_lease("VPI-T2-D5", "scheduled")
    snapshot = _matched_snapshot(db, owner="回滚测试")

    original = DatabaseManager._update_project_status_deliverable_row

    def boom(*args, **kwargs):
        # 先让业务更新成功，再在写入审计前抛错 → 整事务回滚。
        result = original(*args, **kwargs)
        raise sqlite3.OperationalError("injected failure after update")

    monkeypatch.setattr(DatabaseManager, "_update_project_status_deliverable_row", staticmethod(boom))

    with pytest.raises(sqlite3.OperationalError):
        service.apply_sync_update(
            int(lease["binding_id"]), int(lease["run_id"]),
            lease["lease_token"], snapshot, "scheduled",
        )

    # 业务行未变，cursor 未推进。
    with db.get_connection() as conn:
        owner = conn.execute(
            "SELECT owner FROM project_status_deliverables WHERE id='VPI-T2-D5'"
        ).fetchone()["owner"]
        assert owner == "赵岩"
        cursor = json.loads(
            conn.execute(
                "SELECT cursor_json FROM project_status_update_bindings WHERE id=?",
                (binding_id,),
            ).fetchone()["cursor_json"]
        )
        assert "v-001" not in cursor.get("processed_versions", [])
        # 租约仍在（事务回滚未释放），但可被过期抢占回收。
        binding = conn.execute(
            "SELECT lease_token, sync_state FROM project_status_update_bindings WHERE id=?",
            (binding_id,),
        ).fetchone()
        assert binding["lease_token"] is not None
        assert binding["sync_state"] == "running"


# ── 15. 脱敏：密码/Cookie/token 不出现在 audit/run/error ───────


def test_secrets_redacted_from_audit_and_run(
    service: ProjectStatusUpdateService, db: DatabaseManager
) -> None:
    _enable_pilot_binding(service)
    lease = service.acquire_sync_lease("VPI-T2-D5", "scheduled")
    snapshot = ConnectorSnapshot(
        match_state="matched",
        candidates=[ConnectorCandidate(
            external_key="FM-1", external_version="v-secret",
            field_values={"owner": "ok password=hunter2 cookie=abc123 token=xyz"},
            fetched_at="2026-08-20T00:00:00.000Z")],
        external_version="v-secret",
        fetched_at="2026-08-20T00:00:00.000Z",
        expected_deliverable_updated_at=_current_updated_at(db, "VPI-T2-D5"),
    )
    service.apply_sync_update(
        int(lease["binding_id"]), int(lease["run_id"]),
        lease["lease_token"], snapshot, "scheduled",
    )

    with db.get_connection() as conn:
        audits = conn.execute(
            "SELECT proposed_changes_json, applied_changes_json, error_summary "
            "FROM project_status_update_audit WHERE deliverable_id='VPI-T2-D5'"
        ).fetchall()
        blob = json.dumps([dict(a) for a in audits])
        assert "hunter2" not in blob
        assert "abc123" not in blob
        assert "xyz" not in blob

        run = conn.execute(
            "SELECT result_summary, error_message FROM project_status_sync_runs "
            "WHERE binding_id=?", (int(lease["binding_id"]),)
        ).fetchall()
        run_blob = json.dumps([dict(r) for r in run])
        assert "hunter2" not in run_blob

        # 业务表 owner 列必须被脱敏，不得存原始敏感片段。
        owner = conn.execute(
            "SELECT owner FROM project_status_deliverables WHERE id='VPI-T2-D5'"
        ).fetchone()["owner"]
        assert "hunter2" not in str(owner)
        assert "abc123" not in str(owner)
        assert "[redacted]" in str(owner)


# ── 16. credential_ref/lease_token/cursor_json 不出现在 policy API ─


def test_policy_api_does_not_leak_internal_columns(
    service: ProjectStatusUpdateService, db: DatabaseManager
) -> None:
    _enable_pilot_binding(service)
    # 写入 credential_ref（模拟未来引用名，非凭据本身）。
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET credential_ref='vault-ref-1', "
            "cursor_json='{\"x\":1}' WHERE deliverable_id='VPI-T2-D5'"
        )
        conn.commit()

    policy = service.get_update_policy("VPI-T2-D5")
    assert policy is not None
    serialized = json.dumps(policy, ensure_ascii=False, default=str)
    assert "credential_ref" not in serialized
    assert "lease_token" not in serialized
    assert "lease_acquired_at" not in serialized
    assert "lease_expires_at" not in serialized
    assert "retry_policy_json" not in serialized
    assert "cursor_json" not in serialized
    assert "vault-ref-1" not in serialized


# ── 17. artifact schema 支持一对多 ──────────────────────────────


def test_artifact_one_to_many_metadata(db: DatabaseManager, service: ProjectStatusUpdateService) -> None:
    binding_id = _enable_pilot_binding(service)
    # 将 owner 设为 automatic，使字段可应用。
    service.update_update_policy(
        "VPI-T2-D5",
        {"fieldAuthority": {"owner": "automatic", "note": "automatic"}},
    )
    lease = db.acquire_sync_lease(binding_id, "scheduled")
    expected_at = _current_updated_at(db, "VPI-T2-D5")
    artifacts = [
        {
            "artifact_type": "export_xlsx",
            "relative_path": "runs/1/data.xlsx",
            "display_name": "数模导出.xlsx",
            "size_bytes": 1024,
            "sha256": "abc123",
        },
        {
            "artifact_type": "export_csv",
            "relative_path": "runs/1/data.csv",
            "display_name": "数模导出.csv",
            "size_bytes": 512,
            "sha256": "def456",
        },
    ]
    db.finalize_sync_success(
        binding_id=binding_id,
        run_id=int(lease["run_id"]),
        lease_token=lease["lease_token"],
        deliverable_values={"owner": "x"},
        expected_updated_at=expected_at,
        phase_id="VPI-T2",
        skipped_fields={},
        external_version="v-art",
        proposed_changes_json="{}",
        applied_changes_json="{}",
        trigger_type="scheduled",
        source_type="tdc",
        result_summary="ok",
        artifacts=artifacts,
    )
    rows = db.list_sync_artifacts(int(lease["run_id"]))
    assert len(rows) == 2
    assert {r["artifact_type"] for r in rows} == {"export_xlsx", "export_csv"}


def test_artifact_rejects_absolute_and_traversal_paths(db: DatabaseManager, service: ProjectStatusUpdateService) -> None:
    binding_id = _enable_pilot_binding(service)
    service.update_update_policy(
        "VPI-T2-D5",
        {"fieldAuthority": {"owner": "automatic", "note": "automatic"}},
    )
    lease = db.acquire_sync_lease(binding_id, "scheduled")
    expected_at = _current_updated_at(db, "VPI-T2-D5")
    for bad in ("C:/evil.xlsx", "/etc/passwd", "../escape.xlsx", "runs/../x.xlsx"):
        with pytest.raises(ValueError):
            db.finalize_sync_success(
                binding_id=binding_id,
                run_id=int(lease["run_id"]),
                lease_token=lease["lease_token"],
                deliverable_values={},
                expected_updated_at=expected_at,
                phase_id="VPI-T2",
                skipped_fields={},
                external_version="v-bad",
                proposed_changes_json="{}",
                applied_changes_json="{}",
                trigger_type="scheduled",
                source_type="tdc",
                result_summary="ok",
                artifacts=[{"artifact_type": "x", "relative_path": bad,
                            "display_name": "x", "size_bytes": 1, "sha256": "h"}],
            )


def test_sync_runs_preserved_when_binding_deleted(
    service: ProjectStatusUpdateService, db: DatabaseManager
) -> None:
    """binding_id 无外键 → 删除 binding 后运行历史保留。"""
    binding_id = _enable_pilot_binding(service)
    lease = db.acquire_sync_lease(binding_id, "scheduled")
    db.finalize_sync_failure(
        binding_id, int(lease["run_id"]), lease["lease_token"],
        "test", "preserved", "test failure",
    )
    # 删除交付物（级联删除 binding）。
    with db.get_connection() as conn:
        conn.execute("DELETE FROM project_status_deliverables WHERE id='VPI-T2-D5'")
        conn.commit()
    # sync_runs 仍在。
    run = db.get_sync_run(int(lease["run_id"]))
    assert run is not None
    assert run["run_state"] == "failed"


# ── 20/21. processed_versions 按处理顺序、attempt=1 回归 ─────────


def test_processed_versions_insertion_order_not_lexicographic(
    service: ProjectStatusUpdateService, db: DatabaseManager
) -> None:
    """证明 cursor 按处理顺序保留版本，不是字典序。"""
    binding_id = _enable_pilot_binding(service)
    versions = ["v-2", "v-10", "v-1"]
    for ver in versions:
        lease = db.acquire_sync_lease(binding_id, "scheduled")
        snapshot = ConnectorSnapshot(
            match_state="matched",
            candidates=[ConnectorCandidate(
                external_key="FM-1", external_version=ver,
                field_values={"owner": "ok"}, fetched_at="2026-08-20T00:00:00.000Z")],
            external_version=ver,
            fetched_at="2026-08-20T00:00:00.000Z",
            expected_deliverable_updated_at=_current_updated_at(db, "VPI-T2-D5"),
        )
        service.apply_sync_update(
            int(lease["binding_id"]), int(lease["run_id"]),
            lease["lease_token"], snapshot, "scheduled",
        )

    with db.get_connection() as conn:
        cursor = json.loads(
            conn.execute(
                "SELECT cursor_json FROM project_status_update_bindings WHERE id=?",
                (binding_id,),
            ).fetchone()["cursor_json"]
        )
    # 处理顺序 v-2 → v-10 → v-1，不是字典序 v-1 → v-10 → v-2。
    assert cursor["processed_versions"] == ["v-2", "v-10", "v-1"]


def test_attempt_always_one_across_independent_runs(
    service: ProjectStatusUpdateService, db: DatabaseManager
) -> None:
    """每个独立 run 在 M2A 无重试模式下 attempt=1。"""
    binding_id = _enable_pilot_binding(service)
    for _ in range(3):
        lease = db.acquire_sync_lease(binding_id, "scheduled")
        snapshot = _matched_snapshot(db, owner="ok")
        service.apply_sync_update(
            int(lease["binding_id"]), int(lease["run_id"]),
            lease["lease_token"], snapshot, "scheduled",
        )

    with db.get_connection() as conn:
        attempts = [
            int(row["attempt"])
            for row in conn.execute(
                "SELECT attempt FROM project_status_sync_runs WHERE binding_id=? ORDER BY id",
                (binding_id,),
            )
        ]
    assert attempts == [1, 1, 1]


def test_malformed_cursor_degrades_to_empty(
    service: ProjectStatusUpdateService, db: DatabaseManager
) -> None:
    """malformed cursor_json 安全降级为空 cursor，不崩溃。"""
    binding_id = _enable_pilot_binding(service)
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET cursor_json='not-valid-json' "
            "WHERE id=?",
            (binding_id,),
        )
        conn.commit()

    lease = db.acquire_sync_lease(binding_id, "scheduled")
    snapshot = _matched_snapshot(db, owner="ok")
    # 不应崩溃；cursor 重新从空开始。
    result = service.apply_sync_update(
        int(lease["binding_id"]), int(lease["run_id"]),
        lease["lease_token"], snapshot, "scheduled",
    )
    assert result.final_state == "success"

    with db.get_connection() as conn:
        cursor = json.loads(
            conn.execute(
                "SELECT cursor_json FROM project_status_update_bindings WHERE id=?",
                (binding_id,),
            ).fetchone()["cursor_json"]
        )
    assert cursor["processed_versions"] == ["v-001"]
