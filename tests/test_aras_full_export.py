from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any, Callable

import pytest

import services.aras_report_export as export_service
from services.aras_crawler import (
    DEFAULT_EWO_SELECT_FIELDS,
    DEFAULT_PAA_SELECT_FIELDS,
    ArasCrawlerSessionExpired,
    EWOReportFilters,
    EWOReportPage,
    PAAReportFilters,
    PAAReportPage,
)
from services.aras_report_export import ArasReportExportError, row_matches_filters


def _rows(prefix: str, start: int, count: int) -> tuple[list[dict[str, str]], list[str]]:
    rows = [
        {
            "_no": f"{prefix}-{index:04d}",
            "state": "Open",
            "_subject": f"Subject {index}",
        }
        for index in range(start, start + count)
    ]
    return rows, [f"{prefix}-ID-{index:04d}" for index in range(start, start + count)]


def _page(module: str, start: int, count: int):  # type: ignore[no-untyped-def]
    rows, item_ids = _rows(module.upper(), start, count)
    page_type = EWOReportPage if module == "ewo" else PAAReportPage
    return page_type(rows=rows, page=1, item_ids=item_ids, raw_xml="<never-export-this/>")


class ScriptedClient:
    def __init__(self, ewo_pages=(), paa_pages=()) -> None:  # type: ignore[no-untyped-def]
        self.timeout = 30.0
        self._request_deadline = None
        self._ewo_pages = list(ewo_pages)
        self._paa_pages = list(paa_pages)
        self.calls: list[dict[str, Any]] = []

    def _next(self, module: str, filters, page: int, page_size: int, max_records: int):  # type: ignore[no-untyped-def]
        self.calls.append(
            {
                "module": module,
                "filters": filters,
                "page": page,
                "page_size": page_size,
                "max_records": max_records,
            }
        )
        script = self._ewo_pages if module == "ewo" else self._paa_pages
        if not script:
            raise AssertionError(f"unexpected {module} page {page}")
        value = script.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def query_ewo_report(self, filters, page=1, page_size=50, max_records=2000):  # type: ignore[no-untyped-def]
        return self._next("ewo", filters, page, page_size, max_records)

    def query_paa_report(self, filters, page=1, page_size=50, max_records=2000):  # type: ignore[no-untyped-def]
        return self._next("paa", filters, page, page_size, max_records)


@pytest.fixture()
def captured_writer(monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    writes: list[dict[str, Any]] = []

    def write(path: Path, module: str, columns, rows) -> None:  # type: ignore[no-untyped-def]
        writes.append(
            {
                "path": path,
                "module": module,
                "columns": tuple(columns),
                "rows": [dict(row) for row in rows],
            }
        )
        path.write_bytes(b"fake-xlsx")

    monkeypatch.setattr(export_service, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(export_service, "_write_xlsx", write)
    return writes


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        (EWOReportFilters(), EWOReportFilters()),
        (EWOReportFilters(ewo_no="EWO-1"), EWOReportFilters(ewo_no="EWO-1")),
        (
            EWOReportFilters(
                ewo_no="EWO-1",
                project_code="P100",
                subject_keyword="seat",
                change_type="major",
                change_sub_type="drawing",
                area="PT",
                state="Open",
                rsp_department="VSE",
                submit_start="2026-01-01",
                submit_end="2026-01-31",
            ),
            EWOReportFilters(
                ewo_no="EWO-1",
                project_code="P100",
                subject_keyword="seat",
                change_type="major",
                change_sub_type="drawing",
                area="PT",
                state="Open",
                rsp_department="VSE",
                submit_start="2026-01-01",
                submit_end="2026-01-31",
            ),
        ),
    ],
    ids=("no-filter", "single-filter", "combined-filters"),
)
def test_ewo_export_accepts_no_single_and_combined_filters(
    filters: EWOReportFilters,
    expected: EWOReportFilters,
    captured_writer,
) -> None:
    client = ScriptedClient(ewo_pages=[_page("ewo", 0, 1)])

    result = export_service.export_ewo_report(client, filters)  # type: ignore[arg-type]

    assert result.status == "completed"
    assert result.count == 1
    assert result.stop_reason == "short_page"
    assert client.calls[0]["filters"] == expected
    assert captured_writer[0]["columns"] == DEFAULT_EWO_SELECT_FIELDS


