# -*- coding: utf-8 -*-
"""API contracts for project-status update policy and audit endpoints."""

from __future__ import annotations

import pytest

import web.app as web_app
from core.repos.project_status import compute_policy_config_digest as _p1d_digest
from services.project_status_records import compute_config_signature


@pytest.fixture()
def client(monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "project-status.db"))
    app = web_app.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _status(client):  # type: ignore[no-untyped-def]
    response = client.get("/api/project-status?phase=VPI-T2")
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    return body["data"]


def _manual_payload(item, **overrides):  # type: ignore[no-untyped-def]
    payload = {
        "status": item["status"],
        "owner": item["owner"],
        "plannedDate": item["plannedDate"],
        "actualDate": item["actualDate"],
        "progress": item["progress"],
        "note": item["note"],
        "updatedAt": item["updatedAt"],
    }
    payload.update(overrides)
    return payload


def test_update_policy_defaults_and_status_summary(client) -> None:  # type: ignore[no-untyped-def]
    response = client.get("/api/project-status/deliverables/VPI-T2-D5/update-policy")
    assert response.status_code == 200
    policy = response.get_json()["data"]
    # 契约内交付物新库默认 automatic（未启用，待配置）。
    assert policy["mode"] == "automatic"
    assert policy["sourceType"] == "tdc"
    assert policy["enabled"] is False
    assert policy["externalKey"] is None
    assert policy["matchRule"] == {}
    assert all(value == "manual" for value in policy["fieldAuthority"].values())

    status = _status(client)
    summary = next(
        item["updatePolicy"] for item in status["deliverables"] if item["id"] == "VPI-T2-D5"
    )
    assert summary["mode"] == "automatic"
    assert summary["sourceType"] == "tdc"
    assert summary["enabled"] is False
    assert summary["syncState"] == "idle"


def _record_two_observations(
    client,
    deliverable_id: str = "VPI-T2-D5",
    source_type: str = "tdc",
    external_key: str = "FM-1",
    fields: list[str] | None = None,
    match_rule: dict[str, object] | None = None,
) -> None:
    """Helper to record two consecutive stable observations directly in test DB."""
    import json
    field_list = fields if fields is not None else [
        "currentApprover", "approvalComment", "incident", "reportType"
    ]
    report = {
        "fields": field_list,
        "statusOrApprovalFields": [],
        "suggestedStatusMapping": [],
        "suggestedAutomaticFields": [],
        "requiresConfirmation": True,
    }
    if match_rule is None:
        match_rule = (
            {"reportType": "ewo", "ewoNo": external_key}
            if source_type == "aras"
            else {"reportType": "data_model", "incident": external_key}
        )
    config_signature = compute_config_signature(source_type, match_rule)
    db = web_app.DatabaseManager()

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


def test_policy_patch_enables_pilot_and_persists(client) -> None:  # type: ignore[no-untyped-def]
    _record_two_observations(
        client,
        deliverable_id="VPI-T2-D5",
        source_type="tdc",
        external_key="FM-1",
        fields=["currentApprover", "incident", "reportType"],
    )
    payload = {
        "mode": "hybrid",
        "enabled": True,
        "externalKey": "FM-1",
        "credentialRef": "test-alias",
        "matchRule": {"reportType": "data_model", "incident": "FM-1"},
        "mapping": {"owner": "currentApprover"},
        "fieldAuthority": {"owner": "automatic"},
    }
    response = client.patch(
        "/api/project-status/deliverables/VPI-T2-D5/update-policy",
        json=payload,
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["mode"] == "hybrid"
    assert data["enabled"] is True
    assert data["externalKey"] == "FM-1"
    assert isinstance(data["credentialAvailable"], bool)
    assert data["credentialAvailable"] is True
    credential_keys = {key for key in data if "credential" in key.lower()}
    assert credential_keys == {"credentialAvailable"}
    assert data["matchRule"] == {"reportType": "data_model", "incident": "FM-1"}
    assert data["mapping"] == {"owner": "currentApprover"}
    assert data["fieldAuthority"]["owner"] == "automatic"

    again = client.get("/api/project-status/deliverables/VPI-T2-D5/update-policy")
    assert again.get_json()["data"] == data


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"enabled": True}, "externalKey"),
        ({"enabled": True, "externalKey": "k"}, "matchRule"),
        ({"matchRule": {"badKey": 1}}, "matchRule"),
        ({"matchRule": {"url": "http://example.invalid"}}, "matchRule"),
        ({"mapping": {"host": "example.invalid"}}, "mapping"),
        ({"mapping": {"status": "approvalStatus"}}, "mapping"),
        ({"mapping": {"owner": ""}}, "mapping"),
        ({"fieldAuthority": {"status": "automatic"}}, "fieldAuthority"),
        (
            {
                "mode": "manual",
                "enabled": True,
                "externalKey": "FM-1",
                "credentialRef": "alias",
                "matchRule": {"reportType": "data_model", "incident": "FM-1"},
                "mapping": {"owner": "currentApprover"},
                "fieldAuthority": {"owner": "automatic"},
            },
            "enabled",
        ),
        ({"sourceType": "feishu"}, "request"),
        ({"mode": "scheduled"}, "mode"),
        # Missing or wrong reportType when enabling
        (
            {
                "mode": "hybrid",
                "enabled": True,
                "externalKey": "FM-1",
                "credentialRef": "alias",
                "matchRule": {"incident": "FM-1"},
                "mapping": {"owner": "currentApprover"},
                "fieldAuthority": {"owner": "automatic"},
            },
            "matchRule",
        ),
        (
            {
                "mode": "hybrid",
                "enabled": True,
                "externalKey": "FM-1",
                "credentialRef": "alias",
                "matchRule": {"reportType": "wrong_type", "incident": "FM-1"},
                "mapping": {"owner": "currentApprover"},
                "fieldAuthority": {"owner": "automatic"},
            },
            "matchRule",
        ),
        # Missing additional match key
        (
            {
                "mode": "hybrid",
                "enabled": True,
                "externalKey": "FM-1",
                "credentialRef": "alias",
                "matchRule": {"reportType": "data_model"},
                "mapping": {"owner": "currentApprover"},
                "fieldAuthority": {"owner": "automatic"},
            },
            "matchRule",
        ),
        # Absent credential alias
        (
            {
                "mode": "hybrid",
                "enabled": True,
                "externalKey": "FM-1",
                "matchRule": {"reportType": "data_model", "incident": "FM-1"},
                "mapping": {"owner": "currentApprover"},
                "fieldAuthority": {"owner": "automatic"},
            },
            "credentialRef",
        ),
        # Automatic authority empty when enabling
        (
            {
                "mode": "hybrid",
                "enabled": True,
                "externalKey": "FM-1",
                "credentialRef": "alias",
                "matchRule": {"reportType": "data_model", "incident": "FM-1"},
                "mapping": {"owner": "currentApprover"},
                "fieldAuthority": {},
            },
            "fieldAuthority",
        ),
        # Mapping keys differ from automatic authority
        (
            {
                "mode": "hybrid",
                "enabled": True,
                "externalKey": "FM-1",
                "credentialRef": "alias",
                "matchRule": {"reportType": "data_model", "incident": "FM-1"},
                "mapping": {"owner": "currentApprover", "note": "approvalComment"},
                "fieldAuthority": {"owner": "automatic"},
            },
            "mapping",
        ),
        # No evidence recorded (<2 observations)
        (
            {
                "mode": "hybrid",
                "enabled": True,
                "externalKey": "FM-1",
                "credentialRef": "alias",
                "matchRule": {"reportType": "data_model", "incident": "FM-1"},
                "mapping": {"owner": "currentApprover"},
                "fieldAuthority": {"owner": "automatic"},
            },
            "enabled",
        ),
    ],
)
def test_policy_patch_rejects_invalid_configuration(client, payload, field) -> None:  # type: ignore[no-untyped-def]
    response = client.patch(
        "/api/project-status/deliverables/VPI-T2-D5/update-policy",
        json=payload,
    )
    assert response.status_code == 422
    assert field in response.get_json()["error"]["fields"]


