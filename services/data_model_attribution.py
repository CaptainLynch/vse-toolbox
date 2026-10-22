# -*- coding: utf-8 -*-
"""数模设计审核流程（D5）的「项目件 / 架构件」归集规则。

本模块只服务 ``tdc_data_model``（VPI-T2-D5）这一个交付物：其他交付物
（EWO / PAA / NCR / SOR / A面）不读取这里的任何函数，也不受影响。

背景：车型项目的零件开发分两种——

* **项目件**：``项目/车型`` 直接是车型代号，如 ``F620S``；
* **架构件**：``项目/车型`` 是架构平台代号（``Ar-`` 开头，如 ``Ar-L``、
  ``Ar-L+``），零件先在架构平台上发布，再被一个或多个车型项目复用。

因此架构件要"算进某个车型"，必须先从报表自带字段里找出车型证据：

1. ``EWO/SOR号`` 形如 ``SGMW-<车型>-SOR####``；
2. ``流水单号`` 前缀形如 ``F710S-3D-0248``；
3. 两者都没有时归入**平台池**（``Ar-L`` / ``Ar-L+``），不并入任何车型合计。

证据只能证明"本次发布针对该车型的需求"，不能证明"该件不服务其他车型"，
所以归集结果保留 ``attribution``（归属方式）供事后修正，不做覆盖式改写。
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

# ── 来源与归属方式词表（与报表展示文案一致，改动需同步前端） ──────────────
PROJECT_PART = "项目件"
ARCHITECTURE_PART = "架构件"

ATTRIBUTION_SELF = "自身车型"
ATTRIBUTION_SOR = "SOR号证据"
ATTRIBUTION_DOCUMENT = "流水单号证据"
ATTRIBUTION_POOL = "平台池"

POOL_LABEL_PREFIX = "待归属"
UNASSIGNED_VEHICLE = "未识别车型"

# 架构平台：``Ar-L`` / ``Ar-L+`` / ``ar_l`` 等写法都归为架构件。
_ARCH_PLATFORM_RE = re.compile(r"^ar[-_+ ]", re.IGNORECASE)
# 车型代号：``F620S`` 形态。``F620S产品项目`` 这类带后缀的脏值取前缀。
_VEHICLE_PREFIX_RE = re.compile(r"^(F\d{3}S)", re.IGNORECASE)
# 观测到的漏字母脏值：``620S`` → ``F620S``。
_VEHICLE_BARE_RE = re.compile(r"^(\d{3}S)$", re.IGNORECASE)
# SOR 号：``SGMW-F710S-SOR0023`` / ``SGMW-Ar-L-SOR0027``。
_SOR_VEHICLE_RE = re.compile(r"SGMW-([A-Za-z0-9+]+?)-SOR", re.IGNORECASE)
# 流水单号：``F710S-3D-0248`` / ``Ar-L-3D-0029`` / ``3D-00001181``。
_DOCUMENT_VEHICLE_RE = re.compile(r"^([A-Za-z0-9+]+?)-3D-", re.IGNORECASE)

_SOURCE_ORDER = {PROJECT_PART: 0, ARCHITECTURE_PART: 1}
_ATTRIBUTION_ORDER = {
    ATTRIBUTION_SELF: 0,
    ATTRIBUTION_SOR: 1,
    ATTRIBUTION_DOCUMENT: 2,
    ATTRIBUTION_POOL: 3,
}


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


def extract_vehicle_evidence(
    ewo_no: object,
    document_no: object,
) -> tuple[str, str] | None:
    """从 SOR 号、流水单号中提取车型证据，返回 ``(车型, 归属方式)``。

    SOR 号优先于流水单号：前者直接绑定车型项目，后者只是单据编号前缀。
    提取不到可识别的车型代号时返回 ``None``。
    """
    sor = _SOR_VEHICLE_RE.search(_text(ewo_no))
    if sor:
        vehicle, _ = normalize_vehicle(sor.group(1))
        if vehicle:
            return vehicle, ATTRIBUTION_SOR
    document = _DOCUMENT_VEHICLE_RE.match(_text(document_no))
    if document:
        vehicle, _ = normalize_vehicle(document.group(1))
        if vehicle:
            return vehicle, ATTRIBUTION_DOCUMENT
    return None


def dimension_fields(
    project_model: object,
    ewo_no: object = None,
    document_no: object = None,
) -> dict[str, str]:
    """给一行 47 列数据算出归集维度。

    返回键：``dataSource``（项目件/架构件）、``vehicle``（归集车型；平台池
    为空串）、``attribution``（归属方式）、``archPlatform``（架构平台原值，
    项目件为空串）。
    """
    raw = _text(project_model)
    source = classify_source(raw)
    if source == PROJECT_PART:
        vehicle, _ = normalize_vehicle(raw)
        return {
            "dataSource": PROJECT_PART,
            "vehicle": vehicle or raw,
            "attribution": ATTRIBUTION_SELF,
            "archPlatform": "",
        }
    evidence = extract_vehicle_evidence(ewo_no, document_no)
    if evidence is not None:
        vehicle, attribution = evidence
        return {
            "dataSource": ARCHITECTURE_PART,
            "vehicle": vehicle,
            "attribution": attribution,
            "archPlatform": raw,
        }
    return {
        "dataSource": ARCHITECTURE_PART,
        "vehicle": "",
        "attribution": ATTRIBUTION_POOL,
        "archPlatform": raw,
    }


def resolve_dimensions(dimensions: Mapping[str, Any]) -> dict[str, str]:
    """读取归集维度；旧快照缺键时按原 ``stage`` 兜底推导（不回填也一致）。

    兜底只依赖同一套纯函数，因此新旧快照走的是同一套规则，不存在第二条
    计算路径。
    """
    source = _text(dimensions.get("dataSource"))
    vehicle = _text(dimensions.get("vehicle"))
    attribution = _text(dimensions.get("attribution"))
    platform = _text(dimensions.get("archPlatform"))
    if source and attribution and (vehicle or attribution == ATTRIBUTION_POOL):
        return {
            "dataSource": source,
            "vehicle": vehicle,
            "attribution": attribution,
            "archPlatform": platform,
        }
    stage = _text(dimensions.get("stage"))
    fallback = dimension_fields(stage)
    if not source:
        source = fallback["dataSource"]
    if not attribution:
        attribution = fallback["attribution"]
    if not vehicle:
        vehicle = fallback["vehicle"]
    if not platform:
        platform = fallback["archPlatform"]
    return {
        "dataSource": source,
        "vehicle": vehicle,
        "attribution": attribution,
        "archPlatform": platform,
    }


def group_label(dimensions: Mapping[str, Any]) -> str:
    """阶段图/汇总用的分组标签：``<车型> · <来源>``。

    平台池统一显示为 ``待归属 <平台> · 架构件``，与车型分组区分开。
    """
    resolved = resolve_dimensions(dimensions)
    source = resolved["dataSource"]
    if resolved["attribution"] == ATTRIBUTION_POOL:
        platform = resolved["archPlatform"] or "架构平台"
        return f"{POOL_LABEL_PREFIX} {platform} · {source}"
    vehicle = resolved["vehicle"] or UNASSIGNED_VEHICLE
    return f"{vehicle} · {source}"


def group_sort_key(label: str) -> tuple[int, str, int]:
    """让同一车型的项目件/架构件相邻，平台池排在最后。

    标签由 ``group_label`` 产出，形如 ``<车型> · <来源>``，因此先按车型
    分段再按来源排序，避免中文排序把「架构件」排到「项目件」前面。
    """
    pool = label.startswith(POOL_LABEL_PREFIX)
    vehicle, separator, source = label.rpartition(" · ")
    if not separator:
        vehicle, source = label, ""
    return (1 if pool else 0, vehicle, _SOURCE_ORDER.get(source, 9))


def resolve_instance_dimensions(
    dims_list: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    """把一个流程实例内多行的归集维度合成一份（实例级口径）。

    规则（依次）：

    1. 有证据的行优先于平台池；
    2. 证据之间按**行数多数**定车型（一个实例里可能既有 F710S 的 SOR 行，
       也有 F520S 的 SOR 行）；
    3. 平票时按 SOR 号 > 流水单号、再按车型代号取最小，保证确定性。

    这样阶段图（行级）与实例汇总不会因为"实例里某一行缺 SOR 号"而给出
    互相矛盾的数字。
    """
    resolved_rows = [resolve_dimensions(dims) for dims in dims_list]
    evidenced = [
        item for item in resolved_rows if item["attribution"] != ATTRIBUTION_POOL
    ]
    if not evidenced:
        platform = next(
            (item["archPlatform"] for item in resolved_rows if item["archPlatform"]),
            "",
        )
        return {
            "dataSource": ARCHITECTURE_PART,
            "vehicle": "",
            "attribution": ATTRIBUTION_POOL,
            "archPlatform": platform,
        }
    votes: dict[str, int] = {}
    for item in evidenced:
        votes[item["vehicle"]] = votes.get(item["vehicle"], 0) + 1
    best = min(
        evidenced,
        key=lambda item: (
            -votes[item["vehicle"]],
            _ATTRIBUTION_ORDER.get(item["attribution"], 9),
            item["vehicle"],
        ),
    )
    return dict(best)


def unify_rows(rows: Sequence[dict[str, Any]], instance_of) -> None:
    """按实例统一各行的归集维度（原地改写 ``row["dimensions"]``）。

    ``instance_of(row)`` 返回实例键；返回空串时视为无法归并，保持行级结果。

    只在同一实例内 ``stage``（项目/车型 原值）一致时才归并：实测两份导出
    中一个实例从不跨车型（1037 行 0 例外），若上游出现跨车型实例，保留
    行级结果比强行合并更诚实。
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        dimensions = row.get("dimensions")
        if not isinstance(dimensions, dict):
            continue
        key = _text(instance_of(row))
        if not key:
            continue
        grouped.setdefault(key, []).append(dimensions)
    for dimensions_list in grouped.values():
        if len(dimensions_list) < 2:
            continue
        stages = {_text(dimensions.get("stage")) for dimensions in dimensions_list}
        if len(stages) > 1:
            continue
        resolved = resolve_instance_dimensions(dimensions_list)
        for dimensions in dimensions_list:
            dimensions.update(resolved)


