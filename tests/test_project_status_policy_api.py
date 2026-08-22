# -*- coding: utf-8 -*-
"""API contracts for project-status update policy and audit endpoints."""

from __future__ import annotations

import pytest

import web.app as web_app


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
    assert policy["mode"] == "manual"
    assert policy["sourceType"] == "tdc"
    assert policy["enabled"] is False
    assert policy["externalKey"] is None
    assert policy["matchRule"] == {}
    assert all(value == "manual" for value in policy["fieldAuthority"].values())

    status = _status(client)
    summary = next(
        item["updatePolicy"] for item in status["deliverables"] if item["id"] == "VPI-T2-D5"
    )
    assert summary["mode"] == "manual"
    assert summary["sourceType"] == "tdc"
    assert summary["enabled"] is False
    assert summary["syncState"] == "idle"


def _record_two_observations(
    client,
    deliverable_id: str = "VPI-T2-D5",
    source_type: str = "tdc",
    external_key: str = "FM-1",
    fields: list[str] | None = None,
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
