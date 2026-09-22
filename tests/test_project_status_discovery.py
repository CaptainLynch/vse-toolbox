# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import pytest

from core.db_manager import DatabaseManager
from services.aras_crawler import DEFAULT_EWO_SELECT_FIELDS
from services.project_status_discovery import MappingDiscoveryService
from services.project_status_records import (
    aggregate_fingerprint,
    compute_config_signature,
)
from services.project_status_deliverable_analysis import EWO_DEFAULT_RSP_DEPARTMENT_EXPRESSION


def test_two_stable_observations_reach_ready_without_status_guess(tmp_path):
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)
    rows = [{"incident": "FLOW-1", "approvalStatus": "待审批", "password": "must-not-store"}]
    first = service.observe("VPI-T2-D5", "tdc", rows)
    second = service.observe("VPI-T2-D5", "tdc", rows)
    assert first["stability"]["confirmed"] == 1
    assert second["stability"] == {"confirmed": 2, "required": 2, "ready": True}
    assert second["fieldReport"]["suggestedStatusMapping"] == []
    serialized = str(service.history("VPI-T2-D5"))
    assert "must-not-store" not in serialized


def test_stability_persists_across_fingerprint_and_field_value_differences(tmp_path):
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)
    rows_v1 = [
        {"incident": "FLOW-1", "currentApprover": "Alice", "remark": "Initial note"}
    ]
    rows_v2 = [
        {
            "incident": "FLOW-1",
            "currentApprover": "Bob",
            "remark": "Updated note",
            "extraField": "value",
        }
    ]

    first = service.observe("VPI-T2-D5", "tdc", rows_v1)
    second = service.observe("VPI-T2-D5", "tdc", rows_v2)
    assert first["stability"]["confirmed"] == 1
    assert second["stability"]["confirmed"] == 2
    assert second["stability"]["ready"] is True
    # Verify candidate fingerprints are indeed different while stability is confirmed
    obs = db.list_mapping_observations("VPI-T2-D5", 2)
    assert len(obs) == 2
    assert obs[0]["candidate_fingerprint"] != obs[1]["candidate_fingerprint"]
    assert obs[0]["external_key"] == obs[1]["external_key"] == "FLOW-1"
    assert obs[0]["source_type"] == obs[1]["source_type"] == "tdc"
    assert db.mapping_stability_count("VPI-T2-D5") == 2


def test_aras_ewo_row_keyed_by_no_field(tmp_path):
    """ARAS EWO rows carry their number in `_no`; discovery must key on it."""
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)
    ewo_row = {
        "_no": "EWO-049039",
        "_subject": "车门密封条更改",
        "_rsp_name": "张三",
        "_required_date": "2026-09-15",
        "_change_description": "初始版本",
    }
    first = service.observe("VPI-T2-D3", "aras", [ewo_row])
    assert first["state"] == "matched"
    assert first["externalKey"] == "EWO-049039"
    assert first["candidateCount"] == 1
    second = service.observe(
        "VPI-T2-D3", "aras", [dict(ewo_row, _rsp_name="李四")], selected_external_key="EWO-049039"
    )
    assert second["stability"] == {"confirmed": 2, "required": 2, "ready": True}
    # The `_no` field must surface in the sanitized field report for confirmation flows.
    assert "_no" in second["fieldReport"]["fields"]


def test_aras_ewo_wide_row_keeps_identity_and_mapped_fields(tmp_path):
    """线上 EWO 行约 70 列且 `_no` 按字母序排在证据截断点之后，不能被丢弃。"""
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)
    wide_row = {field: f"值-{field}" for field in DEFAULT_EWO_SELECT_FIELDS}
    wide_row["id"] = "AAAABBBBCCCCDDDDEEEEFFFF00001111"
    wide_row["id__keyed_name"] = "EWO-049039"
    wide_row["_rsp__keyed_name"] = "EWO-049039"
    wide_row["_no"] = "EWO-049039"
    wide_row["_rsp_name"] = "张三"
    wide_row["_required_date"] = "2026-09-15"
    first = service.observe("VPI-T2-D3", "aras", [wide_row])
    # ARAS 返回的内部 `id`（GUID）不能压过业务单号 `_no`。
    assert first["state"] == "matched"
    assert first["externalKey"] == "EWO-049039"
    assert first["candidateCount"] == 1
    assert first["candidates"][0]["fields"]["_rsp_name"] == "张三"
    report_fields = set(first["fieldReport"]["fields"])
    # 启用自动策略时，映射字段必须出现在最新脱敏字段报告中。
    assert set(DEFAULT_EWO_SELECT_FIELDS).issubset(report_fields)


def test_zero_ambiguous_and_key_change_reset_stability(tmp_path):
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)
    assert service.observe("VPI-T2-D5", "tdc", [{"incident": "A"}])["state"] == "matched"
    ready = service.observe("VPI-T2-D5", "tdc", [{"incident": "A"}])
    assert ready["stability"] == {"confirmed": 2, "required": 2, "ready": True}
    assert service.observe("VPI-T2-D5", "tdc", [])["state"] == "not_found"
    ambiguous = service.observe(
        "VPI-T2-D5", "tdc", [{"incident": "A"}, {"incident": "B"}]
    )
    assert ambiguous["state"] == "ambiguous"
    assert ambiguous["stability"] == {"confirmed": 0, "required": 2, "ready": False}
    assert service.observe("VPI-T2-D5", "tdc", [{"incident": "A"}])["state"] == "matched"
    assert service.observe("VPI-T2-D5", "tdc", [{"incident": "A"}])["stability"]["confirmed"] == 2
    # Changing source_type resets stability
    source_changed = service.observe("VPI-T2-D5", "aras", [{"item_number": "A"}])
    assert source_changed["state"] == "matched"
    assert source_changed["stability"]["confirmed"] == 0
    assert source_changed["stability"]["ready"] is False
    changed = service.observe("VPI-T2-D5", "aras", [{"item_number": "B"}])
    assert changed["state"] == "key_changed"
    assert changed["stability"]["confirmed"] == 0


