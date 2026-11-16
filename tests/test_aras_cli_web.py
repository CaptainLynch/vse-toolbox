from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

import web.app as web_app
import web.crawler_boot as crawler_boot
from services.aras_auth import ArasAuthError
from services.aras_crawler import (
    ArasAuthenticationError,
    ArasCrawlerError,
    ArasNcrExportContractError,
    EWOReportPage,
    PAAReportPage,
)
from services.windows_http import WinHTTPError, WinHTTPTimeoutError


@dataclass
class FakeProgress:
    file_id: str = "FILE-secret2"
    file_name: str = "progress.xlsx"
    record_id: str = "REC-1"


@dataclass
class FakeDetail:
    file_name: str = "detail.xlsx"


class FakeArasClient:
    calls: list[dict[str, object]] = []
    fail: Exception | None = None
    rows: list[dict[str, object]] | None = None
    detail_file_name: str = "detail.xlsx"

    def __init__(self, base_url, headers=None, cookies=None, session=None, timeout=30.0, diagnostic_hook=None):  # type: ignore[no-untyped-def]
        self.base_url = base_url
        self.headers = headers or {}
        self.cookies = cookies
        self.session = session
        self.timeout = timeout
        self.diagnostic_hook = diagnostic_hook
        self.__class__.calls.append(
            {
                "base_url": base_url,
                "headers": self.headers,
                "cookies": cookies,
                "session": session,
                "timeout": timeout,
                "diagnostic_hook": diagnostic_hook,
            }
        )

    def query_ewo_report(self, filters, page=1, page_size=50, max_records=2000):  # type: ignore[no-untyped-def]
        if self.fail:
            raise self.fail
        self.__class__.calls.append(
            {"method": "ewo", "filters": filters, "page": page, "page_size": page_size, "max_records": max_records}
        )
        rows = self.__class__.rows
        if rows is None:
            rows = [
                {
                    "_no": "EWO-1",
                    "_sort_sub_type": "PWO-EWO定点",
                    "created_by_id__keyed_name": "Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3 Authorization: Bearer xyz789",
                    "state": "Open",
                    "note": "Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3 Authorization: Bearer xyz789",
                    "cookie": "sid=secret-cookie",
                    "raw_xml": "<secret-xml/>",
                }
            ]
        return EWOReportPage(
            rows=rows,
            page=page,
            item_ids=["ID-1"],
            raw_xml="<xml/>",
        )

    def crawl_ewo_report_all(self, filters, page_size=50, max_pages=40, max_records=2000, should_stop=None, on_page=None):  # type: ignore[no-untyped-def]
        if self.fail:
            raise self.fail
        self.__class__.calls.append(
            {
                "method": "ewo_all",
                "filters": filters,
                "page_size": page_size,
                "max_pages": max_pages,
                "max_records": max_records,
            }
        )
        return EWOReportPage(
            rows=[{"_no": "EWO-1", "eplmwriteneplcode": "F610S", "state": "Open"}],
            page=1,
            item_ids=["A" * 32],
            raw_xml="<xml/>",
            complete=True,
        )

    def query_paa_report(self, filters, page=1, page_size=50, max_records=2000):  # type: ignore[no-untyped-def]
        if self.fail:
            raise self.fail
        self.__class__.calls.append(
            {"method": "paa", "filters": filters, "page": page, "page_size": page_size, "max_records": max_records}
        )
        rows = self.__class__.rows
        if rows is None:
            rows = [
                {
                    "_no": "PAA-1",
                    "_auth_type": "Open",
                    "created_by_id__keyed_name": "Set-Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3 Authorization: Bearer xyz789",
                    "state": "Open",
                    "note": "Set-Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3 Authorization: Bearer xyz789",
                    "cookie": "sid=secret-cookie",
                    "raw_xml": "<secret-xml/>",
                }
            ]
        return PAAReportPage(
            rows=rows,
            page=page,
            item_ids=["PAA-ID-1"],
            raw_xml="<xml/>",
        )

    def crawl_paa_report_all(self, filters, page_size=50, max_pages=20, max_records=2000, should_stop=None, on_page=None):  # type: ignore[no-untyped-def]
        if self.fail:
            raise self.fail
        self.__class__.calls.append(
            {
                "method": "paa_all",
                "filters": filters,
                "page_size": page_size,
                "max_pages": max_pages,
                "max_records": max_records,
            }
        )
        return PAAReportPage(
            rows=[
                {
                    "_no": "PAA-2",
                    "_auth_type": "Closed",
                    "created_by_id__keyed_name": "Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3 Authorization: Bearer xyz789 token=tok123",
                    "state": "Closed",
                    "note": "Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3 Authorization: Bearer xyz789 token=tok123",
                    "raw_xml": "<secret-xml/>",
                }
            ],
            page=2,
            item_ids=["PAA-ID-2"],
            raw_xml="<xml/>",
        )

    def query_ncr_approval_progress(self, filters):  # type: ignore[no-untyped-def]
        if self.fail:
            raise self.fail
        self.__class__.calls.append({"method": "progress", "filters": filters})
        return FakeProgress()

    def extract_ncr_approval_detail(self, filters):  # type: ignore[no-untyped-def]
        if self.fail:
            raise self.fail
        self.__class__.calls.append({"method": "detail", "filters": filters})
        return FakeDetail(file_name=self.__class__.detail_file_name)

    def download_ncr_detail_file(self, file_name, destination):  # type: ignore[no-untyped-def]
        if self.fail:
            raise self.fail
        self.__class__.calls.append(
            {"method": "ncr_download", "file_name": file_name, "destination": destination}
        )
        target = Path(destination) / file_name
        target.write_bytes(b"NCR-DETAIL-CONTENT")
        return target

    def download_ncr_progress_file(self, export_result, destination):  # type: ignore[no-untyped-def]
        if self.fail:
            raise self.fail
        self.__class__.calls.append(
            {
                "method": "ncr_progress_download",
                "file_name": export_result.file_name,
                "destination": destination,
            }
        )
        target = Path(destination) / export_result.file_name
        target.write_bytes(b"NCR-PROGRESS-CONTENT")
        return target


