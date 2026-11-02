# -*- coding: utf-8 -*-
"""作业处理器注册表（DSH-V2-23：唯一调度器 + 作业处理器分层）。

背景与边界：
- 调度器只有一个（``services.project_status_scheduler``，DSH-V2-20）。它认识
  「槽」但不认识具体作业；项目状态同步（``SYNC_JOB_ID``）继续走既有交付物
  路径，其余 fixed 作业（如日报 ``DAILY_REPORT_JOB_ID``）由插件在加载时注册到
  本模块，调度器只按 ``jobId`` 查表调用。
- 依赖方向固定为「插件 → services」单向：本模块不 import 任何插件、不 import
  ``web.*``、不读写 SQLite、不启动线程/定时器、不读全局时钟。
- ``make_binding(project_id, times, paused)`` 由作业方提供：把绑定表里的
  ``times`` 还原成 ``services.schedule_policy.ScheduleBinding``（日报因此带
  ``workdays_only=True``，周末不产槽）。
- ``handler(slot_row)`` 在调度线程执行，只拿已领取的槽行（camelCase 字段），
  返回 :class:`JobOutcome`；**不得依赖 Flask request/app 上下文**。
- 注册表是进程内单例：同一进程里后注册者覆盖先注册者（宿主重建 app / 测试
  重载插件时，处理器始终指向最新的库）。测试结束必须 ``unregister_job``，
  避免进程内注册表串味。

冻结语义（主控批准）：
1. ``SYNC_JOB_ID`` 不得注册（``ValueError``）：同步作业有专用交付物路径，
   注册表只承载「按槽执行一个作业」的处理器。
2. ``JobOutcome(ok, error_code, retry)`` 是处理器唯一返回值：
   - ``ok=True`` -> 槽 succeeded；
   - ``ok=False`` + ``retry=True`` -> 槽 pending，调度器按 300 秒退避重试一次；
   - ``ok=False`` + ``retry=False`` -> 槽 failed，不再自动重试。
   成功结果不得携带 ``error_code``，也不得要求重试（构造时即拒绝，避免伪报成功）。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from services import schedule_policy as SP

#: ``error_code`` 上限与 ``services.schedule_slots`` 的落库口径一致。
ERROR_CODE_LIMIT = 100


@dataclass(frozen=True)
class JobOutcome:
    """一次作业执行的结果（不可变值对象）。"""

    ok: bool
    error_code: str | None = None
    retry: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.ok, bool):
            raise TypeError("JobOutcome.ok 必须是布尔值")
        if not isinstance(self.retry, bool):
            raise TypeError("JobOutcome.retry 必须是布尔值")
        code = self.error_code
        if code is not None:
            if not isinstance(code, str):
                raise TypeError("JobOutcome.error_code 必须是字符串或 None")
            code = code.strip()
            if not code:
                raise ValueError("JobOutcome.error_code 不能是空文本；没有错误请传 None")
            if len(code) > ERROR_CODE_LIMIT:
                raise ValueError(f"JobOutcome.error_code 过长（最多 {ERROR_CODE_LIMIT} 字符）")
            object.__setattr__(self, "error_code", code)
        if self.ok and code is not None:
            raise ValueError("成功的 JobOutcome 不得携带 error_code")
        if self.ok and self.retry:
            raise ValueError("成功的 JobOutcome 不得要求重试")


@dataclass(frozen=True)
class ScheduledJob:
    """一个已注册作业：绑定工厂 + 槽处理器。"""

    job_id: str
    make_binding: Callable[[str, Sequence[Any], bool], SP.ScheduleBinding]
    handler: Callable[[dict[str, Any]], JobOutcome]

    def __post_init__(self) -> None:
        job_id = str(self.job_id or "").strip()
        if not job_id:
            raise ValueError("job_id 不能为空")
        if job_id == SP.SYNC_JOB_ID:
            raise ValueError(
                f"{SP.SYNC_JOB_ID} 由调度器的交付物路径专用，不得注册到作业处理器注册表"
            )
        if not callable(self.make_binding):
            raise TypeError("make_binding 必须可调用")
        if not callable(self.handler):
            raise TypeError("handler 必须可调用")
        object.__setattr__(self, "job_id", job_id)


_REGISTRY: dict[str, ScheduledJob] = {}
_LOCK = threading.RLock()


def register_job(
    job_id: str,
    *,
    make_binding: Callable[[str, Sequence[Any], bool], SP.ScheduleBinding],
    handler: Callable[[dict[str, Any]], JobOutcome],
) -> ScheduledJob:
    """注册（或替换）一个作业处理器；返回登记后的不可变记录。"""
    job = ScheduledJob(str(job_id or ""), make_binding, handler)
    with _LOCK:
        _REGISTRY[job.job_id] = job
    return job


def unregister_job(job_id: str) -> bool:
    """注销一个作业处理器；返回是否真的删除了登记项（幂等）。"""
    key = str(job_id or "").strip()
    if not key:
        return False
    with _LOCK:
        return _REGISTRY.pop(key, None) is not None


def get_job(job_id: str) -> ScheduledJob | None:
    """按 ``job_id`` 取作业处理器；未注册返回 ``None``。"""
    key = str(job_id or "").strip()
    if not key:
        return None
    with _LOCK:
        return _REGISTRY.get(key)


def registered_job_ids() -> tuple[str, ...]:
    """当前已注册的作业 id（按文本升序，便于诊断与测试断言）。"""
    with _LOCK:
        return tuple(sorted(_REGISTRY))


__all__ = [
    "ERROR_CODE_LIMIT",
    "JobOutcome",
    "ScheduledJob",
    "get_job",
    "register_job",
    "registered_job_ids",
    "unregister_job",
]
