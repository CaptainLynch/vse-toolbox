from __future__ import annotations

from typing import Any

import pytest

from services.tdc_auth import TDCAuthError, TDCPasswordAuthClient


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
    return TDCPasswordAuthClient(session=session, random_value_factory=lambda: next(values), **kwargs)


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
    assert session.calls[3]["headers"]["istoken"] == "false"
    assert session.calls[4]["url"] == "https://tdc.sgmw.com.cn/uwf/user/info"
    assert [event.stage for event in events] == [
        "auth-discovery",
        "auth-credentials",
        "oidc-token",
        "tdc-token",
        "auth-verify",
    ]
    assert events[-1].validation == "authenticated"

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
