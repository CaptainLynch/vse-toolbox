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


def test_build_prompt_workspace_edit_and_escalation_rules():
    task = {
        "task_id": "TASK-123",
        "objective": "Test objective",
    }
    prompt = agy_cli.build_prompt(task)

    assert "write_to_file is artifact-only and must not be used for workspace paths" in prompt
    assert "Apply workspace edits through terminal commands inside the current isolated worktree" in prompt
    assert "Do not request administrator escalation" in prompt
    assert "return compact findings" in prompt
    assert '"task_id": "TASK-123"' in prompt
