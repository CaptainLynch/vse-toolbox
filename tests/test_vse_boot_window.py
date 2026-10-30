# -*- coding: utf-8 -*-
"""W16-02 三级回退开窗契约（pywebview → Edge app → 默认浏览器）。"""

from __future__ import annotations

import builtins
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import vse_boot.supervisor as supervisor


def _layout(tmp_path: Path):
    return types.SimpleNamespace(state_dir=tmp_path / "state")


def test_window_prefers_pywebview_when_available(monkeypatch, tmp_path):
    """pywebview 可用时用它开窗（后台线程），不再落 Edge/浏览器。"""
    fake = MagicMock()
    monkeypatch.setitem(sys.modules, "webview", fake)
    edge = MagicMock()
    monkeypatch.setattr(supervisor, "_edge_path", lambda: edge)
    opened = []
    monkeypatch.setattr(supervisor.webbrowser, "open", lambda url: opened.append(url))

    supervisor.open_window("http://127.0.0.1:5000/", _layout(tmp_path))
    fake.create_window.assert_called_once()
    fake.start.assert_called_once()
    assert opened == []


def test_window_falls_back_to_edge_when_pywebview_missing(monkeypatch, tmp_path):
    import builtins

    monkeypatch.setitem(sys.modules, "webview", None)
    # 让 import webview 抛 ImportError（sys.modules 里是 None 不足以触发 import 语义）
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "webview":
            raise ImportError("no pywebview")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    edge = MagicMock()
    monkeypatch.setattr(supervisor, "_edge_path", lambda: edge)

    popen = MagicMock()
    monkeypatch.setattr(supervisor.subprocess, "Popen", popen)
    supervisor.open_window("http://127.0.0.1:5000/", _layout(tmp_path))
    popen.assert_called_once()
    assert "--app=" in popen.call_args[0][0][1]


def test_window_falls_back_to_browser_when_edge_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(supervisor, "_edge_path", lambda: None)
    opened = []
    monkeypatch.setattr(supervisor.webbrowser, "open", lambda url: opened.append(url))

    supervisor._open_edge_or_browser("http://127.0.0.1:5000/", _layout(tmp_path))
    assert opened == ["http://127.0.0.1:5000/"]


def test_window_webview_runtime_failure_falls_back_to_edge(monkeypatch, tmp_path):
    """webview.start() 运行期失败（无图形环境等）也要落到 Edge/浏览器。"""
    fake = MagicMock()
    fake.start.side_effect = RuntimeError("no display")
    monkeypatch.setitem(sys.modules, "webview", fake)
    edge = MagicMock()
    monkeypatch.setattr(supervisor, "_edge_path", lambda: edge)

    import time

    popen = MagicMock()
    monkeypatch.setattr(supervisor.subprocess, "Popen", popen)
    supervisor.open_window("http://127.0.0.1:5000/", _layout(tmp_path))
    deadline = time.monotonic() + 5
    while not popen.called and time.monotonic() < deadline:
        time.sleep(0.05)
    assert popen.called, "webview 失败后未回退到 Edge"
    assert "--app=" in popen.call_args[0][0][1]
