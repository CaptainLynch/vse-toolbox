# -*- coding: utf-8 -*-
"""启动票据传递端到端验证（DSH-V2-03，契约 §5.3–§5.9、§5.13、§8.1）。

与另外两份测试的分工：

* ``tests/test_local_security.py``：``web/security.py`` 的判定分支（进程内 test client）；
* ``tests/test_local_security_integration.py``：app 侧 8 个真实 HTTP 场景；
* **本文件**：**启动器 → app 子进程 → 窗口子进程 → 页面**这条传递链本身——用真实
  ``Supervisor`` + 真实 HTTP app（``make_server`` 线程）+ 真实 ``WindowBroker``
  （启动器密钥 + ``POST /api/security/window-grant``），只把「子进程」换成进程内替身。

因此这里断言的是**跨进程边界的事实**，而不是某个 helper 的返回值：

1. 票据只走 ``env=``（``VSE_WINDOW_BOOT_TICKET``）→ 窗口子进程 → 页面；
   绝不进入 URL 查询串、``instance.json``、启动器日志、状态文件或诊断记录；
   启动器密钥 ``VSE_LAUNCH_SECRET`` 绝不进入窗口子进程环境。
2. 签发发生在**健康检查之后**：慢启动（注入时钟推进 20 秒）签发的票据仍可交换；
   而 spawn 时刻注册的旧 ``VSE_BOOT_TOKEN`` 在同一时刻已过期——这正是本契约要修的时序。
3. 重复打开（``state/window.request`` → owner 重新签发）总能拿到**新**票据，
   旧票据重放一律 401。
4. app 重启（新 epoch / 新密钥）后旧会话与旧票据全部失效，新票据可建立会话。

时间推进用注入时钟替换 ``web.security.time``（app 侧票据/会话存储唯一时间源），
不 sleep，也不改产品代码。
"""

from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path
from typing import Any, Iterator

import pytest
from werkzeug.serving import make_server

import vse_boot.supervisor as supervisor
import web.app as web_app
import web.security as web_security
from core import diagnostic_recording as dr
from vse_boot.layout import InstallLayout

APP_VERSION = "2.4.0"
#: 需要会话 + 同源 Origin 才能到达视图的写路由（空载荷 → 视图层 422 业务校验）。
WRITE_PATH = "/api/project-status/section-rollup"


# ── app 侧注入时钟（票据/会话存储的唯一时间源） ─────────────────────────────


class AppClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def time(self) -> float:
        return 1_735_689_600.0 + self.now  # 2025-01-01T00:00:00Z（合成时间轴）

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ── 真实 HTTP 客户端（Cookie/Origin 全部显式给出） ──────────────────────────


def _http(
    port: int,
    method: str,
    path: str,
    *,
    json_body: Any = None,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], list[str], bytes]:
    merged = {"Accept": "application/json", "Connection": "close"}
    merged.update(headers or {})
    body: bytes | None = None
    if json_body is not None:
        body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        merged["Content-Type"] = "application/json"
    if cookies:
        merged["Cookie"] = "; ".join(f"{name}={value}" for name, value in cookies.items())
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    try:
        connection.request(method, path, body=body, headers=merged)
        raw = connection.getresponse()
        payload = raw.read()
        return (
            raw.status,
            {name.lower(): value for name, value in raw.getheaders()},
            list(raw.headers.get_all("Set-Cookie") or []),
            payload,
        )
    finally:
        connection.close()


def _set_cookie_value(set_cookies: list[str], name: str) -> str | None:
    for header in set_cookies:
        if header.partition("=")[0].strip() == name:
            return header.partition("=")[2].split(";", 1)[0].strip()
    return None


def _exchange(port: int, ticket: str, *, cookie: str | None = None):
    """页面拿注入票据换会话（真实 HTTP）。"""
    origin = f"http://127.0.0.1:{port}"
    cookies = {web_security.SESSION_COOKIE_NAME: cookie} if cookie else None
    status, _headers, set_cookies, body = _http(
        port,
        "POST",
        web_security.BOOT_EXCHANGE_PATH,
        json_body={"token": ticket},
        headers={"Origin": origin},
        cookies=cookies,
    )
    return status, set_cookies, body


