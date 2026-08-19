# -*- coding: utf-8 -*-
"""TDC username/password authentication through the corporate OIDC flow."""

from __future__ import annotations

import base64
import json
import logging
import math
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from core.redaction import redact_sensitive_text
from services.tdc_crawler import (
    DEFAULT_TDC_BASE_URL,
    DEFAULT_TDC_USER_AGENT,
    TDCHttpDiagnosticEvent,
)

try:
    import requests
except ModuleNotFoundError:  # pragma: no cover - only for minimal environments
    requests = None  # type: ignore[assignment]


logger = logging.getLogger("vse_toolbox.tdc_auth")

DEFAULT_TDC_IDENTITY_ORIGIN = "https://account.sgmw.com.cn"
DEFAULT_TDC_OIDC_CLIENT_ID = "tpc-front"
DEFAULT_TDC_FORM_LOGIN_CLIENT = "pig:pig"
TDC_ENTRY_PATH = "/tpc/"
TDC_TOKEN_EXCHANGE_PATH = "/auth/oauth/token"
TDC_USER_INFO_PATH = "/uwf/user/info"
_TDC_TOKEN_BROWSER_HEADERS = {
    "Sec-CH-UA": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}
_ENTRY_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_MAX_ENTRY_REDIRECTS = 5
_OIDC_AUTH_SUFFIX = "/protocol/openid-connect/auth"
_OIDC_TOKEN_SUFFIX = "/protocol/openid-connect/token"
_OIDC_AUTH_PATH = "/auth/realms/common/protocol/openid-connect/auth"
_SAFE_HEADER_NAMES = {
    "accept",
    "accept-language",
    "content-type",
    "istoken",
    "origin",
    "referer",
    "sec-ch-ua",
    "sec-ch-ua-mobile",
    "sec-ch-ua-platform",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
    "user-agent",
}


class TDCAuthError(RuntimeError):
    """Raised when the TDC OIDC login cannot be completed safely."""

    def __init__(
        self,
        message: str,
        *,
        stage: str | None = None,
        request_id: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(redact_sensitive_text(message))
        self.stage = stage
        self.request_id = request_id
        self.status_code = status_code


@dataclass(frozen=True)
class TDCLoginResult:
    """Authenticated session without exposing credentials or token values."""

    session: Any = field(repr=False)
    token_expires_in: int | None = None
    auth_mode: str = "password"


@dataclass
class _LoginForm:
    action: str
    method: str
    fields: dict[str, str]


class _LoginFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[_LoginForm] = []
        self._current: _LoginForm | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(key).lower(): "" if value is None else str(value) for key, value in attrs}
        if tag.lower() == "form":
            self._current = _LoginForm(
                action=values.get("action", ""),
                method=values.get("method", "get").lower(),
                fields={},
            )
            return
        if tag.lower() != "input" or self._current is None:
            return
        name = values.get("name", "").strip()
        input_type = values.get("type", "text").lower()
        if name and input_type not in {"button", "submit", "reset", "image", "file"}:
            self._current.fields[name] = values.get("value", "")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "form" and self._current is not None:
            self.forms.append(self._current)
            self._current = None


@dataclass(frozen=True)
class _RequestTrace:
    stage: str
    request_id: str
    method: str
    url: str
    query: Mapping[str, str]
    headers: Mapping[str, str]
    response: Any
    elapsed_ms: float
    timeout: float