def test_policy_patch_rejects_evidence_mismatches(client) -> None:  # type: ignore[no-untyped-def]
    import json
    db = web_app.DatabaseManager()
    report = {
        "fields": ["currentApprover", "incident"],
        "statusOrApprovalFields": [],
        "suggestedStatusMapping": [],
        "suggestedAutomaticFields": [],
        "requiresConfirmation": True,
    }
    # 1. Evidence with different external key
    db.record_mapping_observation(
        "VPI-T2-D5", "tdc", "matched", "DIFF-KEY", "fp", 1, "[]", json.dumps(report)
    )
    db.record_mapping_observation(
        "VPI-T2-D5", "tdc", "matched", "DIFF-KEY", "fp", 1, "[]", json.dumps(report)
    )
    payload = {
        "mode": "hybrid",
        "enabled": True,
        "externalKey": "FM-1",
        "credentialRef": "alias",
        "matchRule": {"reportType": "data_model", "incident": "FM-1"},
        "mapping": {"owner": "currentApprover"},
        "fieldAuthority": {"owner": "automatic"},
    }
    res = client.patch("/api/project-status/deliverables/VPI-T2-D5/update-policy", json=payload)
    assert res.status_code == 422
    assert "enabled" in res.get_json()["error"]["fields"]

    # 2. Mapped source field absent from latest fieldReport
    _record_two_observations(
        client,
        deliverable_id="VPI-T2-D5",
        source_type="tdc",
        external_key="FM-1",
        fields=["otherField"],  # currentApprover absent
    )
    res2 = client.patch("/api/project-status/deliverables/VPI-T2-D5/update-policy", json=payload)
    assert res2.status_code == 422
    assert "enabled" in res2.get_json()["error"]["fields"]

    # 3. Two observations with differing sources
    db.record_mapping_observation(
        "VPI-T2-D5", "tdc", "matched", "FM-1", "fp1", 1, "[]", json.dumps(report)
    )
    db.record_mapping_observation(
        "VPI-T2-D5", "aras", "matched", "FM-1", "fp2", 1, "[]", json.dumps(report)
    )
    res3 = client.patch("/api/project-status/deliverables/VPI-T2-D5/update-policy", json=payload)
    assert res3.status_code == 422
    assert "enabled" in res3.get_json()["error"]["fields"]

    # 4. Exactly one observation
    payload_d3 = {
        "mode": "hybrid",
        "enabled": True,
        "externalKey": "FM-3",
        "credentialRef": "alias",
        "matchRule": {"reportType": "ewo", "ewoNo": "FM-3"},
        "mapping": {"owner": "currentApprover"},
        "fieldAuthority": {"owner": "automatic"},
    }
    db.record_mapping_observation(
        "VPI-T2-D3", "aras", "matched", "FM-3", "fp", 1, "[]", json.dumps(report)
    )
    res4 = client.patch("/api/project-status/deliverables/VPI-T2-D3/update-policy", json=payload_d3)
    assert res4.status_code == 422
    assert "enabled" in res4.get_json()["error"]["fields"]


@pytest.mark.parametrize("blocked_id", ["VPI-T2-D1", "VPI-T2-D4"])
def test_policy_patch_rejects_blocked_targets(client, blocked_id: str) -> None:  # type: ignore[no-untyped-def]
    """D1 和 D4 禁止配置非 manual 模式及自动同步。"""
    response = client.patch(
        f"/api/project-status/deliverables/{blocked_id}/update-policy",
        json={"mode": "hybrid"},
    )
    assert response.status_code == 422
    assert "mode" in response.get_json()["error"]["fields"]

    response = client.patch(
        f"/api/project-status/deliverables/{blocked_id}/update-policy",
        json={"enabled": True, "externalKey": "k", "matchRule": {"incident": "x"}},
    )
    assert response.status_code == 422
    assert "enabled" in response.get_json()["error"]["fields"]


