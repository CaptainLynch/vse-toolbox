# Recovery Notes

## 2026-09-14 — 生产测试双 EXE 已构建并完成离线冒烟

- 使用 canonical `tools/build_excel_bundle.ps1` 生成 `dist/VSE-Production-Test-20260914/`，包含 `VSE-WebUI.exe`、`VSE-ExcelWorker.exe` 与 `SHA256SUMS.txt`；清单哈希已用独立 `Get-FileHash` 重新核对。
- 依赖隔离验证从 `.runtime/production_exe_smoke_20260914` 工作目录完成：Worker `--help` 返回 0；WebUI 本机 `/` 和 `/api/overview` 返回 200。one-file WebUI 启动链曾留下实际监听进程，已按端口核对其精确可执行路径后终止，端口复核已释放。
- 全量回归为 **1997 passed, 3 skipped / 183.89s**，项目地图检查通过。构建日志中的 `xlwings.pro` LicenseError 仅影响可选 pro 子模块收集，不影响标准 Worker 打包；后续目标机仍需真实 Excel/Office 验收。

## 2026-09-14 — 第四轮分页缺陷已修复并全量验证
## 2026-09-14 — 第四轮分页缺陷已修复并全量验证

- `services/tdc_crawler.py` 增加严格分页整数解析，size 与请求不一致时不合并且不授权；显式无效页号不会再被默认值掩盖。缺失字段与 nullable total/pages 按旧兼容处理；零总数/零页数的空结果合法。
- `services/aras_crawler.py` 校验 Result 和全部 EWO Item 页号；错页、重复 Item ID 在合并前拒绝。只比较整页内容无法拦截缺 ID 的局部重叠，因此采用行内容哈希并跟踪有/无 ID 切换；有明确不同 Item ID 的相同业务内容仍允许。
- 两处旧测试需按新合同处理：数模 max_records 夹具应明确 size=3，不能靠默认 size=2；EWO page=unknown 的旧容忍测试应改为拒绝。最终持久分页用例 62 项，爬虫相关 154 passed，全量 1997 passed / 3 skipped。
- 原审计复现脚本断言漏洞存在，修复后不应继续以其 exit 0 为验收目标；使用 `tests/test_crawler_pagination_integrity.py` 与文档中的最终验证记录。

## 2026-09-14 — 第四轮审计新增未修复分页边界

- 已用真实 JSON/SOAP 解析加合成 HTTP session 证明：TDC 请求 size=100 而响应 size=2、无 total/pages 时，两条满页被当 short_page；current=0/invalid 在解析器中变成请求页号；Aras EWO 请求第二页返回 page=1 的短页，或连续重复 Item ID 后空页，仍返回 complete=true。两侧完整性门禁均接受。
- 防止误判：仅检查 `_crawl_all` 的 result.page 不足以证明协议校验可靠，必须检查解析器是否已把显式错误默认成请求值；尾页判断必须考虑有效分页大小；Aras 不能假定 TDC 的修复自动覆盖自身路径。
- 本轮未修产品代码。完整复现输入、影响、方案与验收合同在 `docs/AGGREGATE_SYNC_AUDIT_20260914_ROUND4.md`；403 项既有相关测试通过不代表上述新增边界通过。

## 2026-09-14 — TDC 分页完整性再次审计与修复

- 根因：`_crawl_all` 使用未去重的 `accumulated_count` 作为 `total_end` 证明，且没有验证 `TDCPagedResult.page` 是否等于请求页；因此重复页或矛盾的 `total/pages` 元数据可以被完整性门禁接受。
- 修复：请求页号错配时不合并该响应并返回 `inconsistent_page`；达到 total 但声明仍有后续页时返回 `inconsistent_metadata`；去重后的结果不足声明 total 或出现重复身份时不返回完整态，并以 `duplicate_records` 拒绝。
- 回归：`tests/test_tdc_crawler.py` 新增三项红绿测试；原审计合成脚本验证连接器与映射发现两侧均拒绝修复后的结果。相关套件 **270 passed**，全量 **1935 passed, 3 skipped**；地图、编译、Node 契约与差异检查均通过。

## 2026-09-14 — 聚合同步第二轮审计修复闭环

