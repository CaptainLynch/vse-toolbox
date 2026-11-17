# -*- coding: utf-8 -*-
"""关注清单入口与表单/导出入口收敛（DSH-V2-29）。

本文件用 Node 真实执行三份前端模块：

1. ``plugins/workbench/static/reports.js``：渲染报告页，断言关注清单入口读取
   ``/api/p/project-overview/watchlist``（与交付物详情 ``detail-watchlist.js``
   同一个常量），并原样展示 count / scope / missing / configIssue；
2. 同一模块的 ``EXPORT_TARGETS`` / ``exportTarget`` / ``ExportCard``：F5/F6/F7
   共用一张定位表，逐个点击按钮断言跳到既有实现，F7 保留人工核查门禁；
3. ``web/static/host/legacy-routes.js``：旧表单书签落到交付物详情，不返回 null。

另有一个 Flask 集成用例：用真实的 ``/api/p/project-overview/watchlist`` 载荷
驱动上面的 Node 组件，证明报告中心与交付物详情使用同一份数据。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import web.app as web_app
from services.deliverable_form_analysis import build_form_snapshot, form_definition

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_JS = REPO_ROOT / "plugins" / "workbench" / "static" / "reports.js"
DETAIL_WATCHLIST_JS = REPO_ROOT / "plugins" / "project_overview" / "static" / "deliverable" / "detail-watchlist.js"
WATCHLIST_JS = REPO_ROOT / "plugins" / "project_overview" / "static" / "deliverable" / "watchlist.js"
WATCHLIST_LOGIC_JS = REPO_ROOT / "plugins" / "project_overview" / "static" / "deliverable" / "watchlist-logic.js"
LEGACY_ROUTES_JS = REPO_ROOT / "web" / "static" / "host" / "legacy-routes.js"
WATCHLIST_API = "/api/p/project-overview/watchlist"


def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
        match = re.match(r"v(\d+)", out.strip())
        return int(match.group(1)) if match else 0
    except Exception:  # noqa: BLE001 - 探测失败按「Node 不可用」处理
        return 0


needs_node = pytest.mark.skipif(
    _node_major() < 20,
    reason="需要 Node 20+（--experimental-vm-modules 运行 ES Module 并渲染组件）",
)


_RUNNER_JS = r"""
import { readFileSync } from "node:fs";
import * as vm from "node:vm";

const [, REPORTS_PATH, DETAIL_PATH, PANEL_PATH, LOGIC_PATH, LEGACY_PATH, SCENARIO_JSON] = process.argv;
const scenario = JSON.parse(SCENARIO_JSON);
const navigations = [];
let capturedLoaders = null;

function htmlStub(strings, ...values) {
  return { __template: true, strings: Array.from(strings), values };
}

const context = vm.createContext({
  console: { log() {}, warn() {}, error() {} },
  Promise, JSON, Math, Date, Object, Array, String, Number, Boolean, RegExp, Error,
  Map, Set, encodeURIComponent, decodeURIComponent, URLSearchParams,
  window: { location: { hash: "" } },
});

const cache = new Map();

function synthetic(exportsMap) {
  return new vm.SyntheticModule(
    Object.keys(exportsMap),
    function () {
      for (const [key, value] of Object.entries(exportsMap)) this.setExport(key, value);
    },
    { context },
  );
}

const preact = {
  html: htmlStub,
  useEffect: () => {},
  useRef: (value) => ({ current: value }),
  useState: (value) => [typeof value === "function" ? value() : value, () => {}],
};

async function linker(specifier) {
  if (specifier.includes("preact-htm")) return synthetic(preact);
  if (specifier === "/static/host/report-controller.js") {
    return synthetic({
      blockReason: () => "",
      copyPayload: () => ({ html: "", text: "" }),
      copyToClipboard: async () => "",
      downloadEml: async () => "",
      exportAllowed: () => true,
      isStatusGateError: () => false,
      missingChartKeys: () => [],
      previewHtml: () => "",
      runSignDaily: async () => null,
    });
  }
  if (specifier === "./common.js") {
    return synthetic({
      html: htmlStub,
      api: async () => ({}),
      useLoad: (loaders) => {
        capturedLoaders = loaders;
        return {
          data: scenario.stateData || {},
          errors: scenario.stateErrors || {},
          loading: false,
          reload: () => {},
        };
      },
      useWorkbenchStyles: () => {},
      Pill: (props) => htmlStub`<span class="wb-pill">${props.children}</span>`,
      PageHead: (props) => htmlStub`<header>${props.title}${props.sub || ""}</header>`,
      Progress: () => htmlStub`<div class="wb-progress"></div>`,
      go: (hash) => { navigations.push(hash); },
      todayString: () => "2026-10-31",
    });
  }
  if (specifier === "./api.js") {
    return synthetic({
      apiRequest: async () => ({}),
      enc: (value) => encodeURIComponent(String(value)),
      plainErrorMessage: (error, fallback) => (error && error.message) || fallback,
    });
  }
  if (specifier === "./format.js") {
    return synthetic({
      formatArtifactSize: () => "",
      safeDisplayValue: (value) => (value === null || value === undefined ? "" : String(value)),
    });
  }
  if (specifier === "./watchlist-logic.js") return loadFile(LOGIC_PATH);
  throw new Error("unexpected specifier: " + specifier);
}

