# -*- coding: utf-8 -*-
"""Deliverables catalog plugin backend.

页面直接调用宿主既有的 /api/deliverables/catalog、/api/tdc/* 与 /api/tasks/*
接口（凭据会话、主机 allowlist、后台任务引擎都在那里），本插件不注册自己的路由。
"""

from __future__ import annotations


def register(host):  # noqa: ARG001 - 宿主契约要求存在 register(host)
    return None
