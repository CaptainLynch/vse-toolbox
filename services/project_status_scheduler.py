# -*- coding: utf-8 -*-
"""
services/project_status_scheduler.py — WebUI 常驻项目状态同步调度线程。

职责边界：
- 仅 WebUI 入口（webui.py）以 daemon 线程启动；CLI（main.py 的
  project-status-sync --once）与 pytest 不启动。
- 每个 tick 通过 db.list_eligible_sync_bindings(None) 读取启用绑定；
  last_success_at 距今不足 interval 的绑定直接跳过（D 的新鲜度复用，
  零网络调用——既有展示层继续消费最近一次成功快照）。
- 其余绑定逐个调用 ProjectStatusSyncRunner.run_once(
  deliverable_id=<id>, trigger_type='scheduled',
  validate_runtime_prerequisites=False)，对齐 main.py CLI 定时先例：
  不做凭据/稳定键/映射前置阻断，由连接器产生可审计的运行时结果。
- 单绑定异常（含 SyncLeaseBusyError 抛出形态）记录脱敏日志后继续，
  不中断循环；stop_event 置位后线程退出。
- 本模块不 import Flask、不直接编写 SQL、不持有凭据或 lease_token。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from core.redaction import redact_sensitive_text

logger = logging.getLogger("vse_toolbox.sync_scheduler")

#: 默认同步间隔（秒）：15 分钟一次补偿性后台同步。
DEFAULT_SYNC_INTERVAL_SECONDS = 900

#: 环境变量覆盖：VSE_PROJECT_STATUS_SYNC_INTERVAL（秒，正整数）。
SYNC_INTERVAL_ENV_VAR = "VSE_PROJECT_STATUS_SYNC_INTERVAL"

#: last_success_at 由 db_manager 以 UTC strftime('%Y-%m-%dT%H:%M:%fZ') 写入。
_SUCCESS_AT_FORMATS = ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ")


class _SyncSchedulerRunner(Protocol):
    """调度器依赖的 runner 最小协议（ProjectStatusSyncRunner 满足）。"""

    def run_once(
        self,
        deliverable_id: str | None = None,
        dry_run: bool = False,
        trigger_type: str = "scheduled",
        validate_runtime_prerequisites: bool = True,
    ) -> Any:
        ...


class _SyncSchedulerDb(Protocol):
    """调度器依赖的 db 最小协议（DatabaseManager 满足）。"""

    def list_eligible_sync_bindings(
        self, deliverable_id: str | None = None
    ) -> list[dict[str, Any]]:
        ...


class _StoppableEvent(Protocol):
    """threading.Event 的鸭子类型子集，便于测试注入假 stop_event。"""

    def is_set(self) -> bool:
        ...

    def wait(self, timeout: float | None = None) -> bool:
        ...


def resolve_sync_interval(env: dict[str, str] | None = None) -> int:
    """解析同步间隔：显式参数 > 环境变量 > 默认值；非法值回落默认。"""
    source = os.environ if env is None else env
    raw = str(source.get(SYNC_INTERVAL_ENV_VAR, "")).strip()
    if not raw:
        return DEFAULT_SYNC_INTERVAL_SECONDS
    try:
        parsed = int(raw)
    except ValueError:
        logger.warning(
            "invalid %s=%r; falling back to %s seconds",
            SYNC_INTERVAL_ENV_VAR,
            raw,
            DEFAULT_SYNC_INTERVAL_SECONDS,
        )
        return DEFAULT_SYNC_INTERVAL_SECONDS
    if parsed <= 0:
        logger.warning(
            "invalid %s=%r; falling back to %s seconds",
            SYNC_INTERVAL_ENV_VAR,
            raw,
            DEFAULT_SYNC_INTERVAL_SECONDS,
        )
        return DEFAULT_SYNC_INTERVAL_SECONDS
    return parsed


def _parse_success_at(value: Any) -> float | None:
    """解析 last_success_at 为 UTC epoch 秒；无法解析返回 None（视为陈旧）。"""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    for fmt in _SUCCESS_AT_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        return parsed.timestamp()
    return None


class ProjectStatusSyncScheduler:
    """可注入 clock/interval/runner/stop_event 的常驻同步调度循环。"""

    def __init__(
        self,
        db: _SyncSchedulerDb,
        runner: _SyncSchedulerRunner,
        *,
        clock: Callable[[], float] = time.time,
        interval: int | None = None,
        stop_event: _StoppableEvent | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._db = db
        self._runner = runner
        self._clock = clock
        self._interval = (
            interval if interval is not None else resolve_sync_interval()
        )
        if self._interval <= 0:
            raise ValueError("sync interval must be a positive number of seconds")
        self._stop_event = stop_event if stop_event is not None else threading.Event()
        self._sleep = sleep

    @property
    def interval(self) -> int:
        """当前生效的同步间隔（秒）。"""
        return self._interval

    def stop(self) -> None:
        """请求调度循环退出（幂等）。"""
        self._stop_event.set()

    def run_forever(self) -> None:
        """阻塞执行调度循环；作为 daemon 线程 target 使用。"""
        logger.info(
            "project status sync scheduler started (interval=%ss)", self._interval
        )
        try:
            while not self._stop_event.is_set():
                self.tick()
                if self._stop_event.wait(self._interval):
                    break
                # wait 返回 False 表示超时到期，进入下一 tick。
        finally:
            logger.info("project status sync scheduler stopped")

    def tick(self) -> None:
        """单次调度：新鲜绑定零网络跳过，陈旧绑定逐个补偿同步。"""
        try:
            bindings = self._db.list_eligible_sync_bindings(None)
        except Exception:
            # 数据库暂时不可用：记录后等待下一 tick，不让线程消亡。
            logger.exception("sync scheduler could not list eligible bindings")
            return
        if not bindings:
            return  # 无启用绑定：no-op。
        now = self._clock()
        for binding in bindings:
            if self._stop_event.is_set():
                return
            deliverable_id = str(binding.get("deliverable_id") or "")
            if not deliverable_id:
                continue
            if self._is_fresh(binding, now):
                logger.debug(
                    "skipping fresh binding for %s (last success within interval)",
                    deliverable_id,
                )
                continue
            try:
                self._runner.run_once(
                    deliverable_id=deliverable_id,
                    trigger_type="scheduled",
                    validate_runtime_prerequisites=False,
                )
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                # 单绑定异常（含 SyncLeaseBusyError、凭据、连接器等）：
                # 记录脱敏日志后继续，不中断循环。
                logger.warning(
                    "scheduled sync for %s failed: %s",
                    deliverable_id,
                    redact_sensitive_text(str(exc), limit=200),
                )

    def _is_fresh(self, binding: dict[str, Any], now: float) -> bool:
        """last_success_at 距今不足 interval 视为新鲜（零网络复用快照）。"""
        last_success = _parse_success_at(binding.get("last_success_at"))
        if last_success is None:
            return False
        return (now - last_success) < self._interval
