from __future__ import annotations

import gzip
import sys
import zlib
from http.cookiejar import Cookie
from types import SimpleNamespace
from typing import Any

import pytest

import services.windows_http as windows_http
from services.windows_http import WinHTTPError, WinHTTPSession, WinHTTPTimeoutError


def _make_cookie(
    name: str,
    value: str,
    *,
    domain: str,
    domain_specified: bool,
    domain_initial_dot: bool,
    path: str = "/",
    path_specified: bool = True,
    secure: bool = False,
    expires: int | None = None,
    discard: bool = False,
) -> Cookie:
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
        expires=expires,
        discard=discard,
        comment=None,
        comment_url=None,
        rest={},
        rfc2109=False,
    )


class FakeHandle:
    def __init__(self) -> None:
        self.options: dict[int, Any] = {}
        self.opened: tuple[str, str, bool] | None = None
        self.request_headers: list[tuple[str, str]] = []
        self.body: Any = None
        self.send_calls: list[tuple[Any, ...]] = []
        self.Status = 200
        self.ResponseBody = b'{"ok": true}'
        self.timeouts: tuple[int, int, int, int] | None = None
        self.response_headers_text = "Content-Type: application/json; charset=utf-8\r\n"

    def SetTimeouts(self, *values: int) -> None:
        self.timeouts = values  # type: ignore[assignment]

    def Open(self, method: str, url: str, asynchronous: bool) -> None:
        self.opened = method, url, asynchronous

    def SetOption(self, option: int, value: Any) -> None:
        self.options[option] = value

    def SetRequestHeader(self, name: str, value: str) -> None:
        self.request_headers.append((name, value))

    def Send(self, *args: Any) -> None:
        self.send_calls.append(args)
        self.body = args[0] if args else None

    def GetAllResponseHeaders(self) -> str:
        return self.response_headers_text


class FakePythonCom:
    def __init__(self) -> None:
        self.initialized = 0
        self.uninitialized = 0

    def CoInitialize(self) -> None:
        self.initialized += 1

    def CoUninitialize(self) -> None:
        self.uninitialized += 1


@pytest.fixture
def fake_com(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeHandle, FakePythonCom]:
    handle = FakeHandle()
    pythoncom = FakePythonCom()
    client = SimpleNamespace(Dispatch=lambda progid: handle)
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)
    monkeypatch.setitem(sys.modules, "win32com", SimpleNamespace(client=client))
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    return handle, pythoncom


def test_request_encodes_query_form_headers_and_redirect_option(fake_com) -> None:
    handle, pythoncom = fake_com
    session = WinHTTPSession()
    session.headers["Authorization"] = "Bearer fictional-token"
    response = session.post(
        "https://tdc.sgmw.com.cn/api?x=1",
        params={"a": ["b", "c"]},
        data={"q": "two words"},
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "isToken": "false",
        },
        timeout=1.5,
        allow_redirects=False,
    )

    assert handle.opened == ("POST", "https://tdc.sgmw.com.cn/api?x=1&a=b&a=c", False)
    assert handle.options == {6: False}
    assert handle.body == "q=two+words"
    assert ("Authorization", "Bearer fictional-token") in handle.request_headers
    assert ("isToken", "false") in handle.request_headers
    assert handle.timeouts == (1500, 1500, 1500, 1500)
    assert response.json() == {"ok": True}
    assert response.raise_for_status() is None
    assert pythoncom.initialized == pythoncom.uninitialized == 1


def test_binary_response_is_preserved(fake_com) -> None:
    handle, _ = fake_com
    handle.ResponseBody = b"PK\x03\x04\x00\xff"
    response = WinHTTPSession().get("https://tdc.sgmw.com.cn/export")
    assert response.content == b"PK\x03\x04\x00\xff"


def test_post_without_data_calls_send_without_a_body_argument(fake_com) -> None:
    handle, _ = fake_com

    WinHTTPSession().post(
        "https://tdc.sgmw.com.cn/auth/oauth/token",
        params={"token": "fictional-token"},
        data=None,
        headers={"isToken": "false"},
    )

    assert handle.send_calls == [()]


