# -*- coding: utf-8 -*-
"""
tests/test_db_manager.py — DatabaseManager 单元测试（E2）

验收断言:
    1. 兜底项目 id=1 名称='未归类' 在 init_database() 后存在
    2. 重复调用 init_database() 不增加 projects 行数（幂等）
    3. get_connection() 在异常时回滚（无脏数据）
"""

from pathlib import Path

import pytest

from core.db_manager import DatabaseManager


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
    """所有必需表均应存在。"""
    for table in ("projects", "deliverables", "feishu_tasks"):
        assert tmp_db.table_exists(table), f"表 {table} 不存在"


def test_get_table_row_count(tmp_db: DatabaseManager) -> None:
    """projects 至少包含 id=1 兜底项目 + 预置的测试项目。"""
    count = tmp_db.get_table_row_count("projects")
    assert count >= 2, f"projects 行数应 ≥ 2，实际 {count}"
