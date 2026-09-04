# -*- coding: utf-8 -*-
"""
tests/test_db_manager.py — DatabaseManager 单元测试（E2）

验收断言:
    1. 兜底项目 id=1 名称='未归类' 在 init_database() 后存在
    2. 重复调用 init_database() 不增加 projects 行数（幂等）
    3. get_connection() 在异常时回滚（无脏数据）
    4. Excel schema v5 可新建、迁移并保持初始化幂等
"""

from pathlib import Path
import sqlite3

import pytest

from core.db_manager import DatabaseManager, CURRENT_SCHEMA_VERSION


def test_fallback_project_exists(tmp_db: DatabaseManager) -> None:
    """A2 验收：init_database 后 projects 含 id=1 名称='未归类'。"""
    with tmp_db.get_connection() as conn:
        row = conn.execute(
            "SELECT id, name, manager, status FROM projects WHERE id=1"
        ).fetchone()

    assert row is not None, "id=1 兜底项目不存在"
    assert row["name"] == "未归类"
    assert row["manager"] == "system"
    assert row["status"] == "active"


def test_init_database_idempotent(tmp_path: Path) -> None:
    """A2 验收：重复调用 init_database() 后 projects 行数不变。"""
    db = DatabaseManager(db_path=tmp_path / "idempotent.db")
    db.init_database()

    with db.get_connection() as conn:
        count_before = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]

    db.init_database()

    with db.get_connection() as conn:
        count_after = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]

    assert count_before == count_after, (
        f"重复 init_database() 导致行数从 {count_before} 变为 {count_after}"
    )


def test_get_connection_rollback_on_error(tmp_path: Path) -> None:
    """A2 验收：get_connection() 在异常时回滚，无脏数据残留。"""
    db = DatabaseManager(db_path=tmp_path / "rollback.db")
    db.init_database()

    with db.get_connection() as conn:
        before = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]

    # 构造异常：在 with 块内写入后抛出，期望回滚
    try:
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO projects (id, name, manager, status) "
                "VALUES (999, '脏数据', 'test', 'active')"
            )
            raise RuntimeError("构造异常触发回滚")
    except RuntimeError:
        pass

    with db.get_connection() as conn:
        after = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]

    assert after == before, f"回滚失败：行数从 {before} 变为 {after}，存在脏数据"


def test_table_exists(tmp_db: DatabaseManager) -> None:
    """所有必需表均应存在（含 Schema v6 Excel artifact audit 表）。"""
    for table in (
        "projects",
        "deliverables",
        "feishu_tasks",
        "excel_tasks",
        "excel_task_files",
        "excel_task_runs",
        "excel_task_artifacts",
        "excel_artifact_download_audit",
        "project_status_analysis_snapshots",
        "project_status_analysis_items",
        "deliverable_form_snapshots",
        "deliverable_form_rows",
    ):
        assert tmp_db.table_exists(table), f"表 {table} 不存在"


def test_get_table_row_count(tmp_db: DatabaseManager) -> None:
    """projects 至少包含 id=1 兜底项目 + 预置的测试项目。"""
    count = tmp_db.get_table_row_count("projects")
    assert count >= 2, f"projects 行数应 ≥ 2，实际 {count}"


def test_schema_version_is_v12(tmp_db: DatabaseManager) -> None:
    """验证当前支持的 schema 版本为 12。"""
    assert CURRENT_SCHEMA_VERSION == 12
    with tmp_db.get_connection() as conn:
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
    assert ver == 12