@pytest.mark.parametrize("allowed_id", ["VPI-T2-D2", "VPI-T2-D3", "VPI-T2-D5"])
def test_policy_patch_allows_supported_targets(client, allowed_id: str) -> None:  # type: ignore[no-untyped-def]
    """D2, D3, D5 属于允许自动化范围。"""
    response = client.patch(
        f"/api/project-status/deliverables/{allowed_id}/update-policy",
        json={"mode": "hybrid"},
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["mode"] == "hybrid"

    response = client.patch(
        f"/api/project-status/deliverables/{allowed_id}/update-policy",
        json={"fieldAuthority": {"status": "automatic"}},
    )
    assert response.status_code == 422
    assert "fieldAuthority" in response.get_json()["error"]["fields"]


def test_updates_endpoint_records_manual_save(client) -> None:  # type: ignore[no-untyped-def]
    empty = client.get("/api/project-status/updates?deliverableId=VPI-T2-D5")
    assert empty.status_code == 200
    assert empty.get_json()["data"]["updates"] == []

    item = next(
        row for row in _status(client)["deliverables"] if row["id"] == "VPI-T2-D5"
    )
    response = client.patch(
        f'/api/project-status/deliverables/{item["id"]}',
        json=_manual_payload(item, progress=83, note="推进中 password=secret123"),
    )
    assert response.status_code == 200

    updates = client.get("/api/project-status/updates?deliverableId=VPI-T2-D5")
    assert updates.status_code == 200
    data = updates.get_json()["data"]
    assert data["total"] == 1
    record = data["updates"][0]
    assert record["triggerType"] == "manual"
    assert record["result"] == "applied"
    assert record["appliedChanges"]["progress"] == 83
    assert "secret123" not in str(record["proposedChanges"])
    assert "[redacted]" in str(record["proposedChanges"])


def test_updates_and_policy_not_found_or_invalid(client) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/project-status/deliverables/missing/update-policy").status_code == 404
    missing = client.patch(
        "/api/project-status/deliverables/missing/update-policy",
        json={"mode": "manual"},
    )
    assert missing.status_code == 404

    updates = client.get("/api/project-status/updates?deliverableId=missing")
    assert updates.status_code == 404

    no_id = client.get("/api/project-status/updates")
    assert no_id.status_code == 422
    assert "deliverableId" in no_id.get_json()["error"]["fields"]


def test_sync_display_states_across_binding_lifecycle(client) -> None:
    """终审测试缺口：七态展示状态的 payload 级断言（绑定生命周期驱动）。"""
    db = web_app.DatabaseManager()

    def fetch(deliverable_id: str):  # type: ignore[no-untyped-def]
        status = client.get("/api/project-status").get_json()["data"]
        item = next(i for i in status["deliverables"] if i["id"] == deliverable_id)
        return status, item

    # 1. 新库默认：契约内 pending_config；手工模式 manual。
    _, d3 = fetch("VPI-T2-D3")
    assert d3["syncDisplay"]["state"] == "pending_config"
    # 非快照态：派生进度等于手工字段，来源标 manual（不编造快照数字）。
    assert d3["progressSource"] == "manual"
    assert d3["effectiveProgress"] == d3["progress"]
    _, d4 = fetch("VPI-T2-D4")
    assert d4["syncDisplay"]["state"] == "manual"

    # 2. 启用绑定但无快照：pending_first_sync。
    _record_two_observations(
        client,
        deliverable_id="VPI-T2-D5",
        source_type="tdc",
        external_key="FM-1",
        fields=["currentApprover", "incident", "reportType"],
    )
    response = client.patch(
        "/api/project-status/deliverables/VPI-T2-D5/update-policy",
        json={
            "mode": "hybrid",
            "enabled": True,
            "externalKey": "FM-1",
            "credentialRef": "test-alias",
            "matchRule": {"reportType": "data_model", "incident": "FM-1"},
            "mapping": {"owner": "currentApprover"},
            "fieldAuthority": {"owner": "automatic"},
        },
    )
    assert response.status_code == 200
    _, d5 = fetch("VPI-T2-D5")
    assert d5["syncDisplay"]["state"] == "pending_first_sync"

    # 3. syncState=failed 且无快照：sync_failed。
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET sync_state='failed' "
            "WHERE deliverable_id='VPI-T2-D5'"
        )
    _, d5 = fetch("VPI-T2-D5")
    assert d5["syncDisplay"]["state"] == "sync_failed"

    # 4. enabled + total=0 快照：no_source_records。
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET sync_state='success' "
            "WHERE deliverable_id='VPI-T2-D5'"
        )
    db.replace_project_status_analysis_cache("VPI-T2-D5", 1, {
        "total_count": 0, "completed_count": 0, "incomplete_count": 0,
        "overdue_count": 0, "due_soon_count": 0, "missing_due_date_count": 0,
        "department_counts": {}, "snapshot_at": "2026-09-12T08:00:00.000Z",
    }, [])
    _, d5 = fetch("VPI-T2-D5")
    assert d5["syncDisplay"]["state"] == "no_source_records"
    # 快照存在但 total=0 属「无来源记录」，不是 snapshot 态：派生进度回退手工值，
    # 不把空快照当可信进度来源（state 与 progressSource 因此不同源）。
    assert d5["progressSource"] == "manual"
    assert d5["effectiveProgress"] == d5["progress"]

    # 5. enabled + 有效快照：snapshot + effectiveStatus（有逾期 → 已逾期）；
    #    汇总：待同步只剩 D2/D3（pending_config），D5 快照逾期计风险。
    db.replace_project_status_analysis_cache("VPI-T2-D5", 2, {
        "total_count": 4, "completed_count": 3, "incomplete_count": 1,
        "overdue_count": 1, "due_soon_count": 0, "missing_due_date_count": 0,
        "department_counts": {}, "snapshot_at": "2026-09-12T09:00:00.000Z",
    }, [])
    status, d5 = fetch("VPI-T2-D5")
    assert d5["syncDisplay"]["state"] == "snapshot"
    assert d5["effectiveStatus"] == "已逾期"
    # 2026-10-28：进度按明细换算（3/4 → 75%），不再回落到手工 0%。
    assert d5["effectiveProgress"] == 75
    assert d5["progressSource"] == "snapshot"
    assert d5["progress"] == 0  # 手工字段语义不变（编辑表单预填它）
    # 概览表的「实际完成或当前进度」同样取派生值，避免两套数字。
    assert d5["progressOrDate"] == "75%"
    assert status["phase"]["pendingCount"] == 2
    assert status["phase"]["completedCount"] == 1
    assert status["phase"]["riskCount"] == 2  # D4 计划逾期（手工态）+ D5 快照逾期

    # 6. GPT 终审修正：有独立快照但从未成功同步（last_success_at 为空）
    #    → pending_config，不暴露手工占位值（paused 只属于"曾同步后暂停"）。
    db.replace_project_status_analysis_cache("VPI-T2-D2", 1, {
        "total_count": 2, "completed_count": 2, "incomplete_count": 0,
        "overdue_count": 0, "due_soon_count": 0, "missing_due_date_count": 0,
        "department_counts": {}, "snapshot_at": "2026-09-12T08:30:00.000Z",
    }, [])
    status, d2 = fetch("VPI-T2-D2")
    assert d2["syncDisplay"]["state"] == "pending_config"
    assert status["phase"]["pendingCount"] == 2  # D2 + D3
    assert status["phase"]["riskCount"] == 2  # D4 + D5

    # 6b. 曾成功同步后关闭：paused（手工列持有可信同步值）。
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET last_success_at='2026-09-12 08:00:00' "
            "WHERE deliverable_id='VPI-T2-D2'"
        )
    status, d2 = fetch("VPI-T2-D2")
    assert d2["syncDisplay"]["state"] == "paused"
    # paused 为非数值态（同步不写 status/progress，占位值不可信）：
    # 不应用快照换算、计入待同步、不计完成与业务风险。
    assert status["phase"]["pendingCount"] == 2  # D2（已暂停）+ D3
    assert status["phase"]["riskCount"] == 2  # D4（计划逾期，手工态）+ D5（快照逾期）

    # 7. enabled + syncState=running：待首次同步态、标签「同步中」。
    _record_two_observations(
        client,
        deliverable_id="VPI-T2-D3",
        source_type="aras",
        external_key="EWO-1",
        fields=["currentApprover", "reportType"],
    )
    response = client.patch(
        "/api/project-status/deliverables/VPI-T2-D3/update-policy",
        json={
            "mode": "automatic",
            "enabled": True,
            "externalKey": "EWO-1",
            "credentialRef": "test-alias",
            "matchRule": {"reportType": "ewo", "ewoNo": "EWO-1"},
            "mapping": {"owner": "currentApprover"},
            "fieldAuthority": {"owner": "automatic"},
        },
    )
    assert response.status_code == 200
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET sync_state='running' "
            "WHERE deliverable_id='VPI-T2-D3'"
        )
    _, d3 = fetch("VPI-T2-D3")
    assert d3["syncDisplay"]["state"] == "pending_first_sync"
    assert d3["syncDisplay"]["label"] == "同步中"


