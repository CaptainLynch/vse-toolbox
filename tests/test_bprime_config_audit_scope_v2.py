import json

import pytest
from core.redaction import redact_sensitive_text
from tests.conftest import trace


R, T = {"reportType": "bprime"}, {"reportType": "other"}
A, B = ["SYNTHETIC_SECTION_A"], ["SYNTHETIC_SECTION_B"]
M0, M1 = {"owner": "currentApprover"}, {"owner": "SYNTHETIC_OWNER_2"}
RA, RB, TB = (dict(base, sectionScope=items) for base, items in ((R, A), (R, B), (T, B)))
C, D = ["<cookie>SYNTHETIC_MARKER_1</cookie>"], ["<cookie>SYNTHETIC_MARKER_2</cookie>"]
MASK = ["<cookie>[redacted]</cookie>"]


def scope(items):
    return {"source": "matchRule.sectionScope", "declarationOnly": True, "items": items}


def delta(old, new):
    return {"from": old, "to": new, "changed": True}


CASES = [
    ("no_scope_missing", R, R, M1, None, {"mapping": delta(M0, M1)}),
    ("no_scope_empty", dict(R, sectionScope=[]), dict(R, sectionScope=[]), M1, None, {"mapping": delta(M0, M1)}),
    ("no_scope_null", dict(R, sectionScope=None), dict(R, sectionScope=None), M1, None, {"mapping": delta(M0, M1)}),
    ("no_scope_nonlist", dict(R, sectionScope="SYNTHETIC_NONLIST"), dict(R, sectionScope="SYNTHETIC_NONLIST"), M1, None, {"mapping": delta(M0, M1)}),
    ("add", R, RA, M0, scope(A), {"scope": delta(None, scope(A))}),
    ("replace", RA, RB, M0, scope(B), {"scope": delta(scope(A), scope(B))}),
    ("delete", RA, R, M0, None, {"scope": delta(scope(A), None)}),
    ("scope_and_rule", RA, TB, M0, scope(B), {"scope": delta(scope(A), scope(B)), "matchRule": delta(R, T)}),
    ("unchanged_scope_mapping", RA, RA, M1, scope(A), {"mapping": delta(M0, M1)}),
    ("redacted_equal", dict(R, sectionScope=C), dict(R, sectionScope=D), M0, scope(MASK), {"scope": delta(scope(MASK), scope(MASK))}),
    ("rule_only", R, T, M0, None, {"matchRule": delta(R, T)}),
    ("equivalent_scope_forms", R, dict(R, sectionScope=[]), M0, None, {}),
]


def seed(case, rule):
    with case["db"].get_connection() as conn:
        conn.execute("UPDATE scheduled_archive_jobs SET project_status_deliverable_id = NULL "
                     "WHERE project_status_deliverable_id = ?", (case["deliverable_id"],))
        conn.execute("UPDATE project_status_update_bindings SET match_rule_json = ? "
                     "WHERE deliverable_id = ?", (json.dumps(rule), case["deliverable_id"]))
        conn.commit()
    before = case["snapshot"]()
    assert len(before["binding"]) == 1 and not before["archive_jobs"]
    binding = before["binding"][0]
    assert binding["sync_config_revision"] == case["revision"] == 7
    assert json.loads(binding["match_rule_json"]) == rule
    assert json.loads(binding["mapping_json"]) == M0
    assert json.loads(binding["cursor_json"]) and before["analysis_snapshots"] and before["analysis_items"]
    assert next(row for row in before["authorities"] if row["field_name"] == "owner")["authority"] == "manual"


