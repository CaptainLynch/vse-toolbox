# -*- mode: python ; coding: utf-8 -*-

import atexit
import json
import os
import shutil
import tempfile
from pathlib import Path


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
# static analysis cannot see them. xlwings (Excel automation) stays excluded.
hiddenimports += [
    'pythoncom',
    'pywintypes',
    'win32crypt',
    'win32timezone',
    'win32com.client',
    'win32com.client.gencache',
]
# Selenium is used only by the optional CLI intranet scraper.  The WebUI
# entrypoint does not import or expose that scraper, so collecting every
# Selenium submodule needlessly adds roughly 28 MB to the standalone bundle.


a = Analysis(
    ['webui.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('web/templates', 'web/templates'),
        ('web/static', 'web/static'),
        ('core/report_headers.json', 'core'),
        *version_datas,
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # These integrations are CLI-only and are exposed through services' lazy
    # exports.  The WebUI has no execution path for them; excluding the lazy
    # modules also keeps their optional Selenium/IMAP/Rich dependency trees
    # out of the standalone WebUI package.
    excludes=[
        'xlwings',
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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='VSE-WebUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
