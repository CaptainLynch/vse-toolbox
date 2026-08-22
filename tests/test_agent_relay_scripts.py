"""Tests for temporary Codex relay provider configuration and PowerShell setup scripts."""
import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = REPO_ROOT / "tools" / "agents" / "setup_codex_relay_profile.ps1"
RUN_SCRIPT = REPO_ROOT / "tools" / "agents" / "run_supervisor.ps1"
DESKTOP_SWITCH_SCRIPT = REPO_ROOT / "tools" / "agents" / "switch_codex_desktop.ps1"
START_SCRIPT = REPO_ROOT / "start-supervisor.ps1"
CONFIG_JSON = REPO_ROOT / ".agents" / "config.json"


def find_powershell() -> str:
    for name in ("pwsh", "powershell"):
        exe = shutil.which(name)
        if exe:
            return exe
    pytest.skip("PowerShell executable (pwsh or powershell) not found on system.")


def normalize_ps_output(text: str) -> str:
    """Normalize PowerShell error and output formatting by stripping margin pipes and extra spaces."""
    cleaned_lines = []
    for line in text.splitlines():
        trimmed = re.sub(r"^\s*\|\s*", "", line).strip()
        if trimmed and not trimmed.startswith("~") and not trimmed.startswith("Line |"):
            cleaned_lines.append(trimmed)
    return " ".join(cleaned_lines)


def run_ps_setup(codex_home: Path | str, extra_args: tuple[str, ...] = (), env_vars: dict[str, str] | None = None):
    ps = find_powershell()
    cmd = [
        ps,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SETUP_SCRIPT),
        "-CodexHome",
        str(codex_home),
        *extra_args,
    ]
    env = os.environ.copy()
    if env_vars:
        env.update(env_vars)
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )


def run_ps_supervisor(args: tuple[str, ...], env_vars: dict[str, str] | None = None):
    ps = find_powershell()
    cmd = [
        ps,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(RUN_SCRIPT),
        *args,
    ]
    env = os.environ.copy()
    if env_vars:
        env.update(env_vars)
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )


def run_ps_desktop(args: tuple[str, ...], env_vars: dict[str, str] | None = None):
    ps = find_powershell()
    cmd = [
        ps,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(DESKTOP_SWITCH_SCRIPT),
        *args,
    ]
    env = os.environ.copy()
    env.pop("CODEX_RELAY_API_KEY", None)
    if env_vars:
        env.update(env_vars)
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )


def test_checked_in_setup_script_parameters_and_toml_content():
    """Verify checked-in relay parameters match exact requirements."""
    content = SETUP_SCRIPT.read_text(encoding="utf-8")
    assert 'model = "GPT-5.6 SOL"' in content
    assert 'model_provider = "vse_relay"' in content
    assert 'name = "VSE temporary Responses relay"' in content
    assert 'base_url = "https://node-cf.sssaicodeapi.com/api/v1"' in content
    assert 'env_key = "CODEX_RELAY_API_KEY"' in content
    assert 'wire_api = "responses"' in content
    assert "request_max_retries = 2" in content
    assert "stream_max_retries = 4" in content
    assert "stream_idle_timeout_ms = 300000" in content


def test_checked_in_config_codex_relay_definition():
    """Verify .agents/config.json declares official and relay profiles properly."""
    cfg = json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
    codex_cfg = cfg.get("codex", {})
    assert codex_cfg.get("allowed_profiles") == ["official", "relay"]
    profiles = codex_cfg.get("profiles", {})
    assert profiles.get("official") == {"cli_profile": None, "required_env": None}
    assert profiles.get("relay") == {
        "cli_profile": "vse-relay",
        "required_env": "CODEX_RELAY_API_KEY",
    }


def test_no_embedded_secrets_in_scripts_and_config():
    """Verify no hardcoded secret keys or tokens exist in scripts or config."""
    secret_patterns = [
        re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
        re.compile(r"(?i)api[_-]?key\s*[:=]\s*['\"][a-zA-Z0-9_\-]{16,}['\"]"),
        re.compile(r"(?i)bearer\s+[a-zA-Z0-9_\-]{20,}"),
    ]
    files_to_check = [
        SETUP_SCRIPT,
        RUN_SCRIPT,
        CONFIG_JSON,
        REPO_ROOT / "tools" / "agents" / "supervisor.py",
        DESKTOP_SWITCH_SCRIPT,
        START_SCRIPT,
    ]
    for path in files_to_check:
        text = path.read_text(encoding="utf-8")
        for pattern in secret_patterns:
            matches = pattern.findall(text)
            assert not matches, f"Potential secret found in {path}: {matches}"


