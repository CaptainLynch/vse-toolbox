from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console
from rich.prompt import Prompt

import main
import web.app as web_app
from core.diagnostics import DiagnosticOptions, MarkdownDiagnosticReport
from services.aras_auth import ArasAuthError
from services.aras_crawler import ArasCrawlerError, EWOReportPage, PAAReportPage
from services.aras_export import CSVExportResult, EWOExportResult


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
        return EWOReportPage(
            rows=[
                {
                    "_no": "EWO-1",
                    "_sort_sub_type": "PWO-EWO定点",
                    "created_by_id__keyed_name": "Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3 Authorization: Bearer xyz789",
                    "state": "Open",
                    "note": "Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3 Authorization: Bearer xyz789",
                    "cookie": "sid=secret-cookie",
                    "raw_xml": "<secret-xml/>",
                }
            ],
            page=page,
            item_ids=["ID-1"],
            raw_xml="<xml/>",
        )

    def crawl_ewo_report_all(self, filters, page_size=50, max_pages=40, max_records=2000):  # type: ignore[no-untyped-def]
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
            item_ids=["ID-1"],
            raw_xml="<xml/>",
        )

    def query_paa_report(self, filters, page=1, page_size=50, max_records=2000):  # type: ignore[no-untyped-def]
        if self.fail:
            raise self.fail
        self.__class__.calls.append(
            {"method": "paa", "filters": filters, "page": page, "page_size": page_size, "max_records": max_records}
        )
        return PAAReportPage(
            rows=[
                {
                    "_no": "PAA-1",
                    "_auth_type": "Open",
                    "created_by_id__keyed_name": "Set-Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3 Authorization: Bearer xyz789",
                    "state": "Open",
                    "note": "Set-Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3 Authorization: Bearer xyz789",
                    "cookie": "sid=secret-cookie",
                    "raw_xml": "<secret-xml/>",
                }
            ],
            page=page,
            item_ids=["PAA-ID-1"],
            raw_xml="<xml/>",
        )

    def crawl_paa_report_all(self, filters, page_size=50, max_pages=20, max_records=2000):  # type: ignore[no-untyped-def]
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


@pytest.fixture(autouse=True)
def disable_cli_aras_diagnostics(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(main, "_ask_aras_diagnostic_options", lambda: DiagnosticOptions())


def _make_test_client(monkeypatch, tmp_path, allowed_hosts=None):  # type: ignore[no-untyped-def]
    FakeArasClient.calls = []
    FakeArasClient.fail = None
    FakeArasClient.detail_file_name = "detail.xlsx"
    monkeypatch.setattr(web_app, "ArasCrawlerClient", FakeArasClient)
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "web-test.db"))
    monkeypatch.setattr(web_app, "DIAGNOSTIC_DIR", tmp_path / "diagnostics")
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
    monkeypatch.setattr(web_app, "ArasECMAuthClient", FakeWebAuthClient)
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
    monkeypatch.setattr(web_app, "ArasECMAuthClient", FakeWebAuthClient)
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
    monkeypatch.setattr(web_app, "ArasECMAuthClient", FakeWebAuthClient)

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
    assert crawl.status_code == 200
    crawl_data = crawl.get_json()["data"]
    assert "headerRows" in crawl_data
    assert "columns" in crawl_data
    assert crawl_data["defaultVisibleCount"] == 12
    assert crawl_data["rows"][0][:3] == [
        "PAA-2",
        "Closed",
        "Cookie: [redacted] Authorization: [redacted] token=[redacted]",
    ]
    query_call = next(call for call in FakeArasClient.calls if call.get("method") == "paa")
    assert query_call["filters"].paa_no == "PAA-1"
    assert query_call["filters"].mtl_rq_end == "2026-02-28"
    assert query_call["page"] == 3
    crawl_call = next(call for call in FakeArasClient.calls if call.get("method") == "paa_all")
    assert crawl_call["page_size"] == 40
    assert crawl_call["max_pages"] == 6
    assert crawl_call["max_records"] == 120
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
    monkeypatch.setattr(web_app, "ArasCrawlerClient", FakeArasClient)
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


def test_ewo_export_route_streams_csv_with_export_headers(client) -> None:
    resp = client.post(
        "/api/aras/ewo/export",
        json={
            "base_url": "http://aras.example",
            "headers": {"Authorization": "secret-auth"},
            "cookie": "sid=secret-cookie",
            "filters": {"project_code": "F610S"},
        },
    )
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "text/csv; charset=utf-8"
    assert "attachment" in resp.headers["Content-Disposition"]
    assert "filename=" in resp.headers["Content-Disposition"]
    body = resp.get_data(as_text=True)
    assert "EWO-1" in body
    assert "F610S" in body
    assert resp.headers["X-Export-Complete"] == "true"
    assert resp.headers["X-Export-Truncated"] == "false"
    assert resp.headers["X-Export-Row-Count"] == "1"
    crawl_call = next(call for call in FakeArasClient.calls if call.get("method") == "ewo_all")
    assert crawl_call["page_size"] == 2000
    assert crawl_call["max_pages"] == 1000
    assert crawl_call["max_records"] == 10000
    assert "secret-cookie" not in body
    assert "secret-auth" not in body


def test_paa_export_route_streams_csv_and_redacts_credentials(client) -> None:
    resp = client.post(
        "/api/aras/paa/export",
        json={
            "base_url": "http://aras.example",
            "cookie": "sid=secret-cookie",
            "filters": {"department": "技术中心-车体工程"},
        },
    )
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "text/csv; charset=utf-8"
    assert resp.headers["X-Export-Complete"] == "true"
    assert resp.headers["X-Export-Row-Count"] == "1"
    body = resp.get_data(as_text=True)
    assert "PAA-2" in body
    assert "abc123" not in body
    assert "tok123" not in body
    assert "secret-cookie" not in body
    assert "raw_xml" not in body
    crawl_call = next(call for call in FakeArasClient.calls if call.get("method") == "paa_all")
    assert crawl_call["page_size"] == 2000
    assert crawl_call["max_pages"] == 1000
    assert crawl_call["max_records"] == 10000
    assert crawl_call["filters"].department == "技术中心_车体工程"


