# P1 Crawl Source Baseline Index

Scope: read-only index of `E:\project\vse-toolbox\crawl source` sample pool plus `services/` crawler/HTTP/Feishu/Office related skeletons.

## 1) Sample inventory

| Path | Size | Modified | Type | Likely use |
| --- | ---: | --- | --- | --- |
| `E:\project\vse-toolbox\crawl source\ecm.sgmw.com.cn-EWO明细.har` | 210,956 B | 2026-06-20 01:58:26 | HAR | EWO detail / report export baseline |
| `E:\project\vse-toolbox\crawl source\ecm.sgmw.com.cn-NCR审批进度.har` | 98,009 B | 2026-06-20 02:12:14 | HAR | NCR progress / status query baseline |
| `E:\project\vse-toolbox\crawl source\ecm.sgmw.com.cn-NCR审批明细.har` | 9,927 B | 2026-06-20 02:20:19 | HAR | NCR detail extraction baseline |
| `E:\project\vse-toolbox\crawl source\SGMW工程变更审批-EWO.html` | 70,603 B | 2026-06-19 23:51:40 | HTML | Offline mirror of EWO app shell |
| `E:\project\vse-toolbox\crawl source\SGMW工程变更审批-NCR.html` | 71,054 B | 2026-06-19 23:52:14 | HTML | Offline mirror of NCR app shell |
| `E:\project\vse-toolbox\crawl source\NCR审批进度查询表 20260620 021152.892.xlsx` | 117,384 B | 2026-06-20 02:11:59 | XLSX | Generated progress export artifact |
| `E:\project\vse-toolbox\crawl source\NCR审批明细查询表_5d5aed49-1963-452c-a329-71aaf93a66c3.xlsx` | 822,981 B | 2026-06-20 02:19:57 | XLSX | Generated detail export artifact |

Other sample-like content observed:
- `E:\project\vse-toolbox\crawl source\SGMW工程变更审批_EWO_files\...`
- `E:\project\vse-toolbox\crawl source\SGMW工程变更审批-NCR_files\...`

These folders contain mirrored JS/CSS/HTML/assets and are the strongest offline-shell evidence for both flows.

## 2) HAR entry summaries

### `ecm.sgmw.com.cn-EWO明细.har`

1. `POST http://ecm.sgmw.com.cn/innovatorserver/Server/InnovatorServer.aspx`
   - Status: `200 OK`
   - mimeType: `text/xml`
   - Response inline: yes
   - Keywords: `EWO`, `NCR`
   - Request body: `ApplyItem` on `Item type="EWO_O" action="get"` with large `select` list
   - Response body: `Result/Item type="EWO_O"` with many `_affect_*` fields and EWO data
   - Sensitive headers observed: none in this entry; no cookie/authorization values surfaced

2. `POST http://ecm.sgmw.com.cn/innovatorserver/Server/InnovatorServer.aspx`
   - Status: `200 OK`
   - mimeType: `text/xml`
   - Response inline: yes
   - Keywords: `EWO`
   - Request body: `ApplyItem` on `Item type="Favorite"` with `context_type>EWO_O<`
   - Response body: fault, `No items of type Favorite found.`

3. `POST http://ecm.sgmw.com.cn/innovatorserver/Server/InnovatorServer.aspx`
   - Status: `200 OK`
   - mimeType: `text/xml`
   - Response inline: yes
   - Keywords: `EWO`
   - Request body: repeat of Favorite lookup for `EWO_O`
   - Response body: same fault as above

### `ecm.sgmw.com.cn-NCR审批进度.har`

1. `POST http://ecm.sgmw.com.cn/innovatorserver/Server/InnovatorServer.aspx`
   - Status: `200 OK`
   - mimeType: `text/xml`
   - Response inline: yes
   - Keywords: `NCR`
   - Request body: `ApplyItem` on `Item type="NCR Project" action="get" orderBy="name asc"` with `_belongepl=F610S`
   - Response body: NCR project metadata; includes `created_by_id`, `current_state`, `config_id`, etc.

2. `POST http://ecm.sgmw.com.cn/innovatorserver/Server/InnovatorServer.aspx`
   - Status: `200 OK`
   - mimeType: `text/xml`
   - Response inline: yes
   - Keywords: `NCR`, `审批`, `进度`
   - Request body: `ApplyMethod` on `Method action="sgmw_downloadFileProgressC"` with filters:
     - `ncrname = F610S,F610S DG`
     - most other filters blank
     - `othercondition = 0`
   - Response body: `sgmw_outputFileRecord` with file name `NCR审批进度查询表 20260620 021152.892.xlsx`