- 请求级 discovery 证据必须由请求开始时冻结的规范化规则签名；不能在外部请求返回后从当前 binding 回读规则。合法的未保存筛选仍可先形成证据，之后再保存/启用；请求身份不含凭据。
- 完整性不是 `rows` 非空或 `len(rows) == limit` 的推测。TDC 只有 `reported_pages`、`reported_total`、无矛盾的 `empty_page`/`short_page` 等明确停止证据才能 complete；页间 total/pages 矛盾要以 `inconsistent_metadata` fail-closed。Aras/TDC discovery 与同步执行共享完成态白名单。
- 历史计数需要从当前 binding 推导签名，并在有有效规则时归一化比较当前稳定键；聚合绑定的稳定键是 NULL。请求局部签名不能强行受旧 binding 稳定键限制，否则会破坏“先发现、后保存”的流程。
- 完整候选缓存是有界脱敏行集合，不是展示样本；展示可以截断到 200，候选写入口径仍可到 1000。mapping signature 用于记录缓存身份，mapping 改变时必须从完整缓存重算，不能继续读取旧聚合字符串。
- 旧测试夹具缺失 `config_signature` 时应迁移夹具生成合法当前签名，不能放宽生产校验。最终全量回归固定为 1932 passed / 3 skipped；证据日志位于 `.runtime/review2_repro_final.log` 和 `.runtime/review2_full_final3.log`。事务回归的并发侧应直接尝试换绑，才能验证产品写事务保护而不只是验证任意 SQLite 锁。

Environment pitfalls, failed attempts (do-not-retry), and verified root
causes. Rewritable wholesale at checkpoints — but never delete *why* a failed
attempt failed; prune only entries that no longer apply. Root causes that are
locked by regression tests are noted here for orientation; the tests in the
repo are the authoritative record.

## 2026-09-02 — 数模 tdc_data_model track (ZCode session 2)

- **No openpyxl/pandas on this host's Pythons** (venv 3.11 and system Python
  both lack them; the product ships xlsx via Win32 COM instead). Do-not-retry:
  `pip install` into the user env. Read-only xlsx structure inspection works
  with stdlib only (`zipfile` + `xml.etree`, sharedStrings + sheet XML) —
  kept at `.runtime/sm-review-inspect-xlsx-stdlib.py`.
- **`python -c` with multi-line/multi-arg quoting swallows output** in this
  cmd-compatible shell (exit 0, no stdout). Write a script file under
  `.runtime/` and run it instead.
- **summarize dead-code trap**: when adding a per-report `incomplete`
  computation above the result dict, the dict still returned the old
  `total - completed` expression — caught because the test-first contract
  asserted the contracted value (general-purpose agent reported it as a
  production-bug stop instead of patching). Lesson: per-report summary
  branches must be paired with a same-commit assertion on the summary key.
- **classify_overdue guard ordering**: the generic
  `if not stage or stage == CLOSE: not_applicable` runs before per-report
  branches; any report whose `stage` dimension is NOT an approval stage
  (数模 stage = 项目/车型) must be classified BEFORE that guard or empty/
  conflicting values silently bypass its overdue rule. Locked by
  `test_tdc_overdue_does_not_depend_on_project_value`.
- **SQLite CHECK whitelist extension** requires table rebuild; recipe and
  recovery (leftover `*_rebuild` table is dropped on next init) locked by
  `test_form_snapshot_check_constraint_rebuild_allows_tdc_data_model`.
  `PRAGMA foreign_keys=OFF` is a silent no-op inside a transaction — the
  rebuild must run before any DML opens the implicit transaction in
  `init_database`, then commit and re-enable FK inside `_migrate_schema`.

## Environment & tooling pitfalls

- Host is Windows with **no bash and no WSL**. SDD/workspace scripts that
  require bash fail; create the equivalent files manually (observed
  2026-09-01). Shell is cmd-compatible; `head`/`tail` etc. do not exist.
- **AGY CLI headless permission denials.** The local AGY worker
  (gemini-3.7-flash, sandboxed) cannot prompt for tool permissions in
  headless mode. Symptom: exit code 0 with stderr
  `jetski: no output produced — a tool required the "command" permission that
  headless mode cannot prompt for, so it was auto-denied.`
  FAILED ATTEMPT (do not repeat): delegating UI implementation to AGY on this
  host lost 6 runs on 2026-09-01 (TASK-20260901-DELIVERABLE-UI R1–R5, each
  ending `codex-takeover-required`, zero diffs produced). Until the
  permission flow is resolved, the lead/Main session implements UI and
  command-heavy work directly and reserves AGY for tasks whose required
  commands are pre-authorized in the sandbox. Fix in progress: `agy_cli.py`
  now classifies zero-exit denials as `blocked` (committed in `785c650`).
- `.agents/runs/`, `.runtime/`, `.superpowers/sdd/` are gitignored and
  local-only. Never treat their contents as recoverable state.
- Git CRLF warnings on this working tree are benign (autocrlf conversion
  notices), not corruption.
