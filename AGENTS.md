# Agent Collaboration Rules

## Shared Engineering Rules

- Keep architecture, module boundaries, interfaces, data flow, security,
  authentication, authorization, privacy, and public contracts under the
  Main Agent's direct judgment.
- Delegate only bounded work with a concrete objective, owned files or a
  read-only scope, acceptance criteria, and focused verification commands.
- Do not repeat the same broad exploration in multiple agents. Give each
  agent the smallest useful evidence set and require compact, structured
  reports rather than full files, diffs, or logs.
- Do not trade correctness for token savings. Escalate when the evidence
  contradicts the settled design, a public interface or data model must change,
  a security assumption is uncertain, unrelated edits prevent a safe change,
  or two bounded repair attempts fail for the same cause.
- Preserve unrelated workspace changes. Never revert them unless the user
  explicitly requests it.
- Redirect verbose test, build, and log output to `.runtime/` where practical.
  Report failures, root causes, evidence locations, and material warnings.
- Verify the implemented contract with focused tests, then perform the final
  regression, packaging, or smoke checks warranted by the change.
- Treat secrets, credentials, tokens, cookies, and environment values as
  sensitive. Do not place them in instructions, source control, routine agent
  handoffs, or reports. Expose the minimum necessary exact value only when the
  Main Agent explicitly judges it essential for reproduction or verification.

## Project Map / Agent Exploration Policy

Project code location is map-first, scope-limited, and evidence-driven. The
repository and tests remain authoritative; `PROJECT_MAP.md` is the default
navigation index, not a replacement for reading the target implementation.

- At the start of every non-trivial task, read `PROJECT_MAP.md` after restoring
  the required memory state and before searching for code. Use its Task Router
  to choose a domain and an initial file set.
- The default production scope is `core/`, `host/`, `plugins/`, `services/`, `web/`, `main.py`,
  `webui.py`, `excel_worker_entry.py`, `tools/excel_worker_cli.py`,
  `tdc_probe_main.py`, and `tdc_probe_cli.py`.
- Enter `tests/`, `*.spec`, `setup.cfg`, `requirements.txt`,
  `.github/workflows/`, `tools/agents/`, `schemas/`, `docs/`, or `memory/`
  only when the task needs tests, packaging, Agent infrastructure, contracts,
  or documentation.
- The following are default-deny paths and must not be read or indexed unless
  the task explicitly concerns them: `crawl source/`, `爬虫源文件/`,
  `error data/`, `build/`, `dist/`, `dist-probe/`, `production*/`,
  `.build_production*/`, `.runtime/`, `artifacts/`, `tmp/`, `.tmp_*/`,
  `.agents/runs/`, `.agents/logs/`, `.agents/worktrees/`, `.zcode/`,
  `.excel_workbench/`, `design-previews/`, `meeting_outputs/`, caches, root
  exploratory scripts, and raw XML/HAR/XLSX samples.
- Searches must include an explicit scope, for example
  `rg -n "symbol" core services tests` or
  `rg -n "symbol" services/tdc_crawler.py tests/test_tdc_crawler.py`.
  Do not use repository-root `rg --files`, recursive directory trees,
  `Get-ChildItem -Recurse`, `find`, or equivalent full-repository scans.
- Read the map-selected entrypoint and focused tests first. Expand only one
  dependency/caller layer at a time when the contract is not explained; do not
  fall back to a full scan because the first result is incomplete.
- Raw HAR/XML/XLSX, browser mirrors, and error data are permitted only for an
  explicit parsing or forensic task. Prefer the redacted summaries under
  `docs/agents/`.
- Before claiming the map is current, run
  `python tools/generate_project_map.py --check`. If it fails, report map
  drift and refresh or repair it; do not compensate with a full scan.
- If the target is still not found after the mapped, scoped search, report a
  map gap and the paths already checked, then request or justify a scope
  expansion. Never silently widen the search.

## Plugin Architecture (since 2026-10)

- New features are new plugins: `python tools/new_plugin.py <id> --name 名称`
  creates `plugins/<id>/` (`plugin.json`, `backend.py` with `register(host)`,
  `static/pages/*.json`). Do not add new code to legacy `web/static/app.js`,
  route bodies in `web/app.py`, or `core/db_manager.py`.
