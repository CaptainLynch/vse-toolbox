# -*- coding: utf-8 -*-
"""
web/app.py — WEB 适配层：Flask 应用工厂 + /api/overview 路由

架构约束:
    - 唯一允许 import flask 的文件
    - 路由只做序列化与 HTTP 响应，不写业务 SQL
    - FLASK_HOST / FLASK_PORT 从 core.config 取值
    - service/core 层对 Flask 无感知
"""

import argparse
import atexit
import hashlib
import hmac
import logging
import math
import re
import secrets
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from flask import Flask, jsonify, render_template, request

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.config import FLASK_HOST, FLASK_PORT
from core.db_manager import DatabaseManager
from core.redaction import redact_sensitive_text
from services.aras_auth import (
    BROWSER_AUTH_SUBSTAGES,
    BROWSER_EXCEPTION_CATEGORIES,
    ArasAuthError,
    ArasPasswordAuthClient,
    close_authenticated_session,
)
from services.aras_crawler import (
    ArasCrawlerClient,
    ArasCrawlerError,
    EWOReportFilters,
    NCRApprovalFilters,
    PAAReportFilters,
)
from services.aras_report_export import (
    DEFAULT_EXPORT_MAX_PAGES,
    DEFAULT_EXPORT_MAX_RECORDS,
    DEFAULT_EXPORT_TIMEOUT_SECONDS,
    ArasReportExportError,
)
from services.ephemeral_test_session import (
    MAX_OPERATIONS,
    EphemeralOperationLease,
    EphemeralTestSessionError,
    EphemeralTestSessionVault,
)

logger = logging.getLogger("vse_toolbox.web")

_TEST_SESSION_PREFIX = "/api/test-session"
_TEST_SESSION_COOKIE = "vse_test_session"
_TEST_SESSION_CSRF_HEADER = "X-Test-Session-CSRF"
_TEST_SESSION_COOKIE_PATH = "/api/test-session"
_TEST_SESSION_HOST = f"127.0.0.1:{FLASK_PORT}"
_TEST_SESSION_ORIGIN = f"http://{_TEST_SESSION_HOST}"
_EXPORT_JOB_PREFIX = "/api/aras/export-jobs"
_EXPORT_JOB_COOKIE = "vse_aras_export_job"
_EXPORT_JOB_COOKIE_PATH = _EXPORT_JOB_PREFIX
_EXPORT_JOB_CSRF_HEADER = "X-Aras-Export-CSRF"
_EXPORT_JOB_ID_HEADER = "X-Aras-Export-Operation"
_EXPORT_JOB_TTL_SECONDS = 15 * 60
_TEST_SESSION_FILTER_FIELDS = {
    "ewo": frozenset(
        {
            "ewo_no",
            "project_code",
            "subject_keyword",
            "change_type",
            "change_sub_type",
            "area",
            "state",
            "rsp_department",
            "rsp_department_keyword",
            "model_keyword",
            "submit_start",
            "submit_end",
        }
    ),
    "paa": frozenset(
        {
            "paa_no",
            "ewo_no",
            "state",
            "area",
            "base",
            "department_keyword",
            "vehicle_keyword",
            "submit_start",
            "submit_end",
            "mtl_rq_start",
            "mtl_rq_end",
        }
    ),
}

_PUBLIC_AUTH_STAGES = frozenset(
    {
        "transport",
        "client",
        "discovery",
        "metadata",
        "authorize",
        "form",
        "credentials",
        "browser",
        "callback",
        "validation",
        "base_load",
        "credential_submit",
        "callback_wait",
        "callback_verify",
        "auth_capability_wait",
        "auth_header_call",
        "soap_dispatch",
        "soap_response",
        "soap_parse",
        "business_ready",
        "cleanup",
    }
)
_SCHEME_A_AUTH_STAGES = frozenset(
    {
        "base_load",
        "credential_submit",
        "callback_wait",
        "callback_verify",
        "auth_capability_wait",
        "auth_header_call",
        "soap_dispatch",
        "soap_response",
        "soap_parse",
        "business_ready",
        "cleanup",
    }
)

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

_PUBLIC_EXPORT_ERROR_CODES = frozenset(
    {
        "AUTH_BROWSER_UNAVAILABLE",
        "AUTH_CALLBACK_INVALID",
        "AUTH_CALLBACK_TIMEOUT",
        "AUTH_SESSION_CAPABILITY_TIMEOUT",
        "AUTH_SESSION_CAPABILITY_AMBIGUOUS",
        "AUTH_AUTHORIZATION_UNAVAILABLE",
        "AUTH_SOAP_GATE_FAILED",
        "AUTH_EXPORT_CANCELLED",
        "AUTH_DEADLINE_EXCEEDED",
        "AUTH_CLEANUP_FAILED",
        "AUTH_CREDENTIALS_REJECTED",
        "AUTH_MODE_CONFLICT",
        "INSECURE_HTTP_NOT_ALLOWED",
        "INVALID_REQUEST",
        "INVALID_EXPORT_LIMIT",
        "EXPORT_TIMEOUT",
        "FILE_WRITE_FAILED",
        "SESSION_EXPIRED",
        "UPSTREAM_REQUEST_FAILED",
        "EXPORT_FAILED",
        "EXPORT_JOB_BUSY",
        "EXPORT_JOB_NOT_FOUND",
        "EXPORT_JOB_FORBIDDEN",
        "EXPORT_JOB_PROTOCOL_FAILED",
    }
)


@dataclass
class _ExportJob:
    operation_id: str = field(repr=False)
    sid_digest: bytes = field(repr=False)
    csrf_digest: bytes = field(repr=False)
    module: str
    created_at: float
    expires_at: float
    status: str = "running"
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    cancel_requested: bool = False
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    session: Any | None = field(default=None, repr=False)
    thread: threading.Thread | None = field(default=None, repr=False)


