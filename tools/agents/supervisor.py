"""Durable, bounded Codex lead / local AGY CLI worker supervisor."""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
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

HIGH_RISK_CATEGORIES = {
    "architecture", "security", "authentication", "authorization",
    "concurrency", "migration", "public-contract", "destructive",
}

LOW_RISK_CATEGORIES = {
    "mechanical", "test-only", "ui", "ordinary-implementation",
    "test_only", "ordinary_implementation", "implementation",
}

HIGH_RISK = re.compile(
    r"\b(auth\w*|authori[sz]\w*|security|credential\w*|token\w*|password\w*|migration\w*|schema\w*|database\w*|"
    r"concurren\w*|transaction\w*|deploy\w*|production|delete\w*|remove\w*|architect\w*|public[-_\s]?contract\w*|destructive)\b",
    re.I,
)
IMPLEMENTATION = re.compile(
    r"\b(ui|css|component|crud|test|lint|type|document|refactor|bug|feature|api|form|mechanical|ordinary[-_]?implementation)\b",
    re.I,
)


class CodexProfileUnavailable(RuntimeError):
    """Selected Codex provider profile cannot be used safely."""


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
    task_dict = {
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
    if raw.get("profile"):
        task_dict["profile"] = str(raw["profile"])
    if raw.get("category"):
        cat = str(raw["category"]).strip().lower().replace("_", "-")
        if cat == "implementation":
            cat = "ordinary-implementation"
        task_dict["category"] = cat
    if raw.get("risk_class"):
        rc = str(raw["risk_class"]).strip().lower().replace("_", "-")
        if rc == "implementation":
            rc = "ordinary-implementation"
        task_dict["risk_class"] = rc
    if raw.get("review_policy"):
        task_dict["review_policy"] = str(raw["review_policy"])
    if raw.get("agy_self_repair_attempts") is not None:
        val = raw["agy_self_repair_attempts"]
        if isinstance(val, bool) or not isinstance(val, int) or not 1 <= val <= 5:
            raise ValueError("agy_self_repair_attempts must be an integer between 1 and 5")
        task_dict["agy_self_repair_attempts"] = val
    return task_dict


def _normalize_commands(raw: Any) -> list[list[str]]:
    if not isinstance(raw, list):
        raise ValueError("verification_commands must be an array of argument arrays")
    commands: list[list[str]] = []
    for command in raw:
        if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
            raise ValueError("Each verification command must be a non-empty array of non-empty strings")
        commands.append(command)
    return commands


def evaluate_risk(task: dict[str, Any]) -> str:
    labels = [
        str(value).strip().lower().replace("_", "-")
        for value in (
            task.get("risk_class"),
            task.get("category"),
            task.get("context", {}).get("risk_class"),
            task.get("context", {}).get("category"),
        )
        if value
    ]
    objective = str(task.get("objective", ""))
    risk_field = str(task.get("risk") or task.get("context", {}).get("risk") or "").strip().lower()

    if (
        any(label in HIGH_RISK_CATEGORIES or HIGH_RISK.search(label) for label in labels)
        or HIGH_RISK.search(objective)
        or risk_field == "high"
    ):
        return "high"
    if any(label in LOW_RISK_CATEGORIES for label in labels) or risk_field == "low":
        return "low"
    if IMPLEMENTATION.search(objective) or any(IMPLEMENTATION.search(label) for label in labels):
        return "low"
    return "medium"


def resolve_profile(
    task: dict[str, Any],
    cfg: dict[str, Any],
    cli_profile: str | None = None,
) -> tuple[str, str, str | None]:
    requested = cli_profile or task.get("profile") or cfg.get("profile", "agy-heavy")
    if requested not in ("agy-heavy", "codex-controlled"):
        requested = "agy-heavy"
    risk = evaluate_risk(task)
    review_policy = str(
        task.get("review_policy")
        or task.get("context", {}).get("review_policy")
        or ""
    ).strip().lower()
    if requested == "agy-heavy" and risk == "high":
        return "codex-controlled", requested, "High-risk task forced to codex-controlled profile"
    if requested == "agy-heavy" and risk == "medium":
        return (
            "codex-controlled",
            requested,
            "Unclassified or medium-risk task forced to codex-controlled profile",
        )
    if requested == "agy-heavy" and review_policy == "codex-required":
        return "codex-controlled", requested, "Review policy codex-required forced to codex-controlled profile"
    return requested, requested, None


def resolve_codex_profile(cfg: dict[str, Any], cli_profile: str | None = None) -> dict[str, str | None]:
    settings = cfg.get("codex", {})
    if not isinstance(settings, dict):
        settings = {}
    requested = str(cli_profile or settings.get("profile") or "official").strip().lower()
    allowed = settings.get("allowed_profiles", ["official", "relay"])
    if not isinstance(allowed, list) or requested not in {
        str(value).strip().lower() for value in allowed if isinstance(value, str)
    }:
        raise ValueError(f"Unsupported Codex profile: {requested}")
    profiles = settings.get("profiles", {})
    profile_settings = profiles.get(requested, {}) if isinstance(profiles, dict) else {}
    if not isinstance(profile_settings, dict):
        raise ValueError(f"Invalid Codex profile configuration: {requested}")
    cli_name = profile_settings.get("cli_profile")
    required_env = profile_settings.get("required_env")
    if cli_name is not None and (not isinstance(cli_name, str) or not cli_name.strip()):
        raise ValueError(f"Invalid Codex CLI profile configuration: {requested}")
    if required_env is not None and (not isinstance(required_env, str) or not required_env.strip()):
        raise ValueError(f"Invalid Codex credential reference configuration: {requested}")
    return {
        "name": requested,
        "cli_profile": cli_name.strip() if isinstance(cli_name, str) else None,
        "required_env": required_env.strip() if isinstance(required_env, str) else None,
    }


DEFAULT_ALLOWED_MODELS: tuple[str, ...] = ("gemini-3.7-flash-high", "gemini-3.7-flash-low")
DEFAULT_MODEL: str = "gemini-3.7-flash-high"


def get_allowed_models(cfg: dict[str, Any]) -> list[str]:
    agy_settings = cfg.get("agy", {})
    allowed = agy_settings.get("allowed_models")
    if allowed is None:
        model_policy = agy_settings.get("model_policy") or cfg.get("model_policy") or {}
        if isinstance(model_policy, dict):
            allowed = model_policy.get("allowed_models")
    if allowed is None:
        allowed = cfg.get("allowed_models")
    if isinstance(allowed, list):
        parsed = [str(m).strip() for m in allowed if isinstance(m, str) and str(m).strip()]
        if parsed:
            return parsed
    return list(DEFAULT_ALLOWED_MODELS)


def resolve_model(task: dict[str, Any], cfg: dict[str, Any]) -> str:
    allowed_models = get_allowed_models(cfg)
    agy_settings = cfg.get("agy", {})
    raw_configured_model = str(agy_settings.get("model", DEFAULT_MODEL)).strip() or DEFAULT_MODEL
    fallback_model = raw_configured_model if raw_configured_model in allowed_models else DEFAULT_MODEL
    model_policy = agy_settings.get("model_policy")
    if model_policy is None:
        model_policy = cfg.get("model_policy", {})

    if not isinstance(model_policy, dict):
        return fallback_model

    raw_default = str(model_policy.get("default", fallback_model)).strip() or fallback_model
    default_model = raw_default if raw_default in allowed_models else fallback_model

    categories_map = model_policy.get("categories")
    merged_categories: dict[str, Any] = dict(categories_map) if isinstance(categories_map, dict) else {}
    for k, v in model_policy.items():
        if k not in ("default", "categories", "allowed_models") and isinstance(v, str):
            merged_categories[k] = v

    normalized_policy_map: dict[str, str] = {}
    for cat_name, mod_val in merged_categories.items():
        normalized_key = cat_name.strip().lower().replace("_", "-")
        if normalized_key == "implementation":
            normalized_key = "ordinary-implementation"
        if isinstance(mod_val, str) and mod_val.strip() and mod_val.strip() in allowed_models:
            model_val = mod_val.strip()
        else:
            model_val = fallback_model
        normalized_policy_map[normalized_key] = model_val
        normalized_policy_map[cat_name.strip()] = model_val

    raw_category = (
        task.get("category")
        or task.get("risk_class")
        or task.get("context", {}).get("category")
        or task.get("context", {}).get("risk_class")
    )
    if raw_category:
        norm_cat = str(raw_category).strip().lower().replace("_", "-")
        if norm_cat == "implementation":
            norm_cat = "ordinary-implementation"
        if norm_cat in normalized_policy_map:
            return normalized_policy_map[norm_cat]
        if str(raw_category).strip() in normalized_policy_map:
            return normalized_policy_map[str(raw_category).strip()]

    return default_model


def build_contract_plan(task: dict[str, Any], reason: str = "Local agy-heavy task contract") -> dict[str, Any]:
    risk = evaluate_risk(task)
    route = "agy" if risk == "low" else "codex"
    return {
        "task_id": task["task_id"],
        "route": route,
        "reason": reason,
        "risk": risk,
        "worker_effort": "high" if route == "agy" else "medium",
        "scope": task["scope"] or ["repository"],
        "constraints": task["constraints"],
        "acceptance_criteria": task["acceptance_criteria"],
        "planning_source": "task-contract",
    }


def heuristic_plan(task: dict[str, Any], root: Path, reason: str = "Local fallback router") -> dict[str, Any]:
    risk = evaluate_risk(task)
    if risk == "high":
        route = "manual"
    elif risk == "low":
        route = "agy"
    else:
        route = "codex"
    return {
        "task_id": task["task_id"],
        "route": route,
        "reason": reason,
        "risk": risk,
        "worker_effort": "high" if route == "agy" else "medium",
        "scope": task["scope"] or ["repository"],
        "constraints": task["constraints"],
        "acceptance_criteria": task["acceptance_criteria"],
        "planning_source": "heuristic-fallback",
    }


def codex_structured(
    root: Path,
    schema: Path,
    prompt: str,
    output: Path,
    codex_profile: dict[str, str | None] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    codex = shutil.which("codex")
    if not codex:
        return None, "codex CLI not found"
    selected = codex_profile or {"name": "official", "cli_profile": None, "required_env": None}
    required_env = selected.get("required_env")
    if required_env and not os.environ.get(required_env):
        raise CodexProfileUnavailable(
            f"Codex profile '{selected.get('name')}' requires credential environment variable '{required_env}'."
        )
    command = [codex, "exec"]
    cli_profile = selected.get("cli_profile")
    if cli_profile:
        command.extend(["--profile", cli_profile])
    command.extend(["--sandbox", "read-only", "--output-schema", str(schema), "-o", str(output), "-"])
    try:
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


def create_plan(
    root: Path,
    run_dir: Path,
    task: dict[str, Any],
    dry_run: bool,
    codex_profile: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    prompt = """You are Codex Lead Engineer. Return only the requested JSON plan. Route `agy` only for bounded, implementation-heavy low-risk work executed by the local AGY CLI. Route `codex` for complex reasoning; route `manual` for security, destructive, deployment, or unclear-risk work. Do not modify files.\n\nTASK:\n""" + json.dumps(task, ensure_ascii=False)
    plan_file = run_dir / "plan.json"
    plan, source = codex_structured(
        root,
        ROOT / "schemas" / "codex-plan.schema.json",
        prompt,
        plan_file,
        codex_profile,
    )
    if not plan:
        if codex_profile and codex_profile.get("name") != "official":
            raise CodexProfileUnavailable(
                f"Codex profile '{codex_profile.get('name')}' failed to produce a valid plan; see Codex run logs."
            )
        plan = heuristic_plan(task, root, f"{source}; heuristic fallback used")
        plan["planning_source"] = "heuristic-fallback"
        write_json(plan_file, plan)
    else:
        plan["planning_source"] = "codex"
        write_json(plan_file, plan)
    return plan


def command_checks(root: Path, task: dict[str, Any] | None = None) -> list[list[str]]:
    if task and task.get("context", {}).get("read_only") is True:
        return []
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
        if allowed in ("", ".", "repository"):
            return True
        if allowed and (candidate == allowed or candidate.startswith(allowed + "/")):
            return True
    return False


def compute_changed_paths(root: Path, base_commit: str | None = None) -> list[str]:
    changed: list[str] = []
    if base_commit:
        diff_res = _git(root, "diff", "--name-only", base_commit)
        if diff_res.returncode == 0:
            changed.extend([p.strip().strip('"') for p in diff_res.stdout.splitlines() if p.strip()])
        else:
            status_res = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
            changed.extend(_status_paths(status_res.stdout))
    else:
        status_res = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
        changed.extend(_status_paths(status_res.stdout))

    untracked_res = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    if untracked_res.returncode == 0:
        changed.extend([p.strip().strip('"') for p in untracked_res.stdout.split("\0") if p.strip()])

    return sorted(list(dict.fromkeys(changed)))


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


def collect_change_evidence(
    root: Path,
    scope: list[str],
    max_file_bytes: int = 262_144,
    max_total_bytes: int = 1_048_576,
    base_commit: str | None = None,
) -> dict[str, Any]:
    status_result = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if base_commit:
        diff_result = _git(root, "diff", "--binary", "--no-ext-diff", base_commit)
        if diff_result.returncode != 0:
            diff_result = _git(root, "diff", "--binary", "--no-ext-diff")
    else:
        diff_result = _git(root, "diff", "--binary", "--no-ext-diff")

    untracked_result = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    untracked_files: list[dict[str, Any]] = []
    untracked_diff_chunks: list[str] = []
    total_bytes = 0
    if untracked_result.returncode == 0:
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

                untracked_diff = _git(root, "diff", "--no-index", "--binary", "--", "/dev/null", relative_path)
                if untracked_diff.stdout:
                    untracked_diff_chunks.append(untracked_diff.stdout)

            untracked_files.append(record)

    patch_parts: list[str] = []
    if diff_result.stdout:
        patch_parts.append(diff_result.stdout)
    if untracked_diff_chunks:
        patch_parts.extend(untracked_diff_chunks)
    full_patch = "".join(patch_parts)

    changed_paths = compute_changed_paths(root, base_commit)

    return {
        "status": status_result.stdout,
        "status_error": status_result.stderr,
        "tracked_diff": diff_result.stdout,
        "diff_error": diff_result.stderr,
        "untracked_files": untracked_files,
        "patch": full_patch,
        "changed_paths": changed_paths,
        "base_commit": base_commit,
    }


def recover_context_canceled_worker(
    worker: dict[str, Any], evidence: dict[str, Any], check_results: list[dict[str, Any]]
) -> dict[str, Any]:
    diagnostics = "\n".join(str(item) for item in worker.get("unresolved", []))
    if worker.get("status") != "failed" or "context canceled" not in diagnostics.lower():
        return worker
    if not check_results or any(result.get("exit_code") != 0 for result in check_results):
        return worker
    changed_files = evidence.get("changed_paths") or _status_paths(str(evidence.get("status", "")))
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


def run(
    root: Path,
    task: dict[str, Any],
    dry_run: bool,
    profile: str | None = None,
    codex_profile: str | None = None,
) -> int:
    cfg = config(root)
    effective_profile, requested_profile, override_reason = resolve_profile(task, cfg, profile)
    selected_codex_profile = resolve_codex_profile(cfg, codex_profile)
    resolved_model = resolve_model(task, cfg)
    effective_agy_settings = dict(cfg.get("agy", {}))
    effective_agy_settings["model"] = resolved_model

    run_dir = root / ".agents" / "runs" / task["task_id"]
    if run_dir.exists():
        raise FileExistsError(f"Task run already exists: {task['task_id']}")
    run_dir.mkdir(parents=True)
    write_json(run_dir / "task.json", task)
    append_event(run_dir, "supervisor", "task-created", "ok")

    if effective_profile == "agy-heavy":
        plan = build_contract_plan(task)
        write_json(run_dir / "plan.json", plan)
        append_event(run_dir, "supervisor", "plan", "ok")
    else:
        started = time.monotonic()
        try:
            plan = create_plan(root, run_dir, task, dry_run, selected_codex_profile)
        except CodexProfileUnavailable as exc:
            state = {
                "task_id": task["task_id"],
                "status": "codex-profile-unavailable",
                "route": "codex",
                "profile": effective_profile,
                "requested_profile": requested_profile,
                "codex_profile": selected_codex_profile["name"],
                "dry_run": dry_run,
                "worktree": None,
                "round": 0,
                "updated_at": now(),
                "error": str(exc),
            }
            write_json(run_dir / "state.json", state)
            append_event(run_dir, "codex", "profile-preflight", "failed", time.monotonic() - started)
            print(f"{task['task_id']}: {state['status']} - {state['error']}")
            return 0
        append_event(run_dir, "codex", "plan", "ok", time.monotonic() - started)

    state: dict[str, Any] = {
        "task_id": task["task_id"],
        "status": "planned",
        "route": plan["route"],
        "profile": effective_profile,
        "requested_profile": requested_profile,
        "codex_profile": selected_codex_profile["name"],
        "model": resolved_model,
        "dry_run": dry_run,
        "worktree": None,
        "round": 0,
        "updated_at": now(),
    }
    if override_reason:
        state["profile_override_reason"] = override_reason

    if effective_profile == "agy-heavy" and not task.get("verification_commands"):
        state["status"] = "verification-commands-required"
        state["error"] = "agy-heavy profile requires non-empty verification_commands before creating a worktree."
        state["updated_at"] = now()
        write_json(run_dir / "state.json", state)
        append_event(run_dir, "supervisor", "verification-commands-check", "failed")
        print(f"{task['task_id']}: {state['status']} - {state['error']}")
        return 0

    if dry_run:
        state["status"] = "dry-run-complete"
        expected_checks = task.get("verification_commands") if effective_profile == "agy-heavy" else command_checks(root, task)
        state["expected_commands"] = {
            "checks": expected_checks,
            "worker": agy_cli.build_command(
                effective_agy_settings,
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
    base_commit_res = _git(tree, "rev-parse", "HEAD")
    base_commit = base_commit_res.stdout.strip() if base_commit_res.returncode == 0 else None
    state.update({"status": "worker-running", "worktree": str(tree)})
    if base_commit:
        state["base_commit"] = base_commit
    write_json(run_dir / "state.json", state)

    default_repair = int(cfg.get("max_agy_repair_attempts", cfg.get("max_repair_attempts", 3)))
    task_repair = task.get("agy_self_repair_attempts")
    if task_repair is not None:
        try:
            repair_attempts = max(1, min(5, int(task_repair)))
        except (ValueError, TypeError):
            repair_attempts = max(1, min(5, default_repair))
    else:
        repair_attempts = max(1, min(5, default_repair))

    if effective_profile == "agy-heavy":
        state["round"] = 1
        started = time.monotonic()
        worker = agy_cli.invoke(
            task,
            tree,
            run_dir,
            effective_agy_settings,
            plan["worker_effort"],
            max_repair_attempts=repair_attempts,
        )
        write_json(run_dir / "worker-round-1.json", worker)
        append_event(run_dir, "agy-cli", "worker-round-1", worker["status"], time.monotonic() - started)

        if worker["status"] == "blocked":
            state["status"] = "codex-takeover-required"
            state["takeover_reason"] = worker["summary"]
            state["updated_at"] = now()
            write_json(run_dir / "state.json", state)
            append_event(run_dir, "supervisor", "worker-round-1-blocked", "stopped")
            print(f"{task['task_id']}: worker blocked: {worker['summary']}")
            return 0

        check_results = checks.run_checks(tree, task["verification_commands"])
        write_json(run_dir / "checks-round-1.json", check_results)
        evidence = collect_change_evidence(tree, task["scope"], base_commit=base_commit)
        write_json(run_dir / "change-evidence-round-1.json", evidence)
        (run_dir / "git-diff-round-1.patch").write_text(evidence["patch"], encoding="utf-8")
        worker = recover_context_canceled_worker(worker, evidence, check_results)
        if worker.get("transport_recovered"):
            write_json(run_dir / "worker-round-1.json", worker)
            append_event(run_dir, "supervisor", "worker-round-1-transport-recovered", "partial")

        worker_ok = worker.get("status") == "completed" or bool(worker.get("transport_recovered"))
        checks_ok = bool(check_results) and all(r.get("exit_code") == 0 for r in check_results)

        if not worker_ok:
            state["status"] = "codex-takeover-required"
            state["takeover_reason"] = f"Worker finished with status '{worker.get('status')}': {worker.get('summary', '')}"
            state["updated_at"] = now()
            write_json(run_dir / "state.json", state)
            append_event(run_dir, "supervisor", "worker-round-1-failed", "failed")
            print(f"{task['task_id']}: {state['status']} - {state['takeover_reason']}")
            return 0

        if not checks_ok:
            failed_cmds = [" ".join(r.get("command", [])) for r in check_results if r.get("exit_code") != 0]
            state["status"] = "codex-takeover-required"
            state["takeover_reason"] = f"Verification checks failed: {', '.join(failed_cmds)}"
            state["updated_at"] = now()
            write_json(run_dir / "state.json", state)
            append_event(run_dir, "supervisor", "checks-round-1-failed", "failed")
            print(f"{task['task_id']}: {state['status']} - {state['takeover_reason']}")
            return 0

        changed_paths = evidence.get("changed_paths") or compute_changed_paths(tree, base_commit)
        out_of_scope = [path for path in changed_paths if not _path_in_scope(path, task["scope"])]
        if out_of_scope:
            state["status"] = "codex-takeover-required"
            state["takeover_reason"] = f"Changes outside declared task scope detected: {', '.join(out_of_scope)}"
            state["out_of_scope_changes"] = out_of_scope
            state["updated_at"] = now()
            write_json(run_dir / "state.json", state)
            append_event(run_dir, "supervisor", "scope-validation-failed", "failed")
            print(f"{task['task_id']}: {state['status']} - {state['takeover_reason']}")
            return 0

        state["status"] = "worker-complete-awaiting-manual-review"
        state["updated_at"] = now()
        write_json(run_dir / "state.json", state)
        append_event(run_dir, "supervisor", "worker-completed", "ok")
        print(f"{task['task_id']}: {state['status']} (worktree: {tree})")
        return 0

    # codex-controlled profile loop
    max_agy_rounds = cfg.get("max_agy_rounds", cfg.get("max_antigravity_rounds", 3))
    round_limit = min(max_agy_rounds, cfg["max_codex_review_rounds"], cfg["max_total_agent_runs"] // 2)
    for round_no in range(1, round_limit + 1):
        state["round"] = round_no
        worker_task = dict(task)
        worker_task["review_feedback"] = state.get("review_feedback", [])
        started = time.monotonic()
        worker = agy_cli.invoke(
            worker_task,
            tree,
            run_dir,
            effective_agy_settings,
            plan["worker_effort"],
            max_repair_attempts=repair_attempts,
        )
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
        evidence = collect_change_evidence(tree, task["scope"], base_commit=base_commit)
        write_json(run_dir / f"change-evidence-round-{round_no}.json", evidence)
        (run_dir / f"git-diff-round-{round_no}.patch").write_text(evidence["patch"], encoding="utf-8")
        worker = recover_context_canceled_worker(worker, evidence, check_results)
        if worker.get("transport_recovered"):
            write_json(run_dir / f"worker-round-{round_no}.json", worker)
            append_event(run_dir, "supervisor", f"worker-round-{round_no}-transport-recovered", "partial")
        review_prompt = """You are Codex reviewing a local AGY CLI worker worktree. Do not trust the worker claim. Review the task, plan, worker result, complete scoped change evidence, check results, and acceptance criteria. Return PASS only if the evidence satisfies them. A transport_recovered partial result may PASS when the independent scoped evidence and focused checks fully prove the implementation contract; report the missing raw AGY structured response as a material warning, not an automatic failure. Return FIX with precise feedback where repair is feasible; REJECT for unsafe/unsound work. Do not modify files.\n\n""" + json.dumps({"task": task, "plan": plan, "worker_result": worker, "checks": check_results, "change_evidence": evidence}, ensure_ascii=False)
        review_file = run_dir / f"review-round-{round_no}.json"
        try:
            review, review_source = codex_structured(
                root,
                ROOT / "schemas" / "codex-review.schema.json",
                review_prompt,
                review_file,
                selected_codex_profile,
            )
        except CodexProfileUnavailable as exc:
            review = None
            review_source = str(exc)
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
    model_policy = agy_settings.get("model_policy") or cfg.get("model_policy") or {}
    default_policy_model = (
        str(model_policy.get("default", configured_model))
        if isinstance(model_policy, dict)
        else configured_model
    )
    allowed_models = get_allowed_models(cfg)

    policy_models: list[str] = []
    if configured_model and configured_model != "DEFAULT":
        policy_models.append(configured_model)
    if default_policy_model and default_policy_model != "DEFAULT" and default_policy_model not in policy_models:
        policy_models.append(default_policy_model)
    if isinstance(model_policy, dict):
        cats = model_policy.get("categories")
        if isinstance(cats, dict):
            for m in cats.values():
                if isinstance(m, str) and m.strip() and m.strip() not in policy_models:
                    policy_models.append(m.strip())
        for k, v in model_policy.items():
            if (
                k not in ("default", "categories", "allowed_models")
                and isinstance(v, str)
                and v.strip()
                and v.strip() not in policy_models
            ):
                policy_models.append(v.strip())
    for m in allowed_models:
        if m not in policy_models:
            policy_models.append(m)

    if not agy_path:
        model_available = "MISSING"
        policy_available = "MISSING"
    elif not models:
        model_available = "UNKNOWN"
        policy_available = "UNKNOWN"
    else:
        model_available = "OK" if (configured_model in models and configured_model != "DEFAULT") else "MISSING"
        missing_policy = [m for m in policy_models if m not in models]
        if not missing_policy:
            policy_available = "OK"
        else:
            policy_available = f"MISSING ({', '.join(missing_policy)})"

    configured_profile = str(cfg.get("profile", "agy-heavy"))
    rows = [
        ("Git", "OK" if shutil.which("git") else "MISSING"),
        ("Repository", "OK" if git_ok else "MISSING"),
        ("Python", sys.version.split()[0]),
        ("Supervisor profile", configured_profile),
        ("Codex CLI", "OK" if shutil.which("codex") else "MISSING"),
        ("AGY executable", agy_path or "MISSING"),
        ("AGY version", agy_version or "UNKNOWN"),
        ("AGY configured model", configured_model),
        ("AGY default model policy", default_policy_model),
        ("AGY allowed models", ", ".join(allowed_models)),
        ("AGY model available", model_available),
        ("AGY policy models available", policy_available),
        ("AGY sandbox", "ENABLED" if agy_settings.get("sandbox", True) else "DISABLED"),
        ("AGY authentication", "UNKNOWN (not probed)"),
        ("AGY smoke call", "SKIPPED"),
        ("Worktree support", "OK" if git_ok else "UNKNOWN"),
        ("Project checks", "; ".join(" ".join(x) for x in checks_found) or "NONE"),
    ]
    for name, value in rows:
        print(f"{name:<28} {value}")
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
    run_p.add_argument("--profile", choices=["agy-heavy", "codex-controlled"], default=None, help="Supervisor execution profile")
    run_p.add_argument("--codex-profile", choices=["official", "relay"], default=None, help="Codex provider profile")
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
    return run(
        root,
        normalize_task(raw),
        args.dry_run,
        profile=args.profile,
        codex_profile=args.codex_profile,
    )


if __name__ == "__main__":
    raise SystemExit(main())
