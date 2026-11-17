# -*- coding: utf-8 -*-
"""报告中心原位一键生成（DSH-V2-22）。

本文件用 Node 真实执行宿主控制器 ``web/static/host/report-controller.js`` 与
报告页 ``plugins/workbench/static/reports.js``：

1. 控制器：接上真实的 ``web/static/host/api.js`` 客户端，用假 ``fetch`` 走
   ``POST /api/p/sign-daily/refresh`` → 轮询 ``GET .../refresh/<taskId>`` →
   ``POST .../generate`` → 预览 → 复制 → ``POST .../eml``；
2. 报告页：用最小 hook 运行时挂载真实的 ``DailyReportCard``，找到「一键生成日报」
   按钮并真的点击，断言进度、预览、复制、邮件草稿都发生在原位，且没有跳转；
3. 门禁与孤儿项目：``StatusGateBlocked`` 原样展示且不重试，历史残留项目不被丢弃。

所有数据都是合成值；不联网、不发邮件（.eml 只下载草稿）。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTROLLER_JS = REPO_ROOT / "web" / "static" / "host" / "report-controller.js"
REPORTS_JS = REPO_ROOT / "plugins" / "workbench" / "static" / "reports.js"
API_JS = REPO_ROOT / "web" / "static" / "host" / "api.js"


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
    reason="需要 Node 20+（--experimental-vm-modules 运行 ES Module 并挂载组件）",
)


_RUNNER_JS = r"""
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import * as vm from "node:vm";

const [, CONTROLLER_PATH, REPORTS_PATH, API_PATH, SCENARIO_JSON] = process.argv;
const scenario = JSON.parse(SCENARIO_JSON);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ---- 假 fetch：按预置队列返回 {ok,data}/{ok:false,error} 信封或原始 .eml 响应 ----
const calls = [];
const downloads = [];
const navigations = [];
const reloads = [];
const clipboardWrites = [];
const queue = (scenario.fetchQueue || []).slice();

function envelopeResponse(spec) {
  const status = spec.status || 200;
  const payload = spec.ok === false
    ? { ok: false, error: spec.error || { type: "http", message: "请求失败（HTTP " + status + "）" } }
    : { ok: true, data: spec.data === undefined ? null : spec.data };
  return {
    ok: payload.ok === true && status >= 200 && status < 300,
    status,
    headers: { get: (name) => (spec.headers || {})[name] || "" },
    json: async () => payload,
    blob: async () => ({ __blob: "json" }),
  };
}

function rawResponse(spec) {
  return {
    ok: (spec.status || 200) < 400,
    status: spec.status || 200,
    headers: { get: (name) => (spec.headers || {})[name] || "" },
    json: async () => { throw new Error("不是 JSON 响应"); },
    blob: async () => ({ __blob: "eml" }),
  };
}

async function fakeFetch(url, init) {
  const options = init || {};
  let body = options.body === undefined ? null : options.body;
  if (typeof body === "string") {
    try { body = JSON.parse(body); } catch (_) { /* 保留原文 */ }
  }
  calls.push({ url: String(url), method: options.method || "GET", body });
  if (!queue.length) throw new Error("未预置的请求：" + url);
  const next = queue.shift();
  if (next.url && String(url).indexOf(next.url) === -1) {
    throw new Error("请求顺序不符：期望 " + next.url + "，实际 " + url);
  }
  if (next.method && (options.method || "GET") !== next.method) {
    throw new Error("请求方法不符：期望 " + next.method + "，实际 " + (options.method || "GET"));
  }
  if (next.network) throw new Error("无法连接本地服务");
  return next.raw ? rawResponse(next) : envelopeResponse(next);
}

// ---- 浏览器环境替身（只覆盖被测代码用到的部分）-----------------------------
class FakeClipboardItem {
  constructor(data) { this.data = data; }
}
const navigator = {
  clipboard: { write: async (items) => { clipboardWrites.push(items); } },
};
const document = {
  createElement: () => {
    const node = {
      href: "", download: "", removed: false,
      click() { downloads.push({ name: node.download, href: node.href }); },
      remove() { node.removed = true; },
    };
    return node;
  },
  body: { appendChild() {} },
  createRange: () => ({ selectNodeContents() {} }),
  getSelection: () => ({ removeAllRanges() {}, addRange() {} }),
  execCommand: () => true,
};
const URLStub = { createObjectURL: () => "blob:report-eml", revokeObjectURL: () => {} };

