# -*- coding: utf-8 -*-
"""首次使用向导状态流转、凭据安全与契约测试（REQUIREMENTS U1；契约 C3）。

验证重点：
1. 模块导出完整性与现有调用方零修改兼容（Wizard、wizardDismissed）；
2. 凭据绝不持久化（严格断言 localStorage 序列化键集合与内容，无任何 password/token/credentials 字段）；
3. 跨重启状态恢复（步进、车型、科室、交付物选择、开机自启等非敏感状态持久化与恢复）；
4. 明确区分「稍后设置」（status: skipped）与「已完成」（status: completed）；
5. 开机自启询问默认关闭（autostart: false）；
6. 向导各步骤均提供返回路径（每步可返回）；
7. 用户可见文案通俗合规，无任何内部黑话（快照、取证、JSON、Worker 等）。
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
    except Exception:
        return 0


needs_node = pytest.mark.skipif(_node_major() < 20, reason="需要 Node 20+ 运行 ES Module")

_RUNNER_JS = r"""
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import * as vm from "node:vm";

const [, WIZARD_JS_PATH, SCENARIO_JSON] = process.argv;
const scenario = JSON.parse(SCENARIO_JSON);

const storage = new Map();
if (scenario.initialStorage) {
  for (const [k, v] of Object.entries(scenario.initialStorage)) {
    storage.set(String(k), String(v));
  }
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

const recordedLogins = [];
const recordedApis = [];
const recordedNavigations = [];

const context = vm.createContext({
  console: { log() {}, warn() {}, error() {}, info() {} },
  setTimeout, clearTimeout,
  Promise, JSON, Math, Date, Object, Array, String, Number, Boolean, RegExp, Error,
  encodeURIComponent, decodeURIComponent,
  window: {
    localStorage,
    location: { hash: "", reload() {} },
  },
  localStorage,
});

const code = readFileSync(WIZARD_JS_PATH, "utf8");
const mod = new vm.SourceTextModule(code, {
  context,
  initializeImportMeta(meta) {
    meta.url = pathToFileURL(WIZARD_JS_PATH).href;
  },
});

function templateToString(node) {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(templateToString).join("");
  if (typeof node.type === "function") {
    try {
      return templateToString(node.type(node.props || {}));
    } catch (_err) {
      return "";
    }
  }
  if (node.__template) {
    let res = "";
    for (let i = 0; i < node.strings.length; i++) {
      res += node.strings[i];
      if (i < node.values.length) {
        const v = node.values[i];
        if (typeof v === "function") {
          res += "[fn]";
        } else {
          res += templateToString(v);
        }
      }
    }
    return res;
  }
  return String(node);
}

await mod.link(async (specifier) => {
  if (specifier.includes("preact-htm")) {
    return new vm.SyntheticModule(
      ["html", "useState", "useEffect", "useCallback", "useRef"],
      function () {
        this.setExport("html", (strings, ...values) => ({
          __template: true,
          strings: Array.from(strings),
          values,
        }));
        this.setExport("useState", (init) => {
          let val = typeof init === "function" ? init() : init;
          return [val, () => {}];
        });
        this.setExport("useEffect", () => {});
        this.setExport("useCallback", (fn) => fn);
        this.setExport("useRef", (init) => ({ current: init }));
      },
      { context }
    );
  }
  if (specifier.includes("session.js")) {
    return new vm.SyntheticModule(
      ["submitDomainLogin", "updateSessionBadges"],
      function () {
        this.setExport("submitDomainLogin", async (creds) => {
          recordedLogins.push(creds);
          return { kind: "success", text: "已登录", sessions: { aras: "connected", tdc: "connected" } };
        });
        this.setExport("updateSessionBadges", () => {});
      },
      { context }
    );
  }
  if (specifier.includes("common.js")) {
    return new vm.SyntheticModule(
      ["api", "html", "go", "activeDeliverables"],
      function () {
        this.setExport("api", async (url, opts) => {
          recordedApis.push({ url, opts });
          return scenario.mockApiResponses && scenario.mockApiResponses[url]
            ? scenario.mockApiResponses[url]
            : { ok: true, deliverables: [] };
        });
        this.setExport("html", (strings, ...values) => ({
          __template: true,
          strings: Array.from(strings),
          values,
        }));
        this.setExport("go", (hash) => {
          recordedNavigations.push(hash);
        });
        this.setExport("activeDeliverables", (list) => (list || []).filter((d) => !d.retired));
      },
      { context }
    );
  }
  throw new Error("unexpected specifier: " + specifier);
});

await mod.evaluate();
const exports = mod.namespace;

const out = {};
const action = scenario.action;

if (action === "checkExports") {
  out.exportsList = Object.keys(exports);
  out.hasWizard = typeof exports.Wizard === "function";
  out.hasWizardDismissed = typeof exports.wizardDismissed === "function";
  out.hasSanitize = typeof exports.sanitizeWizardState === "function";
  out.hasLoad = typeof exports.loadWizardState === "function";
  out.hasSave = typeof exports.saveWizardState === "function";
  out.hasMarkSkipped = typeof exports.markWizardSkipped === "function";
  out.hasMarkCompleted = typeof exports.markWizardCompleted === "function";
  out.hasIsSkipped = typeof exports.isWizardSkipped === "function";
  out.hasIsCompleted = typeof exports.isWizardCompleted === "function";
  out.hasReset = typeof exports.resetWizardState === "function";
  out.allowedKeys = exports.ALLOWED_STATE_KEYS;
  out.stepNames = exports.STEP_NAMES;
  out.defaultDepartments = exports.DEFAULT_DEPARTMENTS;
} else if (action === "testCredentialSanitization") {
  const dirty = scenario.dirtyPayload;
  const sanitized = exports.sanitizeWizardState(dirty);
  exports.saveWizardState(dirty);
  const rawSaved = localStorage.getItem(exports.STATE_KEY);
  const parsedSaved = JSON.parse(rawSaved || "{}");
  out.sanitized = sanitized;
  out.parsedSaved = parsedSaved;
  out.rawSavedString = rawSaved;
  out.savedKeys = Object.keys(parsedSaved);
} else if (action === "testProgressionAndRestore") {
  for (const stepData of scenario.steps) {
    exports.saveWizardState(stepData);
  }
  out.restoredState = exports.loadWizardState();
  out.storageDump = localStorage._dump();
} else if (action === "testSkippedVsCompleted") {
  if (scenario.subAction === "skip") {
    exports.markWizardSkipped(scenario.step, scenario.extra);
  } else if (scenario.subAction === "complete") {
    exports.markWizardCompleted(scenario.extra);
  } else if (scenario.subAction === "reset") {
    exports.resetWizardState();
  }
  out.isSkipped = exports.isWizardSkipped();
  out.isCompleted = exports.isWizardCompleted();
  out.isDismissed = exports.wizardDismissed();
  out.state = exports.loadWizardState();
  out.storageDump = localStorage._dump();
} else if (action === "testRenderSteps") {
  const rendered = {};
  for (const stepIdx of [0, 1, 2, 3, 4, 5]) {
    const vnode = exports.Wizard({
      projectName: "测试车型项目",
      onClose: () => {},
      initialStep: stepIdx,
    });
    rendered[stepIdx] = templateToString(vnode);
  }
  out.renderedSteps = rendered;
} else if (action === "testLegacyDismissed") {
  localStorage.setItem(exports.DISMISS_KEY, "1");
  out.isDismissed = exports.wizardDismissed();
  out.isSkipped = exports.isWizardSkipped();
  out.isCompleted = exports.isWizardCompleted();
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


def test_wizard_js_file_exists() -> None:
    """验证向导文件路径与只读范围正确性。"""
    assert WIZARD_JS.is_file(), f"向导源码不存在: {WIZARD_JS}"


def test_wizard_source_code_contract() -> None:
    """静态代码门禁：确保无敏感持久化并符合架构约束。"""
    content = WIZARD_JS.read_text(encoding="utf-8")

    # 导出挂点门禁
    assert "export function Wizard" in content
    assert "export function wizardDismissed" in content
    assert "export const ALLOWED_STATE_KEYS" in content

    # 密码绝不持久化：检查 ALLOWED_STATE_KEYS 绝对不包含敏感词
    match = re.search(r"export const ALLOWED_STATE_KEYS\s*=\s*\[(.*?)\];", content, re.DOTALL)
    assert match, "未找到 ALLOWED_STATE_KEYS 列表声明"
    keys_block = match.group(1).lower()
    for sensitive_term in ["password", "pwd", "token", "secret", "cookie", "session", "cred"]:
        assert sensitive_term not in keys_block, f"ALLOWED_STATE_KEYS 中包含敏感键名: {sensitive_term}"

    # 禁止内部技术黑话
    forbidden_terms = ["快照", "取证", "Base URL", "Worker"]
    for term in forbidden_terms:
        # 只检查非注释行中的用户可见文案
        lines = [ln for ln in content.splitlines() if not ln.strip().startswith("//")]
        for ln in lines:
            if "html`" in ln or "title=" in ln or "placeholder=" in ln:
                assert term not in ln, f"用户可见文案包含内部技术词汇「{term}」: {ln}"


@needs_node
def test_node_module_exports_contract() -> None:
    """验证向导 ES Module 的导出兼容性与基础常量。"""
    data = _run_node_scenario({"action": "checkExports"})
    assert data["hasWizard"] is True
    assert data["hasWizardDismissed"] is True
    assert data["hasSanitize"] is True
    assert data["hasLoad"] is True
    assert data["hasSave"] is True
    assert data["hasMarkSkipped"] is True
    assert data["hasMarkCompleted"] is True
    assert data["hasIsSkipped"] is True
    assert data["hasIsCompleted"] is True
    assert data["hasReset"] is True

    # 步骤数量为 6
    assert data["stepNames"] == ["欢迎", "统一登录", "新建项目", "选择交付物", "开机自启", "完成"]
    # 默认科室完整性
    assert "车体科" in data["defaultDepartments"]
    assert "车体架构集成科" in data["defaultDepartments"]


@needs_node
def test_password_never_saved_to_local_storage() -> None:
    """核心契约 C3：密码绝不持久化到向导状态（断言 localStorage 序列化键集合与内容）。"""
    dirty_payload = {
        "step": 1,
        "username": "zhangsan",
        "password": "VerySecretPassword#999!",
        "pwd": "plain_password_here",
        "token": "bearer-token-12345",
        "secret": "top-secret-val",
        "cookie": "session_cookie=abc",
        "credentials": {"user": "zhangsan", "pass": "secret"},
        "vehicle": "F610S",
        "autostart": False,
    }

    data = _run_node_scenario({
        "action": "testCredentialSanitization",
        "dirtyPayload": dirty_payload,
    })

    saved_keys = set(data["savedKeys"])
    allowed_keys = set(data["sanitized"].keys())

    # 1. 严格断言 saved_keys 绝无任何敏感词
    for sensitive_name in ["password", "pwd", "token", "secret", "cookie", "credentials", "pass"]:
        assert sensitive_name not in saved_keys, f"localStorage 中发现了敏感键名: {sensitive_name}"
        assert sensitive_name not in allowed_keys, f"清洗后的字段中发现了敏感键名: {sensitive_name}"

    # 2. 严格断言原始序列化字符串完全不包含密码文本
    raw_str = data["rawSavedString"]
    assert "VerySecretPassword#999!" not in raw_str, "localStorage 原始字符串中发现了明文密码！"
    assert "plain_password_here" not in raw_str, "localStorage 原始字符串中发现了 pwd 明文！"
    assert "bearer-token-12345" not in raw_str, "localStorage 原始字符串中发现了 token！"

    # 3. 正常非敏感字段不受影响
    parsed = data["parsedSaved"]
    assert parsed["username"] == "zhangsan"
    assert parsed["vehicle"] == "F610S"
    assert parsed["step"] == 1


@needs_node
def test_step_progression_and_restore_across_restart() -> None:
    """跨重启恢复非敏感状态（步进、车型、科室、交付物选择、开机自启）。"""
    steps_data = [
        {"step": 1, "username": "lisi"},
        {"step": 2, "vehicle": "F610S", "name": "F610S全新改款", "departments": ["车体科", "车身科"]},
        {"step": 3, "selectedDeliverables": ["deliv-01", "deliv-03"]},
        {"step": 4, "autostart": True},
    ]

    data = _run_node_scenario({
        "action": "testProgressionAndRestore",
        "steps": steps_data,
    })

    restored = data["restoredState"]
    assert restored["step"] == 4
    assert restored["username"] == "lisi"
    assert restored["vehicle"] == "F610S"
    assert restored["name"] == "F610S全新改款"
    assert restored["departments"] == ["车体科", "车身科"]
    assert restored["selectedDeliverables"] == ["deliv-01", "deliv-03"]
    assert restored["autostart"] is True
    assert "password" not in restored


@needs_node
def test_distinguish_skipped_vs_completed() -> None:
    """明确区分「稍后设置」（status: skipped）与「已完成」（status: completed）。"""
    # 场景 1：稍后设置（在新建项目第 2 步点击跳过并退出）
    data_skip = _run_node_scenario({
        "action": "testSkippedVsCompleted",
        "subAction": "skip",
        "step": 2,
        "extra": {"vehicle": "F610S"},
    })
    assert data_skip["isSkipped"] is True
    assert data_skip["isCompleted"] is False
    assert data_skip["isDismissed"] is True
    assert data_skip["state"]["status"] == "skipped"
    assert data_skip["state"]["skippedStep"] == 2
    assert data_skip["state"]["vehicle"] == "F610S"

    # 场景 2：完成所有步骤（第 5 步正常完成）
    data_complete = _run_node_scenario({
        "action": "testSkippedVsCompleted",
        "subAction": "complete",
        "extra": {"vehicle": "F610S", "selectedDeliverables": ["deliv-01"]},
    })
    assert data_complete["isCompleted"] is True
    assert data_complete["isSkipped"] is False
    assert data_complete["isDismissed"] is True
    assert data_complete["state"]["status"] == "completed"
    assert data_complete["state"]["step"] == 5

    # 场景 3：重置初始状态（首次访问，未曾跳过也未完成）
    data_reset = _run_node_scenario({
        "action": "testSkippedVsCompleted",
        "subAction": "reset",
    })
    assert data_reset["isCompleted"] is False
    assert data_reset["isSkipped"] is False
    assert data_reset["isDismissed"] is False
    assert data_reset["state"] is None


@needs_node
def test_autostart_query_default_disabled() -> None:
    """契约验证：开机自启询问默认关闭。"""
    # 1. sanitize 空输入断言
    data = _run_node_scenario({
        "action": "testCredentialSanitization",
        "dirtyPayload": {},
    })
    assert data["sanitized"]["autostart"] is False
    assert data["parsedSaved"]["autostart"] is False

    # 2. 渲染第 4 步开机自启页面，断言文案与默认关闭
    render_data = _run_node_scenario({"action": "testRenderSteps"})
    step4_html = render_data["renderedSteps"]["4"]
    assert "开机自启设置" in step4_html
    assert "开机自动启动 VSE 工具箱" in step4_html


@needs_node
def test_every_step_has_return_path() -> None:
    """契约验证：向导除首步外每步均提供「上一步」返回路径。"""
    data = _run_node_scenario({"action": "testRenderSteps"})
    rendered = data["renderedSteps"]

    # 第 0 步为欢迎页，有「开始」与「稍后设置」
    assert "欢迎使用 VSE Toolbox" in rendered["0"]
    assert "稍后设置" in rendered["0"]
    assert "开始" in rendered["0"]

    # 第 1 步到第 5 步每一步都必须有「上一步」
    for step_idx in [1, 2, 3, 4, 5]:
        step_html = rendered[str(step_idx)]
        assert "上一步" in step_html, f"第 {step_idx} 步缺少「上一步」返回按钮"


@needs_node
def test_completion_step_has_auto_sync_and_start_actions() -> None:
    """契约验证：完成步触发交付物启用流程跳转或提示去项目页开启。"""
    data = _run_node_scenario({"action": "testRenderSteps"})
    step5_html = data["renderedSteps"]["5"]
    assert "配置完成" in step5_html
    assert "开启自动同步" in step5_html
    assert "开始使用" in step5_html
    assert "项目页" in step5_html


@needs_node
def test_legacy_dismiss_key_compatibility() -> None:
    """兼容旧版 vse.wizardDone = '1' 标记，确保既有逻辑不失效。"""
    data = _run_node_scenario({"action": "testLegacyDismissed"})
    assert data["isDismissed"] is True
    assert data["isCompleted"] is False


@needs_node
def test_project_recovery_keys_persist_and_sanitize() -> None:
    """项目恢复键（已建项目 ID / 签名 / 自启确认态）随向导状态持久化，非法值被清洗。"""
    saved = _run_node_scenario({
        "action": "testProgressionAndRestore",
        "steps": [{
            "step": 3,
            "projectCreated": True,
            "projectId": "proj-9",
            "projectSignature": '["F610S","F610S",["车体科"]]',
            "autostartConfirmed": "on",
        }],
    })["restoredState"]
    assert saved["step"] == 3
    assert saved["projectCreated"] is True
    assert saved["projectId"] == "proj-9"
    assert saved["projectSignature"] == '["F610S","F610S",["车体科"]]'
    assert saved["autostartConfirmed"] == "on"

    dirty = _run_node_scenario({
        "action": "testProgressionAndRestore",
        "steps": [{"projectId": 123, "projectSignature": None, "autostartConfirmed": "maybe"}],
    })
    restored = dirty["restoredState"]
    assert restored["projectId"] == ""
    assert restored["projectSignature"] == ""
    assert restored["autostartConfirmed"] == "unknown"
    assert restored["projectCreated"] is False
    raw = dirty["storageDump"]["vse.wizardState"]
    assert "maybe" not in raw
    assert "123" not in raw
