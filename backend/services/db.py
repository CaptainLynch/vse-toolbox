import json
import logging
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("VSE_TOOLBOX.db")

BASE_DIR = Path(__file__).parent.parent

from config import DATA_DIR

DB_PATH = DATA_DIR / "VSE_TOOLBOX.db"

SCHEMA_SQL = """
-- 问题追踪表（含零件总成/子系统/原因分析/措施/断点/行动计划/source）
CREATE TABLE IF NOT EXISTS issues (
    id TEXT PRIMARY KEY,
    priority TEXT CHECK(priority IN ('P0','P1','P2','P3')),
    component TEXT NOT NULL,
    description TEXT NOT NULL,
    department TEXT NOT NULL,
    status TEXT CHECK(status IN ('open','in_progress','resolved','closed')),
    assignee TEXT,
    part_system TEXT,
    sub_system TEXT,
    root_cause TEXT,
    short_term_action TEXT,
    long_term_action TEXT,
    cutoff_point TEXT,
    action_plan TEXT,
    source TEXT DEFAULT 'manual',
    source_file TEXT,
    created_at TEXT,
    updated_at TEXT
);

-- 里程碑进度表（含实际完成节点）
CREATE TABLE IF NOT EXISTS milestones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    percentage INTEGER DEFAULT 0,
    target_date TEXT,
    actual_date TEXT,
    actual_percentage INTEGER DEFAULT 0
);

-- 飞书邮件缓存表
CREATE TABLE IF NOT EXISTS feishu_mails (
    id TEXT PRIMARY KEY,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    preview TEXT,
    content TEXT,
    category TEXT,
    is_read INTEGER DEFAULT 0,
    is_starred INTEGER DEFAULT 0,
    has_attachment INTEGER DEFAULT 0,
    received_at TEXT
);

-- 待办任务表
CREATE TABLE IF NOT EXISTS todos (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    source TEXT,
    deadline TEXT,
    completed INTEGER DEFAULT 0,
    created_at TEXT
);

-- Deliverable categories
CREATE TABLE IF NOT EXISTS deliverable_categories (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    icon TEXT,
    sort_order INTEGER DEFAULT 0,
    is_visible INTEGER DEFAULT 1,
    created_at TEXT
);

-- Seed deliverable categories
INSERT OR IGNORE INTO deliverable_categories (id, name, icon, sort_order, is_visible, created_at) VALUES
  ('issues', '造车问题', 'ClipboardList', 1, 1, datetime('now')),
  ('ewo', 'EWO/NCR', 'AlertTriangle', 2, 1, datetime('now')),
  ('tir', 'TIR', 'FileText', 3, 1, datetime('now'));

-- Dashboard card layouts
CREATE TABLE IF NOT EXISTS dashboard_layouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT DEFAULT 'default',
    page_key TEXT NOT NULL,
    card_id TEXT NOT NULL,
    card_type TEXT NOT NULL,
    x INTEGER NOT NULL DEFAULT 0,
    y INTEGER NOT NULL DEFAULT 0,
    w INTEGER NOT NULL DEFAULT 1,
    h INTEGER NOT NULL DEFAULT 1,
    config TEXT,
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(user_id, page_key, card_id)
);

-- EWO/NCR records（含 source/source_file）
CREATE TABLE IF NOT EXISTS ewo_ncr (
    id TEXT PRIMARY KEY,
    type TEXT CHECK(type IN ('EWO','NCR')),
    title TEXT NOT NULL,
    description TEXT,
    severity TEXT CHECK(severity IN ('critical','major','minor')),
    status TEXT CHECK(status IN ('open','investigating','resolved','closed')),
    department TEXT,
    assignee TEXT,
    raised_date TEXT,
    target_date TEXT,
    source TEXT DEFAULT 'manual',
    source_file TEXT,
    created_at TEXT,
    updated_at TEXT
);

-- TIR records（含 source/source_file）
CREATE TABLE IF NOT EXISTS tir (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    category TEXT,
    status TEXT CHECK(status IN ('draft','submitted','approved','rejected')),
    department TEXT,
    assignee TEXT,
    test_date TEXT,
    result TEXT,
    source TEXT DEFAULT 'manual',
    source_file TEXT,
    created_at TEXT,
    updated_at TEXT
);

-- 零件总成→子系统映射表
CREATE TABLE IF NOT EXISTS lookup_part_system (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part_system TEXT NOT NULL UNIQUE,
    sub_system TEXT NOT NULL,
    created_at TEXT
);

-- 工程师→科室映射表
CREATE TABLE IF NOT EXISTS lookup_engineer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    department TEXT NOT NULL,
    created_at TEXT
);

-- 应用配置表
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT
);
"""


