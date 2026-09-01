# Recovery Notes

Environment pitfalls, failed attempts (do-not-retry), and verified root
causes. Rewritable wholesale at checkpoints — but never delete *why* a failed
attempt failed; prune only entries that no longer apply. Root causes that are
locked by regression tests are noted here for orientation; the tests in the
repo are the authoritative record.

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
