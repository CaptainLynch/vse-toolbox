# -*- coding: utf-8 -*-
"""Production collectors for the six fixed scheduled archive jobs.

Collectors receive an already-resolved, short-lived credential.  They never
access SQLite and return only controlled-root artifact metadata to the runner.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from core.archive_store import ArchiveArtifact, ArchiveStore
from core.credential_provider import ResolvedCredential
from core.report_contracts import report_contracts
from core.redaction import redact_sensitive_text
from services.aras_auth import ArasECMAuthClient
from services.aras_crawler import (
    ArasCrawlerClient,
    EWOReportFilters,
    NCRApprovalFilters,
    PAAReportFilters,
)
from services.scheduled_archive_runner import (
    ArchiveCollection,
    ArchiveConnectorRegistry,
    ArchiveJobContext,
)
from services.tdc_auth import TDCPasswordAuthClient
from services.tdc_crawler import (
    TDCCrawlerClient,
    TDCDataModelFilters,
    TDCSORFilters,
)
from services.xlsx_preview import XLSXPreviewError, read_xlsx_preview

_MAX_TEXT = 512
_TDC_MAX_RECORDS = 10000
_ARAS_EWO_MAX_RECORDS = 2000
_ARAS_PAA_MAX_RECORDS = 12000
_ARCHIVE_SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "password",
    "token",
    "secret",
    "session",
    "csrf",
    "raw_xml",
)

_TDC_DATA_MODEL_KEYS = {
    "incident",
    "applicant",
    "department",
    "section",
    "applicationStart",
    "applicationEnd",
    "projectModel",
    "partNumber",
    "modelNumber",
}
_TDC_SOR_KEYS = {
    "processNo",
    "processType",
    "carTypeProject",
    "applicant",
    "title",
    "department",
    "section",
    "applicationStart",
    "applicationEnd",
    "partNumber",
    "partName",
    "version",
    "sorNumber",
    "latestCompletedNode",
    "approvalStatus",
}
_ARAS_EWO_KEYS = {
    "ewoNo",
    "projectCode",
    "subjectKeyword",
    "changeType",
    "changeSubType",
    "area",
    "state",
    "responsibleDepartment",
    "submitStart",
    "submitEnd",
}
_ARAS_PAA_KEYS = {
    "paaNo",
    "ewoNo",
    "state",
    "area",
    "base",
    "vehicleKeyword",
    "submitStart",
    "submitEnd",
    "materialRequestStart",
    "materialRequestEnd",
    "department",
}
_ARAS_NCR_KEYS = {
    "buyStart",
    "buyEnd",
    "peStart",
    "peEnd",
    "ncrNo",
    "projectNames",
    "sectionCode",
    "sectionCodes",
    "changeType",
    "otherCondition",
}


def _text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("archive scalar filter must be a string")
    result = value.strip()
    if not result:
        return None
    if len(result) > _MAX_TEXT or any(ord(char) < 32 for char in result):
        raise ValueError("archive filter value is invalid")
    return result


def _string_list(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("archive filter list is invalid")
    if len(value) > 100:
        raise ValueError("archive filter list is too large")
    result: list[str] = []
    for item in value:
        cleaned = _text(item)
        if cleaned:
            result.append(cleaned)
    return tuple(result)


def _checked_filters(
    value: Mapping[str, object],
    allowed: set[str],
) -> Mapping[str, object]:
    unknown = set(value) - allowed
    if unknown:
        raise ValueError("archive filters contain unsupported fields")
    return value


def archive_filter_names(job_key: str) -> tuple[str, ...]:
    """Return the fixed, non-secret filter contract for one archive job."""
    contracts = {
        "tdc_data_model": _TDC_DATA_MODEL_KEYS,
        "tdc_sor": _TDC_SOR_KEYS,
        "aras_ewo": _ARAS_EWO_KEYS,
        "aras_paa": _ARAS_PAA_KEYS,
        "aras_ncr_progress": _ARAS_NCR_KEYS,
        "aras_ncr_detail": _ARAS_NCR_KEYS,
    }
    try:
        return tuple(sorted(contracts[job_key]))
    except KeyError as exc:
        raise KeyError(job_key) from exc


def _close_session(session: object) -> None:
    close = getattr(session, "close", None)
    if callable(close):
        close()


def _is_sensitive_archive_key(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return any(part in normalized for part in _ARCHIVE_SENSITIVE_KEY_PARTS)


def _sanitize_archive_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_archive_value(item)
            for key, item in value.items()
            if not _is_sensitive_archive_key(key)
        }
    if isinstance(value, list):
        return [_sanitize_archive_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_archive_value(item) for item in value)
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def _sanitize_archive_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            str(key): _sanitize_archive_value(value)
            for key, value in row.items()
            if not _is_sensitive_archive_key(key)
        }
        for row in rows
    )


def _archive_for_context(
    archive: ArchiveStore,
    context: ArchiveJobContext,
) -> ArchiveStore:
    """Use a task-level directory override while preserving global limits."""
    selected = str(getattr(context, "output_directory", "") or "").strip()
    if not selected:
        return archive
    return ArchiveStore(
        {"default": selected},
        max_bytes=archive.max_bytes,
        reserve_bytes=archive.reserve_bytes,
    )


def _normalized_artifacts(
    archive: ArchiveStore,
    context: ArchiveJobContext,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[ArchiveArtifact, ArchiveArtifact]:
    safe_rows = _sanitize_archive_rows(rows)
    fields = sorted({str(key) for row in safe_rows for key in row})
    common = {
        "source": context.source_type,
        "report": context.report_type,
        "run_id": context.run_id,
        "output_subdir": context.output_subdir,
    }
    csv_item = archive.write_csv(
        safe_rows,
        fields,
        file_name=f"{context.report_type}.csv",
        artifact_type="normalized_csv",
        **common,
    )
    json_item = archive.write_json(
        list(safe_rows),
        file_name=f"{context.report_type}.json",
        artifact_type="normalized_json",
        **common,
    )
    return csv_item, json_item


def _official_workbook_rows(path: Path, report_type: str) -> tuple[dict[str, object], ...] | None:
    """Read bounded normalized rows from one official TDC workbook.

    ``None`` means the test double or an older endpoint did not provide a
    readable XLSX; callers may then use the legacy list fallback.  A readable
    official workbook with a wrong header is a contract error and must not be
    silently replaced with list data.
    """
    try:
        preview = read_xlsx_preview(path, max_rows=_TDC_MAX_RECORDS + 1)
    except XLSXPreviewError:
        return None
    if not preview.rows:
        return ()
    raw_header = preview.rows[0]
    headers = [str(value or "").strip() for value in raw_header]
    if report_type in {"data_model", "sor"}:
        contract_key = f"tdc_{report_type}"
        expected = [
            str(value or "").strip()
            for value in report_contracts()[contract_key]["headerRows"][0]
        ]
        if headers[: len(expected)] != expected or any(headers[len(expected) :]):
            raise ValueError(f"official TDC {report_type} export header does not match the approved contract")
        headers = expected
    else:
        headers = [value or f"column_{index + 1}" for index, value in enumerate(headers)]
    result: list[dict[str, object]] = []
    for row in preview.rows[1:]:
        if not row or not any(value not in (None, "") for value in row):
            continue
        values = list(row) + [None] * max(0, len(headers) - len(row))
        result.append({headers[index]: values[index] for index in range(len(headers))})
    return tuple(result)


class TDCArchiveConnector:
    """Collect official XLSX plus normalized API rows for TDC jobs."""

    def __init__(
        self,
        archive: ArchiveStore,
        *,
        timeout: float = 60.0,
        auth_factory: Callable[..., Any] = TDCPasswordAuthClient,
        crawler_factory: Callable[..., Any] = TDCCrawlerClient,
    ) -> None:
        self._archive = archive
        self._timeout = timeout
        self._auth_factory = auth_factory
        self._crawler_factory = crawler_factory

    def collect(
        self,
        context: ArchiveJobContext,
        credential: ResolvedCredential,
    ) -> ArchiveCollection:
        if context.job_key not in {"tdc_data_model", "tdc_sor"}:
            raise ValueError("TDC archive job is not supported")
        login = self._auth_factory(timeout=self._timeout).login(
            credential.username,
            credential.password,
        )
        try:
            return self._collect_authenticated(
                context,
                login.session,
                _archive_for_context(self._archive, context),
            )
        finally:
            _close_session(login.session)

    def _collect_authenticated(
        self,
        context: ArchiveJobContext,
        session: object,
        archive: ArchiveStore,
    ) -> ArchiveCollection:
        with tempfile.TemporaryDirectory() as temp_dir:
            crawler = self._crawler_factory(
                session=session,
                timeout=self._timeout,
                output_dir=Path(temp_dir),
            )
            if context.job_key == "tdc_data_model":
                data_model_filters = self._data_model_filters(context.filters)
                official = crawler.export_data_model(data_model_filters)
                rows = _official_workbook_rows(official.path, "data_model")
                if rows is None:
                    result = crawler.crawl_data_model_all(
                        data_model_filters,
                        max_records=_TDC_MAX_RECORDS,
                    )
                    rows = tuple(dict(row) for row in result.rows)
            else:
                sor_filters = self._sor_filters(context.filters)
                official = crawler.export_sor(sor_filters)
                rows = _official_workbook_rows(official.path, "sor")
                if rows is None:
                    result = crawler.crawl_sor_all(
                        sor_filters,
                        max_records=_TDC_MAX_RECORDS,
                    )
                    rows = tuple(dict(row) for row in result.rows)
            with official.path.open("rb") as stream:
                xlsx = archive.write_stream(
                    stream,
                    source=context.source_type,
                    report=context.report_type,
                    run_id=context.run_id,
                    output_subdir=context.output_subdir,
                    file_name=official.file_name,
                    artifact_type="official_xlsx",
                    expected_size=official.byte_count,
                )
        normalized = _normalized_artifacts(archive, context, rows)
        return ArchiveCollection(len(rows), (xlsx, *normalized))

    @staticmethod
    def _data_model_filters(value: Mapping[str, object]) -> TDCDataModelFilters:
        rule = _checked_filters(value, _TDC_DATA_MODEL_KEYS)
        return TDCDataModelFilters(
            serial_number=_text(rule.get("incident")),
            applicant=_text(rule.get("applicant")),
            department=_text(rule.get("department")),
            section=_text(rule.get("section")),
            application_start=_text(rule.get("applicationStart")),
            application_end=_text(rule.get("applicationEnd")),
            project_model=_text(rule.get("projectModel")),
            part_number=_text(rule.get("partNumber")),
            model_number=_text(rule.get("modelNumber")),
        )

    @staticmethod
    def _sor_filters(value: Mapping[str, object]) -> TDCSORFilters:
        rule = _checked_filters(value, _TDC_SOR_KEYS)
        return TDCSORFilters(
            serial_number=_text(rule.get("processNo")),
            process_type=_text(rule.get("processType")),
            car_type_project=_text(rule.get("carTypeProject")),
            applicant=_text(rule.get("applicant")),
            title=_text(rule.get("title")),
            department=_text(rule.get("department")),
            section=_text(rule.get("section")),
            application_start=_text(rule.get("applicationStart")),
            application_end=_text(rule.get("applicationEnd")),
            part_number=_text(rule.get("partNumber")),
            part_name=_text(rule.get("partName")),
            version=_text(rule.get("version")),
            sor_number=_text(rule.get("sorNumber")),
            latest_completed_node=_text(rule.get("latestCompletedNode")),
            approval_status=_text(rule.get("approvalStatus")),
        )


class ArasArchiveConnector:
    """Collect EWO/PAA rows or the official NCR workbook from ARAS."""

    def __init__(
        self,
        archive: ArchiveStore,
        *,
        timeout: float = 60.0,
        auth_factory: Callable[..., Any] = ArasECMAuthClient,
        crawler_factory: Callable[..., Any] = ArasCrawlerClient,
    ) -> None:
        self._archive = archive
        self._timeout = timeout
        self._auth_factory = auth_factory
        self._crawler_factory = crawler_factory

    def collect(
        self,
        context: ArchiveJobContext,
        credential: ResolvedCredential,
    ) -> ArchiveCollection:
        if context.job_key not in {
            "aras_ewo",
            "aras_paa",
            "aras_ncr_progress",
            "aras_ncr_detail",
        }:
            raise ValueError("ARAS archive job is not supported")
        auth = self._auth_factory(timeout=self._timeout)
        login = auth.login(credential.username, credential.password)
        try:
            return self._collect_authenticated(
                auth.base_url,
                login.session,
                context,
                _archive_for_context(self._archive, context),
            )
        finally:
            _close_session(login.session)

    def _collect_authenticated(
        self,
        base_url: str,
        session: object,
        context: ArchiveJobContext,
        archive: ArchiveStore,
    ) -> ArchiveCollection:
        crawler = self._crawler_factory(
            base_url,
            session=session,
            timeout=self._timeout,
            prewarm=False,
        )
        if context.job_key == "aras_ewo":
            result = crawler.crawl_ewo_report_all(
                self._ewo_filters(context.filters),
                max_records=_ARAS_EWO_MAX_RECORDS,
            )
            rows = tuple(dict(row) for row in result.rows)
            return ArchiveCollection(
                len(rows),
                _normalized_artifacts(archive, context, rows),
            )
        if context.job_key == "aras_paa":
            result = crawler.crawl_paa_report_all(
                self._paa_filters(context.filters),
                max_records=_ARAS_PAA_MAX_RECORDS,
            )
            rows = tuple(dict(row) for row in result.rows)
            return ArchiveCollection(
                len(rows),
                _normalized_artifacts(archive, context, rows),
            )
        return self._collect_ncr(crawler, context, archive)

    def _collect_ncr(
        self,
        crawler: Any,
        context: ArchiveJobContext,
        archive: ArchiveStore,
    ) -> ArchiveCollection:
        filters = self._ncr_filters(context.filters)
        with tempfile.TemporaryDirectory() as temp_dir:
            if context.job_key == "aras_ncr_progress":
                export = crawler.query_ncr_approval_progress(filters)
                downloaded = crawler.download_ncr_progress_file(
                    export,
                    Path(temp_dir),
                )
            else:
                export = crawler.extract_ncr_approval_detail(filters)
                downloaded = crawler.download_ncr_detail_file(
                    export.file_name,
                    Path(temp_dir),
                )
            with downloaded.open("rb") as stream:
                official = archive.write_stream(
                    stream,
                    source=context.source_type,
                    report=context.report_type,
                    run_id=context.run_id,
                    output_subdir=context.output_subdir,
                    file_name=downloaded.name,
                    artifact_type="official_xlsx",
                    expected_size=downloaded.stat().st_size,
                )
        manifest = archive.write_json(
            {
                "jobKey": context.job_key,
                "recordCount": None,
                "normalization": "pending_verified_workbook_contract",
            },
            source=context.source_type,
            report=context.report_type,
            run_id=context.run_id,
            output_subdir=context.output_subdir,
            file_name=f"{context.report_type}-manifest.json",
            artifact_type="manifest_json",
        )
        return ArchiveCollection(0, (official, manifest))

    @staticmethod
    def _ewo_filters(value: Mapping[str, object]) -> EWOReportFilters:
        rule = _checked_filters(value, _ARAS_EWO_KEYS)
        return EWOReportFilters(
            ewo_no=_text(rule.get("ewoNo")),
            project_code=_text(rule.get("projectCode")),
            subject_keyword=_text(rule.get("subjectKeyword")),
            change_type=_text(rule.get("changeType")),
            change_sub_type=_text(rule.get("changeSubType")),
            area=_text(rule.get("area")),
            state=_text(rule.get("state")),
            rsp_department=_text(rule.get("responsibleDepartment")),
            submit_start=_text(rule.get("submitStart")),
            submit_end=_text(rule.get("submitEnd")),
        )

    @staticmethod
    def _paa_filters(value: Mapping[str, object]) -> PAAReportFilters:
        rule = _checked_filters(value, _ARAS_PAA_KEYS)
        return PAAReportFilters(
            paa_no=_text(rule.get("paaNo")),
            ewo_no=_text(rule.get("ewoNo")),
            state=_text(rule.get("state")),
            area=_text(rule.get("area")),
            base=_text(rule.get("base")),
            vehicle_keyword=_text(rule.get("vehicleKeyword")),
            submit_start=_text(rule.get("submitStart")),
            submit_end=_text(rule.get("submitEnd")),
            mtl_rq_start=_text(rule.get("materialRequestStart")),
            mtl_rq_end=_text(rule.get("materialRequestEnd")),
            department=_text(rule.get("department")),
        )

    @staticmethod
    def _ncr_filters(value: Mapping[str, object]) -> NCRApprovalFilters:
        rule = _checked_filters(value, _ARAS_NCR_KEYS)
        return NCRApprovalFilters(
            buy_start=_text(rule.get("buyStart")),
            buy_end=_text(rule.get("buyEnd")),
            pe_start=_text(rule.get("peStart")),
            pe_end=_text(rule.get("peEnd")),
            ncr_no=_text(rule.get("ncrNo")),
            project_names=_string_list(rule.get("projectNames")),
            section_code=_text(rule.get("sectionCode")),
            section_codes=_string_list(rule.get("sectionCodes")),
            change_type=_text(rule.get("changeType")),
            othercondition=_text(rule.get("otherCondition")) or "0",
        )


def create_production_archive_registry(
    archive: ArchiveStore | None = None,
) -> ArchiveConnectorRegistry:
    """Build the fixed production registry; intentionally contains no A-face."""
    store = archive or ArchiveStore()
    tdc = TDCArchiveConnector(store)
    aras = ArasArchiveConnector(store)
    registry = ArchiveConnectorRegistry()
    for key in ("tdc_data_model", "tdc_sor"):
        registry.register(key, tdc)
    for key in (
        "aras_ewo",
        "aras_paa",
        "aras_ncr_progress",
        "aras_ncr_detail",
    ):
        registry.register(key, aras)
    return registry


def validate_archive_filters(
    job_key: str,
    filters: Mapping[str, object],
) -> dict[str, object]:
    """Validate filters against the connector contract without external I/O."""
    if not isinstance(filters, Mapping):
        raise ValueError("archive filters must be an object")
    normalized = dict(filters)
    if job_key == "tdc_data_model":
        TDCArchiveConnector._data_model_filters(normalized)
    elif job_key == "tdc_sor":
        TDCArchiveConnector._sor_filters(normalized)
    elif job_key == "aras_ewo":
        ArasArchiveConnector._ewo_filters(normalized)
    elif job_key == "aras_paa":
        ArasArchiveConnector._paa_filters(normalized)
    elif job_key in {"aras_ncr_progress", "aras_ncr_detail"}:
        ArasArchiveConnector._ncr_filters(normalized)
    else:
        raise KeyError(job_key)
    return normalized
