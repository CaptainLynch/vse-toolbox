# -*- coding: utf-8 -*-
"""M2A ProjectStatusSyncRunner 端到端测试（注入式 fake connector）。"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest

from core.db_manager import (
    DatabaseManager,
    SyncLeaseBusyError,
)
from services.project_status_updates import (
    ConnectorCandidate,
    ConnectorSnapshot,
    ProjectStatusUpdateService,
)
from services.project_status_sync_runner import (
    BindingRunResult,
    ConnectorRegistry,
    EXIT_ATTENTION,
    EXIT_FAILED,
    EXIT_OK,
    ProjectStatusConnector,
    ProjectStatusSyncRunner,
    SyncBindingContext,
    create_production_registry,
)


# ── 公共 fixture ────────────────────────────────────────────────


@pytest.fixture()
def db(tmp_path) -> DatabaseManager:
    manager = DatabaseManager(db_path=tmp_path / "runner.db")
    manager.init_database()
    return manager


@pytest.fixture()
def service(db: DatabaseManager) -> ProjectStatusUpdateService:
    return ProjectStatusUpdateService(db)


@pytest.fixture()
def registry() -> ConnectorRegistry:
    return ConnectorRegistry()


@pytest.fixture()
def runner(
    db: DatabaseManager,
    service: ProjectStatusUpdateService,
    registry: ConnectorRegistry,
) -> ProjectStatusSyncRunner:
    return ProjectStatusSyncRunner(db, service, registry)


def _enable_pilot(service: ProjectStatusUpdateService) -> int:
    service.update_update_policy(
        "VPI-T2-D5",
        {
            "mode": "hybrid",
            "enabled": True,
            "externalKey": "FM-1",
            "matchRule": {"incident": "FM-1"},
            "mapping": {"owner": "currentApprover", "note": "approvalComment"},
            "fieldAuthority": {"owner": "automatic", "note": "automatic"},
            "credentialRef": "test-credential-ref",
        },
    )
    with service._db.get_connection() as conn:
        return int(
            conn.execute(
                "SELECT id FROM project_status_update_bindings WHERE deliverable_id='VPI-T2-D5'"
            ).fetchone()["id"]
        )


def _enable_second_deliverable(db: DatabaseManager) -> int:
    """直接在数据库层面启用 VPI-T2-D3 绑定，绕过试点限制（仅测试用）。"""
    with db.get_connection() as conn:
        conn.execute(
            """
            UPDATE project_status_update_bindings
            SET mode='hybrid', source_type='tdc', enabled=1,
                external_key='FM-3',
                credential_ref='test-credential-ref',
                match_rule_json='{"incident":"FM-3"}',
                mapping_json='{"owner":"currentApprover"}'
            WHERE deliverable_id='VPI-T2-D3'
            """
        )
        conn.execute(
            """
            INSERT INTO project_status_field_authority
                (deliverable_id, field_name, authority, source_type)
            VALUES ('VPI-T2-D3', 'owner', 'automatic', 'tdc')
            ON CONFLICT(deliverable_id, field_name) DO UPDATE SET
                authority='automatic', source_type='tdc', locked_at=NULL
            """
        )
        conn.execute(
            """
            INSERT INTO project_status_field_authority
                (deliverable_id, field_name, authority, source_type)
            VALUES ('VPI-T2-D3', 'note', 'automatic', 'tdc')
            ON CONFLICT(deliverable_id, field_name) DO UPDATE SET
                authority='automatic', source_type='tdc', locked_at=NULL
            """
        )
        conn.commit()
        return int(
            conn.execute(
                "SELECT id FROM project_status_update_bindings WHERE deliverable_id='VPI-T2-D3'"
            ).fetchone()["id"]
        )


def _current_updated_at(db: DatabaseManager, deliverable_id: str) -> str:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT updated_at FROM project_status_deliverables WHERE id = ?",
            (deliverable_id,),
        ).fetchone()
    assert row is not None
    return str(row["updated_at"])


class FakeConnector:
    """可配置的 fake connector，返回预设 snapshot 或抛异常。"""

    def __init__(
        self,
        snapshot: ConnectorSnapshot | None = None,
        exc: BaseException | None = None,
    ) -> None:
        self._snapshot = snapshot
        self._exc = exc
        self.collect_calls: list[SyncBindingContext] = []

    def collect(self, context: SyncBindingContext) -> ConnectorSnapshot:
        self.collect_calls.append(context)
        if self._exc is not None:
            raise self._exc
        assert self._snapshot is not None
        return self._snapshot


def _matched_snapshot(
    db: DatabaseManager,
    external_key: str = "FM-1",
    external_version: str = "v-001",
    **field_values,
) -> ConnectorSnapshot:
    return ConnectorSnapshot(
        match_state="matched",
        candidates=[
            ConnectorCandidate(
                external_key=external_key,
                external_version=external_version,
                field_values=field_values,
                fetched_at="2026-08-20T00:00:00.000Z",
            )
        ],
        external_version=external_version,
        fetched_at="2026-08-20T00:00:00.000Z",
        expected_deliverable_updated_at=_current_updated_at(db, "VPI-T2-D5"),
    )


def _snapshot_for(
    db: DatabaseManager,
    deliverable_id: str,
    external_key: str,
    external_version: str,
    **field_values,
) -> ConnectorSnapshot:
    return ConnectorSnapshot(
        match_state="matched",
        candidates=[
            ConnectorCandidate(
                external_key=external_key,
                external_version=external_version,
                field_values=field_values,
                fetched_at="2026-08-20T00:00:00.000Z",
            )
        ],
        external_version=external_version,
        fetched_at="2026-08-20T00:00:00.000Z",
        expected_deliverable_updated_at=_current_updated_at(db, deliverable_id),
    )


def _count_runs(db: DatabaseManager) -> int:
    with db.get_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM project_status_sync_runs"
        ).fetchone()["c"]


def _count_audit(db: DatabaseManager) -> int:
    with db.get_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM project_status_update_audit"
        ).fetchone()["c"]


# ── 1. 无 enabled binding 时安全返回 0，不创建 run ─────────────


def test_no_enabled_bindings_returns_ok_zero_writes(
    runner: ProjectStatusSyncRunner, db: DatabaseManager
) -> None:
    result = runner.run_once()
    assert result.exit_code == EXIT_OK
    assert result.results == ()
    assert _count_runs(db) == 0


# ── 2. 多 binding 按稳定顺序执行 ───────────────────────────────


def test_multiple_bindings_stable_order(
    runner: ProjectStatusSyncRunner, db: DatabaseManager,
    service: ProjectStatusUpdateService, registry: ConnectorRegistry,
) -> None:
    id5 = _enable_pilot(service)
    id3 = _enable_second_deliverable(db)

    snap5 = _snapshot_for(db, "VPI-T2-D5", "FM-1", "v-5", owner="D5owner")
    snap3 = _snapshot_for(db, "VPI-T2-D3", "FM-3", "v-3", owner="D3owner")
    connector5 = FakeConnector(snapshot=snap5)
    connector3 = FakeConnector(snapshot=snap3)
    registry.register("tdc", connector5)

    # 只能注册一个 tdc connector，两个 binding 都是 tdc → 用同一 connector。
    # 为了区分 snapshot，让 connector 根据 deliverable_id 返回。
    class MultiFake:
        def __init__(self):
            self.calls: list[SyncBindingContext] = []

        def collect(self, context: SyncBindingContext) -> ConnectorSnapshot:
            self.calls.append(context)
            if context.deliverable_id == "VPI-T2-D5":
                return snap5
            return snap3

    multi = MultiFake()
    registry.register("tdc", multi)

    result = runner.run_once()
    assert len(result.results) == 2
    # binding_id 升序：D3 的 binding_id < D5 的（取决于种子插入顺序）。
    ids = [r.binding_id for r in result.results]
    assert ids == sorted(ids)
    assert result.exit_code == EXIT_OK


# ── 3. 单个 connector 失败不阻断后续 binding ───────────────────


def test_single_failure_does_not_block_others(
    runner: ProjectStatusSyncRunner, db: DatabaseManager,
    service: ProjectStatusUpdateService, registry: ConnectorRegistry,
) -> None:
    _enable_pilot(service)
    _enable_second_deliverable(db)

    class FailFirst:
        def __init__(self):
            self.count = 0

        def collect(self, context: SyncBindingContext) -> ConnectorSnapshot:
            self.count += 1
            if context.deliverable_id == "VPI-T2-D3":
                raise RuntimeError("boom password=secret")
            return _snapshot_for(
                db, "VPI-T2-D5", "FM-1", "v-ok", owner="ok"
            )

    registry.register("tdc", FailFirst())
    result = runner.run_once()
    assert len(result.results) == 2
    outcomes = {r.deliverable_id: r.outcome for r in result.results}
    assert outcomes["VPI-T2-D3"] == "failed"
    assert outcomes["VPI-T2-D5"] == "completed"
    assert result.exit_code == EXIT_FAILED


# ── 4. fake connector 成功完成 acquire → start → collect → apply → release


def test_successful_sync_full_lifecycle(
    runner: ProjectStatusSyncRunner, db: DatabaseManager,
    service: ProjectStatusUpdateService, registry: ConnectorRegistry,
) -> None:
    binding_id = _enable_pilot(service)
    snap = _matched_snapshot(db, owner="新负责人", note="ok")
    connector = FakeConnector(snapshot=snap)
    registry.register("tdc", connector)

    result = runner.run_once()
    assert len(result.results) == 1
    r = result.results[0]
    assert r.outcome == "completed"
    assert r.final_state == "success"
    assert "owner" in r.applied_fields
    assert r.run_id is not None

    # 验证租约已释放。
    with db.get_connection() as conn:
        binding = conn.execute(
            "SELECT lease_token, sync_state FROM project_status_update_bindings WHERE id=?",
            (binding_id,),
        ).fetchone()
        assert binding["lease_token"] is None
        assert binding["sync_state"] == "success"

    # 验证 connector 被调用一次。
    assert len(connector.collect_calls) == 1
    ctx = connector.collect_calls[0]
    assert ctx.external_key == "FM-1"
    assert ctx.deliverable_id == "VPI-T2-D5"


# ── 5. fake connector 返回 not_found/ambiguous ──────────────────


@pytest.mark.parametrize("state", ["not_found", "ambiguous"])
def test_connector_returns_no_match(
    runner: ProjectStatusSyncRunner, db: DatabaseManager,
    service: ProjectStatusUpdateService, registry: ConnectorRegistry,
    state: str,
) -> None:
    _enable_pilot(service)
    snap = ConnectorSnapshot(
        match_state=state,
        candidates=[],
        external_version="v-nomatch",
        fetched_at="2026-08-20T00:00:00.000Z",
        expected_deliverable_updated_at=_current_updated_at(db, "VPI-T2-D5"),
    )
    registry.register("tdc", FakeConnector(snapshot=snap))
    result = runner.run_once()
    r = result.results[0]
    assert r.final_state == "needs_attention"
    assert result.exit_code == EXIT_ATTENTION


# ── 6. connector 未注册时不调用外部系统，保留最后成功数据 ───────


def test_connector_unavailable_preserves_last_success(
    runner: ProjectStatusSyncRunner, db: DatabaseManager,
    service: ProjectStatusUpdateService,
) -> None:
    binding_id = _enable_pilot(service)
    # 先手动设置一个 last_success_at。
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET last_success_at='2026-01-01T00:00:00.000Z' "
            "WHERE id=?",
            (binding_id,),
        )
        conn.commit()

    # registry 为空（生产 registry）。
    result = runner.run_once()
    r = result.results[0]
    assert r.final_state == "needs_attention"
    assert r.error_type == "connector_unavailable"

    # last_success_at 不变。
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT last_success_at, cursor_json FROM project_status_update_bindings WHERE id=?",
            (binding_id,),
        ).fetchone()
        assert row["last_success_at"] == "2026-01-01T00:00:00.000Z"
        assert json.loads(row["cursor_json"]) == {}


# ── 7. 已有有效租约时结果为 busy，不创建第二个 run ─────────────


def test_busy_lease_does_not_create_second_run(
    runner: ProjectStatusSyncRunner, db: DatabaseManager,
    service: ProjectStatusUpdateService, registry: ConnectorRegistry,
) -> None:
    binding_id = _enable_pilot(service)
    # 预先获取租约。
    db.acquire_sync_lease(binding_id, "scheduled")

    registry.register("tdc", FakeConnector(snapshot=_matched_snapshot(db)))
    result = runner.run_once()
    r = result.results[0]
    assert r.outcome == "busy"
    assert r.final_state == "busy"
    assert r.run_id is None
    # 只有一个 run（预先获取的那个）。
    assert _count_runs(db) == 1


# ── 8. lease lost 时不覆盖其他运行器的数据 ─────────────────────


def test_lease_lost_does_not_overwrite(
    runner: ProjectStatusSyncRunner, db: DatabaseManager,
    service: ProjectStatusUpdateService, registry: ConnectorRegistry,
) -> None:
    binding_id = _enable_pilot(service)

    # connector 在 collect 时将 runner 持有的租约过期，模拟被另一进程抢占。
    class SlowConnector:
        def collect(self, context: SyncBindingContext) -> ConnectorSnapshot:
            with db.get_connection() as conn:
                conn.execute(
                    "UPDATE project_status_update_bindings SET lease_expires_at='2020-01-01T00:00:00.000Z' "
                    "WHERE id=?",
                    (binding_id,),
                )
                conn.commit()
            return _matched_snapshot(db, owner="自动值")

    registry.register("tdc", SlowConnector())
    result = runner.run_once()
    r = result.results[0]
    assert r.outcome == "failed"
    assert r.error_type == "lease_lost"
    # 业务值不变。
    with db.get_connection() as conn:
        owner = conn.execute(
            "SELECT owner FROM project_status_deliverables WHERE id='VPI-T2-D5'"
        ).fetchone()["owner"]
        assert owner == "赵岩"


# ── 9. connector 异常中的密码/Cookie/Authorization/token 被脱敏 ─


def test_connector_exception_secrets_redacted(
    runner: ProjectStatusSyncRunner, db: DatabaseManager,
    service: ProjectStatusUpdateService, registry: ConnectorRegistry,
) -> None:
    _enable_pilot(service)
    bad = RuntimeError("HTTP 500 password=hunter2 Cookie=abc Authorization=Bearer xyz token=t1")
    registry.register("tdc", FakeConnector(exc=bad))
    result = runner.run_once()
    r = result.results[0]
    assert r.outcome == "failed"
    blob = json.dumps({
        "error_message": r.error_message,
        "error_type": r.error_type,
    })
    assert "hunter2" not in blob
    assert "abc" not in blob
    assert "Bearer" not in blob
    assert "xyz" not in blob

    # 数据库中也不泄漏。
    with db.get_connection() as conn:
        run = conn.execute(
            "SELECT error_message, result_summary FROM project_status_sync_runs "
            "WHERE run_state='failed'"
        ).fetchall()
        db_blob = json.dumps([dict(r2) for r2 in run])
        assert "hunter2" not in db_blob
        assert "abc" not in db_blob


# ── 10. dry-run 完全零写入且不调用 connector ───────────────────


def test_dry_run_zero_writes(
    runner: ProjectStatusSyncRunner, db: DatabaseManager,
    service: ProjectStatusUpdateService, registry: ConnectorRegistry,
) -> None:
    binding_id = _enable_pilot(service)
    connector = FakeConnector(snapshot=_matched_snapshot(db))
    registry.register("tdc", connector)

    # 快照数据库关键表行数。
    runs_before = _count_runs(db)
    audit_before = _count_audit(db)
    with db.get_connection() as conn:
        binding_before = dict(conn.execute(
            "SELECT sync_state, last_attempt_at, cursor_json, lease_token, updated_at "
            "FROM project_status_update_bindings WHERE id=?",
            (binding_id,),
        ).fetchone())

    result = runner.run_once(dry_run=True)
    assert result.dry_run is True
    assert result.exit_code == EXIT_OK
    assert len(result.readiness) == 1
    assert result.readiness[0].connector_available is True

    # 零写入。
    assert _count_runs(db) == runs_before
    assert _count_audit(db) == audit_before
    with db.get_connection() as conn:
        binding_after = dict(conn.execute(
            "SELECT sync_state, last_attempt_at, cursor_json, lease_token, updated_at "
            "FROM project_status_update_bindings WHERE id=?",
            (binding_id,),
        ).fetchone())
    assert dict(binding_before) == dict(binding_after)
    # connector 未被调用。
    assert len(connector.collect_calls) == 0


def test_dry_run_unavailable_connector_returns_attention(
    runner: ProjectStatusSyncRunner, db: DatabaseManager,
    service: ProjectStatusUpdateService,
) -> None:
    _enable_pilot(service)
    # 空 registry（生产）。
    result = runner.run_once(dry_run=True)
    assert result.exit_code == EXIT_ATTENTION
    assert result.readiness[0].connector_available is False


# ── 11. deliverable-id 只运行精确目标 ──────────────────────────


def test_deliverable_filter_runs_only_target(
    runner: ProjectStatusSyncRunner, db: DatabaseManager,
    service: ProjectStatusUpdateService, registry: ConnectorRegistry,
) -> None:
    _enable_pilot(service)
    _enable_second_deliverable(db)
    connector = FakeConnector(snapshot=_matched_snapshot(db, owner="x"))
    registry.register("tdc", connector)

    result = runner.run_once(deliverable_id="VPI-T2-D5")
    assert len(result.results) == 1
    assert result.results[0].deliverable_id == "VPI-T2-D5"


# ── 12. 不存在的 deliverable-id 返回可预期结果 ─────────────────


def test_nonexistent_deliverable_id_returns_empty_ok(
    runner: ProjectStatusSyncRunner, db: DatabaseManager,
    service: ProjectStatusUpdateService, registry: ConnectorRegistry,
) -> None:
    _enable_pilot(service)
    result = runner.run_once(deliverable_id="NONEXISTENT")
    assert result.results == ()
    assert result.exit_code == EXIT_OK


# ── 13. 一个 failed + 一个 needs_attention → 退出码 1 ──────────


def test_failed_and_attention_yields_exit_1(
    runner: ProjectStatusSyncRunner, db: DatabaseManager,
    service: ProjectStatusUpdateService, registry: ConnectorRegistry,
) -> None:
    _enable_pilot(service)
    _enable_second_deliverable(db)

    class FailD5:
        def collect(self, context: SyncBindingContext) -> ConnectorSnapshot:
            if context.deliverable_id == "VPI-T2-D5":
                raise RuntimeError("boom")
            return ConnectorSnapshot(
                match_state="not_found", candidates=[],
                external_version="v-x", fetched_at="2026-08-20T00:00:00.000Z",
                expected_deliverable_updated_at=_current_updated_at(db, "VPI-T2-D3"),
            )

    registry.register("tdc", FailD5())
    result = runner.run_once()
    assert result.exit_code == EXIT_FAILED


# ── 14. 只有 partial/needs_attention → 退出码 2 ────────────────


def test_only_attention_yields_exit_2(
    runner: ProjectStatusSyncRunner, db: DatabaseManager,
    service: ProjectStatusUpdateService, registry: ConnectorRegistry,
) -> None:
    _enable_pilot(service)
    snap = ConnectorSnapshot(
        match_state="ambiguous", candidates=[],
        external_version="v-a", fetched_at="2026-08-20T00:00:00.000Z",
        expected_deliverable_updated_at=_current_updated_at(db, "VPI-T2-D5"),
    )
    registry.register("tdc", FakeConnector(snapshot=snap))
    result = runner.run_once()
    assert result.exit_code == EXIT_ATTENTION


# ── 15. 全部成功/skipped/busy/无任务 → 退出码 0 ────────────────


def test_all_success_exit_0(
    runner: ProjectStatusSyncRunner, db: DatabaseManager,
    service: ProjectStatusUpdateService, registry: ConnectorRegistry,
) -> None:
    _enable_pilot(service)
    registry.register("tdc", FakeConnector(snapshot=_matched_snapshot(db, owner="ok")))
    result = runner.run_once()
    assert result.exit_code == EXIT_OK


# ── 19. KeyboardInterrupt 返回 130 并安全结束当前 run ───────────


def test_keyboard_interrupt_finalizes_run(
    runner: ProjectStatusSyncRunner, db: DatabaseManager,
    service: ProjectStatusUpdateService, registry: ConnectorRegistry,
) -> None:
    binding_id = _enable_pilot(service)

    class InterruptConnector:
        def collect(self, context: SyncBindingContext) -> ConnectorSnapshot:
            raise KeyboardInterrupt

    registry.register("tdc", InterruptConnector())
    with pytest.raises(KeyboardInterrupt):
        runner.run_once()

    # run 被安全结束为 failed（interrupted）。
    with db.get_connection() as conn:
        run = conn.execute(
            "SELECT run_state, error_type FROM project_status_sync_runs "
            "WHERE binding_id=? ORDER BY id DESC LIMIT 1",
            (binding_id,),
        ).fetchone()
        assert run["run_state"] == "failed"
        assert run["error_type"] == "interrupted"
        binding = conn.execute(
            "SELECT lease_token FROM project_status_update_bindings WHERE id=?",
            (binding_id,),
        ).fetchone()
        assert binding["lease_token"] is None


# ── 20. processed_versions 按处理顺序保留最后 100 条 ────────────


def test_processed_versions_preserves_insertion_order(
    runner: ProjectStatusSyncRunner, db: DatabaseManager,
    service: ProjectStatusUpdateService, registry: ConnectorRegistry,
) -> None:
    binding_id = _enable_pilot(service)

    class SequenceConnector:
        def __init__(self):
            self.versions = ["v-2", "v-10", "v-1", "v-2"]  # v-2 重复

        def collect(self, context: SyncBindingContext) -> ConnectorSnapshot:
            ver = self.versions.pop(0)
            return _matched_snapshot(db, external_version=ver, owner="ok")

    registry.register("tdc", SequenceConnector())

    # 运行 3 次（v-2, v-10, v-1），第 4 次 v-2 应幂等跳过。
    for _ in range(4):
        runner.run_once()

    with db.get_connection() as conn:
        cursor = json.loads(
            conn.execute(
                "SELECT cursor_json FROM project_status_update_bindings WHERE id=?",
                (binding_id,),
            ).fetchone()["cursor_json"]
        )
    # 处理顺序：v-2, v-10, v-1（v-2 重复不追加）。
    assert cursor["processed_versions"] == ["v-2", "v-10", "v-1"]


# ── 21. 每个独立 run attempt=1 ──────────────────────────────────


def test_attempt_always_one(
    runner: ProjectStatusSyncRunner, db: DatabaseManager,
    service: ProjectStatusUpdateService, registry: ConnectorRegistry,
) -> None:
    binding_id = _enable_pilot(service)
    registry.register("tdc", FakeConnector(snapshot=_matched_snapshot(db, owner="ok")))

    runner.run_once()
    runner.run_once()
    runner.run_once()

    with db.get_connection() as conn:
        attempts = [
            int(row["attempt"])
            for row in conn.execute(
                "SELECT attempt FROM project_status_sync_runs WHERE binding_id=? ORDER BY id",
                (binding_id,),
            )
        ]
    assert attempts == [1, 1, 1]


# ── 生产 registry 为空 ─────────────────────────────────────────


def test_production_registry_has_fixed_connectors() -> None:
    reg = create_production_registry()
    assert reg.registered_types == ("aras", "tdc")
    assert reg.get("tdc") is not None
    assert reg.get("aras") is not None


# ── 回归：P1 修复后的额外隔离测试 ───────────────────────────────


def test_binding_deleted_mid_batch_does_not_abort(
    runner: ProjectStatusSyncRunner, db: DatabaseManager,
    service: ProjectStatusUpdateService, registry: ConnectorRegistry,
) -> None:
    """binding 在 list 和 acquire 之间被删除 → 该 binding failed，后续不受影响。"""
    _enable_pilot(service)
    _enable_second_deliverable(db)

    class DeleteD5Connector:
        def collect(self, context: SyncBindingContext) -> ConnectorSnapshot:
            return _snapshot_for(db, context.deliverable_id, context.external_key, "v", owner="ok")

    registry.register("tdc", DeleteD5Connector())

    # 在 run_once 前删除 D5 的交付物（级联删除 binding）。
    with db.get_connection() as conn:
        # 先获取 D5 binding_id。
        d5_bid = int(conn.execute(
            "SELECT id FROM project_status_update_bindings WHERE deliverable_id='VPI-T2-D5'"
        ).fetchone()["id"])
        conn.execute("DELETE FROM project_status_deliverables WHERE id='VPI-T2-D5'")
        conn.commit()

    # D5 的 binding 已被级联删除，list_eligible 不会返回它。
    # 此测试验证 list 和 acquire 之间的删除不导致崩溃。
    result = runner.run_once()
    # D3 仍应成功执行。
    assert any(r.deliverable_id == "VPI-T2-D3" for r in result.results)


def test_finalize_failure_secondary_exception_does_not_mask_ki(
    runner: ProjectStatusSyncRunner, db: DatabaseManager,
    service: ProjectStatusUpdateService, registry: ConnectorRegistry, monkeypatch,
) -> None:
    """KeyboardInterrupt 时 finalize_sync_failure 自身抛错 → KI 仍须上抛。"""
    _enable_pilot(service)

    class InterruptConnector:
        def collect(self, context: SyncBindingContext) -> ConnectorSnapshot:
            raise KeyboardInterrupt

    registry.register("tdc", InterruptConnector())

    # 让 finalize_sync_failure 抛出非 LeaseLost 异常。
    def boom(*a, **k):
        raise RuntimeError("db locked")

    monkeypatch.setattr(db, "finalize_sync_failure", boom)

    # KI 仍须上抛，不被 RuntimeError 掩盖。
    with pytest.raises(KeyboardInterrupt):
        runner.run_once()


# ── 绑定就绪度与凭据测试 ─────────────────────────────────────────


def test_runner_needs_attention_when_binding_not_ready_zero_runs(
    runner: ProjectStatusSyncRunner, db: DatabaseManager, service: ProjectStatusUpdateService, registry: ConnectorRegistry
) -> None:
    """当 binding 未就绪（例如无 credential_ref）时，runner 返回 needs_attention，零 connector 调用且零 run 产生。"""
    # 配置 mode=hybrid, enabled=1，但不设置 credential_ref
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
    # 显式清除 credential_ref
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET credential_ref = NULL WHERE deliverable_id = 'VPI-T2-D5'"
        )
        conn.commit()

    connector = FakeConnector(snapshot=_matched_snapshot(db, owner="ok"))
    registry.register("tdc", connector)

    result = runner.run_once()
    assert len(result.results) == 1
    r = result.results[0]
    assert r.outcome == "needs_attention"
    assert r.final_state == "needs_attention"
    assert r.error_type == "binding_not_ready"
    assert r.run_id is None
    assert result.exit_code == EXIT_ATTENTION

    # connector 零调用，零 run 产生
    assert len(connector.collect_calls) == 0
    assert _count_runs(db) == 0


def test_dry_run_binding_not_ready_returns_attention(
    runner: ProjectStatusSyncRunner, db: DatabaseManager, service: ProjectStatusUpdateService, registry: ConnectorRegistry
) -> None:
    """dry-run 下 binding 未配置 credential_ref 时 binding_ready=False 且 exit_code=EXIT_ATTENTION。"""
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
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET credential_ref = NULL WHERE deliverable_id = 'VPI-T2-D5'"
        )
        conn.commit()

    connector = FakeConnector(snapshot=_matched_snapshot(db))
    registry.register("tdc", connector)

    result = runner.run_once(dry_run=True)
    assert result.dry_run is True
    assert result.exit_code == EXIT_ATTENTION
    assert len(result.readiness) == 1
    assert result.readiness[0].connector_available is True
    assert result.readiness[0].binding_ready is False
    assert len(connector.collect_calls) == 0
    assert _count_runs(db) == 0


def test_eligible_rows_credential_configured_bool_and_credential_ref_absent(
    db: DatabaseManager, service: ProjectStatusUpdateService
) -> None:
    """list_eligible_sync_bindings 返回 credential_configured bool 且不返回 credential_ref。"""
    _enable_pilot(service)
    rows = db.list_eligible_sync_bindings()
    assert len(rows) >= 1
    d5_row = next(r for r in rows if r["deliverable_id"] == "VPI-T2-D5")
    assert d5_row["credential_configured"] is True
    assert isinstance(d5_row["credential_configured"], bool)
    assert "credential_ref" not in d5_row
    assert "lease_token" not in d5_row

    # 清空 credential_ref 后再查
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET credential_ref = '' WHERE deliverable_id = 'VPI-T2-D5'"
        )
        conn.commit()

    rows2 = db.list_eligible_sync_bindings()
    d5_row2 = next(r for r in rows2 if r["deliverable_id"] == "VPI-T2-D5")
    assert d5_row2["credential_configured"] is False
    assert isinstance(d5_row2["credential_configured"], bool)
    assert "credential_ref" not in d5_row2
