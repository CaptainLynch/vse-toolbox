from __future__ import annotations

import re
from pathlib import Path

import pytest

from services.aras_crawler import (
    DEFAULT_EWO_SELECT_FIELDS,
    ArasAuthenticationError,
    ArasCrawlerClient,
    ArasCrawlerError,
    EWOReportFilters,
    NCRApprovalFilters,
    NCRExportResult,
    PAAReportFilters,
)
from services.windows_http import WinHTTPTimeoutError
from services.aras_department_mapping import (
    NCR_SECTION_CODES,
    NCR_SECTION_CODES_BY_DEPARTMENT_V1,
    normalize_departments,
    resolve_ncr_section_codes,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "crawler"


class FakeResponse:
    def __init__(
        self,
        text: str,
        status_code: int = 200,
        reason: str = "",
        url: str = "",
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
    ) -> None:
        self.text = text
        self.status_code = status_code
        self.reason = reason
        self.url = url
        self.headers = headers or {}
        self.content = content if content is not None else text.encode("utf-8")

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
        raise AssertionError("HEAD should not be called by query methods")


def fixture_text(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8-sig")


def ewo_response(page: object, numbers: list[str]) -> str:
    items = "".join(
        f'<Item type="EWO_O" id="ID-{number}" page="{page}"><_no>{number}</_no></Item>'
        for number in numbers
    )
    return (
        '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">'
        f"<SOAP-ENV:Body><Result>{items}</Result></SOAP-ENV:Body></SOAP-ENV:Envelope>"
    )


def test_query_ewo_report_maps_route_headers_filters_and_parses_rows() -> None:
    session = FakeSession([FakeResponse(fixture_text("ewo_query_response.xml"))])
    client = ArasCrawlerClient(
        "http://aras.example",
        session=session,  # type: ignore[arg-type]
        headers={"Origin": "http://aras.example", "X-Caller": "unit"},
        cookies={"sid": "fake-session"},
    )

    result = client.query_ewo_report(
        EWOReportFilters(
            ewo_no="EWO-1",
            project_code="F610S",
            subject_keyword="seat",
            area="GA",
            submit_start="2026-01-01",
            submit_end="2026-12-31",
        ),
        page=2,
        page_size=25,
        max_records=100,
    )

    assert session.cookies["sid"] == "fake-session"
    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "http://aras.example/innovatorserver/Server/InnovatorServer.aspx"
    headers = call["headers"]
    assert headers["SOAPAction"] == "ApplyItem"
    assert headers["Content-Type"] == "text/xml; charset=UTF-8"
    assert headers["Origin"] == "http://aras.example"
    assert headers["X-Caller"] == "unit"
    payload = call["data"]
    assert 'type="EWO_O" action="get" page="2"' in payload
    assert 'pagesize="25"' in payload
    assert 'maxRecords="100"' in payload
    assert f'select="{",".join(DEFAULT_EWO_SELECT_FIELDS)}"' in payload
    assert "<_no>EWO-1</_no>" in payload
    assert "<eplmwriteneplcode>F610S</eplmwriteneplcode>" in payload
    assert '<_subject condition="like">seat</_subject>' in payload
    assert '<_area condition="like">GA</_area>' in payload
    assert '<_submit_time condition="ge">2026-01-01</_submit_time>' in payload
    assert '<_submit_time condition="le">2026-12-31</_submit_time>' in payload
    assert result.page == 1
    assert result.item_ids
    assert result.rows
    assert result.rows[0]["_no"] is not None
    assert "_affect_service_type" in result.rows[0]
    assert result.raw_xml.startswith("<SOAP-ENV:Envelope")


def test_query_paa_report_filters_department_without_requester_condition() -> None:
    session = FakeSession(
        [
            FakeResponse(
                '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">'
                '<SOAP-ENV:Body><Result><Item type="PAA_O" id="PAA-1" page="1">'
                "<_no>PAA-1</_no></Item></Result></SOAP-ENV:Body></SOAP-ENV:Envelope>"
            )
        ]
    )
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]

    result = client.query_paa_report(PAAReportFilters(department="技术中心_车体工程"))

    call = session.calls[0]
    assert call["method"] == "POST"
    payload = call["data"]
    assert 'type="PAA_O" action="get" page="1"' in payload
    assert "<_pe_tdc_department>技术中心_车体工程</_pe_tdc_department>" in payload
    assert "<_pe_tdc_department condition=" not in payload
    assert "<_requester_department" not in payload
    assert result.rows[0]["_no"] == "PAA-1"


def test_ewo_and_paa_search_patterns_generate_like_and_or_aml() -> None:
    session = FakeSession(
        [
            FakeResponse(fixture_text("ewo_query_response.xml")),
            FakeResponse(
                '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">'
                "<SOAP-ENV:Body><Result /></SOAP-ENV:Body></SOAP-ENV:Envelope>"
            ),
        ]
    )
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]

    client.query_ewo_report(
        EWOReportFilters(ewo_no="*171|*172", project_code="*310S*730S*|*730S*310S*")
    )
    client.query_paa_report(PAAReportFilters(vehicle_keyword="*310S*|*730S*"))

    ewo_payload = str(session.calls[0]["data"])
    paa_payload = str(session.calls[1]["data"])
    assert (
        "<or><_no condition=\"like\">*171</_no>"
        "<_no condition=\"like\">*172</_no></or>"
    ) in ewo_payload
    assert (
        "<or><eplmwriteneplcode condition=\"like\">*310S*730S*</eplmwriteneplcode>"
        "<eplmwriteneplcode condition=\"like\">*730S*310S*</eplmwriteneplcode></or>"
    ) in ewo_payload
    assert (
        "<or><_vehicles condition=\"like\">*310S*</_vehicles>"
        "<_vehicles condition=\"like\">*730S*</_vehicles></or>"
    ) in paa_payload