def test_v3_to_v12_migration(tmp_path: Path) -> None:
    """验证从已存在的 v3 数据库平滑升级到 v12。"""
    v3_db_path = tmp_path / "v3_legacy.db"
    conn = sqlite3.connect(str(v3_db_path))
    conn.execute("PRAGMA user_version = 3")
    conn.execute(
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            name TEXT,
            manager TEXT,
            status TEXT
        )
        """
    )
    conn.execute("INSERT INTO projects VALUES (1, '未归类', 'system', 'active')")
    conn.commit()
    conn.close()

    db = DatabaseManager(db_path=v3_db_path)
    db.init_database()

    with db.get_connection() as c:
        ver = c.execute("PRAGMA user_version").fetchone()[0]
        assert ver == 12
        assert db.table_exists("excel_tasks")
        assert db.table_exists("excel_task_files")
        assert db.table_exists("excel_task_runs")
        assert db.table_exists("excel_task_artifacts")
        assert db.table_exists("excel_artifact_download_audit")
        assert db.table_exists("project_status_analysis_snapshots")
        assert db.table_exists("project_status_analysis_items")
        phase = c.execute(
            "SELECT display_name FROM project_status_phases WHERE id = 'VPI-T2'"
        ).fetchone()
        assert phase[0] == "F610S"
        row = c.execute("SELECT name FROM projects WHERE id = 1").fetchone()
        assert row[0] == "未归类"


def test_seed_renames_legacy_ewo_and_phase_anchor(tmp_path: Path) -> None:
    """存量库升级时，旧交付物名与旧主计划名必须被幂等迁移到新默认值。"""
    db = DatabaseManager(db_path=tmp_path / "legacy-names.db")
    db.init_database()
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_deliverables SET name = 'EWO 定点流程' WHERE id = 'VPI-T2-D3'"
        )
        conn.execute(
            "UPDATE project_status_phases SET display_name = 'VPI-T2 主计划时间轴' WHERE id = 'VPI-T2'"
        )
        # 用户手动改过的名字不在迁移范围内。
        conn.execute(
            "UPDATE project_status_deliverables SET name = '我的自定义流程' WHERE id = 'VPI-T2-D5'"
        )
        conn.commit()

    db.init_database()  # 模拟应用重启后的再迁移

    with db.get_connection() as conn:
        ewo = conn.execute(
            "SELECT name FROM project_status_deliverables WHERE id = 'VPI-T2-D3'"
        ).fetchone()[0]
        anchor = conn.execute(
            "SELECT display_name FROM project_status_phases WHERE id = 'VPI-T2'"
        ).fetchone()[0]
        custom = conn.execute(
            "SELECT name FROM project_status_deliverables WHERE id = 'VPI-T2-D5'"
        ).fetchone()[0]
    assert ewo == "EWO 流程"
    assert anchor == "F610S"
    assert custom == "我的自定义流程"


def test_v5_to_v12_migration(tmp_path: Path) -> None:
    """验证从已存在的 v5 数据库平滑升级到 v12。"""
    v5_db_path = tmp_path / "v5_legacy.db"
    conn = sqlite3.connect(str(v5_db_path))
    conn.execute("PRAGMA user_version = 5")
    conn.execute(
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            name TEXT,
            manager TEXT,
            status TEXT
        )
        """
    )
    conn.execute("INSERT INTO projects VALUES (1, '未归类', 'system', 'active')")
    conn.commit()
    conn.close()

    db = DatabaseManager(db_path=v5_db_path)
    db.init_database()

    with db.get_connection() as c:
        ver = c.execute("PRAGMA user_version").fetchone()[0]
        assert ver == 12
        assert db.table_exists("excel_artifact_download_audit")
        assert db.table_exists("project_status_analysis_snapshots")


def test_v9_to_v12_migration_adds_analysis_detail_columns(tmp_path: Path) -> None:
    """A v9 database gains the number and pending-signer columns in place."""
    db_path = tmp_path / "v9_analysis_legacy.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA user_version = 9")
    conn.execute(
        """
        CREATE TABLE project_status_analysis_items (
            deliverable_id TEXT NOT NULL,
            item_key TEXT NOT NULL,
            title TEXT NOT NULL,
            department TEXT NOT NULL DEFAULT '未归属',
            owner TEXT NOT NULL DEFAULT '',
            source_status TEXT NOT NULL DEFAULT '',
            is_completed INTEGER NOT NULL,
            planned_date TEXT,
            actual_date TEXT,
            source_run_id INTEGER,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (deliverable_id, item_key)
        )
        """
    )
    conn.commit()
    conn.close()

    db = DatabaseManager(db_path=db_path)
    db.init_database()

    with db.get_connection() as c:
        columns = {
            row["name"]
            for row in c.execute("PRAGMA table_info(project_status_analysis_items)")
        }
        assert {"display_number", "pending_signers"}.issubset(columns)
        assert c.execute("PRAGMA user_version").fetchone()[0] == 12


