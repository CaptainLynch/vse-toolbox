from __future__ import annotations

from pathlib import Path

import pytest

from services.tdc_crawler import (
    AFACE_PAGE_PATH,
    DATA_MODEL_EXPORT_PATH,
    DATA_MODEL_LIST_PATH,
    SOR_EXPORT_PATH,
    TDCAFaceFilters,
    TDCCrawlerClient,
    TDCCrawlerError,
    TDCDataModelFilters,
    TDCSORFilters,
)


class FakeResponse:
    def __init__(
        self,
        payload=None,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        text: str | None = None,
        content: bytes | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "application/json"}
        self.text = text if text is not None else ("" if payload is None else "json")
        self.content = content if content is not None else self.text.encode("utf-8")

    def json(self):  # type: ignore[no-untyped-def]
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"method": "GET", "url": url, **kwargs})
        if not self.responses:
            raise AssertionError("unexpected GET")
        return self.responses.pop(0)


def page_payload(rows, *, current=1, size=2, total=None, pages=None):  # type: ignore[no-untyped-def]
    return {
        "code": 200,
        "msg": "ok",
        "data": {
            "records": rows,
            "current": current,
            "size": size,
            "total": len(rows) if total is None else total,
            "pages": 1 if pages is None else pages,
        },
    }


def test_data_model_filter_mapping_and_empty_omission() -> None:
    filters = TDCDataModelFilters(
        serial_number=" WF-1 ",
        applicant="Alice",
        department="Engineering",
        section="Body",
        application_start="2026-01-01",
        application_end="2026-01-31",
        project_model="P100",
        part_number="PART-1",
        model_number="DM-1",
    )

    assert filters.to_params() == {
        "incident": "WF-1",
        "applicant": "Alice",
        "superDepartment": "Engineering",
        "department": "Body",
        "requestDateStart": "2026-01-01",
        "requestDateEnd": "2026-01-31",
        "projectModel": "P100",
        "partNumber": "PART-1",
        "modelNumber": "DM-1",
    }
    assert TDCDataModelFilters(serial_number=" ", part_number=None).to_params() == {}


def test_sor_filter_mapping_project_pair_and_validation() -> None:
    filters = TDCSORFilters(
        serial_number="SOR-WF-1",
        process_type="Release",
        car_type_project="P100",
        applicant="Bob",
        title="Seat SOR",
        department="Engineering",
        section="Interior",
        application_start="2026-02-01",
        application_end="2026-02-28",
        part_number="PART-2",
        part_name="Seat",
        version="V2",
        sor_number="SOR-9",
        latest_completed_node="Review",
        approval_status="Completed",
    )

    assert filters.to_params() == {
        "processNo": "SOR-WF-1",
        "bizName": "Release",
        "carTypeProject": "P100",
        "startUserName": "Bob",
        "title": "Seat SOR",
        "deptName": "Engineering",
        "sectionName": "Interior",
        "startTimeBegin": "2026-02-01",
        "startTimeEnd": "2026-02-28",
        "sorPartNo": "PART-2",
        "sorPartName": "Seat",
        "version": "V2",
        "sorNo": "SOR-9",
        "latestCompletedNode": "Review",
        "processInstanceStatus": "Completed",
        "carTypeProjectAll[0]": "P100",
    }
    with pytest.raises(ValueError, match="start must not be after end"):
        TDCSORFilters(application_start="2026-03-02", application_end="2026-03-01").to_params()
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        TDCDataModelFilters(application_start="03/01/2026").to_params()
    with pytest.raises(ValueError, match="enum"):
        TDCSORFilters(approval_status="bad\nvalue").to_params()


