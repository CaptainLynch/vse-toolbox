# -*- coding: utf-8 -*-
"""科室归集规则：校验矩阵、归集原语与本地存取契约。"""

from __future__ import annotations

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
