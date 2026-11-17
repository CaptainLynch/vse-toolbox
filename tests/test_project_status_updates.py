# -*- coding: utf-8 -*-
"""ProjectStatusUpdateService focused contracts for the VPI-T2-D5 pilot."""

from __future__ import annotations

import json

import pytest

from core.db_manager import DatabaseManager, MappedDeliverableReadOnlyError
from services.project_status_updates import (
    PROJECT_STATUS_EDITABLE_FIELDS,
    ProjectStatusPolicyError,
    ProjectStatusUpdateService,
)
from services.project_status_records import compute_config_signature


@pytest.fixture()
def service(tmp_db: DatabaseManager) -> ProjectStatusUpdateService:
    return ProjectStatusUpdateService(tmp_db)


def _record_two_observations_for_d5(
    db: DatabaseManager,
    deliverable_id: str = "VPI-T2-D5",
    source_type: str = "tdc",
    external_key: str = "FM-1",
    fields: list[str] | None = None,
    match_rule: dict[str, object] | None = None,
) -> None:
    """Record two matched tdc observations for the same external key."""
    effective_rule = match_rule or {
        "reportType": "data_model",
        "incident": external_key,
    }
    config_signature = compute_config_signature(source_type, effective_rule)
    field_list = fields if fields is not None else [
        "currentApprover", "approvalComment", "incident", "reportType",
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
        config_signature=config_signature,
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
        config_signature=config_signature,
    )


def _current_deliverable(db: DatabaseManager, deliverable_id: str):
    phase, _, deliverables = db.get_project_status("VPI-T2")
    assert phase is not None
    return next(row for row in deliverables if row["id"] == deliverable_id)


def _manual_values(row, **overrides):
    values = {
        "status": row["status"],
        "owner": row["owner"],
        "planned_date": row["planned_date"],
        "actual_date": row["actual_date"],
        "progress": row["progress"],
        "remark": row["remark"],
    }
    values.update(overrides)
    return values


def test_default_policy_and_field_authority(service) -> None:
    policy = service.get_update_policy("VPI-T2-D5")
    assert policy is not None
    assert policy["deliverableId"] == "VPI-T2-D5"
    # 契约内交付物新库默认自动同步模式（未启用，待配置）。
    assert policy["mode"] == "automatic"
    assert policy["sourceType"] == "tdc"
    assert policy["enabled"] is False
    assert policy["externalKey"] is None
    assert policy["matchRule"] == {}
    assert policy["mapping"] == {}
    assert policy["syncState"] == "idle"
    assert policy["latestUpdate"] is None
    assert set(policy["fieldAuthority"]) == set(PROJECT_STATUS_EDITABLE_FIELDS)
    assert all(value == "manual" for value in policy["fieldAuthority"].values())


def test_manual_update_locks_only_changed_fields_and_sanitizes_audit(
    service, tmp_db: DatabaseManager
) -> None:
    service.update_update_policy(
        "VPI-T2-D5",
        {
            "mode": "hybrid",
            "fieldAuthority": {
                "owner": "automatic",
                "note": "automatic",
            },
        },
    )
    row = _current_deliverable(tmp_db, "VPI-T2-D5")
    values = _manual_values(
        row,
        progress=83,
        remark="推进中 password=hunter2",
    )
    service.apply_manual_update("VPI-T2-D5", "VPI-T2", values, str(row["updated_at"]))

    policy = service.get_update_policy("VPI-T2-D5")
    assert policy["fieldAuthority"]["owner"] == "automatic"
    assert policy["fieldAuthority"]["note"] == "manual"

    updates = service.list_updates("VPI-T2-D5")
    assert updates["total"] == 1
    item = updates["updates"][0]
    assert item["triggerType"] == "manual"
    assert item["result"] == "applied"
    assert item["appliedChanges"]["progress"] == 83
    assert "hunter2" not in str(item["proposedChanges"])
    assert "[redacted]" in str(item["proposedChanges"])


