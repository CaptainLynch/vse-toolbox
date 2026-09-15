"""聚合模式快照契约（GPT 终审测试建议：同单号内容变化不得误判幂等）。"""
from __future__ import annotations

import json

import pytest

from services.project_status_connectors import _snapshot
from services.project_status_sync_runner import SyncBindingContext


def _aggregate_context(**kwargs):
    match_rule = {"reportType": "data_model", "aggregate": True, "projectModel": "F610S"}
    expected_updated_at = kwargs.pop("expected_deliverable_updated_at", "v1")
    mapping = kwargs.pop("mapping", {
        "owner": "currentApprover",
        "note": ["latest_completed_node", "approval_status"],
    })
    match_rule.update(kwargs)
    return SyncBindingContext(
        binding_id=3, deliverable_id="VPI-T2-D5", phase_id="VPI-T2",
        source_type="tdc", external_key=None, match_rule=match_rule,
        mapping=mapping,
        cursor={}, expected_deliverable_updated_at=expected_updated_at, run_id=9,
        credential_ref="domain",
    )


def _current_updated_at(db, deliverable_id: str = "VPI-T2-D5") -> str:
    _, _, deliverables = db.get_project_status("VPI-T2")
    return next(d["updated_at"] for d in deliverables if d["id"] == deliverable_id)


def _record_aggregate_evidence(db, deliverable_id: str, rule_json: str, rows: list[dict]) -> None:
    """Seed the same signed aggregate evidence required by a scheduled run."""
    from services.project_status_discovery import MappingDiscoveryService

    rule = json.loads(rule_json)
    discovery = MappingDiscoveryService(db)
    discovery.observe(deliverable_id, "tdc", rows, aggregate=True, match_rule=rule)
    discovery.observe(deliverable_id, "tdc", rows, aggregate=True, match_rule=rule)


def test_apply_ready_aggregate_snapshot_contract():
    """聚合候选满足 _validate_snapshot 契约：单候选、external_key/version 必填、
    field_values 仅 str/None；内容变化 → external_version 变化（不得幂等误判）。"""
    rows_v1 = [
        {"incident": "F610S-3D-0001", "currentApprover": "张三",
         "latest_completed_node": "IMPL", "approval_status": "审批中"},
    ]
    rows_v2 = [
        {"incident": "F610S-3D-0001", "currentApprover": "张三",
         "latest_completed_node": "IMPL", "approval_status": "已驳回"},
    ]
    snapshot_v1 = _snapshot(_aggregate_context(), rows_v1, [])
    snapshot_v2 = _snapshot(_aggregate_context(), rows_v2, [])
    assert snapshot_v1.match_state == "matched"
    assert len(snapshot_v1.candidates) == 1
    candidate = snapshot_v1.candidates[0]
    assert candidate.external_key and candidate.external_version
    assert set(candidate.field_values) <= {"owner", "plannedDate", "note"}
    assert all(value is None or isinstance(value, str) for value in candidate.field_values.values())
    # 同单号内容变化 → external_version 变化（幂等去重不会误跳过）。
    assert snapshot_v1.external_version != snapshot_v2.external_version
    # 记录集合不变 → 候选 external_key（记录集合指纹）不变。
    assert snapshot_v1.candidates[0].external_key == snapshot_v2.candidates[0].external_key


