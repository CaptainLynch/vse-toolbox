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
import ipaddress
import logging
import os
import re
import shutil
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, cast
from urllib.parse import urlsplit

from flask import Flask, current_app, has_app_context, jsonify, render_template, request, send_file

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
    MILESTONE_STATUSES,
    current_stage_label,
    milestone_display_status,
)
from core.report_contracts import matrix_payload, report_contracts, table_payload
from core.runtime_paths import app_root
from core.settings_store import SettingsStore, SettingsValidationError, validate_local_directory
from core.db_manager import (
    ArchiveJobNotReadyError,
    ArchiveLeaseBusyError,
    DatabaseManager,
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
from services.project_status_discovery import MappingDiscoveryService
from services.project_status_analytics import ProjectStatusAnalyticsService
from services.project_status_deliverable_analysis import (
    ProjectStatusDeliverableAnalysisService,
)
from services.deliverable_form_analysis import DeliverableFormAnalysisService
from services.project_status_sync_runner import (
    ProjectStatusSyncRunner,
    create_production_registry,
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
    EWOReportFilters,
    NCRApprovalFilters,
    PAAReportFilters,
)
from services.aras_auth import ArasAuthError, ArasECMAuthClient
from services.aras_department_mapping import normalize_departments, resolve_ncr_section_codes
from services.aras_export import export_report_contract_csv
from services.tdc_auth import TDCAuthError, TDCPasswordAuthClient
from services.tdc_crawler import (
    AFACE_CONTRACT_BLOCKER,
    TDCCrawlerClient,
    TDCCrawlerError,
    TDCDataModelFilters,
    TDCExportResult,
    TDCSORFilters,
)
from services.tdc_export_cache import TDCExportCache
from services.windows_http import WinHTTPError, WinHTTPTimeoutError

logger = logging.getLogger("vse_toolbox.web")

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
    {"id": "office", "name": "办公工具箱"},
    {"id": "sync", "name": "同步与登记"},
]