def test_ewo_export_marks_truncation_via_headers(monkeypatch, client) -> None:
    def truncated_crawl(self, filters=None, page_size=2000, max_pages=1000, max_records=10000):  # type: ignore[no-untyped-def]
        self.__class__.calls.append(
            {
                "method": "ewo_all",
                "filters": filters,
                "page_size": page_size,
                "max_pages": max_pages,
                "max_records": max_records,
            }
        )
        return EWOReportPage(rows=[{"_no": "EWO-1"}], page=max_pages, item_ids=["ID-1"], raw_xml="")

    monkeypatch.setattr(FakeArasClient, "crawl_ewo_report_all", truncated_crawl)
    resp = client.post(
        "/api/aras/ewo/export",
        json={"base_url": "http://aras.example", "filters": {}, "max_records": 100},
    )
    assert resp.status_code == 200
    assert resp.headers["X-Export-Complete"] == "false"
    assert resp.headers["X-Export-Truncated"] == "true"
    assert resp.headers["X-Export-Row-Count"] == "1"


def test_export_temp_dir_removed_after_response(monkeypatch, tmp_path) -> None:
    test_client = _make_test_client(monkeypatch, tmp_path, allowed_hosts=["aras.example"])
    captured: list[str] = []
    real_mkdtemp = tempfile.mkdtemp
    fake_tempfile = SimpleNamespace(
        mkdtemp=lambda *args, **kwargs: captured.append(real_mkdtemp(*args, **kwargs)) or captured[-1]
    )
    monkeypatch.setattr(web_app, "tempfile", fake_tempfile)
    resp = test_client.post(
        "/api/aras/ewo/export",
        json={"base_url": "http://aras.example", "filters": {}},
    )
    assert resp.status_code == 200
    assert "EWO-1" in resp.get_data(as_text=True)
    assert len(captured) == 1
    # 数据读入内存后临时目录已在响应返回前清理（不依赖响应关闭回调）
    assert not Path(captured[0]).exists()


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


def test_remote_report_mutations_are_rejected_before_upstream_access(client) -> None:
    for endpoint in ("/api/aras/ewo/query", "/api/tdc/data-model/query"):
        response = client.post(
            endpoint,
            json={"base_url": "http://aras.example", "filters": {}},
            environ_overrides={"REMOTE_ADDR": "192.0.2.10"},
        )
        assert response.status_code == 403
        assert response.get_json()["error"]["type"] == "LocalAccessRequired"

    cli_text = main._safe_error_message(
        ArasCrawlerError(
            "upstream failed Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3 "
            "Bearer xyz789 token=tok123 api_key=key456\n" + ("x" * 500) + "TAIL"
        )
    )
    assert "abc123" not in cli_text
    assert "secret2" not in cli_text
    assert "secret3" not in cli_text
    assert "xyz789" not in cli_text
    assert "tok123" not in cli_text
    assert "key456" not in cli_text
    assert "\n" in cli_text
    assert "TAIL" in cli_text


def test_cli_helpers_parse_headers_and_render_without_auth() -> None:
    headers = main._parse_header_lines(
        "X-Test: yes, Authorization: secret, Accept-Language: zh-CN,zh;q=0.9\nTIMEZONE_NAME: China Standard Time"
    )
    assert headers == {
        "X-Test": "yes",
        "Authorization": "secret",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "TIMEZONE_NAME": "China Standard Time",
    }

    table = main._render_ewo_result(
        EWOReportPage(rows=[{"_no": "EWO-1", "state": "Open"}], page=1, item_ids=["ID-1"], raw_xml="<xml/>")
    )
    assert table.title == "EWO report result | page=1 rows=1 items=1"
    assert "secret" not in repr(table)