3. `POST http://ecm.sgmw.com.cn/innovatorserver/Server/InnovatorServer.aspx`
   - Status: `200 OK`
   - mimeType: `text/xml`
   - Response inline: yes
   - Keywords: none explicitly in path, but linked to NCR export flow
   - Request body: `GetItem` for `File id="68C519069E974AADA15ABEB4A7277BC5"`
   - Response body: file metadata, including vault placement

4. `POST http://ecm.sgmw.com.cn/innovatorserver/Server/InnovatorServer.aspx`
   - Status: `200 OK`
   - mimeType: `text/xml`
   - Response inline: yes
   - Keywords: none explicitly
   - Request body: `getItemRelationships` for `File relName="Located"`
   - Response body: vault relationship / version info

5. `POST http://ecm.sgmw.com.cn/innovatorserver/Server/InnovatorServer.aspx`
   - Status: `200 OK`
   - mimeType: `text/xml`
   - Response inline: yes
   - Keywords: none explicitly
   - Request body: `ApplyItem` on `User action="get"` with `select="default_vault"` and `ReadPriority` relationship
   - Response body: user default vault and related access structure

6. `POST http://ecm.sgmw.com.cn/innovatorserver/Server/InnovatorServer.aspx`
   - Status: `200 OK`
   - mimeType: `text/xml`
   - Response inline: yes
   - Keywords: none explicitly
   - Request body: `TransformVaultServerURL`
   - Response body: resolves to `http://ecm.sgmw.com.cn/innovatorserver/vault/vaultserver.aspx`

7. `POST http://ecm.sgmw.com.cn/innovatorserver/Server/InnovatorServer.aspx`
   - Status: `200 OK`
   - mimeType: `text/xml`
   - Response inline: yes
   - Keywords: none explicitly
   - Request body: `File action="get"` with `Relationships/Located`
   - Response body: file filename and vault access chain

8. `POST http://ecm.sgmw.com.cn/innovatorserver/Server/AuthenticationBroker.asmx/GetFileDownloadToken?rnd=...`
   - Status: `200 OK`
   - mimeType: `application/json`
   - Response inline: yes
   - Keywords: none explicitly
   - Request body: `{"param":{"fileId":"68C519069E974AADA15ABEB4A7277BC5"}}`
   - Response body: token string
   - Sensitive values: token present in response, redacted here

9. `HEAD http://ecm.sgmw.com.cn/innovatorserver/vault/vaultserver.aspx?...`
   - Status: `200 OK`
   - mimeType: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
   - Response inline: no
   - Keywords: `NCR`
   - Query params include `dbName`, `fileId`, `fileName`, `vaultId`, `token`, `contentDispositionAttachment`
   - Sensitive values: token redacted

### `ecm.sgmw.com.cn-NCR审批明细.har`

1. `POST http://ecm.sgmw.com.cn/innovatorserver/Server/InnovatorServer.aspx`
   - Status: `200 OK`
   - mimeType: `text/xml`
   - Response inline: yes
   - Keywords: `NCR`, `审批`, `明细`
   - Request body: `ApplyMethod` on `Method action="sgmw_downloadFileDetail4C"`
   - Filters visible:
     - `ncrname = F610S,F610S DG`
     - most other filters blank
     - `othercondition = 0`
   - Response body: returns file name `NCR审批明细查询表_5d5aed49-1963-452c-a329-71aaf93a66c3.xlsx`

## 3) `services/` file map and dependency topology

### File roles

- `E:\project\vse-toolbox\services\intranet_scraper.py`
  - Selenium-based intranet scraper
  - Launches visible Chrome, waits for manual login, then downloads an Excel report from an iframe-based Aras/Innovator page and parses it with pandas
  - Imports `core.db_manager.DatabaseManager`
  - Dependencies: `selenium`, `pandas`, `rich`, stdlib `glob/os/time/pathlib`

- `E:\project\vse-toolbox\services\office_toolbox.py`
  - COM automation for Excel / PowerPoint export
  - Reads from SQLite, writes deliverables Excel and weekly PPT outputs
  - Imports `core.db_manager.DatabaseManager`
  - Dependencies: `pywin32` via `win32com.client`, `rich`, stdlib `pathlib/shutil/datetime`