- The repository-wide `python -m flake8` command recursively scans
  `.agents/worktrees` and `.venv` because they are not in `setup.cfg`'s
  exclusions; it therefore returns baseline diagnostics unrelated to the
  migration. Scoped flake8 over the eight hardening Python files passes.
- UTF-8 mypy under both the system Python 3.14 and repository `.venv` Python
  3.11 reports the same 69 existing errors in 13 files. Do not attribute
  those errors to the hardening batch without a new, line-specific diff.
- Full validation of Aras/TDC endpoints requires domain authentication or
  local mock fixtures; production-network acceptance is only claimed when
  production credentials are actually used (so far: never — offline synthetic
  verification is the norm).

## Verified root causes (locked by tests — repo is truth)

- XLSX WebUI preview rejected official workbooks whose single sheet XML
  exceeded the old 32 MB member cap → caps rebalanced to 64 MB per member /
  96 MB total (committed in `785c650`; `tests/test_xlsx_preview.py`).
- NCR progress/vault-download timed out under the default receive timeout →
  240 s receive timeout on those paths (committed in `785c650`;
  `tests/test_aras_crawler.py`).
- DPAPI vault `resolve()` context swallowed consumer exceptions (e.g.
  connector failures raised inside the context) as `CredentialVaultError` →
  consumer exceptions now propagate untouched (committed in `785c650`;
  `tests/test_settings_security.py`).
- AGY `blocked` classification missed headless denials that exit 0 →
  stderr/stdout denial markers now checked before exit-code logic
  (committed in `785c650`; `tests/test_agy_cli.py`).

## Stale-doc warnings

- `README.md`: claims CLI-only/"zero web framework", contains a stray
  `ACCEPTANCE_TEST` line, and its directory table predates `web/`, `tools/`,
  and the scheduler services. The real interfaces are the Flask WebUI
  (`webui.py`) plus the CLI (`main.py`).
- The 2026-06 four-role agent subsystem was retired and deleted on
  2026-09-02: `.codex.yaml` plus `docs/agents/project_state.md`, `task.md`,
  `review_feedback.md`, `role_*.md`, `SOP_worker_coding.md`,
  `implementation_plan.md`, and the consumed sprint plans
  (`PROJECT_OVERVIEW_*`, `FRONTEND_REDESIGN_EXECUTION_PLAN`). Recover from
  Git history if ever needed. Current rules: `AGENTS.md`,
  `tools/agents/README.md`, `.agents/config.json`.

## Hypotheses (clearly labeled; promote only after verification)

- (2026-09-02, unconfirmed) The uncommitted hardening batch is post-release
  fallout from SDD Task 6 verification. Confirm with commit history or the
  user before treating as fact.

## 2026-09-02 — deliverable UI redesign checkpoint

- The UI redesign is paused at the preview gate. Architecture and the NCR
  aggregation grain are confirmed by the user; no production code was changed
  for this redesign.
- Read-only analysis of the supplied workbooks verified the relationship
  `EWO 1:N NCR 1:N NCR detail rows`: 387 unique NCRs, each with one EWO; the
  NCR detail workbook has 3768 rows and 366 NCRs with multiple detail rows.
  Use `.runtime/ncr-ewo-cardinality-20260902.json` only as local evidence;
  it contains field-level counts and no business identifiers.
- Confirmed aggregation: NCR progress status/trend counts distinct
  `NCR编号`; NCR detail status/trend also counts distinct `NCR编号`; NCR
  detail cost charts sum detail rows; department is the all-region total and
  section is `区域`.
- The prior preview regeneration was interrupted after the old ignored
  `.runtime/deliverable-forms-preview.html` was removed. Recreate it before
  any production-code edit; this is not source-code loss.
- Do not include workbook rows, credentials, cookies, tokens, or passwords in
  the preview, memory, ZCode handoff, logs, or tests. Use real headers and
  synthetic/redacted rows only.

## 2026-09-02 — Codex takeover repairs after ZCode quota exhaustion

- **EWO default filter key mismatch.** Stage B initially persisted and injected
  `department` for both EWO and PAA. `ArasArchiveConnector._ewo_filters()`
  accepts only `responsibleDepartment`; fake runner connectors did not expose
  the error. Fixed the seed migration and runtime fallback, including cleanup
  for the exact early incorrect built-in value. Locked by archive seed/admin
  and runner contract tests.
- **NCR entity/row grain mix-up.** Form summaries counted every physical row,
  inflating NCR progress duplicates and NCR detail status metrics. Added the
  sanitized `ncrNumber` dimension and a stable representative-row projection
  for status metrics only. Costs and table rows remain physical-row grain.
  Locked by duplicate progress/detail tests.
