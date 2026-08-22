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
            "profile": "agy-heavy",
            "category": "mechanical",
            "risk_class": "ordinary-implementation",
            "review_policy": "manual-final",
            "agy_self_repair_attempts": 4,
        },
        "TASK-1",
    )

    assert task["verification_commands"] == [["python", "-m", "pytest", "tests/test_readme.py", "-q"]]
    assert task["profile"] == "agy-heavy"
    assert task["category"] == "mechanical"
    assert task["risk_class"] == "ordinary-implementation"
    assert task["review_policy"] == "manual-final"
    assert task["agy_self_repair_attempts"] == 4


def test_normalize_task_validates_agy_self_repair_attempts():
    import pytest

    for valid_attempts in range(1, 6):
        task = supervisor.normalize_task(
            {
                "objective": "test",
                "scope": ["README.md"],
                "constraints": [],
                "acceptance_criteria": ["passes"],
                "agy_self_repair_attempts": valid_attempts,
            },
            "TASK-1",
        )
        assert task["agy_self_repair_attempts"] == valid_attempts

    for invalid in [0, 6, -1, 1.5, True, "bad"]:
        with pytest.raises(ValueError, match="agy_self_repair_attempts"):
            supervisor.normalize_task(
                {
                    "objective": "test",
                    "scope": ["README.md"],
                    "constraints": [],
                    "acceptance_criteria": ["passes"],
                    "agy_self_repair_attempts": invalid,
                },
                "TASK-1",
            )


