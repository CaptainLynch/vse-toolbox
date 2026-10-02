# ZCode Runtime Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the repository's active AGY worker path with the local ZCode CLI while preserving supervisor isolation, structured evidence, review gates, and fail-closed provider errors.

**Architecture:** Keep `tools/agents/supervisor.py` as the Codex-led orchestration boundary and replace its dynamically loaded worker adapter with `tools/agents/zcode_cli.py`. The low-risk profile becomes `zcode-heavy`; high-risk and unclear tasks retain the `codex-controlled` lead/review path. ZCode receives the task through its local CLI using an explicit non-yolo mode, the isolated worktree, JSON output, and a denylist for destructive commands.

**Tech Stack:** Python 3.10+, PowerShell, local `zcode` CLI 0.16.5, JSON task/result contracts, Git worktrees, pytest, compileall, and existing supervisor checks.

**Spec:** `docs/superpowers/specs/2026-09-02-zcode-runtime-migration-design.md`

## Global Constraints

- Never invoke `agy`, Antigravity, an AGY custom agent, `--yolo`, or `--dangerously-skip-permissions` from the active repository path.
- Do not rewrite `%USERPROFILE%\\.zcode\\cli\\config.json`, provider credentials, cookies, tokens, or environment secrets; the local ZCode configuration remains the model/provider source.
- The expected configured model is `gemini-3.7-flash-high`; a provider response containing `User location is not supported for the API use` is a blocked external-eligibility result, not a reason to fall back or weaken permissions.
- Preserve the existing isolated worktree lifecycle, scoped change evidence, explicit verification commands, normalized worker-result contract, and manual/Codex review decisions.
- Preserve unrelated dirty-worktree changes. Historical `.agents/runs/` records and dated root-cause documents are not rewritten or re-executed.
- Use `apply_patch` for repository edits, run focused tests after each task, and write verbose verification output to `.runtime/` where practical.

---

### Task 1: Define the ZCode adapter contract with failing tests

**Files:**
- Create: `tests/test_zcode_cli.py`
- Reference for migration: `tests/test_agy_cli.py`
- Test contract: `schemas/worker-result.schema.json`

**Interfaces:**
- The new adapter will expose `executable`, `build_command`, `build_prompt`, and `invoke` with the supervisor-compatible signatures defined in the design spec.
- `invoke` returns the normalized worker result with `status` in `completed`, `partial`, `failed`, or `blocked` and always includes process evidence when a subprocess was attempted.

- [ ] **Step 1: Write the failing adapter tests**

Create tests that import `tools/agents/zcode_cli.py` and assert the desired behavior before the module exists:

```python
def test_build_command_uses_zcode_edit_mode_and_no_yolo(monkeypatch, tmp_path):
    monkeypatch.setattr(zcode_cli.shutil, "which", lambda _: "C:/tools/zcode.cmd")

    command = zcode_cli.build_command(
        {
            "model": "gemini-3.7-flash-high",
            "mode": "edit",
            "no_browser": True,
            "disallowed_tools": ["Bash(git push *)"],
        },
        tmp_path / "schema.json",
        "structured prompt",
        cwd=tmp_path,
    )

    assert command[0] == "C:/tools/zcode.cmd"
    assert command[command.index("--prompt") + 1] == "structured prompt"
    assert command[command.index("--cwd") + 1] == str(tmp_path)
    assert command[command.index("--mode") + 1] == "edit"
    assert "--json" in command
    assert "--no-browser" in command
    assert "--yolo" not in command
    assert all("agy" not in part.lower() for part in command)


def test_provider_location_error_is_blocked_without_fallback(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(zcode_cli, "executable", lambda _: "zcode")

    def run(*args, **kwargs):
        calls.append(args[0])
        return type(
            "Completed",
            (),
            {
                "stdout": "",
                "stderr": "ProviderBusinessError: User location is not supported for the API use.",
                "returncode": 1,
            },
        )()

    monkeypatch.setattr(zcode_cli.subprocess, "run", run)
    result = zcode_cli.invoke(
        {"task_id": "TASK-ZCODE-LOCATION", "objective": "probe"},
        tmp_path,
        tmp_path / "run",
        {"model": "gemini-3.7-flash-high", "mode": "plan"},
    )

    assert result["status"] == "blocked"
    assert "location" in result["summary"].lower()
    assert len(calls) == 1
    assert calls[0][0] == "zcode"


def test_parse_worker_json_from_zcode_response():
    expected = {
        "task_id": "TASK-1",
        "status": "completed",
        "summary": "done",
        "changed_files": [],
        "tests": [],
        "commands_executed": [],
        "risks": [],
        "unresolved": [],
        "needs_review": True,
    }
    stdout = json.dumps({"status": "SUCCESS", "response": json.dumps(expected)})
    assert zcode_cli._parse_result(stdout, "TASK-1") == expected
```

