# -*- coding: utf-8 -*-
"""调度控制插件后端（C4 执行槽持久化与租约边界，DSH-V2-19）。

本阶段只做存储与租约边界，**不接入任何调度器**（托盘进程接线是 DSH-V2-20）：

- 加载时执行增量迁移（``host.migrate``），只增不删：``{prefix}slots`` /
  ``{prefix}bindings``，表名一律用 ``host.table_prefix``。
- 只暴露一条只读路由：``GET /api/p/sync-control/slots?projectId=&date=``，
  返回 ``{ok, data: {projectId, businessDate, slots}}`` 信封并带 ``Cache-Control: no-store``。
  没有写路由（槽的入队/领取/收尾只由 DSH-V2-20 的调度进程调用 ``store.SlotStore``）。
- ``date`` 省略时取北京时间当天；日期或项目号非法返回 400 校验错误，不静默兜底。
"""

from __future__ import annotations

from flask import request

from core.time_rules import now_utc, pure_date, to_beijing

from .store import SlotStore

#: 项目号长度上限（与既有路由的入参口径一致）。
_PROJECT_ID_LIMIT = 200


def _no_store(pair):
    """宿主信封已带 no-store，这里再显式加一次：槽状态随执行推进，不能缓存。"""
    response, status = pair
    response.headers["Cache-Control"] = "no-store"
    return response, status


def register(host):
    ctx = host.context
    store = SlotStore(ctx.db, host.table_prefix, clock=now_utc)
    host.migrate(store.migrations())

    @host.blueprint.get("/slots")
    def slots():  # type: ignore[no-untyped-def]
        project_id = (request.args.get("projectId") or "").strip()
        if not project_id:
            return _no_store(ctx.json_error(400, "ValidationError", "缺少 projectId"))
        if len(project_id) > _PROJECT_ID_LIMIT:
            return _no_store(ctx.json_error(400, "ValidationError", "projectId 过长"))

        raw_date = (request.args.get("date") or "").strip()
        if raw_date:
            try:
                business_date = pure_date(raw_date)
            except (TypeError, ValueError):
                return _no_store(ctx.json_error(400, "ValidationError", "date 必须是 YYYY-MM-DD"))
        else:
            business_date = to_beijing(now_utc()).date()

        return _no_store(
            ctx.json_ok(
                {
                    "projectId": project_id,
                    "businessDate": business_date.isoformat(),
                    # 租约 token 是收尾 fencing 凭据，只读路由不外露。
                    "slots": [
                        {k: v for k, v in slot.items() if k != "leaseToken"}
                        for slot in store.list_slots(project_id, business_date)
                    ],
                }
            )
        )
