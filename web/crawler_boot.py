# -*- coding: utf-8 -*-
"""Aras/TDC 抓取查询门面路由（W13-06 迁自 web/app.py，路径/方法/信封/endpoint 逐字保持）。

_aras_* / _tdc_* 过滤器与报表查询助手一并迁入（TDC 路由 W13-07 复用同一实现，
web/app.py 留 re-export 别名）。企业凭据会话经注入的 domain_sessions 使用，
本模块不自行构建任何客户端或会话。
"""

from __future__ import annotations

import io
import ipaddress
import json
import logging
import re
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit

from flask import current_app, has_app_context, jsonify, request, send_file

import ipaddress

import re

import shutil

import tempfile

from pathlib import Path

from typing import Any, Callable, Mapping, Sequence, cast

from urllib.parse import urlsplit

from flask import Flask, current_app, has_app_context, jsonify, render_template, request, send_file

from core.config import DIAGNOSTIC_DIR, FLASK_HOST, FLASK_PORT

from core.domain_identity import (
    CredentialVaultError,
    DPAPICredentialProvider,
    DomainSessionRegistry,
    WindowsDPAPICredentialVault,
)

from core.report_contracts import matrix_payload, report_contracts, table_payload
from core.section_rollup import build_rollup_index
from core.project_status_contracts import DELIVERABLE_LINK_REGISTRY

from core.diagnostics import DiagnosticOptions, MarkdownDiagnosticReport

from services.aras_export import export_report_contract_csv
from services.aras_xml import ArasXmlCaptureError, sanitize_aras_xml

from services.xlsx_preview import XLSXPreviewError, read_xlsx_preview

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

from services.windows_http import WinHTTPError, WinHTTPTimeoutError


_DEFAULT_ARAS_ALLOWED_HOSTS: tuple[str, ...] = ("ecm.sgmw.com.cn",)

#: 测试 host 只能通过 create_app(tdc_allowed_hosts=...) 或
#: app.config["TDC_ALLOWED_HOSTS"] 显式注入。
_DEFAULT_TDC_ALLOWED_HOSTS: tuple[str, ...] = ("tdc.sgmw.com.cn",)



logger = logging.getLogger(__name__)


class CrawlerRouteDeps:
    """抓取路由依赖包：create_app 显式注入。"""

    def __init__(
        self,
        *,
        db: Any,
        crawl_task_runner: Any | None,
        domain_sessions: Any,
        tdc_export_cache: Any,
        excel_admin_service: Any | None,
        sanitize_error_message: Callable[[Exception], str],
        local_mutation_error: Callable[[], Any],
        json_ok: Callable[..., Any],
        json_error: Callable[..., Any],
        deliverable_form_service: Any | None = None,
        section_rollup_store: Any | None = None,
    ) -> None:
        self.db = db
        self.crawl_task_runner = crawl_task_runner
        self.domain_sessions = domain_sessions
        self.tdc_export_cache = tdc_export_cache
        self.excel_admin_service = excel_admin_service
        self.sanitize_error_message = sanitize_error_message
        self.local_mutation_error = local_mutation_error
        self.json_ok = json_ok
        self.json_error = json_error
        self.deliverable_form_service = deliverable_form_service
        self.section_rollup_store = section_rollup_store


logger = logging.getLogger("vse_toolbox.web")


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


_EXPORT_PAGE_SIZE = 2000


_EXPORT_DEFAULT_MAX_PAGES = 1000


_EXPORT_DEFAULT_MAX_RECORDS = 10000


_INVALID_ATTACHMENT_CHARS_RE = re.compile(r'[\x00-\x1f<>:"/\\|?*]')


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


def _safe_attachment_basename(name: str, fallback: str = "ncr_detail") -> str:
    """服务端安全 basename（去路径与控制字符），用于 Content-Disposition。"""
    base = Path(str(name or "")).name
    base = _INVALID_ATTACHMENT_CHARS_RE.sub("_", base).strip(" .")
    return base or fallback


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