def test_manual_update_optimistic_conflict_raises(service, tmp_db: DatabaseManager) -> None:
    row = _current_deliverable(tmp_db, "VPI-T2-D5")
    values = _manual_values(row, progress=84)
    service.apply_manual_update("VPI-T2-D5", "VPI-T2", values, str(row["updated_at"]))
    with pytest.raises(RuntimeError):
        service.apply_manual_update("VPI-T2-D5", "VPI-T2", values, str(row["updated_at"]))
    assert service.list_updates("VPI-T2-D5")["total"] == 1


def test_audit_capped_at_100(service, tmp_db: DatabaseManager) -> None:
    for index in range(105):
        row = _current_deliverable(tmp_db, "VPI-T2-D5")
        values = _manual_values(row, remark=f"audit {index}")
        service.apply_manual_update(
            "VPI-T2-D5",
            "VPI-T2",
            values,
            str(row["updated_at"]),
        )
    updates = service.list_updates("VPI-T2-D5")
    assert updates["total"] == 100
    assert updates["updates"][0]["id"] > updates["updates"][-1]["id"]


def test_manual_update_denied_for_paused_mapped_binding_without_mutation(
    service: ProjectStatusUpdateService,
    tmp_db: DatabaseManager,
) -> None:
    """A configured target stays read-only after a failed/paused run."""
    with tmp_db.get_connection() as conn:
        conn.execute(
            """
            UPDATE project_status_update_bindings
            SET mode = 'automatic', enabled = 0, external_key = ?,
                match_rule_json = ?, mapping_json = ?, sync_state = 'failed',
                last_error_type = 'SyntheticFailure'
            WHERE deliverable_id = ?
            """,
            (
                "FM-1",
                json.dumps({"reportType": "data_model", "incident": "FM-1"}),
                json.dumps({"owner": "currentApprover"}),
                "VPI-T2-D5",
            ),
        )
    before = _current_deliverable(tmp_db, "VPI-T2-D5")
    values = _manual_values(before, progress=77)
    with tmp_db.get_connection() as conn:
        before_authority = [
            tuple(row)
            for row in conn.execute(
                """
                SELECT field_name, authority, source_type, locked_at, updated_at
                FROM project_status_field_authority
                WHERE deliverable_id = ? ORDER BY field_name
                """,
                ("VPI-T2-D5",),
            ).fetchall()
        ]
        before_audit_count = conn.execute(
            "SELECT COUNT(*) FROM project_status_update_audit WHERE deliverable_id = ?",
            ("VPI-T2-D5",),
        ).fetchone()[0]
        before_phase = conn.execute(
            "SELECT updated_at FROM project_status_phases WHERE id = 'VPI-T2'"
        ).fetchone()[0]

    with pytest.raises(MappedDeliverableReadOnlyError) as exc_info:
        service.apply_manual_update(
            "VPI-T2-D5", "VPI-T2", values, str(before["updated_at"])
        )
    assert "映射" in str(exc_info.value)
    with pytest.raises(MappedDeliverableReadOnlyError):
        tmp_db.update_project_status_deliverable(
            "VPI-T2-D5",
            "VPI-T2",
            {"progress": 77},
            str(before["updated_at"]),
        )

    after = _current_deliverable(tmp_db, "VPI-T2-D5")
    assert tuple(after) == tuple(before)
    with tmp_db.get_connection() as conn:
        after_authority = [
            tuple(row)
            for row in conn.execute(
                """
                SELECT field_name, authority, source_type, locked_at, updated_at
                FROM project_status_field_authority
                WHERE deliverable_id = ? ORDER BY field_name
                """,
                ("VPI-T2-D5",),
            ).fetchall()
        ]
        after_audit_count = conn.execute(
            "SELECT COUNT(*) FROM project_status_update_audit WHERE deliverable_id = ?",
            ("VPI-T2-D5",),
        ).fetchone()[0]
        after_phase = conn.execute(
            "SELECT updated_at FROM project_status_phases WHERE id = 'VPI-T2'"
        ).fetchone()[0]
    assert after_authority == before_authority
    assert after_audit_count == before_audit_count == 0
    assert after_phase == before_phase


