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


def test_schema_version_is_v14(tmp_db: DatabaseManager) -> None:
    """Version 14 prevents older executables from rewriting EWO v2 contracts."""
    assert CURRENT_SCHEMA_VERSION == 14
    with tmp_db.get_connection() as conn:
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
    assert ver == 14


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
        assert ver == CURRENT_SCHEMA_VERSION
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
        assert ver == CURRENT_SCHEMA_VERSION
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
        assert c.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION


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
    """验证高于 CURRENT_SCHEMA_VERSION 的库在执行 DDL 前被拒绝。"""
    future_version = CURRENT_SCHEMA_VERSION + 1
    future_db_path = tmp_path / "future_schema.db"
    conn = sqlite3.connect(str(future_db_path))
    conn.execute(f"PRAGMA user_version = {future_version}")
    conn.commit()
    conn.close()

    db = DatabaseManager(db_path=future_db_path)
    with pytest.raises(sqlite3.DatabaseError) as exc_info:
        db.init_database()
    assert f"unsupported schema version {future_version}" in str(exc_info.value)


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
        assert "form_key IN" not in ddl
        assert "deliverable_form_snapshots_rebuild" not in ddl
        assert not db.table_exists("deliverable_form_snapshots_rebuild")
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        assert c.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION
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

    # 表上已无 CHECK；未知键由写入前的注册表校验拒绝。
    with pytest.raises(ValueError):
        db.publish_deliverable_form_snapshot({
            "formKey": "unknown_form", "reportType": "ewo",
            "snapshotAt": "2026-09-02T00:00:00Z",
            "schema": {}, "summary": {}, "charts": {}, "rows": [],
        })


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


