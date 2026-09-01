# Decision Log

Durable decisions that constrain future work. Append-only: supersede, never
delete. Per-plan rulings stay in their SDD ledger (`.superpowers/sdd/…`, local)
and get promoted here once they prove durable. Newest first. Keep entries
short: decision, why, cost if violated, source pointer.

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
