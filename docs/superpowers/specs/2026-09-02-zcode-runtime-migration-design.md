# ZCode Runtime Migration Design

**Date:** 2026-09-02

**Status:** Ready for review

## Goal

Make the local ZCode CLI the only delegated implementation-worker runtime used
by this repository's supervisor, while preserving the existing isolated
worktree, structured handoff, focused verification, review, and fail-closed
security boundaries.

This migration does not attempt to bypass model-provider eligibility. The
current local ZCode configuration names `gemini-3.7-flash-high`, but the
provider currently returns `User location is not supported for the API use`.
The migrated worker must report that condition as `blocked` and must not fall
back to another runtime or weaken permissions.

## Decision

Use the existing supervisor architecture and replace its AGY-specific worker
adapter with a ZCode-specific adapter. The current Codex session remains the
lead agent for architecture, security-sensitive work, planning, review, and
integration decisions. Low-risk delegated work is executed by the local
`zcode` executable in an isolated Git worktree.

The active flow becomes:

```text
Codex lead
  -> supervisor.py
  -> zcode_cli.py
  -> local zcode --prompt ... --cwd <isolated-worktree> --mode edit --json
  -> focused checks and scoped diff evidence
  -> manual or Codex review
```

The existing `codex-controlled` path remains available for high-risk,
medium-risk, or otherwise unclear tasks. It keeps Codex planning/review and
uses the same ZCode worker adapter where the existing loop delegates an
implementation round; it never grants the worker authority over architecture,
credentials, destructive operations, or public-contract decisions.

## Runtime and model policy

- The default low-risk profile is renamed from `agy-heavy` to `zcode-heavy`.
- The worker executable is `zcode`; the adapter never invokes `agy`,
  Antigravity, or an AGY custom agent.
- ZCode's local configuration remains the source of the selected provider and
  model because the installed CLI exposes no `--model` option. The repository
  configuration records the expected model as
  `gemini-3.7-flash-high` for diagnostics, but contains no provider key or
  credential material.
- ZCode is invoked with an explicit non-yolo mode (`edit` for bounded changes,
  `plan` for read-only tasks where the task contract requests it), JSON output,
  the target worktree, and `--no-browser`.
- A configured ZCode denylist blocks pushes, hard resets, clean/restore
  operations, credential access, and other destructive or out-of-scope tools.
  The adapter never adds `--yolo` and never silently broadens the denylist.
- The installed AGY binary and user-level AGY settings are not deleted. The
  repository simply no longer selects or invokes them.

## Adapter contract

Create `tools/agents/zcode_cli.py` with the normalized worker interface already
consumed by `supervisor.py`:

```python
def executable(config: dict[str, Any]) -> str | None: ...
def build_command(
    config: dict[str, Any],
    schema: Path,
    prompt: str,
    resolve_executable: bool = True,
) -> list[str]: ...
def build_prompt(task: dict[str, Any], max_repair_attempts: int = 3) -> str: ...
def invoke(
    task: dict[str, Any],
    worktree: Path,
    run_dir: Path,
    config: dict[str, Any],
    effort: str | None = None,
    max_repair_attempts: int | None = None,
) -> dict[str, Any]: ...
```

The signature is retained so supervisor dry-runs and the existing normalized
worker-result contract remain stable. The schema path is used for local result
validation; ZCode itself receives the task prompt and `--json`, not the AGY
`--json-schema` flag.

The adapter writes only local run stdout/stderr evidence and a redacted command
record. It parses the ZCode JSON envelope and the JSON worker result embedded in
its `response` when present. A response is accepted only when it matches the
existing required fields: `task_id`, `status`, `summary`, `changed_files`,
`tests`, `commands_executed`, `risks`, `unresolved`, and `needs_review`.

## Error handling

Normalize errors as follows:

| Condition | Normalized status | Required behavior |
| --- | --- | --- |
| ZCode executable missing | `blocked` | Explain installation/PATH requirement; create no worktree edits |
| Authentication required/failed | `blocked` | Ask for interactive ZCode login; do not print credentials |
| Provider location/business eligibility error | `blocked` | Preserve a short diagnostic; never retry with AGY or another model |
| Zero exit with canceled/empty response after a denied tool | `blocked` | Keep stderr evidence and stop the supervisor loop |
| Non-zero process error unrelated to eligibility | `failed` | Preserve bounded stderr tail and stop for lead review |
| Invalid/missing worker JSON | `failed` | Preserve stdout evidence and reject the result |

No provider error is converted to `completed`, and no fallback runtime is
attempted.

## Supervisor and task contract changes

- Rename the imported worker module and all active worker events from AGY to
  ZCode.
- Rename runtime-specific configuration keys to `zcode`,
  `max_zcode_rounds`, and `max_zcode_repair_attempts`.
- Use a generic `self_repair_attempts` task field rather than encoding a
  runtime name in the public task schema.
- Rename the low-risk route from `agy` to `zcode`; keep `codex` as the lead
  route for Codex-controlled planning/review.
- Change CLI profile choices, PowerShell validation, doctor output, examples,
  and tests to `zcode-heavy` and `codex-controlled`.
- Preserve existing task IDs and historical `.agents/runs/` evidence. Old run
  records are historical artifacts and are not re-executed or rewritten.

## Files in scope

### Active control plane

- Modify `AGENTS.md` to make local ZCode delegation the active worker policy.
- Modify `.agents/config.json` and `schemas/agent-task.schema.json`.
- Modify `tools/agents/supervisor.py`,
  `tools/agents/run_supervisor.ps1`, and `start-supervisor.ps1`.
- Create `tools/agents/zcode_cli.py` and remove the obsolete active
  `tools/agents/agy_cli.py` adapter.
- Update `.agents/README.md`, `tools/agents/README.md`, and the root
  `README.md` where they describe the active worker runtime.

### Tests and persistent memory

- Replace `tests/test_agy_cli.py` with `tests/test_zcode_cli.py`.
- Update supervisor and relay-script tests to use `zcode-heavy` and the ZCode
  adapter contract.
- Update `memory/CURRENT_STATE.md`, `memory/DECISIONS.md`, and
  `memory/CONTEXT_MANIFEST.md`; append the migration result and provider
  limitation to `memory/RECOVERY_NOTES.md` without deleting historical AGY
  failure evidence.

Dated consumed feature plans and root-cause documents that describe the old
  AGY experiments remain historical records. If they need a current-runtime
  note, add a short superseding note rather than rewriting their evidence.

The user-level ZCode file at `%USERPROFILE%\\.zcode\\cli\\config.json` is
not rewritten by the repository migration: it already carries the selected
model and provider credentials, and changing it would risk secret or account
state. Verification may read the model field without logging the rest of the
file.

## Verification and acceptance

Before claiming completion, run all of the following:

1. Focused adapter/supervisor/script tests, including command construction,
   nested JSON parsing, location-error classification, and no-AGY invocation.
2. `python -m compileall -q tools/agents`.
3. `python tools/agents/supervisor.py doctor`, which must report the ZCode
   executable and configured model without calling the provider.
4. Supervisor dry-run for a representative low-risk task; its planned command
   must start with `zcode` and must not contain `--yolo` or any AGY executable.
5. A real no-tool ZCode smoke with the configured model. If the provider still
   returns the known location error, record the exact blocked result and keep
   the repository migration status separate from provider availability.
6. `git diff --check` and the relevant full regression suite.

Success means the active repository path selects ZCode, the safety and evidence
contracts remain intact, and all code-level checks pass. It does not mean the
current provider region restriction has been bypassed.
