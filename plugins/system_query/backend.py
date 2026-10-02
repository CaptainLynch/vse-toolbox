# -*- coding: utf-8 -*-
"""System query plugin backend.

页面直接调用宿主既有的 /api/aras/*、/api/tdc/* 与 /api/tasks/* 接口（凭据会话、
主机 allowlist、后台任务引擎都在那里），本插件暂不注册自己的路由。
路由迁入 Blueprint 属于 S3 后续步骤，届时在这里注册。
"""

from __future__ import annotations


def register(host):  # noqa: ARG001 - 宿主契约要求存在 register(host)
    return None
