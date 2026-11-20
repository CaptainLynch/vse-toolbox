"""services.ibom_client：请求头/MD5、成功判定、计数与报表导出。"""

from __future__ import annotations

import hashlib
import json

import pytest

from services.ibom_client import (
    IBOM_CHECK_TOKEN_PATH,
    IBOM_DMM_EXPORT_PATH,
    IBOM_SMART_QUERY_PATH,
    IBOMClient,
    IBOMClientError,
    IBOMToken,
    check_token,
    content_md5,
    normalize_https_origin,
)

BASE = "https://ibom.sgmw.com.cn"
TOKEN = IBOMToken("tok-SECRET-123", "u12345")


class FakeResponse:
    def __init__(self, status=200, headers=None, content=b""):
        self.status_code = status
        self.headers = headers or {}
        self.content = content


def json_response(payload, *, process="success", status=200):
    return FakeResponse(status, {"Content-Type": "application/json", "x-g-process-result": process},
                        json.dumps(payload).encode("utf-8"))


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, data=None, headers=None, timeout=None, allow_redirects=None):
        self.calls.append({"url": url, "data": data, "headers": dict(headers or {}), "allow_redirects": allow_redirects})
        return self.responses.pop(0)


def test_content_md5_matches_utf8_body():
    body = '{"fieldName":"PROJECT_NAME","value":"中文"}'
    assert content_md5(body) == hashlib.md5(body.encode("utf-8")).hexdigest()
    assert content_md5("") == hashlib.md5(b"").hexdigest()


def test_normalize_origin_rejects_non_https_and_foreign_hosts():
    assert normalize_https_origin("https://IBOM.sgmw.com.cn/", "x") == BASE
    with pytest.raises(ValueError):
        normalize_https_origin("http://ibom.sgmw.com.cn", "x")
    with pytest.raises(ValueError):
        IBOMClient(FakeSession([]), TOKEN, base_url="https://evil.example.com")


def test_check_token_success_and_headers():
    session = FakeSession([json_response({"state": "success", "data": {
        "userToken": "tok-1", "userLoginName": "u1", "loginType": "DEFAULT_SSO"}})])
    token = check_token(session, BASE, sleep=lambda _: None)
    assert (token.user_token, token.user_login_name, token.login_type) == ("tok-1", "u1", "DEFAULT_SSO")
    call = session.calls[0]
    assert call["url"] == BASE + IBOM_CHECK_TOKEN_PATH
    assert call["data"] is None
    assert call["headers"]["x-content-md5"] == hashlib.md5(b"").hexdigest()
    assert call["headers"]["x-g-tenant-id"] == ""
    assert "usertoken" not in call["headers"]
    assert "tok-1" not in repr(token)


def test_check_token_retries_once_on_empty_body_then_fails():
    empty = FakeResponse(200, {"x-g-process-result": "error"}, b"")
    session = FakeSession([empty, json_response({"state": "success", "data": {"userToken": "t", "userLoginName": "u"}})])
    assert check_token(session, BASE, sleep=lambda _: None).user_token == "t"
    session = FakeSession([empty, empty])
    with pytest.raises(IBOMClientError) as info:
        check_token(session, BASE, sleep=lambda _: None)
    assert info.value.stage == "check-token"
    assert len(session.calls) == 2


@pytest.mark.parametrize("response", [
    FakeResponse(500, {}, b'{"state":"success"}'),
    json_response({"state": "success", "data": {"totalCount": 3}}, process="error"),
    FakeResponse(200, {}, b""),
    FakeResponse(200, {}, b"<html>login</html>"),
    json_response({"state": "error", "data": {"totalCount": 3}}),
    json_response({"state": "success", "data": {"totalCount": "3"}}),
])
def test_dmm_count_fails_closed(response):
    with pytest.raises(IBOMClientError):
        IBOMClient(FakeSession([response]), TOKEN).dmm_total_count()


def test_dmm_count_request_shape_and_auth_headers():
    session = FakeSession([json_response({"state": "success", "data": {"totalCount": 43, "content": []}})])
    assert IBOMClient(session, TOKEN).dmm_total_count() == 43
    call = session.calls[0]
    assert call["url"] == BASE + IBOM_SMART_QUERY_PATH
    body = call["data"].decode("utf-8")
    assert json.loads(body)["whereList"] == [{"fieldName": "DISCRIMINATOR", "operator": "EMPTY", "value": "DMM"}]
    headers = call["headers"]
    assert headers["x-content-md5"] == hashlib.md5(call["data"]).hexdigest()
    assert headers["usertoken"] == "tok-SECRET-123"
    assert headers["userloginname"] == "u12345"
    assert headers["logintype"] == "DEFAULT_SSO"
    assert headers["content-type"] == "application/json"
    assert call["allow_redirects"] is False


def test_export_dmm_report_returns_bytes_and_server_file_name():
    name = "数模设计审核流程报表_20261120.xlsx"
    from urllib.parse import quote
    response = FakeResponse(200, {
        "Content-Type": "application/x-download;charset=UTF-8",
        "Content-Disposition": f"inline; filename={quote(name)}",
    }, b"PK\x03\x04rest")
    export = IBOMClient(FakeSession([response]), TOKEN).export_dmm_report()
    assert export.content.startswith(b"PK")
    assert export.file_name == name
    assert export.byte_count == 8


@pytest.mark.parametrize("response", [
    FakeResponse(200, {"Content-Type": "application/json"}, b'{"state":"success"}'),
    FakeResponse(200, {"Content-Type": "application/x-download"}, b"<html>"),
    FakeResponse(302, {"Location": "https://account.sgmw.com.cn/"}, b""),
])
def test_export_dmm_report_rejects_non_xlsx(response):
    with pytest.raises(IBOMClientError):
        IBOMClient(FakeSession([response]), TOKEN).export_dmm_report()


def test_export_file_name_falls_back_on_unsafe_names():
    response = FakeResponse(200, {"Content-Type": "application/x-download",
                                  "Content-Disposition": "inline; filename=..%2F..%2Fevil.exe"}, b"PK..")
    assert IBOMClient(FakeSession([response]), TOKEN).export_dmm_report().file_name == "数模设计审核流程报表.xlsx"


def test_errors_never_contain_token():
    session = FakeSession([FakeResponse(500, {}, b"tok-SECRET-123")])
    with pytest.raises(IBOMClientError) as info:
        IBOMClient(session, TOKEN).dmm_total_count()
    assert "tok-SECRET-123" not in str(info.value)
    assert IBOM_DMM_EXPORT_PATH.startswith("/bommgmt/")
