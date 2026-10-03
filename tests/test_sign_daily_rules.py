# -*- coding: utf-8 -*-
"""sign-daily v2.0 纯函数口径：解析、人员归属、长周期判定、指标与日变化。

用例取自需求规格 v2.0 的条款和 §11 验收用例；编号在每个测试的注释里。
"""

from __future__ import annotations

import csv
import importlib.util
import io
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "plugins" / "sign_daily"


def _load_rules():
    spec = importlib.util.spec_from_file_location("sign_daily_rules_under_test", PLUGIN_DIR / "rules.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


R = _load_rules()
DATA_DATE = date(2026, 10, 3)


def _row(serial: str = "S1", **values: object) -> dict[str, object]:
    base: dict[str, object] = {
        "流水单号": serial,
        "项目/车型": "F610M",
        "部门": "车身科",
        "申请人": "起草甲",
        "申请日期": "2026-09-23 10:00:00",
        "零件号": f"{serial}-P1",
        "零件名称": "前门内板",
        "加签人员": "",
        "应签人数": 2,
        "已签人数": 1,
        "未签人数": 1,
        "签署率": "50.00%",
        "待审批人员": "",
        "状态": "进行中",
    }
    for column in R.ROLE_COLUMNS:
        base.setdefault(column, "")
    base.update(values)
    return base


def _flow(serial: str = "S1", **values: object):
    result = R.build_flows([_row(serial, **values)])
    assert len(result.flows) == 1
    return result.flows[0]


ROSTER = R.Roster([
    ("丘昌州", "外饰科"),
    ("梁海峰", "内饰科"),
    ("车身甲", "车身科"),
    ("车体乙", "车体科"),
    ("吕金柱1", "车身科"),
    ("同名丙", "车身科"),
    ("同名丙", "车体科"),
    ("高义轩", "结构工程科"),
])


# ── §2 解析 ─────────────────────────────────────────────────────────


def test_missing_columns_are_listed_by_name():  # P1
    with pytest.raises(R.MissingColumnsError) as info:
        R.check_columns(["流水单号", "状态"])
    assert "零件号" in info.value.missing and "加签人员" in info.value.missing


def test_names_split_on_all_separators_and_strip_marks():  # P3、P4、A1
    people = R.parse_people("张三(未签)、李四，王五；赵六\n钱七（未签）、孙八(12345)、 None")
    assert people == [("张三", False), ("李四", True), ("王五", True), ("赵六", True), ("钱七", False), ("孙八", True)]
    assert R.parse_people(None) == [] and R.parse_people("None") == []


def test_any_row_unsigned_wins_and_inconsistency_is_reported():  # P2、§1 缺陷 11
    rows = [
        _row("S1", 冲压="张三(未签)", 待审批人员="张三"),
        _row("S1", 冲压="张三", 零件号="S1-P2", 待审批人员="张三"),
    ]
    result = R.build_flows(rows)
    assert result.flows[0].unsigned() == [("冲压", "张三")]
    assert {a["kind"] for a in result.anomalies} == {"rowSignersDiffer"}


def test_discarded_dropped_unknown_status_flagged():  # P6
    result = R.build_flows([_row("S1", 状态="已废弃"), _row("S2", 状态="挂起", 冲压="张三(未签)")])
    assert [f.serial for f in result.flows] == ["S2"]
    assert result.flows[0].in_flight
    assert any(a["kind"] == "unknownStatus" for a in result.anomalies)


def test_unsigned_mark_count_checked_against_field():  # P7
    result = R.build_flows([_row("S1", 冲压="张三(未签)、李四(未签)", 未签人数=1, 待审批人员="张三、李四")])
    assert [a["kind"] for a in result.anomalies] == ["unsignedCountDiffer"]


def test_duplicate_part_numbers_count_once():  # P9
    flow = R.build_flows([_row("S1"), _row("S1"), _row("S1", 零件号="S1-P2")]).flows[0]
    assert len(flow.parts) == 2


def test_add_sign_people_in_pending_are_recognized():  # P5，含「角色列已签又在加签列」
    flow = _flow(冲压="张三", 加签人员="张三(未签)、王五(未签)", 待审批人员="张三、王五", 未签人数=2)
    assert flow.add_sign_pending == ["张三", "王五"]
    assert flow.stage == R.STAGE_ADD_SIGN


def test_days_since_application():  # P8
    assert _flow().days(DATA_DATE) == 10


# ── §3 人员归属 ─────────────────────────────────────────────────────


def test_digit_suffix_fallback():  # A2
    hit = ROSTER.lookup("吕金柱")
    assert hit.status == "hit" and hit.department == "车身科" and hit.digit_fallback


def test_same_name_different_department_is_conflict():  # A4
    assert ROSTER.lookup("同名丙").status == "conflict"
    assert R.attribute("同名丙", "冲压", ROSTER).group == R.GROUP_CONFLICT


def test_history_department_not_redirected():  # A5
    attribution = R.attribute("高义轩", "车身", ROSTER)
    assert (attribution.chart, attribution.group) == (2, R.GROUP_HISTORY)


@pytest.mark.parametrize("name, column, chart, group", [
    ("丘昌州", "内外饰", 2, "外饰科"),        # 验收 1、A3
    ("梁海峰", "内外饰", 2, "内饰科"),        # 验收 1
    ("车身甲", "冲压", 2, "车身科"),          # 验收 3：在册的人不论在哪一列都进图2
    ("冲压丁", "冲压", 1, "冲压"),            # A6
    ("空调戊", "空调电子", 1, "空调电子/ES科"),  # 验收 5
    ("外饰己", "内外饰", 2, "内外饰（未在册）"),  # A7
    ("车身甲", "首席/总监", 3, "首席/总监"),     # 图3 按节点
])
def test_attribution_table(name, column, chart, group):
    attribution = R.attribute(name, column, ROSTER)
    assert (attribution.chart, attribution.group) == (chart, group)


def test_unregistered_internal_person_needs_entry_after_roster_removal():  # 验收 2
    roster = R.Roster([("丘昌州", "外饰科")])
    attribution = R.attribute("梁海峰", "内外饰", roster)
    assert attribution.group == "内外饰（未在册）" and attribution.needs_entry


def test_approver_label():  # A8
    assert R.approver_label(R.attribute("车身甲", "专家/经理", ROSTER)) == "车身科"
    assert R.approver_label(R.attribute("经理庚", "专家/经理", ROSTER)) == "未在册"


def test_person_area_override_merges_columns():  # A11
    flows = R.build_flows([
        _row("S1", 整车性能="潘炳洁(未签)", CAE="潘炳洁(未签)", 待审批人员="潘炳洁", 未签人数=2),
    ]).flows
    charts = R.owed_charts(flows, ROSTER, {"潘炳洁": "整车性能"})
    assert [(g["group"], g["personTimes"]) for g in charts["external"]] == [("整车性能", 1)]
    without = R.owed_charts(flows, ROSTER)
    assert sorted(g["group"] for g in without["external"]) == ["CAE", "整车性能"]


def test_flow_department_prefers_applicant_roster():  # A9、验收 6
    flow = _flow(部门="结构工程科", 申请人="车体乙")
    assert R.flow_department(flow, ROSTER) == ("车体科", False)
    unregistered = _flow(部门="结构工程科", 申请人="外人")
    assert R.flow_department(unregistered, ROSTER) == ("结构工程科（未拆分）", True)


# ── §6 三张图与明细表 ────────────────────────────────────────────────


def test_only_current_todo_counts_as_owed():  # A10、验收 9
    flow = _flow(冲压="冲压丁(未签)", **{"首席/总监": "总监辛(未签)"}, 待审批人员="冲压丁", 未签人数=2)
    charts = R.owed_charts([flow], ROSTER)
    assert charts["approval"] == []
    row = R.flow_rows([flow], DATA_DATE, ROSTER)[0]
    assert row["notRouted"] == 1
    assert R.todo_text(row).endswith("另 1 人未流转到")


def test_bar_height_counts_flows():  # 验收 4、G1
    flows = R.build_flows([
        _row(f"S{i}", 冲压="冲压丁(未签)", 待审批人员="冲压丁") for i in range(3)
    ]).flows
    group = R.owed_charts(flows, ROSTER)["external"][0]
    assert (group["group"], group["bars"][0]["count"], group["personTimes"], group["flows"], group["people"]) == (
        "冲压", 3, 3, 3, 1)


def test_same_person_two_countersign_columns_counts_once():  # §3 边缘场景
    flow = _flow(冲压="车身甲(未签)", 车身="车身甲(未签)", 待审批人员="车身甲", 未签人数=1)
    assert R.owed_charts([flow], ROSTER)["sections"][0]["bars"][0]["count"] == 1
    assert flow.countersign_required == 2


def test_add_sign_not_in_charts_but_marked_in_table():  # 验收 10
    flow = _flow(冲压="冲压丁", 待审批人员="加签壬", 已签人数=1, 未签人数=0)
    charts = R.owed_charts([flow], ROSTER)
    assert charts["external"] == charts["sections"] == charts["approval"] == []
    row = R.flow_rows([flow], DATA_DATE, ROSTER)[0]
    assert row["stage"] == R.STAGE_ADD_SIGN and row["todo"][0]["addSign"]
    assert "加签" in R.todo_text(row)


def test_completed_flows_never_owe():  # §3 已完成但签署率不到 100%
    flow = _flow(冲压="冲压丁(未签)", 待审批人员="冲压丁", 状态="已完成")
    assert R.owed_charts([flow], ROSTER)["external"] == []
    assert R.flow_rows([flow], DATA_DATE, ROSTER) == []


def test_section_groups_put_special_groups_last():
    flows = R.build_flows([
        _row("S1", 内外饰="外饰己(未签)", 待审批人员="外饰己"),
        _row("S2", 车身="车身甲(未签)", 待审批人员="车身甲"),
    ]).flows
    assert [g["group"] for g in R.owed_charts(flows, ROSTER)["sections"]] == ["车身科", "内外饰（未在册）"]


def test_table_sort_stage_then_long_cycle_then_days():  # 验收 19
    flows = R.build_flows([
        _row("A", **{"首席/总监": "车身甲(未签)"}, 待审批人员="车身甲", 申请日期="2026-09-01"),
        _row("B", 冲压="冲压丁(未签)", 待审批人员="冲压丁", 申请日期="2026-09-30"),
        _row("C", 冲压="冲压丁(未签)", 待审批人员="冲压丁", 申请日期="2026-09-10"),
        _row("D", 冲压="冲压丁(未签)", 待审批人员="冲压丁", 申请日期="2026-09-29"),
    ]).flows
    rows = R.flow_rows(flows, DATA_DATE, ROSTER, long_serials={"D"})
    assert [r["serial"] for r in rows] == ["D", "C", "B", "A"]
    assert R.part_label(rows[0]).startswith("【长周期】")


# ── §4 长周期 ───────────────────────────────────────────────────────

VOCAB = R.Vocabulary()
SEEDS = PLUGIN_DIR / "seeds"


def _csv(path: Path) -> list[list[str]]:
    return list(csv.reader(io.StringIO(R.decode_csv(path.read_bytes()))))


RULES = R.parse_long_cycle_table(_csv(SEEDS / "long_cycle.csv"), VOCAB)["rules"]


@pytest.mark.parametrize("name, expected, rule", [
    # §4 正反例表（验收 11），规则取随包种子 seeds/long_cycle.csv
    ("发罩内板", R.RESULT_HIT, "LC12"),
    ("机盖内板", R.RESULT_HIT, "LC12"),
    ("尾门上外板", R.RESULT_HIT, "LC11"),
    ("尾门下外板", R.RESULT_HIT, "LC11"),
    ("尾门外板上部", R.RESULT_HIT, "LC11"),
    ("左前门内板", R.RESULT_HIT, "LC01"),
    ("前门内板总成(LH)", R.RESULT_HIT, "LC01"),
    ("前保险杠蒙皮总成", R.RESULT_HIT, "LC26"),
    ("中控台总成", R.RESULT_HIT, "LC30"),
    ("前地板横梁", R.RESULT_EXCLUDED, "LC15"),
    ("后地板横梁总成", R.RESULT_EXCLUDED, "LC16"),
    ("翼子板加强板", R.RESULT_EXCLUDED, "LC14"),
    ("后侧围内板加强板", R.RESULT_EXCLUDED, "LC06"),
    ("前地板加强板", R.RESULT_EXCLUDED, "LC15"),
    ("翼子板支架", R.RESULT_EXCLUDED, ""),
    ("前照灯支架", R.RESULT_EXCLUDED, ""),
    ("顶盖饰条", R.RESULT_EXCLUDED, ""),
    ("仪表板线束", R.RESULT_EXCLUDED, ""),
    ("前门内板加强板", R.RESULT_SUSPECT, "LC01"),
    ("顶盖横梁", R.RESULT_SUSPECT, "LC09"),
    ("仪表板横梁", R.RESULT_SUSPECT, "LC29"),
    ("翼子板安装板", R.RESULT_SUSPECT, "LC14"),
    ("前蒙皮总成（含支架）", R.RESULT_HIT, "LC26"),
    ("前门外板 带支架", R.RESULT_EXCLUDED, ""),
    ("B柱上饰板总成", R.RESULT_MISS, ""),
    ("前门铰链", R.RESULT_MISS, ""),
    # 真实数据带来的两处修正
    ("后侧围下饰板总成", R.RESULT_HIT, "LC33"),
    ("前照灯焊合总成", R.RESULT_HIT, "LC36"),
    # F610M 里的疑似和相近未命中的例子（§4 末尾）
    ("前门外板加强板A", R.RESULT_SUSPECT, "LC02"),
    ("尾门外板左加强板", R.RESULT_SUSPECT, "LC11"),
    ("仪表板上体组件", R.RESULT_SUSPECT, "LC29"),
    ("前照灯LED模组", R.RESULT_SUSPECT, "LC36"),
    ("尾灯外装饰盖总成", R.RESULT_SUSPECT, "LC41"),
    ("前门饰板氛围灯总成", R.RESULT_SUSPECT, "LC31"),
    ("后位置灯总成", R.RESULT_MISS, ""),
    ("后贯穿灯右侧装饰件", R.RESULT_MISS, ""),
    ("尾门外装饰板总成", R.RESULT_MISS, ""),
    # 多条规则同时命中取核心词最长的一条
    ("天窗顶盖总成", R.RESULT_HIT, "LC08"),
])
def test_long_cycle_examples(name, expected, rule):
    result = R.classify_part(name, RULES, VOCAB)
    assert (result.result, result.rule_id) == (expected, rule)


def test_canonical_word_occupies_its_span():  # L2：「发动机罩」里的「机罩」不再替换
    assert R.normalize_part("发动机罩内板", VOCAB) == "发动机罩内板"


def test_list_item_with_slash_and_remark():  # §7 导入校验：「/」拆并列叫法，「非A、B」成排除词
    rule = R.build_rule("X", "前大灯总成/前照灯", "非支架、线束", VOCAB)
    assert rule.core_groups == (("前照灯",),) and rule.excludes == ("支架", "线束")


def test_review_list_and_conclusions():  # §7 复核时序、验收 12、13
    names = ["前门内板", "前门内板加强板", "前地板横梁", "前门铰链", ""]
    first = R.long_cycle_decisions(names, RULES, {}, VOCAB)
    assert first["counted"] == {"前门内板"}
    assert [(i["normalized"], i["checked"]) for i in first["review"]] == [("前门内板", True), ("前门内板加强板", False)]
    assert [i["normalized"] for i in first["excluded"]] == ["前地板横梁"]
    remembered = {"前门内板": True, "前门内板加强板": False}
    second = R.long_cycle_decisions(names, RULES, remembered, VOCAB)
    assert second["review"] == [] and second["counted"] == {"前门内板"}


# ── §5 指标与日变化 ─────────────────────────────────────────────────


def test_metrics_total_and_long_cycle():
    rows = [
        _row("S1", 冲压="甲、乙(未签)", 零件名称="前门内板", 状态="已完成", 应签人数=3, 已签人数=2, 签署率="66.67%"),
        _row("S1", 冲压="甲、乙(未签)", 零件号="S1-P2", 零件名称="前门铰链", 状态="已完成", 应签人数=3, 已签人数=2),
        _row("S2", 冲压="丙", 零件名称="前门铰链", 应签人数=1, 已签人数=1, 未签人数=0, 签署率="100%"),
    ]
    flows = R.build_flows(rows).flows
    long_parts = R.long_parts_of(flows, lambda n: R.classify_part(n, RULES, VOCAB).result == R.RESULT_HIT)
    result = R.summary(flows, long_parts)
    total, long = result["total"], result["longCycle"]
    assert (total["flows"], total["parts"], total["locked"], total["complete"]) == (2, 3, 2, 2)
    assert total["countersignRate"] == Decimal("66.7")  # 2/3 人次
    assert total["totalRate"] == Decimal("75.0")  # (2+1)/(3+1)，含加签
    assert total["t2Rate"] == Decimal("66.7")
    assert (long["flows"], long["parts"], long["locked"], long["t2Rate"]) == (1, 1, 1, Decimal("100.0"))


def test_zero_denominator_shows_dash():
    assert R.fmt_pct(R.display_pct(0, 0)) == "—"


def test_delta_uses_display_values():  # 验收 17、D4、D5
    today = {"total": {"totalRate": R.display_pct(8534, 10000), "flows": 185}}
    base = {"total": {"totalRate": Decimal("85.3"), "flows": 182}}
    delta = R.deltas(today, base)["total"]
    assert R.fmt_pct(today["total"]["totalRate"]) + R.fmt_delta(delta["totalRate"], percent=True) == "85.3%(+0.0%)"
    assert R.fmt_count_delta(delta["flows"]) == "(+3)"
    assert R.fmt_delta(Decimal("-0.3"), percent=True) == "(−0.3%)"
    assert R.fmt_count_delta(0) == ""  # D6


def test_baseline_modes():  # 验收 14、15、18
    assert R.baseline_mode(DATA_DATE, None) == {"show": False, "note": "首次生成，无日变化"}
    assert R.baseline_mode(DATA_DATE, date(2026, 10, 2)) == {"show": True, "note": ""}
    monday = date(2026, 10, 5)
    assert R.baseline_mode(monday, date(2026, 10, 2))["note"] == "括号内为较 10-02 的变化"
    assert not R.baseline_mode(DATA_DATE, date(2026, 9, 1))["show"]
    assert R.baseline_mode(DATA_DATE, DATA_DATE) == {"show": False, "note": ""}


def test_snapshot_coverage():  # D2、R4
    assert R.snapshot_covers({"kind": "all"}, ["S1"])
    assert R.snapshot_covers({"kind": "watchlist", "serials": ["S1", "S2"]}, ["S1"])
    assert not R.snapshot_covers({"kind": "watchlist", "serials": ["S1"]}, ["S1", "S9"])


def test_suffix_alternative_after_slash_is_not_a_core_word():  # 「前蒙皮总成/组件」
    rule = R.build_rule("X", "前蒙皮总成/组件", "", VOCAB)
    assert rule.core_groups == (("前蒙皮",),)
    assert R.classify_part("车门组件", [rule], VOCAB).result == R.RESULT_MISS


# ── §7 种子与导入校验 ───────────────────────────────────────────────


def test_long_cycle_seed_matches_received_list():  # 10-03：43 项，4 项带排除，8 项带「/」
    assert len(RULES) == 43
    assert sum(1 for rule in RULES if rule.excludes) == 4
    assert {rule.rule_id for rule in RULES if len(rule.core_groups) > 1} == {"LC25"}


def test_roster_seed_contents():  # M1、R8
    rows = _csv(SEEDS / "roster.csv")
    assert rows[0] == ["姓名", "科室"]
    parsed = R.parse_roster_table(rows)
    assert not parsed["errors"] and not parsed["conflicts"]
    assert len(parsed["entries"]) == 784  # 794 行合并同名后 778 人，另加 6 人
    assert all(not entry["ids"] for entry in parsed["entries"])  # 种子不带工号
    roster = R.Roster((e["name"], e["department"]) for e in parsed["entries"])
    for name, department in [("高义轩", "车身科"), ("滕平", "车身科"), ("韦逢义", "车身科"), ("梁海峰", "内饰科"),
                             ("铁盛武", "内饰科"), ("韦孔辉", "内饰科"), ("段大禄", "内饰科")]:
        assert roster.lookup(name).department == department
    hit = roster.lookup("吕金柱")  # A2：TDC 纯姓名命中花名册「吕金柱1」
    assert (hit.status, hit.matched_name, hit.digit_fallback) == ("hit", "吕金柱1", True)


def test_roster_import_validation():  # §7 导入校验、验收 7、8
    rows = [
        ["责任工程师名称", "责任工程师专业科室"],
        ["张三(z001)", "车身科"],
        ["张三（z002）", "车身科"],
        ["李四(l001)", "车体科"],
        ["李四(l002)", "内饰科"],
        ["王五(w001)", "结构工程科"],
        ["赵六", "集成科"],
        ["", ""],
    ]
    parsed = R.parse_roster_table(rows)
    assert parsed["entries"] == [{"name": "张三", "department": "车身科", "ids": ["z001", "z002"]}]
    assert parsed["merged"] == 1
    assert parsed["conflicts"] == [{"name": "李四", "departments": ["内饰科", "车体科"]}]
    assert [e["line"] for e in parsed["errors"]] == [6, 7]
    assert "历史值" in parsed["errors"][0]["text"]
    assert R.parse_roster_table([["名字", "部门"]])["errors"][0]["text"] == "表头要有姓名列和科室列"


def test_csv_decoding_accepts_gbk():
    assert R.decode_csv("零件名称,备注\n".encode("gbk")) == "零件名称,备注\n"
    assert R.decode_csv("\ufeff零件名称".encode("utf-8")) == "零件名称"


def test_conclusions_survive_synonym_changes():  # §4：规则或词表改动后，已有的人工结论不变
    without_alias = R.Vocabulary(synonyms={k: v for k, v in R.DEFAULT_SYNONYMS.items() if k != "前照灯"})
    first = R.long_cycle_decisions(["前大灯总成"], RULES, {}, without_alias)
    assert first["review"] == [] and first["counted"] == set()  # 未命中，用户手工判为不纳入
    remembered = {R.conclusion_key("前大灯总成"): False}
    after = R.long_cycle_decisions(["前大灯总成"], RULES, remembered, VOCAB)
    assert R.classify_part("前大灯总成", RULES, VOCAB).result == R.RESULT_HIT
    assert after["review"] == [] and after["counted"] == set()


def test_generated_rule_ids_do_not_collide_with_explicit_ones():
    table = [["规则编号", "零件名称", "备注"], ["", "前门内板", ""], ["LC01", "后侧门外板", ""], ["LC01", "顶盖", ""]]
    parsed = R.parse_long_cycle_table(table)
    assert [rule.rule_id for rule in parsed["rules"]] == ["LC02", "LC01"]
    assert parsed["errors"] == [{"line": 4, "text": "规则编号「LC01」重复"}]


def test_pending_empty_is_reported():  # §8：会签列有未签但待审批人员为空
    result = R.build_flows([_row("S1", 冲压="冲压丁(未签)", 待审批人员="")])
    assert any(a["kind"] == "pendingEmpty" for a in result.anomalies)
    row = R.flow_rows(result.flows, DATA_DATE, ROSTER)[0]
    assert row["stage"] == R.STAGE_COUNTERSIGN and R.todo_text(row).startswith("—")
