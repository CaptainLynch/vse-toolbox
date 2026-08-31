# EWO/PAA Interactive Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split EWO/PAA detail-page immediate refresh into a server-side-session-backed interactive ARAS query while preserving independent search behavior and keeping automatic/timed synchronization on its lease, credential, retry, audit, and redaction path.

**Architecture:** Detail pages will call the existing `/api/aras/ewo/query` and `/api/aras/paa/query` endpoints with browser-mode, non-secret filters, so independent search and detail refresh share the same Flask adapter and crawler methods. Backend scheduled runners will keep runtime prerequisites out of the scheduled lease gate, then resolve opaque credentials and record every connector outcome; the frontend will maintain separate interactive-query and background-sync controllers.

**Tech Stack:** Python 3.10, Flask, pytest, requests/WinHTTP transport, SQLite, native DOM JavaScript, CSS, PowerShell, local AGY CLI with the repository supervisor.

**Spec:** `docs/superpowers/specs/2026-08-31-ewo-paa-interactive-refresh-design.md`

## Global Constraints

- Existing uncommitted workspace changes are user-owned and must not be reset, overwritten, cleaned, or rolled back.
- Existing public API paths and existing success response fields remain compatible; only additive status/error fields may be introduced.
- Detail refresh requests must not contain `headers`, `cookie`, `cookies`, `username`, `password`, `credentialRef`, `mapping`, or lease tokens.
- Interactive refresh never creates a project-status run, acquires a sync lease, advances a cursor, writes business fields, writes sync audit, or writes archive artifacts.
- `DomainSessionRegistry` remains server-side; its public payload may contain only authentication state and timestamps.
- Scheduled project-status execution continues to call `run_once(validate_runtime_prerequisites=False)`; manual Web background execution keeps the default readiness gate.
- Scheduled archive execution passes `validate_runtime_prerequisites=False` only for `trigger_type="scheduled"`; manual archive `sync-now` keeps the default gate.
- Passwords, Tokens, Cookies, Authorization headers, private keys, complete credentials, and lease tokens must never enter logs, database summaries, Web responses, localStorage, sessionStorage, URLs, or routine agent handoffs.
- Authentication/provider failures are not retried; network, timeout, and native WinHTTP transport failures use the existing bounded retry policy.
- Every test/build/lint/type command writes its complete output to `.runtime/` and reports the saved evidence path.
- No real ARAS/TDC network request, production credential, browser cookie, or Authorization value is used in tests or screenshots.

---

### Task 1: Add the additive ARAS interactive response/error contract

**Owner:** Main session; this task defines the public adapter behavior used by all later UI work.

**Files:**
- Modify: `web/app.py` (`_json_error`, `_aras_error_response`, `api_aras_ewo_query`, `api_aras_paa_query`)
- Modify: `services/aras_crawler.py` only if the existing exception surface cannot identify native transport failures without changing crawler semantics
- Test: `tests/test_aras_cli_web.py`
- Test: `tests/test_overview_web.py` for the frontend-facing error-code contract

**Interfaces:**
- Existing endpoints remain `POST /api/aras/ewo/query` and `POST /api/aras/paa/query`.
- `_json_error(..., code: str | None = None)` adds `error.code` only when supplied; existing `error.type`, `error.message`, and `diagnosticPath` behavior remain available.
- Successful EWO/PAA query payloads retain `rows`, `page`, `item_ids`, and `count`, and add `queryState` with exactly `matched` or `empty`.
- Interactive error codes are `unauthenticated`, `service_unavailable`, and `query_failed`.

- [ ] **Step 1: Extend the fake ARAS client with empty and typed-failure scenarios.**

  Add configurable `rows` and exception behavior to the existing `FakeArasClient` without recording secret values. Keep its call records limited to method names, filter DTOs, pagination, and session identity.

- [ ] **Step 2: Write the failing success-state tests.**

```python
def test_ewo_query_marks_zero_rows_as_empty(client) -> None:
    FakeArasClient.rows = []
    response = client.post(
        "/api/aras/ewo/query",
        json={"base_url": "http://aras.example", "filters": {}},
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["queryState"] == "empty"


def test_paa_query_marks_rows_as_matched(client) -> None:
    response = client.post(
        "/api/aras/paa/query",
        json={"base_url": "http://aras.example", "filters": {}},
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["queryState"] == "matched"
```