def test_d5_contract_exposes_multi_serial_key() -> None:
    """D5 绑定契约新增多单号键 documentNos（与 documentNo 互斥）。

    R3 裁定：Task 11 补上 matchFields 的多值输入项（显示名 / discovery 过滤名 /
    placeholder 说明），与功能开关一起上线。
    """
    from core.project_status_contracts import PROJECT_STATUS_SOURCE_CAPABILITIES

    caps = PROJECT_STATUS_SOURCE_CAPABILITIES["VPI-T2-D5"]
    assert "documentNos" in caps["matchKeys"]
    assert "documentNo" in caps["matchKeys"]
    names = [item[2] for item in caps["matchFields"]]
    assert "document_nos" in names
    # 其它交付物不得出现该键（多单号只对 D5 数模开放）。
    assert all(
        "documentNos" not in PROJECT_STATUS_SOURCE_CAPABILITIES[key]["matchKeys"]
        for key in ("VPI-T2-D2", "VPI-T2-D3")
    )


def test_d5_multi_serial_match_field_is_actionable() -> None:
    """多值输入项必须自解释：显示名点明合并统计，placeholder 说明分隔符与三选一。"""
    from core.project_status_contracts import PROJECT_STATUS_SOURCE_CAPABILITIES

    fields = {
        item[0]: item for item in PROJECT_STATUS_SOURCE_CAPABILITIES["VPI-T2-D5"]["matchFields"]
    }
    key, label, filter_name, placeholder = fields["documentNos"]
    assert key == "documentNos"
    assert filter_name == "document_nos"
    assert label == "流水单号（多个，合并统计）"
    assert "空格" in placeholder and "逗号" in placeholder
    # 三选一：多单号与单值流水单号、实例号三者互斥（不只是与实例号）。
    assert "三选一" in placeholder
    # incident 的占位文案必须同口径：不能再写「与流水单号二选一」。
    incident_placeholder = fields["incident"][3]
    assert "三选一" in incident_placeholder
    assert "二选一" not in incident_placeholder


def test_d5_discovery_maps_multi_serial_filter_name() -> None:
    """discovery 过滤名 document_nos 必须落到契约白名单内的键。"""
    from core.project_status_contracts import PROJECT_STATUS_SOURCE_CAPABILITIES
    from web.app import _MAPPING_DISCOVERY_RULE_FIELDS

    mapping = _MAPPING_DISCOVERY_RULE_FIELDS[("tdc", "data_model")]
    assert mapping["document_no"] == "documentNo"
    assert mapping["document_nos"] == "documentNos"
    assert set(mapping.values()) <= set(
        PROJECT_STATUS_SOURCE_CAPABILITIES["VPI-T2-D5"]["matchKeys"]
    )


def test_multi_serial_filter_never_reaches_upstream_query() -> None:
    """多单号只在本地匹配：构造函数不得把 document_nos 变成 TDC 上游查询参数。"""
    filters = web_app._tdc_data_model_filters({"document_nos": "3D-00001018 3D-00001193"})
    assert "3D-00001018" not in repr(filters)
    assert not any("3D-00001018" in value for value in filters.to_params().values())


# ── 多单号绑定保存校验（Task 8：互斥、聚合、功能开关、字节上限） ──────────────

_D5_POLICY_URL = "/api/project-status/deliverables/VPI-T2-D5/update-policy"