def save(case, rule, mapping, authority=None):
    before = case["snapshot"]()
    assert len(before["binding"]) == 1
    b = before["binding"][0]
    owners = {row["field_name"]: row["authority"] for row in before["authorities"]}
    requested = dict(owners)
    requested.update(authority or {})
    target_changed = json.loads(b["match_rule_json"]) != rule or json.loads(b["mapping_json"]) != mapping
    revision = b["sync_config_revision"] + int(target_changed)
    assert set(mapping) <= {"owner", "plannedDate", "note"}
    with trace(case["db"], "scope-save") as observed:
        result = case["db"].set_project_status_update_policy(
            case["deliverable_id"], b["mode"], bool(b["enabled"]), b["external_key"],
            json.dumps(rule), json.dumps(mapping), requested, credential_ref=b["credential_ref"],
            interval_minutes=b["interval_minutes"], expected_sync_config_revision=b["sync_config_revision"],
            actor="local_web")
    after = case["snapshot"]()
    assert len(after["binding"]) == 1
    saved = after["binding"][0]
    assert result == saved["sync_config_revision"] == revision
    assert json.loads(saved["match_rule_json"]) == rule
    assert json.loads(saved["mapping_json"]) == mapping
    assert json.loads(saved["cursor_json"]) == ({} if target_changed else json.loads(b["cursor_json"]))
    if not target_changed:
        assert saved["cursor_json"] == b["cursor_json"]
    for key in ("mode", "enabled", "source_type", "external_key", "credential_ref", "interval_minutes"):
        assert saved[key] == b[key]
    for key in ("analysis_snapshots", "analysis_items"):
        assert after[key] == ([] if target_changed else before[key])
    assert {row["field_name"]: row["authority"] for row in after["authorities"]} == requested
    if authority is None:
        assert after["authorities"] == before["authorities"]
    for key in ("business_audit", "archive_config_audit", "archive_jobs"):
        assert after[key] == before[key]
    rows = case["audit_rows"]()
    assert rows == after["dedicated_audit"]
    assert len(rows) == len(before["dedicated_audit"]) + 1
    assert rows[:-1] == before["dedicated_audit"]
    audit = rows[-1]
    assert audit["deliverable_id"] == case["deliverable_id"] and audit["config_revision"] == revision
    assert audit["actor"] == "local_web" and audit["event_type"] == "configuration_updated"
    assert isinstance(audit["created_at"], str) and audit["created_at"]
    assert len(observed["recorder_calls"]) == 1
    call = observed["recorder_calls"][0]
    assert call["conn"] is not None and call["in_transaction"] is True and call["result"] is True
    assert all(item["closed"] for item in observed["connections"])
    return after, json.loads(audit["changes_json"])


def test_scope_storage_and_revision_invariants(bprime_audit_case):
    case = bprime_audit_case
    seed(case, RA)
    first, _ = save(case, RA, M0, {"owner": "automatic"})
    assert first["binding"][0]["sync_config_revision"] == 7
    assert json.loads(first["binding"][0]["match_rule_json"]) == RA
    second, _ = save(case, RB, M0)
    assert second["binding"][0]["sync_config_revision"] == 8
    assert json.loads(second["binding"][0]["cursor_json"]) == {}
    assert not second["analysis_snapshots"] and not second["analysis_items"]


@pytest.mark.parametrize("name,old,new,mapping,after_scope,changes", CASES, ids=[row[0] for row in CASES])
def test_scope_payload_v2(bprime_audit_case, name, old, new, mapping, after_scope, changes):
    case = bprime_audit_case
    seed(case, old)
    if name == "redacted_equal":
        assert C != D and [redact_sensitive_text(x) for x in C] == [redact_sensitive_text(x) for x in D] == MASK
    after, actual = save(case, new, mapping)
    assert after["binding"][0]["sync_config_revision"] == 8
    if name == "redacted_equal":
        encoded = json.dumps(actual)
        assert all(marker not in encoded for marker in ("SYNTHETIC_MARKER_1", "SYNTHETIC_MARKER_2"))
        assert MASK[0] in encoded
    expected = {"payloadVersion": 2, "source": "deliverable_sync_settings",
                "deliverableId": case["deliverable_id"], "beforeRevision": 7, "afterRevision": 8,
                "scope": after_scope, "changes": changes}
    assert actual == expected, f"{name}: full payload differs"