Add the remaining contract tests migrated from the old adapter for executable
lookup, prompt constraints, configured repair-attempt limits, invalid JSON,
missing executable, and zero-exit empty/canceled output. Do not copy tests that
assert AGY flags or AGY-specific permission text.

- [ ] **Step 2: Run the adapter tests and confirm the expected red failure**

Run:

```powershell
python -m pytest tests/test_zcode_cli.py -q
```

Expected: collection fails because `tools/agents/zcode_cli.py` has not been
created yet. If collection fails for any other reason, correct the test import
or fixture before implementation.

- [ ] **Step 3: Commit the failing-test contract**

```powershell
git add tests/test_zcode_cli.py
git commit -m "test: define ZCode worker adapter contract"
```

### Task 2: Implement the ZCode CLI adapter

**Files:**
- Create: `tools/agents/zcode_cli.py`
- Test: `tests/test_zcode_cli.py`

**Interfaces:**
- `build_command(config, schema, prompt, resolve_executable=True, cwd=None)` returns an argument array beginning with the resolved `zcode` executable.
- The command includes `--prompt`, `--json`, `--mode` (`plan`, `edit`, or `build` only), `--no-browser`, and `--cwd` when a worktree is supplied.
- `invoke` writes `zcode.stdout.log` and `zcode.stderr.log` under the task run directory and returns the normalized worker-result contract.

- [ ] **Step 1: Implement executable resolution and safe command construction**

Implement `executable(config)` with `shutil.which`, defaulting to `zcode`.
Reject a missing executable as `blocked`. Validate the configured mode and
reject `yolo`; do not accept an arbitrary mode from a task. Join configured
denylist entries into one `--disallowed-tools` argument because the installed
CLI accepts a comma- or space-separated list. Never put the prompt into the
recorded process command or logs beyond the ZCode stdout/stderr evidence.

- [ ] **Step 2: Implement prompt construction and result parsing**

Keep the task prompt bounded to the current isolated worktree, forbid pushes,
resets, cleanup, credentials, system configuration, and scope expansion, and
require a final JSON object matching `schemas/worker-result.schema.json`.
Parse the ZCode JSON envelope and attempt the `response`, `structured_output`,
`result`, and `final` fields in that order. Accept only a dictionary with the
required worker-result fields and matching `task_id`.

- [ ] **Step 3: Implement fail-closed process/error normalization**

Classify authentication failures, provider business errors, location errors,
permission denials, and zero-exit empty/canceled responses as `blocked` with a
bounded diagnostic tail. Classify other non-zero exits and malformed JSON as
`failed`. Never call `agy` or another provider as a fallback. Store only
bounded diagnostics; never echo the ZCode configuration or credentials.

- [ ] **Step 4: Run the adapter tests and confirm green**

Run:

```powershell
python -m pytest tests/test_zcode_cli.py -q
```

Expected: every adapter test passes with no provider call required because
subprocess behavior is isolated by the test fixtures.

- [ ] **Step 5: Commit the adapter**

```powershell
git add tools/agents/zcode_cli.py tests/test_zcode_cli.py
git commit -m "feat: add bounded ZCode worker adapter"
```

### Task 3: Switch supervisor, configuration, schema, and scripts

**Files:**
- Modify: `.agents/config.json`
- Modify: `schemas/agent-task.schema.json`
- Modify: `tools/agents/supervisor.py`
- Modify: `tools/agents/run_supervisor.ps1`
- Modify: `start-supervisor.ps1`
- Modify: `tests/test_agent_supervisor.py`
- Modify: `tests/test_agent_relay_scripts.py`
- Remove after imports are migrated: `tools/agents/agy_cli.py`, `tests/test_agy_cli.py`

**Interfaces:**
- `supervisor.py` imports `zcode_cli` and uses route `zcode` for the low-risk profile `zcode-heavy`.
- The public task field is `self_repair_attempts`; the profile enum is `zcode-heavy` or `codex-controlled`.
- Existing normalized worker results and run state file names remain compatible except for new active event labels (`zcode-cli`).

