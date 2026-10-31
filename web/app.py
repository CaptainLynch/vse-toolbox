# -*- coding: utf-8 -*-
"""
web/app.py — WEB 适配层：Flask 应用工厂 + /api/overview 路由

架构约束:
    - 唯一允许 import flask 的文件
    - 路由只做序列化与 HTTP 响应，不写业务 SQL
    - FLASK_HOST / FLASK_PORT 从 core.config 取值
    - service/core 层对 Flask 无感知
"""

import csv
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
    MATCH_FIELD_CONTRACT,
    MILESTONE_STATUSES,
    PROJECT_STATUS_SOURCE_CAPABILITIES,
    current_stage_label,
    deliverable_display_state,
    derive_effective_progress,
    find_job_key_by_deliverable_id,
    find_registry_entry_by_deliverable_id,
    milestone_display_status,
    project_status_board_visible,
    project_status_retired,
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
    normalize_section_selection,
    resolve_section,
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
    MATCH_RULE_TEXT_LIMIT,
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
    authoritative_identity_field,
    authoritative_record_identity,
    identity_field_name,
    identity_fields,
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
from services.data_model_watchlist import (
    MAX_WATCHLIST_BYTES,
    MULTI_SERIAL_DISABLED_MESSAGE,
    MULTI_SERIAL_EXTERNAL_KEY_MESSAGE,
    WatchlistError,
    match_serial,
    match_serials,
    multi_serial_enabled,
    normalize_serial_set,
    normalize_single_serial,
)
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
from services.tdc_official_rows import (
    OfficialWorkbookContractError,
    OfficialWorkbookTruncated,
    OfficialWorkbookUnreadable,
    official_contract_headers,
    read_official_tdc_rows,
)
from services.windows_http import WinHTTPError, WinHTTPTimeoutError

from web.crawler_boot import (  # noqa: F401  W13-06/07/09 迁移别名
    CrawlerRouteDeps,
    _ArasRequestError,
    _CSV_FORMULA_PREFIXES,
    _DEFAULT_ARAS_ALLOWED_HOSTS,
    _DELIVERABLES_CATALOG,
    _DELIVERABLE_CATEGORIES,
    _EXPORT_DEFAULT_MAX_PAGES,
    _EXPORT_DEFAULT_MAX_RECORDS,
    _EXPORT_PAGE_SIZE,
    _INVALID_ATTACHMENT_CHARS_RE,
    _NCR_PREVIEW_MAX_ROWS,
    _SENSITIVE_RESPONSE_KEYS,
    _STATISTICS_MAX_HISTORY_ROWS,
    _STRICT_NUMBER_LITERAL,
    _TDCRequestError,
    _TDC_CSV_NAME_RE,
    _TDC_DATA_MODEL_FIELDS,
    _TDC_DATA_MODEL_FILTER_NAMES,
    _TDC_MAX_PAGES_MAX,
    _TDC_MAX_RECORDS_MAX,
    _TDC_MERGED_MAX_ROWS,
    _TDC_OFFICIAL_PREVIEW_MAX_ROWS,
    _TDC_PAGE_MAX,
    _TDC_PAGE_SIZE_MAX,
    _TDC_SOR_FIELDS,
    _TDC_SOR_FILTER_NAMES,
    _TDC_XLSX_NAME_RE,
    _aras_error_response,
    _aras_xml_payload,
    _aras_xml_requested,
    _async_session_gate,
    _build_aras_client_from_payload,
    _build_tdc_client_from_payload,
    _clean_string_mapping,
    _close_owned_tdc_client,
    _crawl_runner_from_request,
    _csv_cell,
    _department_names,
    _ewo_filters_from_payload,
    _filter_payload,
    _json_error,
    _local_web_mutation_error,
    _loopback_hostname,
    _mapping_result_is_complete,
    _ncr_filters_from_payload,
    _ncr_preview_requested,
    _ncr_section_codes_from_filters,
    _ncr_table_payload,
    _none_if_blank,
    _normalize_allowed_host,
    _origin_tuple,
    _paa_department_from_filters,
    _paa_filters_from_payload,
    _positive_int,
    _request_payload,
    _safe_attachment_basename,
    _safe_rows,
    _safe_scalar,
    _safe_tdc_sor_rows,
    _safe_tdc_sor_value,
    _sanitize_error_message,
    _save_aras_client_diagnostic,
    _save_web_diagnostic_report,
    _shared_domain_session,
    _submit_background_task,
    _tdc_crawl,
    _tdc_data_model_export_bytes,
    _tdc_data_model_filters,
    _tdc_data_model_serial_query,
    _tdc_document_no,
    _tdc_document_nos,
    _tdc_error_response,
    _tdc_export,
    _tdc_export_cache_context,
    _tdc_file_name,
    _tdc_filter_string,
    _tdc_filters_from_payload,
    _tdc_merged_file_name,
    _tdc_official_data_model_preview,
    _tdc_official_export_bytes,
    _tdc_official_preview,
    _tdc_official_rows_csv,
    _tdc_official_sor_preview,
    _tdc_positive_int,
    _tdc_preview_source,
    _tdc_query,
    _tdc_result_data,
    _tdc_sor_export_bytes,
    _tdc_sor_filters,
    _validate_allowed_base_url,
    _validate_tdc_base_url,
    logger,
    register_crawler_routes,
)



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


