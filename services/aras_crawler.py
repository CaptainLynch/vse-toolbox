"""Offline-testable Aras HTTP/AML crawler for EWO and NCR reports."""

from __future__ import annotations

import json
import random
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html import escape
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urljoin, urlsplit

from core.redaction import redact_sensitive_text

try:
    import requests
except ModuleNotFoundError:  # pragma: no cover - exercised only in minimal test envs
    requests = None  # type: ignore[assignment]


SOAP_ROUTE = "Server/InnovatorServer.aspx"
CLIENT_ROUTE = "Client/default.aspx"
TOKEN_ROUTE = "Server/AuthenticationBroker.asmx/GetFileDownloadToken"
DEFAULT_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)
DEFAULT_EWO_SELECT_FIELDS = (
    "_affect_3c",
    "_affect_3c_cert",
    "_affect_appearance",
    "_affect_fe",
    "_affect_green",
    "_affect_manufacture",
    "_affect_notice",
    "_affect_online_config",
    "_affect_ots",
    "_affect_ots_time",
    "_affect_ppap",
    "_affect_ppap_time",
    "_affect_service",
    "_affect_service_type",
    "_affect_vehicle_basic_data",
    "_area",
    "_change_description",
    "_change_purpose",
    "_change_reason_description",
    "_coordinated_change",
    "_coordinated_implement_comments",
    "_coordinated_paa",
    "_coordinated_part_name",
    "_coordinated_wo",
    "_cross_reference_brief",
    "_cvcev",
    "_division",
    "_dopcpc",
    "_idle_days",
    "_is_buy",
    "_is_self_made",
    "_kdlc_strategy",
    "_m_ncr_req",
    "_m_ncr_res",
    "_mockup",
    "_modelinfo",
    "_no",
    "_project_type",
    "_ptr",
    "_required_date",
    "_road_test",
    "_rsp",
    "_rsp_department",
    "_rsp_name",
    "_rsp_phone",
    "_rsp_smt",
    "_sort_sub_type",
    "_sort_type",
    "_subject",
    "_submit_time",
    "_test_lab",
    "_vce",
    "_vehicle_param",
    "_wo_type",
    "created_on",
    "eplmwriteneplcode",
    "state",
    "created_by_id",
    "modified_by_id",
    "modified_on",
    "locked_by_id",
    "major_rev",
    "css",
    "current_state",
    "keyed_name",
    "new_version",
    "generation",
    "release_date",
    "effective_date",
    "is_current",
)
DEFAULT_PAA_SELECT_FIELDS = (
    "_affect_certificate",
    "_affect_vehicle_photo",
    "_area",
    "_auth_type",
    "_base",
    "_change_description",
    "_charge_to",
    "_days",
    "_days_or_qty",
    "_effect_consistency",
    "_emis_related",
    "_est_cmpl_date",
    "_est_cost",
    "_ewo_no",
    "_exted_reason",
    "_gacsn",
    "_idle_days",
    "_issue_date",
    "_key_part",
    "_license_tag",
    "_mass_impact",
    "_model_year",
    "_mtl_rq_date",
    "_no",
    "_pe_tdc",
    "_pe_tdc_department",
    "_pe_tdc_name",
    "_pe_tdc_phone",
    "_pe_tdc_smt",
    "_pp_comments",
    "_project_type",
    "_quantity",
    "_reason",
    "_requester_department",
    "_requester_phone",
    "_requester_smt",
    "_resp_unit",
    "_rework_place",
    "_spcl_instr",
    "_stakeholder_buy_in",
    "_stock_disp",
    "_submit_date",
    "_support_ewo_concession",
    "_validation_statement",
    "_vehicles",
    "created_on",
    "state",
    "created_by_id",
    "created_on",
    "modified_by_id",
    "modified_on",
    "locked_by_id",
    "major_rev",
    "css",
    "current_state",
    "keyed_name",
    "new_version",
    "generation",
    "release_date",
    "effective_date",
    "is_current",
)


class ArasCrawlerError(RuntimeError):
    """Raised when an Aras crawler response cannot be used."""


