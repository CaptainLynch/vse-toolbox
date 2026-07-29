from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import services.aras_report_export as export_service
from services.aras_crawler import (
    DEFAULT_EWO_SELECT_FIELDS,
    DEFAULT_PAA_SELECT_FIELDS,
    ArasCrawlerClient,
    ArasCrawlerError,
    ArasCrawlerSessionExpired,
    EWOReportFilters,
    PAAReportFilters,
)
from services.aras_report_export import ArasReportExportError


SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"


def _envelope(body: str) -> str:
    return (
        f'<SOAP-ENV:Envelope xmlns:SOAP-ENV="{SOAP_NS}">'
        f"<SOAP-ENV:Body>{body}</SOAP-ENV:Body></SOAP-ENV:Envelope>"
    )


class FakeResponse:
    def __init__(self, text: str, *, content_type: str = "text/xml") -> None:
        self.text = text
        self.status_code = 200
        self.reason = "OK"
        self.url = "https://aras.example/innovatorserver/Server/InnovatorServer.aspx"
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self) -> None:
        pass


class SingleResponseSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []
        self.cookies: dict[str, str] = {"sid": "fictional-session-secret"}

    def post(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"url": url, **kwargs})
        return self.response


INVALID_SHAPES = {
    "soap-fault": (
        _envelope(
            "<SOAP-ENV:Fault><faultcode>Server</faultcode>"
            "<faultstring>fictional-fault-secret Authorization: Bearer fictional-token</faultstring>"
            "</SOAP-ENV:Fault>"
        ),
        "text/xml",
        False,
    ),
    "missing-body": (
        f'<SOAP-ENV:Envelope xmlns:SOAP-ENV="{SOAP_NS}"></SOAP-ENV:Envelope>',
        "text/xml",
        False,
    ),
    "missing-result": (_envelope("<Other />"), "text/xml", False),
    "nested-result": (_envelope("<Wrapper><Result /></Wrapper>"), "text/xml", False),
    "login-html": (
        "<!doctype html><html><body><form><input type='password'>"
        "fictional-html-secret</form></body></html>",
        "text/html",
        True,
    ),
}


def _invalid_response(shape: str, module: str) -> tuple[str, str, bool]:
    if shape == "wrong-item-type":
        wrong_type = "PAA_O" if module == "ewo" else "EWO_O"
        return _envelope(f'<Result><Item type="{wrong_type}" id="wrong" /></Result>'), "text/xml", False
    return INVALID_SHAPES[shape]


@pytest.mark.parametrize("module", ["ewo", "paa"])
@pytest.mark.parametrize(
    "shape",
    ["soap-fault", "missing-body", "missing-result", "nested-result", "wrong-item-type", "login-html"],
)
def test_http_200_invalid_soap_never_becomes_query_success_or_leaks_body(
    module: str,
    shape: str,
) -> None:
    text, content_type, is_login = _invalid_response(shape, module)
    session = SingleResponseSession(FakeResponse(text, content_type=content_type))
    client = ArasCrawlerClient(
        "https://aras.example",
        session=session,  # type: ignore[arg-type]
        headers={"Authorization": "Bearer fictional-request-secret"},
        prewarm=False,
    )
    query = client.query_ewo_report if module == "ewo" else client.query_paa_report
    filters = EWOReportFilters() if module == "ewo" else PAAReportFilters()
    expected_error = ArasCrawlerSessionExpired if is_login else ArasCrawlerError

    with pytest.raises(expected_error) as excinfo:
        query(filters)

    error_text = str(excinfo.value)
    for forbidden in (
        "fictional-fault-secret",
        "fictional-token",
        "fictional-html-secret",
        "fictional-request-secret",
        "fictional-session-secret",
        "faultstring",
    ):
        assert forbidden not in error_text


@pytest.mark.parametrize("module", ["ewo", "paa"])
@pytest.mark.parametrize(
    "shape",
    ["soap-fault", "missing-body", "missing-result", "nested-result", "wrong-item-type", "login-html"],
)
def test_invalid_http_200_response_aborts_export_before_writer_and_creates_no_file(
    monkeypatch,
    tmp_path,
    module: str,
    shape: str,
) -> None:  # type: ignore[no-untyped-def]
    text, content_type, is_login = _invalid_response(shape, module)
    session = SingleResponseSession(FakeResponse(text, content_type=content_type))
    client = ArasCrawlerClient(
        "https://aras.example",
        session=session,  # type: ignore[arg-type]
        headers={
            "Authorization": "Bearer fictional-request-secret",
            "Cookie": "sid=fictional-cookie-secret",
        },
        prewarm=False,
    )
    writes: list[object] = []
    monkeypatch.setattr(export_service, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(
        export_service,
        "_write_xlsx",
        lambda *args, **kwargs: writes.append((args, kwargs)),
    )

    export = export_service.export_ewo_report if module == "ewo" else export_service.export_paa_report
    filters = EWOReportFilters() if module == "ewo" else PAAReportFilters()
    with pytest.raises(ArasReportExportError) as excinfo:
        export(client, filters)

    assert excinfo.value.code == ("SESSION_EXPIRED" if is_login else "UPSTREAM_REQUEST_FAILED")
    assert writes == []
    assert list(tmp_path.iterdir()) == []
    error_text = str(excinfo.value)
    for forbidden in (
        "fictional-fault-secret",
        "fictional-token",
        "fictional-html-secret",
        "fictional-request-secret",
        "fictional-cookie-secret",
        "fictional-session-secret",
        "faultstring",
    ):
        assert forbidden not in error_text


@pytest.mark.parametrize(
    ("module", "columns"),
    [("ewo", DEFAULT_EWO_SELECT_FIELDS), ("paa", DEFAULT_PAA_SELECT_FIELDS)],
)
def test_direct_empty_result_is_valid_and_writes_header_only_file(
    monkeypatch,
    tmp_path,
    module: str,
    columns: tuple[str, ...],
) -> None:  # type: ignore[no-untyped-def]
    session = SingleResponseSession(FakeResponse(_envelope("<Result />")))
    client = ArasCrawlerClient(
        "https://aras.example",
        session=session,  # type: ignore[arg-type]
        prewarm=False,
    )
    writes: list[dict[str, object]] = []

    def write(path: Path, written_module: str, written_columns, rows) -> None:  # type: ignore[no-untyped-def]
        writes.append(
            {
                "module": written_module,
                "columns": tuple(written_columns),
                "rows": list(rows),
            }
        )
        path.write_bytes(b"fake-xlsx-header-only")

    monkeypatch.setattr(export_service, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(export_service, "_write_xlsx", write)
    export = export_service.export_ewo_report if module == "ewo" else export_service.export_paa_report
    filters = EWOReportFilters() if module == "ewo" else PAAReportFilters()

    result = export(client, filters)

    assert result.status == "completed"
    assert result.stop_reason == "empty_page"
    assert result.count == 0
    assert result.pages_fetched == 1
    assert writes == [
        {
            "module": module,
            "columns": export_service._stable_safe_columns(columns),
            "rows": [],
        }
    ]
    assert result.saved_path.exists()
    assert result.saved_path.read_bytes() == b"fake-xlsx-header-only"
    assert [path for path in tmp_path.iterdir()] == [result.saved_path]
