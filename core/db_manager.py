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

import json
import secrets
import sqlite3
import logging
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Generator, Mapping, Sequence

from core.redaction import redact_sensitive_text
from core.runtime_paths import app_root

logger = logging.getLogger("vse_toolbox.db_manager")

# ── 默认数据库路径 ──────────────────────────────────────────────
DEFAULT_DB_DIR = app_root() / "data"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "vse_toolbox.db"

#: 当前支持的 schema 版本。迁移完成后写入 PRAGMA user_version。
#: 旧库 (< CURRENT_SCHEMA_VERSION) 增量升级；高于此版本的库拒绝降级，
#: 避免新代码误读未知的较新 schema。
CURRENT_SCHEMA_VERSION = 10

#: 租约时长安全范围（秒）。默认 900s，由调用方在范围内参数化。
SYNC_LEASE_MIN_SECONDS = 60
SYNC_LEASE_MAX_SECONDS = 86400
SYNC_LEASE_DEFAULT_SECONDS = 900

#: 默认重试策略：max_attempts=1 即自动重试 0 次。
SYNC_DEFAULT_RETRY_POLICY_JSON = '{"max_attempts":1}'

ARCHIVE_JOB_CONTRACTS: dict[str, tuple[str, str, str | None]] = {
    "aras_ewo": ("aras", "ewo", "VPI-T2-D3"),
    "aras_paa": ("aras", "paa", None),
    "aras_ncr_progress": ("aras", "ncr_progress", None),
    "aras_ncr_detail": ("aras", "ncr_detail", None),
    "tdc_data_model": ("tdc", "data_model", "VPI-T2-D5"),
    "tdc_sor": ("tdc", "sor", "VPI-T2-D2"),
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


class ArchiveLeaseBusyError(RuntimeError):
    """归档 job 已有未过期租约。"""


class ArchiveLeaseLostError(RuntimeError):
    """归档 job 的租约 token、run 或有效期不匹配。"""


class ArchiveJobNotReadyError(ValueError):
    """归档 job 缺少启用、凭据或固定合同前置条件。"""


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
    """
    CREATE TABLE IF NOT EXISTS project_status_milestones (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        phase_id       TEXT NOT NULL,
        name           TEXT NOT NULL,
        milestone_date TEXT NOT NULL,
        status         TEXT NOT NULL,
        type           TEXT NOT NULL CHECK (type IN ('done', 'current', 'planned')),
        sort_order     INTEGER NOT NULL,
        UNIQUE (phase_id, name),
        FOREIGN KEY (phase_id) REFERENCES project_status_phases(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS project_status_deliverables (
        id           TEXT PRIMARY KEY,
        display_code TEXT NOT NULL UNIQUE,
        phase_id     TEXT NOT NULL,
        name         TEXT NOT NULL,
        status       TEXT NOT NULL CHECK (status IN ('已完成', '进行中', '待审批', '已逾期')),
        owner        TEXT NOT NULL,
        planned_date TEXT NOT NULL,
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
    """,
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
        source_status  TEXT NOT NULL DEFAULT '',
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
    """
]


#: project_status_deliverables 中允许人工编辑并参与字段归属的列。
PROJECT_STATUS_EDITABLE_FIELDS: tuple[str, ...] = (
    "status",
    "owner",
    "planned_date",
    "actual_date",
    "progress",
    "remark",
)


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
                # 先检查 schema 版本，拒绝降级，再执行任何 DDL。
                # 避免在未知较新 schema 上执行 DDL 后才失败。
                existing_version = conn.execute("PRAGMA user_version").fetchone()[0]
                if existing_version > CURRENT_SCHEMA_VERSION:
                    raise sqlite3.DatabaseError(
                        f"unsupported schema version {existing_version}; "
                        f"this build supports up to {CURRENT_SCHEMA_VERSION}"
                    )

                # 启用 WAL 模式 — 提升并发读写性能
                conn.execute("PRAGMA journal_mode=WAL;")
                # 启用外键约束
                conn.execute("PRAGMA foreign_keys=ON;")

                # 执行所有建表 DDL
                for ddl in TABLE_DEFINITIONS:
                    conn.execute(ddl)

                # 增量迁移：为旧库补齐调度相关列与新表，并维护 user_version。
                # 新库因 DDL 已含最终字段，迁移为幂等 no-op，仅提升版本。
                self._migrate_schema(conn, existing_version)

                # 幂等插入 id=1「未归类」兜底项目，防止 deliverables.project_id 外键孤儿
                conn.execute(
                    "INSERT OR IGNORE INTO projects (id, name, manager, status) "
                    "VALUES (1, '未归类', 'system', 'active');"
                )
                self._seed_project_status(conn)
                self._seed_archive_jobs(conn)

                conn.commit()

            logger.info("数据库初始化完成")

        except sqlite3.Error:
            logger.exception("数据库初始化失败")
            raise

    @staticmethod
    def _migrate_schema(conn: sqlite3.Connection, existing_version: int) -> None:
        """
        幂等增量迁移。

        - 调用方已在执行任何 DDL 前拒绝高于 CURRENT_SCHEMA_VERSION 的库。
        - 对旧库通过 PRAGMA table_info 检测缺失列，逐列 ALTER TABLE ADD COLUMN。
        - 迁移失败由外层 get_connection 回滚，不会留下半迁移状态。
        """
        # project_status_update_bindings 调度相关增量列。
        existing = {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(project_status_update_bindings)"
            )
        }
        additions: list[tuple[str, str]] = [
            ("cursor_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("credential_ref", "TEXT"),
            ("lease_token", "TEXT"),
            ("lease_acquired_at", "TEXT"),
            ("lease_expires_at", "TEXT"),
            ("retry_policy_json", f"TEXT NOT NULL DEFAULT '{SYNC_DEFAULT_RETRY_POLICY_JSON}'"),
        ]
        for column, decl in additions:
            if column not in existing:
                conn.execute(
                    f"ALTER TABLE project_status_update_bindings "
                    f"ADD COLUMN {column} {decl}"
                )

        phase_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(project_status_phases)")
        }
        if "display_name" not in phase_columns:
            conn.execute(
                "ALTER TABLE project_status_phases "
                "ADD COLUMN display_name TEXT NOT NULL DEFAULT ''"
            )
        conn.execute(
            "UPDATE project_status_phases "
            "SET display_name = id || ' 主计划时间轴' "
            "WHERE trim(display_name) = ''"
        )

        deliverable_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(project_status_deliverables)")
        }
        deliverable_additions = [
            ("display_code", "TEXT"),
            ("department", "TEXT NOT NULL DEFAULT ''"),
            ("stage", "TEXT NOT NULL DEFAULT ''"),
            ("update_method", "TEXT NOT NULL DEFAULT 'manual'"),
        ]
        for column, decl in deliverable_additions:
            if column not in deliverable_columns:
                conn.execute(
                    f"ALTER TABLE project_status_deliverables ADD COLUMN {column} {decl}"
                )
        rows = conn.execute(
            "SELECT id FROM project_status_deliverables "
            "WHERE display_code IS NULL OR trim(display_code) = '' "
            "ORDER BY sort_order, id"
        ).fetchall()
        used_codes = {
            str(row["display_code"])
            for row in conn.execute(
                "SELECT display_code FROM project_status_deliverables "
                "WHERE display_code IS NOT NULL AND trim(display_code) <> ''"
            )
        }
        next_number = 1
        for row in rows:
            while f"DEL-{next_number:03d}" in used_codes:
                next_number += 1
            display_code = f"DEL-{next_number:03d}"
            conn.execute(
                "UPDATE project_status_deliverables SET display_code = ? WHERE id = ?",
                (display_code, row["id"]),
            )
            used_codes.add(display_code)
            next_number += 1
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_ps_deliverables_display_code "
            "ON project_status_deliverables(display_code)"
        )

        analysis_item_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(project_status_analysis_items)")
        }
        analysis_item_additions = [
            ("display_number", "TEXT NOT NULL DEFAULT ''"),
            ("pending_signers", "TEXT NOT NULL DEFAULT ''"),
        ]
        for column, decl in analysis_item_additions:
            if column not in analysis_item_columns:
                conn.execute(
                    f"ALTER TABLE project_status_analysis_items ADD COLUMN {column} {decl}"
                )

        conn.execute(
            "UPDATE project_status_milestones SET status = CASE "
            "WHEN status IN ('done', '已达成') OR type = 'done' THEN '已完成' "
            "WHEN status IN ('current', '当前目标节点') OR type = 'current' THEN '进行中' "
            "WHEN status IN ('planned', '计划节点') OR type = 'planned' THEN '未开始' "
            "ELSE status END"
        )

        archive_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(scheduled_archive_jobs)")
        }
        archive_additions = [
            ("output_directory", "TEXT NOT NULL DEFAULT ''"),
            ("display_name", "TEXT NOT NULL DEFAULT ''"),
            ("template_key", "TEXT NOT NULL DEFAULT ''"),
            ("builtin", "INTEGER NOT NULL DEFAULT 1"),
            ("archived_at", "TEXT"),
        ]
        for column, decl in archive_additions:
            if column not in archive_columns:
                conn.execute(
                    f"ALTER TABLE scheduled_archive_jobs ADD COLUMN {column} {decl}"
                )
        conn.execute(
            "UPDATE scheduled_archive_jobs SET template_key = job_key "
            "WHERE trim(template_key) = ''"
        )
        conn.execute(
            "UPDATE scheduled_archive_jobs SET display_name = CASE job_key "
            "WHEN 'aras_ewo' THEN 'EWO' WHEN 'aras_paa' THEN 'PAA' "
            "WHEN 'aras_ncr_progress' THEN 'NCR进度' "
            "WHEN 'aras_ncr_detail' THEN 'NCR明细' "
            "WHEN 'tdc_data_model' THEN '数模设计审核报表' "
            "WHEN 'tdc_sor' THEN 'TDC SOR' ELSE job_key END "
            "WHERE trim(display_name) = ''"
        )
        conn.execute(
            "UPDATE scheduled_archive_jobs "
            "SET display_name = '数模设计审核报表' "
            "WHERE job_key = 'tdc_data_model' AND builtin = 1 "
            "AND display_name = 'TDC数模'"
        )

        if existing_version < CURRENT_SCHEMA_VERSION:
            conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")

    @staticmethod
    def _seed_project_status(conn: sqlite3.Connection) -> None:
        """幂等写入 VPI-T2 仪表盘的初始本地快照。"""
        snapshot = "2026-08-13 09:42:00.000"
        conn.execute(
            """
            INSERT OR IGNORE INTO project_status_phases
                (id, display_name, status, start_date, end_date, simulated_today,
                 overall_progress, planned_progress, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "VPI-T2",
                # 主计划名称即后续交付物的车型锚点，初始默认 F610S，可在
                # 「主计划维护」中手动修改。
                "F610S",
                "进行中",
                "2026-04-08",
                "2026-08-30",
                "2026-08-13",
                64,
                80,
                snapshot,
            ),
        )

        milestones = (
            ("项目启动", "2026-04-08", "已完成", "done"),
            ("策略冻结", "2026-05-12", "已完成", "done"),
            ("定点流程发布", "2026-06-18", "已完成", "done"),
            ("设计冻结", "2026-07-15", "已完成", "done"),
            ("VDR 决策", "2026-08-15", "进行中", "current"),
            ("VPI-T2 Gate", "2026-08-30", "未开始", "planned"),
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO project_status_milestones
                (phase_id, name, milestone_date, status, type, sort_order)
            VALUES ('VPI-T2', ?, ?, ?, ?, ?)
            """,
            [(*item, index) for index, item in enumerate(milestones, start=1)],
        )
        deliverables = (
            ("VPI-T2-D1", "子系统开发策略", "已完成", "王晨", "2026-05-12", "2026-05-10", 100, "无", "内网"),
            ("VPI-T2-D2", "SOR 定点流程", "已完成", "周敏", "2026-06-18", "2026-06-17", 100, "无", "TDC SOR"),
            ("VPI-T2-D3", "EWO 流程", "进行中", "李珊", "2026-08-22", None, 72, "按计划推进", "ARAS EWO"),
            ("VPI-T2-D4", "造型 VDR 审批流程", "待审批", "陈璇", "2026-08-15", None, 90, "等待设计总监审批", "TDC A 面（待契约确认）"),
            ("VPI-T2-D5", "数模设计审核流程报表", "已逾期", "赵岩", "2026-08-08", None, 82, "逾期 5 天", "TDC 数模设计审核流程报表"),
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO project_status_deliverables
                (id, display_code, phase_id, name, status, owner, planned_date, actual_date,
                 progress, remark, source, sort_order, updated_at)
            VALUES (?, ?, 'VPI-T2', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (item[0], f"DEL-{index:03d}", *item[1:], index, snapshot)
                for index, item in enumerate(deliverables, start=1)
            ],
        )
        conn.execute(
            """
            UPDATE project_status_deliverables
            SET name = '数模设计审核流程报表',
                source = 'TDC 数模设计审核流程报表'
            WHERE id = 'VPI-T2-D5'
              AND name = '数模审批流程'
              AND source = 'TDC 数模'
            """
        )
        # 存量库改名迁移：EWO 定点流程 → EWO 流程（种子 INSERT OR IGNORE 不会更新旧行）。
        conn.execute(
            """
            UPDATE project_status_deliverables
            SET name = 'EWO 流程'
            WHERE id = 'VPI-T2-D3'
              AND name = 'EWO 定点流程'
            """
        )
        # 存量库锚点迁移：主计划名称默认改为车型 F610S（旧默认是「VPI-T2 主计划时间轴」）。
        conn.execute(
            """
            UPDATE project_status_phases
            SET display_name = 'F610S'
            WHERE id = 'VPI-T2'
              AND display_name = 'VPI-T2 主计划时间轴'
            """
        )
        for item_id in (item[0] for item in deliverables):
            DatabaseManager._ensure_project_status_policy(conn, str(item_id))
        conn.execute(
            """
            UPDATE project_status_update_bindings
            SET source_type = CASE deliverable_id
                WHEN 'VPI-T2-D2' THEN 'tdc'
                WHEN 'VPI-T2-D3' THEN 'aras'
                WHEN 'VPI-T2-D4' THEN 'tdc'
                WHEN 'VPI-T2-D5' THEN 'tdc'
                ELSE 'none' END
            WHERE deliverable_id IN ('VPI-T2-D1','VPI-T2-D2','VPI-T2-D3','VPI-T2-D4','VPI-T2-D5')
              AND mode = 'manual' AND enabled = 0
              AND external_key IS NULL AND match_rule_json = '{}' AND mapping_json = '{}'
              AND last_attempt_at IS NULL AND last_success_at IS NULL
            """
        )
        conn.execute(
            """
            UPDATE project_status_field_authority
            SET source_type = CASE deliverable_id
                WHEN 'VPI-T2-D2' THEN 'tdc'
                WHEN 'VPI-T2-D3' THEN 'aras'
                WHEN 'VPI-T2-D4' THEN 'tdc'
                WHEN 'VPI-T2-D5' THEN 'tdc'
                ELSE 'none' END
            WHERE deliverable_id IN ('VPI-T2-D1','VPI-T2-D2','VPI-T2-D3','VPI-T2-D4','VPI-T2-D5')
              AND authority = 'manual' AND locked_at IS NULL
            """
        )

    @staticmethod
    def _seed_archive_jobs(conn: sqlite3.Connection) -> None:
        """Seed only fixed, contract-backed archive jobs; never seed TDC A-face."""
        jobs = tuple(
            (job_key, source_type, report_type, deliverable_id)
            for job_key, (source_type, report_type, deliverable_id)
            in ARCHIVE_JOB_CONTRACTS.items()
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO scheduled_archive_jobs
                (job_key, source_type, report_type,
                 project_status_deliverable_id, enabled, interval_minutes,
                 retry_policy_json, sync_state, display_name, template_key, builtin)
            VALUES (?, ?, ?, ?, 0, 60,
                    '{"max_attempts":2,"backoff_seconds":1}', 'idle',
                    CASE ?
                        WHEN 'aras_ewo' THEN 'EWO' WHEN 'aras_paa' THEN 'PAA'
                        WHEN 'aras_ncr_progress' THEN 'NCR进度'
                        WHEN 'aras_ncr_detail' THEN 'NCR明细'
                        WHEN 'tdc_data_model' THEN '数模设计审核报表'
                        WHEN 'tdc_sor' THEN 'TDC SOR' ELSE ? END,
                    ?, 1)
            """,
            [(*job, job[0], job[0], job[0]) for job in jobs],
        )

    def get_project_status(self, phase_id: str) -> tuple[sqlite3.Row | None, list[sqlite3.Row], list[sqlite3.Row]]:
        """读取一个阶段及其里程碑、交付物的同一份已保存快照。"""
        with self.get_connection() as conn:
            phase = conn.execute(
                "SELECT * FROM project_status_phases WHERE id = ?",
                (phase_id,),
            ).fetchone()
            if phase is None:
                return None, [], []
            milestones = conn.execute(
                "SELECT * FROM project_status_milestones WHERE phase_id = ? ORDER BY sort_order, id",
                (phase_id,),
            ).fetchall()
            deliverables = conn.execute(
                "SELECT * FROM project_status_deliverables WHERE phase_id = ? ORDER BY sort_order, id",
                (phase_id,),
            ).fetchall()
            return phase, milestones, deliverables

    def create_project_status_deliverable(
        self,
        phase_id: str,
        values: Mapping[str, object],
    ) -> dict[str, Any]:
        """Create a deliverable while preserving the internal ID/display-code split."""
        required = {"id", "name", "status", "owner", "planned_date", "progress", "source"}
        missing = required - set(values)
        if missing:
            raise ValueError(f"missing deliverable fields: {sorted(missing)}")
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            phase = conn.execute(
                "SELECT 1 FROM project_status_phases WHERE id = ?", (phase_id,)
            ).fetchone()
            if phase is None:
                raise KeyError(phase_id)
            existing_codes = {
                str(row["display_code"])
                for row in conn.execute(
                    "SELECT display_code FROM project_status_deliverables WHERE display_code IS NOT NULL"
                )
            }
            number = 1
            while f"DEL-{number:03d}" in existing_codes:
                number += 1
            display_code = f"DEL-{number:03d}"
            sort_order = int(
                conn.execute(
                    "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM project_status_deliverables WHERE phase_id = ?",
                    (phase_id,),
                ).fetchone()[0]
            )
            now = conn.execute(f"SELECT {_LOCAL_NOW_SQL}").fetchone()[0]
            conn.execute(
                """
                INSERT INTO project_status_deliverables (
                    id, display_code, phase_id, name, status, owner, planned_date,
                    actual_date, progress, remark, source, department, stage,
                    update_method, sort_order, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(values["id"]), display_code, phase_id, str(values["name"]),
                    str(values["status"]), str(values["owner"]), str(values["planned_date"]),
                    values.get("actual_date"), int(str(values["progress"])),
                    str(values.get("remark") or ""), str(values["source"]),
                    str(values.get("department") or ""), str(values.get("stage") or ""),
                    str(values.get("update_method") or "manual"), sort_order, str(now),
                ),
            )
            self._ensure_project_status_policy(conn, str(values["id"]))
            row = conn.execute(
                "SELECT * FROM project_status_deliverables WHERE id = ?", (str(values["id"]),)
            ).fetchone()
            assert row is not None
            return dict(row)

    def get_app_settings(self) -> dict[str, object]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT setting_key, value_json FROM app_settings").fetchall()
        result: dict[str, object] = {}
        for row in rows:
            value = _json_loads_or_none(row["value_json"])
            if value is not None:
                result[str(row["setting_key"])] = value
        return result

    def update_app_settings(self, values: Mapping[str, object]) -> dict[str, object]:
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany(
                """
                INSERT INTO app_settings(setting_key, value_json, updated_at)
                VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                ON CONFLICT(setting_key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                [(str(key), _json_dumps_local(value)) for key, value in values.items()],
            )
        return self.get_app_settings()

    def update_project_status_phase(
        self,
        phase_id: str,
        values: Mapping[str, object],
        expected_updated_at: str,
    ) -> str:
        """Update editable phase metadata using the phase timestamp as an optimistic lock."""
        columns = {
            "display_name": "display_name",
            "status": "status",
            "start_date": "start_date",
            "end_date": "end_date",
        }
        unknown = set(values) - set(columns)
        if unknown:
            raise ValueError(f"unknown project phase field: {sorted(unknown)}")
        if not values:
            return expected_updated_at
        assignments = [f"{columns[key]} = ?" for key in values]
        with self.get_connection() as conn:
            existing = conn.execute(
                "SELECT updated_at FROM project_status_phases WHERE id = ?",
                (phase_id,),
            ).fetchone()
            if existing is None:
                raise KeyError(phase_id)
            cursor = conn.execute(
                f"UPDATE project_status_phases SET {', '.join(assignments)}, "
                f"updated_at = {_LOCAL_NOW_SQL} "
                "WHERE id = ? AND updated_at = ?",
                (*[values[key] for key in values], phase_id, expected_updated_at),
            )
            if cursor.rowcount != 1:
                raise ProjectStatusConcurrentUpdateError("project status phase has changed")
            row = conn.execute(
                "SELECT updated_at FROM project_status_phases WHERE id = ?",
                (phase_id,),
            ).fetchone()
            assert row is not None
            return str(row["updated_at"])

    def replace_project_status_analysis_cache(
        self,
        deliverable_id: str,
        source_run_id: int,
        snapshot: Mapping[str, object],
        items: Sequence[Mapping[str, object]],
        *,
        retention_snapshots: int = 30,
    ) -> None:
        """Atomically publish one aggregate snapshot and replace the latest normalized items."""
        bounded_retention = max(2, min(int(retention_snapshots), 365))
        department_counts_json = json.dumps(
            snapshot.get("department_counts", {}),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.get_connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM project_status_deliverables WHERE id = ?",
                (deliverable_id,),
            ).fetchone()
            if exists is None:
                raise KeyError(deliverable_id)
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO project_status_analysis_snapshots (
                    deliverable_id, source_run_id, total_count, completed_count,
                    incomplete_count, overdue_count, due_soon_count,
                    missing_due_date_count, department_counts_json, snapshot_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(deliverable_id, source_run_id) DO UPDATE SET
                    total_count = excluded.total_count,
                    completed_count = excluded.completed_count,
                    incomplete_count = excluded.incomplete_count,
                    overdue_count = excluded.overdue_count,
                    due_soon_count = excluded.due_soon_count,
                    missing_due_date_count = excluded.missing_due_date_count,
                    department_counts_json = excluded.department_counts_json,
                    snapshot_at = excluded.snapshot_at
                """,
                (
                    deliverable_id,
                    source_run_id,
                    int(str(snapshot["total_count"])),
                    int(str(snapshot["completed_count"])),
                    int(str(snapshot["incomplete_count"])),
                    int(str(snapshot["overdue_count"])),
                    int(str(snapshot["due_soon_count"])),
                    int(str(snapshot["missing_due_date_count"])),
                    department_counts_json,
                    str(snapshot["snapshot_at"]),
                ),
            )
            conn.execute(
                "DELETE FROM project_status_analysis_items WHERE deliverable_id = ?",
                (deliverable_id,),
            )
            conn.executemany(
                """
                INSERT INTO project_status_analysis_items (
                    deliverable_id, item_key, display_number, title, department, owner,
                    pending_signers, source_status, is_completed, planned_date, actual_date,
                    source_run_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        deliverable_id,
                        str(item["item_key"]),
                        str(item.get("display_number") or ""),
                        str(item["title"]),
                        str(item["department"]),
                        str(item["owner"]),
                        str(item.get("pending_signers") or ""),
                        str(item["source_status"]),
                        1 if bool(item["is_completed"]) else 0,
                        item.get("planned_date"),
                        item.get("actual_date"),
                        source_run_id,
                        str(snapshot["snapshot_at"]),
                    )
                    for item in items
                ],
            )
            conn.execute(
                """
                DELETE FROM project_status_analysis_snapshots
                WHERE deliverable_id = ? AND id NOT IN (
                    SELECT id FROM project_status_analysis_snapshots
                    WHERE deliverable_id = ?
                    ORDER BY snapshot_at DESC, id DESC LIMIT ?
                )
                """,
                (deliverable_id, deliverable_id, bounded_retention),
            )

    def list_project_status_analysis_snapshots(
        self,
        deliverable_id: str,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 100))
        with self.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, deliverable_id, source_run_id, total_count,
                       completed_count, incomplete_count, overdue_count,
                       due_soon_count, missing_due_date_count,
                       department_counts_json, snapshot_at, created_at
                FROM project_status_analysis_snapshots
                WHERE deliverable_id = ?
                ORDER BY snapshot_at DESC, id DESC LIMIT ?
                """,
                (deliverable_id, bounded),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_project_status_analysis_items(
        self,
        deliverable_id: str,
        *,
        department: str | None = None,
        completed: bool | None = None,
        offset: int = 0,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 1000))
        bounded_offset = max(0, int(offset))
        sql = """
            SELECT deliverable_id, item_key, title, department, owner,
                   display_number, pending_signers, source_status, is_completed, planned_date, actual_date,
                   source_run_id, updated_at
            FROM project_status_analysis_items
            WHERE deliverable_id = ?
        """
        params: list[object] = [deliverable_id]
        if department:
            sql += " AND department = ?"
            params.append(department)
        if completed is not None:
            sql += " AND is_completed = ?"
            params.append(int(completed))
        sql += " ORDER BY is_completed ASC, planned_date ASC, title ASC LIMIT ? OFFSET ?"
        params.extend([bounded_limit, bounded_offset])
        with self.get_connection() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [dict(row) for row in rows]

    def count_project_status_analysis_items(
        self,
        deliverable_id: str,
        *,
        department: str | None = None,
        completed: bool | None = None,
    ) -> int:
        sql = """
            SELECT COUNT(*) AS total
            FROM project_status_analysis_items
            WHERE deliverable_id = ?
        """
        params: list[object] = [deliverable_id]
        if department:
            sql += " AND department = ?"
            params.append(department)
        if completed is not None:
            sql += " AND is_completed = ?"
            params.append(int(completed))
        with self.get_connection() as conn:
            row = conn.execute(sql, tuple(params)).fetchone()
            return int(row["total"]) if row is not None else 0

    def update_project_status_deliverable(
        self,
        deliverable_id: str,
        phase_id: str,
        values: dict[str, object],
        expected_updated_at: str,
    ) -> str:
        """以更新时间作乐观锁更新交付物，返回新更新时间。"""
        with self.get_connection() as conn:
            updated_at = self._update_project_status_deliverable_row(
                conn,
                deliverable_id,
                phase_id,
                values,
                expected_updated_at,
            )
            conn.execute(
                "UPDATE project_status_phases SET updated_at = ? WHERE id = ?",
                (updated_at, phase_id),
            )
            return updated_at

    @staticmethod
    def _update_project_status_deliverable_row(
        conn: sqlite3.Connection,
        deliverable_id: str,
        phase_id: str,
        values: dict[str, object],
        expected_updated_at: str,
    ) -> str:
        """乐观锁更新交付物行；事务由调用方负责。"""
        columns = {
            "status": "status",
            "owner": "owner",
            "planned_date": "planned_date",
            "actual_date": "actual_date",
            "progress": "progress",
            "remark": "remark",
        }
        unknown = set(values) - set(columns)
        if unknown:
            raise ValueError(f"unknown project status field: {sorted(unknown)}")
        assignments = [f"{columns[key]} = ?" for key in values]
        if not assignments:
            return expected_updated_at
        next_updated_at_sql = "strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime')"
        exists = conn.execute(
            "SELECT updated_at FROM project_status_deliverables WHERE id = ? AND phase_id = ?",
            (deliverable_id, phase_id),
        ).fetchone()
        if exists is None:
            raise KeyError(deliverable_id)
        cursor = conn.execute(
            f"UPDATE project_status_deliverables SET {', '.join(assignments)}, "
            f"updated_at = {next_updated_at_sql} "
            "WHERE id = ? AND phase_id = ? AND updated_at = ?",
            (*[values[key] for key in values], deliverable_id, phase_id, expected_updated_at),
        )
        if cursor.rowcount != 1:
            raise ProjectStatusConcurrentUpdateError("project status record has changed")
        row = conn.execute(
            "SELECT updated_at FROM project_status_deliverables WHERE id = ?",
            (deliverable_id,),
        ).fetchone()
        assert row is not None
        return str(row["updated_at"])

    @staticmethod
    def _ensure_project_status_policy(conn: sqlite3.Connection, deliverable_id: str) -> None:
        """Idempotently seed the confirmed authoritative source assignment."""
        source_type = {
            "VPI-T2-D2": "tdc", "VPI-T2-D3": "aras",
            "VPI-T2-D4": "tdc", "VPI-T2-D5": "tdc",
        }.get(deliverable_id, "none")
        conn.execute(
            """
            INSERT OR IGNORE INTO project_status_update_bindings
                (deliverable_id, mode, source_type, enabled, sync_state)
            VALUES (?, 'manual', ?, 0, 'idle')
            """,
            (deliverable_id, source_type),
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO project_status_field_authority
                (deliverable_id, field_name, authority, source_type)
            VALUES (?, ?, 'manual', ?)
            """,
            [
                (deliverable_id, field_name, source_type)
                for field_name in PROJECT_STATUS_EDITABLE_FIELDS
            ],
        )

    @staticmethod
    def _prune_project_status_audit(
        conn: sqlite3.Connection,
        deliverable_id: str,
        limit: int = 100,
    ) -> None:
        """每个交付物只保留最近 limit 条审计记录。"""
        conn.execute(
            """
            DELETE FROM project_status_update_audit
            WHERE deliverable_id = ?
              AND id NOT IN (
                  SELECT id FROM project_status_update_audit
                  WHERE deliverable_id = ?
                  ORDER BY id DESC LIMIT ?
              )
            """,
            (deliverable_id, deliverable_id, limit),
        )

    def apply_project_status_manual_update(
        self,
        deliverable_id: str,
        phase_id: str,
        values: dict[str, object],
        expected_updated_at: str,
        changed_fields: Sequence[str],
        proposed_changes_json: str,
        applied_changes_json: str,
        source_type: str = "tdc",
    ) -> str:
        """原子执行手动保存：乐观锁更新、人工字段锁和审计落库。"""
        invalid = set(changed_fields) - set(PROJECT_STATUS_EDITABLE_FIELDS)
        if invalid:
            raise ValueError(f"unknown project status field: {sorted(invalid)}")
        with self.get_connection() as conn:
            exists = conn.execute(
                "SELECT id FROM project_status_deliverables WHERE id = ?",
                (deliverable_id,),
            ).fetchone()
            if exists is None:
                raise KeyError(deliverable_id)
            self._ensure_project_status_policy(conn, deliverable_id)
            updated_at = self._update_project_status_deliverable_row(
                conn,
                deliverable_id,
                phase_id,
                values,
                expected_updated_at,
            )

            for field_name in changed_fields:
                conn.execute(
                    """
                    INSERT INTO project_status_field_authority
                        (deliverable_id, field_name, authority, source_type, locked_at, updated_at)
                    VALUES (?, ?, 'manual', ?,
                            strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime'),
                            strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime'))
                    ON CONFLICT(deliverable_id, field_name) DO UPDATE SET
                        authority = 'manual',
                        source_type = excluded.source_type,
                        locked_at = excluded.locked_at,
                        updated_at = excluded.updated_at
                    """,
                    (deliverable_id, field_name, source_type),
                )
            conn.execute(
                """
                INSERT INTO project_status_update_audit
                    (deliverable_id, trigger_type, source_type, external_version,
                     proposed_changes_json, applied_changes_json, skipped_fields_json,
                     result, error_summary)
                VALUES (?, 'manual', ?, NULL, ?, ?, '{}', 'applied', NULL)
                """,
                (deliverable_id, source_type, proposed_changes_json, applied_changes_json),
            )
            self._prune_project_status_audit(conn, deliverable_id)
            conn.execute(
                "UPDATE project_status_phases SET updated_at = ? WHERE id = ?",
                (updated_at, phase_id),
            )
            return updated_at

    def get_project_status_update_policy(self, deliverable_id: str) -> dict[str, object] | None:
        """返回交付物绑定、字段归属和最近审计摘要；未知交付物返回 None。"""
        with self.get_connection() as conn:
            deliverable = conn.execute(
                "SELECT id FROM project_status_deliverables WHERE id = ?",
                (deliverable_id,),
            ).fetchone()
            if deliverable is None:
                return None
            self._ensure_project_status_policy(conn, deliverable_id)
            binding = conn.execute(
                """
                SELECT id, deliverable_id, mode, source_type, external_key,
                       match_rule_json, mapping_json, enabled, interval_minutes,
                       last_attempt_at, last_success_at, sync_state,
                        last_error_type, last_error_message, credential_ref,
                        created_at, updated_at
                FROM project_status_update_bindings
                WHERE deliverable_id = ?
                """,
                (deliverable_id,),
            ).fetchone()
            assert binding is not None
            authorities = conn.execute(
                """
                SELECT field_name, authority, source_type, locked_at, updated_at
                FROM project_status_field_authority
                WHERE deliverable_id = ?
                ORDER BY field_name
                """,
                (deliverable_id,),
            ).fetchall()
            latest = conn.execute(
                """
                SELECT id, trigger_type, source_type, external_version, result,
                       error_summary, created_at
                FROM project_status_update_audit
                WHERE deliverable_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (deliverable_id,),
            ).fetchone()
            return {
                "binding": dict(binding),
                "authorities": [dict(row) for row in authorities],
                "latest_audit": dict(latest) if latest is not None else None,
            }

    def set_project_status_update_policy(
        self,
        deliverable_id: str,
        mode: str,
        enabled: bool,
        external_key: str | None,
        match_rule_json: str,
        mapping_json: str,
        field_authority: dict[str, str],
        credential_ref: str | None = None,
        interval_minutes: int = 60,
    ) -> None:
        """原子写入绑定与字段归属，自动归属同时解除人工锁。"""
        unknown = set(field_authority) - set(PROJECT_STATUS_EDITABLE_FIELDS)
        if unknown:
            raise ValueError(f"unknown project status field: {sorted(unknown)}")
        with self.get_connection() as conn:
            deliverable = conn.execute(
                "SELECT id FROM project_status_deliverables WHERE id = ?",
                (deliverable_id,),
            ).fetchone()
            if deliverable is None:
                raise KeyError(deliverable_id)
            self._ensure_project_status_policy(conn, deliverable_id)
            conn.execute(
                """
                UPDATE project_status_update_bindings
                SET mode = ?, enabled = ?, external_key = ?, match_rule_json = ?,
                    mapping_json = ?, credential_ref = ?, interval_minutes = ?,
                    updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime')
                WHERE deliverable_id = ?
                """,
                (mode, int(enabled), external_key, match_rule_json, mapping_json,
                 credential_ref, interval_minutes, deliverable_id),
            )
            for field_name, authority in field_authority.items():
                conn.execute(
                    """
                    INSERT INTO project_status_field_authority
                        (deliverable_id, field_name, authority, source_type, locked_at, updated_at)
                    VALUES (?, ?, ?, (SELECT source_type FROM project_status_update_bindings WHERE deliverable_id = ?),
                            CASE WHEN ? = 'automatic' THEN NULL
                                 ELSE strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime') END,
                            strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime'))
                    ON CONFLICT(deliverable_id, field_name) DO UPDATE SET
                        authority = excluded.authority,
                        source_type = excluded.source_type,
                        locked_at = excluded.locked_at,
                        updated_at = excluded.updated_at
                    """,
                    (deliverable_id, field_name, authority, deliverable_id, authority),
                )

    def list_project_status_update_audit(
        self,
        deliverable_id: str,
        limit: int = 100,
    ) -> list[sqlite3.Row]:
        """读取按时间倒序的审计记录，最多 limit 条。"""
        with self.get_connection() as conn:
            return conn.execute(
                """
                SELECT id, deliverable_id, trigger_type, source_type, external_version,
                       proposed_changes_json, applied_changes_json, skipped_fields_json,
                       result, error_summary, created_at
                FROM project_status_update_audit
                WHERE deliverable_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (deliverable_id, limit),
            ).fetchall()

    def get_project_status_update_policy_summaries(
        self,
        phase_id: str,
    ) -> dict[str, dict[str, object]]:
        """读取一个阶段全部交付物的绑定摘要，供只读总览增量使用。"""
        with self.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT b.deliverable_id, b.mode, b.source_type, b.enabled, b.sync_state,
                       b.last_attempt_at, b.last_success_at, b.last_error_type,
                       b.last_error_message, b.updated_at
                FROM project_status_update_bindings b
                INNER JOIN project_status_deliverables d ON d.id = b.deliverable_id
                WHERE d.phase_id = ?
                """,
                (phase_id,),
            ).fetchall()
            return {str(row["deliverable_id"]): dict(row) for row in rows}

    # ── 调度运行与租约数据访问 ─────────────────────────────────────
    #
    # 所有租约、运行状态、游标和审计写入均在单一数据库事务内完成。
    # 时间统一使用数据库生成的 UTC 时间戳，不使用 simulated_today。

    @staticmethod
    def _utc_now(conn: sqlite3.Connection) -> str:
        """读取数据库生成的当前 UTC 时间戳，确保与租约 SQL 时钟一致。"""
        row = conn.execute("SELECT " + _UTC_NOW_SQL).fetchone()
        return str(row[0])

    @staticmethod
    def _validate_lease_duration(lease_seconds: int) -> None:
        if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool):
            raise TypeError("lease_seconds must be an int")
        if not (SYNC_LEASE_MIN_SECONDS <= lease_seconds <= SYNC_LEASE_MAX_SECONDS):
            raise ValueError(
                f"lease_seconds must be between {SYNC_LEASE_MIN_SECONDS} "
                f"and {SYNC_LEASE_MAX_SECONDS}"
            )

    @staticmethod
    def _validate_trigger_type(trigger_type: str) -> None:
        if trigger_type not in ("sync_now", "scheduled"):
            raise ValueError(f"unsupported trigger_type: {trigger_type}")

    @staticmethod
    def _validate_run_state(run_state: str) -> None:
        if run_state not in (
            "leased",
            "running",
            "success",
            "partial",
            "failed",
            "needs_attention",
            "expired",
        ):
            raise ValueError(f"unsupported run_state: {run_state}")

    @staticmethod
    def _validate_artifact_metadata(artifact: dict[str, Any]) -> None:
        relative = artifact.get("relative_path")
        if not isinstance(relative, str) or not relative:
            raise ValueError("artifact relative_path is required")
        # 禁止绝对路径与目录穿越：不允许盘符前缀、前导斜杠或 ".." 段。
        norm = relative.replace("\\", "/")
        if (
            len(norm) >= 2 and norm[1] == ":"
        ) or norm.startswith("/"):
            raise ValueError("artifact relative_path must be a relative path")
        segments = norm.split("/")
        if any(segment in ("", ".", "..") for segment in segments):
            raise ValueError("artifact relative_path must not traverse parent directories")
        reserved = {
            "CON", "PRN", "AUX", "NUL",
            *(f"COM{number}" for number in range(1, 10)),
            *(f"LPT{number}" for number in range(1, 10)),
        }
        if any(
            ":" in segment
            or segment.rstrip(" .") != segment
            or segment.split(".", 1)[0].upper() in reserved
            for segment in segments
        ):
            raise ValueError("artifact relative_path contains an unsafe segment")
        artifact_type = artifact.get("artifact_type")
        if not isinstance(artifact_type, str) or not artifact_type.strip():
            raise ValueError("artifact artifact_type is required")
        display_name = artifact.get("display_name")
        if not isinstance(display_name, str) or not display_name.strip():
            raise ValueError("artifact display_name is required")
        size_bytes = artifact.get("size_bytes")
        if size_bytes is not None and (
            not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes < 0
        ):
            raise ValueError("artifact size_bytes must be a non-negative int or None")
        sha256 = artifact.get("sha256")
        if sha256 is not None and (not isinstance(sha256, str) or not sha256.strip()):
            raise ValueError("artifact sha256 must be a non-empty string or None")

    def acquire_sync_lease(
        self,
        binding_id: int,
        trigger_type: str,
        lease_seconds: int = SYNC_LEASE_DEFAULT_SECONDS,
    ) -> dict[str, Any]:
        """
        原子获取同步租约并创建一条 leased run。

        前置校验：binding 存在、enabled=1、mode 为 automatic/hybrid、
        source_type 非 none，且具有已确认 external_key 和非空 mapping/match rule。

        若存在未过期租约，获取失败且不产生新 run（SyncLeaseBusyError）。
        若租约已过期，将旧的活动 run 标记为 expired，再抢占写入新租约。

        返回最小内部 Lease 对象（含 run_id、lease_token、expires_at、
        deliverable_id、phase_id、attempt）。lease_token 不得记录到日志、
        审计或 Web 响应。
        """
        self._validate_trigger_type(trigger_type)
        self._validate_lease_duration(lease_seconds)

        with self.get_connection() as conn:
            binding = conn.execute(
                """
                SELECT b.id, b.deliverable_id, b.mode, b.source_type, b.enabled,
                       b.external_key, b.match_rule_json, b.mapping_json,
                       b.credential_ref,
                       b.lease_token, b.lease_expires_at, b.retry_policy_json,
                       b.sync_state, d.phase_id
                FROM project_status_update_bindings b
                INNER JOIN project_status_deliverables d ON d.id = b.deliverable_id
                WHERE b.id = ?
                """,
                (binding_id,),
            ).fetchone()
            if binding is None:
                raise KeyError(binding_id)
            if not binding["enabled"]:
                raise SyncBindingNotReadyError("binding is not enabled")
            if binding["mode"] not in ("automatic", "hybrid"):
                raise SyncBindingNotReadyError(
                    f"binding mode '{binding['mode']}' does not allow scheduled sync"
                )
            if binding["source_type"] == "none":
                raise SyncBindingNotReadyError("binding source_type is 'none'")
            if not binding["external_key"]:
                raise SyncBindingNotReadyError("binding external_key is not confirmed")
            match_rule = _json_loads_or_none(binding["match_rule_json"])
            mapping = _json_loads_or_none(binding["mapping_json"])
            if not isinstance(match_rule, dict) or not match_rule:
                raise SyncBindingNotReadyError("binding match rule is empty")
            if not isinstance(mapping, dict) or not mapping:
                raise SyncBindingNotReadyError("binding mapping is empty")
            if not str(binding["credential_ref"] or "").strip():
                raise SyncBindingNotReadyError(
                    "credential reference is not configured"
                )

            now = self._utc_now(conn)
            lease_token = secrets.token_urlsafe(32)
            expires_sql = _utc_offset_sql(lease_seconds)

            # 原子抢占租约：UPDATE 的 WHERE 条件同时充当互斥锁。
            # 仅当当前无租约或租约已过期时才能更新成功（rowcount==1）。
            # 两个并发运行器只有一个能拿到 rowcount==1，另一个得到 0 → busy。
            # 这依赖 SQLite 写锁串行化该 UPDATE，无需显式 BEGIN IMMEDIATE。
            cursor = conn.execute(
                f"""
                UPDATE project_status_update_bindings
                SET lease_token = ?,
                    lease_acquired_at = ?,
                    lease_expires_at = {expires_sql},
                    sync_state = 'running',
                    last_attempt_at = ?,
                    updated_at = {_LOCAL_NOW_SQL}
                WHERE id = ?
                  AND (
                      lease_token IS NULL
                      OR lease_expires_at IS NULL
                      OR lease_expires_at <= ?
                  )
                """,
                (
                    lease_token,
                    now,
                    now,
                    binding_id,
                    now,
                ),
            )
            if cursor.rowcount != 1:
                raise SyncLeaseBusyError("binding already has an unexpired lease")

            # 租约获取成功后，回收过期租约对应的旧 run（标记为 expired）。
            conn.execute(
                """
                UPDATE project_status_sync_runs
                SET run_state = 'expired', finished_at = ?
                WHERE binding_id = ? AND run_state IN ('leased', 'running')
                """,
                (now, binding_id),
            )

            # M2A：每次独立 run_once 调用只尝试一次，attempt 固定为 1。
            # retry_policy_json.max_attempts > 1 的重试语义尚未实现，
            # 留待重试策略获批后设计。
            attempt = 1

            run_cursor = conn.execute(
                """
                INSERT INTO project_status_sync_runs
                    (binding_id, deliverable_id, trigger_type, run_state, attempt,
                     created_at)
                VALUES (?, ?, ?, 'leased', ?, ?)
                """,
                (binding_id, binding["deliverable_id"], trigger_type, attempt, now),
            )
            run_id = run_cursor.lastrowid

            expires_row = conn.execute(
                "SELECT lease_expires_at FROM project_status_update_bindings WHERE id = ?",
                (binding_id,),
            ).fetchone()
            return {
                "binding_id": binding_id,
                "run_id": run_id,
                "lease_token": lease_token,
                "lease_expires_at": expires_row["lease_expires_at"],
                "deliverable_id": binding["deliverable_id"],
                "phase_id": binding["phase_id"],
                "attempt": attempt,
                "acquired_at": now,
            }

    def start_sync_run(
        self,
        binding_id: int,
        run_id: int,
        lease_token: str,
    ) -> None:
        """
        受 token 保护的 leased → running 转换。

        旧 token、错误 run_id 或已过期 lease 均不得启动。
        """
        with self.get_connection() as conn:
            self._assert_lease_holder(conn, binding_id, run_id, lease_token)
            now = self._utc_now(conn)
            conn.execute(
                """
                UPDATE project_status_sync_runs
                SET run_state = 'running', started_at = ?
                WHERE id = ? AND run_state = 'leased'
                """,
                (now, run_id),
            )

    @staticmethod
    def _assert_lease_holder(
        conn: sqlite3.Connection,
        binding_id: int,
        run_id: int,
        lease_token: str,
    ) -> None:
        """验证 binding 当前租约与 run 匹配且未过期，否则 SyncLeaseLostError。"""
        if not isinstance(lease_token, str) or not lease_token:
            raise SyncLeaseLostError("lease_token is required")
        binding = conn.execute(
            """
            SELECT lease_token, lease_expires_at
            FROM project_status_update_bindings
            WHERE id = ?
            """,
            (binding_id,),
        ).fetchone()
        if binding is None:
            raise SyncLeaseLostError("binding not found")
        if binding["lease_token"] != lease_token:
            raise SyncLeaseLostError("lease token mismatch")
        expires = binding["lease_expires_at"]
        now_row = conn.execute("SELECT " + _UTC_NOW_SQL).fetchone()
        if expires is None or expires <= str(now_row[0]):
            raise SyncLeaseLostError("lease expired")
        run = conn.execute(
            """
            SELECT id, run_state
            FROM project_status_sync_runs
            WHERE id = ? AND binding_id = ?
            """,
            (run_id, binding_id),
        ).fetchone()
        if run is None:
            raise SyncLeaseLostError("run not found")
        if run["run_state"] in ("success", "partial", "failed", "needs_attention", "expired"):
            raise SyncLeaseLostError(f"run already finalized as {run['run_state']}")

    def finalize_sync_success(
        self,
        binding_id: int,
        run_id: int,
        lease_token: str,
        deliverable_values: dict[str, object],
        expected_updated_at: str,
        phase_id: str,
        skipped_fields: dict[str, str],
        external_version: str,
        proposed_changes_json: str,
        applied_changes_json: str,
        trigger_type: str,
        source_type: str,
        result_summary: str,
        artifacts: Sequence[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        单事务原子完成成功提交：

        - 再次验证 binding_id/run_id/lease_token 仍匹配且租约有效；
        - 验证 cursor/external_version（重复版本 → skipped，不更新业务行）；
        - 验证 snapshot 的 expected_updated_at 乐观锁；
        - 检查字段白名单和 field authority；
        - 更新允许自动写入且未被人工锁定的字段；
        - 写 audit、推进 cursor_json/last_success_at、更新 binding sync_state；
        - 更新 sync_runs 最终状态、写 artifact 元数据、清空当前租约。

        任一步骤失败，整个事务回滚。

        Returns:
            dict 含 updated_at（新版本或原值）和 applied_fields（实际应用字段元组）。
        """
        self._validate_trigger_type(trigger_type)
        with self.get_connection() as conn:
            self._assert_lease_holder(conn, binding_id, run_id, lease_token)

            binding = conn.execute(
                """
                SELECT external_key, cursor_json
                FROM project_status_update_bindings
                WHERE id = ?
                """,
                (binding_id,),
            ).fetchone()
            assert binding is not None

            # 幂等：external_version 已处理 → skipped，不更新业务行但推进 run。
            # cursor 中的 processed_versions 保留处理顺序（非字典序），
            # malformed cursor 安全降级为空列表。
            current_cursor = _json_loads_or_none(binding["cursor_json"])
            processed_versions: list[str] = []
            processed_set: set[str] = set()
            if isinstance(current_cursor, dict):
                versions = current_cursor.get("processed_versions")
                if isinstance(versions, list):
                    for v in versions:
                        text = str(v)
                        if text not in processed_set:
                            processed_versions.append(text)
                            processed_set.add(text)

            now = self._utc_now(conn)
            run_row = conn.execute(
                "SELECT run_state FROM project_status_sync_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            assert run_row is not None

            # 读取字段归属，判定哪些自动字段可写。
            deliverable_id_row = conn.execute(
                "SELECT deliverable_id FROM project_status_sync_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            assert deliverable_id_row is not None
            deliverable_id = deliverable_id_row["deliverable_id"]

            authorities = {
                str(row["field_name"]): {
                    "authority": str(row["authority"]),
                    "locked_at": row["locked_at"],
                }
                for row in conn.execute(
                    """
                    SELECT field_name, authority, locked_at
                    FROM project_status_field_authority
                    WHERE deliverable_id = ?
                    """,
                    (deliverable_id,),
                )
            }

            valid_api_fields = {
                "owner",
                "plannedDate",
                "note",
            }
            unknown = set(deliverable_values) - valid_api_fields
            if unknown:
                raise ValueError(
                    f"connector proposed unsupported fields: {sorted(unknown)}"
                )

            # 过滤出可应用字段：authority=automatic 且 locked_at IS NULL。
            db_field_map = {
                "owner": "owner",
                "plannedDate": "planned_date",
                "note": "remark",
            }
            applicable: dict[str, object] = {}
            skipped: dict[str, str] = dict(skipped_fields)
            for api_name, value in deliverable_values.items():
                db_name = db_field_map[api_name]
                auth = authorities.get(db_name)
                if auth is None:
                    skipped[api_name] = "no field authority configured"
                    continue
                if auth["authority"] == "manual" or auth["locked_at"] is not None:
                    skipped[api_name] = "field is manually locked"
                    continue
                applicable[db_name] = value

            applied_any = bool(applicable)
            already_processed = external_version in processed_set

            if already_processed:
                # 幂等跳过：不更新业务行，audit result=skipped，run_state=success。
                self._insert_audit_row(
                    conn,
                    deliverable_id,
                    trigger_type,
                    source_type,
                    external_version,
                    proposed_changes_json,
                    "{}",
                    _sanitize_json(skipped),
                    "skipped",
                    None,
                )
                self._prune_project_status_audit(conn, deliverable_id)
                self._finalize_run_and_release(
                    conn,
                    binding_id,
                    run_id,
                    "success",
                    result_summary,
                    None,
                    None,
                    now,
                    external_version=external_version,
                )
                self._write_artifacts(conn, run_id, artifacts)
                return {"updated_at": expected_updated_at, "applied_fields": ()}

            # 应用字段更新（乐观锁）。
            updated_at = expected_updated_at
            if applied_any:
                updated_at = self._update_project_status_deliverable_row(
                    conn,
                    deliverable_id,
                    phase_id,
                    applicable,
                    expected_updated_at,
                )
                conn.execute(
                    "UPDATE project_status_phases SET updated_at = ? WHERE id = ?",
                    (updated_at, phase_id),
                )

            audit_result = "applied" if applied_any else "skipped"
            applied_json = _sanitize_json(
                {
                    api_name: applicable[db_name]
                    for api_name, db_name in db_field_map.items()
                    if db_name in applicable
                }
            )
            self._insert_audit_row(
                conn,
                deliverable_id,
                trigger_type,
                source_type,
                external_version,
                proposed_changes_json,
                applied_json,
                _sanitize_json(skipped),
                audit_result,
                None,
            )
            self._prune_project_status_audit(conn, deliverable_id)

            # 推进 cursor：保留处理顺序，新版本追加到末尾，只留最后 100 条。
            if external_version in processed_set:
                next_processed = processed_versions
            else:
                next_processed = processed_versions + [external_version]
            next_cursor = {"processed_versions": next_processed[-100:]}
            conn.execute(
                f"""
                UPDATE project_status_update_bindings
                SET cursor_json = ?,
                    last_success_at = ?,
                    sync_state = ?,
                    updated_at = {_LOCAL_NOW_SQL}
                WHERE id = ?
                """,
                (
                    _json_dumps_local(next_cursor),
                    now,
                    "success",
                    binding_id,
                ),
            )

            # 有跳过字段（含人工锁定）时 run 为 partial；全部应用 → success。
            final_run_state = "partial" if skipped else "success"

            self._finalize_run_and_release(
                conn,
                binding_id,
                run_id,
                final_run_state,
                result_summary,
                None,
                None,
                now,
                external_version=external_version,
            )
            self._write_artifacts(conn, run_id, artifacts)
            applied_api_fields = tuple(
                sorted(
                    api_name
                    for api_name, db_name in db_field_map.items()
                    if db_name in applicable
                )
            )
            return {
                "updated_at": updated_at,
                "applied_fields": applied_api_fields,
                "skipped_fields": dict(skipped),
            }

    def finalize_sync_needs_attention(
        self,
        binding_id: int,
        run_id: int,
        lease_token: str,
        error_type: str,
        sanitized_message: str,
        result_summary: str,
    ) -> None:
        """
        not_found/ambiguous 或候选结构非法时原子结束运行。

        不修改 project_status_deliverables，不推进 cursor/last_success_at。
        """
        with self.get_connection() as conn:
            self._assert_lease_holder(conn, binding_id, run_id, lease_token)
            now = self._utc_now(conn)
            deliverable_id_row = conn.execute(
                "SELECT deliverable_id FROM project_status_sync_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            assert deliverable_id_row is not None
            self._finalize_run_and_release(
                conn,
                binding_id,
                run_id,
                "needs_attention",
                result_summary,
                error_type,
                sanitized_message,
                now,
                sync_state="needs_attention",
            )

    def finalize_sync_failure(
        self,
        binding_id: int,
        run_id: int,
        lease_token: str,
        error_type: str,
        sanitized_message: str,
        result_summary: str,
    ) -> None:
        """
        connector 异常时原子结束运行。

        不修改 project_status_deliverables，不推进 cursor/last_success_at。
        """
        with self.get_connection() as conn:
            self._assert_lease_holder(conn, binding_id, run_id, lease_token)
            now = self._utc_now(conn)
            self._finalize_run_and_release(
                conn,
                binding_id,
                run_id,
                "failed",
                result_summary,
                error_type,
                sanitized_message,
                now,
                sync_state="failed",
            )

    def finalize_sync_conflict(
        self,
        binding_id: int,
        run_id: int,
        lease_token: str,
        deliverable_id: str,
        external_version: str,
        proposed_changes_json: str,
        source_type: str,
        trigger_type: str,
        sanitized_message: str,
    ) -> None:
        """
        乐观锁冲突时原子结束运行：写脱敏 conflict 审计，不覆盖人工更新，
        不推进 cursor，释放当前租约。
        """
        self._validate_trigger_type(trigger_type)
        with self.get_connection() as conn:
            self._assert_lease_holder(conn, binding_id, run_id, lease_token)
            now = self._utc_now(conn)
            self._insert_audit_row(
                conn,
                deliverable_id,
                trigger_type,
                source_type,
                external_version,
                proposed_changes_json,
                "{}",
                "{}",
                "conflict",
                sanitized_message,
            )
            self._prune_project_status_audit(conn, deliverable_id)
            self._finalize_run_and_release(
                conn,
                binding_id,
                run_id,
                "failed",
                "optimistic lock conflict",
                "conflict",
                sanitized_message,
                now,
                sync_state="failed",
            )

    @staticmethod
    def _finalize_run_and_release(
        conn: sqlite3.Connection,
        binding_id: int,
        run_id: int,
        run_state: str,
        result_summary: str,
        error_type: str | None,
        error_message: str | None,
        finished_at: str,
        sync_state: str = "success",
        external_version: str | None = None,
    ) -> None:
        """更新 sync_runs 最终状态并清空 binding 当前租约。"""
        DatabaseManager._validate_run_state(run_state)
        conn.execute(
            """
            UPDATE project_status_sync_runs
            SET run_state = ?, result_summary = ?, error_type = ?,
                error_message = ?, finished_at = ?, external_version = ?
            WHERE id = ?
            """,
            (run_state, result_summary, error_type, error_message,
             finished_at, external_version, run_id),
        )
        conn.execute(
            f"""
            UPDATE project_status_update_bindings
            SET lease_token = NULL,
                lease_acquired_at = NULL,
                lease_expires_at = NULL,
                sync_state = ?,
                updated_at = {_LOCAL_NOW_SQL}
            WHERE id = ?
            """,
            (sync_state, binding_id),
        )

    @staticmethod
    def _write_artifacts(
        conn: sqlite3.Connection,
        run_id: int,
        artifacts: Sequence[dict[str, Any]] | None,
    ) -> None:
        if not artifacts:
            return
        for artifact in artifacts:
            DatabaseManager._validate_artifact_metadata(artifact)
            conn.execute(
                """
                INSERT INTO project_status_sync_artifacts
                    (run_id, artifact_type, relative_path, display_name,
                     size_bytes, sha256)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    artifact["artifact_type"],
                    artifact["relative_path"],
                    artifact["display_name"],
                    artifact.get("size_bytes"),
                    artifact.get("sha256"),
                ),
            )

    @staticmethod
    def _insert_audit_row(
        conn: sqlite3.Connection,
        deliverable_id: str,
        trigger_type: str,
        source_type: str,
        external_version: str | None,
        proposed_changes_json: str,
        applied_changes_json: str,
        skipped_fields_json: str,
        result: str,
        error_summary: str | None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO project_status_update_audit
                (deliverable_id, trigger_type, source_type, external_version,
                 proposed_changes_json, applied_changes_json, skipped_fields_json,
                 result, error_summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                deliverable_id,
                trigger_type,
                source_type,
                external_version,
                proposed_changes_json,
                applied_changes_json,
                skipped_fields_json,
                result,
                error_summary,
            ),
        )

    def get_sync_run(self, run_id: int) -> dict[str, Any] | None:
        """读取一条运行记录（脱敏视图），不存在返回 None。"""
        with self.get_connection() as conn:
            row = conn.execute(
                """
                SELECT id, binding_id, deliverable_id, trigger_type, run_state,
                       attempt, external_version, result_summary, error_type,
                       error_message, created_at, started_at, finished_at
                FROM project_status_sync_runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_sync_artifacts(self, run_id: int) -> list[dict[str, Any]]:
        """读取一次运行的全部 artifact 元数据。"""
        with self.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, run_id, artifact_type, relative_path, display_name,
                       size_bytes, sha256, created_at
                FROM project_status_sync_artifacts
                WHERE run_id = ?
                ORDER BY id
                """,
                (run_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_sync_runs(
        self, deliverable_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return bounded run history without binding secrets or raw payloads."""
        bounded = max(1, min(int(limit), 500))
        sql = """
            SELECT id, binding_id, deliverable_id, trigger_type, run_state,
                   attempt, external_version, result_summary, error_type,
                   error_message, created_at, started_at, finished_at
            FROM project_status_sync_runs
        """
        params: tuple[Any, ...]
        if deliverable_id:
            sql += " WHERE deliverable_id = ?"
            params = (deliverable_id, bounded)
        else:
            params = (bounded,)
        sql += " ORDER BY id DESC LIMIT ?"
        with self.get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_sync_binding_by_deliverable(
        self,
        deliverable_id: str,
    ) -> dict[str, Any] | None:
        """读取交付物的绑定记录（内部视图，含调度列）。"""
        with self.get_connection() as conn:
            row = conn.execute(
                """
                SELECT id, deliverable_id, mode, source_type, enabled,
                       external_key, match_rule_json, mapping_json,
                       interval_minutes, cursor_json, credential_ref,
                       lease_token, lease_acquired_at, lease_expires_at,
                       retry_policy_json, sync_state, last_attempt_at,
                       last_success_at, last_error_type, last_error_message,
                       created_at, updated_at
                FROM project_status_update_bindings
                WHERE deliverable_id = ?
                """,
                (deliverable_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_eligible_sync_bindings(
        self,
        deliverable_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        读取符合 run_once 条件的绑定，供 runner 使用。

        仅返回 enabled=1 且 mode in (automatic, hybrid) 的绑定，以 binding_id 升序。
        同时读取 deliverable 当前 updated_at 和 phase_id。
        不返回 credential_ref、lease_token 等敏感内部列。

        Args:
            deliverable_id: 若提供则精确筛选该交付物的绑定。
        """
        with self.get_connection() as conn:
            if deliverable_id is not None:
                rows = conn.execute(
                    """
                    SELECT b.id, b.deliverable_id, b.source_type, b.external_key,
                           b.match_rule_json, b.mapping_json, b.cursor_json,
                           b.retry_policy_json, b.sync_state,
                           CASE WHEN trim(COALESCE(b.credential_ref, '')) <> ''
                                THEN 1 ELSE 0 END AS credential_configured,
                           d.phase_id, d.updated_at AS deliverable_updated_at
                    FROM project_status_update_bindings b
                    INNER JOIN project_status_deliverables d ON d.id = b.deliverable_id
                    WHERE b.enabled = 1
                      AND b.mode IN ('automatic', 'hybrid')
                      AND b.deliverable_id = ?
                    ORDER BY b.id
                    """,
                    (deliverable_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT b.id, b.deliverable_id, b.source_type, b.external_key,
                           b.match_rule_json, b.mapping_json, b.cursor_json,
                           b.retry_policy_json, b.sync_state,
                           CASE WHEN trim(COALESCE(b.credential_ref, '')) <> ''
                                THEN 1 ELSE 0 END AS credential_configured,
                           d.phase_id, d.updated_at AS deliverable_updated_at
                    FROM project_status_update_bindings b
                    INNER JOIN project_status_deliverables d ON d.id = b.deliverable_id
                    WHERE b.enabled = 1
                      AND b.mode IN ('automatic', 'hybrid')
                    ORDER BY b.id
                    """
                ).fetchall()
            result = [dict(row) for row in rows]
            for item in result:
                item["credential_configured"] = bool(
                    item["credential_configured"]
                )
            return result

    def get_sync_binding_credential_ref(self, binding_id: int) -> str:
        """Return the opaque credential alias for internal connector execution."""
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT credential_ref FROM project_status_update_bindings WHERE id = ?",
                (binding_id,),
            ).fetchone()
        if row is None:
            raise KeyError(binding_id)
        value = str(row["credential_ref"] or "").strip()
        if not value:
            raise SyncBindingNotReadyError("credential reference is not configured")
        return value

    def record_mapping_observation(
        self,
        deliverable_id: str,
        source_type: str,
        result_state: str,
        external_key: str | None,
        candidate_fingerprint: str | None,
        candidate_count: int,
        candidate_summary_json: str,
        field_report_json: str,
    ) -> int:
        allowed = {"matched", "not_found", "ambiguous", "missing_fields", "key_changed"}
        if result_state not in allowed:
            raise ValueError("invalid mapping observation state")
        with self.get_connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM project_status_deliverables WHERE id = ?", (deliverable_id,)
            ).fetchone()
            if exists is None:
                raise KeyError(deliverable_id)
            cursor = conn.execute(
                """
                INSERT INTO project_status_mapping_observations
                    (deliverable_id, source_type, result_state, external_key,
                     candidate_fingerprint, candidate_count,
                     candidate_summary_json, field_report_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (deliverable_id, source_type, result_state, external_key,
                 candidate_fingerprint, candidate_count,
                 _sanitize_json(_json_loads_or_none(candidate_summary_json) or []),
                 _sanitize_json(_json_loads_or_none(field_report_json) or {})),
            )
            conn.execute(
                """
                DELETE FROM project_status_mapping_observations
                WHERE deliverable_id = ? AND id NOT IN (
                    SELECT id FROM project_status_mapping_observations
                    WHERE deliverable_id = ? ORDER BY id DESC LIMIT 100
                )
                """,
                (deliverable_id, deliverable_id),
            )
            return int(cursor.lastrowid)

    def list_mapping_observations(self, deliverable_id: str, limit: int = 20) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 100))
        with self.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, deliverable_id, source_type, result_state, external_key,
                       candidate_fingerprint, candidate_count,
                       candidate_summary_json, field_report_json, created_at
                FROM project_status_mapping_observations
                WHERE deliverable_id = ? ORDER BY id DESC LIMIT ?
                """,
                (deliverable_id, bounded),
            ).fetchall()
        return [dict(row) for row in rows]

    def mapping_stability_count(self, deliverable_id: str) -> int:
        rows = self.list_mapping_observations(deliverable_id, 2)
        if not rows or rows[0]["result_state"] != "matched":
            return 0
        key = rows[0]["external_key"]
        source_type = rows[0]["source_type"]
        count = 0
        for row in rows:
            if (
                row["result_state"] != "matched"
                or row["external_key"] != key
                or row["source_type"] != source_type
            ):
                break
            count += 1
        return count

    def replace_project_status_milestones(
        self,
        phase_id: str,
        milestones: list[dict[str, object]],
        expected_updated_at: str,
    ) -> str:
        """以单一事务替换阶段里程碑，并用阶段更新时间作乐观锁。"""
        next_updated_at_sql = "strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime')"
        with self.get_connection() as conn:
            phase = conn.execute(
                "SELECT updated_at FROM project_status_phases WHERE id = ?",
                (phase_id,),
            ).fetchone()
            if phase is None:
                raise KeyError(phase_id)
            if str(phase["updated_at"]) != expected_updated_at:
                raise RuntimeError("project status phase has changed")

            existing_ids = {
                int(row["id"])
                for row in conn.execute(
                    "SELECT id FROM project_status_milestones WHERE phase_id = ?",
                    (phase_id,),
                ).fetchall()
            }
            requested_ids = {
                int(item["id"])
                for item in milestones
                if item.get("id") is not None
            }
            if not requested_ids.issubset(existing_ids):
                raise KeyError("milestone")

            # 全量重建该阶段的短列表，避免两个合法节点交换名称时触发临时唯一键冲突。
            conn.execute(
                "DELETE FROM project_status_milestones WHERE phase_id = ?",
                (phase_id,),
            )
            for item in milestones:
                milestone_id = item.get("id")
                columns = "phase_id, name, milestone_date, status, type, sort_order"
                values = (
                    phase_id,
                    item["name"],
                    item["date"],
                    item["status"],
                    item["type"],
                    item["sort_order"],
                )
                if milestone_id is None:
                    conn.execute(
                        f"INSERT INTO project_status_milestones ({columns}) VALUES (?, ?, ?, ?, ?, ?)",
                        values,
                    )
                else:
                    conn.execute(
                        f"INSERT INTO project_status_milestones (id, {columns}) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (int(milestone_id), *values),
                    )

            cursor = conn.execute(
                f"UPDATE project_status_phases SET updated_at = {next_updated_at_sql} "
                "WHERE id = ? AND updated_at = ?",
                (phase_id, expected_updated_at),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("project status phase has changed")
            row = conn.execute(
                "SELECT updated_at FROM project_status_phases WHERE id = ?",
                (phase_id,),
            ).fetchone()
            assert row is not None
            return str(row["updated_at"])

    def update_archive_job_config(
        self,
        job_key: str,
        *,
        enabled: bool,
        filters: Mapping[str, object],
        output_subdir: str,
        output_directory: object = ARCHIVE_OUTPUT_DIRECTORY_UNCHANGED,
        expected_updated_at: str,
        actor: str,
        credential_ref: object = ARCHIVE_CREDENTIAL_UNCHANGED,
        interval_minutes: int = 60,
        retry_policy: object = ARCHIVE_RETRY_UNCHANGED,
    ) -> dict[str, Any]:
        """Optimistically update one fixed job and append a secret-free audit."""
        from core.archive_store import ArchiveStore

        if isinstance(interval_minutes, bool) or not 5 <= int(interval_minutes) <= 10080:
            raise ValueError("archive interval must be between 5 and 10080 minutes")
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a bool")
        if not isinstance(filters, Mapping) or any(
            not isinstance(key, str) for key in filters
        ):
            raise ValueError("archive filters must be an object with string keys")
        sensitive_names = {
            "authorization", "cookie", "token", "password", "secret",
            "credential", "session", "csrf",
        }
        for key, value in filters.items():
            lowered = key.strip().lower()
            if not lowered or any(name in lowered for name in sensitive_names):
                raise ValueError("archive filter name is not allowed")
            if value is None or isinstance(value, str):
                continue
            if isinstance(value, list) and all(
                isinstance(item, str) for item in value
            ):
                continue
            raise ValueError("archive filter values must be strings or string lists")
        filters_json = json.dumps(
            dict(filters), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if len(filters_json.encode("utf-8")) > 16 * 1024:
            raise ValueError("archive filters exceed the configured limit")
        safe_subdir = ArchiveStore.validate_output_subdir(output_subdir)
        if not isinstance(expected_updated_at, str) or not expected_updated_at:
            raise ValueError("expected_updated_at is required")
        if actor not in {"local_web", "cli"}:
            raise ValueError("archive configuration actor is invalid")

        with self.get_connection() as conn:
            row = conn.execute(
                """
                SELECT id, enabled, credential_ref, filters_json,
                       output_subdir, output_directory, interval_minutes, retry_policy_json, updated_at,
                       lease_token, lease_expires_at, template_key, archived_at
                FROM scheduled_archive_jobs WHERE job_key = ?
                """,
                (job_key,),
            ).fetchone()
            if row is None:
                raise KeyError(job_key)
            if row["archived_at"] is not None or str(row["template_key"]) not in ARCHIVE_JOB_CONTRACTS:
                raise KeyError(job_key)
            if str(row["updated_at"]) != expected_updated_at:
                raise RuntimeError("archive job configuration has changed")
            now = self._utc_now(conn)
            if (
                row["lease_token"] is not None
                and row["lease_expires_at"] is not None
                and str(row["lease_expires_at"]) > now
            ):
                raise ArchiveLeaseBusyError(
                    "archive job configuration cannot change during an active lease"
                )

            if output_directory is ARCHIVE_OUTPUT_DIRECTORY_UNCHANGED:
                safe_output_directory = str(row["output_directory"] or "")
            else:
                safe_output_directory = ArchiveStore.validate_output_directory(
                    output_directory
                )
            if safe_output_directory and safe_subdir:
                raise ValueError(
                    "archive output directory cannot be combined with a legacy output subdirectory"
                )

            current_ref = str(row["credential_ref"] or "").strip()
            if credential_ref is ARCHIVE_CREDENTIAL_UNCHANGED:
                next_ref: str | None = current_ref or None
            elif credential_ref is None:
                next_ref = None
            elif isinstance(credential_ref, str):
                next_ref = credential_ref.strip()
                if (
                    not next_ref
                    or len(next_ref) > 256
                    or any(ord(char) < 32 for char in next_ref)
                ):
                    raise ValueError("credential reference alias is invalid")
            else:
                raise TypeError("credential_ref must be a string, null, or omitted")
            if enabled and not next_ref:
                raise ArchiveJobNotReadyError(
                    "enabled archive job requires a credential reference alias"
                )

            current_retry = _json_loads_or_none(row["retry_policy_json"])
            if not isinstance(current_retry, dict):
                raise ValueError("archive retry policy is invalid")
            if retry_policy is ARCHIVE_RETRY_UNCHANGED:
                next_retry = current_retry
                next_retry_json = str(row["retry_policy_json"])
            else:
                next_retry = _normalize_archive_retry_policy(retry_policy)
                next_retry_json = json.dumps(
                    next_retry,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )

            changed: list[str] = []
            if bool(row["enabled"]) != enabled:
                changed.append("enabled")
            if current_ref != str(next_ref or ""):
                changed.append("credentialRef")
            if str(row["filters_json"]) != filters_json:
                changed.append("filters")
            if str(row["output_subdir"] or "") != safe_subdir:
                changed.append("outputSubdir")
            if str(row["output_directory"] or "") != safe_output_directory:
                changed.append("outputDirectory")
            if int(row["interval_minutes"]) != int(interval_minutes):
                changed.append("intervalMinutes")
            if str(row["retry_policy_json"]) != next_retry_json:
                changed.append("retryPolicy")
            if changed:
                cursor = conn.execute(
                    f"""
                    UPDATE scheduled_archive_jobs
                    SET enabled = ?, credential_ref = ?, filters_json = ?,
                        output_subdir = ?, output_directory = ?, interval_minutes = ?, retry_policy_json = ?,
                        sync_state = ?, updated_at = {_UTC_NOW_SQL}
                    WHERE id = ? AND updated_at = ?
                    """,
                    (
                        int(enabled), next_ref, filters_json, safe_subdir,
                        safe_output_directory, int(interval_minutes), next_retry_json,
                        "needs_attention" if enabled else "idle",
                        int(row["id"]), expected_updated_at,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("archive job configuration has changed")
                changes_json = json.dumps(
                    {
                        "fields": sorted(changed),
                        "credentialConfigured": bool(next_ref),
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
                conn.execute(
                    """
                    INSERT INTO scheduled_archive_config_audit
                        (job_id, job_key, actor, event_type, changes_json)
                    VALUES (?, ?, ?, 'configuration_updated', ?)
                    """,
                    (int(row["id"]), job_key, actor, changes_json),
                )
        result = next(
            (item for item in self.list_archive_jobs() if item["job_key"] == job_key),
            None,
        )
        if result is None:
            raise KeyError(job_key)
        return result

    def list_archive_config_audit(
        self, job_key: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return bounded configuration audit entries without aliases or values."""
        bounded = max(1, min(int(limit), 500))
        sql = """
            SELECT id, job_id, job_key, actor, event_type,
                   changes_json, created_at
            FROM scheduled_archive_config_audit
        """
        if job_key:
            sql += " WHERE job_key = ? ORDER BY id DESC LIMIT ?"
            params: tuple[Any, ...] = (job_key, bounded)
        else:
            sql += " ORDER BY id DESC LIMIT ?"
            params = (bounded,)
        with self.get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def list_archive_jobs(
        self, enabled_only: bool = False, include_archived: bool = False
    ) -> list[dict[str, Any]]:
        """Return archive job configuration without credential aliases or lease tokens."""
        sql = """
            SELECT id, job_key, source_type, report_type, display_name,
                   template_key, builtin, archived_at,
                   project_status_deliverable_id, enabled, interval_minutes,
                   filters_json, output_subdir, output_directory, retry_policy_json, sync_state,
                   last_attempt_at, last_success_at, last_error_type,
                   last_error_message,
                   CASE WHEN trim(COALESCE(credential_ref, '')) <> ''
                        THEN 1 ELSE 0 END AS credential_configured,
                   created_at, updated_at
            FROM scheduled_archive_jobs
        """
        conditions = []
        if enabled_only:
            conditions.append("enabled = 1")
        if not include_archived:
            conditions.append("archived_at IS NULL")
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY id"
        with self.get_connection() as conn:
            rows = conn.execute(sql).fetchall()
        result = [dict(row) for row in rows]
        for item in result:
            item["enabled"] = bool(item["enabled"])
            item["credential_configured"] = bool(
                item["credential_configured"]
            )
            item["builtin"] = bool(item["builtin"])
        return result

    def create_archive_job_from_template(
        self,
        template_key: str,
        *,
        display_name: str,
        copy_from_job_key: str | None = None,
    ) -> dict[str, Any]:
        contract = ARCHIVE_JOB_CONTRACTS.get(template_key)
        if contract is None:
            raise KeyError(template_key)
        clean_name = str(display_name or "").strip()
        if not clean_name or len(clean_name) > 100:
            raise ValueError("archive task display name is invalid")
        with self.get_connection() as conn:
            source = None
            if copy_from_job_key:
                source = conn.execute(
                    "SELECT * FROM scheduled_archive_jobs WHERE job_key = ? AND archived_at IS NULL",
                    (copy_from_job_key,),
                ).fetchone()
                if source is None or str(source["template_key"]) != template_key:
                    raise KeyError(copy_from_job_key)
            token = secrets.token_hex(5)
            job_key = f"{template_key}_{token}"
            source_type, canonical_report_type, deliverable_id = contract
            cursor = conn.execute(
                """
                INSERT INTO scheduled_archive_jobs (
                    job_key, source_type, report_type, project_status_deliverable_id,
                    enabled, credential_ref, interval_minutes, filters_json,
                    output_subdir, output_directory, retry_policy_json, sync_state,
                    display_name, template_key, builtin
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'idle', ?, ?, 0)
                """,
                (
                    job_key,
                    source_type,
                    f"{canonical_report_type}:{token}",
                    deliverable_id,
                    int(bool(source["enabled"])) if source else 0,
                    source["credential_ref"] if source else None,
                    int(source["interval_minutes"]) if source else 60,
                    source["filters_json"] if source else "{}",
                    source["output_subdir"] if source else "",
                    source["output_directory"] if source else "",
                    source["retry_policy_json"] if source else '{"max_attempts":2,"backoff_seconds":1}',
                    clean_name,
                    template_key,
                ),
            )
            job_id = int(cursor.lastrowid)
        return next(item for item in self.list_archive_jobs() if int(item["id"]) == job_id)

    def archive_archive_job(self, job_key: str, expected_updated_at: str) -> dict[str, Any]:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT id, builtin, updated_at, archived_at FROM scheduled_archive_jobs WHERE job_key = ?",
                (job_key,),
            ).fetchone()
            if row is None or row["archived_at"] is not None:
                raise KeyError(job_key)
            cursor = conn.execute(
                f"UPDATE scheduled_archive_jobs SET enabled = 0, archived_at = {_UTC_NOW_SQL}, "
                f"updated_at = {_UTC_NOW_SQL} WHERE id = ? AND updated_at = ?",
                (int(row["id"]), expected_updated_at),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("archive job configuration has changed")
        archived = next(
            item for item in self.list_archive_jobs(include_archived=True) if item["job_key"] == job_key
        )
        return archived

    def get_archive_job_credential_ref(self, job_id: int) -> str:
        """Return one opaque alias for internal execution only."""
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT credential_ref FROM scheduled_archive_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        value = str(row["credential_ref"] or "").strip()
        if not value:
            raise ArchiveJobNotReadyError(
                "archive job credential reference is not configured"
            )
        return value

    def acquire_archive_job_lease(
        self,
        job_id: int,
        trigger_type: str,
        lease_seconds: int = SYNC_LEASE_DEFAULT_SECONDS,
    ) -> dict[str, Any]:
        """Atomically lease one fixed archive job and create a leased run."""
        self._validate_trigger_type(trigger_type)
        self._validate_lease_duration(lease_seconds)
        with self.get_connection() as conn:
            job = conn.execute(
                """
                SELECT id, job_key, source_type, report_type, template_key, archived_at,
                       project_status_deliverable_id, enabled, credential_ref,
                       filters_json, output_subdir, output_directory, retry_policy_json,
                       lease_token, lease_expires_at
                FROM scheduled_archive_jobs WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
            if job is None:
                raise KeyError(job_id)
            template_key = str(job["template_key"] or job["job_key"])
            contract = ARCHIVE_JOB_CONTRACTS.get(template_key)
            actual = (
                str(job["source_type"]),
                contract[1] if contract else str(job["report_type"]),
                job["project_status_deliverable_id"],
            )
            if contract is None or actual != contract or job["archived_at"] is not None:
                raise ArchiveJobNotReadyError(
                    "archive job does not match a fixed approved contract"
                )
            if not job["enabled"]:
                raise ArchiveJobNotReadyError("archive job is not enabled")
            if not str(job["credential_ref"] or "").strip():
                raise ArchiveJobNotReadyError(
                    "archive job credential reference is not configured"
                )
            filters = _json_loads_or_none(job["filters_json"])
            retry_policy = _json_loads_or_none(job["retry_policy_json"])
            if not isinstance(filters, dict):
                raise ArchiveJobNotReadyError("archive job filters are invalid")
            try:
                retry_policy = _normalize_archive_retry_policy(retry_policy)
            except (TypeError, ValueError):
                raise ArchiveJobNotReadyError("archive job retry policy is invalid")

            now = self._utc_now(conn)
            lease_token = secrets.token_urlsafe(32)
            cursor = conn.execute(
                f"""
                UPDATE scheduled_archive_jobs
                SET lease_token = ?, lease_acquired_at = ?,
                    lease_expires_at = {_utc_offset_sql(lease_seconds)},
                    sync_state = 'running', last_attempt_at = ?,
                    updated_at = {_UTC_NOW_SQL}
                WHERE id = ? AND (
                    lease_token IS NULL OR lease_expires_at IS NULL
                    OR lease_expires_at <= ?
                )
                """,
                (lease_token, now, now, job_id, now),
            )
            if cursor.rowcount != 1:
                raise ArchiveLeaseBusyError(
                    "archive job already has an unexpired lease"
                )
            conn.execute(
                """
                UPDATE scheduled_archive_runs
                SET run_state = 'expired', finished_at = ?
                WHERE job_id = ? AND run_state IN ('leased', 'running')
                """,
                (now, job_id),
            )
            run_id = conn.execute(
                """
                INSERT INTO scheduled_archive_runs
                    (job_id, job_key, trigger_type, run_state, attempt, created_at)
                VALUES (?, ?, ?, 'leased', 1, ?)
                """,
                (job_id, job["job_key"], trigger_type, now),
            ).lastrowid
            expires = conn.execute(
                "SELECT lease_expires_at FROM scheduled_archive_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            return {
                "job_id": job_id,
                "job_key": template_key,
                "task_key": str(job["job_key"]),
                "source_type": str(job["source_type"]),
                "report_type": contract[1],
                "project_status_deliverable_id": job[
                    "project_status_deliverable_id"
                ],
                "filters": filters,
                "output_subdir": str(job["output_subdir"] or ""),
                "output_directory": str(job["output_directory"] or ""),
                "retry_policy": retry_policy,
                "run_id": int(run_id),
                "lease_token": lease_token,
                "lease_expires_at": expires["lease_expires_at"],
                "acquired_at": now,
            }

    def start_archive_run(
        self, job_id: int, run_id: int, lease_token: str
    ) -> None:
        """Move a lease-owned archive run from leased to running."""
        with self.get_connection() as conn:
            self._assert_archive_lease_holder(
                conn, job_id, run_id, lease_token
            )
            now = self._utc_now(conn)
            cursor = conn.execute(
                """
                UPDATE scheduled_archive_runs
                SET run_state = 'running', started_at = ?
                WHERE id = ? AND job_id = ? AND run_state = 'leased'
                """,
                (now, run_id, job_id),
            )
            if cursor.rowcount != 1:
                raise ArchiveLeaseLostError("archive run is not leased")

    def renew_archive_job_lease(
        self,
        job_id: int,
        run_id: int,
        lease_token: str,
        lease_seconds: int = SYNC_LEASE_DEFAULT_SECONDS,
    ) -> str:
        """Atomically extend an active archive lease owned by one run."""
        self._validate_lease_duration(lease_seconds)
        if (
            not isinstance(job_id, int)
            or isinstance(job_id, bool)
            or not isinstance(run_id, int)
            or isinstance(run_id, bool)
            or not isinstance(lease_token, str)
            or not lease_token
        ):
            raise ValueError("archive lease identity is invalid")
        with self.get_connection() as conn:
            cursor = conn.execute(
                f"""
                UPDATE scheduled_archive_jobs
                SET lease_expires_at = {_utc_offset_sql(lease_seconds)},
                    updated_at = {_UTC_NOW_SQL}
                WHERE id = ?
                  AND lease_token = ?
                  AND lease_expires_at > {_UTC_NOW_SQL}
                  AND EXISTS (
                      SELECT 1
                      FROM scheduled_archive_runs r
                      WHERE r.id = ? AND r.job_id = scheduled_archive_jobs.id
                        AND r.run_state IN ('leased', 'running')
                  )
                """,
                (job_id, lease_token, run_id),
            )
            if cursor.rowcount != 1:
                raise ArchiveLeaseLostError("archive lease expired or token/run mismatch")
            row = conn.execute(
                "SELECT lease_expires_at FROM scheduled_archive_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None or not row["lease_expires_at"]:
                raise ArchiveLeaseLostError("archive lease renewal did not persist")
            return str(row["lease_expires_at"])

    def finalize_archive_run(
        self,
        job_id: int,
        run_id: int,
        lease_token: str,
        final_state: str,
        *,
        record_count: int | None = None,
        artifacts: Sequence[dict[str, Any]] = (),
        result_summary: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Validate metadata and atomically finalize a lease-owned archive run."""
        allowed = {"success", "partial", "failed", "needs_attention"}
        if final_state not in allowed:
            raise ValueError("invalid archive final state")
        if record_count is not None and (
            not isinstance(record_count, int)
            or isinstance(record_count, bool)
            or record_count < 0
        ):
            raise ValueError("record_count must be a non-negative int or None")
        for artifact in artifacts:
            self._validate_artifact_metadata(artifact)
        if final_state == "success" and not artifacts:
            raise ValueError("successful archive run requires artifacts")

        summary = (
            redact_sensitive_text(result_summary, limit=1000)
            if result_summary
            else None
        )
        safe_error_type = (
            redact_sensitive_text(error_type, limit=200)
            if error_type
            else None
        )
        safe_error = (
            redact_sensitive_text(error_message, limit=1000)
            if error_message
            else None
        )
        with self.get_connection() as conn:
            self._assert_archive_lease_holder(
                conn, job_id, run_id, lease_token
            )
            now = self._utc_now(conn)
            for artifact in artifacts:
                conn.execute(
                    """
                    INSERT INTO scheduled_archive_artifacts
                        (run_id, artifact_type, relative_path, display_name,
                         size_bytes, sha256, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        artifact["artifact_type"],
                        artifact["relative_path"],
                        artifact["display_name"],
                        artifact.get("size_bytes"),
                        artifact.get("sha256"),
                        now,
                    ),
                )
            cursor = conn.execute(
                """
                UPDATE scheduled_archive_runs
                SET run_state = ?, record_count = ?, result_summary = ?,
                    error_type = ?, error_message = ?, finished_at = ?
                WHERE id = ? AND job_id = ?
                  AND run_state IN ('leased', 'running')
                """,
                (
                    final_state, record_count, summary, safe_error_type,
                    safe_error, now, run_id, job_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ArchiveLeaseLostError("archive run is no longer active")
            last_success = ", last_success_at = ?" if final_state == "success" else ""
            job_state = (
                "needs_attention" if final_state == "partial" else final_state
            )
            params: list[Any] = [
                job_state, safe_error_type, safe_error, now,
            ]
            if final_state == "success":
                params.append(now)
            params.extend([job_id, lease_token])
            cursor = conn.execute(
                f"""
                UPDATE scheduled_archive_jobs
                SET sync_state = ?, last_error_type = ?,
                    last_error_message = ?, updated_at = ?,
                    lease_token = NULL, lease_acquired_at = NULL,
                    lease_expires_at = NULL{last_success}
                WHERE id = ? AND lease_token = ?
                """,
                params,
            )
            if cursor.rowcount != 1:
                raise ArchiveLeaseLostError("archive job lease was lost")

    @staticmethod
    def _assert_archive_lease_holder(
        conn: sqlite3.Connection,
        job_id: int,
        run_id: int,
        lease_token: str,
    ) -> None:
        row = conn.execute(
            f"""
            SELECT 1
            FROM scheduled_archive_jobs j
            INNER JOIN scheduled_archive_runs r
                ON r.job_id = j.id AND r.id = ?
            WHERE j.id = ? AND j.lease_token = ?
              AND j.lease_expires_at > {_UTC_NOW_SQL}
              AND r.run_state IN ('leased', 'running')
            """,
            (run_id, job_id, lease_token),
        ).fetchone()
        if row is None:
            raise ArchiveLeaseLostError(
                "archive lease expired or token/run mismatch"
            )

    def list_archive_runs(
        self, job_key: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return sanitized archive run history without lease or credential data."""
        bounded = max(1, min(int(limit), 500))
        sql = """
            SELECT id, job_id, job_key, trigger_type, run_state, attempt,
                   record_count, result_summary, error_type, error_message,
                   created_at, started_at, finished_at
            FROM scheduled_archive_runs
        """
        params: tuple[Any, ...]
        if job_key:
            sql += " WHERE job_key = ? ORDER BY id DESC LIMIT ?"
            params = (job_key, bounded)
        else:
            sql += " ORDER BY id DESC LIMIT ?"
            params = (bounded,)
        with self.get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_archive_run(self, run_id: int) -> dict[str, Any] | None:
        """Return one sanitized archive run, or None when it does not exist."""
        if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1:
            return None
        with self.get_connection() as conn:
            row = conn.execute(
                """
                SELECT id, job_id, job_key, trigger_type, run_state, attempt,
                       record_count, result_summary, error_type, error_message,
                       created_at, started_at, finished_at
                FROM scheduled_archive_runs WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_archive_artifacts(self, run_id: int) -> list[dict[str, Any]]:
        """Return artifact metadata; never resolve or expose a server absolute path."""
        with self.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, run_id, artifact_type, relative_path, display_name,
                       size_bytes, sha256, created_at
                FROM scheduled_archive_artifacts
                WHERE run_id = ? ORDER BY id
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

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