def test_ewo_export_fetches_all_pages_with_identical_filters_and_short_last_page(captured_writer) -> None:
    filters = EWOReportFilters(project_code="P100", state="Open")
    client = ScriptedClient(
        ewo_pages=[_page("ewo", 0, export_service.DEFAULT_EXPORT_PAGE_SIZE), _page("ewo", 50, 2)]
    )

    result = export_service.export_ewo_report(client, filters)  # type: ignore[arg-type]

    assert result.count == 52
    assert result.pages_fetched == 2
    assert result.stop_reason == "short_page"
    assert [call["page"] for call in client.calls] == [1, 2]
    assert {call["page_size"] for call in client.calls} == {export_service.DEFAULT_EXPORT_PAGE_SIZE}
    assert all(call["filters"] == filters for call in client.calls)
    assert [row["_no"] for row in captured_writer[0]["rows"]][-2:] == ["EWO-0050", "EWO-0051"]


def test_ewo_export_rechecks_chinese_department_and_casefolded_model_before_write(
    captured_writer,
) -> None:
    rows = [
        {"_no": "EWO-1", "_rsp_department": "SGMW 车体工程一科", "_modelinfo": "f610s HEV"},
        {"_no": "EWO-2", "_rsp_department": "SGMW 车体工程一科", "_modelinfo": "OTHER"},
        {"_no": "EWO-3", "_rsp_department": None, "_modelinfo": "F610S"},
    ]
    page = EWOReportPage(rows=rows, page=1, item_ids=["1", "2", "3"], raw_xml="<private/>")
    filters = EWOReportFilters(
        rsp_department_keyword="  车体工程  ",
        model_keyword=" f610S ",
    )

    result = export_service.export_ewo_report(  # type: ignore[arg-type]
        ScriptedClient(ewo_pages=[page]), filters
    )

    assert result.count == 1
    assert [row["_no"] for row in captured_writer[0]["rows"]] == ["EWO-1"]


def test_paa_export_rechecks_department_or_vehicle_and_casefolds_vehicle(captured_writer) -> None:
    rows = [
        {
            "_no": "PAA-1",
            "_pe_tdc_department": "车体工程技术组",
            "_requester_department": None,
            "_vehicles": "f610s phev",
        },
        {
            "_no": "PAA-2",
            "_pe_tdc_department": "Other",
            "_requester_department": "车体工程申请组",
            "_vehicles": "F610S",
        },
        {
            "_no": "PAA-3",
            "_pe_tdc_department": None,
            "_requester_department": None,
            "_vehicles": "F610S",
        },
        {
            "_no": "PAA-4",
            "_pe_tdc_department": "车体工程技术组",
            "_requester_department": None,
            "_vehicles": None,
        },
    ]
    page = PAAReportPage(rows=rows, page=1, item_ids=["1", "2", "3", "4"], raw_xml="<private/>")
    filters = PAAReportFilters(department_keyword="车体工程", vehicle_keyword="f610s")

    result = export_service.export_paa_report(  # type: ignore[arg-type]
        ScriptedClient(paa_pages=[page]), filters
    )

    assert result.count == 2
    assert [row["_no"] for row in captured_writer[0]["rows"]] == ["PAA-1", "PAA-2"]


def test_department_contains_matching_is_casefolded_for_ewo_and_both_paa_fields() -> None:
    assert row_matches_filters(
        "ewo",
        {"_rsp_department": "BODY Engineering Team", "_modelinfo": "F610S"},
        EWOReportFilters(rsp_department_keyword="body engineering", model_keyword="f610s"),
    )
    assert row_matches_filters(
        "paa",
        {
            "_pe_tdc_department": "Other",
            "_requester_department": "BODY Engineering Request",
            "_vehicles": "F610S",
        },
        PAAReportFilters(department_keyword="body engineering", vehicle_keyword="f610s"),
    )


