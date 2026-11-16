# -*- mode: python ; coding: utf-8 -*-
"""
VSE-EWO-Verify.spec — EWO 导出件离线验证器（onefile, console）。

入口：ewo_verify_main.py
支持输入：程序「全量导出 CSV」产物（.csv）与上游官方报表工作簿（.xlsx）。
依赖面：core.report_contracts + core/report_headers.json、services.ewo_workbook、
services.ewo_official_rows、services.ewo_readonly、services.xlsx_preview、ewo_verify_cli。
全部为标准库实现；排除 Flask/requests/Aras 客户端/Web 层，保证生产机零依赖运行。
"""

a = Analysis(
    ["ewo_verify_main.py"],
    pathex=[],
    binaries=[],
    datas=[("core/report_headers.json", "core")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "flask",
        # sqlite3 不能排除：services.xlsx_preview → core.diagnostic_recording 会在导入期用到它。
        "requests",
        "urllib3",
        "certifi",
        "charset_normalizer",
        "idna",
        "web",
        "web.app",
        "web.crawler_boot",
        "services.aras_crawler",
        "services.aras_export",
        "services.aras_auth",
        "services.ewo_csv_export",
        "services.ewo_export_transport",
        "core.db_manager",
        "core.config",
        "core.diagnostics",
        "openpyxl",
        "pandas",
        "numpy",
    ],
    noarchive=False,
    cipher=None,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="VSE-EWO-Verify",
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
