from contextlib import contextmanager
import pytest
from core.project_status_contracts import project_status_supports_record_set
from core.repos.project_status import PROJECT_STATUS_EDITABLE_FIELDS, compute_policy_config_digest
from tests.conftest import trace
from services.project_status_updates import ProjectStatusPolicyError

DID = "VPI-T2-D3"
TABLES = (
    "project_status_phases project_status_deliverables project_status_update_bindings "
    "project_status_field_authority project_status_analysis_snapshots project_status_analysis_items "
    "project_status_binding_config_audit project_status_update_audit scheduled_archive_jobs "
    "scheduled_archive_config_audit"
).split()
BINDING, AUTHORITY, AUDIT, UPDATE_AUDIT = TABLES[2], TABLES[3], TABLES[6], TABLES[7]
MESSAGE = "绑定已发生变化，请刷新配置后重试"


def _rows(conn, table):
    return [dict(row) for row in conn.execute(
        f"SELECT * FROM {table} WHERE deliverable_id = ?", (DID,))]


def _snapshot(conn):
    result = {}
    for table in TABLES:
        cursor = conn.execute(f"SELECT * FROM {table}")
        result[table] = (tuple(col[0] for col in cursor.description),
                         sorted((tuple(row) for row in cursor.fetchall()), key=repr))
    return result


def _missing(conn):
    assert conn.execute("SELECT id FROM project_status_deliverables WHERE id = ?", (DID,)).fetchone()
    for table in (BINDING, AUTHORITY, UPDATE_AUDIT):
        assert _rows(conn, table) == [], table


def _seeded(conn):
    bindings, authorities = _rows(conn, BINDING), _rows(conn, AUTHORITY)
    assert len(bindings) == 1
    assert len(authorities) == len(PROJECT_STATUS_EDITABLE_FIELDS)
    assert {row["field_name"] for row in authorities} == set(PROJECT_STATUS_EDITABLE_FIELDS)
    return bindings[0]


@pytest.fixture
def missing_case(bprime_audit_case):
    db, service = bprime_audit_case["db"], bprime_audit_case["service"]
    assert project_status_supports_record_set(DID)
    with db.get_connection() as conn:
        for table in (BINDING, AUTHORITY, UPDATE_AUDIT):
            conn.execute(f"DELETE FROM {table} WHERE deliverable_id = ?", (DID,))
        conn.commit()
        _missing(conn)
        assert _rows(conn, AUDIT) == []
    return db, service

@contextmanager
def _probe(db, writes=False, no_begin=False):
    with db.get_connection() as observer:
        _missing(observer)
        before = _snapshot(observer)
        version = observer.execute("PRAGMA data_version").fetchone()[0]
        assert not observer.in_transaction
        with trace(db) as seen:
            yield
        assert not observer.in_transaction
        assert (_snapshot(observer) != before) == writes
        assert (observer.execute("PRAGMA data_version").fetchone()[0] != version) == writes
        connections = seen["connections"]
        assert connections and seen["recorder_wrapped"]
        assert all(item["closed"] for item in connections)
        verbs = [event["sql"].lstrip().split(None, 1)[0].upper()
                 for item in connections for event in item["sql"]]
        dml = [verb for verb in verbs if verb in {"INSERT", "UPDATE", "DELETE", "REPLACE"}]
        assert bool(dml) == writes
        if no_begin:
            assert not any(
                " ".join(event["sql"].upper().split()).startswith("BEGIN IMMEDIATE")
                for item in connections for event in item["sql"]
            )
        if writes:
            assert any(item["total_changes_after"] > item["total_changes_before"] for item in connections)
        else:
            assert all(item["total_changes_after"] == item["total_changes_before"] for item in connections)
            assert seen["recorder_calls"] == []
            _missing(observer)


def test_missing_snapshot_matches_seeded_get(missing_case):
    db, service = missing_case
    with _probe(db, no_begin=True):
        raw = db.read_project_status_update_policy_snapshot(DID)
        policy = service._policy_to_api(raw)
        assert db.read_project_status_update_policy_snapshot("UNKNOWN-PREREAD") is None
    assert policy["configDigest"] == compute_policy_config_digest(DID, raw["binding"], raw["authorities"])
    assert policy["createdAt"] is None and policy["updatedAt"] is None
    seeded = service.get_update_policy(DID)
    with db.get_connection() as conn:
        binding = _seeded(conn)
    assert raw["binding"]["sync_config_revision"] == binding["sync_config_revision"]
    assert set(policy) == set(seeded)
    assert policy["latestUpdate"] is None and seeded["latestUpdate"] is None
    assert policy["configDigest"] == seeded["configDigest"]
    assert seeded["createdAt"] is not None and seeded["updatedAt"] is not None
    for key in set(policy) - {"createdAt", "updatedAt"}:
        assert policy[key] == seeded[key], key


def test_missing_failed_requests_have_zero_dml(missing_case):
    db, service = missing_case
    read = db.read_project_status_update_policy_snapshot
    raw = read(DID)
    assert raw["binding"]["interval_minutes"] is None
    assert raw["binding"]["sync_config_revision"] == 0
    current = compute_policy_config_digest(DID, raw["binding"], raw["authorities"])
    changed = dict(raw["binding"], interval_minutes=5)
    stale = compute_policy_config_digest(DID, changed, raw["authorities"])
    assert stale != current

    def stale_read(target):
        actual = read(target)
        assert actual["binding"]["sync_config_revision"] == 0
        return dict(actual, binding=dict(actual["binding"], sync_config_revision=1))

    for kind, expected, field, message in (
        ("format", "bad", "expectedConfigDigest", "配置摘要格式无效"),
        ("digest", stale, "expectedConfigDigest", MESSAGE),
        ("revision", current, "request", MESSAGE),
    ):
        with pytest.MonkeyPatch.context() as patch:
            if kind == "revision":
                patch.setattr(db, "read_project_status_update_policy_snapshot", stale_read)
            with _probe(db):
                with pytest.raises(ProjectStatusPolicyError) as caught:
                    service.update_update_policy(DID, {"intervalMinutes": 5, "expectedConfigDigest": expected})
                assert caught.value.fields == {field: message}


def test_missing_success_is_positive_write_control(missing_case):
    db, service = missing_case
    raw = db.read_project_status_update_policy_snapshot(DID)
    assert raw["binding"]["interval_minutes"] is None
    current = compute_policy_config_digest(DID, raw["binding"], raw["authorities"])
    with _probe(db, writes=True):
        result = service.update_update_policy(DID, {"intervalMinutes": 5, "expectedConfigDigest": current})
    assert result["intervalMinutes"] == 5
    with db.get_connection() as conn:
        assert _seeded(conn)["interval_minutes"] == 5
        assert len(_rows(conn, AUDIT)) == 1
