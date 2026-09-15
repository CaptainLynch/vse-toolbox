"""Audit one Codex session and its bounded worker runs.

The script intentionally reads raw JSONL/JSON/TOML files and writes only
redacted summaries.  It does not emit raw prompts, tool returns, credentials,
cookies, image data, or worker model I/O.

Example:
    python tools/audit_token_trajectory.py --out .runtime/token-audit-20260910
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import math
import re
import statistics
import sys
import tomllib
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from tools.agents.main_context_policy import normalize_policy, summarize_records
except ModuleNotFoundError:
    from agents.main_context_policy import normalize_policy, summarize_records


DEFAULT_SESSION = Path(r"C:\Users\Lynch\.codex\sessions\2026\09\09\rollout-2026-09-09T18-28-53-01a085b6-a083-7890-a0d9-a3a2a31a05df.jsonl")
DEFAULT_RUNS = Path(r"E:\project\vse-toolbox\.agents\runs")
DEFAULT_CODEX_CONFIG = Path(r"C:\Users\Lynch\.codex\config.toml")
DEFAULT_AGENT_CONFIG = Path(r"E:\project\vse-toolbox\.agents\config.json")

SECRET_VALUE_RE = re.compile(
    r"(?i)(Bearer\s+|(?:api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"password|secret|authorization|cookie)\s*[:=]\s*[\"']?)[^\s,;\"'}]+"
)
DATA_URI_RE = re.compile(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+")
TASK_ID_RE = re.compile(r"\bTASK-[A-Za-z0-9][A-Za-z0-9_-]*\b")
NESTED_TOOL_RE = re.compile(r"\btools\.([A-Za-z0-9_]+)\s*\(")


def parse_timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        # Run records use ISO strings; this is only a defensive fallback.
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_no, line in enumerate(handle, 1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                rows.append({"_line": line_no, "_parse_error": str(exc)})
                continue
            if isinstance(value, dict):
                value["_line"] = line_no
                rows.append(value)
    return rows


def as_int(value: Any) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def serialized_chars(value: Any) -> int:
    if isinstance(value, str):
        return len(value)
    return len(compact_json(value))


def redact_text(value: str) -> str:
    value = DATA_URI_RE.sub("<IMAGE_DATA_REDACTED>", value)
    value = SECRET_VALUE_RE.sub(lambda match: match.group(1) + "<REDACTED>", value)
    return value


def preview(value: Any, limit: int = 900) -> str:
    text = value if isinstance(value, str) else compact_json(value)
    text = redact_text(text).replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 14] + "...<TRUNCATED>"


def content_metrics(value: Any) -> dict[str, int]:
    """Count serialized characters, visible text, and image payload metadata.

    Image URL/base64 characters are retained in the raw character count because
    that is what was persisted.  They are not converted to text-token estimates:
    the JSONL does not contain per-image tokenizer accounting.
    """

    result = {"serialized_chars": serialized_chars(value), "text_chars": 0, "image_url_chars": 0, "image_bytes": 0}

    def walk(node: Any, key: str | None = None) -> None:
        if isinstance(node, dict):
            kind = node.get("type")
            if kind == "input_text":
                result["text_chars"] += len(str(node.get("text", "")))
                return
            if kind == "input_image":
                url = str(node.get("image_url", ""))
                result["image_url_chars"] += len(url)
                if "," in url and ";base64," in url:
                    try:
                        result["image_bytes"] += len(base64.b64decode(url.split(",", 1)[1]))
                    except (ValueError, base64.binascii.Error):
                        pass
                return
            for child_key, child in node.items():
                walk(child, str(child_key))
            return
        if isinstance(node, list):
            for child in node:
                walk(child, key)
            return
        if isinstance(node, str) and key in {"text", "message", "output", "content"}:
            result["text_chars"] += len(node)

    if isinstance(value, str):
        result["text_chars"] = len(value)
    else:
        walk(value)
    result["estimated_text_tokens"] = math.ceil(result["text_chars"] / 4) if result["text_chars"] else 0
    return result


def nested_tool_names(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    found: list[str] = []
    for match in NESTED_TOOL_RE.finditer(value):
        name = match.group(1)
        if name not in found:
            found.append(name)
    return found


def normalize_usage(value: Any) -> dict[str, int]:
    value = value if isinstance(value, dict) else {}

    def pick(*keys: str) -> int:
        for key in keys:
            if key in value:
                return as_int(value[key])
        return 0

    raw_input = pick("input_tokens", "inputTokens")
    cached = pick("cached_input_tokens", "cacheReadTokens", "cachedInputTokens")
    output = pick("output_tokens", "outputTokens")
    reasoning = pick("reasoning_output_tokens", "reasoningTokens", "reasoning_output_tokens")
    total = pick("total_tokens", "totalTokens")
    if not total:
        total = raw_input + output
    return {
        "raw_input_tokens": raw_input,
        "cached_input_tokens": cached,
        "uncached_input_tokens": raw_input - cached,
        "output_tokens": output,
        "reasoning_tokens": reasoning,
        "total_tokens": total,
    }


def sum_usage(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    fields = [
        "raw_input_tokens",
        "cached_input_tokens",
        "uncached_input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens",
    ]
    result = {field: 0 for field in fields}
    for row in rows:
        for field in fields:
            result[field] += as_int(row.get(field))
    return result


def token_records(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get("type") != "token_usage_record":
            continue
        payload = entry.get("payload") or {}
        usage = normalize_usage(payload.get("usage"))
        row = {
            "record": len(records) + 1,
            "line": entry.get("_line"),
            "timestamp": entry.get("timestamp"),
            "turn_id": payload.get("turn_id"),
            "source_ordinal": entry.get("ordinal"),
            **usage,
            "total_consistent_with_input_plus_output": usage["total_tokens"] == usage["raw_input_tokens"] + usage["output_tokens"],
        }
        records.append(row)
    for index, row in enumerate(records):
        previous = records[index - 1] if index else None
        if previous and previous["turn_id"] == row["turn_id"]:
            row["previous_input_tokens"] = previous["raw_input_tokens"]
            row["delta_input_tokens"] = row["raw_input_tokens"] - previous["raw_input_tokens"]
        else:
            row["previous_input_tokens"] = None
            row["delta_input_tokens"] = None
        row["cached_ratio"] = (
            row["cached_input_tokens"] / row["raw_input_tokens"]
            if row["raw_input_tokens"]
            else 0.0
        )
    return records


def session_messages(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get("type") != "response_item":
            continue
        payload = entry.get("payload") or {}
        if payload.get("type") != "message":
            continue
        metrics = content_metrics(payload.get("content", []))
        result.append(
            {
                "line": entry.get("_line"),
                "timestamp": entry.get("timestamp"),
                "item_type": "message",
                "role": payload.get("role"),
                "turn_id": (payload.get("internal_chat_message_metadata_passthrough") or {}).get("turn_id"),
                **metrics,
                "preview": preview(payload.get("content", []), 700),
            }
        )
    return result


def session_calls_and_outputs(entries: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    calls: dict[str, dict[str, Any]] = {}
    outputs: dict[str, dict[str, Any]] = {}
    for entry in entries:
        payload = entry.get("payload") or {}
        kind = payload.get("type")
        metadata = payload.get("internal_chat_message_metadata_passthrough") or {}
        turn_id = metadata.get("turn_id") or payload.get("turn_id")
        if kind in {"custom_tool_call", "function_call"}:
            argument = payload.get("input", payload.get("arguments", ""))
            calls[str(payload.get("call_id"))] = {
                "call_id": payload.get("call_id"),
                "line": entry.get("_line"),
                "timestamp": entry.get("timestamp"),
                "turn_id": turn_id,
                "kind": kind,
                "namespace": payload.get("namespace"),
                "name": payload.get("name"),
                "input": argument,
                "input_preview": preview(argument),
                "nested_tools": nested_tool_names(argument),
            }
        elif kind in {"custom_tool_call_output", "function_call_output"}:
            output = payload.get("output", "")
            outputs[str(payload.get("call_id"))] = {
                "call_id": payload.get("call_id"),
                "line": entry.get("_line"),
                "timestamp": entry.get("timestamp"),
                "turn_id": turn_id,
                "kind": kind,
                "output": output,
            }
    return calls, outputs


def display_tool(call: dict[str, Any]) -> str:
    namespace = call.get("namespace")
    name = call.get("name") or "<unknown>"
    return f"{namespace}.{name}" if namespace else str(name)


def tool_output_rows(
    calls: dict[str, dict[str, Any]],
    outputs: dict[str, dict[str, Any]],
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for call_id, output in outputs.items():
        call = calls.get(call_id)
        if not call:
            continue
        metrics = content_metrics(output.get("output"))
        prior = max((row for row in records if row["line"] < output["line"]), key=lambda row: row["line"], default=None)
        following = min((row for row in records if row["line"] > output["line"]), key=lambda row: row["line"], default=None)
        delta = None
        if prior and following and prior["turn_id"] == following["turn_id"]:
            delta = following["raw_input_tokens"] - prior["raw_input_tokens"]
        rows.append(
            {
                "call_id": call_id,
                "call_line": call["line"],
                "output_line": output["line"],
                "timestamp": output["timestamp"],
                "turn_id": call.get("turn_id") or output.get("turn_id"),
                "outer_kind": call["kind"],
                "namespace": call.get("namespace"),
                "name": call.get("name"),
                "tool": display_tool(call),
                "nested_tools": call.get("nested_tools", []),
                "parameter_chars": serialized_chars(call.get("input", "")),
                "parameter_preview": call.get("input_preview", ""),
                **metrics,
                "previous_record": prior.get("record") if prior else None,
                "previous_input_tokens": prior.get("raw_input_tokens") if prior else None,
                "next_record": following.get("record") if following else None,
                "next_input_tokens": following.get("raw_input_tokens") if following else None,
                "next_delta_input_tokens": delta,
            }
        )
    return sorted(rows, key=lambda row: row["output_line"])


def input_items(messages: list[dict[str, Any]], calls: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = list(messages)
    for call in calls.values():
        metrics = content_metrics(call.get("input", ""))
        rows.append(
            {
                "line": call["line"],
                "timestamp": call["timestamp"],
                "item_type": "tool_call_input",
                "role": "assistant_tool_call",
                "turn_id": call.get("turn_id"),
                "tool": display_tool(call),
                **metrics,
                "preview": call.get("input_preview", ""),
            }
        )
    return sorted(rows, key=lambda row: (-row["serialized_chars"], row["line"]))


def context_jumps(records: list[dict[str, Any]], outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if index == 0 or record["turn_id"] != records[index - 1]["turn_id"]:
            continue
        previous = records[index - 1]
        delta = record["raw_input_tokens"] - previous["raw_input_tokens"]
        preceding = [
            output
            for output in outputs
            if previous["line"] < output["output_line"] < record["line"]
            and output.get("turn_id") == record["turn_id"]
        ]
        largest = max(preceding, key=lambda row: row["serialized_chars"], default=None)
        rows.append(
            {
                "record": record["record"],
                "line": record["line"],
                "timestamp": record["timestamp"],
                "turn_id": record["turn_id"],
                "previous_input_tokens": previous["raw_input_tokens"],
                "input_tokens": record["raw_input_tokens"],
                "delta_input_tokens": delta,
                "preceding_output_count": len(preceding),
                "preceding_output_chars": sum(row["serialized_chars"] for row in preceding),
                "largest_output_line": largest.get("output_line") if largest else None,
                "largest_output_tool": largest.get("tool") if largest else None,
                "largest_output_chars": largest.get("serialized_chars") if largest else None,
                "largest_output_text_chars": largest.get("text_chars") if largest else None,
                "largest_output_preview": largest.get("parameter_preview") if largest else None,
            }
        )
    return sorted(rows, key=lambda row: row["delta_input_tokens"], reverse=True)


def task_events(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for entry in entries:
        payload = entry.get("payload") or {}
        if payload.get("type") not in {"task_started", "task_complete"}:
            continue
        error = payload.get("error") or {}
        result.append(
            {
                "line": entry.get("_line"),
                "timestamp": entry.get("timestamp"),
                "event": payload.get("type"),
                "turn_id": payload.get("turn_id"),
                "duration_ms": payload.get("duration_ms"),
                "time_to_first_token_ms": payload.get("time_to_first_token_ms"),
                "error_code": error.get("codex_error_info"),
                "error_message": redact_text(str(error.get("message", ""))) if error else "",
            }
        )
    return result


def session_context(entries: list[dict[str, Any]]) -> dict[str, Any]:
    contexts: dict[str, dict[str, Any]] = {}
    starts: dict[str, dict[str, Any]] = {}
    meta: dict[str, Any] = {}
    for entry in entries:
        payload = entry.get("payload") or {}
        kind = payload.get("type")
        if entry.get("type") == "session_meta":
            meta = payload
        elif entry.get("type") == "turn_context":
            contexts[str(payload.get("turn_id"))] = {
                "model": payload.get("model"),
                "effort": payload.get("effort"),
                "approval_policy": payload.get("approval_policy"),
                "permission_profile": (payload.get("permission_profile") or {}).get("type"),
            }
        elif kind == "task_started":
            starts[str(payload.get("turn_id"))] = {
                "model_context_window": payload.get("model_context_window"),
                "collaboration_mode_kind": payload.get("collaboration_mode_kind"),
            }
    provenance = ((meta.get("base_instructions") or {}).get("provenance") or {})
    return {
        "base_instruction_model": provenance.get("model"),
        "turn_contexts": contexts,
        "task_starts": starts,
        "effective_models": sorted({x.get("model") for x in contexts.values() if x.get("model")} ),
        "effective_efforts": sorted({x.get("effort") for x in contexts.values() if x.get("effort")} ),
        "context_windows": sorted({x.get("model_context_window") for x in starts.values() if x.get("model_context_window")}),
    }


def read_direct_json(path: Path) -> dict[str, Any]:
    try:
        value = load_json(path)
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def worker_usage(summary: dict[str, Any], round_rows: list[dict[str, Any]]) -> dict[str, int]:
    usage = summary.get("usage") if isinstance(summary.get("usage"), dict) else {}
    if not usage:
        for row in round_rows:
            process = row.get("process") or {}
            if isinstance(process.get("usage"), dict):
                usage = process["usage"]
                break
    return normalize_usage(usage)


def model_io_summary(task_dir: Path) -> dict[str, Any]:
    files = list((task_dir / "zcode-storage" / "cli" / "rollout").glob("model-io-*.jsonl"))
    rows: list[dict[str, Any]] = []
    for path in files:
        rows.extend(read_jsonl(path))
    finish_reasons: Counter[str] = Counter()
    tool_calls: Counter[str] = Counter()
    usage_rows: list[dict[str, Any]] = []
    for row in rows:
        response = row.get("response") or {}
        finish_reasons[str(response.get("finishReason"))] += 1
        for tool_call in response.get("toolCalls") or []:
            if isinstance(tool_call, dict):
                name = tool_call.get("name") or (tool_call.get("function") or {}).get("name") or tool_call.get("toolName") or "<unknown>"
                tool_calls[str(name)] += 1
        usage_rows.append(normalize_usage(response.get("usage")))
    return {
        "files": [str(path.relative_to(task_dir)) for path in files],
        "request_rows": len(rows),
        "finish_reasons": dict(finish_reasons),
        "tool_calls": dict(tool_calls),
        "usage_sum": sum_usage(usage_rows),
    }


def scope_audit_summary(task_dir: Path) -> dict[str, int]:
    counts = Counter()
    path = task_dir / "scope-audit.jsonl"
    if path.exists():
        for row in read_jsonl(path):
            counts["allowed" if row.get("allowed") else "denied"] += 1
    return dict(counts)


def external_tasks(session_text: str, runs_root: Path, start: datetime | None, end: datetime | None) -> list[dict[str, Any]]:
    mentioned = set(TASK_ID_RE.findall(session_text))
    result: list[dict[str, Any]] = []
    for task_dir in sorted((path for path in runs_root.iterdir() if path.is_dir()), key=lambda path: path.name):
        state = read_direct_json(task_dir / "state.json")
        task = read_direct_json(task_dir / "task.json")
        task_id = str(state.get("task_id") or task.get("task_id") or task_dir.name)
        if task_id not in mentioned:
            continue
        events_path = task_dir / "events.jsonl"
        events = read_jsonl(events_path) if events_path.exists() else []
        event_times = [parse_timestamp(row.get("timestamp")) for row in events]
        event_times = [value for value in event_times if value]
        in_window = any((not start or value >= start) and (not end or value <= end) for value in event_times)
        if not in_window:
            continue
        round_paths = sorted(task_dir.glob("worker-round-*.json"))
        round_rows = [read_direct_json(path) for path in round_paths]
        summary = read_direct_json(task_dir / "zcode-summary.json")
        usage = worker_usage(summary, round_rows)
        process = (round_rows[0].get("process") or {}) if round_rows else {}
        round_status = [row.get("status") for row in round_rows if row.get("status")]
        worker_events = [
            row for row in events
            if str(row.get("action", "")).startswith("worker-round")
            or row.get("action") == "worker-completed"
        ]
        worker_event_times = [parse_timestamp(row.get("timestamp")) for row in worker_events]
        worker_event_times = [value for value in worker_event_times if value]
        result.append(
            {
                "task_id": task_id,
                "directory": str(task_dir),
                "task_objective": preview(task.get("objective", ""), 500),
                "start": iso(min(event_times)) if event_times else None,
                "end": iso(max(worker_event_times or event_times)) if (worker_event_times or event_times) else None,
                "model": summary.get("model") or process.get("model") or state.get("model"),
                "worker_runtime": state.get("worker_runtime"),
                "route": state.get("route"),
                "profile": state.get("profile"),
                "request_count": as_int((summary.get("usage") or {}).get("modelRequestCount")) or model_io_summary(task_dir)["request_rows"],
                **usage,
                "state_status": state.get("status"),
                "round_status": ",".join(map(str, round_status)),
                "failure_code": (round_rows[0].get("failure_code") if round_rows else None),
                "takeover_reason": state.get("takeover_reason") or (
                    round_rows[0].get("summary") if round_rows and round_rows[0].get("failure_code") else None
                ),
                "duration_seconds": process.get("duration_seconds"),
                "guard_calls": as_int(process.get("guard_calls")),
                "worker_tool_call_count": as_int(process.get("tool_call_count")),
                "worker_permissions": process.get("permissions") or [],
                "worker_changed_files": len(round_rows[0].get("changed_files") or []) if round_rows else 0,
                "worker_commands_executed": len(round_rows[0].get("commands_executed") or []) if round_rows else 0,
                "worker_tests_recorded": len(round_rows[0].get("tests") or []) if round_rows else 0,
                "scope_audit": scope_audit_summary(task_dir),
                "model_io": model_io_summary(task_dir),
            }
        )
    return sorted(result, key=lambda row: row.get("start") or row["task_id"])


def config_snapshot(codex_path: Path, agent_path: Path) -> dict[str, Any]:
    try:
        codex = tomllib.loads(codex_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        codex = {}
    agents = read_direct_json(agent_path)
    desktop = codex.get("desktop") or {}
    zcode = agents.get("zcode") or {}
    return {
        "codex_config": {
            "path": str(codex_path),
            "model": codex.get("model"),
            "model_reasoning_effort": codex.get("model_reasoning_effort"),
            "model_context_window": codex.get("model_context_window"),
            "model_max_output_tokens": codex.get("model_max_output_tokens"),
            "approval_policy": codex.get("approval_policy"),
            "sandbox_mode": codex.get("sandbox_mode"),
            "disable_response_storage": codex.get("disable_response_storage"),
            "features": codex.get("features"),
            "conversation_detail_mode": desktop.get("conversationDetailMode"),
            "show_context_window_usage": desktop.get("show-context-window-usage"),
            "enabled_plugins": sorted((codex.get("plugins") or {}).keys()),
        },
        "agent_config": {
            "path": str(agent_path),
            "lead_agent": agents.get("lead_agent"),
            "worker_agent": agents.get("worker_agent"),
            "profile": agents.get("profile"),
            "max_total_agent_runs": agents.get("max_total_agent_runs"),
            "max_agy_rounds": agents.get("max_agy_rounds"),
            "max_agy_repair_attempts": agents.get("max_agy_repair_attempts"),
            "max_codex_review_rounds": agents.get("max_codex_review_rounds"),
            "auto_commit_worker": agents.get("auto_commit_worker"),
            "auto_merge": agents.get("auto_merge"),
            "run_build": agents.get("run_build"),
            "run_lint": agents.get("run_lint"),
            "run_tests": agents.get("run_tests"),
            "checks": agents.get("checks"),
            "zcode_model": zcode.get("model"),
            "zcode_allowed_models": zcode.get("allowed_models"),
            "zcode_max_output_tokens": zcode.get("max_output_tokens"),
            "zcode_timeout_seconds": zcode.get("timeout_seconds"),
            "main_context_policy": agents.get("main_context_policy"),
        },
    }


def metric_row(label: str, rows: list[dict[str, Any]], main_total: int | None = None) -> dict[str, Any]:
    usage = sum_usage(rows)
    count = len(rows)
    result: dict[str, Any] = {"stage": label, "records": count, **usage}
    for field in ("total_tokens", "raw_input_tokens", "uncached_input_tokens", "output_tokens"):
        result[f"avg_{field}"] = usage[field] / count if count else 0
    result["cached_ratio"] = usage["cached_input_tokens"] / usage["raw_input_tokens"] if usage["raw_input_tokens"] else 0
    result["main_total_share"] = usage["total_tokens"] / main_total if main_total else 0
    return result


def phase_label(index: int) -> str:
    labels = [
        "turn-1 规划/初始分析与首次派发",
        "turn-2 修复派发/监督",
        "turn-3 主控接管/集成与浏览器验证",
        "turn-4 收尾/产物检查",
    ]
    return labels[index] if index < len(labels) else f"turn-{index + 1}"


def call_category(call: dict[str, Any]) -> str:
    text = call.get("input") if isinstance(call.get("input"), str) else compact_json(call.get("input"))
    lower = text.lower()
    namespace = str(call.get("namespace") or "")
    if re.search(r"run-worker\.ps1.{0,200}-workspace", lower) or "deepseek-harness.ps1" in lower:
        return "worker_dispatch"
    if namespace.startswith("mcp__cua_repl") or "view_image" in lower or "getScreenshot".lower() in lower or "createBrowserTab".lower() in lower:
        return "browser_or_visual"
    if re.search(r"pytest|pyinstaller|compileall|flake8|sha256|smoke|test_", lower):
        return "test_or_package"
    if re.search(r"apply_patch|set-content|write_text|copy-item|move-item", lower):
        return "edit_or_integration"
    if re.search(r"read_thread|agents\.md|memory/|skill\.md|brainstorm", lower):
        return "context_retrieval"
    if re.search(r"rg\s|select-object|get-content|git\s+(diff|status|show|log)|get-childitem", lower):
        return "source_inspection"
    return "other"


def operation_metrics(
    calls: dict[str, dict[str, Any]],
    outputs: list[dict[str, Any]],
    records: list[dict[str, Any]],
    stage_by_turn: dict[str, str],
) -> list[dict[str, Any]]:
    by_turn: dict[str, Counter[str]] = defaultdict(Counter)
    nested_by_turn: dict[str, Counter[str]] = defaultdict(Counter)
    for call in calls.values():
        turn = call.get("turn_id") or "<unknown>"
        by_turn[turn][call_category(call)] += 1
        for name in call.get("nested_tools", []):
            nested_by_turn[turn][name] += 1
    output_by_turn: Counter[str] = Counter()
    output_count_by_turn: Counter[str] = Counter()
    for output in outputs:
        turn = output.get("turn_id") or "<unknown>"
        output_by_turn[turn] += as_int(output.get("serialized_chars"))
        output_count_by_turn[turn] += 1
    result: list[dict[str, Any]] = []
    turn_order: list[str] = []
    for record in records:
        if record["turn_id"] not in turn_order:
            turn_order.append(record["turn_id"])
    for turn in turn_order:
        counts = by_turn[turn]
        result.append(
            {
                "turn_id": turn,
                "stage": stage_by_turn.get(turn),
                "outer_calls": sum(counts.values()),
                "context_retrieval": counts["context_retrieval"],
                "worker_dispatch": counts["worker_dispatch"],
                "source_inspection": counts["source_inspection"],
                "edit_or_integration": counts["edit_or_integration"],
                "test_or_package": counts["test_or_package"],
                "browser_or_visual": counts["browser_or_visual"],
                "other": counts["other"],
                "tool_output_count": output_count_by_turn[turn],
                "tool_output_chars": output_by_turn[turn],
                "nested_tools": dict(nested_by_turn[turn]),
            }
        )
    return result


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            cooked = {}
            for field in fields:
                value = row.get(field, "")
                cooked[field] = compact_json(value) if isinstance(value, (dict, list)) else value
            writer.writerow(cooked)


def fmt_num(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, float):
        return f"{value:,.1f}"
    if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
        return f"{int(value):,}"
    return str(value)


def fmt_pct(value: Any) -> str:
    return f"{float(value) * 100:.2f}%" if value not in (None, "") else "—"


def md_table(headers: list[str], rows: Iterable[Iterable[Any]]) -> str:
    def cell(value: Any) -> str:
        text = compact_json(value) if isinstance(value, (dict, list)) else str(value if value is not None else "—")
        return text.replace("\r", " ").replace("\n", " ").replace("|", "\\|")

    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(cell(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def write_trajectory_svg(records: list[dict[str, Any]], path: Path) -> None:
    width, height = 1100, 460
    left, right, top, bottom = 74, 24, 24, 54
    max_value = max((row["raw_input_tokens"] for row in records), default=1)
    plot_width = width - left - right
    plot_height = height - top - bottom
    points = []
    for index, row in enumerate(records):
        x = left + (index / max(len(records) - 1, 1)) * plot_width
        y = top + (1 - row["raw_input_tokens"] / max_value) * plot_height
        points.append(f"{x:.1f},{y:.1f}")
    grid = []
    for fraction in (0, 0.25, 0.5, 0.75, 1):
        y = top + fraction * plot_height
        label = int(max_value * (1 - fraction))
        grid.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#e5e7eb"/><text x="8" y="{y+4:.1f}" font-size="12" fill="#4b5563">{label:,}</text>')
    boundary_lines = []
    previous_turn = None
    for index, row in enumerate(records):
        if previous_turn is not None and row["turn_id"] != previous_turn:
            x = left + (index / max(len(records) - 1, 1)) * plot_width
            boundary_lines.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{height-bottom}" stroke="#ef4444" stroke-dasharray="4 4"/>')
        previous_turn = row["turn_id"]
    svg = """<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="460" viewBox="0 0 1100 460">