def test_selected_key_removes_multirow_ambiguity(tmp_path):
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    result = MappingDiscoveryService(db).observe(
        "VPI-T2-D2", "tdc", [{"processNo": "A"}, {"processNo": "B"}], "B"
    )
    assert result["state"] == "matched"
    assert result["externalKey"] == "B"
    assert len(result["candidates"]) == 1


def test_candidate_preview_ready_with_differences_and_unchanged_values(tmp_path):
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)

    # Initial deliverable row in DB (VPI-T2-D5 seeded values)
    # Configure update policy
    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D5",
        mode="automatic",
        enabled=True,
        external_key="FLOW-1",
        match_rule_json='{"incident":"FLOW-1","reportType":"DataModelReport"}',
        mapping_json='{"owner":"currentApprover","plannedDate":"targetDate","note":"summaryNote"}',
        field_authority={"owner": "automatic", "planned_date": "automatic", "remark": "automatic"},
    )

    # Deliverable row in DB has: owner="赵岩", planned_date="2026-08-08", remark="待同步"
    candidate_row = {
        "incident": "FLOW-1",
        "currentApprover": "李四",  # changed
        "targetDate": "2026-08-08",  # unchanged
        "summaryNote": "更新备注",  # changed
        "password": "secret-must-not-leak",
    }
    service.observe("VPI-T2-D5", "tdc", [candidate_row])
    service.observe("VPI-T2-D5", "tdc", [candidate_row])

    preview = service.candidate_preview("VPI-T2-D5")
    assert preview["deliverableId"] == "VPI-T2-D5"
    assert preview["state"] == "matched"
    assert preview["reason"] is None
    assert preview["externalKey"] == "FLOW-1"
    assert preview["stability"] == {"confirmed": 2, "required": 2, "ready": True}

    diffs = preview["differences"]
    assert len(diffs) == 3

    owner_diff = next(d for d in diffs if d["targetField"] == "owner")
    assert owner_diff["sourceField"] == "currentApprover"
    assert owner_diff["currentValue"] == "赵岩"
    assert owner_diff["candidateValue"] == "李四"
    assert owner_diff["changed"] is True

    date_diff = next(d for d in diffs if d["targetField"] == "plannedDate")
    assert date_diff["sourceField"] == "targetDate"
    assert date_diff["currentValue"] == "2026-08-08"
    assert date_diff["candidateValue"] == "2026-08-08"
    assert date_diff["changed"] is False

    note_diff = next(d for d in diffs if d["targetField"] == "note")
    assert note_diff["sourceField"] == "summaryNote"
    assert note_diff["currentValue"] == "待同步"
    assert note_diff["candidateValue"] == "更新备注"
    assert note_diff["changed"] is True

    # Ensure no sensitive keys / candidate fingerprints / raw responses leaked
    serialized = str(preview)
    assert "password" not in serialized
    assert "secret-must-not-leak" not in serialized
    assert "candidate_fingerprint" not in serialized
    assert "credential_ref" not in serialized


def test_candidate_preview_no_evidence(tmp_path):
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)

    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D5",
        mode="automatic",
        enabled=True,
        external_key="FLOW-1",
        match_rule_json='{"incident":"FLOW-1"}',
        mapping_json='{"owner":"currentApprover"}',
        field_authority={"owner": "automatic"},
    )

    preview = service.candidate_preview("VPI-T2-D5")
    assert preview["deliverableId"] == "VPI-T2-D5"
    assert preview["state"] == "not_found"
    assert preview["reason"] == "no_observation"
    assert preview["stability"] == {"confirmed": 0, "required": 2, "ready": False}
    assert preview["differences"] == []


@pytest.mark.parametrize(
    "malformed_rule",
    [
        "not-json",
        "[]",
        '{"reportType":"data_model","incident":"FLOW-1","aggregate":"true"}',
    ],
)
def test_candidate_preview_fail_closed_for_malformed_rule(tmp_path, malformed_rule):
    """畸形/错误顶层/错误字段类型的规则不能借旧证据宣称 ready。"""
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)
    valid_rule = {"reportType": "data_model", "incident": "FLOW-1"}
    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D5",
        mode="automatic",
        enabled=True,
        external_key="FLOW-1",
        match_rule_json=json.dumps(valid_rule),
        mapping_json='{"owner":"currentApprover"}',
        field_authority={"owner": "automatic"},
    )
    row = {"incident": "FLOW-1", "currentApprover": "Alice"}
    service.observe("VPI-T2-D5", "tdc", [row], match_rule=valid_rule)
    service.observe("VPI-T2-D5", "tdc", [row], match_rule=valid_rule)

    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET match_rule_json=? WHERE deliverable_id=?",
            (malformed_rule, "VPI-T2-D5"),
        )

    preview = service.candidate_preview("VPI-T2-D5")
    assert preview["reason"] == "invalid_configuration"
    assert preview["stability"]["ready"] is False
    assert preview["differences"] == []


