"""services.ibom_auth：统一身份认证登录 iBOM 的五步链路与防锁号约束。"""

from __future__ import annotations

import json
from urllib.parse import urlencode

import pytest

from services.ibom_auth import IBOMAuthError, IBOMPasswordAuthClient

IBOM = "https://ibom.sgmw.com.cn"
IDP = "https://account.sgmw.com.cn"
AUTH_PATH = "/auth/realms/common/protocol/openid-connect/auth"
CALLBACK = IBOM + "/fwSecurity/ssoAuth/login.api"
PASSWORD = "Pa55-SECRET"

LOGIN_PAGE = """<html><head><title>登录到 SGMW 认证中心</title></head><body>
<form id="kc-form-login" action="/auth/realms/common/login-actions/authenticate?session_code=S&amp;execution=E&amp;client_id=ibom-front&amp;tab_id=T" method="post">
<input name="username" type="text"><input name="password" type="password">
<input name="newokey" type="hidden" value=""><input name="eodpkey" type="hidden" value="">
<input name="feishukey" type="hidden" value=""><input name="phoneNumber" type="text">
<input name="code" type="text"><input name="credentialId" type="hidden" value="">
<input name="login" type="submit" value="登录"></form></body></html>"""


class R:
    def __init__(self, status=200, headers=None, text="", content=b""):
        self.status_code = status
        self.headers = headers or {}
        self.text = text
        self.content = content


def auth_location(**overrides):
    query = {"response_type": "code", "scope": "openid email phone", "client_id": "ibom-front",
             "state": "ibom-state", "redirect_uri": CALLBACK}
    query.update(overrides)
    return IDP + AUTH_PATH + "?" + urlencode(query)


def token_ok():
    return R(200, {"Content-Type": "application/json", "x-g-process-result": "success"},
             content=json.dumps({"state": "success", "data": {
                 "userToken": "TOKEN-xyz", "userLoginName": "u123", "loginType": "DEFAULT_SSO"}}).encode())


class Session:
    """按顺序回放响应；记录每次请求（不保留密码以外的任何东西也无妨，测试里会检查）。"""

    def __init__(self, gets, posts):
        self.gets = list(gets)
        self.posts = list(posts)
        self.log = []

    def get(self, url, headers=None, timeout=None, allow_redirects=None):
        self.log.append(("GET", url, None))
        assert allow_redirects is False
        return self.gets.pop(0)

    def post(self, url, data=None, headers=None, timeout=None, allow_redirects=None):
        self.log.append(("POST", url, data))
        assert allow_redirects is False
        return self.posts.pop(0)


def happy_session():
    return Session(
        gets=[
            R(302, {"Location": auth_location()}),
            R(200, text=LOGIN_PAGE),
            R(302, {"Location": "/"}),
            R(200, {"Content-Type": "text/html"}, text="<html></html>"),
        ],
        posts=[
            R(302, {"Location": CALLBACK + "?state=ibom-state&session_state=x&code=CODE-1"}),
            token_ok(),
        ],
    )


def client(session):
    return IBOMPasswordAuthClient(session=session, sleep=lambda _: None)


def test_login_happy_path_sends_password_once_and_returns_token():
    session = happy_session()
    result = client(session).login(" u123 ", PASSWORD)
    assert result.user_token == "TOKEN-xyz"
    assert result.user_login_name == "u123"
    assert "TOKEN-xyz" not in repr(result)
    password_posts = [entry for entry in session.log if entry[0] == "POST" and entry[2] and "password" in entry[2]]
    assert len(password_posts) == 1
    method, url, data = password_posts[0]
    assert url.startswith(IDP + "/auth/realms/common/login-actions/authenticate")
    assert data["username"] == "u123"
    for optional in ("newokey", "eodpkey", "feishukey", "phoneNumber", "code", "credentialId"):
        assert optional in data
    assert "login" not in data  # submit 按钮不进表单
    assert session.log[0] == ("GET", IBOM + "/fwPlatform/ssoAuth/login.api", None)
    assert session.log[-1][1] == IBOM + "/fwSecurity/authentication/checkToken.api"


@pytest.mark.parametrize("location", [
    "https://evil.example.com" + AUTH_PATH + "?client_id=ibom-front&state=s&redirect_uri=" + CALLBACK,
    IDP + "/other/path?client_id=ibom-front&state=s&redirect_uri=" + CALLBACK,
    auth_location(client_id="other-client"),
    auth_location(redirect_uri="https://evil.example.com/cb"),
    auth_location(state=""),
])
def test_sso_entry_validation_rejects_before_any_password(location):
    session = Session(gets=[R(302, {"Location": location})], posts=[])
    with pytest.raises(IBOMAuthError) as info:
        client(session).login("u", PASSWORD)
    assert info.value.stage == "sso-entry"
    assert info.value.credentials_sent is False
    assert not any(entry[0] == "POST" for entry in session.log)


