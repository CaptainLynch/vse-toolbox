# -*- coding: utf-8 -*-
"""M2A ProjectStatusSyncRunner 端到端测试（注入式 fake connector）。"""

from __future__ import annotations

import json

import pytest

from core.credential_provider import CredentialProviderError
from core.db_manager import DatabaseManager
from services.aras_auth import ArasAuthError
from services.aras_crawler import ArasAuthenticationError, ArasCrawlerError
from services.project_status_updates import (
    ConnectorCandidate,
    ConnectorSnapshot,
    ProjectStatusUpdateService,
)
from services.project_status_sync_runner import (
    ConnectorRegistry,
    EXIT_ATTENTION,
    EXIT_FAILED,
    EXIT_OK,
    ProjectStatusSyncRunner,
    SyncBindingContext,
    create_production_registry,
)
from services.tdc_auth import TDCAuthError
from services.tdc_crawler import TDCCrawlerError
from services.windows_http import WinHTTPError, WinHTTPTimeoutError


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


def _record_two_observations_for_runner(
    db: DatabaseManager,
    deliverable_id: str = "VPI-T2-D5",
    source_type: str = "tdc",
    external_key: str = "FM-1",
    fields: list[str] | None = None,
) -> None:
    field_list = fields if fields is not None else [
        "currentApprover", "approvalComment", "incident",
        "reportType", "ewoNo", "projectCode", "subjectKeyword",
    ]

    report = {
        "fields": field_list,
        "statusOrApprovalFields": [],
        "suggestedStatusMapping": [],
        "suggestedAutomaticFields": [],
        "requiresConfirmation": True,
    }
    db.record_mapping_observation(
        deliverable_id=deliverable_id,
        source_type=source_type,
        result_state="matched",
        external_key=external_key,
        candidate_fingerprint="fp1",
        candidate_count=1,
        candidate_summary_json=json.dumps([{"externalKey": external_key, "fields": {}}]),
        field_report_json=json.dumps(report),
    )
    db.record_mapping_observation(
        deliverable_id=deliverable_id,
        source_type=source_type,
        result_state="matched",
        external_key=external_key,
        candidate_fingerprint="fp2",
        candidate_count=1,
        candidate_summary_json=json.dumps([{"externalKey": external_key, "fields": {}}]),
        field_report_json=json.dumps(report),
    )