def test_candidate_preview_ambiguous_and_latest_reset(tmp_path):
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)

    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D5",
        mode="automatic",
        enabled=True,
        external_key="FLOW-1",
        match_rule_json='{"incident":"FLOW-1"}',
        mapping_json='{"owner":"currentApprover"}',
        field_authority={"owner": "automatic"},
    )

    # 2 matched observations -> stable
    service.observe("VPI-T2-D5", "tdc", [{"incident": "FLOW-1", "currentApprover": "Alice"}])
    service.observe("VPI-T2-D5", "tdc", [{"incident": "FLOW-1", "currentApprover": "Alice"}])
    ready_preview = service.candidate_preview("VPI-T2-D5")
    assert ready_preview["stability"]["ready"] is True

    # 3rd observation is ambiguous -> resets stability and readiness
    service.observe("VPI-T2-D5", "tdc", [
        {"incident": "FLOW-1", "currentApprover": "Alice"},
        {"incident": "FLOW-1", "currentApprover": "Bob"},
    ])
    preview = service.candidate_preview("VPI-T2-D5")
    assert preview["stability"]["ready"] is False
    assert preview["reason"] == "observation_not_matched"
    assert preview["differences"] == []


def test_candidate_preview_source_and_key_mismatch(tmp_path):
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)

    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D5",
        mode="automatic",
        enabled=True,
        external_key="FLOW-1",
        match_rule_json='{"incident":"FLOW-1"}',
        mapping_json='{"owner":"currentApprover"}',
        field_authority={"owner": "automatic"},
    )

    # Observation has key FLOW-2 instead of FLOW-1
    service.observe("VPI-T2-D5", "tdc", [{"incident": "FLOW-2", "currentApprover": "Alice"}])
    service.observe("VPI-T2-D5", "tdc", [{"incident": "FLOW-2", "currentApprover": "Alice"}])
    preview_key_mismatch = service.candidate_preview("VPI-T2-D5")
    assert preview_key_mismatch["stability"]["ready"] is False
    assert preview_key_mismatch["reason"] == "key_mismatch"
    assert preview_key_mismatch["differences"] == []

    # Deliverable VPI-T2-D2 has source tdc in binding, observe with aras
    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D2",
        mode="automatic",
        enabled=True,
        external_key="EWO-100",
        match_rule_json='{"ewoNo":"EWO-100"}',
        mapping_json='{"owner":"currentApprover"}',
        field_authority={"owner": "automatic"},
    )
    service.observe("VPI-T2-D2", "aras", [{"item_number": "EWO-100", "currentApprover": "Alice"}])
    service.observe("VPI-T2-D2", "aras", [{"item_number": "EWO-100", "currentApprover": "Alice"}])
    preview_source_mismatch = service.candidate_preview("VPI-T2-D2")
    assert preview_source_mismatch["stability"]["ready"] is False
    assert preview_source_mismatch["reason"] == "source_mismatch"
    assert preview_source_mismatch["differences"] == []


def test_candidate_preview_unapproved_and_manual_field_exclusion(tmp_path):
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)

    # owner is automatic, note is manual
    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D5",
        mode="automatic",
        enabled=True,
        external_key="FLOW-1",
        match_rule_json='{"incident":"FLOW-1"}',
        mapping_json='{"owner":"currentApprover","note":"comment"}',
        field_authority={"owner": "automatic", "remark": "manual"},
    )

    service.observe("VPI-T2-D5", "tdc", [{"incident": "FLOW-1", "currentApprover": "Alice", "comment": "Note"}])
    service.observe("VPI-T2-D5", "tdc", [{"incident": "FLOW-1", "currentApprover": "Alice", "comment": "Note"}])

    preview = service.candidate_preview("VPI-T2-D5")
    assert preview["stability"]["ready"] is True
    assert len(preview["differences"]) == 1
    assert preview["differences"][0]["targetField"] == "owner"

    # A manual field is excluded before its source mapping is validated. It
    # must not block an otherwise approved automatic preview.
    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D5",
        mode="automatic",
        enabled=True,
        external_key="FLOW-1",
        match_rule_json='{"incident":"FLOW-1"}',
        mapping_json='{"owner":"currentApprover","note":"password"}',
        field_authority={"owner": "automatic", "remark": "manual"},
    )
    preview_with_sensitive_manual = service.candidate_preview("VPI-T2-D5")
    assert preview_with_sensitive_manual["stability"]["ready"] is True
    assert [
        item["targetField"] for item in preview_with_sensitive_manual["differences"]
    ] == ["owner"]
    assert "password" not in str(preview_with_sensitive_manual)

    # If all mapped fields are manual -> unapproved_mapping
    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D5",
        mode="automatic",
        enabled=True,
        external_key="FLOW-1",
        match_rule_json='{"incident":"FLOW-1"}',
        mapping_json='{"owner":"currentApprover"}',
        field_authority={"owner": "manual"},
    )
    preview_all_manual = service.candidate_preview("VPI-T2-D5")
    assert preview_all_manual["stability"]["ready"] is False
    assert preview_all_manual["reason"] == "unapproved_mapping"
    assert preview_all_manual["differences"] == []

    # If mapping is empty dict -> unapproved_mapping
    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D5",
        mode="automatic",
        enabled=True,
        external_key="FLOW-1",
        match_rule_json='{"incident":"FLOW-1"}',
        mapping_json='{}',
        field_authority={"owner": "automatic"},
    )
    preview_empty = service.candidate_preview("VPI-T2-D5")
    assert preview_empty["stability"]["ready"] is False
    assert preview_empty["reason"] == "unapproved_mapping"
    assert preview_empty["differences"] == []


