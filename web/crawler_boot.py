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