- [ ] **Step 3: Run the success-state tests and confirm the contract is missing.**

  Run: `python -m pytest tests/test_aras_cli_web.py -k "query_marks_zero_rows or query_marks_rows" -q > .runtime/task1-red-success.log 2>&1`

  Expected: FAIL because the response has no `queryState` field.

- [ ] **Step 4: Write the failing typed-error tests.**

```python
@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (ArasAuthenticationError("login page"), 401, "unauthenticated"),
        (WinHTTPTimeoutError("transport timeout"), 503, "service_unavailable"),
        (ArasCrawlerError("XML response is not valid"), 502, "query_failed"),
    ],
)
def test_ewo_query_exposes_stable_interactive_error_code(
    client, failure, status, code
) -> None:
    FakeArasClient.fail = failure
    response = client.post(
        "/api/aras/ewo/query",
        json={"base_url": "http://aras.example", "filters": {}},
    )
    assert response.status_code == status
    assert response.get_json()["error"]["code"] == code
```

  Add the corresponding PAA transport/auth coverage and assert that the response body does not contain the fake secret fragments used by the fixture.

- [ ] **Step 5: Run the typed-error tests and confirm the failure is expected.**

  Run: `python -m pytest tests/test_aras_cli_web.py -k "stable_interactive_error_code" -q > .runtime/task1-red-errors.log 2>&1`

  Expected: FAIL because the adapter does not yet emit stable codes/statuses for crawler authentication and transport failures.

- [ ] **Step 6: Implement the additive adapter contract.**

  Add the optional `code` field to `_json_error`. In `_aras_error_response`, check `ArasAuthenticationError` before its `ArasCrawlerError` base; map it to HTTP 401 and `unauthenticated`. Map `WinHTTPTimeoutError`, `WinHTTPError`, `ConnectionError`, and `OSError` to HTTP 503 and `service_unavailable`. For an `ArasCrawlerError` whose sanitized text identifies an upstream 5xx, use HTTP 503 and `service_unavailable`; otherwise retain the existing crawler error response and add `query_failed`. Keep diagnostics redacted and never echo exception bodies directly to interactive UI.

  Add `queryState = "matched" if result.rows else "empty"` to both existing success payloads.

- [ ] **Step 7: Run the focused tests and verify green.**

  Run: `python -m pytest tests/test_aras_cli_web.py tests/test_overview_web.py -q > .runtime/task1-green.log 2>&1`

  Expected: PASS; any changed legacy expectation must be updated only when it describes the old, incorrect transport/auth classification.

- [ ] **Step 8: Commit only Task 1 files.**

  Run: `git add web/app.py services/aras_crawler.py tests/test_aras_cli_web.py tests/test_overview_web.py; git commit -m "feat: expose stable ARAS interactive query states"`

---

### Task 2: Preserve real project-status connector execution and classify scheduled failures

**Owner:** Main session; this task owns credential and connector safety.

**Files:**
- Modify: `services/project_status_sync_runner.py` (`_classify_exception`, retryable transport tuple, sanitized public messages)
- Modify: `services/project_status_connectors.py` only for the bounded native transport retry surface if required by Task 2 tests
- Test: `tests/test_project_status_sync_runner.py`
- Test: `tests/test_project_status_connectors.py`

**Interfaces:**
- `ProjectStatusSyncRunner.run_once(..., validate_runtime_prerequisites: bool = True)` remains backward compatible.
- Scheduled execution with `False` still performs the fixed binding guard, acquires a lease, starts a run, invokes `connector.collect`, and finalizes an auditable result.
- Stable scheduled error types are `credential_unavailable`, `credential_invalid`, `authentication_error`, `service_unavailable`, `timeout`, `query_failed`, `invalid_data`, and `missing_entity`.
- Retry remains bounded to the existing maximum of two attempts and never retries credential/authentication failures.

- [ ] **Step 1: Add a parametrized failure fixture to the runner tests.**

  Use the existing `_enable_pilot` fixture helpers and a `FakeConnector(exc=...)`. Assert run count, final DB state, `error_type`, sanitized `error_message`, and absence of secret fragments.

