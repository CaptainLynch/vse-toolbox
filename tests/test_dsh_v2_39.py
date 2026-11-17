# -*- coding: utf-8 -*-
"""DSH-V2-39：可配置车型列表 + 科室回写交互。

后端（真实 create_app + 测试客户端）：

- ``GET /api/p/workbench/vehicle-models`` 初始 ``configured`` 为空（不预置、不编造任何
  车型代码），``inUse`` 来自真实项目（含归档）的车型去重升序，响应 no-store；
- ``PUT`` 同一路由整表替换，逐项校验（空 / 超长 / 非文字 / 去重 / 超 200 项），非法请求
  400 ValidationError 且不改动已保存的清单；写路由经 ``ctx.local_guard()``；
- 清单变化绝不修改任何项目已保存的车型。

前端（Node 真实执行 ES Module，不做源文本断言）：

- ``projects.js``：``vehicleModelOptions`` / ``parseVehicleCodes`` 纯函数；新建与编辑
  对话框的车型输入始终可手填，datalist 候选 = configured ∪ inUse ∪ 当前值，候选加载
  失败只显示一行提示、不阻断手填；「车型清单」小节保存失败如实显示后端 message。
- ``auto-sync.js``：未勾选不发 PATCH；勾选且本次至少成功开启一项才带 expectedRevision
  回写；失败（含 409 修订冲突）在结果区显示「科室没有写回项目默认值：<原因>」，且不
  影响已开启项的结果展示；一键开启仍只处理未开启项。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import web.app as web_app
from vse_boot import projects
from vse_boot.layout import InstallLayout

REPO = Path(__file__).resolve().parent.parent
PROJECTS_JS = REPO / "plugins" / "workbench" / "static" / "projects.js"
AUTO_SYNC_JS = REPO / "plugins" / "project_overview" / "static" / "auto-sync.js"
VEHICLE_MODELS_URL = "/api/p/workbench/vehicle-models"


# ---------------------------------------------------------------------------
# 后端夹具：真实 create_app + 测试客户端（受启动器管理的安装布局）
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "data" / "host.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    monkeypatch.delenv("VSE_INSTALL_ROOT", raising=False)
    root = tmp_path / "VSE-Toolbox"
    InstallLayout(root).ensure()
    monkeypatch.setenv("VSE_INSTALL_ROOT", str(root))
    app = web_app.create_app(plugin_dirs=[REPO / "plugins"], plugin_only=["workbench"])
    app.config.update(TESTING=True)
    return app.test_client(), InstallLayout(root)


def _get_models(c):  # type: ignore[no-untyped-def]
    res = c.get(VEHICLE_MODELS_URL)
    assert res.status_code == 200, res.get_data(as_text=True)
    return res, res.get_json()["data"]


# ---------------------------------------------------------------------------
# 验收 1：车型清单可读写，初始为空、不编造代码，inUse 来自真实项目
# ---------------------------------------------------------------------------


def test_get_starts_empty_and_derives_in_use_from_real_projects(client) -> None:  # type: ignore[no-untyped-def]
    c, _layout = client
    res, data = _get_models(c)
    # 不预置、不编造任何车型代码
    assert data["configured"] == []
    # inUse 与既有项目列表同一份查询：去重升序
    listed = c.get("/api/p/workbench/projects").get_json()["data"]["projects"]
    expected = sorted({str(p["vehicle"]).strip() for p in listed if str(p.get("vehicle") or "").strip()})
    assert data["inUse"] == expected
    assert res.headers["Cache-Control"] == "no-store"


def test_in_use_includes_archived_projects_and_dedupes(client) -> None:  # type: ignore[no-untyped-def]
    c, _layout = client
    c.post("/api/p/workbench/projects", json={"name": "甲", "vehicle": "F720"})
    c.post("/api/p/workbench/projects", json={"name": "乙", "vehicle": "F610S"})
    archived = c.post("/api/p/workbench/projects/p2/archive")
    assert archived.status_code == 200, archived.get_data(as_text=True)

    _res, data = _get_models(c)
    assert data["configured"] == []
    # 归档项目（p2/F720）仍然算「在用」，且升序去重
    assert data["inUse"] == ["F610S", "F720"]


def test_put_replaces_configured_list_and_never_touches_project_vehicles(client) -> None:  # type: ignore[no-untyped-def]
    c, layout = client
    c.post("/api/p/workbench/projects", json={"name": "甲", "vehicle": "F720"})
    assert projects.ProjectRegistry(layout).get("p2")["vehicle"] == "F720"

    # strip + 大小写不敏感去重（保留首次写法）
    res = c.put(VEHICLE_MODELS_URL, json={"codes": [" F610S ", "f610s", "F720"]})
    assert res.status_code == 200, res.get_data(as_text=True)
    assert res.get_json()["data"]["configured"] == ["F610S", "F720"]
    assert _get_models(c)[1]["configured"] == ["F610S", "F720"]

    # 清单变化不修改任何项目的车型字段
    assert projects.ProjectRegistry(layout).get("p2")["vehicle"] == "F720"

    # 从清单里删掉 F720 之后，项目已保存的车型仍然保留，并继续出现在 inUse 里
    res = c.put(VEHICLE_MODELS_URL, json={"codes": ["F610S"]})
    assert res.status_code == 200
    data = _get_models(c)[1]
    assert data["configured"] == ["F610S"]
    assert "F720" in data["inUse"]
    assert projects.ProjectRegistry(layout).get("p2")["vehicle"] == "F720"

    # 清空清单是合法的（只是没有候选），项目车型同样不受影响
    res = c.put(VEHICLE_MODELS_URL, json={"codes": []})
    assert res.status_code == 200
    assert _get_models(c)[1]["configured"] == []
    assert projects.ProjectRegistry(layout).get("p2")["vehicle"] == "F720"


@pytest.mark.parametrize(
    "payload, message",
    [
        ({}, "codes 必须是车型代码数组"),
        ({"codes": "F610S"}, "codes 必须是车型代码数组"),
        ({"codes": None}, "codes 必须是车型代码数组"),
        ({"codes": [""]}, "codes[0] 不能为空"),
        ({"codes": ["F610S", "   "]}, "codes[1] 不能为空"),
        ({"codes": ["X" * 41]}, "不能超过 40 个字符"),
        ({"codes": ["F610S", 42]}, "codes[1] 必须是文字"),
    ],
)
def test_put_rejects_invalid_codes(client, payload, message) -> None:  # type: ignore[no-untyped-def]
    c, _layout = client
    res = c.put(VEHICLE_MODELS_URL, json=payload)
    assert res.status_code == 400, res.get_data(as_text=True)
    error = res.get_json()["error"]
    assert error["type"] == "ValidationError"
    assert message in error["message"]


def test_put_rejects_more_than_200_codes_and_keeps_previous_list(client) -> None:  # type: ignore[no-untyped-def]
    c, _layout = client
    assert c.put(VEHICLE_MODELS_URL, json={"codes": ["KEEP"]}).status_code == 200

    too_many = [f"V{index:03d}" for index in range(201)]
    res = c.put(VEHICLE_MODELS_URL, json={"codes": too_many})
    assert res.status_code == 400, res.get_data(as_text=True)
    message = res.get_json()["error"]["message"]
    assert "200" in message
    # 被拒绝的请求不得改动已保存的清单（先校验后写）
    assert _get_models(c)[1]["configured"] == ["KEEP"]

    # 恰好 200 项是允许的上限
    assert c.put(VEHICLE_MODELS_URL, json={"codes": too_many[:200]}).status_code == 200
    assert len(_get_models(c)[1]["configured"]) == 200


def test_put_goes_through_local_guard(client) -> None:  # type: ignore[no-untyped-def]
    c, _layout = client
    assert c.put(VEHICLE_MODELS_URL, json={"codes": ["F610S"]}).status_code == 200
    res = c.put(
        VEHICLE_MODELS_URL,
        json={"codes": ["HACK"]},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert res.status_code == 403, res.get_data(as_text=True)
    assert res.get_json()["error"]["type"] == "CrossSiteRequest"
    # 跨站写请求没有落到配置表
    assert _get_models(c)[1]["configured"] == ["F610S"]


def test_vehicle_models_table_is_additive_migration(client) -> None:  # type: ignore[no-untyped-def]
    """迁移只建自己的表：不动既有表，也不预置任何车型代码。"""
    c, _layout = client
    from core.repos.plugin_schema import plugin_table_prefix

    table = f"{plugin_table_prefix('workbench')}vehicle_models"
    db = web_app.DatabaseManager()
    with db.get_connection() as conn:
        names = {
            str(row["name"])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert table in names
        assert "projects" in names
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert count == 0


# ---------------------------------------------------------------------------
# Node 执行前端 ES Module（纯函数 + 真实组件挂载）
# ---------------------------------------------------------------------------


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


def _run_node(runner: str, module_path: Path, scenario: dict) -> dict:
    node = shutil.which("node")
    assert node is not None, "未找到 Node.js 命令"
    res = subprocess.run(
        [
            node,
            "--experimental-vm-modules",
            "--input-type=module",
            "-e",
            runner,
            str(module_path),
            json.dumps(scenario),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert res.returncode == 0, f"Node 执行失败 (code {res.returncode}):\n{res.stderr}\n{res.stdout}"
    lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip().startswith("{")]
    assert lines, f"未获取到 Node 输出的 JSON 行:\n{res.stdout}\n{res.stderr}"
    return json.loads(lines[-1])


# --- 共用的小型 hook 运行时 + 渲染模型 --------------------------------------

_HOOKS_RUNTIME = r"""
const hooks = { slots: [], effects: {}, pending: [], cursor: 0, dirty: false };
let tree = null;
let component = null;
let props = null;

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
  const prev = hooks.effects[index];
  const changed = !prev || !deps || deps.length !== prev.deps.length || deps.some((d, i) => d !== prev.deps[i]);
  if (changed) hooks.pending.push({ index, fn, deps });
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

