# -*- coding: utf-8 -*-
"""Supervisor process: pick a version, start the app as a child, trial, commit or roll back.

The app runs in a child process so that a broken trial version (import error,
crash, failing health check) can be stopped and replaced by the previous
version without the user doing anything.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
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
from urllib.parse import urlsplit

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
#: 第二实例等 owner 接手 window.request 的上限（契约 §5.6：最多 8 秒）。
WINDOW_REQUEST_TIMEOUT_SECONDS = 8.0
#: 等 window.request 被删除的轮询间隔（真实环境 0.2s × 40 次 = 8s）。
WINDOW_REQUEST_POLL_SECONDS = 0.2
#: 一次性票据/授权的 TTL（与 web/security.py 的冻结值一致，启动器不 import app 包：
#: app 可能是任意已安装版本，启动器必须能独立判断）。
TICKET_TTL_SECONDS = 10
#: 自动化票据文件（K6）的删除延迟：ttl + 5 秒。
HANDOFF_DELETE_DELAY_SECONDS = TICKET_TTL_SECONDS + 5
HANDOFF_ENV_VAR = "VSE_BOOT_HANDOFF"

#: 安全契约冻结路径/头名（与 web/security.py 逐字一致；启动器不 import app 包）。
CAPABILITIES_PATH = "/api/security/capabilities"
WINDOW_GRANT_PATH = "/api/security/window-grant"
LAUNCHER_SECRET_HEADER = "X-VSE-Launch-Secret"
SECURITY_CONTRACT_VERSION = 1
#: instance.json 的 schemaVersion（契约 §5.9）。
INSTANCE_SCHEMA_VERSION = 2

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})



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


# ── 状态文件（契约 §6.8）：均不含任何秘密 ────────────────────────────
def window_request_path(layout: InstallLayout) -> Path:
    """第二实例 → owner 的“请重新开窗”请求（无秘密，被 owner 消费后删除）。"""
    return Path(layout.state_dir) / "window.request"


def handoff_path(layout: InstallLayout) -> Path:
    """自动化工具的一次性票据文件（仅 ``VSE_BOOT_HANDOFF=1`` 时创建）。"""
    return Path(layout.state_dir) / "boot-handoff.json"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """原子写：先写 ``<name>.tmp`` 再 ``os.replace``，读者绝不会看到半个文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / (path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _public_base_url(info: dict[str, Any]) -> str | None:
    """instance.json → 可公开的本机地址；查询串一律丢弃（票据绝不从这里取用）。"""
    port = info.get("port")
    if isinstance(port, int) and not isinstance(port, bool) and 0 < port < 65536:
        return f"http://127.0.0.1:{port}/"
    url = info.get("url")
    if not isinstance(url, str) or not url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if host not in _LOOPBACK_HOSTS:
        return None
    resolved = parts.port or (443 if parts.scheme == "https" else 80)
    return f"http://{host}:{resolved}/"


def _accepts_broker(callback: Callable[..., None]) -> bool:
    """``show`` 是否支持 ``broker=``：默认 ``open_window`` 支持；老式 2 参 callable
    （headless 日志输出、测试替身）保持原签名，不需要跟着改。"""
    try:
        parameters = inspect.signature(callback).parameters
    except (TypeError, ValueError):
        return False
    if "broker" in parameters:
        return True
    return any(item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values())


class Controls:
    """Requests from the tray (same process) to the supervisor loop."""

    def __init__(self) -> None:
        self.quit = threading.Event()
        self.restart = threading.Event()


def spawn_app(
    app_dir: Path,
    port: int,
    layout: InstallLayout,
    *,
    env_overrides: dict[str, str] | None = None,
) -> ChildProcess:
    """启动 app 子进程。

    C7（DSH-V2-03）：票据与启动器密钥只经**继承的环境变量**（``env=``）下发，
    绝不写 ``os.environ``——否则它们会泄漏给启动器自身随后创建的所有子进程
    （窗口子进程、Excel worker）。
    """
    env = dict(os.environ)
    # 多项目：每个项目一个数据文件夹，启动前按当前项目选定（vse_boot/projects.py）。
    env["VSE_DATA_ROOT"] = str(projects.active_data_root(layout))
    env["VSE_INSTALL_ROOT"] = str(layout.root)
    # vse_boot 本身所在目录（生产环境是运行时的 site-packages）；app 目录由 app_main 插到最前面。
    boot_parent = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = boot_parent + os.pathsep + env.get("PYTHONPATH", "") if env.get("PYTHONPATH") else boot_parent
    if env_overrides:
        env.update({str(key): str(value) for key, value in env_overrides.items()})
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


def probe_capabilities(port: int, timeout: float = 2.0) -> dict[str, Any] | None:
    """探测 app 是否支持新契约（``grantArm``）。

    任何失败（超时 / 404 / JSON 非法 / 缺字段）都返回 None，调用方一律按
    “旧 app”处理（契约 §8.2）。启动器不 import app 包：app 可能是任意版本。
    """
    url = f"http://127.0.0.1:{port}{CAPABILITIES_PATH}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else None


class WindowBroker:
    """新契约下的开窗授权代理：只用启动器密钥向 app 预置一次性授权。

    启动器密钥只存在于本进程内存与 app 子进程环境里：不落盘、不进 argv、
    不进日志、绝不交给窗口子进程（契约 §5.3）。
    """

    def __init__(self, port: int, secret: str, *, timeout: float = 5.0) -> None:
        self.base_url = f"http://127.0.0.1:{port}"
        self._secret = secret
        self._timeout = timeout

    def arm(self, purpose: str, delivery: str) -> dict[str, Any] | None:
        """``POST /api/security/window-grant``；失败返回 None（调用方降级，绝不放大权限）。"""
        if not self._secret:
            return None
        body = json.dumps({"purpose": purpose, "delivery": delivery}).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + WINDOW_GRANT_PATH,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": self.base_url,
                LAUNCHER_SECRET_HEADER: self._secret,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError):
            return None
        data = payload.get("data") if isinstance(payload, dict) else None
        return data if isinstance(data, dict) else None


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