def register_crawler_routes(app: Any, deps: CrawlerRouteDeps) -> None:
    # 闭包别名：被搬运的路由按 create_app 内原名引用这些对象。
    db = deps.db
    crawl_task_runner = deps.crawl_task_runner
    excel_admin_service = deps.excel_admin_service

    def _shared_domain_session(system: str):
        """企业凭据会话读取（原实现经 current_app.extensions 取注册表）。"""
        if not has_app_context():
            return None
        registry = current_app.extensions.get("domain_sessions")
        if not isinstance(registry, DomainSessionRegistry):
            return None
        return registry.session(system)

    def _local_web_mutation_error():
        return deps.local_mutation_error()

    def _json_error(*args: Any, **kwargs: Any):
        return deps.json_error(*args, **kwargs)

    def _json_ok(*args: Any, **kwargs: Any):
        return deps.json_ok(*args, **kwargs)

    def _sanitize_error_message(exc):
        return deps.sanitize_error_message(exc)

    # ── Aras 路由（逐字迁入） ──
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



# ── TDC 报表查询/导出门面（W13-07 迁入，三清单冻结法） ──

import csv

import hashlib

from dataclasses import asdict, replace

from services.form_search import MAX_TERMS as MAX_DOCUMENT_NOS

from services.form_search import parse_terms as parse_form_terms

from services.form_search import _SEPARATORS as _FORM_TERM_SEPARATORS

from services.project_status_records import (
    COMPLETE_RESULT_STOP_REASONS,
    MAX_AGGREGATE_RECORDS,
    authoritative_identity_field,
    authoritative_record_identity,
    identity_field_name,
    identity_fields,
)

from services.deliverable_form_analysis import SECTION_ROLLUP_FORM_KEYS

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

_TDC_PAGE_MAX = 1_000_000


_TDC_PAGE_SIZE_MAX = 1000


_TDC_MAX_PAGES_MAX = 10000


_TDC_MAX_RECORDS_MAX = 1_000_000


_TDC_XLSX_NAME_RE = re.compile(r"^[^<>:\"/\\|?*\x00-\x1f]+\.xlsx$", re.IGNORECASE)


_TDC_CSV_NAME_RE = re.compile(r"^[^<>:\"/\\|?*\x00-\x1f]+\.csv$", re.IGNORECASE)


_TDC_OFFICIAL_PREVIEW_MAX_ROWS = 50_001


_TDC_MERGED_MAX_ROWS = _TDC_OFFICIAL_PREVIEW_MAX_ROWS


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


def _safe_tdc_sor_rows(rows: list[dict[str, Any]]) -> list[dict[str, str | None]]:
    """SOR 行扁平化（共享实现见 services.tdc_crawler.flatten_sor_rows）。"""
    return flatten_sor_rows(rows)


_safe_tdc_sor_value = flatten_sor_value


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


def _mapping_result_is_complete(result: Any) -> bool:
    """抓取结果是否有显式终局证据（与 ``_require_complete_mapping_result`` 同源）。"""
    stop_reason = str(getattr(result, "stop_reason", "unknown") or "unknown")
    return getattr(result, "complete", None) is True and stop_reason in COMPLETE_RESULT_STOP_REASONS


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


def _tdc_file_name(value: Any, *, pattern: re.Pattern[str] | None = None) -> str | None:
    """校验用户提供的导出文件名（默认要求安全 `.xlsx` basename）。

    ``pattern`` 允许合并导出这类产物扩展名不同的路径复用同一套安全校验
    （长度/纯 basename/无穿越/无非法字符），避免为 `.csv` 另写一份校验。
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise _TDCRequestError("file_name must be a string")
    name = value.strip()
    if len(name) > 180:
        raise _TDCRequestError("file_name is too long")
    if Path(name).name != name or ".." in Path(name).parts:
        raise _TDCRequestError("file_name must be a plain basename without traversal")
    if not (pattern or _TDC_XLSX_NAME_RE).fullmatch(name):
        raise _TDCRequestError("file_name must be a safe .xlsx basename")
    return name


def _tdc_merged_file_name(value: Any) -> str | None:
    """合并导出的文件名：接受 `.xlsx`（用户看到的是「XLSX 文件名」框）或 `.csv`。

    Codex 复核 P2：产物是 CSV，但请求里的名字按 `.xlsx` 校验会让填 `.csv` 的用户
    拿到「must be a safe .xlsx basename」。两种扩展名都放行，产物统一改写为 `.csv`。
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, str) and value.strip().lower().endswith(".csv"):
        return _tdc_file_name(value, pattern=_TDC_CSV_NAME_RE)
    return _tdc_file_name(value)


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


