# -*- coding: utf-8 -*-
"""Excel 工具页前端 Node 夹具测试（W12-02A）。

门禁验证：
1. 环境检查三态分类与渲染函数（正常/绿、需要检查/黄、不可用/红、无后端占位/灰），
   断言无后端路由时显示占位说明且绝不伪造通过状态；
2. 页面错误展示统一接入 web/static/host/ui-kit.js 的 ErrorCard，
   断言结构包含「发生了什么 / 你需要做什么」、保留原始错误文案不变；
3. 用户可见文案合规门禁：无内部技术术语（JSON、Base URL、Worker、快照、取证）、
   无代码路径与 .py 脚本特征。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC = REPO_ROOT / "plugins" / "excel_tasks" / "static"
HOST_STATIC = REPO_ROOT / "web" / "static" / "host"


def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.match(r"v(\d+)", out.strip())
    return int(match.group(1)) if match else 0


pytestmark = pytest.mark.skipif(_node_major() < 22, reason="需要 Node 22+ 运行 ES 模块测试")


_NODE_TEST_SCRIPT = r"""
import * as vm from "node:vm";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import path from "node:path";

const [, STATIC_DIR, HOST_STATIC_DIR] = process.argv;

// 1. 纯逻辑模块动态导入测试
const logicUrl = pathToFileURL(path.join(STATIC_DIR, "logic.js")).href;
const logic = await import(logicUrl);

const out = {};

// 1.1 纯逻辑三态分类与渲染断言
out.logicTests = {
  // 正常（绿 / ok）
  normalFromData: logic.renderEnvStatus({
    installed: true,
    install_state: "installed",
    activation: { state: "activated", detail: "软件授权正常" },
    residual_count: 0,
  }),
  normalFromString: logic.renderEnvStatus("ok"),
  normalFromState: logic.renderEnvStatus({ state: "ok" }),

  // 需要检查（黄 / warn）
  needCheckFromData: logic.renderEnvStatus({
    installed: true,
    install_state: "installed",
    activation: { state: "need_check", detail: "无法可靠确认激活状态，请在软件账户信息中核对" },
    residual_count: 0,
  }),
  needCheckFromResidual: logic.renderEnvStatus({
    installed: true,
    activation: { state: "activated", detail: "软件授权正常" },
    residual_count: 3,
  }),
  needCheckFromString: logic.renderEnvStatus("need_check"),
  needCheckFromState: logic.renderEnvStatus({ state: "need_check" }),

  // 不可用（红 / bad）
  uninstalledFromData: logic.renderEnvStatus({
    installed: false,
    install_state: "not_installed",
    activation: { state: "need_check", detail: "未检测到可用的表格软件" },
  }),
  unlicensedFromData: logic.renderEnvStatus({
    installed: true,
    install_state: "installed",
    activation: { state: "unlicensed", detail: "软件尚未激活或授权已过期" },
  }),
  unavailableFromString: logic.renderEnvStatus("unavailable"),
  unavailableFromBadState: logic.renderEnvStatus({ state: "bad" }),

  // 占位情况（无后端/空/占位，绝不伪造通过状态）
  placeholderFromNull: logic.renderEnvStatus(null),
  placeholderFromUndefined: logic.renderEnvStatus(undefined),
  placeholderFromEmpty: logic.renderEnvStatus({}),
  placeholderFromFlag: logic.renderEnvStatus({ placeholder: true }),
  placeholderFromString: logic.renderEnvStatus("placeholder"),
};

// 1.2 错误文案格式化（验证原文保留）
const rawError = new Error("文件「demo.xlsx」读取失败：格式不兼容");
rawError.status = 422;
rawError.type = "ValidationError";
rawError.fields = { targetPath: "模板文件不存在" };

out.formatErrorWhat = logic.formatErrorWhat(rawError);
out.formatErrorTodoAuth = logic.formatErrorTodo({ status: 401 });
out.formatErrorTodoNormal = logic.formatErrorTodo(rawError);

// 2. Node VM 模块链接与组件渲染测试
const context = vm.createContext({
  console: { log() {}, warn() {}, error() {}, info() {} },
  setTimeout, clearTimeout,
  Promise, JSON, Math, Date, Object, Array, String, Number, Boolean, RegExp, Error,
  encodeURIComponent, decodeURIComponent,
  window: {
    openInPlaceLogin() {},
  },
});

