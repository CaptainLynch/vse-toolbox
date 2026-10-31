# -*- coding: utf-8 -*-
"""简洁视图纯逻辑契约（Node 下执行 simple-logic.js）。

锁定的契约：
1. 阶段列读后端 schema.stageLabels，缺失回退原码/源表状态；
2. 逾期独立成列，已完成行不判逾期，未知不猜测；
3. 派生进度按 effectiveProgress 显示，null 显示「—」（不编造 0%）；
4. 同步结果文案区分「更新 N 项 / 上游无变化 / 失败」——接口对 failed 也返回 HTTP 200；
5. 自适应排序：数值与字符串自适应比较、空值置底、三态轮转（升/降/恢复）；
6. 单号提取与行内复制：识别业务单号列、提取单号；
7. 可见列与本地存储：候选列过滤、偏好计算、存储隔离与回退兜底；
8. 表单入口降级契约：manifest 中表单入口标注 expert: true，普通模式下收起。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC = REPO_ROOT / "plugins" / "project_overview" / "static"


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


_SCRIPT_CORE = r"""
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
    data = _run(_SCRIPT_CORE)

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


_SCRIPT_SORT = r"""
const base = process.argv[1];
const L = await import(base + "/deliverable/simple-logic.js");
const out = {};

// 数值解析
out.numParsed = [
  L.parseNumericLike(42),
  L.parseNumericLike("123.45"),
  L.parseNumericLike(" 1,234.50 "),
  L.parseNumericLike("ABC"),
  L.parseNumericLike(null),
  L.parseNumericLike(true)
];

// 自适应比对
out.cmpNum = L.compareAdaptive(2, 10);
out.cmpNumStr = L.compareAdaptive("2", "10");
out.cmpMixedSerial = L.compareAdaptive("PAA-2", "PAA-10");
out.cmpEmptyRight = L.compareAdaptive("A", null);
out.cmpEmptyLeft = L.compareAdaptive(null, "A");
out.cmpBothEmpty = L.compareAdaptive("", null);

// 状态三态轮转：null -> asc -> desc -> null；换列时从 asc 重新开始
const s0 = null;
const s1 = L.nextSortState(s0, "colA");
const s2 = L.nextSortState(s1, "colA");
const s3 = L.nextSortState(s2, "colA");
const s4 = L.nextSortState(s2, "colB");
out.sortStates = [s1, s2, s3, s4];

// 行排序：按数值、含空值置底、恢复默认
const rows = [
  { id: 1, values: [10, "车身科"] },
  { id: 2, values: [2, "内饰科"] },
  { id: 3, values: [null, "底盘科"] },
  { id: 4, values: [5, "外饰科"] }
];
const schema = { columns: [{ key: "val", index: 0 }, { key: "dept", index: 1 }] };

out.sortedAsc = L.sortRows(rows, { key: "val", direction: "asc" }, (r, k) => L.getRowCellValue(r, k, { schema, columns: schema.columns })).map((r) => r.id);
out.sortedDesc = L.sortRows(rows, { key: "val", direction: "desc" }, (r, k) => L.getRowCellValue(r, k, { schema, columns: schema.columns })).map((r) => r.id);
out.sortedReset = L.sortRows(rows, { key: "val", direction: null }, (r, k) => L.getRowCellValue(r, k, { schema, columns: schema.columns })).map((r) => r.id);

console.log(JSON.stringify(out));
"""


def test_simple_table_sort_logic() -> None:
    data = _run(_SCRIPT_SORT)

    # 1. 数值解析
    assert data["numParsed"] == [42, 123.45, 1234.5, None, None, None]

    # 2. 自适应比对：2 < 10、"2" < "10"、"PAA-2" < "PAA-10"、空值置底
    assert data["cmpNum"] < 0
    assert data["cmpNumStr"] < 0
    assert data["cmpMixedSerial"] < 0
    assert data["cmpEmptyRight"] < 0
    assert data["cmpEmptyLeft"] > 0
    assert data["cmpBothEmpty"] == 0

    # 3. 三态轮转
    assert data["sortStates"][0] == {"key": "colA", "direction": "asc"}
    assert data["sortStates"][1] == {"key": "colA", "direction": "desc"}
    assert data["sortStates"][2] == {"key": None, "direction": None}
    assert data["sortStates"][3] == {"key": "colB", "direction": "asc"}

    # 4. 数据行排序：升序 2, 5, 10, null；降序 10, 5, 2, null（空值均置底）；重置恢复原顺序
    assert data["sortedAsc"] == [2, 4, 1, 3]
    assert data["sortedDesc"] == [1, 4, 2, 3]
    assert data["sortedReset"] == [1, 2, 3, 4]


_SCRIPT_SERIAL_AND_COPY = r"""
const base = process.argv[1];
const L = await import(base + "/deliverable/simple-logic.js");
const out = {};

const schema1 = { columns: [{ label: "申请人", index: 0 }, { label: "流水单号", index: 1 }] };
const schema2 = { columns: [{ label: "零件名称", index: 0 }, { label: "EWO编号", index: 1 }] };
const schema3 = { columns: [{ label: "变更主题", index: 0 }, { label: "流程单号", index: 1 }] };
const schema4 = { columns: [{ label: "自定义", index: 0 }], keyColumns: [0] };

out.serialCol1 = L.findSerialNumberColumn(schema1).label;
out.serialCol2 = L.findSerialNumberColumn(schema2).label;
out.serialCol3 = L.findSerialNumberColumn(schema3).label;
out.serialCol4 = L.findSerialNumberColumn(schema4).label;

const row1 = { values: ["张三", "F999X-SOR-001"] };
const rowFallback = { values: ["李四", ""], serialNumber: "FALLBACK-002" };
const rowEmpty = { values: ["王五", null] };

out.extracted1 = L.extractSerialNumber(row1, schema1);
out.extractedFallback = L.extractSerialNumber(rowFallback, schema1);
out.extractedEmpty = L.extractSerialNumber(rowEmpty, schema1);

console.log(JSON.stringify(out));
"""


