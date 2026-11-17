# -*- coding: utf-8 -*-
"""Double-click ``.vsepkg`` to install: a per-user (HKCU) file association, no admin needed.

M0 confirmed HKCU\\Software\\Classes is writable on production machines.
"""

from __future__ import annotations

import os
from pathlib import Path

PROG_ID = "VSEToolbox.Package"
CLASSES = r"Software\Classes"


def command_for(exe: Path) -> str:
    return f'"{exe}" open "%1"'


def register(exe: Path, *, classes_key: str = CLASSES) -> bool:
    """Point ``.vsepkg`` at ``exe``; returns ``True`` when something changed."""
    if os.name != "nt":
        return False
    import winreg

    wanted = command_for(exe)
    command_key = rf"{classes_key}\{PROG_ID}\shell\open\command"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, command_key) as key:
            if winreg.QueryValue(key, None) == wanted:
                return False
    except OSError:
        pass
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{classes_key}\.vsepkg") as key:
        winreg.SetValue(key, None, winreg.REG_SZ, PROG_ID)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{classes_key}\{PROG_ID}") as key:
        winreg.SetValue(key, None, winreg.REG_SZ, "VSE Toolbox 更新包")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{classes_key}\{PROG_ID}\DefaultIcon") as key:
        winreg.SetValue(key, None, winreg.REG_SZ, f'"{exe}",0')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, command_key) as key:
        winreg.SetValue(key, None, winreg.REG_SZ, wanted)
    if classes_key == CLASSES:
        _notify_shell()
    return True


def _notify_shell() -> None:
    try:
        import ctypes

        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED
    except (OSError, AttributeError):
        pass


def ask(text: str, *, yes_no: bool = True) -> bool:
    """A native message box (the windowed launcher has no console)."""
    if os.name != "nt":
        print(text)
        return False
    import ctypes

    flags = 0x40 | (0x4 if yes_no else 0x0)  # MB_ICONINFORMATION | MB_YESNO
    return ctypes.windll.user32.MessageBoxW(None, text, "VSE Toolbox", flags) == 6  # IDYES
