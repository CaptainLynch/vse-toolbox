"""Bounded subagent dispatch and completion-wait protocol.

This module turns the 2026-10-22 dispatch audit
(``docs/AGENT_DISPATCH_PROTOCOL_20261022.md``) into pure, testable rules:

* a dispatch plan is only valid when concurrently writing units own disjoint
  paths and the number of write channels stays within the pilot cap;
* commands with repository-wide side effects are never delegated;
* a wait returns as soon as any unit reaches a terminal state, reports a stall
  when a unit stops updating its marker, and never waits past a hard limit.

The functions here perform no I/O so the lead can reason about a plan before
spending wall clock on it. ``python -m tools.agents.dispatch_wait_protocol``
adds the thin file-system layer used by the lead session.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

# Measured 2026-10-21/22: subagent rounds ran 259s..1423s (median ~420s) and 27
# fixed 300s shell polls expired without a result. The waiter therefore polls a
# marker directory instead of a fixed budget, with a stall signal well below the
# observed maximum and a hard limit above it.
DEFAULT_WAIT_POLICY: dict[str, int] = {
    "stall_seconds": 600,
    "hard_limit_seconds": 1800,
    "poll_interval_seconds": 5,
    "max_write_channels": 2,
    # A waiter is normally started right after dispatch, before any unit has
    # written its marker, so "no markers yet" must not end the wait instantly.
    "no_marks_grace_seconds": 60,
}

MAX_WRITE_CHANNELS_CEILING = 3

TERMINAL_STATUSES = frozenset({"done", "failed", "blocked"})
NON_TERMINAL_STATUSES = frozenset({"running", "started"})
WRITE_ROLES = frozenset({"implement", "fix"})
READ_ONLY_ROLES = frozenset({"review", "rereview"})

# Repository-wide side effects that must stay with the lead, because two
# concurrent units would corrupt each other (git index, generated files,
# dependency trees, lockfiles, migration numbering).
FORBIDDEN_COMMAND_PATTERNS: tuple[tuple[str, str], ...] = (
    ("git-add", r"\bgit\s+add\b"),
    ("git-commit", r"\bgit\s+commit\b"),
    ("git-stash", r"\bgit\s+stash\b"),
    ("git-checkout", r"\bgit\s+checkout\b"),
    ("git-reset", r"\bgit\s+reset\b"),
    ("git-clean", r"\bgit\s+clean\b"),
    ("git-worktree", r"\bgit\s+worktree\b"),
    ("dependency-install", r"\b(pip|pip3|uv\s+pip|poetry|npm|pnpm|yarn)\s+(install|add|remove|upgrade)\b"),
    ("repo-wide-format", r"\b(black|ruff\s+format|prettier|eslint\s+--fix|clang-format)\b(?!.*\s--?\w*(file|include|paths?))"),
    ("migration-generate", r"\b(alembic\s+revision|makemigrations|migrate\s+revision)\b"),
)

# A pytest run without a file, selector or directory path runs the whole suite.
_SCOPED_PYTEST_TARGET = re.compile(r"(\.py\b|::|[\w.\-]+[/\\][\w./\\\-]+)")
_PYTEST_INVOCATION = re.compile(r"\bpytest\b([^\n|;&]*)")


def _is_full_suite_pytest(command: str) -> bool:
    """True when pytest is invoked with no file, selector or nested directory."""
    for match in _PYTEST_INVOCATION.finditer(command):
        if not _SCOPED_PYTEST_TARGET.search(match.group(1)):
            return True
    return False


def normalize_wait_policy(raw: Mapping[str, Any] | None = None) -> dict[str, int]:
    """Validate and complete the wait policy."""
    policy = dict(DEFAULT_WAIT_POLICY)
    if raw is not None:
        if not isinstance(raw, Mapping):
            raise ValueError("Wait policy must be an object")
        for key in DEFAULT_WAIT_POLICY:
            if key not in raw:
                continue
            value = raw[key]
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{key} must be a positive integer")
            policy[key] = value

    for key, value in policy.items():
        if value <= 0:
            raise ValueError(f"{key} must be a positive integer")
    if policy["stall_seconds"] >= policy["hard_limit_seconds"]:
        raise ValueError("stall_seconds must be lower than hard_limit_seconds")
    if policy["max_write_channels"] > MAX_WRITE_CHANNELS_CEILING:
        raise ValueError(
            f"max_write_channels must be <= {MAX_WRITE_CHANNELS_CEILING} until a pilot proves it safe"
        )
    return policy


def _normalize_path(path: str) -> str:
    cleaned = path.replace("\\", "/").strip()
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned.strip("/").lower()


def validate_dispatch_plan(
    units: Iterable[Mapping[str, Any]],
    *,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Check one dispatch plan before any subagent is started.

    Each unit declares ``id``, ``role`` and ``write_paths``. Units in a write
    role must declare at least one path and all write paths must be disjoint.
    Read-only roles must not declare write paths.
    """
    wait_policy = normalize_wait_policy(policy)
    errors: list[str] = []
    conflicts: list[dict[str, Any]] = []
    owners: dict[str, str] = {}
    write_units: list[str] = []
    seen_ids: set[str] = set()

    normalized: list[dict[str, Any]] = []
    for raw in units:
        if not isinstance(raw, Mapping):
            errors.append("unit must be an object")
            continue
        unit_id = str(raw.get("id") or "").strip()
        role = str(raw.get("role") or "").strip().lower()
        raw_paths = raw.get("write_paths") or []
        if not unit_id:
            errors.append("unit is missing id")
            continue
        if unit_id in seen_ids:
            errors.append(f"duplicate unit id: {unit_id}")
            continue
        seen_ids.add(unit_id)
        if role not in WRITE_ROLES | READ_ONLY_ROLES:
            errors.append(f"{unit_id}: unknown role {role!r}")
            continue
        if isinstance(raw_paths, str) or not isinstance(raw_paths, Sequence):
            errors.append(f"{unit_id}: write_paths must be a list")
            continue

        paths = [_normalize_path(str(p)) for p in raw_paths if str(p).strip()]
        if role in WRITE_ROLES:
            if not paths:
                errors.append(f"{unit_id}: write role requires at least one write path")
            write_units.append(unit_id)
        else:
            if paths:
                errors.append(f"{unit_id}: read-only role must not declare write paths")

        for path in paths:
            holder = owners.get(path)
            if holder is not None and holder != unit_id:
                conflicts.append({"path": path, "units": [holder, unit_id]})
            else:
                owners[path] = unit_id
        normalized.append({"id": unit_id, "role": role, "write_paths": paths})

    if len(write_units) > wait_policy["max_write_channels"]:
        errors.append(
            "write channels "
            f"{len(write_units)} exceed the cap of {wait_policy['max_write_channels']}: "
            f"{', '.join(write_units)}"
        )

    return {
        "ok": not errors and not conflicts,
        "units": normalized,
        "write_channels": len(write_units),
        "read_only_units": len(normalized) - len(write_units),
        "conflicts": conflicts,
        "errors": errors,
        "max_write_channels": wait_policy["max_write_channels"],
    }


