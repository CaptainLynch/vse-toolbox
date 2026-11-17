import pytest
from core.project_status_contracts import project_status_supports_record_set
from core.repos.project_status import compute_policy_config_digest as digest
from services.project_status_updates import ProjectStatusPolicyError
from tests.conftest import bprime_audit_case


MESSAGE = "绑定已发生变化，请刷新配置后重试"


def _stale_owner(case):
    db, did = case["db"], case["deliverable_id"]
    raw = db.get_project_status_update_policy(did)
    assert not project_status_supports_record_set(did)
    assert raw["binding"]["sync_config_revision"] == 7
    assert next(r for r in raw["authorities"] if r["field_name"] == "owner")["authority"] == "manual"
    stale = digest(did, raw["binding"], raw["authorities"])
    with db.get_connection() as conn:
        changed = conn.execute(
            "UPDATE project_status_field_authority SET authority = 'automatic', locked_at = NULL "
            "WHERE deliverable_id = ? AND field_name = 'owner'", (did,))
        assert changed.rowcount == 1
    before = case["snapshot"]()
    assert before["binding"][0]["sync_config_revision"] == 7
    assert digest(did, before["binding"][0], before["authorities"]) != stale
    return stale, before


def test_stale_digest_rejects_authority_change(bprime_audit_case):
    case = bprime_audit_case
    stale, before = _stale_owner(case)
    count = len(case["audit_rows"]())
    with pytest.raises(ProjectStatusPolicyError) as caught:
        case["service"].update_update_policy(case["deliverable_id"], {
            "fieldAuthority": {"owner": "manual"}, "expectedConfigDigest": stale})
    assert caught.value.fields == {"expectedConfigDigest": MESSAGE}
    assert case["snapshot"]() == before
    assert len(case["audit_rows"]()) == count


def test_stale_digest_rejects_noop(bprime_audit_case):
    case = bprime_audit_case
    stale, before = _stale_owner(case)
    count = len(case["audit_rows"]())
    with pytest.raises(ProjectStatusPolicyError) as caught:
        case["service"].update_update_policy(
            case["deliverable_id"], {"expectedConfigDigest": stale})
    assert caught.value.fields == {"expectedConfigDigest": MESSAGE}
    assert case["snapshot"]() == before
    assert len(case["audit_rows"]()) == count


def test_revision_conflict_precedes_digest(bprime_audit_case):
    db, service = bprime_audit_case["db"], bprime_audit_case["service"]
    did = "VPI-T2-D3"
    assert project_status_supports_record_set(did)
    raw = db.get_project_status_update_policy(did)
    assert raw is not None and not raw["binding"]["enabled"]
    revision = raw["binding"]["sync_config_revision"]
    stale = digest(did, raw["binding"], raw["authorities"])
    save = db._save_policy_txn
    seen = []

    def race(conn, target, *args, **kwargs):
        assert target == did and not conn.in_transaction
        assert kwargs["expected_sync_config_revision"] == revision
        assert kwargs["expected_config_digest"] == stale
        with db.get_connection() as writer:
            changed = writer.execute(
                "UPDATE project_status_update_bindings "
                "SET sync_config_revision = sync_config_revision + 1 WHERE deliverable_id = ?", (did,))
            assert changed.rowcount == 1
        current = db.get_project_status_update_policy(did)
        assert current["binding"]["sync_config_revision"] == revision + 1
        assert digest(did, current["binding"], current["authorities"]) != stale
        seen.append(current)
        return save(conn, target, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(db, "_save_policy_txn", race)
        with pytest.raises(ProjectStatusPolicyError) as caught:
            service.update_update_policy(did, {"expectedConfigDigest": stale})
    assert caught.value.fields == {"request": MESSAGE}
    assert len(seen) == 1
    assert db.get_project_status_update_policy(did) == seen[0]