const COMPONENT_ATTR = /([A-Za-z_][\w-]*)=\s*"?$/;

function componentProps(node) {
  const props = {};
  for (let i = 1; i < node.values.length; i++) {
    const match = COMPONENT_ATTR.exec(node.strings[i] || "");
    if (match) props[match[1]] = node.values[i];
  }
  return props;
}

function isComponentNode(node) {
  return Boolean(node && node.__template) && node.strings[0] === "<" && typeof node.values[0] === "function";
}

function expand(node) {
  if (node === null || node === undefined || typeof node === "boolean") return node;
  if (Array.isArray(node)) return node.map(expand);
  if (typeof node !== "object" || !node.__template) return node;
  if (isComponentNode(node)) return expand(node.values[0](componentProps(node)));
  return { __template: true, strings: node.strings, values: node.values.map(expand) };
}

function renderMarkup(root) {
  const parts = [];
  const values = [];
  const visit = (node) => {
    if (node === null || node === undefined || typeof node === "boolean") return;
    if (typeof node === "string" || typeof node === "number") { parts.push(String(node)); return; }
    if (Array.isArray(node)) { node.forEach(visit); return; }
    if (node && node.__template) {
      for (let i = 0; i < node.strings.length; i++) {
        parts.push(node.strings[i]);
        if (i < node.values.length) {
          const value = node.values[i];
          if (value && value.__template) visit(value);
          else if (Array.isArray(value)) visit(value);
          else {
            parts.push("\u0000" + values.length + "\u0000");
            values.push(value);
          }
        }
      }
    }
  };
  visit(root);
  return { markup: parts.join(""), values };
}

const TAG_RE = /<([A-Za-z][\w-]*)((?:"[^"]*"|'[^']*'|[^>"'])*?)(\/?)>/g;
const ATTR_RE = /([A-Za-z_:][\w:.-]*)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|\u0000(\d+)\u0000))?/g;

