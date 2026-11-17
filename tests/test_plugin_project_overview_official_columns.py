# -*- coding: utf-8 -*-
"""project-overview 前端：官方工作簿列「本次未取得」的展示契约。

后端把官方工作簿 47 列按 (流水单号, 零件号) 合并进表单快照，并在快照 schema 里写
``officialColumns = {status, rowStatus, missingIndexes}``；``/view`` 载荷透出该键，
行里带 ``officialJoin``（joined / ambiguous / unmatched / unavailable，旧快照为 ``''``）。

这里只钉前端的读法，全部用仓库既有 node / node-VM 夹具写法：

* 纯函数（``form-state.js``）：``formOfficialColumns`` / ``formOfficialMissingRow`` 的闭集，
  以及 ``''`` = 未知、绝不当成未取得的语义；
* 渲染（``form-analysis.js`` 的真实 ``FormRowsTable``，在 Node VM 里跑真源码，
  preact 只提供模板 + hooks 桩）：未合并行显示新文案、已合并行不显示、旧快照逐字不变、
  ``status != ok`` 在表格上方给出状态说明。

运行期不写任何文件、不联网，只读仓库内的静态文件。
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
DELIVERABLE = STATIC / "deliverable"

MISSING_TEXT = "本次未取得官方列"
NOTE_UNAVAILABLE = "本次未取得官方工作簿"
NOTE_TRUNCATED = "官方工作簿行数超出上限，本次未补齐官方列"
NOTE_MISMATCH = "官方工作簿表头与契约不一致，本次未采用官方列"
NOTE_EXPORT_FAILED = "官方报表导出失败，本次未取得官方列"

MIN_NODE_MAJOR = 22


def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.match(r"v(\d+)", out.strip())
    return int(match.group(1)) if match else 0


needs_node = pytest.mark.skipif(
    _node_major() < MIN_NODE_MAJOR,
    reason="needs Node 22+ (ES modules / vm.SourceTextModule)",
)


def _run_node(script: str, *args: str) -> dict:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def _run_node_vm(script: str, *args: str) -> dict:
    result = subprocess.run(
        ["node", "--experimental-vm-modules", "--input-type=module", "-e", script, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------------------
# 纯函数：form-state.js
# ---------------------------------------------------------------------------

_PURE_SCRIPT = r"""
const base = process.argv[1];
const S = await import(base + "/deliverable/form-state.js");
const ok = S.formOfficialColumns({
  officialColumns: {status: "ok", missingIndexes: [5, 6], rowStatus: {joined: 3, ambiguous: 1, unmatched: 2, unavailable: 0}},
});
const dirty = S.formOfficialColumns({
  officialColumns: {status: "truncated", missingIndexes: [3, "7", null, true, "x"]},
});
const notRequested = S.formOfficialColumns({officialColumns: {status: "not_requested"}});
console.log(JSON.stringify({
  text: S.FORM_OFFICIAL_MISSING_TEXT,
  statuses: [...S.FORM_OFFICIAL_COLUMN_STATUSES],
  joins: [...S.FORM_OFFICIAL_JOIN_STATUSES],
  parsedStatus: ok.status,
  parsedMissing: [...ok.missingIndexes].sort((a, b) => a - b),
  parsedMissingIsSet: ok.missingIndexes instanceof Set,
  parsedRowStatus: ok.rowStatus,
  dirtyMissing: [...dirty.missingIndexes].sort((a, b) => a - b),
  rowStatusDefaults: S.formOfficialColumns({officialColumns: {status: "ok"}}).rowStatus,
  legacyNoKey: S.formOfficialColumns({formKey: "tdc_data_model"}),
  legacyNullData: S.formOfficialColumns(null),
  legacyArrayPayload: S.formOfficialColumns({officialColumns: []}),
  legacyStringPayload: S.formOfficialColumns({officialColumns: "ok"}),
  badStatus: S.formOfficialColumns({officialColumns: {status: "bogus"}}),
  emptyStatus: S.formOfficialColumns({officialColumns: {}}),
  notRequested: notRequested.status,
  rows: {
    joined: S.formOfficialMissingRow({officialJoin: "joined"}, ok),
    ambiguous: S.formOfficialMissingRow({officialJoin: "ambiguous"}, ok),
    unmatched: S.formOfficialMissingRow({officialJoin: "unmatched"}, ok),
    unavailable: S.formOfficialMissingRow({officialJoin: "unavailable"}, ok),
    unknownEmpty: S.formOfficialMissingRow({officialJoin: ""}, ok),
    unknownMissing: S.formOfficialMissingRow({}, ok),
    unknownNullItem: S.formOfficialMissingRow(null, ok),
    bogus: S.formOfficialMissingRow({officialJoin: "bogus"}, ok),
    noOfficialArg: S.formOfficialMissingRow({officialJoin: "unmatched"}),
    legacyOfficialNull: S.formOfficialMissingRow({officialJoin: "unmatched"}, null),
    notRequestedOfficial: S.formOfficialMissingRow({officialJoin: "unmatched"}, notRequested),
    notRequestedUnavailable: S.formOfficialMissingRow({officialJoin: "unavailable"}, notRequested),
  },
  notes: {
    ok: S.formOfficialStatusNote(ok),
    legacy: S.formOfficialStatusNote(null),
    notRequested: S.formOfficialStatusNote({status: "not_requested"}),
    unavailable: S.formOfficialStatusNote({status: "unavailable"}),
    truncated: S.formOfficialStatusNote({status: "truncated"}),
    mismatch: S.formOfficialStatusNote({status: "contract_mismatch"}),
    exportFailed: S.formOfficialStatusNote({status: "export_failed"}),
  },
}));
"""


@needs_node
def test_form_official_columns_closed_set_and_legacy_null() -> None:
    """officialColumns 的解析闭集；键缺失/非法一律 null（旧快照行为不变）。"""
    data = _run_node(_PURE_SCRIPT, STATIC.as_uri())
    assert data["text"] == MISSING_TEXT
    assert data["statuses"] == ["ok", "unavailable", "truncated", "contract_mismatch", "export_failed", "not_requested"]
    assert data["joins"] == ["joined", "ambiguous", "unmatched", "unavailable"]
    assert data["parsedStatus"] == "ok"
    assert data["parsedMissing"] == [5, 6]
    assert data["parsedMissingIsSet"] is True
    assert data["parsedRowStatus"] == {"joined": 3, "ambiguous": 1, "unmatched": 2, "unavailable": 0}
    # 非法索引被剔除；数字字符串按数字收下，布尔/空值/非数字丢弃。
    assert data["dirtyMissing"] == [3, 7]
    assert data["rowStatusDefaults"] == {"joined": 0, "ambiguous": 0, "unmatched": 0, "unavailable": 0}
    assert data["legacyNoKey"] is None
    assert data["legacyNullData"] is None
    assert data["legacyArrayPayload"] is None
    assert data["legacyStringPayload"] is None
    assert data["badStatus"] is None
    assert data["emptyStatus"] is None
    assert data["notRequested"] == "not_requested"


@needs_node
def test_form_official_missing_row_treats_empty_string_as_unknown() -> None:
    """逐行状态闭集；'' / 缺失 / joined → 未取得为假（'' 是「未知」，不是未取得）。"""
    rows = _run_node(_PURE_SCRIPT, STATIC.as_uri())["rows"]
    assert rows == {
        "joined": False,
        "ambiguous": True,
        "unmatched": True,
        "unavailable": True,
        "unknownEmpty": False,
        "unknownMissing": False,
        "unknownNullItem": False,
        "bogus": False,
        # 纵深防御：没有 officialColumns / status == not_requested → 一律 false。
        "noOfficialArg": False,
        "legacyOfficialNull": False,
        "notRequestedOfficial": False,
        "notRequestedUnavailable": False,
    }


@needs_node
def test_form_official_status_notes_cover_non_ok_statuses() -> None:
    """status 文案闭集：ok / not_requested / 旧快照不提示，其余四种各一句。"""
    notes = _run_node(_PURE_SCRIPT, STATIC.as_uri())["notes"]
    assert notes == {
        "ok": "",
        "legacy": "",
        "notRequested": "",
        "unavailable": NOTE_UNAVAILABLE,
        "truncated": NOTE_TRUNCATED,
        "mismatch": NOTE_MISMATCH,
        "exportFailed": NOTE_EXPORT_FAILED,
    }


# ---------------------------------------------------------------------------
# 渲染：真实 form-analysis.js 的 FormRowsTable（Node VM）
# ---------------------------------------------------------------------------

_RENDER_SCRIPT = r"""
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import * as vm from "node:vm";