class BootBridge:
    """pywebview ``js_api`` 桥：把宿主注入的一次性票据交给页面，只交付一次。

    页面在 ``window.pywebview.api.take_boot_ticket()`` 里取票后立刻换会话；
    票据不打印、不写日志，取走后桥内即置空（纵深防御，契约 §5.4）。
    """

    def __init__(self, ticket: str | None = None) -> None:
        self._ticket = ticket
        self._lock = threading.Lock()

    def take_boot_ticket(self) -> str | None:
        with self._lock:
            ticket, self._ticket = self._ticket, None
        return ticket


def run_window(argv: list[str], webview_module: Any = None) -> int:
    """``--window`` 子进程入口：pywebview 必须跑在**本进程主线程**（C1）。

    退出码：正常关闭 0；pywebview 缺失 3；create_window/start 抛异常 4。
    票据只经环境变量进入本进程，注入桥之后立即从 ``os.environ`` 清除；异常信息
    先抹掉 URL（旧链路）与票据子串，再写 stderr——票据绝不进日志。
    """
    url, profile = _parse_window_argv(argv)
    ticket = os.environ.pop("VSE_WINDOW_BOOT_TICKET", None)
    module = webview_module
    if module is None:
        try:
            module = _load_webview()
        except ImportError as exc:
            print(f"无法加载 pywebview：{exc}", file=sys.stderr)
            return 3
    try:
        module.create_window(
            "VSE Toolbox", url, width=1280, height=860, js_api=BootBridge(ticket)
        )
        module.start(private_mode=False, storage_path=str(profile) if profile is not None else None)
    except Exception as exc:  # noqa: BLE001 - 任何 GUI 失败都只值一个退出码
        detail = str(exc)
        if url:
            detail = detail.replace(url, "<url>")
        if ticket:
            detail = detail.replace(ticket, "<ticket>")
        print(f"窗口启动失败：{type(exc).__name__}: {detail}", file=sys.stderr)
        return 4
    return 0


