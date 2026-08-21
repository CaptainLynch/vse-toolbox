# VSE Toolbox - GPT Web Project Context

Snapshot date: 2026-08-20

## 1. Project Positioning

VSE Toolbox is a Windows-first internal project-management toolbox for collecting,
exporting, analyzing, and presenting delivery data from Aras, TDC, Excel, and
selected internal sources. It has both a legacy CLI and a Flask-based local WebUI.
The WebUI is packaged as a single-file PyInstaller executable for internal use.

Treat the current source tree as the authority. `README.md` still describes an
earlier CLI-only shape and is not a complete description of the current WebUI.

## 2. Current Branch and Workspace State

- Active development branch: `feature/scheduled-deliverables-overview-excel`
- Baseline checkpoint: `checkpoint-tdc-auth-20260820` (`616d611`)
- The working tree contains parallel, uncommitted work. Never reset, revert, or
  reformat unrelated changes. Keep each new feature in a small, separately
  reviewable commit.
- Generated files, diagnostics, local databases, `dist/`, `build/`, and
  `.runtime/` are not source-of-truth code and must not be committed casually.

## 3. Runtime and Architecture

- Platform: Windows, Python 3.12, local SQLite, Flask, pywin32/xlwings, and
  PyInstaller.
- Main Web entry: `web/app.py`.
- Web assets: `web/templates/dashboard.html`, `web/static/app.js`, and
  `web/static/style.css`.
- Persistent storage: `core/db_manager.py` with SQLite transactions, foreign
  keys, WAL, project-status seed data, and optimistic concurrency timestamps.
- Secret redaction and safe diagnostics: `core/redaction.py`,
  `core/diagnostics.py`, and `core/runtime_paths.py`.
- Service code must not import Flask. `web/app.py` owns HTTP serialization and
  route-level validation.
- CLI entry: `main.py`; it remains useful for one-off operations and is the
  preferred future host for scheduled `--once` runs.

## 4. Implemented Capabilities

### Aras

- `services/aras_auth.py`: enterprise OIDC code flow, user-info lookup,
  ADValidate bridge, Innovator internal OAuth password grant, then SOAP session
  validation. Credentials and tokens are redacted and short-lived in memory.
- `services/aras_crawler.py`: EWO, PAA, NCR progress, and NCR detail querying;
  fuzzy-search syntax support where the source system permits it; NCR detail
  calls use a longer receive timeout because server-side export generation is
  slow.
- `services/aras_export.py`: CSV export helpers.
- WebUI supports preview, crawl/export, and official NCR XLSX downloads.

### TDC

- `services/tdc_auth.py`: enterprise OIDC authorization-code login, native
  WinHTTP session handoff on Windows, browser-compatible token-exchange request
  contract, Basic client authentication for the exchange, and safe Markdown
  diagnostics.
- `services/windows_http.py`: WinHTTP COM transport, response decompression,
  cookie support, request timeout handling, and response compatibility helpers.
- `services/tdc_crawler.py`: TDC data-model and SOR querying, crawl-all, and
  XLSX export. A-face remains intentionally unavailable until a verified source
  contract exists.
- TDC password authentication was validated successfully and checkpointed before
  this branch was created.

### Project Status Overview

- The dashboard contains a read-oriented project-status overview and a
  deliverable-detail workspace.
- `GET /api/project-status` and manual `PATCH` updates are implemented with
  validation and optimistic concurrency.
- `core/db_manager.py` contains dedicated project-status phase, milestone,
  deliverable, update-policy, field-authority, and audit tables.
- `services/project_status_updates.py` centralizes manual updates, policy
  validation, field authority, and sanitized audit records.
- The current automatic-update policy model is a guarded TDC pilot. It stores
  only non-sensitive matching and mapping metadata; it does not yet execute
  external synchronization.

### Excel

- `services/excel_toolbox.py` is implemented for append merge, overlay merge,
  baseline comparison, automatic backup, rollback, and source-color legends.
- It uses xlwings/Excel COM for DLP-compatible local workbook operations.
- The current Excel toolbox is CLI-only. The WebUI catalog correctly labels it
  as not yet having a Web execution surface.

## 5. New Feature Goals for This Branch

1. Scheduled delivery collection:
   - Schedule Aras and TDC delivery collection.
   - Persist downloaded/exported artifacts to controlled local output folders.
   - Link successful, partial, and failed runs to project-status deliverables.
