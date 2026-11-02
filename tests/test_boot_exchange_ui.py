# -*- coding: utf-8 -*-
"""DSH-V2-04：启动票据清理与失败反馈（真实浏览器场景）。

运行::

    python -B -m pytest -p no:cacheprovider tests/test_boot_exchange_ui.py -q -rs

全部用例都跑在 ``tests/browser/v2_fixtures.py`` 的真实浏览器夹具里（Edge/Chrome
无头 + CDP，真实 ES Module、真实 DOM、真实 HTTP 与 Cookie），不使用源文本断言：

1. 首次打开：``/?boot=<票据>`` → 交换成功、会话 Cookie 建立、地址栏清理、无横幅；
2. 兼容分支顺序：交换请求发出时地址栏已经清理（票据不进入请求 Referer）；
3. 刷新：地址栏残留的已消费票据被清理，有效会话不被重设；
4. 已有有效 Cookie：再次打开不显示横幅，claim 返回 ``sessionValid``；
5. 交换失败：无效票据返回 ``status=failed`` + 真实原因（不返回伪成功）；8 秒硬超时 →
   明确失败状态 + “重试 / 从开始菜单重新打开”横幅；
6. 服务重启：旧会话失效，新启动票据重新建立会话；
7. 服务重启且无票据：写请求 401 → “恢复会话” → 标记失效 → 指引重新打开。

无浏览器/Node 时夹具按约定 ``pytest.skip`` 并写明缺失项与设置方法（release 门禁
应把 SKIP 视为失败，见 ``docs/refactor-v2/DSH_BROWSER_SETUP.md``）。
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any

from werkzeug.serving import make_server

import web.app as web_app
from tests.browser.v2_fixtures import (  # noqa: F401 - pytest fixture 注入
    BrowserPage,
    LiveServer,
    assert_no_console_errors,
    browser,
    page,
    server,
)

BANNER_ID = "vse-session-banner"

#: 直接打开页面时 boot-claim 必然 409（没有预置授权），属正常路径。
BOOT_CLAIM_PROBE = re.compile(
    r"status of 409 \(CONFLICT\) \(http://127\.0\.0\.1:\d+/api/security/boot-claim\)"
)
#: 客户端 8 秒硬超时会 abort 在途的 boot-exchange 请求，浏览器记为 network error。
BOOT_EXCHANGE_ABORT = re.compile(r"net::ERR_ABORTED.*boot-exchange")
#: 无效/已消费票据的交换被服务端拒绝：浏览器把 401 记为 network error。
BOOT_EXCHANGE_401 = re.compile(
    r"status of 401 \(UNAUTHORIZED\) \(http://127\.0\.0\.1:\d+/api/security/boot-exchange\)"
)
#: 服务重启后旧会话失效：写请求与恢复请求各有一条 401 网络日志。
WRITE_SESSION_401 = re.compile(
    r"status of 401 \(UNAUTHORIZED\) \(http://127\.0\.0\.1:\d+/api/p/workbench/projects\)"
)
RECOVER_401 = re.compile(
    r"status of 401 \(UNAUTHORIZED\) \(http://127\.0\.0\.1:\d+/api/security/session-recover\)"
)

_BANNER_STATE_JS = """
(() => {
  const el = document.getElementById('vse-session-banner');
  if (!el) return { exists: false };
  const button = el.querySelector('button');
  const message = el.querySelector('span');
  return {
    exists: true,
    hidden: Boolean(el.hidden),
    visible: el.getClientRects().length > 0,
    message: message ? message.textContent.trim() : null,
    text: el.innerText,
    button: button ? button.textContent.trim() : null,
    buttonHidden: button ? Boolean(button.hidden) : null,
  };
})()
"""


def _wait_shell(page: BrowserPage) -> None:  # noqa: F811 - 参数名就是 fixture 名
    """等外壳 ES Module 链真正渲染出插件页面（不是只看 HTML 文本）。"""
    page.wait_for_selector("#plugin-host .wb-page")


def _banner_state(page: BrowserPage) -> dict:  # noqa: F811 - 参数名就是 fixture 名
    return page.eval(_BANNER_STATE_JS)


def _session_cookies(page: BrowserPage, base_url: str) -> list[dict]:  # noqa: F811
    return [item for item in page.cookies([base_url]) if item.get("name") == "vse_session"]


def _wait_session_cookie(
    page: BrowserPage,  # noqa: F811 - 参数名就是 fixture 名
    base_url: str,
    timeout: float = 15.0,
    previous: str | None = None,
) -> list[dict]:
    """等启动握手真正建立会话 Cookie，避免在交换请求仍在途时断言。

    Cookie 不按端口隔离：服务重启场景下旧 Cookie 仍在同一个 127.0.0.1 上，
    因此给出 ``previous`` 时必须等到它被新值替换，而不是“看到 Cookie 就返回”。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        cookies = _session_cookies(page, base_url)
        if cookies and (previous is None or cookies[0].get("value") != previous):
            return cookies
        time.sleep(0.05)
    raise AssertionError(page.diagnose("等待启动握手建立会话 Cookie 超时"))


