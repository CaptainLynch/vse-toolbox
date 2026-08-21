# -*- coding: utf-8 -*-
"""ProjectStatusUpdateService focused contracts for the VPI-T2-D5 pilot."""

from __future__ import annotations

import pytest

from core.db_manager import DatabaseManager
from services.project_status_updates import (
    PROJECT_STATUS_EDITABLE_FIELDS,
    ProjectStatusPolicyError,
    ProjectStatusUpdateService,
)


@pytest.fixture()
def service(tmp_db: DatabaseManager) -> ProjectStatusUpdateService:
    return ProjectStatusUpdateService(tmp_db)


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
    assert policy["mode"] == "manual"
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

    policy = service.update_update_policy(
        "VPI-T2-D5",
        {
            "mode": "hybrid",
            "enabled": True,
            "externalKey": "FM-1",
            "matchRule": {"incident": "FM-1"},
            "mapping": {"owner": "currentApprover"},
        },
    )
    assert policy["enabled"] is True
    assert policy["externalKey"] == "FM-1"
    assert policy["matchRule"] == {"incident": "FM-1"}


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


def test_policy_restricts_automation_to_pilot(service) -> None:
    with pytest.raises(ProjectStatusPolicyError) as exc:
        service.update_update_policy("VPI-T2-D3", {"mode": "hybrid"})
    assert "mode" in exc.value.fields

    with pytest.raises(ProjectStatusPolicyError) as exc:
        service.update_update_policy(
            "VPI-T2-D3",
            {
                "enabled": True,
                "externalKey": "k",
                "matchRule": {"incident": "x"},
            },
        )
    assert "enabled" in exc.value.fields

    with pytest.raises(ProjectStatusPolicyError) as exc:
        service.update_update_policy(
            "VPI-T2-D3",
            {"fieldAuthority": {"status": "automatic"}},
        )
    assert "fieldAuthority" in exc.value.fields


def test_manual_mode_rejects_automatic_field_authority(service) -> None:
    with pytest.raises(ProjectStatusPolicyError) as exc:
        service.update_update_policy(
            "VPI-T2-D5",
            {"mode": "manual", "fieldAuthority": {"status": "automatic"}},
        )
    assert "fieldAuthority" in exc.value.fields
