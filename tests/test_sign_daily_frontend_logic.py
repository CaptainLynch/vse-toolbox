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

