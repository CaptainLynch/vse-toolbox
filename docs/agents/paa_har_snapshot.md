# PAA HAR Baseline Snapshot

Scope: read-only exploration of `crawl source` HAR artifacts for PAA pagination behavior.

## 1) PAA-related HAR files

| Absolute path | Size | Last modified |
|---|---:|---|
| `E:\project\vse-toolbox\crawl source\ecm.sgmw.com.cn-PAA.har` | 199,163 bytes | 2026-06-21 00:35:48 |
| `E:\project\vse-toolbox\crawl source\ecm.sgmw.com.cn-PAA1.har` | 56,961 bytes | 2026-06-21 00:57:34 |

Notes:
- This folder also contains `EWO` and `NCR` HAR files, but this snapshot is scoped to the PAA artifacts only.
- No real HTTP requests were sent.

## 2) HAR entry inventory

`PAA.har` contains 3 POST entries, all to:

- Host: `ecm.sgmw.com.cn`
- Path: `/innovatorserver/Server/InnovatorServer.aspx`

Entry summary:

1. `POST 200 text/xml` - core `PAA_O get` list query
2. `POST 200 text/xml` - `Favorite` lookup, returned SOAP fault
3. `POST 200 text/xml` - duplicate `Favorite` lookup, returned SOAP fault

Only entry 1 is relevant for the crawler baseline.

`PAA1.har` contains 4 POST entries. The key delta is entry 1:

- Method: `POST`
- URL: `http://ecm.sgmw.com.cn/innovatorserver/Server/InnovatorServer.aspx`
- Status: `200`
- Response mimeType: `text/xml`
- SOAPAction: `ApplyItem`
- Request payload: `PAA_O get`
- `page="1"`
- `pagesize="12000"`
- `maxRecords="12000"`
- `returnMode="itemsOnly"`

The recorded HAR has no response text for that entry, so it is best treated as a request-side baseline for the large-fetch path rather than a completed payload sample.

## 3) Core POST entry

### Request metadata

- Method: `POST`
- URL: `http://ecm.sgmw.com.cn/innovatorserver/Server/InnovatorServer.aspx`
- Status: `200`
- Response mimeType: `text/xml`
- SOAPAction: `ApplyItem`
- Content-Type: `text/xml; charset=UTF-8`

### Presence checks

- `<SOAP-ENV:Envelope>`: yes
- `Item type="PAA_O" action="get"`: yes
- `page`: yes, `page="1"`
- `pagesize`: yes, `pagesize="50"`
- `maxRecords`: yes, `maxRecords="2000"`
- `select`: yes, long field projection list

### Request headers, sanitized

No sensitive values were present in the captured headers. The request headers were:

- `Accept`
- `Accept-Encoding`
- `Accept-Language`
- `Connection`
- `Content-Length`
- `Content-Type`
- `Host`
- `Origin`
- `Referer`
- `SOAPAction`
- `TIMEZONE_NAME`
- `User-Agent`

No `Cookie`, `Authorization`, `Set-Cookie`, `token`, `session`, or `csrf` headers were present.

### Sanitized request payload template

```xml
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">
  <SOAP-ENV:Body>
    <ApplyItem>
      <Item
        type="PAA_O"
        action="get"
        page="1"
        select="_affect_certificate,_affect_vehicle_photo,_area,_auth_type,_base,_change_description,_charge_to,_days,_days_or_qty,_effect_consistency,_emis_related,_est_cmpl_date,_est_cost,_ewo_no,_exted_reason,_gacsn,_idle_days,_issue_date,_key_part,_license_tag,_mass_impact,_model_year,_mtl_rq_date,_no,_pe_tdc,_pe_tdc_department,_pe_tdc_name,_pe_tdc_phone,_pe_tdc_smt,_pp_comments,_project_type,_quantity,_reason,_requester_department,_requester_phone,_requester_smt,_resp_unit,_rework_place,_spcl_instr,_stakeholder_buy_in,_stock_disp,_submit_date,_support_ewo_concession,_validation_statement,_vehicles,created_on,state,created_by_id,created_on,modified_by_id,modified_on,locked_by_id,major_rev,css,current_state,keyed_name,new_version,generation,release_date,effective_date,is_current"
        pagesize="50"
        maxRecords="2000"
        returnMode="itemsOnly"
      />
    </ApplyItem>
  </SOAP-ENV:Body>
</SOAP-ENV:Envelope>
```

## 4) Response structure

The response is a SOAP envelope with a `<Result>` block containing 50 `PAA_O` items.

### Response head

```xml
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">
  <SOAP-ENV:Body>
    <Result>
      <Item type="PAA_O" typeId="AB78E8D480754234925C19962AD62A4D" id="9638699D94724411A70031BF2FA44CEE" page="1">
        ...
      </Item>
```

### Example `PAA_O` item shape

The first item in the page includes fields such as:

- `_area`
- `_base`
- `_change_description`
- `_ewo_no`
- `_mtl_rq_date`
- `_pe_tdc`
- `_requester_department`
- `_reason`
- `_submit_date`
- `_support_ewo_concession`
- `_vehicles`
- `created_by_id`
- `created_on`
- `current_state`
- `id`
- `keyed_name`
- `modified_by_id`
- `modified_on`
- `state`
- `_no`

Observed values in the sample item show the typical `PAA_O` record structure and confirm the page carries full business payload fields, not just lightweight summary metadata.

### Response tail

The last item in the captured response is another `PAA_O` record on `page="1"` and the response ends directly after the 50th item, with no obvious total-count or next-page marker in the XML body.

### `PAA1.har` note

The `PAA1` capture suggests a bulk-load branch:

- It asks for `12000` rows in a single request.
- The captured HAR does not preserve the response body for that entry.
- The surrounding `Favorite` entries remain noise and should not be used as paging signals.

## 5) Phase 2 architect notes

Recommended pagination strategy:

1. Prefer explicit page iteration driven by `page` and `pagesize`.
2. Treat a page as exhausted when the returned `Result` contains fewer `PAA_O` items than the requested `pagesize`.
3. If the server always returns a full page, use stable dedupe by `id` / `keyed_name` / `_no` across pages as a secondary stop check.
4. Inspect whether the upstream UI or API exposes an additional total count elsewhere before relying on open-ended page walking.
5. For the `PAA1` path, confirm whether the app is deliberately switching from paging to a single-shot bulk fetch via `pagesize=maxRecords=12000`.

Likely parser fields to retain:

- `id`
- `keyed_name`
- `_no`
- `state`
- `current_state`
- `created_on`
- `modified_on`
- `_submit_date`
- `_mtl_rq_date`
- `_ewo_no`
- `_vehicles`
- `_base`
- `_area`
- `_reason`

Risk points:

- The `select` projection is long and may change; parse defensively.
- The response is a large SOAP XML blob; avoid assuming one item per line or clean indentation.
- Any future crawl that includes authentication may expose cookies or session-like values; redact by key name only.
- The HAR currently includes `Favorite` fault traffic that should not be mistaken for the crawler's main list query.
- `PAA1.har` currently lacks a response body for the big request, so a future capture should confirm whether the server actually returns all rows or the browser discarded the payload.