function rendered() {
  const { markup, values } = renderMarkup(tree);
  const resolve = (text) => String(text).replace(/\u0000(\d+)\u0000/g, (_all, i) => {
    const value = values[Number(i)];
    if (value === null || value === undefined || typeof value === "boolean" || typeof value === "function") return "";
    return String(value);
  });
  const elements = [];
  let m;
  TAG_RE.lastIndex = 0;
  while ((m = TAG_RE.exec(markup))) {
    const attrs = {};
    let a;
    ATTR_RE.lastIndex = 0;
    while ((a = ATTR_RE.exec(m[2]))) {
      let value = true;
      if (a[4] !== undefined) value = values[Number(a[4])];
      else if (a[2] !== undefined) value = resolve(a[2]);
      else if (a[3] !== undefined) value = resolve(a[3]);
      attrs[a[1]] = value;
    }
    elements.push({ tag: m[1].toLowerCase(), attrs });
  }
  return { elements, markup, values, resolve };
}

function visibleText() {
  const { markup, values } = renderMarkup(tree);
  return markup.replace(/<[^>]*>/g, "").replace(/\u0000(\d+)\u0000/g, (_all, i) => {
    const value = values[Number(i)];
    if (value === null || value === undefined || typeof value === "boolean" || typeof value === "function") return "";
    if (Array.isArray(value)) return value.map((item) => (item && item.__template ? "" : String(item))).join("");
    return String(value);
  });
}

function find(selector) {
  return rendered().elements.filter(selector);
}

function renderTree() {
  hooks.cursor = 0;
  hooks.dirty = false;
  tree = expand(component(props));
}

function runEffects() {
  const pending = hooks.pending.splice(0);
  for (const effect of pending) {
    hooks.effects[effect.index] = { deps: effect.deps };
    effect.fn();
  }
}

async function settle() {
  for (let i = 0; i < 80; i++) {
    renderTree();
    runEffects();
    await new Promise((resolve) => setTimeout(resolve, 0));
    if (!hooks.dirty) return;
  }
  throw new Error("组件未稳定（可能陷入无限重渲染）");
}

function mount(name, extra) {
  hooks.slots = [];
  hooks.effects = {};
  hooks.pending = [];
  hooks.cursor = 0;
  component = exports[name];
  if (typeof component !== "function") throw new Error("没有可挂载的导出: " + name);
  props = Object.assign({}, extra || {});
}
"""


# --- projects.js：车型候选 / 手填 / 车型清单小节 ----------------------------

_PROJECTS_RUNNER = (
    r"""
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import * as vm from "node:vm";

const [, PROJECTS_JS_PATH, SCENARIO_JSON] = process.argv;
const scenario = JSON.parse(SCENARIO_JSON);

const apiCalls = [];
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
  if (next.network) throw apiErrorFrom({ status: 0, type: "network", message: "无法连接本地服务" });
  if (next.ok === false) throw apiErrorFrom(next);
  return next.data;
}

const context = vm.createContext({
  console: { log() {}, warn() {}, error() {}, info() {} },
  setTimeout: (fn) => setTimeout(fn, 0),
  clearTimeout,
  fetch: async () => { throw new Error("本用例不发 fetch"); },
  Promise, JSON, Math, Date, Object, Array, String, Number, Boolean, RegExp, Error,
  encodeURIComponent, decodeURIComponent,
  window: { location: { hash: "", reload() {} } },
});

const code = readFileSync(PROJECTS_JS_PATH, "utf8");
const mod = new vm.SourceTextModule(code, {
  context,
  initializeImportMeta(meta) {
    meta.url = pathToFileURL(PROJECTS_JS_PATH).href;
  },
});

await mod.link(async (specifier) => {
  if (specifier.includes("preact-htm")) {
    return new vm.SyntheticModule(
      ["html", "useState", "useEffect", "useRef", "useCallback"],
      function () {
        this.setExport("html", htmlStub);
        this.setExport("useState", useState);
        this.setExport("useEffect", useEffect);
        this.setExport("useRef", useRef);
        this.setExport("useCallback", useCallback);
      },
      { context }
    );
  }
  if (specifier.includes("common.js")) {
    return new vm.SyntheticModule(
      ["api", "html"],
      function () {
        this.setExport("api", fakeApi);
        this.setExport("html", htmlStub);
      },
      { context }
    );
  }
  throw new Error("unexpected specifier: " + specifier);
});

await mod.evaluate();
const exports = mod.namespace;

const out = { action: scenario.action, created: [], saved: [], closed: 0, snapshots: {}, results: {} };

"""
    + _HOOKS_RUNTIME
    + r"""

function inputElements() {
  return find((el) => el.tag === "input" && typeof el.attrs.onInput === "function");
}

function textareas() {
  return find((el) => el.tag === "textarea");
}

function optionValues() {
  return find((el) => el.tag === "option").map((el) => String(el.attrs.value));
}

function pickButton(step) {
  if (step.action) return find((el) => el.attrs["data-action"] === step.action)[0];
  if (step.text) {
    return find((el) => el.tag === "button"
      && typeof el.attrs.onClick === "function"
      && visibleText().indexOf(step.text) !== -1)[0];
  }
  return find((el) => el.tag === "button" && String(el.attrs.class || "").indexOf(step.class) !== -1
    && typeof el.attrs.onClick === "function")[0];
}

function snapshot() {
  return {
    text: visibleText(),
    options: optionValues(),
    inputs: inputElements().map((el) => el.attrs.value),
    textarea: textareas().length ? textareas()[0].attrs.value : null,
    apiCalls: apiCalls.slice(),
    created: out.created.slice(),
    saved: out.saved.slice(),
    closed: out.closed,
  };
}