def test_command_checks_skips_default_checks_for_read_only_task(tmp_path):
    task = {
        "context": {"read_only": True},
        "verification_commands": [],
    }

    assert supervisor.command_checks(tmp_path, task) == []


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
        "profile": "codex-controlled",
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
        lambda *args, **kwargs: {
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
            "profile": "codex-controlled",
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


def test_agy_heavy_profile_builds_local_plan_and_awaits_manual_review(monkeypatch, tmp_path):
    worker_tree = tmp_path / "worker"
    worker_tree.mkdir()
    subprocess.run(["git", "init"], cwd=worker_tree, check=True, capture_output=True)

    config = {
        "profile": "agy-heavy",
        "max_agy_repair_attempts": 2,
        "agy": {},
        "worktree_root": ".agents/worktrees",
    }
    monkeypatch.setattr(supervisor, "config", lambda _: config)
    monkeypatch.setattr(supervisor.worktrees, "create", lambda *args: worker_tree)

    def fail_if_codex_called(*args, **kwargs):
        raise AssertionError("codex_structured must not be invoked in agy-heavy profile")

    monkeypatch.setattr(supervisor, "codex_structured", fail_if_codex_called)

    worker_invoked = []

    def mock_invoke(task, tree, run_dir, agy_cfg, effort, max_repair_attempts=None):
        worker_invoked.append((task["task_id"], max_repair_attempts))
        (tree / "component.py").write_text("# new component\n", encoding="utf-8")
        return {
            "task_id": task["task_id"],
            "status": "completed",
            "summary": "Implemented component",
            "changed_files": ["component.py"],
            "tests": [{"command": ["python", "-m", "pytest", "tests/test_ui.py"], "exit_code": 0}],
            "commands_executed": ["python -m pytest tests/test_ui.py"],
            "risks": [],
            "unresolved": [],
            "needs_review": True,
        }

    monkeypatch.setattr(supervisor.agy_cli, "invoke", mock_invoke)

    checks_run = []

    def mock_run_checks(tree, cmd_list):
        checks_run.extend(cmd_list)
        return [{"command": c, "exit_code": 0, "stdout": "ok", "stderr": ""} for c in cmd_list]

    monkeypatch.setattr(supervisor.checks, "run_checks", mock_run_checks)

    task = supervisor.normalize_task(
        {
            "task_id": "TASK-AGY-HEAVY-1",
            "objective": "Add ui button component",
            "category": "ui",
            "scope": ["component.py"],
            "constraints": ["Keep simple"],
            "acceptance_criteria": ["Button exists"],
            "verification_commands": [["python", "-m", "pytest", "tests/test_ui.py"]],
        }
    )

    assert supervisor.run(tmp_path, task, dry_run=False) == 0

    run_dir = tmp_path / ".agents/runs/TASK-AGY-HEAVY-1"
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "worker-complete-awaiting-manual-review"
    assert state["profile"] == "agy-heavy"

    plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    assert plan["planning_source"] == "task-contract"
    assert plan["route"] == "agy"

    assert len(worker_invoked) == 1
    assert worker_invoked[0][1] == 2
    assert checks_run == [["python", "-m", "pytest", "tests/test_ui.py"]]

    assert (run_dir / "worker-round-1.json").exists()
    assert (run_dir / "checks-round-1.json").exists()
    assert (run_dir / "change-evidence-round-1.json").exists()
    assert (run_dir / "git-diff-round-1.patch").exists()
    assert not (run_dir / "review-round-1.json").exists()


def test_agy_heavy_stops_before_worktree_creation_without_verification_commands(monkeypatch, tmp_path):
    config = {
        "profile": "agy-heavy",
        "agy": {},
        "worktree_root": ".agents/worktrees",
    }
    monkeypatch.setattr(supervisor, "config", lambda _: config)

    def fail_if_worktree_created(*args, **kwargs):
        raise AssertionError("Worktree must not be created when verification_commands are missing")

    monkeypatch.setattr(supervisor.worktrees, "create", fail_if_worktree_created)

    task = supervisor.normalize_task(
        {
            "task_id": "TASK-NO-CHECKS",
            "objective": "Update mechanical helper",
            "category": "mechanical",
            "scope": ["utils.py"],
            "constraints": [],
            "acceptance_criteria": ["updated"],
            "verification_commands": [],
        }
    )

    assert supervisor.run(tmp_path, task, dry_run=False) == 0
    state = json.loads((tmp_path / ".agents/runs/TASK-NO-CHECKS/state.json").read_text(encoding="utf-8"))
    assert state["status"] == "verification-commands-required"
    assert "verification_commands" in state["error"]


def test_high_risk_categories_force_codex_controlled_profile(monkeypatch, tmp_path):
    config = {"profile": "agy-heavy"}
    high_risk_categories = [
        "architecture", "security", "authentication", "authorization",
        "concurrency", "migration", "public-contract", "destructive",
    ]

    for category in high_risk_categories:
        for field in ("category", "risk_class"):
            task = {
                "task_id": f"TASK-RISK-{category}",
                "objective": f"Refactor system {category}",
                field: category,
                "scope": ["core.py"],
                "constraints": [],
                "acceptance_criteria": ["verified"],
                "verification_commands": [["python", "-m", "pytest"]],
            }
            eff, req, reason = supervisor.resolve_profile(task, config)
            assert eff == "codex-controlled", f"Expected codex-controlled for {category} ({field})"
            assert req == "agy-heavy"
            assert reason is not None


def test_low_risk_categories_evaluate_to_low():
    low_risk_categories = ["mechanical", "test-only", "ui", "ordinary-implementation"]
    for category in low_risk_categories:
        for field in ("category", "risk_class"):
            task = {
                "objective": f"Perform {category} update",
                field: category,
            }
            assert supervisor.evaluate_risk(task) == "low"


def test_high_risk_objective_overrides_low_risk_classification():
    config = {"profile": "agy-heavy"}
    high_risk_signals = [
        "Update authentication credentials and token validator",
        "Perform database schema migration",
        "Refactor public-contract for external service API",
        "Fix concurrency race condition in cache lock",
        "Update security authorization check",
    ]
    for signal in high_risk_signals:
        for low_label in ("ordinary-implementation", "mechanical", "ui", "test-only"):
            task = {
                "task_id": "TASK-HR-OVERRIDE",
                "objective": signal,
                "risk_class": low_label,
                "category": low_label,
                "scope": ["core.py"],
                "constraints": [],
                "acceptance_criteria": ["verified"],
                "verification_commands": [["python", "-m", "pytest"]],
            }
            assert supervisor.evaluate_risk(task) == "high"
            eff, req, reason = supervisor.resolve_profile(task, config)
            assert eff == "codex-controlled"
            assert req == "agy-heavy"
            assert "High-risk task forced" in (reason or "")


def test_conflicting_risk_aliases_cannot_downgrade_high_risk():
    task = {
        "objective": "Update helper",
        "risk_class": "ui",
        "category": "security",
    }

    assert supervisor.evaluate_risk(task) == "high"


def test_review_policy_codex_required_forces_codex_controlled():
    config = {"profile": "agy-heavy"}
    task = {
        "task_id": "TASK-REVIEW-POLICY",
        "objective": "Minor UI button update",
        "risk_class": "ui",
        "review_policy": "codex-required",
        "scope": ["ui.py"],
        "constraints": [],
        "acceptance_criteria": ["verified"],
        "verification_commands": [["python", "-m", "pytest"]],
    }
    eff, req, reason = supervisor.resolve_profile(task, config)
    assert eff == "codex-controlled"
    assert req == "agy-heavy"
    assert "codex-required" in (reason or "")


def test_review_policy_manual_final_does_not_bypass_high_risk():
    config = {"profile": "agy-heavy"}
    task = {
        "task_id": "TASK-REVIEW-POLICY-MANUAL-HIGH-RISK",
        "objective": "Update auth secrets handling",
        "risk_class": "security",
        "review_policy": "manual-final",
        "scope": ["auth.py"],
        "constraints": [],
        "acceptance_criteria": ["verified"],
        "verification_commands": [["python", "-m", "pytest"]],
    }
    eff, req, reason = supervisor.resolve_profile(task, config)
    assert eff == "codex-controlled"
    assert req == "agy-heavy"
    assert "High-risk" in (reason or "")


def test_per_task_agy_self_repair_attempts_passed_to_worker(monkeypatch, tmp_path):
    worker_tree = tmp_path / "worker"
    worker_tree.mkdir()
    subprocess.run(["git", "init"], cwd=worker_tree, check=True, capture_output=True)

    config = {
        "profile": "agy-heavy",
        "max_agy_repair_attempts": 2,
        "agy": {},
        "worktree_root": ".agents/worktrees",
    }
    monkeypatch.setattr(supervisor, "config", lambda _: config)
    monkeypatch.setattr(supervisor.worktrees, "create", lambda *args: worker_tree)

    captured_attempts = []

    def mock_invoke(task, tree, run_dir, agy_cfg, effort, max_repair_attempts=None):
        captured_attempts.append(max_repair_attempts)
        (tree / "code.py").write_text("# done\n", encoding="utf-8")
        return {
            "task_id": task["task_id"],
            "status": "completed",
            "summary": "done",
            "changed_files": ["code.py"],
            "tests": [],
            "commands_executed": [],
            "risks": [],
            "unresolved": [],
            "needs_review": True,
        }

    monkeypatch.setattr(supervisor.agy_cli, "invoke", mock_invoke)
    monkeypatch.setattr(
        supervisor.checks,
        "run_checks",
        lambda tree, cmd_list: [{"command": c, "exit_code": 0, "stdout": "ok", "stderr": ""} for c in cmd_list],
    )

    # 1. Per-task attempts = 4
    task_custom = supervisor.normalize_task(
        {
            "task_id": "TASK-ATTEMPTS-4",
            "objective": "Update code",
            "risk_class": "ordinary-implementation",
            "agy_self_repair_attempts": 4,
            "scope": ["code.py"],
            "constraints": [],
            "acceptance_criteria": ["done"],
            "verification_commands": [["python", "-m", "pytest"]],
        }
    )
    assert supervisor.run(tmp_path, task_custom, dry_run=False) == 0
    assert captured_attempts[-1] == 4

    # 2. Absent per-task attempts with default cfg=3
    monkeypatch.setattr(supervisor, "config", lambda _: {
        "profile": "agy-heavy",
        "agy": {},
        "worktree_root": ".agents/worktrees",
    })
    task_default = supervisor.normalize_task(
        {
            "task_id": "TASK-ATTEMPTS-DEFAULT",
            "objective": "Update code default",
            "risk_class": "ordinary-implementation",
            "scope": ["code.py"],
            "constraints": [],
            "acceptance_criteria": ["done"],
            "verification_commands": [["python", "-m", "pytest"]],
        }
    )
    assert supervisor.run(tmp_path, task_default, dry_run=False) == 0
    assert captured_attempts[-1] == 3


def test_agy_heavy_failed_worker_stops_with_takeover_and_no_worker_completed_ok(monkeypatch, tmp_path):
    worker_tree = tmp_path / "worker"
    worker_tree.mkdir()
    subprocess.run(["git", "init"], cwd=worker_tree, check=True, capture_output=True)

    config = {
        "profile": "agy-heavy",
        "max_agy_repair_attempts": 2,
        "agy": {},
        "worktree_root": ".agents/worktrees",
    }
    monkeypatch.setattr(supervisor, "config", lambda _: config)
    monkeypatch.setattr(supervisor.worktrees, "create", lambda *args: worker_tree)

    def mock_invoke(task, tree, run_dir, agy_cfg, effort, max_repair_attempts=None):
        return {
            "task_id": task["task_id"],
            "status": "failed",
            "summary": "AGY execution failed with syntax errors",
            "changed_files": [],
            "tests": [],
            "commands_executed": [],
            "risks": [],
            "unresolved": ["syntax error in file"],
            "needs_review": True,
        }

    monkeypatch.setattr(supervisor.agy_cli, "invoke", mock_invoke)
    monkeypatch.setattr(
        supervisor.checks,
        "run_checks",
        lambda tree, cmd_list: [{"command": c, "exit_code": 0, "stdout": "ok", "stderr": ""} for c in cmd_list],
    )

    task = supervisor.normalize_task(
        {
            "task_id": "TASK-FAIL-WORKER",
            "objective": "Mechanical fix",
            "category": "mechanical",
            "scope": ["utils.py"],
            "constraints": [],
            "acceptance_criteria": ["fixed"],
            "verification_commands": [["python", "-m", "pytest", "tests/test_utils.py"]],
        }
    )

    assert supervisor.run(tmp_path, task, dry_run=False) == 0

    run_dir = tmp_path / ".agents/runs/TASK-FAIL-WORKER"
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "codex-takeover-required"
    assert "Worker finished with status 'failed'" in state["takeover_reason"]

    assert (run_dir / "worker-round-1.json").exists()
    assert (run_dir / "checks-round-1.json").exists()
    assert (run_dir / "change-evidence-round-1.json").exists()
    assert (run_dir / "git-diff-round-1.patch").exists()

    events_content = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in events_content.strip().splitlines()]
    for ev in events:
        assert not (ev.get("action") == "worker-completed" and ev.get("status") == "ok")
    assert any(ev.get("action") == "worker-round-1-failed" and ev.get("status") == "failed" for ev in events)