def test_timeout_tuple_only_extends_receive_phase(fake_com) -> None:
    handle, _ = fake_com

    WinHTTPSession().post("https://tdc.sgmw.com.cn/slow", timeout=(30, 240))

    assert handle.timeouts == (30000, 30000, 30000, 240000)


def test_com_timeout_code_maps_to_safe_timeout_error(fake_com) -> None:
    handle, _ = fake_com

    def fail(body: Any = None) -> None:
        raise RuntimeError(
            -2147352567,
            "fictional-password-secret",
            (0, "WinHttp.WinHttpRequest", "fictional-token-secret", None, 0, -2147012894),
            None,
        )

    handle.Send = fail

    with pytest.raises(WinHTTPTimeoutError, match="timed out") as excinfo:
        WinHTTPSession().get("https://tdc.sgmw.com.cn/private?token=fictional-query-secret")

    rendered = str(excinfo.value) + repr(excinfo.value)
    assert "fictional-password-secret" not in rendered
    assert "fictional-token-secret" not in rendered
    assert "fictional-query-secret" not in rendered


def test_gzip_response_is_decompressed_for_text_and_json(fake_com) -> None:
    handle, _ = fake_com
    handle.ResponseBody = gzip.compress(b'{"message": "ok"}')
    handle.response_headers_text = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: application/json; charset=utf-8\r\n"
        "Content-Encoding: gzip\r\n"
    )

    response = WinHTTPSession().get("https://tdc.sgmw.com.cn/data")

    assert response.content == b'{"message": "ok"}'
    assert response.text == '{"message": "ok"}'
    assert response.json() == {"message": "ok"}


@pytest.mark.parametrize("window_bits", [zlib.MAX_WBITS, -zlib.MAX_WBITS])
def test_deflate_response_accepts_wrapped_and_raw_streams(fake_com, window_bits: int) -> None:
    handle, _ = fake_com
    compressor = zlib.compressobj(wbits=window_bits)
    handle.ResponseBody = compressor.compress(b"<Result>ok</Result>") + compressor.flush()
    handle.response_headers_text = "Content-Encoding: deflate\r\nContent-Type: text/xml\r\n"

    response = WinHTTPSession().get("http://ecm.sgmw.com.cn/soap")

    assert response.text == "<Result>ok</Result>"


def test_corrupt_compressed_response_raises_safe_error(fake_com) -> None:
    handle, _ = fake_com
    handle.ResponseBody = b"fictional-response-secret"
    handle.response_headers_text = "Content-Encoding: gzip\r\n"

    with pytest.raises(WinHTTPError) as excinfo:
        WinHTTPSession().get("https://tdc.sgmw.com.cn/data")

    assert "fictional-response-secret" not in str(excinfo.value)


def test_decompressed_response_size_is_bounded(fake_com, monkeypatch: pytest.MonkeyPatch) -> None:
    handle, _ = fake_com
    monkeypatch.setattr(windows_http, "_MAX_DECOMPRESSED_BYTES", 32)
    handle.ResponseBody = gzip.compress(b"x" * 33)
    handle.response_headers_text = "Content-Encoding: gzip\r\n"

    with pytest.raises(WinHTTPError, match="size limit"):
        WinHTTPSession().get("https://tdc.sgmw.com.cn/data")


def test_response_raise_for_status_is_safe(fake_com) -> None:
    handle, _ = fake_com
    handle.Status = 401
    handle.ResponseBody = b'Authorization: Bearer fictional-token-secret'

    response = WinHTTPSession().get("https://tdc.sgmw.com.cn/private")

    with pytest.raises(WinHTTPError, match="HTTP 401") as excinfo:
        response.raise_for_status()
    assert "fictional-token-secret" not in str(excinfo.value)


def test_error_and_repr_do_not_leak_request_secrets(fake_com) -> None:
    handle, pythoncom = fake_com

    def fail(body: Any = None) -> None:
        raise RuntimeError("fictional-password-secret")

    handle.Send = fail
    session = WinHTTPSession()
    session.headers["Authorization"] = "Bearer fictional-token-secret"
    with pytest.raises(WinHTTPError) as excinfo:
        session.get("https://tdc.sgmw.com.cn/private?token=fictional-query-secret")
    rendered = str(excinfo.value) + repr(excinfo.value) + repr(session)
    assert "fictional-password-secret" not in rendered
    assert "fictional-token-secret" not in rendered
    assert "fictional-query-secret" not in rendered
    assert pythoncom.initialized == pythoncom.uninitialized == 1