class FakeWebAuthClient:
    calls: list[dict[str, object]] = []
    fail: Exception | None = None
    session = object()

    def __init__(self, base_url, timeout=30.0, diagnostic_hook=None):  # type: ignore[no-untyped-def]
        self.__class__.calls.append({"base_url": base_url, "timeout": timeout, "diagnostic_hook": diagnostic_hook})

    def login(self, username, password):  # type: ignore[no-untyped-def]
        self.__class__.calls.append({"username": username, "password": password})
        if self.fail:
            raise self.fail
        return SimpleNamespace(session=self.session)


def _make_test_client(monkeypatch, tmp_path, allowed_hosts=None):  # type: ignore[no-untyped-def]
    FakeArasClient.calls = []
    FakeArasClient.fail = None
    FakeArasClient.rows = None
    FakeArasClient.detail_file_name = "detail.xlsx"
    monkeypatch.setattr(crawler_boot, "ArasCrawlerClient", FakeArasClient)
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "web-test.db"))
    monkeypatch.setattr(crawler_boot, "DIAGNOSTIC_DIR", tmp_path / "diagnostics")
    app = web_app.create_app(allowed_hosts=allowed_hosts)
    app.config.update(TESTING=True)
    # 统一域账号登录后，路由测试默认处于「已建立共享域会话」的状态。
    registry = app.extensions.get("domain_sessions")
    if isinstance(registry, web_app.DomainSessionRegistry):
        registry.mark_authenticated("aras", object())
        registry.mark_authenticated("tdc", object())
    return app.test_client()


@pytest.fixture()
def client(monkeypatch, tmp_path):
    # aras.example 仅通过 create_app(allowed_hosts=...) 注入，供既有路由契约测试使用
    return _make_test_client(monkeypatch, tmp_path, allowed_hosts=["aras.example"])


