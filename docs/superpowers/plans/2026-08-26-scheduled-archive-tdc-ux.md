# 定时归档与 TDC 查询体验 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复定时归档工作台的已确认 UI/契约问题，并提供可缓存的 TDC 快速查询与官方精确预览。

**Architecture:** 保留现有 Flask、SQLite、`ArchiveStore` 和 TDC crawler 边界，新增集中式归档筛选字段定义、受控凭据引用和 TDC 官方导出缓存。前端只负责选择模式和生成字段 payload；后端负责合同校验、安全路径校验、缓存一致性和认证会话复用。

**Tech Stack:** Python 3、Flask、SQLite、requests、原生 JavaScript/CSS、PyInstaller 单文件 EXE。

**Spec:** `docs/superpowers/specs/2026-08-26-scheduled-archive-tdc-ux-design.md`

## Global Constraints

- 不回滚或覆盖现有未提交改动；所有源文件修改使用 `apply_patch`。
- 不把密码、Cookie、Authorization、DPAPI 明文或凭据引用秘密写入缓存、日志、API 返回或测试报告。
- `outputSubdir` 始终是批准归档根目录下的相对 POSIX 子路径；拒绝绝对路径、UNC、反斜杠、`..` 和重解析点。
- 官方精确 TDC 模式不得用 list 数据静默替代；快速模式必须显式标注 `list_endpoint`。
- 每个行为先添加失败测试，单独运行确认失败，再实现最小修复并回归。
- 打包前必须运行完整测试、静态检查、PyInstaller 构建、隔离启动和 HTTP 冒烟。

### Task 1: 固化基线和行为合同

**Files:**
- Read: `AGENTS.md`, `docs/superpowers/specs/2026-08-26-scheduled-archive-tdc-ux-design.md`
- Inspect: `web/static/app.js`, `web/app.py`, `services/scheduled_archive_admin.py`, `core/db_manager.py`, `core/archive_store.py`, `services/tdc_crawler.py`
- Test: existing tests under `tests/test_scheduled_archive*.py`, `tests/test_deliverables_web.py`, `tests/test_tdc_crawler.py`

- [ ] **Step 1: Record the dirty baseline without changing it.**

Run:

```powershell
git status --short --branch
git diff --stat
```

Expected: the known pre-existing modified and untracked files remain visible; no reset or checkout is run.

- [ ] **Step 2: Run focused baseline tests.**

Run:

```powershell
pytest -q tests/test_scheduled_task_lifecycle.py tests/test_scheduled_archive_admin_ui.py tests/test_deliverables_web.py tests/test_tdc_crawler.py
```

Expected: baseline result is recorded before adding new tests.

### Task 2: Add failing regression tests for archive contracts

**Files:**
- Modify: `tests/test_scheduled_archive_admin_ui.py`
- Modify: `tests/test_scheduled_task_lifecycle.py`
- Modify: `tests/test_scheduled_archive_folder_api.py`
- Modify: `tests/test_settings_security.py`

**Interfaces:**
- `GET /api/scheduled-archive/jobs` returns `builtin` and never exposes `credential_ref`.
- `PATCH /api/scheduled-archive/jobs/<job_key>` accepts only approved filter keys and relative `outputSubdir`.
- Built-in archive deletion returns a validation error; custom archive deletion removes the job from active listings.

- [ ] **Step 1: Write failing tests.**

Add assertions that:

```python
assert job_payload["builtin"] is True
assert "isBuiltin" not in job_payload
assert "credential_ref" not in job_payload
```

Add a source-contract test requiring the archive UI to branch on `job.builtin`, render no delete button for built-ins, and expose a user-facing credential choice instead of an opaque password-style alias field.

Add a test that a relative nested output subdirectory is accepted and an absolute Windows path is rejected.

Add a test that the UI serialization preserves a configured retry count of `0` instead of coercing it to `2`.

- [ ] **Step 2: Run only the new tests to verify RED.**

Run:

```powershell
pytest -q tests/test_scheduled_archive_admin_ui.py tests/test_scheduled_task_lifecycle.py tests/test_scheduled_archive_folder_api.py tests/test_settings_security.py
```

Expected: the new assertions fail because the current frontend uses `isBuiltin`, the credential control is opaque, and the UI uses truthiness fallback for zero.

### Task 3: Implement archive lifecycle, credentials, filters, and directory UX

**Files:**
- Modify: `web/static/app.js`
- Modify: `web/templates/dashboard.html`
- Modify: `web/static/style.css`
- Modify: `services/scheduled_archive_admin.py`
- Modify: `core/db_manager.py`
- Modify: `core/domain_identity.py` only if the credential availability contract needs a narrow helper
- Test: tests from Task 2 and existing archive tests

