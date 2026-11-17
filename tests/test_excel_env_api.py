# -*- coding: utf-8 -*-
"""Excel 环境自检 API 与页面接线的契约测试（DSH-V2-25）。

覆盖要求：
1. 走真实 create_app 与真实插件加载，发起 GET /api/p/excel-tasks/env-check；
   探测器一律用假实现注入，绝不读真实注册表或真实进程列表；
2. 已安装+激活 / 已安装+无法确认激活(need_check) / 未安装 / 探测抛异常(500) /
   服务缺失(501) / 响应 no-store；
3. 插件 backend 源码不得 import services.* 或 web.*（只经 host.context 取服务）；
4. 只读契约：没有任何结束进程的代码路径（subprocess/os.kill 桩一旦被调用即失败）；
5. 用 Node 实际执行 workspace.js 导出的转换函数 + logic.js 的 classifyEnvStatus，
   证明 need_check → 「需要检查」、请求失败 → 非「正常」。
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

import web.app as web_app
from core.db_manager import DatabaseManager

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO_ROOT / "plugins" / "excel_tasks"
PLUGIN_BACKEND = PLUGIN_DIR / "backend.py"
STATIC_DIR = PLUGIN_DIR / "static"
ENV_CHECK_RULE = "/api/p/excel-tasks/env-check"

ACTIVATED_RESULT = {
    "installed": True,
    "install_state": "installed",
    "excel_path": r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",
    "version": "16.0",
    "activation": {"state": "activated", "text": "已激活", "detail": "软件授权正常"},
    "residual_processes": [],
    "residual_count": 0,
}

NEED_CHECK_RESULT = {
    "installed": True,
    "install_state": "installed",
    "excel_path": r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",
    "version": "16.0",
    "activation": {
        "state": "need_check",
        "text": "需要检查",
        "detail": "无法可靠确认激活状态，请在软件账户信息中核对",
    },
    "residual_processes": [],
    "residual_count": 0,
}

NOT_INSTALLED_RESULT = {
    "installed": False,
    "install_state": "not_installed",
    "excel_path": None,
    "version": None,
    "activation": {"state": "need_check", "text": "需要检查", "detail": "未检测到可用的表格软件"},
    "residual_processes": [],
    "residual_count": 0,
}


@pytest.fixture()
def env_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """真实 create_app（含真实插件加载），数据库与数据根目录隔离到 tmp。"""
    db = DatabaseManager(db_path=tmp_path / "excel_env_api.db")
    db.init_database()
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db)
    monkeypatch.setattr("core.runtime_paths.app_root", lambda: tmp_path)
    app = web_app.create_app(allowed_hosts=["aras.example"], tdc_allowed_hosts=["tdc.example"])
    app.config.update(TESTING=True)
    return app


@pytest.fixture()
def client(env_app):
    return env_app.test_client()


def _inject(app, detector) -> None:
    """替换宿主注入的服务实现（与生产同一映射，验证 E1 接线）。"""
    app.extensions["excel_env_check"] = detector


def _no_kill_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """任何结束进程的调用路径一旦被触发，测试立即失败。"""

    def _boom(*args: Any, **kwargs: Any):  # pragma: no cover - 触发即失败
        raise AssertionError(f"环境自检不得结束进程，却调用了: {args[:2]!r}")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(subprocess, "call", _boom)
    monkeypatch.setattr(subprocess, "check_output", _boom)
    monkeypatch.setattr(os, "kill", _boom)
    monkeypatch.setattr(os, "system", _boom)


# ── 1. 路由存在且为 GET ────────────────────────────────────────────


def test_env_check_route_registered_by_plugin(env_app) -> None:
    rules = {rule.rule: rule for rule in env_app.url_map.iter_rules()}
    assert ENV_CHECK_RULE in rules, f"插件未注册 {ENV_CHECK_RULE}"
    rule = rules[ENV_CHECK_RULE]
    assert "GET" in rule.methods
    assert not ({"POST", "PUT", "PATCH", "DELETE"} & set(rule.methods))
    assert rule.endpoint.startswith("plugin_excel_tasks."), rule.endpoint


# ── 2. 真实请求：四种检测结果 + 两种失败 ──────────────────────────


def test_env_check_installed_and_activated(env_app, client, monkeypatch) -> None:
    _no_kill_calls(monkeypatch)
    _inject(env_app, lambda: ACTIVATED_RESULT)

    resp = client.get(ENV_CHECK_RULE)
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["data"] == ACTIVATED_RESULT
    assert resp.headers["Cache-Control"] == "no-store"


def test_env_check_need_check_activation(env_app, client, monkeypatch) -> None:
    _no_kill_calls(monkeypatch)
    _inject(env_app, lambda: NEED_CHECK_RESULT)

    resp = client.get(ENV_CHECK_RULE)
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["installed"] is True
    assert data["activation"]["state"] == "need_check"
    assert data["activation"]["text"] == "需要检查"
    assert resp.headers["Cache-Control"] == "no-store"


def test_env_check_not_installed(env_app, client, monkeypatch) -> None:
    _no_kill_calls(monkeypatch)
    _inject(env_app, lambda: NOT_INSTALLED_RESULT)

    resp = client.get(ENV_CHECK_RULE)
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["installed"] is False
    assert data["install_state"] == "not_installed"
    assert resp.headers["Cache-Control"] == "no-store"


def test_env_check_detector_failure_returns_500_without_internals(env_app, client, monkeypatch) -> None:
    _no_kill_calls(monkeypatch)
    secret = "C:\\Users\\secret-probe\\env_probe.py"

    def _broken():
        raise RuntimeError(f"probe exploded at {secret}")

    _inject(env_app, _broken)

    resp = client.get(ENV_CHECK_RULE)
    assert resp.status_code == 500
    payload = resp.get_json()
    assert payload["ok"] is False
    assert payload["error"]["type"] == "EnvCheckFailed"
    body = resp.get_data(as_text=True)
    assert "secret-probe" not in body
    assert "RuntimeError" not in body
    assert "Traceback" not in body
    assert ".py" not in body
    # 用户可见文案必须是通俗中文
    assert payload["error"]["message"] == "环境自检没有完成，请稍后重试"
    assert resp.headers["Cache-Control"] == "no-store"


def test_env_check_service_missing_returns_501(env_app, client, monkeypatch) -> None:
    _no_kill_calls(monkeypatch)
    monkeypatch.delitem(env_app.extensions, "excel_env_check")

    resp = client.get(ENV_CHECK_RULE)
    assert resp.status_code == 501
    payload = resp.get_json()
    assert payload["ok"] is False
    assert payload["error"]["type"] == "EnvCheckUnavailable"
    assert payload["error"]["message"] == "环境自检暂时不可用，请重启程序后再试"
    assert resp.headers["Cache-Control"] == "no-store"


def test_env_check_uses_host_service_not_plugin_import(env_app, client, monkeypatch) -> None:
    """替换宿主服务即改变响应，证明数据确实来自 host.context.service。"""
    calls: list[str] = []

    def _detector():
        calls.append("called")
        return NOT_INSTALLED_RESULT

    _inject(env_app, _detector)
    assert client.get(ENV_CHECK_RULE).get_json()["data"]["installed"] is False

    _inject(env_app, lambda: ACTIVATED_RESULT)
    assert client.get(ENV_CHECK_RULE).get_json()["data"]["installed"] is True
    assert calls == ["called"]


# ── 3. 插件边界：只经 host.context，不 import services/web，不结束进程 ──


def test_plugin_backend_imports_no_services_or_web() -> None:
    source = PLUGIN_BACKEND.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(PLUGIN_BACKEND))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    offenders = [name for name in imported if name.split(".")[0] in {"services", "web"}]
    assert not offenders, f"插件不得直接 import 宿主模块: {offenders}"
    assert "ctx.service(" in source or "context.service(" in source
    assert "local_guard" not in source, "GET 只读路由不得调用本机写保护"


def test_plugin_backend_has_no_process_killing_path() -> None:
    source = PLUGIN_BACKEND.read_text(encoding="utf-8")
    banned = re.findall(r"(?i)taskkill|terminate\(|\bkill\b|Popen|subprocess", source)
    assert not banned, f"环境自检插件不得结束或枚举进程: {banned}"


def test_workspace_mounts_env_card_with_backend_data() -> None:
    """页面必须把接口数据交给 EnvCheckCard（不再是 env=${null} 静态占位）。"""
    source = (STATIC_DIR / "workspace.js").read_text(encoding="utf-8")
    assert ENV_CHECK_RULE in source
    assert "EnvCheckCard} env=${envCheck}" in source
    assert "onRefresh=${loadEnvCheck}" in source
    assert "EnvCheckCard} env=${null}" not in source
    # 挂载（refreshAll）、定义、刷新按钮三处都要触发同一加载函数
    assert source.count("loadEnvCheck") >= 3


# ── 4. Node 实际执行前端转换函数 ───────────────────────────────────


def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.match(r"v(\d+)", out.strip())
    return int(match.group(1)) if match else 0


_NODE_SCRIPT = r"""
import * as vm from "node:vm";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import path from "node:path";

