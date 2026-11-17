# -*- coding: utf-8 -*-
"""Supervisor boot sequence with fake child processes (no real app is started)."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

import vse_boot.supervisor as supervisor
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
        self.env_overrides: list[dict] = []
        self.capabilities_data: dict | None = None
        self.broker: "FakeBroker | None" = None
        self.shown_brokers: list[object] = []
        self.now = 0.0
        self.current: str | None = None

    def spawn(self, app_dir: Path, port: int, layout: InstallLayout, *, env_overrides=None) -> FakeChild:
        self.current = app_dir.name
        self.spawned.append(app_dir.name)
        self.env_overrides.append(dict(env_overrides or {}))
        child = FakeChild(exit_code=1 if app_dir.name in self.crash else None, lifetime=self.lifetime, final=self.final)
        self.children.append(child)
        return child

    def probe(self, port: int) -> bool:
        return self.healthy.get(self.current or "", False)

    def capabilities(self, port: int) -> dict | None:
        return self.capabilities_data

    def broker_factory(self, port: int, secret: str) -> "FakeBroker":
        self.broker = FakeBroker(secret)
        return self.broker

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        if self.on_poll is not None:
            self.on_poll()

    def show(self, url: str, layout: InstallLayout, *, broker=None) -> None:  # type: ignore[no-untyped-def]
        """记录开窗 URL；带 ``broker`` 时走**真实** ``open_window`` 的授权预置逻辑。

        真实 ``open_window`` 才是「pywebview → 环境变量注入票据 / Edge → 预置 claim
        授权」的执行者（``supervisor.open_window``）。这里只把子进程与 webview 探测
        换成替身，其余（签发顺序、env 构造、降级判定）全部走产品代码。
        """
        self.shown.append(url)
        self.shown_brokers.append(broker)
        if broker is None:
            return
        supervisor.open_window(
            url,
            layout,
            spawn=lambda _target, _profile: FakeChild(),
            find_webview=lambda: True,
            wait=lambda _child, _timeout: None,
            assign_job=False,
            broker=broker,
        )

    def supervisor(self, **kwargs) -> Supervisor:  # type: ignore[no-untyped-def]
        return Supervisor(
            self.layout,
            spawn=self.spawn,
            probe=self.probe,
            show=kwargs.pop("show", self.show),
            pick_port=lambda: 50123,
            port_free=lambda _port: True,
            health_timeout=3.0,
            sleep=self.sleep,
            clock=lambda: self.now,
            log=lambda _msg: None,
            capabilities=self.capabilities,
            broker_factory=self.broker_factory,
            **kwargs,
        )


class FakeBroker:
    """记录授权预置（真实 HTTP 由 web/security.py 的端点测试覆盖）。"""

    def __init__(self, secret: str) -> None:
        self.secret = secret
        self.arms: list[tuple[str, str]] = []

    def arm(self, purpose: str, delivery: str) -> dict | None:
        self.arms.append((purpose, delivery))
        if delivery == "env":
            return {"ticket": "tok_synthetic", "delivery": "env"}
        return {"delivery": "claim"}


@pytest.fixture()
def layout(tmp_path: Path) -> InstallLayout:
    return InstallLayout(tmp_path / "VSE-Toolbox").ensure()


def test_first_install_boots_and_opens_window(layout: InstallLayout) -> None:
    install(layout, "2.0.0")
    harness = Harness(layout, {"2.0.0": True})
    assert harness.supervisor().run() == 0
    assert harness.spawned == ["2.0.0"]
    assert harness.shown and harness.shown[0].startswith("http://127.0.0.1:50123/?boot=")
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

    def spawn_and_migrate(app_dir, port, lay, *, env_overrides=None):  # type: ignore[no-untyped-def]
        if app_dir.name == "2.0.1":
            with sqlite3.connect(layout.database) as conn:
                conn.execute("update t set v = 'half-migrated'")
        return original_spawn(app_dir, port, lay, env_overrides=env_overrides)

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
        # K4：先写 window.request 请 owner 重开；8 秒无人接手才兜底打开**无票据**的 /
        assert harness.shown == ["http://127.0.0.1:50999/"]
        assert harness.now >= 8.0
        request = layout.state_dir / "window.request"
        assert json.loads(request.read_text(encoding="utf-8"))["purpose"] == "open"
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
    assert harness.shown and harness.shown[0].startswith("http://127.0.0.1:50123/?boot=")  # 重启沿用端口，不再弹第二个窗口
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


# ── DSH-V2-03：票据传递、受控重开、handoff 文件（契约 §5.3–§5.9） ─────────


def _supervisor_capture(harness: Harness, supervisor_obj: Supervisor) -> dict:
    """第一次 sleep 时抓取 instance.json / handoff，然后退出。"""
    captured: dict = {}

    def sleep_once(_seconds: float) -> None:
        try:
            captured["info"] = json.loads(harness.layout.instance_file.read_text(encoding="utf-8"))
        except OSError:
            captured["info"] = None
        handoff = harness.layout.state_dir / "boot-handoff.json"
        captured["handoff"] = json.loads(handoff.read_text(encoding="utf-8")) if handoff.is_file() else None
        supervisor_obj.controls.quit.set()

    supervisor_obj.sleep = sleep_once  # type: ignore[method-assign]
    return captured


def test_instance_file_has_new_field_set_and_no_boot_token(layout: InstallLayout) -> None:
    """新链路：instance.json 字段集冻结、url 无查询串、绝不含 bootToken（§5.9）。"""
    install(layout, "2.4.0")
    harness = Harness(layout, {"2.4.0": True})
    harness.capabilities_data = {"grantArm": True, "epoch": "9f2c0d7a4b1e6c33"}
    supervisor_obj = harness.supervisor()
    captured = _supervisor_capture(harness, supervisor_obj)

    assert supervisor_obj.run() == 0
    info = captured["info"]
    assert set(info) == {
        "schemaVersion", "url", "port", "version", "pid", "supervisorPid",
        "startedAt", "epoch", "securityContract",
    }
    assert info["schemaVersion"] == 2
    assert info["securityContract"] == 1
    assert info["epoch"] == "9f2c0d7a4b1e6c33"
    assert info["url"] == "http://127.0.0.1:50123/"
    assert "?" not in info["url"]
    assert info["port"] == 50123 and info["pid"] == 4242
    assert info["version"] == "2.4.0"
    assert info["startedAt"].endswith("Z") and "T" in info["startedAt"]
    assert "bootToken" not in info
    assert "handoff" not in info
    assert harness.shown == ["http://127.0.0.1:50123/"]
    assert captured["handoff"] is None  # 默认不创建


def test_spawn_env_carries_secret_but_launcher_environ_does_not(
    layout: InstallLayout, monkeypatch: pytest.MonkeyPatch
) -> None:
    """票据/启动器密钥只经 env= 下发；启动器自身 os.environ 不含它们（§5.3）。"""
    monkeypatch.delenv("VSE_BOOT_TOKEN", raising=False)
    monkeypatch.delenv("VSE_LAUNCH_SECRET", raising=False)
    install(layout, "2.4.0")
    harness = Harness(layout, {"2.4.0": True})
    harness.capabilities_data = {"grantArm": True, "epoch": "9f2c0d7a4b1e6c33"}
    supervisor_obj = harness.supervisor()
    captured = _supervisor_capture(harness, supervisor_obj)

    assert supervisor_obj.run() == 0
    env = harness.env_overrides[-1]
    assert env["VSE_LAUNCH_SECRET"] and env["VSE_BOOT_TOKEN"]
    assert env["VSE_LEGACY_BOOT_QUERY"] == "0"
    assert os.environ.get("VSE_BOOT_TOKEN") is None
    assert os.environ.get("VSE_LAUNCH_SECRET") is None
    # 密钥交给 broker（window-grant），绝不进入展示 URL / 实例文件 / 日志
    assert harness.broker is not None and harness.broker.secret == env["VSE_LAUNCH_SECRET"]
    assert env["VSE_LAUNCH_SECRET"] not in json.dumps(harness.shown)
    assert env["VSE_LAUNCH_SECRET"] not in json.dumps(captured["info"])
    assert env["VSE_BOOT_TOKEN"] not in json.dumps(captured["info"])


@pytest.mark.parametrize("capabilities", [None, {}, {"grantArm": False}, {"grantArm": "yes"}])
def test_capabilities_failure_falls_back_to_legacy_path(
    layout: InstallLayout, capabilities: dict | None
) -> None:
    """探测失败/无 grantArm → 旧路径（URL 带票 + bootToken），不误用新链路（§8.2）。"""
    install(layout, "2.4.0")
    harness = Harness(layout, {"2.4.0": True})
    harness.capabilities_data = capabilities
    supervisor_obj = harness.supervisor()
    captured = _supervisor_capture(harness, supervisor_obj)

    assert supervisor_obj.run() == 0
    token = harness.env_overrides[-1]["VSE_BOOT_TOKEN"]
    assert harness.shown == [f"http://127.0.0.1:50123/?boot={token}"]
    assert captured["info"]["bootToken"] == token
    assert captured["info"]["url"] == harness.shown[0]
    assert harness.broker is None  # 旧 app 没有 window-grant


def test_ticket_issue_happens_after_health_check(layout: InstallLayout) -> None:
    """注入时钟：健康检查等了 20 秒，授权/票据仍在健康检查之后才签发（§5.3）。"""
    install(layout, "2.4.0")
    # lifetime 必须远大于 20 秒探活所需的 40 次轮询，否则子进程会先「退出」。
    harness = Harness(layout, {}, lifetime=1000)
    armed: dict = {}

    class SlowBroker(FakeBroker):
        def arm(self, purpose: str, delivery: str) -> dict | None:
            armed.setdefault("at", harness.now)
            return super().arm(purpose, delivery)

    supervisor_obj = Supervisor(
        layout,
        spawn=harness.spawn,
        probe=lambda port: harness.now >= 20.0,  # 慢启动：20 秒后才探活成功
        show=harness.show,
        pick_port=lambda: 50123,
        port_free=lambda _port: True,
        health_timeout=30.0,
        sleep=lambda seconds: harness.sleep(seconds),
        clock=lambda: harness.now,
        log=lambda _msg: None,
        capabilities=lambda port: {"grantArm": True, "epoch": "9f2c0d7a4b1e6c33"},
        broker_factory=lambda port, secret: SlowBroker(secret),
    )

    def sleep_until_armed(seconds: float) -> None:
        harness.sleep(seconds)
        if "at" in armed:
            supervisor_obj.controls.quit.set()

    supervisor_obj.sleep = sleep_until_armed  # type: ignore[method-assign]
    assert supervisor_obj.run() == 0
    assert armed["at"] >= 20.0  # 票据签发在健康检查之后（TTL 从签发时刻起算）
    assert harness.shown == ["http://127.0.0.1:50123/"]


def test_owner_consumes_window_request_and_reopens_window(layout: InstallLayout) -> None:
    """K4：owner 轮询发现 window.request → 删除 → 重新签发授权并开窗。"""
    install(layout, "2.4.0")
    harness = Harness(layout, {"2.4.0": True})
    harness.capabilities_data = {"grantArm": True, "epoch": "9f2c0d7a4b1e6c33"}
    request = layout.state_dir / "window.request"
    supervisor_obj = harness.supervisor()
    state = {"written": False}

    def on_poll() -> None:
        if not state["written"]:
            state["written"] = True
            request.write_text(
                json.dumps({"purpose": "open", "requestedAt": 0, "nonce": "0" * 32}),
                encoding="utf-8",
            )

    harness.on_poll = on_poll

    def sleep_and_stop(seconds: float) -> None:
        harness.sleep(seconds)
        if len(harness.shown) >= 2:
            supervisor_obj.controls.quit.set()

    supervisor_obj.sleep = sleep_and_stop  # type: ignore[method-assign]
    assert supervisor_obj.run() == 0
    assert harness.shown == ["http://127.0.0.1:50123/", "http://127.0.0.1:50123/"]
    assert not request.exists()  # 被 owner 消费后删除
    assert harness.broker is not None
    # 两次开窗都由真实 open_window 预置了新的 env 票据（首发 + 重开各一次）
    assert harness.broker.arms == [("open", "env"), ("open", "env")]
    assert harness.shown_brokers == [harness.broker, harness.broker]


def test_second_instance_fallback_never_reuses_old_boot_url(layout: InstallLayout) -> None:
    """8 秒未被 owner 接手 → 直接开无票据的 /，绝不重放旧 URL 里的票据（§5.6）。"""
    held = InstanceLock(layout.lock_file)
    assert held.acquire()
    try:
        layout.instance_file.write_text(
            json.dumps({"url": "http://127.0.0.1:50999/?boot=stale-token", "port": 50999}),
            encoding="utf-8",
        )
        harness = Harness(layout, {})
        assert harness.supervisor().run() == 0
        assert harness.shown == ["http://127.0.0.1:50999/"]
        assert all("stale-token" not in url for url in harness.shown)
        assert all("?" not in url for url in harness.shown)
    finally:
        held.release()


def test_boot_cleans_stale_window_request_and_handoff(
    layout: InstallLayout, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VSE_BOOT_HANDOFF", raising=False)
    install(layout, "2.4.0")
    harness = Harness(layout, {"2.4.0": True})
    harness.capabilities_data = {"grantArm": True, "epoch": "9f2c0d7a4b1e6c33"}
    request = layout.state_dir / "window.request"
    handoff = layout.state_dir / "boot-handoff.json"
    request.write_text("{}", encoding="utf-8")
    handoff.write_text("{}", encoding="utf-8")
    supervisor_obj = harness.supervisor()
    _supervisor_capture(harness, supervisor_obj)

    assert supervisor_obj.run() == 0
    assert not request.exists()
    assert not handoff.exists()
    assert harness.shown == ["http://127.0.0.1:50123/"]  # 陈旧请求没有触发额外开窗


def test_handoff_file_only_when_opted_in(layout: InstallLayout, monkeypatch: pytest.MonkeyPatch) -> None:
    """K6：仅 VSE_BOOT_HANDOFF=1 时创建，含 expiresAt/pid/epoch，且不含启动器密钥。"""
    monkeypatch.setenv("VSE_BOOT_HANDOFF", "1")
    install(layout, "2.4.0")
    harness = Harness(layout, {"2.4.0": True})
    harness.capabilities_data = {"grantArm": True, "epoch": "9f2c0d7a4b1e6c33"}
    supervisor_obj = harness.supervisor()
    captured = _supervisor_capture(harness, supervisor_obj)

    assert supervisor_obj.run() == 0
    payload = captured["handoff"]
    assert payload is not None
    assert payload["ticket"] == "tok_synthetic"
    assert payload["expiresAt"] > 0
    assert payload["pid"] == os.getpid()
    assert payload["epoch"] == "9f2c0d7a4b1e6c33"
    assert captured["info"]["handoff"] == "boot-handoff.json"
    assert harness.env_overrides[-1]["VSE_LAUNCH_SECRET"] not in json.dumps(payload)


def test_security_contract_constants_match_app_module() -> None:
    """启动器不 import app 包，但冻结路径/头名必须与 web/security.py 逐字一致。"""
    from web import security as app_security

    assert supervisor.CAPABILITIES_PATH == app_security.CAPABILITIES_PATH
    assert supervisor.WINDOW_GRANT_PATH == app_security.WINDOW_GRANT_PATH
    assert supervisor.LAUNCHER_SECRET_HEADER == app_security.LAUNCHER_SECRET_HEADER
    assert supervisor.TICKET_TTL_SECONDS == app_security.BOOT_TICKET_TTL_SECONDS
    assert supervisor.SECURITY_CONTRACT_VERSION == app_security.SECURITY_CONTRACT_VERSION
    assert supervisor.INSTANCE_SCHEMA_VERSION == 2