def test_search_patterns_keep_exact_and_enum_fields_exact() -> None:
    session = FakeSession([FakeResponse(fixture_text("ewo_query_response.xml"))])
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]

    client.query_ewo_report(
        EWOReportFilters(
            ewo_no="EWO-1|*EWO-2*",
            change_type="PWO",
            state="OPEN",
        )
    )

    payload = str(session.calls[0]["data"])
    assert (
        "<or><_no>EWO-1</_no>"
        "<_no condition=\"like\">*EWO-2*</_no></or>"
    ) in payload
    assert "<_sort_type>PWO</_sort_type>" in payload
    assert "<state>OPEN</state>" in payload
    assert "<_sort_type condition=" not in payload
    assert "<state condition=" not in payload


@pytest.mark.parametrize(
    "expression",
    ["A||B", "|A", "A|", "|".join(f"value-{index}" for index in range(11)), "x" * 501],
)
def test_search_patterns_reject_empty_oversized_or_excessive_alternatives(expression: str) -> None:
    client = ArasCrawlerClient("http://aras.example", session=FakeSession())  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        client.query_ewo_report(EWOReportFilters(ewo_no=expression))


def test_query_ewo_report_emits_diagnostic_http_event() -> None:
    events = []
    session = FakeSession([FakeResponse(fixture_text("ewo_query_response.xml"))])
    client = ArasCrawlerClient(
        "http://aras.example",
        session=session,  # type: ignore[arg-type]
        headers={"Authorization": "Bearer fake-token"},
        diagnostic_hook=events.append,
    )

    result = client.query_ewo_report(EWOReportFilters(ewo_no="EWO-1"))

    assert result.rows
    assert len(events) == 1
    event = events[0]
    assert event.stage == "soap-ApplyItem"
    assert event.method == "POST"
    assert event.status_code == 200
    assert "Bearer fake-token" in event.request_headers["Authorization"]
    assert event.request_body is not None
    assert "<_no>EWO-1</_no>" in event.request_body


def test_crawl_ewo_report_all_paginates_and_honors_record_limit() -> None:
    session = FakeSession(
        [
            FakeResponse(ewo_response(1, ["EWO-1", "EWO-2"])),
            FakeResponse(ewo_response(2, ["EWO-3", "EWO-4"])),
        ]
    )
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]

    result = client.crawl_ewo_report_all(page_size=2, max_pages=5, max_records=3)

    assert [row["_no"] for row in result.rows] == ["EWO-1", "EWO-2", "EWO-3"]
    assert result.item_ids == ["ID-EWO-1", "ID-EWO-2", "ID-EWO-3"]
    assert len(session.calls) == 2
    assert 'page="1"' in session.calls[0]["data"]
    assert 'page="2"' in session.calls[1]["data"]


