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
- 匹配口径（2026-09-26 生产反馈后升级）：真实科室值常带英文缩写前缀
  （如 ``BE 结构工程科``），匹配先做空白归一，再按三级**全等**判定——
  ① 折叠空白后的全值精确；② 去空格后的全值精确；③ 剥一层「拉丁/数字
  token + 空格」前缀后的余部精确。**不做任意包含/子串匹配**：
  ``非车体科``、``车体科/内饰科`` 这类值必须落「未归集」，子串扫描会误归集。
  无空格分隔的前缀写法（``BE结构工程科``）不自动剥离，需登记完整历史值。
- 保存（strict）按去空格形态查重，跨目标冲突在保存时逐字段报错；读取
  （宽松）不拦截存量载荷，跨目标冲突键由 ``build_rollup_index`` 显式置为
  ``None``（命中即未归集），绝不按规则顺序静默择一。
- 未配置规则时调用方应传 ``None`` 并保持既有原始值行为。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Mapping

from core.db_manager import DatabaseManager

ROLLUP_SETTINGS_KEY = "sectionRollup"

MAX_TARGETS = 24
MAX_ALIASES_PER_TARGET = 40
MAX_TOTAL_ALIASES = 200
MAX_NAME_CHARS = 40
MAX_JSON_BYTES = 64 * 1024

#: 零宽字符族：与空白一并从匹配形态中移除（字符集显式定义，不做 Unicode 等价合并）。
_ZERO_WIDTH_CHARS = "\u200b\u200c\u200d\ufeff"
#: 前缀剥离只认「拉丁字母/数字 token + 单个空格」，只剥一层且余部必须精确命中。
_LATIN_PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9]+ ")
_MISSING = object()

_UNASSIGNED_LABEL = "未归集"

# 默认科室归集规则（2026-09-29 用户提供完整「历史科室 → 现行科室」对照清单；
# 2026-09-30 G34 更正：「结构工程科」「BE 结构工程科」移入车身科——它们是
# 车身科的历史名，不是车体科的）。
# 仅在本地从未保存过规则时生效（整体让位于已存规则，旧默认存量经幂等迁移，
# 见 SectionRollupStore.get）；WebUI 归集面板加载的是生效规则、保存后即持久化。
# identity 映射（科室名=目标名）不列入别名。
DEFAULT_SECTION_ROLLUP: dict[str, Any] = {
    "version": 1,
    "targets": [
        {
            "target": "车身科",
            "aliases": [
                "车门及附件工程科",
                "车身工程科",
                "CA 车门及附件工程科",
                "车门及附件科",
                "结构工程科",
                "BE 结构工程科",
            ],
        },
        {
            "target": "车体科",
            "aliases": [
                "车身规划及工艺工程科",
                "制造工程科",
                "车身工装工程科",
                "车体工程科",
            ],
        },
        {
            "target": "内饰科",
            "aliases": [
                "内饰设计科",
                "内饰工程科",
                "安全集成工程科",
            ],
        },
        {
            "target": "外饰科",
            "aliases": [
                "视觉工程科",
                "外饰工程科",
                "EXT 外饰工程科",
                "模具及装备科",
                "外饰设计科",
            ],
        },
        {
            "target": "车体架构集成科",
            "aliases": [
                "尺寸工程科",
                "项目集成管理科",
                "架构集成科",
                "车体集成科",
                "材料工程科",
                "BI 车体集成科",
            ],
        },
    ],
}

