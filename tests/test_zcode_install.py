import json
import sys
from pathlib import Path

import pytest

from tools.agents import install_zcode


@pytest.fixture
def installation(tmp_path, monkeypatch):
    if not Path('D:/zcode/resources/glm/zcode.cjs').is_file():
        pytest.skip('machine-specific installer fixture')
    home = tmp_path / 'home'
    source = tmp_path / 'source'
    (home / '.zcode/cli').mkdir(parents=True)
    (home / '.zcode/v2').mkdir(parents=True)
    (home / '.codex').mkdir()
    (source / 'tools/agents').mkdir(parents=True)
    (source / '.agents').mkdir()
    original = '{"model":"original","mcp":{"servers":{"agy-subagent":{"enabled":true}}}}'
    (home / '.zcode/cli/config.json').write_text(original)
    (home / '.codex/AGENTS.md').write_text('existing rules\n')
    (source / '.agents/config.json').write_text('{"custom":"preserve"}')
    providers = {'provider': {'test-id': {'name': 'Gemini', 'models': {
        'gemini-3.8-flash-high': {}, 'gemini-pro-agent': {}, 'gemini-3.1-pro-low': {},
    }}}}
    (home / '.zcode/v2/config.json').write_text(json.dumps(providers))
    for name in ('supervisor.py', 'zcode_worker.py', 'zcode_process.py', 'zcode_guard.py',
                 'git_worktree.py', 'project_checks.py', 'agy_cli.py', 'install_zcode.py'):
        (source / 'tools/agents' / name).write_text('# fixture\n')
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))

    def run(action, *flags):
        monkeypatch.setattr(sys, 'argv', ['install', action, '--source', str(source), *flags])
        install_zcode.main()
    return home, source, original, run


def test_install_preserves_settings_and_rolls_back(installation):
    home, source, original, run = installation
    run('install')
    run('check')
    run('install')  # idempotent; original backups survive.
    config = json.loads((source / '.agents/config.json').read_text())
    assert config['custom'] == 'preserve'
    assert config['worker_agent'] == 'zcode-app-server'
    assert config['zcode']['context_window_tokens'] == 1000000
    assert config['zcode']['model_slots']['flash']['model'] == 'gemini-3.8-flash-high'
    assert config['zcode']['model_slots']['pro']['model'] == 'gemini-3.8-flash-high'
    assert config['zcode']['allowed_models'] == ['gemini-3.8-flash-high']
    reviewer = (home / '.zcode/agents/code-reviewer.md').read_text()
    explorer = (home / '.zcode/agents/readonly-explorer.md').read_text()
    assert 'custom:test-id:gemini-3.8-flash-high' in reviewer
    assert 'thoughtLevel: high' in reviewer
    assert 'custom:test-id:gemini-3.8-flash-high' in explorer
    user = json.loads((home / '.zcode/cli/config.json').read_text())
    assert user['model'] == 'original'
    assert user['mcp']['servers']['agy-subagent']['enabled'] is False
    assert len(user['hooks']['events']['PreToolUse']) == 1
    run('rollback')
    assert (home / '.zcode/cli/config.json').read_text() == original
    assert (home / '.codex/AGENTS.md').read_text() == 'existing rules\n'
    assert not (home / '.zcode/tools/run-worker.ps1').exists()


def test_rollback_preserves_later_user_edits(installation):
    home, source, original, run = installation
    run('install')
    path = home / '.codex/AGENTS.md'
    path.write_text('later user changes')
    with pytest.raises(SystemExit, match='Changed since installation'):
        run('rollback')
    assert path.read_text() == 'later user changes'
    assert json.loads((source / '.agents/config.json').read_text())['worker_agent'] == 'zcode-app-server'


def test_explicit_adopted_install_backups_changed_runtime_before_overwrite(installation):
    home, source, original, run = installation
    run('install')
    target = home / '.zcode/worker-runtime/tools/agents/supervisor.py'
    target.write_text('user-maintained runtime\n')

    run('install', '--accept-changed-targets')

    adopted_backup = home / '.zcode/backups/vse-worker-20260910-dual-tier/manifest.json'
    assert adopted_backup.exists()
    assert target.read_text() == '# fixture\n'

    run('rollback', '--installation-id', 'vse-worker-20260910-dual-tier')
    assert target.read_text() == 'user-maintained runtime\n'
