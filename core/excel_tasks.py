# -*- coding: utf-8 -*-
"""
core/excel_tasks.py — Excel 离线任务核心：路径安全、状态机、租约管理与幂等控制
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import sqlite3
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from core.db_manager import DatabaseManager
from core.redaction import redact_sensitive_text

logger = logging.getLogger("vse_toolbox.excel_tasks")

# ── 允许的操作与状态 ──────────────────────────────────────────
ALLOWED_OPERATIONS = frozenset({"merge_append", "merge_overlay", "diff_against_baseline"})
ALLOWED_TASK_STATUSES = frozenset({"queued", "leased", "running", "succeeded", "failed", "cancelled"})
ALLOWED_RUN_STATES = frozenset({"leased", "running", "succeeded", "failed", "expired", "cancelled"})
ALLOWED_ROLES = frozenset({"source", "target", "baseline", "output"})
ALLOWED_EXTENSIONS = frozenset({".xlsx", ".xls"})

_DEVICE_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})
_BAD_COMPONENT_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

LEASE_MIN_SECONDS = 60
LEASE_MAX_SECONDS = 86400
DEFAULT_LEASE_SECONDS = 900


# ── 异常体系 ──────────────────────────────────────────────────
class ExcelTaskError(Exception):
    """Excel 任务系统通用异常基类。"""


class ExcelPathSafetyError(ExcelTaskError, ValueError):
    """路径安全违规：越界、目录穿越、非法字符、重解析点或非法扩展名。"""


class ExcelIdempotencyConflictError(ExcelTaskError, ValueError):
    """幂等键冲突：相同幂等键尝试提交不同指纹的请求。"""


class ExcelInvalidStateError(ExcelTaskError, RuntimeError):
    """非法的任务状态转换。"""


class ExcelLeaseLostError(ExcelTaskError, RuntimeError):
    """租约丢失、过期、token 不匹配或 run 不匹配。"""


# ── 文件引用结构 ──────────────────────────────────────────────
@dataclass(frozen=True)
class ExcelTaskFileRef:
    """受控文件引用（不可变且自动规范化）。"""

    role: str
    root_id: str
    relative_path: str
    ordinal: int = 0

    def __post_init__(self) -> None:
        if self.role not in ALLOWED_ROLES:
            raise ExcelPathSafetyError(f"unknown file role: {self.role!r}")
        if not isinstance(self.ordinal, int) or isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise ValueError(f"ordinal must be a non-negative integer, got {self.ordinal!r}")
        clean_root = ApprovedExcelRoots.canonicalize_root_id(self.root_id)
        clean_path = ApprovedExcelRoots.normalize_relative_path(self.relative_path)
        object.__setattr__(self, "root_id", clean_root)
        object.__setattr__(self, "relative_path", clean_path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "root_id": self.root_id,
            "relative_path": self.relative_path,
            "ordinal": self.ordinal,
        }


# ── ApprovedExcelRoots ─────────────────────────────────────────
class ApprovedExcelRoots:
    """
    业务受控根目录安全管理器。

    职责:
        1. 维护已批准的业务根目录白名单映射
        2. 拒绝包含符号链接/重解析点（Junction/Symlink）的目录
        3. 规范化并严格校验相对路径
        4. 解析并验证文件在根目录内的受控封闭性
        5. 检查输入/输出文件存在性约束，自身绝不创建目录或写入文件
    """

    def __init__(self, roots: Mapping[str, Path | str]) -> None:
        if not roots or not isinstance(roots, Mapping):
            raise ExcelPathSafetyError("at least one approved root is required")
        self._roots: dict[str, Path] = {}
        for root_id, path_val in roots.items():
            safe_id = self.canonicalize_root_id(root_id)
            if safe_id in self._roots:
                raise ExcelPathSafetyError(f"duplicate or colliding canonical root_id: {safe_id!r}")
            p = Path(path_val).expanduser().absolute()
            if not p.exists() or not p.is_dir():
                raise ExcelPathSafetyError(
                    f"approved root directory does not exist or is not a directory: {p}"
                )
            self._assert_no_reparse_in_hierarchy(p)
            self._roots[safe_id] = p.resolve(strict=True)

    @property
    def root_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._roots))

    def get_root(self, root_id: str) -> Path:
        canonical_id = self.canonicalize_root_id(root_id)
        try:
            return self._roots[canonical_id]
        except KeyError:
            raise ExcelPathSafetyError(f"unknown approved root_id: {root_id!r}")

    @staticmethod
    def canonicalize_root_id(root_id: object) -> str:
        if not isinstance(root_id, str):
            raise ExcelPathSafetyError("root_id must be a string")
        text = unicodedata.normalize("NFKC", root_id).strip()
        if not text or text in {".", ".."} or _BAD_COMPONENT_RE.search(text):
            raise ExcelPathSafetyError(f"invalid root_id: {root_id!r}")
        if text.rstrip(". ") != text or text.lstrip(" ") != text:
            raise ExcelPathSafetyError(f"root_id has leading/trailing dot or space: {root_id!r}")
        if text.split(".", 1)[0].upper() in _DEVICE_NAMES:
            raise ExcelPathSafetyError(f"root_id cannot be a Windows device name: {root_id!r}")
        if len(text) > 128:
            raise ExcelPathSafetyError(f"root_id exceeds maximum length (128): {root_id!r}")
        return text

    _validate_root_id = canonicalize_root_id

    @staticmethod
    def _is_reparse(path: Path) -> bool:
        try:
            info = path.lstat()
        except (FileNotFoundError, OSError):
            return False
        attrs = int(getattr(info, "st_file_attributes", 0))
        reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        return path.is_symlink() or bool(attrs & reparse_flag)

    @classmethod
    def _assert_no_reparse_in_hierarchy(cls, path: Path) -> None:
        current = path.absolute()
        while True:
            if current.exists() and cls._is_reparse(current):
                raise ExcelPathSafetyError(
                    f"links/reparse points are not allowed in approved roots: {current}"
                )
            if current.parent == current:
                break
            current = current.parent

    @classmethod
    def normalize_relative_path(cls, value: object) -> str:
        """
        规范化并严格校验相对路径。

        拒绝绝对路径、UNC 路径、驱动器号、反斜杠、冒号、目录穿越、设备名等。
        """
        if not isinstance(value, str):
            raise ExcelPathSafetyError("relative_path must be a string")
        text = unicodedata.normalize("NFKC", value)
        if not text:
            raise ExcelPathSafetyError("relative_path cannot be empty")
        if text != text.strip():
            raise ExcelPathSafetyError("relative_path cannot have leading or trailing whitespace")
        if "\\" in text:
            raise ExcelPathSafetyError("relative_path cannot contain backslashes")
        if ":" in text:
            raise ExcelPathSafetyError("relative_path cannot contain colons or drive letters")
        if text.startswith("/"):
            raise ExcelPathSafetyError("relative_path cannot be an absolute path")

        segments = text.split("/")
        for seg in segments:
            if not seg:
                raise ExcelPathSafetyError("relative_path contains empty segment")
            if seg in {".", ".."}:
                raise ExcelPathSafetyError("relative_path contains traversal segment")
            if _BAD_COMPONENT_RE.search(seg):
                raise ExcelPathSafetyError(f"relative_path contains invalid character in segment: {seg!r}")
            if seg.rstrip(". ") != seg or seg.lstrip(" ") != seg:
                raise ExcelPathSafetyError(f"segment cannot have leading/trailing dot or space: {seg!r}")
            stem = seg.split(".", 1)[0].upper()
            if stem in _DEVICE_NAMES:
                raise ExcelPathSafetyError(f"relative_path contains Windows reserved device name: {seg!r}")

        canonical_path = "/".join(segments)
        if len(canonical_path) > 1024:
            raise ExcelPathSafetyError("relative_path exceeds maximum length (1024)")

        ext = Path(canonical_path).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ExcelPathSafetyError(f"extension {ext!r} not allowed; only .xlsx and .xls are supported")

        return canonical_path

    def resolve_ref(self, file_ref: ExcelTaskFileRef, *, check_role: bool = True) -> Path:
        """
        安全解析文件引用为绝对 Path，并进行封闭性与存在性校验。

        注意: 本方法绝不执行任何写操作 (不创建目录，不写文件)。
        """
        root_dir = self.get_root(file_ref.root_id)
        rel_path = self.normalize_relative_path(file_ref.relative_path)
        target = root_dir / Path(rel_path)

        # 检查各层级 reparse point
        current = target.parent.absolute()
        while True:
            if current.exists() and self._is_reparse(current):
                raise ExcelPathSafetyError(f"reparse point detected in parent path: {current}")
            if current == root_dir or current.parent == current:
                break
            current = current.parent

        if target.exists() and self._is_reparse(target):
            raise ExcelPathSafetyError(f"reparse point detected in target file: {target}")

        # 验证封闭性
        try:
            resolved_target = target.resolve()
            resolved_root = root_dir.resolve()
            if not resolved_target.is_relative_to(resolved_root) or resolved_target == resolved_root:
                raise ExcelPathSafetyError(f"path escapes approved root containment: {file_ref.relative_path}")
        except (ValueError, RuntimeError) as exc:
            raise ExcelPathSafetyError(f"containment check failed: {exc}") from exc

        if check_role:
            if file_ref.role in {"source", "target", "baseline"}:
                if not target.exists() or not target.is_file():
                    raise ExcelPathSafetyError(
                        f"input file for role {file_ref.role!r} does not exist or is not a regular file: {rel_path}"
                    )
            elif file_ref.role == "output":
                if target.exists() and not target.is_file():
                    raise ExcelPathSafetyError(f"output path exists but is not a regular file: {rel_path}")
                parent = target.parent
                if not parent.exists() or not parent.is_dir():
                    raise ExcelPathSafetyError(f"output parent directory does not exist: {parent}")
                if self._is_reparse(parent):
                    raise ExcelPathSafetyError(f"output parent directory cannot be a reparse point: {parent}")

        return target


# ── 请求校验与指纹 ──────────────────────────────────────────
def validate_task_request(
    operation: str,
    file_refs: Sequence[ExcelTaskFileRef],
    options: Mapping[str, Any] | None = None,
    max_attempts: int = 1,
) -> None:
    """校验任务请求参数契约。"""
    if operation not in ALLOWED_OPERATIONS:
        raise ValueError(f"unsupported operation: {operation!r}")

    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not (1 <= max_attempts <= 5):
        raise ValueError(f"max_attempts must be an integer between 1 and 5, got {max_attempts!r}")

    if options is not None:
        if not isinstance(options, Mapping):
            raise TypeError("options must be a mapping")
        if dict(options):
            raise ValueError("options must currently be an empty mapping in phase A")

    if not file_refs:
        raise ValueError("file_refs cannot be empty")

    roles_count: dict[str, int] = {}
    seen_ordinals: set[tuple[str, int]] = set()

    for ref in file_refs:
        if not isinstance(ref, ExcelTaskFileRef):
            raise TypeError(f"expected ExcelTaskFileRef, got {type(ref)}")
        key = (ref.role, ref.ordinal)
        if key in seen_ordinals:
            raise ValueError(f"duplicate role and ordinal: {ref.role}[{ref.ordinal}]")
        seen_ordinals.add(key)
        roles_count[ref.role] = roles_count.get(ref.role, 0) + 1

    sources = roles_count.get("source", 0)
    targets = roles_count.get("target", 0)
    baselines = roles_count.get("baseline", 0)
    outputs = roles_count.get("output", 0)

    if operation == "merge_append":
        if sources < 1:
            raise ValueError("merge_append requires at least one source file")
        if outputs != 1:
            raise ValueError("merge_append requires exactly one output file")
        if baselines > 1:
            raise ValueError("merge_append allows at most one baseline file")
        if targets != 0:
            raise ValueError("merge_append does not permit target files")

    elif operation == "merge_overlay":
        if sources < 1:
            raise ValueError("merge_overlay requires at least one source file")
        if targets != 1:
            raise ValueError("merge_overlay requires exactly one target file")
        if outputs != 1:
            raise ValueError("merge_overlay requires exactly one output file")
        if baselines > 1:
            raise ValueError("merge_overlay allows at most one baseline file")

    elif operation == "diff_against_baseline":
        if sources != 0:
            raise ValueError("diff_against_baseline does not permit source files")
        if targets != 1:
            raise ValueError("diff_against_baseline requires exactly one target file")
        if baselines != 1:
            raise ValueError("diff_against_baseline requires exactly one baseline file")
        if outputs != 1:
            raise ValueError("diff_against_baseline requires exactly one output file")


def compute_request_fingerprint(
    operation: str,
    file_refs: Sequence[ExcelTaskFileRef],
    options: Mapping[str, Any] | None = None,
) -> str:
    """计算确定性的请求指纹 SHA-256 摘要。"""
    sorted_files = sorted(file_refs, key=lambda r: (r.role, r.ordinal))
    payload = {
        "operation": operation,
        "files": [ref.to_dict() for ref in sorted_files],
        "options": dict(options or {}),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── ExcelTaskRepository ────────────────────────────────────────
class ExcelTaskRepository:
    """
    Excel 任务持久化仓库与状态机引擎。
    """

    def __init__(self, db_manager: DatabaseManager, roots: ApprovedExcelRoots) -> None:
        self._db = db_manager
        self._roots = roots

    def _begin_immediate(self, conn: sqlite3.Connection) -> None:
        """执行 BEGIN IMMEDIATE 获取 SQLite 写锁（作为并发控制与测试同步接缝）。"""
        conn.execute("BEGIN IMMEDIATE")

    def create_task(
        self,
        operation: str,
        file_refs: Sequence[ExcelTaskFileRef],
        idempotency_key: str,
        *,
        options: Mapping[str, Any] | None = None,
        max_attempts: int = 1,
    ) -> dict[str, Any]:
        """
        原子创建 Excel 任务或幂等重放已有任务。

        在执行文件系统存在性校验之前先解析已有幂等键，
        确保相同的 (idempotency_key, fingerprint) 即使原始输入文件已移动/删除
        也能成功返回原任务记录。
        """
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("idempotency_key must be a non-empty string")
        if len(idempotency_key) > 512:
            raise ValueError("idempotency_key exceeds maximum length (512)")

        # 1. 规范化参数与语法级校验
        validate_task_request(operation, file_refs, options, max_attempts)

        canonical_refs = tuple(
            ExcelTaskFileRef(
                role=r.role,
                root_id=r.root_id,
                relative_path=r.relative_path,
                ordinal=r.ordinal,
            )
            for r in file_refs
        )

        key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        fingerprint = compute_request_fingerprint(operation, canonical_refs, options)
        options_json = json.dumps(dict(options or {}), sort_keys=True, separators=(",", ":"))

        # 2. 幂等查重（在文件系统校验之前）
        with self._db.get_connection() as conn:
            existing = conn.execute(
                "SELECT id, request_fingerprint FROM excel_tasks WHERE idempotency_key_hash = ?",
                (key_hash,),
            ).fetchone()
            if existing is not None:
                if existing["request_fingerprint"] != fingerprint:
                    raise ExcelIdempotencyConflictError(
                        "idempotency key reused with different request fingerprint"
                    )
                return self._format_task(conn, int(existing["id"]))

        # 3. 首次创建：对所有引用执行文件系统存在性与封闭性校验
        for ref in canonical_refs:
            self._roots.resolve_ref(ref, check_role=True)

        # 4. 插入任务与文件关联（处理并发写入竞态）
        with self._db.get_connection() as conn:
            self._begin_immediate(conn)
            # 再次检查防并发
            existing = conn.execute(
                "SELECT id, request_fingerprint FROM excel_tasks WHERE idempotency_key_hash = ?",
                (key_hash,),
            ).fetchone()
            if existing is not None:
                if existing["request_fingerprint"] != fingerprint:
                    raise ExcelIdempotencyConflictError(
                        "idempotency key reused with different request fingerprint"
                    )
                return self._format_task(conn, int(existing["id"]))

            try:
                cursor = conn.execute(
                    """
                    INSERT INTO excel_tasks (
                        operation, status, idempotency_key_hash, request_fingerprint,
                        options_json, attempt_count, max_attempts,
                        created_at, updated_at
                    ) VALUES (?, 'queued', ?, ?, ?, 0, ?,
                             strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                             strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                    """,
                    (operation, key_hash, fingerprint, options_json, max_attempts),
                )
                task_id = cursor.lastrowid

                for ref in canonical_refs:
                    conn.execute(
                        """
                        INSERT INTO excel_task_files (task_id, role, ordinal, root_id, relative_path)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (task_id, ref.role, ref.ordinal, ref.root_id, ref.relative_path),
                    )

                return self._format_task(conn, task_id)

            except sqlite3.IntegrityError:
                existing = conn.execute(
                    "SELECT id, request_fingerprint FROM excel_tasks WHERE idempotency_key_hash = ?",
                    (key_hash,),
                ).fetchone()
                if existing is not None:
                    if existing["request_fingerprint"] != fingerprint:
                        raise ExcelIdempotencyConflictError(
                            "idempotency key reused with different request fingerprint"
                        )
                    return self._format_task(conn, int(existing["id"]))
                raise

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        if not isinstance(task_id, int) or isinstance(task_id, bool) or task_id < 1:
            return None
        with self._db.get_connection() as conn:
            row = conn.execute("SELECT id FROM excel_tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                return None
            return self._format_task(conn, task_id)

    def _format_task(self, conn: sqlite3.Connection, task_id: int) -> dict[str, Any]:
        row = conn.execute(
            """
            SELECT id, operation, status, request_fingerprint, options_json,
                   attempt_count, max_attempts, error_type, error_message,
                   created_at, updated_at, started_at, finished_at
            FROM excel_tasks
            WHERE id = ?
            """,
            (task_id,),
        ).fetchone()
        if row is None:
            raise KeyError(task_id)

        file_rows = conn.execute(
            """
            SELECT role, root_id, relative_path, ordinal
            FROM excel_task_files
            WHERE task_id = ?
            ORDER BY role, ordinal
            """,
            (task_id,),
        ).fetchall()

        files = [
            ExcelTaskFileRef(
                role=str(f["role"]),
                root_id=str(f["root_id"]),
                relative_path=str(f["relative_path"]),
                ordinal=int(f["ordinal"]),
            )
            for f in file_rows
        ]

        try:
            opts = json.loads(row["options_json"]) if row["options_json"] else {}
        except (ValueError, TypeError):
            opts = {}

        return {
            "id": int(row["id"]),
            "operation": str(row["operation"]),
            "status": str(row["status"]),
            "request_fingerprint": str(row["request_fingerprint"]),
            "options": opts,
            "attempt_count": int(row["attempt_count"]),
            "max_attempts": int(row["max_attempts"]),
            "error_type": row["error_type"],
            "error_message": row["error_message"],
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "started_at": str(row["started_at"]) if row["started_at"] else None,
            "finished_at": str(row["finished_at"]) if row["finished_at"] else None,
            "files": files,
        }

    def lease_next(self, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> dict[str, Any] | None:
        if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or not (
            LEASE_MIN_SECONDS <= lease_seconds <= LEASE_MAX_SECONDS
        ):
            raise ValueError(f"lease_seconds must be between {LEASE_MIN_SECONDS} and {LEASE_MAX_SECONDS}")

        modifier = f"+{int(lease_seconds)} seconds"

        with self._db.get_connection() as conn:
            self._begin_immediate(conn)
            # 1. 回收过期租约（使用 CAS 保护，防止与并发 renew/finish 冲突）
            expired_tasks = conn.execute(
                """
                SELECT id, attempt_count, max_attempts, lease_token
                FROM excel_tasks
                WHERE status IN ('leased', 'running')
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                """
            ).fetchall()

            for exp in expired_tasks:
                tid = int(exp["id"])
                attempts = int(exp["attempt_count"])
                max_att = int(exp["max_attempts"])
                exp_token = str(exp["lease_token"]) if exp["lease_token"] else ""

                if attempts < max_att:
                    # CAS 回收重新入队
                    task_cur = conn.execute(
                        """
                        UPDATE excel_tasks
                        SET status = 'queued',
                            lease_token = NULL,
                            lease_acquired_at = NULL,
                            lease_expires_at = NULL,
                            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                        WHERE id = ?
                          AND status IN ('leased', 'running')
                          AND lease_token = ?
                          AND lease_expires_at IS NOT NULL
                          AND lease_expires_at <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                        """,
                        (tid, exp_token),
                    )
                    if task_cur.rowcount == 1:
                        run_cur = conn.execute(
                            """
                            UPDATE excel_task_runs
                            SET run_state = 'expired',
                                finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                            WHERE task_id = ? AND attempt = ?
                              AND run_state IN ('leased', 'running')
                            """,
                            (tid, attempts),
                        )
                        if run_cur.rowcount != 1:
                            raise ExcelInvalidStateError(
                                "expired Excel task does not have exactly one active run"
                            )
                else:
                    # CAS 回收并永久置为 failed
                    safe_msg = redact_sensitive_text(
                        "Task exceeded maximum retry attempts after lease expiration",
                        limit=1000,
                    )
                    task_cur = conn.execute(
                        """
                        UPDATE excel_tasks
                        SET status = 'failed',
                            error_type = 'LeaseExpired',
                            error_message = ?,
                            lease_token = NULL,
                            lease_acquired_at = NULL,
                            lease_expires_at = NULL,
                            finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                        WHERE id = ?
                          AND status IN ('leased', 'running')
                          AND lease_token = ?
                          AND lease_expires_at IS NOT NULL
                          AND lease_expires_at <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                        """,
                        (safe_msg, tid, exp_token),
                    )
                    if task_cur.rowcount == 1:
                        run_cur = conn.execute(
                            """
                            UPDATE excel_task_runs
                            SET run_state = 'expired',
                                error_type = 'LeaseExpired',
                                error_message = ?,
                                finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                            WHERE task_id = ? AND attempt = ?
                              AND run_state IN ('leased', 'running')
                            """,
                            (safe_msg, tid, attempts),
                        )
                        if run_cur.rowcount != 1:
                            raise ExcelInvalidStateError(
                                "expired Excel task does not have exactly one active run"
                            )

            # 2. 查找并租用最旧排队任务
            candidate = conn.execute(
                """
                SELECT id, attempt_count, max_attempts
                FROM excel_tasks
                WHERE status = 'queued'
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """
            ).fetchone()

            if candidate is None:
                return None

            candidate_id = int(candidate["id"])
            token = secrets.token_urlsafe(32)

            cursor = conn.execute(
                """
                UPDATE excel_tasks
                SET status = 'leased',
                    attempt_count = attempt_count + 1,
                    lease_token = ?,
                    lease_acquired_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    lease_expires_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?),
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ? AND status = 'queued'
                """,
                (token, modifier, candidate_id),
            )
            if cursor.rowcount != 1:
                return None

            updated_task = conn.execute(
                "SELECT attempt_count, lease_expires_at FROM excel_tasks WHERE id = ?",
                (candidate_id,),
            ).fetchone()
            current_attempt = int(updated_task["attempt_count"])
            expires_at = str(updated_task["lease_expires_at"])

            run_cursor = conn.execute(
                """
                INSERT INTO excel_task_runs (task_id, attempt, run_state, created_at)
                VALUES (?, ?, 'leased', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """,
                (candidate_id, current_attempt),
            )
            run_id = run_cursor.lastrowid

            return {
                "task_id": candidate_id,
                "run_id": run_id,
                "lease_token": token,
                "attempt": current_attempt,
                "lease_expires_at": expires_at,
                "task": self._format_task(conn, candidate_id),
            }

    def start(self, task_id: int, run_id: int, lease_token: str) -> None:
        if not isinstance(task_id, int) or isinstance(task_id, bool) or task_id < 1:
            raise ExcelLeaseLostError("invalid task_id")
        if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1:
            raise ExcelLeaseLostError("invalid run_id")
        if not isinstance(lease_token, str) or not lease_token:
            raise ExcelLeaseLostError("lease_token is required")

        with self._db.get_connection() as conn:
            # 1. CAS 更新 task (要求 status='leased', lease_token 匹配且未过期)
            task_cursor = conn.execute(
                """
                UPDATE excel_tasks
                SET status = 'running',
                    started_at = COALESCE(started_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                  AND status = 'leased'
                  AND lease_token = ?
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at > strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                """,
                (task_id, lease_token),
            )
            if task_cursor.rowcount != 1:
                # 检查具体失败原因
                task = conn.execute(
                    "SELECT id, status, lease_token, lease_expires_at FROM excel_tasks WHERE id = ?",
                    (task_id,),
                ).fetchone()
                if task is None:
                    raise ExcelLeaseLostError(f"task {task_id} not found")
                if task["status"] != "leased":
                    raise ExcelInvalidStateError(f"task {task_id} is in invalid state: {task['status']!r}")
                if task["lease_token"] != lease_token:
                    raise ExcelLeaseLostError("lease token mismatch")
                raise ExcelLeaseLostError("lease expired")

            # 2. CAS 更新 run (要求 run_state='leased')
            run_cursor = conn.execute(
                """
                UPDATE excel_task_runs
                SET run_state = 'running',
                    started_at = COALESCE(started_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                WHERE id = ?
                  AND task_id = ?
                  AND run_state = 'leased'
                """,
                (run_id, task_id),
            )
            if run_cursor.rowcount != 1:
                run = conn.execute(
                    "SELECT id, run_state FROM excel_task_runs WHERE id = ? AND task_id = ?",
                    (run_id, task_id),
                ).fetchone()
                if run is None:
                    raise ExcelLeaseLostError(f"run {run_id} for task {task_id} not found")
                if run["run_state"] != "leased":
                    raise ExcelInvalidStateError(f"run {run_id} is in invalid state: {run['run_state']!r}")
                raise ExcelLeaseLostError("failed to start run under lease")

    start_task = start

    def renew(
        self,
        task_id: int,
        run_id: int,
        lease_token: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> str:
        if not isinstance(task_id, int) or isinstance(task_id, bool) or task_id < 1:
            raise ExcelLeaseLostError("invalid task_id")
        if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1:
            raise ExcelLeaseLostError("invalid run_id")
        if not isinstance(lease_token, str) or not lease_token:
            raise ExcelLeaseLostError("lease_token is required")
        if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or not (
            LEASE_MIN_SECONDS <= lease_seconds <= LEASE_MAX_SECONDS
        ):
            raise ValueError(f"lease_seconds must be between {LEASE_MIN_SECONDS} and {LEASE_MAX_SECONDS}")

        modifier = f"+{int(lease_seconds)} seconds"

        with self._db.get_connection() as conn:
            # 1. 验证 run 处于活动租约状态
            run = conn.execute(
                """
                SELECT id, run_state FROM excel_task_runs
                WHERE id = ? AND task_id = ? AND run_state IN ('leased', 'running')
                """,
                (run_id, task_id),
            ).fetchone()
            if run is None:
                any_run = conn.execute(
                    "SELECT run_state FROM excel_task_runs WHERE id = ? AND task_id = ?",
                    (run_id, task_id),
                ).fetchone()
                if any_run is None:
                    raise ExcelLeaseLostError(f"run {run_id} for task {task_id} not found")
                raise ExcelInvalidStateError(f"run {run_id} is in invalid state: {any_run['run_state']!r}")

            # 2. CAS 续租 task
            task_cursor = conn.execute(
                """
                UPDATE excel_tasks
                SET lease_expires_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?),
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                  AND status IN ('leased', 'running')
                  AND lease_token = ?
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at > strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                """,
                (modifier, task_id, lease_token),
            )
            if task_cursor.rowcount != 1:
                task = conn.execute(
                    "SELECT id, status, lease_token, lease_expires_at FROM excel_tasks WHERE id = ?",
                    (task_id,),
                ).fetchone()
                if task is None:
                    raise ExcelLeaseLostError(f"task {task_id} not found")
                if task["status"] not in ("leased", "running"):
                    raise ExcelInvalidStateError(f"task {task_id} is in invalid state: {task['status']!r}")
                if task["lease_token"] != lease_token:
                    raise ExcelLeaseLostError("lease token mismatch")
                raise ExcelLeaseLostError("lease expired")

            row = conn.execute("SELECT lease_expires_at FROM excel_tasks WHERE id = ?", (task_id,)).fetchone()
            return str(row["lease_expires_at"])

    renew_lease = renew

    def finish(
        self,
        task_id: int,
        run_id: int,
        lease_token: str,
        status: str,
        *,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if status not in ("succeeded", "failed"):
            raise ValueError(f"finish status must be 'succeeded' or 'failed', got {status!r}")
        if not isinstance(task_id, int) or isinstance(task_id, bool) or task_id < 1:
            raise ExcelLeaseLostError("invalid task_id")
        if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1:
            raise ExcelLeaseLostError("invalid run_id")
        if not isinstance(lease_token, str) or not lease_token:
            raise ExcelLeaseLostError("lease_token is required")

        safe_error_type = redact_sensitive_text(error_type, limit=200) if error_type else None
        safe_error_msg = redact_sensitive_text(error_message, limit=1000) if error_message else None

        with self._db.get_connection() as conn:
            # 1. CAS 完成 task（终态只允许从 running 进入）
            task_cursor = conn.execute(
                """
                UPDATE excel_tasks
                SET status = ?,
                    error_type = ?,
                    error_message = ?,
                    lease_token = NULL,
                    lease_acquired_at = NULL,
                    lease_expires_at = NULL,
                    finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                  AND status = 'running'
                  AND lease_token = ?
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at > strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                """,
                (status, safe_error_type, safe_error_msg, task_id, lease_token),
            )
            if task_cursor.rowcount != 1:
                task = conn.execute(
                    "SELECT id, status, lease_token, lease_expires_at FROM excel_tasks WHERE id = ?",
                    (task_id,),
                ).fetchone()
                if task is None:
                    raise ExcelLeaseLostError(f"task {task_id} not found")
                if task["status"] != "running":
                    raise ExcelInvalidStateError(f"task {task_id} is in invalid state: {task['status']!r}")
                if task["lease_token"] != lease_token:
                    raise ExcelLeaseLostError("lease token mismatch")
                raise ExcelLeaseLostError("lease expired")

            # 2. CAS 完成 run（终态只允许从 running 进入）
            run_cursor = conn.execute(
                """
                UPDATE excel_task_runs
                SET run_state = ?,
                    error_type = ?,
                    error_message = ?,
                    finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                  AND task_id = ?
                  AND run_state = 'running'
                """,
                (status, safe_error_type, safe_error_msg, run_id, task_id),
            )
            if run_cursor.rowcount != 1:
                run = conn.execute(
                    "SELECT id, run_state FROM excel_task_runs WHERE id = ? AND task_id = ?",
                    (run_id, task_id),
                ).fetchone()
                if run is None:
                    raise ExcelLeaseLostError(f"run {run_id} for task {task_id} not found")
                raise ExcelInvalidStateError(f"run {run_id} is in invalid state: {run['run_state']!r}")

    finish_task = finish

    def list_tasks(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 200))
        with self._db.get_connection() as conn:
            if status:
                rows = conn.execute(
                    "SELECT id FROM excel_tasks WHERE status = ? ORDER BY id DESC LIMIT ?",
                    (status, bounded),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id FROM excel_tasks ORDER BY id DESC LIMIT ?",
                    (bounded,),
                ).fetchall()
            return [self._format_task(conn, int(row["id"])) for row in rows]

    def list_task_runs(self, task_id: int) -> list[dict[str, Any]]:
        with self._db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, task_id, attempt, run_state, error_type, error_message,
                       created_at, started_at, finished_at
                FROM excel_task_runs
                WHERE task_id = ?
                ORDER BY id ASC
                """,
                (task_id,),
            ).fetchall()
            return [dict(r) for r in rows]