- **TDC official export mapping gap.** Official TDC XLSX rows use Chinese
  contract headers while the list API uses English keys. The old dictionary
  path therefore produced empty dimensions and values in snapshots. Added a
  header-detection path that restores positional values before normalizing.
  Locked by synthetic official-header regression coverage.
- **Frontend filter transport gap.** Stage B rendered overdue/relation-EWO
  controls but omitted both keys from the query builder, and multi-select
  reloads discarded newly selected values. Both are fixed and covered by UI
  static contract tests.
- Final offline validation after these repairs: `1658 passed, 2 skipped`,
  compileall/Node check/build passed; mypy remains the known 69-error baseline
  and scoped flake8 retains only the known `core/db_manager.py:37 E305`.

## 2026-09-02 — Codex read-only audit findings

- **NCR missing-identity collapse:** `_safe_text(None)` returns the literal
  `"None"`; the new NCR representative projection consequently treats blank
  `ncrNumber` values as one shared NCR. A synthetic two-row case returns
  `summary.total == 1`. The untouched local database reproduces the same
  symptom: NCR progress has 17,055 stored rows but the current view matches 1,
  and NCR detail has 74 stored rows but the current view matches 1.
- **Legacy snapshot incompatibility:** the local database is still schema v11
  and its existing form snapshots have no `keyColumns` or `overdueRules`.
  Startup migration upgrades the table constraint but does not rewrite the
  stored schema, dimensions, or historical summaries. `view()` serves the
  stored schema and unfiltered trend summaries, so an existing installation
  can show a current summary and historical trend at different grains.
- **NCR source aliases:** the existing snapshot contains a `完成` status which
  the current aliases do not classify as `CLOSE`; `LEADER审核` and
  `财务高级总监批准` are also not in the current node aliases. Their exact
  mapping to approved nodes needs business confirmation before production
  acceptance.
- **Sync observability/completeness:** an unreadable NCR workbook returns
  `form_rows=None` and record count zero, while the archive runner finalizes
  the source run as success. Form projection exceptions are likewise logged
  and hidden behind a successful run. TDC/NCR workbook parser truncation flags
  are not propagated, so bounded partial form snapshots can also look like
  complete successful syncs.
- Focused form/runner/connector tests: `162 passed`; full suite:
  `1658 passed, 2 skipped`. These tests do not cover the above legacy, blank
  identity, source-code status, parser-truncation, or projection-failure cases.

## 2026-09-02 — Codex repair and bounded ZCode cross-audit

- Added regression coverage and fixes for blank NCR identity handling, legacy
  schema/trend/status compatibility, NCR `完成`, TDC status code `4`, numeric
  and short contact masking, independent filter-option discovery, and archive
  form-projection/truncation observability.
- Archive projection is now checked before source-run success is finalized. A
  projection or verified-completeness failure finalizes the same run as
  `needs_attention` with the collected artifacts, preserving the last good
  form snapshot.
- Verification completed with `1671 passed, 2 skipped`, clean repair-scope
  flake8, clean target-service mypy under UTF-8/import-skip mode, and a passing
  isolated dual PyInstaller build. Full mypy remains the documented 69-error
  repository baseline.
- The configured local AGY worker was invoked in an isolated worktree for the
  requested cross-audit. A corrected bounded retry still hit the same
  headless `escalate_admin` denial and produced no findings or edits. Never
  weaken sandbox permissions or use `--dangerously-skip-permissions` to retry;
  treat this as an environment-blocked cross-audit and rely on Codex evidence
  until the exact project-level permission is approved.

## 2026-09-02 — NCR progress live response compatibility

- The built WebUI reached ARAS successfully, but the initial parser rejected an
  HTTP 200 response because the `<Result>/<Item>` type value was not the fixed
  `sgmw_outputFileRecord` spelling. A sanitized live-shape probe confirmed a
  valid `<Result>` item with a non-empty `_file` relation.
- `ArasCrawlerClient.parse_ncr_progress_response()` now scopes discovery to the
  `Result` subtree and accepts an `Item` only when it has a non-empty direct
  `_file` child. It still rejects empty/malformed results and never falls back
  to `Message` content.
- Regression and real validation passed: parser/Web routes `126 passed`, full
  suite `1673 passed, 2 skipped`, fresh dual build passed, and the fresh EXE
  returned 500 NCR progress rows with no browser console errors. No raw XML or
  credential value was persisted.

## 2026-09-02 — ZCode audit and Antigravity repair boundary

- ZCode was verified independently before the AGY repair attempt. Session
  `sess_8471cad2-b3f8-49d9-a956-7f9f22546a1c` used the configured
  `gemini-3.7-flash-high` provider, completed the requested read-only audit,
  ran the exact focused pytest command (`151 passed in 6.43s`), and ran
  `python -m compileall -q services core web` successfully. The model report
  found the requested deliverable-form and scheduled-archive behavior
  compliant, with custom NCR node aliases still awaiting domain confirmation.
