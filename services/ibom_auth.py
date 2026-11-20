"""iBOM 域账号登录（统一身份认证 → iBOM 服务端换 code → checkToken）。

登录链（2026-11-20 实网取证，docs/PLAN_20261119_IBOM_DMM_DUAL_SOURCE.md §3.3）：

1. ``GET {iBOM}/fwPlatform/ssoAuth/login.api``（不跟随）→ 302 到
   ``account.sgmw.com.cn/auth/realms/common/protocol/openid-connect/auth``，
   ``client_id=ibom-front``，``state`` 由 iBOM 生成，``redirect_uri`` 指回 iBOM。
2. ``GET`` 认证地址 → 登录页；表单与 TDC 登录页相同（复用 ``services.tdc_auth`` 的解析）。
3. ``POST`` 表单 → 302 回 iBOM 回调（带 ``code``、``state``）。
4. 跟随 iBOM 回调：iBOM 服务端用 code 建立会话并写 Cookie。
5. ``POST {iBOM}/fwSecurity/authentication/checkToken.api`` → ``userToken``。

安全约束：

- 密码只发送一次（步骤 3），**任何失败都不重试密码**（统一身份认证错 3 次锁号）。
- 每一跳都校验主机：只允许 iBOM 本身与统一身份认证两个源。
- 错误信息只带阶段与 HTTP 状态，不带 URL 查询值、Cookie、token 或密码。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import parse_qs, urljoin, urlsplit

from core.redaction import redact_sensitive_text
from services.ibom_client import (
    DEFAULT_IBOM_BASE_URL,
    IBOMClientError,
    check_token,
    normalize_https_origin,
)
from services.tdc_auth import _parse_login_form  # 同一统一身份认证登录页，解析逻辑单一来源

try:  # pragma: no cover - 依赖缺失时由构造函数报错
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

DEFAULT_IBOM_IDENTITY_ORIGIN = "https://account.sgmw.com.cn"
DEFAULT_IBOM_OIDC_CLIENT_ID = "ibom-front"
IBOM_SSO_ENTRY_PATH = "/fwPlatform/ssoAuth/login.api"
_OIDC_AUTH_PATH = "/auth/realms/common/protocol/openid-connect/auth"
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_MAX_CALLBACK_REDIRECTS = 6
_OPTIONAL_FORM_FIELDS = ("newokey", "eodpkey", "feishukey", "phoneNumber", "code", "credentialId")
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
_BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "User-Agent": _USER_AGENT,
}


class IBOMAuthError(RuntimeError):
    """iBOM 登录失败。``credentials_sent`` 表示密码是否已经发出过（调用方据此禁止重试）。"""

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        status_code: int | None = None,
        credentials_sent: bool = False,
    ) -> None:
        super().__init__(redact_sensitive_text(message))
        self.stage = stage
        self.status_code = status_code
        self.credentials_sent = credentials_sent


@dataclass(frozen=True)
class IBOMLoginResult:
    """已登录会话。token 不进 repr，避免误入日志。"""

    session: Any = field(repr=False)
    user_token: str = field(repr=False)
    user_login_name: str = field(repr=False)
    login_type: str = "DEFAULT_SSO"


def _status(response: Any) -> int:
    return int(getattr(response, "status_code", 0) or 0)


def _location(response: Any) -> str:
    headers = getattr(response, "headers", {}) or {}
    for key in ("Location", "location"):
        value = headers.get(key) if hasattr(headers, "get") else None
        if value:
            return str(value)
    return ""


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


def _text(response: Any) -> str:
    try:
        return str(getattr(response, "text", "") or "")
    except Exception:
        return ""


class IBOMPasswordAuthClient:
    """用域账号走统一身份认证登录 iBOM。一次 ``login`` 最多发送一次密码。"""

    def __init__(
        self,
        base_url: str = DEFAULT_IBOM_BASE_URL,
        *,
        identity_origin: str = DEFAULT_IBOM_IDENTITY_ORIGIN,
        oidc_client_id: str = DEFAULT_IBOM_OIDC_CLIENT_ID,
        session: Any | None = None,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = normalize_https_origin(base_url, "base_url")
        self.identity_origin = normalize_https_origin(identity_origin, "identity_origin")
        if not oidc_client_id or not oidc_client_id.replace("-", "").isalnum():
            raise ValueError("oidc_client_id is invalid")
        self.oidc_client_id = oidc_client_id
        if not (0 < float(timeout) <= 300):
            raise ValueError("timeout must be in (0, 300]")
        self.timeout = float(timeout)
        if session is None:
            if requests is None:
                raise ImportError("IBOMPasswordAuthClient requires requests; install requirements.txt")
            session = requests.Session()
            session.trust_env = False  # 与 TDC 一致：内网直连，不走系统代理变量
        self.session = session
        self._sleep = sleep

    # ── 公共入口 ────────────────────────────────────────────────────
    def login(self, username: str, password: str) -> IBOMLoginResult:
        username_value = str(username or "").strip()
        password_value = str(password or "")
        if not username_value or not password_value:
            raise IBOMAuthError("iBOM username and password are required", stage="credential-validation")
        if any(ord(char) < 32 for char in username_value):
            raise IBOMAuthError("iBOM username contains control characters", stage="credential-validation")

        auth_url = self._start_sso()
        login_url, payload = self._login_form(auth_url)
        payload["username"] = username_value
        payload["password"] = password_value
        try:
            callback_url = self._post_credentials(login_url, auth_url, payload)
        finally:
            payload["password"] = ""
            password_value = ""
        self._follow_callback(callback_url)
        try:
            token = check_token(self.session, self.base_url, timeout=self.timeout, sleep=self._sleep)
        except IBOMClientError as exc:
            raise IBOMAuthError(
                f"iBOM session was not established: {exc}",
                stage="check-token",
                status_code=exc.status_code,
                credentials_sent=True,
            ) from None
        return IBOMLoginResult(
            session=self.session,
            user_token=token.user_token,
            user_login_name=token.user_login_name,
            login_type=token.login_type,
        )

    # ── 步骤 ────────────────────────────────────────────────────────
    def _get(self, url: str, stage: str, *, headers: dict[str, str] | None = None) -> Any:
        try:
            return self.session.get(
                url,
                headers={**_BROWSER_HEADERS, **(headers or {})},
                timeout=self.timeout,
                allow_redirects=False,
            )
        except Exception as exc:
            raise IBOMAuthError(
                f"iBOM login request failed during {stage}: {type(exc).__name__}", stage=stage
            ) from None

    def _start_sso(self) -> str:
        entry = self.base_url + IBOM_SSO_ENTRY_PATH
        response = self._get(entry, "sso-entry")
        if _status(response) not in _REDIRECT_STATUSES:
            raise IBOMAuthError(
                "iBOM SSO entry did not redirect to the identity provider",
                stage="sso-entry",
                status_code=_status(response),
            )
        auth_url = urljoin(entry, _location(response))
        parts = urlsplit(auth_url)
        if _origin(auth_url) != self.identity_origin or parts.path != _OIDC_AUTH_PATH:
            raise IBOMAuthError("iBOM SSO entry redirected to an unexpected host or path", stage="sso-entry")
        query = parse_qs(parts.query)
        if query.get("client_id") != [self.oidc_client_id]:
            raise IBOMAuthError("iBOM SSO entry uses an unexpected client_id", stage="sso-entry")
        redirect = (query.get("redirect_uri") or [""])[0]
        if _origin(redirect) != self.base_url:
            raise IBOMAuthError("iBOM SSO redirect_uri does not point back to iBOM", stage="sso-entry")
        if not (query.get("state") or [""])[0]:
            raise IBOMAuthError("iBOM SSO entry did not provide a state value", stage="sso-entry")
        return auth_url

    def _login_form(self, auth_url: str) -> tuple[str, dict[str, str]]:
        response = self._get(auth_url, "auth-discovery")
        if _status(response) != 200:
            raise IBOMAuthError(
                "identity provider did not return the login page",
                stage="auth-discovery",
                status_code=_status(response),
            )
        form = _parse_login_form(_text(response))
        if form is None or form.method != "post":
            raise IBOMAuthError("identity login page has no username/password POST form", stage="auth-discovery")
        login_url = urljoin(auth_url, form.action)
        if _origin(login_url) != self.identity_origin:
            raise IBOMAuthError("identity login form posts to an unexpected host", stage="auth-discovery")
        payload = dict(form.fields)
        for name in _OPTIONAL_FORM_FIELDS:
            payload.setdefault(name, "")
        return login_url, payload

    def _post_credentials(self, login_url: str, auth_url: str, payload: dict[str, str]) -> str:
        headers = {
            **_BROWSER_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": self.identity_origin,
            "Referer": auth_url,
        }
        try:
            response = self.session.post(
                login_url, data=payload, headers=headers, timeout=self.timeout, allow_redirects=False
            )
        except Exception as exc:
            raise IBOMAuthError(
                f"iBOM credential submission failed: {type(exc).__name__}",
                stage="auth-credentials",
                credentials_sent=True,
            ) from None
        if _status(response) not in _REDIRECT_STATUSES:
            raise IBOMAuthError(
                "identity provider rejected the credentials or requires additional verification",
                stage="auth-credentials",
                status_code=_status(response),
                credentials_sent=True,
            )
        callback = urljoin(login_url, _location(response))
        if _origin(callback) != self.base_url:
            raise IBOMAuthError(
                "identity provider redirected to an unexpected host after login",
                stage="auth-credentials",
                credentials_sent=True,
            )
        values = parse_qs(urlsplit(callback).query)
        if not (values.get("code") or [""])[0] or not (values.get("state") or [""])[0]:
            raise IBOMAuthError(
                "login callback is missing code/state", stage="auth-credentials", credentials_sent=True
            )
        return callback

    def _follow_callback(self, url: str) -> None:
        allowed = {self.base_url, self.identity_origin}
        for _ in range(_MAX_CALLBACK_REDIRECTS):
            response = self._get(url, "sso-callback")
            status = _status(response)
            if status in _REDIRECT_STATUSES:
                nxt = urljoin(url, _location(response))
                if _origin(nxt) not in allowed:
                    # 回调最终跳去前端页面以外的主机：会话可能已建立，交给 checkToken 判定。
                    return
                url = nxt
                continue
            if status >= 400:
                raise IBOMAuthError(
                    "iBOM SSO callback failed", stage="sso-callback", status_code=status, credentials_sent=True
                )
            return
        raise IBOMAuthError("iBOM SSO callback redirected too many times", stage="sso-callback", credentials_sent=True)
