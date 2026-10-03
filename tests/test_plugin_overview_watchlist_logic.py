# -*- coding: utf-8 -*-
"""交付物明细页 §9 前端纯逻辑（Node）：多值搜索、关注清单与「同步设置」列。"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from services.form_search import PLACEHOLDER, parse_terms

STATIC = Path(__file__).resolve().parent.parent / "plugins" / "project_overview" / "static"


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


SAMPLE = "F610M-3D-0001 F610M-3D-0002，前门内板；张三、Z9\nA1\tA2,，a1　全角"


def test_terms_parsing_matches_backend_and_placeholder():
    out = _run(r"""
const base = process.argv[1];
const W = await import(base + "/deliverable/watchlist-logic.js");
console.log(JSON.stringify({
  terms: W.parseTerms(process.env.SAMPLE),
  placeholder: W.TERMS_PLACEHOLDER,
  summary: W.termSummaryText({forms: 2, unmatched: ["x"]}),
  allMatched: W.termSummaryText({forms: 3, unmatched: []}),
  chip: W.termsChipText("a b c"),
  suffix: W.watchlistProgressSuffix({scope: "watchlist", count: 12}),
  noSuffix: W.watchlistProgressSuffix({scope: "all", count: 3}),
  states: [W.itemStateText({found: true}), W.itemStateText({found: false}), W.itemStateText({found: null})],
}));
""".replace("process.env.SAMPLE", json.dumps(SAMPLE)))
    assert out["terms"] == parse_terms(SAMPLE)  # 前后端同一口径
    assert out["placeholder"] == PLACEHOLDER
    assert out["summary"] == "匹配 2 份表单；1 个词没有匹配"
    assert out["allMatched"] == "匹配 3 份表单"
    assert out["chip"] == "3 个词"
    assert (out["suffix"], out["noSuffix"]) == ("（关注 12 份）", "")
    assert out["states"] == ["", "未找到", "未同步"]


def test_sync_settings_logic():
    out = _run(r"""
const base = process.argv[1];
const L = await import(base + "/details/sync-settings-logic.js");
const binding = {kind: "binding", deliverableId: "VPI-T2-D5", displayName: "数模", enabled: true, intervalMinutes: 60,
  mode: "automatic", filters: {reportType: "data_model", aggregate: true, department: "技术中心_车体工程"},
  watchlist: {scope: "watchlist", count: 12}, syncState: "success", lastAttemptAt: "2026-10-03T08:15:00.123Z",
  missing: []};
const archive = {kind: "archive", deliverableId: "VPI-T2-D6", jobKey: "aras_paa", enabled: false, intervalMinutes: 60,
  filters: {}, outputSubdir: "", updatedAt: "u1", missing: ["统一域账号凭据"]};
console.log(JSON.stringify({
  summary: L.filterSummary(binding),
  all: L.filterSummary(archive),
  interval: [L.intervalText(binding), L.intervalText({intervalMinutes: 90}), L.intervalText({intervalMinutes: 2880}),
             L.intervalText({kind: "binding", intervalMinutes: null})],
  last: L.lastSyncText(binding),
  never: L.lastSyncText(archive),
  missing: L.missingText(archive),
  bindingReq: L.settingRequest(binding, {enabled: false, filters: {reportType: "data_model"}, outputSubdir: "x"}),
  archiveReq: L.settingRequest(archive, {enabled: true}),
  badInterval: [L.parseInterval("0", "binding").error, L.parseInterval("3", "archive").error, L.parseInterval("15", "archive").value],
  badFilters: [L.parseFilters("[1]").error, L.parseFilters("{").error, L.parseFilters("").value],
  errors: L.fieldErrorsText({fields: {enabled: "缺凭据", matchRule: "缺条件"}}),
  candidates: L.syncAllCandidates([binding, archive, {...binding, deliverableId: "X", enabled: false}]),
  warn: [L.schedulerWarning({running: true, paused: false, eligibleCount: 0}), L.schedulerWarning({running: true, eligibleCount: 2}),
         L.schedulerWarning({running: true, paused: true, eligibleCount: 0})],
}));
""")
    assert out["summary"] == "关注 12 份；部门：技术中心_车体工程"
    assert out["all"] == "全部"
    assert out["interval"] == ["每 1 小时", "每 90 分钟", "每 2 天", "跟随调度频率"]
    assert out["last"] == "10-03 08:15 成功" and out["never"] == "从未同步"
    assert out["missing"] == "待配置：缺统一域账号凭据"
    assert out["bindingReq"] == {
        "path": "/api/project-status/deliverables/VPI-T2-D5/update-policy", "method": "PATCH",
        "body": {"enabled": False, "matchRule": {"reportType": "data_model"}},
    }
    assert out["archiveReq"]["path"] == "/api/scheduled-archive/jobs/aras_paa"
    assert out["archiveReq"]["body"] == {"enabled": True, "intervalMinutes": 60, "filters": {}, "outputSubdir": "",
                                         "updatedAt": "u1"}
    assert out["badInterval"] == ["间隔必须是正整数分钟", "归档任务间隔必须在 5–10080 分钟之间", 15]
    assert out["badFilters"][:2] == ["筛选条件必须是 JSON 对象", "筛选条件不是有效的 JSON"] and out["badFilters"][2] == {}
    assert out["errors"] == "缺凭据；缺条件"
    assert out["candidates"] == [{"deliverableId": "VPI-T2-D5", "name": "数模", "filters": "关注 12 份；部门：技术中心_车体工程"}]
    assert out["warn"] == ["没有启用任何交付物，自动同步不会抓取数据", "", ""]
