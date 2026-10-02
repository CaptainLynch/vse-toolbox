# -*- coding: utf-8 -*-
"""Settings plugin backend.

页面直接调用宿主已有的 /api/settings、/api/settings/folders/native、
/api/settings/domain-login、/api/settings/sessions 与 /api/version，
这些接口（含本机写保护、凭据与会话处理）保留在 web/app.py，不在插件内复制。
插件暂不注册自有路由。
"""

from __future__ import annotations


def register(host):
    return None
