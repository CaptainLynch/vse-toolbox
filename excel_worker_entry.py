# -*- coding: utf-8 -*-
"""VSE-ExcelWorker.exe 冻结入口：转发到 tools/excel_worker_cli.main。

源码运行需要 tools 目录在导入路径上；冻结构建由 webui.spec 的 pathex 提供。
命令契约（由 ExcelWorkerProcessController 调用）:
    VSE-ExcelWorker.exe run --db <path> --stop-file <path> [--root ID=PATH ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))

from excel_worker_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