def test_query_ewo_report_rejects_login_html_as_authentication_error() -> None:
    session = FakeSession(
        [
            FakeResponse(
                '<html><form class="login-form"><input type="password"></form></html>',
                headers={"Content-Type": "text/html; charset=UTF-8"},
            )
        ]
    )
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]

    with pytest.raises(ArasAuthenticationError, match="returned a login page"):
        client.query_ewo_report(EWOReportFilters())


def test_prewarm_rejects_login_html_before_posting_credentials() -> None:
    session = FakeSession()
    session.get = lambda *args, **kwargs: FakeResponse(  # type: ignore[method-assign]
        '<html><form><input type="password"></form></html>',
        headers={"Content-Type": "text/html"},
    )
    client = ArasCrawlerClient("http://aras.example", session=session, prewarm=True)  # type: ignore[arg-type]

    with pytest.raises(ArasAuthenticationError, match="context warmup returned a login page"):
        client.query_ewo_report(EWOReportFilters())

    assert not any(call["method"] == "POST" for call in session.calls)


def test_ewo_parser_tolerates_non_numeric_page_attribute() -> None:
    result = ArasCrawlerClient.parse_ewo_report_response(ewo_response("unknown", ["EWO-1"]))

    assert result.page is None
    assert result.rows[0]["_no"] == "EWO-1"


def test_query_ewo_report_caps_untrusted_server_rows() -> None:
    session = FakeSession([FakeResponse(ewo_response(1, ["EWO-1", "EWO-2"]))])
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]

    result = client.query_ewo_report(EWOReportFilters(), page_size=50, max_records=1)

    assert [row["_no"] for row in result.rows] == ["EWO-1"]
    assert result.item_ids == ["ID-EWO-1"]


def test_app_root_base_url_does_not_duplicate_innovatorserver() -> None:
    session = FakeSession([FakeResponse(fixture_text("ewo_query_response.xml"))])
    client = ArasCrawlerClient("http://aras.example/innovatorserver", session=session)  # type: ignore[arg-type]

    client.query_ewo_report(EWOReportFilters(ewo_no="EWO-1"))

    call = session.calls[0]
    assert call["url"] == "http://aras.example/innovatorserver/Server/InnovatorServer.aspx"
    assert call["headers"]["Referer"] == "http://aras.example/innovatorserver/Client/default.aspx"
    assert "/innovatorserver/innovatorserver/" not in call["url"].lower()


def test_download_token_app_root_base_url_does_not_duplicate_innovatorserver() -> None:
    session = FakeSession([FakeResponse(fixture_text("download_token_response.json"))])
    client = ArasCrawlerClient("http://aras.example/innovatorserver", session=session)  # type: ignore[arg-type]

    client.get_file_download_token("FILE123")

    call = session.calls[0]
    assert str(call["url"]).startswith(
        "http://aras.example/innovatorserver/Server/AuthenticationBroker.asmx/GetFileDownloadToken?rnd="
    )
    assert "/innovatorserver/innovatorserver/" not in str(call["url"]).lower()


def test_401_bearer_error_includes_authentication_hint_without_leaking_token() -> None:
    session = FakeSession(
        [
            FakeResponse(
                "Authorization: Bearer secret-token is invalid",
                status_code=401,
                reason="Unauthorized",
                url="http://aras.example/innovatorserver/Server/InnovatorServer.aspx",
                headers={"WWW-Authenticate": "Bearer"},
            )
        ]
    )
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]

    with pytest.raises(ArasCrawlerError) as excinfo:
        client.query_ewo_report(EWOReportFilters())

    message = str(excinfo.value)
    assert "missing or expired Authorization Bearer token" in message
    assert "successful InnovatorServer.aspx browser request" in message
    assert "secret-token" not in message


