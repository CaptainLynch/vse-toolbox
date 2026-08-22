# -*- coding: utf-8 -*-
"""
tests/test_db_manager.py — DatabaseManager 单元测试（E2）

验收断言:
    1. 兜底项目 id=1 名称='未归类' 在 init_database() 后存在
    2. 重复调用 init_database() 不增加 projects 行数（幂等）
    3. get_connection() 在异常时回滚（无脏数据）
    4. Excel Phase A schema v4 可新建、迁移并保持初始化幂等
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
    """所有必需表均应存在（含 Schema v4 Excel 任务表）。"""
    for table in (
        "projects",
        "deliverables",
        "feishu_tasks",
        "excel_tasks",
        "excel_task_files",
        "excel_task_runs",
    ):
        assert tmp_db.table_exists(table), f"表 {table} 不存在"


def test_get_table_row_count(tmp_db: DatabaseManager) -> None:
    """projects 至少包含 id=1 兜底项目 + 预置的测试项目。"""
    count = tmp_db.get_table_row_count("projects")
    assert count >= 2, f"projects 行数应 ≥ 2，实际 {count}"


def test_schema_version_is_v4(tmp_db: DatabaseManager) -> None:
    """验证当前支持的 schema 版本为 4。"""
    assert CURRENT_SCHEMA_VERSION == 4
    with tmp_db.get_connection() as conn:
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
    assert ver == 4


def test_v3_to_v4_migration(tmp_path: Path) -> None:
    """验证从已存在的 v3 数据库平滑升级到 v4。"""
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
        assert ver == 4
        assert db.table_exists("excel_tasks")
        assert db.table_exists("excel_task_files")
        assert db.table_exists("excel_task_runs")
        row = c.execute("SELECT name FROM projects WHERE id = 1").fetchone()
        assert row[0] == "未归类"


def test_rejects_newer_schema_version(tmp_path: Path) -> None:
    """验证高于 CURRENT_SCHEMA_VERSION (如 v5) 的库在执行 DDL 前被拒绝。"""
    v5_db_path = tmp_path / "v5_future.db"
    conn = sqlite3.connect(str(v5_db_path))
    conn.execute("PRAGMA user_version = 5")
    conn.commit()
    conn.close()

    db = DatabaseManager(db_path=v5_db_path)
    with pytest.raises(sqlite3.DatabaseError) as exc_info:
        db.init_database()
    assert "unsupported schema version 5" in str(exc_info.value)


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
    """验证 Schema v4 数据库级 CHECK 约束。"""
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
