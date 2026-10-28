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
    def __init__(self, *, exit_code: int | None = None) -> None:
        self.pid = 4242
        self._exit = exit_code
        self.terminated = False

    def poll(self) -> int | None:
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

    def __init__(self, layout: InstallLayout, healthy: dict[str, bool], crash: set[str] = frozenset()) -> None:
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
        child = FakeChild(exit_code=1 if app_dir.name in self.crash else None)
        self.children.append(child)
        return child

    def probe(self, port: int) -> bool:
        return self.healthy.get(self.current or "", False)

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def supervisor(self, **kwargs) -> Supervisor:  # type: ignore[no-untyped-def]
        return Supervisor(
            self.layout,
            spawn=self.spawn,
            probe=self.probe,
            show=lambda url, _layout: self.shown.append(url),
            pick_port=lambda: 50123,
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
    assert harness.children[0].terminated or harness.children[0].poll() == 1
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
