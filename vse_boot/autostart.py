# -*- coding: utf-8 -*-
"""当前用户（HKCU）开机自启管理。

管理注册表项：
HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run

无管理员权限要求（HKCU 属于当前用户配置，普通权限即可读写）。
注意：本文件属于启动器运行时层（vse_boot），下次发布需要完整更新安装包。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None  # 非 Windows 环境或测试中 mock

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "VSE-Toolbox"


def command(exe: Path | str | None = None) -> str:
    """返回开机自启命令行（带当前可执行文件路径与最小参数）。

    对于包含空格的路径，统一使用双引号包裹，保证 Windows Run 项在登录启动时能正确解析。
    若传入已包含外层双引号的路径，会自动规整避免多重引号。
    """
    if exe is None:
        exe_path = str(Path(sys.executable).resolve())
    else:
        raw = str(exe).strip()
        if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
            raw = raw[1:-1].strip()
        exe_path = raw
    return f'"{exe_path}"'


def _is_corrupted(val: object, val_type: int) -> bool:
    """判断注册表值是否损坏。

    损坏情况包括：
    - 类型不是字符串（REG_SZ / REG_EXPAND_SZ，例如被误写为 REG_DWORD 或 REG_BINARY）；
    - 值不是有效 Python 字符串；
    - 值为空或仅包含空白字符；
    - 路径引号未闭合（双引号数量为奇数）；
    - 包含空字符（\\x00）。
    """
    reg_sz = getattr(winreg, "REG_SZ", 1) if winreg else 1
    reg_expand_sz = getattr(winreg, "REG_EXPAND_SZ", 2) if winreg else 2
    if val_type not in (reg_sz, reg_expand_sz):
        return True
    if not isinstance(val, str):
        return True
    text = val.strip()
    if not text:
        return True
    if text.count('"') % 2 != 0:
        return True
    if "\x00" in text:
        return True
    return False


def _clean_path(cmd_or_path: str) -> str:
    """提取命令行中的可执行文件路径，并规整斜杠与大小写用于 Windows 路径比对。"""
    text = cmd_or_path.strip()
    if text.startswith('"'):
        end = text.find('"', 1)
        text = text[1:end] if end != -1 else text[1:]
    else:
        text = text.split()[0] if text.split() else text
    return text.strip().replace("/", "\\").lower()


def _delete_entry(name: str) -> None:
    """删除 Run 键下的自启动项；若不存在则安全忽略（幂等）。"""
    if winreg is None:
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, name)
    except (FileNotFoundError, OSError):
        pass


def enabled(name: str = APP_NAME, *, exe: Path | str | None = None, repair: bool = True) -> bool:
    """检查当前用户是否已启用开机自启。

    - 注册表键或项不存在时返回 False；
    - 若发现值损坏，按未启用处理（返回 False），并在 repair=True 时清理损坏项以完成修复；
    - 正常匹配当前可执行文件命令行时返回 True。
    """
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            val, val_type = winreg.QueryValueEx(key, name)
    except FileNotFoundError:
        return False
    except OSError:
        return False

    if _is_corrupted(val, val_type):
        if repair:
            _delete_entry(name)
        return False

    expected = command(exe)
    if val.strip() == expected:
        return True
    if _clean_path(val) == _clean_path(expected):
        return True

    return False


def enable(name: str = APP_NAME, *, exe: Path | str | None = None) -> None:
    """开启开机自启。

    幂等：重复调用不报错；若此前存在损坏值或旧路径，将自动覆盖修复为有效命令行。
    """
    if winreg is None:
        return
    cmd = command(exe)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            val, val_type = winreg.QueryValueEx(key, name)
            if not _is_corrupted(val, val_type) and val.strip() == cmd:
                return  # 已正确启用且内容完全一致，幂等返回
    except OSError:
        pass

    reg_sz = getattr(winreg, "REG_SZ", 1) if winreg else 1
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, name, 0, reg_sz, cmd)


def disable(name: str = APP_NAME) -> None:
    """关闭开机自启并清掉已有注册表项。

    幂等：重复调用或项已不存在时直接返回，不抛出异常。
    """
    _delete_entry(name)