def test_query_page_contract_headers_and_diagnostic_summary() -> None:
    events = []
    session = FakeSession(
        [FakeResponse(page_payload([{"formId": "F1", "incident": "WF-1"}], current=2, size=25, total=51, pages=3))]
    )
    client = TDCCrawlerClient(
        "https://tdc.example/root",
        session=session,
        headers={"Authorization": "Bearer fictional-secret", "Cookie": "sid=fake-cookie"},
        timeout=12,
        diagnostic_hook=events.append,
    )

    result = client.query_data_model_page(
        TDCDataModelFilters(project_model="P100", applicant="Fictional User"), page=2, page_size=25
    )

    call = session.calls[0]
    assert call["url"] == "https://tdc.example" + DATA_MODEL_LIST_PATH
    assert call["params"] == {
        "applicant": "Fictional User",
        "projectModel": "P100",
        "current": 2,
        "size": 25,
    }
    assert call["headers"]["Referer"] == "https://tdc.example/tpc/dataAdmin/dataModelDesign/index"  # type: ignore[index]
    assert call["headers"]["Accept-Language"] == "zh-CN,zh;q=0.9"  # type: ignore[index]
    assert call["timeout"] == 12
    assert result.page == 2
    assert result.total == 51
    assert result.pages == 3
    assert result.record_granularity == "workflow"
    event = events[0]
    assert event.request_id
    assert event.path == DATA_MODEL_LIST_PATH
    assert event.record_count == 1
    assert event.total == 51
    assert event.pages == 3
    assert event.request_headers["Authorization"] == "[redacted]"
    assert event.request_headers["Cookie"] == "[redacted]"
    assert event.query["applicant"] == "[redacted]"


def test_full_crawl_deduplicates_and_records_stop_reason() -> None:
    events = []
    session = FakeSession(
        [
            FakeResponse(page_payload([{"id": "1"}, {"id": "2"}], current=1, total=4, pages=2)),
            FakeResponse(page_payload([{"id": "2"}, {"id": "3"}], current=2, total=4, pages=2)),
        ]
    )
    client = TDCCrawlerClient("https://tdc.example", session=session, diagnostic_hook=events.append)

    result = client.crawl_sor_all(page_size=2, max_pages=10, max_records=20)

    assert [row["id"] for row in result.rows] == ["1", "2", "3"]
    assert result.fetched_pages == 2
    assert result.unique_count == 3
    assert result.duplicate_count == 1
    assert result.stop_reason == "reported_pages"
    pagination = [event for event in events if event.stage == "pagination"]
    assert pagination[-1].accumulated_count == 4
    assert pagination[-1].unique_count == 3
    assert pagination[-1].duplicate_count == 1
    assert pagination[-1].stop_reason == "reported_pages"


def test_full_crawl_page_and_record_fuses() -> None:
    pages_session = FakeSession(
        [
            FakeResponse(page_payload([{"id": "1"}, {"id": "2"}], current=1, total=20, pages=10)),
            FakeResponse(page_payload([{"id": "3"}, {"id": "4"}], current=2, total=20, pages=10)),
        ]
    )
    pages_result = TDCCrawlerClient("https://tdc.example", session=pages_session).crawl_sor_all(
        page_size=2, max_pages=2, max_records=20
    )
    assert pages_result.stop_reason == "max_pages"
    assert pages_result.fetched_pages == 2

    records_session = FakeSession(
        [FakeResponse(page_payload([{"formId": "1"}, {"formId": "2"}, {"formId": "3"}], total=20, pages=7))]
    )
    records_result = TDCCrawlerClient("https://tdc.example", session=records_session).crawl_data_model_all(
        page_size=3, max_pages=10, max_records=2
    )
    assert records_result.stop_reason == "max_records"
    assert len(records_result.rows) == 2

    for kwargs in (
        {"page_size": 0, "max_pages": 1, "max_records": 1},
        {"page_size": 1, "max_pages": 0, "max_records": 1},
        {"page_size": 1, "max_pages": 1, "max_records": 0},
    ):
        with pytest.raises(ValueError):
            TDCCrawlerClient("https://tdc.example", session=FakeSession([])).crawl_sor_all(**kwargs)


def test_error_response_and_login_html_are_rejected_without_body_leak() -> None:
    failed = FakeSession(
        [
            FakeResponse(
                None,
                status_code=500,
                headers={"Content-Type": "text/plain"},
                text="Cookie: sid=fictional-secret Authorization: Bearer fictional-token",
            )
        ]
    )
    with pytest.raises(TDCCrawlerError) as excinfo:
        TDCCrawlerClient("https://tdc.example", session=failed).query_sor_page()
    assert "fictional-secret" not in str(excinfo.value)
    assert "fictional-token" not in str(excinfo.value)
    assert excinfo.value.status_code == 500

    login = FakeSession(
        [
            FakeResponse(
                None,
                headers={"Content-Type": "text/html; charset=utf-8"},
                text="<html><body>Sign in</body></html>",
            )
        ]
    )
    with pytest.raises(TDCCrawlerError, match="login HTML"):
        TDCCrawlerClient("https://tdc.example", session=login).query_data_model_page()


