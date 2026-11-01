# -*- coding: utf-8 -*-
"""向导失败处理与跨重启项目恢复（DSH-V2-12；契约 C3 向导条款）。

本文件用 Node 真实执行 `plugins/workbench/static/wizard.js` 的模块逻辑：
1. 直接调用导出的决策函数 `createOrReuseProject` / `submitAutostartChoice`；
2. 用最小 hook 运行时挂载真实的 `Wizard` 组件，取出表单 `onSubmit` 与主按钮
   `onClick` 并真的调用它们，再用假 `api` 观察请求与持久化结果。

覆盖：
- 401 / 403 / 500 / 网络异常 / 非 JSON 响应都不得被当成「项目创建成功」，
  必须停在当前步、显示中文原因、不标记已建项目；
- 只有 HTTP 409 + 错误码 NotManaged 才走单项目分支，其它 409 与其它错误码按失败处理；
- 创建成功后持久化项目 ID 与创建签名，刷新/重启后复用，重复提交不再建项目；
- 开机自启：成功才显示已开启，失败如实显示，未勾选绝不调用开启。
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

const [, WIZARD_JS_PATH, SCENARIO_JSON] = process.argv;
const scenario = JSON.parse(SCENARIO_JSON);

// ---- 最小 localStorage 桩 -------------------------------------------------
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

// ---- 假 api：与 web/static/host/api.js 同形状的 ApiError ----------------
const apiCalls = [];
const navigations = [];
const queue = (scenario.apiQueue || []).slice();

function apiErrorFrom(spec) {
  const err = new Error(spec.message || "请求失败");
  err.name = "ApiError";
  err.status = spec.status === undefined || spec.status === null ? 0 : spec.status;
  err.type = spec.type || (err.status ? "http" : "network");
  err.code = spec.code === undefined ? null : spec.code;
  return err;
}

async function fakeApi(url, opts) {
  const options = opts || {};
  apiCalls.push({
    url: String(url),
    method: options.method || "GET",
    body: options.body === undefined ? null : options.body,
  });
  if (!queue.length) throw new Error("未预置的接口调用: " + url);
  const next = queue.shift();
  if (next.url && String(url).indexOf(next.url) === -1) {
    throw new Error("接口调用顺序不符: 期望 " + next.url + " 实际 " + url);
  }
  if (next.network) {
    throw apiErrorFrom({ status: 0, type: "network", message: "无法连接本地服务，请确认 VSE Toolbox 仍在运行" });
  }
  if (next.notJson) {
    throw apiErrorFrom({ status: next.status || 200, type: "http", message: "请求失败（HTTP " + (next.status || 200) + "）" });
  }
  if (next.ok === false) throw apiErrorFrom(next);
  return next.data;
}

// ---- 最小 hook 运行时（让真实组件可被挂载与重渲染）----------------------
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

// 交付物加载副作用不在本文件断言范围，但必须占位以保持 hook 顺序稳定
function useEffect() { hooks.cursor++; }
function useCallback(fn) { return fn; }

function htmlStub(strings, ...values) {
  return { __template: true, strings: Array.from(strings), values };
}

// ---- 载入被测算模块 -------------------------------------------------------
const context = vm.createContext({
  console: { log() {}, warn() {}, error() {}, info() {} },
  setTimeout, clearTimeout,
  Promise, JSON, Math, Date, Object, Array, String, Number, Boolean, RegExp, Error,
  encodeURIComponent, decodeURIComponent,
  window: { localStorage, location: { hash: "", reload() {} } },
  localStorage,
});

const code = readFileSync(WIZARD_JS_PATH, "utf8");
const mod = new vm.SourceTextModule(code, {
  context,
  initializeImportMeta(meta) {
    meta.url = pathToFileURL(WIZARD_JS_PATH).href;
  },
});

await mod.link(async (specifier) => {
  if (specifier.includes("preact-htm")) {
    return new vm.SyntheticModule(
      ["html", "useState", "useEffect", "useCallback", "useRef"],
      function () {
        this.setExport("html", htmlStub);
        this.setExport("useState", useState);
        this.setExport("useEffect", useEffect);
        this.setExport("useCallback", useCallback);
        this.setExport("useRef", useRef);
      },
      { context }
    );
  }
  if (specifier.includes("session.js")) {
    return new vm.SyntheticModule(
      ["submitDomainLogin", "updateSessionBadges"],
      function () {
        this.setExport("submitDomainLogin", async () => ({ kind: "success", text: "已登录", sessions: {} }));
        this.setExport("updateSessionBadges", () => {});
      },
      { context }
    );
  }
  if (specifier.includes("common.js")) {
    return new vm.SyntheticModule(
      ["api", "html", "go", "activeDeliverables"],
      function () {
        this.setExport("api", fakeApi);
        this.setExport("html", htmlStub);
        this.setExport("go", (hash) => { navigations.push(hash); });
        this.setExport("activeDeliverables", (list) => (list || []).filter((d) => !d.retired));
      },
      { context }
    );
  }
  throw new Error("unexpected specifier: " + specifier);
});

await mod.evaluate();
const exports = mod.namespace;

// ---- vnode 树工具 --------------------------------------------------------
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

function formSubmitHandler() {
  const found = findBy((text, props) => typeof props.onSubmit === "function" && text.indexOf("<form") !== -1);
  return found.length ? found[0].props.onSubmit : null;
}

function primaryClickHandler() {
  const found = findBy((text, props) => typeof props.onClick === "function" && text.indexOf("is-primary") !== -1);
  return found.length ? found[0].props.onClick : null;
}

function render() {
  hooks.cursor = 0;
  hooks.dirty = false;
  tree = exports.Wizard(currentProps);
}

function mount(extra) {
  hooks.slots = [];
  currentProps = Object.assign({ projectName: "测试车型项目", onClose: () => {} }, extra || {});
  render();
}

async function flush() {
  for (let i = 0; i < 20; i++) {
    if (!hooks.dirty) return;
    await new Promise((resolve) => setTimeout(resolve, 0));
    render();
  }
}

function snapshot() {
  return {
    text: textOf(tree),
    wizardState: exports.loadWizardState(),
    apiCalls: apiCalls.slice(),
    navigations: navigations.slice(),
    storage: localStorage._dump(),
  };
}

// ---- 场景 ----------------------------------------------------------------
const out = { action: scenario.action };

async function runCreateFailures() {
  const results = [];
  for (const item of scenario.cases || []) {
    const calls = [];
    const outcome = await exports.createOrReuseProject({
      create: async (body) => {
        calls.push(body);
        if (item.error) {
          const err = new Error(item.error.message || "请求失败");
          err.name = "ApiError";
          err.status = item.error.status === undefined || item.error.status === null ? 0 : item.error.status;
          err.type = item.error.type || (err.status ? "http" : "network");
          err.code = item.error.code === undefined ? null : item.error.code;
          throw err;
        }
        return item.data;
      },
      vehicle: item.vehicle,
      name: item.name,
      departments: item.departments,
      saved: item.saved || {},
    });
    results.push({ label: item.label, outcome, calls });
  }
  out.results = results;
}

async function runComponentProject() {
  mount(scenario.mountProps || {});
  out.before = snapshot();
  const submit = formSubmitHandler();
  out.foundSubmit = typeof submit === "function";
  if (!submit) return;

  if (scenario.doubleSubmit) {
    const first = submit({ preventDefault() {} });
    const second = submit({ preventDefault() {} });
    await Promise.all([first, second]);
  } else {
    await submit({ preventDefault() {} });
  }
  await flush();
  out.after = snapshot();
}

async function runComponentAutostart() {
  mount(scenario.mountProps || {});
  out.before = snapshot();
  const click = primaryClickHandler();
  out.foundPrimary = typeof click === "function";
  if (!click) return;
  await click();
  await flush();
  out.after = snapshot();

  if (scenario.thenSkip) {
    const skip = findBy((text, props) => typeof props.onClick === "function" && text.indexOf("先跳过自启") !== -1);
    out.foundSkip = skip.length > 0;
    if (skip.length) {
      await skip[0].props.onClick();
      await flush();
    }
    out.afterSkip = snapshot();
  }
}

if (scenario.action === "createFailures") {
  await runCreateFailures();
} else if (scenario.action === "componentProject") {
  await runComponentProject();
} else if (scenario.action === "componentAutostart") {
  await runComponentAutostart();
} else {
  throw new Error("unknown action: " + scenario.action);
}

console.log(JSON.stringify(out));
"""


