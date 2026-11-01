# -*- coding: utf-8 -*-
"""Supervisor process: pick a version, start the app as a child, trial, commit or roll back.

The app runs in a child process so that a broken trial version (import error,
crash, failing health check) can be stopped and replaced by the previous
version without the user doing anything.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from vse_boot import dbsnap, projects
from vse_boot.layout import InstallLayout
from vse_boot.state import BootState, BootStateError

HEALTH_TIMEOUT_SECONDS = 45.0
#: 窗口子进程的启动宽限期（C2）：这段时间内以非 0 退出码结束才降级到 Edge/浏览器。
WINDOW_STARTUP_GRACE_SECONDS = 15.0
_MAX_APP_LOG_BYTES = 2 * 1024 * 1024
_POLL_SECONDS = 0.5
_MAX_BOOT_ATTEMPTS = 3
_MAX_CRASH_RESTARTS = 2
#: 端口被其他进程占用时换端口重试的次数上限（C4）。
_MAX_PORT_RETRIES = 3


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


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


class Controls:
    """Requests from the tray (same process) to the supervisor loop."""

    def __init__(self) -> None:
        self.quit = threading.Event()
        self.restart = threading.Event()


def spawn_app(app_dir: Path, port: int, layout: InstallLayout) -> ChildProcess:
    env = dict(os.environ)
    # 多项目：每个项目一个数据文件夹，启动前按当前项目选定（vse_boot/projects.py）。
    env["VSE_DATA_ROOT"] = str(projects.active_data_root(layout))
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


def webview_available() -> bool:
    """pywebview 是否可用：只看模块能否找到，不在启动器里 import（C1）。"""
    if "webview" in sys.modules:
        return sys.modules["webview"] is not None
    try:
        return importlib.util.find_spec("webview") is not None
    except (ImportError, ValueError):
        return False


def _load_webview():  # type: ignore[no-untyped-def]
    """只在 ``--window`` 子进程里调用。"""
    return importlib.import_module("webview")


def _parse_window_argv(argv: list[str]) -> tuple[str | None, Path | None]:
    """``--window URL --profile DIR`` → (url, profile)。"""
    url: str | None = None
    profile: Path | None = None
    pending = [str(arg) for arg in argv]
    if pending[:1] == ["--window"]:
        pending = pending[1:]
    while pending:
        arg = pending.pop(0)
        if arg == "--profile" and pending:
            profile = Path(pending.pop(0))
        elif arg == "--window" and pending:
            url = pending.pop(0)
        elif url is None:
            url = arg
    return url, profile


def run_window(argv: list[str], webview_module: Any = None) -> int:
    """``--window`` 子进程入口：pywebview 必须跑在**本进程主线程**（C1）。

    退出码：正常关闭 0；pywebview 缺失 3；create_window/start 抛异常 4。
    异常信息写 stderr，并抹掉 URL——查询串里有启动票据，不能进日志。
    """
    url, profile = _parse_window_argv(argv)
    module = webview_module
    if module is None:
        try:
            module = _load_webview()
        except ImportError as exc:
            print(f"无法加载 pywebview：{exc}", file=sys.stderr)
            return 3
    try:
        module.create_window("VSE Toolbox", url, width=1280, height=860)
        module.start(private_mode=False, storage_path=str(profile) if profile is not None else None)
    except Exception as exc:  # noqa: BLE001 - 任何 GUI 失败都只值一个退出码
        detail = str(exc)
        if url:
            detail = detail.replace(url, "<url>")
        print(f"窗口启动失败：{type(exc).__name__}: {detail}", file=sys.stderr)
        return 4
    return 0


def spawn_window(url: str, profile_dir: Path, *, assign_job: bool = True) -> ChildProcess:
    """把 pywebview 窗口放进独立子进程（C1）。

    pywebview 要求 ``start()`` 在进程主线程调用，所以窗口不能是启动器里的一个
    线程。``assign_job`` 只在**长驻的**启动器进程里为 True：窗口随它一起结束；
    第二实例进程十几秒后就会退出，把窗口挂到它的 job 上会被
    KILL_ON_JOB_CLOSE 杀掉，所以那条路径必须传 False（见 ``open_window``）。
    """
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    profile = str(profile_dir)
    if getattr(sys, "frozen", False):
        command = [sys.executable, "--window", url, "--profile", profile]
    else:
        command = [sys.executable, "-m", "vse_boot", "--window", url, "--profile", profile]
    child = subprocess.Popen(command, creationflags=flags)
    if assign_job:
        _JOB.assign(child)  # 启动器退出时窗口一起关掉，不留孤儿进程
    return child


def wait_window_exit(child: ChildProcess, timeout: float) -> int | None:
    """最多等 ``timeout`` 秒：仍在运行返回 None（宽限期内没退出 = 窗口正常）。"""
    try:
        return child.wait(timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None


def _watch_window(
    child: ChildProcess,
    fallback: Callable[[], None],
    wait: Callable[[ChildProcess, float], int | None],
) -> None:
    """窗口监视线程体：宽限期内非 0 退出才降级，绝不无限等待（C2）。"""
    try:
        code = wait(child, WINDOW_STARTUP_GRACE_SECONDS)
    except Exception:  # noqa: BLE001 - 监视线程的异常不能外溢
        return
    if code:
        try:
            fallback()
        except Exception:  # noqa: BLE001 - 降级本身失败也不能崩线程
            pass


def open_window(
    url: str,
    layout: InstallLayout,
    *,
    spawn: Callable[[str, Path], ChildProcess] | None = None,
    find_webview: Callable[[], bool] | None = None,
    wait: Callable[[ChildProcess, float], int | None] | None = None,
    fallback: Callable[[], None] | None = None,
    assign_job: bool | None = None,
) -> None:
    """三级回退开窗（W16-02 / DSH-V2-47 C2）：pywebview 子进程 → Edge app → 默认浏览器。

    pywebview 是 WebView2 封装，体验最接近桌面应用，但第三方依赖可能缺失；
    Edge app 模式有自己的独立配置目录（无地址栏）；两者都不可用才退到默认
    浏览器标签页。本函数**立即返回**：pywebview 在独立子进程里跑（见
    ``spawn_window``），本进程只起一个非 daemon 的 ``vse-window-watch`` 线程，
    在 ``WINDOW_STARTUP_GRACE_SECONDS`` 内盯住子进程，只有它以非 0 退出码结束
    （或 spawn 失败）才降级。非 daemon 是因为第二实例唤起窗口后进程马上退出，
    daemon 线程会被直接杀掉、降级判定永远不发生。

    ``assign_job`` 默认按「本进程是不是长驻的启动器」决定：只有持有实例锁的
    启动器才把窗口收进自己的 job（启动器一退窗口就退）；第二实例拿不到锁，
    它开出的窗口不能跟着这个十几秒后就退出的进程一起死。
    """
    if assign_job is None:
        assign_job = launcher_holds_instance_lock(layout.lock_file)
    spawn_fn = spawn or (
        lambda target, profile: spawn_window(target, profile, assign_job=assign_job)
    )
    available = find_webview or webview_available
    wait_fn = wait or wait_window_exit
    fallback_fn = fallback or (lambda: _open_edge_or_browser(url, layout))
    if not available():
        fallback_fn()
        return
    profile = layout.state_dir / "webview-profile"
    try:
        child = spawn_fn(url, profile)
    except OSError:
        fallback_fn()
        return
    threading.Thread(
        target=_watch_window,
        args=(child, fallback_fn, wait_fn),
        name="vse-window-watch",
        daemon=False,
    ).start()


def _open_edge_or_browser(url: str, layout: InstallLayout) -> None:
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


#: 本进程里正在跑「长驻启动器」的实例锁路径（见 ``Supervisor.run``）。
#: 只有这些进程可以把窗口收进自己的 job；第二实例不在其中。
_OWNER_LOCKS: set[str] = set()


def _lock_key(path: Path) -> str:
    try:
        return os.path.normcase(str(Path(path).resolve()))
    except OSError:  # pragma: no cover - 路径异常时退化成字面比较
        return os.path.normcase(str(path))


def launcher_holds_instance_lock(path: Path) -> bool:
    """本进程是不是持有该实例锁的长驻启动器（C1/C3）。

    第二实例拿不到锁，它只负责唤起已有窗口然后退出；窗口若被挂到它的 job 上，
    KILL_ON_JOB_CLOSE 会在它退出时把刚开的窗口杀掉。
    """
    return _lock_key(path) in _OWNER_LOCKS


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
    #: ``tray(supervisor)`` starts a tray icon and returns an object with ``stop()`` and ``notify(text)``.
    tray: Callable[["Supervisor"], Any] | None = None
    port_free: Callable[[int], bool] = port_is_free
    controls: Controls = field(default_factory=Controls)
    url: str | None = field(default=None, init=False)
    version: str | None = field(default=None, init=False)
    _tray_handle: Any = field(default=None, init=False, repr=False)

    def notify(self, text: str) -> None:
        self.log(text)
        if self._tray_handle is not None:
            try:
                self._tray_handle.notify(text)
            except Exception:  # noqa: BLE001 - a tray balloon is best effort
                pass

    def run(self) -> int:
        self.layout.ensure()
        lock = self.lock or InstanceLock(self.layout.lock_file)
        if not lock.acquire():
            return self._show_existing()
        # 本进程现在才是长驻启动器：只有它能把自己的窗口收进 job（见 open_window）。
        key = _lock_key(lock.path)
        _OWNER_LOCKS.add(key)
        try:
            return self._run_locked()
        finally:
            _OWNER_LOCKS.discard(key)
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
        if self.tray is not None:
            try:
                self._tray_handle = self.tray(self)
            except Exception as exc:  # noqa: BLE001 - no tray is not fatal
                self.log(f"托盘图标不可用：{exc}")
        try:
            return self._loop()
        finally:
            if self._tray_handle is not None:
                try:
                    self._tray_handle.stop()
                except Exception:  # noqa: BLE001
                    pass

    def _loop(self) -> int:
        port: int | None = None
        crashes = 0
        first = True
        port_retries = 0
        while True:
            # 端口尽量沿用：重启后已打开的窗口刷新一下就能继续用。
            if port is None:
                port = self.pick_port()
                first = True
            outcome, code = self._boot(port, open_window=first)
            first = False
            if outcome == "port_conflict":
                # C4：端口被别的进程占着——换一个端口重来，不杀占用者、不打扰用户。
                port_retries += 1
                if port_retries > _MAX_PORT_RETRIES:
                    self.log(f"端口 {port} 连续被其他程序占用，已重试 {_MAX_PORT_RETRIES} 次仍无法启动；"
                             "请关闭占用该端口的程序后再打开 VSE Toolbox。")
                    return 3
                port = self.pick_port()
                first = True  # 新端口意味着新 URL，需要重新开窗
                continue
            port_retries = 0
            if outcome == "restart":
                crashes = 0
                continue
            if outcome == "crashed" and crashes < _MAX_CRASH_RESTARTS and not self.controls.quit.is_set():
                crashes += 1
                self.log(f"程序意外退出（退出码 {code}），正在自动重启")
                continue
            return code

    def _boot(self, port: int, *, open_window: bool) -> tuple[str, int]:
        self.layout.restart_request.unlink(missing_ok=True)
        self.layout.quit_request.unlink(missing_ok=True)
        self.controls.restart.clear()
        state = BootState(self.layout)
        for version in state.install_staged():
            self.log(f"已安装新版本 {version}")
        for _ in range(_MAX_BOOT_ATTEMPTS):
            if not self.port_free(port):
                self.log(f"端口 {port} 已被其他程序占用，换一个端口重试")
                return "port_conflict", 0
            try:
                version, trial = state.select_for_boot()
            except BootStateError as exc:
                self.log(str(exc))
                return "failed", 2
            app_dir = self.layout.app_dir(version)
            if trial:
                self._snapshot_before_trial(state, version)
            self.log(f"启动 VSE Toolbox {version}{'（试用）' if trial else ''}")
            # C7（W16-03）：启动器生成短时单次启动票据，经环境变量传给服务进程、
            # 经 ?boot= 查询串传给页面；服务端校验单次+TTL 后换会话 Cookie。
            # 经 os.environ 传递（不进命令行，避免本机进程列表可见）。
            self.boot_token = secrets.token_urlsafe(32)
            os.environ["VSE_BOOT_TOKEN"] = self.boot_token
            child = self.spawn(app_dir, port, self.layout)
            healthy, reason = self._wait_healthy(child, port)
            if healthy:
                if trial:
                    state.commit(version)
                    self.notify(f"VSE Toolbox 已更新到 {version}")
                return self._serve(child, port, version, open_window=open_window)
            exited = child.poll()
            self._stop(child)
            # C4：子进程没起来且端口已被别的进程占住 = 端口冲突，不是版本坏了。
            # 既不能记 bootFailed，也不能放弃试用版本，否则用户得手工干预。
            if exited is not None and not self.port_free(port):
                self.log(f"端口 {port} 已被其他程序占用，换一个端口重试")
                return "port_conflict", exited
            if not trial:
                self.log(f"VSE Toolbox {version} 无法启动：{reason}")
                state.record("bootFailed", version, reason=reason)
                return "failed", 3
            state.abandon(version, reason=reason)  # 也负责恢复试用前的数据库快照
            self.notify(f"新版本 {version} 启动失败，已自动回到之前的版本")
        return "failed", 3

    def _snapshot_before_trial(self, state: BootState, version: str) -> None:
        """Every trial gets a snapshot: migrations run from app code whether or not the
        release declared them, and the database is only a few MB."""
        if state.app.get("trialSnapshot") and Path(state.app["trialSnapshot"]).is_file():
            return
        registry = projects.ProjectRegistry(self.layout)
        database = registry.database()
        snapshots = self.layout.snapshots_dir
        if registry.active_id != projects.MAIN_ID:
            snapshots = snapshots / registry.active_id
        snap = dbsnap.snapshot(database, snapshots, tag=version)
        state.set_trial_snapshot(str(snap) if snap else None, database=str(database))

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

    def _serve(self, child: ChildProcess, port: int, version: str, *, open_window: bool) -> tuple[str, int]:
        boot_token = getattr(self, "boot_token", None) or ""
        # 票据附在 URL 供页面交换；instance.json 同步记录（单次+10s TTL，
        # 留存本身无价值），供重启后 _show_existing 重开窗口与本机自动化取用。
        url = f"http://127.0.0.1:{port}/?boot={boot_token}" if boot_token else f"http://127.0.0.1:{port}/"
        self.url, self.version = url, version
        info = {"url": url, "port": port, "version": version, "pid": child.pid,
                "supervisorPid": os.getpid(), "bootToken": boot_token}
        self.layout.instance_file.write_text(json.dumps(info), encoding="utf-8")
        if open_window:
            self.show(url, self.layout)
        try:
            while True:
                code = child.poll()
                if code is not None:
                    return ("exited" if code == 0 else "crashed"), code
                if self.layout.quit_request.exists():
                    self.layout.quit_request.unlink(missing_ok=True)
                    self.controls.quit.set()
                if self.controls.quit.is_set():
                    self._stop(child)
                    return "quit", 0
                if self.controls.restart.is_set() or self.layout.restart_request.exists():
                    self.log("按请求重新启动程序")
                    self._stop(child)
                    return "restart", 0
                self.sleep(_POLL_SECONDS)
        except KeyboardInterrupt:
            self._stop(child)
            return "quit", 0

    @staticmethod
    def _stop(child: ChildProcess) -> None:
        if child.poll() is not None:
            return
        child.terminate()
        try:
            child.wait(timeout=10)
        except Exception:
            child.kill()