async function runSteps() {
  for (const step of scenario.steps || []) {
    if (step.type === "focus") {
      const inputs = inputElements();
      if (step.index >= inputs.length) throw new Error("没有第 " + step.index + " 个输入框");
      const handler = inputs[step.index].attrs.onFocus;
      if (typeof handler !== "function") throw new Error("第 " + step.index + " 个输入框没有 onFocus");
      handler({ currentTarget: inputs[step.index] });
    } else if (step.type === "input") {
      const inputs = inputElements();
      if (step.index >= inputs.length) throw new Error("没有第 " + step.index + " 个输入框");
      inputs[step.index].attrs.onInput({ currentTarget: { value: step.value } });
    } else if (step.type === "textarea") {
      const area = textareas()[0];
      if (!area) throw new Error("未找到 textarea");
      area.attrs.onInput({ currentTarget: { value: step.value } });
    } else if (step.type === "submit") {
      const form = find((el) => el.tag === "form" && typeof el.attrs.onSubmit === "function")[0];
      if (!form) throw new Error("未找到表单 onSubmit");
      await form.attrs.onSubmit({ preventDefault() {} });
    } else if (step.type === "click") {
      const target = pickButton(step);
      if (!target) throw new Error("未找到可点击元素: " + JSON.stringify(step));
      if (target.attrs.disabled === true || target.attrs.disabled === "true") {
        throw new Error("目标是禁用状态，不应被点击: " + JSON.stringify(step));
      }
      await target.attrs.onClick();
    } else if (step.type === "snapshot") {
      out.snapshots[step.label] = snapshot();
    } else {
      throw new Error("unknown step: " + step.type);
    }
    await settle();
  }
  out.snapshots.final = snapshot();
}

function runHelpers() {
  const cases = scenario.cases || {};
  out.results.options = (cases.options || []).map((item) => ({
    label: item.label,
    value: Array.from(exports.vehicleModelOptions(item.configured, item.inUse, item.current)),
  }));
  out.results.parse = (cases.parse || []).map((item) => ({
    label: item.label,
    value: Array.from(exports.parseVehicleCodes(item.text)),
  }));
  out.results.constants = {
    max: exports.VEHICLE_MODELS_MAX,
    maxLength: exports.VEHICLE_CODE_MAX_LENGTH,
  };
}

if (scenario.action === "helpers") {
  runHelpers();
} else if (scenario.action === "modelsDialog") {
  mount("VehicleModelsDialog", { onClose: () => { out.closed += 1; } });
  await settle();
  out.snapshots.mounted = snapshot();
  await runSteps();
} else if (scenario.action === "newDialog") {
  mount("NewProjectDialog", {
    onClose: () => { out.closed += 1; },
    onCreated: (project) => { out.created.push(project); },
  });
  await settle();
  out.snapshots.mounted = snapshot();
  await runSteps();
} else if (scenario.action === "editDialog") {
  mount("EditProjectDialog", {
    project: scenario.project,
    onClose: () => { out.closed += 1; },
    onSaved: (project) => { out.saved.push(project); },
  });
  await settle();
  out.snapshots.mounted = snapshot();
  await runSteps();
} else {
  throw new Error("unknown action: " + scenario.action);
}

