from __future__ import annotations

import ast
import re
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from services.aras_crawler import (
    DEFAULT_PAA_SELECT_FIELDS,
    ArasCrawlerClient,
    ArasCrawlerError,
    PAAReportFilters,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "crawler"


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200, reason: str = "", url: str = "") -> None:
        self.text = text
        self.status_code = status_code
        self.reason = reason
        self.url = url

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeCookieJar(dict):
    def update(self, values):  # type: ignore[no-untyped-def]
        super().update(values)


class FakeSession:
    def __init__(self, responses: list[FakeResponse] | None = None) -> None:
        self.responses = responses or []
        self.calls: list[dict[str, object]] = []
        self.cookies = FakeCookieJar()

    def post(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"method": "POST", "url": url, **kwargs})
        if not self.responses:
            raise AssertionError("unexpected POST")
        return self.responses.pop(0)

    def get(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"method": "GET", "url": url, **kwargs})
        if not self.responses:
            raise AssertionError("unexpected GET")
        return self.responses.pop(0)

    def head(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"method": "HEAD", "url": url, **kwargs})
        raise AssertionError("HEAD should not be called by PAA query methods")


def fixture_text(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8-sig")


def payload_item(payload: str) -> ET.Element:
    root = ET.fromstring(payload)
    return next(node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "Item")


def test_query_paa_report_maps_route_headers_paging_select_and_empty_filters() -> None:
    session = FakeSession([FakeResponse(fixture_text("paa_query_page_1.xml"))])
    client = ArasCrawlerClient(
        "http://aras.example",
        session=session,  # type: ignore[arg-type]
        headers={"Origin": "http://aras.example", "SOAPAction": "WrongAction"},
        cookies={"sid": "fake-session"},
        timeout=9,
    )

    result = client.query_paa_report(page=3, page_size=25, max_records=100)

    assert session.cookies["sid"] == "fake-session"
    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "http://aras.example/innovatorserver/Server/InnovatorServer.aspx"
    assert call["timeout"] == 9
    assert call["headers"]["SOAPAction"] == "ApplyItem"
    assert call["headers"]["Content-Type"] == "text/xml; charset=UTF-8"
    assert call["headers"]["Origin"] == "http://aras.example"
    assert call["headers"]["Referer"] == "http://aras.example/innovatorserver/Client/default.aspx"
    assert call["headers"]["Accept-Encoding"] == "gzip, deflate"
    assert call["headers"]["Accept-Language"] == "zh-CN,zh;q=0.9"
    assert call["headers"]["Connection"] == "keep-alive"
    assert "Mozilla/5.0" in call["headers"]["User-Agent"]
    item = payload_item(str(call["data"]))
    assert item.get("type") == "PAA_O"
    assert item.get("action") == "get"
    assert item.get("page") == "3"
    assert item.get("pagesize") == "25"
    assert item.get("maxRecords") == "100"
    assert item.get("returnMode") == "itemsOnly"
    assert item.get("select") == ",".join(DEFAULT_PAA_SELECT_FIELDS)
    assert list(item) == []
    assert result.page == 1
    assert result.item_ids == ["ID_PLACEHOLDER_001", "ID_PLACEHOLDER_002"]
    assert result.rows[0]["_no"] == "PAA000001"
    assert result.rows[0]["_est_cmpl_date"] is None
    assert result.rows[1]["keyed_name"] == "PAA000002"


def test_default_requests_session_disables_environment_proxy_settings() -> None:
    client = ArasCrawlerClient("http://aras.example")

    assert getattr(client.session, "trust_env", None) is False


def test_query_paa_report_can_prewarm_client_context_before_post() -> None:
    session = FakeSession([FakeResponse("<html/>"), FakeResponse(fixture_text("paa_query_page_1.xml"))])
    client = ArasCrawlerClient(
        "http://aras.example",
        session=session,  # type: ignore[arg-type]
        headers={"Cookie": "sid=secret-cookie", "Authorization": "Bearer secret-auth"},
        prewarm=True,
    )

    client.query_paa_report(page=1)

    assert [call["method"] for call in session.calls] == ["GET", "POST"]
    warmup, post = session.calls
    assert warmup["url"] == "http://aras.example/innovatorserver/Client/default.aspx"
    assert warmup["headers"]["Accept"].startswith("text/html")
    assert warmup["headers"]["Accept-Encoding"] == "gzip, deflate"
    assert warmup["headers"]["Cookie"] == "sid=secret-cookie"
    assert warmup["headers"]["Authorization"] == "Bearer secret-auth"
    assert post["url"] == "http://aras.example/innovatorserver/Server/InnovatorServer.aspx"
    assert post["headers"]["Cookie"] == "sid=secret-cookie"
    assert post["headers"]["Authorization"] == "Bearer secret-auth"


def test_prewarm_app_root_base_url_does_not_duplicate_innovatorserver() -> None:
    session = FakeSession([FakeResponse("<html/>"), FakeResponse(fixture_text("paa_query_page_1.xml"))])
    client = ArasCrawlerClient(
        "http://aras.example/innovatorserver",
        session=session,  # type: ignore[arg-type]
        prewarm=True,
    )

    client.query_paa_report(page=1)

    warmup, post = session.calls
    assert warmup["url"] == "http://aras.example/innovatorserver/Client/default.aspx"
    assert post["url"] == "http://aras.example/innovatorserver/Server/InnovatorServer.aspx"
    assert "/innovatorserver/innovatorserver/" not in str(warmup["url"]).lower()
    assert "/innovatorserver/innovatorserver/" not in str(post["url"]).lower()


def test_query_paa_report_prewarm_error_does_not_leak_credentials() -> None:
    session = FakeSession(
        [
            FakeResponse(
                "warmup failed "
                + "Cook"
                + "ie: sid=secret-cookie "
                + "Authori"
                + "zation: Bearer secret-auth "
                + "tok"
                + "en=tok123",
                status_code=401,
                reason="Unauthorized",
                url="http://aras.example/innovatorserver/Client/default.aspx",
            )
        ]
    )
    client = ArasCrawlerClient(
        "http://aras.example",
        session=session,  # type: ignore[arg-type]
        headers={"Cookie": "sid=secret-cookie", "Authorization": "Bearer secret-auth"},
        prewarm=True,
    )

    with pytest.raises(ArasCrawlerError) as excinfo:
        client.query_paa_report(page=1)

    message = str(excinfo.value)
    assert "Aras context warmup failed" in message
    assert "secret-cookie" not in message
    assert "secret-auth" not in message
    assert "tok123" not in message


def test_query_paa_report_maps_inferred_filters_and_custom_select() -> None:
    session = FakeSession([FakeResponse(fixture_text("paa_query_page_1.xml"))])
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]

    client.query_paa_report(
        PAAReportFilters(
            paa_no="PAA000001",
            ewo_no="EWO000001",
            state="DRAFT1",
            area="AREA",
            base="BASE",
            vehicle_keyword="VEHICLE",
            submit_start="2026-01-01",
            submit_end="2026-12-31",
            mtl_rq_start="2026-02-01",
            mtl_rq_end="2026-11-30",
        ),
        select_fields=("_no", "state"),
    )

    payload = str(session.calls[0]["data"])
    item = payload_item(payload)
    assert item.get("select") == "_no,state"
    assert "<_no>PAA000001</_no>" in payload
    assert "<_ewo_no>EWO000001</_ewo_no>" in payload
    assert "<state>DRAFT1</state>" in payload
    assert '<_area condition="like">AREA</_area>' in payload
    assert '<_base condition="like">BASE</_base>' in payload
    assert '<_vehicles condition="like">%VEHICLE%</_vehicles>' in payload
    assert '<_submit_date condition="ge">2026-01-01</_submit_date>' in payload
    assert '<_submit_date condition="le">2026-12-31</_submit_date>' in payload
    assert '<_mtl_rq_date condition="ge">2026-02-01</_mtl_rq_date>' in payload
    assert '<_mtl_rq_date condition="le">2026-11-30</_mtl_rq_date>' in payload