def test_download_token_401_bearer_error_uses_authentication_hint() -> None:
    session = FakeSession(
        [
            FakeResponse(
                "token=secret-token",
                status_code=401,
                reason="Unauthorized",
                url="http://aras.example/innovatorserver/Server/AuthenticationBroker.asmx/GetFileDownloadToken",
                headers={"WWW-Authenticate": "Bearer"},
            )
        ]
    )
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]

    with pytest.raises(ArasCrawlerError) as excinfo:
        client.get_file_download_token("FILE123")

    message = str(excinfo.value)
    assert "missing or expired Authorization Bearer token" in message
    assert "secret-token" not in message


def test_ncr_progress_maps_cdata_payload_and_parses_export_record() -> None:
    session = FakeSession([FakeResponse(fixture_text("ncr_progress_response.xml"))])
    client = ArasCrawlerClient("http://aras.example/root", session=session)  # type: ignore[arg-type]

    result = client.query_ncr_approval_progress(
        NCRApprovalFilters(
            buy_start="2026-01-01",
            buy_end="2026-01-31",
            ncr_no="NCR-9",
            project_names=("F610S", "F610S DG"),
            section_code="SEC",
            change_type="type-a",
        )
    )

    call = session.calls[0]
    assert call["url"] == "http://aras.example/root/innovatorserver/Server/InnovatorServer.aspx"
    assert call["headers"]["SOAPAction"] == "ApplyMethod"
    payload = call["data"]
    assert 'action="sgmw_downloadFileProgressC"' in payload
    assert "<buystart><![CDATA[2026-01-01]]></buystart>" in payload
    assert "<buyend><![CDATA[2026-01-31]]></buyend>" in payload
    assert "<ncrno><![CDATA[NCR-9]]></ncrno>" in payload
    assert "<ncrname><![CDATA[F610S,F610S DG]]></ncrname>" in payload
    assert "<seccode><![CDATA[SEC]]></seccode>" in payload
    assert "<changetype><![CDATA[type-a]]></changetype>" in payload
    assert "<othercondition><![CDATA[0]]></othercondition>" in payload
    assert result.file_id == "68C519069E974AADA15ABEB4A7277BC5"
    assert result.file_name.endswith(".xlsx")
    assert result.record_id == "C4382C4265084C28AC107455C4C47690"


def test_ncr_detail_uses_detail_method_and_parses_file_name() -> None:
    session = FakeSession([FakeResponse(fixture_text("ncr_detail_response.xml"))])
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]

    result = client.extract_ncr_approval_detail(
        NCRApprovalFilters(project_names=("F610S", "F610S DG"), othercondition="1")
    )

    payload = session.calls[0]["data"]
    assert 'action="sgmw_downloadFileDetail4C"' in payload
    assert "<ncrname><![CDATA[F610S,F610S DG]]></ncrname>" in payload
    assert "<othercondition><![CDATA[1]]></othercondition>" in payload
    assert result.file_name.endswith(".xlsx")
    assert result.raw_xml.startswith("<SOAP-ENV:Envelope")
    assert session.calls[0]["timeout"] == (30.0, 240.0)


def test_ncr_filters_preserve_server_side_wildcard_and_union_syntax() -> None:
    session = FakeSession([FakeResponse(fixture_text("ncr_detail_response.xml"))])
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]

    client.extract_ncr_approval_detail(
        NCRApprovalFilters(ncr_no="*NCR-9*", project_names=("*610*|*730*",))
    )

    payload = str(session.calls[0]["data"])
    assert "<ncrno><![CDATA[*NCR-9*]]></ncrno>" in payload
    assert "<ncrname><![CDATA[*610*|*730*]]></ncrname>" in payload


