# Main Context Governance and Temporary 5.3 Flash Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an auditable 150K/180K/200K main-context governance policy and an explicit, reversible ZCode `GLM-5.3-Flash` interactive profile without changing the Codex native context window or the normal Gemini default.

**Architecture:** A small pure policy module classifies main-controller input usage and trigger conditions. The existing session audit consumes that policy and reports crossings and counterfactual savings. The supervisor receives an opt-in worker-profile override that deep-merges only approved ZCode settings, records the selected profile in run state, and stops interactive-only profiles before headless execution while leaving the default Gemini route unchanged.

**Tech Stack:** Python standard library, pytest, PowerShell, JSON configuration, existing ZCode app-server supervisor and session audit tool.

**Spec:** Approved in the current thread: `soft_waterline=150000`, `handoff_trigger=180000`, `hard_guard=200000`, `uncached_increment_trigger=20000`, `large_tool_output=8192`, and an explicit weekend `GLM-5.3-Flash` route with an effective 272,000-token worker cap.

## Global Constraints

- Codex keeps its configured native context window; the main policy is an orchestration trigger, not a context-window clamp.
- Every non-Codex worker remains capped at 272,000 effective context tokens.
- The normal `flash` slot continues to point to `gemini-3.8-flash-high` unless the new profile is explicitly selected.
- The temporary profile must use an explicit provider/model allowlist, must declare whether it needs an interactive host, and must never silently fall back to another provider.
- No credentials, raw prompts, screenshots, full logs, or production data may be placed in task contracts, reports, or handoffs.
- Preserve all unrelated working-tree changes; do not commit, merge, push, reset, clean, or delete existing user artifacts.

---

### Task 1: Add and test the main-context policy

**Files:**
- Create: `tools/agents/main_context_policy.py`
- Create: `tests/test_main_context_policy.py`

**Interfaces:**
- `normalize_policy(raw: Mapping[str, Any] | None) -> dict[str, int]`
- `classify_context(input_tokens: int, *, uncached_increment: int = 0, tool_output_chars: int = 0, browser_payload: bool = False, phase_boundary: bool = False, policy: Mapping[str, Any] | None = None) -> dict[str, Any]`
- `estimate_excess_tokens(samples: Iterable[int], cap: int) -> int`

- [x] **Step 1: Write failing tests** for default thresholds, monotonic validation, green/monitor/handoff/hard-guard levels, phase-boundary behavior, large-output/browser triggers, and counterfactual savings.
- [x] **Step 2: Run** `python -m pytest tests/test_main_context_policy.py -q` and confirm the module import fails because the production module does not exist.
- [x] **Step 3: Implement** the pure policy functions with integer validation, explicit trigger reasons, and no I/O.
- [x] **Step 4: Run** the focused test command and confirm all policy tests pass.

### Task 2: Integrate policy into session audit and project guidance

**Files:**
- Modify: `tools/audit_token_trajectory.py`
- Modify: `.agents/config.json`
- Modify: `AGENTS.md`
- Modify: `tools/agents/README.md`
- Modify: `docs/ZCODE_WORKER_RUNTIME.md`

**Interfaces:**
- Audit output adds a `main_context_policy` object containing thresholds, crossing counts, first/last crossing records, and estimated excess input at the configured handoff cap.
- Existing token totals, worker summaries, and report files remain backward-compatible.

- [x] **Step 1: Add** a focused audit assertion fixture for policy metrics and run it against a synthetic trajectory.
- [x] **Step 2: Implement** config loading and report serialization using the pure policy module; keep raw evidence redacted and bounded.
- [x] **Step 3: Document** the green/monitor/handoff/hard-guard actions and the separation between main-controller policy and the worker's 272K cap.
- [x] **Step 4: Run** `python tools/generate_project_map.py --check` and the focused audit/policy tests.

### Task 3: Add an explicit temporary ZCode worker profile

**Files:**
- Modify: `tools/agents/supervisor.py`
- Modify: `tools/agents/install_zcode.py`
- Modify: `C:/Users/Lynch/.zcode/tools/run-worker.ps1`
- Modify: `.agents/config.json`
- Modify: `tests/test_agent_supervisor.py`

**Interfaces:**
- Supervisor accepts `--worker-profile <name>` and records `worker_profile` in `state.json`.
- Launcher accepts optional `-WorkerProfile <name>` and passes it as an argument array.
- Profile `weekend-5.3flash` selects `GLM-5.3-Flash` through the enabled ZCode provider, while retaining 272K context, output, preflight, and safety settings.

- [x] **Step 1: Write failing tests** for profile validation, deep-merge behavior, state recording, unknown-profile rejection, and launcher argument construction.
- [x] **Step 2: Run** the focused supervisor tests and confirm the new profile behavior is absent.
- [x] **Step 3: Implement** explicit profile resolution, allowlist validation, CLI plumbing, and installer-template support; leave the default route unchanged.
- [x] **Step 4: Run** supervisor and ZCode runtime tests plus a no-inference dry-run that proves the selected model and profile are recorded.

### Task 4: Final verification and handoff

**Files:**
- Review only the touched files and their focused tests.

- [x] **Step 1: Run** policy, supervisor, ZCode runtime, and audit tests with bounded output.
- [x] **Step 2: Run** the project map check and `git diff --check` on the touched source/docs/config files.
- [x] **Step 3: Inspect** the actual diff and confirm no existing unrelated files were reverted or overwritten.
- [x] **Step 4: Report** the default route, opt-in weekend command, threshold behavior, test evidence, and rollback procedure.
