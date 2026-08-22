# -*- coding: utf-8 -*-
"""Fixed-contract Aras/TDC project-status connectors."""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from core.archive_store import ArchiveStore
from core.credential_provider import CredentialProvider
from services.aras_auth import ArasECMAuthClient
from services.aras_crawler import ArasCrawlerClient, EWOReportFilters
from services.project_status_sync_runner import SyncBindingContext
from services.project_status_updates import ConnectorCandidate, ConnectorSnapshot
from services.tdc_auth import TDCPasswordAuthClient
from services.tdc_crawler import (
    TDCCrawlerClient,
    TDCDataModelFilters,
    TDCSORFilters,
)

_IDENTITY_FIELDS = (
    "formId", "incident", "documentNo", "processInstanceId", "processNo",
    "id", "ewo_no", "item_number", "itemNumber",
)
_MAX_ROWS = 10000
logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_scalar(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:1000] if text else None


def _stable_version(row: Mapping[str, Any]) -> str:
    normalized = {str(key): _clean_scalar(value) for key, value in sorted(row.items())}
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _identity(row: Mapping[str, Any]) -> str:
    for key in _IDENTITY_FIELDS:
        value = _clean_scalar(row.get(key))
        if value:
            return value
    return ""


def _close_session(session: Any) -> None:
    """Best-effort close without allowing cleanup errors to mask sync results."""
    close = getattr(session, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception:
        logger.warning("project-status external session close failed")


def _snapshot(context: SyncBindingContext, rows: Sequence[Mapping[str, Any]], artifacts: Sequence[Mapping[str, Any]]) -> ConnectorSnapshot:
    matches = [dict(row) for row in rows if _identity(row) == context.external_key]
    fetched = _now()
    if len(matches) != 1:
        marker = hashlib.sha256(f"{len(matches)}:{context.external_key}".encode()).hexdigest()
        return ConnectorSnapshot(
            "not_found" if not matches else "ambiguous", (), marker, fetched,
            context.expected_deliverable_updated_at, artifacts,
        )
    row = matches[0]
    version = _stable_version(row)
    values = {
        api_field: _clean_scalar(row.get(str(source_field)))
        for api_field, source_field in context.mapping.items()
    }
    candidate = ConnectorCandidate(context.external_key, version, values, fetched)
    return ConnectorSnapshot(
        "matched", (candidate,), version, fetched,
        context.expected_deliverable_updated_at, artifacts,
    )


class RetryingConnector:
    def __init__(self, connector: Any, *, max_attempts: int = 2, backoff_seconds: float = 1.0, sleeper: Callable[[float], None] = time.sleep) -> None:
        if max_attempts < 1 or max_attempts > 2:
            raise ValueError("max_attempts must be between 1 and 2")
        self.connector = connector
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.sleeper = sleeper

    def collect(self, context: SyncBindingContext) -> ConnectorSnapshot:
        for attempt in range(1, self.max_attempts + 1):
            try:
                return self.connector.collect(context)
            except (ConnectionError, TimeoutError, OSError):
                if attempt >= self.max_attempts:
                    raise
                self.sleeper(self.backoff_seconds * (2 ** (attempt - 1)))
        raise AssertionError("unreachable")


class TDCProjectStatusConnector:
    def __init__(self, credentials: CredentialProvider, archive: ArchiveStore, *, timeout: float = 60.0, auth_factory: Callable[..., Any] = TDCPasswordAuthClient, crawler_factory: Callable[..., Any] = TDCCrawlerClient) -> None:
        self.credentials = credentials
        self.archive = archive
        self.timeout = timeout
        self.auth_factory = auth_factory
        self.crawler_factory = crawler_factory

    def collect(self, context: SyncBindingContext) -> ConnectorSnapshot:
        report = str(context.match_rule.get("reportType") or (
            "sor" if context.deliverable_id == "VPI-T2-D2" else "data_model"
        ))
        if report not in {"data_model", "sor"}:
            raise ValueError("TDC reportType must be data_model or sor")
        with self.credentials.resolve(context.credential_ref) as secret:
            login = self.auth_factory(timeout=self.timeout).login(secret.username, secret.password)
            try:
                with tempfile.TemporaryDirectory() as temp:
                    crawler = self.crawler_factory(session=login.session, timeout=self.timeout, output_dir=Path(temp))
                    if report == "data_model":
                        filters = self._data_model_filters(context.match_rule)
                        result = crawler.crawl_data_model_all(filters, max_records=_MAX_ROWS)
                        official = crawler.export_data_model(filters)
                    else:
                        filters = self._sor_filters(context.match_rule)
                        result = crawler.crawl_sor_all(filters, max_records=_MAX_ROWS)
                        official = crawler.export_sor(filters)
                    with official.path.open("rb") as handle:
                        xlsx = self.archive.write_stream(
                            handle, source="tdc", report=report, run_id=context.run_id,
                            file_name=official.file_name, artifact_type="xlsx",
                            expected_size=official.byte_count,
                        )
            finally:
                _close_session(login.session)
        artifacts = [xlsx.as_metadata()]
        artifacts.extend(self._normalized("tdc", report, context.run_id, result.rows))
        return _snapshot(context, result.rows, artifacts)

    def _normalized(self, source: str, report: str, run_id: int, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        fields = sorted({str(key) for row in rows for key in row})
        csv_item = self.archive.write_csv(rows, fields, source=source, report=report, run_id=run_id, file_name=f"{report}.csv", artifact_type="csv")
        json_item = self.archive.write_json(list(rows), source=source, report=report, run_id=run_id, file_name=f"{report}.json", artifact_type="json")
        return [csv_item.as_metadata(), json_item.as_metadata()]

    @staticmethod
    def _data_model_filters(rule: Mapping[str, Any]) -> TDCDataModelFilters:
        return TDCDataModelFilters(
            serial_number=_clean_scalar(rule.get("incident")), applicant=_clean_scalar(rule.get("applicant")),
            department=_clean_scalar(rule.get("department")), section=_clean_scalar(rule.get("section")),
            application_start=_clean_scalar(rule.get("applicationStart")), application_end=_clean_scalar(rule.get("applicationEnd")),
            project_model=_clean_scalar(rule.get("projectModel")), part_number=_clean_scalar(rule.get("partNumber")),
            model_number=_clean_scalar(rule.get("modelNumber")),
        )

    @staticmethod
    def _sor_filters(rule: Mapping[str, Any]) -> TDCSORFilters:
        return TDCSORFilters(
            serial_number=_clean_scalar(rule.get("processNo")), car_type_project=_clean_scalar(rule.get("carTypeProject")),
            applicant=_clean_scalar(rule.get("applicant")), title=_clean_scalar(rule.get("title")),
            part_number=_clean_scalar(rule.get("partNumber")), sor_number=_clean_scalar(rule.get("sorNumber")),
            approval_status=_clean_scalar(rule.get("approvalStatus")),
        )


class ArasProjectStatusConnector:
    def __init__(self, credentials: CredentialProvider, archive: ArchiveStore, *, timeout: float = 60.0, auth_factory: Callable[..., Any] = ArasECMAuthClient, crawler_factory: Callable[..., Any] = ArasCrawlerClient) -> None:
        self.credentials = credentials
        self.archive = archive
        self.timeout = timeout
        self.auth_factory = auth_factory
        self.crawler_factory = crawler_factory

    def collect(self, context: SyncBindingContext) -> ConnectorSnapshot:
        report = str(context.match_rule.get("reportType") or "ewo")
        if report != "ewo":
            raise ValueError("Aras project-status connector supports EWO only")
        with self.credentials.resolve(context.credential_ref) as secret:
            auth = self.auth_factory(timeout=self.timeout)
            login = auth.login(secret.username, secret.password)
            try:
                crawler = self.crawler_factory(auth.base_url, session=login.session, timeout=self.timeout, prewarm=False)
                filters = EWOReportFilters(
                    ewo_no=_clean_scalar(context.match_rule.get("ewoNo")),
                    project_code=_clean_scalar(context.match_rule.get("projectCode")),
                    subject_keyword=_clean_scalar(context.match_rule.get("subjectKeyword")),
                )
                result = crawler.crawl_ewo_report_all(filters, max_records=2000)
            finally:
                _close_session(login.session)
        fields = sorted({str(key) for row in result.rows for key in row})
        csv_item = self.archive.write_csv(result.rows, fields, source="aras", report="ewo", run_id=context.run_id, file_name="ewo.csv", artifact_type="csv")
        json_item = self.archive.write_json(result.rows, source="aras", report="ewo", run_id=context.run_id, file_name="ewo.json", artifact_type="json")
        return _snapshot(context, result.rows, [csv_item.as_metadata(), json_item.as_metadata()])