console.log(JSON.stringify(out));
"""
)


@needs_node
def test_vehicle_model_options_union_dedupes_and_never_invents_codes() -> None:
    """候选 = configured ∪ inUse ∪ 当前值；空输入得到空候选（不编造任何代码）。"""
    cases = [
        {"label": "empty", "configured": [], "inUse": [], "current": ""},
        {"label": "configured-only", "configured": ["F610S"], "inUse": [], "current": ""},
        {
            "label": "union-dedupe",
            "configured": ["F610S", "f610s", " F720 "],
            "inUse": ["F720", "F100"],
            "current": "",
        },
        {"label": "keeps-current", "configured": ["F610S"], "inUse": [], "current": "F999"},
        {"label": "blank-current", "configured": [], "inUse": [], "current": "   "},
        {"label": "not-arrays", "configured": None, "inUse": "F610S", "current": "F1"},
    ]
    data = _run_node(_PROJECTS_RUNNER, PROJECTS_JS, {"action": "helpers", "cases": {"options": cases}})
    values = {item["label"]: item["value"] for item in data["results"]["options"]}

    assert values["empty"] == []
    assert values["configured-only"] == ["F610S"]
    assert values["union-dedupe"] == ["F610S", "F720", "F100"]
    assert values["keeps-current"] == ["F610S", "F999"]
    assert values["blank-current"] == []
    assert values["not-arrays"] == ["F1"]
    assert data["results"]["constants"] == {"max": 200, "maxLength": 40}


@needs_node
def test_parse_vehicle_codes_splits_and_dedupes() -> None:
    """车型清单文本框：一行一个（也接受逗号/顿号），去空、大小写不敏感去重。"""
    cases = [
        {"label": "lines", "text": "F610S\nF720\n\n"},
        {"label": "commas", "text": "F610S, F720、f610s"},
        {"label": "blank", "text": "   \n , 、 "},
    ]
    data = _run_node(_PROJECTS_RUNNER, PROJECTS_JS, {"action": "helpers", "cases": {"parse": cases}})
    values = {item["label"]: item["value"] for item in data["results"]["parse"]}
    assert values["lines"] == ["F610S", "F720"]
    assert values["commas"] == ["F610S", "F720"]
    assert values["blank"] == []


@needs_node
def test_new_project_vehicle_input_offers_candidates_and_stays_free_text() -> None:
    """新建项目：聚焦后加载候选（datalist = configured ∪ inUse），手填值照样提交。"""
    data = _run_node(
        _PROJECTS_RUNNER,
        PROJECTS_JS,
        {
            "action": "newDialog",
            "apiQueue": [
                {
                    "url": VEHICLE_MODELS_URL,
                    "ok": True,
                    "data": {"configured": ["F610S", "F720"], "inUse": ["F100"]},
                },
                {"url": "/api/p/workbench/projects", "ok": True, "data": {"project": {"id": "p3"}}},
            ],
            "steps": [
                {"type": "focus", "index": 0},
                {"type": "snapshot", "label": "loaded"},
                {"type": "input", "index": 0, "value": "F999"},
                {"type": "submit"},
            ],
        },
    )
    loaded = data["snapshots"]["loaded"]
    assert loaded["options"] == ["F610S", "F720", "F100"]
    assert loaded["apiCalls"] == [{"url": VEHICLE_MODELS_URL, "method": "GET", "body": None}]

    final = data["snapshots"]["final"]
    assert final["apiCalls"][-1]["url"] == "/api/p/workbench/projects"
    assert final["apiCalls"][-1]["body"]["vehicle"] == "F999", "清单里没有的车型必须仍可手填提交"
    assert [project["id"] for project in final["created"]] == ["p3"]


@needs_node
def test_new_project_survives_candidate_load_failure_with_readable_hint() -> None:
    """候选加载失败只降级为无候选：显示一行提示，手填与提交照常。"""
    data = _run_node(
        _PROJECTS_RUNNER,
        PROJECTS_JS,
        {
            "action": "newDialog",
            "apiQueue": [
                {"url": VEHICLE_MODELS_URL, "network": True},
                {"url": "/api/p/workbench/projects", "ok": True, "data": {"project": {"id": "p9"}}},
            ],
            "steps": [
                {"type": "focus", "index": 0},
                {"type": "snapshot", "label": "degraded"},
                {"type": "input", "index": 0, "value": "F123"},
                {"type": "submit"},
            ],
        },
    )
    degraded = data["snapshots"]["degraded"]
    assert degraded["options"] == []
    assert "车型候选没有加载成功" in degraded["text"]
    assert "无法连接本地服务" in degraded["text"]

    final = data["snapshots"]["final"]
    assert final["apiCalls"][-1]["body"]["vehicle"] == "F123"
    assert [project["id"] for project in final["created"]] == ["p9"]


@needs_node
def test_edit_project_keeps_existing_vehicle_even_when_list_changed() -> None:
    """既有车型不在清单里也必须保留在候选与输入框里（清单变化不丢既有车型）。"""
    project = {
        "id": "p2",
        "name": "旧项目",
        "vehicle": "F777",
        "departments": ["车体科"],
        "active": True,
        "revision": 3,
        "status": "active",
    }
    data = _run_node(
        _PROJECTS_RUNNER,
        PROJECTS_JS,
        {
            "action": "editDialog",
            "project": project,
            "apiQueue": [
                {"url": VEHICLE_MODELS_URL, "ok": True, "data": {"configured": ["F610S"], "inUse": []}},
                {
                    "url": "/api/p/workbench/projects/p2",
                    "ok": True,
                    "data": {"project": dict(project, name="新名字", revision=4)},
                },
            ],
            "steps": [
                {"type": "focus", "index": 1},
                {"type": "snapshot", "label": "loaded"},
                {"type": "input", "index": 0, "value": "新名字"},
                {"type": "submit"},
            ],
        },
    )
    loaded = data["snapshots"]["loaded"]
    assert loaded["inputs"][1] == "F777", "既有项目的车型必须原样显示"
    assert loaded["options"] == ["F610S", "F777"]

    final = data["snapshots"]["final"]
    assert final["apiCalls"][-1]["body"] == {"name": "新名字", "expectedRevision": 3}
    assert "vehicle" not in final["apiCalls"][-1]["body"], "清单变化不得触发车型改写"


@needs_node
def test_vehicle_models_dialog_saves_configured_list_and_refreshes_candidates() -> None:
    """「车型清单」小节：PUT 整表替换，成功后刷新候选，并说明不影响项目车型。"""
    data = _run_node(
        _PROJECTS_RUNNER,
        PROJECTS_JS,
        {
            "action": "modelsDialog",
            "apiQueue": [
                {"url": VEHICLE_MODELS_URL, "ok": True, "data": {"configured": ["F610S"], "inUse": ["F720"]}},
                {"url": VEHICLE_MODELS_URL, "ok": True, "data": {"configured": ["F610S", "F720", "F888"]}},
                {"url": VEHICLE_MODELS_URL, "ok": True, "data": {"configured": ["F610S", "F720", "F888"], "inUse": ["F720"]}},
            ],
            "steps": [
                {"type": "snapshot", "label": "loaded"},
                {"type": "textarea", "value": "F610S\nF720\nF888"},
                {"type": "click", "action": "save-vehicle-models"},
                {"type": "snapshot", "label": "saved"},
            ],
        },
    )
    loaded = data["snapshots"]["loaded"]
    assert loaded["textarea"] == "F610S"
    assert "正在使用（来自现有项目，只读）：F720" in loaded["text"]

    saved = data["snapshots"]["saved"]
    put_calls = [call for call in saved["apiCalls"] if call["method"] == "PUT"]
    assert put_calls == [
        {
            "url": VEHICLE_MODELS_URL,
            "method": "PUT",
            "body": {"codes": ["F610S", "F720", "F888"]},
        }
    ]
    assert "已保存车型清单（3 项）" in saved["text"]
    assert "不会改动任何项目已保存的车型" in saved["text"]
    # 保存成功后重新拉取候选
    assert saved["apiCalls"][-1] == {"url": VEHICLE_MODELS_URL, "method": "GET", "body": None}
    assert saved["textarea"] == "F610S\nF720\nF888"


@needs_node
def test_vehicle_models_dialog_shows_backend_message_on_failure() -> None:
    """保存失败如实显示后端 message，不假装成功。"""
    data = _run_node(
        _PROJECTS_RUNNER,
        PROJECTS_JS,
        {
            "action": "modelsDialog",
            "apiQueue": [
                {"url": VEHICLE_MODELS_URL, "ok": True, "data": {"configured": ["F610S"], "inUse": []}},
                {
                    "url": VEHICLE_MODELS_URL,
                    "ok": False,
                    "status": 400,
                    "type": "ValidationError",
                    "message": "codes[1] 不能超过 40 个字符",
                },
            ],
            "steps": [
                {"type": "textarea", "value": "F610S\n" + "X" * 41},
                {"type": "click", "action": "save-vehicle-models"},
            ],
        },
    )
    final = data["snapshots"]["final"]
    assert "codes[1] 不能超过 40 个字符" in final["text"]
    assert "已保存车型清单" not in final["text"]
    assert [call["method"] for call in final["apiCalls"]] == ["GET", "PUT"]


# --- auto-sync.js：科室回写的显式勾选与失败展示 ----------------------------

_AUTO_SYNC_RUNNER = (
    r"""
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import * as vm from "node:vm";