#: Aras routes 的默认主机 allowlist；仅允许 ecm.sgmw.com.cn。
#: localhost/测试 host 只能通过 create_app(allowed_hosts=...) 或
#: app.config["ARAS_ALLOWED_HOSTS"] 显式注入。

#: TDC routes 的默认主机 allowlist；仅允许 tdc.sgmw.com.cn。
#: 测试 host 只能通过 create_app(tdc_allowed_hosts=...) 或
#: app.config["TDC_ALLOWED_HOSTS"] 显式注入。
_DEFAULT_TDC_ALLOWED_HOSTS: tuple[str, ...] = ("tdc.sgmw.com.cn",)

#: 全量 CSV 导出路由固定使用的边界（page_size 固定 2000，不可被请求覆盖）。


_TDC_XLSX_MIMETYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
#: 合并导出产物是 CSV：同一套安全校验换扩展名（见 `_tdc_merged_file_name`）。
#: 「导出合并结果」同样以官方工作簿为数据源：读取上限与官方预览一致（含表头行）。










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










#: 单值扁平化别名（项目选项等展示场景沿用既有调用点）。










































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














def _narrow_discovery_rows_by_sections(
    db: Any,
    rows: Sequence[Mapping[str, Any]],
    match_rule: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    """按绑定 sections 收窄取证/采样行集（与同步 collect 同一收窄函数）。

    为什么单独成函数：稳定性采样（第 1 页 50 行 / 单号重抓）必须与首次取证
    **同源**——同一条收窄流水线、同一归集索引。采样若拿未收窄的行去比「已收窄
    的全量基线」，其它科室的行永远不在基线集合里 ⇒ sample_not_in_baseline 会把
    绑定永久卡死（2026-10-28 生产现象）。

    返回空列表表示「收窄后无行」：取证侧按 SectionScopeEmpty 报错，采样侧按
    inconclusive 处理（空集是任何集合的子集，直接比对会空真通过）。
    """
    selection = normalize_section_selection(match_rule.get("sections"))
    if not selection:
        return list(rows)
    from services.project_status_connectors import TDCProjectStatusConnector

    try:
        return list(
            TDCProjectStatusConnector._narrow_by_sections(
                rows,
                match_rule,
                build_rollup_index(SectionRollupStore(db).get()),
            )
        )
    except ValueError as exc:
        raise _TDCRequestError(str(exc), "SectionColumnMissing", 422) from None


# 稳定性采样在「所选科室第 1 页无命中」时最多翻到的页数（含第 1 页）。
# 有界的原因：稳定性核验是**同步请求**（用户在向导里等着），每翻一页都是一次上游
# 往返；全量抓取（crawl_*_all）才允许跑后台任务。10 页 × 50 行 = 500 行的采样窗口
# 足以覆盖「所选科室的行不在上游默认排序前 50 行」的常见情形，翻不到则按
# inconclusive 如实报「未判定」，而不是无限翻页拖死请求。
_STABILITY_SAMPLE_MAX_PAGES = 10
_STABILITY_SAMPLE_PAGE_SIZE = 50


def _stability_paged_sample(
    db: Any,
    fetch_page: Callable[[int], Any],
    match_rule: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], Any]:
    """分页类（SOR / 数模无单号）稳定性采样：按 sections 收窄并必要时有界翻页。

    为什么翻页：绑定选了科室后，上游默认排序的第 1 页（50 行）可能一行都不属于
    所选科室，收窄后为空 ⇒ 每次重试都 inconclusive，绑定永远无法就绪（2026-10-28
    生产现象的另一种形态）。仅在「有 sections 且收窄后为空」时才继续取第 2、3…页，
    遇到第一页有命中即停，用该页命中行作样本。

    返回 (样本行, 上游声明总数)。总数永远取第 1 页的**未收窄**上游总数——它与
    首次取证的 upstream_declared_total 同口径，翻页/收窄不改变总数语义。样本行
    为空表示「有界窗口内无命中」，调用方按 inconclusive 处理。
    """
    first = fetch_page(1)
    sample_total = first.total
    sample_rows = _narrow_discovery_rows_by_sections(db, first.rows, match_rule)
    if sample_rows or not normalize_section_selection(match_rule.get("sections")):
        return sample_rows, sample_total
    page = 1
    page_rows = list(first.rows)
    while (
        page < _STABILITY_SAMPLE_MAX_PAGES
        and page_rows
        and isinstance(sample_total, int)
        and not isinstance(sample_total, bool)
        and page * _STABILITY_SAMPLE_PAGE_SIZE < sample_total
    ):
        page += 1
        page_rows = list(fetch_page(page).rows)
        sample_rows = _narrow_discovery_rows_by_sections(db, page_rows, match_rule)
        if sample_rows:
            break
    return sample_rows, sample_total





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
        # 多单号集合键（契约 matchKeys 内）。这里只做「过滤名 -> 契约键」映射；
        # 值同样不进上游查询参数（_tdc_data_model_filters 不读取该键），
        # 运行期多号匹配与保存校验由 Task 8-10 接线。
        "document_nos": "documentNos",
        # 科室多选（契约 matchKeys 内）：同上，值不进上游查询参数（TDC 科室参数
        # 只接受单值），抓取后按行内科室列本地收窄，与同步 collect 同一收窄函数。
        "sections": "sections",
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