- [ ] **Step 2: Write the failing scheduled error-classification tests.**

```python
@pytest.mark.parametrize(
    ("failure", "error_type"),
    [
        (CredentialProviderError("credential missing password=secret"), "credential_unavailable"),
        (ArasAuthError("credentials rejected password=secret"), "credential_invalid"),
        (ArasAuthenticationError("login page token=secret"), "authentication_error"),
        (WinHTTPError("transport failed Cookie=secret"), "service_unavailable"),
        (WinHTTPTimeoutError("timed out token=secret"), "timeout"),
        (ArasCrawlerError("invalid XML Authorization=secret"), "query_failed"),
    ],
)
def test_scheduled_connector_failure_is_audited_without_secret(
    runner, db, service, registry, failure, error_type
) -> None:
    _enable_pilot(service)
    registry.register("tdc", FakeConnector(exc=failure))
    result = runner.run_once(validate_runtime_prerequisites=False)
    assert result.results[0].error_type == error_type
    assert result.results[0].run_id is not None
    assert "secret" not in json.dumps(result.results[0].__dict__)
```

- [ ] **Step 3: Run the new classification tests and confirm red.**

  Run: `python -m pytest tests/test_project_status_sync_runner.py -k "failure_is_audited_without_secret" -q > .runtime/task2-red-classification.log 2>&1`

  Expected: FAIL because the current classifier collapses provider/auth/WinHTTP failures into `connector_error`.

- [ ] **Step 4: Add the real credential-resolution connector test.**

  Construct `ArasProjectStatusConnector` with `MemoryCredentialProvider`, a fake auth factory that records only whether it received the expected fixture username/password, and a fake crawler returning one EWO row. Assert `provider.resolve` is called through the connector, the crawler receives the EWO filter, the snapshot is matched, and the stored artifacts contain no credential values.

- [ ] **Step 5: Run the credential-resolution test and confirm red if the connector path is not yet asserted.**

  Run: `python -m pytest tests/test_project_status_connectors.py -k "resolves_opaque_credential" -q > .runtime/task2-red-credential.log 2>&1`

  Expected: FAIL until the test observes the real provider/auth/crawler sequence rather than a fake runner-only shortcut.

- [ ] **Step 6: Implement stable runner classification and bounded native retry.**

  Import the provider/auth/crawler/WinHTTP exception types in `project_status_sync_runner.py` without importing Flask or the production connector module. Classify provider lookup as `credential_unavailable`, `ArasAuthError`/`TDCAuthError` as `credential_invalid`, crawler authentication as `authentication_error`, WinHTTP/OS transport as `service_unavailable`, native timeout as `timeout`, crawler parse/response errors as `query_failed`, then retain the existing validation/entity mappings. Replace raw connector exception text in result/history summaries with a stable message selected by error type and pass it through the existing redaction limit.

  Extend `RetryingConnector`'s transient tuple with `WinHTTPError` so Windows native timeout/transport failures receive the same maximum-two-attempt policy. Do not add provider/auth exceptions to the transient tuple.

- [ ] **Step 7: Run the focused project-status tests and verify green.**

  Run: `python -m pytest tests/test_project_status_sync_runner.py tests/test_project_status_connectors.py -q > .runtime/task2-green.log 2>&1`

- [ ] **Step 8: Commit only Task 2 files.**

  Run: `git add services/project_status_sync_runner.py services/project_status_connectors.py tests/test_project_status_sync_runner.py tests/test_project_status_connectors.py; git commit -m "fix: audit scheduled project status connector failures"`

---

### Task 3: Make scheduled PAA archive leasing runtime-tolerant without weakening manual execution

**Owner:** Main session; this task owns the second lease implementation.

**Files:**
- Modify: `core/db_manager.py` (`get_archive_job_credential_ref`, `acquire_archive_job_lease`)
- Modify: `services/scheduled_archive_runner.py` (`run_job`, `run_once`, retry/error classification)
- Test: `tests/test_scheduled_archive_runner.py`
- Test: `tests/test_scheduled_archive_admin_api.py` or `tests/test_archive_jobs.py` for manual-vs-scheduled compatibility

