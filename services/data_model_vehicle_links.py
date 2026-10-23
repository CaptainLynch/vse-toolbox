# -*- coding: utf-8 -*-
"""数模设计审核流程（D5）：车型 ↔ 架构件单号的人工关联（方案 B：并入车型合计）。

口径（用户 2026-10-23 确认）：

* 项目件照旧按车型统计；
* **用户在车型下显式指定**的架构件单号，按声明确认后并入该车型合计
  （方案 B）；同时保留"仅项目件"数字作对照，避免历史不可比时无法解释；
* 声明是**人工口径**，只记录"谁、何时、依据什么"，不做任何推断；
* 同一架构单被多个车型声明时：各车型视图分别计入（称"关联覆盖"），
  全局合计必须按单号去重，禁止把各车型数字直接相加。

失配四态（必须分开披露，不能静默少算）：

``matched``       单号存在，且 ``项目/车型`` 确为架构平台
``source_mismatch`` 单号存在，但它是项目件（声明写错了）
``missing``       清单里有，本次快照查不到（上游剔除或未同步）
``conflict``      同一单号匹配到多个实例，键不稳定
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from services import data_model_attribution as attribution

FORM_KEY = "tdc_data_model"

LINK_MATCHED = "matched"
LINK_SOURCE_MISMATCH = "source_mismatch"
LINK_MISSING = "missing"
LINK_CONFLICT = "conflict"

LINK_STATUS_LABELS = {
    LINK_MATCHED: "已匹配",
    LINK_SOURCE_MISMATCH: "来源不符",
    LINK_MISSING: "快照缺失",
    LINK_CONFLICT: "键冲突",
}

MAX_SERIALS_PER_VEHICLE = 500
_SERIAL_MAX_LENGTH = 64
_SERIAL_SEPARATORS = re.compile(r"[\s,;、]+")


class LinkError(ValueError):
    """声明内容不合法（不是失配，是输入错误）。"""


def normalize_serials(value: object) -> list[str]:
    """把粘贴文本/列表解析成去重后的单号列表。"""
    if value is None:
        return []
    if isinstance(value, str):
        raw = [part for part in _SERIAL_SEPARATORS.split(value)]
    elif isinstance(value, Iterable):
        raw = [str(item) for item in value]
    else:
        raise LinkError("单号必须是文本或列表")
    cleaned: list[str] = []
    for item in raw:
        serial = str(item).strip()
        if not serial:
            continue
        if len(serial) > _SERIAL_MAX_LENGTH:
            raise LinkError(f"单号过长（上限 {_SERIAL_MAX_LENGTH} 字符）：{serial[:20]}…")
        if serial not in cleaned:
            cleaned.append(serial)
    if len(cleaned) > MAX_SERIALS_PER_VEHICLE:
        raise LinkError(f"单个车型最多关联 {MAX_SERIALS_PER_VEHICLE} 个单号")
    return cleaned


def resolve_links(
    serials: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    definition: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """把声明单号对到当前快照行，给出失配四态。

    ``definition`` 用于从原始 47 列取值；不传则只读 ``dimensions``/``values``
    里已有的 ``流水单号`` 字段。
    """
    by_serial: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        serial = _row_serial(row, definition)
        if serial:
            by_serial.setdefault(serial, []).append(row)

    claimed: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    result: list[dict[str, Any]] = []
    for serial in serials:
        matched = by_serial.get(serial) or []
        instances = {_row_instance(row, definition) for row in matched}
        if not matched:
            result.append(
                {
                    "serial": serial,
                    "status": LINK_MISSING,
                    "statusLabel": LINK_STATUS_LABELS[LINK_MISSING],
                    "projectModel": "",
                    "instance": "",
                }
            )
            continue
        if len(instances) > 1:
            result.append(
                {
                    "serial": serial,
                    "status": LINK_CONFLICT,
                    "statusLabel": LINK_STATUS_LABELS[LINK_CONFLICT],
                    "projectModel": "",
                    "instance": ",".join(sorted(filter(None, instances)))[:200],
                }
            )
            continue
        row = matched[0]
        dimensions = row.get("dimensions")
        if not isinstance(dimensions, Mapping):
            dimensions = {}
        project_model = str(dimensions.get("stage") or "").strip()
        if attribution.classify_source(project_model) != attribution.ARCHITECTURE_PART:
            result.append(
                {
                    "serial": serial,
                    "status": LINK_SOURCE_MISMATCH,
                    "statusLabel": LINK_STATUS_LABELS[LINK_SOURCE_MISMATCH],
                    "projectModel": project_model,
                    "instance": _row_instance(row, definition),
                }
            )
            continue
        result.append(
            {
                "serial": serial,
                "status": LINK_MATCHED,
                "statusLabel": LINK_STATUS_LABELS[LINK_MATCHED],
                "projectModel": project_model,
                "instance": _row_instance(row, definition),
            }
        )
        claimed.setdefault(str(serial), []).append((_row_instance(row, definition), row))
    return result


def linked_instances(
    serials: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    definition: Mapping[str, Any] | None = None,
) -> dict[str, set[str]]:
    """返回 ``{车型: {实例号}}``——已匹配的声明单按车型归组。

    只收 ``matched``：来源不符/缺失/冲突都不并入合计。
    """
    resolved = resolve_links(serials, rows, definition)
    instances: dict[str, set[str]] = {}
    for item in resolved:
        if item["status"] != LINK_MATCHED:
            continue
        instances.setdefault("", set()).add(str(item["instance"]))
    return instances


def relabel_linked_rows(
    rows: Sequence[dict[str, Any]],
    vehicle: str,
    matched_instances: set[str],
    definition: Mapping[str, Any] | None = None,
) -> int:
    """把被声明并且已匹配的架构件行，打上"关联给哪个车型"的标记。

    只改 ``linkedVehicle`` 维度键，不改 ``dataSource``/``archPlatform``：
    架构件的来源事实不变，变的只是"这个车型把它算进来了"。返回改动行数。
    """
    changed = 0
    for row in rows:
        dimensions = row.get("dimensions")
        if not isinstance(dimensions, dict):
            continue
        instance = _row_instance(row, definition)
        if not instance or instance not in matched_instances:
            continue
        if attribution.classify_source(str(dimensions.get("stage") or "").strip()) != (
            attribution.ARCHITECTURE_PART
        ):
            continue
        dimensions["linkedVehicle"] = vehicle
        changed += 1
    return changed


def summarize(
    rows: Sequence[Mapping[str, Any]],
    links_by_vehicle: Mapping[str, Sequence[str]],
    definition: Mapping[str, Any] | None = None,
    instance_of=None,
) -> dict[str, Any]:
    """方案 B 的汇总：车型合计 = 项目件 + 已确认关联的架构件。

    计数口径：**按流程实例**（`实例号`）计一次，`rows` 只作附带信息。
    这与"主口径 = 实例级"一致；行级数字另外给出并明确命名，避免两个口径混用。
    `instance_of(row)` 取实例号，不传则用 `values`/`instance` 兜底。
    """
    instance_of = instance_of or (lambda row: _row_instance(row, definition))
    instances: dict[str, dict[str, Any]] = {}
    rows_by_instance: dict[str, int] = {}
    for index, row in enumerate(rows):
        dimensions = row.get("dimensions")
        if not isinstance(dimensions, Mapping):
            dimensions = {}
        instance = str(instance_of(row) or "").strip() or f"row:{index}"
        rows_by_instance[instance] = rows_by_instance.get(instance, 0) + 1
        if instance not in instances:
            instances[instance] = {
                "dimensions": dict(dimensions),
                "projectModel": str(dimensions.get("stage") or "").strip(),
                "status": str(dimensions.get("status") or row.get("status") or ""),
            }

    project_by_vehicle: dict[str, dict[str, Any]] = {}
    for instance, info in instances.items():
        if attribution.classify_source(info["projectModel"]) != attribution.PROJECT_PART:
            continue
        vehicle = str(info["dimensions"].get("vehicle") or "").strip()
        bucket = project_by_vehicle.setdefault(
            vehicle, {"rows": 0, "instances": 0, "completed": 0, "active": 0, "discarded": 0}
        )
        bucket["rows"] += rows_by_instance.get(instance, 1)
        bucket["instances"] += 1
        if info["status"] == "已完成":
            bucket["completed"] += 1
        elif info["status"] == "已废弃":
            bucket["discarded"] += 1
        else:
            bucket["active"] += 1

    vehicles: list[dict[str, Any]] = []
    all_linked: set[str] = set()
    # 车型视图覆盖"有项目件"与"有声明"的并集：只声明不存在的车型也要能报出来。
    for vehicle in sorted(set(project_by_vehicle) | set(links_by_vehicle)):
        declared = links_by_vehicle.get(vehicle, ())
        resolved = resolve_links(list(declared), rows, definition)
        matched = [item for item in resolved if item["status"] == LINK_MATCHED]
        linked_ids = {item["instance"] for item in matched}
        all_linked |= linked_ids
        linked_completed = linked_active = linked_discarded = 0
        for instance in linked_ids:
            status = instances.get(instance, {}).get("status", "")
            if status == "已完成":
                linked_completed += 1
            elif status == "已废弃":
                linked_discarded += 1
            else:
                linked_active += 1
        base = project_by_vehicle.get(
            vehicle, {"rows": 0, "instances": 0, "completed": 0, "active": 0, "discarded": 0}
        )
        base_effective = base["completed"] + base["active"]
        combined_completed = base["completed"] + linked_completed
        combined_active = base["active"] + linked_active
        combined_discarded = base["discarded"] + linked_discarded
        combined_effective = combined_completed + combined_active
        vehicles.append(
            {
                "vehicle": vehicle,
                "projectOnly": {
                    "rows": base["rows"],
                    "instances": base["instances"],
                    "completed": base["completed"],
                    "active": base["active"],
                    "discarded": base["discarded"],
                    "completionRate": round(base["completed"] / base_effective * 100, 2)
                    if base_effective else 0.0,
                },
                "linkedArchitecture": {
                    "declared": len(declared),
                    "matched": len(matched),
                    "instances": len(linked_ids),
                    "completed": linked_completed,
                    "active": linked_active,
                    "discarded": linked_discarded,
                },
                "combined": {
                    "instances": base["instances"] + len(linked_ids),
                    "completed": combined_completed,
                    "active": combined_active,
                    "discarded": combined_discarded,
                    "completionRate": round(
                        combined_completed / combined_effective * 100, 2
                    ) if combined_effective else 0.0,
                },
                "links": resolved,
            }
        )
    vehicles.sort(key=lambda item: item["vehicle"])
    return {
        "scope": "combined",
        "countUnit": "instance",
        "vehicles": vehicles,
        "linkedInstanceCount": len(all_linked),
        "note": (
            "车型合计 = 项目件 + 已确认关联的架构件（人工声明），按实例号计数。"
            "同一架构单若被多个车型声明，各车型视图分别计入；跨车型合计按单号去重"
            "（linkedInstanceCount）。"
        ),
    }


def _row_serial(
    row: Mapping[str, Any],
    definition: Mapping[str, Any] | None,
) -> str:
    values = row.get("values")
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes)) and definition:
        position = _label_index(definition, "流水单号")
        if position is not None and position < len(values):
            return str(values[position] or "").strip()
    return str(row.get("serial") or "").strip()


def _row_instance(
    row: Mapping[str, Any],
    definition: Mapping[str, Any] | None = None,
) -> str:
    values = row.get("values")
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes)) and definition:
        position = _label_index(definition, "实例号")
        if position is not None and position < len(values):
            return str(values[position] or "").strip()
    return str(row.get("instance") or "").strip()


def _label_index(definition: Mapping[str, Any], label: str) -> int | None:
    headers = definition.get("headerRows") or ()
    if not headers:
        return None
    first = headers[0]
    try:
        return list(first).index(label)
    except (ValueError, TypeError):
        return None