const [, STATIC_DIR] = process.argv;

// workspace.js 的依赖全部用最小桩替代，只为执行它导出的纯转换函数。
const STUBS = {
  "/static/host/vendor/preact-htm.js":
    "export const html = () => null;\n" +
    "export const useCallback = (fn) => fn;\n" +
    "export const useEffect = () => undefined;\n" +
    "export const useRef = (value) => ({ current: value });\n" +
    "export const useState = (initial) => [typeof initial === 'function' ? initial() : initial, () => undefined];\n",
  "/static/host/expert.js": "export const expertStore = { get: () => false };\n",
  "/static/host/api.js":
    "export class ApiError extends Error {}\n" +
    "export const api = async () => ({});\n",
  "/static/host/kit.js":
    "export const DataTable = () => null;\n" +
    "export const StateBlock = () => null;\n" +
    "export const useStylesheet = () => undefined;\n",
  "./examples.js": "export const ExamplesDialog = () => null;\n",
  "./shared.js":
    "export const ACTIVE_TASK_STATES = [];\n" +
    "export const EnvCheckCard = () => null;\n" +
    "export const ErrorCard = () => null;\n" +
    "export const OPERATIONS = [];\n" +
    "export const STATUS_FILTERS = [];\n" +
    "export const StatusChip = () => null;\n" +
    "export const buildTaskPayload = () => ({});\n" +
    "export const display = (value) => (value === null || value === undefined || String(value).trim() === '' ? '-' : String(value));\n" +
    "export const formFromTask = () => ({});\n" +
    "export const formatDate = () => '-';\n" +
    "export const formatSize = () => '-';\n" +
    "export const newIdempotencyKey = () => 'key';\n" +
    "export const operationLabel = () => '-';\n",
};

