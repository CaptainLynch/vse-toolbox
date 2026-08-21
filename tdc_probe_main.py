# -*- coding: utf-8 -*-
"""
tdc_probe_main.py — VSE-TDC-Contract-Probe 专用入口。

被 PyInstaller 构建为 dist/VSE-TDC-Contract-Probe.exe。
不 import main，不构造 DatabaseManager，不初始化 SQLite，不启动 Flask。

用法：
    VSE-TDC-Contract-Probe.exe              — 交互式只读探测
    VSE-TDC-Contract-Probe.exe --help       — 用法说明
    VSE-TDC-Contract-Probe.exe --self-test  — 离线自检
"""

from __future__ import annotations

import sys
from typing import Sequence

from tdc_probe_cli import (
    parse_probe_args,
    run_probe,
    run_self_test,
)


def main(argv: Sequence[str] | None = None) -> int:
    """
    专用 EXE 主入口。

    - --self-test：离线自检，不访问网络，不创建持久文件。
    - 无参数或未知参数由 argparse 处理。
    - 正常运行：交互式只读探测。
    """
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = parse_probe_args(raw_argv)

    if args.self_test:
        return run_self_test()

    try:
        return run_probe()
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        from core.redaction import redact_sensitive_text
        print(f"探测运行失败: {redact_sensitive_text(str(exc), limit=500)}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
