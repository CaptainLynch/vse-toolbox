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


def test_policy_patch_enables_pilot_and_persists(client) -> None:  # type: ignore[no-untyped-def]
    payload = {
        "mode": "hybrid",
        "enabled": True,
        "externalKey": "FM-1",
        "matchRule": {"incident": "FM-1"},
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
    assert data["matchRule"] == {"incident": "FM-1"}
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
        ({"mode": "manual", "enabled": True, "externalKey": "k", "matchRule": {"incident": "k"}}, "enabled"),
        ({"sourceType": "feishu"}, "request"),
        ({"mode": "scheduled"}, "mode"),
    ],
)
def test_policy_patch_rejects_invalid_configuration(client, payload, field) -> None:  # type: ignore[no-untyped-def]
    response = client.patch(
        "/api/project-status/deliverables/VPI-T2-D5/update-policy",
        json=payload,
    )
    assert response.status_code == 422
    assert field in response.get_json()["error"]["fields"]


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
