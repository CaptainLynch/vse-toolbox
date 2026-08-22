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
import ipaddress
import logging
import re
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlsplit

from flask import Flask, jsonify, render_template, request, send_file

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.config import DIAGNOSTIC_DIR, FLASK_HOST, FLASK_PORT
from core.archive_store import ArchiveSafetyError
from core.db_manager import (
    ArchiveJobNotReadyError,
    ArchiveLeaseBusyError,
    DatabaseManager,
    SyncBindingNotReadyError,
)
from core.diagnostics import DiagnosticOptions, MarkdownDiagnosticReport
from services.project_status_updates import (
    ProjectStatusPolicyError,
    ProjectStatusUpdateService,
)
from services.project_status_discovery import MappingDiscoveryService
from services.project_status_analytics import ProjectStatusAnalyticsService
from services.project_status_sync_runner import (
    ProjectStatusSyncRunner,
    create_production_registry,
)
from services.scheduled_archive_admin import (
    ArchiveAdminValidationError,
    ScheduledArchiveAdminService,
)
from core.redaction import redact_sensitive_text
from services.aras_crawler import (
    ArasCrawlerClient,
    ArasCrawlerError,
    DEFAULT_PAA_SELECT_FIELDS,
    EWOReportFilters,
    NCRApprovalFilters,
    PAAReportFilters,
)
from services.aras_auth import ArasAuthError, ArasECMAuthClient
from services.aras_department_mapping import normalize_departments, resolve_ncr_section_codes
from services.aras_export import export_ewo_report_csv, export_report_csv
from services.tdc_auth import TDCAuthError, TDCPasswordAuthClient
from services.tdc_crawler import (
    AFACE_CONTRACT_BLOCKER,
    TDCCrawlerClient,
    TDCCrawlerError,
    TDCDataModelFilters,
    TDCSORFilters,
)

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


def _json_error(status: int, error_type: str, message: str, diagnostic_path: Path | None = None):
    error: dict[str, Any] = {"type": error_type, "message": message}
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
    return parsed.scheme.lower(), parsed.hostname.rstrip(".").lower(), port


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


def _safe_scalar(value: Any) -> str:
    return redact_sensitive_text(value)


def _request_payload() -> tuple[dict[str, Any] | None, Any]:
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

    cookie = payload.get("cookie")
    if isinstance(cookie, str) and cookie.strip():
        headers["Cookie"] = cookie.strip()
    cookies = _clean_string_mapping(payload.get("cookies")) or None
    return ArasCrawlerClient(
        base_url,
        headers=headers,
        cookies=cookies,
        timeout=30.0,
    )


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


_TDC_DATA_MODEL_FILTER_NAMES = tuple(field["name"] for field in _TDC_DATA_MODEL_FIELDS)
_TDC_SOR_FILTER_NAMES = tuple(field["name"] for field in _TDC_SOR_FIELDS)


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
    return {
        "report_type": result.report_type,
        "rows": _safe_rows(result.rows),
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


_PROJECT_STATUS_VALUES = {"已完成", "进行中", "待审批", "已逾期"}
_PROJECT_STATUS_TONES = {
    "已完成": "success",
    "进行中": "primary",
    "待审批": "warning",
    "已逾期": "error",
}


def _project_status_payload(db: DatabaseManager, phase_id: str) -> dict[str, Any] | None:
    """把项目状态专用表序列化为前端唯一的已保存状态。"""
    phase_row, milestone_rows, deliverable_rows = db.get_project_status(phase_id)
    if phase_row is None:
        return None
    deliverables = []
    policy_summaries = db.get_project_status_update_policy_summaries(phase_id)
    for row in deliverable_rows:
        actual_date = row["actual_date"]
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
                "tone": _PROJECT_STATUS_TONES[row["status"]],
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
    risk_count = sum(item["status"] == "已逾期" for item in deliverables)
    overall_progress = int(phase_row["overall_progress"])
    planned_progress = int(phase_row["planned_progress"])
    overdue = next((item for item in deliverables if item["status"] == "已逾期"), None)
    risk_text = "无"
    if overdue:
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
            "status": phase_row["status"],
            "startDate": start_date,
            "endDate": end_date,
            "today": phase_row["simulated_today"],
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
                "status": row["status"],
                "type": row["type"],
                "sortOrder": row["sort_order"],
            }
            for row in milestone_rows
        ],
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
    current_count = 0
    phase = project_status["phase"]
    start_date = date.fromisoformat(str(phase["startDate"]))
    end_date = date.fromisoformat(str(phase["endDate"]))
    simulated_today = date.fromisoformat(str(phase["today"]))
    type_status = {
        "done": "已达成",
        "current": "当前目标节点",
        "planned": "计划节点",
    }

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

        node_type = raw.get("type")
        if not isinstance(node_type, str) or node_type not in type_status:
            errors[f"{prefix}.type"] = "请选择有效节点状态"
            node_type = "planned"
        expected_status = type_status[node_type]
        if raw.get("status") not in (None, expected_status):
            errors[f"{prefix}.status"] = "节点状态与类型不一致"
        if node_type == "current":
            current_count += 1

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
        elif parsed_date and node_type == "done" and parsed_date > simulated_today:
            errors[f"{prefix}.date"] = "已达成节点不能晚于当前日期"
        elif parsed_date and node_type == "planned" and parsed_date < simulated_today:
            errors[f"{prefix}.date"] = "计划节点不能早于当前日期"

        normalized.append(
            {
                "id": milestone_id,
                "name": clean_name,
                "date": date_text,
                "status": expected_status,
                "type": node_type,
                "sort_order": index + 1,
            }
        )

    if current_count != 1:
        errors["milestones"] = "主计划必须且只能有一个当前目标节点"
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