const [, STATIC_DIR, SCENARIO_JSON] = process.argv;
const scenario = JSON.parse(SCENARIO_JSON);

const context = vm.createContext({
  console: { log() {}, warn() {}, error() {}, info() {}, debug() {} },
  setTimeout, clearTimeout, queueMicrotask,
  Promise, JSON, Math, Date, Object, Array, String, Number, Boolean, Error, TypeError, RangeError,
  Map, Set, WeakMap, WeakSet, Symbol, Reflect, RegExp, parseInt, parseFloat, isNaN,
  encodeURIComponent, decodeURIComponent,
});

// 模板与 hooks 的最小桩：FormRowsTable 本身不用 hooks，模板只保留 strings/values。
function html(strings, ...values) { return { __template: true, strings: Array.from(strings), values }; }
const noop = () => {};
const preactStub = {
  html,
  useState: (init) => [typeof init === "function" ? init() : init, noop],
  useRef: (init) => ({ current: init }),
  useEffect: noop,
  useLayoutEffect: noop,
};

function synthetic(identifier, exportsMap) {
  const names = Object.keys(exportsMap);
  return new vm.SyntheticModule(names, function () {
    for (const key of names) this.setExport(key, exportsMap[key]);
  }, { context, identifier });
}

function realSource(relative) {
  const file = STATIC_DIR + "/deliverable/" + relative;
  return new vm.SourceTextModule(readFileSync(file, "utf8"), {
    context, identifier: pathToFileURL(file).href,
  });
}