const context = vm.createContext({ console, setTimeout, clearTimeout, Promise, JSON, Math, Date });

const linker = async (specifier) => {
  const stub = STUBS[specifier];
  if (stub === undefined) throw new Error("未预期的模块导入: " + specifier);
  return new vm.SourceTextModule(stub, { context });
};

const workspacePath = path.join(STATIC_DIR, "workspace.js");
const workspaceMod = new vm.SourceTextModule(readFileSync(workspacePath, "utf8"), {
  context,
  identifier: pathToFileURL(workspacePath).href,
});
await workspaceMod.link(linker);
await workspaceMod.evaluate();
const ws = workspaceMod.namespace;

const logic = await import(pathToFileURL(path.join(STATIC_DIR, "logic.js")).href);

const cases = {
  activated: ws.toEnvCardData({
    installed: true,
    install_state: "installed",
    activation: { state: "activated", detail: "软件授权正常" },
    residual_count: 0,
  }),
  needCheck: ws.toEnvCardData({
    installed: true,
    install_state: "installed",
    activation: { state: "need_check", detail: "无法可靠确认激活状态，请在软件账户信息中核对" },
    residual_count: 0,
  }),
  unknownActivationMissing: ws.toEnvCardData({ installed: true, activation: {}, residual_count: 0 }),
  unknownActivationValue: ws.toEnvCardData({ installed: true, activation: { state: "weird" }, residual_count: 0 }),
  installedFlagMissing: ws.toEnvCardData({ activation: { state: "activated" } }),
  notInstalled: ws.toEnvCardData({
    installed: false,
    install_state: "not_installed",
    activation: { state: "need_check", detail: "未检测到可用的表格软件" },
  }),
  unlicensed: ws.toEnvCardData({
    installed: true,
    activation: { state: "unlicensed", detail: "软件尚未激活或授权已过期" },
  }),
  residual: ws.toEnvCardData({
    installed: true,
    activation: { state: "activated", detail: "软件授权正常" },
    residual_count: 2,
  }),
  emptyPayload: ws.toEnvCardData(null),
  failure: ws.toEnvCardFailure(new Error("服务内部错误")),
  failureNoMessage: ws.toEnvCardFailure(null),
  checking: ws.envChecking(),
};

