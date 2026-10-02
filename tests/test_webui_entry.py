# -*- coding: utf-8 -*-
"""W5-1 桌面启动体验测试：--no-browser 开关与端口就绪探测后自动唤起浏览器。"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import webui


def test_parser_defaults_open_browser() -> None:
    args = webui.build_parser().parse_args([])
    assert args.host == "127.0.0.1"
    assert args.port is None
    assert args.no_browser is False


def test_resolve_port_priority(monkeypatch) -> None:
    """端口优先级：--port 参数 > VSE_TOOLBOX_PORT 环境变量 > 默认 5000。"""
    monkeypatch.delenv("VSE_TOOLBOX_PORT", raising=False)
    assert webui._resolve_port(None) == 5000
    assert webui._resolve_port(8021) == 8021

    monkeypatch.setenv("VSE_TOOLBOX_PORT", "8123")
    assert webui._resolve_port(None) == 8123
    assert webui._resolve_port(8021) == 8021

    monkeypatch.setenv("VSE_TOOLBOX_PORT", "not-a-number")
    assert webui._resolve_port(None) == 5000

    monkeypatch.setenv("VSE_TOOLBOX_PORT", "70000")
    assert webui._resolve_port(None) == 5000


def test_parser_accepts_no_browser_flag() -> None:
    args = webui.build_parser().parse_args(["--no-browser", "--port", "8021"])
    assert args.no_browser is True
    assert args.port == 8021


def test_parser_sync_scheduler_flag_defaults_on() -> None:
    """常驻同步调度默认开启；--no-sync-scheduler 显式关闭。"""
    args = webui.build_parser().parse_args([])
    assert args.no_sync_scheduler is False
    args = webui.build_parser().parse_args(["--no-sync-scheduler"])
    assert args.no_sync_scheduler is True


def test_probe_opens_browser_once_service_is_ready(monkeypatch) -> None:
    """服务监听就绪后探测成功并调用 webbrowser.open_new_tab 恰好一次。"""
    opened: list[str] = []
    monkeypatch.setattr(webui.webbrowser, "open_new_tab", lambda url: opened.append(url) or True)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')

        def log_message(self, *args):  # noqa: N802
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        webui._open_browser_when_ready(
            f"http://127.0.0.1:{port}/", timeout=5.0
        )
    finally:
        server.shutdown()
        server.server_close()

    assert len(opened) == 1
    assert opened[0].endswith("/")


def test_probe_gives_up_gracefully_when_no_service(monkeypatch) -> None:
    """无服务监听时探测超时放弃：不唤起浏览器、不抛异常。"""
    opened: list[str] = []
    monkeypatch.setattr(webui.webbrowser, "open_new_tab", lambda url: opened.append(url) or True)

    # 占用一个空闲端口但无服务监听
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    free_port = sock.getsockname()[1]
    sock.close()

    webui._open_browser_when_ready(f"http://127.0.0.1:{free_port}/", timeout=1.0)
    assert opened == []


def test_probe_accepts_http_error_as_readiness(monkeypatch) -> None:
    """端口已监听但返回 404 等错误码同样视为就绪（仅探测连通性）。"""
    opened: list[str] = []
    monkeypatch.setattr(webui.webbrowser, "open_new_tab", lambda url: opened.append(url) or True)

    class NotFoundHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(404)
            self.end_headers()

        def log_message(self, *args):  # noqa: N802
            return

    server = HTTPServer(("127.0.0.1", 0), NotFoundHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        webui._open_browser_when_ready(f"http://127.0.0.1:{port}/", timeout=5.0)
    finally:
        server.shutdown()
        server.server_close()

    assert len(opened) == 1