def test_ewo_route_contract_and_no_auth_echo(client) -> None:
    resp = client.post(
        "/api/aras/ewo/query",
        json={
            "base_url": "http://aras.example",
            "headers": {"X-Test": "yes", "Authorization": "secret-auth"},
            "cookie": "sid=secret-cookie",
            "filters": {"ewo_no": "EWO-1", "project_code": "F610S"},
            "page": 2,
            "page_size": 25,
            "max_records": 100,
        },
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    data = payload["data"]
    assert "headerRows" in data
    assert "columns" in data
    assert data["defaultVisibleCount"] == 12
    assert data["page"] == 2
    assert data["item_ids"] == ["ID-1"]
    assert data["count"] == 1
    assert data["rows"][0][:3] == ["EWO-1", "EWO定点", "Cookie: [redacted] Authorization: [redacted]"]
    init_call = FakeArasClient.calls[0]
    assert init_call["base_url"] == "http://aras.example"
    assert init_call["headers"]["Cookie"] == "sid=secret-cookie"  # type: ignore[index]
    assert "secret-cookie" not in resp.get_data(as_text=True)
    assert "secret-auth" not in resp.get_data(as_text=True)
    assert "abc123" not in resp.get_data(as_text=True)
    assert "secret2" not in resp.get_data(as_text=True)
    assert "secret3" not in resp.get_data(as_text=True)
    assert "xyz789" not in resp.get_data(as_text=True)
    assert "raw_xml" not in resp.get_data(as_text=True)
    assert "<secret-xml/>" not in resp.get_data(as_text=True)
    method_call = FakeArasClient.calls[1]
    assert method_call["page"] == 2
    assert method_call["page_size"] == 25
    assert method_call["max_records"] == 100
    assert method_call["filters"].ewo_no == "EWO-1"


def test_ewo_route_can_return_sanitized_request_and_response_xml(client, monkeypatch) -> None:
    request_xml = (
        '<SOAP-ENV:Envelope><SOAP-ENV:Body><ApplyItem><Item type="EWO_O" action="get">'
        "<_no>EWO-1</_no></Item></ApplyItem></SOAP-ENV:Body></SOAP-ENV:Envelope>"
    )
    response_xml = (
        '<SOAP-ENV:Envelope><Result><Item type="EWO_O"><_no>EWO-1</_no>'
        "<token>fictional-token-secret</token></Item></Result></SOAP-ENV:Envelope>"
    )

    def query_with_xml(*args, **kwargs):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            rows=[{"_no": "EWO-1"}],
            page=1,
            item_ids=["ID-1"],
            raw_xml=response_xml,
            request_xml=request_xml,
        )

    monkeypatch.setattr(FakeArasClient, "query_ewo_report", query_with_xml)
    response = client.post(
        "/api/aras/ewo/query",
        json={
            "base_url": "http://aras.example",
            "include_xml": True,
            "filters": {},
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    xml = body["data"]["xml"]
    assert xml["requestXml"] == request_xml
    assert "<Result>" in xml["responseXml"]
    assert "EWO-1" in xml["responseXml"]
    assert "fictional-token-secret" not in response.get_data(as_text=True)
    assert "<token>[redacted]</token>" in xml["responseXml"]


def test_paa_route_can_return_sanitized_request_and_response_xml(client, monkeypatch) -> None:
    request_xml = '<Envelope><ApplyItem><Item type="PAA_O" action="get" /></ApplyItem></Envelope>'
    response_xml = '<Envelope><Result><Item type="PAA_O"><_no>PAA-1</_no></Item></Result></Envelope>'

    def query_with_xml(*args, **kwargs):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            rows=[{"_no": "PAA-1"}],
            page=1,
            item_ids=["ID-1"],
            raw_xml=response_xml,
            request_xml=request_xml,
        )

    monkeypatch.setattr(FakeArasClient, "query_paa_report", query_with_xml)
    response = client.post(
        "/api/aras/paa/query",
        json={
            "base_url": "http://aras.example",
            "include_xml": True,
            "filters": {},
        },
    )

    assert response.status_code == 200
    xml = response.get_json()["data"]["xml"]
    assert xml["requestXml"] == request_xml
    assert "PAA-1" in xml["responseXml"]


def test_web_password_auth_injects_authenticated_session_without_echo(monkeypatch, tmp_path) -> None:
    FakeWebAuthClient.calls = []
    FakeWebAuthClient.fail = None
    monkeypatch.setattr(crawler_boot, "ArasECMAuthClient", FakeWebAuthClient)
    test_client = _make_test_client(monkeypatch, tmp_path, allowed_hosts=["aras.example"])

    resp = test_client.post(
        "/api/aras/ewo/query",
        json={
            "base_url": "http://aras.example",
            "auth_mode": "password",
            "username": "fictional-user",
            "password": "fictional-password-secret",
            "headers": {"X-Test": "yes"},
            "filters": {},
        },
    )

    assert resp.status_code == 200
    assert FakeWebAuthClient.calls[-1] == {
        "username": "fictional-user",
        "password": "fictional-password-secret",
    }
    assert FakeArasClient.calls[0]["session"] is FakeWebAuthClient.session
    assert FakeArasClient.calls[0]["headers"] == {"X-Test": "yes"}
    assert callable(FakeArasClient.calls[0]["diagnostic_hook"])
    body = resp.get_data(as_text=True)
    assert "fictional-user" not in body
    assert "fictional-password-secret" not in body


def test_web_password_auth_failure_is_401_and_secret_modes_cannot_mix(monkeypatch, tmp_path) -> None:
    FakeWebAuthClient.calls = []
    FakeWebAuthClient.fail = ArasAuthError("ECM identity rejected credentials", stage="ecm-credentials")
    monkeypatch.setattr(crawler_boot, "ArasECMAuthClient", FakeWebAuthClient)
    test_client = _make_test_client(monkeypatch, tmp_path, allowed_hosts=["aras.example"])

    failed = test_client.post(
        "/api/aras/ewo/query",
        json={
            "base_url": "http://aras.example",
            "auth_mode": "password",
            "username": "fictional-user",
            "password": "fictional-password-secret",
            "filters": {},
        },
    )
    assert failed.status_code == 401
    assert failed.get_json()["error"]["type"] == "AuthenticationError"
    assert "fictional-password-secret" not in failed.get_data(as_text=True)
    # 认证失败生成诊断报告：路径透传为 .md 且文件真实落盘，不含 secret
    diag_path = failed.get_json()["error"].get("diagnosticPath")
    assert isinstance(diag_path, str) and diag_path.endswith(".md")
    assert Path(diag_path).is_file()
    assert "fictional-password-secret" not in Path(diag_path).read_text(encoding="utf-8")

    mixed = test_client.post(
        "/api/aras/ewo/query",
        json={
            "base_url": "http://aras.example",
            "auth_mode": "password",
            "username": "fictional-user",
            "password": "fictional-password-secret",
            "cookie": "sid=fictional-cookie",
            "filters": {},
        },
    )
    assert mixed.status_code == 400
    assert mixed.get_json()["error"]["type"] == "AuthenticationModeConflict"


def test_web_password_crawler_failure_saves_detailed_diagnostic(monkeypatch, tmp_path) -> None:
    FakeWebAuthClient.calls = []
    FakeWebAuthClient.fail = None
    monkeypatch.setattr(crawler_boot, "ArasECMAuthClient", FakeWebAuthClient)

    def fail_with_invalid_xml(self, filters, page=1, page_size=50, max_records=2000):  # type: ignore[no-untyped-def]
        assert callable(self.diagnostic_hook)
        self.diagnostic_hook(
            SimpleNamespace(
                stage="soap-ApplyItem",
                method="POST",
                url="http://aras.example/innovatorserver/Server/InnovatorServer.aspx",
                elapsed_ms=12.5,
                status_code=200,
                reason="OK",
                request_headers={"Authorization": "Bearer fictional-token-secret"},
                response_headers={"Content-Type": "text/html"},
                response_body="<html>not valid XML token=fictional-token-secret</html>",
            )
        )
        raise ArasCrawlerError("XML response is not valid")

    monkeypatch.setattr(FakeArasClient, "query_ewo_report", fail_with_invalid_xml)
    test_client = _make_test_client(monkeypatch, tmp_path, allowed_hosts=["aras.example"])

    failed = test_client.post(
        "/api/aras/ewo/query",
        json={
            "base_url": "http://aras.example",
            "auth_mode": "password",
            "username": "fictional-user",
            "password": "fictional-password-secret",
            "filters": {},
        },
    )

    assert failed.status_code == 502
    body = failed.get_json()
    assert body["error"]["type"] == "ArasCrawlerError"
    diagnostic_path = body["error"].get("diagnosticPath")
    assert isinstance(diagnostic_path, str) and diagnostic_path.endswith(".md")
    report_text = Path(diagnostic_path).read_text(encoding="utf-8")
    assert "Aras WebUI Diagnostic" in report_text
    assert "soap-ApplyItem" in report_text
    assert "XML response is not valid" in report_text
    assert "not valid XML" in report_text
    assert "fictional-password-secret" not in report_text
    assert "fictional-token-secret" not in report_text


def test_ncr_progress_and_detail_routes(client) -> None:
    common = {
        "base_url": "http://aras.example",
        "filters": {
            "buy_start": "2026-01-01",
            "project_names": ["F610S", "F610S DG"],
            "othercondition": "1",
        },
    }

    progress = client.post("/api/aras/ncr/progress", json=common)
    detail = client.post("/api/aras/ncr/detail", json=common)

    assert progress.status_code == 200
    p_data = progress.get_json()["data"]
    assert p_data["file_name"] == "progress.xlsx"
    assert p_data["record_id"] == "REC-1"
    assert "headerRows" in p_data
    assert "columns" in p_data
    assert p_data["rows"] == []
    assert p_data["defaultVisibleCount"] == 12
    assert "file_id" not in progress.get_data(as_text=True)
    assert "FILE-secret2" not in progress.get_data(as_text=True)
    assert "secret2" not in progress.get_data(as_text=True)
    assert detail.status_code == 200
    d_data = detail.get_json()["data"]
    assert d_data["file_name"] == "detail.xlsx"
    assert "headerRows" in d_data
    assert "columns" in d_data
    assert d_data["rows"] == []
    assert d_data["defaultVisibleCount"] == 17
    progress_call = next(call for call in FakeArasClient.calls if call.get("method") == "progress")
    assert progress_call["filters"].project_names == ("F610S", "F610S DG")
    assert progress_call["filters"].othercondition == "1"


def test_paa_routes_contract_and_no_auth_echo(client) -> None:
    query = client.post(
        "/api/aras/paa/query",
        json={
            "base_url": "http://aras.example",
            "headers": {"Authorization": "secret-auth"},
            "cookie": "sid=secret-cookie",
            "filters": {
                "paa_no": "PAA-1",
                "ewo_no": "EWO-1",
                "state": "Open",
                "area": "PT",
                "base": "Base-A",
                "vehicle_keyword": "Vehicle",
                "submit_start": "2026-01-01",
                "submit_end": "2026-01-31",
                "mtl_rq_start": "2026-02-01",
                "mtl_rq_end": "2026-02-28",
            },
            "page": 3,
            "page_size": 25,
            "max_records": 100,
        },
    )
    crawl = client.post(
        "/api/aras/paa/crawl-all",
        json={
            "base_url": "http://aras.example",
            "headers": {"Authorization": "secret-auth"},
            "cookie": "sid=secret-cookie",
            "filters": {"paa_no": "PAA-2"},
            "page_size": 40,
            "max_pages": 6,
            "max_records": 120,
        },
    )

    assert query.status_code == 200
    query_data = query.get_json()["data"]
    assert "headerRows" in query_data
    assert "columns" in query_data
    assert query_data["defaultVisibleCount"] == 12
    assert query_data["rows"][0][:3] == [
        "PAA-1",
        "Open",
        "Set-Cookie: [redacted] Authorization: [redacted]",
    ]
    assert query_data["page"] == 3
    # 全量抓取已异步化：携带凭据的请求被凭据红线直接拒绝（凭据零入库、零回显）
    assert crawl.status_code == 400
    crawl_error = crawl.get_json()["error"]
    assert crawl_error["type"] == "AsyncAuthUnsupported"
    crawl_text = crawl.get_data(as_text=True)
    assert "secret-cookie" not in crawl_text
    assert "secret-auth" not in crawl_text
    query_call = next(call for call in FakeArasClient.calls if call.get("method") == "paa")
    assert query_call["filters"].paa_no == "PAA-1"
    assert query_call["filters"].mtl_rq_end == "2026-02-28"
    assert query_call["page"] == 3
    # 凭据红线拒绝后不得有任何抓取调用发生
    assert not any(call.get("method") == "paa_all" for call in FakeArasClient.calls)
    assert "secret-cookie" not in query.get_data(as_text=True)
    assert "secret-auth" not in query.get_data(as_text=True)
    assert "abc123" not in query.get_data(as_text=True)
    assert "secret2" not in query.get_data(as_text=True)
    assert "secret3" not in query.get_data(as_text=True)
    assert "xyz789" not in query.get_data(as_text=True)
    assert "raw_xml" not in query.get_data(as_text=True)
    assert "secret-cookie" not in crawl.get_data(as_text=True)
    assert "secret-auth" not in crawl.get_data(as_text=True)
    assert "abc123" not in crawl.get_data(as_text=True)
    assert "tok123" not in crawl.get_data(as_text=True)
    assert "secret2" not in crawl.get_data(as_text=True)
    assert "secret3" not in crawl.get_data(as_text=True)
    assert "xyz789" not in crawl.get_data(as_text=True)
    assert "raw_xml" not in crawl.get_data(as_text=True)


def test_ewo_query_marks_zero_rows_as_empty(client) -> None:
    FakeArasClient.rows = []

    response = client.post(
        "/api/aras/ewo/query",
        json={"base_url": "http://aras.example", "filters": {}},
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["queryState"] == "empty"


def test_paa_query_marks_rows_as_matched(client) -> None:
    response = client.post(
        "/api/aras/paa/query",
        json={"base_url": "http://aras.example", "filters": {}},
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["queryState"] == "matched"


def test_paa_query_marks_zero_rows_as_empty(client) -> None:
    FakeArasClient.rows = []

    response = client.post(
        "/api/aras/paa/query",
        json={"base_url": "http://aras.example", "filters": {}},
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["queryState"] == "empty"


@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (ArasAuthenticationError("login page token=fictional-token"), 401, "unauthenticated"),
        (WinHTTPError("transport failed token=fictional-token"), 503, "service_unavailable"),
        (WinHTTPTimeoutError("transport timeout token=fictional-token"), 503, "service_unavailable"),
        (ArasCrawlerError("XML response is not valid token=fictional-token"), 502, "query_failed"),
    ],
)
def test_ewo_query_exposes_stable_interactive_error_code(
    client, failure: Exception, status: int, code: str
) -> None:
    FakeArasClient.fail = failure

    response = client.post(
        "/api/aras/ewo/query",
        json={"base_url": "http://aras.example", "filters": {}},
    )

    assert response.status_code == status
    body = response.get_json()
    assert body["error"]["code"] == code
    assert "fictional-token" not in response.get_data(as_text=True)


@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (ArasAuthenticationError("login page token=fictional-token"), 401, "unauthenticated"),
        (WinHTTPError("transport failed token=fictional-token"), 503, "service_unavailable"),
        (ArasCrawlerError("XML response is not valid token=fictional-token"), 502, "query_failed"),
    ],
)
def test_paa_query_exposes_stable_interactive_error_code(
    client, failure: Exception, status: int, code: str
) -> None:
    FakeArasClient.fail = failure

    response = client.post(
        "/api/aras/paa/query",
        json={"base_url": "http://aras.example", "filters": {}},
    )

    assert response.status_code == status
    body = response.get_json()
    assert body["error"]["code"] == code
    assert "fictional-token" not in response.get_data(as_text=True)


