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
import sys
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
# 三段认证链后两段所用的端点：
# - 外层 OIDC token 仅用于调 userinfo 拿 preferred_username，最终 session 不带它
# - ADValidate 桥：用 userinfo 字段换出 Innovator 内部账号的 MD5 密码
# - 内层 Innovator OAuthServer password grant：用 MD5 换 aud 含 Innovator 的 access_token
USERINFO_PATH = f"/auth/realms/{ECM_OIDC_REALM}/protocol/openid-connect/userinfo"
ADVALIDATE_PATH = "/ADLogin/ADValidate.asmx/findUserByloginname"
INNOVATOR_OAUTH_TOKEN_PATH = "/oauthserver/connect/token"
INNOVATOR_CLIENT_ID = "InnovatorClient"
INNOVATOR_SCOPE = "openid Innovator"
ECM_OIDC_TOKEN_SCOPE = "email profile openid"
_WINHTTP_PROGID = "WinHttp.WinHttpRequest.5.1"
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
        innovator_database: str = "InnovatorSolutions",
        native_session_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.base_url = _normalize_aras_app_root(base_url)
        if not urlsplit(self.base_url).scheme or not urlsplit(self.base_url).netloc:
            raise ValueError("base_url must be an absolute http(s) URL")
        self.identity_origin = _normalize_https_origin(identity_origin, "identity_origin")
        self.oidc_client_id = _validate_client_id(oidc_client_id)
        self.redirect_uri = _validate_redirect_uri(redirect_uri)
        self.timeout = _validate_timeout(timeout)
        self._session_injected = session is not None
        if session is None:
            if requests is None:
                raise ImportError("ArasECMAuthClient requires requests; install requirements.txt")
            session = requests.Session()
            session.trust_env = False
        self.session = session
        self.diagnostic_hook = diagnostic_hook
        self.random_value_factory = random_value_factory or (lambda: uuid.uuid4().hex)
        self.innovator_database = str(innovator_database).strip() or "InnovatorSolutions"
        self.native_session_factory = native_session_factory
        # 在 frozen/源码 win32 生产环境下，切到 WinHTTP COM 传输，绕开 urllib3
        # 在某些 frozen 环境对明文 HTTP(80) socket 建链失败的问题（与 tdc_auth 同构）。
        # 测试通过显式注入 session 触发 _session_injected=True 跳过此切换。
        if not self._session_injected and (
            self.native_session_factory is not None or sys.platform == "win32"
        ):
            factory = self.native_session_factory or _new_native_aras_session
            try:
                self.session = factory()
            except Exception as exc:
                raise ArasAuthError(
                    f"Aras native session creation failed: {type(exc).__name__}",
                    stage="aras-session-init",
                ) from exc

    def login(self, username: str, password: str) -> ArasLoginResult:
        """Run the OIDC code flow, gate on Aras SOAP ValidateUser, return the session."""
        # 重复调用 login() 时，先丢弃上一轮残留的 Innovator token，避免它被
        # _request 合并进本轮外层身份域（account.sgmw.com.cn）请求而跨域泄露。
        self.session.headers.pop("Authorization", None)
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
            "scope": ECM_OIDC_TOKEN_SCOPE,
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
        outer_access_token = oidc_payload.get("access_token")
        if not isinstance(outer_access_token, str) or not outer_access_token:
            self._reject(oidc_token, "oidc-token-missing", "ECM OIDC response does not contain an access token")
        self._accept(oidc_token, validation="oidc-token-received", json_fields=tuple(sorted(oidc_payload)))
        # The outer OIDC token is used only to call userinfo and obtain the corporate
        # preferred_username; it never becomes the session Authorization header (its
        # aud is ecm-front, which Innovator Server does not accept).

        # --- Stage: 外层 userinfo（用完即丢，绝不让外层 token 进入最终 session）---
        userinfo_url = urljoin(self.identity_origin, USERINFO_PATH.lstrip("/"))
        try:
            self.session.headers["Authorization"] = f"Bearer {outer_access_token}"
            userinfo_trace = self._request(
                "POST",
                userinfo_url,
                stage="ecm-userinfo",
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Content-Type": "application/json",
                    "User-Agent": DEFAULT_BROWSER_USER_AGENT,
                },
                data={},
                allow_redirects=False,
            )
        finally:
            self.session.headers.pop("Authorization", None)
            outer_access_token = ""
        userinfo_payload = self._json_response(userinfo_trace)
        preferred_username = userinfo_payload.get("preferred_username")
        if not isinstance(preferred_username, str) or not preferred_username.strip():
            self._reject(
                userinfo_trace,
                "userinfo-missing",
                "ECM userinfo response does not contain preferred_username",
            )
        given_name = userinfo_payload.get("given_name") or "0"
        family_name = userinfo_payload.get("family_name") or "0"
        email = userinfo_payload.get("email") or "000000"
        self._accept(
            userinfo_trace,
            validation="userinfo-received",
            json_fields=tuple(sorted(userinfo_payload)),
        )

        # --- Stage: ADValidate 桥（ecm 域 http；换出 Innovator 内部账号 MD5 密码）---
        advalidate_url = urljoin(self.base_url, ADVALIDATE_PATH.lstrip("/"))
        advalidate_form = {
            "loginname": preferred_username,
            "given_name": given_name,
            "family_name": family_name,
            "email": email,
        }
        try:
            advalidate_trace = self._request(
                "POST",
                advalidate_url,
                stage="ecm-advalidate",
                headers={
                    "Accept": "application/xml, text/xml, */*; q=0.01",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "X-Requested-With": "XMLHttpRequest",
                    "Origin": _origin(self.base_url),
                    "Referer": self.redirect_uri,
                    "User-Agent": DEFAULT_BROWSER_USER_AGENT,
                },
                data=advalidate_form,
                allow_redirects=False,
            )
        finally:
            advalidate_form["loginname"] = ""
        # ADValidate 返 XML，不能走 _json_response（其 Content-Type 含 xml 会被拒）。
        # 先校验 HTTP 状态，避免非 2xx 响应因恰好含成功 XML 而被误判通过。
        ad_status = int(getattr(advalidate_trace.response, "status_code", 0) or 0)
        if ad_status not in set(range(200, 300)):
            self._reject(
                advalidate_trace,
                "advalidate-rejected",
                f"ADValidate returned HTTP {ad_status}",
            )
        ad_body = _response_text(advalidate_trace.response)
        ad_success, innovator_md5 = _parse_advalidate_response(ad_body)
        if not ad_success or not _is_valid_md5(innovator_md5):
            self._reject(
                advalidate_trace,
                "advalidate-failed",
                "ADValidate did not return a valid Innovator password",
            )
        self._accept(advalidate_trace, validation="innovator-md5-received")

        # --- Stage: 内层 Innovator OAuthServer password grant（用 MD5 换 aud=Innovator 的 token）---
        innovator_token_url = urljoin(self.base_url, INNOVATOR_OAUTH_TOKEN_PATH.lstrip("/"))
        innovator_form = {
            "grant_type": "password",
            "client_id": INNOVATOR_CLIENT_ID,
            "username": preferred_username,
            "password": innovator_md5,
            "scope": INNOVATOR_SCOPE,
            "database": self.innovator_database,
        }
        try:
            innovator_token_trace = self._request(
                "POST",
                innovator_token_url,
                stage="ecm-innovator-token",
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": DEFAULT_BROWSER_USER_AGENT,
                },
                data=innovator_form,
                allow_redirects=False,
            )
        finally:
            innovator_form["password"] = ""
            innovator_form["username"] = ""
            # 立即丢弃 MD5 与 username 变量副本，避免在 4xx/解析失败的栈帧中残留
            innovator_md5 = ""
            preferred_username = ""
        inn_status = int(getattr(innovator_token_trace.response, "status_code", 0) or 0)
        if inn_status not in set(range(200, 300)):
            # 不回显任意响应正文：服务端可能在 error_description 中回显 MD5/JWT。
            # 仅取白名单错误码字段（OAuth 标准 error / 自定义 code），不含凭据。
            err_payload = _parse_json_payload(innovator_token_trace.response)
            err_code = err_payload.get("error") or err_payload.get("error_code") or err_payload.get("code")
            msg = f"Innovator token exchange failed: HTTP {inn_status}"
            if isinstance(err_code, (str, int)) and str(err_code).strip():
                msg += f" (error={err_code})"
            self._reject(innovator_token_trace, "innovator-token-rejected", msg)
        innovator_payload = _parse_json_payload(innovator_token_trace.response)
        inner_access_token = innovator_payload.get("access_token")
        if not isinstance(inner_access_token, str) or not inner_access_token:
            self._reject(
                innovator_token_trace,
                "innovator-token-missing",
                "Innovator token exchange did not return an access token",
            )
        innovator_token_type = _safe_token_type(innovator_payload.get("token_type"))
        self._accept(
            innovator_token_trace,
            validation="innovator-token-received",
            json_fields=tuple(sorted(innovator_payload)),
        )

        # The Innovator access_token (aud contains Innovator) is the only token that
        # lives only in this in-memory session; never persist or log it.
        self.session.headers["Authorization"] = f"{innovator_token_type} {inner_access_token}"
        inner_access_token = ""

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
        # Merge session-level headers (e.g. Authorization added between stages)
        # with the stage-specific headers; stage headers win on conflict.
        merged_headers = {**dict(getattr(self.session, "headers", {}) or {}), **dict(headers)}
        try:
            request_method = getattr(self.session, method.lower())
            response = request_method(
                url,
                params=dict(params or {}),
                data=dict(data) if isinstance(data, Mapping) else data,
                headers=merged_headers,
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


def _parse_advalidate_response(xml_text: str) -> tuple[bool, str]:
    """Parse the ADValidate XML envelope. Returns (is_success, md5_password).

    Never raises; malformed bodies simply report failure so the caller can
    reject with a fixed, secret-free message.
    """
    if not xml_text:
        return False, ""
    m_ok = re.search(r"<IsSuccess>\s*(\w+)\s*</IsSuccess>", xml_text, re.IGNORECASE)
    m_pw = re.search(
        r"<password>\s*([0-9a-fA-F]{32})\s*</password>", xml_text, re.IGNORECASE
    )
    success = bool(m_ok and m_ok.group(1).strip().lower() == "true")
    return success, (m_pw.group(1) if m_pw else "")


def _is_valid_md5(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{32}", value or ""))


def _safe_token_type(value: Any) -> str:
    """Sanitize a token_type string, defaulting to Bearer (mirrors tdc_auth)."""
    token_type = str(value or "Bearer").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9._~-]{0,31}", token_type or ""):
        return "Bearer"
    return token_type or "Bearer"


def _parse_json_payload(response: Any) -> dict[str, Any]:
    """Best-effort JSON parse from a response, never raising (caller prechecks status)."""
    loader = getattr(response, "json", None)
    if callable(loader):
        try:
            payload = loader()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            return payload
    try:
        payload = json.loads(_response_text(response) or "{}")
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _new_native_aras_session() -> Any:
    """Create a WinHTTP-backed session for win32 production (mirrors tdc_auth).

    WinHTTP via COM bypasses Python's urllib3/socket path, avoiding frozen-EXE
    plaintext-HTTP(80) connection failures observed on some Windows hosts.
    Eagerly import the COM stack here so a missing pywin32 or unregistered
    WinHttp progid surfaces at session-init (mapped to aras-session-init by the
    caller) rather than later at the first request stage.
    """
    import pythoncom
    import win32com.client
    from services.windows_http import WinHTTPSession

    # Probe the COM progid availability now; raise ImportError/DispatchError
    # here so the __init__ guard maps it to aras-session-init.
    pythoncom.CoInitialize()
    try:
        win32com.client.Dispatch(_WINHTTP_PROGID)
    finally:
        pythoncom.CoUninitialize()
    return WinHTTPSession()


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
