# -*- coding: utf-8 -*-
"""简洁视图纯逻辑契约（Node 下执行 simple-logic.js）。

锁四件事：
1. 阶段列读后端 schema.stageLabels，缺失回退原码/源表状态；
2. 逾期独立成列，已完成行不判逾期，未知不猜测；
3. 派生进度按 effectiveProgress 显示，null 显示「—」（不编造 0%）；
4. 同步结果文案区分「更新 N 项 / 上游无变化 / 失败」——接口对 failed 也返回 HTTP 200。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

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


_SCRIPT = r"""
const base = process.argv[1];
const L = await import(base + "/deliverable/simple-logic.js");
const schema = {stageLabels: {PROC: "审批中"}};
const out = {};
out.stageKnown = L.stageLabel(schema, {dimensions: {stage: "PROC", status: "PROC"}});
out.stageUnknown = L.stageLabel(schema, {dimensions: {stage: "WEIRD"}});
out.stageFallback = L.stageLabel({}, {dimensions: {status: "PROC"}});
out.overdueYes = L.overdueLabel({overdueState: "overdue"});
out.overdueNo = L.overdueLabel({overdueState: "on_time"});
out.overdueUnknown = L.overdueLabel({overdueState: "unknown"});
out.overdueDone = L.overdueLabel({overdueState: "overdue", isCompleted: true});
out.progressSnapshot = L.progressDisplay({effectiveProgress: 71, progress: 0, progressSource: "snapshot"});
out.progressNull = L.progressDisplay({effectiveProgress: null, progress: 0, progressSource: "snapshot"});
out.progressManual = L.progressDisplay({progress: 45, progressSource: "manual"});
out.progressClamp = L.progressDisplay({effectiveProgress: 130});
out.syncApplied = L.syncResultText({result: {finalState: "success", outcome: "completed", appliedFields: ["note"]}});
out.syncSkipped = L.syncResultText({result: {finalState: "success", outcome: "completed", appliedFields: []}});
out.syncFailed = L.syncResultText({result: {finalState: "failed", outcome: "failed", errorType: "timeout"}});
console.log(JSON.stringify(out));
"""


def test_simple_view_stage_overdue_progress_and_sync_text() -> None:
    data = _run(_SCRIPT)

    # 1. 阶段：后端标签优先，未登记回退原码，空阶段回退源表状态。
    assert data["stageKnown"] == "审批中"
    assert data["stageUnknown"] == "WEIRD"
    assert data["stageFallback"] == "PROC"

    # 2. 逾期独立成列。
    assert data["overdueYes"] == "是"
    assert data["overdueNo"] == "否"
    assert data["overdueUnknown"] == "—"
    assert data["overdueDone"] == "—"

    # 3. 派生进度：快照态取 effectiveProgress，null 显示「—」。
    assert data["progressSnapshot"] == {"value": 71, "text": "71%", "derived": True}
    assert data["progressNull"] == {"value": None, "text": "—", "derived": False}
    assert data["progressManual"] == {"value": 45, "text": "45%", "derived": False}
    assert data["progressClamp"] == {"value": 100, "text": "100%", "derived": False}

    # 4. 同步文案：应用了字段才叫「更新」，幂等跳过叫「无变化」，失败显式报错。
    assert data["syncApplied"] == "同步完成，更新 1 项"
    assert data["syncSkipped"] == "已同步，上游无变化"
    assert data["syncFailed"].startswith("同步失败：")