def test_aras_browser_query_without_server_session_is_unauthenticated(
    monkeypatch, tmp_path
) -> None:
    client = _make_test_client(monkeypatch, tmp_path, allowed_hosts=["aras.example"])
    registry = client.application.extensions["domain_sessions"]
    registry.clear("aras")

    response = client.post(
        "/api/aras/ewo/query",
        json={"base_url": "http://aras.example", "auth_mode": "browser", "filters": {}},
    )

    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "unauthenticated"


def test_aras_browser_query_reuses_authenticated_server_session(monkeypatch, tmp_path) -> None:
    client = _make_test_client(monkeypatch, tmp_path, allowed_hosts=["aras.example"])
    registry = client.application.extensions["domain_sessions"]
    shared_session = object()
    registry.mark_authenticated("aras", shared_session)

    response = client.post(
        "/api/aras/ewo/query",
        json={"base_url": "http://aras.example", "auth_mode": "browser", "filters": {}},
    )

    assert response.status_code == 200
    assert FakeArasClient.calls[0]["session"] is shared_session


def test_host_allowlist_default_rejects_unknown_host_without_echoing_credentials(
    monkeypatch, tmp_path
) -> None:
    default_client = _make_test_client(monkeypatch, tmp_path)
    resp = default_client.post(
        "/api/aras/ewo/query",
        json={
            "base_url": "http://evil.example/innovatorserver",
            "headers": {"Authorization": "secret-auth"},
            "cookie": "sid=secret-cookie",
            "filters": {},
        },
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert resp.get_json()["error"]["type"] == "HostNotAllowed"
    assert "secret-cookie" not in body
    assert "secret-auth" not in body
    assert FakeArasClient.calls == []  # client 从未构造，allowlist 在构造前拒绝


def test_host_allowlist_normalizes_case_port_and_scheme(monkeypatch, tmp_path) -> None:
    default_client = _make_test_client(monkeypatch, tmp_path)
    for url in [
        "https://ecm.sgmw.com.cn/innovatorserver",
        "HTTPS://ECM.SGMW.COM.CN:443/innovatorserver",
        "http://ecm.sgmw.com.cn:80/innovatorserver",
        "http://ecm.sgmw.com.cn:8080/innovatorserver",
    ]:
        resp = default_client.post("/api/aras/ewo/query", json={"base_url": url, "filters": {}})
        assert resp.status_code == 200, url
    for url in [
        "http://user:pass@ecm.sgmw.com.cn/innovatorserver",  # userinfo
        "ftp://ecm.sgmw.com.cn/innovatorserver",  # 非 http(s)
        "https://aras.example/innovatorserver",  # 任意主机
        "https://ecm.sgmw.com.cn:99999/innovatorserver",  # 非法端口
    ]:
        resp = default_client.post("/api/aras/ewo/query", json={"base_url": url, "filters": {}})
        assert resp.status_code == 400, url


def test_host_allowlist_injectable_via_app_config(monkeypatch, tmp_path) -> None:
    FakeArasClient.calls = []
    FakeArasClient.fail = None
    FakeArasClient.detail_file_name = "detail.xlsx"
    monkeypatch.setattr(crawler_boot, "ArasCrawlerClient", FakeArasClient)
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "web-test.db"))
    app = web_app.create_app()  # 默认仅 ecm.sgmw.com.cn
    app.config["ARAS_ALLOWED_HOSTS"] = ("aras.example",)  # 运行前注入测试 host
    app.config.update(TESTING=True)
    registry = app.extensions.get("domain_sessions")
    if isinstance(registry, web_app.DomainSessionRegistry):
        registry.mark_authenticated("aras", object())
    test_client = app.test_client()

    allowed = test_client.post("/api/aras/paa/query", json={"base_url": "http://aras.example", "filters": {}})
    assert allowed.status_code == 200
    rejected = test_client.post("/api/aras/paa/query", json={"base_url": "http://localhost", "filters": {}})
    assert rejected.status_code == 400
    assert rejected.get_json()["error"]["type"] == "HostNotAllowed"


