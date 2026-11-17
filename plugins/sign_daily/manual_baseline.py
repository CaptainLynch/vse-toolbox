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
  固定的那天不受 90 天保留期清理；路由按「本次指定 > 基线文件 / 固定 > 自动」决定基线日期。
- 基线文件（2026-11-16 起，``BaselineFileStore``，迁移版本 6）：用户把一份本地报表指定为固定的对比基线。
  文件按原字节复制进插件数据目录的 ``baseline-backup/``（服务端生成的安全文件名，原子写入，只留一份），
  对比永远读备份；原路径（已知时）只做监控（不存在 / 被修改过）。基线文件与「固定」互斥。
  生成时用 ``FileBaselineAdapter`` 把备份的内容以「那一天的全量快照」交给 ``S.compose``，compose 本身不改。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from services import data_model_watchlist as W

from . import importer as IMP
from . import rules as V
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


# ── 基线文件（2026-11-16）：指定一份本地报表为固定基线，对比只读备份 ─────────────

#: 备份目录名（插件数据目录下）。
BACKUP_SUBDIR = "baseline-backup"
#: 备份文件名只能是服务端生成的这一种形状：不含任何分隔符，也不含用户给的名字。
_BACKUP_NAME = re.compile(r"baseline-[0-9a-f]{12}\.(?:xlsx|txt)")

#: 原文件状态：ok 未变 / missing 不在了或读不了 / changed 指定后被改过 / unknown 原位置未知（选择文件指定）。
ORIGINAL_OK, ORIGINAL_MISSING, ORIGINAL_CHANGED, ORIGINAL_UNKNOWN = "ok", "missing", "changed", "unknown"
#: 备份状态：ok 在且内容与指定时一致 / missing 不在、读不了或内容对不上。
BACKUP_OK, BACKUP_MISSING = "ok", "missing"


def valid_backup_name(name: Any) -> bool:
    """备份文件名白名单：``baseline-<12 位小写十六进制>.xlsx|.txt``，其它一律不认（含 ../、分隔符）。"""
    return isinstance(name, str) and _BACKUP_NAME.fullmatch(name) is not None


def backup_name_for(sha256: str, suffix: str) -> str:
    name = f"baseline-{str(sha256)[:12].lower()}{str(suffix).lower()}"
    if not valid_backup_name(name):
        raise ValueError("无效的备份文件名")
    return name


def backup_path(directory: Path, name: Any) -> Path | None:
    """记录里的备份名 → 备份目录下的直接子项；名字不合白名单或跳出目录就返回 None。"""
    if not valid_backup_name(name):
        return None
    base = Path(directory).resolve()
    target = base / str(name)
    if target.parent != base:
        return None
    return target


def write_backup(directory: Path, name: str, data: bytes) -> Path:
    """原子写入备份：同目录临时文件写完、刷盘，再 ``os.replace`` 到位。"""
    target = backup_path(directory, name)
    if target is None:
        raise ValueError("无效的备份文件名")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.parent / f".{target.name}.{os.getpid()}.tmp"
    try:
        with temp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    finally:
        if temp.exists():
            temp.unlink()
    return target


def remove_backup(directory: Path, name: Any) -> bool:
    """只删记录里的那份备份（白名单名字、备份目录的直接子项、普通文件）；不按用户输入删任何东西。"""
    target = backup_path(directory, name)
    if target is None:
        return False
    try:
        info = target.lstat()
    except OSError:
        return False
    if not stat.S_ISREG(info.st_mode):
        return False
    try:
        target.unlink()
    except OSError:
        return False
    return True


