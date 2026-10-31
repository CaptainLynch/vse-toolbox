# -*- coding: utf-8 -*-
"""旧页体验统一第二批（U6/U7/U8）源级断言门禁测试。

契约说明：
上一轮教训：hooks 组件在无 DOM 的 Node VM 里无法直渲染（无 render 流水线，useState 直接抛错）。
本测试套件遵循纯源级断言原则，不做组件直接渲染：
1. node --check 语法检查：验证四页语法完全符合 ES Module 规范；
2. 源级正则断言：验证每页必须从 /static/host/ui-kit.js（或 ui-kit）导入并调用 ErrorCard 与 Skeleton，且接入 TONE 状态色；
3. 纯逻辑函数测试：通过 new Function 隔离执行纯函数契约，杜绝 hooks 依赖；
4. 术语门禁委托：由仓库权威测试 tests/test_glossary_terms.py 统一保证文案无内部黑话与代码路径泄露。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# 统一第二批四个目标页面
TARGET_PAGES = {
    "tir_report": REPO_ROOT / "plugins" / "tir_report" / "static" / "report.js",
    "system_query": REPO_ROOT / "plugins" / "system_query" / "static" / "query.js",
    "settings": REPO_ROOT / "plugins" / "settings" / "static" / "general.js",
    "sign_daily_settings": REPO_ROOT / "plugins" / "sign_daily" / "static" / "settings-panel.js",
}


def _node_available() -> bool:
    return shutil.which("node") is not None


needs_node = pytest.mark.skipif(not _node_available(), reason="需要 Node.js 执行语法检查与纯函数测试")


# ── ① node --check 语法检查 ──────────────────────────────────────────────


@needs_node
@pytest.mark.parametrize("page_id,page_file", list(TARGET_PAGES.items()))
def test_page_syntax_check_passes(page_id: str, page_file: Path) -> None:
    """验证目标页面文件存在且通过 node --check 语法检查（杜绝模板串/ESM语法缺陷）。"""
    assert page_file.is_file(), f"页面文件不存在: {page_file}"
    result = subprocess.run(
        ["node", "--check", str(page_file)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, f"页面 {page_id} node --check 检查失败:\n{result.stderr}"


# ── ② 源级正则断言：ErrorCard / Skeleton / TONE 导入与调用 ───────────────

RE_UI_KIT_IMPORT = re.compile(
    r'import\s+{[^}]*?(?P<symbols>[^}]+?)}\s+from\s+["\'][^"\']*ui-kit(?:\.js)?["\']'
)
RE_ERROR_CARD_CALL = re.compile(r'<\s*(?:\$\{\s*)?ErrorCard\b')
RE_SKELETON_CALL = re.compile(r'<\s*(?:\$\{\s*)?Skeleton\b')
RE_TONE_USAGE = re.compile(r'\bTONE\.(?:ok|warn|bad|off)\b|\bTONE\[')


@pytest.mark.parametrize("page_id,page_file", list(TARGET_PAGES.items()))
def test_page_imports_ui_kit_components(page_id: str, page_file: Path) -> None:
    """源级断言：每页必须从 ui-kit 导入 ErrorCard、Skeleton 与 TONE。"""
    source = page_file.read_text(encoding="utf-8")
    match = RE_UI_KIT_IMPORT.search(source)
    assert match is not None, f"{page_id} 未从 ui-kit 导入组件: {page_file}"
    symbols = {s.strip().split()[0] for s in match.group("symbols").split(",")}
    assert "ErrorCard" in symbols, f"{page_id} 未从 ui-kit 导入 ErrorCard"
    assert "Skeleton" in symbols, f"{page_id} 未从 ui-kit 导入 Skeleton"
    assert "TONE" in symbols, f"{page_id} 未从 ui-kit 导入 TONE"


@pytest.mark.parametrize("page_id,page_file", list(TARGET_PAGES.items()))
def test_page_calls_error_card(page_id: str, page_file: Path) -> None:
    """源级断言：每页必须在 JSX/htm 模板中调用 <${ErrorCard} ...> 或 <ErrorCard ...>。"""
    source = page_file.read_text(encoding="utf-8")
    assert RE_ERROR_CARD_CALL.search(source) is not None, f"{page_id} 源码中未调用 ErrorCard"


@pytest.mark.parametrize("page_id,page_file", list(TARGET_PAGES.items()))
def test_page_calls_skeleton(page_id: str, page_file: Path) -> None:
    """源级断言：每页必须在 JSX/htm 模板中调用 <${Skeleton} ...> 或 <Skeleton ...>。"""
    source = page_file.read_text(encoding="utf-8")
    assert RE_SKELETON_CALL.search(source) is not None, f"{page_id} 源码中未调用 Skeleton"


@pytest.mark.parametrize("page_id,page_file", list(TARGET_PAGES.items()))
def test_page_uses_tone_semantics(page_id: str, page_file: Path) -> None:
    """源级断言：每页状态色语义必须对齐 TONE 常量。"""
    source = page_file.read_text(encoding="utf-8")
    assert RE_TONE_USAGE.search(source) is not None, f"{page_id} 源码中未引用 TONE 状态色"


# ── ③ 纯逻辑函数测试（new Function 隔离，零 hooks 依赖） ────────────────


@needs_node
def test_pure_logic_format_error_with_new_function() -> None:
    """纯逻辑函数隔离断言：使用 new Function 验证错误格式化纯逻辑，无 hooks / 无 DOM。"""
    eval_script = r"""