#: 发现侧多单号集合的字节预算：与保存侧 ``match_rule`` 的 4000 字符上限取更严的一侧
#: （关注清单预算 12 KB 更宽）。两侧不一致就会出现「能发现不能存」。
_DISCOVERY_SERIAL_SET_MAX_BYTES = min(MAX_WATCHLIST_BYTES, MATCH_RULE_TEXT_LIMIT)
_DISCOVERY_SERIAL_SET_TOO_LONG_MESSAGE = (
    f"多单号集合过长，请分批处理（单次最多 {_DISCOVERY_SERIAL_SET_MAX_BYTES} 字节）"
)


def _mapping_discovery_serial_set(value: Any, error_type: Any) -> list[str]:
    """discovery 过滤名 ``document_nos`` 的值 -> 规范化单号集合（空值 = 未配置）。

    多单号是本地匹配键，绝不进上游查询参数（``_tdc_data_model_filters`` 不读该键）。
    开关关闭时 fail-closed（R22/R4：与保存/运行期同一个 ``multi_serial_enabled``）；
    集合超字节预算时同样在抓取前拒绝（R15/R27：这条规则后面要落进 match_rule_json，
    预算与保存侧 ``_TEXT_LIMITS["match_rule"]`` 对齐，避免「能发现不能存」）。
    """
    if isinstance(value, str):
        if not value.strip():
            return []
    elif isinstance(value, (list, tuple)):
        if not value:
            return []
    else:
        raise error_type("document_nos 必须是字符串或字符串数组")
    if not multi_serial_enabled():
        raise error_type(MULTI_SERIAL_DISABLED_MESSAGE)
    try:
        serials = normalize_serial_set(value)
    except WatchlistError as exc:
        raise error_type(str(exc)) from None
    if len(json.dumps(serials, ensure_ascii=False).encode("utf-8")) > _DISCOVERY_SERIAL_SET_MAX_BYTES:
        raise error_type(_DISCOVERY_SERIAL_SET_TOO_LONG_MESSAGE)
    return serials


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
        if name == "document_nos":
            # 多单号集合：规范化后进匹配规则，值不进上游查询参数（与 document_no 同处理）。
            serials = _mapping_discovery_serial_set(value, error_type)
            if serials:
                rule[rule_name] = serials
            continue
        if name == "sections":
            # 科室多选：规范化后进匹配规则，同样绝不进上游查询参数（TDC 科室参数
            # 只接受单值）。抓取后按行内科室列本地收窄，与同步 collect 同口径。
            try:
                sections = normalize_section_selection(value)
            except ValueError as exc:
                raise error_type(str(exc)) from None
            if sections:
                rule[rule_name] = list(sections)
            continue
        if not isinstance(value, str):
            raise error_type(f"{name} filter must be a string")
        clean = value.strip() or None
        values[name] = clean
        if clean is not None:
            rule[rule_name] = clean
    if rule.get("documentNos") and selected_external_key:
        # R27.3：与保存侧（_multi_serial_rule_error）对齐——多单号集合没有单记录
        # 稳定键。带 selectedExternalKey 的请求在抓取前就拒绝，不先白跑一次全量
        # 抓取再 422，也不把 selected 混进聚合观测。
        raise error_type(MULTI_SERIAL_EXTERNAL_KEY_MESSAGE)
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
        # 多单号集合（documentNos）：与单值流水单号/实例号三选一，且必须是聚合绑定
        # （集合没有单记录稳定键；保存校验同源，见 _multi_serial_rule_error）。
        if rule.get("documentNos"):
            if str(rule.get("documentNo") or "").strip() or str(
                rule.get("incident") or ""
            ).strip():
                raise error_type("多单号与单个流水单号/实例号三选一：请只保留一种匹配方式")
            rule["aggregate"] = True
        # 流水单号与实例号二选一（与 updates 落库校验同语义，2026-10-09）：同填时
        # 运行期会按两键取交集，指向不同行则永久 not_found 且无从提示。
        if str(rule.get("documentNo") or "").strip() and str(rule.get("incident") or "").strip():
            raise error_type("流水单号与实例号二选一：请只填写其中一项")
        if rule.get("documentNo"):
            # 单值 fail-closed（2026-10-10）：向导这条路径是单值精确匹配，多值整串
            # 必然 0 行；在抓取前拒绝，避免白跑一次全量抓取。
            try:
                rule["documentNo"] = normalize_single_serial(rule["documentNo"])
            except WatchlistError as exc:
                raise error_type(str(exc)) from None
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