**Interfaces:**
- `DatabaseManager.acquire_archive_job_lease(..., *, validate_runtime_prerequisites: bool = True)` keeps the default behavior for existing callers.
- `DatabaseManager.get_archive_job_credential_ref(job_id, *, require_configured: bool = True)` returns an empty string only when explicitly called with `False`; the default still raises `ArchiveJobNotReadyError`.
- `ArchiveSyncRunner.run_job(..., validate_runtime_prerequisites: bool = True)` keeps manual default behavior.
- `ArchiveSyncRunner.run_once(trigger_type="scheduled")` passes `False`; `trigger_type="sync_now"` passes `True`.

- [ ] **Step 1: Add a fake PAA archive job with an enabled state and no credential reference.**

  Use the existing archive test fixtures and a fake provider/connector so the test never reads a real credential store or contacts ARAS.

- [ ] **Step 2: Write the failing scheduled lease test.**

```python
def test_scheduled_paa_missing_credential_creates_auditable_run(db, runner) -> None:
    job = _enable_archive_job_without_credential(db, "aras_paa")
    result = runner.run_once(trigger_type="scheduled", job_key="aras_paa")
    assert result.results[0].run_id is not None
    assert result.results[0].error_type == "credential_unavailable"
    run = _latest_archive_run(db, int(job["id"]))
    assert run["run_state"] == "needs_attention"
```

- [ ] **Step 3: Run the scheduled lease test and confirm red.**

  Run: `python -m pytest tests/test_scheduled_archive_runner.py -k "scheduled_paa_missing_credential" -q > .runtime/task3-red-scheduled.log 2>&1`

  Expected: FAIL because `acquire_archive_job_lease` rejects a missing credential before creating a run.

- [ ] **Step 4: Write the manual compatibility test.**

  Call `runner.run_job(job_id, trigger_type="sync_now")` or the admin service sync-now path for the same missing-credential job and assert the default precondition result remains `not_ready` with no newly created leased run.

- [ ] **Step 5: Run the manual compatibility test and confirm red only for the new signature.**

  Run: `python -m pytest tests/test_scheduled_archive_runner.py tests/test_scheduled_archive_admin_api.py -k "manual.*credential or credential.*not_ready" -q > .runtime/task3-red-manual.log 2>&1`

- [ ] **Step 6: Implement the opt-in runtime-prerequisite bypass.**

  Add the keyword-only flag to the database lease method. Keep fixed contract, archived, enabled, filter, and retry-policy validation before leasing. Guard only the credential-reference presence check with the flag. Let scheduled execution request an empty reference from `get_archive_job_credential_ref(..., require_configured=False)` and pass it to the provider, which produces `CredentialProviderError`; the runner then finalizes the already-created run with `needs_attention` and `credential_unavailable`.

  Pass `validate_runtime_prerequisites=False` from scheduled `run_once`; leave manual `sync_now` at the default. Add `WinHTTPError`/`WinHTTPTimeoutError` to archive transient retry handling, map auth failures to credential/authentication types, and keep stable redacted summaries.

- [ ] **Step 7: Run all archive focused tests and verify green.**

  Run: `python -m pytest tests/test_scheduled_archive_runner.py tests/test_scheduled_archive_admin_api.py tests/test_archive_jobs.py -q > .runtime/task3-green.log 2>&1`

- [ ] **Step 8: Commit only Task 3 files.**

  Run: `git add core/db_manager.py services/scheduled_archive_runner.py tests/test_scheduled_archive_runner.py tests/test_scheduled_archive_admin_api.py tests/test_archive_jobs.py; git commit -m "fix: keep scheduled archive runs auditable"`

---

### Task 4: Add the frontend interactive-query helper and stable error presentation

**Owner:** AGY `ui` task after Main supplies the exact contract below; Main reviews and integrates the diff.

**Files:**
- Modify: `web/static/app.js` (`overviewRequestError`, new interactive query helpers, temporary result renderer)
- Modify: `web/static/style.css` (interactive result/status states)
- Test: `tests/test_interactive_refresh_ui.py` (new static contract test)

