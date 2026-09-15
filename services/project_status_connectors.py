# -*- coding: utf-8 -*-
"""Fixed-contract Aras/TDC project-status connectors."""

from __future__ import annotations

from core.diagnostic_recording import observed

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
from services.project_status_deliverable_analysis import (
    EWO_DEFAULT_RSP_DEPARTMENT_EXPRESSION,
)
from services.tdc_auth import TDCPasswordAuthClient
from services.tdc_crawler import (
    TDCCrawlerClient,
    TDCDataModelFilters,
    TDCSORFilters,
)
from services.windows_http import WinHTTPError

# 身份字段统一来自共享记录模块（与 discovery 完全一致，GPT 终审任务 3）。
from services.project_status_records import IDENTITY_FIELDS as _IDENTITY_FIELDS
from services.project_status_records import (
    COMPLETE_RESULT_STOP_REASONS,
    MAX_AGGREGATE_RECORDS,
    aggregate_content_version,
    aggregate_fingerprint,
    build_aggregate_candidate_values,
    identified_records,
    record_identity as _record_identity,
)
_MAX_ROWS = MAX_AGGREGATE_RECORDS
logger = logging.getLogger(__name__)
_TRANSIENT_ERRORS = (ConnectionError, TimeoutError, OSError, WinHTTPError)

# 科室合并后 `_rsp_smt` 混杂，默认范围改按上级部门 `_rsp_department` 的
# 包含式 LIKE 并集；`*` 触发 `_search_elements` 的 like 条件（crawler 现有约定）。
_EWO_DEFAULT_DEPARTMENT_EXPRESSION = EWO_DEFAULT_RSP_DEPARTMENT_EXPRESSION


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_scalar(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:1000] if text else None


def _require_complete_result(result: Any) -> None:
    """Reject unknown or truncated crawler results before sync/archive writes."""
    rows = getattr(result, "rows", None)
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ValueError("external query did not return a list of row objects")
    if len(rows) > MAX_AGGREGATE_RECORDS:
        raise ValueError(
            f"external query returned more than {MAX_AGGREGATE_RECORDS} rows"
        )
    reason = str(getattr(result, "stop_reason", "unknown") or "unknown")
    if (
        getattr(result, "complete", None) is not True
        or reason not in COMPLETE_RESULT_STOP_REASONS
    ):
        raise ValueError(f"external query is incomplete ({reason})")


def _stable_version(row: Mapping[str, Any]) -> str:
    normalized = {str(key): _clean_scalar(value) for key, value in sorted(row.items())}
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _identity(row: Mapping[str, Any]) -> str:
    return _record_identity(row)


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
    analysis_rows = tuple(dict(row) for row in rows)
    if context.match_rule.get('contractVersion') is not None:
        return _ewo_v2_snapshot(context, rows, artifacts, analysis_rows)
    if context.match_rule.get("aggregate") is True:
        return _aggregate_snapshot(context, rows, artifacts, analysis_rows)
    matches = [dict(row) for row in rows if _identity(row) == context.external_key]
    fetched = _now()
    if len(matches) != 1:
        marker = hashlib.sha256(f"{len(matches)}:{context.external_key}".encode()).hexdigest()
        return ConnectorSnapshot(
            "not_found" if not matches else "ambiguous", (), marker, fetched,
            context.expected_deliverable_updated_at, artifacts, analysis_rows,
        )
    row = matches[0]
    version = _stable_version(row)
    values = _mapping_values(row, context.mapping)
    candidate = ConnectorCandidate(context.external_key, version, values, fetched)
    return ConnectorSnapshot(
        "matched", (candidate,), version, fetched,
        context.expected_deliverable_updated_at, artifacts, analysis_rows,
    )


def _ewo_v2_snapshot(context, rows, artifacts, analysis_rows):
    from core.ewo_binding_v2 import identified_ewo_v2_rows, normalize_ewo_v2_rule
    from services.ewo_binding_records import ewo_v2_candidate_values

    if context.source_type != 'aras' or context.deliverable_id != 'VPI-T2-D3':
        raise ValueError('Versioned EWO source mismatch')
    rule = normalize_ewo_v2_rule(dict(context.match_rule))
    records = identified_ewo_v2_rows(rows)
    if rule['bindingMode'] == 'single_record':
        if context.external_key != rule['sourceItemId']:
            raise ValueError('Fixed EWO source ID mismatch')
        records = [pair for pair in records if pair[0] == rule['sourceItemId']]
    fetched = _now()
    if not records:
        return ConnectorSnapshot('not_found', (), 'ewo-v2:empty', fetched,
                                 context.expected_deliverable_updated_at, artifacts, analysis_rows)
    values = ewo_v2_candidate_values(records, context.mapping, rule)
    identity = aggregate_fingerprint(records) if rule['bindingMode'] == 'record_set' else records[0][0]
    version = aggregate_content_version(records) + '|' + json.dumps(values, sort_keys=True)
    candidate = ConnectorCandidate(identity, version, values, fetched)
    return ConnectorSnapshot('matched', (candidate,), version, fetched,
                             context.expected_deliverable_updated_at, artifacts, analysis_rows)


