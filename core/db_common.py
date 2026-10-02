# -*- coding: utf-8 -*-
"""
core/db_common.py — 数据库层共用的常量、DDL、异常与辅助函数

由 core/db_manager.py 拆出，供 DatabaseManager 及 core/repos/ 各领域分片共用。
原 db_manager 的说明：SQLite 数据库连接管理与 ORM 表结构初始化

职责:
    1. 管理 SQLite 连接的生命周期（上下文管理器）
    2. 初始化 / 迁移所有业务表结构
    3. 提供统一的数据访问入口，禁止各 service 裸连数据库

架构约束:
    - 使用 WAL 模式提升并发读写性能
    - 所有表使用 ISO-8601 时间戳
    - 启用外键约束 (PRAGMA foreign_keys = ON)
"""

# 以下导入同时供 core/repos/ 与 core/db_manager.py 经本模块取用，并非都在本文件内使用。
import json  # noqa: F401
import re  # noqa: F401
import secrets  # noqa: F401
import sqlite3  # noqa: F401
from core import form_registry as _form_registry  # noqa: F401
from core.diagnostic_recording import operation, observed  # noqa: F401
from core.project_status_contracts import (  # noqa: F401
    DELIVERABLE_LINK_REGISTRY,
    PROJECT_STATUS_SOURCE_CAPABILITIES,
    find_deliverable_id_by_form_key,
    project_status_manual_editability,
)
import logging  # noqa: F401
from pathlib import Path  # noqa: F401
from contextlib import contextmanager  # noqa: F401
from typing import Any, Generator, Mapping, Sequence  # noqa: F401

from core.redaction import redact_sensitive_text  # noqa: F401
from core.runtime_paths import app_root  # noqa: F401

logger = logging.getLogger("vse_toolbox.db_manager")


def _dump_extra_fields(extra: object) -> str:
    """extra_fields 快照序列化为 JSON；空快照存空串，避免无意义占位。"""
    if not isinstance(extra, Mapping) or not extra:
        return ""
    return json.dumps(dict(extra), ensure_ascii=False)


# ── 默认数据库路径 ──────────────────────────────────────────────
DEFAULT_DB_DIR = app_root() / "data"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "vse_toolbox.db"

#: 当前支持的 schema 版本。迁移完成后写入 PRAGMA user_version。
#: 旧库 (< CURRENT_SCHEMA_VERSION) 增量升级；高于此版本的库拒绝降级，
#: 避免新代码误读未知的较新 schema。
# v14 also gates old executables: they must not rewrite EWO v2 rules as legacy rules.
CURRENT_SCHEMA_VERSION = 14

#: 租约时长安全范围（秒）。默认 900s，由调用方在范围内参数化。
SYNC_LEASE_MIN_SECONDS = 60
SYNC_LEASE_MAX_SECONDS = 86400
SYNC_LEASE_DEFAULT_SECONDS = 900

#: 默认重试策略：max_attempts=1 即自动重试 0 次。
SYNC_DEFAULT_RETRY_POLICY_JSON = '{"max_attempts":1}'

#: 第三元组元素（deliverable_id）从 core.project_status_contracts
#: DELIVERABLE_LINK_REGISTRY 单一注册表派生；source/report 字面量保留在本表。
ARCHIVE_JOB_CONTRACTS: dict[str, tuple[str, str, str | None]] = {
    "aras_ewo": ("aras", "ewo", DELIVERABLE_LINK_REGISTRY["aras_ewo"]["deliverable_id"]),
    "aras_paa": ("aras", "paa", DELIVERABLE_LINK_REGISTRY["aras_paa"]["deliverable_id"]),
    "aras_ncr_progress": (
        "aras",
        "ncr_progress",
        DELIVERABLE_LINK_REGISTRY["aras_ncr_progress"]["deliverable_id"],
    ),
    "aras_ncr_detail": (
        "aras",
        "ncr_detail",
        DELIVERABLE_LINK_REGISTRY["aras_ncr_detail"]["deliverable_id"],
    ),
    "tdc_data_model": (
        "tdc",
        "data_model",
        DELIVERABLE_LINK_REGISTRY["tdc_data_model"]["deliverable_id"],
    ),
    "tdc_sor": ("tdc", "sor", DELIVERABLE_LINK_REGISTRY["tdc_sor"]["deliverable_id"]),
}

ARCHIVE_CREDENTIAL_UNCHANGED = object()
ARCHIVE_RETRY_UNCHANGED = object()
ARCHIVE_OUTPUT_DIRECTORY_UNCHANGED = object()

#: 数据库生成的 UTC 时间戳 SQL 片段。调度、租约和审计统一使用 UTC，
#: 不使用 simulated_today（后者仅用于业务展示）。
_UTC_NOW_SQL = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"


def _utc_offset_sql(seconds: int) -> str:
    """返回 now + seconds 的 UTC 时间戳 SQL 片段。"""
    sign = "+" if seconds >= 0 else "-"
    return f"strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '{sign}{abs(seconds)} seconds')"


