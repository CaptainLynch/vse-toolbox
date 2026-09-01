# Unified Deliverable Form Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox ( - [ ] ) syntax for tracking.

**Goal:** Build a common, secure form snapshot and analysis view so EWO, PAA, NCR approval progress, and NCR approval detail expose approved form fields, chart tabs, independent filters, and auditable background/interactive states.

**Architecture:** The Main session owns report contracts, XLSX parsing, snapshot persistence, overdue/cost aggregation, scheduled publication, authentication boundaries, and public API behavior. After those contracts are frozen, the local AGY CLI receives isolated low-risk UI and UI-test tasks only. Existing EWO analysis and archive APIs remain compatible through an additive adapter.

**Tech Stack:** Python 3.10+, Flask, SQLite, native DOM JavaScript, CSS, pytest, the repository XLSX parser, PowerShell, and the configured local AGY CLI.

**Spec:** docs/superpowers/specs/2026-09-01-deliverable-form-analysis-design.md

## Global Constraints

- Preserve all existing user changes; never reset, clean, overwrite, or roll back unrelated work.
- The approved form keys are exactly 'VPI-T2-D3', 'aras_paa', 'aras_ncr_progress', and 'aras_ncr_detail'.
- EWO/PAA/NCR progress expose three chart tabs: department status, section status, and daily total/incomplete/overdue trend; NCR detail exposes department cost and section cost tabs and no overdue calculation.
- EWO dimensions are '部门' and '责任工程师专业科室'; PAA dimensions are '部门' and '专业科室'; NCR dimensions use '区域' as section and department as the sum of sections.
- Use the exact approved overdue rules in the spec: EWO 7 days/one calendar month/IMPL deadline/CLOSE; PAA 3 days/7 days/IMPL deadline/CLOSE; NCR first two stages 3 days/later stages 7 days/finance-director completion; NCR detail has no overdue.
- Preserve all three NCR detail cost groups: estimated, approved, and actual tooling cost plus estimated, approved, and actual per-vehicle cost change; department and section aggregations are sums.
- Each chart tab owns its filter state; filters include keyword, status, department, section/region, model/project, stage/node, start date, and end date; chart clicks append filters.
- Existing public API paths remain compatible. New form APIs are additive and allowlist form keys and filter field names.
- Interactive results never create a project-status run, acquire a lease, advance a cursor, write business fields, write audit, or write archive artifacts.
- Passwords, tokens, cookies, Authorization values, private keys, complete credentials, lease tokens, and raw auth headers never enter snapshots, logs, responses, browser storage, URLs, or AGY handoffs.
- Scheduled execution keeps the existing runtime-prerequisite bypass and real connector credential resolution; manual execution keeps its readiness checks; failures retain the last successful snapshot.
- Do not expose server absolute paths; return only controlled artifact metadata and existing download routes.
- Every focused test, full test, compile, lint, type, build, and browser evidence command writes complete output under .runtime/.
- No real ARAS/TDC request or production credential is used in tests or screenshots.

---

## File Map

- core/db_manager.py: idempotent schema for form snapshots/rows and bounded read/write methods.
- core/report_contracts.py: approved report headers, source mappings, display transforms, and chart/filter field metadata.
- services/xlsx_preview.py: bounded all-sheet XLSX reading while preserving the existing first-sheet API.
- services/deliverable_form_analysis.py: new allowlisted form registry, row normalization, overdue/cost aggregation, daily snapshot selection, and view serialization.
- services/scheduled_archive_connectors.py: publish sanitized PAA/NCR form data while preserving official artifacts and existing ArchiveCollection compatibility.
- services/scheduled_archive_runner.py: atomically publish the form snapshot after successful archive collection and retain it on failure.
- services/project_status_sync_runner.py: publish EWO form snapshots alongside the existing EWO analysis cache without changing lease or credential flow.
- web/app.py: additive form-view/rows/chart-label endpoints and service wiring; existing search/archive/project-status endpoints stay compatible.
- web/static/app.js: common detail shell, chart tabs, independent filter state, click-to-filter, interactive/background badges, and stable empty/error states.
- web/static/style.css: desktop layout, chart/table/filter styling, status colors, cost increase/decrease colors, and multilevel header presentation.
- tests/test_deliverable_form_analysis.py: normalization, overdue, cost, grouping, daily trend, and redaction tests.
- tests/test_deliverable_form_api.py: API allowlist, paging, filters, empty/error states, and artifact metadata tests.
- tests/test_scheduled_archive_connectors.py, tests/test_scheduled_archive_runner.py, tests/test_project_status_sync_runner.py: publication, failure retention, lease, retry, and real credential-resolution regressions.
- tests/test_overview_web.py, tests/test_overview_external_deliverables_ui.py, tests/test_scheduled_archive_admin_ui.py: frontend contract and existing overview/archive regression tests.
- .runtime/: all test/build/lint/type/browser evidence; never store credentials or raw external responses.

