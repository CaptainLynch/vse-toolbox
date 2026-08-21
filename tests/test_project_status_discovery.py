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


def test_zero_ambiguous_and_key_change_reset_stability(tmp_path):
    db = DatabaseManager(tmp_path / "db.sqlite")
    db.init_database()
    service = MappingDiscoveryService(db)
    assert service.observe("VPI-T2-D5", "tdc", [])["state"] == "not_found"
    ambiguous = service.observe(
        "VPI-T2-D5", "tdc", [{"incident": "A"}, {"incident": "B"}]
    )
    assert ambiguous["state"] == "ambiguous"
    assert ambiguous["stability"]["confirmed"] == 0
    assert service.observe("VPI-T2-D5", "tdc", [{"incident": "A"}])["state"] == "matched"
    changed = service.observe("VPI-T2-D5", "tdc", [{"incident": "B"}])
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
