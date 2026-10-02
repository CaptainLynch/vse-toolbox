# Codex / ZCode dual-tier worker runtime

> 状态：Active
> 读者：Developer、Agent（Worker 运行时任务）
> 权威来源：当前 Worker 代码、配置和运行时验证
> 默认读取：按 Agent 基础设施或 Worker 任务读取

The default execution worker is **ZCode app-server + Gemini 3.8 Flash High only** (`gemini-3.8-flash-high`). Codex owns contracts, architecture, security and final integration. Gemini Pro is removed from the active provider and allowlist. The legacy `pro` task slot is retained as an explicit alias to 3.8 Flash for existing contracts, including deep review; it does not invoke Pro. Both read-only roles use 3.8 Flash. The installer preserves this policy. There is no automatic provider fallback.

## Dual-tier and context policy

- Codex lead sessions use the configured native Codex context window; this machine's Astra Codex client is currently capped at `272000` tokens, while the worker budget is independently controlled and is not inherited from the main controller.
- Main-controller orchestration uses a separate soft policy: `150000` input tokens starts bounded-read mode, `180000` requests a phase Handoff, and `200000` stops further context accumulation. A phase boundary above 150K, an uncached increment of 20K, a tool return of 8192 characters, or a browser image also requests Handoff. These values do not change Codex's native context window.
- Worker context is capped at `1000000` tokens. The default `32768` output allowance and `16384` safety reserve leave `950848` input tokens.
- Green/yellow/red watermarks are 80%/95%/100% of the available input budget (`760678`/`903305`/`950848` with the defaults). A red worker ends its micro-session with `handoff.v1.json`; it does not receive the previous raw transcript in a new session.
- Model slots are selected from the explicit provider allowlist. Official model IDs are recorded as metadata only; local provider aliases must pass runtime and network preflight.
- `preflight.network_probe` sends one plan-mode, no-tool, minimal request. It is retried only for safe transient transport errors with capped full jitter.

## Run a bounded task

Create a UTF-8 JSON contract (no credentials or production data):

```json
{
  "task_id": "TASK-example-001",
  "objective": "Update the documented launch prerequisites",
  "risk_class": "mechanical",
  "scope": ["README.md"],
  "constraints": ["Preserve unrelated content"],
  "acceptance_criteria": ["The prerequisites match the supplied contract"],
  "verification_commands": [["python", "-m", "pytest", "tests/test_launch_contract.py", "-q"]]
}
```

Replace the example acceptance criteria and verification command with real, task-specific ones before running. From PowerShell:

```powershell
& "$env:USERPROFILE/.zcode/tools/run-worker.ps1" -Workspace E:/project/vse-toolbox -TaskFile E:/project/vse-toolbox/.agents/tasks/task.json -DryRun
& "$env:USERPROFILE/.zcode/tools/run-worker.ps1" -Workspace E:/project/vse-toolbox -TaskFile E:/project/vse-toolbox/.agents/tasks/task.json
python tools/agents/supervisor.py status TASK-example-001
```

The repository defines `weekend-5.3flash` for the ZCode gifted trial card.
That profile is `interactive-only`: the card requires the interactive ZCode
host to supply runtime headers/CAPTCHA state. Passing the profile to the
headless launcher is deliberately stopped with `interactive-required` and no
Worker is started. Omitting `-WorkerProfile` keeps the normal Gemini
3.8 Flash route.

```powershell
& "$env:USERPROFILE/.zcode/tools/run-worker.ps1" -Workspace E:/project/vse-toolbox -TaskFile E:/project/vse-toolbox/.agents/tasks/task.json -WorkerProfile weekend-5.3flash -DryRun
```

The dry-run shows the selected interactive route. For real work, select
`GLM-5.3-Flash` in the interactive ZCode session and send only a compact
Handoff back to Codex. The profile name/model are recorded in any attempted
run state; no CAPTCHA or provider header is synthesized by the headless
worker, and there is no automatic provider fallback.

The local project `.agents/config.json` takes priority; projects without one use `~/.zcode/worker-runtime/config.json`. The project must ignore `.agents/` (or its worktree/run subdirectories) before running a writer. The supervisor refuses unclassified/high-risk tasks and overlapping uncommitted input; these stay with the current lead, without another Codex planner call.

The profile name `agy-heavy` remains a compatibility label for the existing contract/check pipeline; `worker_agent=zcode-app-server` selects the actual runtime. A run succeeds only when `state.json` is `worker-complete-awaiting-manual-review`; process exit alone is not acceptance. Review `worker-round-1.json`, `checks-round-1.json`, `change-evidence-round-1.json`, `handoff.v1.json` and the patch before integrating. No auto-merge/push. ZCode `preflight-blocked`, `worker-blocked-awaiting-human`, `worker-failed-awaiting-human` and `worker-checks-failed-awaiting-human` states do not start an automatic Codex takeover.

## Guard and lifecycle