def test_ncr_detail_timeout_uses_clear_safe_error_and_diagnostic_timeout() -> None:
    events = []

    class TimeoutSession(FakeSession):
        def post(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append({"method": "POST", "url": url, **kwargs})
            raise WinHTTPTimeoutError("WinHTTP request timed out")

    session = TimeoutSession()
    client = ArasCrawlerClient(
        "http://aras.example",
        session=session,  # type: ignore[arg-type]
        diagnostic_hook=events.append,
    )

    with pytest.raises(ArasCrawlerError, match="NCR 明细生成超时"):
        client.extract_ncr_approval_detail(NCRApprovalFilters(project_names=("F610S",)))

    assert session.calls[0]["timeout"] == (30.0, 240.0)
    assert events[-1].timeout == (30.0, 240.0)
    assert events[-1].exception == "WinHTTPTimeoutError()"


def test_get_file_download_token_posts_json_without_real_network() -> None:
    session = FakeSession([FakeResponse(fixture_text("download_token_response.json"))])
    client = ArasCrawlerClient("http://aras.example", session=session, timeout=7)  # type: ignore[arg-type]

    token = client.get_file_download_token("FILE123")

    call = session.calls[0]
    assert token == "<download_token>"
    assert call["method"] == "POST"
    assert call["url"].startswith(
        "http://aras.example/innovatorserver/Server/AuthenticationBroker.asmx/GetFileDownloadToken?rnd="
    )
    assert call["headers"]["SOAPAction"] == "GetFileDownloadToken"
    assert call["headers"]["Content-Type"] == "application/json; charset=UTF-8"
    assert call["data"] == '{"param":{"fileId":"FILE123"}}'
    assert call["timeout"] == 7


def test_parsers_reject_empty_or_malformed_responses() -> None:
    with pytest.raises(ArasCrawlerError):
        ArasCrawlerClient.parse_ewo_report_response("")
    with pytest.raises(ArasCrawlerError):
        ArasCrawlerClient.parse_ncr_progress_response("<Result />")
    with pytest.raises(ArasCrawlerError):
        ArasCrawlerClient.parse_ncr_detail_response("<Result />")
    with pytest.raises(ArasCrawlerError):
        ArasCrawlerClient.parse_download_token_response("{}")


def test_query_methods_do_not_call_get_or_head() -> None:
    session = FakeSession([FakeResponse(fixture_text("ncr_detail_response.xml"))])
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]

    client.extract_ncr_approval_detail(NCRApprovalFilters())

    assert [call["method"] for call in session.calls] == ["POST"]


def test_static_guard_blocks_direct_http_and_persisted_credentials() -> None:
    checked_files = [
        Path("services/aras_crawler.py"),
        Path("tests/test_aras_crawler.py"),
        *FIXTURE_DIR.glob("*"),
    ]
    credential_files = [
        Path("services/aras_crawler.py"),
        *FIXTURE_DIR.glob("*"),
    ]
    direct_http = re.compile(r"requests\.(?:get|post|head|request)\(")
    sensitive = re.compile(
        r"(?:Set-Cookie|csrf|sessionid=|token=|Authorization\s*[:=]|Cookie\s*[:=])",
        re.IGNORECASE,
    )

    for path in checked_files:
        text = path.read_text(encoding="utf-8-sig")
        assert not direct_http.search(text), path
    for path in credential_files:
        text = path.read_text(encoding="utf-8-sig")
        assert not sensitive.search(text), path
    assert fixture_text("download_token_response.json").strip() == '{"d":"<download_token>"}'


def test_department_mapping_normalizes_aliases_and_exposes_section_codes() -> None:
    normalized = normalize_departments(("技术中心-车体工程", "技术中心_车体工程"))

    assert normalized == ("技术中心_车体工程", "技术中心_车体工程")
    assert isinstance(normalized, tuple)
    assert isinstance(NCR_SECTION_CODES, tuple)
    assert NCR_SECTION_CODES == ("BA", "BE", "BI", "EXT", "INT", "SES", "VE")
    assert normalize_departments(()) == ()


def test_resolve_ncr_section_codes_maps_department_to_section_codes() -> None:
    resolved = resolve_ncr_section_codes(("技术中心-车体工程", "技术中心_车体工程"))

    assert resolved == ("BA", "BE", "BI", "EXT", "INT", "SES", "VE")
    assert isinstance(resolved, tuple)
    assert resolve_ncr_section_codes(()) == ()


def test_ncr_section_codes_mapping_is_versioned_and_immutable() -> None:
    from types import MappingProxyType

    assert isinstance(NCR_SECTION_CODES_BY_DEPARTMENT_V1, MappingProxyType)
    assert NCR_SECTION_CODES_BY_DEPARTMENT_V1["技术中心_车体工程"] == NCR_SECTION_CODES
    with pytest.raises(TypeError):
        NCR_SECTION_CODES_BY_DEPARTMENT_V1["研发部"] = ("XX",)  # type: ignore[index]