def _read_regular(path: Path, limit: int) -> bytes:
    """打开一次、校验句柄是普通文件、最多读 limit+1 字节（检查与使用是同一份字节）。"""
    with Path(path).open("rb") as handle:
        info = os.fstat(handle.fileno())
        # 只按句柄类型判断：Windows 上 OneDrive「按需文件」等云同步占位符也带重解析点属性，
        # 按属性拒绝会把「桌面/文档」里的正常报表挡掉；符号链接在打开时已经解析到目标。
        if not stat.S_ISREG(info.st_mode):
            raise IMP.ManualImportError("E_FILE_NOT_REGULAR", "只接受普通文件（不接受文件夹或设备）")
        return handle.read(limit + 1)


def read_backup(directory: Path, name: Any, limit: int) -> bytes | None:
    """读记录里的那份备份；不在、读不了、超限都返回 None。"""
    target = backup_path(directory, name)
    if target is None:
        return None
    try:
        data = _read_regular(target, limit)
    except (OSError, IMP.ManualImportError):
        return None
    return None if len(data) > limit else data


def clean_path_text(raw: Any) -> str:
    """粘贴的路径：去掉首尾空白和成对引号（Windows「复制文件地址」会带双引号）。"""
    text = str(raw or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text


def read_designated(raw: Any, limit: int) -> tuple[Path, bytes]:
    """按用户粘贴的完整路径读一份基线文件（用户决定：不限于扫描目录）。

    只接受绝对路径；解析后必须是普通文件、扩展名 .xlsx / .txt；从同一个句柄最多读 limit+1 字节，
    之后的哈希、解析、备份都只用这份字节（检查与复制之间没有时间窗）。错误文案只带用户自己输入的路径。
    """
    text = clean_path_text(raw)
    if not text:
        raise IMP.ManualImportError("E_PATH_REQUIRED", "请粘贴基线文件的完整路径")
    candidate = Path(text)
    if not candidate.is_absolute():
        raise IMP.ManualImportError(
            "E_PATH_NOT_ABSOLUTE", f"「{text}」不是完整路径：请粘贴从盘符开始的完整路径，例如 D:\\报表\\11-01.xlsx"
        )
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise IMP.ManualImportError(
            "E_FILE_GONE", f"找不到文件「{text}」：请确认路径完整、文件还在原位置"
        ) from None
    if resolved.is_dir():
        raise IMP.ManualImportError("E_FILE_NOT_REGULAR", f"「{text}」是文件夹，请粘贴文件本身的路径")
    if not resolved.is_file():
        raise IMP.ManualImportError("E_FILE_NOT_REGULAR", f"「{text}」不是普通文件，请粘贴报表文件本身的路径")
    if resolved.suffix.lower() not in IMP.SUFFIXES:
        raise IMP.ManualImportError(
            "E_BAD_SUFFIX", "基线文件只接受 .xlsx（TDC 官方导出）或 .txt（Excel 另存为 Unicode 文本）"
        )
    try:
        data = _read_regular(resolved, limit)
    except OSError:
        raise IMP.ManualImportError(
            "E_FILE_UNREADABLE", f"读不了文件「{text}」：可能正被其它程序独占打开，关闭后再试"
        ) from None
    if len(data) > limit:
        raise IMP.ManualImportError("E_FILE_TOO_LARGE", f"文件超过 {limit // (1024 * 1024)} MB 上限")
    if not data:
        raise IMP.ManualImportError("E_EMPTY_WORKBOOK", "文件是空的")
    return resolved, data


def probe_original(path: str | None, sha256: str, size: int, limit: int) -> str:
    """原文件状态：位置未知 / 不在或读不了 / 指定后被改过（大小或内容摘要不同）/ 未变。"""
    if not path:
        return ORIGINAL_UNKNOWN
    try:
        data = _read_regular(Path(path), limit)
    except (OSError, IMP.ManualImportError):
        return ORIGINAL_MISSING
    if len(data) != int(size) or hashlib.sha256(data).hexdigest() != sha256:
        return ORIGINAL_CHANGED
    return ORIGINAL_OK


class BaselineFileStore:
    """单行表 ``{prefix}manual_baseline_file``：当前指定的基线文件（最多一条）。"""

    def __init__(self, db: Any, prefix: str):
        self.db = db
        self.table = f"{prefix}manual_baseline_file"

    def migration(self) -> tuple[int, Callable[[Any], None]]:
        def v6(conn) -> None:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self.table} ("
                "id INTEGER PRIMARY KEY CHECK (id = 1), original_path TEXT, original_name TEXT NOT NULL, "
                "data_date TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL, backup_name TEXT NOT NULL, "
                "set_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))"
            )

        return (6, v6)

    def get(self) -> dict[str, Any] | None:
        with self.db.get_connection() as conn:
            row = conn.execute(
                f"SELECT original_path, original_name, data_date, sha256, size, backup_name, set_at "
                f"FROM {self.table} WHERE id = 1"
            ).fetchone()
        return dict(row) if row is not None else None

    def set(self, *, original_path: str | None, original_name: str, data_date: date, sha256: str,
            size: int, backup_name: str) -> None:
        if not valid_backup_name(backup_name):
            raise ValueError("无效的备份文件名")
        with self.db.get_connection() as conn:
            conn.execute(
                f"INSERT INTO {self.table} (id, original_path, original_name, data_date, sha256, size, backup_name) "
                "VALUES (1, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "original_path = excluded.original_path, original_name = excluded.original_name, "
                "data_date = excluded.data_date, sha256 = excluded.sha256, size = excluded.size, "
                "backup_name = excluded.backup_name, set_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                (original_path, original_name, data_date.isoformat(), sha256, int(size), backup_name),
            )

    def clear(self) -> dict[str, Any] | None:
        """删掉记录，返回删掉的那条（调用方据此删备份）；本来就没有时返回 None。"""
        previous = self.get()
        if previous is not None:
            with self.db.get_connection() as conn:
                conn.execute(f"DELETE FROM {self.table} WHERE id = 1")
        return previous


