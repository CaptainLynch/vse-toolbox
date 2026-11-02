# -*- coding: utf-8 -*-
"""DSH-V2-21 调度时刻与暂停设置界面测试。

覆盖主控冻结契约（每条都是真实调用链，不做「源码含某符号」式断言）：

1. 后端经 ``create_app`` + conftest 默认已认证客户端走真实路由与真实 SQLite
   （``tmp_path``）：无绑定 -> ``mode="off"``、PUT 固定时刻后 GET 返回规范化 times
   与 nextRunAt、PUT 空 times 回到 interval、paused 时 nextRunAt 为 null；
2. 非法时刻 400 ``ValidationError`` 且消息字段级（``times`` / ``times[i]`` / ``paused``），
   失败不落库；
3. 写路由先过 ``ctx.local_guard()``：用 stub host 直接调 ``register``，守卫拒绝时
   路由返回 403 且**没有写库**（证明顺序，不是「源码里有这个调用」）；
4. 无会话写被拒：``@pytest.mark.raw_security`` 原生客户端 -> 401 SessionRequired；
5. ``today`` 只暴露 scheduledTime/status/attempt/lastErrorCode，不外露
   leaseToken/leaseOwner（同时断言库内确有租约值，避免空断言）；
6. 前端 ``schedule.js`` 在 Node VM 中执行真实模块（真实 api.js / ui-kit.js /
   time-format.js，仅 preact-htm 用最小 hook 运行时替身）：增删时刻、保存成功刷新、
   保存失败原位显示后端 message 且不清空输入、off / 未配置态文案、暂停与恢复、
   当天补跑状态。
"""

from __future__ import annotations

import importlib
import json
import shutil
import sqlite3
import subprocess
import sys
import types
from datetime import datetime, time
from pathlib import Path
from typing import Any

import pytest
from flask import Blueprint, Flask, jsonify

import services.schedule_policy as sp
from core.db_manager import DatabaseManager
from core.time_rules import BEIJING_OFFSET
from host.context import HostContext

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO_ROOT / "plugins" / "sync_control"
HOST_STATIC = REPO_ROOT / "web" / "static" / "host"
SCHEDULE_JS = PLUGIN_DIR / "static" / "schedule.js"
API_JS = HOST_STATIC / "api.js"
UIKIT_JS = HOST_STATIC / "ui-kit.js"
TIME_FORMAT_JS = HOST_STATIC / "time-format.js"

PLUGIN_ID = "sync-control"
PREFIX = "p_sync_control_"
PROJECT = "proj-21"
JOB = sp.SYNC_JOB_ID

#: 固定「现在」：2024-05-06（周一）北京时间 10:00。
BEIJING = BEIJING_OFFSET
NOW = datetime(2024, 5, 6, 10, 0, tzinfo=BEIJING)
NOW_MS = int(NOW.timestamp() * 1000)


# ── 后端夹具 ──────────────────────────────────────────────────────────────────


def _make_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """真实 create_app（只加载本插件）+ 隔离 SQLite，返回 (app, db_file)。"""
    import web.app as web_app

    db_cls = web_app.DatabaseManager
    db_file = tmp_path / "schedule_ui.db"
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(db_file))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=[PLUGIN_ID])
    app.config.update(TESTING=True)
    return app, db_file


class Api:
    """真实 Flask 测试客户端 + 契约路径的薄封装（无业务逻辑）。"""

    def __init__(self, app: Flask, module: Any, db_file: Path) -> None:
        self.app = app
        self.client = app.test_client()
        self.module = module
        self.db_file = db_file

    def binding(self, project: str = PROJECT):
        return self.client.get(f"/api/p/{PLUGIN_ID}/binding?projectId={project}")

    def save(self, body: Any, project: str = PROJECT):
        return self.client.put(f"/api/p/{PLUGIN_ID}/binding/{project}", json=body)

    def data(self, response) -> dict[str, Any]:
        assert response.status_code == 200, response.get_data(as_text=True)
        payload = response.get_json()
        assert payload["ok"] is True
        return payload["data"]


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Api:
    app, db_file = _make_app(monkeypatch, tmp_path)
    module = sys.modules["vse_plugins.sync_control.backend"]
    # 固定「现在」：nextRunAt 与 today 的当天判定都要可复现。
    monkeypatch.setattr(module, "now_utc", lambda: NOW)
    return Api(app, module, db_file)


def _binding_row(db_file: Path, project: str = PROJECT) -> dict[str, Any] | None:
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            f"SELECT mode, times, paused FROM {PREFIX}bindings "
            "WHERE project_id = ? AND job_id = ?",
            (project, JOB),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row is not None else None


def _slot_row(db_file: Path, scheduled_time: str) -> dict[str, Any]:
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            f"SELECT status, attempt, lease_owner, lease_token, last_error_code "
            f"FROM {PREFIX}slots WHERE project_id = ? AND scheduled_time = ?",
            (PROJECT, scheduled_time),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return dict(row)


def _store(db_file: Path) -> Any:
    from services.schedule_slots import SlotStore

    return SlotStore(DatabaseManager(db_path=db_file), PREFIX, clock=lambda: NOW)


