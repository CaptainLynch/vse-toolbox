# EWO Update Policy Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the EWO update policy genuinely configurable from the detail page: bind a saved credential alias, confirm an external stable key and match rule, collect two stable mapping observations, select approved automatic fields, and only then allow automatic sync.

**Architecture:** Keep the existing Flask policy API, SQLite binding state, and backend approval gate authoritative. Extend the EWO-specific browser component from a read-only mode summary into a complete safe binding form. It submits the existing policy fields (mode, enabled flag, credential alias, stable key, match rule, automatic field authority, and mapping), calls the existing mapping-discovery endpoint for sanitized evidence, and refreshes the evidence/readiness consumers after either operation. Credentials remain in the existing Windows Credential Manager/DPAPI stores; the browser handles aliases and never handles secret values.

**Tech Stack:** Vanilla JavaScript, Flask API, SQLite policy state, pytest static web contracts, PyInstaller single-file Windows executable.

**Spec:** `docs/superpowers/specs/2026-08-30-ewo-department-stage-filter-design.md`

## Global Constraints

- The backend must continue rejecting automatic sync unless the persisted binding is enabled and the existing credential, mapping, contract, and two-observation evidence checks pass.
- Selecting a mode must not implicitly enable a binding or invent credentials, external keys, mappings, or discovery evidence.
- User-visible readiness text must distinguish a selected mode from an enabled/ready binding.
- No credential values or environment secrets may be added to source, tests, logs, or the packaged output.
- Build output must use the repository's canonical `VSE-WebUI.spec` entry point and be verified by isolated HTTP checks; the source `webui.py --help` parser remains separately syntax-checked.

### Task 1: Add failing browser-contract tests

**Files:**
- Modify: `tests/test_overview_web.py`
- Test: `tests/test_overview_web.py`

**Interfaces:**
- The tests will require `renderEwoDeliverablePolicy` to contain radio controls and a PATCH save handler.
- The tests will require the EWO status-chart action to expose a readiness gate instead of always allowing `立即同步`.

- [x] **Step 1: Write the failing assertions**

  Add focused tests that slice the EWO policy renderer and assert it exposes the credential alias, stable-key/match-rule, automatic field/mapping, enable control, and mapping-discovery workflow. Assert that the loader reads settings/discovery state, the detail page wires an evidence refresh callback, and the status-chart renderer is controlled by readiness.

- [x] **Step 2: Run the focused test**

  Run:

  ```powershell
  .venv\Scripts\python.exe -m pytest tests\test_overview_web.py -q
  ```

  Expected: the new contract fails because the current EWO renderer cannot configure a binding and the EWO chart action has no policy gate.

### Task 2: Implement the EWO policy editor and sync gate

**Files:**
- Modify: `web/static/app.js`
- Modify: `web/app.py`
- Modify: `web/static/style.css`
- Modify: `web/templates/dashboard.html`

**Interfaces:**
- `renderEwoDeliverablePolicy(container, item, policy, options)` remains the renderer used by `loadDeliverablePolicy`.
- The renderer submits the complete binding payload to the existing PATCH endpoint, while never sending a password, cookie, token, or session value.
- The renderer calls the existing mapping-discovery endpoint with a validated base URL, filters, and selected stable key; the backend returns only sanitized evidence.
- `renderDeliverableStatusChart(item, actions)` exposes methods for updating EWO sync readiness after the detailed policy/observation requests finish.
- `_ewo_filters_from_payload` forwards the EWO `model_info` filter so the UI's model match rule is effective during discovery.

- [x] **Step 1: Replace display-only EWO modes with a form**

  Render three radio controls using the existing labels, initialize the current mode, and add controls for the credential alias, stable key, EWO match filters, automatic field authority, source mappings, and explicit enablement. Save the complete policy payload and re-render from the API response after saving.

- [x] **Step 2: Keep the backend gate visible**

  Preserve the existing readiness text based on `enabled` and mapping completeness. Explain that changing the mode does not enable synchronization until credentials, mapping, and evidence are configured. Reuse the backend's final validation rather than duplicating trust decisions in the client.

- [x] **Step 3: Gate the EWO chart action**

  Disable the EWO chart “立即同步” button until the policy and mapping evidence indicate readiness. If an unavailable action is somehow invoked, show the prerequisite message without making a POST request. Refresh this gate after policy save and after each discovery observation.

### Task 3: Audit the implementation

**Files:**
- Review: all changed frontend/backend/test files

- [x] **Step 1: Inspect the data flow and security boundary**

  Confirm that the browser sends only credential aliases, that the base URL remains backend allowlisted, that discovery data is sanitized, and that the server-side `assert_sync_ready` gate remains before any external sync call.

- [x] **Step 2: Run focused and full regression checks**

  Confirm focused EWO/policy tests, syntax checks, whitespace checks, and the complete pytest suite.

### Task 4: Verify the behavior

**Files:**
- Modify: none unless tests expose a contract defect.

- [x] **Step 1: Run focused web tests**

  ```powershell
  .venv\Scripts\python.exe -m pytest tests\test_overview_web.py -q
  ```

- [x] **Step 2: Run the relevant policy tests**

  ```powershell
  .venv\Scripts\python.exe -m pytest tests\test_project_status_policy_api.py tests\test_project_status_sync_runs.py -q
  ```

- [x] **Step 3: Run the complete test suite**

  ```powershell
  .venv\Scripts\python.exe -m pytest -q
  ```

### Task 5: Rebuild and smoke-test the standalone WebUI

**Files:**
- Generated: `dist/VSE-WebUI.exe`
- Generated companion: `dist/VSE-ExcelWorker.exe`

- [x] **Step 1: Build from `VSE-WebUI.spec` with the current `.venv`**

  Redirect verbose output to `.runtime`, then publish the WebUI executable using the repository’s `VSE-WebUI.exe` naming contract.

- [x] **Step 2: Verify the published binary**

  Run `webui.py --help` for the CLI parser, start the published `VSE-WebUI.exe` on an isolated loopback port, and require HTTP 200 for `/` and `/api/overview` plus the new static binding-editor markers.

- [x] **Step 3: Verify repository state**

  Confirm the source diff contains only the intended frontend/test/plan changes and that no credentials are present in changes or logs.
