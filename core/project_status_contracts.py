"""Pure project-status presentation rules."""

from __future__ import annotations

from datetime import date
from typing import Mapping, Sequence


MILESTONE_STATUSES = ("未开始", "进行中", "已完成", "已超期")


def milestone_display_status(status: object, milestone_date: object, today: date) -> str:
    normalized = {
        "done": "已完成",
        "current": "进行中",
        "planned": "未开始",
        "已达成": "已完成",
        "当前目标节点": "进行中",
        "计划节点": "未开始",
    }.get(str(status), str(status))
    if normalized == "已完成":
        return normalized
    try:
        planned = date.fromisoformat(str(milestone_date))
    except ValueError:
        return normalized if normalized in MILESTONE_STATUSES else "未开始"
    return "已超期" if planned < today else normalized


def current_stage_label(
    milestones: Sequence[Mapping[str, object]],
    today: date,
) -> str:
    ordered = sorted(milestones, key=lambda item: (str(item["date"]), str(item["name"])))
    if not ordered:
        return "项目开始 → 项目结束"
    previous = [item for item in ordered if date.fromisoformat(str(item["date"])) <= today]
    following = [item for item in ordered if date.fromisoformat(str(item["date"])) > today]
    left = str(previous[-1]["name"]) if previous else "项目开始"
    right = str(following[0]["name"]) if following else "项目结束"
    return f"{left} → {right}"
