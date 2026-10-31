# -*- coding: utf-8 -*-
"""C7 本机安全与启动契约验证（W16-03）。

覆盖契约验证清单：
1. 无票据 401（boot-exchange 拒绝无效/缺失票据）；
2. 票据单次（重放 401）与 ≤10s TTL；
3. 写操作 Origin 拒绝（缺失 403 OriginRequired、不匹配 403 CrossSiteRequest）；
4. CSRF 缺失拒绝（以 Origin 严格校验替代：会话有效但无 Origin 的写请求 403）；
5. Cookie 属性断言（HttpOnly; SameSite=Strict; Path=/；loopback http 不设 Secure）；
6. fail-closed：会话缺失的写请求 401，绝不退化为无认证访问；读请求不受影响
   （supervisor 健康探测与页面静态加载保持既有行为）；
7. 启动链：supervisor 经环境变量把票据传给 child，URL 与 instance.json 记录票据；
8. 前端交换模块：票据提取/清除/replaceState 行为（Node 隔离执行）。

fail-closed 路径用原生 werkzeug Client（模拟"不带浏览器等价行为的客户端"），
正常路径用 create_app 自带的等价 test client（真实走 boot-exchange 端点）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from werkzeug.test import Client
from werkzeug.wrappers import Response

import web.app as web_app
from web.security import (
    BOOT_EXCHANGE_PATH,
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "security.db"))
    monkeypatch.delenv("VSE_BOOT_TOKEN", raising=False)
    flask_app = web_app.create_app()
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture()
def raw(app):
    """原生 werkzeug Client：不注入 Origin、不自动交换票据。"""
    return Client(app, Response)


def _loopback(raw_client: Client):
    return {"environ_base": {"REMOTE_ADDR": "127.0.0.1"}}


def _origin_headers(origin: str = "http://localhost") -> dict:
    return {"Origin": origin}


# ── 1&2. 票据：无票据 401、单次、TTL ─────────────────────────────────────


def test_boot_exchange_without_ticket_is_401(app, raw):
    response = raw.post(BOOT_EXCHANGE_PATH, json={}, **_loopback(raw))
    assert response.status_code == 401
    assert response.get_json()["error"]["type"] == "BootTicketInvalid"


def test_boot_exchange_with_wrong_ticket_is_401(app, raw):
    response = raw.post(
        BOOT_EXCHANGE_PATH,
        json={"token": "not-the-real-ticket"},
        **_loopback(raw),
    )
    assert response.status_code == 401


def test_boot_ticket_is_single_use(app, raw):
    token = app.config["VSE_BOOT_TOKEN"]
    first = raw.post(
        BOOT_EXCHANGE_PATH, json={"token": token}, **_loopback(raw), headers=_origin_headers()
    )
    assert first.status_code == 200
    replay = raw.post(
        BOOT_EXCHANGE_PATH, json={"token": token}, **_loopback(raw), headers=_origin_headers()
    )
    assert replay.status_code == 401
    assert replay.get_json()["error"]["type"] == "BootTicketInvalid"


def test_boot_ticket_ttl_is_at_most_ten_seconds(app, raw):
    from web.security import BootTicketStore

    store = BootTicketStore("t", ttl_seconds=10)
    assert store.consume("wrong") is False
    assert store.consume("t") is True
    assert store.consume("t") is False  # 单次

    expired = BootTicketStore("t2", ttl_seconds=10)
    expired._issued_at -= 11  # 模拟签发于 11 秒前
    assert expired.consume("t2") is False


# ── 5. Cookie 属性 ───────────────────────────────────────────────────────


def test_session_cookie_attributes(app, raw):
    token = app.config["VSE_BOOT_TOKEN"]
    response = raw.post(
        BOOT_EXCHANGE_PATH, json={"token": token}, **_loopback(raw), headers=_origin_headers()
    )
    assert response.status_code == 200
    cookie = response.headers.get("Set-Cookie") or ""
    assert cookie.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie
    assert "Path=/" in cookie
    # loopback http：浏览器把 127.0.0.1 视为安全上下文，不设 Secure（C7 以实测为准）
    assert "Secure" not in cookie
    assert f"Max-Age={SESSION_TTL_SECONDS}" in cookie


# ── 3&4. 写操作：会话 + Origin（Origin 严格校验替代 CSRF token） ──────────


def test_write_without_session_is_401_fail_closed(app, raw):
    response = raw.put(
        "/api/project-status/section-rollup", json={}, **_loopback(raw), headers=_origin_headers()
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["type"] == "SessionRequired"


def test_write_with_session_but_missing_origin_is_403(app, raw):
    token = app.config["VSE_BOOT_TOKEN"]
    first = raw.post(
        BOOT_EXCHANGE_PATH, json={"token": token}, **_loopback(raw), headers=_origin_headers()
    )
    cookie_header = first.headers.get("Set-Cookie") or ""
    session_pair = cookie_header.split(";")[0]
    response = raw.put(
        "/api/project-status/section-rollup",
        json={},
        **_loopback(raw),
        headers={"Cookie": session_pair},
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["type"] == "OriginRequired"


def test_write_with_wrong_origin_is_403(app, raw):
    token = app.config["VSE_BOOT_TOKEN"]
    first = raw.post(
        BOOT_EXCHANGE_PATH, json={"token": token}, **_loopback(raw), headers=_origin_headers()
    )
    session_pair = (first.headers.get("Set-Cookie") or "").split(";")[0]
    for origin in ("http://127.0.0.1:6666", "http://evil.example", "http://localhost:1"):
        response = raw.put(
            "/api/project-status/section-rollup",
            json={},
            **_loopback(raw),
            headers={"Cookie": session_pair, "Origin": origin},
        )
        assert response.status_code == 403, origin
        assert response.get_json()["error"]["type"] == "CrossSiteRequest"


def test_write_with_session_and_matching_origin_reaches_view(app, raw):
    token = app.config["VSE_BOOT_TOKEN"]
    first = raw.post(
        BOOT_EXCHANGE_PATH, json={"token": token}, **_loopback(raw), headers=_origin_headers()
    )
    session_pair = (first.headers.get("Set-Cookie") or "").split(";")[0]
    response = raw.put(
        "/api/project-status/section-rollup",
        json={},
        **_loopback(raw),
        headers={"Cookie": session_pair, "Origin": "http://localhost"},
    )
    # 通过安全层后到达视图（422=业务校验，而不是 401/403 安全拒绝）
    assert response.status_code == 422


def test_read_endpoints_stay_open_for_supervisor_probe(app, raw):
    # supervisor 探测 /api/version 与 /api/host/manifest（父进程、无会话）。
    for path in ("/api/version", "/api/host/manifest"):
        response = raw.get(path, **_loopback(raw))
        assert response.status_code == 200, path


def test_non_loopback_exchange_stays_rejected(app, raw):
    token = app.config["VSE_BOOT_TOKEN"]
    response = raw.post(
        BOOT_EXCHANGE_PATH,
        json={"token": token},
        environ_base={"REMOTE_ADDR": "192.0.2.10"},
        headers=_origin_headers(),
    )
    # 既有 loopback 守卫先于本模块生效（fail-closed 不回退）。
    assert response.status_code == 403
    assert response.get_json()["error"]["type"] == "LocalAccessRequired"


# ── 6. 测试客户端等价性：写请求自动补 Origin + 真实 boot-exchange ─────────


def test_default_test_client_writes_pass_through_security(app):
    client = app.test_client()
    response = client.put("/api/project-status/section-rollup", json={})
    # 到达视图的业务校验层（而不是被安全层拒绝）。
    assert response.status_code == 422


def test_each_app_instance_has_its_own_session_store(app):
    other = web_app.create_app()
    client = app.test_client()
    other_client = other.test_client()
    ok = client.put("/api/project-status/section-rollup", json={})
    ok_other = other_client.put("/api/project-status/section-rollup", json={})
    assert ok.status_code == 422 and ok_other.status_code == 422
    # per-app 状态，绝不串味。
    assert app.config["VSE_BOOT_TOKEN"] != other.config["VSE_BOOT_TOKEN"]


# ── 7. 启动链：supervisor 生成票据 → env → URL/instance.json ─────────────


def test_supervisor_boot_token_reaches_env_url_and_instance_file(tmp_path: Path, monkeypatch):
    """supervisor 在 spawn 前生成票据：env 传递、URL 附票、instance.json 记录。"""
    from vse_boot.layout import InstallLayout
    from vse_boot import supervisor as sup
    from tests.test_vse_boot_supervisor import install as stage_version

    monkeypatch.delenv("VSE_BOOT_TOKEN", raising=False)  # 防泄漏到同进程其他用例

    class FakeChild:
        pid = 4242

        def __init__(self) -> None:
            self._exit = None

        def poll(self):
            return self._exit

        def wait(self, timeout=None):
            return 0 if self._exit is None else self._exit

        def terminate(self):
            self._exit = -15

        def kill(self):
            self._exit = -9

    layout = InstallLayout(tmp_path).ensure()
    stage_version(layout, "2.4.0")  # 有可启动版本，_boot 才会走到 spawn
    captured: dict = {}

    def spawn(app_dir, port, layout_):
        captured["env_token"] = os.environ.get("VSE_BOOT_TOKEN")
        return FakeChild()

    supervisor = sup.Supervisor(
        layout,
        spawn=spawn,
        probe=lambda port: True,
        show=lambda url, _layout: captured.__setitem__("show_url", url),
        pick_port=lambda: 46789,
        health_timeout=2.0,
        log=lambda _m: None,
    )

    # _serve 写完 instance.json/show 之后第一次 sleep 即退出（否则空转）。
    # run() 的 finally 会删掉 instance.json，所以在退出前于 sleep 里读取。
    def _sleep_once(_seconds: float) -> None:
        captured["instance"] = json.loads(
            layout.instance_file.read_text(encoding="utf-8")
        )
        supervisor.controls.quit.set()

    supervisor.sleep = _sleep_once  # type: ignore[method-assign]
    code = supervisor.run()
    assert code == 0
    token = captured.get("env_token")
    assert token, "spawn 时 os.environ 必须已注入 VSE_BOOT_TOKEN"
    assert captured["show_url"] == f"http://127.0.0.1:46789/?boot={token}"
    info = captured["instance"]
    assert info["bootToken"] == token
    assert info["url"] == captured["show_url"]


# ── 8. 前端交换模块（Node 隔离执行，无 DOM） ─────────────────────────────


def _node_available() -> bool:
    return shutil.which("node") is not None


needs_node = pytest.mark.skipif(not _node_available(), reason="需要 Node.js")


@needs_node
def test_boot_exchange_js_extract_strip_and_cleanup_logic() -> None:
    script = r"""
const mod = await import(process.argv[1]);
const { extractBootTicket, stripBootTicket } = mod;
const out = {
  extract: extractBootTicket("?boot=abc&x=1"),
  none: extractBootTicket("?x=1"),
  keep: stripBootTicket("?boot=abc&x=1"),
  root: stripBootTicket("?boot=abc"),
  unchanged: stripBootTicket("?x=1"),
};
console.log(JSON.stringify(out));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script,
         (REPO_ROOT / "web" / "static" / "host" / "boot-exchange.js").as_uri()],
        capture_output=True, text=True, encoding="utf-8", check=False, cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout.strip().splitlines()[-1])
    assert data["extract"] == "abc"
    assert data["none"] is None
    assert data["keep"] == "?x=1"
    assert data["root"] == ""
    assert data["unchanged"] is None


@needs_node
def test_host_shell_boots_exchange_before_shell_render() -> None:
    source = (REPO_ROOT / "web" / "static" / "host" / "shell.js").read_text(encoding="utf-8")
    # 外壳启动前先做票据交换（顺序固定，防外壳读接口时写请求先行失败）。
    assert 'runBootExchange().finally(() => startShell())' in source
    assert 'from "./boot-exchange.js"' in source