def spawn_window(
    url: str,
    profile_dir: Path,
    *,
    assign_job: bool = True,
    env: dict[str, str] | None = None,
) -> ChildProcess:
    """把 pywebview 窗口放进独立子进程（C1）。

    pywebview 要求 ``start()`` 在进程主线程调用，所以窗口不能是启动器里的一个
    线程。``assign_job`` 只在**长驻的**启动器进程里为 True：窗口随它一起结束；
    第二实例进程十几秒后就会退出，把窗口挂到它的 job 上会被
    KILL_ON_JOB_CLOSE 杀掉，所以那条路径必须传 False（见 ``open_window``）。

    ``env`` 只用于注入 ``VSE_WINDOW_BOOT_TICKET``；窗口子进程**绝不**继承
    ``VSE_LAUNCH_SECRET``（契约 §5.3）。
    """
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    profile = str(profile_dir)
    if getattr(sys, "frozen", False):
        command = [sys.executable, "--window", url, "--profile", profile]
    else:
        command = [sys.executable, "-m", "vse_boot", "--window", url, "--profile", profile]
    child_env = dict(os.environ)
    child_env.pop("VSE_LAUNCH_SECRET", None)
    child_env.pop("VSE_WINDOW_BOOT_TICKET", None)
    if env:
        child_env.update({str(key): str(value) for key, value in env.items()})
    child = subprocess.Popen(command, creationflags=flags, env=child_env)
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
    broker: "WindowBroker | None" = None,
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

    ``broker``（契约 §5.4/§5.5）：新契约下由启动器预置一次性授权——pywebview
    走 ``delivery="env"`` 把票据经环境变量注入窗口子进程；Edge/默认浏览器没有
    注入通道，打开**纯 URL** 前先预置 ``delivery="claim"`` 授权。``broker`` 为
    None 时保持旧链路（URL 自带 ``?boot=``，无授权预置）。
    """
    if assign_job is None:
        assign_job = launcher_holds_instance_lock(layout.lock_file)
    available = find_webview or webview_available
    wait_fn = wait or wait_window_exit

    def _edge_fallback() -> None:
        if broker is not None:
            # 浏览器没有注入通道：先预置一次性 claim 授权，再打开纯 URL。
            try:
                broker.arm("open", "claim")
            except Exception:  # noqa: BLE001 - 预置失败只让页面显示「需要启动器授权」
                pass
        _open_edge_or_browser(url, layout)

    fallback_fn = fallback or _edge_fallback
    if not available():
        fallback_fn()
        return
    env: dict[str, str] | None = None
    if broker is not None:
        data = broker.arm("open", "env") or {}
        ticket = data.get("ticket")
        if not isinstance(ticket, str) or not ticket:
            fallback_fn()  # 拿不到票据就不开一个没有会话的窗口
            return
        env = {"VSE_WINDOW_BOOT_TICKET": ticket}
    spawn_fn = spawn or (
        lambda target, profile: spawn_window(target, profile, assign_job=assign_job, env=env)
    )
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
    spawn: Callable[..., ChildProcess] = spawn_app
    probe: Callable[[int], bool] = probe_app
    show: Callable[..., None] = open_window
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
    #: 新契约探测（``grantArm``）；失败一律按旧 app 处理（契约 §8.2）。
    capabilities: Callable[[int], dict[str, Any] | None] = probe_capabilities
    #: 授权代理工厂：测试注入替身，生产用 ``WindowBroker``（真实 HTTP + 启动器密钥）。
    broker_factory: Callable[[int, str], Any] = WindowBroker
    url: str | None = field(default=None, init=False)
    version: str | None = field(default=None, init=False)
    #: 本次 app 子进程的票据/密钥/epoch：绝不打印、绝不进 instance.json。
    boot_token: str = field(default="", init=False, repr=False)
    launch_secret: str = field(default="", init=False, repr=False)
    epoch: str = field(default="", init=False, repr=False)
    contract_available: bool = field(default=False, init=False, repr=False)
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

    # ── 第二实例：请求 owner 重开窗口（契约 §5.6 / K4） ──────────────
    def _show_existing(self) -> int:
        """拿不到实例锁：写 ``window.request`` 请 owner 重新签发授权并开窗。

        **不再**读 ``instance.json["url"]`` 直接开窗——那张票据早已被首窗消费或
        超过 10 秒（D2）。8 秒内 owner 未接手时兜底打开**无票据**的 ``/``，页面
        显示“需要启动器授权”横幅；绝不回退到复用旧票据或旧 URL。
        """
        info = self._read_instance()
        base = _public_base_url(info) if info is not None else None
        if base is None:
            self.log("VSE Toolbox 正在启动，请稍候再打开。")
            return 0
        request = window_request_path(self.layout)
        try:
            _write_json_atomic(
                request,
                {
                    "purpose": "open",
                    "requestedAt": int(time.time() * 1000),
                    "nonce": secrets.token_hex(16),
                },
            )
        except OSError as exc:
            self.log(f"无法请求正在运行的启动器重开窗口：{exc}")
            return 0
        if self._wait_window_request(request):
            return 0  # owner 已接手：它负责签发授权并开窗
        self.log("未能联系到正在运行的启动器，请从开始菜单重新打开 VSE Toolbox。")
        self._show_window(base)
        return 0

    def _show_window(self, url: str, *, broker: Any = None) -> None:
        """按 ``show`` 的能力开窗：支持 ``broker=`` 的走新契约，老式 2 参 callable 保持原样。"""
        if broker is not None and _accepts_broker(self.show):
            self.show(url, self.layout, broker=broker)
        else:
            self.show(url, self.layout)

    def _read_instance(self) -> dict[str, Any] | None:
        try:
            info = json.loads(self.layout.instance_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return info if isinstance(info, dict) else None

    def _wait_window_request(self, request: Path) -> bool:
        """最多等 ``WINDOW_REQUEST_TIMEOUT_SECONDS``：文件被 owner 删除即视为已接手。"""
        deadline = self.clock() + WINDOW_REQUEST_TIMEOUT_SECONDS
        while self.clock() < deadline:
            if not request.exists():
                return True
            self.sleep(WINDOW_REQUEST_POLL_SECONDS)
        return not request.exists()

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
        # 陈旧状态文件：历史 window.request / boot-handoff.json 绝不能被误执行或复用。
        window_request_path(self.layout).unlink(missing_ok=True)
        handoff_path(self.layout).unlink(missing_ok=True)
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
            # C7（DSH-V2-03）：票据与启动器密钥**只**经继承的环境变量交给 app 子进程。
            # 绝不写 os.environ：那会把它们泄漏给启动器随后创建的所有子进程
            # （窗口子进程、Excel worker）。票据/密钥不落盘、不进 argv、不进日志。
            self.boot_token = secrets.token_urlsafe(32)
            self.launch_secret = secrets.token_urlsafe(32)
            self.epoch = secrets.token_hex(8)
            self.contract_available = False
            env_overrides = {
                "VSE_BOOT_TOKEN": self.boot_token,  # 旧 app 兼容路径（配合 ?boot=）
                "VSE_LAUNCH_SECRET": self.launch_secret,
                "VSE_LEGACY_BOOT_QUERY": "0",  # 新启动器显式关闭 ?boot= 兼容读取
            }
            child = self.spawn(app_dir, port, self.layout, env_overrides=env_overrides)
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
        # 健康检查通过之后才探测/签发：票据 TTL 从 app 侧签发时刻起算（契约 §5.3）。
        capabilities = self.capabilities(port)
        self.contract_available = bool(capabilities and capabilities.get("grantArm") is True)
        if self.contract_available:
            self.epoch = str(capabilities.get("epoch") or self.epoch)
        broker = self.broker_factory(port, self.launch_secret) if self.contract_available else None
        self.url, self.version = f"http://127.0.0.1:{port}/", version
        if self.contract_available:
            # 新链路：URL 无查询串；票据/授权只在内存与环境变量里流转。
            url = self.url
            handoff = self._write_handoff(broker)
        else:
            # 旧 app（无 grantArm）：逐字保留旧路径语义——URL 附 ?boot=、instance.json
            # 写 bootToken。这条分支只服务“新启动器 + 旧 app”（契约 §8.1）。
            url = f"{self.url}?boot={self.boot_token}"
            handoff = False
        self._write_instance(child, port, version, url, handoff=handoff)
        if open_window:
            self._show_window(url, broker=broker)
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
                request = window_request_path(self.layout)
                if request.exists():
                    # K4：第二实例请 owner 重新签发授权并开窗；先删请求再开窗。
                    request.unlink(missing_ok=True)
                    self.log("按请求重新打开窗口")
                    try:
                        self._show_window(self.url, broker=broker)
                    except Exception as exc:  # noqa: BLE001 - 重开窗口失败不能拖垮启动器
                        self.log(f"重新打开窗口失败：{type(exc).__name__}")
                self.sleep(_POLL_SECONDS)
        except KeyboardInterrupt:
            self._stop(child)
            return "quit", 0

    def _write_instance(
        self,
        child: ChildProcess,
        port: int,
        version: str,
        url: str,
        *,
        handoff: bool,
    ) -> None:
        """写 ``state/instance.json``：**不含任何票据/密钥**（契约 §5.9）。"""
        info: dict[str, Any] = {
            "schemaVersion": INSTANCE_SCHEMA_VERSION,
            "url": url,
            "port": port,
            "version": version,
            "pid": child.pid,
            "supervisorPid": os.getpid(),
            "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "epoch": self.epoch,
            "securityContract": SECURITY_CONTRACT_VERSION,
        }
        if not self.contract_available:
            # 仅旧 app 分支：旧启动器/旧 app 只认这个字段（契约 §8.1）。
            info["bootToken"] = self.boot_token
        if handoff:
            info["handoff"] = handoff_path(self.layout).name
        _write_json_atomic(self.layout.instance_file, info)

    def _write_handoff(self, broker: Any) -> bool:
        """K6（opt-in）：把刚签发的票据写入 ``state/boot-handoff.json``，ttl+5 秒后自删。

        默认**不创建**（生产零残留）；仅 ``VSE_BOOT_HANDOFF=1`` 时写入。文件权限
        依赖安装根继承的当前用户私有 ACL——**不新增任何 ACL 操作，也不宣称 0600**
        （主控裁决 1）。
        """
        if os.environ.get(HANDOFF_ENV_VAR) != "1":
            return False
        data = broker.arm("open", "env") if broker is not None else None
        ticket = (data or {}).get("ticket")
        if not isinstance(ticket, str) or not ticket:
            self.log("启动器未能在开窗前签发自动化票据，boot-handoff.json 未写入")
            return False
        path = handoff_path(self.layout)
        try:
            _write_json_atomic(
                path,
                {
                    "ticket": ticket,
                    "expiresAt": int(time.time()) + TICKET_TTL_SECONDS,
                    "pid": os.getpid(),
                    "epoch": self.epoch,
                },
            )
        except OSError as exc:
            self.log(f"无法写入 boot-handoff.json：{exc}")
            return False

        def _remove() -> None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

        timer = threading.Timer(HANDOFF_DELETE_DELAY_SECONDS, _remove)
        timer.daemon = True
        timer.start()
        return True

    @staticmethod
    def _stop(child: ChildProcess) -> None:
        if child.poll() is not None:
            return
        child.terminate()
        try:
            child.wait(timeout=10)
        except Exception:
            child.kill()