# 上一版内置默认（G34 种子更正前）：仅供存量规则的幂等迁移判定，
# 不再直接生效；用户在旧默认基础上做过任何增删改都不属于该形态，一律不动。
_PREVIOUS_DEFAULT_SECTION_ROLLUP: dict[str, Any] = {
    "version": 1,
    "targets": [
        {
            "target": "车身科",
            "aliases": [
                "车门及附件工程科",
                "车身工程科",
                "CA 车门及附件工程科",
                "车门及附件科",
            ],
        },
        {
            "target": "车体科",
            "aliases": [
                "结构工程科",
                "车身规划及工艺工程科",
                "制造工程科",
                "BE 结构工程科",
                "车身工装工程科",
                "车体工程科",
            ],
        },
        {
            "target": "内饰科",
            "aliases": [
                "内饰设计科",
                "内饰工程科",
                "安全集成工程科",
            ],
        },
        {
            "target": "外饰科",
            "aliases": [
                "视觉工程科",
                "外饰工程科",
                "EXT 外饰工程科",
                "模具及装备科",
                "外饰设计科",
            ],
        },
        {
            "target": "车体架构集成科",
            "aliases": [
                "尺寸工程科",
                "项目集成管理科",
                "架构集成科",
                "车体集成科",
                "材料工程科",
                "BI 车体集成科",
            ],
        },
    ],
}


def _matches_previous_default(validated: Mapping[str, Any]) -> bool:
    """存量规则（宽松校验后）是否与上一版内置默认完全一致（不含 updatedAt）。"""
    if validated.get("version") != _PREVIOUS_DEFAULT_SECTION_ROLLUP.get("version"):
        return False
    return validated.get("targets") == _PREVIOUS_DEFAULT_SECTION_ROLLUP.get("targets")


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


def _norm_c(value: object) -> str:
    """折叠空白形态：移除零宽字符、去首尾空白、连续空白折叠为单个半角空格。"""
    if not isinstance(value, str):
        return ""
    cleaned = "".join("" if char in _ZERO_WIDTH_CHARS else char for char in value)
    return " ".join(cleaned.split())


def _norm_s(value: object) -> str:
    """去空格形态：在折叠形态上移除全部半角空格（仅用于比较与查重）。"""
    return _norm_c(value).replace(" ", "")


def validate_section_rollup(payload: object, *, strict: bool = True) -> dict[str, Any]:
    """校验并规范化规则载荷；非法时抛出带逐字段信息的 :class:`SectionRollupError`。

    ``strict=True``（保存路径）额外按去空格形态查重：不同目标下出现同一
    去空格键属跨目标冲突，同目标重复亦报错。``strict=False``（读取路径）
    跳过该查重，让 ``build_rollup_index`` 把冲突键显式置为未归集，避免手工
    改动过的存量载荷让整个看板不可用。
    """
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
    if strict and not errors:
        # 第三趟（仅保存路径）：去空格形态查重。空白归一让「BE 结构工程科」与
        # 「BE结构工程科」成为同一个键，跨目标登记同一键会让匹配结果取决于
        # 顺序，必须在保存时显式拒绝，而不是靠读取顺序静默择一。
        norm_owners: dict[str, tuple[str, str]] = {}
        for position, entry in enumerate(targets, start=1):
            fields = [(entry["target"], f"targets.{position}.target")]
            fields.extend(
                (alias, f"targets.{position}.aliases") for alias in entry["aliases"]
            )
            for name, field in fields:
                key = _norm_s(name)
                if not key:
                    continue
                previous = norm_owners.get(key)
                if previous is None:
                    norm_owners[key] = (entry["target"], field)
                elif previous[0] != entry["target"]:
                    errors[field] = f"忽略空格后与目标科室「{previous[0]}」的登记值冲突：{name}"
                else:
                    errors[field] = f"忽略空格后重复：{name}"
    if errors:
        raise SectionRollupError(errors)
    if total_aliases > MAX_TOTAL_ALIASES:
        raise SectionRollupError({"targets": f"历史科室值总数不能超过 {MAX_TOTAL_ALIASES} 个"})
    result: dict[str, Any] = {"version": version, "targets": targets}
    if updated_at is not None:
        result["updatedAt"] = updated_at.strip()
    return result


