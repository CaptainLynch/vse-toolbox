# -*- coding: utf-8 -*-
"""U-P1A-TEST-FIXTURE-STATE-R2：bprime_audit_case 只读快照夹具契约。

只断言夹具样本与只读能力，不验证审计业务行为。
"""

FIXED_AT = "2026-01-05 09:00:00"
SNAPSHOT_KEYS = {
    "binding", "authorities", "analysis_snapshots", "analysis_items",
    "dedicated_audit", "business_audit", "archive_config_audit", "archive_jobs",
}

_DEDICATED_SQL = "SELECT * FROM project_status_binding_config_audit WHERE deliverable_id = ? ORDER BY id"
_ARCHIVE_CONFIG_SQL = (
    "SELECT a.* FROM scheduled_archive_config_audit AS a JOIN scheduled_archive_jobs AS j "
    "ON j.id = a.job_id WHERE j.project_status_deliverable_id = ? ORDER BY a.job_id, a.id"
)


def _query(conn, sql, params=("VPI-T2-D5",)) -> list:
    cursor = conn.execute(sql, params)
    return [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]


def test_bprime_fixture_state_contract(bprime_audit_case) -> None:
    case = bprime_audit_case
    assert set(case) == {
        "db", "service", "deliverable_id", "revision", "snapshot", "audit_rows",
    }
    assert case["deliverable_id"] == "VPI-T2-D5" and case["revision"] == 7

    first = case["snapshot"]()
    assert set(first) == SNAPSHOT_KEYS
    assert all(isinstance(first[key], list) for key in SNAPSHOT_KEYS)

    assert len(first["binding"]) == 1
    row = first["binding"][0]
    assert row["deliverable_id"] == "VPI-T2-D5"
    assert (row["mode"], row["enabled"], row["source_type"]) == ("hybrid", 0, "tdc")
    assert row["external_key"] == "BPRIME-EXT-7"
    assert row["mapping_json"].strip() not in ("", "{}")
    assert row["sync_config_revision"] == 7
    assert row["cursor_json"].strip() not in ("", "{}")
    assert row["updated_at"] == FIXED_AT

    authorities = first["authorities"]
    assert authorities
    assert [item["field_name"] for item in authorities] == sorted(
        item["field_name"] for item in authorities
    )
    owners = [item for item in authorities if item["field_name"] == "owner"]
    assert len(owners) == 1
    owner = owners[0]
    assert (owner["authority"], owner["source_type"]) == ("manual", "tdc")
    assert owner["locked_at"] == FIXED_AT and owner["updated_at"] == FIXED_AT
    others = [item for item in authorities if item["field_name"] != "owner"]
    progress = [item for item in others if item["field_name"] == "progress"]
    assert len(progress) == 1 and progress[0]["authority"] == "manual"
    assert progress[0]["locked_at"] == FIXED_AT and progress[0]["updated_at"] == FIXED_AT

    snapshots = first["analysis_snapshots"]
    assert len(snapshots) == 1 and snapshots[0]["source_run_id"] is None
    assert snapshots[0]["snapshot_at"] == FIXED_AT
    assert snapshots[0]["total_count"] == (
        snapshots[0]["completed_count"] + snapshots[0]["incomplete_count"]
    )

    items = first["analysis_items"]
    assert items
    assert {"item_key", "title", "is_completed", "updated_at"} <= set(items[0])
    assert items[0]["updated_at"] == FIXED_AT and items[0]["is_completed"] in (0, 1)

    business = first["business_audit"]
    assert {e["deliverable_id"] for e in business} == {"VPI-T2-D5"}
    assert ("sync_now", "skipped", FIXED_AT) in {
        (e["trigger_type"], e["result"], e["created_at"]) for e in business
    }

    dedicated = first["dedicated_audit"]
    assert dedicated == case["audit_rows"]()
    assert all(entry["deliverable_id"] == "VPI-T2-D5" for entry in dedicated)

    with case["db"].get_connection() as conn:
        assert case["snapshot"](conn) == first
        assert case["audit_rows"](conn) == dedicated
        assert _query(conn, _DEDICATED_SQL) == dedicated
        assert first["archive_config_audit"] == _query(conn, _ARCHIVE_CONFIG_SQL)
    assert case["snapshot"]() == first