def test_candidate_preview_forbidden_target_exclusion(tmp_path):
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)

    # Mapping contains forbidden fields: status, actualDate, progress
    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D5",
        mode="automatic",
        enabled=True,
        external_key="FLOW-1",
        match_rule_json='{"incident":"FLOW-1"}',
        mapping_json='{"owner":"approver","status":"st","actualDate":"ad","progress":"pct"}',
        field_authority={"owner": "automatic", "status": "automatic", "actual_date": "automatic"},
    )

    service.observe("VPI-T2-D5", "tdc", [{
        "incident": "FLOW-1", "approver": "Alice", "st": "已完成", "ad": "2026-03-01", "pct": "100"
    }])
    service.observe("VPI-T2-D5", "tdc", [{
        "incident": "FLOW-1", "approver": "Alice", "st": "已完成", "ad": "2026-03-01", "pct": "100"
    }])

    preview = service.candidate_preview("VPI-T2-D5")
    assert preview["stability"]["ready"] is True
    # Only owner allowed in differences
    target_fields = [d["targetField"] for d in preview["differences"]]
    assert target_fields == ["owner"]
    assert "status" not in target_fields
    assert "actualDate" not in target_fields
    assert "progress" not in target_fields


def test_candidate_preview_disabled_policy(tmp_path):
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)

    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D5",
        mode="automatic",
        enabled=False,  # disabled
        external_key="FLOW-1",
        match_rule_json='{"incident":"FLOW-1"}',
        mapping_json='{"owner":"currentApprover"}',
        field_authority={"owner": "automatic"},
    )

    service.observe("VPI-T2-D5", "tdc", [{"incident": "FLOW-1", "currentApprover": "Alice"}])
    service.observe("VPI-T2-D5", "tdc", [{"incident": "FLOW-1", "currentApprover": "Alice"}])

    preview = service.candidate_preview("VPI-T2-D5")
    assert preview["stability"]["ready"] is False
    assert preview["reason"] == "policy_disabled"
    assert preview["differences"] == []


def test_candidate_preview_scalar_limit_and_sanitization(tmp_path):
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)

    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D5",
        mode="automatic",
        enabled=True,
        external_key="FLOW-1",
        match_rule_json='{"incident":"FLOW-1"}',
        mapping_json='{"owner":"approver","note":"longNote"}',
        field_authority={"owner": "automatic", "remark": "automatic"},
    )

    long_text = "A" * 300
    sensitive_approver = "Alice Bearer eyJhbGciOiJIUzI1NiJ9.test"
    service.observe("VPI-T2-D5", "tdc", [{
        "incident": "FLOW-1",
        "approver": sensitive_approver,
        "longNote": long_text,
    }])
    service.observe("VPI-T2-D5", "tdc", [{
        "incident": "FLOW-1",
        "approver": sensitive_approver,
        "longNote": long_text,
    }])

    preview = service.candidate_preview("VPI-T2-D5")
    assert preview["stability"]["ready"] is True
    note_diff = next(d for d in preview["differences"] if d["targetField"] == "note")
    assert len(note_diff["candidateValue"]) <= 200
    owner_diff = next(d for d in preview["differences"] if d["targetField"] == "owner")
    assert "[redacted]" in owner_diff["candidateValue"]


def test_candidate_preview_unapproved_source_field_validation(tmp_path):
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)

    # 1. Automatic mapping references a field absent from the latest field report
    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D5",
        mode="automatic",
        enabled=True,
        external_key="FLOW-1",
        match_rule_json='{"incident":"FLOW-1"}',
        mapping_json='{"owner":"nonExistentField"}',
        field_authority={"owner": "automatic"},
    )
    service.observe("VPI-T2-D5", "tdc", [{"incident": "FLOW-1", "currentApprover": "Alice"}])
    service.observe("VPI-T2-D5", "tdc", [{"incident": "FLOW-1", "currentApprover": "Alice"}])
    preview = service.candidate_preview("VPI-T2-D5")
    assert preview["stability"]["ready"] is False
    assert preview["reason"] == "unapproved_mapping"
    assert preview["differences"] == []
    assert "nonExistentField" not in str(preview)

    # 2. Sensitive field such as password or credential_ref
    for sensitive_name in ["password", "credential_ref", "Bearer eyJhbGciOiJIUzI1NiJ9.test", "sessionToken"]:
        db.set_project_status_update_policy(
            deliverable_id="VPI-T2-D5",
            mode="automatic",
            enabled=True,
            external_key="FLOW-1",
            match_rule_json='{"incident":"FLOW-1"}',
            mapping_json=f'{{"owner":"{sensitive_name}"}}',
            field_authority={"owner": "automatic"},
        )
        preview_sensitive = service.candidate_preview("VPI-T2-D5")
        assert preview_sensitive["stability"]["ready"] is False
        assert preview_sensitive["reason"] == "unapproved_mapping"
        assert preview_sensitive["differences"] == []
        assert sensitive_name not in str(preview_sensitive)

    # 3. Source-field name longer than 200 characters
    long_source_field = "custom_field_" + ("x" * 250)
    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D5",
        mode="automatic",
        enabled=True,
        external_key="FLOW-1",
        match_rule_json='{"incident":"FLOW-1"}',
        mapping_json=f'{{"owner":"{long_source_field}"}}',
        field_authority={"owner": "automatic"},
    )
    preview_long = service.candidate_preview("VPI-T2-D5")
    assert preview_long["stability"]["ready"] is False
    assert preview_long["reason"] == "unapproved_mapping"
    assert preview_long["differences"] == []
    assert long_source_field not in str(preview_long)


def test_candidate_preview_nonexistent_deliverable(tmp_path):
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)

    preview = service.candidate_preview("NONEXISTENT-DELIV")
    assert preview["deliverableId"] == "NONEXISTENT-DELIV"
    assert preview["state"] == "not_found"
    assert preview["reason"] == "deliverable_not_found"
    assert preview["stability"]["ready"] is False
    assert preview["differences"] == []


