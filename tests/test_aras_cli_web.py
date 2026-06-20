from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

import main
import web.app as web_app
from services.aras_crawler import ArasCrawlerError, EWOReportPage


@dataclass
class FakeProgress:
    file_id: str = "FILE-1"
    file_name: str = "progress.xlsx"
    record_id: str = "REC-1"


@dataclass
class FakeDetail:
    file_name: str = "detail.xlsx"


class FakeArasClient:
    calls: list[dict[str, object]] = []
    fail: Exception | None = None

    def __init__(self, base_url, headers=None, cookies=None, timeout=30.0):  # type: ignore[no-untyped-def]
        self.base_url = base_url
        self.headers = headers or {}
        self.cookies = cookies
        self.timeout = timeout
        self.__class__.calls.append(
            {"base_url": base_url, "headers": self.headers, "cookies": cookies, "timeout": timeout}
        )

    def query_ewo_report(self, filters, page=1, page_size=50, max_records=2000):  # type: ignore[no-untyped-def]
        if self.fail:
            raise self.fail
        self.__class__.calls.append(
            {"method": "ewo", "filters": filters, "page": page, "page_size": page_size, "max_records": max_records}
        )
        return EWOReportPage(rows=[{"_no": "EWO-1", "state": "Open"}], page=page, item_ids=["ID-1"], raw_xml="<xml/>")

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


@pytest.fixture()
def client(monkeypatch):
    FakeArasClient.calls = []
    FakeArasClient.fail = None
    monkeypatch.setattr(web_app, "ArasCrawlerClient", FakeArasClient)
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
        "data": {"rows": [{"_no": "EWO-1", "state": "Open"}], "page": 2, "item_ids": ["ID-1"], "count": 1},
    }
    init_call = FakeArasClient.calls[0]
    assert init_call["base_url"] == "http://aras.example"
    assert init_call["headers"]["Cookie"] == "sid=secret-cookie"  # type: ignore[index]
    assert "secret-cookie" not in resp.get_data(as_text=True)
    assert "secret-auth" not in resp.get_data(as_text=True)
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
    assert progress.get_json()["data"] == {"file_id": "FILE-1", "file_name": "progress.xlsx", "record_id": "REC-1"}
    assert detail.status_code == 200
    assert detail.get_json()["data"] == {"file_name": "detail.xlsx"}
    progress_call = next(call for call in FakeArasClient.calls if call.get("method") == "progress")
    assert progress_call["filters"].project_names == ("F610S", "F610S DG")
    assert progress_call["filters"].othercondition == "1"


def test_route_validation_and_aras_error_are_sanitized(client) -> None:
    missing = client.post("/api/aras/ewo/query", json={"filters": {}})
    assert missing.status_code == 400
    assert missing.get_json()["ok"] is False

    FakeArasClient.fail = ArasCrawlerError(
        'upstream failed Cookie: sid=abc123 Authorization: Bearer xyz789 token=tok123 '
        '"token":"tok123" {\'Authorization\': \'Bearer xyz789\'}'
    )
    failed = client.post("/api/aras/ewo/query", json={"base_url": "http://aras.example", "cookie": "sid=abc123"})
    text = failed.get_data(as_text=True)
    assert failed.status_code == 502
    assert failed.get_json()["error"]["type"] == "ArasCrawlerError"
    assert "abc123" not in text
    assert "xyz789" not in text
    assert "tok123" not in text

    cli_text = main._safe_error_message(
        ArasCrawlerError("upstream failed sid=abc123 Bearer xyz789 token=tok123 api_key=key456")
    )
    assert "abc123" not in cli_text
    assert "xyz789" not in cli_text
    assert "tok123" not in cli_text
    assert "key456" not in cli_text


def test_cli_helpers_parse_headers_and_render_without_auth() -> None:
    headers = main._parse_header_lines("X-Test: yes, Authorization: secret")
    assert headers == {"X-Test": "yes", "Authorization": "secret"}

    table = main._render_ewo_result(
        EWOReportPage(rows=[{"_no": "EWO-1", "state": "Open"}], page=1, item_ids=["ID-1"], raw_xml="<xml/>")
    )
    assert table.title == "EWO 查询结果 | page=1 rows=1 items=1"
    assert "secret" not in repr(table)


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
            "tests/test_aras_cli_web.py",
        ]
    )
    assert ("local" + "Storage") not in cli_web_text
    assert ("session" + "Storage") not in cli_web_text
    assert ("console" + ".log(") not in cli_web_text
    assert not re.search(
        r"requests\.(?:get|post|head|request)\(",
        Path("tests/test_aras_cli_web.py").read_text(encoding="utf-8-sig"),
    )
