# -*- coding: utf-8 -*-
"""术语门禁测试：扫描前端 JS 页面中的可见文案，禁止内部实现黑话与代码路径泄露给用户。

门禁规则：
1. 扫描 plugins/*/static/*.js（含子目录）与 web/static/host/*.js 中的字符串字面量与模板串；
2. 禁词范围：JSON、Base URL、Worker、快照、取证，以及 Windows 盘符路径与 .py 脚本后缀特征；
3. 纯代码注释（// 与 /* */）及 import/export 模块路径不作为界面文案参与校验；
4. 基线控制：以 tests/golden/glossary_baseline.json 为准；
   - 基线外出现新命中 -> 测试失败并报错 文件:行 与词；
   - 基线条目在对应文件中已不再命中 -> 测试失败，要求删除基线项
     （DSH-V2-40 已删除 plugins/deliverables 下 2 项过期条目，不再保留过期登记）；
   - 每一条基线项都必须在 BASELINE_AUDIT 里有一句话理由（白名单逐项审计）。
5. 编码规范：所有 .js 文件必须以 UTF-8 读取，遇到无法解码报错。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_FILE = REPO_ROOT / "tests" / "golden" / "glossary_baseline.json"

#: DSH-V2-40：任务开始时（e1f40ba）既有白名单的 (文件, 术语) 项数——21 个文件 / 23 项。
#: 这是「白名单不得增大」的预算上限，不是当前有效条目数：本轮删除了 2 项
#: plugins/deliverables/... 过期条目，当前有效条目数见 BASELINE_EFFECTIVE_ENTRIES。
BASELINE_WHITELIST_ENTRIES = 23

#: 本轮从基线删除的过期条目数：plugins/deliverables 插件已下线，文件不存在。
BASELINE_STALE_ENTRIES_REMOVED = 2

#: 主控补丁修正产品文案后删除的基线条目数：deliverable_forms/static/index.js「快照」。
BASELINE_FIXED_ENTRIES_REMOVED = 1

#: 删除过期与已修正条目后的基线有效条目数（20）；DOM 门禁的预算口径同用此值。
BASELINE_EFFECTIVE_ENTRIES = (
    BASELINE_WHITELIST_ENTRIES - BASELINE_STALE_ENTRIES_REMOVED - BASELINE_FIXED_ENTRIES_REMOVED
)

#: 既有白名单逐项审计：键 = (文件, 术语)，值 = 一句话理由（为什么允许保留）。
#: 基线增删必须同步改这里，否则 test_baseline_whitelist_audit_is_justified 失败。
#: 说明：这些是历史遗留的用户文案例外（部分已由 test_dsh_v2_40.py 的 DOM 门禁
#: 单独登记为 KNOWN_VIOLATIONS）；保留基线不等于认可文案，清理需产品侧任务。
BASELINE_AUDIT: dict[tuple[str, str], str] = {
    (
        "plugins/project_overview/static/archive-deliverable.js",
        "快照",
    ): "归档详情页「正在刷新表单快照」等后台进度提示，属既有用户可见文案，待文案清理。",
    (
        "plugins/project_overview/static/deliverable/analysis.js",
        "快照",
    ): "交付物分析页「快照时间 / 暂无分析快照」等统计口径文案，历史遗留。",
    (
        "plugins/project_overview/static/deliverable/detail.js",
        "快照",
    ): "交付物明细页「表单快照 / 正在刷新表单快照」等刷新与口径文案，历史遗留。",
    (
        "plugins/project_overview/static/deliverable/discovery.js",
        "取证",
    ): "外部同步映射「映射取证」流程提示，属产品既有术语，待文案清理。",
    (
        "plugins/project_overview/static/deliverable/display.js",
        "快照",
    ): "交付物展示层「无快照时间」空态文案，历史遗留。",
    (
        "plugins/project_overview/static/deliverable/evidence.js",
        "JSON",
    ): "证据页「下载 JSON」按钮文案，属面向高级用户的导出动作，历史遗留。",
    (
        "plugins/project_overview/static/deliverable/evidence.js",
        "取证",
    ): "证据页「读取证据失败」等取证流程提示，历史遗留。",
    (
        "plugins/project_overview/static/deliverable/form-analysis.js",
        "快照",
    ): "表单分析页多处「快照时间 / 快照方差」统计文案，历史遗留。",
    (
        "plugins/project_overview/static/deliverable/policy-logic.js",
        "取证",
    ): "同步规则页「重新抓取证据 / 映射稳定性核验」提示，历史遗留。",
    (
        "plugins/project_overview/static/deliverable/status-chart.js",
        "快照",
    ): "状态图「统计来自最近一次 EWO 快照」等口径说明，历史遗留。",
    (
        "plugins/project_overview/static/details/external.js",
        "快照",
    ): "交付物明细外部来源区块的快照口径说明，历史遗留。",
    (
        "plugins/project_overview/static/details/sync-settings-logic.js",
        "JSON",
    ): "同步筛选条件校验提示「必须是 JSON 对象」，面向配置用户，历史遗留。",
    (
        "plugins/project_overview/static/shared/status-logic.js",
        "快照",
    ): "状态文案「更新异常 · 保留上次快照」，历史遗留。",
    (
        "plugins/scheduled_archive/static/archive_data.js",
        "JSON",
    ): "归档条件校验提示「必须是 JSON 对象」，历史遗留。",
    (
        "plugins/scheduled_archive/static/jobs.js",
        "JSON",
    ): "高级下载条件「下载条件 JSON（兼容旧配置）」表单标签，历史遗留。",
    (
        "plugins/scheduled_archive/static/jobs.js",
        "盘符路径",
    ): "归档目录输入框示例占位符「例如：D:\\VSE\\archive」，是引导用户填本机路径的示例，非内部代码路径泄露。",
    (
        "plugins/settings/static/settings-form.js",
        "快照",
    ): "设置页「历史快照保留数量 / 快照策略」保留策略文案，历史遗留。",
    (
        "plugins/system_query/static/query.js",
        "Base URL",
    ): "系统查询页「请求上下文 · Base URL」字段标签，面向高级查询用户，历史遗留。",
    (
        "plugins/workbench/static/tools.js",
        "Base URL",
    ): "工具页专家模式说明「系统查询（Base URL / XML）」，历史遗留。",
    (
        "web/static/host/session.js",
        "JSON",
    ): "源级提取器把代码里的 JSON.stringify 与注释误当可见文案（该文件无面向用户的 JSON 字样）；"
    "DOM 门禁未在宿主外壳发现该词，保留基线以免改动提取规则强度。",
}

# 禁用术语定义（与 web/static/host/glossary.js 保持一致）
EXACT_BANNED_TERMS = ("JSON", "Base URL", "Worker", "快照", "取证")
# 盘符只认反斜杠：URL 里的 s:// 不是代码路径（2026-10-31 修复误报）。
DRIVE_PATH_REGEX = re.compile(r"[a-zA-Z]:\\[^\s\"'`<>]*")
PY_SUFFIX_REGEX = re.compile(r"\b[a-zA-Z0-9_.-]+\.py\b")


@dataclass(frozen=True)
class GlossaryHit:
    file_path: str
    line: int
    term: str
    match: str


def read_js_file_utf8(path: Path) -> str:
    """读取 JS 文件内容，强制 UTF-8；无法解码时抛出异常阻断，禁止静默跳过。"""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"文件无法使用 UTF-8 解码: {path}，原因: {exc}") from exc


def extract_js_visible_strings(content: str) -> list[tuple[int, str]]:
    """从 JS 源码中提取单引号、双引号与模板字符串片段。

    过滤规则：
    - 跳过 // 单行注释与 /* */ 多行注释（注释面向开发者，不属于界面文案）；
    - 跳过 import 与 export from 模块路径；
    - 解析模板字符串中的静态文本（quasi），并在进入 ${...} 表达式时解析嵌套的字符串字面量。
    """
    length = len(content)
    index = 0
    line = 1
    strings: list[tuple[int, str]] = []

    while index < length:
        ch = content[index]

        # 换行行号递增
        if ch == "\n":
            line += 1
            index += 1
            continue

        # 单行注释 //
        if ch == "/" and index + 1 < length and content[index + 1] == "/":
            index += 2
            while index < length and content[index] != "\n":
                index += 1
            continue

        # 多行注释 /* ... */
        if ch == "/" and index + 1 < length and content[index + 1] == "*":
            index += 2
            while index + 1 < length and not (content[index] == "*" and content[index + 1] == "/"):
                if content[index] == "\n":
                    line += 1
                index += 1
            index += 2
            continue

        # 过滤 import / export 静态依赖导入语句
        if content.startswith(("import ", "export "), index):
            semicolon = index
            while semicolon < length and content[semicolon] not in (";", "\n"):
                semicolon += 1
            chunk = content[index:semicolon]
            if " from " in chunk or chunk.strip().startswith(('import "', "import '")):
                line += chunk.count("\n")
                index = semicolon
                continue

        # 单引号或双引号字符串
        if ch in ("'", '"'):
            quote = ch
            start_line = line
            index += 1
            buf: list[str] = []
            while index < length and content[index] != quote:
                if content[index] == "\n":
                    line += 1
                    buf.append("\n")
                    index += 1
                elif content[index] == "\\" and index + 1 < length:
                    buf.append(content[index:index + 2])
                    if content[index + 1] == "\n":
                        line += 1
                    index += 2
                else:
                    buf.append(content[index])
                    index += 1
            if index < length and content[index] == quote:
                index += 1
            strings.append((start_line, "".join(buf)))
            continue

        # 模板字符串 `...`
        if ch == "`":
            index += 1
            start_line = line
            quasi_buf: list[str] = []
            while index < length:
                curr = content[index]
                if curr == "`":
                    if quasi_buf:
                        strings.append((start_line, "".join(quasi_buf)))
                    index += 1
                    break
                elif curr == "\n":
                    line += 1
                    quasi_buf.append("\n")
                    index += 1
                elif curr == "\\" and index + 1 < length:
                    quasi_buf.append(content[index:index + 2])
                    if content[index + 1] == "\n":
                        line += 1
                    index += 2
                elif curr == "$" and index + 1 < length and content[index + 1] == "{":
                    if quasi_buf:
                        strings.append((start_line, "".join(quasi_buf)))
                        quasi_buf = []
                    index += 2
                    depth = 1
                    while index < length and depth > 0:
                        inner = content[index]
                        if inner == "\n":
                            line += 1
                            index += 1
                        elif inner == "/" and index + 1 < length and content[index + 1] == "/":
                            index += 2
                            while index < length and content[index] != "\n":
                                index += 1
                        elif inner == "/" and index + 1 < length and content[index + 1] == "*":
                            index += 2
                            while index + 1 < length and not (content[index] == "*" and content[index + 1] == "/"):
                                if content[index] == "\n":
                                    line += 1
                                index += 1
                            index += 2
                        elif inner in ("'", '"'):
                            eq = inner
                            eq_line = line
                            index += 1
                            ebuf: list[str] = []
                            while index < length and content[index] != eq:
                                if content[index] == "\n":
                                    line += 1
                                    ebuf.append("\n")
                                    index += 1
                                elif content[index] == "\\" and index + 1 < length:
                                    ebuf.append(content[index:index + 2])
                                    if content[index + 1] == "\n":
                                        line += 1
                                    index += 2
                                else:
                                    ebuf.append(content[index])
                                    index += 1
                            if index < length and content[index] == eq:
                                index += 1
                            strings.append((eq_line, "".join(ebuf)))
                        elif inner == "{":
                            depth += 1
                            index += 1
                        elif inner == "}":
                            depth -= 1
                            index += 1
                        else:
                            index += 1
                    start_line = line
                else:
                    quasi_buf.append(curr)
                    index += 1
            continue

        index += 1

    return strings


def scan_text_segment_occurrences(text: str) -> list[tuple[str, str, int]]:
    """检测一段字符串，返回**每一次**命中 ``(term_name, matched_text, start)``。

    与 ``scan_text_segment`` 不同，这里不去重：同一术语出现几次就返回几项，
    并带上命中在原文中的起始下标。DOM 门禁需要据此区分「登记文案内」与
    「同词其他位置」，不能用 ``(term, source)`` 去重后只留首个命中。
    """
    hits: list[tuple[str, str, int]] = []

    # 精确匹配字面量词汇：枚举所有出现位置。
    for term in EXACT_BANNED_TERMS:
        start = text.find(term)
        while start >= 0:
            hits.append((term, term, start))
            start = text.find(term, start + len(term))

    # 正则匹配 Windows 盘符代码路径特征。
    for match in DRIVE_PATH_REGEX.finditer(text):
        hits.append(("盘符路径", match.group(0), match.start()))

    # 正则匹配 .py 脚本文件特征。
    for match in PY_SUFFIX_REGEX.finditer(text):
        hits.append((".py 后缀", match.group(0), match.start()))

    hits.sort(key=lambda item: (item[2], item[0]))
    return hits


def scan_text_segment(text: str) -> list[tuple[str, str]]:
    """检测一段字符串是否命中禁用术语规则，返回 [(term_name, matched_text), ...] 列表。

    保持既有契约：每个术语最多返回一项（首次出现），供源级扫描与词表一致性测试使用。
    """
    hits: list[tuple[str, str]] = []
    seen: set[str] = set()
    for term, match, _start in scan_text_segment_occurrences(text):
        if term in seen:
            continue
        seen.add(term)
        hits.append((term, match))
    return hits


def collect_target_files(repo_root: Path) -> list[Path]:
    """收集需要检查的前端文件：
    - plugins/*/static/ 下的所有 JS 文件（含子目录）
    - web/static/host/*.js（排除 glossary.js 自身）
    """
    targets: set[Path] = set()
    for js_path in repo_root.glob("plugins/*/static/**/*.js"):
        targets.add(js_path)
    for js_path in repo_root.glob("plugins/*/static/*.js"):
        targets.add(js_path)
    for js_path in repo_root.glob("web/static/host/*.js"):
        if js_path.name != "glossary.js":
            targets.add(js_path)
    return sorted(targets)