def _normalize_archive_retry_policy(value: object) -> dict[str, object]:
    """Validate the small, task-level archive retry contract."""
    if not isinstance(value, Mapping):
        raise ValueError("archive retry policy must be an object")
    if set(value) - {"max_attempts", "backoff_seconds"}:
        raise ValueError("archive retry policy contains unsupported fields")
    attempts = value.get("max_attempts")
    if isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= 2:
        raise ValueError("archive retry max_attempts must be 1 or 2")
    backoff = value.get("backoff_seconds", 1)
    if isinstance(backoff, bool) or not isinstance(backoff, (int, float)) or not 0 <= backoff <= 60:
        raise ValueError("archive retry backoff_seconds must be between 0 and 60")
    return {
        "max_attempts": attempts,
        "backoff_seconds": int(backoff) if isinstance(backoff, int) else float(backoff),
    }


#: 绑定 updated_at 列沿用 localtime 格式，与表默认值及策略写入保持一致，
#: 避免同一列混用 UTC/localtime 导致字典序比较错乱。
_LOCAL_NOW_SQL = "strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime')"


class SyncLeaseBusyError(RuntimeError):
    """绑定已有未过期租约，本次获取失败且未产生新 run。"""


class SyncLeaseLostError(RuntimeError):
    """租约 token、run 不匹配或已过期；持有者无权启动或提交。"""


class SyncBindingNotReadyError(ValueError):
    """绑定不满足自动同步前置条件（未启用、缺外部键或映射）。"""


class ProjectStatusConcurrentUpdateError(RuntimeError):
    """乐观锁检测到交付物已被并发修改；自动任务不得覆盖人工更新。"""


class MappedDeliverableReadOnlyError(RuntimeError):
    """手工写入命中了已配置外部映射的交付物。"""

    error_type = "MappedDeliverableReadOnly"

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# Keep a concise alias available to callers that use the API error name.
MappedDeliverableReadOnly = MappedDeliverableReadOnlyError


class ArchiveLeaseBusyError(RuntimeError):
    """归档 job 已有未过期租约。"""


class ArchiveLeaseLostError(RuntimeError):
    """归档 job 的租约 token、run 或有效期不匹配。"""


class ArchiveJobNotReadyError(ValueError):
    """归档 job 缺少启用、凭据或固定合同前置条件。

    `reason` 是**闭集**原因码（不反射异常原文），由上层映射为可操作指引；
    调用方不得把上游/自由文本放进该字段。
    """

    #: 闭集原因码（新增值必须同步 services/scheduled_archive_runner 的指引映射）。
    REASONS: tuple[str, ...] = (
        "credential_not_configured",
        "job_disabled",
        "contract_mismatch",
        "filters_invalid",
        "retry_policy_invalid",
        "unknown",
    )

    def __init__(self, message: str, reason: str = "unknown") -> None:
        super().__init__(message)
        self.reason = reason if reason in self.REASONS else "unknown"


