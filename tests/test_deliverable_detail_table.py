# -*- coding: utf-8 -*-
"""交付物详情简表交互门禁（Node 下执行真实 simple-logic.js）。

锁定的契约：
1. 列身份统一：列 key 缺失时，排序、显隐、复制、表头一律回退 c.index；
2. 排序稳定：相等元素保持原序，空值在升序/降序下均置底，且不修改原数组；
3. 复制单号：单号列 key 缺失仍能定位到可见列并提取可复制的单号文本；
4. 列显隐至少保留一列：隐藏最后一列被拒绝，未知列不会被误加。

测试直接 import 插件里的 simple-logic.js，不检查源码文本包含关系。
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
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, f"Node 执行失败:\n{result.stderr[-2000:]}"
    lines = result.stdout.strip().splitlines()
    assert lines, "Node 执行未产生输出"
    return json.loads(lines[-1])


_SCRIPT_TABLE = r"""
const base = process.argv[1];
const L = await import(base + "/deliverable/simple-logic.js");
const out = {};

// 列定义故意不带 key：列身份必须回退 index。
const columns = [
  { label: "流水单号", index: 0 },
  { label: "零件名称", index: 1 },
  { label: "数量", index: 2 }
];
const schema = { columns, keyColumns: [0] };

out.keys = columns.map((c) => L.columnKeyOf(c));
out.keyedKeys = [L.columnKeyOf({ key: "c1", index: 1 }), L.columnKeyOf({ key: "", index: 2 }), L.columnKeyOf(null)];
out.headers = L.tableHeaders(columns, { key: "0", direction: "asc" });
out.headersReset = L.tableHeaders(columns, null);
out.keyedHeaders = L.tableHeaders([{ key: "c1", label: "零件名称", index: 1 }], { key: "c1", direction: "desc" });

// 排序：数量列 key 缺失，排序键为 index 字符串；相等值保持原序，空值置底。
const rows = [
  { rowKey: "r5", values: ["SOR-005", "空值", null] },
  { rowKey: "r1", values: ["SOR-001", "前保险杠", 5] },
  { rowKey: "r2", values: ["SOR-002", "后保险杠", 5] },
  { rowKey: "r3", values: ["SOR-003", "侧围", 3] },
  { rowKey: "r4", values: ["SOR-004", "车门", 5] },
  { rowKey: "r6", values: ["SOR-006", "空值", ""] }
];
const getValue = (row, key) => L.getRowCellValue(row, key, { schema, columns });
out.sortAsc = L.sortRows(rows, { key: "2", direction: "asc" }, getValue).map((r) => r.rowKey);
out.sortDesc = L.sortRows(rows, { key: "2", direction: "desc" }, getValue).map((r) => r.rowKey);
out.sortReset = L.sortRows(rows, { key: "2", direction: null }, getValue).map((r) => r.rowKey);
out.originalOrder = rows.map((r) => r.rowKey);

// index 0 的列 key 缺失：排序键 "0" 不能被当成空键跳过。
const serialRows = [
  { rowKey: "a", values: ["SOR-010"] },
  { rowKey: "b", values: ["SOR-002"] }
];
const serialGet = (row, key) => L.getRowCellValue(row, key, { schema: { columns }, columns });
out.stateZero = L.nextSortState(null, "0");
out.sortByIndexZero = L.sortRows(serialRows, { key: "0", direction: "asc" }, serialGet).map((r) => r.rowKey);

// 显隐：偏好里只有 index 字符串；全不选/全隐藏时保底一列。
const candidates = L.candidateColumns(schema, rows);
const defaults = L.simpleColumns(schema, rows);
out.candidateKeys = candidates.map((c) => L.columnKeyOf(c));
out.defaultKeys = defaults.map((c) => L.columnKeyOf(c));
out.visByIndex = L.calculateVisibleColumns(candidates, { visibleKeys: ["2"] }, defaults).map((c) => L.columnKeyOf(c));
out.visEmpty = L.calculateVisibleColumns(candidates, { visibleKeys: [] }, defaults).map((c) => L.columnKeyOf(c));
out.visHiddenAll = L.calculateVisibleColumns(candidates, { hiddenKeys: ["0", "1", "2"] }, defaults).map((c) => L.columnKeyOf(c));

