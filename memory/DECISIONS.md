# Decision Log

Durable decisions that constrain future work. Append-only: supersede, never
delete. Per-plan rulings stay in their SDD ledger (`.superpowers/sdd/…`, local)
and get promoted here once they prove durable. Newest first. Keep entries
short: decision, why, cost if violated, source pointer.

## 2026-09-06 — 环图"按节点状态自动显示"规则口径

auto 模式下，交付物若已完成（完成态取快照换算口径，回退手工值）且主计划中
存在"名称分词后包含其关联节点关键字、且日期已过"的节点，则不再展示；隐藏
数量在 band-head 提示。映射常量 DELIVERABLE_AUTO_HIDE_NODE_KEYWORDS
（app.js）：D1→VDR、D2→VPI、D3→T2、D4→VDR、D5→T2，属产品口径可调整。
节点匹配必须用分词精确匹配且连字符不分词——子串或按连字符分词会把
「VPI-T2 Gate」误判为 VPI 节点。空日期（待排期）节点永不触发隐藏。
Cost if violated: 关键交付物在总览被误隐藏或该隐藏的不隐藏。
Source: ZCode 会话 2026-09-06 用户示例（到了 VDR 阶段隐藏已完成的子系统
开发策略）+ code-reviewer 审计轮。

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


## 2026-09-08 — Primary local delegation runtime

Supersedes earlier default AGY-only Codex delegation for this project. User explicitly chose Codex lead + local ZCode Gemini bounded worker; optional free-GLM periods use one interactive ZCode GLM lead. Gemini is subscription/fixed quota, so optimize Codex allowance and acceptance success rather than minimizing Gemini reasoning at the expense of retries. Keep Flash High initially.

Reuse supervisor contracts/worktrees/checks, select zcode-app-server explicitly, and return high-risk/unclassified work to the current lead without another Codex planner call. Do not silently fallback to paid providers. Keep AGY/DeepSeek as explicit opt-in only. Native-tool guard, process-tree cleanup, model preflight and final diff/check review are required. New worker branches use codex/ prefix.


## 2026-09-09 — SOR identity and failure contract

- Resolve SOR project number/name to a unique internal ID with exact trimmed matching; reject missing/ambiguous/stale/mismatched identities. Do not reuse display text as carTypeProjectAll[0]. Blank filters remain unfiltered without a project-list request; cache only within one client.
- Retain query_failed compatibility while preserving allowlisted diagnostic stage/status/code/request identifier in archival messages. Arbitrary upstream prose stays out of persisted history. Do not mark workflow-list fallback as successful official XLSX export.

## 2026-09-10 — Gemini dual-tier and 272K worker policy

- Codex is the sole control-plane authority: use `gpt-5.6-luna` with `max` reasoning for architecture, security, public contracts, task decomposition and final integration; preserve its native context window.
- All non-Codex workers use an effective 272,000-token context ceiling. Gemini total usage is not cost-capped; output, waterline, wall-clock and loop limits exist for protocol stability, side-effect safety and context overflow prevention.
- Use Flash for bounded exploration, mechanical implementation, tests and ordinary UI work. Use Pro for complex implementation, root-cause analysis and deep read-only review. High-risk tasks remain Codex-controlled with Pro as an advisory reviewer only.
- The default worker path is ZCode app-server with explicit model slots and no automatic GLM/provider fallback. GLM is an explicit optional probe whose failure skips the side path.
- Worker-to-lead communication uses bounded `handoff.v1.json`; raw tool output, screenshots, credentials and provider diagnostics remain local evidence. The runtime must preflight model identity, protocol fields, scope policy and transport before a formal worker run.

## 2026-09-10 — Generated project map and Markdown lifecycle policy

`PROJECT_MAP.md` is the default Agent-facing code-navigation entrypoint. Its
volatile file, symbol, route and source-fingerprint sections are generated by
`tools/generate_project_map.py` from an explicit production allowlist; raw
crawler evidence, build artifacts, runtime state, historical root scripts and
session documents remain default-deny. `AGENTS.md` requires map-first,
scope-limited searches and `memory/CONTEXT_MANIFEST.md` remains the memory
navigation layer rather than duplicating the code map.

Markdown is classified as Active, Generated, Historical, Reference/Evidence or
Scratch. Active documents point to code/tests/decisions, generated documents
are refreshed by their named generator, and historical or scratch material is
not default Agent input. Why: the repository contains a large tracked crawler
sample pool and many dated planning artifacts; a manually maintained directory
tree or README cannot reliably distinguish production code from evidence.

## 2026-09-11 — safe diagnostic capture scope

User approved the complete observable WebUI/Aras/TDC/sync/archive/storage chain, excluding Office/Excel Worker/API. Use local cross-process recording with structural metadata and stable per-recording fingerprints, not raw payload capture or external telemetry. The operator guide states capacity, retention and evidence limitations. A matching CLI shares the application data root; existing Windows Task Scheduler definitions are not modified automatically.

## 2026-09-12 — main context governance and weekend worker profile