**Interfaces:**
- `buildInteractiveArasPayload(reportType: "ewo" | "paa", source: object) -> object` returns only `base_url`, `auth_mode`, `filters`, `page`, `page_size`, and `max_records`.
- `requestInteractiveArasQuery(reportType: "ewo" | "paa", payload: object) -> Promise<object>` selects exactly `/api/aras/ewo/query` or `/api/aras/paa/query` and returns `body.data`.
- `formatInteractiveArasResult(data: object, expectedExternalKey?: string) -> {text: string, tone: string, state: string}` returns `matched`, `empty`, or `no_match` without relying on backend readiness fields.
- `formatInteractiveArasError(error: object) -> string` returns one of the user-facing prefixes `未认证`, `服务不可用`, or `查询失败` and never displays the raw internal prerequisite string.
- `renderInteractiveArasResult(container: Element, reportType: string, data: object, expectedExternalKey?: string)` renders a bounded, redacted table and a note that business/background sync was not changed.

- [ ] **Step 1: Write the failing static contract tests.**

```python
def test_interactive_query_helper_uses_existing_ewo_and_paa_endpoints() -> None:
    source = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    assert "function buildInteractiveArasPayload" in source
    assert "async function requestInteractiveArasQuery" in source
    assert '"/api/aras/ewo/query"' in source
    assert '"/api/aras/paa/query"' in source


def test_interactive_payload_excludes_background_credentials_and_readiness() -> None:
    source = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    helper = source[source.index("function buildInteractiveArasPayload"):source.index("function renderInteractiveArasResult")]
    for forbidden in ("credentialRef", "credential_ref", "mapping", "leaseToken", "password", "cookie", "authorization"):
        assert forbidden not in helper
```

- [ ] **Step 2: Run the UI contract tests and confirm red.**

  Run: `python -m pytest tests/test_interactive_refresh_ui.py -q > .runtime/task4-red.log 2>&1`

  Expected: FAIL because the helper names and temporary result renderer do not exist.

- [ ] **Step 3: Implement the minimal helper and error mapping.**

  Extend `overviewRequestError` with `errorType`, `errorCode`, and `errorMessage` properties. Build EWO filters from only `matchRule` keys `ewoNo`, `projectCode`, `subjectKeyword`, `modelInfo`; build PAA filters from only the stored non-secret archive filter names. Send `auth_mode: "browser"` and no explicit headers/cookies/credentials. Map `errorCode` first, then HTTP 401/503, then `query_failed`, to short Chinese text. Use existing `renderRows`/`safeDisplayValue` for result display and include `queryState`/target-match status in the label.

- [ ] **Step 4: Run the UI contract tests and verify green.**

  Run: `python -m pytest tests/test_interactive_refresh_ui.py -q > .runtime/task4-green.log 2>&1`

- [ ] **Step 5: Run the JavaScript syntax smoke check.**

  Run: `node --check web/static/app.js > .runtime/task4-node-check.log 2>&1`

  Expected: exit code 0.

- [ ] **Step 6: Main audits the AGY diff.**

  Confirm the worker changed only the listed UI/test files, did not add `localStorage`/`sessionStorage` writes for credentials, did not add network endpoints, and did not modify `web/app.py`, credential providers, or lease code. Run `git diff --check` and the focused UI tests independently.

---

### Task 5: Wire EWO detail actions to interactive refresh and isolate background sync

**Owner:** AGY `ui` task under the exact Task 4 interface; Main owns final behavior review.

**Files:**
- Modify: `web/static/app.js` (`renderDeliverableDetailPage`, `renderDeliverableStatusChart`, `renderDeliverableAnalysisActionBar`, EWO refresh handlers, evidence action labels)
- Modify: `web/static/style.css` (EWO interactive result panel and button/status states)
- Test: `tests/test_interactive_refresh_ui.py`
- Test: `tests/test_overview_web.py` (update obsolete readiness assertions and preserve filter/tag/chart contracts)

**Interfaces:**
- EWO interactive filters come from `item.updatePolicy.matchRule` and optionally the existing external key as an EWO-number filter; an absent rule produces a bounded empty-filter query.
- EWO detail actions call `requestInteractiveArasQuery("ewo", payload)`.
- Existing background `requestProjectStatusSync(item)` remains reachable only from an explicitly labeled background-sync/evidence action and remains readiness-gated.