def test_manual_update_malformed_nonempty_binding_fails_closed(
    service: ProjectStatusUpdateService,
    tmp_db: DatabaseManager,
) -> None:
    """Malformed nonempty rules cannot reopen a manual write path."""
    with tmp_db.get_connection() as conn:
        conn.execute(
            """
            UPDATE project_status_update_bindings
            SET match_rule_json = '{not-json}', mapping_json = '{}'
            WHERE deliverable_id = 'VPI-T2-D5'
            """
        )
    row = _current_deliverable(tmp_db, "VPI-T2-D5")
    with pytest.raises(MappedDeliverableReadOnlyError):
        service.apply_manual_update(
            "VPI-T2-D5",
            "VPI-T2",
            _manual_values(row, progress=66),
            str(row["updated_at"]),
        )


@pytest.mark.parametrize(
    ("rule_json", "mapping_json", "external_key"),
    [
        ('{"reportType":"data_model","incident":"FM-1\\u0000"}', "{}", None),
        ('{"reportType":"data_model","incident":"FM-1"}', '{"note":["approver\\u0000"]}', None),
        ('{"reportType":"data_model","incident":"FM-1"}', "{}", "FM-1\x00"),
        ('{"reportType":"data_model","incident":"' + ('A' * 4005) + '"}', "{}", None),
        ('{"reportType":"data_model","incident":"FM-1"}', '{"note":["' + ('B' * 4005) + '"]}', None),
    ],
)
def test_manual_update_abnormal_rules_fail_closed_without_side_effects(
    service: ProjectStatusUpdateService,
    tmp_db: DatabaseManager,
    rule_json: str,
    mapping_json: str,
    external_key: str | None,
) -> None:
    """Abnormal rules (control chars, oversized) must fail closed with no side effects."""
    with tmp_db.get_connection() as conn:
        conn.execute(
            """
            UPDATE project_status_update_bindings
            SET mode = 'hybrid', enabled = 0, external_key = ?,
                match_rule_json = ?, mapping_json = ?, sync_state = 'idle'
            WHERE deliverable_id = 'VPI-T2-D5'
            """,
            (external_key, rule_json, mapping_json),
        )
    before = _current_deliverable(tmp_db, "VPI-T2-D5")
    values = _manual_values(before, progress=88, remark="attempt update")
    with tmp_db.get_connection() as conn:
        before_authority = [
            tuple(row)
            for row in conn.execute(
                """
                SELECT field_name, authority, source_type, locked_at, updated_at
                FROM project_status_field_authority
                WHERE deliverable_id = 'VPI-T2-D5' ORDER BY field_name
                """
            ).fetchall()
        ]
        before_audit_count = conn.execute(
            "SELECT COUNT(*) FROM project_status_update_audit WHERE deliverable_id = 'VPI-T2-D5'"
        ).fetchone()[0]
        before_phase = conn.execute(
            "SELECT updated_at FROM project_status_phases WHERE id = 'VPI-T2'"
        ).fetchone()[0]

    with pytest.raises(MappedDeliverableReadOnlyError) as exc_info:
        service.apply_manual_update(
            "VPI-T2-D5", "VPI-T2", values, str(before["updated_at"])
        )
    assert "外部来源映射规则无效" in str(exc_info.value) or "映射" in str(exc_info.value)

    with pytest.raises(MappedDeliverableReadOnlyError):
        tmp_db.update_project_status_deliverable(
            "VPI-T2-D5",
            "VPI-T2",
            {"progress": 88},
            str(before["updated_at"]),
        )

    after = _current_deliverable(tmp_db, "VPI-T2-D5")
    assert tuple(after) == tuple(before)
    with tmp_db.get_connection() as conn:
        after_authority = [
            tuple(row)
            for row in conn.execute(
                """
                SELECT field_name, authority, source_type, locked_at, updated_at
                FROM project_status_field_authority
                WHERE deliverable_id = 'VPI-T2-D5' ORDER BY field_name
                """
            ).fetchall()
        ]
        after_audit_count = conn.execute(
            "SELECT COUNT(*) FROM project_status_update_audit WHERE deliverable_id = 'VPI-T2-D5'"
        ).fetchone()[0]
        after_phase = conn.execute(
            "SELECT updated_at FROM project_status_phases WHERE id = 'VPI-T2'"
        ).fetchone()[0]
    assert after_authority == before_authority
    assert after_audit_count == before_audit_count == 0
    assert after_phase == before_phase


