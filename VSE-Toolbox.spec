# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['pythoncom', 'pywintypes', 'win32timezone', 'win32com.client', 'win32com.client.gencache', 'requests', 'imapclient', 'pytz', 'flask']
hiddenimports += collect_submodules('rich')
hiddenimports += collect_submodules('win32com')
hiddenimports += collect_submodules('xlwings')
hiddenimports += collect_submodules('selenium')
hiddenimports += collect_submodules('flask')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('web/templates', 'web/templates'), ('web/static', 'web/static')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='VSE-Toolbox',
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
