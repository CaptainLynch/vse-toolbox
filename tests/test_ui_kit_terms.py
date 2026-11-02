# -*- coding: utf-8 -*-
"""UI Kit 组件与术语词表 Node 门禁测试。

基于真实 Node.js 运行时测试前端 ES Module 契约：
1. 模块导入与导出完整性：ui-kit.js 导出 ErrorCard、FixIt、Skeleton、TONE；glossary.js 导出 BANNED、scanText；
2. ErrorCard 使用真实 htm 渲染，验证「发生了什么 / 你需要做什么 / [一键处理] / [导出诊断包]」结构及按钮可缺省特性；
3. FixIt 与 Skeleton 渲染正确性；
4. TONE 状态色常量（ok / warn / bad / off）完整性；
5. scanText 在干净文本与包含各类禁词/路径特征文本下的判定准确性。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOST_STATIC = REPO_ROOT / "web" / "static" / "host"


def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.match(r"v(\d+)", out.strip())
    return int(match.group(1)) if match else 0


pytestmark = pytest.mark.skipif(_node_major() < 22, reason="needs Node 22+ to import ES modules")


_NODE_TEST_SCRIPT = r"""
const base = process.argv[1];
const uiKit = await import(base + "/ui-kit.js");
const glossary = await import(base + "/glossary.js");

const out = {};

// 1. 导出检查
out.uiKitExports = {
  hasErrorCard: typeof uiKit.ErrorCard === "function",
  hasFixIt: typeof uiKit.FixIt === "function",
  hasSkeleton: typeof uiKit.Skeleton === "function",
  hasTone: typeof uiKit.TONE === "object" && uiKit.TONE !== null,
  toneKeys: uiKit.TONE ? Object.keys(uiKit.TONE).sort() : [],
  toneValues: uiKit.TONE,
  hasHtml: typeof uiKit.html === "function",
};

out.glossaryExports = {
  hasBanned: Array.isArray(glossary.BANNED),
  bannedLength: glossary.BANNED ? glossary.BANNED.length : 0,
  hasScanText: typeof glossary.scanText === "function",
};

// 1b. 运行时词表构成：字面量禁词与正则特征分开导出，供 Python 侧和仓库门禁比对。
out.bannedLiterals = Array.isArray(glossary.BANNED)
  ? glossary.BANNED.filter((item) => typeof item === "string")
  : [];
out.bannedPatterns = Array.isArray(glossary.BANNED)
  ? glossary.BANNED.filter((item) => item instanceof RegExp).map((item) => item.source)
  : [];

// 2. scanText 扫描能力验证
out.scanClean = glossary.scanText("这里是纯正通俗的普通中文文案，无任何违规");
out.scanHitJson = glossary.scanText("请求响应失败：返回数据不是合法的 JSON 格式");
out.scanHitBaseUrl = glossary.scanText("请在输入框填写正确的 Base URL 地址");
out.scanHitWorker = glossary.scanText("后台处理服务 Worker 处于不可用状态");
out.scanHitSnapshot = glossary.scanText("各表单数据来自最近一次自动归档快照");
out.scanHitForensics = glossary.scanText("需要进行全量取证并导出证据文件");
out.scanHitDrive = glossary.scanText("例如：D:\\VSE\\archive 归档文件目录");
out.scanHitPy = glossary.scanText("请检查并执行 python tools/tir_probe.py 取证脚本");

// 3. VNode 树递归序列化为 HTML 字符串（纯内存测试，无需浏览器 DOM）
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

// 4. ErrorCard 完整渲染（含两类按钮）
const fullCard = uiKit.ErrorCard({
  what: "数据库连接已被上游断开",
  todo: "请检查网络链路后点击重试",
  onFix: () => {},
  onDiagnostics: () => {},
});
out.fullCardHtml = vnodeToHtml(fullCard);

// 5. ErrorCard 缺省按钮渲染
const minimalCard = uiKit.ErrorCard({
  what: "当前用户无权访问此页面",
  todo: "请联系系统管理员开通相关权限",
});
out.minimalCardHtml = vnodeToHtml(minimalCard);

// 6. FixIt 渲染
const fixItBtn = uiKit.FixIt({ label: "立即恢复", disabled: true });
out.fixItHtml = vnodeToHtml(fixItBtn);

// 7. Skeleton 骨架屏渲染
const skeletonVNode = uiKit.Skeleton({ rows: 5 });
out.skeletonHtml = vnodeToHtml(skeletonVNode);

