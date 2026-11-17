# -*- coding: utf-8 -*-
"""向导选择 → 首次启用同步（DSH-V2-13；契约 C3 向导条款 / C1 前端宿主模块）。

本文件用 Node 真实执行三个模块：
- `plugins/workbench/static/wizard.js`；
- `plugins/project_overview/static/auto-sync.js`；
- 新建的宿主交接模块 `web/static/host/onboarding-selection.js`。

覆盖：
1. `selectedDeliverables` 真正约束自动同步的启用范围（未勾选的不发 sync-now）；
2. 首次同步由真实任务触发：自动同步页点击开始后，真实 `deliverable/enable-flow.js`
   调用现有 `/api/project-status/deliverables/<id>/sync-now` 接口，结果逐项显示；
3. 仅跳页、未开始或失败都不得算全部完成（宿主模块状态只由真实结果推导）；
4. 向导与 project_overview 不互相 import，经宿主模块 `/static/host/onboarding-selection.js` 交接。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WIZARD_JS = REPO_ROOT / "plugins" / "workbench" / "static" / "wizard.js"
AUTO_SYNC_JS = REPO_ROOT / "plugins" / "project_overview" / "static" / "auto-sync.js"
ENABLE_FLOW_JS = REPO_ROOT / "plugins" / "project_overview" / "static" / "deliverable" / "enable-flow.js"
HOST_JS = REPO_ROOT / "web" / "static" / "host" / "onboarding-selection.js"


def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
        m = re.match(r"v(\d+)", out.strip())
        return int(m.group(1)) if m else 0
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

const [, WIZARD_JS_PATH, AUTO_SYNC_JS_PATH, ENABLE_FLOW_JS_PATH, HOST_JS_PATH, SCENARIO_JSON] = process.argv;
const scenario = JSON.parse(SCENARIO_JSON);

// ---- localStorage 桩 -------------------------------------------------------
const storage = new Map();
for (const [k, v] of Object.entries(scenario.initialStorage || {})) {
  storage.set(String(k), typeof v === "string" ? v : JSON.stringify(v));
}
const localStorage = {
  getItem: (k) => (storage.has(String(k)) ? storage.get(String(k)) : null),
  setItem: (k, v) => { storage.set(String(k), String(v)); },
  removeItem: (k) => { storage.delete(String(k)); },
  clear: () => { storage.clear(); },
  get length() { return storage.size; },
  key: (i) => Array.from(storage.keys())[i] || null,
  _dump: () => Object.fromEntries(storage.entries()),
};

const navigations = [];
const apiCalls = [];
const syncCalls = [];

const windowStub = { localStorage, location: { hash: "", reload() {} } };
const context = vm.createContext({
  console: { log() {}, warn() {}, error() {}, info() {} },
  setTimeout, clearTimeout,
  Promise, JSON, Math, Date, Object, Array, String, Number, Boolean, RegExp, Error, Set, Map,
  encodeURIComponent, decodeURIComponent,
  window: windowStub,
  localStorage,
});

// ---- 最小 hook 运行时 ------------------------------------------------------
const hooks = { slots: [], cursor: 0, dirty: false, effects: [] };

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

function useEffect(fn, deps) {
  const index = hooks.cursor++;
  const prev = hooks.slots[index];
  const same = prev && Array.isArray(deps) && Array.isArray(prev.deps)
    && deps.length === prev.deps.length && deps.every((d, i) => d === prev.deps[i]);
  if (!prev || !same) {
    hooks.slots[index] = { deps: Array.isArray(deps) ? deps.slice() : [], cleanup: prev ? prev.cleanup : null };
    hooks.effects.push(fn);
  }
}

function useRef(init) {
  const index = hooks.cursor++;
  if (!(index in hooks.slots)) hooks.slots[index] = { current: init };
  return hooks.slots[index];
}

function useCallback(fn) { return fn; }

function htmlStub(strings, ...values) {
  return { __template: true, strings: Array.from(strings), values };
}

function synthetic(names, exportsObject) {
  return new vm.SyntheticModule(names, function () {
    for (const name of names) this.setExport(name, exportsObject[name]);
  }, { context });
}

// ---- 假接口：按路径分流，sync-now 只认真实 POST ---------------------------
function pathOf(value) { return String(value).split("?")[0]; }

async function fakeApiRequest(path, options = {}) {
  const method = options.method || "GET";
  const key = pathOf(path);
  apiCalls.push({ path: key, method, body: options.body === undefined ? null : options.body });
  if (method === "POST" && key.endsWith("/sync-now")) {
    const id = key.split("/")[4];
    syncCalls.push(id);
    const spec = (scenario.syncResults || {})[id];
    if (!spec) throw new Error("未预置同步结果: " + id);
    if (spec.error) throw new Error(spec.error);
    // 模拟后端：启用流程先保存策略，sync-now 之后该项策略为已启用。
    scenario.policies = scenario.policies || {};
    scenario.policies[id] = { enabled: true };
    return Object.prototype.hasOwnProperty.call(spec, "data") ? spec.data : spec;
  }
  if (method === "PATCH" && key.endsWith("/update-policy")) return {};
  if (method === "PATCH" && key.startsWith("/api/project-status/phases/")) return {};
  if (method === "PATCH" && key.startsWith("/api/p/workbench/projects/")) return {};
  if (method === "GET" && key === "/api/project-status") return scenario.status || { phase: {}, deliverables: [] };
  if (method === "GET" && key === "/api/settings") return scenario.settings || { credentialVaultConfigured: true };
  if (method === "GET" && key === "/api/p/workbench/projects") return scenario.projects || { projects: [] };
  if (method === "GET" && key.startsWith("/api/project-status/deliverables/") && key.endsWith("/update-policy")) {
    const id = key.split("/")[4];
    return (scenario.policies || {})[id] || { enabled: false };
  }
  throw new Error("未预置的接口调用: " + method + " " + key);
}

async function fakeWizardApi(url, options) {
  const opts = options || {};
  const key = pathOf(url);
  apiCalls.push({ path: key, method: opts.method || "GET", body: opts.body === undefined ? null : opts.body });
  const spec = (scenario.wizardApi || {})[key];
  if (spec === undefined) throw new Error("未预置的向导接口调用: " + key);
  if (spec && spec.error) {
    const err = new Error(spec.error.message || "请求失败");
    err.name = "ApiError";
    err.status = spec.error.status === undefined ? 0 : spec.error.status;
    err.type = spec.error.type || (err.status ? "http" : "network");
    err.code = spec.error.code === undefined ? null : spec.error.code;
    throw err;
  }
  return spec && Object.prototype.hasOwnProperty.call(spec, "data") ? spec.data : spec;
}

// ---- 载入真实模块 ---------------------------------------------------------
const hostCode = readFileSync(HOST_JS_PATH, "utf8");
async function loadHostModule() {
  const mod = new vm.SourceTextModule(hostCode, { context });
  await mod.link(() => { throw new Error("宿主模块不应有静态 import"); });
  await mod.evaluate();
  return mod;
}
const hostForWizard = await loadHostModule();
const hostForAutoSync = await loadHostModule();

const enableFlowMod = new vm.SourceTextModule(readFileSync(ENABLE_FLOW_JS_PATH, "utf8"), { context });
await enableFlowMod.link(async (specifier) => {
  if (specifier === "./api.js") {
    return synthetic(["apiRequest", "enc"], { apiRequest: fakeApiRequest, enc: encodeURIComponent });
  }
  if (specifier === "./discovery.js") {
    return synthetic(["newWizardSessionId", "postMappingDiscovery"], {
      newWizardSessionId: () => "wizard-session-1",
      postMappingDiscovery: async () => ({ state: "matched", stability: { confirmed: 2 }, candidates: [] }),
    });
  }
  if (specifier === "./policy-logic.js") {
    return synthetic([
      "buildWizardDiscovery", "dropDepartment", "stabilityGateFailureMessage", "wizardMapping",
      "wizardNotMatchedMessage", "wizardPolicyPatch", "wizardRetryWithoutDepartment",
    ], {
      buildWizardDiscovery: () => ({ payload: {}, kind: { isTdc: false }, aggregate: true }),
      dropDepartment: () => {},
      stabilityGateFailureMessage: () => "映射不稳定",
      wizardMapping: () => ({}),
      wizardNotMatchedMessage: () => "没有匹配到记录",
      wizardPolicyPatch: () => ({}),
      wizardRetryWithoutDepartment: (payload) => payload,
    });
  }
  throw new Error("unexpected enable-flow specifier: " + specifier);
});
await enableFlowMod.evaluate();

const wizardMod = new vm.SourceTextModule(readFileSync(WIZARD_JS_PATH, "utf8"), {
  context,
  importModuleDynamically: async (specifier) => {
    if (String(specifier).includes("onboarding-selection")) return hostForWizard;
    throw new Error("unexpected dynamic import: " + specifier);
  },
  initializeImportMeta(meta) { meta.url = pathToFileURL(WIZARD_JS_PATH).href; },
});
await wizardMod.link(async (specifier) => {
  if (specifier.includes("preact-htm")) {
    return synthetic(["html", "useState", "useEffect", "useCallback", "useRef"], {
      html: htmlStub, useState, useEffect, useCallback, useRef,
    });
  }
  if (specifier.includes("session.js")) {
    return synthetic(["submitDomainLogin", "updateSessionBadges"], {
      submitDomainLogin: async () => ({ kind: "success", text: "已登录", sessions: {} }),
      updateSessionBadges: () => {},
    });
  }
  if (specifier.includes("common.js")) {
    return synthetic(["api", "html", "go", "activeDeliverables"], {
      api: fakeWizardApi,
      html: htmlStub,
      go: (hash) => { navigations.push(hash); },
      activeDeliverables: (list) => (list || []).filter((d) => !d.retired),
    });
  }
  throw new Error("unexpected wizard specifier: " + specifier);
});
await wizardMod.evaluate();

const autoSyncMod = new vm.SourceTextModule(readFileSync(AUTO_SYNC_JS_PATH, "utf8"), { context });
await autoSyncMod.link(async (specifier) => {
  if (specifier.includes("onboarding-selection")) return hostForAutoSync;
  if (specifier.includes("preact-htm")) {
    return synthetic(["html", "useState", "useEffect", "useCallback", "useRef"], {
      html: htmlStub, useState, useEffect, useCallback, useRef,
    });
  }
  if (specifier.includes("kit.js")) {
    return synthetic(["useStylesheet"], { useStylesheet: () => {} });
  }
  if (specifier.includes("shared/client.js")) {
    return synthetic(["PROJECT_PHASE_ID"], { PROJECT_PHASE_ID: "VPI-T2" });
  }
  if (specifier.includes("deliverable/api.js")) {
    return synthetic(["apiRequest", "enc"], { apiRequest: fakeApiRequest, enc: encodeURIComponent });
  }
  if (specifier.includes("enable-flow.js")) return enableFlowMod;
  if (specifier.includes("deliverable/format.js")) {
    return synthetic(["redactSensitiveText"], {
      redactSensitiveText: (value) => (value === null || value === undefined ? "" : String(value)),
    });
  }
  if (specifier.includes("policy-logic.js")) {
    return synthetic(["capabilitiesOf", "ewoPolicyErrorMessage", "wizardInitialValues", "wizardKind", "wizardPrecheck"], {
      capabilitiesOf: (item) => (item && item.sourceInfo) || {},
      ewoPolicyErrorMessage: (err) => (err && err.message ? String(err.message) : "操作失败"),
      wizardInitialValues: () => ({}),
      wizardKind: () => ({ isDataModel: false, isNcr: false, isTdc: false }),
      wizardPrecheck: () => "",
    });
  }
  throw new Error("unexpected auto-sync specifier: " + specifier);
});
await autoSyncMod.evaluate();

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

function findBy(predicate) {
  const found = [];
  walk(tree, (node) => {
    const props = propsOf(node);
    const staticText = node.strings.join("");
    if (predicate(staticText, props)) found.push({ text: staticText, props });
  });
  return found;
}

// 同一个模板里可能并排多个按钮：按文案位置找它前面最近的 onClick= 对应的值，
// 避免把整段容器的 onClick 误当成目标按钮的处理器。
function handlerForLabel(label) {
  let handler = null;
  walk(tree, (node) => {
    if (handler) return;
    const strings = node.strings;
    const values = node.values;
    const positions = [];
    let offset = 0;
    for (const segment of strings) {
      positions.push(offset);
      offset += segment.length;
    }
    const full = strings.join("");
    const labelPos = full.lastIndexOf(label);
    if (labelPos === -1) return;
    const clickPos = full.lastIndexOf("onClick=", labelPos);
    if (clickPos === -1) return;
    for (let i = 0; i < strings.length; i++) {
      const start = positions[i];
      const end = start + strings[i].length;
      if (clickPos >= start && clickPos < end && typeof values[i] === "function") {
        handler = values[i];
        return;
      }
    }
  });
  return handler;
}

// 按钮文案是动态值时，按按钮的静态标记（class）定位它后面的 onClick=。
function handlerAfterMarker(marker) {
  let handler = null;
  walk(tree, (node) => {
    if (handler) return;
    const strings = node.strings;
    const values = node.values;
    const positions = [];
    let offset = 0;
    for (const segment of strings) {
      positions.push(offset);
      offset += segment.length;
    }
    const full = strings.join("");
    const markerPos = full.indexOf(marker);
    if (markerPos === -1) return;
    const clickPos = full.indexOf("onClick=", markerPos);
    if (clickPos === -1) return;
    for (let i = 0; i < strings.length; i++) {
      const start = positions[i];
      const end = start + strings[i].length;
      if (clickPos >= start && clickPos < end && typeof values[i] === "function") {
        handler = values[i];
        return;
      }
    }
  });
  return handler;
}

// ---- 挂载与重渲染 ----------------------------------------------------------
let tree = null;
let renderFn = null;

function render() {
  hooks.cursor = 0;
  hooks.dirty = false;
  tree = renderFn();
  const pending = hooks.effects;
  hooks.effects = [];
  for (const effect of pending) {
    try { effect(); } catch (_err) {}
  }
}

function mount(fn, props) {
  hooks.slots = [];
  hooks.cursor = 0;
  hooks.dirty = false;
  hooks.effects = [];
  renderFn = () => fn(props);
  tree = null;
  render();
}

async function flush() {
  for (let i = 0; i < 40; i++) {
    await new Promise((resolve) => setTimeout(resolve, 0));
    render();
  }
}

function autoSyncSnapshot() {
  return {
    text: textOf(tree),
    request: hostForAutoSync.namespace.readFirstSyncRequest(),
    selection: hostForAutoSync.namespace.readOnboardingSelection(),
    apiCalls: apiCalls.slice(),
    syncCalls: syncCalls.slice(),
  };
}

// ---- 场景 ------------------------------------------------------------------
const out = { action: scenario.action };

if (scenario.action === "hostUnit") {
  const host = hostForWizard.namespace;
  out.saved = host.saveOnboardingSelection({
    deliverables: ["d1", "d1", "", "d2"],
    vehicle: " F610S ",
    departments: ["车体科", "车体科", ""],
    projectId: " proj-1 ",
  });
  out.read = host.readOnboardingSelection();
  out.request = host.requestFirstSync({ deliverables: ["d1", "d2"], vehicle: "F610S", departments: ["车体科"], projectId: "proj-1" });
  out.afterRead = host.readFirstSyncRequest();
  out.summaryPending = host.summarizeFirstSync(out.afterRead.entries);
  out.afterOne = host.recordFirstSyncEntry({ id: "d1", name: "交付物一", state: "success", text: "首次同步成功" });
  out.summaryOne = host.summarizeFirstSync(out.afterOne.entries);
  out.afterTwo = host.recordFirstSyncEntry({ id: "d2", name: "交付物二", state: "failed", text: "首次同步失败：候选记录不唯一" });
  out.summaryTwo = host.summarizeFirstSync(out.afterTwo.entries);
  out.afterAll = host.recordFirstSyncEntry({ id: "d2", name: "交付物二", state: "success", text: "首次同步成功" });
  out.summaryAll = host.summarizeFirstSync(out.afterAll.entries);
  out.emptyRequest = host.requestFirstSync({ deliverables: [] });
  out.emptySummary = host.summarizeFirstSync(out.emptyRequest.entries);
  out.unknownRequest = host.requestFirstSync({ deliverables: ["d1"] });
  out.unknownEntry = host.recordFirstSyncEntry({ id: "d1", state: "done" });
  out.foreignEntry = host.recordFirstSyncEntry({ id: "d9", state: "success" });
  out.storage = localStorage._dump();
} else if (scenario.action === "hostLifecycle") {
  const host = hostForWizard.namespace;
  host.requestFirstSync({ deliverables: ["d1", "d2", "d3"] });
  out.naRequest = host.markFirstSyncNotApplicable([{ id: "d3", name: "手工项", text: "只能手工维护" }]);
  out.naSummaryBefore = host.summarizeFirstSync(out.naRequest.entries);
  host.recordFirstSyncEntry({ id: "d1", state: "success" });
  const done = host.recordFirstSyncEntry({ id: "d2", state: "success" });
  out.naSummaryDone = host.summarizeFirstSync(done.entries);
  out.naStatusDone = done.status;
  out.naNoOverride = host.markFirstSyncNotApplicable([{ id: "d1", text: "已开启自动同步" }]).entries[0].state;
  host.requestFirstSync({ deliverables: ["e1", "e2"] });
  host.markFirstSyncRunning(["e1", "e2"]);
  host.recordFirstSyncEntry({ id: "e1", state: "success" });
  out.failRunning = host.failRunningFirstSync("运行中断");
  host.requestFirstSync({ deliverables: ["f1"] });
  host.markFirstSyncRunning(["f1"]);
  out.recovered = host.recoverInterruptedFirstSync();
  host.requestFirstSync({ deliverables: ["g1"] });
  out.allNa = host.markFirstSyncNotApplicable([{ id: "g1", text: "已开启自动同步" }]);
  out.allNaSummary = host.summarizeFirstSync(out.allNa.entries);
} else if (scenario.action === "wizardFinish") {
  if (scenario.seedRequest) hostForWizard.namespace.requestFirstSync(scenario.seedRequest);
  const props = Object.assign({ projectName: "测试车型项目", onClose: () => {} }, scenario.mountProps || {});
  mount(wizardMod.namespace.Wizard, props);
  out.beforeText = textOf(tree);
  const label = scenario.button === "start" ? "开启自动同步" : "开始使用";
  const click = handlerForLabel(label);
  out.found = typeof click === "function";
  if (click) await click();
  await flush();
  out.afterText = textOf(tree);
  out.wizardState = wizardMod.namespace.loadWizardState();
  out.selection = hostForWizard.namespace.readOnboardingSelection();
  out.request = hostForWizard.namespace.readFirstSyncRequest();
  out.navigations = navigations.slice();
  out.storage = localStorage._dump();
} else if (scenario.action === "autoSync") {
  if (scenario.seedSelection) hostForAutoSync.namespace.saveOnboardingSelection(scenario.seedSelection);
  if (scenario.seedRequest) hostForAutoSync.namespace.requestFirstSync(scenario.seedRequest);
  for (const entry of scenario.seedEntries || []) hostForAutoSync.namespace.recordFirstSyncEntry(entry);
  mount(autoSyncMod.namespace.default, { plugin: { id: "project-overview" } });
  await flush();
  out.before = autoSyncSnapshot();
  const click = handlerAfterMarker('class="vk-btn is-primary"');
  out.foundStart = typeof click === "function";
  if (click && scenario.clickStart !== false) {
    await click();
    await flush();
  }
  out.after = autoSyncSnapshot();
} else {
  throw new Error("unknown action: " + scenario.action);
}

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
            str(WIZARD_JS),
            str(AUTO_SYNC_JS),
            str(ENABLE_FLOW_JS),
            str(HOST_JS),
            json.dumps(scenario),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert res.returncode == 0, f"Node 执行失败 (code {res.returncode}):\n{res.stderr}\n{res.stdout}"
    lines = [ln.strip() for ln in res.stdout.strip().splitlines() if ln.strip().startswith("{")]
    assert lines, f"未获取到 Node 输出的 JSON 行:\n{res.stdout}\n{res.stderr}"
    return json.loads(lines[-1])


def _wizard_state(**overrides) -> dict:
    """等价于用户在向导里已勾选 d1/d3、已建好项目并停在完成步。"""
    state = {
        "step": 5,
        "status": "in_progress",
        "vehicle": "F610S",
        "name": "F610S",
        "departments": ["车体科"],
        "selectedDeliverables": ["d1", "d3"],
        "autostart": False,
        "username": "",
        "projectCreated": True,
        "projectId": "proj-9",
        "projectSignature": '["F610S","F610S",["车体科"]]',
        "autostartConfirmed": "off",
    }
    state.update(overrides)
    return state


def _status() -> dict:
    return {
        "phase": {
            "displayName": "F610S",
            "status": "active",
            "startDate": None,
            "endDate": None,
            "updatedAt": "2026-01-01T00:00:00",
        },
        "deliverables": [
            {"id": "d1", "name": "交付物一", "sourceInfo": {"syncCapable": True, "displayName": "来源一"}},
            {"id": "d2", "name": "交付物二", "sourceInfo": {"syncCapable": True, "displayName": "来源二"}},
            {"id": "d3", "name": "交付物三", "sourceInfo": {"syncCapable": True, "displayName": "来源三"}},
            {"id": "d4", "name": "手工交付物", "sourceInfo": {"syncCapable": False, "syncNote": "只能手工维护"}},
        ],
    }


def _projects() -> dict:
    return {
        "projects": [
            {"id": "proj-1", "active": True, "vehicle": "F610S", "departments": ["车体科"]},
        ]
    }


def _sync_success() -> dict:
    return {"exitCode": 0, "result": {"finalState": "success", "outcome": "completed", "errorMessage": ""}}


def _sync_partial() -> dict:
    return {"exitCode": 0, "result": {"finalState": "partial", "outcome": "partial", "errorMessage": ""}}


def _sync_failed(message: str = "候选记录不唯一") -> dict:
    return {"exitCode": 1, "result": {"finalState": "failed", "outcome": "failed", "errorMessage": message}}


def _selection(deliverables: list[str]) -> dict:
    return {
        "deliverables": deliverables,
        "vehicle": "F610S",
        "departments": ["车体科"],
        "projectId": "proj-1",
    }


# ---------------------------------------------------------------------------
# 验收 3：宿主模块只由真实结果推导完成态
# ---------------------------------------------------------------------------


@needs_node
def test_host_module_never_marks_complete_without_real_results() -> None:
    """仅登记请求、仅读取、失败或未开始都不得变成「全部完成」。"""
    data = _run_node_scenario({"action": "hostUnit"})

    # 选择去重、去空、去首尾空白
    assert data["saved"]["deliverables"] == ["d1", "d2"]
    assert data["saved"]["vehicle"] == "F610S"
    assert data["saved"]["departments"] == ["车体科"]
    assert data["saved"]["projectId"] == "proj-1"

    # 刚登记：全部未开始，不能算完成
    assert data["request"]["status"] == "pending"
    assert [entry["id"] for entry in data["request"]["entries"]] == ["d1", "d2"]
    assert [entry["state"] for entry in data["request"]["entries"]] == ["not_started", "not_started"]
    assert data["summaryPending"]["allDone"] is False
    assert data["summaryPending"]["notStarted"] == 2

    # 只读取不改变状态
    assert data["afterRead"]["status"] == "pending"

    # 一项成功 + 一项未开始：部分完成，不是全部完成
    assert data["afterOne"]["status"] == "partial"
    assert data["summaryOne"]["success"] == 1
    assert data["summaryOne"]["notStarted"] == 1
    assert data["summaryOne"]["allDone"] is False

    # 一项成功 + 一项失败：仍然不是全部完成
    assert data["afterTwo"]["status"] == "partial"
    assert data["summaryTwo"]["failed"] == 1
    assert data["summaryTwo"]["allDone"] is False

    # 全部真实成功后才算完成
    assert data["afterAll"]["status"] == "completed"
    assert data["summaryAll"]["allDone"] is True

    # 空选择：不是完成
    assert data["emptyRequest"]["status"] == "empty"
    assert data["emptySummary"]["total"] == 0
    assert data["emptySummary"]["allDone"] is False

    # 非法状态不得被当成成功；请求里没有的交付物不得被追加
    assert data["unknownEntry"]["status"] == "pending"
    assert data["unknownEntry"]["entries"][0]["state"] == "not_started"
    assert data["foreignEntry"]["entries"][0]["state"] == "not_started"
    assert data["foreignEntry"]["status"] == "pending"


# ---------------------------------------------------------------------------
# 验收 4：向导经宿主模块交接，不跨插件 import
# ---------------------------------------------------------------------------


@needs_node
def test_wizard_hands_selected_deliverables_and_first_sync_request_to_host() -> None:
    """点「开启自动同步」：勾选的交付物写入宿主模块，首次同步请求全部为未开始。"""
    data = _run_node_scenario(
        {
            "action": "wizardFinish",
            "button": "start",
            "initialStorage": {"vse.wizardState": _wizard_state()},
        }
    )
    assert data["found"] is True
    assert data["selection"]["deliverables"] == ["d1", "d3"]
    assert data["selection"]["vehicle"] == "F610S"
    assert data["selection"]["departments"] == ["车体科"]
    assert data["selection"]["projectId"] == "proj-9"

    request = data["request"]
    assert request["status"] == "pending"
    assert [entry["id"] for entry in request["entries"]] == ["d1", "d3"]
    assert all(entry["state"] == "not_started" for entry in request["entries"])

    assert data["navigations"] == ["#p/project-overview/auto-sync"]
    assert data["wizardState"]["status"] == "completed"
    # 完成步如实说明：真实任务逐项执行，未开始或失败不算完成
    assert "首次同步由真实任务逐项执行" in data["beforeText"]
    assert "未开始或失败的项不会算作完成" in data["beforeText"]


@needs_node
def test_wizard_start_using_saves_scope_without_first_sync_request() -> None:
    """点「开始使用」：只保存勾选范围，不登记首次同步请求、不跳页。"""
    data = _run_node_scenario(
        {
            "action": "wizardFinish",
            "button": "done",
            "initialStorage": {"vse.wizardState": _wizard_state()},
        }
    )
    assert data["found"] is True
    assert data["selection"]["deliverables"] == ["d1", "d3"]
    assert data["request"] is None
    assert data["navigations"] == []
    assert data["wizardState"]["status"] == "completed"


@needs_node
def test_wizard_start_using_clears_stale_first_sync_request_scope() -> None:
    """重新走向导并改了勾选范围：旧请求的范围不再代表这次选择，必须清掉。"""
    data = _run_node_scenario(
        {
            "action": "wizardFinish",
            "button": "done",
            "initialStorage": {"vse.wizardState": _wizard_state()},
            "seedRequest": _selection(["d1", "d2"]),
        }
    )
    assert data["selection"]["deliverables"] == ["d1", "d3"]
    assert data["request"] is None


@needs_node
def test_wizard_start_using_keeps_same_scope_first_sync_request() -> None:
    """范围没变时不清旧请求，已有的首次同步进度仍然可查。"""
    data = _run_node_scenario(
        {
            "action": "wizardFinish",
            "button": "done",
            "initialStorage": {"vse.wizardState": _wizard_state()},
            "seedRequest": _selection(["d1", "d3"]),
        }
    )
    assert data["request"]["status"] == "pending"
    assert data["request"]["deliverables"] == ["d1", "d3"]


# ---------------------------------------------------------------------------
# 验收 1 + 2：selectedDeliverables 约束范围；真实任务触发并逐项展示
# ---------------------------------------------------------------------------


@needs_node
def test_selected_deliverables_constrain_first_sync_scope() -> None:
    """勾选 d1/d2：只对 d1/d2 调 sync-now，d3 不进入范围；结果逐项展示。"""
    data = _run_node_scenario(
        {
            "action": "autoSync",
            "status": _status(),
            "projects": _projects(),
            "seedSelection": _selection(["d1", "d2"]),
            "seedRequest": _selection(["d1", "d2"]),
            "syncResults": {"d1": _sync_success(), "d2": _sync_failed()},
        }
    )
    before = data["before"]
    after = data["after"]

    # 仅打开页面：请求仍是未开始，没发任何 sync-now
    assert before["request"]["status"] == "pending"
    assert [entry["state"] for entry in before["request"]["entries"]] == ["not_started", "not_started"]
    assert before["syncCalls"] == []
    assert "首次同步进度" in before["text"]
    assert "未开始或失败的项不会算作完成" in before["text"]
    assert "已全部完成" not in before["text"]
    assert "不在向导选择范围" in before["text"]

    # 真实任务只处理勾选项
    assert after["syncCalls"] == ["d1", "d2"]
    assert "d3" not in after["syncCalls"]
    entries = {entry["id"]: entry["state"] for entry in after["request"]["entries"]}
    assert entries == {"d1": "success", "d2": "failed"}
    assert after["request"]["status"] == "partial"

    # 结果逐项展示，且失败不被写成完成
    assert "首次同步成功" in after["text"]
    assert "首次同步失败：候选记录不唯一" in after["text"]
    assert "成功 1 项，未成功 1 项" in after["text"]
    assert "1 项首次同步没有成功" in after["text"]
    assert "已全部完成" not in after["text"]
    assert "已全部开启" not in after["text"]
    assert "已开启（首次同步未全部成功）" in after["text"]

    # 走的是现有 sync-now 接口（POST），没有新增后端路由
    posts = [call for call in after["apiCalls"] if call["method"] == "POST" and call["path"].endswith("/sync-now")]
    assert [call["path"] for call in posts] == [
        "/api/project-status/deliverables/d1/sync-now",
        "/api/project-status/deliverables/d2/sync-now",
    ]


@needs_node
def test_all_success_marks_completed_only_after_real_results() -> None:
    """勾选 d1：打开页面时未开始；真实 sync-now 全部成功后才显示全部完成。"""
    data = _run_node_scenario(
        {
            "action": "autoSync",
            "status": _status(),
            "projects": _projects(),
            "seedSelection": _selection(["d1"]),
            "seedRequest": _selection(["d1"]),
            "syncResults": {"d1": _sync_success()},
        }
    )
    assert data["before"]["request"]["status"] == "pending"
    assert data["before"]["syncCalls"] == []
    assert "已全部完成" not in data["before"]["text"]

    assert data["after"]["syncCalls"] == ["d1"]
    assert data["after"]["request"]["status"] == "completed"
    assert data["after"]["request"]["entries"][0]["state"] == "success"
    assert "首次同步已全部完成" in data["after"]["text"]


@needs_node
def test_reloaded_page_keeps_failed_first_sync_visible() -> None:
    """刷新后策略已是「已开启」，但首次同步失败仍要按失败展示，不能被「已开启」盖掉。"""
    data = _run_node_scenario(
        {
            "action": "autoSync",
            "status": _status(),
            "projects": _projects(),
            "policies": {"d1": {"enabled": True}},
            "seedSelection": _selection(["d1"]),
            "seedRequest": _selection(["d1"]),
            "seedEntries": [
                {"id": "d1", "name": "交付物一", "state": "failed", "text": "首次同步失败：候选记录不唯一"},
            ],
            "clickStart": False,
        }
    )
    assert data["before"]["request"]["status"] == "failed"
    assert "首次同步失败：候选记录不唯一" in data["before"]["text"]
    assert "未开始或失败的项不会算作完成" in data["before"]["text"]
    assert "已全部完成" not in data["before"]["text"]


@needs_node
def test_selection_without_request_creates_request_only_when_task_starts() -> None:
    """只保存了选择（点「开始使用」）：打开页面不登记完成，点开始才建请求并记录结果。"""
    data = _run_node_scenario(
        {
            "action": "autoSync",
            "status": _status(),
            "projects": _projects(),
            "seedSelection": _selection(["d1"]),
            "syncResults": {"d1": _sync_success()},
        }
    )
    assert data["before"]["request"] is None
    assert data["before"]["syncCalls"] == []
    assert "本次只处理向导里勾选的 1 项交付物" in data["before"]["text"]

    assert data["after"]["syncCalls"] == ["d1"]
    assert data["after"]["request"]["status"] == "completed"
    assert data["after"]["request"]["deliverables"] == ["d1"]


@needs_node
def test_empty_wizard_selection_syncs_nothing() -> None:
    """向导一个都没勾选：不启用、不调 sync-now，也不伪造完成。"""
    data = _run_node_scenario(
        {
            "action": "autoSync",
            "status": _status(),
            "projects": _projects(),
            "seedSelection": _selection([]),
            "seedRequest": _selection([]),
            "syncResults": {},
            "clickStart": False,
        }
    )
    assert data["before"]["request"]["status"] == "empty"
    assert data["before"]["syncCalls"] == []
    assert "没有勾选任何交付物" in data["before"]["text"]
    assert "没有可同步的交付物" in data["before"]["text"]
    assert data["after"]["syncCalls"] == []


@needs_node
def test_without_wizard_selection_all_sync_capable_deliverables_are_targets() -> None:
    """没有向导选择时保持原行为：处理全部可同步且未开启的交付物。"""
    data = _run_node_scenario(
        {
            "action": "autoSync",
            "status": _status(),
            "projects": _projects(),
            "syncResults": {"d1": _sync_success(), "d2": _sync_success(), "d3": _sync_success()},
        }
    )
    assert data["before"]["selection"] is None
    assert data["before"]["request"] is None
    assert data["before"]["syncCalls"] == []
    assert data["after"]["syncCalls"] == ["d1", "d2", "d3"]
    assert data["after"]["request"] is None
    assert "全部开启了（3 项）" in data["after"]["text"]


def test_wizard_and_auto_sync_use_host_module_not_cross_plugin_imports() -> None:
    """架构门禁：两侧都经宿主模块交接，且不 import 另一个插件。"""
    wizard = WIZARD_JS.read_text(encoding="utf-8")
    auto_sync = AUTO_SYNC_JS.read_text(encoding="utf-8")
    for source in (wizard, auto_sync):
        assert "/static/plugins/" not in source
    assert "/static/host/onboarding-selection.js" in wizard
    assert "/static/host/onboarding-selection.js" in auto_sync
    assert HOST_JS.is_file()


def test_host_module_is_served_as_javascript(tmp_path, monkeypatch) -> None:
    """宿主模块必须按 ES Module 的 JavaScript MIME 提供，浏览器才能动态/静态加载。"""
    import web.app as web_app

    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "first-sync.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(plugin_dirs=[tmp_path / "plugins"])
    app.config.update(TESTING=True)
    response = app.test_client().get("/static/host/onboarding-selection.js")
    assert response.status_code == 200
    assert response.mimetype == "text/javascript"


@needs_node
def test_not_applicable_and_interrupted_entries_do_not_block_or_fake_completion() -> None:
    """主控补充：不参与同步的选中项不得永远「未开始」；中断的「进行中」不得残留。"""
    data = _run_node_scenario({"action": "hostLifecycle"})

    # 不适用项不进入完成分母：其余项真实成功后即完成
    assert [e["state"] for e in data["naRequest"]["entries"]] == ["not_started", "not_started", "not_applicable"]
    assert data["naSummaryBefore"]["total"] == 2
    assert data["naSummaryBefore"]["notApplicable"] == 1
    assert data["naSummaryBefore"]["allDone"] is False
    assert data["naSummaryDone"]["allDone"] is True
    assert data["naStatusDone"] == "completed"
    # 真实结果不会被「不适用」覆盖
    assert data["naNoOverride"] == "success"

    # 运行结束仍在「进行中」的项改记失败，已成功的不变
    states = {e["id"]: e["state"] for e in data["failRunning"]["entries"]}
    assert states == {"e1": "success", "e2": "failed"}
    assert data["failRunning"]["status"] == "partial"

    # 重新打开页面：遗留「进行中」恢复为未开始，不显示为仍在执行
    assert data["recovered"]["entries"][0]["state"] == "not_started"
    assert data["recovered"]["status"] == "pending"

    # 选中项全部不适用：没有待做的首次同步，视为完成
    assert data["allNaSummary"]["allDone"] is True
    assert data["allNa"]["status"] == "completed"