- AGY 1.1.23 and the auto-updated 1.1.24 both execute model-only headless
  prompts, but a read-only `git status --short --branch` prompt is soft-denied
  in headless mode: the `Bash`/`RunCommand` tool requests `escalate_admin`,
  which headless mode cannot prompt for. A precise `command(git status
  --short --branch)` allow rule did not change the result. The TUI launches but
  stops at first-run terms/sign-in onboarding, which was not accepted
  automatically. A custom-agent experiment was removed because it did not
  demonstrate Bash execution and its real agent path returned a location
  precondition error.
- This is an external Windows permission/onboarding boundary, not a proven
  repository adapter defect. Keep the existing blocked-result classification
  and tests. Do not broaden global command permissions, enable
  `always-proceed`, or use `--dangerously-skip-permissions` without an explicit
  security decision.

## 2026-09-02 — Production WebUI package size and mail delivery boundary

- The original WebUI one-file build exceeded the mail limit because
  `VSE-WebUI.spec` collected CLI-only Selenium/IMAP/Rich trees and optional
  PythonWin helpers. The production spec now excludes those unused WebUI
  paths and development-only Flask/debug modules while retaining the explicit
  WinHTTP/pywin32 imports required by the packaging test.
- A size-compliant package was built in an isolated Python 3.11 environment
  with PyInstaller 6.22.2 and UPX 5.2.1. The final Deflate9 ZIP is
  14,942,697 bytes and contains only `VSE-WebUI.exe`; `ZipFile.testzip()`
  passed. Rebuilding with the default Python 3.14 environment is known to
  exceed the strict 15,000,000-byte target and must be rechecked.
- The local AGY packaging audit returned `Agent execution terminated due to
  error` after one read-only turn and made no changes. The result is not
  evidence against the packaging decision; the decision was independently
  verified by the build, smoke test, and full pytest.
- Classic Outlook COM activation is unavailable on this host. The user later
  reported Gmail connected and the workspace app list discovered Gmail, but
  the current task still exposes no Gmail send/attachment action. Do not claim
  delivery without a callable mail tool or a verified local mail-client send
  result. No credentials or mail secrets were stored.


## 2026-09-08 — ZCode worker runtime verified boundaries

- CLI 0.16.5 help lists --settings/--max-turns but the parser rejects them. Use the validated app-server adapter; do not retry those headless flags.
- `state.updated` reason `prompt_completed` is a dispatch milestone, emitted before actual model work. Wait for matching `session/event` turn.completed/turn.failed. Initial projection can be stale; verify settings.model.current and settings.permission.mode before sending.
- `mcpServers: []` does not disable global MCP loading; ZCODE_STORAGE_DIR changes storage, not the user config discovery path. Native tool allowlist removes MCP tools; the old AGY MCP was separately disabled in user config.
- Build mode allows native Edit without permission broker callbacks. Do not rely on permission_decision alone: the installed conditional PreToolUse scope guard was tested with an actual ZCode + local fake model that attempted an out-of-scope Write; result blocked and target absent.
- Worker deliberately has no Bash; supervisor runs user/lead-supplied verification commands. A worker statement that tests passed is not evidence. Single-round task IDs/run directories are not reusable; repair is a new bounded contract/task after lead review.
- Credentials are passed only in runtimeModel over stdio. Raw request/stderr logs are prohibited; summaries mask the configured key and endpoint URLs. Backups of existing user config remain under the user directory because those config files can contain secrets.


## 2026-09-09 — SOR export production evidence and Gemini review

- Loopback HAR cannot reveal upstream TDC request/response. Local 502 wraps crawler API validation; generic JSON-instead-of-XLSX text is local fallback, not a specific upstream cause. Do not equate archive query_failed with a proven failing upstream operation.
- Current manual-only SOR UI is intentional in tests since 623d4f2; historical project-selector completion claims do not describe current behavior. Archive ID omission reproduced synthetically.
- Gemini review needs primary verification: this run incorrectly claimed carTypeProjectId was accepted and absent test_tdc_web.py meant no Web tests; existing test_deliverables_web.py is the correct test home. Generic 12-column fallback does not apply to observed 15-column headerRows response.
- Installed launcher worked with current gemini-3.8-flash-high. Single verification command must remain an array of argument arrays; PowerShell can flatten nested arrays, so validate JSON shape before dispatch. This audit used a read-only task instruction, but runtime tool allowlist included writes; actual guard audit/diff confirmed no writes. Do not claim enforced readonly mode from context.read_only alone.
- Full evidence and next tasks: docs/SOR_EXPORT_ANALYSIS_20260909.md. Original production files and DPAPI remain untouched.