async function linker(specifier, referencingModule) {
  if (specifier === "/static/host/vendor/preact-htm.js") {
    const filePath = path.join(HOST_STATIC_DIR, "vendor", "preact-htm.js");
    const code = readFileSync(filePath, "utf8");
    return new vm.SourceTextModule(code, {
      context,
      initializeImportMeta(meta) { meta.url = pathToFileURL(filePath).href; },
    });
  }
  if (specifier === "/static/host/ui-kit.js") {
    const filePath = path.join(HOST_STATIC_DIR, "ui-kit.js");
    const code = readFileSync(filePath, "utf8");
    const m = new vm.SourceTextModule(code, {
      context,
      initializeImportMeta(meta) { meta.url = pathToFileURL(filePath).href; },
    });
    await m.link(linker);
    return m;
  }
  if (specifier === "./vendor/preact-htm.js") {
    const filePath = path.join(HOST_STATIC_DIR, "vendor", "preact-htm.js");
    const code = readFileSync(filePath, "utf8");
    return new vm.SourceTextModule(code, {
      context,
      initializeImportMeta(meta) { meta.url = pathToFileURL(filePath).href; },
    });
  }
  if (specifier === "./logic.js") {
    const filePath = path.join(STATIC_DIR, "logic.js");
    const code = readFileSync(filePath, "utf8");
    return new vm.SourceTextModule(code, {
      context,
      initializeImportMeta(meta) { meta.url = pathToFileURL(filePath).href; },
    });
  }
  throw new Error("未预期的模块导入: " + specifier);
}

const sharedPath = path.join(STATIC_DIR, "shared.js");
const sharedCode = readFileSync(sharedPath, "utf8");
const sharedMod = new vm.SourceTextModule(sharedCode, {
  context,
  initializeImportMeta(meta) { meta.url = pathToFileURL(sharedPath).href; },
});
await sharedMod.link(linker);
await sharedMod.evaluate();
const shared = sharedMod.namespace;

// VNode 树递归序列化为 HTML 字符串
function vnodeToHtml(node) {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(vnodeToHtml).join("");
  if (typeof node.type === "function") {
    return vnodeToHtml(node.type(node.props || {}));
  }
  const tag = node.type;
  const props = node.props || {};
  let attrs = "";
  for (const [k, v] of Object.entries(props)) {
    if (k === "children" || k.startsWith("on") || v == null || v === false) continue;
    const name = k === "className" ? "class" : k;
    attrs += ` ${name}="${String(v)}"`;
  }
  const children = props.children ? vnodeToHtml(props.children) : "";
  return `<${tag}${attrs}>${children}</${tag}>`;
}

// 2.1 渲染 EnvCheckCard 各状态
out.envCardRenders = {
  // 正常（绿）
  ok: vnodeToHtml(shared.EnvCheckCard({
    env: { installed: true, activation: { state: "activated", detail: "软件授权正常" } }
  })),
  // 需要检查（黄）
  needCheck: vnodeToHtml(shared.EnvCheckCard({
    env: { installed: true, activation: { state: "need_check", detail: "无法确认激活状态" } }
  })),
  // 不可用（红）
  unavailable: vnodeToHtml(shared.EnvCheckCard({
    env: { installed: false, activation: { detail: "未检测到可用的表格软件" } }
  })),
  // 占位情况（灰）
  placeholder: vnodeToHtml(shared.EnvCheckCard({ env: null })),
};

// 2.2 渲染 ErrorCard（统一接入 ui-kit ErrorCard）
const renderedErrorCard = shared.ErrorCard({ error: rawError });
out.errorCardHtml = vnodeToHtml(renderedErrorCard);

const authErrorCard = shared.ErrorCard({
  error: { status: 401, message: "登录凭据已过期" },
});
out.authErrorCardHtml = vnodeToHtml(authErrorCard);

const directPropsErrorCard = shared.ErrorCard({
  what: "直接传入错误现象",
  todo: "直接传入指导操作",
});
out.directPropsErrorCardHtml = vnodeToHtml(directPropsErrorCard);