- Plugins reach shared services only through `host.context` (db, data dir,
  JSON envelope, `local_guard` for every write route) and must not import
  `web.*` or other plugins. Plugin tables use `host.table_prefix` and
  additive `host.migrate([(version, fn)])` steps.
- Ship a plugin change as a signed `.vsepkg` (`tools/build_plugin_pkg.py`);
  host changes ship as a new onedir zip. See
  `docs/PRODUCTION_OPERATION_GUIDE.md` section 7.

## Runtime Selection

Use one lead per task. The user's current choice takes precedence over defaults.

### Expert Advisor routing for DSH and ZCode leads

- The DeepSeek Harness + v4.1 Flash main agent and the ZCode interactive lead
  on its selected model (including GLM-5.3-Flash) decide whether a Codex second opinion is
  useful. Follow C:/Users/Lynch/.dsh/skills/expert-advisor/SKILL.md for the
  full trigger, profile and safety contract. Only the interactive lead may
  call the Expert Advisor. Bounded implementation, tests, documentation
  and focused evidence collection remain delegable to ZCode workers.
- After enough local evidence, consult once before committing to a nontrivial
  architecture design or implementation plan. The user need not name a scenario
  or supply two options. Also consult after two focused debugging passes leave
  conflicting evidence on a high-impact issue, or when the user explicitly
  requests an independent opinion.
- Choose sol-high for ordinary nontrivial design, sol-xhigh for complex
  multi-module public contracts, concurrency or rollback, and astra-medium
  or astra-high for hard-to-reverse security, silent-data-loss or destructive
  migration decisions. Use astra-high when evidence conflicts or several
  high-risk boundaries are coupled. Do not upgrade after a failed call.
- Skip routine implementation, tests, documentation, settled decisions and
  questions a focused local check can answer. Do not re-consult the same
  decision without material new evidence. A keyword alone is not a trigger.
- The lead prepares a redacted self-contained package, checks status and
  dry-run with the chosen profile, then makes at most one live call for that
  decision. All profiles share one ledger and rolling limits. It independently
  judges the advice and retains implementation responsibility. If the route is
  unavailable or rejects the call, continue without switching profile,
  account, provider or harness.

- In Codex, Codex owns architecture, public contracts, security, complex debugging and final integration. Bounded implementation, tests and mechanical work use the local ZCode Gemini worker through `C:/Users/Lynch/.zcode/tools/run-worker.ps1 -Workspace <repo> -TaskFile <contract.json>`.
- In an interactive ZCode task, the selected model is the lead. During free GLM periods use the flagship actually available under the account, not a hardcoded model version. Use Gemini subagents for bounded work; do not keep a second Codex lead running in parallel.
- A ZCode process invoked with a worker contract acts only as the worker. It must not recursively delegate or start Codex, AGY or DeepSeek. Model, quota and permission failures stop the route, never silently switch provider.
- The old AGY MCP bridge is retired. AGY CLI and DeepSeek are explicit opt-in alternatives only, never fallback paths. A visible legacy Codex role file does not establish a valid provider configuration.

## Bounded Worker Contracts

- Every task supplies task_id, objective, owned scope, constraints, acceptance criteria, risk_class and explicit verification_commands as argument arrays. Batch related implementation and tests; do not launch a fresh worker per function.
- The supervisor uses isolated worktrees, checks dirty-scope conflicts and refuses high-risk/unclassified work to the current lead without another Codex planning call. The legacy profile label `agy-heavy` names this contract pipeline; `worker_agent` selects the runtime.
- Gemini 3.8 Flash worker sessions use an effective 1M context cap; with the default output/reserve budget, 950848 input tokens are available. Gemini total usage is not cost-capped. Flash handles bounded routine work, 3.8 Flash handles bounded implementation/deep review, and Codex remains the final architecture/security/integration authority.
- The guarded worker has only native Read/Grep/Glob/Edit/Write; no shell or nested agents. The supervisor runs the supplied checks externally. The installed PreToolUse guard blocks out-of-scope/control-file operations; worktree isolation is not an OS sandbox.
- The lead inspects the actual diff, check results and concise worker report before integration. No auto-merge or push. Preserve unrelated changes. After at most two targeted repairs for the same cause, take over rather than retrying indefinitely.
- Architecture, authentication/authorization, credentials/redaction, concurrency, destructive migrations and unclear public contracts remain with the lead. Delegate tests only after the lead defines the fixture/data contract and scenario assertions.
- Use readonly-explorer for bounded evidence and code-reviewer for meaningful changes. They are directly configured Gemini roles, not AGY dispatchers. Avoid duplicate broad searches and full-file/log handoffs.
- Runtime setup, verified boundaries and rollback: `docs/ZCODE_WORKER_RUNTIME.md`. Run evidence is local-only under `.agents/runs/`; promote durable conclusions into memory.