def test_entry_without_redirect_is_rejected():
    session = Session(gets=[R(200, text="<html></html>")], posts=[])
    with pytest.raises(IBOMAuthError) as info:
        client(session).login("u", PASSWORD)
    assert info.value.stage == "sso-entry"


def test_login_form_must_post_to_identity_host():
    page = LOGIN_PAGE.replace('action="/auth/realms', 'action="https://evil.example.com/auth/realms')
    session = Session(gets=[R(302, {"Location": auth_location()}), R(200, text=page)], posts=[])
    with pytest.raises(IBOMAuthError) as info:
        client(session).login("u", PASSWORD)
    assert info.value.stage == "auth-discovery"
    assert not any(entry[0] == "POST" for entry in session.log)


def test_rejected_credentials_are_not_retried():
    session = Session(
        gets=[R(302, {"Location": auth_location()}), R(200, text=LOGIN_PAGE)],
        posts=[R(200, text=LOGIN_PAGE)],  # Keycloak 密码错误时回登录页
    )
    with pytest.raises(IBOMAuthError) as info:
        client(session).login("u", PASSWORD)
    assert info.value.stage == "auth-credentials"
    assert info.value.credentials_sent is True
    assert info.value.status_code == 200
    assert sum(1 for entry in session.log if entry[0] == "POST") == 1
    assert PASSWORD not in str(info.value)


def test_callback_must_return_to_ibom_with_code_and_state():
    for location in ("https://evil.example.com/cb?code=c&state=s", CALLBACK + "?state=s", CALLBACK + "?code=c"):
        session = Session(gets=[R(302, {"Location": auth_location()}), R(200, text=LOGIN_PAGE)],
                          posts=[R(302, {"Location": location})])
        with pytest.raises(IBOMAuthError) as info:
            client(session).login("u", PASSWORD)
        assert info.value.stage == "auth-credentials"
        assert sum(1 for entry in session.log if entry[0] == "POST") == 1


def test_callback_error_and_missing_session_fail_without_resending_password():
    session = Session(
        gets=[R(302, {"Location": auth_location()}), R(200, text=LOGIN_PAGE), R(500)],
        posts=[R(302, {"Location": CALLBACK + "?state=s&code=c"})],
    )
    with pytest.raises(IBOMAuthError) as info:
        client(session).login("u", PASSWORD)
    assert info.value.stage == "sso-callback"

    empty = R(200, {"x-g-process-result": "error"}, content=b"")
    session = Session(
        gets=[R(302, {"Location": auth_location()}), R(200, text=LOGIN_PAGE), R(200, text="ok")],
        posts=[R(302, {"Location": CALLBACK + "?state=s&code=c"}), empty, empty],
    )
    with pytest.raises(IBOMAuthError) as info:
        client(session).login("u", PASSWORD)
    assert info.value.stage == "check-token"
    assert info.value.credentials_sent is True
    password_posts = [entry for entry in session.log if entry[0] == "POST" and entry[2] and "password" in entry[2]]
    assert len(password_posts) == 1


def test_blank_credentials_never_touch_network():
    session = Session(gets=[], posts=[])
    for username, password in (("", PASSWORD), ("u", ""), ("u\x00x", PASSWORD)):
        with pytest.raises(IBOMAuthError) as info:
            client(session).login(username, password)
        assert info.value.stage == "credential-validation"
    assert session.log == []


def test_owned_session_is_closed_when_login_fails(monkeypatch):
    import services.ibom_auth as module

    closed = []

    class OwnSession(Session):
        def close(self):
            closed.append(True)

    session = OwnSession(gets=[R(302, {"Location": auth_location()}), R(200, text=LOGIN_PAGE)],
                         posts=[R(200, text=LOGIN_PAGE)])
    monkeypatch.setattr(module.requests, "Session", lambda: session)
    with pytest.raises(IBOMAuthError):
        IBOMPasswordAuthClient(sleep=lambda _: None).login("u", PASSWORD)
    assert closed == [True]
    injected = Session(gets=[R(200, text="x")], posts=[])
    with pytest.raises(IBOMAuthError):
        client(injected).login("u", PASSWORD)  # 调用方注入的会话由调用方管理，不关闭
