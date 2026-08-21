# Scheduled Deliverables, Overview Analytics, and Excel Web Architecture

## Decision baseline

- The standalone `ProjectStatusSyncRunner.run_once` remains the only scheduled
  execution model. Windows Task Scheduler invokes `main.py project-status-sync
  --once`; Flask never owns a permanent scheduler.
- Connectors authenticate with a short-lived credential resolved from Windows
  Credential Manager by opaque `credential_ref`. SQLite, API payloads, logs and
  diagnostics never contain credential values.
- Connectors return a normalized snapshot and archive payloads. They never write
  project-status rows. `ProjectStatusUpdateService` remains the only automatic
  business-field writer and enforces field authority, optimistic concurrency,
  audit, idempotency, and needs-attention outcomes.
- Official XLSX and normalized CSV/JSON are written atomically beneath an
  approved root. Artifact rows contain relative paths and hashes only. Retention
  is a separate explicit command and defaults to a 90-day dry-run plan.
- D1 is manual-only. D2=TDC SOR, D3=Aras EWO, D5=TDC data-model. D4=TDC A-face
  stays blocked until its request contract is verified. PAA and NCR exports are
  archive-only and do not update the five dashboard deliverables.
- Unknown status mappings, missing fields, zero matches, ambiguous matches, and
  unstable external keys are evidence, not business values. They produce
  `needs_attention`. Two consecutive unambiguous observations of the same key
  are required before sync can be approved.
- Excel COM work runs in a single-process serial queue outside request parsing.
  Inputs are uploads streamed to a controlled workspace or files selected by
  opaque IDs beneath approved roots. Every operation creates a new result.

## Data flow

`Task Scheduler / sync-now -> lease -> credential_ref resolution -> fixed-host connector -> official export + normalized candidate -> atomic archive -> candidate validation/diff -> unified update service -> saved project status + run/audit/artifact evidence -> dedicated history/analytics APIs -> dashboard`

`Web request -> validate operation schema and controlled file references -> durable Excel job -> serial COM worker -> new output + backup metadata -> job history/download API`

## Public-contract boundary

`/api/overview` is unchanged. New project-status history, discovery, preview,
sync-now, artifacts, analytics, archive-root, and Excel-job endpoints use the
existing `{ok,data}` / sanitized `{ok:false,error}` response convention.