## 2026-09-09 — SOR repair implementation and verification

- Both ZCode implementation runs ended as permission-classified blocked after leaving partial edits. Their result changed_files=[] did NOT mean worktree was clean. Inspect actual git diff before takeover. No broadened permission or model retry was used.
- Gemini UI tests initially used CommonJS globals to override lexical functions and incomplete DOM stubs. Parent changed tests to VM context with bounded DOM control parsing; no production module.exports/test bootstrap was kept.
- Browser verification caught selector overflow invisible to contract assertions; flex wrapping and bounded select width fixed it. Manual edits clear hidden ID; reload clears selection; stale lookup cannot unlock a newer request. ID-only choices submit ID without copying it into display-name filter.
- New safe diagnostic stores allowlisted metadata only; raw upstream prose is intentionally not persisted in archive history. Numeric business code and upstream HTTP status are separate from local Web status. Nested messages are bounded to known keys and redacted for interactive display.
- Current WebUI entrypoint supports VSE_TOOLBOX_PORT (historical fixed-port note is superseded). Final packaged smoke used 5066; temporary DB kept separate from production. Output ZIP contains EXE only.
- Validation: full 1751 passed / 3 skipped; final targeted 15 passed after one ID-only test added; production TDC export not exercised. Durable release/retest guide: docs/SOR_EXPORT_REPAIR_20260909.md.

## 2026-09-10 — ZCode worker permission audit root cause

- `tools/agents/zcode_worker.py:27` currently allows permission requests only when the tool is in `WRITE_TOOLS`; an in-scope `Read` permission request is therefore denied. The two SOR implementation run audits each contain one `Read` record with `allowed: false`, and the worker result maps that denial to `failure_code=permission`.
- Preserve the write/scope safety boundary when repairing this predicate. Add a focused preflight and regression test for in-scope `Read`, `Grep`, and `Glob` before retrying implementation workers. Do not broaden global permissions or silently switch providers.

## 2026-09-10 — Gemini dual-tier runtime implementation

- The app-server rejects unknown fields inside `runtimeModel.provider.models[*]`. Internal `contextBudget` and `thinkingLevel` metadata must be removed before protocol submission; retain them only in local summaries and handoffs. Real Flash and Pro no-tool probes passed after this filter was added.
- The old installation manifest intentionally refused to overwrite a changed user runtime. Use the explicit installer mode with a new installation ID to back up the current target before synchronization; the verified Pro-agent installation is `vse-worker-20260910-pro-agent-verified`. Do not weaken the default hash guard.
- CliproxyAPI exposes `gemini-pro-agent` as `Gemini 3.1 Pro (High)` and also exposes `gemini-3.1-pro-low`; the project Pro slot must use `gemini-pro-agent`. Do not treat either local alias as an official model ID; capability and network preflight remain the source of truth.
- `Read` permission failures were caused by a Worker RPC predicate that only admitted `WRITE_TOOLS`; the shared `tool_decision` implementation now covers Read/Grep/Glob separately and preserves write scope/readonly checks.

## 2026-09-10 — dual-tier short/medium/long smoke

- The first long Pro-agent smoke was blocked after three tool requests because app-server native tool input used `filePath`, while the guard only read `file_path`/`path`. Additions to shared `tool_path` fixed this without broadening scope; rerun completed short Flash read, medium Flash write and long Pro-agent high read-only review.
- Smoke evidence: short `gemini-3.8-flash-high` completed with one Read; medium Flash completed with two calls and only `medium.txt` changed; long `gemini-pro-agent` completed with two Reads and no changes. All three used the 272,000-token effective context cap.

## 2026-09-11 — diagnostic recording recovery facts

- Short-lived SQLite connections caused repeated last-connection WAL checkpoints and intermittent event loss in a four-thread recorder test. Retain one connection during recording and serialize same-process writers; retain the short cross-process lock timeout so diagnostic contention never replaces the business error. Drop evidence is best-effort and explicitly described in the manifest.
- UI history initially preserved the old selected recording after starting a new one. Node regression now requires start to select the returned latest ID; manual history selection remains stable thereafter. Browser EXE smoke verified the fix.
- Expired recordings with no subsequent writes must have their effective expired state projected during export, not only during status reads. Every event includes process build identity so a recording spanning process restarts cannot silently imply one build version.
- Exception messages/locals/source lines remain excluded; preserve errno/winerror/HRESULT and each exception type in a bounded cause chain for native/network root-cause triage.
- Scheduled EXE requires core/report_headers.json in its PyInstaller datas. Added focused packaging test and supplied matching CLI/WebUI; two-process dry-run export verified offline. Do not claim full production execution from a no-enabled-jobs dry-run.

