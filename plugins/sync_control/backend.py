# -*- coding: utf-8 -*-
"""调度控制插件后端（C4 执行槽持久化与调度时刻界面，DSH-V2-19/20/21）。

存储与租约边界由 DSH-V2-19 建立、DSH-V2-20 接线到唯一后台调度器；本阶段
（DSH-V2-21）只增加「调度时刻与暂停设置」所需的读写路由，**不新建表、不改
services、不启动任何定时器**：

- 加载时执行增量迁移（``host.migrate``），只增不删：``{prefix}slots`` /
  ``{prefix}bindings``，表名一律用 ``host.table_prefix``；复用已构造的
  ``SlotStore``，不新建第二份存储。
- ``GET /api/p/sync-control/slots?projectId=&date=``：只读槽查询（DSH-V2-19）。
- ``GET /api/p/sync-control/binding?projectId=``：读当前项目的同步绑定与当天槽
  摘要。无绑定即 ``mode="off"``、``times=[]``、``nextRunAt=null``（「0 个绑定
  显示未开启」）。``nextRunAt`` 由 ``services.schedule_policy.next_slot_at`` 计算，
  暂停或非 fixed 时为 null；``today`` 只暴露 ``scheduledTime / status / attempt /
  lastErrorCode``，**绝不外露 leaseToken / leaseOwner**（收尾 fencing 凭据）。
- ``PUT /api/p/sync-control/binding/<projectId>``：写时刻与暂停标志。写路由先过
  ``ctx.local_guard()``（与既有插件写路由同一方式）。``times`` 经
  ``schedule_policy`` 规范化（``'9:00'`` ≡ ``'09:00'``、去重、升序），非法时刻返回
  400 ``ValidationError`` 且消息以 ``times`` 字段开头；``times`` 非空写 fixed 绑定，
  为空写 interval 绑定（回到间隔同步，表示「关闭固定时刻」）。
- 全部路由带 ``Cache-Control: no-store``：绑定与槽状态随执行推进，不能缓存。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from flask import request

from core.time_rules import now_utc, pure_date, to_beijing
from services import schedule_policy

from .store import SlotStore

#: 项目号长度上限（与既有路由的入参口径一致）。
_PROJECT_ID_LIMIT = 200

#: 同步任务 ID：调度器派发时固定使用 ``schedule_policy.SYNC_JOB_ID``（DSH-V2-20）。
_JOB_ID = schedule_policy.SYNC_JOB_ID

#: 无绑定时的模式：前端据此显示「未开启固定时刻，当前按间隔同步」。
_MODE_OFF = "off"


class BindingValidationError(ValueError):
    """绑定请求不合法；消息以字段名开头（``times`` / ``paused``），由路由转 400。"""


def _no_store(pair):
    """宿主信封已带 no-store，这里再显式加一次：槽状态随执行推进，不能缓存。"""
    response, status = pair
    response.headers["Cache-Control"] = "no-store"
    return response, status


def _project_id_error(ctx, project_id: str):
    """项目号校验（非空、≤200）：与既有 ``/slots`` 路由同一口径。"""
    if not project_id:
        return _no_store(ctx.json_error(400, "ValidationError", "缺少 projectId"))
    if len(project_id) > _PROJECT_ID_LIMIT:
        return _no_store(ctx.json_error(400, "ValidationError", "projectId 过长"))
    return None


def _normalized_times(project_id: str, raw: Any) -> tuple:
    """校验并规范化 ``times``：字段级错误消息，规范化复用 ``schedule_policy``。

    空数组合法（表示「关闭固定时刻」，写 interval 绑定）；每一项必须是
    ``'HH:MM'`` / ``'HH:MM:SS'`` 文本，规范化后去重升序。
    """
    if not isinstance(raw, list):
        raise BindingValidationError("times 必须是时刻字符串数组（'HH:MM'）")
    for index, item in enumerate(raw):
        if not isinstance(item, str):
            raise BindingValidationError(f"times[{index}] 必须是 'HH:MM' 文本")
        try:
            # 逐项构造绑定：复用 schedule_policy 的解析口径，并给出下标级错误位置。
            schedule_policy.sync_binding(project_id, times=(item,))
        except (TypeError, ValueError) as exc:
            raise BindingValidationError(f"times[{index}] {exc}") from None
    if not raw:
        return ()
    return schedule_policy.sync_binding(project_id, times=raw).times


def _paused_flag(raw: Any) -> bool:
    """``paused`` 只接受严格布尔；缺省为 False（不静默接受 'true' 之类的字符串）。"""
    if raw is None:
        return False
    if not isinstance(raw, bool):
        raise BindingValidationError("paused 必须是布尔值")
    return raw


def _binding_payload(store: SlotStore, project_id: str, now: datetime) -> dict[str, Any]:
    """绑定 + 下次执行 + 当天槽摘要（GET / PUT 共用同一份形状）。"""
    binding = store.get_binding(project_id, _JOB_ID)
    mode = str(binding["mode"]) if binding else _MODE_OFF
    times: Iterable[str] = ()
    paused = False
    if binding is not None:
        paused = bool(binding["paused"])
        if mode == schedule_policy.JOB_KIND_FIXED:
            times = list(binding["times"])

    next_run_at: str | None = None
    if mode == schedule_policy.JOB_KIND_FIXED and not paused:
        policy_binding = schedule_policy.sync_binding(
            project_id, job_id=_JOB_ID, times=times, paused=paused
        )
        next_run = schedule_policy.next_slot_at(policy_binding, now=now)
        next_run_at = next_run.isoformat() if next_run is not None else None

    return {
        "projectId": project_id,
        "jobId": _JOB_ID,
        "mode": mode,
        "times": list(times),
        "paused": paused,
        "nextRunAt": next_run_at,
        # 租约 token / owner 是收尾 fencing 凭据，界面只读路由不外露。
        "today": [
            {
                "scheduledTime": row["scheduledTime"],
                "status": row["status"],
                "attempt": row["attempt"],
                "lastErrorCode": row["lastErrorCode"],
            }
            for row in store.list_slots(project_id, to_beijing(now).date())
        ],
    }


def register(host):
    ctx = host.context
    store = SlotStore(ctx.db, host.table_prefix, clock=now_utc)
    host.migrate(store.migrations())

    @host.blueprint.get("/slots")
    def slots():  # type: ignore[no-untyped-def]
        project_id = (request.args.get("projectId") or "").strip()
        invalid = _project_id_error(ctx, project_id)
        if invalid is not None:
            return invalid

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

    @host.blueprint.get("/binding")
    def binding_read():  # type: ignore[no-untyped-def]
        project_id = (request.args.get("projectId") or "").strip()
        invalid = _project_id_error(ctx, project_id)
        if invalid is not None:
            return invalid
        return _no_store(ctx.json_ok(_binding_payload(store, project_id, now_utc())))

    @host.blueprint.put("/binding/<project_id>")
    def binding_write(project_id: str):  # type: ignore[no-untyped-def]
        guard = ctx.local_guard()
        if guard is not None:
            return guard

        project_text = (project_id or "").strip()
        invalid = _project_id_error(ctx, project_text)
        if invalid is not None:
            return invalid

        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _no_store(ctx.json_error(400, "ValidationError", "请求体必须是 JSON 对象"))
        try:
            times = _normalized_times(project_text, body.get("times"))
            paused = _paused_flag(body.get("paused"))
        except BindingValidationError as exc:
            return _no_store(ctx.json_error(400, "ValidationError", str(exc)))

        if times:
            store.set_binding(
                project_text, _JOB_ID, schedule_policy.JOB_KIND_FIXED,
                [item.strftime("%H:%M") for item in times], paused,
            )
        else:
            # 0 个时刻 = 关闭固定时刻，回到既有间隔同步（同一绑定只能一种）。
            store.set_binding(
                project_text, _JOB_ID, schedule_policy.JOB_KIND_INTERVAL, [], paused
            )
        return _no_store(ctx.json_ok(_binding_payload(store, project_text, now_utc())))
