# -*- coding: utf-8 -*-
"""ECM (Aras) username/password authentication through the corporate OIDC flow.

The chain mirrors what the deployed Innovator client does when a user signs in
to ECM with an account password, as captured in the bundled crawl source
(`crawl source/SGMW工程变更审批-NCR_files/include(3).aspx`, which contains the
Aras ``soap_object.js`` / ``OAuthClient`` sources):

1. OIDC authorization-code request to ``https://account.sgmw.com.cn``
   (realm ``common``, client ``ecm-front``, redirect
   ``http://ecm.sgmw.com.cn/innovatorserver/client/redirect.html``).
2. The identity server answers with the dynamic login form; the form action
   must stay on the HTTPS ``account.sgmw.com.cn`` origin. The username and
   password are posted exactly as entered (no MD5/SHA transform).
3. The callback URL (exact host/path), the random state and the code are
   validated before the code is exchanged at the OIDC token endpoint
   (discovered via ``.well-known/openid-configuration`` where possible).
4. The access token is placed only in the in-memory ``requests.Session``
   ``Authorization`` header.
5. The session is only returned after the Aras SOAP ``ValidateUser`` call
   succeeds. Derived from the bundled client: ``ValidateUser`` is posted to
   ``Server/InnovatorServer.aspx`` with an empty SOAP body plus
   ``TIMEZONE_NAME`` and the OAuth ``Authorization`` header
   (``getAuthorizationHeader()``), and the response must contain
   ``Result/id`` (``HttpServerConnection.Login`` selects ``//Result/id`` and
   fails closed without it).

Passwords, tokens, cookies and authorization codes are never written to
config, logs, diagnostics, exceptions, reprs, fixtures, or the public login
result.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from core.redaction import redact_sensitive_text
from services.aras_crawler import (
    DEFAULT_BROWSER_USER_AGENT,
    _normalize_aras_app_root,
)

try:
    import requests
except ModuleNotFoundError:  # pragma: no cover - only for minimal environments
    requests = None  # type: ignore[assignment]

logger = logging.getLogger("vse_toolbox.aras_auth")

DEFAULT_ARAS_BASE_URL = "http://ecm.sgmw.com.cn/innovatorserver"
DEFAULT_ECM_IDENTITY_ORIGIN = "https://account.sgmw.com.cn"
DEFAULT_ECM_OIDC_CLIENT_ID = "ecm-front"
ECM_OIDC_REALM = "common"
ECM_REDIRECT_URI = "http://ecm.sgmw.com.cn/innovatorserver/client/redirect.html"
_OIDC_AUTH_SUFFIX = "/protocol/openid-connect/auth"
_OIDC_TOKEN_SUFFIX = "/protocol/openid-connect/token"
_OIDC_METADATA_PATH = f"/auth/realms/{ECM_OIDC_REALM}/.well-known/openid-configuration"
ECM_OIDC_AUTH_PATH = f"/auth/realms/{ECM_OIDC_REALM}/protocol/openid-connect/auth"
SOAP_ROUTE = "Server/InnovatorServer.aspx"
SOAP_ACTION_VALIDATE_USER = "ValidateUser"
TIMEZONE_NAME = "China Standard Time"
_SAFE_HEADER_NAMES = {
    "accept",
    "accept-language",
    "content-type",
    "origin",
    "referer",
    "soapaction",
    "timezone_name",
    "user-agent",
}
_EMPTY_SOAP_BODY = (
    '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" >'
    "<SOAP-ENV:Body></SOAP-ENV:Body></SOAP-ENV:Envelope>"
)
_LOGIN_PAGE_MARKERS = (
    'type="password"',
    "type='password'",
    "kc-form-login",
    "login-form",
    "loginform",
)
_CHALLENGE_MARKERS = (
    "captcha",
    "验证码",
    "滑块",
    "安全验证",
    "otp",
    "one-time",
    "mfa",
    "two-factor",
    "扫码",
)


class ArasAuthError(RuntimeError):
    """Raised when the ECM OIDC login cannot be completed safely."""

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
class ArasLoginResult:
    """Authenticated ECM session without exposing credentials or token values."""

    session: Any = field(repr=False)
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
class ArasAuthHttpDiagnosticEvent:
    """Redacted diagnostic trace for one ECM authentication HTTP step.

    Never carries passwords, tokens, codes or cookies: request/response
    bodies are omitted and header/query values are scrubbed at construction.
    """

    timestamp: str
    stage: str
    request_id: str
    method: str
    url: str
    path: str
    query: Mapping[str, str]
    timeout: float | None
    status_code: int | None
    elapsed_ms: float
    request_headers: Mapping[str, str]
    response_headers: Mapping[str, str]
    json_fields: tuple[str, ...]
    validation: str | None
    exception_type: str | None
    reason: str | None


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


class ArasECMAuthClient:
    """Establish an authenticated ECM session using the OIDC authorization-code flow."""

    def __init__(
        self,
        base_url: str = DEFAULT_ARAS_BASE_URL,
        *,
        identity_origin: str = DEFAULT_ECM_IDENTITY_ORIGIN,
        oidc_client_id: str = DEFAULT_ECM_OIDC_CLIENT_ID,
        redirect_uri: str = ECM_REDIRECT_URI,
        session: Any | None = None,
        timeout: float = 30.0,
        diagnostic_hook: Callable[[ArasAuthHttpDiagnosticEvent], None] | None = None,
        random_value_factory: Callable[[], str] | None = None,
    ) -> None:
        self.base_url = _normalize_aras_app_root(base_url)
        if not urlsplit(self.base_url).scheme or not urlsplit(self.base_url).netloc:
            raise ValueError("base_url must be an absolute http(s) URL")
        self.identity_origin = _normalize_https_origin(identity_origin, "identity_origin")
        self.oidc_client_id = _validate_client_id(oidc_client_id)
        self.redirect_uri = _validate_redirect_uri(redirect_uri)
        self.timeout = _validate_timeout(timeout)
        if session is None:
            if requests is None:
                raise ImportError("ArasECMAuthClient requires requests; install requirements.txt")
            session = requests.Session()
            session.trust_env = False
        self.session = session
        self.diagnostic_hook = diagnostic_hook
        self.random_value_factory = random_value_factory or (lambda: uuid.uuid4().hex)

    def login(self, username: str, password: str) -> ArasLoginResult:
        """Run the OIDC code flow, gate on Aras SOAP ValidateUser, return the session."""
        username_value = str(username).strip()
        password_value = str(password)
        if not username_value:
            raise ArasAuthError("ECM username is required", stage="credential-validation")
        if not password_value:
            raise ArasAuthError("ECM password is required", stage="credential-validation")
        if any(ord(char) < 32 for char in username_value):
            raise ArasAuthError("ECM username contains control characters", stage="credential-validation")

        browser_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "User-Agent": DEFAULT_BROWSER_USER_AGENT,
        }
        expected_state = _validate_random_value(self.random_value_factory(), "OIDC state")
        auth_url = urljoin(self.identity_origin, ECM_OIDC_AUTH_PATH.lstrip("/"))
        auth_query = urlencode(
            {
                "client_id": self.oidc_client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": "openid",
                "state": expected_state,
            }
        )
        auth_url = f"{auth_url}?{auth_query}"

        discovery = self._request(
            "GET",
            auth_url,
            stage="ecm-auth-discovery",
            headers=browser_headers,
            allow_redirects=False,
        )
        self._require_status(discovery, {200})
        auth_parts = urlsplit(auth_url)

        form = _parse_login_form(_response_text(discovery.response))
        if form is None:
            self._reject(discovery, "login-form-missing", "ECM identity response does not contain a username/password form")
        if form.method != "post":
            self._reject(discovery, "login-form-method", "ECM identity login form must use POST")
        login_url = urljoin(auth_url, form.action)
        self._require_origin(login_url, self.identity_origin, "ECM login form")
        payload = dict(form.fields)
        payload["username"] = username_value
        payload["password"] = password_value
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
                stage="ecm-credentials",
                headers=identity_headers,
                data=payload,
                allow_redirects=False,
            )
        finally:
            # Drop references as soon as requests has encoded the body.
            payload["password"] = ""
            password_value = ""
        login_status = int(getattr(login_response.response, "status_code", 0) or 0)
        if login_status in {301, 302, 303, 307, 308}:
            self._accept(login_response, validation="credentials-redirect")
        else:
            login_body = _response_text(login_response.response).lower()
            if _has_challenge(login_body):
                self._reject(
                    login_response,
                    "challenge-required",
                    "ECM login requires CAPTCHA/MFA/OTP verification that this tool cannot complete",
                )
            if _is_login_page(login_body):
                self._reject(
                    login_response,
                    "credentials-rejected",
                    "ECM username/password login failed or requires additional verification",
                )
            self._reject(
                login_response,
                "credentials-rejected",
                "ECM username/password login failed or requires additional verification",
            )
        location = _header_value(getattr(login_response.response, "headers", {}), "Location")
        callback_url = urljoin(login_url, location)
        self._require_callback(callback_url)
        callback_parts = urlsplit(callback_url)
        callback_values = parse_qs(callback_parts.query or callback_parts.fragment, keep_blank_values=True)
        authorization_code = _single_query_value(callback_values, "code")
        returned_state = _single_query_value(callback_values, "state")
        if not authorization_code or not expected_state or returned_state != expected_state:
            self._reject(login_response, "oidc-state-or-code", "ECM OIDC callback state/code validation failed")
        self._accept(login_response, validation="authorization-code-received")

        token_url = self._discover_token_endpoint(auth_parts)
        token_form = {
            "client_id": self.oidc_client_id,
            "code": authorization_code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
        }
        try:
            oidc_token = self._request(
                "POST",
                token_url,
                stage="ecm-token",
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": urlsplit(self.redirect_uri).scheme + "://" + urlsplit(self.redirect_uri).netloc,
                    "Referer": self.redirect_uri,
                    "User-Agent": DEFAULT_BROWSER_USER_AGENT,
                },
                data=token_form,
                allow_redirects=False,
            )
        finally:
            token_form["code"] = ""
            authorization_code = ""
        oidc_payload = self._json_response(oidc_token)
        access_token = oidc_payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            self._reject(oidc_token, "oidc-token-missing", "ECM OIDC response does not contain an access token")
        token_type = str(oidc_payload.get("token_type") or "Bearer").strip() or "Bearer"
        self._accept(oidc_token, validation="oidc-token-received", json_fields=tuple(sorted(oidc_payload)))
        # The token lives only in this in-memory session; never persist or log it.
        self.session.headers["Authorization"] = f"{token_type} {access_token}"
        access_token = ""

        try:
            self._validate_user()
        except ArasAuthError:
            self.session.headers.pop("Authorization", None)
            raise
        return ArasLoginResult(session=self.session)

    def _validate_user(self) -> None:
        """Gate the session on the Aras SOAP ValidateUser call (bundled client shape)."""
        soap_url = urljoin(self.base_url, SOAP_ROUTE.lstrip("/"))
        validate_headers = {
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Content-Type": "text/xml; charset=UTF-8",
            "Origin": _origin(self.base_url),
            "Referer": urljoin(self.base_url, "Client/default.aspx"),
            "SOAPAction": SOAP_ACTION_VALIDATE_USER,
            "TIMEZONE_NAME": TIMEZONE_NAME,
            "User-Agent": DEFAULT_BROWSER_USER_AGENT,
        }
        trace = self._request(
            "POST",
            soap_url,
            stage="ecm-validate-user",
            headers=validate_headers,
            data=_EMPTY_SOAP_BODY,
            allow_redirects=False,
        )
        status = int(getattr(trace.response, "status_code", 0) or 0)
        if status not in set(range(200, 300)):
            self._reject(
                trace,
                "validate-user-rejected",
                f"ECM Aras ValidateUser returned HTTP {status}; the OAuth session was rejected by the ECM server",
            )
        body = _response_text(trace.response)
        if _is_login_page(body.lower()):
            self._reject(
                trace,
                "validate-user-login-page",
                "ECM Aras ValidateUser returned a login page; the OAuth session was not accepted",
            )
        if not _validate_user_response_has_id(body):
            self._reject(
                trace,
                "validate-user-no-user",
                (
                    "ECM Aras ValidateUser did not return a valid user record; the ECM account may lack "
                    "Aras access, or this deployment differs from the verified login chain"
                ),
            )
        self._accept(trace, validation="authenticated")

    def _discover_token_endpoint(self, auth_parts) -> str:  # type: ignore[no-untyped-def]
        """Prefer the OIDC metadata token_endpoint; fall back to the derived path."""
        metadata_url = urljoin(self.identity_origin, _OIDC_METADATA_PATH.lstrip("/"))
        try:
            metadata = self._request(
                "GET",
                metadata_url,
                stage="ecm-oidc-discovery",
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "User-Agent": DEFAULT_BROWSER_USER_AGENT,
                },
                allow_redirects=False,
            )
        except ArasAuthError:
            metadata = None
        if metadata is not None:
            status = int(getattr(metadata.response, "status_code", 0) or 0)
            if status in set(range(200, 300)):
                try:
                    payload = metadata.response.json() if callable(getattr(metadata.response, "json", None)) else {}
                except Exception:
                    payload = {}
                token_endpoint = payload.get("token_endpoint") if isinstance(payload, dict) else None
                if isinstance(token_endpoint, str) and token_endpoint:
                    self._require_origin(token_endpoint, self.identity_origin, "ECM OIDC token endpoint")
                    self._accept(metadata, validation="oidc-metadata-received")
                    return token_endpoint
        # Deterministic fallback: same authority, token path next to the auth path.
        fallback = urlunsplit(
            (
                auth_parts.scheme,
                auth_parts.netloc,
                auth_parts.path[: -len(_OIDC_AUTH_SUFFIX)] + _OIDC_TOKEN_SUFFIX,
                "",
                "",
            )
        )
        if metadata is not None:
            self._accept(metadata, validation="oidc-metadata-fallback")
        return fallback

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
        try:
            request_method = getattr(self.session, method.lower())
            response = request_method(
                url,
                params=dict(params or {}),
                data=dict(data) if isinstance(data, Mapping) else data,
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
                    headers=headers,
                    timeout=self.timeout,
                    elapsed_ms=elapsed,
                    exception_type=type(exc).__name__,
                    reason=f"authentication request failed: {type(exc).__name__}",
                )
            )
            raise ArasAuthError(
                f"ECM authentication request failed during {stage}: {type(exc).__name__}",
                stage=stage,
                request_id=request_id,
            ) from exc
        return _RequestTrace(
            stage=stage,
            request_id=request_id,
            method=method,
            url=url,
            query=_safe_auth_query(params, url),
            headers=dict(headers),
            response=response,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            timeout=self.timeout,
        )

    def _json_response(self, trace: _RequestTrace) -> dict[str, Any]:
        self._require_status(trace, set(range(200, 300)))
        content_type = _header_value(getattr(trace.response, "headers", {}), "Content-Type")
        if "json" not in content_type.lower():
            self._reject(trace, "rejected-content-type", "ECM authentication endpoint did not return JSON")
        try:
            loader = getattr(trace.response, "json", None)
            payload = loader() if callable(loader) else json.loads(_response_text(trace.response))
        except Exception as exc:
            self._reject(
                trace,
                "invalid-json",
                "ECM authentication endpoint returned invalid JSON",
                exception_type=type(exc).__name__,
            )
        if not isinstance(payload, dict):
            self._reject(trace, "json-not-object", "ECM authentication JSON is not an object")
        return payload

    def _require_status(self, trace: _RequestTrace, allowed: set[int]) -> None:
        status = int(getattr(trace.response, "status_code", 0) or 0)
        if status not in allowed:
            self._reject(trace, "rejected-status", f"ECM authentication HTTP {status}")

    def _require_origin(self, value: str, expected_origin: str, label: str) -> None:
        parsed = urlsplit(str(value))
        actual = f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else ""
        if parsed.scheme != "https" or actual != expected_origin:
            raise ArasAuthError(f"{label} origin is not trusted", stage="origin-validation")

    def _require_callback(self, value: str) -> None:
        """The OIDC callback must match the registered redirect_uri exactly."""
        expected = urlsplit(self.redirect_uri)
        parsed = urlsplit(str(value))
        if not (
            parsed.scheme == expected.scheme
            and parsed.netloc == expected.netloc
            and parsed.path == expected.path
        ):
            raise ArasAuthError("ECM OIDC callback is not trusted", stage="callback-validation")

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
    ) -> None:
        status = int(getattr(trace.response, "status_code", 0) or 0)
        self._emit(
            _event_from_trace(
                trace,
                validation=validation,
                exception_type=exception_type,
                reason=message,
            )
        )
        raise ArasAuthError(message, stage=trace.stage, request_id=trace.request_id, status_code=status)

    def _emit(self, event: ArasAuthHttpDiagnosticEvent) -> None:
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
            logger.warning("ECM auth diagnostic hook failed: %s", type(exc).__name__)


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


def _is_login_page(lowered_body: str) -> bool:
    return any(marker in lowered_body for marker in _LOGIN_PAGE_MARKERS)


def _has_challenge(lowered_body: str) -> bool:
    return any(marker in lowered_body for marker in _CHALLENGE_MARKERS)


def _validate_user_response_has_id(xml_text: str) -> bool:
    """Gate on the bundled client behavior: ``//Result/id`` must be present."""
    import xml.etree.ElementTree as ET

    if not xml_text or not xml_text.strip():
        return False
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return False
    result = next((node for node in root.iter() if _local_name(node.tag) == "Result"), None)
    if result is None:
        return False
    user_id = next((child for child in list(result) if _local_name(child.tag) == "id"), None)
    return user_id is not None and bool((user_id.text or "").strip())


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _event_from_trace(
    trace: _RequestTrace,
    *,
    validation: str,
    json_fields: tuple[str, ...] = (),
    exception_type: str | None = None,
    reason: str | None = None,
) -> ArasAuthHttpDiagnosticEvent:
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
) -> ArasAuthHttpDiagnosticEvent:
    parts = urlsplit(url)
    # 事件 URL 不含 query/fragment，避免 state/code 等参数进入诊断
    safe_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return ArasAuthHttpDiagnosticEvent(
        timestamp=datetime.now().isoformat(timespec="milliseconds"),
        stage=stage,
        request_id=request_id,
        method=method,
        url=safe_url,
        path=parts.path,
        query=dict(query),
        timeout=timeout,
        status_code=status_code,
        elapsed_ms=elapsed_ms,
        request_headers=_safe_auth_headers(headers),
        response_headers=_safe_auth_headers(response_headers or {}),
        json_fields=json_fields,
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


def _without_url_query(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return value.split("?", 1)[0].split("#", 1)[0]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _single_query_value(values: Mapping[str, list[str]], name: str) -> str:
    items = values.get(name, [])
    return str(items[0]) if len(items) == 1 else ""


def _response_text(response: Any) -> str:
    text = getattr(response, "text", "")
    if isinstance(text, str):
        return text
    content = getattr(response, "content", b"")
    return content.decode("utf-8", errors="replace") if isinstance(content, bytes) else ""


def _header_value(headers: Mapping[str, Any], name: str) -> str:
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            return str(value)
    return ""


def _origin(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return base_url.rstrip("/")


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


def _validate_redirect_uri(value: str) -> str:
    text = str(value).strip()
    parsed = urlsplit(text)
    if not (parsed.scheme in {"http", "https"} and parsed.netloc and parsed.path):
        raise ValueError("redirect_uri is invalid")
    return text


def _validate_random_value(value: str, label: str) -> str:
    text = str(value)
    if not re.fullmatch(r"[A-Za-z0-9._~-]{16,256}", text):
        raise ArasAuthError(f"{label} generation failed", stage="oidc-parameter-generation")
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