def summarize_instances(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """按流程实例（``实例号``）汇总三态计数，输出车型分层结构。

    ``rows`` 每项需含 ``dimensions``（或已归集字段）、``status`` 与
    ``instance``（实例号）。同一实例只计一次（实测实例内状态唯一）。

    分组键是 ``(归集车型, 数据来源)``——同一车型下项目件与架构件并列两行；
    平台池单独成组，不并入任何车型合计。

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
        resolved = resolve_instance_dimensions(bucket["dims"])
        key = (resolved["vehicle"], resolved["dataSource"])
        group = groups.get(key)
        if group is None:
            group = {
                "vehicle": resolved["vehicle"],
                "dataSource": resolved["dataSource"],
                "attribution": resolved["attribution"],
                "archPlatform": resolved["archPlatform"],
                "attributions": [],
                "total": 0,
                "completed": 0,
                "active": 0,
                "discarded": 0,
            }
            groups[key] = group
        if resolved["attribution"] not in group["attributions"]:
            group["attributions"].append(resolved["attribution"])
            group["attributions"].sort(key=lambda name: _ATTRIBUTION_ORDER.get(name, 9))
            group["attribution"] = group["attributions"][0]
        if not group["archPlatform"]:
            group["archPlatform"] = resolved["archPlatform"]
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
            item["attribution"] == ATTRIBUTION_POOL,
            item["vehicle"],
            _SOURCE_ORDER.get(item["dataSource"], 9),
        )
    )
    return result


def summarize_vehicles(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """在 ``summarize_instances`` 之上按车型合计（平台池不并入车型合计）。"""
    groups = summarize_instances(rows)
    vehicles: dict[str, dict[str, Any]] = {}
    for group in groups:
        if group["attribution"] == ATTRIBUTION_POOL:
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