const stubs = new Map([
  ["/static/host/vendor/preact-htm.js", preactStub],
  // 只有表格渲染路径被测；这些模块在真实页面里由别的组件使用。
  ["./multi-select.js", { SearchMultiSelect: function SearchMultiSelect() { return html`<div></div>`; } }],
  ["./watchlist.js", {
    TermsInput: function TermsInput() { return html`<div></div>`; },
    TermsSummary: function TermsSummary() { return html`<div></div>`; },
    WatchlistPanel: function WatchlistPanel() { return html`<div></div>`; },
    loadWatchlist: async () => ({}),
  }],
  ["./watchlist-logic.js", { DATA_MODEL_FORM_KEY: "tdc_data_model", termsChipText: () => "" }],
  // D5 关联架构件面板：本用例只测表格渲染，面板本身由 arch_links 用例覆盖。
  ["./arch-links.js", { ArchLinksPanel: function ArchLinksPanel() { return html`<div></div>`; } }],
  // v2 专家模式：这些用例断言来源工作表/行号列，按专家模式渲染。
  ["/static/host/expert.js", { expertStore: { get: () => true, subscribe: () => () => {} } }],
]);

// 真源码：form-state.js（被钉住的纯函数）、format.js（safeDisplayValue）、chart-math.js、api.js。
const REAL = { "./form-state.js": "form-state.js", "./format.js": "format.js",
               "./chart-math.js": "chart-math.js", "./api.js": "api.js" };

const entry = STATIC_DIR + "/deliverable/form-analysis.js";
const module = new vm.SourceTextModule(readFileSync(entry, "utf8"), {
  context, identifier: pathToFileURL(entry).href,
});

