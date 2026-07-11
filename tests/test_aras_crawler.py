from __future__ import annotations

import re
from pathlib import Path

import pytest

from services.aras_crawler import (
    DEFAULT_EWO_SELECT_FIELDS,
    ArasCrawlerClient,
    ArasCrawlerError,
    EWOReportFilters,
    NCRApprovalFilters,
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
    ) -> None:
        self.text = text
        self.status_code = status_code
        self.reason = reason
        self.url = url
        self.headers = headers or {}

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
        raise AssertionError("GET should not be called by query methods")

    def head(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"method": "HEAD", "url": url, **kwargs})
        raise AssertionError("HEAD should not be called by query methods")


def fixture_text(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8-sig")


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
