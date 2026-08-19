# -*- coding: utf-8 -*-
"""Offline-testable HTTP client for the TDC report pages."""

from __future__ import annotations

import json
import logging
import math
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import unquote, urljoin, urlsplit

from core.redaction import redact_sensitive_text
from core.runtime_paths import app_root

try:
    import requests
except ModuleNotFoundError:  # pragma: no cover - only for minimal environments
    requests = None  # type: ignore[assignment]


logger = logging.getLogger("vse_toolbox.tdc_crawler")

DEFAULT_TDC_BASE_URL = "https://tdc.sgmw.com.cn"
DEFAULT_TDC_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

DATA_MODEL_PAGE_PATH = "/tpc/dataAdmin/dataModelDesign/index"
DATA_MODEL_LIST_PATH = "/uwf/procuwfpe3ddigitalmodeldesignreview/list"
DATA_MODEL_EXPORT_PATH = "/uwf/procuwfpe3ddigitalmodeldesignreview/export"
SOR_PAGE_PATH = "/tpc/dataAdmin/intelligent/sor/index"
SOR_PROJECT_LIST_PATH = "/sp/carTypeProject/list"
SOR_LIST_PATH = "/sp/sor/sorPage"
SOR_EXPORT_PATH = "/sp/sor/export"
AFACE_PAGE_PATH = "/tpc/dataAdmin/intelligent/ots2/index"

AFACE_CONTRACT_BLOCKER = (
    "待 HAR 验证：本地材料仅确认页面路径 "
    f"{AFACE_PAGE_PATH} 和结果工作簿结构；未包含该页的网络请求，"
    "因此 list/export 路径、HTTP method、分页字段及筛选参数均未确认。"
)

_SAFE_REQUEST_HEADERS = {
    "accept",
    "accept-language",
    "content-type",
    "origin",
    "referer",
    "user-agent",
}
_REDACTED_HEADERS = {"authorization", "cookie", "set-cookie"}
_PERSON_QUERY_KEYS = {"applicant", "startusername", "applicanttel", "phone", "tel"}
_PATH_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ENUM_RE = re.compile(r"^[\w\u3400-\u9fff .()/+-]{1,128}$", re.UNICODE)


class TDCCrawlerError(RuntimeError):
    """Raised when a TDC request or response cannot be used safely."""

    def __init__(
        self,
        message: str,
        *,
        stage: str | None = None,
        request_id: str | None = None,
        status_code: int | None = None,
        completed_pages: int = 0,
    ) -> None:
        super().__init__(redact_sensitive_text(message))
        self.stage = stage
        self.request_id = request_id
        self.status_code = status_code
        self.completed_pages = completed_pages


@dataclass(frozen=True)
class TDCHttpDiagnosticEvent:
    timestamp: str
    stage: str
    request_id: str
    page_type: str
    method: str = "GET"
    origin: str = ""
    path: str = ""
    query: Mapping[str, Any] = field(default_factory=dict)
    page: int | None = None
    page_size: int | None = None
    attempt: int = 1
    timeout: float | None = None
    status_code: int | None = None
    elapsed_ms: float | None = None
    content_type: str | None = None
    content_length: int | None = None
    json_fields: tuple[str, ...] = ()
    record_count: int | None = None
    total: int | None = None
    pages: int | None = None
    request_headers: Mapping[str, str] = field(default_factory=dict)
    response_headers: Mapping[str, str] = field(default_factory=dict)
    accumulated_count: int | None = None
    unique_count: int | None = None
    duplicate_count: int | None = None
    current_page: int | None = None
    estimated_pages: int | None = None
    stop_reason: str | None = None
    file_name: str | None = None
    saved_path: str | None = None
    bytes_written: int | None = None
    validation: str | None = None
    exception_type: str | None = None
    reason: str | None = None
    completed_pages: int | None = None


@dataclass(frozen=True)
class TDCDataModelFilters:
    serial_number: str | None = None
    applicant: str | None = None
    department: str | None = None
    section: str | None = None
    application_start: str | None = None
    application_end: str | None = None
    project_model: str | None = None
    part_number: str | None = None
    model_number: str | None = None

    def to_params(self) -> dict[str, str]:
        _validate_date_range(self.application_start, self.application_end, "application date")
        return _compact_params(
            {
                "incident": self.serial_number,
                "applicant": self.applicant,
                "superDepartment": self.department,
                "department": self.section,
                "requestDateStart": self.application_start,
                "requestDateEnd": self.application_end,
                "projectModel": self.project_model,
                "partNumber": self.part_number,
                "modelNumber": self.model_number,
            }
        )