def _serial_identity_diagnostic(
    rows: Sequence[Mapping[str, Any]],
    report_type: str | None,
    serial_match: Mapping[str, Any] | None,
    *,
    used_fields: Sequence[str] = (),
    distinct_identities: int = 0,
) -> dict[str, Any]:
    """流水单号本地匹配的身份事实（只给字段名与计数，不含业务值）。

    2026-10-10 数模生产事故：命中行与选中键来自不同身份字段时，旧实现只回
    「未匹配（命中 0 行）」，用户无法区分「上游没数据」「单号不在范围内」
    「身份字段对不上」。这里把判别所需的最小事实一并返回。
    """
    present = sorted(
        {
            str(name)
            for row in rows
            for name in identity_fields(report_type)
            if row.get(name) not in (None, "")
        }
    )
    return {
        "scanned": serial_match.get("scanned") if serial_match else None,
        "matched": serial_match.get("matched") if serial_match else None,
        "matchedRows": serial_match.get("matched") if serial_match else None,
        "identityFieldsPresent": present,
        "identityFieldUsed": sorted({str(name) for name in used_fields}),
        "authoritativeField": authoritative_identity_field(report_type),
        "distinctIdentities": distinct_identities,
    }




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


















#: CSV 公式注入缓解：危险前导字符（Excel 会当公式执行）。
#: 严格数字字面量豁免：`-12.5` 这类文本必须保持数值语义，不能加 `'` 前缀。






















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
        else:
            display_summary_value = None
        # 进度派生单源（core.project_status_contracts.derive_effective_progress）：
        # 快照态按明细 completed/total 换算，其余状态保留手工值。响应里的
        # progress 仍是手工字段（编辑表单预填它并原样保存），派生值只走新键
        # effectiveProgress/progressSource，避免派生数字被"保存"回写成手工值。
        effective_progress_value, progress_source = derive_effective_progress(
            display_state, display_summary_value, row["progress"]
        )
        # displayProgress 语义保持不变：只在 manual/snapshot 两态给数值。
        display_progress_value: int | None = (
            effective_progress_value
            if display_state in ("manual", "snapshot")
            else None
        )
        # 「实际完成或当前进度」列同样取派生值：否则概览表仍显示手工 0%，
        # 与工作台列表/详情页出现两套数字。
        progress_text_value = (
            effective_progress_value
            if effective_progress_value is not None
            else row["progress"]
        )
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
                "progressOrDate": (
                    actual_date
                    if row["status"] == "已完成"
                    else (f"{progress_text_value}%" if progress_text_value is not None else "—")
                ),
                "progress": row["progress"],
                # 派生进度：快照态按明细 completed/total 换算，其余状态等于手工值。
                # 只读展示键；progress 保持手工语义（编辑表单预填它）。
                "effectiveProgress": effective_progress_value,
                "progressSource": progress_source,
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
                "retired": project_status_retired(str(row["id"])),
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
                    # 数模科室多选预设（契约标志 sectionPresets）：与归集目标同源，
                    # 默认即现行五科室。它不是声明式范围，而是同步筛选的默认勾选。
                    "sectionPresets": (
                        list(section_scope_presets)
                        if capabilities.get("sectionPresets") is True
                        else None
                    ),
                    "syncNote": capabilities.get("syncNote"),
                    # 字段契约版本：前端据此发现「代码已改但界面还是旧的」
                    # （onedir 包未重建 / ES module 缓存 / 后端未重启）。
                    "matchFieldContract": MATCH_FIELD_CONTRACT,
                    # 多单号同步功能开关（缺省关闭）随能力下发：前端据此决定是否
                    # 引导用户使用多单号（开关关闭时后端保存/发现/运行期一律
                    # fail-closed）。只有契约声明 documentNos 的交付物可能为 True。
                    "multiSerialSyncEnabled": bool(
                        multi_serial_enabled()
                        and "documentNos" in (capabilities.get("matchKeys") or ())
                    ),
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




















