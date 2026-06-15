# -*- coding: utf-8 -*-
"""
services/__init__.py — 服务层包初始化

导出各服务模块的主类，便于 main.py 统一导入。
office_toolbox 使用延迟导入，避免非 Windows 环境因 win32com 报错。
"""

import sys

from services.intranet_scraper import IntranetScraper
from services.feishu_imap import FeishuImapParser

# win32com 仅 Windows 可用，非 Windows 环境延迟导入
if sys.platform == "win32":
    from services.office_toolbox import OfficeToolbox
else:
    OfficeToolbox = None  # type: ignore[assignment,misc]

__all__ = ["IntranetScraper", "FeishuImapParser", "OfficeToolbox"]