// ---- 最小 hook 运行时（让真实组件可被挂载与重渲染）-------------------------
const hooks = { slots: [], cursor: 0, dirty: false };
let tree = null;
let currentProps = null;

function useState(init) {
  const index = hooks.cursor++;
  if (!(index in hooks.slots)) hooks.slots[index] = typeof init === "function" ? init() : init;
  const set = (next) => {
    const value = typeof next === "function" ? next(hooks.slots[index]) : next;
    if (value !== hooks.slots[index]) {
      hooks.slots[index] = value;
      hooks.dirty = true;
    }
  };
  return [hooks.slots[index], set];
}

function useRef(init) {
  const index = hooks.cursor++;
  if (!(index in hooks.slots)) hooks.slots[index] = { current: init };
  return hooks.slots[index];
}

// 组件挂载副作用不在本文件断言范围，但必须占位以保持 hook 顺序稳定
function useEffect() { hooks.cursor++; }
function useCallback(fn) { return fn; }

function htmlStub(strings, ...values) {
  return { __template: true, strings: Array.from(strings), values };
}

// ---- 模块加载：真实文件 + 合成模块 -----------------------------------------
const context = vm.createContext({
  console: { log() {}, warn() {}, error() {}, info() {} },
  setTimeout, clearTimeout, Promise, JSON, Math, Date, Object, Array, String, Number, Boolean, RegExp, Error,
  Map, Set, encodeURIComponent, decodeURIComponent, URLSearchParams, Blob, URL: URLStub,
  navigator, window: { isSecureContext: true, location: { hash: "" } },
  document, ClipboardItem: FakeClipboardItem, fetch: fakeFetch,
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

async function linker(specifier) {
  if (specifier.includes("preact-htm")) {
    return synthetic({ html: htmlStub, useState, useRef, useEffect, useCallback });
  }
  if (specifier === "./api.js" || specifier === "/static/host/api.js") {
    return loadFile(API_PATH);
  }
  if (specifier === "/static/host/report-controller.js") {
    return loadFile(CONTROLLER_PATH);
  }
  if (specifier === "./common.js") {
    const apiModule = await loadFile(API_PATH);
    return synthetic({
      html: htmlStub,
      api: apiModule.namespace.api,
      useLoad: () => ({
        data: scenario.stateData || {},
        errors: {},
        loading: false,
        reload: () => { reloads.push(true); },
      }),
      useWorkbenchStyles: () => {},
      Pill: (props) => htmlStub`<span class="wb-pill">${props.children}</span>`,
      PageHead: (props) => htmlStub`<header>${props.title}${props.sub || ""}</header>`,
      Progress: () => htmlStub`<div class="wb-progress"></div>`,
      go: (hash) => { navigations.push(hash); },
      todayString: () => scenario.today || "2026-10-31",
    });
  }
  throw new Error("unexpected specifier: " + specifier);
}

async function loadFile(filePath) {
  if (cache.has(filePath)) return cache.get(filePath);
  const mod = new vm.SourceTextModule(readFileSync(filePath, "utf8"), {
    context,
    identifier: filePath,
    initializeImportMeta(meta) { meta.url = pathToFileURL(filePath).href; },
  });
  cache.set(filePath, mod);
  await mod.link(linker);
  await mod.evaluate();
  return mod;
}

// ---- vnode 树工具 ----------------------------------------------------------
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

function findButtons(label) {
  const found = [];
  walk(tree, (node) => {
    // 只认真正的 <button> 节点：祖先模板里也会出现同名文案，不能把祖先的 onClick 当按钮
    if (!String(node.strings[0] || "").trim().startsWith("<button")) return;
    const props = propsOf(node);
    if (typeof props.onClick === "function" && textOf(node).indexOf(label) !== -1) found.push(props);
  });
  return found;
}

function render() {
  hooks.cursor = 0;
  hooks.dirty = false;
  tree = scenario.action === "component"
    ? reportsNamespace.DailyReportCard(currentProps)
    : null;
}

async function flush() {
  for (let i = 0; i < 50; i++) {
    if (!hooks.dirty) return;
    await sleep(0);
    render();
  }
}

// ---- 载入被测模块 ----------------------------------------------------------
const controller = await loadFile(CONTROLLER_PATH);
const controllerNamespace = controller.namespace;
let reportsNamespace = null;
if (scenario.action === "component") {
  reportsNamespace = (await loadFile(REPORTS_PATH)).namespace;
}

const out = { action: scenario.action };

if (scenario.action === "controller") {
  const ns = controllerNamespace;
  const noWait = async () => {};
  out.savedTexts = ns.savedTexts(scenario.preferences, scenario.form);

  const progress = [];
  const outcome = await ns.runSignDaily({
    form: scenario.form,
    preferences: scenario.preferences,
    wait: noWait,
    renderChart: (groups, key) => "data:image/png;base64," + key,
    onProgress: (item) => progress.push({
      phase: item.phase,
      task: item.task ? { status: item.task.status, stage: item.task.stage, percent: item.task.percent } : null,
    }),
  });
  out.progress = progress;
  out.images = outcome.images;
  out.body = outcome.body;
  out.notices = outcome.result.notices;
  out.imagesError = outcome.imagesError;
  out.preview = ns.previewHtml(outcome.result, outcome.images);
  out.previewNoImage = ns.previewHtml(outcome.result, {});
  out.copy = ns.copyPayload(outcome.result, outcome.images);
  out.exportAllowed = ns.exportAllowed(outcome.result);
  out.blockReason = ns.blockReason(outcome.result);
  out.missing = ns.missingChartKeys(outcome.result, outcome.images);
  out.missingWithoutImages = ns.missingChartKeys(outcome.result, {});

  out.emlName = await ns.downloadEml({ body: outcome.body, images: outcome.images });

  // 非安全上下文（没有剪贴板 API）时退回选中复制；没有节点时必须给出可读提示而不是静默失败
  const insecure = { isSecureContext: false, navigator: {}, ClipboardItem: undefined, document };
  out.copyFallback = await ns.copyToClipboard({ html: "<p>x</p>", text: "x" }, { ...insecure, fallbackNode: {} });
  try {
    await ns.copyToClipboard({ html: "<p>x</p>", text: "x" }, { ...insecure, fallbackNode: null });
  } catch (error) {
    out.copyFallbackError = error.message;
  }

  out.gate = {
    allowed: ns.exportAllowed(scenario.gateResult),
    reason: ns.blockReason(scenario.gateResult),
  };
  const callsBeforeGate = calls.length;
  try {
    await ns.downloadEml({ body: outcome.body, images: outcome.images });
  } catch (error) {
    out.emlGateError = { message: error.message, code: error.code, status: error.status };
  }
  out.gateEmlAttempts = calls.length - callsBeforeGate;
  // 宿主 _json_error 只填 error.type：分类必须从 type 兜底认出来
  out.isGateFromType = ns.isStatusGateError({ type: "StatusGateBlocked" });
  out.isGateFromCode = ns.isStatusGateError({ code: "StatusGateBlocked" });
  out.isGateFromApiError = ns.isStatusGateError(Object.assign(new Error("门禁"), { type: "StatusGateBlocked" }));
  out.isGatePlainError = ns.isStatusGateError(new Error("网络失败"));

  const callsBeforeRefreshFailure = calls.length;
  try {
    await ns.runSignDaily({ form: scenario.form, wait: noWait, onProgress: () => {} });
  } catch (error) {
    out.refreshError = { message: error.message, code: error.code, stage: error.stage };
  }
  out.refreshFailureCalls = calls.slice(callsBeforeRefreshFailure).map((call) => call.url);

  const callsBeforeCancel = calls.length;
  out.cancel = await ns.runSignDaily({
    form: scenario.form, wait: noWait, onProgress: () => {}, isAlive: () => false,
  });
  out.cancelCalls = calls.slice(callsBeforeCancel).map((call) => call.url);
  out.downloads = downloads.slice();
  out.navigations = navigations.slice();
} else if (scenario.action === "component") {
  // 1) 报告页把日报卡片接上同一份 state（不是跳转链接）
  const page = reportsNamespace.default({});
  const cards = [];
  walk(page, (node) => {
    const props = propsOf(node);
    if (typeof props.onReload === "function" && props.state) cards.push(props);
  });
  out.pageCardFound = cards.length;
  out.pageCardStateSubject = cards.length ? cards[0].state.form.projects : null;

  // 2) 挂载真实日报卡片，真的点「一键生成日报」
  hooks.slots = [];
  currentProps = {
    state: scenario.stateData.signDaily,
    fresh: true,
    onReload: () => { reloads.push(true); },
  };
  render();
  out.idleText = textOf(tree);

  const generate = findButtons("一键生成日报")[0];
  out.foundGenerate = Boolean(generate);
  if (generate) {
    const pending = generate.onClick();
    await sleep(80);
    await flush();
    out.progressText = textOf(tree);
    await pending;
    await flush();
    out.previewText = textOf(tree);

    const copy = findButtons("复制正文")[0];
    out.foundCopy = Boolean(copy);
    out.copyDisabled = copy ? copy.disabled : null;
    if (copy && !scenario.gateOnly) {
      await copy.onClick();
      await flush();
      out.afterCopyText = textOf(tree);
    }

    const eml = findButtons("下载 .eml 草稿")[0];
    out.foundEml = Boolean(eml);
    out.emlDisabled = eml ? eml.disabled : null;
    if (eml && !scenario.gateOnly) {
      await eml.onClick();
      await sleep(10);
      await flush();
      out.afterEmlText = textOf(tree);
    }
  }
  out.clipboardItems = clipboardWrites.length;
  out.clipboardTypes = clipboardWrites.length ? Object.keys(clipboardWrites[0][0].data) : [];
  out.downloads = downloads.slice();
  out.navigations = navigations.slice();
  out.reloads = reloads.length;
} else {
  throw new Error("unknown action: " + scenario.action);
}

out.calls = calls.map((call) => ({ url: call.url, method: call.method, body: call.body }));
console.log(JSON.stringify(out));
"""


def _run_node_scenario(scenario: dict) -> dict:
    node = shutil.which("node")
    assert node is not None, "未找到 Node.js 命令"
    res = subprocess.run(
        [
            node,
            "--experimental-vm-modules",
            "--input-type=module",
            "-e",
            _RUNNER_JS,
            str(CONTROLLER_JS),
            str(REPORTS_JS),
            str(API_JS),
            json.dumps(scenario, ensure_ascii=False, separators=(",", ":")),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert res.returncode == 0, f"Node 执行失败 (code {res.returncode}):\n{res.stderr}\n{res.stdout}"
    lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip().startswith("{")]
    assert lines, f"未获取到 Node 输出的 JSON 行:\n{res.stdout}"
    return json.loads(lines[-1])


# ---------------------------------------------------------------------------
# 合成数据：与后端 /state、/refresh、/generate、/eml 返回的形状一致
# ---------------------------------------------------------------------------

_GATE_TEXT = (
    "状态列是数字码（3：2 份），已禁止发送：请先确认码值含义或改用归档快照；"
    "临时放行需管理员把 statusGateEnabled 置为 false"
)

_ORPHAN_NOTICE = "所选项目在所选范围内没有单，未计入：已停产项目"

_FORM = {
    "projects": ["F610S", "已停产项目"],
    "departments": ["车体科"],
    "watchlistOnly": True,
    "region": "车体区域",
}


def _preference_key(form: dict) -> str:
    key = {"projects": sorted(form["projects"]), "departments": sorted(form["departments"])}
    if form["watchlistOnly"]:
        key["watchlistOnly"] = True
    return json.dumps(key, ensure_ascii=False)


_PREFERENCES = {
    _preference_key(_FORM): {
        "region": "车体区域",
        "greeting": "各位领导：",
        "planText": "计划10-10发布，已超期2天",
        "feishuLink": "https://example.invalid/feishu",
        "to": "",
        "cc": "",
    },
}

_RESULT = {
    "subject": "F610S&已停产项目项目3D单签署进展-车体区域-20261031",
    "projectLabel": "F610S&已停产项目",
    "dataDate": "2026-10-31",
    "snapshotAt": "2026-10-31T02:00:00Z",
    "stale": False,
    "baseDate": "2026-10-30",
    "summary": {},
    "baseline": {},
    "delta": {},
    "summaryLines": ["汇总数字"],
    "charts": {"external": [{"group": "车体", "bars": []}], "sections": [], "approval": []},
    "flows": [],
    "longCycle": {"review": [], "excluded": [], "misses": []},
    "exportBlocked": False,
    "notices": [
        {"kind": "selectedWithoutData", "blocking": False, "projects": ["已停产项目"], "text": _ORPHAN_NOTICE},
    ],
    "anomalies": [],
    "watchlist": {"count": 1, "missing": [], "counted": 1},
    "selectedWithoutData": ["已停产项目"],
    "statusGate": {"enabled": True, "blocked": False, "codes": [], "text": ""},
    "coverage": "all",
    "seedVersion": "test",
    "snapshotSaved": True,
    "scopeKey": _preference_key(_FORM),
    "texts": {"region": "车体区域", "greeting": "各位领导：", "planText": "计划10-10发布，已超期2天", "feishuLink": ""},
    "thresholds": {"warnDays": 7, "overdueDays": 14, "baselineMaxGapDays": 30},
    "html": (
        '<div><p>各位领导：</p><p>汇总数字</p>'
        '<p><b>图1 外区域会签未签单情况</b></p>'
        '<p><img src="cid:sd-external" width="720" alt="图1"></p>'
        "<p>在途流程签署明细</p></div>"
    ),
    "text": "各位领导：\n汇总数字\n在途流程签署明细：\n",
    "chartsWithData": ["external"],
    "recipients": {"to": [], "cc": [], "added": [], "missing": [], "ambiguous": []},
    "recipientsText": {"to": "", "cc": ""},
}

_GATE_RESULT = dict(
    _RESULT,
    exportBlocked=False,
    statusGate={"enabled": True, "blocked": True, "codes": [{"code": "3", "flows": 2}], "text": _GATE_TEXT},
)

_DAILY_STATE = {
    "data": {"dataDate": "2026-10-31", "snapshotAt": "2026-10-31T02:00:00Z", "coverage": "all"},
    "dataError": None,
    "options": {"projects": ["F610S"], "departments": ["车体科"]},
    "form": dict(_FORM),
    "preferences": _PREFERENCES,
    "legacyRecipients": {},
    "thresholds": {"warnDays": 7, "overdueDays": 14, "baselineMaxGapDays": 30},
    "addressBook": "",
    "personAreas": {},
    "areaNames": {},
    "externalColumns": [],
    "watchlist": {"scope": "all", "serials": ["A-1"], "count": 1},
    "seedVersion": "test",
}

_COMPONENT_RESULT = dict(
    _RESULT,
    chartsWithData=[],
    charts={"external": [], "sections": [], "approval": []},
    html='<div><p>各位领导：</p><p>汇总数字</p><p>在途流程签署明细</p></div>',
)

_EML_HEADERS = {"Content-Disposition": "attachment; filename=\"daily-report.eml\""}


def _controller_scenario() -> dict:
    return {
        "action": "controller",
        "form": _FORM,
        "preferences": _PREFERENCES,
        "gateResult": _GATE_RESULT,
        "fetchQueue": [
            {"url": "/api/p/sign-daily/refresh", "method": "POST",
             "data": {"taskId": "t1", "status": "running", "stage": "正在抓取 TDC 数模设计审核流程", "percent": 40}},
            {"url": "/api/p/sign-daily/refresh/t1", "method": "GET",
             "data": {"taskId": "t1", "status": "running", "stage": "正在抓取 TDC 数模设计审核流程", "percent": 80}},
            {"url": "/api/p/sign-daily/refresh/t1", "method": "GET",
             "data": {"taskId": "t1", "status": "succeeded", "stage": "抓取完成", "percent": 100}},
            {"url": "/api/p/sign-daily/generate", "method": "POST", "data": _RESULT},
            {"url": "/api/p/sign-daily/eml", "method": "POST", "raw": True, "headers": _EML_HEADERS},
            {"url": "/api/p/sign-daily/eml", "method": "POST", "ok": False, "status": 409,
             "error": {"type": "StatusGateBlocked", "message": _GATE_TEXT}},
            {"url": "/api/p/sign-daily/refresh", "method": "POST",
             "data": {"taskId": "t9", "status": "failed",
                      "error": "TDC 抓取未完成：登录信息已失效，请重新登录并保存至凭据保护库（credential_invalid）"}},
            {"url": "/api/p/sign-daily/refresh", "method": "POST",
             "data": {"taskId": "t10", "status": "running", "stage": "正在抓取", "percent": 5}},
        ],
    }


def _component_scenario() -> dict:
    return {
        "action": "component",
        "today": "2026-10-31",
        "stateData": {"signDaily": _DAILY_STATE, "tir": {"data": {"dataDate": "2026-10-31"}}},
        "fetchQueue": [
            {"url": "/api/p/sign-daily/refresh", "method": "POST",
             "data": {"taskId": "t1", "status": "running", "stage": "正在抓取 TDC 数模设计审核流程", "percent": 40}},
            {"url": "/api/p/sign-daily/refresh/t1", "method": "GET",
             "data": {"taskId": "t1", "status": "succeeded", "stage": "抓取完成", "percent": 100}},
            {"url": "/api/p/sign-daily/generate", "method": "POST", "data": _COMPONENT_RESULT},
            {"url": "/api/p/sign-daily/eml", "method": "POST", "raw": True, "headers": _EML_HEADERS},
        ],
    }


def _gate_component_scenario() -> dict:
    """门禁拦截的生成结果：页面必须原样显示原因，并且不再请求 /eml。"""
    scenario = _component_scenario()
    scenario["gateOnly"] = True
    scenario["fetchQueue"] = [
        scenario["fetchQueue"][0],
        scenario["fetchQueue"][1],
        {"url": "/api/p/sign-daily/generate", "method": "POST", "data": dict(
            _GATE_RESULT,
            chartsWithData=[],
            charts={"external": [], "sections": [], "approval": []},
            html='<div><p>各位领导：</p><p>汇总数字</p></div>',
        )},
    ]
    return scenario


# ---------------------------------------------------------------------------
# 验收 3：复用现有接口，提交 → 轮询进度 → 生成
# ---------------------------------------------------------------------------


@needs_node
def test_controller_submits_polls_and_generates_through_existing_apis() -> None:
    data = _run_node_scenario(_controller_scenario())
    calls = data["calls"]

    assert calls[0]["url"] == "/api/p/sign-daily/refresh"
    assert calls[0]["method"] == "POST"
    assert calls[0]["body"] == {"watchlistOnly": True}
    assert [call["method"] for call in calls[1:3]] == ["GET", "GET"]
    assert calls[1]["url"] == "/api/p/sign-daily/refresh/t1"
    assert calls[2]["url"] == "/api/p/sign-daily/refresh/t1"

    generate = calls[3]
    assert generate["url"] == "/api/p/sign-daily/generate"
    assert generate["method"] == "POST"
    # 历史残留项目原样提交，绝不自动删除；文案用该范围已记住的偏好
    assert generate["body"]["projects"] == ["F610S", "已停产项目"]
    assert generate["body"]["departments"] == ["车体科"]
    assert generate["body"]["watchlistOnly"] is True
    assert generate["body"]["region"] == "车体区域"
    assert generate["body"]["greeting"] == "各位领导："
    assert generate["body"]["planText"] == "计划10-10发布，已超期2天"
    assert generate["body"]["feishuLink"] == ""

    phases = [item["phase"] for item in data["progress"]]
    assert phases == ["refresh", "refresh", "refresh", "generate"], phases
    assert data["progress"][1]["task"]["percent"] == 40
    assert data["progress"][2]["task"]["percent"] == 80
    assert data["progress"][3]["task"]["status"] == "succeeded"

    # savedTexts 只解析后端已存下的键，不重拼 scope_key 格式
    assert data["savedTexts"]["greeting"] == "各位领导："


@needs_node
def test_refresh_failure_reports_backend_reason_and_skips_generate() -> None:
    data = _run_node_scenario(_controller_scenario())
    error = data["refreshError"]
    assert error["stage"] == "refresh"
    assert error["code"] == "failed"
    assert error["message"].startswith("TDC 抓取未完成：登录信息已失效")
    # 抓取失败只发生在 refresh 上，没有偷偷调用 generate
    assert data["refreshFailureCalls"] == ["/api/p/sign-daily/refresh"]
    assert all("/generate" not in url for url in data["refreshFailureCalls"])


@needs_node
def test_cancel_stops_polling_without_generating() -> None:
    data = _run_node_scenario(_controller_scenario())
    assert data["cancel"] is None
    assert data["cancelCalls"] == ["/api/p/sign-daily/refresh"]


# ---------------------------------------------------------------------------
# 验收 1：预览、复制与邮件草稿都来自同一次生成结果
# ---------------------------------------------------------------------------


@needs_node
def test_preview_inlines_the_same_png_and_copy_keeps_backend_text() -> None:
    data = _run_node_scenario(_controller_scenario())
    assert data["images"] == {"external": "data:image/png;base64,external"}
    assert 'src="data:image/png;base64,external"' in data["preview"]
    assert "cid:sd-external" not in data["preview"]
    # 没有出图时用可读占位，不留破图
    assert "图表未在本页渲染" in data["previewNoImage"]
    assert "cid:sd-external" not in data["previewNoImage"]

    assert data["copy"]["text"] == _RESULT["text"]
    assert "data:image/png;base64,external" in data["copy"]["html"]
    assert data["exportAllowed"] is True
    assert data["blockReason"] == ""
    assert data["missing"] == []
    assert data["missingWithoutImages"] == ["external"]


@needs_node
def test_copy_falls_back_to_selection_when_clipboard_api_is_unavailable() -> None:
    """非安全上下文没有剪贴板 API：退回选中复制；没有节点时给可读提示，不静默失败。"""
    data = _run_node_scenario(_controller_scenario())
    assert "已改用选中复制" in data["copyFallback"]
    assert "请到完整日报页" in data["copyFallbackError"]


@needs_node
def test_email_draft_uses_existing_eml_endpoint_and_only_downloads() -> None:
    data = _run_node_scenario(_controller_scenario())
    eml_calls = [call for call in data["calls"] if call["url"] == "/api/p/sign-daily/eml"]
    assert eml_calls, "没有调用现有 /eml 接口"
    body = eml_calls[0]["body"]
    assert body["images"] == {"external": "data:image/png;base64,external"}
    assert body["proceedWithSuggestion"] is False
    assert body["projects"] == ["F610S", "已停产项目"]
    assert data["emlName"] == "daily-report.eml"
    assert data["downloads"] == [{"name": "daily-report.eml", "href": "blob:report-eml"}]


# ---------------------------------------------------------------------------
# 验收 4：StatusGateBlocked 原样展示、不重试；孤儿项目走后端提示
# ---------------------------------------------------------------------------


@needs_node
def test_status_gate_blocked_is_shown_verbatim_and_not_retried() -> None:
    data = _run_node_scenario(_controller_scenario())
    assert data["gate"]["allowed"] is False
    assert data["gate"]["reason"] == _GATE_TEXT, "门禁原因必须是后端原文"

    error = data["emlGateError"]
    assert error["message"] == _GATE_TEXT
    # 宿主 _json_error(409, "StatusGateBlocked", text) 只写 error.type，没有 error.code：
    # 控制器必须从 type 兜底认出分类，否则门禁会被当成普通失败。
    assert error["code"] == "StatusGateBlocked"
    assert error["status"] == 409
    # 只尝试了一次：没有重试，也没有第二条 /eml 请求
    assert data["gateEmlAttempts"] == 1

    # 分类识别对 type / code / ApiError 都成立，普通失败不误判为门禁
    assert data["isGateFromType"] is True
    assert data["isGateFromCode"] is True
    assert data["isGateFromApiError"] is True
    assert data["isGatePlainError"] is False


@needs_node
def test_reports_page_shows_status_gate_verbatim_and_disables_export() -> None:
    """门禁拦截时报告页原位显示后端原文，复制/邮件草稿都禁用，且不重试 /eml。"""
    data = _run_node_scenario(_gate_component_scenario())

    assert data["foundGenerate"] is True
    assert _GATE_TEXT in data["previewText"], data["previewText"]
    assert data["foundCopy"] is True and data["copyDisabled"] is True
    assert data["foundEml"] is True and data["emlDisabled"] is True
    assert data["clipboardItems"] == 0
    assert data["downloads"] == []
    assert data["navigations"] == []
    urls = [call["url"] for call in data["calls"]]
    assert urls == [
        "/api/p/sign-daily/refresh",
        "/api/p/sign-daily/refresh/t1",
        "/api/p/sign-daily/generate",
    ], f"门禁拦截后仍尝试了其它请求：{urls}"


@needs_node
def test_orphan_project_is_kept_and_backend_notice_is_passed_through() -> None:
    data = _run_node_scenario(_controller_scenario())
    # 历史残留项目照原样提交（绝不自动删除），由后端给出「未计入」的原文提示
    assert "已停产项目" in data["body"]["projects"]
    assert data["notices"][0]["text"] == _ORPHAN_NOTICE


# ---------------------------------------------------------------------------
# 验收 1 + 2：报告页原位生成（进度、预览、复制、邮件草稿），不是跳转链接
# ---------------------------------------------------------------------------


@needs_node
def test_reports_page_generates_in_place_with_progress_and_preview() -> None:
    data = _run_node_scenario(_component_scenario())

    assert data["pageCardFound"] == 1, "报告页没有把日报卡片接上 state"
    assert data["pageCardStateSubject"] == ["F610S", "已停产项目"]
    assert data["foundGenerate"] is True, "没有渲染「一键生成日报」按钮"

    assert "正在抓取 TDC 数模设计审核流程（40%）" in data["progressText"], data["progressText"]
    assert _RESULT["subject"] in data["previewText"]
    assert "复制正文" in data["previewText"]
    assert "下载 .eml 草稿" in data["previewText"]
    # 孤儿项目由后端结果提示，页面原样展示（可见、不被丢弃）
    assert _ORPHAN_NOTICE in data["previewText"]

    # 真的提交了生成，且没有用跳转冒充一键生成
    urls = [call["url"] for call in data["calls"]]
    assert urls[:3] == [
        "/api/p/sign-daily/refresh",
        "/api/p/sign-daily/refresh/t1",
        "/api/p/sign-daily/generate",
    ], urls
    assert data["navigations"] == [], f"生成过程发生了跳转：{data['navigations']}"

    generate = data["calls"][2]
    assert generate["body"]["projects"] == ["F610S", "已停产项目"]
    assert generate["body"]["greeting"] == "各位领导："
    assert data["reloads"] == 1, "生成后应刷新报告页的数据状态"


@needs_node
def test_reports_page_copy_and_email_draft_are_available_after_generation() -> None:
    data = _run_node_scenario(_component_scenario())

    assert data["foundCopy"] is True
    assert data["clipboardItems"] == 1
    assert data["clipboardTypes"] == ["text/html", "text/plain"]
    assert "正文已复制" in data["afterCopyText"]

    assert data["foundEml"] is True
    assert data["emlDisabled"] is False
    assert data["downloads"] == [{"name": "daily-report.eml", "href": "blob:report-eml"}]
    assert "邮件草稿已下载" in data["afterEmlText"]
    assert data["navigations"] == []


# ---------------------------------------------------------------------------
# 回归：控制器/页面只经宿主模块与现有接口，不跨插件 import
# ---------------------------------------------------------------------------


def test_controller_and_page_do_not_statically_import_other_plugins() -> None:
    controller = CONTROLLER_JS.read_text(encoding="utf-8")
    page = REPORTS_JS.read_text(encoding="utf-8")

    # 允许宿主按插件静态资源 URL 动态载入既有出图模块（运行时代码，不是静态 import）
    static_plugin_import = re.compile(r"^\s*import\b[^\n]*[\"']/plugins/", re.MULTILINE)
    for text in (controller, page):
        assert not static_plugin_import.search(text), "不得静态 import 其他插件模块"
        assert "report-logic.js" not in text
        assert "plugins/sign_daily/static/report.js" not in text
        assert "plugins/tir_report" not in text

    assert 'from "./api.js"' in controller
    assert '"/static/host/report-controller.js"' in page
    # 门禁分类的判定只在宿主模块里，报告页只调用它，不自己复制一份判定规则
    assert "isStatusGateError" in controller
    assert "isStatusGateError" in page