_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


_STRICT_NUMBER_LITERAL = re.compile(r"^-?\d+(?:\.\d+)?$")


def _csv_cell(value: Any) -> Any:
    """单元格输出前的公式注入缓解（只处理文本，严格数字豁免）。

    Codex 复核 P1：只检查首字符会漏掉"前导空白/控制字符 + 公式"的形态，
    因此按**去掉前导空白后的首字符**判定；严格数字字面量（含前导空白）保持原样。
    """
    if not isinstance(value, str) or not value:
        return value
    probe = value.lstrip()
    if not probe:
        return value
    if probe[0] in _CSV_FORMULA_PREFIXES and not _STRICT_NUMBER_LITERAL.match(probe):
        return "'" + value
    return value


def _tdc_official_rows_csv(rows: Sequence[Mapping[str, Any]]) -> bytes:
    """官方工作簿行的 CSV 字节（UTF-8 BOM，Excel 双击可开）。

    列序与列头沿用官方 47 列契约，**逐列取值**：官方工作簿是全部官方列的唯一
    来源，列表接口只有其中 20 列——用列表行拼官方列会把"官方才有"的 27 列
    留空，用户会把空列读成"无人待签/数量为 0"（2026-10-13 生产反馈）。
    单元格经 ``_csv_cell`` 做公式注入缓解（数据来自上游报表，属不可信文本）。
    """
    labels = official_contract_headers("data_model")
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(labels)
    for row in rows:
        writer.writerow([_csv_cell(row.get(label)) for label in labels])
    return buffer.getvalue().encode("utf-8-sig")


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

    范围预检（2026-10-13 生产反馈）：流水单号不是上游查询参数，只能全量抓取后
    本地匹配；当上游声明的总行数已超过本次抓取上限（``max_pages × page_size``
    与 ``max_records`` 的较小值）时，用首页 ``total`` 直接给出可操作结论
    （``reason="range_too_large"``），不再空跑 max_pages 页后报"抓取不完整"
    （现场表现为同步请求跑满数分钟仍无结论）。
    """
    page_size = _tdc_positive_int(payload.get("page_size"), "page_size", 50, _TDC_PAGE_SIZE_MAX)
    max_pages = _tdc_positive_int(payload.get("max_pages"), "max_pages", 100, _TDC_MAX_PAGES_MAX)
    max_records = _tdc_positive_int(
        payload.get("max_records"), "max_records", 10000, _TDC_MAX_RECORDS_MAX
    )
    row_cap = min(max_pages * page_size, max_records)
    client: TDCCrawlerClient | None = None
    try:
        client = _build_tdc_client_from_payload(payload, allowed_hosts)
        probe = client.crawl_data_model_all(
            filters,
            page_size=page_size,
            max_pages=1,
            max_records=max_records,
        )
        total = getattr(probe, "total", None)
        if isinstance(total, int) and not isinstance(total, bool) and total > row_cap:
            data = _tdc_result_data(
                replace(probe, rows=[], unique_count=0, duplicate_count=0)
            )
            data["serialMatch"] = {
                "requested": document_nos if len(document_nos) > 1 else document_nos[0],
                "scanned": 0,
                "matched": 0,
                "scannedPages": int(getattr(probe, "fetched_pages", 0) or 0),
                "complete": False,
                "reason": "range_too_large",
                "total": total,
                "limit": row_cap,
            }
            return jsonify({"ok": True, "data": data})
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
                    "填了流水单号时，查询预览只能用「快速查询（list 接口）」：请把查询模式切回快速查询；"
                    "需要官方 47 列全量请到交付物工作台使用「导出合并结果」，或清空流水单号后再用官方 Excel 预览。",
                    "SerialRequiresListSource",
                    400,
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


def _tdc_report_export_merged(allowed_hosts: Sequence[str]):
    """数模「填多个流水单号 → 合并导出」：全量抓取 → 本地集合精确匹配 → 合并成一张 CSV。

    官方导出（`_tdc_report_export`）只按其它筛选条件取数，**不读**顶层的
    ``document_no``——多单号合并导出此前完全缺失（2026-10-10 用户反馈）。
    本入口复用查询侧同一套解析与匹配（``_tdc_document_nos`` + ``match_serials``），
    保证"预览里看到的合并行"与"导出的合并行"同源。
    """
    payload, error_response = _request_payload()
    if error_response:
        return error_response
    assert payload is not None
    try:
        file_name = _tdc_merged_file_name(payload.get("file_name")) or "tdc_data_model_merged.xlsx"
        document_nos = _tdc_document_nos(payload)
        if not document_nos:
            raise _TDCRequestError("请先填写至少一个流水单号（多个用空格、逗号或换行分隔）")
        # 与查询预览共用同一套筛选/分页参数构造，保证"预览命中的单号 = 导出命中的单号"。
        filters = _tdc_data_model_filters(
            _tdc_filters_from_payload(payload, _TDC_DATA_MODEL_FILTER_NAMES)
        )
        page_size = _tdc_positive_int(payload.get("page_size"), "page_size", 50, _TDC_PAGE_SIZE_MAX)
        max_pages = _tdc_positive_int(payload.get("max_pages"), "max_pages", 100, _TDC_MAX_PAGES_MAX)
        max_records = _tdc_positive_int(
            payload.get("max_records"), "max_records", 10000, _TDC_MAX_RECORDS_MAX
        )
    except Exception as exc:
        return _tdc_error_response(exc, "data_model", "export")

    session, gate_error = _async_session_gate("tdc", payload)
    if gate_error is not None:
        return gate_error
    try:
        base_url = str(payload["base_url"]).strip()
        _validate_tdc_base_url(base_url, allowed_hosts, require_https=False)
    except Exception as exc:
        return _tdc_error_response(exc, "data_model", "export")

    def worker(ctx):
        # 统一域会话是应用内存对象：worker 线程内复用，禁止关闭。
        work_dir = Path(tempfile.mkdtemp(prefix="tdc_merged_official_"))
        try:
            client = TDCCrawlerClient(
                base_url, session=session, timeout=30.0, output_dir=work_dir
            )
            ctx.update_progress(percent=5, stage="正在核对范围（官方报表行数）")
            # 范围预检：官方工作簿一次返回全部行，先用列表首页拿 total，避免为了
            # 一个超大范围去下载整表（也避免把"没抓全"说成"单号不存在"）。
            probe = client.crawl_data_model_all(
                filters, page_size=page_size, max_pages=1, max_records=max_records
            )
            total = getattr(probe, "total", None)
            if (
                isinstance(total, int)
                and not isinstance(total, bool)
                and total > _TDC_MERGED_MAX_ROWS
            ):
                raise _TDCRequestError(
                    f"当前条件命中 {total} 行，超过官方报表单次上限 "
                    f"{_TDC_MERGED_MAX_ROWS} 行；请补充车型/日期等条件后重试",
                    "RangeTooLarge",
                    422,
                )
            ctx.update_progress(percent=20, stage="正在生成官方报表（含全部官方列）")
            official = client.export_data_model(
                filters, file_name=f"{Path(str(file_name)).stem}_官方报表.xlsx"
            )
            ctx.update_progress(percent=70, stage="正在按流水单号筛选官方报表行")
            try:
                official_rows = read_official_tdc_rows(
                    Path(official.path), "data_model", max_rows=_TDC_MERGED_MAX_ROWS
                )
            except OfficialWorkbookTruncated:
                raise _TDCRequestError(
                    f"官方报表行数超过单次上限 {_TDC_MERGED_MAX_ROWS} 行，"
                    "请补充车型/日期等条件后重试",
                    "RangeTooLarge",
                    422,
                )
            except OfficialWorkbookContractError:
                raise _TDCRequestError(
                    "官方报表表头与已批准契约不一致，无法安全导出（请联系维护人员）",
                    "OfficialContractMismatch",
                    502,
                )
            except OfficialWorkbookUnreadable:
                raise _TDCRequestError(
                    "官方报表无法解析（不是有效的 XLSX 工作簿），请重试或联系维护人员",
                    "OfficialWorkbookUnreadable",
                    502,
                )
            matched, bookkeeping = match_serials(official_rows, document_nos)
            # fail-closed：请求了 N 个单号就必须全部命中——静默少导出会被当成"导出成功"，
            # 与查询预览"展示 missing"的语义不同（导出件是要带走的结果）。
            missing = [str(item) for item in bookkeeping.get("missing", [])]
            if missing or not matched:
                shown = "、".join(missing[:5]) + (f"（共 {len(missing)} 个）" if len(missing) > 5 else "")
                raise _TDCRequestError(
                    f"未找到以下流水单号：{shown}" if missing else "未找到任何匹配的流水单号",
                    "SerialNotFound",
                    422,
                )
            ctx.update_progress(percent=90, stage=f"命中 {len(matched)} 行，正在生成 CSV")
            stem = Path(str(file_name)).stem or "tdc_data_model_merged"
            out_path = ctx.downloads_dir / f"{stem}_合并_{ctx.task_id}.csv"
            out_path.write_bytes(_tdc_official_rows_csv(matched))
            ctx.set_artifact(out_path)
            ctx.update_progress(
                percent=100,
                stage=(
                    f"合并导出完成（{len(matched)} 行，官方 "
                    f"{len(official_contract_headers('data_model'))} 列）"
                ),
            )
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    params = {
        "base_url": base_url,
        "filters": asdict(filters),
        "document_no_count": len(document_nos),
        "page_size": page_size,
        "max_pages": max_pages,
        "max_records": max_records,
    }
    return _submit_background_task(
        _crawl_runner_from_request(),
        "tdc_data_model_export_merged",
        "tdc",
        params,
        worker,
        error_context="TDC merged export",
    )



def register_tdc_routes(app: Any, deps: CrawlerRouteDeps) -> None:
    # 闭包别名：被搬运的 TDC 路由按 create_app 内原名引用 db。
    db = deps.db

    # ── TDC 路由（逐字迁入） ──
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


    @app.post("/api/tdc/data-model/export-merged")
    def api_tdc_data_model_export_merged():
        """多流水单号合并导出（CSV）。官方导出不支持按单号过滤，见函数注释。"""
        return _tdc_report_export_merged(app.config["TDC_ALLOWED_HOSTS"])


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




# ── 交付物目录与表单统计路由（W13-08 迁入） ──

from core.db_manager import (
    ArchiveJobNotReadyError,
    ArchiveLeaseBusyError,
    DatabaseManager,
    MappedDeliverableReadOnlyError,
    PROJECT_STATUS_MILESTONE_TEMPLATE,
    SyncBindingNotReadyError,
)
from services.deliverable_statistics import (
    STATISTICS_HISTORY_SNAPSHOT_LIMIT,
    compute_form_statistics,
    statistics_history_entry,
)

_DELIVERABLE_CATEGORIES = [
    {"id": "aras", "name": "Aras 报告"},
    {"id": "tdc", "name": "TDC 报表"},
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



def register_form_catalog_routes(app: Any, deps: CrawlerRouteDeps) -> None:
    # 交付物表单/目录路由：服务与归集存储由 create_app 经 deps 注入；
    # 查询契约解析与归集索引构建为纯模块级逻辑（逐字迁自 create_app 闭包）。
    db = deps.db
    deliverable_form_service = deps.deliverable_form_service
    section_rollup_store = deps.section_rollup_store

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

    # ── 路由（逐字迁入） ──
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



