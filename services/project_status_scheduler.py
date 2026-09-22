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

_GLOBAL_SCHEDULER: ProjectStatusSyncScheduler | None = None


def get_global_scheduler() -> ProjectStatusSyncScheduler | None:
    """获取当前进程常驻的项目状态同步调度器实例。"""
    return _GLOBAL_SCHEDULER


def set_global_scheduler(scheduler: ProjectStatusSyncScheduler | None) -> None:
    """设置或清理全局项目状态同步调度器实例。"""
    global _GLOBAL_SCHEDULER
    _GLOBAL_SCHEDULER = scheduler


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
        register_global: bool = True,
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
        self._paused: bool = False
        self._last_tick_time: float | None = None
        self._last_tick_at: str | None = None
        self._last_results: list[dict[str, Any]] = []
        self._wake_event: threading.Event = threading.Event()
        if register_global:
            set_global_scheduler(self)

    @property
    def interval(self) -> int:
        """当前生效的同步间隔（秒）。"""
        return self._interval

    @property
    def is_paused(self) -> bool:
        """是否已处于暂停状态。"""
        return self._paused

    def pause(self) -> None:
        """暂停自动调度循环（不终止后台线程）。"""
        self._paused = True
        logger.info("project status sync scheduler paused")

    def resume(self) -> None:
        """恢复自动调度循环并触发一次即时唤醒。"""
        self._paused = False
        self._wake_event.set()
        logger.info("project status sync scheduler resumed")

    def set_interval(self, seconds: int) -> None:
        """动态修改自动同步间隔并唤醒调度循环。"""
        if seconds <= 0:
            raise ValueError("sync interval must be a positive number of seconds")
        self._interval = seconds
        self._wake_event.set()
        logger.info("project status sync scheduler interval updated to %ss", seconds)

    def stop(self) -> None:
        """请求调度循环退出（幂等）。"""
        self._stop_event.set()
        self._wake_event.set()

    def get_status(self) -> dict[str, Any]:
        """获取当前调度器运行状态快照。"""
        now = self._clock()
        eligible_count = 0
        try:
            eligible_count = len(self._db.list_eligible_sync_bindings(None))
        except Exception:
            pass
        next_sec = None
        if not self._paused and not self._stop_event.is_set():
            if self._last_tick_time is not None:
                passed = now - self._last_tick_time
                next_sec = max(0, int(self._interval - passed))
            else:
                next_sec = self._interval
        return {
            "running": not self._stop_event.is_set(),
            "paused": self._paused,
            "intervalSeconds": self._interval,
            "lastTickAt": self._last_tick_at,
            "nextRunSeconds": next_sec,
            "eligibleCount": eligible_count,
            "lastResults": list(self._last_results),
        }

    def trigger_sync_all(self, force: bool = True) -> list[dict[str, Any]]:
        """立即同步所有已启用的交付物绑定，返回聚合结果报告。"""
        now = self._clock()
        try:
            bindings = self._db.list_eligible_sync_bindings(None)
        except Exception as exc:
            logger.exception("trigger_sync_all could not list eligible bindings")
            return [{"error": redact_sensitive_text(str(exc), limit=200)}]

        results: list[dict[str, Any]] = []
        for binding in bindings:
            deliverable_id = str(binding.get("deliverable_id") or "")
            if not deliverable_id:
                continue
            if not force and self._is_fresh(binding, now):
                continue
            try:
                runner_res = self._runner.run_once(
                    deliverable_id=deliverable_id,
                    trigger_type="sync_now",
                    validate_runtime_prerequisites=False,
                )
                item_info: dict[str, Any] = {"deliverableId": deliverable_id, "status": "success"}
                if hasattr(runner_res, "results") and runner_res.results:
                    first = runner_res.results[0]
                    item_info["outcome"] = getattr(first, "outcome", None)
                    item_info["finalState"] = getattr(first, "final_state", None)
                    item_info["appliedFields"] = list(getattr(first, "applied_fields", []))
                results.append(item_info)
            except Exception as exc:
                results.append({
                    "deliverableId": deliverable_id,
                    "status": "error",
                    "error": redact_sensitive_text(str(exc), limit=200),
                })
        self._last_results = list(results)
        self._last_tick_time = now
        self._last_tick_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return results

    def run_forever(self) -> None:
        """阻塞执行调度循环；作为 daemon 线程 target 使用。"""
        logger.info(
            "project status sync scheduler started (interval=%ss)", self._interval
        )
        try:
            while not self._stop_event.is_set():
                self.tick()
                if self._wait_for_next_tick():
                    break
        finally:
            logger.info("project status sync scheduler stopped")

    def _wait_for_next_tick(self) -> bool:
        """等待至下一次 tick 或收到停止信号。返回 True 表示应退出循环。"""
        self._wake_event.clear()
        if self._stop_event.is_set():
            return True
        start_wait = self._clock()
        while not self._stop_event.is_set():
            if self._wake_event.is_set():
                self._wake_event.clear()
                return False
            passed = self._clock() - start_wait
            remaining = self._interval - passed
            if remaining <= 0:
                return False
            slice_sec = min(remaining, 1.0)
            if self._stop_event.wait(slice_sec):
                return True
        return True

    def tick(self) -> None:
        """单次调度：新鲜绑定零网络跳过，陈旧绑定逐个补偿同步。"""
        if self._paused:
            logger.debug("sync scheduler is paused, skipping tick")
            return
        now = self._clock()
        self._last_tick_time = now
        self._last_tick_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            bindings = self._db.list_eligible_sync_bindings(None)
        except Exception:
            # 数据库暂时不可用：记录后等待下一 tick，不让线程消亡。
            logger.exception("sync scheduler could not list eligible bindings")
            return
        if not bindings:
            return  # 无启用绑定：no-op。
        for binding in bindings:
            if self._stop_event.is_set() or self._paused:
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
        interval = self._interval
        im = binding.get("interval_minutes")
        if isinstance(im, int) and not isinstance(im, bool) and im > 0:
            interval = im * 60
        return (now - last_success) < interval