const [, AUTO_SYNC_JS_PATH, SCENARIO_JSON] = process.argv;
const scenario = JSON.parse(SCENARIO_JSON);

const calls = [];
const enableFlowCalls = [];
const busyStates = [];

function apiError(spec) {
  const err = new Error(spec.message || "请求失败");
  err.name = "ApiError";
  err.status = spec.status === undefined || spec.status === null ? 0 : spec.status;
  err.type = spec.type || (err.status ? "http" : "network");
  err.code = spec.code === undefined ? null : spec.code;
  return err;
}

const STATUS = {
  phase: { displayName: "F610S", status: "active", startDate: "", endDate: "", updatedAt: "" },
  deliverables: [
    { id: "D1", name: "交付物一", sourceInfo: { syncCapable: true, displayName: "TDC" } },
    { id: "D2", name: "交付物二（已开启）", sourceInfo: { syncCapable: true, displayName: "TDC" } },
  ],
};

const PROJECTS = {
  managed: true,
  active: "p2",
  projects: [
    {
      id: "p2",
      name: "当前项目",
      vehicle: "F610S",
      departments: ["车体科", "车身科"],
      active: true,
      revision: 7,
      status: "active",
    },
  ],
};

async function apiRequest(url, options) {
  const opts = options || {};
  const method = opts.method || "GET";
  const text = String(url);
  calls.push({ url: text, method, body: opts.body === undefined ? null : opts.body });
  if (text.indexOf("/api/project-status/deliverables/") === 0) {
    return text.indexOf("/D2/") !== -1 ? { enabled: true } : { enabled: false };
  }
  if (text.indexOf("/api/project-status?phase=") === 0) return STATUS;
  if (text === "/api/settings") return { credentialVaultConfigured: true };
  if (text === "/api/p/workbench/projects" && method === "GET") return PROJECTS;
  if (text.indexOf("/api/project-status/phases/") === 0) return { ok: true };
  if (text.indexOf("/api/p/workbench/projects/") === 0 && method === "PATCH") {
    if (scenario.writeBackError) throw apiError(scenario.writeBackError);
    return { project: { id: "p2", departments: opts.body.departments, revision: 8 } };
  }
  throw new Error("未预置的接口调用: " + text);
}

const syncStore = { request: null };

function markFirstSyncRunning(ids) {
  if (!syncStore.request) syncStore.request = { deliverables: [], entries: [] };
  (ids || []).forEach((id) => recordFirstSyncEntry({ id, name: "", state: "running", text: "首次同步进行中" }));
}

function markFirstSyncNotApplicable(items) {
  (items || []).forEach((item) => recordFirstSyncEntry({ id: item.id, name: item.name, state: "not_applicable", text: item.text }));
  return syncStore.request;
}

function recordFirstSyncEntry(entry) {
  if (!syncStore.request) syncStore.request = { deliverables: [], entries: [] };
  const index = syncStore.request.entries.findIndex((item) => item.id === entry.id);
  if (index === -1) syncStore.request.entries.push(entry);
  else syncStore.request.entries[index] = entry;
  return syncStore.request;
}

function failRunningFirstSync(text) {
  if (!syncStore.request) return null;
  syncStore.request.entries = syncStore.request.entries.map((entry) => (entry.state === "running"
    ? { id: entry.id, name: entry.name, state: "failed", text: text || "首次同步没有完成" }
    : entry));
  return syncStore.request;
}

function readFirstSyncRequest() { return syncStore.request; }
function readOnboardingSelection() { return null; }
function recoverInterruptedFirstSync() { return null; }
function requestFirstSync(payload) {
  syncStore.request = { deliverables: (payload && payload.deliverables) || [], entries: [] };
  return syncStore.request;
}

function summarizeFirstSync(entries) {
  const list = Array.isArray(entries) ? entries : [];
  const count = (state) => list.filter((entry) => entry.state === state).length;
  const success = count("success");
  const failed = count("failed");
  const partial = count("partial");
  const running = count("running");
  const notApplicable = count("not_applicable");
  const total = list.length;
  return {
    total,
    success,
    failed,
    partial,
    running,
    notApplicable,
    notStarted: Math.max(0, total - success - failed - partial - running - notApplicable),
    allDone: total > 0 && success === total,
  };
}

function capabilitiesOf() { return {}; }
function ewoPolicyErrorMessage(err) {
  return (err && err.message) || String(err || "");
}
function wizardInitialValues() { return {}; }
function wizardKind() { return {}; }
function wizardPrecheck() { return ""; }
function redactSensitiveText(text) { return String(text === undefined || text === null ? "" : text); }

async function runEnableFlow(args) {
  enableFlowCalls.push(args && args.item ? String(args.item.id) : "");
  if (scenario.enableFails) throw new Error("核对没有通过：系统里没有匹配的数据");
  return { data: { result: { finalState: "success", outcome: "completed" } } };
}

const windowStub = {
  location: { hash: "", reload() {} },
  __vseWizardBusy: false,
};
Object.defineProperty(windowStub, "__vseWizardBusy", {
  get() { return busyStates[busyStates.length - 1]; },
  set(value) { busyStates.push(value); },
});

