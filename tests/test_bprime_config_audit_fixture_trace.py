def test_bprime_fixture_trace_contract(bprime_audit_case):
    import json
    import sqlite3
    import pytest
    from tests.conftest import trace

    case = bprime_audit_case
    db = case["db"]
    assert set(case) == {"db", "service", "deliverable_id", "revision",
                         "snapshot", "audit_rows"}
    assert (case["deliverable_id"], case["revision"]) == ("VPI-T2-D5", 7)
    absent = object()
    name = "record_deliverable_config_audit"
    get_slot = db.__dict__.get("get_connection", absent)
    rec_slot = db.__dict__.get(name, absent)
    original_get = db.get_connection
    original_rec = getattr(db, name, absent)
    present = original_rec is not absent

    def restored():
        assert db.__dict__.get("get_connection", absent) is get_slot
        assert db.__dict__.get(name, absent) is rec_slot
        assert db.get_connection == original_get
        assert getattr(db, name, absent) == original_rec

    def checked(observed):
        assert observed["recorder_present"] is present
        assert observed["recorder_wrapped"] is callable(original_rec)
        assert observed["recorder_calls"] == []
        events = observed["events"]
        assert [event["seq"] for event in events] == list(range(len(events)))
        for item in observed["connections"]:
            assert isinstance(item["conn"], sqlite3.Connection)
            assert item["closed"] is True
            assert isinstance(item["total_changes_before"], int)
            assert isinstance(item["total_changes_after"], int)
            assert item["open_seq"] < item["exit_seq"]
            assert all(event["conn"] is item["conn"] and
                       item["open_seq"] < event["seq"] < item["exit_seq"]
                       for event in item["sql"])

    with trace(db, "baseline") as baseline:
        assert db.get_connection is not original_get
        if callable(original_rec):
            assert getattr(db, name) is not original_rec
        else:
            assert getattr(db, name, absent) is original_rec
        first = case["snapshot"]()
        assert case["audit_rows"]() == first["dedicated_audit"]
    restored()
    checked(baseline)
    assert baseline["label"] == "baseline" and baseline["connections"]
    assert set(first) == {"binding", "authorities", "analysis_snapshots",
                          "analysis_items", "dedicated_audit", "business_audit",
                          "archive_config_audit", "archive_jobs"}
    assert all(isinstance(value, list) for value in first.values())
    assert len(first["binding"]) == 1
    binding = first["binding"][0]
    assert (binding["mode"], binding["enabled"], binding["source_type"]) == ("hybrid", 0, "tdc")
    assert binding["deliverable_id"] == case["deliverable_id"]
    assert binding["external_key"] == "BPRIME-EXT-7"
    assert binding["sync_config_revision"] == 7
    assert json.loads(binding["mapping_json"]) and json.loads(binding["cursor_json"])
    fixed = "2026-01-05 09:00:00"
    assert binding["updated_at"] == fixed
    owners = [row for row in first["authorities"] if row["field_name"] == "owner"]
    assert len(owners) == 1
    assert (owners[0]["authority"], owners[0]["source_type"]) == ("manual", "tdc")
    assert owners[0]["locked_at"] == owners[0]["updated_at"] == fixed
    assert first["analysis_snapshots"] and first["analysis_items"]
    assert ("VPI-T2-D5", "sync_now", "skipped", fixed) in {
        (row["deliverable_id"], row["trigger_type"], row["result"], row["created_at"])
        for row in first["business_audit"]}
    assert all(row["deliverable_id"] == case["deliverable_id"] for row in first["dedicated_audit"])
    for item in baseline["connections"]:
        assert item["total_changes_after"] == item["total_changes_before"]
        assert all(event["sql"].lstrip().split(None, 1)[0].upper() not in
                   {"INSERT", "UPDATE", "DELETE", "REPLACE"} for event in item["sql"])

    update = "UPDATE project_status_update_bindings SET external_key = ? WHERE deliverable_id = ?"
    with trace(db, "probe") as probe:
        with db.get_connection() as conn:
            item = probe["connections"][0]
            assert item["conn"] is conn and not conn.in_transaction
            conn.execute("BEGIN IMMEDIATE")
            assert conn.in_transaction
            conn.execute(update, ("TRACE-PROBE", case["deliverable_id"]))
            assert conn.execute("SELECT 41").fetchone()[0] == 41
            assert conn.total_changes == item["total_changes_before"] + 1
            conn.rollback()
            assert not conn.in_transaction
    restored()
    checked(probe)
    assert probe["label"] == "probe" and len(probe["connections"]) == 1
    item = probe["connections"][0]
    assert item["in_transaction_before"] is False
    assert item["in_transaction_after_body"] is False
    assert item["total_changes_after"] == item["total_changes_before"] + 1
    assert [event["sql"].split()[0].upper() for event in item["sql"]] == ["BEGIN", "UPDATE", "SELECT", "ROLLBACK"]
    assert "TRACE-PROBE" in item["sql"][1]["sql"]
    assert [event["in_transaction"] for event in item["sql"]] == [False, True, True, True]
    assert case["snapshot"]() == first

    sentinel = RuntimeError("TRACE-SYNTHETIC-ERROR")
    with pytest.raises(RuntimeError) as caught:
        with trace(db, "exception_probe") as failure:
            with db.get_connection() as conn:
                assert failure["connections"][0]["conn"] is conn
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(update, ("TRACE-ERROR", case["deliverable_id"]))
                raise sentinel
    assert caught.value is sentinel
    restored()
    checked(failure)
    assert failure["label"] == "exception_probe" and len(failure["connections"]) == 1
    item = failure["connections"][0]
    assert item["in_transaction_after_body"] is True
    assert item["total_changes_after"] == item["total_changes_before"] + 1
    assert [event["sql"].split()[0].upper() for event in item["sql"]] == ["BEGIN", "UPDATE", "ROLLBACK"]
    assert [event["in_transaction"] for event in item["sql"]] == [False, True, True]
    logs = (baseline, probe, failure)
    counts = [len(observed["events"]) for observed in logs]
    assert case["snapshot"]() == first
    assert case["audit_rows"]() == first["dedicated_audit"]
    assert [len(observed["events"]) for observed in logs] == counts
    restored()
