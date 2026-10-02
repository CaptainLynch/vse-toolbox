# Local agent harness state

`config.json` is checked in. The remaining directories are created on demand:

- `tasks/` holds submitted task inputs;
- `runs/` holds durable per-task handoff, check, review, and event records;
- `logs/` holds subprocess output;
- `worktrees/` holds isolated local AGY CLI worktrees.

They are intentionally ignored because they can contain task-specific source diffs or local diagnostics. Do not place credentials, cookies, tokens, or environment dumps here.