def test_observe_aggregate_mode_fingerprint_semantics(tmp_db: DatabaseManager) -> None:
    """聚合观测：多记录 matched（无单记录筛选/歧义）；指纹=单号集合哈希；
    无单号行不计入（与连接器口径一致）。"""
    service = MappingDiscoveryService(tmp_db)
    rows_a = [
        {"incident": "F610S-3D-0001", "name": "组件A"},
        {"incident": "F610S-3D-0002", "name": "组件B"},
        {"approval_status": "审批中"},  # 无单号行：不计入
    ]
    result_a = service.observe("VPI-T2-D5", "tdc", rows_a, aggregate=True)
    assert result_a["state"] == "matched"
    assert result_a["externalKey"] is None
    assert result_a["candidateCount"] == 2
    # 指纹=全部记录单号集合的确定性哈希（共享算法）；无单号行不计入
    # （candidateCount 为 2 佐证）。
    stored = tmp_db.list_mapping_observations("VPI-T2-D5", 1)[0]
    expected_fp = aggregate_fingerprint([
        ("F610S-3D-0001", {"incident": "F610S-3D-0001", "name": "组件A"}),
        ("F610S-3D-0002", {"incident": "F610S-3D-0002", "name": "组件B"}),
    ])
    assert stored["candidate_fingerprint"] == expected_fp

    # 集合变化（新增一条）→ 指纹变化
    result_b = service.observe("VPI-T2-D5", "tdc", [
        {"incident": "F610S-3D-0001", "name": "组件A"},
        {"incident": "F610S-3D-0002", "name": "组件B"},
        {"incident": "F610S-3D-0003", "name": "组件C"},
    ], aggregate=True)
    assert result_b["state"] == "matched"
    stored_b = tmp_db.list_mapping_observations("VPI-T2-D5", 1)[0]
    assert stored_b["candidate_fingerprint"] != expected_fp

    # 全部无单号 → not_found
    result_c = service.observe("VPI-T2-D5", "tdc", [{"name": "无单号"}], aggregate=True)
    assert result_c["state"] == "not_found"


def test_candidate_preview_with_note_list_mapping(tmp_path):
    """candidate_preview 支持 note 来源字段为列表并用 ｜ 拼接。"""
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)

    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D5",
        mode="automatic",
        enabled=True,
        external_key="FLOW-1",
        match_rule_json='{"incident":"FLOW-1","reportType":"DataModelReport"}',
        mapping_json='{"owner":"currentApprover","note":["node","status"]}',
        field_authority={"owner": "automatic", "remark": "automatic"},
    )

    candidate_row = {
        "incident": "FLOW-1",
        "currentApprover": "张三",
        "node": "节点A",
        "status": "审批中",
    }
    service.observe("VPI-T2-D5", "tdc", [candidate_row])
    service.observe("VPI-T2-D5", "tdc", [candidate_row])

    preview = service.candidate_preview("VPI-T2-D5")
    assert preview["state"] == "matched"
    assert preview["reason"] is None
    assert preview["stability"]["ready"] is True

    diffs = preview["differences"]
    note_diff = next(d for d in diffs if d["targetField"] == "note")
    assert note_diff["sourceField"] == ["node", "status"]
    assert note_diff["candidateValue"] == "节点A｜审批中"


def test_candidate_preview_aggregate_multiple_records_with_note_list(tmp_path):
    """聚合模式下多记录 candidate_preview：owner 不写，note 逐单号拼接。"""
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)

    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D5",
        mode="automatic",
        enabled=True,
        external_key=None,
        match_rule_json='{"reportType":"data_model","aggregate":true,"carTypeProjectId":"F610S"}',
        mapping_json='{"owner":"currentApprover","note":["node","status"]}',
        field_authority={"owner": "automatic", "remark": "automatic"},
    )

    rows = [
        {"incident": "F610S-001", "currentApprover": "张三", "node": "节点A", "status": "审批中"},
        {"incident": "F610S-002", "currentApprover": "李四", "node": "节点B", "status": "待审核"},
    ]
    service.observe("VPI-T2-D5", "tdc", rows, aggregate=True)
    service.observe("VPI-T2-D5", "tdc", rows, aggregate=True)

    preview = service.candidate_preview("VPI-T2-D5")
    assert preview["state"] == "matched"
    assert preview["reason"] is None
    assert preview["stability"]["ready"] is True

    diffs = preview["differences"]
    owner_diff = next(d for d in diffs if d["targetField"] == "owner")
    assert owner_diff["candidateValue"] == owner_diff["currentValue"]
    assert owner_diff["changed"] is False

    note_diff = next(d for d in diffs if d["targetField"] == "note")
    assert note_diff["sourceField"] == ["node", "status"]
    assert note_diff["candidateValue"] == "F610S-001：节点A｜审批中；F610S-002：节点B｜待审核"


def test_candidate_preview_aggregate_multiple_records_with_single_string_note(tmp_path):
    """聚合多记录模式下 note 为单字符串映射：依然按单号聚合每条记录。"""
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)

    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D5",
        mode="automatic",
        enabled=True,
        external_key=None,
        match_rule_json='{"reportType":"data_model","aggregate":true,"carTypeProjectId":"F610S"}',
        mapping_json='{"note":"summaryNote"}',
        field_authority={"remark": "automatic"},
    )

    rows = [
        {"incident": "F610S-001", "summaryNote": "阶段卡点A"},
        {"incident": "F610S-002", "summaryNote": "阶段卡点B"},
    ]
    service.observe("VPI-T2-D5", "tdc", rows, aggregate=True)
    service.observe("VPI-T2-D5", "tdc", rows, aggregate=True)

    preview = service.candidate_preview("VPI-T2-D5")
    assert preview["state"] == "matched"
    diffs = preview["differences"]
    note_diff = next(d for d in diffs if d["targetField"] == "note")
    assert note_diff["candidateValue"] == "F610S-001：阶段卡点A；F610S-002：阶段卡点B"


