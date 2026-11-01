# -*- coding: utf-8 -*-
"""项目编辑与归档的前端接线（DSH-V2-38；契约 C3「项目与向导」）。

本文件用 Node 真实执行 `plugins/workbench/static/projects.js`：

1. 直接调用导出的纯函数 `buildProjectPatch` / `isRevisionConflict` /
   `archiveBlockedReason`，钉住「省略 = 不改」「409 修订冲突」「归档门禁」三条语义；
2. 用最小 hook 运行时挂载真实的 `EditProjectDialog` / `ArchiveProjectDialog` /
   `ProjectSwitcher`，取出表单 `onSubmit`、输入 `onInput`、按钮 `onClick` 并真的调用，
   再用假 `api` / 假 `fetch` 观察实际发出的请求体与界面文案。

覆盖：
- 编辑只提交改动字段（未改动一律省略，绝不因省略而清空后端字段），并带 `expectedRevision`；
- 409 RevisionConflict 时提示「项目已被修改，请刷新后再试」，刷新按钮重新拉列表并载入最新值，
  再用新的 revision 保存；
- 归档按钮：当前项目禁用并写明原因，其余项目可归档；归档请求复用既有 archive 接口，
  成功文案明确「数据仍保留」；
- 项目切换路径未变（POST switch → 等重启 → 刷新页面）。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECTS_JS = REPO_ROOT / "plugins" / "workbench" / "static" / "projects.js"


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

const [, PROJECTS_JS_PATH, SCENARIO_JSON] = process.argv;
const scenario = JSON.parse(SCENARIO_JSON);

// ---- 假 api / 假 fetch（与 web/static/host/api.js 同形状的 ApiError）---------
const apiCalls = [];
const reloads = [];
const queue = (scenario.apiQueue || []).slice();
const fetchScript = (scenario.fetchScript || []).slice();

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

async function fakeFetch(url) {
  if (!fetchScript.length) throw new Error("未预置的 fetch: " + url);
  const next = fetchScript.shift();
  if (next.network) throw new Error("服务未启动");
  return {
    ok: next.ok !== false,
    async json() { return next.body === undefined ? null : next.body; },
  };
}

// ---- 最小 hook 运行时（useState / useEffect，可重渲染）---------------------
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

// ---- 载入被测算模块 -------------------------------------------------------
const context = vm.createContext({
  console: { log() {}, warn() {}, error() {}, info() {} },
  setTimeout: (fn) => setTimeout(fn, 0),
  clearTimeout,
  fetch: fakeFetch,
  Promise, JSON, Math, Date, Object, Array, String, Number, Boolean, RegExp, Error,
  encodeURIComponent, decodeURIComponent,
  window: { location: { hash: "", reload() { reloads.push(1); } } },
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

// ---- 渲染结果模型：先展开嵌套组件，再把模板摊平成标记串并解析成元素 --------
// htmlStub 产出的是扁平模板：同一模板里的多个控件无法按 props 区分。
// 这里先递归展开函数组件（Busy / EditProjectDialog …），再把插值替换成哨兵、
// 按标签解析，得到每个控件自己的属性集合。
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

function inputElements() {
  return find((el) => el.tag === "input" && typeof el.attrs.onInput === "function");
}

function chipStates() {
  const states = {};
  find((el) => el.tag === "button" && el.attrs["aria-pressed"] !== undefined).forEach((el) => {
    states[String(el.attrs.key)] = el.attrs["aria-pressed"];
  });
  return states;
}

function archiveButtons() {
  return find((el) => el.attrs["data-action"] === "archive-project").map((el) => ({
    project: el.attrs["data-project"],
    disabled: el.attrs.disabled === true,
    label: el.attrs["aria-label"],
  }));
}

function snapshot() {
  return {
    text: visibleText(),
    inputs: inputElements().map((el) => el.attrs.value),
    chips: chipStates(),
    buttons: archiveButtons(),
    apiCalls: apiCalls.slice(),
    reloads: reloads.length,
    saved: out.saved.slice(),
    archived: out.archived.slice(),
    closed: out.closed,
  };
}

// ---- 渲染与稳定 ----------------------------------------------------------
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
  for (let i = 0; i < 60; i++) {
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
  props = Object.assign(
    {
      onClose: () => { out.closed += 1; },
      onSaved: (project) => { out.saved.push(project); },
      onArchived: (project) => { out.archived.push(project); },
    },
    extra || {}
  );
  // 首次渲染交给 settle()：先渲染再跑副作用，避免同一个 effect 被注册两次。
}

function pick(step) {
  if (step.action) {
    return find((el) => el.attrs["data-action"] === step.action
      && (step.project === undefined || el.attrs["data-project"] === step.project))[0];
  }
  if (step.role) {
    return find((el) => el.attrs.role === step.role
      && (step.project === undefined || el.attrs["data-project"] === step.project))[0];
  }
  return find((el) => String(el.attrs.class || "").indexOf(step.class) !== -1
    && typeof el.attrs.onClick === "function")[0];
}

// ---- 场景 ----------------------------------------------------------------
const out = { action: scenario.action, saved: [], archived: [], closed: 0, snapshots: {}, results: {} };

function runHelpers() {
  const cases = scenario.cases || {};
  out.results.patch = (cases.patch || []).map((item) => ({
    label: item.label,
    patch: exports.buildProjectPatch(item.draft, item.original),
  }));
  out.results.conflict = (cases.conflict || []).map((item) => {
    const err = Object.assign(new Error("synthetic"), {
      status: item.status === undefined ? null : item.status,
      type: item.type === undefined ? null : item.type,
      code: item.code === undefined ? null : item.code,
    });
    return { label: item.label, conflict: exports.isRevisionConflict(err) };
  });
  out.results.archive = (cases.archive || []).map((item) => ({
    label: item.label,
    reason: exports.archiveBlockedReason(item.project, item.projects),
  }));
  out.results.constants = {
    conflictMessage: exports.REVISION_CONFLICT_MESSAGE,
    defaults: Array.from(exports.DEFAULT_DEPARTMENTS),
  };
}

async function runSteps() {
  for (const step of scenario.steps || []) {
    if (step.type === "input") {
      const inputs = inputElements();
      if (step.index >= inputs.length) throw new Error("没有第 " + step.index + " 个输入框");
      inputs[step.index].attrs.onInput({ currentTarget: { value: step.value } });
    } else if (step.type === "submit") {
      const form = find((el) => el.tag === "form" && typeof el.attrs.onSubmit === "function")[0];
      if (!form) throw new Error("未找到表单 onSubmit");
      await form.attrs.onSubmit({ preventDefault() {} });
    } else if (step.type === "click") {
      const target = pick(step);
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

if (scenario.action === "helpers") {
  runHelpers();
} else if (scenario.action === "editDialog" || scenario.action === "archiveDialog") {
  mount(scenario.action === "editDialog" ? "EditProjectDialog" : "ArchiveProjectDialog", { project: scenario.project });
  await settle();
  out.snapshots.mounted = snapshot();
  await runSteps();
} else if (scenario.action === "switcher") {
  mount("ProjectSwitcher");
  await settle();
  out.snapshots.mounted = snapshot();
  await runSteps();
} else {
  throw new Error("unknown action: " + scenario.action);
}

console.log(JSON.stringify(out));
"""


