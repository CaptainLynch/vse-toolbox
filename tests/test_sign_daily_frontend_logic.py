# -*- coding: utf-8 -*-
"""签署日报前端纯逻辑（Node）：三张图的布局（§6 G2–G5）与页面辅助函数。"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "plugins" / "sign_daily" / "static"


def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.match(r"v(\d+)", out.strip())
    return int(match.group(1)) if match else 0


pytestmark = pytest.mark.skipif(_node_major() < 22, reason="needs Node 22+ to import ES modules")


def _run(script: str) -> dict:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, STATIC.as_uri()],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_chart_layout_wraps_at_group_boundaries():
    out = _run(r"""
const C = await import(process.argv[1] + "/chart.js");
const group = (name, n, count = 1) => ({group: name, personTimes: n * count, flows: n, people: n,
  bars: Array.from({length: n}, (_, i) => ({name: `${name}${i}`, label: `${name}${i}`, count}))});
const rows = C.packRows([group("A", 20), group("B", 15), group("C", 45), group("D", 3)]);
const layout = C.layoutChart([group("A", 2, 7), group("B", 1, 3)]);
console.log(JSON.stringify({
  rows: rows.map((row) => row.map((seg) => [seg.group.group, seg.bars.length, seg.continued])),
  ticks: C.yTicks(7), ticks1: C.yTicks(1), ticks23: C.yTicks(23),
  width: layout.width, oneRow: layout.rows.length, height: layout.height,
  taller: C.layoutChart([group("A", 40)]).height > layout.height,
  bars: layout.rows[0].segments.map((s) => s.bars.map((b) => b.x + b.width <= layout.width)),
  stats: C.groupStatsText({personTimes: 23, flows: 15, people: 5}),
  palettes: [C.PALETTES.external.bar !== C.PALETTES.sections.bar, C.PALETTES.sections.special !== C.PALETTES.sections.bar],
  constants: [C.DISPLAY_WIDTH, C.PIXEL_RATIO, C.MAX_BARS_PER_ROW],
}));
""")
    # 每行最多 30 根；超出在分组边界换行；单组 45 人在组内续行
    assert out["rows"] == [
        [["A", 20, False]],
        [["B", 15, False]],
        [["C", 30, False]],
        [["C", 15, True], ["D", 3, False]],
    ]
    assert out["ticks"][0] == 0 and out["ticks"][-1] >= 7 and all(isinstance(t, int) for t in out["ticks"])
    assert out["ticks1"] == [0, 1] and out["ticks23"][-1] >= 23
    assert out["width"] == 720 and out["oneRow"] == 1 and out["taller"] is True
    assert all(all(row) for row in out["bars"])
    assert out["stats"] == "23 人次 / 15 份 / 5 人"
    assert out["palettes"] == [True, True]  # 图1 强调色；图2 特殊组浅色
    assert out["constants"] == [720, 2, 30]


def test_page_logic():
    out = _run(r"""
