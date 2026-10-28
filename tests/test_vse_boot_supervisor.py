# -*- coding: utf-8 -*-
"""Supervisor boot sequence with fake child processes (no real app is started)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from vse_boot.layout import InstallLayout
from vse_boot.state import BootState
from vse_boot.supervisor import InstanceLock, Supervisor


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


def install(layout: InstallLayout, version: str, *, migrations: list[str] | None = None) -> None:
    entry = layout.staging_dir / f"app-{version}"
    (entry / "files").mkdir(parents=True)
    (entry / "files" / "webui.py").write_text("#", encoding="utf-8")
    meta = {"kind": "app", "version": version, "notes": "", "migrations": migrations or []}
    (entry / "staged.json").write_text(json.dumps(meta), encoding="utf-8")


class Harness:
    """Records spawns; ``healthy`` decides per version whether the probe ever succeeds."""

    def __init__(self, layout: InstallLayout, healthy: dict[str, bool], crash: set[str] = frozenset(), *, final: int = 0, lifetime: int = 4) -> None:
        self.final = final
        self.lifetime = lifetime
        self.on_poll = None
        self.layout = layout
        self.healthy = healthy
        self.crash = crash
        self.spawned: list[str] = []
        self.children: list[FakeChild] = []
        self.shown: list[str] = []
        self.now = 0.0
        self.current: str | None = None

    def spawn(self, app_dir: Path, port: int, layout: InstallLayout) -> FakeChild:
        self.current = app_dir.name
        self.spawned.append(app_dir.name)
        child = FakeChild(exit_code=1 if app_dir.name in self.crash else None, lifetime=self.lifetime, final=self.final)
        self.children.append(child)
        return child

    def probe(self, port: int) -> bool:
        return self.healthy.get(self.current or "", False)

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        if self.on_poll is not None:
            self.on_poll()

    def supervisor(self, **kwargs) -> Supervisor:  # type: ignore[no-untyped-def]
        return Supervisor(
            self.layout,
            spawn=self.spawn,
            probe=self.probe,
            show=lambda url, _layout: self.shown.append(url),
            pick_port=lambda: 50123,
            port_free=lambda _port: True,
            health_timeout=3.0,
            sleep=self.sleep,
            clock=lambda: self.now,
            log=lambda _msg: None,
            **kwargs,
        )


@pytest.fixture()
def layout(tmp_path: Path) -> InstallLayout:
    return InstallLayout(tmp_path / "VSE-Toolbox").ensure()


def test_first_install_boots_and_opens_window(layout: InstallLayout) -> None:
    install(layout, "2.0.0")
    harness = Harness(layout, {"2.0.0": True})
    assert harness.supervisor().run() == 0
    assert harness.spawned == ["2.0.0"]
    assert harness.shown == ["http://127.0.0.1:50123/"]
    assert not layout.instance_file.exists()  # 退出时清理


def test_healthy_trial_is_committed(layout: InstallLayout) -> None:
    install(layout, "2.0.0")
    BootState(layout).install_staged()
    install(layout, "2.0.1")
    harness = Harness(layout, {"2.0.0": True, "2.0.1": True})
    assert harness.supervisor().run() == 0
    state = BootState(layout)
    assert (state.app["current"], state.app["previous"]) == ("2.0.1", "2.0.0")


@pytest.mark.parametrize("failure", ["never_healthy", "crashes"])
def test_failing_trial_rolls_back_and_boots_previous(layout: InstallLayout, failure: str) -> None:
    install(layout, "2.0.0")
    BootState(layout).install_staged()
    install(layout, "2.0.1")
    harness = Harness(layout, {"2.0.0": True, "2.0.1": False}, crash={"2.0.1"} if failure == "crashes" else set())
    assert harness.supervisor().run() == 0
    assert harness.spawned == ["2.0.1", "2.0.0"]
    assert harness.children[0].poll() is not None  # 试用子进程已结束（被终止或自行退出）
    state = BootState(layout)
    assert (state.app["current"], state.app["trial"]) == ("2.0.0", None)
    assert state.events[0]["kind"] == "rolledBack"
    assert not layout.app_dir("2.0.1").exists()


def test_failed_trial_with_migrations_restores_database(layout: InstallLayout) -> None:
    with sqlite3.connect(layout.database) as conn:
        conn.execute("create table t (v text)")
        conn.execute("insert into t values ('before')")
    install(layout, "2.0.0")
    BootState(layout).install_staged()
    install(layout, "2.0.1", migrations=["0007_x"])

    harness = Harness(layout, {"2.0.0": True, "2.0.1": False})
    original_spawn = harness.spawn

    def spawn_and_migrate(app_dir, port, lay):  # type: ignore[no-untyped-def]
        if app_dir.name == "2.0.1":
            with sqlite3.connect(layout.database) as conn:
                conn.execute("update t set v = 'half-migrated'")
        return original_spawn(app_dir, port, lay)

    harness.spawn = spawn_and_migrate  # type: ignore[method-assign]
    assert harness.supervisor().run() == 0
    with sqlite3.connect(layout.database) as conn:
        assert conn.execute("select v from t").fetchone()[0] == "before"
    assert len(list(layout.snapshots_dir.glob("*.db"))) == 1


def test_broken_current_version_reports_failure(layout: InstallLayout) -> None:
    install(layout, "2.0.0")
    harness = Harness(layout, {"2.0.0": False})
    assert harness.supervisor().run() == 3
    assert BootState(layout).events[0]["kind"] == "bootFailed"


def test_second_instance_shows_existing_window(layout: InstallLayout) -> None:
    held = InstanceLock(layout.lock_file)
    assert held.acquire()
    try:
        layout.instance_file.write_text(json.dumps({"url": "http://127.0.0.1:50999/"}), encoding="utf-8")
        harness = Harness(layout, {})
        assert harness.supervisor().run() == 0
        assert harness.spawned == []
        assert harness.shown == ["http://127.0.0.1:50999/"]
    finally:
        held.release()
    assert InstanceLock(layout.lock_file).acquire()


def test_frozen_launcher_uses_localappdata_unless_portable(monkeypatch, tmp_path: Path) -> None:
    import vse_boot.__main__ as boot_main

    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    monkeypatch.delenv("VSE_INSTALL_ROOT", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setattr(boot_main.sys, "frozen", True, raising=False)
    monkeypatch.setattr(boot_main.sys, "executable", str(downloads / "VSE-Toolbox(3).exe"))
    assert boot_main.default_root() == tmp_path / "Local" / "VSE-Toolbox"
    (downloads / "portable.flag").write_text("", encoding="utf-8")
    assert boot_main.default_root() == downloads.resolve()


def test_restart_request_installs_staged_version_and_keeps_port(layout: InstallLayout) -> None:
    install(layout, "2.0.0")
    harness = Harness(layout, {"2.0.0": True, "2.0.1": True}, lifetime=1000)
    supervisor = harness.supervisor()
    state = {"requested": False}

    def during_serve() -> None:
        if not state["requested"] and harness.spawned == ["2.0.0"]:
            # 用户在设置页点了「安装并重启」
            install(layout, "2.0.1")
            layout.restart_request.write_text("restart", encoding="utf-8")
            state["requested"] = True
        elif harness.spawned == ["2.0.0", "2.0.1"]:
            layout.quit_request.write_text("quit", encoding="utf-8")

    harness.on_poll = during_serve
    assert supervisor.run() == 0
    assert harness.spawned == ["2.0.0", "2.0.1"]
    assert harness.shown == ["http://127.0.0.1:50123/"]  # 重启沿用端口，不再弹第二个窗口
    assert BootState(layout).app["current"] == "2.0.1"
    assert not layout.restart_request.exists() and not layout.quit_request.exists()


def test_crashing_app_is_restarted_a_limited_number_of_times(layout: InstallLayout) -> None:
    install(layout, "2.0.0")
    harness = Harness(layout, {"2.0.0": True}, final=7)
    assert harness.supervisor().run() == 7
    assert harness.spawned == ["2.0.0"] * 3  # 1 次启动 + 2 次自动重启


def test_tray_is_started_and_stopped_and_quit_control_stops_app(layout: InstallLayout) -> None:
    install(layout, "2.0.0")
    harness = Harness(layout, {"2.0.0": True}, lifetime=1000)
    events: list[str] = []

    class FakeTray:
        def __init__(self, supervisor: Supervisor) -> None:
            events.append("start")

        def notify(self, text: str) -> None:
            events.append("notify")

        def stop(self) -> None:
            events.append("stop")

    supervisor = harness.supervisor(tray=FakeTray)
    harness.on_poll = lambda: supervisor.controls.quit.set()
    assert supervisor.run() == 0
    assert events[0] == "start" and events[-1] == "stop"
    assert harness.children[0].terminated


@pytest.mark.skipif(__import__("os").name != "nt", reason="HKCU association is Windows-only")
def test_file_association_is_written_once_under_hkcu(tmp_path: Path) -> None:
    import winreg

    from vse_boot import association

    base = r"Software\VSE-Toolbox-Test-Classes"
    exe = tmp_path / "VSE-Toolbox.exe"
    try:
        assert association.register(exe, classes_key=base) is True
        assert association.register(exe, classes_key=base) is False  # 已指向同一个 exe，不重复写
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{base}\.vsepkg") as key:
            assert winreg.QueryValue(key, None) == association.PROG_ID
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{base}\{association.PROG_ID}\shell\open\command") as key:
            assert winreg.QueryValue(key, None) == f'"{exe}" open "%1"'
    finally:
        for sub in (rf"{association.PROG_ID}\shell\open\command", rf"{association.PROG_ID}\shell\open",
                    rf"{association.PROG_ID}\shell", rf"{association.PROG_ID}\DefaultIcon", association.PROG_ID, ".vsepkg", ""):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"{base}\{sub}".rstrip("\\"))
            except OSError:
                pass