def _run_node_scenario(scenario: dict) -> dict:
    node = shutil.which("node")
    assert node is not None, "未找到 Node.js 命令"
    res = subprocess.run(
        [node, "--experimental-vm-modules", "--input-type=module", "-e", _RUNNER_JS, str(PROJECTS_JS), json.dumps(scenario)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert res.returncode == 0, f"Node 执行失败 (code {res.returncode}):\n{res.stderr}\n{res.stdout}"
    lines = [ln.strip() for ln in res.stdout.strip().splitlines() if ln.strip().startswith("{")]
    assert lines, f"未获取到 Node 输出的 JSON 行:\n{res.stdout}"
    return json.loads(lines[-1])


_PROJECT = {
    "id": "p2",
    "name": "旧项目名",
    "vehicle": "F610S",
    "departments": ["车体科"],
    "active": False,
    "revision": 3,
    "status": "active",
}


def _projects_payload(projects: list[dict], active: str) -> dict:
    return {"managed": True, "active": active, "projects": projects}


# ---------------------------------------------------------------------------
# 验收 1：只复用既有 PATCH / archive 接口，请求体只含改动字段
# ---------------------------------------------------------------------------


@needs_node
def test_patch_only_contains_changed_fields() -> None:
    """buildProjectPatch 只输出改动字段；未改动字段必须省略（省略 = 不改）。"""
    cases = [
        {
            "label": "no-change",
            "draft": {"name": "F610S", "vehicle": "F610S", "departments": ["车体科"]},
            "original": {"name": "F610S", "vehicle": "F610S", "departments": ["车体科"]},
        },
        {
            "label": "trimmed-no-change",
            "draft": {"name": " F610S ", "vehicle": " F610S ", "departments": [" 车体科 "]},
            "original": {"name": "F610S", "vehicle": "F610S", "departments": ["车体科"]},
        },
        {
            "label": "name-only",
            "draft": {"name": "新项目名", "vehicle": "F610S", "departments": ["车体科"]},
            "original": {"name": "旧项目名", "vehicle": "F610S", "departments": ["车体科"]},
        },
        {
            "label": "vehicle-only",
            "draft": {"name": "旧项目名", "vehicle": "F720", "departments": ["车体科"]},
            "original": {"name": "旧项目名", "vehicle": "F610S", "departments": ["车体科"]},
        },
        {
            "label": "departments-only",
            "draft": {"name": "旧项目名", "vehicle": "F610S", "departments": ["车体科", "内饰科"]},
            "original": {"name": "旧项目名", "vehicle": "F610S", "departments": ["车体科"]},
        },
        {
            "label": "vehicle-cleared",
            "draft": {"name": "旧项目名", "vehicle": "", "departments": ["车体科"]},
            "original": {"name": "旧项目名", "vehicle": "F610S", "departments": ["车体科"]},
        },
        {
            "label": "legacy-project-without-fields",
            "draft": {"name": "旧项目名", "vehicle": "", "departments": []},
            "original": {"name": "旧项目名"},
        },
    ]
    data = _run_node_scenario({"action": "helpers", "cases": {"patch": cases}})
    patches = {item["label"]: item["patch"] for item in data["results"]["patch"]}

    assert patches["no-change"] == {}
    assert patches["trimmed-no-change"] == {}
    assert patches["name-only"] == {"name": "新项目名"}
    assert patches["vehicle-only"] == {"vehicle": "F720"}
    assert patches["departments-only"] == {"departments": ["车体科", "内饰科"]}
    assert patches["vehicle-cleared"] == {"vehicle": ""}
    assert patches["legacy-project-without-fields"] == {}

    # 前端不会主动发 null（显式 null 才清空；清空车型发空串即可）
    for label, patch in patches.items():
        for key, value in patch.items():
            assert value is not None, f"{label} 的 {key} 不应是 null"


@needs_node
def test_revision_conflict_detection_uses_409_and_error_code() -> None:
    """409 + RevisionConflict（error.type 或 error.code）才算修订冲突，其它 409 不误判。"""
    cases = [
        {"label": "type", "status": 409, "type": "RevisionConflict"},
        {"label": "code", "status": 409, "type": "http", "code": "RevisionConflict"},
        {"label": "current-project-archived", "status": 409, "type": "CurrentProjectArchived"},
        {"label": "not-managed", "status": 409, "type": "NotManaged"},
        {"label": "wrong-status", "status": 422, "type": "RevisionConflict"},
        {"label": "no-status", "status": None, "type": "RevisionConflict"},
    ]
    data = _run_node_scenario({"action": "helpers", "cases": {"conflict": cases}})
    results = {item["label"]: item["conflict"] for item in data["results"]["conflict"]}
    assert results["type"] is True
    assert results["code"] is True
    assert results["current-project-archived"] is False
    assert results["not-managed"] is False
    assert results["wrong-status"] is False
    assert results["no-status"] is False


@needs_node
def test_edit_dialog_submits_changed_fields_with_expected_revision() -> None:
    """改名只发 name + expectedRevision；车型与科室省略，不会被清空。"""
    project = dict(_PROJECT)
    data = _run_node_scenario(
        {
            "action": "editDialog",
            "project": project,
            "apiQueue": [{"url": "/api/p/workbench/projects/p2", "ok": True, "data": {"project": dict(project, name="新项目名", revision=4)}}],
            "steps": [
                {"type": "input", "index": 0, "value": "新项目名"},
                {"type": "submit"},
            ],
        }
    )
    final = data["snapshots"]["final"]
    assert [call["method"] for call in final["apiCalls"]] == ["PATCH"]
    call = final["apiCalls"][0]
    assert call["url"] == "/api/p/workbench/projects/p2", "必须复用既有 PATCH projects/<id> 接口"
    assert call["body"] == {"name": "新项目名", "expectedRevision": 3}
    assert "vehicle" not in call["body"], "未改动的车型必须省略（省略 = 不改）"
    assert "departments" not in call["body"], "未改动的科室必须省略（省略 = 不改）"
    assert len(final["saved"]) == 1, "保存成功后必须把后端返回的项目交回列表"
    assert final["saved"][0]["name"] == "新项目名"
    assert final["closed"] == 0, "保存成功由父组件关闭对话框，不应重复调用 onClose"


@needs_node
def test_edit_dialog_without_changes_sends_no_request() -> None:
    """没有任何改动时直接关闭，不发 PATCH（避免无意义地自增 revision）。"""
    data = _run_node_scenario(
        {
            "action": "editDialog",
            "project": dict(_PROJECT),
            "steps": [{"type": "submit"}],
        }
    )
    final = data["snapshots"]["final"]
    assert final["apiCalls"] == []
    assert final["closed"] == 1
    assert final["saved"] == []


@needs_node
def test_blank_name_is_rejected_before_request() -> None:
    """项目名称清空是后端 422；前端先拦住并给中文说明，不发请求。"""
    data = _run_node_scenario(
        {
            "action": "editDialog",
            "project": dict(_PROJECT),
            "steps": [
                {"type": "input", "index": 0, "value": "   "},
                {"type": "submit"},
            ],
        }
    )
    final = data["snapshots"]["final"]
    assert final["apiCalls"] == []
    assert "项目名称不能为空" in final["text"]


# ---------------------------------------------------------------------------
# 验收 2：expectedRevision 冲突提示刷新，刷新后载入最新值再保存
# ---------------------------------------------------------------------------


@needs_node
def test_revision_conflict_prompts_refresh_and_reloads_latest_values() -> None:
    """409 RevisionConflict → 提示「项目已被修改，请刷新后再试」+ 刷新；刷新后 revision 前进。"""
    project = dict(_PROJECT)
    fresh = dict(project, name="别人刚改的名字", revision=4)
    data = _run_node_scenario(
        {
            "action": "editDialog",
            "project": project,
            "apiQueue": [
                {"url": "/api/p/workbench/projects/p2", "ok": False, "status": 409, "type": "RevisionConflict", "message": "项目已被修改，请刷新后重试"},
                {"url": "/api/p/workbench/projects", "ok": True, "data": _projects_payload([fresh], "main")},
                {"url": "/api/p/workbench/projects/p2", "ok": True, "data": {"project": dict(fresh, name="我的新名字", revision=5)}},
            ],
            "steps": [
                {"type": "input", "index": 0, "value": "我的新名字"},
                {"type": "submit"},
                {"type": "snapshot", "label": "conflict"},
                {"type": "click", "action": "refresh-project"},
                {"type": "snapshot", "label": "refreshed"},
                {"type": "input", "index": 0, "value": "我的新名字"},
                {"type": "submit"},
            ],
        }
    )
    conflict = data["snapshots"]["conflict"]
    assert "项目已被修改，请刷新后再试" in conflict["text"]
    assert conflict["apiCalls"][0]["body"] == {"name": "我的新名字", "expectedRevision": 3}
    assert len(conflict["saved"]) == 0, "冲突时绝不能当成保存成功"

    refreshed = data["snapshots"]["refreshed"]
    assert refreshed["inputs"][0] == "别人刚改的名字", "刷新必须载入服务器上的最新名称"
    assert refreshed["inputs"][1] == "F610S"
    assert refreshed["chips"].get("车体科") == "true"
    assert "已刷新到最新数据" in refreshed["text"]
    assert "项目已被修改，请刷新后再试" not in refreshed["text"], "刷新后冲突提示应消失"
    assert [call["method"] for call in refreshed["apiCalls"]] == ["PATCH", "GET"], "刷新走既有 GET projects 列表接口"

    final = data["snapshots"]["final"]
    assert final["apiCalls"][-1]["body"] == {"name": "我的新名字", "expectedRevision": 4}, "刷新后必须用新的 revision 保存"
    assert len(final["saved"]) == 1


@needs_node
def test_revision_conflict_refresh_handles_project_gone() -> None:
    """刷新时项目已不在列表：如实说明，不假装保存成功。"""
    project = dict(_PROJECT)
    data = _run_node_scenario(
        {
            "action": "editDialog",
            "project": project,
            "apiQueue": [
                {"url": "/api/p/workbench/projects/p2", "ok": False, "status": 409, "type": "RevisionConflict"},
                {"url": "/api/p/workbench/projects", "ok": True, "data": _projects_payload([], "main")},
            ],
            "steps": [
                {"type": "input", "index": 0, "value": "我的新名字"},
                {"type": "submit"},
                {"type": "click", "action": "refresh-project"},
            ],
        }
    )
    final = data["snapshots"]["final"]
    assert "这个项目已经不在项目列表里" in final["text"]
    assert len(final["saved"]) == 0


# ---------------------------------------------------------------------------
# 验收 3：归档保留数据，当前项目不能直接归档（按钮禁用 + 说明原因）
# ---------------------------------------------------------------------------


@needs_node
def test_archive_blocked_for_current_and_single_project() -> None:
    """归档门禁与后端 archive() 同口径：当前项目、唯一项目都给出中文原因。"""
    projects = [
        {"id": "main", "name": "主项目", "vehicle": "", "departments": [], "active": False, "status": "active", "revision": 1},
        {"id": "p2", "name": "当前项目", "vehicle": "F610S", "departments": [], "active": True, "status": "active", "revision": 2},
    ]
    cases = [
        {"label": "current-with-other-active", "project": projects[1], "projects": projects},
        {"label": "other-project", "project": projects[0], "projects": projects},
        {"label": "only-project", "project": projects[1], "projects": [projects[1]]},
        {"label": "current-with-only-retired-others", "project": projects[1], "projects": [dict(projects[0], status="retired"), projects[1]]},
        {"label": "missing-project", "project": None, "projects": projects},
    ]
    data = _run_node_scenario({"action": "helpers", "cases": {"archive": cases}})
    reasons = {item["label"]: item["reason"] for item in data["results"]["archive"]}

    assert reasons["current-with-other-active"] == "当前项目正在使用中，请先切换到其他项目再归档"
    assert reasons["other-project"] == ""
    assert reasons["only-project"] == "当前只有一个项目，不能归档"
    assert reasons["current-with-only-retired-others"] == "当前只有一个可用项目，不能归档"
    assert reasons["missing-project"]


@needs_node
def test_switcher_disables_archive_for_current_project_and_explains() -> None:
    """当前项目的归档按钮禁用并写明原因；其它项目可点开归档确认。"""
    projects = [
        {"id": "main", "name": "主项目", "vehicle": "F610S", "departments": ["车体科"], "active": False, "status": "active", "revision": 1},
        {"id": "p2", "name": "当前项目", "vehicle": "F720", "departments": [], "active": True, "status": "active", "revision": 2},
    ]
    data = _run_node_scenario(
        {
            "action": "switcher",
            "apiQueue": [{"url": "/api/p/workbench/projects", "ok": True, "data": _projects_payload(projects, "p2")}],
            "steps": [
                {"type": "click", "class": "wb-project-btn"},
                {"type": "snapshot", "label": "menu"},
            ],
        }
    )
    menu = data["snapshots"]["menu"]
    assert "当前项目" in menu["text"] and "主项目" in menu["text"]
    assert "当前项目正在使用中，请先切换到其他项目再归档" in menu["text"], "必须写明当前项目不能归档的原因"

    buttons = {item["project"]: item for item in menu["buttons"]}
    assert buttons["p2"]["disabled"] is True, "当前项目的归档按钮必须禁用"
    assert buttons["main"]["disabled"] is False, "非当前项目可以归档"
    assert buttons["p2"]["label"] == "归档「当前项目」"


@needs_node
def test_switcher_archives_other_project_and_keeps_data_message() -> None:
    """归档非当前项目：POST 既有 archive 接口，成功后刷新列表并说明数据仍保留。"""
    projects = [
        {"id": "main", "name": "主项目", "vehicle": "F610S", "departments": [], "active": False, "status": "active", "revision": 1},
        {"id": "p2", "name": "当前项目", "vehicle": "F720", "departments": [], "active": True, "status": "active", "revision": 2},
    ]
    archived = dict(projects[0], status="retired", revision=2)
    data = _run_node_scenario(
        {
            "action": "switcher",
            "apiQueue": [
                {"url": "/api/p/workbench/projects", "ok": True, "data": _projects_payload(projects, "p2")},
                {"url": "/api/p/workbench/projects/main/archive", "ok": True, "data": {"project": archived, "message": "已归档「主项目」"}},
                {"url": "/api/p/workbench/projects", "ok": True, "data": _projects_payload([archived, projects[1]], "p2")},
            ],
            "steps": [
                {"type": "click", "class": "wb-project-btn"},
                {"type": "click", "action": "archive-project", "project": "main"},
                {"type": "snapshot", "label": "confirm"},
                {"type": "click", "action": "confirm-archive"},
                {"type": "snapshot", "label": "after"},
            ],
        }
    )
    confirm = data["snapshots"]["confirm"]
    assert "归档「主项目」" in confirm["text"]
    assert "不会删除任何数据" in confirm["text"], "归档确认必须说明数据保留"

    after = data["snapshots"]["after"]
    archive_calls = [call for call in after["apiCalls"] if call["url"].endswith("/archive")]
    assert archive_calls == [{"url": "/api/p/workbench/projects/main/archive", "method": "POST", "body": {}}]
    assert "已归档「主项目」，数据仍保留在原来的数据文件夹里" in after["text"]
    assert "不会删除任何数据" not in after["text"], "归档成功后确认框必须关闭"
    assert after["apiCalls"][-1]["method"] == "GET", "归档成功后必须重新拉列表（retired 项目从菜单隐藏）"
    assert after["buttons"] == [], "归档后菜单已关闭，列表刷新为最新状态"


@needs_node
def test_archive_failure_is_reported_and_not_shown_as_success() -> None:
    """归档失败（例如后端判定不可归档）如实显示中文原因，不当成成功。"""
    projects = [
        {"id": "main", "name": "主项目", "vehicle": "F610S", "departments": [], "active": False, "status": "active", "revision": 1},
        {"id": "p2", "name": "当前项目", "vehicle": "F720", "departments": [], "active": True, "status": "active", "revision": 2},
    ]
    data = _run_node_scenario(
        {
            "action": "switcher",
            "apiQueue": [
                {"url": "/api/p/workbench/projects", "ok": True, "data": _projects_payload(projects, "p2")},
                {"url": "/api/p/workbench/projects/main/archive", "ok": False, "status": 409, "type": "CurrentProjectArchived", "message": "当前只有一个可用项目，不能归档"},
            ],
            "steps": [
                {"type": "click", "class": "wb-project-btn"},
                {"type": "click", "action": "archive-project", "project": "main"},
                {"type": "click", "action": "confirm-archive"},
            ],
        }
    )
    final = data["snapshots"]["final"]
    assert "当前只有一个可用项目，不能归档" in final["text"]
    assert final["archived"] == []
    assert "已归档" not in final["text"]


# ---------------------------------------------------------------------------
# 验收 4：项目切换路径未被改动（回归）
# ---------------------------------------------------------------------------


@needs_node
def test_project_switch_still_posts_switch_then_reloads_after_restart() -> None:
    """切换仍走 POST projects/<id>/switch，等重启后刷新；点当前项目不发请求。"""
    projects = [
        {"id": "main", "name": "主项目", "vehicle": "F610S", "departments": [], "active": True, "status": "active", "revision": 1},
        {"id": "p2", "name": "另一个项目", "vehicle": "F720", "departments": [], "active": False, "status": "active", "revision": 0},
    ]
    data = _run_node_scenario(
        {
            "action": "switcher",
            "apiQueue": [
                {"url": "/api/p/workbench/projects", "ok": True, "data": _projects_payload(projects, "main")},
                {"url": "/api/p/workbench/projects/p2/switch", "ok": True, "data": {"project": projects[1], "restarting": True}},
            ],
            "fetchScript": [
                {"ok": False},
                {"ok": True, "body": {"ok": True, "data": {"active": "p2", "managed": True, "projects": projects}}},
            ],
            "steps": [
                {"type": "click", "class": "wb-project-btn"},
                {"type": "click", "role": "option", "project": "main"},
                {"type": "snapshot", "label": "clicked-active"},
                {"type": "click", "class": "wb-project-btn"},
                {"type": "click", "role": "option", "project": "p2"},
                {"type": "snapshot", "label": "switched"},
            ],
        }
    )
    clicked_active = data["snapshots"]["clicked-active"]
    assert [call["method"] for call in clicked_active["apiCalls"]] == ["GET"], "点当前项目不得发切换请求"

    switched = data["snapshots"]["switched"]
    switch_calls = [call for call in switched["apiCalls"] if call["url"].endswith("/switch")]
    assert switch_calls == [{"url": "/api/p/workbench/projects/p2/switch", "method": "POST", "body": {}}]
    assert switched["reloads"] == 1, "确认服务以目标项目重启后必须刷新页面"
    assert "正在切换到「另一个项目」" in switched["text"]


# ---------------------------------------------------------------------------
# 回归：既有导出与复用面不变
# ---------------------------------------------------------------------------


@needs_node
def test_exports_stay_backwards_compatible() -> None:
    """新增可测函数不得破坏既有导出（project.js / today.js 零修改）。"""
    content = PROJECTS_JS.read_text(encoding="utf-8")
    for name in (
        "export const DEFAULT_DEPARTMENTS",
        "export function useProjects",
        "export async function waitForProject",
        "export function NewProjectDialog",
        "export function ProjectSwitcher",
        "export function EditProjectDialog",
        "export function ArchiveProjectDialog",
        "export function buildProjectPatch",
        "export function isRevisionConflict",
        "export function archiveBlockedReason",
    ):
        assert name in content, f"缺少导出：{name}"
    # 不新增注册表或接口：BASE 之外的 projects 路径都是 `${BASE}/...` 拼接
    rest = content.replace('const BASE = "/api/p/workbench/projects";', "")
    assert '"/api/p/workbench/projects"' not in rest
    assert "ProjectRegistry" not in content