**Interfaces:**
- Frontend uses `job.builtin`, `job.credentialConfigured`, `job.allowedFilterNames`, and `job.retryPolicy`.
- Credential selection sends `credentialRef: "domain"` for the approved DPAPI vault.
- Archive filters remain a JSON object at the API boundary, but the generated form maps visible fields to existing camelCase contract keys.
- Folder selection remains relative to `ArchiveStore`; native selection, if available, returns a validated root/subdirectory value without exposing unapproved paths.

- [ ] **Step 1: Implement the minimum lifecycle fix.**

Change both built-in checks in `renderArchiveConfigCard` from `job.isBuiltin` to `job.builtin`; use copy/archive labels that distinguish built-in disable from custom soft archive. Preserve the existing successful custom flow and error rendering.

- [ ] **Step 2: Implement credential guidance and validation.**

Render a non-secret select/choice with `domain` as the production value, explain that Settings → unified domain login → “保存至凭据保护库” must be completed first, and validate availability before enabling a job. Keep the write-only behavior and never prefill the value.

- [ ] **Step 3: Implement contract-driven archive filter controls.**

Add a shared JavaScript field metadata map for each approved template. Render text/date/number controls with Chinese labels and examples, serialize only non-empty values to the existing camelCase filter object, and keep the raw JSON editor under an advanced disclosure for compatibility.

- [ ] **Step 4: Clarify and secure output directory controls.**

Change the visible label/help to state that the value is a relative subdirectory. Keep `ArchiveStore.validate_output_subdir` as the authoritative validator. Do not send an absolute path to the current endpoint.

- [ ] **Step 5: Add native-picker integration boundary or safe fallback.**

Add a local-only native folder picker adapter behind an explicit endpoint/feature check. If native selection is unavailable, keep the current approved-root browser and label it “选择安全子目录”. Any selected root must be passed through the same `ArchiveStore` allowlist and reparse-point checks.

- [ ] **Step 6: Make retry semantics explicit.**

If task-level retry is not yet persisted, label the current fixed policy as “最多尝试 2 次（失败后重试 1 次）” and remove misleading edit behavior. If the existing schema supports it safely, wire the validated setting to the runner and ensure zero is preserved by replacing truthiness defaults with nullish/finite checks.

- [ ] **Step 7: Run focused GREEN tests and archive regression.**

Run:

```powershell
pytest -q tests/test_scheduled_archive_admin_ui.py tests/test_scheduled_task_lifecycle.py tests/test_scheduled_archive_folder_api.py tests/test_archive_jobs.py tests/test_archive_store.py tests/test_settings_security.py
```

Expected: all focused tests pass with no credential values in output.

### Task 4: Add failing tests for TDC modes and cache contract

**Files:**
- Modify: `tests/test_deliverables_web.py`
- Modify: `tests/test_tdc_crawler.py`
- Create: `tests/test_tdc_export_cache.py`
- Inspect: `web/app.py`, `services/tdc_crawler.py`, `services/scheduled_archive_connectors.py`

**Interfaces:**
- TDC query accepts `preview_source` values `list_endpoint` and `official_export`; default remains fast list unless the caller explicitly selects exact mode.
- Official cache keys contain normalized report/filter/mode/session metadata only; cache values contain bounded XLSX bytes or a controlled temporary file.
- Cache hit avoids a second `export_data_model` call and returns the same 47-column contract.

- [ ] **Step 1: Write failing cache tests.**

Use a fake TDC client whose export counter increments on each export. Assert that two identical official preview requests within TTL call export once, while a changed filter or expired entry calls it again. Assert that cache keys and diagnostic metadata do not contain password, Cookie, Authorization, or DPAPI content.

- [ ] **Step 2: Write failing mode-routing tests.**

Assert that a payload without `preview_source` calls `query_data_model_page`, while `preview_source="official_export"` calls `export_data_model` and returns `data_source="official_export"`.

- [ ] **Step 3: Run RED.**

Run:

```powershell
pytest -q tests/test_deliverables_web.py tests/test_tdc_export_cache.py tests/test_tdc_crawler.py
```

Expected: cache tests fail because every official preview currently performs a fresh export and the frontend always requests official mode.

### Task 5: Implement TDC fast/exact modes and remove duplicate archive requests