@contextmanager
def get_connection():
    """提供 SQLite 连接的上下文管理器，确保正确关闭。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = None
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


_VALID_TABLES = {"issues", "milestones", "ewo_ncr", "tir", "feishu_mails", "todos",
                  "deliverable_categories", "dashboard_layouts",
                  "lookup_part_system", "lookup_engineer", "app_settings"}

_VALID_COLUMN_DEFS = {"TEXT", "TEXT DEFAULT 'manual'", "INTEGER DEFAULT 0", "INTEGER"}


def _validate_identifier(name: str):
    """验证 SQL 标识符仅含安全字符。"""
    if not name.replace("_", "").isalnum():
        raise ValueError(f"Invalid SQL identifier: {name}")


def _table_columns(conn, table_name: str) -> set[str]:
    """获取指定表的已有列名集合。"""
    _validate_identifier(table_name)
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] for row in rows}


def _add_column_if_missing(conn, table: str, column: str, col_def: str):
    """安全添加列：仅当列不存在时执行 ALTER TABLE。"""
    _validate_identifier(table)
    _validate_identifier(column)
    if col_def not in _VALID_COLUMN_DEFS:
        raise ValueError(f"Invalid column definition: {col_def}")
    existing = _table_columns(conn, table)
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
        logger.info("Migration: added %s.%s (%s)", table, column, col_def)


def evolve_schema():
    """增量迁移：为已有数据库安全添加新列和新表。"""
    with get_connection() as conn:
        # --- B-24: issues 表新增 9 列 ---
        _add_column_if_missing(conn, "issues", "part_system", "TEXT")
        _add_column_if_missing(conn, "issues", "sub_system", "TEXT")
        _add_column_if_missing(conn, "issues", "root_cause", "TEXT")
        _add_column_if_missing(conn, "issues", "short_term_action", "TEXT")
        _add_column_if_missing(conn, "issues", "long_term_action", "TEXT")
        _add_column_if_missing(conn, "issues", "cutoff_point", "TEXT")
        _add_column_if_missing(conn, "issues", "action_plan", "TEXT")
        _add_column_if_missing(conn, "issues", "source", "TEXT DEFAULT 'manual'")
        _add_column_if_missing(conn, "issues", "source_file", "TEXT")

        # --- B-25: milestones 表新增 actual_date / actual_percentage ---
        _add_column_if_missing(conn, "milestones", "actual_date", "TEXT")
        _add_column_if_missing(conn, "milestones", "actual_percentage", "INTEGER DEFAULT 0")

        # --- B-26: ewo_ncr / tir 表新增 source / source_file ---
        _add_column_if_missing(conn, "ewo_ncr", "source", "TEXT DEFAULT 'manual'")
        _add_column_if_missing(conn, "ewo_ncr", "source_file", "TEXT")
        _add_column_if_missing(conn, "tir", "source", "TEXT DEFAULT 'manual'")
        _add_column_if_missing(conn, "tir", "source_file", "TEXT")

        # --- B-27: 新增 3 张表 ---
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS lookup_part_system (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                part_system TEXT NOT NULL UNIQUE,
                sub_system TEXT NOT NULL,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS lookup_engineer (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                department TEXT NOT NULL,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT
            );
        """)

        conn.commit()
    logger.info("Schema evolution completed")