## 2026-09-12 — context policy and GLM-5.3-Flash profile verification

- Main-controller policy is orchestration-only: `150000` means bounded-read monitoring, `180000` requests Handoff and `200000` starts a new micro-session. It does not alter the native Codex context window. `tools/audit_token_trajectory.py` consumes the policy without reading raw prompts into the report.
- The first `weekend-5.3flash` no-inference probe failed because `zcode_worker.load_runtime` accepted only `openai-compatible`, while the configured `GLM-5.3-Flash` Provider is `anthropic`. The verified fix maps `anthropic` to `anthropic-messages` and preserves rejection of unsupported kinds/formats.
- The project profile is opt-in and maps both Flash/Pro slots to `GLM-5.3-Flash`; the default model remains Gemini. Launcher dry-run, provider load, local permission preflight and the installation manifest all pass. No external model inference was performed during this change.
- Global runtime changes use installation ID `vse-worker-20260912-interactive-card`; use its manifest-aware check/rollback rather than overwriting changed targets.

## 2026-09-12 — GLM-5.3-Flash real smoke blocker

- A temporary isolated short task with `-WorkerProfile weekend-5.3flash` reached the supervisor and passed static preflight: model `GLM-5.3-Flash`, Provider `builtin:zai-start-plan`, format `anthropic-messages`, effective context `272000`, Read/Grep/Glob allowed. Network preflight then returned a non-retryable runtime `unknown_error` during `prepare`; the task stayed `preflight-blocked`, with no worktree or Worker round.
- A separate explicit comparison using configured `builtin:zai` reached the provider but returned non-retryable HTTP 429/provider code `1309`. This is evidence of an entitlement/provider-side blocker, not permission scope failure. Medium and long real smokes were intentionally skipped; do not add a silent fallback or claim the weekend route operational until a short smoke reaches Worker execution.
- The initial failed short attempt was caused by PowerShell flattening nested `verification_commands`; rebuilding the contract with explicit nested lists produced the valid contract and exposed the actual provider preflight failure.
- The first preflight failure (`runtime prepare` / `Preflight tools are disabled`) was caused by the worker rejecting normal ZCode host callbacks `session/requestRuntimePreferences` and `interaction/requestProviderRuntimeHeaders`. The worker now answers safe runtime preferences and refuses to claim provider headers were applied when no interactive host is present. The next real probe reached the provider and exposed the true non-retryable 400/3007 CAPTCHA failure. Do not turn this into a header/CAPTCHA bypass.
- CliproxyAPI at the configured local `/v1/models` endpoint returned Gemini models but no `GLM-5.3-Flash`; there is no configured local OpenAI-compatible 5.3 Flash route to use as a transparent fallback.
- User clarified that `GLM-5.3-Flash` is a ZCode gifted trial card. Interpret provider code 3007 as the expected interactive-entitlement boundary; use interactive ZCode for the card and keep the headless supervisor profile fail-closed with `interactive-required`.

## 2026-09-13 — Gemini Worker 1M context verification

- The provider config advertises 1,000,000 context for `gemini-3.8-flash-high`, `gemini-pro-agent` and the GLM trial entry. The Worker itself, not CliproxyAPI, had been clamping all providers to 272,000; the clamp, handoff schema constant, installer default and runtime config were updated to 1,000,000.
- Flash static preflight and network preflight passed with a 1,000,000 context budget. A real read-only smoke reached Gemini and returned a completed result, but the supervisor recorded `permission` blocked because the model tried Glob/Grep with an omitted path and one repository-root Read outside the isolated worktree; the scope audit is intentionally fail-closed. Treat this as a test-contract/scope issue, not a context or provider failure.
- Pro `gemini-pro-agent` no-tool network preflight passed with the same 1,000,000/950,848 budget. Do not use the GLM interactive-only profile for this normal Gemini route.

## 2026-09-13 — direct `zcode` TUI entrypoint boundary

- `C:/Users/Lynch/.local/bin/zcode.cmd` and `C:/Users/Lynch/bin/zcode.cmd` both invoke `D:/zcode/resources/glm/zcode.cjs` without arguments. That bundle contains the `app-server` path used by the Worker, but the installed `glm` resource has no `@zcode/tui` package or `node_modules`, so bare `zcode` fails while importing the interactive TUI.
- Keep the normal project route on `C:/Users/Lynch/.zcode/tools/run-worker.ps1`; it passes the `app-server` argument and has been verified with both Gemini slots. Launch `D:/zcode/ZCode.exe` for the Desktop UI. Do not repair the bundle by manually copying or installing an unverified package; update/reinstall the official ZCode distribution if an interactive CLI is required.