def test_observe_aggregate_mode_sanitization(tmp_db: DatabaseManager):
    """聚合模式下敏感字段绝不进入 candidate_summary_json 落库。"""
    service = MappingDiscoveryService(tmp_db)
    rows = [
        {"incident": "F610S-001", "token": "secret-token", "password": "pwd", "summaryNote": "正常备注"},
    ]
    service.observe("VPI-T2-D5", "tdc", rows, aggregate=True)
    stored = tmp_db.list_mapping_observations("VPI-T2-D5", 1)[0]
    candidate_summary = stored["candidate_summary_json"]
    assert "secret-token" not in candidate_summary
    assert "pwd" not in candidate_summary
    assert "正常备注" in candidate_summary


def test_rebind_invalidates_old_observations_for_candidate_preview(tmp_path):
    """【P1-4 严密回归】换绑后旧观测签名失配，候选预览立即失效（ready=False），新观测后恢复。"""
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)

    # 1. 初始绑定车型 A
    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D5",
        mode="automatic",
        enabled=True,
        external_key=None,
        match_rule_json='{"reportType":"data_model","aggregate":true,"carTypeProjectId":"CAR-A"}',
        mapping_json='{"note":"summaryNote"}',
        field_authority={"remark": "automatic"},
    )
    rows_a = [{"incident": "A-01", "summaryNote": "A备注"}]
    service.observe("VPI-T2-D5", "tdc", rows_a, aggregate=True)
    service.observe("VPI-T2-D5", "tdc", rows_a, aggregate=True)

    # 车型 A 下已具备 2 次稳定观测证据
    preview_a = service.candidate_preview("VPI-T2-D5")
    assert preview_a["state"] == "matched"
    assert preview_a["stability"]["ready"] is True

    # 2. 换绑为车型 B（不重新观测）
    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D5",
        mode="automatic",
        enabled=True,
        external_key=None,
        match_rule_json='{"reportType":"data_model","aggregate":true,"carTypeProjectId":"CAR-B"}',
        mapping_json='{"note":"summaryNote"}',
        field_authority={"remark": "automatic"},
    )

    # 验证：旧 A 证据对新 B 配置直接失效，禁止宣称 ready
    preview_b_stale = service.candidate_preview("VPI-T2-D5")
    assert preview_b_stale["state"] == "not_found"
    assert preview_b_stale["reason"] == "no_observation"
    assert preview_b_stale["stability"]["ready"] is False
    assert preview_b_stale["stability"]["confirmed"] == 0

    # 3. 在新车型 B 下重新观测 2 次
    rows_b = [{"incident": "B-01", "summaryNote": "B备注"}]
    service.observe("VPI-T2-D5", "tdc", rows_b, aggregate=True)
    service.observe("VPI-T2-D5", "tdc", rows_b, aggregate=True)

    # 验证：新配置证据就绪
    preview_b_fresh = service.candidate_preview("VPI-T2-D5")
    assert preview_b_fresh["state"] == "matched"
    assert preview_b_fresh["stability"]["ready"] is True
    assert preview_b_fresh["stability"]["confirmed"] == 2


def test_candidate_preview_with_six_records_aligns_with_actual_connector_aggregate(tmp_path):
    """【P2-5 严密回归】6条记录时预览包含全部6条，与连接器 _snapshot 实际拟写入聚合值 100% 对齐。"""
    from services.project_status_connectors import _snapshot
    from services.project_status_sync_runner import SyncBindingContext
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)

    rule = {"reportType": "data_model", "aggregate": True, "carTypeProjectId": "F610S"}
    mapping = {"owner": "who", "note": "note"}

    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D5",
        mode="automatic",
        enabled=True,
        external_key=None,
        match_rule_json=json.dumps(rule),
        mapping_json=json.dumps(mapping),
        field_authority={"owner": "automatic", "remark": "automatic"},
    )

    rows = [{"incident": str(i), "who": f"owner-{i}", "note": f"note-{i}"} for i in range(6)]
    service.observe("VPI-T2-D5", "tdc", rows, aggregate=True)
    service.observe("VPI-T2-D5", "tdc", rows, aggregate=True)

    preview = service.candidate_preview("VPI-T2-D5")
    assert preview["state"] == "matched"
    preview_note = next(d["candidateValue"] for d in preview["differences"] if d["targetField"] == "note")

    ctx = SyncBindingContext(
        binding_id=1, deliverable_id="VPI-T2-D5", phase_id="VPI-T2",
        source_type="tdc", external_key=None, match_rule=rule,
        mapping=mapping, cursor={}, expected_deliverable_updated_at="v1",
        run_id=1, credential_ref="domain",
    )
    actual_snap = _snapshot(ctx, rows, [])
    actual_note = actual_snap.candidates[0].field_values["note"]

    # 彻底杜绝漏第 6 条的问题：两者严格相等
    assert preview_note == actual_note
    assert "5：note-5" in preview_note


