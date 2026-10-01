# -*- coding: utf-8 -*-
"""Project overview plugin backend.

页面调用宿主已有的 /api/project-status*、/api/deliverable-forms/*、
/api/scheduled-archive/*、/api/tasks* 等接口（含本机写保护与租约逻辑），
这些接口暂留在 web/app.py；插件暂不注册自有路由。
"""

from __future__ import annotations


def register(host):
    return None