def test_set_policy_sync_config_revision_and_cursor_reset(tmp_db) -> None:
    """换绑或配置目标变化：revision 自增、清空分析快照、重置 cursor；仅改 interval 不变。"""
    deliverable_id = "VPI-T2-D5"
    rule_1 = json.dumps({"reportType": "data_model", "aggregate": True, "projectModel": "F610S"})
    mapping_1 = json.dumps({"owner": "currentApprover", "note": "summaryNote"})

    # 1. 初始配置（从默认空规则变为具体规则，target_changed 触发 +1）
    rev1 = tmp_db.set_project_status_update_policy(
        deliverable_id=deliverable_id,
        mode="automatic",
        enabled=True,
        external_key=None,
        match_rule_json=rule_1,
        mapping_json=mapping_1,
        field_authority={"owner": "automatic", "remark": "automatic"},
        credential_ref="domain",
        interval_minutes=60,
    )
    assert rev1 == 1

    # 模拟产生 cursor 与分析快照
    with tmp_db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET cursor_json = ? WHERE deliverable_id = ?",
            (json.dumps({"aggregate_last_content_version": "agg:v1"}), deliverable_id),
        )
        conn.execute(
            """
            INSERT INTO project_status_analysis_snapshots
                (deliverable_id, total_count, completed_count, incomplete_count,
                 overdue_count, due_soon_count, missing_due_date_count, snapshot_at)
            VALUES (?, 1, 1, 0, 0, 1, 0, '2026-09-13 12:00:00')
            """,
            (deliverable_id,),
        )

    # 2. 仅修改 interval_minutes：revision 不变，cursor 与快照保留
    rev_same = tmp_db.set_project_status_update_policy(
        deliverable_id=deliverable_id,
        mode="automatic",
        enabled=True,
        external_key=None,
        match_rule_json=rule_1,
        mapping_json=mapping_1,
        field_authority={"owner": "automatic", "remark": "automatic"},
        credential_ref="domain",
        interval_minutes=120,
    )
    assert rev_same == 1
    with tmp_db.get_connection() as conn:
        b = conn.execute("SELECT cursor_json, sync_config_revision FROM project_status_update_bindings WHERE deliverable_id = ?", (deliverable_id,)).fetchone()
        assert "agg:v1" in b["cursor_json"]
        assert b["sync_config_revision"] == 1
        s = conn.execute("SELECT count(*) FROM project_status_analysis_snapshots WHERE deliverable_id = ?", (deliverable_id,)).fetchone()
        assert s[0] == 1

    # 3. 换绑（车型变更）：revision 递增，cursor 重置为 {}，快照被清空
    rule_2 = json.dumps({"reportType": "data_model", "aggregate": True, "projectModel": "F620S"})
    rev2 = tmp_db.set_project_status_update_policy(
        deliverable_id=deliverable_id,
        mode="automatic",
        enabled=True,
        external_key=None,
        match_rule_json=rule_2,
        mapping_json=mapping_1,
        field_authority={"owner": "automatic", "remark": "automatic"},
        credential_ref="domain",
        interval_minutes=120,
    )
    assert rev2 == 2
    with tmp_db.get_connection() as conn:
        b = conn.execute("SELECT cursor_json, sync_config_revision FROM project_status_update_bindings WHERE deliverable_id = ?", (deliverable_id,)).fetchone()
        assert b["cursor_json"] == "{}"
        assert b["sync_config_revision"] == 2
        s = conn.execute("SELECT count(*) FROM project_status_analysis_snapshots WHERE deliverable_id = ?", (deliverable_id,)).fetchone()
        assert s[0] == 0


def test_aggregate_cursor_advances_only_on_full_apply(tmp_db) -> None:
    """聚合模式：部分字段锁定被跳过时不推进 cursor，全量应用时推进。"""
    from services.project_status_updates import ProjectStatusUpdateService
    service = ProjectStatusUpdateService(tmp_db)
    deliverable_id = "VPI-T2-D5"
    rule = json.dumps({"reportType": "data_model", "aggregate": True, "projectModel": "F610S"})
    mapping_dict = {"owner": "currentApprover", "note": "summaryNote"}
    mapping_manual = json.dumps({"note": "summaryNote"})
    mapping = json.dumps(mapping_dict)

    # 设置 owner 为 manual，remark 为 automatic
    tmp_db.set_project_status_update_policy(
        deliverable_id=deliverable_id,
        mode="automatic",
        enabled=True,
        external_key=None,
        match_rule_json=rule,
        mapping_json=mapping_manual,
        field_authority={"owner": "manual", "remark": "automatic"},
        credential_ref="domain",
    )

    rows = [{"incident": "F610S-01", "currentApprover": "王五", "summaryNote": "阶段卡点"}]
    _record_aggregate_evidence(tmp_db, deliverable_id, rule, rows)

    # 第 1 次同步：部分应用（owner 锁定被跳过）
    lease1 = service.acquire_sync_lease(deliverable_id, "scheduled", validate_runtime_prerequisites=False)
    ctx1 = _aggregate_context(expected_deliverable_updated_at=_current_updated_at(tmp_db, deliverable_id), mapping=mapping_dict)
    snap1 = _snapshot(ctx1, rows, [])
    res1 = service.apply_sync_update(
        binding_id=int(lease1["binding_id"]),
        run_id=int(lease1["run_id"]),
        lease_token=lease1["lease_token"],
        snapshot=snap1,
        trigger_type="scheduled",
    )
    assert res1.final_state == "partial"
    assert "owner" in res1.skipped_fields

    # 游标基线失效（P1-3）
    binding_row = tmp_db.get_sync_binding_by_deliverable(deliverable_id)
    cursor1 = json.loads(binding_row["cursor_json"])
    assert cursor1.get("aggregate_last_content_version") is None

    # 将 owner 改为 automatic
    tmp_db.set_project_status_update_policy(
        deliverable_id=deliverable_id,
        mode="automatic",
        enabled=True,
        external_key=None,
        match_rule_json=rule,
        mapping_json=mapping,
        field_authority={"owner": "automatic", "remark": "automatic"},
        credential_ref="domain",
    )

    # 第 2 次同步：全量应用，游标推进
    lease2 = service.acquire_sync_lease(deliverable_id, "scheduled", validate_runtime_prerequisites=False)
    ctx2 = _aggregate_context(expected_deliverable_updated_at=_current_updated_at(tmp_db, deliverable_id), mapping=mapping_dict)
    snap2 = _snapshot(ctx2, rows, [])
    res2 = service.apply_sync_update(
        binding_id=int(lease2["binding_id"]),
        run_id=int(lease2["run_id"]),
        lease_token=lease2["lease_token"],
        snapshot=snap2,
        trigger_type="scheduled",
    )
    assert res2.final_state == "success"
    assert not res2.skipped_fields

    # 游标成功推进并记录内容版本
    binding_row2 = tmp_db.get_sync_binding_by_deliverable(deliverable_id)
    cursor2 = json.loads(binding_row2["cursor_json"])
    assert cursor2.get("aggregate_last_content_version") == snap2.external_version