def test_fingerprint_parity_long_identity_and_large_record_set(tmp_path):
    """【P2-6 严密回归】201字符单号与1001条记录在 discovery 与 connector 两端指纹严格一致。"""
    from services.project_status_connectors import _snapshot
    from services.project_status_sync_runner import SyncBindingContext
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)

    rule = {"reportType": "data_model", "aggregate": True}
    mapping = {"note": "n"}

    # 1. 201 字符超长单号
    long_rows = [{"incident": "x" * 201, "n": "note-1"}]
    service.observe("VPI-T2-D5", "tdc", long_rows, aggregate=True)
    disc_fp_1 = db.list_mapping_observations("VPI-T2-D5", 1)[0]["candidate_fingerprint"]

    ctx1 = SyncBindingContext(
        binding_id=1, deliverable_id="VPI-T2-D5", phase_id="VPI-T2",
        source_type="tdc", external_key=None, match_rule=rule,
        mapping=mapping, cursor={}, expected_deliverable_updated_at="v1",
        run_id=1, credential_ref="domain",
    )
    conn_fp_1 = _snapshot(ctx1, long_rows, []).candidates[0].external_key
    assert disc_fp_1 == conn_fp_1

    # 2. 1001 条记录
    large_rows = [{"incident": f"NO-{i}", "n": f"v-{i}"} for i in range(1001)]
    service.observe("VPI-T2-D5", "tdc", large_rows, aggregate=True)
    disc_fp_1001 = db.list_mapping_observations("VPI-T2-D5", 1)[0]["candidate_fingerprint"]

    ctx2 = SyncBindingContext(
        binding_id=1, deliverable_id="VPI-T2-D5", phase_id="VPI-T2",
        source_type="tdc", external_key=None, match_rule=rule,
        mapping=mapping, cursor={}, expected_deliverable_updated_at="v1",
        run_id=1, credential_ref="domain",
    )
    conn_fp_1001 = _snapshot(ctx2, large_rows, []).candidates[0].external_key
    assert disc_fp_1001 == conn_fp_1001


def test_config_signature_uses_explicit_query_keys_not_fuzzy_forbidden_regex():
    """A legitimate subjectKeyword filter must affect evidence identity."""
    base = {"source_type": "aras", "rule": {"reportType": "ewo", "aggregate": True}}
    first = dict(base["rule"], subjectKeyword="door")
    second = dict(base["rule"], subjectKeyword="hood")
    assert compute_config_signature("aras", first) != compute_config_signature("aras", second)
    assert compute_config_signature("aras", {"subjectKeyword": "door", "reportType": "ewo"}) == compute_config_signature(
        "aras", {"reportType": "ewo", "subjectKeyword": "door"}
    )
    assert compute_config_signature(
        "aras", dict(first, credentialRef="alias-a", password="not-a-query")
    ) == compute_config_signature("aras", first)
    assert compute_config_signature(
        "aras", {"reportType": "ewo", "aggregate": True}
    ) == compute_config_signature(
        "aras",
        {
            "reportType": "ewo",
            "aggregate": True,
            "rspDepartment": EWO_DEFAULT_RSP_DEPARTMENT_EXPRESSION,
        },
    )


def test_history_derives_current_config_signature_for_aggregate_observations(tmp_path):
    """History readiness must use the same signed evidence rule as preview/enable."""
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    rule = {"reportType": "data_model", "aggregate": True, "projectModel": "A"}
    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D5",
        mode="automatic",
        enabled=False,
        external_key=None,
        match_rule_json=json.dumps(rule),
        mapping_json=json.dumps({"note": "summaryNote"}),
        field_authority={"remark": "automatic"},
    )
    service = MappingDiscoveryService(db)
    rows = [{"incident": "A-1", "summaryNote": "blocked"}]
    service.observe("VPI-T2-D5", "tdc", rows, aggregate=True)
    service.observe("VPI-T2-D5", "tdc", rows, aggregate=True)
    assert service.history("VPI-T2-D5")["stability"]["confirmed"] == 2


def test_unsigned_or_mismatched_observation_cannot_authorize_current_config(tmp_path):
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    rule = {"reportType": "data_model", "aggregate": True, "projectModel": "A"}
    signature = compute_config_signature("tdc", rule)
    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D5",
        mode="automatic",
        enabled=True,
        external_key=None,
        match_rule_json=json.dumps(rule),
        mapping_json=json.dumps({"note": "summaryNote"}),
        field_authority={"remark": "automatic"},
    )
    summary = json.dumps([{"externalKey": "A-1", "fields": {"summaryNote": "x"}}])
    report = json.dumps({"fields": ["incident", "summaryNote"]})
    for value in (None, "", "sig:wrong"):
        db.record_mapping_observation(
            "VPI-T2-D5", "tdc", "matched", None, "agg:stable", 1,
            summary, report, config_signature=value,
        )
    assert db.mapping_stability_count("VPI-T2-D5", expected_signature=signature) == 0


def test_aggregate_preview_recomputes_full_candidate_after_mapping_change(tmp_path):
    """Mapping changes use the bounded full candidate cache, never five display rows."""
    from services.project_status_connectors import _snapshot
    from services.project_status_sync_runner import SyncBindingContext

    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)
    rule = {"reportType": "data_model", "aggregate": True, "projectModel": "A"}
    db.set_project_status_update_policy(
        "VPI-T2-D5", "automatic", True, None, json.dumps(rule),
        json.dumps({"note": "a"}), {"remark": "automatic"},
    )
    rows = [{"incident": str(i), "a": "A" * 300, "b": f"B-{i}"} for i in range(6)]
    service.observe("VPI-T2-D5", "tdc", rows, aggregate=True)
    service.observe("VPI-T2-D5", "tdc", rows, aggregate=True)
    preview_a = service.candidate_preview("VPI-T2-D5")
    candidate_a = next(item["candidateValue"] for item in preview_a["differences"] if item["targetField"] == "note")
    # API output is display-capped, while the comparison/cache retains the
    # bounded full value used by execution.
    assert len(candidate_a) == 200
    db.set_project_status_update_policy(
        "VPI-T2-D5", "automatic", True, None, json.dumps(rule),
        json.dumps({"note": "b"}), {"remark": "automatic"},
    )
    preview = service.candidate_preview("VPI-T2-D5")
    candidate = next(item["candidateValue"] for item in preview["differences"] if item["targetField"] == "note")
    ctx = SyncBindingContext(
        binding_id=1, deliverable_id="VPI-T2-D5", phase_id="VPI-T2", source_type="tdc",
        external_key=None, match_rule=rule, mapping={"note": "b"}, cursor={},
        expected_deliverable_updated_at="v1", run_id=1, credential_ref="domain",
    )
    actual = _snapshot(ctx, rows, []).candidates[0].field_values["note"]
    assert candidate == actual
    assert "5：B-5" in candidate


