# -*- coding: utf-8 -*-
"""Focused offline contract tests for production scheduled archive connectors.

All tests run strictly offline with in-memory fakes and temporary ArchiveStore.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping, Sequence
from xml.sax.saxutils import escape
from zipfile import ZipFile

import pytest

from core.archive_store import ArchiveStore
from core.credential_provider import ResolvedCredential
from core.report_contracts import report_contracts
from services.aras_crawler import (
    EWOReportFilters,
    NCRApprovalFilters,
    PAAReportFilters,
)
from services.aras_ncr_workbook import (
    NcrWorkbookOutcome,
    NcrWorkbookRow,
    parse_ncr_workbook,
)
from services.scheduled_archive_connectors import (
    ArasArchiveConnector,
    TDCArchiveConnector,
    _official_workbook_rows,
    _sanitize_archive_rows,
    create_production_archive_registry,
)
from services.pagination_integrity import WorkbookBookkeeping
from services.scheduled_archive_runner import (
    ArchiveConnectorRegistry,
    ArchiveJobContext,
)
from services.tdc_crawler import (
    TDCDataModelFilters,
    TDCSORFilters,
)


class FakeSession:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


class FakeAuthClient:
    def __init__(
        self,
        base_url: str = "https://mock.aras.local",
        *,
        timeout: float = 60.0,
        login_exc: Exception | None = None,
    ) -> None:
        self.base_url, self.timeout, self.login_exc = base_url, timeout, login_exc
        self.session = FakeSession()
        self.login_calls: list[tuple[str, str]] = []

    def login(self, username: str, password: str) -> Any:
        self.login_calls.append((username, password))
        if self.login_exc:
            raise self.login_exc
        return SimpleNamespace(session=self.session)


class FakeTDCCrawler:
    def __init__(
        self,
        *,
        session: Any = None,
        timeout: float = 60.0,
        output_dir: Path | None = None,
        crawl_exc: Exception | None = None,
        export_exc: Exception | None = None,
        rows: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        self.session, self.timeout, self.output_dir = session, timeout, output_dir
        self.crawl_exc, self.export_exc = crawl_exc, export_exc
        self.rows = rows if rows is not None else (
            {"incident": "INC-001", "applicant": "Tester"},
            {"incident": "INC-002", "applicant": "Tester2"},
        )
        self.last_crawl_filters: Any = None
        self.last_export_filters: Any = None
        self.crawl_max_records: int | None = None

    def crawl_data_model_all(self, filters: Any, max_records: int = 10000) -> Any:
        self.last_crawl_filters, self.crawl_max_records = filters, max_records
        if self.crawl_exc:
            raise self.crawl_exc
        return SimpleNamespace(rows=self.rows)

    def export_data_model(self, filters: Any) -> Any:
        self.last_export_filters = filters
        if self.export_exc:
            raise self.export_exc
        assert self.output_dir is not None
        p = self.output_dir / "tdc_data_model.xlsx"
        p.write_bytes(b"TDC_DATA_MODEL_XLSX_BYTES")
        return SimpleNamespace(path=p, file_name="tdc_data_model.xlsx", byte_count=25)

    def crawl_sor_all(self, filters: Any, max_records: int = 10000) -> Any:
        self.last_crawl_filters, self.crawl_max_records = filters, max_records
        if self.crawl_exc:
            raise self.crawl_exc
        return SimpleNamespace(rows=self.rows)

    def export_sor(self, filters: Any) -> Any:
        self.last_export_filters = filters
        if self.export_exc:
            raise self.export_exc
        assert self.output_dir is not None
        p = self.output_dir / "tdc_sor.xlsx"
        p.write_bytes(b"TDC_SOR_XLSX_BYTES")
        return SimpleNamespace(path=p, file_name="tdc_sor.xlsx", byte_count=18)


class TruncatedFallbackTDCCrawler(FakeTDCCrawler):
    """TDC fallback double exposing an explicit pagination cap."""

    def crawl_data_model_all(self, filters: Any, max_records: int = 10000) -> Any:
        result = super().crawl_data_model_all(filters, max_records)
        return SimpleNamespace(
            rows=result.rows,
            total=max_records + 1,
            stop_reason="max_records",
        )


class FakeArasCrawler:
    def __init__(
        self,
        base_url: str,
        *,
        session: Any = None,
        timeout: float = 60.0,
        prewarm: bool = False,
        crawl_exc: Exception | None = None,
        export_exc: Exception | None = None,
        download_exc: Exception | None = None,
        rows: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        self.base_url, self.session, self.timeout, self.prewarm = base_url, session, timeout, prewarm
        self.crawl_exc, self.export_exc, self.download_exc = crawl_exc, export_exc, download_exc
        self.rows = rows if rows is not None else ({"colA": "valA", "colB": "valB"},)
        self.last_filters: Any = None
        self.last_max_records: int | None = None
        self.query_progress_calls: list[Any] = []
        self.download_progress_calls: list[Any] = []
        self.extract_detail_calls: list[Any] = []
        self.download_detail_calls: list[Any] = []

    def crawl_ewo_report_all(self, filters: Any, max_records: int = 2000) -> Any:
        self.last_filters, self.last_max_records = filters, max_records
        if self.crawl_exc:
            raise self.crawl_exc
        return SimpleNamespace(rows=self.rows)

    def crawl_paa_report_all(self, filters: Any, max_records: int = 12000) -> Any:
        self.last_filters, self.last_max_records = filters, max_records
        if self.crawl_exc:
            raise self.crawl_exc
        return SimpleNamespace(rows=self.rows)

    def query_ncr_approval_progress(self, filters: Any) -> Any:
        self.last_filters = filters
        self.query_progress_calls.append(filters)
        if self.export_exc:
            raise self.export_exc
        return SimpleNamespace(
            file_id="FID-1", file_name="ncr_progress.xlsx",
            record_id="RID-1", raw_xml="<raw_secret_progress_xml/>",
        )

    def download_ncr_progress_file(self, export: Any, target_dir: Path) -> Path:
        self.download_progress_calls.append(export)
        if self.download_exc:
            raise self.download_exc
        p = target_dir / export.file_name
        p.write_bytes(b"ARAS_NCR_PROGRESS_XLSX_BYTES")
        return p

    def extract_ncr_approval_detail(self, filters: Any) -> Any:
        self.last_filters = filters
        self.extract_detail_calls.append(filters)
        if self.export_exc:
            raise self.export_exc
        return SimpleNamespace(file_name="ncr_detail.xlsx", raw_xml="<raw_secret_detail_xml/>")

    def download_ncr_detail_file(self, file_name: str, target_dir: Path) -> Path:
        self.download_detail_calls.append(file_name)
        if self.download_exc:
            raise self.download_exc
        p = target_dir / file_name
        p.write_bytes(b"ARAS_NCR_DETAIL_XLSX_BYTES")
        return p


def make_store(tmp_path: Path) -> ArchiveStore:
    return ArchiveStore({"default": tmp_path}, reserve_bytes=0)


def _cell_ref(column: int, row: int) -> str:
    result = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        result = chr(65 + remainder) + result
    return f"{result}{row}"


def _write_official_data_model_xlsx(path: Path) -> None:
    headers = report_contracts()["tdc_data_model"]["headerRows"][0]
    values = ["INC-REAL", "流程", "DOC-REAL"] + [""] * (len(headers) - 3)
    values[-1] = "已完成"
    header_cells = "".join(
        f'<c r="{_cell_ref(index, 1)}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
        for index, value in enumerate(headers, 1)
    )
    value_cells = "".join(
        f'<c r="{_cell_ref(index, 2)}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
        for index, value in enumerate(values, 1)
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        f'<row r="1">{header_cells}</row><row r="2">{value_cells}</row>'
        '</sheetData></worksheet>'
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


def _write_official_ncr_form_xlsx(path: Path) -> None:
    contract = report_contracts()["ncr_detail"]
    vehicle_headers = contract["headerRows"][0]
    engine_headers = list(vehicle_headers[:17]) + list(vehicle_headers[34:])
    values_by_label = {
        "状态": "审批中",
        "编号": "NCR-SYNTH-1",
        "提交日期": "2026-09-01",
        "项目": "F610S",
        "区域": "科室A",
        "NCR编号": "NCR-SYNTH-1",
        "当前节点": "PE提交",
        "测算工程工装费用(万元)": "10",
        "批准工程工装费用（万元）": "9",
        "实际工程工装费用(万元)": "8",
        "测算单件成本变化（元）": "3",
        "批准单件成本变化（元）": "2",
        "实际单件成本变化（元）": "-1",
    }

    def row_xml(row_number: int, values: Sequence[object]) -> str:
        cells = []
        for index, value in enumerate(values, 1):
            if value in (None, ""):
                continue
            cells.append(
                f'<c r="{_cell_ref(index, row_number)}" t="inlineStr">'
                f"<is><t>{escape(str(value))}</t></is></c>"
            )
        return f'<row r="{row_number}">{"".join(cells)}</row>'

    def values_for(headers: Sequence[object]) -> list[object]:
        return [values_by_label.get(str(header or ""), "") for header in headers]

    vehicle_rows = [list(vehicle_headers)]
    vehicle_rows.extend([[""] * len(vehicle_headers) for _ in range(4)])
    vehicle_rows.append(values_for(vehicle_headers))
    engine_rows = [engine_headers, values_for(engine_headers)]

    def sheet_xml(rows: Sequence[Sequence[object]]) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(row_xml(i, row) for i, row in enumerate(rows, 1))}</sheetData>'
            '</worksheet>'
        )

    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="整车" sheetId="1" r:id="rId1"/>'
        '<sheet name="发动机" sheetId="2" r:id="rId2"/></sheets></workbook>'
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet2.xml"/></Relationships>'
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml(vehicle_rows))
        archive.writestr("xl/worksheets/sheet2.xml", sheet_xml(engine_rows))


def test_official_ncr_form_rows_align_vehicle_and_engine_columns(tmp_path: Path) -> None:
    path = tmp_path / "official-ncr-detail.xlsx"
    _write_official_ncr_form_xlsx(path)

    outcome = parse_ncr_workbook(path, "ncr_detail")
    rows = outcome.named_rows()

    assert outcome.complete is True
    assert len(rows) == 2
    assert [item["sheetName"] for item in rows] == ["整车", "发动机"]
    detail_labels = [
        str(value or "").strip()
        for value in report_contracts()["ncr_detail"]["headerRows"][0]
    ]
    # 两条工作表都按已批准列名对齐：成本列在两侧落在同一标签下，
    # 行形状是按标签命名的字典（与同步路径同形），并携带契约顺序的位置视图。
    for row in rows:
        assert row["NCR编号"] == "NCR-SYNTH-1"
        assert row["测算工程工装费用(万元)"] == "10"
        assert row["批准工程工装费用（万元）"] == "9"
        assert len(row["values"]) == 65
        assert row["values"][detail_labels.index("测算工程工装费用(万元)")] == "10"
    assert outcome.bookkeeping_facts()["rowsParsed"] == 2


def test_official_ncr_truncated_preview_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = SimpleNamespace(
        sheet_name="Sheet1",
        rows=[[]],
        truncated=True,
    )
    monkeypatch.setattr(
        "services.aras_ncr_workbook.read_xlsx_workbook_preview",
        lambda *args, **kwargs: (preview,),
    )

    outcome = parse_ncr_workbook(tmp_path / "ncr.xlsx", "ncr_progress")

    assert outcome.complete is False
    assert outcome.stop_reason == "workbook_truncated"
    assert outcome.projection_error == "official_workbook_truncated"
    assert outcome.named_rows() == ()


def test_tdc_truncated_preview_is_exposed_on_collection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = SimpleNamespace(
        rows=[],
        truncated=True,
    )
    monkeypatch.setattr(
        "services.scheduled_archive_connectors.read_xlsx_preview",
        lambda *args, **kwargs: preview,
    )
    connector, _ = make_tdc_harness(tmp_path, FakeTDCCrawler)

    collection = connector.collect(
        make_context(
            "tdc_data_model",
            source_type="tdc",
            report_type="data_model",
            output_subdir="tdc_truncated",
            run_id=63,
        ),
        random_credential()[0],
    )

    assert collection.form_projection_error == "official_workbook_truncated"
    assert collection.form_rows is None
    assert collection.record_count == 0
    assert collection.artifacts


def test_official_data_model_workbook_rows_are_used_for_normalization(tmp_path: Path) -> None:
    path = tmp_path / "official-data-model.xlsx"
    _write_official_data_model_xlsx(path)

    rows = _official_workbook_rows(path, "data_model")

    assert rows == (
        {
            "实例号": "INC-REAL",
            "流程名": "流程",
            "流水单号": "DOC-REAL",
            **{str(header): ("已完成" if index == len(report_contracts()["tdc_data_model"]["headerRows"][0]) - 1 else "")
               for index, header in enumerate(report_contracts()["tdc_data_model"]["headerRows"][0][3:], 3)},
        },
    )


def make_context(
    job_key: str,
    *,
    source_type: str = "tdc",
    report_type: str = "data_model",
    filters: Mapping[str, Any] | None = None,
    output_subdir: str = "",
    output_directory: str = "",
    run_id: int = 1,
) -> ArchiveJobContext:
    return ArchiveJobContext(
        job_id=10, job_key=job_key, source_type=source_type,
        report_type=report_type, filters=filters or {},
        output_subdir=output_subdir, output_directory=output_directory, run_id=run_id,
    )


def random_credential() -> tuple[ResolvedCredential, str, str]:
    user, pwd = f"user_{secrets.token_hex(8)}", f"pass_{secrets.token_hex(16)}"
    return ResolvedCredential(username=user, password=pwd), user, pwd


def make_harness(
    tmp_path: Path,
    connector_cls: type,
    *,
    login_exc: Exception | None = None,
    crawl_exc: Exception | None = None,
    export_exc: Exception | None = None,
    download_exc: Exception | None = None,
) -> tuple[Any, list[FakeAuthClient], list[Any]]:
    auths: list[FakeAuthClient] = []
    crawlers: list[Any] = []

    def auth_factory(**kw: Any) -> FakeAuthClient:
        inst = FakeAuthClient(login_exc=login_exc, **kw)
        auths.append(inst)
        return inst

    def tdc_factory(**kw: Any) -> FakeTDCCrawler:
        inst = FakeTDCCrawler(crawl_exc=crawl_exc, export_exc=export_exc, **kw)
        crawlers.append(inst)
        return inst

    def aras_factory(*a: Any, **kw: Any) -> FakeArasCrawler:
        inst = FakeArasCrawler(
            *a,
            crawl_exc=crawl_exc,
            export_exc=export_exc,
            download_exc=download_exc,
            **kw,
        )
        crawlers.append(inst)
        return inst

    crawler_factory: Callable[..., Any] = tdc_factory if connector_cls is TDCArchiveConnector else aras_factory
    connector = connector_cls(make_store(tmp_path), auth_factory=auth_factory, crawler_factory=crawler_factory)
    return connector, auths, crawlers


def test_normalized_archive_rows_drop_secret_fields_and_redact_nested_values() -> None:
    rows = _sanitize_archive_rows(
        [
            {
                "incident": "INC-1",
                "cookie": "sid=secret-cookie",
                "note": "Authorization: Bearer secret-token",
                "metadata": {"password": "secret-password", "owner": "Tester"},
            }
        ]
    )

    assert rows == (
        {
            "incident": "INC-1",
            "note": "Authorization: [redacted]",
            "metadata": {"owner": "Tester"},
        },
    )


def test_production_registry_approved_job_keys(tmp_path: Path) -> None:
    registry = create_production_archive_registry(make_store(tmp_path))
    assert isinstance(registry, ArchiveConnectorRegistry)
    expected = {"tdc_data_model", "tdc_sor", "aras_ewo", "aras_paa", "aras_ncr_progress", "aras_ncr_detail"}
    assert set(registry.registered_job_keys) == expected
    assert len(registry.registered_job_keys) == 6
    assert "aras_aface" not in registry.registered_job_keys
    assert not any("aface" in k for k in registry.registered_job_keys)
    assert registry.get("aras_aface") is None
    assert registry.get("unknown_job") is None

    with pytest.raises(ValueError, match="archive connector job key is not approved"):
        registry.register("aras_aface", registry.get("aras_ewo"))


@pytest.mark.parametrize(
    "job_key,source_type,report_type,filters_in,expected_filter_type,expected_attrs",
    [
        (
            "tdc_data_model", "tdc", "data_model",
            {
                "incident": "INC-99", "applicant": "John Doe", "department": "DeptA",
                "section": "SecB", "applicationStart": "2026-01-01", "applicationEnd": "2026-01-31",
                "projectModel": "PM-1", "partNumber": "PN-01", "modelNumber": "MN-02",
            },
            TDCDataModelFilters,
            {
                "instance_no": "INC-99", "applicant": "John Doe", "department": "DeptA",
                "section": "SecB", "application_start": "2026-01-01", "application_end": "2026-01-31",
                "project_model": "PM-1", "part_number": "PN-01", "model_number": "MN-02",
            },
        ),
        (
            "tdc_sor", "tdc", "sor",
            {
                "processNo": "PROC-1", "processType": "Type1", "carTypeProject": "CTP-1",
                "carTypeProjectId": "PID-99",
                "applicant": "Jane Doe", "title": "Title1", "department": "DeptC",
                "section": "SecD", "applicationStart": "2026-02-01", "applicationEnd": "2026-02-28",
                "partNumber": "P-99", "partName": "Name99", "version": "v1",
                "sorNumber": "SOR-88", "latestCompletedNode": "NodeA", "approvalStatus": "Approved",
            },
            TDCSORFilters,
            {
                "serial_number": "PROC-1", "process_type": "Type1", "car_type_project": "CTP-1",
                "car_type_project_id": "PID-99",
                "applicant": "Jane Doe", "title": "Title1", "department": "DeptC",
                "section": "SecD", "application_start": "2026-02-01", "application_end": "2026-02-28",
                "part_number": "P-99", "part_name": "Name99", "version": "v1",
                "sor_number": "SOR-88", "latest_completed_node": "NodeA", "approval_status": "Approved",
            },
        ),
    ],
)
def test_tdc_connector_collect_success(
    tmp_path: Path,
    job_key: str,
    source_type: str,
    report_type: str,
    filters_in: dict[str, Any],
    expected_filter_type: type,
    expected_attrs: dict[str, Any],
) -> None:
    connector, auth_list, crawlers = make_harness(tmp_path, TDCArchiveConnector)
    context = make_context(
        job_key, source_type=source_type, report_type=report_type,
        filters=filters_in, output_subdir="custom_tdc_subdir", run_id=42,
    )
    credential, user, pwd = random_credential()
    collection = connector.collect(context, credential)

    assert auth_list[0].timeout == 60.0
    assert auth_list[0].login_calls == [(user, pwd)]
    assert auth_list[0].session.closed == 1

    crawler = crawlers[0]
    assert crawler.timeout == 60.0
    assert crawler.crawl_max_records == 10000
    assert isinstance(crawler.last_crawl_filters, expected_filter_type)
    for field_name, expected_val in expected_attrs.items():
        assert getattr(crawler.last_crawl_filters, field_name) == expected_val
    assert crawler.last_export_filters == crawler.last_crawl_filters

    assert collection.record_count == len(crawler.rows)
    assert len(collection.artifacts) == 3
    assert [a.artifact_type for a in collection.artifacts] == ["official_xlsx", "normalized_csv", "normalized_json"]
    for art in collection.artifacts:
        assert art.relative_path.startswith(f"custom_tdc_subdir/{source_type}/{report_type}/")
        assert (tmp_path / art.relative_path).is_file()


def test_tdc_connector_writes_to_task_output_directory(
    tmp_path: Path,
) -> None:
    """An explicit task directory becomes the archive root for all generated artifacts."""
    connector, _, _ = make_harness(tmp_path, TDCArchiveConnector)
    selected = tmp_path.parent / f"{tmp_path.name}-selected-archive"
    selected.mkdir()
    context = make_context(
        "tdc_data_model",
        output_directory=str(selected),
        run_id=43,
    )
    credential, _, _ = random_credential()

    collection = connector.collect(context, credential)

    assert collection.artifacts
    for artifact in collection.artifacts:
        assert (selected / artifact.relative_path).is_file()
        assert not (tmp_path / artifact.relative_path).exists()


@pytest.mark.parametrize(
    "job_key,source_type,report_type,filters_in,expected_filter_type,expected_attrs,expected_max_records",
    [
        (
            "aras_ewo", "aras", "ewo",
            {
                "ewoNo": "EWO-10", "projectCode": "PRJ-1", "subjectKeyword": "Subj",
                "changeType": "Chg", "changeSubType": "SubChg", "area": "Area1",
                "state": "State1", "responsibleDepartment": "Dept1",
                "submitStart": "2026-03-01", "submitEnd": "2026-03-31",
            },
            EWOReportFilters,
            {
                "ewo_no": "EWO-10", "project_code": "PRJ-1", "subject_keyword": "Subj",
                "change_type": "Chg", "change_sub_type": "SubChg", "area": "Area1",
                "state": "State1", "rsp_department": "Dept1",
                "submit_start": "2026-03-01", "submit_end": "2026-03-31",
            },
            2000,
        ),
        (
            "aras_paa", "aras", "paa",
            {
                "paaNo": "PAA-20", "ewoNo": "EWO-20", "state": "State2",
                "area": "Area2", "base": "Base2", "vehicleKeyword": "Veh",
                "submitStart": "2026-04-01", "submitEnd": "2026-04-30",
                "materialRequestStart": "2026-04-05", "materialRequestEnd": "2026-04-25",
                "department": "Dept2",
            },
            PAAReportFilters,
            {
                "paa_no": "PAA-20", "ewo_no": "EWO-20", "state": "State2",
                "area": "Area2", "base": "Base2", "vehicle_keyword": "Veh",
                "submit_start": "2026-04-01", "submit_end": "2026-04-30",
                "mtl_rq_start": "2026-04-05", "mtl_rq_end": "2026-04-25",
                "department": "Dept2",
            },
            12000,
        ),
    ],
)
def test_aras_ewo_paa_collect_success(
    tmp_path: Path,
    job_key: str,
    source_type: str,
    report_type: str,
    filters_in: dict[str, Any],
    expected_filter_type: type,
    expected_attrs: dict[str, Any],
    expected_max_records: int,
) -> None:
    connector, auth_list, crawlers = make_harness(tmp_path, ArasArchiveConnector)
    context = make_context(
        job_key, source_type=source_type, report_type=report_type,
        filters=filters_in, output_subdir="custom_aras_subdir", run_id=55,
    )
    credential, _, _ = random_credential()
    collection = connector.collect(context, credential)

    assert auth_list[0].timeout == 60.0
    assert auth_list[0].session.closed == 1

    crawler = crawlers[0]
    assert crawler.timeout == 60.0
    assert crawler.prewarm is False
    assert crawler.last_max_records == expected_max_records
    assert isinstance(crawler.last_filters, expected_filter_type)
    for field_name, expected_val in expected_attrs.items():
        assert getattr(crawler.last_filters, field_name) == expected_val

    assert collection.record_count == len(crawler.rows)
    assert collection.form_rows == tuple(dict(row) for row in crawler.rows)
    assert len(collection.artifacts) == 2
    assert [a.artifact_type for a in collection.artifacts] == ["normalized_csv", "normalized_json"]
    for art in collection.artifacts:
        assert art.relative_path.startswith(f"custom_aras_subdir/{source_type}/{report_type}/")
        assert (tmp_path / art.relative_path).is_file()


@pytest.mark.parametrize(
    "job_key,report_type,is_progress",
    [
        ("aras_ncr_progress", "ncr_progress", True),
        ("aras_ncr_detail", "ncr_detail", False),
    ],
)
def test_aras_ncr_progress_detail_success(
    tmp_path: Path,
    job_key: str,
    report_type: str,
    is_progress: bool,
) -> None:
    connector, auth_list, crawlers = make_harness(tmp_path, ArasArchiveConnector)
    filters_in = {
        "buyStart": "2026-05-01", "buyEnd": "2026-05-31",
        "peStart": "2026-05-02", "peEnd": "2026-05-30",
        "ncrNo": "NCR-101", "projectNames": ["ProjA", "ProjB"],
        "sectionCode": "SEC-01", "sectionCodes": ["SEC-01", "SEC-02"],
        "changeType": "TypeA", "otherCondition": "1",
    }
    context = make_context(
        job_key, source_type="aras", report_type=report_type,
        filters=filters_in, output_subdir="ncr_sub", run_id=77,
    )
    credential, _, _ = random_credential()
    collection = connector.collect(context, credential)

    assert auth_list[0].session.closed == 1
    crawler = crawlers[0]
    assert isinstance(crawler.last_filters, NCRApprovalFilters)
    assert crawler.last_filters.buy_start == "2026-05-01"
    assert crawler.last_filters.buy_end == "2026-05-31"
    assert crawler.last_filters.pe_start == "2026-05-02"
    assert crawler.last_filters.pe_end == "2026-05-30"
    assert crawler.last_filters.ncr_no == "NCR-101"
    assert crawler.last_filters.project_names == ("ProjA", "ProjB")
    assert crawler.last_filters.section_code == "SEC-01"
    assert crawler.last_filters.section_codes == ("SEC-01", "SEC-02")
    assert crawler.last_filters.change_type == "TypeA"
    assert crawler.last_filters.othercondition == "1"

    if is_progress:
        assert len(crawler.query_progress_calls) == 1 and len(crawler.download_progress_calls) == 1
        assert len(crawler.extract_detail_calls) == 0 and len(crawler.download_detail_calls) == 0
    else:
        assert len(crawler.query_progress_calls) == 0 and len(crawler.download_progress_calls) == 0
        assert len(crawler.extract_detail_calls) == 1 and len(crawler.download_detail_calls) == 1

    assert collection.record_count == 0
    assert len(collection.artifacts) == 2
    assert [a.artifact_type for a in collection.artifacts] == ["official_xlsx", "manifest_json"]

    manifest_art = collection.artifacts[1]
    assert manifest_art.display_name == f"{report_type}-manifest.json"
    manifest_data = json.loads((tmp_path / manifest_art.relative_path).read_text(encoding="utf-8"))
    assert manifest_data["jobKey"] == job_key
    assert manifest_data["recordCount"] is None
    assert manifest_data["normalization"] == "pending_verified_workbook_contract"
    # 簿记事实随 manifest 披露：用于生产证据校准 NCR 准入策略。
    assert manifest_data["stopReason"] == "workbook_unreadable"
    assert manifest_data["projectionError"] == "official_workbook_unreadable"
    assert manifest_data["bookkeeping"] == {
        "rowsRead": 0,
        "rowsParsed": 0,
        "rowsBlank": 0,
        "rowsHeader": 0,
        "rowsUnclassified": 0,
        "cellsOutsideContract": 0,
    }
    assert collection.form_projection_error == "official_workbook_unreadable"


def test_aras_ncr_admission_failure_blocks_projection_but_keeps_official_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """准入失败（簿记不平）时：不落库任何部分投影，但官方产物仍归档并可取证。"""
    connector, _, _ = make_harness(tmp_path, ArasArchiveConnector)
    monkeypatch.setattr(
        "services.scheduled_archive_connectors.parse_ncr_workbook",
        lambda path, report_type: NcrWorkbookOutcome(
            report_type=report_type,
            rows=(
                NcrWorkbookRow(
                    values=("NCR-1",),
                    labels={"NCR编号": "NCR-1"},
                    sheet_name="Sheet1",
                ),
            ),
            bookkeeping=WorkbookBookkeeping(
                read_rows=11, parsed_rows=8, blank_rows=2
            ),
            projection_error=None,
            stop_reason="workbook_accounting_mismatch",
        ),
    )

    collection = connector.collect(
        make_context(
            "aras_ncr_progress",
            source_type="aras",
            report_type="ncr_progress",
            output_subdir="ncr_admission",
            run_id=79,
        ),
        random_credential()[0],
    )

    assert collection.form_rows is None
    assert collection.form_projection_error == "official_workbook_admission_failed"
    assert collection.record_count == 0
    assert [a.artifact_type for a in collection.artifacts] == [
        "official_xlsx",
        "manifest_json",
    ]
    manifest = json.loads(
        (tmp_path / collection.artifacts[1].relative_path).read_text(encoding="utf-8")
    )
    assert manifest["stopReason"] == "workbook_accounting_mismatch"
    assert manifest["projectionError"] == "official_workbook_admission_failed"
    assert manifest["recordCount"] is None
    assert manifest["normalization"] == "pending_verified_workbook_contract"
    # 簿记事实随 manifest 披露，供生产证据校准准入策略。
    assert manifest["bookkeeping"]["rowsRead"] == 11
    assert manifest["bookkeeping"]["rowsParsed"] == 8


def test_ncr_archive_path_has_no_binding_department_narrowing(tmp_path: Path) -> None:
    """两路径 NCR 行集合口径已收敛（2026-09-26 生产证据后统一）：绑定部门在两条
    路径都不参与查询与收窄。

    归档任务用 `sectionCode/sectionCodes` 走**上游**查询；交付物绑定曾在
    `services.project_status_connectors._collect_ncr_rows` 里按 `department`
    做内存收窄——生产实锤（2026-09-26）：NCR 报表没有部门维度，部门名兜底进
    seccode 会让服务端导出方法生成不了文件，部门收窄又匹配不到科室列。两者
    已一并移除（seccode 与内存收窄只接受真实科室代码）。本测试钉住：归档源码
    无收窄函数、同步源码保留收窄函数（仅服务 sectionCode 来源）。
    """
    import services.project_status_connectors as project_connectors

    archive_source = Path(
        __import__(
            "services.scheduled_archive_connectors", fromlist=["__file__"]
        ).__file__
    ).read_text(encoding="utf-8")
    assert "_filter_ncr_rows_by_department" not in archive_source
    assert "_filter_ncr_rows_by_department" in Path(
        project_connectors.__file__
    ).read_text(encoding="utf-8")

    # 归档侧仍接受更宽的键集（含 sectionCodes / otherCondition）。
    archive_filters = ArasArchiveConnector._ncr_filters(
        {
            "sectionCodes": ["SEC-01"],
            "otherCondition": "1",
            "peStart": "2026-05-02",
        }
    )
    assert archive_filters.section_codes == ("SEC-01",)
    assert archive_filters.othercondition == "1"


def test_aras_ncr_form_projection_runs_before_download_directory_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector, _, _ = make_harness(tmp_path, ArasArchiveConnector)
    seen_paths: list[bool] = []

    def parse_live_workbook(path: Path, report_type: str) -> NcrWorkbookOutcome:
        seen_paths.append(path.is_file())
        assert report_type == "ncr_progress"
        return NcrWorkbookOutcome(
            report_type="ncr_progress",
            rows=(
                NcrWorkbookRow(
                    values=("NCR-SYNTH-1",),
                    labels={"NCR编号": "NCR-SYNTH-1"},
                    sheet_name="Sheet1",
                ),
            ),
            bookkeeping=WorkbookBookkeeping(read_rows=1, parsed_rows=1),
            projection_error=None,
            stop_reason="workbook_rows",
        )

    monkeypatch.setattr(
        "services.scheduled_archive_connectors.parse_ncr_workbook",
        parse_live_workbook,
    )
    collection = connector.collect(
        make_context(
            "aras_ncr_progress",
            source_type="aras",
            report_type="ncr_progress",
            output_subdir="ncr_projection",
            run_id=78,
        ),
        random_credential()[0],
    )

    assert seen_paths == [True]
    assert collection.record_count == 1
    # 归档路径发布与同步路径同形的命名行（按已批准表头标签 + 契约顺序的位置视图）。
    assert collection.form_rows == (
        {"NCR编号": "NCR-SYNTH-1", "values": ["NCR-SYNTH-1"], "sheetName": "Sheet1"},
    )


@pytest.mark.parametrize(
    "connector_cls,job_key,invalid_filters",
    [
        (TDCArchiveConnector, "tdc_data_model", {"unknownKey": "val"}),
        (TDCArchiveConnector, "tdc_sor", {"badFieldName": "val"}),
        (ArasArchiveConnector, "aras_ewo", {"invalidEwoField": "val"}),
        (ArasArchiveConnector, "aras_paa", {"invalidPaaField": "val"}),
        (ArasArchiveConnector, "aras_ncr_progress", {"invalidNcrField": "val"}),
        (ArasArchiveConnector, "aras_ncr_detail", {"extraField": "val"}),
    ],
)
def test_unknown_filter_fields_rejected(
    tmp_path: Path,
    connector_cls: type,
    job_key: str,
    invalid_filters: dict[str, Any],
) -> None:
    connector, auth_list, _ = make_harness(tmp_path, connector_cls)
    context = make_context(job_key, filters=invalid_filters)
    credential, _, _ = random_credential()
    with pytest.raises(ValueError, match="unsupported fields"):
        connector.collect(context, credential)
    assert len(auth_list) == 1 and auth_list[0].session.closed == 1


@pytest.mark.parametrize(
    "invalid_val",
    [
        "A" * 513,
        "hello" + chr(1) + "world",
        "line1" + chr(10) + "line2",
        "tab" + chr(9) + "char",
        "esc" + chr(27) + "test",
    ],
)
def test_filter_value_length_and_control_chars_rejected(tmp_path: Path, invalid_val: str) -> None:
    connector, auth_list, _ = make_harness(tmp_path, TDCArchiveConnector)
    context = make_context("tdc_data_model", filters={"incident": invalid_val})
    credential, _, _ = random_credential()
    with pytest.raises(ValueError, match="archive filter value is invalid"):
        connector.collect(context, credential)
    assert len(auth_list) == 1 and auth_list[0].session.closed == 1


@pytest.mark.parametrize(
    "connector_cls,job_key,invalid_filters",
    [
        (TDCArchiveConnector, "tdc_data_model", {"incident": ["bad", "list"]}),
        (TDCArchiveConnector, "tdc_data_model", {"incident": {"bad": "dict"}}),
        (TDCArchiveConnector, "tdc_sor", {"processNo": ["bad", "list"]}),
        (ArasArchiveConnector, "aras_ewo", {"ewoNo": ["bad", "list"]}),
        (ArasArchiveConnector, "aras_paa", {"paaNo": {"bad": "dict"}}),
        (ArasArchiveConnector, "aras_ncr_progress", {"ncrNo": ["bad", "list"]}),
    ],
)
def test_filter_scalar_shape_rejected(
    tmp_path: Path,
    connector_cls: type,
    job_key: str,
    invalid_filters: dict[str, Any],
) -> None:
    connector, auth_list, _ = make_harness(tmp_path, connector_cls)
    context = make_context(job_key, filters=invalid_filters)
    credential, _, _ = random_credential()
    with pytest.raises(ValueError, match="archive scalar filter must be a string"):
        connector.collect(context, credential)
    assert len(auth_list) == 1 and auth_list[0].session.closed == 1


@pytest.mark.parametrize("invalid_list", ["not_a_list", b"bytes", 12345, ["item"] * 101])
def test_filter_list_shape_and_limit_rejected(tmp_path: Path, invalid_list: Any) -> None:
    connector, auth_list, _ = make_harness(tmp_path, ArasArchiveConnector)
    context = make_context("aras_ncr_progress", filters={"projectNames": invalid_list})
    credential, _, _ = random_credential()
    with pytest.raises(ValueError, match="archive filter list"):
        connector.collect(context, credential)
    assert len(auth_list) == 1 and auth_list[0].session.closed == 1


def test_tdc_sor_filters_whitelist_accepts_car_type_project_id() -> None:
    filters = TDCArchiveConnector._sor_filters({
        "carTypeProject": "P100",
        "carTypeProjectId": "project-id-1",
    })
    assert filters.car_type_project == "P100"
    assert filters.car_type_project_id == "project-id-1"


def test_empty_and_whitespace_filter_values_are_normalized_to_none(tmp_path: Path) -> None:
    connector, auth_list, crawlers = make_harness(tmp_path, TDCArchiveConnector)
    context = make_context("tdc_data_model", filters={"incident": "   ", "applicant": None})
    credential, _, _ = random_credential()
    connector.collect(context, credential)
    assert len(auth_list) == 1 and auth_list[0].session.closed == 1
    assert crawlers[0].last_crawl_filters.instance_no is None
    assert crawlers[0].last_crawl_filters.applicant is None


@pytest.mark.parametrize(
    "connector_cls,unsupported_job_key,expected_err",
    [
        (TDCArchiveConnector, "aras_ewo", "TDC archive job is not supported"),
        (TDCArchiveConnector, "invalid_job", "TDC archive job is not supported"),
        (ArasArchiveConnector, "tdc_data_model", "ARAS archive job is not supported"),
        (ArasArchiveConnector, "aras_aface", "ARAS archive job is not supported"),
        (ArasArchiveConnector, "unsupported_job", "ARAS archive job is not supported"),
    ],
)
def test_unsupported_connector_context_rejected(
    tmp_path: Path,
    connector_cls: type,
    unsupported_job_key: str,
    expected_err: str,
) -> None:
    connector = connector_cls(make_store(tmp_path))
    context = make_context(unsupported_job_key)
    credential, _, _ = random_credential()
    with pytest.raises(ValueError, match=expected_err):
        connector.collect(context, credential)


@pytest.mark.parametrize(
    "job_key,fail_stage",
    [
        ("tdc_data_model", "login"), ("tdc_data_model", "crawl"), ("tdc_data_model", "export"),
        ("aras_ewo", "crawl"), ("aras_ncr_progress", "export"), ("aras_ncr_progress", "download"),
        ("aras_ncr_detail", "export"), ("aras_ncr_detail", "download"),
    ],
)
def test_session_closed_and_no_partial_files_on_failure(tmp_path: Path, job_key: str, fail_stage: str) -> None:
    cls = TDCArchiveConnector if job_key.startswith("tdc_") else ArasArchiveConnector
    connector, auth_inst, _ = make_harness(
        tmp_path,
        cls,
        login_exc=RuntimeError("Login error") if fail_stage == "login" else None,
        crawl_exc=RuntimeError("Crawl fail") if fail_stage == "crawl" else None,
        export_exc=RuntimeError("Export fail") if fail_stage == "export" else None,
        download_exc=RuntimeError("Download fail") if fail_stage == "download" else None,
    )
    context = make_context(job_key, output_subdir="failure_run", run_id=999)
    credential, _, _ = random_credential()

    with pytest.raises(RuntimeError):
        connector.collect(context, credential)

    if fail_stage != "login":
        assert auth_inst[0].session.closed == 1
    assert not any(p.is_file() for p in tmp_path.rglob("*"))


def test_credentials_and_raw_ncr_xml_never_enter_artifacts_or_content(tmp_path: Path) -> None:
    tdc, _, _ = make_harness(tmp_path, TDCArchiveConnector)
    aras, _, _ = make_harness(tmp_path, ArasArchiveConnector)
    credential, user_sentinel, pwd_sentinel = random_credential()

    collections = [
        tdc.collect(make_context("tdc_data_model", source_type="tdc", report_type="data_model", output_subdir="s1", run_id=1), credential),
        aras.collect(make_context("aras_ewo", source_type="aras", report_type="ewo", output_subdir="s2", run_id=2), credential),
        aras.collect(make_context("aras_ncr_progress", source_type="aras", report_type="ncr_progress", output_subdir="s3", run_id=3), credential),
        aras.collect(make_context("aras_ncr_detail", source_type="aras", report_type="ncr_detail", output_subdir="s4", run_id=4), credential),
    ]

    secrets_to_check = [user_sentinel, pwd_sentinel, "<raw_secret_progress_xml/>", "<raw_secret_detail_xml/>"]

    for col in collections:
        for art in col.artifacts:
            meta = art.as_metadata()
            for secret in secrets_to_check:
                assert secret not in art.relative_path
                assert secret not in art.display_name
                assert secret not in str(meta)

    for file_path in tmp_path.rglob("*"):
        if file_path.is_file():
            content = file_path.read_bytes()
            for secret in secrets_to_check:
                assert secret.encode("utf-8") not in content
                assert secret not in file_path.name


# ── TDC 数模设计审核流程的表单快照行（form_rows） ────────────────────────────


def _tdc_export_values() -> list[str]:
    """构造一行合成的 47 列官方导出数据（全部为虚构值，按合同表头展开）。"""
    labeled = {
        "实例号": "90000101",
        "流程名": "T2发布-组件A",
        "流水单号": "F999X-3D-0001",
        "发布属性": "T2发布",
        "申请人": "测试员甲",
        "部门": "内饰科",
        "申请日期": "2026-08-20 10:00:00",
        "项目/车型": "F999X",
        "零件号": "27000001",
        "数模号": "27000001",
        "零件名称": "组件A",
        "数量": "1",
        "重量（单件）": "0.8",
        "零件合计": "0.8",
        "版本号": "001.0001",
        "对应IA号": "IA000001",
        "EWO/SOR号": "EWO-000001",
        "应签人数": "13",
        "已签人数": "13",
        "未签人数": "0",
        "签署率": "100.00%",
        "状态": "审批中",
    }
    headers = report_contracts()["tdc_data_model"]["headerRows"][0]
    return [str(labeled.get(str(header), "")) for header in headers]


def _write_official_data_model_values_xlsx(
    path: Path,
    rows: Sequence[Sequence[object]],
) -> None:
    """按 tdc_data_model 合同表头写一本可读的官方导出工作簿。"""
    headers = report_contracts()["tdc_data_model"]["headerRows"][0]

    def row_xml(row_number: int, values: Sequence[object]) -> str:
        cells = "".join(
            f'<c r="{_cell_ref(index, row_number)}" t="inlineStr">'
            f"<is><t>{escape(str(value))}</t></is></c>"
            for index, value in enumerate(values, 1)
        )
        return f'<row r="{row_number}">{cells}</row>'

    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        + row_xml(1, headers)
        + "".join(row_xml(number, values) for number, values in enumerate(rows, 2))
        + "</sheetData></worksheet>"
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


class OfficialExportTDCCrawler(FakeTDCCrawler):
    """TDC 测试替身：官方导出产出可读的合同工作簿。"""

    def __init__(self, *, export_values: Sequence[str], **kw: Any) -> None:
        super().__init__(**kw)
        self.export_values = list(export_values)

    def export_data_model(self, filters: Any) -> Any:
        self.last_export_filters = filters
        assert self.output_dir is not None
        path = self.output_dir / "tdc_data_model.xlsx"
        _write_official_data_model_values_xlsx(path, [self.export_values])
        return SimpleNamespace(
            path=path,
            file_name="tdc_data_model.xlsx",
            byte_count=path.stat().st_size,
        )


def make_tdc_harness(
    tmp_path: Path,
    crawler_cls: type,
    **crawler_kwargs: Any,
) -> tuple[TDCArchiveConnector, list[Any]]:
    """Build a TDC connector whose crawler instances accept injected rows."""
    crawlers: list[Any] = []

    def crawler_factory(**kw: Any) -> Any:
        inst = crawler_cls(**kw, **crawler_kwargs)
        crawlers.append(inst)
        return inst

    connector = TDCArchiveConnector(
        make_store(tmp_path),
        auth_factory=FakeAuthClient,
        crawler_factory=crawler_factory,
    )
    return connector, crawlers


def test_tdc_official_export_collection_exposes_contract_form_rows(
    tmp_path: Path,
) -> None:
    """官方导出可读时 form_rows 必须等于按合同表头展开的行字典。"""
    export_values = _tdc_export_values()
    connector, crawlers = make_tdc_harness(
        tmp_path,
        OfficialExportTDCCrawler,
        export_values=export_values,
    )
    context = make_context(
        "tdc_data_model",
        source_type="tdc",
        report_type="data_model",
        output_subdir="tdc_official",
        run_id=61,
    )

    collection = connector.collect(context, random_credential()[0])

    headers = report_contracts()["tdc_data_model"]["headerRows"][0]
    assert collection.record_count == 1
    assert collection.form_rows == (
        {str(header): value for header, value in zip(headers, export_values)},
    )
    assert len(collection.artifacts) == 3
    # 官方工作簿可用时不得再退回爬取列表。
    assert crawlers[0].last_crawl_filters is None
    assert crawlers[0].last_export_filters is not None


def test_tdc_crawl_fallback_collection_exposes_crawl_form_rows(
    tmp_path: Path,
) -> None:
    """官方工作簿不可读时回退爬取列表，form_rows 等于爬取字典行。"""
    crawl_rows = (
        {
            "incident": "90000201",
            "documentNo": "F888Y-3D-0002",
            "requestDate": "2026-08-30 09:30:00",
            "projectModel": "F888Y",
            "department": "车身科",
            "publishProperty": "T2发布",
            "status": "审批中",
        },
    )
    connector, crawlers = make_tdc_harness(
        tmp_path,
        FakeTDCCrawler,
        rows=crawl_rows,
    )
    context = make_context(
        "tdc_data_model",
        source_type="tdc",
        report_type="data_model",
        output_subdir="tdc_fallback",
        run_id=62,
    )

    collection = connector.collect(context, random_credential()[0])

    assert collection.record_count == len(crawl_rows)
    assert collection.form_rows == crawl_rows
    assert len(collection.artifacts) == 3
    # 官方工作簿不可读时必须已执行爬取回退。
    assert crawlers[0].last_crawl_filters is not None


def test_tdc_truncated_crawl_fallback_is_exposed_on_collection(tmp_path: Path) -> None:
    connector, _ = make_tdc_harness(
        tmp_path,
        TruncatedFallbackTDCCrawler,
    )

    collection = connector.collect(
        make_context(
            "tdc_data_model",
            source_type="tdc",
            report_type="data_model",
            output_subdir="tdc_fallback_truncated",
            run_id=64,
        ),
        random_credential()[0],
    )

    assert collection.form_projection_error == "api_result_truncated"
    assert collection.form_rows is None
