"""Install/check/rollback the approved local ZCode worker settings (no model requests)."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'check', 'rollback'])
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--installation-id', default=None)
    parser.add_argument('--accept-changed-targets', action='store_true')
    args = parser.parse_args()
    home = Path.home()
    installation_id = args.installation_id or (
        'vse-worker-20260910-dual-tier' if args.accept_changed_targets else 'vse-worker-20260908'
    )
    backup = home / '.zcode/backups' / installation_id
    manifest_path = backup / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {'files': []}
    if args.action in ('check', 'rollback'):
        if not manifest['files']:
            raise SystemExit('No installation manifest')
        changed = [item['path'] for item in manifest['files'] if not Path(item['path']).exists()
                   or digest(Path(item['path'])) != item['after_sha256']]
        if changed:
            raise SystemExit('Changed since installation; preserve and review: ' + ', '.join(changed))
        if args.action == 'rollback':
            for item in reversed(manifest['files']):
                target = Path(item['path'])
                if item['existed']:
                    shutil.copy2(item['backup'], target)
                else:
                    target.unlink()
            print('Restored recorded pre-install files. Backup retained.')
        else:
            print(f'PASS: {len(manifest["files"])} installed files match manifest.')
        return
    backup.mkdir(parents=True, exist_ok=True)

    def put(path, data):
        path = Path(path)
        item = next((x for x in manifest['files'] if x['path'] == str(path)), None)
        if item and path.exists() and digest(path) != item.get('after_sha256'):
            raise RuntimeError('Refusing to overwrite changes since installation: ' + str(path))
        if not item:
            item = {'path': str(path), 'existed': path.exists()}
            if path.exists():
                destination = backup / (str(len(manifest['files'])) + '-' + path.name)
                shutil.copy2(path, destination)
                item.update(backup=str(destination), before_sha256=digest(path))
            manifest['files'].append(item)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.vse-install-tmp')
        temporary.write_bytes(data if isinstance(data, bytes) else data.encode('utf8'))
        temporary.replace(path)
        item['after_sha256'] = digest(path)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf8')

    source = args.source.resolve()
    runtime = home / '.zcode/worker-runtime'
    names = ['supervisor.py', 'zcode_worker.py', 'zcode_process.py', 'zcode_guard.py',
             'git_worktree.py', 'project_checks.py', 'agy_cli.py', 'install_zcode.py']
    for name in names:
        put(runtime / 'tools/agents' / name, (source / 'tools/agents' / name).read_bytes())
    for name in ('worker-result.schema.json', 'worker-handoff.schema.json', 'agent-task.schema.json',
                 'codex-plan.schema.json', 'codex-review.schema.json'):
        path = source / 'schemas' / name
        if path.exists():
            put(runtime / 'schemas' / name, path.read_bytes())
    put(home / '.zcode/tools/vse-worker-guard.py', (source / 'tools/agents/zcode_guard.py').read_bytes())
    providers = json.loads((home / '.zcode/v2/config.json').read_text(encoding='utf-8-sig'))['provider']
    matches = [(key, value) for key, value in providers.items()
               if value.get('name') == 'Gemini' and 'gemini-3.8-flash-high' in value.get('models', {})]
    if len(matches) != 1:
        raise RuntimeError('Expected exactly one configured Gemini provider')
    provider_id = matches[0][0]
    node = shutil.which('node')
    cli = Path('D:/zcode/resources/glm/zcode.cjs')
    if not node or not cli.is_file():
        raise RuntimeError('Configured local Node/ZCode installation unavailable')
    provider_models = matches[0][1].get('models', {})
    allowed_models = ['gemini-3.8-flash-high']
    model_slots = {
        'flash': {
            'model': 'gemini-3.8-flash-high',
            'official_model': 'gemini-3.8-flash',
            'thinking_level': 'high',
        },
    }
    # Legacy contracts may request pro; it is a slot alias, never a Pro model.
    model_slots['pro'] = dict(model_slots['flash'])
    settings = {'lead_agent': 'codex', 'worker_agent': 'zcode-app-server', 'profile': 'agy-heavy',
                'routing_profile': 'gemini-flash-only',
                'route_policy': {'default': 'flash', 'task_kinds': {
                    'exploration': 'flash', 'mechanical': 'flash', 'test-only': 'flash',
                    'ui': 'flash', 'ordinary-implementation': 'flash',
                    'complex-implementation': 'pro', 'root-cause': 'pro', 'deep-review': 'pro'}},
                'glm_probe': {'enabled': False, 'explicit_opt_in': True, 'failure_policy': 'skip'},
                'worktree_root': '.agents/worktrees',
                'auto_merge': False, 'auto_commit_worker': False,
                'max_agy_repair_attempts': 2, 'max_total_agent_runs': 2,
                'codex': {'profile': 'official', 'allowed_profiles': ['official']},
                'zcode': {'node_executable': node, 'cli_entry': str(cli), 'provider_id': provider_id,
                          'provider_config': str(home / '.zcode/v2/config.json'),
                          'model': 'gemini-3.8-flash-high', 'allowed_models': allowed_models,
                          'timeout_seconds': 900, 'context_window_tokens': 1000000,
                          'safety_reserve_tokens': 16384, 'max_output_tokens': 32768,
                          'max_model_turns': 64, 'max_tool_calls': 256,
                          'max_tool_output_chars': 32768, 'model_slots': model_slots,
                          'cache_policy': {'mode': 'implicit-prefix', 'explicit_cache': False,
                                           'ttl_seconds': 900, 'allow_production_data': False},
                          'preflight': {'required': True, 'network_probe': True},
                          'preflight_timeout_seconds': 60, 'preflight_retries': 2}}
    put(runtime / 'config.json', json.dumps(settings, ensure_ascii=False, indent=2) + '\n')
    project_config = source / '.agents/config.json'
    if project_config.exists():
        existing = json.loads(project_config.read_text(encoding='utf-8-sig'))
        existing.update({key: settings[key] for key in (
            'worker_agent', 'profile', 'routing_profile', 'route_policy', 'glm_probe', 'zcode',
            'auto_merge', 'auto_commit_worker', 'max_agy_repair_attempts'
        )})
        put(project_config, json.dumps(existing, ensure_ascii=False, indent=2) + '\n')
    user_config_path = home / '.zcode/cli/config.json'
    user_config = json.loads(user_config_path.read_text(encoding='utf-8-sig'))
    old_mcp = user_config.get('mcp', {}).get('servers', {}).get('agy-subagent')
    if old_mcp is not None:
        old_mcp['enabled'] = False
    hooks = user_config.setdefault('hooks', {})
    hooks['enabled'] = True
    entries = hooks.setdefault('events', {}).setdefault('PreToolUse', [])
    guard_path = str(home / '.zcode/tools/vse-worker-guard.py')
    entries[:] = [entry for entry in entries if not any(guard_path in h.get('args', []) for h in entry.get('hooks', []))]
    entries.append({'hooks': [{'type': 'process', 'command': sys.executable, 'args': [guard_path], 'timeoutMs': 5000}]})
    put(user_config_path, json.dumps(user_config, ensure_ascii=False, indent=2) + '\n')
    model_ref = f'custom:{provider_id}:gemini-3.8-flash-high'
    review_model_ref = model_ref
    review_thought_level = 'high'
    for name, description, body, turns in [
        ('readonly-explorer', 'Bounded read-only repository search with Gemini. Return exact files, symbols and evidence; no external agent routing.',
         'Read only the bounded scope supplied by the lead. Use Read/Grep/Glob. Do not delegate, execute commands, edit files, or make final architecture decisions. Return concise evidence and unresolved questions; never whole files.', 12),
        ('code-reviewer', 'Read-only review of meaningful changes; report confirmed actionable regressions with evidence.',
         'Review only supplied changes and surrounding contracts. Do not modify files, delegate or invent findings. Report severity, file/line evidence, impact and minimal fix. Clearly separate uncertainty; say when no material issue is found.', 12),
    ]:
        selected_model_ref = review_model_ref if name == 'code-reviewer' else model_ref
        selected_thought_level = review_thought_level if name == 'code-reviewer' else 'high'
        text = f'---\nname: "{name}"\ndescription: "{description}"\nmodel: "{selected_model_ref}"\nthoughtLevel: {selected_thought_level}\ncolor: yellow\ntools:\n  - Read\n  - Grep\n  - Glob\nmaxTurns: {turns}\ninjectAgentsMd: false\n---\n\n{body}\n'
        put(home / '.zcode/agents' / (name + '.md'), text)
    launcher = f'''[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Workspace,
      [Parameter(Mandatory=$true)][string]$TaskFile,
      [string]$WorkerProfile,
      [switch]$DryRun)
$ErrorActionPreference = 'Stop'
$targetWorkspace = (Resolve-Path -LiteralPath $Workspace).Path
$targetTask = (Resolve-Path -LiteralPath $TaskFile).Path
Push-Location -LiteralPath $targetWorkspace
try {{
    $workerArguments = @('{str(runtime / 'tools/agents/supervisor.py')}', 'run', '--task-file', $targetTask)
    if ($WorkerProfile) {{ $workerArguments += @('--worker-profile', $WorkerProfile) }}
    if ($DryRun) {{ $workerArguments += '--dry-run' }}
    & '{sys.executable}' @workerArguments
    if ($LASTEXITCODE -ne 0) {{ throw "Worker supervisor exited with $LASTEXITCODE" }}
}} finally {{ Pop-Location }}
'''
    put(home / '.zcode/tools/run-worker.ps1', launcher)
    codex_path = home / '.codex/AGENTS.md'
    prior = codex_path.read_text(encoding='utf-8-sig') if codex_path.exists() else ''
    marker = '<!-- zcode-worker-routing:start -->'
    if marker in prior:
        prior = prior[:prior.index(marker)].rstrip() + '\n'
    put(codex_path, prior + '''
<!-- zcode-worker-routing:start -->
- Default workflow: Codex Luna at max reasoning is the lead for architecture, contracts, complex debugging, security and final review. Delegate bounded implementation/tests/documentation to the configured ZCode Gemini 3.8 Flash runtime; Gemini usage is not cost-capped, while non-Codex context is capped at 1M (950848 input tokens with the default output/reserve budget).
- Use the local PowerShell launcher `C:/Users/Lynch/.zcode/tools/run-worker.ps1 -Workspace <repo> -TaskFile <contract.json>`; add `-DryRun` to inspect the explicit route. A project-defined temporary worker profile is selected only with `-WorkerProfile <name>`. Never use bare `zcode --prompt`, AGY MCP, a missing AGY model provider, or a DeepSeek worker as an implicit fallback.
- Contract: task_id (TASK-...), objective, scope, constraints, acceptance_criteria, risk_class, task_kind, model_slot, verification_commands (argument arrays). Batch related work. Use synthetic data and concise evidence; do not copy full conversation, secrets, or production data.
- Each writer uses an isolated worktree. Native tools are guarded; shells and nested agents are unavailable. The supervisor runs the supplied focused checks. Read the result, diff and check output before integrating. Preserve unrelated changes; no automatic merge or push.
- High-risk/unclassified work remains with this lead, without spawning a second Codex planner. At most two targeted repair rounds; blocked/timeout/quota/model errors stop, never silently switch provider. All Gemini worker slots use 3.8 Flash; complex root-cause judgment stays with the lead. In a GLM-led session, let GLM own the task unless the user explicitly escalates to Codex.
<!-- zcode-worker-routing:end -->
''')
    put(home / '.zcode/AGENTS.md', '''# Local agent workflow

- When the user works directly in ZCode, the selected model is the lead. During free GLM periods use the flagship model actually available under the account; do not hardcode an old model or silently switch to paid usage.
- When invoked with a bounded worker contract, act only as that worker. Follow supplied scope and contracts; do not delegate again or start Codex/AGY/DeepSeek. The invoking lead owns architecture, security and final integration.
- Gemini Flash is the default for bounded implementation, tests, mechanical sweeps and evidence collection; Gemini 3.8 Flash also handles bounded deep read-only review; Pro is disabled. Pass concrete scope, constraints and checks. Keep each worker at or below 1M context and do not re-read full project memory or paste whole files/logs back.
- One lead and one writer per worktree. Preserve unrelated changes. Keep credentials and production data out of prompts, logs and reports. Stop on ambiguity affecting interfaces, concurrency, security or migrations.
- Do not use the retired agy-subagent MCP route. Model/permission/quota failures must be reported, never trigger a silent paid fallback. The main agent runs final checks and reviews the actual diff.
''')
    print('Installed guarded ZCode worker routing. Restart/new sessions load updated roles. Backup:', backup)


if __name__ == '__main__':
    main()
