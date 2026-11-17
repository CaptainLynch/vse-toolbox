import json

import pytest

from tools.agents.dispatch_wait_protocol import (
    DEFAULT_WAIT_POLICY,
    MAX_WRITE_CHANNELS_CEILING,
    classify_marker,
    decide_wait,
    find_forbidden_commands,
    normalize_wait_policy,
    read_markers,
    validate_dispatch_plan,
    wait_for_markers,
)


def test_default_wait_policy_values():
    policy = normalize_wait_policy(None)

    assert policy == DEFAULT_WAIT_POLICY
    assert policy["stall_seconds"] == 600
    assert policy["hard_limit_seconds"] == 1800
    assert policy["max_write_channels"] == 2


def test_wait_policy_rejects_stall_above_hard_limit_and_wide_parallelism():
    with pytest.raises(ValueError, match="lower than hard_limit"):
        normalize_wait_policy({"stall_seconds": 1800, "hard_limit_seconds": 1800})

    with pytest.raises(ValueError, match="max_write_channels"):
        normalize_wait_policy({"max_write_channels": MAX_WRITE_CHANNELS_CEILING + 1})

    with pytest.raises(ValueError, match="positive integer"):
        normalize_wait_policy({"stall_seconds": 0})


def test_disjoint_write_channels_pass():
    report = validate_dispatch_plan(
        [
            {"id": "t1", "role": "implement", "write_paths": ["core/a.py", "core/a_test.py"]},
            {"id": "t2", "role": "review", "write_paths": []},
        ]
    )

    assert report["ok"] is True
    assert report["write_channels"] == 1
    assert report["read_only_units"] == 1
    assert report["conflicts"] == []


def test_overlapping_write_paths_are_a_conflict():
    report = validate_dispatch_plan(
        [
            {"id": "t1", "role": "implement", "write_paths": ["core/a.py"]},
            {"id": "t2", "role": "implement", "write_paths": ["./CORE/a.py"]},
        ]
    )

    assert report["ok"] is False
    assert report["conflicts"] == [{"path": "core/a.py", "units": ["t1", "t2"]}]


def test_write_role_needs_paths_and_read_only_role_must_not_write():
    report = validate_dispatch_plan(
        [
            {"id": "t1", "role": "implement", "write_paths": []},
            {"id": "t2", "role": "review", "write_paths": ["core/a.py"]},
        ]
    )

    assert report["ok"] is False
    assert any("requires at least one write path" in e for e in report["errors"])
    assert any("must not declare write paths" in e for e in report["errors"])


def test_write_channel_cap_blocks_three_implementers_by_default():
    units = [
        {"id": f"t{i}", "role": "implement", "write_paths": [f"core/m{i}.py"]} for i in range(3)
    ]

    default_report = validate_dispatch_plan(units)
    raised_report = validate_dispatch_plan(units, policy={"max_write_channels": 3})

    assert default_report["ok"] is False
    assert any("exceed the cap of 2" in e for e in default_report["errors"])
    assert raised_report["ok"] is True


def test_duplicate_ids_and_unknown_roles_are_rejected():
    report = validate_dispatch_plan(
        [
            {"id": "t1", "role": "implement", "write_paths": ["core/a.py"]},
            {"id": "t1", "role": "implement", "write_paths": ["core/b.py"]},
            {"id": "t2", "role": "deploy", "write_paths": []},
        ]
    )

    assert report["ok"] is False
    assert any("duplicate unit id" in e for e in report["errors"])
    assert any("unknown role" in e for e in report["errors"])


def test_repository_wide_side_effects_are_flagged():
    findings = find_forbidden_commands(
        [
            "git add -A && git commit -m wip",
            "python -m pip install -r requirements.txt",
            "pytest tests -q",
            "pytest tests/test_core.py -q",
            "black tools/x.py",
            "git status --porcelain",
        ]
    )
    rules = {f["rule"] for f in findings}

    assert {"git-add", "git-commit", "dependency-install", "full-suite-gate", "repo-wide-format"} <= rules
    assert all(f["command"] != "git status --porcelain" for f in findings)
    assert all("test_core.py" not in f["command"] for f in findings)


def test_scoped_pytest_runs_are_not_treated_as_the_full_suite_gate():
    findings = find_forbidden_commands(
        [
            "python -m pytest .runtime/protocol-e2e/a -q",
            "python -m pytest tests/unit/test_core.py::test_one -q",
            "cd core; python -m pytest . -q",
        ]
    )

    assert [f["rule"] for f in findings] == ["full-suite-gate"]
    assert findings[0]["command"] == "cd core; python -m pytest . -q"


