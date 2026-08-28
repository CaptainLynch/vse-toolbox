# Excel Operations Production Acceptance & Deployment Guide

This document defines the production configuration, operational boundaries,
dual-executable packaging, lifecycle control, integrity audit, rollback
procedures, and manual production verification steps for VSE Toolbox Excel
Operations.

---

## 1. Architectural Overview & Boundaries

The Excel subsystem operates under strict process and capability boundaries:

- **Web Application Process (`VSE-WebUI.exe`)**:
  - Hosts the Flask web interface and REST API.
  - Excludes all Office COM dependencies (`xlwings`, `win32com`, `pythoncom`, `pywintypes`).
  - Read-only artifact downloads verify file integrity in-memory without invoking COM.
  - Local lifecycle API endpoints (`/api/excel-worker/*`) are loopback-only and same-origin.
- **Worker Process (`VSE-ExcelWorker.exe`)**:
  - Independent Windows CLI process (`tools/excel_worker_cli.py`).
  - Bundles Excel COM and `xlwings` dependencies.
  - Leases tasks from SQLite using CAS (Compare-And-Swap) concurrency controls.
  - Performs workbook transformations and commits artifacts atomically.
- **Data & Storage Containment**:
  - Approved roots whitelist prevents directory traversal, reparse point exploitation, and path escaping.
  - Database stores only canonical root IDs and normalized relative paths; absolute server paths are never persisted or returned via HTTP.

---

## 2. Environment Configuration

### Approved Roots (`VSE_EXCEL_ROOTS_JSON`)

Production roots are configured exclusively via the `VSE_EXCEL_ROOTS_JSON` environment variable:

```json
{
  "business": "D:\\ApprovedExcel\\Business",
  "archive": "D:\\ApprovedExcel\\Archive"
}
```