## Task Decomposition and AGY Assessment

| Task | Owner | Model | Risk | AGY decision |
| --- | --- | --- | --- | --- |
| Form contract, XLSX parsing, row normalization, overdue/cost semantics | Main session | Main model | architecture/data correctness | Main only |
| Snapshot tables, retention, API, artifact access | Main session | Main model | migration/public contract/data security | Main only |
| Scheduled/project-status publication and failure retention | Main session | Main model | credentials/lease/concurrency | Main only |
| Detail UI implementation after API freeze | AGY ui | gemini-3.7-flash-high | bounded frontend | Eligible; isolated worktree and scope review required |
| UI static/regression tests | AGY test-only | gemini-3.7-flash-low | tests only | Eligible after UI contract is merged |
| Mechanical call-site/document sweep | Conditional | gemini-3.7-flash-low | only if exact paths are known | Do not dispatch initially; fold into the UI task unless Main identifies a disjoint scope |
| Final integration/security review/browser acceptance | Main session | Main model | cross-module and production-like behavior | Main only |

AGY is not allowed to decide authentication/session reuse, form field authority, database schema, lease behavior, cost/overdue semantics, public API compatibility, redaction rules, or cross-module integration.

## Task 1: Freeze the form registry and parser contract

**Owner:** Main session.

**Files:**

- Modify: core/report_contracts.py
- Modify: services/xlsx_preview.py
- Create: services/deliverable_form_analysis.py
- Test: tests/test_deliverable_form_analysis.py

**Interfaces:**

- FormKey is the closed set Literal['VPI-T2-D3', 'aras_paa', 'aras_ncr_progress', 'aras_ncr_detail'].
- read_xlsx_workbook_preview(path: Path, *, max_rows: int, max_columns: int) -> tuple[XLSXPreview, ...] returns all approved worksheets; existing read_xlsx_preview() remains first-sheet compatible.
- FormSnapshotInput contains form_key, report_type, source_run_id, snapshot_at, schema, rows, summary, charts, and sanitized artifact metadata.
- DeliverableFormAnalysisService.normalize_snapshot(form_key: str, source_rows: Sequence[Mapping[str, object]] | Sequence[Sequence[object]], *, snapshot_at: str, source_run_id: int | None, source: str, sheet_name: str | None = None) -> FormSnapshotInput.
- NCR detail rows preserve sheet_name, six independent cost fields, and the original unit labels.

- [ ] Step 1: Add contract metadata tests from the approved JSON headers.

  Assert EWO 111 columns/one header, PAA 113 columns/one header, NCR progress 64 columns/two headers, and NCR detail 65 columns/five headers. Assert the approved NCR detail worksheet names remain available as metadata.

- [ ] Step 2: Add bounded all-sheet XLSX parser tests.

  Build tiny in-memory XLSX fixtures with two worksheets and multilevel headers using the existing test helper style. Assert row/column limits, sheet names, blank-cell preservation, and bounded failure messages.

- [ ] Step 3: Add row normalization tests.

  Use synthetic EWO/PAA dictionaries and positional NCR rows. Assert approved source fields are mapped, unknown fields are discarded, contact values are masked, duplicate row keys are deterministic, and NCR detail keeps measurement, approved, and actual cost groups separate.

- [ ] Step 4: Add overdue-rule tests.

  Cover EWO stage durations of 7 days, PROC one calendar month, IMPL deadline, CLOSE completion; PAA 3/7 day stages and IMPL deadline; NCR first two 3-day stages, later 7-day stages, finance-director completion; NCR detail returns no overdue flags. Assert unknown dates remain unknown instead of being classified on time.

- [ ] Step 5: Add aggregation tests.

  Assert department and section counts are sums of filtered rows, cost series are estimated/approved/actual and never overwrite one another, positive cost change is marked increase, negative change is marked decrease, and daily trend selects the latest snapshot per natural day.

