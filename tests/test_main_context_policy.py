import pytest

from tools.agents.main_context_policy import (
    DEFAULT_MAIN_CONTEXT_POLICY,
    classify_context,
    estimate_excess_tokens,
    normalize_policy,
    summarize_records,
)


def test_default_policy_has_approved_main_thresholds():
    policy = normalize_policy(None)

    assert policy == DEFAULT_MAIN_CONTEXT_POLICY
    assert policy["soft_waterline_tokens"] == 150_000
    assert policy["handoff_trigger_tokens"] == 180_000
    assert policy["hard_guard_tokens"] == 200_000
    assert policy["uncached_increment_trigger_tokens"] == 20_000
    assert policy["large_tool_output_chars"] == 8_192


def test_policy_rejects_non_monotonic_or_non_positive_thresholds():
    with pytest.raises(ValueError, match="monotonic"):
        normalize_policy(
            {
                "soft_waterline_tokens": 180_000,
                "handoff_trigger_tokens": 150_000,
                "hard_guard_tokens": 200_000,
            }
        )

    with pytest.raises(ValueError, match="positive"):
        normalize_policy({"hard_guard_tokens": 0})


def test_context_levels_are_soft_then_handoff_then_hard_guard():
    assert classify_context(149_999)["level"] == "green"
    assert classify_context(150_000)["level"] == "monitor"
    assert classify_context(180_000)["level"] == "handoff"
    assert classify_context(200_000)["level"] == "hard-guard"


def test_phase_boundary_can_request_handoff_before_180k():
    result = classify_context(160_000, phase_boundary=True)

    assert result["level"] == "monitor"
    assert result["should_handoff"] is True
    assert "phase-boundary" in result["reasons"]
    assert result["should_stop"] is False


def test_uncached_large_output_and_browser_payload_trigger_handoff():
    result = classify_context(
        140_000,
        uncached_increment=20_000,
        tool_output_chars=8_192,
        browser_payload=True,
    )

    assert result["level"] == "green"
    assert result["should_handoff"] is True
    assert result["should_stop"] is False
    assert result["reasons"] == [
        "uncached-increment",
        "large-tool-output",
        "browser-payload",
    ]


def test_hard_guard_stops_new_context_accumulation():
    result = classify_context(210_000)

    assert result["level"] == "hard-guard"
    assert result["should_handoff"] is True
    assert result["should_stop"] is True
    assert result["action"] == "start-new-micro-session"


def test_estimate_excess_tokens_is_a_counterfactual_only():
    assert estimate_excess_tokens([100_000, 150_000, 210_000], 150_000) == 60_000


def test_summarize_records_reports_crossings_and_counterfactual_savings():
    summary = summarize_records(
        [
            {"record": 1, "raw_input_tokens": 120_000},
            {"record": 2, "raw_input_tokens": 180_000},
            {"record": 3, "raw_input_tokens": 210_000},
        ]
    )

    assert summary["record_count"] == 3
    assert summary["max_input_tokens"] == 210_000
    assert summary["counts"] == {
        "green": 1,
        "monitor": 0,
        "handoff": 1,
        "hard-guard": 1,
    }
    assert summary["first_handoff_record"] == 2
    assert summary["first_hard_guard_record"] == 3
    assert summary["estimated_excess_at_handoff"] == 30_000
