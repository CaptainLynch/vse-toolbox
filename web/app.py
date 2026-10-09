# -*- coding: utf-8 -*-
"""
web/app.py — WEB 适配层：Flask 应用工厂 + /api/overview 路由

架构约束:
    - 唯一允许 import flask 的文件
    - 路由只做序列化与 HTTP 响应，不写业务 SQL
    - FLASK_HOST / FLASK_PORT 从 core.config 取值
    - service/core 层对 Flask 无感知
"""

import io
import hashlib
import json
import ipaddress
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from dataclasses import asdict, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, cast
from urllib.parse import urlsplit

from flask import Flask, current_app, has_app_context, jsonify, render_template, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.config import DIAGNOSTIC_DIR, FLASK_HOST, FLASK_PORT
from core.archive_store import ArchiveSafetyError, ArchiveStore
from core.credential_provider import (
    CredentialProviderError,
    delete_windows_generic_credential,
    store_windows_generic_credential,
)
from core.domain_identity import (
    CredentialVaultError,
    DPAPICredentialProvider,
    DomainSessionRegistry,
    WindowsDPAPICredentialVault,
)

#: 交付物同步凭据在 Windows 凭据管理器中的引用名（与统一域账号登录共享）。
SYNC_CREDENTIAL_REF = "domain"
from core.native_folder_picker import NativeFolderPickerError, choose_native_folder
from core.project_status_contracts import (
    DELIVERABLE_LINK_REGISTRY,
    MILESTONE_STATUSES,
    PROJECT_STATUS_SOURCE_CAPABILITIES,
    current_stage_label,
    deliverable_display_state,
    find_job_key_by_deliverable_id,
    find_registry_entry_by_deliverable_id,
    milestone_display_status,
    project_status_board_visible,
    project_status_manual_editability,
)
from core.report_contracts import matrix_payload, report_contracts, table_payload
from core.diagnostic_recording import emit
from core.runtime_paths import app_root
from core.settings_store import SettingsStore, SettingsValidationError, validate_local_directory
from core.section_rollup import (
    SectionRollupError,
    SectionRollupStore,
    build_rollup_index,
    rollup_targets_in_order,
)
from core.db_manager import (
    ArchiveJobNotReadyError,
    ArchiveLeaseBusyError,
    DatabaseManager,
    MappedDeliverableReadOnlyError,
    PROJECT_STATUS_MILESTONE_TEMPLATE,
    SyncBindingNotReadyError,
)
from core.diagnostics import DiagnosticOptions, MarkdownDiagnosticReport
from core.debug_bundle import build_debug_bundle, export_debug_bundle
from core.unified_status import (
    AuthState,
    QueryState,
    SyncState,
    UnifiedObjectStatus,
)
from core.version import get_app_version_info
from core.excel_tasks import (
    ApprovedExcelRoots,
    ExcelIdempotencyConflictError,
    ExcelTaskRepository,
    load_production_excel_roots,
)
from core.excel_worker import ExcelTaskWorker
from services.project_status_updates import (
    ProjectStatusPolicyError,
    ProjectStatusUpdateService,
)
from services.form_search import MAX_TERMS as MAX_DOCUMENT_NOS
from services.form_search import parse_terms as parse_form_terms
from services.form_search import _SEPARATORS as _FORM_TERM_SEPARATORS
from services.project_status_discovery import MappingDiscoveryService
from services.project_status_records import (
    COMPLETE_RESULT_STOP_REASONS,
    MAX_AGGREGATE_RECORDS,
)
from services.project_status_analytics import ProjectStatusAnalyticsService
from services.project_status_deliverable_analysis import (
    EWO_DEFAULT_RSP_DEPARTMENT_EXPRESSION,
    ProjectStatusDeliverableAnalysisService,
)
from services.deliverable_form_analysis import (
    SECTION_ROLLUP_FORM_KEYS,
    DeliverableFormAnalysisService,
)
from services.deliverable_statistics import (
    STATISTICS_HISTORY_SNAPSHOT_LIMIT,
    compute_form_statistics,
    statistics_history_entry,
)
from services.project_status_sync_runner import (
    ProjectStatusSyncRunner,
    create_production_registry,
)
from services.project_status_connectors import build_project_status_ewo_filters
from services.data_model_watchlist import match_serial, match_serials
from services.scheduled_archive_admin import (
    ArchiveAdminValidationError,
    ScheduledArchiveAdminService,
)
from services.aras_xml import ArasXmlCaptureError, sanitize_aras_xml
from services.xlsx_preview import XLSXPreviewError, read_xlsx_preview
from services.excel_task_admin import (
    ExcelArtifactUnavailableError,
    ExcelTaskAdminService,
    ExcelTaskAdminValidationError,
)
from services.excel_worker_controller import ExcelWorkerController
from services.excel_worker_process_controller import ExcelWorkerProcessController
from core.redaction import redact_sensitive_text
from services.aras_crawler import (
    ArasAuthenticationError,
    ArasCrawlerClient,
    ArasCrawlerError,
    ArasNcrExportContractError,
    EWOReportFilters,
    NCRApprovalFilters,
    PAAReportFilters,
)
from services.aras_auth import ArasAuthError, ArasECMAuthClient, DEFAULT_ARAS_BASE_URL
from services.aras_department_mapping import (
    NCR_SECTION_CODES,
    normalize_departments,
    parse_ncr_section_codes_input,
    resolve_ncr_section_codes,
)
from services.aras_export import export_report_contract_csv
from services.tdc_auth import TDCAuthError, TDCPasswordAuthClient
from services.tdc_crawler import (
    AFACE_CONTRACT_BLOCKER,
    CrawlCancelled,
    TDCCrawlerClient,
    TDCCrawlerError,
    TDCDataModelFilters,
    TDCSORFilters,
    flatten_sor_rows,
    flatten_sor_value,
)
from services.tdc_export_cache import TDCExportCache
from services.windows_http import WinHTTPError, WinHTTPTimeoutError

logger = logging.getLogger("vse_toolbox.web")

# 映射取证的取消登记：前端 abort 之后服务端必须真的停下来，否则"可取消"只是表面
# 文章（顾问 2026-09-28 提醒），而且重复点击会叠加多个后台全量抓取。
# TDC 的分页抓取支持协作式停止（should_stop 在每个分页边界被探测）；
# Aras 的整本工作簿导出是**单次** SOAP 调用，没有取消钩子，登记对它只是尽力而为。
_DISCOVERY_CANCEL_TOKENS: dict[str, threading.Event] = {}
_DISCOVERY_CANCEL_LOCK = threading.Lock()
_DISCOVERY_CANCEL_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_DISCOVERY_CANCEL_MAX_TOKENS = 64


def _register_discovery_cancel(token: Any) -> tuple[str | None, threading.Event | None]:
    """登记本次取证的取消令牌；非法/缺省令牌返回 (None, None)（不取消，行为不变）。"""
    if not isinstance(token, str) or not _DISCOVERY_CANCEL_TOKEN_RE.match(token):
        return None, None
    event = threading.Event()
    with _DISCOVERY_CANCEL_LOCK:
        _DISCOVERY_CANCEL_TOKENS[token] = event
        while len(_DISCOVERY_CANCEL_TOKENS) > _DISCOVERY_CANCEL_MAX_TOKENS:
            _DISCOVERY_CANCEL_TOKENS.pop(next(iter(_DISCOVERY_CANCEL_TOKENS)))
    return token, event


def _release_discovery_cancel(token: str | None, event: threading.Event | None) -> None:
    if token is None or event is None:
        return
    with _DISCOVERY_CANCEL_LOCK:
        if _DISCOVERY_CANCEL_TOKENS.get(token) is event:
            _DISCOVERY_CANCEL_TOKENS.pop(token, None)


# F9a: 向导会话内映射取证去重与复用。
# 作用域限定在单一向导会话（wizardSessionId）与相同的上游查询参数组合，TTL 180s，最多 32 个。
# 仅用于向导内部候选重选、指定部门重试等中间交互，sync-now 绝不复用此缓存。
# 缓存连带保存首次抓取时的上游声明总数：候选重选等缓存命中路径再次落观测时，
# 必须沿用同源声明总数（F10 稳定性基线），不能用去重后行数充当——否则上游存在
# 重复行时，采样端的声明总数会与基线假性失配。
_DISCOVERY_SESSION_CACHE: dict[str, tuple[float, list[dict[str, Any]], int | None]] = {}
_DISCOVERY_SESSION_LOCK = threading.Lock()
_DISCOVERY_SESSION_TTL_SECONDS = 180.0
_DISCOVERY_SESSION_MAX_ENTRIES = 32
_WIZARD_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# G5（2026-09-30）映射取证后台化：同一交付物同一时刻只允许一个在途取证任务。
# 重复提交（相同参数哈希）返回原任务（向导重开后经 statusUrl 重新挂接）；
# 参数不同的在途任务期间再提交返回 409，避免新旧取证结果互相污染
# （与 C1 的「过期请求」问题同构，绑定的是查询身份而非请求时序）。
_MAPPING_DISCOVERY_TASKS: dict[str, dict[str, Any]] = {}
_MAPPING_DISCOVERY_TASKS_LOCK = threading.Lock()
_MAPPING_DISCOVERY_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "interrupted"}