_SENSITIVE_NAMES = ("cook" + "ie", "authori" + "zation", "tok" + "en", "api_key", "sid", "sessionid", "cs" + "rf", "secret")
_SENSITIVE_DIAGNOSTIC_RE = re.compile(
    r"(?i)\b(" + "|".join(_SENSITIVE_NAMES) + r")\b(\s*[:=]?\s*)(?:Bearer\s+)?([^,\s;'\"}\]\[<]+)"
)
_SENSITIVE_BEARER_RE = re.compile(r"(?i)\bBearer\s+([^,\s;'\"}\]\[<]+)")


@dataclass(frozen=True)
class ArasHttpDiagnosticEvent:
    stage: str
    method: str
    url: str
    request_headers: Mapping[str, str]
    request_body: str | None = None
    status_code: int | None = None
    reason: str | None = None
    response_headers: Mapping[str, str] | None = None
    response_body: str | None = None
    elapsed_ms: float | None = None
    exception: str | None = None


@dataclass(frozen=True)
class EWOReportFilters:
    ewo_no: str | None = None
    project_code: str | None = None
    subject_keyword: str | None = None
    change_type: str | None = None
    change_sub_type: str | None = None
    area: str | None = None
    state: str | None = None
    rsp_department: str | None = None
    submit_start: str | None = None
    submit_end: str | None = None


@dataclass(frozen=True)
class PAAReportFilters:
    paa_no: str | None = None
    ewo_no: str | None = None
    state: str | None = None
    area: str | None = None
    base: str | None = None
    vehicle_keyword: str | None = None
    submit_start: str | None = None
    submit_end: str | None = None
    mtl_rq_start: str | None = None
    mtl_rq_end: str | None = None


@dataclass(frozen=True)
class NCRApprovalFilters:
    buy_start: str | None = None
    buy_end: str | None = None
    pe_start: str | None = None
    pe_end: str | None = None
    ncr_no: str | None = None
    project_names: Sequence[str] = ()
    section_code: str | None = None
    change_type: str | None = None
    othercondition: str = "0"


@dataclass(frozen=True)
class EWOReportPage:
    rows: list[dict[str, str | None]]
    page: int | None
    item_ids: list[str]
    raw_xml: str


@dataclass(frozen=True)
class PAAReportPage:
    rows: list[dict[str, str | None]]
    page: int | None
    item_ids: list[str]
    raw_xml: str


@dataclass(frozen=True)
class NCRExportResult:
    file_id: str
    file_name: str
    record_id: str
    raw_xml: str


@dataclass(frozen=True)
class NCRDetailExportResult:
    file_name: str
    raw_xml: str