@pytest.mark.parametrize("bad_name", ["", "   ", None, "研发部", "车身工程"])
def test_resolve_ncr_section_codes_rejects_unknown_or_empty_departments(
    bad_name: str | None,
) -> None:
    with pytest.raises(ValueError):
        resolve_ncr_section_codes((bad_name,))


@pytest.mark.parametrize("bad_name", ["", "   ", None, "研发部", "车身工程"])
def test_department_mapping_rejects_unknown_or_empty_departments(bad_name: str | None) -> None:
    with pytest.raises(ValueError):
        normalize_departments((bad_name,))


def test_ncr_payload_merges_trimmed_deduped_section_codes() -> None:
    session = FakeSession([FakeResponse(fixture_text("ncr_detail_response.xml"))])
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]

    client.extract_ncr_approval_detail(
        NCRApprovalFilters(section_code=" BA ", section_codes=("BA", "EXT", " int ", "BA"))
    )

    payload = session.calls[0]["data"]
    assert "<seccode><![CDATA[BA,EXT,int]]></seccode>" in payload


def test_download_ncr_detail_file_uses_app_root_and_writes_atomically(tmp_path) -> None:
    payload = b"PK\x03\x04fake-xlsx-content"
    session = FakeSession(
        [
            FakeResponse("", content=payload, headers={"Content-Type": "application/octet-stream"}),
            FakeResponse("", content=payload, headers={"Content-Type": "application/octet-stream"}),
        ]
    )
    client = ArasCrawlerClient("http://aras.example/innovatorserver", session=session, timeout=9)  # type: ignore[arg-type]

    downloaded = client.download_ncr_detail_file("NCR 9.xlsx", tmp_path)

    assert downloaded == tmp_path / "NCR 9.xlsx"
    assert downloaded.read_bytes() == payload
    call = session.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == "http://aras.example/innovatorserver/Server/NcrReport/NCR%209.xlsx"
    assert "/innovatorserver/innovatorserver/" not in call["url"].lower()
    assert call["timeout"] == 9

    named = client.download_ncr_detail_file("NCR-9.xlsx", tmp_path / "custom.bin")
    assert named == tmp_path / "custom.bin"
    assert named.read_bytes() == payload
    assert len(session.calls) == 2


@pytest.mark.parametrize(
    "bad_name",
    ["", "   ", ".", "..", "a/b.xlsx", "a\\b.xlsx", "/etc/passwd", "../secret.xlsx", "sub/../up.xlsx"],
)
def test_download_ncr_detail_file_rejects_non_basename_names(tmp_path, bad_name: str) -> None:
    session = FakeSession()
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        client.download_ncr_detail_file(bad_name, tmp_path)

    assert session.calls == []
    assert list(tmp_path.iterdir()) == []


def test_download_ncr_detail_file_rejects_html_login_and_empty_bodies(tmp_path) -> None:
    session = FakeSession(
        [
            FakeResponse(
                '<html><form class="login-form"><input type="password"></form></html>',
                headers={"Content-Type": "text/html"},
            )
        ]
    )
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]
    with pytest.raises(ArasAuthenticationError, match="login page"):
        client.download_ncr_detail_file("NCR.xlsx", tmp_path)

    session = FakeSession([FakeResponse("<html><body>not found</body></html>")])
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]
    with pytest.raises(ArasCrawlerError, match="HTML page"):
        client.download_ncr_detail_file("NCR.xlsx", tmp_path)

    session = FakeSession([FakeResponse("", content=b"")])
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]
    with pytest.raises(ArasCrawlerError, match="empty"):
        client.download_ncr_detail_file("NCR.xlsx", tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_download_ncr_detail_file_http_errors_use_safe_exceptions(tmp_path) -> None:
    session = FakeSession(
        [
            FakeResponse(
                "unauthorized",
                status_code=401,
                reason="Unauthorized",
                headers={"WWW-Authenticate": "Bearer"},
            )
        ]
    )
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]
    with pytest.raises(ArasAuthenticationError):
        client.download_ncr_detail_file("NCR.xlsx", tmp_path)

    session = FakeSession([FakeResponse("missing", status_code=404, reason="Not Found")])
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]
    with pytest.raises(ArasCrawlerError):
        client.download_ncr_detail_file("NCR.xlsx", tmp_path)


