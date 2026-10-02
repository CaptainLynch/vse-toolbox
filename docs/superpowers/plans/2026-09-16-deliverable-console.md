# Deliverable console implementation plan

Status: implementation, integration and independent Luna/max review completed on 2026-09-16. This is a consumed execution plan; manual UI acceptance remains pending.

Results: backend integrated regression 547 passed / 1 UI case deselected; after final A2 correction, focused backend regression 141 passed (overlapping coverage, not additive). No UI tests were run. Static JavaScript syntax and project-map checks passed.

See [final audit](../../DELIVERABLE_CONSOLE_AUDIT_20260916.md) and [manual UI checklist](../../DELIVERABLE_CONSOLE_UI_TODO_20260916.md).

## Approved scope
Implement the eight findings approved in conversation on 2026-09-16. Preserve EWO read-only enrichment and generation recovery. Mapped deliverables are entirely read-only; unconfigured defaults remain editable. PAA and NCR get snapshot progress cards without becoming formal phase deliverables. Remove project risk and external sync cards; hide node delivery/risk placeholders until membership is configured.

## Execution constraints
- User explicitly selects gpt-5.6-luna with max reasoning for parallel agents, overriding default Gemini routing.
- Independent writer worktrees; lead reviews contracts, actual diff and backend evidence before integration. Do not take over a worker without a concrete reason.
- Backend tests only. No UI unit tests, browser tests, frontend test execution, or UI test changes. Deliver manual UI TODOs.
- No production requests, database changes, packaging, commits or pushes in this task.

## Contracts and tasks
- [x] A / backend: core/db_manager.py, core/project_status_contracts.py, services/project_status_updates.py, web/app.py and focused backend tests. Return manualEditable and readOnlyReason on serialized deliverables. Determine mapping from configured record target or aggregate/versioned selection, not mode/source metadata alone. Malformed configured binding fails closed. Recheck in the write transaction with concurrency protection; mapped PATCH returns 409 MappedDeliverableReadOnly without successful update/audit or authority changes.
- [x] B / frontend: web/static/app.js only. Consume manualEditable === true (missing capability fails closed), guard every manual edit entry. Batch filter drafts until Apply; preserve filter DOM during loading/failure. Add two read-only snapshot cards for aras_paa and aras_ncr_progress using existing form APIs and their authoritative summary; NCR detail is drilldown, not another counted deliverable. Keep scope and snapshot time visible; no snapshot/empty never 100%; no formal node inclusion. Remove obsolete renderProjectRisks/renderExternalSyncSummary calls and container references.
- [x] C / panels: web/static/ewo-enrichment.js, web/static/node-overview.js, web/templates/dashboard.html and narrowly scoped style additions if necessary. Business-first EWO title/results, collapsed task diagnostics, state-appropriate primary action preserving unknown-generation guard. Remove two unwanted overview cards, hide unconfigured node delivery/risk sections while retaining node timing and plan editor.
- [x] Lead: integrate reviewed worktree diffs, select and run only backend regression tests; independent whole-change code audit then owner-directed repairs; record UI manual checklist and final memory checkpoint.

## Interface/conflict preflight
| Tasks | Interface or overlap | Ruling |
|---|---|---|
| A/B | manualEditable + readOnlyReason | Explicit booleans, frontend missing value fails closed; API is authoritative |
| B/C | app.js mount calls vs EWO/node/template exports | Keep module exports and mount contract; B owns app.js removal of obsolete calls |
| A/C | None | Separate files |
| A | Tests vs implementation | Synthetic backend fixtures only |
| B | UI behavior vs verification | Code inspection and user manual TODO, no UI tests |
| C | UI behavior vs verification | Code inspection and user manual TODO, no UI tests |

## Verification
Backend permission cases: unconfigured automatic and manual editable; configured single/set mappings read-only even paused or failed; malformed target fail-closed; no mutation on denial; stale record conflict preserved. Existing backend EWO and form snapshot tests remain relevant. Final suite must explicitly exclude frontend-source assertion and browser/Node wrappers, including mixed files' UI test cases.