def test_simple_table_serial_and_copy_logic() -> None:
    data = _run(_SCRIPT_SERIAL_AND_COPY)

    # 1. 单号列识别契约
    assert data["serialCol1"] == "流水单号"
    assert data["serialCol2"] == "EWO编号"
    assert data["serialCol3"] == "流程单号"
    assert data["serialCol4"] == "自定义"

    # 2. 单号提取与降级
    assert data["extracted1"] == "F999X-SOR-001"
    assert data["extractedFallback"] == "FALLBACK-002"
    assert data["extractedEmpty"] == ""


_SCRIPT_COLUMNS_AND_PREFS = r"""
const base = process.argv[1];
const L = await import(base + "/deliverable/simple-logic.js");
const out = {};

const schema = {
  columns: [
    { key: "c0", label: "流水单号", index: 0 },
    { key: "c1", label: "零件名称", index: 1 },
    { key: "c2", label: "状态", index: 2 },
    { key: "c3", label: "空列", index: 3 },
    { key: "c4", label: "申请人", index: 4 },
    { key: "c5", label: "申请日期", index: 5 }
  ]
};
const rows = [
  { values: ["SOR-001", "前保险杠", "进行中", "", "张三", "2026-08-01"] },
  { values: ["SOR-002", "后保险杠", "已完成", null, "李四", "2026-08-02"] }
];

// 候选列过滤：排除状态列与全空列
const candidates = L.candidateColumns(schema, rows);
out.candidateLabels = candidates.map((c) => c.label);

// 默认列挑选
const defaults = L.simpleColumns(schema, rows);
out.defaultLabels = defaults.map((c) => c.label);

// 可见列计算：未配置时取默认；指定 visibleKeys；全不选时保底保留 1 列
out.visDefault = L.calculateVisibleColumns(candidates, null, defaults).map((c) => c.label);
out.visCustom = L.calculateVisibleColumns(candidates, { visibleKeys: ["c1", "c5"] }, defaults).map((c) => c.label);
out.visEmptyFallback = L.calculateVisibleColumns(candidates, { visibleKeys: [] }, defaults).map((c) => c.label);

// Mock Storage 测试保存与隔离
const mockStore = {};
const mockStorage = {
  getItem: (k) => (k in mockStore ? mockStore[k] : null),
  setItem: (k, v) => { mockStore[k] = String(v); }
};

L.saveColumnPreferences("form_sor", { visibleKeys: ["c1"] }, mockStorage);
out.prefLoadedSor = L.loadColumnPreferences("form_sor", mockStorage);
out.prefLoadedOther = L.loadColumnPreferences("form_other", mockStorage);

L.saveColumnPreferences("form_sor", null, mockStorage);
out.prefClearedSor = L.loadColumnPreferences("form_sor", mockStorage);

console.log(JSON.stringify(out));
"""


def test_simple_table_column_visibility_and_storage_logic() -> None:
    data = _run(_SCRIPT_COLUMNS_AND_PREFS)

    # 1. 候选列：排除「状态」与「空列」
    assert data["candidateLabels"] == ["流水单号", "零件名称", "申请人", "申请日期"]

    # 2. 默认列
    assert data["defaultLabels"] == ["流水单号", "零件名称", "申请人", "申请日期"]

    # 3. 可见列计算契约
    assert data["visDefault"] == ["流水单号", "零件名称", "申请人", "申请日期"]
    assert data["visCustom"] == ["零件名称", "申请日期"]
    # 用户全部取消勾选时，保底保留至少一列
    assert len(data["visEmptyFallback"]) >= 1

    # 4. 本地存储隔离与清空
    assert data["prefLoadedSor"] == {"visibleKeys": ["c1"]}
    assert data["prefLoadedOther"] is None
    assert data["prefClearedSor"] is None


def test_forms_manifest_expert_mode_contract() -> None:
    """旧「表单」独立入口降级契约：plugin.json 中 nav 标注 expert: true。"""
    forms_manifest = json.loads(
        (REPO_ROOT / "plugins" / "deliverable_forms" / "plugin.json").read_text(encoding="utf-8")
    )
    overview_manifest = json.loads(
        (REPO_ROOT / "plugins" / "project_overview" / "plugin.json").read_text(encoding="utf-8")
    )

    forms_nav = [entry for entry in forms_manifest.get("nav", []) if entry.get("title") == "表单"]
    assert len(forms_nav) == 1, "deliverable_forms 必须登记表单导航入口"
    assert forms_nav[0].get("expert") is True, "表单导航入口必须设置 expert: true 以在普通模式下收起"

    overview_nav = [entry for entry in overview_manifest.get("nav", []) if entry.get("title") == "概览"]
    assert len(overview_nav) == 1
    assert overview_nav[0].get("expert") is True
