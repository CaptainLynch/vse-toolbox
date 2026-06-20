# P1 Intranet Crawler Contract - EWO / NCR

Scope: Phase 2 HAR reverse engineering based only on offline samples under `E:\project\vse-toolbox\crawl source`. This document is the implementation contract for the P1 crawler Worker. It must not be treated as permission to call the real intranet during tests.

## 1. Offline Sources Read

- `E:\project\vse-toolbox\crawl source\ecm.sgmw.com.cn-EWO明细.har`
- `E:\project\vse-toolbox\crawl source\ecm.sgmw.com.cn-NCR审批进度.har`
- `E:\project\vse-toolbox\crawl source\ecm.sgmw.com.cn-NCR审批明细.har`
- Local workbook/header evidence: `columns.txt`, `head_detail.json`, `head_detail.txt`

Sensitive-value handling:
- No request `Cookie` or `Authorization` header was present in the three key SOAP requests in these HAR files.
- Response CORS headers allow `api_key` and `Authorization`; production callers may still need to inject those headers.
- A download token appears in the NCR progress token response and vault URL. The real token value must never be committed to docs, source, or tests; use `<download_token>` or a generated fake token in fixtures.

## 2. Shared Aras HTTP Contract

Base endpoints:

| Purpose | Method | Route |
| --- | --- | --- |
| SOAP / AML operations | `POST` | `/innovatorserver/Server/InnovatorServer.aspx` |
| File download token | `POST` | `/innovatorserver/Server/AuthenticationBroker.asmx/GetFileDownloadToken?rnd=<random>` |
| Vault file download | `HEAD` / `GET` | `/innovatorserver/vault/vaultserver.aspx?...&token=<download_token>&...` |

Common SOAP headers:

| Header | Required | Value / Source |
| --- | --- | --- |
| `Accept` | yes | `*/*` |
| `Content-Type` | yes | `text/xml; charset=UTF-8` |
| `SOAPAction` | yes | `ApplyItem`, `ApplyMethod`, `GetItem`, etc. |
| `TIMEZONE_NAME` | yes | usually `China Standard Time` |
| `Origin` | usually | caller-provided base origin |
| `Referer` | usually | caller-provided Aras client page |
| `User-Agent` | optional | caller-provided |
| `Cookie` | environment-dependent | caller-provided `<cookie>`, never hardcoded |
| `Authorization` / `api_key` | environment-dependent | caller-provided `<authorization>` / `<api_key>`, never hardcoded |

Implementation requirement:
- The service must accept a caller-supplied `requests.Session` or create a new one without credentials.
- All auth material must enter through explicit `headers` / `cookies` arguments or an already-authenticated `Session`.
- No sample token, session, cookie, or authorization value may be embedded in production code.
- Unit tests must mock `Session.post`, `Session.head`, and `Session.get`; they must not reach `ecm.sgmw.com.cn` or any external host.

Suggested shared constructor:

```python
class ArasCrawlerClient:
    def __init__(
        self,
        base_url: str,
        session: requests.Session | None = None,
        headers: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None: ...
```

`headers` is merged into the common SOAP/token headers. `cookies` is injected into the `Session` or passed per request. The caller owns the source of credentials.

## 3. Capability A - EWO Report Filter Query

HAR evidence:
- File: `ecm.sgmw.com.cn-EWO明细.har`
- Entry: first `POST /InnovatorServer.aspx`
- SOAPAction: `ApplyItem`
- AML: `<Item type="EWO_O" action="get" page="1" pagesize="50" maxRecords="2000" returnMode="itemsOnly" select="..."/>`

Suggested service signature:

```python
def query_ewo_report(
    filters: EWOReportFilters,
    page: int = 1,
    page_size: int = 50,
    max_records: int = 2000,
    select_fields: Sequence[str] | None = None,
) -> EWOReportPage: ...
```

Suggested filter type:

```python
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
```

Parameter mapping:

