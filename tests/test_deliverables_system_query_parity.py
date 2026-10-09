# -*- coding: utf-8 -*-
"""system_query 与 deliverables 两个插件的流水单号前端行为一致性（防漂移）。

A′ 路线的「document_no 提升到请求体顶层」逻辑在两个插件里各有一份实现
（2026-10-07 交付物工作台漏接导致生产 0 行的根因即两份拷贝漂移）。本测试
用同一组输入分别驱动两份 buildPayload / serialMatch 文案实现，断言输出一致；
再断言目录下发的字段单源（web/app.py）与两个前端字段的键集一致。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import web.app as web_app

REPO_ROOT = Path(__file__).resolve().parent.parent
SQ_STATIC = REPO_ROOT / "plugins" / "system_query" / "static"
DLV_STATIC = REPO_ROOT / "plugins" / "deliverables" / "static"

# 输入样例与期望输出在 JS 侧生成、Python 侧断言，保证两侧真正跑的是各自实现。
_NODE_SCRIPT = r"""
const [sqUri, dlvUri] = process.argv.slice(1);
const sqLib = await import(sqUri + "/lib.js");
const dlvLib = await import(dlvUri + "/lib.js");

const sqMode = {
  base_url: "https://tdc.sgmw.com.cn",
  headers: "",
};
const sqValues = {serial_number: "900001", document_no: " 3D-00001018 3D-00001193 ", page: "1", page_size: "50"};
const sqModeDef = await import(sqUri + "/modes.js");

// system_query: buildPayload(modeId, values, connection)
const sqPayload = sqLib.buildPayload("tdc-data-model", sqValues, sqMode);

// deliverables: buildPayload(item, values, operation)；item.fields 由目录下发，
// 这里用与 web/app.py _TDC_DATA_MODEL_FIELDS 相同的键集（Python 侧单源断言兜底）。
const dmItem = {
  id: "tdc-data-model",
  fields: sqModeDef.TDC_MODES["tdc-data-model"].filterNames.map((name) => ({name, label: name, type: "text"})),
};
const dlvPayload = dlvLib.buildPayload(dmItem, sqValues, "query");

const samples = [
  {serialMatch: {requested: "x", scanned: 12, matched: 0, scannedPages: 3, complete: false, reason: "crawl_incomplete"}},
  {serialMatch: {requested: "x", scanned: 12, matched: 0, scannedPages: 3, complete: true}},
  {serialMatch: {requested: ["a", "b"], found: ["a"], missing: ["b"], scanned: 12, matched: 1, scannedPages: 3, complete: true}},
  {serialMatch: {requested: ["a", "b"], found: ["a", "b"], missing: [], scanned: 12, matched: 2, scannedPages: 3, complete: true}},
  {rows: []},
];
const sqNotices = samples.map((d) => sqLib.serialMatchNotice(d));
const dlvWarnings = samples.map((d) => dlvLib.serialMatchWarning(d));

console.log(JSON.stringify({
  sqPayload,
  dlvPayload,
  sqNotices,
  dlvWarnings,
  dlvSummary: dlvLib.formatFilterSummary(dmItem, dlvPayload.filters, dlvPayload.document_no),
}));
"""


def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    out = subprocess.run(["node", "--version"], capture_output=True, text=True, check=False).stdout
    match = re.match(r"v(\d+)", out.strip())
    return int(match.group(1)) if match else 0


@pytest.fixture(scope="module")
def parity() -> dict:  # type: ignore[type-arg]
    if _node_major() < 22:
        pytest.skip("needs Node 22+ to import ES modules without a package.json")
    result = subprocess.run(
        ["node", "--input-type=module", "-e", _NODE_SCRIPT, SQ_STATIC.as_uri(), DLV_STATIC.as_uri()],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_document_no_promotion_is_identical(parity: dict) -> None:
    """两份 buildPayload 都把 document_no 提到顶层、其余进 filters，trim 行为一致。"""
    sq, dlv = parity["sqPayload"], parity["dlvPayload"]
    assert sq["document_no"] == dlv["document_no"] == "3D-00001018 3D-00001193"
    assert "document_no" not in sq["filters"] and "document_no" not in dlv["filters"]
    assert sq["filters"]["serial_number"] == dlv["filters"]["serial_number"] == "900001"


def test_serial_match_messages_are_equivalent(parity: dict) -> None:
    """未完成 / 单号未找到 / 多号含 missing / 全命中 / 无簿记，五态语义一致。

    文案允许措辞差异（单号 vs 列表），但「抓取不完整」必须同句、missing 必须
    出现在未命中文案里、命中与无簿记必须同时为空提示。
    """
    sq, dlv = parity["sqNotices"], parity["dlvWarnings"]
    assert "抓取不完整" in sq[0] and "抓取不完整" in dlv[0]
    assert "未找到" in sq[1] and "未找到" in dlv[1]
    assert "未找到" in dlv[2] and "b" in dlv[2]  # missing 单号必须列出
    assert sq[3] is None and dlv[3] == ""  # 全命中无提示
    assert sq[4] is None and dlv[4] == ""  # 无 serialMatch 无提示


def test_filter_summary_includes_document_no(parity: dict) -> None:
    # parity 夹具的 dmItem label=name，所以摘要里是字段名；真实目录 label 由
    # test_catalog_field_set_matches_system_query_mode_fields 的单源断言兜底。
    summary = parity["dlvSummary"]
    assert "document_no" in summary
    assert "3D-00001018" in summary


def test_catalog_field_set_matches_system_query_mode_fields() -> None:
    """字段单源：目录下发（web/app.py）与 system_query modes 的数模键集一致。"""
    catalog_names = [f["name"] for f in web_app._TDC_DATA_MODEL_FIELDS]
    modes_source = (SQ_STATIC / "modes.js").read_text(encoding="utf-8")
    # modes.js 的 tdc-data-model fields 块里每个字段一行 text(...)/date(...)，
    # 第一个参数即字段名；与目录键集逐一对应（顺序一致，含 document_no）。
    block = modes_source.split('"tdc-data-model"', 1)[1].split("],", 1)[0]
    mode_names = re.findall(r'(?:text|date)\("([a-z_]+)"', block)
    assert mode_names == catalog_names
    # document_no 不是服务端 filter（顶层读取），其余都是。
    assert web_app._TDC_DATA_MODEL_FILTER_NAMES == tuple(n for n in catalog_names if n != "document_no")