async function loadFile(filePath) {
  if (cache.has(filePath)) return cache.get(filePath);
  const mod = new vm.SourceTextModule(readFileSync(filePath, "utf8"), {
    context,
    identifier: filePath,
  });
  cache.set(filePath, mod);
  await mod.link(linker);
  await mod.evaluate();
  return mod;
}

function textOf(node) {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (node && node.__template) {
    let out = "";
    for (let i = 0; i < node.strings.length; i++) {
      out += node.strings[i];
      if (i < node.values.length) out += textOf(node.values[i]);
    }
    return out;
  }
  return "";
}

function walk(node, visit) {
  if (node === null || node === undefined || typeof node === "boolean") return;
  if (Array.isArray(node)) { node.forEach((child) => walk(child, visit)); return; }
  if (typeof node !== "object") return;
  if (node.__template) {
    visit(node);
    node.values.forEach((child) => walk(child, visit));
  }
}

function propsOf(node) {
  const props = {};
  for (let i = 0; i < node.values.length; i++) {
    const match = /([A-Za-z_][\w-]*)=\s*"?$/.exec(node.strings[i] || "");
    if (match) props[match[1]] = node.values[i];
  }
  return props;
}

function collect(root, predicate) {
  const found = [];
  walk(root, (node) => {
    const props = propsOf(node);
    if (predicate(props, node)) found.push({ props, node });
  });
  return found;
}

// htm 把没有插值的静态标签留在 strings 里，所以不能只看 strings[0]。
// 这里按「插值前最后一个未闭合标签」判断属性属于哪个元素。
function collectAttr(root, tag, attr) {
  const found = [];
  walk(root, (node) => {
    for (let i = 0; i < node.values.length; i++) {
      const before = node.strings[i] || "";
      const open = before.slice(before.lastIndexOf("<") + 1).trim().toLowerCase();
      if (!(open === tag || open.startsWith(tag + " "))) continue;
      const match = /([A-Za-z_][\w-]*)=\s*"?$/.exec(before);
      if (!match || match[1] !== attr) continue;
      found.push({ value: node.values[i], node, index: i });
    }
  });
  return found;
}

const reports = (await loadFile(REPORTS_PATH)).namespace;
const detail = (await loadFile(DETAIL_PATH)).namespace;
const panel = (await loadFile(PANEL_PATH)).namespace;
const legacy = (await loadFile(LEGACY_PATH)).namespace;

const out = {
  watchlistPath: reports.WATCHLIST_PATH,
  detailWatchlistPath: detail.WATCHLIST_PATH,
  watchlistCsvPath: reports.WATCHLIST_CSV_PATH,
  detailCsvPath: detail.WATCHLIST_CSV_PATH,
  watchlistDetail: reports.WATCHLIST_DETAIL,
};

const payload = scenario.payload;
out.summary = reports.watchlistSummary(payload);
const detailPanel = panel.WatchlistPanel({ watchlist: payload });
out.detailText = textOf(detailPanel);
out.detailLinks = collectAttr(detailPanel, "a", "href").map((item) => item.value);

const card = reports.WatchlistCard({ watchlist: payload, error: null });
out.cardText = textOf(card);
const entry = collect(card, (props) => Array.isArray(props.actions))[0] || null;
out.cardActions = entry
  ? entry.props.actions.map((action) => ({ label: action.label, href: action.href }))
  : [];
out.cardLinks = collectAttr(card, "a", "href").map((item) => item.value);

const failed = reports.WatchlistCard({
  watchlist: null,
  error: { message: "未找到数模设计审核流程的同步任务" },
});
out.errorText = textOf(failed);

out.targets = ["F5", "F6", "F7", "F8", "f5"].map((id) => {
  const target = reports.exportTarget(id);
  return target ? { id: target.id, href: target.href, manualCheck: target.manualCheck || "" } : null;
});

