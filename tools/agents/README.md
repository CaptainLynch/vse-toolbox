# Codex + local AGY CLI harness

The supervisor is a durable local handoff loop: Codex plans and reviews; the
locally installed `agy` CLI invokes its configured model only in a task
worktree. JSON files in `.agents/runs/TASK-*` retain the task, plan, worker
result, check output, review, patch, state, and event history. It never
auto-merges or pushes.

## Setup

Confirm the installed CLIs:

```powershell
codex --version
agy --version
python tools/agents/supervisor.py doctor
```

The AGY executable, model, effort, mode, sandbox, new-project behavior, and
timeout are configured in `.agents/config.json`. The harness invokes the local
CLI directly with an argument array, `--sandbox`, JSON output, and the
checked-in worker schema. It does not use `shell=True`, a Codex subagent, a
remote model API, or `--dangerously-skip-permissions`.

Sign in to both CLIs using their normal interactive flows if a real run reports
an authentication error. `doctor` deliberately does not inspect credentials.

## Use

```powershell
python tools/agents/supervisor.py run --dry-run "分析 README 并判断是否需要补充开发环境说明"
python tools/agents/supervisor.py run "增加 Excel 导出功能"
python tools/agents/supervisor.py run --task-file .agents/tasks/my-task.json
python tools/agents/supervisor.py status TASK-20260821-120000
python tools/agents/supervisor.py cleanup TASK-20260821-120000
```

Task JSON must satisfy `schemas/agent-task.schema.json`. A worker may commit in
its own branch, but the supervisor never merges; inspect the state and diff,
then merge only after an explicit human/Codex decision.

Use `verification_commands` as arrays of executable arguments, for example
`[["python", "-m", "pytest", "tests/test_feature.py", "-q"]]`. These focused
checks run instead of automatic repository-wide checks. Do not use shell
strings or command separators. If a task depends on any current uncommitted
workspace state, set `context.requires_current_worktree` to `true`; the
supervisor will keep it with Codex/manual handling because AGY worktrees start
from `HEAD`. Scope paths that already have uncommitted changes are rejected
automatically for the same reason.

AGY CLI 1.1.17 can occasionally return `context canceled` after applying a
change but before emitting `structured_output`. The supervisor recovers this
only when scoped change evidence exists and every focused check passes, records
a `partial` normalized worker result, and permits one Codex evidence review.
It never retries that transport failure automatically after review.

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