- [ ] **Step 1: Write the failing EWO wiring tests.**

```python
def test_ewo_detail_immediate_actions_use_interactive_query_not_project_sync() -> None:
    source = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    detail = source[source.index("function renderDeliverableDetailPage"):source.index("function renderArchiveDeliverableDetailPage")]
    assert "requestInteractiveArasQuery(\"ewo\"" in detail
    assert "立即刷新（交互式查询）" in detail
    assert "requestProjectStatusSync(item)" not in detail


def test_ewo_background_action_keeps_explicit_sync_label_and_gate() -> None:
    source = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    evidence = source[source.index("function renderDeliverableEvidence"):source.index("function renderCustomLabelChart")]
    assert "运行后台同步" in evidence
    assert "requestProjectStatusSync(item)" in evidence
    assert "analysisSyncReadiness" in evidence
```

- [ ] **Step 2: Run the EWO wiring tests and confirm red.**

  Run: `python -m pytest tests/test_interactive_refresh_ui.py tests/test_overview_web.py -k "ewo_detail or background_action" -q > .runtime/task5-red.log 2>&1`

  Expected: FAIL because the current detail actions still call project-status sync and readiness controls.

- [ ] **Step 3: Implement the EWO interactive action wiring.**

  Add `interactiveReportType: "ewo"` to the EWO detail analysis options. Change the status-chart and analysis action buttons to `立即刷新（交互式查询）`; make their busy state local to the interactive request and never set it from background readiness. After a successful query, render the temporary redacted result and state note, then reload the existing cached analysis only as a separate cache read. Change the evidence/background action label to `运行后台同步`, retain its readiness gate and project-status endpoint, and keep its error/history behavior.

- [ ] **Step 4: Add the EWO result-state assertions.**

  Assert static coverage for `未认证`, `服务不可用`, `未匹配`, `数据为空`, `查询失败`, the “not written to background sync” note, and the absence of `credentialRef`/`mapping`/`leaseToken` in the interactive payload builder.

- [ ] **Step 5: Run EWO UI and regression tests and verify green.**

  Run: `python -m pytest tests/test_interactive_refresh_ui.py tests/test_overview_web.py tests/test_overview_external_deliverables_ui.py -q > .runtime/task5-green.log 2>&1`

- [ ] **Step 6: Main audits the AGY diff and checks the call graph.**

  Verify only EWO detail interactive actions changed; D5/TDC existing background behavior, department/stage/model filters, tags, charts, and custom chart grouping remain present.

---

### Task 6: Wire PAA detail actions to the same interactive query path

**Owner:** AGY `ui` task under the exact Task 4 interface; Main owns final behavior review.

**Files:**
- Modify: `web/static/app.js` (`renderArchiveDeliverableDetailPage`, PAA filter conversion, archive detail result rendering)
- Modify: `web/static/style.css` (PAA interactive result/status states)
- Test: `tests/test_interactive_refresh_ui.py`
- Test: `tests/test_overview_external_deliverables_ui.py`

**Interfaces:**
- PAA interactive filters are converted from the job's non-secret `filters` values: `paaNo→paa_no`, `ewoNo→ewo_no`, `vehicleKeyword→vehicle_keyword`, `submitStart/submitEnd`, `materialRequestStart/materialRequestEnd`, and `department` plus the remaining approved scalar fields.
- PAA detail actions call `requestInteractiveArasQuery("paa", payload)` and never call `/api/scheduled-archive/jobs/<job_key>/sync-now`.
- The existing “进入任务配置/重试” control remains the route to background archive configuration and history.

- [ ] **Step 1: Write the failing PAA wiring tests.**

```python
def test_paa_detail_immediate_refresh_uses_interactive_query() -> None:
    source = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    detail = source[source.index("function renderArchiveDeliverableDetailPage"):source.index("function toggleDeliverableDetail")]
    assert "requestInteractiveArasQuery(\"paa\"" in detail
    assert "立即刷新（交互式查询）" in detail
    assert "/api/scheduled-archive/jobs/${encodeURIComponent(job.jobKey)}/sync-now" not in detail


def test_paa_detail_filter_conversion_preserves_stored_query_filters() -> None:
    source = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    detail = source[source.index("function renderArchiveDeliverableDetailPage"):source.index("function toggleDeliverableDetail")]
    for marker in ("paaNo", "ewoNo", "vehicleKeyword", "materialRequestStart", "department"):
        assert marker in detail
```