def test_enable_requires_external_key_and_allowed_match_rule(service) -> None:
    with pytest.raises(ProjectStatusPolicyError) as exc:
        service.update_update_policy("VPI-T2-D5", {"enabled": True})
    assert "externalKey" in exc.value.fields
    assert "matchRule" in exc.value.fields

    with pytest.raises(ProjectStatusPolicyError) as exc:
        service.update_update_policy(
            "VPI-T2-D5",
            {"enabled": True, "externalKey": "FM-1", "matchRule": {}},
        )
    assert "matchRule" in exc.value.fields

    _record_two_observations_for_d5(
        service._db,
        deliverable_id="VPI-T2-D5",
        source_type="tdc",
        external_key="FM-1",
    )
    policy = service.update_update_policy(
        "VPI-T2-D5",
        {
            "mode": "hybrid",
            "enabled": True,
            "externalKey": "FM-1",
            "credentialRef": "placeholder_cred_alias",
            "matchRule": {"reportType": "data_model", "incident": "FM-1"},
            "mapping": {"owner": "currentApprover"},
            "fieldAuthority": {"owner": "automatic"},
        },
    )
    assert policy["enabled"] is True
    assert policy["externalKey"] == "FM-1"
    assert policy["matchRule"] == {"reportType": "data_model", "incident": "FM-1"}


def test_ewo_model_info_match_rule_is_accepted_when_mapping_evidence_is_ready(service) -> None:
    """EWO 合同允许车型匹配键，且就绪证据完整时可以启用自动同步。"""
    _record_two_observations_for_d5(
        service._db,
        deliverable_id="VPI-T2-D3",
        source_type="aras",
        external_key="EWO-1",
        fields=["_rsp_name", "_required_date", "_subject", "_modelinfo"],
        match_rule={"reportType": "ewo", "modelInfo": "F610S"},
    )

    policy = service.update_update_policy(
        "VPI-T2-D3",
        {
            "mode": "automatic",
            "enabled": True,
            "externalKey": "EWO-1",
            "credentialRef": "domain",
            "matchRule": {"reportType": "ewo", "modelInfo": "F610S"},
            "mapping": {"owner": "_rsp_name"},
            "fieldAuthority": {"owner": "automatic"},
        },
    )

    assert policy["enabled"] is True
    assert policy["matchRule"] == {"reportType": "ewo", "modelInfo": "F610S"}


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"matchRule": {"url": "http://example.invalid"}}, "matchRule"),
        ({"matchRule": {"incident": "x", "randomKey": "y"}}, "matchRule"),
        ({"mapping": {"apiUrl": "http://example.invalid"}}, "mapping"),
        ({"sourceType": "feishu"}, "request"),
    ],
)
def test_policy_rejects_unknown_and_forbidden_config(service, payload, field) -> None:
    with pytest.raises(ProjectStatusPolicyError) as exc:
        service.update_update_policy("VPI-T2-D5", payload)
    assert field in exc.value.fields


@pytest.mark.parametrize("blocked_id", ["VPI-T2-D1", "VPI-T2-D4"])
def test_policy_blocks_automation_for_unsupported_targets(service, blocked_id: str) -> None:
    """D1 和 D4 保持禁止自动化配置（mode/enabled/fieldAuthority）。"""
    with pytest.raises(ProjectStatusPolicyError) as exc:
        service.update_update_policy(blocked_id, {"mode": "hybrid"})
    assert "mode" in exc.value.fields

    with pytest.raises(ProjectStatusPolicyError) as exc:
        service.update_update_policy(
            blocked_id,
            {
                "enabled": True,
                "externalKey": "k",
                "matchRule": {"incident": "x"},
            },
        )
    assert "enabled" in exc.value.fields

    with pytest.raises(ProjectStatusPolicyError) as exc:
        service.update_update_policy(
            blocked_id,
            {"fieldAuthority": {"owner": "automatic"}},
        )
    assert "fieldAuthority" in exc.value.fields