const context = vm.createContext({
  console: { log() {}, warn() {}, error() {}, info() {} },
  setTimeout: (fn) => setTimeout(fn, 0),
  clearTimeout,
  Promise, JSON, Math, Date, Object, Array, String, Number, Boolean, RegExp, Error,
  encodeURIComponent, decodeURIComponent,
  window: windowStub,
});

const code = readFileSync(AUTO_SYNC_JS_PATH, "utf8");
const mod = new vm.SourceTextModule(code, {
  context,
  initializeImportMeta(meta) {
    meta.url = pathToFileURL(AUTO_SYNC_JS_PATH).href;
  },
});

function synthetic(names, factory) {
  return new vm.SyntheticModule(names, function () {
    const values = factory();
    names.forEach((name) => this.setExport(name, values[name]));
  }, { context });
}

await mod.link(async (specifier) => {
  if (specifier.includes("preact-htm")) {
    return synthetic(["html", "useState", "useEffect", "useRef", "useCallback"], () => ({
      html: htmlStub,
      useState,
      useEffect,
      useRef,
      useCallback,
    }));
  }
  if (specifier.includes("kit.js")) {
    return synthetic(["useStylesheet"], () => ({ useStylesheet() {} }));
  }
  if (specifier.includes("onboarding-selection")) {
    return synthetic(
      [
        "failRunningFirstSync",
        "markFirstSyncNotApplicable",
        "markFirstSyncRunning",
        "readFirstSyncRequest",
        "recoverInterruptedFirstSync",
        "readOnboardingSelection",
        "recordFirstSyncEntry",
        "requestFirstSync",
        "summarizeFirstSync",
      ],
      () => ({
        failRunningFirstSync,
        markFirstSyncNotApplicable,
        markFirstSyncRunning,
        readFirstSyncRequest,
        recoverInterruptedFirstSync,
        readOnboardingSelection,
        recordFirstSyncEntry,
        requestFirstSync,
        summarizeFirstSync,
      })
    );
  }
  if (specifier.includes("shared/client")) {
    return synthetic(["PROJECT_PHASE_ID"], () => ({ PROJECT_PHASE_ID: "VPI-T2" }));
  }
  if (specifier.includes("deliverable/api")) {
    return synthetic(["apiRequest", "enc"], () => ({ apiRequest, enc: encodeURIComponent }));
  }
  if (specifier.includes("enable-flow")) {
    return synthetic(["runEnableFlow"], () => ({ runEnableFlow }));
  }
  if (specifier.includes("deliverable/format")) {
    return synthetic(["redactSensitiveText"], () => ({ redactSensitiveText }));
  }
  if (specifier.includes("policy-logic")) {
    return synthetic(
      ["capabilitiesOf", "ewoPolicyErrorMessage", "wizardInitialValues", "wizardKind", "wizardPrecheck"],
      () => ({ capabilitiesOf, ewoPolicyErrorMessage, wizardInitialValues, wizardKind, wizardPrecheck })
    );
  }
  throw new Error("unexpected specifier: " + specifier);
});

await mod.evaluate();
const exports = mod.namespace;

const out = { action: scenario.action, results: {}, snapshots: {} };

"""
    + _HOOKS_RUNTIME
    + r"""

function checkboxes() {
  return find((el) => el.tag === "input" && el.attrs.type === "checkbox");
}

function primaryButton() {
  return find((el) => el.tag === "button" && String(el.attrs.class || "").indexOf("is-primary") !== -1
    && typeof el.attrs.onClick === "function")[0];
}

function snapshot() {
  const box = checkboxes()[0];
  return {
    text: visibleText(),
    checkbox: box ? box.attrs.checked === true : null,
    calls: calls.slice(),
    enableFlow: enableFlowCalls.slice(),
    busyStates: busyStates.slice(),
  };
}

async function runSteps() {
  for (const step of scenario.steps || []) {
    if (step.type === "toggle-write-back") {
      const box = checkboxes()[0];
      if (!box) throw new Error("未找到「同时把这些科室设为项目默认科室」勾选框");
      box.attrs.onChange({ currentTarget: { checked: step.value } });
    } else if (step.type === "click-start") {
      const button = primaryButton();
      if (!button) throw new Error("未找到「全部开启」按钮");
      if (button.attrs.disabled === true) throw new Error("「全部开启」按钮不应是禁用状态");
      await button.attrs.onClick();
    } else if (step.type === "snapshot") {
      out.snapshots[step.label] = snapshot();
    } else {
      throw new Error("unknown step: " + step.type);
    }
    await settle();
  }
  out.snapshots.final = snapshot();
}

function runHelpers() {
  const cases = scenario.cases || {};
  out.results.plan = (cases.plan || []).map((item) => ({
    label: item.label,
    value: exports.departmentWriteBackPlan({
      writeBack: item.writeBack,
      enabled: item.enabled,
      project: item.project,
      departments: item.departments,
    }),
  }));
  out.results.failure = (cases.failure || []).map((item) => ({
    label: item.label,
    value: exports.departmentWriteBackFailure(item.reason),
  }));
}

if (scenario.action === "helpers") {
  runHelpers();
} else if (scenario.action === "page") {
  mount("default", { plugin: { id: "project_overview" } });
  await settle();
  out.snapshots.mounted = snapshot();
  await runSteps();
} else {
  throw new Error("unknown action: " + scenario.action);
}