- [ ] **Step 2: Run the PAA wiring tests and confirm red.**

  Run: `python -m pytest tests/test_interactive_refresh_ui.py tests/test_overview_external_deliverables_ui.py -k "paa_detail" -q > .runtime/task6-red.log 2>&1`

  Expected: FAIL because PAA detail still calls the scheduled archive sync endpoint.

- [ ] **Step 3: Implement the PAA interactive action wiring.**

  Make `立即刷新（交互式查询）` call the shared helper with `auth_mode: "browser"`, the fixed/default ARAS base URL, page one, bounded page size, and converted job filters. Make the secondary detail refresh action explicitly refresh interactive query results (and then reload history as a separate read if needed). Render a temporary PAA result table and show “本次结果未写入后台同步状态”. Do not disable these buttons based on `job.credentialAvailable`, `job.enabled`, or archive filters; only disable while the interactive request is running.

- [ ] **Step 4: Run PAA UI regression tests and verify green.**

  Run: `python -m pytest tests/test_interactive_refresh_ui.py tests/test_overview_external_deliverables_ui.py tests/test_overview_web.py -q > .runtime/task6-green.log 2>&1`

- [ ] **Step 5: Main audits the AGY diff and verifies scheduled separation.**

  Confirm the only scheduled endpoint left in the PAA detail area is the configuration/history navigation; the automatic PAA runner and API remain available elsewhere.

---

### Task 7: Add security, mode-separation, and regression coverage

**Owner:** AGY `test-only` task after Tasks 1–6 define the exact interfaces; Main reviews every test and runs them independently.

**Files:**
- Create: `tests/test_interactive_refresh_ui.py`
- Modify: `tests/test_aras_cli_web.py`
- Modify: `tests/test_project_status_sync_runner.py`
- Modify: `tests/test_scheduled_archive_runner.py`
- Modify: `tests/test_overview_web.py`
- Modify: `tests/test_overview_external_deliverables_ui.py`
- Modify: `tests/test_debug_bundle.py`
- Modify: `tests/test_debug_bundle_ui.py`

**Interfaces:**
- Tests are static/fixture-based and never contact an external system.
- Existing filtering, labels, charts, debug bundle, and redaction contracts remain asserted.

- [ ] **Step 1: Main provides AGY the fixed fixture and assertion checklist.**

  The worker may use only fake rows such as `{"_no": "EWO-TEST-1", "state": "Open"}` and fake secrets such as `fictional-token`; it must not inspect or access credential stores, cookies, environment dumps, or production data.

- [ ] **Step 2: Have AGY write the failing test scenarios.**

  Required scenarios: EWO/PAA interactive endpoint parity, no credential/ref/mapping payload, shared Session reuse, five interactive states, scheduled prerequisite bypass, real credential-provider resolution, credential missing/invalid, unauthenticated, service unavailable, no-match, empty data, debug redaction, and existing filter/tag/chart regressions.

- [ ] **Step 3: Run the test-only worker's focused tests and preserve the red evidence.**

  Run: `python -m pytest tests/test_interactive_refresh_ui.py tests/test_aras_cli_web.py tests/test_project_status_sync_runner.py tests/test_scheduled_archive_runner.py -q > .runtime/task7-red.log 2>&1`

  Expected: the newly added tests fail only at the not-yet-implemented assertions; unrelated baseline tests must not be silently removed or weakened.

- [ ] **Step 4: Main reviews and integrates the test-only diff.**

  Check `git diff --stat`, `git diff --check`, changed test names, fixtures, and that no test contains a real URL, secret, external HTTP call, broad monkeypatch, or relaxed assertion.