- [ ] Step 6: Implement the parser, allowlist registry, and pure aggregation functions.

  Keep existing report-contract response shapes unchanged. Add explicit field metadata for filterable and chartable fields; do not infer SQL or field names from request input. Use this pure cost result shape:

  ~~~python
  {
      'dimension': 'department' | 'section',
      'label': str,
      'investment': {'estimate': number | None, 'approved': number | None, 'actual': number | None},
      'vehicle_change': {'estimate': number | None, 'approved': number | None, 'actual': number | None},
  }
  ~~~

- [ ] Step 7: Run the focused task checks.

  ~~~powershell
  python -m pytest tests/test_deliverable_form_analysis.py -q > .runtime/task1-form-analysis.log 2>&1
  python -m py_compile core/report_contracts.py services/xlsx_preview.py services/deliverable_form_analysis.py > .runtime/task1-compile.log 2>&1
  ~~~

- [ ] Step 8: Main review and commit.

  Inspect the diff for raw row/secret leakage and commit only the Task 1 files:

  ~~~powershell
  git diff --check
  git add core/report_contracts.py services/xlsx_preview.py services/deliverable_form_analysis.py tests/test_deliverable_form_analysis.py
  git commit -m "feat: define unified deliverable form analysis contract"
  ~~~

## Task 2: Persist form snapshots and expose additive read APIs

**Owner:** Main session.

**Files:**

- Modify: core/db_manager.py
- Modify: services/deliverable_form_analysis.py
- Modify: web/app.py
- Create: tests/test_deliverable_form_api.py

**Interfaces:**

- DatabaseManager.publish_deliverable_form_snapshot(snapshot: FormSnapshotInput) -> int atomically inserts one snapshot and its bounded rows, retaining configured snapshot history.
- DatabaseManager.get_latest_deliverable_form_snapshot(form_key: str) -> dict[str, object] | None.
- DatabaseManager.list_deliverable_form_rows(form_key: str, filters: Mapping[str, object], *, offset: int, limit: int) -> dict[str, object].
- GET /api/deliverable-forms/<form_key>/view returns {formKey, reportType, snapshot, schema, summary, charts, filters, artifacts, sync}.
- GET /api/deliverable-forms/<form_key>/rows accepts only the fixed filters from the spec and bounded offset/limit.
- GET/PUT /api/deliverable-forms/<form_key>/chart-labels uses existing EWO label validation rules, keyed by form key; old EWO chart-label storage is read compatibly.

- [ ] Step 1: Add idempotent SQLite tables and indexes.

  Add deliverable_form_snapshots with form_key, report type, source run ID, snapshot time, row count, schema JSON, summary JSON, chart JSON, artifact metadata JSON, and status. Add deliverable_form_rows with snapshot ID, row key, row number, values JSON, search text, sheet name, status, department, section, model, stage, submitted date, planned date, and overdue state. Use foreign keys, bounded lengths, and snapshot retention in the same transaction.

- [ ] Step 2: Add database round-trip tests.

  Publish two snapshots on the same day and one on another day; assert latest selection, row paging, field filters, retention, and no absolute path or secret fields in returned dictionaries.

- [ ] Step 3: Add API contract tests.

  Cover all four allowlisted form keys, unknown form key 404, invalid fields 422, bounded paging, empty snapshot, empty filtered result, missing snapshot, chart-label round-trip, artifact metadata, and redacted error responses.

- [ ] Step 4: Implement service/API wiring.

  Use the form registry to serialize schema and chart definitions. Aggregate trends by natural day and use only the last snapshot in each day. Keep existing project-status, ARAS, and scheduled-archive response fields unchanged.

- [ ] Step 5: Run focused verification.

  ~~~powershell
  python -m pytest tests/test_deliverable_form_analysis.py tests/test_deliverable_form_api.py tests/test_project_status_analysis_api.py -q > .runtime/task2-form-api.log 2>&1
  python -m py_compile core/db_manager.py services/deliverable_form_analysis.py web/app.py > .runtime/task2-compile.log 2>&1
  ~~~

- [ ] Step 6: Review and commit.

  Verify request field allowlists, response redaction, artifact path handling, and migration idempotency, then commit:

  ~~~powershell
  git diff --check
  git add core/db_manager.py services/deliverable_form_analysis.py web/app.py tests/test_deliverable_form_api.py
  git commit -m "feat: add unified deliverable form snapshot APIs"
  ~~~

## Task 3: Publish PAA/NCR/EWO snapshots without changing sync safety

**Owner:** Main session.

**Files:**

- Modify: services/scheduled_archive_connectors.py
- Modify: services/scheduled_archive_runner.py
- Modify: services/project_status_sync_runner.py
- Modify: services/project_status_connectors.py only for the pure EWO form-row handoff
- Test: tests/test_scheduled_archive_connectors.py
- Test: tests/test_scheduled_archive_runner.py
- Test: tests/test_project_status_sync_runner.py

