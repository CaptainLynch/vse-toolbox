from __future__ import annotations

from pathlib import Path

import pytest

from services.tdc_crawler import (
    AFACE_PAGE_PATH,
    DATA_MODEL_EXPORT_PATH,
    DATA_MODEL_LIST_PATH,
    SOR_EXPORT_PATH,
    SOR_LIST_PATH,
    SOR_PROJECT_LIST_PATH,
    TDCAFaceFilters,
    TDCCrawlerClient,
    TDCCrawlerError,
    TDCDataModelFilters,
    TDCSORFilters,
)
from services.windows_http import WinHTTPTimeoutError


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
    }
    with pytest.raises(ValueError, match="start must not be after end"):
        TDCSORFilters(application_start="2026-03-02", application_end="2026-03-01").to_params()
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        TDCDataModelFilters(application_start="03/01/2026").to_params()
    with pytest.raises(ValueError, match="enum"):
        TDCSORFilters(approval_status="bad\nvalue").to_params()


def test_sor_filter_mapping_uses_project_id_for_selected_project_array() -> None:
    params = TDCSORFilters(
        car_type_project="E262S",
        car_type_project_id="project-id-1",
    ).to_params()

    assert params["carTypeProject"] == "project-id-1"
    assert params["carTypeProjectAll[0]"] == "project-id-1"


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
    assert result.record_granularity == "part_detail"
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
    assert result.stop_reason == "duplicate_records"
    assert result.complete is False
    pagination = [event for event in events if event.stage == "pagination"]
    assert pagination[-1].accumulated_count == 4
    assert pagination[-1].unique_count == 3
    assert pagination[-1].duplicate_count == 1
    assert pagination[-1].stop_reason == "duplicate_records"


def test_data_model_crawl_keeps_part_rows_with_the_same_workflow() -> None:
    page_one = [
        {"formId": "FORM-1", "incident": "INC-1", "documentNo": "DOC-1", "partNumber": "P-1", "modelNumber": "M-1", "partName": "左件"},
        {"formId": "FORM-1", "incident": "INC-1", "documentNo": "DOC-1", "partNumber": "P-2", "modelNumber": "M-2", "partName": "右件"},
    ]
    page_two = [
        {"formId": "FORM-1", "incident": "INC-1", "documentNo": "DOC-1", "partNumber": "P-2", "modelNumber": "M-2", "partName": "右件"},
        {"formId": "FORM-1", "incident": "INC-1", "documentNo": "DOC-1", "partNumber": "P-3", "modelNumber": "M-3", "partName": "第三件"},
    ]
    client = TDCCrawlerClient(
        "https://tdc.example",
        session=FakeSession(
            [
                FakeResponse(page_payload(page_one, current=1, total=4, pages=2)),
                FakeResponse(page_payload(page_two, current=2, total=4, pages=2)),
            ]
        ),
    )

    result = client.crawl_data_model_all(page_size=2, max_pages=2, max_records=10)

    assert [row["partNumber"] for row in result.rows] == ["P-1", "P-2", "P-3"]
    assert result.unique_count == 3
    assert result.duplicate_count == 1
    assert result.record_granularity == "part_detail"


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
        [FakeResponse(page_payload([{"formId": "1"}, {"formId": "2"}, {"formId": "3"}], size=3, total=20, pages=7))]
    )
    records_result = TDCCrawlerClient("https://tdc.example", session=records_session).crawl_data_model_all(
        page_size=3, max_pages=10, max_records=2
    )
    assert records_result.stop_reason == "max_records"
    assert len(records_result.rows) == 2
    assert pages_result.complete is False
    assert records_result.complete is False

    for kwargs in (
        {"page_size": 0, "max_pages": 1, "max_records": 1},
        {"page_size": 1, "max_pages": 0, "max_records": 1},
        {"page_size": 1, "max_pages": 1, "max_records": 0},
    ):
        with pytest.raises(ValueError):
            TDCCrawlerClient("https://tdc.example", session=FakeSession([])).crawl_sor_all(**kwargs)


def test_full_crawl_exact_limit_is_complete_only_when_server_reports_all_pages() -> None:
    session = FakeSession(
        [
            FakeResponse(page_payload([{"id": "1"}, {"id": "2"}], current=1, total=4, pages=2)),
            FakeResponse(page_payload([{"id": "3"}, {"id": "4"}], current=2, total=4, pages=2)),
        ]
    )
    result = TDCCrawlerClient("https://tdc.example", session=session).crawl_sor_all(
        page_size=2, max_pages=10, max_records=4
    )
    assert result.stop_reason == "reported_pages"
    assert result.complete is True
    assert result.unique_count == 4


