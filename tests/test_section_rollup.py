# -*- coding: utf-8 -*-
"""科室归集规则：校验矩阵、归集原语与本地存取契约。"""

from __future__ import annotations

import copy

import pytest

from core.section_rollup import (
    DEFAULT_SECTION_ROLLUP,
    ROLLUP_SETTINGS_KEY,
    SectionRollupError,
    SectionRollupStore,
    build_rollup_index,
    resolve_section,
    rollup_targets_in_order,
    validate_section_rollup,
)
from core.settings_store import DEFAULTS as SETTINGS_DEFAULTS


def _rules(**overrides) -> dict:
    base = {
        "targets": [
            {"target": "车身科", "aliases": ["结构工程科", "车门附件科"]},
            {"target": "内饰科", "aliases": []},
        ],
    }
    base.update(overrides)
    return base


def test_validate_keeps_rule_order_and_trims_values() -> None:
    rules = validate_section_rollup(
        {
            "targets": [
                {"target": " 车身科 ", "aliases": [" 结构工程科 ", "车门附件科"]},
                {"target": "内饰科", "aliases": ["前内饰科"]},
            ],
        }
    )

    assert [entry["target"] for entry in rules["targets"]] == ["车身科", "内饰科"]
    assert rules["targets"][0]["aliases"] == ["结构工程科", "车门附件科"]
    assert rules["targets"][1]["aliases"] == ["前内饰科"]
    assert rules["version"] == 1


def test_validate_rejects_structural_problems() -> None:
    with pytest.raises(SectionRollupError) as empty:
        validate_section_rollup({"targets": []})
    assert "targets" in empty.value.fields

    with pytest.raises(SectionRollupError):
        validate_section_rollup({"targets": [{"target": "   ", "aliases": []}]})

    with pytest.raises(SectionRollupError):
        validate_section_rollup("not-a-mapping")

    with pytest.raises(SectionRollupError):
        validate_section_rollup({"targets": [], "unexpected": 1})


def test_validate_rejects_duplicate_targets_and_cross_target_alias() -> None:
    with pytest.raises(SectionRollupError) as duplicate_target:
        validate_section_rollup(
            {
                "targets": [
                    {"target": "车身科", "aliases": []},
                    {"target": "车身科", "aliases": []},
                ],
            }
        )
    assert "目标科室重复" in duplicate_target.value.fields["targets.2.target"]

    with pytest.raises(SectionRollupError) as cross_alias:
        validate_section_rollup(
            {
                "targets": [
                    {"target": "车身科", "aliases": ["结构工程科"]},
                    {"target": "内饰科", "aliases": ["结构工程科"]},
                ],
            }
        )
    assert "只能归属一个目标科室" in cross_alias.value.fields["targets.2.aliases"]

    with pytest.raises(SectionRollupError) as alias_is_target:
        validate_section_rollup(
            {
                "targets": [
                    {"target": "车身科", "aliases": []},
                    {"target": "内饰科", "aliases": ["车身科"]},
                ],
            }
        )
    assert "不能与目标科室同名" in alias_is_target.value.fields["targets.2.aliases"]


def test_validate_rejects_blank_and_non_string_aliases_without_cascading() -> None:
    with pytest.raises(SectionRollupError) as blank:
        validate_section_rollup(
            {
                "targets": [
                    {"target": "车身科", "aliases": ["结构工程科", "  "]},
                    {"target": "内饰科", "aliases": ["结构工程科"]},
                ],
            }
        )
    # 出错条目不登记别名，后续条目不得产生级联误报。
    assert "历史科室值不能为空" in blank.value.fields["targets.1.aliases"]
    assert "targets.2" not in blank.value.fields


def test_build_rollup_index_orders_targets_before_aliases() -> None:
    index = build_rollup_index(_rules())

    assert index["车身科"] == "车身科"
    assert index["结构工程科"] == "车身科"
    assert index["车门附件科"] == "车身科"
    assert rollup_targets_in_order(index) == ["车身科", "内饰科"]