class ArasCrawlerClient:
    def __init__(
        self,
        base_url: str,
        session: Any | None = None,
        headers: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: float = 30.0,
        prewarm: bool | None = None,
        diagnostic_hook: Callable[[ArasHttpDiagnosticEvent], None] | None = None,
    ) -> None:
        self.base_url = _normalize_aras_app_root(base_url)
        created_session = session is None
        if session is None:
            if requests is None:
                raise ImportError("ArasCrawlerClient requires requests; install requirements.txt")
            session = requests.Session()
            session.trust_env = False
        self.session = session
        self.headers = dict(headers or {})
        self.timeout = timeout
        self.prewarm = created_session if prewarm is None else prewarm
        self.diagnostic_hook = diagnostic_hook
        self._context_warmed = False
        if cookies:
            self.session.cookies.update(cookies)

    def query_ewo_report(
        self,
        filters: EWOReportFilters,
        page: int = 1,
        page_size: int = 50,
        max_records: int = 2000,
        select_fields: Sequence[str] | None = None,
    ) -> EWOReportPage:
        payload = self._build_ewo_payload(filters, page, page_size, max_records, select_fields)
        response = self._post_soap("ApplyItem", payload)
        return self.parse_ewo_report_response(response.text)

    def query_paa_report(
        self,
        filters: PAAReportFilters | None = None,
        page: int = 1,
        page_size: int = 50,
        max_records: int = 2000,
        select_fields: Sequence[str] | None = None,
    ) -> PAAReportPage:
        payload = self._build_paa_payload(filters or PAAReportFilters(), page, page_size, max_records, select_fields)
        response = self._post_soap("ApplyItem", payload)
        return self.parse_paa_report_response(response.text)

    def crawl_paa_report_all(
        self,
        filters: PAAReportFilters | None = None,
        page_size: int = 50,
        max_pages: int = 500,
        max_records: int = 12000,
        select_fields: Sequence[str] | None = None,
    ) -> PAAReportPage:
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        if max_pages <= 0:
            raise ValueError("max_pages must be positive")
        if max_records <= 0:
            raise ValueError("max_records must be positive")

        rows: list[dict[str, str | None]] = []
        item_ids: list[str] = []
        raw_pages: list[str] = []
        last_page: int | None = None
        page = 1
        while page <= max_pages and len(rows) < max_records:
            current = self.query_paa_report(
                filters,
                page=page,
                page_size=page_size,
                max_records=max_records,
                select_fields=select_fields,
            )
            raw_pages.append(current.raw_xml)
            if current.page is not None:
                last_page = current.page
            if not current.rows:
                break
            remaining = max_records - len(rows)
            rows.extend(current.rows[:remaining])
            item_ids.extend(current.item_ids[:remaining])
            if len(current.rows) < page_size or len(rows) >= max_records:
                break
            page += 1
        return PAAReportPage(rows=rows, page=last_page, item_ids=item_ids, raw_xml="\n".join(raw_pages))

    def query_ncr_approval_progress(self, filters: NCRApprovalFilters) -> NCRExportResult:
        payload = self._build_ncr_payload(filters, "sgmw_downloadFileProgressC")
        response = self._post_soap("ApplyMethod", payload)
        return self.parse_ncr_progress_response(response.text)

    def extract_ncr_approval_detail(self, filters: NCRApprovalFilters) -> NCRDetailExportResult:
        payload = self._build_ncr_payload(filters, "sgmw_downloadFileDetail4C")
        response = self._post_soap("ApplyMethod", payload)
        return self.parse_ncr_detail_response(response.text)

    def get_file_download_token(self, file_id: str) -> str:
        if not file_id:
            raise ValueError("file_id is required")
        url = self._url(f"{TOKEN_ROUTE}?rnd={random.random()}")
        headers = self._headers("GetFileDownloadToken", "application/json; charset=UTF-8")
        body = json.dumps({"param": {"fileId": file_id}}, separators=(",", ":"))
        started = time.perf_counter()
        try:
            response = self.session.post(
                url,
                data=body,
                headers=headers,
                timeout=self.timeout,
            )
        except Exception as exc:
            self._emit_diagnostic(
                ArasHttpDiagnosticEvent(
                    stage="download-token",
                    method="POST",
                    url=url,
                    request_headers=headers,
                    request_body=body,
                    elapsed_ms=_elapsed_ms(started),
                    exception=repr(exc),
                )
            )
            raise
        self._emit_diagnostic(_event_from_response("download-token", "POST", url, headers, body, response, started))
        if getattr(response, "status_code", 200) >= 400:
            raise ArasCrawlerError(_format_http_error(response))
        response.raise_for_status()
        return self.parse_download_token_response(response.text)

    @staticmethod
    def parse_ewo_report_response(xml_text: str) -> EWOReportPage:
        root = _parse_xml(xml_text)
        rows, item_ids, page = _parse_item_rows(root, "EWO_O")
        return EWOReportPage(rows=rows, page=page, item_ids=item_ids, raw_xml=xml_text)

    @staticmethod
    def parse_paa_report_response(xml_text: str) -> PAAReportPage:
        root = _parse_xml(xml_text)
        result = next((node for node in root.iter() if _local_name(node.tag) == "Result"), None)
        if result is None:
            raise ArasCrawlerError("PAA response does not contain Result")
        rows, item_ids, page = _parse_item_rows(result, "PAA_O")
        return PAAReportPage(rows=rows, page=page, item_ids=item_ids, raw_xml=xml_text)

    @staticmethod
    def parse_ncr_progress_response(xml_text: str) -> NCRExportResult:
        root = _parse_xml(xml_text)
        item = next(
            (node for node in root.iter() if _local_name(node.tag) == "Item" and node.get("type") == "sgmw_outputFileRecord"),
            None,
        )
        if item is None:
            raise ArasCrawlerError("NCR progress response does not contain sgmw_outputFileRecord")
        file_node = next((child for child in list(item) if _local_name(child.tag) == "_file"), None)
        if file_node is None or not (file_node.text or "").strip():
            raise ArasCrawlerError("NCR progress response does not contain _file id")
        return NCRExportResult(
            file_id=(file_node.text or "").strip(),
            file_name=file_node.get("keyed_name", ""),
            record_id=item.get("id", ""),
            raw_xml=xml_text,
        )

    @staticmethod
    def parse_ncr_detail_response(xml_text: str) -> NCRDetailExportResult:
        root = _parse_xml(xml_text)
        result = next((node for node in root.iter() if _local_name(node.tag) == "Result"), None)
        file_name = (result.text or "").strip() if result is not None else ""
        if not file_name:
            raise ArasCrawlerError("NCR detail response does not contain a file name")
        return NCRDetailExportResult(file_name=file_name, raw_xml=xml_text)

    @staticmethod
    def parse_download_token_response(json_text: str) -> str:
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise ArasCrawlerError("download token response is not valid JSON") from exc
        token = data.get("d")
        if not isinstance(token, str) or not token:
            raise ArasCrawlerError("download token response does not contain d")
        return token

    def _post_soap(self, soap_action: str, payload: str) -> Any:
        self._prewarm_context()
        url = self._url(SOAP_ROUTE)
        headers = self._headers(soap_action, "text/xml; charset=UTF-8")
        started = time.perf_counter()
        try:
            response = self.session.post(
                url,
                data=payload,
                headers=headers,
                timeout=self.timeout,
            )
        except Exception as exc:
            self._emit_diagnostic(
                ArasHttpDiagnosticEvent(
                    stage=f"soap-{soap_action}",
                    method="POST",
                    url=url,
                    request_headers=headers,
                    request_body=payload,
                    elapsed_ms=_elapsed_ms(started),
                    exception=repr(exc),
                )
            )
            raise
        self._emit_diagnostic(_event_from_response(f"soap-{soap_action}", "POST", url, headers, payload, response, started))
        if getattr(response, "status_code", 200) >= 400:
            raise ArasCrawlerError(_format_http_error(response))
        response.raise_for_status()
        if not response.text:
            raise ArasCrawlerError("Aras response is empty")
        return response

    def _prewarm_context(self) -> None:
        if not self.prewarm or self._context_warmed:
            return
        headers = self._browser_headers("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
        headers.update(self.headers)
        url = self._url(CLIENT_ROUTE)
        started = time.perf_counter()
        try:
            response = self.session.get(
                url,
                headers=headers,
                timeout=self.timeout,
            )
        except Exception as exc:
            self._emit_diagnostic(
                ArasHttpDiagnosticEvent(
                    stage="prewarm",
                    method="GET",
                    url=url,
                    request_headers=headers,
                    elapsed_ms=_elapsed_ms(started),
                    exception=repr(exc),
                )
            )
            raise
        self._emit_diagnostic(_event_from_response("prewarm", "GET", url, headers, None, response, started))
        if getattr(response, "status_code", 200) >= 400:
            raise ArasCrawlerError(f"Aras context warmup failed: {_format_http_error(response)}")
        response.raise_for_status()
        self._context_warmed = True

    def _headers(self, soap_action: str, content_type: str) -> dict[str, str]:
        headers = self._browser_headers("*/*")
        headers.update(
            {
            "Content-Type": content_type,
            "SOAPAction": soap_action,
            "TIMEZONE_NAME": "China Standard Time",
            }
        )
        headers.update(self.headers)
        headers["Content-Type"] = self.headers.get("Content-Type", content_type)
        headers["SOAPAction"] = soap_action
        return headers

    def _browser_headers(self, accept: str) -> dict[str, str]:
        origin = self._origin()
        return {
            "Accept": accept,
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Connection": "keep-alive",
            "Origin": origin,
            "Referer": self._url(CLIENT_ROUTE),
            "User-Agent": DEFAULT_BROWSER_USER_AGENT,
        }

    def _url(self, route: str) -> str:
        return urljoin(self.base_url, route.lstrip("/"))

    def _origin(self) -> str:
        parsed = urlsplit(self.base_url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
        return self.base_url.rstrip("/")

    def _emit_diagnostic(self, event: ArasHttpDiagnosticEvent) -> None:
        if self.diagnostic_hook is None:
            return
        self.diagnostic_hook(event)

    def _build_ewo_payload(
        self,
        filters: EWOReportFilters,
        page: int,
        page_size: int,
        max_records: int,
        select_fields: Sequence[str] | None,
    ) -> str:
        select = ",".join(select_fields or DEFAULT_EWO_SELECT_FIELDS)
        attrs = (
            f'type="EWO_O" action="get" page="{page}" select="{escape(select)}" '
            f'pagesize="{page_size}" maxRecords="{max_records}" returnMode="itemsOnly"'
        )
        children = [
            _element("_no", filters.ewo_no),
            _element("eplmwriteneplcode", filters.project_code),
            _element("_subject", filters.subject_keyword, condition="like"),
            _element("_sort_type", filters.change_type),
            _element("_sort_sub_type", filters.change_sub_type),
            _element("_area", filters.area, condition="like"),
            _element("state", filters.state),
            _element("_rsp_department", filters.rsp_department),
            _element("_submit_time", filters.submit_start, condition="ge"),
            _element("_submit_time", filters.submit_end, condition="le"),
        ]
        body = "".join(child for child in children if child)
        return _soap_envelope(f"<ApplyItem><Item {attrs}>{body}</Item></ApplyItem>")

    def _build_paa_payload(
        self,
        filters: PAAReportFilters,
        page: int,
        page_size: int,
        max_records: int,
        select_fields: Sequence[str] | None,
    ) -> str:
        select = ",".join(select_fields or DEFAULT_PAA_SELECT_FIELDS)
        attrs = (
            f'type="PAA_O" action="get" page="{page}" select="{escape(select)}" '
            f'pagesize="{page_size}" maxRecords="{max_records}" returnMode="itemsOnly"'
        )
        children = [
            _element("_no", filters.paa_no),
            _element("_ewo_no", filters.ewo_no),
            _element("state", filters.state),
            _element("_area", filters.area, condition="like"),
            _element("_base", filters.base, condition="like"),
            _element("_vehicles", filters.vehicle_keyword, condition="like"),
            _element("_submit_date", filters.submit_start, condition="ge"),
            _element("_submit_date", filters.submit_end, condition="le"),
            _element("_mtl_rq_date", filters.mtl_rq_start, condition="ge"),
            _element("_mtl_rq_date", filters.mtl_rq_end, condition="le"),
        ]
        body = "".join(child for child in children if child)
        if body:
            return _soap_envelope(f"<ApplyItem><Item {attrs}>{body}</Item></ApplyItem>")
        return _soap_envelope(f"<ApplyItem><Item {attrs}/></ApplyItem>")

    def _build_ncr_payload(self, filters: NCRApprovalFilters, method_action: str) -> str:
        project_names = ",".join(filters.project_names)
        nodes = (
            ("buystart", filters.buy_start),
            ("buyend", filters.buy_end),
            ("pestart", filters.pe_start),
            ("peend", filters.pe_end),
            ("ncrno", filters.ncr_no),
            ("ncrname", project_names),
            ("seccode", filters.section_code),
            ("changetype", filters.change_type),
            ("othercondition", filters.othercondition),
        )
        body = "".join(f"<{name}><![CDATA[{_cdata(value or '')}]]></{name}>" for name, value in nodes)
        return _soap_envelope(f'<ApplyMethod><Item type="Method" action="{method_action}">{body}</Item></ApplyMethod>')


def _parse_item_rows(root: ET.Element, item_type: str) -> tuple[list[dict[str, str | None]], list[str], int | None]:
    items = [item for item in root.iter() if _local_name(item.tag) == "Item" and item.get("type") == item_type]
    if not items and item_type == "EWO_O":
        return [], [], None
    if not items and item_type == "PAA_O":
        return [], [], None
    rows: list[dict[str, str | None]] = []
    item_ids: list[str] = []
    page: int | None = None
    for item in items:
        if item.get("id"):
            item_ids.append(item.get("id", ""))
        if page is None and item.get("page"):
            page = int(item.get("page", "0"))
        row: dict[str, str | None] = {}
        for child in list(item):
            row[_local_name(child.tag)] = None if child.get("is_null") == "1" else child.text
        rows.append(row)
    return rows, item_ids, page


def _soap_envelope(body: str) -> str:
    return (
        '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" >'
        f"<SOAP-ENV:Body>{body}</SOAP-ENV:Body></SOAP-ENV:Envelope>"
    )


def _element(name: str, value: str | None, condition: str | None = None) -> str:
    if value is None or value == "":
        return ""
    attr = f' condition="{condition}"' if condition else ""
    return f"<{name}{attr}>{escape(value)}</{name}>"


def _cdata(value: str) -> str:
    return value.replace("]]>", "]]]]><![CDATA[>")


def _parse_xml(xml_text: str) -> ET.Element:
    if not xml_text:
        raise ArasCrawlerError("XML response is empty")
    try:
        return ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ArasCrawlerError("XML response is not valid") from exc


def _format_http_error(response: Any) -> str:
    status = getattr(response, "status_code", "unknown")
    reason = getattr(response, "reason", "")
    url = getattr(response, "url", "")
    snippet = _redact_diagnostic(str(getattr(response, "text", "") or "").strip()) or "<empty response body>"
    location = f" for {url}" if url else ""
    suffix = f" {reason}" if reason else ""
    message = f"Aras HTTP {status}{suffix}{location}: {snippet}"
    if str(status) == "401" and _response_requires_bearer(response):
        message += (
            " | Authentication hint: missing or expired Authorization Bearer token. "
            "Copy the Authorization header from a successful InnovatorServer.aspx browser request."
        )
    return message


def _response_requires_bearer(response: Any) -> bool:
    headers = getattr(response, "headers", {}) or {}
    try:
        authenticate = headers.get("WWW-Authenticate", "")
    except AttributeError:
        authenticate = ""
    return "bearer" in str(authenticate).lower()


def _event_from_response(
    stage: str,
    method: str,
    url: str,
    request_headers: Mapping[str, str],
    request_body: str | None,
    response: Any,
    started: float,
) -> ArasHttpDiagnosticEvent:
    return ArasHttpDiagnosticEvent(
        stage=stage,
        method=method,
        url=url,
        request_headers=dict(request_headers),
        request_body=request_body,
        status_code=getattr(response, "status_code", None),
        reason=getattr(response, "reason", None),
        response_headers=dict(getattr(response, "headers", {}) or {}),
        response_body=getattr(response, "text", None),
        elapsed_ms=_elapsed_ms(started),
    )


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _normalize_aras_app_root(base_url: str) -> str:
    cleaned = base_url.strip()
    if not cleaned:
        return ""
    if not cleaned.endswith("/"):
        cleaned += "/"
    lowered = cleaned.lower()
    marker = "/innovatorserver/"
    marker_index = lowered.find(marker)
    if marker_index >= 0:
        return cleaned[: marker_index + len(marker)]
    return urljoin(cleaned, "innovatorserver/")


def _redact_diagnostic(message: str) -> str:
    message = redact_sensitive_text(message)
    message = _SENSITIVE_DIAGNOSTIC_RE.sub(r"\1\2[redacted]", message)
    return _SENSITIVE_BEARER_RE.sub("Bearer [redacted]", message)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
