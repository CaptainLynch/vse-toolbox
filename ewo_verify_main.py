"""VSE-EWO-Verify 入口（PyInstaller 单文件，无第三方依赖）。

打包产物用法：
    VSE-EWO-Verify.exe <官方 EWO 导出.xlsx> [--json] [--out result.csv]

Windows 控制台默认使用本地代码页（GBK），中文报告会在 UTF-8 终端显示为乱码；
这里把标准输出/错误统一切到 UTF-8，并保留 errors=replace 以免个别字符中断报告。
"""

from __future__ import annotations

import sys

from ewo_verify_cli import main


def _use_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


if __name__ == "__main__":
    _use_utf8_console()
    raise SystemExit(main(sys.argv[1:]))