def test_resolve_section_is_the_single_rollup_primitive() -> None:
    index = build_rollup_index(_rules())

    assert resolve_section("车身科", index) == "车身科"
    assert resolve_section(" 结构工程科 ", index) == "车身科"
    assert resolve_section("未知历史科室", index) is None
    assert resolve_section("", index) is None
    assert resolve_section(None, index) is None
    assert resolve_section("车身科", None) is None


def test_store_roundtrip_and_defaults_are_independent_of_settings_whitelist(
    tmp_db,
) -> None:
    store = SectionRollupStore(tmp_db)

    defaults = store.get()
    assert [entry["target"] for entry in defaults["targets"]] == [
        entry["target"] for entry in DEFAULT_SECTION_ROLLUP["targets"]
    ]

    saved = store.save(_rules())
    assert saved["updatedAt"]
    reloaded = store.get()
    assert reloaded["targets"] == saved["targets"]

    settings_keys = tmp_db.get_app_settings().keys()
    assert ROLLUP_SETTINGS_KEY in settings_keys
    # 通用设置白名单不受理该键（独立于 SettingsStore）。
    assert ROLLUP_SETTINGS_KEY not in SETTINGS_DEFAULTS


def test_store_falls_back_to_defaults_on_invalid_stored_payload(tmp_db) -> None:
    store = SectionRollupStore(tmp_db)
    store.save(_rules())
    tmp_db.update_app_settings({ROLLUP_SETTINGS_KEY: {"targets": "corrupted"}})

    rules = store.get()

    assert [entry["target"] for entry in rules["targets"]] == [
        entry["target"] for entry in DEFAULT_SECTION_ROLLUP["targets"]
    ]


def test_validate_rejects_alias_same_as_own_target() -> None:
    with pytest.raises(SectionRollupError) as caught:
        validate_section_rollup(
            {
                "targets": [
                    {"target": "车身科", "aliases": ["车身科"]},
                    {"target": "内饰科", "aliases": []},
                ],
            }
        )
    assert "不能与目标科室同名" in caught.value.fields["targets.1.aliases"]


def test_validate_rejects_alias_colliding_with_later_target() -> None:
    """前序别名撞后序目标：若放行，build_rollup_index 会令后序目标自绑定被抢占。"""
    with pytest.raises(SectionRollupError) as caught:
        validate_section_rollup(
            {
                "targets": [
                    {"target": "车身科", "aliases": ["内饰科"]},
                    {"target": "内饰科", "aliases": []},
                ],
            }
        )
    assert "不能与目标科室同名" in caught.value.fields["targets.1.aliases"]


def test_validate_rejects_reserved_unassigned_label_as_target_or_alias() -> None:
    with pytest.raises(SectionRollupError) as as_target:
        validate_section_rollup({"targets": [{"target": "未归集", "aliases": []}]})
    assert "不能使用系统保留名" in as_target.value.fields["targets.1.target"]

    with pytest.raises(SectionRollupError) as as_alias:
        validate_section_rollup({"targets": [{"target": "车身科", "aliases": ["未归集"]}]})
    assert "不能使用系统保留名" in as_alias.value.fields["targets.1.aliases"]


def test_resolve_section_matches_prefixed_and_whitespace_variants() -> None:
    """生产数据形态（2026-09-26）：科室值带英文缩写前缀 + 空格。

    匹配口径：空白归一（折叠空白/去零宽字符）+ 剥一层「拉丁/数字 token + 空格」
    前缀后的精确全等；不做任意包含匹配。
    """
    index = build_rollup_index(
        {
            "targets": [
                {"target": "车身科", "aliases": ["结构工程科", "车门附件科"]},
                {"target": "车体科", "aliases": []},
                {"target": "车体架构集成科", "aliases": []},
            ],
        }
    )
    # 前缀剥离（一层，拉丁/数字 token + 空格）
    assert resolve_section("BE 结构工程科", index) == "车身科"
    assert resolve_section("BI 车体科", index) == "车体科"
    # 空白变体
    assert resolve_section("BE  结构工程科", index) == "车身科"
    assert resolve_section("BE　结构工程科", index) == "车身科"
    assert resolve_section(" 结构工程科 ", index) == "车身科"
    assert resolve_section("车体架构集成科", index) == "车体架构集成科"
    # 零宽字符
    assert resolve_section("B\u200bE 结构工程科", index) == "车身科"
    # 无空格分隔：去空格键形精确命中（登记完整历史值「BE结构工程科」即可）
    index_with_full = build_rollup_index(
        {"targets": [{"target": "车身科", "aliases": ["BE结构工程科"]}]}
    )
    assert resolve_section("BE 结构工程科", index_with_full) == "车身科"