def init_schema():
    """初始化数据库 Schema，然后执行增量迁移。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    evolve_schema()
    logger.info("Database schema initialized at %s", DB_PATH)


class DBManager:
    """SQLite CRUD 封装。所有查询使用参数化，禁止字符串拼接 SQL。"""

    # ------------------------------------------------------------------
    # issues
    # ------------------------------------------------------------------

    @staticmethod
    def generate_issue_id() -> str:
        now = datetime.now()
        suffix = uuid.uuid4().hex[:6]
        return f"ISS-{now.strftime('%Y')}-{now.strftime('%m%d%H%M%S')}-{suffix}"

    @staticmethod
    def create_issue(data: dict) -> dict:
        issue_id = DBManager.generate_issue_id()
        now = datetime.now().isoformat()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO issues (id, priority, component, description, department, status, assignee,
                    part_system, sub_system, root_cause, short_term_action, long_term_action,
                    cutoff_point, action_plan, source, source_file, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    issue_id,
                    data.get("priority", "P1"),
                    data["component"],
                    data["description"],
                    data["department"],
                    data.get("status", "open"),
                    data.get("assignee"),
                    data.get("part_system"),
                    data.get("sub_system"),
                    data.get("root_cause"),
                    data.get("short_term_action"),
                    data.get("long_term_action"),
                    data.get("cutoff_point"),
                    data.get("action_plan"),
                    data.get("source", "manual"),
                    data.get("source_file"),
                    now,
                    now,
                ),
            )
            conn.commit()
        return DBManager.get_issue_by_id(issue_id)

    @staticmethod
    def get_issue_by_id(issue_id: str) -> dict | None:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM issues WHERE id = ?", (issue_id,)
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_issues(
        page: int = 1,
        size: int = 20,
        priority: str | None = None,
        status: str | None = None,
        department: str | None = None,
    ) -> tuple[list[dict], int]:
        conditions = []
        params: list = []

        if priority:
            conditions.append("priority = ?")
            params.append(priority)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if department:
            conditions.append("department = ?")
            params.append(department)

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        with get_connection() as conn:
            total_row = conn.execute(
                f"SELECT COUNT(*) FROM issues {where_clause}", params
            ).fetchone()
            total = total_row[0] if total_row else 0

            offset = (page - 1) * size
            rows = conn.execute(
                f"""
                SELECT * FROM issues {where_clause}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                params + [size, offset],
            ).fetchall()

        items = [dict(row) for row in rows]
        return items, total

    @staticmethod
    def update_issue(issue_id: str, data: dict) -> dict | None:
        allowed = {
            "priority", "component", "description", "department", "status", "assignee",
            "part_system", "sub_system", "root_cause", "short_term_action", "long_term_action",
            "cutoff_point", "action_plan", "source", "source_file",
        }
        updates = {k: v for k, v in data.items() if k in allowed and v is not None}
        if not updates:
            return DBManager.get_issue_by_id(issue_id)

        updates["updated_at"] = datetime.now().isoformat()
        fields = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [issue_id]

        with get_connection() as conn:
            conn.execute(
                f"UPDATE issues SET {fields} WHERE id = ?",
                values,
            )
            conn.commit()
        return DBManager.get_issue_by_id(issue_id)

    @staticmethod
    def delete_issue(issue_id: str) -> bool:
        with get_connection() as conn:
            cursor = conn.execute("DELETE FROM issues WHERE id = ?", (issue_id,))
            conn.commit()
            return cursor.rowcount > 0

    @staticmethod
    def get_issue_stats() -> dict:
        with get_connection() as conn:
            total_open = conn.execute(
                "SELECT COUNT(*) FROM issues WHERE status IN ('open', 'in_progress')"
            ).fetchone()[0]

            # 本周新增（从本周一开始）
            today = datetime.now()
            week_start = today.replace(hour=0, minute=0, second=0, microsecond=0)
            while week_start.weekday() != 0:
                week_start -= timedelta(days=1)
            week_start_iso = week_start.isoformat()

            new_this_week = conn.execute(
                "SELECT COUNT(*) FROM issues WHERE created_at >= ?",
                (week_start_iso,),
            ).fetchone()[0]

            closed_this_week = conn.execute(
                "SELECT COUNT(*) FROM issues WHERE status = 'closed' AND updated_at >= ?",
                (week_start_iso,),
            ).fetchone()[0]

            high_risk = conn.execute(
                "SELECT COUNT(*) FROM issues WHERE priority = 'P0' AND status IN ('open', 'in_progress')"
            ).fetchone()[0]

            dept_rows = conn.execute(
                """
                SELECT department,
                       COUNT(*) as total,
                       SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) as closed
                FROM issues
                GROUP BY department
                ORDER BY total DESC
                """
            ).fetchall()

            department_stats = []
            for row in dept_rows:
                dept, total, closed = row
                rate = round((closed / total) * 100) if total > 0 else 0
                department_stats.append({
                    "department": dept,
                    "closed_rate": rate,
                    "total_issues": total,
                })

            # 最近 14 天趋势
            trend = []
            for i in range(13, -1, -1):
                day = (today - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
                day_start = day.strftime("%Y-%m-%d")
                count = conn.execute(
                    "SELECT COUNT(*) FROM issues WHERE created_at LIKE ?",
                    (f"{day_start}%",),
                ).fetchone()[0]
                trend.append({
                    "date": day.strftime("%m-%d"),
                    "count": count,
                })

        return {
            "total_open": total_open,
            "new_this_week": new_this_week,
            "closed_this_week": closed_this_week,
            "high_risk_count": high_risk,
            "department_stats": department_stats,
            "trend": trend,
        }

    # ------------------------------------------------------------------
    # milestones
    # ------------------------------------------------------------------

    @staticmethod
    def list_milestones() -> list[dict]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM milestones ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def create_milestone(data: dict) -> dict:
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO milestones (name, category, percentage, target_date, actual_date, actual_percentage)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    data["name"],
                    data["category"],
                    data.get("percentage", 0),
                    data.get("target_date"),
                    data.get("actual_date"),
                    data.get("actual_percentage", 0),
                ),
            )
            conn.commit()
            milestone_id = cursor.lastrowid
            row = conn.execute(
                "SELECT * FROM milestones WHERE id = ?", (milestone_id,)
            ).fetchone()
        return dict(row) if row else {"id": milestone_id}

    @staticmethod
    def update_milestone(milestone_id: int, data: dict) -> dict | None:
        allowed = {"name", "category", "percentage", "target_date", "actual_date", "actual_percentage"}
        updates = {k: v for k, v in data.items() if k in allowed and v is not None}
        if not updates:
            return None
        fields = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [milestone_id]
        with get_connection() as conn:
            conn.execute(
                f"UPDATE milestones SET {fields} WHERE id = ?",
                values,
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM milestones WHERE id = ?", (milestone_id,)
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def delete_milestone(milestone_id: int) -> bool:
        with get_connection() as conn:
            cursor = conn.execute("DELETE FROM milestones WHERE id = ?", (milestone_id,))
            conn.commit()
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # feishu mails
    # ------------------------------------------------------------------

    @staticmethod
    def save_mails(mails: list[dict]) -> tuple[int, int]:
        new_count = 0
        with get_connection() as conn:
            for mail in mails:
                existing = conn.execute(
                    "SELECT 1 FROM feishu_mails WHERE id = ?", (mail["id"],)
                ).fetchone()
                if existing:
                    continue
                conn.execute(
                    """
                    INSERT INTO feishu_mails (id, sender, subject, preview, content,
                                              category, is_read, is_starred, has_attachment, received_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        mail["id"],
                        mail["sender"],
                        mail["subject"],
                        mail.get("preview"),
                        mail.get("content"),
                        mail.get("category"),
                        1 if mail.get("is_read") else 0,
                        1 if mail.get("is_starred") else 0,
                        1 if mail.get("has_attachment") else 0,
                        mail.get("received_at", datetime.now().isoformat()),
                    ),
                )
                new_count += 1
            conn.commit()
        return len(mails), new_count

    @staticmethod
    def list_mails(
        page: int = 1,
        size: int = 20,
        category: str | None = None,
        is_read: int | None = None,
    ) -> tuple[list[dict], int]:
        conditions = []
        params: list = []
        if category:
            conditions.append("category = ?")
            params.append(category)
        if is_read is not None:
            conditions.append("is_read = ?")
            params.append(is_read)

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        with get_connection() as conn:
            total_row = conn.execute(
                f"SELECT COUNT(*) FROM feishu_mails {where_clause}", params
            ).fetchone()
            total = total_row[0] if total_row else 0

            offset = (page - 1) * size
            rows = conn.execute(
                f"""
                SELECT id, sender, subject, preview, received_at as date,
                       is_read, is_starred, has_attachment, category
                FROM feishu_mails {where_clause}
                ORDER BY received_at DESC
                LIMIT ? OFFSET ?
                """,
                params + [size, offset],
            ).fetchall()

        items = []
        for row in rows:
            d = dict(row)
            d["is_read"] = bool(d["is_read"])
            d["is_starred"] = bool(d["is_starred"])
            d["has_attachment"] = bool(d["has_attachment"])
            items.append(d)
        return items, total

    @staticmethod
    def clear_mails() -> int:
        with get_connection() as conn:
            cursor = conn.execute("DELETE FROM feishu_mails")
            conn.commit()
            return cursor.rowcount

    # ------------------------------------------------------------------
    # todos
    # ------------------------------------------------------------------

    @staticmethod
    def save_todos(todos: list[dict]) -> int:
        count = 0
        with get_connection() as conn:
            for todo in todos:
                existing = conn.execute(
                    "SELECT 1 FROM todos WHERE id = ?", (todo["id"],)
                ).fetchone()
                if existing:
                    continue
                conn.execute(
                    """
                    INSERT INTO todos (id, content, source, deadline, completed, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        todo["id"],
                        todo["content"],
                        todo.get("source"),
                        todo.get("deadline"),
                        1 if todo.get("completed") else 0,
                        todo.get("created_at", datetime.now().isoformat()),
                    ),
                )
                count += 1
            conn.commit()
        return count

    @staticmethod
    def list_todos() -> list[dict]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, content, source, deadline, completed, created_at
                FROM todos ORDER BY created_at DESC
                """
            ).fetchall()
        items = []
        for row in rows:
            d = dict(row)
            d["completed"] = bool(d["completed"])
            items.append(d)
        return items

    @staticmethod
    def toggle_todo(todo_id: str) -> dict | None:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT completed FROM todos WHERE id = ?", (todo_id,)
            ).fetchone()
            if not row:
                return None
            new_status = 0 if row[0] else 1
            conn.execute(
                "UPDATE todos SET completed = ? WHERE id = ?",
                (new_status, todo_id),
            )
            conn.commit()
        return {"id": todo_id, "completed": bool(new_status)}

    @staticmethod
    def clear_todos() -> int:
        with get_connection() as conn:
            cursor = conn.execute("DELETE FROM todos")
            conn.commit()
            return cursor.rowcount


    # ------------------------------------------------------------------
    # deliverable categories
    # ------------------------------------------------------------------

    @staticmethod
    def list_deliverable_categories() -> list[dict]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM deliverable_categories WHERE is_visible = 1 ORDER BY sort_order"
            ).fetchall()
        items = []
        for row in rows:
            d = dict(row)
            d["is_visible"] = bool(d["is_visible"])
            items.append(d)
        return items

    @staticmethod
    def create_deliverable_category(data: dict) -> dict:
        now = datetime.now().isoformat()
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO deliverable_categories (id, name, icon, sort_order, is_visible, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (data["id"], data["name"], data.get("icon"), data.get("sort_order", 0), 1, now),
            )
            conn.commit()
        return data

    @staticmethod
    def update_deliverable_category(cat_id: str, data: dict) -> dict | None:
        allowed = {"name", "icon", "sort_order", "is_visible"}
        updates = {k: v for k, v in data.items() if k in allowed and v is not None}
        if not updates:
            return None
        fields = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [cat_id]
        with get_connection() as conn:
            conn.execute(f"UPDATE deliverable_categories SET {fields} WHERE id = ?", values)
            conn.commit()
            row = conn.execute("SELECT * FROM deliverable_categories WHERE id = ?", (cat_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def delete_deliverable_category(cat_id: str) -> bool:
        with get_connection() as conn:
            cursor = conn.execute("DELETE FROM deliverable_categories WHERE id = ?", (cat_id,))
            conn.commit()
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # dashboard layouts
    # ------------------------------------------------------------------

    @staticmethod
    def get_layouts(page_key: str, user_id: str = "default") -> list[dict]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM dashboard_layouts WHERE user_id = ? AND page_key = ?",
                (user_id, page_key),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def save_layouts(page_key: str, layouts: list[dict], user_id: str = "default") -> int:
        now = datetime.now().isoformat()
        count = 0
        with get_connection() as conn:
            for card in layouts:
                conn.execute(
                    """INSERT INTO dashboard_layouts (user_id, page_key, card_id, card_type, x, y, w, h, config, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, page_key, card_id) DO UPDATE SET
                        card_type=excluded.card_type, x=excluded.x, y=excluded.y,
                        w=excluded.w, h=excluded.h, config=excluded.config, updated_at=excluded.updated_at""",
                    (user_id, page_key, card["card_id"], card.get("card_type", "custom"),
                     card.get("x", 0), card.get("y", 0), card.get("w", 1), card.get("h", 1),
                     card.get("config"), now, now),
                )
                count += 1
            conn.commit()
        return count

    # ------------------------------------------------------------------
    # EWO/NCR
    # ------------------------------------------------------------------

    @staticmethod
    def generate_ewo_id(ewo_type: str = "EWO") -> str:
        now = datetime.now()
        suffix = uuid.uuid4().hex[:4]
        return f"{ewo_type}-{now.strftime('%Y')}-{now.strftime('%m%d')}-{suffix}"

    @staticmethod
    def create_ewo(data: dict) -> dict:
        ewo_id = DBManager.generate_ewo_id(data.get("type", "EWO"))
        now = datetime.now().isoformat()
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO ewo_ncr (id, type, title, description, severity, status, department, assignee,
                    raised_date, target_date, source, source_file, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ewo_id, data.get("type", "EWO"), data["title"], data.get("description"),
                 data.get("severity", "minor"), data.get("status", "open"), data.get("department"),
                 data.get("assignee"), data.get("raised_date"), data.get("target_date"),
                 data.get("source", "manual"), data.get("source_file"), now, now),
            )
            conn.commit()
        return DBManager.get_ewo_by_id(ewo_id)

    @staticmethod
    def get_ewo_by_id(ewo_id: str) -> dict | None:
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM ewo_ncr WHERE id = ?", (ewo_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_ewos(page: int = 1, size: int = 20, status: str | None = None, severity: str | None = None) -> tuple[list[dict], int]:
        conditions, params = [], []
        if status:
            conditions.append("status = ?")
            params.append(status)
        if severity:
            conditions.append("severity = ?")
            params.append(severity)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        with get_connection() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM ewo_ncr {where}", params).fetchone()[0]
            offset = (page - 1) * size
            rows = conn.execute(f"SELECT * FROM ewo_ncr {where} ORDER BY created_at DESC LIMIT ? OFFSET ?", params + [size, offset]).fetchall()
        return [dict(r) for r in rows], total

    @staticmethod
    def update_ewo(ewo_id: str, data: dict) -> dict | None:
        allowed = {"type", "title", "description", "severity", "status", "department", "assignee",
                    "raised_date", "target_date", "source", "source_file"}
        updates = {k: v for k, v in data.items() if k in allowed and v is not None}
        if not updates:
            return DBManager.get_ewo_by_id(ewo_id)
        updates["updated_at"] = datetime.now().isoformat()
        fields = ", ".join(f"{k} = ?" for k in updates)
        with get_connection() as conn:
            conn.execute(f"UPDATE ewo_ncr SET {fields} WHERE id = ?", list(updates.values()) + [ewo_id])
            conn.commit()
        return DBManager.get_ewo_by_id(ewo_id)

    @staticmethod
    def delete_ewo(ewo_id: str) -> bool:
        with get_connection() as conn:
            cursor = conn.execute("DELETE FROM ewo_ncr WHERE id = ?", (ewo_id,))
            conn.commit()
            return cursor.rowcount > 0

    @staticmethod
    def get_ewo_stats() -> dict:
        with get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM ewo_ncr").fetchone()[0]
            open_count = conn.execute("SELECT COUNT(*) FROM ewo_ncr WHERE status IN ('open','investigating')").fetchone()[0]
            critical = conn.execute("SELECT COUNT(*) FROM ewo_ncr WHERE severity = 'critical' AND status IN ('open','investigating')").fetchone()[0]
            by_type = conn.execute("SELECT type, COUNT(*) as cnt FROM ewo_ncr GROUP BY type").fetchall()
        return {"total": total, "open": open_count, "critical_risk": critical, "by_type": {r[0]: r[1] for r in by_type}}

    # ------------------------------------------------------------------
    # TIR
    # ------------------------------------------------------------------

    @staticmethod
    def generate_tir_id() -> str:
        now = datetime.now()
        suffix = uuid.uuid4().hex[:4]
        return f"TIR-{now.strftime('%Y')}-{now.strftime('%m%d')}-{suffix}"

    @staticmethod
    def create_tir(data: dict) -> dict:
        tir_id = DBManager.generate_tir_id()
        now = datetime.now().isoformat()
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO tir (id, title, description, category, status, department, assignee,
                    test_date, result, source, source_file, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (tir_id, data["title"], data.get("description"), data.get("category"),
                 data.get("status", "draft"), data.get("department"), data.get("assignee"),
                 data.get("test_date"), data.get("result"),
                 data.get("source", "manual"), data.get("source_file"), now, now),
            )
            conn.commit()
        return DBManager.get_tir_by_id(tir_id)

    @staticmethod
    def get_tir_by_id(tir_id: str) -> dict | None:
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM tir WHERE id = ?", (tir_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_tirs(page: int = 1, size: int = 20, status: str | None = None, category: str | None = None) -> tuple[list[dict], int]:
        conditions, params = [], []
        if status:
            conditions.append("status = ?")
            params.append(status)
        if category:
            conditions.append("category = ?")
            params.append(category)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        with get_connection() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM tir {where}", params).fetchone()[0]
            offset = (page - 1) * size
            rows = conn.execute(f"SELECT * FROM tir {where} ORDER BY created_at DESC LIMIT ? OFFSET ?", params + [size, offset]).fetchall()
        return [dict(r) for r in rows], total

    @staticmethod
    def update_tir(tir_id: str, data: dict) -> dict | None:
        allowed = {"title", "description", "category", "status", "department", "assignee",
                    "test_date", "result", "source", "source_file"}
        updates = {k: v for k, v in data.items() if k in allowed and v is not None}
        if not updates:
            return DBManager.get_tir_by_id(tir_id)
        updates["updated_at"] = datetime.now().isoformat()
        fields = ", ".join(f"{k} = ?" for k in updates)
        with get_connection() as conn:
            conn.execute(f"UPDATE tir SET {fields} WHERE id = ?", list(updates.values()) + [tir_id])
            conn.commit()
        return DBManager.get_tir_by_id(tir_id)

    @staticmethod
    def delete_tir(tir_id: str) -> bool:
        with get_connection() as conn:
            cursor = conn.execute("DELETE FROM tir WHERE id = ?", (tir_id,))
            conn.commit()
            return cursor.rowcount > 0

    @staticmethod
    def get_tir_stats() -> dict:
        with get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM tir").fetchone()[0]
            approved = conn.execute("SELECT COUNT(*) FROM tir WHERE status = 'approved'").fetchone()[0]
            pending = conn.execute("SELECT COUNT(*) FROM tir WHERE status IN ('draft','submitted')").fetchone()[0]
            by_cat = conn.execute("SELECT category, COUNT(*) as cnt FROM tir GROUP BY category").fetchall()
        return {"total": total, "approved": approved, "pending": pending, "by_category": {r[0]: r[1] for r in by_cat}}

    # ------------------------------------------------------------------
    # lookup_part_system
    # ------------------------------------------------------------------

    @staticmethod
    def search_part_system(query: str) -> list[dict]:
        """模糊搜索零件总成→子系统映射。转义 LIKE 通配符防止注入。"""
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT part_system, sub_system FROM lookup_part_system WHERE part_system LIKE ? ESCAPE '\\' ORDER BY part_system LIMIT 20",
                (f"%{escaped}%",),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def get_part_system(part_system: str) -> dict | None:
        """精确查询零件总成映射。"""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT part_system, sub_system FROM lookup_part_system WHERE part_system = ?",
                (part_system,),
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def create_part_system(data: dict) -> dict:
        now = datetime.now().isoformat()
        with get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO lookup_part_system (part_system, sub_system, created_at) VALUES (?, ?, ?)",
                (data["part_system"], data["sub_system"], now),
            )
            conn.commit()
        return {"part_system": data["part_system"], "sub_system": data["sub_system"]}

    # ------------------------------------------------------------------
    # lookup_engineer
    # ------------------------------------------------------------------

    @staticmethod
    def search_engineer(query: str) -> list[dict]:
        """模糊搜索工程师→科室映射。转义 LIKE 通配符防止注入。"""
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT name, department FROM lookup_engineer WHERE name LIKE ? ESCAPE '\\' ORDER BY name LIMIT 20",
                (f"%{escaped}%",),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def get_engineer(name: str) -> dict | None:
        """精确查询工程师映射。"""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT name, department FROM lookup_engineer WHERE name = ?",
                (name,),
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def create_engineer(data: dict) -> dict:
        now = datetime.now().isoformat()
        with get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO lookup_engineer (name, department, created_at) VALUES (?, ?, ?)",
                (data["name"], data["department"], now),
            )
            conn.commit()
        return {"name": data["name"], "department": data["department"]}

    # ------------------------------------------------------------------
    # app_settings
    # ------------------------------------------------------------------

    @staticmethod
    def get_all_settings() -> dict:
        """获取全部设置项，返回 {key: value} 字典。"""
        with get_connection() as conn:
            rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
        return {row[0]: row[1] for row in rows}

    @staticmethod
    def get_setting(key: str) -> str | None:
        with get_connection() as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    @staticmethod
    def set_setting(key: str, value: str) -> dict:
        now = datetime.now().isoformat()
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, value, now),
            )
            conn.commit()
        return {"key": key, "value": value, "updated_at": now}