class TDCPasswordAuthClient:
    """Establish an authenticated TDC session using OIDC authorization code login."""

    def __init__(
        self,
        base_url: str = DEFAULT_TDC_BASE_URL,
        *,
        identity_origin: str = DEFAULT_TDC_IDENTITY_ORIGIN,
        oidc_client_id: str = DEFAULT_TDC_OIDC_CLIENT_ID,
        form_login_client: str = DEFAULT_TDC_FORM_LOGIN_CLIENT,
        session: Any | None = None,
        timeout: float = 30.0,
        diagnostic_hook: Callable[[TDCHttpDiagnosticEvent], None] | None = None,
        random_value_factory: Callable[[], str] | None = None,
        tdc_session_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.base_url = _normalize_https_origin(base_url, "base_url")
        self.identity_origin = _normalize_https_origin(identity_origin, "identity_origin")
        self.oidc_client_id = _validate_client_id(oidc_client_id)
        self.form_login_client = _validate_form_login_client(form_login_client)
        self.timeout = _validate_timeout(timeout)
        self._session_injected = session is not None
        if session is None:
            if requests is None:
                raise ImportError("TDCPasswordAuthClient requires requests; install requirements.txt")
            session = requests.Session()
            session.trust_env = False
        self.session = session
        self.diagnostic_hook = diagnostic_hook
        self.random_value_factory = random_value_factory or (lambda: uuid.uuid4().hex)
        self.tdc_session_factory = tdc_session_factory

    def login(self, username: str, password: str) -> TDCLoginResult:
        """Run the captured OIDC code flow and return the authenticated session."""
        username_value = str(username).strip()
        password_value = str(password)
        if not username_value:
            raise TDCAuthError("TDC username is required", stage="credential-validation")
        if not password_value:
            raise TDCAuthError("TDC password is required", stage="credential-validation")
        if any(ord(char) < 32 for char in username_value):
            raise TDCAuthError("TDC username contains control characters", stage="credential-validation")

        browser_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "User-Agent": DEFAULT_TDC_USER_AGENT,
        }
        expected_state = _validate_random_value(self.random_value_factory(), "OIDC state")
        nonce = _validate_random_value(self.random_value_factory(), "OIDC nonce")
        redirect_uri = self._url(TDC_ENTRY_PATH).rstrip("/")
        self._require_origin(redirect_uri, self.base_url, "OIDC redirect_uri")
        auth_url = urljoin(self.identity_origin, _OIDC_AUTH_PATH.lstrip("/"))
        auth_query = urlencode(
            {
                "client_id": self.oidc_client_id,
                "redirect_uri": redirect_uri,
                "response_mode": "fragment",
                "response_type": "code",
                "scope": "openid",
                "state": expected_state,
                "nonce": nonce,
            }
        )
        auth_url = f"{auth_url}?{auth_query}"
        discovery = self._request(
            "GET",
            auth_url,
            stage="auth-discovery",
            headers=browser_headers,
            allow_redirects=False,
        )
        self._require_status(discovery, {200})
        auth_parts = urlsplit(auth_url)

        form = _parse_login_form(_response_text(discovery.response))
        if form is None:
            self._reject(discovery, "login-form-missing", "TDC identity response does not contain a username/password form")
        if form.method != "post":
            self._reject(discovery, "login-form-method", "TDC identity login form must use POST")
        login_url = urljoin(auth_url, form.action)
        self._require_origin(login_url, self.identity_origin, "OIDC login form")
        payload = dict(form.fields)
        payload["username"] = username_value
        payload["password"] = password_value
        for optional_field in ("newokey", "eodpkey", "feishukey", "phoneNumber", "code", "credentialId"):
            payload.setdefault(optional_field, "")
        self._accept(discovery, validation="login-form-ready")

        identity_headers = {
            **browser_headers,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": self.identity_origin.rstrip("/"),
            "Referer": auth_url,
        }
        try:
            login_response = self._request(
                "POST",
                login_url,
                stage="auth-credentials",
                headers=identity_headers,
                data=payload,
                allow_redirects=False,
            )
        finally:
            # Drop references as soon as requests has encoded the body.
            payload["password"] = ""
            password_value = ""
        if int(getattr(login_response.response, "status_code", 0) or 0) not in {301, 302, 303, 307, 308}:
            self._reject(
                login_response,
                "credentials-rejected",
                "TDC username/password login failed or requires additional verification",
            )
        location = _header_value(getattr(login_response.response, "headers", {}), "Location")
        callback_url = urljoin(login_url, location)
        self._require_origin(callback_url, self.base_url, "OIDC login callback")
        callback_parts = urlsplit(callback_url)
        callback_values = parse_qs(callback_parts.fragment or callback_parts.query, keep_blank_values=True)
        authorization_code = _single_query_value(callback_values, "code")
        returned_state = _single_query_value(callback_values, "state")
        if not authorization_code or not expected_state or returned_state != expected_state:
            self._reject(login_response, "oidc-state-or-code", "OIDC callback state/code validation failed")
        self._accept(login_response, validation="authorization-code-received")
        entry_url = urlunsplit((callback_parts.scheme, callback_parts.netloc, callback_parts.path, "", ""))

        token_path = auth_parts.path[: -len(_OIDC_AUTH_SUFFIX)] + _OIDC_TOKEN_SUFFIX
        oidc_token_url = urlunsplit((auth_parts.scheme, auth_parts.netloc, token_path, "", ""))
        token_form = {
            "client_id": self.oidc_client_id,
            "code": authorization_code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        try:
            oidc_token = self._request(
                "POST",
                oidc_token_url,
                stage="oidc-token",
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": self.base_url.rstrip("/"),
                    "Referer": self._url(TDC_ENTRY_PATH),
                    "User-Agent": DEFAULT_TDC_USER_AGENT,
                },
                data=token_form,
                allow_redirects=False,
            )
        finally:
            token_form["code"] = ""
            authorization_code = ""
        oidc_payload = self._json_response(oidc_token)
        identity_access_token = oidc_payload.get("access_token")
        if not isinstance(identity_access_token, str) or not identity_access_token:
            self._reject(oidc_token, "oidc-token-missing", "OIDC response does not contain an access token")
        self._accept(oidc_token, validation="oidc-token-received", json_fields=tuple(sorted(oidc_payload)))

        native_session_created = False
        previous_session: Any = None
        if not self._session_injected and (self.tdc_session_factory is not None or sys.platform == "win32"):
            factory = self.tdc_session_factory or _new_native_tdc_session
            try:
                previous_session = self.session
                self.session = factory()
                native_session_created = True
            except Exception as exc:
                raise TDCAuthError(
                    f"TDC native session creation failed: {type(exc).__name__}",
                    stage="tdc-session-init",
                ) from exc

        if native_session_created:
            self._migrate_cookies(previous_session, entry_url)
            self._prewarm_entry(entry_url, browser_headers)

        basic_authorization = _basic_authorization(self.form_login_client)
        try:
            tdc_exchange = self._request(
                "POST",
                self._url(TDC_TOKEN_EXCHANGE_PATH),
                stage="tdc-token",
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Origin": self.base_url.rstrip("/"),
                    "Referer": self._url(TDC_ENTRY_PATH),
                    "User-Agent": DEFAULT_TDC_USER_AGENT,
                    "isToken": "false",
                    "Authorization": basic_authorization,
                    **_TDC_TOKEN_BROWSER_HEADERS,
                },
                params={"token": identity_access_token},
                allow_redirects=False,
            )
        finally:
            identity_access_token = ""
            basic_authorization = ""
        tdc_payload = self._json_response(tdc_exchange)
        if tdc_payload.get("code") not in (0, "0") or not isinstance(tdc_payload.get("data"), Mapping):
            self._reject(tdc_exchange, "tdc-token-rejected", "TDC rejected the identity token exchange")
        tdc_data = tdc_payload["data"]
        access_token = tdc_data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            self._reject(tdc_exchange, "tdc-token-missing", "TDC token exchange did not establish a session")
        token_type = _safe_token_type(tdc_data.get("token_type"))
        expires_in = _optional_positive_int(tdc_data.get("expires_in"))
        self._accept(tdc_exchange, validation="tdc-session-established", json_fields=tuple(sorted(tdc_payload)))
        try:
            self.session.headers["Authorization"] = f"{token_type} {access_token}"
        finally:
            access_token = ""
            tdc_data = {}
            tdc_payload = {}

        try:
            verification = self._request(
                "GET",
                self._url(TDC_USER_INFO_PATH),
                stage="auth-verify",
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Referer": self._url(TDC_ENTRY_PATH),
                    "User-Agent": DEFAULT_TDC_USER_AGENT,
                },
                allow_redirects=False,
            )
            verification_payload = self._json_response(verification)
            if verification_payload.get("code") not in (0, "0") or verification_payload.get("data") is None:
                self._reject(verification, "session-verification-failed", "TDC session verification failed")
            self._accept(
                verification,
                validation="authenticated",
                json_fields=tuple(sorted(verification_payload)),
            )
        except TDCAuthError:
            self.session.headers.pop("Authorization", None)
            raise
        return TDCLoginResult(session=self.session, token_expires_in=expires_in)

    def _prewarm_entry(self, entry_url: str, browser_headers: Mapping[str, str]) -> None:
        current_url = entry_url
        trace: _RequestTrace | None = None
        validation = "entry-observed"
        for redirect_count in range(_MAX_ENTRY_REDIRECTS + 1):
            trace = self._request(
                "GET",
                current_url,
                stage="tdc-entry",
                headers=browser_headers,
                allow_redirects=False,
            )
            status = int(getattr(trace.response, "status_code", 0) or 0)
            if status not in _ENTRY_REDIRECT_STATUSES:
                validation = "entry-observed" if 200 <= status < 300 else "entry-http-observed"
                break
            location = _header_value(getattr(trace.response, "headers", {}), "Location")
            redirect_parts = urlsplit(urljoin(current_url, location))
            redirect_url = urlunsplit(
                (
                    redirect_parts.scheme,
                    redirect_parts.netloc,
                    redirect_parts.path,
                    redirect_parts.query,
                    "",
                )
            )
            if not location or not self._is_trusted_entry_redirect(redirect_url):
                validation = "entry-redirect-not-followed"
                break
            if redirect_count == _MAX_ENTRY_REDIRECTS:
                validation = "entry-redirect-limit"
                break
            current_url = redirect_url
        if trace is not None:
            self._accept(trace, validation=validation)

    def _migrate_cookies(self, previous_session: Any, entry_url: str) -> None:
        """Migrate RFC-eligible cookies from the OIDC session to the native one.

        Only runs when the flow switched from a ``requests.Session`` to a newly
        created native session. Cookie names and values are never surfaced: the
        diagnostic event carries only the migrated count, whether the migration
        ran, and the elapsed time. A count of 0 is a valid experimental result
        and never raises; a migration failure is logged generically and the
        login flow continues unchanged.
        """
        importer = getattr(self.session, "import_cookies", None)
        source_jar = getattr(previous_session, "cookies", previous_session)
        started = time.perf_counter()
        migrated = 0
        performed = False
        if callable(importer):
            try:
                migrated = importer(source_jar, entry_url)
                performed = True
            except Exception as exc:  # experiment; must never break authentication
                logger.warning("TDC cookie migration failed: %s", type(exc).__name__)
                migrated = 0
                performed = False
        elapsed_ms = (time.perf_counter() - started) * 1000
        self._emit(
            self._cookie_migration_event(entry_url, performed, migrated, elapsed_ms)
        )

    def _cookie_migration_event(
        self, entry_url: str, performed: bool, migrated: int, elapsed_ms: float
    ) -> TDCHttpDiagnosticEvent:
        parts = urlsplit(entry_url)
        validation = "cookie-migration-performed" if performed else "cookie-migration-skipped"
        return TDCHttpDiagnosticEvent(
            timestamp=datetime.now().isoformat(timespec="milliseconds"),
            stage="tdc-cookie-migration",
            request_id=uuid.uuid4().hex[:8],
            page_type="authentication",
            origin=f"{parts.scheme}://{parts.netloc}",
            path=parts.path,
            validation=validation,
            record_count=migrated,
            elapsed_ms=elapsed_ms,
        )

    def _is_trusted_entry_redirect(self, value: str) -> bool:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            return False
        origin = f"https://{parsed.netloc}/".lower()
        return origin in {self.base_url.lower(), self.identity_origin.lower()}

    def _request(
        self,
        method: str,
        url: str,
        *,
        stage: str,
        headers: Mapping[str, str],
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        allow_redirects: bool,
    ) -> _RequestTrace:
        request_id = uuid.uuid4().hex[:8]
        started = time.perf_counter()
        request_headers = {**getattr(self.session, "headers", {}), **dict(headers)}
        try:
            request_method = getattr(self.session, method.lower())
            response = request_method(
                url,
                params=dict(params or {}),
                data=None if data is None else dict(data),
                headers=dict(headers),
                timeout=self.timeout,
                allow_redirects=allow_redirects,
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000
            self._emit(
                _auth_event(
                    stage=stage,
                    request_id=request_id,
                    method=method,
                    url=url,
                    query=_safe_auth_query(params, url),
                    headers=request_headers,
                    timeout=self.timeout,
                    elapsed_ms=elapsed,
                    exception_type=type(exc).__name__,
                    reason=f"authentication request failed: {type(exc).__name__}",
                )
            )
            raise TDCAuthError(
                f"TDC authentication request failed during {stage}: {type(exc).__name__}",
                stage=stage,
                request_id=request_id,
            ) from exc
        return _RequestTrace(
            stage=stage,
            request_id=request_id,
            method=method,
            url=url,
            query=_safe_auth_query(params, url),
            headers=request_headers,
            response=response,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            timeout=self.timeout,
        )

    def _json_response(self, trace: _RequestTrace) -> dict[str, Any]:
        self._require_status(trace, set(range(200, 300)))
        content_type = _header_value(getattr(trace.response, "headers", {}), "Content-Type")
        if "json" not in content_type.lower():
            self._reject(trace, "rejected-content-type", "TDC authentication endpoint did not return JSON")
        try:
            loader = getattr(trace.response, "json", None)
            payload = loader() if callable(loader) else json.loads(_response_text(trace.response))
        except Exception as exc:
            self._reject(
                trace,
                "invalid-json",
                "TDC authentication endpoint returned invalid JSON",
                exception_type=type(exc).__name__,
            )
        if not isinstance(payload, dict):
            self._reject(trace, "json-not-object", "TDC authentication JSON is not an object")
        return payload

    def _require_status(self, trace: _RequestTrace, allowed: set[int]) -> None:
        status = int(getattr(trace.response, "status_code", 0) or 0)
        if status not in allowed:
            detail, json_fields = _safe_error_detail(trace.response)
            message = f"TDC authentication HTTP {status}"
            if detail:
                message = f"{message}: {detail}"
            self._reject(trace, "rejected-status", message, json_fields=json_fields)

    def _require_origin(self, value: str, expected_origin: str, label: str) -> None:
        parsed = urlsplit(str(value))
        actual = f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else ""
        if actual != expected_origin:
            raise TDCAuthError(f"{label} origin is not trusted", stage="origin-validation")

    def _accept(
        self,
        trace: _RequestTrace,
        *,
        validation: str,
        json_fields: tuple[str, ...] = (),
    ) -> None:
        self._emit(_event_from_trace(trace, validation=validation, json_fields=json_fields))

    def _reject(
        self,
        trace: _RequestTrace,
        validation: str,
        message: str,
        *,
        exception_type: str | None = None,
        json_fields: tuple[str, ...] = (),
    ) -> None:
        status = int(getattr(trace.response, "status_code", 0) or 0)
        self._emit(
            _event_from_trace(
                trace,
                validation=validation,
                exception_type=exception_type,
                reason=message,
                json_fields=json_fields,
            )
        )
        raise TDCAuthError(message, stage=trace.stage, request_id=trace.request_id, status_code=status)

    def _url(self, path: str) -> str:
        return urljoin(self.base_url, path.lstrip("/"))

    def _emit(self, event: TDCHttpDiagnosticEvent) -> None:
        logger.debug(
            "stage=%s request_id=%s path=%s status=%s validation=%s type=%s",
            event.stage,
            event.request_id,
            event.path,
            event.status_code,
            event.validation,
            event.exception_type,
        )
        if self.diagnostic_hook is None:
            return
        try:
            self.diagnostic_hook(event)
        except Exception as exc:  # diagnostics must never break authentication
            logger.warning("TDC auth diagnostic hook failed: %s", type(exc).__name__)


def _parse_login_form(html: str) -> _LoginForm | None:
    parser = _LoginFormParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return None
    for form in parser.forms:
        lowered = {name.lower() for name in form.fields}
        if "username" in lowered and "password" in lowered and form.action:
            return form
    return None


def _new_native_tdc_session() -> Any:
    from services.windows_http import WinHTTPSession

    return WinHTTPSession()


def _event_from_trace(
    trace: _RequestTrace,
    *,
    validation: str,
    json_fields: tuple[str, ...] = (),
    exception_type: str | None = None,
    reason: str | None = None,
) -> TDCHttpDiagnosticEvent:
    response = trace.response
    return _auth_event(
        stage=trace.stage,
        request_id=trace.request_id,
        method=trace.method,
        url=trace.url,
        query=trace.query,
        headers=trace.headers,
        timeout=trace.timeout,
        elapsed_ms=trace.elapsed_ms,
        status_code=int(getattr(response, "status_code", 0) or 0),
        response_headers=getattr(response, "headers", {}),
        json_fields=json_fields,
        validation=validation,
        exception_type=exception_type,
        reason=reason,
    )


def _auth_event(
    *,
    stage: str,
    request_id: str,
    method: str,
    url: str,
    query: Mapping[str, str],
    headers: Mapping[str, str],
    timeout: float | None,
    elapsed_ms: float,
    status_code: int | None = None,
    response_headers: Mapping[str, Any] | None = None,
    json_fields: tuple[str, ...] = (),
    validation: str | None = None,
    exception_type: str | None = None,
    reason: str | None = None,
) -> TDCHttpDiagnosticEvent:
    parts = urlsplit(url)
    return TDCHttpDiagnosticEvent(
        timestamp=datetime.now().isoformat(timespec="milliseconds"),
        stage=stage,
        request_id=request_id,
        page_type="authentication",
        method=method,
        origin=f"{parts.scheme}://{parts.netloc}",
        path=parts.path,
        query=dict(query),
        attempt=1,
        timeout=timeout,
        status_code=status_code,
        elapsed_ms=elapsed_ms,
        content_type=_header_value(response_headers or {}, "Content-Type"),
        content_length=_content_length(response_headers or {}),
        json_fields=json_fields,
        request_headers=_safe_auth_headers(headers),
        response_headers=_safe_auth_headers(response_headers or {}),
        validation=validation,
        exception_type=exception_type,
        reason=redact_sensitive_text(reason or "", limit=240, collapse_newlines=True) or None,
    )


def _safe_auth_query(params: Mapping[str, Any] | None, url: str) -> dict[str, str]:
    keys = set(str(key) for key in (params or {}))
    keys.update(parse_qs(urlsplit(url).query, keep_blank_values=True))
    return {key: "[redacted]" for key in sorted(keys)}


def _safe_auth_headers(headers: Mapping[str, Any]) -> dict[str, str]:
    safe: dict[str, str] = {}
    for key, value in headers.items():
        lowered = str(key).lower()
        if lowered in {"authorization", "cookie", "set-cookie"}:
            safe[str(key)] = "[redacted]"
        elif lowered in _SAFE_HEADER_NAMES:
            shown = _without_url_query(str(value)) if lowered in {"origin", "referer"} else value
            safe[str(key)] = redact_sensitive_text(shown, limit=500, collapse_newlines=True)
    return safe


def _single_query_value(values: Mapping[str, list[str]], name: str) -> str:
    items = values.get(name, [])
    return str(items[0]) if len(items) == 1 else ""


def _without_url_query(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return value.split("?", 1)[0].split("#", 1)[0]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _response_text(response: Any) -> str:
    text = getattr(response, "text", "")
    if isinstance(text, str):
        return text
    content = getattr(response, "content", b"")
    return content.decode("utf-8", errors="replace") if isinstance(content, bytes) else ""


_SAFE_ERROR_FIELDS = ("error", "error_description", "code", "message", "msg")


def _safe_error_detail(response: Any) -> tuple[str, tuple[str, ...]]:
    content_type = _header_value(getattr(response, "headers", {}), "Content-Type")
    if "json" not in content_type.lower():
        return "", ()
    try:
        loader = getattr(response, "json", None)
        payload = loader() if callable(loader) else json.loads(_response_text(response))
    except Exception:
        return "", ()
    if not isinstance(payload, Mapping):
        return "", ()
    parts: list[str] = []
    for name in _SAFE_ERROR_FIELDS:
        value = payload.get(name)
        if value is None or isinstance(value, (Mapping, list, tuple, set)):
            continue
        shown = redact_sensitive_text(value, limit=160, collapse_newlines=True)
        if shown:
            parts.append(f"{name}={shown}")
    fields = tuple(sorted(name for name in _SAFE_ERROR_FIELDS if name in payload))
    return "; ".join(parts)[:480], fields


def _header_value(headers: Mapping[str, Any], name: str) -> str:
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            return str(value)
    return ""


def _content_length(headers: Mapping[str, Any]) -> int | None:
    value = _header_value(headers, "Content-Length")
    try:
        return int(value) if value else None
    except ValueError:
        return None


def _normalize_https_origin(value: str, label: str) -> str:
    parsed = urlsplit(str(value).strip())
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError(f"{label} must be an absolute HTTPS origin")
    return f"https://{parsed.netloc}/"


def _validate_client_id(value: str) -> str:
    client_id = str(value).strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", client_id):
        raise ValueError("oidc_client_id is invalid")
    return client_id


def _validate_random_value(value: str, label: str) -> str:
    text = str(value)
    if not re.fullmatch(r"[A-Za-z0-9._~-]{16,256}", text):
        raise TDCAuthError(f"{label} generation failed", stage="oidc-parameter-generation")
    return text


def _validate_timeout(value: float) -> float:
    if isinstance(value, bool):
        raise ValueError("timeout must be positive")
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout must be positive") from exc
    if not math.isfinite(timeout) or timeout <= 0 or timeout > 600:
        raise ValueError("timeout must be between 0 and 600 seconds")
    return timeout


def _validate_form_login_client(value: str) -> str:
    client = str(value)
    if (
        not client
        or len(client) > 256
        or ":" not in client
        or any(ord(char) < 32 or ord(char) > 126 for char in client)
    ):
        raise ValueError("form_login_client must be a printable ASCII client credential")
    return client


def _basic_authorization(client: str) -> str:
    encoded = base64.b64encode(client.encode("ascii")).decode("ascii")
    return f"Basic {encoded}"


def _safe_token_type(value: Any) -> str:
    token_type = str(value or "Bearer").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9._~-]{0,31}", token_type):
        return "Bearer"
    return token_type


def _optional_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
