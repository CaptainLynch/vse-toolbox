# -*- coding: utf-8 -*-
"""Excel 文件处理插件后端。

本插件只提供前端模块页（static/workspace.js），数据仍走既有的
/api/excel-tasks、/api/excel-artifacts、/api/excel-worker、/api/excel-roots
以及统一任务中心的 /api/tasks/<id>/cancel，不在 /api/p/excel-tasks/ 下新增路由。
"""

from __future__ import annotations


def register(host):  # noqa: ARG001 - 宿主契约要求存在 register(host)
    return None