def test_download_ncr_detail_file_diagnostic_omits_response_headers_and_body(tmp_path) -> None:
    events = []
    session = FakeSession(
        [
            FakeResponse(
                "",
                content=b"xlsx-bytes",
                headers={"Content-Type": "application/octet-stream", "Set-Cookie": "session=secret"},
            )
        ]
    )
    client = ArasCrawlerClient("http://aras.example", session=session, diagnostic_hook=events.append)  # type: ignore[arg-type]

    client.download_ncr_detail_file("NCR.xlsx", tmp_path)

    assert len(events) == 1
    assert events[0].stage == "ncr-download"
    assert events[0].response_headers is None
    assert events[0].response_body is None


def test_download_ncr_progress_file_resolves_vault_and_keeps_token_out_of_diagnostics(tmp_path) -> None:
    metadata = """<Envelope><Body><Result>
      <Item type="File" id="FILE123"><filename>NCR progress.xlsx</filename><Relationships>
        <Item type="Located"><related_id><Item type="Vault" id="VAULT1">
          <vault_url>http://aras.example/innovatorserver/vault/vaultserver.aspx</vault_url>
        </Item></related_id></Item>
      </Relationships></Item>
    </Result></Body></Envelope>"""
    payload = b"PK\x03\x04progress-xlsx"
    events = []
    session = FakeSession(
        [
            FakeResponse(metadata),
            FakeResponse('{"d":"fictional-download-token"}'),
            FakeResponse("", content=payload, headers={"Content-Type": "application/octet-stream"}),
        ]
    )
    client = ArasCrawlerClient(
        "http://aras.example",
        session=session,  # type: ignore[arg-type]
        diagnostic_hook=events.append,
    )

    saved = client.download_ncr_progress_file(
        NCRExportResult("FILE123", "fallback.xlsx", "REC1", "<xml/>"),
        tmp_path,
    )

    assert saved == tmp_path / "NCR progress.xlsx"
    assert saved.read_bytes() == payload
    assert [call["method"] for call in session.calls] == ["POST", "POST", "GET"]
    metadata_call, token_call, download_call = session.calls
    assert metadata_call["headers"]["SOAPAction"] == "ApplyItem"
    assert "<id>FILE123</id>" in metadata_call["data"]
    assert token_call["headers"]["SOAPAction"] == "GetFileDownloadToken"
    assert "token=fictional-download-token" in download_call["url"]
    assert "fileName=NCR+progress.xlsx" in download_call["url"]
    assert "vaultId=VAULT1" in download_call["url"]
    assert all("fictional-download-token" not in repr(event) for event in events)
    assert events[-1].stage == "ncr-progress-download"
    assert events[-1].url == "http://aras.example/innovatorserver/vault/vaultserver.aspx"
    assert events[-1].response_headers is None
    assert events[-1].response_body is None


def test_download_ncr_progress_file_rejects_cross_origin_vault_url(tmp_path) -> None:
    metadata = """<Envelope><Body><Result>
      <Item type="File" id="FILE123"><filename>NCR.xlsx</filename><Relationships>
        <Item type="Located"><related_id><Item type="Vault" id="VAULT1">
          <vault_url>http://attacker.example/vault/vaultserver.aspx</vault_url>
        </Item></related_id></Item>
      </Relationships></Item>
    </Result></Body></Envelope>"""
    session = FakeSession([FakeResponse(metadata)])
    client = ArasCrawlerClient("http://aras.example", session=session)  # type: ignore[arg-type]

    with pytest.raises(ArasCrawlerError, match="Vault URL is not allowed"):
        client.download_ncr_progress_file(
            NCRExportResult("FILE123", "fallback.xlsx", "REC1", "<xml/>"),
            tmp_path,
        )

    assert [call["method"] for call in session.calls] == ["POST"]
    assert list(tmp_path.iterdir()) == []
