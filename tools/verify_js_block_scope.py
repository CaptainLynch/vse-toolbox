# -*- coding: utf-8 -*-
"""手动排查工具：扫描前端脚本里「在块内用 const/let 声明、却在包围块之外仍被引用」
的标识符。

来源：2026-09-28 生产回归 —— `const departmentLabel` 被移进 `if (!isNcr) {` 块，
而 `remountWizardInputs` 在块外引用它，点击「开始配置并启用」即抛 ReferenceError
（按钮消失、同步未发起）。`node --check` 只验语法，查不出这类运行时错误。

用法（仓库根目录执行）：

    python tools/verify_js_block_scope.py [--file web/static/app.js]

定位：**手动排查工具，不是门禁**。启发式扫描信噪比偏低（首轮实测 12 条候选 /
1 条真阳性，其余为函数参数名、对象属性键与解构声明的假阳性），入 pytest 会持续误报；
同类缺陷的正式守护由 `tests/frontend_behavior_gate.cjs`（行为层）与
`tests/frontend_regression_mutations.cjs`（回归变异自检）承担。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DECL = re.compile(r"^(\s*)(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=")
FUNC_START = re.compile(r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)|^(?:async\s+)?function\s*\(")
BOUNDARY = re.compile(r"^\}\s*(?:else|catch|while|finally|\)|;|,|\.|\+|\?|:|\|\||&&)")


def project_code(text: str) -> str:
    """把字符串/模板/注释内容替换为等长空白，保留换行与结构，避免误命中文案与选择器。"""
    out = list(text)
    i = 0
    n = len(text)
    state = "code"
    while i < n:
        ch = text[i]
        if state == "code":
            if ch == "/" and i + 1 < n and text[i + 1] == "/":
                state = "line_comment"
                out[i] = " "
                i += 1
                continue
            if ch == "/" and i + 1 < n and text[i + 1] == "*":
                state = "block_comment"
                out[i] = " "
                i += 1
                continue
            if ch in "\"'`":
                state = ch
                i += 1
                continue
        elif state == "line_comment":
            if ch == "\n":
                state = "code"
            else:
                out[i] = " "
        elif state == "block_comment":
            if ch == "*" and i + 1 < n and text[i + 1] == "/":
                out[i] = " "
                out[i + 1] = " "
                i += 2
                state = "code"
                continue
            if ch != "\n":
                out[i] = " "
        elif state in ("'", '"', "`"):
            if ch == "\\":
                out[i] = " "
                if i + 1 < n and text[i + 1] != "\n":
                    out[i + 1] = " "
                i += 2
                continue
            if ch == state:
                state = "code"
            elif ch != "\n":
                out[i] = " "
        i += 1
    return "".join(out)


def scan(path: Path) -> list[tuple[str, int, int, int, int, str]]:
    raw_lines = path.read_text(encoding="utf-8-sig").splitlines()
    code_lines = project_code("\n".join(raw_lines)).splitlines()

    declarations: dict[str, list[tuple[int, int]]] = {}
    for index, line in enumerate(code_lines):
        match = DECL.match(line)
        if match:
            declarations.setdefault(match.group(2), []).append((index, len(match.group(1).expandtabs(4))))

    # 顶层函数区域划分：排除"同名标识符出现在另一个函数里"的假阳性。
    region: list[str] = [""] * len(code_lines)
    current = "<global>"
    for index, line in enumerate(code_lines):
        if FUNC_START.match(line):
            current = FUNC_START.match(line).group(1) or "<anonymous>"
        region[index] = current
        if line.rstrip() == "}" and not line.startswith(" "):
            current = "<global>"

    hits: list[tuple[str, int, int, int, int, str]] = []
    for name, entries in declarations.items():
        if len(entries) != 1:
            continue
        decl_index, decl_indent = entries[0]
        if decl_indent < 4:
            continue
        close_index = None
        for index in range(decl_index + 1, len(code_lines)):
            stripped = code_lines[index].lstrip()
            if not stripped.startswith("}"):
                continue
            indent = len(code_lines[index]) - len(stripped)
            if indent < decl_indent and not BOUNDARY.match(code_lines[index].strip()):
                close_index = index
                break
        if close_index is None:
            continue
        use = re.compile(r"(?<![\w$.])" + re.escape(name) + r"(?![\w$])")
        for index in range(close_index + 1, len(code_lines)):
            if region[index] != region[decl_index]:
                continue
            if use.search(code_lines[index]):
                hits.append(
                    (name, decl_index + 1, decl_indent, close_index + 1, index + 1, raw_lines[index].strip()[:100])
                )
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描块内声明、块外引用的标识符（手动排查）")
    parser.add_argument("--file", default="web/static/app.js", help="相对仓库根目录的前端脚本路径")
    args = parser.parse_args()

    target = (REPO_ROOT / args.file).resolve()
    if not target.exists():
        print(f"文件不存在：{target}", file=sys.stderr)
        return 1

    hits = scan(target)
    print(f"扫描 {args.file}：{len(hits)} 条候选（需人工复核；启发式假阳性已知偏高）")
    for name, decl_line, decl_indent, close_line, use_line, text in hits:
        print(f"  {name}: 声明 L{decl_line}(indent {decl_indent}) 包围块闭合 L{close_line} → 块外引用 L{use_line}: {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
