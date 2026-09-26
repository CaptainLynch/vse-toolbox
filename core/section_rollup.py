"""科室归集规则：本地设置存储、校验与统一归集原语（无业务字段语义）。

为什么存在：EWO/NCR/PAA 下发人员对应的科室值因历史原因五花八门
（如车身科的前身「结构工程科」「车门附件科」），图表与筛选必须先归集到
现行科室集合再统计，且未登记的历史值要进入显式的「未归集」兜底桶，
不允许静默丢弃。规则保存在本地 ``app_settings`` KV（键 ``sectionRollup``），
归集在读取层逐行应用，因此规则保存后立即生效——只调整统计口径，
不改写任何原始同步数据，也无需重建快照。

设计边界（勿破）：
- 本模块只做规则校验、存取和「原始科室值 → 目标科室」的单一判定原语
  ``resolve_section``；筛选谓词与图表聚合必须共用这一原语，禁止各自实现。
- 匹配是去除首尾空白后的精确相等，不做前缀/包含匹配（避免误归集）。
- 未配置规则时调用方应传 ``None`` 并保持既有原始值行为。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from core.db_manager import DatabaseManager

ROLLUP_SETTINGS_KEY = "sectionRollup"

MAX_TARGETS = 24
MAX_ALIASES_PER_TARGET = 40
MAX_TOTAL_ALIASES = 200
MAX_NAME_CHARS = 40
MAX_JSON_BYTES = 64 * 1024

_UNASSIGNED_LABEL = "未归集"

DEFAULT_SECTION_ROLLUP: dict[str, Any] = {
    "version": 1,
    "targets": [
        {"target": "车身科", "aliases": []},
        {"target": "车体科", "aliases": []},
        {"target": "内饰科", "aliases": []},
        {"target": "外饰科", "aliases": []},
        {"target": "车体架构集成科", "aliases": []},
    ],
}


class SectionRollupError(ValueError):
    """科室归集规则非法；``fields`` 携带逐字段错误信息。"""

    def __init__(self, fields: Mapping[str, str]) -> None:
        super().__init__("科室归集规则无效")
        self.fields = dict(fields)


def unassigned_label() -> str:
    """「未归集」兜底桶的固定展示名。"""
    return _UNASSIGNED_LABEL


def _clean_name(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, str):
        raise ValueError("必须是字符串")
    return value.strip()


def validate_section_rollup(payload: object) -> dict[str, Any]:
    """校验并规范化规则载荷；非法时抛出带逐字段信息的 :class:`SectionRollupError`。"""
    if not isinstance(payload, Mapping):
        raise SectionRollupError({"request": "必须是对象"})
    if len(str(payload)) > MAX_JSON_BYTES:
        raise SectionRollupError({"request": "规则内容过大"})
    unknown = set(payload) - {"version", "updatedAt", "targets"}
    if unknown:
        raise SectionRollupError({"request": f"包含不支持的字段：{sorted(unknown)}"})
    errors: dict[str, str] = {}
    version = payload.get("version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        errors["version"] = "必须是正整数"
    updated_at = payload.get("updatedAt")
    if updated_at is not None and (
        isinstance(updated_at, bool) or not isinstance(updated_at, str) or not updated_at.strip()
    ):
        errors["updatedAt"] = "必须是非空字符串"
    targets_raw = payload.get("targets")
    if not isinstance(targets_raw, list) or not targets_raw:
        errors["targets"] = "至少需要一个目标科室"
    elif len(targets_raw) > MAX_TARGETS:
        errors["targets"] = f"目标科室不能超过 {MAX_TARGETS} 个"
    if errors:
        raise SectionRollupError(errors)

    reserved = unassigned_label()
    # 第一趟：规范化并收集全部目标名；别名必须与**全部**目标名（含自身与
    # 后序目标）查重，因此必须在收集完成后才能开始别名校验。
    normalized_targets: dict[int, str] = {}
    all_targets: set[str] = set()
    for position, entry in enumerate(targets_raw, start=1):
        if not isinstance(entry, Mapping) or set(entry) - {"target", "aliases"}:
            errors[f"targets.{position}"] = "必须是 {{target, aliases}} 对象"
            continue
        try:
            target = _clean_name(entry.get("target"))
        except ValueError:
            errors[f"targets.{position}.target"] = "必须是字符串"
            continue
        if not target:
            errors[f"targets.{position}.target"] = "目标科室不能为空"
        elif len(target) > MAX_NAME_CHARS:
            errors[f"targets.{position}.target"] = f"目标科室不能超过 {MAX_NAME_CHARS} 个字符"
        elif target == reserved:
            errors[f"targets.{position}.target"] = f"不能使用系统保留名：{reserved}"
        elif target in all_targets:
            errors[f"targets.{position}.target"] = f"目标科室重复：{target}"
        else:
            all_targets.add(target)
            normalized_targets[position] = target

    # 第二趟：逐条目校验别名；出错条目整条跳过，不登记别名避免级联误报。
    seen_aliases: dict[str, str] = {}
    total_aliases = 0
    targets: list[dict[str, Any]] = []
    for position, entry in enumerate(targets_raw, start=1):
        target = normalized_targets.get(position)
        if target is None:
            continue
        alias_error: str | None = None
        aliases: list[str] = []
        aliases_raw = entry.get("aliases", [])
        if not isinstance(aliases_raw, list):
            alias_error = "必须是字符串列表"
        else:
            for alias_raw in aliases_raw:
                try:
                    alias = _clean_name(alias_raw)
                except ValueError:
                    alias_error = "必须是字符串列表"
                    break
                if not alias:
                    alias_error = "历史科室值不能为空"
                    break
                if len(alias) > MAX_NAME_CHARS:
                    alias_error = f"历史科室值不能超过 {MAX_NAME_CHARS} 个字符：{alias}"
                    break
                if alias in all_targets:
                    alias_error = f"历史科室值不能与目标科室同名：{alias}"
                    break
                if alias in aliases:
                    alias_error = f"历史科室值重复：{alias}"
                    break
                if alias == reserved:
                    alias_error = f"不能使用系统保留名：{reserved}"
                    break
                owner = seen_aliases.get(alias)
                if owner is not None:
                    alias_error = f"历史科室值只能归属一个目标科室：{alias}（已归属 {owner}）"
                    break
                aliases.append(alias)
        if alias_error is not None:
            errors[f"targets.{position}.aliases"] = alias_error
            continue
        seen_aliases.update({alias: target for alias in aliases})
        total_aliases += len(aliases)
        targets.append({"target": target, "aliases": aliases})
    if errors:
        raise SectionRollupError(errors)
    if total_aliases > MAX_TOTAL_ALIASES:
        raise SectionRollupError({"targets": f"历史科室值总数不能超过 {MAX_TOTAL_ALIASES} 个"})
    result: dict[str, Any] = {"version": version, "targets": targets}
    if updated_at is not None:
        result["updatedAt"] = updated_at.strip()
    return result


def build_rollup_index(rules: Mapping[str, Any]) -> dict[str, str]:
    """构建「原始科室值 → 目标科室」扁平映射。

    键序契约：目标名按规则顺序先插入（target → target），随后才是各目标的
    别名。``rollup_targets_in_order`` 因此还原规则的展示顺序。
    """
    index: dict[str, str] = {}
    for entry in rules.get("targets", []):
        target = str(entry.get("target") or "").strip()
        if not target:
            continue
        index.setdefault(target, target)
        for alias in entry.get("aliases", []):
            alias_text = str(alias or "").strip()
            if alias_text:
                index.setdefault(alias_text, target)
    return index


def rollup_targets_in_order(index: Mapping[str, str]) -> list[str]:
    """按规则顺序去重返回目标科室列表（依赖 build_rollup_index 的键序契约）。"""
    return list(dict.fromkeys(index.values()))


def resolve_section(value: object, index: Mapping[str, str] | None) -> str | None:
    """单一归集判定原语：命中返回目标科室名，未命中返回 ``None``（未归集）。"""
    if index is None or isinstance(value, bool) or not isinstance(value, str):
        return None
    return index.get(value.strip())


class SectionRollupStore:
    """基于 ``app_settings`` KV 的规则存取；独立键，不进入通用设置白名单。"""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def get(self) -> dict[str, Any]:
        """读取规则；缺失或存量值非法时回退内置默认规则（写路径始终先校验）。"""
        raw = self._db.get_app_settings().get(ROLLUP_SETTINGS_KEY)
        if not isinstance(raw, Mapping):
            return validate_section_rollup(DEFAULT_SECTION_ROLLUP)
        try:
            return validate_section_rollup(raw)
        except SectionRollupError:
            # 写路径保证合法；走到这里只可能是手工改动本地库，此时回退默认
            # 规则兜底而不是让整个看板不可用。
            return validate_section_rollup(DEFAULT_SECTION_ROLLUP)

    def save(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """校验并保存规则；``updatedAt`` 由存取层生成（UTC）。"""
        validated = validate_section_rollup(payload)
        stored = {
            "version": validated.get("version", 1),
            "updatedAt": _utc_now_iso(),
            "targets": validated["targets"],
        }
        self._db.update_app_settings({ROLLUP_SETTINGS_KEY: stored})
        return stored


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