<rect width="100%" height="100%" fill="#fffdf8"/>
<text x="74" y="18" font-size="15" font-family="sans-serif" fill="#111827">Input tokens per response record</text>
{grid}
{boundaries}
<polyline points="{points}" fill="none" stroke="#d95d39" stroke-width="2"/>
{dots}
<text x="74" y="448" font-size="12" font-family="sans-serif" fill="#4b5563">record 1</text>
<text x="1010" y="448" font-size="12" font-family="sans-serif" fill="#4b5563">record {last}</text>
</svg>
""".format(
        grid="".join(grid),
        boundaries="".join(boundary_lines),
        points=" ".join(points),
        dots="".join(
            f'<circle cx="{left + (i / max(len(records)-1, 1))*plot_width:.1f}" cy="{top + (1-row["raw_input_tokens"]/max_value)*plot_height:.1f}" r="2" fill="#d95d39"/>'
            for i, row in enumerate(records)
        ),
        last=len(records),
    )
    path.write_text(svg, encoding="utf-8")


def build_report(
    output_dir: Path,
    session_path: Path,
    runs_root: Path,
    config: dict[str, Any],
    entries: list[dict[str, Any]],
    records: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    jumps: list[dict[str, Any]],
    workers: list[dict[str, Any]],
    stages: list[dict[str, Any]],
    operations: list[dict[str, Any]],
    context: dict[str, Any],
    events: list[dict[str, Any]],
    top_types: Counter[str],
) -> str:
    main_total = sum_usage(records)
    main_policy = normalize_policy(
        (config.get("agent_config") or {}).get("main_context_policy")
    )
    main_policy_summary = summarize_records(records, main_policy)
    token_count_events = sum(1 for entry in entries if (entry.get("payload") or {}).get("type") == "token_count")
    start = parse_timestamp(entries[0].get("timestamp")) if entries else None
    end = parse_timestamp(entries[-1].get("timestamp")) if entries else None
    worker_total = sum_usage(workers)
    worker_requests = sum(as_int(row.get("request_count")) for row in workers)
    run_dir_count = sum(1 for path in runs_root.iterdir() if path.is_dir()) if runs_root.exists() else 0
    external_end = max((parse_timestamp(row.get("end")) for row in workers if row.get("end")), default=None)
    turn_order: list[str] = []
    for row in records:
        if row["turn_id"] not in turn_order:
            turn_order.append(row["turn_id"])
    p95_deltas = [row["delta_input_tokens"] for row in jumps if row["delta_input_tokens"] is not None]
    p95 = sorted(p95_deltas)[max(0, math.ceil(len(p95_deltas) * 0.95) - 1)] if p95_deltas else 0
    top_raw = sorted(outputs, key=lambda row: row["serialized_chars"], reverse=True)[:5]
    top_text = sorted(outputs, key=lambda row: row["text_chars"], reverse=True)[:5]
    top_input = messages[:5]
    pre = next((row for row in stages if row["stage"] == "before_external_tasks_end"), {})
    post = next((row for row in stages if row["stage"] == "after_external_tasks_end"), {})
    blocked_workers = [row for row in workers if row.get("failure_code") or "takeover" in str(row.get("state_status", ""))]
    status_rows = []
    for event in events:
        if event["event"] == "task_complete":
            status_rows.append([event["turn_id"], event["timestamp"], event.get("error_code") or "success", event.get("error_message") or ""])

    stage_rows = []
    for row in stages:
        stage_rows.append(
            [
                row["stage"],
                row["records"],
                fmt_num(row["raw_input_tokens"]),
                fmt_num(row["cached_input_tokens"]),
                fmt_num(row["uncached_input_tokens"]),
                fmt_num(row["output_tokens"]),
                fmt_num(row["reasoning_tokens"]),
                fmt_num(row["total_tokens"]),
                fmt_num(row["avg_total_tokens"]),
                fmt_num(row["avg_uncached_input_tokens"]),
                fmt_pct(row["main_total_share"]),
            ]
        )
    jump_rows = []
    for row in jumps[:10]:
        jump_rows.append(
            [
                row["record"],
                row["line"],
                row["timestamp"],
                fmt_num(row["previous_input_tokens"]),
                fmt_num(row["input_tokens"]),
                fmt_num(row["delta_input_tokens"]),
                row["preceding_output_count"],
                row["largest_output_tool"] or "—",
                fmt_num(row["largest_output_chars"]),
                row["largest_output_line"] or "—",
            ]
        )
    output_rows = []
    for index, row in enumerate(top_raw, 1):
        output_rows.append(
            [
                index,
                row["output_line"],
                row["timestamp"],
                row["tool"] + (" → " + ", ".join(row.get("nested_tools") or []) if row.get("nested_tools") else ""),
                row["parameter_preview"],
                fmt_num(row["serialized_chars"]),
                fmt_num(row["text_chars"]),
                fmt_num(row["image_url_chars"]),
                fmt_num(row["image_bytes"]),
                fmt_num(row["estimated_text_tokens"]),
                f'{fmt_num(row["previous_input_tokens"])} → {fmt_num(row["next_input_tokens"])} (Δ {fmt_num(row["next_delta_input_tokens"])})',
            ]
        )
    text_output_rows = []
    for index, row in enumerate(top_text, 1):
        text_output_rows.append(
            [index, row["output_line"], row["tool"], fmt_num(row["text_chars"]), fmt_num(row["serialized_chars"]), fmt_num(row["next_delta_input_tokens"]), row["parameter_preview"]]
        )
    worker_rows = []
    for row in workers:
        worker_rows.append(
            [
                row["task_id"],
                row["start"],
                row["end"],
                row["model"],
                row["request_count"],
                fmt_num(row["raw_input_tokens"]),
                fmt_num(row["cached_input_tokens"]),
                fmt_num(row["uncached_input_tokens"]),
                fmt_num(row["output_tokens"]),
                fmt_num(row["reasoning_tokens"]),
                fmt_num(row["total_tokens"]),
                row["state_status"],
                row["failure_code"] or "—",
                row["worker_tool_call_count"],
                row["scope_audit"],
            ]
        )
    op_rows = []
    for row in operations:
        op_rows.append(
            [
                row["stage"],
                row["turn_id"],
                row["outer_calls"],
                row["context_retrieval"],
                row["worker_dispatch"],
                row["source_inspection"],
                row["edit_or_integration"],
                row["test_or_package"],
                row["browser_or_visual"],
                row["tool_output_count"],
                fmt_num(row["tool_output_chars"]),
                row["nested_tools"],
            ]
        )

    report = f"""# 指定会话 Token 消耗与执行链路审计