await module.link((specifier) => {
  if (REAL[specifier]) return realSource(REAL[specifier]);
  const exportsMap = stubs.get(specifier);
  if (!exportsMap) throw new Error("unknown specifier " + specifier);
  return synthetic(specifier, exportsMap);
});
await module.evaluate();

const FormRowsTable = module.namespace.FormRowsTable;
if (typeof FormRowsTable !== "function") {
  console.log(JSON.stringify({ ok: false, error: "FormRowsTable export missing" }));
  process.exit(0);
}

// 标量内联、函数（事件处理器）跳过，得到与浏览器 DOM 文本等价的伪 HTML。
function flatten(node, out) {
  if (node === null || node === undefined || node === false || node === true) return;
  if (typeof node === "function") return;
  if (Array.isArray(node)) { node.forEach((child) => flatten(child, out)); return; }
  if (node && node.__template === true) {
    for (let index = 0; index < node.strings.length; index += 1) {
      out.push(node.strings[index]);
      if (index < node.values.length) flatten(node.values[index], out);
    }
    return;
  }
  out.push(String(node));
}

const out = [];
flatten(FormRowsTable({
  data: scenario.data,
  rowsData: scenario.rowsData,
  state: { activeTab: "departmentStatus", pageByTab: {} },
  onReload: () => {},
}), out);
const text = out.join("");

const cells = [];
const CELL = /<(td|dd)([^>]*)>([^<]*)<\/\1>/g;
let match;
while ((match = CELL.exec(text)) !== null) cells.push({ tag: match[1], attrs: match[2], text: match[3] });

