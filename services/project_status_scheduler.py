# -*- coding: utf-8 -*-
"""
services/project_status_scheduler.py — WebUI 常驻项目状态同步调度线程。

职责边界：
- 仅 WebUI 入口（webui.py）以 daemon 线程启动；CLI（main.py 的
  project-status-sync --once）与 pytest 不启动。
- 唯一后台调度器：每个 tick 先处理固定时刻执行槽（C4，DSH-V2-20），再处理
  既有 interval 补偿同步；固定时刻型与 interval 型互斥，同一项目不可既被
  interval 又被 fixed 派发（见 ``tick`` 的 fixed 项目跳过）。
- fixed 路径（注入 ``slot_store`` 时）：读 ``mode='fixed'`` 绑定 → 用
  ``services.schedule_policy`` 计算当天到点槽 → ``ensure_slots`` 落库 →
  循环 ``lease_next`` 领取 → 对该项目下全部启用交付物逐个 ``run_once`` →
  ``finish`` 收尾。去重完全依赖槽唯一键与租约，重启/暂停/切换当前项目都不会
  重复派发；派发按绑定的 project_id，与“当前项目”无关。
- 槽表不存在（插件未加载/未迁移）时视为 0 个 fixed 绑定：记一次 warning 后
  走纯 interval 路径，不建表、不调用迁移。
- interval 路径：通过 db.list_eligible_sync_bindings(None) 读取启用绑定；
  last_success_at 距今不足 interval 的绑定直接跳过（D 的新鲜度复用，
  零网络调用——既有展示层继续消费最近一次成功快照）。
- 其余绑定逐个调用 ProjectStatusSyncRunner.run_once(
  deliverable_id=<id>, trigger_type='scheduled',
  validate_runtime_prerequisites=False)，对齐 main.py CLI 定时先例：
  不做凭据/稳定键/映射前置阻断，由连接器产生可审计的运行时结果。
- 单绑定异常（含 SyncLeaseBusyError 抛出形态）记录脱敏日志后继续，
  不中断循环；stop_event 置位后线程退出。
- 本模块不 import Flask、不直接编写 SQL、不持有凭据或 lease_token；
  ``slot_store=None`` 时行为与 DSH-V2-20 之前完全一致。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from core.redaction import redact_sensitive_text
from core.time_rules import now_utc, to_beijing
from services import schedule_policy as SP

logger = logging.getLogger("vse_toolbox.sync_scheduler")

#: 默认同步间隔（秒）：15 分钟一次补偿性后台同步。
DEFAULT_SYNC_INTERVAL_SECONDS = 900

#: 环境变量覆盖：VSE_PROJECT_STATUS_SYNC_INTERVAL（秒，正整数）。
SYNC_INTERVAL_ENV_VAR = "VSE_PROJECT_STATUS_SYNC_INTERVAL"

#: fixed 槽租约时长（秒）：覆盖一次同步的常规耗时；崩溃后当天可重入队一次。
FIXED_LEASE_SECONDS = 900
#: fixed 槽失败重试退避（秒）：C4 要求 ≥300；同一槽最多尝试 2 次。
FIXED_RETRY_SECONDS = 300
#: fixed 槽执行失败（未抛异常）时的兜底错误码。
FIXED_FAILURE_CODE = "run_failed"
#: 调度线程在槽执行途中被暂停/停止时的错误码（不重试，避免重复副作用）。
FIXED_STOPPED_CODE = "scheduler_stopped"

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


class _SyncSchedulerSlotStore(Protocol):
    """调度器依赖的槽存储最小协议（``services.schedule_slots.SlotStore`` 满足）。"""

    def list_bindings(self, mode: str | None = None) -> list[dict[str, Any]]:
        ...

    def list_slots(self, project_id: str, business_date: Any) -> list[dict[str, Any]]:
        ...

    def ensure_slots(self, slots: Any) -> int:
        ...

    def lease_next(
        self, owner: str, *, lease_seconds: int, business_date: Any
    ) -> dict[str, Any] | None:
        ...

    def finish(
        self,
        key: Any,
        token: str,
        *,
        ok: bool,
        error_code: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> bool:
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


def _is_missing_table_error(exc: BaseException) -> bool:
    """sqlite ``no such table`` 判定：插件未加载/未迁移时槽表不存在。"""
    return isinstance(exc, sqlite3.OperationalError) and "no such table" in str(exc).lower()


class ProjectStatusSyncScheduler:
    """可注入 clock/interval/runner/stop_event/slot_store 的常驻同步调度循环。"""

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
        slot_store: _SyncSchedulerSlotStore | None = None,
        clock_utc: Callable[[], datetime] | None = None,
        lease_owner: str | None = None,
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
        # fixed 槽（C4）：slot_store 为 None 时整条 fixed 路径关闭，行为与旧版一致。
        self._slot_store = slot_store
        self._clock_utc = clock_utc if clock_utc is not None else now_utc
        owner = str(lease_owner or "").strip()
        self._lease_owner = owner or f"webui-sync-{os.getpid()}"
        self._fixed_tables_missing = False
        self._fixed_warning_emitted = False
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
        """获取当前调度器运行状态快照（含 fixed 绑定数与 fixedMode）。"""
        now = self._clock()
        eligible_count = 0
        try:
            eligible_count = len(self._db.list_eligible_sync_bindings(None))
        except Exception:
            pass
        fixed_bindings = 0
        if self._slot_store is not None:
            rows = self._list_fixed_bindings()
            fixed_bindings = len(rows) if rows is not None else 0
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
            "fixedBindings": fixed_bindings,
            "fixedMode": "on" if fixed_bindings > 0 else "off",
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
        """单次调度：先派发 fixed 槽，再补偿 interval 陈旧绑定（fixed 项目跳过）。"""
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
        try:
            fixed_project_ids = self._dispatch_fixed_slots(bindings)
        except KeyboardInterrupt:
            raise
        except Exception:
            # fixed 路径的未预期错误：本轮直接结束，不回退 interval（避免重复副作用），
            # 下一 tick 重试；绝不让调度线程因此消亡。
            logger.exception("fixed slot dispatch failed; skipping this tick")
            return
        if not bindings:
            return  # 无启用绑定：no-op。
        for binding in bindings:
            if self._stop_event.is_set() or self._paused:
                return
            deliverable_id = str(binding.get("deliverable_id") or "")
            if not deliverable_id:
                continue
            if fixed_project_ids:
                # 替换而非并存：fixed 项目的交付物只由槽派发，interval 路径不再碰。
                logger.debug(
                    "skipping interval dispatch for %s (project has fixed bindings)",
                    deliverable_id,
                )
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

    # ── fixed 槽派发（C4，DSH-V2-20） ─────────────────────────────────────

    def _list_fixed_bindings(self) -> list[dict[str, Any]] | None:
        """读 fixed 绑定；``None`` 表示槽表不存在或读取失败（fixed 路径降级）。

        槽表不存在（插件未加载/未迁移）只记一次 warning 并缓存判定：之后不再查询，
        避免每个 tick / 每次状态轮询都触发一次 SQLite 错误日志。不建表、不迁移。
        """
        if self._slot_store is None or self._fixed_tables_missing:
            return None
        try:
            return list(self._slot_store.list_bindings(SP.JOB_KIND_FIXED))
        except Exception as exc:
            if _is_missing_table_error(exc):
                self._fixed_tables_missing = True
                if not self._fixed_warning_emitted:
                    logger.warning(
                        "fixed slot tables are missing (%s); fixed scheduling disabled, "
                        "interval path unchanged",
                        redact_sensitive_text(str(exc), limit=200),
                    )
                    self._fixed_warning_emitted = True
                return None
            logger.warning(
                "could not list fixed sync bindings: %s",
                redact_sensitive_text(str(exc), limit=200),
            )
            return None

    def _dispatch_fixed_slots(self, deliverable_bindings: list[dict[str, Any]]) -> set[str]:
        """计算并派发当天到点的 fixed 槽；返回「fixed 同步项目」id 集合。

        槽表不存在（插件未加载/未迁移）时视为 0 个 fixed 绑定，调用方继续走纯
        interval 路径（与 DSH-V2-20 之前一致）。
        """
        fixed_bindings = self._list_fixed_bindings()
        if not fixed_bindings:
            return set()

        now_utc_value = self._clock_utc()
        business_date = to_beijing(now_utc_value).date()
        fixed_project_ids: set[str] = set()
        for row in fixed_bindings:
            project_id = str(row.get("projectId") or "").strip()
            job_id = str(row.get("jobId") or "").strip()
            if not project_id:
                continue
            if job_id != SP.SYNC_JOB_ID:
                # 只派发项目状态同步任务；其它 fixed 任务（如日报）尚无 runner 接线。
                continue
            fixed_project_ids.add(project_id)
            try:
                binding = SP.sync_binding(
                    project_id,
                    job_id=job_id,
                    times=row.get("times") or (),
                    paused=bool(row.get("paused")),
                )
                existing = self._slot_store.list_slots(project_id, business_date)
                due = SP.compute_due_slots(
                    binding, now=now_utc_value, existing_keys=existing
                )
                if due:
                    self._slot_store.ensure_slots(due)
            except Exception as exc:
                logger.warning(
                    "fixed slot planning failed for project %s: %s",
                    project_id,
                    redact_sensitive_text(str(exc), limit=200),
                )
                continue
        self._run_leased_slots(business_date, deliverable_bindings)
        return fixed_project_ids

    def _run_leased_slots(
        self, business_date: Any, deliverable_bindings: list[dict[str, Any]]
    ) -> None:
        """循环领取并执行当天 fixed 槽，直到没有可领取的槽。"""
        deliverable_ids = self._project_deliverable_ids(deliverable_bindings)
        while not self._stop_event.is_set() and not self._paused:
            try:
                leased = self._slot_store.lease_next(
                    self._lease_owner,
                    lease_seconds=FIXED_LEASE_SECONDS,
                    business_date=business_date,
                )
            except Exception as exc:
                logger.warning(
                    "could not lease a fixed slot: %s",
                    redact_sensitive_text(str(exc), limit=200),
                )
                return
            if leased is None:
                return
            try:
                self._execute_leased_slot(leased, deliverable_ids)
            except KeyboardInterrupt:
                raise
            except Exception:
                # 未预期错误（如槽行损坏）：租约留在原地按崩溃恢复处理，不再重跑。
                logger.exception(
                    "fixed slot execution failed unexpectedly; leaving lease to expire"
                )
                return

    def _project_deliverable_ids(self, deliverable_bindings: list[dict[str, Any]]) -> list[str]:
        """fixed 项目下的全部启用交付物 id。

        映射口径（只读既有方法，不新增 SQL）：ADR-0001 定「一个项目一个数据根」，
        ``project_status_update_bindings`` 没有 project_id 列，本库的启用绑定天然
        都属于当前项目；因此按 ``list_eligible_sync_bindings(None)`` 取交付物，
        不新建跨项目映射（主控裁决项见交付报告）。
        """
        deliverable_ids: list[str] = []
        for binding in deliverable_bindings:
            deliverable_id = str(binding.get("deliverable_id") or "").strip()
            if deliverable_id and deliverable_id not in deliverable_ids:
                deliverable_ids.append(deliverable_id)
        return deliverable_ids

    def _execute_leased_slot(
        self, leased: dict[str, Any], deliverable_ids: list[str]
    ) -> None:
        """执行一个已领取的槽：全部交付物成功才算成功，收尾带 fencing。"""
        key = SP.slot_key_from_mapping(leased)
        token = str(leased.get("leaseToken") or "")
        error_code: str | None = None
        if not deliverable_ids:
            logger.info(
                "fixed slot %s has no enabled deliverable bindings; nothing to run",
                key.as_text(),
            )
        for deliverable_id in deliverable_ids:
            if self._stop_event.is_set() or self._paused:
                # 暂停/停止打断：落 failed（不重试），避免恢复后重复副作用。
                self._finish_slot(key, token, FIXED_STOPPED_CODE)
                return
            try:
                result = self._runner.run_once(
                    deliverable_id=deliverable_id,
                    trigger_type="scheduled",
                    validate_runtime_prerequisites=False,
                )
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                error_code = type(exc).__name__
                logger.warning(
                    "fixed sync for %s failed: %s",
                    deliverable_id,
                    redact_sensitive_text(str(exc), limit=200),
                )
                break
            failure = self._run_failure_code(result)
            if failure is not None:
                error_code = failure
                logger.warning(
                    "fixed sync for %s finished as failed (%s)",
                    deliverable_id,
                    failure,
                )
                break
        self._finish_slot(key, token, error_code)

    def _finish_slot(
        self, key: Any, token: str, error_code: str | None
    ) -> None:
        """收尾槽：失败带 300 秒退避；被 fencing 时只记日志，不重跑。"""
        try:
            finished = self._slot_store.finish(
                key,
                token,
                ok=error_code is None,
                error_code=error_code,
                # 暂停/停止打断不重试（不补跑，避免恢复后重复副作用）；其余失败 300 秒退避。
                retry_after_seconds=(
                    None
                    if error_code is None or error_code == FIXED_STOPPED_CODE
                    else FIXED_RETRY_SECONDS
                ),
            )
        except Exception as exc:
            logger.warning(
                "could not finish fixed slot %s: %s",
                getattr(key, "as_text", lambda: str(key))(),
                redact_sensitive_text(str(exc), limit=200),
            )
            return
        if not finished:
            logger.warning(
                "fixed slot %s finish was fenced (lease token mismatch); not re-running",
                getattr(key, "as_text", lambda: str(key))(),
            )

    @staticmethod
    def _run_failure_code(result: Any) -> str | None:
        """从 runner 返回值里取失败错误码；成功或未知形状返回 None。"""
        results = getattr(result, "results", None)
        if not results:
            return None
        for item in results:
            if (
                getattr(item, "outcome", None) == "failed"
                or getattr(item, "final_state", None) == "failed"
            ):
                code = str(getattr(item, "error_type", "") or "").strip()
                return (code or FIXED_FAILURE_CODE)[:100]
        return None

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
