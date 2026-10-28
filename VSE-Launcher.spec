# -*- mode: python ; coding: utf-8 -*-
# VSE Toolbox v2 launcher + runtime (L0 + L1), onedir.
#
#   pyinstaller --noconfirm VSE-Launcher.spec
#
# `_internal/` is the runtime layer: the full standard library, the third-party
# packages the app needs, and vse_boot. App code (core/ services/ host/ web/
# plugins/ webui.py) is NOT frozen in: it is loaded from app/<version>/ so it
# can be updated with small signed packages (docs/refactor-v2/M1_PLAN.md).
#
# Env:
#   VSE_TRUSTED_KEYS_FILE  keys file bundled as vse_boot/trusted_keys.json
#                          (default: the repository's vse_boot/trusted_keys.json)
#   VSE_LAUNCHER_CONSOLE=1 keep a console window (debug builds)

import importlib.util
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

REPO = Path(SPECPATH)
sys.path.insert(0, str(REPO))
from vse_boot.packages import TARGET_RUNTIME_TAG  # noqa: E402

_BUILD_TAG = f"cp{sys.version_info.major}{sys.version_info.minor}"
if _BUILD_TAG != TARGET_RUNTIME_TAG:
    raise SystemExit(f"运行时必须用 {TARGET_RUNTIME_TAG} 构建，当前是 {_BUILD_TAG}：否则发出的 app 包与运行时不匹配")
APP_TOP_LEVEL = {"core", "services", "host", "web", "plugins", "vse_plugins", "webui", "excel_worker_cli"}
SKIP_STDLIB = {
    "test", "idlelib", "turtledemo", "turtle", "lib2to3", "ensurepip", "venv", "pydoc_data",
    "distutils", "this", "antigravity", "__phello__",
    # POSIX-only
    "pwd", "grp", "fcntl", "termios", "resource", "curses", "readline", "crypt", "nis", "spwd",
    "syslog", "tty", "pty", "posix", "_posixsubprocess", "_curses", "_curses_panel", "ossaudiodev",
    "_scproxy", "_posixshmem", "_crypt", "_dbm", "_gdbm", "dbm.gnu", "dbm.ndbm",
}


def _stdlib_modules():
    """Every standard-library module: future app versions may import any of them."""
    names = []
    for name in sorted(sys.stdlib_module_names):
        if name in SKIP_STDLIB:
            continue
        names.append(name)
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError):
            continue
        # 只有包才需要展开子模块；对普通模块调用 collect_submodules 只会白白起一个子进程。
        if spec is None or not spec.submodule_search_locations:
            continue
        try:
            names += [m for m in collect_submodules(name) if m.split(".")[1:2] not in (["test"], ["tests"])]
        except Exception:
            pass
    return [n for n in names if n.split(".")[0] not in SKIP_STDLIB]


def _app_modules():
    """App module names, so their third-party imports are traced (the modules themselves are stripped below)."""
    names = ["webui"]
    for package in ("core", "services", "host", "web"):
        for path in (REPO / package).rglob("*.py"):
            if "__pycache__" in path.parts or "tests" in path.parts:
                continue
            rel = path.relative_to(REPO).with_suffix("")
            parts = list(rel.parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            names.append(".".join(parts))
    return names


hiddenimports = _stdlib_modules() + _app_modules()
hiddenimports += [
    "requests", "flask", "jinja2", "werkzeug", "cryptography",
    "pythoncom", "pywintypes", "win32crypt", "win32timezone", "win32api", "win32con", "win32file",
    "win32com.client", "win32com.client.gencache",
]
hiddenimports += collect_submodules("win32com")
hiddenimports += collect_submodules("xlwings")
hiddenimports += collect_submodules("vse_boot")

keys_file = os.environ.get("VSE_TRUSTED_KEYS_FILE") or str(REPO / "vse_boot" / "trusted_keys.json")

a = Analysis(
    [str(REPO / "tools" / "vse_launcher_entry.py")],
    pathex=[str(REPO), str(REPO / "tools")],
    binaries=[],
    datas=[(keys_file, "vse_boot")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "selenium", "setuptools", "_distutils_hack", "pytest", "_pytest",
        "services.intranet_scraper", "services.feishu_imap", "services.office_toolbox",
        "win32com.client.makepy", "win32com.client.selecttlb", "win32com.client.combrowse",
        "win32com.client.tlbrowse", "pywin", "pythonwin", "win32ui",
    ],
    noarchive=False,
    optimize=0,
)

# 去掉 app 自己的模块：它们从 app/<版本>/ 以源码加载，才能按小包更新。
a.pure = [entry for entry in a.pure if entry[0].split(".")[0] not in APP_TOP_LEVEL]
a.datas = [entry for entry in a.datas if not entry[0].replace("\\", "/").startswith(("web/", "core/", "host/", "plugins/"))]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VSE-Toolbox",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=os.environ.get("VSE_LAUNCHER_CONSOLE") == "1",
    disable_windowed_traceback=True,
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
    upx=False,
    upx_exclude=[],
    name="VSE-Toolbox",
)
