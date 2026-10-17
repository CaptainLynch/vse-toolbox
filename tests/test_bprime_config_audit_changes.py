def pytest_generate_tests(metafunc):
    if metafunc.function.__name__ == "test_policy_audit_single_change":
        names = ("external_key", "mapping", "field_authority")
        metafunc.parametrize("change", names, ids=names)


def test_policy_audit_single_change(bprime_audit_case, change):
    import json
    from tests.conftest import trace

    case = bprime_audit_case
    db, service = case["db"], case["service"]
    deliverable_id = case["deliverable_id"]
    policy = service._policy_to_api(db.get_project_status_update_policy(deliverable_id))
    before = case["snapshot"]()
    assert len(before["binding"]) == 1
    binding = before["binding"][0]
    assert binding["sync_config_revision"] == case["revision"] == 7
    assert (binding["mode"], binding["enabled"]) == ("hybrid", 0)
    assert case["audit_rows"]() == before["dedicated_audit"]
    old_mapping = json.loads(binding["mapping_json"])
    old_authority = dict(policy["fieldAuthority"])
    old_rows = {row["field_name"]: row for row in before["authorities"]}
    assert old_authority["owner"] == old_rows["owner"]["authority"] == "manual"
    assert old_rows["owner"]["locked_at"]
    expected_external = binding["external_key"]
    expected_mapping, expected_authority = dict(old_mapping), dict(old_authority)
    if change == "external_key":
        field, old, new = "externalKey", binding["external_key"], "SYNTHETIC_MARKER_1"
        expected_external = new
    elif change == "mapping":
        field, old = "mapping", old_mapping
        new = dict(old_mapping, owner="SYNTHETIC_MARKER_1")
        expected_mapping = new
    else:
        assert change == "field_authority"
        field, old = "fieldAuthority", old_authority
        new = dict(old_authority, owner="automatic")
        expected_authority = new
    assert old != new
    with trace(db, "save") as observed:
        result = service.update_update_policy(deliverable_id, {field: new})
    after = case["snapshot"]()
    saved = after["binding"][0]
    rows = case["audit_rows"]()
    assert rows == after["dedicated_audit"]
    assert len(rows) == len(before["dedicated_audit"]) + 1
    assert rows[:-1] == before["dedicated_audit"]
    audit = rows[-1]
    expected_revision = case["revision"] + (change != "field_authority")
    assert saved["sync_config_revision"] == audit["config_revision"] == expected_revision
    assert saved["external_key"] == result["externalKey"] == expected_external
    assert json.loads(saved["mapping_json"]) == result["mapping"] == expected_mapping
    new_rows = {row["field_name"]: row for row in after["authorities"]}
    assert set(new_rows) == set(old_rows)
    assert result["fieldAuthority"] == expected_authority
    assert {name: row["authority"] for name, row in new_rows.items()} == {
        name: ("automatic" if change == "field_authority" and name == "owner"
               else row["authority"]) for name, row in old_rows.items()}
    if change == "field_authority":
        assert new_rows["owner"]["locked_at"] is None
        assert new_rows["owner"]["source_type"] == old_rows["owner"]["source_type"]
        assert all(new_rows[name] == row for name, row in old_rows.items() if name != "owner")
        assert saved["cursor_json"] == binding["cursor_json"]
        assert after["analysis_snapshots"] == before["analysis_snapshots"]
        assert after["analysis_items"] == before["analysis_items"]
    else:
        assert after["authorities"] == before["authorities"]
    for name in ("mode", "enabled", "source_type", "match_rule_json"):
        assert saved[name] == binding[name]
    for name in ("business_audit", "archive_config_audit", "archive_jobs"):
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
        "changes": {field: {"from": old, "to": new, "changed": True}}}
    assert observed["label"] == "save"
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