def scan_repository_for_glossary_hits(repo_root: Path) -> dict[str, list[GlossaryHit]]:
    """扫描所有目标文件并返回按文件归类的命中清单。"""
    hits_by_file: dict[str, list[GlossaryHit]] = {}
    files = collect_target_files(repo_root)

    for file_path in files:
        rel_posix = file_path.relative_to(repo_root).as_posix()
        content = read_js_file_utf8(file_path)
        extracted = extract_js_visible_strings(content)

        file_hits: list[GlossaryHit] = []
        for line_no, text_val in extracted:
            matched_terms = scan_text_segment(text_val)
            for term_name, matched_str in matched_terms:
                file_hits.append(
                    GlossaryHit(
                        file_path=rel_posix,
                        line=line_no,
                        term=term_name,
                        match=matched_str,
                    )
                )

        if file_hits:
            hits_by_file[rel_posix] = file_hits

    return hits_by_file


def test_glossary_terms_gate() -> None:
    """断言前端页面不出现禁词：基线外新命中即失败，无命中的旧基线条目提示人工收紧。"""
    assert BASELINE_FILE.is_file(), f"未找到基线文件: {BASELINE_FILE}"
    baseline_data: dict[str, list[str]] = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))

    current_hits_by_file = scan_repository_for_glossary_hits(REPO_ROOT)

    # 1. 断言：基线之外的新命中 -> 失败并报 文件:行 与词
    new_violations: list[str] = []
    for file_rel, hits in current_hits_by_file.items():
        allowed_terms = set(baseline_data.get(file_rel, []))
        for hit in hits:
            if hit.term not in allowed_terms:
                # 匹配内容只露前 6 字符：命中可能带内网地址等敏感串，测试输出不许外泄。
                new_violations.append(
                    f"{hit.file_path}:{hit.line} 发现未登记禁词 [{hit.term}] "
                    f"(匹配内容前 6 字符: {hit.match[:6]!r}…，完整内容已脱敏)"
                )

    if new_violations:
        msg = (
            "检测到未在基线中登记的前端内部术语违规，请替换为通俗中文文案：\n"
            + "\n".join(f"  - {item}" for item in new_violations)
        )
        pytest.fail(msg)

    # 2. 检查：基线条目若已不再命中 -> 直接失败，要求删除基线项（不再保留过期登记）
    stale_entries: list[tuple[str, str]] = []
    for file_rel, allowed_terms in baseline_data.items():
        actual_terms = {h.term for h in current_hits_by_file.get(file_rel, [])}
        for term in allowed_terms:
            if term not in actual_terms:
                stale_entries.append((file_rel, term))

    assert not stale_entries, (
        "基线出现过期条目（对应文件已不再命中该术语）：请删除 "
        "tests/golden/glossary_baseline.json 中的这些条目，并同步 BASELINE_AUDIT：\n"
        + "\n".join(f"  - {file_rel} -> [{term}]" for file_rel, term in stale_entries)
    )