**Files:**
- Modify: `web/app.py`
- Modify: `web/static/app.js`
- Modify: `services/tdc_crawler.py` only when the cache integration requires a narrow cache-safe helper
- Modify: `services/scheduled_archive_connectors.py`
- Create: `services/tdc_export_cache.py`
- Test: `tests/test_deliverables_web.py`, `tests/test_tdc_export_cache.py`, `tests/test_tdc_crawler.py`, `tests/test_scheduled_archive_connectors.py`

**Interfaces:**
- `TDCExportCache.get_or_create(key, producer, ttl_seconds=180)` returns a bounded official export path/bytes and never accepts secrets as key material.
- `_tdc_official_data_model_preview` uses the cache, validates the 47-column header, and still slices only after the official workbook is loaded.
- The frontend exposes an explicit operation/mode label and only sends `preview_source="official_export"` for exact mode.

- [ ] **Step 1: Implement the cache with bounded lifetime and cleanup.**

Use a thread-safe in-process cache keyed by report type, normalized filter parameters, base origin, and a session generation marker. Store only temporary XLSX data, enforce the existing maximum preview rows/bytes, evict expired entries, and delete evicted files.

- [ ] **Step 2: Route fast and exact modes explicitly.**

Make list endpoint the fast default. Add an “官方 Excel 精确预览（较慢）” choice. Keep export/download on the official endpoint. Return `data_source` and a human-readable mode in response metadata.

- [ ] **Step 3: Reuse the authenticated TDC session where safe.**

Use the existing `DomainSessionRegistry` for browser/unified-session requests; keep password and browser authentication mutually exclusive. Ensure session expiration invalidates the cache generation marker.

- [ ] **Step 4: Avoid duplicate TDC archive retrieval.**

For `tdc_data_model` and `tdc_sor`, use the official workbook as the authoritative artifact. If normalized CSV/JSON remains required, parse the same workbook through the approved header mapping rather than calling `crawl_*_all` and `export_*` separately.

- [ ] **Step 5: Run GREEN TDC tests.**

Run:

```powershell
pytest -q tests/test_deliverables_web.py tests/test_tdc_export_cache.py tests/test_tdc_crawler.py tests/test_scheduled_archive_connectors.py
```

Expected: mode routing, cache reuse, header validation, and archive connector tests pass.

### Task 6: Full audit and regression verification

**Files:**
- Read/inspect all changed files from Tasks 2–5
- Modify: only files required by audit findings
- Test: full `tests/` suite and static/package tests

- [ ] **Step 1: Run security and contract searches.**

Run:

```powershell
rg -n "isBuiltin|credential_ref|password|Cookie|Authorization|preview_source|outputSubdir|retryCount|ArchiveStore\(" web core services tests
python -m compileall -q core services web
```

Expected: no frontend `isBuiltin` usage remains; secret values are not serialized/logged; path and mode boundaries remain explicit.

- [ ] **Step 2: Run the full test suite.**

Run:

```powershell
pytest -q
```

Expected: zero failures; record skipped tests and any pre-existing warnings in `.runtime/`.

- [ ] **Step 3: Perform a manual diff audit.**

Check each acceptance criterion in the spec against the diff, especially built-in/custom deletion, DPAPI reference handling, filter conversion, root path ownership, cache eviction, TDC mode labels, and retry count semantics.

- [ ] **Step 4: Run the code-review gate.**

Request an independent review of the final diff with the acceptance criteria and full test result. Fix all Critical/Important findings, then rerun affected tests and the full suite.

### Task 7: Build and verify the dependency-free EXE

**Files:**
- Inspect/modify: `VSE-WebUI.spec`, `tools/` build scripts only if packaging requires the new module
- Create: a new versioned directory under `dist/`

- [ ] **Step 1: Run the configured PyInstaller build.**

Run the repository’s existing WebUI build command using `VSE-WebUI.spec`; redirect verbose output to `.runtime/`.

Expected: exit code 0 and a new single-file `VSE-WebUI.exe`.

- [ ] **Step 2: Verify archive contents and dependency independence.**

Run the existing packaging tests plus a clean-directory launch with Python path/environment variables removed.

Expected: bundled web assets, TDC/Aras modules, DPAPI adapter, and cache module are present; no external Python installation is required.

- [ ] **Step 3: Run isolated startup and HTTP smoke checks.**

Start the EXE from its output directory, poll `http://127.0.0.1:5000/`, verify HTTP 200 and the scheduled archive/TDC static assets, then stop only the process started by this check.

- [ ] **Step 4: Record delivery metadata.**

Record absolute EXE path, byte size, SHA-256, test counts, build exit code, and smoke result in the final response. Do not include credentials or raw business data.
