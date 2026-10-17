def test_policy_audit_without_archive_job(bprime_audit_case):
    import json
    from tests.conftest import trace

    case = bprime_audit_case
    db, service = case["db"], case["service"]
    deliverable_id = case["deliverable_id"]
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE scheduled_archive_jobs SET project_status_deliverable_id = NULL "
            "WHERE project_status_deliverable_id = ?", (deliverable_id,))
        count = conn.execute(
            "SELECT COUNT(*) FROM scheduled_archive_jobs "
            "WHERE project_status_deliverable_id = ?", (deliverable_id,)).fetchone()[0]
        assert count == 0

    def archive_and_existing_audits():
        with db.get_connection() as conn:
            return [[tuple(row) for row in conn.execute(sql)] for sql in (
                "SELECT * FROM scheduled_archive_jobs ORDER BY id",
                "SELECT * FROM scheduled_archive_config_audit ORDER BY id",
                "SELECT * FROM project_status_update_audit ORDER BY id")]

    baseline = archive_and_existing_audits()
    before = case["snapshot"]()
    assert len(before["binding"]) == 1
    binding = before["binding"][0]
    assert binding["sync_config_revision"] == case["revision"] == 7
    assert (binding["mode"], binding["enabled"]) == ("hybrid", 0)
    assert before["archive_jobs"] == []
    assert case["audit_rows"]() == before["dedicated_audit"]
    old, new = binding["external_key"], "SYNTHETIC_MARKER_1"
    assert old != new
    with trace(db, "save") as observed:
        result = service.update_update_policy(deliverable_id, {"externalKey": new})
    after = case["snapshot"]()
    assert len(after["binding"]) == 1
    saved = after["binding"][0]
    rows = case["audit_rows"]()
    assert rows == after["dedicated_audit"]
    assert len(rows) == len(before["dedicated_audit"]) + 1
    assert rows[:-1] == before["dedicated_audit"]
    audit = rows[-1]
    expected_revision = case["revision"] + 1
    assert saved["sync_config_revision"] == audit["config_revision"] == expected_revision
    assert saved["external_key"] == result["externalKey"] == new
    for name in ("mode", "enabled", "source_type", "mapping_json", "match_rule_json"):
        assert saved[name] == binding[name]
    assert after["authorities"] == before["authorities"]
    assert archive_and_existing_audits() == baseline
    for name in ("archive_jobs", "archive_config_audit", "business_audit"):
        assert after[name] == before[name]
    assert set(audit) == {"id", "deliverable_id", "actor", "event_type",
                          "config_revision", "changes_json", "created_at"}
    assert audit["deliverable_id"] == deliverable_id
    assert audit["actor"] in {"local_web", "cli"}
    assert audit["event_type"] == "configuration_updated"
    assert isinstance(audit["created_at"], str) and audit["created_at"]
    assert json.loads(audit["changes_json"]) == {
        "payloadVersion": 1, "source": "deliverable_sync_settings",
        "deliverableId": deliverable_id, "beforeRevision": case["revision"],
        "afterRevision": expected_revision, "scope": None,
        "changes": {"externalKey": {"from": old, "to": new, "changed": True}}}
    assert observed["label"] == "save"
    assert observed["recorder_present"] and observed["recorder_wrapped"]
    assert len(observed["recorder_calls"]) == 1
    call = observed["recorder_calls"][0]
    assert call["conn"] is not None and call["in_transaction"] is True
    writes = [item for item in observed["connections"] if any(
        event["sql"].lstrip().split(None, 1)[0].upper() in
        {"INSERT", "UPDATE", "DELETE", "REPLACE"} for event in item["sql"])]
    assert writes and all(item["conn"] is call["conn"] for item in writes)
    inside = [event for event in observed["events"] if event["kind"] == "sql"
              and event["conn"] is call["conn"]
              and call["start_seq"] < event["seq"] < call["end_seq"]]
    assert inside
    assert all(event["sql"].lstrip().split(None, 1)[0].upper() not in
               {"COMMIT", "ROLLBACK"} for event in inside)
    assert all(item["closed"] for item in observed["connections"])