def test_resolve_section_rejects_containment_shapes() -> None:
    """不做包含匹配：否定值、多科室合并格、无空格前缀必须落未归集。

    任意子串扫描会把「非车体科」「车体科/内饰科」这类值误归集（顾问审计
    否决项）；「车体架构集成科」也不得因子串关系被并进「车体科」。
    """
    index = build_rollup_index(
        {
            "targets": [
                {"target": "车体科", "aliases": ["结构工程科"]},
                {"target": "车体架构集成科", "aliases": []},
            ],
        }
    )
    assert resolve_section("非车体科", index) is None
    assert resolve_section("车体科/内饰科", index) is None
    assert resolve_section("BE结构工程科", index) is None
    assert resolve_section("车体科二组", index) is None


def test_validate_rejects_normalized_conflicts_on_save() -> None:
    """保存（strict）按去空格形态查重：跨目标冲突逐字段报错，同目标重复亦报错。

    空白归一让「BE 结构工程科」与「BE结构工程科」成为同一个键；跨目标登记
    同一键会让匹配结果取决于规则顺序，必须在保存时显式拒绝。
    """
    with pytest.raises(SectionRollupError) as cross_target:
        validate_section_rollup(
            {
                "targets": [
                    {"target": "车身科", "aliases": ["BE 结构工程科"]},
                    {"target": "内饰科", "aliases": ["BE结构工程科"]},
                ],
            }
        )
    assert "忽略空格后与目标科室" in cross_target.value.fields["targets.2.aliases"]

    with pytest.raises(SectionRollupError) as same_target:
        validate_section_rollup(
            {"targets": [{"target": "车体科", "aliases": ["BI 车体科", "BI  车体科"]}]}
        )
    assert "忽略空格后重复" in same_target.value.fields["targets.1.aliases"]


def test_store_read_is_lenient_about_normalized_conflicts(tmp_db) -> None:
    """读取（宽松）不拦截存量载荷；跨目标冲突键显式置未归集，不按顺序静默择一。"""
    store = SectionRollupStore(tmp_db)
    tmp_db.update_app_settings(
        {
            ROLLUP_SETTINGS_KEY: {
                "version": 1,
                "targets": [
                    {"target": "车身科", "aliases": ["BE 结构工程科"]},
                    {"target": "内饰科", "aliases": ["BE结构工程科"]},
                ],
            }
        }
    )

    rules = store.get()
    assert [entry["target"] for entry in rules["targets"]] == ["车身科", "内饰科"]

    index = build_rollup_index(rules)
    # 去空格键形被两个目标同时登记 → 显式冲突 → 未归集；
    # 折叠键形只有车身科一个主张 → 正常归集（无顺序择一）。
    assert resolve_section("BE结构工程科", index) is None
    assert resolve_section("BE 结构工程科", index) == "车身科"