**Validation & Safety Invariants**:
- Must be a valid JSON object mapping string root IDs to absolute filesystem directory paths.
- Maximum 16 roots allowed.
- Root IDs must be non-empty, NFKC-canonicalized, contain no path separators (`/`, `\`, `:`), and avoid Windows device names (`CON`, `PRN`, `AUX`, `COM1-9`, `LPT1-9`).
- Target directories must exist, be regular directories, and contain no symlinks or junction points in their entire parent hierarchy.
- When `VSE_EXCEL_ROOTS_JSON` is unset or empty, the Excel API routes fail closed and return `503 NotConfigured`.

### Network & Loopback Configuration

- Web service binds to `127.0.0.1` (or configured loopback host) by default.
- Mutation endpoints (`POST /api/excel-worker/start`, `POST /api/excel-worker/stop`, `POST /api/excel-tasks`) require loopback origins and same-origin `Sec-Fetch-Site` validation.

---

## 3. Database Schema & Pre-Deployment Backup

### Pre-Deployment Backup Procedure

Before applying application upgrades or running migrations on production SQLite databases:

1. Stop any active `VSE-ExcelWorker.exe` and `VSE-WebUI.exe` processes.
2. Execute a timestamped database backup:

```powershell
Copy-Item data\vse_toolbox.db "data\vse_toolbox.db.backup-$(Get-Date -Format 'yyyyMMdd_HHmmss')"
```

3. Verify SQLite backup integrity using the SQLite CLI or Python:

```powershell
python -c "import sqlite3; conn = sqlite3.connect('data/vse_toolbox.db'); print('Integrity:', conn.execute('PRAGMA integrity_check').fetchall())"
```

### Table Schemas & Indexes

The Excel operations subsystem relies on the following schema definitions:

- `excel_tasks`: Core state machine records with `idempotency_key_hash`, `request_fingerprint`, `status` (`queued`, `leased`, `running`, `succeeded`, `failed`, `cancelled`), `lease_token`, and lease expiration timestamps.
- `excel_task_files`: File references mapped to tasks with role (`source`, `target`, `baseline`, `output`), `ordinal`, `root_id`, and `relative_path`.
- `excel_task_runs`: Audit history of each lease attempt with `run_state` (`leased`, `running`, `succeeded`, `failed`, `expired`, `cancelled`).
- `excel_task_artifacts`: Output artifacts recorded on task success with `root_id`, `relative_path`, `display_name`, `size_bytes`, and `sha256`.
- `excel_artifact_download_audit`: Append-only audit trail recording download attempts, results (`succeeded`, `rejected`), reason codes, served byte counts, and timestamps.

---

## 4. Sibling Executable Dual Build & Deployment

### Build Script (`tools/build_excel_bundle.ps1`)

Execute the automated dual-executable build script:

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_excel_bundle.ps1 -OutputDir "dist"
```

**Build Guarantees**:
1. Invokes PyInstaller for `VSE-WebUI.spec` into the target directory.
2. Invokes PyInstaller for `VSE-ExcelWorker.spec` into the target directory.
3. Isolates intermediate work directories beneath `.runtime\build_excel_bundle`.
4. Confines cleanup strictly to verified paths within repository `.runtime`.
5. Post-build verification asserts both `VSE-WebUI.exe` and `VSE-ExcelWorker.exe` exist and are regular files.
6. Writes `SHA256SUMS.txt` beside both executables for deployment integrity verification.

### Deployment Directory Structure

Both sibling executables must reside in the same directory:

```text
C:\Program Files\VSE-Toolbox\
├── VSE-WebUI.exe          # Flask Web Application (excludes Excel COM)
├── VSE-ExcelWorker.exe    # Excel Worker CLI (bundles Excel COM)
├── data\
│   └── vse_toolbox.db
└── .runtime\              # Isolated runtime and logs
```

When running in packaged mode (`sys.frozen`), `ExcelWorkerProcessController` automatically discovers and spawns the sibling `VSE-ExcelWorker.exe`. If missing, it fails closed without executing untrusted binaries.

---

## 5. Worker Process Lifecycle & Concurrency

### Process Management

- **Status Query**: `GET /api/excel-worker/status` returns current state and, when available, worker PID or exit code.
- **Start**: `POST /api/excel-worker/start` spawns `VSE-ExcelWorker.exe run` as a dedicated background process with standard streams disconnected from the WebUI. Returns `409 Conflict` if already running.
- **Graceful Stop**: `POST /api/excel-worker/stop` writes the controller-owned stop file. The worker finishes its active task and cleanup before exiting; the controller terminates it only after the bounded grace period expires.

### CLI Execution Modes

- **Single Task (Run Once)**:
  ```powershell
  VSE-ExcelWorker.exe run-once --db data\vse_toolbox.db --root business=D:\ApprovedExcel
  ```
- **Continuous Polling**:
  ```powershell
  VSE-ExcelWorker.exe run --db data\vse_toolbox.db --root business=D:\ApprovedExcel --poll-interval-seconds 2.0
  ```

### Lease Concurrency & Stale Lease Recovery

- Tasks are leased for a bounded duration (default 900 seconds, configurable 60..86400 seconds).
- Active workers renew leases periodically during long transformations.
- If a worker process terminates abruptly, subsequent lease queries detect expired leases and recover them:
  - If `attempt_count < max_attempts`: resets status to `queued` and marks the previous run `expired`.
  - If `attempt_count >= max_attempts`: marks task and run permanently as `failed` (`LeaseExpired`).

---

## 6. Supported Excel Operations

The worker handles three operations with strict file role and multiplicity constraints:

| Operation | Source Files | Target Files | Baseline Files | Output Files | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `merge_append` | >= 1 (`ordinal` 0..N) | 0 | <= 1 (`ordinal` 0) | Exactly 1 (`ordinal` 0) | Appends rows from source workbooks into a unified output, optionally applying a baseline schema. |
| `merge_overlay` | >= 1 (`ordinal` 0..N) | Exactly 1 (`ordinal` 0) | <= 1 (`ordinal` 0) | Exactly 1 (`ordinal` 0) | Overlays source data into a target workbook template. |
| `diff_against_baseline` | 0 | Exactly 1 (`ordinal` 0) | Exactly 1 (`ordinal` 0) | Exactly 1 (`ordinal` 0) | Compares target against baseline and produces a highlighted discrepancy report. |

---

## 7. Artifact Integrity, Audit Logging, & Retention Planning

### Atomic Commitment & Integrity Verification

1. **Publication**: The worker writes to a task-scoped temporary file and atomically publishes it to the designated output path with `os.replace`.
2. **Hash Calculation**: Computes the exact byte size and SHA-256 digest of the committed file.
3. **Atomic DB Commit**: Records the succeeded task, succeeded run, and artifact metadata row in a single transaction.
4. **Download Validation**: On `GET /api/excel-artifacts/<id>/download`, the server:
   - Resolves the stored relative path against current approved roots.
   - Reads the file into memory.
   - Re-verifies byte size and SHA-256 digest using constant-time comparison (`hmac.compare_digest`).
   - If missing or tampered, refuses download with `409 ArtifactUnavailable`.

### Append-Only Audit Logging

Every download attempt on a known artifact is recorded in `excel_artifact_download_audit`:
- Result: `succeeded` or `rejected`
- Reason codes: `verified`, `file_missing`, `integrity_mismatch`, `unsafe_path`, `reparse_point_detected`, `read_error`
- Served size in bytes (only on success)
- Queryable via `GET /api/excel-artifacts/<id>/download-audit?limit=50`

### Read-Only Retention Planning

Query retention candidates without touching the filesystem:

```http
GET /api/excel-artifacts/retention-plan?retentionDays=90&limit=200
```

- **Safety**: 100% read-only metadata query against SQLite `created_at`. No files are deleted, moved, opened, or hashed.
- **Parameters**: `retentionDays` (`1..3650`), `limit` (`1..500`, default `200`).
- **Response**: Contains `cutoffAt` (UTC ISO string), `truncated` (boolean), and list of artifact records ordered oldest-first with deterministic ID tie-breaking.

---

## 8. Rollback Procedure

If issues arise during or after deployment:

1. **Stop Services**:
   ```powershell
   Stop-Process -Name "VSE-ExcelWorker" -ErrorAction SilentlyContinue
   Stop-Process -Name "VSE-WebUI" -ErrorAction SilentlyContinue
   ```
2. **Restore Database**:
   ```powershell
   Copy-Item "data\vse_toolbox.db.backup-<TIMESTAMP>" data\vse_toolbox.db -Force
   ```
3. **Rollback Executables**:
   Replace `VSE-WebUI.exe` and `VSE-ExcelWorker.exe` with previous stable builds from archive storage.
4. **Restart & Validate**:
   Start `VSE-WebUI.exe` and verify health via `GET /api/excel-roots` and `GET /api/excel-worker/status`.

---

## 9. Evidence & Log Locations

- **Application & Worker Logs**: `.runtime\logs\`
- **Database File**: `data\vse_toolbox.db`
- **Build Intermediates**: `.runtime\build_excel_bundle\` (cleaned automatically upon successful build)
- **Windows Event Log**: Application logs for unhandled subprocess exceptions

---

## 10. Production-Only Verification Checklist

> [!IMPORTANT]
> The following steps require actual Microsoft Excel (Office COM) installations,
> real business data, or live filesystem permissions.
> **These steps are NOT executed by automated CI/CD or worker test suites and
> must be performed manually in the production/staging validation environment.**

### Checklist

- [ ] **[MANUAL PRODUCTION-ONLY STEP - NOT EXECUTED BY AUTOMATION]**:
  Verify Microsoft Office 2016 / 2019 / 365 (64-bit or 32-bit matching Python build) is installed and activated on the target Windows host.
- [ ] **[MANUAL PRODUCTION-ONLY STEP - NOT EXECUTED BY AUTOMATION]**:
  Verify Excel COM automation permissions by opening PowerShell as the service user and confirming Excel initializes headlessly without license/activation dialogs:
  ```powershell
  $excel = New-Object -ComObject Excel.Application
  $excel.Visible = $false
  $excel.Quit()
  [System.Runtime.Interopservices.Marshal]::ReleaseComObject($excel) | Out-Null
  ```
- [ ] **[MANUAL PRODUCTION-ONLY STEP - NOT EXECUTED BY AUTOMATION]**:
  Set `VSE_EXCEL_ROOTS_JSON` in the production environment pointing to real business storage volumes (e.g. `D:\ApprovedExcel\Business`). Verify that network shares or junction points are not present in the path.
- [ ] **[MANUAL PRODUCTION-ONLY STEP - NOT EXECUTED BY AUTOMATION]**:
  Execute `tools\build_excel_bundle.ps1` in the production build environment and verify digital signatures or hash checksums of `VSE-WebUI.exe` and `VSE-ExcelWorker.exe`.
- [ ] **[MANUAL PRODUCTION-ONLY STEP - NOT EXECUTED BY AUTOMATION]**:
  Submit real production workbooks for `merge_append`, `merge_overlay`, and `diff_against_baseline` through the Web UI and verify resulting XLSX calculations, cell formats, and formulas in desktop Microsoft Excel.
- [ ] **[MANUAL PRODUCTION-ONLY STEP - NOT EXECUTED BY AUTOMATION]**:
  Simulate unexpected worker termination (`taskkill /F /IM VSE-ExcelWorker.exe`) during an active run and verify that stale lease recovery resets or fails the task according to `max_attempts` configuration.
- [ ] **[MANUAL PRODUCTION-ONLY STEP - NOT EXECUTED BY AUTOMATION]**:
  Query `GET /api/excel-artifacts/retention-plan?retentionDays=30` and verify candidate list against organizational data governance policies prior to manual file archiving.