def _mapping_discovery_params_hash(
    match_rule: Mapping[str, Any], values: Mapping[str, Any], selected: str | None
) -> str:
    """把取证的查询身份（匹配规则+过滤值+选中候选）压成 16 位哈希。

    该哈希随 202 响应下发并写入任务结果：前端应用结果前先比对，向导参数
    变化后旧任务结果不得应用（G5 参数哈希绑定）。
    """
    identity = {"match_rule": match_rule, "values": values, "selected": selected}
    canonical = json.dumps(identity, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _mapping_discovery_accepted_response(task_id: str, status: str, params_hash: str):
    """映射取证后台任务的 202 Accepted 契约响应（与 _submit_background_task 同形 + paramsHash）。"""
    response = jsonify(
        {
            "ok": True,
            "data": {
                "taskId": task_id,
                "status": status,
                "category": "crawl",
                "statusUrl": f"/api/tasks/{task_id}",
                "resultUrl": f"/api/tasks/{task_id}/result",
                "paramsHash": params_hash,
            },
        }
    )
    response.status_code = 202
    response.headers["Cache-Control"] = "no-store"
    return response


def _get_discovery_session_cache(key: str) -> list[dict[str, Any]] | None:
    now = time.monotonic()
    with _DISCOVERY_SESSION_LOCK:
        entry = _DISCOVERY_SESSION_CACHE.get(key)
        if entry is None:
            return None
        created_at, rows, _upstream_total = entry
        if now - created_at > _DISCOVERY_SESSION_TTL_SECONDS:
            _DISCOVERY_SESSION_CACHE.pop(key, None)
            return None
        return list(rows)


def _get_discovery_session_cache_total(key: str) -> int | None:
    with _DISCOVERY_SESSION_LOCK:
        entry = _DISCOVERY_SESSION_CACHE.get(key)
        if entry is None:
            return None
        total = entry[2]
    if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
        return total
    return None


def _set_discovery_session_cache(
    key: str,
    rows: Sequence[Mapping[str, Any]],
    upstream_total: int | None = None,
) -> None:
    now = time.monotonic()
    with _DISCOVERY_SESSION_LOCK:
        expired = [
            k for k, (t, _r, _n) in _DISCOVERY_SESSION_CACHE.items()
            if now - t > _DISCOVERY_SESSION_TTL_SECONDS
        ]
        for k in expired:
            _DISCOVERY_SESSION_CACHE.pop(k, None)
        while len(_DISCOVERY_SESSION_CACHE) >= _DISCOVERY_SESSION_MAX_ENTRIES:
            _DISCOVERY_SESSION_CACHE.pop(next(iter(_DISCOVERY_SESSION_CACHE)), None)
        _DISCOVERY_SESSION_CACHE[key] = (now, [dict(r) for r in rows], upstream_total)


_SENSITIVE_JSON_RE = re.compile(
    r"(?i)(['\"])(authorization|cookie|token|api_key|sid|sessionid|csrf|secret)\1(\s*:\s*)(['\"])(.*?)\4"
)
_SENSITIVE_PARAM_RE = re.compile(r"(?i)\b(token|api_key|sid|sessionid|csrf|secret)=([^&\s,;'\"}\])]+)")
_SENSITIVE_HEADER_RE = re.compile(
    r"(?i)\b(cookie|authorization)\b(\s*[:=]?\s*)(?:Bearer\s+)?([^,\s;'\"}\])]+)"
)
_SENSITIVE_BEARER_RE = re.compile(r"(?i)\bBearer\s+([^,\s;'\"}\])]+)")

_SENSITIVE_RESPONSE_KEYS = {
    "raw_xml",
    "file_id",
    "authorization",
    "set-cookie",
    "cookie",
    "token",
    "api_key",
    "sid",
    "sessionid",
    "arasauth",
    "jsessionid",
    "csrf",
    "secret",
    "password",
}

#: Aras routes 的默认主机 allowlist；仅允许 ecm.sgmw.com.cn。
#: localhost/测试 host 只能通过 create_app(allowed_hosts=...) 或
#: app.config["ARAS_ALLOWED_HOSTS"] 显式注入。
_DEFAULT_ARAS_ALLOWED_HOSTS: tuple[str, ...] = ("ecm.sgmw.com.cn",)

#: TDC routes 的默认主机 allowlist；仅允许 tdc.sgmw.com.cn。
#: 测试 host 只能通过 create_app(tdc_allowed_hosts=...) 或
#: app.config["TDC_ALLOWED_HOSTS"] 显式注入。
_DEFAULT_TDC_ALLOWED_HOSTS: tuple[str, ...] = ("tdc.sgmw.com.cn",)

#: 全量 CSV 导出路由固定使用的边界（page_size 固定 2000，不可被请求覆盖）。
_EXPORT_PAGE_SIZE = 2000
_EXPORT_DEFAULT_MAX_PAGES = 1000
_EXPORT_DEFAULT_MAX_RECORDS = 10000

_INVALID_ATTACHMENT_CHARS_RE = re.compile(r'[\x00-\x1f<>:"/\\|?*]')

_TDC_PAGE_MAX = 1_000_000
_TDC_PAGE_SIZE_MAX = 1000
_TDC_MAX_PAGES_MAX = 10000
_TDC_MAX_RECORDS_MAX = 1_000_000
_TDC_XLSX_MIMETYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_TDC_XLSX_NAME_RE = re.compile(r"^[^<>:\"/\\|?*\x00-\x1f]+\.xlsx$", re.IGNORECASE)
_TDC_OFFICIAL_PREVIEW_MAX_ROWS = 50_001

_DELIVERABLE_CATEGORIES = [
    {"id": "aras", "name": "Aras 报告"},
    {"id": "tdc", "name": "TDC 报表"},
]

_TDC_DATA_MODEL_FIELDS = [
    # serial_number 的 API 键名语义是第 0 列实例号（incident，纯数字）；流水单号
    # （documentNo，3D- 前缀）不是 TDC 查询参数，走顶层 document_no 全量抓取 + 本地匹配。
    {"name": "serial_number", "label": "实例号(incident)", "type": "text"},
    # 目录/交付物工作台可见的输入字段；不在 _TDC_DATA_MODEL_FILTER_NAMES 里
    # （服务端从请求体顶层读取，进 filters 会被 400 拒绝——fail-open 防护）。
    {"name": "document_no", "label": "流水单号", "type": "text"},
    {"name": "applicant", "label": "申请人", "type": "text"},
    {"name": "department", "label": "部门", "type": "text"},
    {"name": "section", "label": "科室", "type": "text"},
    {"name": "application_start", "label": "申请开始", "type": "date"},
    {"name": "application_end", "label": "申请结束", "type": "date"},
    {"name": "project_model", "label": "项目车型", "type": "text"},
    {"name": "part_number", "label": "零件号", "type": "text"},
    {"name": "model_number", "label": "模型编号", "type": "text"},
    {"name": "status", "label": "状态", "type": "text"},
]

_TDC_SOR_FIELDS = [
    {"name": "serial_number", "label": "流水号", "type": "text"},
    {"name": "process_type", "label": "流程类型", "type": "text"},
    {"name": "car_type_project", "label": "车型项目", "type": "text"},
    {"name": "applicant", "label": "申请人", "type": "text"},
    {"name": "title", "label": "标题", "type": "text"},
    {"name": "department", "label": "部门", "type": "text"},
    {"name": "section", "label": "科室", "type": "text"},
    {"name": "application_start", "label": "申请开始", "type": "date"},
    {"name": "application_end", "label": "申请结束", "type": "date"},
    {"name": "part_number", "label": "零件号", "type": "text"},
    {"name": "part_name", "label": "零件名称", "type": "text"},
    {"name": "version", "label": "版本", "type": "text"},
    {"name": "sor_number", "label": "SOR 编号", "type": "text"},
    {"name": "latest_completed_node", "label": "最近完成节点", "type": "text"},
    {"name": "approval_status", "label": "审批状态", "type": "text"},
]

_DELIVERABLES_CATALOG = [
    {
        "id": "aras-ewo",
        "name": "EWO 工程变更报告",
        "category": "aras",
        "source": "services/aras_crawler.py",
        "availability": "available",
        "implementation_status": "已完整实现",
        "description": "在 Aras 工作区执行 EWO 报告查询、全量抓取与 CSV 导出。",
        "output_formats": ["JSON", "CSV"],
        "operations": ["query", "crawl_all", "export"],
        "fields": [],
        "target": {"panel": "aras-panel", "mode": "ewo"},
    },
    {
        "id": "aras-paa",
        "name": "PAA流程",
        "category": "aras",
        "source": "services/aras_crawler.py",
        "availability": "available",
        "implementation_status": "已完整实现",
        "description": "在 Aras 工作区执行 PAA流程分页查询、全量抓取与 CSV 导出。",
        "output_formats": ["JSON", "CSV"],
        "operations": ["query", "crawl_all", "export"],
        "fields": [],
        "target": {"panel": "aras-panel", "mode": "paa"},
    },
    {
        "id": "aras-ncr-progress",
        "name": "NCR 审批进度",
        "category": "aras",
        "source": "services/aras_crawler.py",
        "availability": "available",
        "implementation_status": "已完整实现",
        "description": "在 Aras 工作区执行 NCR 审批进度查询。",
        "output_formats": ["JSON"],
        "operations": ["query"],
        "fields": [],
        "target": {"panel": "aras-panel", "mode": "ncr-progress"},
    },
    {
        "id": "aras-ncr-detail",
        "name": "NCR 审批明细",
        "category": "aras",
        "source": "services/aras_crawler.py",
        "availability": "available",
        "implementation_status": "已完整实现",
        "description": "在 Aras 工作区生成并下载 NCR 审批明细文件。",
        "output_formats": ["XLSX"],
        "operations": ["query", "download"],
        "fields": [],
        "target": {"panel": "aras-panel", "mode": "ncr-detail"},
    },
    {
        "id": "tdc-data-model",
        "name": "TDC 数模设计审核流程报表",
        "category": "tdc",
        "source": "services/tdc_crawler.py",
        "availability": "available",
        "implementation_status": "已完整实现",
        "description": "TDC 数模设计审核流程报表的查询、全量抓取与官方 XLSX 导出。",
        "output_formats": ["JSON", "XLSX"],
        "operations": ["query", "crawl_all", "export"],
        "fields": _TDC_DATA_MODEL_FIELDS,
    },
    {
        "id": "tdc-sor",
        "name": "TDC SOR 流程报表",
        "category": "tdc",
        "source": "services/tdc_crawler.py",
        "availability": "available",
        "implementation_status": "已完整实现",
        "description": "TDC SOR 流程报表的查询、全量抓取与官方 XLSX 导出。",
        "output_formats": ["JSON", "XLSX"],
        "operations": ["query", "crawl_all", "export"],
        "fields": _TDC_SOR_FIELDS,
    },
]


class _ArasRequestError(ValueError):
    """Aras 请求级校验失败（主机 allowlist / filter 语义），映射为 HTTP 400。"""

    def __init__(
        self,
        message: str,
        error_type: str = "ValidationError",
        status_code: int = 400,
        diagnostic_path: Path | None = None,
        diagnostic: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.status_code = status_code
        self.diagnostic_path = diagnostic_path
        self.diagnostic = dict(diagnostic) if diagnostic is not None else None


class _TDCRequestError(ValueError):
    """TDC 请求级校验失败（主机 allowlist / 凭据 / 参数边界），映射为 HTTP 错误。"""

    def __init__(
        self,
        message: str,
        error_type: str = "ValidationError",
        status_code: int = 400,
        diagnostic_path: Path | None = None,
        diagnostic: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.status_code = status_code
        self.diagnostic_path = diagnostic_path
        self.diagnostic = dict(diagnostic) if diagnostic is not None else None


def _query_overview(db: DatabaseManager) -> dict[str, Any]:
    """从 DatabaseManager 查询概览数据，返回 dict（供 jsonify 使用）。"""
    with db.get_connection() as conn:
        project_rows = conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM projects GROUP BY status"
        ).fetchall()
        deliverable_rows = conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM deliverables GROUP BY status"
        ).fetchall()
        feishu_total = conn.execute("SELECT COUNT(*) FROM feishu_tasks").fetchone()[0]
        feishu_synced = conn.execute(
            "SELECT COUNT(*) FROM feishu_tasks WHERE synced=1"
        ).fetchone()[0]

    return {
        "projects": {row["status"]: row["cnt"] for row in project_rows},
        "deliverables": {row["status"]: row["cnt"] for row in deliverable_rows},
        "feishu": {"total": feishu_total, "synced": feishu_synced},
    }


def _sanitize_error_message(exc: Exception) -> str:
    return redact_sensitive_text(exc, limit=240, collapse_newlines=True)


def _json_error(
    status: int,
    error_type: str,
    message: str,
    diagnostic_path: Path | None = None,
    *,
    code: str | None = None,
    diagnostic: Mapping[str, Any] | None = None,
):
    """统一错误出口。

    `diagnostic` 只承载有界、非敏感的元数据（枚举值与计数），是完整性/抓取
    类失败可自诊断的唯一通道；禁止放入上游原文、凭据或业务行内容。
    """
    error: dict[str, Any] = {"type": error_type, "message": message}
    if code is not None:
        error["code"] = code
    if diagnostic_path is not None:
        error["diagnosticPath"] = str(diagnostic_path)
    if diagnostic is not None:
        error["diagnostic"] = dict(diagnostic)
    response = jsonify({"ok": False, "error": error})
    response.headers["Cache-Control"] = "no-store"
    return response, status


def _loopback_hostname(value: str | None) -> bool:
    if not value:
        return False
    hostname = value.strip().rstrip(".").lower()
    if hostname == "localhost":
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped.is_loopback
    return address.is_loopback


def _origin_tuple(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
        invalid = any((
            parsed.scheme not in {"http", "https"},
            not parsed.hostname,
            parsed.username is not None,
            parsed.password is not None,
            parsed.path not in {"", "/"},
            bool(parsed.query),
            bool(parsed.fragment),
        ))
        if invalid:
            return None
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None
    hostname = parsed.hostname
    if hostname is None:
        return None
    return parsed.scheme.lower(), hostname.rstrip(".").lower(), port


def _local_web_mutation_error():
    """Reject cross-host/cross-site writes in the local-only WebUI."""
    if not _loopback_hostname(request.remote_addr):
        return _json_error(403, "LocalAccessRequired", "此操作仅允许从本机访问")
    try:
        host_url = urlsplit(f"//{request.host}")
        host_name = host_url.hostname
        host_port = host_url.port or (443 if request.scheme == "https" else 80)
    except ValueError:
        return _json_error(403, "LocalAccessRequired", "请求主机不受信任")
    if not _loopback_hostname(host_name):
        return _json_error(403, "LocalAccessRequired", "请求主机不受信任")
    if request.headers.get("Sec-Fetch-Site", "").strip().lower() == "cross-site":
        return _json_error(403, "CrossSiteRequest", "拒绝跨站写操作")
    origin = request.headers.get("Origin")
    if origin is not None:
        expected = (
            request.scheme.lower(),
            str(host_name).rstrip(".").lower(),
            host_port,
        )
        if _origin_tuple(origin.strip()) != expected:
            return _json_error(403, "CrossSiteRequest", "请求来源与本机服务不一致")
    return None


def _enforce_local_web_access():
    """Reject non-local or cross-site requests to prevent DNS rebinding and cross-site attacks."""
    if not _loopback_hostname(request.remote_addr):
        return _json_error(403, "LocalAccessRequired", "此操作仅允许从本机访问")
    try:
        host_url = urlsplit(f"//{request.host}")
        host_name = host_url.hostname
        host_port = host_url.port or (443 if request.scheme == "https" else 80)
    except ValueError:
        return _json_error(403, "LocalAccessRequired", "请求主机不受信任")
    if not _loopback_hostname(host_name):
        return _json_error(403, "LocalAccessRequired", "请求主机不受信任")

    sec_fetch_site = request.headers.get("Sec-Fetch-Site", "").strip().lower()
    if sec_fetch_site == "cross-site":
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            return _json_error(403, "CrossSiteRequest", "拒绝跨站写操作")
        if request.path.startswith("/api/"):
            return _json_error(403, "CrossSiteRequest", "拒绝跨站请求")

    origin = request.headers.get("Origin")
    if origin is not None:
        expected = (
            request.scheme.lower(),
            str(host_name).rstrip(".").lower(),
            host_port,
        )
        if _origin_tuple(origin.strip()) != expected:
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                return _json_error(403, "CrossSiteRequest", "请求来源与本机服务不一致")
            if request.path.startswith("/api/"):
                return _json_error(403, "CrossSiteRequest", "请求来源与本机服务不一致")
    return None


def _save_web_diagnostic_report(
    report: MarkdownDiagnosticReport | None,
    exc: Exception,
) -> Path | None:
    if report is None:
        return None
    try:
        report.record_exception(exc)
        return report.save("failed")
    except Exception as diagnostic_exc:
        logger.warning("Web diagnostic save failed: %s", type(diagnostic_exc).__name__)
        return None


def _save_aras_client_diagnostic(client: ArasCrawlerClient | None, exc: Exception) -> Path | None:
    report = getattr(client, "_web_diagnostic_report", None) if client is not None else None
    return _save_web_diagnostic_report(report, exc)


def _safe_rows(rows: list[dict[str, Any]]) -> list[dict[str, str | None]]:
    safe: list[dict[str, str | None]] = []
    for row in rows:
        clean: dict[str, str | None] = {}
        for key, value in row.items():
            key_text = str(key)
            if key_text.lower() in _SENSITIVE_RESPONSE_KEYS:
                continue
            clean[key_text] = None if value is None else redact_sensitive_text(value)
        safe.append(clean)
    return safe


def _safe_tdc_sor_rows(rows: list[dict[str, Any]]) -> list[dict[str, str | None]]:
    """SOR 行扁平化（共享实现见 services.tdc_crawler.flatten_sor_rows）。"""
    return flatten_sor_rows(rows)


#: 单值扁平化别名（项目选项等展示场景沿用既有调用点）。
_safe_tdc_sor_value = flatten_sor_value


def _safe_scalar(value: Any) -> str:
    return redact_sensitive_text(value)


def _aras_xml_requested(payload: Mapping[str, Any]) -> bool:
    value = payload.get("include_xml")
    return value is True or (
        isinstance(value, str) and value.strip().lower() in {"1", "true", "yes"}
    )


def _aras_xml_payload(result: Any, payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return bounded request/response XML only when explicitly requested."""
    if not _aras_xml_requested(payload):
        return None
    request_xml = sanitize_aras_xml(getattr(result, "request_xml", ""))
    response_xml = sanitize_aras_xml(getattr(result, "raw_xml", ""))
    if not request_xml or not response_xml:
        raise ArasXmlCaptureError("Aras XML capture is unavailable for this result")
    return {
        "requestXml": request_xml,
        "responseXml": response_xml,
        "requestBytes": len(request_xml.encode("utf-8")),
        "responseBytes": len(response_xml.encode("utf-8")),
    }


def _request_payload() -> tuple[dict[str, Any] | None, Any]:
    local_error = _local_web_mutation_error()
    if local_error is not None:
        return None, local_error
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, _json_error(400, "ValidationError", "JSON object body is required")
    base_url = payload.get("base_url")
    if not isinstance(base_url, str) or not base_url.strip():
        return None, _json_error(400, "ValidationError", "base_url must be a non-empty string")
    return payload, None


def _clean_string_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    clean: dict[str, str] = {}
    for key, item in value.items():
        if isinstance(key, str) and isinstance(item, str) and key.strip() and item.strip():
            clean[key.strip()] = item.strip()
    return clean


def _normalize_allowed_host(entry: str) -> tuple[str, int | None]:
    """规范化 allowlist 条目 'host' / 'host:port'（小写；无端口表示任意端口）。"""
    text = str(entry).strip().lower()
    if not text:
        raise _ArasRequestError("ARAS_ALLOWED_HOSTS contains an empty host", "HostNotAllowed")
    try:
        parsed = urlsplit("//" + text)
        port = parsed.port
    except ValueError:
        raise _ArasRequestError("ARAS_ALLOWED_HOSTS contains an invalid host", "HostNotAllowed") from None
    hostname = parsed.hostname or ""
    if not hostname:
        raise _ArasRequestError("ARAS_ALLOWED_HOSTS contains an invalid host", "HostNotAllowed")
    return hostname, port


def _validate_allowed_base_url(base_url: str, allowed_hosts: Sequence[str]) -> None:
    """构造 Aras client 前执行主机 allowlist（fail-closed，拒绝任意主机）。"""
    try:
        parsed = urlsplit(str(base_url or "").strip())
        port = parsed.port
    except ValueError:
        raise _ArasRequestError("base_url is not a valid URL", "HostNotAllowed") from None
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise _ArasRequestError("base_url must use http or https", "HostNotAllowed")
    if parsed.username is not None or parsed.password is not None:
        raise _ArasRequestError("base_url must not contain userinfo", "HostNotAllowed")
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise _ArasRequestError("base_url must include a host", "HostNotAllowed")
    default_port = 443 if scheme == "https" else 80
    if port is None or port == default_port:
        port = None  # 规范化 scheme 默认端口
    for entry in allowed_hosts:
        allowed_host, allowed_port = _normalize_allowed_host(entry)
        if hostname == allowed_host and (allowed_port is None or allowed_port == port):
            return
    raise _ArasRequestError("base_url host is not allowed", "HostNotAllowed")


def _build_aras_client_from_payload(
    payload: dict[str, Any],
    allowed_hosts: Sequence[str] | None = None,
) -> ArasCrawlerClient:
    base_url = str(payload["base_url"]).strip()
    hosts = tuple(allowed_hosts) if allowed_hosts is not None else _DEFAULT_ARAS_ALLOWED_HOSTS
    _validate_allowed_base_url(base_url, hosts)
    headers = _clean_string_mapping(payload.get("headers"))
    auth_mode = str(payload.get("auth_mode") or "browser").strip().lower()
    if auth_mode not in {"password", "browser"}:
        raise _ArasRequestError("auth_mode must be password or browser")

    if auth_mode == "password":
        if any(name.lower() in {"authorization", "cookie", "set-cookie"} for name in headers):
            raise _ArasRequestError(
                "password authentication cannot be combined with secret headers",
                "AuthenticationModeConflict",
            )
        if str(payload.get("cookie") or "").strip() or _clean_string_mapping(payload.get("cookies")):
            raise _ArasRequestError(
                "password authentication cannot be combined with browser cookies",
                "AuthenticationModeConflict",
            )
        username = str(payload.get("username") or "").strip()
        password = str(payload.get("password") or "")
        if not username:
            raise _ArasRequestError("username is required for password authentication")
        if not password:
            raise _ArasRequestError("password is required for password authentication")
        report = MarkdownDiagnosticReport(
            options=DiagnosticOptions(enabled=True, unsafe_raw=False),
            base_url=base_url,
            mode="aras:web",
            inputs={
                "auth_mode": "password",
                "origin": urlsplit(base_url).netloc,
            },
            report_title="Aras WebUI Diagnostic",
            file_name_prefix="aras_webui_auth",
            output_dir=DIAGNOSTIC_DIR,
            allow_unsafe_raw=False,
        )
        try:
            login_result = ArasECMAuthClient(
                base_url, timeout=30.0, diagnostic_hook=report.record_http_event
            ).login(username, password)
        except ArasAuthError as exc:
            diagnostic_path = _save_web_diagnostic_report(report, exc)
            raise _ArasRequestError(
                f"ECM authentication failed: {_sanitize_error_message(exc)}",
                "AuthenticationError",
                401,
                diagnostic_path=diagnostic_path,
            ) from None
        client = ArasCrawlerClient(
            base_url,
            session=login_result.session,
            headers=headers,
            timeout=30.0,
            diagnostic_hook=report.record_http_event,
        )
        setattr(client, "_web_diagnostic_report", report)
        return client

    if str(payload.get("username") or "").strip() or str(payload.get("password") or ""):
        raise _ArasRequestError(
            "browser authentication cannot be combined with username/password",
            "AuthenticationModeConflict",
        )
    cookie = payload.get("cookie")
    cookies = _clean_string_mapping(payload.get("cookies")) or None
    if not any(name.lower() in {"authorization", "cookie", "set-cookie"} for name in headers):
        shared = _shared_domain_session("aras")
        if shared is not None and not (isinstance(cookie, str) and cookie.strip()) and not cookies:
            return ArasCrawlerClient(base_url, session=shared, headers=headers, timeout=30.0)
    if isinstance(cookie, str) and cookie.strip():
        headers["Cookie"] = cookie.strip()
    if not headers and not (isinstance(cookie, str) and cookie.strip()) and not cookies:
        raise _ArasRequestError(
            "尚未建立统一域账号会话：请先在「设置 → 统一域账号登录」完成登录",
            "DomainSessionRequired",
            401,
        )
    return ArasCrawlerClient(
        base_url,
        headers=headers,
        cookies=cookies,
        timeout=30.0,
    )


def _shared_domain_session(system: str) -> Any | None:
    if not has_app_context():
        return None
    registry = current_app.extensions.get("domain_sessions")
    if not isinstance(registry, DomainSessionRegistry):
        return None
    return registry.session(system)


def _async_session_gate(system: str, payload: Mapping[str, Any]) -> tuple[Any | None, Any | None]:
    """后台异步任务凭据准入（红线：凭据禁止入库持久化）。

    密码模式与显式 Cookie/Authorization 只存在于请求生命周期内，无法随任务
    参数安全落库；后台 worker 仅允许复用应用内存中的统一域会话对象。
    Returns (session, error_response) — 恰好其一为 None。
    """
    auth_mode = str(payload.get("auth_mode") or "browser").strip().lower()
    has_secret_headers = any(
        name.lower() in {"authorization", "cookie", "set-cookie"}
        for name in _clean_string_mapping(payload.get("headers"))
    )
    has_cookie = bool(
        str(payload.get("cookie") or "").strip() or _clean_string_mapping(payload.get("cookies"))
    )
    has_userpass = bool(
        str(payload.get("username") or "").strip() or str(payload.get("password") or "")
    )
    if auth_mode == "password" or has_userpass:
        return None, _json_error(
            400,
            "AsyncAuthUnsupported",
            "后台任务不支持账号密码模式：凭据禁止入库持久化；请使用「设置 → 统一域账号登录」后重试",
        )
    if has_secret_headers or has_cookie:
        return None, _json_error(
            400,
            "AsyncAuthUnsupported",
            "后台任务不支持显式 Cookie/Authorization 凭据：凭据禁止入库持久化；请使用统一域账号会话",
        )
    session = _shared_domain_session(system)
    if session is None:
        return None, _json_error(
            401,
            "DomainSessionRequired",
            "尚未建立统一域账号会话：请先在「设置 → 统一域账号登录」完成登录",
        )
    return session, None


def _close_owned_tdc_client(client: TDCCrawlerClient | None) -> None:
    """Close one-shot TDC sessions without closing the shared domain session."""
    if client is None:
        return
    session = getattr(client, "session", None)
    if session is None or session is _shared_domain_session("tdc"):
        return
    close = getattr(session, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception as exc:  # cleanup must not mask the request result
        logger.debug("TDC one-shot session close failed: %s", type(exc).__name__)


def _filter_payload(payload: dict[str, Any]) -> dict[str, Any]:
    filters = payload.get("filters", {})
    return filters if isinstance(filters, dict) else {}


def _none_if_blank(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _department_names(value: Any) -> list[str]:
    """把 department 字段解析为显示名列表（字符串按逗号分隔；空值 → 不筛选）。"""
    if value is None:
        return []
    if isinstance(value, str):
        names = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, (list, tuple)):
        names = [str(item).strip() for item in value if str(item).strip()]
    else:
        raise _ArasRequestError("department must be a string or a list of strings")
    return names


def _paa_department_from_filters(filters: dict[str, Any]) -> str | None:
    """PAA department：空值不筛；非空归一化后必须唯一系统部门，未知/多部门 400。"""
    raw_value = filters.get("department")
    if isinstance(raw_value, str) and any(marker in raw_value for marker in ("*", "|")):
        return raw_value.strip() or None
    names = _department_names(filters.get("department"))
    if not names:
        return None
    try:
        resolved = tuple(dict.fromkeys(normalize_departments(names)))
    except ValueError as exc:
        raise _ArasRequestError(str(exc)) from None
    if len(resolved) != 1:
        raise _ArasRequestError("department must resolve to a single system department")
    return resolved[0]


def _ncr_section_codes_from_filters(filters: dict[str, Any]) -> tuple[str, ...]:
    """NCR 业务 department → NCR 科室代码（未知部门 400）；高级 section_code 仍可用。"""
    names = _department_names(filters.get("department"))
    if not names:
        return ()
    try:
        return resolve_ncr_section_codes(names)
    except ValueError as exc:
        raise _ArasRequestError(str(exc)) from None


def _ewo_filters_from_payload(
    payload: dict[str, Any],
    *,
    default_rsp_department: str | None = None,
) -> EWOReportFilters:
    filters = _filter_payload(payload)
    return EWOReportFilters(
        ewo_no=_none_if_blank(filters.get("ewo_no")),
        project_code=_none_if_blank(filters.get("project_code")),
        subject_keyword=_none_if_blank(filters.get("subject_keyword")),
        change_type=_none_if_blank(filters.get("change_type")),
        change_sub_type=_none_if_blank(filters.get("change_sub_type")),
        area=_none_if_blank(filters.get("area")),
        state=_none_if_blank(filters.get("state")),
        rsp_department=(
            _none_if_blank(filters.get("rsp_department"))
            or _none_if_blank(default_rsp_department)
        ),
        rsp_smt=_none_if_blank(filters.get("rsp_smt")),
        submit_start=_none_if_blank(filters.get("submit_start")),
        submit_end=_none_if_blank(filters.get("submit_end")),
        model_info=_none_if_blank(filters.get("model_info")),
    )


def _paa_filters_from_payload(payload: dict[str, Any]) -> PAAReportFilters:
    filters = _filter_payload(payload)
    return PAAReportFilters(
        paa_no=_none_if_blank(filters.get("paa_no")),
        ewo_no=_none_if_blank(filters.get("ewo_no")),
        state=_none_if_blank(filters.get("state")),
        area=_none_if_blank(filters.get("area")),
        base=_none_if_blank(filters.get("base")),
        vehicle_keyword=_none_if_blank(filters.get("vehicle_keyword")),
        submit_start=_none_if_blank(filters.get("submit_start")),
        submit_end=_none_if_blank(filters.get("submit_end")),
        mtl_rq_start=_none_if_blank(filters.get("mtl_rq_start")),
        mtl_rq_end=_none_if_blank(filters.get("mtl_rq_end")),
        department=_paa_department_from_filters(filters),
    )


def _ncr_filters_from_payload(payload: dict[str, Any]) -> NCRApprovalFilters:
    filters = _filter_payload(payload)
    project_names = filters.get("project_names", ())
    if isinstance(project_names, str):
        projects = tuple(item.strip() for item in project_names.split(",") if item.strip())
    elif isinstance(project_names, list):
        projects = tuple(str(item).strip() for item in project_names if str(item).strip())
    else:
        projects = ()
    return NCRApprovalFilters(
        buy_start=_none_if_blank(filters.get("buy_start")),
        buy_end=_none_if_blank(filters.get("buy_end")),
        pe_start=_none_if_blank(filters.get("pe_start")),
        pe_end=_none_if_blank(filters.get("pe_end")),
        ncr_no=_none_if_blank(filters.get("ncr_no")),
        project_names=projects,
        section_code=_none_if_blank(filters.get("section_code")),
        section_codes=_ncr_section_codes_from_filters(filters),
        change_type=_none_if_blank(filters.get("change_type")),
        othercondition=str(filters.get("othercondition") or "0").strip() or "0",
    )


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _analysis_query_values(
    primary: str,
    legacy: str,
    *,
    kind: str,
) -> tuple[str, ...] | None:
    """Read bounded repeated analysis filters, preferring the new key."""
    if primary in request.args:
        raw_values = request.args.getlist(primary)
    elif legacy in request.args:
        raw_values = [request.args.get(legacy, "")]
    else:
        return None
    if len(raw_values) > 20:
        raise ValueError(f"{kind} accepts at most 20 values")
    values: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        value = str(raw_value or "").strip()
        if not value:
            continue
        if len(value) > 120:
            raise ValueError(f"{kind} value is too long")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError(f"{kind} contains control characters")
        if value not in seen:
            seen.add(value)
            values.append(value)
    return tuple(values)


def _archive_history_limit(value: Any, default: int = 100) -> int:
    """Parse archive history limits strictly; invalid input is never defaulted."""
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError("limit must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("limit must be a positive integer") from exc
    if parsed < 1:
        raise ValueError("limit must be a positive integer")
    return parsed


def _safe_attachment_basename(name: str, fallback: str = "ncr_detail") -> str:
    """服务端安全 basename（去路径与控制字符），用于 Content-Disposition。"""
    base = Path(str(name or "")).name
    base = _INVALID_ATTACHMENT_CHARS_RE.sub("_", base).strip(" .")
    return base or fallback


def _tdc_positive_int(value: Any, name: str, default: int, maximum: int) -> int:
    """严格正整数边界校验：缺失用默认值，非法值 fail-closed。"""
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise _TDCRequestError(f"{name} must be an integer")
    if value <= 0 or value > maximum:
        raise _TDCRequestError(f"{name} must be between 1 and {maximum}")
    return value


def _tdc_filter_string(filters: dict[str, Any], name: str) -> str | None:
    value = filters.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _TDCRequestError(f"{name} filter must be a string")
    return value.strip() or None


def _tdc_filters_from_payload(
    payload: dict[str, Any],
    allowed_names: tuple[str, ...],
) -> dict[str, str | None]:
    filters = payload.get("filters", {})
    if not isinstance(filters, dict):
        raise _TDCRequestError("filters must be an object")
    unknown = [name for name in filters if name not in allowed_names]
    if unknown:
        raise _TDCRequestError("filters contains unsupported fields")
    return {name: _tdc_filter_string(filters, name) for name in allowed_names}


def _tdc_data_model_filters(values: dict[str, str | None]) -> TDCDataModelFilters:
    # API 层键名仍是 serial_number（前端传参键；历史持久化值一律按实例号处理）：
    # 它对应第 0 列实例号 incident，不是流水单号（documentNo）。
    return TDCDataModelFilters(
        instance_no=values.get("serial_number"),
        applicant=values.get("applicant"),
        department=values.get("department"),
        section=values.get("section"),
        application_start=values.get("application_start"),
        application_end=values.get("application_end"),
        project_model=values.get("project_model"),
        part_number=values.get("part_number"),
        model_number=values.get("model_number"),
        status=values.get("status"),
    )


def _tdc_sor_filters(values: dict[str, str | None]) -> TDCSORFilters:
    return TDCSORFilters(
        serial_number=values.get("serial_number"),
        process_type=values.get("process_type"),
        car_type_project=values.get("car_type_project"),
        car_type_project_id=values.get("car_type_project_id"),
        applicant=values.get("applicant"),
        title=values.get("title"),
        department=values.get("department"),
        section=values.get("section"),
        application_start=values.get("application_start"),
        application_end=values.get("application_end"),
        part_number=values.get("part_number"),
        part_name=values.get("part_name"),
        version=values.get("version"),
        sor_number=values.get("sor_number"),
        latest_completed_node=values.get("latest_completed_node"),
        approval_status=values.get("approval_status"),
    )


def _tdc_preview_source(payload: Mapping[str, Any]) -> str:
    """Validate the explicit TDC query source selector."""
    value = payload.get("preview_source")
    if value is None:
        return "list_endpoint"
    if not isinstance(value, str):
        raise _TDCRequestError("preview_source must be list_endpoint or official_export")
    source = value.strip() or "list_endpoint"
    if source not in {"list_endpoint", "official_export"}:
        raise _TDCRequestError("preview_source must be list_endpoint or official_export")
    return source


_TDC_DATA_MODEL_FILTER_NAMES = tuple(
    field["name"] for field in _TDC_DATA_MODEL_FIELDS if field["name"] != "document_no"
)
_TDC_SOR_FILTER_NAMES = tuple(field["name"] for field in _TDC_SOR_FIELDS) + ("car_type_project_id",)

_MAPPING_DISCOVERY_RULE_FIELDS: dict[tuple[str, str], dict[str, str]] = {
    ("tdc", "data_model"): {
        "serial_number": "incident",
        "applicant": "applicant",
        "department": "department",
        "section": "section",
        "application_start": "applicationStart",
        "application_end": "applicationEnd",
        "project_model": "projectModel",
        "part_number": "partNumber",
        "model_number": "modelNumber",
        "status": "status",
        # 流水单号不是 TDC 查询参数：该值不发上游，改为全量抓取后本地精确匹配。
        "document_no": "documentNo",
    },
    ("tdc", "sor"): {
        "serial_number": "processNo",
        "process_type": "processType",
        "car_type_project": "carTypeProject",
        "car_type_project_id": "carTypeProjectId",
        "applicant": "applicant",
        "title": "title",
        "department": "department",
        "section": "section",
        "application_start": "applicationStart",
        "application_end": "applicationEnd",
        "part_number": "partNumber",
        "part_name": "partName",
        "version": "version",
        "sor_number": "sorNumber",
        "latest_completed_node": "latestCompletedNode",
        "approval_status": "approvalStatus",
    },
    ("aras", "ewo"): {
        "ewo_no": "ewoNo",
        "project_code": "projectCode",
        "subject_keyword": "subjectKeyword",
        "change_type": "changeType",
        "change_sub_type": "changeSubType",
        "area": "area",
        "state": "state",
        "rsp_department": "rspDepartment",
        "rsp_smt": "rspSmt",
        "submit_start": "submitStart",
        "submit_end": "submitEnd",
        "model_info": "modelInfo",
    },
    ("aras", "paa"): {
        "serial_number": "paaNo",
        "paa_no": "paaNo",
        "project_model": "projectModel",
        "department": "department",
        "section_code": "sectionCode",
        "ewo_no": "ewoNo",
    },
    ("aras", "ncr_progress"): {
        "serial_number": "ncrNo",
        "ncr_no": "ncrNo",
        "project_model": "projectModel",
        "department": "department",
        "section_code": "sectionCode",
    },
    ("aras", "ncr_detail"): {
        "serial_number": "ncrNo",
        "ncr_no": "ncrNo",
        "project_model": "projectModel",
        "department": "department",
        "section_code": "sectionCode",
    },
}


def _mapping_discovery_query_identity(
    payload: dict[str, Any],
    deliverable_id: str,
    selected_external_key: str | None = None,
) -> tuple[dict[str, Any], dict[str, str | None]]:
    """Freeze the validated, canonical query rule at POST request start."""
    capability = PROJECT_STATUS_SOURCE_CAPABILITIES.get(deliverable_id) or {}
    source_type = str(capability.get("sourceType") or "").strip()
    report_type = str(capability.get("reportType") or "").strip()
    mapping = _MAPPING_DISCOVERY_RULE_FIELDS.get((source_type, report_type))
    if not mapping:
        raise _ArasRequestError("mapping discovery is not available for this deliverable")
    error_type = _TDCRequestError if source_type == "tdc" else _ArasRequestError
    filters = payload.get("filters", {})
    if not isinstance(filters, dict):
        raise error_type("filters must be an object")
    unknown = [name for name in filters if name not in mapping]
    if unknown:
        raise error_type("filters contains unsupported fields")
    values: dict[str, str | None] = {}
    rule: dict[str, Any] = {
        "reportType": report_type,
        "aggregate": capability.get("aggregate") is True,
    }
    aggregate = payload.get("aggregate", rule["aggregate"])
    if not isinstance(aggregate, bool):
        raise error_type("aggregate must be a boolean")
    rule["aggregate"] = aggregate
    versioned_ewo = any(key in payload for key in ('contractVersion', 'bindingMode', 'sourceItemId'))
    if versioned_ewo:
        if source_type != 'aras' or capability.get("supportsRecordSet") is not True:
            raise error_type('Versioned record-set source mismatch')
        for key in ('contractVersion', 'bindingMode', 'sourceItemId'):
            if key in payload:
                rule[key] = payload[key]
    for name, rule_name in mapping.items():
        value = filters.get(name)
        if value is None:
            values[name] = None
            continue
        if not isinstance(value, str):
            raise error_type(f"{name} filter must be a string")
        clean = value.strip() or None
        values[name] = clean
        if clean is not None:
            rule[rule_name] = clean
    if source_type == "aras" and report_type in {"ncr_progress", "ncr_detail"}:
        # NCR 科室代码：配置保存/探测与同步 collect 共用同一解析器（fail-closed，
        # 非法输入 422 并列出合法代码；空 = 不限科室）。
        raw_section = rule.get("sectionCode")
        if raw_section:
            try:
                parse_ncr_section_codes_input(str(raw_section))
            except ValueError as exc:
                raise _ArasRequestError(str(exc)) from None
    if (
        source_type == "aras"
        and report_type == "ewo"
        and not str(rule.get("rspDepartment") or "").strip()
    ):
        # The scheduled connector applies this bounded source-side scope
        # whenever the binding omits rspDepartment.  Include it in the
        # request identity so discovery evidence and execution query the
        # same EWO population.
        rule["rspDepartment"] = EWO_DEFAULT_RSP_DEPARTMENT_EXPRESSION
    if not versioned_ewo and not aggregate and selected_external_key:
        stable_filter_name = {
            # 数模的稳定键是流水单号（documentNo），不是实例号 incident：incident
            # 是第 0 列实例号，拿它当"选定单号"会把查询收窄到错误的行集。
            "tdc/data_model": "documentNo",
            "tdc/sor": "processNo",
            "aras/ewo": "ewoNo",
            "aras/paa": "paaNo",
            "aras/ncr_progress": "ncrNo",
            "aras/ncr_detail": "ncrNo",
        }.get(f"{source_type}/{report_type}")
        if stable_filter_name:
            existing = rule.get(stable_filter_name)
            if existing is not None and existing != selected_external_key:
                raise error_type("selected external key conflicts with the query filter")
            rule[stable_filter_name] = selected_external_key
            for filter_name, canonical_name in mapping.items():
                if canonical_name == stable_filter_name:
                    # Keep the actual crawler request aligned with the
                    # request identity.  Previously selectedExternalKey was
                    # used only by observe(), so the signed rule could claim
                    # a narrower query than the rows actually fetched.
                    values[filter_name] = selected_external_key
                    break
    if source_type == "aras" and report_type == "ewo" and rule.get("modelInfo"):
        # In the established model-anchor mode the connector searches the
        # model population and resolves a selected EWO number locally; an
        # ewoNo filter is therefore not part of the effective query.
        rule.pop("ewoNo", None)
    if versioned_ewo:
        from core.ewo_binding_v2 import normalize_ewo_v2_rule
        rule = normalize_ewo_v2_rule(rule)
        if not aggregate and selected_external_key != rule['sourceItemId']:
            raise error_type('Selected EWO source ID mismatch')
    if source_type == "tdc" and report_type == "data_model":
        # 流水单号与实例号二选一（与 updates 落库校验同语义，2026-10-09）：同填时
        # 运行期会按两键取交集，指向不同行则永久 not_found 且无从提示。
        if str(rule.get("documentNo") or "").strip() and str(rule.get("incident") or "").strip():
            raise error_type("流水单号与实例号二选一：请只填写其中一项")
        if rule.get("documentNo"):
            # 流水单号（documentNo）不是 TDC 查询参数（查询参数 incident 是第 0 列
            # 实例号）：该值绝不发给上游，改为全量抓取后由调用方本地精确匹配。
            values.pop("document_no", None)
    return rule, values


def _pagination_diagnostic(result: Any, row_count: int) -> dict[str, Any]:
    """有界、非敏感的抓取完整性事实，供前端与用户自诊断。

    只允许枚举值（stop_reason）与计数；不含任何上游原文或业务行内容。
    """
    def _bounded_int(name: str) -> int | None:
        value = getattr(result, name, None)
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value

    return {
        "stopReason": str(getattr(result, "stop_reason", "") or "unknown")[:64],
        "rowCount": row_count,
        "uniqueCount": _bounded_int("unique_count"),
        "duplicateCount": _bounded_int("duplicate_count"),
        "declaredTotal": _bounded_int("total"),
        "declaredPages": _bounded_int("pages"),
        "fetchedPages": _bounded_int("fetched_pages"),
    }


def _mapping_result_is_complete(result: Any) -> bool:
    """抓取结果是否有显式终局证据（与 ``_require_complete_mapping_result`` 同源）。"""
    stop_reason = str(getattr(result, "stop_reason", "unknown") or "unknown")
    return getattr(result, "complete", None) is True and stop_reason in COMPLETE_RESULT_STOP_REASONS


def _require_complete_mapping_result(result: Any, error_type: type[ValueError]) -> list[dict[str, Any]]:
    """Accept only a crawler result with explicit end-of-data evidence.

    失败时把完整性事实放进 `error.diagnostic`：此前只回一句「不完整」，
    导致线上问题无法定位（两轮修复都只能靠猜）。
    """
    rows = getattr(result, "rows", None)
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise error_type("mapping discovery result must contain a list of objects")
    if len(rows) > MAX_AGGREGATE_RECORDS:
        raise error_type(
            f"mapping discovery result exceeds maximum {MAX_AGGREGATE_RECORDS}",
            "DiscoveryLimitExceeded",
            422,
        )
    if not _mapping_result_is_complete(result):
        raise error_type(
            "mapping discovery query was incomplete; narrow the filters or retry",
            "IncompleteDiscovery",
            422,
            None,
            _pagination_diagnostic(result, len(rows)),
        )
    return [dict(row) for row in rows]


def _validate_tdc_base_url(
    base_url: str,
    allowed_hosts: Sequence[str],
    *,
    require_https: bool,
) -> None:
    """构造 TDC client 前执行主机 allowlist；password 模式额外要求 HTTPS。"""
    try:
        parsed = urlsplit(str(base_url or "").strip())
        port = parsed.port
    except ValueError:
        raise _TDCRequestError("base_url is not a valid URL", "HostNotAllowed") from None
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise _TDCRequestError("base_url must use http or https", "HostNotAllowed")
    if require_https and scheme != "https":
        raise _TDCRequestError("password authentication requires an HTTPS base_url", "HostNotAllowed")
    if parsed.username is not None or parsed.password is not None:
        raise _TDCRequestError("base_url must not contain userinfo", "HostNotAllowed")
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise _TDCRequestError("base_url must include a host", "HostNotAllowed")
    default_port = 443 if scheme == "https" else 80
    if port is None or port == default_port:
        port = None
    for entry in allowed_hosts:
        allowed_host, allowed_port = _normalize_allowed_host(entry)
        if hostname == allowed_host and (allowed_port is None or allowed_port == port):
            return
    raise _TDCRequestError("base_url host is not allowed", "HostNotAllowed")


def _build_tdc_client_from_payload(
    payload: dict[str, Any],
    allowed_hosts: Sequence[str] | None = None,
    *,
    output_dir: Path | None = None,
) -> TDCCrawlerClient:
    base_url = str(payload["base_url"]).strip()
    hosts = tuple(allowed_hosts) if allowed_hosts is not None else _DEFAULT_TDC_ALLOWED_HOSTS
    auth_mode = str(payload.get("auth_mode") or "browser").strip().lower()
    if auth_mode not in {"password", "browser"}:
        raise _TDCRequestError("auth_mode must be password or browser")
    headers = _clean_string_mapping(payload.get("headers"))
    secret_header_names = {"authorization", "cookie", "set-cookie"}
    cookies = _clean_string_mapping(payload.get("cookies"))
    cookie = payload.get("cookie")

    if auth_mode == "password":
        _validate_tdc_base_url(base_url, hosts, require_https=True)
        if any(name.lower() in secret_header_names for name in headers):
            raise _TDCRequestError(
                "password authentication cannot be combined with secret headers",
                "AuthenticationModeConflict",
            )
        if (isinstance(cookie, str) and cookie.strip()) or cookies:
            raise _TDCRequestError(
                "password authentication cannot be combined with browser cookies",
                "AuthenticationModeConflict",
            )
        username = str(payload.get("username") or "").strip()
        password = str(payload.get("password") or "")
        if not username:
            raise _TDCRequestError("username is required for password authentication")
        if not password:
            raise _TDCRequestError("password is required for password authentication")
        report = MarkdownDiagnosticReport(
            options=DiagnosticOptions(enabled=True, unsafe_raw=False),
            base_url=base_url,
            mode="tdc:auth",
            inputs={
                "auth_mode": "password",
                "origin": urlsplit(base_url).netloc,
            },
            report_title="TDC WebUI Auth Diagnostic",
            file_name_prefix="tdc_webui_auth",
            output_dir=DIAGNOSTIC_DIR,
            allow_unsafe_raw=False,
        )
        try:
            login_result = TDCPasswordAuthClient(
                base_url, timeout=30.0, diagnostic_hook=report.record_http_event
            ).login(username, password)
        except TDCAuthError as exc:
            report.record_exception(exc)
            try:
                diagnostic_path = report.save("failed")
            except OSError:
                # 诊断落盘失败不得改变认证错误的 HTTP 语义；降级为无路径
                diagnostic_path = None
            raise _TDCRequestError(
                f"TDC authentication failed: {_sanitize_error_message(exc)}",
                "AuthenticationError",
                401,
                diagnostic_path=diagnostic_path,
            ) from None
        return TDCCrawlerClient(
            base_url,
            session=login_result.session,
            headers=headers,
            timeout=30.0,
            output_dir=output_dir,
        )

    _validate_tdc_base_url(base_url, hosts, require_https=False)
    if str(payload.get("username") or "").strip() or str(payload.get("password") or ""):
        raise _TDCRequestError(
            "browser authentication cannot be combined with username/password",
            "AuthenticationModeConflict",
        )
    if isinstance(cookie, str) and cookie.strip():
        headers["Cookie"] = cookie.strip()
    if cookies:
        cookie_pairs = "; ".join(f"{key}={value}" for key, value in cookies.items())
        existing = headers.get("Cookie")
        headers["Cookie"] = f"{existing}; {cookie_pairs}" if existing else cookie_pairs
    shared = _shared_domain_session("tdc")
    if shared is not None and not headers.get("Cookie"):
        return TDCCrawlerClient(
            base_url, session=shared, headers=headers, timeout=30.0, output_dir=output_dir
        )
    if not headers:
        raise _TDCRequestError(
            "尚未建立统一域账号会话：请先在「设置 → 统一域账号登录」完成登录",
            "DomainSessionRequired",
            401,
        )
    return TDCCrawlerClient(base_url, headers=headers, timeout=30.0, output_dir=output_dir)


def _tdc_file_name(value: Any) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise _TDCRequestError("file_name must be a string")
    name = value.strip()
    if len(name) > 180:
        raise _TDCRequestError("file_name is too long")
    if Path(name).name != name or ".." in Path(name).parts:
        raise _TDCRequestError("file_name must be a plain basename without traversal")
    if not _TDC_XLSX_NAME_RE.fullmatch(name):
        raise _TDCRequestError("file_name must be a safe .xlsx basename")
    return name


def _tdc_query(
    client: TDCCrawlerClient,
    report_type: str,
    filters: Any,
    *,
    page: int,
    page_size: int,
):
    if report_type == "data_model":
        return client.query_data_model_page(filters, page=page, page_size=page_size)
    return client.query_sor_page(filters, page=page, page_size=page_size)


def _tdc_crawl(
    client: TDCCrawlerClient,
    report_type: str,
    filters: Any,
    *,
    page_size: int,
    max_pages: int,
    max_records: int,
    should_stop: Callable[[], bool] | None = None,
    on_page: Callable[[int, int], None] | None = None,
):
    if report_type == "data_model":
        return client.crawl_data_model_all(
            filters,
            page_size=page_size,
            max_pages=max_pages,
            max_records=max_records,
            should_stop=should_stop,
            on_page=on_page,
        )
    return client.crawl_sor_all(
        filters,
        page_size=page_size,
        max_pages=max_pages,
        max_records=max_records,
        should_stop=should_stop,
        on_page=on_page,
    )


def _tdc_export(
    client: TDCCrawlerClient,
    report_type: str,
    filters: Any,
    *,
    file_name: str | None,
):
    if report_type == "data_model":
        return client.export_data_model(filters, file_name=file_name)
    return client.export_sor(filters, file_name=file_name)


def _tdc_result_data(result: Any) -> dict[str, Any]:
    if result.report_type == "data_model":
        safe_rows = _safe_rows(result.rows)
        table = table_payload("tdc_data_model", safe_rows)
    elif result.report_type == "sor":
        safe_rows = _safe_tdc_sor_rows(result.rows)
        table = table_payload("tdc_sor", safe_rows)
    else:
        raise ValueError(f"unsupported TDC report type: {result.report_type}")
    return {
        **table,
        "report_type": result.report_type,
        "data_source": "list_endpoint",
        "page": result.page,
        "page_size": result.page_size,
        "total": result.total,
        "pages": result.pages,
        "fetched_pages": result.fetched_pages,
        "unique_count": result.unique_count,
        "duplicate_count": result.duplicate_count,
        "stop_reason": result.stop_reason,
        "record_granularity": result.record_granularity,
    }


def _tdc_export_cache_context(payload: Mapping[str, Any]) -> tuple[TDCExportCache, str] | None:
    """Return a cache and non-secret namespace for one safe local request."""
    if not has_app_context():
        return None
    cache = current_app.extensions.get("tdc_export_cache")
    if not isinstance(cache, TDCExportCache):
        return None
    headers = payload.get("headers")
    if isinstance(headers, Mapping) and any(
        str(key).lower() in {"authorization", "cookie", "set-cookie"} for key in headers
    ):
        return None
    if str(payload.get("cookie") or "").strip() or payload.get("cookies"):
        return None
    auth_mode = str(payload.get("auth_mode") or "browser").strip().lower()
    if auth_mode == "password":
        username = str(payload.get("username") or "").strip()
        if not username:
            return None
        marker = hashlib.sha256(username.encode("utf-8")).hexdigest()
        return cache, f"password-user:{marker}"
    shared = _shared_domain_session("tdc")
    if shared is None:
        return None
    registry = current_app.extensions.get("domain_sessions")
    marker = ""
    if isinstance(registry, DomainSessionRegistry):
        status = registry.payload().get("tdc", {})
        if isinstance(status, Mapping):
            marker = str(status.get("updatedAt") or status.get("expiresAt") or "")
    if not marker:
        return None
    return cache, f"shared-session:{marker}:{id(shared)}"


def _tdc_sor_project_options(projects: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Expose only the safe, user-visible fields of TDC project choices."""
    options: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for project in projects:
        if not isinstance(project, Mapping):
            continue
        project_id = _safe_tdc_sor_value(project.get("id"))
        project_no = _safe_tdc_sor_value(project.get("projectNo"))
        project_name = _safe_tdc_sor_value(project.get("projectName"))
        if not project_id:
            continue
        identity = (project_id, project_no or "", project_name or "")
        if identity in seen:
            continue
        seen.add(identity)
        label = project_no or project_name or project_id
        if project_no and project_name and project_no != project_name:
            label = f"{project_no} — {project_name}"
        options.append(
            {
                "id": project_id,
                "projectNo": project_no or "",
                "projectName": project_name or "",
                "label": label,
            }
        )
    return options


def _tdc_official_export_bytes(
    payload: Mapping[str, Any],
    report_type: str,
    filters: Any,
    allowed_hosts: Sequence[str],
    *,
    file_name: str | None = None,
) -> tuple[bytes, bool]:
    """Fetch one official workbook, using only a safe short-lived cache when possible."""
    cache_context = _tdc_export_cache_context(payload)

    def produce() -> bytes:
        temp_dir = Path(tempfile.mkdtemp(prefix=f"tdc_{report_type}_export_cache_"))
        client: TDCCrawlerClient | None = None
        try:
            client = _build_tdc_client_from_payload(dict(payload), allowed_hosts, output_dir=temp_dir)
            exported = _tdc_export(
                client,
                report_type,
                filters,
                file_name=file_name or f"tdc_{report_type}_cached.xlsx",
            )
            saved = Path(exported.path).resolve()
            if not saved.is_relative_to(temp_dir.resolve()):
                raise TDCCrawlerError(
                    "TDC export produced a path outside the temporary output directory",
                    stage="export-validation",
                )
            return saved.read_bytes()
        finally:
            _close_owned_tdc_client(client)
            shutil.rmtree(temp_dir, ignore_errors=True)

    if cache_context is None:
        return produce(), False
    cache, namespace = cache_context
    key = cache.make_key(
        report_type=report_type,
        base_url=str(payload.get("base_url") or ""),
        filters=filters.to_params(),
        namespace=namespace,
    )
    result = cache.get_or_create(key, produce)
    return result.content, result.hit


def _tdc_data_model_export_bytes(
    payload: Mapping[str, Any],
    filters: TDCDataModelFilters,
    allowed_hosts: Sequence[str],
    *,
    file_name: str | None = None,
) -> tuple[bytes, bool]:
    return _tdc_official_export_bytes(
        payload,
        "data_model",
        filters,
        allowed_hosts,
        file_name=file_name,
    )


def _tdc_sor_export_bytes(
    payload: Mapping[str, Any],
    filters: TDCSORFilters,
    allowed_hosts: Sequence[str],
    *,
    file_name: str | None = None,
) -> tuple[bytes, bool]:
    return _tdc_official_export_bytes(
        payload,
        "sor",
        filters,
        allowed_hosts,
        file_name=file_name,
    )


def _tdc_official_preview(
    payload: Mapping[str, Any],
    report_type: str,
    filters: Any,
    allowed_hosts: Sequence[str],
    *,
    operation: str,
    page: int = 1,
    page_size: int = 50,
    max_records: int = _TDC_MAX_RECORDS_MAX,
) -> dict[str, Any]:
    """Preview an official TDC workbook using its approved table contract."""
    contract_key = "tdc_data_model" if report_type == "data_model" else "tdc_sor"
    temp_dir = Path(tempfile.mkdtemp(prefix=f"tdc_{report_type}_preview_"))
    try:
        if report_type == "data_model":
            content, cache_hit = _tdc_data_model_export_bytes(payload, filters, allowed_hosts)
        else:
            content, cache_hit = _tdc_sor_export_bytes(payload, filters, allowed_hosts)
        saved = temp_dir / f"tdc_{report_type}_preview.xlsx"
        saved.write_bytes(content)

        preview = read_xlsx_preview(saved, max_rows=_TDC_OFFICIAL_PREVIEW_MAX_ROWS)
        expected_header = [
            str(value or "").strip() for value in report_contracts()[contract_key]["headerRows"][0]
        ]
        actual_header = [
            str(value or "").strip() for value in (preview.rows[0] if preview.rows else [])
        ]
        if (
            len(actual_header) < len(expected_header)
            or actual_header[: len(expected_header)] != expected_header
            or any(actual_header[len(expected_header) :])
        ):
            raise TDCCrawlerError(
                f"official TDC {report_type} export header does not match the approved contract",
                stage="contract-validation",
            )

        data_rows = [
            [None if value is None else redact_sensitive_text(value) for value in row]
            for row in preview.rows[1:]
            if row and any(value not in (None, "") for value in row)
        ]
        total = None if preview.truncated else len(data_rows)
        pages = None if total is None else (total + page_size - 1) // page_size
        if operation == "query":
            start = (page - 1) * page_size
            selected_rows = data_rows[start : start + page_size]
            result_page = page
            result_page_size = page_size
            stop_reason = "official_export_truncated" if preview.truncated else "official_export"
        else:
            selected_rows = data_rows[:max_records]
            result_page = 1
            result_page_size = page_size
            if len(data_rows) > max_records:
                stop_reason = "max_records"
            else:
                stop_reason = "official_export_truncated" if preview.truncated else "official_export"

        table = matrix_payload(contract_key, selected_rows)
        return {
            **table,
            "report_type": report_type,
            "data_source": "official_export",
            "page": result_page,
            "page_size": result_page_size,
            "total": total,
            "pages": pages,
            "fetched_pages": 1,
            "unique_count": len(selected_rows),
            "duplicate_count": 0,
            "stop_reason": stop_reason,
            "record_granularity": "part_detail",
            "preview": {
                "sheetName": preview.sheet_name,
                "sheetNames": list(preview.sheet_names),
                "truncated": preview.truncated,
                "maxRows": _TDC_OFFICIAL_PREVIEW_MAX_ROWS,
            },
            "cache": {"hit": cache_hit, "ttlSeconds": 180},
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _tdc_official_data_model_preview(
    payload: Mapping[str, Any],
    filters: TDCDataModelFilters,
    allowed_hosts: Sequence[str],
    *,
    operation: str,
    page: int = 1,
    page_size: int = 50,
    max_records: int = _TDC_MAX_RECORDS_MAX,
) -> dict[str, Any]:
    return _tdc_official_preview(
        payload,
        "data_model",
        filters,
        allowed_hosts,
        operation=operation,
        page=page,
        page_size=page_size,
        max_records=max_records,
    )


def _tdc_official_sor_preview(
    payload: Mapping[str, Any],
    filters: TDCSORFilters,
    allowed_hosts: Sequence[str],
    *,
    operation: str,
    page: int = 1,
    page_size: int = 50,
    max_records: int = _TDC_MAX_RECORDS_MAX,
) -> dict[str, Any]:
    return _tdc_official_preview(
        payload,
        "sor",
        filters,
        allowed_hosts,
        operation=operation,
        page=page,
        page_size=page_size,
        max_records=max_records,
    )


_PROJECT_STATUS_VALUES = {"已完成", "进行中", "待审批", "已逾期"}
_PROJECT_STATUS_TONES = {
    "已完成": "success",
    "进行中": "primary",
    "待审批": "warning",
    "已逾期": "error",
}

#: 交付物 ↔ 统一表单分析 form_key 的后端单一映射（从
#: core.project_status_contracts.DELIVERABLE_LINK_REGISTRY 派生，仅保留
#: deliverable_id 非 None 的条目，deliverable_id → form_key）。payload 通过
#: formLink 下发给前端，前端不再各自维护该映射。
DELIVERABLE_FORM_LINKS = {
    entry["deliverable_id"]: entry["form_key"]
    for entry in DELIVERABLE_LINK_REGISTRY.values()
    if entry["deliverable_id"] is not None
}


def _deliverable_associations(
    deliverable_id: str,
    archive_jobs_by_key: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """按单一关联注册表反查交付物关联（归档任务 + 目录条目）。

    未关联项目交付物的条目（如 D1/D4）返回空数组。
    """
    entry = find_registry_entry_by_deliverable_id(deliverable_id)
    if entry is None:
        return []
    job_key = find_job_key_by_deliverable_id(deliverable_id)
    catalog_name = next(
        (
            str(item["name"])
            for item in _DELIVERABLES_CATALOG
            if item["id"] == entry["catalog_id"]
        ),
        str(entry["catalog_id"]),
    )
    associations: list[dict[str, Any]] = []
    job_row = archive_jobs_by_key.get(str(job_key or ""))
    associations.append(
        {
            "type": "archive_job",
            "jobKey": job_key,
            "name": (
                str(job_row.get("display_name") or job_key)
                if job_row is not None
                else catalog_name
            ),
            "enabled": bool(job_row["enabled"]) if job_row is not None else False,
            # 只透出「是否已绑定凭据引用」这一布尔事实（来自既有 raw row，无 vault I/O）；
            # 凭据是否真的可用留给点击时的 sync-now 结果，避免污染 /api/project-status 热路径。
            "credentialConfigured": (
                bool(job_row["credential_configured"]) if job_row is not None else False
            ),
            "lastSuccessAt": job_row.get("last_success_at") if job_row is not None else None,
            "href": f"#archive-deliverable/{job_key}",
        }
    )
    associations.append(
        {
            "type": "catalog_item",
            "catalogId": entry["catalog_id"],
            "name": catalog_name,
            "href": "#deliverables",
        }
    )
    return associations


def _deliverable_form_link(
    db: DatabaseManager, deliverable_id: str
) -> dict[str, Any] | None:
    """读取交付物最新表单快照的联动摘要；无映射返回 None。"""
    form_key = DELIVERABLE_FORM_LINKS.get(deliverable_id)
    if not form_key:
        return None
    snapshot_at = None
    summary: dict[str, int] | None = None
    try:
        snapshot = db.get_latest_deliverable_form_snapshot(form_key)
    except KeyError:
        snapshot = None
    if snapshot is not None:
        snapshot_at = snapshot.get("snapshot_at")
        raw_summary = snapshot.get("summary")
        if isinstance(raw_summary, Mapping):
            summary = {
                "total": int(raw_summary.get("total") or 0),
                "completed": int(raw_summary.get("completed") or 0),
                "incomplete": int(raw_summary.get("incomplete") or 0),
                "overdue": int(raw_summary.get("overdue") or 0),
            }
    return {"formKey": form_key, "snapshotAt": snapshot_at, "summary": summary}


def _deliverable_analysis_link(
    db: DatabaseManager,
    deliverable_id: str,
    analysis_service: ProjectStatusDeliverableAnalysisService | None = None,
) -> dict[str, Any] | None:
    """读取交付物最新明细分析快照摘要（与交付物明细页分析同源）。

    传入 analysis_service 时走服务的 latest_link_summary（EWO 交付物按
    当前日期重算逾期/临期，环图与明细页数字一致）；否则读存储摘要。
    """
    if analysis_service is not None:
        return analysis_service.latest_link_summary(deliverable_id)
    snapshots = db.list_project_status_analysis_snapshots(deliverable_id, 1)
    if not snapshots:
        return None
    latest = snapshots[0]
    return {
        "snapshotAt": latest.get("snapshot_at"),
        "summary": {
            "total": int(latest.get("total_count") or 0),
            "completed": int(latest.get("completed_count") or 0),
            "incomplete": int(latest.get("incomplete_count") or 0),
            "overdue": int(latest.get("overdue_count") or 0),
        },
    }


#: 历史快照装载的每请求累计行数上限。30 份历史快照 × 每份最多 20000 行的
#: 全量解码上界过大：按快照从新到旧装载，累计行数达到该上限即停止装载
#: 剩余历史（最新快照行不受影响；单份快照内部行数上限维持 db 层现状）。
_STATISTICS_MAX_HISTORY_ROWS = 20000


def _deliverable_form_statistics_payload(
    db: DatabaseManager,
    form_key: str,
) -> dict[str, Any]:
    """快照统计分析读取装配：最新快照行 + 有界历史快照 → 纯函数。

    只读已落库的规范化行，不做任何抓取或凭据解析；历史快照数量有界
    （STATISTICS_HISTORY_SNAPSHOT_LIMIT），累计行数有界
    （_STATISTICS_MAX_HISTORY_ROWS），避免端点无界读取。
    historyTruncated=True 表示因行数上限停止装载，历史不完整。
    """
    latest = db.get_latest_deliverable_form_snapshot(form_key)
    if latest is None:
        return {
            "formKey": str(form_key),
            "hasSnapshot": False,
            "snapshotAt": None,
            "statistics": None,
            "historyTruncated": False,
        }
    snapshot_id = int(latest["id"])
    snapshot_at = str(latest.get("snapshot_at") or "")
    rows = db.list_deliverable_form_snapshot_rows(snapshot_id)
    history: list[dict[str, Any]] = []
    history_rows_loaded = 0
    history_truncated = False
    snapshots = db.list_deliverable_form_snapshots(
        form_key, limit=STATISTICS_HISTORY_SNAPSHOT_LIMIT + 1
    )
    for item in snapshots:
        if int(item["id"]) == snapshot_id or len(history) >= STATISTICS_HISTORY_SNAPSHOT_LIMIT:
            continue
        if history_rows_loaded >= _STATISTICS_MAX_HISTORY_ROWS:
            history_truncated = True
            break
        entry_rows = db.list_deliverable_form_snapshot_rows(int(item["id"]))
        # 解码成本已发生，即使快照时间非法未入 history 也计入累计上界。
        history_rows_loaded += len(entry_rows)
        entry = statistics_history_entry(item.get("snapshot_at"), entry_rows)
        if entry is not None:
            history.append(entry)
    statistics = compute_form_statistics(
        str(form_key), rows, snapshot_at=snapshot_at, history=history
    )
    return {
        "formKey": str(form_key),
        "hasSnapshot": True,
        "snapshotAt": snapshot_at or None,
        "statistics": statistics,
        "historyTruncated": history_truncated,
    }


def _project_status_payload(
    db: DatabaseManager,
    phase_id: str,
    *,
    today: date | None = None,
    analysis_service: ProjectStatusDeliverableAnalysisService | None = None,
) -> dict[str, Any] | None:
    """把项目状态专用表序列化为前端唯一的已保存状态。"""
    phase_row, milestone_rows, deliverable_rows = db.get_project_status(phase_id)
    if phase_row is None:
        return None
    current_day = today or date.today()
    archive_jobs_by_key = {
        str(row["job_key"]): row
        for row in db.list_archive_jobs(include_archived=True)
    }
    deliverables = []
    # NCR 向导的「科室」预设与看板归集口径同源：取科室归集规则的目标清单
    # （默认五科室，用户可编辑），其他科室值由归集层计入「未归集」。
    section_scope_presets = rollup_targets_in_order(
        build_rollup_index(SectionRollupStore(db).get())
    )
    policy_summaries = db.get_project_status_update_policy_summaries(phase_id)
    for row in deliverable_rows:
        actual_date = row["actual_date"]
        # planned_date 可空（外部快照驱动交付物 D6-D8 无手工排期）：
        # NULL 或非法值均不做排期计算，payload 输出 plannedDate=null 且
        # scheduleState/scheduleDays 为 null。
        planned_raw = row["planned_date"]
        planned_day: date | None = None
        if planned_raw not in (None, ""):
            try:
                planned_day = date.fromisoformat(str(planned_raw))
            except ValueError:
                planned_day = None
        schedule_state: str | None = None
        schedule_days: int | None = None
        if row["status"] != "已完成" and planned_day is not None:
            delta = (planned_day - current_day).days
            if delta < 0:
                schedule_state = "overdue"
                schedule_days = abs(delta)
            elif delta <= 7:
                schedule_state = "due_soon"
                schedule_days = delta
        summary = policy_summaries.get(row["id"])
        if summary is None:
            summary = {
                "mode": "manual",
                "source_type": "tdc",
                "enabled": 0,
                "external_key": None,
                "mapping_json": "{}",
                "sync_state": "idle",
                "last_attempt_at": None,
                "last_success_at": None,
                "last_error_type": None,
                "last_error_message": None,
                "updated_at": row["updated_at"],
                "match_rule_json": None,
            }
        try:
            raw_match_rule = summary.get("match_rule_json")
            aggregate_binding = bool(
                isinstance(raw_match_rule, str)
                and raw_match_rule.strip()
                and json.loads(raw_match_rule).get("aggregate") is True
            )
        except Exception:
            aggregate_binding = False
        form_link = _deliverable_form_link(db, str(row["id"]))
        analysis_link = _deliverable_analysis_link(db, str(row["id"]), analysis_service)
        capabilities = PROJECT_STATUS_SOURCE_CAPABILITIES.get(str(row["id"]), {})
        form_snapshot_driven = bool(capabilities.get("formSnapshotDriven"))
        counts_toward_completion = capabilities.get("countsTowardCompletion") is not False
        editability = project_status_manual_editability(
            summary, deliverable_id=str(row["id"])
        )
        form_summary = (
            form_link.get("summary")
            if isinstance(form_link, dict) and isinstance(form_link.get("summary"), dict)
            else None
        )
        # 展示状态机：mode/enabled/有效快照/syncState 四输入，七态输出。
        # 纯函数提取至 core.project_status_contracts，前后端共用同一口径。
        binding_mode = str(summary["mode"])
        binding_sync_state = str(summary["sync_state"] or "idle")
        analysis_summary = (
            analysis_link.get("summary")
            if isinstance(analysis_link, dict) and isinstance(analysis_link.get("summary"), dict)
            else None
        )
        display_state, display_label, effective_status = deliverable_display_state(
            binding_mode=binding_mode,
            binding_enabled=bool(summary["enabled"]),
            binding_sync_state=binding_sync_state,
            last_success_at=summary.get("last_success_at"),
            analysis_summary=analysis_summary,
            form_summary=form_summary,
            aggregate=aggregate_binding,
            status_baseline=str(row["status"]),
            form_snapshot_driven=form_snapshot_driven,
        )
        # display 三字段仅在数值态（manual/snapshot）填真实值，其余各态
        # 一律 null，防止 total=0 或暂停残留渗入环图与自动隐藏；
        # effectiveStatus 同源保留（node-overview 消费 item.effectiveStatus）。
        if display_state == "snapshot" and (
            analysis_summary or (form_summary if not aggregate_binding else None)
        ):
            source_summary = analysis_summary or form_summary or {}
            source_link = analysis_link if analysis_summary is not None else form_link
            display_total = int(source_summary.get("total") or 0)
            display_completed = int(source_summary.get("completed") or 0)
            display_summary_value: dict[str, Any] | None = {
                "total": display_total,
                "completed": display_completed,
                "incomplete": int(source_summary.get("incomplete") or 0),
                "overdue": int(source_summary.get("overdue") or 0),
                "snapshotAt": source_link.get("snapshotAt") if isinstance(source_link, dict) else None,
            }
            display_progress_value: int | None = (
                min(100, max(0, round(display_completed / display_total * 100)))
                if display_total > 0
                else None
            )
        elif display_state == "manual":
            display_summary_value = None
            display_progress_value = (
                int(row["progress"]) if row["progress"] is not None else None
            )
        else:
            display_summary_value = None
            display_progress_value = None
        display_status_value = (
            effective_status if display_state in ("manual", "snapshot") else None
        )
        deliverables.append(
            {
                "id": row["id"],
                "displayCode": row["display_code"],
                "phaseId": row["phase_id"],
                "name": row["name"],
                "status": row["status"],
                "owner": row["owner"],
                "plannedDate": row["planned_date"],
                "actualDate": actual_date,
                "progressOrDate": actual_date if row["status"] == "已完成" else f'{row["progress"]}%',
                "progress": row["progress"],
                "note": row["remark"],
                "source": row["source"],
                "department": row["department"],
                "stage": row["stage"],
                # binding.mode 为唯一权威：updateMethod 是策略模式的兼容投影。
                "updateMethod": binding_mode,
                "manualEditable": editability["manualEditable"],
                "readOnlyReason": editability["readOnlyReason"],
                "formSnapshotDriven": form_snapshot_driven,
                "countsTowardCompletion": counts_toward_completion,
                # 看板可见性由能力注册表单一来源派生（D1/D4 不进两块看板）。
                # 该字段只影响看板渲染：deliverables 全量字段、
                # 详情页、分析接口、审计与统计分母一律不变。
                "boardVisible": project_status_board_visible(str(row["id"])),
                "tone": _PROJECT_STATUS_TONES[row["status"]],
                "effectiveStatus": effective_status,
                "syncDisplay": {
                    "state": display_state,
                    "label": display_label,
                    "syncState": binding_sync_state,
                    "lastError": summary["last_error_message"],
                    # 仅数值态填真实值，其余各态一律 null（见上方注释）。
                    "displayStatus": display_status_value,
                    "displayProgress": display_progress_value,
                    "displaySummary": display_summary_value,
                },
                "sourceInfo": {
                    "sourceType": capabilities.get("sourceType"),
                    "reportType": capabilities.get("reportType"),
                    "displayName": capabilities.get("displayName"),
                    "syncCapable": bool(capabilities.get("syncCapable")),
                    "manualOnly": bool(capabilities.get("manualOnly")),
                    # 版本化绑定契约与完备性策略由能力注册表下发：前端不再按
                    # reportType/交付物 id 自行判断能力（单一来源）。
                    "supportsRecordSet": capabilities.get("supportsRecordSet") is True,
                    "completenessPolicy": str(
                        capabilities.get("completenessPolicy") or "paged_result"
                    ),
                    "defaultDepartment": capabilities.get("defaultDepartment"),
                    # NCR 官方导出接受的科室代码表（单一来源
                    # services.aras_department_mapping.NCR_SECTION_CODES）；
                    # 非 NCR 交付物为 null。
                    "ncrSectionCodes": (
                        list(NCR_SECTION_CODES)
                        if capabilities.get("reportType") in {"ncr_progress", "ncr_detail"}
                        else None
                    ),
                    # 科室预设（与归集规则同源，用户可编辑）；非 NCR 为 null。
                    "sectionScopePresets": (
                        list(section_scope_presets)
                        if capabilities.get("reportType") in {"ncr_progress", "ncr_detail"}
                        else None
                    ),
                    "syncNote": capabilities.get("syncNote"),
                    "matchFields": [list(field) for field in capabilities.get("matchFields", ())],
                    "evidenceFields": [dict(field) for field in capabilities.get("evidenceFields", ())],
                    "defaultMapping": capabilities.get("defaultMapping") or {},
                    "fieldAliases": capabilities.get("fieldAliases") or {},
                    "fieldSemantics": capabilities.get("fieldSemantics") or {},
                    "archiveJobKey": find_job_key_by_deliverable_id(str(row["id"])),
                },
                "scheduleState": schedule_state,
                "scheduleDays": schedule_days,
                "updatedAt": row["updated_at"],
                "formLink": form_link,
                "analysisLink": analysis_link,
                "updatePolicy": {
                    "mode": summary["mode"],
                    "enabled": bool(summary["enabled"]),
                    "aggregate": aggregate_binding,
                    "sourceType": summary["source_type"],
                    "syncState": summary["sync_state"],
                    "lastAttemptAt": summary["last_attempt_at"],
                    "lastSuccessAt": summary["last_success_at"],
                    "lastErrorType": summary["last_error_type"],
                    "lastErrorMessage": summary["last_error_message"],
                    "updatedAt": summary["updated_at"],
                },
                "associations": _deliverable_associations(
                    str(row["id"]), archive_jobs_by_key
                ),
            }
        )

    # 汇总口径：数值态（manual/snapshot）计入完成与风险；
    # paused/待同步类状态单列 pendingCount，不计完成也不计业务风险
    # （同步不写 status/progress，paused 无可信进度值——GPT 终审 P1）。
    # countsTowardCompletion=False 的交付物（外部快照驱动 D6-D8，仅展示
    # 参考）不进入价值态汇总——总体进度分母仍为 D1-D5。
    value_states = {"manual", "snapshot"}
    counting_deliverables = [
        item for item in deliverables if item["countsTowardCompletion"]
    ]
    completed_count = sum(
        1 for item in counting_deliverables
        if item["syncDisplay"]["state"] in value_states
        and item["effectiveStatus"] == "已完成"
    )
    pending_count = sum(
        1 for item in counting_deliverables
        if item["syncDisplay"]["state"] not in value_states
    )
    risk_count = sum(
        1 for item in counting_deliverables
        if item["syncDisplay"]["state"] in value_states
        and (
            item["effectiveStatus"] == "已逾期"
            or (item["syncDisplay"]["state"] != "snapshot" and item["scheduleState"] == "overdue")
        )
    )
    overall_progress = int(phase_row["overall_progress"])
    planned_progress = int(phase_row["planned_progress"])
    overdue = next(
        (
            item
            for item in counting_deliverables
            if item["syncDisplay"]["state"] in value_states
            and (
                item["effectiveStatus"] == "已逾期"
                or (item["syncDisplay"]["state"] != "snapshot" and item["scheduleState"] == "overdue")
            )
        ),
        None,
    )
    risk_text = "无"
    if overdue:
        if overdue["scheduleState"] == "overdue" and overdue["scheduleDays"] is not None:
            risk_text = f'{overdue["name"]}已逾期 {overdue["scheduleDays"]} 天'
        elif overdue["syncDisplay"]["state"] == "snapshot":
            risk_text = f'{overdue["name"]}的快照存在逾期项'
        else:
            note = str(overdue["note"])
            risk_text = f'{overdue["name"]}已{note}' if note.startswith("逾期") else f'{overdue["name"]}：{note}'
    start_date = str(phase_row["start_date"])
    end_date = str(phase_row["end_date"])
    start_month = date.fromisoformat(start_date).replace(day=1)
    end_month = date.fromisoformat(end_date).replace(day=1)
    months = []
    current = start_month
    while current <= end_month:
        months.append(current.strftime("%Y.%m"))
        current = date(current.year + (current.month == 12), 1 if current.month == 12 else current.month + 1, 1)
    updated_at = str(phase_row["updated_at"])
    return {
        "phase": {
            "id": phase_row["id"],
            "displayName": phase_row["display_name"],
            "status": phase_row["status"],
            "startDate": start_date,
            "endDate": end_date,
            "today": current_day.isoformat(),
            "updatedAt": updated_at,
            "overallProgress": overall_progress,
            "completedCount": completed_count,
            "pendingCount": pending_count,
            "totalCount": len(deliverables),
            "riskCount": risk_count,
        },
        "months": months,
        "milestones": [
            {
                "id": row["id"],
                "name": row["name"],
                "date": row["milestone_date"],
                "status": milestone_display_status(
                    row["status"], row["milestone_date"], current_day
                ),
                "type": row["type"],
                "sortOrder": row["sort_order"],
            }
            for row in milestone_rows
        ],
        "currentStage": current_stage_label(
            [
                {"name": row["name"], "date": row["milestone_date"]}
                for row in milestone_rows
            ],
            current_day,
        ),
        "deliverables": deliverables,
        "summary": {
            "overall": f"{overall_progress}%",
            "planned": f"{planned_progress}%",
            "variance": f"{overall_progress - planned_progress}%",
            "risk": risk_text,
            "snapshot": updated_at,
        },
    }


def _project_status_validation_error(fields: dict[str, str]):
    response = jsonify(
        {
            "ok": False,
            "error": {
                "type": "ValidationError",
                "message": "请修正标记的字段",
                "fields": fields,
            },
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response, 422


def _validate_project_status_phase(
    payload: Mapping[str, Any],
) -> tuple[dict[str, object], dict[str, str]]:
    errors: dict[str, str] = {}
    unknown = set(payload) - {"displayName", "status", "startDate", "endDate", "updatedAt"}
    if unknown:
        errors["request"] = "包含不允许修改的字段"

    display_name = payload.get("displayName")
    status = payload.get("status")
    start_text = payload.get("startDate")
    end_text = payload.get("endDate")

    if not isinstance(display_name, str) or not display_name.strip():
        errors["displayName"] = "主计划名称不能为空"
    elif len(display_name.strip()) > 120:
        errors["displayName"] = "主计划名称不能超过 120 个字符"

    allowed_statuses = {"未开始", "进行中", "已完成", "暂停"}
    if status not in allowed_statuses:
        errors["status"] = "阶段状态无效"

    parsed_start: date | None = None
    parsed_end: date | None = None
    for field_name, raw_value in (("startDate", start_text), ("endDate", end_text)):
        if not isinstance(raw_value, str):
            errors[field_name] = "必须使用 YYYY-MM-DD 日期"
            continue
        try:
            parsed = date.fromisoformat(raw_value)
        except ValueError:
            errors[field_name] = "必须使用 YYYY-MM-DD 日期"
            continue
        if field_name == "startDate":
            parsed_start = parsed
        else:
            parsed_end = parsed
    if parsed_start is not None and parsed_end is not None and parsed_start > parsed_end:
        errors["endDate"] = "计划完成日期不能早于开始日期"

    values = {
        "display_name": display_name.strip() if isinstance(display_name, str) else "",
        "status": status,
        "start_date": start_text,
        "end_date": end_text,
    }
    return values, errors


def _validate_project_status_update(
    payload: dict[str, Any], current: dict[str, Any], phase: dict[str, Any]
) -> tuple[dict[str, object], dict[str, str]]:
    allowed = {"status", "owner", "plannedDate", "actualDate", "progress", "note", "updatedAt"}
    fields: dict[str, str] = {}
    unknown = set(payload) - allowed
    if unknown:
        fields["request"] = "包含不允许修改的字段"

    status = payload.get("status", current["status"])
    owner = payload.get("owner", current["owner"])
    planned_date = payload.get("plannedDate", current["plannedDate"])
    actual_date = payload.get("actualDate", current.get("actualDate"))
    progress = payload.get("progress", current["progress"])
    note = payload.get("note", current["note"])

    if not isinstance(status, str) or status not in _PROJECT_STATUS_VALUES:
        fields["status"] = "请选择有效状态"
    if not isinstance(owner, str) or not owner.strip():
        fields["owner"] = "负责人不能为空"
    elif len(owner.strip()) > 100:
        fields["owner"] = "负责人不能超过 100 个字符"
    if not isinstance(note, str):
        fields["note"] = "风险与备注必须是文本"
    elif len(note) > 1000:
        fields["note"] = "风险与备注不能超过 1000 个字符"
    if isinstance(progress, bool) or not isinstance(progress, int) or not 0 <= progress <= 100:
        fields["progress"] = "当前进度必须是 0 至 100 的整数"

    parsed_planned = None
    if not isinstance(planned_date, str) or not planned_date:
        fields["plannedDate"] = "计划完成日期不能为空"
    else:
        try:
            parsed_planned = date.fromisoformat(planned_date)
        except ValueError:
            fields["plannedDate"] = "计划完成日期格式无效"
    if parsed_planned and parsed_planned < date.fromisoformat(str(phase["startDate"])):
        fields["plannedDate"] = "计划完成日期不能早于阶段开始日期"

    if actual_date in (None, ""):
        actual_date = None
    elif not isinstance(actual_date, str):
        fields["actualDate"] = "实际完成日期格式无效"
    else:
        try:
            if date.fromisoformat(actual_date) < date.fromisoformat(str(phase["startDate"])):
                fields["actualDate"] = "实际完成日期不能早于阶段开始日期"
        except ValueError:
            fields["actualDate"] = "实际完成日期格式无效"

    if status == "已完成":
        if progress != 100:
            fields["progress"] = "已完成交付物的进度必须为 100"
        if actual_date is None:
            fields["actualDate"] = "已完成交付物必须填写实际完成日期"
    elif actual_date is not None:
        fields["actualDate"] = "非完成状态不能填写实际完成日期"

    values: dict[str, object] = {
        "status": status,
        "owner": owner.strip() if isinstance(owner, str) else owner,
        "planned_date": planned_date,
        "actual_date": actual_date,
        "progress": progress,
        "remark": note,
    }
    return values, fields


def _validate_project_status_milestones(
    payload: dict[str, Any], project_status: dict[str, Any]
) -> tuple[list[dict[str, object]], dict[str, str]]:
    """校验主计划草稿并转换为数据库字段。"""
    raw_items = payload.get("milestones")
    if not isinstance(raw_items, list):
        return [], {"milestones": "主计划节点数据无效"}
    if not raw_items:
        # 删除全部节点后保存视为"恢复默认模板"：自动生成一套默认的
        # 空日期节点（用户 2026-09-06 确认口径），不再返回 422。
        return (
            [
                {
                    "id": None,
                    "name": name,
                    "date": None,
                    "status": "未开始",
                    "type": "planned",
                    "sort_order": index,
                }
                for index, (name, *_rest) in enumerate(
                    PROJECT_STATUS_MILESTONE_TEMPLATE, start=1
                )
            ],
            {},
        )
    errors: dict[str, str] = {}
    normalized: list[dict[str, object]] = []
    names: set[str] = set()
    ids: set[int] = set()
    phase = project_status["phase"]
    start_date = date.fromisoformat(str(phase["startDate"]))
    end_date = date.fromisoformat(str(phase["endDate"]))
    status_type = {"已完成": "done", "进行中": "current", "未开始": "planned", "已超期": "planned"}

    for index, raw in enumerate(raw_items):
        prefix = f"milestones.{index}"
        if not isinstance(raw, dict):
            errors[prefix] = "节点必须是对象"
            continue
        allowed = {"id", "name", "date", "status", "type", "sortOrder"}
        if set(raw) - allowed:
            errors[prefix] = "节点包含不允许的字段"
        raw_id = raw.get("id")
        milestone_id: int | None = None
        if raw_id is not None:
            if isinstance(raw_id, bool) or not isinstance(raw_id, int) or raw_id <= 0:
                errors[f"{prefix}.id"] = "节点 ID 无效"
            elif raw_id in ids:
                errors[f"{prefix}.id"] = "节点 ID 重复"
            else:
                milestone_id = raw_id
                ids.add(raw_id)

        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            errors[f"{prefix}.name"] = "节点名称不能为空"
            clean_name = ""
        else:
            clean_name = name.strip()
            if len(clean_name) > 100:
                errors[f"{prefix}.name"] = "节点名称不能超过 100 个字符"
            elif clean_name in names:
                errors[f"{prefix}.name"] = "同一阶段的节点名称不能重复"
            names.add(clean_name)

        requested_status = raw.get("status")
        if not isinstance(requested_status, str) or requested_status not in MILESTONE_STATUSES:
            legacy_type = raw.get("type")
            requested_status = {"done": "已完成", "current": "进行中", "planned": "未开始"}.get(
                str(legacy_type), "未开始"
            )
        if requested_status == "已超期":
            requested_status = "未开始"
        node_type = status_type[requested_status]

        date_text = raw.get("date")
        parsed_date = None
        if isinstance(date_text, str) and date_text.strip():
            date_text = date_text.strip()
            try:
                parsed_date = date.fromisoformat(date_text)
            except ValueError:
                errors[f"{prefix}.date"] = "节点日期格式无效"
        else:
            # 空日期=待排期：仅允许"未开始"节点；排期后按阶段区间校验。
            date_text = ""
            if requested_status != "未开始":
                errors[f"{prefix}.date"] = "空日期节点状态必须为未开始"
        if parsed_date and not start_date <= parsed_date <= end_date:
            errors[f"{prefix}.date"] = "节点日期必须位于阶段周期内"

        normalized.append(
            {
                "id": milestone_id,
                "name": clean_name,
                "date": date_text or None,
                "status": requested_status,
                "type": node_type,
                "sort_order": index + 1,
            }
        )

    return normalized, errors


_NCR_PREVIEW_MAX_ROWS = 500


def _ncr_preview_requested(payload: Mapping[str, Any]) -> bool:
    value = payload.get("preview")
    return value is True or (isinstance(value, str) and value.strip().lower() in {"1", "true", "yes"})


def _ncr_table_payload(
    client: ArasCrawlerClient,
    result: Any,
    report_type: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Return an empty contract or a bounded preview of the official XLSX."""
    if not _ncr_preview_requested(payload):
        return {
            **table_payload(report_type, []),
            "count": 0,
            "previewAvailable": False,
        }

    requested_rows = _positive_int(payload.get("preview_rows"), _NCR_PREVIEW_MAX_ROWS)
    preview_rows = min(requested_rows, _NCR_PREVIEW_MAX_ROWS)
    temp_dir = Path(tempfile.mkdtemp(prefix=f"aras_{report_type}_preview_"))
    try:
        if report_type == "ncr_progress":
            saved = client.download_ncr_progress_file(result, temp_dir)
            header_count = 2
        else:
            saved = client.download_ncr_detail_file(result.file_name, temp_dir)
            header_count = 5
        workbook = read_xlsx_preview(saved, max_rows=header_count + preview_rows)
        data_rows = workbook.rows[header_count:]
        table = matrix_payload(report_type, data_rows)
        return {
            **table,
            "count": len(data_rows),
            "previewAvailable": True,
            "preview": {
                "sheetName": workbook.sheet_name,
                "sheetNames": list(workbook.sheet_names),
                "truncated": workbook.truncated,
                "maxRows": preview_rows,
            },
        }
    except XLSXPreviewError:
        raise
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _aras_error_response(
    exc: Exception,
    client: ArasCrawlerClient | None,
    operation: str,
):
    if isinstance(exc, _ArasRequestError):
        code = "unauthenticated" if exc.status_code == 401 else None
        return _json_error(
            exc.status_code,
            exc.error_type,
            _sanitize_error_message(exc),
            exc.diagnostic_path,
            code=code,
            diagnostic=getattr(exc, "diagnostic", None),
        )
    diagnostic_path = _save_aras_client_diagnostic(client, exc)
    if isinstance(exc, ArasAuthenticationError):
        return _json_error(
            401,
            "AuthenticationError",
            "ARAS 会话未认证或已过期，请在设置中重新登录",
            diagnostic_path,
            code="unauthenticated",
        )
    if isinstance(exc, (WinHTTPTimeoutError, WinHTTPError, ConnectionError, TimeoutError, OSError)):
        return _json_error(
            503,
            "ServiceUnavailable",
            "ARAS 服务当前不可用，请检查网络或 VPN 后重试",
            diagnostic_path,
            code="service_unavailable",
        )
    if isinstance(exc, ArasNcrExportContractError):
        # 官方 NCR 导出方法返回 200 但没有文件引用：不是网关/网络问题，也不宜
        # 归为通用 query_failed。消息带无泄漏结构签名；正文只经既有诊断管道落盘。
        return _json_error(
            502,
            "ArasNcrExportContractError",
            (
                "官方 NCR 导出方法未返回文件引用（可能无匹配数据、导出参数不被接受"
                f"或响应结构不符）；响应结构签名：{exc.signature}。诊断文件已生成，"
                "若持续失败请回传该诊断文件（含脱敏的上游原始响应）以便进一步定位。"
            ),
            diagnostic_path,
            code="ncr_export_no_file",
        )
    if isinstance(exc, ArasCrawlerError):
        service_unavailable = bool(re.search(r"\bAras HTTP 5\d{2}\b", str(exc)))
        return _json_error(
            503 if service_unavailable else 502,
            "ArasCrawlerError",
            (
                "ARAS 服务当前不可用，请检查网络或 VPN 后重试"
                if service_unavailable
                else _sanitize_error_message(exc)
            ),
            diagnostic_path,
            code="service_unavailable" if service_unavailable else "query_failed",
        )
    if isinstance(exc, XLSXPreviewError):
        return _json_error(502, "ArasCrawlerError", _sanitize_error_message(exc), diagnostic_path)
    if isinstance(exc, ValueError):
        return _json_error(
            400,
            "ValidationError",
            _sanitize_error_message(exc),
            diagnostic_path,
        )
    logger.warning("Aras %s API failed: %s", operation, type(exc).__name__)
    return _json_error(
        500,
        type(exc).__name__,
        _sanitize_error_message(exc),
        diagnostic_path,
    )


def _tdc_error_response(exc: Exception, report_type: str, operation: str):
    if isinstance(exc, _TDCRequestError):
        return _json_error(
            exc.status_code,
            exc.error_type,
            _sanitize_error_message(exc),
            exc.diagnostic_path,
            diagnostic=getattr(exc, "diagnostic", None),
        )
    if isinstance(exc, TDCAuthError):
        return _json_error(401, "AuthenticationError", _sanitize_error_message(exc), getattr(exc, "diagnostic_path", None))
    if isinstance(exc, XLSXPreviewError):
        return _json_error(502, "TDCCrawlerError", _sanitize_error_message(exc))
    if isinstance(exc, ValueError):
        return _json_error(400, "ValidationError", _sanitize_error_message(exc))
    if isinstance(exc, TDCCrawlerError):
        status = 400 if exc.stage == "contract-validation" else 502
        diagnostic = exc.safe_diagnostic()
        # 有界重试后仍失败的上游 5xx/429 是"暂时不可用"，不是配置错误：
        # 主文案给出可重试语义并保留 request_id（现场与诊断关联的唯一抓手）；
        # 上游路径等运维细节在下发的 diagnostic 与诊断录制里，不再塞进用户文案。
        if diagnostic.get("retryable") is True:
            message = (
                f"TDC 暂时不可用（{diagnostic.get('upstreamHttpStatus')}），请稍后重试；"
                f"request_id={diagnostic.get('requestId', '')}"
            )
        else:
            message = f"{_sanitize_error_message(exc)}; {exc.safe_diagnostic_message()}"
        return _json_error(
            status,
            "TDCCrawlerError",
            message,
            diagnostic=diagnostic,
        )
    logger.warning("TDC %s %s API failed: %s", report_type, operation, type(exc).__name__)
    return _json_error(500, type(exc).__name__, "Unexpected server error")


def _tdc_document_no(payload: Mapping[str, Any]) -> str | None:
    """流水单号（documentNo）。它不是 TDC 查询参数，只能本地精确匹配。

    缺省或纯空白 = 不启用本地匹配；类型非法 fail-closed。
    """
    value = payload.get("document_no")
    if value is None:
        return None
    if not isinstance(value, str):
        raise _TDCRequestError("document_no must be a string")
    return value.strip() or None


def _tdc_document_nos(payload: Mapping[str, Any]) -> list[str] | None:
    """流水单号（可多值，分隔符约定同交付物明细搜索：空格/逗号/分号/顿号/换行）。

    缺省 = 不启用本地匹配；去重保序，上限沿用 form_search.MAX_TERMS（超限部分
    被 parse_terms 丢弃，这里按分隔符预扫描发现超限即 fail-closed），全空白也
    fail-closed——绝不静默截断或退化成无过滤查询。
    """
    raw = _tdc_document_no(payload)
    if raw is None:
        return None
    if len(_FORM_TERM_SEPARATORS.split(raw.strip())) > MAX_DOCUMENT_NOS:
        raise _TDCRequestError(f"流水单号一次最多 {MAX_DOCUMENT_NOS} 个，请分批查询")
    serials = parse_form_terms(raw)
    if not serials:
        raise _TDCRequestError("document_no 不能为空")
    return serials


def _tdc_data_model_serial_query(
    payload: Mapping[str, Any],
    filters: TDCDataModelFilters,
    allowed_hosts: Sequence[str],
    document_nos: list[str],
):
    """带流水单号的数模查询：全量翻页 → 本地精确匹配（A′ 路线）。

    单个流水单号保持既有簿记形状（``requested`` 为字符串）；多个流水单号走
    集合匹配，簿记含 ``found``/``missing`` 明细（S8：missing 只展示不删除）。
    fail-closed：抓取不完整时返回 200 + 空行 + ``serialMatch.complete=false``
    且 ``reason="crawl_incomplete"``——语义是"无法判定"，不是"未找到"；只有
    抓取完整且匹配 0 行才是真正的"未找到"。
    """
    page_size = _tdc_positive_int(payload.get("page_size"), "page_size", 50, _TDC_PAGE_SIZE_MAX)
    max_pages = _tdc_positive_int(payload.get("max_pages"), "max_pages", 100, _TDC_MAX_PAGES_MAX)
    max_records = _tdc_positive_int(
        payload.get("max_records"), "max_records", 10000, _TDC_MAX_RECORDS_MAX
    )
    client: TDCCrawlerClient | None = None
    try:
        client = _build_tdc_client_from_payload(payload, allowed_hosts)
        crawl_result = client.crawl_data_model_all(
            filters,
            page_size=page_size,
            max_pages=max_pages,
            max_records=max_records,
        )
    finally:
        _close_owned_tdc_client(client)
    scanned_pages = int(getattr(crawl_result, "fetched_pages", 0) or 0)
    scanned = len(crawl_result.rows)
    if not _mapping_result_is_complete(crawl_result):
        data = _tdc_result_data(
            replace(crawl_result, rows=[], unique_count=0, duplicate_count=0)
        )
        data["serialMatch"] = {
            "requested": document_nos if len(document_nos) > 1 else document_nos[0],
            "scanned": scanned,
            "matched": 0,
            "scannedPages": scanned_pages,
            "complete": False,
            "reason": "crawl_incomplete",
        }
        return jsonify({"ok": True, "data": data})
    if len(document_nos) == 1:
        matched, bookkeeping = match_serial(crawl_result.rows, document_nos[0])
        data = _tdc_result_data(
            replace(crawl_result, rows=matched, unique_count=len(matched), duplicate_count=0)
        )
        data["serialMatch"] = {
            "requested": bookkeeping["serial"],
            "scanned": bookkeeping["scanned"],
            "matched": bookkeeping["matched"],
            "scannedPages": scanned_pages,
            "complete": True,
        }
        return jsonify({"ok": True, "data": data})
    matched, bookkeeping = match_serials(crawl_result.rows, document_nos)
    data = _tdc_result_data(
        replace(crawl_result, rows=matched, unique_count=len(matched), duplicate_count=0)
    )
    data["serialMatch"] = {
        "requested": bookkeeping["requested"],
        "found": bookkeeping["found"],
        "missing": bookkeeping["missing"],
        "scanned": bookkeeping["scanned"],
        "matched": bookkeeping["matched"],
        "scannedPages": scanned_pages,
        "complete": True,
    }
    return jsonify({"ok": True, "data": data})


def _tdc_report_query(
    report_type: str,
    filter_builder,
    allowed_names: tuple[str, ...],
    allowed_hosts: Sequence[str],
):
    payload, error_response = _request_payload()
    if error_response:
        return error_response
    assert payload is not None
    client: TDCCrawlerClient | None = None
    try:
        filters = filter_builder(_tdc_filters_from_payload(payload, allowed_names))
        document_nos = _tdc_document_nos(payload) if report_type == "data_model" else None
        page = _tdc_positive_int(payload.get("page"), "page", 1, _TDC_PAGE_MAX)
        page_size = _tdc_positive_int(payload.get("page_size"), "page_size", 50, _TDC_PAGE_SIZE_MAX)
        preview_source = _tdc_preview_source(payload)
        if document_nos is not None:
            # 流水单号必须走全量翻页 + 本地精确匹配；官方导出预览是另一种数据源，
            # 静默忽略 document_no 会让用户拿到"全部行"当成匹配结果。
            if preview_source != "list_endpoint":
                raise _TDCRequestError(
                    "document_no 本地匹配只支持 list_endpoint 数据源"
                )
            return _tdc_data_model_serial_query(payload, filters, allowed_hosts, document_nos)
        if preview_source == "official_export":
            preview_builder = (
                _tdc_official_data_model_preview
                if report_type == "data_model"
                else _tdc_official_sor_preview
            )
            data = preview_builder(
                payload,
                filters,
                allowed_hosts,
                operation="query",
                page=page,
                page_size=page_size,
            )
            return jsonify({"ok": True, "data": data})
        client = _build_tdc_client_from_payload(payload, allowed_hosts)
        result = _tdc_query(client, report_type, filters, page=page, page_size=page_size)
        return jsonify({"ok": True, "data": _tdc_result_data(result)})
    except Exception as exc:
        return _tdc_error_response(exc, report_type, "query")
    finally:
        _close_owned_tdc_client(client)


#: 后台任务结果 JSON 工件的大小上限（与同步响应体量级一致的安全上限）。
_TASK_RESULT_MAX_BYTES = 64 * 1024 * 1024


def _submit_background_task(
    runner: Any,
    task_type: str,
    source: str,
    params: Mapping[str, Any],
    worker_fn: Callable[[Any], None],
    *,
    error_context: str,
):
    """提交后台任务并返回 202 Accepted + task_id 契约响应。"""
    if runner is None:
        return _json_error(503, "TaskEngineUnavailable", "后台任务引擎未初始化")
    try:
        tid = runner.submit_task(task_type, source, params, worker_fn)
    except Exception:
        logger.exception("Failed to submit background task (%s)", error_context)
        return _json_error(500, "ServerError", "后台任务提交失败")
    response = jsonify(
        {
            "ok": True,
            "data": {
                "taskId": tid,
                "status": "queued",
                "category": "crawl",
                "source": source,
                "statusUrl": f"/api/tasks/{tid}",
                "resultUrl": f"/api/tasks/{tid}/result",
            },
        }
    )
    response.status_code = 202
    response.headers["Cache-Control"] = "no-store"
    return response


def _crawl_runner_from_request() -> Any:
    return current_app.extensions.get("crawl_task_runner")


def _tdc_report_crawl(
    report_type: str,
    filter_builder,
    allowed_names: tuple[str, ...],
    allowed_hosts: Sequence[str],
):
    payload, error_response = _request_payload()
    if error_response:
        return error_response
    assert payload is not None
    try:
        filters = filter_builder(_tdc_filters_from_payload(payload, allowed_names))
        page_size = _tdc_positive_int(payload.get("page_size"), "page_size", 50, _TDC_PAGE_SIZE_MAX)
        max_pages = _tdc_positive_int(payload.get("max_pages"), "max_pages", 100, _TDC_MAX_PAGES_MAX)
        max_records = _tdc_positive_int(
            payload.get("max_records"), "max_records", 10000, _TDC_MAX_RECORDS_MAX
        )
        preview_source = _tdc_preview_source(payload)
    except Exception as exc:
        return _tdc_error_response(exc, report_type, "crawl-all")
    if preview_source == "official_export":
        # 官方导出预览为本地解析路径，维持同步 200 契约（交付物控制台依赖）。
        preview_builder = (
            _tdc_official_data_model_preview
            if report_type == "data_model"
            else _tdc_official_sor_preview
        )
        try:
            data = preview_builder(
                payload,
                filters,
                allowed_hosts,
                operation="crawl_all",
                page_size=page_size,
                max_records=max_records,
            )
            return jsonify({"ok": True, "data": data})
        except Exception as exc:
            return _tdc_error_response(exc, report_type, "crawl-all")

    # 网络全量抓取路径转换为后台任务（202 Accepted + task_id）。
    session, gate_error = _async_session_gate("tdc", payload)
    if gate_error is not None:
        return gate_error
    try:
        base_url = str(payload["base_url"]).strip()
        _validate_tdc_base_url(base_url, allowed_hosts, require_https=False)
    except Exception as exc:
        return _tdc_error_response(exc, report_type, "crawl-all")

    def worker(ctx):
        client = TDCCrawlerClient(base_url, session=session, timeout=30.0)
        # 会话为共享统一域会话：worker 线程内禁止关闭（无 app 上下文无法识别）。
        result = _tdc_crawl(
            client,
            report_type,
            filters,
            page_size=page_size,
            max_pages=max_pages,
            max_records=max_records,
            should_stop=lambda: ctx.is_cancelled,
            on_page=lambda page_no, rows_so_far: ctx.update_progress(
                current=rows_so_far,
                total=max_records,
                stage=f"TDC {report_type} 全量抓取第 {page_no} 页",
            ),
        )
        data = _tdc_result_data(result)
        artifact = ctx.downloads_dir / f"{ctx.task_id}.result.json"
        artifact.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        ctx.set_artifact(artifact)
        ctx.update_progress(percent=100, stage="全量抓取完成")

    params = {
        "base_url": base_url,
        "filters": asdict(filters),
        "page_size": page_size,
        "max_pages": max_pages,
        "max_records": max_records,
    }
    return _submit_background_task(
        _crawl_runner_from_request(),
        f"tdc_{report_type}_crawl",
        "tdc",
        params,
        worker,
        error_context="TDC crawl-all",
    )


def _tdc_report_export(
    report_type: str,
    filter_builder,
    allowed_names: tuple[str, ...],
    allowed_hosts: Sequence[str],
):
    payload, error_response = _request_payload()
    if error_response:
        return error_response
    assert payload is not None
    try:
        file_name = _tdc_file_name(payload.get("file_name"))
        filters = filter_builder(_tdc_filters_from_payload(payload, allowed_names))
    except Exception as exc:
        return _tdc_error_response(exc, report_type, "export")

    # 大导出转换为后台任务：官方工作簿下载 + XLSX 落盘至 data/downloads/，
    # 由统一任务抽屉下载（7 天自动轮换清理）。
    session, gate_error = _async_session_gate("tdc", payload)
    if gate_error is not None:
        return gate_error
    try:
        base_url = str(payload["base_url"]).strip()
        _validate_tdc_base_url(base_url, allowed_hosts, require_https=False)
    except Exception as exc:
        return _tdc_error_response(exc, report_type, "export")

    def worker(ctx):
        # 会话为共享统一域会话：worker 线程内禁止关闭（无 app 上下文无法识别）。
        client = TDCCrawlerClient(
            base_url, session=session, timeout=30.0, output_dir=ctx.downloads_dir
        )
        ctx.update_progress(stage=f"正在生成 TDC {report_type} 官方导出")
        user_name = file_name or f"tdc_{report_type}.xlsx"
        unique_name = f"{Path(user_name).stem}_{ctx.task_id}.xlsx"
        result = _tdc_export(client, report_type, filters, file_name=unique_name)
        out_path = Path(result.path).resolve()
        if not out_path.is_relative_to(ctx.downloads_dir.resolve()):
            raise TDCCrawlerError(
                "TDC export produced a path outside the download directory",
                stage="export-validation",
            )
        ctx.set_artifact(out_path)
        ctx.update_progress(percent=100, stage="导出完成")

    params = {
        "base_url": base_url,
        "filters": asdict(filters),
        "file_name": file_name,
    }
    return _submit_background_task(
        _crawl_runner_from_request(),
        f"tdc_{report_type}_export",
        "tdc",
        params,
        worker,
        error_context="TDC export",
    )


def create_app(
    allowed_hosts: Sequence[str] | None = None,
    tdc_allowed_hosts: Sequence[str] | None = None,
    excel_roots: Mapping[str, Path | str] | None = None,
    excel_repository: ExcelTaskRepository | None = None,
    excel_worker_controller: ExcelWorkerController | ExcelWorkerProcessController | None = None,
    excel_worker_mode: str = "process",
    excel_clock: Callable[[], datetime] | None = None,
    project_status_clock: Callable[[], date] | None = None,
    archive_store: ArchiveStore | None = None,
    plugin_dirs: Sequence[Path] | None = None,
    plugin_only: Sequence[str] | None = None,
) -> Flask:
    """Flask 应用工厂。

    `allowed_hosts` 覆盖 Aras 路由的主机 allowlist（默认仅 ecm.sgmw.com.cn）；
    `tdc_allowed_hosts` 覆盖 TDC 路由的主机 allowlist（默认仅 tdc.sgmw.com.cn）；
    localhost/测试 host 也可在创建后通过对应 app.config 键注入。
    `plugin_dirs` 覆盖插件搜索目录（默认源码 `plugins/`、冻结包 exe 同级 `plugins/`）；
    `plugin_only` 只加载指定 id 的插件（单插件沙箱）。
    """
    if getattr(sys, "frozen", False):
        base_dir = Path(str(getattr(sys, "_MEIPASS"))) / "web"
    else:
        base_dir = Path(__file__).resolve().parent

    app = Flask(
        __name__,
        template_folder=str(base_dir / "templates"),
        static_folder=str(base_dir / "static"),
    )
    app.config["ARAS_ALLOWED_HOSTS"] = (
        tuple(allowed_hosts) if allowed_hosts is not None else _DEFAULT_ARAS_ALLOWED_HOSTS
    )
    app.config["TDC_ALLOWED_HOSTS"] = (
        tuple(tdc_allowed_hosts) if tdc_allowed_hosts is not None else _DEFAULT_TDC_ALLOWED_HOSTS
    )

    version_info = get_app_version_info()
    app.config["APP_VERSION_INFO"] = version_info
    app.config["APP_VERSION"] = version_info.get("displayVersion", "开发工作区")
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
    app.before_request(_enforce_local_web_access)

    @app.errorhandler(413)
    @app.errorhandler(RequestEntityTooLarge)
    def _request_entity_too_large(error=None):
        return _json_error(413, "PayloadTooLarge", "请求体超过大小限制 (最大 16MB)")

    # DatabaseManager 实例化一次，init_database 只在启动时调用
    db = DatabaseManager()
    db.init_database()
    update_service = ProjectStatusUpdateService(db)
    discovery_service = MappingDiscoveryService(db)
    analytics_service = ProjectStatusAnalyticsService(db)
    deliverable_analysis_service = ProjectStatusDeliverableAnalysisService(
        db,
        clock=project_status_clock,
    )
    deliverable_form_service = DeliverableFormAnalysisService(db)
    section_rollup_store = SectionRollupStore(db)
    app.extensions["deliverable_analysis"] = deliverable_analysis_service

    def current_project_status(phase_id: str) -> dict[str, Any] | None:
        return _project_status_payload(
            db,
            phase_id,
            today=project_status_clock() if project_status_clock else None,
            analysis_service=deliverable_analysis_service,
        )

    settings_store = SettingsStore(db)
    domain_sessions = DomainSessionRegistry()
    credential_vault = WindowsDPAPICredentialVault(app_root() / "data" / "domain-credential.dpapi")
    tdc_export_cache = TDCExportCache()
    archive_admin_service = (
        ScheduledArchiveAdminService(db, archive_store=archive_store)
        if archive_store is not None
        else ScheduledArchiveAdminService(db)
    )
    archive_admin_service.set_credential_provider(DPAPICredentialProvider(credential_vault))
    app.extensions["scheduled_archive_admin"] = archive_admin_service
    app.extensions["settings_store"] = settings_store
    app.extensions["domain_sessions"] = domain_sessions
    from core.ewo_export_jobs import EWOExportJobs
    from services.ewo_enrichment import EWOEnrichment
    from web.ewo_enrichment import register_ewo_enrichment

    ewo_enrichment = EWOEnrichment(
        EWOExportJobs(db.db_path), Path(db.db_path).parent / 'ewo-downloads'
    )
    app.extensions["ewo_enrichment"] = ewo_enrichment
    register_ewo_enrichment(app, ewo_enrichment, domain_sessions, _local_web_mutation_error)

    from services.crawl_task_runner import CrawlTaskRunner, prune_old_artifacts
    crawl_downloads_dir = Path(db.db_path).parent / "downloads"
    crawl_task_runner = CrawlTaskRunner(db, downloads_dir=crawl_downloads_dir)
    swept_tasks = crawl_task_runner.startup_sweep()
    if swept_tasks > 0:
        logger.info("Crawl tasks startup sweep: %d orphan tasks marked interrupted", swept_tasks)
    pruned_artifacts = prune_old_artifacts(crawl_downloads_dir)
    if pruned_artifacts > 0:
        logger.info("Startup artifact pruning: %d expired files removed", pruned_artifacts)
    app.extensions["crawl_task_runner"] = crawl_task_runner
    app.extensions["domain_credential_vault"] = credential_vault
    app.extensions["tdc_export_cache"] = tdc_export_cache
    app.extensions["deliverable_form_analysis"] = deliverable_form_service
    if excel_roots is not None and excel_repository is not None:
        raise ValueError("provide excel_roots or excel_repository, not both")
    if excel_repository is None and excel_roots is not None:
        excel_repository = ExcelTaskRepository(db, ApprovedExcelRoots(excel_roots))
    excel_admin_service = (
        ExcelTaskAdminService(excel_repository, clock=excel_clock)
        if excel_repository is not None
        else None
    )
    app.extensions["excel_task_admin"] = excel_admin_service
    if excel_worker_controller is None and excel_repository is not None:
        if excel_worker_mode == "process":
            excel_worker_controller = ExcelWorkerProcessController(excel_repository)
        elif excel_worker_mode == "in_process":
            excel_worker_controller = ExcelWorkerController(lambda: ExcelTaskWorker(excel_repository))
        else:
            raise ValueError("excel_worker_mode must be 'process' or 'in_process'")
    app.extensions["excel_worker_controller"] = excel_worker_controller

    @app.route("/")
    def index():
        return render_template(
            "dashboard.html",
            app_version=app.config.get("APP_VERSION", "开发工作区"),
        )

    @app.get("/favicon.ico")
    def favicon():
        return "", 204

    @app.get("/api/version")
    def api_version():
        info = app.config.get("APP_VERSION_INFO") or get_app_version_info()
        response = jsonify({"ok": True, "data": info})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.route("/api/overview")
    def api_overview():
        try:
            data = _query_overview(db)
            return jsonify(data)
        except Exception as e:
            logger.exception("api/overview 查询失败")
            return jsonify({"error": str(e)}), 500

    @app.get("/api/excel-roots")
    def api_excel_roots_list():
        if excel_admin_service is None:
            return _json_error(503, "NotConfigured", "Excel task roots are not configured")
        try:
            data = excel_admin_service.list_roots()
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception:
            logger.exception("Excel roots list failed")
            return _json_error(500, "ServerError", "Excel roots query failed")

    @app.post("/api/excel-tasks")
    def api_excel_tasks_create():
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        if excel_admin_service is None:
            return _json_error(503, "NotConfigured", "Excel task roots are not configured")
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _json_error(400, "ValidationError", "JSON object body is required")
        try:
            data = excel_admin_service.create_task(payload)
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except ExcelTaskAdminValidationError as exc:
            return _project_status_validation_error(exc.fields)
        except ExcelIdempotencyConflictError:
            return _json_error(
                409,
                "Conflict",
                "Idempotency key was already used for a different request",
            )
        except Exception:
            logger.exception("Excel task creation failed")
            return _json_error(500, "ServerError", "Excel task creation failed")

    @app.get("/api/excel-tasks")
    def api_excel_tasks_list():
        if excel_admin_service is None:
            return _json_error(503, "NotConfigured", "Excel task roots are not configured")
        try:
            data = excel_admin_service.list_tasks(
                request.args.get("status"),
                request.args.get("limit"),
            )
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except ExcelTaskAdminValidationError as exc:
            return _project_status_validation_error(exc.fields)
        except Exception:
            logger.exception("Excel task list failed")
            return _json_error(500, "ServerError", "Excel task query failed")

    @app.get("/api/excel-worker/status")
    def api_excel_worker_status():
        if excel_worker_controller is None:
            return _json_error(503, "NotConfigured", "Excel worker is not configured")
        response = jsonify({"ok": True, "data": excel_worker_controller.status().to_dict()})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/excel-worker/start")
    def api_excel_worker_start():
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        if excel_worker_controller is None:
            return _json_error(503, "NotConfigured", "Excel worker is not configured")
        try:
            status = excel_worker_controller.start()
            response = jsonify({"ok": True, "data": status.to_dict()})
            response.headers["Cache-Control"] = "no-store"
            return response
        except RuntimeError:
            return _json_error(409, "Conflict", "Excel worker is already running")
        except Exception:
            logger.exception("Excel worker start failed")
            return _json_error(500, "ServerError", "Excel worker start failed")

    @app.post("/api/excel-worker/stop")
    def api_excel_worker_stop():
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        if excel_worker_controller is None:
            return _json_error(503, "NotConfigured", "Excel worker is not configured")
        try:
            status = excel_worker_controller.stop()
            response = jsonify({"ok": True, "data": status.to_dict()})
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception:
            logger.exception("Excel worker stop failed")
            return _json_error(500, "ServerError", "Excel worker stop failed")

    @app.get("/api/excel-tasks/<int:task_id>")
    def api_excel_task_detail(task_id: int):
        if excel_admin_service is None:
            return _json_error(503, "NotConfigured", "Excel task roots are not configured")
        try:
            data = excel_admin_service.get_task(task_id)
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "Excel task was not found")
        except Exception:
            logger.exception("Excel task detail failed")
            return _json_error(500, "ServerError", "Excel task query failed")

    @app.get("/api/excel-tasks/<int:task_id>/runs")
    def api_excel_task_runs(task_id: int):
        if excel_admin_service is None:
            return _json_error(503, "NotConfigured", "Excel task roots are not configured")
        try:
            data = excel_admin_service.list_runs(task_id)
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "Excel task was not found")
        except Exception:
            logger.exception("Excel task runs failed")
            return _json_error(500, "ServerError", "Excel task query failed")

    @app.get("/api/excel-tasks/<int:task_id>/artifacts")
    def api_excel_task_artifacts(task_id: int):
        if excel_admin_service is None:
            return _json_error(503, "NotConfigured", "Excel task roots are not configured")
        try:
            data = excel_admin_service.list_artifacts(task_id)
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "Excel task was not found")
        except Exception:
            logger.exception("Excel task artifacts failed")
            return _json_error(500, "ServerError", "Excel artifact query failed")

    @app.get("/api/excel-artifacts/<int:artifact_id>")
    def api_excel_artifact_detail(artifact_id: int):
        if excel_admin_service is None:
            return _json_error(503, "NotConfigured", "Excel task roots are not configured")
        try:
            data = excel_admin_service.get_artifact(artifact_id)
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "Excel artifact was not found")
        except Exception:
            logger.exception("Excel artifact detail failed")
            return _json_error(500, "ServerError", "Excel artifact query failed")

    @app.get("/api/excel-artifacts/<int:artifact_id>/download")
    def api_excel_artifact_download(artifact_id: int):
        if excel_admin_service is None:
            return _json_error(503, "NotConfigured", "Excel task roots are not configured")
        try:
            artifact = excel_admin_service.prepare_artifact_download(artifact_id)
            response = send_file(
                io.BytesIO(artifact.data),
                mimetype=artifact.mimetype,
                as_attachment=True,
                download_name=_safe_attachment_basename(
                    artifact.display_name,
                    fallback="excel-artifact.xlsx",
                ),
            )
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "Excel artifact was not found")
        except ExcelArtifactUnavailableError:
            return _json_error(
                409,
                "ArtifactUnavailable",
                "Excel artifact is unavailable or failed integrity validation",
            )
        except Exception:
            logger.exception("Excel artifact download failed")
            return _json_error(500, "ServerError", "Excel artifact download failed")

    @app.get("/api/excel-artifacts/<int:artifact_id>/download-audit")
    def api_excel_artifact_download_audit(artifact_id: int):
        if excel_admin_service is None:
            return _json_error(503, "NotConfigured", "Excel task roots are not configured")
        try:
            data = excel_admin_service.list_artifact_download_audits(
                artifact_id,
                limit=request.args.get("limit"),
            )
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "Excel artifact was not found")
        except ExcelTaskAdminValidationError as exc:
            return _project_status_validation_error(exc.fields)
        except Exception:
            logger.exception("Excel artifact download audit query failed")
            return _json_error(500, "ServerError", "Excel artifact download audit query failed")

    @app.get("/api/excel-artifacts/retention-plan")
    def api_excel_artifacts_retention_plan():
        if excel_admin_service is None:
            return _json_error(503, "NotConfigured", "Excel task roots are not configured")
        try:
            data = excel_admin_service.plan_retention(
                retention_days=request.args.get("retentionDays"),
                limit=request.args.get("limit"),
            )
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except ExcelTaskAdminValidationError as exc:
            return _project_status_validation_error(exc.fields)
        except Exception:
            logger.exception("Excel artifact retention plan query failed")
            return _json_error(500, "ServerError", "Excel artifact retention plan query failed")

    # ── 统一任务中心门面与工件下载 (Unified Task Center API Facade) ──────────

    _CRAWL_TASK_TYPE_LABELS = {
        "paa_crawl": "Aras PAA 全量抓取",
        "paa_export": "Aras PAA 导出",
        "ewo_export": "Aras EWO 导出",
        "tdc_data_model_crawl": "TDC 数模审核全量抓取",
        "tdc_data_model_export": "TDC 数模审核导出",
        "tdc_sor_crawl": "TDC SOR 全量抓取",
        "tdc_sor_export": "TDC SOR 导出",
    }

    def _crawl_task_title(task_type: str | None, source: str | None) -> str:
        t = (task_type or "").lower()
        if t in _CRAWL_TASK_TYPE_LABELS:
            return _CRAWL_TASK_TYPE_LABELS[t]
        s = (source or "aras").upper()
        if "ewo" in t:
            return f"{s} EWO 数据查询与抓取"
        elif "paa" in t:
            return f"{s} PAA 报表查询"
        elif "ncr" in t:
            return f"{s} NCR 报表抓取"
        elif "sor" in t:
            return f"{s} SOR 导出任务"
        elif "model" in t or "data_model" in t:
            return f"{s} 数模审核报表抓取"
        elif "export" in t:
            return f"{s} 数据导出任务"
        return f"{s} {task_type or '后台任务'}"

    def _crawl_task_entry(ct: dict[str, Any]) -> dict[str, Any]:
        st = ct["status"]
        is_active = st in ("queued", "leased", "running")
        prog = {}
        if ct.get("progress_json"):
            try:
                prog = json.loads(ct["progress_json"])
            except Exception:
                pass
        art_path = ct.get("artifact_path")
        has_art = False
        if art_path:
            try:
                target_f = (crawl_task_runner.downloads_dir / art_path).resolve()
                has_art = (
                    target_f.is_file()
                    and target_f.is_relative_to(crawl_task_runner.downloads_dir.resolve())
                )
            except Exception:
                pass

        tid = ct["task_id"]
        # 仅注册了默认 handler 的任务类型可安全重试；抓取/导出任务的工作函数
        # 与请求上下文（会话、筛选）绑定，过期后须从面板重新提交。
        retryable = st in ("failed", "interrupted", "cancelled") and (
            crawl_task_runner is not None
            and crawl_task_runner.has_handler(ct.get("task_type") or "")
        )
        return {
            "id": tid if tid.startswith("crawl_") else f"crawl_{tid}",
            "raw_id": tid,
            "category": "crawl",
            "source": ct.get("source", "aras"),
            "task_type": ct.get("task_type", "query"),
            "title": _crawl_task_title(ct.get("task_type"), ct.get("source")),
            "status": st,
            "is_active": is_active,
            "progress": prog,
            "artifact_path": art_path if has_art else None,
            "has_artifact": has_art,
            "error_message": ct.get("error_message"),
            "created_at": ct.get("created_at"),
            "updated_at": ct.get("updated_at"),
            "can_cancel": is_active,
            "can_download": has_art and st == "succeeded",
            "can_retry": retryable,
            "manual_check_required": False,
        }

    def _excel_task_entry(et: dict[str, Any]) -> dict[str, Any]:
        st = et["status"]
        is_active = st in ("queued", "leased", "running")
        has_art = False
        try:
            arts = excel_admin_service.list_artifacts(et["id"])
            has_art = bool(arts)
        except Exception:
            pass
        return {
            "id": f"excel_{et['id']}",
            "raw_id": str(et["id"]),
            "category": "excel",
            "source": "excel",
            "task_type": et.get("operation", "transform"),
            "title": f"Excel {et.get('operation', '处理')}",
            "status": st,
            "is_active": is_active,
            "progress": {},
            "artifact_path": None,
            "has_artifact": has_art,
            "error_message": et.get("errorMessage"),
            "created_at": et.get("createdAt"),
            "updated_at": et.get("updatedAt"),
            "can_cancel": is_active,
            "can_download": has_art and st == "succeeded",
            "can_retry": False,
            "manual_check_required": False,
        }

    def _ewo_task_entry(ej: dict[str, Any]) -> dict[str, Any]:
        raw_st = ej["state"]
        is_active = raw_st in ("queued", "generating", "downloading")
        if raw_st == "queued":
            norm_st = "queued"
        elif raw_st in ("generating", "downloading"):
            norm_st = "running"
        elif raw_st in ("parsed", "generated"):
            norm_st = "succeeded"
        elif raw_st in ("generation_unknown",):
            norm_st = "failed"
        else:
            norm_st = raw_st

        has_art = bool(ej.get("file_id") or ej.get("snapshot_ref"))
        ewo_dl_dir = (Path(db.db_path).parent / "ewo-downloads").resolve()
        cand = []
        if ewo_dl_dir.exists():
            for f in ewo_dl_dir.iterdir():
                if f.is_file() and ej["id"] in f.name:
                    cand.append(f)
                    break
        if cand and cand[0].is_file():
            has_art = True

        c_ts = (
            datetime.fromtimestamp(ej["created"], tz=timezone.utc).isoformat()
            if ej.get("created")
            else ""
        )
        u_ts = (
            datetime.fromtimestamp(ej["updated"], tz=timezone.utc).isoformat()
            if ej.get("updated")
            else ""
        )

        # W3-3 冻结重试语义：generation_unknown 仅允许人工核查，禁止自动重发。
        manual_check = raw_st == "generation_unknown"
        return {
            "id": f"ewo_{ej['id']}",
            "raw_id": ej["id"],
            "category": "ewo",
            "source": "aras",
            "task_type": "ewo_export",
            "title": f"Aras EWO 增强导表 ({ej.get('scope', 'default')})",
            "status": norm_st,
            "raw_status": raw_st,
            "is_active": is_active,
            "progress": {},
            "artifact_path": cand[0].name if cand else None,
            "has_artifact": has_art,
            "error_message": None,
            "created_at": c_ts,
            "updated_at": u_ts,
            "can_cancel": is_active,
            "can_download": has_art and norm_st == "succeeded",
            "can_retry": raw_st in ("interrupted", "failed"),
            "manual_check_required": manual_check,
        }

    def _find_unified_task_entry(task_id: str) -> dict[str, Any] | None:
        tid = task_id.strip()
        if crawl_task_runner is not None:
            ct = crawl_task_runner.get_task(tid) or crawl_task_runner.get_task(tid.removeprefix("crawl_"))
            if ct is not None:
                return _crawl_task_entry(ct)
        raw_ex_id = tid.removeprefix("excel_")
        if raw_ex_id.isdigit() and excel_admin_service is not None:
            try:
                et = excel_admin_service.get_task(int(raw_ex_id))
                return _excel_task_entry(et)
            except KeyError:
                pass
        raw_ewo_id = tid.removeprefix("ewo_").strip()
        if raw_ewo_id and re.fullmatch(r"[0-9a-fA-F-]{8,64}", raw_ewo_id):
            try:
                from core.ewo_export_jobs import EWOExportJobs
                ej = EWOExportJobs(db.db_path).get_job(raw_ewo_id)
                if ej is not None:
                    return _ewo_task_entry(ej)
            except Exception:
                pass
        return None

    @app.get("/api/tasks")
    def api_tasks_list():
        category = request.args.get("category", "").strip().lower()
        status_filter = request.args.get("status", "").strip().lower()
        raw_limit = request.args.get("limit")
        try:
            limit = max(1, min(int(raw_limit), 200)) if raw_limit else 50
        except (ValueError, TypeError):
            limit = 50

        aggregated: list[dict[str, Any]] = []

        # 1. crawl_tasks
        if crawl_task_runner is not None and (not category or category == "crawl"):
            try:
                for ct in crawl_task_runner.list_tasks(limit=limit * 2):
                    aggregated.append(_crawl_task_entry(ct))
            except Exception:
                logger.exception("Failed to query crawl_tasks for unified task list")

        # 2. excel_tasks
        if excel_admin_service is not None and (not category or category == "excel"):
            try:
                for et in excel_admin_service.list_tasks(limit=limit * 2):
                    aggregated.append(_excel_task_entry(et))
            except Exception:
                logger.exception("Failed to query excel_tasks for unified task list")

        # 3. ewo_export_jobs（EWO 增强导表任务）
        if (not category or category == "ewo"):
            try:
                from core.ewo_export_jobs import EWOExportJobs
                ewo_jobs = EWOExportJobs(db.db_path).list_jobs(limit=limit * 2)
                for ej in ewo_jobs:
                    aggregated.append(_ewo_task_entry(ej))
            except Exception:
                logger.exception("Failed to query ewo_export_jobs for unified task list")

        # Compute accurate total active count from database indices
        active_crawl = db.count_active_crawl_tasks() if hasattr(db, "count_active_crawl_tasks") else 0
        active_excel = 0
        if excel_repository is not None:
            try:
                with db.get_connection() as conn:
                    row = conn.execute(
                        "SELECT COUNT(*) FROM excel_tasks WHERE status IN ('queued', 'leased', 'running')"
                    ).fetchone()
                    active_excel = int(row[0]) if row else 0
            except Exception:
                pass
        active_ewo = 0
        try:
            from core.ewo_export_jobs import EWOExportJobs
            active_ewo = EWOExportJobs(db.db_path).count_active_jobs()
        except Exception:
            pass
        active_count = active_crawl + active_excel + active_ewo

        if status_filter == "active":
            aggregated = [t for t in aggregated if t["is_active"]]
        elif status_filter in ("history", "finished"):
            aggregated = [t for t in aggregated if not t["is_active"]]
        elif status_filter:
            aggregated = [t for t in aggregated if t["status"] == status_filter]

        aggregated.sort(key=lambda t: t.get("created_at") or "", reverse=True)
        paged = aggregated[:limit]

        response = jsonify({
            "ok": True,
            "data": {
                "tasks": paged,
                "active_count": active_count,
                "total_count": len(aggregated),
            }
        })
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/tasks/<task_id>/cancel")
    def api_tasks_cancel(task_id: str):
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error

        tid = task_id.strip()

        # 1. Try crawl task
        if crawl_task_runner is not None:
            raw_tid = tid.removeprefix("crawl_")
            ct = crawl_task_runner.get_task(tid) or crawl_task_runner.get_task(raw_tid)
            if ct is not None:
                if ct["status"] not in ("queued", "leased", "running"):
                    return _json_error(409, "Conflict", f"Task is already {ct['status']}")
                crawl_task_runner.cancel_task(ct["task_id"])
                return jsonify({"ok": True, "data": {"taskId": task_id, "status": "cancelled"}})

        # 2. Try excel task
        raw_ex_id = tid.removeprefix("excel_")
        if raw_ex_id.isdigit() and excel_admin_service is not None:
            ex_id = int(raw_ex_id)
            try:
                et = excel_admin_service.get_task(ex_id)
                if et["status"] not in ("queued", "leased", "running"):
                    return _json_error(409, "Conflict", f"Task is already {et['status']}")
                excel_admin_service.cancel_task(ex_id)
                return jsonify({"ok": True, "data": {"taskId": task_id, "status": "cancelled"}})
            except KeyError:
                pass

        # 3. Try EWO export job
        raw_ewo_id = tid.removeprefix("ewo_").strip()
        if raw_ewo_id and re.fullmatch(r"[0-9a-fA-F-]{8,64}", raw_ewo_id):
            try:
                from core.ewo_export_jobs import EWOExportJobs
                ewo_jobs = EWOExportJobs(db.db_path)
                ej = ewo_jobs.get_job(raw_ewo_id)
                if ej is not None:
                    if ej["state"] not in ("queued", "generating", "downloading"):
                        return _json_error(409, "Conflict", f"Task is already {ej['state']}")
                    ewo_jobs.cancel(raw_ewo_id)
                    return jsonify({"ok": True, "data": {"taskId": task_id, "status": "cancelled"}})
            except Exception:
                pass

        return _json_error(404, "NotFound", f"Task '{task_id}' was not found")

    @app.post("/api/tasks/<task_id>/retry")
    def api_tasks_retry(task_id: str):
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error

        tid = task_id.strip()

        # 1. Try crawl task retry
        if crawl_task_runner is not None:
            raw_tid = tid.removeprefix("crawl_")
            ct = crawl_task_runner.get_task(tid) or crawl_task_runner.get_task(raw_tid)
            if ct is not None:
                if ct["status"] not in ("failed", "cancelled", "interrupted"):
                    return _json_error(409, "Conflict", f"Task cannot be retried (current status: {ct['status']})")
                try:
                    new_id = crawl_task_runner.retry_task(ct["task_id"])
                    return jsonify({"ok": True, "data": {"taskId": ct["task_id"], "newTaskId": new_id, "status": "queued"}})
                except (RuntimeError, ValueError) as exc:
                    return _json_error(400, "CannotRetry", str(exc))

        # 2. Try excel task retry (Excel transformations are not retry-safe per policy)
        raw_ex_id = tid.removeprefix("excel_")
        if raw_ex_id.isdigit() and excel_admin_service is not None:
            ex_id = int(raw_ex_id)
            try:
                excel_admin_service.get_task(ex_id)
                return _json_error(400, "CannotRetry", "Excel batch tasks must be re-submitted from Excel Toolbox")
            except KeyError:
                pass

        # 3. Try EWO export job retry
        raw_ewo_id = tid.removeprefix("ewo_").strip()
        if raw_ewo_id and re.fullmatch(r"[0-9a-fA-F-]{8,64}", raw_ewo_id):
            try:
                from core.ewo_export_jobs import EWOExportJobs
                ewo_jobs = EWOExportJobs(db.db_path)
                ej = ewo_jobs.get_job(raw_ewo_id)
                if ej is not None:
                    # 业务红线：generation_unknown 表示外部生成结果未知，
                    # 严禁自动重发，仅允许人工核查后再处理。
                    if ej["state"] == "generation_unknown":
                        return _json_error(
                            409,
                            "ManualCheckRequired",
                            "EWO 生成结果未知，禁止自动重发；请先人工核查该任务的生成状态",
                        )
                    if ej["state"] not in ("interrupted", "failed"):
                        return _json_error(409, "Conflict", f"EWO job cannot be retried (current state: {ej['state']})")
                    try:
                        targets = json.loads(ej["item_ids"]) if ej.get("item_ids") else []
                    except (TypeError, ValueError):
                        return _json_error(500, "ServerError", "EWO job selection data is corrupted")
                    if not targets:
                        return _json_error(409, "Conflict", "EWO job has no selection to retry")
                    try:
                        new_job = ewo_jobs.create(ej["scope"], targets)
                    except ValueError as exc:
                        return _json_error(400, "CannotRetry", str(exc))
                    return jsonify({"ok": True, "data": {"taskId": task_id, "newTaskId": f"ewo_{new_job['id']}", "status": "queued"}})
            except Exception:
                logger.exception("EWO export job retry failed")
                return _json_error(500, "ServerError", "EWO export job retry failed")

        return _json_error(404, "NotFound", f"Task '{task_id}' was not found")

    @app.get("/api/tasks/<task_id>/download")
    def api_tasks_download(task_id: str):
        tid = task_id.strip()

        # 1. Try crawl task artifact
        if crawl_task_runner is not None:
            raw_tid = tid.removeprefix("crawl_")
            ct = crawl_task_runner.get_task(tid) or crawl_task_runner.get_task(raw_tid)
            if ct is not None:
                art_rel = ct.get("artifact_path")
                if not art_rel:
                    return _json_error(404, "NotFound", "Task has no artifact")
                downloads_dir = crawl_task_runner.downloads_dir.resolve()
                try:
                    target_file = (downloads_dir / art_rel).resolve()
                    if not target_file.is_relative_to(downloads_dir):
                        return _json_error(403, "Forbidden", "Unsafe artifact path")
                except (ValueError, RuntimeError):
                    return _json_error(403, "Forbidden", "Unsafe artifact path")
                if not target_file.is_file():
                    return _json_error(404, "NotFound", "Artifact file not found")
                safe_name = _safe_attachment_basename(target_file.name, fallback="artifact.xlsx")
                response = send_file(
                    target_file,
                    as_attachment=True,
                    download_name=safe_name,
                )
                response.headers["Cache-Control"] = "no-store"
                response.headers["X-Content-Type-Options"] = "nosniff"
                return response

        # 2. Try excel task artifact
        raw_ex_id = tid.removeprefix("excel_")
        if raw_ex_id.isdigit() and excel_admin_service is not None:
            ex_id = int(raw_ex_id)
            try:
                excel_admin_service.get_task(ex_id)
                arts = excel_admin_service.list_artifacts(ex_id)
                if not arts:
                    return _json_error(404, "NotFound", "Task has no artifact")
                artifact = excel_admin_service.prepare_artifact_download(arts[0]["id"])
                response = send_file(
                    io.BytesIO(artifact.data),
                    mimetype=artifact.mimetype,
                    as_attachment=True,
                    download_name=_safe_attachment_basename(
                        artifact.display_name,
                        fallback="excel-artifact.xlsx",
                    ),
                )
                response.headers["Cache-Control"] = "no-store"
                response.headers["X-Content-Type-Options"] = "nosniff"
                return response
            except KeyError:
                pass
            except Exception:
                pass

        # 3. Try EWO export artifact
        raw_ewo_id = tid.removeprefix("ewo_").strip()
        if raw_ewo_id and re.fullmatch(r"[0-9a-fA-F-]{8,64}", raw_ewo_id):
            try:
                from core.ewo_export_jobs import EWOExportJobs
                ej = EWOExportJobs(db.db_path).get_job(raw_ewo_id)
                if ej is not None:
                    ewo_dl_dir = (Path(db.db_path).parent / "ewo-downloads").resolve()
                    if ewo_dl_dir.exists():
                        for f in ewo_dl_dir.iterdir():
                            if f.is_file() and raw_ewo_id in f.name:
                                target_file = f.resolve()
                                try:
                                    if not target_file.is_relative_to(ewo_dl_dir):
                                        continue
                                except (ValueError, RuntimeError):
                                    continue
                                safe_name = _safe_attachment_basename(target_file.name, fallback="ewo-export.xlsx")
                                response = send_file(
                                    target_file,
                                    as_attachment=True,
                                    download_name=safe_name,
                                )
                                response.headers["Cache-Control"] = "no-store"
                                response.headers["X-Content-Type-Options"] = "nosniff"
                                return response
                    return _json_error(404, "NotFound", "Task has no artifact")
            except Exception:
                pass

        return _json_error(404, "NotFound", f"Artifact for task '{task_id}' was not found")

    @app.get("/api/tasks/<task_id>")
    def api_tasks_get(task_id: str):
        entry = _find_unified_task_entry(task_id.strip())
        if entry is None:
            return _json_error(404, "NotFound", f"Task '{task_id}' was not found")
        response = jsonify({"ok": True, "data": entry})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/tasks/<task_id>/result")
    def api_tasks_result(task_id: str):
        """读取成功后台抓取任务的结果 JSON（与原同步响应 data 同构）。"""
        if crawl_task_runner is None:
            return _json_error(503, "TaskEngineUnavailable", "后台任务引擎未初始化")
        tid = task_id.strip()
        ct = crawl_task_runner.get_task(tid) or crawl_task_runner.get_task(tid.removeprefix("crawl_"))
        if ct is None:
            return _json_error(404, "NotFound", f"Task '{task_id}' was not found")
        if ct["status"] != "succeeded":
            return _json_error(
                409,
                "Conflict",
                f"Task result is only available after success (current: {ct['status']})",
            )
        art_rel = ct.get("artifact_path")
        if not art_rel or not art_rel.lower().endswith(".json"):
            return _json_error(404, "NotFound", "Task has no JSON result artifact")
        downloads_dir = crawl_task_runner.downloads_dir.resolve()
        try:
            target_file = (downloads_dir / art_rel).resolve()
            if not target_file.is_relative_to(downloads_dir):
                return _json_error(403, "Forbidden", "Unsafe artifact path")
        except (ValueError, RuntimeError):
            return _json_error(403, "Forbidden", "Unsafe artifact path")
        if not target_file.is_file():
            return _json_error(404, "NotFound", "Result artifact file not found")
        if target_file.stat().st_size > _TASK_RESULT_MAX_BYTES:
            return _json_error(413, "PayloadTooLarge", "Task result artifact exceeds size limit")
        try:
            data = json.loads(target_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _json_error(500, "ServerError", "Task result artifact is unreadable")
        response = jsonify({"ok": True, "data": data})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/scheduled-archive/folders")
    def api_scheduled_archive_folders():
        try:
            data = archive_admin_service.list_folders(request.args.get("path", ""))
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except FileNotFoundError:
            return _json_error(404, "NotFound", "未找到归档目录")
        except ArchiveSafetyError as exc:
            return _json_error(422, "ValidationError", _sanitize_error_message(exc))
        except OSError:
            logger.exception("scheduled archive folder query failed")
            return _json_error(500, "ServerError", "无法读取归档目录")

    @app.post("/api/scheduled-archive/folders/native")
    def api_scheduled_archive_native_folder():
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        if app.config.get("TESTING"):
            return _json_error(503, "NativeFolderPickerUnavailable", "测试环境不打开本机文件夹选择器")
        payload = request.get_json(silent=True) or {}
        initial_directory = payload.get("path", "") if isinstance(payload, dict) else ""
        if not isinstance(initial_directory, str):
            return _project_status_validation_error({"path": "必须是本机目录字符串"})
        try:
            data = archive_admin_service.pick_native_folder(initial_directory)
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except NativeFolderPickerError as exc:
            return _json_error(503, "NativeFolderPickerUnavailable", _sanitize_error_message(exc))
        except FileNotFoundError:
            return _json_error(404, "NotFound", "未找到归档目录")
        except ArchiveSafetyError as exc:
            return _json_error(422, "ValidationError", _sanitize_error_message(exc))
        except OSError:
            logger.exception("scheduled archive native folder picker failed")
            return _json_error(500, "ServerError", "无法选择归档目录")

    @app.get("/api/settings")
    def api_settings_get():
        response = jsonify(
            {
                "ok": True,
                "data": {
                    "settings": settings_store.get(),
                    "sessions": domain_sessions.payload(),
                    "credentialVaultConfigured": credential_vault.is_configured(),
                    "excelService": {"configured": excel_admin_service is not None},
                },
            }
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.patch("/api/settings")
    def api_settings_update():
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _json_error(400, "ValidationError", "JSON object body is required")
        try:
            data = settings_store.update(payload)
            response = jsonify({"ok": True, "data": {"settings": data}})
            response.headers["Cache-Control"] = "no-store"
            return response
        except SettingsValidationError as exc:
            return _project_status_validation_error(exc.fields)

    @app.post("/api/settings/folders/native")
    def api_settings_native_folder():
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        if app.config.get("TESTING"):
            return _json_error(503, "NativeFolderPickerUnavailable", "测试环境不打开本机文件夹选择器")
        payload = request.get_json(silent=True) or {}
        initial_value = payload.get("path", "") if isinstance(payload, dict) else ""
        initial_path: Path | None = None
        if isinstance(initial_value, str) and initial_value.strip():
            try:
                initial_path = Path(validate_local_directory(initial_value))
            except ValueError:
                initial_path = None
        try:
            selected = choose_native_folder(initial_path)
            selected_path = None if selected is None else validate_local_directory(str(selected))
            response = jsonify({"ok": True, "data": {"path": selected_path, "cancelled": selected is None}})
            response.headers["Cache-Control"] = "no-store"
            return response
        except NativeFolderPickerError as exc:
            return _json_error(503, "NativeFolderPickerUnavailable", _sanitize_error_message(exc))
        except ValueError as exc:
            return _project_status_validation_error({"path": _sanitize_error_message(exc)})

    @app.post("/api/settings/domain-login")
    def api_domain_login():
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _json_error(400, "ValidationError", "JSON object body is required")
        username = payload.get("username")
        password = payload.get("password")
        if not isinstance(username, str) or not username.strip() or not isinstance(password, str) or not password:
            return _project_status_validation_error({"credentials": "域用户名和密码不能为空"})
        results: dict[str, object] = {}
        domain_sessions.clear()
        try:
            login_result = ArasECMAuthClient().login(username.strip(), password)
            domain_sessions.mark_authenticated(
                "aras", login_result.session, principal=username.strip(), source_root=DEFAULT_ARAS_BASE_URL
            )
            results["aras"] = {"ok": True}
        except Exception as exc:
            results["aras"] = {"ok": False, "message": _sanitize_error_message(exc)}
        try:
            login_result = TDCPasswordAuthClient().login(username.strip(), password)
            domain_sessions.mark_authenticated("tdc", login_result.session)
            results["tdc"] = {"ok": True}
        except Exception as exc:
            results["tdc"] = {"ok": False, "message": _sanitize_error_message(exc)}
        if any(isinstance(item, dict) and item.get("ok") for item in results.values()):
            tdc_export_cache.clear()
        if bool(payload.get("saveForScheduled")) and any(
            isinstance(item, dict) and item.get("ok") for item in results.values()
        ):
            # 先写 Windows 凭据管理器（失败更常见），再写 DPAPI 凭据库；
            # 任一步失败都不得出现「一侧已落盘」的半保存状态。
            try:
                store_windows_generic_credential(SYNC_CREDENTIAL_REF, username.strip(), password)
            except CredentialProviderError as exc:
                return _json_error(
                    503,
                    "CredentialVaultUnavailable",
                    f"登录会话已建立，但同步凭据保存失败：{_sanitize_error_message(exc)}",
                )
            try:
                credential_vault.store(username.strip(), password)
            except CredentialVaultError as exc:
                # DPAPI 落库失败：回滚 Windows 凭据，保持两侧一致。
                try:
                    delete_windows_generic_credential(SYNC_CREDENTIAL_REF)
                except CredentialProviderError:
                    pass
                return _json_error(
                    503,
                    "CredentialVaultUnavailable",
                    f"登录会话已建立，但定时下载凭据保存失败：{_sanitize_error_message(exc)}",
                )
        response = jsonify(
            {
                "ok": any(isinstance(item, dict) and item.get("ok") for item in results.values()),
                "data": {"results": results, "sessions": domain_sessions.payload()},
            }
        )
        response.headers["Cache-Control"] = "no-store"
        return response, (200 if response.get_json()["ok"] else 401)

    @app.delete("/api/settings/sessions")
    def api_domain_sessions_clear():
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        payload = request.get_json(silent=True) or {}
        system = payload.get("system") if isinstance(payload, dict) else None
        if system not in (None, "aras", "tdc"):
            return _project_status_validation_error({"system": "仅支持 aras 或 tdc"})
        domain_sessions.clear(system)
        if system in (None, "tdc"):
            tdc_export_cache.clear()
        if isinstance(payload, dict) and payload.get("clearCredentialVault"):
            # 先删 Windows 凭据，再清 DPAPI 凭据库；Windows 删除失败时 DPAPI
            # 保持原状，避免出现 Windows 侧孤儿凭据。
            try:
                delete_windows_generic_credential(SYNC_CREDENTIAL_REF)
            except CredentialProviderError as exc:
                return _json_error(503, "CredentialVaultUnavailable", _sanitize_error_message(exc))
            try:
                credential_vault.clear()
            except CredentialVaultError as exc:
                return _json_error(503, "CredentialVaultUnavailable", _sanitize_error_message(exc))
        response = jsonify({"ok": True, "data": {"sessions": domain_sessions.payload()}})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/scheduled-archive/jobs")
    def api_scheduled_archive_jobs():
        try:
            response = jsonify({"ok": True, "data": archive_admin_service.list_jobs()})
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception as exc:
            logger.exception("scheduled archive jobs query failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.post("/api/scheduled-archive/jobs")
    def api_scheduled_archive_job_create():
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _json_error(400, "ValidationError", "JSON object body is required")
        try:
            data = archive_admin_service.create_job(payload)
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response, 201
        except ArchiveAdminValidationError as exc:
            return _project_status_validation_error(exc.fields)
        except (KeyError, ValueError) as exc:
            return _project_status_validation_error({"request": _sanitize_error_message(exc)})

    @app.patch("/api/scheduled-archive/jobs/<job_key>")
    def api_scheduled_archive_job_update(job_key: str):
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _json_error(400, "ValidationError", "JSON object body is required")
        try:
            data = archive_admin_service.update_job(job_key, payload)
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except ArchiveAdminValidationError as exc:
            return _project_status_validation_error(exc.fields)
        except KeyError:
            return _json_error(404, "NotFound", "未找到归档任务")
        except (ArchiveLeaseBusyError, RuntimeError):
            return _json_error(409, "Conflict", "任务正在运行或配置已更新，请刷新后重试")
        except ArchiveJobNotReadyError:
            return _json_error(409, "NotReady", "启用任务前必须配置凭据引用")
        except (ArchiveSafetyError, TypeError, ValueError) as exc:
            return _project_status_validation_error(
                {"request": _sanitize_error_message(exc)}
            )
        except Exception as exc:
            logger.exception("scheduled archive job update failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.delete("/api/scheduled-archive/jobs/<job_key>")
    def api_scheduled_archive_job_archive(job_key: str):
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        payload = request.get_json(silent=True) or {}
        try:
            data = archive_admin_service.archive_job(
                job_key,
                payload.get("updatedAt") if isinstance(payload, dict) else None,
            )
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except ArchiveAdminValidationError as exc:
            return _project_status_validation_error(exc.fields)
        except KeyError:
            return _json_error(404, "NotFound", "未找到定时任务")
        except RuntimeError:
            return _json_error(409, "Conflict", "任务配置已更新，请刷新后重试")
        except ValueError as exc:
            return _project_status_validation_error({"request": _sanitize_error_message(exc)})

    @app.get("/api/scheduled-archive/runs")
    def api_scheduled_archive_runs():
        job_key = request.args.get("jobKey") or None
        try:
            limit = _archive_history_limit(request.args.get("limit"))
            data = archive_admin_service.list_runs(job_key, limit)
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "未找到归档任务")
        except (TypeError, ValueError) as exc:
            return _json_error(422, "ValidationError", _sanitize_error_message(exc))
        except Exception as exc:
            logger.exception("scheduled archive runs query failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.get("/api/scheduled-archive/runs/<int:run_id>/artifacts")
    def api_scheduled_archive_artifacts(run_id: int):
        try:
            if db.get_archive_run(run_id) is None:
                return _json_error(404, "NotFound", "未找到归档运行")
            data = {
                "runId": run_id,
                "artifacts": archive_admin_service.list_artifacts(run_id),
            }
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception as exc:
            logger.exception("scheduled archive artifacts query failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.get("/api/scheduled-archive/config-audit")
    def api_scheduled_archive_config_audit():
        job_key = request.args.get("jobKey") or None
        try:
            limit = _archive_history_limit(request.args.get("limit"))
            data = archive_admin_service.list_audit(job_key, limit)
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "未找到归档任务")
        except (TypeError, ValueError) as exc:
            return _json_error(422, "ValidationError", _sanitize_error_message(exc))
        except Exception as exc:
            logger.exception("scheduled archive audit query failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.post("/api/scheduled-archive/jobs/<job_key>/sync-now")
    def api_scheduled_archive_sync_now(job_key: str):
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        try:
            data = archive_admin_service.sync_now(job_key)
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "未找到归档任务")
        except Exception as exc:
            logger.exception("scheduled archive sync-now failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.get("/api/project-status")
    def api_project_status():
        phase_id = request.args.get("phase", "VPI-T2").strip()
        if phase_id != "VPI-T2":
            return _json_error(404, "NotFound", "未找到项目阶段")
        try:
            data = current_project_status(phase_id)
            if data is None:
                return _json_error(404, "NotFound", "未找到项目阶段")
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception as exc:
            logger.exception("api/project-status 查询失败")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.patch("/api/project-status/phases/<phase_id>")
    def api_project_status_phase_update(phase_id: str):
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        if phase_id != "VPI-T2":
            return _json_error(404, "NotFound", "未找到项目阶段")
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _json_error(400, "ValidationError", "JSON object body is required")
        expected_updated_at = payload.get("updatedAt")
        if not isinstance(expected_updated_at, str) or not expected_updated_at:
            return _project_status_validation_error({"updatedAt": "缺少阶段版本"})
        values, errors = _validate_project_status_phase(payload)
        if errors:
            return _project_status_validation_error(errors)
        try:
            db.update_project_status_phase(
                phase_id,
                values,
                expected_updated_at,
            )
            updated_status = current_project_status(phase_id)
            assert updated_status is not None
            response = jsonify({"ok": True, "data": {"projectStatus": updated_status}})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "未找到项目阶段")
        except RuntimeError:
            return _json_error(409, "Conflict", "主计划已被其他会话更新，请刷新后重试")
        except Exception as exc:
            logger.exception("api/project-status/phases 更新失败")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    def _phase_car_type_anchor(deliverable_id: str) -> str | None:
        """车型锚点：显式传入 carType 优先，否则回退主计划名称（可在主计划维护中修改）。

        主计划名称上限 120 字符（displayName 校验），显式 carType 参数上限 80；
        锚点取 80 字符截断，与显式参数的存储口径保持一致。
        """
        phase_id = str(deliverable_id).rsplit("-", 1)[0]
        phase_row, _, _ = deliverable_analysis_service.db.get_project_status(phase_id)
        if phase_row is None:
            return None
        name = str(phase_row["display_name"] or "").strip()
        return name[:80] or None

    def _analysis_model_filters() -> tuple[str | None, str]:
        """解析 model/modelMatch 查询参数：空 model 表示不按车型过滤。"""
        raw_model = request.args.get("model")
        model = None
        if raw_model is not None:
            # 控制字符检查必须先于 strip，否则换行等字符会被静默吞掉。
            if any(ord(char) < 32 or ord(char) == 127 for char in raw_model):
                raise ValueError("model contains control characters")
            model = raw_model.strip()
            if len(model) > 80:
                raise ValueError("model is too long")
            if not model:
                model = None
        raw_match = (request.args.get("modelMatch") or "fuzzy").strip().casefold()
        model_match = raw_match or "fuzzy"
        if model_match not in {"fuzzy", "exact"}:
            raise ValueError("unsupported model match")
        return model, model_match

    @app.get("/api/project-status/deliverables/<deliverable_id>/analysis")
    def api_project_status_deliverable_analysis(deliverable_id: str):
        try:
            raw_limit = request.args.get("trendLimit", "8")
            trend_limit = int(raw_limit)
            if not 2 <= trend_limit <= 30:
                raise ValueError("trendLimit must be between 2 and 30")
            raw_car_type = request.args.get("carType")
            car_type = None
            if raw_car_type is not None:
                car_type = raw_car_type.strip()
                if len(car_type) > 80:
                    raise ValueError("carType is too long")
                if not car_type:
                    car_type = None
            if car_type is None:
                car_type = _phase_car_type_anchor(deliverable_id)
            model, model_match = _analysis_model_filters()
            data = deliverable_analysis_service.overview(
                deliverable_id,
                trend_limit=trend_limit,
                car_type=car_type,
                model=model,
                model_match=model_match,
            )
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "未找到交付物")
        except (TypeError, ValueError) as exc:
            return _json_error(422, "ValidationError", _sanitize_error_message(exc))
        except Exception as exc:
            logger.exception("project status deliverable analysis failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.get("/api/project-status/deliverables/<deliverable_id>/analysis/items")
    def api_project_status_deliverable_analysis_items(deliverable_id: str):
        try:
            raw_limit = request.args.get("limit", "200")
            limit = int(raw_limit)
            if not 1 <= limit <= 500:
                raise ValueError("limit must be between 1 and 500")
            raw_offset = request.args.get("offset", "0")
            offset = int(raw_offset)
            if not 0 <= offset <= 100000:
                raise ValueError("offset must be between 0 and 100000")
            departments = _analysis_query_values(
                "departments", "department", kind="departments"
            )
            stages = _analysis_query_values(
                "stages", "stage", kind="stages"
            )
            raw_state = request.args.get("state")
            state = None
            if raw_state is not None:
                state = raw_state.strip()
                if not state or state == "all":
                    state = None
                elif state not in {"completed", "incomplete"}:
                    raise ValueError("unsupported state filter")
            raw_car_type = request.args.get("carType")
            car_type = None
            if raw_car_type is not None:
                car_type = raw_car_type.strip()
                if len(car_type) > 80:
                    raise ValueError("carType is too long")
                if not car_type:
                    car_type = None
            if car_type is None:
                car_type = _phase_car_type_anchor(deliverable_id)
            model, model_match = _analysis_model_filters()
            data = deliverable_analysis_service.items(
                deliverable_id,
                alert=request.args.get("alert") or None,
                departments=departments,
                stages=stages,
                state=state,
                offset=offset,
                limit=limit,
                car_type=car_type,
                model=model,
                model_match=model_match,
            )
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "未找到交付物")
        except (TypeError, ValueError) as exc:
            return _json_error(422, "ValidationError", _sanitize_error_message(exc))
        except Exception as exc:
            logger.exception("project status deliverable analysis items failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.get("/api/project-status/deliverables/<deliverable_id>/chart-labels")
    def api_project_status_chart_labels(deliverable_id: str):
        try:
            data = {
                "labels": deliverable_analysis_service.chart_labels(deliverable_id),
                "fields": deliverable_analysis_service.chart_field_candidates(deliverable_id),
            }
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "未找到交付物")
        except (TypeError, ValueError) as exc:
            return _json_error(422, "ValidationError", _sanitize_error_message(exc))
        except Exception as exc:
            logger.exception("project status chart labels query failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.put("/api/project-status/deliverables/<deliverable_id>/chart-labels")
    def api_project_status_chart_labels_write(deliverable_id: str):
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _json_error(400, "ValidationError", "JSON object body is required")
        try:
            labels = deliverable_analysis_service.save_chart_labels(
                deliverable_id,
                payload.get("labels"),
            )
            response = jsonify({"ok": True, "data": {"labels": labels}})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "未找到交付物")
        except (TypeError, ValueError) as exc:
            return _json_error(422, "ValidationError", _sanitize_error_message(exc))
        except Exception as exc:
            logger.exception("project status chart labels update failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    def _deliverable_form_query() -> tuple[dict[str, object], int, dict[str, int] | None]:
        """Parse the shared read-only form-view query contract.

        同一字段内多选以重复查询参数表达（OR）；逾期判定天数以
        overdueDaysStage / overdueDaysLate 覆盖批准的默认口径。
        """
        filter_keys = {
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
            "terms",
        }
        multi_keys = {"status", "department", "section", "model", "stage", "overdueState"}
        control_keys = filter_keys | {
            "trendLimit",
            "offset",
            "limit",
            "overdueDaysStage",
            "overdueDaysLate",
        }
        unknown = set(request.args) - control_keys
        if unknown:
            raise ValueError("unsupported deliverable form query parameter")
        filters: dict[str, object] = {}
        for key in filter_keys:
            values = [value for value in request.args.getlist(key) if value != ""]
            if not values:
                continue
            if key in multi_keys:
                if len(values) > 20:
                    raise ValueError(f"{key} accepts at most 20 values")
                filters[key] = values
            else:
                if len(values) > 1:
                    raise ValueError(f"{key} accepts one value")
                filters[key] = values[0]
        if "terms" in filters:
            # 多值搜索原文 -> 检索词列表（§9 S2，services/form_search.py）。
            filters["terms"] = parse_form_terms(filters["terms"])

        def strict_int(name: str, default: int, lower: int, upper: int) -> int:
            raw = request.args.get(name)
            if raw is None or raw == "":
                return default
            try:
                value = int(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} must be an integer") from exc
            if not lower <= value <= upper:
                raise ValueError(f"{name} must be between {lower} and {upper}")
            return value

        thresholds: dict[str, int] = {}
        for name in ("overdueDaysStage", "overdueDaysLate"):
            parsed = strict_int(name, -1, 0, 999)
            if parsed >= 0:
                thresholds[name] = parsed
        return filters, strict_int("trendLimit", 30, 1, 365), thresholds or None

    def _form_section_rollup(form_key: str):
        """读取归集规则并构建扁平索引；非归集表单返回 None（保持原始口径）。"""
        if form_key not in SECTION_ROLLUP_FORM_KEYS:
            return None
        rules = section_rollup_store.get()
        return build_rollup_index(rules), rules

    @app.get("/api/deliverable-forms/<form_key>/view")
    def api_deliverable_form_view(form_key: str):
        try:
            filters, trend_limit, overdue_thresholds = _deliverable_form_query()
            rollup = _form_section_rollup(form_key)
            data = deliverable_form_service.view(
                form_key,
                filters=filters,
                trend_limit=trend_limit,
                overdue_thresholds=overdue_thresholds,
                section_rollup=rollup[0] if rollup else None,
            )
            if rollup is not None:
                data["sectionRollup"] = rollup[1]
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "未找到交付物表单")
        except (TypeError, ValueError) as exc:
            return _json_error(422, "ValidationError", _sanitize_error_message(exc))
        except Exception as exc:
            logger.exception("deliverable form view failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.get("/api/deliverable-forms/<form_key>/rows")
    def api_deliverable_form_rows(form_key: str):
        try:
            filters, _, overdue_thresholds = _deliverable_form_query()
            offset = request.args.get("offset", "0")
            limit = request.args.get("limit", "200")
            try:
                parsed_offset = int(offset)
                parsed_limit = int(limit)
            except (TypeError, ValueError) as exc:
                raise ValueError("offset and limit must be integers") from exc
            if not 0 <= parsed_offset <= 100000:
                raise ValueError("offset must be between 0 and 100000")
            if not 1 <= parsed_limit <= 500:
                raise ValueError("limit must be between 1 and 500")
            rollup = _form_section_rollup(form_key)
            data = deliverable_form_service.rows(
                form_key,
                filters,
                offset=parsed_offset,
                limit=parsed_limit,
                overdue_thresholds=overdue_thresholds,
                section_rollup=rollup[0] if rollup else None,
            )
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "未找到交付物表单")
        except (TypeError, ValueError) as exc:
            return _json_error(422, "ValidationError", _sanitize_error_message(exc))
        except Exception as exc:
            logger.exception("deliverable form rows failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.get("/api/project-status/section-rollup")
    def api_section_rollup_get():
        response = jsonify({"ok": True, "data": section_rollup_store.get()})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.put("/api/project-status/section-rollup")
    def api_section_rollup_put():
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _json_error(400, "ValidationError", "JSON object body is required")
        try:
            data = section_rollup_store.save(payload)
        except SectionRollupError as exc:
            return _project_status_validation_error(exc.fields)
        response = jsonify({"ok": True, "data": data})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/deliverable-forms/<form_key>/statistics")
    def api_deliverable_form_statistics(form_key: str):
        """确定性快照统计分析（纯统计学，无 AI）：读取最新快照行 + 有界
        历史快照，交由 services.deliverable_statistics 纯函数计算。"""
        try:
            data = _deliverable_form_statistics_payload(db, form_key)
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "未找到交付物表单")
        except (TypeError, ValueError) as exc:
            return _json_error(422, "ValidationError", _sanitize_error_message(exc))
        except Exception as exc:
            logger.exception("deliverable form statistics failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.patch("/api/project-status/deliverables/<deliverable_id>")
    def api_project_status_deliverable_update(deliverable_id: str):
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _json_error(400, "ValidationError", "JSON object body is required")
        phase_id = "VPI-T2"
        try:
            project_status = current_project_status(phase_id)
            if project_status is None:
                return _json_error(404, "NotFound", "未找到项目阶段")
            current = next(
                (item for item in project_status["deliverables"] if item["id"] == deliverable_id),
                None,
            )
            if current is None:
                return _json_error(404, "NotFound", "未找到交付物")
            expected_updated_at = payload.get("updatedAt")
            if not isinstance(expected_updated_at, str) or not expected_updated_at:
                return _project_status_validation_error({"updatedAt": "缺少记录版本"})
            values, errors = _validate_project_status_update(payload, current, project_status["phase"])
            if errors:
                return _project_status_validation_error(errors)
            update_service.apply_manual_update(
                deliverable_id,
                phase_id,
                values,
                expected_updated_at,
            )

            updated_status = current_project_status(phase_id)
            assert updated_status is not None
            updated = next(
                item for item in updated_status["deliverables"] if item["id"] == deliverable_id
            )
            return jsonify(
                {
                    "ok": True,
                    "data": {"deliverable": updated, "projectStatus": updated_status},
                }
            )
        except KeyError:
            return _json_error(404, "NotFound", "未找到交付物")
        except MappedDeliverableReadOnlyError as exc:
            return _json_error(409, "MappedDeliverableReadOnly", str(exc))
        except RuntimeError:
            return _json_error(409, "Conflict", "记录已被其他会话更新，请刷新后重试")
        except Exception as exc:
            logger.exception("api/project-status/deliverables 更新失败")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.get("/api/project-status/deliverables/<deliverable_id>/update-policy")
    def api_project_status_update_policy(deliverable_id: str):
        try:
            policy = update_service.get_update_policy(deliverable_id)
            if policy is None:
                return _json_error(404, "NotFound", "未找到交付物")
            response = jsonify({"ok": True, "data": policy})
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception as exc:
            logger.exception("api/project-status/update-policy 查询失败")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.patch("/api/project-status/deliverables/<deliverable_id>/update-policy")
    def api_project_status_update_policy_write(deliverable_id: str):
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _json_error(400, "ValidationError", "JSON object body is required")
        try:
            policy = update_service.update_update_policy(deliverable_id, payload)
            response = jsonify({"ok": True, "data": policy})
            response.headers["Cache-Control"] = "no-store"
            return response
        except ProjectStatusPolicyError as exc:
            return _project_status_validation_error(exc.fields)
        except KeyError:
            return _json_error(404, "NotFound", "未找到交付物")
        except Exception as exc:
            logger.exception("api/project-status/update-policy 更新失败")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.get("/api/project-status/updates")
    def api_project_status_updates():
        deliverable_id = request.args.get("deliverableId", "").strip()
        if not deliverable_id:
            return _project_status_validation_error({"deliverableId": "缺少交付物 ID"})
        try:
            data = update_service.list_updates(deliverable_id)
            if data is None:
                return _json_error(404, "NotFound", "未找到交付物")
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception as exc:
            logger.exception("api/project-status/updates 查询失败")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.get("/api/project-status/deliverables/<deliverable_id>/mapping-discovery")
    def api_project_status_mapping_discovery_history(deliverable_id: str):
        try:
            response = jsonify({"ok": True, "data": discovery_service.history(deliverable_id)})
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception as exc:
            logger.exception("mapping discovery history failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.get("/api/project-status/deliverables/<deliverable_id>/candidate-preview")
    def api_project_status_candidate_preview(deliverable_id: str):
        try:
            data = discovery_service.candidate_preview(deliverable_id)
            if data.get("reason") == "deliverable_not_found":
                return _json_error(404, "NotFound", "未找到交付物")
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception as exc:
            logger.exception("candidate preview failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.post("/api/project-status/deliverables/<deliverable_id>/mapping-discovery")
    def api_project_status_mapping_discovery(deliverable_id: str):
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        payload, error = _request_payload()
        if error is not None:
            return error
        assert payload is not None
        if deliverable_id == "VPI-T2-D1":
            return _json_error(409, "ManualOnly", "该交付物仅允许手工维护")
        if deliverable_id == "VPI-T2-D4":
            return _json_error(409, "ContractBlocked", AFACE_CONTRACT_BLOCKER)
        selected = payload.get("selectedExternalKey")
        if selected is not None and not isinstance(selected, str):
            return _project_status_validation_error(
                {"selectedExternalKey": "必须是字符串或 null"}
            )
        if isinstance(selected, str):
            selected = selected.strip() or None
        wizard_session_id = payload.get("wizardSessionId")
        if wizard_session_id is not None:
            if not isinstance(wizard_session_id, str) or not _WIZARD_SESSION_ID_RE.match(wizard_session_id):
                return _project_status_validation_error({"wizardSessionId": "非法的向导会话ID"})
        is_stability_check = payload.get("stabilityCheck") is True
        aras_client: ArasCrawlerClient | None = None
        cancel_token, cancel_event = _register_discovery_cancel(payload.get("cancelToken"))
        try:
            # Freeze the exact query identity before any external call. The
            # binding may be rebound while the request is in flight; the old
            # response must still carry the rule that produced it.
            match_rule, values = _mapping_discovery_query_identity(
                payload, deliverable_id, selected
            )
            source_type = "tdc" if deliverable_id in {"VPI-T2-D2", "VPI-T2-D5"} else "aras"
            # 数模流水单号（documentNo）不是 TDC 查询参数：规则里带它时只做本地
            # 精确匹配，绝不发给上游（见 _mapping_discovery_query_identity）。
            document_no = str(match_rule.get("documentNo") or "").strip()
            cache_key = None
            if wizard_session_id and not is_stability_check:
                base_query_params = {
                    k: v for k, v in values.items()
                    if k not in {"serial_number", "incident", "processNo", "ewo_no",
                                 "paa_no", "ncr_no", "document_no"}
                }
                base_query_params["aggregate"] = match_rule.get("aggregate")
                if "contractVersion" in match_rule:
                    base_query_params["contractVersion"] = match_rule["contractVersion"]
                base_query_json = json.dumps(base_query_params, sort_keys=True, ensure_ascii=False)
                base_query_hash = hashlib.sha256(base_query_json.encode()).hexdigest()[:16]
                cache_key = f"{wizard_session_id}:{deliverable_id}:{source_type}:{base_query_hash}"

            def run_observation(build_client, should_stop=None):
                """非 stability 的完整观测：会话缓存 → 全量抓取 → 落观测（G5 单源）。

                同步路径与后台 worker 共用：build_client 延迟构建（命中会话
                缓存时不构建客户端）；should_stop 为协作式取消探测，在 TDC
                分页边界被探测（Aras 单次 SOAP 导出无取消钩子，保持原状）。
                """
                nonlocal aras_client
                cached_rows = _get_discovery_session_cache(cache_key) if cache_key else None
                if source_type == "tdc":
                    upstream_declared_total: int | None = None
                    if cached_rows is not None:
                        rows = cached_rows
                        # 缓存命中（候选重选等）：沿用首次抓取时的上游声明总数，
                        # 保持与采样端同源（去重后行数不能充当声明总数）。
                        cached_total = (
                            _get_discovery_session_cache_total(cache_key) if cache_key else None
                        )
                        if cached_total is not None:
                            upstream_declared_total = cached_total
                    else:
                        client = build_client()
                        # 协作式取消：前端 abort 后会调 cancel 端点置位，分页边界即停止，
                        # 不再把整轮全量抓取跑完（否则取消只省了浏览器等待）。
                        if deliverable_id == "VPI-T2-D2":
                            crawl_result = client.crawl_sor_all(
                                _tdc_sor_filters(values),
                                max_records=MAX_AGGREGATE_RECORDS,
                                should_stop=should_stop,
                            )
                        else:
                            crawl_result = client.crawl_data_model_all(
                                _tdc_data_model_filters(values),
                                max_records=MAX_AGGREGATE_RECORDS,
                                should_stop=should_stop,
                            )
                        if document_no and not _mapping_result_is_complete(crawl_result):
                            # fail-closed：抓不全就不能判定"这个流水单号没有匹配行"。
                            raise _TDCRequestError(
                                "抓取不完整，无法判定流水单号，请重试",
                                "IncompleteDiscovery",
                                422,
                                None,
                                _pagination_diagnostic(crawl_result, len(crawl_result.rows)),
                            )
                        rows = _require_complete_mapping_result(crawl_result, _TDCRequestError)
                        crawl_total = getattr(crawl_result, "total", None)
                        if (
                            isinstance(crawl_total, int)
                            and not isinstance(crawl_total, bool)
                            and crawl_total >= 0
                        ):
                            upstream_declared_total = crawl_total
                        if cache_key:
                            _set_discovery_session_cache(cache_key, rows, upstream_declared_total)
                    serial_match: dict[str, Any] | None = None
                    effective_selected = selected
                    if document_no:
                        # 本地精确匹配是流水单号的唯一判定依据：恰好命中 1 行才放行，
                        # 并把该行的实例号 incident 作为有效查询结果（线上参数语义）。
                        matched, serial_match = match_serial(rows, document_no)
                        if len(matched) > 1:
                            raise _TDCRequestError("该流水单号命中多行，请核对后重试")
                        if upstream_declared_total is None:
                            # 本地匹配不改变上游范围：基线总数仍是全量抓取的行数，
                            # 否则 F10 采样（同样全量抓取）会与基线总数误判失配。
                            upstream_declared_total = len(rows)
                        rows = matched
                        effective_selected = (
                            serial_match["matched_instances"][0] if matched else None
                        )
                    observation = discovery_service.observe(
                        deliverable_id, "tdc", rows, effective_selected,
                        aggregate=bool(match_rule["aggregate"]), match_rule=match_rule,
                        upstream_total=upstream_declared_total,
                    )
                    if serial_match is not None:
                        # 0 行时仍走既有「未匹配」路径（state=not_found），但附带
                        # 覆盖范围，用户能看到抓了多少行/多少页，而不是只看到"未匹配"。
                        observation = {**observation, "serialMatch": serial_match}
                    return observation
                if cached_rows is not None:
                    rows = cached_rows
                else:
                    aras_client = build_client()
                    # 报表分派来自能力注册表（取代 deliverable_id 硬编码）。
                    aras_report = str(
                        PROJECT_STATUS_SOURCE_CAPABILITIES.get(deliverable_id, {}).get("reportType")
                        or ""
                    )
                    if aras_report == "ewo":
                        crawl_result = aras_client.crawl_ewo_report_all(
                            build_project_status_ewo_filters(match_rule),
                            max_records=MAX_AGGREGATE_RECORDS,
                        )
                        rows = _require_complete_mapping_result(crawl_result, _ArasRequestError)
                        if match_rule.get('contractVersion') == '2':
                            from services.ewo_binding_records import attach_ewo_source_ids
                            rows = attach_ewo_source_ids(crawl_result)
                    elif aras_report == "paa":
                        from services.project_status_connectors import ArasProjectStatusConnector
                        paa_filters = ArasProjectStatusConnector._paa_filters(match_rule)
                        crawl_result = aras_client.crawl_paa_report_all(
                            paa_filters, max_records=MAX_AGGREGATE_RECORDS
                        )
                        rows = _require_complete_mapping_result(crawl_result, _ArasRequestError)
                    else:
                        from services.project_status_connectors import ArasProjectStatusConnector
                        rows = ArasProjectStatusConnector._collect_ncr_rows(
                            aras_client, aras_report, match_rule
                        )
                    if cache_key:
                        _set_discovery_session_cache(cache_key, rows)
                return discovery_service.observe(
                    deliverable_id, "aras", rows, selected,
                    aggregate=bool(match_rule["aggregate"]), match_rule=match_rule,
                )

            def submit_discovery_task(system):
                """统一域会话在位时把全量取证转后台任务（G5/C3 异步化）。

                返回 202（新任务或同参数重挂）或 409（不同参数的在途任务冲突）；
                引擎不可用或凭据准入不通过（密码/显式 Cookie 模式，凭据红线禁止
                入库）时返回 None，调用方回落到既有同步路径，行为零回归。
                """
                runner = _crawl_runner_from_request()
                session, _gate_error = _async_session_gate(system, payload)
                if runner is None or session is None:
                    return None
                params_hash = _mapping_discovery_params_hash(match_rule, values, selected)

                def worker(ctx):
                    # 统一域会话是应用内存对象（凭据红线：任务参数不落库任何凭据）；
                    # app_context 内重建客户端以复用共享会话，worker 线程禁止关闭它。
                    try:
                        with app.app_context():
                            observation = run_observation(
                                lambda: (
                                    _build_tdc_client_from_payload(
                                        payload, app.config["TDC_ALLOWED_HOSTS"]
                                    )
                                    if source_type == "tdc"
                                    else _build_aras_client_from_payload(
                                        payload, app.config["ARAS_ALLOWED_HOSTS"]
                                    )
                                ),
                                should_stop=lambda: ctx.is_cancelled,
                            )
                            ctx.update_progress(percent=95, stage="取证完成，落盘结果")
                            artifact = ctx.downloads_dir / f"{ctx.task_id}.result.json"
                            artifact.write_text(
                                json.dumps(
                                    {"result": observation, "paramsHash": params_hash},
                                    ensure_ascii=False,
                                ),
                                encoding="utf-8",
                            )
                            ctx.set_artifact(artifact)
                            ctx.update_progress(percent=100, stage="映射取证完成")
                    finally:
                        # G5（顾问复审 F2）：cancel_task 会在 worker 仍运行时就把 DB
                        # 行写为 cancelled（Aras 单次导出不可中断），注册表若以 DB
                        # 终态为准会提前放行新任务，造成同交付物双 worker。键的释放
                        # 以 worker 实际退出为准。
                        with _MAPPING_DISCOVERY_TASKS_LOCK:
                            entry = _MAPPING_DISCOVERY_TASKS.get(deliverable_id)
                            if entry is not None and entry.get("task_id") == ctx.task_id:
                                _MAPPING_DISCOVERY_TASKS.pop(deliverable_id, None)

                task_params = {
                    "deliverable_id": deliverable_id,
                    "wizard_session_id": wizard_session_id,
                    "aggregate": bool(match_rule.get("aggregate")),
                    "params_hash": params_hash,
                }
                with _MAPPING_DISCOVERY_TASKS_LOCK:
                    entry = _MAPPING_DISCOVERY_TASKS.get(deliverable_id)
                    if entry is not None:
                        # G5（顾问复审 F2）：注册键以 worker 实际退出为准释放
                        # （worker finally 弹出）；cancel_task 会提前把 DB 行写成
                        # 终态，不得以 DB 状态判占用，否则同交付物会出现双 worker。
                        if entry.get("params_hash") == params_hash:
                            # 重新挂接：本次请求的令牌同样属于该任务（令牌→任务关联持续到 worker 退出）。
                            if cancel_token:
                                entry.setdefault("tokens", []).append(cancel_token)
                            existing = runner.get_task(entry.get("task_id", ""))
                            return _mapping_discovery_accepted_response(
                                entry["task_id"],
                                str((existing or {}).get("status") or "queued"),
                                params_hash,
                            )
                        return _json_error(
                            409,
                            "DiscoveryInProgress",
                            "该交付物已有不同的映射取证任务在后台进行，请等待其完成或取消后再试",
                        )
                    tid = runner.submit_task("mapping_discovery", system, task_params, worker)
                    _MAPPING_DISCOVERY_TASKS[deliverable_id] = {
                        "task_id": tid,
                        "params_hash": params_hash,
                        "tokens": [cancel_token] if cancel_token else [],
                    }
                return _mapping_discovery_accepted_response(tid, "queued", params_hash)

            def inline_conflict_response():
                """G5（顾问复审 F6）：后台任务在途期间，密码/Cookie 模式的同步回落
                也要受单在途约束，否则两条路径会对同一交付物并发取证。
                占用以注册键为准（worker finally 弹出），不看 DB 终态（F2）。"""
                runner = _crawl_runner_from_request()
                if runner is None:
                    return None
                with _MAPPING_DISCOVERY_TASKS_LOCK:
                    entry = _MAPPING_DISCOVERY_TASKS.get(deliverable_id)
                if entry is None:
                    return None
                return _json_error(
                    409,
                    "DiscoveryInProgress",
                    "该交付物已有映射取证任务在后台进行，请等待其完成或取消后再试",
                )

            if deliverable_id in {"VPI-T2-D2", "VPI-T2-D5"}:
                if is_stability_check:
                    # F10: 独立轻量签名采样核验（只拉取第 1 页 50 条，秒级完成，保持同步）
                    client = _build_tdc_client_from_payload(
                        payload, app.config["TDC_ALLOWED_HOSTS"]
                    )
                    if deliverable_id == "VPI-T2-D2":
                        paged_result = client.query_sor_page(
                            _tdc_sor_filters(values), page=1, page_size=50
                        )
                        sample_rows, sample_total = paged_result.rows, paged_result.total
                    elif document_no:
                        # 流水单号只能本地判定：采样必须与首次观测同源（全量抓取 +
                        # 精确匹配）。拿"全量第 1 页"去比"匹配到的那一行"必然误报
                        # 不稳定，让带流水单号的绑定永远无法就绪。
                        crawl_result = client.crawl_data_model_all(
                            _tdc_data_model_filters(values),
                            max_records=MAX_AGGREGATE_RECORDS,
                        )
                        if not _mapping_result_is_complete(crawl_result):
                            raise _TDCRequestError(
                                "抓取不完整，无法判定流水单号，请重试",
                                "IncompleteDiscovery",
                                422,
                                None,
                                _pagination_diagnostic(crawl_result, len(crawl_result.rows)),
                            )
                        sample_rows, _ = match_serial(crawl_result.rows, document_no)
                        if len(sample_rows) > 1:
                            raise _TDCRequestError("该流水单号命中多行，请核对后重试")
                        full_total = getattr(crawl_result, "total", None)
                        sample_total = (
                            full_total
                            if isinstance(full_total, int) and not isinstance(full_total, bool)
                            else len(crawl_result.rows)
                        )
                    else:
                        paged_result = client.query_data_model_page(
                            _tdc_data_model_filters(values), page=1, page_size=50
                        )
                        sample_rows, sample_total = paged_result.rows, paged_result.total
                    if sample_total is None or sample_total < 0:
                        raise _TDCRequestError("TDC 返回的总记录数无效")
                    result = discovery_service.observe_stability_sample(
                        deliverable_id, "tdc", sample_rows, sample_total,
                        aggregate=bool(match_rule["aggregate"]), match_rule=match_rule,
                    )
                    mismatch = result.get("mismatch") if isinstance(result, dict) else None
                    if mismatch:
                        emit(
                            "mapping_stability_mismatch",
                            {
                                "stability_reason": str(mismatch.get("reason") or ""),
                                "expected_count": mismatch.get("expected"),
                                "actual_count": mismatch.get("actual"),
                            },
                        )
                    return jsonify({"ok": True, "data": result})

                async_response = submit_discovery_task("tdc")
                if async_response is not None:
                    return async_response
                inline_conflict = inline_conflict_response()
                if inline_conflict is not None:
                    return inline_conflict
                client = _build_tdc_client_from_payload(
                    payload, app.config["TDC_ALLOWED_HOSTS"]
                )
                result = run_observation(
                    lambda: client,
                    should_stop=cancel_event.is_set if cancel_event is not None else None,
                )
            elif deliverable_id in {"VPI-T2-D3", "VPI-T2-D6", "VPI-T2-D7", "VPI-T2-D8"}:
                async_response = submit_discovery_task("aras")
                if async_response is not None:
                    return async_response
                inline_conflict = inline_conflict_response()
                if inline_conflict is not None:
                    return inline_conflict
                aras_client = _build_aras_client_from_payload(
                    payload, app.config["ARAS_ALLOWED_HOSTS"]
                )
                result = run_observation(lambda: aras_client)
            else:
                return _json_error(404, "NotFound", "未找到交付物")
            return jsonify({"ok": True, "data": result})
        except CrawlCancelled:
            # 前端已 abort，不会读到这个响应；返回明确语义便于诊断录制与人工重放。
            return _json_error(409, "Cancelled", "映射取证已取消")
        except (_TDCRequestError, TDCCrawlerError, TDCAuthError) as exc:
            return _tdc_error_response(exc, "mapping-discovery", "query")
        except (_ArasRequestError, ArasCrawlerError, ArasAuthError) as exc:
            return _aras_error_response(exc, aras_client, "mapping-discovery")
        except ValueError as exc:
            if deliverable_id in {"VPI-T2-D2", "VPI-T2-D5"}:
                return _tdc_error_response(exc, "mapping-discovery", "query")
            return _aras_error_response(exc, aras_client, "mapping-discovery")
        except Exception as exc:
            logger.exception("mapping discovery failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))
        finally:
            _release_discovery_cancel(cancel_token, cancel_event)

    @app.post("/api/project-status/deliverables/<deliverable_id>/mapping-discovery/cancel")
    def api_project_status_mapping_discovery_cancel(deliverable_id: str):
        """请求停止正在进行的映射取证（前端 abort 后调用）。

        只置位协作式取消标志：TDC 分页抓取会在下一个分页边界停止；
        Aras 整本工作簿导出是单次调用，登记对它只是尽力而为。
        """
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        # 取消不触达上游，因此不要求 base_url（_request_payload 的上游查询校验在此不适用）；
        # 前端 abort 后只带 cancelToken 调用本端点。
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _json_error(400, "ValidationError", "JSON object body is required")
        token = payload.get("cancelToken")
        if not isinstance(token, str) or not _DISCOVERY_CANCEL_TOKEN_RE.match(token):
            return _json_error(400, "ValidationError", "cancelToken 非法")
        with _DISCOVERY_CANCEL_LOCK:
            event = _DISCOVERY_CANCEL_TOKENS.get(token)
        if event is not None:
            event.set()
            return jsonify({"ok": True, "data": {"cancelled": True, "deliverableId": deliverable_id}})
        # G5（顾问复审 F1）：后台任务路径下，握手响应未被前端读到前 abort 时
        # 手里没有 taskId，旧令牌也已在 202 落定后释放——按交付物查注册表
        # 兜底协作取消，避免"服务端照跑、前端已放弃"（F7 禁止路线）。
        runner = _crawl_runner_from_request()
        if runner is not None:
            with _MAPPING_DISCOVERY_TASKS_LOCK:
                entry = _MAPPING_DISCOVERY_TASKS.get(deliverable_id)
            # 只取消该令牌所属的任务：过期/未知令牌（例如旧请求的延迟取消）不得取消后来启动的新任务。
            if entry is not None and token in entry.get("tokens", ()):
                existing = runner.get_task(entry.get("task_id", ""))
                if (
                    existing is not None
                    and existing.get("status") not in _MAPPING_DISCOVERY_TERMINAL_STATUSES
                ):
                    runner.cancel_task(entry["task_id"])
                    return jsonify(
                        {
                            "ok": True,
                            "data": {
                                "cancelled": True,
                                "deliverableId": deliverable_id,
                                "taskId": entry["task_id"],
                                "status": "cancelled",
                            },
                        }
                    )
        return jsonify({"ok": True, "data": {"cancelled": False, "reason": "not_running"}})

    @app.get("/api/project-status/analytics")
    def api_project_status_analytics():
        try:
            response = jsonify({"ok": True, "data": analytics_service.overview()})
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception as exc:
            logger.exception("project status analytics failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.get("/api/project-status/runs")
    def api_project_status_runs():
        deliverable_id = request.args.get("deliverableId")
        try:
            limit = _positive_int(request.args.get("limit"), 100)
            response = jsonify({"ok": True, "data": analytics_service.runs(deliverable_id, limit)})
            response.headers["Cache-Control"] = "no-store"
            return response
        except (TypeError, ValueError) as exc:
            return _json_error(422, "ValidationError", _sanitize_error_message(exc))
        except Exception as exc:
            logger.exception("project status runs failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.get("/api/project-status/runs/<int:run_id>/artifacts")
    def api_project_status_run_artifacts(run_id: int):
        try:
            if db.get_sync_run(run_id) is None:
                return _json_error(404, "NotFound", "未找到同步运行")
            data = {"runId": run_id, "artifacts": db.list_sync_artifacts(run_id)}
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception as exc:
            logger.exception("project status artifacts failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.get("/api/project-status/deliverables/<deliverable_id>/unified-status")
    def api_project_status_unified_status(deliverable_id: str):
        """Expose one public status contract for EWO, PAA, and NCR."""
        try:
            current = current_project_status("VPI-T2")
            deliverable = next(
                (item for item in (current or {}).get("deliverables", [])
                 if item.get("id") == deliverable_id),
                None,
            )
            if deliverable is None:
                return _json_error(404, "NotFound", "未找到交付物")
            policy = update_service.get_update_policy(deliverable_id) or {}
            analytics = analytics_service.overview()
            analytic_item = next(
                (item for item in analytics.get("deliverables", [])
                 if item.get("deliverableId") == deliverable_id),
                {},
            )
            mapping = discovery_service.history(deliverable_id)
            mapping_latest = (mapping.get("observations") or [{}])[0]
            policy_sync = str(policy.get("syncState") or "").casefold()
            sync_state = (
                policy_sync if policy_sync in {state.value for state in SyncState}
                else SyncState.MANUAL.value
            )
            credential_available = bool(policy.get("credentialAvailable"))
            auth_error = str(policy.get("lastErrorType") or "").casefold()
            auth_state = (
                AuthState.CREDENTIAL_INVALID.value
                if auth_error in {"auth", "authentication", "credential", "credential_invalid", "credential_unavailable"}
                else AuthState.AUTHENTICATED.value
                if credential_available
                else AuthState.CREDENTIAL_MISSING.value
            )
            mapping_state = str(mapping_latest.get("state") or "").casefold()
            query_error = str(policy.get("lastErrorType") or "").casefold()
            query_state = (
                QueryState.SERVICE_UNAVAILABLE.value
                if query_error in {"connection", "connection_error", "service_unavailable", "network", "timeout"}
                else QueryState.FAILED.value
                if query_error in {"failed", "query_failed", "invalid_response"}
                else QueryState.MATCHED.value if mapping_state in {"matched", "selected"}
                else QueryState.NO_MATCH.value if mapping_state in {"no_match", "not_found", "ambiguous", "key_changed", "missing_fields"}
                else QueryState.IDLE.value
            )
            ewo = UnifiedObjectStatus(
                kind="ewo",
                id=deliverable_id,
                source="aras" if deliverable_id == "VPI-T2-D3" else "project_status",
                external_key=str(policy.get("externalKey") or ""),
                auth_state=auth_state,
                query_state=query_state,
                sync_state=sync_state,
                stage=deliverable.get("status") or analytic_item.get("stage"),
                matched_fields=tuple(
                    (mapping_latest.get("fieldReport") or {}).get("fields") or ()
                ),
                errors=tuple(filter(None, [redact_sensitive_text(policy.get("lastErrorMessage") or "")])),
                last_updated=policy.get("updatedAt") or deliverable.get("updatedAt"),
                content={
                    "report_type": "EWO",
                    "sync_state": sync_state,
                    "last_success_at": policy.get("lastSuccessAt"),
                    "error": redact_sensitive_text(policy.get("lastErrorMessage") or "") or None,
                },
            )
            objects = [ewo]
            for job in archive_admin_service.list_jobs():
                template = str(job.get("templateKey") or job.get("jobKey") or "")
                if template not in {"aras_paa", "aras_ncr_progress", "aras_ncr_detail"}:
                    continue
                kind = "paa" if template == "aras_paa" else "ncr"
                job_sync = str(job.get("syncState") or "").casefold()
                if job_sync not in {state.value for state in SyncState}:
                    job_sync = SyncState.MANUAL.value
                job_auth = (
                    AuthState.CREDENTIAL_INVALID.value
                    if str(job.get("lastErrorType") or "").casefold()
                    in {"auth", "authentication", "credential", "credential_invalid", "credential_unavailable"}
                    else AuthState.AUTHENTICATED.value
                    if job.get("credentialAvailable")
                    else AuthState.CREDENTIAL_MISSING.value
                )
                job_query = (
                    QueryState.SERVICE_UNAVAILABLE.value
                    if str(job.get("lastErrorType") or "").casefold() in {
                        "connection", "connection_error", "service_unavailable",
                        "timeout", "credential_unavailable",
                    }
                    else QueryState.FAILED.value
                    if job.get("lastErrorType")
                    else QueryState.MATCHED.value if job.get("lastSuccessAt")
                    else QueryState.IDLE.value
                )
                objects.append(UnifiedObjectStatus(
                    kind=kind,
                    id=str(job.get("jobKey") or job.get("id")),
                    source="aras",
                    external_key="",
                    auth_state=job_auth,
                    query_state=job_query,
                    sync_state=job_sync,
                    stage=str(job.get("reportType") or ""),
                    matched_fields=(),
                    errors=tuple(filter(None, [redact_sensitive_text(job.get("lastErrorMessage") or "")])),
                    last_updated=job.get("updatedAt"),
                    content={
                        "report_type": str(job.get("reportType") or template),
                        "sync_state": job_sync,
                        "last_success_at": job.get("lastSuccessAt"),
                        "error": redact_sensitive_text(job.get("lastErrorMessage") or "") or None,
                    },
                ))
            response = jsonify({"ok": True, "data": {"objects": [item.to_dict() for item in objects]}})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "未找到交付物")
        except Exception as exc:
            logger.exception("project status unified status failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.get("/api/project-status/deliverables/<deliverable_id>/debug-bundle")
    def api_project_status_debug_bundle(deliverable_id: str):
        """Return an offline, allowlisted and redacted diagnostic bundle."""
        requested_format = request.args.get("format", "json").strip().casefold()
        if requested_format not in {"json", "zip"}:
            return _json_error(422, "ValidationError", "format 必须是 json 或 zip")
        try:
            policy = update_service.get_update_policy(deliverable_id)
            if policy is None:
                return _json_error(404, "NotFound", "未找到交付物")
            analytics = cast(dict[str, Any], next(
                (
                    item
                    for item in analytics_service.overview().get("deliverables", [])
                    if item.get("deliverableId") == deliverable_id
                ),
                {},
            ))
            mapping = discovery_service.history(deliverable_id)
            runs = analytics_service.runs(deliverable_id, 20)
            context = {
                "page": "project-status-deliverable-detail",
                "deliverableId": deliverable_id,
                "policy": policy,
                "analytics": analytics,
                "mapping": mapping,
                "sectionRollup": section_rollup_store.get(),
                "version": app.config.get("APP_VERSION", "unknown"),
                "timestamp": datetime.now().astimezone().isoformat(),
            }
            events = runs.get("runs", []) if isinstance(runs, dict) else []
            bundle = build_debug_bundle(context, events)
            if requested_format == "json":
                response = jsonify(bundle)
                response.headers["Cache-Control"] = "no-store"
                return response
            buffer = io.BytesIO()
            temp_file = tempfile.NamedTemporaryFile(
                prefix="vse_debug_", suffix=".zip", delete=False
            )
            temp_path = Path(temp_file.name)
            temp_file.close()
            try:
                export_debug_bundle(bundle, temp_path, fmt="zip")
                buffer.write(temp_path.read_bytes())
            finally:
                temp_path.unlink(missing_ok=True)
            buffer.seek(0)
            response = send_file(
                buffer,
                mimetype="application/zip",
                as_attachment=True,
                download_name=f"{deliverable_id}_debug.zip",
            )
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception as exc:
            logger.exception("project status debug bundle failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.post("/api/project-status/deliverables/<deliverable_id>/sync-now")
    def api_project_status_sync_now(deliverable_id: str):
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        # 未知交付物保持 404（先于能力门控，避免 404 退化为 409）。
        _, _, sync_now_deliverable_rows = db.get_project_status("VPI-T2")
        if deliverable_id not in {str(row["id"]) for row in sync_now_deliverable_rows}:
            return _json_error(404, "NotFound", "未找到交付物")
        # sync-now 准入门控由能力注册表驱动（D1/D4 硬编码收敛，终审 P2）。
        sync_block = PROJECT_STATUS_SOURCE_CAPABILITIES.get(deliverable_id, {})
        if not sync_block.get("syncCapable"):
            block_type = str(sync_block.get("syncBlockType") or "ManualOnly")
            block_reason = (
                AFACE_CONTRACT_BLOCKER
                if block_type == "ContractBlocked"
                else str(sync_block.get("blockReason") or "该交付物仅允许手工维护")
            )
            return _json_error(409, block_type, block_reason)
        try:
            update_service.assert_sync_ready(deliverable_id)
            runner = ProjectStatusSyncRunner(
                db,
                update_service,
                create_production_registry(),
            )
            result = runner.run_once(
                deliverable_id=deliverable_id,
                trigger_type="sync_now",
            )
            if len(result.results) != 1:
                return _json_error(409, "SyncNotReady", "同步绑定不可用")
            item = result.results[0]
            data = {
                "exitCode": result.exit_code,
                "result": {
                    "deliverableId": item.deliverable_id,
                    "sourceType": item.source_type,
                    "outcome": item.outcome,
                    "runId": item.run_id,
                    "finalState": item.final_state,
                    "appliedFields": list(item.applied_fields),
                    "skippedFields": dict(item.skipped_fields),
                    "errorType": item.error_type,
                    "errorMessage": item.error_message,
                },
            }
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "未找到交付物")
        except SyncBindingNotReadyError as exc:
            return _json_error(409, "SyncNotReady", _sanitize_error_message(exc))
        except Exception as exc:
            logger.exception("project status sync-now failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.get("/api/project-status/scheduler")
    def api_project_status_scheduler_status():
        from services.project_status_scheduler import get_global_scheduler
        scheduler = get_global_scheduler()
        if scheduler is not None:
            data = scheduler.get_status()
        else:
            bindings = []
            try:
                bindings = db.list_eligible_sync_bindings(None)
            except Exception:
                pass
            data = {
                "running": False,
                "paused": False,
                "intervalSeconds": 900,
                "lastTickAt": None,
                "nextRunSeconds": None,
                "eligibleCount": len(bindings),
                "lastResults": [],
            }
        response = jsonify({"ok": True, "data": data})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/project-status/scheduler/config")
    def api_project_status_scheduler_config():
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _json_error(400, "ValidationError", "JSON object body is required")
        interval = payload.get("intervalSeconds")
        paused = payload.get("paused")
        if interval is not None:
            if isinstance(interval, bool) or not isinstance(interval, int) or interval <= 0:
                return _json_error(400, "ValidationError", "intervalSeconds must be a positive integer")
        if paused is not None:
            if not isinstance(paused, bool):
                return _json_error(400, "ValidationError", "paused must be a boolean")

        from services.project_status_scheduler import get_global_scheduler
        scheduler = get_global_scheduler()
        if scheduler is not None:
            if interval is not None:
                scheduler.set_interval(interval)
            if paused is not None:
                if paused:
                    scheduler.pause()
                else:
                    scheduler.resume()
            data = scheduler.get_status()
        else:
            eligible_count = 0
            try:
                eligible_count = len(db.list_eligible_sync_bindings(None))
            except Exception:
                pass
            data = {
                "running": False,
                "paused": bool(paused),
                "intervalSeconds": interval or 900,
                "lastTickAt": None,
                "nextRunSeconds": None,
                "eligibleCount": eligible_count,
                "lastResults": [],
            }
        response = jsonify({"ok": True, "data": data})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/project-status/scheduler/sync-all")
    def api_project_status_scheduler_sync_all():
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        from services.project_status_scheduler import get_global_scheduler
        scheduler = get_global_scheduler()
        if scheduler is not None:
            results = scheduler.trigger_sync_all(force=True)
        else:
            runner = ProjectStatusSyncRunner(
                db,
                update_service,
                create_production_registry(),
            )
            bindings = []
            try:
                bindings = db.list_eligible_sync_bindings(None)
            except Exception:
                pass
            results = []
            for b in bindings:
                d_id = str(b.get("deliverable_id") or "")
                if not d_id:
                    continue
                try:
                    runner_res = runner.run_once(
                        deliverable_id=d_id,
                        trigger_type="sync_now",
                        validate_runtime_prerequisites=False,
                    )
                    item_info = {"deliverableId": d_id, "status": "success"}
                    if hasattr(runner_res, "results") and runner_res.results:
                        first = runner_res.results[0]
                        item_info["outcome"] = getattr(first, "outcome", None)
                        item_info["finalState"] = getattr(first, "final_state", None)
                        item_info["appliedFields"] = list(getattr(first, "applied_fields", []))
                    results.append(item_info)
                except Exception as exc:
                    results.append({
                        "deliverableId": d_id,
                        "status": "error",
                        "error": _sanitize_error_message(exc),
                    })
        response = jsonify({"ok": True, "data": {"results": results, "count": len(results)}})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.patch("/api/project-status/phases/<phase_id>/milestones")
    def api_project_status_milestones_update(phase_id: str):
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        if phase_id != "VPI-T2":
            return _json_error(404, "NotFound", "未找到项目阶段")
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _json_error(400, "ValidationError", "JSON object body is required")
        unknown = set(payload) - {"milestones", "updatedAt"}
        if unknown:
            return _project_status_validation_error({"request": "包含不允许修改的字段"})
        expected_updated_at = payload.get("updatedAt")
        if not isinstance(expected_updated_at, str) or not expected_updated_at:
            return _project_status_validation_error({"updatedAt": "缺少阶段版本"})
        try:
            project_status = current_project_status(phase_id)
            if project_status is None:
                return _json_error(404, "NotFound", "未找到项目阶段")
            milestones, errors = _validate_project_status_milestones(payload, project_status)
            if errors:
                return _project_status_validation_error(errors)
            db.replace_project_status_milestones(
                phase_id,
                milestones,
                expected_updated_at,
            )
            updated_status = current_project_status(phase_id)
            assert updated_status is not None
            return jsonify({"ok": True, "data": {"projectStatus": updated_status}})
        except KeyError:
            return _json_error(404, "NotFound", "主计划包含不存在的节点")
        except RuntimeError:
            return _json_error(409, "Conflict", "主计划已被其他会话更新，请刷新后重试")
        except Exception as exc:
            logger.exception("api/project-status/phases/milestones 更新失败")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.get("/api/deliverables/catalog")
    def api_deliverables_catalog():
        # 按目录条目反查单一关联注册表，追加 links 字段；只追加，
        # 不修改 _DELIVERABLES_CATALOG 字面量本身，向后兼容。
        registry_by_catalog_id: dict[str, tuple[str, Mapping[str, Any]]] = {}
        linked_deliverable_ids: set[str] = set()
        for candidate_key, candidate in DELIVERABLE_LINK_REGISTRY.items():
            registry_by_catalog_id[str(candidate["catalog_id"])] = (
                candidate_key,
                candidate,
            )
            linked_deliverable_ids.add(str(candidate["deliverable_id"]))
        # displayCode 优先取 project_status_deliverables 表中的实际展示码：
        # 存量库顺延场景（display_code 冲突后重建）下注册表常量可能与项目
        # 状态页展示不一致；一次轻量查询取回映射复用，查不到回退注册表常量。
        actual_display_codes: dict[str, str] = {}
        if linked_deliverable_ids:
            with db.get_connection() as conn:
                placeholders = ", ".join("?" for _ in linked_deliverable_ids)
                rows = conn.execute(
                    "SELECT id, display_code FROM project_status_deliverables "
                    f"WHERE id IN ({placeholders})",
                    tuple(sorted(linked_deliverable_ids)),
                ).fetchall()
            for row in rows:
                code = str(row["display_code"] or "").strip()
                if code:
                    actual_display_codes[str(row["id"])] = code
        deliverables = []
        for item in _DELIVERABLES_CATALOG:
            linked = registry_by_catalog_id.get(str(item.get("id") or ""))
            job_key, entry = linked if linked is not None else (None, None)
            display_code = None
            if entry is not None:
                deliverable_id = str(entry["deliverable_id"])
                display_code = (
                    actual_display_codes.get(deliverable_id)
                    or entry["display_code"]
                )
            enriched = dict(item)
            enriched["links"] = {
                "archiveJobKey": job_key,
                "projectStatusDeliverableId": entry["deliverable_id"] if entry else None,
                "displayCode": display_code,
                "formKey": entry["form_key"] if entry else None,
            }
            deliverables.append(enriched)
        return jsonify(
            {
                "ok": True,
                "data": {
                    "categories": _DELIVERABLE_CATEGORIES,
                    "deliverables": deliverables,
                },
            }
        )

    @app.post("/api/aras/ewo/query")
    def api_aras_ewo_query():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        client: ArasCrawlerClient | None = None
        try:
            client = _build_aras_client_from_payload(payload, app.config["ARAS_ALLOWED_HOSTS"])
            result = client.query_ewo_report(
                _ewo_filters_from_payload(payload),
                page=_positive_int(payload.get("page"), 1),
                page_size=_positive_int(payload.get("page_size"), 50),
                max_records=_positive_int(payload.get("max_records"), 2000),
            )
            table = table_payload("ewo", _safe_rows(result.rows))
            return jsonify(
                {
                    "ok": True,
                    "data": {
                        **table,
                        "page": result.page,
                        "item_ids": result.item_ids,
                        "count": len(result.rows),
                        "queryState": "matched" if result.rows else "empty",
                        **(
                            {"xml": _aras_xml_payload(result, payload)}
                            if _aras_xml_requested(payload)
                            else {}
                        ),
                    },
                }
            )
        except Exception as e:
            return _aras_error_response(e, client, "EWO query")

    @app.post("/api/aras/paa/query")
    def api_aras_paa_query():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        client: ArasCrawlerClient | None = None
        try:
            client = _build_aras_client_from_payload(payload, app.config["ARAS_ALLOWED_HOSTS"])
            result = client.query_paa_report(
                _paa_filters_from_payload(payload),
                page=_positive_int(payload.get("page"), 1),
                page_size=_positive_int(payload.get("page_size"), 50),
                max_records=_positive_int(payload.get("max_records"), 2000),
            )
            table = table_payload("paa", _safe_rows(result.rows))
            return jsonify(
                {
                    "ok": True,
                    "data": {
                        **table,
                        "page": result.page,
                        "item_ids": result.item_ids,
                        "count": len(result.rows),
                        "queryState": "matched" if result.rows else "empty",
                        **(
                            {"xml": _aras_xml_payload(result, payload)}
                            if _aras_xml_requested(payload)
                            else {}
                        ),
                    },
                }
            )
        except Exception as e:
            return _aras_error_response(e, client, "PAA query")

    @app.post("/api/aras/paa/crawl-all")
    def api_aras_paa_crawl_all():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        session, gate_error = _async_session_gate("aras", payload)
        if gate_error is not None:
            return gate_error
        try:
            base_url = str(payload["base_url"]).strip()
            _validate_allowed_base_url(base_url, app.config["ARAS_ALLOWED_HOSTS"])
            filters = _paa_filters_from_payload(payload)
        except Exception as e:
            return _aras_error_response(e, None, "PAA crawl-all")
        page_size = _positive_int(payload.get("page_size"), 50)
        max_pages = _positive_int(payload.get("max_pages"), 20)
        max_records = _positive_int(payload.get("max_records"), 2000)
        include_xml = _aras_xml_requested(payload)

        def worker(ctx):
            client = ArasCrawlerClient(base_url, session=session, timeout=30.0)
            result = client.crawl_paa_report_all(
                filters,
                page_size=page_size,
                max_pages=max_pages,
                max_records=max_records,
                should_stop=lambda: ctx.is_cancelled,
                on_page=lambda page_no, rows_so_far: ctx.update_progress(
                    current=rows_so_far,
                    total=max_records,
                    stage=f"PAA 全量抓取第 {page_no} 页",
                ),
            )
            table = table_payload("paa", _safe_rows(result.rows))
            data: dict[str, Any] = {
                **table,
                "page": result.page,
                "item_ids": result.item_ids,
                "count": len(result.rows),
            }
            xml_payload = _aras_xml_payload(result, payload) if include_xml else None
            if xml_payload:
                data["xml"] = xml_payload
            artifact = ctx.downloads_dir / f"{ctx.task_id}.result.json"
            artifact.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            ctx.set_artifact(artifact)
            ctx.update_progress(percent=100, stage="PAA 全量抓取完成")

        params = {
            "base_url": base_url,
            "filters": asdict(filters),
            "page_size": page_size,
            "max_pages": max_pages,
            "max_records": max_records,
        }
        return _submit_background_task(
            crawl_task_runner, "paa_crawl", "aras", params, worker, error_context="PAA crawl-all"
        )

    @app.post("/api/aras/ncr/progress")
    def api_aras_ncr_progress():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        client: ArasCrawlerClient | None = None
        try:
            client = _build_aras_client_from_payload(payload, app.config["ARAS_ALLOWED_HOSTS"])
            result = client.query_ncr_approval_progress(_ncr_filters_from_payload(payload))
            table = _ncr_table_payload(client, result, "ncr_progress", payload)
            return jsonify(
                {
                    "ok": True,
                    "data": {
                        "file_name": _safe_scalar(result.file_name),
                        "record_id": _safe_scalar(result.record_id),
                        **table,
                    },
                }
            )
        except Exception as e:
            return _aras_error_response(e, client, "NCR progress")

    @app.post("/api/aras/ncr/detail")
    def api_aras_ncr_detail():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        client: ArasCrawlerClient | None = None
        try:
            client = _build_aras_client_from_payload(payload, app.config["ARAS_ALLOWED_HOSTS"])
            result = client.extract_ncr_approval_detail(_ncr_filters_from_payload(payload))
            table = _ncr_table_payload(client, result, "ncr_detail", payload)
            return jsonify(
                {
                    "ok": True,
                    "data": {
                        "file_name": _safe_scalar(result.file_name),
                        **table,
                    },
                }
            )
        except Exception as e:
            return _aras_error_response(e, client, "NCR detail")

    @app.post("/api/aras/ncr/progress/download")
    def api_aras_ncr_progress_download():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        temp_dir = Path(tempfile.mkdtemp(prefix="aras_ncr_progress_"))
        client: ArasCrawlerClient | None = None
        try:
            client = _build_aras_client_from_payload(payload, app.config["ARAS_ALLOWED_HOSTS"])
            result = client.query_ncr_approval_progress(_ncr_filters_from_payload(payload))
            saved = client.download_ncr_progress_file(result, temp_dir)
            data = saved.read_bytes()
            shutil.rmtree(temp_dir, ignore_errors=True)
            return send_file(
                io.BytesIO(data),
                as_attachment=True,
                download_name=_safe_attachment_basename(saved.name, "ncr_progress.xlsx"),
            )
        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return _aras_error_response(e, client, "NCR progress download")

    @app.post("/api/aras/ewo/export")
    def api_aras_ewo_export():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        session, gate_error = _async_session_gate("aras", payload)
        if gate_error is not None:
            return gate_error
        try:
            base_url = str(payload["base_url"]).strip()
            _validate_allowed_base_url(base_url, app.config["ARAS_ALLOWED_HOSTS"])
            filters = _ewo_filters_from_payload(payload)
        except Exception as e:
            return _aras_error_response(e, None, "EWO export")
        max_pages = _positive_int(payload.get("max_pages"), _EXPORT_DEFAULT_MAX_PAGES)
        max_records = _positive_int(payload.get("max_records"), _EXPORT_DEFAULT_MAX_RECORDS)

        def worker(ctx):
            client = ArasCrawlerClient(base_url, session=session, timeout=30.0)
            page = client.crawl_ewo_report_all(
                filters,
                page_size=_EXPORT_PAGE_SIZE,
                max_pages=max_pages,
                max_records=max_records,
                should_stop=lambda: ctx.is_cancelled,
                on_page=lambda page_no, rows_so_far: ctx.update_progress(
                    current=rows_so_far,
                    total=max_records,
                    stage=f"EWO 全量抓取第 {page_no} 页",
                ),
            )
            ctx.update_progress(stage="正在生成 CSV 导出文件")
            export = export_report_contract_csv(
                "ewo",
                page.rows,
                output_dir=ctx.downloads_dir,
                file_name=f"ewo_export_{ctx.task_id}.csv",
            )
            ctx.set_artifact(export.path)
            if len(page.rows) >= max_records or (
                getattr(page, "page", None) is not None and getattr(page, "page") >= max_pages
            ):
                ctx.update_progress(
                    percent=100, stage="导出完成（结果已按 max_records/max_pages 截断）"
                )
            else:
                ctx.update_progress(percent=100, stage="导出完成")

        params = {
            "base_url": base_url,
            "filters": asdict(filters),
            "max_pages": max_pages,
            "max_records": max_records,
        }
        return _submit_background_task(
            crawl_task_runner, "ewo_export", "aras", params, worker, error_context="EWO export"
        )

    @app.post("/api/aras/paa/export")
    def api_aras_paa_export():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        session, gate_error = _async_session_gate("aras", payload)
        if gate_error is not None:
            return gate_error
        try:
            base_url = str(payload["base_url"]).strip()
            _validate_allowed_base_url(base_url, app.config["ARAS_ALLOWED_HOSTS"])
            filters = _paa_filters_from_payload(payload)
        except Exception as e:
            return _aras_error_response(e, None, "PAA export")
        max_pages = _positive_int(payload.get("max_pages"), _EXPORT_DEFAULT_MAX_PAGES)
        max_records = _positive_int(payload.get("max_records"), _EXPORT_DEFAULT_MAX_RECORDS)

        def worker(ctx):
            client = ArasCrawlerClient(base_url, session=session, timeout=30.0)
            page = client.crawl_paa_report_all(
                filters,
                page_size=_EXPORT_PAGE_SIZE,
                max_pages=max_pages,
                max_records=max_records,
                should_stop=lambda: ctx.is_cancelled,
                on_page=lambda page_no, rows_so_far: ctx.update_progress(
                    current=rows_so_far,
                    total=max_records,
                    stage=f"PAA 全量抓取第 {page_no} 页",
                ),
            )
            ctx.update_progress(stage="正在生成 CSV 导出文件")
            export = export_report_contract_csv(
                "paa",
                page.rows,
                output_dir=ctx.downloads_dir,
                file_name=f"paa_export_{ctx.task_id}.csv",
            )
            ctx.set_artifact(export.path)
            if len(page.rows) >= max_records or (
                getattr(page, "page", None) is not None and getattr(page, "page") >= max_pages
            ):
                ctx.update_progress(
                    percent=100, stage="导出完成（结果已按 max_records/max_pages 截断）"
                )
            else:
                ctx.update_progress(percent=100, stage="导出完成")

        params = {
            "base_url": base_url,
            "filters": asdict(filters),
            "max_pages": max_pages,
            "max_records": max_records,
        }
        return _submit_background_task(
            crawl_task_runner, "paa_export", "aras", params, worker, error_context="PAA export"
        )

    @app.post("/api/aras/ncr/detail/download")
    def api_aras_ncr_detail_download():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        temp_dir = Path(tempfile.mkdtemp(prefix="aras_ncr_detail_"))
        client: ArasCrawlerClient | None = None
        try:
            client = _build_aras_client_from_payload(payload, app.config["ARAS_ALLOWED_HOSTS"])
            result = client.extract_ncr_approval_detail(_ncr_filters_from_payload(payload))
            file_name = getattr(result, "file_name", None)
            if not isinstance(file_name, str) or not file_name.strip():
                shutil.rmtree(temp_dir, ignore_errors=True)
                return _json_error(502, "ArasCrawlerError", "NCR detail did not produce a file_name")
            saved = client.download_ncr_detail_file(file_name.strip(), temp_dir)
            data = saved.read_bytes()
            shutil.rmtree(temp_dir, ignore_errors=True)
            response = send_file(
                io.BytesIO(data),
                as_attachment=True,
                download_name=_safe_attachment_basename(file_name.strip()),
            )
            return response
        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return _aras_error_response(e, client, "NCR detail download")

    @app.post("/api/tdc/data-model/query")
    def api_tdc_data_model_query():
        return _tdc_report_query(
            "data_model",
            _tdc_data_model_filters,
            _TDC_DATA_MODEL_FILTER_NAMES,
            app.config["TDC_ALLOWED_HOSTS"],
        )

    @app.post("/api/tdc/data-model/crawl-all")
    def api_tdc_data_model_crawl_all():
        return _tdc_report_crawl(
            "data_model",
            _tdc_data_model_filters,
            _TDC_DATA_MODEL_FILTER_NAMES,
            app.config["TDC_ALLOWED_HOSTS"],
        )

    @app.post("/api/tdc/data-model/export")
    def api_tdc_data_model_export():
        return _tdc_report_export(
            "data_model",
            _tdc_data_model_filters,
            _TDC_DATA_MODEL_FILTER_NAMES,
            app.config["TDC_ALLOWED_HOSTS"],
        )

    @app.post("/api/tdc/sor/car-type-projects")
    def api_tdc_sor_car_type_projects():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        client: TDCCrawlerClient | None = None
        try:
            client = _build_tdc_client_from_payload(payload, app.config["TDC_ALLOWED_HOSTS"])
            projects = client.list_car_type_projects()
            return jsonify({"ok": True, "data": {"projects": _tdc_sor_project_options(projects)}})
        except Exception as exc:
            return _tdc_error_response(exc, "sor", "car-type-projects")
        finally:
            _close_owned_tdc_client(client)

    @app.post("/api/tdc/sor/query")
    def api_tdc_sor_query():
        return _tdc_report_query(
            "sor",
            _tdc_sor_filters,
            _TDC_SOR_FILTER_NAMES,
            app.config["TDC_ALLOWED_HOSTS"],
        )

    @app.post("/api/tdc/sor/crawl-all")
    def api_tdc_sor_crawl_all():
        return _tdc_report_crawl(
            "sor",
            _tdc_sor_filters,
            _TDC_SOR_FILTER_NAMES,
            app.config["TDC_ALLOWED_HOSTS"],
        )

    @app.post("/api/tdc/sor/export")
    def api_tdc_sor_export():
        return _tdc_report_export(
            "sor",
            _tdc_sor_filters,
            _TDC_SOR_FILTER_NAMES,
            app.config["TDC_ALLOWED_HOSTS"],
        )

    @app.post("/api/tdc/a-face/query")
    def api_tdc_a_face_query():
        return _json_error(400, "ContractBlocker", AFACE_CONTRACT_BLOCKER)

    @app.post("/api/tdc/a-face/crawl-all")
    def api_tdc_a_face_crawl_all():
        return _json_error(400, "ContractBlocker", AFACE_CONTRACT_BLOCKER)

    @app.post("/api/tdc/a-face/export")
    def api_tdc_a_face_export():
        return _json_error(400, "ContractBlocker", AFACE_CONTRACT_BLOCKER)

    from web.diagnostics import install_diagnostics
    install_diagnostics(app, local_guard=_local_web_mutation_error)
    _install_plugin_host(app, db, plugin_dirs=plugin_dirs, plugin_only=plugin_only)
    return app


def _json_ok(data: Any = None, status: int = 200):
    response = jsonify({"ok": True, "data": data})
    response.headers["Cache-Control"] = "no-store"
    return response, status


def _install_plugin_host(
    app: Flask,
    db: DatabaseManager,
    *,
    plugin_dirs: Sequence[Path] | None,
    plugin_only: Sequence[str] | None,
) -> None:
    """加载 `plugins/` 下的功能插件；旧路由全部注册完成后再加载，插件不能覆盖它们。"""
    import mimetypes
    from types import MappingProxyType

    from host import HostContext, PluginRegistry
    from host.updates import PackageError, PluginUpdates

    # Windows 注册表可能把 .js 映射成 text/plain，浏览器会拒绝执行 ES Module。
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/javascript", ".mjs")

    if plugin_only is None:
        env_only = os.environ.get("VSE_TOOLBOX_PLUGIN_ONLY", "").strip()
        plugin_only = [item.strip() for item in env_only.split(",") if item.strip()] or None
    context = HostContext(
        db=db,
        data_dir=Path(db.db_path).parent,
        json_ok=_json_ok,
        json_error=_json_error,
        local_guard=_local_web_mutation_error,
        services=MappingProxyType(app.extensions),
    )
    updates = PluginUpdates(context.data_dir / "plugin-updates")
    try:
        applied = updates.apply_pending()
    except OSError:
        logger.exception("applying staged plugin packages failed")
        applied = []
    for item in applied:
        logger.info("Plugin package %s %s activated", item["id"], item["version"])
    registry = PluginRegistry(plugin_dirs, only=plugin_only, overrides=updates.active_dirs())
    registry.load_all(app, context)
    for plugin_id, bundled_version in registry.superseded.items():
        logger.info("Plugin %s: bundled %s supersedes installed package", plugin_id, bundled_version)
        updates.supersede(plugin_id, bundled_version=bundled_version)
    # 已安装的新版本启动失败：切回上一版本（或随包内置版本）并当场重新加载。
    for record in list(registry.records):
        if record.source != "installed" or record.status == "loaded" or record.id is None:
            continue
        previous = updates.rollback(record.id, reason=record.error or record.status)
        fallback = updates.active_dirs().get(record.id) if previous else registry.bundled_dirs.get(record.id)
        logger.warning("Plugin %s rolled back to %s", record.id, previous or "bundled")
        if fallback is not None:
            registry.load_dir(app, context, fallback, source="installed" if previous else "bundled")
    app.extensions["plugin_registry"] = registry
    app.extensions["plugin_updates"] = updates

    @app.get("/api/host/manifest")
    def api_host_manifest():
        return _json_ok(registry.manifest_payload())

    def _updates_payload() -> dict[str, Any]:
        payload = updates.status()
        payload["plugins"] = [
            {
                "id": r.id,
                "name": r.manifest.name if r.manifest else r.path.name,
                "version": r.manifest.version if r.manifest else None,
                "status": r.status,
                "source": r.source,
            }
            for r in registry.records
        ]
        return payload

    @app.get("/api/host/updates")
    def api_host_updates():
        return _json_ok(_updates_payload())

    @app.post("/api/host/updates/import")
    def api_host_updates_import():
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            return _json_error(400, "ValidationError", "请选择 .vsepkg 插件包")
        data = upload.read()
        try:
            from host.updates import verify_package

            package = verify_package(data, updates.trusted_keys)
            record = registry.record_for(package.id)
            current = record.manifest.version if record and record.manifest and record.status == "loaded" else None
            updates.stage(data, current_version=current)
        except PackageError as exc:
            return _json_error(422, "PackageRejected", str(exc))
        except OSError as exc:
            logger.exception("staging plugin package failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))
        return _json_ok({
            "id": package.id,
            "version": package.version,
            "previous": current,
            "message": "插件包已校验通过，重启 VSE Toolbox 后生效",
            "updates": _updates_payload(),
        })

    @app.post("/api/host/updates/<plugin_id>/discard")
    def api_host_updates_discard(plugin_id: str):
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        if not updates.discard_pending(plugin_id):
            return _json_error(404, "NotFound", "没有待生效的插件包")
        return _json_ok(_updates_payload())

    @app.post("/api/host/updates/<plugin_id>/rollback")
    def api_host_updates_rollback(plugin_id: str):
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        if plugin_id not in updates.read_state()["plugins"]:
            return _json_error(404, "NotFound", "该插件没有通过插件包安装的版本")
        previous = updates.rollback(plugin_id, reason="用户手动回滚")
        data = _updates_payload()
        data["message"] = f"已切回 {previous or '随包内置版本'}，重启后生效"
        return _json_ok(data)


if __name__ == "__main__":
    excel_roots = load_production_excel_roots()
    app = create_app(excel_roots=excel_roots)
    raw_port = os.environ.get("VSE_TOOLBOX_PORT", "").strip()
    try:
        selected_port = int(raw_port) if raw_port else FLASK_PORT
    except ValueError:
        selected_port = FLASK_PORT
    if not 1 <= selected_port <= 65535:
        selected_port = FLASK_PORT
    if "--diagnostics" in sys.argv:
        try:
            app.extensions["diagnostic_recorder"].start()
        except Exception:
            print("诊断录制未能开启，请在页面诊断控件中检查状态。")
    app.run(host=FLASK_HOST, port=selected_port, debug=False, use_reloader=False)
