# -*- coding: utf-8 -*-
"""sign-daily v2.0 配置数据：种子 + 本地改动、CSV 导入、备份与回滚（规格 §7 M1–M8）。"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import web.app as web_app
from core.db_manager import DatabaseManager

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def mods():
    web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=["sign-daily"])
    return (importlib.import_module("vse_plugins.sign_daily.settings"),
            importlib.import_module("vse_plugins.sign_daily.rules"))


SEED_ROSTER = [("张三", "车身科"), ("李四", "内饰科"), ("王五", "外饰科")]
SEED_RULES = [
    {"id": "LC01", "name": "前门内板", "remark": "", "aliases": "", "enabled": True},
    {"id": "LC02", "name": "翼子板", "remark": "非加强板", "aliases": "", "enabled": True},
]


def _store(mods, tmp_path: Path, roster=SEED_ROSTER, rules=SEED_RULES):
    SET, _ = mods
    db = DatabaseManager(db_path=tmp_path / "s.db")
    db.init_database()
    store = SET.SettingsStore(db, "p_test_", roster, rules)
    db.apply_plugin_migrations("test-settings", [store.migration()])
    return store, db


def _sources(store):
    return {row["name"]: (row["department"], row["source"]) for row in store.roster_rows()}


def test_layers_and_sources(mods, tmp_path):  # M2、M3
    SET, _ = mods
    store, _ = _store(mods, tmp_path)
    store.set_person("张三", "车体科")          # 改种子 -> 已修改
    store.set_person("赵六", "车身科")          # 新增 -> 本地新增
    store.set_person("李四", None)              # 删种子 -> 删除标记，不物理删除
    assert _sources(store) == {
        "张三": ("车体科", SET.SOURCE_MODIFIED), "赵六": ("车身科", SET.SOURCE_LOCAL),
        "李四": ("内饰科", SET.SOURCE_DELETED), "王五": ("外饰科", SET.SOURCE_SEED),
    }
    assert dict(store.roster()) == {"张三": "车体科", "赵六": "车身科", "王五": "外饰科"}
    store.revert_person("张三")
    store.set_person("赵六", None)              # 删本地新增的人：直接去掉
    assert dict(store.roster()) == {"张三": "车身科", "王五": "外饰科"}


def test_seed_upgrade_reconcile(mods, tmp_path):  # M4
    SET, _ = mods
    store, db = _store(mods, tmp_path)
    store.set_person("张三", "车体科")
    store.set_person("王五", "车体科")
    upgraded = SET.SettingsStore(db, "p_test_", [("张三", "车体科"), ("李四", "内饰科"), ("王五", "内饰科")], SEED_RULES)
    conflicts = upgraded.reconcile()
    # 张三：本地改动与新种子相同 -> 自动清除；王五：种子和本地都改过 -> 列出，本地优先
    assert [c["key"] for c in conflicts["roster"]] == ["王五"]
    assert dict(upgraded.roster())["王五"] == "车体科"
    assert {r["name"]: r["source"] for r in upgraded.roster_rows()}["张三"] == SET.SOURCE_SEED


def test_import_merge_replace_backup_and_restore(mods, tmp_path):  # M5–M7、验收 7、8
    SET, _ = mods
    store, _ = _store(mods, tmp_path)
    csv_text = ("责任工程师名称,责任工程师专业科室\n张三(z1),车体科\n新人甲(a1),车身科\n新人甲(a2),车身科\n"
                "冲突乙(b1),车身科\n冲突乙(b2),内饰科\n历史丙,结构工程科\n")
    plan = store.roster_import_plan(csv_text, replace=False)
    assert {k: len(plan[k]) for k in ("added", "changed", "removed", "conflicts", "errors")} == {
        "added": 1, "changed": 1, "removed": 0, "conflicts": 1, "errors": 1}
    assert plan["merged"] == 1  # 新人甲两行合并成 1 人
    store.commit_roster_import(plan)
    assert dict(store.roster()) == {"张三": "车体科", "李四": "内饰科", "王五": "外饰科", "新人甲": "车身科"}
    assert "冲突乙" not in dict(store.roster())

    replace = store.roster_import_plan("姓名,科室\n只剩我,车身科\n", replace=True)
    assert len(replace["removed"]) == 4
    store.commit_roster_import(replace)
    assert store.mode("roster") == SET.MODE_REPLACE and dict(store.roster()) == {"只剩我": "车身科"}

    backups = store.backups("roster")
    assert [b["reason"] for b in backups] == ["导入前", "导入前"]
    store.restore("roster", backups[0]["id"])  # 回到整体覆盖之前
    assert store.mode("roster") == SET.MODE_OVERLAY and "新人甲" in dict(store.roster())
    store.reset_seed("roster")
    assert dict(store.roster()) == dict(SEED_ROSTER)
    for _ in range(7):
        store.reset_seed("roster")
    assert len(store.backups("roster")) == SET.BACKUP_KEEP
    assert store.roster_csv().splitlines()[0] == "姓名,科室"


def test_rules_layers_import_and_export(mods, tmp_path):
    SET, R = mods
    store, _ = _store(mods, tmp_path)
    vocab = R.Vocabulary()
    store.set_rule("LC02", {"name": "翼子板", "remark": "非加强板、支架", "aliases": "", "enabled": False})
    store.set_rule(store.next_rule_id(), {"name": "顶盖", "remark": "", "aliases": "车顶", "enabled": True})
    sources = {row["id"]: row["source"] for row in store.rule_rows()}
    assert sources == {"LC01": SET.SOURCE_SEED, "LC02": SET.SOURCE_MODIFIED, "LC03": SET.SOURCE_LOCAL}
    assert [r.rule_id for r in store.rules(vocab)] == ["LC01", "LC03"]  # LC02 已停用
    assert R.classify_part("车顶", store.rules(vocab), vocab).result == R.RESULT_HIT  # 别名列
    plan = store.rules_import_plan("零件名称,备注,启用\n前门内板,,启用\n尾门外板,,启用\n坏,,也许\n", False, vocab)
    assert [e["id"] for e in plan["added"]] == ["LC04"] and len(plan["errors"]) == 1
    store.commit_rules_import(plan)
    assert "LC04" in {r.rule_id for r in store.rules(vocab)}
    exported = store.rules_csv().splitlines()
    assert exported[0] == "规则编号,零件名称,备注,别名,启用"
    assert "LC02,翼子板,非加强板、支架,,停用" in exported


def test_vocabulary_validation(mods, tmp_path):
    SET, R = mods
    store, _ = _store(mods, tmp_path)
    value = SET.default_vocabulary()
    value["globalExcludes"].append("堵件")
    store.save_vocabulary(SET.validate_vocabulary(value), "修改词表前")
    assert "堵件" in store.vocabulary()["globalExcludes"]
    for bad in ({**value, "orientation": ""}, {**value, "synonyms": []}, {**value, "suffixes": ["x" * 60]}):
        with pytest.raises(SET.SettingsError):
            SET.validate_vocabulary(bad)
    store.reset_seed("vocabulary")
    assert store.vocabulary() == SET.default_vocabulary()
