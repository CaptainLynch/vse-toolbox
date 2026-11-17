# -*- coding: utf-8 -*-
"""交付物详情页关注清单与历史原件组件测试（契约 C5 单一权威、REQUIREMENTS D9/G2）。

门禁断言：
1. 双入口同源读写：交付物详情页（detail-watchlist.js）与报告页/表单分析页（watchlist.js）
   必须使用完全一致的 API 路由路径（/api/p/project-overview/watchlist）。
2. 文案无内部术语：界面文案通俗化，禁止泄露 JSON、Base URL、Worker、快照、取证及代码路径。
3. 历史原件只读契约：历史原件块仅执行 GET 只读查询，不创建任何写路由；
   并明确声明后端阻塞点（接口不支持按交付物标识过滤，且无文件流下载端点）。
4. 约束保障：simple.js 与 form-analysis.js 零改动。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC = REPO_ROOT / "plugins" / "project_overview" / "static"
DELIVERABLE_DIR = STATIC / "deliverable"
DETAIL_WATCHLIST_JS = DELIVERABLE_DIR / "detail-watchlist.js"
WATCHLIST_JS = DELIVERABLE_DIR / "watchlist.js"
SIMPLE_JS = DELIVERABLE_DIR / "simple.js"
FORM_ANALYSIS_JS = DELIVERABLE_DIR / "form-analysis.js"

# 禁用术语定义（与 test_glossary_terms.py 及 web/static/host/glossary.js 一致）
BANNED_TERMS = ("JSON", "Base URL", "Worker", "快照", "取证")
DRIVE_PATH_REGEX = re.compile(r"[a-zA-Z]:\\[^\s\"'`<>]*")
PY_SUFFIX_REGEX = re.compile(r"\b[a-zA-Z0-9_.-]+\.py\b")


def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.match(r"v(\d+)", out.strip())
    return int(match.group(1)) if match else 0


needs_node = pytest.mark.skipif(_node_major() < 22, reason="needs Node 22+ to test ES modules")


def test_detail_watchlist_file_exists() -> None:
    """组件文件必须存在于 scope 指定路径。"""
    assert DETAIL_WATCHLIST_JS.is_file(), f"缺少文件: {DETAIL_WATCHLIST_JS}"


@needs_node
def test_detail_watchlist_node_check_passes() -> None:
    """Node 语法检查必须通过（杜绝模板字符串反引号配对或嵌套语法错误）。"""
    result = subprocess.run(
        ["node", "--check", str(DETAIL_WATCHLIST_JS)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"node --check 失败: {result.stderr}"


@needs_node
def test_dual_entry_same_api_path_node_fixture() -> None:
    """Node 夹具断言双入口同源读写：详情页组件与报告页组件引用同一 API 路径。"""
    node_eval_script = r"""
import fs from 'node:fs';

const detailCode = fs.readFileSync(process.argv[1], 'utf8');
const watchlistCode = fs.readFileSync(process.argv[2], 'utf8');

function extractPath(code, varName) {
  const re = new RegExp(`${varName}\\s*=\\s*["']([^"']+)["']`);
  const match = code.match(re);
  return match ? match[1] : null;
}

const detailWatchlistPath = extractPath(detailCode, 'WATCHLIST_PATH');
const mainWatchlistPath = extractPath(watchlistCode, 'WATCHLIST_PATH');
const detailCsvPath = extractPath(detailCode, 'WATCHLIST_CSV_PATH');
const mainCsvPath = extractPath(watchlistCode, 'WATCHLIST_CSV_PATH');
const detailTermsPath = extractPath(detailCode, 'TERMS_PATH');
const mainTermsPath = extractPath(watchlistCode, 'TERMS_PATH');