def test_cli_aras_connection_defaults_base_url_and_headers_are_visible(monkeypatch) -> None:
    real_prompt_ask = Prompt.ask  # 在 monkeypatch 前捕获真实 Prompt.ask
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_ask(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((args, kwargs))
        return ""

    monkeypatch.setattr(main.Prompt, "ask", fake_ask)

    base_url, headers, credentials = main._ask_aras_connection()

    assert base_url == ""
    assert credentials is None
    assert headers == {}
    base_call = next((args, kwargs) for args, kwargs in calls if str(args[0]).startswith("Aras base_url"))
    assert base_call[1]["default"] == "http://ecm.sgmw.com.cn/innovatorserver"
    assert not any(str(args[0]).startswith("Cookie header") for args, _kwargs in calls)

    # 真实 Prompt 渲染：base_url 默认值以明文出现在终端提示中；用户名为空 → 安全校验错误
    console = Console(record=True, width=160)
    monkeypatch.setattr(main, "console", console)
    monkeypatch.setattr(console, "input", lambda *args, **kwargs: "")
    monkeypatch.setattr(
        main.Prompt,
        "ask",
        lambda prompt, **kwargs: real_prompt_ask(prompt, console=console, **kwargs),
    )
    with pytest.raises(ValueError, match="用户名不能为空"):
        main._ask_aras_connection()
    rendered = console.export_text()
    assert "http://ecm.sgmw.com.cn/innovatorserver" in rendered
    assert "Cookie header" not in rendered
    assert "Cookie> " not in rendered


def test_cli_aras_connection_default_headers_show_safe_plaintext_and_enter_accepts(
    monkeypatch,
) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_ask(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((args, kwargs))
        prompt = str(args[0])
        if prompt.startswith("Aras base_url"):
            return "http://aras.example/innovatorserver"
        if prompt.startswith("ECM 用户名"):
            return "fictional-user"
        if prompt.startswith("ECM 密码"):
            return "fictional-password-secret"
        return ""

    monkeypatch.setattr(main.Prompt, "ask", fake_ask)
    console = Console(record=True, width=160)
    # 直接回车（空行）→ 使用可见的安全默认 headers
    monkeypatch.setattr(console, "input", lambda *args, **kwargs: "")
    monkeypatch.setattr(main, "console", console)

    base_url, headers, credentials = main._ask_aras_connection()

    assert base_url == "http://aras.example/innovatorserver"
    assert credentials == ("fictional-user", "fictional-password-secret")
    rendered = console.export_text()
    assert "Accept: */*" in rendered
    assert "Accept-Language: zh-CN,zh;q=0.9" in rendered
    assert "Content-Type: text/xml; charset=UTF-8" in rendered
    assert "Origin: http://aras.example" in rendered
    assert "Referer: http://aras.example/innovatorserver/Client/default.aspx" in rendered
    assert "TIMEZONE_NAME: China Standard Time" in rendered
    assert "User-Agent:" in rendered
    # 默认 headers 仅含非机密浏览器/SOAP 头
    for header_name in ("Accept", "Accept-Language", "Content-Type", "Origin", "Referer", "TIMEZONE_NAME", "User-Agent"):
        assert header_name in headers
    assert not any(
        name.lower() in {"cookie", "authorization"}
        for name in headers
    )
    assert not any(str(args[0]).startswith("Cookie header") for args, _kwargs in calls)


def test_cli_aras_connection_username_with_hidden_password_and_no_cookie_prompt(
    monkeypatch,
) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    answers = iter(
        [
            "http://aras.example/innovatorserver",
            "fictional-user",
            "fictional-password-secret",
        ]
    )

    def fake_ask(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((args, kwargs))
        return next(answers)

    monkeypatch.setattr(main.Prompt, "ask", fake_ask)
    console = Console(record=True, width=160)
    monkeypatch.setattr(console, "input", lambda *args, **kwargs: "")
    monkeypatch.setattr(main, "console", console)

    base_url, headers, credentials = main._ask_aras_connection()

    assert base_url == "http://aras.example/innovatorserver"
    assert credentials == ("fictional-user", "fictional-password-secret")
    assert headers == {  # 回车 → 使用默认 headers
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Content-Type": "text/xml; charset=UTF-8",
        "Origin": "http://aras.example",
        "Referer": "http://aras.example/innovatorserver/Client/default.aspx",
        "TIMEZONE_NAME": "China Standard Time",
        "User-Agent": main.DEFAULT_BROWSER_USER_AGENT,
    }
    prompts = [str(args[0]) for args, _kwargs in calls]
    assert "ECM 用户名" in prompts
    password_call = next((args, kwargs) for args, kwargs in calls if str(args[0]).startswith("ECM 密码"))
    assert password_call[1]["password"] is True
    assert not any(prompt.startswith("Cookie header") for prompt in prompts)
    assert "fictional-password-secret" not in console.export_text()


def test_cli_aras_connection_blank_username_raises_required_validation(monkeypatch) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    answers = iter(
        [
            "http://aras.example/innovatorserver",
            "",  # 用户名为空 → 安全校验错误，不再询问密码
        ]
    )

    def fake_ask(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((args, kwargs))
        return next(answers)

    monkeypatch.setattr(main.Prompt, "ask", fake_ask)
    console = Console(record=True, width=160)
    monkeypatch.setattr(console, "input", lambda *args, **kwargs: "")
    monkeypatch.setattr(main, "console", console)

    with pytest.raises(ValueError, match="用户名不能为空"):
        main._ask_aras_connection()

    prompts = [str(args[0]) for args, _kwargs in calls]
    assert "ECM 用户名" in prompts
    assert not any(prompt.startswith("ECM 密码") for prompt in prompts)  # fail-fast，不进入密码询问
    assert not any(prompt.startswith("Cookie header") for prompt in prompts)
    assert "fictional-password-secret" not in console.export_text()


def test_cli_aras_connection_blank_password_raises_required_validation(monkeypatch) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    answers = iter(
        [
            "http://aras.example/innovatorserver",
            "fictional-user",
            "",  # 密码为空 → 安全校验错误，拒绝无凭据访问
        ]
    )

    def fake_ask(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((args, kwargs))
        return next(answers)

    monkeypatch.setattr(main.Prompt, "ask", fake_ask)
    console = Console(record=True, width=160)
    monkeypatch.setattr(console, "input", lambda *args, **kwargs: "")
    monkeypatch.setattr(main, "console", console)

    with pytest.raises(ValueError, match="密码不能为空"):
        main._ask_aras_connection()

    prompts = [str(args[0]) for args, _kwargs in calls]
    password_call = next((args, kwargs) for args, kwargs in calls if str(args[0]).startswith("ECM 密码"))
    assert password_call[1]["password"] is True  # 密码始终隐藏输入
    assert not any(prompt.startswith("Cookie header") for prompt in prompts)


def test_cli_aras_connection_rejects_authorization_extra_header_fail_fast(monkeypatch) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    answers = iter(["http://aras.example/innovatorserver"])
    input_lines = iter(
        [
            "Authorization: Bearer fake-token",
            "",
        ]
    )

    def fake_ask(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((args, kwargs))
        return next(answers)

    monkeypatch.setattr(main.Prompt, "ask", fake_ask)
    console = Console(record=True, width=160)
    monkeypatch.setattr(console, "input", lambda *args, **kwargs: next(input_lines))
    monkeypatch.setattr(main, "console", console)

    with pytest.raises(ValueError, match="Authorization"):
        main._ask_aras_connection()

    # fail-fast：拒绝发生在询问用户名/密码之前，且消息不含粘贴值
    prompts = [str(args[0]) for args, _kwargs in calls]
    assert prompts == ["Aras base_url"]
    rendered = console.export_text()
    assert "fake-token" not in rendered
    assert "Cookie header" not in rendered
    assert "Cookie> " not in rendered


def test_cli_aras_connection_rejects_cookie_extra_header_fail_fast(monkeypatch) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    answers = iter(["http://aras.example/innovatorserver"])
    input_lines = iter(
        [
            "Cookie: sid=fake-cookie-secret",
            "",
        ]
    )

    def fake_ask(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((args, kwargs))
        return next(answers)

    monkeypatch.setattr(main.Prompt, "ask", fake_ask)
    console = Console(record=True, width=160)
    monkeypatch.setattr(console, "input", lambda *args, **kwargs: next(input_lines))
    monkeypatch.setattr(main, "console", console)

    with pytest.raises(ValueError, match="Extra headers must not contain Cookie"):
        main._ask_aras_connection()

    # fail-fast：拒绝发生在询问用户名/密码之前，且消息不含粘贴值
    prompts = [str(args[0]) for args, _kwargs in calls]
    assert prompts == ["Aras base_url"]
    rendered = console.export_text()
    assert "fake-cookie-secret" not in rendered
    assert "Cookie header" not in rendered
    assert "Cookie> " not in rendered


def test_cli_paa_helper_collects_filters_and_limits(monkeypatch) -> None:
    answers = iter(
        [
            "",  # 业务部门（空 → 不筛选）
            "PAA-1",
            "EWO-1",
            "Open",
            "PT",
            "Base-A",
            "Vehicle",
            "2026-01-01",
            "2026-01-31",
            "2026-02-01",
            "2026-02-28",
            "3",
            "25",
            "100",
            "7",
        ]
    )
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: next(answers))

    filters, page, page_size, max_records, max_pages = main._ask_paa_filters()

    assert filters.paa_no == "PAA-1"
    assert filters.ewo_no == "EWO-1"
    assert filters.state == "Open"
    assert filters.area == "PT"
    assert filters.base == "Base-A"
    assert filters.vehicle_keyword == "Vehicle"
    assert filters.submit_start == "2026-01-01"
    assert filters.submit_end == "2026-01-31"
    assert filters.mtl_rq_start == "2026-02-01"
    assert filters.mtl_rq_end == "2026-02-28"
    assert filters.department is None
    assert (page, page_size, max_records, max_pages) == (3, 25, 100, 7)


def test_cli_paa_helper_normalizes_department_and_default_max_pages(monkeypatch) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    answers = iter(
        [
            "技术中心-车体工程, 技术中心_车体工程",  # 重复 → 去重
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "1",
            "50",
            "2000",
            "",  # Max pages 使用默认值
        ]
    )

    def fake_ask(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((args, kwargs))
        return next(answers)

    monkeypatch.setattr(main.Prompt, "ask", fake_ask)

    filters, page, page_size, max_records, max_pages = main._ask_paa_filters()

    assert filters.department == "技术中心_车体工程"
    assert (page, page_size, max_records, max_pages) == (1, 50, 2000, 1000)
    max_pages_call = next((args, kwargs) for args, kwargs in calls if str(args[0]).startswith("Max pages"))
    assert max_pages_call[1]["default"] == "1000"

    answers = iter(["未知部门"] + [""] * 13)
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: next(answers))
    with pytest.raises(ValueError):
        main._ask_paa_filters()


def test_cli_ncr_helper_maps_department_to_section_codes(monkeypatch) -> None:
    answers = iter(
        [
            "",  # 项目名称
            "技术中心-车体工程",  # 业务部门 → section_codes
            "",  # 采购开始日期
            "",  # 采购结束日期
            "",  # PE 开始日期
            "",  # PE 结束日期
            "",  # NCR 编号
            "BE",  # 高级科室代码原输入仍可用
            "",  # 变更类型
            "0",  # othercondition
        ]
    )
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: next(answers))

    filters = main._ask_ncr_filters()

    assert filters.section_codes == ("BA", "BE", "BI", "EXT", "INT", "SES", "VE")
    assert filters.section_code == "BE"

    answers = iter(["", "未知部门", "", "", "", "", "", "", "", "0"])
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: next(answers))
    with pytest.raises(ValueError):
        main._ask_ncr_filters()


def test_cli_paa_render_without_raw_xml_or_credentials() -> None:
    table = main._render_paa_result(
        PAAReportPage(
            rows=[
                {
                    "_no": "PAA-1",
                    "state": "Open",
                    "note": "Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3 token=tok123 Authorization: Bearer xyz789",
                    "cookie": "sid=secret-cookie",
                    "raw_xml": "<secret-xml/>",
                }
            ],
            page=2,
            item_ids=["ID-1", "ID-2"],
            raw_xml="<raw secret-auth/>",
        )
    )
    console = Console(record=True, width=140)
    console.print(table)
    rendered = console.export_text()

    assert table.title == "PAA report result | page=2 rows=1 items=2"
    assert "PAA-1" in rendered
    assert "abc123" not in rendered
    assert "secret2" not in rendered
    assert "secret3" not in rendered
    assert "tok123" not in rendered
    assert "xyz789" not in rendered
    assert "secret-cookie" not in rendered
    assert "secret-auth" not in rendered
    assert "<secret-xml/>" not in rendered


def test_cli_diagnostic_report_disabled_does_not_create_file(tmp_path) -> None:
    report = MarkdownDiagnosticReport(
        options=DiagnosticOptions(),
        base_url="http://aras.example",
        mode="1",
        output_dir=tmp_path,
    )

    assert report.save("success") is None
    assert list(tmp_path.iterdir()) == []


def test_cli_diagnostic_report_safe_redacts_and_raw_preserves(tmp_path) -> None:
    safe = MarkdownDiagnosticReport(
        options=DiagnosticOptions(enabled=True, unsafe_raw=False),
        base_url="http://aras.example",
        mode="1",
        inputs={"headers": {"Cookie": "sid=secret-cookie", "Authorization": "Bearer secret-token"}},
        output_dir=tmp_path,
    )
    safe.record_exception(RuntimeError("failed Cookie: sid=secret-cookie token=secret-token"))
    safe_path = safe.save("failed")
    assert safe_path is not None
    safe_text = safe_path.read_text(encoding="utf-8")
    assert "secret-cookie" not in safe_text
    assert "secret-token" not in safe_text
    assert "[redacted]" in safe_text

    raw = MarkdownDiagnosticReport(
        options=DiagnosticOptions(enabled=True, unsafe_raw=True),
        base_url="http://aras.example",
        mode="1",
        inputs={"headers": {"Cookie": "sid=secret-cookie", "Authorization": "Bearer secret-token"}},
        output_dir=tmp_path,
    )
    raw.record_exception(RuntimeError("failed Cookie: sid=secret-cookie token=secret-token"))
    raw_path = raw.save("failed")
    assert raw_path is not None
    raw_text = raw_path.read_text(encoding="utf-8")
    assert "secret-cookie" in raw_text
    assert "secret-token" in raw_text


def test_cli_diagnostic_report_escapes_control_characters(tmp_path) -> None:
    report = MarkdownDiagnosticReport(
        options=DiagnosticOptions(enabled=True, unsafe_raw=True),
        base_url="http://aras.example",
        mode="1",
        output_dir=tmp_path,
    )
    report.record_http_event(
        {
            "stage": "prewarm",
            "method": "GET",
            "url": "http://aras.example/innovatorserver/Client/default.aspx",
            "request_headers": {"Cookie": "\x16"},
        }
    )

    path = report.save("failed")
    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "\\x16" in text
    assert "\x16" not in text


def test_cli_ncr_renderers_do_not_leak_sensitive_values() -> None:
    console = Console(record=True, width=140)

    console.print(main._render_ncr_progress_result(FakeProgress()))
    console.print(main._render_ncr_detail_result(FakeDetail(file_name="detail.xlsx")))
    rendered = console.export_text()

    assert "NCR approval progress result" in rendered
    assert "NCR approval detail result" in rendered
    assert "progress.xlsx" in rendered
    assert "FILE-secret2" not in rendered
    assert "secret2" not in rendered


def test_cli_ewo_handler_queries_without_forcing_export(monkeypatch) -> None:
    FakeArasClient.calls = []
    FakeArasClient.fail = None
    FakeECMAuthClient.calls = []
    FakeECMAuthClient.fail = None
    filters = main.EWOReportFilters(ewo_no="EWO-1")
    monkeypatch.setattr(main, "ArasCrawlerClient", FakeArasClient)
    monkeypatch.setattr(main, "ArasECMAuthClient", FakeECMAuthClient)
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: "1")
    monkeypatch.setattr(main.Confirm, "ask", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        main,
        "_ask_aras_connection",
        lambda: ("http://aras.example", {}, ("fictional-user", "fictional-password-secret")),
    )
    monkeypatch.setattr(main, "_ask_ewo_filters", lambda: (filters, 2, 25, 100))
    console = Console(record=True, width=140)
    monkeypatch.setattr(main, "console", console)

    main.handle_intranet_scrape(None)  # type: ignore[arg-type]

    call = next(item for item in FakeArasClient.calls if item.get("method") == "ewo")
    assert call["filters"] == filters
    assert call["page"] == 2
    assert call["page_size"] == 25
    assert call["max_records"] == 100
    assert not any(item.get("method") == "ewo_all" for item in FakeArasClient.calls)
    assert "EWO report result" in console.export_text()


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


def test_cli_aras_handler_ecm_password_login_injects_authenticated_session(
    monkeypatch,
) -> None:
    FakeArasClient.calls = []
    FakeArasClient.fail = None
    FakeECMAuthClient.calls = []
    FakeECMAuthClient.fail = None
    filters = main.EWOReportFilters(ewo_no="EWO-1")
    monkeypatch.setattr(main, "ArasCrawlerClient", FakeArasClient)
    monkeypatch.setattr(main, "ArasECMAuthClient", FakeECMAuthClient)
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: "1")
    monkeypatch.setattr(main.Confirm, "ask", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        main,
        "_ask_aras_connection",
        lambda: ("http://aras.example", {}, ("fictional-user", "fictional-password-secret")),
    )
    monkeypatch.setattr(main, "_ask_ewo_filters", lambda: (filters, 1, 25, 100))
    console = Console(record=True, width=140)
    monkeypatch.setattr(main, "console", console)

    main.handle_intranet_scrape(None)  # type: ignore[arg-type]

    auth_call = next(item for item in FakeECMAuthClient.calls if item["method"] == "login")
    assert auth_call["username"] == "fictional-user"
    assert auth_call["password"] == "fictional-password-secret"
    init_call = next(item for item in FakeArasClient.calls if item.get("method") is None)
    assert init_call["session"] is FakeECMAuthClient.session
    rendered = console.export_text()
    assert "正在通过企业账号中心登录 ECM" in rendered
    assert "ECM 账号密码登录成功" in rendered
    assert "fictional-user" not in rendered
    assert "fictional-password-secret" not in rendered


def test_cli_aras_handler_auth_error_is_redacted_and_reported(monkeypatch) -> None:
    from services.aras_auth import ArasAuthError

    FakeArasClient.calls = []
    FakeArasClient.fail = None
    FakeECMAuthClient.calls = []
    FakeECMAuthClient.fail = ArasAuthError(
        "ECM login failed password=fictional-password-secret token=fictional-token-secret",
        stage="ecm-credentials",
    )
    monkeypatch.setattr(main, "ArasCrawlerClient", FakeArasClient)
    monkeypatch.setattr(main, "ArasECMAuthClient", FakeECMAuthClient)
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: "1")
    monkeypatch.setattr(main.Confirm, "ask", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        main,
        "_ask_aras_connection",
        lambda: ("http://aras.example", {}, ("fictional-user", "fictional-password-secret")),
    )
    monkeypatch.setattr(main, "_ask_ewo_filters", lambda: (main.EWOReportFilters(), 1, 25, 100))
    console = Console(record=True, width=140)
    monkeypatch.setattr(main, "console", console)

    main.handle_intranet_scrape(None)  # type: ignore[arg-type]

    rendered = console.export_text()
    assert "ArasAuthError" in rendered
    assert "fictional-user" not in rendered
    assert "fictional-password-secret" not in rendered
    assert "fictional-token-secret" not in rendered
    assert "[redacted]" in rendered
    assert not any(item.get("method") == "ewo" for item in FakeArasClient.calls)


def test_cli_aras_handler_requires_credentials_without_business_requests(monkeypatch) -> None:
    FakeArasClient.calls = []
    FakeArasClient.fail = None
    FakeECMAuthClient.calls = []
    FakeECMAuthClient.fail = None
    monkeypatch.setattr(main, "ArasCrawlerClient", FakeArasClient)
    monkeypatch.setattr(main, "ArasECMAuthClient", FakeECMAuthClient)
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: "1")
    monkeypatch.setattr(main, "_ask_aras_connection", lambda: ("http://aras.example", {}, None))
    console = Console(record=True, width=140)
    monkeypatch.setattr(main, "console", console)

    main.handle_intranet_scrape(None)  # type: ignore[arg-type]

    rendered = console.export_text()
    assert "用户名和密码为必填" in rendered
    # 无凭据 → 不构造客户端、不发起登录、零业务请求
    assert FakeArasClient.calls == []
    assert FakeECMAuthClient.calls == []
    assert not any(item.get("method") == "ewo" for item in FakeArasClient.calls)


