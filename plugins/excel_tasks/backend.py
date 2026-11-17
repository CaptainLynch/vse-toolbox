# -*- coding: utf-8 -*-
"""Excel 文件处理插件后端。

本插件只提供前端模块页（static/workspace.js），业务数据仍走既有的
/api/excel-tasks、/api/excel-artifacts、/api/excel-worker、/api/excel-roots
以及统一任务中心的 /api/tasks/<id>/cancel。

插件自有路由只有一条（DSH-V2-25）：
GET env-check   /api/p/excel-tasks/env-check   本机 Excel 运行环境自检（只读）

检测逻辑由宿主在 create_app 里以 ``app.extensions["excel_env_check"]`` 注入，
插件只经 ``host.context.service(...)`` 取用，不 import services.* / web.*，
也不自行实例化探测器。该路由只读：不结束任何进程、不改动任何文件，
残留的后台表格进程只展示数量。
"""

from __future__ import annotations

#: 服务缺失（宿主未注入）时的用户可见文案。
_UNAVAILABLE_MESSAGE = "环境自检暂时不可用，请重启程序后再试"
#: 检测本身失败时的用户可见文案；不回显堆栈、路径或异常原文。
_FAILED_MESSAGE = "环境自检没有完成，请稍后重试"


def _with_no_store(pair):
    """宿主信封已带 no-store，这里再显式加一次：自检结果随本机环境变化，不能缓存。"""
    response, status = pair
    response.headers["Cache-Control"] = "no-store"
    return response, status


def register(host):
    ctx = host.context
    bp = host.blueprint

    @bp.get("/env-check")
    def env_check():  # type: ignore[no-untyped-def]
        try:
            check = ctx.service("excel_env_check")
        except LookupError:
            return _with_no_store(
                ctx.json_error(501, "EnvCheckUnavailable", ctx.redact(_UNAVAILABLE_MESSAGE))
            )

        try:
            result = check()
        except Exception:  # noqa: BLE001 - 任何探测器异常都只回通俗中文，不回显内部细节
            return _with_no_store(
                ctx.json_error(500, "EnvCheckFailed", ctx.redact(_FAILED_MESSAGE))
            )

        return _with_no_store(ctx.json_ok(result))