**Interfaces:**

- ArchiveCollection gains optional sanitized form_snapshot: FormSnapshotInput | None = None with a default preserving existing test doubles and callers.
- Successful PAA/NCR archive collection returns form snapshot input; NCR parses all approved worksheets and sets actual data row count instead of the current zero placeholder.
- Successful EWO project-status collection publishes a form snapshot alongside the existing ProjectStatusDeliverableAnalysisService.publish().
- Scheduled execution still calls validate_runtime_prerequisites=False; sync_now keeps the strict default.

- [ ] Step 1: Add connector fixture tests using synthetic rows and official-workbook fixtures.

  Assert PAA rows are sanitized, NCR progress reads approved worksheets, NCR detail preserves worksheet names and all three cost groups, and no credentials enter the returned collection.

- [ ] Step 2: Add scheduled publication tests.

  Assert a successful run writes both archive metadata and a form snapshot; a failed connector writes an auditable error and leaves the previous successful snapshot unchanged; scheduled missing credentials still creates a run after lease acquisition.

- [ ] Step 3: Add EWO publication regression tests.

  Assert the existing EWO analysis cache, mapping, business update, run state, and artifacts remain unchanged while the additive form snapshot is published.

- [ ] Step 4: Implement collection-to-snapshot handoff.

  Parse official NCR workbooks before finalization, keep original XLSX artifacts, publish sanitized form rows only after collection success, and treat parser failure as a bounded invalid-data/attention result without deleting the last good snapshot.

- [ ] Step 5: Verify credential and lease boundaries.

  Use fake credential providers and connectors that record method calls but never persist secret values. Assert scheduled and manual paths still differ exactly at the documented prerequisite gate.

- [ ] Step 6: Run focused sync/archive verification.

  ~~~powershell
  python -m pytest tests/test_scheduled_archive_connectors.py tests/test_scheduled_archive_runner.py tests/test_project_status_sync_runner.py tests/test_project_status_connectors.py -q > .runtime/task3-publication.log 2>&1
  python -m py_compile services/scheduled_archive_connectors.py services/scheduled_archive_runner.py services/project_status_sync_runner.py services/project_status_connectors.py > .runtime/task3-compile.log 2>&1
  ~~~

- [ ] Step 7: Review and commit.

  Main must inspect the diff for credential/lease leakage before:

  ~~~powershell
  git diff --check
  git add services/scheduled_archive_connectors.py services/scheduled_archive_runner.py services/project_status_sync_runner.py services/project_status_connectors.py tests/test_scheduled_archive_connectors.py tests/test_scheduled_archive_runner.py tests/test_project_status_sync_runner.py tests/test_project_status_connectors.py
  git commit -m "feat: publish auditable form snapshots from syncs"
  ~~~

## Task 4: Implement the desktop detail UI from the frozen API contract

**Owner:** AGY ui; Main reviews and integrates.

**Files:**

- Modify: web/static/app.js
- Modify: web/static/style.css

**AGY task contract:**

- Use the repository .agents/config.json, agy-heavy supervisor, configured gemini-3.7-flash-high, --sandbox, and an isolated worktree.
- Do not modify Python, database, authentication, credential, lease, connector, report-contract, or API files.
- Use only the additive form APIs and existing interactive query APIs defined in the spec.
- EWO/PAA/NCR progress render three chart tabs; NCR detail renders department-cost and section-cost tabs.
- Each chart tab has independent filter state and the filter controls listed in the spec.
- Chart clicks append current-tab filters; clear affects only the current tab.
- EWO keeps legacy chart labels, grouping/unmatched behavior, existing status chart, independent search, overview filters, tags, and accessibility.
- Render PAA/NCR form schemas from API metadata; preserve multilevel headers and horizontal scrolling.
- Show interactive results as temporary and background snapshots as persisted; never place secrets in browser state.

**Verification commands supplied to AGY:**

~~~text
["node", "--check", "web/static/app.js"]
["python", "-m", "pytest", "tests/test_overview_web.py", "tests/test_overview_external_deliverables_ui.py", "-q"]
~~~

- [ ] Step 1: Main records the backend commit and creates the bounded AGY task JSON.
- [ ] Step 2: Supervisor creates the isolated worktree and runs AGY with the exact scope and checks.
- [ ] Step 3: Main inspects the worker report, scoped patch, checks, and changed paths.
- [ ] Step 4: Main accepts only a diff with no backend/security/public-contract changes.
- [ ] Step 5: Main commits the reviewed UI diff in the primary worktree.