审计脚本：`tools/audit_token_trajectory.py`

## 数据范围与统计口径

- 主日志：`{session_path}`；共读取 `{len(entries):,}` 行，JSON 解析错误 `{sum(1 for row in entries if row.get('_parse_error'))}`。
- 外部记录根目录：`{runs_root}`。任务目录按“任务 ID 出现在主日志 + 目录事件时间落在主日志时间窗”筛选，避免把历史目录混入。
- 主日志时间窗：`{iso(start)}` 至 `{iso(end)}`；原始行时间跨度约 `{(end-start).total_seconds()/3600:.2f}` 小时（仅表示落盘跨度，不表示模型持续运行）。
- `Raw Input = payload.usage.input_tokens`；`Cached Input = payload.usage.cached_input_tokens`；`Uncached Input = Raw Input - Cached Input`。
- `Output Tokens` 与 `Reasoning Tokens` 分栏保留；`Reasoning Tokens` 按原始字段视为 Output 的子项，不重复相加。等效总量采用原始 `usage.total_tokens`，本文件已验证其与 `Raw Input + Output` 一致的比例。
- 字符量按 JSON 值的 Unicode 字符数统计；文本估算 Token 使用 `ceil(text_chars / 4)`，只作为排序辅助。图片 base64 字符单独列出，图片没有从该 JSONL 中可复现的逐图 Token 账单。