def test_cli_aras_handler_rejects_secret_extra_headers_without_business_requests(
    monkeypatch,
) -> None:
    FakeArasClient.calls = []
    FakeArasClient.fail = None
    FakeECMAuthClient.calls = []
    FakeECMAuthClient.fail = None
    monkeypatch.setattr(main, "ArasCrawlerClient", FakeArasClient)
    monkeypatch.setattr(main, "ArasECMAuthClient", FakeECMAuthClient)
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: "1")
    monkeypatch.setattr(
        main,
        "_ask_aras_connection",
        lambda: (
            "http://aras.example",
            {"Cookie": "sid=fake-cookie-secret"},
            ("fictional-user", "fictional-password-secret"),
        ),
    )
    console = Console(record=True, width=140)
    monkeypatch.setattr(main, "console", console)

    main.handle_intranet_scrape(None)  # type: ignore[arg-type]

    rendered = console.export_text()
    assert "Extra headers must not contain Cookie" in rendered
    assert "fake-cookie-secret" not in rendered
    # 拒绝对话边界：即使提供了凭据，带 Cookie/Authorization 的 extra headers 也不放行
    assert FakeArasClient.calls == []
    assert FakeECMAuthClient.calls == []


def test_cli_ewo_handler_exports_all_matching_rows(monkeypatch, tmp_path) -> None:
    FakeArasClient.calls = []
    FakeArasClient.fail = None
    FakeECMAuthClient.calls = []
    FakeECMAuthClient.fail = None
    filters = main.EWOReportFilters(project_code="F610S")
    answers = iter(["1", "safe-report"])
    captured = {}
    monkeypatch.setattr(main, "ArasCrawlerClient", FakeArasClient)
    monkeypatch.setattr(main, "ArasECMAuthClient", FakeECMAuthClient)
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: next(answers))
    monkeypatch.setattr(main.Confirm, "ask", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        main,
        "_ask_aras_connection",
        lambda: ("http://aras.example", {}, ("fictional-user", "fictional-password-secret")),
    )
    monkeypatch.setattr(main, "_ask_ewo_filters", lambda: (filters, 1, 25, 100))

    def fake_export(page, file_name=None):  # type: ignore[no-untyped-def]
        captured["page"] = page
        captured["file_name"] = file_name
        return EWOExportResult(path=tmp_path / "safe-report.csv", row_count=len(page.rows), columns=("_no",))

    monkeypatch.setattr(main, "export_ewo_report_csv", fake_export)
    console = Console(record=True, width=140)
    monkeypatch.setattr(main, "console", console)

    main.handle_intranet_scrape(None)  # type: ignore[arg-type]

    call = next(item for item in FakeArasClient.calls if item.get("method") == "ewo_all")
    assert call["filters"] == filters
    assert call["page_size"] == 2000
    assert call["max_pages"] == 1
    assert call["max_records"] == 100
    assert captured["file_name"] == "safe-report"
    assert captured["page"].rows[0]["_no"] == "EWO-1"
    assert "EWO CSV 已保存" in console.export_text()


