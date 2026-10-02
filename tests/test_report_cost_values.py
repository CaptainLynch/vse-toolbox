# -*- coding: utf-8 -*-
"""core/report_cost_values：NCR 费用四指标解析/求和单源契约（G34）。"""

from __future__ import annotations

import pytest

from core.report_cost_values import (
    COST_METRIC_LABELS,
    NCR_COST_LABELS,
    cost_note_segments,
    format_cost_amount,
    parse_cost_value,
    sum_cost_metrics,
)
from services.deliverable_form_analysis import _number


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, None),
        (False, None),
        (3, 3.0),
        (-2.5, -2.5),
        ("3", 3.0),
        (" -4.50 ", -4.5),
        ("+7", 7.0),
        ("1,234.5", 1234.5),
        ("12,34,56", 123456.0),
        ("1e3", 1000.0),
        ("", None),
        ("   ", None),
        ("abc", None),
        ("12 万", None),
    ],
)
def test_parse_cost_value_matches_legacy_number_bit_for_bit(
    value: object,
    expected: float | None,
) -> None:
    """与 analysis 历史 ``_number`` 逐位同语义（含带符号/千分位/非数）。"""
    assert parse_cost_value(value) == expected
    assert parse_cost_value(value) == _number(value)


def test_cost_labels_match_analysis_constants_shape() -> None:
    """六字段标签（含「实际」列）键形不变：标签即行键，禁止改写括号形态。"""
    assert NCR_COST_LABELS["investment"]["estimate"] == "测算工程工装费用(万元)"
    assert NCR_COST_LABELS["investment"]["approved"] == "批准工程工装费用（万元）"
    assert NCR_COST_LABELS["investment"]["actual"] == "实际工程工装费用(万元)"
    assert NCR_COST_LABELS["vehicleChange"]["estimate"] == "测算单件成本变化（元）"
    assert NCR_COST_LABELS["vehicleChange"]["approved"] == "批准单件成本变化（元）"
    assert NCR_COST_LABELS["vehicleChange"]["actual"] == "实际单件成本变化（元）"
    assert [metric for metric, _label, _unit in COST_METRIC_LABELS] == [
        "investmentEstimate",
        "investmentApproved",
        "vehicleChangeEstimate",
        "vehicleChangeApproved",
    ]


def test_sum_cost_metrics_keeps_none_distinct_from_zero() -> None:
    rows = [
        {
            "测算工程工装费用(万元)": "1,234.5",
            "批准工程工装费用（万元）": "0",
            "测算单件成本变化（元）": "-50.5",
        },
        {
            "测算工程工装费用(万元)": "10.5",
            "测算单件成本变化（元）": "60",
            "批准单件成本变化（元）": "-0.4",
        },
        {"测算工程工装费用(万元)": "不是数字"},
        "非 Mapping 行一致跳过",
    ]
    totals = sum_cost_metrics(rows)
    assert totals["investmentEstimate"] == {"sum": 1245.0, "count": 2}
    assert totals["investmentApproved"] == {"sum": 0.0, "count": 1}
    assert totals["vehicleChangeEstimate"] == {"sum": 9.5, "count": 2}
    assert totals["vehicleChangeApproved"] == {"sum": -0.4, "count": 1}
    # 全部无值 → sum=None（与「0」可区分）。
    assert sum_cost_metrics([{}])["investmentEstimate"] == {"sum": None, "count": 0}
    assert sum_cost_metrics([]) == {
        metric: {"sum": None, "count": 0}
        for metric, _label, _unit in COST_METRIC_LABELS
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1234.5, "1234.5"),
        (12.0, "12"),
        (-300.0, "-300"),
        (1.25, "1.25"),
        (12.50, "12.5"),
        (10.10, "10.1"),
        (0.0, "0"),
        (2.674, "2.67"),
    ],
)
def test_format_cost_amount_strips_trailing_zeros(value: float, expected: str) -> None:
    assert format_cost_amount(value) == expected


def test_cost_note_segments_order_units_and_zero_count_omission() -> None:
    rows = [
        {"测算工程工装费用(万元)": "1000", "批准工程工装费用（万元）": "800.50"},
        {"测算工程工装费用(万元)": "1000", "测算单件成本变化（元）": "9.5"},
        {},
    ]
    segments = cost_note_segments(rows, total_count=3)
    assert segments == [
        "测算工程工装费用合计 2000 万元（有值 2/3 条）",
        "批准工程工装费用合计 800.5 万元（有值 1/3 条）",
        "测算单件成本变化合计 9.5 元（有值 1/3 条）",
    ]
    # 批准单件成本变化全无值 → 该段省略；顺序固定为四指标定义序。
    assert len(segments) == 3
    assert cost_note_segments([], total_count=5) == []