- `E:\project\vse-toolbox\services\feishu_imap.py`
  - IMAP mail parser for Feishu/Lark task notifications
  - Extracts title / assignee / deadline, writes to SQLite
  - Imports `core.db_manager.DatabaseManager`
  - Dependencies: `imapclient`, `rich`, stdlib `email/re/getpass`

- `E:\project\vse-toolbox\services\vertical_forms.py`
  - Placeholder form abstractions only
  - `EWOForm`, `NCRForm`, `DMUReviewForm`, `StylingReviewForm` all raise `NotImplementedError`
  - No live I/O or scraping logic yet

- `E:\project\vse-toolbox\services\excel_toolbox.py`
  - P0 Excel helper using `xlwings`
  - Works on local files and output/backups, not intranet crawling
  - Imports `core.config.BACKUP_DIR`, `core.config.OUTPUT_DIR`
  - Useful boundary indicator: file operations are local and separate from crawler flow

- `E:\project\vse-toolbox\services\__init__.py`
  - Re-exports `IntranetScraper`, `FeishuImapParser`
  - Conditionally exports `OfficeToolbox` only on Windows

### Dependency topology

`main.py` or entrypoint
-> `services.__init__`
-> `IntranetScraper`
-> `core.db_manager`
-> SQLite storage

`main.py` or entrypoint
-> `services.__init__`
-> `FeishuImapParser`
-> IMAP mailbox
-> SQLite storage

`main.py` or entrypoint
-> `services.__init__`
-> `OfficeToolbox` on Windows
-> SQLite storage
-> local Office COM

`services/vertical_forms.py` is currently detached scaffolding and looks like the future bridge for EWO/NCR form filling.

`services/excel_toolbox.py` is adjacent but not a crawler; it can help with local workbook assembly once the sample-to-schema mapping is known.

## 4) Inferred sample-to-capability mapping

### A. EWO 报表按需过滤查询

Best-matching sample:
- `E:\project\vse-toolbox\crawl source\ecm.sgmw.com.cn-EWO明细.har`

Why:
- The first HAR entry is `Item type="EWO_O" action="get"`
- Response contains rich EWO fields, including many `_affect_*` flags and date fields
- The page shell `SGMW工程变更审批-EWO.html` contains Angular/Aras UI code with a chart-driven `EWO/Overview` and a download flow for detail lists

Likely upstream action:
- EWO overview by grouping dimension
- click-through export of the matching detail list

### B. NCR 审批进度查询

Best-matching sample:
- `E:\project\vse-toolbox\crawl source\ecm.sgmw.com.cn-NCR审批进度.har`

Why:
- The method `sgmw_downloadFileProgressC` explicitly emits `NCR审批进度查询表...xlsx`
- Query filters are visible in the request payload
- The page shell `SGMW工程变更审批-NCR.html` contains `NCR/Overview` and chart code for status breakdown

Likely upstream action:
- Query / filter NCR status by department, project, change type, lag time
- Download progress spreadsheet

### C. NCR 审批明细提取

Best-matching sample:
- `E:\project\vse-toolbox\crawl source\ecm.sgmw.com.cn-NCR审批明细.har`

Why:
- The method `sgmw_downloadFileDetail4C` directly returns the detail workbook name
- The request filter pattern mirrors the progress export with different output type

Likely upstream action:
- Same search/filter surface as progress query
- Download row-level approval detail workbook

## 5) Phase 2 high-fidelity reading order

Recommended first reads:
1. `E:\project\vse-toolbox\crawl source\ecm.sgmw.com.cn-NCR审批进度.har`
   - Best single baseline for request/response contract, file download token chain, and query parameter shape
2. `E:\project\vse-toolbox\crawl source\ecm.sgmw.com.cn-EWO明细.har`
   - Best baseline for EWO object fields and overview/detail split
3. `E:\project\vse-toolbox\crawl source\ecm.sgmw.com.cn-NCR审批明细.har`
   - Confirms the detail export method naming and output file contract
4. `E:\project\vse-toolbox\crawl source\SGMW工程变更审批-NCR.html`
   - Contains the `NCR/Overview` UI wiring and likely the callable service names
5. `E:\project\vse-toolbox\crawl source\SGMW工程变更审批-EWO.html`
   - Contains the `EWO/Overview` UI wiring and download action for detail lists

## 6) Sensitivity handling note

No raw cookie / authorization / token / session values are emitted here. Where the sample surfaced credential-like material, only the existence, field name, and structure were retained.
