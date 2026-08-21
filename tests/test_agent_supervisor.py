import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "agents" / "supervisor.py"
SPEC = importlib.util.spec_from_file_location("supervisor_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
supervisor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(supervisor)


def test_normalize_task_preserves_argument_array_verification_commands():
    task = supervisor.normalize_task(
        {
            "objective": "test",
            "scope": ["README.md"],
            "constraints": [],
            "acceptance_criteria": ["passes"],
            "verification_commands": [["python", "-m", "pytest", "tests/test_readme.py", "-q"]],
        },
        "TASK-1",
    )

    assert task["verification_commands"] == [["python", "-m", "pytest", "tests/test_readme.py", "-q"]]


def test_collect_change_evidence_includes_only_scoped_untracked_text(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "allowed.txt").write_bytes(b"allowed\n")
    (tmp_path / "outside.txt").write_bytes(b"outside\n")

    evidence = supervisor.collect_change_evidence(tmp_path, ["allowed.txt"])
    records = {item["path"]: item for item in evidence["untracked_files"]}

    assert "?? allowed.txt" in evidence["status"]
    assert records["allowed.txt"]["content"] == "allowed\n"
    assert records["outside.txt"]["omitted_reason"] == "outside explicit task scope"


def test_blocked_worker_stops_before_checks_and_review(monkeypatch, tmp_path):
    worker_tree = tmp_path / "worker"
    worker_tree.mkdir()
    config = {
        "agy": {},
        "worktree_root": ".agents/worktrees",
        "max_agy_rounds": 3,
        "max_codex_review_rounds": 2,
        "max_total_agent_runs": 6,
    }
    monkeypatch.setattr(supervisor, "config", lambda _: config)
    monkeypatch.setattr(
        supervisor,
        "create_plan",
        lambda *args: {"route": "agy", "worker_effort": "high"},
    )
    monkeypatch.setattr(supervisor.worktrees, "create", lambda *args: worker_tree)
    monkeypatch.setattr(
        supervisor.agy_cli,
        "invoke",
        lambda *args: {
            "task_id": "TASK-BLOCKED",
            "status": "blocked",
            "summary": "permission denied",
            "changed_files": [],
            "tests": [],
            "commands_executed": [],
            "risks": [],
            "unresolved": [],
            "needs_review": True,
        },
    )

    def unexpected_checks(*args, **kwargs):
        raise AssertionError("checks must not run after a blocked worker")

    monkeypatch.setattr(supervisor.checks, "run_checks", unexpected_checks)
    task = supervisor.normalize_task(
        {
            "task_id": "TASK-BLOCKED",
            "objective": "test blocked handling",
            "scope": ["marker.txt"],
            "constraints": [],
            "acceptance_criteria": ["stops"],
        }
    )

    assert supervisor.run(tmp_path, task, dry_run=False) == 0
    state = json.loads((tmp_path / ".agents/runs/TASK-BLOCKED/state.json").read_text(encoding="utf-8"))
    assert state["status"] == "codex-takeover-required"
    assert state["round"] == 1
    assert not (tmp_path / ".agents/runs/TASK-BLOCKED/checks-round-1.json").exists()


def test_context_canceled_worker_recovers_only_with_changes_and_passing_checks():
    worker = {
        "status": "failed",
        "summary": "AGY CLI exited with code 1.",
        "changed_files": [],
        "tests": [],
        "commands_executed": [],
        "unresolved": ["context canceled"],
        "needs_review": True,
    }
    evidence = {"status": "?? marker.txt\n"}
    checks = [{"command": ["git", "status", "--short"], "exit_code": 0}]

    recovered = supervisor.recover_context_canceled_worker(worker, evidence, checks)

    assert recovered["status"] == "partial"
    assert recovered["changed_files"] == ["marker.txt"]
    assert recovered["transport_recovered"] is True


def test_context_canceled_worker_is_not_recovered_when_checks_fail():
    worker = {"status": "failed", "unresolved": ["context canceled"]}
    evidence = {"status": "?? marker.txt\n"}
    checks = [{"command": ["test"], "exit_code": 1}]

    assert supervisor.recover_context_canceled_worker(worker, evidence, checks) is worker


def test_dirty_scope_conflicts_only_returns_paths_in_task_scope(monkeypatch, tmp_path):
    result = SimpleNamespace(
        stdout=" M services/owned.py\n M README.md\n?? services/new.py\n",
        stderr="",
        returncode=0,
    )
    monkeypatch.setattr(supervisor, "_git", lambda *args: result)
    task = {"scope": ["services"], "context": {}}

    assert supervisor.dirty_scope_conflicts(tmp_path, task) == ["services/owned.py", "services/new.py"]


def test_requires_current_worktree_rejects_any_dirty_path(monkeypatch, tmp_path):
    result = SimpleNamespace(stdout=" M README.md\n", stderr="", returncode=0)
    monkeypatch.setattr(supervisor, "_git", lambda *args: result)
    task = {"scope": ["services"], "context": {"requires_current_worktree": True}}

    assert supervisor.dirty_scope_conflicts(tmp_path, task) == ["README.md"]
