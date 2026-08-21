# -*- mode: python ; coding: utf-8 -*-
"""
VSE-TDC-Probe.spec — 专用 TDC 契约探测 EXE 的 PyInstaller 规格。

入口：tdc_probe_main.py
模式：onefile, console=True

不打包 main.py、DatabaseManager、Flask、WebUI、Excel、Aras、Feishu 或
项目状态同步模块。
"""

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# ── 隐式依赖 ────────────────────────────────────────────────────
hiddenimports = [
    "pythoncom",
    "pywintypes",
    "win32timezone",
    "win32com",
    "win32com.client",
    "win32com.client.gencache",
    "requests",
    # core.redaction is required by the probe.  tdc_crawler imports
    # core.runtime_paths, but the probe always passes an explicit output_dir
    # so app_root() is never called.
    "core.redaction",
]

# Rich 子模块（console/table/panel/prompt/text 等）
hiddenimports += collect_submodules("rich")

# win32com 子模块
hiddenimports += collect_submodules("win32com")

# ── 明确排除 ────────────────────────────────────────────────────
excludes = [
    "flask",
    "sqlite3",
    "xlwings",
    "selenium",
    "imapclient",
    "openpyxl",
    "pandas",
    "numpy",
    "web",
    "web.app",
    "services.intranet_scraper",
    "services.feishu_imap",
    "services.aras_auth",
    "services.aras_crawler",
    "services.aras_export",
    "services.aras_department_mapping",
    "services.project_status_updates",
    "services.project_status_sync_runner",
    "services.excel_toolbox",
    "services.office_toolbox",
    "core.db_manager",
    "core.config",
    "core.diagnostics",
    "main",
]

a = Analysis(
    ["tdc_probe_main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="VSE-TDC-Contract-Probe",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    argv_emulation=False,
    target_arch=None,
    icon=None,
)