def find_forbidden_commands(commands: Iterable[str]) -> list[dict[str, str]]:
    """Return every delegated command that has repository-wide side effects."""
    findings: list[dict[str, str]] = []
    for command in commands:
        text = str(command)
        for name, pattern in FORBIDDEN_COMMAND_PATTERNS:
            if re.search(pattern, text, flags=re.IGNORECASE):
                findings.append({"rule": name, "command": text})
        if _is_full_suite_pytest(text):
            findings.append({"rule": "full-suite-gate", "command": text})
    return findings


def classify_marker(marker: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one completion marker written by a subagent."""
    status = str(marker.get("status") or "").strip().lower()
    errors: list[str] = []
    if status not in TERMINAL_STATUSES | NON_TERMINAL_STATUSES:
        errors.append(f"unknown status: {status!r}")
    changed_files = marker.get("changed_files")
    if changed_files is None:
        errors.append("changed_files is required")
        changed_files = []
    elif isinstance(changed_files, str) or not isinstance(changed_files, Sequence):
        errors.append("changed_files must be a list")
        changed_files = []
    if status in TERMINAL_STATUSES and not marker.get("finished_at"):
        errors.append("finished_at is required for a terminal status")
    return {
        "task_id": str(marker.get("task_id") or "").strip(),
        "role": str(marker.get("role") or "").strip(),
        "status": status,
        "terminal": status in TERMINAL_STATUSES,
        "changed_files": [_normalize_path(str(p)) for p in changed_files],
        "errors": errors,
    }


def _last_activity_seconds(marker: Mapping[str, Any]) -> float | None:
    for key in ("progress_at", "finished_at", "started_at"):
        value = marker.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def decide_wait(
    markers: Iterable[Mapping[str, Any]],
    *,
    now_epoch: float,
    start_epoch: float,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Decide what a lead should do while subagents are in flight.

    ``return``   - at least one unit reached a terminal state; collect it now.
    ``timeout``  - the hard limit elapsed; stop waiting and reconcile.
    ``stall``    - no unit updated its marker for ``stall_seconds``; treat as
                   suspect and inspect before waiting again.
    ``continue`` - keep waiting.
    ``no-marks`` - nothing was dispatched; the caller has a bookkeeping bug.
    """
    wait_policy = normalize_wait_policy(policy)
    elapsed = max(0.0, float(now_epoch) - float(start_epoch))

    terminal: list[dict[str, Any]] = []
    running: list[dict[str, Any]] = []
    newest_activity: float | None = None
    for raw in markers:
        if not isinstance(raw, Mapping):
            continue
        info = classify_marker(raw)
        activity = _last_activity_seconds(raw)
        if activity is not None and (newest_activity is None or activity > newest_activity):
            newest_activity = activity
        entry = {
            "task_id": info["task_id"],
            "role": info["role"],
            "status": info["status"],
            "changed_files": info["changed_files"],
            "errors": info["errors"],
            "active_seconds": round(max(0.0, float(now_epoch) - activity), 1) if activity else None,
        }
        if info["terminal"]:
            terminal.append(entry)
        else:
            running.append(entry)

    if not terminal and not running:
        return {
            "action": "no-marks",
            "elapsed_seconds": round(elapsed, 1),
            "terminal": [],
            "running": [],
            "stalled_seconds": 0.0,
        }

    idle = (
        round(max(0.0, float(now_epoch) - newest_activity), 1)
        if newest_activity is not None
        else round(elapsed, 1)
    )
    result = {
        "action": "continue",
        "elapsed_seconds": round(elapsed, 1),
        "idle_seconds": idle,
        "terminal": terminal,
        "running": running,
        "policy": wait_policy,
    }
    if terminal:
        result["action"] = "return"
    elif elapsed >= wait_policy["hard_limit_seconds"]:
        result["action"] = "timeout"
    elif idle >= wait_policy["stall_seconds"]:
        result["action"] = "stall"
    return result


# ---------------------------------------------------------------------------
# Thin file-system layer used by the lead session.
# ---------------------------------------------------------------------------


def read_markers(status_dir: Path) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    if not status_dir.is_dir():
        return markers
    for path in sorted(status_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        payload.setdefault("task_id", path.stem.split(".")[0])
        payload.setdefault("role", path.stem.split(".")[1] if "." in path.stem else "")
        payload["_path"] = str(path)
        markers.append(payload)
    return markers


def wait_for_markers(
    status_dir: Path,
    *,
    policy: Mapping[str, Any] | None = None,
    sleep: Any = time.sleep,
    clock: Any = time.time,
) -> dict[str, Any]:
    wait_policy = normalize_wait_policy(policy)
    start = clock()
    while True:
        decision = decide_wait(
            read_markers(status_dir),
            now_epoch=clock(),
            start_epoch=start,
            policy=wait_policy,
        )
        if decision["action"] == "no-marks":
            # Dispatch happens before any unit writes its marker; only give up
            # once the grace window proves nothing was ever dispatched.
            if clock() - start >= wait_policy["no_marks_grace_seconds"]:
                return decision
        elif decision["action"] in {"return", "stall", "timeout"}:
            return decision
        sleep(wait_policy["poll_interval_seconds"])


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Subagent dispatch and wait protocol")
    sub = parser.add_subparsers(dest="command", required=True)

    wait_cmd = sub.add_parser("wait", help="wait until a marker reaches a terminal state")
    wait_cmd.add_argument("--status-dir", required=True, type=Path)
    wait_cmd.add_argument("--stall-seconds", type=int, default=DEFAULT_WAIT_POLICY["stall_seconds"])
    wait_cmd.add_argument(
        "--hard-limit-seconds", type=int, default=DEFAULT_WAIT_POLICY["hard_limit_seconds"]
    )
    wait_cmd.add_argument(
        "--poll-interval-seconds", type=int, default=DEFAULT_WAIT_POLICY["poll_interval_seconds"]
    )
    wait_cmd.add_argument(
        "--no-marks-grace-seconds",
        type=int,
        default=DEFAULT_WAIT_POLICY["no_marks_grace_seconds"],
    )
    wait_cmd.add_argument("--json", action="store_true")

    plan_cmd = sub.add_parser("plan", help="validate a dispatch plan before starting units")
    plan_cmd.add_argument("--file", required=True, type=Path)
    plan_cmd.add_argument("--max-write-channels", type=int, default=DEFAULT_WAIT_POLICY["max_write_channels"])
    plan_cmd.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "wait":
        policy = {
            "stall_seconds": args.stall_seconds,
            "hard_limit_seconds": args.hard_limit_seconds,
            "poll_interval_seconds": args.poll_interval_seconds,
            "max_write_channels": DEFAULT_WAIT_POLICY["max_write_channels"],
            "no_marks_grace_seconds": args.no_marks_grace_seconds,
        }
        decision = wait_for_markers(args.status_dir, policy=policy)
        print(json.dumps(decision, ensure_ascii=False, indent=2))
        return 0 if decision["action"] == "return" else 2

    payload = json.loads(args.file.read_text(encoding="utf-8-sig"))
    units = payload.get("units") if isinstance(payload, dict) else payload
    report = validate_dispatch_plan(
        units or [],
        policy={"max_write_channels": args.max_write_channels},
    )
    forbidden = find_forbidden_commands(payload.get("commands", []) if isinstance(payload, dict) else [])
    report["forbidden_commands"] = forbidden
    report["ok"] = report["ok"] and not forbidden
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main())