def test_form_snapshot_check_constraint_rebuild_allows_tdc_sor(
    tmp_path: Path,
) -> None:
    """只有 tdc_data_model 的中间版本旧库同样被重建以放行 tdc_sor。"""
    legacy_db_path = tmp_path / "legacy-sor-check.db"
    conn = sqlite3.connect(str(legacy_db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA user_version = 12")
    conn.execute(
        """
        CREATE TABLE deliverable_form_snapshots (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_key       TEXT NOT NULL UNIQUE,
            form_key           TEXT NOT NULL CHECK (form_key IN (
                'VPI-T2-D3', 'aras_paa', 'aras_ncr_progress', 'aras_ncr_detail',
                'tdc_data_model'
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
    conn.commit()
    conn.close()

    db = DatabaseManager(db_path=legacy_db_path)
    db.init_database()

    with db.get_connection() as c:
        ddl = c.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'deliverable_form_snapshots'"
        ).fetchone()["sql"] or ""
        assert "form_key IN" not in ddl
        assert "deliverable_form_snapshots_rebuild" not in ddl
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []


def test_reinit_preserves_configured_binding(tmp_path: Path) -> None:
    """终审测试缺口：存量绑定保护——重新 init_database 不得翻转
    已配置/已被用户动过的绑定（INSERT OR IGNORE 语义 + pristine 翻转
    仅覆盖从未动过的 manual 绑定）。"""
    db = DatabaseManager(tmp_path / "reinit-binding.db")
    db.init_database()
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings "
            "SET mode='automatic', enabled=1, external_key='KEEP-KEY', "
            "sync_state='success' WHERE deliverable_id='VPI-T2-D3'"
        )
        # 旧库手工数据（被用户动过：持有同步成功历史）：pristine 翻转
        # 迁移不得触碰，保持 manual。
        conn.execute(
            "UPDATE project_status_update_bindings "
            "SET mode='manual', enabled=0, external_key=NULL, "
            "last_success_at='2026-01-02T03:04:05.000Z' "
            "WHERE deliverable_id='VPI-T2-D2'"
        )
    db.init_database()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT mode, enabled, external_key, sync_state "
            "FROM project_status_update_bindings WHERE deliverable_id='VPI-T2-D3'"
        ).fetchone()
    assert row["mode"] == "automatic"
    assert row["enabled"] == 1
    assert row["external_key"] == "KEEP-KEY"
    assert row["sync_state"] == "success"
    with db.get_connection() as conn:
        manual_row = conn.execute(
            "SELECT mode, enabled FROM project_status_update_bindings "
            "WHERE deliverable_id='VPI-T2-D2'"
        ).fetchone()
    assert manual_row["mode"] == "manual"
    assert manual_row["enabled"] == 0


def test_pristine_manual_binding_flips_to_automatic_for_sync_capable(
    tmp_path: Path,
) -> None:
    """存量库幂等迁移：syncCapable 交付物（D2/D3/D5）从未动过的 pristine
    manual 绑定在再次 init_database 时翻转为 automatic；enabled 保持 0，
    不绕过证据/凭据门控。"""
    db = DatabaseManager(tmp_path / "pristine-flip.db")
    db.init_database()
    with db.get_connection() as conn:
        # 模拟老库：种子曾是 manual（source_type 补丁之前的行为）。
        conn.execute(
            "UPDATE project_status_update_bindings "
            "SET mode='manual' WHERE deliverable_id IN "
            "('VPI-T2-D2','VPI-T2-D3','VPI-T2-D5')"
        )
        conn.commit()

    db.init_database()  # 模拟应用升级后的再迁移

    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT deliverable_id, mode, enabled, external_key, "
            "match_rule_json, mapping_json, last_attempt_at, last_success_at "
            "FROM project_status_update_bindings "
            "WHERE deliverable_id IN ('VPI-T2-D2','VPI-T2-D3','VPI-T2-D5') "
            "ORDER BY deliverable_id"
        ).fetchall()
    assert [(r["deliverable_id"], r["mode"]) for r in rows] == [
        ("VPI-T2-D2", "automatic"),
        ("VPI-T2-D3", "automatic"),
        ("VPI-T2-D5", "automatic"),
    ]
    for row in rows:
        assert row["enabled"] == 0
        assert row["external_key"] is None
        assert row["match_rule_json"] == "{}"
        assert row["mapping_json"] == "{}"
        assert row["last_attempt_at"] is None
        assert row["last_success_at"] is None


def test_touched_manual_bindings_stay_manual_after_reinit(tmp_path: Path) -> None:
    """用户手工改过的绑定（任一 pristine 条件不满足）保持 manual：
    external_key / match_rule / mapping / last_attempt / enabled 任一被改过。"""
    db = DatabaseManager(tmp_path / "touched-manual.db")
    db.init_database()
    with db.get_connection() as conn:
        # 全部先变为 pristine manual（老库形态）。
        conn.execute(
            "UPDATE project_status_update_bindings SET mode='manual' "
            "WHERE deliverable_id IN ('VPI-T2-D2','VPI-T2-D3','VPI-T2-D5')"
        )
        # 再各自破坏一个 pristine 条件。
        conn.execute(
            "UPDATE project_status_update_bindings SET external_key='EWO-1' "
            "WHERE deliverable_id='VPI-T2-D3'"
        )
        conn.execute(
            "UPDATE project_status_update_bindings SET last_attempt_at='2026-09-01T00:00:00.000Z' "
            "WHERE deliverable_id='VPI-T2-D5'"
        )
        conn.execute(
            "UPDATE project_status_update_bindings SET match_rule_json='{\"reportType\": \"sor\"}' "
            "WHERE deliverable_id='VPI-T2-D2'"
        )
        conn.commit()

    db.init_database()

    with db.get_connection() as conn:
        modes = dict(
            conn.execute(
                "SELECT deliverable_id, mode FROM project_status_update_bindings "
                "WHERE deliverable_id IN ('VPI-T2-D2','VPI-T2-D3','VPI-T2-D5')"
            ).fetchall()
        )
    assert modes == {"VPI-T2-D2": "manual", "VPI-T2-D3": "manual", "VPI-T2-D5": "manual"}


def test_manual_only_and_contract_blocked_deliverables_stay_manual(
    tmp_path: Path,
) -> None:
    """D1（ManualOnly）与 D4（ContractBlocked）不受 pristine 翻转影响：
    即使处于 pristine manual 形态也保持 manual。"""
    db = DatabaseManager(tmp_path / "d1-d4-manual.db")
    db.init_database()
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET mode='manual' "
            "WHERE deliverable_id IN ('VPI-T2-D1','VPI-T2-D4')"
        )
        conn.commit()

    db.init_database()

    with db.get_connection() as conn:
        modes = dict(
            conn.execute(
                "SELECT deliverable_id, mode FROM project_status_update_bindings "
                "WHERE deliverable_id IN ('VPI-T2-D1','VPI-T2-D4')"
            ).fetchall()
        )
    assert modes == {"VPI-T2-D1": "manual", "VPI-T2-D4": "manual"}


def test_fresh_seed_sync_capable_bindings_are_automatic(tmp_db: DatabaseManager) -> None:
    """新库种子不受迁移影响：syncCapable 本就 automatic（D2/D3/D5 及同构后的 D6-D8）；
    无自动化连接器的 D1/D4 保持 manual 绑定。"""
    with tmp_db.get_connection() as conn:
        modes = dict(
            conn.execute(
                "SELECT deliverable_id, mode FROM project_status_update_bindings "
                "WHERE deliverable_id LIKE 'VPI-T2-D%' ORDER BY deliverable_id"
            ).fetchall()
        )
    assert modes == {
        "VPI-T2-D1": "manual",
        "VPI-T2-D2": "automatic",
        "VPI-T2-D3": "automatic",
        "VPI-T2-D4": "manual",
        "VPI-T2-D5": "automatic",
        "VPI-T2-D6": "automatic",
        "VPI-T2-D7": "automatic",
        "VPI-T2-D8": "automatic",
    }


def test_aggregate_binding_can_acquire_sync_lease_without_external_key(tmp_path: Path) -> None:
    """任务 1 行为测试：聚合绑定（matchRule.aggregate=true、无 external_key）
    必须能通过租约入口的运行时前置校验（修复前被 external_key 检查阻断）。"""
    import json

    db = DatabaseManager(tmp_path / "aggregate-lease.db")
    db.init_database()
    match_rule = {
        "reportType": "data_model", "aggregate": True, "incident": "FM-1",
    }
    db.set_project_status_update_policy(
        "VPI-T2-D5", mode="automatic", enabled=True, external_key=None,
        match_rule_json=json.dumps(match_rule), mapping_json=json.dumps({"owner": "currentApprover"}),
        field_authority={"owner": "automatic"}, credential_ref="test-alias",
    )
    with db.get_connection() as conn:
        binding_id = conn.execute(
            "SELECT id FROM project_status_update_bindings WHERE deliverable_id='VPI-T2-D5'"
        ).fetchone()["id"]

    # 修复前：SyncBindingNotReadyError（external_key is not confirmed）。
    lease = db.acquire_sync_lease(binding_id, trigger_type="sync_now")
    assert lease["run_id"] > 0

    # 非聚合绑定缺稳定键仍拒绝。
    db.set_project_status_update_policy(
        "VPI-T2-D3", mode="automatic", enabled=True, external_key=None,
        match_rule_json=json.dumps({"reportType": "ewo", "ewoNo": "EWO-1"}),
        mapping_json=json.dumps({"owner": "_rsp_name"}),
        field_authority={"owner": "automatic"}, credential_ref="test-alias",
    )
    with db.get_connection() as conn:
        d3_binding_id = conn.execute(
            "SELECT id FROM project_status_update_bindings WHERE deliverable_id='VPI-T2-D3'"
        ).fetchone()["id"]
    from core.db_manager import SyncBindingNotReadyError
    with pytest.raises(SyncBindingNotReadyError):
        db.acquire_sync_lease(d3_binding_id, trigger_type="sync_now")


def test_archive_lease_methods_execute_begin_immediate(tmp_path: Path) -> None:
    """acquire_archive_job_lease and finalize_archive_run must issue BEGIN IMMEDIATE first."""
    db = DatabaseManager(tmp_path / "test_immediate.db")
    db.init_database()
    executed_sql: list[str] = []

    orig_get_connection = db.get_connection

    from contextlib import contextmanager

    @contextmanager
    def tracked_get_connection():
        with orig_get_connection() as conn:
            conn.set_trace_callback(lambda s: executed_sql.append(str(s).strip()))
            yield conn

    db.get_connection = tracked_get_connection  # type: ignore[method-assign]

    # Enable an existing seeded archive job to lease
    with orig_get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM scheduled_archive_jobs WHERE enabled = 1 LIMIT 1"
        ).fetchone()
        job_id = row["id"] if row else 1
        conn.execute(
            "UPDATE scheduled_archive_jobs SET enabled = 1, credential_ref = 'cred_ref' WHERE id = ?",
            (job_id,),
        )

    executed_sql.clear()
    lease = db.acquire_archive_job_lease(job_id, "scheduled", validate_runtime_prerequisites=False)
    assert lease["lease_token"]
    assert executed_sql[0] == "BEGIN IMMEDIATE"

    executed_sql.clear()
    db.finalize_archive_run(
        job_id,
        lease["run_id"],
        lease["lease_token"],
        "failed",
        error_type="TestError",
        error_message="Test failure",
    )
    assert executed_sql[0] == "BEGIN IMMEDIATE"


def test_get_table_row_count_identifier_validation(tmp_path: Path) -> None:
    """get_table_row_count strictly rejects non-ASCII or invalid identifiers."""
    db = DatabaseManager(tmp_path / "test_ident.db")
    db.init_database()

    # Valid table returns >= 0
    assert db.get_table_row_count("projects") >= 0
    # Non-existent valid identifier returns -1
    assert db.get_table_row_count("non_existent_table") == -1
    # SQL injection / non-identifier patterns return -1 without querying
    assert db.get_table_row_count("projects; DROP TABLE projects;--") == -1
    assert db.get_table_row_count("table with spaces") == -1
    assert db.get_table_row_count("表名") == -1


def test_setup_cfg_decodable_with_cp936() -> None:
    """setup.cfg must be pure ASCII to prevent UnicodeDecodeError on Windows CP936/GBK systems."""
    setup_cfg = Path(__file__).resolve().parents[1] / "setup.cfg"
    assert setup_cfg.is_file()
    # Must decode cleanly under cp936 / gbk
    content = setup_cfg.read_text(encoding="cp936")
    assert "[flake8]" in content
    assert "[mypy]" in content


def _seed_deliverable_rows(db: DatabaseManager) -> list[sqlite3.Row]:
    with db.get_connection() as conn:
        return conn.execute(
            "SELECT id, display_code, name, status, planned_date, progress, "
            "       source, sort_order, phase_id "
            "FROM project_status_deliverables ORDER BY sort_order"
        ).fetchall()


def test_seed_includes_form_snapshot_driven_deliverables(tmp_db: DatabaseManager) -> None:
    """D6-D8（外部快照驱动）种子行：DEL-006/007/008、planned_date NULL、
    progress 0、sort_order 6/7/8、归属 VPI-T2。"""
    rows = _seed_deliverable_rows(tmp_db)
    assert [row["id"] for row in rows] == [
        "VPI-T2-D1", "VPI-T2-D2", "VPI-T2-D3", "VPI-T2-D4", "VPI-T2-D5",
        "VPI-T2-D6", "VPI-T2-D7", "VPI-T2-D8",
    ]
    assert [row["display_code"] for row in rows][-3:] == ["DEL-006", "DEL-007", "DEL-008"]
    for row in rows[-3:]:
        assert row["name"] in ("PAA 报告", "NCR 审批进度", "NCR 审批明细")
        assert row["planned_date"] is None
        assert row["progress"] == 0
        assert row["phase_id"] == "VPI-T2"
        assert row["source"].startswith("ARAS")


def test_seed_form_snapshot_driven_deliverables_idempotent(tmp_db: DatabaseManager) -> None:
    """重复 init_database() 后 D6-D8 仍为单行且 planned_date 保持 NULL。"""
    tmp_db.init_database()
    tmp_db.init_database()
    rows = _seed_deliverable_rows(tmp_db)
    assert len(rows) == 8
    assert all(row["planned_date"] is None for row in rows[-3:])


def test_legacy_planned_date_not_null_is_relaxed_by_rebuild(tmp_path: Path) -> None:
    """旧库 planned_date NOT NULL：迁移整表重建为可空列，数据保留、
    子表不受级联影响，随后 D6-D8 种子行可写入 NULL。"""
    db = DatabaseManager(db_path=tmp_path / "legacy-planned-date.db")
    db.init_database()
    with db.get_connection() as conn:
        # 还原旧库形态：planned_date 恢复 NOT NULL（SQLite 无法 ALTER，
        # 按旧 DDL 重建以模拟历史库）；D6-D8 是本次新增的种子行，先移除
        # 以模拟升级前的存量库。
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            """
            CREATE TABLE project_status_deliverables_legacy (
                id           TEXT PRIMARY KEY,
                display_code TEXT NOT NULL UNIQUE,
                phase_id     TEXT NOT NULL,
                name         TEXT NOT NULL,
                status       TEXT NOT NULL CHECK (status IN ('已完成', '进行中', '待审批', '已逾期')),
                owner        TEXT NOT NULL,
                planned_date TEXT NOT NULL,
                actual_date  TEXT,
                progress     INTEGER NOT NULL CHECK (progress BETWEEN 0 AND 100),
                remark       TEXT NOT NULL DEFAULT '',
                source       TEXT NOT NULL,
                department   TEXT NOT NULL DEFAULT '',
                stage        TEXT NOT NULL DEFAULT '',
                update_method TEXT NOT NULL DEFAULT 'manual',
                sort_order   INTEGER NOT NULL,
                updated_at   TEXT NOT NULL,
                FOREIGN KEY (phase_id) REFERENCES project_status_phases(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            INSERT INTO project_status_deliverables_legacy
                (id, display_code, phase_id, name, status, owner, planned_date,
                 actual_date, progress, remark, source, department, stage,
                 update_method, sort_order, updated_at)
            SELECT id, display_code, phase_id, name, status, owner, planned_date,
                 actual_date, progress, remark, source, department, stage,
                 update_method, sort_order, updated_at
            FROM project_status_deliverables
            WHERE id NOT IN ('VPI-T2-D6', 'VPI-T2-D7', 'VPI-T2-D8')
            """
        )
        conn.execute("DELETE FROM project_status_update_bindings WHERE deliverable_id IN ('VPI-T2-D6', 'VPI-T2-D7', 'VPI-T2-D8')")
        conn.execute("DROP TABLE project_status_deliverables")
        conn.execute(
            "ALTER TABLE project_status_deliverables_legacy "
            "RENAME TO project_status_deliverables"
        )
        conn.commit()
        conn.execute("PRAGMA foreign_keys=ON")

    db.init_database()

    with db.get_connection() as conn:
        notnull = {
            str(row["name"]): int(row["notnull"])
            for row in conn.execute("PRAGMA table_info(project_status_deliverables)")
        }["planned_date"]
        assert notnull == 0
        d1 = conn.execute(
            "SELECT planned_date FROM project_status_deliverables WHERE id = 'VPI-T2-D1'"
        ).fetchone()
        assert d1["planned_date"] == "2026-05-12"
        count = conn.execute("SELECT COUNT(*) FROM project_status_deliverables").fetchone()[0]
        assert count == 8
        # 子表数据未被级联清空。
        assert conn.execute("SELECT COUNT(*) FROM project_status_phases").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM project_status_update_bindings"
        ).fetchone()[0] == 8


def test_migration_backfills_null_config_signatures(tmp_path) -> None:
    """Test that init_database backfills missing config_signature on matched observations."""
    from services.project_status_records import compute_config_signature

    db = DatabaseManager(tmp_path / "migration-test.db")
    db.init_database()

    # Insert a binding and an observation with null config_signature
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings "
            "SET enabled = 1, match_rule_json = '{\"testKey\": \"testVal\"}' "
            "WHERE deliverable_id = 'VPI-T2-D2'"
        )
        conn.execute(
            "INSERT INTO project_status_mapping_observations "
            "(deliverable_id, source_type, result_state, candidate_count, candidate_fingerprint, config_signature) "
            "VALUES ('VPI-T2-D2', 'tdc', 'matched', 1, 'fp-1', NULL)"
        )
        conn.commit()

    # Re-run init_database (migration path)
    db.init_database()

    expected_sig = compute_config_signature("tdc", {"testKey": "testVal"})
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT config_signature FROM project_status_mapping_observations "
            "WHERE deliverable_id = 'VPI-T2-D2' AND candidate_fingerprint = 'fp-1'"
        ).fetchone()
        assert row is not None
        assert row["config_signature"] == expected_sig