console.log(JSON.stringify(out));
"""
)


@needs_node
def test_department_write_back_plan_requires_explicit_checkbox_and_enabled_item() -> None:
    """未勾选 / 没有成功开启一项 / 没有科室 → 不发请求；勾选且有成功项才带 expectedRevision。"""
    project = {"id": "p2", "revision": 7, "departments": ["车体科"]}
    cases = [
        {"label": "unchecked", "writeBack": False, "enabled": 1, "project": project, "departments": ["车体科"]},
        {"label": "nothing-enabled", "writeBack": True, "enabled": 0, "project": project, "departments": ["车体科"]},
        {"label": "no-departments", "writeBack": True, "enabled": 1, "project": project, "departments": []},
        {"label": "blank-departments", "writeBack": True, "enabled": 1, "project": project, "departments": ["  "]},
        {"label": "checked-ok", "writeBack": True, "enabled": 2, "project": project, "departments": ["车体科", " 车身科 ", "车体科"]},
        {"label": "no-revision", "writeBack": True, "enabled": 1, "project": {"id": "p2"}, "departments": ["车体科"]},
        {"label": "no-project", "writeBack": True, "enabled": 1, "project": None, "departments": ["车体科"]},
    ]
    data = _run_node(_AUTO_SYNC_RUNNER, AUTO_SYNC_JS, {"action": "helpers", "cases": {"plan": cases}})
    plans = {item["label"]: item["value"] for item in data["results"]["plan"]}

    assert plans["unchecked"] is None, "未勾选时绝不能发回写请求"
    assert plans["nothing-enabled"] is None, "一项都没成功开启时不能回写"
    assert plans["no-departments"] is None
    assert plans["blank-departments"] is None
    assert plans["checked-ok"] == {
        "projectId": "p2",
        "body": {"departments": ["车体科", "车身科"], "expectedRevision": 7},
        "error": "",
    }
    assert plans["no-revision"]["body"] == {"departments": ["车体科"]}, "没有 revision 字段时按既有契约省略"
    assert plans["no-project"]["error"]


@needs_node
def test_department_write_back_failure_message_is_explicit() -> None:
    data = _run_node(
        _AUTO_SYNC_RUNNER,
        AUTO_SYNC_JS,
        {"action": "helpers", "cases": {"failure": [{"label": "reason", "reason": "项目已被修改，请刷新后重试"}]}},
    )
    assert data["results"]["failure"][0]["value"] == "科室没有写回项目默认值：项目已被修改，请刷新后重试"


@needs_node
def test_auto_sync_without_checkbox_never_patches_project_departments() -> None:
    """默认不勾选：一键开启照常跑，但不发任何项目 PATCH。"""
    data = _run_node(
        _AUTO_SYNC_RUNNER,
        AUTO_SYNC_JS,
        {
            "action": "page",
            "steps": [
                {"type": "snapshot", "label": "mounted"},
                {"type": "click-start"},
                {"type": "snapshot", "label": "after"},
            ],
        },
    )
    mounted = data["snapshots"]["mounted"]
    assert mounted["checkbox"] is False, "「同时把这些科室设为项目默认科室」默认不勾选"

    after = data["snapshots"]["after"]
    patches = [call for call in after["calls"] if call["method"] == "PATCH"]
    assert patches == [], "未勾选时不得改动项目默认科室"
    assert after["enableFlow"] == ["D1"], "一键开启仍只处理未开启项（D2 已开启）"
    assert "首次同步成功" in after["text"]
    assert "科室没有写回" not in after["text"]
    assert "科室已写回" not in after["text"]


@needs_node
def test_auto_sync_checked_writes_departments_back_with_expected_revision() -> None:
    """勾选且成功开启一项：PATCH 只改默认科室，并带 expectedRevision。"""
    data = _run_node(
        _AUTO_SYNC_RUNNER,
        AUTO_SYNC_JS,
        {
            "action": "page",
            "steps": [
                {"type": "toggle-write-back", "value": True},
                {"type": "snapshot", "label": "checked"},
                {"type": "click-start"},
                {"type": "snapshot", "label": "after"},
            ],
        },
    )
    assert data["snapshots"]["checked"]["checkbox"] is True

    after = data["snapshots"]["after"]
    patches = [call for call in after["calls"] if call["method"] == "PATCH"]
    assert patches == [
        {
            "url": "/api/p/workbench/projects/p2",
            "method": "PATCH",
            "body": {"departments": ["车体科", "车身科"], "expectedRevision": 7},
        }
    ]
    assert "科室已写回项目默认值：车体科、车身科" in after["text"]
    # 已开启项的结果展示不受回写影响
    assert "首次同步成功" in after["text"]
    assert after["enableFlow"] == ["D1"]


@needs_node
def test_auto_sync_write_back_conflict_is_reported_and_keeps_item_results() -> None:
    """回写失败（409 修订冲突）在结果区如实显示，不 console.warn、不影响已开启项结果。"""
    data = _run_node(
        _AUTO_SYNC_RUNNER,
        AUTO_SYNC_JS,
        {
            "action": "page",
            "writeBackError": {"status": 409, "type": "RevisionConflict", "message": "项目已被修改，请刷新后重试"},
            "steps": [
                {"type": "toggle-write-back", "value": True},
                {"type": "click-start"},
                {"type": "snapshot", "label": "after"},
            ],
        },
    )
    after = data["snapshots"]["after"]
    assert "科室没有写回项目默认值：项目已被修改，请刷新后重试" in after["text"]
    assert "科室已写回项目默认值" not in after["text"]
    assert "首次同步成功" in after["text"], "已开启项的结果不能被回写失败盖掉"
    assert after["enableFlow"] == ["D1"]
    patches = [call for call in after["calls"] if call["method"] == "PATCH"]
    assert patches[0]["body"]["expectedRevision"] == 7


@needs_node
def test_auto_sync_checked_but_nothing_enabled_never_patches() -> None:
    """勾选了但一项都没开启成功：不回写项目默认科室。"""
    data = _run_node(
        _AUTO_SYNC_RUNNER,
        AUTO_SYNC_JS,
        {
            "action": "page",
            "enableFails": True,
            "steps": [
                {"type": "toggle-write-back", "value": True},
                {"type": "click-start"},
                {"type": "snapshot", "label": "after"},
            ],
        },
    )
    after = data["snapshots"]["after"]
    patches = [call for call in after["calls"] if call["method"] == "PATCH"]
    assert patches == []
    assert "核对没有通过" in after["text"]
    assert "科室没有写回" not in after["text"], "没有开启成功就不存在回写失败"