def test_cli_ncr_handlers_progress_and_detail(monkeypatch) -> None:
    for choice, method, title in [
        ("2", "progress", "NCR approval progress result"),
        ("3", "detail", "NCR approval detail result"),
    ]:
        FakeArasClient.calls = []
        FakeArasClient.fail = None
        FakeECMAuthClient.calls = []
        FakeECMAuthClient.fail = None
        filters = main.NCRApprovalFilters(ncr_no="NCR-1")
        monkeypatch.setattr(main, "ArasCrawlerClient", FakeArasClient)
        monkeypatch.setattr(main, "ArasECMAuthClient", FakeECMAuthClient)
        monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: choice)
        monkeypatch.setattr(
            main,
            "_ask_aras_connection",
            lambda: ("http://aras.example", {}, ("fictional-user", "fictional-password-secret")),
        )
        monkeypatch.setattr(main, "_ask_ncr_filters", lambda: filters)
        console = Console(record=True, width=140)
        monkeypatch.setattr(main, "console", console)

        main.handle_intranet_scrape(None)  # type: ignore[arg-type]

        method_call = next(call for call in FakeArasClient.calls if call.get("method") == method)
        assert method_call["filters"] == filters
        rendered = console.export_text()
        assert title in rendered
        assert "FILE-secret2" not in rendered
        assert "secret2" not in rendered


