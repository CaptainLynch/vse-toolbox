from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest
from rich.console import Console

import main
import web.app as web_app
from core.diagnostics import DiagnosticOptions, MarkdownDiagnosticReport
from services.aras_crawler import ArasCrawlerError, EWOReportPage, PAAReportPage


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

    def __init__(self, base_url, headers=None, cookies=None, timeout=30.0, diagnostic_hook=None):  # type: ignore[no-untyped-def]
        self.base_url = base_url
        self.headers = headers or {}
        self.cookies = cookies
        self.timeout = timeout
        self.diagnostic_hook = diagnostic_hook
        self.__class__.calls.append(
            {
                "base_url": base_url,
                "headers": self.headers,
                "cookies": cookies,
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
        return FakeDetail()


@pytest.fixture(autouse=True)
def disable_cli_aras_diagnostics(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(main, "_ask_aras_diagnostic_options", lambda: DiagnosticOptions())


@pytest.fixture()
def client(monkeypatch, tmp_path):
    FakeArasClient.calls = []
    FakeArasClient.fail = None
    monkeypatch.setattr(web_app, "ArasCrawlerClient", FakeArasClient)
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "web-test.db"))
    app = web_app.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


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
    assert payload == {
        "ok": True,
        "data": {
            "rows": [{"_no": "EWO-1", "state": "Open", "note": "Cookie: [redacted] Authorization: [redacted]"}],
            "page": 2,
            "item_ids": ["ID-1"],
            "count": 1,
        },
    }
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
    assert progress.get_json()["data"] == {"file_name": "progress.xlsx", "record_id": "REC-1"}
    assert "file_id" not in progress.get_data(as_text=True)
    assert "FILE-secret2" not in progress.get_data(as_text=True)
    assert "secret2" not in progress.get_data(as_text=True)
    assert detail.status_code == 200
    assert detail.get_json()["data"] == {"file_name": "detail.xlsx"}
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
    assert query.get_json()["data"]["rows"] == [
        {"_no": "PAA-1", "state": "Open", "note": "Set-Cookie: [redacted] Authorization: [redacted]"}
    ]
    assert query.get_json()["data"]["page"] == 3
    assert crawl.status_code == 200
    assert crawl.get_json()["data"]["rows"] == [
        {"_no": "PAA-2", "state": "Closed", "note": "Cookie: [redacted] Authorization: [redacted] token=[redacted]"}
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


def test_cli_aras_connection_defaults_browser_headers(monkeypatch) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_ask(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((args, kwargs))
        prompt = str(args[0])
        if prompt.startswith("Aras base_url"):
            return ""
        if prompt.startswith("Extra headers"):
            return kwargs["default"]
        return ""

    monkeypatch.setattr(main.Prompt, "ask", fake_ask)

    base_url, headers, cookies = main._ask_aras_connection()

    assert base_url == ""
    assert cookies is None
    assert headers == {}
    base_call = next((args, kwargs) for args, kwargs in calls if str(args[0]).startswith("Aras base_url"))
    assert base_call[1]["default"] == ""
    assert not any(str(args[0]).startswith("Cookie header") for args, _kwargs in calls)


def test_cli_aras_connection_cookie_header_is_plain_and_normalized(monkeypatch) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    answers = iter(
        [
            "http://aras.example/innovatorserver",
            "",
        ]
    )
    input_lines = iter(["", "Cookie: sid=abc; token=x", ""])

    def fake_ask(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((args, kwargs))
        return next(answers)

    monkeypatch.setattr(main.Prompt, "ask", fake_ask)
    console = Console(record=True, width=140)
    monkeypatch.setattr(console, "input", lambda *args, **kwargs: next(input_lines))
    monkeypatch.setattr(main, "console", console)

    base_url, headers, cookies = main._ask_aras_connection()

    assert base_url == "http://aras.example/innovatorserver"
    assert headers["Cookie"] == "sid=abc; token=x"
    assert cookies is None
    assert not any(str(args[0]).startswith("Cookie header") for args, _kwargs in calls)


def test_cli_aras_connection_multiline_cookie_paste_stays_in_cookie_prompt(monkeypatch) -> None:
    answers = iter(["http://aras.example/innovatorserver", ""])
    input_lines = iter(
        [
            "",
            "Cookie: sid=abc; token=x",
            "ASP.NET_SessionId=should-not-be-filter",
            "",
        ]
    )
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: next(answers))
    console = Console(record=True, width=140)
    monkeypatch.setattr(console, "input", lambda *args, **kwargs: next(input_lines))
    monkeypatch.setattr(main, "console", console)

    _base_url, headers, _cookies = main._ask_aras_connection()

    assert headers["Cookie"] == "sid=abc; token=x"


def test_cli_aras_connection_ignores_cookie_control_characters(monkeypatch) -> None:
    answers = iter(["http://aras.example", ""])
    input_lines = iter(["", "\x16", ""])
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: next(answers))
    console = Console(record=True, width=140)
    monkeypatch.setattr(console, "input", lambda *args, **kwargs: next(input_lines))
    monkeypatch.setattr(main, "console", console)

    _base_url, headers, _cookies = main._ask_aras_connection()

    assert "Cookie" not in headers
    assert "control characters" in console.export_text()


def test_cli_aras_connection_accepts_multiline_authorization_headers(monkeypatch) -> None:
    answers = iter(["http://aras.example/innovatorserver"])
    input_lines = iter(
        [
            "Authorization: Bearer fake-token",
            "Cookie: sid=abc; token=x",
            "Accept-Language: zh-CN,zh;q=0.9",
            "",
            "",
        ]
    )
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: next(answers))
    console = Console(record=True, width=140)
    monkeypatch.setattr(console, "input", lambda *args, **kwargs: next(input_lines))
    monkeypatch.setattr(main, "console", console)

    _base_url, headers, _cookies = main._ask_aras_connection()

    assert headers["Authorization"] == "Bearer fake-token"
    assert headers["Cookie"] == "sid=abc; token=x"
    assert headers["Accept-Language"] == "zh-CN,zh;q=0.9"
    assert "可能需要 Authorization" not in console.export_text()


def test_cli_paa_helper_collects_filters_and_limits(monkeypatch) -> None:
    answers = iter(
        [
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
    assert (page, page_size, max_records, max_pages) == (3, 25, 100, 7)


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


def test_cli_ncr_handlers_progress_and_detail(monkeypatch) -> None:
    for choice, method, title in [
        ("2", "progress", "NCR approval progress result"),
        ("3", "detail", "NCR approval detail result"),
    ]:
        FakeArasClient.calls = []
        FakeArasClient.fail = None
        filters = main.NCRApprovalFilters(ncr_no="NCR-1")
        monkeypatch.setattr(main, "ArasCrawlerClient", FakeArasClient)
        monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: choice)
        monkeypatch.setattr(main, "_ask_aras_connection", lambda: ("http://aras.example", {}, None))
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


def test_cli_paa_handler_page_query(monkeypatch) -> None:
    FakeArasClient.calls = []
    FakeArasClient.fail = None
    filters = main.PAAReportFilters(paa_no="PAA-1")
    monkeypatch.setattr(main, "ArasCrawlerClient", FakeArasClient)
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: "4")
    monkeypatch.setattr(main, "_ask_aras_connection", lambda: ("http://aras.example", {"Authorization": "secret"}, None))
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


def test_cli_paa_handler_full_crawl(monkeypatch) -> None:
    FakeArasClient.calls = []
    FakeArasClient.fail = None
    filters = main.PAAReportFilters(ewo_no="EWO-1")
    monkeypatch.setattr(main, "ArasCrawlerClient", FakeArasClient)
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: "5")
    monkeypatch.setattr(main.Confirm, "ask", lambda *args, **kwargs: True)
    monkeypatch.setattr(main, "_ask_aras_connection", lambda: ("http://aras.example", {}, None))
    monkeypatch.setattr(main, "_ask_paa_filters", lambda: (filters, 9, 40, 120, 6))
    console = Console(record=True, width=140)
    monkeypatch.setattr(main, "console", console)

    main.handle_intranet_scrape(None)  # type: ignore[arg-type]

    method_call = next(call for call in FakeArasClient.calls if call.get("method") == "paa_all")
    assert method_call["filters"] == filters
    assert method_call["page_size"] == 40
    assert method_call["max_pages"] == 6
    assert method_call["max_records"] == 120
    assert "PAA report result" in console.export_text()


def test_cli_paa_handler_full_crawl_cancel(monkeypatch) -> None:
    FakeArasClient.calls = []
    FakeArasClient.fail = None
    filters = main.PAAReportFilters(ewo_no="EWO-1")
    monkeypatch.setattr(main, "ArasCrawlerClient", FakeArasClient)
    monkeypatch.setattr(main.Prompt, "ask", lambda *args, **kwargs: "5")
    monkeypatch.setattr(main.Confirm, "ask", lambda *args, **kwargs: False)
    monkeypatch.setattr(main, "_ask_aras_connection", lambda: ("http://aras.example", {}, None))
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
    assert not re.search(r"(?:cookie|token|authorization|sessionid|csrf).{0,80}localStorage", cli_web_text, re.IGNORECASE)
    assert ("session" + "Storage") not in cli_web_text
    assert ("console" + ".log(") not in cli_web_text
    assert not re.search(
        r"requests\.(?:get|post|head|request)\(",
        Path("tests/test_aras_cli_web.py").read_text(encoding="utf-8-sig"),
    )