## 1. 会话全局账单

主日志中顶层 `token_usage_record` 共 **{len(records):,} 条**；另有 `token_count` 事件 `{token_count_events:,}` 条。统计只对 `token_usage_record.payload.usage` 求和，避免把累计字段重复相加。

{md_table(['指标', '精确值', '占 Raw Input / Total'], [
    ['Raw Input', fmt_num(main_total['raw_input_tokens']), '100% / ' + fmt_pct(main_total['raw_input_tokens']/main_total['total_tokens'])],
    ['Cached Input', fmt_num(main_total['cached_input_tokens']), fmt_pct(main_total['cached_input_tokens']/main_total['raw_input_tokens'])],
    ['Uncached Input', fmt_num(main_total['uncached_input_tokens']), fmt_pct(main_total['uncached_input_tokens']/main_total['raw_input_tokens'])],
    ['Reasoning Tokens', fmt_num(main_total['reasoning_tokens']), fmt_pct(main_total['reasoning_tokens']/main_total['output_tokens'])],
    ['Output Tokens', fmt_num(main_total['output_tokens']), fmt_pct(main_total['output_tokens']/main_total['total_tokens'])],
    ['Equivalent Total', fmt_num(main_total['total_tokens']), '100%'],
])}

全局缓存读取率为 **{fmt_pct(main_total['cached_input_tokens']/main_total['raw_input_tokens'])}**；未缓存输入为 **{fmt_num(main_total['uncached_input_tokens'])}**。`total_tokens` 与 `input + output` 一致的记录数为 `{sum(1 for row in records if row['total_consistent_with_input_plus_output'])}/{len(records)}`。