## Task 5: Add frontend contract and regression tests

**Owner:** AGY test-only; Main reviews and integrates.

**Files:**

- Modify/Create: tests/test_overview_web.py
- Modify/Create: tests/test_overview_external_deliverables_ui.py
- Modify: tests/test_scheduled_archive_admin_ui.py only for shared selector/accessibility regressions

**AGY task contract:**

- Use gemini-3.7-flash-low, --sandbox, the supervisor, and an isolated worktree.
- Modify tests only; do not alter production code or fixtures containing real business data.
- Assert three EWO/PAA/NCR-progress chart tabs, two NCR-detail cost tabs, per-tab filter state, click-to-filter selectors, daily trend labels, cost series labels, red/green cost semantics, multilevel table markers, interactive/background copy, empty/error states, and legacy EWO tag/chart markers.
- Assert no forbidden credential terms are placed in interactive payload helpers or browser storage code.

**Verification commands supplied to AGY:**

~~~text
["python", "-m", "pytest", "tests/test_overview_web.py", "tests/test_overview_external_deliverables_ui.py", "tests/test_scheduled_archive_admin_ui.py", "-q"]
~~~

- [ ] Step 1: Main prepares the exact UI selectors and API markers from Task 4.
- [ ] Step 2: Supervisor runs the test-only AGY task in a clean isolated worktree.
- [ ] Step 3: Main reviews assertions for meaningful behavior rather than string-only vacuous checks.
- [ ] Step 4: Main commits the reviewed test diff.

## Task 6: Main integration, review, and browser acceptance

**Owner:** Main session.

**Files:**

- Modify only when required by reviewed findings; no unreviewed broad refactor.
- Evidence: .runtime/

- [ ] Step 1: Review all AGY evidence and compare changed paths with task scope.

  A blocked or failed AGY run is recorded as blocked; never weaken sandbox or permissions. If the worker makes an out-of-scope change, reject it and implement the necessary fix in Main.

- [ ] Step 2: Run the required focused tests.

  ~~~powershell
  python -m pytest tests/test_project_status_sync_runner.py tests/test_project_status_admin_api.py tests/test_overview_web.py -q > .runtime/final-required-focused.log 2>&1
  ~~~

- [ ] Step 3: Run form/API/UI focused tests.

  ~~~powershell
  python -m pytest tests/test_deliverable_form_analysis.py tests/test_deliverable_form_api.py tests/test_overview_external_deliverables_ui.py tests/test_scheduled_archive_admin_ui.py -q > .runtime/final-form-ui-focused.log 2>&1
  ~~~

- [ ] Step 4: Run the complete regression and required static checks.

  ~~~powershell
  python -m pytest -q > .runtime/final-full-regression.log 2>&1
  python -m py_compile core/db_manager.py services/project_status_updates.py services/project_status_sync_runner.py main.py > .runtime/final-required-compile.log 2>&1
  node --check web/static/app.js > .runtime/final-node-check.log 2>&1
  git diff --check > .runtime/final-diff-check.log 2>&1
  ~~~

- [ ] Step 5: Run configured lint/type checks and classify baseline errors.

  ~~~powershell
  python -m flake8 > .runtime/final-flake8.log 2>&1
  python -m mypy core services web > .runtime/final-mypy.log 2>&1
  ~~~

  Compare failures with the pre-change baseline; only newly introduced errors block completion.

- [ ] Step 6: Build and save hashes.

  Use the repository build command and save complete output under .runtime/final-build.log; save resulting executable hashes under .runtime/final-build-output/SHA256SUMS.txt.

- [ ] Step 7: Start an isolated local UI test instance.

  Use an isolated SQLite database and local archive root. Do not use production credentials or production network. Verify EWO, PAA, NCR progress, and NCR detail page loads, tab switching, filters, chart clicks, empty states, and background/interactive labels.

- [ ] Step 8: Save desktop screenshots and inspect them visually.

  Save EWO department/section/trend, PAA, NCR progress, and NCR detail department/section cost screenshots under .runtime/. Screenshots must contain only synthetic or redacted data.

- [ ] Step 9: Perform Main final review.

  Review authentication/session boundaries, redaction, public API compatibility, data retention, daily trend selection, overdue formulas, cost aggregation, EWO legacy behavior, and AGY diffs. Final status is PASS only when every acceptance criterion and evidence path is satisfied.