# ── 1. 读：无绑定显示未开启 ───────────────────────────────────────────────────


def test_binding_without_row_is_off(api: Api) -> None:
    response = api.binding()
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json()["data"] == {
        "projectId": PROJECT,
        "jobId": JOB,
        "mode": "off",
        "times": [],
        "paused": False,
        "nextRunAt": None,
        "today": [],
    }


def test_binding_routes_validate_project_id(api: Api) -> None:
    missing = api.client.get(f"/api/p/{PLUGIN_ID}/binding")
    assert missing.status_code == 400
    assert missing.get_json()["error"]["type"] == "ValidationError"
    assert missing.headers["Cache-Control"] == "no-store"

    too_long = api.client.get(f"/api/p/{PLUGIN_ID}/binding?projectId={'x' * 201}")
    assert too_long.status_code == 400
    assert too_long.get_json()["error"]["type"] == "ValidationError"

    put_long = api.client.put(
        f"/api/p/{PLUGIN_ID}/binding/{'x' * 201}", json={"times": [], "paused": False}
    )
    assert put_long.status_code == 400
    assert put_long.get_json()["error"]["type"] == "ValidationError"


# ── 2. 写：固定时刻 / 规范化 / 下次执行 ───────────────────────────────────────


def test_put_fixed_times_normalizes_and_get_returns_next_run(api: Api) -> None:
    saved = api.save({"times": ["16:00", "9:00", "09:00"], "paused": False})
    assert saved.status_code == 200
    assert saved.headers["Cache-Control"] == "no-store"
    data = api.data(saved)
    assert data["mode"] == "fixed"
    # '9:00' ≡ '09:00'、去重、升序（规范化以后端 schedule_policy 为准）。
    assert data["times"] == ["09:00", "16:00"]
    # 10:00 之后的下一个固定时刻是当天 16:00（北京时间 ISO）。
    assert data["nextRunAt"] == "2024-05-06T16:00:00+08:00"
    assert data["paused"] is False
    assert data["jobId"] == JOB

    # 真实落库：不是只改了响应。
    row = _binding_row(api.db_file)
    assert row == {"mode": "fixed", "times": '["09:00", "16:00"]', "paused": 0}

    # GET 与 PUT 返回同一形状（保存后界面直接用这份数据刷新）。
    assert api.data(api.binding()) == data


def test_put_empty_times_returns_to_interval(api: Api) -> None:
    api.data(api.save({"times": ["09:00"], "paused": False}))
    data = api.data(api.save({"times": [], "paused": False}))
    assert data["mode"] == "interval"
    assert data["times"] == []
    assert data["nextRunAt"] is None
    assert _binding_row(api.db_file)["mode"] == "interval"


def test_put_empty_times_with_paused_keeps_interval_paused(api: Api) -> None:
    """0 个时刻 + 暂停：写 interval 绑定并保留暂停标志，且不排下一槽（评审补测）。"""
    data = api.data(api.save({"times": [], "paused": True}))
    assert data["mode"] == "interval"
    assert data["times"] == []
    assert data["paused"] is True
    assert data["nextRunAt"] is None
    # 真实落库：interval 的暂停标志不会被静默清掉。
    assert _binding_row(api.db_file) == {"mode": "interval", "times": "[]", "paused": 1}
    # GET 与 PUT 同形状。
    assert api.data(api.binding()) == data
    # 恢复：同一请求把 paused 置回 False，仍是 interval。
    resumed = api.data(api.save({"times": [], "paused": False}))
    assert resumed["mode"] == "interval"
    assert resumed["paused"] is False
    assert resumed["nextRunAt"] is None


def test_paused_fixed_binding_has_no_next_run_until_resumed(api: Api) -> None:
    paused = api.data(api.save({"times": ["09:00", "16:00"], "paused": True}))
    assert paused["mode"] == "fixed"
    assert paused["times"] == ["09:00", "16:00"]
    assert paused["paused"] is True
    assert paused["nextRunAt"] is None
    assert _binding_row(api.db_file)["paused"] == 1

    resumed = api.data(api.save({"times": ["09:00", "16:00"], "paused": False}))
    assert resumed["paused"] is False
    assert resumed["nextRunAt"] == "2024-05-06T16:00:00+08:00"


# ── 2b. 页面声明：manifest 页面/nav + 真实静态模块 ───────────────────────────


def test_plugin_manifest_declares_the_schedule_page_and_serves_the_module(api: Api) -> None:
    manifest = api.client.get("/api/host/manifest").get_json()["data"]
    record = next(item for item in manifest["plugins"] if item["id"] == PLUGIN_ID)
    assert record["status"] == "loaded", record.get("error")
    assert record["pages"] == [
        {"id": "schedule", "title": "调度时刻", "kind": "module", "module": "schedule.js"}
    ]
    # nav 挂在「工具」下，按现有插件惯例只在专家模式显示。
    assert [entry for entry in manifest["nav"] if entry["plugin"] == PLUGIN_ID] == [
        {
            "plugin": PLUGIN_ID,
            "title": "调度时刻",
            "page": "schedule",
            "order": 55,
            "expert": True,
            "parent": "workbench/tools",
        }
    ]
    static = api.client.get(f"/plugins/{PLUGIN_ID}/static/schedule.js")
    assert static.status_code == 200
    assert "javascript" in static.headers["Content-Type"]
    assert b"SchedulePage" in static.data