def _error_type(body: bytes) -> str | None:
    try:
        return json.loads(body.decode("utf-8"))["error"]["type"]
    except (KeyError, TypeError, ValueError):
        return None


def _write(port: int, *, cookie: str | None, origin: str | None = "auto"):
    headers = {}
    if origin == "auto":
        headers["Origin"] = f"http://127.0.0.1:{port}"
    elif origin is not None:
        headers["Origin"] = origin
    cookies = {web_security.SESSION_COOKIE_NAME: cookie} if cookie else None
    return _http(port, "PUT", WRITE_PATH, json_body={}, headers=headers, cookies=cookies)


# ── 子进程替身 ─────────────────────────────────────────────────────────────


class FakeChild:
    """永不自行退出的 app 子进程替身（真实 app 跑在本进程的服务线程里）。"""

    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid
        self.terminated = False

    def poll(self) -> int | None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.terminated = True


# ── 传递链夹具：真实 Supervisor + 真实 app 服务 + 真实 WindowBroker ─────────


class TransportHarness:
    """把 ``Supervisor`` 的「启动子进程」换成「起一个真实 HTTP app 服务」。

    app 的启动器密钥来自 ``spawn`` 收到的 ``env_overrides``——与真实子进程完全一致：
    密钥只经环境变量进入 app 进程，启动器自己不留副本（``supervisor.py`` 也不写
    ``os.environ``）。
    """

    def __init__(self, layout: InstallLayout, *, app_clock: AppClock | None = None) -> None:
        self.layout = layout
        self.port = supervisor.free_port()
        self.app_clock = app_clock
        self.apps: list[tuple[Any, Any, threading.Thread]] = []
        self.env_overrides: list[dict[str, str]] = []
        self.logs: list[str] = []
        self.shown: list[str] = []
        self.brokers: list[Any] = []
        self.health_probe_failures = 0
        self.now = 0.0
        self.instance_snapshots: list[dict[str, Any]] = []

    # ── 子进程 / 服务 ────────────────────────────────────────────────
    def spawn(self, app_dir: Path, port: int, layout: InstallLayout, *, env_overrides=None):
        env = dict(env_overrides or {})
        self.env_overrides.append(env)
        self.start_app(port, env)
        return FakeChild()

    def start_app(self, port: int, env: dict[str, str]) -> Any:
        # 与 webui.py 的入口一致：票据/密钥/兼容开关全部来自继承的环境变量。
        app = web_app.create_app(
            boot_token=env.get("VSE_BOOT_TOKEN"),
            launcher_secret=env.get("VSE_LAUNCH_SECRET"),
            accept_legacy_boot_query=env.get("VSE_LEGACY_BOOT_QUERY", "1") != "0",
        )
        app.config.update(TESTING=False)
        server = make_server("127.0.0.1", port, app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, name="transport-app", daemon=True)
        thread.start()
        self.apps.append((app, server, thread))
        return app

    def stop_apps(self) -> None:
        for _app, server, thread in reversed(self.apps):
            server.shutdown()
            thread.join(timeout=5)
        self.apps.clear()

    # ── Supervisor 注入点 ────────────────────────────────────────────
    def probe(self, port: int) -> bool:
        if self.health_probe_failures > 0:
            self.health_probe_failures -= 1
            return False
        return supervisor.probe_app(port)

    def capabilities(self, port: int):
        return supervisor.probe_capabilities(port)

    def broker_factory(self, port: int, secret: str):
        broker = supervisor.WindowBroker(port, secret)
        self.brokers.append(broker)
        return broker

    def show(self, url: str, layout: InstallLayout, *, broker=None) -> None:
        self.shown.append(url)
        # 真实 open_window：pywebview 分支由它调用 broker.arm("open", "env") 并构造
        # 只含 VSE_WINDOW_BOOT_TICKET 的窗口环境（spawn_window 已被夹具替换为记录器）。
        supervisor.open_window(
            url,
            layout,
            find_webview=lambda: True,
            wait=lambda _child, _timeout: None,
            assign_job=False,
            broker=broker,
        )

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def supervisor(self) -> supervisor.Supervisor:
        return supervisor.Supervisor(
            self.layout,
            spawn=self.spawn,
            probe=self.probe,
            show=self.show,
            pick_port=lambda: self.port,
            port_free=lambda _port: True,
            sleep=self.sleep,
            clock=lambda: self.now,
            log=self.logs.append,
            capabilities=self.capabilities,
            broker_factory=self.broker_factory,
        )

    # ── 驱动一轮启动 ────────────────────────────────────────────────
    def run(self, *, stop_when, on_sleep=None, max_steps: int = 500) -> int:
        supervisor_obj = self.supervisor()
        steps = {"count": 0}

        def sleep_hook(seconds: float) -> None:
            self.sleep(seconds)
            steps["count"] += 1
            self.instance_snapshots.append(self.read_instance())
            if on_sleep is not None:
                on_sleep()
            if steps["count"] >= max_steps or stop_when():
                supervisor_obj.controls.quit.set()

        supervisor_obj.sleep = sleep_hook  # type: ignore[method-assign]
        return supervisor_obj.run()

    def read_instance(self) -> dict[str, Any] | None:
        try:
            info = json.loads(self.layout.instance_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return info if isinstance(info, dict) else None


def install(layout: InstallLayout, version: str) -> None:
    entry = layout.staging_dir / f"app-{version}"
    (entry / "files").mkdir(parents=True)
    (entry / "files" / "webui.py").write_text("#", encoding="utf-8")
    meta = {"kind": "app", "version": version, "notes": "", "migrations": []}
    (entry / "staged.json").write_text(json.dumps(meta), encoding="utf-8")


@pytest.fixture()
def layout(tmp_path: Path) -> InstallLayout:
    return InstallLayout(tmp_path / "VSE-Toolbox").ensure()


@pytest.fixture()
def app_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """app 的数据库落到临时目录（绝不碰开发/生产数据库）。"""
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "transport.db"))
    monkeypatch.delenv("VSE_BOOT_TOKEN", raising=False)
    monkeypatch.delenv("VSE_BOOT_HANDOFF", raising=False)