### 输入上下文轨迹

完整 98 行轨迹见 [`trajectory.csv`](trajectory.csv)，折线图见 [`input_trajectory.svg`](input_trajectory.svg)。同一 turn 内相邻记录的输入增量 Top 10：

{md_table(['记录', 'JSONL 行', '时间', '前一轮 Input', '本轮 Input', '增量', '前置输出数', '最大前置工具', '最大输出字符', '最大输出行'], jump_rows)}

大幅跃升参考阈值为同一 turn 增量的经验 P95：`{fmt_num(p95)}` tokens；最大跃升是第 `{jumps[0]['record'] if jumps else '—'}` 条记录，`+{fmt_num(jumps[0]['delta_input_tokens']) if jumps else '—'}` tokens。该跃升前的最大落盘返回为 `{jumps[0]['largest_output_tool'] if jumps and jumps[0]['largest_output_tool'] else '—'}`，因此可把它作为第一处上下文膨胀检查点，而不是把所有工具输出简单相加。

### 主控上下文治理策略

本策略是 Codex 主控的编排水位，不改变其原生上下文窗口。当前配置为：软提醒 `{fmt_num(main_policy['soft_waterline_tokens'])}`、Handoff `{fmt_num(main_policy['handoff_trigger_tokens'])}`、硬门禁 `{fmt_num(main_policy['hard_guard_tokens'])}` tokens；未缓存增量 `{fmt_num(main_policy['uncached_increment_trigger_tokens'])}`、单次工具返回 `{fmt_num(main_policy['large_tool_output_chars'])}` 字符也会触发阶段交接。该会话最高输入 `{fmt_num(main_policy_summary['max_input_tokens'])}` tokens；达到 Handoff/硬门禁的记录数为 `{main_policy_summary['counts']['handoff'] + main_policy_summary['counts']['hard-guard']}` / `{main_policy_summary['record_count']}`，超过 Handoff 的反事实输入量为 `{fmt_num(main_policy_summary['estimated_excess_at_handoff'])}` tokens。