def test_invalid_json_and_content_type_are_rejected() -> None:
    invalid_json = FakeSession(
        [FakeResponse(ValueError("bad json"), headers={"Content-Type": "application/json"}, text="not-json")]
    )
    with pytest.raises(TDCCrawlerError, match="not valid JSON"):
        TDCCrawlerClient("https://tdc.example", session=invalid_json).query_sor_page()

    wrong_type = FakeSession(
        [FakeResponse(page_payload([]), headers={"Content-Type": "text/plain"}, text="json-like")]
    )
    with pytest.raises(TDCCrawlerError, match="Content-Type"):
        TDCCrawlerClient("https://tdc.example", session=wrong_type).query_sor_page()


def test_xlsx_exports_validate_signature_sanitize_name_and_mark_granularity(tmp_path: Path) -> None:
    xlsx = b"PK\x03\x04fictional-minimal-xlsx"
    data_session = FakeSession(
        [
            FakeResponse(
                None,
                headers={
                    "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "Content-Disposition": "attachment; filename*=UTF-8''official%20report.xlsx",
                },
                content=xlsx,
            )
        ]
    )
    result = TDCCrawlerClient("https://tdc.example", session=data_session, output_dir=tmp_path).export_data_model(
        TDCDataModelFilters(project_model="P100"), file_name="../bad:name?.xlsx"
    )
    assert data_session.calls[0]["url"] == "https://tdc.example" + DATA_MODEL_EXPORT_PATH
    assert data_session.calls[0]["params"]["pagePath"] == "https://tdc.example/tpc/dataAdmin/dataModelDesign/index"  # type: ignore[index]
    assert result.file_name == "bad_name_.xlsx"
    assert result.path == (tmp_path / "bad_name_.xlsx").resolve()
    assert result.path.read_bytes() == xlsx
    assert result.signature_valid is True
    assert result.record_granularity == "workflow"

    sor_session = FakeSession(
        [
            FakeResponse(
                None,
                headers={"Content-Type": "application/octet-stream"},
                content=xlsx,
            )
        ]
    )
    sor = TDCCrawlerClient("https://tdc.example", session=sor_session, output_dir=tmp_path).export_sor()
    assert sor_session.calls[0]["url"] == "https://tdc.example" + SOR_EXPORT_PATH
    assert sor.record_granularity == "part_detail"
    assert "part_details" in sor.file_name


def test_export_rejects_login_html_bad_type_and_bad_zip_signature(tmp_path: Path) -> None:
    cases = [
        FakeResponse(None, headers={"Content-Type": "text/html"}, content=b"<html>login</html>"),
        FakeResponse(None, headers={"Content-Type": "application/json"}, content=b'{"code":200}'),
        FakeResponse(None, headers={"Content-Type": "application/octet-stream"}, content=b"not-a-zip"),
    ]
    for response in cases:
        with pytest.raises(TDCCrawlerError):
            TDCCrawlerClient("https://tdc.example", session=FakeSession([response]), output_dir=tmp_path).export_sor()
    assert list(tmp_path.iterdir()) == []


def test_a_face_contract_is_independent_and_never_guesses_an_endpoint() -> None:
    session = FakeSession([])
    client = TDCCrawlerClient("https://tdc.example", session=session)

    with pytest.raises(TDCCrawlerError) as excinfo:
        client.query_a_face_page(TDCAFaceFilters())

    assert "待 HAR 验证" in str(excinfo.value)
    assert AFACE_PAGE_PATH in str(excinfo.value)
    assert session.calls == []


def test_pagination_and_timeout_validation() -> None:
    client = TDCCrawlerClient("https://tdc.example", session=FakeSession([]))
    with pytest.raises(ValueError, match="page"):
        client.query_sor_page(page=0)
    with pytest.raises(ValueError, match="page_size"):
        client.query_sor_page(page_size=1001)
    with pytest.raises(ValueError, match="timeout"):
        TDCCrawlerClient("https://tdc.example", session=FakeSession([]), timeout=0)