class _ExportJobCoordinator:
    """RAM-only single-flight owner for EWO/PAA browser export jobs."""

    def __init__(self, *, ttl_seconds: float = _EXPORT_JOB_TTL_SECONDS) -> None:
        self._ttl_seconds = max(60.0, float(ttl_seconds))
        self._lock = threading.RLock()
        self._jobs: dict[str, _ExportJob] = {}
        self._closed = False

    @staticmethod
    def _digest(value: str) -> bytes:
        return hashlib.sha256(value.encode("ascii", errors="strict")).digest()

    @staticmethod
    def _token() -> str:
        return secrets.token_urlsafe(32)

    def _purge_locked(self, now: float) -> None:
        expired = [
            operation_id
            for operation_id, job in self._jobs.items()
            if job.status != "running" and job.expires_at <= now
        ]
        for operation_id in expired:
            job = self._jobs.pop(operation_id, None)
            if job is not None:
                job.result = None
                job.error = None
                job.session = None
                job.thread = None

    def start(
        self,
        module: str,
        payload: dict[str, Any],
        runner: Callable[[_ExportJob, dict[str, Any]], None],
    ) -> tuple[str, str, str]:
        with self._lock:
            if self._closed:
                raise RuntimeError("EXPORT_JOB_NOT_FOUND")
            now = time.monotonic()
            self._purge_locked(now)
            if any(job.status in {"running", "cancelling"} for job in self._jobs.values()):
                raise RuntimeError("EXPORT_JOB_BUSY")
            operation_id = self._token()
            sid = self._token()
            csrf = self._token()
            job = _ExportJob(
                operation_id=operation_id,
                sid_digest=self._digest(sid),
                csrf_digest=self._digest(csrf),
                module=module,
                created_at=now,
                expires_at=now + self._ttl_seconds,
            )
            thread = threading.Thread(
                target=self._run,
                args=(job, payload, runner),
                name=f"vse-aras-export-{module}",
                daemon=True,
            )
            job.thread = thread
            self._jobs[operation_id] = job
            thread.start()
            return operation_id, sid, csrf

    def _run(
        self,
        job: _ExportJob,
        payload: dict[str, Any],
        runner: Callable[[_ExportJob, dict[str, Any]], None],
    ) -> None:
        try:
            runner(job, payload)
        finally:
            password = payload.get("password")
            if isinstance(password, str):
                payload["password"] = ""
            payload.clear()
            with self._lock:
                job.session = None
                job.thread = None
                job.expires_at = time.monotonic() + self._ttl_seconds
                if job.status in {"running", "cancelling"}:
                    job.status = "cancelled" if job.cancel_requested else "failed"
                    if job.error is None and job.status == "failed":
                        job.error = _fixed_export_error("EXPORT_FAILED")

    def attach_session(self, job: _ExportJob, session: Any) -> None:
        with self._lock:
            if self._jobs.get(job.operation_id) is not job:
                raise RuntimeError("EXPORT_JOB_NOT_FOUND")
            job.session = session
            should_cancel = job.cancel_requested
        if should_cancel:
            request_cancel = getattr(session, "request_cancel", None)
            if callable(request_cancel):
                request_cancel()

    def complete(self, job: _ExportJob, result: dict[str, Any]) -> None:
        with self._lock:
            if self._jobs.get(job.operation_id) is not job:
                return
            job.result = result
            job.error = None
            job.status = str(result.get("status") or "completed")

    def fail(self, job: _ExportJob, error: dict[str, Any]) -> None:
        with self._lock:
            if self._jobs.get(job.operation_id) is not job:
                return
            job.result = None
            job.error = error
            job.status = "cancelled" if error.get("code") == "AUTH_EXPORT_CANCELLED" else "failed"

    def _require(self, operation_id: str, sid: str, csrf: str) -> _ExportJob:
        with self._lock:
            self._purge_locked(time.monotonic())
            job = self._jobs.get(operation_id)
            try:
                sid_digest = self._digest(sid)
                csrf_digest = self._digest(csrf)
            except (UnicodeError, ValueError):
                job = None
                sid_digest = b""
                csrf_digest = b""
            if (
                job is None
                or not hmac.compare_digest(job.sid_digest, sid_digest)
                or not hmac.compare_digest(job.csrf_digest, csrf_digest)
            ):
                raise RuntimeError("EXPORT_JOB_NOT_FOUND")
            return job

    def status(self, operation_id: str, sid: str, csrf: str) -> dict[str, Any]:
        job = self._require(operation_id, sid, csrf)
        with self._lock:
            response: dict[str, Any] = {
                "ok": job.status in {"running", "cancelling", "completed", "partial"},
                "module": job.module,
                "status": job.status,
            }
            if job.result is not None:
                response.update(job.result)
            if job.error is not None:
                response["error"] = dict(job.error)
            return response

    def cancel(self, operation_id: str, sid: str, csrf: str) -> str:
        job = self._require(operation_id, sid, csrf)
        with self._lock:
            if job.status not in {"running", "cancelling"}:
                return job.status
            job.cancel_requested = True
            job.cancel_event.set()
            job.status = "cancelling"
            session = job.session
        request_cancel = getattr(session, "request_cancel", None)
        if callable(request_cancel):
            try:
                request_cancel()
            except Exception:
                pass
        return "cancelling"

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            jobs = list(self._jobs.values())
            for job in jobs:
                if job.status in {"running", "cancelling"}:
                    job.cancel_requested = True
                    job.cancel_event.set()
                    job.status = "cancelling"
                session = job.session
                request_cancel = getattr(session, "request_cancel", None)
                if callable(request_cancel):
                    try:
                        request_cancel()
                    except Exception:
                        pass
        for job in jobs:
            thread = job.thread
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=2.0)


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


def _json_error(status: int, error_type: str, message: str, *, stage: str | None = None):
    error = {"type": error_type, "message": message}
    if stage is not None:
        error["stage"] = stage
    return jsonify({"ok": False, "error": error}), status


def _json_export_error(
    module: str,
    status: int,
    code: str,
    message: str,
    *,
    stage: str | None = None,
):
    error = {"code": code, "message": message}
    if stage is not None:
        error["stage"] = stage
    return (
        jsonify(
            {
                "ok": False,
                "module": module,
                "status": "failed",
                "error": error,
            }
        ),
        status,
    )