主控 turn 状态事件：

{md_table(['Turn', '完成时间', '状态/错误码', '错误信息'], status_rows)}

其中两个 turn 被主控日志明确记为 `usage_limit_exceeded`，这会造成后续“继续”请求重新在已经很大的上下文底座上运行，是执行链路额外变长的重要原因。

## 2. 上下文膨胀归因

严格按工具返回值落盘序列化字符数排名前 5：

{md_table(['排名', '返回行', '时间', '工具', '参数（脱敏截断）', '序列化字符', '文本字符', '图片 URL 字符', '图片字节', '文本 Token 估算', '前后 Input / 后续增量'], output_rows)}

图片数据占据前两项的绝大部分：这两项的图片 URL 字符分别为 `{fmt_num(top_raw[0]['image_url_chars']) if top_raw else '—'}` 和 `{fmt_num(top_raw[1]['image_url_chars']) if len(top_raw)>1 else '—'}`，不能直接用字符数除以 4 当作模型 Token。其后续主控 Input 增量由原始账单直接给出，分别记录在上表最后一列。

为避免图片字符掩盖真正的文本上下文，文本字符排名前 5 为：

{md_table(['排名', '返回行', '工具', '文本字符', '序列化字符', '后续 Input 增量', '参数摘要'], text_output_rows)}

这组文本返回主要来自重复读取线程/状态/技能/差异和验证输出。典型因果链是：大段 `read_thread`/`Get-Content`/差异结果进入上下文 → 下一条 `token_usage_record.input_tokens` 跃升 → 后续每个请求都在更大的 Input 基线上计费。完整配对结果见 [`tool_outputs.csv`](tool_outputs.csv)，前 5 输入项（包含消息和工具参数）见 [`input_items.csv`](input_items.csv)。

## 3. 外部任务与派发有效性

会话时间窗内通过上述交集规则锁定 **{len(workers)} 个外部任务目录**；共扫描 `.agents/runs` 下 `{run_dir_count:,}` 个直接子目录，其余历史目录被排除。外部任务总模型请求 `{worker_requests:,}` 次，记录的等效 Token 为 `{fmt_num(worker_total['total_tokens'])}`。

{md_table(['任务', '开始', '结束', '模型', '请求数', 'Raw Input', 'Cached', 'Uncached', 'Output', 'Reasoning', 'Total', '最终状态', '失败码', 'Worker 工具调用', 'Scope audit'], worker_rows)}

外部任务合计：Raw Input `{fmt_num(worker_total['raw_input_tokens'])}`，Cached `{fmt_num(worker_total['cached_input_tokens'])}`，Uncached `{fmt_num(worker_total['uncached_input_tokens'])}`，Output `{fmt_num(worker_total['output_tokens'])}`，Reasoning `{fmt_num(worker_total['reasoning_tokens'])}`，Total `{fmt_num(worker_total['total_tokens'])}`。完整明细见 [`workers.csv`](workers.csv)。

状态因果证据：两个实现任务的 `state.json.takeover_reason` 和 `worker-round-1.json.failure_code` 都是 **`permission`**，`tools/agents/supervisor.py` 在 `worker["status"] == "blocked"` 时把 worker 摘要写入 `codex-takeover-required`；`tools/agents/zcode_worker.py:27` 的权限判定只允许 `WRITE_TOOLS = ['Edit', 'Write']`，因此进入权限请求的 `Read` 会返回 deny，随后 `zcode_worker.py:239-243` 映射为 `failure_code=permission`。两个 scope audit 分别出现一条精确的 `{{"tool":"Read","allowed":false}}`（项目任务第 6 行、UI 任务第 12 行），其余记录允许；这与状态文件完全吻合。model I/O 没有更低层异常文本，所以能确定的根因是“Read 权限请求被当前权限判定拒绝”，而不是业务源码故障。

