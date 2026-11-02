# -*- coding: utf-8 -*-
"""执行槽持久化与租约边界（C4 调度契约的持久化部分，DSH-V2-19）。

职责边界（勿破）：
- 只做 SQLite 读写：增量建表、槽入队、租约领取、续租、收尾、绑定读写。
- 不做调度：不启动线程/定时器、不计算到点时刻（那是 ``services.schedule_policy``）、
  不接入托盘进程（接线是 DSH-V2-20）。本模块当前没有生产调度调用方。
- 时钟一律注入（``clock`` 返回 aware UTC datetime），不读取全局时钟，便于测试与回放。

冻结的存储契约（主控批准，逐条对应实现）：
1. ``{prefix}slots`` 唯一键 ``(project_id, job_id, business_date, scheduled_time)``；
   不设全局单例：projectId 是键的一部分。
2. ``{prefix}bindings`` 主键 ``(project_id, job_id)``，``mode`` 只能是 fixed / interval。
3. 只有 ``mode='fixed'`` 且未暂停的绑定对应的槽才会被 :meth:`SlotStore.lease_next` 领取；
   interval 绑定的槽永不被新调度领取（禁止旧新两套调度同时执行）。
4. 崩溃恢复：租约过期且 ``attempt < 2`` 时当天回到 pending 并记 ``retry_of``（当天一次）；
   ``attempt >= 2`` 直接 failed（``lease_expired``）；非当天的 pending/leased 槽一律
   expired，不补跑。
5. 收尾带 fencing：token 不匹配不改行；任何失败路径都不会写成 succeeded。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping

from core.time_rules import pure_date
from services import schedule_policy as SP

#: 槽状态闭集（与主控冻结契约一致）。
STATUS_PENDING = "pending"
STATUS_LEASED = "leased"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_PAUSED_SKIPPED = "paused_skipped"
STATUS_EXPIRED = "expired"

#: 全部槽状态。
STATUSES = (
    STATUS_PENDING,
    STATUS_LEASED,
    STATUS_SUCCEEDED,
    STATUS_FAILED,
    STATUS_PAUSED_SKIPPED,
    STATUS_EXPIRED,
)

#: 绑定类型闭集（与 ``services.schedule_policy`` 一致）。
BINDING_FIXED = SP.JOB_KIND_FIXED
BINDING_INTERVAL = SP.JOB_KIND_INTERVAL
BINDING_MODES = (BINDING_INTERVAL, BINDING_FIXED)

#: 同一槽最多尝试次数（含崩溃恢复重入队）：``attempt < 2`` 才允许再入队。
MAX_ATTEMPTS = 2
#: 失败重试的最短退避（C4：≥5 分钟）；小于此值视为调用方错误，直接拒绝。
MIN_RETRY_SECONDS = 300
#: 租约过期错误码（崩溃恢复耗尽后落库）。
ERROR_LEASE_EXPIRED = "lease_expired"

#: UTC 文本格式：固定宽度，字典序等于时间序，可直接在 SQL 里比较。
UTC_TEXT_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


# ── 工具 ──────────────────────────────────────────────────────────────────────


def utc_text(value: datetime) -> str:
    """aware datetime -> 固定宽度 UTC ISO 文本；拒绝无时区输入，不猜测时区。"""
    if not isinstance(value, datetime):
        raise TypeError(f"时间必须是 datetime，收到 {type(value).__name__}")
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("时间必须是带时区的 aware datetime（本模块不读取全局时钟）")
    return value.astimezone(timezone.utc).strftime(UTC_TEXT_FORMAT)


def _business_date_text(value: Any) -> str:
    """业务日期 -> ``YYYY-MM-DD`` 文本（北京日期语义，不做时区换算）。"""
    if isinstance(value, datetime):
        raise TypeError("business_date 必须是纯日期或 'YYYY-MM-DD' 字符串")
    return pure_date(value).isoformat()


def _require_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} 不能为空")
    return text


def _coerce_key(value: Any) -> SP.SlotKey:
    """把 SlotKey / Slot / 行映射 / 槽键文本 / 四元组规范化为 :class:`SlotKey`。"""
    if isinstance(value, SP.SlotKey):
        return value
    if isinstance(value, SP.Slot):
        return value.key
    if isinstance(value, Mapping):
        return SP.slot_key_from_mapping(value)
    if isinstance(value, str):
        parts = [part.strip() for part in value.strip().split("/")]
        if len(parts) != 4:
            raise ValueError("槽键文本必须是 projectId/jobId/YYYY-MM-DD/HH:MM")
        return SP.SlotKey(*parts)
    if isinstance(value, (tuple, list)) and len(value) == 4:
        return SP.SlotKey(*value)
    raise TypeError(f"不支持的槽键类型: {type(value).__name__}")


def _slot_entry(value: Any) -> tuple[SP.SlotKey, str]:
    """入队项 -> (规范化的槽键, 落库状态)；字符串键经 SlotKey 规范化。"""
    if isinstance(value, SP.Slot):
        status = STATUS_PAUSED_SKIPPED if value.status == SP.STATUS_PAUSED_SKIPPED else STATUS_PENDING
        return value.key, status
    if isinstance(value, SP.SlotKey):
        return value, STATUS_PENDING
    if isinstance(value, Mapping):
        key = SP.slot_key_from_mapping(value)
        raw = value.get("status", SP.STATUS_DUE)
        if raw == SP.STATUS_PAUSED_SKIPPED:
            return key, STATUS_PAUSED_SKIPPED
        if raw == SP.STATUS_DUE:
            return key, STATUS_PENDING
        raise ValueError(f"未知的槽状态: {raw!r}")
    return _coerce_key(value), STATUS_PENDING


def _error_code_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("error_code 必须是字符串或 None")
    text = value.strip()
    if not text:
        return None
    if len(text) > 100:
        raise ValueError("error_code 过长（最多 100 字符）")
    return text


def _retry_seconds(value: Any) -> int | None:
    """校验失败重试退避：None 或 ≥300 的整数秒；更短的值直接拒绝（不静默降级）。"""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("retry_after_seconds 必须是整数秒或 None")
    if value < MIN_RETRY_SECONDS:
        raise ValueError(f"retry_after_seconds 不能小于 {MIN_RETRY_SECONDS} 秒（C4 指数退避下限）")
    return value


def _lease_seconds(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("lease_seconds 必须是整数秒")
    if value <= 0:
        raise ValueError("lease_seconds 必须是正整数秒")
    return value


# ── 存储 ──────────────────────────────────────────────────────────────────────


class SlotStore:
    """执行槽与绑定的持久化 + 租约边界（无调度、无后台线程、无全局时钟）。"""

    def __init__(self, db: Any, prefix: str, *, clock: Callable[[], datetime]) -> None:
        if not callable(clock):
            raise TypeError("clock 必须可调用并返回 aware UTC datetime")
        self.db = db
        self.prefix = _require_text(prefix, "prefix")
        self.slots_table = f"{self.prefix}slots"
        self.bindings_table = f"{self.prefix}bindings"
        self._clock = clock

    # ── 迁移（只增不删） ──────────────────────────────────────────────────

    def migrations(self) -> list[tuple[int, Callable[[Any], None]]]:
        """返回给 ``host.migrate`` 的增量步骤：只建表/建索引，不改既有表。"""
        slots = self.slots_table
        bindings = self.bindings_table

        def v1(conn: Any) -> None:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {slots} ("
                "project_id TEXT NOT NULL, "
                "job_id TEXT NOT NULL, "
                "business_date TEXT NOT NULL, "
                "scheduled_time TEXT NOT NULL, "
                "status TEXT NOT NULL, "
                "attempt INTEGER NOT NULL DEFAULT 0, "
                "retry_of INTEGER, "
                "lease_owner TEXT, "
                "lease_token TEXT, "
                "lease_expires_at TEXT, "
                "next_attempt_at TEXT, "
                "last_error_code TEXT, "
                "created_at TEXT, "
                "updated_at TEXT, "
                "UNIQUE (project_id, job_id, business_date, scheduled_time))"
            )
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {bindings} ("
                "project_id TEXT NOT NULL, "
                "job_id TEXT NOT NULL, "
                "mode TEXT NOT NULL CHECK (mode IN ('interval', 'fixed')), "
                "times TEXT NOT NULL DEFAULT '[]', "
                "paused INTEGER NOT NULL DEFAULT 0, "
                "updated_at TEXT NOT NULL, "
                "PRIMARY KEY (project_id, job_id))"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS {slots}_due "
                f"ON {slots} (business_date, status, scheduled_time)"
            )

        return [(1, v1)]

    # ── 槽入队 ────────────────────────────────────────────────────────────

    def ensure_slots(self, slots: Iterable[Any]) -> int:
        """把到点槽写入表；重复键（含 ``'9:00'`` 与 ``'09:00'``）不重复入队。

        返回真正新增的行数。``paused_skipped`` 槽直接以该状态落库，不参与领取。
        """
        entries = [_slot_entry(item) for item in slots]
        if not entries:
            return 0
        now_text = utc_text(self._clock())
        inserted = 0
        with self.db.get_connection() as conn:
            for key, status in entries:
                cursor = conn.execute(
                    f"INSERT OR IGNORE INTO {self.slots_table} ("
                    "project_id, job_id, business_date, scheduled_time, status, "
                    "attempt, retry_of, lease_owner, lease_token, lease_expires_at, "
                    "next_attempt_at, last_error_code, created_at, updated_at"
                    ") VALUES (?, ?, ?, ?, ?, 0, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?)",
                    (
                        key.project_id,
                        key.job_id,
                        key.business_date.isoformat(),
                        key.scheduled_time.strftime("%H:%M"),
                        status,
                        now_text,
                        now_text,
                    ),
                )
                if cursor.rowcount and cursor.rowcount > 0:
                    inserted += 1
        return inserted

    # ── 租约 ──────────────────────────────────────────────────────────────

    def lease_next(self, owner: str, *, lease_seconds: int, business_date: Any) -> dict[str, Any] | None:
        """单事务原子领取当天最早的可执行槽；没有可领取的槽时返回 ``None``。

        同一事务里按顺序处理三件事：
        1. 非当天的 pending/leased 槽一律 expired（只补当天，不补跑前几天）；
        2. 当天租约过期的 leased 槽：``attempt < 2`` 回到 pending 并记 ``retry_of``
           （崩溃恢复，当天一次），``attempt >= 2`` 落 failed(``lease_expired``)；
        3. 领取 ``mode='fixed'`` 且未暂停绑定的最早 pending 槽（``next_attempt_at`` 已到）。

        没有绑定行的槽不会被领取：新调度只接管显式声明为 fixed 的绑定。
        """
        owner_text = _require_text(owner, "lease_owner")
        seconds = _lease_seconds(lease_seconds)
        day = _business_date_text(business_date)
        now = self._clock()
        now_text = utc_text(now)
        expires_text = utc_text(now + timedelta(seconds=seconds))

        with self.db.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # 1. 跨天：不补跑，直接 expired。
            conn.execute(
                f"UPDATE {self.slots_table} SET status = ?, lease_owner = NULL, lease_token = NULL, "
                "lease_expires_at = NULL, next_attempt_at = NULL, updated_at = ? "
                "WHERE business_date <> ? AND status IN (?, ?)",
                (STATUS_EXPIRED, now_text, day, STATUS_PENDING, STATUS_LEASED),
            )
            # 2a. 当天租约过期且还有重入队额度：回到 pending，retry_of 记原 attempt。
            conn.execute(
                f"UPDATE {self.slots_table} SET status = ?, retry_of = attempt, next_attempt_at = ?, "
                "lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL, updated_at = ? "
                "WHERE business_date = ? AND status = ? AND lease_expires_at IS NOT NULL "
                "AND lease_expires_at <= ? AND attempt < ?",
                (STATUS_PENDING, now_text, now_text, day, STATUS_LEASED, now_text, MAX_ATTEMPTS),
            )
            # 2b. 当天租约过期且额度已用尽：失败，不静默完成。
            conn.execute(
                f"UPDATE {self.slots_table} SET status = ?, last_error_code = ?, "
                "next_attempt_at = NULL, lease_owner = NULL, lease_token = NULL, "
                "lease_expires_at = NULL, updated_at = ? "
                "WHERE business_date = ? AND status = ? AND lease_expires_at IS NOT NULL "
                "AND lease_expires_at <= ? AND attempt >= ?",
                (STATUS_FAILED, ERROR_LEASE_EXPIRED, now_text, day, STATUS_LEASED, now_text, MAX_ATTEMPTS),
            )
            # 3. 领取：只认 fixed 且未暂停的绑定（interval 绑定永不被新调度领取）。
            row = conn.execute(
                f"SELECT s.project_id, s.job_id, s.business_date, s.scheduled_time, s.attempt "
                f"FROM {self.slots_table} AS s "
                f"JOIN {self.bindings_table} AS b "
                "ON b.project_id = s.project_id AND b.job_id = s.job_id "
                "WHERE s.business_date = ? AND s.status = ? "
                "AND (s.next_attempt_at IS NULL OR s.next_attempt_at <= ?) "
                "AND b.mode = ? AND b.paused = 0 "
                "ORDER BY s.scheduled_time ASC, s.project_id ASC, s.job_id ASC LIMIT 1",
                (day, STATUS_PENDING, now_text, BINDING_FIXED),
            ).fetchone()
            if row is None:
                return None
            token = uuid.uuid4().hex
            cursor = conn.execute(
                f"UPDATE {self.slots_table} SET status = ?, attempt = attempt + 1, lease_owner = ?, "
                "lease_token = ?, lease_expires_at = ?, updated_at = ? "
                "WHERE project_id = ? AND job_id = ? AND business_date = ? AND scheduled_time = ? "
                "AND status = ?",
                (
                    STATUS_LEASED,
                    owner_text,
                    token,
                    expires_text,
                    now_text,
                    row["project_id"],
                    row["job_id"],
                    row["business_date"],
                    row["scheduled_time"],
                    STATUS_PENDING,
                ),
            )
            if cursor.rowcount != 1:
                return None
            leased = conn.execute(
                f"SELECT * FROM {self.slots_table} WHERE project_id = ? AND job_id = ? "
                "AND business_date = ? AND scheduled_time = ?",
                (row["project_id"], row["job_id"], row["business_date"], row["scheduled_time"]),
            ).fetchone()
            return _row_view(leased)

    def renew(self, key: Any, token: str, lease_seconds: int) -> bool:
        """续租：token 与状态都对才延长租约，否则返回 ``False`` 且不改行。"""
        slot_key = _coerce_key(key)
        seconds = _lease_seconds(lease_seconds)
        token_text = _require_text(token, "lease_token")
        now = self._clock()
        now_text = utc_text(now)
        expires_text = utc_text(now + timedelta(seconds=seconds))
        with self.db.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                f"UPDATE {self.slots_table} SET lease_expires_at = ?, updated_at = ? "
                "WHERE project_id = ? AND job_id = ? AND business_date = ? AND scheduled_time = ? "
                "AND status = ? AND lease_token = ?",
                (
                    expires_text,
                    now_text,
                    slot_key.project_id,
                    slot_key.job_id,
                    slot_key.business_date.isoformat(),
                    slot_key.scheduled_time.strftime("%H:%M"),
                    STATUS_LEASED,
                    token_text,
                ),
            )
            return cursor.rowcount == 1

    def finish(
        self,
        key: Any,
        token: str,
        *,
        ok: bool,
        error_code: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> bool:
        """收尾一个已领取的槽；token 不匹配返回 ``False`` 且不改行（fencing）。

        - ``ok=True`` -> succeeded（清空错误码与租约）；
        - ``ok=False`` 且 ``attempt < 2`` 且给了 ``retry_after_seconds``（≥300）-> pending +
          ``next_attempt_at``；
        - 其余失败路径 -> failed（带 ``last_error_code``）。

        任何路径都不会把失败写成 succeeded。
        """
        slot_key = _coerce_key(key)
        token_text = _require_text(token, "lease_token")
        if not isinstance(ok, bool):
            raise TypeError("ok 必须是布尔值")
        code = _error_code_text(error_code)
        retry_seconds = _retry_seconds(retry_after_seconds)
        now = self._clock()
        now_text = utc_text(now)
        params_key = (
            slot_key.project_id,
            slot_key.job_id,
            slot_key.business_date.isoformat(),
            slot_key.scheduled_time.strftime("%H:%M"),
        )
        with self.db.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                f"SELECT status, attempt, lease_token FROM {self.slots_table} "
                "WHERE project_id = ? AND job_id = ? AND business_date = ? AND scheduled_time = ?",
                params_key,
            ).fetchone()
            if row is None:
                return False
            if row["status"] != STATUS_LEASED or row["lease_token"] != token_text:
                return False
            if ok:
                cursor = conn.execute(
                    f"UPDATE {self.slots_table} SET status = ?, last_error_code = NULL, "
                    "next_attempt_at = NULL, lease_owner = NULL, lease_token = NULL, "
                    "lease_expires_at = NULL, updated_at = ? "
                    "WHERE project_id = ? AND job_id = ? AND business_date = ? AND scheduled_time = ? "
                    "AND status = ? AND lease_token = ?",
                    (STATUS_SUCCEEDED, now_text, *params_key, STATUS_LEASED, token_text),
                )
                return cursor.rowcount == 1
            if row["attempt"] < MAX_ATTEMPTS and retry_seconds is not None:
                next_text = utc_text(now + timedelta(seconds=retry_seconds))
                cursor = conn.execute(
                    f"UPDATE {self.slots_table} SET status = ?, last_error_code = ?, "
                    "next_attempt_at = ?, lease_owner = NULL, lease_token = NULL, "
                    "lease_expires_at = NULL, updated_at = ? "
                    "WHERE project_id = ? AND job_id = ? AND business_date = ? AND scheduled_time = ? "
                    "AND status = ? AND lease_token = ?",
                    (STATUS_PENDING, code, next_text, now_text, *params_key, STATUS_LEASED, token_text),
                )
                return cursor.rowcount == 1
            cursor = conn.execute(
                f"UPDATE {self.slots_table} SET status = ?, last_error_code = ?, "
                "next_attempt_at = NULL, lease_owner = NULL, lease_token = NULL, "
                "lease_expires_at = NULL, updated_at = ? "
                "WHERE project_id = ? AND job_id = ? AND business_date = ? AND scheduled_time = ? "
                "AND status = ? AND lease_token = ?",
                (STATUS_FAILED, code, now_text, *params_key, STATUS_LEASED, token_text),
            )
            return cursor.rowcount == 1

    # ── 查询 ──────────────────────────────────────────────────────────────

    def list_slots(self, project_id: str, business_date: Any) -> list[dict[str, Any]]:
        """列出某项目某业务日期的全部槽（按时刻、任务排序）。"""
        project_text = _require_text(project_id, "project_id")
        day = _business_date_text(business_date)
        with self.db.get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM {self.slots_table} WHERE project_id = ? AND business_date = ? "
                "ORDER BY scheduled_time ASC, job_id ASC",
                (project_text, day),
            ).fetchall()
        return [_row_view(row) for row in rows]

    # ── 绑定 ──────────────────────────────────────────────────────────────

    def set_binding(
        self,
        project_id: str,
        job_id: str,
        mode: str,
        times: Iterable[Any] | None = None,
        paused: bool = False,
    ) -> dict[str, Any]:
        """写入/更新一个调度绑定（唯一键 project_id + job_id）。"""
        project_text = _require_text(project_id, "project_id")
        job_text = _require_text(job_id, "job_id")
        mode_text = str(mode or "").strip().lower()
        if mode_text not in BINDING_MODES:
            raise ValueError(f"未知绑定类型: {mode!r}，必须属于 {BINDING_MODES}")
        if not isinstance(paused, bool):
            raise TypeError("paused 必须是布尔值")
        raw_times = tuple(times or ())
        if mode_text == BINDING_FIXED:
            # 复用 schedule_policy 的规范化（去重、升序、'9:00' 与 '09:00' 同键）。
            normalized = SP.sync_binding(project_text, job_id=job_text, times=raw_times).times
        else:
            if raw_times:
                raise ValueError("interval 型绑定不得声明固定时刻；固定时刻与 interval 互斥")
            normalized = ()
        times_json = json.dumps([item.strftime("%H:%M") for item in normalized])
        now_text = utc_text(self._clock())
        with self.db.get_connection() as conn:
            conn.execute(
                f"INSERT INTO {self.bindings_table} "
                "(project_id, job_id, mode, times, paused, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(project_id, job_id) DO UPDATE SET mode = excluded.mode, "
                "times = excluded.times, paused = excluded.paused, updated_at = excluded.updated_at",
                (project_text, job_text, mode_text, times_json, 1 if paused else 0, now_text),
            )
        return {
            "projectId": project_text,
            "jobId": job_text,
            "mode": mode_text,
            "times": [item.strftime("%H:%M") for item in normalized],
            "paused": paused,
            "updatedAt": now_text,
        }

    def get_binding(self, project_id: str, job_id: str) -> dict[str, Any] | None:
        """读取一个绑定；不存在时返回 ``None``。"""
        project_text = _require_text(project_id, "project_id")
        job_text = _require_text(job_id, "job_id")
        with self.db.get_connection() as conn:
            row = conn.execute(
                f"SELECT * FROM {self.bindings_table} WHERE project_id = ? AND job_id = ?",
                (project_text, job_text),
            ).fetchone()
        if row is None:
            return None
        return {
            "projectId": row["project_id"],
            "jobId": row["job_id"],
            "mode": row["mode"],
            "times": list(json.loads(row["times"] or "[]")),
            "paused": bool(row["paused"]),
            "updatedAt": row["updated_at"],
        }


def _row_view(row: Any) -> dict[str, Any]:
    """持久化行 -> 契约字段名（camelCase）映射，供只读路由直接输出。"""
    return {
        "projectId": row["project_id"],
        "jobId": row["job_id"],
        "businessDate": row["business_date"],
        "scheduledTime": row["scheduled_time"],
        "status": row["status"],
        "attempt": int(row["attempt"]),
        "retryOf": row["retry_of"],
        "leaseOwner": row["lease_owner"],
        "leaseToken": row["lease_token"],
        "leaseExpiresAt": row["lease_expires_at"],
        "nextAttemptAt": row["next_attempt_at"],
        "lastErrorCode": row["last_error_code"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


__all__ = [
    "BINDING_FIXED",
    "BINDING_INTERVAL",
    "BINDING_MODES",
    "ERROR_LEASE_EXPIRED",
    "MAX_ATTEMPTS",
    "MIN_RETRY_SECONDS",
    "STATUSES",
    "STATUS_EXPIRED",
    "STATUS_FAILED",
    "STATUS_LEASED",
    "STATUS_PAUSED_SKIPPED",
    "STATUS_PENDING",
    "STATUS_SUCCEEDED",
    "SlotStore",
    "utc_text",
]