def test_baseline_whitelist_audit_is_justified() -> None:
    """白名单逐项审计：有效项数 = 23 − 2 项过期 − 1 项已修正 = 20、每条都有理由、不得新增。"""
    assert BASELINE_FILE.is_file(), f"未找到基线文件: {BASELINE_FILE}"
    baseline_data: dict[str, list[str]] = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    entries = {(file_rel, term) for file_rel, terms in baseline_data.items() for term in terms}

    assert len(entries) == BASELINE_EFFECTIVE_ENTRIES, (
        f"基线有效项数不符：实测 {len(entries)} 项，期望 {BASELINE_EFFECTIVE_ENTRIES} 项"
        f"（任务开始时 {BASELINE_WHITELIST_ENTRIES} 项，本轮删除 "
        f"{BASELINE_STALE_ENTRIES_REMOVED} 项过期条目）。DSH-V2-40 要求白名单不得增大；"
        "确需变化必须同步更新常量并在报告中说明。"
    )
    assert len(entries) <= BASELINE_WHITELIST_ENTRIES, (
        f"基线项数 {len(entries)} 超过任务开始时的 {BASELINE_WHITELIST_ENTRIES} 项预算"
    )
    assert set(BASELINE_AUDIT) == entries, (
        "BASELINE_AUDIT 与 tests/golden/glossary_baseline.json 不是一一对应：\n"
        f"  缺理由={sorted(entries - set(BASELINE_AUDIT))}\n"
        f"  多余审计={sorted(set(BASELINE_AUDIT) - entries)}"
    )
    unjustified = sorted(key for key, reason in BASELINE_AUDIT.items() if len(reason.strip()) < 10)
    assert not unjustified, f"以下白名单项没有写出可核查的理由：{unjustified}"


def test_utf8_decoding_guard(tmp_path: Path) -> None:
    """验证 UTF-8 解码保护：遇到非 UTF-8 编码的文件抛出明确异常，绝不静默跳过。"""
    bad_file = tmp_path / "bad_encoding.js"
    bad_file.write_bytes(b"const text = '\xff\xfe\x00';")
    with pytest.raises(RuntimeError, match="无法使用 UTF-8 解码"):
        read_js_file_utf8(bad_file)


def test_comment_and_import_exclusion() -> None:
    """验证纯注释与模块导入路径不会被误判为可见文案。"""
    code = r"""
    // 这里包含注释 快照 与 JSON
    /* 这里包含多行注释
       Worker 与 Base URL
    */
    import { something } from "./worker.py";
    import "fast-json";
    export { other } from "./snapshot.py";
    const ok = "正常界面文案";
    """
    strings = extract_js_visible_strings(code)
    for _, text in strings:
        hits = scan_text_segment(text)
        assert not hits, f"注释或 import 内容被误判为可见文案: {text} -> {hits}"