def test_paa_department_filter_normalizes_and_fails_closed(client) -> None:
    ok = client.post(
        "/api/aras/paa/query",
        json={
            "base_url": "http://aras.example",
            "filters": {"department": "技术中心-车体工程, 技术中心_车体工程"},
        },
    )
    assert ok.status_code == 200
    assert FakeArasClient.calls[-1]["filters"].department == "技术中心_车体工程"

    blank = client.post(
        "/api/aras/paa/query",
        json={"base_url": "http://aras.example", "filters": {"department": ""}},
    )
    assert blank.status_code == 200
    assert FakeArasClient.calls[-1]["filters"].department is None

    unknown = client.post(
        "/api/aras/paa/query",
        json={"base_url": "http://aras.example", "filters": {"department": "未知部门"}},
    )
    assert unknown.status_code == 400
    assert unknown.get_json()["error"]["type"] == "ValidationError"
    assert FakeArasClient.calls[-1].get("method") is None  # 未发起查询

    fuzzy = client.post(
        "/api/aras/paa/query",
        json={
            "base_url": "http://aras.example",
            "filters": {"department": "*车体工程*|*整车*"},
        },
    )
    assert fuzzy.status_code == 200
    assert FakeArasClient.calls[-1]["filters"].department == "*车体工程*|*整车*"


def _wait_for_background_task(client, task_id: str, timeout: float = 10.0) -> dict:
    import time as _time

    deadline = _time.time() + timeout
    while _time.time() < deadline:
        resp = client.get(f"/api/tasks/{task_id}")
        assert resp.status_code == 200
        task = resp.get_json()["data"]
        if not task["is_active"]:
            return task
        _time.sleep(0.05)
    raise AssertionError("background task did not finish in time")


def _column_letters(index: int) -> str:
    letters = ""
    value = index + 1
    while value:
        value, remainder = divmod(value - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _write_official_workbook(path: Path) -> Path:
    """合成官方 EWO 工作簿（111 契约表头 + 1 行，值带标签前缀便于验证列语义）。"""
    import zipfile
    from xml.sax.saxutils import escape

    from core.report_contracts import report_contracts

    labels = [str(value or "").strip() for value in report_contracts()["ewo"]["headerRows"][0]]
    row = [f"{label}|EWO-1" for label in labels]
    row[0] = "EWO-1"
    strings: list[str] = []
    lookup: dict[str, int] = {}

    def sid(text: str) -> int:
        if text not in lookup:
            lookup[text] = len(strings)
            strings.append(text)
        return lookup[text]

    sheet_rows = []
    for row_index, values in enumerate([labels] + [row], start=1):
        cells = [
            f'<c r="{_column_letters(column)}{row_index}" t="s"><v>{sid(str(value))}</v></c>'
            for column, value in enumerate(values)
        ]
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Innovator" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    shared = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(strings)}" uniqueCount="{len(strings)}">'
        + "".join(f"<si><t>{escape(text)}</t></si>" for text in strings)
        + "</sst>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/sharedStrings.xml", shared)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return path


class FakeOfficialTransport:
    """官方导出 transport 替身：生成返回固定 file_id，下载落到合成工作簿。"""

    generate_calls = 0

    def __init__(self, client):  # type: ignore[no-untyped-def]
        self.client = client

    def generate(self, ids):  # type: ignore[no-untyped-def]
        type(self).generate_calls += 1
        assert ids == ["A" * 32]
        return "B" * 32

    def download(self, file_id, destination):  # type: ignore[no-untyped-def]
        return _write_official_workbook(Path(destination) / "official.xlsx")


