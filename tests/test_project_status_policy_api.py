# -*- coding: utf-8 -*-
"""API contracts for project-status update policy and audit endpoints."""

from __future__ import annotations

import pytest

import web.app as web_app
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
        for field in capabilities["matchFields"]:
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
