# -*- coding: utf-8 -*-
from __future__ import annotations

from core.db_manager import DatabaseManager
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