const L = await import(process.argv[1] + "/report-logic.js");
const longCycle = {
  review: [{project: "F610M", normalized: "前门内板", checked: true}, {project: "F610M", normalized: "前门内板加强板", checked: false}],
  misses: [{project: "F610M", normalized: "前门铰链", flows: 2}, {project: "F610M", normalized: "尾灯支座", flows: 1}],
};
const picks = L.initialPicks(longCycle);
console.log(JSON.stringify({
  key: L.scopeKey(["F610S", "F610M"], [], false),
  keyWatch: L.scopeKey(["F610M"], ["车身科"], true),
  inline: L.inlineImages('<img src="cid:sd-external"><img src="cid:sd-approval">', {external: "data:x"}),
  allowed: [L.exportAllowed({exportBlocked: true}, false), L.exportAllowed({exportBlocked: true}, true), L.exportAllowed({exportBlocked: false})],
  payload: L.conclusionsPayload(longCycle, picks, {"F610M\u0000前门铰链": true}),
  search: L.searchMisses(longCycle.misses, "铰链").map((i) => i.normalized),
  pairs: L.parsePairs("潘炳洁=整车性能\n坏行\n高颖阁 ＝ 车身制造"),
  synonyms: L.parseSynonyms("尾门=背门、后背门\n饰板=护板"),
  formatted: L.formatSynonyms({"尾门": ["背门", "后背门"]}),
  gbk: L.decodeCsv(new Uint8Array([0xd0, 0xd5, 0xc3, 0xfb])),
  utf8: L.decodeCsv(new TextEncoder().encode("﻿姓名")),
  stage: L.stageText({stage: "正在抓取", percent: 5}),
  gate: [L.exportAllowed({exportBlocked: false, statusGate: {blocked: true}}, true),
         L.exportAllowed({exportBlocked: false, statusGate: {blocked: false}})],
  gateText: [L.statusGateText({statusGate: {blocked: true, text: "X"}}),
             L.statusGateText({statusGate: {blocked: false, text: "X"}}), L.statusGateText(null),
             L.statusGateText({statusGate: {blocked: false, codes: [{code: "6", flows: 2}]}})],
  orphans: L.orphanProjects(["F620S", "F620S产品项目"], ["F610S", "F620S", "F620S产品项目", "F610S"]),
  migrate: [L.migratePrefs({a: {to: "x"}, b: {to: "y"}}, "a", "b"),
            L.migratePrefs({a: {to: "x"}}, "a", "c"), L.migratePrefs({a: {to: "x"}}, "a", "a")],
}));
""")
    # 与 backend.scope_key（Python json.dumps）逐字一致
    assert out["key"] == json.dumps({"projects": ["F610M", "F610S"], "departments": []}, ensure_ascii=False)
    assert out["keyWatch"] == json.dumps({"projects": ["F610M"], "departments": ["车身科"], "watchlistOnly": True},
                                         ensure_ascii=False)
    assert out["inline"] == '<img src="data:x"><img src="cid:sd-approval">'
    assert out["allowed"] == [False, True, True]
    assert out["payload"] == [{"project": "F610M", "items": [
        {"key": "前门内板", "include": True}, {"key": "前门内板加强板", "include": False}, {"key": "前门铰链", "include": True}]}]
    assert out["search"] == ["前门铰链"]
    assert out["pairs"] == {"潘炳洁": "整车性能", "高颖阁": "车身制造"}
    assert out["synonyms"] == {"尾门": ["背门", "后背门"], "饰板": ["护板"]}
    assert out["formatted"] == "尾门=背门、后背门"
    assert out["gbk"] == "姓名" and out["utf8"] == "姓名"
    assert out["stage"] == "正在抓取（5%）"
    # 状态门禁不提供「继续」选项；孤儿项目只披露、不自动删除；新范围有记忆时不覆盖
    assert out["gate"] == [False, True]
    assert out["gateText"] == ["X", "", "", "门禁已关闭，状态列仍是数字码（6：2 份）：数字仅供参考，发出去就是错数"]
    assert out["orphans"] == ["F610S"]
    assert out["migrate"] == [None, {"to": "x"}, None]


def test_chips_renders_orphans(tmp_path):
    """门禁：孤儿 chip 排在 options 之后、class 带 is-on 与 is-orphan、点一下取消；无 options 时仍渲染。"""
    root = STATIC.parents[2]
    (tmp_path / "preact-htm.js").write_text(
        (root / "web" / "static" / "host" / "vendor" / "preact-htm.js").read_text(encoding="utf-8"),
        encoding="utf-8")
    (tmp_path / "report-logic.js").write_text(
        (STATIC / "report-logic.js").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "chips.mjs").write_text(
        (STATIC / "chips.js").read_text(encoding="utf-8").replace(
            '"/static/host/vendor/preact-htm.js"', '"./preact-htm.js"'),
        encoding="utf-8")
    harness = """
import { Chips } from "./chips.mjs";
const flatten = (v) => v.props.children.filter(Boolean).flat(Infinity);
const rows = (v) => flatten(v).map((x) => ({
  cls: x.props.class, title: x.props.title || "",
  checked: x.props.children.find((c) => c && c.type === "input").props.checked,
  text: x.props.children.filter((c) => typeof c === "string").join(""),
}));
const input = (node) => node.props.children.find((c) => c && c.type === "input");
const calls = [];
const out = Chips({options: ["F620S", "F620S产品项目"], value: ["F620S", "F620S产品项目", "F610S"],
  onChange: (v) => calls.push(v), emptyText: "空", orphans: ["F610S"]});
input(flatten(out).find((x) => String(x.props.class).includes("is-orphan"))).props.onChange();
const dup = Chips({options: ["F620S"], value: ["F620S", "F610S", "F610S"], onChange: (v) => calls.push(v),
  emptyText: "空", orphans: ["F610S"]});
