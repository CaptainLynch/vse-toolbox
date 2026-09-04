# Recovery Notes

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
