# -*- coding: utf-8 -*-
"""手工导入专用的日变化基线（2026-11-16 起）：本地导入之间互相比较，不碰 TDC 共享快照。

- 自有两张表 ``{prefix}manual_baseline_meta`` / ``{prefix}manual_baseline_rows``，表名刻意
  不含 ``snapshot_meta`` / ``snapshot_rows``：一键生成的 TDC 快照与手工导入的基线互不可见，
  测试也靠这一点证明共享表没被写过。
- 读写接口与 ``service.SnapshotStore`` 相同（``S.compose`` 原样复用：基线挑选、旧数据判定、
  最长间隔、括号里的变化），同一数据日期后一次覆盖前一次（D1），保留 90 天。
- 长周期结论不读也不写：``conclusions`` 恒为空，任何结论/配置写入都抛错（与 ``NullStore`` 相同）。
- 元数据多记来源文件名与内容 sha256，页面据此说明「基线是哪一份手工导入」。
- 用户可以把某一天的导入「固定」为基线（``pinned``，同一时刻最多一个日期，覆盖该日所有项目）：
  固定的那天不受 90 天保留期清理；路由按「本次指定 > 固定 > 自动」决定基线日期。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import service as S


class ManualBaselineStore(S.SnapshotStore):
    """手工导入的基线库：``source_name`` / ``sha256`` 是本次导入的来源，写基线时一并记下。"""

    def __init__(self, db: Any, prefix: str, *, source_name: str = "", sha256: str = ""):
        # 不调父类 __init__：父类会登记共享表名（含长周期结论表），这里一张都不该碰。
        self.db = db
        self.prefix = prefix
        self.meta_table = f"{prefix}manual_baseline_meta"
        self.rows_table = f"{prefix}manual_baseline_rows"
        self.source_name = source_name
        self.sha256 = sha256

    def bind(self, *, source_name: str, sha256: str) -> "ManualBaselineStore":
        """同一套表、换一份来源：路由每次导入绑定一次。"""
        return ManualBaselineStore(self.db, self.prefix, source_name=source_name, sha256=sha256)

    def migration(self) -> tuple[int, Callable[[Any], None]]:
        def v5(conn) -> None:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self.meta_table} ("
                "data_date TEXT NOT NULL, project TEXT NOT NULL, scope_kind TEXT NOT NULL, "
                "serials_json TEXT NOT NULL, source_snapshot_at TEXT, row_count INTEGER NOT NULL, "
                "source_name TEXT NOT NULL DEFAULT '', sha256 TEXT NOT NULL DEFAULT '', "
                "pinned INTEGER NOT NULL DEFAULT 0, "
                "updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), "
                "PRIMARY KEY (data_date, project))"
            )
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self.rows_table} ("
                "data_date TEXT NOT NULL, project TEXT NOT NULL, seq INTEGER NOT NULL, row_json TEXT NOT NULL, "
                "PRIMARY KEY (data_date, project, seq))"
            )

        return (5, v5)

    def save_snapshot(self, day: date, project: str, rows: Sequence[Mapping[str, Any]], *,
                      scope_kind: str, serials: Sequence[str], source_snapshot_at: str | None) -> None:
        """D1：同一数据日期重复导入时后一次覆盖前一次；保留 90 天（与 TDC 快照同口径）。"""
        cutoff = (day - timedelta(days=S.SNAPSHOT_RETENTION_DAYS)).isoformat()
        with self.db.get_connection() as conn:
            conn.execute(f"DELETE FROM {self.rows_table} WHERE data_date = ? AND project = ?", (day.isoformat(), project))
            conn.executemany(
                f"INSERT INTO {self.rows_table} (data_date, project, seq, row_json) VALUES (?, ?, ?, ?)",
                [(day.isoformat(), project, seq, json.dumps(row, ensure_ascii=False)) for seq, row in enumerate(rows)],
            )
            conn.execute(
                f"INSERT INTO {self.meta_table} (data_date, project, scope_kind, serials_json, source_snapshot_at, "
                "row_count, source_name, sha256, pinned) VALUES (?, ?, ?, ?, ?, ?, ?, ?, "
                # 固定是「整个日期」的属性：这天已固定时，新项目的行也跟着固定。
                f"(SELECT COUNT(*) > 0 FROM {self.meta_table} WHERE data_date = ? AND pinned = 1)) "
                "ON CONFLICT(data_date, project) DO UPDATE SET "
                "scope_kind = excluded.scope_kind, serials_json = excluded.serials_json, "
                "source_snapshot_at = excluded.source_snapshot_at, row_count = excluded.row_count, "
                "source_name = excluded.source_name, sha256 = excluded.sha256, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                (day.isoformat(), project, scope_kind, json.dumps(sorted(serials), ensure_ascii=False),
                 source_snapshot_at, len(rows), self.source_name, self.sha256, day.isoformat()),
            )
            # 保留期清理：固定为基线的那天不删。
            conn.execute(
                f"DELETE FROM {self.rows_table} WHERE data_date < ? AND data_date NOT IN "
                f"(SELECT data_date FROM {self.meta_table} WHERE pinned = 1)", (cutoff,),
            )
            conn.execute(f"DELETE FROM {self.meta_table} WHERE data_date < ? AND pinned = 0", (cutoff,))

    # 基线管理（页面「对比基线」）

    def list_baselines(self) -> list[dict[str, Any]]:
        """按日期汇总：[{date, sourceName, sha256(12), rowCount, projects, pinned}]，新的在前。"""
        with self.db.get_connection() as conn:
            rows = conn.execute(
                f"SELECT data_date, project, row_count, source_name, sha256, pinned FROM {self.meta_table} "
                "ORDER BY data_date DESC, updated_at DESC, project"
            ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = result.setdefault(row["data_date"], {
                "date": row["data_date"], "sourceName": row["source_name"], "sha256": str(row["sha256"])[:12],
                "rowCount": 0, "projects": [], "pinned": False,
            })
            item["rowCount"] += int(row["row_count"])
            item["projects"].append(row["project"])
            item["pinned"] = item["pinned"] or bool(row["pinned"])
        for item in result.values():
            item["projects"].sort()
        return list(result.values())

    def pinned_date(self) -> date | None:
        with self.db.get_connection() as conn:
            row = conn.execute(
                f"SELECT data_date FROM {self.meta_table} WHERE pinned = 1 ORDER BY data_date DESC LIMIT 1"
            ).fetchone()
        return date.fromisoformat(row["data_date"]) if row else None

    def has_date(self, day: date) -> bool:
        with self.db.get_connection() as conn:
            return conn.execute(
                f"SELECT 1 FROM {self.meta_table} WHERE data_date = ? LIMIT 1", (day.isoformat(),)
            ).fetchone() is not None

    def pin(self, day: date) -> None:
        """把这一天固定为基线（同时取消其它日期的固定）；这天没有存过就抛 LookupError。"""
        with self.db.get_connection() as conn:
            if conn.execute(f"SELECT 1 FROM {self.meta_table} WHERE data_date = ? LIMIT 1",
                            (day.isoformat(),)).fetchone() is None:
                raise LookupError(day.isoformat())
            conn.execute(f"UPDATE {self.meta_table} SET pinned = CASE WHEN data_date = ? THEN 1 ELSE 0 END",
                         (day.isoformat(),))

    def unpin(self) -> int:
        with self.db.get_connection() as conn:
            return conn.execute(f"UPDATE {self.meta_table} SET pinned = 0 WHERE pinned = 1").rowcount

    def delete(self, day: date) -> int:
        """删掉这一天的基线（含固定状态）；返回删掉的项目数，0 表示没有这天。"""
        with self.db.get_connection() as conn:
            conn.execute(f"DELETE FROM {self.rows_table} WHERE data_date = ?", (day.isoformat(),))
            return conn.execute(f"DELETE FROM {self.meta_table} WHERE data_date = ?", (day.isoformat(),)).rowcount

    def source_of(self, projects: Iterable[str], day: date) -> dict[str, str] | None:
        """某个基线日期是哪份手工导入（取所选项目里第一条有记录的）。"""
        projects = list(projects)
        if not projects:
            return None
        marks = ",".join("?" for _ in projects)
        with self.db.get_connection() as conn:
            row = conn.execute(
                f"SELECT source_name, sha256 FROM {self.meta_table} WHERE data_date = ? AND project IN ({marks}) "
                "ORDER BY project LIMIT 1",
                (day.isoformat(), *projects),
            ).fetchone()
        if row is None:
            return None
        return {"sourceName": row["source_name"], "sha256": row["sha256"]}

    # 长周期结论：手工导入不读也不写（与 NullStore 相同）

    @staticmethod
    def _refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("手工导入不允许写长周期结论或配置")

    save_conclusions = _refuse
    clear_conclusions = _refuse
    save_config = _refuse

    def conclusions(self, projects: Iterable[str]) -> dict[str, dict[str, bool]]:
        return {str(project): {} for project in projects}

    def list_conclusions(self, project: str) -> list[dict[str, Any]]:
        return []

    def projects_with_conclusions(self) -> list[str]:
        return []
