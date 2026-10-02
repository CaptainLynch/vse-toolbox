from __future__ import annotations

import base64
from http.cookiejar import CookieJar
from typing import Any
import sys

import pytest

from services.tdc_auth import TDCAuthError, TDCPasswordAuthClient
from services.windows_http import WinHTTPSession


def _make_cookie(
    name: str,
    value: str,
    *,
    domain: str,
    domain_specified: bool,
    domain_initial_dot: bool,
    path: str = "/",
    path_specified: bool = True,
    secure: bool = True,
) -> Any:
    from http.cookiejar import Cookie

    return Cookie(
        version=0,
        name=name,
        value=value,
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=domain_specified,
        domain_initial_dot=domain_initial_dot,
        path=path,
        path_specified=path_specified,
        secure=secure,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest={},
        rfc2109=False,
    )


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        url: str = "",
        headers: dict[str, str] | None = None,
        text: str = "",
        payload: Any = None,
    ) -> None:
        self.status_code = status_code
        self.url = url
        self.headers = headers or {}
        self.text = text
        self.content = text.encode("utf-8")
        self._payload = payload

    def json(self):  # type: ignore[no-untyped-def]
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.trust_env = True
        self.headers: dict[str, str] = {}

    def get(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
        return self._next("GET", url, kwargs)

    def post(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
        return self._next("POST", url, kwargs)

    def _next(self, method: str, url: str, kwargs: dict[str, Any]):
        self.calls.append({"method": method, "url": url, **kwargs})
        if not self.responses:
            raise AssertionError(f"unexpected {method}")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class NativeFakeSession(FakeSession):
    """FakeSession that also exposes import_cookies, delegating to a real jar.

    Lets tests assert cross-session cookie migration timing and counts without
    exercising WinHTTP/COM, while reusing the real RFC matching logic.
    """

    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        super().__init__(responses)
        self._jar = WinHTTPSession()
        self.import_calls: list[dict[str, Any]] = []

    def import_cookies(self, cookies: Any, target_url: str) -> int:
        self.import_calls.append({"target_url": target_url})
        return self._jar.import_cookies(cookies, target_url)


AUTH_URL = (
    "https://account.sgmw.com.cn/auth/realms/common/protocol/openid-connect/auth"
    "?client_id=tpc-front&redirect_uri=https%3A%2F%2Ftdc.sgmw.com.cn%2Ftpc"
    "&response_mode=fragment&response_type=code&scope=openid"
    "&state=fictional-state-value&nonce=fictional-nonce-value"
)
LOGIN_HTML = """
<html><body>
  <form method="post" action="https://account.sgmw.com.cn/auth/realms/common/login-actions/authenticate?session_code=fictional-session&amp;execution=fictional-execution&amp;client_id=fictional-client&amp;tab_id=fictional-tab">
    <input name="username" type="text">
    <input name="password" type="password">
    <input name="newokey" type="hidden" value="">
    <input name="credentialId" type="hidden" value="">
  </form>
</body></html>
"""


def successful_responses() -> list[FakeResponse]:
    return [
        FakeResponse(
            status_code=200,
            url=AUTH_URL,
            headers={"Content-Type": "text/html; charset=utf-8"},
            text=LOGIN_HTML,
        ),
        FakeResponse(
            status_code=302,
            headers={
                "Location": (
                    "https://tdc.sgmw.com.cn/tpc"
                    "#state=fictional-state-value&session_state=fictional-session-state&code=fictional-code"
                )
            },
        ),
        FakeResponse(
            headers={"Content-Type": "application/json"},
            payload={
                "access_token": "fictional-identity-token",
                "refresh_token": "fictional-identity-refresh",
                "token_type": "bearer",
                "expires_in": 300,
            },
        ),
        FakeResponse(
            headers={
                "Content-Type": "application/json",
                "Set-Cookie": "tdc_session=fictional-cookie-secret; Secure; HttpOnly",
            },
            payload={
                "code": 0,
                "msg": "ok",
                "data": {
                    "access_token": "fictional-tdc-token",
                    "refresh_token": "fictional-tdc-refresh",
                    "expires_in": 600,
                },
            },
        ),
        FakeResponse(
            headers={"Content-Type": "application/json"},
            payload={"code": 0, "msg": "ok", "data": {"displayName": "Fictional User"}},
        ),
    ]


def make_auth_client(session: FakeSession, **kwargs: Any) -> TDCPasswordAuthClient:
    values = iter(["fictional-state-value", "fictional-nonce-value"])
    return TDCPasswordAuthClient(
        session=session,
        random_value_factory=lambda: next(values),
        form_login_client="fictional-client:fictional-client-secret",
        **kwargs,
    )


def test_password_login_completes_oidc_code_exchange_and_reuses_session() -> None:
    events = []
    session = FakeSession(successful_responses())
    client = make_auth_client(session, diagnostic_hook=events.append)

    result = client.login("fictional-user", "fictional-password-secret")

    assert result.session is session
    assert result.auth_mode == "password"
    assert result.token_expires_in == 600
    assert [call["method"] for call in session.calls] == ["GET", "POST", "POST", "POST", "GET"]
    assert session.calls[0]["allow_redirects"] is False
    assert session.calls[0]["url"].startswith(
        "https://account.sgmw.com.cn/auth/realms/common/protocol/openid-connect/auth?"
    )
    assert "client_id=tpc-front" in session.calls[0]["url"]
    assert session.calls[1]["allow_redirects"] is False
    assert session.calls[1]["data"]["username"] == "fictional-user"
    assert session.calls[1]["data"]["password"] == "fictional-password-secret"
    assert session.calls[2]["data"]["grant_type"] == "authorization_code"
    assert session.calls[3]["params"] == {"token": "fictional-identity-token"}
    assert session.calls[3]["data"] is None
    assert "Content-Type" not in session.calls[3]["headers"]
    expected_basic = "Basic " + base64.b64encode(
        b"fictional-client:fictional-client-secret"
    ).decode("ascii")
    assert session.calls[3]["headers"] == {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Origin": "https://tdc.sgmw.com.cn",
        "Referer": "https://tdc.sgmw.com.cn/tpc/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
        ),
        "isToken": "false",
        "Authorization": expected_basic,
        "Sec-CH-UA": (
            '"Not:A-Brand";v="99", "Google Chrome";v="145", '
            '"Chromium";v="145"'
        ),
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    assert session.calls[4]["url"] == "https://tdc.sgmw.com.cn/uwf/user/info"
    assert session.headers["Authorization"] == "Bearer fictional-tdc-token"
    assert [event.stage for event in events] == [
        "auth-discovery",
        "auth-credentials",
        "oidc-token",
        "tdc-token",
        "auth-verify",
    ]
    assert events[-1].validation == "authenticated"
    assert events[3].request_headers["isToken"] == "false"
    assert events[3].request_headers["Authorization"] == "[redacted]"
    assert events[3].request_headers["Sec-Fetch-Site"] == "same-origin"
    assert events[-1].request_headers["Authorization"] == "[redacted]"

    rendered = repr(result) + "\n" + "\n".join(repr(event) for event in events)
    for secret in (
        "fictional-user",
        "fictional-password-secret",
        "fictional-code",
        "fictional-identity-token",
        "fictional-identity-refresh",
        "fictional-tdc-token",
        "fictional-tdc-refresh",
        "fictional-cookie-secret",
        "fictional-state-value",
        "fictional-session",
        "fictional-nonce-value",
        "fictional-client-secret",
        expected_basic,
    ):
        assert secret not in rendered
    assert "[redacted]" in rendered


def test_password_login_rejects_untrusted_form_origin_before_sending_credentials() -> None:
    hostile_html = LOGIN_HTML.replace("https://account.sgmw.com.cn/", "https://identity.invalid/")
    session = FakeSession(
        [
            FakeResponse(
                status_code=200,
                url=AUTH_URL,
                headers={"Content-Type": "text/html"},
                text=hostile_html,
            )
        ]
    )

    with pytest.raises(TDCAuthError, match="not trusted"):
        make_auth_client(session).login("fictional-user", "fictional-password")

    assert len(session.calls) == 1


def test_password_login_rejects_failed_credentials_without_body_or_secret_leak() -> None:
    session = FakeSession(
        [
            FakeResponse(
                status_code=200,
                url=AUTH_URL,
                headers={"Content-Type": "text/html"},
                text=LOGIN_HTML,
            ),
            FakeResponse(
                status_code=200,
                url=AUTH_URL,
                headers={"Content-Type": "text/html"},
                text="fictional-password-secret was rejected",
            ),
        ]
    )

    with pytest.raises(TDCAuthError) as excinfo:
        make_auth_client(session).login("fictional-user", "fictional-password-secret")

    message = str(excinfo.value)
    assert "failed or requires additional verification" in message
    assert "fictional-password-secret" not in message
    assert "fictional-user" not in message


def test_password_login_transport_error_is_generic_and_diagnostics_are_redacted() -> None:
    events = []
    session = FakeSession([RuntimeError("fictional-password-secret")])

    with pytest.raises(TDCAuthError) as excinfo:
        make_auth_client(session, diagnostic_hook=events.append).login(
            "fictional-user", "fictional-password-secret"
        )

    combined = str(excinfo.value) + "\n" + "\n".join(repr(event) for event in events)
    assert "fictional-password-secret" not in combined
    assert "fictional-user" not in combined
    assert events[0].exception_type == "RuntimeError"


def test_token_exchange_401_records_allowlisted_redacted_json_detail() -> None:
    events = []
    responses = successful_responses()[:3]
    responses.append(
        FakeResponse(
            status_code=401,
            headers={"Content-Type": "application/json"},
            payload={
                "error": "invalid_token",
                "code": 40101,
                "message": "token=fictional-identity-token was rejected",
                "data": {"access_token": "fictional-response-token"},
            },
        )
    )
    session = FakeSession(responses)

    with pytest.raises(TDCAuthError) as excinfo:
        make_auth_client(session, diagnostic_hook=events.append).login(
            "fictional-user", "fictional-password-secret"
        )

    event = events[-1]
    rendered = str(excinfo.value) + repr(event)
    assert event.stage == "tdc-token"
    assert event.validation == "rejected-status"
    assert event.json_fields == ("code", "error", "message")
    assert "error=invalid_token" in (event.reason or "")
    assert "code=40101" in (event.reason or "")
    assert "token=[redacted]" in (event.reason or "")
    assert "fictional-identity-token" not in rendered
    assert "fictional-response-token" not in rendered


def test_password_login_validates_credentials_before_network() -> None:
    session = FakeSession([])
    client = make_auth_client(session)

    with pytest.raises(TDCAuthError, match="username is required"):
        client.login("", "fictional-password")
    with pytest.raises(TDCAuthError, match="password is required"):
        client.login("fictional-user", "")

    assert session.calls == []


def test_password_login_rejects_callback_state_mismatch() -> None:
    responses = successful_responses()[:2]
    responses[1].headers["Location"] = "https://tdc.sgmw.com.cn/tpc#state=wrong&code=fictional-code"
    session = FakeSession(responses)

    with pytest.raises(TDCAuthError, match="state/code validation failed"):
        make_auth_client(session).login("fictional-user", "fictional-password")

    assert len(session.calls) == 2


def test_new_windows_client_switches_to_native_session_after_oidc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    oidc_session = FakeSession(successful_responses()[:3])
    tdc_session = FakeSession(
        [
            FakeResponse(
                status_code=200,
                headers={"Content-Type": "text/html; charset=utf-8"},
                text="<html></html>",
            ),
            *successful_responses()[3:],
        ]
    )
    events = []
    values = iter(["fictional-state-value", "fictional-nonce-value"])

    class NativeClient(TDCPasswordAuthClient):
        pass

    monkeypatch.setattr("services.tdc_auth.requests.Session", lambda: oidc_session)
    client = NativeClient(
        diagnostic_hook=events.append,
        random_value_factory=lambda: next(values),
        tdc_session_factory=lambda: tdc_session,
    )
    result = client.login("fictional-user", "fictional-password")

    assert result.session is tdc_session
    assert [call["method"] for call in oidc_session.calls] == ["GET", "POST", "POST"]
    assert [call["method"] for call in tdc_session.calls] == ["GET", "POST", "GET"]
    entry_call = tdc_session.calls[0]
    assert entry_call["url"] == "https://tdc.sgmw.com.cn/tpc"
    assert entry_call["allow_redirects"] is False
    assert entry_call["headers"]["Accept"].startswith("text/html")
    assert "Origin" not in entry_call["headers"]
    assert [event.stage for event in events].count("tdc-entry") == 1
    assert next(event for event in events if event.stage == "tdc-entry").validation == "entry-observed"
    assert tdc_session.headers["Authorization"] == "Bearer fictional-tdc-token"


@pytest.mark.parametrize("entry_status", [401, 500])
def test_native_entry_http_error_does_not_hide_token_exchange(
    monkeypatch: pytest.MonkeyPatch, entry_status: int
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    oidc_session = FakeSession(successful_responses()[:3])
    tdc_session = FakeSession(
        [FakeResponse(status_code=entry_status), *successful_responses()[3:]]
    )
    events = []
    values = iter(["fictional-state-value", "fictional-nonce-value"])
    monkeypatch.setattr("services.tdc_auth.requests.Session", lambda: oidc_session)
    client = TDCPasswordAuthClient(
        diagnostic_hook=events.append,
        random_value_factory=lambda: next(values),
        tdc_session_factory=lambda: tdc_session,
    )

    result = client.login("fictional-user", "fictional-password")

    assert result.session is tdc_session
    assert [call["method"] for call in tdc_session.calls] == ["GET", "POST", "GET"]
    entry_event = next(event for event in events if event.stage == "tdc-entry")
    assert entry_event.status_code == entry_status
    assert entry_event.validation == "entry-http-observed"


def test_native_entry_follows_trusted_redirects_and_emits_one_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    oidc_session = FakeSession(successful_responses()[:3])
    tdc_session = FakeSession(
        [
            FakeResponse(status_code=302, headers={"Location": "/tpc/landing?route=1#hidden"}),
            FakeResponse(status_code=200, headers={"Content-Type": "text/html"}),
            *successful_responses()[3:],
        ]
    )
    events = []
    values = iter(["fictional-state-value", "fictional-nonce-value"])
    monkeypatch.setattr("services.tdc_auth.requests.Session", lambda: oidc_session)
    client = TDCPasswordAuthClient(
        diagnostic_hook=events.append,
        random_value_factory=lambda: next(values),
        tdc_session_factory=lambda: tdc_session,
    )

    client.login("fictional-user", "fictional-password")

    assert [call["url"] for call in tdc_session.calls[:3]] == [
        "https://tdc.sgmw.com.cn/tpc",
        "https://tdc.sgmw.com.cn/tpc/landing?route=1",
        "https://tdc.sgmw.com.cn/auth/oauth/token",
    ]
    assert [event.stage for event in events].count("tdc-entry") == 1


def test_native_entry_transport_error_stops_before_token_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    oidc_session = FakeSession(successful_responses()[:3])
    tdc_session = FakeSession([RuntimeError("fictional-transport-secret")])
    values = iter(["fictional-state-value", "fictional-nonce-value"])
    monkeypatch.setattr("services.tdc_auth.requests.Session", lambda: oidc_session)
    client = TDCPasswordAuthClient(
        random_value_factory=lambda: next(values),
        tdc_session_factory=lambda: tdc_session,
    )

    with pytest.raises(TDCAuthError) as excinfo:
        client.login("fictional-user", "fictional-password")

    assert excinfo.value.stage == "tdc-entry"
    assert "fictional-transport-secret" not in str(excinfo.value)
    assert [call["method"] for call in tdc_session.calls] == ["GET"]


def test_injected_session_is_never_replaced() -> None:
    session = FakeSession(successful_responses())

    def forbidden_factory() -> FakeSession:
        raise AssertionError("factory should not be called")

    result = make_auth_client(session, tdc_session_factory=forbidden_factory).login(
        "fictional-user", "fictional-password"
    )
    assert result.session is session


# --- cross-session cookie continuity experiment ---


def _oidc_session_with_cookies(monkeypatch: pytest.MonkeyPatch, *cookies: Any) -> FakeSession:
    monkeypatch.setattr(sys, "platform", "win32")
    oidc_session = FakeSession(successful_responses()[:3])
    jar = CookieJar()
    for cookie in cookies:
        jar.set_cookie(cookie)
    oidc_session.cookies = jar  # type: ignore[attr-defined]
    return oidc_session


def _make_native_client(
    monkeypatch: pytest.MonkeyPatch,
    oidc_session: FakeSession,
    tdc_session: NativeFakeSession,
    events: list,
) -> TDCPasswordAuthClient:
    values = iter(["fictional-state-value", "fictional-nonce-value"])
    monkeypatch.setattr("services.tdc_auth.requests.Session", lambda: oidc_session)
    return TDCPasswordAuthClient(
        diagnostic_hook=events.append,
        random_value_factory=lambda: next(values),
        tdc_session_factory=lambda: tdc_session,
    )


def test_native_switch_migrates_cookies_before_tdc_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = _make_cookie(
        "shared",
        "fictional-cookie-secret",
        domain=".sgmw.com.cn",
        domain_specified=True,
        domain_initial_dot=True,
        secure=True,
    )
    host_only = _make_cookie(
        "AUTH_SESSION_ID",
        "fictional-session-secret",
        domain="account.sgmw.com.cn",
        domain_specified=False,
        domain_initial_dot=False,
    )
    oidc_session = _oidc_session_with_cookies(monkeypatch, shared, host_only)
    tdc_session = NativeFakeSession(
        [
            FakeResponse(
                status_code=200,
                headers={"Content-Type": "text/html; charset=utf-8"},
                text="<html></html>",
            ),
            *successful_responses()[3:],
        ]
    )
    events: list = []
    client = _make_native_client(monkeypatch, oidc_session, tdc_session, events)

    client.login("fictional-user", "fictional-password")

    # Migration ran once, before the tdc-entry GET.
    assert len(tdc_session.import_calls) == 1
    assert tdc_session.import_calls[0]["target_url"] == "https://tdc.sgmw.com.cn/tpc"
    assert [call["method"] for call in tdc_session.calls] == ["GET", "POST", "GET"]
    assert tdc_session.calls[0]["url"] == "https://tdc.sgmw.com.cn/tpc"

    # Only the parent-domain cookie is eligible; account host-only is excluded.
    migration_event = next(
        event for event in events if event.stage == "tdc-cookie-migration"
    )
    assert migration_event.validation == "cookie-migration-performed"
    assert migration_event.record_count == 1
    assert migration_event.elapsed_ms is not None

    # tdc-entry still observed exactly once.
    assert [event.stage for event in events].count("tdc-entry") == 1

    rendered = repr(migration_event)
    assert "fictional-cookie-secret" not in rendered
    assert "fictional-session-secret" not in rendered
    assert "shared" not in rendered
    assert "AUTH_SESSION_ID" not in rendered


def test_native_switch_emits_migration_event_even_when_count_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_only = _make_cookie(
        "AUTH_SESSION_ID",
        "fictional-session-secret",
        domain="account.sgmw.com.cn",
        domain_specified=False,
        domain_initial_dot=False,
    )
    oidc_session = _oidc_session_with_cookies(monkeypatch, host_only)
    tdc_session = NativeFakeSession(
        [
            FakeResponse(
                status_code=200,
                headers={"Content-Type": "text/html; charset=utf-8"},
                text="<html></html>",
            ),
            *successful_responses()[3:],
        ]
    )
    events: list = []
    client = _make_native_client(monkeypatch, oidc_session, tdc_session, events)

    client.login("fictional-user", "fictional-password")

    migration_event = next(
        event for event in events if event.stage == "tdc-cookie-migration"
    )
    assert migration_event.validation == "cookie-migration-performed"
    assert migration_event.record_count == 0
    # Login still completes normally.
    assert [call["method"] for call in tdc_session.calls] == ["GET", "POST", "GET"]


def test_injected_session_does_not_trigger_migration() -> None:
    events: list = []
    session = FakeSession(successful_responses())

    def forbidden_factory() -> FakeSession:
        raise AssertionError("factory should not be called")

    make_auth_client(session, diagnostic_hook=events.append, tdc_session_factory=forbidden_factory).login(
        "fictional-user", "fictional-password"
    )

    assert not [event for event in events if event.stage == "tdc-cookie-migration"]


def test_migration_event_does_not_leak_cookies_tokens_or_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = _make_cookie(
        "shared",
        "fictional-cookie-secret",
        domain=".sgmw.com.cn",
        domain_specified=True,
        domain_initial_dot=True,
        secure=True,
    )
    oidc_session = _oidc_session_with_cookies(monkeypatch, shared)
    tdc_session = NativeFakeSession(
        [
            FakeResponse(
                status_code=200,
                headers={"Content-Type": "text/html; charset=utf-8"},
                text="<html></html>",
            ),
            *successful_responses()[3:],
        ]
    )
    events: list = []
    client = _make_native_client(monkeypatch, oidc_session, tdc_session, events)

    result = client.login("fictional-user", "fictional-password")

    rendered = repr(result) + "\n" + "\n".join(repr(event) for event in events)
    for secret in (
        "fictional-cookie-secret",
        "shared",
        "fictional-identity-token",
        "fictional-tdc-token",
        "fictional-password",
        "fictional-user",
    ):
        assert secret not in rendered
    assert "[redacted]" in rendered