def test_full_crawl_rejects_response_page_mismatch_as_incomplete() -> None:
    session = FakeSession(
        [
            FakeResponse(page_payload([{"id": "1"}, {"id": "2"}], current=1, total=4, pages=2)),
            # The second request is for page 2, but the upstream repeats page 1.
            FakeResponse(page_payload([{"id": "1"}, {"id": "2"}], current=1, total=4, pages=2)),
        ]
    )
    result = TDCCrawlerClient("https://tdc.example", session=session).crawl_sor_all(
        page_size=2, max_pages=5, max_records=20
    )

    assert result.stop_reason == "inconsistent_page"
    assert result.complete is False
    assert result.unique_count == 2
    assert result.duplicate_count == 0
    assert [call["params"]["current"] for call in session.calls] == [1, 2]


def test_full_crawl_rejects_total_reached_before_declared_final_page() -> None:
    session = FakeSession(
        [FakeResponse(page_payload([{"id": "1"}, {"id": "2"}], current=1, total=2, pages=2))]
    )
    result = TDCCrawlerClient("https://tdc.example", session=session).crawl_sor_all(
        page_size=2, max_pages=5, max_records=20
    )

    assert result.stop_reason == "inconsistent_metadata"
    assert result.complete is False
    assert result.fetched_pages == 1
    assert len(session.calls) == 1


def test_full_crawl_does_not_use_duplicate_rows_to_prove_total_complete() -> None:
    session = FakeSession(
        [
            FakeResponse(page_payload([{"id": "1"}, {"id": "2"}], current=1, total=4, pages=2)),
            FakeResponse(page_payload([{"id": "1"}, {"id": "2"}], current=2, total=4, pages=2)),
        ]
    )
    result = TDCCrawlerClient("https://tdc.example", session=session).crawl_sor_all(
        page_size=2, max_pages=5, max_records=20
    )

    assert result.stop_reason == "duplicate_records"
    assert result.complete is False
    assert result.unique_count == 2
    assert result.duplicate_count == 2


def test_full_crawl_empty_page_before_reported_total_is_incomplete() -> None:
    session = FakeSession(
        [
            FakeResponse(page_payload([{"id": "1"}, {"id": "2"}], current=1, total=6, pages=3)),
            FakeResponse(page_payload([], current=2, total=6, pages=3)),
        ]
    )
    result = TDCCrawlerClient("https://tdc.example", session=session).crawl_sor_all(
        page_size=2, max_pages=10, max_records=10
    )

    assert result.stop_reason == "incomplete_page"
    assert result.complete is False
    assert result.fetched_pages == 2


def test_full_crawl_short_or_empty_page_cannot_override_reported_tail() -> None:
    short_session = FakeSession(
        [
            FakeResponse(page_payload([{"id": "1"}, {"id": "2"}], current=1, total=6, pages=3)),
            FakeResponse(page_payload([{"id": "3"}], current=2, total=6, pages=3)),
        ]
    )
    short_result = TDCCrawlerClient("https://tdc.example", session=short_session).crawl_sor_all(
        page_size=2, max_pages=10, max_records=10
    )
    assert short_result.stop_reason == "incomplete_page"
    assert short_result.complete is False

    empty_session = FakeSession(
        [
            FakeResponse(page_payload([{"id": "1"}, {"id": "2"}], current=1, total=6, pages=3)),
            FakeResponse(page_payload([], current=2, total=6, pages=3)),
        ]
    )
    empty_result = TDCCrawlerClient("https://tdc.example", session=empty_session).crawl_sor_all(
        page_size=2, max_pages=10, max_records=10
    )
    assert empty_result.stop_reason == "incomplete_page"
    assert empty_result.complete is False


def test_full_crawl_short_final_page_at_exact_limit_is_complete_without_tail_metadata() -> None:
    session = FakeSession(
        [
            FakeResponse({
                "code": 200,
                "data": {"records": [{"id": "1"}, {"id": "2"}, {"id": "3"}], "current": 1, "size": 3},
            }),
            FakeResponse({
                "code": 200,
                "data": {"records": [{"id": "4"}], "current": 2, "size": 3},
            }),
        ]
    )
    result = TDCCrawlerClient("https://tdc.example", session=session).crawl_sor_all(
        page_size=3, max_pages=10, max_records=4
    )

    assert result.stop_reason == "short_page"
    assert result.complete is True
    assert [row["id"] for row in result.rows] == ["1", "2", "3", "4"]