def test_candidate_preview_compares_full_values_and_normalizes_single_dates(tmp_path):
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)
    rule = {"reportType": "data_model", "incident": "FLOW-1"}
    db.set_project_status_update_policy(
        "VPI-T2-D5", "automatic", True, "FLOW-1", json.dumps(rule),
        json.dumps({"plannedDate": "targetDate", "note": "summaryNote"}),
        {"planned_date": "automatic", "remark": "automatic"},
    )
    long_current = "A" * 200 + "current"
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_deliverables SET planned_date=?, remark=? WHERE id=?",
            ("2026-08-08", long_current, "VPI-T2-D5"),
        )
    row = {
        "incident": "FLOW-1",
        "targetDate": "2026-08-08T00:00:00",
        "summaryNote": "A" * 200 + "candidate",
    }
    service.observe("VPI-T2-D5", "tdc", [row])
    service.observe("VPI-T2-D5", "tdc", [row])
    preview = service.candidate_preview("VPI-T2-D5")
    date_diff = next(item for item in preview["differences"] if item["targetField"] == "plannedDate")
    note_diff = next(item for item in preview["differences"] if item["targetField"] == "note")
    assert date_diff["candidateValue"] == "2026-08-08"
    assert date_diff["changed"] is False
    assert note_diff["changed"] is True


def test_multi_record_without_writable_note_is_not_reported_as_clear(tmp_path):
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)
    rule = {"reportType": "data_model", "aggregate": True, "projectModel": "A"}
    db.set_project_status_update_policy(
        "VPI-T2-D5", "automatic", True, None, json.dumps(rule),
        json.dumps({"owner": "currentApprover"}), {"owner": "automatic"},
    )
    rows = [
        {"incident": "A-1", "currentApprover": "Alice"},
        {"incident": "A-2", "currentApprover": "Bob"},
    ]
    service.observe("VPI-T2-D5", "tdc", rows, aggregate=True)
    service.observe("VPI-T2-D5", "tdc", rows, aggregate=True)
    preview = service.candidate_preview("VPI-T2-D5")
    assert preview["stability"]["confirmed"] == 2
    assert preview["stability"]["ready"] is False
    assert preview["reason"] == "aggregate_note_mapping_required"


def test_identified_records_boundaries_and_reorder_stability():
    """【P2-6 共享规范化纯函数边界】重排指纹稳定、异常类型防御、超限 fail-closed。"""
    from services.project_status_records import (
        identified_records,
        aggregate_fingerprint,
        aggregate_content_version,
        clean_identity,
        MAX_AGGREGATE_RECORDS,
    )

    # 1. 重排输入保持指纹与版本一致
    r1 = [{"incident": "B", "val": 2}, {"incident": "A", "val": 1}]
    r2 = [{"incident": "A", "val": 1}, {"incident": "B", "val": 2}]
    id1 = identified_records(r1)
    id2 = identified_records(r2)
    assert id1 == id2
    assert aggregate_fingerprint(id1) == aggregate_fingerprint(id2)
    assert aggregate_content_version(id1) == aggregate_content_version(id2)

    # 2. 单号类型异常安全防御
    assert clean_identity(None) == ""
    assert clean_identity([1, 2, 3]) == ""
    assert clean_identity({"key": "val"}) == ""
    assert clean_identity(12345) == "12345"

    # 3. 超出最大记录上限显式 fail-closed
    oversized = [{"incident": str(i)} for i in range(MAX_AGGREGATE_RECORDS + 1)]
    with pytest.raises(ValueError, match="exceeds maximum"):
        identified_records(oversized)


def test_observe_record_set_filters_legacy_scalar_mappings(tmp_path):
    """Verifies record_set discovery drops legacy scalar owner/date without raising ValueError."""
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    # Save a legacy policy with owner, plannedDate and note
    db.set_project_status_update_policy(
        deliverable_id="VPI-T2-D3",
        mode="automatic",
        enabled=False,
        external_key=None,
        match_rule_json=json.dumps({"reportType": "ewo", "aggregate": False}),
        mapping_json=json.dumps({"owner": "_rsp_name", "plannedDate": "_required_date", "note": "_subject"}),
        field_authority={"owner": "automatic", "planned_date": "automatic", "remark": "automatic"},
    )
    service = MappingDiscoveryService(db)
    rows = [{"_no": "EWO-001", "_source_item_id": "a" * 32, "_subject": "Test Note"}]
    rule = {
        "contractVersion": "2",
        "bindingMode": "record_set",
        "reportType": "ewo",
        "aggregate": True,
        "projectCode": "F610S",
    }
    result = service.observe("VPI-T2-D3", "aras", rows, aggregate=True, match_rule=rule)
    assert result["state"] == "matched"