input(flatten(dup).find((x) => String(x.props.class).includes("is-orphan"))).props.onChange();
const only = Chips({options: [], value: ["F610S"], onChange: () => {}, emptyText: "空", orphans: ["F610S"]});
console.log(JSON.stringify({rows: rows(out), calls, only: rows(only), onlyTag: only.type}));
"""
    (tmp_path / "run.mjs").write_text(harness, encoding="utf-8")
    result = subprocess.run(["node", str(tmp_path / "run.mjs")], capture_output=True, text=True,
                            encoding="utf-8", check=False)
    assert result.returncode == 0, result.stderr[-2000:]
    data = json.loads(result.stdout.strip().splitlines()[-1])
    # 不变量 1：孤儿只出现一次、排在 options 之后、class 同时含 is-on 与 is-orphan，普通 chip 不受影响
    assert [r["cls"] for r in data["rows"]] == ["sd-chip is-on", "sd-chip is-on", "sd-chip is-on is-orphan"]
    assert data["rows"][2]["title"] and "取消" in data["rows"][2]["title"]
    # 不变量 2：options 为空、只有孤儿时仍渲染 chip（不是 emptyText 的 span）
    assert data["onlyTag"] == "div" and [r["cls"] for r in data["only"]] == ["sd-chip is-on is-orphan"]
    # 不变量 3：点掉孤儿后该项完全移除（含重复），其余选择与顺序不变
    assert data["calls"][0] == ["F620S", "F620S产品项目"]
    assert data["calls"][1] == ["F620S"]


def test_chart_palette_helpers():
    """配色：坏值回落默认、未知图沿用图2 默认；方案与太浅提示；不传 palette 时出图行为不变。"""
    out = _run(r"""
const C = await import(process.argv[1] + "/chart.js");
const calls = [];
const fakeDoc = {createElement: () => ({width: 0, height: 0, toDataURL: () => "data:image/png;base64,x",
  getContext: () => new Proxy({}, {get: (t, k) => k === "fillStyle" ? t.fill : (k in t ? t[k] : () => {}),
    set: (t, k, v) => { if (k === "fillStyle") calls.push(v); t[k === "fillStyle" ? "fill" : k] = v; return true; }})})};
const groups = [{group: "A", personTimes: 1, flows: 1, people: 1, bars: [{name: "x", label: "x", count: 1}]},
                {group: "B", special: true, personTimes: 1, flows: 1, people: 1, bars: [{name: "y", label: "y", count: 1}]}];
C.renderChartPng(groups, "sections", fakeDoc);
const plain = calls.splice(0);
C.renderChartPng(groups, "sections", fakeDoc, {bar: "#112233", special: "#445566"});
const custom = calls.splice(0);
console.log(JSON.stringify({
  ok: C.resolvePalette("external", {external: {bar: "#ABCDEF"}}),
  bad: C.resolvePalette("sections", {sections: {bar: "red", special: 3}}),
  none: C.resolvePalette("approval", null),
  unknown: C.resolvePalette("pie", {pie: {bar: "#000000"}}),
  all: C.resolveAllPalettes({sections: {special: "#000000"}}),
  defaults: C.PALETTES,
  presets: C.CHART_PRESETS.map((p) => p.id),
  presetDefault: C.presetPalettes("default"), presetUnknown: C.presetPalettes("nope"),
  match: [C.matchPreset(C.PALETTES), C.matchPreset(C.presetPalettes("warm")), C.matchPreset({external: {bar: "#010203"}})],
  light: [C.tooLight("#ffffff"), C.tooLight("#f5f5f5"), C.tooLight("#3370ff"), C.tooLight("#c9cdd4"), C.tooLight("bad")],
  defaultsLight: Object.values(C.PALETTES).some((p) => C.tooLight(p.bar) || C.tooLight(p.special)),
  plainHasDefault: plain.includes("#8f959e") && plain.includes("#c9cdd4"),
  custom: custom.includes("#112233") && custom.includes("#445566") && !custom.includes("#8f959e"),
}));
""")
    assert out["ok"] == {"bar": "#abcdef", "special": "#3370ff"}
    assert out["bad"] == out["defaults"]["sections"]
    assert out["none"] == out["defaults"]["approval"]
    assert out["unknown"] == out["defaults"]["sections"]
    assert out["all"]["sections"] == {"bar": "#8f959e", "special": "#000000"}
    assert out["all"]["external"] == out["defaults"]["external"]
    assert out["presets"] == ["default", "bluegray", "warm", "contrast"]
    assert out["presetDefault"] == out["defaults"] and out["presetUnknown"] == out["defaults"]
    assert out["match"] == ["default", "warm", ""]
    assert out["light"] == [True, True, False, False, False]
    assert out["defaultsLight"] is False
    assert out["plainHasDefault"] is True and out["custom"] is True


def test_compare_plan_and_result_text():
    out = _run(r"""