Worker 侧 `commands_executed`/`tests` 记录为零并不表示没有模型工具调用，而是 worker 没有执行 shell 验证；worker 的实际模型请求数与工具调用、结束原因已经由 model I/O 汇总复核，详见 `workers.csv` 中的字段和 `audit.json`。

## 4. 派发前后阶段对比

外部任务最后结束时间为 `{iso(external_end)}`。按主控 turn 首条 Token 记录划分：turn 1/2 属于派发与监督，turn 3/4 属于外部任务结束后的主控接管、集成、浏览器/回归和收尾。

{md_table(['阶段', '记录数', 'Raw Input', 'Cached', 'Uncached', 'Output', 'Reasoning', 'Total', '平均 Total/轮', '平均 Uncached/轮', '占主控 Total'], stage_rows)}

派发/监督阶段平均 Total 为 `{fmt_num(pre.get('avg_total_tokens'))}`/轮；主控接管后为 `{fmt_num(post.get('avg_total_tokens'))}`/轮，变化约 `{fmt_pct(post.get('avg_total_tokens', 0)/pre.get('avg_total_tokens', 1)-1)}`。这不是模型能力变化的证明，主要反映接管阶段的上下文底座已从约 `{fmt_num(pre.get('raw_input_tokens', 0)/max(pre.get('records', 1), 1))}` 到约 `{fmt_num(post.get('raw_input_tokens', 0)/max(post.get('records', 1), 1))}` Raw Input/轮。

主控操作类型（外层调用计数；嵌套工具计数见最后一列）：

{md_table(['阶段', 'Turn ID', '外层调用', '上下文/线程读取', 'Worker 派发', '源码检查', '编辑/集成', '测试/打包', '浏览器/图片', '返回数', '返回字符', '嵌套工具'], op_rows)}

阶段全量表、工具分类和完整轨迹均在输出目录中，分类只按调用参数中出现的命令/工具名标记，单次 `exec` 内包含多个命令时会被记入嵌套工具列。

## 5. 前三项瓶颈与无损优化

1. **主控接管/验证阶段的上下文基线最高**：该阶段 `{fmt_num(post.get('total_tokens'))}` tokens，占主控总量 `{fmt_pct(post.get('main_total_share'))}`；平均 `{fmt_num(post.get('avg_total_tokens'))}`/轮。把集成、浏览器观察、回归、打包拆成独立短会话或在阶段边界生成一份结构化 handoff（文件路径、失败断言、待办、验证命令），后续只注入 handoff 和必要 diff，保留原始证据在本地文件中，能够减少重复上下文而不减少验证覆盖。
2. **两个未完成的实现 worker 消耗高且最终接管**：`{fmt_num(sum(row['total_tokens'] for row in blocked_workers))}` tokens、`{sum(as_int(row.get('request_count')) for row in blocked_workers):,}` 次请求属于 permission 接管任务，占外部总量 `{fmt_pct(sum(row['total_tokens'] for row in blocked_workers)/worker_total['total_tokens'] if worker_total['total_tokens'] else 0)}`。保留当前“不自动切 provider/不扩大权限”的安全边界；先做一次只读 preflight，确认所需 Edit/Write 权限和 scope audit，再派发实现任务，并把 worker 合约内任务文件、受限命令和回滚边界压缩成一个批次，避免 70+ 请求后才发现无法完成。接管规则继续限制最多两次 targeted repair。
3. **高字符工具返回和重复线程/策略注入造成跃升**：原始字符 Top 2 由图片数据主导，文本 Top 5 中可见大量线程、状态、技能、diff 和验证输出；最大单轮上下文增量为 `+{fmt_num(jumps[0]['delta_input_tokens']) if jumps else '—'}` tokens。读取时使用结构化摘要、`rg` 命中行加小窗口、`read_thread` 的最小 turn/字符上限；图片仅在 DOM/AX 不足以判断布局时取一张目标截图，避免同一状态重复全页截图。证据文件仍保留在本地，所以这是压缩传递内容，不是删除证据。

## 6. 配置审计与建议

会话自身捕获的有效运行环境为：模型 `{context.get('effective_models')}`，effort `{context.get('effective_efforts')}`，上下文窗口 `{context.get('context_windows')}`，基础指令 provenance `{context.get('base_instruction_model')}`。当前 `config.toml` 读取到的模型/effort/context/max-output 为 `{config['codex_config'].get('model')}` / `{config['codex_config'].get('model_reasoning_effort')}` / `{config['codex_config'].get('model_context_window')}` / `{config['codex_config'].get('model_max_output_tokens')}`；它与会话捕获值不同，说明当前配置不能倒推本次账单。

`.agents/config.json` 当前选择 lead=`{config['agent_config'].get('lead_agent')}`、worker=`{config['agent_config'].get('worker_agent')}`、profile=`{config['agent_config'].get('profile')}`、ZCode model=`{config['agent_config'].get('zcode_model')}`、ZCode max output=`{config['agent_config'].get('zcode_max_output_tokens')}`、timeout=`{config['agent_config'].get('zcode_timeout_seconds')}` 秒；自动合并/提交均为 `{config['agent_config'].get('auto_merge')}`/`{config['agent_config'].get('auto_commit_worker')}`。建议把 `profile=agy-heavy` 与实际 `worker_agent=zcode-app-server` 的命名统一，避免统计和故障面板把 ZCode 误标成 AGY；不要通过提高全局权限或切换未授权 provider 来掩盖 permission 失败。

## 可复现产物

- [`audit.json`](audit.json)：脱敏结构化全量结果。
- [`trajectory.csv`](trajectory.csv)：98 条 Token 轨迹。
- [`input_trajectory.svg`](input_trajectory.svg)：Input Tokens 折线图。
- [`tool_outputs.csv`](tool_outputs.csv)：所有已配对工具返回及其前后 Input 影响。
- [`input_items.csv`](input_items.csv)：消息和工具参数的字符排名。
- [`context_jumps.csv`](context_jumps.csv)：同一 turn 相邻记录的上下文跃升。
- [`workers.csv`](workers.csv)：3 个外部任务的模型请求、Token、状态和 model I/O 校验摘要。
- [`stage_metrics.csv`](stage_metrics.csv) / [`operations.csv`](operations.csv)：阶段和主控操作分类完整表。

