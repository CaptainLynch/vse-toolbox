# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['requests', 'imapclient', 'pytz', 'flask', 'tkinter', 'tkinter.filedialog']
# WinHTTP via COM (WinHttp.WinHttpRequest.5.1) is the WebUI's HTTP transport for
# Aras/TDC auth on win32; pythoncom + pywintypes + win32com.client are imported
# lazily inside services/windows_http.py and services/aras_auth.py, so PyInstaller
# static analysis cannot see them. xlwings (Excel automation) stays excluded.
hiddenimports += ['pythoncom', 'pywintypes', 'win32crypt', 'win32timezone', 'win32com.client', 'win32com.client.gencache']
hiddenimports += collect_submodules('rich')
hiddenimports += collect_submodules('selenium')
hiddenimports += collect_submodules('flask')


a = Analysis(
    ['web\\app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('web/templates', 'web/templates'),
        ('web/static', 'web/static'),
        ('core/report_headers.json', 'core'),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['xlwings'],
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