def test_aggregate_cursor_dedup_a_b_a(tmp_db) -> None:
    """聚合模式 A→A(去重)→B(应用)→A(从B变回A正常应用)。"""
    from services.project_status_updates import ProjectStatusUpdateService
    service = ProjectStatusUpdateService(tmp_db)
    deliverable_id = "VPI-T2-D5"
    rule = json.dumps({"reportType": "data_model", "aggregate": True, "projectModel": "F610S"})
    mapping_dict = {"owner": "currentApprover", "note": "summaryNote"}
    mapping = json.dumps(mapping_dict)

    tmp_db.set_project_status_update_policy(
        deliverable_id=deliverable_id,
        mode="automatic",
        enabled=True,
        external_key=None,
        match_rule_json=rule,
        mapping_json=mapping,
        field_authority={"owner": "automatic", "remark": "automatic"},
        credential_ref="domain",
    )

    rows_a = [{"incident": "F610S-01", "currentApprover": "张三", "summaryNote": "A内容"}]
    rows_b = [{"incident": "F610S-01", "currentApprover": "李四", "summaryNote": "B内容"}]
    _record_aggregate_evidence(tmp_db, deliverable_id, rule, rows_a)

    # 1. 运行 A：应用
    lease1 = service.acquire_sync_lease(deliverable_id, "scheduled", validate_runtime_prerequisites=False)
    ctx1 = _aggregate_context(expected_deliverable_updated_at=_current_updated_at(tmp_db, deliverable_id), mapping=mapping_dict)
    snap_a1 = _snapshot(ctx1, rows_a, [])
    res1 = service.apply_sync_update(int(lease1["binding_id"]), int(lease1["run_id"]), lease1["lease_token"], snap_a1, "scheduled")
    assert res1.final_state == "success"
    assert "owner" in res1.applied_fields

    # 2. 再次运行 A：去重跳过
    lease2 = service.acquire_sync_lease(deliverable_id, "scheduled", validate_runtime_prerequisites=False)
    ctx2 = _aggregate_context(expected_deliverable_updated_at=_current_updated_at(tmp_db, deliverable_id), mapping=mapping_dict)
    snap_a2 = _snapshot(ctx2, rows_a, [])
    res2 = service.apply_sync_update(int(lease2["binding_id"]), int(lease2["run_id"]), lease2["lease_token"], snap_a2, "scheduled")
    assert res2.final_state == "success"
    assert len(res2.applied_fields) == 0

    # 3. 运行 B：内容变更，应用
    lease3 = service.acquire_sync_lease(deliverable_id, "scheduled", validate_runtime_prerequisites=False)
    ctx3 = _aggregate_context(expected_deliverable_updated_at=_current_updated_at(tmp_db, deliverable_id), mapping=mapping_dict)
    snap_b = _snapshot(ctx3, rows_b, [])
    res3 = service.apply_sync_update(int(lease3["binding_id"]), int(lease3["run_id"]), lease3["lease_token"], snap_b, "scheduled")
    assert res3.final_state == "success"
    assert "owner" in res3.applied_fields

    # 4. 从 B 变回 A：再次应用（证明并非全局已见哈希集合去重）
    lease4 = service.acquire_sync_lease(deliverable_id, "scheduled", validate_runtime_prerequisites=False)
    ctx4 = _aggregate_context(expected_deliverable_updated_at=_current_updated_at(tmp_db, deliverable_id), mapping=mapping_dict)
    snap_a3 = _snapshot(ctx4, rows_a, [])
    res4 = service.apply_sync_update(int(lease4["binding_id"]), int(lease4["run_id"]), lease4["lease_token"], snap_a3, "scheduled")
    assert res4.final_state == "success"
    assert "owner" in res4.applied_fields


