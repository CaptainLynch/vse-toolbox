# Codex + local AGY CLI harness

The supervisor is a durable local handoff loop between Codex and the locally
installed `agy` CLI worker running inside isolated Git worktrees. JSON files in
`.agents/runs/TASK-*` retain the task contract, plan, worker result, check output,
evidence, patch, state, and event history. It never auto-merges or pushes.

## Profiles

The supervisor supports two execution profiles:

1. **`agy-heavy` (default)**:
   - For bounded, low-risk implementation tasks (`mechanical`, `test-only`, `ui`,
     `ordinary-implementation`).
   - Supports `risk_class` (with `category` alias) and `review_policy` (`manual-final` or `codex-required`).
   - Builds its plan locally from the task contract without Codex planning.
   - Requires non-empty, explicit `verification_commands` before creating a worktree.
   - Records a stable worktree base commit before running AGY.
   - Runs AGY once, passing the per-task `agy_self_repair_attempts` (or configured `max_agy_repair_attempts`, defaulting to 3, bounded 1..5)
     into the prompt.
   - Runs only the explicit focused verification commands, collects scoped change evidence
     and Git-native patches against the recorded base commit (including scoped untracked files).
   - Validates all changed paths against declared scope before transitioning to
     `worker-complete-awaiting-manual-review`.
   - Completes in the state `worker-complete-awaiting-manual-review` without invoking
     automatic Codex review when `review_policy` is `manual-final`.
   - High-risk categories (`architecture`, `security`, `authentication`, `authorization`,
     `concurrency`, `migration`, `public-contract`, `destructive`) or tasks whose objectives
     contain high-risk signals (security, auth, credentials, concurrency, migration, public contract)
     are automatically forced to `codex-controlled`, even if marked with a low-risk category or `manual-final`.
   - Tasks configured with `review_policy: "codex-required"` are forced to `codex-controlled`.

2. **`codex-controlled`**:
   - Compatibility profile for high-risk or complex tasks requiring Codex leadership.
   - Uses Codex structured planning and per-round Codex review.
   - Supports multi-round repair loops until Codex issues `PASS` or requires takeover.

## Setup

Confirm the installed CLIs and supervisor configuration:

```powershell
codex --version
agy --version
python tools/agents/supervisor.py doctor
```

The profile, AGY executable, model, effort, mode, sandbox, repair attempts, and timeout
are configured in `.agents/config.json`. The harness invokes the local CLI directly with an
argument array, `--sandbox`, JSON output, and the checked-in worker schema. It does not use
`shell=True`, a Codex subagent, a remote model API, or `--dangerously-skip-permissions`.

Sign in to both CLIs using their normal interactive flows if a real run reports
an authentication error. `doctor` deliberately does not inspect credentials.

## Use

```powershell
# Run with default profile (agy-heavy)
python tools/agents/supervisor.py run "增加 Excel 导出功能"
python tools/agents/supervisor.py run --task-file .agents/tasks/my-task.json

# Explicitly choose a profile or dry-run
python tools/agents/supervisor.py run --profile agy-heavy --task-file .agents/tasks/ui-task.json
python tools/agents/supervisor.py run --profile codex-controlled --task-file .agents/tasks/auth-refactor.json
python tools/agents/supervisor.py run --dry-run --task-file .agents/tasks/my-task.json

# Check status and cleanup
python tools/agents/supervisor.py status TASK-20260821-120000
python tools/agents/supervisor.py cleanup TASK-20260821-120000
```

Task JSON must satisfy `schemas/agent-task.schema.json`. A worker may commit in
its own branch, but the supervisor never merges; inspect the state and diff,
then merge only after an explicit human review.

Use `verification_commands` as arrays of executable arguments, for example
`[["python", "-m", "pytest", "tests/test_feature.py", "-q"]]`. In `agy-heavy`,
these focused checks are mandatory before worktree creation. If a task depends
on any current uncommitted workspace state, set `context.requires_current_worktree`
to `true`; the supervisor will keep it with Codex/manual handling because AGY worktrees
start from `HEAD`. Scope paths that already have uncommitted changes are rejected
automatically for the same reason.

AGY CLI can occasionally return `context canceled` after applying a change but before
emitting `structured_output`. The supervisor recovers this only when scoped change
evidence exists and every focused check passes, records a `partial` normalized worker result,
and preserves the run evidence.

`dry-run` writes task and plan state but creates no worktree, business commit,
or merge. `cleanup` removes only the named registered worktree and preserves
the run record.

## Permissions

Keep the local AGY CLI permissions scoped to the worktree,
`git status/diff/log`,
`git add/commit`, and this project's test/lint/build commands. Do not grant
global arbitrary shell, credential access, remote push, or production access.

A headless permission denial is stored as a `blocked` worker result. Fix only
the exact required project-level permission; do not disable the sandbox.