def _wait_initial_handshake(page: BrowserPage, timeout: float = 15.0) -> None:  # noqa: F811
    """等外壳启动时的自动握手走完（无预置授权时以 boot-claim 409 收尾）。

    该信号出现时自动握手已越过「读取地址栏票据」这一步，此后注入的票据不会被它抢走。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for entry in page.console_errors():
            if BOOT_CLAIM_PROBE.search(str(entry.get("text") or "")):
                return
        time.sleep(0.05)
    raise AssertionError(page.diagnose("等待外壳自动握手完成超时（未观察到 boot-claim 409）"))


def _start_instance() -> tuple[Any, Any, threading.Thread]:
    """在同一测试进程里再起一个真实 app 实例（模拟服务重启：内存态会话全部失效）。"""
    app = web_app.create_app()
    httpd = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=httpd.serve_forever, name="v2-restart-http", daemon=True)
    thread.start()
    return app, httpd, thread


def _stop_instance(httpd: Any, thread: threading.Thread) -> None:
    httpd.shutdown()
    thread.join(timeout=5)


# ── 1. 首次打开：票据交换 + 地址栏清理 + 会话 Cookie ────────────────────────


def test_first_open_exchanges_ticket_and_cleans_address_bar(
    server: LiveServer, page: BrowserPage  # noqa: F811 - 参数名就是 fixture 名
) -> None:
    page.goto(server.launch_url)
    _wait_shell(page)

    # 地址栏票据在网络请求后立即被 replaceState 清理（保留其余查询参数）。
    page.wait_for_function("location.search === ''")
    cookies = _wait_session_cookie(page, server.base_url)
    assert len(cookies) == 1, page.diagnose(f"启动票据未建立会话 Cookie：{cookies}")
    assert cookies[0].get("httpOnly") is True, page.diagnose(f"会话 Cookie 必须 HttpOnly：{cookies[0]}")
    assert cookies[0].get("sameSite") == "Strict", page.diagnose(f"会话 Cookie 必须 SameSite=Strict：{cookies[0]}")
    assert "vse_session" not in str(page.eval("document.cookie")), page.diagnose("HttpOnly 会话不应被页面 JS 读到")

    state = _banner_state(page)
    assert state["exists"] is True, page.diagnose("外壳未挂载会话横幅")
    assert state["hidden"] is True and state["visible"] is False, page.diagnose(
        f"成功交换后不应显示横幅：{state}"
    )
    assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE,))


# ── 2. 兼容分支顺序：先清理地址栏，再发交换请求 ──────────────────────────────


def test_legacy_ticket_cleared_before_exchange_request(
    server: LiveServer, page: BrowserPage  # noqa: F811 - 参数名就是 fixture 名
) -> None:
    page.goto(server.base_url + "/")
    _wait_shell(page)
    # 先让外壳自己的自动握手走完，再注入票据（否则票据可能被它读走）。
    _wait_initial_handshake(page)
    # 此时没有会话：页面自动握手走 claim → 409（正常），地址栏没有票据。
    assert _session_cookies(page, server.base_url) == [], page.diagnose("新实例不应已有会话")

    token = server.security.tickets.issue()  # 测试进程签发的合成票据
    script = """
    (async () => {
      history.replaceState(null, "", "/?boot=__TOKEN__&keep=1");
      const calls = [];
      const realFetch = window.fetch;
      window.fetch = (url, init = {}) => {
        calls.push({
          url: String(url),
          search: location.search,
          referrerPolicy: init.referrerPolicy || null,
        });
        return realFetch(url, init);
      };
      let outcome = null;
      try {
        const mod = await import("/static/host/boot-exchange.js?probe=" + Date.now());
        outcome = await mod.runBootHandshakeDetailed(window);
      } finally {
        window.fetch = realFetch;
      }
      return { outcome, calls, search: location.search, path: location.pathname };
    })()
    """.replace(
        "__TOKEN__", token
    )
    result = page.eval(script)

    exchange_calls = [call for call in result["calls"] if call["url"].startswith("/api/security/boot-exchange")]
    assert len(exchange_calls) == 1, page.diagnose(f"兼容分支未发起唯一一次交换：{result['calls']}")
    # 关键断言：交换请求发出的瞬间，地址栏已经不含票据。
    assert "boot=" not in exchange_calls[0]["search"], page.diagnose(
        f"交换请求发出时地址栏仍有票据：{exchange_calls[0]}"
    )
    after_probe = [
        call for call in result["calls"] if not call["url"].startswith("/api/security/capabilities")
    ]
    assert after_probe and all("boot=" not in call["search"] for call in after_probe), page.diagnose(
        f"清理后的请求仍带票据查询串：{result['calls']}"
    )
    capabilities_calls = [
        call for call in result["calls"] if call["url"].startswith("/api/security/capabilities")
    ]
    assert capabilities_calls and capabilities_calls[0]["referrerPolicy"] == "no-referrer", page.diagnose(
        f"能力探测必须禁止 Referer（否则票据随 Referer 外泄）：{capabilities_calls}"
    )
    assert result["outcome"] == {"status": "ok", "source": "legacy", "error": None}, page.diagnose(
        f"兼容分支未返回成功状态：{result['outcome']}"
    )
    assert result["search"] == "?keep=1", page.diagnose(f"清理票据时丢失了其他查询参数：{result['search']}")
    assert result["path"] == "/", page.diagnose(f"清理票据时改变了路径：{result['path']}")
    assert len(_session_cookies(page, server.base_url)) == 1, page.diagnose("兼容分支未建立会话 Cookie")
    assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE,))


# ── 3. 刷新：残留票据被清理，有效会话不被重设 ────────────────────────────────


def test_refresh_cleans_stale_ticket_and_keeps_session(
    server: LiveServer, page: BrowserPage  # noqa: F811 - 参数名就是 fixture 名
) -> None:
    page.goto(server.launch_url)
    _wait_shell(page)
    first = _wait_session_cookie(page, server.base_url)
    assert len(first) == 1, page.diagnose(f"首次打开未建立会话：{first}")

    # 模拟“交换后地址栏仍留着旧票据”的刷新：已消费票据不得再次触发交换或报错。
    page.eval(f"history.replaceState(null, '', '/?boot={server.token}&keep=1')")
    page.eval("window.__vseReloadMarker = 1; setTimeout(() => location.reload(), 0); true")
    page.wait_for_function(
        "document.readyState === 'complete' && typeof window.__vseReloadMarker === 'undefined'"
    )
    _wait_shell(page)
    page.wait_for_function("location.search === '?keep=1'")

    after = _session_cookies(page, server.base_url)
    assert len(after) == 1, page.diagnose(f"刷新后会话 Cookie 数量异常：{after}")
    assert after[0]["value"] == first[0]["value"], page.diagnose("刷新不应重设有效会话 Cookie")
    state = _banner_state(page)
    assert state["hidden"] is True and state["visible"] is False, page.diagnose(
        f"刷新后不应显示横幅：{state}"
    )
    assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE,))


# ── 4. 已有有效 Cookie：直接打开不显示横幅 ──────────────────────────────────


def test_existing_valid_cookie_opens_without_banner(
    server: LiveServer, page: BrowserPage  # noqa: F811 - 参数名就是 fixture 名
) -> None:
    page.goto(server.launch_url)
    _wait_shell(page)
    first = _wait_session_cookie(page, server.base_url)
    assert len(first) == 1, page.diagnose(f"首次打开未建立会话：{first}")

    page.goto(server.base_url + "/")
    _wait_shell(page)
    page.wait_for_function("location.search === ''")

    claim = page.eval(
        """
        (async () => {
          const response = await fetch('/api/security/boot-claim', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: '{}',
          });
          return { status: response.status, body: await response.json() };
        })()
        """
    )
    assert claim["status"] == 200, page.diagnose(f"已有会话时 claim 应 200：{claim}")
    data = claim["body"]["data"]
    assert data["sessionValid"] is True and data["exchanged"] is False, page.diagnose(
        f"已有有效 Cookie 时不应重设会话：{data}"
    )
    assert _session_cookies(page, server.base_url)[0]["value"] == first[0]["value"], page.diagnose(
        "已有有效 Cookie 被意外重设"
    )
    state = _banner_state(page)
    assert state["hidden"] is True and state["visible"] is False, page.diagnose(
        f"已有有效会话时不应显示横幅：{state}"
    )
    assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE,))


# ── 5. 交换超时：明确失败状态 + 可恢复提示 ──────────────────────────────────


def test_exchange_timeout_shows_recoverable_banner(
    server: LiveServer, page: BrowserPage  # noqa: F811 - 参数名就是 fixture 名
) -> None:
    release = threading.Event()
    original = server.security._boot_exchange

    def slow_exchange():
        release.wait(30)
        return original()

    server.security._boot_exchange = slow_exchange  # 只挂起本实例的交换端点
    try:
        page.goto(server.launch_url)
        # 客户端 8 秒硬超时 → 失败事件 → 横幅（重试 / 从开始菜单重新打开）。
        page.wait_for_selector(f"#{BANNER_ID}:not([hidden])", timeout_ms=25000)
        state = _banner_state(page)
        assert state["visible"] is True, page.diagnose(f"超时横幅不可见：{state}")
        assert "超时" in state["message"], page.diagnose(f"超时未给出明确失败原因：{state}")
        assert "从开始菜单重新打开" in state["message"], page.diagnose(f"缺少可恢复指引：{state}")
        assert state["button"] == "重试", page.diagnose(f"失败横幅应提供重试：{state}")
        assert page.eval("location.search") == "", page.diagnose("超时前地址栏票据未被清理")
        assert _session_cookies(page, server.base_url) == [], page.diagnose("超时的交换不应建立会话")

        # 重试：仍不可恢复时给出“从开始菜单重新打开”的明确指引，而不是伪装成功。
        page.click(selector=f"#{BANNER_ID} button")
        page.wait_for_function(
            "document.getElementById('vse-session-banner').innerText.includes('无法自动恢复')",
            timeout_ms=15000,
        )
        retried = _banner_state(page)
        assert retried["buttonHidden"] is True, page.diagnose(f"不可恢复时不应继续显示重试按钮：{retried}")
        assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE, BOOT_EXCHANGE_ABORT, RECOVER_401))
    finally:
        release.set()
        server.security._boot_exchange = original


# ── 5b. 交换失败：返回明确失败状态（不返回伪成功）+ 可恢复横幅 ────────────────


def test_legacy_exchange_failure_returns_failed_state(
    server: LiveServer, page: BrowserPage  # noqa: F811 - 参数名就是 fixture 名
) -> None:
    page.goto(server.base_url + "/")
    _wait_shell(page)
    _wait_initial_handshake(page)
    assert _session_cookies(page, server.base_url) == [], page.diagnose("新实例不应已有会话")

    # 未签发的合成票据：真实 HTTP 交换必然 401 BootTicketInvalid（不是伪造的响应）。
    script = """
    (async () => {
      history.replaceState(null, "", "/?boot=not-an-issued-ticket&keep=1");
      const mod = await import("/static/host/boot-exchange.js?probe=" + Date.now());
      const outcome = await mod.runBootHandshakeDetailed(window);
      return { outcome, search: location.search, path: location.pathname };
    })()
    """
    result = page.eval(script)

    outcome = result["outcome"]
    assert outcome["status"] == "failed", page.diagnose(
        f"交换失败必须返回失败状态而不是伪成功：{outcome}"
    )
    assert outcome["source"] == "legacy", page.diagnose(f"失败来源应为兼容分支：{outcome}")
    error = outcome["error"]
    assert error["type"] == "BootTicketInvalid" and error["status"] == 401, page.diagnose(
        f"失败状态未带真实原因：{error}"
    )
    assert "not-an-issued-ticket" not in str(outcome), page.diagnose("失败状态不得回传票据")
    # 失败前地址栏已经清理，且其他查询参数保留。
    assert result["search"] == "?keep=1" and result["path"] == "/", page.diagnose(
        f"交换失败时地址栏清理不正确：{result}"
    )
    assert _session_cookies(page, server.base_url) == [], page.diagnose("失败的交换不应建立会话")

    page.wait_for_selector(f"#{BANNER_ID}:not([hidden])")
    state = _banner_state(page)
    assert state["visible"] is True, page.diagnose(f"交换失败横幅不可见：{state}")
    assert "票据无效" in state["message"], page.diagnose(f"横幅未展示真实失败原因：{state}")
    assert "从开始菜单重新打开" in state["text"], page.diagnose(f"缺少可恢复指引：{state}")
    assert state["button"] == "重试", page.diagnose(f"失败横幅应提供重试：{state}")
    assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE, BOOT_EXCHANGE_401))


# ── 6. 服务重启：旧会话失效，新启动票据重新建立会话 ──────────────────────────


def test_service_restart_reissues_session_via_new_launch_ticket(
    server: LiveServer, page: BrowserPage  # noqa: F811 - 参数名就是 fixture 名
) -> None:
    page.goto(server.launch_url)
    _wait_shell(page)
    old = _wait_session_cookie(page, server.base_url)
    assert len(old) == 1, page.diagnose(f"首次打开未建立会话：{old}")

    app2, httpd2, thread2 = _start_instance()
    try:
        base2 = f"http://127.0.0.1:{httpd2.server_port}"
        token2 = app2.config["VSE_BOOT_TOKEN"]
        page.goto(f"{base2}/?boot={token2}")
        _wait_shell(page)
        page.wait_for_function("location.search === ''")

        cookies = _wait_session_cookie(page, base2, previous=old[0]["value"])
        assert len(cookies) == 1, page.diagnose(f"重启后新票据未建立会话：{cookies}")
        assert cookies[0]["value"] != old[0]["value"], page.diagnose("重启后仍在用旧会话 Cookie")
        claim = page.eval(
            """
            (async () => {
              const response = await fetch('/api/security/boot-claim', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: '{}',
              });
              return { status: response.status, body: await response.json() };
            })()
            """
        )
        assert claim["status"] == 200 and claim["body"]["data"]["sessionValid"] is True, page.diagnose(
            f"重启后的会话不可用：{claim}"
        )
        state = _banner_state(page)
        assert state["hidden"] is True and state["visible"] is False, page.diagnose(
            f"重启后恢复成功不应显示横幅：{state}"
        )
        assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE,))
    finally:
        _stop_instance(httpd2, thread2)


# ── 7. 服务重启且无票据：会话失效 → 恢复失败 → 指引重新打开 ──────────────────


def test_restart_without_ticket_shows_reopen_guidance(
    server: LiveServer, page: BrowserPage  # noqa: F811 - 参数名就是 fixture 名
) -> None:
    page.goto(server.launch_url)
    _wait_shell(page)
    assert len(_wait_session_cookie(page, server.base_url)) == 1, page.diagnose("首次打开未建立会话")

    app2, httpd2, thread2 = _start_instance()
    try:
        base2 = f"http://127.0.0.1:{httpd2.server_port}"
        page.goto(base2 + "/")
        _wait_shell(page)
        state = _banner_state(page)
        assert state["hidden"] is True and state["visible"] is False, page.diagnose(
            f"只读打开不应提前显示横幅：{state}"
        )

        error = page.eval(
            """
            (async () => {
              const { api } = await import('/static/host/api.js?probe=' + Date.now());
              try {
                await api('/api/p/workbench/projects', { method: 'POST', body: { name: 'DSH-V2-04' } });
                return null;
              } catch (failure) {
                return { status: failure.status, type: failure.type, message: failure.message };
              }
            })()
            """
        )
        assert error is not None and error["status"] == 401 and error["type"] == "SessionRequired", page.diagnose(
            f"旧会话在新实例上未被拒绝：{error}"
        )

        page.wait_for_selector(f"#{BANNER_ID}:not([hidden])")
        state = _banner_state(page)
        assert state["visible"] is True, page.diagnose(f"401 后横幅不可见：{state}")
        assert state["message"] == "本地会话已过期", page.diagnose(f"401 后横幅文案异常：{state}")
        assert state["button"] == "恢复会话", page.diagnose(f"401 后应提供恢复入口：{state}")

        page.click(selector=f"#{BANNER_ID} button")
        # 横幅里始终有通用指引段，必须等“无法自动恢复”这个真实结果，不能等通用文案。
        page.wait_for_function(
            "document.getElementById('vse-session-banner').innerText.includes('无法自动恢复')",
            timeout_ms=15000,
        )
        state = _banner_state(page)
        assert "无法自动恢复" in state["text"], page.diagnose(f"恢复失败未给出真实原因：{state}")
        assert state["buttonHidden"] is True, page.diagnose(f"不可恢复时不应继续显示按钮：{state}")
        assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE, WRITE_SESSION_401, RECOVER_401))
    finally:
        _stop_instance(httpd2, thread2)