def test_paa_department_or_and_vehicle_and_are_contains_predicates_on_every_page() -> None:
    client = ArasCrawlerClient("http://aras.example", session=object(), prewarm=False)  # type: ignore[arg-type]
    filters = PAAReportFilters(
        department_keyword="  Body Engineering  ",
        vehicle_keyword="  F610S  ",
    )

    page_one = client._build_paa_payload(filters, 1, 50, 12000, None)
    page_two = client._build_paa_payload(filters, 2, 50, 12000, None)

    grouped = (
        '<and><or><_pe_tdc_department condition="like">%Body Engineering%</_pe_tdc_department>'
        '<_requester_department condition="like">%Body Engineering%</_requester_department></or>'
        '<_vehicles condition="like">%F610S%</_vehicles></and>'
    )
    assert grouped in page_one
    assert page_one.replace('page="1"', 'page="2"', 1) == page_two


def test_paa_blank_department_and_vehicle_emit_no_grouping() -> None:
    client = ArasCrawlerClient("http://aras.example", session=object(), prewarm=False)  # type: ignore[arg-type]

    payload = client._build_paa_payload(
        PAAReportFilters(department_keyword="  ", vehicle_keyword="\t"),
        1,
        50,
        12000,
        None,
    )

    assert "<_pe_tdc_department" not in payload
    assert "<_requester_department" not in payload
    assert "<_vehicles" not in payload
    assert "<and>" not in payload