const L = await import(process.argv[1] + "/report-logic.js");
const items = [
  {date: "2026-11-15", sourceName: "a.xlsx", pinned: false},
  {date: "2026-11-01", sourceName: "b.xlsx", pinned: false},
];
const pinned = [items[0], {...items[1], pinned: true}];
console.log(JSON.stringify({
  today: L.todayIso(new Date(2026, 0, 5)),
  options: L.baselineOptions(pinned).map((o) => [o.value, o.label]),
  first: L.comparePlan([], {dataDate: "2026-11-16"}),
  auto: L.comparePlan(items, {dataDate: "2026-11-16"}),
  gap: L.comparePlan(items, {dataDate: "2026-12-20", maxGapDays: 14}),
  stale: L.comparePlan(items, {dataDate: "2026-11-10"}),
  noEarlier: L.comparePlan([{date: "2026-11-16", sourceName: "c"}], {dataDate: "2026-11-16"}),
  explicit: L.comparePlan(items, {dataDate: "2026-11-16", choice: "2026-11-01"}),
  explicitBad: L.comparePlan(items, {dataDate: "2026-11-15", choice: "2026-11-15"}),
  pinnedPlan: L.comparePlan(pinned, {dataDate: "2026-11-16"}),
  explicitOverPinned: L.comparePlan(pinned, {dataDate: "2026-11-16", choice: "2026-11-15"}),
  noDate: L.comparePlan(items, {dataDate: ""}),
  result: [
    L.compareResultText({baseline: {date: "2026-11-15", sourceName: "a.xlsx", mode: "auto"}, baselineSaved: true}),
    L.compareResultText({baseline: {date: "2026-11-01", sourceName: "b.xlsx", mode: "pinned"}, baselineSaved: false}),
    L.compareResultText({baseline: null, baselineReason: "x", baselineSaved: false}),
    L.compareResultText({baseline: null, baselineStatement: "已有更晚日期的手工导入…", baselineSaved: false}),
    L.compareResultText({baseline: null, baselineSaved: true}),
  ],
  same: [L.sameColors({external: {bar: "#AAAAAA"}}, {external: {bar: "#aaaaaa"}}),
         L.sameColors({external: {bar: "#aaaaaa"}}, {external: {bar: "#bbbbbb"}})],
}));
""")
    assert out["today"] == "2026-01-05"
    assert out["options"] == [["", "上次导入（自动）"], ["2026-11-15", "2026-11-15 · a.xlsx"],
                              ["2026-11-01", "2026-11-01 · b.xlsx（固定）"]]
    assert out["first"] == {"text": "这是第一次导入，明天起才能看到每日进展", "tone": "info"}
    assert out["auto"] == {"text": "将与 11-15 的导入（a.xlsx）对比", "tone": "ok"}
    assert out["gap"]["tone"] == "info" and "隔了超过 14 天" in out["gap"]["text"]
    assert out["stale"]["tone"] == "warn" and "按旧数据处理" in out["stale"]["text"]
    assert out["noEarlier"]["text"] == "今天先导入一次，明天再导入就能看到进展"
    assert out["explicit"] == {"text": "将与 11-01 的导入（b.xlsx）对比（你指定的）", "tone": "ok"}
    assert out["explicitBad"] == {"text": "选的对比日期要早于本次数据日期，请改选或改回自动", "tone": "warn"}
    assert out["pinnedPlan"] == {"text": "已固定与 11-01 的导入（b.xlsx）对比", "tone": "ok"}
    assert out["explicitOverPinned"]["text"].startswith("将与 11-15")
    assert out["noDate"]["tone"] == "info"
    assert out["result"][0] == "已与 11-15 的导入（a.xlsx，自动选的上次导入）对比。本次已留作下次对比。"
    assert "已固定的" in out["result"][1] and "没有留作" in out["result"][1]
    assert out["result"][2].startswith("选的对比日期要早于本次数据日期")
    assert out["result"][3].startswith("已有更晚日期的导入")
    assert out["result"][4].startswith("没有可比的更早导入")
    assert out["same"] == [True, False]


def test_report_page_passes_palette_to_every_chart_render():
    source = (STATIC / "report.js").read_text(encoding="utf-8")
    calls = re.findall(r"renderChartPng\(([^)]*)\)", source)
    assert calls and all(call.count(",") >= 3 for call in calls)  # 每处都传第 4 个参数（生效配色）
    assert "renderImages(data, effectiveColors)" in source
    assert "不计算日变化" not in source


def test_file_date_hint_only_warns_on_mismatch():
    out = _run(r"""
const L = await import(process.argv[1] + "/report-logic.js");
const at = (y, m, d) => new Date(y, m - 1, d, 10, 0, 0).getTime();
console.log(JSON.stringify({
  same: L.fileDateHint(at(2026, 11, 16), "2026-11-16"),
  differs: L.fileDateHint(at(2026, 11, 15), "2026-11-16"),
  noFile: L.fileDateHint(null, "2026-11-16"),
  noDate: L.fileDateHint(at(2026, 11, 15), ""),
  bad: L.fileDateHint("not a time", "2026-11-16"),
}));
""")
    assert out["same"] == "" and out["noFile"] == "" and out["noDate"] == "" and out["bad"] == ""
    assert out["differs"] == "这份文件最后修改于 2026-11-15，和填写的数据截至日期 2026-11-16 不是同一天，请确认日期没填错"
