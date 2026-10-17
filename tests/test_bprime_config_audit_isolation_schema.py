def test_binding_config_audit_schema_reinit_idempotent(bprime_audit_case):
    import sqlite3
    import pytest
    from core.project_status_config_audit import (
        ensure_binding_config_audit_schema, BindingConfigAuditError)

    case = bprime_audit_case
    db, deliverable_id = case["db"], case["deliverable_id"]
    table = "project_status_binding_config_audit"
    columns = [
        (0, "id", "INTEGER", 0, None, 1),
        (1, "deliverable_id", "TEXT", 1, None, 0),
        (2, "actor", "TEXT", 1, None, 0),
        (3, "event_type", "TEXT", 1, None, 0),
        (4, "config_revision", "INTEGER", 1, None, 0),
        (5, "changes_json", "TEXT", 1, None, 0),
        (6, "created_at", "TEXT", 1, "strftime('%Y-%m-%dT%H:%M:%fZ','now')", 0)]
    insert = (
        "INSERT INTO project_status_binding_config_audit "
        "(deliverable_id, actor, event_type, config_revision, changes_json) VALUES (?, ?, ?, ?, ?)")
    schema_query = (
        "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE tbl_name = ? ORDER BY type, name")
    memory = sqlite3.connect(":memory:")
    try:
        statements = []
        memory.set_trace_callback(statements.append)
        assert not memory.in_transaction
        assert ensure_binding_config_audit_schema(memory) is None
        assert not memory.in_transaction
        assert ensure_binding_config_audit_schema(memory) is None
        assert not memory.in_transaction
        assert sum(sql.strip().upper() == "BEGIN IMMEDIATE" for sql in statements) == 2
        assert sum(sql.strip().upper() == "COMMIT" for sql in statements) == 2
        assert [tuple(row) for row in memory.execute("PRAGMA table_info(" + table + ")")] == columns
        assert memory.execute("PRAGMA foreign_key_list(" + table + ")").fetchall() == []
        shape = memory.execute(schema_query, (table,)).fetchall()
        tables = [row for row in shape if row[0] == "table"]
        assert len(tables) == 1
        assert "AUTOINCREMENT" in tables[0][3].upper()
        for actor in ("local_web", "cli"):
            memory.execute(insert, (deliverable_id, actor, "configuration_updated", 0, "{}"))
        memory.commit()
        legal = memory.execute("SELECT * FROM " + table + " ORDER BY id").fetchall()
        assert [row[0] for row in legal] == [1, 2]
        assert {row[2] for row in legal} == {"local_web", "cli"}
        assert all(row[3] == "configuration_updated" for row in legal)
        assert all(isinstance(row[6], str) and row[6] for row in legal)
        invalid = (
            ("SYNTHETIC_MARKER_1", "configuration_updated", 0),
            ("local_web", "SYNTHETIC_MARKER_1", 0),
            ("local_web", "configuration_updated", -1))
        for actor, event_type, revision in invalid:
            memory.execute("SAVEPOINT invalid_value")
            with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
                memory.execute(insert, (deliverable_id, actor, event_type, revision, "{}"))
            assert memory.in_transaction
            memory.execute("ROLLBACK TO invalid_value")
            memory.execute("RELEASE invalid_value")
        assert memory.execute("SELECT * FROM " + table + " ORDER BY id").fetchall() == legal
        memory.execute("BEGIN")
        memory.execute(insert, ("SYNTHETIC_MARKER_1", "local_web", "configuration_updated", 0, "{}"))
        marked = memory.execute("SELECT * FROM " + table + " ORDER BY id").fetchall()
        assert len(marked) == len(legal) + 1
        assert memory.in_transaction
        with pytest.raises(BindingConfigAuditError):
            ensure_binding_config_audit_schema(memory)
        assert memory.in_transaction
        assert memory.execute("SELECT * FROM " + table + " ORDER BY id").fetchall() == marked
        memory.rollback()
        assert not memory.in_transaction
        assert memory.execute("SELECT * FROM " + table + " ORDER BY id").fetchall() == legal
    finally:
        memory.close()
    assert case["audit_rows"]() == []
    with db.get_connection() as conn:
        conn.executemany(insert, [
            (deliverable_id, "local_web" if index % 2 else "cli",
             "configuration_updated", index, "{}") for index in range(105)])
    before = case["snapshot"]()
    rows = case["audit_rows"]()
    assert len(rows) == 105
    assert before["dedicated_audit"] == rows
    assert before["binding"][0]["sync_config_revision"] == case["revision"] == 7
    assert before["binding"][0]["cursor_json"]
    assert before["authorities"]
    assert before["analysis_snapshots"]
    assert before["analysis_items"]
    with db.get_connection() as conn:
        schema = [tuple(row) for row in conn.execute(schema_query, (table,))]
        assert [tuple(row) for row in conn.execute("PRAGMA table_info(" + table + ")")] == columns
        assert conn.execute("PRAGMA foreign_key_list(" + table + ")").fetchall() == []
    for _ in range(2):
        db.init_database()
        with db.get_connection() as conn:
            assert [tuple(row) for row in conn.execute(schema_query, (table,))] == schema
            assert conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,)).fetchone()[0] == 1
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 14
            assert [tuple(row) for row in conn.execute("PRAGMA table_info(" + table + ")")] == columns
            assert conn.execute("PRAGMA foreign_key_list(" + table + ")").fetchall() == []
            after = case["snapshot"](conn)
            assert case["audit_rows"](conn) == rows
        assert set(after) == set(before)
        for section in before:
            assert after[section] == before[section], section