def test_full_crawl_reports_incomplete_when_reported_pages_under_deliver_total() -> None:
    session = FakeSession(
        [
            FakeResponse(page_payload([{"id": "1"}, {"id": "2"}], current=1, total=4, pages=2)),
            FakeResponse(page_payload([{"id": "3"}], current=2, total=4, pages=2)),
        ]
    )
    result = TDCCrawlerClient("https://tdc.example", session=session).crawl_sor_all(
        page_size=2, max_pages=10, max_records=10
    )
    assert result.stop_reason == "incomplete_page"
    assert result.complete is False
    assert result.fetched_pages == 2


def test_full_crawl_unknown_tail_is_incomplete_even_when_limit_is_exact() -> None:
    response = FakeResponse({
        "code": 200,
        "data": {"records": [{"id": "1"}, {"id": "2"}], "current": 1, "size": 2},
    })
    result = TDCCrawlerClient("https://tdc.example", session=FakeSession([response])).crawl_sor_all(
        page_size=2, max_pages=10, max_records=2
    )
    assert result.stop_reason == "max_records"
    assert result.complete is False


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


def test_xlsx_export_json_error_surfaces_sanitized_api_reason() -> None:
    events = []
    response = FakeResponse(
        {"code": 401, "msg": "session expired Cookie: sid=secret-cookie"},
        headers={"Content-Type": "application/json; charset=utf-8"},
        text='{"code":401,"msg":"session expired Cookie: sid=secret-cookie"}',
    )

    with pytest.raises(TDCCrawlerError) as excinfo:
        TDCCrawlerClient(
            "https://tdc.example",
            session=FakeSession([response]),
            diagnostic_hook=events.append,
        ).export_data_model(TDCDataModelFilters(project_model="F610M"))

    error = excinfo.value
    assert error.stage == "api-validation"
    assert error.status_code == 200
    assert str(error).startswith("TDC export API error code 401: session expired Cookie: [redacted]")
    assert "secret-cookie" not in str(error)
    assert events[0].validation == "api-error"
    assert events[0].reason == "session expired Cookie: [redacted]"


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(
            {"code": 200},
            headers={"Content-Type": "application/json"},
            text='{"code":200}',
        ),
        FakeResponse(
            ValueError("invalid JSON"),
            headers={"Content-Type": "application/json"},
            text="not-json",
        ),
    ],
)
def test_xlsx_export_json_without_api_error_is_still_rejected(response: FakeResponse) -> None:
    events = []
    with pytest.raises(TDCCrawlerError, match="returned JSON instead of an XLSX file") as excinfo:
        TDCCrawlerClient(
            "https://tdc.example",
            session=FakeSession([response]),
            diagnostic_hook=events.append,
        ).export_data_model(TDCDataModelFilters(project_model="F610M"))

    assert excinfo.value.stage == "export-validation"
    assert events[0].validation == "rejected-json-response"