2. Better project-status visualization and analysis:
   - Show status, freshness, source, run result, trends, risk, and material
     differences from collected deliverables.
   - Do not fabricate associations. Each automated link needs a stable external
     key, allowed filter/match rule, and explicit field mapping.
3. Web Excel toolbox:
   - Expose the existing Excel service through a safe local WebUI workflow.
   - Support selecting local files, operation-specific inputs, progress/error
     states, output download/open location, and backup visibility.

## 6. Non-Negotiable Design Constraints

- Do not run a permanent scheduler thread inside Flask. Implement a standalone
  `run_once` service/CLI command and invoke it with Windows Task Scheduler.
- External connectors return normalized candidate updates; they must not write
  project-status tables directly.
- Manual values win by default. Scheduled work must respect field authority and
  never silently overwrite a manually locked field.
- A failed run keeps the last successful data and records a sanitized failure;
  it must not clear the dashboard or claim success.
- No real password, Cookie, Authorization header, token, full raw HTTP payload,
  or credential value may be stored in SQLite, browser storage, diagnostics,
  logs, test fixtures, prompts, or UI responses.
- Unattended authentication requires a separately approved Windows Credential
  Manager or equivalent credential-reference design. Do not persist plaintext
  credentials merely to make scheduling work.
- Preserve the existing `/api/overview` contract. Add dedicated APIs rather
  than changing unrelated public endpoints.
- Reuse current host allowlists, redaction helpers, response conventions, and
  focused tests. Do not introduce cryptography/RSA work or change established
  OIDC scopes without concrete evidence.

## 7. Recommended Delivery Sequence

1. Define the shared scheduling domain model: bindings, run state, artifact
   metadata, lease, retry policy, and sanitized audit trail.
2. Implement an independent sync runner with `--once`, then test it through
   Windows Task Scheduler. Start with one verified TDC or Aras binding rather
   than enabling every deliverable at once.
3. Add artifact persistence and project-status linkage after stable external
   keys and field mappings are confirmed.
4. Build overview API data for freshness, trends, differences, and analysis;
   then render it in the existing dashboard without mixing it with edit drafts.
5. Implement the Excel WebUI using the existing `ExcelToolbox` service. Keep
   workbook COM work outside request parsing and protect against path traversal,
   locked files, and unbounded file selection.

## 8. Testing and Packaging Expectations

- Add focused service, database/API, and WebUI tests for each feature.
- Authentication, authorization, diagnostics, file-system writes, concurrency,
  and scheduled-run leases require negative tests, not only happy paths.
- Run the relevant regression suite before each checkpoint. Redirect long logs
  to `.runtime/`.
- Build the frozen executable with `python -m PyInstaller --noconfirm --clean
  VSE-WebUI.spec` only after source tests pass.
- The executable is ignored by Git; archive a hash with any distribution when
  needed.

## 9. GPT Web Prompt Template

Use this context before asking for implementation work:

```text
You are working in the VSE Toolbox repository on branch
feature/scheduled-deliverables-overview-excel.

Read GPT_WEB_PROJECT_CONTEXT.md first. Treat the current source tree, not the
legacy README, as authoritative. The worktree is dirty: preserve all unrelated
changes and do not reset, revert, or reformat files outside the approved scope.

Task:
[describe one bounded feature or investigation]

Approved scope:
[list files/modules and expected behavior]

Do not:
- store or reveal passwords, tokens, Cookies, Authorization headers, or raw
  external responses;
- start a scheduler inside Flask;
- change existing public APIs unless explicitly listed;
- invent an external-system field mapping without HAR/code/business evidence.

For scheduled external collection, use an independent run_once runner suitable
for Windows Task Scheduler. External sources produce candidate updates; the
shared project-status update service owns validation, locks, audit, and writes.

Before editing, summarize evidence, risks, proposed files, and acceptance
tests. After implementation, run focused tests, report exact files changed,
remaining risks, and whether a PyInstaller rebuild is required.
```

## 10. Questions to Resolve Before Broad Automation

- Which specific project-status deliverables map to which Aras/TDC records?
- What stable external key and allowed filter identify each mapping?
- Which source owns each field, and which fields remain manual-only?
- What local output retention, naming, and cleanup policy is required?
- Which credential-reference mechanism is approved for unattended Windows tasks?
- What Excel operations are required in the WebUI beyond the existing append,
  overlay, and baseline-diff operations?