def test_cli_ncr_detail_downloads_file_and_reports_path(monkeypatch, tmp_path) -> None:
    FakeArasClient.calls = []
    FakeArasClient.fail = None
    FakeECMAuthClient.calls = []
    FakeECMAuthClient.fail = None
    filters = main.NCRApprovalFilters(ncr_no="NCR-1", section_codes=("BA", "BE"))
    answers = iter(["3", str(tmp_path)])
    monkeypatch.setattr(main, "ArasCrawlerClient", FakeArasClient)
    monkeypatch.setattr(main, "ArasECMAuthClient", FakeECMAuthClient)
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: next(answers))
    monkeypatch.setattr(
        main,
        "_ask_aras_connection",
        lambda: ("http://aras.example", {}, ("fictional-user", "fictional-password-secret")),
    )
    monkeypatch.setattr(main, "_ask_ncr_filters", lambda: filters)
    console = Console(record=True, width=140)
    monkeypatch.setattr(main, "console", console)

    main.handle_intranet_scrape(None)  # type: ignore[arg-type]

    detail_call = next(call for call in FakeArasClient.calls if call.get("method") == "detail")
    assert detail_call["filters"] == filters
    assert detail_call["filters"].section_codes == ("BA", "BE")
    download_call = next(call for call in FakeArasClient.calls if call.get("method") == "ncr_download")
    assert download_call["file_name"] == "detail.xlsx"
    assert download_call["destination"] == str(tmp_path)
    rendered = console.export_text()
    assert "NCR 明细文件已保存" in rendered
    assert str(tmp_path / "detail.xlsx") in rendered


def test_cli_paa_handler_page_query(monkeypatch) -> None:
    FakeArasClient.calls = []
    FakeArasClient.fail = None
    FakeECMAuthClient.calls = []
    FakeECMAuthClient.fail = None
    filters = main.PAAReportFilters(paa_no="PAA-1")
    monkeypatch.setattr(main, "ArasCrawlerClient", FakeArasClient)
    monkeypatch.setattr(main, "ArasECMAuthClient", FakeECMAuthClient)
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: "4")
    monkeypatch.setattr(
        main,
        "_ask_aras_connection",
        lambda: ("http://aras.example", {}, ("fictional-user", "fictional-password-secret")),
    )
    monkeypatch.setattr(main, "_ask_paa_filters", lambda: (filters, 3, 25, 100, 7))
    console = Console(record=True, width=140)
    monkeypatch.setattr(main, "console", console)

    main.handle_intranet_scrape(None)  # type: ignore[arg-type]

    method_call = next(call for call in FakeArasClient.calls if call.get("method") == "paa")
    assert method_call["filters"] == filters
    assert method_call["page"] == 3
    assert method_call["page_size"] == 25
    assert method_call["max_records"] == 100
    rendered = console.export_text()
    assert "PAA report result" in rendered
    assert "secret" not in rendered