def test_ewo_export_rejects_when_concurrency_limit_reached(monkeypatch, tmp_path) -> None:
    """并发上限按 purpose 计：已有 2 个 csv_export 在途时拒绝新导出。"""
    from core.ewo_export_jobs import EWOExportJobs

    test_client = _make_test_client(monkeypatch, tmp_path, allowed_hosts=["aras.example"])
    jobs = EWOExportJobs(tmp_path / "web-test.db")
    for index in range(2):
        jobs.create("scope-a", [f"{index + 1:032X}"], purpose="csv_export")
    monkeypatch.setattr(crawler_boot, "EWOExportTransport", FakeOfficialTransport)
    resp = test_client.post(
        "/api/aras/ewo/export",
        json={"base_url": "http://aras.example", "filters": {}},
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"]["type"] == "ExportBusy"


def test_ewo_export_route_creates_official_csv_artifact(client, monkeypatch) -> None:
    """主路由已切到官方工作簿：202 带 ewo_<jobId>，下载件 111 列且 BF 起有值。"""
    FakeArasClient.calls = []
    FakeOfficialTransport.generate_calls = 0
    monkeypatch.setattr(crawler_boot, "EWOExportTransport", FakeOfficialTransport)

    resp = client.post(
        "/api/aras/ewo/export",
        json={
            "base_url": "http://aras.example",
            "filters": {"project_code": "F610S"},
        },
    )
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["ok"] is True
    task_id = body["data"]["taskId"]
    assert task_id.startswith("ewo_")
    assert body["data"]["statusUrl"] == f"/api/tasks/{task_id}"

    task = _wait_for_background_task(client, task_id)
    assert task["status"] == "succeeded"
    assert task["can_download"] is True
    assert FakeOfficialTransport.generate_calls == 1

    download = client.get(f"/api/tasks/{task_id}/download")
    assert download.status_code == 200
    assert "attachment" in download.headers["Content-Disposition"]
    text = download.get_data(as_text=True)
    lines = text.splitlines()
    header = lines[0].split(",")
    row = lines[1].split(",")
    assert len(header) == 111
    assert header[57] == "项目生产基地汇总"
    assert row[0] == "EWO-1"
    # 列表来源下恒空的尾部列，现在必须来自官方工作簿。
    assert row[57] == "项目生产基地汇总|EWO-1"
    assert row[-1] == f"{header[-1]}|EWO-1"


def test_ewo_list_columns_export_route_marks_unprovided_columns(client) -> None:
    resp = client.post(
        "/api/aras/ewo/export-list-columns",
        json={"base_url": "http://aras.example", "filters": {"project_code": "F610S"}},
    )
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["ok"] is True
    task_id = body["data"]["taskId"]
    task = _wait_for_background_task(client, task_id)
    assert task["status"] == "succeeded"
    assert task["can_download"] is True

    download = client.get(f"/api/tasks/{task_id}/download")
    assert download.status_code == 200
    csv_body = download.get_data(as_text=True)
    assert "EWO-1" in csv_body
    assert "（列表导出未提供）" in csv_body
    assert "secret-cookie" not in csv_body


def test_paa_export_route_creates_async_csv_artifact_and_redacts(client) -> None:
    resp = client.post(
        "/api/aras/paa/export",
        json={
            "base_url": "http://aras.example",
            "filters": {"department": "技术中心-车体工程"},
        },
    )
    assert resp.status_code == 202
    task_id = resp.get_json()["data"]["taskId"]

    task = _wait_for_background_task(client, task_id)
    assert task["status"] == "succeeded"

    crawl_call = next(call for call in FakeArasClient.calls if call.get("method") == "paa_all")
    assert crawl_call["page_size"] == 2000
    assert crawl_call["max_pages"] == 1000
    assert crawl_call["max_records"] == 10000
    assert crawl_call["filters"].department == "技术中心_车体工程"

    download = client.get(f"/api/tasks/{task_id}/download")
    assert download.status_code == 200
    body = download.get_data(as_text=True)
    assert "PAA-2" in body
    assert "abc123" not in body
    assert "tok123" not in body
    assert "secret-cookie" not in body
    assert "raw_xml" not in body


def test_paa_crawl_all_async_result_contract(client) -> None:
    resp = client.post(
        "/api/aras/paa/crawl-all",
        json={
            "base_url": "http://aras.example",
            "filters": {"paa_no": "PAA-2"},
            "page_size": 40,
            "max_pages": 6,
            "max_records": 120,
        },
    )
    assert resp.status_code == 202
    body = resp.get_json()
    task_id = body["data"]["taskId"]

    task = _wait_for_background_task(client, task_id)
    assert task["status"] == "succeeded"
    assert task["task_type"] == "paa_crawl"

    crawl_call = next(call for call in FakeArasClient.calls if call.get("method") == "paa_all")
    assert crawl_call["page_size"] == 40
    assert crawl_call["max_pages"] == 6
    assert crawl_call["max_records"] == 120

    result = client.get(f"/api/tasks/{task_id}/result")
    assert result.status_code == 200
    result_data = result.get_json()["data"]
    assert "headerRows" in result_data
    assert "columns" in result_data
    assert result_data["defaultVisibleCount"] == 12
    assert result_data["rows"][0][:3] == [
        "PAA-2",
        "Closed",
        "Cookie: [redacted] Authorization: [redacted] token=[redacted]",
    ]
    assert result_data["page"] == 2
    # 结果工件内部不得包含未脱敏凭据
    result_text = result.get_data(as_text=True)
    assert "secret-cookie" not in result_text
    assert "sid=abc123" not in result_text


def test_ewo_export_rejects_incomplete_listing_before_generation(monkeypatch, client) -> None:
    """列表预检不完整时同步 422，绝不进入非幂等的生成阶段。"""
    def truncated_crawl(self, filters=None, **kwargs):  # type: ignore[no-untyped-def]
        self.__class__.calls.append({"method": "ewo_all", "filters": filters})
        return EWOReportPage(
            rows=[{"_no": "EWO-1"}], page=1, item_ids=["A" * 32], raw_xml="", complete=False,
        )

    monkeypatch.setattr(FakeArasClient, "crawl_ewo_report_all", truncated_crawl)
    FakeOfficialTransport.generate_calls = 0
    monkeypatch.setattr(crawler_boot, "EWOExportTransport", FakeOfficialTransport)
    resp = client.post(
        "/api/aras/ewo/export",
        json={"base_url": "http://aras.example", "filters": {}, "max_records": 100},
    )
    assert resp.status_code == 422
    assert resp.get_json()["error"]["type"] == "IncompleteSelection"
    assert FakeOfficialTransport.generate_calls == 0


def test_ewo_export_artifact_lands_in_ewo_downloads_dir(monkeypatch, tmp_path) -> None:
    test_client = _make_test_client(monkeypatch, tmp_path, allowed_hosts=["aras.example"])
    FakeOfficialTransport.generate_calls = 0
    monkeypatch.setattr(crawler_boot, "EWOExportTransport", FakeOfficialTransport)
    resp = test_client.post(
        "/api/aras/ewo/export",
        json={"base_url": "http://aras.example", "filters": {}},
    )
    assert resp.status_code == 202
    task_id = resp.get_json()["data"]["taskId"]

    task = _wait_for_background_task(test_client, task_id)
    assert task["status"] == "succeeded"

    downloads_dir = tmp_path / "ewo-downloads"
    files = [p.name for p in downloads_dir.iterdir() if p.is_file()]
    assert any(name.startswith("ewo_export_") and name.endswith(".csv") for name in files)


def test_ncr_detail_download_route_downloads_file(client) -> None:
    resp = client.post(
        "/api/aras/ncr/detail/download",
        json={
            "base_url": "http://aras.example",
            "cookie": "sid=secret-cookie",
            "filters": {"department": "技术中心-车体工程", "section_code": "BE"},
        },
    )
    assert resp.status_code == 200
    assert resp.get_data() == b"NCR-DETAIL-CONTENT"
    disposition = resp.headers["Content-Disposition"]
    assert "attachment" in disposition
    assert "detail.xlsx" in disposition
    detail_call = next(call for call in FakeArasClient.calls if call.get("method") == "detail")
    assert detail_call["filters"].section_codes == ("BA", "BE", "BI", "EXT", "INT", "SES", "VE")
    assert detail_call["filters"].section_code == "BE"
    download_call = next(call for call in FakeArasClient.calls if call.get("method") == "ncr_download")
    assert download_call["file_name"] == "detail.xlsx"
    assert "secret-cookie" not in resp.get_data(as_text=True)


def test_ncr_progress_download_route_downloads_vault_file(client) -> None:
    resp = client.post(
        "/api/aras/ncr/progress/download",
        json={
            "base_url": "http://aras.example",
            "cookie": "sid=secret-cookie",
            "filters": {"project_names": ["F610S", "F610S DG"]},
        },
    )

    assert resp.status_code == 200
    assert resp.get_data() == b"NCR-PROGRESS-CONTENT"
    disposition = resp.headers["Content-Disposition"]
    assert "attachment" in disposition
    assert "progress.xlsx" in disposition
    progress_calls = [call for call in FakeArasClient.calls if call.get("method") == "progress"]
    assert progress_calls[-1]["filters"].project_names == ("F610S", "F610S DG")
    download_call = next(call for call in FakeArasClient.calls if call.get("method") == "ncr_progress_download")
    assert download_call["file_name"] == "progress.xlsx"
    assert "FILE-secret2" not in resp.get_data(as_text=True)
    assert "secret-cookie" not in resp.get_data(as_text=True)


def test_ncr_detail_download_without_file_name_returns_502(monkeypatch, client) -> None:
    monkeypatch.setattr(FakeArasClient, "detail_file_name", "")
    resp = client.post(
        "/api/aras/ncr/detail/download",
        json={"base_url": "http://aras.example", "filters": {}},
    )
    assert resp.status_code == 502
    assert resp.get_json()["ok"] is False
    assert not any(call.get("method") == "ncr_download" for call in FakeArasClient.calls)


def test_route_validation_and_aras_error_are_sanitized(client) -> None:
    missing = client.post("/api/aras/ewo/query", json={"filters": {}})
    assert missing.status_code == 400
    assert missing.get_json()["ok"] is False

    FakeArasClient.fail = ArasCrawlerError(
        'upstream failed Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3 Authorization: Bearer xyz789 token=tok123 '
        'Set-Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3 '
        '"token":"tok123" {\'Authorization\': \'Bearer xyz789\'}'
    )
    failed = client.post("/api/aras/ewo/query", json={"base_url": "http://aras.example", "cookie": "sid=abc123"})
    text = failed.get_data(as_text=True)
    assert failed.status_code == 502
    assert failed.get_json()["error"]["type"] == "ArasCrawlerError"
    assert "abc123" not in text
    assert "secret2" not in text
    assert "secret3" not in text
    assert "xyz789" not in text
    assert "tok123" not in text


def test_ncr_export_contract_error_maps_to_dedicated_code_and_chinese_message(client) -> None:
    """官方 NCR 导出方法未返回文件引用 → 502 + ncr_export_no_file + 中文可操作文案。

    消息携带无泄漏结构签名并指引回传诊断文件；不再落到通用 query_failed 分支。
    """
    FakeArasClient.fail = ArasNcrExportContractError(
        "NCR progress response does not contain a Result Item with _file id",
        "result_present=true result_text_present=false child_tags=[] item_count=0 body_chars=87",
    )
    failed = client.post(
        "/api/aras/ewo/query", json={"base_url": "http://aras.example", "cookie": "sid=abc123"}
    )
    body = failed.get_json()
    assert failed.status_code == 502
    assert body["error"]["type"] == "ArasNcrExportContractError"
    assert body["error"]["code"] == "ncr_export_no_file"
    message = body["error"]["message"]
    assert "官方 NCR 导出方法未返回文件引用" in message
    assert "result_present=true" in message
    assert "诊断文件" in message


def test_remote_report_mutations_are_rejected_before_upstream_access(client) -> None:
    for endpoint in ("/api/aras/ewo/query", "/api/tdc/data-model/query"):
        response = client.post(
            endpoint,
            json={"base_url": "http://aras.example", "filters": {}},
            environ_overrides={"REMOTE_ADDR": "192.0.2.10"},
        )
        assert response.status_code == 403
        assert response.get_json()["error"]["type"] == "LocalAccessRequired"





































class FakeECMAuthClient:
    calls: list[dict[str, object]] = []
    session = object()
    fail: Exception | None = None

    def __init__(self, base_url, timeout=30.0, diagnostic_hook=None):  # type: ignore[no-untyped-def]
        self.__class__.calls.append(
            {
                "method": "init",
                "base_url": base_url,
                "timeout": timeout,
                "diagnostic_hook": diagnostic_hook,
            }
        )

    def login(self, username, password):  # type: ignore[no-untyped-def]
        self.__class__.calls.append({"method": "login", "username": username, "password": password})
        if self.fail:
            raise self.fail
        from services.aras_auth import ArasLoginResult

        return ArasLoginResult(session=self.session)
























def test_static_guards_for_boundaries_and_credentials() -> None:
    service_text = Path("services/aras_crawler.py").read_text(encoding="utf-8-sig")
    assert not re.search(r"\b(rich|flask|render_template|jsonify|document\.|window\.)\b", service_text)

    frontend = sorted(Path("web/static/host").glob("**/*.js")) + sorted(Path("plugins").glob("*/static/**/*.js"))
    cli_web_text = "\n".join(
        Path(path).read_text(encoding="utf-8-sig")
        for path in [
            "web/app.py",
            "web/templates/dashboard.html",
            *(path for path in frontend if "vendor" not in path.parts),
        ]
    )
    assert not re.search(
        r"(?:cookie|token|authorization|sessionid|csrf|password).{0,80}localStorage",
        cli_web_text,
        re.IGNORECASE,
    )
    assert ("session" + "Storage") not in cli_web_text
    assert ("console" + ".log(") not in cli_web_text
    assert not re.search(
        r"requests\.(?:get|post|head|request)\(",
        Path("tests/test_aras_cli_web.py").read_text(encoding="utf-8-sig"),
    )


def test_aras_auth_error_survives_diagnostic_save_failure(monkeypatch, tmp_path) -> None:
    """诊断报告 save() 抛 OSError 时，认证错误仍应返 401，不被替换为 500。"""
    FakeWebAuthClient.calls = []
    FakeWebAuthClient.fail = ArasAuthError("ECM identity rejected credentials", stage="ecm-credentials")
    monkeypatch.setattr(crawler_boot, "ArasECMAuthClient", FakeWebAuthClient)

    real_cls = crawler_boot.MarkdownDiagnosticReport

    class FailingSaveReport(real_cls):  # type: ignore[misc, valid-type]
        def save(self, status: str):  # type: ignore[override]
            raise OSError("disk full")

    monkeypatch.setattr(crawler_boot, "MarkdownDiagnosticReport", FailingSaveReport)
    test_client = _make_test_client(monkeypatch, tmp_path, allowed_hosts=["aras.example"])

    failed = test_client.post(
        "/api/aras/ewo/query",
        json={
            "base_url": "http://aras.example",
            "auth_mode": "password",
            "username": "fictional-user",
            "password": "fictional-password-secret",
            "filters": {},
        },
    )

    # 认证错误语义不变：仍 401 AuthenticationError，不因 save 失败变 500
    assert failed.status_code == 401
    body = failed.get_json()
    assert body["error"]["type"] == "AuthenticationError"
    # 诊断路径降级为不提供（无 diagnosticPath 字段或为 None）
    assert not body["error"].get("diagnosticPath")
    assert "fictional-password-secret" not in failed.get_data(as_text=True)


def test_aras_crawler_error_survives_diagnostic_save_failure(monkeypatch, tmp_path) -> None:
    FakeWebAuthClient.calls = []
    FakeWebAuthClient.fail = None
    monkeypatch.setattr(crawler_boot, "ArasECMAuthClient", FakeWebAuthClient)

    real_cls = crawler_boot.MarkdownDiagnosticReport

    class FailingSaveReport(real_cls):  # type: ignore[misc, valid-type]
        def save(self, status: str):  # type: ignore[override]
            raise OSError("disk full")

    monkeypatch.setattr(crawler_boot, "MarkdownDiagnosticReport", FailingSaveReport)
    test_client = _make_test_client(monkeypatch, tmp_path, allowed_hosts=["aras.example"])
    FakeArasClient.fail = ArasCrawlerError("XML response is not valid")

    failed = test_client.post(
        "/api/aras/ewo/query",
        json={
            "base_url": "http://aras.example",
            "auth_mode": "password",
            "username": "fictional-user",
            "password": "fictional-password-secret",
            "filters": {},
        },
    )

    assert failed.status_code == 502
    body = failed.get_json()
    assert body["error"]["type"] == "ArasCrawlerError"
    assert not body["error"].get("diagnosticPath")
    assert "fictional-password-secret" not in failed.get_data(as_text=True)


def test_aras_browser_mode_without_session_or_credentials_is_guided_to_unified_login() -> None:
    """无共享域会话且无任何凭据时，必须 401 引导用户去统一域账号登录。"""
    payload = {"base_url": "http://ecm.sgmw.com.cn/innovatorserver"}
    with pytest.raises(crawler_boot._ArasRequestError) as excinfo:
        crawler_boot._build_aras_client_from_payload(payload)
    assert excinfo.value.error_type == "DomainSessionRequired"
    assert excinfo.value.status_code == 401


def test_aras_browser_mode_rejects_username_password_credentials() -> None:
    """browser 模式与账号密码互斥（与 TDC 侧语义一致），避免凭据被静默忽略。"""
    payload = {
        "base_url": "http://ecm.sgmw.com.cn/innovatorserver",
        "username": "user",
        "password": "pwd",
    }
    with pytest.raises(crawler_boot._ArasRequestError) as excinfo:
        crawler_boot._build_aras_client_from_payload(payload)
    assert excinfo.value.error_type == "AuthenticationModeConflict"


def test_aras_browser_mode_allows_custom_authorization_header() -> None:
    """自带 Authorization 等自定义头的 browser 请求不受新门禁影响。"""
    payload = {
        "base_url": "http://ecm.sgmw.com.cn/innovatorserver",
        "headers": {"Authorization": "Bearer token"},
    }
    client = crawler_boot._build_aras_client_from_payload(payload)
    # _normalize_aras_app_root 会补尾斜杠。
    assert "innovatorserver" in client.base_url


def test_tdc_browser_mode_without_session_or_credentials_is_guided_to_unified_login() -> None:
    payload = {"base_url": "https://tdc.sgmw.com.cn"}
    with pytest.raises(web_app._TDCRequestError) as excinfo:
        web_app._build_tdc_client_from_payload(payload)
    assert excinfo.value.error_type == "DomainSessionRequired"
    assert excinfo.value.status_code == 401
