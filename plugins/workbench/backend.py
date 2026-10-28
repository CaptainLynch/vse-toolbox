# -*- coding: utf-8 -*-
"""Workbench plugin backend.

工作台页面只编排宿主和其他插件已有的接口（/api/project-status、/api/settings、
/api/tasks、/api/p/sign-daily/state、/api/p/settings/app-updates …），
不复制业务逻辑，因此暂不注册自有路由。
"""

from __future__ import annotations


def register(host):
    return None