def test_xlsx_export_uses_long_receive_timeout_for_slow_official_generation() -> None:
    class TimeoutSession(FakeSession):
        def get(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append({"method": "GET", "url": url, **kwargs})
            raise WinHTTPTimeoutError("WinHTTP request timed out")

    events = []
    session = TimeoutSession([])
    with pytest.raises(TDCCrawlerError, match="WinHTTPTimeoutError"):
        TDCCrawlerClient(
            "https://tdc.example",
            session=session,
            diagnostic_hook=events.append,
        ).export_data_model(TDCDataModelFilters(project_model="F610M"))

    assert session.calls[0]["timeout"] == (30.0, 120.0)
    assert events[0].timeout == (30.0, 120.0)


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
    assert data_session.calls[0]["headers"]["Accept"] == "application/json, text/plain, */*"  # type: ignore[index]
    assert data_session.calls[0]["params"]["pagePath"] == "https://tdc.example/tpc/dataAdmin/dataModelDesign/index"  # type: ignore[index]
    assert result.file_name == "bad_name_.xlsx"
    assert result.path == (tmp_path / "bad_name_.xlsx").resolve()
    assert result.path.read_bytes() == xlsx
    assert result.signature_valid is True
    assert result.record_granularity == "part_detail"

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


def test_sor_resolver_blank_filters_no_project_lookup() -> None:
    session = FakeSession([FakeResponse(page_payload([{"processNo": "WF-1"}]))])
    client = TDCCrawlerClient("https://tdc.example", session=session)
    result = client.query_sor_page(TDCSORFilters())
    assert len(result.rows) == 1
    assert len(session.calls) == 1
    assert session.calls[0]["url"].endswith(SOR_LIST_PATH)
    assert "carTypeProject" not in session.calls[0]["params"]
    assert "carTypeProjectAll[0]" not in session.calls[0]["params"]


def test_sor_resolver_exact_project_no_and_name_matching() -> None:
    projects_payload = {
        "code": 200,
        "data": [
            {"id": "proj-id-1", "projectNo": "P100", "projectName": "Project 100"},
            {"id": "proj-id-2", "projectNo": "P200", "projectName": "Project 200"},
        ],
    }
    # Match by projectNo
    session1 = FakeSession([
        FakeResponse(projects_payload),
        FakeResponse(page_payload([{"processNo": "WF-1"}])),
    ])
    client1 = TDCCrawlerClient("https://tdc.example", session=session1)
    client1.query_sor_page(TDCSORFilters(car_type_project="  P100  "))
    assert session1.calls[1]["params"]["carTypeProject"] == "proj-id-1"
    assert session1.calls[1]["params"]["carTypeProjectAll[0]"] == "proj-id-1"

    # Match by projectName
    session2 = FakeSession([
        FakeResponse(projects_payload),
        FakeResponse(page_payload([{"processNo": "WF-2"}])),
    ])
    client2 = TDCCrawlerClient("https://tdc.example", session=session2)
    client2.query_sor_page(TDCSORFilters(car_type_project="Project 200"))
    assert session2.calls[1]["params"]["carTypeProject"] == "proj-id-2"
    assert session2.calls[1]["params"]["carTypeProjectAll[0]"] == "proj-id-2"


def test_sor_resolver_absent_project_raises_fixed_guidance_without_raw_values() -> None:
    session = FakeSession([FakeResponse({"code": 200, "data": [{"id": "id-1", "projectNo": "P100"}]})])
    client = TDCCrawlerClient("https://tdc.example", session=session)
    with pytest.raises(TDCCrawlerError) as excinfo:
        client.query_sor_page(TDCSORFilters(car_type_project="SecretProjectCode999"))
    err = excinfo.value
    assert err.stage == "contract-validation"
    assert "SecretProjectCode999" not in str(err)
    assert "未找到匹配的车型项目" in str(err)
    # No query/report call sent
    assert len(session.calls) == 1
    assert session.calls[0]["url"].endswith(SOR_PROJECT_LIST_PATH)


def test_sor_resolver_ambiguous_and_deduplication() -> None:
    # Multiple distinct IDs -> ambiguous error
    ambiguous_session = FakeSession([
        FakeResponse({
            "code": 200,
            "data": [
                {"id": "id-1", "projectNo": "P100", "projectName": "A"},
                {"id": "id-2", "projectNo": "P100", "projectName": "B"},
            ],
        })
    ])
    client = TDCCrawlerClient("https://tdc.example", session=ambiguous_session)
    with pytest.raises(TDCCrawlerError) as excinfo:
        client.query_sor_page(TDCSORFilters(car_type_project="P100"))
    assert excinfo.value.stage == "contract-validation"
    assert "歧义" in str(excinfo.value)
    assert "P100" not in str(excinfo.value)

    # Identical duplicate IDs -> deduplicate and succeed
    dedup_session = FakeSession([
        FakeResponse({
            "code": 200,
            "data": [
                {"id": "id-1", "projectNo": "P100", "projectName": "A"},
                {"id": "id-1", "projectNo": "P100", "projectName": "A"},
            ],
        }),
        FakeResponse(page_payload([])),
    ])
    client_dedup = TDCCrawlerClient("https://tdc.example", session=dedup_session)
    client_dedup.query_sor_page(TDCSORFilters(car_type_project="P100"))
    assert dedup_session.calls[1]["params"]["carTypeProjectAll[0]"] == "id-1"


def test_sor_resolver_missing_id_raises_contract_validation() -> None:
    session = FakeSession([
        FakeResponse({"code": 200, "data": [{"id": "", "projectNo": "P100", "projectName": "P100"}]})
    ])
    client = TDCCrawlerClient("https://tdc.example", session=session)
    with pytest.raises(TDCCrawlerError) as excinfo:
        client.query_sor_page(TDCSORFilters(car_type_project="P100"))
    assert excinfo.value.stage == "contract-validation"
    assert "缺少" in str(excinfo.value)
    assert "P100" not in str(excinfo.value)


def test_sor_resolver_stale_explicit_id_and_mismatched_text() -> None:
    projects_payload = {
        "code": 200,
        "data": [{"id": "valid-id-1", "projectNo": "P100", "projectName": "Project 100"}],
    }
    # Stale explicit ID not in list
    session1 = FakeSession([FakeResponse(projects_payload)])
    client1 = TDCCrawlerClient("https://tdc.example", session=session1)
    with pytest.raises(TDCCrawlerError) as excinfo1:
        client1.query_sor_page(TDCSORFilters(car_type_project_id="stale-secret-id"))
    assert excinfo1.value.stage == "contract-validation"
    assert "stale-secret-id" not in str(excinfo1.value)
    assert "不存在或已失效" in str(excinfo1.value)

    # Mismatched ID/text
    session2 = FakeSession([FakeResponse(projects_payload)])
    client2 = TDCCrawlerClient("https://tdc.example", session=session2)
    with pytest.raises(TDCCrawlerError) as excinfo2:
        client2.query_sor_page(TDCSORFilters(car_type_project="WrongProjectName", car_type_project_id="valid-id-1"))
    assert excinfo2.value.stage == "contract-validation"
    assert "WrongProjectName" not in str(excinfo2.value)
    assert "valid-id-1" not in str(excinfo2.value)
    assert "不匹配" in str(excinfo2.value)

    # Matching text and explicit ID succeeds
    session3 = FakeSession([FakeResponse(projects_payload), FakeResponse(page_payload([]))])
    client3 = TDCCrawlerClient("https://tdc.example", session=session3)
    client3.query_sor_page(TDCSORFilters(car_type_project="P100", car_type_project_id="valid-id-1"))
    assert session3.calls[1]["params"]["carTypeProject"] == "valid-id-1"
    assert session3.calls[1]["params"]["carTypeProjectAll[0]"] == "valid-id-1"

    # Explicit ID without text succeeds
    session4 = FakeSession([FakeResponse(projects_payload), FakeResponse(page_payload([]))])
    client4 = TDCCrawlerClient("https://tdc.example", session=session4)
    client4.query_sor_page(TDCSORFilters(car_type_project_id="valid-id-1"))
    assert session4.calls[1]["params"]["carTypeProjectAll[0]"] == "valid-id-1"


def test_sor_resolver_multipage_crawl_does_single_lookup_and_export_validation(tmp_path: Path) -> None:
    projects_payload = {
        "code": 200,
        "data": [{"id": "proj-id-1", "projectNo": "P100", "projectName": "Project 100"}],
    }
    page1 = FakeResponse(page_payload([{"processNo": "WF-1"}], current=1, size=1, total=2, pages=2))
    page2 = FakeResponse(page_payload([{"processNo": "WF-2"}], current=2, size=1, total=2, pages=2))
    session = FakeSession([FakeResponse(projects_payload), page1, page2])
    client = TDCCrawlerClient("https://tdc.example", session=session)

    result = client.crawl_sor_all(TDCSORFilters(car_type_project="P100"), page_size=1, max_pages=2)
    assert len(result.rows) == 2
    # Only 1 project list request, followed by 2 page requests
    project_list_calls = [c for c in session.calls if c["url"].endswith(SOR_PROJECT_LIST_PATH)]
    page_calls = [c for c in session.calls if c["url"].endswith(SOR_LIST_PATH)]
    assert len(project_list_calls) == 1
    assert len(page_calls) == 2

    # Export with invalid resolution sends no export request
    export_session = FakeSession([FakeResponse(projects_payload)])
    export_client = TDCCrawlerClient("https://tdc.example", session=export_session, output_dir=tmp_path)
    with pytest.raises(TDCCrawlerError) as excinfo:
        export_client.export_sor(TDCSORFilters(car_type_project="MissingProject"))
    assert excinfo.value.stage == "contract-validation"
    assert len(export_session.calls) == 1
    assert export_session.calls[0]["url"].endswith(SOR_PROJECT_LIST_PATH)


@pytest.mark.parametrize("mode", ["list", "query", "crawl", "export"])
def test_sor_official_project_context_and_id_contract(mode, tmp_path):
    # Synthetic transport reproduces the two different project dictionaries.
    class ProjectContextSession(FakeSession):
        def get(self, url, **kwargs):
            self.calls.append({"method": "GET", "url": url, **kwargs})
            params = kwargs.get("params", {})
            if url.endswith(SOR_PROJECT_LIST_PATH):
                projects = ([{"id": "sor-id", "projectNo": "P100", "projectName": "Project 100"}]
                            if params.get("sorEnabled") == "true" else
                            [{"id": "other-id", "projectNo": "OTHER"}])
                return FakeResponse({"code": 0, "data": projects})
            if url.endswith(SOR_EXPORT_PATH):
                return FakeResponse(headers={"Content-Type": "application/octet-stream"}, content=b"PK\x03\x04synthetic")
            return FakeResponse(page_payload([{"processNo": "WF-1"}], current=1, size=2, total=1, pages=1))

    session = ProjectContextSession([])
    client = TDCCrawlerClient("https://tdc.example", session=session, output_dir=tmp_path)
    filters = TDCSORFilters(car_type_project="P100")
    if mode == "list":
        assert client.list_car_type_projects()[0]["projectNo"] == "P100"
    elif mode == "query":
        assert len(client.query_sor_page(filters, page_size=2).rows) == 1
    elif mode == "crawl":
        result = client.crawl_sor_all(filters, page_size=2)
        assert result.complete and len(result.rows) == 1
    else:
        assert client.export_sor(filters).path.is_file()
    assert session.calls[0]["params"] == {"sorEnabled": "true"}
    if mode != "list":
        params = session.calls[-1]["params"]
        assert params["carTypeProject"] == "sor-id"
        assert params["carTypeProjectAll[0]"] == "sor-id"
        assert filters.car_type_project == "P100"
        assert filters.car_type_project_id is None


@pytest.mark.parametrize("process_type, expected", [(None, "SOR"), ("", "SOR"), ("  ", "SOR"), ("Release", "Release")])
def test_sor_export_defaults_business_name_without_overriding_selection(tmp_path, process_type, expected):
    session = FakeSession([FakeResponse(headers={"Content-Type": "application/octet-stream"}, content=b"PK\x03\x04synthetic")])
    client = TDCCrawlerClient("https://tdc.example", session=session, output_dir=tmp_path)
    client.export_sor(TDCSORFilters(process_type=process_type))
    params = session.calls[0]["params"]
    assert params["bizName"] == expected
    assert params["pagePath"] == "https://tdc.example/tpc/dataAdmin/intelligent/sor/index"
    assert "carTypeProject" not in params
    assert "carTypeProjectAll[0]" not in params


def test_sor_id_only_sends_both_project_parameters():
    session = FakeSession([
        FakeResponse({"code": 0, "data": [{"id": "sor-id", "projectNo": "P100"}]}),
        FakeResponse(page_payload([])),
    ])
    TDCCrawlerClient("https://tdc.example", session=session).query_sor_page(TDCSORFilters(car_type_project_id="sor-id"))
    assert session.calls[1]["params"]["carTypeProject"] == "sor-id"
    assert session.calls[1]["params"]["carTypeProjectAll[0]"] == "sor-id"


def test_safe_filename_truncation_and_boundaries() -> None:
    from services.tdc_crawler import _safe_filename

    # 1. Normal filename preserves extension
    assert _safe_filename("export_2026.xlsx") == "export_2026.xlsx"
    assert _safe_filename("export_2026") == "export_2026.xlsx"
    assert _safe_filename("export_2026.XLSX") == "export_2026.xlsx"

    # 2. Long filenames (>= 180 chars) truncate stem to 175 chars and retain .xlsx
    long_name = "a" * 200 + ".xlsx"
    safe = _safe_filename(long_name)
    assert len(safe) == 175 + len(".xlsx")
    assert safe.endswith(".xlsx")
    assert safe == "a" * 175 + ".xlsx"

    long_name_no_ext = "b" * 250
    safe_no_ext = _safe_filename(long_name_no_ext)
    assert len(safe_no_ext) == 175 + len(".xlsx")
    assert safe_no_ext.endswith(".xlsx")
    assert safe_no_ext == "b" * 175 + ".xlsx"

    # 3. Path traversal and illegal chars sanitized
    traversal = "../../secrets/report:1?.xlsx"
    assert _safe_filename(traversal) == "report_1_.xlsx"

    # 4. Empty or whitespace-only inputs fall back to default timestamped filename
    fallback = _safe_filename("   ")
    assert fallback.startswith("tdc_export_")
    assert fallback.endswith(".xlsx")
    assert len(fallback) < 50