def test_default_section_rollup_seeds_full_historical_mapping() -> None:
    """F7（2026-09-29）+ G34（2026-09-30）更正：默认规则种入完整「历史科室 →
    现行科室」对照；「结构工程科」「BE 结构工程科」是车身科的历史名，归
    车身科（原误挂车体科）。

    仅在本地从未保存规则时生效；测试锁定 5 目标 / 24 别名全部可解析，
    未知值仍落「未归集」（None）。带英文缩写前缀的写法（BE/BI/CA/EXT）
    直接登记完整历史值，不依赖前缀剥离。
    """
    validated = validate_section_rollup(DEFAULT_SECTION_ROLLUP)
    assert len(validated["targets"]) == 5
    assert sum(len(entry["aliases"]) for entry in validated["targets"]) == 24
    body_aliases = next(
        entry["aliases"] for entry in validated["targets"] if entry["target"] == "车身科"
    )
    vehicle_body_aliases = next(
        entry["aliases"] for entry in validated["targets"] if entry["target"] == "车体科"
    )
    assert body_aliases == [
        "车门及附件工程科",
        "车身工程科",
        "CA 车门及附件工程科",
        "车门及附件科",
        "结构工程科",
        "BE 结构工程科",
    ]
    assert vehicle_body_aliases == [
        "车身规划及工艺工程科",
        "制造工程科",
        "车身工装工程科",
        "车体工程科",
    ]
    index = build_rollup_index(validated)
    expectations = {
        "结构工程科": "车身科",
        "BE 结构工程科": "车身科",
        "车身规划及工艺工程科": "车体科",
        "制造工程科": "车体科",
        "车体工程科": "车体科",
        "尺寸工程科": "车体架构集成科",
        "项目集成管理科": "车体架构集成科",
        "架构集成科": "车体架构集成科",
        "车体集成科": "车体架构集成科",
        "材料工程科": "车体架构集成科",
        "BI 车体集成科": "车体架构集成科",
        "内饰设计科": "内饰科",
        "内饰工程科": "内饰科",
        "安全集成工程科": "内饰科",
        "视觉工程科": "外饰科",
        "外饰工程科": "外饰科",
        "EXT 外饰工程科": "外饰科",
        "模具及装备科": "外饰科",
        "外饰设计科": "外饰科",
        "车门及附件工程科": "车身科",
        "车身工程科": "车身科",
        "CA 车门及附件工程科": "车身科",
        "车门及附件科": "车身科",
        "内饰科": "内饰科",
        "车体架构集成科": "车体架构集成科",
        "某个未来才出现的历史科室": None,
    }
    for raw, expected in expectations.items():
        assert resolve_section(raw, index) == expected, raw


def test_store_migrates_stored_previous_default_to_new_seed(tmp_db) -> None:
    """G34 幂等迁移：存量规则与旧默认完全一致（用户从未自定义）→ 读取即
    生效新默认；updatedAt 不参与比较；读取路径不回写。"""
    previous = copy.deepcopy(_previous_default_payload())
    tmp_db.update_app_settings(
        {ROLLUP_SETTINGS_KEY: {**previous, "updatedAt": "2026-09-29T00:00:00.000Z"}}
    )

    store = SectionRollupStore(tmp_db)
    rules = store.get()

    assert rules == validate_section_rollup(DEFAULT_SECTION_ROLLUP)
    index = build_rollup_index(rules)
    assert resolve_section("结构工程科", index) == "车身科"
    assert resolve_section("BE 结构工程科", index) == "车身科"
    # 幂等：再次读取结果一致；且未回写（存储里仍是旧载荷 + 原 updatedAt）。
    assert store.get() == rules
    stored = tmp_db.get_app_settings()[ROLLUP_SETTINGS_KEY]
    assert stored["updatedAt"] == "2026-09-29T00:00:00.000Z"
    assert stored["targets"] == previous["targets"]


def test_store_keeps_custom_rules_untouched_by_seed_migration(tmp_db) -> None:
    """G34 迁移只认旧默认形态：用户自定义（含基于旧默认的增删改）一律不动。"""
    custom = {
        "version": 1,
        "updatedAt": "2026-09-30T08:00:00.000Z",
        "targets": [
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
        ],
    }
    tmp_db.update_app_settings({ROLLUP_SETTINGS_KEY: custom})

    store = SectionRollupStore(tmp_db)
    rules = store.get()

    assert rules["targets"] == custom["targets"]
    index = build_rollup_index(rules)
    # 用户明确把「结构工程科」挂在车体科：迁移不得偷偷改写。
    assert resolve_section("结构工程科", index) == "车体科"


def _previous_default_payload() -> dict[str, object]:
    """旧默认载荷（G34 前的 DEFAULT_SECTION_ROLLUP 形态，从模块常量取）。"""
    from core.section_rollup import _PREVIOUS_DEFAULT_SECTION_ROLLUP

    return copy.deepcopy(_PREVIOUS_DEFAULT_SECTION_ROLLUP)