def _public_auth_stage(stage: str) -> str:
    return stage if stage in _PUBLIC_AUTH_STAGES else "authentication"


def _public_browser_substage(substage: str | None) -> str | None:
    return substage if substage in BROWSER_AUTH_SUBSTAGES else None


def _public_browser_category(category: str | None) -> str | None:
    return category if category in BROWSER_EXCEPTION_CATEGORIES else None


def _fixed_export_error(
    code: str,
    *,
    stage: str | None = None,
    category: str | None = None,
    capability_mask: int = 0,
) -> dict[str, Any]:
    safe_code = code if code in _PUBLIC_EXPORT_ERROR_CODES else "EXPORT_FAILED"
    error: dict[str, Any] = {"code": safe_code, "retryable": False}
    if stage in _PUBLIC_AUTH_STAGES:
        error["stage"] = stage
    if category in BROWSER_EXCEPTION_CATEGORIES:
        error["category"] = category
    if stage in _SCHEME_A_AUTH_STAGES:
        error["capability_mask"] = (
            int(capability_mask) & ((1 << 14) - 1)
            if isinstance(capability_mask, int) and not isinstance(capability_mask, bool)
            else 0
        )
    return error


def _public_auth_error(error: ArasAuthError) -> dict[str, Any]:
    return _fixed_export_error(
        str(error.code or ""),
        stage=_public_auth_stage(str(error.stage or "")),
        category=_public_browser_category(error.category),
        capability_mask=getattr(error, "capability_mask", 0),
    )


def _json_auth_error(error: ArasAuthError, *, module: str | None = None):
    stage = _public_auth_stage(str(error.stage or ""))
    substage = _public_browser_substage(error.substage)
    category = _public_browser_category(error.category)
    logger.warning(
        "Aras authentication failed: code=%s stage=%s substage=%s category=%s",
        error.code,
        stage,
        substage or "",
        category or "",
    )
    public_error: dict[str, Any] = {"code": error.code, "stage": stage}
    if substage is not None:
        public_error["substage"] = substage
    if category is not None:
        public_error["category"] = category
    if stage in _SCHEME_A_AUTH_STAGES:
        raw_mask = getattr(error, "capability_mask", 0)
        public_error["capability_mask"] = (
            int(raw_mask) & ((1 << 14) - 1)
            if isinstance(raw_mask, int) and not isinstance(raw_mask, bool)
            else 0
        )
        public_error["retryable"] = False
    if module is not None:
        return (
            jsonify(
                {
                    "ok": False,
                    "module": module,
                    "status": "failed",
                    "error": public_error,
                }
            ),
            error.http_status,
        )
    return jsonify({"ok": False, "error": public_error}), error.http_status


def _test_session_json(
    body: dict[str, Any],
    status: int = 200,
    *,
    set_sid: str | None = None,
    clear_cookie: bool = False,
):
    response = jsonify(body)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    if set_sid is not None:
        response.set_cookie(
            _TEST_SESSION_COOKIE,
            set_sid,
            httponly=True,
            secure=False,
            samesite="Strict",
            path=_TEST_SESSION_COOKIE_PATH,
        )
    if clear_cookie:
        response.delete_cookie(
            _TEST_SESSION_COOKIE,
            path=_TEST_SESSION_COOKIE_PATH,
            secure=False,
            httponly=True,
            samesite="Strict",
        )
    return response


def _test_session_error(code: str, status: int, *, clear_cookie: bool = False):
    return _test_session_json(
        {"ok": False, "error": {"code": code}},
        status,
        clear_cookie=clear_cookie,
    )


def _test_session_request_gate() -> tuple[str, int] | None:
    forwarded_headers = (
        "Forwarded",
        "X-Forwarded-For",
        "X-Forwarded-Host",
        "X-Forwarded-Proto",
    )
    if (
        request.remote_addr != "127.0.0.1"
        or request.host != _TEST_SESSION_HOST
        or request.headers.get("Origin", "") != _TEST_SESSION_ORIGIN
        or request.headers.get("Sec-Fetch-Site", "") != "same-origin"
        or any(request.headers.get(name) for name in forwarded_headers)
    ):
        return "TEST_SESSION_LOOPBACK_REQUIRED", 403
    return None


def _test_session_tokens() -> tuple[str, str]:
    return (
        str(request.cookies.get(_TEST_SESSION_COOKIE, "") or ""),
        str(request.headers.get(_TEST_SESSION_CSRF_HEADER, "") or ""),
    )


def _clean_test_session_filters(value: Any, module: str) -> dict[str, Any]:
    if not isinstance(value, dict) or len(value) > 64:
        raise EphemeralTestSessionError("TEST_SESSION_INVALID", http_status=400)
    allowed_fields = _TEST_SESSION_FILTER_FIELDS.get(module, frozenset())
    clean: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or key not in allowed_fields:
            raise EphemeralTestSessionError("TEST_SESSION_INVALID", http_status=400)
        if item is None or isinstance(item, bool):
            clean[key] = item
        elif isinstance(item, int):
            clean[key] = item
        elif isinstance(item, float) and math.isfinite(item):
            clean[key] = item
        elif isinstance(item, str) and len(item) <= 512:
            clean[key] = item.strip()
        else:
            raise EphemeralTestSessionError("TEST_SESSION_INVALID", http_status=400)
    return clean


def _test_session_status_error(error: EphemeralTestSessionError):
    return _test_session_error(
        error.code,
        error.http_status,
        clear_cookie=error.code
        in {"TEST_SESSION_NOT_FOUND", "TEST_SESSION_EXPIRED", "TEST_SESSION_LIMIT_REACHED"},
    )


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


def _close_aras_client(client: Any) -> None:
    session = getattr(client, "session", None)
    if session is None:
        return
    client_headers = getattr(client, "headers", None)
    if hasattr(client_headers, "clear"):
        try:
            client_headers.clear()
        except Exception:
            pass
    try:
        session.headers.clear()
    except Exception:
        pass
    try:
        session.cookies.clear()
    except Exception:
        pass
    try:
        session.close()
    except Exception:
        pass


