"""Offline-testable Aras HTTP/AML crawler for EWO and NCR reports."""

from __future__ import annotations

import json
import random
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html import escape
from typing import Any, Mapping, Sequence
from urllib.parse import urljoin

try:
    import requests
except ModuleNotFoundError:  # pragma: no cover - exercised only in minimal test envs
    requests = None  # type: ignore[assignment]


SOAP_ROUTE = "/innovatorserver/Server/InnovatorServer.aspx"
TOKEN_ROUTE = "/innovatorserver/Server/AuthenticationBroker.asmx/GetFileDownloadToken"
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


class ArasCrawlerError(RuntimeError):
    """Raised when an Aras crawler response cannot be used."""


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
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        if session is None:
            if requests is None:
                raise ImportError("ArasCrawlerClient requires requests; install requirements.txt")
            session = requests.Session()
        self.session = session
        self.headers = dict(headers or {})
        self.timeout = timeout
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
        response = self.session.post(
            url,
            data=json.dumps({"param": {"fileId": file_id}}, separators=(",", ":")),
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return self.parse_download_token_response(response.text)

    @staticmethod
    def parse_ewo_report_response(xml_text: str) -> EWOReportPage:
        root = _parse_xml(xml_text)
        items = [item for item in root.iter() if _local_name(item.tag) == "Item" and item.get("type") == "EWO_O"]
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
        return EWOReportPage(rows=rows, page=page, item_ids=item_ids, raw_xml=xml_text)

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
        response = self.session.post(
            self._url(SOAP_ROUTE),
            data=payload,
            headers=self._headers(soap_action, "text/xml; charset=UTF-8"),
            timeout=self.timeout,
        )
        response.raise_for_status()
        if not response.text:
            raise ArasCrawlerError("Aras response is empty")
        return response

    def _headers(self, soap_action: str, content_type: str) -> dict[str, str]:
        headers = {
            "Accept": "*/*",
            "Content-Type": content_type,
            "SOAPAction": soap_action,
            "TIMEZONE_NAME": "China Standard Time",
        }
        headers.update(self.headers)
        headers["Content-Type"] = self.headers.get("Content-Type", content_type)
        headers["SOAPAction"] = soap_action
        return headers

    def _url(self, route: str) -> str:
        return urljoin(self.base_url, route.lstrip("/"))

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


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