# ── 3. 校验：字段级 400，且失败不落库 ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"times": ["25:00"], "paused": False}, "times[0]"),
        ({"times": ["0900"], "paused": False}, "times[0]"),
        ({"times": ["09:00", 9], "paused": False}, "times[1]"),
        ({"times": "09:00", "paused": False}, "times"),
        ({"times": ["09:00"], "paused": "yes"}, "paused"),
    ],
)
def test_invalid_binding_payload_is_400_with_field_level_message(
    api: Api, body: dict[str, Any], field: str
) -> None:
    response = api.save(body)
    assert response.status_code == 400
    assert response.headers["Cache-Control"] == "no-store"
    error = response.get_json()["error"]
    assert error["type"] == "ValidationError"
    assert error["message"].startswith(field), error["message"]
    # 校验失败不写库。
    assert _binding_row(api.db_file) is None


def test_non_object_body_is_400(api: Api) -> None:
    response = api.client.put(
        f"/api/p/{PLUGIN_ID}/binding/{PROJECT}",
        data="[]",
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["type"] == "ValidationError"
    assert _binding_row(api.db_file) is None


# ── 4. 当天槽摘要：状态/错误码可见，租约凭据不外露 ───────────────────────────


def test_today_rows_never_expose_lease_credentials(api: Api) -> None:
    api.data(api.save({"times": ["09:00"], "paused": False}))
    store = _store(api.db_file)
    store.ensure_slots([sp.SlotKey(PROJECT, JOB, NOW.date(), time(9, 0))])
    leased = store.lease_next("tray", lease_seconds=300, business_date=NOW.date())
    assert leased is not None and leased["leaseToken"]

    data = api.data(api.binding())
    assert [row["scheduledTime"] for row in data["today"]] == ["09:00"]
    row = data["today"][0]
    assert row["status"] == "leased"
    assert row["attempt"] == 1
    assert row["lastErrorCode"] is None
    # 字段整体缺席，与取值无关。
    assert set(row) == {"scheduledTime", "status", "attempt", "lastErrorCode"}

    # 库内确实有租约值：上面的「不外露」不是空断言。
    raw = _slot_row(api.db_file, "09:00")
    assert raw["lease_owner"] == "tray"
    assert raw["lease_token"] == leased["leaseToken"]

    # 失败槽的错误码可见（界面据此显示失败原因）。
    assert store.finish(
        sp.SlotKey(PROJECT, JOB, NOW.date(), time(9, 0)),
        leased["leaseToken"],
        ok=False,
        error_code="sync_failed",
    )
    failed = api.data(api.binding())["today"][0]
    assert failed["status"] == "failed"
    assert failed["lastErrorCode"] == "sync_failed"


# ── 5. 写路由先过 local_guard（stub host，证明顺序） ─────────────────────────


def _plugin_backend() -> Any:
    """按宿主装载方式取插件后端模块（同包名 ``vse_plugins.<id>``）。"""
    namespace = sys.modules.get("vse_plugins")
    if namespace is None:
        namespace = types.ModuleType("vse_plugins")
        namespace.__path__ = []  # type: ignore[attr-defined]
        sys.modules["vse_plugins"] = namespace
    package_name = "vse_plugins.sync_control"
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(PLUGIN_DIR)]  # type: ignore[attr-defined]
        sys.modules[package_name] = package
    return importlib.import_module(f"{package_name}.backend")


class _StubHost:
    """最小 host 替身：真实 HostContext + 真实迁移 + 真实 blueprint。"""

    def __init__(self, context: HostContext, blueprint: Blueprint, prefix: str) -> None:
        self.context = context
        self.blueprint = blueprint
        self.table_prefix = prefix

    def migrate(self, steps: Any) -> Any:
        return self.context.db.apply_plugin_migrations("sync-control", steps)