_TDC_DATA_MODEL_FIELDS = [
    {"name": "serial_number", "label": "流水号", "type": "text"},
    {"name": "applicant", "label": "申请人", "type": "text"},
    {"name": "department", "label": "部门", "type": "text"},
    {"name": "section", "label": "科室", "type": "text"},
    {"name": "application_start", "label": "申请开始", "type": "date"},
    {"name": "application_end", "label": "申请结束", "type": "date"},
    {"name": "project_model", "label": "项目车型", "type": "text"},
    {"name": "part_number", "label": "零件号", "type": "text"},
    {"name": "model_number", "label": "模型编号", "type": "text"},
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
        "name": "PAA 报告",
        "category": "aras",
        "source": "services/aras_crawler.py",
        "availability": "available",
        "implementation_status": "已完整实现",
        "description": "在 Aras 工作区执行 PAA 报告分页查询、全量抓取与 CSV 导出。",
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
    {
        "id": "tdc-a-face",
        "name": "TDC 造型 A 面冻结发布单",
        "category": "tdc",
        "source": "services/tdc_crawler.py",
        "availability": "disabled",
        "implementation_status": "仅占位",
        "description": "A-face 页面路径与结果工作簿结构已确认，但 HAR 网络契约缺失。",
        "reason": AFACE_CONTRACT_BLOCKER,
        "output_formats": [],
        "operations": [],
        "fields": [],
    },
    {
        "id": "dm-change-form",
        "name": "数模更改单 / DMU 审核单（独立表单）",
        "category": "office",
        "source": "services/vertical_forms.py",
        "availability": "disabled",
        "implementation_status": "仅占位",
        "description": "独立 DMU 表单，区别于可执行的 TDC 数模设计审核流程报表。",
        "reason": "独立 DMU 表单仅为 NotImplementedError 占位，待真实模板接入后实现。",
        "output_formats": [],
        "operations": [],
        "fields": [],
    },
    {
        "id": "deliverables-register",
        "name": "交付物状态登记",
        "category": "sync",
        "source": "main.py + core/db_manager.py",
        "availability": "cli_only",
        "implementation_status": "部分实现",
        "description": "CLI 可更新 SQLite 交付物状态，Web 提供概览但不提供编辑/导出。",
        "reason": "CLI 更新、DB 存储与 Web 概览已存在；Web 编辑/导出未实现。",
        "output_formats": [],
        "operations": ["cli"],
        "fields": [],
    },
    {
        "id": "excel-toolbox",
        "name": "Excel 工具箱",
        "category": "office",
        "source": "services/excel_toolbox.py",
        "availability": "cli_only",
        "implementation_status": "后端已实现、前端缺失",
        "description": "xlwings 驱动的 Excel 合并、叠加与差异工具，仅 CLI 可用。",
        "reason": "后端已实现、前端缺失：Web 无执行入口。",
        "output_formats": ["XLSX"],
        "operations": ["cli"],
        "fields": [],
    },
    {
        "id": "weekly-ppt",
        "name": "周报 PPT",
        "category": "office",
        "source": "services/office_toolbox.py",
        "availability": "disabled",
        "implementation_status": "部分实现",
        "description": "周报 PPT 服务层依赖本地 PowerPoint COM 与模板；CLI 入口已暂缓。",
        "reason": "CLI 已主动短路（P3 暂缓），且所需 PPT 模板缺失；当前无可执行流程。",
        "output_formats": ["PPTX"],
        "operations": [],
        "fields": [],
    },
    {
        "id": "feishu-tasks",
        "name": "飞书任务同步",
        "category": "sync",
        "source": "services/feishu_imap.py",
        "availability": "disabled",
        "implementation_status": "部分实现",
        "description": "飞书 IMAP 解析与入库能力存在；CLI 同步入口已暂停，Web 无执行入口。",
        "reason": "服务层已实现解析/存储，CLI 处理入口已暂停（P4 暂缓）。",
        "output_formats": [],
        "operations": [],
        "fields": [],
    },
    {
        "id": "office-deliverables-excel",
        "name": "交付物清单 Excel 导出",
        "category": "office",
        "source": "services/office_toolbox.py",
        "availability": "disabled",
        "implementation_status": "后端已实现、前端缺失",
        "description": "OfficeToolbox.export_deliverables_excel 服务层可导出交付物清单 XLSX；无 CLI/Web 执行入口。",
        "reason": "仅服务层实现（win32com COM 导出），无 CLI 菜单或 Web 执行入口，且依赖本地 Office 环境。",
        "output_formats": ["XLSX"],
        "operations": [],
        "fields": [],
    },
    {
        "id": "vertical-ewo-form",
        "name": "工程变更单表单",
        "category": "office",
        "source": "services/vertical_forms.py",
        "availability": "disabled",
        "implementation_status": "仅占位",
        "description": "EWOForm 垂类表单占位。",
        "reason": "EWOForm 仅为 NotImplementedError 占位，待真实模板接入后实现。",
        "output_formats": [],
        "operations": [],
        "fields": [],
    },
    {
        "id": "vertical-ncr-form",
        "name": "不合格报告表单",
        "category": "office",
        "source": "services/vertical_forms.py",
        "availability": "disabled",
        "implementation_status": "仅占位",
        "description": "NCRForm 垂类表单占位。",
        "reason": "NCRForm 仅为 NotImplementedError 占位，待真实模板接入后实现。",
        "output_formats": [],
        "operations": [],
        "fields": [],
    },
    {
        "id": "vertical-styling-review-form",
        "name": "造型数据审核单表单",
        "category": "office",
        "source": "services/vertical_forms.py",
        "availability": "disabled",
        "implementation_status": "仅占位",
        "description": "StylingReviewForm 垂类表单占位。",
        "reason": "StylingReviewForm 仅为 NotImplementedError 占位，待真实模板接入后实现。",
        "output_formats": [],
        "operations": [],
        "fields": [],
    },
    {
        "id": "intranet-ncr-scraper",
        "name": "内网 NCR Excel 抓取（旧版）",
        "category": "sync",
        "source": "services/intranet_scraper.py",
        "availability": "disabled",
        "implementation_status": "部分实现",
        "description": "旧版 Selenium 内网 NCR XLSX 下载与导入流程；依赖人工浏览器登录。",
        "reason": "部分实现：依赖 Selenium/Chrome WebDriver、pandas 与人工内网登录等外部依赖，当前 CLI/Web 均无执行入口。",
        "output_formats": ["XLSX"],
        "operations": [],
        "fields": [],
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
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.status_code = status_code
        self.diagnostic_path = diagnostic_path


class _TDCRequestError(ValueError):
    """TDC 请求级校验失败（主机 allowlist / 凭据 / 参数边界），映射为 HTTP 错误。"""

    def __init__(
        self,
        message: str,
        error_type: str = "ValidationError",
        status_code: int = 400,
        diagnostic_path: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.status_code = status_code
        self.diagnostic_path = diagnostic_path


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
):
    error: dict[str, Any] = {"type": error_type, "message": message}
    if code is not None:
        error["code"] = code
    if diagnostic_path is not None:
        error["diagnosticPath"] = str(diagnostic_path)
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


def _safe_tdc_sor_value(
    value: Any,
    *,
    preferred_keys: tuple[str, ...] = (),
) -> str | None:
    """Flatten known TDC SOR objects without serializing raw JSON into cells."""
    if value is None:
        return None
    if isinstance(value, Mapping):
        fallback_keys = (
            "projectNo",
            "projectName",
            "name",
            "userName",
            "keyed_name",
            "label",
            "code",
            "value",
        )
        for key in (*preferred_keys, *fallback_keys):
            if key not in value:
                continue
            candidate = _safe_tdc_sor_value(value[key], preferred_keys=preferred_keys)
            if candidate:
                return candidate
        return None
    if isinstance(value, (list, tuple)):
        parts = [
            part
            for item in value
            if (part := _safe_tdc_sor_value(item, preferred_keys=preferred_keys))
        ]
        return "、".join(parts) if parts else None
    text = redact_sensitive_text(value).strip()
    return text or None


def _safe_tdc_sor_rows(rows: list[dict[str, Any]]) -> list[dict[str, str | None]]:
    """Return SOR rows with production display fields and no nested raw values."""
    safe: list[dict[str, str | None]] = []
    for row in rows:
        clean: dict[str, str | None] = {}
        for key, value in row.items():
            key_text = str(key)
            if key_text.lower() in _SENSITIVE_RESPONSE_KEYS:
                continue
            if key_text == "carTypeProject":
                clean[key_text] = _safe_tdc_sor_value(
                    value,
                    preferred_keys=("projectNo", "projectName"),
                )
            elif key_text == "currentAssigneeNameList":
                clean[key_text] = _safe_tdc_sor_value(
                    value,
                    preferred_keys=("name", "userName", "keyed_name"),
                )
            else:
                clean[key_text] = _safe_tdc_sor_value(value)
        safe.append(clean)
    return safe


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


def _ewo_filters_from_payload(payload: dict[str, Any]) -> EWOReportFilters:
    filters = _filter_payload(payload)
    return EWOReportFilters(
        ewo_no=_none_if_blank(filters.get("ewo_no")),
        project_code=_none_if_blank(filters.get("project_code")),
        subject_keyword=_none_if_blank(filters.get("subject_keyword")),
        change_type=_none_if_blank(filters.get("change_type")),
        change_sub_type=_none_if_blank(filters.get("change_sub_type")),
        area=_none_if_blank(filters.get("area")),
        state=_none_if_blank(filters.get("state")),
        rsp_department=_none_if_blank(filters.get("rsp_department")),
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


def _send_csv_attachment(
    path: Path,
    page: Any,
    max_pages: int,
    max_records: int,
    temp_dir: Path,
):
    """以 attachment 返回 CSV；可能截断时用 X-Export-* headers 明确告知。

    send_file 的响应是 direct_passthrough，其 call_on_close 不会随 WSGI
    app_iter 关闭触发（werkzeug 已知行为）；因此先把文件读入内存并立即删除
    临时目录（无句柄占用），再以 BytesIO 发送，临时文件生命周期不会外泄。
    """
    truncated = len(page.rows) >= max_records or (page.page is not None and page.page >= max_pages)
    data = path.read_bytes()
    shutil.rmtree(temp_dir, ignore_errors=True)
    response = send_file(
        io.BytesIO(data),
        mimetype="text/csv",
        as_attachment=True,
        download_name=path.name,
    )
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["X-Export-Complete"] = "false" if truncated else "true"
    response.headers["X-Export-Truncated"] = "true" if truncated else "false"
    response.headers["X-Export-Row-Count"] = str(len(page.rows))
    return response


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
    return TDCDataModelFilters(
        serial_number=values.get("serial_number"),
        applicant=values.get("applicant"),
        department=values.get("department"),
        section=values.get("section"),
        application_start=values.get("application_start"),
        application_end=values.get("application_end"),
        project_model=values.get("project_model"),
        part_number=values.get("part_number"),
        model_number=values.get("model_number"),
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


_TDC_DATA_MODEL_FILTER_NAMES = tuple(field["name"] for field in _TDC_DATA_MODEL_FIELDS)
_TDC_SOR_FILTER_NAMES = tuple(field["name"] for field in _TDC_SOR_FIELDS) + ("car_type_project_id",)


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
):
    if report_type == "data_model":
        return client.crawl_data_model_all(
            filters,
            page_size=page_size,
            max_pages=max_pages,
            max_records=max_records,
        )
    return client.crawl_sor_all(
        filters,
        page_size=page_size,
        max_pages=max_pages,
        max_records=max_records,
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
            project_id = project_no or project_name
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


def _project_status_payload(
    db: DatabaseManager,
    phase_id: str,
    *,
    today: date | None = None,
) -> dict[str, Any] | None:
    """把项目状态专用表序列化为前端唯一的已保存状态。"""
    phase_row, milestone_rows, deliverable_rows = db.get_project_status(phase_id)
    if phase_row is None:
        return None
    current_day = today or date.today()
    deliverables = []
    policy_summaries = db.get_project_status_update_policy_summaries(phase_id)
    for row in deliverable_rows:
        actual_date = row["actual_date"]
        planned_day = date.fromisoformat(str(row["planned_date"]))
        schedule_state: str | None = None
        schedule_days: int | None = None
        if row["status"] != "已完成":
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
                "sync_state": "idle",
                "last_attempt_at": None,
                "last_success_at": None,
                "last_error_type": None,
                "last_error_message": None,
                "updated_at": row["updated_at"],
            }
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
                "updateMethod": row["update_method"],
                "tone": _PROJECT_STATUS_TONES[row["status"]],
                "scheduleState": schedule_state,
                "scheduleDays": schedule_days,
                "updatedAt": row["updated_at"],
                "updatePolicy": {
                    "mode": summary["mode"],
                    "enabled": bool(summary["enabled"]),
                    "sourceType": summary["source_type"],
                    "syncState": summary["sync_state"],
                    "lastAttemptAt": summary["last_attempt_at"],
                    "lastSuccessAt": summary["last_success_at"],
                    "lastErrorType": summary["last_error_type"],
                    "lastErrorMessage": summary["last_error_message"],
                    "updatedAt": summary["updated_at"],
                },
                "associations": [],
            }
        )

    completed_count = sum(item["status"] == "已完成" for item in deliverables)
    risk_count = sum(
        item["status"] == "已逾期" or item["scheduleState"] == "overdue"
        for item in deliverables
    )
    overall_progress = int(phase_row["overall_progress"])
    planned_progress = int(phase_row["planned_progress"])
    overdue = next(
        (
            item
            for item in deliverables
            if item["status"] == "已逾期" or item["scheduleState"] == "overdue"
        ),
        None,
    )
    risk_text = "无"
    if overdue:
        if overdue["scheduleState"] == "overdue" and overdue["scheduleDays"] is not None:
            risk_text = f'{overdue["name"]}已逾期 {overdue["scheduleDays"]} 天'
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
    if not isinstance(raw_items, list) or not raw_items:
        return [], {"milestones": "主计划至少需要一个节点"}
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
        if not isinstance(date_text, str) or not date_text:
            errors[f"{prefix}.date"] = "节点日期不能为空"
            date_text = ""
        else:
            try:
                parsed_date = date.fromisoformat(date_text)
            except ValueError:
                errors[f"{prefix}.date"] = "节点日期格式无效"
        if parsed_date and not start_date <= parsed_date <= end_date:
            errors[f"{prefix}.date"] = "节点日期必须位于阶段周期内"

        normalized.append(
            {
                "id": milestone_id,
                "name": clean_name,
                "date": date_text,
                "status": requested_status,
                "type": node_type,
                "sort_order": index + 1,
            }
        )

    return normalized, errors


def _send_tdc_xlsx_attachment(result: Any, temp_dir: Path):
    """读入内存后立即清理临时目录，再以 BytesIO 发送 XLSX。"""
    path = Path(result.path)
    resolved = path.resolve()
    root = temp_dir.resolve()
    if not resolved.is_relative_to(root):
        raise TDCCrawlerError(
            "TDC export produced a path outside the temporary output directory",
            stage="export-validation",
        )
    data = resolved.read_bytes()
    shutil.rmtree(temp_dir, ignore_errors=True)
    response = send_file(
        io.BytesIO(data),
        mimetype=_TDC_XLSX_MIMETYPE,
        as_attachment=True,
        download_name=_safe_attachment_basename(path.name, fallback="tdc_export.xlsx"),
    )
    response.headers["Content-Type"] = _TDC_XLSX_MIMETYPE
    response.headers["X-Export-Complete"] = "true"
    response.headers["X-Export-File-Name"] = path.name
    response.headers["X-Export-Byte-Count"] = str(len(data))
    return response


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
        return _json_error(exc.status_code, exc.error_type, _sanitize_error_message(exc), exc.diagnostic_path)
    if isinstance(exc, TDCAuthError):
        return _json_error(401, "AuthenticationError", _sanitize_error_message(exc), getattr(exc, "diagnostic_path", None))
    if isinstance(exc, XLSXPreviewError):
        return _json_error(502, "TDCCrawlerError", _sanitize_error_message(exc))
    if isinstance(exc, ValueError):
        return _json_error(400, "ValidationError", _sanitize_error_message(exc))
    if isinstance(exc, TDCCrawlerError):
        status = 400 if exc.stage == "contract-validation" else 502
        return _json_error(status, "TDCCrawlerError", _sanitize_error_message(exc))
    logger.warning("TDC %s %s API failed: %s", report_type, operation, type(exc).__name__)
    return _json_error(500, type(exc).__name__, "Unexpected server error")


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
        page = _tdc_positive_int(payload.get("page"), "page", 1, _TDC_PAGE_MAX)
        page_size = _tdc_positive_int(payload.get("page_size"), "page_size", 50, _TDC_PAGE_SIZE_MAX)
        preview_source = _tdc_preview_source(payload)
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
    client: TDCCrawlerClient | None = None
    try:
        filters = filter_builder(_tdc_filters_from_payload(payload, allowed_names))
        page_size = _tdc_positive_int(payload.get("page_size"), "page_size", 50, _TDC_PAGE_SIZE_MAX)
        max_pages = _tdc_positive_int(payload.get("max_pages"), "max_pages", 100, _TDC_MAX_PAGES_MAX)
        max_records = _tdc_positive_int(
            payload.get("max_records"), "max_records", 10000, _TDC_MAX_RECORDS_MAX
        )
        preview_source = _tdc_preview_source(payload)
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
                operation="crawl_all",
                page_size=page_size,
                max_records=max_records,
            )
            return jsonify({"ok": True, "data": data})
        client = _build_tdc_client_from_payload(payload, allowed_hosts)
        result = _tdc_crawl(
            client,
            report_type,
            filters,
            page_size=page_size,
            max_pages=max_pages,
            max_records=max_records,
        )
        return jsonify({"ok": True, "data": _tdc_result_data(result)})
    except Exception as exc:
        return _tdc_error_response(exc, report_type, "crawl-all")
    finally:
        _close_owned_tdc_client(client)


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
    temp_dir = Path(tempfile.mkdtemp(prefix="tdc_export_"))
    client: TDCCrawlerClient | None = None
    try:
        file_name = _tdc_file_name(payload.get("file_name"))
        filters = filter_builder(_tdc_filters_from_payload(payload, allowed_names))
        if report_type == "data_model":
            safe_name = file_name or "tdc_data_model.xlsx"
            content, _ = _tdc_data_model_export_bytes(
                payload,
                filters,
                allowed_hosts,
                file_name=safe_name,
            )
            saved = (temp_dir / safe_name).resolve()
            if not saved.is_relative_to(temp_dir.resolve()):
                raise TDCCrawlerError(
                    "TDC export produced a path outside the temporary output directory",
                    stage="export-validation",
                )
            saved.write_bytes(content)
            result = TDCExportResult(
                report_type="data_model",
                file_name=safe_name,
                path=saved,
                byte_count=len(content),
                content_type=_TDC_XLSX_MIMETYPE,
                signature_valid=content.startswith(b"PK"),
                elapsed_ms=0.0,
                record_granularity="part_detail",
            )
        else:
            client = _build_tdc_client_from_payload(payload, allowed_hosts, output_dir=temp_dir)
            result = _tdc_export(client, report_type, filters, file_name=file_name)
        return _send_tdc_xlsx_attachment(result, temp_dir)
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return _tdc_error_response(exc, report_type, "export")
    finally:
        _close_owned_tdc_client(client)


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
) -> Flask:
    """Flask 应用工厂。

    `allowed_hosts` 覆盖 Aras 路由的主机 allowlist（默认仅 ecm.sgmw.com.cn）；
    `tdc_allowed_hosts` 覆盖 TDC 路由的主机 allowlist（默认仅 tdc.sgmw.com.cn）；
    localhost/测试 host 也可在创建后通过对应 app.config 键注入。
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

    def current_project_status(phase_id: str) -> dict[str, Any] | None:
        return _project_status_payload(
            db,
            phase_id,
            today=project_status_clock() if project_status_clock else None,
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
        return render_template("dashboard.html")

    @app.get("/favicon.ico")
    def favicon():
        return "", 204

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
        try:
            login_result = ArasECMAuthClient().login(username.strip(), password)
            domain_sessions.mark_authenticated("aras", login_result.session)
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

    def _deliverable_form_query() -> tuple[dict[str, object], int]:
        """Parse the shared read-only form-view query contract."""
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
        }
        control_keys = filter_keys | {"trendLimit", "offset", "limit"}
        unknown = set(request.args) - control_keys
        if unknown:
            raise ValueError("unsupported deliverable form query parameter")
        filters: dict[str, object] = {}
        for key in filter_keys:
            values = request.args.getlist(key)
            if len(values) > 1:
                raise ValueError(f"{key} accepts one value")
            if values and values[0] != "":
                filters[key] = values[0]

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

        return filters, strict_int("trendLimit", 30, 1, 365)

    @app.get("/api/deliverable-forms/<form_key>/view")
    def api_deliverable_form_view(form_key: str):
        try:
            filters, trend_limit = _deliverable_form_query()
            data = deliverable_form_service.view(
                form_key,
                filters=filters,
                trend_limit=trend_limit,
            )
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
            filters, _ = _deliverable_form_query()
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
            data = deliverable_form_service.rows(
                form_key,
                filters,
                offset=parsed_offset,
                limit=parsed_limit,
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
        aras_client: ArasCrawlerClient | None = None
        try:
            if deliverable_id in {"VPI-T2-D2", "VPI-T2-D5"}:
                client = _build_tdc_client_from_payload(
                    payload, app.config["TDC_ALLOWED_HOSTS"]
                )
                if deliverable_id == "VPI-T2-D2":
                    values = _tdc_filters_from_payload(payload, _TDC_SOR_FILTER_NAMES)
                    rows = client.crawl_sor_all(
                        _tdc_sor_filters(values), max_records=1000
                    ).rows
                else:
                    values = _tdc_filters_from_payload(payload, _TDC_DATA_MODEL_FILTER_NAMES)
                    rows = client.crawl_data_model_all(
                        _tdc_data_model_filters(values), max_records=1000
                    ).rows
                result = discovery_service.observe(deliverable_id, "tdc", rows, selected)
            elif deliverable_id == "VPI-T2-D3":
                aras_client = _build_aras_client_from_payload(
                    payload, app.config["ARAS_ALLOWED_HOSTS"]
                )
                rows = aras_client.crawl_ewo_report_all(
                    _ewo_filters_from_payload(payload), max_records=1000
                ).rows
                result = discovery_service.observe(deliverable_id, "aras", rows, selected)
            else:
                return _json_error(404, "NotFound", "未找到交付物")
            return jsonify({"ok": True, "data": result})
        except (_TDCRequestError, TDCCrawlerError, TDCAuthError) as exc:
            return _tdc_error_response(exc, "mapping-discovery", "query")
        except (_ArasRequestError, ArasCrawlerError, ArasAuthError) as exc:
            return _aras_error_response(exc, aras_client, "mapping-discovery")
        except Exception as exc:
            logger.exception("mapping discovery failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

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
        if deliverable_id == "VPI-T2-D1":
            return _json_error(409, "ManualOnly", "该交付物仅允许手工维护")
        if deliverable_id == "VPI-T2-D4":
            return _json_error(409, "ContractBlocked", AFACE_CONTRACT_BLOCKER)
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
        return jsonify(
            {
                "ok": True,
                "data": {
                    "categories": _DELIVERABLE_CATEGORIES,
                    "deliverables": _DELIVERABLES_CATALOG,
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
        client: ArasCrawlerClient | None = None
        try:
            client = _build_aras_client_from_payload(payload, app.config["ARAS_ALLOWED_HOSTS"])
            result = client.crawl_paa_report_all(
                _paa_filters_from_payload(payload),
                page_size=_positive_int(payload.get("page_size"), 50),
                max_pages=_positive_int(payload.get("max_pages"), 20),
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
                        **(
                            {"xml": _aras_xml_payload(result, payload)}
                            if _aras_xml_requested(payload)
                            else {}
                        ),
                    },
                }
            )
        except Exception as e:
            return _aras_error_response(e, client, "PAA crawl-all")

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
        temp_dir = Path(tempfile.mkdtemp(prefix="aras_ewo_export_"))
        client: ArasCrawlerClient | None = None
        try:
            client = _build_aras_client_from_payload(payload, app.config["ARAS_ALLOWED_HOSTS"])
            max_pages = _positive_int(payload.get("max_pages"), _EXPORT_DEFAULT_MAX_PAGES)
            max_records = _positive_int(payload.get("max_records"), _EXPORT_DEFAULT_MAX_RECORDS)
            page = client.crawl_ewo_report_all(
                _ewo_filters_from_payload(payload),
                page_size=_EXPORT_PAGE_SIZE,
                max_pages=max_pages,
                max_records=max_records,
            )
            export = export_report_contract_csv("ewo", page.rows, output_dir=temp_dir, file_name="ewo_export.csv")
            return _send_csv_attachment(export.path, page, max_pages, max_records, temp_dir)
        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return _aras_error_response(e, client, "EWO export")

    @app.post("/api/aras/paa/export")
    def api_aras_paa_export():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        temp_dir = Path(tempfile.mkdtemp(prefix="aras_paa_export_"))
        client: ArasCrawlerClient | None = None
        try:
            client = _build_aras_client_from_payload(payload, app.config["ARAS_ALLOWED_HOSTS"])
            max_pages = _positive_int(payload.get("max_pages"), _EXPORT_DEFAULT_MAX_PAGES)
            max_records = _positive_int(payload.get("max_records"), _EXPORT_DEFAULT_MAX_RECORDS)
            page = client.crawl_paa_report_all(
                _paa_filters_from_payload(payload),
                page_size=_EXPORT_PAGE_SIZE,
                max_pages=max_pages,
                max_records=max_records,
            )
            export = export_report_contract_csv("paa", page.rows, output_dir=temp_dir, file_name="paa_export.csv")
            return _send_csv_attachment(export.path, page, max_pages, max_records, temp_dir)
        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return _aras_error_response(e, client, "PAA export")

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

    return app


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
    app.run(host=FLASK_HOST, port=selected_port, debug=False)