const out = {};
for (const [key, value] of Object.entries(cases)) {
  out[key] = { converted: value, rendered: logic.renderEnvStatus(value) };
}
console.log(JSON.stringify(out));
"""


def _run_node_env_conversion() -> dict:
    node = shutil.which("node")
    assert node is not None, "未找到 node 命令"
    result = subprocess.run(
        [node, "--experimental-vm-modules", "--input-type=module", "-e", _NODE_SCRIPT, str(STATIC_DIR)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, f"Node 执行失败:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    lines = [ln.strip() for ln in result.stdout.strip().splitlines() if ln.strip().startswith("{")]
    assert lines, f"Node 执行未输出有效 JSON:\n{result.stdout}"
    return json.loads(lines[-1])


@pytest.mark.skipif(_node_major() < 18, reason="需要 Node 18+ 运行 ES 模块测试（--experimental-vm-modules）")
def test_workspace_env_conversion_via_node() -> None:
    """Node 实际执行 workspace.js 的转换函数，再经 logic.js 分类渲染。"""
    data = _run_node_env_conversion()

    ok = data["activated"]
    assert ok["converted"]["state"] == "ok"
    assert ok["rendered"]["state"] == "ok"
    assert ok["rendered"]["label"] == "正常"

    for key in ("needCheck", "unknownActivationMissing", "unknownActivationValue", "installedFlagMissing"):
        item = data[key]
        assert item["converted"]["state"] == "need_check", f"{key} 转换结果异常: {item['converted']}"
        assert item["rendered"]["state"] == "need_check", f"{key} 渲染结果异常: {item['rendered']}"
        assert item["rendered"]["label"] == "需要检查"
        assert item["rendered"]["placeholder"] is False
        assert item["rendered"]["isPassed"] is False

    uninstalled = data["notInstalled"]
    assert uninstalled["rendered"]["state"] == "unavailable"
    assert uninstalled["rendered"]["label"] == "不可用"
    assert uninstalled["rendered"]["placeholder"] is False

    unlicensed = data["unlicensed"]
    assert unlicensed["rendered"]["state"] == "unavailable"
    assert unlicensed["rendered"]["isPassed"] is False

    residual = data["residual"]
    assert residual["rendered"]["state"] == "need_check"
    assert "2" in residual["rendered"]["description"]

    empty = data["emptyPayload"]
    assert empty["rendered"]["state"] == "need_check"
    assert empty["rendered"]["placeholder"] is False

    for key in ("failure", "failureNoMessage"):
        item = data[key]
        assert item["rendered"]["state"] != "ok", f"{key} 失败时不得显示正常: {item['rendered']}"
        assert item["rendered"]["label"] != "正常"
        assert item["rendered"]["isPassed"] is False
        assert item["rendered"]["placeholder"] is False, f"{key} 不得退回占位伪装成无数据"
        assert "失败" in item["rendered"]["description"] or "没有完成" in item["rendered"]["description"]

    checking = data["checking"]
    assert checking["rendered"]["placeholder"] is False
    assert checking["rendered"]["isPassed"] is False
