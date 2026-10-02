# -*- coding: utf-8 -*-
"""Service package exports.

The package itself stays import-light so focused tools can import one service
without also loading unrelated integrations such as Excel or IMAP.
"""

from __future__ import annotations

import sys
from typing import Any

__all__ = ["IntranetScraper", "FeishuImapParser", "OfficeToolbox"]


def __getattr__(name: str) -> Any:
    if name == "IntranetScraper":
        from services.intranet_scraper import IntranetScraper

        return IntranetScraper
    if name == "FeishuImapParser":
        from services.feishu_imap import FeishuImapParser

        return FeishuImapParser
    if name == "OfficeToolbox":
        if sys.platform != "win32":
            return None
        from services.office_toolbox import OfficeToolbox

        return OfficeToolbox
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
