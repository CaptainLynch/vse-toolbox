# Current State

Last checkpoint: 2026-09-02 (Codex). Re-verify the repository with
`git status`, `git diff`, and `git log --oneline -5` before any new work.

## Current objective

The EWO/PAA/NCR unified deliverable form analysis and UI work is complete at
`5194820`. The migration cleanup, persistent memory layer, and post-release
hardening are committed on branch
`feature/scheduled-deliverables-overview-excel`:

- `82827f5 chore: retire legacy agent subsystem`
- `86238b9 chore: add persistent project memory`
- `785c650 fix: harden delivery and agent workflows`

Production-network acceptance remains intentionally unclaimed because no
production credentials were used in verification.

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

## Verification status

- Full pytest on the committed tree: `1629 passed, 2 skipped` using the
  repository `.venv` (Python 3.11.9).
- Scoped flake8 over the eight hardening Python files passes.
- Repository-wide `python -m flake8` returns 1 because `setup.cfg` does not
  exclude `.venv` or `.agents/worktrees`, and the scan also reports existing
  project lint errors. This baseline is accepted for this migration.
- UTF-8 mypy under both system Python 3.14 and repository Python 3.11 reports
  the same 69 existing errors in 13 files; no new error was found at a changed
  hardening line. This baseline is accepted for this migration.
- `git diff --check HEAD` passes. Windows LF-to-CRLF warnings are benign.

## Current workspace constraints

The migration changes are committed and the worktree should remain clean.
Do not reset, clean, checkout, or overwrite unrelated future changes. The
source WebUI is running at `http://127.0.0.1:5000/#scheduled-archive` when
available; do not restart or stop it unless necessary and safe.

No credentials, cookies, tokens, raw production workbook rows, or complete
business data may enter source control, preview HTML, logs, tests, memory, or
ZCode handoffs.

## Exact next action

Verify `git status --short --branch` and `git log --oneline -5` after this
checkpoint commit. The branch is ready for the user's preferred integration
action; no code changes are pending in this migration.

If future work targets repository-wide quality gates, handle the flake8 scan
scope and the existing mypy errors as a separate, explicitly scoped task.

## Completion criteria

- Unified deliverable analysis/UI, migration cleanup, memory layer, and
  hardening changes are committed on the current branch.
- Full pytest and scoped hardening flake8 checks pass.
- The accepted repository-wide flake8/mypy baseline is documented in this
  file and `RECOVERY_NOTES.md`.
- Working tree is clean after the checkpoint commit.
- Production-network acceptance remains unclaimed without production
  credentials.
