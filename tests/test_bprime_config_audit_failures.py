def pytest_generate_tests(metafunc):
    if metafunc.function.__name__ == "test_recorder_failure_rolls_back_all_related_state":
        names = ("missing", "raises", "false", "true_without_insert")
        metafunc.parametrize("failure", names, ids=names)


def test_recorder_failure_rolls_back_all_related_state(bprime_audit_case, monkeypatch, failure):
    import json
    import pytest
    from tests.conftest import trace

    case = bprime_audit_case
    db, service = case["db"], case["service"]
    deliverable_id = case["deliverable_id"]
    policy = service._policy_to_api(db.get_project_status_update_policy(deliverable_id))
    before = case["snapshot"]()
    assert len(before["binding"]) == 1
    binding = before["binding"][0]
    assert (binding["mode"], binding["enabled"]) == ("hybrid", 0)
    assert binding["sync_config_revision"] == case["revision"] == 7
    assert binding["updated_at"] and json.loads(binding["cursor_json"])
    owners = [row for row in before["authorities"] if row["field_name"] == "owner"]
    assert len(owners) == 1
    assert owners[0]["authority"] == "manual"
    assert owners[0]["locked_at"]
    assert owners[0]["updated_at"]
    assert before["analysis_snapshots"] and before["analysis_items"]
    assert case["audit_rows"]() == before["dedicated_audit"]
    old_mapping = json.loads(binding["mapping_json"])
    old_authority = dict(policy["fieldAuthority"])
    assert old_mapping and old_authority["owner"] == "manual"
    new_mapping = dict(old_mapping, owner="SYNTHETIC_MARKER_1")
    new_authority = dict(old_authority, owner="automatic")
    target = {"mode": "hybrid", "enabled": False, "externalKey": "SYNTHETIC_MARKER_1",
              "mapping": new_mapping, "fieldAuthority": new_authority}
    assert binding["external_key"] != target["externalKey"]
    assert old_mapping != new_mapping
    expected = {
        "payloadVersion": 2, "source": "deliverable_sync_settings", "deliverableId": deliverable_id,
        "beforeRevision": case["revision"], "afterRevision": case["revision"] + 1, "scope": None,
        "changes": {
            "externalKey": {"from": binding["external_key"], "to": target["externalKey"], "changed": True},
            "mapping": {"from": old_mapping, "to": new_mapping, "changed": True},
            "fieldAuthority": {"from": old_authority, "to": new_authority, "changed": True}}}
    sentinel = ValueError("<cookie>SYNTHETIC_MARKER_1</cookie>")

    def recorder(deliverable_id, changes, actor="local_web", *, conn):
        assert deliverable_id == case["deliverable_id"]
        assert changes == expected
        assert actor in {"local_web", "cli"} and conn.in_transaction
        candidate = case["snapshot"](conn)
        assert len(candidate["binding"]) == 1
        saved = candidate["binding"][0]
        assert saved["external_key"] == target["externalKey"]
        assert json.loads(saved["mapping_json"]) == new_mapping
        assert (saved["mode"], saved["enabled"]) == ("hybrid", 0)
        assert saved["sync_config_revision"] == case["revision"] + 1
        assert json.loads(saved["cursor_json"]) == {}
        current = [row for row in candidate["authorities"] if row["field_name"] == "owner"]
        assert len(current) == 1
        assert current[0]["authority"] == "automatic"
        assert current[0]["locked_at"] is None
        assert current[0]["source_type"] == owners[0]["source_type"]
        assert candidate["analysis_snapshots"] == []
        assert candidate["analysis_items"] == []
        assert candidate["dedicated_audit"] == before["dedicated_audit"]
        if failure == "true_without_insert":
            return True
        conn.execute(
            "INSERT INTO project_status_binding_config_audit "
            "(deliverable_id, actor, event_type, config_revision, changes_json) VALUES (?, ?, ?, ?, ?)",
            (deliverable_id, actor, "configuration_updated", case["revision"] + 1, json.dumps(expected)))
        inserted = case["audit_rows"](conn)
        assert len(inserted) == len(before["dedicated_audit"]) + 1
        assert inserted[:-1] == before["dedicated_audit"]
        if failure == "raises":
            raise sentinel
        assert failure == "false"
        return False

    name = "record_deliverable_config_audit"
    monkeypatch.setattr(db, name, None if failure == "missing" else recorder)
    with trace(db, "save") as observed:
        with pytest.raises(RuntimeError) as caught:
            service.update_update_policy(deliverable_id, target)
    assert type(caught.value).__name__ == "BindingConfigAuditError"
    assert "SYNTHETIC_MARKER_1" not in str(caught.value)
    assert observed["label"] == "save"
    assert observed["recorder_present"] is True
    calls = observed["recorder_calls"]
    writes = [event for event in observed["events"] if event["kind"] == "sql"
              and event["sql"].lstrip().split(None, 1)[0].upper() in
              {"INSERT", "UPDATE", "DELETE", "REPLACE"}]
    if failure == "missing":
        assert calls == [] and observed["recorder_wrapped"] is False
        assert len({id(event["conn"]) for event in writes}) <= 1
    else:
        assert observed["recorder_wrapped"] is True
        assert len(calls) == 1
        call = calls[0]
        assert call["conn"] is not None and call["in_transaction"] is True
        assert writes and all(event["conn"] is call["conn"] for event in writes)
        assert any(event["seq"] < call["start_seq"] for event in writes)
        inside = [event for event in observed["events"] if event["kind"] == "sql"
                  and event["conn"] is call["conn"]
                  and call["start_seq"] < event["seq"] < call["end_seq"]]
        assert inside and all(event["sql"].lstrip().split(None, 1)[0].upper() not in
                              {"COMMIT", "ROLLBACK"} for event in inside)
        inserts = [event for event in inside if event["sql"].lstrip().upper().startswith(
            "INSERT INTO PROJECT_STATUS_BINDING_CONFIG_AUDIT")]
        assert len(inserts) == (failure != "true_without_insert")
        if failure == "raises":
            assert call["exception"] is sentinel and caught.value.__cause__ is sentinel
        else:
            assert "exception" not in call
            assert call["result"] is (failure == "true_without_insert")
    assert all(item["closed"] for item in observed["connections"])
    with db.get_connection() as independent:
        assert all(independent is not item["conn"] for item in observed["connections"])
        after = case["snapshot"](independent)
        assert case["audit_rows"](independent) == before["dedicated_audit"]
    assert set(after) == set(before)
    for section in before:
        assert after[section] == before[section], section
    assert after["binding"][0]["sync_config_revision"] == case["revision"]
    assert after["binding"][0]["cursor_json"] == binding["cursor_json"]
    assert after["analysis_snapshots"] and after["analysis_items"]
