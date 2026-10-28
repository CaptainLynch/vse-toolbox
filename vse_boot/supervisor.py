# -*- coding: utf-8 -*-
"""Supervisor process: pick a version, start the app as a child, trial, commit or roll back.

The app runs in a child process so that a broken trial version (import error,
crash, failing health check) can be stopped and replaced by the previous
version without the user doing anything.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from vse_boot import dbsnap
from vse_boot.layout import InstallLayout
from vse_boot.state import BootState, BootStateError

HEALTH_TIMEOUT_SECONDS = 45.0
_MAX_APP_LOG_BYTES = 2 * 1024 * 1024
_POLL_SECONDS = 0.5
_MAX_BOOT_ATTEMPTS = 3


class ChildProcess(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


# ── default side effects ─────────────────────────────────────────────


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def spawn_app(app_dir: Path, port: int, layout: InstallLayout) -> ChildProcess:
    env = dict(os.environ)
    env["VSE_DATA_ROOT"] = str(layout.root)
    env["VSE_INSTALL_ROOT"] = str(layout.root)
    # vse_boot 本身所在目录（生产环境是运行时的 site-packages）；app 目录由 app_main 插到最前面。
    boot_parent = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = boot_parent + os.pathsep + env.get("PYTHONPATH", "") if env.get("PYTHONPATH") else boot_parent
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if getattr(sys, "frozen", False):
        command = [sys.executable, "--app-child", "--app-dir", str(app_dir), "--port", str(port)]
    else:
        command = [sys.executable, "-m", "vse_boot", "--app-child", "--app-dir", str(app_dir), "--port", str(port)]
    log_path = layout.state_dir / "app-last-run.log"
    if log_path.is_file() and log_path.stat().st_size > _MAX_APP_LOG_BYTES:
        os.replace(log_path, log_path.with_name("app-last-run.1.log"))
    # 追加而不是覆盖：回滚后紧接着启动的旧版本不能把失败版本的报错冲掉。
    with open(log_path, "ab") as log:
        banner = f"===== {time.strftime('%Y-%m-%d %H:%M:%S')} start {app_dir.name} port {port} ====="
        log.write(("\n" + banner + "\n").encode("utf-8"))
        log.flush()
        child = subprocess.Popen(
            command,
            cwd=str(app_dir),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
    _JOB.assign(child)
    return child


class _KillOnCloseJob:
    """Windows Job Object: when the supervisor dies, the app child (and its Excel worker) die too.

    Without it, ending VSE-Toolbox.exe in Task Manager leaves the app running;
    the next start would then run a second app on the same database.
    """

    def __init__(self) -> None:
        self._handle = None

    def _create(self):  # type: ignore[no-untyped-def]
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class BASIC(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
            ]

        class EXTENDED(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            return None
        return kernel32, job

    def assign(self, child) -> None:  # type: ignore[no-untyped-def]
        if os.name != "nt" or not hasattr(child, "_handle"):
            return
        try:
            if self._handle is None:
                self._handle = self._create() or False
            if self._handle:
                kernel32, job = self._handle
                kernel32.AssignProcessToJobObject(job, int(child._handle))
        except (OSError, AttributeError, ValueError):
            pass  # 尽力而为：失败时退回到"监督进程正常退出时结束子进程"


_JOB = _KillOnCloseJob()


def probe_app(port: int) -> bool:
    base = f"http://127.0.0.1:{port}"
    for path in ("/api/version", "/api/host/manifest"):
        try:
            with urllib.request.urlopen(base + path, timeout=2) as response:
                if response.status != 200:
                    return False
        except (urllib.error.URLError, OSError):
            return False
    return True


def _edge_path() -> str | None:
    candidates = [
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), r"Microsoft\Edge\Application\msedge.exe"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return shutil.which("msedge")


def open_window(url: str, layout: InstallLayout) -> None:
    """Edge app window with its own profile (no address bar); default browser as fallback."""
    edge = _edge_path()
    if edge:
        profile = layout.state_dir / "edge-profile"
        try:
            subprocess.Popen([edge, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run"])
            return
        except OSError:
            pass
    webbrowser.open(url)


# ── single instance ──────────────────────────────────────────────────


class InstanceLock:
    """An exclusive lock on ``state/instance.lock`` held for the supervisor's lifetime."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: Any = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")  # noqa: SIM115 - kept open while locked
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None