def _mapping_values(row: Mapping[str, Any], mapping: Mapping[str, Any]) -> dict[str, str | None]:
    """按绑定映射提取字段值；note 允许列表型来源字段（多列合并）。"""
    identity = _record_identity(row)
    return build_aggregate_candidate_values([(identity, row)], mapping)


def _aggregate_snapshot(
    context: SyncBindingContext,
    rows: Sequence[Mapping[str, Any]],
    artifacts: Sequence[Mapping[str, Any]],
    analysis_rows: tuple[dict[str, Any], ...],
) -> ConnectorSnapshot:
    """按车型聚合模式：全部过滤后记录计入同一交付物（用户 2026-09-13 确认）。

    - 单条记录：按绑定映射直写（owner/plannedDate/note）。
    - 多条记录：负责人/计划完成日期不写（多记录写单值必然出错），
      仅聚合风险备注（逐条"标识：卡点信息"，未完成信息按报告原样保留，超长截断）。
    - 同步从不写 status/progress（既有限制不变）。
    """
    fetched = _now()
    # 与 discovery 口径一致（GPT 终审任务 3）：共享记录规范化——仅纳入
    # 有业务单号的记录、按单号排序（重排不变）；全部无单号 → not_found。
    identified = identified_records(rows)
    if not identified:
        marker = hashlib.sha256(b"aggregate:empty").hexdigest()
        return ConnectorSnapshot(
            "not_found", (), marker, fetched,
            context.expected_deliverable_updated_at, artifacts, analysis_rows,
        )
    record_set_fingerprint = aggregate_fingerprint(identified)
    values = build_aggregate_candidate_values(identified, context.mapping)
    # 内容版本随行内容变化（GPT 终审 P1：与记录集合指纹分离，
    # 同单号的内容变化不得被误判为幂等 skipped）。
    version = aggregate_content_version(identified) + "|" + json.dumps(values, sort_keys=True)
    candidate = ConnectorCandidate(record_set_fingerprint, version, values, fetched)
    return ConnectorSnapshot(
        "matched", (candidate,), version, fetched,
        context.expected_deliverable_updated_at, artifacts, analysis_rows,
    )


class RetryingConnector:
    def __init__(self, connector: Any, *, max_attempts: int = 2, backoff_seconds: float = 1.0, sleeper: Callable[[float], None] = time.sleep) -> None:
        if max_attempts < 1 or max_attempts > 2:
            raise ValueError("max_attempts must be between 1 and 2")
        self.connector = connector
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.sleeper = sleeper

    @observed("sync_connector.RetryingConnector.collect")
    def collect(self, context: SyncBindingContext) -> ConnectorSnapshot:
        for attempt in range(1, self.max_attempts + 1):
            try:
                return self.connector.collect(context)
            except Exception as exc:
                if not _has_transient_cause(exc):
                    raise
                if attempt >= self.max_attempts:
                    raise
                self.sleeper(self.backoff_seconds * (2 ** (attempt - 1)))
        raise AssertionError("unreachable")