def test_agy_heavy_failed_verification_command_stops_with_takeover_and_no_worker_completed_ok(monkeypatch, tmp_path):
    worker_tree = tmp_path / "worker"
    worker_tree.mkdir()
    subprocess.run(["git", "init"], cwd=worker_tree, check=True, capture_output=True)

    config = {
        "profile": "agy-heavy",
        "max_agy_repair_attempts": 2,
        "agy": {},
        "worktree_root": ".agents/worktrees",
    }
    monkeypatch.setattr(supervisor, "config", lambda _: config)
    monkeypatch.setattr(supervisor.worktrees, "create", lambda *args: worker_tree)

    def mock_invoke(task, tree, run_dir, agy_cfg, effort, max_repair_attempts=None):
        return {
            "task_id": task["task_id"],
            "status": "completed",
            "summary": "Completed change",
            "changed_files": ["utils.py"],
            "tests": [],
            "commands_executed": [],
            "risks": [],
            "unresolved": [],
            "needs_review": True,
        }

    monkeypatch.setattr(supervisor.agy_cli, "invoke", mock_invoke)
    monkeypatch.setattr(
        supervisor.checks,
        "run_checks",
        lambda tree, cmd_list: [{"command": c, "exit_code": 1, "stdout": "", "stderr": "test failed"} for c in cmd_list],
    )

    task = supervisor.normalize_task(
        {
            "task_id": "TASK-FAIL-CHECKS",
            "objective": "Mechanical fix",
            "category": "mechanical",
            "scope": ["utils.py"],
            "constraints": [],
            "acceptance_criteria": ["fixed"],
            "verification_commands": [["python", "-m", "pytest", "tests/test_utils.py"]],
        }
    )

    assert supervisor.run(tmp_path, task, dry_run=False) == 0

    run_dir = tmp_path / ".agents/runs/TASK-FAIL-CHECKS"
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "codex-takeover-required"
    assert "Verification checks failed" in state["takeover_reason"]

    assert (run_dir / "worker-round-1.json").exists()
    assert (run_dir / "checks-round-1.json").exists()
    assert (run_dir / "change-evidence-round-1.json").exists()
    assert (run_dir / "git-diff-round-1.patch").exists()

    events_content = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in events_content.strip().splitlines()]
    for ev in events:
        assert not (ev.get("action") == "worker-completed" and ev.get("status") == "ok")
    assert any(ev.get("action") == "checks-round-1-failed" and ev.get("status") == "failed" for ev in events)


