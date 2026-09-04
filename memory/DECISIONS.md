# Decision Log

Durable decisions that constrain future work. Append-only: supersede, never
delete. Per-plan rulings stay in their SDD ledger (`.superpowers/sdd/…`, local)
and get promoted here once they prove durable. Newest first. Keep entries
short: decision, why, cost if violated, source pointer.

## 2026-09-02 — 数模设计审核流程 (tdc_data_model) unified detail view contract

`tdc_data_model` (数模设计审核流程, TDC UWF `procuwfpe3ddigitalmodeldesignreview`,
47-column export) is now the 5th unified deliverable form. Approved口径:
chart tabs = 项目状态 (stage ← 项目/车型, observed values not fixed list) /
部门状态 (section ← 部门) / 数量趋势; 发布属性 only a filter (model dimension);
department dimension unused (empty select is hidden in UI). Overdue = 审批中
dwell > 7 days from 申请日期 (`_OVERDUE_RULES["tdc_data_model"]`); 已完成 and
已废弃 are not_applicable. Summary incomplete excludes 已废弃 (but in charts
已废弃 falls into the blue "unknown" bucket by design). Detail table hides
columns 12/13 (重量（单件）, 零件合计) everywhere in the view via
`_TDC_HIDDEN_COLUMN_INDEXES`, default visible 15 ending at EWO/SOR号; raw
values stay in stored rows. form_key is `tdc_data_model` (job-key aligned,
auto-links archive cards); project-status deliverable VPI-T2-D5 maps to it in
`DELIVERABLE_FORM_KEY_BY_ITEM`. Why: matches production test product (808 rows,
headers identical to the contract) and user-confirmed preview. Cost if
violated: the detail view diverges from the approved preview and EWO/PAA/NCR
structure. Source: this session's preview confirmation + implementation.

## 2026-09-02 — SQLite form_key CHECK 白名单扩展必须走表重建迁移

SQLite cannot alter a CHECK constraint; `_migrate_schema` rebuilds
`deliverable_form_snapshots` when its stored DDL lacks a newly allowed
form_key (foreign_keys=OFF outside any transaction → rebuild → commit →
foreign_keys=ON; leftover rebuild tables are dropped on next init). Adding a
future form key requires: DDL template + detection-based rebuild + the four
analysis-service maps + runner job→form map + connector form_rows + app.js
maps. Source: tdc_data_model registration, schema v11→v12.

## 2026-09-02 — Accept existing lint/type baseline for this migration

Treat the full pytest result (`1629 passed, 2 skipped`) and scoped flake8 over
the hardening files as the migration gates. Accept the repository-wide flake8
scan-boundary diagnostics and 69 existing mypy errors as out of scope; fixing
them requires a separate quality task. Source: verification after commits
`82827f5`, `86238b9`, and `785c650`.

## 2026-09-02 — Retired the 2026-06 four-role agent subsystem

Deleted `.codex.yaml` (explorer/architect/worker/reviewer role prompts; no
code consumer left) and the related historical docs (`docs/agents/`:
`project_state`, `task`, `review_feedback`, `role_*`, `SOP_worker_coding`,
`implementation_plan`) plus the consumed sprint plans (`PROJECT_OVERVIEW_*`,
`FRONTEND_REDESIGN_EXECUTION_PLAN`). Current collaboration rules: `AGENTS.md`
+ the supervisor harness (`tools/agents/`, `.agents/config.json`) +
`memory/`. Kept on purpose: `docs/PHASE0/PHASE1_*` (refactor rationale),
`DELIVERABLE_UPDATE_MODES_*` (implemented architecture), and
`GPT_WEB_PROJECT_CONTEXT.md` (external-LLM context). Recover via Git history.

## Established ≤ 2026-08-20 — Web/scheduling architecture constraints (promoted from GPT_WEB_PROJECT_CONTEXT.md §6)

- No permanent scheduler thread inside Flask: scheduled work runs as a
  standalone `run_once` runner invoked by Windows Task Scheduler
  (`services/scheduled_archive_runner.py`, `services/project_status_sync_runner.py`).
- External connectors return normalized candidate updates; they never write
  project-status tables directly — the shared update service owns validation,
  field authority, audit, and writes.
- Manual values win by default; scheduled sync respects field authority and
  never silently overwrites manually locked fields.
- A failed run keeps the last successful data and records a sanitized
  failure; it must not clear the dashboard or claim success.
- Preserve the existing `/api/overview` contract; add dedicated APIs rather
  than changing unrelated public endpoints.
- Unattended authentication requires a separately approved credential-reference
  design; plaintext credentials are never persisted to make scheduling work.
Source: `GPT_WEB_PROJECT_CONTEXT.md` §6 (capability claims elsewhere in that
file are partially stale — see CONTEXT_MANIFEST).

## 2026-09-02 — `memory/` is the shared Codex+ZCode memory layer

Four git-tracked agent-neutral files (`CONTEXT_MANIFEST`, `CURRENT_STATE`,
`DECISIONS`, `RECOVERY_NOTES`); protocol in `AGENTS.md`. Chosen because the
only durable cross-agent state was git history plus design docs: SDD ledgers
and `.agents/runs/` are local-only. Cost if violated: state loss on
clone/machine change/session switch, repeated investigation.

## 2026-09-01 — Headless AGY permission denial is a blocked result, never a reason to weaken the sandbox

Reaffirmed after 6 lost AGY runs (see RECOVERY_NOTES). The fix belongs in
detection/classification (`tools/agents/agy_cli.py`), not in disabling
`--sandbox` or granting blanket permissions. Source: `AGENTS.md` → Local AGY
CLI Delegation.