console.log(JSON.stringify(out));
"""


def _run_node_suite() -> dict:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", _NODE_TEST_SCRIPT, HOST_STATIC.as_uri()],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, f"Node 执行失败:\n{result.stderr}"
    lines = result.stdout.strip().splitlines()
    assert lines, "Node 执行未产生输出"
    return json.loads(lines[-1])


def test_ui_kit_and_glossary_exports() -> None:
    """断言 ui-kit.js 与 glossary.js 导出齐全。"""
    data = _run_node_suite()

    # ui-kit 导出
    ui_exports = data["uiKitExports"]
    assert ui_exports["hasErrorCard"] is True
    assert ui_exports["hasFixIt"] is True
    assert ui_exports["hasSkeleton"] is True
    assert ui_exports["hasTone"] is True
    assert ui_exports["toneKeys"] == ["bad", "off", "ok", "warn"]
    assert ui_exports["toneValues"] == {
        "ok": "ok",
        "warn": "warn",
        "bad": "bad",
        "off": "off",
    }
    assert ui_exports["hasHtml"] is True

    # glossary 导出
    glossary_exports = data["glossaryExports"]
    assert glossary_exports["hasBanned"] is True
    assert glossary_exports["bannedLength"] >= 5
    assert glossary_exports["hasScanText"] is True


def test_glossary_rules_match_repository_gate() -> None:
    """词表一致性：运行时 glossary.js 的规则必须与仓库门禁（test_glossary_terms）一致。

    源级门禁与 DSH-V2-40 的 DOM 门禁都用 ``EXACT_BANNED_TERMS`` / 两个路径正则判定；
    若只改 ``web/static/host/glossary.js`` 的词表，页面内 ``scanText`` 会变严/变松而
    门禁不自知。这里用真实 Node 模块把两边锁在一起（不改任何规则强度）。
    """
    from tests.test_glossary_terms import EXACT_BANNED_TERMS, scan_text_segment

    data = _run_node_suite()

    literals = data["bannedLiterals"]
    assert sorted(literals) == sorted(EXACT_BANNED_TERMS), (
        "glossary.js 的字面量禁词与仓库门禁 EXACT_BANNED_TERMS 不一致：\n"
        f"  运行时={sorted(literals)}\n"
        f"  门禁={sorted(EXACT_BANNED_TERMS)}"
    )

    patterns = data["bannedPatterns"]
    assert any("a-zA-Z]:" in pattern for pattern in patterns), (
        f"glossary.js 缺少盘符路径特征（盘符路径规则）：{patterns}"
    )
    assert any("\\.py" in pattern for pattern in patterns), (
        f"glossary.js 缺少 .py 脚本后缀特征：{patterns}"
    )

    # 两侧对同一段文本给出同样的术语名，避免只改名字导致门禁漏判。
    samples = (
        (data["scanHitDrive"], "例如：D:\\VSE\\archive 归档文件目录", "盘符路径"),
        (data["scanHitPy"], "请检查并执行 python tools/tir_probe.py 取证脚本", ".py 后缀"),
    )
    for runtime_hits, sample, expected in samples:
        assert expected in {hit["term"] for hit in runtime_hits}
        assert expected in {term for term, _ in scan_text_segment(sample)}


def test_scan_text_logic_under_node() -> None:
    """断言 scanText 能准确定位禁词与代码路径特征，干净文本无误报。"""
    data = _run_node_suite()

    assert data["scanClean"] == []

    # 各禁词命中判定
    assert any(h["term"] == "JSON" for h in data["scanHitJson"])
    assert any(h["term"] == "Base URL" for h in data["scanHitBaseUrl"])
    assert any(h["term"] == "Worker" for h in data["scanHitWorker"])
    assert any(h["term"] == "快照" for h in data["scanHitSnapshot"])
    assert any(h["term"] == "取证" for h in data["scanHitForensics"])
    assert any(h["term"] == "盘符路径" for h in data["scanHitDrive"])
    assert any(h["term"] == ".py 后缀" for h in data["scanHitPy"])

    # 检查命中位置属性字段完整
    for hit in data["scanHitJson"]:
        assert "term" in hit
        assert "word" in hit
        assert "match" in hit
        assert "index" in hit
        assert isinstance(hit["index"], int)


def test_error_card_rendered_structure_under_node() -> None:
    """断言 ErrorCard 用真 htm 渲染出符合规范的预期结构，且按钮可缺省。"""
    data = _run_node_suite()

    full_html = data["fullCardHtml"]
    assert 'role="alert"' in full_html
    assert "发生了什么" in full_html
    assert "数据库连接已被上游断开" in full_html
    assert "你需要做什么" in full_html
    assert "请检查网络链路后点击重试" in full_html
    assert "一键处理" in full_html
    assert "导出诊断包" in full_html

    min_html = data["minimalCardHtml"]
    assert 'role="alert"' in min_html
    assert "发生了什么" in min_html
    assert "当前用户无权访问此页面" in min_html
    assert "你需要做什么" in min_html
    assert "请联系系统管理员开通相关权限" in min_html
    # 缺省时不可渲染动作按钮
    assert "一键处理" not in min_html
    assert "导出诊断包" not in min_html


def test_fixit_and_skeleton_rendered_under_node() -> None:
    """断言 FixIt 按钮与 Skeleton 骨架屏渲染正确。"""
    data = _run_node_suite()

    fix_html = data["fixItHtml"]
    assert "立即恢复" in fix_html
    assert 'disabled="true"' in fix_html or "disabled" in fix_html

    sk_html = data["skeletonHtml"]
    assert "uk-skeleton" in sk_html
    assert sk_html.count("uk-skeleton-row") == 5
