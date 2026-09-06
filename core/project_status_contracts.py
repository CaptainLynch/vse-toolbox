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
    valid_milestones = []
    for item in milestones:
        raw_date = item.get("date")
        if raw_date in (None, ""):
            continue
        try:
            parsed = date.fromisoformat(str(raw_date))
            valid_milestones.append((parsed, str(item.get("name", ""))))
        except ValueError:
            continue
    if not valid_milestones:
        return "项目开始 → 项目结束"
    ordered = sorted(valid_milestones, key=lambda item: (item[0].isoformat(), item[1]))
    previous = [item for item in ordered if item[0] <= today]
    following = [item for item in ordered if item[0] > today]
    left = previous[-1][1] if previous else "项目开始"
    right = following[0][1] if following else "项目结束"
    return f"{left} → {right}"
