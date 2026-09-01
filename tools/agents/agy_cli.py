"""Direct adapter for the locally installed AGY CLI."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


def executable(config: dict[str, Any]) -> str | None:
    configured = str(config.get("executable", "agy"))
    return shutil.which(configured)


def build_command(
    config: dict[str, Any],
    schema: Path,
    prompt: str,
    resolve_executable: bool = True,
) -> list[str]:
    agy = executable(config) if resolve_executable else str(config.get("executable", "agy"))
    if not agy:
        raise FileNotFoundError(f"AGY CLI was not found: {config.get('executable', 'agy')}")
    timeout = int(config.get("timeout_seconds", 900))
    command = [agy]
    if config.get("new_project", True):
        command.append("--new-project")
    model = str(config.get("model", "")).strip()
    if model:
        command.extend(["--model", model])
    effort = str(config.get("effort", "high"))
    mode = str(config.get("mode", "accept-edits"))
    # Model IDs such as gemini-3.7-flash-high already encode an effort tier.
    # Passing a separate --effort can create an invalid low/high combination.
    if not re.search(r"-(?:low|medium|high)$", model):
        command.extend(["--effort", effort])
    command.extend(["--mode", mode])
    if config.get("sandbox", True):
        command.append("--sandbox")
    if config.get("disable_slash_commands", True):
        command.append("--disable-slash-commands")
    command.extend([
        "--output-format", "json",
        "--json-schema", str(schema),
        "--print-timeout", f"{timeout}s",
        "--print",
        prompt,
    ])
    return command


def build_prompt(task: dict[str, Any], max_repair_attempts: int = 3) -> str:
    instructions = (
        "Act as a bounded implementation worker in the current Git worktree. "
        "Follow only the structured task below. Do not push, rebase, reset, clean, "
        "restore, access credentials, change system configuration, or operate outside "
        "the worktree. Apply workspace edits through terminal commands inside the "
        "current isolated worktree; write_to_file is artifact-only and must not be "
        "used for workspace paths. Do not request administrator escalation. "
        "For a read-only exploration task, return compact findings with title, "
        "file-and-line evidence, and implication; do not hide the report in prose. "
        f"You may perform up to {max_repair_attempts} self-repair attempts for focused check failures within scope. "
        "Stop and escalate on architecture, security, authentication, authorization, "
        "concurrency, migration, public contract, or scope expansion. "
        "Run only the verification_commands specified in the task and finish with JSON matching the supplied "
        "output schema."
    )
    return f"{instructions}\n\n{json.dumps(task, ensure_ascii=False, indent=2)}"


def invoke(
    task: dict[str, Any],
    worktree: Path,
    run_dir: Path,
    config: dict[str, Any],
    effort: str | None = None,
    max_repair_attempts: int | None = None,
) -> dict[str, Any]:
    """Run one local AGY model turn and return a normalized worker result."""
    run_dir.mkdir(parents=True, exist_ok=True)
    effective = dict(config)
    model = str(effective.get("model", ""))
    if effort and not re.search(r"-(?:low|medium|high)$", model):
        effective["effort"] = effort
    timeout = int(effective.get("timeout_seconds", 900))
    schema = Path(__file__).resolve().parents[2] / "schemas" / "worker-result.schema.json"
    task_repair = task.get("agy_self_repair_attempts")
    if max_repair_attempts is not None:
        try:
            repair_attempts = max(1, min(5, int(max_repair_attempts)))
        except (ValueError, TypeError):
            repair_attempts = 3
    elif task_repair is not None:
        try:
            repair_attempts = max(1, min(5, int(task_repair)))
        except (ValueError, TypeError):
            repair_attempts = 3
    else:
        default_cfg = int(effective.get("max_agy_repair_attempts", effective.get("max_repair_attempts", 3)))
        repair_attempts = max(1, min(5, default_cfg))
    prompt = build_prompt(task, max_repair_attempts=repair_attempts)
    try:
        command = build_command(effective, schema, prompt)
    except FileNotFoundError as exc:
        return _failure(task["task_id"], "blocked", str(exc), ["Install AGY CLI and ensure it is on PATH."])

    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=worktree,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout + 30,
            check=False,
        )
        stdout, stderr, exit_code = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = _as_text(exc.stdout)
        stderr = _as_text(exc.stderr) or f"AGY CLI exceeded the {timeout + 30}s process timeout."
        exit_code = None
    except OSError as exc:
        stdout, stderr, exit_code = "", str(exc), None

    duration = round(time.monotonic() - started, 3)
    (run_dir / "agy.stdout.log").write_text(stdout, encoding="utf-8")
    (run_dir / "agy.stderr.log").write_text(stderr, encoding="utf-8")
    diagnostic_output = "\n".join(value for value in (stderr, stdout) if value)
    if _is_permission_denial(diagnostic_output):
        permission_output = stderr if _is_permission_denial(stderr) else diagnostic_output
        result = _process_failure(task["task_id"], permission_output, exit_code)
    elif exit_code != 0:
        result = _process_failure(task["task_id"], stderr or stdout, exit_code)
    else:
        result = _parse_result(stdout, task["task_id"])
    result["process"] = {
        "command": command[:-1],
        "exit_code": exit_code,
        "duration_seconds": duration,
        "model": effective.get("model"),
    }
    return result


def _is_permission_denial(output: str) -> bool:
    lowered = output.lower()
    if "permission check failed" in lowered or "denied permission" in lowered:
        return True
    if "soft-denying tool confirmation" in lowered:
        return True
    if "headless mode" not in lowered or "permission" not in lowered:
        return False
    return any(
        marker in lowered
        for marker in ("auto-denied", "auto denied", "cannot prompt")
    )


def _process_failure(task_id: str, output: str, exit_code: int | None) -> dict[str, Any]:
    lowered = output.lower()
    if "authentication required" in lowered or "authentication failed" in lowered:
        return _failure(task_id, "blocked", "AGY CLI authentication is required.", ["Complete AGY login and retry."])
    if _is_permission_denial(output):
        return _failure(task_id, "blocked", "AGY sandbox denied a requested command.", [output[-2000:]])
    if "model" in lowered and any(word in lowered for word in ("unsupported", "not found", "unavailable")):
        return _failure(task_id, "blocked", "The configured AGY model is unavailable.", [output[-2000:]])
    return _failure(task_id, "failed", f"AGY CLI exited with code {exit_code}.", [output[-2000:] or "No diagnostic output was returned."])


def _parse_result(stdout: str, task_id: str) -> dict[str, Any]:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return _failure(task_id, "failed", "AGY CLI did not return valid JSON.", ["See agy.stdout.log."])
    candidates: list[Any] = [data]
    if isinstance(data, dict):
        candidates.extend(data.get(key) for key in ("structured_output", "result", "response", "final", "content"))
    for candidate in candidates:
        if isinstance(candidate, str):
            try:
                candidate = json.loads(candidate)
            except json.JSONDecodeError:
                continue
        if isinstance(candidate, dict) and _valid_worker_result(candidate, task_id):
            return candidate
    return _failure(task_id, "failed", "AGY JSON did not match the worker result contract.", ["See agy.stdout.log."])


def _valid_worker_result(value: dict[str, Any], task_id: str) -> bool:
    required = {
        "task_id", "status", "summary", "changed_files", "tests",
        "commands_executed", "risks", "unresolved", "needs_review",
    }
    return required.issubset(value) and value.get("task_id") == task_id and value.get("status") in {
        "completed", "partial", "failed", "blocked",
    }


def _failure(task_id: str, status: str, summary: str, unresolved: list[str]) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "status": status,
        "summary": summary,
        "changed_files": [],
        "tests": [],
        "commands_executed": [],
        "risks": [],
        "unresolved": unresolved,
        "needs_review": True,
    }


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("task_file", type=Path)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path(".agents/config.json"))
    args = parser.parse_args()
    settings = json.loads(args.config.read_text(encoding="utf-8"))
    task = json.loads(args.task_file.read_text(encoding="utf-8"))
    print(json.dumps(invoke(task, args.worktree, args.run_dir, settings.get("agy", {})), ensure_ascii=False, indent=2))