- Keep Codex on its native context window, but enforce orchestration watermarks of 150K (bounded-read monitoring), 180K (phase Handoff) and 200K (new micro-session). Trigger Handoff early for a phase boundary above 150K, a 20K uncached increment, an 8K tool return, or browser image payload.
- Keep the normal ZCode Gemini Flash/Pro route unchanged. Use the explicit project profile `weekend-5.3flash` only when the weekend allowance is selected; it maps to the configured `GLM-5.3-Flash` Provider and retains the 272K non-Codex worker cap.
- ZCode runtime accepts only explicit provider kinds and formats: `openai-compatible`/`openai-chat-completions` and `anthropic`/`anthropic-messages`. Provider/model/allowlist/preflight failures stop the route; no silent fallback.
- Parent Handoffs remain bounded to changed files, diff summary, verification, risks and next action. Full logs, diffs and screenshots remain local evidence.
- Treat `weekend-5.3flash` as an interactive-only ZCode gifted-card profile: static `anthropic-messages` setup passes, but the headless path must stop before preflight because the card requires interactive runtime headers/CAPTCHA. Do not route it through the bounded headless Worker or silently fall back.

## 2026-09-13 — Gemini Worker 1M context override

- The user explicitly overrides the previous non-Codex 272K Worker cap. Keep the Astra main-controller policy independent, but allow the configured Gemini Flash/Pro Worker to use up to 1,000,000 context tokens when the provider advertises that capacity.
- Preserve the 32,768 output allowance and 16,384 safety reserve, yielding a 950,848-token per-request input budget. Derive Worker waterlines from that budget at 80%/95%/100% instead of retaining the old 272K absolute thresholds.
- The repository config, installed runtime, handoff schema, installer defaults and operator docs must agree on 1,000,000. Provider/model preflight remains authoritative; no model/provider fallback is introduced.

## 2026-09-13 — Astra main-controller effective context 272K

- The user explicitly chooses a 272,000-token effective context window for the Astra Codex client, while keeping the Gemini Flash/Pro Worker at 1,000,000.
- Set `C:\Users\Lynch\.codex\config.toml:model_context_window` to `272000`; preserve `model_max_output_tokens=128000`, model selection and reasoning settings. This is a local client limit; it does not change Astra's provider-side native context capability.
- New Codex sessions must be used to observe the updated UI context total. The existing 150K/180K/200K orchestration watermarks remain inside this client window and are not replaced by the config edit.

## 2026-09-13 — 交付物同步聚合模式与映射模板（用户确认）

- 按车型模糊搜索默认**聚合全部匹配记录**（F610S 会命中低规出口/右舵/出口巴西等多个变体，
  全部计入同一交付物的完成度），不再要求唯一稳定键；单记录匹配保留为聚合的特例。
- 字段回写规则（用户确认的映射模板 + 聚合规则）：
  - EWO 流程：负责人←「责任工程师名称」；计划完成日期←「要求完成时间」；
    风险备注←「当前阶段未签署的角色&人员」。
  - SOR 定点流程：负责人←「申请人」；计划完成日期**取消自动更新**（报表无对应列，保持手工）；
    风险备注←「最新完成节点」+「审批状态」组合。
  - 数模设计审核流程报表：负责人←「申请人」；计划完成日期**取消自动更新**；风险备注←「待审批人员」。
  - 聚合多条记录时：负责人/计划完成日期**不自动写**（多记录写单值必然出错）；
    风险备注聚合写入（逐条"标识：卡点信息"，未完成优先、超长截断）。
    同步从不写 status/progress（既有口径不变）。
- 映射模板按"来源/报表版本"显式维护并需业务确认；来源字段名以真实证据抓取的
  字段报告为准（mapping ⊆ 最新报告校验兜底），TDC 行键为英文字段名（如
  incident/currentApprover），部分列名需生产证据确认。
- NCR **纳入同步范围**：排在聚合引擎之后接入（新增交付物行 + Aras 连接器 NCR
  报表支持 + 能力注册表契约 + NCR 列映射确认）。接入前维持归档留存 + 外部同步行展示。
- 交互形态（design-previews/sync-quick-config-demo.html 已确认方向）：
  车型关键词搜索 → 聚合记录预览 → 确认启用；服务端凭据抓取证据（复用统一域账号
  账密）；专家表单折叠为逃生门。TDC password 模式要求 HTTPS（生产地址待确认）；
  browser 模式无 Cookie 时已自动复用统一域会话（app.py _shared_domain_session）。
- 前置未决：单记录 vs 聚合的业务语义已由本决策定为**聚合**；若后续需要
  "单条流程精确定位"，专家表单的匹配键仍可收窄到单条。

## 2026-09-15 EWO v2持久兼容边界

EWO新版合同使用字符串contractVersion=2和显式single_record/record_set；旧规则不自动迁移。内部sourceItemId只固定当前记录版本，不能跟随同号新修订。集合负责人/计划日期永远手工。迁移先停用保存，新签名两次取证后启用；旧HTTP客户端缺版本确认拒绝修改，并在事务内比较配置修订号。数据库schema14同时阻止旧EXE打开新版库，回退必须恢复旧库备份。

官方导出为独立只读增强，不进入自动字段映射。账号+来源+筛选签名控制恢复；unknown生成结果禁止重发；基础与增强分别记时间；空号不按位置猜测关联。用户可以在prepare后查看真实基础内部ID，prepare无生成副作用。