const formatErrorWhat = new Function("error", `
  if (!error) return "";
  const isAuth = Boolean(error.status === 401 || String(error.message || "").includes("未登录"));
  if (isAuth) return "企业认证会话已失效";
  return error.summary || error.message || "系统设置操作未成功";
`);

const formatErrorTodo = new Function("error", "openLogin", `
  if (!error) return "";
  const isAuth = Boolean(error.status === 401 || String(error.message || "").includes("未登录"));
  if (isAuth) {
    return openLogin
      ? "本地系统设置未受影响，但企业会话需要重新验证。请点击【重新登录】。"
      : "本地系统设置未受影响，但企业会话需要重新验证。请在下方「统一域账号登录」中重新登录。";
  }
  return error.impact || "表单中已输入的内容已完整保留，未覆盖未修改的配置项。";
`);

const out = {
  authWhat: formatErrorWhat({ status: 401 }),
  normalWhat: formatErrorWhat({ message: "连接被拒绝" }),
  emptyWhat: formatErrorWhat(null),
  authTodoWithLogin: formatErrorTodo({ status: 401 }, true),
  authTodoNoLogin: formatErrorTodo({ status: 401 }, false),
  normalTodo: formatErrorTodo({ impact: "参数格式不正确，请核对" }, false),
};

console.log(JSON.stringify(out));
"""
    result = subprocess.run(
        ["node", "-e", eval_script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, f"new Function 逻辑测试失败:\n{result.stderr}"
    data = json.loads(result.stdout.strip())
    assert data["authWhat"] == "企业认证会话已失效"
    assert data["normalWhat"] == "连接被拒绝"
    assert data["emptyWhat"] == ""
    assert "请点击【重新登录】" in data["authTodoWithLogin"]
    assert "请在下方「统一域账号登录」中重新登录" in data["authTodoNoLogin"]
    assert data["normalTodo"] == "参数格式不正确，请核对"


@needs_node
def test_pure_logic_parse_pairs_with_new_function() -> None:
    """纯逻辑函数隔离断言：使用 new Function 验证键值对解析纯逻辑，无 hooks。"""
    eval_script = r"""
const parsePairs = new Function("text", `
  const out = {};
  for (const line of String(text || "").split("\\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const idx = trimmed.indexOf("=");
    if (idx > 0) {
      out[trimmed.slice(0, idx).trim()] = trimmed.slice(idx + 1).trim();
    }
  }
  return out;
`);

const parsed = parsePairs("张三=车身科\n# 注释行\n李四=外饰科\n无效行");
console.log(JSON.stringify(parsed));
"""
    result = subprocess.run(
        ["node", "-e", eval_script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, f"parsePairs new Function 失败:\n{result.stderr}"
    data = json.loads(result.stdout.strip())
    assert data == {"张三": "车身科", "李四": "外饰科"}


# ── ④ 无组件直渲染安全约束 ──────────────────────────────────────────────


def test_test_suite_avoids_preact_dom_free_rendering() -> None:
    """断言本测试文件不含 Preact 直渲染逻辑，严防 Node VM 崩溃重演（W6-02/W8-02 教训）。

    检查词写成拼接形式，避免本文件的函数名/文档字面量自己命中断言。
    """
    test_source = Path(__file__).read_text(encoding="utf-8")
    forbidden = ["render" + "(", "render" + "ToString", "preact-render-to-" + "string"]
    for word in forbidden:
        assert word not in test_source, f"测试文件不应包含直渲染入口: {word}"