@pytest.mark.parametrize("allowed_id", ["VPI-T2-D2", "VPI-T2-D3", "VPI-T2-D5"])
def test_policy_allows_automation_for_supported_targets(service, allowed_id: str) -> None:
    """D2, D3, D5 属于允许目标，可成功配置 hybrid 模式。"""
    policy = service.update_update_policy(
        allowed_id,
        {
            "mode": "hybrid",
        },
    )
    assert policy["mode"] == "hybrid"


def test_manual_mode_rejects_automatic_field_authority(service) -> None:
    with pytest.raises(ProjectStatusPolicyError) as exc:
        service.update_update_policy(
            "VPI-T2-D5",
            {"mode": "manual", "fieldAuthority": {"status": "automatic"}},
        )
    assert "fieldAuthority" in exc.value.fields


def test_aggregate_evidence_fingerprint_mismatch_rejected(tmp_db: DatabaseManager) -> None:
    """GPT 终审 P2 回归：聚合模式下连续两次抓取的记录集合指纹不一致 →
    启用被拒（ready 计数与启用校验共用指纹一致规则）。"""
    import json
    service = ProjectStatusUpdateService(tmp_db)
    report = {
        "fields": ["currentApprover", "incident", "reportType"],
        "statusOrApprovalFields": [],
        "suggestedStatusMapping": [],
        "suggestedAutomaticFields": [],
        "requiresConfirmation": True,
    }
    evidence_signature = compute_config_signature(
        "tdc",
        {"reportType": "data_model", "aggregate": True, "incident": "FM-1"},
    )
    # 两次 matched 但记录集合指纹不同（第二次多了一条记录）。
    tmp_db.record_mapping_observation(
        "VPI-T2-D5", "tdc", "matched", None, "agg:fp-set-1", 2,
        json.dumps([{"externalKey": None, "fields": {}}]),
        json.dumps(report),
        evidence_signature,
    )
    tmp_db.record_mapping_observation(
        "VPI-T2-D5", "tdc", "matched", None, "agg:fp-set-2", 3,
        json.dumps([{"externalKey": None, "fields": {}}]),
        json.dumps(report),
        evidence_signature,
    )
    with pytest.raises(Exception) as exc_info:
        service.update_update_policy("VPI-T2-D5", {
            "mode": "automatic",
            "enabled": True,
            "credentialRef": "test-alias",
            "matchRule": {"reportType": "data_model", "aggregate": True, "incident": "FM-1"},
            "mapping": {"owner": "currentApprover"},
            "fieldAuthority": {"owner": "automatic"},
        })
    assert any("聚合证据不稳定" in msg for msg in exc_info.value.fields.values())


def test_aggregate_match_rule_requires_boolean_flag(tmp_db: DatabaseManager) -> None:
    """GPT 终审 P2 回归：aggregate 标记必须严格布尔，字符串 "false" 拒绝。"""
    service = ProjectStatusUpdateService(tmp_db)
    with pytest.raises(Exception) as exc_info:
        service.update_update_policy("VPI-T2-D5", {
            "mode": "automatic",
            "enabled": True,
            "credentialRef": "test-alias",
            "matchRule": {"reportType": "data_model", "aggregate": "false", "incident": "FM-1"},
            "mapping": {"owner": "currentApprover"},
            "fieldAuthority": {"owner": "automatic"},
        })
    assert any("aggregate 必须是布尔值" in msg for msg in exc_info.value.fields.values())