def test_client_side_filtering_uses_raw_page_length_for_stop_condition(captured_writer) -> None:
    full_rows = [
        {
            "_no": f"PAA-{index}",
            "_pe_tdc_department": "Other",
            "_requester_department": None,
            "_vehicles": "F610S",
        }
        for index in range(export_service.DEFAULT_EXPORT_PAGE_SIZE)
    ]
    full_rows[0]["_requester_department"] = "车体工程"
    first = PAAReportPage(
        rows=full_rows,
        page=1,
        item_ids=[f"ID-{index}" for index in range(len(full_rows))],
        raw_xml="<private/>",
    )
    second = PAAReportPage(
        rows=[
            {
                "_no": "PAA-last",
                "_pe_tdc_department": "车体工程",
                "_requester_department": None,
                "_vehicles": "f610s",
            }
        ],
        page=2,
        item_ids=["ID-last"],
        raw_xml="<private/>",
    )

    result = export_service.export_paa_report(  # type: ignore[arg-type]
        ScriptedClient(paa_pages=[first, second]),
        PAAReportFilters(department_keyword="车体工程", vehicle_keyword="F610S"),
    )

    assert result.status == "completed"
    assert result.stop_reason == "short_page"
    assert result.pages_fetched == 2
    assert result.count == 2


def test_matching_max_records_and_raw_scan_limit_are_distinct_partial_reasons(captured_writer) -> None:
    matching_rows = [
        {
            "_no": f"PAA-match-{index}",
            "_pe_tdc_department": "车体工程",
            "_vehicles": "F610S",
        }
        for index in range(export_service.DEFAULT_EXPORT_PAGE_SIZE)
    ]
    matching_page = PAAReportPage(
        rows=matching_rows,
        page=1,
        item_ids=[f"MATCH-{index}" for index in range(len(matching_rows))],
        raw_xml="<private/>",
    )
    matched = export_service.export_paa_report(  # type: ignore[arg-type]
        ScriptedClient(paa_pages=[matching_page]),
        PAAReportFilters(department_keyword="车体工程", vehicle_keyword="F610S"),
        max_records=3,
    )
    assert (matched.status, matched.stop_reason, matched.count, matched.limit_reached) == (
        "partial",
        "max_records",
        3,
        True,
    )

    nonmatching_rows = [
        {"_no": f"PAA-scan-{index}", "_pe_tdc_department": "Other", "_vehicles": "F610S"}
        for index in range(export_service.DEFAULT_EXPORT_PAGE_SIZE)
    ]
    scan_page = PAAReportPage(
        rows=nonmatching_rows,
        page=1,
        item_ids=[f"SCAN-{index}" for index in range(len(nonmatching_rows))],
        raw_xml="<private/>",
    )
    scanned = export_service.export_paa_report(  # type: ignore[arg-type]
        ScriptedClient(paa_pages=[scan_page]),
        PAAReportFilters(department_keyword="车体工程", vehicle_keyword="F610S"),
        max_records=2,
        max_pages=5,
    )
    assert (scanned.status, scanned.stop_reason, scanned.count, scanned.limit_reached) == (
        "partial",
        "max_scanned_records",
        0,
        True,
    )


def test_session_expiry_is_stable_failure_and_never_writes_partial_artifact(captured_writer) -> None:
    client = ScriptedClient(ewo_pages=[ArasCrawlerSessionExpired("private response body")])

    with pytest.raises(ArasReportExportError) as excinfo:
        export_service.export_ewo_report(client, EWOReportFilters())  # type: ignore[arg-type]

    assert excinfo.value.code == "SESSION_EXPIRED"
    assert "private response body" not in str(excinfo.value)
    assert captured_writer == []


def test_ewo_export_empty_result_still_writes_stable_header_file(captured_writer, tmp_path) -> None:
    client = ScriptedClient(ewo_pages=[_page("ewo", 0, 0)])

    result = export_service.export_ewo_report(client, EWOReportFilters())  # type: ignore[arg-type]

    assert result.count == 0
    assert result.stop_reason == "empty_page"
    assert result.file_name.startswith("EWO_")
    assert result.file_name.endswith(".xlsx")
    assert result.saved_path.parent == tmp_path.resolve()
    assert result.saved_path.read_bytes() == b"fake-xlsx"
    assert captured_writer[0]["columns"] == DEFAULT_EWO_SELECT_FIELDS
    assert captured_writer[0]["rows"] == []