| Public parameter | AML field | Evidence level |
| --- | --- | --- |
| `page` | `Item@page` | HAR-proven |
| `page_size` | `Item@pagesize` | HAR-proven |
| `max_records` | `Item@maxRecords` | HAR-proven |
| `select_fields` | `Item@select` | HAR-proven |
| `ewo_no` | child `<_no>` | inferred from selected/returned field |
| `project_code` | child `<eplmwriteneplcode>` | inferred from selected/returned field |
| `subject_keyword` | child `<_subject condition="like">` | inferred from selected/returned field and AML convention |
| `change_type` | child `<_sort_type>` | inferred from selected/returned field |
| `change_sub_type` | child `<_sort_sub_type>` | inferred from selected/returned field |
| `area` | child `<_area condition="like">` | inferred from selected/returned field and AML convention |
| `state` | child `<state>` | inferred from selected/returned field |
| `rsp_department` | child `<_rsp_department>` | inferred from selected/returned field |
| `submit_start` / `submit_end` | child `<_submit_time condition="ge/le">` | inferred from selected/returned field and AML convention |

Default `select_fields` must match the HAR-proven list unless the caller overrides it:

```text
_affect_3c,_affect_3c_cert,_affect_appearance,_affect_fe,_affect_green,
_affect_manufacture,_affect_notice,_affect_online_config,_affect_ots,
_affect_ots_time,_affect_ppap,_affect_ppap_time,_affect_service,
_affect_service_type,_affect_vehicle_basic_data,_area,_change_description,
_change_purpose,_change_reason_description,_coordinated_change,
_coordinated_implement_comments,_coordinated_paa,_coordinated_part_name,
_coordinated_wo,_cross_reference_brief,_cvcev,_division,_dopcpc,_idle_days,
_is_buy,_is_self_made,_kdlc_strategy,_m_ncr_req,_m_ncr_res,_mockup,
_modelinfo,_no,_project_type,_ptr,_required_date,_road_test,_rsp,
_rsp_department,_rsp_name,_rsp_phone,_rsp_smt,_sort_sub_type,_sort_type,
_subject,_submit_time,_test_lab,_vce,_vehicle_param,_wo_type,created_on,
eplmwriteneplcode,state,created_by_id,modified_by_id,modified_on,
locked_by_id,major_rev,css,current_state,keyed_name,new_version,generation,
release_date,effective_date,is_current
```

Response structure:
- XML: `SOAP-ENV:Envelope/SOAP-ENV:Body/Result/Item`.
- Each `Item` has attributes `type="EWO_O"`, `typeId`, `id`, `page`.
- Children are the selected EWO fields. Null values may appear as elements with `is_null="1"`.
- Parser output should normalize to `list[dict[str, str | None]]` plus `page`, `item_ids`, and raw XML for audit/debug fixtures.

Pagination:
- Request controls are `page`, `pagesize`, `maxRecords`.
- The sample does not prove total-count metadata. Worker should page until fewer than `page_size` items are returned, or stop at `max_records`.

## 4. Capability B - NCR Approval Progress Query

HAR evidence:
- File: `ecm.sgmw.com.cn-NCR审批进度.har`
- Entry 1: optional project lookup, `ApplyItem` on `Item type="NCR Project" action="get" orderBy="name asc"`.
- Entry 2: export request, `ApplyMethod` on `Method action="sgmw_downloadFileProgressC"`.
- Entries 3-9: file metadata, token, and vault file access chain.

Suggested service signature:

```python
def query_ncr_approval_progress(filters: NCRApprovalFilters) -> NCRExportResult: ...
```

Suggested filter type:

```python
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
```

Payload mapping:

| Public parameter | XML node | Sample value |
| --- | --- | --- |
| `buy_start` | `<buystart><![CDATA[...]]></buystart>` | blank |
| `buy_end` | `<buyend><![CDATA[...]]></buyend>` | blank |
| `pe_start` | `<pestart><![CDATA[...]]></pestart>` | blank |
| `pe_end` | `<peend><![CDATA[...]]></peend>` | blank |
| `ncr_no` | `<ncrno><![CDATA[...]]></ncrno>` | blank |
| `project_names` | `<ncrname><![CDATA[name1,name2]]></ncrname>` | `F610S,F610S DG` |
| `section_code` | `<seccode><![CDATA[...]]></seccode>` | blank |
| `change_type` | `<changetype><![CDATA[...]]></changetype>` | blank |
| `othercondition` | `<othercondition><![CDATA[...]]></othercondition>` | `0` |