def test_setup_relay_profile_fresh_install(tmp_path):
    """Fresh installation in isolated tmp_path creates vse-relay.config.toml with approved content."""
    res = run_ps_setup(tmp_path)
    assert res.returncode == 0, f"Setup script failed:\nstdout: {res.stdout}\nstderr: {res.stderr}"
    assert "Installed relay profile without storing an API key" in res.stdout

    target = tmp_path / "vse-relay.config.toml"
    assert target.exists()
    content = target.read_text(encoding="utf-8")
    assert 'model = "GPT-5.6 SOL"' in content
    assert 'base_url = "https://node-cf.sssaicodeapi.com/api/v1"' in content
    assert 'env_key = "CODEX_RELAY_API_KEY"' in content
    assert 'wire_api = "responses"' in content

    raw_bytes = target.read_bytes()
    assert not raw_bytes.startswith(b"\xef\xbb\xbf"), "TOML file must not include a UTF-8 BOM"


def test_setup_relay_profile_idempotent_install(tmp_path):
    """Re-running install when configuration already matches is a no-op."""
    res1 = run_ps_setup(tmp_path)
    assert res1.returncode == 0

    res2 = run_ps_setup(tmp_path)
    assert res2.returncode == 0
    assert "Relay profile already matches the approved configuration" in res2.stdout

    backups = list(tmp_path.glob("*.backup-*"))
    assert len(backups) == 0


def test_setup_relay_profile_check_only_missing(tmp_path):
    """CheckOnly throws error when profile is not installed."""
    res = run_ps_setup(tmp_path, extra_args=("-CheckOnly",))
    assert res.returncode != 0
    combined = normalize_ps_output(res.stdout + res.stderr)
    assert "Relay profile is not installed" in combined


def test_setup_relay_profile_check_only_matching(tmp_path):
    """CheckOnly succeeds when profile is installed and matches approved configuration."""
    run_ps_setup(tmp_path)
    res = run_ps_setup(tmp_path, extra_args=("-CheckOnly",))
    assert res.returncode == 0
    assert "Relay profile is installed and matches the approved configuration" in res.stdout


def test_setup_relay_profile_check_only_mismatched(tmp_path):
    """CheckOnly throws error when profile exists but differs from approved configuration."""
    target = tmp_path / "vse-relay.config.toml"
    target.write_text('model = "wrong-model"\n', encoding="utf-8")

    res = run_ps_setup(tmp_path, extra_args=("-CheckOnly",))
    assert res.returncode != 0
    combined = normalize_ps_output(res.stdout + res.stderr)
    assert "does not match the approved configuration" in combined


def test_setup_relay_profile_mismatch_refuses_without_force(tmp_path):
    """Installation over mismatched content throws without -Force."""
    target = tmp_path / "vse-relay.config.toml"
    target.write_text('model = "custom-model"\n', encoding="utf-8")

    res = run_ps_setup(tmp_path)
    assert res.returncode != 0
    combined = normalize_ps_output(res.stdout + res.stderr)
    assert "Re-run with -Force to create a timestamped backup and replace it" in combined

    assert target.read_text(encoding="utf-8") == 'model = "custom-model"\n'


