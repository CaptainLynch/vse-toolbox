# -*- coding: utf-8 -*-
"""NCR 费用四指标的单一解析/求和原语（纯函数、零 I/O、零 services 依赖）。

为什么存在：NCR 明细的费用值同时存在于两种形态——标签键的原始工作簿行
（风险备注摘要、审计取证）与归一化后的 ``row["cost"]`` 分组（看板聚合）。
备注摘要（services/project_status_records）与图表聚合
（services/deliverable_form_analysis）必须共用同一套标签、数值解析与求和
口径，禁止出现第二套实现（TASK-20260930-R7-G34 费用解析单源）。

- 标签常量自 ``services/deliverable_form_analysis`` 原位迁入（analysis 侧以
  旧名引用，历史消费者不受影响）；标签即行键，全角/半角括号保持原样，禁止改写；
- ``parse_cost_value`` 与 analysis 既有数值解析逐位同语义：
  ``None``/布尔 → ``None``；int/float → float；字符串去千分位逗号与首尾
  空白后 ``float()``，空串/非数 → ``None``（带符号，如 ``"-50.5"``、
  ``"1,234.5"``）；
- ``sum_cost_metrics`` 对标签键原始行求四指标合计与有值件数（None≠0），
  全部无值的指标 ``sum=None``（「无批准值」与「0」必须可区分）。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

#: 完整六字段费用标签（含「实际」列）；analysis 历史常量原位迁入，键形不变。
NCR_COST_LABELS: dict[str, dict[str, str]] = {
    "investment": {
        "estimate": "测算工程工装费用(万元)",
        "approved": "批准工程工装费用（万元）",
        "actual": "实际工程工装费用(万元)",
    },
    "vehicleChange": {
        "estimate": "测算单件成本变化（元）",
        "approved": "批准单件成本变化（元）",
        "actual": "实际单件成本变化（元）",
    },
}

#: 用户要求的四项费用指标：指标名 → (工作簿标签, 单位)。
#: 顺序即风险备注费用段的展示顺序；单位跟随标签（万元/元）。
COST_METRIC_LABELS: tuple[tuple[str, str, str], ...] = (
    ("investmentEstimate", NCR_COST_LABELS["investment"]["estimate"], "万元"),
    ("investmentApproved", NCR_COST_LABELS["investment"]["approved"], "万元"),
    ("vehicleChangeEstimate", NCR_COST_LABELS["vehicleChange"]["estimate"], "元"),
    ("vehicleChangeApproved", NCR_COST_LABELS["vehicleChange"]["approved"], "元"),
)

_UNIT_TAILS = ("(万元)", "（万元）", "（元）", "(元)")


def parse_cost_value(value: object) -> float | None:
    """单值费用解析：带符号、千分位可去除、空白/非数 → ``None``。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def sum_cost_metrics(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """对**标签键原始行**求四指标 ``{"sum", "count"}``（有值件数、None≠0）。

    某指标全部行都无值时 ``sum=None``、``count=0``；有值行按符号直加。
    非 Mapping 行一致跳过（与聚合侧防御一致）。
    """
    sums = {metric: 0.0 for metric, _label, _unit in COST_METRIC_LABELS}
    counts = {metric: 0 for metric, _label, _unit in COST_METRIC_LABELS}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        for metric, label, _unit in COST_METRIC_LABELS:
            value = parse_cost_value(row.get(label))
            if value is None:
                continue
            sums[metric] += value
            counts[metric] += 1
    return {
        metric: {
            "sum": sums[metric] if counts[metric] else None,
            "count": counts[metric],
        }
        for metric, _label, _unit in COST_METRIC_LABELS
    }


def format_cost_amount(value: float) -> str:
    """费用展示格式化：四舍五入至多 2 位小数并去掉多余尾零（12.50→"12.5"）。"""
    rounded = round(value, 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def cost_note_segments(
    rows: Iterable[Mapping[str, Any]],
    *,
    total_count: int,
) -> list[str]:
    """风险备注的费用合计段列表（固定指标顺序；有值件数为 0 的指标省略）。

    每段形如 ``测算工程工装费用合计 12.5 万元（有值 2/3 条）``——展示名去掉
    标签尾部的单位括注，单位由 :data:`COST_METRIC_LABELS` 下发。
    """
    metrics = sum_cost_metrics(rows)
    segments: list[str] = []
    for metric, label, unit in COST_METRIC_LABELS:
        entry = metrics[metric]
        if entry["count"] == 0 or entry["sum"] is None:
            continue
        name = label
        for tail in _UNIT_TAILS:
            if name.endswith(tail):
                name = name[: -len(tail)]
                break
        segments.append(
            f"{name}合计 {format_cost_amount(entry['sum'])} {unit}"
            f"（有值 {entry['count']}/{int(total_count)} 条）"
        )
    return segments


__all__ = [
    "COST_METRIC_LABELS",
    "NCR_COST_LABELS",
    "cost_note_segments",
    "format_cost_amount",
    "parse_cost_value",
    "sum_cost_metrics",
]