const exportCard = reports.ExportCard({});
out.exportText = textOf(exportCard);
const buttons = collectAttr(exportCard, "button", "onClick");
out.exportButtons = buttons.map((item) => ({ text: textOf(item.node), onClick: item.value }));
for (const item of buttons) item.value();
out.navigations = navigations.slice();

const page = reports.default({});
out.pageText = textOf(page);
out.loaders = capturedLoaders;
const pageWatch = collect(page, (props) => props.watchlist && typeof props.watchlist === "object" && "count" in props.watchlist)[0];
out.pageWatchlistCount = pageWatch ? pageWatch.props.watchlist.count : null;
out.pageHasLegacyFormsLink = out.pageText.includes("#p/deliverable-forms");

const hashes = [
  "#forms",
  "#deliverable-forms",
  "#deliverable-forms/index",
  "#deliverable-forms/ewo",
  "#deliverable-forms/paa",
  "#deliverable-forms/ncr_progress",
  "#deliverable-forms/ncr-detail",
  "#deliverable-forms/tdc_data_model",
  "#deliverable-forms/tdc-sor",
  "#form-panel?mode=ewo&from=overview",
  "#form/tdc-sor",
  "#deliverables",
  "#nope",
  "#p/deliverable-forms/ewo",
];
out.legacy = Object.fromEntries(hashes.map((hash) => [hash, legacy.legacyRedirect(hash)]));

