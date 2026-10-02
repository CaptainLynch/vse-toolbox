# -*- coding: utf-8 -*-
"""VSE Toolbox 应用程序版本与运行环境元数据探测。

支持源码开发工作区、PyInstaller 独立冻结运行包及发布元数据的安全退化，
不强依赖 Git，不泄露工作区绝对路径、系统用户名或敏感环境变量。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from core.runtime_paths import app_root


def _clean_version_field(val: Any, limit: int = 100) -> str | None:
    if not isinstance(val, str):
        return None
    cleaned = val.strip()
    if not cleaned or len(cleaned) > limit:
        return None
    for ch in cleaned:
        if ord(ch) < 32 or (127 <= ord(ch) <= 159):
            return None
    return cleaned


def get_app_version_info() -> dict[str, Any]:
    """获取当前运行环境的真实版本与构建元数据。

    优先级：
    1. 可执行程序旁、应用根目录或 sys._MEIPASS 下的 version.json / VERSION
    2. 显式环境变量 VSE_TOOLBOX_VERSION（构建或 CI 注入）
    3. 安全退化：冻结包显示「独立运行包」，源码开发环境显示「开发工作区」
    """
    version_str: str | None = None
    build_id: str | None = None
    channel: str = "source"
    is_frozen = bool(getattr(sys, "frozen", False))

    if is_frozen:
        channel = "standalone-exe"

    # 1. 检查应用根目录、可执行文件同级目录或 PyInstaller 解压目录下的 version.json 或 VERSION 文件
    root = app_root()
    search_dirs: list[Path] = []
    if is_frozen:
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            try:
                meipass_dir = Path(meipass).resolve()
                if meipass_dir not in search_dirs:
                    search_dirs.append(meipass_dir)
            except Exception:
                pass
        try:
            exe_dir = Path(sys.executable).resolve().parent
            if exe_dir not in search_dirs:
                search_dirs.append(exe_dir)
        except Exception:
            pass
    if root not in search_dirs:
        search_dirs.append(root)

    for d in search_dirs:
        vjson = d / "version.json"
        if vjson.is_file():
            try:
                data = json.loads(vjson.read_text(encoding="utf-8-sig"))
                if isinstance(data, dict):
                    ver = _clean_version_field(data.get("version"))
                    if ver:
                        version_str = ver
                        build_id = _clean_version_field(data.get("buildId") or data.get("build_id"))
                        ch = _clean_version_field(data.get("channel"))
                        if ch:
                            channel = ch
                        break
            except Exception:
                pass

        vtxt = d / "VERSION"
        if vtxt.is_file():
            try:
                text = vtxt.read_text(encoding="utf-8-sig").strip()
                if text:
                    first_line = _clean_version_field(text.splitlines()[0])
                    if first_line:
                        version_str = first_line
                        break
            except Exception:
                pass

    # 2. 检查环境变量注入（例如自动化构建流程或开发调试注入）
    if not version_str:
        env_ver = _clean_version_field(os.environ.get("VSE_TOOLBOX_VERSION"))
        if env_ver:
            version_str = env_ver
            env_ch = _clean_version_field(os.environ.get("VSE_TOOLBOX_CHANNEL"))
            if env_ch:
                channel = env_ch

    if not build_id:
        env_build = _clean_version_field(os.environ.get("VSE_TOOLBOX_BUILD_ID"))
        if env_build:
            build_id = env_build

    # 3. 确定对最终用户的显示名称与维护详情
    if version_str:
        display_version = f"v{version_str.lstrip('v')}"
        detail = f"{display_version} ({channel})"
    elif is_frozen:
        display_version = "独立运行包"
        detail = "独立运行包 (无外部版本标识)"
    else:
        display_version = "开发工作区"
        detail = "开发工作区 (源码运行)"

    return {
        "displayVersion": display_version,
        "rawVersion": version_str,
        "buildId": build_id,
        "channel": channel,
        "isFrozen": is_frozen,
        "detail": detail,
    }