def test_export_deduplicates_by_stable_item_id_across_pages(captured_writer) -> None:
    first = _page("ewo", 0, export_service.DEFAULT_EXPORT_PAGE_SIZE)
    second = _page("ewo", 50, 2)
    second.rows.insert(0, {"_no": "CHANGED-NUMBER", "state": "Closed"})
    second.item_ids.insert(0, first.item_ids[0])
    client = ScriptedClient(ewo_pages=[first, second])

    result = export_service.export_ewo_report(client, EWOReportFilters())  # type: ignore[arg-type]

    assert result.count == 52
    assert result.duplicates_removed == 1
    assert len(captured_writer[0]["rows"]) == 52
    assert "CHANGED-NUMBER" not in {row["_no"] for row in captured_writer[0]["rows"]}


@pytest.mark.parametrize(
    ("max_pages", "max_records", "expected_reason", "expected_count"),
    [
        (2, 1000, "max_pages", 100),
        (10, 7, "max_records", 7),
    ],
)
def test_ewo_export_safety_limits_create_explicit_partial_file(
    max_pages: int,
    max_records: int,
    expected_reason: str,
    expected_count: int,
    captured_writer,
) -> None:
    client = ScriptedClient(
        ewo_pages=[_page("ewo", 0, 50), _page("ewo", 50, 50), _page("ewo", 100, 50)]
    )

    result = export_service.export_ewo_report(
        client, EWOReportFilters(), max_pages=max_pages, max_records=max_records  # type: ignore[arg-type]
    )

    assert result.status == "partial"
    assert result.limit_reached is True
    assert result.stop_reason == expected_reason
    assert result.count == expected_count
    assert "_PARTIAL" in result.file_name
    assert result.saved_path.exists()


def test_export_stops_on_repeated_page_and_marks_partial(captured_writer) -> None:
    repeated = _page("paa", 0, export_service.DEFAULT_EXPORT_PAGE_SIZE)
    client = ScriptedClient(paa_pages=[repeated, _page("paa", 0, export_service.DEFAULT_EXPORT_PAGE_SIZE)])

    result = export_service.export_paa_report(client, PAAReportFilters())  # type: ignore[arg-type]

    assert result.status == "partial"
    assert result.stop_reason == "repeated_page"
    assert result.limit_reached is False
    assert result.count == export_service.DEFAULT_EXPORT_PAGE_SIZE
    assert result.duplicates_removed == export_service.DEFAULT_EXPORT_PAGE_SIZE
    assert result.pages_fetched == 2
    assert "_PARTIAL" in result.file_name


def test_export_middle_request_failure_is_stable_and_writes_no_partial_artifact(
    captured_writer,
    tmp_path,
) -> None:
    secret = "fictional-upstream-secret"
    client = ScriptedClient(
        ewo_pages=[_page("ewo", 0, export_service.DEFAULT_EXPORT_PAGE_SIZE), RuntimeError(secret)]
    )

    with pytest.raises(ArasReportExportError) as excinfo:
        export_service.export_ewo_report(client, EWOReportFilters())  # type: ignore[arg-type]

    assert excinfo.value.code == "UPSTREAM_REQUEST_FAILED"
    assert excinfo.value.http_status == 502
    assert secret not in str(excinfo.value)
    assert captured_writer == []
    assert list(tmp_path.iterdir()) == []