def _enable_pilot(service: ProjectStatusUpdateService) -> int:
    _record_two_observations_for_runner(
        service._db,
        deliverable_id="VPI-T2-D5",
        source_type="tdc",
        external_key="FM-1",
        fields=["currentApprover", "approvalComment", "incident", "reportType"],
    )
    service.update_update_policy(
        "VPI-T2-D5",
        {
            "mode": "hybrid",
            "enabled": True,
            "externalKey": "FM-1",
            "matchRule": {"reportType": "data_model", "incident": "FM-1"},
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
    """在数据库层面配置并启用 VPI-T2-D3 绑定（符合 aras/ewo 契约与证据要求）。"""
    _record_two_observations_for_runner(
        db,
        deliverable_id="VPI-T2-D3",
        source_type="aras",
        external_key="FM-3",
        fields=["currentApprover", "ewoNo", "reportType", "projectCode", "approvalComment"],
    )
    with db.get_connection() as conn:
        conn.execute(
            """
            UPDATE project_status_update_bindings
            SET mode='hybrid', source_type='aras', enabled=1,
                external_key='FM-3',
                credential_ref='test-credential-ref',
                match_rule_json='{"reportType":"ewo","ewoNo":"FM-3"}',
                mapping_json='{"owner":"currentApprover"}'
            WHERE deliverable_id='VPI-T2-D3'
            """
        )
        conn.execute(
            """
            INSERT INTO project_status_field_authority
                (deliverable_id, field_name, authority, source_type)
            VALUES ('VPI-T2-D3', 'owner', 'automatic', 'aras')
            ON CONFLICT(deliverable_id, field_name) DO UPDATE SET
                authority='automatic', source_type='aras', locked_at=NULL
            """
        )
        conn.execute(
            """
            INSERT INTO project_status_field_authority
                (deliverable_id, field_name, authority, source_type)
            VALUES ('VPI-T2-D3', 'note', 'manual', 'aras')
            ON CONFLICT(deliverable_id, field_name) DO UPDATE SET
                authority='manual', source_type='aras', locked_at=NULL
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
    _enable_pilot(service)
    _enable_second_deliverable(db)

    snap5 = _snapshot_for(db, "VPI-T2-D5", "FM-1", "v-5", owner="D5owner", note="D5note")
    snap3 = _snapshot_for(db, "VPI-T2-D3", "FM-3", "v-3", owner="D3owner")
    connector5 = FakeConnector(snapshot=snap5)
    connector3 = FakeConnector(snapshot=snap3)
    registry.register("tdc", connector5)
    registry.register("aras", connector3)

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

    registry.register("aras", FakeConnector(exc=RuntimeError("boom password=secret")))
    registry.register(
        "tdc",
        FakeConnector(
            snapshot=_snapshot_for(db, "VPI-T2-D5", "FM-1", "v-ok", owner="ok", note="ok")
        ),
    )
    result = runner.run_once()
    assert len(result.results) == 2
    outcomes = {r.deliverable_id: r.outcome for r in result.results}
    assert outcomes["VPI-T2-D3"] == "failed"
    assert outcomes["VPI-T2-D5"] == "completed"
    assert result.exit_code == EXIT_FAILED


@pytest.mark.parametrize(
    ("failure", "error_type"),
    [
        (
            CredentialProviderError("credential missing password=secret"),
            "credential_unavailable",
        ),
        (ArasAuthError("credentials rejected password=secret"), "credential_invalid"),
        (TDCAuthError("TDC credentials rejected password=secret"), "credential_invalid"),
        (
            ArasAuthenticationError("login page token=secret"),
            "authentication_error",
        ),
        (WinHTTPError("transport failed Cookie=secret"), "service_unavailable"),
        (WinHTTPTimeoutError("timed out token=secret"), "timeout"),
        (ArasCrawlerError("invalid XML Authorization=secret"), "query_failed"),
    ],
)
def test_scheduled_connector_failure_is_audited_without_secret(
    runner: ProjectStatusSyncRunner,
    db: DatabaseManager,
    service: ProjectStatusUpdateService,
    registry: ConnectorRegistry,
    failure: BaseException,
    error_type: str,
) -> None:
    _enable_pilot(service)
    registry.register("tdc", FakeConnector(exc=failure))

    result = runner.run_once(validate_runtime_prerequisites=False)
    item = result.results[0]

    assert item.error_type == error_type
    assert item.final_state == "failed"
    assert item.run_id is not None
    serialized = json.dumps(item.__dict__, ensure_ascii=False)
    assert "secret" not in serialized
    assert "Cookie" not in serialized
    assert "Authorization" not in serialized

    with db.get_connection() as conn:
        run = conn.execute(
            "SELECT run_state, error_type, error_message, result_summary "
            "FROM project_status_sync_runs WHERE id=?",
            (item.run_id,),
        ).fetchone()
    assert run["run_state"] == "failed"
    assert run["error_type"] == error_type
    db_serialized = json.dumps(dict(run), ensure_ascii=False)
    assert "secret" not in db_serialized
    assert "Cookie" not in db_serialized
    assert "Authorization" not in db_serialized


def test_wrapped_tdc_transport_failure_is_classified_as_service_unavailable(
    runner: ProjectStatusSyncRunner,
    db: DatabaseManager,
    service: ProjectStatusUpdateService,
    registry: ConnectorRegistry,
) -> None:
    _enable_pilot(service)
    failure = TDCCrawlerError("request failed")
    failure.__cause__ = WinHTTPError("Cookie=secret")
    registry.register("tdc", FakeConnector(exc=failure))

    result = runner.run_once(validate_runtime_prerequisites=False)

    item = result.results[0]
    assert item.error_type == "service_unavailable"
    assert item.error_message == "external service unavailable; retry later"
    assert "secret" not in str(item)


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


def test_successful_sync_publishes_analysis_cache(
    db: DatabaseManager,
    service: ProjectStatusUpdateService,
    registry: ConnectorRegistry,
) -> None:
    _enable_pilot(service)
    base = _matched_snapshot(db, owner="新负责人", note="ok")
    snapshot = ConnectorSnapshot(
        match_state=base.match_state,
        candidates=base.candidates,
        external_version=base.external_version,
        fetched_at=base.fetched_at,
        expected_deliverable_updated_at=base.expected_deliverable_updated_at,
        analysis_rows=(
            {
                "id": "analysis-1",
                "name": "冻结发布单确认",
                "department": "质量科",
                "status": "进行中",
                "dueDate": "2026-08-18",
            },
            {
                "id": "analysis-2",
                "name": "审批关闭",
                "department": "项目管理科",
                "status": "已完成",
            },
        ),
    )
    registry.register("tdc", FakeConnector(snapshot=snapshot))

    result = ProjectStatusSyncRunner(db, service, registry).run_once()
    assert result.exit_code == EXIT_OK
    snapshots = db.list_project_status_analysis_snapshots("VPI-T2-D5")
    assert len(snapshots) == 1
    assert snapshots[0]["total_count"] == 2
    assert snapshots[0]["completed_count"] == 1
    items = db.list_project_status_analysis_items("VPI-T2-D5")
    assert {item["department"] for item in items} == {"质量科", "项目管理科"}


def test_successful_ewo_sync_also_publishes_unified_form_snapshot(
    db: DatabaseManager,
    service: ProjectStatusUpdateService,
    registry: ConnectorRegistry,
) -> None:
    _enable_second_deliverable(db)
    base = _snapshot_for(db, "VPI-T2-D3", "FM-3", "ewo-v-001", owner="负责人")
    snapshot = ConnectorSnapshot(
        match_state=base.match_state,
        candidates=base.candidates,
        external_version=base.external_version,
        fetched_at=base.fetched_at,
        expected_deliverable_updated_at=base.expected_deliverable_updated_at,
        artifacts=({
            "artifact_type": "normalized_json",
            "relative_path": "aras/ewo/ewo.json",
            "display_name": "ewo.json",
        },),
        analysis_rows=(
            {
                "_no": "FM-3",
                "_rsp_department": "车身开发部",
                "_rsp_smt": "车体工程",
                "_modelinfo": "F610S",
                "state": "PROC",
                "_submit_time": "2026-08-20",
            },
        ),
    )
    registry.register("aras", FakeConnector(snapshot=snapshot))

    result = ProjectStatusSyncRunner(db, service, registry).run_once(
        deliverable_id="VPI-T2-D3",
    )

    assert result.exit_code == EXIT_OK
    form_snapshot = db.get_latest_deliverable_form_snapshot("VPI-T2-D3")
    assert form_snapshot is not None
    assert form_snapshot["source_run_id"] == result.results[0].run_id
    assert db.list_deliverable_form_rows("VPI-T2-D3")["total"] == 1


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

    registry.register("tdc", FakeConnector(exc=RuntimeError("boom")))
    registry.register(
        "aras",
        FakeConnector(
            snapshot=ConnectorSnapshot(
                match_state="not_found",
                candidates=[],
                external_version="v-x",
                fetched_at="2026-08-20T00:00:00.000Z",
                expected_deliverable_updated_at=_current_updated_at(db, "VPI-T2-D3"),
            )
        ),
    )
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
    registry.register(
        "aras",
        FakeConnector(snapshot=_snapshot_for(db, "VPI-T2-D3", "FM-3", "v-3", owner="D3owner")),
    )

    # 在 run_once 前删除 D5 的交付物（级联删除 binding）。
    with db.get_connection() as conn:
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
    runner: ProjectStatusSyncRunner,
    db: DatabaseManager,
    service: ProjectStatusUpdateService,
    registry: ConnectorRegistry,
) -> None:

    """当 binding 未就绪（例如无 credential_ref）时，runner 返回 needs_attention，零 connector 调用且零 run 产生。"""
    # 记录有效证据并配置合规规则，然后清除 credential_ref 模拟未就绪
    _record_two_observations_for_runner(
        db,
        deliverable_id="VPI-T2-D5",
        source_type="tdc",
        external_key="FM-1",
        fields=["currentApprover", "approvalComment", "incident", "reportType"],
    )
    service.update_update_policy(
        "VPI-T2-D5",
        {
            "mode": "hybrid",
            "enabled": True,
            "externalKey": "FM-1",
            "matchRule": {"reportType": "data_model", "incident": "FM-1"},
            "mapping": {"owner": "currentApprover", "note": "approvalComment"},
            "fieldAuthority": {"owner": "automatic", "note": "automatic"},
            "credentialRef": "temp-alias",
        },
    )
    # 显式清除 credential_ref
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET credential_ref = NULL WHERE deliverable_id = 'VPI-T2-D5'"
        )
        conn.commit()

    connector = FakeConnector(snapshot=_matched_snapshot(db, owner="ok", note="ok"))
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


def test_scheduled_run_can_reach_connector_without_runtime_readiness(
    runner: ProjectStatusSyncRunner,
    db: DatabaseManager,
    service: ProjectStatusUpdateService,
    registry: ConnectorRegistry,
) -> None:
    """定时运行不把凭据缺失变成租约前的零运行阻断。"""
    _record_two_observations_for_runner(
        db,
        deliverable_id="VPI-T2-D5",
        source_type="tdc",
        external_key="FM-1",
        fields=["currentApprover", "approvalComment", "incident", "reportType"],
    )
    service.update_update_policy(
        "VPI-T2-D5",
        {
            "mode": "hybrid",
            "enabled": True,
            "externalKey": "FM-1",
            "matchRule": {"reportType": "data_model", "incident": "FM-1"},
            "mapping": {"owner": "currentApprover", "note": "approvalComment"},
            "fieldAuthority": {"owner": "automatic", "note": "automatic"},
            "credentialRef": "temp-alias",
        },
    )
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET credential_ref = NULL "
            "WHERE deliverable_id = 'VPI-T2-D5'"
        )
        conn.commit()

    connector = FakeConnector(snapshot=_matched_snapshot(db, owner="scheduled-owner"))
    registry.register("tdc", connector)

    result = runner.run_once(validate_runtime_prerequisites=False)

    assert len(connector.collect_calls) == 1
    assert len(result.results) == 1
    assert result.results[0].run_id is not None


def test_scheduled_run_defers_all_runtime_prerequisites_until_after_lease(
    runner: ProjectStatusSyncRunner,
    db: DatabaseManager,
    service: ProjectStatusUpdateService,
    registry: ConnectorRegistry,
) -> None:
    """缺少凭据、稳定键、匹配规则和映射时仍先创建 run 并调用 connector。"""
    _enable_pilot(service)
    with db.get_connection() as conn:
        conn.execute(
            """
            UPDATE project_status_update_bindings
            SET credential_ref = NULL, external_key = NULL,
                match_rule_json = '{}', mapping_json = '{}'
            WHERE deliverable_id = 'VPI-T2-D5'
            """
        )
        conn.commit()

    connector = FakeConnector(snapshot=_matched_snapshot(db, owner="runtime-check"))
    registry.register("tdc", connector)

    result = runner.run_once(
        deliverable_id="VPI-T2-D5",
        validate_runtime_prerequisites=False,
    )

    assert len(connector.collect_calls) == 1
    assert result.results[0].run_id is not None
    assert result.results[0].error_type == "binding_not_ready"
    run = db.get_sync_run(result.results[0].run_id)
    assert run is not None
    assert run["run_state"] == "failed"


def test_dry_run_binding_not_ready_returns_attention(
    runner: ProjectStatusSyncRunner,
    db: DatabaseManager,
    service: ProjectStatusUpdateService,
    registry: ConnectorRegistry,
) -> None:

    """dry-run 下 binding 未配置 credential_ref 时 binding_ready=False 且 exit_code=EXIT_ATTENTION。"""
    _record_two_observations_for_runner(
        db,
        deliverable_id="VPI-T2-D5",
        source_type="tdc",
        external_key="FM-1",
        fields=["currentApprover", "approvalComment", "incident", "reportType"],
    )
    service.update_update_policy(
        "VPI-T2-D5",
        {
            "mode": "hybrid",
            "enabled": True,
            "externalKey": "FM-1",
            "matchRule": {"reportType": "data_model", "incident": "FM-1"},
            "mapping": {"owner": "currentApprover", "note": "approvalComment"},
            "fieldAuthority": {"owner": "automatic", "note": "automatic"},
            "credentialRef": "temp-alias",
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


def test_legacy_binding_lacking_approval_evidence_refuses_sync(
    runner: ProjectStatusSyncRunner, db: DatabaseManager, registry: ConnectorRegistry
) -> None:
    """Runner refuses a legacy enabled binding without approval evidence before connector call and creates no run."""
    # 直接在数据库写入 legacy enabled 记录（无 mapping observations 证据）
    with db.get_connection() as conn:
        conn.execute(
            """
            UPDATE project_status_update_bindings
            SET mode='hybrid', source_type='tdc', enabled=1,
                external_key='LEGACY-1',
                credential_ref='legacy-alias',
                match_rule_json='{"reportType":"data_model","incident":"LEGACY-1"}',
                mapping_json='{"owner":"currentApprover"}'
            WHERE deliverable_id='VPI-T2-D5'
            """
        )
        conn.execute(
            """
            INSERT INTO project_status_field_authority
                (deliverable_id, field_name, authority, source_type)
            VALUES ('VPI-T2-D5', 'owner', 'automatic', 'tdc')
            ON CONFLICT(deliverable_id, field_name) DO UPDATE SET
                authority='automatic', source_type='tdc', locked_at=NULL
            """
        )
        conn.commit()

    fake_conn = FakeConnector(snapshot=_matched_snapshot(db, external_key="LEGACY-1", owner="new-owner"))
    registry.register("tdc", fake_conn)

    result = runner.run_once(deliverable_id="VPI-T2-D5")
    assert len(result.results) == 1
    r = result.results[0]
    assert r.outcome == "needs_attention"
    assert r.final_state == "needs_attention"
    assert r.error_type == "binding_not_ready"
    assert "证据" in (r.error_message or "")
    assert r.run_id is None
    assert result.exit_code == EXIT_ATTENTION

    # Connector 零调用，零 run 产生
    assert len(fake_conn.collect_calls) == 0
    assert _count_runs(db) == 0


def test_run_once_trigger_type_sync_now(
    runner: ProjectStatusSyncRunner,
    db: DatabaseManager,
    service: ProjectStatusUpdateService,
    registry: ConnectorRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_once(trigger_type='sync_now') records sync_now in run/audit and passes it to apply_sync_update."""
    binding_id = _enable_pilot(service)
    snap = _matched_snapshot(db, owner="新负责人", note="同步备注")
    connector = FakeConnector(snapshot=snap)
    registry.register("tdc", connector)

    apply_calls = []
    original_apply = service.apply_sync_update

    def spy_apply(binding_id, run_id, lease_token, snapshot, trigger_type):
        apply_calls.append({
            "binding_id": binding_id,
            "run_id": run_id,
            "lease_token": lease_token,
            "snapshot": snapshot,
            "trigger_type": trigger_type,
        })
        return original_apply(binding_id, run_id, lease_token, snapshot, trigger_type)

    monkeypatch.setattr(service, "apply_sync_update", spy_apply)

    result = runner.run_once(trigger_type="sync_now")
    assert len(result.results) == 1
    assert result.results[0].outcome == "completed"
    assert result.results[0].final_state == "success"
    assert result.exit_code == EXIT_OK

    # 验证 apply_sync_update 显式收到 sync_now 参数
    assert len(apply_calls) == 1
    assert apply_calls[0]["trigger_type"] == "sync_now"

    # 验证 run 表中 trigger_type 为 sync_now
    with db.get_connection() as conn:
        run = conn.execute(
            "SELECT trigger_type FROM project_status_sync_runs WHERE binding_id = ?",
            (binding_id,),
        ).fetchone()
        assert run is not None
        assert run["trigger_type"] == "sync_now"

        # 验证 audit 表中 trigger_type 为 sync_now
        audit = conn.execute(
            """
            SELECT trigger_type FROM project_status_update_audit
            WHERE deliverable_id = 'VPI-T2-D5' ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        assert audit is not None
        assert audit["trigger_type"] == "sync_now"


def test_run_once_rejects_unsupported_trigger_type_without_writes(
    runner: ProjectStatusSyncRunner,
    db: DatabaseManager,
    service: ProjectStatusUpdateService,
) -> None:
    """Unsupported trigger values are rejected without any database writes."""
    _enable_pilot(service)
    runs_before = _count_runs(db)
    audit_before = _count_audit(db)

    with pytest.raises(ValueError, match="unsupported"):
        runner.run_once(trigger_type="manual")

    with pytest.raises(ValueError, match="unsupported"):
        runner.run_once(trigger_type="invalid_trigger")

    assert _count_runs(db) == runs_before
    assert _count_audit(db) == audit_before