console.log(JSON.stringify(out));
"""


def _run_node_suite() -> dict:
    node = shutil.which("node")
    assert node is not None, "未找到 node 命令"
    result = subprocess.run(
        [
            node,
            "--experimental-vm-modules",
            "--input-type=module",
            "-e",
            _NODE_TEST_SCRIPT,
            str(STATIC),
            str(HOST_STATIC),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, f"Node 执行失败:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    lines = [ln.strip() for ln in result.stdout.strip().splitlines() if ln.strip().startswith("{")]
    assert lines, f"Node 执行未输出有效 JSON:\n{result.stdout}"
    return json.loads(lines[-1])


def test_env_check_pure_logic_three_state_and_placeholder() -> None:
    """断言环境检查纯逻辑的三态分类及占位处理（绝不伪造通过状态）。"""
    data = _run_node_suite()["logicTests"]

    # 1. 正常（绿 / ok）
    for key in ("normalFromData", "normalFromString", "normalFromState"):
        item = data[key]
        assert item["state"] == "ok", f"{key} state 异常: {item}"
        assert item["tone"] == "ok", f"{key} tone 异常: {item}"
        assert item["label"] == "正常"
        assert item["toneClass"] == "is-success"
        assert item["isPassed"] is True
        assert item["placeholder"] is False

    # 2. 需要检查（黄 / warn）
    for key in ("needCheckFromData", "needCheckFromResidual", "needCheckFromString", "needCheckFromState"):
        item = data[key]
        assert item["state"] == "need_check", f"{key} state 异常: {item}"
        assert item["tone"] == "warn", f"{key} tone 异常: {item}"
        assert item["label"] == "需要检查"
        assert item["toneClass"] == "is-warning"
        assert item["isPassed"] is False
        assert item["placeholder"] is False

    # 3. 不可用（红 / bad）
    for key in ("uninstalledFromData", "unlicensedFromData", "unavailableFromString", "unavailableFromBadState"):
        item = data[key]
        assert item["state"] == "unavailable", f"{key} state 异常: {item}"
        assert item["tone"] == "bad", f"{key} tone 异常: {item}"
        assert item["label"] == "不可用"
        assert item["toneClass"] == "is-failed"
        assert item["isPassed"] is False
        assert item["placeholder"] is False

    # 4. 占位状态（无后端/空/占位，绝不伪造通过状态）
    for key in ("placeholderFromNull", "placeholderFromUndefined", "placeholderFromEmpty", "placeholderFromFlag", "placeholderFromString"):
        item = data[key]
        assert item["state"] == "placeholder", f"{key} state 异常: {item}"
        assert item["tone"] == "off", f"{key} tone 异常: {item}"
        assert item["label"] == "暂未提供"
        assert "环境检查将在后续版本提供" in item["description"]
        assert item["placeholder"] is True
        # 核心契约：无后端接口时绝不伪报通过
        assert item["isPassed"] is False
        assert item["toneClass"] == "is-unknown"


def test_env_check_card_vnode_rendering() -> None:
    """断言 EnvCheckCard 在 Node VM 下能按三态渲染对应的 DOM 结构与样式类。"""
    renders = _run_node_suite()["envCardRenders"]

    # 正常（绿）
    html_ok = renders["ok"]
    assert 'aria-label="环境检查"' in html_ok
    assert "xt-env-card" in html_ok
    assert "正常" in html_ok
    assert "is-success" in html_ok
    assert "软件授权正常" in html_ok

    # 需要检查（黄）
    html_warn = renders["needCheck"]
    assert "需要检查" in html_warn
    assert "is-warning" in html_warn
    assert "无法确认激活状态" in html_warn

    # 不可用（红）
    html_bad = renders["unavailable"]
    assert "不可用" in html_bad
    assert "is-failed" in html_bad
    assert "未检测到可用的表格软件" in html_bad

    # 占位（灰 / 暂未提供，说明文本存在，绝不显示正常通过）
    html_ph = renders["placeholder"]
    assert "暂未提供" in html_ph
    assert "环境检查将在后续版本提供" in html_ph
    assert "is-success" not in html_ph
    assert "is-failed" not in html_ph


def test_error_card_usage_and_verbatim_preservation() -> None:
    """断言错误展示统一走 ui-kit ErrorCard，结构正确且保留原文不变。"""
    suite = _run_node_suite()
    html_error = suite["errorCardHtml"]

    # 1. 结构接入 host ui-kit 的 ErrorCard
    assert 'class="uk-error-card"' in html_error
    assert 'role="alert"' in html_error
    assert "发生了什么" in html_error
    assert "你需要做什么" in html_error

    # 2. 原文内容保持不变
    assert "文件「demo.xlsx」读取失败：格式不兼容" in html_error
    assert "HTTP 422" in html_error
    assert "ValidationError" in html_error
    assert "targetPath: 模板文件不存在" in html_error

    # 3. 认证错误支持重新登录动作
    auth_html = suite["authErrorCardHtml"]
    assert "登录凭据已过期" in auth_html
    assert "请重新登录后再试" in auth_html
    assert "重新登录" in auth_html

    # 4. 直接传入 what / todo 支持
    direct_html = suite["directPropsErrorCardHtml"]
    assert "直接传入错误现象" in direct_html
    assert "直接传入指导操作" in direct_html


def test_user_facing_copy_glossary_gate() -> None:
    """门禁断言：excel_tasks 插件下所有前端文件中禁止出现内部技术术语与代码路径特征。"""
    from tests.test_glossary_terms import (
        DRIVE_PATH_REGEX,
        EXACT_BANNED_TERMS,
        PY_SUFFIX_REGEX,
        extract_js_visible_strings,
        read_js_file_utf8,
        scan_text_segment,
    )

    violations = []
    for js_path in STATIC.glob("*.js"):
        content = read_js_file_utf8(js_path)
        strings = extract_js_visible_strings(content)
        for line_no, text_val in strings:
            hits = scan_text_segment(text_val)
            for term, match_str in hits:
                violations.append(f"{js_path.name}:{line_no} 命中禁词 [{term}] -> {match_str!r}")

    assert not violations, "发现前端违规术语或代码路径，请替换为通俗中文:\n" + "\n".join(violations)