def test_session_persists_cookies_across_requests(fake_com) -> None:
    """Set-Cookie 响应后，后续请求应携带 Cookie 头（OIDC 会话保持所必需）。"""
    handle, _pythoncom = fake_com
    session = WinHTTPSession()

    # 第一次请求：响应带 Set-Cookie
    handle.response_headers_text = (
        "Content-Type: text/html\r\n"
        "Set-Cookie: AUTH_SESSION_ID=abc123; Path=/; HttpOnly\r\n"
        "Set-Cookie: KC_RESTART=xyz; Path=/\r\n"
    )
    session.get("https://account.sgmw.com.cn/auth")
    assert session.cookies["AUTH_SESSION_ID"] == "abc123"
    assert session.cookies["KC_RESTART"] == "xyz"

    # 第二次请求：清空 request_headers 记录，验证 cookie 被回放
    handle.request_headers = []
    session.post("https://account.sgmw.com.cn/login", data={"u": "x"})
    cookie_headers = [v for n, v in handle.request_headers if n.lower() == "cookie"]
    assert cookie_headers, "Cookie 头应被注入到后续请求"
    assert "AUTH_SESSION_ID=abc123" in cookie_headers[0]
    assert "KC_RESTART=xyz" in cookie_headers[0]


def test_cookie_jar_enforces_host_path_and_secure_scope(fake_com) -> None:
    handle, _ = fake_com
    session = WinHTTPSession()
    handle.response_headers_text = (
        "HTTP/1.1 200 OK\r\n"
        "Set-Cookie: host_only=one; Path=/private\r\n"
        "Set-Cookie: shared=two; Domain=.sgmw.com.cn; Path=/; Secure\r\n"
    )
    session.get("https://account.sgmw.com.cn/private/login")
    handle.response_headers_text = "Content-Type: text/plain\r\n"

    handle.request_headers = []
    session.get("https://account.sgmw.com.cn/public")
    account_public = [value for name, value in handle.request_headers if name.lower() == "cookie"]
    assert account_public == ["shared=two"]

    handle.request_headers = []
    session.get("https://tdc.sgmw.com.cn/private")
    tdc_https = [value for name, value in handle.request_headers if name.lower() == "cookie"]
    assert tdc_https == ["shared=two"]

    handle.request_headers = []
    session.get("http://tdc.sgmw.com.cn/private")
    assert not [value for name, value in handle.request_headers if name.lower() == "cookie"]

    handle.request_headers = []
    session.get("https://unrelated.invalid/private")
    assert not [value for name, value in handle.request_headers if name.lower() == "cookie"]


def test_expired_cookie_is_removed(fake_com) -> None:
    handle, _ = fake_com
    session = WinHTTPSession()
    handle.response_headers_text = "Set-Cookie: sid=active; Path=/\r\n"
    session.get("https://account.sgmw.com.cn/login")
    assert session.cookies["sid"] == "active"

    handle.response_headers_text = "Set-Cookie: sid=gone; Path=/; Max-Age=0\r\n"
    session.get("https://account.sgmw.com.cn/logout")

    with pytest.raises(KeyError):
        _ = session.cookies["sid"]


# --- import_cookies: cross-session cookie continuity experiment ---


def test_import_cookies_migrates_parent_domain_cookie_for_tdc() -> None:
    """A Domain=.sgmw.com.cn Secure cookie is eligible for the TDC entry URL."""
    session = WinHTTPSession()
    shared = _make_cookie(
        "shared",
        "two",
        domain=".sgmw.com.cn",
        domain_specified=True,
        domain_initial_dot=True,
        secure=True,
    )
    count = session.import_cookies([shared], "https://tdc.sgmw.com.cn/tpc")

    assert count == 1
    assert session._cookie_header("https://tdc.sgmw.com.cn/tpc") == "shared=two"
    # Secure cookie is not sent over plain HTTP.
    assert session._cookie_header("http://tdc.sgmw.com.cn/tpc") == ""