def test_export_write_failure_cleans_atomic_temp_and_reservation(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(export_service, "OUTPUT_DIR", tmp_path)

    def fail_after_partial_write(path: Path, *_args) -> None:  # type: ignore[no-untyped-def]
        path.write_bytes(b"partial")
        raise OSError("disk failure with fictional-secret")

    monkeypatch.setattr(export_service, "_write_xlsx", fail_after_partial_write)
    client = ScriptedClient(ewo_pages=[_page("ewo", 0, 1)])

    with pytest.raises(ArasReportExportError) as excinfo:
        export_service.export_ewo_report(client, EWOReportFilters())  # type: ignore[arg-type]

    assert excinfo.value.code == "FILE_WRITE_FAILED"
    assert "fictional-secret" not in str(excinfo.value)
    assert list(tmp_path.iterdir()) == []


def test_export_removes_sensitive_columns_and_redacts_sensitive_values(captured_writer) -> None:
    page = _page("ewo", 0, 1)
    page.rows[0].update(
        {
            "raw_xml": "<secret/>",
            "Authorization": "Bearer fictional-auth-secret",
            "session_token": "fictional-session-secret",
            "cookie": "sid=fictional-cookie-secret",
            "note": "Cookie: sid=fictional-cookie-secret Authorization: Bearer fictional-auth-secret",
        }
    )
    client = ScriptedClient(ewo_pages=[page])

    export_service.export_ewo_report(client, EWOReportFilters())  # type: ignore[arg-type]

    written = captured_writer[0]
    serialized = repr(written)
    for forbidden in (
        "raw_xml",
        "fictional-auth-secret",
        "fictional-session-secret",
        "fictional-cookie-secret",
    ):
        assert forbidden not in serialized
    assert "[redacted]" in written["rows"][0]["note"]


def test_paa_export_preserves_every_filter_and_fetches_all_pages(captured_writer) -> None:
    filter_values = {
        "paa_no": "PAA-1",
        "ewo_no": "EWO-1",
        "state": "Open",
        "area": "PT",
        "base": "Base-A",
        "department_keyword": None,
        "vehicle_keyword": "Vehicle",
        "submit_start": "2026-01-01",
        "submit_end": "2026-01-31",
        "mtl_rq_start": "2026-02-01",
        "mtl_rq_end": "2026-02-28",
    }
    assert set(filter_values) == {field.name for field in fields(PAAReportFilters)}
    filters = PAAReportFilters(**filter_values)
    pages = [_page("paa", 0, 50), _page("paa", 50, 3)]
    for page in pages:
        for row in page.rows:
            row["_vehicles"] = "Target Vehicle"
    client = ScriptedClient(paa_pages=pages)

    result = export_service.export_paa_report(client, filters)  # type: ignore[arg-type]

    assert result.count == 53
    assert result.stop_reason == "short_page"
    assert result.pages_fetched == 2
    assert all(call["filters"] == filters for call in client.calls)
    assert captured_writer[0]["columns"] == export_service._stable_safe_columns(
        DEFAULT_PAA_SELECT_FIELDS
    )


@pytest.mark.parametrize(
    ("script", "expected_reason", "expected_count"),
    [
        ([_page("paa", 0, 0)], "empty_page", 0),
        ([_page("paa", 0, 2)], "short_page", 2),
    ],
    ids=("empty-page", "short-page"),
)
def test_paa_export_empty_and_short_page_stops(
    script,
    expected_reason: str,
    expected_count: int,
    captured_writer,
) -> None:  # type: ignore[no-untyped-def]
    client = ScriptedClient(paa_pages=script)

    result = export_service.export_paa_report(client, PAAReportFilters())  # type: ignore[arg-type]

    assert result.status == "completed"
    assert result.stop_reason == expected_reason
    assert result.count == expected_count


def test_paa_export_deduplicates_business_number_when_item_ids_are_unusable(captured_writer) -> None:
    first_source = _page("paa", 0, 50)
    first = PAAReportPage(rows=first_source.rows, page=1, item_ids=[], raw_xml="<never-export-this/>")
    second_source = _page("paa", 50, 1)
    second_rows = [dict(first.rows[0]), *second_source.rows]
    second = PAAReportPage(rows=second_rows, page=2, item_ids=[], raw_xml="<never-export-this/>")
    client = ScriptedClient(paa_pages=[first, second])

    result = export_service.export_paa_report(client, PAAReportFilters())  # type: ignore[arg-type]

    assert result.count == 51
    assert result.duplicates_removed == 1


def test_paa_export_max_records_is_partial_and_field_count_is_stable(captured_writer) -> None:
    client = ScriptedClient(paa_pages=[_page("paa", 0, 50)])

    result = export_service.export_paa_report(
        client, PAAReportFilters(), max_records=4  # type: ignore[arg-type]
    )

    assert result.count == len(captured_writer[0]["rows"]) == 4
    assert result.stop_reason == "max_records"
    assert result.limit_reached is True
    assert all(tuple(row.keys())[:3] == ("_no", "state", "_subject") for row in captured_writer[0]["rows"])


class _FakeFont:
    Bold = False


class _FakeRange:
    def __init__(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        self.start = start
        self.end = end
        self.Value = None
        self.NumberFormat = None
        self.Font = _FakeFont()


class _FakeSheet:
    def __init__(self) -> None:
        self.Name = ""
        self.ranges: list[_FakeRange] = []
        self.Columns = type("Columns", (), {"AutoFit": lambda self: None})()

    @staticmethod
    def Cells(row: int, column: int) -> tuple[int, int]:
        return row, column

    def Range(self, start: tuple[int, int], end: tuple[int, int]) -> _FakeRange:
        cell_range = _FakeRange(start, end)
        self.ranges.append(cell_range)
        return cell_range


class _FakeWorkbook:
    def __init__(self) -> None:
        self.ActiveSheet = _FakeSheet()
        self.saved: tuple[str, int] | None = None
        self.closed = False

    def SaveAs(self, path: str, FileFormat: int) -> None:  # noqa: N803
        self.saved = path, FileFormat

    def Close(self, SaveChanges: bool) -> None:  # noqa: N803
        assert SaveChanges is False
        self.closed = True


class _FakeExcel:
    def __init__(self) -> None:
        self.Visible = True
        self.DisplayAlerts = True
        self.workbook = _FakeWorkbook()
        self.Workbooks = type("Workbooks", (), {"Add": lambda _self: self.workbook})()
        self.quit_called = False

    def Quit(self) -> None:
        self.quit_called = True


def _fake_excel_runtime() -> tuple[Any, None]:
    excel = _FakeExcel()
    dispatch = type(
        "Dispatch",
        (),
        {
            "DispatchEx": lambda _self, _name: excel,
            "Dispatch": lambda _self, _name: excel,
        },
    )()
    return dispatch, None


def test_xlsx_writer_empty_result_has_only_stable_headers(monkeypatch, tmp_path) -> None:
    excel = _FakeExcel()
    dispatch = type(
        "Dispatch",
        (),
        {"DispatchEx": lambda _self, _name: excel, "Dispatch": lambda _self, _name: excel},
    )()
    monkeypatch.setattr(export_service, "_excel_runtime", lambda: (dispatch, None))

    export_service._write_xlsx(tmp_path / "empty.xlsx", "ewo", ("_no", "state"), [])

    sheet = excel.workbook.ActiveSheet
    assert sheet.Name == "EWO"
    assert len(sheet.ranges) == 1
    assert sheet.ranges[0].Value == (("_no", "state"),)
    assert sheet.ranges[0].Font.Bold is True
    assert excel.workbook.saved is not None and excel.workbook.saved[1] == 51
    assert excel.workbook.closed is True
    assert excel.quit_called is True


def test_xlsx_writer_forces_text_and_neutralizes_formula_injection(monkeypatch, tmp_path) -> None:
    excel = _FakeExcel()
    dispatch = type(
        "Dispatch",
        (),
        {"DispatchEx": lambda _self, _name: excel, "Dispatch": lambda _self, _name: excel},
    )()
    monkeypatch.setattr(export_service, "_excel_runtime", lambda: (dispatch, None))

    export_service._write_xlsx(
        tmp_path / "formula.xlsx",
        "paa",
        ("_no", "state"),
        [{"_no": "=HYPERLINK(\"bad\")", "state": "+SUM(1,1)"}],
    )

    data_range = excel.workbook.ActiveSheet.ranges[1]
    assert data_range.NumberFormat == "@"
    assert data_range.Value == (("'=HYPERLINK(\"bad\")", "'+SUM(1,1)"),)


def test_output_name_collision_never_overwrites_existing_file(captured_writer, tmp_path, monkeypatch) -> None:
    class FixedDateTime:
        @classmethod
        def now(cls):  # type: ignore[no-untyped-def]
            return cls()

        @staticmethod
        def strftime(_format: str) -> str:
            return "20260722_130000"

    monkeypatch.setattr(export_service, "datetime", FixedDateTime)
    existing = tmp_path / "EWO_20260722_130000.xlsx"
    existing.write_bytes(b"keep-me")
    client = ScriptedClient(ewo_pages=[_page("ewo", 0, 1)])

    result = export_service.export_ewo_report(client, EWOReportFilters())  # type: ignore[arg-type]

    assert existing.read_bytes() == b"keep-me"
    assert result.file_name == "EWO_20260722_130000_2.xlsx"
    assert not list(tmp_path.glob("*.lock"))
    assert not list(tmp_path.glob(".*.tmp.xlsx"))