console.log(JSON.stringify({
  ok: true,
  text,
  rows: text.split("<tr"),
  cells,
}));
"""


def _columns() -> list[dict]:
    return [
        {"index": 0, "label": "流水单号"},
        {"index": 1, "label": "零件号"},
        {"index": 5, "label": "官方·审批状态"},
    ]


def _data(official: dict | None = None) -> dict:
    data = {
        "formKey": "tdc_data_model",
        "schema": {"columns": _columns(), "keyColumns": [0, 1, 5], "defaultVisibleCount": 3},
        "sourceAbsentIndexes": [],
    }
    if official is not None:
        data["officialColumns"] = official
    return data


def _rows(items: list[dict]) -> dict:
    return {"items": items, "total": len(items), "offset": 0, "limit": 50}


UNJOINED = {"sheetName": "清单", "rowNumber": 2, "values": ["DM-1", "P-1", None], "officialJoin": "unmatched"}
JOINED = {"sheetName": "清单", "rowNumber": 3, "values": ["DM-2", "P-2", None], "officialJoin": "joined"}
LEGACY = {"sheetName": "清单", "rowNumber": 2, "values": ["DM-1", "P-1", None], "officialJoin": ""}


def _render(data: dict, items: list[dict]) -> dict:
    payload = json.dumps({"data": data, "rowsData": _rows(items)})
    result = _run_node_vm(_RENDER_SCRIPT, STATIC.as_posix(), payload)
    assert result.get("ok") is True, result
    return result


@needs_node
def test_rows_table_marks_unjoined_row_and_leaves_joined_row_alone() -> None:
    """未合并行显示「本次未取得官方列」；已合并行的真实空值仍是 `-`。"""
    rendered = _render(
        _data({"status": "ok", "missingIndexes": [5], "rowStatus": {"joined": 1, "ambiguous": 0, "unmatched": 1, "unavailable": 0}}),
        [UNJOINED, JOINED],
    )
    text = rendered["text"]
    # 未合并行：正文单元格 + 「查看全部字段」的 <dd> 各一处。
    marked = [cell for cell in rendered["cells"] if "form-cell-official-missing" in cell["attrs"]]
    assert len(marked) == 2, marked
    assert {cell["text"] for cell in marked} == {MISSING_TEXT}
    assert all("本次未取得官方工作簿，无法展示该官方列" in cell["attrs"] for cell in marked)
    # 表格按行切开：第一条（未合并）行含新文案，第二条（已合并）行不含。
    rows = rendered["rows"]
    assert MISSING_TEXT in rows[2], rows[2]
    assert MISSING_TEXT in rows[3], rows[3]  # 该行的「查看全部字段」明细
    assert MISSING_TEXT not in rows[4], rows[4]
    assert MISSING_TEXT not in rows[5], rows[5]
    # 已合并行的官方列真实空值仍是 `-`，不得被标成未取得。
    assert re.search(r"<td[^>]*>-[^<]*</td>", rows[4]), rows[4]
    # status=ok 时表格上方没有状态说明（注意单元格 title 里含同样的前缀，故按段落元素断言）。
    assert "form-row-official-note" not in text


@needs_node
def test_rows_table_legacy_snapshot_is_unchanged() -> None:
    """旧快照（无 officialColumns）：既不加新文案，也不加顶部说明。"""
    rendered = _render(_data(), [LEGACY])
    text = rendered["text"]
    assert MISSING_TEXT not in text
    assert "form-cell-official-missing" not in text
    assert "form-row-official-note" not in text
    # 与升级前一致：官方列位置仍是真实空值 `-`。
    assert re.search(r"<td[^>]*>-[^<]*</td>", text)


@needs_node
def test_rows_table_ignores_row_marker_without_official_columns() -> None:
    """只有 officialColumns 存在时才判定行标记：键缺失时 officialJoin 不生效。"""
    rendered = _render(_data(), [UNJOINED])
    assert MISSING_TEXT not in rendered["text"]


@pytest.mark.parametrize(
    "status,note",
    [
        ("unavailable", NOTE_UNAVAILABLE),
        ("truncated", NOTE_TRUNCATED),
        ("contract_mismatch", NOTE_MISMATCH),
        ("export_failed", NOTE_EXPORT_FAILED),
        ("not_requested", ""),
        ("ok", ""),
    ],
)
@needs_node
def test_rows_table_shows_status_note_above_the_table(status: str, note: str) -> None:
    """status != ok 时在表格上方给一条说明；ok / not_requested 不提示。"""
    rendered = _render(
        _data({"status": status, "missingIndexes": [5], "rowStatus": {"joined": 0, "ambiguous": 0, "unmatched": 1, "unavailable": 0}}),
        [UNJOINED],
    )
    text = rendered["text"]
    if note:
        # 说明必须是表格上方的独立段落（单元格 title 里含同样的前缀，不能只按子串断言）。
        assert f'<p class="form-row-official-note">{note}</p>' in text
        assert text.index(note) < text.index("form-row-table-wrap")
    else:
        assert "form-row-official-note" not in text
    if status == "not_requested":
        # 本次根本没申请官方列 → 行级标记也不生效（纵深防御），不得遮住真实值。
        assert MISSING_TEXT not in text
    else:
        # 行级标记与快照级状态互不影响：未合并行仍逐格明示。
        assert MISSING_TEXT in text


@needs_node
def test_rows_table_archive_shape_snapshot_shows_real_official_values() -> None:
    """归档形状快照（无 officialColumns、行无标记）：官方列真实值必须可见。

    归档连接器的行本来就是官方 47 列；只要快照不带 officialColumns（服务端
    ``not_requested`` 不写该键），渲染就与升级前逐字一致——不得出现
    「本次未取得官方列」。
    """
    rendered = _render(
        _data(),
        [
            {
                "sheetName": "清单",
                "rowNumber": 2,
                "values": ["DM-1", "P-1", None, None, None, "审批中"],
                "officialJoin": "",
            }
        ],
    )
    text = rendered["text"]
    assert MISSING_TEXT not in text
    assert "form-cell-official-missing" not in text
    assert "form-row-official-note" not in text
    # 官方列位置的真实值照常渲染（正文 <td> + 「查看全部字段」的 <dd>）。
    shown = [cell for cell in rendered["cells"] if cell["text"] == "审批中"]
    assert shown, rendered["cells"]