#: 后台任务结果 JSON 工件的大小上限（与同步响应体量级一致的安全上限）。
_TASK_RESULT_MAX_BYTES = 64 * 1024 * 1024












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

    @app.after_request
    def _plugin_static_revalidate(response):  # type: ignore[no-untyped-def]
        """插件静态资源走协商缓存（ETag/304），避免「代码改了界面没变」。

        插件前端是原生 ES module：子模块 import 不带版本号，浏览器一旦留下旧副本
        且没有 revalidate 提示，页面就会一直显示旧控件。这里约束插件静态目录和宿主外壳（/static/host/，同为 ES module），
        API 响应仍由各路由的 ``no-store`` 负责。
        """
        if request.path.startswith(("/plugins/", "/static/host/")) and response.status_code in (200, 304):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response

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

    # 版本与设置路由已迁入 web/host_boot.py（W13-02，路径/endpoint/信封不变）；
    # 注册放在设置服务就绪之后（见下方 register_host_service_routes 调用）。

    @app.route("/api/overview")
    def api_overview():
        try:
            data = _query_overview(db)
            return jsonify(data)
        except Exception as e:
            logger.exception("api/overview 查询失败")
            return jsonify({"error": str(e)}), 500

    # Excel 领域路由已迁入 web/excel_boot.py（W13-04，路径/endpoint/信封不变）。
    from web.excel_boot import ExcelRouteDeps, register_excel_routes

    register_excel_routes(
        app,
        ExcelRouteDeps(
            excel_admin_service=excel_admin_service,
            excel_worker_controller=excel_worker_controller,
            local_mutation_error=_local_web_mutation_error,
            json_error=_json_error,
            validation_error=_project_status_validation_error,
            safe_attachment_basename=_safe_attachment_basename,
        ),
    )

    # ── 统一任务中心门面与工件下载 (Unified Task Center API Facade) ──────────
    # 实现已迁入 web/tasks_boot.py（W13-03）；_CRAWL_TASK_TYPE_LABELS 随迁。

    # 任务中心统一路由已迁入 web/tasks_boot.py（W13-03，路径/endpoint/信封不变）。
    from web.tasks_boot import TasksRouteDeps, register_tasks_routes

    register_tasks_routes(
        app,
        TasksRouteDeps(
            db=db,
            crawl_task_runner=crawl_task_runner,
            excel_admin_service=excel_admin_service,
            excel_repository=excel_repository,
            local_mutation_error=_local_web_mutation_error,
            json_error=_json_error,
            safe_attachment_basename=_safe_attachment_basename,
        ),
    )

    # 设置路由已迁入 web/host_boot.py（W13-02）：settings 读改、本机选目录、
    # 统一域账号登录、会话清除。此处只做依赖注入。
    from web.host_boot import HostRouteDeps, register_host_service_routes

    host_deps = HostRouteDeps(
        settings_store=settings_store,
        domain_sessions=domain_sessions,
        credential_vault=credential_vault,
        excel_admin_service=excel_admin_service,
        tdc_export_cache=tdc_export_cache,
        local_mutation_error=_local_web_mutation_error,
        json_ok=_json_ok,
        json_error=_json_error,
        sanitize_error_message=_sanitize_error_message,
        validation_error=_project_status_validation_error,
    )
    register_host_service_routes(app, host_deps)

    # Aras 路由已迁入 web/crawler_boot.py（W13-06，路径/endpoint/信封不变）；
    # TDC 路由 W13-07 复用同一门面模块。
    from web.crawler_boot import (
        CrawlerRouteDeps,
        register_crawler_routes,
        register_form_catalog_routes,
        register_tdc_routes,
    )

    crawler_deps = CrawlerRouteDeps(
        db=db,
        crawl_task_runner=crawl_task_runner,
        domain_sessions=domain_sessions,
        tdc_export_cache=tdc_export_cache,
        excel_admin_service=excel_admin_service,
        sanitize_error_message=_sanitize_error_message,
        local_mutation_error=_local_web_mutation_error,
        json_ok=_json_ok,
        json_error=_json_error,
        deliverable_form_service=deliverable_form_service,
        section_rollup_store=section_rollup_store,
    )
    register_crawler_routes(app, crawler_deps)

    # TDC 报表路由（W13-07）与交付物表单/目录路由（W13-08）复用同一门面接线；
    # 路径/endpoint/信封不变。
    register_tdc_routes(app, crawler_deps)
    register_form_catalog_routes(app, crawler_deps)

    # 原件留存路由已迁入 web/archive_boot.py（W13-05，路径/endpoint/信封不变）。
    from web.archive_boot import ArchiveRouteDeps, register_archive_routes

    register_archive_routes(
        app,
        ArchiveRouteDeps(
            db=db,
            archive_admin_service=archive_admin_service,
            excel_admin_service=excel_admin_service,
            sanitize_error_message=_sanitize_error_message,
            local_mutation_error=_local_web_mutation_error,
            json_ok=_json_ok,
            json_error=_json_error,
            validation_error=_project_status_validation_error,
        ),
    )

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
            # 多单号集合（documentNos）同理：只做本地精确匹配，且没有单记录稳定键。
            _raw_document_nos = match_rule.get("documentNos")
            document_nos = (
                [str(item) for item in _raw_document_nos]
                if isinstance(_raw_document_nos, (list, tuple))
                else None
            ) or None
            cache_key = None
            if wizard_session_id and not is_stability_check:
                base_query_params = {
                    k: v for k, v in values.items()
                    if k not in {"serial_number", "incident", "processNo", "ewo_no",
                                 "paa_no", "ncr_no", "document_no", "document_nos"}
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
                        if document_nos and not _mapping_result_is_complete(crawl_result):
                            # 同一条 fail-closed：抓不全就分不清「单号不存在」与「没抓到」。
                            raise _TDCRequestError(
                                "抓取不完整，无法判定流水单号集合，请重试",
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
                        elif upstream_declared_total is None:
                            # 未声明总数时用「收窄前的全量行数」当基线总数：采样侧拿到的是
                            # 上游 page total（同样未收窄），两者必须同口径。若在这里记收窄
                            # 后的行数，带科室多选的绑定会在 total_mismatch 上永久失败。
                            upstream_declared_total = len(rows)
                        if cache_key:
                            _set_discovery_session_cache(cache_key, rows, upstream_declared_total)
                    # 科室多选（sections）：与同步 collect 共用同一收窄函数（行内科室列
                    # 归集后求交）。会话缓存里存的是**未收窄**的全量行，所以收窄放在
                    # 缓存之后——换科室不必重新抓取。
                    section_selection = normalize_section_selection(
                        match_rule.get("sections")
                    )
                    if section_selection:
                        narrowed = _narrow_discovery_rows_by_sections(db, rows, match_rule)
                        if rows and not narrowed:
                            raise _TDCRequestError(
                                f"所选科室（{len(section_selection)} 个）在当前查询条件下"
                                "没有命中任何行；请核对科室名（历史科室名需先在看板"
                                "「科室归集规则」登记）或放宽其它筛选条件",
                                "SectionScopeEmpty",
                                422,
                            )
                        rows = narrowed
                    serial_match: dict[str, Any] | None = None
                    serial_diagnostic: dict[str, Any] | None = None
                    serial_partial = False
                    effective_selected = selected
                    if document_nos:
                        # 多单号集合：与单值同一条本地精确匹配（上游没有该查询参数），
                        # 但集合没有单记录稳定键 ⇒ 聚合观测 + 无选中键。
                        matched, bookkeeping = match_serials(rows, document_nos)
                        serial_match = {
                            "requested": list(document_nos),
                            "found": bookkeeping["found"],
                            "missing": bookkeeping["missing"],
                            "scanned": bookkeeping["scanned"],
                            "matched": bookkeeping["matched"],
                            "complete": True,
                        }
                        if upstream_declared_total is None:
                            # 本地匹配不改变上游范围（与单值分支同一口径）：
                            # 基线总数仍是全量抓取的行数。
                            upstream_declared_total = len(rows)
                        serial_partial = bool(serial_match["missing"])
                        # 部分/全部缺失：绝不按已命中子集建绑定——否则证据会为一个
                        # 「少算」的范围背书。这里只落一条 not_found 观测，命中情况
                        # 全部由 serialMatch 归因（missing 逐项可见）。
                        rows = [] if serial_partial else matched
                        effective_selected = None
                    elif document_no:
                        # 本地精确匹配是流水单号的唯一判定依据（上游没有该查询参数）。
                        # 选中键必须与 observe() 的候选过滤键同源——同一个身份函数、
                        # 同一行——否则命中行会被 selected 过滤掉而误报「未匹配」
                        # （2026-10-10 生产事故：行内含 formId 时身份 ≠ 实例号）。
                        matched, serial_match = match_serial(rows, document_no)
                        report_type = str(
                            PROJECT_STATUS_SOURCE_CAPABILITIES.get(deliverable_id, {}).get(
                                "reportType"
                            )
                            or ""
                        ) or None
                        used_fields: list[str] = []
                        identity_values: list[str] = []
                        for row in matched:
                            # 单记录绑定只认契约里的权威字段（数模 = 第 0 列实例号 incident）：
                            # 权威字段空白/缺失时**不得**回退到 formId 等候选键（Codex 复核 P0）。
                            value = authoritative_record_identity(row, report_type=report_type)
                            if not value:
                                continue
                            identity_values.append(value)
                            used_fields.append(
                                identity_field_name(row, report_type=report_type) or ""
                            )
                        distinct_identities = sorted(set(identity_values))
                        authoritative_field = authoritative_identity_field(report_type)
                        # 权威字段缺失（含空白值）：命中行数 > 可用权威身份数即 fail-closed。
                        missing_authoritative = bool(authoritative_field) and (
                            len(identity_values) != len(matched)
                        )
                        serial_diagnostic = _serial_identity_diagnostic(
                            rows,
                            report_type,
                            serial_match,
                            used_fields=used_fields,
                            distinct_identities=len(distinct_identities),
                        )
                        if matched and not identity_values:
                            # fail-closed：命中行没有可用的**权威**身份字段，externalKey 无法成立。
                            raise _TDCRequestError(
                                "流水单号命中了行，但命中行没有可用的权威业务单号字段"
                                "（实例号 incident）；上游结构可能已变化，请重新进行映射发现",
                                "IdentityMissing",
                                422,
                                None,
                                serial_diagnostic,
                            )
                        if matched and missing_authoritative:
                            raise _TDCRequestError(
                                f"流水单号命中了行，但部分命中行缺少权威业务单号字段"
                                f"（{authoritative_field}），无法建立单记录绑定；"
                                "上游结构可能已变化，请重新进行映射发现",
                                "IdentityMissing",
                                422,
                                None,
                                serial_diagnostic,
                            )
                        if len(distinct_identities) > 1:
                            raise _TDCRequestError(
                                "该流水单号命中了多行且身份不唯一，请核对后重试",
                                "IdentityAmbiguous",
                                400,
                                None,
                                serial_diagnostic,
                            )
                        if len(matched) > 1:
                            # 同一实例多行（part_detail 粒度）仍不能构成单记录绑定。
                            raise _TDCRequestError("该流水单号命中多行，请核对后重试")
                        if upstream_declared_total is None:
                            # 本地匹配不改变上游范围：基线总数仍是全量抓取的行数，
                            # 否则 F10 采样（同样全量抓取）会与基线总数误判失配。
                            upstream_declared_total = len(rows)
                        rows = matched
                        effective_selected = (
                            distinct_identities[0] if distinct_identities else None
                        )
                    observe_kwargs: dict[str, Any] = {}
                    if document_nos:
                        # 多单号证据基线 = 配置单号成员身份（行身份口径在上游行集
                        # 变化时永不稳定，见 MappingDiscoveryService.observe）。
                        observe_kwargs["fingerprint_identities"] = serial_match["found"]
                        if serial_partial:
                            # 归因交给 observe 落库（``_reason``）：历史/DB 读者看到的
                            # 不能只是一条裸的 not_found（与响应里的 reason 同源）。
                            observe_kwargs["state_reason"] = "serial_set_partial"
                    observation = discovery_service.observe(
                        deliverable_id, "tdc", rows, effective_selected,
                        aggregate=bool(match_rule["aggregate"]), match_rule=match_rule,
                        upstream_total=upstream_declared_total,
                        **observe_kwargs,
                    )
                    if serial_match is not None:
                        # 0 行时仍走既有「未匹配」路径（state=not_found），但附带覆盖范围
                        # 与身份事实，用户能看到抓了多少行、身份字段是哪个，而不是只看到
                        # "未匹配"（2026-10-10：命中行身份 ≠ 选中键时曾静默变成未匹配）。
                        observation = {**observation, "serialMatch": serial_match}
                        if serial_diagnostic is not None:
                            observation = {
                                **observation,
                                "serialDiagnostic": serial_diagnostic,
                            }
                        if (
                            not matched
                            and observation.get("state") == "not_found"
                            and not observation.get("reason")
                        ):
                            observation = {**observation, "reason": "serial_no_match"}
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
                    # F10: 独立轻量签名采样核验（默认只拉第 1 页 50 条，秒级完成，保持同步；
                    # 选了科室且第 1 页无命中时才有界翻页，见 _stability_paged_sample）
                    client = _build_tdc_client_from_payload(
                        payload, app.config["TDC_ALLOWED_HOSTS"]
                    )
                    stability_kwargs: dict[str, Any] = {}
                    if deliverable_id == "VPI-T2-D2":
                        sor_filters = _tdc_sor_filters(values)
                        # 与首次取证同源：按 sections 收窄（必要时有界翻页），否则
                        # 其它科室的行永远不在（已收窄的）基线里 ⇒ 永久 sample_not_in_baseline。
                        sample_rows, sample_total = _stability_paged_sample(
                            db,
                            lambda page: client.query_sor_page(
                                sor_filters,
                                page=page,
                                page_size=_STABILITY_SAMPLE_PAGE_SIZE,
                            ),
                            match_rule,
                        )
                        if not sample_rows:
                            stability_kwargs["sample_empty_reason"] = (
                                "stability_sample_inconclusive"
                            )
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
                        # 与首次取证同源：先按 sections 收窄，再做单号精确匹配
                        # （取证侧同一顺序：收窄 → match_serial）。
                        narrowed_rows = _narrow_discovery_rows_by_sections(
                            db, crawl_result.rows, match_rule
                        )
                        sample_rows, _ = match_serial(narrowed_rows, document_no)
                        if len(sample_rows) > 1:
                            raise _TDCRequestError("该流水单号命中多行，请核对后重试")
                        if not sample_rows:
                            # 收窄/未命中导致样本为空：不能判稳定（空集空真通过）。
                            stability_kwargs["sample_empty_reason"] = (
                                "stability_sample_inconclusive"
                            )
                        full_total = getattr(crawl_result, "total", None)
                        sample_total = (
                            full_total
                            if isinstance(full_total, int) and not isinstance(full_total, bool)
                            else len(crawl_result.rows)
                        )
                    elif document_nos:
                        # R28：多单号稳定性必须与首次观测同源（全量抓取 + 本地匹配），
                        # 且按「配置单号成员身份」比对——拿全量第 1 页去比「已命中并集」
                        # 必然报 sample_not_in_baseline，卡在两条 matched 之间永远无法就绪。
                        if not match_rule["aggregate"]:
                            # 成员身份比对只对聚合绑定成立；非聚合多单号是非法组合
                            # （保存侧同一条不变量），这里明确拒绝而不是静默误报。
                            raise _TDCRequestError(
                                "多单号稳定性校验只支持聚合绑定（aggregate=true）",
                                "UnsupportedStabilityCheck",
                                400,
                            )
                        crawl_result = client.crawl_data_model_all(
                            _tdc_data_model_filters(values),
                            max_records=MAX_AGGREGATE_RECORDS,
                        )
                        if not _mapping_result_is_complete(crawl_result):
                            raise _TDCRequestError(
                                "抓取不完整，无法判定流水单号集合，请重试",
                                "IncompleteDiscovery",
                                422,
                                None,
                                _pagination_diagnostic(crawl_result, len(crawl_result.rows)),
                            )
                        narrowed_rows = _narrow_discovery_rows_by_sections(
                            db, crawl_result.rows, match_rule
                        )
                        matched_rows, bookkeeping = match_serials(
                            narrowed_rows, document_nos
                        )
                        if not matched_rows:
                            # 同单值分支：收窄后没有命中集合时按不确定处理。
                            stability_kwargs["sample_empty_reason"] = (
                                "stability_sample_inconclusive"
                            )
                        # 样本侧是「本次全量抓取里命中的单号集合」（全集，不是采样），
                        # 与基线按集合相等比对；声明总数与单值分支同一口径，但成员模式
                        # 不参与比对（上游零件行会让总体总数增长）。
                        sample_rows = matched_rows
                        full_total = getattr(crawl_result, "total", None)
                        sample_total = (
                            full_total
                            if isinstance(full_total, int) and not isinstance(full_total, bool)
                            else len(crawl_result.rows)
                        )
                        stability_kwargs["member_identities"] = bookkeeping["found"]
                    else:
                        dm_filters = _tdc_data_model_filters(values)
                        # 与首次取证同源：采样同样按 sections 收窄（必要时有界翻页），
                        # 否则其它科室的行永远不在（已收窄的）基线集合里 ⇒ 永久
                        # sample_not_in_baseline。
                        sample_rows, sample_total = _stability_paged_sample(
                            db,
                            lambda page: client.query_data_model_page(
                                dm_filters,
                                page=page,
                                page_size=_STABILITY_SAMPLE_PAGE_SIZE,
                            ),
                            match_rule,
                        )
                        if not sample_rows:
                            stability_kwargs["sample_empty_reason"] = (
                                "stability_sample_inconclusive"
                            )
                    if sample_total is None or sample_total < 0:
                        raise _TDCRequestError("TDC 返回的总记录数无效")
                    result = discovery_service.observe_stability_sample(
                        deliverable_id, "tdc", sample_rows, sample_total,
                        aggregate=bool(match_rule["aggregate"]), match_rule=match_rule,
                        **stability_kwargs,
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
            payload = request.get_json(silent=True) or {}
            raw_car_type = payload.get("carType") or payload.get("car_type") or payload.get("model")
            if raw_car_type is not None and isinstance(raw_car_type, str):
                if any(ord(c) < 32 or ord(c) == 127 for c in raw_car_type):
                    raise ValueError("carType contains control characters")
                car_type = raw_car_type.strip()
                if car_type:
                    if len(car_type) > 80:
                        raise ValueError("carType is too long")
                    runner = ProjectStatusSyncRunner(
                        db,
                        update_service,
                        create_production_registry(),
                        analysis_service=deliverable_analysis_service,
                    )
                    data = runner.sync_by_car_type(deliverable_id, car_type)
                    response = jsonify({"ok": True, "data": data})
                    response.headers["Cache-Control"] = "no-store"
                    return response

            update_service.assert_sync_ready(deliverable_id)
            runner = ProjectStatusSyncRunner(
                db,
                update_service,
                create_production_registry(),
                analysis_service=deliverable_analysis_service,
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
            # 必须先于 `except ValueError`：SyncBindingNotReadyError 是 ValueError 子类，
            # 顺序反了会把 409 SyncNotReady 降级成 422 ValidationError。
            return _json_error(409, "SyncNotReady", _sanitize_error_message(exc))
        except ValueError as exc:
            return _json_error(422, "ValidationError", _sanitize_error_message(exc))
        except Exception as exc:
            logger.exception("project status sync-now failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.post("/api/project-status/deliverables/<deliverable_id>/sync-by-car-type")
    def api_project_status_sync_by_car_type(deliverable_id: str):
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        _, _, sync_now_deliverable_rows = db.get_project_status("VPI-T2")
        if deliverable_id not in {str(row["id"]) for row in sync_now_deliverable_rows}:
            return _json_error(404, "NotFound", "未找到交付物")
        sync_block = PROJECT_STATUS_SOURCE_CAPABILITIES.get(deliverable_id, {})
        if not sync_block.get("syncCapable"):
            block_type = str(sync_block.get("syncBlockType") or "ManualOnly")
            block_reason = (
                AFACE_CONTRACT_BLOCKER
                if block_type == "ContractBlocked"
                else str(sync_block.get("blockReason") or "该交付物仅允许手工维护")
            )
            return _json_error(409, block_type, block_reason)
        payload = request.get_json(silent=True) or {}
        raw_car_type = payload.get("carType") or payload.get("car_type") or payload.get("model")
        if not raw_car_type or not isinstance(raw_car_type, str):
            return _json_error(422, "ValidationError", "缺少车型参数 carType")
        if any(ord(c) < 32 or ord(c) == 127 for c in raw_car_type):
            return _json_error(422, "ValidationError", "车型参数包含非法控制字符")
        car_type = raw_car_type.strip()
        if not car_type:
            return _json_error(422, "ValidationError", "车型参数不能为空")
        if len(car_type) > 80:
            return _json_error(422, "ValidationError", "车型参数不能超过 80 个字符")
        try:
            runner = ProjectStatusSyncRunner(
                db,
                update_service,
                create_production_registry(),
                analysis_service=deliverable_analysis_service,
            )
            data = runner.sync_by_car_type(deliverable_id, car_type)
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "未找到交付物")
        except SyncBindingNotReadyError as exc:
            # 同 sync-now：子类必须先捕获，否则 409 被 422 吞掉。
            return _json_error(409, "SyncNotReady", _sanitize_error_message(exc))
        except ValueError as exc:
            return _json_error(422, "ValidationError", _sanitize_error_message(exc))
        except Exception as exc:
            logger.exception("project status sync by car type failed")
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














    from web.diagnostics import install_diagnostics
    install_diagnostics(app, local_guard=_local_web_mutation_error)
    _install_plugin_host(app, db, plugin_dirs=plugin_dirs, plugin_only=plugin_only, host_deps=host_deps)
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
    host_deps: Any = None,
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

    # 宿主更新路由已迁入 web/host_boot.py（W13-02，路径/endpoint/信封不变）；
    # updates/registry/_updates_payload 仍由本函数装配。
    from web.host_boot import register_host_update_routes

    if host_deps is not None:
        register_host_update_routes(
            app,
            updates=updates,
            registry=registry,
            updates_payload=_updates_payload,
            deps=host_deps,
        )


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