def _request_payload() -> tuple[dict[str, Any] | None, Any]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, _json_error(400, "ValidationError", "JSON object body is required")
    if not str(payload.get("base_url") or "").strip():
        return None, _json_error(400, "ValidationError", "base_url is required")
    return payload, None


def _export_request_payload(module: str) -> tuple[dict[str, Any] | None, Any]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, _json_export_error(
            module,
            400,
            "INVALID_REQUEST",
            "JSON object body is required.",
        )
    if not str(payload.get("base_url") or "").strip():
        return None, _json_export_error(
            module,
            400,
            "INVALID_REQUEST",
            "base_url is required.",
        )
    return payload, None


def _clean_string_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    clean: dict[str, str] = {}
    for key, item in value.items():
        if isinstance(key, str) and isinstance(item, str) and key.strip() and item.strip():
            clean[key.strip()] = item.strip()
    return clean


def _build_aras_client_from_payload(
    payload: dict[str, Any], *, cancel_event: threading.Event | None = None
) -> ArasCrawlerClient:
    if payload.pop("_legacy_header_cookie_only", False) is True:
        return _build_legacy_aras_client_from_payload(payload)
    headers = _clean_string_mapping(payload.get("headers"))
    cookie = payload.get("cookie")
    if isinstance(cookie, str) and cookie.strip():
        headers["Cookie"] = cookie.strip()
    cookies = _clean_string_mapping(payload.get("cookies")) or None
    username = _none_if_blank(payload.pop("username", None))
    password_value = payload.pop("password", None)
    password = str(password_value) if password_value is not None else ""
    uses_password = username is not None or bool(password)
    uses_fallback = bool(headers or cookies)
    if uses_password and uses_fallback:
        password = ""
        raise ArasAuthError(
            "AUTH_MODE_CONFLICT",
            "Password authentication cannot be combined with temporary headers or cookies.",
            stage="credentials",
            http_status=400,
        )
    if uses_password:
        try:
            auth = ArasPasswordAuthClient(
                str(payload["base_url"]).strip(),
                allow_insecure_http=payload.get("allow_insecure_http") is True,
                timeout=30.0,
                cancel_event=cancel_event,
            )
            login = auth.login(
                username or "",
                password,
                validation_item_type=str(payload.pop("_validation_item_type", "EWO_O")),
            )
            return ArasCrawlerClient(
                str(payload["base_url"]).strip(),
                session=login.session,
                timeout=30.0,
                prewarm=False,
            )
        finally:
            password = ""
    return ArasCrawlerClient(
        str(payload["base_url"]).strip(),
        headers=headers,
        cookies=cookies,
        timeout=30.0,
    )


def _build_legacy_aras_client_from_payload(payload: dict[str, Any]) -> ArasCrawlerClient:
    """Keep NCR on its pre-existing temporary Header/Cookie authentication path."""
    username = _none_if_blank(payload.pop("username", None))
    password_value = payload.pop("password", None)
    password = str(password_value) if password_value is not None else ""
    try:
        if username is not None or bool(password):
            raise ArasAuthError(
                "AUTH_MODE_NOT_SUPPORTED",
                "Password authentication is not enabled for NCR compatibility endpoints.",
                stage="credentials",
                http_status=400,
            )
        headers = _clean_string_mapping(payload.get("headers"))
        cookie = payload.get("cookie")
        if isinstance(cookie, str) and cookie.strip():
            headers["Cookie"] = cookie.strip()
        cookies = _clean_string_mapping(payload.get("cookies")) or None
        return ArasCrawlerClient(
            str(payload["base_url"]).strip(),
            headers=headers,
            cookies=cookies,
            timeout=30.0,
        )
    finally:
        password = ""


def _filter_payload(payload: dict[str, Any]) -> dict[str, Any]:
    filters = payload.get("filters", {})
    return filters if isinstance(filters, dict) else {}


def _none_if_blank(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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
        rsp_department_keyword=_none_if_blank(filters.get("rsp_department_keyword")),
        model_keyword=_none_if_blank(filters.get("model_keyword")),
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
        department_keyword=_none_if_blank(filters.get("department_keyword")),
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
        change_type=_none_if_blank(filters.get("change_type")),
        othercondition=str(filters.get("othercondition") or "0").strip() or "0",
    )


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _export_limits_from_payload(payload: dict[str, Any]) -> tuple[int, int, float]:
    limits = payload.get("limits", {})
    if limits is None:
        limits = {}
    if not isinstance(limits, dict):
        raise ArasReportExportError(
            "INVALID_EXPORT_LIMIT",
            "Export limits must be an object.",
            http_status=400,
        )

    def positive_number(name: str, default: float, maximum: float, integer: bool) -> int | float:
        value = limits.get(name, payload.get(name, default))
        try:
            if isinstance(value, bool):
                raise ValueError("boolean is not a numeric export limit")
            if integer:
                if isinstance(value, int):
                    parsed: int | float = value
                elif isinstance(value, float):
                    if not math.isfinite(value) or not value.is_integer():
                        raise ValueError("integer export limit required")
                    parsed = int(value)
                elif isinstance(value, str) and re.fullmatch(r"\+?\d+", value.strip()):
                    parsed = int(value.strip())
                else:
                    raise ValueError("integer export limit required")
            else:
                parsed = float(value)
                if not math.isfinite(parsed):
                    raise ValueError("finite export limit required")
        except (TypeError, ValueError, OverflowError) as exc:
            raise ArasReportExportError(
                "INVALID_EXPORT_LIMIT",
                "Export limits must be positive numbers.",
                http_status=400,
            ) from exc
        if parsed <= 0:
            raise ArasReportExportError(
                "INVALID_EXPORT_LIMIT",
                "Export limits must be positive numbers.",
                http_status=400,
            )
        return min(parsed, int(maximum) if integer else maximum)

    return (
        int(positive_number("max_pages", DEFAULT_EXPORT_MAX_PAGES, DEFAULT_EXPORT_MAX_PAGES, True)),
        int(
            positive_number(
                "max_records",
                DEFAULT_EXPORT_MAX_RECORDS,
                DEFAULT_EXPORT_MAX_RECORDS,
                True,
            )
        ),
        float(
            positive_number(
                "timeout_seconds",
                DEFAULT_EXPORT_TIMEOUT_SECONDS,
                DEFAULT_EXPORT_TIMEOUT_SECONDS,
                False,
            )
        ),
    )


