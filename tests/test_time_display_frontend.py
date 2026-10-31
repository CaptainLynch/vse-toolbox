# -*- coding: utf-8 -*-
"""前端时间展示门禁（REQUIREMENTS F8 / 契约 C9）。

1. 时间点展示一律 zh-CN + 24 小时制（hour12: false），不允许依赖运行环境默认 locale；
2. toISOString 只允许用于内部时间戳/文件名（白名单钉住现有内部用法）；
3. 纯日期字段（slice(0, 10)）不在本门禁范围（后端载荷已是北京时间字符串）。
"""

from __future__ import annotations

import re
from pathlib import Path

PLUGINS_STATIC = Path(__file__).resolve().parent.parent / "plugins"


def test_time_displays_use_explicit_zh_cn_locale() -> None:
    """不带显式 zh-CN/hour12 的 toLocale* 展示点 = 环境 related locale 泄漏，一律禁止。"""
    offenders = []
    for js in PLUGINS_STATIC.glob("*/static/**/*.js"):
        for i, line in enumerate(js.read_text(encoding="utf-8").splitlines(), start=1):
            if "toLocaleTimeString()" in line or re.search(r"toLocaleString\(\)", line):
                offenders.append(f"{js.relative_to(PLUGINS_STATIC.parent)}:{i}: {line.strip()[:80]}")
    assert not offenders, "时间展示必须显式 zh-CN + hour12:false：\n" + "\n".join(offenders)


def test_to_iso_string_only_for_internal_stamps() -> None:
    """toISOString 现存用法均为内部时间戳/文件名（白名单钉住）；新展示点必须走 zh-CN 格式化。"""
    allowed = {
        "plugins/workbench/static/wizard.js",
        "plugins/system_query/static/query.js",
    }
    for js in PLUGINS_STATIC.glob("*/static/**/*.js"):
        rel = js.relative_to(PLUGINS_STATIC.parent).as_posix()
        if rel in allowed:
            continue
        text = js.read_text(encoding="utf-8")
        assert "toISOString()" not in text, f"{rel} 出现新的 toISOString 展示点，请走显式 zh-CN 格式化"
