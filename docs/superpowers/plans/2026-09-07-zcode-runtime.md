# ZCode Worker Runtime Implementation Plan

> 状态：Historical / Consumed
> 读者：Developer、Agent（运行时历史复盘）
> 权威来源：已批准并实施的历史计划；当前规则以 `docs/ZCODE_WORKER_RUNTIME.md` 为准
> 默认读取：禁止默认读取，仅在追溯运行时演进时读取

Goal: Codex delegates bounded work to the configured ZCode Gemini provider; GLM remains an optional human-selected lead. No automatic paid fallback.
Architecture: reuse supervisor worktrees, contracts, focused checks and evidence. Add a local stdio protocol worker with explicit model, tool allowlist, default-deny permission handling and process-tree cleanup. The current lead handles high-risk tasks instead of spawning another Codex.
Spec: docs/AGENT_ENVIRONMENT_AND_COST_PLAN_20260907.md (approved 2026-09-07).

- [x] Verify CLI compatibility and app-server handshake with a synthetic fixture.
- [x] Verify real Gemini Read and unavailable Write; wait for turn.completed, never prompt_completed.
- [x] Add tests/test_zcode_worker.py: missing/disallowed model, explicit tool list, scoped paths, early completion, invalid result, timeout and descendant cleanup, provider errors and permission denial.
- [x] Add tools/agents/zcode_process.py: stdio transport; Windows suspended child assigned to kill-on-close Job Object before resume; bounded message queue; reject unsupported server requests.
- [x] Add tools/agents/zcode_worker.py: read existing provider credentials only in memory; never log requests or raw stderr; enforce contract and model equality; compact structured result and usage.
- [x] Add supervisor dispatch tests; extend tools/agents/supervisor.py to select zcode-app-server and route high-risk tasks to current lead without a new model call. Preserve AGY compatibility.
- [x] Run isolated write probe with exact owned paths and external focused checks; test simulated error/timeout/permission routes.
- [x] Integrate reviewed files into original checkout, preserving unrelated edits; back up global settings before updates.
- [x] Update local runtime config, Codex/ZCode AGENTS rules and ZCode role prompts. Disable legacy AGY MCP only after new worker passes acceptance.
- [x] Run focused regression and configuration checks; write setup/rollback docs and persistent checkpoint.

Global constraints: no secrets in source/logs/task files; no yolo or skip-permissions; one worktree per writer; no auto merge/push; no production data in probes; default Flash High; timeout is enforced outside the model; failures never change provider.
Verification: python -m pytest tests/test_zcode_worker.py tests/test_agent_supervisor.py tests/test_agy_cli.py -q; python -m flake8 tools/agents/zcode_worker.py tools/agents/zcode_process.py; live probes under .runtime with synthetic data.

Completed 2026-09-08. Global installation and original-checkout integration verified. Full regression 1727 passed, 3 skipped; 21 installed hashes verified. Source changes remain uncommitted; no push.