def test_parse_paa_report_response_rejects_bad_or_missing_result_xml() -> None:
    with pytest.raises(ArasCrawlerError):
        ArasCrawlerClient.parse_paa_report_response("")
    with pytest.raises(ArasCrawlerError):
        ArasCrawlerClient.parse_paa_report_response("<not-xml")
    with pytest.raises(ArasCrawlerError):
        ArasCrawlerClient.parse_paa_report_response("<SOAP-ENV:Envelope xmlns:SOAP-ENV='x' />")


def test_query_paa_report_never_exposes_http_error_body_or_credentials() -> None:
    session = FakeSession(
        [
            FakeResponse(
                "<Fault>bad request "
                + "Cook"
                + "ie: sid=secret-token; ArasAuth=secret2; JSESSIONID=secret3 "
                + "Set-"
                + "Cook"
                + "ie: sid=abc123; ArasAuth=secret4; JSESSIONID=secret5\nNext: ok "
                + "tok"
                + "en=abc123 missing context"
                + ("x" * 700)
                + "TAIL</Fault>",
                status_code=400,
                reason="Bad Request",
                url="http://aras.example/innovatorserver/Server/InnovatorServer.aspx",
            )
        ]
    )
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]

    with pytest.raises(ArasCrawlerError) as excinfo:
        client.query_paa_report()

    message = str(excinfo.value)
    assert message == "Aras HTTP 400 Bad Request; the response body was not exposed."
    assert "missing context" not in message
    assert "Next: ok" not in message
    assert "TAIL" not in message
    assert "secret-token" not in message
    assert "secret2" not in message
    assert "secret3" not in message
    assert "abc123" not in message
    assert "secret4" not in message
    assert "secret5" not in message


def test_crawl_paa_report_all_stops_on_empty_page() -> None:
    session = FakeSession(
        [
            FakeResponse(fixture_text("paa_query_page_1.xml")),
            FakeResponse(fixture_text("paa_query_empty.xml")),
        ]
    )
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]

    result = client.crawl_paa_report_all(page_size=2, max_pages=5, max_records=10)

    assert len(result.rows) == 2
    assert result.item_ids == ["ID_PLACEHOLDER_001", "ID_PLACEHOLDER_002"]
    assert [payload_item(str(call["data"])).get("page") for call in session.calls] == ["1", "2"]
    assert [call["method"] for call in session.calls] == ["POST", "POST"]