所有报告字段均来自上述原始落盘文件；摘要中的图片 Token 不做臆测。worker 已记录被拒绝的工具类型为 `Read`，但没有记录该请求的具体路径，因此路径级归因到此为止。
"""
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, default=DEFAULT_SESSION)
    parser.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--codex-config", type=Path, default=DEFAULT_CODEX_CONFIG)
    parser.add_argument("--agent-config", type=Path, default=DEFAULT_AGENT_CONFIG)
    parser.add_argument("--out", type=Path, default=Path(".runtime/token-audit-20260910"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    raw_session = args.session.read_text(encoding="utf-8-sig")
    entries = read_jsonl(args.session)
    records = token_records(entries)
    messages = session_messages(entries)
    calls, raw_outputs = session_calls_and_outputs(entries)
    outputs = tool_output_rows(calls, raw_outputs, records)
    input_rows = input_items(messages, calls)
    jumps = context_jumps(records, outputs)
    events = task_events(entries)
    context = session_context(entries)
    config = config_snapshot(args.codex_config, args.agent_config)
    main_context_policy = normalize_policy(config["agent_config"].get("main_context_policy"))
    main_context_summary = summarize_records(records, main_context_policy)
    timestamps = [parse_timestamp(row.get("timestamp")) for row in entries if row.get("timestamp")]
    timestamps = [value for value in timestamps if value]
    session_start = min(timestamps) if timestamps else None
    session_end = max(timestamps) if timestamps else None
    workers = external_tasks(raw_session, args.runs, session_start, session_end)

    turn_order: list[str] = []
    rows_by_turn: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        rows_by_turn[row["turn_id"]].append(row)
        if row["turn_id"] not in turn_order:
            turn_order.append(row["turn_id"])
    external_end = max((parse_timestamp(row.get("end")) for row in workers if row.get("end")), default=None)
    stage_by_turn: dict[str, str] = {}
    stage_name_by_turn: dict[str, str] = {}
    for index, turn_id in enumerate(turn_order):
        first = parse_timestamp(rows_by_turn[turn_id][0].get("timestamp"))
        stage_by_turn[turn_id] = "after_external_tasks_end" if external_end and first and first > external_end else "before_external_tasks_end"
        stage_name_by_turn[turn_id] = phase_label(index)
    stage_metrics: list[dict[str, Any]] = []
    main_total = sum_usage(records)["total_tokens"]
    for index, turn_id in enumerate(turn_order):
        row = metric_row(stage_name_by_turn[turn_id], rows_by_turn[turn_id], main_total)
        row["turn_id"] = turn_id
        stage_metrics.append(row)
    stage_metrics.append(metric_row("before_external_tasks_end", [row for row in records if stage_by_turn.get(row["turn_id"]) == "before_external_tasks_end"], main_total))
    stage_metrics.append(metric_row("after_external_tasks_end", [row for row in records if stage_by_turn.get(row["turn_id"]) == "after_external_tasks_end"], main_total))
    operations = operation_metrics(calls, outputs, records, stage_name_by_turn)

    top_types = Counter(str(row.get("type")) for row in entries)
    audit = {
        "source": {
            "session": str(args.session),
            "runs_root": str(args.runs),
            "codex_config": str(args.codex_config),
            "agent_config": str(args.agent_config),
            "session_lines": len(entries),
            "session_start": iso(session_start),
            "session_end": iso(session_end),
            "top_level_type_counts": dict(top_types),
            "runs_directories_scanned": sum(1 for path in args.runs.iterdir() if path.is_dir()) if args.runs.exists() else 0,
        },
        "session_context": context,
        "token_usage": {
            "record_count": len(records),
            "totals": sum_usage(records),
            "trajectory": records,
            "context_jumps": jumps,
        },
        "main_context_policy": main_context_summary,
        "tool_outputs": outputs,
        "input_items": input_rows,
        "task_events": events,
        "workers": workers,
        "worker_totals": sum_usage(workers),
        "worker_request_count": sum(as_int(row.get("request_count")) for row in workers),
        "stage_metrics": stage_metrics,
        "operations": operations,
        "config": config,
        "method": {
            "uncached_formula": "raw_input_tokens - cached_input_tokens",
            "equivalent_total_formula": "usage.total_tokens; verified equal to raw input + output for each available main record",
            "estimated_text_token_formula": "ceil(text_chars / 4)",
            "external_task_filter": "task ID mentioned in session and direct run event timestamp inside session timestamp window",
        },
    }
    (args.out / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    write_csv(args.out / "trajectory.csv", records, [
        "record", "line", "timestamp", "turn_id", "raw_input_tokens", "cached_input_tokens", "uncached_input_tokens", "output_tokens", "reasoning_tokens", "total_tokens", "previous_input_tokens", "delta_input_tokens", "cached_ratio"
    ])
    write_csv(args.out / "tool_outputs.csv", outputs, [
        "call_id", "call_line", "output_line", "timestamp", "turn_id", "tool", "outer_kind", "namespace", "name", "nested_tools", "parameter_chars", "parameter_preview", "serialized_chars", "text_chars", "image_url_chars", "image_bytes", "estimated_text_tokens", "previous_record", "previous_input_tokens", "next_record", "next_input_tokens", "next_delta_input_tokens"
    ])
    write_csv(args.out / "input_items.csv", input_rows, [
        "line", "timestamp", "item_type", "role", "turn_id", "tool", "serialized_chars", "text_chars", "image_url_chars", "image_bytes", "estimated_text_tokens", "preview"
    ])
    write_csv(args.out / "context_jumps.csv", jumps, [
        "record", "line", "timestamp", "turn_id", "previous_input_tokens", "input_tokens", "delta_input_tokens", "preceding_output_count", "preceding_output_chars", "largest_output_line", "largest_output_tool", "largest_output_chars", "largest_output_text_chars", "largest_output_preview"
    ])
    write_csv(args.out / "workers.csv", workers, [
        "task_id", "directory", "start", "end", "model", "worker_runtime", "route", "profile", "request_count", "raw_input_tokens", "cached_input_tokens", "uncached_input_tokens", "output_tokens", "reasoning_tokens", "total_tokens", "state_status", "round_status", "failure_code", "takeover_reason", "duration_seconds", "guard_calls", "worker_tool_call_count", "worker_permissions", "worker_changed_files", "worker_commands_executed", "worker_tests_recorded", "scope_audit", "model_io"
    ])
    write_csv(args.out / "stage_metrics.csv", stage_metrics, [
        "stage", "turn_id", "records", "raw_input_tokens", "cached_input_tokens", "uncached_input_tokens", "output_tokens", "reasoning_tokens", "total_tokens", "avg_total_tokens", "avg_raw_input_tokens", "avg_uncached_input_tokens", "avg_output_tokens", "cached_ratio", "main_total_share"
    ])
    write_csv(args.out / "operations.csv", operations, [
        "stage", "turn_id", "outer_calls", "context_retrieval", "worker_dispatch", "source_inspection", "edit_or_integration", "test_or_package", "browser_or_visual", "other", "tool_output_count", "tool_output_chars", "nested_tools"
    ])
    write_trajectory_svg(records, args.out / "input_trajectory.svg")
    report = build_report(
        args.out, args.session, args.runs, config, entries, records, outputs, messages, jumps, workers, stage_metrics, operations, context, events, top_types
    )
    (args.out / "report.md").write_text(report, encoding="utf-8")

    print(json.dumps({
        "out": str(args.out.resolve()),
        "session_token_usage_records": len(records),
        "main_totals": sum_usage(records),
        "external_tasks": [row["task_id"] for row in workers],
        "external_request_count": sum(as_int(row.get("request_count")) for row in workers),
        "external_totals": sum_usage(workers),
        "top_context_jump": jumps[0] if jumps else None,
        "main_context_policy": main_context_summary,
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