def test_migrate_v1_to_v2_with_valid_evidence_enables_directly(tmp_db: DatabaseManager) -> None:
    """Migrating legacy v1 EWO binding to v2 record_set with valid 2/2 evidence enables in one step."""
    from services.project_status_records import compute_config_signature
    service = ProjectStatusUpdateService(tmp_db)

    # 1. Database starts with a legacy v1 binding
    tmp_db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D3",
        mode="automatic",
        enabled=False,
        external_key=None,
        match_rule_json=json.dumps({"reportType": "ewo", "aggregate": False}),
        mapping_json=json.dumps({"note": "_subject"}),
        field_authority={"owner": "manual", "planned_date": "manual", "remark": "automatic"},
    )

    # 2. Record 2 matching observations for the new v2 rule
    new_rule = {
        "reportType": "ewo",
        "contractVersion": "2",
        "bindingMode": "record_set",
        "aggregate": True,
        "projectCode": "F610S",
    }
    sig = compute_config_signature("aras", new_rule)
    summary = json.dumps([{"externalKey": "agg:fp-1", "fields": {"_subject": "Test"}}])
    report = json.dumps({"fields": ["_subject", "_change_description"]})
    for _ in range(2):
        tmp_db.record_mapping_observation(
            "VPI-T2-D3", "aras", "matched", None, "agg:fp-1", 1,
            summary, report, config_signature=sig,
        )

    # 3. Update directly to v2 and enabled=True
    policy = service.update_update_policy("VPI-T2-D3", {
        "mode": "automatic",
        "enabled": True,
        "credentialRef": "test-alias",
        "bindingContractVersion": "2",
        "matchRule": new_rule,
        "mapping": {"note": "_subject"},
        "fieldAuthority": {"note": "automatic"},
        "intervalMinutes": 15,
    })
    assert policy["enabled"] is True
    assert policy["matchRule"]["contractVersion"] == "2"
    assert policy["matchRule"]["bindingMode"] == "record_set"
    assert policy["intervalMinutes"] == 15


def test_mapping_evidence_error_sanitizes_note_list_and_persists(tmp_db: DatabaseManager) -> None:
    """note 列表包含未知字段时只要有至少 1 个有效字段即放行并清洗写回，全未知则阻断。"""
    service = ProjectStatusUpdateService(tmp_db)
    match_rule = {
        "reportType": "data_model",
        "aggregate": True,
        "projectModel": "F610S",
    }
    sig = compute_config_signature("tdc", match_rule)
    summary = json.dumps([{"externalKey": "agg:fp-1", "fields": {"latestApproveLog": "ok"}}])
    report = json.dumps({"fields": ["latestApproveLog", "applicant", "incident"]})

    for _ in range(2):
        tmp_db.record_mapping_observation(
            "VPI-T2-D5", "tdc", "matched", None, "agg:fp-1", 1,
            summary, report, config_signature=sig,
        )

    # 1. 候选包含有效字段 latestApproveLog 与未知字段 unknown_field -> 放行并清洗
    policy = service.update_update_policy("VPI-T2-D5", {
        "mode": "automatic",
        "enabled": True,
        "credentialRef": "test-alias",
        "matchRule": match_rule,
        "mapping": {"note": ["latestApproveLog", "unknown_field"]},
        "fieldAuthority": {"note": "automatic"},
    })
    assert policy["enabled"] is True
    assert policy["mapping"]["note"] == ["latestApproveLog"]

    # 验证底层 DB 持久化的是清洗后的列表
    raw = tmp_db.get_project_status_update_policy("VPI-T2-D5")
    assert json.loads(raw["binding"]["mapping_json"])["note"] == ["latestApproveLog"]

    # 2. 候选全部为未知字段 -> 阻断
    with pytest.raises(ProjectStatusPolicyError) as exc_info:
        service.update_update_policy("VPI-T2-D5", {
            "mode": "automatic",
            "enabled": True,
            "credentialRef": "test-alias",
            "matchRule": match_rule,
            "mapping": {"note": ["non_existent_1", "non_existent_2"]},
            "fieldAuthority": {"note": "automatic"},
        })
    assert "自动字段映射必须来自最新的脱敏字段报告" in exc_info.value.fields.get("enabled", "")


