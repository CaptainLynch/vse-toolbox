# -*- coding: utf-8 -*-
"""
tests/conftest.py — 公共 pytest fixtures

提供:
    tmp_db  — 使用 tmp_path 隔离的 DatabaseManager，
              init_database() 已调用，预置若干测试行。
              不污染真实 data/vse_toolbox.db。
"""

import pytest
from core.db_manager import DatabaseManager


@pytest.fixture
def tmp_db(tmp_path) -> DatabaseManager:
    """返回已初始化的隔离数据库，预置 projects + deliverables 测试数据。"""
    db = DatabaseManager(db_path=tmp_path / "test.db")
    db.init_database()

    with db.get_connection() as conn:
        # 追加一个真实项目（id=1 兜底项目已由 init_database 插入）
        conn.execute(
            "INSERT INTO projects (id, name, manager, status) VALUES (2, '测试项目', '测试员', 'active')"
        )
        conn.execute(
            "INSERT INTO deliverables (project_id, name, owner, due_date, status) "
            "VALUES (2, '交付物A', '负责人A', '2026-12-31', 'pending')"
        )
        conn.execute(
            "INSERT INTO deliverables (project_id, name, owner, due_date, status) "
            "VALUES (2, '交付物B', '负责人B', '2026-11-30', 'done')"
        )
        conn.execute(
            "INSERT INTO feishu_tasks (title, assignee, deadline, synced) "
            "VALUES ('飞书任务1', '张三', '2026-12-01', 0)"
        )
        conn.execute(
            "INSERT INTO feishu_tasks (title, assignee, deadline, synced) "
            "VALUES ('飞书任务2', '李四', '2026-12-15', 1)"
        )
        conn.commit()

    return db