def _json_loads_or_none(value: Any) -> Any:
    """安全 JSON 解析；非字符串或解析失败返回 None（区别于空对象）。"""
    if not isinstance(value, str) or not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _json_dumps_local(value: Any) -> str:
    """紧凑 JSON 序列化，保持键有序。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _sanitize_json(value: Any) -> str:
    """脱敏后序列化为 JSON，确保 audit 不存原始敏感片段。"""
    if isinstance(value, dict):
        sanitized = {
            str(key): redact_sensitive_text(item, limit=1000)
            if isinstance(item, str)
            else item
            for key, item in value.items()
        }
    else:
        sanitized = value
    return _json_dumps_local(sanitized)


# 由 core/form_registry.py 推导；写入前据此校验 form_key（表上已无 SQL CHECK）。
_FORM_SNAPSHOT_KEYS = _form_registry.FORM_KEYS
_FORM_SNAPSHOT_REPORTS = {spec.form_key: spec.report for spec in _form_registry.FORMS}
_FORM_SNAPSHOT_FORBIDDEN_KEY_PARTS = (
    "password",
    "token",
    "cookie",
    "authorization",
    "private_key",
    "credential",
    "lease",
    "session",
    "csrf",
)
_FORM_SNAPSHOT_RETENTION = 365


def _is_forbidden_form_key(value: object) -> bool:
    normalized = str(value).strip().casefold().replace("-", "_")
    return any(part in normalized for part in _FORM_SNAPSHOT_FORBIDDEN_KEY_PARTS)


def _sanitize_form_value(value: object, *, key: object | None = None) -> object:
    if key is not None and _is_forbidden_form_key(key):
        return "[redacted]"
    if isinstance(value, Mapping):
        return {
            str(item_key): _sanitize_form_value(item, key=item_key)
            for item_key, item in value.items()
            if not _is_forbidden_form_key(item_key)
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_form_value(item) for item in value]
    if isinstance(value, str):
        return redact_sensitive_text(value, limit=2000)
    return value


def _form_snapshot_payload(snapshot: object) -> dict[str, Any]:
    to_dict = getattr(snapshot, "to_dict", None)
    payload = to_dict() if callable(to_dict) else snapshot
    if not isinstance(payload, Mapping):
        raise ValueError("form snapshot must be an object")
    clean = _sanitize_form_value(payload)
    if not isinstance(clean, Mapping):
        raise ValueError("form snapshot must be an object")
    form_key = str(clean.get("formKey") or clean.get("form_key") or "").strip()
    if form_key not in _FORM_SNAPSHOT_KEYS:
        raise ValueError("unsupported deliverable form key")
    report_type = str(clean.get("reportType") or clean.get("report_type") or "").strip()
    if not report_type:
        raise ValueError("form snapshot report type is required")
    if report_type != _FORM_SNAPSHOT_REPORTS[form_key]:
        raise ValueError("form key and report type do not match")
    snapshot_at = str(clean.get("snapshotAt") or clean.get("snapshot_at") or "").strip()
    if not snapshot_at:
        raise ValueError("form snapshot time is required")
    rows = clean.get("rows")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ValueError("form snapshot rows must be a sequence")
    if len(rows) > 20000:
        raise ValueError("form snapshot rows exceed the limit")
    if any(not isinstance(item, Mapping) for item in rows):
        raise ValueError("form snapshot rows must contain objects")
    schema = clean.get("schema")
    summary = clean.get("summary")
    charts = clean.get("charts")
    if not isinstance(schema, Mapping) or not isinstance(summary, Mapping) or not isinstance(charts, Mapping):
        raise ValueError("form snapshot schema, summary, and charts are required")
    source_run_id = clean.get("sourceRunId", clean.get("source_run_id"))
    if source_run_id is not None and (
        isinstance(source_run_id, bool)
        or not isinstance(source_run_id, int)
        or source_run_id < 1
    ):
        raise ValueError("form snapshot source run id is invalid")
    artifacts = clean.get("artifacts") or []
    if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
        raise ValueError("form snapshot artifacts must be a sequence")
    snapshot_key = f"{form_key}:{source_run_id or 'none'}:{snapshot_at}"
    return {
        "snapshot_key": snapshot_key[:512],
        "form_key": form_key,
        "report_type": report_type[:120],
        "source_run_id": source_run_id,
        "source": str(clean.get("source") or "")[:200],
        "snapshot_at": snapshot_at[:120],
        "rows": list(rows),
        "schema": dict(schema),
        "summary": dict(summary),
        "charts": dict(charts),
        "artifacts": list(artifacts),
    }


def _form_json(value: object, *, limit: int = 4 * 1024 * 1024) -> str:
    serialized = _json_dumps_local(_sanitize_form_value(value))
    if len(serialized.encode("utf-8")) > limit:
        raise ValueError("form snapshot JSON exceeds the limit")
    return serialized


_FORM_ROW_FILTER_KEYS = frozenset(
    {
        "keyword",
        "status",
        "department",
        "section",
        "model",
        "stage",
        "dateStart",
        "dateEnd",
        "overdueState",
        "isCompleted",
        "relationEwo",
    }
)


def _form_row_filter_sql(
    filters: Mapping[str, object] | None,
    *,
    alias: str = "r",
) -> tuple[list[str], list[object]]:
    """Build the allowlisted SQL predicates used by form-row readers."""
    rule = dict(filters or {})
    unknown = set(rule) - _FORM_ROW_FILTER_KEYS
    if unknown:
        raise ValueError("unsupported form row filter")
    where: list[str] = []
    params: list[object] = []

    def filter_values(key: str) -> list[str]:
        value = rule.get(key)
        if value in (None, ""):
            return []
        items = value if isinstance(value, (list, tuple)) else [value]
        cleaned: list[str] = []
        for item in items[:20]:
            text = str(item or "").strip()
            if text and text not in cleaned:
                cleaned.append(text[:200])
        return cleaned

    column_filters = {
        "department": f"{alias}.department_key",
        "section": f"{alias}.section_key",
        "model": f"{alias}.model_key",
        "stage": f"{alias}.stage_key",
        "overdueState": f"{alias}.overdue_state",
    }
    for key, column in column_filters.items():
        values = filter_values(key)
        if values:
            placeholders = ", ".join("?" for _ in values)
            where.append(f"{column} IN ({placeholders})")
            params.extend(values)
    status_values = filter_values("status")
    if status_values:
        # A source can expose CLOSE as CLOZ while the normalized stage is
        # CLOSE; accepting either keeps filters stable without rewriting the
        # source-facing status value stored in the row. 同一字段内多选为 OR。
        status_clause = " OR ".join(
            f"({alias}.status_key = ? OR {alias}.stage_key = ?)"
            for _ in status_values
        )
        where.append(f"({status_clause})")
        for value in status_values:
            params.extend((value, value))
    relation_ewo = str(rule.get("relationEwo") or "").strip()
    if relation_ewo:
        # 关联EWO：EWO 号位于行 values 的搜索文本内（PAA/NCR 表单）。
        where.append(f"instr({alias}.search_text, ?) > 0")
        params.append(relation_ewo[:200])
    if "isCompleted" in rule and rule["isCompleted"] not in (None, ""):
        completed_value: object = rule["isCompleted"]
        if isinstance(completed_value, str):
            completed_value = completed_value.strip().casefold() in {
                "1",
                "true",
                "yes",
                "completed",
            }
        where.append(f"{alias}.is_completed = ?")
        params.append(1 if bool(completed_value) else 0)
    keyword = str(rule.get("keyword") or "").strip()
    if keyword:
        where.append(f"instr(lower({alias}.search_text), lower(?)) > 0")
        params.append(keyword[:200])
    date_start = str(rule.get("dateStart") or "").strip()
    if date_start:
        where.append(f"{alias}.submitted_date >= ?")
        params.append(date_start[:32])
    date_end = str(rule.get("dateEnd") or "").strip()
    if date_end:
        where.append(f"{alias}.submitted_date <= ?")
        params.append(date_end[:32])
    return where, params


# ── 建表 DDL ───────────────────────────────────────────────────
# 每张表均包含 created_at / updated_at 以便追踪

# 统一外部交付物表单快照表 DDL 模板。form_key 不再用 SQL CHECK 白名单
# （新增表单不必再重建表），合法性由写入前的 core/form_registry.py 校验保证。
# 旧库仍带 CHECK 时由 _migrate_schema 用该模板重建一次，DDL 只保留一份。
_DELIVERABLE_FORM_SNAPSHOTS_DDL = """
    CREATE TABLE IF NOT EXISTS {table} (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_key       TEXT NOT NULL UNIQUE,
        form_key           TEXT NOT NULL,
        report_type        TEXT NOT NULL,
        source_run_id      INTEGER,
        source             TEXT NOT NULL DEFAULT '',
        snapshot_at        TEXT NOT NULL,
        row_count          INTEGER NOT NULL CHECK (row_count >= 0),
        schema_json        TEXT NOT NULL,
        summary_json       TEXT NOT NULL,
        charts_json        TEXT NOT NULL,
        artifacts_json     TEXT NOT NULL DEFAULT '[]',
        created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );
    """

# 主计划里程碑表 DDL 模板。schema v13 起 milestone_date 允许为空
# （NULL 表示"待排期"，由用户在编辑主计划时排期）；旧库的 NOT NULL
# 列由 _migrate_schema 用该模板检测并整表重建。
_PROJECT_STATUS_MILESTONES_DDL = """
    CREATE TABLE IF NOT EXISTS {table} (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        phase_id       TEXT NOT NULL,
        name           TEXT NOT NULL,
        milestone_date TEXT,
        status         TEXT NOT NULL,
        type           TEXT NOT NULL CHECK (type IN ('done', 'current', 'planned')),
        sort_order     INTEGER NOT NULL,
        UNIQUE (phase_id, name),
        FOREIGN KEY (phase_id) REFERENCES project_status_phases(id) ON DELETE CASCADE
    );
    """

# 项目状态交付物表 DDL 模板。外部快照驱动交付物（D6-D8）没有手工排期的
# 计划完成日期，planned_date 允许为空（NULL 由展示层输出 plannedDate=null）；
# 旧库的 NOT NULL 列由 _migrate_schema 用该模板检测并整表重建。
_PROJECT_STATUS_DELIVERABLES_DDL = """
    CREATE TABLE IF NOT EXISTS {table} (
        id           TEXT PRIMARY KEY,
        display_code TEXT NOT NULL UNIQUE,
        phase_id     TEXT NOT NULL,
        name         TEXT NOT NULL,
        status       TEXT NOT NULL CHECK (status IN ('已完成', '进行中', '待审批', '已逾期')),
        owner        TEXT NOT NULL,
        planned_date TEXT,
        actual_date  TEXT,
        progress     INTEGER NOT NULL CHECK (progress BETWEEN 0 AND 100),
        remark       TEXT NOT NULL DEFAULT '',
        source       TEXT NOT NULL,
        department   TEXT NOT NULL DEFAULT '',
        stage        TEXT NOT NULL DEFAULT '',
        update_method TEXT NOT NULL DEFAULT 'manual',
        sort_order   INTEGER NOT NULL,
        updated_at   TEXT NOT NULL,
        FOREIGN KEY (phase_id) REFERENCES project_status_phases(id) ON DELETE CASCADE
    );
    """

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
    """,
    # 项目状态仪表盘专用表；与既有 deliverables 业务表隔离，避免语义混用。
    """
    CREATE TABLE IF NOT EXISTS project_status_phases (
        id               TEXT PRIMARY KEY,
        display_name     TEXT NOT NULL DEFAULT '',
        status           TEXT NOT NULL,
        start_date       TEXT NOT NULL,
        end_date         TEXT NOT NULL,
        simulated_today  TEXT NOT NULL,
        overall_progress INTEGER NOT NULL CHECK (overall_progress BETWEEN 0 AND 100),
        planned_progress INTEGER NOT NULL CHECK (planned_progress BETWEEN 0 AND 100),
        updated_at       TEXT NOT NULL
    );
    """,
    _PROJECT_STATUS_MILESTONES_DDL.format(table="project_status_milestones"),
    _PROJECT_STATUS_DELIVERABLES_DDL.format(table="project_status_deliverables"),
    # 交付物更新策略绑定：试点默认 manual + tdc，自动写入未启用。
    # 调度相关内部列（cursor_json/credential_ref/lease_*/retry_policy_json）
    # 仅供同步运行器使用，不通过现有 policy API 返回。
    """
    CREATE TABLE IF NOT EXISTS project_status_update_bindings (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        deliverable_id     TEXT NOT NULL UNIQUE,
        mode               TEXT NOT NULL DEFAULT 'manual'
                           CHECK (mode IN ('manual', 'automatic', 'hybrid')),
        source_type        TEXT NOT NULL DEFAULT 'tdc'
                           CHECK (source_type IN ('feishu', 'aras', 'tdc', 'intranet', 'none')),
        external_key       TEXT,
        match_rule_json    TEXT NOT NULL DEFAULT '{}',
        mapping_json       TEXT NOT NULL DEFAULT '{}',
        enabled            INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
        interval_minutes   INTEGER,
        last_attempt_at    TEXT,
        last_success_at    TEXT,
        sync_state         TEXT NOT NULL DEFAULT 'idle'
                           CHECK (sync_state IN ('idle', 'running', 'success', 'failed', 'needs_attention')),
        last_error_type    TEXT,
        last_error_message TEXT,
        cursor_json        TEXT NOT NULL DEFAULT '{}',
        sync_config_revision INTEGER NOT NULL DEFAULT 0,
        credential_ref     TEXT,
        lease_token        TEXT,
        lease_acquired_at  TEXT,
        lease_expires_at   TEXT,
        retry_policy_json  TEXT NOT NULL DEFAULT '{"max_attempts":1}',
        created_at         TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        updated_at         TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (deliverable_id) REFERENCES project_status_deliverables(id) ON DELETE CASCADE
    );
    """,
    # 同步运行历史与状态机。binding_id 不设外键，刻意与 binding 解耦：
    # binding 被删除（随交付物级联）时运行历史保留，不因配置变更而丢失。
    """
    CREATE TABLE IF NOT EXISTS project_status_sync_runs (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        binding_id       INTEGER NOT NULL,
        deliverable_id   TEXT NOT NULL,
        trigger_type     TEXT NOT NULL
                         CHECK (trigger_type IN ('sync_now', 'scheduled')),
        run_state        TEXT NOT NULL DEFAULT 'leased'
                         CHECK (run_state IN (
                             'leased', 'running', 'success', 'partial',
                             'failed', 'needs_attention', 'expired'
                         )),
        attempt          INTEGER NOT NULL DEFAULT 1,
        external_version TEXT,
        result_summary   TEXT,
        error_type       TEXT,
        error_message    TEXT,
        created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        started_at       TEXT,
        finished_at      TEXT
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ps_sync_runs_binding
        ON project_status_sync_runs(binding_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ps_sync_runs_deliverable
        ON project_status_sync_runs(deliverable_id, run_state);
    """,
    # 一次运行可关联多个 artifact 元数据。M1 仅落地 schema，不写真实文件。
    # relative_path 必须为受控根目录下的相对路径，禁止绝对路径。
    """
    CREATE TABLE IF NOT EXISTS project_status_sync_artifacts (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id        INTEGER NOT NULL,
        artifact_type TEXT NOT NULL,
        relative_path TEXT NOT NULL,
        display_name  TEXT NOT NULL,
        size_bytes    INTEGER,
        sha256        TEXT,
        created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        FOREIGN KEY (run_id) REFERENCES project_status_sync_runs(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ps_sync_artifacts_run
        ON project_status_sync_artifacts(run_id);
    """,
    # 与首页交付物同步解耦的独立归档任务。PAA/NCR 的 dashboard link 必须为空。
    """
    CREATE TABLE IF NOT EXISTS scheduled_archive_jobs (
        id                            INTEGER PRIMARY KEY AUTOINCREMENT,
        job_key                       TEXT NOT NULL UNIQUE,
        source_type                   TEXT NOT NULL CHECK (source_type IN ('aras', 'tdc')),
        report_type                   TEXT NOT NULL,
        project_status_deliverable_id TEXT,
        enabled                       INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
        credential_ref                TEXT,
        interval_minutes              INTEGER NOT NULL DEFAULT 60 CHECK (interval_minutes > 0),
        filters_json                  TEXT NOT NULL DEFAULT '{}',
        output_subdir                 TEXT NOT NULL DEFAULT '',
        output_directory              TEXT NOT NULL DEFAULT '',
        retry_policy_json             TEXT NOT NULL DEFAULT '{"max_attempts":2,"backoff_seconds":1}',
        sync_state                    TEXT NOT NULL DEFAULT 'idle'
                                      CHECK (sync_state IN ('idle', 'running', 'success', 'failed', 'needs_attention')),
        last_attempt_at               TEXT,
        last_success_at               TEXT,
        last_error_type               TEXT,
        last_error_message            TEXT,
        lease_token                   TEXT,
        lease_acquired_at             TEXT,
        lease_expires_at              TEXT,
        display_name                  TEXT NOT NULL DEFAULT '',
        template_key                  TEXT NOT NULL DEFAULT '',
        builtin                       INTEGER NOT NULL DEFAULT 1 CHECK (builtin IN (0, 1)),
        archived_at                   TEXT,
        created_at                    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        updated_at                    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        UNIQUE (source_type, report_type),
        FOREIGN KEY (project_status_deliverable_id)
            REFERENCES project_status_deliverables(id) ON DELETE SET NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS scheduled_archive_runs (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id         INTEGER NOT NULL,
        job_key        TEXT NOT NULL,
        trigger_type   TEXT NOT NULL CHECK (trigger_type IN ('sync_now', 'scheduled')),
        run_state      TEXT NOT NULL DEFAULT 'leased'
                       CHECK (run_state IN ('leased', 'running', 'success', 'partial',
                                            'failed', 'needs_attention', 'expired')),
        attempt        INTEGER NOT NULL DEFAULT 1 CHECK (attempt BETWEEN 1 AND 2),
        record_count   INTEGER,
        result_summary TEXT,
        error_type     TEXT,
        error_message  TEXT,
        created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        started_at     TEXT,
        finished_at    TEXT,
        FOREIGN KEY (job_id) REFERENCES scheduled_archive_jobs(id) ON DELETE RESTRICT
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_archive_runs_job
        ON scheduled_archive_runs(job_id, id DESC);
    """,
    """
    CREATE TABLE IF NOT EXISTS scheduled_archive_artifacts (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id        INTEGER NOT NULL,
        artifact_type TEXT NOT NULL,
        relative_path TEXT NOT NULL,
        display_name  TEXT NOT NULL,
        size_bytes    INTEGER,
        sha256        TEXT,
        created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        UNIQUE (run_id, relative_path),
        FOREIGN KEY (run_id) REFERENCES scheduled_archive_runs(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_archive_artifacts_run
        ON scheduled_archive_artifacts(run_id);
    """,
    """
    CREATE TABLE IF NOT EXISTS scheduled_archive_config_audit (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id       INTEGER NOT NULL,
        job_key      TEXT NOT NULL,
        actor        TEXT NOT NULL CHECK (actor IN ('local_web', 'cli')),
        event_type   TEXT NOT NULL CHECK (event_type = 'configuration_updated'),
        changes_json TEXT NOT NULL,
        created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        FOREIGN KEY (job_id) REFERENCES scheduled_archive_jobs(id) ON DELETE RESTRICT
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_archive_config_audit_job
        ON scheduled_archive_config_audit(job_id, id DESC);
    """,
    """
    CREATE TABLE IF NOT EXISTS project_status_mapping_observations (
        id                     INTEGER PRIMARY KEY AUTOINCREMENT,
        deliverable_id         TEXT NOT NULL,
        source_type            TEXT NOT NULL,
        result_state           TEXT NOT NULL CHECK (result_state IN ('matched','not_found','ambiguous','missing_fields','key_changed')),
        external_key           TEXT,
        candidate_fingerprint  TEXT,
        candidate_count        INTEGER NOT NULL,
        candidate_summary_json TEXT NOT NULL DEFAULT '[]',
        field_report_json      TEXT NOT NULL DEFAULT '{}',
        config_signature       TEXT,
        aggregated_candidate_json TEXT,
        created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        FOREIGN KEY (deliverable_id) REFERENCES project_status_deliverables(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ps_mapping_observations
        ON project_status_mapping_observations(deliverable_id, id DESC);
    """,
    """
    CREATE TABLE IF NOT EXISTS project_status_field_authority (
        deliverable_id TEXT NOT NULL,
        field_name     TEXT NOT NULL,
        authority      TEXT NOT NULL CHECK (authority IN ('manual', 'automatic')),
        source_type    TEXT,
        locked_at      TEXT,
        updated_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        PRIMARY KEY (deliverable_id, field_name),
        FOREIGN KEY (deliverable_id) REFERENCES project_status_deliverables(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS project_status_update_audit (
        id                     INTEGER PRIMARY KEY AUTOINCREMENT,
        deliverable_id         TEXT NOT NULL,
        trigger_type           TEXT NOT NULL
                               CHECK (trigger_type IN ('manual', 'sync_now', 'scheduled')),
        source_type            TEXT,
        external_version       TEXT,
        proposed_changes_json  TEXT NOT NULL DEFAULT '{}',
        applied_changes_json   TEXT NOT NULL DEFAULT '{}',
        skipped_fields_json    TEXT NOT NULL DEFAULT '{}',
        result                 TEXT NOT NULL
                               CHECK (result IN ('applied', 'skipped', 'conflict', 'failed')),
        error_summary          TEXT,
        created_at             TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (deliverable_id) REFERENCES project_status_deliverables(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ps_audit_deliverable
        ON project_status_update_audit(deliverable_id, created_at);
    """,
    # 交付物分析的历史聚合快照。仅保存业务分析所需的计数与科室分布。
    """
    CREATE TABLE IF NOT EXISTS project_status_analysis_snapshots (
        id                     INTEGER PRIMARY KEY AUTOINCREMENT,
        deliverable_id         TEXT NOT NULL,
        source_run_id          INTEGER,
        total_count            INTEGER NOT NULL CHECK (total_count >= 0),
        completed_count        INTEGER NOT NULL CHECK (completed_count >= 0),
        incomplete_count       INTEGER NOT NULL CHECK (incomplete_count >= 0),
        overdue_count          INTEGER NOT NULL CHECK (overdue_count >= 0),
        due_soon_count         INTEGER NOT NULL CHECK (due_soon_count >= 0),
        missing_due_date_count INTEGER NOT NULL CHECK (missing_due_date_count >= 0),
        department_counts_json TEXT NOT NULL DEFAULT '{}',
        snapshot_at            TEXT NOT NULL,
        created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        UNIQUE (deliverable_id, source_run_id),
        FOREIGN KEY (deliverable_id) REFERENCES project_status_deliverables(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS app_settings (
        setting_key TEXT PRIMARY KEY,
        value_json  TEXT NOT NULL,
        updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ps_analysis_snapshots_deliverable
        ON project_status_analysis_snapshots(deliverable_id, snapshot_at DESC, id DESC);
    """,
    # 最新一次分析使用的规范化任务缓存。旧快照只保留聚合数据，限制数据增长。
    """
    CREATE TABLE IF NOT EXISTS project_status_analysis_items (
        deliverable_id TEXT NOT NULL,
        item_key       TEXT NOT NULL,
        display_number TEXT NOT NULL DEFAULT '',
        title          TEXT NOT NULL,
        department     TEXT NOT NULL DEFAULT '未归属',
        owner          TEXT NOT NULL DEFAULT '',
        pending_signers TEXT NOT NULL DEFAULT '',
        source_department TEXT NOT NULL DEFAULT '',
        model_info     TEXT NOT NULL DEFAULT '',
        extra_fields_json TEXT NOT NULL DEFAULT '',
        source_status  TEXT NOT NULL DEFAULT '',
        source_stage   TEXT,
        source_type    TEXT NOT NULL DEFAULT '',
        is_completed   INTEGER NOT NULL CHECK (is_completed IN (0, 1)),
        planned_date   TEXT,
        actual_date    TEXT,
        source_run_id  INTEGER,
        updated_at     TEXT NOT NULL,
        PRIMARY KEY (deliverable_id, item_key),
        FOREIGN KEY (deliverable_id) REFERENCES project_status_deliverables(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ps_analysis_items_filters
        ON project_status_analysis_items(deliverable_id, department, is_completed, planned_date);
    """,
    # 统一外部交付物表单快照。表单行与项目状态分析缓存分离，允许 PAA/NCR
    # 使用归档运行作为来源，同时保留 EWO 的旧分析 API。
    _DELIVERABLE_FORM_SNAPSHOTS_DDL.format(table="deliverable_form_snapshots"),
    """
    CREATE INDEX IF NOT EXISTS idx_deliverable_form_snapshots_latest
        ON deliverable_form_snapshots(form_key, snapshot_at DESC, id DESC);
    """,
    """
    CREATE TABLE IF NOT EXISTS deliverable_form_rows (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id     INTEGER NOT NULL,
        row_key         TEXT NOT NULL,
        row_number      INTEGER NOT NULL CHECK (row_number >= 1),
        sheet_name      TEXT NOT NULL DEFAULT '',
        values_json     TEXT NOT NULL,
        dimensions_json TEXT NOT NULL DEFAULT '{}',
        search_text     TEXT NOT NULL DEFAULT '',
        status_key      TEXT NOT NULL DEFAULT '',
        department_key  TEXT NOT NULL DEFAULT '',
        section_key     TEXT NOT NULL DEFAULT '',
        model_key       TEXT NOT NULL DEFAULT '',
        stage_key       TEXT NOT NULL DEFAULT '',
        submitted_date  TEXT,
        planned_date    TEXT,
        overdue_state   TEXT NOT NULL DEFAULT 'unknown'
                        CHECK (overdue_state IN ('on_time', 'overdue', 'unknown', 'not_applicable')),
        is_completed    INTEGER NOT NULL DEFAULT 0 CHECK (is_completed IN (0, 1)),
        cost_json       TEXT NOT NULL DEFAULT '{}',
        UNIQUE (snapshot_id, row_key),
        FOREIGN KEY (snapshot_id) REFERENCES deliverable_form_snapshots(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_deliverable_form_rows_filter
        ON deliverable_form_rows(
            snapshot_id, department_key, section_key, model_key,
            status_key, stage_key, overdue_state, submitted_date
        );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_deliverable_form_rows_search
        ON deliverable_form_rows(snapshot_id, search_text);
    """,
    # Excel 离线任务主表 (Schema v4; artifact 表在 Schema v5 增加)
    """
    CREATE TABLE IF NOT EXISTS excel_tasks (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        operation            TEXT    NOT NULL
                             CHECK (operation IN ('merge_append', 'merge_overlay', 'diff_against_baseline')),
        status               TEXT    NOT NULL DEFAULT 'queued'
                             CHECK (status IN ('queued', 'leased', 'running', 'succeeded', 'failed', 'cancelled')),
        idempotency_key_hash TEXT    NOT NULL UNIQUE CHECK (length(idempotency_key_hash) = 64),
        request_fingerprint  TEXT    NOT NULL CHECK (length(request_fingerprint) = 64),
        options_json         TEXT    NOT NULL DEFAULT '{}' CHECK (length(options_json) <= 4096),
        attempt_count        INTEGER NOT NULL DEFAULT 0,
        max_attempts         INTEGER NOT NULL DEFAULT 1 CHECK (max_attempts BETWEEN 1 AND 5),
        lease_token          TEXT    CHECK (lease_token IS NULL OR (length(lease_token) >= 16 AND length(lease_token) <= 256)),
        lease_acquired_at    TEXT,
        lease_expires_at     TEXT,
        error_type           TEXT    CHECK (error_type IS NULL OR length(error_type) <= 200),
        error_message        TEXT    CHECK (error_message IS NULL OR length(error_message) <= 1000),
        created_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        updated_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        started_at           TEXT,
        finished_at          TEXT,
        CHECK (attempt_count BETWEEN 0 AND max_attempts)
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_excel_tasks_status
        ON excel_tasks(status, created_at);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_excel_tasks_lease
        ON excel_tasks(status, lease_expires_at);
    """,
    # Excel 任务关联文件引用表
    """
    CREATE TABLE IF NOT EXISTS excel_task_files (
        task_id       INTEGER NOT NULL,
        role          TEXT    NOT NULL
                      CHECK (role IN ('source', 'target', 'baseline', 'output')),
        ordinal       INTEGER NOT NULL DEFAULT 0 CHECK (ordinal >= 0),
        root_id       TEXT    NOT NULL CHECK (length(root_id) BETWEEN 1 AND 128),
        relative_path TEXT    NOT NULL CHECK (length(relative_path) BETWEEN 1 AND 1024),
        PRIMARY KEY (task_id, role, ordinal),
        FOREIGN KEY (task_id) REFERENCES excel_tasks(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_excel_task_files_task
        ON excel_task_files(task_id, role, ordinal);
    """,
    # Excel 任务执行运行历史
    """
    CREATE TABLE IF NOT EXISTS excel_task_runs (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id       INTEGER NOT NULL,
        attempt       INTEGER NOT NULL CHECK (attempt >= 1),
        run_state     TEXT    NOT NULL DEFAULT 'leased'
                      CHECK (run_state IN ('leased', 'running', 'succeeded', 'failed', 'expired', 'cancelled')),
        error_type    TEXT    CHECK (error_type IS NULL OR length(error_type) <= 200),
        error_message TEXT    CHECK (error_message IS NULL OR length(error_message) <= 1000),
        created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        started_at    TEXT,
        finished_at   TEXT,
        UNIQUE (task_id, attempt),
        FOREIGN KEY (task_id) REFERENCES excel_tasks(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_excel_task_runs_task
        ON excel_task_runs(task_id, id DESC);
    """,
    # Excel 任务成功输出 artifact（仅保存受控根与相对路径）
    """
    CREATE TABLE IF NOT EXISTS excel_task_artifacts (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id       INTEGER NOT NULL,
        run_id        INTEGER NOT NULL UNIQUE,
        artifact_type TEXT    NOT NULL DEFAULT 'output'
                      CHECK (artifact_type = 'output'),
        root_id       TEXT    NOT NULL CHECK (length(root_id) BETWEEN 1 AND 128),
        relative_path TEXT    NOT NULL CHECK (length(relative_path) BETWEEN 1 AND 1024),
        display_name  TEXT    NOT NULL CHECK (length(display_name) BETWEEN 1 AND 255),
        size_bytes    INTEGER NOT NULL CHECK (size_bytes >= 0),
        sha256        TEXT    NOT NULL
                      CHECK (length(sha256) = 64
                             AND sha256 = lower(sha256)
                             AND sha256 NOT GLOB '*[^0-9a-f]*'),
        created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        UNIQUE (task_id, relative_path),
        FOREIGN KEY (task_id) REFERENCES excel_tasks(id) ON DELETE CASCADE,
        FOREIGN KEY (run_id) REFERENCES excel_task_runs(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_excel_task_artifacts_task
        ON excel_task_artifacts(task_id, id DESC);
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_excel_task_artifact_run_matches_task
    BEFORE INSERT ON excel_task_artifacts
    FOR EACH ROW
    WHEN NOT EXISTS (
        SELECT 1 FROM excel_task_runs
        WHERE id = NEW.run_id AND task_id = NEW.task_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'excel artifact run does not belong to task');
    END;
    """,
    # Excel artifact 下载审计记录表 (Schema v6; 仅追加审计记录)
    """
    CREATE TABLE IF NOT EXISTS excel_artifact_download_audit (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        artifact_id       INTEGER NOT NULL,
        task_id           INTEGER NOT NULL,
        result            TEXT    NOT NULL
                          CHECK (result IN ('succeeded', 'rejected')),
        reason_code       TEXT    NOT NULL
                          CHECK (length(reason_code) BETWEEN 1 AND 64),
        served_size_bytes INTEGER CHECK (served_size_bytes IS NULL OR served_size_bytes >= 0),
        created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        FOREIGN KEY (artifact_id) REFERENCES excel_task_artifacts(id) ON DELETE CASCADE,
        FOREIGN KEY (task_id) REFERENCES excel_tasks(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_excel_artifact_download_audit_artifact
        ON excel_artifact_download_audit(artifact_id, id DESC);
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_excel_artifact_download_audit_artifact_matches_task
    BEFORE INSERT ON excel_artifact_download_audit
    FOR EACH ROW
    WHEN NOT EXISTS (
        SELECT 1 FROM excel_task_artifacts
        WHERE id = NEW.artifact_id AND task_id = NEW.task_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'excel download audit artifact does not belong to task');
    END;
    """,
    # 爬虫/异步任务表 (crawl_tasks, Schema v14 增量兼容表)
    """
    CREATE TABLE IF NOT EXISTS crawl_tasks (
        task_id        TEXT PRIMARY KEY NOT NULL,
        task_type      TEXT NOT NULL,
        source         TEXT NOT NULL,
        status         TEXT NOT NULL DEFAULT 'queued'
                       CHECK (status IN ('queued', 'leased', 'running', 'succeeded', 'failed', 'cancelled', 'interrupted')),
        params_json    TEXT NOT NULL DEFAULT '{}',
        progress_json  TEXT NOT NULL DEFAULT '{}',
        artifact_path  TEXT,
        error_message  TEXT,
        created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_crawl_tasks_status
        ON crawl_tasks(status, created_at);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_crawl_tasks_source
        ON crawl_tasks(source, status);
    """
]


#: project_status_deliverables 中允许人工编辑并参与字段归属的列。

# 主计划默认里程碑模板：空日期=待排期，由用户在「编辑主计划」中排期后
# 生效。项目初始化与"删除全部节点后保存"都按此模板恢复。
PROJECT_STATUS_MILESTONE_TEMPLATE: tuple[tuple[str, None, str, str, int], ...] = tuple(
    (name, None, "未开始", "planned", index)
    for index, name in enumerate(
        (
            "VPI",
            "内饰模型评审",
            "外饰模型评审",
            "LLP VDR",
            "100% VDR",
            "LLP T2",
            "100% T2",
            "OTS",
            "验证阀",
            "内部体验阀",
            "用户体验阀",
        ),
        start=1,
    )
)

PROJECT_STATUS_EDITABLE_FIELDS: tuple[str, ...] = (
    "status",
    "owner",
    "planned_date",
    "actual_date",
    "progress",
    "remark",
)