@dataclass(frozen=True)
class TDCSORFilters:
    serial_number: str | None = None
    process_type: str | None = None
    car_type_project: str | None = None
    applicant: str | None = None
    title: str | None = None
    department: str | None = None
    section: str | None = None
    application_start: str | None = None
    application_end: str | None = None
    part_number: str | None = None
    part_name: str | None = None
    version: str | None = None
    sor_number: str | None = None
    latest_completed_node: str | None = None
    approval_status: str | None = None

    def to_params(self) -> dict[str, str]:
        _validate_date_range(self.application_start, self.application_end, "application date")
        _validate_enum(self.process_type, "process_type")
        _validate_enum(self.latest_completed_node, "latest_completed_node")
        _validate_enum(self.approval_status, "approval_status")
        params = _compact_params(
            {
                "processNo": self.serial_number,
                "bizName": self.process_type,
                "carTypeProject": self.car_type_project,
                "startUserName": self.applicant,
                "title": self.title,
                "deptName": self.department,
                "sectionName": self.section,
                "startTimeBegin": self.application_start,
                "startTimeEnd": self.application_end,
                "sorPartNo": self.part_number,
                "sorPartName": self.part_name,
                "version": self.version,
                "sorNo": self.sor_number,
                "latestCompletedNode": self.latest_completed_node,
                "processInstanceStatus": self.approval_status,
            }
        )
        # The captured TDC request sends both fields for the same project selector.
        if "carTypeProject" in params:
            params["carTypeProjectAll[0]"] = params["carTypeProject"]
        return params


@dataclass(frozen=True)
class TDCAFaceFilters:
    """Independent contract placeholder; filter names require a page-specific HAR."""

    def to_params(self) -> dict[str, str]:
        return {}


@dataclass(frozen=True)
class TDCPagedResult:
    report_type: str
    rows: list[dict[str, Any]]
    page: int
    page_size: int
    total: int | None
    pages: int | None
    fetched_pages: int
    unique_count: int
    duplicate_count: int
    stop_reason: str
    record_granularity: str


@dataclass(frozen=True)
class TDCExportResult:
    report_type: str
    file_name: str
    path: Path
    byte_count: int
    content_type: str
    signature_valid: bool
    elapsed_ms: float
    record_granularity: str