class FileBaselineAdapter:
    """把基线文件（备份）的内容伪装成「那一天的全量快照」交给 ``S.compose``，其余全部委托给手工基线库。

    - ``snapshot_dates``：在库里已有日期之外，补上基线文件的日期（只对文件里有的项目，且只在早于本次数据日期时）；
    - ``snapshot_scope`` / ``snapshot_rows``：基线文件那一天只认文件内容（库里同一天的导入不参与），
      文件里没有的项目返回 None / 空，compose 据此判定「指定的基线不可用」；
    - ``records`` 为空（备份不在或认不出）时，那一天对任何项目都不覆盖 → 不显示日变化，也不退回自动挑选；
    - ``save_snapshot`` 等照常委托：留作基线的开关照旧生效。
    """

    def __init__(self, inner: Any, day: date, records: Sequence[Mapping[str, Any]] | None, data_date: date):
        self._inner = inner
        self._day = day
        self._active = day < data_date
        self._by_project: dict[str, list[dict[str, Any]]] = {}
        for record in records or ():
            project = V.cell_text(record.get("项目/车型"))
            if project:
                self._by_project.setdefault(project, []).append(dict(record))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def snapshot_dates(self, project: str) -> list[date]:
        dates = set(self._inner.snapshot_dates(project))
        if self._active and project in self._by_project:
            dates.add(self._day)
        return sorted(dates, reverse=True)

    def snapshot_scope(self, project: str, day: date) -> dict[str, Any] | None:
        if not (self._active and day == self._day):
            return self._inner.snapshot_scope(project, day)
        rows = self._by_project.get(project)
        if not rows:
            return None
        serials = {V.cell_text(r.get("流水单号")) for r in rows if V.cell_text(r.get("流水单号"))}
        return {"kind": W.SCOPE_ALL, "serials": sorted(serials)}

    def snapshot_rows(self, projects: Iterable[str], day: date) -> list[dict[str, Any]]:
        if not (self._active and day == self._day):
            return self._inner.snapshot_rows(projects, day)
        return [dict(row) for project in sorted(set(projects)) for row in self._by_project.get(project, [])]
