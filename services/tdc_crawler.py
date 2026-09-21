# -*- coding: utf-8 -*-
"""Offline-testable HTTP client for the TDC report pages."""

from __future__ import annotations

from core.diagnostic_recording import observed, record_http

import json
import logging
import math
import re
import time
import uuid
from dataclasses import dataclass, field, replace
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
TDC_EXPORT_RECEIVE_TIMEOUT = 120.0

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


class CrawlCancelled(RuntimeError):
    """Raised at a pagination boundary when the caller requested cancellation."""


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
        operation: str | None = None,
        report_type: str | None = None,
        api_code: Any = None,
        response_fields: tuple[str, ...] = (),
        reason_available: bool | None = None,
    ) -> None:
        super().__init__(redact_sensitive_text(message))
        self.stage = stage
        self.request_id = request_id
        self.status_code = status_code
        self.completed_pages = completed_pages
        self.operation = operation
        self.report_type = report_type
        self.api_code = api_code
        self.response_fields = response_fields
        self.reason_available = reason_available

    def safe_diagnostic(self) -> dict[str, Any]:
        """Allowlisted metadata only: safe to persist without upstream prose."""
        result: dict[str, Any] = {"source": "tdc"}
        if self.operation in ("query", "export"):
            result["operation"] = self.operation
        if self.report_type in ("sor", "sor_projects", "data_model", "a_face"):
            result["reportType"] = self.report_type
        if self.stage in (
            "request", "export", "status-validation", "content-validation",
            "parse-json", "api-validation", "export-validation",
            "contract-validation", "pagination",
        ):
            result["stage"] = self.stage
        if isinstance(self.request_id, str) and re.fullmatch(r"[a-f0-9]{8,32}", self.request_id):
            result["requestId"] = self.request_id
        if type(self.status_code) is int and 100 <= self.status_code <= 599:
            result["upstreamHttpStatus"] = self.status_code
        code = _safe_api_code(self.api_code)
        if code is not None:
            result["apiCode"] = code
        allowed_fields = {"code", "msg", "message", "error", "data", "success", "status"}
        result["responseFields"] = sorted({
            name for name in self.response_fields
            if isinstance(name, str) and name in allowed_fields
        })
        if type(self.reason_available) is bool:
            result["reasonAvailable"] = self.reason_available
        return result

    def safe_diagnostic_message(self) -> str:
        """Stable archival explanation; never include arbitrary exception text."""
        details = self.safe_diagnostic()
        labels = {"reportType": "report", "stage": "stage", "upstreamHttpStatus": "upstream_http",
                  "apiCode": "api_code", "requestId": "request_id"}
        parts = [f"{label}={details[key]}" for key, label in labels.items() if key in details]
        if details["responseFields"]:
            parts.append("fields=" + "|".join(details["responseFields"]))
        if details.get("reasonAvailable") is False:
            parts.append("reason=not_provided")
        elif details.get("reasonAvailable") is True:
            parts.append("reason=provided_not_persisted")
        operation = details.get("operation", "request")
        return f"TDC {operation} failed" + (f" ({', '.join(parts)})" if parts else "")


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
    timeout: float | tuple[float, float] | None = None
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
    car_type_project_id: str | None = None
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
        if self.car_type_project_id and self.car_type_project_id.strip():
            # Official SOR requests use the internal ID in both parameters.
            params["carTypeProject"] = self.car_type_project_id.strip()
            params["carTypeProjectAll[0]"] = self.car_type_project_id.strip()
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
    # True only when the response metadata or an explicit end-of-data page
    # proves that no tail was omitted. Unknown/truncated results stay false.
    complete: bool = False


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
        self._car_type_projects_cache: list[dict[str, Any]] | None = None

    @observed("tdc.TDCCrawlerClient.query_data_model_page")
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
            record_granularity="part_detail",
        )

    @observed("tdc.TDCCrawlerClient.crawl_data_model_all")
    def crawl_data_model_all(
        self,
        filters: TDCDataModelFilters | None = None,
        *,
        page_size: int = 50,
        max_pages: int = 100,
        max_records: int = 10000,
        should_stop: Callable[[], bool] | None = None,
        on_page: Callable[[int, int], None] | None = None,
    ) -> TDCPagedResult:
        return self._crawl_all(
            report_type="data_model",
            query=self.query_data_model_page,
            filters=filters or TDCDataModelFilters(),
            page_size=page_size,
            max_pages=max_pages,
            max_records=max_records,
            record_granularity="part_detail",
            should_stop=should_stop,
            on_page=on_page,
        )

    @observed("tdc.TDCCrawlerClient.export_data_model")
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
            record_granularity="part_detail",
        )

    @observed("tdc.TDCCrawlerClient.list_car_type_projects")
    def list_car_type_projects(self) -> list[dict[str, Any]]:
        result = self._request_json(
            report_type="sor_projects",
            route=SOR_PROJECT_LIST_PATH,
            referer_path=SOR_PAGE_PATH,
            params={"sorEnabled": "true"},
            page=None,
            page_size=None,
        )
        data = result[0].get("data", [])
        if not isinstance(data, list) or any(not isinstance(item, Mapping) for item in data):
            raise TDCCrawlerError("TDC car type project response does not contain a list", stage="parse-json")
        return [dict(item) for item in data]

    def _get_cached_car_type_projects(self) -> list[dict[str, Any]]:
        if self._car_type_projects_cache is not None:
            return self._car_type_projects_cache
        projects = self.list_car_type_projects()
        self._car_type_projects_cache = projects
        return projects

    @observed("tdc.TDCCrawlerClient._resolve_sor_filters")
    def _resolve_sor_filters(self, filters: TDCSORFilters | None) -> TDCSORFilters:
        if filters is None:
            return TDCSORFilters()

        filters.to_params()  # Reject invalid dates/enums before any project lookup.
        project_text = (filters.car_type_project or "").strip()
        project_id = (filters.car_type_project_id or "").strip()

        if not project_text and not project_id:
            return filters

        projects = self._get_cached_car_type_projects()

        if project_id:
            matched_by_id = [
                p
                for p in projects
                if isinstance(p, Mapping)
                and _project_scalar(p.get("id")) == project_id
            ]
            if not matched_by_id:
                raise TDCCrawlerError(
                    "指定的车型项目ID不存在或已失效，请重新核对车型项目配置。",
                    stage="contract-validation",
                )
            if project_text:
                text_matched = any(
                    _project_scalar(p.get("projectNo")) == project_text
                    or _project_scalar(p.get("projectName")) == project_text
                    for p in matched_by_id
                )
                if not text_matched:
                    raise TDCCrawlerError(
                        "指定的车型项目ID与项目名称不匹配，请核对车型项目配置。",
                        stage="contract-validation",
                    )
            return replace(
                filters,
                car_type_project_id=project_id,
            )

        matched = [
            p
            for p in projects
            if isinstance(p, Mapping)
            and (
                _project_scalar(p.get("projectNo")) == project_text
                or _project_scalar(p.get("projectName")) == project_text
            )
        ]

        if not matched:
            raise TDCCrawlerError(
                "未找到匹配的车型项目，请核对车型项目编号或名称。",
                stage="contract-validation",
            )

        candidate_ids: list[str] = []
        for p in matched:
            item_id = _project_scalar(p.get("id"))
            if not item_id:
                raise TDCCrawlerError(
                    "匹配的车型项目缺少有效内部ID，无法进行查询或导出。",
                    stage="contract-validation",
                )
            candidate_ids.append(item_id)

        unique_ids = set(candidate_ids)
        if len(unique_ids) > 1:
            raise TDCCrawlerError(
                "车型项目匹配到多个不同的内部ID，存在歧义，请指定明确的项目ID。",
                stage="contract-validation",
            )

        resolved_id = candidate_ids[0]
        return replace(
            filters,
            car_type_project_id=resolved_id,
        )

    @observed("tdc.TDCCrawlerClient.query_sor_page")
    def query_sor_page(
        self,
        filters: TDCSORFilters | None = None,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> TDCPagedResult:
        resolved = self._resolve_sor_filters(filters)
        return self._query_page(
            report_type="sor",
            route=SOR_LIST_PATH,
            referer_path=SOR_PAGE_PATH,
            filter_params=resolved.to_params(),
            page=page,
            page_size=page_size,
            record_granularity="workflow",
        )

    @observed("tdc.TDCCrawlerClient.crawl_sor_all")
    def crawl_sor_all(
        self,
        filters: TDCSORFilters | None = None,
        *,
        page_size: int = 50,
        max_pages: int = 100,
        max_records: int = 10000,
        should_stop: Callable[[], bool] | None = None,
        on_page: Callable[[int, int], None] | None = None,
    ) -> TDCPagedResult:
        resolved = self._resolve_sor_filters(filters)
        return self._crawl_all(
            report_type="sor",
            query=self.query_sor_page,
            filters=resolved,
            page_size=page_size,
            max_pages=max_pages,
            max_records=max_records,
            record_granularity="workflow",
            should_stop=should_stop,
            on_page=on_page,
        )

    @observed("tdc.TDCCrawlerClient.export_sor")
    def export_sor(
        self,
        filters: TDCSORFilters | None = None,
        *,
        file_name: str | None = None,
    ) -> TDCExportResult:
        resolved = self._resolve_sor_filters(filters)
        params = resolved.to_params()
        params["pagePath"] = self._url(SOR_PAGE_PATH)
        params.setdefault("bizName", "SOR")
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

    @observed("tdc.TDCCrawlerClient._query_page")
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
        current = _pagination_int(data, "current", default=page, minimum=1)
        size = _pagination_int(data, "size", default=page_size, minimum=1)
        total = _pagination_int(data, "total", minimum=0)
        pages = _pagination_int(data, "pages", minimum=0)
        assert current is not None and size is not None
        return TDCPagedResult(
            report_type=report_type,
            rows=rows,
            page=current,
            page_size=size,
            total=total,
            pages=pages,
            fetched_pages=1,
            unique_count=len(rows),
            duplicate_count=0,
            stop_reason="single_page",
            record_granularity=record_granularity,
        )

    @observed("tdc.TDCCrawlerClient._crawl_all")
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
        should_stop: Callable[[], bool] | None = None,
        on_page: Callable[[int, int], None] | None = None,
    ) -> TDCPagedResult:
        _validate_limits(page_size=page_size, max_pages=max_pages, max_records=max_records)
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        duplicates = 0
        fetched_pages = 0
        reported_total: int | None = None
        reported_pages: int | None = None
        accumulated_count = 0
        metadata_inconsistent = False
        stop_reason = "max_pages"

        for page in range(1, max_pages + 1):
            if should_stop is not None and should_stop():
                raise CrawlCancelled(
                    f"cancelled at TDC {report_type} pagination boundary "
                    f"(page {page}, rows {len(rows)})"
                )
            try:
                result = query(filters, page=page, page_size=page_size)
            except TDCCrawlerError as exc:
                exc.completed_pages = fetched_pages
                self._emit_failure_event(report_type, exc, fetched_pages)
                raise
            fetched_pages += 1
            rows_before = len(rows)
            raw_page_count = len(result.rows)
            page_mismatch = result.page != page
            size_mismatch = result.page_size != page_size
            invalid_page = page_mismatch or size_mismatch
            # Never claim a complete result after discarding rows at the
            # caller's safety boundary, even if page metadata says this was
            # the last page.  The discarded rows may carry distinct business
            # identities or content needed by the aggregate fingerprint.
            overflowed = not invalid_page and rows_before + raw_page_count > max_records
            if not invalid_page:
                accumulated_count += len(result.rows)
            added = 0
            if not invalid_page:
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

            if result.total is not None:
                if (
                    reported_total is not None and result.total != reported_total
                ) or result.total < accumulated_count:
                    metadata_inconsistent = True
                if reported_total is None:
                    reported_total = result.total
            if result.pages is not None:
                # A zero-page empty result is a valid server convention.
                empty_zero_pages = (
                    page == 1 and result.pages == 0 and not result.rows
                    and result.total in (None, 0)
                )
                if (
                    reported_pages is not None and result.pages != reported_pages
                ) or (result.pages < page and not empty_zero_pages):
                    metadata_inconsistent = True
                if reported_pages is None:
                    reported_pages = result.pages

            total_reached = (
                reported_total is not None
                and reported_total <= max_records
                and accumulated_count >= reported_total
            )
            pages_reached = reported_pages is not None and page >= reported_pages
            if total_reached and reported_pages is not None and page < reported_pages:
                # A server cannot simultaneously say that all records have
                # been returned and that a later page still exists.  Do not
                # choose total over pages as the authoritative source.
                metadata_inconsistent = True

            total_proven = (
                reported_total is None
                or (
                    reported_total <= max_records
                    and accumulated_count >= reported_total
                    and len(rows) >= reported_total
                )
            )
            reported_end = (
                pages_reached
                and total_proven
            )
            total_end = (
                reported_total is not None
                and reported_total <= max_records
                and reported_pages is None
                and accumulated_count >= reported_total
                and len(rows) >= reported_total
            )
            if page_mismatch:
                # The response is not for the page we requested.  Its rows
                # are deliberately excluded from the result and cannot
                # contribute to an end-of-data proof.
                stop_reason = "inconsistent_page"
            elif size_mismatch:
                # The requested size cannot prove a short final page when
                # the server uses a different size/offset contract.
                stop_reason = "inconsistent_page_size"
            elif metadata_inconsistent:
                # Contradictory page metadata is not an end-of-data proof.
                # Stop immediately and require a fresh, narrower query.
                stop_reason = "inconsistent_metadata"
            elif duplicates:
                # A duplicate row means raw accumulated_count can no longer
                # prove that the deduplicated result contains the declared
                # record set.  Reject the result instead of authorizing a
                # partial aggregate snapshot.
                stop_reason = "duplicate_records"
            elif not overflowed and (reported_end or total_end):
                stop_reason = "reported_pages" if reported_end else "reported_total"
            elif not overflowed and not result.rows:
                # An empty page proves end-of-data only when it does not
                # contradict the server's declared total.  A premature
                # empty page is an incomplete result and must never be
                # accepted by mapping discovery or sync execution.
                stop_reason = (
                    "incomplete_page"
                    if (
                        reported_total is not None
                        and accumulated_count < reported_total
                    )
                    or (reported_pages is not None and page < reported_pages)
                    else "empty_page"
                )
            elif not overflowed and len(result.rows) < page_size:
                stop_reason = (
                    "short_page"
                    if (
                        (reported_total is None or accumulated_count >= reported_total)
                        and (reported_pages is None or page >= reported_pages)
                    )
                    else "incomplete_page"
                )
            elif len(rows) >= max_records:
                stop_reason = "max_records"
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
                    current_page=result.page,
                )
            )
            if stop_reason != "continue":
                break
            if on_page is not None:
                on_page(page, len(rows))

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
            complete=stop_reason in {"reported_pages", "reported_total", "empty_page", "short_page"},
        )

    @observed("tdc.TDCCrawlerClient._request_json")
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
                operation="query",
                report_type=report_type,
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
                operation="query",
                report_type=report_type,
                status_code=status,
            )
        if _looks_like_html(response, content_type):
            self._emit(TDCHttpDiagnosticEvent(**base_event, validation="rejected-login-html"))
            raise TDCCrawlerError(
                "TDC response looks like a login HTML page, not JSON; refresh browser headers and Cookie/Authorization",
                stage="content-validation",
                request_id=request_id,
                operation="query",
                report_type=report_type,
                status_code=status,
            )
        if not _is_json_content_type(content_type):
            self._emit(TDCHttpDiagnosticEvent(**base_event, validation="rejected-content-type"))
            raise TDCCrawlerError(
                f"TDC JSON endpoint returned unsupported Content-Type: {content_type or '<missing>'}",
                stage="content-validation",
                request_id=request_id,
                operation="query",
                report_type=report_type,
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
                operation="query",
                report_type=report_type,
                status_code=status,
            ) from exc
        if not isinstance(payload, dict):
            self._emit(TDCHttpDiagnosticEvent(**base_event, validation="json-not-object"))
            raise TDCCrawlerError(
                "TDC JSON response is not an object",
                stage="parse-json",
                request_id=request_id,
                operation="query",
                report_type=report_type,
                status_code=status,
            )
        api_code = payload.get("code")
        if api_code not in (None, 0, 200, "0", "200"):
            reason = redact_sensitive_text(payload.get("msg", "TDC API rejected the request"), limit=240)
            self._emit(TDCHttpDiagnosticEvent(**base_event, validation="api-error", reason=reason))
            raise TDCCrawlerError(
                f"TDC API error code {_safe_api_code(api_code) if _safe_api_code(api_code) is not None else 'unrecognized'}: {reason}",
                stage="api-validation",
                api_code=api_code,
                response_fields=tuple(payload.keys()),
                reason_available=isinstance(payload.get("msg"), str) and bool(payload["msg"].strip()),
                request_id=request_id,
                operation="query",
                report_type=report_type,
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

    @observed("tdc.TDCCrawlerClient._export")
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
            "application/json, text/plain, */*",
        )
        export_timeout = (self.timeout, max(self.timeout, TDC_EXPORT_RECEIVE_TIMEOUT))
        started = time.perf_counter()
        try:
            response = self.session.get(url, params=dict(params), headers=headers, timeout=export_timeout)
        except Exception as exc:
            elapsed = _elapsed_ms(started)
            self._emit(
                self._exception_event(
                    report_type,
                    "export",
                    request_id,
                    route,
                    params,
                    headers,
                    None,
                    None,
                    elapsed,
                    exc,
                    timeout=export_timeout,
                )
            )
            raise TDCCrawlerError(
                f"TDC export failed: {type(exc).__name__}: {redact_sensitive_text(exc)}",
                stage="export",
                request_id=request_id,
                operation="export",
                report_type=report_type,
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
            timeout=export_timeout,
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
                operation="export",
                report_type=report_type,
                status_code=status,
            )
        if _looks_like_html(response, content_type):
            self._emit(TDCHttpDiagnosticEvent(**event_args, validation="rejected-login-html"))
            raise TDCCrawlerError(
                "TDC export returned a login HTML page, not an XLSX file",
                stage="export-validation",
                request_id=request_id,
                operation="export",
                report_type=report_type,
                status_code=status,
            )
        if not _is_xlsx_content_type(content_type):
            if _is_json_content_type(content_type):
                api_code, reason, json_fields = _export_json_summary(response)
                is_api_error = api_code not in (None, 0, 200, "0", "200")
                validation = "api-error" if is_api_error else "rejected-json-response"
                self._emit(
                    TDCHttpDiagnosticEvent(
                        **event_args,
                        validation=validation,
                        json_fields=json_fields,
                        reason=reason,
                    )
                )
                if is_api_error:
                    raise TDCCrawlerError(
                        f"TDC export API error code {_safe_api_code(api_code) if _safe_api_code(api_code) is not None else 'unrecognized'}: {reason}",
                        stage="api-validation",
                        request_id=request_id,
                        operation="export",
                        report_type=report_type,
                        api_code=api_code,
                        response_fields=json_fields,
                        reason_available=reason not in _EXPORT_REASON_FALLBACKS,
                        status_code=status,
                    )
                raise TDCCrawlerError(
                    f"TDC export returned JSON instead of an XLSX file: {reason}",
                    stage="export-validation",
                    request_id=request_id,
                    operation="export",
                    report_type=report_type,
                    api_code=api_code,
                    response_fields=json_fields,
                    reason_available=reason not in _EXPORT_REASON_FALLBACKS,
                    status_code=status,
                )
            self._emit(TDCHttpDiagnosticEvent(**event_args, validation="rejected-content-type"))
            raise TDCCrawlerError(
                f"TDC export returned unsupported Content-Type: {content_type or '<missing>'}",
                stage="export-validation",
                request_id=request_id,
                operation="export",
                report_type=report_type,
                status_code=status,
            )
        if not content.startswith(b"PK"):
            self._emit(TDCHttpDiagnosticEvent(**event_args, validation="rejected-xlsx-signature"))
            raise TDCCrawlerError(
                "TDC export failed XLSX ZIP signature validation",
                stage="export-validation",
                request_id=request_id,
                operation="export",
                report_type=report_type,
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
        record_http("tdc", event)
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
        *,
        timeout: float | tuple[float, float] | None = None,
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
            timeout=self.timeout if timeout is None else timeout,
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


def _pagination_int(
    data: Mapping[str, Any], key: str, *, default: int | None = None, minimum: int,
) -> int | None:
    """Do not disguise explicitly invalid pagination as absent metadata."""
    if key not in data:
        return default
    value = data[key]
    # Nullable totals are used by endpoints that cannot report a count.
    if value is None and default is None:
        return None
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        try:
            value = int(value.strip())
        except ValueError:
            value = None
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise TDCCrawlerError(
            f"TDC pagination field {key} is invalid", stage="parse-json",
        )
    return value


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


_EXPORT_REASON_FALLBACKS = {
    "TDC export returned JSON instead of an XLSX file",
    "TDC export API returned JSON instead of an XLSX file",
}


def _project_scalar(value: Any) -> str:
    return str(value).strip() if type(value) in (str, int) else ""


def _safe_api_code(value: Any) -> int | None:
    if type(value) is int and -999999999999 <= value <= 999999999999:
        return value
    if isinstance(value, str) and re.fullmatch(r"-?\d{1,12}", value, flags=re.ASCII):
        return int(value)
    return None


def _export_json_summary(response: Any) -> tuple[Any, str, tuple[str, ...]]:
    """Extract only safe, short diagnostics from a JSON response to export."""
    try:
        reader = getattr(response, "json", None)
        payload = reader() if callable(reader) else json.loads(getattr(response, "text", ""))
    except Exception:
        return None, "TDC export returned JSON instead of an XLSX file", ()
    if not isinstance(payload, Mapping):
        return None, "TDC export returned JSON instead of an XLSX file", ()

    code = payload.get("code")
    message: Any = "TDC export API returned JSON instead of an XLSX file"
    # Only known message positions, at most one nested level. Never stringify
    # records, arbitrary objects, stack traces, or the full response body.
    candidates = [payload.get(key) for key in ("msg", "message", "error")]
    for key in ("error", "data"):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            candidates.extend(nested.get(name) for name in ("msg", "message"))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            message = candidate
            break
        if type(candidate) in (int, float, bool):
            message = candidate
            break
    reason = redact_sensitive_text(message, limit=240, collapse_newlines=True)
    fields = tuple(sorted(key for key in payload if key in {
        "code", "msg", "message", "error", "data", "success", "status",
    }))
    return code, reason, fields


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
        name = f"tdc_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if name.lower().endswith(".xlsx"):
        stem = name[:-5]
    else:
        stem = name
    stem = stem[:175].rstrip(" .")
    if not stem:
        stem = f"tdc_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return f"{stem}.xlsx"


def _row_identity(report_type: str, row: Mapping[str, Any]) -> str:
    if report_type == "data_model":
        workflow_key = next(
            (
                f"{key}:{str(row.get(key)).strip()}"
                for key in ("incident", "documentNo", "formId")
                if row.get(key) is not None and str(row.get(key)).strip()
            ),
            "workflow:unknown",
        )
        detail = tuple(str(row.get(key) or "").strip() for key in ("partNumber", "modelNumber", "partName"))
        if any(detail):
            return "data_model:" + workflow_key + ":" + "\x1f".join(detail)
        return "data_model:" + workflow_key

    candidates = ("id", "processInstanceId", "processNo")
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
    "TDC_EXPORT_RECEIVE_TIMEOUT",
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
