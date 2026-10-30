# -*- coding: utf-8 -*-
"""离线浏览器通道探测与冒烟测试。

探测本机 Microsoft Edge / Google Chrome 常见安装路径与环境变量。
找到可用浏览器后，通过原生无头模式（headless 模式 + dump-dom）运行最小冒烟测试。
若未安装或未探测到可用通道，则如实跳过（pytest.skip）并记录原因。
不依赖 Playwright，不进行网络下载。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest


@dataclass(frozen=True)
class BrowserChannel:
    """浏览器通道信息。"""

    name: Optional[str] = None
    path: Optional[Path] = None
    available: bool = False
    reason: str = ""


def find_browser_channel() -> BrowserChannel:
    """探测本机 Edge 或 Chrome 浏览器通道可执行文件。

    优先级：
    1. 环境变量 VSE_BROWSER_PATH 显式覆盖；
    2. 系统 PATH 环境变量中的可执行文件名；
    3. Windows 常见安装目录与系统注册表；
    4. Linux / macOS 常见安装路径。
    """
    # 1. 允许通过环境变量显式指定浏览器可执行文件
    explicit_path = os.environ.get("VSE_BROWSER_PATH")
    if explicit_path:
        p = Path(explicit_path.strip(' \t\r\n"'))
        if p.is_file():
            return BrowserChannel(
                name="Custom Browser",
                path=p,
                available=True,
                reason="通过环境变量 VSE_BROWSER_PATH 指定",
            )

    # 2. 检查系统 PATH 环境变量
    path_commands = [
        ("Microsoft Edge", "msedge"),
        ("Google Chrome", "chrome"),
        ("Google Chrome", "google-chrome"),
        ("Chromium", "chromium"),
        ("Google Chrome", "google-chrome-stable"),
        ("Microsoft Edge", "microsoft-edge"),
    ]
    for name, cmd in path_commands:
        found = shutil.which(cmd)
        if found:
            p = Path(found)
            if p.is_file():
                return BrowserChannel(
                    name=name,
                    path=p,
                    available=True,
                    reason=f"在环境变量 PATH 中找到 {name}",
                )

    # 3. Windows 平台特化探测
    if sys.platform == "win32":
        roots: list[Path] = []
        for var in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "ProgramW6432"):
            val = os.environ.get(var)
            if val:
                p = Path(val)
                if p not in roots:
                    roots.append(p)

        sys_drive = os.environ.get("SystemDrive", "C:")
        for fallback in (f"{sys_drive}\\Program Files", f"{sys_drive}\\Program Files (x86)"):
            p = Path(fallback)
            if p not in roots:
                roots.append(p)

        # 常见相对目录（Edge 优先，符合 Windows 默认标配）
        relative_candidates = [
            ("Microsoft Edge", Path("Microsoft") / "Edge" / "Application" / "msedge.exe"),
            ("Google Chrome", Path("Google") / "Chrome" / "Application" / "chrome.exe"),
        ]
        for root in roots:
            for name, rel in relative_candidates:
                candidate = root / rel
                try:
                    if candidate.is_file():
                        return BrowserChannel(
                            name=name,
                            path=candidate,
                            available=True,
                            reason=f"在标准目录找到 {name}",
                        )
                except OSError:
                    continue

        # 注册表 App Paths 探测
        try:
            import winreg

            reg_keys = [
                ("Microsoft Edge", r"Software\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"),
                ("Google Chrome", r"Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
            ]
            for name, subkey in reg_keys:
                for root_hkey in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    try:
                        with winreg.OpenKey(root_hkey, subkey) as key:
                            val, _ = winreg.QueryValueEx(key, "")
                            if val:
                                p = Path(str(val).strip(' \t\r\n"'))
                                if p.is_file():
                                    return BrowserChannel(
                                        name=name,
                                        path=p,
                                        available=True,
                                        reason=f"在系统注册表中找到 {name}",
                                    )
                    except OSError:
                        pass
        except ImportError:
            pass

    # 4. Linux / macOS 常见路径
    else:
        unix_candidates = [
            ("Google Chrome", Path("/usr/bin/google-chrome")),
            ("Google Chrome", Path("/usr/bin/google-chrome-stable")),
            ("Chromium", Path("/usr/bin/chromium")),
            ("Chromium", Path("/usr/bin/chromium-browser")),
            ("Microsoft Edge", Path("/usr/bin/microsoft-edge")),
            ("Microsoft Edge", Path("/usr/bin/microsoft-edge-stable")),
            ("Google Chrome", Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")),
            ("Microsoft Edge", Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")),
        ]
        for name, p in unix_candidates:
            try:
                if p.is_file():
                    return BrowserChannel(
                        name=name,
                        path=p,
                        available=True,
                        reason=f"在系统目录找到 {name}",
                    )
            except OSError:
                continue

    return BrowserChannel(
        name=None,
        path=None,
        available=False,
        reason="未在常见安装路径或环境变量中探测到 Edge 或 Chrome 浏览器通道",
    )


def test_browser_channel_headless_smoke() -> None:
    """验证本机浏览器通道在无头模式下可启动并输出关于空白页的最小 DOM。"""
    channel = find_browser_channel()
    if not channel.available or channel.path is None:
        pytest.skip(channel.reason)

    # 使用专属临时用户数据目录，避免进程冲突或污染用户真实环境配置
    with tempfile.TemporaryDirectory(prefix="vse_browser_smoke_") as tmp_dir:
        cmd = [
            str(channel.path),
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            f"--user-data-dir={tmp_dir}",
            "--dump-dom",
            "about:blank",
        ]
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
            # 兼容处理：若较旧版本浏览器不支持 --headless=new，回退使用 --headless
            if res.returncode != 0:
                cmd_fallback = [
                    str(channel.path),
                    "--headless",
                    "--disable-gpu",
                    "--no-sandbox",
                    f"--user-data-dir={tmp_dir}",
                    "--dump-dom",
                    "about:blank",
                ]
                res = subprocess.run(
                    cmd_fallback,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=20,
                    check=False,
                )
        except subprocess.TimeoutExpired:
            pytest.fail(f"浏览器进程启动超时（20 秒）: {channel.path}")

        assert res.returncode == 0, (
            f"浏览器无头模式启动失败 (退出码: {res.returncode}):\n{res.stderr[:400]}"
        )
        output = (res.stdout or "").lower()
        assert "html" in output or "body" in output, (
            f"浏览器无头模式输出未包含预期 DOM 节点: {res.stdout[:300]}"
        )