class TDCCrawlerClient:
    def __init__(
        self,
        base_url: str = DEFAULT_TDC_BASE_URL,
        session: Any | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
        diagnostic_hook: Callable[[TDCHttpDiagnosticEvent], None] | None = None,
        output_dir: Path | None = None,
    ) -> None:
        self.base_url = _normalize_base_url(base_url)
        self.timeout = _validate_timeout(timeout)
        if session is None:
            if requests is None:
                raise ImportError("TDCCrawlerClient requires requests; install requirements.txt")
            session = requests.Session()
            session.trust_env = False
        self.session = session
        self.headers = {str(key): str(value) for key, value in (headers or {}).items()}
        self.diagnostic_hook = diagnostic_hook
        self.output_dir = output_dir or (app_root() / "data" / "tdc")

    def query_data_model_page(
        self,
        filters: TDCDataModelFilters | None = None,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> TDCPagedResult:
        return self._query_page(
            report_type="data_model",
            route=DATA_MODEL_LIST_PATH,
            referer_path=DATA_MODEL_PAGE_PATH,
            filter_params=(filters or TDCDataModelFilters()).to_params(),
            page=page,
            page_size=page_size,
            record_granularity="workflow",
        )

    def crawl_data_model_all(
        self,
        filters: TDCDataModelFilters | None = None,
        *,
        page_size: int = 50,
        max_pages: int = 100,
        max_records: int = 10000,
    ) -> TDCPagedResult:
        return self._crawl_all(
            report_type="data_model",
            query=self.query_data_model_page,
            filters=filters or TDCDataModelFilters(),
            page_size=page_size,
            max_pages=max_pages,
            max_records=max_records,
            record_granularity="workflow",
        )

    def export_data_model(
        self,
        filters: TDCDataModelFilters | None = None,
        *,
        file_name: str | None = None,
    ) -> TDCExportResult:
        params = (filters or TDCDataModelFilters()).to_params()
        params["pagePath"] = self._url(DATA_MODEL_PAGE_PATH)
        return self._export(
            report_type="data_model",
            route=DATA_MODEL_EXPORT_PATH,
            referer_path=DATA_MODEL_PAGE_PATH,
            params=params,
            file_name=file_name,
            default_name="tdc_data_model.xlsx",
            record_granularity="workflow",
        )

    def list_car_type_projects(self) -> list[dict[str, Any]]:
        result = self._request_json(
            report_type="sor_projects",
            route=SOR_PROJECT_LIST_PATH,
            referer_path=SOR_PAGE_PATH,
            params={},
            page=None,
            page_size=None,
        )
        data = result[0].get("data", [])
        if not isinstance(data, list) or any(not isinstance(item, Mapping) for item in data):
            raise TDCCrawlerError("TDC car type project response does not contain a list", stage="parse-json")
        return [dict(item) for item in data]

    def query_sor_page(
        self,
        filters: TDCSORFilters | None = None,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> TDCPagedResult:
        return self._query_page(
            report_type="sor",
            route=SOR_LIST_PATH,
            referer_path=SOR_PAGE_PATH,
            filter_params=(filters or TDCSORFilters()).to_params(),
            page=page,
            page_size=page_size,
            record_granularity="workflow",
        )

    def crawl_sor_all(
        self,
        filters: TDCSORFilters | None = None,
        *,
        page_size: int = 50,
        max_pages: int = 100,
        max_records: int = 10000,
    ) -> TDCPagedResult:
        return self._crawl_all(
            report_type="sor",
            query=self.query_sor_page,
            filters=filters or TDCSORFilters(),
            page_size=page_size,
            max_pages=max_pages,
            max_records=max_records,
            record_granularity="workflow",
        )

    def export_sor(
        self,
        filters: TDCSORFilters | None = None,
        *,
        file_name: str | None = None,
    ) -> TDCExportResult:
        params = (filters or TDCSORFilters()).to_params()
        params["pagePath"] = self._url(SOR_PAGE_PATH)
        return self._export(
            report_type="sor",
            route=SOR_EXPORT_PATH,
            referer_path=SOR_PAGE_PATH,
            params=params,
            file_name=file_name,
            default_name="tdc_sor_part_details.xlsx",
            record_granularity="part_detail",
        )

    def query_a_face_page(
        self,
        filters: TDCAFaceFilters | None = None,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> TDCPagedResult:
        del filters
        _validate_pagination(page=page, page_size=page_size)
        raise TDCCrawlerError(AFACE_CONTRACT_BLOCKER, stage="contract-validation")

    def crawl_a_face_all(
        self,
        filters: TDCAFaceFilters | None = None,
        *,
        page_size: int = 50,
        max_pages: int = 100,
        max_records: int = 10000,
    ) -> TDCPagedResult:
        del filters
        _validate_limits(page_size=page_size, max_pages=max_pages, max_records=max_records)
        raise TDCCrawlerError(AFACE_CONTRACT_BLOCKER, stage="contract-validation")

    def export_a_face(
        self,
        filters: TDCAFaceFilters | None = None,
        *,
        file_name: str | None = None,
    ) -> TDCExportResult:
        del filters, file_name
        raise TDCCrawlerError(AFACE_CONTRACT_BLOCKER, stage="contract-validation")

    # Friendly aliases for callers that spell A-face without the separator.
    query_data_model_report = query_data_model_page
    crawl_data_model_report_all = crawl_data_model_all
    export_data_model_report = export_data_model
    query_sor_report = query_sor_page
    crawl_sor_report_all = crawl_sor_all
    export_sor_report = export_sor
    query_aface_page = query_a_face_page
    crawl_aface_all = crawl_a_face_all
    export_aface = export_a_face

    def _query_page(
        self,
        *,
        report_type: str,
        route: str,
        referer_path: str,
        filter_params: Mapping[str, str],
        page: int,
        page_size: int,
        record_granularity: str,
    ) -> TDCPagedResult:
        _validate_pagination(page=page, page_size=page_size)
        params: dict[str, Any] = dict(filter_params)
        params.update({"current": page, "size": page_size})
        payload, request_id = self._request_json(
            report_type=report_type,
            route=route,
            referer_path=referer_path,
            params=params,
            page=page,
            page_size=page_size,
        )
        data = payload.get("data", payload)
        if not isinstance(data, Mapping):
            raise TDCCrawlerError(
                "TDC JSON response data is not an object",
                stage="parse-json",
                request_id=request_id,
            )
        raw_rows = data.get("records", [])
        if not isinstance(raw_rows, list) or any(not isinstance(item, Mapping) for item in raw_rows):
            raise TDCCrawlerError(
                "TDC JSON response records is not a list of objects",
                stage="parse-json",
                request_id=request_id,
            )
        rows = [dict(item) for item in raw_rows]
        current = _optional_int(data.get("current"), page)
        size = _optional_int(data.get("size"), page_size)
        total = _optional_int(data.get("total"))
        pages = _optional_int(data.get("pages"))
        return TDCPagedResult(
            report_type=report_type,
            rows=rows,
            page=current or page,
            page_size=size or page_size,
            total=total,
            pages=pages,
            fetched_pages=1,
            unique_count=len(rows),
            duplicate_count=0,
            stop_reason="single_page",
            record_granularity=record_granularity,
        )

    def _crawl_all(
        self,
        *,
        report_type: str,
        query: Callable[..., TDCPagedResult],
        filters: Any,
        page_size: int,
        max_pages: int,
        max_records: int,
        record_granularity: str,
    ) -> TDCPagedResult:
        _validate_limits(page_size=page_size, max_pages=max_pages, max_records=max_records)
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        duplicates = 0
        fetched_pages = 0
        reported_total: int | None = None
        reported_pages: int | None = None
        accumulated_count = 0
        stop_reason = "max_pages"

        for page in range(1, max_pages + 1):
            try:
                result = query(filters, page=page, page_size=page_size)
            except TDCCrawlerError as exc:
                exc.completed_pages = fetched_pages
                self._emit_failure_event(report_type, exc, fetched_pages)
                raise
            fetched_pages += 1
            accumulated_count += len(result.rows)
            reported_total = result.total if result.total is not None else reported_total
            reported_pages = result.pages if result.pages is not None else reported_pages
            added = 0
            for row in result.rows:
                identity = _row_identity(report_type, row)
                if identity in seen:
                    duplicates += 1
                    continue
                seen.add(identity)
                if len(rows) >= max_records:
                    break
                rows.append(row)
                added += 1

            if len(rows) >= max_records:
                stop_reason = "max_records"
            elif not result.rows:
                stop_reason = "empty_page"
            elif reported_pages is not None and page >= reported_pages:
                stop_reason = "reported_pages"
            elif len(result.rows) < page_size:
                stop_reason = "short_page"
            elif page >= max_pages:
                stop_reason = "max_pages"
            else:
                stop_reason = "continue"

            self._emit(
                TDCHttpDiagnosticEvent(
                    timestamp=_timestamp(),
                    stage="pagination",
                    request_id=_request_id(),
                    page_type=report_type,
                    page=page,
                    page_size=page_size,
                    current_page=page,
                    accumulated_count=accumulated_count,
                    unique_count=len(rows),
                    duplicate_count=duplicates,
                    record_count=added,
                    total=reported_total,
                    pages=reported_pages,
                    estimated_pages=reported_pages
                    or (math.ceil(reported_total / page_size) if reported_total is not None else None),
                    stop_reason=stop_reason,
                    completed_pages=fetched_pages,
                )
            )
            if stop_reason != "continue":
                break

        return TDCPagedResult(
            report_type=report_type,
            rows=rows,
            page=fetched_pages,
            page_size=page_size,
            total=reported_total,
            pages=reported_pages,
            fetched_pages=fetched_pages,
            unique_count=len(rows),
            duplicate_count=duplicates,
            stop_reason=stop_reason,
            record_granularity=record_granularity,
        )

    def _request_json(
        self,
        *,
        report_type: str,
        route: str,
        referer_path: str,
        params: Mapping[str, Any],
        page: int | None,
        page_size: int | None,
    ) -> tuple[dict[str, Any], str]:
        request_id = _request_id()
        url = self._url(route)
        headers = self._headers(referer_path, "application/json, text/plain, */*")
        started = time.perf_counter()
        try:
            response = self.session.get(url, params=dict(params), headers=headers, timeout=self.timeout)
        except Exception as exc:
            elapsed = _elapsed_ms(started)
            event = self._exception_event(
                report_type, "request", request_id, route, params, headers, page, page_size, elapsed, exc
            )
            self._emit(event)
            raise TDCCrawlerError(
                f"TDC request failed: {type(exc).__name__}: {redact_sensitive_text(exc)}",
                stage="request",
                request_id=request_id,
            ) from exc

        elapsed = _elapsed_ms(started)
        status = int(getattr(response, "status_code", 0) or 0)
        content_type = _header_value(getattr(response, "headers", {}), "Content-Type")
        content_length = _content_length(response)
        base_event: dict[str, Any] = dict(
            timestamp=_timestamp(),
            stage="response",
            request_id=request_id,
            page_type=report_type,
            method="GET",
            origin=self._origin(),
            path=route,
            query=_safe_query(params),
            page=page,
            page_size=page_size,
            attempt=1,
            timeout=self.timeout,
            status_code=status,
            elapsed_ms=elapsed,
            content_type=content_type,
            content_length=content_length,
            request_headers=_safe_headers(headers),
            response_headers=_safe_headers(getattr(response, "headers", {})),
        )
        if status < 200 or status >= 300:
            self._emit(TDCHttpDiagnosticEvent(**base_event, reason=f"HTTP {status}"))
            raise TDCCrawlerError(
                f"TDC HTTP {status} at {route}",
                stage="status-validation",
                request_id=request_id,
                status_code=status,
            )
        if _looks_like_html(response, content_type):
            self._emit(TDCHttpDiagnosticEvent(**base_event, validation="rejected-login-html"))
            raise TDCCrawlerError(
                "TDC response looks like a login HTML page, not JSON; refresh browser headers and Cookie/Authorization",
                stage="content-validation",
                request_id=request_id,
                status_code=status,
            )
        if not _is_json_content_type(content_type):
            self._emit(TDCHttpDiagnosticEvent(**base_event, validation="rejected-content-type"))
            raise TDCCrawlerError(
                f"TDC JSON endpoint returned unsupported Content-Type: {content_type or '<missing>'}",
                stage="content-validation",
                request_id=request_id,
                status_code=status,
            )
        try:
            payload = response.json() if callable(getattr(response, "json", None)) else json.loads(response.text)
        except Exception as exc:
            self._emit(
                TDCHttpDiagnosticEvent(
                    **base_event,
                    validation="invalid-json",
                    exception_type=type(exc).__name__,
                )
            )
            raise TDCCrawlerError(
                "TDC response is not valid JSON",
                stage="parse-json",
                request_id=request_id,
                status_code=status,
            ) from exc
        if not isinstance(payload, dict):
            self._emit(TDCHttpDiagnosticEvent(**base_event, validation="json-not-object"))
            raise TDCCrawlerError(
                "TDC JSON response is not an object",
                stage="parse-json",
                request_id=request_id,
                status_code=status,
            )
        api_code = payload.get("code")
        if api_code not in (None, 0, 200, "0", "200"):
            reason = redact_sensitive_text(payload.get("msg", "TDC API rejected the request"), limit=240)
            self._emit(TDCHttpDiagnosticEvent(**base_event, validation="api-error", reason=reason))
            raise TDCCrawlerError(
                f"TDC API error code {api_code}: {reason}",
                stage="api-validation",
                request_id=request_id,
                status_code=status,
            )
        data = payload.get("data")
        summary = data if isinstance(data, Mapping) else {}
        records = summary.get("records") if isinstance(summary, Mapping) else None
        self._emit(
            TDCHttpDiagnosticEvent(
                **base_event,
                validation="json-ok",
                json_fields=tuple(sorted(str(key) for key in payload.keys())),
                record_count=len(records) if isinstance(records, list) else (len(data) if isinstance(data, list) else None),
                total=_optional_int(summary.get("total")),
                pages=_optional_int(summary.get("pages")),
            )
        )
        return payload, request_id

    def _export(
        self,
        *,
        report_type: str,
        route: str,
        referer_path: str,
        params: Mapping[str, Any],
        file_name: str | None,
        default_name: str,
        record_granularity: str,
    ) -> TDCExportResult:
        request_id = _request_id()
        url = self._url(route)
        headers = self._headers(
            referer_path,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/octet-stream;q=0.9,*/*;q=0.8",
        )
        started = time.perf_counter()
        try:
            response = self.session.get(url, params=dict(params), headers=headers, timeout=self.timeout)
        except Exception as exc:
            elapsed = _elapsed_ms(started)
            self._emit(
                self._exception_event(
                    report_type, "export", request_id, route, params, headers, None, None, elapsed, exc
                )
            )
            raise TDCCrawlerError(
                f"TDC export failed: {type(exc).__name__}: {redact_sensitive_text(exc)}",
                stage="export",
                request_id=request_id,
            ) from exc

        elapsed = _elapsed_ms(started)
        status = int(getattr(response, "status_code", 0) or 0)
        content_type = _header_value(getattr(response, "headers", {}), "Content-Type")
        content = _response_bytes(response)
        event_args: dict[str, Any] = dict(
            timestamp=_timestamp(),
            stage="export",
            request_id=request_id,
            page_type=report_type,
            method="GET",
            origin=self._origin(),
            path=route,
            query=_safe_query(params),
            timeout=self.timeout,
            status_code=status,
            elapsed_ms=elapsed,
            content_type=content_type,
            content_length=len(content),
            request_headers=_safe_headers(headers),
            response_headers=_safe_headers(getattr(response, "headers", {})),
        )
        if status < 200 or status >= 300:
            self._emit(TDCHttpDiagnosticEvent(**event_args, reason=f"HTTP {status}"))
            raise TDCCrawlerError(
                f"TDC export HTTP {status} at {route}",
                stage="status-validation",
                request_id=request_id,
                status_code=status,
            )
        if _looks_like_html(response, content_type):
            self._emit(TDCHttpDiagnosticEvent(**event_args, validation="rejected-login-html"))
            raise TDCCrawlerError(
                "TDC export returned a login HTML page, not an XLSX file",
                stage="export-validation",
                request_id=request_id,
                status_code=status,
            )
        if not _is_xlsx_content_type(content_type):
            self._emit(TDCHttpDiagnosticEvent(**event_args, validation="rejected-content-type"))
            raise TDCCrawlerError(
                f"TDC export returned unsupported Content-Type: {content_type or '<missing>'}",
                stage="export-validation",
                request_id=request_id,
                status_code=status,
            )
        if not content.startswith(b"PK"):
            self._emit(TDCHttpDiagnosticEvent(**event_args, validation="rejected-xlsx-signature"))
            raise TDCCrawlerError(
                "TDC export failed XLSX ZIP signature validation",
                stage="export-validation",
                request_id=request_id,
                status_code=status,
            )

        header_name = _content_disposition_filename(
            _header_value(getattr(response, "headers", {}), "Content-Disposition")
        )
        safe_name = _safe_filename(file_name or header_name or default_name)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = (self.output_dir / safe_name).resolve()
        path.write_bytes(content)
        self._emit(
            TDCHttpDiagnosticEvent(
                **event_args,
                file_name=safe_name,
                saved_path=str(path),
                bytes_written=len(content),
                validation="content-type+xlsx-pk-ok",
            )
        )
        return TDCExportResult(
            report_type=report_type,
            file_name=safe_name,
            path=path,
            byte_count=len(content),
            content_type=content_type,
            signature_valid=True,
            elapsed_ms=elapsed,
            record_granularity=record_granularity,
        )

    def _headers(self, referer_path: str, accept: str) -> dict[str, str]:
        headers = {
            "Accept": accept,
            "Accept-Language": "zh-CN,zh;q=0.9",
            "User-Agent": DEFAULT_TDC_USER_AGENT,
            "Referer": self._url(referer_path),
        }
        headers.update(self.headers)
        return headers

    def _url(self, route: str) -> str:
        return urljoin(self.base_url, route.lstrip("/"))

    def _origin(self) -> str:
        parsed = urlsplit(self.base_url)
        return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else self.base_url.rstrip("/")

    def _emit(self, event: TDCHttpDiagnosticEvent) -> None:
        logger.debug(
            "stage=%s request_id=%s page_type=%s path=%s status=%s records=%s stop=%s reason=%s",
            event.stage,
            event.request_id,
            event.page_type,
            event.path,
            event.status_code,
            event.record_count,
            event.stop_reason,
            redact_sensitive_text(event.reason or "", limit=240, collapse_newlines=True),
        )
        if self.diagnostic_hook is None:
            return
        try:
            self.diagnostic_hook(event)
        except Exception as exc:  # diagnostics must never break a report request
            logger.warning("TDC diagnostic hook failed: %s", type(exc).__name__)

    def _exception_event(
        self,
        report_type: str,
        stage: str,
        request_id: str,
        route: str,
        params: Mapping[str, Any],
        headers: Mapping[str, str],
        page: int | None,
        page_size: int | None,
        elapsed_ms: float,
        exc: Exception,
    ) -> TDCHttpDiagnosticEvent:
        return TDCHttpDiagnosticEvent(
            timestamp=_timestamp(),
            stage=stage,
            request_id=request_id,
            page_type=report_type,
            method="GET",
            origin=self._origin(),
            path=route,
            query=_safe_query(params),
            page=page,
            page_size=page_size,
            timeout=self.timeout,
            elapsed_ms=elapsed_ms,
            request_headers=_safe_headers(headers),
            exception_type=type(exc).__name__,
            reason=redact_sensitive_text(exc, limit=240, collapse_newlines=True),
        )

    def _emit_failure_event(self, report_type: str, exc: TDCCrawlerError, completed_pages: int) -> None:
        self._emit(
            TDCHttpDiagnosticEvent(
                timestamp=_timestamp(),
                stage=exc.stage or "crawl",
                request_id=exc.request_id or _request_id(),
                page_type=report_type,
                status_code=exc.status_code,
                exception_type=type(exc).__name__,
                reason=redact_sensitive_text(exc, limit=240, collapse_newlines=True),
                completed_pages=completed_pages,
            )
        )


def combine_diagnostic_hooks(
    *hooks: Callable[[TDCHttpDiagnosticEvent], None] | None,
) -> Callable[[TDCHttpDiagnosticEvent], None] | None:
    active = tuple(hook for hook in hooks if hook is not None)
    if not active:
        return None

    def combined(event: TDCHttpDiagnosticEvent) -> None:
        for hook in active:
            hook(event)

    return combined


def _compact_params(values: Mapping[str, Any]) -> dict[str, str]:
    compact: dict[str, str] = {}
    for key, value in values.items():
        if value is None:
            continue
        text = str(value).strip()
        if text:
            compact[key] = text
    return compact


def _validate_date_range(start: str | None, end: str | None, label: str) -> None:
    start_date = _parse_date(start, f"{label} start")
    end_date = _parse_date(end, f"{label} end")
    if start_date and end_date and start_date > end_date:
        raise ValueError(f"{label} start must not be after end")


def _parse_date(value: str | None, label: str) -> date | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    if not _DATE_RE.fullmatch(text):
        raise ValueError(f"{label} must use YYYY-MM-DD")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{label} is not a valid calendar date") from exc


def _validate_enum(value: str | None, label: str) -> None:
    if value is None or not str(value).strip():
        return
    if not isinstance(value, str) or not _ENUM_RE.fullmatch(value.strip()):
        raise ValueError(f"{label} is not a valid TDC enum label")


def _validate_pagination(*, page: int, page_size: int) -> None:
    _validate_positive_int(page, "page", maximum=1_000_000)
    _validate_positive_int(page_size, "page_size", maximum=1000)


def _validate_limits(*, page_size: int, max_pages: int, max_records: int) -> None:
    _validate_positive_int(page_size, "page_size", maximum=1000)
    _validate_positive_int(max_pages, "max_pages", maximum=10000)
    _validate_positive_int(max_records, "max_records", maximum=1_000_000)


def _validate_positive_int(value: int, label: str, *, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > maximum:
        raise ValueError(f"{label} must be an integer between 1 and {maximum}")


def _validate_timeout(value: float) -> float:
    if isinstance(value, bool):
        raise ValueError("timeout must be positive")
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout must be positive") from exc
    if not math.isfinite(timeout) or timeout <= 0 or timeout > 600:
        raise ValueError("timeout must be between 0 and 600 seconds")
    return timeout


def _optional_int(value: Any, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_base_url(base_url: str) -> str:
    value = str(base_url).strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base_url must be an absolute HTTP(S) URL")
    return f"{parsed.scheme}://{parsed.netloc}/"


def _header_value(headers: Any, name: str) -> str:
    if not isinstance(headers, Mapping):
        return ""
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            return str(value)
    return ""


def _safe_headers(headers: Any) -> dict[str, str]:
    if not isinstance(headers, Mapping):
        return {}
    safe: dict[str, str] = {}
    for key, value in headers.items():
        lowered = str(key).lower()
        if lowered in _REDACTED_HEADERS:
            safe[str(key)] = "[redacted]"
        elif lowered in _SAFE_REQUEST_HEADERS:
            safe[str(key)] = redact_sensitive_text(value, limit=500, collapse_newlines=True)
    return safe


def _safe_query(params: Mapping[str, Any]) -> dict[str, str]:
    safe: dict[str, str] = {}
    for key, value in params.items():
        lowered = str(key).lower()
        if lowered in _PERSON_QUERY_KEYS or any(part in lowered for part in ("token", "cookie", "authorization", "secret")):
            safe[str(key)] = "[redacted]"
        else:
            safe[str(key)] = redact_sensitive_text(value, limit=240, collapse_newlines=True)
    return safe


def _response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    content = getattr(response, "content", b"")
    if isinstance(content, bytes):
        return content[:512].decode("utf-8", errors="ignore")
    return ""


def _response_bytes(response: Any) -> bytes:
    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        return content
    text = getattr(response, "text", "")
    return str(text).encode("utf-8")


def _content_length(response: Any) -> int:
    header = _header_value(getattr(response, "headers", {}), "Content-Length")
    if header.isdigit():
        return int(header)
    return len(_response_bytes(response))


def _looks_like_html(response: Any, content_type: str) -> bool:
    prefix = _response_text(response).lstrip().lower()[:100]
    return "text/html" in content_type.lower() or prefix.startswith(("<!doctype html", "<html", "<head", "<body"))


def _is_json_content_type(content_type: str) -> bool:
    lowered = content_type.lower().split(";", 1)[0].strip()
    return lowered == "application/json" or lowered.endswith("+json")


def _is_xlsx_content_type(content_type: str) -> bool:
    lowered = content_type.lower().split(";", 1)[0].strip()
    return lowered in {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
        "application/zip",
    }


def _content_disposition_filename(value: str) -> str | None:
    if not value:
        return None
    encoded = re.search(r"(?i)filename\*\s*=\s*UTF-8''([^;]+)", value)
    if encoded:
        return unquote(encoded.group(1).strip().strip('"'))
    plain = re.search(r"(?i)filename\s*=\s*(?:\"([^\"]+)\"|([^;]+))", value)
    if plain:
        return (plain.group(1) or plain.group(2) or "").strip()
    return None


def _safe_filename(value: str) -> str:
    name = _PATH_CHARS_RE.sub("_", Path(str(value)).name).strip(" .")
    name = re.sub(r"\s+", " ", name)
    if not name:
        name = f"tdc_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    if not name.lower().endswith(".xlsx"):
        name += ".xlsx"
    return name[:180]


def _row_identity(report_type: str, row: Mapping[str, Any]) -> str:
    candidates = (
        ("formId", "incident", "documentNo")
        if report_type == "data_model"
        else ("id", "processInstanceId", "processNo")
    )
    for key in candidates:
        value = row.get(key)
        if value is not None and str(value).strip():
            return f"{key}:{value}"
    try:
        return "json:" + json.dumps(row, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    except TypeError:
        return "repr:" + repr(sorted((str(key), str(value)) for key, value in row.items()))


def _request_id() -> str:
    return uuid.uuid4().hex[:8]


def _timestamp() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


__all__ = [
    "AFACE_CONTRACT_BLOCKER",
    "AFACE_PAGE_PATH",
    "DATA_MODEL_EXPORT_PATH",
    "DATA_MODEL_LIST_PATH",
    "DEFAULT_TDC_BASE_URL",
    "SOR_EXPORT_PATH",
    "SOR_LIST_PATH",
    "SOR_PROJECT_LIST_PATH",
    "TDCAFaceFilters",
    "TDCCrawlerClient",
    "TDCCrawlerError",
    "TDCDataModelFilters",
    "TDCExportResult",
    "TDCHttpDiagnosticEvent",
    "TDCPagedResult",
    "TDCSORFilters",
    "combine_diagnostic_hooks",
]