def test_collect_change_evidence_includes_committed_changes_relative_to_base(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "file.txt").write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True)
    base_commit = supervisor._git(tmp_path, "rev-parse", "HEAD").stdout.strip()

    (tmp_path / "file.txt").write_text("updated\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "worker commit"], cwd=tmp_path, check=True, capture_output=True)

    evidence = supervisor.collect_change_evidence(tmp_path, ["file.txt"], base_commit=base_commit)

    assert "file.txt" in evidence["changed_paths"]
    assert "-initial" in evidence["tracked_diff"]
    assert "+updated" in evidence["tracked_diff"]
    assert "-initial" in evidence["patch"]
    assert "+updated" in evidence["patch"]


def test_collect_change_evidence_includes_untracked_files_in_patch(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "init.txt").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "init.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True)
    base_commit = supervisor._git(tmp_path, "rev-parse", "HEAD").stdout.strip()

    (tmp_path / "scoped_new.txt").write_text("new content\n", encoding="utf-8")
    (tmp_path / "outside_new.txt").write_text("outside content\n", encoding="utf-8")

    evidence = supervisor.collect_change_evidence(tmp_path, ["scoped_new.txt"], base_commit=base_commit)

    assert bool(evidence["patch"].strip())
    assert "diff --git a/scoped_new.txt b/scoped_new.txt" in evidence["patch"]
    assert "+new content" in evidence["patch"]
    assert "outside_new.txt" not in evidence["patch"]


def test_collect_change_evidence_includes_binary_untracked_file_in_patch(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "init.txt").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "init.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True)
    base_commit = supervisor._git(tmp_path, "rev-parse", "HEAD").stdout.strip()

    (tmp_path / "data.bin").write_bytes(b"bin\x00data\xff")

    evidence = supervisor.collect_change_evidence(tmp_path, ["data.bin"], base_commit=base_commit)

    assert "diff --git a/data.bin b/data.bin" in evidence["patch"]
    assert "GIT binary patch" in evidence["patch"]


def test_agy_heavy_preserves_committed_worker_changes_in_run_artifacts(monkeypatch, tmp_path):
    worker_tree = tmp_path / "worker"
    worker_tree.mkdir()
    subprocess.run(["git", "init"], cwd=worker_tree, check=True, capture_output=True)
    (worker_tree / "component.py").write_text("# v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "component.py"], cwd=worker_tree, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=worker_tree, check=True, capture_output=True)
    base_sha = supervisor._git(worker_tree, "rev-parse", "HEAD").stdout.strip()

    config = {
        "profile": "agy-heavy",
        "max_agy_repair_attempts": 2,
        "agy": {},
        "worktree_root": ".agents/worktrees",
    }
    monkeypatch.setattr(supervisor, "config", lambda _: config)
    monkeypatch.setattr(supervisor.worktrees, "create", lambda *args: worker_tree)

    def mock_invoke(task, tree, run_dir, agy_cfg, effort, max_repair_attempts=None):
        (tree / "component.py").write_text("# v2\n", encoding="utf-8")
        subprocess.run(["git", "add", "component.py"], cwd=tree, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "worker commit"], cwd=tree, check=True, capture_output=True)
        return {
            "task_id": task["task_id"],
            "status": "completed",
            "summary": "Committed component update",
            "changed_files": ["component.py"],
            "tests": [{"command": ["python", "-m", "pytest"], "exit_code": 0}],
            "commands_executed": ["python -m pytest"],
            "risks": [],
            "unresolved": [],
            "needs_review": True,
        }

    monkeypatch.setattr(supervisor.agy_cli, "invoke", mock_invoke)
    monkeypatch.setattr(
        supervisor.checks,
        "run_checks",
        lambda tree, cmd_list: [{"command": c, "exit_code": 0, "stdout": "ok", "stderr": ""} for c in cmd_list],
    )

    task = supervisor.normalize_task(
        {
            "task_id": "TASK-COMMITTED-EVIDENCE",
            "objective": "Update component",
            "category": "ordinary-implementation",
            "scope": ["component.py"],
            "constraints": [],
            "acceptance_criteria": ["passes"],
            "verification_commands": [["python", "-m", "pytest"]],
        }
    )

    assert supervisor.run(tmp_path, task, dry_run=False) == 0

    run_dir = tmp_path / ".agents/runs/TASK-COMMITTED-EVIDENCE"
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "worker-complete-awaiting-manual-review"
    assert state["base_commit"] == base_sha

    patch_content = (run_dir / "git-diff-round-1.patch").read_text(encoding="utf-8")
    assert "-# v1" in patch_content
    assert "+# v2" in patch_content

    evidence = json.loads((run_dir / "change-evidence-round-1.json").read_text(encoding="utf-8"))
    assert "component.py" in evidence["changed_paths"]


def test_agy_heavy_out_of_scope_committed_change_rejects_and_requires_takeover(monkeypatch, tmp_path):
    worker_tree = tmp_path / "worker"
    worker_tree.mkdir()
    subprocess.run(["git", "init"], cwd=worker_tree, check=True, capture_output=True)
    (worker_tree / "component.py").write_text("# v1\n", encoding="utf-8")
    (worker_tree / "secret.py").write_text("# secret v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=worker_tree, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=worker_tree, check=True, capture_output=True)

    config = {
        "profile": "agy-heavy",
        "max_agy_repair_attempts": 2,
        "agy": {},
        "worktree_root": ".agents/worktrees",
    }
    monkeypatch.setattr(supervisor, "config", lambda _: config)
    monkeypatch.setattr(supervisor.worktrees, "create", lambda *args: worker_tree)

    def mock_invoke(task, tree, run_dir, agy_cfg, effort, max_repair_attempts=None):
        (tree / "component.py").write_text("# v2\n", encoding="utf-8")
        (tree / "secret.py").write_text("# secret v2\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=tree, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "worker out-of-scope commit"], cwd=tree, check=True, capture_output=True)
        return {
            "task_id": task["task_id"],
            "status": "completed",
            "summary": "Modified both files",
            "changed_files": ["component.py", "secret.py"],
            "tests": [],
            "commands_executed": [],
            "risks": [],
            "unresolved": [],
            "needs_review": True,
        }

    monkeypatch.setattr(supervisor.agy_cli, "invoke", mock_invoke)
    monkeypatch.setattr(
        supervisor.checks,
        "run_checks",
        lambda tree, cmd_list: [{"command": c, "exit_code": 0, "stdout": "ok", "stderr": ""} for c in cmd_list],
    )

    task = supervisor.normalize_task(
        {
            "task_id": "TASK-OOS-COMMITTED",
            "objective": "Update component only",
            "category": "ordinary-implementation",
            "scope": ["component.py"],
            "constraints": [],
            "acceptance_criteria": ["passes"],
            "verification_commands": [["python", "-m", "pytest"]],
        }
    )

    assert supervisor.run(tmp_path, task, dry_run=False) == 0

    run_dir = tmp_path / ".agents/runs/TASK-OOS-COMMITTED"
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "codex-takeover-required"
    assert "Changes outside declared task scope detected" in state["takeover_reason"]
    assert "secret.py" in state["out_of_scope_changes"]

    assert (run_dir / "worker-round-1.json").exists()
    assert (run_dir / "checks-round-1.json").exists()
    assert (run_dir / "change-evidence-round-1.json").exists()
    assert (run_dir / "git-diff-round-1.patch").exists()

    events_content = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in events_content.strip().splitlines()]
    assert any(ev.get("action") == "scope-validation-failed" and ev.get("status") == "failed" for ev in events)


def test_agy_heavy_out_of_scope_untracked_change_rejects_and_requires_takeover(monkeypatch, tmp_path):
    worker_tree = tmp_path / "worker"
    worker_tree.mkdir()
    subprocess.run(["git", "init"], cwd=worker_tree, check=True, capture_output=True)
    (worker_tree / "component.py").write_text("# v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=worker_tree, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=worker_tree, check=True, capture_output=True)

    config = {
        "profile": "agy-heavy",
        "max_agy_repair_attempts": 2,
        "agy": {},
        "worktree_root": ".agents/worktrees",
    }
    monkeypatch.setattr(supervisor, "config", lambda _: config)
    monkeypatch.setattr(supervisor.worktrees, "create", lambda *args: worker_tree)

    def mock_invoke(task, tree, run_dir, agy_cfg, effort, max_repair_attempts=None):
        (tree / "component.py").write_text("# v2\n", encoding="utf-8")
        (tree / "extra_untracked.py").write_text("# extra\n", encoding="utf-8")
        return {
            "task_id": task["task_id"],
            "status": "completed",
            "summary": "Updated component and left extra file",
            "changed_files": ["component.py"],
            "tests": [],
            "commands_executed": [],
            "risks": [],
            "unresolved": [],
            "needs_review": True,
        }

    monkeypatch.setattr(supervisor.agy_cli, "invoke", mock_invoke)
    monkeypatch.setattr(
        supervisor.checks,
        "run_checks",
        lambda tree, cmd_list: [{"command": c, "exit_code": 0, "stdout": "ok", "stderr": ""} for c in cmd_list],
    )

    task = supervisor.normalize_task(
        {
            "task_id": "TASK-OOS-UNTRACKED",
            "objective": "Update component only",
            "category": "ordinary-implementation",
            "scope": ["component.py"],
            "constraints": [],
            "acceptance_criteria": ["passes"],
            "verification_commands": [["python", "-m", "pytest"]],
        }
    )

    assert supervisor.run(tmp_path, task, dry_run=False) == 0

    run_dir = tmp_path / ".agents/runs/TASK-OOS-UNTRACKED"
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "codex-takeover-required"
    assert "Changes outside declared task scope detected" in state["takeover_reason"]
    assert "extra_untracked.py" in state["out_of_scope_changes"]

    assert (run_dir / "worker-round-1.json").exists()
    assert (run_dir / "checks-round-1.json").exists()
    assert (run_dir / "change-evidence-round-1.json").exists()
    assert (run_dir / "git-diff-round-1.patch").exists()


def test_checked_in_config_resolves_all_delegable_categories_and_default_to_flash_high():
    repo_root = Path(__file__).resolve().parents[1]
    cfg = supervisor.config(repo_root)

    # 1. Fallback / default when no category is specified
    empty_task = {"objective": "Some mechanical update"}
    assert supervisor.resolve_model(empty_task, cfg) == "gemini-3.7-flash-high"

    # 2. All delegable categories resolve to gemini-3.7-flash-high
    delegable_categories = ["mechanical", "test-only", "ui", "ordinary-implementation"]
    for cat in delegable_categories:
        # via category field
        assert supervisor.resolve_model({"objective": "Update", "category": cat}, cfg) == "gemini-3.7-flash-high"
        # via risk_class field
        assert supervisor.resolve_model({"objective": "Update", "risk_class": cat}, cfg) == "gemini-3.7-flash-high"

    # 3. Underscore aliases normalize and resolve to gemini-3.7-flash-high
    underscore_aliases = ["test_only", "ordinary_implementation", "implementation"]
    for alias in underscore_aliases:
        assert supervisor.resolve_model({"objective": "Update", "category": alias}, cfg) == "gemini-3.7-flash-high"
        assert supervisor.resolve_model({"objective": "Update", "risk_class": alias}, cfg) == "gemini-3.7-flash-high"

    # 4. Unknown low-risk category resolves to configured policy default
    unknown_task = {"objective": "Update unknown", "category": "custom-category"}
    assert supervisor.resolve_model(unknown_task, cfg) == "gemini-3.7-flash-high"


def test_single_configured_category_changed_to_low_resolves_only_that_category_to_low():
    repo_root = Path(__file__).resolve().parents[1]
    base_cfg = supervisor.config(repo_root)

    # Change only "test-only" to gemini-3.7-flash-low
    cfg_test_low = json.loads(json.dumps(base_cfg))
    cfg_test_low["agy"]["model_policy"]["categories"]["test-only"] = "gemini-3.7-flash-low"

    # test-only (and alias test_only) resolves to gemini-3.7-flash-low
    assert supervisor.resolve_model({"objective": "Test", "category": "test-only"}, cfg_test_low) == "gemini-3.7-flash-low"
    assert supervisor.resolve_model({"objective": "Test", "category": "test_only"}, cfg_test_low) == "gemini-3.7-flash-low"
    assert supervisor.resolve_model({"objective": "Test", "risk_class": "test-only"}, cfg_test_low) == "gemini-3.7-flash-low"

    # All other categories and default remain gemini-3.7-flash-high
    assert supervisor.resolve_model({"objective": "UI", "category": "ui"}, cfg_test_low) == "gemini-3.7-flash-high"
    assert supervisor.resolve_model({"objective": "Mechanical", "category": "mechanical"}, cfg_test_low) == "gemini-3.7-flash-high"
    assert supervisor.resolve_model({"objective": "Impl", "category": "ordinary-implementation"}, cfg_test_low) == "gemini-3.7-flash-high"
    assert supervisor.resolve_model({"objective": "Default"}, cfg_test_low) == "gemini-3.7-flash-high"
    assert supervisor.resolve_model({"objective": "Unknown", "category": "unknown"}, cfg_test_low) == "gemini-3.7-flash-high"

    # Change only "ui" to gemini-3.7-flash-low
    cfg_ui_low = json.loads(json.dumps(base_cfg))
    cfg_ui_low["agy"]["model_policy"]["categories"]["ui"] = "gemini-3.7-flash-low"
    assert supervisor.resolve_model({"objective": "UI", "category": "ui"}, cfg_ui_low) == "gemini-3.7-flash-low"
    assert supervisor.resolve_model({"objective": "Test", "category": "test-only"}, cfg_ui_low) == "gemini-3.7-flash-high"
    assert supervisor.resolve_model({"objective": "Mechanical", "category": "mechanical"}, cfg_ui_low) == "gemini-3.7-flash-high"


def test_missing_or_invalid_model_policy_falls_back_safely():
    # 1. No model_policy in config: fallback to agy.model
    cfg_no_policy = {"agy": {"model": "gemini-3.7-flash-high"}}
    assert supervisor.resolve_model({"objective": "Test", "category": "ui"}, cfg_no_policy) == "gemini-3.7-flash-high"

    # 2. Non-dict model_policy: fallback to agy.model
    cfg_bad_policy = {"agy": {"model": "gemini-3.7-flash-high", "model_policy": "invalid"}}
    assert supervisor.resolve_model({"objective": "Test", "category": "ui"}, cfg_bad_policy) == "gemini-3.7-flash-high"

    # 3. Invalid category value (empty or non-string): falls back to default
    cfg_invalid_val = {
        "agy": {
            "model": "gemini-3.7-flash-high",
            "model_policy": {
                "default": "gemini-3.7-flash-high",
                "categories": {
                    "ui": "",
                    "mechanical": None,
                },
            },
        }
    }
    assert supervisor.resolve_model({"objective": "Test", "category": "ui"}, cfg_invalid_val) == "gemini-3.7-flash-high"
    assert supervisor.resolve_model({"objective": "Test", "category": "mechanical"}, cfg_invalid_val) == "gemini-3.7-flash-high"

    # 4. Flat model_policy dictionary support
    cfg_flat = {
        "agy": {
            "model": "gemini-3.7-flash-high",
            "model_policy": {
                "default": "gemini-3.7-flash-high",
                "ui": "gemini-3.7-flash-low",
                "test-only": "gemini-3.7-flash-high",
            },
        }
    }
    assert supervisor.resolve_model({"objective": "Test", "category": "ui"}, cfg_flat) == "gemini-3.7-flash-low"
    assert supervisor.resolve_model({"objective": "Test", "category": "test-only"}, cfg_flat) == "gemini-3.7-flash-high"


def test_dry_run_records_resolved_model_in_state_and_worker_command(monkeypatch, tmp_path):
    config = {
        "profile": "agy-heavy",
        "agy": {
            "model": "gemini-3.7-flash-high",
            "model_policy": {
                "default": "gemini-3.7-flash-high",
                "categories": {
                    "ui": "gemini-3.7-flash-low",
                    "mechanical": "gemini-3.7-flash-high",
                },
            },
        },
    }
    monkeypatch.setattr(supervisor, "config", lambda _: config)

    task = supervisor.normalize_task(
        {
            "task_id": "TASK-DRY-RUN-MODEL",
            "objective": "Test dry run model resolution",
            "category": "ui",
            "scope": ["component.py"],
            "constraints": [],
            "acceptance_criteria": ["pass"],
            "verification_commands": [["python", "-m", "pytest"]],
        }
    )

    assert supervisor.run(tmp_path, task, dry_run=True) == 0
    state = json.loads((tmp_path / ".agents/runs/TASK-DRY-RUN-MODEL/state.json").read_text(encoding="utf-8"))
    assert state["status"] == "dry-run-complete"
    assert state["model"] == "gemini-3.7-flash-low"

    worker_command = state["expected_commands"]["worker"]
    assert "--model" in worker_command
    assert worker_command[worker_command.index("--model") + 1] == "gemini-3.7-flash-low"


def test_real_run_records_resolved_model_and_passes_to_agy_invoke(monkeypatch, tmp_path):
    worker_tree = tmp_path / "worker"
    worker_tree.mkdir()
    subprocess.run(["git", "init"], cwd=worker_tree, check=True, capture_output=True)

    config = {
        "profile": "agy-heavy",
        "max_agy_repair_attempts": 2,
        "agy": {
            "model": "gemini-3.7-flash-high",
            "model_policy": {
                "default": "gemini-3.7-flash-high",
                "categories": {
                    "test-only": "gemini-3.7-flash-low",
                    "ui": "gemini-3.7-flash-high",
                },
            },
        },
        "worktree_root": ".agents/worktrees",
    }
    monkeypatch.setattr(supervisor, "config", lambda _: config)
    monkeypatch.setattr(supervisor.worktrees, "create", lambda *args: worker_tree)

    captured_settings = []

    def mock_invoke(task, tree, run_dir, agy_cfg, effort, max_repair_attempts=None):
        captured_settings.append(dict(agy_cfg))
        (tree / "test_comp.py").write_text("# test\n", encoding="utf-8")
        return {
            "task_id": task["task_id"],
            "status": "completed",
            "summary": "Done tests",
            "changed_files": ["test_comp.py"],
            "tests": [],
            "commands_executed": [],
            "risks": [],
            "unresolved": [],
            "needs_review": True,
        }

    monkeypatch.setattr(supervisor.agy_cli, "invoke", mock_invoke)
    monkeypatch.setattr(
        supervisor.checks,
        "run_checks",
        lambda tree, cmd_list: [{"command": c, "exit_code": 0, "stdout": "ok", "stderr": ""} for c in cmd_list],
    )

    task = supervisor.normalize_task(
        {
            "task_id": "TASK-REAL-RUN-MODEL",
            "objective": "Add tests",
            "category": "test-only",
            "scope": ["test_comp.py"],
            "constraints": [],
            "acceptance_criteria": ["pass"],
            "verification_commands": [["python", "-m", "pytest"]],
        }
    )

    assert supervisor.run(tmp_path, task, dry_run=False) == 0

    run_dir = tmp_path / ".agents/runs/TASK-REAL-RUN-MODEL"
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["model"] == "gemini-3.7-flash-low"
    assert len(captured_settings) == 1
    assert captured_settings[0]["model"] == "gemini-3.7-flash-low"


def test_high_risk_tasks_force_codex_controlled_regardless_of_model_policy(monkeypatch, tmp_path):
    config = {
        "profile": "agy-heavy",
        "agy": {
            "model": "gemini-3.7-flash-high",
            "model_policy": {
                "default": "gemini-3.7-flash-high",
                "categories": {
                    "security": "gemini-3.7-flash-high",
                    "ui": "gemini-3.7-flash-low",
                },
            },
        },
    }

    high_risk_task = supervisor.normalize_task(
        {
            "task_id": "TASK-HR-MODEL",
            "objective": "Update security authentication policy",
            "risk_class": "security",
            "category": "security",
            "scope": ["auth.py"],
            "constraints": [],
            "acceptance_criteria": ["pass"],
            "verification_commands": [["python", "-m", "pytest"]],
        }
    )

    eff, req, reason = supervisor.resolve_profile(high_risk_task, config)
    assert eff == "codex-controlled"
    assert req == "agy-heavy"
    assert "High-risk task forced" in (reason or "")


def test_doctor_reports_default_model_policy(monkeypatch, tmp_path, capsys):
    config = {
        "profile": "agy-heavy",
        "agy": {
            "executable": "agy",
            "model": "gemini-3.7-flash-high",
            "allowed_models": [
                "gemini-3.7-flash-high",
                "gemini-3.7-flash-low",
            ],
            "model_policy": {
                "default": "gemini-3.7-flash-high",
                "categories": {
                    "mechanical": "gemini-3.7-flash-high",
                    "test-only": "gemini-3.7-flash-high",
                    "ui": "gemini-3.7-flash-high",
                    "ordinary-implementation": "gemini-3.7-flash-high",
                },
            },
        },
    }
    monkeypatch.setattr(supervisor, "config", lambda _: config)
    monkeypatch.setattr(supervisor.agy_cli, "executable", lambda _: "agy")
    monkeypatch.setattr(
        supervisor,
        "_command_line",
        lambda cmd, root: "1.0.0" if "--version" in cmd else "gemini-3.7-flash-high\ngemini-3.7-flash-low",
    )

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    exit_code = supervisor.doctor(tmp_path)
    assert exit_code == 0

    captured = capsys.readouterr().out
    assert "AGY configured model" in captured
    assert "AGY default model policy" in captured
    assert "AGY allowed models" in captured
    assert "AGY policy models available" in captured
    assert "gemini-3.7-flash-high" in captured


def test_arbitrary_models_in_policy_cannot_be_selected_and_fallback_to_agy_model():
    cfg = {
        "agy": {
            "model": "gemini-3.7-flash-high",
            "allowed_models": [
                "gemini-3.7-flash-high",
                "gemini-3.7-flash-low",
            ],
            "model_policy": {
                "default": "arbitrary-default-model",
                "categories": {
                    "ui": "arbitrary-ui-model",
                    "mechanical": "gemini-3.7-flash-low",
                    "test-only": "gpt-4o",
                    "ordinary-implementation": None,
                },
                "custom-flat": "arbitrary-flat-model",
            },
        },
    }

    # 1. Arbitrary category values fall back to configured agy.model (gemini-3.7-flash-high)
    assert supervisor.resolve_model({"objective": "UI", "category": "ui"}, cfg) == "gemini-3.7-flash-high"
    assert supervisor.resolve_model({"objective": "Test", "category": "test-only"}, cfg) == "gemini-3.7-flash-high"
    assert supervisor.resolve_model({"objective": "Impl", "category": "ordinary-implementation"}, cfg) == "gemini-3.7-flash-high"
    assert supervisor.resolve_model({"objective": "Flat", "category": "custom-flat"}, cfg) == "gemini-3.7-flash-high"

    # 2. Valid model in allowed_models is successfully selected
    assert supervisor.resolve_model({"objective": "Mechanical", "category": "mechanical"}, cfg) == "gemini-3.7-flash-low"

    # 3. Arbitrary default falls back to configured agy.model for unknown/unspecified categories
    assert supervisor.resolve_model({"objective": "Unknown", "category": "unknown"}, cfg) == "gemini-3.7-flash-high"
    assert supervisor.resolve_model({"objective": "None"}, cfg) == "gemini-3.7-flash-high"


def test_allowed_models_permits_low_and_high_and_handles_invalid_default_with_low_default():
    cfg = {
        "agy": {
            "model": "gemini-3.7-flash-high",
            "allowed_models": [
                "gemini-3.7-flash-high",
                "gemini-3.7-flash-low",
            ],
            "model_policy": {
                "default": "gemini-3.7-flash-low",
                "categories": {
                    "ui": "invalid-model-name",
                    "mechanical": "gemini-3.7-flash-high",
                },
            },
        },
    }

    # Valid default is used for unknown categories
    assert supervisor.resolve_model({"objective": "Unknown", "category": "unknown"}, cfg) == "gemini-3.7-flash-low"

    # Invalid category value falls back to configured agy.model (gemini-3.7-flash-high)
    assert supervisor.resolve_model({"objective": "UI", "category": "ui"}, cfg) == "gemini-3.7-flash-high"

    # Valid mapped category is used
    assert supervisor.resolve_model({"objective": "Mech", "category": "mechanical"}, cfg) == "gemini-3.7-flash-high"


def test_doctor_reports_policy_model_availability_missing_and_unknown(monkeypatch, tmp_path, capsys):
    config = {
        "profile": "agy-heavy",
        "agy": {
            "executable": "agy",
            "model": "gemini-3.7-flash-high",
            "allowed_models": [
                "gemini-3.7-flash-high",
                "gemini-3.7-flash-low",
            ],
            "model_policy": {
                "default": "gemini-3.7-flash-high",
                "categories": {
                    "mechanical": "gemini-3.7-flash-high",
                    "test-only": "gemini-3.7-flash-low",
                },
            },
        },
    }
    monkeypatch.setattr(supervisor, "config", lambda _: config)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    # Scenario 1: Partial models output where gemini-3.7-flash-low is missing
    monkeypatch.setattr(supervisor.agy_cli, "executable", lambda _: "agy")
    monkeypatch.setattr(
        supervisor,
        "_command_line",
        lambda cmd, root: "1.0.0" if "--version" in cmd else "gemini-3.7-flash-high",
    )
    assert supervisor.doctor(tmp_path) == 0
    captured = capsys.readouterr().out
    assert "AGY policy models available" in captured
    assert "MISSING (gemini-3.7-flash-low)" in captured

    # Scenario 2: AGY models command returns empty string
    monkeypatch.setattr(supervisor, "_command_line", lambda cmd, root: "1.0.0" if "--version" in cmd else "")
    assert supervisor.doctor(tmp_path) == 0
    captured = capsys.readouterr().out
    assert "UNKNOWN" in captured

    # Scenario 3: AGY executable not found
    monkeypatch.setattr(supervisor.agy_cli, "executable", lambda _: "")
    assert supervisor.doctor(tmp_path) == 0
    captured = capsys.readouterr().out
    assert "MISSING" in captured