def test_crawl_paa_report_all_stops_on_short_page() -> None:
    session = FakeSession(
        [
            FakeResponse(fixture_text("paa_query_page_1.xml")),
            FakeResponse(fixture_text("paa_query_short_page.xml")),
        ]
    )
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]

    result = client.crawl_paa_report_all(page_size=2, max_pages=5, max_records=10)

    assert [row["_no"] for row in result.rows] == ["PAA000001", "PAA000002", "PAA000003"]
    assert result.page == 2
    assert len(session.calls) == 2


def test_crawl_paa_report_all_honors_max_pages_fuse() -> None:
    session = FakeSession(
        [
            FakeResponse(fixture_text("paa_query_page_1.xml")),
            FakeResponse(fixture_text("paa_query_page_1.xml")),
            FakeResponse(fixture_text("paa_query_page_1.xml")),
        ]
    )
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]

    result = client.crawl_paa_report_all(page_size=2, max_pages=2, max_records=10)

    assert len(result.rows) == 4
    assert [payload_item(str(call["data"])).get("page") for call in session.calls] == ["1", "2"]


def test_crawl_paa_report_all_honors_max_records_fuse_and_truncates() -> None:
    session = FakeSession(
        [
            FakeResponse(fixture_text("paa_query_page_1.xml")),
            FakeResponse(fixture_text("paa_query_page_1.xml")),
        ]
    )
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]

    result = client.crawl_paa_report_all(page_size=2, max_pages=5, max_records=3)

    assert len(result.rows) == 3
    assert len(result.item_ids) == 3
    assert [payload_item(str(call["data"])).get("page") for call in session.calls] == ["1", "2"]


def test_crawl_paa_report_all_rejects_non_positive_fuses() -> None:
    client = ArasCrawlerClient("http://aras.example", session=FakeSession())  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        client.crawl_paa_report_all(page_size=0)
    with pytest.raises(ValueError):
        client.crawl_paa_report_all(max_pages=0)
    with pytest.raises(ValueError):
        client.crawl_paa_report_all(max_records=0)


def test_static_guard_paa_scope_has_no_real_credentials_or_direct_network_and_uses_xml_parser() -> None:
    checked_files = [
        Path("services/aras_crawler.py"),
        Path("tests/test_aras_paa_crawler.py"),
        *FIXTURE_DIR.glob("paa_*.xml"),
    ]
    sensitive_terms = [
        r"ecm\.sgmw\.com\.cn",
        "Set-" + "Cookie",
        "cs" + "rf",
        "Authori" + r"zation\s*[:=]",
        "Cook" + r"ie\s*[:=]",
        "tok" + "en=",
    ]
    sensitive = re.compile(r"(?:%s)" % "|".join(sensitive_terms), re.IGNORECASE)
    direct_http = re.compile(r"requests\.(?:get|post|head|request)\(")
    forbidden_ui = re.compile(r"\b(?:rich|flask|render_template|jsonify|document\.|window\.)\b")

    for path in checked_files:
        text = path.read_text(encoding="utf-8-sig")
        assert not sensitive.search(text), path
        assert not direct_http.search(text), path
    assert not forbidden_ui.search(Path("services/aras_crawler.py").read_text(encoding="utf-8-sig"))

    service_tree = ast.parse(Path("services/aras_crawler.py").read_text(encoding="utf-8-sig"))
    parse_paa = next(
        node for node in ast.walk(service_tree) if isinstance(node, ast.FunctionDef) and node.name == "parse_paa_report_response"
    )
    calls = [
        node
        for node in ast.walk(parse_paa)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "loads"
    ]
    assert calls == []
