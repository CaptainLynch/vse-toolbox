# -*- coding: utf-8 -*-
"""术语门禁测试：扫描前端 JS 页面中的可见文案，禁止内部实现黑话与代码路径泄露给用户。

门禁规则：
1. 扫描 plugins/*/static/*.js（含子目录）与 web/static/host/*.js 中的字符串字面量与模板串；
2. 禁词范围：JSON、Base URL、Worker、快照、取证，以及 Windows 盘符路径与 .py 脚本后缀特征；
3. 纯代码注释（// 与 /* */）及 import/export 模块路径不作为界面文案参与校验；
4. 基线控制：以 tests/golden/glossary_baseline.json 为准；
   - 基线外出现新命中 -> 测试失败并报错 文件:行 与词；
   - 基线条目在对应文件中已不再命中 -> 发出提示，提醒人工收紧基线（测试不自动改基线文件）；
5. 编码规范：所有 .js 文件必须以 UTF-8 读取，遇到无法解码报错。
"""

from __future__ import annotations

import json
import re
import warnings
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_FILE = REPO_ROOT / "tests" / "golden" / "glossary_baseline.json"

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


def scan_text_segment(text: str) -> list[tuple[str, str]]:
    """检测一段字符串是否命中禁用术语规则，返回 [(term_name, matched_text), ...] 列表。"""
    hits: list[tuple[str, str]] = []

    # 精确匹配字面量词汇
    for term in EXACT_BANNED_TERMS:
        if term in text:
            hits.append((term, term))

    # 正则匹配 Windows 盘符代码路径特征
    drive_match = DRIVE_PATH_REGEX.search(text)
    if drive_match:
        hits.append(("盘符路径", drive_match.group(0)))

    # 正则匹配 .py 脚本文件特征
    py_match = PY_SUFFIX_REGEX.search(text)
    if py_match:
        hits.append((".py 后缀", py_match.group(0)))

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

    # 2. 检查：基线条目对应文件若不再命中 -> 提示人工收紧（测试本身不改基线文件）
    stale_reports: list[str] = []
    for file_rel, allowed_terms in baseline_data.items():
        actual_hits = current_hits_by_file.get(file_rel, [])
        actual_terms = {h.term for h in actual_hits}
        for term in allowed_terms:
            if term not in actual_terms:
                stale_reports.append(f"{file_rel} -> [{term}]")

    if stale_reports:
        warnings.warn(
            UserWarning(
                "检测到已有历史页面已清理禁词，可人工收紧基线文件 tests/golden/glossary_baseline.json：\n"
                + "\n".join(f"  - {item}" for item in stale_reports)
            )
        )


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
