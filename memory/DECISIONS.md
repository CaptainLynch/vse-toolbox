# Decision Log

Durable decisions that constrain future work. Append-only: supersede, never
delete. Per-plan rulings stay in their SDD ledger (`.superpowers/sdd/…`, local)
and get promoted here once they prove durable. Newest first. Keep entries
short: decision, why, cost if violated, source pointer.

## 2026-09-06 — SOR 定点流程 (tdc_sor) 注册为第 6 个统一表单

`tdc_sor`（TDC SOR 定点流程，官方 15 列导出，headers 见
report_contracts()['tdc_sor']）按 tdc_data_model 同款机制注册：DDL CHECK
白名单 + 检测式重建迁移（迁移检测条件为存储 DDL 缺任一新 form_key）；
维度口径 stage←车型项目 / section←科室 / department←部门（入库不上图）/
model←类型（仅筛选）；审批状态 API 中英文混合，`_normalize_sor_status`
归一（Completed→已完成）；已完成/Completed 计为完成；已终止/已作废/
Terminated/Cancelled 为终态（不计完成、不计未完成、不判逾期）；逾期沿用
审批中滞留 7 天口径（申请日期起）；“当前待办人”列（索引 14）加入
_CONTACT_INDEXES 脱敏；deliverable VPI-T2-D2 经
DELIVERABLE_FORM_LINKS/DELIVERABLE_FORM_KEY_BY_ITEM 双侧映射到 tdc_sor。
后续新增 TDC 表单照此配方：DDL 白名单+重建检测 → 分析服务四映射+维度/
逾期/状态归一 → runner job→form map → DELIVERABLE_FORM_LINKS → app.js
（键/tabs/筛选标签/图表标题）→ 四层测试。Cost if violated: 位置行错位、
联系人泄漏或状态口径不一致。Source: ZCode 会话 2026-09-06，SOR 官方 15 列
合同与 report_contracts 源字段映射为既定事实。

## 2026-09-06 — 主计划默认里程碑模板与空日期语义

默认里程碑模板为 11 个空日期节点（VPI → 内饰模型评审 → 外饰模型评审 →
LLP VDR → 100% VDR → LLP T2 → 100% T2 → OTS → 验证阀 → 内部体验阀 → 用户
体验阀），milestone_date=NULL 表示"待排期"（schema v13 里程碑列可空）。空
日期仅允许"未开始"节点；种子修复采用**全字段元组比对**：与旧 6 节点种子
完全一致才替换为模板，任何差异（哪怕只调换顺序或改一天日期）都视为用户
数据保留。current_stage_label 必须跳过空日期节点，否则 /api/project-status
500。未来新增"创建项目"接口时必须挂同一模板。Cost if violated: 用户手工
排期数据被静默覆盖，或空日期导致总览接口崩溃。Source: ZCode 会话
2026-09-06（用户确认方案 A + 架构审核修正版）。

## 2026-09-06 — 交付物状态图表读侧联动表单快照，不写库

除 VPI-T2-D1（子系统开发策略，纯手动）外，交付物"当前状态图表"与总览环图
在渲染时从 DELIVERABLE_FORM_LINKS（web/app.py 后端单源）指向的最新表单快照
换算：progress=round(completed/total*100)，状态三态（全部完成→已完成/
overdue>0→已逾期/否则→进行中）；无快照回退手工值；手工进度保留为详细明细
参考值。不向 project_status_deliverables 写回任何字段，字段权威规则不受影
响。快照→交付物映射只允许在后端维护（formLink payload 下发），前端
DELIVERABLE_FORM_KEY_BY_ITEM 仅作归档详情页回退。D2(SOR) 需业务口径确认后
注册表单；D4(造型VDR) 等 A 面契约解锁。Cost if violated: 双源映射漂移、或
自动写库与手工锁定字段冲突。Source: ZCode 会话 2026-09-06 用户确认。

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