def _enable_multi_serial(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("VSE_TDC_MULTI_SERIAL_SYNC", "1")


@pytest.mark.parametrize(("rule", "field"), [
    ({"reportType": "data_model", "aggregate": True, "documentNos": ["3D-1"], "documentNo": "3D-2"}, "matchRule"),
    ({"reportType": "data_model", "aggregate": True, "documentNos": ["3D-1"], "incident": "900001"}, "matchRule"),
    ({"reportType": "data_model", "aggregate": False, "documentNos": ["3D-1"]}, "matchRule"),
    ({"reportType": "data_model", "aggregate": True, "documentNos": ["3D-1", 42]}, "matchRule"),
])
def test_multi_serial_rule_rejects_invalid_combinations(client, monkeypatch, rule, field) -> None:
    _enable_multi_serial(monkeypatch)
    response = client.patch(_D5_POLICY_URL, json={"matchRule": rule})
    assert response.status_code == 422
    assert field in response.get_json()["error"]["fields"]


def test_multi_serial_rule_rejects_single_serial_key_with_explicit_message(client, monkeypatch) -> None:
    """互斥文案必须指向「三选一」，且指明多单号绑定不接受单记录键。"""
    _enable_multi_serial(monkeypatch)
    response = client.patch(
        _D5_POLICY_URL,
        json={"matchRule": {"reportType": "data_model", "aggregate": True,
                            "documentNos": ["3D-1"], "incident": "900001"}},
    )
    assert response.status_code == 422
    assert "三选一" in response.get_json()["error"]["fields"]["matchRule"]


def test_multi_serial_rule_rejected_when_flag_disabled(client, monkeypatch) -> None:
    """R22/R4：开关关闭时 documentNos 一律 fail-closed（保存入口）。"""
    monkeypatch.delenv("VSE_TDC_MULTI_SERIAL_SYNC", raising=False)
    response = client.patch(
        _D5_POLICY_URL,
        json={"matchRule": {"reportType": "data_model", "aggregate": True, "documentNos": ["3D-1"]}},
    )
    assert response.status_code == 422
    assert "功能开关关闭" in response.get_json()["error"]["fields"]["matchRule"]


def test_multi_serial_draft_saves_normalized_set(client, monkeypatch) -> None:
    """合法多单号草稿：去重排序后落库，聚合标志保留，单值键不出现。"""
    _enable_multi_serial(monkeypatch)
    response = client.patch(
        _D5_POLICY_URL,
        json={"matchRule": {"reportType": "data_model", "aggregate": True,
                            "documentNos": ["3D-2", " 3D-1 ", "3D-2"]}},
    )
    assert response.status_code == 200
    rule = response.get_json()["data"]["matchRule"]
    assert rule["documentNos"] == ["3D-1", "3D-2"]
    assert rule["aggregate"] is True
    assert "documentNo" not in rule


@pytest.mark.parametrize("empty", [None, []])
def test_multi_serial_empty_set_omits_key(client, monkeypatch, empty) -> None:
    """R19：空集合/None 省略该键，绝不持久化 null（签名侧对 null 会 raise）。"""
    _enable_multi_serial(monkeypatch)
    response = client.patch(
        _D5_POLICY_URL,
        json={"matchRule": {"reportType": "data_model", "aggregate": True, "documentNos": empty}},
    )
    assert response.status_code == 200
    rule = response.get_json()["data"]["matchRule"]
    assert "documentNos" not in rule


def test_multi_serial_rule_rejects_watchlist_scope_overlap(client, monkeypatch) -> None:
    """与关注清单同步范围叠加会静默取交集（少算），保存入口拒绝。"""
    _enable_multi_serial(monkeypatch)
    db = web_app.DatabaseManager()
    job = next(j for j in db.list_archive_jobs() if j["job_key"] == "tdc_data_model")
    db.update_archive_job_config(
        "tdc_data_model", enabled=False, credential_ref="ref",
        filters={"syncScope": "watchlist", "watchlist": ["3D-1"]},
        output_subdir="", expected_updated_at=job["updated_at"], actor="cli",
    )
    response = client.patch(
        _D5_POLICY_URL,
        json={"matchRule": {"reportType": "data_model", "aggregate": True, "documentNos": ["3D-1"]}},
    )
    assert response.status_code == 422
    assert "关注清单" in response.get_json()["error"]["fields"]["matchRule"]


def test_multi_serial_rule_rejects_oversized_set(client, monkeypatch) -> None:
    """R15：写入 match_rule_json 前校验 12 KB 字节上限（复用关注清单预算）。"""
    _enable_multi_serial(monkeypatch)
    serials = [f"3D-{index:058d}" for index in range(300)]  # 约 18 KB，超过 12 KB 预算
    response = client.patch(
        _D5_POLICY_URL,
        json={"matchRule": {"reportType": "data_model", "aggregate": True, "documentNos": serials}},
    )
    assert response.status_code == 422
    # R27.1：上限用例断言精确文案（不只用「过长」子串）。
    assert (
        response.get_json()["error"]["fields"]["matchRule"]
        == "多单号集合过长，请分批处理（单次最多 12 KB）"
    )


def test_multi_serial_rule_rejects_over_match_rule_text_limit(client, monkeypatch) -> None:
    """R27.1：集合字节预算之内、但整条 match_rule 超过 4000 字符时按规则上限拒绝。"""
    _enable_multi_serial(monkeypatch)
    serials = [f"3D-{index:017d}" for index in range(200)]  # 约 4.6 KB：未过 12 KB
    response = client.patch(
        _D5_POLICY_URL,
        json={"matchRule": {"reportType": "data_model", "aggregate": True, "documentNos": serials}},
    )
    assert response.status_code == 422
    assert response.get_json()["error"]["fields"]["matchRule"] == "匹配规则过长"


def test_discovery_identity_derives_multi_serial_set(monkeypatch) -> None:
    """discovery 身份：document_nos 规范化为 documentNos，强制聚合，绝不进上游参数。"""
    _enable_multi_serial(monkeypatch)
    rule, values = web_app._mapping_discovery_query_identity(
        {"filters": {"document_nos": ["3D-2", " 3D-1 ", "3D-2"]}}, "VPI-T2-D5",
    )
    assert rule["documentNos"] == ["3D-1", "3D-2"]
    assert rule["aggregate"] is True
    assert "document_nos" not in values
    assert "3D-1" not in repr(values)

    empty_rule, _ = web_app._mapping_discovery_query_identity(
        {"filters": {"document_nos": []}}, "VPI-T2-D5",
    )
    assert "documentNos" not in empty_rule


def test_multi_serial_rule_rejects_single_record_external_key(client, monkeypatch) -> None:
    """多单号集合没有单记录稳定键：带上单记录外部键必须拒绝（与运行期同源）。"""
    _enable_multi_serial(monkeypatch)
    response = client.patch(
        _D5_POLICY_URL,
        json={
            "matchRule": {"reportType": "data_model", "aggregate": True, "documentNos": ["3D-1"]},
            "externalKey": "FM-1",
        },
    )
    assert response.status_code == 422
    assert "外部键" in response.get_json()["error"]["fields"]["matchRule"]


def test_discovery_identity_rejects_oversized_multi_serial_set(monkeypatch) -> None:
    """R27.1：发现侧预算对齐保存侧（4000 字节），超限在抓取前拒绝，避免白跑一次全量。"""
    _enable_multi_serial(monkeypatch)
    serials = [f"3D-{index:058d}" for index in range(300)]
    with pytest.raises(web_app._TDCRequestError) as info:
        web_app._mapping_discovery_query_identity({"filters": {"document_nos": serials}}, "VPI-T2-D5")
    assert str(info.value) == "多单号集合过长，请分批处理（单次最多 4000 字节）"


def test_discovery_serial_set_budget_aligns_with_save_side() -> None:
    """R27.1 防漂移：发现侧集合预算 = min(12 KB 关注清单预算, match_rule 4000 字符)。

    两边不一致就会出现「能发现不能存」：发现侧放行、保存侧 422。
    """
    from services.data_model_watchlist import MAX_WATCHLIST_BYTES
    from services.project_status_updates import MATCH_RULE_TEXT_LIMIT

    assert MATCH_RULE_TEXT_LIMIT == 4000
    assert web_app._DISCOVERY_SERIAL_SET_MAX_BYTES == min(
        MAX_WATCHLIST_BYTES, MATCH_RULE_TEXT_LIMIT
    )


def test_discovery_identity_rejects_non_string_multi_serial_filter(monkeypatch) -> None:
    _enable_multi_serial(monkeypatch)
    with pytest.raises(web_app._TDCRequestError) as info:
        web_app._mapping_discovery_query_identity(
            {"filters": {"document_nos": {"3D-1": True}}}, "VPI-T2-D5",
        )
    assert "字符串" in str(info.value)


def test_discovery_identity_rejects_multi_serial_when_flag_disabled(monkeypatch) -> None:
    monkeypatch.delenv("VSE_TDC_MULTI_SERIAL_SYNC", raising=False)
    with pytest.raises(web_app._TDCRequestError) as info:
        web_app._mapping_discovery_query_identity(
            {"filters": {"document_nos": "3D-1 3D-2"}}, "VPI-T2-D5",
        )
    assert "功能开关关闭" in str(info.value)


def test_discovery_identity_rejects_multi_serial_with_single_serial(monkeypatch) -> None:
    _enable_multi_serial(monkeypatch)
    with pytest.raises(web_app._TDCRequestError) as info:
        web_app._mapping_discovery_query_identity(
            {"filters": {"document_nos": "3D-1", "document_no": "3D-2"}}, "VPI-T2-D5",
        )
    assert "三选一" in str(info.value)


def test_match_fields_use_real_discovery_filter_names() -> None:
    """GPT 终审 P1 回归：matchFields 的 discovery 过滤名必须是后端实际
    接受的过滤键（process_no 臆造键会让 SOR 证据抓取直接报 unsupported）。"""
    from core.project_status_contracts import (
        project_status_source_capabilities,
    )
    from web.app import (
        _TDC_DATA_MODEL_FILTER_NAMES,
        _TDC_SOR_FILTER_NAMES,
        _ewo_filters_from_payload,
    )

    for deliverable_id, allowed in (
        ("VPI-T2-D2", _TDC_SOR_FILTER_NAMES),
        ("VPI-T2-D5", _TDC_DATA_MODEL_FILTER_NAMES),
    ):
        capabilities = project_status_source_capabilities(deliverable_id)
        local_only = web_app._MAPPING_DISCOVERY_RULE_FIELDS[("tdc", "data_model")]
        for field in capabilities["matchFields"]:
            # document_no / document_nos（流水单号单值与多值集合）是唯一的例外：
            # 它们不是 TDC 查询参数，发现端按 _MAPPING_DISCOVERY_RULE_FIELDS 键
            # 收口为 matchRule.documentNo / documentNos 本地匹配，绝不发上游
            # （2026-10-09 数模流水单号绑定、2026-10-21 多单号合并统计）。
            if field[2] in {"document_no", "document_nos"}:
                assert field[2] in local_only
                continue
            assert field[2] in allowed, (deliverable_id, field)

    ewo_capabilities = project_status_source_capabilities("VPI-T2-D3")
    for field in ewo_capabilities["matchFields"]:
        filters = _ewo_filters_from_payload({"filters": {field[2]: "*x*"}})
        assert getattr(filters, field[2]) == "*x*", field


def test_snapshot_state_falls_back_to_form_snapshot_summary(client) -> None:  # type: ignore[no-untyped-def]
    """GPT 终审测试建议③：仅有表单快照（无分析快照）时，启用态交付物
    仍进入 snapshot 数值态——后端有效快照选择与前端同规则（分析优先、
    表单兜底），effectiveStatus 用同一摘要换算。"""
    from services.deliverable_form_analysis import build_form_snapshot
    from tests.test_deliverable_form_analysis import _tdc_values

    db = web_app.DatabaseManager()
    _record_two_observations(
        client,
        deliverable_id="VPI-T2-D5",
        source_type="tdc",
        external_key="FM-1",
        fields=["currentApprover", "incident", "reportType"],
    )
    response = client.patch(
        "/api/project-status/deliverables/VPI-T2-D5/update-policy",
        json={
            "mode": "hybrid",
            "enabled": True,
            "externalKey": "FM-1",
            "credentialRef": "test-alias",
            "matchRule": {"reportType": "data_model", "incident": "FM-1"},
            "mapping": {"owner": "currentApprover"},
            "fieldAuthority": {"owner": "automatic"},
        },
    )
    assert response.status_code == 200

    # 仅发布表单快照（不写分析快照缓存）。
    snapshot = build_form_snapshot(
        "tdc_data_model",
        [
            {"values": _tdc_values("审批中"), "sheetName": "Sheet1"},
            {"values": _tdc_values("已完成"), "sheetName": "Sheet1"},
        ],
        snapshot_at="2026-09-12T08:00:00Z",
        source_run_id=7,
        source="test",
    )
    db.publish_deliverable_form_snapshot(snapshot)

    status = client.get("/api/project-status").get_json()["data"]
    d5 = next(i for i in status["deliverables"] if i["id"] == "VPI-T2-D5")
    assert d5["syncDisplay"]["state"] == "snapshot"
    assert d5["analysisLink"] is None
    assert d5["formLink"]["summary"]["total"] > 0
    assert d5["effectiveStatus"] in ("进行中", "已逾期", "已完成")


def test_aggregate_rebind_clears_stale_snapshot_and_returns_to_pending(client) -> None:  # type: ignore[no-untyped-def]
    """GPT 终审 E 回归：聚合绑定换匹配规则后，旧车型分析快照被清除，
    展示状态回到 pending_first_sync（且不落入表单快照兜底）。"""
    import json
    db = web_app.DatabaseManager()
    first_rule = {
        "reportType": "data_model", "aggregate": True, "incident": "FM-1",
    }
    second_rule = {
        "reportType": "data_model", "aggregate": True, "incident": "FM-2",
    }
    report = {
        "fields": ["currentApprover", "incident", "reportType"],
        "statusOrApprovalFields": [],
        "suggestedStatusMapping": [],
        "suggestedAutomaticFields": [],
        "requiresConfirmation": True,
    }
    for fingerprint in ("agg:fp-a", "agg:fp-a"):
        db.record_mapping_observation(
            "VPI-T2-D5", "tdc", "matched", None, fingerprint, 2,
            json.dumps([{"externalKey": None, "fields": {}}]),
            json.dumps(report),
            compute_config_signature("tdc", first_rule),
        )
    response = client.patch(
        "/api/project-status/deliverables/VPI-T2-D5/update-policy",
        json={
            "mode": "automatic",
            "enabled": True,
            "credentialRef": "test-alias",
            "matchRule": {
                "reportType": "data_model", "aggregate": True, "incident": "FM-1",
            },
            "mapping": {"owner": "currentApprover"},
            "fieldAuthority": {"owner": "automatic"},
        },
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["enabled"] is True

    # 模拟上次同步已发布分析快照：换绑前处于 snapshot 数值态。
    db.replace_project_status_analysis_cache("VPI-T2-D5", 1, {
        "total_count": 4, "completed_count": 4, "incomplete_count": 0,
        "overdue_count": 0, "due_soon_count": 0, "missing_due_date_count": 0,
        "department_counts": {}, "snapshot_at": "2026-09-12T08:00:00.000Z",
    }, [])
    before = client.get("/api/project-status").get_json()["data"]
    d5_before = next(i for i in before["deliverables"] if i["id"] == "VPI-T2-D5")
    assert d5_before["syncDisplay"]["state"] == "snapshot"

    # 先换绑并暂停：当前配置变化必须清除旧快照，但旧证据不能直接
    # 授权新的 enabled 配置。
    response = client.patch(
        "/api/project-status/deliverables/VPI-T2-D5/update-policy",
        json={
            "mode": "automatic",
            "enabled": False,
            "credentialRef": "test-alias",
            "matchRule": {
                "reportType": "data_model", "aggregate": True, "incident": "FM-2",
            },
            "mapping": {"owner": "currentApprover"},
            "fieldAuthority": {"owner": "automatic"},
        },
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["enabled"] is False

    second_report = dict(report)
    for fingerprint in ("agg:fp-b", "agg:fp-b"):
        db.record_mapping_observation(
            "VPI-T2-D5", "tdc", "matched", None, fingerprint, 2,
            json.dumps([{"externalKey": None, "fields": {}}]),
            json.dumps(second_report),
            compute_config_signature("tdc", second_rule),
        )
    response = client.patch(
        "/api/project-status/deliverables/VPI-T2-D5/update-policy",
        json={
            "mode": "automatic",
            "enabled": True,
            "credentialRef": "test-alias",
            "matchRule": second_rule,
            "mapping": {"owner": "currentApprover"},
            "fieldAuthority": {"owner": "automatic"},
        },
    )
    assert response.status_code == 200
    after = client.get("/api/project-status").get_json()["data"]
    d5_after = next(i for i in after["deliverables"] if i["id"] == "VPI-T2-D5")
    assert d5_after["syncDisplay"]["state"] == "pending_first_sync"
    assert d5_after["updatePolicy"]["aggregate"] is True
    assert db.list_project_status_analysis_snapshots("VPI-T2-D5", 5) == []


def _p1d_case(client, did='VPI-T2-D5'):
    url = f'/api/project-status/deliverables/{did}/update-policy'
    response = client.get(url)
    assert response.status_code == 200
    return url, web_app.DatabaseManager(), response.get_json()['data']


def _p1d_snapshot(db, did):
    tables = (
        ('project_status_update_bindings', 'deliverable_id'),
        ('project_status_field_authority', 'field_name'),
        ('project_status_binding_config_audit', 'id'),
        ('project_status_update_audit', 'id'),
    )
    with db.get_connection() as conn:
        return tuple(
            [tuple(row) for row in conn.execute(
                f'SELECT * FROM {table} WHERE deliverable_id = ? ORDER BY {key}', (did,))]
            for table, key in tables
        )


def test_p1d_stale_digest_422(client):
    did = 'VPI-T2-D5'
    url, db, policy = _p1d_case(client, did)
    raw = db.read_project_status_update_policy_snapshot(did)
    stale = policy['configDigest']
    assert stale == _p1d_digest(did, raw['binding'], raw['authorities'])
    with db.get_connection() as conn:
        changed = conn.execute(
            'UPDATE project_status_update_bindings '
            'SET interval_minutes = COALESCE(interval_minutes, 0) + 1 WHERE deliverable_id = ?', (did,))
        assert changed.rowcount == 1
    before = _p1d_snapshot(db, did)
    current = db.read_project_status_update_policy_snapshot(did)
    assert current['binding']['sync_config_revision'] == raw['binding']['sync_config_revision']
    assert _p1d_digest(did, current['binding'], current['authorities']) != stale
    response = client.patch(url, json={'intervalMinutes': 47, 'expectedConfigDigest': stale})
    assert response.status_code == 422
    fields = response.get_json()['error']['fields']
    assert isinstance(fields, dict) and set(fields) == {'expectedConfigDigest'}
    after = _p1d_snapshot(db, did)
    assert after == before
    assert tuple(map(len, after[2:])) == tuple(map(len, before[2:]))


def test_p1d_invalid_digest_422(client):
    url, db, _ = _p1d_case(client)
    before = _p1d_snapshot(db, 'VPI-T2-D5')
    response = client.patch(url, json={'intervalMinutes': 47, 'expectedConfigDigest': 'cfgd1:BAD'})
    assert response.status_code == 422
    fields = response.get_json()['error']['fields']
    assert isinstance(fields, dict) and set(fields) == {'expectedConfigDigest'}
    after = _p1d_snapshot(db, 'VPI-T2-D5')
    assert after == before
    assert tuple(map(len, after[2:])) == tuple(map(len, before[2:]))


def test_p1d_unknown_field_request_error(client):
    url, db, _ = _p1d_case(client)
    before = _p1d_snapshot(db, 'VPI-T2-D5')
    response = client.patch(url, json={'intervalMinutes': 47, 'p1dUnknown': True})
    assert response.status_code == 422
    fields = response.get_json()['error']['fields']
    assert isinstance(fields, dict) and set(fields) == {'request'}
    assert fields['request'] == '包含不允许修改的字段'
    after = _p1d_snapshot(db, 'VPI-T2-D5')
    assert after == before
    assert tuple(map(len, after[2:])) == tuple(map(len, before[2:]))


def test_p1d_revision_conflict_request_error(client, monkeypatch):
    did = 'VPI-T2-D3'
    url, db, policy = _p1d_case(client, did)
    raw = db.read_project_status_update_policy_snapshot(did)
    revision = raw['binding']['sync_config_revision']
    save = type(db)._save_policy_txn
    seen = []

    def race(self, conn, target, *args, **kwargs):
        assert target == did and not conn.in_transaction
        assert kwargs['expected_sync_config_revision'] == revision
        assert kwargs['expected_config_digest'] == policy['configDigest']
        assert not seen
        with db.get_connection() as writer:
            changed = writer.execute(
                'UPDATE project_status_update_bindings '
                'SET sync_config_revision = sync_config_revision + 1 WHERE deliverable_id = ?', (did,))
            assert changed.rowcount == 1
        current = db.read_project_status_update_policy_snapshot(did)
        assert current['binding']['sync_config_revision'] == revision + 1
        assert _p1d_digest(did, current['binding'], current['authorities']) != policy['configDigest']
        seen.append(_p1d_snapshot(db, did))
        changes = conn.total_changes
        try:
            return save(self, conn, target, *args, **kwargs)
        finally:
            assert conn.total_changes == changes

    monkeypatch.setattr(type(db), '_save_policy_txn', race)
    response = client.patch(url, json={'intervalMinutes': 47, 'expectedConfigDigest': policy['configDigest']})
    assert len(seen) == 1
    assert response.status_code == 422
    fields = response.get_json()['error']['fields']
    assert isinstance(fields, dict) and set(fields) == {'request'}
    assert fields['request'] == '绑定已发生变化，请刷新配置后重试'
    after = _p1d_snapshot(db, did)
    assert after == seen[0]
    assert tuple(map(len, after[2:])) == tuple(map(len, seen[0][2:]))


def test_p1d_patch_response_digest_reusable(client):
    did = 'VPI-T2-D5'
    url, db, policy = _p1d_case(client, did)
    before = _p1d_snapshot(db, did)
    token = policy['configDigest']
    assert isinstance(token, str) and len(token) == 70 and token.startswith('cfgd1:')
    for interval in (17, 23):
        response = client.patch(url, json={'intervalMinutes': interval, 'expectedConfigDigest': token})
        assert response.status_code == 200
        data = response.get_json()['data']
        assert data['intervalMinutes'] == interval
        new_token = data.get('configDigest')
        assert isinstance(new_token, str) and len(new_token) == 70
        assert new_token != token
        raw = db.read_project_status_update_policy_snapshot(did)
        assert new_token == _p1d_digest(did, raw['binding'], raw['authorities'])
        token = new_token
    after = _p1d_snapshot(db, did)
    assert len(after[2]) == len(before[2]) + 2
    assert after[3] == before[3]

# ── 开关关闭时的回滚 PATCH（停用/调间隔不改写存量规则） ─────────────────────


def _raw_match_rule(db) -> str:  # type: ignore[no-untyped-def]
    with db.get_connection() as conn:
        return str(
            conn.execute(
                "SELECT match_rule_json FROM project_status_update_bindings "
                "WHERE deliverable_id='VPI-T2-D5'"
            ).fetchone()["match_rule_json"]
        )


def _enable_multi_serial_binding(client, monkeypatch):  # type: ignore[no-untyped-def]
    """开关开启时落一条启用中的多单号绑定，返回 (db, match_rule_json 原文)。"""
    import json

    monkeypatch.setenv("VSE_TDC_MULTI_SERIAL_SYNC", "1")
    db = web_app.DatabaseManager()
    rule = {"reportType": "data_model", "aggregate": True, "documentNos": ["3D-1", "3D-2"]}
    report = {
        "fields": ["currentApprover", "incident", "reportType"],
        "statusOrApprovalFields": [],
        "suggestedStatusMapping": [],
        "suggestedAutomaticFields": [],
        "requiresConfirmation": True,
    }
    signature = compute_config_signature("tdc", rule)
    for _ in range(2):
        db.record_mapping_observation(
            deliverable_id="VPI-T2-D5",
            source_type="tdc",
            result_state="matched",
            external_key=None,
            candidate_fingerprint="agg:members-3d-1-3d-2",
            candidate_count=2,
            candidate_summary_json=json.dumps(
                [{"externalKey": "FLOW-A", "fields": {}}, {"externalKey": "FLOW-B", "fields": {}}]
            ),
            field_report_json=json.dumps(report),
            config_signature=signature,
        )
    response = client.patch(
        _D5_POLICY_URL,
        json={
            "mode": "hybrid",
            "enabled": True,
            "externalKey": None,
            "matchRule": rule,
            "mapping": {"owner": "currentApprover"},
            "fieldAuthority": {"owner": "automatic"},
            "credentialRef": "test-credential-ref",
        },
    )
    assert response.status_code == 200, response.get_json()
    return db, _raw_match_rule(db)


def test_flag_off_allows_disabling_existing_multi_serial_binding(client, monkeypatch) -> None:
    """回滚可执行：开关关闭后仍能把存量多单号绑定停用，且不改写规则。"""
    db, raw_before = _enable_multi_serial_binding(client, monkeypatch)
    monkeypatch.delenv("VSE_TDC_MULTI_SERIAL_SYNC", raising=False)

    response = client.patch(_D5_POLICY_URL, json={"enabled": False})

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["data"]["enabled"] is False
    assert _raw_match_rule(db) == raw_before
    assert db.get_sync_binding_by_deliverable("VPI-T2-D5")["enabled"] == 0


def test_flag_off_allows_interval_patch_without_rewriting_rule(client, monkeypatch) -> None:
    """开关关闭后仍可调同步间隔；存量规则逐字保留。"""
    db, raw_before = _enable_multi_serial_binding(client, monkeypatch)
    monkeypatch.delenv("VSE_TDC_MULTI_SERIAL_SYNC", raising=False)

    response = client.patch(_D5_POLICY_URL, json={"intervalMinutes": 30})

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["data"]["intervalMinutes"] == 30
    assert _raw_match_rule(db) == raw_before


def test_flag_off_still_rejects_reenabling_multi_serial_binding(client, monkeypatch) -> None:
    """开关关闭时不允许把含 documentNos 的绑定重新置为 enabled。"""
    _db, _raw = _enable_multi_serial_binding(client, monkeypatch)
    monkeypatch.delenv("VSE_TDC_MULTI_SERIAL_SYNC", raising=False)
    assert client.patch(_D5_POLICY_URL, json={"enabled": False}).status_code == 200

    response = client.patch(_D5_POLICY_URL, json={"enabled": True})

    assert response.status_code == 422
    fields = response.get_json()["error"]["fields"]
    assert "matchRule" in fields or "enabled" in fields