def test_in_flight_sync_superseded_by_config_revision(tmp_db) -> None:
    """在途任务获取租约后发生换绑（revision自增），提交时被安全拦截转入 needs_attention。"""
    from services.project_status_updates import ProjectStatusUpdateService
    service = ProjectStatusUpdateService(tmp_db)
    deliverable_id = "VPI-T2-D5"
    rule_old = json.dumps({"reportType": "data_model", "aggregate": True, "projectModel": "F610S"})
    mapping_dict = {"owner": "currentApprover", "note": "summaryNote"}
    mapping = json.dumps(mapping_dict)

    tmp_db.set_project_status_update_policy(
        deliverable_id=deliverable_id,
        mode="automatic",
        enabled=True,
        external_key=None,
        match_rule_json=rule_old,
        mapping_json=mapping,
        field_authority={"owner": "automatic", "remark": "automatic"},
        credential_ref="domain",
    )

    # 1. 任务在途启动，租约与 run 记录当时 revision
    _record_aggregate_evidence(
        tmp_db,
        deliverable_id,
        rule_old,
        [{"incident": "F610S-01", "currentApprover": "在途人员", "summaryNote": "旧车型内容"}],
    )
    lease = service.acquire_sync_lease(deliverable_id, "scheduled", validate_runtime_prerequisites=False)
    binding_id = int(lease["binding_id"])
    run_id = int(lease["run_id"])
    lease_token = lease["lease_token"]

    ctx = _aggregate_context(expected_deliverable_updated_at=_current_updated_at(tmp_db, deliverable_id), mapping=mapping_dict)
    snap = _snapshot(ctx, [{"incident": "F610S-01", "currentApprover": "在途人员", "summaryNote": "旧车型内容"}], [])

    # 2. 在途期间后台换绑（切换车型，revision 发生变更）
    rule_new = json.dumps({"reportType": "data_model", "aggregate": True, "projectModel": "F620S"})
    tmp_db.set_project_status_update_policy(
        deliverable_id=deliverable_id,
        mode="automatic",
        enabled=True,
        external_key=None,
        match_rule_json=rule_new,
        mapping_json=mapping,
        field_authority={"owner": "automatic", "remark": "automatic"},
        credential_ref="domain",
    )

    # 3. 在途旧任务试图提交
    res = service.apply_sync_update(
        binding_id=binding_id,
        run_id=run_id,
        lease_token=lease_token,
        snapshot=snap,
        trigger_type="scheduled",
    )

    # 验证安全拦截
    assert res.final_state == "needs_attention"
    assert "binding config changed" in res.message
    assert len(res.applied_fields) == 0

    # 验证业务表未被污染
    phase, _, deliverables = tmp_db.get_project_status("VPI-T2")
    d5 = next(d for d in deliverables if d["id"] == deliverable_id)
    assert d5["owner"] != "在途人员"

    # 验证租约已释放，且 binding 状态为 needs_attention 而非 success（P2-7）
    b = tmp_db.get_sync_binding_by_deliverable(deliverable_id)
    assert b["lease_token"] is None
    assert b["sync_state"] == "needs_attention"

    run_row = tmp_db.get_sync_run(run_id)
    assert run_row["run_state"] == "needs_attention"
    assert run_row["error_type"] == "binding_config_superseded"