def test_analysis_items_department_model_extra_columns_migration(tmp_path: Path) -> None:
    """project_status_analysis_items 补齐 source_department / model_info / extra_fields_json 三列且迁移幂等。"""
    db = DatabaseManager(db_path=tmp_path / "analysis-extra-columns.db")
    db.init_database()

    with db.get_connection() as conn:
        info = conn.execute("PRAGMA table_info(project_status_analysis_items)").fetchall()
    columns = {row["name"]: row for row in info}
    for name in ("source_department", "model_info", "extra_fields_json"):
        assert name in columns, f"缺少新列 {name}"
        assert columns[name]["type"] == "TEXT"
        assert columns[name]["notnull"] == 1
        assert columns[name]["dflt_value"] == "''"

    # 连续两次 init_database() 幂等：不抛错、列不重复。
    db.init_database()
    with db.get_connection() as conn:
        names = [
            row["name"]
            for row in conn.execute("PRAGMA table_info(project_status_analysis_items)")
        ]
    assert names.count("source_department") == 1
    assert names.count("model_info") == 1
    assert names.count("extra_fields_json") == 1

    # 新列参与缓存写入/读出：source_department 与 model_info 回读，extra_fields_json 默认空串。
    snapshot = {
        "total_count": 1,
        "completed_count": 0,
        "incomplete_count": 1,
        "overdue_count": 0,
        "due_soon_count": 0,
        "missing_due_date_count": 0,
        "department_counts": {"车身科": {"total": 1, "completed": 0, "incomplete": 1}},
        "snapshot_at": "2026-08-23T00:00:00.000Z",
    }
    item = {
        "item_key": "EWO-BODY-KEY",
        "display_number": "EWO-049039",
        "title": "蒙皮总成更改",
        "department": "车身科",
        "owner": "张三",
        "pending_signers": "",
        "source_status": "IMPL",
        "source_stage": "impl",
        "source_type": "aras",
        "is_completed": False,
        "planned_date": "2026-09-01",
        "actual_date": None,
        "source_department": "技术中心_车体工程",
        "model_info": "F610S",
    }
    db.replace_project_status_analysis_cache("VPI-T2-D3", 11, snapshot, [item])

    rows = db.list_project_status_analysis_items("VPI-T2-D3")
    assert len(rows) == 1
    assert rows[0]["source_department"] == "技术中心_车体工程"
    assert rows[0]["model_info"] == "F610S"
    with db.get_connection() as conn:
        stored = conn.execute(
            "SELECT extra_fields_json FROM project_status_analysis_items "
            "WHERE deliverable_id = ?",
            ("VPI-T2-D3",),
        ).fetchone()
    assert stored["extra_fields_json"] == ""


def test_rejects_newer_schema_version(tmp_path: Path) -> None:
    """验证高于 CURRENT_SCHEMA_VERSION (如 v13) 的库在执行 DDL 前被拒绝。"""
    future_db_path = tmp_path / "v13_future.db"
    conn = sqlite3.connect(str(future_db_path))
    conn.execute("PRAGMA user_version = 13")
    conn.commit()
    conn.close()

    db = DatabaseManager(db_path=future_db_path)
    with pytest.raises(sqlite3.DatabaseError) as exc_info:
        db.init_database()
    assert "unsupported schema version 13" in str(exc_info.value)