// 切换：隐藏最后一列被拒绝；未知列不会被误加。
out.toggleLast = L.toggleColumnVisibility([columns[0]], "0", false, columns);
out.toggleKeep = L.toggleColumnVisibility([columns[0], columns[1]], "0", false, columns);
out.toggleAdd = L.toggleColumnVisibility([columns[0]], "2", true, columns);
out.toggleUnknown = L.toggleColumnVisibility([columns[0]], "9", true, columns);

// 复制：单号列 key 缺失仍能定位；单号列被隐藏时退回第一可见列。
const serialCol = L.findSerialNumberColumn(schema);
out.serialColKey = L.columnKeyOf(serialCol);
out.serialCopyVisible = L.serialCopyColumnKey(schema, columns);
out.serialCopyHidden = L.serialCopyColumnKey(schema, [columns[1], columns[2]]);
out.serialNumber = L.extractSerialNumber({ values: ["F999X-SOR-001", "前保险杠", 5] }, schema);
out.serialFallback = L.extractSerialNumber({ values: [null], serialNumber: " FALLBACK-002 " }, schema);
out.serialEmpty = L.extractSerialNumber({ values: [null] }, schema);

console.log(JSON.stringify(out));
"""


def test_column_key_falls_back_to_index_across_surfaces() -> None:
    """列 key 缺失时，表头、排序、显隐、复制全部回退 c.index。"""
    data = _run(_SCRIPT_TABLE)

    # 表头身份回退 index，且彼此唯一。
    assert data["keys"] == ["0", "1", "2"]
    # 已有 key 的列仍以 key 为准；空 key 回退 index；空列返回空串。
    assert data["keyedKeys"] == ["c1", "2", ""]
    headers = data["headers"]
    assert [h["key"] for h in headers] == ["0", "1", "2"]
    assert headers[0]["label"] == "流水单号"
    assert headers[0]["sortKey"] == "0"
    assert headers[0]["ariaSort"] == "ascending"
    assert headers[0]["arrow"] == " ▲"
    assert headers[1]["ariaSort"] == "none"
    assert headers[1]["arrow"] == ""
    assert data["keyedHeaders"][0]["key"] == "c1"
    assert data["keyedHeaders"][0]["ariaSort"] == "descending"
    assert data["keyedHeaders"][0]["arrow"] == " ▼"

    # 排序状态与排序键同样使用 index 回退；"0" 不是空键。
    assert data["stateZero"] == {"key": "0", "direction": "asc"}
    assert data["sortByIndexZero"] == ["b", "a"]

    # 显隐偏好只给 index 字符串也能命中。
    assert data["candidateKeys"] == ["0", "1", "2"]
    assert data["defaultKeys"]
    assert data["visByIndex"] == ["2"]

    # 复制定位：单号列 key 缺失回退 index；被隐藏时退回第一可见列。
    assert data["serialColKey"] == "0"
    assert data["serialCopyVisible"] == "0"
    assert data["serialCopyHidden"] == "1"


def test_sort_rows_is_stable_and_keeps_empty_last() -> None:
    """相等元素保持原序；空值升序/降序均置底；重置与排序都不改原数组。"""
    data = _run(_SCRIPT_TABLE)

    assert data["sortAsc"] == ["r3", "r1", "r2", "r4", "r5", "r6"]
    assert data["sortDesc"] == ["r1", "r2", "r4", "r3", "r5", "r6"]
    assert data["sortReset"] == ["r5", "r1", "r2", "r3", "r4", "r6"]
    assert data["originalOrder"] == ["r5", "r1", "r2", "r3", "r4", "r6"]


def test_copy_serial_number_content() -> None:
    """单号列 key 缺失时仍提取可复制的单号文本，并保留行级回退。"""
    data = _run(_SCRIPT_TABLE)

    assert data["serialNumber"] == "F999X-SOR-001"
    assert data["serialFallback"] == "FALLBACK-002"
    assert data["serialEmpty"] == ""


def test_visibility_keeps_at_least_one_column() -> None:
    """列显隐至少保留一列：全不选/全隐藏有保底，隐藏最后一列被拒绝。"""
    data = _run(_SCRIPT_TABLE)

    assert len(data["visEmpty"]) == 1
    assert len(data["visHiddenAll"]) == 1
    assert data["toggleLast"] is None
    assert data["toggleKeep"] == ["1"]
    assert data["toggleAdd"] == ["0", "2"]
    assert data["toggleUnknown"] is None