def test_cli_paa_handler_full_crawl(monkeypatch, tmp_path) -> None:
    FakeArasClient.calls = []
    FakeArasClient.fail = None
    FakeECMAuthClient.calls = []
    FakeECMAuthClient.fail = None
    filters = main.PAAReportFilters(ewo_no="EWO-1")
    monkeypatch.setattr(main, "ArasCrawlerClient", FakeArasClient)
    monkeypatch.setattr(main, "ArasECMAuthClient", FakeECMAuthClient)
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: "5")
    monkeypatch.setattr(main.Confirm, "ask", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        main,
        "_ask_aras_connection",
        lambda: ("http://aras.example", {}, ("fictional-user", "fictional-password-secret")),
    )
    monkeypatch.setattr(main, "_ask_paa_filters", lambda: (filters, 9, 40, 120, 6))
    captured = {}

    def fake_export(rows, output_dir=None, report_name=None, filters=None, preferred_fields=None):  # type: ignore[no-untyped-def]
        captured["rows"] = rows
        captured["report_name"] = report_name
        captured["preferred_fields"] = preferred_fields
        return CSVExportResult(path=tmp_path / "paa.csv", row_count=len(rows), fieldnames=("_no",))

    monkeypatch.setattr(main, "export_report_csv", fake_export)
    console = Console(record=True, width=140)
    monkeypatch.setattr(main, "console", console)

    main.handle_intranet_scrape(None)  # type: ignore[arg-type]

    method_call = next(call for call in FakeArasClient.calls if call.get("method") == "paa_all")
    assert method_call["filters"] == filters
    assert method_call["page_size"] == 2000
    assert method_call["max_pages"] == 6
    assert method_call["max_records"] == 120
    assert captured["report_name"] == "paa"
    assert captured["preferred_fields"] == main.DEFAULT_PAA_SELECT_FIELDS
    assert captured["rows"][0]["_no"] == "PAA-2"
    rendered = console.export_text()
    assert "PAA report result" in rendered
    assert "PAA CSV 已保存" in rendered


def test_cli_paa_handler_full_crawl_warns_when_limits_reached(monkeypatch) -> None:
    FakeArasClient.calls = []
    FakeArasClient.fail = None
    FakeECMAuthClient.calls = []
    FakeECMAuthClient.fail = None
    filters = main.PAAReportFilters(ewo_no="EWO-1")
    monkeypatch.setattr(main, "ArasCrawlerClient", FakeArasClient)
    monkeypatch.setattr(main, "ArasECMAuthClient", FakeECMAuthClient)
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: "5")
    confirm_answers = iter([True, False])
    monkeypatch.setattr(main.Confirm, "ask", lambda *args, **kwargs: next(confirm_answers))
    monkeypatch.setattr(
        main,
        "_ask_aras_connection",
        lambda: ("http://aras.example", {}, ("fictional-user", "fictional-password-secret")),
    )
    monkeypatch.setattr(main, "_ask_paa_filters", lambda: (filters, 9, 40, 120, 1))
    console = Console(record=True, width=140)
    monkeypatch.setattr(main, "console", console)

    main.handle_intranet_scrape(None)  # type: ignore[arg-type]

    method_call = next(call for call in FakeArasClient.calls if call.get("method") == "paa_all")
    assert method_call["max_pages"] == 1
    assert "可能截断" in console.export_text()


def test_cli_paa_handler_full_crawl_cancel(monkeypatch) -> None:
    FakeArasClient.calls = []
    FakeArasClient.fail = None
    FakeECMAuthClient.calls = []
    FakeECMAuthClient.fail = None
    filters = main.PAAReportFilters(ewo_no="EWO-1")
    monkeypatch.setattr(main, "ArasCrawlerClient", FakeArasClient)
    monkeypatch.setattr(main, "ArasECMAuthClient", FakeECMAuthClient)
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: "5")
    monkeypatch.setattr(main.Confirm, "ask", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        main,
        "_ask_aras_connection",
        lambda: ("http://aras.example", {}, ("fictional-user", "fictional-password-secret")),
    )
    monkeypatch.setattr(main, "_ask_paa_filters", lambda: (filters, 9, 40, 120, 6))
    console = Console(record=True, width=140)
    monkeypatch.setattr(main, "console", console)

    main.handle_intranet_scrape(None)  # type: ignore[arg-type]

    assert not any(call.get("method") == "paa_all" for call in FakeArasClient.calls)
    assert "cancelled" in console.export_text()


