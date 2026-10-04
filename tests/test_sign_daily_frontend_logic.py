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