- [ ] **Step 1: Update the configuration and task schema**

Replace the active worker block with the following shape, retaining the
existing Codex profile block unchanged:

```json
"worker_agent": "zcode-cli",
"zcode": {
  "executable": "zcode",
  "model": "gemini-3.7-flash-high",
  "mode": "edit",
  "no_browser": true,
  "timeout_seconds": 2400,
  "disallowed_tools": [
    "Bash(git push *)",
    "Bash(git reset *)",
    "Bash(git clean *)",
    "Bash(git restore *)",
    "Bash(git checkout *)",
    "Bash(git rebase *)",
    "Bash(rm *)",
    "Bash(del *)",
    "Bash(rmdir *)"
  ],
  "allowed_models": ["gemini-3.7-flash-high", "gemini-3.7-flash-low"],
  "model_policy": {
    "default": "gemini-3.7-flash-high",
    "categories": {
      "mechanical": "gemini-3.7-flash-low",
      "test-only": "gemini-3.7-flash-low",
      "ui": "gemini-3.7-flash-high",
      "ordinary-implementation": "gemini-3.7-flash-high"
    }
  }
},
"max_zcode_rounds": 3,
"max_zcode_repair_attempts": 3,
"profile": "zcode-heavy"
```

Change the schema profile enum to `zcode-heavy`/`codex-controlled` and replace
`agy_self_repair_attempts` with `self_repair_attempts`, preserving the existing
numeric bounds.

- [ ] **Step 2: Update supervisor runtime selection and state labels**

Change the dynamic import to `load_module("zcode_cli", "zcode_cli.py")` and
replace active AGY-specific defaults, routes, settings, repair keys, worker
events, doctor labels, dry-run profile choices, and error messages with their
ZCode equivalents. Keep `codex-controlled` as the high-risk lead/review mode.
Pass the isolated worktree to the ZCode command builder so dry-run evidence
shows `zcode --cwd <path>`. Do not change worktree safety or check execution.

- [ ] **Step 3: Update the PowerShell entry points**

Change `ValidateSet` and defaults in both scripts to:

```powershell
[ValidateSet("zcode-heavy", "codex-controlled")]
[string]$SupervisorProfile = "zcode-heavy"
```

Keep Codex provider selection, relay-key process scoping, path validation, and
dry-run behavior unchanged.

- [ ] **Step 4: Migrate supervisor tests before removing the old adapter**

Mechanically update fixtures, monkeypatch targets, profile names, route names,
repair field names, event labels, and expected summaries in the supervisor and
relay-script tests. Add assertions that a low-risk dry-run command begins with
`zcode`, contains no `--yolo`, and contains no `agy` substring. Run:

```powershell
python -m pytest tests/test_zcode_cli.py tests/test_agent_supervisor.py tests/test_agent_relay_scripts.py -q
```

Expected: all focused tests pass. Only after imports and tests are green,
remove `tools/agents/agy_cli.py` and `tests/test_agy_cli.py` so no active code
can accidentally call AGY.

- [ ] **Step 5: Commit the runtime switch**

```powershell
git add .agents/config.json schemas/agent-task.schema.json tools/agents/supervisor.py tools/agents/run_supervisor.ps1 start-supervisor.ps1 tests/test_zcode_cli.py tests/test_agent_supervisor.py tests/test_agent_relay_scripts.py
git rm tools/agents/agy_cli.py tests/test_agy_cli.py
git commit -m "refactor: switch supervisor worker from AGY to ZCode"
```

### Task 4: Update active documentation and persistent memory

**Files:**
- Modify: `AGENTS.md`
- Modify: `.agents/README.md`
- Modify: `tools/agents/README.md`
- Modify: `README.md`
- Modify: `memory/CURRENT_STATE.md`
- Modify: `memory/DECISIONS.md`
- Modify: `memory/CONTEXT_MANIFEST.md`
- Append: `memory/RECOVERY_NOTES.md`

**Interfaces:**
- Active instructions and examples must select ZCode and `zcode-heavy`.
- Historical evidence must remain identifiable and must not be rewritten to
  claim that AGY was never attempted.

- [ ] **Step 1: Replace the active runtime policy in `AGENTS.md`**

Rename the active Local AGY delegation section to Local ZCode CLI Delegation.
Require `zcode --prompt`, explicit non-yolo mode, isolated worktrees, JSON
result validation, bounded timeouts, and fail-closed location/auth errors.
Keep the Main Agent ownership and ZCode Runtime Rules sections; remove active
instructions that direct Codex to invoke AGY.