def test_bare_pytest_and_tests_root_are_the_full_suite_gate():
    findings = find_forbidden_commands(["pytest", "python -m pytest tests -q", "pytest -x tests"])

    assert [f["rule"] for f in findings] == ["full-suite-gate"] * 3


def test_classify_marker_requires_finished_at_for_terminal_status():
    ok = classify_marker(
        {"task_id": "t1", "role": "implement", "status": "done", "changed_files": ["core/a.py"], "finished_at": 1}
    )
    bad = classify_marker({"task_id": "t1", "role": "implement", "status": "done"})

    assert ok["terminal"] is True
    assert ok["errors"] == []
    assert bad["terminal"] is True
    assert any("finished_at" in e for e in bad["errors"])
    assert any("changed_files" in e for e in bad["errors"])


def test_decide_wait_returns_as_soon_as_any_unit_is_terminal():
    decision = decide_wait(
        [
            {"task_id": "t1", "role": "implement", "status": "running", "progress_at": 1_000},
            {"task_id": "t2", "role": "review", "status": "done", "finished_at": 1_050},
        ],
        now_epoch=1_060,
        start_epoch=1_000,
    )

    assert decision["action"] == "return"
    assert [t["task_id"] for t in decision["terminal"]] == ["t2"]
    assert decision["elapsed_seconds"] == 60.0


def test_decide_wait_reports_stall_before_the_hard_limit():
    decision = decide_wait(
        [{"task_id": "t1", "role": "implement", "status": "running", "progress_at": 1_000}],
        now_epoch=1_700,
        start_epoch=1_000,
    )

    assert decision["action"] == "stall"
    assert decision["idle_seconds"] == 700.0


def test_decide_wait_hits_hard_limit_and_handles_no_marks():
    timed_out = decide_wait(
        [{"task_id": "t1", "role": "implement", "status": "running", "progress_at": 1_900}],
        now_epoch=2_900,
        start_epoch=1_000,
    )
    empty = decide_wait([], now_epoch=2_900, start_epoch=1_000)

    assert timed_out["action"] == "timeout"
    assert empty["action"] == "no-marks"


def test_wait_for_markers_stops_on_terminal_marker(tmp_path):
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    (status_dir / "t1.implement.json").write_text(
        json.dumps(
            {
                "task_id": "t1",
                "role": "implement",
                "status": "done",
                "changed_files": ["core/a.py"],
                "started_at": 0,
                "finished_at": 10,
            }
        ),
        encoding="utf-8",
    )

    ticks = iter([100, 105, 110, 115])
    decision = wait_for_markers(
        status_dir,
        policy={"poll_interval_seconds": 5},
        sleep=lambda _seconds: None,
        clock=lambda: next(ticks),
    )

    assert decision["action"] == "return"
    assert read_markers(status_dir)[0]["task_id"] == "t1"


def test_read_markers_accepts_bom_prefixed_files(tmp_path):
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    (status_dir / "t1.implement.json").write_text(
        json.dumps({"status": "done", "changed_files": [], "finished_at": 9}),
        encoding="utf-8-sig",
    )

    markers = read_markers(status_dir)

    assert [m["status"] for m in markers] == ["done"]


def test_wait_for_markers_returns_no_marks_after_the_grace_window(tmp_path):
    status_dir = tmp_path / "status"
    status_dir.mkdir()

    ticks = iter([1_000, 1_030, 1_090])
    decision = wait_for_markers(
        status_dir,
        policy={"poll_interval_seconds": 5, "no_marks_grace_seconds": 60},
        sleep=lambda _seconds: None,
        clock=lambda: next(ticks),
    )

    assert decision["action"] == "no-marks"


def test_wait_for_markers_tolerates_markers_arriving_after_dispatch(tmp_path):
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    ticks = iter([1_000, 1_010, 1_020, 1_030])
    sleeps: list[int] = []

    def fake_sleep(seconds: int) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 1:
            (status_dir / "t1.implement.json").write_text(
                json.dumps({"status": "done", "changed_files": [], "finished_at": 1_025}),
                encoding="utf-8",
            )

    decision = wait_for_markers(
        status_dir,
        policy={"poll_interval_seconds": 5, "no_marks_grace_seconds": 60},
        sleep=fake_sleep,
        clock=lambda: next(ticks),
    )

    assert decision["action"] == "return"
    assert sleeps == [5]


def test_read_markers_ignores_broken_files(tmp_path):
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    (status_dir / "broken.json").write_text("{not json", encoding="utf-8")
    (status_dir / "t1.review.json").write_text(
        json.dumps({"status": "running", "started_at": 5}), encoding="utf-8"
    )

    markers = read_markers(status_dir)

    assert len(markers) == 1
    assert markers[0]["task_id"] == "t1"
    assert markers[0]["role"] == "review"
