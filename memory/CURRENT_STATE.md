# Current State

Last checkpoint: 2026-09-02 (Codex). This file records the durable
continuation point for the deliverable UI redesign. Re-verify the repository
with `git status`, `git diff`, and `git log` before any implementation.

## Current objective

Continue the EWO/PAA/NCR deliverable detail UI redesign in ZCode. The user has
confirmed the architecture and the NCR aggregation grain. The work is paused
before preview regeneration; production code must not be changed until the
new preview is reviewed and approved.

## Confirmed product decisions

- EWO, PAA, and NCR approval progress each use three chart tabs:
  department status, section/region status, and daily quantity trend.
- NCR approval detail uses department cost and section cost tabs.
- One NCR maps to exactly one EWO; one EWO may map to multiple NCRs.
- NCR progress status/trend counts distinct `NCR编号`.
- NCR detail status/trend also counts distinct `NCR编号`.
- NCR detail costs sum detail rows; department is the all-region total and
  section is `区域`.
- Positive cost change is red; negative cost change is green.
- EWO dimensions: `部门` and `责任工程师专业科室`.
- PAA dimensions: `部门` and `专业科室`.
- NCR section dimension: `区域`; department is the fixed business aggregate.
- The default Aras business department is the exact source value
  `技术中心_车体工程`.
- Each chart tab owns its filters; same-field selections are OR and different
  fields are AND. Filters include status, department, section/region,
  model/project, stage/node, overdue state, dates, keyword, and relation.
- Trend nodes represent the latest snapshot of a natural day. Submission date
  and snapshot date must remain separate concepts.

## Real workbook evidence

Read-only audits of the supplied workbooks found:

- EWO: 399 rows, 111 columns; department is `技术中心_车体工程`; 13
  professional sections; stage-arrival columns are present.
- PAA: 54 rows, 113 columns; department is `技术中心_车体工程`; 7
  professional sections; vehicle values include composite strings.
- NCR progress: 387 rows, 64 columns; 387 unique NCRs; 385 EWO values; two
  EWO values each relate to two NCRs; full approval-node/date fields exist.
- NCR detail: 3768 rows, 387 unique NCRs; 366 NCRs have multiple detail rows;
  the maximum is 168 detail rows per NCR. Six tooling/per-vehicle cost fields
  are present; the engine worksheet is empty in the supplied workbook.

Local field-only evidence (no raw business rows or credentials):

- `.runtime/real-form-counts-20260902.json`
- `.runtime/ncr-ewo-cardinality-20260902.json`
- `.runtime/real-form-schema-20260902.json`

## Root causes already identified

1. The table chooses the first 12/17 columns, hiding workflow dates, approval
   nodes, and NCR cost columns.
2. Static stage lists omit EWO/PAA `OPEN`/`CANCEL` and several official NCR
   approval nodes.
3. EWO/PAA scheduled list queries do not yet prove that stage-arrival dates are
   included, so missing dates correctly become `unknown` rather than a safe
   on-time result.
4. Frontend selects and backend SQL currently support scalar filters only;
   chart clicks overwrite instead of append, and `overdueState` is not fully
   exposed in the UI.
5. The fixed one-row filter grid plus `overflow-x:hidden` clips right-side
   content. Project detail information is always expanded.
6. Built-in scheduled jobs have empty filters; business department appears as
   a placeholder rather than an effective default.
7. Mapping editor values expose internal source keys such as `_rsp_name` and
   `_required_date` instead of Chinese field labels.
8. NCR normalized department is empty and has no dedicated `EWO号` relation
   filter. The current NCR detail row count must not be treated as NCR count.

Relevant implementation locations include:

- `services/deliverable_form_analysis.py`
- `services/scheduled_archive_connectors.py`
- `core/db_manager.py`
- `web/app.py`
- `web/static/app.js`
- `web/static/style.css`

## Current workspace constraints

Preserve all existing uncommitted changes. Current known changes include the
DPAPI, Aras timeout, XLSX size-limit, AGY CLI hardening, and memory/AGENTS
changes. Do not reset, clean, checkout, or overwrite them. The source WebUI is
running at `http://127.0.0.1:5000/#scheduled-archive` when available; do not
restart or stop it unless necessary and safe.

No credentials, cookies, tokens, raw production workbook rows, or complete
business data may enter source control, preview HTML, logs, tests, memory, or
ZCode handoffs.

## Exact next action

1. In ZCode, read this file and the other memory files, then verify the current
   worktree.
2. Recreate `.runtime/deliverable-forms-preview.html` using real Chinese
   headers plus synthetic/redacted example rows. The prior preview generation
   was interrupted after the old ignored preview file was removed.
3. Start or reuse a local preview server, inspect the page, and save screenshots
   under `.runtime/`.
4. Stop and wait for the user to approve the preview. Do not edit production
   code before that approval.
5. After preview approval, implement the additive API/data contract, relation
   filters, aggregation grain, UI layout, and tests, followed by code review
   and full verification.

## Completion criteria

- Preview is approved before production-code edits.
- EWO/PAA/NCR progress have correct three-tab charts and filters.
- NCR detail has correct two-tab cost charts and row-grain cost sums.
- EWO/NCR relation filtering and reverse navigation are correct.
- Existing authentication, credential redaction, lease behavior, public APIs,
  EWO legacy charts/tags, and scheduled sync behavior remain compatible.
- Focused tests, full tests, compile, Node syntax, lint/type baseline review,
  browser screenshots, and final code review are complete.
- Final review is explicitly `PASS` only after evidence is saved under
  `.runtime/`.
