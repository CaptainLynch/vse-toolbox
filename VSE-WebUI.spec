# -*- mode: python ; coding: utf-8 -*-

import atexit
import json
import os
import shutil
import tempfile
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


def _clean_build_field(val, limit=100):
    if not isinstance(val, str):
        return None
    cleaned = val.strip()
    if not cleaned or len(cleaned) > limit:
        return None
    for ch in cleaned:
        if ord(ch) < 32 or (127 <= ord(ch) <= 159):
            return None
    return cleaned


version_datas = []
raw_build_version = os.environ.get("VSE_TOOLBOX_VERSION")
build_version = _clean_build_field(raw_build_version)
if build_version:
    build_channel = _clean_build_field(os.environ.get("VSE_TOOLBOX_CHANNEL")) or "standalone-exe"
    build_id = _clean_build_field(os.environ.get("VSE_TOOLBOX_BUILD_ID")) or _clean_build_field(os.environ.get("GITHUB_SHA"))
    version_payload = {
        "version": build_version,
        "channel": build_channel,
        "buildId": build_id,
    }
    temp_dir = Path(tempfile.mkdtemp(prefix="vse_version_build_"))
    atexit.register(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
    vjson_file = temp_dir / "version.json"
    vjson_file.write_text(json.dumps(version_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    version_datas.append((str(vjson_file), "."))

hiddenimports = ['requests', 'tkinter', 'tkinter.filedialog']
# WinHTTP via COM (WinHttp.WinHttpRequest.5.1) is the WebUI's HTTP transport for
# Aras/TDC auth on win32; pythoncom + pywintypes + win32com.client are imported
# lazily inside services/windows_http.py and services/aras_auth.py, so PyInstaller
# static analysis cannot see them.
hiddenimports += [
    'pythoncom',
    'pywintypes',
    'win32crypt',
    'win32timezone',
    'win32com.client',
    'win32com.client.gencache',
]
# 单 exe 部署（2026-10-09 顾问复核方案 A）：宿主同时承担 Excel Worker 角色，
# 通过 `--excel-worker` 哨兵自调起子进程（webui.py）。因此 Excel 自动化依赖
# 必须收进本包——原先它们只在独立的 VSE-ExcelWorker.exe 里。
hiddenimports += ['excel_worker_cli']
hiddenimports += collect_submodules('win32com')
hiddenimports += collect_submodules('xlwings')
# Selenium is used only by the optional CLI intranet scraper.  The WebUI
# entrypoint does not import or expose that scraper, so collecting every
# Selenium submodule needlessly adds roughly 28 MB to the standalone bundle.


a = Analysis(
    ['webui.py'],
    # tools/ 需在 pathex 上：worker 哨兵分支惰性导入 excel_worker_cli（tools 下），
    # 静态分析看不到这条动态导入，靠 hiddenimports + pathex 一并收进来。
    pathex=['tools'],
    binaries=[],
    datas=[
        ('web/templates', 'web/templates'),
        ('web/static', 'web/static'),
        ('core/report_headers.json', 'core'),
        ('host/trusted_keys.json', 'host'),
        *version_datas,
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # These integrations are CLI-only and are exposed through services' lazy
    # exports.  The WebUI has no execution path for them; excluding the lazy
    # modules also keeps their optional Selenium/IMAP dependency trees out of
    # the standalone WebUI package.  xlwings is NOT excluded any more: the host
    # doubles as the Excel Worker (single-exe deployment).
    excludes=[
        'selenium',
        'services.intranet_scraper',
        'services.feishu_imap',
        'services.office_toolbox',
        # PyInstaller's Python 3.14 hooks otherwise include packaging/build
        # tooling that is not imported by the runtime application.
        'setuptools',
        '_distutils_hack',
        # Dynamic WinHTTP dispatch does not use makepy/type-library browsers;
        # these optional pywin32 helpers are the source of pythonwin/win32ui.
        # 注：xlwings 在导入期调用 gencache.EnsureModule（UDF 早绑定用，包在
        # 裸 except 里）；本产品不用 UDF，因此保留这些排除。真机验收需覆盖
        # “清空 %TEMP%\gen_py 后首次运行成功”。
        'win32com.client.makepy',
        'win32com.client.selecttlb',
        'win32com.client.combrowse',
        'win32com.client.tlbrowse',
        'pywin',
        'pythonwin',
        'win32ui',
        'pytz',
        # Test/debug-only Flask and stdlib helpers pulled through type-only or
        # optional Werkzeug/Click paths; production WebUI never uses them.
        'flask.testing',
        'click.testing',
        'pdb',
        'pydoc',
        'pydoc_data',
        'doctest',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# onedir（2026-10-01 插件化重构）：启动不再每次解压到临时目录，插件和后续
# 增量更新包可以直接放在 exe 旁边。布局：
#   VSE-WebUI/VSE-WebUI.exe
#   VSE-WebUI/_internal/      PyInstaller 运行时与 web/ 静态资源
#   VSE-WebUI/plugins/        功能插件（源码形式，不进 _internal）
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VSE-WebUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VSE-WebUI',
)


def _copy_plugins(dist_dir):
    """Copy repo plugins/ next to the exe; skip caches so the bundle is reproducible."""
    source = Path(SPECPATH) / "plugins"
    target = Path(dist_dir) / "VSE-WebUI" / "plugins"
    if target.exists():
        shutil.rmtree(target)
    if source.is_dir():
        shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
    else:
        target.mkdir(parents=True)


# DISTPATH/SPECPATH 由 PyInstaller 注入；单元测试以假的全局变量执行 spec 时跳过复制。
if "DISTPATH" in globals() and "SPECPATH" in globals():
    _copy_plugins(DISTPATH)
