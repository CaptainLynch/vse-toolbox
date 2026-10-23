# -*- coding: utf-8 -*-
"""数模设计审核流程（D5）的「项目件 / 架构件」分组规则。

本模块只服务 ``tdc_data_model``（VPI-T2-D5）这一个交付物：其他交付物
（EWO / PAA / NCR / SOR / A面）不读取这里的任何函数，也不受影响。

业务口径（用户 2026-10-23 确认，方案 c + 台账结论）：

* **项目件**：``项目/车型`` 直接是车型代号（如 ``F620S``），按车型统计；
* **架构件**：``项目/车型`` 是架构平台代号（``Ar-`` 开头，如 ``Ar-L``、
  ``Ar-L+``）。架构件是平台级发布、可被多个车型复用，**不归属单一车型**，
  因此按平台单独成组统计，只和车型报表并列展示，不并入任何车型合计。

重要的反面前提（务必保留，勿再引入）：
``EWO/SOR号`` 里的 ``SGMW-<车型>-SOR####`` **不能**用来判断"这单服务哪个
车型"。那是零件的定点/SOR 文档编号，属于零件，不属于数模审批单。批次实测
反证：项目件报表里有 3 个实例，发布车型是 ``F620S`` 而 SOR 号写的是
``F710S``——若 SOR 是发布归属，这应当为 0。早期版本曾把 SOR 当最高优先级
证据，导致架构件 94 单里 34 单被错误归到车型，已整体移除。

台账结论（用户 2026-10-23 确认）：项目派单台账**不存在**，所谓"台账"就是
TDC 按车型查询的结果，而按车型查询在结构上不会返回 ``Ar-`` 行，所以它无法
提供"平台单属于哪个车型"的关系。因此不再保留任何台账入参——若将来出现
独立于 TDC 的派单台账，再以显式参数重新引入，并先补齐口径与回归测试。
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

# ── 来源与归属方式词表（与报表展示文案一致，改动需同步前端） ──────────────
PROJECT_PART = "项目件"
ARCHITECTURE_PART = "架构件"

ATTRIBUTION_SELF = "自身车型"
#: 架构件按平台单列（唯一口径）。
ATTRIBUTION_PLATFORM = "平台单列"

UNASSIGNED_VEHICLE = "未识别车型"

# 架构平台：``Ar-L`` / ``Ar-L+`` / ``ar_l`` 等写法都归为架构件。
_ARCH_PLATFORM_RE = re.compile(r"^ar[-_+ ]", re.IGNORECASE)
# 车型代号：``F620S`` 形态。``F620S产品项目`` 这类带后缀的脏值取前缀。
_VEHICLE_PREFIX_RE = re.compile(r"^(F\d{3}S)", re.IGNORECASE)
# 观测到的漏字母脏值：``620S`` → ``F620S``。
_VEHICLE_BARE_RE = re.compile(r"^(\d{3}S)$", re.IGNORECASE)

_SOURCE_ORDER = {PROJECT_PART: 0, ARCHITECTURE_PART: 1}


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_vehicle(value: object) -> tuple[str, bool]:
    """把「项目/车型」原值归一成车型代号。

    返回 ``(车型代号, 是否做过修复)``；无法识别时返回 ``("", False)``。

    已知脏值形态（2026-10-22 实测导出）：

    * ``F620S产品项目`` → ``F620S``（去掉描述性后缀）
    * ``620S`` → ``F620S``（漏字母，补前缀并标记为修复）
    """
    text = _text(value)
    if not text:
        return "", False
    match = _VEHICLE_PREFIX_RE.match(text)
    if match:
        code = match.group(1).upper()
        return code, code != text.upper()
    match = _VEHICLE_BARE_RE.match(text)
    if match:
        return f"F{match.group(1).upper()}", True
    return "", False


def is_architecture_platform(value: object) -> bool:
    """「项目/车型」是否为架构平台代号（``Ar-`` 开头）。"""
    return bool(_ARCH_PLATFORM_RE.match(_text(value)))


def classify_source(value: object) -> str:
    """按「项目/车型」判定数据来源：架构件 / 项目件。"""
    return ARCHITECTURE_PART if is_architecture_platform(value) else PROJECT_PART


def dimension_fields(project_model: object) -> dict[str, str]:
    """给一行 47 列数据算出分组维度。

    返回键：

    * ``dataSource``：项目件 / 架构件
    * ``vehicle``：车型（架构件为空串——平台件不归属单一车型）
    * ``attribution``：归属方式（自身车型 / 平台单列）
    * ``archPlatform``：架构平台原值（项目件为空串）

    刻意不接受 EWO/SOR 号、流水单号等入参：它们都不是"这单服务哪个车型"
    的证据（见模块文档）。若将来出现独立派单台账，以新参数显式引入。
    """
    raw = _text(project_model)
    if classify_source(raw) == PROJECT_PART:
        vehicle, _ = normalize_vehicle(raw)
        return {
            "dataSource": PROJECT_PART,
            "vehicle": vehicle or raw,
            "attribution": ATTRIBUTION_SELF,
            "archPlatform": "",
        }
    return {
        "dataSource": ARCHITECTURE_PART,
        "vehicle": "",
        "attribution": ATTRIBUTION_PLATFORM,
        "archPlatform": raw,
    }


def resolve_dimensions(dimensions: Mapping[str, Any]) -> dict[str, str]:
    """读取分组维度；旧快照缺键或带历史口径时按现行规则重算。

    兜底只依赖同一套纯函数，因此新旧快照走同一套规则，不存在第二条计算路径。
    旧快照里若残留早期版本的 ``attribution``（``SOR号证据`` / ``平台池`` /
    ``台账归属`` 等），一律按当前口径重算——口径修正必须对历史行同样生效。
    """
    known = {ATTRIBUTION_SELF, ATTRIBUTION_PLATFORM}
    source = _text(dimensions.get("dataSource"))
    attribution = _text(dimensions.get("attribution"))
    if source and attribution in known and (source == ARCHITECTURE_PART or dimensions.get("vehicle")):
        return {
            "dataSource": source,
            "vehicle": _text(dimensions.get("vehicle")),
            "attribution": attribution,
            "archPlatform": _text(dimensions.get("archPlatform")),
        }
    fallback = dimension_fields(_text(dimensions.get("stage")))
    return {
        "dataSource": fallback["dataSource"],
        "vehicle": fallback["vehicle"],
        "attribution": fallback["attribution"],
        "archPlatform": fallback["archPlatform"],
    }


def group_label(dimensions: Mapping[str, Any]) -> str:
    """阶段图/汇总用的分组标签。

    * 项目件：``<车型> · 项目件``
    * 架构件：``<平台> · 架构件``（平台单列，不挂车型）
    """
    resolved = resolve_dimensions(dimensions)
    if resolved["dataSource"] == PROJECT_PART:
        vehicle = resolved["vehicle"] or UNASSIGNED_VEHICLE
        return f"{vehicle} · {PROJECT_PART}"
    platform = resolved["archPlatform"] or "架构平台"
    return f"{platform} · {ARCHITECTURE_PART}"


def group_sort_key(label: str) -> tuple[int, str]:
    """项目件（按车型）在前，架构件（按平台）在后；同类按名称排序。"""
    source_rank = 1 if label.endswith(ARCHITECTURE_PART) else 0
    return (source_rank, label)


def _group_key(resolved: Mapping[str, str]) -> tuple[str, str]:
    """分组键：项目件按车型、架构件按平台。"""
    if resolved["dataSource"] == PROJECT_PART:
        return PROJECT_PART, resolved["vehicle"]
    return ARCHITECTURE_PART, resolved["archPlatform"]


def summarize_instances(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """按流程实例（``实例号``）汇总三态计数。

    ``rows`` 每项需含 ``dimensions``（或已归集字段）、``status`` 与
    ``instance``（实例号）。同一实例只计一次（实测实例内状态唯一）。

    分组：项目件按车型、架构件按平台。架构件**不并入**任何车型合计。

    * 计数：``total`` / ``completed`` / ``active`` / ``discarded``
    * ``completionRate``：``completed / (completed + active)``，已废弃不进分母
    """
    instances: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        dimensions = row.get("dimensions")
        if not isinstance(dimensions, Mapping):
            dimensions = {}
        instance = _text(row.get("instance")) or f"row:{index}"
        bucket = instances.get(instance)
        if bucket is None:
            bucket = {"instance": instance, "dims": [], "status": ""}
            instances[instance] = bucket
        bucket["dims"].append(dimensions)
        # 实例级状态取首个非空值；同实例内状态本应一致（实测 0 例外）。
        if not bucket["status"]:
            bucket["status"] = _text(row.get("status"))

    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for bucket in instances.values():
        resolved = resolve_dimensions(bucket["dims"][0])
        data_source, subject = _group_key(resolved)
        group = groups.get((data_source, subject))
        if group is None:
            group = {
                "dataSource": data_source,
                "vehicle": resolved["vehicle"] if data_source == PROJECT_PART else "",
                "archPlatform": resolved["archPlatform"]
                if data_source == ARCHITECTURE_PART else "",
                "attribution": resolved["attribution"],
                "total": 0,
                "completed": 0,
                "active": 0,
                "discarded": 0,
            }
            groups[(data_source, subject)] = group
        group["total"] += 1
        if bucket["status"] == "已完成":
            group["completed"] += 1
        elif bucket["status"] == "已废弃":
            group["discarded"] += 1
        else:
            group["active"] += 1

    result: list[dict[str, Any]] = []
    for group in groups.values():
        effective = group["completed"] + group["active"]
        group["completionRate"] = (
            round(group["completed"] / effective * 100, 2) if effective else 0.0
        )
        group["label"] = group_label(
            {
                "dataSource": group["dataSource"],
                "vehicle": group["vehicle"],
                "attribution": group["attribution"],
                "archPlatform": group["archPlatform"],
            }
        )
        result.append(group)
    result.sort(
        key=lambda item: (
            _SOURCE_ORDER.get(item["dataSource"], 9),
            item["vehicle"] or item["archPlatform"],
        )
    )
    return result


def summarize_vehicles(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """车型合计：只统计项目件（架构件按平台单列，不并入车型）。"""
    groups = summarize_instances(rows)
    vehicles: dict[str, dict[str, Any]] = {}
    for group in groups:
        if group["dataSource"] != PROJECT_PART:
            continue
        bucket = vehicles.setdefault(
            group["vehicle"],
            {
                "vehicle": group["vehicle"],
                "total": 0,
                "completed": 0,
                "active": 0,
                "discarded": 0,
                "parts": [],
            },
        )
        for key in ("total", "completed", "active", "discarded"):
            bucket[key] += group[key]
        bucket["parts"].append(
            {
                "dataSource": group["dataSource"],
                "attribution": group["attribution"],
                "total": group["total"],
                "completed": group["completed"],
                "active": group["active"],
                "discarded": group["discarded"],
            }
        )
    result: list[dict[str, Any]] = []
    for bucket in vehicles.values():
        effective = bucket["completed"] + bucket["active"]
        bucket["completionRate"] = (
            round(bucket["completed"] / effective * 100, 2) if effective else 0.0
        )
        result.append(bucket)
    result.sort(key=lambda item: item["vehicle"])
    return result


def summarize_platforms(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """平台合计：只统计架构件，按架构平台分桶。"""
    groups = summarize_instances(rows)
    platforms: dict[str, dict[str, Any]] = {}
    for group in groups:
        if group["dataSource"] != ARCHITECTURE_PART:
            continue
        platform = group["archPlatform"] or "（平台未知）"
        bucket = platforms.setdefault(
            platform,
            {
                "archPlatform": platform,
                "total": 0,
                "completed": 0,
                "active": 0,
                "discarded": 0,
            },
        )
        for key in ("total", "completed", "active", "discarded"):
            bucket[key] += group[key]
    result: list[dict[str, Any]] = []
    for bucket in platforms.values():
        effective = bucket["completed"] + bucket["active"]
        bucket["completionRate"] = (
            round(bucket["completed"] / effective * 100, 2) if effective else 0.0
        )
        result.append(bucket)
    result.sort(key=lambda item: item["archPlatform"])
    return result