## Main Controller Context Governance

- Codex keeps its configured native context window; on this machine Astra's Codex client is configured with an effective `272000`-token window. The following values are orchestration watermarks within that window: soft reminder `150000`, Handoff trigger `180000`, hard guard `200000` input tokens.
- Below `150000`, continue normally. From `150000` to `180000`, use bounded reads and summaries. At `180000`, finish only the current atomic operation and hand off. At `200000`, stop accumulating context and start a new micro-session.
- A phase boundary above `150000`, an uncached input increment of `20000` or more, a tool return of `8192` or more characters, or any browser image/large AX payload requests a Handoff even when the token watermark is lower.
- Handoffs contain only the task ID, changed files, diff summary, verification commands/results, risks and next action. Keep full logs, full diffs, screenshots and raw tool output in local evidence files.
- The worker's separate `1000000` effective context cap remains unchanged. With the default `32768` output allowance and `16384` safety reserve, the normal Gemini 3.8 Flash route has `950848` input tokens available. A weekend model override is opt-in and must not change the normal Gemini 3.8 Flash route.
- The ZCode gifted `GLM-5.3-Flash` weekend profile is `interactive-only`: a headless `-WorkerProfile weekend-5.3flash` invocation must stop with `interactive-required` because runtime headers/CAPTCHA come from the interactive host. Use the model in interactive ZCode and omit the option to restore the normal Gemini worker route.

## Persistent Project Memory Protocol

`memory/` is the shared, git-tracked long-term memory for Codex and ZCode.
It is agent-neutral Markdown: no session state, no runtime-private context,
no secrets. `memory/CONTEXT_MANIFEST.md` is its map — read order, update
rules, document freshness, and fact priority. Repository is truth; memory is
navigation, not proof.

Before a non-trivial task, restore state in this order: `AGENTS.md`, then
`memory/CURRENT_STATE.md` (execution frontier and exact next action), plus
`memory/RECOVERY_NOTES.md` when debugging or touching the agent harness,
crawlers, credentials, Excel COM, or packaging, then verify against
`git status`, `git diff`, and the relevant code/tests before working. When
information conflicts, trust the fact-priority order in
`memory/CONTEXT_MANIFEST.md` — never memory over code, tests, or git.

Milestone checkpoints: update `memory/CURRENT_STATE.md` (replace wholesale)
and, when the milestone produced new knowledge, `memory/RECOVERY_NOTES.md`
(pitfalls, failed attempts, verified root causes) or `memory/DECISIONS.md`
(durable decisions). Checkpoint at: feature complete, bug fixed and
verified, important decision made, long investigation finished, root cause
found, hypothesis confirmed or rejected, execution frontier change — and
always before session end, before `/compact` or Codex compaction, before a
model switch, and before a Codex <-> ZCode handoff. Compact only after the
persistent state is safe on disk.

The SDD ledgers (`.superpowers/sdd/`) and `.agents/runs/` are local-only
(gitignored). Anything from them that must survive a new clone, a machine
change, or a session loss must be promoted into `memory/` at the checkpoint
that produces it.

Subagents do not read `memory/` wholesale. The lead agent passes the relevant
excerpts, constraints, and known failed routes in the task brief, then
decides what enters long-term memory from the results.