def test_import_cookies_excludes_account_host_only_for_tdc() -> None:
    """account.sgmw.com.cn host-only cookies must not travel to tdc.sgmw.com.cn."""
    session = WinHTTPSession()
    host_only = _make_cookie(
        "AUTH_SESSION_ID",
        "abc",
        domain="account.sgmw.com.cn",
        domain_specified=False,
        domain_initial_dot=False,
    )
    count = session.import_cookies([host_only], "https://tdc.sgmw.com.cn/tpc")

    assert count == 0
    assert session._cookie_header("https://tdc.sgmw.com.cn/tpc") == ""


def test_import_cookies_excludes_path_and_secure_mismatches() -> None:
    session = WinHTTPSession()
    path_mismatch = _make_cookie(
        "p",
        "v",
        domain=".sgmw.com.cn",
        domain_specified=True,
        domain_initial_dot=True,
        path="/other",
        path_specified=True,
    )
    secure_only = _make_cookie(
        "s",
        "w",
        domain=".sgmw.com.cn",
        domain_specified=True,
        domain_initial_dot=True,
        secure=True,
    )
    count = session.import_cookies(
        [path_mismatch, secure_only], "http://tdc.sgmw.com.cn/tpc"
    )

    assert count == 0
    assert session._cookie_header("http://tdc.sgmw.com.cn/tpc") == ""


def test_import_cookies_preserves_attributes_not_downgraded_to_host_only() -> None:
    session = WinHTTPSession()
    shared = _make_cookie(
        "shared",
        "two",
        domain=".sgmw.com.cn",
        domain_specified=True,
        domain_initial_dot=True,
        path="/",
        path_specified=True,
        secure=True,
    )
    session.import_cookies([shared], "https://tdc.sgmw.com.cn/tpc")

    [cookie] = list(session._cookie_jar)
    assert cookie.domain == ".sgmw.com.cn"
    assert cookie.domain_specified is True
    assert cookie.domain_initial_dot is True
    assert cookie.path == "/"
    assert cookie.path_specified is True
    assert cookie.secure is True


def test_import_cookies_replays_migrated_cookie_on_subsequent_request(fake_com) -> None:
    handle, _ = fake_com
    handle.response_headers_text = "Content-Type: text/plain\r\n"
    session = WinHTTPSession()
    shared = _make_cookie(
        "shared",
        "two",
        domain=".sgmw.com.cn",
        domain_specified=True,
        domain_initial_dot=True,
        secure=True,
    )
    session.import_cookies([shared], "https://tdc.sgmw.com.cn/tpc")

    handle.request_headers = []
    session.get("https://tdc.sgmw.com.cn/tpc")
    cookie_headers = [v for n, v in handle.request_headers if n.lower() == "cookie"]
    assert cookie_headers == ["shared=two"]


def test_import_cookies_count_zero_is_valid_and_does_not_raise() -> None:
    session = WinHTTPSession()
    host_only = _make_cookie(
        "x",
        "y",
        domain="account.sgmw.com.cn",
        domain_specified=False,
        domain_initial_dot=False,
    )
    assert session.import_cookies([host_only], "https://tdc.sgmw.com.cn/tpc") == 0


def test_import_cookies_accepts_cookiejar_iterable(fake_com) -> None:
    handle, _ = fake_com
    # Build a jar by absorbing Set-Cookie headers from account.sgmw.com.cn.
    session = WinHTTPSession()
    handle.response_headers_text = (
        "Set-Cookie: shared=two; Domain=.sgmw.com.cn; Path=/; Secure\r\n"
        "Set-Cookie: host_only=one; Path=/\r\n"
    )
    session.get("https://account.sgmw.com.cn/auth")

    target = WinHTTPSession()
    count = target.import_cookies(session._cookie_jar, "https://tdc.sgmw.com.cn/tpc")

    assert count == 1
    assert target._cookie_header("https://tdc.sgmw.com.cn/tpc") == "shared=two"