def create_app(*, enable_ephemeral_test_session: bool = False) -> Flask:
    """Flask 应用工厂。"""
    if enable_ephemeral_test_session and FLASK_HOST != "127.0.0.1":
        raise RuntimeError("TEST_SESSION_LOOPBACK_REQUIRED")
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    test_session_vault = (
        EphemeralTestSessionVault() if enable_ephemeral_test_session else None
    )
    export_jobs = _ExportJobCoordinator()
    app.extensions["aras_export_jobs"] = export_jobs
    atexit.register(export_jobs.close)
    app.config["EPHEMERAL_TEST_SESSION_ENABLED"] = test_session_vault is not None
    if test_session_vault is not None:
        app.extensions["ephemeral_test_session_vault"] = test_session_vault
        atexit.register(test_session_vault.close)

    # DatabaseManager 实例化一次，init_database 只在启动时调用
    db = DatabaseManager()
    db.init_database()

    @app.after_request
    def test_session_no_store(response):  # type: ignore[no-untyped-def]
        if request.path.startswith((_TEST_SESSION_PREFIX, _EXPORT_JOB_PREFIX)):
            response.headers["Cache-Control"] = "no-store, private"
            response.headers["Pragma"] = "no-cache"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def require_test_session_vault():  # type: ignore[no-untyped-def]
        if test_session_vault is None:
            return None, _test_session_error(
                "TEST_SESSION_DISABLED", 404, clear_cookie=True
            )
        gate_error = _test_session_request_gate()
        if gate_error is not None:
            code, status = gate_error
            return None, _test_session_error(code, status)
        return test_session_vault, None

    @app.post("/api/test-session/bootstrap")
    def api_test_session_bootstrap():
        vault, error_response = require_test_session_vault()
        if error_response is not None:
            return error_response
        assert vault is not None
        sid, csrf = vault.bootstrap()
        return _test_session_json(
            {
                "ok": True,
                "csrf": csrf,
                "status": {
                    "seeded": False,
                    "password_cached": False,
                    "authenticated": False,
                    "running": False,
                    "operations_remaining": MAX_OPERATIONS,
                },
            },
            set_sid=sid,
        )

    @app.post("/api/test-session/seed")
    def api_test_session_seed():
        vault, error_response = require_test_session_vault()
        if error_response is not None:
            return error_response
        assert vault is not None
        sid, csrf = _test_session_tokens()
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not set(payload).issubset(
            {
                "base_url",
                "username",
                "password",
                "allow_insecure_http",
                "module",
                "filters",
            }
        ):
            return _test_session_error("TEST_SESSION_INVALID", 400)
        password_value = payload.pop("password", None)
        password = password_value if isinstance(password_value, str) else ""
        try:
            base_url = str(payload.get("base_url") or "").strip()
            username = str(payload.get("username") or "").strip()
            module = str(payload.get("module") or "").strip().casefold()
            allow_insecure_http = payload.get("allow_insecure_http") is True
            if (
                not base_url
                or len(base_url) > 2048
                or not username
                or len(username) > 256
                or not password
                or len(password.encode("utf-8")) > 4096
                or module not in {"ewo", "paa"}
            ):
                return _test_session_error("TEST_SESSION_INVALID", 400)
            filters = _clean_test_session_filters(payload.get("filters", {}), module)
            canonical_base_url = ArasPasswordAuthClient(
                base_url,
                allow_insecure_http=allow_insecure_http,
            ).base_url
            new_sid, new_csrf, status = vault.seed(
                sid,
                csrf,
                base_url=canonical_base_url,
                username=username,
                password=password,
                allow_insecure_http=allow_insecure_http,
                module=module,
                filters=filters,
            )
            return _test_session_json(
                {"ok": True, "csrf": new_csrf, "status": status},
                set_sid=new_sid,
            )
        except EphemeralTestSessionError as error:
            return _test_session_status_error(error)
        except ArasAuthError as error:
            return _json_auth_error(error)
        finally:
            password = ""
            password_value = None
            payload.clear()

    @app.post("/api/test-session/status")
    def api_test_session_status():
        vault, error_response = require_test_session_vault()
        if error_response is not None:
            return error_response
        assert vault is not None
        sid, csrf = _test_session_tokens()
        try:
            return _test_session_json(
                {"ok": True, "status": vault.status(sid, csrf)}
            )
        except EphemeralTestSessionError as error:
            return _test_session_status_error(error)

    @app.post("/api/test-session/clear")
    def api_test_session_clear():
        vault, error_response = require_test_session_vault()
        if error_response is not None:
            return error_response
        assert vault is not None
        sid, csrf = _test_session_tokens()
        try:
            status = vault.status(sid, csrf)
            vault.clear(sid, csrf)
            if status.get("running") is True:
                return _test_session_json({"ok": True, "status": "cancelling"})
            return _test_session_json(
                {"ok": True, "status": "cleared"}, clear_cookie=True
            )
        except EphemeralTestSessionError as error:
            return _test_session_status_error(error)

    @app.post("/api/test-session/export")
    def api_test_session_export():
        vault, error_response = require_test_session_vault()
        if error_response is not None:
            return error_response
        assert vault is not None
        sid, csrf = _test_session_tokens()
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not set(payload).issubset(
            {"module", "filters", "max_pages", "max_records", "timeout_seconds"}
        ):
            return _test_session_error("TEST_SESSION_INVALID", 400)
        module = str(payload.get("module") or "").strip().casefold()
        if module not in {"ewo", "paa"}:
            return _test_session_error("TEST_SESSION_INVALID", 400)
        try:
            filters = (
                _clean_test_session_filters(payload["filters"], module)
                if "filters" in payload
                else None
            )
        except EphemeralTestSessionError as error:
            return _test_session_status_error(error)

        lease: EphemeralOperationLease | None = None
        client: ArasCrawlerClient | None = None
        password = ""
        try:
            lease = vault.begin_operation(
                sid,
                csrf,
                module=module,
                filters=filters,
            )
            max_pages, max_records, timeout_seconds = _export_limits_from_payload(payload)
            validation_item_type = "EWO_O" if module == "ewo" else "PAA_O"
            auth = ArasPasswordAuthClient(
                lease.base_url,
                allow_insecure_http=lease.allow_insecure_http,
                timeout=min(30.0, timeout_seconds),
            )
            authenticated_session = lease.authenticated_session
            if authenticated_session is None:
                password = lease.reveal_password()
                if not password:
                    raise EphemeralTestSessionError(
                        "TEST_SESSION_EXPIRED", http_status=410
                    )
                login = auth.login(
                    lease.username,
                    password,
                    validation_item_type=validation_item_type,
                )
                authenticated_session = login.session
                try:
                    vault.promote_authenticated(
                        lease,
                        authenticated_session,
                        validated_module=module,
                    )
                except Exception:
                    close_authenticated_session(authenticated_session)
                    authenticated_session = None
                    raise
                password = ""
            elif not vault.module_is_validated(lease, module):
                auth.validate_authenticated_session(
                    authenticated_session, validation_item_type
                )
                vault.mark_validated(lease, module)

            client = ArasCrawlerClient(
                lease.base_url,
                session=authenticated_session,
                timeout=30.0,
                prewarm=False,
            )
            operation_payload = {"filters": dict(lease.filters)}
            if module == "ewo":
                result = client.export_ewo_report(
                    _ewo_filters_from_payload(operation_payload),
                    max_pages=max_pages,
                    max_records=max_records,
                    timeout_seconds=timeout_seconds,
                )
            else:
                result = client.export_paa_report(
                    _paa_filters_from_payload(operation_payload),
                    max_pages=max_pages,
                    max_records=max_records,
                    timeout_seconds=timeout_seconds,
                )
            destroyed = vault.finish_success(lease)
            response = _test_session_json(
                {
                    "ok": True,
                    "module": result.module,
                    "status": result.status,
                    "count": result.count,
                    "file_name": _safe_scalar(result.file_name),
                    "saved_path": _safe_scalar(result.saved_path),
                    "stop_reason": result.stop_reason,
                    "limit_reached": result.limit_reached,
                    "pages_fetched": result.pages_fetched,
                    "duplicates_removed": result.duplicates_removed,
                    "test_session_destroyed": destroyed,
                },
                clear_cookie=destroyed,
            )
            lease = None
            return response
        except EphemeralTestSessionError as error:
            destroyed = vault.finish_failure(
                lease, preserve_pre_touch_password=False
            ) if lease is not None else False
            lease = None
            return _test_session_error(
                error.code,
                error.http_status,
                clear_cookie=destroyed,
            )
        except ArasAuthError as error:
            destroyed = vault.finish_failure(
                lease,
                preserve_pre_touch_password=False,
            ) if lease is not None else False
            lease = None
            response, status = _json_auth_error(error, module=module)
            if destroyed:
                response.delete_cookie(
                    _TEST_SESSION_COOKIE,
                    path=_TEST_SESSION_COOKIE_PATH,
                    secure=False,
                    httponly=True,
                    samesite="Strict",
                )
            return response, status
        except (ArasReportExportError, ArasCrawlerError):
            destroyed = vault.finish_failure(
                lease, preserve_pre_touch_password=False
            ) if lease is not None else False
            lease = None
            return _test_session_error(
                "TEST_SESSION_EXPORT_FAILED", 502, clear_cookie=destroyed
            )
        except Exception:
            destroyed = vault.finish_failure(
                lease, preserve_pre_touch_password=False
            ) if lease is not None else False
            lease = None
            return _test_session_error(
                "TEST_SESSION_EXPORT_FAILED", 500, clear_cookie=destroyed
            )
        finally:
            password = ""
            if client is not None:
                client.headers.clear()

    def export_job_tokens() -> tuple[str, str, str]:
        return (
            str(request.headers.get(_EXPORT_JOB_ID_HEADER, "") or ""),
            str(request.cookies.get(_EXPORT_JOB_COOKIE, "") or ""),
            str(request.headers.get(_EXPORT_JOB_CSRF_HEADER, "") or ""),
        )

    def export_job_response(
        body: dict[str, Any],
        status: int = 200,
        *,
        sid: str | None = None,
        clear_cookie: bool = False,
    ):
        response = jsonify(body)
        response.status_code = status
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["Referrer-Policy"] = "no-referrer"
        if sid is not None:
            response.set_cookie(
                _EXPORT_JOB_COOKIE,
                sid,
                httponly=True,
                secure=False,
                samesite="Strict",
                path=_EXPORT_JOB_COOKIE_PATH,
            )
        if clear_cookie:
            response.delete_cookie(
                _EXPORT_JOB_COOKIE,
                path=_EXPORT_JOB_COOKIE_PATH,
                secure=False,
                httponly=True,
                samesite="Strict",
            )
        return response

    def run_export_job(job: _ExportJob, payload: dict[str, Any]) -> None:
        client: ArasCrawlerClient | None = None
        try:
            max_pages, max_records, timeout_seconds = _export_limits_from_payload(payload)
            module = job.module
            if module == "paa":
                payload["_validation_item_type"] = "PAA_O"
            client = _build_aras_client_from_payload(
                payload, cancel_event=job.cancel_event
            )
            export_jobs.attach_session(job, client.session)
            if job.cancel_requested:
                request_cancel = getattr(client.session, "request_cancel", None)
                if callable(request_cancel):
                    request_cancel()
            if module == "ewo":
                result = client.export_ewo_report(
                    _ewo_filters_from_payload(payload),
                    max_pages=max_pages,
                    max_records=max_records,
                    timeout_seconds=timeout_seconds,
                )
            else:
                result = client.export_paa_report(
                    _paa_filters_from_payload(payload),
                    max_pages=max_pages,
                    max_records=max_records,
                    timeout_seconds=timeout_seconds,
                )
            export_jobs.complete(
                job,
                {
                    "module": result.module,
                    "status": result.status,
                    "count": result.count,
                    "file_name": _safe_scalar(result.file_name),
                    "saved_path": _safe_scalar(result.saved_path),
                    "stop_reason": result.stop_reason,
                    "limit_reached": bool(result.limit_reached),
                    "pages_fetched": result.pages_fetched,
                    "duplicates_removed": result.duplicates_removed,
                },
            )
        except ArasAuthError as error:
            export_jobs.fail(job, _public_auth_error(error))
        except ArasReportExportError as error:
            code = (
                "AUTH_EXPORT_CANCELLED"
                if job.cancel_requested
                else error.code
                if error.code in _PUBLIC_EXPORT_ERROR_CODES
                else "EXPORT_FAILED"
            )
            export_jobs.fail(job, _fixed_export_error(code))
        except ArasCrawlerError:
            export_jobs.fail(
                job,
                _fixed_export_error(
                    "AUTH_EXPORT_CANCELLED"
                    if job.cancel_requested
                    else "UPSTREAM_REQUEST_FAILED"
                ),
            )
        except Exception:
            logger.warning("Aras export job failed: module=%s", job.module)
            export_jobs.fail(
                job,
                _fixed_export_error(
                    "AUTH_EXPORT_CANCELLED" if job.cancel_requested else "EXPORT_FAILED"
                ),
            )
        finally:
            _close_aras_client(client)

    @app.post("/api/aras/export-jobs")
    def api_aras_export_job_start():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return export_job_response(
                {
                    "ok": False,
                    "status": "failed",
                    "error": _fixed_export_error("INVALID_REQUEST"),
                },
                400,
            )
        password = ""
        try:
            module = str(payload.pop("module", "") or "").strip().casefold()
            allowed_keys = {
                "base_url",
                "username",
                "password",
                "allow_insecure_http",
                "headers",
                "cookie",
                "cookies",
                "filters",
                "limits",
                "max_pages",
                "max_records",
                "timeout_seconds",
            }
            username = str(payload.get("username") or "").strip()
            password = str(payload.get("password") or "")
            headers = _clean_string_mapping(payload.get("headers"))
            cookies = _clean_string_mapping(payload.get("cookies"))
            cookie = str(payload.get("cookie") or "").strip()
            if (
                module not in {"ewo", "paa"}
                or not set(payload).issubset(allowed_keys)
                or not str(payload.get("base_url") or "").strip()
                or not username
                or not password
                or headers
                or cookies
                or cookie
            ):
                return export_job_response(
                    {
                        "ok": False,
                        "module": module if module in {"ewo", "paa"} else "",
                        "status": "failed",
                        "error": _fixed_export_error("INVALID_REQUEST"),
                    },
                    400,
                )
            payload["username"] = username
            payload["password"] = password
            payload["headers"] = {}
            payload["cookies"] = {}
            payload["cookie"] = ""
            _export_limits_from_payload(payload)
            if module == "ewo":
                _ewo_filters_from_payload(payload)
            else:
                _paa_filters_from_payload(payload)
            job_payload = dict(payload)
            if isinstance(payload.get("filters"), dict):
                job_payload["filters"] = dict(payload["filters"])
            operation_id, sid, csrf = export_jobs.start(module, job_payload, run_export_job)
            return export_job_response(
                {
                    "ok": True,
                    "module": module,
                    "status": "running",
                    "operation_id": operation_id,
                    "csrf": csrf,
                },
                202,
                sid=sid,
            )
        except RuntimeError as error:
            code = str(error) if str(error) == "EXPORT_JOB_BUSY" else "EXPORT_JOB_NOT_FOUND"
            return export_job_response(
                {
                    "ok": False,
                    "status": "failed",
                    "error": _fixed_export_error(code),
                },
                409 if code == "EXPORT_JOB_BUSY" else 404,
            )
        except (ArasAuthError, ArasReportExportError):
            return export_job_response(
                {
                    "ok": False,
                    "status": "failed",
                    "error": _fixed_export_error("INVALID_REQUEST"),
                },
                400,
            )
        finally:
            password = ""
            if isinstance(payload, dict):
                if "password" in payload:
                    payload["password"] = ""
                payload.clear()

    @app.get("/api/aras/export-jobs/status")
    def api_aras_export_job_status():
        operation_id, sid, csrf = export_job_tokens()
        try:
            body = export_jobs.status(operation_id, sid, csrf)
            terminal = body.get("status") in {"completed", "partial", "failed", "cancelled"}
            return export_job_response(body, clear_cookie=terminal)
        except RuntimeError:
            return export_job_response(
                {
                    "ok": False,
                    "status": "failed",
                    "error": _fixed_export_error("EXPORT_JOB_NOT_FOUND"),
                },
                404,
                clear_cookie=True,
            )

    @app.post("/api/aras/export-jobs/cancel")
    def api_aras_export_job_cancel():
        operation_id, sid, csrf = export_job_tokens()
        try:
            status = export_jobs.cancel(operation_id, sid, csrf)
            return export_job_response(
                {"ok": True, "status": status},
            )
        except RuntimeError:
            return export_job_response(
                {
                    "ok": False,
                    "status": "failed",
                    "error": _fixed_export_error("EXPORT_JOB_NOT_FOUND"),
                },
                404,
                clear_cookie=True,
            )

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

    @app.post("/api/aras/ewo/query")
    def api_aras_ewo_query():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        client = None
        try:
            client = _build_aras_client_from_payload(payload)
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
        except ArasAuthError as e:
            return _json_auth_error(e)
        except ArasCrawlerError as e:
            return _json_error(502, "ArasCrawlerError", _sanitize_error_message(e))
        except Exception as e:
            logger.warning("Aras EWO API failed: %s", type(e).__name__)
            return _json_error(500, type(e).__name__, _sanitize_error_message(e))
        finally:
            _close_aras_client(client)

    @app.post("/api/aras/ewo/export")
    def api_aras_ewo_export():
        payload, error_response = _export_request_payload("ewo")
        if error_response:
            return error_response
        assert payload is not None
        client = None
        try:
            max_pages, max_records, timeout_seconds = _export_limits_from_payload(payload)
            client = _build_aras_client_from_payload(payload)
            result = client.export_ewo_report(
                _ewo_filters_from_payload(payload),
                max_pages=max_pages,
                max_records=max_records,
                timeout_seconds=timeout_seconds,
            )
            return jsonify(
                {
                    "ok": True,
                    "module": result.module,
                    "status": result.status,
                    "count": result.count,
                    "file_name": _safe_scalar(result.file_name),
                    "saved_path": _safe_scalar(result.saved_path),
                    "stop_reason": result.stop_reason,
                    "limit_reached": result.limit_reached,
                    "pages_fetched": result.pages_fetched,
                    "duplicates_removed": result.duplicates_removed,
                }
            )
        except ArasAuthError as e:
            return _json_auth_error(e, module="ewo")
        except ArasReportExportError as e:
            return _json_export_error("ewo", e.http_status, e.code, _sanitize_error_message(e))
        except Exception:
            logger.warning("Aras EWO export API failed")
            return _json_export_error(
                "ewo",
                500,
                "EXPORT_FAILED",
                "The EWO report export could not be completed.",
            )
        finally:
            _close_aras_client(client)

    @app.post("/api/aras/paa/query")
    def api_aras_paa_query():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        client = None
        try:
            payload["_validation_item_type"] = "PAA_O"
            client = _build_aras_client_from_payload(payload)
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
        except ArasAuthError as e:
            return _json_auth_error(e)
        except ArasCrawlerError as e:
            return _json_error(502, "ArasCrawlerError", _sanitize_error_message(e))
        except Exception as e:
            logger.warning("Aras PAA API failed: %s", type(e).__name__)
            return _json_error(500, type(e).__name__, _sanitize_error_message(e))
        finally:
            _close_aras_client(client)

    @app.post("/api/aras/paa/crawl-all")
    def api_aras_paa_crawl_all():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        client = None
        try:
            payload["_validation_item_type"] = "PAA_O"
            client = _build_aras_client_from_payload(payload)
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
        except ArasAuthError as e:
            return _json_auth_error(e)
        except ArasCrawlerError as e:
            return _json_error(502, "ArasCrawlerError", _sanitize_error_message(e))
        except Exception as e:
            logger.warning("Aras PAA crawl-all API failed: %s", type(e).__name__)
            return _json_error(500, type(e).__name__, _sanitize_error_message(e))
        finally:
            _close_aras_client(client)

    @app.post("/api/aras/paa/export")
    def api_aras_paa_export():
        payload, error_response = _export_request_payload("paa")
        if error_response:
            return error_response
        assert payload is not None
        client = None
        try:
            max_pages, max_records, timeout_seconds = _export_limits_from_payload(payload)
            payload["_validation_item_type"] = "PAA_O"
            client = _build_aras_client_from_payload(payload)
            result = client.export_paa_report(
                _paa_filters_from_payload(payload),
                max_pages=max_pages,
                max_records=max_records,
                timeout_seconds=timeout_seconds,
            )
            return jsonify(
                {
                    "ok": True,
                    "module": result.module,
                    "status": result.status,
                    "count": result.count,
                    "file_name": _safe_scalar(result.file_name),
                    "saved_path": _safe_scalar(result.saved_path),
                    "stop_reason": result.stop_reason,
                    "limit_reached": result.limit_reached,
                    "pages_fetched": result.pages_fetched,
                    "duplicates_removed": result.duplicates_removed,
                }
            )
        except ArasAuthError as e:
            return _json_auth_error(e, module="paa")
        except ArasReportExportError as e:
            return _json_export_error("paa", e.http_status, e.code, _sanitize_error_message(e))
        except Exception:
            logger.warning("Aras PAA export API failed")
            return _json_export_error(
                "paa",
                500,
                "EXPORT_FAILED",
                "The PAA report export could not be completed.",
            )
        finally:
            _close_aras_client(client)

    @app.post("/api/aras/ncr/progress")
    def api_aras_ncr_progress():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        client = None
        try:
            payload["_legacy_header_cookie_only"] = True
            client = _build_aras_client_from_payload(payload)
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
        except ArasAuthError as e:
            return _json_auth_error(e)
        except ArasCrawlerError as e:
            return _json_error(502, "ArasCrawlerError", _sanitize_error_message(e))
        except Exception as e:
            logger.warning("Aras NCR progress API failed: %s", type(e).__name__)
            return _json_error(500, type(e).__name__, _sanitize_error_message(e))
        finally:
            _close_aras_client(client)

    @app.post("/api/aras/ncr/detail")
    def api_aras_ncr_detail():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        client = None
        try:
            payload["_legacy_header_cookie_only"] = True
            client = _build_aras_client_from_payload(payload)
            result = client.extract_ncr_approval_detail(_ncr_filters_from_payload(payload))
            return jsonify({"ok": True, "data": {"file_name": _safe_scalar(result.file_name)}})
        except ArasAuthError as e:
            return _json_auth_error(e)
        except ArasCrawlerError as e:
            return _json_error(502, "ArasCrawlerError", _sanitize_error_message(e))
        except Exception as e:
            logger.warning("Aras NCR detail API failed: %s", type(e).__name__)
            return _json_error(500, type(e).__name__, _sanitize_error_message(e))
        finally:
            _close_aras_client(client)

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--ephemeral-test-session",
        action="store_true",
        help="Enable the loopback-only RAM test session for this process.",
    )
    arguments = parser.parse_args()
    app = create_app(
        enable_ephemeral_test_session=arguments.ephemeral_test_session
    )
    app.run(
        host=FLASK_HOST,
        port=FLASK_PORT,
        debug=False,
        use_reloader=False,
        processes=1,
        threaded=True,
    )
