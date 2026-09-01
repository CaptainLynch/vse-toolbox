import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "agents" / "agy_cli.py"
SPEC = importlib.util.spec_from_file_location("agy_cli_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
agy_cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agy_cli)


def test_build_command_places_prompt_after_print(monkeypatch, tmp_path):
    monkeypatch.setattr(agy_cli.shutil, "which", lambda _: "C:/tools/agy.exe")
    command = agy_cli.build_command(
        {
            "model": "gemini-3.7-flash-high",
            "effort": "high",
            "mode": "accept-edits",
            "sandbox": True,
            "new_project": True,
            "timeout_seconds": 120,
        },
        tmp_path / "schema.json",
        "structured prompt",
    )

    assert command[-2:] == ["--print", "structured prompt"]
    assert command[command.index("--model") + 1] == "gemini-3.7-flash-high"
    assert "--effort" not in command
    assert "--sandbox" in command
    assert "--dangerously-skip-permissions" not in command


def test_build_command_uses_effort_for_model_without_embedded_tier(monkeypatch, tmp_path):
    monkeypatch.setattr(agy_cli.shutil, "which", lambda _: "C:/tools/agy.exe")
    command = agy_cli.build_command(
        {"model": "custom-model", "effort": "medium"},
        tmp_path / "schema.json",
        "structured prompt",
    )

    assert command[command.index("--effort") + 1] == "medium"


def test_parse_nested_json_result():
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
    stdout = json.dumps({"result": json.dumps(expected)})

    assert agy_cli._parse_result(stdout, "TASK-1") == expected


def test_parse_agy_structured_output_field():
    expected = {
        "task_id": "TASK-1",
        "status": "completed",
        "summary": "done",
        "changed_files": ["marker.txt"],
        "tests": [],
        "commands_executed": ["git status --short"],
        "risks": [],
        "unresolved": [],
        "needs_review": True,
    }
    stdout = json.dumps({"status": "SUCCESS", "response": "ignored prose", "structured_output": expected})

    assert agy_cli._parse_result(stdout, "TASK-1") == expected


def test_permission_denial_is_blocked():
    result = agy_cli._process_failure(
        "TASK-1",
        "permission check failed: user denied permission",
        1,
    )

    assert result["status"] == "blocked"


def test_headless_permission_denial_with_zero_exit_is_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(agy_cli, "executable", lambda _: "agy")
    stderr = (
        'jetski: no output produced — a tool required the "command" permission '
        "that headless mode cannot prompt for, so it was auto-denied."
    )

    monkeypatch.setattr(
        agy_cli.subprocess,
        "run",
        lambda *args, **kwargs: type(
            "Completed",
            (),
            {
                "stdout": json.dumps({"status": "CANCELED", "response": ""}),
                "stderr": stderr,
                "returncode": 0,
            },
        )(),
    )

    result = agy_cli.invoke(
        {"task_id": "TASK-HEADLESS", "objective": "test"},
        tmp_path,
        tmp_path / "run",
        config={},
    )

    assert result["status"] == "blocked"
    assert result["summary"] == "AGY sandbox denied a requested command."
    assert result["unresolved"] == [stderr]


def test_build_prompt_workspace_edit_and_escalation_rules():
    task = {
        "task_id": "TASK-123",
        "objective": "Test objective",
    }
    prompt = agy_cli.build_prompt(task, max_repair_attempts=3)

    assert "write_to_file is artifact-only and must not be used for workspace paths" in prompt
    assert "Apply workspace edits through terminal commands inside the current isolated worktree" in prompt
    assert "Do not request administrator escalation" in prompt
    assert "return compact findings" in prompt
    assert "You may perform up to 3 self-repair attempts" in prompt
    assert "Stop and escalate on architecture, security, authentication, authorization" in prompt
    assert "Run only the verification_commands specified in the task" in prompt
    assert '"task_id": "TASK-123"' in prompt


def test_invoke_uses_configured_max_repair_attempts(monkeypatch, tmp_path):
    monkeypatch.setattr(agy_cli, "executable", lambda _: "agy")
    captured = {}

    def mock_build_command(cfg, schema, prompt, resolve_executable=True):
        captured["prompt"] = prompt
        return ["agy", "--print", prompt]

    monkeypatch.setattr(agy_cli, "build_command", mock_build_command)
    monkeypatch.setattr(
        agy_cli.subprocess,
        "run",
        lambda *args, **kwargs: type(
            "Completed",
            (),
            {
                "stdout": json.dumps({
                    "task_id": "TASK-R",
                    "status": "completed",
                    "summary": "ok",
                    "changed_files": [],
                    "tests": [],
                    "commands_executed": [],
                    "risks": [],
                    "unresolved": [],
                    "needs_review": True,
                }),
                "stderr": "",
                "returncode": 0,
            },
        )(),
    )

    # Configured in config
    config = {"max_agy_repair_attempts": 4}
    task = {"task_id": "TASK-R", "objective": "test"}
    agy_cli.invoke(task, tmp_path, tmp_path / "run", config)
    assert "You may perform up to 4 self-repair attempts" in captured["prompt"]

    # Per-task field overrides default
    task_with_field = {"task_id": "TASK-R", "objective": "test", "agy_self_repair_attempts": 5}
    agy_cli.invoke(task_with_field, tmp_path, tmp_path / "run", config={})
    assert "You may perform up to 5 self-repair attempts" in captured["prompt"]

    # Default without config is 3
    agy_cli.invoke(task, tmp_path, tmp_path / "run", config={})
    assert "You may perform up to 3 self-repair attempts" in captured["prompt"]


def test_build_command_uses_flash_low_without_separate_effort(monkeypatch, tmp_path):
    monkeypatch.setattr(agy_cli.shutil, "which", lambda _: "C:/tools/agy.exe")
    command = agy_cli.build_command(
        {
            "model": "gemini-3.7-flash-low",
            "effort": "high",
            "mode": "accept-edits",
            "sandbox": True,
            "new_project": True,
            "timeout_seconds": 120,
        },
        tmp_path / "schema.json",
        "structured prompt",
    )

    assert command[command.index("--model") + 1] == "gemini-3.7-flash-low"
    assert "--effort" not in command


def test_invoke_records_resolved_model_in_process_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(agy_cli, "executable", lambda _: "agy")
    monkeypatch.setattr(
        agy_cli.subprocess,
        "run",
        lambda *args, **kwargs: type(
            "Completed",
            (),
            {
                "stdout": json.dumps({
                    "task_id": "TASK-PROC-MODEL",
                    "status": "completed",
                    "summary": "ok",
                    "changed_files": [],
                    "tests": [],
                    "commands_executed": [],
                    "risks": [],
                    "unresolved": [],
                    "needs_review": True,
                }),
                "stderr": "",
                "returncode": 0,
            },
        )(),
    )

    config = {"model": "gemini-3.7-flash-high"}
    task = {"task_id": "TASK-PROC-MODEL", "objective": "test"}
    result = agy_cli.invoke(task, tmp_path, tmp_path / "run", config=config)
    assert result["process"]["model"] == "gemini-3.7-flash-high"

    config_low = {"model": "gemini-3.7-flash-low"}
    result_low = agy_cli.invoke(task, tmp_path, tmp_path / "run", config=config_low)
    assert result_low["process"]["model"] == "gemini-3.7-flash-low"