def test_static_guards_for_boundaries_and_credentials() -> None:
    service_text = Path("services/aras_crawler.py").read_text(encoding="utf-8-sig")
    assert not re.search(r"\b(rich|flask|render_template|jsonify|document\.|window\.)\b", service_text)

    cli_web_text = "\n".join(
        Path(path).read_text(encoding="utf-8-sig")
        for path in [
            "main.py",
            "web/app.py",
            "web/templates/dashboard.html",
            "web/static/app.js",
            "web/static/style.css",
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


def test_static_aras_export_download_markers_and_department_fields() -> None:
    html_text = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    css_text = Path("web/static/style.css").read_text(encoding="utf-8-sig")

    # 业务部门字段：PAA（分页与全量共用字段组）与 NCR 进度/明细都要有
    assert html_text.count('name="department"') >= 2
    assert html_text.count('placeholder="技术中心-车体工程"') >= 2
    assert 'name="section_code"' in html_text  # NCR 高级字段保留
    assert "BA/BE/BI/EXT/INT/SES/VE" in html_text
    assert 'placeholder="*310S*|*730S*"' in html_text
    assert html_text.count('title="支持 * 模糊和 | 并集"') >= 10
    assert 'title="搜索符号将原样传给 NCR 服务"' in html_text

    # 统一域账号登录后，连接区不再保留账号密码/Cookie 备用模式，
    # 凭据统一来自「设置 → 统一域账号登录」（该表单是全页唯一账号输入）。
    assert 'id="aras-auth-mode"' not in html_text
    assert '<option value="password" selected>' not in html_text
    assert 'id="aras-username"' not in html_text
    assert 'id="aras-password"' not in html_text
    assert html_text.count('name="username"') == 1
    assert html_text.count('name="password"') == 1
    assert "统一域账号登录" in html_text

    # 按钮 action 标识（预览 / 全量导出 / 生成并下载）
    assert 'data-aras-action="preview"' in html_text
    assert 'data-aras-action="export"' in html_text
    assert 'data-aras-action="download"' in html_text
    assert 'type="button"' in html_text
    assert 'id="aras-include-xml"' in html_text
    assert 'id="aras-xml-actions"' in html_text
    assert 'id="aras-download-request-xml"' in html_text
    assert 'id="aras-download-response-xml"' in html_text
    assert 'style.css?v=domain-unify-20260828-r3' in html_text
    assert 'app.js?v=domain-unify-20260828-r3' in html_text

    # 导出 / 下载端点在前端配置中
    assert "/api/aras/ewo/export" in js_text
    assert "/api/aras/paa/export" in js_text
    assert "/api/aras/ncr/detail/download" in js_text
    assert "include_xml" in js_text
    assert "downloadArasXml" in js_text
    assert "requestXml" in js_text
    assert "responseXml" in js_text
    download_block = js_text[js_text.index("function downloadArasXml") : js_text.index("function showArasError")]
    assert "setTimeout" in download_block
    assert "showArasError" in download_block

    actions_rule = re.search(r"\.actions-block\s*\{([^}]*)\}", css_text)
    assert actions_rule is not None
    assert "flex-wrap: wrap" in actions_rule.group(1)
    xml_actions_rule = re.search(r"\.xml-capture-actions\s*\{([^}]*)\}", css_text)
    assert xml_actions_rule is not None
    assert "flex: 1 1 100%" in xml_actions_rule.group(1)
    secondary_rule = re.search(r"\.xml-capture-actions \.secondary-btn\s*\{([^}]*)\}", css_text)
    assert secondary_rule is not None
    assert "white-space: nowrap" in secondary_rule.group(1)

    # XML 取证只挂在用户批准的 EWO/PAA 查询上，不应误出现在 NCR
    paa_block = js_text[js_text.index("paa: ") : js_text.index('"ncr-progress"')]
    assert "xmlCapture: true" in paa_block

    # NCR 进度通过后端 Vault 链路生成并下载，同时保留业务部门筛选
    progress_block = js_text[js_text.index('"ncr-progress"') : js_text.index('"ncr-detail"')]
    assert 'downloadEndpoint: "/api/aras/ncr/progress/download"' in progress_block
    assert "exportEndpoint" not in progress_block
    assert 'exportLabel: "生成并下载"' in progress_block
    assert "department" in progress_block
    assert "xmlCapture: true" not in progress_block

    # blob 下载 helper 读取导出状态头并解析 Content-Disposition 文件名
    assert "X-Export-Row-Count" in js_text
    assert "X-Export-Truncated" in js_text
    assert "Content-Disposition" in js_text
    assert "URL.revokeObjectURL" in js_text

    # 凭据不进 localStorage / sessionStorage（只随 POST body 发送）
    assert "sessionStorage" not in html_text
    assert "sessionStorage" not in js_text
    assert not re.search(
        r"(?:cookie|token|authorization|sessionid|csrf|password).{0,80}localStorage",
        html_text + js_text,
        re.IGNORECASE,
    )


def test_aras_auth_error_survives_diagnostic_save_failure(monkeypatch, tmp_path) -> None:
    """诊断报告 save() 抛 OSError 时，认证错误仍应返 401，不被替换为 500。"""
    FakeWebAuthClient.calls = []
    FakeWebAuthClient.fail = ArasAuthError("ECM identity rejected credentials", stage="ecm-credentials")
    monkeypatch.setattr(web_app, "ArasECMAuthClient", FakeWebAuthClient)

    real_cls = web_app.MarkdownDiagnosticReport

    class FailingSaveReport(real_cls):  # type: ignore[misc, valid-type]
        def save(self, status: str):  # type: ignore[override]
            raise OSError("disk full")

    monkeypatch.setattr(web_app, "MarkdownDiagnosticReport", FailingSaveReport)
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
    monkeypatch.setattr(web_app, "ArasECMAuthClient", FakeWebAuthClient)

    real_cls = web_app.MarkdownDiagnosticReport

    class FailingSaveReport(real_cls):  # type: ignore[misc, valid-type]
        def save(self, status: str):  # type: ignore[override]
            raise OSError("disk full")

    monkeypatch.setattr(web_app, "MarkdownDiagnosticReport", FailingSaveReport)
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
    with pytest.raises(web_app._ArasRequestError) as excinfo:
        web_app._build_aras_client_from_payload(payload)
    assert excinfo.value.error_type == "DomainSessionRequired"
    assert excinfo.value.status_code == 401


def test_aras_browser_mode_rejects_username_password_credentials() -> None:
    """browser 模式与账号密码互斥（与 TDC 侧语义一致），避免凭据被静默忽略。"""
    payload = {
        "base_url": "http://ecm.sgmw.com.cn/innovatorserver",
        "username": "user",
        "password": "pwd",
    }
    with pytest.raises(web_app._ArasRequestError) as excinfo:
        web_app._build_aras_client_from_payload(payload)
    assert excinfo.value.error_type == "AuthenticationModeConflict"


def test_aras_browser_mode_allows_custom_authorization_header() -> None:
    """自带 Authorization 等自定义头的 browser 请求不受新门禁影响。"""
    payload = {
        "base_url": "http://ecm.sgmw.com.cn/innovatorserver",
        "headers": {"Authorization": "Bearer token"},
    }
    client = web_app._build_aras_client_from_payload(payload)
    # _normalize_aras_app_root 会补尾斜杠。
    assert "innovatorserver" in client.base_url


def test_tdc_browser_mode_without_session_or_credentials_is_guided_to_unified_login() -> None:
    payload = {"base_url": "https://tdc.sgmw.com.cn"}
    with pytest.raises(web_app._TDCRequestError) as excinfo:
        web_app._build_tdc_client_from_payload(payload)
    assert excinfo.value.error_type == "DomainSessionRequired"
    assert excinfo.value.status_code == 401