# ── supervisor ───────────────────────────────────────────────────────


@dataclass
class Supervisor:
    layout: InstallLayout
    spawn: Callable[[Path, int, InstallLayout], ChildProcess] = spawn_app
    probe: Callable[[int], bool] = probe_app
    show: Callable[[str, InstallLayout], None] = open_window
    pick_port: Callable[[], int] = free_port
    health_timeout: float = HEALTH_TIMEOUT_SECONDS
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    log: Callable[[str], None] = print
    lock: InstanceLock | None = field(default=None)

    def run(self) -> int:
        self.layout.ensure()
        lock = self.lock or InstanceLock(self.layout.lock_file)
        if not lock.acquire():
            return self._show_existing()
        try:
            return self._run_locked()
        finally:
            self.layout.instance_file.unlink(missing_ok=True)
            lock.release()

    def _show_existing(self) -> int:
        try:
            info = json.loads(self.layout.instance_file.read_text(encoding="utf-8"))
            self.show(str(info["url"]), self.layout)
            return 0
        except (OSError, ValueError, KeyError):
            self.log("VSE Toolbox 正在启动，请稍候再打开。")
            return 0

    def _run_locked(self) -> int:
        state = BootState(self.layout)
        for version in state.install_staged():
            self.log(f"已安装新版本 {version}")
        for _ in range(_MAX_BOOT_ATTEMPTS):
            try:
                version, trial = state.select_for_boot()
            except BootStateError as exc:
                self.log(str(exc))
                return 2
            app_dir = self.layout.app_dir(version)
            if trial:
                self._snapshot_before_trial(state, version)
            port = self.pick_port()
            self.log(f"启动 VSE Toolbox {version}{'（试用）' if trial else ''}")
            child = self.spawn(app_dir, port, self.layout)
            healthy, reason = self._wait_healthy(child, port)
            if healthy:
                if trial:
                    state.commit(version)
                    self.log(f"新版本 {version} 已生效")
                return self._serve(child, port, version)
            self._stop(child)
            if not trial:
                self.log(f"VSE Toolbox {version} 无法启动：{reason}")
                state.record("bootFailed", version, reason=reason)
                return 3
            state.abandon(version, reason=reason)  # 也负责恢复试用前的数据库快照
            self.log(f"新版本 {version} 启动失败（{reason}），已自动回到之前的版本")
        return 3

    def _snapshot_before_trial(self, state: BootState, version: str) -> None:
        """Every trial gets a snapshot: migrations run from app code whether or not the
        release declared them, and the database is only a few MB."""
        if state.app.get("trialSnapshot") and Path(state.app["trialSnapshot"]).is_file():
            return
        snap = dbsnap.snapshot(self.layout.database, self.layout.snapshots_dir, tag=version)
        state.set_trial_snapshot(str(snap) if snap else None)

    def _wait_healthy(self, child: ChildProcess, port: int) -> tuple[bool, str]:
        deadline = self.clock() + self.health_timeout
        while self.clock() < deadline:
            code = child.poll()
            if code is not None:
                return False, f"程序启动后立即退出（退出码 {code}）"
            if self.probe(port):
                return True, ""
            self.sleep(_POLL_SECONDS)
        return False, f"{int(self.health_timeout)} 秒内没有完成启动"

    def _serve(self, child: ChildProcess, port: int, version: str) -> int:
        url = f"http://127.0.0.1:{port}/"
        info = {"url": url, "port": port, "version": version, "pid": child.pid, "supervisorPid": os.getpid()}
        self.layout.instance_file.write_text(json.dumps(info), encoding="utf-8")
        self.show(url, self.layout)
        try:
            return child.wait()
        except KeyboardInterrupt:
            self._stop(child)
            return 0

    @staticmethod
    def _stop(child: ChildProcess) -> None:
        if child.poll() is not None:
            return
        child.terminate()
        try:
            child.wait(timeout=10)
        except Exception:
            child.kill()