def _run_node_scenario(scenario: dict) -> dict:
    node = shutil.which("node")
    assert node is not None, "未找到 Node.js 命令"
    res = subprocess.run(
        [node, "--experimental-vm-modules", "--input-type=module", "-e", _RUNNER_JS, str(WIZARD_JS), json.dumps(scenario)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert res.returncode == 0, f"Node 执行失败 (code {res.returncode}):\n{res.stderr}\n{res.stdout}"
    lines = [ln.strip() for ln in res.stdout.strip().splitlines() if ln.strip().startswith("{")]
    assert lines, f"未获取到 Node 输出的 JSON 行:\n{res.stdout}"
    return json.loads(lines[-1])


def _wizard_state(initial: dict | None = None) -> dict:
    """构造一份可恢复的向导状态（等价于用户已填好第 2 步车型）。"""
    state = {
        "step": 2,
        "status": "in_progress",
        "vehicle": "F610S",
        "name": "F610S",
        "departments": ["车体科", "车身科"],
        "selectedDeliverables": [],
        "autostart": False,
        "username": "",
    }
    if initial:
        state.update(initial)
    return state


_INTERNAL_LEAK_MARKERS = [
    "IOError", "Exception", "Traceback", "errno", "HTTP", "http", "ApiError", "TypeError", "C:\\", "/api/",
]


def _assert_user_facing_chinese(message: str) -> None:
    assert isinstance(message, str) and message.strip(), "失败时必须给出用户可见的中文说明"
    assert re.search(r"[\u4e00-\u9fff]", message), f"说明必须是中文：{message}"
    for marker in _INTERNAL_LEAK_MARKERS:
        assert marker not in message, f"说明暴露了内部细节「{marker}」：{message}"


# ---------------------------------------------------------------------------
# 验收 1 + 4：失败不得被当成成功；只有 409 NotManaged 走单项目分支
# ---------------------------------------------------------------------------


@needs_node
def test_create_failures_are_not_treated_as_success() -> None:
    """401/403/500/网络异常/非 JSON/其它 409 一律失败：停在新建项目步，不标记已建项目。"""
    cases = [
        {"label": "401", "error": {"status": 401, "type": "AuthenticationError", "message": "未认证"}},
        {"label": "403", "error": {"status": 403, "type": "LocalAccessRequired", "message": "仅本机"}},
        {"label": "500", "error": {"status": 500, "type": "IOError", "message": "保存项目失败：磁盘错误"}},
        {"label": "network", "error": {"status": 0, "type": "network", "message": "无法连接本地服务"}},
        {"label": "not-json", "error": {"status": 200, "type": "http", "message": "请求失败（HTTP 200）"}},
        {"label": "409-revision-conflict", "error": {"status": 409, "type": "RevisionConflict", "message": "冲突"}},
        {"label": "409-other-code", "error": {"status": 409, "code": "CurrentProjectArchived", "type": "http"}},
        {"label": "409-no-code", "error": {"status": 409, "type": "http"}},
        {"label": "422", "error": {"status": 422, "type": "ValidationError", "message": "项目名称不能为空"}},
        {"label": "500-with-not-managed-code", "error": {"status": 500, "code": "NotManaged", "type": "http"}},
    ]
    data = _run_node_scenario(
        {
            "action": "createFailures",
            "cases": [
                dict(case, vehicle="F610S", name="F610S", departments=["车体科"])
                for case in cases
            ],
        }
    )
    results = {item["label"]: item for item in data["results"]}
    assert set(results) == {case["label"] for case in cases}

    for case in cases:
        outcome = results[case["label"]]["outcome"]
        assert outcome["ok"] is False, f"{case['label']} 不得被当成项目创建成功"
        assert outcome["step"] == 2, f"{case['label']} 必须停在新建项目步"
        assert outcome["projectId"] == "", f"{case['label']} 不得产出项目 ID"
        _assert_user_facing_chinese(outcome["message"])
        # 真的发了创建请求（不是静默跳过）
        assert len(results[case["label"]]["calls"]) == 1


@needs_node
def test_only_explicit_409_not_managed_uses_single_project_branch() -> None:
    """409 + NotManaged（host 放在 error.type，显式时放 error.code）才走单项目分支。"""
    cases = [
        {"label": "not-managed-as-type", "error": {"status": 409, "type": "NotManaged", "message": "单项目"}},
        {"label": "not-managed-as-code", "error": {"status": 409, "code": "NotManaged", "type": "http"}},
        {"label": "revision-conflict", "error": {"status": 409, "type": "RevisionConflict"}},
        {"label": "not-managed-wrong-status", "error": {"status": 400, "code": "NotManaged", "type": "http"}},
        {"label": "not-managed-500", "error": {"status": 500, "type": "NotManaged"}},
        {"label": "lowercase-not-managed", "error": {"status": 409, "type": "notmanaged"}},
    ]
    data = _run_node_scenario(
        {
            "action": "createFailures",
            "cases": [dict(case, vehicle="F610S", name="F610S", departments=[]) for case in cases],
        }
    )
    results = {item["label"]: item["outcome"] for item in data["results"]}

    for label in ("not-managed-as-type", "not-managed-as-code"):
        assert results[label]["ok"] is True
        assert results[label]["singleProject"] is True
        assert results[label]["step"] == 3
        assert results[label]["projectId"] == "main"

    for label in ("revision-conflict", "not-managed-wrong-status", "not-managed-500", "lowercase-not-managed"):
        assert results[label]["ok"] is False, f"{label} 不得走单项目分支"
        assert results[label]["step"] == 2


# ---------------------------------------------------------------------------
# 验收 2：保存项目 ID 与恢复步，重复提交不再建项目
# ---------------------------------------------------------------------------


@needs_node
def test_component_persists_project_id_and_step_after_success() -> None:
    """创建成功后把项目 ID、创建签名与步进写入 localStorage。"""
    data = _run_node_scenario(
        {
            "action": "componentProject",
            "initialStorage": {"vse.wizardState": _wizard_state()},
            "apiQueue": [{"url": "/api/p/workbench/projects", "ok": True, "data": {"project": {"id": "proj-42", "name": "F610S"}}}],
        }
    )
    assert data["foundSubmit"] is True
    after = data["after"]
    state = after["wizardState"]
    assert state["projectCreated"] is True
    assert state["projectId"] == "proj-42"
    assert state["projectSignature"], "必须保存创建签名以判断能否复用"
    assert state["step"] == 3, "创建成功后应推进到选择交付物步"
    assert len(after["apiCalls"]) == 1
    assert after["apiCalls"][0]["method"] == "POST"
    assert after["apiCalls"][0]["body"]["vehicle"] == "F610S"


@needs_node
def test_restored_step_reuses_project_without_creating_another() -> None:
    """刷新/重启回到新建项目步后再次提交：复用已建项目，不再发创建请求。"""
    # 第一次：正常创建，拿到真实的持久化状态
    first = _run_node_scenario(
        {
            "action": "componentProject",
            "initialStorage": {"vse.wizardState": _wizard_state()},
            "apiQueue": [{"url": "/api/p/workbench/projects", "ok": True, "data": {"project": {"id": "proj-42"}}}],
        }
    )
    persisted = first["after"]["wizardState"]
    assert persisted["projectCreated"] is True and persisted["projectId"] == "proj-42"

    # 第二次：全新进程，storage 里只剩「已建项目 + 回到第 2 步」的状态
    restored = dict(persisted, step=2)
    second = _run_node_scenario(
        {
            "action": "componentProject",
            "initialStorage": {"vse.wizardState": restored},
            # 若错误地又建一次项目，这里会真的被消费
            "apiQueue": [{"url": "/api/p/workbench/projects", "ok": True, "data": {"project": {"id": "proj-duplicate"}}}],
        }
    )
    after = second["after"]
    assert second["foundSubmit"] is True
    assert after["apiCalls"] == [], f"恢复后重复建了项目：{after['apiCalls']}"
    assert after["wizardState"]["step"] == 3, "复用后应推进到选择交付物步"
    assert after["wizardState"]["projectId"] == "proj-42", "必须复用已建项目 ID"
    assert "新建或配置项目" not in after["text"]


@needs_node
def test_double_submit_creates_only_one_project() -> None:
    """重复点击「下一步」只发一次创建请求。"""
    data = _run_node_scenario(
        {
            "action": "componentProject",
            "initialStorage": {"vse.wizardState": _wizard_state()},
            "apiQueue": [{"url": "/api/p/workbench/projects", "ok": True, "data": {"project": {"id": "proj-7"}}}],
            "doubleSubmit": True,
        }
    )
    after = data["after"]
    assert len(after["apiCalls"]) == 1, f"重复点击建了多个项目：{after['apiCalls']}"
    assert after["wizardState"]["projectId"] == "proj-7"
    assert after["wizardState"]["step"] == 3


@needs_node
def test_component_stops_on_401_and_does_not_mark_project_created() -> None:
    """401 时组件停在新建项目步、显示中文错误、不标记已建项目。"""
    data = _run_node_scenario(
        {
            "action": "componentProject",
            "initialStorage": {"vse.wizardState": _wizard_state()},
            "apiQueue": [{"url": "/api/p/workbench/projects", "ok": False, "status": 401, "type": "AuthenticationError", "message": "session expired"}],
        }
    )
    after = data["after"]
    text = after["text"]
    assert "新建或配置项目" in text, "必须停在新建项目步"
    assert "登录状态已失效" in text, "必须显示真实的中文原因"
    assert "选择要跟踪的交付物" not in text, "401 不得推进到下一步"
    assert after["wizardState"]["projectCreated"] is False
    assert after["wizardState"]["projectId"] == ""
    assert after["wizardState"]["step"] == 2
    assert after["navigations"] == []


# ---------------------------------------------------------------------------
# 验收 3：开机自启如实显示，未勾选不得调用开启
# ---------------------------------------------------------------------------


@needs_node
def test_autostart_success_reports_enabled_only_after_backend_confirms() -> None:
    """勾选且后端返回 enabled=true 才显示已开启。"""
    data = _run_node_scenario(
        {
            "action": "componentAutostart",
            "initialStorage": {"vse.wizardState": _wizard_state({"step": 4, "autostart": True})},
            "apiQueue": [{"url": "/api/p/settings/autostart", "ok": True, "data": {"enabled": True}}],
        }
    )
    after = data["after"]
    assert data["foundPrimary"] is True
    assert after["apiCalls"] == [{"url": "/api/p/settings/autostart", "method": "POST", "body": {"enabled": True}}]
    assert after["wizardState"]["autostartConfirmed"] == "on"
    assert after["wizardState"]["step"] == 5
    assert "配置完成" in after["text"]
    assert "开机自启：已开启" in after["text"]


@needs_node
def test_autostart_failure_is_reported_and_not_shown_as_enabled() -> None:
    """自启失败如实显示失败、停在自启步；显式跳过后完成页写明未能开启。"""
    data = _run_node_scenario(
        {
            "action": "componentAutostart",
            "initialStorage": {"vse.wizardState": _wizard_state({"step": 4, "autostart": True})},
            "apiQueue": [{"url": "/api/p/settings/autostart", "ok": False, "status": 500, "type": "RegistryError", "message": "修改开机启动项失败"}],
            "thenSkip": True,
        }
    )
    after = data["after"]
    assert "开机自启设置" in after["text"], "失败时必须停在自启步"
    assert "本地服务暂时不可用，开机自启未生效" in after["text"]
    assert after["wizardState"]["autostartConfirmed"] == "failed"
    assert after["wizardState"]["step"] == 4
    assert "配置完成" not in after["text"]

    assert data["foundSkip"] is True
    after_skip = data["afterSkip"]
    assert after_skip["wizardState"]["step"] == 5
    assert "开机自启：未能开启（可稍后在设置里开启）" in after_skip["text"]
    assert "开机自启：已开启" not in after_skip["text"]


@needs_node
def test_autostart_backend_not_enabled_counts_as_failure() -> None:
    """后端返回成功但 enabled 不为 true 时不得显示已开启。"""
    data = _run_node_scenario(
        {
            "action": "componentAutostart",
            "initialStorage": {"vse.wizardState": _wizard_state({"step": 4, "autostart": True})},
            "apiQueue": [{"url": "/api/p/settings/autostart", "ok": True, "data": {"enabled": False}}],
        }
    )
    after = data["after"]
    assert after["wizardState"]["autostartConfirmed"] == "failed"
    assert after["wizardState"]["step"] == 4
    assert "开机自启没有生效" in after["text"]


@needs_node
def test_autostart_unchecked_never_calls_enable() -> None:
    """未勾选时绝不调用开启；只读回真实状态，并按真实状态显示。"""
    data = _run_node_scenario(
        {
            "action": "componentAutostart",
            "initialStorage": {"vse.wizardState": _wizard_state({"step": 4, "autostart": False})},
            "apiQueue": [{"url": "/api/p/settings/autostart", "ok": True, "data": {"enabled": False}}],
        }
    )
    after = data["after"]
    methods = [call["method"] for call in after["apiCalls"]]
    assert "POST" not in methods, f"未勾选不得调用开启：{after['apiCalls']}"
    assert methods == ["GET"]
    assert after["wizardState"]["autostartConfirmed"] == "off"
    assert after["wizardState"]["step"] == 5
    assert "开机自启：未开启" in after["text"]


@needs_node
def test_autostart_unchecked_without_readable_state_is_unknown() -> None:
    """未勾选且读不到真实状态时不得声称已开启或已关闭。"""
    data = _run_node_scenario(
        {
            "action": "componentAutostart",
            "initialStorage": {"vse.wizardState": _wizard_state({"step": 4, "autostart": False})},
            "apiQueue": [{"url": "/api/p/settings/autostart", "network": True}],
        }
    )
    after = data["after"]
    assert [call["method"] for call in after["apiCalls"]] == ["GET"]
    assert after["wizardState"]["autostartConfirmed"] == "unknown"
    assert "开机自启：未确认" in after["text"]
    assert "开机自启：已开启" not in after["text"]


# ---------------------------------------------------------------------------
# 回归：既有导出与默认值不变
# ---------------------------------------------------------------------------


@needs_node
def test_wizard_exports_stay_backwards_compatible() -> None:
    """新增可测函数不得破坏既有导出（既有调用方零修改）。"""
    content = WIZARD_JS.read_text(encoding="utf-8")
    for name in (
        "export function Wizard",
        "export function wizardDismissed",
        "export function sanitizeWizardState",
        "export function loadWizardState",
        "export function saveWizardState",
        "export function markWizardSkipped",
        "export function markWizardCompleted",
        "export function resetWizardState",
        "export async function createOrReuseProject",
        "export async function submitAutostartChoice",
        "export function isSingleProjectEnvironment",
    ):
        assert name in content, f"缺少导出：{name}"