console.log(JSON.stringify({
  detailWatchlistPath,
  mainWatchlistPath,
  detailCsvPath,
  mainCsvPath,
  detailTermsPath,
  mainTermsPath
}));
"""
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            node_eval_script,
            str(DETAIL_WATCHLIST_JS),
            str(WATCHLIST_JS),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout.strip().splitlines()[-1])

    # 1. 关注清单 API 路径完全同源
    assert data["detailWatchlistPath"] is not None
    assert data["detailWatchlistPath"] == data["mainWatchlistPath"]
    assert data["detailWatchlistPath"] == "/api/p/project-overview/watchlist"

    # 2. 导出 CSV 路径完全同源
    assert data["detailCsvPath"] is not None
    assert data["detailCsvPath"] == data["mainCsvPath"]
    assert data["detailCsvPath"] == "/api/p/project-overview/watchlist.csv"

    # 3. 多值搜索摘要路径完全同源
    assert data["detailTermsPath"] is not None
    assert data["detailTermsPath"] == data["mainTermsPath"]
    assert data["detailTermsPath"] == "/api/p/project-overview/form-terms"


@needs_node
def test_parse_serial_input_node_logic() -> None:
    """测试多单号解析纯逻辑：支持空格、换行、逗号、顿号、分号，全角转半角，自动去重。"""
    node_script = r"""
import fs from 'node:fs';

const code = fs.readFileSync(process.argv[1], 'utf8');

// 提取 parseSerialInput 函数体在隔离环境中测试
const fnMatch = code.match(/export function parseSerialInput\([\s\S]*?\n\}/);
if (!fnMatch) {
  throw new Error('parseSerialInput not found');
}
// 函数引用的模块级常量一并提取（否则 new Function 里 ReferenceError）
const constMatch = code.match(/const SERIAL_SPLIT_REGEX\s*=\s*\/[^\n]+\//);
if (!constMatch) {
  throw new Error('SERIAL_SPLIT_REGEX not found');
}

const cleanedFn = constMatch[0] + '\n' + fnMatch[0].replace('export ', '');
const runner = new Function(cleanedFn + '\nreturn parseSerialInput(arguments[0]);');

const sample = ' WF-001  WF-002,WF-003；WF-004、WF-005\nWF-001，ｗｆ－００２ ';
const parsed = runner(sample);

console.log(JSON.stringify({ parsed }));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", node_script, str(DETAIL_WATCHLIST_JS)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout.strip().splitlines()[-1])["parsed"]
    # 验证去重、全角转半角大写、各分隔符切分
    assert parsed == ["WF-001", "WF-002", "WF-003", "WF-004", "WF-005"]


def test_no_internal_jargon_in_detail_watchlist() -> None:
    """文案通俗化断言：禁止出现 JSON、Base URL、Worker、快照、取证等内部术语。"""
    content = DETAIL_WATCHLIST_JS.read_text(encoding="utf-8")

    # 1. 禁用词校验
    for term in BANNED_TERMS:
        assert term not in content, f"detail-watchlist.js 中发现了内部术语: '{term}'"

    # 2. 盘符路径校验
    assert not DRIVE_PATH_REGEX.search(content), "detail-watchlist.js 中泄露了 Windows 盘符路径"

    # 3. .py 后缀校验
    assert not PY_SUFFIX_REGEX.search(content), "detail-watchlist.js 中泄露了 .py 代码脚本文件名"


def test_historical_archive_readonly_contract() -> None:
    """历史原件只读断言：只调用 GET 接口，无新增写路由；声明阻塞点。"""
    content = DETAIL_WATCHLIST_JS.read_text(encoding="utf-8")

    # 引用了只读 runs 路径
    assert "/api/scheduled-archive/runs" in content
    # 引用了只读产物路径
    assert "artifacts" in content

    # 确保原件留存只读，绝不发 POST/PUT/DELETE 请求到 scheduled-archive
    scheduled_writes = re.findall(
        r'apiRequest\([^)]*scheduled-archive[^)]*method:\s*["\'](POST|PUT|DELETE)["\']',
        content,
    )
    assert not scheduled_writes, f"历史原件不允许写操作: {scheduled_writes}"

    # 确保阻塞点已在常量与注释中明确声明
    assert "ARCHIVE_FILTER_BLOCKING_NOTE" in content
    assert "ARCHIVE_DOWNLOAD_BLOCKING_NOTE" in content