def test_form_snapshot_check_constraint_rebuild_allows_tdc_data_model(
    tmp_path: Path,
) -> None:
    """旧库的 form_key CHECK 白名单被重建，既有快照与行数据必须保留。"""
    legacy_db_path = tmp_path / "legacy-form-check.db"
    conn = sqlite3.connect(str(legacy_db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA user_version = 11")
    conn.execute(
        """
        CREATE TABLE deliverable_form_snapshots (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_key       TEXT NOT NULL UNIQUE,
            form_key           TEXT NOT NULL CHECK (form_key IN (
                'VPI-T2-D3', 'aras_paa', 'aras_ncr_progress', 'aras_ncr_detail'
            )),
            report_type        TEXT NOT NULL,
            source_run_id      INTEGER,
            source             TEXT NOT NULL DEFAULT '',
            snapshot_at        TEXT NOT NULL,
            row_count          INTEGER NOT NULL CHECK (row_count >= 0),
            schema_json        TEXT NOT NULL,
            summary_json       TEXT NOT NULL,
            charts_json        TEXT NOT NULL,
            artifacts_json     TEXT NOT NULL DEFAULT '[]',
            created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE deliverable_form_rows (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id     INTEGER NOT NULL,
            row_key         TEXT NOT NULL,
            row_number      INTEGER NOT NULL CHECK (row_number >= 1),
            sheet_name      TEXT NOT NULL DEFAULT '',
            values_json     TEXT NOT NULL,
            dimensions_json TEXT NOT NULL DEFAULT '{}',
            search_text     TEXT NOT NULL DEFAULT '',
            status_key      TEXT NOT NULL DEFAULT '',
            department_key  TEXT NOT NULL DEFAULT '',
            section_key     TEXT NOT NULL DEFAULT '',
            model_key       TEXT NOT NULL DEFAULT '',
            stage_key       TEXT NOT NULL DEFAULT '',
            submitted_date  TEXT,
            planned_date    TEXT,
            overdue_state   TEXT NOT NULL DEFAULT 'unknown'
                            CHECK (overdue_state IN ('on_time', 'overdue', 'unknown', 'not_applicable')),
            is_completed    INTEGER NOT NULL DEFAULT 0 CHECK (is_completed IN (0, 1)),
            cost_json       TEXT NOT NULL DEFAULT '{}',
            UNIQUE (snapshot_id, row_key),
            FOREIGN KEY (snapshot_id) REFERENCES deliverable_form_snapshots(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "INSERT INTO deliverable_form_snapshots "
        "(snapshot_key, form_key, report_type, snapshot_at, row_count, "
        "schema_json, summary_json, charts_json) "
        "VALUES ('legacy-ewo', 'VPI-T2-D3', 'ewo', '2026-09-01T00:00:00Z', 1, '{}', '{}', '{}')"
    )
    conn.execute(
        "INSERT INTO deliverable_form_rows "
        "(snapshot_id, row_key, row_number, values_json) "
        "VALUES (1, 'row-1', 1, '[]')"
    )
    conn.commit()
    conn.close()

    db = DatabaseManager(db_path=legacy_db_path)
    db.init_database()

    with db.get_connection() as c:
        ddl = c.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'deliverable_form_snapshots'"
        ).fetchone()["sql"] or ""
        assert "tdc_data_model" in ddl
        assert "deliverable_form_snapshots_rebuild" not in ddl
        assert not db.table_exists("deliverable_form_snapshots_rebuild")
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        assert c.execute("PRAGMA user_version").fetchone()[0] == 12
        ewo = c.execute(
            "SELECT form_key FROM deliverable_form_snapshots WHERE snapshot_key = 'legacy-ewo'"
        ).fetchone()
        assert ewo is not None
        rows = c.execute(
            "SELECT COUNT(*) FROM deliverable_form_rows WHERE row_key = 'row-1'"
        ).fetchone()[0]
        assert rows == 1
        index_row = c.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' "
            "AND name = 'idx_deliverable_form_snapshots_latest'"
        ).fetchone()
        assert index_row is not None

    # 新白名单立即生效：tdc_data_model 可写入并提交。
    with db.get_connection() as c:
        c.execute(
            "INSERT INTO deliverable_form_snapshots "
            "(snapshot_key, form_key, report_type, snapshot_at, row_count, "
            "schema_json, summary_json, charts_json) "
            "VALUES ('legacy-tdc', 'tdc_data_model', 'tdc_data_model', "
            "'2026-09-02T00:00:00Z', 0, '{}', '{}', '{}')"
        )
    with db.get_connection() as c:
        stored = c.execute(
            "SELECT COUNT(*) FROM deliverable_form_snapshots "
            "WHERE form_key = 'tdc_data_model'"
        ).fetchone()[0]
        assert stored == 1

    # 未知键仍被 CHECK 约束拒绝。
    with db.get_connection() as c:
        with pytest.raises(sqlite3.IntegrityError):
            c.execute(
                "INSERT INTO deliverable_form_snapshots "
                "(snapshot_key, form_key, report_type, snapshot_at, row_count, "
                "schema_json, summary_json, charts_json) "
                "VALUES ('bad-key', 'unknown_form', 'ewo', "
                "'2026-09-02T00:00:00Z', 0, '{}', '{}', '{}')"
            )


def test_excel_task_artifact_schema_contract(tmp_db: DatabaseManager) -> None:
    """Schema v5 stores only controlled artifact references and integrity metadata."""
    with tmp_db.get_connection() as conn:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(excel_task_artifacts)")
        }
        assert columns == {
            "id",
            "task_id",
            "run_id",
            "artifact_type",
            "root_id",
            "relative_path",
            "display_name",
            "size_bytes",
            "sha256",
            "created_at",
        }
        foreign_keys = {
            (row["from"], row["table"], row["to"], row["on_delete"])
            for row in conn.execute("PRAGMA foreign_key_list(excel_task_artifacts)")
        }
        assert ("task_id", "excel_tasks", "id", "CASCADE") in foreign_keys
        assert ("run_id", "excel_task_runs", "id", "CASCADE") in foreign_keys
        indices = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'index' AND tbl_name = 'excel_task_artifacts'"
            )
        }
        assert "idx_excel_task_artifacts_task" in indices
        triggers = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'trigger' AND tbl_name = 'excel_task_artifacts'"
            )
        }
        assert "trg_excel_task_artifact_run_matches_task" in triggers


def test_excel_artifact_download_audit_schema_contract(tmp_db: DatabaseManager) -> None:
    """Schema v6 creates excel_artifact_download_audit with foreign keys, constraints, index and trigger."""
    with tmp_db.get_connection() as conn:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(excel_artifact_download_audit)")
        }
        assert columns == {
            "id",
            "artifact_id",
            "task_id",
            "result",
            "reason_code",
            "served_size_bytes",
            "created_at",
        }
        foreign_keys = {
            (row["from"], row["table"], row["to"], row["on_delete"])
            for row in conn.execute("PRAGMA foreign_key_list(excel_artifact_download_audit)")
        }
        assert ("artifact_id", "excel_task_artifacts", "id", "CASCADE") in foreign_keys
        assert ("task_id", "excel_tasks", "id", "CASCADE") in foreign_keys
        indices = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'index' AND tbl_name = 'excel_artifact_download_audit'"
            )
        }
        assert "idx_excel_artifact_download_audit_artifact" in indices
        triggers = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'trigger' AND tbl_name = 'excel_artifact_download_audit'"
            )
        }
        assert "trg_excel_artifact_download_audit_artifact_matches_task" in triggers


def test_excel_task_files_composite_pk_and_no_id_column(tmp_db: DatabaseManager) -> None:
    """验证 excel_task_files 无多余 id 列，且 composite PK (task_id, role, ordinal) 生效。"""
    with tmp_db.get_connection() as conn:
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(excel_task_files)").fetchall()]
        assert "id" not in columns
        assert set(columns) == {"task_id", "role", "ordinal", "root_id", "relative_path"}

        # 插入父任务
        conn.execute(
            """
            INSERT INTO excel_tasks (operation, idempotency_key_hash, request_fingerprint)
            VALUES ('merge_append', ?, ?)
            """,
            ("a" * 64, "b" * 64),
        )
        task_id = conn.execute("SELECT id FROM excel_tasks WHERE idempotency_key_hash = ?", ("a" * 64,)).fetchone()[0]

        # 正常插入
        conn.execute(
            """
            INSERT INTO excel_task_files (task_id, role, ordinal, root_id, relative_path)
            VALUES (?, 'source', 0, 'default', 'file1.xlsx')
            """,
            (task_id,),
        )

        # 相同 (task_id, role, ordinal) 违反 Primary Key
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO excel_task_files (task_id, role, ordinal, root_id, relative_path)
                VALUES (?, 'source', 0, 'default', 'file2.xlsx')
                """,
                (task_id,),
            )


def test_excel_tasks_schema_check_constraints(tmp_db: DatabaseManager) -> None:
    """验证 Schema v5 数据库级 CHECK 约束。"""
    with tmp_db.get_connection() as conn:
        # 1. invalid operation
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO excel_tasks (operation, idempotency_key_hash, request_fingerprint)
                VALUES ('unsupported_op', ?, ?)
                """,
                ("1" * 64, "2" * 64),
            )

        # 2. invalid hash length
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO excel_tasks (operation, idempotency_key_hash, request_fingerprint)
                VALUES ('merge_append', 'short_hash', ?)
                """,
                ("2" * 64,),
            )

        # 3. invalid max_attempts
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO excel_tasks (operation, idempotency_key_hash, request_fingerprint, max_attempts)
                VALUES ('merge_append', ?, ?, 6)
                """,
                ("3" * 64, "4" * 64),
            )

        # 4. options_json length > 4096
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO excel_tasks (operation, idempotency_key_hash, request_fingerprint, options_json)
                VALUES ('merge_append', ?, ?, ?)
                """,
                ("5" * 64, "6" * 64, "{" + "a" * 4096 + "}"),
            )

        # 5. error_type length > 200
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO excel_tasks (operation, idempotency_key_hash, request_fingerprint, error_type)
                VALUES ('merge_append', ?, ?, ?)
                """,
                ("7" * 64, "8" * 64, "E" * 201),
            )

        # 6. excel_task_files root_id length > 128
        conn.execute(
            """
            INSERT INTO excel_tasks (operation, idempotency_key_hash, request_fingerprint)
            VALUES ('merge_append', ?, ?)
            """,
            ("9" * 64, "0" * 64),
        )
        task_id = conn.execute("SELECT id FROM excel_tasks WHERE idempotency_key_hash = ?", ("9" * 64,)).fetchone()[0]

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO excel_task_files (task_id, role, ordinal, root_id, relative_path)
                VALUES (?, 'source', 0, ?, 'valid.xlsx')
                """,
                (task_id, "r" * 129),
            )

        # 7. excel_task_runs run_state CHECK
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO excel_task_runs (task_id, attempt, run_state)
                VALUES (?, 1, 'invalid_run_state')
                """,
                (task_id,),
            )