Response structure:
- XML: `Envelope/Body/Result/Item type="sgmw_outputFileRecord"`.
- `Item/_file` text is `<file_id>`; `_file@keyed_name` is the generated xlsx file name.
- Additional metadata includes `created_on`, `modified_on`, `itemtype`, `config_id`, and `permission_id`.
- Parser output should return `file_id`, `file_name`, `record_id`, and raw XML.

Download chain contract:
- `get_file_download_token(file_id: str) -> str` calls `AuthenticationBroker.asmx/GetFileDownloadToken?rnd=<random>` with JSON body `{"param":{"fileId":"<file_id>"}}` and `Content-Type: application/json; charset=UTF-8`.
- Response JSON shape is `{"d":"<download_token>"}`. Never persist or log the real value.
- Vault URL query parameters are `dbName`, `fileId`, `fileName`, `vaultId`, `token`, `contentDispositionAttachment`.
- Production download is allowed only when the caller explicitly opts in. Tests use mocked bytes or local xlsx samples.

## 5. Capability C - NCR Approval Detail Extraction

HAR evidence:
- File: `ecm.sgmw.com.cn-NCR审批明细.har`
- Entry 1: `POST /InnovatorServer.aspx`
- SOAPAction: `ApplyMethod`
- AML: `<Item type="Method" action="sgmw_downloadFileDetail4C">...same filters...</Item>`

Suggested service signature:

```python
def extract_ncr_approval_detail(filters: NCRApprovalFilters) -> NCRDetailExportResult: ...
```

Payload mapping:
- Same XML nodes and public `NCRApprovalFilters` mapping as the progress query.
- Only the method action changes from `sgmw_downloadFileProgressC` to `sgmw_downloadFileDetail4C`.

Response structure:
- XML: `Envelope/Body/Result`.
- `Result` text is the generated xlsx file name.
- This HAR does not include the subsequent file-id/token chain. Worker should parse the returned file name and expose `file_name`; if later samples prove the download chain, add it as an explicit opt-in method.

Local workbook shape:
- `columns.txt` shows progress workbook headers such as `状态`, `序号`, `提交日期`, `项目`, `NCR编号`, approval-node columns, `当前审批人`, `当前审批人滞留天数`, `备注`, and downstream buyer/status fields.
- `head_detail.json` shows detail workbook columns such as `状态`, `变更序号`, `提交日期`, `项目`, `更改主题`, `NCR编号`, `当前节点`, part fields, cost fields, `EWO号`, procurement fields, SAP/JPC fields, and `RC_ID`.
- Workbook parsing must be local-only and fixture-driven in this phase.

## 6. Offline Fixture Strategy

Worker must create fixtures from HAR `response.content.text`, not from real HTTP calls:

- `tests/fixtures/crawler/ewo_query_response.xml`: raw XML from the EWO `EWO_O` response, unless it contains newly discovered sensitive material.
- `tests/fixtures/crawler/ncr_project_lookup_response.xml`: raw XML from NCR project lookup response.
- `tests/fixtures/crawler/ncr_progress_response.xml`: raw XML from `sgmw_downloadFileProgressC`.
- `tests/fixtures/crawler/ncr_detail_response.xml`: raw XML from `sgmw_downloadFileDetail4C`.
- `tests/fixtures/crawler/download_token_response.json`: sanitized JSON shape with `{"d":"<download_token>"}` or a fake token, never the real HAR token.

Tests must verify:
- Request XML builders produce the exact route, method, SOAPAction, pagination attributes, and XML node names above.
- Parser functions extract EWO item rows, NCR progress `file_id/file_name`, NCR detail `file_name`, and token JSON shape.
- Mocked `requests.Session` records calls but performs no network I/O.
- A static guard fails if crawler tests attempt to call `requests.post/get/head` directly or if fixture/doc/source files contain known sensitive key names with real-looking values.