def test_setup_relay_profile_force_replaces_with_backup(tmp_path):
    """Installation with -Force creates timestamped backup and overwrites with approved TOML."""
    target = tmp_path / "vse-relay.config.toml"
    original_custom_content = 'model = "custom-model"\ncustom_key = "value"\n'
    target.write_text(original_custom_content, encoding="utf-8")

    res = run_ps_setup(tmp_path, extra_args=("-Force",))
    assert res.returncode == 0
    assert "Installed relay profile without storing an API key" in res.stdout

    assert 'model = "GPT-5.6 SOL"' in target.read_text(encoding="utf-8")

    backups = list(tmp_path.glob("vse-relay.config.toml.backup-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original_custom_content


def test_setup_relay_profile_respects_env_codex_home(tmp_path):
    """When -CodexHome is omitted, setup respects CODEX_HOME environment variable."""
    ps = find_powershell()
    cmd = [
        ps,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SETUP_SCRIPT),
    ]
    env = os.environ.copy()
    env["CODEX_HOME"] = str(tmp_path)
    res = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    assert res.returncode == 0
    assert (tmp_path / "vse-relay.config.toml").exists()


def test_run_supervisor_relay_fails_if_profile_not_installed(tmp_path):
    """run_supervisor.ps1 fails when -CodexProfile relay is used without setup."""
    dummy_task = REPO_ROOT / ".agents" / "tasks" / "test_tmp_task.json"
    dummy_task.parent.mkdir(parents=True, exist_ok=True)
    try:
        dummy_task.write_text(json.dumps({
            "objective": "test",
            "scope": ["README.md"],
            "constraints": [],
            "acceptance_criteria": [],
            "verification_commands": [["python", "-c", "print('ok')"]],
        }), encoding="utf-8")

        res = run_ps_supervisor(
            ("-TaskFile", str(dummy_task), "-CodexProfile", "relay", "-DryRun"),
            env_vars={"CODEX_HOME": str(tmp_path)},
        )
        assert res.returncode != 0
        combined = normalize_ps_output(res.stdout + res.stderr)
        assert "Relay profile is not installed" in combined
    finally:
        if dummy_task.exists():
            dummy_task.unlink()


def test_run_supervisor_dry_run_relay_with_installed_profile(tmp_path):
    """run_supervisor.ps1 succeeds on dry-run with relay profile and process key."""
    run_ps_setup(tmp_path)

    dummy_task = REPO_ROOT / ".agents" / "tasks" / "test_tmp_task_dryrun.json"
    dummy_task.parent.mkdir(parents=True, exist_ok=True)
    try:
        dummy_task.write_text(json.dumps({
            "objective": "test dry run",
            "category": "mechanical",
            "scope": ["README.md"],
            "constraints": [],
            "acceptance_criteria": [],
            "verification_commands": [["python", "-c", "print('ok')"]],
        }), encoding="utf-8")

        res = run_ps_supervisor(
            ("-TaskFile", str(dummy_task), "-CodexProfile", "relay", "-SupervisorProfile", "agy-heavy", "-DryRun"),
            env_vars={
                "CODEX_HOME": str(tmp_path),
                "CODEX_RELAY_API_KEY": "dummy-process-key",
            },
        )
        assert res.returncode == 0
        assert "Running supervisor with orchestration profile 'agy-heavy' and Codex profile 'relay'" in res.stdout
    finally:
        if dummy_task.exists():
            dummy_task.unlink()


def test_run_supervisor_rejects_task_file_outside_repo(tmp_path):
    """run_supervisor.ps1 rejects task files outside the repository root."""
    outside_task = tmp_path / "outside_task.json"
    outside_task.write_text("{}", encoding="utf-8")

    res = run_ps_supervisor(("-TaskFile", str(outside_task)))
    assert res.returncode != 0
    combined = normalize_ps_output(res.stdout + res.stderr)
    assert "Task file must remain inside the repository" in combined


def test_desktop_switch_relay_then_restores_exact_official_config(tmp_path):
    original = 'model = "gpt-5.6-sol"\n\n[features]\njs_repl = false\n'
    config = tmp_path / "config.toml"
    config.write_text(original, encoding="utf-8")

    relay = run_ps_desktop(
        ("-CodexProfile", "relay", "-CodexHome", str(tmp_path), "-ConfigureOnly"),
        env_vars={"CODEX_RELAY_API_KEY": "dummy-process-key"},
    )
    assert relay.returncode == 0, relay.stderr
    relay_config = config.read_text(encoding="utf-8")
    parsed = tomllib.loads(relay_config)
    assert 'model = "GPT-5.6 SOL"' in relay_config
    assert 'model_provider = "vse_relay"' in relay_config
    assert 'base_url = "https://node-cf.sssaicodeapi.com/api/v1"' in relay_config
    assert 'wire_api = "responses"' in relay_config
    assert parsed["model"] == "GPT-5.6 SOL"
    assert parsed["model_provider"] == "vse_relay"
    assert parsed["model_providers"]["vse_relay"]["wire_api"] == "responses"

    state_path = tmp_path / ".vse-profile-switch" / "state.json"
    state_text = state_path.read_text(encoding="utf-8")
    assert "dummy-process-key" not in state_text
    assert "CODEX_RELAY_API_KEY" not in state_text

    official = run_ps_desktop(
        ("-CodexProfile", "official", "-CodexHome", str(tmp_path), "-ConfigureOnly")
    )
    assert official.returncode == 0, official.stderr
    assert config.read_text(encoding="utf-8") == original
    assert not state_path.exists()
    assert not (tmp_path / ".vse-profile-switch" / "official.config.toml").exists()


def test_desktop_switch_missing_relay_key_does_not_change_config(tmp_path):
    original = 'model = "gpt-5.6-sol"\n'
    config = tmp_path / "config.toml"
    config.write_text(original, encoding="utf-8")

    result = run_ps_desktop(
        ("-CodexProfile", "relay", "-CodexHome", str(tmp_path), "-ConfigureOnly")
    )
    assert result.returncode != 0
    assert "CODEX_RELAY_API_KEY" in normalize_ps_output(result.stdout + result.stderr)
    assert config.read_text(encoding="utf-8") == original
    assert not (tmp_path / ".vse-profile-switch").exists()


def test_desktop_restore_refuses_to_discard_changes_made_in_relay_mode(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('model = "gpt-5.6-sol"\n', encoding="utf-8")
    relay = run_ps_desktop(
        ("-CodexProfile", "relay", "-CodexHome", str(tmp_path), "-ConfigureOnly"),
        env_vars={"CODEX_RELAY_API_KEY": "dummy-process-key"},
    )
    assert relay.returncode == 0, relay.stderr
    with config.open("a", encoding="utf-8") as stream:
        stream.write("\n[desktop]\nconversationDetailMode = \"STEPS_COMMANDS\"\n")
    changed = config.read_text(encoding="utf-8")

    restore = run_ps_desktop(
        ("-CodexProfile", "official", "-CodexHome", str(tmp_path), "-ConfigureOnly")
    )
    assert restore.returncode != 0
    assert "Refusing to discard those changes" in normalize_ps_output(
        restore.stdout + restore.stderr
    )
    assert config.read_text(encoding="utf-8") == changed