def test_partial_aba_resets_cursor_baseline_and_restores_business_values(tmp_db) -> None:
    """【P1-3 严密回归】A 全量 → B 部分 → A 重新全量应用，业务行不残留 B。"""
    from services.project_status_updates import ProjectStatusUpdateService
    service = ProjectStatusUpdateService(tmp_db)
    deliverable_id = "VPI-T2-D5"
    rule = json.dumps({"reportType": "data_model", "aggregate": True, "projectModel": "F610S"})
    mapping_dict = {"owner": "currentApprover", "note": "summaryNote"}
    mapping = json.dumps(mapping_dict)

    tmp_db.set_project_status_update_policy(
        deliverable_id=deliverable_id,
        mode="automatic",
        enabled=True,
        external_key=None,
        match_rule_json=rule,
        mapping_json=mapping,
        field_authority={"owner": "automatic", "remark": "automatic"},
        credential_ref="domain",
    )

    rows_a = [{"incident": "1", "currentApprover": "owner-A", "summaryNote": "note-A"}]
    rows_b = [{"incident": "1", "currentApprover": "owner-B", "summaryNote": "note-B"}]
    _record_aggregate_evidence(tmp_db, deliverable_id, rule, rows_a)

    # 1. 运行 A：全量成功应用
    lease1 = service.acquire_sync_lease(deliverable_id, "scheduled", validate_runtime_prerequisites=False)
    ctx1 = _aggregate_context(expected_deliverable_updated_at=_current_updated_at(tmp_db, deliverable_id), mapping=mapping_dict)
    res1 = service.apply_sync_update(int(lease1["binding_id"]), int(lease1["run_id"]), lease1["lease_token"], _snapshot(ctx1, rows_a, []), "scheduled")
    assert res1.final_state == "success"
    d_after_a = next(d for d in tmp_db.get_project_status("VPI-T2")[2] if d["id"] == deliverable_id)
    assert d_after_a["owner"] == "owner-A"
    assert d_after_a["remark"] == "note-A"
    cursor_a = json.loads(tmp_db.get_sync_binding_by_deliverable(deliverable_id)["cursor_json"])
    assert cursor_a.get("aggregate_last_content_version") is not None

    # 2. 锁定 owner，运行 B：部分应用（remark 写为 note-B，owner 跳过）
    tmp_db.set_project_status_update_policy(
        deliverable_id=deliverable_id,
        mode="automatic",
        enabled=True,
        external_key=None,
        match_rule_json=rule,
        mapping_json=json.dumps({"note": "summaryNote"}),
        field_authority={"owner": "manual", "remark": "automatic"},
        credential_ref="domain",
    )
    lease2 = service.acquire_sync_lease(deliverable_id, "scheduled", validate_runtime_prerequisites=False)
    ctx2 = _aggregate_context(expected_deliverable_updated_at=_current_updated_at(tmp_db, deliverable_id), mapping=mapping_dict)
    res2 = service.apply_sync_update(int(lease2["binding_id"]), int(lease2["run_id"]), lease2["lease_token"], _snapshot(ctx2, rows_b, []), "scheduled")
    assert res2.final_state == "partial"
    assert "owner" in res2.skipped_fields
    d_after_b = next(d for d in tmp_db.get_project_status("VPI-T2")[2] if d["id"] == deliverable_id)
    assert d_after_b["owner"] == "owner-A"  # 保持原值
    assert d_after_b["remark"] == "note-B"  # 写入新值
    # 关键：部分应用后，聚合游标基线必须失效为 None（P1-3 核心）
    cursor_b = json.loads(tmp_db.get_sync_binding_by_deliverable(deliverable_id)["cursor_json"])
    assert cursor_b.get("aggregate_last_content_version") is None

    # 3. 解锁 owner，外部来源变回 A：A 不得被误判去重，必须全量应用并将 remark 恢复为 note-A！
    tmp_db.set_project_status_update_policy(
        deliverable_id=deliverable_id,
        mode="automatic",
        enabled=True,
        external_key=None,
        match_rule_json=rule,
        mapping_json=mapping,
        field_authority={"owner": "automatic", "remark": "automatic"},
        credential_ref="domain",
    )
    lease3 = service.acquire_sync_lease(deliverable_id, "scheduled", validate_runtime_prerequisites=False)
    ctx3 = _aggregate_context(expected_deliverable_updated_at=_current_updated_at(tmp_db, deliverable_id), mapping=mapping_dict)
    res3 = service.apply_sync_update(int(lease3["binding_id"]), int(lease3["run_id"]), lease3["lease_token"], _snapshot(ctx3, rows_a, []), "scheduled")
    assert res3.final_state == "success"
    assert "note" in res3.applied_fields or "owner" in res3.applied_fields

    # 最终业务行断言：remark 必须是 note-A，绝不能残留 note-B！
    d_final = next(d for d in tmp_db.get_project_status("VPI-T2")[2] if d["id"] == deliverable_id)
    assert d_final["owner"] == "owner-A"
    assert d_final["remark"] == "note-A"