- [ ] **Step 2: Update active runbooks and examples**

Change worker names, profile examples, setup commands, permissions guidance,
and doctor output descriptions in `.agents/README.md`,
`tools/agents/README.md`, and `README.md`. State that `%USERPROFILE%\\.zcode\\cli\\config.json`
is user-managed and must not be committed. Do not advertise yolo or global
permission grants.

- [ ] **Step 3: Checkpoint persistent memory**

Update `CURRENT_STATE.md` so its next action and active worker are ZCode.
Append a durable decision in `DECISIONS.md` explaining why ZCode replaces AGY
and why the provider location error remains external. Change the local-only
handoff label in `CONTEXT_MANIFEST.md`. Append the migration result and the
known ZCode provider error to `RECOVERY_NOTES.md`; retain earlier AGY failures
as historical do-not-retry evidence and write no session IDs, keys, or tokens.

- [ ] **Step 4: Commit documentation and memory**

```powershell
git add AGENTS.md .agents/README.md tools/agents/README.md README.md memory/CURRENT_STATE.md memory/DECISIONS.md memory/CONTEXT_MANIFEST.md memory/RECOVERY_NOTES.md
git commit -m "docs: make ZCode the active local worker runtime"
```

### Task 5: Run final verification and record provider availability

**Files:**
- Verify: `tools/agents/supervisor.py`, `tools/agents/zcode_cli.py`, `.agents/config.json`
- Logs: `.runtime/zcode-runtime-migration-*.log`

- [ ] **Step 1: Run focused and static checks**

```powershell
python -m pytest tests/test_zcode_cli.py tests/test_agent_supervisor.py tests/test_agent_relay_scripts.py -q *> .runtime/zcode-runtime-migration-focused-tests.log
python -m compileall -q tools/agents *> .runtime/zcode-runtime-migration-compileall.log
git diff --check *> .runtime/zcode-runtime-migration-diff-check.log
```

The focused tests, compileall, and diff check must exit 0. Line-ending
warnings from Git are not diff errors; record them separately if present.

- [ ] **Step 2: Verify supervisor doctor without a model call**

```powershell
python tools/agents/supervisor.py doctor *> .runtime/zcode-runtime-migration-doctor.log
```

Confirm the output names the `zcode` executable, the configured
`gemini-3.7-flash-high` model, the `zcode-heavy` profile, and no AGY path.

- [ ] **Step 3: Verify representative dry-run command construction**

```powershell
python tools/agents/supervisor.py run --dry-run --profile zcode-heavy --task-file .agents/tasks/TASK-20260901-DELIVERABLE-UI.json *> .runtime/zcode-runtime-migration-dry-run.log
```

Inspect the generated plan/state and confirm the worker command starts with
`zcode`, contains `--mode edit` or the task-selected non-yolo mode, contains
`--json`, and contains neither `--yolo` nor `agy`.

- [ ] **Step 4: Run the real no-tool ZCode smoke**

```powershell
zcode --prompt "Respond with exactly ZCODE_READY. Do not call any tool and do not read or modify files." --mode plan --json --no-browser --cwd (Get-Location).Path *> .runtime/zcode-runtime-migration-provider-smoke.log
```

If the command returns `ZCODE_READY`, record the successful model/provider
selection without logging credentials. If it returns the known
`User location is not supported for the API use` error, record that the code
migration is verified but provider eligibility remains `blocked`; do not retry
with AGY, change the user config, or weaken permissions.

- [ ] **Step 5: Review the final diff and status**

```powershell
rg -n -S --hidden -g '!**/.git/**' -g '!**/.runtime/**' -g '!**/.agents/runs/**' -g '!**/.agents/worktrees/**' "agy|AGY|Antigravity|antigravity" AGENTS.md .agents tools schemas tests README.md memory/CONTEXT_MANIFEST.md memory/CURRENT_STATE.md memory/DECISIONS.md
git status --short --branch
git diff --stat HEAD~3..HEAD
```

The active control plane must have no AGY invocation path; remaining matches
must be clearly historical recovery/decision evidence or consumed dated
documents explicitly marked historical. Preserve all unrelated user changes.

- [ ] **Step 6: Final handoff**

Report the exact test counts, doctor/dry-run results, provider smoke result,
the known location limitation if still present, the commits created by this
plan, and the files intentionally left unchanged. Do not claim that Gemini
eligibility was repaired unless the fresh smoke proves it.
