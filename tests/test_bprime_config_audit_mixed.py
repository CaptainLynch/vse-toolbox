def test_policy_audit_mixed_sanitized(bprime_audit_case):
    import json
    from tests.conftest import trace
    from core.redaction import redact_sensitive_text
    from services.project_status_updates import PROJECT_STATUS_SYNC_CONTRACTS

    case = bprime_audit_case
    db, service = case["db"], case["service"]
    deliverable_id = case["deliverable_id"]
    policy = service._policy_to_api(db.get_project_status_update_policy(deliverable_id))
    rule_fields = set(PROJECT_STATUS_SYNC_CONTRACTS[deliverable_id]["matchKeys"])
    rule_fields -= {"reportType", "aggregate", "sectionScope", "contractVersion",
                    "bindingMode", "sourceItemId"}
    rule_field = sorted(rule_fields)[0]
    markers = ("SYNTHETIC_MARKER_1", "SYNTHETIC_MARKER_2")
    old_text, new_text = (f"<cookie>{marker}</cookie>" for marker in markers)
    masked = "<cookie>[redacted]</cookie>"
    assert old_text != new_text
    assert redact_sensitive_text(old_text) == redact_sensitive_text(new_text) == masked
    old_rule = dict(policy["matchRule"])
    old_rule[rule_field] = old_text
    new_rule = dict(old_rule)
    new_rule[rule_field] = new_text
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET match_rule_json = ? "
            "WHERE deliverable_id = ?", (json.dumps(old_rule), deliverable_id))
        conn.commit()
    before = case["snapshot"]()
    assert len(before["binding"]) == 1
    binding = before["binding"][0]
    assert binding["sync_config_revision"] == case["revision"] == 7
    assert (binding["mode"], binding["enabled"]) == ("hybrid", 0)
    assert json.loads(binding["match_rule_json"]) == old_rule
    assert case["audit_rows"]() == before["dedicated_audit"]
    old_rows = {row["field_name"]: row for row in before["authorities"]}
    old_authority = dict(policy["fieldAuthority"])
    assert old_authority["owner"] == old_rows["owner"]["authority"] == "manual"
    assert old_rows["owner"]["locked_at"]
    old_mapping = json.loads(binding["mapping_json"])
    new_mapping = dict(old_mapping, owner=new_text)
    new_authority = dict(old_authority, owner="automatic")
    old_values = {"externalKey": binding["external_key"], "mapping": old_mapping,
                  "fieldAuthority": old_authority, "matchRule": old_rule}
    target = {"externalKey": new_text, "mapping": new_mapping,
              "fieldAuthority": new_authority, "matchRule": new_rule}
    assert all(old_values[name] != target[name] for name in target)
    with trace(db, "save") as observed:
        result = service.update_update_policy(deliverable_id, target)
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
    assert saved["external_key"] == result["externalKey"] == new_text
    assert json.loads(saved["mapping_json"]) == result["mapping"] == new_mapping
    assert json.loads(saved["match_rule_json"]) == result["matchRule"] == new_rule
    assert result["fieldAuthority"] == new_authority
    new_rows = {row["field_name"]: row for row in after["authorities"]}
    assert set(new_rows) == set(old_rows)
    assert {name: row["authority"] for name, row in new_rows.items()} == {
        name: new_authority.get(name, row["authority"]) for name, row in old_rows.items()}
    assert new_rows["owner"]["locked_at"] is None
    assert new_rows["owner"]["source_type"] == old_rows["owner"]["source_type"]
    assert all(new_rows[name] == row for name, row in old_rows.items() if name != "owner")
    for name in ("mode", "enabled", "source_type"):
        assert saved[name] == binding[name]
    for name in ("business_audit", "archive_config_audit", "archive_jobs"):
        assert after[name] == before[name]
    sanitized_rule = dict(old_rule, **{rule_field: masked})
    expected_changes = {
        "externalKey": {"from": binding["external_key"], "to": masked, "changed": True},
        "mapping": {"from": old_mapping, "to": dict(old_mapping, owner=masked), "changed": True},
        "fieldAuthority": {"from": old_authority, "to": new_authority, "changed": True},
        "matchRule": {"from": sanitized_rule, "to": sanitized_rule, "changed": True}}
    assert json.loads(audit["changes_json"]) == {
        "payloadVersion": 1, "source": "deliverable_sync_settings",
        "deliverableId": deliverable_id, "beforeRevision": case["revision"],
        "afterRevision": expected_revision, "scope": None, "changes": expected_changes}
    assert all(marker not in audit["changes_json"] for marker in markers)
    assert masked in audit["changes_json"]
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
              and event["conn"] is call["conn"] and call["start_seq"] < event["seq"] < call["end_seq"]]
    assert inside and all(event["sql"].lstrip().split(None, 1)[0].upper() not in
                          {"COMMIT", "ROLLBACK"} for event in inside)
    assert all(item["closed"] for item in observed["connections"])