## 2026-09-14 — SOR 查询诊断边界
- 诊断包 f52efc893c2b424bad728f56be76f138：两个车型文本解析零匹配、本地 400；列表 200/16 条；同录制仅部门 SOR 第一页成功。四个异常是两次请求的分层记录。不要误报为登录失败、SOR 全面不可用或四次失败。
- json-ok 的项目列表不证明 id/projectNo/projectName 存在；当前解析器和选择器均依赖这些字段。优化前先区分字段合同与真实零匹配；见 docs/SOR_QUERY_DIAGNOSTIC_20260914.md。

- 官方 SOR HAR 已补齐（2026-09-14）：list 必带观察到的 sorEnabled=true（201项）；查询 carTypeProject 与 carTypeProjectAll[0] 都传内部ID；导出附bizName=SOR。旧16项列表及名称参数合同需修正。独立XLSX 4833明细/408流程与查询total408对齐，勿混淆粒度。见SOR诊断报告补充章节。

- SOR上述三项合同已于2026-09-14修复；新增合成上下文切换测试能重现错误项目字典导致拒绝，四入口共用修正。全量2006 passed/3 skipped，新双EXE复测包VSE-SOR-Fix-20260914已验哈希与本地启动，内网成功仍待现场验证。

## 2026-09-15 EWO worker实际通道阻塞
- TASK-ewo-pure-association-20260915静态预检passed，网络预检Worker deadline exceeded，transport/preflight-blocked；未生成worktree或worker轮次。不把路由配置可用当成模型实际可用；禁止自动provider fallback或大规模GPT接管。
- supervisor的风险关键词会匹配objective中的否定描述（如No database）；准确描述纯函数职责、把排除职责放constraints能保留真实边界；不是给高风险实现重贴低风险标签。

- 2026-09-15 Gemini路由：取消Pro，仅3.8 Flash；旧pro槽位兼容映射Flash。此前EWO失败是Flash网络预检deadline，非Pro失败。新同30秒预算无工具探针25.77秒成功；尚不能区分上游/中继/启动延迟。doctor有独立Luna硬编码限制，勿混作网络故障。见docs/ZCODE_WORKER_RUNTIME.md。


### 2026-09-15 预检总预算修复验证

原30秒截止覆盖启动、session/create/subscribe/send和模型响应。现统一为60秒（源码默认、安装器、项目/全局配置、已安装运行时），仍为单次总截止且保留进程树清理。成功结果增加timings_seconds/elapsed_seconds/timeout_seconds，超时报告安全stage标签与耗时，不记录提示词或凭据。

安装后的真实3.8 Flash无工具预检30.172秒成功：create1.516、send0.062、模型响应28.594秒。该正常响应跨越旧30秒截止，验证原预算会误杀正常请求；不宣称已经定位原请求的服务商内部延迟原因。147 passed/1 skipped，地图检查通过。未重启原EWO实施。

## 2026-09-15 EWO Flash任务验证与边界
- 官方ZCode launcher恢复后两个Flash隔离任务产出已审查集成；state passed不替代diff核验：发现纯函数把未知小写state upper，测试也写了同一错误预期，主控修正并验红绿。工作簿另有regex大小写测试失败。
- 新解析器读取实际sheetData，真实111列表410数据行/406唯一编号+4空编号，关联不会按行序补ID。105项相关测试通过，但尚未Web集成或全量发布。
- 下一关键边界是主体scope：DomainSessionRegistry目前无显式principal，不可用domain常量或session对象id作为持久任务账号身份。

## 2026-09-15 EWO v2集成排错

- 配置CAS不能只加比较：get_project_status_update_policy原SELECT未返回sync_config_revision，必须一起补齐，否则重复保存被误判冲突。使用唯一上下文应用补丁，泛化old_binding锚点曾插入错误方法，定向测试已捕获并修复。
- 新源码增加详情页内容后，旧测试按6000字符截断造成假失败；改为按下一函数边界定位，保留原断言。
- 新身份必须同时进入发现、执行与分析item_key；只改关联函数仍会让同号/空号同属性行被分析层合并。v2仅用_source_item_id生成item_key，legacy不改。
- 候选预览也必须采用v2空值不清空规则；否则显示待清空而执行实际跳过。已补预览/执行一致性测试。
- schema14为旧EXE保护门槛；此前只有HTTP版本确认不足以约束旧二进制。升级测试保留legacy规则，模拟v13 runtime会在DDL前拒绝v14数据库。