def _has_transient_cause(exc: BaseException) -> bool:
    """Recognize transport exceptions wrapped by a crawler error."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, _TRANSIENT_ERRORS):
            return True
        current = current.__cause__ or current.__context__
    return False


class TDCProjectStatusConnector:
    def __init__(self, credentials: CredentialProvider, archive: ArchiveStore, *, timeout: float = 60.0, auth_factory: Callable[..., Any] = TDCPasswordAuthClient, crawler_factory: Callable[..., Any] = TDCCrawlerClient) -> None:
        self.credentials = credentials
        self.archive = archive
        self.timeout = timeout
        self.auth_factory = auth_factory
        self.crawler_factory = crawler_factory

    @observed("sync_connector.TDCProjectStatusConnector.collect")
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
                    else:
                        filters = self._sor_filters(context.match_rule)
                        result = crawler.crawl_sor_all(filters, max_records=_MAX_ROWS)
                    _require_complete_result(result)
                    official = (
                        crawler.export_data_model(filters)
                        if report == "data_model"
                        else crawler.export_sor(filters)
                    )
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
            serial_number=_clean_scalar(rule.get("processNo")),
            process_type=_clean_scalar(rule.get("processType")),
            car_type_project=_clean_scalar(rule.get("carTypeProject")),
            car_type_project_id=_clean_scalar(rule.get("carTypeProjectId")),
            applicant=_clean_scalar(rule.get("applicant")), title=_clean_scalar(rule.get("title")),
            department=_clean_scalar(rule.get("department")),
            section=_clean_scalar(rule.get("section")),
            application_start=_clean_scalar(rule.get("applicationStart")),
            application_end=_clean_scalar(rule.get("applicationEnd")),
            part_number=_clean_scalar(rule.get("partNumber")),
            part_name=_clean_scalar(rule.get("partName")),
            version=_clean_scalar(rule.get("version")),
            sor_number=_clean_scalar(rule.get("sorNumber")),
            latest_completed_node=_clean_scalar(rule.get("latestCompletedNode")),
            approval_status=_clean_scalar(rule.get("approvalStatus")),
        )


def build_project_status_ewo_filters(rule: Mapping[str, Any]) -> EWOReportFilters:
    """Build the EWO query used by both discovery and scheduled execution.

    The model-anchor path must not silently drop the other approved filters
    (notably ``subjectKeyword``).  When no department filter is configured,
    the bounded default is part of the effective query in both paths.
    """
    model_info = _clean_scalar(rule.get("modelInfo"))
    return EWOReportFilters(
        # Model-anchor execution intentionally searches the model population
        # and resolves the selected EWO key inside that result set.  Preserve
        # that established scope behavior while keeping every other approved
        # filter (including subjectKeyword) in the shared builder.
        ewo_no=None if model_info else _clean_scalar(rule.get("ewoNo")),
        project_code=_clean_scalar(rule.get("projectCode")),
        subject_keyword=_clean_scalar(rule.get("subjectKeyword")),
        change_type=_clean_scalar(rule.get("changeType")),
        change_sub_type=_clean_scalar(rule.get("changeSubType")),
        area=_clean_scalar(rule.get("area")),
        state=_clean_scalar(rule.get("state")),
        rsp_department=(
            _clean_scalar(rule.get("rspDepartment"))
            or _EWO_DEFAULT_DEPARTMENT_EXPRESSION
        ),
        rsp_smt=_clean_scalar(rule.get("rspSmt")),
        submit_start=_clean_scalar(rule.get("submitStart")),
        submit_end=_clean_scalar(rule.get("submitEnd")),
        model_info=model_info,
    )


class ArasProjectStatusConnector:
    def __init__(self, credentials: CredentialProvider, archive: ArchiveStore, *, timeout: float = 60.0, auth_factory: Callable[..., Any] = ArasECMAuthClient, crawler_factory: Callable[..., Any] = ArasCrawlerClient) -> None:
        self.credentials = credentials
        self.archive = archive
        self.timeout = timeout
        self.auth_factory = auth_factory
        self.crawler_factory = crawler_factory

    @observed("sync_connector.ArasProjectStatusConnector.collect")
    def collect(self, context: SyncBindingContext) -> ConnectorSnapshot:
        report = str(context.match_rule.get("reportType") or "ewo")
        if report != "ewo":
            raise ValueError("Aras project-status connector supports EWO only")
        with self.credentials.resolve(context.credential_ref) as secret:
            auth = self.auth_factory(timeout=self.timeout)
            login = auth.login(secret.username, secret.password)
            try:
                crawler = self.crawler_factory(auth.base_url, session=login.session, timeout=self.timeout, prewarm=False)
                filters = build_project_status_ewo_filters(context.match_rule)
                result = crawler.crawl_ewo_report_all(
                    filters, max_records=MAX_AGGREGATE_RECORDS
                )
                _require_complete_result(result)
                if context.match_rule.get('contractVersion') is not None:
                    from services.ewo_binding_records import attach_ewo_source_ids
                    from dataclasses import replace
                    result = replace(result, rows=attach_ewo_source_ids(result))
            finally:
                _close_session(login.session)
        fields = sorted({str(key) for row in result.rows for key in row})
        csv_item = self.archive.write_csv(result.rows, fields, source="aras", report="ewo", run_id=context.run_id, file_name="ewo.csv", artifact_type="csv")
        json_item = self.archive.write_json(result.rows, source="aras", report="ewo", run_id=context.run_id, file_name="ewo.json", artifact_type="json")
        return _snapshot(context, result.rows, [csv_item.as_metadata(), json_item.as_metadata()])