def build_rollup_index(rules: Mapping[str, Any]) -> dict[str, str | None]:
    """构建「匹配键 → 目标科室」索引。

    每个目标名/别名同时登记折叠空白（``_norm_c``）与去空格（``_norm_s``）两个
    键形；纯中文名两形态同键，索引形状与旧版一致。键序契约：目标名按规则顺序
    先插入，随后才是各目标的别名——``rollup_targets_in_order`` 据此还原展示顺序。
    跨目标冲突键（仅可能来自宽松读取的存量/手工载荷）显式置为 ``None``：
    命中该键一律按未归集处理，绝不按顺序静默择一。
    """
    index: dict[str, str | None] = {}
    for entry in rules.get("targets", []):
        target = str(entry.get("target") or "").strip()
        if not target:
            continue
        names = [target]
        names.extend(str(alias or "").strip() for alias in entry.get("aliases", []))
        for name in names:
            if not name:
                continue
            for key in {_norm_c(name), _norm_s(name)}:
                if not key:
                    continue
                existing = index.get(key, _MISSING)
                if existing is _MISSING:
                    index[key] = target
                elif existing is not None and existing != target:
                    index[key] = None
    return index


def rollup_targets_in_order(index: Mapping[str, str | None]) -> list[str]:
    """按规则顺序去重返回目标科室列表（依赖 build_rollup_index 的键序契约）。"""
    return [target for target in dict.fromkeys(index.values()) if target]


def _match_section(value: str, index: Mapping[str, str | None]) -> str | None:
    """三级全等匹配内核：折叠精确 → 去空格精确 → 剥前缀后精确。

    冲突键（值为 ``None``）命中即返回未归集（``None``），不再尝试其余键形；
    键不存在才继续下一级。
    """
    collapsed = _norm_c(value)
    if not collapsed:
        return None
    hit = index.get(collapsed, _MISSING)
    if hit is not _MISSING:
        return hit
    space_free = _norm_s(value)
    if space_free != collapsed:
        hit = index.get(space_free, _MISSING)
        if hit is not _MISSING:
            return hit
    stripped = _LATIN_PREFIX_PATTERN.sub("", collapsed, count=1)
    if stripped and stripped != collapsed:
        hit = index.get(stripped, _MISSING)
        if hit is _MISSING and " " in stripped:
            hit = index.get(stripped.replace(" ", ""), _MISSING)
        if hit is not _MISSING:
            return hit
    return None


def resolve_section(value: object, index: Mapping[str, str | None] | None) -> str | None:
    """单一归集判定原语：命中返回目标科室名，未命中返回 ``None``（未归集）。"""
    if index is None or isinstance(value, bool) or not isinstance(value, str):
        return None
    return _match_section(value, index)


class SectionRollupStore:
    """基于 ``app_settings`` KV 的规则存取；独立键，不进入通用设置白名单。"""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def get(self) -> dict[str, Any]:
        """读取规则；缺失或存量值非法时回退内置默认规则（写路径始终先校验）。

        读取走宽松校验（不做去空格查重拦截），跨目标冲突键由索引构建显式
        置为未归集，保证手工改动过的存量载荷不会让整个看板不可用。

        幂等迁移（G34 种子更正）：存量规则与**上一版**内置默认完全一致
        （version 与 targets 深相等；``updatedAt`` 不参与比较）即视为用户
        从未自定义，直接生效新默认。读取路径保持只读、不回写——迁移可重复
        执行且结果一致，用户下次在面板保存时自然落盘；任何自定义过的规则
        一律原样返回。
        """
        raw = self._db.get_app_settings().get(ROLLUP_SETTINGS_KEY)
        if not isinstance(raw, Mapping):
            return validate_section_rollup(DEFAULT_SECTION_ROLLUP)
        try:
            validated = validate_section_rollup(raw, strict=False)
        except SectionRollupError:
            # 写路径保证合法；走到这里只可能是手工改动本地库，此时回退默认
            # 规则兜底而不是让整个看板不可用。
            return validate_section_rollup(DEFAULT_SECTION_ROLLUP)
        if _matches_previous_default(validated):
            return validate_section_rollup(DEFAULT_SECTION_ROLLUP)
        return validated

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
