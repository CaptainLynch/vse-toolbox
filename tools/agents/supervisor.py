"""Durable, bounded Codex lead / local AGY CLI worker supervisor."""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checks = load_module("project_checks", "project_checks.py")
worktrees = load_module("git_worktree", "git_worktree.py")
agy_cli = load_module("agy_cli", "agy_cli.py")

DEFAULT_FORBIDDEN = [
    "git push --force", "git reset --hard", "git clean -fd", "git checkout .", "git restore .", "git rebase",
    "delete repository or user files", "access credentials, cookies, SSH keys, or credential stores", "production deployment",
]
HIGH_RISK = re.compile(r"\b(auth|authori[sz]|security|credential|token|password|migration|schema|database|concurren|transaction|deploy|production|delete|remove)\b", re.I)
IMPLEMENTATION = re.compile(r"\b(ui|css|component|crud|test|lint|type|document|refactor|bug|feature|api|form)\b", re.I)


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_event(run_dir: Path, agent: str, action: str, status: str, duration: float = 0.0) -> None:
    record = {"timestamp": now(), "agent": agent, "action": action, "status": status, "duration_seconds": round(duration, 3)}
    with (run_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def config(root: Path) -> dict[str, Any]:
    return read_json(root / ".agents" / "config.json")


def task_id() -> str:
    return "TASK-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def normalize_task(raw: dict[str, Any], generated_id: str | None = None) -> dict[str, Any]:
    required = ("objective", "scope", "constraints", "acceptance_criteria")
    absent = [key for key in required if key not in raw]
    if absent:
        raise ValueError("Task JSON is missing: " + ", ".join(absent))
    return {
        "task_id": raw.get("task_id") or generated_id or task_id(),
        "objective": str(raw["objective"]),
        "scope": list(raw["scope"]),
        "constraints": list(raw["constraints"]),
        "acceptance_criteria": list(raw["acceptance_criteria"]),
        "verification_commands": _normalize_commands(raw.get("verification_commands", [])),
        "forbidden_actions": list(raw.get("forbidden_actions", DEFAULT_FORBIDDEN)),
        "context": dict(raw.get("context", {})),
        "review_feedback": list(raw.get("review_feedback", [])),
    }


def _normalize_commands(raw: Any) -> list[list[str]]:
    if not isinstance(raw, list):
        raise ValueError("verification_commands must be an array of argument arrays")
    commands: list[list[str]] = []
    for command in raw:
        if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
            raise ValueError("Each verification command must be a non-empty array of non-empty strings")
        commands.append(command)
    return commands


def heuristic_plan(task: dict[str, Any], root: Path, reason: str = "Local fallback router") -> dict[str, Any]:
    objective = task["objective"]
    if HIGH_RISK.search(objective):
        route, risk = ("manual", "high")
    elif IMPLEMENTATION.search(objective):
        route, risk = ("agy", "low")
    else:
        route, risk = ("codex", "medium")
    return {"task_id": task["task_id"], "route": route, "reason": reason, "risk": risk, "worker_effort": "high" if route == "agy" else "medium", "scope": task["scope"] or ["repository"], "constraints": task["constraints"], "acceptance_criteria": task["acceptance_criteria"]}


def codex_structured(root: Path, schema: Path, prompt: str, output: Path) -> tuple[dict[str, Any] | None, str]:
    codex = shutil.which("codex")
    if not codex:
        return None, "codex CLI not found"
    command = [codex, "exec", "--sandbox", "read-only", "--output-schema", str(schema), "-o", str(output), "-"]
    try:
        # Codex exec requires UTF-8 stdin. Windows' process locale may otherwise
        # encode Chinese task text as a legacy code page.
        result = subprocess.run(command, cwd=root, text=True, encoding="utf-8", errors="replace", input=prompt, capture_output=True, timeout=900, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    (output.parent / f"{output.stem}.codex.stdout.log").write_text(result.stdout, encoding="utf-8")
    (output.parent / f"{output.stem}.codex.stderr.log").write_text(result.stderr, encoding="utf-8")
    if result.returncode or not output.exists():
        return None, (result.stderr or result.stdout or f"codex exited {result.returncode}")[-2000:]
    try:
        return read_json(output), "codex"
    except (OSError, json.JSONDecodeError) as exc:
        return None, str(exc)


def create_plan(root: Path, run_dir: Path, task: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    prompt = """You are Codex Lead Engineer. Return only the requested JSON plan. Route `agy` only for bounded, implementation-heavy low-risk work executed by the local AGY CLI. Route `codex` for complex reasoning; route `manual` for security, destructive, deployment, or unclear-risk work. Do not modify files.\n\nTASK:\n""" + json.dumps(task, ensure_ascii=False)
    plan_file = run_dir / "plan.json"
    plan, source = codex_structured(root, ROOT / "schemas" / "codex-plan.schema.json", prompt, plan_file)
    if not plan:
        plan = heuristic_plan(task, root, f"{source}; heuristic fallback used")
        plan["planning_source"] = "heuristic-fallback"
        write_json(plan_file, plan)
    else:
        plan["planning_source"] = "codex"
        write_json(plan_file, plan)
    return plan


def command_checks(root: Path, task: dict[str, Any] | None = None) -> list[list[str]]:
    task_commands = (task or {}).get("verification_commands", [])
    return task_commands or checks.discover(root)


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def _path_in_scope(relative_path: str, scope: list[str]) -> bool:
    candidate = relative_path.replace("\\", "/")
    if candidate.startswith("./"):
        candidate = candidate[2:]
    for item in scope:
        allowed = str(item).replace("\\", "/").strip("/")
        if allowed and (candidate == allowed or candidate.startswith(allowed + "/")):
            return True
    return False


def _status_paths(status: str) -> list[str]:
    paths: list[str] = []
    for line in status.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path.strip('"'))
    return paths


def dirty_scope_conflicts(root: Path, task: dict[str, Any]) -> list[str]:
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all").stdout
    dirty_paths = _status_paths(status)
    if task.get("context", {}).get("requires_current_worktree"):
        return dirty_paths
    return [path for path in dirty_paths if _path_in_scope(path, task["scope"])]


def collect_change_evidence(root: Path, scope: list[str], max_file_bytes: int = 262_144, max_total_bytes: int = 1_048_576) -> dict[str, Any]:
    status_result = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    diff_result = _git(root, "diff", "--binary", "--no-ext-diff")
    untracked_result = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    untracked_files: list[dict[str, Any]] = []
    total_bytes = 0
    for relative_path in filter(None, untracked_result.stdout.split("\0")):
        record: dict[str, Any] = {"path": relative_path}
        if not _path_in_scope(relative_path, scope):
            record["omitted_reason"] = "outside explicit task scope"
        else:
            path = (root / relative_path).resolve()
            try:
                payload = path.read_bytes()
                if len(payload) > max_file_bytes or total_bytes + len(payload) > max_total_bytes:
                    record["omitted_reason"] = "evidence size limit"
                elif b"\0" in payload:
                    record["omitted_reason"] = "binary file"
                else:
                    record["content"] = payload.decode("utf-8", errors="replace")
                    record["size_bytes"] = len(payload)
                    total_bytes += len(payload)
            except OSError as exc:
                record["omitted_reason"] = f"read failed: {exc}"
        untracked_files.append(record)
    return {
        "status": status_result.stdout,
        "status_error": status_result.stderr,
        "tracked_diff": diff_result.stdout,
        "diff_error": diff_result.stderr,
        "untracked_files": untracked_files,
    }


def recover_context_canceled_worker(worker: dict[str, Any], evidence: dict[str, Any], check_results: list[dict[str, Any]]) -> dict[str, Any]:
    diagnostics = "\n".join(str(item) for item in worker.get("unresolved", []))
    if worker.get("status") != "failed" or "context canceled" not in diagnostics.lower():
        return worker
    if not check_results or any(result.get("exit_code") != 0 for result in check_results):
        return worker
    changed_files = _status_paths(str(evidence.get("status", "")))
    if not changed_files:
        return worker
    recovered = dict(worker)
    recovered.update({
        "status": "partial",
        "summary": "AGY applied changes but its final structured response was canceled; independent scoped evidence and focused checks succeeded.",
        "changed_files": changed_files,
        "tests": [
            {"command": result["command"], "exit_code": result["exit_code"]}
            for result in check_results
        ],
        "commands_executed": [" ".join(result["command"]) for result in check_results],
        "unresolved": ["AGY transport ended with context canceled before returning structured_output."],
        "needs_review": True,
        "transport_recovered": True,
    })
    return recovered


def run(root: Path, task: dict[str, Any], dry_run: bool) -> int:
    cfg = config(root)
    run_dir = root / ".agents" / "runs" / task["task_id"]
    if run_dir.exists():
        raise FileExistsError(f"Task run already exists: {task['task_id']}")
    run_dir.mkdir(parents=True)
    write_json(run_dir / "task.json", task)
    append_event(run_dir, "supervisor", "task-created", "ok")
    started = time.monotonic()
    plan = create_plan(root, run_dir, task, dry_run)
    append_event(run_dir, "codex", "plan", "ok", time.monotonic() - started)
    state: dict[str, Any] = {"task_id": task["task_id"], "status": "planned", "route": plan["route"], "dry_run": dry_run, "worktree": None, "round": 0, "updated_at": now()}
    if dry_run:
        state["status"] = "dry-run-complete"
        agy_settings = cfg.get("agy", {})
        state["expected_commands"] = {
            "checks": command_checks(root, task),
            "worker": agy_cli.build_command(
                agy_settings,
                ROOT / "schemas" / "worker-result.schema.json",
                "<structured-task-json>",
                resolve_executable=False,
            )[:-1],
        }
        write_json(run_dir / "state.json", state)
        append_event(run_dir, "supervisor", "dry-run", "ok")
        print(json.dumps({"task": task, "plan": plan, "state": state}, ensure_ascii=False, indent=2))
        return 0
    if plan["route"] != "agy":
        state["status"] = "awaiting-codex-or-manual"
        write_json(run_dir / "state.json", state)
        append_event(run_dir, "supervisor", "route", "stopped")
        print(f"{task['task_id']}: routed to {plan['route']}; no worker was started.")
        return 0
    dirty_conflicts = dirty_scope_conflicts(root, task)
    if dirty_conflicts:
        state["status"] = "awaiting-codex-or-manual"
        state["takeover_reason"] = "AGY worktrees start from HEAD and cannot safely consume conflicting uncommitted changes."
        state["dirty_conflicts"] = dirty_conflicts
        state["updated_at"] = now()
        write_json(run_dir / "state.json", state)
        append_event(run_dir, "supervisor", "dirty-worktree-preflight", "stopped")
        print(f"{task['task_id']}: dirty scope conflicts require Codex/manual handling.")
        return 0
    tree = worktrees.create(root, task["task_id"], cfg["worktree_root"])
    state.update({"status": "worker-running", "worktree": str(tree)})
    write_json(run_dir / "state.json", state)
    # Each worker attempt needs a separate Codex review. Enforce every configured
    # ceiling rather than allowing a later loop to exceed the review/run budget.
    max_agy_rounds = cfg.get("max_agy_rounds", cfg.get("max_antigravity_rounds", 3))
    round_limit = min(max_agy_rounds, cfg["max_codex_review_rounds"], cfg["max_total_agent_runs"] // 2)
    for round_no in range(1, round_limit + 1):
        state["round"] = round_no
        worker_task = dict(task)
        worker_task["review_feedback"] = state.get("review_feedback", [])
        started = time.monotonic()
        worker = agy_cli.invoke(worker_task, tree, run_dir, cfg.get("agy", {}), plan["worker_effort"])
        write_json(run_dir / f"worker-round-{round_no}.json", worker)
        append_event(run_dir, "agy-cli", f"worker-round-{round_no}", worker["status"], time.monotonic() - started)
        if worker["status"] == "blocked":
            state["status"] = "codex-takeover-required"
            state["takeover_reason"] = worker["summary"]
            state["updated_at"] = now()
            write_json(run_dir / "state.json", state)
            append_event(run_dir, "supervisor", f"worker-round-{round_no}-blocked", "stopped")
            break
        check_results = checks.run_checks(tree, command_checks(tree, task))
        write_json(run_dir / f"checks-round-{round_no}.json", check_results)
        evidence = collect_change_evidence(tree, task["scope"])
        write_json(run_dir / f"change-evidence-round-{round_no}.json", evidence)
        (run_dir / f"git-diff-round-{round_no}.patch").write_text(evidence["tracked_diff"], encoding="utf-8")
        worker = recover_context_canceled_worker(worker, evidence, check_results)
        if worker.get("transport_recovered"):
            write_json(run_dir / f"worker-round-{round_no}.json", worker)
            append_event(run_dir, "supervisor", f"worker-round-{round_no}-transport-recovered", "partial")
        review_prompt = """You are Codex reviewing a local AGY CLI worker worktree. Do not trust the worker claim. Review the task, plan, worker result, complete scoped change evidence, check results, and acceptance criteria. Return PASS only if the evidence satisfies them. A transport_recovered partial result may PASS when the independent scoped evidence and focused checks fully prove the implementation contract; report the missing raw AGY structured response as a material warning, not an automatic failure. Return FIX with precise feedback where repair is feasible; REJECT for unsafe/unsound work. Do not modify files.\n\n""" + json.dumps({"task": task, "plan": plan, "worker_result": worker, "checks": check_results, "change_evidence": evidence}, ensure_ascii=False)
        review_file = run_dir / f"review-round-{round_no}.json"
        review, review_source = codex_structured(root, ROOT / "schemas" / "codex-review.schema.json", review_prompt, review_file)
        if not review:
            review = {"task_id": task["task_id"], "verdict": "REJECT", "reason": f"Codex review unavailable: {review_source}", "feedback": [], "risk": "medium", "takeover_required": True}
            write_json(review_file, review)
        append_event(run_dir, "codex", f"review-round-{round_no}", review["verdict"])
        if review["verdict"] == "PASS":
            state["status"] = "review-passed-awaiting-manual-merge"
            break
        if worker.get("transport_recovered"):
            state["status"] = "codex-takeover-required"
            state["takeover_reason"] = review["reason"]
            break
        if review["verdict"] != "FIX" or round_no == round_limit:
            state["status"] = "codex-takeover-required"
            state["takeover_reason"] = review["reason"]
            break
        state["review_feedback"] = review["feedback"]
        write_json(run_dir / "state.json", state)
    state["updated_at"] = now()
    write_json(run_dir / "state.json", state)
    print(f"{task['task_id']}: {state['status']} (worktree: {tree})")
    return 0


def doctor(root: Path) -> int:
    checks_found = command_checks(root)
    git_ok = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root, capture_output=True, text=True).returncode == 0
    cfg = config(root)
    agy_settings = cfg.get("agy", {})
    agy_path = agy_cli.executable(agy_settings)
    agy_version = _command_line([agy_path, "--version"], root) if agy_path else "MISSING"
    models = _command_line([agy_path, "models"], root) if agy_path else ""
    configured_model = str(agy_settings.get("model", "DEFAULT"))
    model_available = "OK" if configured_model in models else "UNKNOWN" if agy_path else "MISSING"
    rows = [
        ("Git", "OK" if shutil.which("git") else "MISSING"),
        ("Repository", "OK" if git_ok else "MISSING"),
        ("Python", sys.version.split()[0]),
        ("Codex CLI", "OK" if shutil.which("codex") else "MISSING"),
        ("AGY executable", agy_path or "MISSING"),
        ("AGY version", agy_version or "UNKNOWN"),
        ("AGY configured model", configured_model),
        ("AGY model available", model_available),
        ("AGY sandbox", "ENABLED" if agy_settings.get("sandbox", True) else "DISABLED"),
        ("AGY authentication", "UNKNOWN (not probed)"),
        ("AGY smoke call", "SKIPPED"),
        ("Worktree support", "OK" if git_ok else "UNKNOWN"),
        ("Project checks", "; ".join(" ".join(x) for x in checks_found) or "NONE"),
    ]
    for name, value in rows:
        print(f"{name:<24} {value}")
    return 0 if git_ok else 1


def _command_line(command: list[str | None], root: Path) -> str:
    if not command[0]:
        return ""
    try:
        result = subprocess.run(
            [str(item) for item in command], cwd=root, text=True,
            encoding="utf-8", errors="replace", capture_output=True,
            timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (result.stdout or result.stderr).strip()


def status(root: Path, task: str) -> int:
    print((root / ".agents" / "runs" / task / "state.json").read_text(encoding="utf-8"))
    return 0


def cleanup(root: Path, task: str) -> int:
    cfg = config(root)
    worktrees.remove(root, task, cfg["worktree_root"])
    print(f"Removed worktree for {task}; run records remain for diagnosis.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run")
    run_p.add_argument("objective", nargs="?")
    run_p.add_argument("--task-file", type=Path)
    run_p.add_argument("--dry-run", action="store_true")
    sub.add_parser("doctor")
    status_p = sub.add_parser("status")
    status_p.add_argument("task_id")
    cleanup_p = sub.add_parser("cleanup")
    cleanup_p.add_argument("task_id")
    args = parser.parse_args()
    root = worktrees.repository_root(Path.cwd())
    if args.command == "doctor":
        return doctor(root)
    if args.command == "status":
        return status(root, args.task_id)
    if args.command == "cleanup":
        return cleanup(root, args.task_id)
    if bool(args.objective) == bool(args.task_file):
        parser.error("run requires exactly one objective or --task-file")
    raw = read_json(args.task_file) if args.task_file else {"objective": args.objective, "scope": [], "constraints": ["Preserve unrelated user changes", "Use the isolated worktree"], "acceptance_criteria": ["Relevant configured checks pass"]}
    return run(root, normalize_task(raw), args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
