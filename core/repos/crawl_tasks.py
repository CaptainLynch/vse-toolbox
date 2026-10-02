# -*- coding: utf-8 -*-
"""crawl_tasks 任务持久化与调度支持的数据访问（DatabaseManager 的领域分片）。

由 core/db_manager.py 按领域拆出；``DatabaseManager`` 继承本类，对外接口不变。
本类依赖 ``get_connection`` 等由 DatabaseManager 提供的方法，不单独实例化。
"""

from core.db_common import (  # noqa: F401
    Any,
)


class CrawlTaskRepo:
    def create_crawl_task(
        self,
        task_id: str,
        task_type: str,
        source: str,
        params_json: str = "{}",
        progress_json: str = "{}",
    ) -> dict[str, Any]:
        """
        创建新的爬虫/异步任务记录。
        """
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO crawl_tasks (
                    task_id, task_type, source, status, params_json, progress_json
                ) VALUES (?, ?, ?, 'queued', ?, ?)
                """,
                (task_id, task_type, source, params_json, progress_json),
            )
            row = conn.execute(
                "SELECT * FROM crawl_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            return dict(row) if row else {}

    def get_crawl_task(self, task_id: str) -> dict[str, Any] | None:
        """根据 task_id 获取单个 crawl 任务。"""
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM crawl_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_crawl_tasks(
        self,
        status: str | None = None,
        source: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """列出 crawl 任务，按创建时间逆序排列。"""
        clauses = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if source:
            clauses.append("source = ?")
            params.append(source)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM crawl_tasks {where} ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        with self.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def update_crawl_task_progress(
        self,
        task_id: str,
        progress_json: str,
    ) -> bool:
        """更新任务进度。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE crawl_tasks
                SET progress_json = ?,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE task_id = ?
                """,
                (progress_json, task_id),
            )
            return cursor.rowcount > 0

    def update_crawl_task_status(
        self,
        task_id: str,
        status: str,
        *,
        error_message: str | None = None,
        artifact_path: str | None = None,
        progress_json: str | None = None,
    ) -> bool:
        """更新任务状态及错误信息或产物路径。"""
        updates = ["status = ?", "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"]
        params: list[Any] = [status]
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)
        if artifact_path is not None:
            updates.append("artifact_path = ?")
            params.append(artifact_path)
        if progress_json is not None:
            updates.append("progress_json = ?")
            params.append(progress_json)
        params.append(task_id)
        with self.get_connection() as conn:
            cursor = conn.execute(
                f"UPDATE crawl_tasks SET {', '.join(updates)} WHERE task_id = ?",
                params,
            )
            return cursor.rowcount > 0

    def cancel_crawl_task(self, task_id: str) -> bool:
        """取消 queued, leased 或 running 状态的任务。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE crawl_tasks
                SET status = 'cancelled',
                    error_message = coalesce(error_message, 'Cancelled by user'),
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE task_id = ? AND status IN ('queued', 'leased', 'running')
                """,
                (task_id,),
            )
            return cursor.rowcount > 0

    def sweep_interrupted_crawl_tasks(self) -> int:
        """启动自检：将所有处于未完成孤儿状态的任务置为 interrupted。"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE crawl_tasks
                SET status = 'interrupted',
                    error_message = 'Interrupted by application restart',
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE status IN ('queued', 'leased', 'running')
                """
            )
            return cursor.rowcount

    def count_active_crawl_tasks(self) -> int:
        """获取当前活跃（排队/执行中）的 crawl 任务数量。"""
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM crawl_tasks WHERE status IN ('queued', 'leased', 'running')"
            ).fetchone()
            return int(row[0]) if row else 0