def test_data_model_status_in_match_rule_is_allowed(tmp_db: DatabaseManager) -> None:
    """VPI-T2-D5 支持在 matchRule 中配置 status 筛选。"""
    service = ProjectStatusUpdateService(tmp_db)
    match_rule = {
        "reportType": "data_model",
        "aggregate": True,
        "projectModel": "F610S",
        "status": "审批完成",
    }
    sig = compute_config_signature("tdc", match_rule)
    summary = json.dumps([{"externalKey": "agg:fp-1", "fields": {"latestApproveLog": "ok"}}])
    report = json.dumps({"fields": ["latestApproveLog"]})

    for _ in range(2):
        tmp_db.record_mapping_observation(
            "VPI-T2-D5", "tdc", "matched", None, "agg:fp-1", 1,
            summary, report, config_signature=sig,
        )

    policy = service.update_update_policy("VPI-T2-D5", {
        "mode": "automatic",
        "enabled": True,
        "credentialRef": "test-alias",
        "matchRule": match_rule,
        "mapping": {"note": ["latestApproveLog"]},
        "fieldAuthority": {"note": "automatic"},
    })
    assert policy["enabled"] is True
    assert policy["matchRule"]["status"] == "审批完成"


def test_data_model_document_no_and_incident_are_mutually_exclusive(tmp_db: DatabaseManager) -> None:
    """数模流水单号与实例号二选一（2026-10-09）：同填落库 fail-closed。"""
    service = ProjectStatusUpdateService(tmp_db)
    match_rule = {
        "reportType": "data_model",
        "aggregate": False,
        "incident": "51553863",
        "documentNo": "3D-00001018",
    }
    with pytest.raises(Exception) as excinfo:
        service.update_update_policy("VPI-T2-D5", {
            "mode": "automatic",
            "enabled": True,
            "credentialRef": "test-alias",
            "matchRule": match_rule,
            "mapping": {"note": ["latestApproveLog"]},
            "fieldAuthority": {"note": "automatic"},
        })
    fields = getattr(excinfo.value, "fields", None) or {}
    assert "二选一" in str(fields.get("matchRule") or excinfo.value)


def test_data_model_document_no_only_binding_is_accepted(tmp_db: DatabaseManager) -> None:
    """只填流水单号的绑定合法：单记录模式经既有 external_key 校验路径落库。"""
    service = ProjectStatusUpdateService(tmp_db)
    match_rule = {
        "reportType": "data_model",
        "aggregate": False,
        "documentNo": "3D-00001018",
    }
    sig = compute_config_signature("tdc", match_rule)
    summary = json.dumps([{"externalKey": "900001", "fields": {"latestApproveLog": "ok"}}])
    report = json.dumps({"fields": ["latestApproveLog"]})
    for _ in range(2):
        tmp_db.record_mapping_observation(
            "VPI-T2-D5", "tdc", "matched", "900001", "900001", 1,
            summary, report, config_signature=sig,
        )
    policy = service.update_update_policy("VPI-T2-D5", {
        "mode": "automatic",
        "enabled": True,
        "credentialRef": "test-alias",
        "externalKey": "900001",
        "matchRule": match_rule,
        "mapping": {"note": ["latestApproveLog"]},
        "fieldAuthority": {"note": "automatic"},
    })
    assert policy["enabled"] is True
    assert policy["matchRule"]["documentNo"] == "3D-00001018"


def test_assert_sync_ready_is_strictly_read_only(tmp_db: DatabaseManager) -> None:
    """assert_sync_ready 必须是纯只读校验，严禁在校验方法内部静默修改 SQLite 绑定。"""
    service = ProjectStatusUpdateService(tmp_db)
    _record_two_observations_for_d5(tmp_db)

    service.update_update_policy("VPI-T2-D5", {
        "mode": "automatic",
        "enabled": True,
        "credentialRef": "test-alias",
        "externalKey": "FM-1",
        "matchRule": {"reportType": "data_model", "incident": "FM-1"},
        "mapping": {"owner": "currentApprover"},
        "fieldAuthority": {"owner": "automatic"},
    })

    binding_before = tmp_db.get_sync_binding_by_deliverable("VPI-T2-D5")
    assert binding_before is not None

    ready_binding = service.assert_sync_ready("VPI-T2-D5")
    assert ready_binding["id"] == binding_before["id"]

    binding_after = tmp_db.get_sync_binding_by_deliverable("VPI-T2-D5")
    assert binding_after == binding_before