def test_runner_listing_then_rebind_rejects_stale_batch_and_protects_business_row(tmp_db) -> None:
    """【P1-2 严密回归】列出 A 后发生换绑 B，尝试执行旧 binding 批次被安全拦截，不写入错误数据。"""
    from services.project_status_sync_runner import ProjectStatusSyncRunner, ConnectorRegistry
    from services.project_status_updates import ProjectStatusUpdateService
    deliverable_id = "VPI-T2-D5"
    rule_a = json.dumps({"reportType": "data_model", "aggregate": True, "carTypeProjectId": "CAR-A"})
    rule_b = json.dumps({"reportType": "data_model", "aggregate": True, "carTypeProjectId": "CAR-B"})
    mapping = json.dumps({"owner": "who", "note": "note"})

    # 1. 设置配置 A 并列出可运行绑定
    tmp_db.set_project_status_update_policy(
        deliverable_id=deliverable_id,
        mode="automatic",
        enabled=True,
        external_key=None,
        match_rule_json=rule_a,
        mapping_json=mapping,
        field_authority={"owner": "automatic", "remark": "automatic"},
        credential_ref="domain",
    )
    stale_listing = tmp_db.list_eligible_sync_bindings(deliverable_id)[0]

    # 2. 外部发生换绑为 CAR-B
    tmp_db.set_project_status_update_policy(
        deliverable_id=deliverable_id,
        mode="automatic",
        enabled=True,
        external_key=None,
        match_rule_json=rule_b,
        mapping_json=mapping,
        field_authority={"owner": "automatic", "remark": "automatic"},
        credential_ref="domain",
    )

    # 3. 模拟 connector 试图返回旧车型 A 的数据
    class MockConnector:
        def collect(self, context):
            return _snapshot(context, [{"incident": "1", "who": "owner-A", "note": "note-A"}], [])

    reg = ConnectorRegistry()
    reg.register("tdc", MockConnector())
    runner = ProjectStatusSyncRunner(tmp_db, ProjectStatusUpdateService(tmp_db), reg)

    # 4. 执行旧批次
    run_result = runner._run_single_binding(stale_listing, "scheduled", validate_runtime_prerequisites=False)

    # 验证安全拦截：状态转为 needs_attention，且业务表未被污染为 note-A
    assert run_result.final_state == "needs_attention"
    assert run_result.error_type == "binding_not_ready"
    d_current = next(d for d in tmp_db.get_project_status("VPI-T2")[2] if d["id"] == deliverable_id)
    assert d_current["remark"] != "note-A"