def _aras_error_response(
    exc: Exception,
    client: ArasCrawlerClient | None,
    operation: str,
):
    if isinstance(exc, _ArasRequestError):
        return _json_error(
            exc.status_code,
            exc.error_type,
            _sanitize_error_message(exc),
            exc.diagnostic_path,
        )
    diagnostic_path = _save_aras_client_diagnostic(client, exc)
    if isinstance(exc, ArasCrawlerError):
        return _json_error(
            502,
            "ArasCrawlerError",
            _sanitize_error_message(exc),
            diagnostic_path,
        )
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
    try:
        filters = filter_builder(_tdc_filters_from_payload(payload, allowed_names))
        page = _tdc_positive_int(payload.get("page"), "page", 1, _TDC_PAGE_MAX)
        page_size = _tdc_positive_int(payload.get("page_size"), "page_size", 50, _TDC_PAGE_SIZE_MAX)
        client = _build_tdc_client_from_payload(payload, allowed_hosts)
        result = _tdc_query(client, report_type, filters, page=page, page_size=page_size)
        return jsonify({"ok": True, "data": _tdc_result_data(result)})
    except Exception as exc:
        return _tdc_error_response(exc, report_type, "query")


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
    try:
        file_name = _tdc_file_name(payload.get("file_name"))
        filters = filter_builder(_tdc_filters_from_payload(payload, allowed_names))
        client = _build_tdc_client_from_payload(payload, allowed_hosts, output_dir=temp_dir)
        result = _tdc_export(client, report_type, filters, file_name=file_name)
        return _send_tdc_xlsx_attachment(result, temp_dir)
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return _tdc_error_response(exc, report_type, "export")


def create_app(
    allowed_hosts: Sequence[str] | None = None,
    tdc_allowed_hosts: Sequence[str] | None = None,
) -> Flask:
    """Flask 应用工厂。

    `allowed_hosts` 覆盖 Aras 路由的主机 allowlist（默认仅 ecm.sgmw.com.cn）；
    `tdc_allowed_hosts` 覆盖 TDC 路由的主机 allowlist（默认仅 tdc.sgmw.com.cn）；
    localhost/测试 host 也可在创建后通过对应 app.config 键注入。
    """
    if getattr(sys, "frozen", False):
        base_dir = Path(sys._MEIPASS) / "web"
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
    archive_admin_service = ScheduledArchiveAdminService(db)
    app.extensions["scheduled_archive_admin"] = archive_admin_service

    @app.route("/")
    def index():
        return render_template("dashboard.html")

    @app.route("/api/overview")
    def api_overview():
        try:
            data = _query_overview(db)
            return jsonify(data)
        except Exception as e:
            logger.exception("api/overview 查询失败")
            return jsonify({"error": str(e)}), 500

    @app.get("/api/scheduled-archive/jobs")
    def api_scheduled_archive_jobs():
        try:
            response = jsonify({"ok": True, "data": archive_admin_service.list_jobs()})
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception as exc:
            logger.exception("scheduled archive jobs query failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

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
            data = _project_status_payload(db, phase_id)
            if data is None:
                return _json_error(404, "NotFound", "未找到项目阶段")
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception as exc:
            logger.exception("api/project-status 查询失败")
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
            project_status = _project_status_payload(db, phase_id)
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

            updated_status = _project_status_payload(db, phase_id)
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
            project_status = _project_status_payload(db, phase_id)
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
            updated_status = _project_status_payload(db, phase_id)
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
            return jsonify(
                {
                    "ok": True,
                    "data": {
                        "rows": _safe_rows(result.rows),
                        "page": result.page,
                        "item_ids": result.item_ids,
                        "count": len(result.rows),
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
            return jsonify(
                {
                    "ok": True,
                    "data": {
                        "rows": _safe_rows(result.rows),
                        "page": result.page,
                        "item_ids": result.item_ids,
                        "count": len(result.rows),
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
            return jsonify(
                {
                    "ok": True,
                    "data": {
                        "rows": _safe_rows(result.rows),
                        "page": result.page,
                        "item_ids": result.item_ids,
                        "count": len(result.rows),
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
            return jsonify(
                {
                    "ok": True,
                    "data": {
                        "file_name": _safe_scalar(result.file_name),
                        "record_id": _safe_scalar(result.record_id),
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
            return jsonify({"ok": True, "data": {"file_name": _safe_scalar(result.file_name)}})
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
            export = export_ewo_report_csv(page, output_dir=temp_dir)
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
            export = export_report_csv(
                page.rows,
                output_dir=temp_dir,
                report_name="paa",
                preferred_fields=DEFAULT_PAA_SELECT_FIELDS,
            )
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
    app = create_app()
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False)