@pytest.fixture()
def app_clock(monkeypatch: pytest.MonkeyPatch) -> AppClock:
    fake = AppClock()
    monkeypatch.setattr(web_security, "time", fake)
    return fake


@pytest.fixture()
def window_spawns(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """替换 ``spawn_window``：记录窗口子进程真正会继承到的环境，不真起进程。"""
    calls: list[dict[str, Any]] = []

    def fake_spawn_window(url, profile_dir, *, assign_job=True, env=None):  # type: ignore[no-untyped-def]
        calls.append(
            {
                "url": url,
                "profile": profile_dir,
                "assign_job": assign_job,
                "env": dict(env or {}),
            }
        )
        return FakeChild(pid=5252)

    monkeypatch.setattr(supervisor, "spawn_window", fake_spawn_window)
    return calls


@pytest.fixture()
def harness(layout: InstallLayout, app_db, window_spawns) -> Iterator[TransportHarness]:
    transport = TransportHarness(layout)
    install(layout, APP_VERSION)
    try:
        yield transport
    finally:
        transport.stop_apps()


# ── 1. 票据/密钥的载体：env 注入、URL 无查询串、instance.json 无秘密 ─────────


def test_transport_chain_keeps_ticket_out_of_url_and_instance_file(
    harness: TransportHarness, window_spawns: list[dict[str, Any]]
) -> None:
    code = harness.run(stop_when=lambda: bool(window_spawns))
    assert code == 0

    # ① 窗口 URL 无查询串，argv 里也就没有秘密（契约 §5.10）。
    assert harness.shown == [f"http://127.0.0.1:{harness.port}/"]
    assert window_spawns[0]["url"] == harness.shown[0]
    assert "?" not in window_spawns[0]["url"]

    # ② 窗口子进程只拿到票据，绝不拿到启动器密钥（契约 §5.3）。
    window_env = window_spawns[0]["env"]
    ticket = window_env.get("VSE_WINDOW_BOOT_TICKET")
    assert isinstance(ticket, str) and len(ticket) >= 32
    assert "VSE_LAUNCH_SECRET" not in window_env

    # ③ instance.json 字段集冻结、无 bootToken、url 无查询串（契约 §5.9）。
    instance = next(info for info in harness.instance_snapshots if info is not None)
    assert instance["url"] == f"http://127.0.0.1:{harness.port}/"
    assert "?" not in instance["url"]
    assert "bootToken" not in instance
    assert instance["schemaVersion"] == 2
    assert instance["securityContract"] == 1
    assert instance["epoch"] == harness.apps[0][0].extensions["local_web_security"].epoch
    secret = harness.env_overrides[-1]["VSE_LAUNCH_SECRET"]
    assert secret and secret not in json.dumps(instance)
    assert ticket not in json.dumps(instance)

    # ④ 启动器日志不含票据/授权/密钥（契约 §5.13）。
    joined = "\n".join(harness.logs)
    assert ticket not in joined and secret not in joined

    # ⑤ capabilities 只暴露契约字段，不含任何凭据（契约 §6.2）。
    status, _headers, _cookies, body = _http(harness.port, "GET", web_security.CAPABILITIES_PATH)
    assert status == 200
    assert ticket not in body.decode("utf-8") and secret not in body.decode("utf-8")
    assert json.loads(body.decode("utf-8"))["data"]["grantArm"] is True

    # ⑥ 票据真的能用：换会话 → 写请求到达视图（422，不是 401/403）。
    status, set_cookies, body = _exchange(harness.port, ticket)
    assert status == 200, body
    assert json.loads(body.decode("utf-8")) == {"ok": True, "data": {"exchanged": True}}
    cookie = _set_cookie_value(set_cookies, web_security.SESSION_COOKIE_NAME)
    assert cookie
    assert _write(harness.port, cookie=cookie)[0] == 422

    # ⑦ 写保护仍拒绝缺失/错误认证。
    assert _write(harness.port, cookie=None)[0] == 401
    no_origin = _write(harness.port, cookie=cookie, origin=None)
    assert no_origin[0] == 403
    assert _error_type(no_origin[3]) == "OriginRequired"
    wrong_origin = _write(harness.port, cookie=cookie, origin="http://evil.example")
    assert wrong_origin[0] == 403
    assert _error_type(wrong_origin[3]) == "CrossSiteRequest"

    # ⑧ 票据重放一律 401（与过期不可区分）。
    replay_status, replay_cookies, replay_body = _exchange(harness.port, ticket)
    assert replay_status == 401
    assert _error_type(replay_body) == "BootTicketInvalid"
    assert replay_cookies == []


# ── 2. 慢启动：签发在健康检查之后 ──────────────────────────────────────────


def test_slow_start_ticket_is_issued_after_health_check(
    harness: TransportHarness,
    window_spawns: list[dict[str, Any]],
    app_clock: AppClock,
) -> None:
    """健康检查耗时 20 秒：注入票据仍可交换，而 spawn 时刻的旧票据已过期。"""
    harness.app_clock = app_clock
    harness.health_probe_failures = 4  # 4 次探活失败 × 每次推进 5 秒 = 20 秒慢启动

    def slow_clock() -> None:
        app_clock.advance(5.0)

    code = harness.run(stop_when=lambda: bool(window_spawns), on_sleep=slow_clock)
    assert code == 0
    assert app_clock.now >= 20.0

    ticket = window_spawns[0]["env"]["VSE_WINDOW_BOOT_TICKET"]
    status, _cookies, body = _exchange(harness.port, ticket)
    assert status == 200, body  # TTL 从「健康检查之后的签发时刻」起算

    # 对照：spawn 时刻注册的旧 VSE_BOOT_TOKEN 在同一时刻已过期——这正是旧链路的
    # 潜伏缺陷（契约 §2 D2），新链路不得靠放大 TTL 规避（§5.3）。
    legacy_token = harness.env_overrides[-1]["VSE_BOOT_TOKEN"]
    assert legacy_token != ticket
    legacy_status, _legacy_cookies, legacy_body = _exchange(harness.port, legacy_token)
    assert legacy_status == 401
    assert _error_type(legacy_body) == "BootTicketInvalid"


# ── 3. 重复打开：window.request → owner 重新签发 ───────────────────────────


def test_reopen_through_window_request_yields_a_fresh_ticket(
    harness: TransportHarness, window_spawns: list[dict[str, Any]]
) -> None:
    state: dict[str, Any] = {}

    def on_sleep() -> None:
        if state.get("stage", 0) == 0 and window_spawns:
            # 首窗页面已完成握手：消费它的票据。
            state["ticket1"] = window_spawns[0]["env"]["VSE_WINDOW_BOOT_TICKET"]
            status, set_cookies, body = _exchange(harness.port, state["ticket1"])
            assert status == 200, body
            state["session1"] = _set_cookie_value(set_cookies, web_security.SESSION_COOKIE_NAME)
            # 第二实例拿不到实例锁：写 window.request 请 owner 重开窗口。
            (harness.layout.state_dir / "window.request").write_text(
                json.dumps({"purpose": "open", "requestedAt": 0, "nonce": "0" * 32}),
                encoding="utf-8",
            )
            state["stage"] = 1

    code = harness.run(stop_when=lambda: len(window_spawns) >= 2, on_sleep=on_sleep)
    assert code == 0
    assert len(window_spawns) == 2
    # owner 已消费请求文件；两次开窗都是同一个无查询串 URL。
    assert not (harness.layout.state_dir / "window.request").exists()
    assert [call["url"] for call in window_spawns] == [harness.shown[0]] * 2

    ticket2 = window_spawns[1]["env"]["VSE_WINDOW_BOOT_TICKET"]
    assert ticket2 and ticket2 != state["ticket1"]  # 每次都现签，绝不复用旧票据

    # 新票据可用；旧票据重放一律 401（不因重开而复活）。
    status, _cookies, body = _exchange(harness.port, ticket2)
    assert status == 200, body
    replay_status, replay_cookies, replay_body = _exchange(harness.port, state["ticket1"])
    assert replay_status == 401
    assert _error_type(replay_body) == "BootTicketInvalid"
    assert replay_cookies == []

    # 首窗的会话不受重开影响。
    assert _write(harness.port, cookie=state["session1"])[0] == 422


# ── 4. app 重启：旧会话/旧票据全部失效 ─────────────────────────────────────


def test_restart_invalidates_old_session_and_ticket(
    harness: TransportHarness, window_spawns: list[dict[str, Any]]
) -> None:
    assert harness.run(stop_when=lambda: bool(window_spawns)) == 0
    ticket1 = window_spawns[0]["env"]["VSE_WINDOW_BOOT_TICKET"]
    status, set_cookies, body = _exchange(harness.port, ticket1)
    assert status == 200, body
    session1 = _set_cookie_value(set_cookies, web_security.SESSION_COOKIE_NAME)
    epoch1 = harness.apps[0][0].extensions["local_web_security"].epoch
    secret1 = harness.env_overrides[-1]["VSE_LAUNCH_SECRET"]

    # 重启：旧 app 进程结束，新进程（新 epoch / 新启动器密钥）在同端口起来。
    harness.stop_apps()
    window_spawns.clear()
    assert harness.run(stop_when=lambda: bool(window_spawns)) == 0
    epoch2 = harness.apps[0][0].extensions["local_web_security"].epoch
    secret2 = harness.env_overrides[-1]["VSE_LAUNCH_SECRET"]
    assert epoch2 != epoch1 and secret2 != secret1

    # 旧会话失效：写请求 fail-closed（会话只在内存，重启即全体失效）。
    stale_write = _write(harness.port, cookie=session1)
    assert stale_write[0] == 401
    assert _error_type(stale_write[3]) == "SessionRequired"
    # 旧票据同样失效。
    assert _exchange(harness.port, ticket1)[0] == 401
    # 旧启动器密钥在新进程上无效。
    grant_status, _headers, _cookies, grant_body = _http(
        harness.port,
        "POST",
        web_security.WINDOW_GRANT_PATH,
        json_body={"purpose": "open", "delivery": "claim"},
        headers={
            "Origin": f"http://127.0.0.1:{harness.port}",
            web_security.LAUNCHER_SECRET_HEADER: secret1,
        },
    )
    assert grant_status == 401
    assert _error_type(grant_body) == "LauncherAuthRequired"

    # 新票据重新建立会话，写操作恢复。
    ticket2 = window_spawns[0]["env"]["VSE_WINDOW_BOOT_TICKET"]
    status, set_cookies, body = _exchange(harness.port, ticket2)
    assert status == 200, body
    session2 = _set_cookie_value(set_cookies, web_security.SESSION_COOKIE_NAME)
    assert _write(harness.port, cookie=session2)[0] == 422


# ── 5. 诊断与状态文件：票据/密钥零残留 ─────────────────────────────────────


def test_diagnostics_and_state_files_never_record_ticket_or_secret(
    harness: TransportHarness,
    window_spawns: list[dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = dr.Recorder(tmp_path / "diagnostics")
    monkeypatch.setattr(dr, "_default", recorder)

    assert harness.run(stop_when=lambda: bool(window_spawns)) == 0
    app = harness.apps[0][0]
    assert app.extensions["diagnostic_recorder"] is recorder  # 确实是同一个记录器

    ticket = window_spawns[0]["env"]["VSE_WINDOW_BOOT_TICKET"]
    secret = harness.env_overrides[-1]["VSE_LAUNCH_SECRET"]

    recorder.start()
    try:
        # 真实走一遍会碰凭据的请求：交换票据 + 一次被拒的写请求。
        assert _exchange(harness.port, ticket)[0] == 200
        assert _write(harness.port, cookie=None)[0] == 401
    finally:
        recorder.stop()

    blobs = [path.read_bytes() for path in recorder.root.rglob("*") if path.is_file()]
    assert blobs, "诊断记录器没有落任何文件，扫描无意义"
    joined = b"".join(blobs)
    # 正向对照：记录器确实抓到了这次交换（否则「扫描无票据」是空断言）。
    assert b"api_security_boot_exchange" in joined
    for blob in blobs:
        assert ticket.encode("utf-8") not in blob
        assert secret.encode("utf-8") not in blob

    # 安装根下的状态文件同样零残留（instance.json 等）。
    state_files = [path for path in harness.layout.root.rglob("*") if path.is_file()]
    assert state_files
    for path in state_files:
        data = path.read_bytes()
        assert ticket.encode("utf-8") not in data, path
        assert secret.encode("utf-8") not in data, path


# ── 6. 旧 app 降级：新启动器 + 旧 app 仍走 ?boot= 且 instance.json 带 bootToken ─


def test_legacy_app_fallback_keeps_boot_query_and_works(
    harness: TransportHarness, window_spawns: list[dict[str, Any]]
) -> None:
    harness.capabilities = lambda port: None  # 旧 app：无 capabilities / 无 grantArm

    assert harness.run(stop_when=lambda: bool(window_spawns)) == 0
    legacy_token = harness.env_overrides[-1]["VSE_BOOT_TOKEN"]

    # 旧路径逐字保留：URL 带 ?boot=、instance.json 写 bootToken（契约 §8.1）。
    assert harness.shown == [f"http://127.0.0.1:{harness.port}/?boot={legacy_token}"]
    instance = next(info for info in harness.instance_snapshots if info is not None)
    assert instance["bootToken"] == legacy_token
    assert instance["url"] == harness.shown[0]
    # 旧 app 没有 window-grant：不预置授权、不注入窗口票据。
    assert harness.brokers == []
    assert window_spawns[0]["env"] == {}

    # 旧链路的票据在真实 app 上照旧可用（语义不因契约收窄）。
    status, _cookies, body = _exchange(harness.port, legacy_token)
    assert status == 200, body
