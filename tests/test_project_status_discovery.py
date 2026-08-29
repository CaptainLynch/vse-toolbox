# -*- coding: utf-8 -*-
from __future__ import annotations

from core.db_manager import DatabaseManager
from services.aras_crawler import DEFAULT_EWO_SELECT_FIELDS
from services.project_status_discovery import MappingDiscoveryService


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
    assert source_changed["stability"]["confirmed"] == 1
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

    # Deliverable row in DB has: owner="赵岩", planned_date="2026-08-08", remark="逾期 5 天"
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
    assert note_diff["currentValue"] == "逾期 5 天"
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
