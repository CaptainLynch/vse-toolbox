# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 构建脚本：产出无外部依赖的双 exe（主 WebUI + Excel 工作进程）。

用法（仓库根目录）:
    pip install pyinstaller
    python -m PyInstaller --noconfirm webui.spec

产物:
    dist/VSE-Toolbox-WebUI.exe   本地 Web 控制台（默认 127.0.0.1:5000）
    dist/VSE-ExcelWorker.exe     Excel 任务工作进程（WebUI 同目录自动发现）

数据落位（冻结态由 core/runtime_paths.app_root 决定）: exe 所在目录/data。
"""

datas = [
    ("web/templates", "web/templates"),
    ("web/static", "web/static"),
    # 运行时数据文件：core/report_contracts.py 以 __file__ 同目录定位，
    # 缺失会导致 Aras 查询报 FileNotFoundError。
    ("core/report_headers.json", "core"),
]

excludes = ["pytest", "flake8", "mypy"]

webui_a = Analysis(
    ["webui.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
webui_pyz = PYZ(webui_a.pure)

exe_webui = EXE(
    webui_pyz,
    webui_a.scripts,
    webui_a.binaries,
    webui_a.zipfiles,
    webui_a.datas,
    name="VSE-Toolbox-WebUI",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)

# Excel 工作进程冻结契约见 services/excel_worker_process_controller.start：
# 主程序在自身目录查找 VSE-ExcelWorker.exe 并以
# `run --db <path> --stop-file <path> [--root ID=PATH ...]` 方式调用。
worker_a = Analysis(
    ["excel_worker_entry.py"],
    pathex=["tools"],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
worker_pyz = PYZ(worker_a.pure)

exe_worker = EXE(
    worker_pyz,
    worker_a.scripts,
    worker_a.binaries,
    worker_a.zipfiles,
    worker_a.datas,
    name="VSE-ExcelWorker",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)
