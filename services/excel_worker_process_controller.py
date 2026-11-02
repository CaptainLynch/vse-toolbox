"""Controller for the production Excel worker subprocess."""

from __future__ import annotations

import logging
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core.excel_tasks import ExcelTaskRepository

logger = logging.getLogger(__name__)

#: 自动启停契约（主控冻结）：空闲判定窗口、监视线程节拍与崩溃重启预算。
DEFAULT_IDLE_TIMEOUT_SECONDS = 300.0
DEFAULT_MONITOR_INTERVAL_SECONDS = 5.0
DEFAULT_MAX_AUTO_RESTARTS = 3
DEFAULT_RESTART_WINDOW_SECONDS = 600.0

#: 空闲退出只统计仍在等待/执行中的任务状态；不改 core.excel_tasks 的状态机。
_ACTIVE_TASK_STATUSES = ("queued", "leased", "running")

#: 面向用户/前端的固定安全文案：不含路径、异常原文或环境细节。
SAFE_AUTO_START_ERROR = "Excel 处理进程自动启动失败，请手动启动或稍后重试"
SAFE_AUTO_RESTART_LIMIT_ERROR = "Excel 处理进程反复异常退出，已停止自动重启，请手动启动"


@dataclass(frozen=True)
class ExcelWorkerProcessStatus:
    state: str
    pid: int | None = None
    exit_code: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"state": self.state}
        if self.pid is not None:
            data["pid"] = self.pid
        if self.exit_code is not None:
            data["exitCode"] = self.exit_code
        if self.error is not None:
            data["error"] = self.error
        return data


def _worker_creation_flags() -> int:
    """Windows 下不给 Worker 子进程分配控制台窗口（宿主可能无控制台）。

    非 Windows 或旧版 subprocess 无该常量时返回 0，保持默认行为。
    """
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)