def test_write_route_asks_local_guard_before_touching_storage(tmp_path: Path) -> None:
    db = DatabaseManager(db_path=tmp_path / "guard.db")
    db.init_database()
    guard_calls: list[int] = []

    def local_guard():
        guard_calls.append(1)
        return (
            jsonify({"ok": False, "error": {"type": "LocalAccessRequired", "message": "此操作仅允许从本机访问"}}),
            403,
        )

    context = HostContext(
        db=db,
        data_dir=tmp_path,
        json_ok=lambda data=None, status=200: (jsonify({"ok": True, "data": data}), status),
        json_error=lambda status, error_type, message: (
            jsonify({"ok": False, "error": {"type": error_type, "message": message}}),
            status,
        ),
        local_guard=local_guard,
    )
    blueprint = Blueprint("plugin_sync_control_stub", __name__, url_prefix=f"/api/p/{PLUGIN_ID}")
    host = _StubHost(context, blueprint, PREFIX)
    _plugin_backend().register(host)

    app = Flask(__name__)
    app.register_blueprint(blueprint)
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.put(
        f"/api/p/{PLUGIN_ID}/binding/{PROJECT}", json={"times": ["09:00"], "paused": False}
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["type"] == "LocalAccessRequired"
    # 守卫被调用一次，且拒绝发生在写库之前。
    assert guard_calls == [1]
    assert _binding_row(tmp_path / "guard.db") is None


# ── 6. 无会话写被拒（原生客户端，不装已认证替身） ───────────────────────────


@pytest.mark.raw_security
def test_write_without_local_session_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app, db_file = _make_app(monkeypatch, tmp_path)
    client = app.test_client()
    response = client.put(
        f"/api/p/{PLUGIN_ID}/binding/{PROJECT}",
        json={"times": ["09:00"], "paused": False},
        headers={"Origin": "http://localhost"},
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["type"] == "SessionRequired"
    assert _binding_row(db_file) is None


# ── 7. 前端：Node VM 中执行真实页面模块 ──────────────────────────────────────

_RUNNER_JS = r"""
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import * as vm from "node:vm";

const [, SCHEDULE_JS, API_JS, UIKIT_JS, TIME_JS, SCENARIO_JSON] = process.argv;
const scenario = JSON.parse(SCENARIO_JSON);

// ---- 假 fetch：记录真实请求（method/url/body），按场景返回宿主信封 ----------
const requests = [];

function specFor(method, url) {
  if (method === "PUT") {
    if (Array.isArray(scenario.put)) {
      if (!scenario.put.length) throw new Error("没有更多 PUT 预置响应: " + url);
      return scenario.put.shift();
    }
    return scenario.put;
  }
  if (url.indexOf("/api/p/workbench/projects") === 0) return scenario.projects;
  if (url.indexOf("/api/p/sync-control/binding") === 0) return scenario.binding;
  return null;
}

async function fakeFetch(url, init) {
  const options = init || {};
  const method = String(options.method || "GET").toUpperCase();
  const target = String(url);
  requests.push({
    method,
    url: target,
    body: options.body === undefined ? null : JSON.parse(options.body),
  });
  const spec = specFor(method, target);
  if (!spec) throw new Error("未预置的请求: " + method + " " + target);
  if (spec.network) throw new Error("本地服务未启动");
  const status = spec.status === undefined ? 200 : spec.status;
  return {
    ok: status < 400,
    status,
    async json() {
      return spec.body === undefined ? null : spec.body;
    },
  };
}

// ---- 最小 hook 运行时（useState / useEffect / useRef，可重渲染）-------------
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

function htmlStub(strings, ...values) {
  return { __template: true, strings: Array.from(strings), values };
}

// ---- 载入真实模块（只有 preact-htm 是替身）---------------------------------
const context = vm.createContext({
  console: { log() {}, warn() {}, error() {}, info() {} },
  setTimeout: (fn) => setTimeout(fn, 0),
  clearTimeout,
  fetch: fakeFetch,
  Date,
  Intl,
  Promise,
  JSON,
  Math,
  Object,
  Array,
  String,
  Number,
  Boolean,
  RegExp,
  Error,
  Map,
  Set,
  encodeURIComponent,
  decodeURIComponent,
  window: {},
});

function realModule(path) {
  return new vm.SourceTextModule(readFileSync(path, "utf8"), {
    context,
    identifier: pathToFileURL(path).href,
  });
}

const mods = {
  schedule: realModule(SCHEDULE_JS),
  api: realModule(API_JS),
  uikit: realModule(UIKIT_JS),
  time: realModule(TIME_JS),
};

const preact = new vm.SyntheticModule(
  ["html", "useState", "useEffect", "useRef", "useCallback", "useMemo"],
  function () {
    this.setExport("html", htmlStub);
    this.setExport("useState", useState);
    this.setExport("useEffect", useEffect);
    this.setExport("useRef", useRef);
    this.setExport("useCallback", (fn) => fn);
    this.setExport("useMemo", (fn) => fn());
  },
  { context }
);

async function linker(specifier) {
  if (specifier.indexOf("preact-htm") !== -1) return preact;
  if (specifier.endsWith("/api.js")) return mods.api;
  if (specifier.endsWith("/ui-kit.js")) return mods.uikit;
  if (specifier.endsWith("/time-format.js")) return mods.time;
  throw new Error("未预期的 import: " + specifier);
}

// 只 link 入口模块：链接器返回的真实模块会被 VM 递归 link（重复 link 会抛错）。
await mods.schedule.link(linker);
await mods.schedule.evaluate();
const exports = mods.schedule.namespace;

// ---- 渲染模型：展开嵌套组件，把模板摊平成标记串并解析成元素 -----------------
const COMPONENT_ATTR = /([A-Za-z_][\w-]*)=\s*"?$/;

function componentProps(node) {
  const out = {};
  for (let i = 1; i < node.values.length; i++) {
    const match = COMPONENT_ATTR.exec(node.strings[i] || "");
    if (match) out[match[1]] = node.values[i];
  }
  return out;
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
    if (typeof node === "string" || typeof node === "number") {
      parts.push(String(node));
      return;
    }
    if (Array.isArray(node)) {
      node.forEach(visit);
      return;
    }
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
  const resolve = (value) =>
    String(value).replace(/\u0000(\d+)\u0000/g, (_all, i) => {
      const item = values[Number(i)];
      if (item === null || item === undefined || typeof item === "boolean" || typeof item === "function") return "";
      return String(item);
    });
  const elements = [];
  let match;
  TAG_RE.lastIndex = 0;
  while ((match = TAG_RE.exec(markup))) {
    const attrs = {};
    let attr;
    ATTR_RE.lastIndex = 0;
    while ((attr = ATTR_RE.exec(match[2]))) {
      let value = true;
      if (attr[4] !== undefined) value = values[Number(attr[4])];
      else if (attr[2] !== undefined) value = resolve(attr[2]);
      else if (attr[3] !== undefined) value = resolve(attr[3]);
      attrs[attr[1]] = value;
    }
    elements.push({ tag: match[1].toLowerCase(), attrs });
  }
  return { elements, markup, values, resolve };
}

function visibleText() {
  const { markup, values } = renderMarkup(tree);
  return markup
    .replace(/<[^>]*>/g, "")
    .replace(/\u0000(\d+)\u0000/g, (_all, i) => {
      const value = values[Number(i)];
      if (value === null || value === undefined || typeof value === "boolean" || typeof value === "function") return "";
      return String(value);
    })
    .replace(/\s+/g, " ");
}

// ---- 渲染与稳定 ------------------------------------------------------------
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

function elements() {
  return rendered().elements;
}

function timeInputs() {
  return elements().filter((el) => el.tag === "input" && el.attrs["data-time-index"] !== undefined);
}

function findAction(action, index) {
  return elements().filter((el) => {
    if (el.attrs["data-action"] !== action) return false;
    if (index === undefined) return true;
    return String(el.attrs["data-time-index"]) === String(index);
  })[0];
}

function snapshot() {
  const all = elements();
  const pause = all.filter((el) => el.attrs["data-action"] === "toggle-pause")[0];
  const saveError = all.filter((el) => el.attrs["data-role"] === "save-error")[0];
  return {
    text: visibleText(),
    inputs: timeInputs().map((el) => ({ index: el.attrs["data-time-index"], value: el.attrs.value })),
    paused: pause ? pause.attrs.checked === true : null,
    actions: all
      .filter((el) => typeof el.attrs["data-action"] === "string")
      .map((el) => ({ action: el.attrs["data-action"], disabled: el.attrs.disabled === true })),
    runs: all
      .filter((el) => el.tag === "li" && el.attrs["data-status"] !== undefined)
      .map((el) => ({
        status: el.attrs["data-status"],
        time: el.attrs["data-scheduled-time"],
        tone: el.attrs["data-tone"],
      })),
    saveError: saveError ? { field: saveError.attrs["data-field"] } : null,
    requests: requests.map((item) => ({ method: item.method, url: item.url, body: item.body })),
  };
}

// ---- 场景 ------------------------------------------------------------------
const out = { snapshots: {}, results: {} };

function runHelpers() {
  const cases = scenario.cases || {};
  out.results.normalize = (cases.normalize || []).map((value) => exports.normalizeTimeText(value));
  out.results.invalid = (cases.invalid || []).map((value) => exports.isInvalidTime(value));
  out.results.payload = (cases.payload || []).map((values) => exports.payloadTimes(values));
  out.results.nextRun = (cases.nextRun || []).map((data) => exports.nextRunText(data));
  out.results.mode = (cases.mode || []).map((data) => exports.modeText(data));
  out.results.today = (cases.today || []).map((item) => exports.todayRows(item.data, item.nowMs));
  out.results.labels = exports.STATUS_LABELS;
  out.results.tones = exports.STATUS_TONES;
  out.results.draft = (cases.draft || []).map((data) => exports.bindingDraft(data));
}

async function runSteps() {
  for (const step of scenario.steps || []) {
    if (step.type === "input") {
      const inputs = timeInputs();
      if (!inputs[step.index]) throw new Error("没有第 " + step.index + " 个时刻输入框");
      inputs[step.index].attrs.onInput({ currentTarget: { value: step.value } });
    } else if (step.type === "toggle") {
      const target = findAction("toggle-pause");
      if (!target) throw new Error("未找到暂停开关");
      target.attrs.onChange({ currentTarget: { checked: !target.attrs.checked } });
    } else if (step.type === "click") {
      const target = findAction(step.action, step.index);
      if (!target) throw new Error("未找到按钮: " + JSON.stringify(step));
      if (target.attrs.disabled === true) throw new Error("按钮被禁用: " + JSON.stringify(step));
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
} else if (scenario.action === "page") {
  hooks.slots = [];
  hooks.effects = {};
  hooks.pending = [];
  hooks.cursor = 0;
  component = exports.default;
  props = { plugin: { id: "sync-control", version: "0.2.0" }, nowMs: scenario.nowMs };
  await settle();
  out.snapshots.mounted = snapshot();
  await runSteps();
} else {
  throw new Error("unknown action: " + scenario.action);
}

console.log(JSON.stringify(out));
"""


def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    result = subprocess.run([node, "--version"], capture_output=True, text=True, check=False)
    text = (result.stdout or "").strip()
    if not text.startswith("v"):
        return 0
    try:
        return int(text[1:].split(".", 1)[0])
    except ValueError:
        return 0


needs_node = pytest.mark.skipif(
    _node_major() < 22,
    reason="需要 Node 22+（--experimental-vm-modules 执行真实页面模块）",
)


def _run_node(scenario: dict[str, Any], *, timeout: int = 120) -> dict[str, Any]:
    node = shutil.which("node")
    assert node is not None, "未找到 Node.js 命令：前端页面模块必须在 Node VM 中真实执行"
    result = subprocess.run(
        [
            node,
            "--experimental-vm-modules",
            "--input-type=module",
            "-e",
            _RUNNER_JS,
            str(SCHEDULE_JS),
            str(API_JS),
            str(UIKIT_JS),
            str(TIME_FORMAT_JS),
            json.dumps(scenario, ensure_ascii=False),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=timeout,
    )
    assert result.returncode == 0, (
        f"Node 执行失败 (code {result.returncode}):\n{result.stderr[-4000:]}\n{result.stdout[-2000:]}"
    )
    lines = [line.strip() for line in (result.stdout or "").strip().splitlines() if line.strip().startswith("{")]
    assert lines, f"Node 未输出结果行：\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
    return json.loads(lines[-1])


def _projects_ok(active: str = PROJECT, name: str = "示例项目") -> dict[str, Any]:
    return {
        "body": {
            "ok": True,
            "data": {
                "managed": False,
                "active": active,
                "projects": [{"id": active, "name": name, "active": True}],
            },
        }
    }


def _binding_body(
    *,
    mode: str = "fixed",
    times: list[str] | None = None,
    paused: bool = False,
    next_run_at: str | None = "2024-05-06T16:00:00+08:00",
    today: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "projectId": PROJECT,
            "jobId": JOB,
            "mode": mode,
            "times": [] if times is None else times,
            "paused": paused,
            "nextRunAt": next_run_at,
            "today": [] if today is None else today,
        },
    }


@needs_node
def test_frontend_helpers_normalize_and_describe() -> None:
    out = _run_node(
        {
            "action": "helpers",
            "cases": {
                "normalize": ["9:00", "09:00", " 7:5 ", "24:00", "0930", "", None],
                "invalid": ["9:00", "25:00", "", None],
                "payload": [["16:00", "9:00", "09:00", "", "  "], ["25:00"], []],
                "nextRun": [
                    {"mode": "off", "times": [], "paused": False, "nextRunAt": None},
                    {"mode": "fixed", "times": ["09:00"], "paused": True, "nextRunAt": None},
                    {
                        "mode": "fixed",
                        "times": ["09:00", "16:00"],
                        "paused": False,
                        "nextRunAt": "2024-05-06T16:00:00+08:00",
                    },
                    {"mode": "interval", "times": [], "paused": False, "nextRunAt": None},
                ],
                "mode": [
                    {"mode": "fixed", "times": ["09:00", "16:00"]},
                    {"mode": "interval", "times": []},
                    {"mode": "off", "times": []},
                ],
                "today": [
                    {
                        "nowMs": NOW_MS,
                        "data": {
                            "today": [
                                {"scheduledTime": "09:00", "status": "pending", "attempt": 1, "lastErrorCode": None},
                                {"scheduledTime": "10:30", "status": "pending", "attempt": 0, "lastErrorCode": None},
                                {"scheduledTime": "09:00", "status": "failed", "attempt": 2, "lastErrorCode": "sync_failed"},
                                {"scheduledTime": "09:00", "status": "paused_skipped", "attempt": 0, "lastErrorCode": None},
                                {"scheduledTime": "09:00", "status": "expired", "attempt": 0, "lastErrorCode": None},
                                {"scheduledTime": "09:00", "status": "succeeded", "attempt": 1, "lastErrorCode": None},
                                {"scheduledTime": "09:00", "status": "leased", "attempt": 1, "lastErrorCode": None},
                            ]
                        },
                    }
                ],
                "draft": [
                    {"mode": "fixed", "times": ["09:00", "16:00"], "paused": True},
                    {"mode": "off", "times": [], "paused": False},
                ],
            },
        }
    )
    results = out["results"]
    assert results["normalize"] == ["09:00", "09:00", None, None, None, None, None]
    assert results["invalid"] == [False, True, False, False]
    # 前端不替后端规范化：原样提交，去重/升序/非法判定都以后端为准。
    assert results["payload"] == [["16:00", "9:00", "09:00"], ["25:00"], []]
    assert results["nextRun"] == [
        "未开启固定时刻，当前按间隔同步",
        "已暂停，恢复后才排下一槽",
        "2024-05-06 16:00（北京时间）",
        "未开启固定时刻，当前按间隔同步",
    ]
    assert results["mode"] == [
        "固定时刻 · 共 2 个：09:00、16:00",
        "间隔同步（未开启固定时刻）",
        "未配置调度绑定",
    ]
    rows = results["today"][0]
    assert [(row["statusText"], row["tone"]) for row in rows] == [
        ("待执行", "warn"),
        ("待执行", "warn"),
        ("失败", "bad"),
        ("暂停跳过", "off"),
        ("已过期", "off"),
        ("已完成", "ok"),
        ("执行中", "warn"),
    ]
    assert rows[0]["catchUp"] is True
    assert "已过点，等待补跑" in rows[0]["detail"]
    assert rows[1]["catchUp"] is False and rows[1]["detail"] == ""
    assert rows[2]["detail"] == "第 2 次尝试 · 错误码 sync_failed"
    # 状态色来自宿主 ui-kit 的 TONE 四色（schedule.js 的 STATUS_TONES 用它构造）。
    assert results["tones"] == {
        "pending": "warn",
        "leased": "warn",
        "succeeded": "ok",
        "failed": "bad",
        "paused_skipped": "off",
        "expired": "off",
    }
    assert results["labels"]["paused_skipped"] == "暂停跳过"
    assert results["draft"] == [
        {"times": ["09:00", "16:00"], "paused": True},
        {"times": [""], "paused": False},
    ]


@needs_node
def test_frontend_off_state_and_today_list() -> None:
    out = _run_node(
        {
            "action": "page",
            "nowMs": NOW_MS,
            "projects": _projects_ok(),
            "binding": {
                "body": _binding_body(
                    mode="off",
                    times=[],
                    next_run_at=None,
                    today=[
                        {"scheduledTime": "09:00", "status": "pending", "attempt": 1, "lastErrorCode": None},
                        {"scheduledTime": "09:00", "status": "failed", "attempt": 2, "lastErrorCode": "sync_failed"},
                    ],
                )
            },
            "steps": [],
        }
    )
    mounted = out["snapshots"]["mounted"]
    assert "未开启固定时刻，当前按间隔同步" in mounted["text"]
    assert "当前项目：示例项目" in mounted["text"]
    assert "已过点，等待补跑" in mounted["text"]
    assert "错误码 sync_failed" in mounted["text"]
    assert mounted["runs"] == [
        {"status": "pending", "time": "09:00", "tone": "warn"},
        {"status": "failed", "time": "09:00", "tone": "bad"},
    ]
    # off 态没有时刻：给一个空输入框供填写，不显示旧时刻。
    assert mounted["inputs"] == [{"index": 0, "value": ""}]
    assert mounted["paused"] is False
    # 真实读取顺序：先当前项目，再该项目的绑定。
    assert [item["method"] for item in mounted["requests"]] == ["GET", "GET"]
    assert mounted["requests"][0]["url"] == "/api/p/workbench/projects"
    assert mounted["requests"][1]["url"] == f"/api/p/sync-control/binding?projectId={PROJECT}"


@needs_node
def test_frontend_add_remove_times_and_save_refreshes() -> None:
    out = _run_node(
        {
            "action": "page",
            "nowMs": NOW_MS,
            "projects": _projects_ok(),
            "binding": {"body": _binding_body(times=["09:00"], next_run_at="2024-05-06T16:00:00+08:00")},
            "put": {
                "body": _binding_body(
                    times=["08:30", "16:00"], next_run_at="2024-05-06T16:00:00+08:00"
                )
            },
            "steps": [
                {"type": "click", "action": "add-time"},
                {"type": "input", "index": 0, "value": "08:30"},
                {"type": "input", "index": 1, "value": "16:00"},
                {"type": "snapshot", "label": "before-save"},
                {"type": "click", "action": "save"},
                {"type": "snapshot", "label": "after-save"},
                {"type": "click", "action": "add-time"},
                {"type": "input", "index": 2, "value": "07:15"},
                {"type": "click", "action": "remove-time", "index": 1},
                {"type": "snapshot", "label": "after-remove"},
            ],
        }
    )
    snapshots = out["snapshots"]
    assert snapshots["mounted"]["inputs"] == [{"index": 0, "value": "09:00"}]
    assert snapshots["before-save"]["inputs"] == [
        {"index": 0, "value": "08:30"},
        {"index": 1, "value": "16:00"},
    ]
    # 保存走真实 PUT，body 是用户输入（未在前端规范化）。
    put_calls = [item for item in snapshots["after-save"]["requests"] if item["method"] == "PUT"]
    assert len(put_calls) == 1
    assert put_calls[0]["url"] == f"/api/p/sync-control/binding/{PROJECT}"
    assert put_calls[0]["body"] == {"times": ["08:30", "16:00"], "paused": False}
    # 保存成功后界面用服务端返回刷新。
    assert "已保存固定时刻" in snapshots["after-save"]["text"]
    assert snapshots["after-save"]["inputs"] == [
        {"index": 0, "value": "08:30"},
        {"index": 1, "value": "16:00"},
    ]
    assert snapshots["after-save"]["saveError"] is None
    # 增删时刻：新增第三行后删除第二行。
    assert snapshots["after-remove"]["inputs"] == [
        {"index": 0, "value": "08:30"},
        {"index": 1, "value": "07:15"},
    ]


@needs_node
def test_frontend_save_failure_keeps_inputs_and_shows_backend_message() -> None:
    out = _run_node(
        {
            "action": "page",
            "nowMs": NOW_MS,
            "projects": _projects_ok(),
            "binding": {"body": _binding_body(times=["09:00"])},
            "put": {
                "status": 400,
                "body": {
                    "ok": False,
                    "error": {
                        "type": "ValidationError",
                        "message": "times[1] 无法解析的时刻: '25:99'，应为 'HH:MM' 或 'HH:MM:SS'",
                    },
                },
            },
            "steps": [
                {"type": "input", "index": 0, "value": "07:15"},
                {"type": "click", "action": "add-time"},
                {"type": "input", "index": 1, "value": "25:99"},
                {"type": "snapshot", "label": "before-save"},
                {"type": "click", "action": "save"},
                {"type": "snapshot", "label": "after-save"},
            ],
        }
    )
    snapshots = out["snapshots"]
    # 前端只做格式提示：非法值照样提交，由后端裁决。
    assert snapshots["before-save"]["text"].count("格式应为 HH:MM") == 1
    assert snapshots["after-save"]["saveError"] == {"field": "times"}
    assert "times[1] 无法解析的时刻" in snapshots["after-save"]["text"]
    # 原位报错：用户输入完整保留，没有被清空或规范化。
    assert snapshots["after-save"]["inputs"] == [
        {"index": 0, "value": "07:15"},
        {"index": 1, "value": "25:99"},
    ]
    assert snapshots["after-save"]["text"].count("已保存") == 0


@needs_node
def test_frontend_pause_and_resume_round_trip() -> None:
    out = _run_node(
        {
            "action": "page",
            "nowMs": NOW_MS,
            "projects": _projects_ok(),
            "binding": {"body": _binding_body(times=["09:00", "16:00"])},
            "put": [
                {
                    "body": _binding_body(
                        times=["09:00", "16:00"], paused=True, next_run_at=None
                    )
                },
                {"body": _binding_body(times=["09:00", "16:00"], paused=False)},
            ],
            "steps": [
                {"type": "toggle"},
                {"type": "snapshot", "label": "paused-draft"},
                {"type": "click", "action": "save"},
                {"type": "snapshot", "label": "paused-saved"},
                {"type": "toggle"},
                {"type": "click", "action": "save"},
                {"type": "snapshot", "label": "resumed"},
            ],
        }
    )
    snapshots = out["snapshots"]
    assert snapshots["mounted"]["paused"] is False
    assert snapshots["paused-draft"]["paused"] is True
    paused_put = [item for item in snapshots["paused-saved"]["requests"] if item["method"] == "PUT"][-1]
    assert paused_put["body"] == {"times": ["09:00", "16:00"], "paused": True}
    assert "已暂停，恢复后才排下一槽" in snapshots["paused-saved"]["text"]
    resumed_put = [item for item in snapshots["resumed"]["requests"] if item["method"] == "PUT"][-1]
    assert resumed_put["body"] == {"times": ["09:00", "16:00"], "paused": False}
    assert "2024-05-06 16:00（北京时间）" in snapshots["resumed"]["text"]
    assert snapshots["resumed"]["paused"] is False


@needs_node
def test_frontend_paused_interval_binding_shows_interval_mode() -> None:
    """interval + paused：界面仍按「间隔同步」显示，暂停开关保持已勾选（评审补测）。"""
    out = _run_node(
        {
            "action": "page",
            "nowMs": NOW_MS,
            "projects": _projects_ok(),
            "binding": {
                "body": _binding_body(mode="interval", times=[], paused=True, next_run_at=None)
            },
            "put": {
                "body": _binding_body(
                    mode="interval", times=[], paused=False, next_run_at=None
                )
            },
            "steps": [
                {"type": "snapshot", "label": "paused-interval"},
                {"type": "toggle"},
                {"type": "click", "action": "save"},
                {"type": "snapshot", "label": "resumed"},
            ],
        }
    )
    snapshots = out["snapshots"]
    mounted = snapshots["paused-interval"]
    # 暂停标志被如实回显，但模式文案仍明确「未开启固定时刻」。
    assert mounted["paused"] is True
    assert "未开启固定时刻，当前按间隔同步" in mounted["text"]
    assert "间隔同步（未开启固定时刻）" in mounted["text"]
    assert mounted["inputs"] == [{"index": 0, "value": ""}]
    # 取消暂停并保存：times 仍为空 -> 继续写 interval，paused=false。
    put_calls = [item for item in snapshots["resumed"]["requests"] if item["method"] == "PUT"]
    assert put_calls[-1]["body"] == {"times": [], "paused": False}
    assert snapshots["resumed"]["paused"] is False


@needs_node
def test_frontend_unconfigured_project_state() -> None:
    out = _run_node(
        {
            "action": "page",
            "nowMs": NOW_MS,
            "projects": {
                "status": 500,
                "body": {"ok": False, "error": {"type": "ServerError", "message": "boom"}},
            },
            "steps": [],
        }
    )
    mounted = out["snapshots"]["mounted"]
    assert "未配置项目" in mounted["text"]
    # 读不到当前项目就不再请求绑定接口。
    assert [item["method"] for item in mounted["requests"]] == ["GET"]
    assert mounted["inputs"] == []
