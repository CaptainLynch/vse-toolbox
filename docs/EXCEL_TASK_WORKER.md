# Excel Task Worker

The Excel task worker is a local-only process. It does not expose an HTTP
write interface and does not upload or download files.

## Commands

Process at most one queued task:

```powershell
python tools/excel_worker_cli.py run-once `
  --db data/vse_toolbox.db `
  --root business=D:\ApprovedExcel
```

Continuously poll until `Ctrl+C`, `SIGTERM`, or the Windows console break
signal requests shutdown:

```powershell
python tools/excel_worker_cli.py run `
  --db data/vse_toolbox.db `
  --root business=D:\ApprovedExcel
```

Repeat `--root ID=PATH` for additional approved directories. Root IDs and
relative task paths are stored in SQLite; task records do not store approved
root absolute paths.

## Results

`run-once` reports one of these statuses:

- `idle`: no queued task was available; exit code `0`.
- `succeeded`: output was atomically committed and completion was recorded;
  exit code `0`.
- `failed`: execution or completion recording failed; exit code `1`.
- `lease_lost`: the worker can no longer modify the task run; exit code `1`.

The `output_committed` field distinguishes failures before the final file was
published from database completion failures after publication. A committed
output is never rolled back merely because the completion record failed.

On success, the worker calculates the committed file's byte size and SHA-256.
The succeeded task state, succeeded run state, and one output artifact record
are then written in a single lease-guarded SQLite transaction. Artifact rows
store only an approved root ID and normalized relative path, never a server
absolute path.

Continuous mode reports counts for processed, succeeded, failed, and
lease-lost tasks. A failed task does not prevent later queued tasks from
running.

## Shutdown And Recovery

A stop signal prevents the worker from leasing another task. The current
Excel operation retains its lease, performs its normal workbook and Excel
application cleanup, and then the process exits.

If the process terminates unexpectedly, the repository's stale-lease recovery
marks the active run expired. Retry occurs only when the task was explicitly
created with remaining attempts. The default remains one attempt because the
Excel transformations are not assumed to be generally idempotent.

Automated tests use fake executors and do not start real Excel COM, use real
business workbooks, or access credentials.

## Local Management API

When the Flask app is created with server-side approved roots, the local API
also exposes:

- `GET /api/excel-roots`
- `GET /api/excel-worker/status`
- `POST /api/excel-worker/start`
- `POST /api/excel-worker/stop`

Root discovery via `GET /api/excel-roots` returns sorted canonical root ID objects
(`[{"rootId": "..."}]`) with `Cache-Control: no-store`. It never exposes server
absolute paths, filesystem properties, environment variables, or credentials.

Start and stop are loopback-only, same-origin mutations. They control one
dedicated Windows worker process by default and never accept an executor, root
path, or COM handle from the request body. The optional in-process controller exists for explicit test/development configuration only. Starting an already-running worker returns `409`; stopping is graceful and signals the worker to finish cleanup before the controller reports `stopped`.

## Packaging And Process Boundary

To maintain process isolation and prevent Office COM dependencies from polluting
the Flask WebUI process:

- `VSE-WebUI.spec` packages the Flask web application and explicitly excludes
  Excel COM modules (`xlwings`, `win32com`, `pythoncom`, `pywintypes`).
- `VSE-ExcelWorker.spec` targets `tools/excel_worker_cli.py` and bundles the
  required Excel COM and `xlwings` dependencies into a dedicated executable (`VSE-ExcelWorker.exe`).
- `tools/build_excel_bundle.ps1` automates building both specifications into a single
  caller-selected directory, isolates intermediate work directories under `.runtime`,
  and strictly verifies that both sibling executables exist and are regular files.
- In packaged production deployments (`sys.frozen`), `ExcelWorkerProcessController`
  launches the sibling `VSE-ExcelWorker.exe` directly in a subprocess without
  invoking python scripts. If the executable is absent or not a regular file, the
  controller fails closed with a path-free `RuntimeError`.
- In development/source environments, `ExcelWorkerProcessController` launches
  `python tools/excel_worker_cli.py`.
- Executable paths are never accepted from HTTP requests or environment variables.

## Production Configuration

Production approved roots are configured via the `VSE_EXCEL_ROOTS_JSON` environment
variable, a JSON object mapping root IDs to absolute directory paths (up to 16 roots).
If unset or empty, the Excel task APIs remain unconfigured (returning `503`).

## Artifact API And Retention Planning

The read-only artifact surface is:

- `GET /api/excel-tasks/<task_id>/artifacts`
- `GET /api/excel-artifacts/<artifact_id>`
- `GET /api/excel-artifacts/<artifact_id>/download`
- `GET /api/excel-artifacts/<artifact_id>/download-audit`
- `GET /api/excel-artifacts/retention-plan`

Downloads accept only the server-issued artifact ID. The service resolves the
stored reference through the configured approved roots, rejects traversal,
unsupported extensions, directories, and reparse points, reads the file into
memory, and verifies both byte size and SHA-256 before returning an attachment.
Missing, replaced, or tampered files fail closed with a generic response that
does not disclose filesystem paths.

Download decisions on known artifacts are recorded in an append-only audit table
(`excel_artifact_download_audit`) containing only artifact ID, task ID, result
(`succeeded` or `rejected`), bounded non-sensitive reason code, served byte count on success,
and UTC timestamp. The audit metadata can be queried via `GET /api/excel-artifacts/<artifact_id>/download-audit`
(newest-first, bounded to 1..200, default 50) without disclosing internal paths, IP addresses,
or request headers.

Retention planning via `GET /api/excel-artifacts/retention-plan` is strictly read-only
and operates exclusively on persisted database metadata timestamps (`created_at`).
It accepts:

- `retentionDays` (required integer, `1..3650`): identifies artifacts created on or before
  `now(UTC) - retentionDays`.
- `limit` (optional integer, `1..500`, default `200`): bounds candidate results.

The endpoint returns:

- `cutoffAt`: UTC ISO timestamp cutoff used for evaluation.
- `truncated`: boolean indicating whether additional eligible records exist beyond `limit`.
- `artifacts`: list of matching artifact records ordered oldest-first with deterministic ID tie-breaking.

Retention planning never accesses the filesystem, never deletes or moves files, and introduces
no mutable retention or deletion APIs. These endpoints do not start or call Excel COM and do not control the worker process.