class ExcelWorkerProcessController:
    """Start and stop one worker subprocess without exposing COM to Flask."""

    def __init__(
        self,
        repository: ExcelTaskRepository,
        *,
        python_executable: str | None = None,
        project_root: Path | None = None,
        idle_timeout: float = DEFAULT_IDLE_TIMEOUT_SECONDS,
        monitor_interval: float = DEFAULT_MONITOR_INTERVAL_SECONDS,
        clock: Callable[[], float] | None = None,
        max_auto_restarts: int = DEFAULT_MAX_AUTO_RESTARTS,
        restart_window: float = DEFAULT_RESTART_WINDOW_SECONDS,
    ) -> None:
        self._repository = repository
        self._python = python_executable or sys.executable
        self._project_root = (project_root or Path(__file__).resolve().parents[1]).resolve()
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._stop_file: Path | None = None
        self._status = ExcelWorkerProcessStatus("stopped")
        # 空闲退出/崩溃恢复监视（惰性启动的守护线程）。
        self._idle_timeout = max(0.0, float(idle_timeout))
        self._monitor_interval = max(0.001, float(monitor_interval))
        self._clock = clock or time.monotonic
        self._max_auto_restarts = max(0, int(max_auto_restarts))
        self._restart_window = max(0.0, float(restart_window))
        self._monitor_thread: threading.Thread | None = None
        self._monitor_stop: threading.Event | None = None
        # 自动重启只在“已武装”时生效；手动 stop 会解除武装，下一次提交重新武装。
        self._armed = False
        self._pending_start = False
        self._stop_requested = False
        self._idle_since: float | None = None
        self._restart_times: list[float] = []

    # ── 既有手动契约（start/stop/status 语义与响应保持不变）───────────────
    def status(self) -> ExcelWorkerProcessStatus:
        with self._lock:
            process = self._process
            if process is not None:
                exit_code = process.poll()
                if exit_code is None:
                    if self._status.state != "stopping":
                        self._status = ExcelWorkerProcessStatus("running", process.pid)
                elif self._status.state in {"running", "stopping"}:
                    self._status = ExcelWorkerProcessStatus("stopped", process.pid, exit_code)
                    self._cleanup_stop_file()
            return self._status

    def start(self) -> ExcelWorkerProcessStatus:
        with self._lock:
            if self.status().state in {"running", "stopping"}:
                raise RuntimeError("Excel worker is already running or stopping")
            status = self._start_process_locked()
            self._restart_times.clear()
            return status

    def stop(self, timeout: float = 10.0) -> ExcelWorkerProcessStatus:
        with self._lock:
            # 手动/空闲停止优先：对当前进程解除自动重启与空闲监视，直到下一次提交。
            self._stop_requested = True
            self._armed = False
            self._pending_start = False
            self._idle_since = None
            status = self.status()
            if status.state != "running" or self._process is None:
                return status
            process = self._process
            stop_file = self._stop_file
            self._status = ExcelWorkerProcessStatus("stopping", process.pid)
            if stop_file is not None:
                stop_file.write_text("stop", encoding="ascii")
        try:
            process.wait(timeout=max(0.0, float(timeout)))
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    pass
        with self._lock:
            if self._process is process:
                self._status = ExcelWorkerProcessStatus("stopped", process.pid, process.returncode)
                self._cleanup_stop_file()
                return self._status
            if stop_file is not None:
                try:
                    stop_file.unlink(missing_ok=True)
                except OSError:
                    pass
            return self.status()

    # ── 提交自动启动（契约 1）────────────────────────────────────────────
    def ensure_running(self, *, reason: str = "submit") -> dict[str, Any]:
        """幂等保证唯一 Worker 进程在跑；返回面向路由的状态字典。

        只在本控制器 Popen 出的句柄上操作，绝不按进程名枚举/结束进程。
        """
        with self._lock:
            self._armed = True
            self._ensure_monitor_locked()
            state = self.status().state
            if state == "running":
                return {"state": "already_running"}
            if state == "stopping":
                # 不在锁内阻塞等待旧进程退出：交给监视线程在退出后启动。
                self._pending_start = True
                return {"state": "deferred"}
            try:
                self._start_process_locked()
            except Exception:
                logger.exception("Excel worker auto start failed (reason=%s)", reason)
                self._status = ExcelWorkerProcessStatus("failed", error=SAFE_AUTO_START_ERROR)
                return {"state": "failed", "error": SAFE_AUTO_START_ERROR}
            self._restart_times.clear()
            return {"state": "started"}

    # ── 空闲退出与崩溃恢复（契约 3/4/5/7）────────────────────────────────
    def close(self) -> None:
        """停止监视线程（测试与应用退出使用）；不动 Worker 进程本身。"""
        with self._lock:
            stop_event = self._monitor_stop
            thread = self._monitor_thread
            self._monitor_stop = None
            self._monitor_thread = None
            self._armed = False
        if stop_event is not None:
            stop_event.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, self._monitor_interval * 4))

    def _ensure_monitor_locked(self) -> None:
        thread = self._monitor_thread
        if thread is not None and thread.is_alive():
            return
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._monitor_loop,
            args=(stop_event,),
            name="excel-worker-monitor",
            daemon=True,
        )
        self._monitor_stop = stop_event
        self._monitor_thread = thread
        thread.start()

    def _monitor_loop(self, stop_event: threading.Event) -> None:
        while not stop_event.wait(self._monitor_interval):
            try:
                self._monitor_tick()
            except Exception:
                # 监视线程异常只记日志：不得退出宿主，也不得打断请求线程。
                logger.exception("Excel worker monitor tick failed")

    def _monitor_tick(self) -> None:
        action: str | None = None
        with self._lock:
            if not self._armed:
                return
            state = self.status().state
            if state == "running":
                self._pending_start = False
                active = self._active_task_count()
                if active is None:
                    return
                if active > 0:
                    self._idle_since = None
                    return
                now = self._clock()
                if self._idle_since is None:
                    self._idle_since = now
                    return
                if now - self._idle_since >= self._idle_timeout:
                    self._idle_since = None
                    action = "idle_stop"
            elif state == "stopped":
                if self._pending_start:
                    action = "deferred_start"
                elif self._process is not None and not self._stop_requested:
                    # 非请求退出：仍有待办任务才自动重启（过期租约由 lease_next 回收）。
                    if self._active_task_count():
                        action = "restart"
        if action == "idle_stop":
            logger.info("Excel worker idle timeout reached; stopping worker process")
            self.stop()
            # 判定空闲与 stop() 之间若有新提交（拿到 already_running 后进程被停），
            # 停止后复核待办：仍有任务则重新武装并拉起，避免任务滞留 queued。
            active = self._active_task_count()
            if active:
                self.ensure_running(reason="idle_race")
        elif action == "deferred_start":
            self._auto_start(reason="deferred", count_restart=False)
        elif action == "restart":
            self._auto_start(reason="crash", count_restart=True)

    def _auto_start(self, *, reason: str, count_restart: bool) -> None:
        with self._lock:
            if not self._armed:
                return
            now = self._clock()
            if count_restart:
                self._restart_times = [
                    stamp for stamp in self._restart_times if now - stamp < self._restart_window
                ]
                if len(self._restart_times) >= self._max_auto_restarts:
                    process = self._process
                    self._status = ExcelWorkerProcessStatus(
                        "failed",
                        process.pid if process is not None else None,
                        process.returncode if process is not None else None,
                        error=SAFE_AUTO_RESTART_LIMIT_ERROR,
                    )
                    self._armed = False
                    self._pending_start = False
                    self._idle_since = None
                    logger.error(
                        "Excel worker auto restart budget exhausted (reason=%s, restarts=%d)",
                        reason,
                        len(self._restart_times),
                    )
                    return
            try:
                self._start_process_locked()
            except Exception:
                logger.exception("Excel worker auto start failed (reason=%s)", reason)
                self._status = ExcelWorkerProcessStatus("failed", error=SAFE_AUTO_START_ERROR)
                self._armed = False
                self._pending_start = False
                return
            if count_restart:
                self._restart_times.append(now)

    def _active_task_count(self) -> int | None:
        """只读统计 queued+leased+running 任务数；读取失败返回 None（本轮跳过）。"""
        total = 0
        try:
            for status in _ACTIVE_TASK_STATUSES:
                total += len(self._repository.list_tasks(status=status, limit=200))
        except Exception:
            logger.exception("Excel worker monitor could not read the task backlog")
            return None
        return total

    def _start_process_locked(self) -> ExcelWorkerProcessStatus:
        if self.status().state in {"running", "stopping"}:
            raise RuntimeError("Excel worker is already running or stopping")
        stop_file = Path(tempfile.gettempdir()) / f"vse-excel-worker-{os.getpid()}-{secrets.token_hex(8)}.stop"
        roots = self._repository.roots
        if getattr(sys, "frozen", False):
            # 单 exe 部署（2026-10-09 顾问复核方案 A）：宿主用哨兵参数自调起
            # Worker 子进程。原同目录 VSE-ExcelWorker.exe 已并入宿主；进程隔离
            # 不变——仍是一个可独立终止的子进程，Excel COM 不进宿主进程。
            executable = Path(sys.executable).resolve()
            if not executable.is_file():
                raise FileNotFoundError(
                    "Packaged WebUI executable was not found or is not a regular file"
                )
            command = [
                str(executable),
                "--excel-worker",
                "run",
                "--db",
                str(self._repository._db.db_path),
                "--stop-file",
                str(stop_file),
                "--parent-pid",
                str(os.getpid()),
            ]
            cwd = str(executable.parent)
        else:
            command = [
                self._python,
                str(self._project_root / "tools" / "excel_worker_cli.py"),
                "run",
                "--db",
                str(self._repository._db.db_path),
                "--stop-file",
                str(stop_file),
                "--parent-pid",
                str(os.getpid()),
            ]
            cwd = str(self._project_root)
        for root_id in roots.root_ids:
            command.extend(["--root", f"{root_id}={roots.get_root(root_id)}"])
        # Worker 输出写自己的日志文件：不与宿主共用日志句柄（Windows 下宿主
        # 轮转 rename 会失败），也不与宿主控制台混流。
        log_path = self._worker_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8", errors="replace") as log_handle:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=_worker_creation_flags(),
            )
        self._process = process
        self._stop_file = stop_file
        self._status = ExcelWorkerProcessStatus("running", process.pid)
        # 新进程即新的生命周期：自动重启只看它之后的非请求退出。
        self._stop_requested = False
        self._pending_start = False
        self._idle_since = None
        return self._status

    def _cleanup_stop_file(self) -> None:
        stop_file = self._stop_file
        self._stop_file = None
        if stop_file is None:
            return
        try:
            stop_file.unlink()
        except OSError:
            pass

    def _worker_log_path(self) -> Path:
        """Worker 日志落库文件同级目录（随数据目录一起被运维看到，不污染宿主日志）。"""
        return Path(self._repository._db.db_path).parent / "excel_worker.log"