def test_finalize_sync_success_begin_immediate_prevents_concurrent_write_interleaving(tmp_db) -> None:
    """【P1-1 严密回归】实际 finalize 路径持锁时，独立连接不能插入换绑。"""
    import sqlite3
    import threading

    from services.project_status_updates import ProjectStatusUpdateService

    service = ProjectStatusUpdateService(tmp_db)
    deliverable_id = "VPI-T2-D5"
    rule_dict = {"reportType": "data_model", "aggregate": True, "projectModel": "F610S"}
    rule = json.dumps(rule_dict)
    mapping_dict = {"owner": "currentApprover", "note": "summaryNote"}
    mapping = json.dumps(mapping_dict)

    tmp_db.set_project_status_update_policy(
        deliverable_id=deliverable_id,
        mode="automatic",
        enabled=True,
        external_key=None,
        match_rule_json=rule,
        mapping_json=mapping,
        field_authority={"owner": "automatic", "remark": "automatic"},
        credential_ref="domain",
    )

    rows = [{"incident": "1", "currentApprover": "张三", "summaryNote": "内容"}]
    discovery = __import__("services.project_status_discovery", fromlist=["MappingDiscoveryService"]).MappingDiscoveryService(tmp_db)
    discovery.observe(deliverable_id, "tdc", rows, aggregate=True, match_rule=rule_dict)
    discovery.observe(deliverable_id, "tdc", rows, aggregate=True, match_rule=rule_dict)
    lease = service.acquire_sync_lease(deliverable_id, "scheduled")
    ctx = _aggregate_context(
        expected_deliverable_updated_at=_current_updated_at(tmp_db, deliverable_id),
        mapping=mapping_dict,
    )
    snap = _snapshot(ctx, rows, [])

    finalize_entered = threading.Event()
    release_finalize = threading.Event()
    worker_result: list[object] = []
    worker_error: list[BaseException] = []
    original_assert_lease_holder = tmp_db._assert_lease_holder
    assert_lease_holder_calls = 0

    def wrapped_assert_lease_holder(conn, *args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal assert_lease_holder_calls
        result = original_assert_lease_holder(conn, *args, **kwargs)
        assert_lease_holder_calls += 1
        # apply_sync_update reaches this hook only after
        # finalize_sync_success has executed BEGIN IMMEDIATE.  The event is
        # therefore a proof point inside the product transaction, not a
        # caller-created lock.
        finalize_entered.set()
        if not release_finalize.wait(5.0):
            raise AssertionError("test did not release the product transaction")
        return result

    tmp_db._assert_lease_holder = wrapped_assert_lease_holder  # type: ignore[method-assign]
    conn2 = None
    worker = None
    try:
        def apply_worker() -> None:
            try:
                worker_result.append(
                    service.apply_sync_update(
                        binding_id=int(lease["binding_id"]),
                        run_id=int(lease["run_id"]),
                        lease_token=lease["lease_token"],
                        snapshot=snap,
                        trigger_type="scheduled",
                    )
                )
            except BaseException as exc:  # report the worker failure in the main assertion
                worker_error.append(exc)

        worker = threading.Thread(target=apply_worker, name="aggregate-finalize-test")
        worker.start()
        assert finalize_entered.wait(2.0), "apply_sync_update did not reach finalize_sync_success"
        assert assert_lease_holder_calls == 1

        conn2 = sqlite3.connect(str(tmp_db.db_path), timeout=0.05)
        conn2.execute("PRAGMA busy_timeout=50")
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            conn2.execute(
                "UPDATE project_status_update_bindings "
                "SET match_rule_json = ?, sync_config_revision = sync_config_revision + 1 "
                "WHERE deliverable_id = ?",
                (
                    json.dumps(
                        {"reportType": "data_model", "aggregate": True, "projectModel": "F620S"}
                    ),
                    deliverable_id,
                ),
            )
        conn2.rollback()
        release_finalize.set()
    finally:
        release_finalize.set()
        if conn2 is not None:
            conn2.close()
        if worker is not None:
            worker.join(timeout=5.0)
        tmp_db._assert_lease_holder = original_assert_lease_holder  # type: ignore[method-assign]

    assert not worker_error
    assert worker_result and worker_result[0].final_state == "success"
    current = next(
        row for row in tmp_db.get_project_status("VPI-T2")[2] if row["id"] == deliverable_id
    )
    assert current["owner"] == "张三"
    assert current["remark"] == "内容"
    binding = tmp_db.get_sync_binding_by_deliverable(deliverable_id)
    with tmp_db.get_connection() as conn:
        revision_row = conn.execute(
            "SELECT sync_config_revision, match_rule_json "
            "FROM project_status_update_bindings WHERE deliverable_id = ?",
            (deliverable_id,),
        ).fetchone()
    assert revision_row["sync_config_revision"] == 1
    assert json.loads(revision_row["match_rule_json"]) == rule_dict
    cursor = json.loads(binding["cursor_json"])
    assert cursor["aggregate_last_content_version"] == snap.external_version
    run = tmp_db.get_sync_run(int(lease["run_id"]))
    assert run["run_state"] == "success"
    with tmp_db.get_connection() as conn:
        lease_row = conn.execute(
            "SELECT lease_token FROM project_status_update_bindings WHERE deliverable_id = ?",
            (deliverable_id,),
        ).fetchone()
    assert lease_row["lease_token"] is None
    with tmp_db.get_connection() as conn:
        audit = conn.execute(
            """
            SELECT result, external_version
            FROM project_status_update_audit
            WHERE deliverable_id = ? AND external_version = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (deliverable_id, snap.external_version),
        ).fetchone()
    assert audit is not None
    assert audit["result"] == "applied"
    assert audit["external_version"] == snap.external_version
