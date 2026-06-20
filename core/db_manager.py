# -*- coding: utf-8 -*-
"""
core/db_manager.py — SQLite 数据库连接管理与 ORM 表结构初始化

职责:
    1. 管理 SQLite 连接的生命周期（上下文管理器）
    2. 初始化 / 迁移所有业务表结构
    3. 提供统一的数据访问入口，禁止各 service 裸连数据库

架构约束:
    - 使用 WAL 模式提升并发读写性能
    - 所有表使用 ISO-8601 时间戳
    - 启用外键约束 (PRAGMA foreign_keys = ON)
"""

import sqlite3
import logging
from pathlib import Path
from contextlib import contextmanager
from typing import Generator

from core.runtime_paths import app_root

logger = logging.getLogger("vse_toolbox.db_manager")

# ── 默认数据库路径 ──────────────────────────────────────────────
DEFAULT_DB_DIR = app_root() / "data"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "vse_toolbox.db"

# ── 建表 DDL ───────────────────────────────────────────────────
# 每张表均包含 created_at / updated_at 以便追踪
TABLE_DEFINITIONS: list[str] = [
    # 项目主表
    """
    CREATE TABLE IF NOT EXISTS projects (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT    NOT NULL,
        manager     TEXT,
        status      TEXT    DEFAULT 'active'
                            CHECK (status IN ('active', 'archived')),
        created_at  TEXT    DEFAULT (datetime('now', 'localtime')),
        updated_at  TEXT    DEFAULT (datetime('now', 'localtime'))
    );
    """,
    # 交付物明细表
    """
    CREATE TABLE IF NOT EXISTS deliverables (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id  INTEGER NOT NULL,
        name        TEXT    NOT NULL,
        owner       TEXT,
        due_date    TEXT,
        status      TEXT    DEFAULT 'pending'
                            CHECK (status IN ('pending', 'in_progress', 'done', 'blocked')),
        remark      TEXT,
        created_at  TEXT    DEFAULT (datetime('now', 'localtime')),
        updated_at  TEXT    DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    );
    """,
    # 飞书待办解析表
    """
    CREATE TABLE IF NOT EXISTS feishu_tasks (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        title           TEXT,
        assignee        TEXT,
        deadline        TEXT,
        source_email_id TEXT,
        parsed_at       TEXT    DEFAULT (datetime('now', 'localtime')),
        synced          INTEGER DEFAULT 0
    );
    """,
    # NCR明细表
    """
    CREATE TABLE IF NOT EXISTS ncr_details (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ncr_name        TEXT NOT NULL,
        project_name    TEXT,
        part_number     TEXT,
        part_name       TEXT,
        change_type     TEXT,
        quantity        TEXT,
        cost_change     TEXT,
        pr_number       TEXT,
        po_number       TEXT,
        created_at      TEXT DEFAULT (datetime('now', 'localtime'))
    );
    """

]


class DatabaseManager:
    """
    SQLite 数据库管理器

    用法:
        db = DatabaseManager()
        db.init_database()

        with db.get_connection() as conn:
            conn.execute("SELECT * FROM projects")
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        """
        初始化数据库管理器。

        Args:
            db_path: SQLite 文件路径。为 None 时使用默认路径 data/vse_toolbox.db
        """
        self._db_path = Path(db_path) if db_path else DEFAULT_DB_PATH

        # 确保 data/ 目录存在
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info("数据库路径: %s", self._db_path)

    @property
    def db_path(self) -> Path:
        """返回当前数据库文件路径"""
        return self._db_path

    def init_database(self) -> None:
        """
        初始化数据库: 创建表结构、启用 WAL 模式和外键约束。

        幂等操作，重复调用不会破坏已有数据。
        """
        try:
            with self.get_connection() as conn:
                # 启用 WAL 模式 — 提升并发读写性能
                conn.execute("PRAGMA journal_mode=WAL;")
                # 启用外键约束
                conn.execute("PRAGMA foreign_keys=ON;")

                # 执行所有建表 DDL
                for ddl in TABLE_DEFINITIONS:
                    conn.execute(ddl)

                # 幂等插入 id=1「未归类」兜底项目，防止 deliverables.project_id 外键孤儿
                conn.execute(
                    "INSERT OR IGNORE INTO projects (id, name, manager, status) "
                    "VALUES (1, '未归类', 'system', 'active');"
                )

                conn.commit()

            logger.info("数据库初始化完成")

        except sqlite3.Error:
            logger.exception("数据库初始化失败")
            raise

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        获取数据库连接的上下文管理器。

        自动处理:
            - 设置 row_factory = sqlite3.Row (支持字典式访问)
            - 启用外键约束
            - 正常退出时 commit，异常时 rollback
            - 无论何种情况都确保连接关闭

        Yields:
            sqlite3.Connection: 已配置好的数据库连接

        Raises:
            sqlite3.Error: 数据库操作异常
        """
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(
                str(self._db_path),
                timeout=10,  # 等待锁的超时时间（秒）
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON;")

            yield conn

            conn.commit()

        except sqlite3.Error:
            if conn:
                conn.rollback()
            logger.exception("数据库事务回滚")
            raise

        finally:
            if conn:
                conn.close()

    def execute_script(self, script: str) -> None:
        """
        执行多条 SQL 语句（用于迁移脚本）。

        Args:
            script: 包含多条 SQL 语句的字符串，以分号分隔

        Raises:
            sqlite3.Error: SQL 执行异常
        """
        try:
            with self.get_connection() as conn:
                conn.executescript(script)
            logger.info("SQL 脚本执行成功")
        except sqlite3.Error:
            logger.exception("SQL 脚本执行失败")
            raise

    def table_exists(self, table_name: str) -> bool:
        """
        检查指定表是否存在。

        Args:
            table_name: 表名

        Returns:
            True 如果表存在，否则 False
        """
        try:
            with self.get_connection() as conn:
                result = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table_name,),
                ).fetchone()
                return result is not None
        except sqlite3.Error as e:
            logger.error("检查表 %s 是否存在时出错: %s", table_name, e)
            return False

    def get_table_row_count(self, table_name: str) -> int:
        """
        获取指定表的行数。

        Args:
            table_name: 表名

        Returns:
            表中的行数，表不存在时返回 -1
        """
        if not self.table_exists(table_name):
            return -1
        try:
            with self.get_connection() as conn:
                # SQLite 不支持参数化表名，用 table_exists 预验证后拼接
                # table_name 已经过 table_exists 白名单验证，无 SQL 注入风险
                result = conn.execute(  # nosec: table_name validated by table_exists
                    f"SELECT COUNT(*) FROM {table_name}"
                ).fetchone()
                return result[0] if result else 0
        except sqlite3.Error as e:
            logger.error("获取表 %s 行数时出错: %s", table_name, e)
            return -1