- Each writer uses an isolated Git worktree. Worktrees are editing isolation, not an OS sandbox.
- The model sees only Read/Grep/Glob/Edit/Write. No Bash, browser, MCP tools or nested Agent.
- The installed PreToolUse hook is active only when `VSE_ZCODE_CONTRACT` is present. It checks canonical paths before tools run, blocks external/control paths, and records only tool name and allow/deny. Normal interactive ZCode sessions are unaffected.
- The worker verifies the guard file hash/configuration and refuses project runtime override files pending manual review. Hook errors fail closed.
- Windows starts the worker suspended, assigns it to a kill-on-close Job Object, then resumes it. Completion/timeout terminates the owned tree and confirms zero active processes. No unrelated processes are killed.
- Wait for the matching `session/event` `turn.completed` or `turn.failed`. Legacy `prompt_completed` merely indicates dispatch and is not completion.
- Credentials are read from the existing ZCode provider file and passed in memory over stdio, never copied to the task or runtime config. Raw requests/stderr are not logged. Usage and concise sanitized error details are recorded.
- The lead should return only bounded command summaries to the parent. Successful checks report exit code/count/duration; failures report failing names and a bounded tail. Full logs remain under the local runtime evidence directory.
- Verification commands run externally under the lead's supplied contract. The worker must not claim it ran tests. Batch related work and allow at most two targeted repair attempts before lead takeover.

## Installation / verification / rollback

```powershell
python tools/agents/install_zcode.py install
python tools/agents/supervisor.py doctor
python tools/agents/install_zcode.py check
python tools/agents/install_zcode.py rollback
```

The installer targets this machine's existing Node and ZCode installation. It snapshots the existing files to `~/.zcode/backups/vse-worker-20260908/`, records SHA-256 hashes, installs a local copy of the reviewed runtime, pins Gemini roles, and disables the old `agy-subagent` MCP. Existing API credentials and the desktop lead-model choice are preserved. New ZCode/Codex sessions load the new rules; running conversations are not forcibly restarted.

Rollback first validates every installed hash; if a file changed later it refuses to overwrite it. Backups stay in the user directory, since original config files may contain credentials. No recursive deletion is used. Rollback restores manifest-listed runtime/config files; project source and AGENTS.md changes remain as Git working-tree changes and require separate reviewed source rollback if desired.

For another machine, review CLI paths and provider selection before install. Do not copy credential files. Codex AGY role files and the DeepSeek hook are retained as legacy/explicit opt-in assets; the new rules prohibit selecting them as implicit fallbacks.

## Verified acceptance (2026-09-08)

- Explicit model/permission handshake and real Gemini Read with unavailable Write.
- Real Gemini native Edit changed one owned synthetic file; external pytest passed.
- Local fake provider forced an out-of-scope Write through actual ZCode: hook denied it before creation; worker returned permission-blocked.
- Automated process-tree timeout test prevents a descendant from writing after timeout; routing/result/scope regression tests cover no paid fallback and early completion.
- Logs are under `.runtime/zcode-*`; these are local-only. See CURRENT_STATE for final test count and integration status.

### Code review disposition

Gemini independently reviewed the authorized source snapshot. Fixed and tested: doctor must fail for missing executables; changed model must classify as blocked/model; zcode.json, .env.* and other agent config directories are protected; malformed one-line fences return a parse failure. The suggested repeat-run-directory issue is not reachable in the ZCode branch: controlled/high-risk tasks return to the current lead before the legacy loop, and the default worker runs once per unique task. If resumable/multi-round ZCode execution is added later, introduce per-attempt artifact directories first.

Final installed-launcher acceptance: `worker-complete-awaiting-manual-review`, explicit Gemini Flash High, one external focused check, two guarded tool calls, original checkout unchanged, process tree stopped, no additional Codex planner calls.

Final regression: **1727 passed, 3 skipped** (`python -m pytest tests -q`, 167.95s). Related runtime/compatibility suite: **100 passed, 1 skipped**. Scoped flake8 clean; 21 installed file hashes verified.


## 2026-09-15 Flash-only change and failure diagnosis

- The EWO run `TASK-ewo-pure-association-20260915` failed with `preflight-blocked`, `transport`, `Worker deadline exceeded`. The selected model was already `gemini-3.8-flash-high`; static provider/permission checks passed, worktree was null and round was zero. This is a network-preflight deadline failure, not evidence of a Pro-model failure. The original evidence does not isolate relay, upstream or startup latency.
- A fresh no-tool network preflight using the unchanged 30-second deadline passed in 25.77 seconds, with zero tool calls. This proves current Flash connectivity only; a timing/transient cause is plausible, not proven. No EWO implementation task was restarted.
- Project/global runtime allowlists contain only 3.8 Flash. The Gemini provider's two Pro entries were removed; other providers/models and credentials were preserved. Legacy pro slots resolve to Flash. Backups are local under `~/.zcode/backups/flash-only-20260915/manifest.json`.
- Full doctor currently rejects the current Codex lead because `validate_codex_lead_policy` hardcodes `gpt-5.6-luna`. Independent guard and Gemini runtime checks pass. This separate pre-existing policy issue is not a Gemini transport diagnosis and was not changed here.


### 2026-09-15 预检总预算修复验证

原30秒截止覆盖启动、session/create/subscribe/send和模型响应。现统一为60秒（源码默认、安装器、项目/全局配置、已安装运行时），仍为单次总截止且保留进程树清理。成功结果增加timings_seconds/elapsed_seconds/timeout_seconds，超时报告安全stage标签与耗时，不记录提示词或凭据。

安装后的真实3.8 Flash无工具预检30.172秒成功：create1.516、send0.062、模型响应28.594秒。该正常响应跨越旧30秒截止，验证原预算会误杀正常请求；不宣称已经定位原请求的服务商内部延迟原因。147 passed/1 skipped，地图检查通过。未重启原EWO实施。