- [ ] **Step 5: Run the complete focused suite after all implementations.**

  Run: `python -m pytest tests/test_project_status_sync_runner.py tests/test_project_status_admin_api.py tests/test_overview_web.py tests/test_aras_cli_web.py tests/test_project_status_connectors.py tests/test_scheduled_archive_runner.py tests/test_scheduled_archive_admin_api.py tests/test_overview_external_deliverables_ui.py tests/test_debug_bundle.py tests/test_debug_bundle_ui.py -q > .runtime/interactive-focused-final.log 2>&1`

  Expected: PASS with no removed coverage and no secret fragments in output.

---

### Task 8: Final integration, browser preview, review, and release evidence

**Owner:** Main session; mandatory code-reviewer review for the cross-module behavior.

**Files:**
- Inspect: all files changed by Tasks 1–7
- Create: `.runtime/` logs, screenshots, and preview evidence only
- Modify: only if review identifies a verified defect

- [ ] **Step 1: Run the required compile and diff checks.**

  Run: `python -m py_compile core/db_manager.py services/project_status_updates.py services/project_status_sync_runner.py main.py web/app.py > .runtime/final-compile.log 2>&1`.

  Run: `git diff --check > .runtime/final-diff-check.log 2>&1`.

- [ ] **Step 2: Run the user-required focused command.**

  Run: `python -m pytest tests/test_project_status_sync_runner.py tests/test_project_status_admin_api.py tests/test_overview_web.py -q > .runtime/final-required-focused.log 2>&1`.

- [ ] **Step 3: Run the full regression suite.**

  Run: `python -m pytest -q > .runtime/final-full-regression.log 2>&1`.

  Expected: 0 failures; distinguish any pre-existing flake8/mypy baseline errors from errors introduced by this work.

- [ ] **Step 4: Run configured flake8 and mypy checks.**

  Run: `python -m flake8 > .runtime/final-flake8.log 2>&1`.

  Run: `python -m mypy core services web > .runtime/final-mypy.log 2>&1`.

  Record exit codes and compare new diagnostics with the documented baseline before the implementation commits.

- [ ] **Step 5: Start the local WebUI with an isolated test data path if the repository supports it.**

  Use the existing local entrypoint and a fake/offline fixture path; do not log in or make an ARAS request. If a real browser smoke cannot be run safely, use the committed preview plus static DOM checks and record that limitation.

- [ ] **Step 6: Capture UI evidence.**

  Capture one EWO detail view showing `立即刷新（交互式查询）`, a separate `运行后台同步` action, and a short error/status card; capture one PAA detail view showing the same separation. Save screenshots under `.runtime/` and ensure no secrets are visible.

- [ ] **Step 7: Request cross-module code review.**

  Provide the reviewer only the relevant commit range, the spec, the changed-file list, acceptance criteria, and focused/full test log paths. Ask specifically about Session reuse, payload redaction, lease-before-runtime validation, retry boundaries, and EWO/PAA endpoint parity.

- [ ] **Step 8: Fix Critical/Important findings with a new failing test first.**

  Main decides whether each finding is valid; no blind acceptance. Re-run the affected focused suite and then the full regression suite after every repair.

- [ ] **Step 9: Produce the final audit summary.**

  Include root cause, old/new UI modes, both interactive call chains, both scheduled call chains, Session/credential boundary, changed files, AGY task IDs and diff audit, test/build/Lint/type evidence, screenshot paths, known limitations, rollback steps, and final Review `PASS`/`FIX` conclusion.

---

## Plan self-review

- **Spec coverage:** interactive endpoint parity and error states are covered by Tasks 1, 4, 5, 6, and 7; project-status scheduled bypass and real credentials by Task 2; PAA scheduled lease behavior and retry by Task 3; UI/filter/tag/chart/Debug regression by Tasks 5–7; final evidence and review by Task 8.
- **Public-contract consistency:** the plan keeps existing EWO/PAA query routes and success fields, adds only `queryState` and optional `error.code`, and leaves manual background routes available.
- **Security consistency:** no task sends or stores detail-page credentials; Session remains server-side; all fake secrets stay in tests only.
- **Type/signature consistency:** every new helper and keyword-only parameter is named once in its task interface and reused with the same spelling in later tasks.
- **Concrete-step audit:** every step contains an owner, exact files, a testable action, and a verification command; no vague implementation step remains.
- **Workspace safety:** every worker task is scoped to listed files, and every AGY diff is independently inspected by Main before integration.
