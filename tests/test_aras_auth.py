# -*- coding: utf-8 -*-
"""Focused tests for ECM (Aras) OIDC username/password authentication.

Only synthetic secret values are used; no real credentials and no live
network requests.
"""

from __future__ import annotations

from typing import Any

import pytest

from services.aras_auth import (
    ECM_REDIRECT_URI,
    SOAP_ACTION_VALIDATE_USER,
    ArasAuthError,
    ArasECMAuthClient,
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
        self.headers: dict[str, str] = {}
        self.trust_env = True

    def get(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
        return self._next("GET", url, kwargs)

    def post(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
        return self._next("POST", url, kwargs)

    def _next(self, method: str, url: str, kwargs: dict[str, Any]):  # type: ignore[no-untyped-def]
        self.calls.append({"method": method, "url": url, **kwargs})
        if not self.responses:
            raise AssertionError(f"unexpected {method} {url}")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


ECM_AUTH_URL = (
    "https://account.sgmw.com.cn/auth/realms/common/protocol/openid-connect/auth"
    "?client_id=ecm-front&redirect_uri=http%3A%2F%2Fecm.sgmw.com.cn%2Finnovatorserver%2Fclient%2Fredirect.html"
    "&response_type=code&scope=openid&state=fictional-state-value"
)
LOGIN_ACTION_URL = (
    "https://account.sgmw.com.cn/auth/realms/common/login-actions/authenticate"
    "?session_code=fictional-session&execution=fictional-execution"
    "&client_id=fictional-client&tab_id=fictional-tab"
)
LOGIN_HTML = f"""
<html><body>
  <form method="post" action="{LOGIN_ACTION_URL}">
    <input name="session_code" type="hidden" value="fictional-session">
    <input name="execution" type="hidden" value="fictional-execution">
    <input name="client_id" type="hidden" value="fictional-client">
    <input name="tab_id" type="hidden" value="fictional-tab">
    <input name="username" type="text">
    <input name="password" type="password">
  </form>
</body></html>
"""
CALLBACK_URL = (
    "http://ecm.sgmw.com.cn/innovatorserver/client/redirect.html"
    "?state=fictional-state-value&code=fictional-code"
)
VALIDATE_OK_XML = (
    '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">'
    "<SOAP-ENV:Body><Result>"
    "<login_name>fictional-user</login_name>"
    "<database>InnovatorSolutions</database>"
    "<authentication_type>OAuth</authentication_type>"
    "<password_hash_algorithm>SHA256</password_hash_algorithm>"
    "<id>FICTIONAL-USER-ID</id>"
    "<user_type>employee</user_type>"
    "</Result></SOAP-ENV:Body></SOAP-ENV:Envelope>"
)
USERINFO_PAYLOAD = {
    "preferred_username": "fictional-user",
    "given_name": "启航",
    "family_name": "林",
    "email": "fictional.user@sgmw.com.cn",
}
ADVALIDATE_OK_XML = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<Result xmlns="http://tempuri.org/">'
    "<IsSuccess>true</IsSuccess>"
    "<password>31fb5e75856fe1adf8528cb1f53e782c</password>"
    "</Result>"
)
INNOVATOR_TOKEN_PAYLOAD = {
    "access_token": "fictional-inner-token",
    "token_type": "Bearer",
    "expires_in": 108000,
    "scope": "openid Innovator",
}
TOKEN_URL = "https://account.sgmw.com.cn/auth/realms/common/protocol/openid-connect/token"
USERINFO_URL = "https://account.sgmw.com.cn/auth/realms/common/protocol/openid-connect/userinfo"
ADVALIDATE_URL = "http://ecm.sgmw.com.cn/innovatorserver/ADLogin/ADValidate.asmx/findUserByloginname"
INNOVATOR_TOKEN_URL = "http://ecm.sgmw.com.cn/innovatorserver/oauthserver/connect/token"
METADATA_URL = "https://account.sgmw.com.cn/auth/realms/common/.well-known/openid-configuration"


def successful_responses() -> list[FakeResponse]:
    return [
        # 0: OIDC auth discovery (login form)
        FakeResponse(
            status_code=200,
            url=ECM_AUTH_URL,
            headers={"Content-Type": "text/html; charset=utf-8"},
            text=LOGIN_HTML,
        ),
        # 1: credentials POST -> 302 to callback
        FakeResponse(status_code=302, headers={"Location": CALLBACK_URL}),
        # 2: OIDC metadata discovery
        FakeResponse(
            headers={"Content-Type": "application/json"},
            payload={"token_endpoint": TOKEN_URL},
        ),
        # 3: outer OIDC token exchange
        FakeResponse(
            headers={"Content-Type": "application/json"},
            payload={
                "access_token": "fictional-ecm-token",
                "token_type": "Bearer",
                "expires_in": 300,
            },
        ),
        # 4: outer userinfo
        FakeResponse(
            headers={"Content-Type": "application/json"},
            payload=USERINFO_PAYLOAD,
        ),
        # 5: ADValidate bridge -> Innovator MD5
        FakeResponse(
            headers={"Content-Type": "text/xml; charset=utf-8"},
            text=ADVALIDATE_OK_XML,
        ),
        # 6: inner Innovator OAuthServer password grant
        FakeResponse(
            headers={"Content-Type": "application/json"},
            payload=INNOVATOR_TOKEN_PAYLOAD,
        ),
        # 7: SOAP ValidateUser -> Result/id
        FakeResponse(
            headers={"Content-Type": "text/xml; charset=UTF-8"},
            text=VALIDATE_OK_XML,
        ),
    ]


def make_auth_client(session: FakeSession, **kwargs: Any) -> ArasECMAuthClient:
    return ArasECMAuthClient(
        session=session,  # type: ignore[arg-type]
        random_value_factory=lambda: "fictional-state-value",
        **kwargs,
    )


def test_password_login_completes_oidc_flow_and_gates_on_validate_user() -> None:
    events = []
    session = FakeSession(successful_responses())
    client = make_auth_client(session, diagnostic_hook=events.append)

    result = client.login("fictional-user", "fictional-password-secret")

    assert result.session is session
    assert result.auth_mode == "password"
    # 最终 session 只带内层 Innovator token（aud 含 Innovator），外层 ecm-front token 不留
    assert session.headers["Authorization"] == "Bearer fictional-inner-token"
    # 8 步：discovery(GET) credentials(POST) metadata(GET) ecm-token(POST)
    #       userinfo(POST) advalidate(POST) innovator-token(POST) validate(POST)
    assert [call["method"] for call in session.calls] == [
        "GET", "POST", "GET", "POST", "POST", "POST", "POST", "POST",
    ]

    auth_call = session.calls[0]
    assert auth_call["url"].startswith("https://account.sgmw.com.cn/auth/realms/common/protocol/openid-connect/auth?")
    assert auth_call["allow_redirects"] is False
    assert "client_id=ecm-front" in auth_call["url"]
    assert "response_type=code" in auth_call["url"]
    assert "scope=openid" in auth_call["url"]
    assert "state=fictional-state-value" in auth_call["url"]

    login_call = session.calls[1]
    assert login_call["url"] == LOGIN_ACTION_URL
    assert login_call["allow_redirects"] is False
    assert login_call["data"]["username"] == "fictional-user"
    # 密码逐字提交：不做 MD5/SHA 变换
    assert login_call["data"]["password"] == "fictional-password-secret"
    # 动态表单隐藏字段随请求回传
    assert login_call["data"]["session_code"] == "fictional-session"
    assert login_call["data"]["execution"] == "fictional-execution"
    assert login_call["data"]["client_id"] == "fictional-client"
    assert login_call["data"]["tab_id"] == "fictional-tab"
    assert "md5" not in str(login_call["data"]).lower()
    assert "hash" not in str(login_call["data"]).lower()

    metadata_call = session.calls[2]
    assert metadata_call["url"] == METADATA_URL

    token_call = session.calls[3]
    assert token_call["url"] == TOKEN_URL
    assert token_call["data"] == {
        "client_id": "ecm-front",
        "code": "fictional-code",
        "grant_type": "authorization_code",
        "redirect_uri": ECM_REDIRECT_URI,
        "scope": "email profile openid",
    }
    assert "client_secret" not in token_call["data"]
    assert "secret" not in token_call["data"]

    # 外层 userinfo：拿 preferred_username 给后续 ADValidate
    userinfo_call = session.calls[4]
    assert userinfo_call["url"] == USERINFO_URL
    assert userinfo_call["headers"]["Authorization"] == "Bearer fictional-ecm-token"

    # ADValidate 桥：用 userinfo 字段换 Innovator 内部账号 MD5 密码
    advalidate_call = session.calls[5]
    assert advalidate_call["url"] == ADVALIDATE_URL
    assert advalidate_call["headers"]["X-Requested-With"] == "XMLHttpRequest"
    assert advalidate_call["data"]["loginname"] == "fictional-user"
    assert advalidate_call["data"]["given_name"] == "启航"
    assert advalidate_call["data"]["family_name"] == "林"
    assert advalidate_call["data"]["email"] == "fictional.user@sgmw.com.cn"

    # 内层 Innovator OAuthServer password grant：MD5 换 aud=Innovator 的 token
    innovator_call = session.calls[6]
    assert innovator_call["url"] == INNOVATOR_TOKEN_URL
    assert innovator_call["data"]["grant_type"] == "password"
    assert innovator_call["data"]["client_id"] == "InnovatorClient"
    assert innovator_call["data"]["scope"] == "openid Innovator"
    assert innovator_call["data"]["database"] == "InnovatorSolutions"
    assert innovator_call["data"]["username"] == "fictional-user"
    assert "fictional-password-secret" not in str(innovator_call["data"])
    # MD5 在 form body，不进 headers，亦不应在诊断里裸露
    assert "31fb5e75856fe1adf8528cb1f53e782c" not in str(innovator_call["headers"])

    validate_call = session.calls[7]
    assert validate_call["url"] == "http://ecm.sgmw.com.cn/innovatorserver/Server/InnovatorServer.aspx"
    assert validate_call["headers"]["SOAPAction"] == SOAP_ACTION_VALIDATE_USER
    assert validate_call["headers"]["TIMEZONE_NAME"] == "China Standard Time"
    # 与捆绑客户端一致：ValidateUser 为带空 SOAP Body 的调用，方法名在 SOAPAction 头
    assert validate_call["data"] == (
        '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" >'
        "<SOAP-ENV:Body></SOAP-ENV:Body></SOAP-ENV:Envelope>"
    )
    assert "fictional-password-secret" not in validate_call["data"]

    assert [event.stage for event in events] == [
        "ecm-auth-discovery",
        "ecm-credentials",
        "ecm-credentials",
        "ecm-oidc-discovery",
        "ecm-token",
        "ecm-userinfo",
        "ecm-advalidate",
        "ecm-innovator-token",
        "ecm-validate-user",
    ]
    assert events[0].validation == "login-form-ready"
    assert events[1].validation == "credentials-redirect"
    assert events[2].validation == "authorization-code-received"
    assert events[-1].validation == "authenticated"

    rendered = repr(result) + "\n" + "\n".join(repr(event) for event in events)
    for secret in (
        "fictional-user",
        "fictional-password-secret",
        "fictional-code",
        "fictional-ecm-token",
        "fictional-inner-token",
        "fictional-state-value",
        "fictional-session",
        "FICTIONAL-USER-ID",
        "31fb5e75856fe1adf8528cb1f53e782c",
    ):
        assert secret not in rendered
    assert "[redacted]" in rendered


def test_password_login_rejects_untrusted_form_origin_before_sending_credentials() -> None:
    hostile_html = LOGIN_HTML.replace("https://account.sgmw.com.cn/", "https://identity.invalid/")
    session = FakeSession(
        [
            FakeResponse(
                status_code=200,
                url=ECM_AUTH_URL,
                headers={"Content-Type": "text/html"},
                text=hostile_html,
            )
        ]
    )

    with pytest.raises(ArasAuthError, match="not trusted"):
        make_auth_client(session).login("fictional-user", "fictional-password-secret")

    assert len(session.calls) == 1


def test_password_login_rejects_http_form_action() -> None:
    hostile_html = LOGIN_HTML.replace("https://account.sgmw.com.cn/", "http://account.sgmw.com.cn/")
    session = FakeSession(
        [
            FakeResponse(
                status_code=200,
                url=ECM_AUTH_URL,
                headers={"Content-Type": "text/html"},
                text=hostile_html,
            )
        ]
    )

    with pytest.raises(ArasAuthError, match="not trusted"):
        make_auth_client(session).login("fictional-user", "fictional-password-secret")

    assert len(session.calls) == 1


def test_password_login_rejects_credentials_without_body_or_secret_leak() -> None:
    session = FakeSession(
        [
            FakeResponse(
                status_code=200,
                url=ECM_AUTH_URL,
                headers={"Content-Type": "text/html"},
                text=LOGIN_HTML,
            ),
            FakeResponse(
                status_code=200,
                url=LOGIN_ACTION_URL,
                headers={"Content-Type": "text/html"},
                text='<html><form class="kc-form-login"><input name="username"><input type="password"></form></html>',
            ),
        ]
    )

    with pytest.raises(ArasAuthError) as excinfo:
        make_auth_client(session).login("fictional-user", "fictional-password-secret")

    message = str(excinfo.value)
    assert "failed or requires additional verification" in message
    assert "fictional-password-secret" not in message
    assert "fictional-user" not in message


@pytest.mark.parametrize(
    "challenge_html",
    [
        '<html><div id="captcha">captcha image</div></html>',
        '<html><label>请输入验证码</label></html>',
        '<html><input id="otp" name="otp" type="text"></html>',
        '<html><div class="mfa">two-factor required</div></html>',
        '<html><div>请扫码登录</div></html>',
    ],
)
def test_password_login_rejects_captcha_mfa_otp_challenges(challenge_html: str) -> None:
    session = FakeSession(
        [
            FakeResponse(status_code=200, url=ECM_AUTH_URL, headers={"Content-Type": "text/html"}, text=LOGIN_HTML),
            FakeResponse(status_code=200, url=LOGIN_ACTION_URL, headers={"Content-Type": "text/html"}, text=challenge_html),
        ]
    )

    with pytest.raises(ArasAuthError, match="CAPTCHA/MFA/OTP"):
        make_auth_client(session).login("fictional-user", "fictional-password-secret")

    assert len(session.calls) == 2


def test_password_login_validates_credentials_before_network() -> None:
    session = FakeSession([])
    client = make_auth_client(session)

    with pytest.raises(ArasAuthError, match="username is required"):
        client.login("", "fictional-password-secret")
    with pytest.raises(ArasAuthError, match="password is required"):
        client.login("fictional-user", "")

    assert session.calls == []


def test_password_login_rejects_callback_host_or_path_mismatch() -> None:
    for hostile in [
        "https://ecm.sgmw.com.cn/innovatorserver/client/redirect.html?state=fictional-state-value&code=fictional-code",
        "http://evil.example/innovatorserver/client/redirect.html?state=fictional-state-value&code=fictional-code",
        "http://ecm.sgmw.com.cn/other/path?state=fictional-state-value&code=fictional-code",
    ]:
        responses = successful_responses()[:2]
        responses[1].headers["Location"] = hostile
        session = FakeSession(responses)

        with pytest.raises(ArasAuthError, match="callback is not trusted"):
            make_auth_client(session).login("fictional-user", "fictional-password-secret")

        assert len(session.calls) == 2


def test_password_login_rejects_callback_state_mismatch() -> None:
    responses = successful_responses()[:2]
    responses[1].headers["Location"] = (
        "http://ecm.sgmw.com.cn/innovatorserver/client/redirect.html"
        "?state=wrong-state&code=fictional-code"
    )
    session = FakeSession(responses)

    with pytest.raises(ArasAuthError, match="state/code validation failed"):
        make_auth_client(session).login("fictional-user", "fictional-password-secret")

    assert len(session.calls) == 2


def test_password_login_rejects_callback_without_code() -> None:
    responses = successful_responses()[:2]
    responses[1].headers["Location"] = (
        "http://ecm.sgmw.com.cn/innovatorserver/client/redirect.html?state=fictional-state-value"
    )
    session = FakeSession(responses)

    with pytest.raises(ArasAuthError, match="state/code validation failed"):
        make_auth_client(session).login("fictional-user", "fictional-password-secret")


def test_token_exchange_uses_oidc_metadata_and_falls_back_to_derived_endpoint() -> None:
    # 1) discovery supplies the token endpoint
    session = FakeSession(successful_responses())
    make_auth_client(session).login("fictional-user", "fictional-password-secret")
    assert session.calls[3]["url"] == TOKEN_URL

    # 2) discovery unavailable (HTTP error) -> deterministic derived endpoint
    responses = successful_responses()
    responses[2] = FakeResponse(status_code=404, headers={"Content-Type": "text/html"}, text="missing")
    session = FakeSession(responses)
    make_auth_client(session).login("fictional-user", "fictional-password-secret")
    assert session.calls[3]["url"] == TOKEN_URL

    # 3) discovery JSON lacks token_endpoint -> derived endpoint
    responses = successful_responses()
    responses[2] = FakeResponse(headers={"Content-Type": "application/json"}, payload={"issuer": "x"})
    session = FakeSession(responses)
    make_auth_client(session).login("fictional-user", "fictional-password-secret")
    assert session.calls[3]["url"] == TOKEN_URL


def test_token_exchange_rejects_untrusted_metadata_token_endpoint() -> None:
    responses = successful_responses()
    responses[2] = FakeResponse(
        headers={"Content-Type": "application/json"},
        payload={"token_endpoint": "https://evil.example/token"},
    )
    session = FakeSession(responses)

    with pytest.raises(ArasAuthError, match="token endpoint origin is not trusted"):
        make_auth_client(session).login("fictional-user", "fictional-password-secret")

    assert len(session.calls) == 3


def test_token_response_without_access_token_is_rejected_without_leak() -> None:
    responses = successful_responses()
    responses[3] = FakeResponse(
        headers={"Content-Type": "application/json"},
        payload={"error": "fictional-code is invalid"},
    )
    session = FakeSession(responses)

    with pytest.raises(ArasAuthError, match="does not contain an access token") as excinfo:
        make_auth_client(session).login("fictional-user", "fictional-password-secret")

    assert "fictional-code" not in str(excinfo.value)
    assert len(session.calls) == 4


def test_validate_user_gate_fails_closed_without_user_id() -> None:
    responses = successful_responses()
    responses[7] = FakeResponse(
        headers={"Content-Type": "text/xml; charset=UTF-8"},
        text=(
            '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">'
            "<SOAP-ENV:Body><Result><login_name>fictional-user</login_name></Result></SOAP-ENV:Body></SOAP-ENV:Envelope>"
        ),
    )
    session = FakeSession(responses)

    with pytest.raises(ArasAuthError, match="did not return a valid user record") as excinfo:
        make_auth_client(session).login("fictional-user", "fictional-password-secret")

    message = str(excinfo.value)
    assert "fictional-user" not in message
    assert "fictional-password-secret" not in message
    assert "fictional-ecm-token" not in message
    assert session.headers.get("Authorization") is None  # 失败时移除 Bearer 头


def test_validate_user_http_rejection_fails_closed() -> None:
    responses = successful_responses()
    responses[7] = FakeResponse(
        status_code=401,
        headers={"Content-Type": "text/xml"},
        text="Authorization: Bearer fictional-rejection-token is invalid",
    )
    session = FakeSession(responses)

    with pytest.raises(ArasAuthError, match="HTTP 401") as excinfo:
        make_auth_client(session).login("fictional-user", "fictional-password-secret")

    assert "fictional-ecm-token" not in str(excinfo.value)
    assert "fictional-inner-token" not in str(excinfo.value)
    assert session.headers.get("Authorization") is None


def test_validate_user_login_page_rejection_fails_closed() -> None:
    responses = successful_responses()
    responses[7] = FakeResponse(
        headers={"Content-Type": "text/html"},
        text='<html><form class="login-form"><input type="password"></form></html>',
    )
    session = FakeSession(responses)

    with pytest.raises(ArasAuthError, match="returned a login page"):
        make_auth_client(session).login("fictional-user", "fictional-password-secret")

    assert session.headers.get("Authorization") is None


def test_advalidate_failure_rejected_without_secret_leak() -> None:
    responses = successful_responses()
    responses[5] = FakeResponse(
        headers={"Content-Type": "text/xml; charset=utf-8"},
        text='<?xml version="1.0"?><Result xmlns="http://tempuri.org/">'
        "<IsSuccess>false</IsSuccess></Result>",
    )
    session = FakeSession(responses)

    with pytest.raises(ArasAuthError, match="ADValidate did not return") as excinfo:
        make_auth_client(session).login("fictional-user", "fictional-password-secret")

    assert excinfo.value.stage == "ecm-advalidate"
    assert "fictional-password-secret" not in str(excinfo.value)
    assert "31fb5e75856fe1adf8528cb1f53e782c" not in str(excinfo.value)
    # ADValidate 失败时尚未把任何 token 写入 session
    assert session.headers.get("Authorization") is None


def test_innovator_token_failure_rejected_without_secret_leak() -> None:
    responses = successful_responses()
    responses[6] = FakeResponse(
        status_code=400,
        headers={"Content-Type": "application/json"},
        payload={"error": "invalid_grant", "error_description": "Missing database parameter"},
    )
    session = FakeSession(responses)

    with pytest.raises(ArasAuthError, match="Innovator token exchange failed") as excinfo:
        make_auth_client(session).login("fictional-user", "fictional-password-secret")

    assert excinfo.value.stage == "ecm-innovator-token"
    assert excinfo.value.status_code == 400
    assert "fictional-password-secret" not in str(excinfo.value)
    assert "31fb5e75856fe1adf8528cb1f53e782c" not in str(excinfo.value)
    # 新：error_description 不回显，仅白名单 error 字段
    assert "Missing database parameter" not in str(excinfo.value)
    assert "invalid_grant" in str(excinfo.value)


def test_innovator_token_4xx_does_not_echo_md5_from_error_description() -> None:
    """服务端在 error_description 中回显 MD5/JWT 时，异常消息不得包含这些秘密。"""
    responses = successful_responses()
    responses[6] = FakeResponse(
        status_code=400,
        headers={"Content-Type": "application/json"},
        payload={
            "error": "invalid_grant",
            "error_description": "bad credentials: password=31fb5e75856fe1adf8528cb1f53e782c token=eyJleaked",
        },
    )
    session = FakeSession(responses)

    with pytest.raises(ArasAuthError, match="Innovator token exchange failed") as excinfo:
        make_auth_client(session).login("fictional-user", "fictional-password-secret")

    message = str(excinfo.value)
    assert "31fb5e75856fe1adf8528cb1f53e782c" not in message
    assert "eyJleaked" not in message
    assert "bad credentials" not in message
    assert "invalid_grant" in message  # 白名单 error 字段保留


def test_advalidate_non_2xx_rejected_before_xml_parse() -> None:
    """非 2xx 响应即使 body 恰好含成功 XML，也应按 HTTP 状态先拒收。"""
    responses = successful_responses()
    responses[5] = FakeResponse(
        status_code=500,
        headers={"Content-Type": "text/xml; charset=utf-8"},
        text='<?xml version="1.0"?><Result xmlns="http://tempuri.org/">'
        "<IsSuccess>true</IsSuccess>"
        "<password>31fb5e75856fe1adf8528cb1f53e782c</password></Result>",
    )
    session = FakeSession(responses)

    with pytest.raises(ArasAuthError, match="ADValidate returned HTTP 500") as excinfo:
        make_auth_client(session).login("fictional-user", "fictional-password-secret")

    assert excinfo.value.stage == "ecm-advalidate"
    assert excinfo.value.status_code == 500
    assert session.headers.get("Authorization") is None


def test_repeated_login_clears_stale_inner_token_before_outer_requests() -> None:
    """重复 login() 时，上一轮残留的内层 token 不得被合并进本轮外层身份域请求。"""
    session = FakeSession(successful_responses())
    client = make_auth_client(session)
    client.login("fictional-user", "fictional-password-secret")
    assert session.headers["Authorization"] == "Bearer fictional-inner-token"

    # 第二次登录：重置 responses，检查 discovery 请求不带旧 inner token
    session.responses = successful_responses()
    session.calls = []
    client.login("fictional-user", "fictional-password-secret")

    # 第一次请求（discovery，account.sgmw.com.cn）的 Authorization 头应为空或外层临时 token，
    # 绝不是上一轮的 fictional-inner-token
    discovery_call = session.calls[0]
    auth_header = next(
        (v for n, v in discovery_call["headers"].items() if n.lower() == "authorization"),
        None,
    )
    assert auth_header != "Bearer fictional-inner-token"
    assert "fictional-inner-token" not in str(discovery_call["headers"])
    # 第二次登录成功后 session 带新 inner token（与第一次同值是 mock 复用，正常）
    assert session.headers["Authorization"] == "Bearer fictional-inner-token"


def test_transport_error_is_generic_and_diagnostics_are_redacted() -> None:
    events = []
    session = FakeSession([RuntimeError("fictional-password-secret")])

    with pytest.raises(ArasAuthError) as excinfo:
        make_auth_client(session, diagnostic_hook=events.append).login(
            "fictional-user", "fictional-password-secret"
        )

    combined = str(excinfo.value) + "\n" + "\n".join(repr(event) for event in events)
    assert "fictional-password-secret" not in combined
    assert "fictional-user" not in combined
    assert events[0].exception_type == "RuntimeError"


def test_public_login_result_repr_contains_no_credentials() -> None:
    session = FakeSession(successful_responses())
    result = make_auth_client(session).login("fictional-user", "fictional-password-secret")

    rendered = repr(result)
    assert "fictional-password-secret" not in rendered
    assert "fictional-ecm-token" not in rendered
    assert "fictional-code" not in rendered
    assert "Authorization" not in rendered


def test_ecm_auth_module_has_no_live_requests_calls() -> None:
    import re
    from pathlib import Path

    source = Path("services/aras_auth.py").read_text(encoding="utf-8-sig")
    assert not re.search(r"requests\.(?:get|post|head|request)\(", source)
    assert "getpass" not in source


def test_win32_default_uses_native_session_for_full_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    """win32 生产环境下，未注入 session 时 __init__ 阶段切到 native(WinHTTP) session，
    且 native session 承接全部 8 步请求（含外层 OIDC，因 ADValidate 是 ecm:80 明文，
    frozen urllib3 在该步即失败，故必须在 __init__ 就切，不能像 TDC 那样 oidc 后切）。"""
    import sys as _sys

    native_session = FakeSession(successful_responses())
    monkeypatch.setattr(_sys, "platform", "win32")

    client = ArasECMAuthClient(
        random_value_factory=lambda: "fictional-state-value",
        native_session_factory=lambda: native_session,
    )
    result = client.login("fictional-user", "fictional-password-secret")

    assert result.session is native_session
    # native session 承接全部 8 步（不像 TDC 只承接后段）
    assert [call["method"] for call in native_session.calls] == [
        "GET", "POST", "GET", "POST", "POST", "POST", "POST", "POST",
    ]
    assert native_session.headers["Authorization"] == "Bearer fictional-inner-token"


def test_injected_session_is_never_replaced_by_native_factory() -> None:
    """测试注入 session 时 _session_injected=True，native 切换不触发，factory 不被调用。"""
    session = FakeSession(successful_responses())

    def forbidden_factory() -> FakeSession:
        raise AssertionError("native factory should not be called when session injected")

    result = make_auth_client(
        session, native_session_factory=forbidden_factory
    ).login("fictional-user", "fictional-password-secret")
    assert result.session is session
