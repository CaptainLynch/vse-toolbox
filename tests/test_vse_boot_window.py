# -*- coding: utf-8 -*-
"""DSH-V2-47：窗口子进程、三级降级、端口冲突与自启默认关闭（全 mock）。

契约要点：
- C1：pywebview 只在 ``--window`` 子进程的主线程里跑（``run_window``），
  启动器进程不 import 它、不跑 ``webview.start()``；
- C2：``open_window`` 立即返回，pywebview → Edge app → 默认浏览器，
  宽限期内非 0 退出（或 spawn 失败）才降级，由非 daemon 的监视线程判定；
- C3：第二实例只 show、不 spawn；且它开出的窗口不得挂到自己的 job 上
  （KILL_ON_JOB_CLOSE 会在第二实例退出时杀掉刚开的窗口）；
- C4：端口冲突换端口重试，最多 3 次，不记 bootFailed、不放弃试用版本；
- C5：启动流程从不调用 ``autostart.enable``。

本文件不启动任何真实窗口 / Edge / 浏览器 / 子进程，也不读写注册表。
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import vse_boot.__main__ as boot_main
import vse_boot.supervisor as supervisor
from vse_boot import autostart
from vse_boot.layout import InstallLayout
from vse_boot.state import BootState
from vse_boot.supervisor import InstanceLock, Supervisor

WATCH_THREAD_NAME = "vse-window-watch"
URL = "http://127.0.0.1:5000/?boot=secret-token"


# ── 通用工具 ────────────────────────────────────────────────────────


def _layout(tmp_path: Path):  # type: ignore[no-untyped-def]
    """open_window 只用到 ``state_dir`` 和 ``lock_file``；用轻量布局避免建目录。"""
    state = tmp_path / "state"
    return types.SimpleNamespace(state_dir=state, lock_file=state / "instance.lock")


def _watchers() -> list[threading.Thread]:
    return [thread for thread in threading.enumerate() if thread.name == WATCH_THREAD_NAME]


def _join_watchers(timeout: float = 5.0) -> None:
    for thread in _watchers():
        thread.join(timeout)


@pytest.fixture(autouse=True)
def _no_leaked_watcher():  # type: ignore[no-untyped-def]
    """监视线程是非 daemon 的，绝不能留到进程退出。"""
    yield
    _join_watchers(3.0)
    assert _watchers() == [], "vse-window-watch 线程没有在宽限期内结束"


class FakeChild:
    """``exit_code`` set: exits immediately. Otherwise runs ``lifetime`` polls, then exits with ``final``."""

    def __init__(self, *, exit_code: int | None = None, lifetime: int = 4, final: int = 0) -> None:
        self.pid = 4242
        self._exit = exit_code
        self._polls = 0
        self._lifetime = lifetime
        self._final = final
        self.terminated = False

    def poll(self) -> int | None:
        if self._exit is None:
            self._polls += 1
            if self._polls > self._lifetime:
                self._exit = self._final
        return self._exit

    def wait(self, timeout: float | None = None) -> int:
        return 0 if self._exit is None else self._exit

    def terminate(self) -> None:
        self.terminated = True
        self._exit = -15

    def kill(self) -> None:
        self._exit = -9


class FakeWebview:
    """假 pywebview 模块：记录 create_window / start 的调用参数。"""

    def __init__(self, *, create_error: Exception | None = None, start_error: Exception | None = None) -> None:
        self.created: list[tuple[str, str, dict]] = []
        self.started: list[dict] = []
        self.create_error = create_error
        self.start_error = start_error

    def create_window(self, title: str, url: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
        if self.create_error is not None:
            raise self.create_error
        self.created.append((title, url, kwargs))

    def start(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        if self.start_error is not None:
            raise self.start_error
        self.started.append(kwargs)


# ── 1. pywebview 可用：独立子进程 + 立即返回 ────────────────────────


def test_open_window_spawns_window_child_and_returns_immediately(tmp_path: Path) -> None:
    """C1/C2：注入一个阻塞的 wait，open_window 仍然立即返回，且不降级。"""
    layout = _layout(tmp_path)
    spawned: list[tuple[str, Path]] = []
    started = threading.Event()
    release = threading.Event()
    fallback = MagicMock()
    seen_timeouts: list[float] = []

    def spawn(url: str, profile: Path) -> FakeChild:
        spawned.append((url, Path(profile)))
        return FakeChild()

    def blocking_wait(child: FakeChild, timeout: float) -> None:
        seen_timeouts.append(timeout)
        started.set()
        release.wait(min(timeout, 2.0))  # 模拟"窗口一直开着"，但有界
        return None

    began = time.monotonic()
    supervisor.open_window(
        URL, layout, spawn=spawn, find_webview=lambda: True, wait=blocking_wait, fallback=fallback
    )
    elapsed = time.monotonic() - began

    assert elapsed < 1.0, f"open_window 阻塞了 {elapsed:.2f}s"
    assert started.wait(5.0), "监视线程没有启动"
    assert spawned == [(URL, layout.state_dir / "webview-profile")]
    assert seen_timeouts == [supervisor.WINDOW_STARTUP_GRACE_SECONDS]
    assert supervisor.WINDOW_STARTUP_GRACE_SECONDS == 15.0
    assert fallback.call_count == 0  # 宽限期内仍在运行 → 什么也不做

    release.set()
    _join_watchers()
    assert fallback.call_count == 0


def test_window_exit_zero_does_not_fall_back(tmp_path: Path) -> None:
    """用户自己关窗（退出码 0）不算失败，不降级。"""
    fallback = MagicMock()
    supervisor.open_window(
        URL, _layout(tmp_path),
        spawn=lambda url, profile: FakeChild(exit_code=0),
        find_webview=lambda: True,
        wait=lambda child, timeout: 0,
        fallback=fallback,
    )
    _join_watchers()
    assert fallback.call_count == 0


def test_window_nonzero_exit_within_grace_falls_back_once(tmp_path: Path) -> None:
    """C2：宽限期内非 0 退出 → 降级一次。"""
    fallback = MagicMock()
    supervisor.open_window(
        URL, _layout(tmp_path),
        spawn=lambda url, profile: FakeChild(exit_code=4),
        find_webview=lambda: True,
        wait=lambda child, timeout: 4,
        fallback=fallback,
    )
    _join_watchers()
    assert fallback.call_count == 1


def test_window_spawn_oserror_falls_back_without_thread(tmp_path: Path) -> None:
    """C2：spawn_window 抛 OSError → 立即降级，且不留下监视线程。"""

    def spawn(url: str, profile: Path) -> FakeChild:
        raise OSError("cannot start window")

    fallback = MagicMock()
    supervisor.open_window(
        URL, _layout(tmp_path), spawn=spawn, find_webview=lambda: True, fallback=fallback
    )
    assert fallback.call_count == 1
    assert _watchers() == []


def test_open_window_propagates_non_oserror_spawn_failure(tmp_path: Path) -> None:
    """契约只兜 OSError：其他异常照旧上抛，不静默吞掉、也不误触发降级。"""

    def spawn(url: str, profile: Path) -> FakeChild:
        raise RuntimeError("bad command line")

    fallback = MagicMock()
    with pytest.raises(RuntimeError):
        supervisor.open_window(
            URL, _layout(tmp_path), spawn=spawn, find_webview=lambda: True, fallback=fallback
        )
    assert fallback.call_count == 0


def test_watcher_thread_is_not_daemon(tmp_path: Path) -> None:
    """C2：非 daemon——第二实例进程退出前必须还能完成降级判定。"""
    release = threading.Event()
    daemon_flags: list[bool] = []

    def blocking_wait(child: FakeChild, timeout: float) -> None:
        thread = next(t for t in threading.enumerate() if t.name == WATCH_THREAD_NAME)
        daemon_flags.append(thread.daemon)
        release.set()

    supervisor.open_window(
        URL, _layout(tmp_path),
        spawn=lambda url, profile: FakeChild(),
        find_webview=lambda: True,
        wait=blocking_wait,
        fallback=MagicMock(),
    )
    assert release.wait(5.0)
    _join_watchers()
    assert daemon_flags == [False]


# ── 2. pywebview 缺失：直接 Edge app ────────────────────────────────


def test_missing_pywebview_goes_straight_to_edge(monkeypatch, tmp_path: Path) -> None:
    """C2：find_webview 返回 None → 不 spawn 窗口子进程，直接 Edge app 模式。"""
    layout = _layout(tmp_path)
    monkeypatch.setattr(supervisor, "_edge_path", lambda: r"C:\Edge\msedge.exe")
    popen = MagicMock()
    monkeypatch.setattr(supervisor.subprocess, "Popen", popen)
    spawned = MagicMock()

    supervisor.open_window(URL, layout, spawn=spawned, find_webview=lambda: None)

    spawned.assert_not_called()
    popen.assert_called_once()
    command = popen.call_args[0][0]
    assert f"--app={URL}" in command
    assert f"--user-data-dir={layout.state_dir / 'edge-profile'}" in command
    assert "--no-first-run" in command
    assert _watchers() == []


def test_webview_available_uses_find_spec(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """默认探测只看 find_spec，不在启动器里 import pywebview。"""
    monkeypatch.delitem(sys.modules, "webview", raising=False)
    monkeypatch.setattr(supervisor.importlib.util, "find_spec", lambda name: None)
    assert supervisor.webview_available() is False
    monkeypatch.setattr(supervisor.importlib.util, "find_spec", lambda name: object())
    assert supervisor.webview_available() is True


# ── 3. Edge 缺失 / Edge 启动失败 → 默认浏览器 ──────────────────────


def test_edge_missing_uses_default_browser(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(supervisor, "_edge_path", lambda: None)
    opened: list[str] = []
    monkeypatch.setattr(supervisor.webbrowser, "open", lambda url: opened.append(url))

    supervisor._open_edge_or_browser(URL, _layout(tmp_path))
    assert opened == [URL]


def test_edge_popen_oserror_uses_default_browser(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(supervisor, "_edge_path", lambda: r"C:\Edge\msedge.exe")

    def boom(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise OSError("edge is broken")

    monkeypatch.setattr(supervisor.subprocess, "Popen", boom)
    opened: list[str] = []
    monkeypatch.setattr(supervisor.webbrowser, "open", lambda url: opened.append(url))

    supervisor._open_edge_or_browser(URL, _layout(tmp_path))
    assert opened == [URL]


# ── 4. run_window：--window 子进程入口 ─────────────────────────────


def test_run_window_returns_zero_and_passes_storage_path(tmp_path: Path) -> None:
    fake = FakeWebview()
    profile = tmp_path / "webview-profile"

    code = supervisor.run_window(["--window", URL, "--profile", str(profile)], webview_module=fake)

    assert code == 0
    assert fake.created == [("VSE Toolbox", URL, {"width": 1280, "height": 860})]
    assert fake.started == [{"private_mode": False, "storage_path": str(profile)}]


def test_run_window_start_error_returns_four_and_scrubs_url(capsys, tmp_path: Path) -> None:
    """start() 抛异常 → 4；stderr 里不能出现完整 URL（查询串带启动票据）。"""
    fake = FakeWebview(start_error=RuntimeError(f"failed to load {URL}"))

    code = supervisor.run_window(["--window", URL, "--profile", str(tmp_path / "p")], webview_module=fake)

    assert code == 4
    err = capsys.readouterr().err
    assert "RuntimeError" in err
    assert "failed to load" in err
    assert "<url>" in err
    assert "secret-token" not in err


def test_run_window_create_window_error_returns_four(capsys, tmp_path: Path) -> None:
    fake = FakeWebview(create_error=RuntimeError("no display"))

    code = supervisor.run_window(["--window", URL, "--profile", str(tmp_path / "p")], webview_module=fake)

    assert code == 4
    assert "no display" in capsys.readouterr().err


def test_run_window_missing_pywebview_returns_three(monkeypatch, capsys) -> None:
    """``import webview`` 失败 → 3（sys.modules 里的 None 会让 import 抛 ImportError）。"""
    monkeypatch.setitem(sys.modules, "webview", None)

    code = supervisor.run_window(["--window", URL, "--profile", "profile-dir"])

    assert code == 3
    assert "pywebview" in capsys.readouterr().err


def test_main_routes_window_flag_to_run_window(monkeypatch, tmp_path: Path) -> None:
    """``__main__.main(["--window", ...])`` 在 argparse 之前路由到 run_window。"""
    fake = FakeWebview()
    monkeypatch.setitem(sys.modules, "webview", fake)
    profile = tmp_path / "webview-profile"

    assert boot_main.main(["--window", URL, "--profile", str(profile)]) == 0
    assert fake.created == [("VSE Toolbox", URL, {"width": 1280, "height": 860})]
    assert fake.started == [{"private_mode": False, "storage_path": str(profile)}]


def test_run_window_without_url_forwards_none(tmp_path: Path) -> None:
    """缺 URL 也不崩：参数原样交给 create_window（真实 pywebview 会抛 → 4）。"""
    fake = FakeWebview()

    assert supervisor.run_window(["--profile", str(tmp_path / "p")], webview_module=fake) == 0
    assert fake.created == [("VSE Toolbox", None, {"width": 1280, "height": 860})]


# ── 5. spawn_window 命令行 ─────────────────────────────────────────


def _capture_popen(monkeypatch) -> dict:  # type: ignore[no-untyped-def]
    recorded: dict = {}

    def fake_popen(command, **kwargs):  # type: ignore[no-untyped-def]
        recorded["command"] = command
        recorded["kwargs"] = kwargs
        return FakeChild()

    monkeypatch.setattr(supervisor.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(supervisor._JOB, "assign", lambda child: recorded.__setitem__("assigned", child))
    return recorded


def test_spawn_window_command_line_not_frozen(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    recorded = _capture_popen(monkeypatch)
    profile = tmp_path / "webview-profile"

    child = supervisor.spawn_window(URL, profile)

    assert recorded["command"] == [
        sys.executable, "-m", "vse_boot", "--window", URL, "--profile", str(profile),
    ]
    assert recorded["kwargs"]["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert recorded["assigned"] is child  # 随启动器退出一起结束


def test_spawn_window_command_line_frozen(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    recorded = _capture_popen(monkeypatch)
    profile = tmp_path / "webview-profile"

    supervisor.spawn_window(URL, profile)

    assert recorded["command"] == [sys.executable, "--window", URL, "--profile", str(profile)]


def test_spawn_window_skips_job_when_disabled(monkeypatch, tmp_path: Path) -> None:
    """``assign_job=False`` 时不调 ``_JOB.assign``（窗口必须活过第二实例进程）。"""
    monkeypatch.delattr(sys, "frozen", raising=False)
    recorded = _capture_popen(monkeypatch)

    child = supervisor.spawn_window(URL, tmp_path / "webview-profile", assign_job=False)

    assert isinstance(child, FakeChild)
    assert "assigned" not in recorded
    assert recorded["command"][:3] == [sys.executable, "-m", "vse_boot"]


# ── 5b. job 归属：窗口必须活过第二实例进程（评审阻断项）─────────────


def test_owning_launcher_window_is_tied_to_its_job(monkeypatch, layout: InstallLayout) -> None:
    """C1：持有实例锁的长驻启动器仍把窗口收进 job，启动器退出窗口一起关。"""
    install(layout, "2.0.0")
    recorded = _capture_popen(monkeypatch)
    monkeypatch.setattr(supervisor, "webview_available", lambda: True)
    monkeypatch.setattr(supervisor, "wait_window_exit", lambda child, timeout: None)
    harness = Harness(layout, {"2.0.0": True})

    assert harness.supervisor(show=supervisor.open_window).run() == 0

    assert recorded["assigned"] is not None
    assert "--window" in recorded["command"]
    _join_watchers()


def test_second_instance_window_is_not_tied_to_its_own_job(monkeypatch, layout: InstallLayout) -> None:
    """C3：第二实例拿不到锁，它开出的窗口不得挂到自己的 job 上，否则 15s 后被杀。"""
    held = InstanceLock(layout.lock_file)
    assert held.acquire()
    try:
        layout.instance_file.write_text(json.dumps({"url": "http://127.0.0.1:50999/"}), encoding="utf-8")
        recorded = _capture_popen(monkeypatch)
        monkeypatch.setattr(supervisor, "webview_available", lambda: True)
        monkeypatch.setattr(supervisor, "wait_window_exit", lambda child, timeout: None)
        harness = Harness(layout, {})

        assert harness.supervisor(show=supervisor.open_window).run() == 0

        assert harness.spawned == []  # 第二实例不起 app
        assert "--window" in recorded["command"]
        assert recorded["command"][-1].endswith("webview-profile")
        assert "assigned" not in recorded  # 没有 _JOB.assign
        _join_watchers()
    finally:
        held.release()


# ── 6. Supervisor 驱动：端口冲突零干预 ─────────────────────────────


def install(layout: InstallLayout, version: str) -> None:
    entry = layout.staging_dir / f"app-{version}"
    (entry / "files").mkdir(parents=True)
    (entry / "files" / "webui.py").write_text("#", encoding="utf-8")
    meta = {"kind": "app", "version": version, "notes": "", "migrations": []}
    (entry / "staged.json").write_text(json.dumps(meta), encoding="utf-8")


class Harness:
    """记录 spawn/show/端口选择；``healthy`` 决定每个版本是否探活成功。"""

    def __init__(self, layout: InstallLayout, healthy: dict[str, bool], *, crash_ports=frozenset(),
                 final: int = 0, lifetime: int = 4) -> None:
        self.layout = layout
        self.healthy = healthy
        self.crash_ports = set(crash_ports)
        self.final = final
        self.lifetime = lifetime
        self.spawned: list[tuple[str, int]] = []
        self.children: list[FakeChild] = []
        self.shown: list[str] = []
        self.logs: list[str] = []
        self.ports: list[int] = []
        self.port_free = lambda _port: True  # type: ignore[assignment]
        self._port_queue: list[int] = []
        self.now = 0.0
        self.current: str | None = None

    def pick_port(self) -> int:
        port = self._port_queue.pop(0) if self._port_queue else 50123
        self.ports.append(port)
        return port

    def spawn(self, app_dir: Path, port: int, layout: InstallLayout) -> FakeChild:
        self.current = app_dir.name
        self.spawned.append((app_dir.name, port))
        child = FakeChild(exit_code=1 if port in self.crash_ports else None,
                          lifetime=self.lifetime, final=self.final)
        self.children.append(child)
        return child

    def probe(self, port: int) -> bool:
        return self.healthy.get(self.current or "", False)

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def supervisor(self, **kwargs) -> Supervisor:  # type: ignore[no-untyped-def]
        options = dict(
            spawn=self.spawn,
            probe=self.probe,
            show=lambda url, _layout: self.shown.append(url),
            pick_port=self.pick_port,
            port_free=self.port_free,
            health_timeout=3.0,
            sleep=self.sleep,
            clock=lambda: self.now,
            log=self.logs.append,
        )
        options.update(kwargs)
        return Supervisor(self.layout, **options)


@pytest.fixture()
def layout(tmp_path: Path) -> InstallLayout:
    return InstallLayout(tmp_path / "VSE-Toolbox").ensure()


_FAILURE_EVENTS = {"bootFailed", "rolledBack", "databaseRestored"}


def _failure_events(layout: InstallLayout) -> list[str]:
    """只挑失败类事件：正常安装也会写 activated/installed。"""
    return [event["kind"] for event in BootState(layout).events if event["kind"] in _FAILURE_EVENTS]


def test_port_taken_before_spawn_picks_new_port_without_spawning(layout: InstallLayout) -> None:
    """C4：spawn 前端口被占 → 不 spawn 旧端口，换端口后正常启动。"""
    install(layout, "2.0.0")
    harness = Harness(layout, {"2.0.0": True})
    harness._port_queue = [50100, 50101]
    harness.port_free = lambda port: port != 50100

    assert harness.supervisor().run() == 0

    assert harness.spawned == [("2.0.0", 50101)]  # 50100 上从未 spawn
    assert harness.ports[:2] == [50100, 50101]
    assert harness.shown and "127.0.0.1:50101" in harness.shown[0]  # 新 URL 重新开窗
    assert _failure_events(layout) == []


def test_child_exit_with_port_taken_retries_new_port_without_boot_failed(layout: InstallLayout) -> None:
    """C4：子进程因端口被占立即退出 → 换端口重试，不记 bootFailed。"""
    install(layout, "2.0.0")
    harness = Harness(layout, {"2.0.0": True}, crash_ports={50100})
    harness._port_queue = [50100, 50101]
    checks = {"count": 0}

    def port_free(port: int) -> bool:
        if port != 50100:
            return True
        checks["count"] += 1
        return checks["count"] == 1  # 第一次空闲，子进程退出时已被别人占住

    harness.port_free = port_free

    assert harness.supervisor().run() == 0

    assert harness.spawned == [("2.0.0", 50100), ("2.0.0", 50101)]
    assert _failure_events(layout) == []  # 没有 bootFailed
    assert any("端口" in line for line in harness.logs)


def test_port_conflict_gives_up_after_three_retries(layout: InstallLayout) -> None:
    """C4：连续冲突超过 _MAX_PORT_RETRIES 次 → 返回 3 并给出中文说明。"""
    install(layout, "2.0.0")
    harness = Harness(layout, {"2.0.0": True})
    harness._port_queue = [50100, 50101, 50102, 50103, 50104]
    harness.port_free = lambda _port: False

    assert supervisor._MAX_PORT_RETRIES == 3
    assert harness.supervisor().run() == 3

    assert harness.spawned == []  # 端口全被占，一次都没有启动子进程
    assert _failure_events(layout) == []
    assert any("端口" in line and "重试" in line for line in harness.logs)


# ── 7. 第二实例：只 show、不 spawn ─────────────────────────────────


def test_second_instance_shows_once_and_spawns_nothing(layout: InstallLayout) -> None:
    """C3：拿不到锁时只唤起已有窗口，不起第二份 app。"""
    held = InstanceLock(layout.lock_file)
    assert held.acquire()
    try:
        layout.instance_file.write_text(json.dumps({"url": "http://127.0.0.1:50999/"}), encoding="utf-8")
        harness = Harness(layout, {})
        shown: list[str] = []

        assert harness.supervisor(show=lambda url, _layout: shown.append(url)).run() == 0

        assert harness.spawned == []
        assert len(shown) == 1
    finally:
        held.release()


# ── 8. 自启默认关闭（C5）───────────────────────────────────────────


class _ForbiddenWinreg:
    """任何注册表访问都算违约。"""

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        def call(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError(f"启动流程不得访问注册表（winreg.{name}）")

        return call


def test_launcher_run_never_enables_autostart(monkeypatch, layout: InstallLayout) -> None:
    """C5：一次完整的 Supervisor.run() 不调用 autostart.enable，也不碰 HKCU。"""
    install(layout, "2.0.0")
    calls: list[str] = []

    def forbidden_enable(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append("enable")
        raise AssertionError("启动流程不得开启开机自启")

    def forbidden_disable(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append("disable")
        raise AssertionError("启动流程不得改动开机自启")

    monkeypatch.setattr(autostart, "enable", forbidden_enable)
    monkeypatch.setattr(autostart, "disable", forbidden_disable)
    monkeypatch.setattr(autostart, "winreg", _ForbiddenWinreg())

    harness = Harness(layout, {"2.0.0": True})
    assert harness.supervisor().run() == 0

    assert calls == []
    assert harness.spawned == [("2.0.0", 50123)]


def test_launcher_sources_do_not_reference_autostart() -> None:
    """C5：启动器运行路径（supervisor / __main__）根本不引用 autostart。"""
    for module in (supervisor, boot_main):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "autostart" not in source, f"{module.__name__} 引用了 autostart"