console.log(JSON.stringify(out));
"""


def _run_node(payload: object, state_data: dict | None = None, state_errors: dict | None = None) -> dict:
    node = shutil.which("node")
    assert node is not None, "未找到 Node.js 命令"
    scenario = {
        "payload": payload,
        "stateData": state_data or {},
        "stateErrors": state_errors or {},
    }
    result = subprocess.run(
        [
            node,
            "--experimental-vm-modules",
            "--input-type=module",
            "-e",
            _RUNNER_JS,
            str(REPORTS_JS),
            str(DETAIL_WATCHLIST_JS),
            str(WATCHLIST_JS),
            str(WATCHLIST_LOGIC_JS),
            str(LEGACY_ROUTES_JS),
            json.dumps(scenario, ensure_ascii=False, separators=(",", ":")),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, f"Node 执行失败 (code {result.returncode}):\n{result.stderr}\n{result.stdout}"
    lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip().startswith("{")]
    assert lines, f"未获取到 Node 输出的 JSON 行:\n{result.stdout}"
    return json.loads(lines[-1])


_HEADERS = form_definition("tdc_data_model")["headerRows"][0]


@pytest.fixture()
def watchlist_payload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict:
    """真实走一遍 /api/p/project-overview/watchlist，拿交付物详情同源载荷。"""
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "single-entry.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=["project-overview"])
    app.config.update(TESTING=True)
    db = db_cls(tmp_path / "single-entry.db")
    rows = [
        {"流水单号": "F610M-3D-0001", "零件名称": "前门内板", "零件号": "P-1", "申请人": "张三", "状态": "进行中"},
        {"流水单号": "F610M-3D-0002", "零件名称": "尾灯", "零件号": "P-3", "申请人": "李四", "状态": "已完成"},
    ]
    positional = [{"values": [row.get(header) for header in _HEADERS], "sheetName": "Sheet1"} for row in rows]
    db.publish_deliverable_form_snapshot(
        build_form_snapshot(
            "tdc_data_model",
            positional,
            snapshot_at="2026-10-03T08:00:00Z",
            source_run_id=1,
            source="test",
        )
    )
    http = app.test_client()
    added = http.post(
        "/api/p/project-overview/watchlist",
        json={"action": "add", "serials": ["F610M-3D-0001", "F610M-3D-0099"]},
    )
    assert added.status_code == 200, added.get_data(as_text=True)
    response = http.get("/api/p/project-overview/watchlist")
    body = response.get_json()
    assert body["ok"] is True, body
    return body["data"]


@needs_node
def test_report_center_watchlist_uses_same_api_and_fields_as_detail(watchlist_payload: dict) -> None:
    data = _run_node(watchlist_payload, state_data={"watchlist": watchlist_payload})

    # 同一个接口常量：报告页与交付物详情都读 /api/p/project-overview/watchlist。
    assert data["watchlistPath"] == WATCHLIST_API
    assert data["detailWatchlistPath"] == WATCHLIST_API
    assert data["watchlistCsvPath"] == data["detailCsvPath"] == "/api/p/project-overview/watchlist.csv"
    assert data["watchlistDetail"] == "#p/project-overview/deliverable?id=VPI-T2-D5"

    # 字段原样来自详情接口，报告页不另算。
    assert data["summary"]["count"] == 2
    assert data["summary"]["scope"] == "全部表单"
    assert data["summary"]["missing"] == 1
    assert data["summary"]["configIssue"] == ""
    assert "关注清单 2 份" in data["detailText"], data["detailText"]
    assert "1 份未找到" in data["detailText"], data["detailText"]
    assert "同步范围：全部表单" in data["cardText"], data["cardText"]
    assert "同步范围：全部表单" in data["detailText"], data["detailText"]
    assert [item["serial"] for item in data["summary"]["items"]] == ["F610M-3D-0001", "F610M-3D-0099"]

    assert "关注清单" in data["cardText"], data["cardText"]
    assert "共 2 份" in data["cardText"], data["cardText"]
    assert "1 份未找到" in data["cardText"], data["cardText"]
    assert {"label": "在交付物详情维护", "href": data["watchlistDetail"]} in data["cardActions"]
    assert data["watchlistCsvPath"] in data["cardLinks"]
    assert data["watchlistCsvPath"] in data["detailLinks"]

    # 报告页的数据加载器确实带上了这个同源接口。
    assert data["loaders"]["watchlist"] == WATCHLIST_API
    assert data["pageWatchlistCount"] == 2
    assert data["pageHasLegacyFormsLink"] is False


@needs_node
def test_export_targets_share_one_resolver_and_keep_manual_check(watchlist_payload: dict) -> None:
    data = _run_node(watchlist_payload)

    f5, f6, f7, unknown, lower = data["targets"]
    assert f5["id"] == "F5" and f5["href"] == "#p/system-query/query?mode=ewo"
    assert f6["id"] == "F6" and "mode=tdc-data-model" in f6["href"]
    assert f7["id"] == "F7" and "id=VPI-T2-D3" in f7["href"]
    assert "不自动重发" in f7["manualCheck"]
    assert unknown is None
    assert lower["id"] == "F5"

    assert "F5" in data["exportText"] and "F6" in data["exportText"] and "F7" in data["exportText"]
    assert "不自动重发" in data["exportText"]
    assert len(data["exportButtons"]) == 3
    for label in ("打开 F5 导出", "打开 F6 导出", "打开 F7 导出"):
        assert label in data["exportText"], data["exportText"]
    # 真的点击三个按钮：都走同一张定位表，不各写一份跳转。
    assert data["navigations"] == [f5["href"], f6["href"], f7["href"]]


@needs_node
def test_legacy_form_bookmarks_redirect_to_deliverable_detail(watchlist_payload: dict) -> None:
    data = _run_node(watchlist_payload)
    legacy = data["legacy"]

    assert legacy["#forms"] == "#p/project-overview/details"
    assert legacy["#deliverable-forms"] == "#p/project-overview/details"
    assert legacy["#deliverable-forms/index"] == "#p/project-overview/details"
    assert legacy["#deliverable-forms/ewo"] == "#p/project-overview/deliverable?id=VPI-T2-D3"
    assert legacy["#deliverable-forms/paa"] == "#p/project-overview/deliverable?id=VPI-T2-D6"
    assert legacy["#deliverable-forms/ncr_progress"] == "#p/project-overview/deliverable?id=VPI-T2-D7"
    assert legacy["#deliverable-forms/ncr-detail"] == "#p/project-overview/deliverable?id=VPI-T2-D8"
    assert legacy["#deliverable-forms/tdc_data_model"] == "#p/project-overview/deliverable?id=VPI-T2-D5"
    assert legacy["#deliverable-forms/tdc-sor"] == "#p/project-overview/deliverable?id=VPI-T2-D2"
    assert legacy["#form-panel?mode=ewo&from=overview"] == (
        "#p/project-overview/deliverable?from=overview&id=VPI-T2-D3"
    )
    assert legacy["#form/tdc-sor"] == "#p/project-overview/deliverable?id=VPI-T2-D2"
    # 既有交付物书签保持原样；未知哈希仍交给外壳兜底。
    assert legacy["#deliverables"] == "#p/project-overview/details"
    assert legacy["#nope"] is None
    # #p/... 由 shell 直接路由，legacy-routes 不抢。
    assert legacy["#p/deliverable-forms/ewo"] is None


@needs_node
def test_watchlist_read_failure_does_not_render_fake_counts(watchlist_payload: dict) -> None:
    data = _run_node(None, state_data={}, state_errors={"watchlist": {"message": "未找到数模设计审核流程的同步任务"}})

    assert data["summary"] is None
    assert "关注清单读取失败" in data["errorText"]
    assert "未找到数模设计审核流程的同步任务" in data["errorText"]
    assert "共 0 份" not in data["errorText"]
