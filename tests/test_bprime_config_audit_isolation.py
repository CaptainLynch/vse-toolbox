def test_policy_no_difference_zero_writes(bprime_audit_case):
    import json
    from tests.conftest import trace

    case = bprime_audit_case
    db, service = case["db"], case["service"]
    deliverable_id = case["deliverable_id"]
    with db.get_connection() as conn:
        mapping = json.loads(case["snapshot"](conn)["binding"][0]["mapping_json"])
        mapping["plannedDate"] = "SYNTHETIC_MARKER_1"
        conn.execute(
            "UPDATE project_status_update_bindings SET mapping_json = ? WHERE deliverable_id = ?",
            (json.dumps(mapping), deliverable_id))
    policy = service._policy_to_api(db.get_project_status_update_policy(deliverable_id))
    before = case["snapshot"]()
    binding = before["binding"][0]
    assert binding["sync_config_revision"] == case["revision"] == 7
    assert json.loads(binding["cursor_json"])
    assert before["analysis_snapshots"]
    assert before["analysis_items"]
    owners = [row for row in before["authorities"] if row["field_name"] == "owner"]
    assert len(owners) == 1
    assert owners[0]["authority"] == "manual"
    assert owners[0]["locked_at"]
    payload = {name: policy[name] for name in (
        "mode", "enabled", "externalKey", "matchRule", "mapping", "fieldAuthority",
        "intervalMinutes")}
    payload["credentialRef"] = binding["credential_ref"]
    payload["mapping"] = dict(reversed(list(mapping.items())))
    assert list(payload["mapping"]) != list(mapping)
    assert payload["mapping"] == mapping
    with trace(db, "save") as observed:
        result = service.update_update_policy(deliverable_id, payload)
    assert result == policy
    after = case["snapshot"]()
    assert set(after) == set(before)
    for section in before:
        assert after[section] == before[section], section
    assert case["audit_rows"]() == before["dedicated_audit"]
    assert observed["recorder_calls"] == []
    assert observed["connections"]
    for item in observed["connections"]:
        assert item["total_changes_after"] == item["total_changes_before"]
        assert item["closed"]
        for event in item["sql"]:
            assert event["sql"].lstrip().split(None, 1)[0].upper() not in {
                "INSERT", "UPDATE", "DELETE", "REPLACE"}


def test_policy_concurrent_before_state_is_current(bprime_audit_case):
    import json
    import pytest
    from threading import Event, Thread
    from tests.conftest import trace
    from core.db_common import ProjectStatusConcurrentUpdateError

    case = bprime_audit_case
    db, deliverable_id = case["db"], case["deliverable_id"]
    p0 = case["snapshot"]()
    binding = p0["binding"][0]
    assert binding["sync_config_revision"] == case["revision"] == 7
    authority = {row["field_name"]: row["authority"] for row in p0["authorities"]}
    assert authority["owner"] == "manual"
    request = dict(mode=binding["mode"], enabled=bool(binding["enabled"]),
                   external_key=binding["external_key"], match_rule_json=binding["match_rule_json"],
                   mapping_json=binding["mapping_json"], field_authority=authority,
                   credential_ref=binding["credential_ref"], interval_minutes=binding["interval_minutes"])
    begun, errors, results = Event(), [], []

    class Events(list):
        def append(self, event):
            super().append(event)
            if event["kind"] == "sql" and event["sql"].strip().upper() == "BEGIN IMMEDIATE":
                begun.set()

    def save():
        try:
            results.append(db.set_project_status_update_policy(
                deliverable_id, **request, expected_sync_config_revision=None))
        except BaseException as exc:
            errors.append(exc)

    with db.get_connection() as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute(
            "UPDATE project_status_update_bindings SET external_key = ?, sync_config_revision = ? "
            "WHERE deliverable_id = ?", ("SYNTHETIC_MARKER_1", case["revision"] + 1, deliverable_id))
        writer.execute(
            "UPDATE project_status_field_authority SET authority = 'automatic', locked_at = NULL "
            "WHERE deliverable_id = ? AND field_name = 'owner'", (deliverable_id,))
        p1 = case["snapshot"](writer)
        assert p1["binding"][0]["external_key"] != request["external_key"]
        assert p1["binding"][0]["sync_config_revision"] == case["revision"] + 1
        with trace(db, "concurrent") as observed:
            observed["events"] = Events()
            thread = Thread(target=save, daemon=True)
            thread.start()
            try:
                entered = begun.wait(5)
                if entered:
                    assert writer.in_transaction
                    assert len(observed["connections"]) == 1
                    assert observed["connections"][0]["conn"] is not writer
                    writer.commit()
            finally:
                try:
                    writer.rollback()
                finally:
                    thread.join(15)
            assert not thread.is_alive()
            if errors:
                raise errors[0]
            assert entered
        assert all(item["closed"] for item in observed["connections"])
    after = case["snapshot"]()
    assert results == [case["revision"] + 2]
    assert after["binding"][0]["sync_config_revision"] == case["revision"] + 2
    assert after["binding"][0]["external_key"] == request["external_key"]
    current = {row["field_name"]: row["authority"] for row in after["authorities"]}
    assert current == authority
    rows = case["audit_rows"]()
    assert len(rows) == len(p0["dedicated_audit"]) + 1
    assert rows[:-1] == p0["dedicated_audit"]
    p1_authority = {row["field_name"]: row["authority"] for row in p1["authorities"]}
    assert p1_authority["owner"] == "automatic"
    assert json.loads(rows[-1]["changes_json"]) == {
        "payloadVersion": 1, "source": "deliverable_sync_settings", "deliverableId": deliverable_id,
        "beforeRevision": case["revision"] + 1, "afterRevision": case["revision"] + 2, "scope": None,
        "changes": {
            "externalKey": {"from": "SYNTHETIC_MARKER_1", "to": request["external_key"], "changed": True},
            "fieldAuthority": {"from": p1_authority, "to": authority, "changed": True}}}
    assert rows[-1]["config_revision"] == case["revision"] + 2
    assert len(observed["recorder_calls"]) == 1
    call = observed["recorder_calls"][0]
    assert call["conn"] is observed["connections"][0]["conn"]
    assert call["in_transaction"] is True
    with pytest.raises(ProjectStatusConcurrentUpdateError):
        db.set_project_status_update_policy(
            deliverable_id, **request, expected_sync_config_revision=case["revision"])
    assert case["snapshot"]() == after
    assert case["audit_rows"]() == rows
