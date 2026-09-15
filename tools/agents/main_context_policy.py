"""Main-controller context governance thresholds.

The policy is an orchestration signal for Codex lead sessions. It does not
change the native Codex context window and it does not impose a total worker
token quota.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


DEFAULT_MAIN_CONTEXT_POLICY: dict[str, int] = {
    "soft_waterline_tokens": 150_000,
    "handoff_trigger_tokens": 180_000,
    "hard_guard_tokens": 200_000,
    "uncached_increment_trigger_tokens": 20_000,
    "large_tool_output_chars": 8_192,
}


def normalize_policy(raw: Mapping[str, Any] | None) -> dict[str, int]:
    """Validate and complete the main-controller policy."""
    policy = dict(DEFAULT_MAIN_CONTEXT_POLICY)
    if raw is not None:
        if not isinstance(raw, Mapping):
            raise ValueError("Main context policy must be an object")
        for key in DEFAULT_MAIN_CONTEXT_POLICY:
            if key not in raw:
                continue
            value = raw[key]
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{key} must be a positive integer")
            policy[key] = value

    for key, value in policy.items():
        if value <= 0:
            raise ValueError(f"{key} must be a positive integer")
    if not (
        policy["soft_waterline_tokens"]
        <= policy["handoff_trigger_tokens"]
        <= policy["hard_guard_tokens"]
    ):
        raise ValueError("Main context thresholds must be monotonic")
    return policy


def classify_context(
    input_tokens: int,
    *,
    uncached_increment: int = 0,
    tool_output_chars: int = 0,
    browser_payload: bool = False,
    phase_boundary: bool = False,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the action for one observed lead request."""
    if isinstance(input_tokens, bool) or not isinstance(input_tokens, int):
        raise ValueError("input_tokens must be a non-negative integer")
    if input_tokens < 0:
        raise ValueError("input_tokens must be a non-negative integer")
    if uncached_increment < 0 or tool_output_chars < 0:
        raise ValueError("context increments cannot be negative")

    limits = normalize_policy(policy)
    reasons: list[str] = []
    if uncached_increment >= limits["uncached_increment_trigger_tokens"]:
        reasons.append("uncached-increment")
    if tool_output_chars >= limits["large_tool_output_chars"]:
        reasons.append("large-tool-output")
    if browser_payload:
        reasons.append("browser-payload")
    if phase_boundary and input_tokens >= limits["soft_waterline_tokens"]:
        reasons.append("phase-boundary")

    if input_tokens >= limits["hard_guard_tokens"]:
        level = "hard-guard"
    elif input_tokens >= limits["handoff_trigger_tokens"]:
        level = "handoff"
    elif input_tokens >= limits["soft_waterline_tokens"]:
        level = "monitor"
    else:
        level = "green"

    should_handoff = level in {"handoff", "hard-guard"} or bool(reasons)
    should_stop = level == "hard-guard"
    if should_stop:
        action = "start-new-micro-session"
    elif should_handoff:
        action = "handoff-after-current-operation"
    elif level == "monitor":
        action = "continue-with-bounded-reads"
    else:
        action = "continue"

    return {
        "input_tokens": input_tokens,
        "level": level,
        "should_handoff": should_handoff,
        "should_stop": should_stop,
        "action": action,
        "reasons": reasons,
        "policy": limits,
    }


def estimate_excess_tokens(samples: Iterable[int], cap: int) -> int:
    """Estimate input above a hypothetical cap for audit comparisons."""
    if isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0:
        raise ValueError("cap must be a positive integer")
    total = 0
    for sample in samples:
        if isinstance(sample, bool) or not isinstance(sample, int) or sample < 0:
            raise ValueError("samples must contain non-negative integers")
        total += max(sample - cap, 0)
    return total


def summarize_records(
    records: Iterable[Mapping[str, Any]],
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize recorded lead inputs without retaining raw conversation data."""
    limits = normalize_policy(policy)
    rows = list(records)
    inputs: list[int] = []
    levels = {"green": 0, "monitor": 0, "handoff": 0, "hard-guard": 0}
    first_handoff: int | None = None
    first_hard_guard: int | None = None

    for index, row in enumerate(rows, 1):
        value = row.get("raw_input_tokens", row.get("input_tokens"))
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("records must contain non-negative input token counts")
        inputs.append(value)
        result = classify_context(value, policy=limits)
        levels[result["level"]] += 1
        record_number = row.get("record", index)
        if result["level"] in {"handoff", "hard-guard"} and first_handoff is None:
            first_handoff = record_number
        if result["level"] == "hard-guard" and first_hard_guard is None:
            first_hard_guard = record_number

    return {
        "record_count": len(rows),
        "max_input_tokens": max(inputs, default=0),
        "counts": levels,
        "first_handoff_record": first_handoff,
        "first_hard_guard_record": first_hard_guard,
        "estimated_excess_at_soft": estimate_excess_tokens(
            inputs, limits["soft_waterline_tokens"]
        ),
        "estimated_excess_at_handoff": estimate_excess_tokens(
            inputs, limits["handoff_trigger_tokens"]
        ),
        "estimated_excess_at_hard_guard": estimate_excess_tokens(
            inputs, limits["hard_guard_tokens"]
        ),
        "policy": limits,
    }