## 2026-09-01 — Form snapshot service stays additive to the existing EWO analysis cache

Existing EWO endpoints and legacy chart-label behavior must remain
compatible. Cost if violated: duplicate EWO storage and an extra migration
surface. Source: SDD ledger ruling 2026-09-01.

## 2026-09-01 — EWO PROC period uses one natural calendar-month boundary, not a fixed 30-day approximation

Requirement says "one month" and month boundaries are user-visible. Cost if
violated: one-day classification differences around short/long months.
Source: SDD ledger ruling 2026-09-01.

## Long-standing — Credential boundaries

- TDC: OIDC login via enterprise account center; passwords, tokens, and
  session data are never written to config, logs, or diagnostics.
- Aras/EWO: reuse the browser session Cookie/Authorization; no local
  credential persistence; expired sessions prompt re-capture, not storage.
- Secrets live only in the Windows DPAPI vault
  (`core/credential_provider.py`, `data/domain-credential.dpapi`, gitignored).
- Redaction (`core/redaction.py`) scrubs tokens/cookies/authorization
  headers from logs, exports, and diagnostics.
Source: README, `docs/PROD_DATA_MODEL_SOR_CAPTURE_GUIDE.md`, code.

## Long-standing — Excel automation is out-of-process for DLP compatibility

Office COM work runs in a dedicated worker process
(`tools/excel_worker_cli.py` / `core/excel_worker.py`), not in-process,
because enterprise DLP transparent encryption breaks in-process COM file
access. Source: `docs/EXCEL_TASK_WORKER.md`.

## 2026-09-02 — NCR/EWO relationship and detail aggregation

- Treat the cross-form relationship as `EWO 1:N NCR`; every NCR must map to
  exactly one EWO, while one EWO may map to multiple NCRs. NCR detail rows
  remain a separate `NCR 1:N detail-row` grain.
- Count NCR progress and NCR detail status/trend metrics by distinct NCR
  number. Sum NCR detail cost values at detail-row grain, aggregate the
  department as the all-region total, and use `区域` as the section
  dimension. Source: user confirmation on 2026-09-02 and the supplied
  workbook cardinality audit.

## 2026-09-02 — Scheduled EWO/PAA default department uses connector-specific keys

The built-in EWO archive filter stores and sends
`responsibleDepartment=技术中心_车体工程`; PAA stores and sends
`department=技术中心_车体工程`. The runner keeps a runtime fallback and the
schema seed repairs the exact early EWO typo without overwriting other user
filters. Why: the two ARAS connector contracts use different field names;
using `department` for EWO causes connector validation failure.

## 2026-09-02 — NCR form status metrics are entity-grain, costs are row-grain

`ncr_progress` and `ncr_detail` summary/status/overdue metrics collapse rows by
the sanitized `NCR编号`, using a stable representative for each NCR. NCR
detail cost charts and detail-table pagination continue to use every physical
detail row. Why: one NCR can have many detail rows; mixing grains inflates
status counts or loses cost values.

## 2026-09-02 — TDC official exports normalize by approved Chinese headers

TDC official XLSX rows are returned by the connector as header-keyed mappings,
but the form analysis layer recognizes approved Chinese headers and restores
the positional 47-column contract before extracting dimensions and dates. Why:
the API dictionary keys and official workbook labels are different contracts;
mapping the latter as API keys silently produces empty snapshot rows.

## 2026-09-02 — Legacy form snapshots use read-side compatibility

Existing installations are not rewritten just to add current schema metadata or
change NCR metric grain. The view service serves the current allowlisted schema
and re-summarizes legacy NCR history from preserved positional rows when the
stored schema lacks the entity-grain marker; status completion is normalized in
the read-side metric projection. Why: this preserves historical rows and keeps
the migration additive while removing mixed-grain dashboard results.

## 2026-09-02 — Form projection completeness is part of archive run acceptance

An archive run with an unreadable/invalid/truncated official form or a failed
form snapshot projection cannot finalize as `success`. The connector returns a
stable projection error code; the runner stores collected artifacts and marks
the same run `needs_attention`, preserving the last good snapshot. Why: a
successful source archive without a trustworthy form projection is not an
auditable successful sync.

## 2026-09-02 — NCR progress export records are identified by Result/_file

The NCR progress parser must not require one server-side `Item type` spelling.
It accepts only a non-empty `_file` child under an `Item` within the top-level
`Result` subtree, retaining the outer record ID and `_file` keyed name. It does
not use `Message` nodes as a fallback. Why: live ARAS returned a valid export
record with a different type value; the scoped relation is the stable contract
while arbitrary XML fallback would risk accepting error metadata.

## 2026-09-02 — Production WebUI package uses an explicit slim build profile

The WebUI PyInstaller spec excludes CLI-only integrations and development
helpers that are not reachable from the WebUI runtime (Selenium, IMAP, Rich,
xlwings, PythonWin browsers, and Flask test/debug modules). It retains the
explicit WinHTTP/pywin32 hidden imports required by the packaging contract.
The size-compliant delivery build uses Python 3.11, PyInstaller 6.22.2, and
UPX 5.2.1, then creates a standard Deflate ZIP containing only
`VSE-WebUI.exe`. Why: the default Python 3.14 build remains above the strict
15,000,000-byte mail limit; dropping Tk or the required COM hidden imports
would trade away WebUI functionality or violate the existing contract.
