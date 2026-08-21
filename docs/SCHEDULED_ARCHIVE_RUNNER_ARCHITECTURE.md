# Scheduled Archive Runner Architecture

## Boundary

The archive scheduler is a one-shot process invoked by Windows Task Scheduler.
It does not run a permanent scheduler inside Flask. Its persistence is separate
from `project_status_sync_runs` so archive-only reports are not represented as
dashboard deliverables.

## Stable jobs

| Job key | Source/report | Optional dashboard link | Proven official file |
| --- | --- | --- | --- |
| `aras_ewo` | ARAS EWO | `VPI-T2-D3` | Not exposed by the current crawler; archive normalized CSV/JSON |
| `aras_paa` | ARAS PAA | none | Not exposed by the current crawler; archive normalized CSV/JSON |
| `aras_ncr_progress` | ARAS NCR progress | none | Remote downloaded workbook |
| `aras_ncr_detail` | ARAS NCR detail | none | Remote downloaded workbook |
| `tdc_data_model` | TDC data-model | `VPI-T2-D5` | Official XLSX export |
| `tdc_sor` | TDC SOR | `VPI-T2-D2` | Official XLSX export |

No TDC A-face job is created until its real contract is approved.

## Persistence

- `scheduled_archive_jobs` owns non-secret configuration, the opaque
  `credential_ref`, interval, filters, optional approved-root subdirectory,
  freshness state, and the per-job lease.
- `scheduled_archive_runs` records one invocation attempt and its sanitized
  terminal state. A failed run never clears `last_success_at` or prior files.
- `scheduled_archive_artifacts` records only controlled-root relative paths,
  display name, type, size, SHA-256, creation time, and archive run ownership.
- List/API methods omit `credential_ref` and expose only
  `credentialConfigured: bool`.

## Execution flow

1. Select due, enabled jobs without returning their credential alias.
2. Acquire one atomic lease for the job and create a leased run.
3. Read the opaque alias through an internal-only method and resolve it through
   the credential provider for the shortest possible lifetime.
4. Call a fixed registry connector. The connector returns normalized collection
   metadata and controlled-root artifact metadata; it never writes database
   state.
5. In one lease-token-protected transaction, validate artifact metadata,
   finalize the run, release the lease, and update freshness.
6. Optional dashboard linking consumes the saved collection through the unified
   project-status update service. It is blocked until mapping stability,
   explicit field approval, and credential readiness are satisfied.

## Safety invariants

- Missing configuration is `needs_attention`, before any external call.
- One job cannot run concurrently with itself; different jobs are independent.
- Total attempts are at most two with exponential backoff for transient I/O.
- Paths remain beneath the approved archive root; artifacts are atomically
  published and never overwrite an existing name.
- Retention is a separate explicit command with dry-run; synchronization never
  deletes old artifacts.
- Errors and reports are redacted and bounded. Raw responses, cookies,
  authorization values, usernames, and secret values never enter SQLite,
  logs, API responses, or UI state.
