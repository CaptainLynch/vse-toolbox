# -*- coding: utf-8 -*-
"""DSH-V2-08：可离线运行的真实浏览器关键路径夹具。

为什么不用 Playwright / Selenium
================================
本机没有 Playwright，``websocket`` / ``selenium`` 虽然能 import 但不在
``requirements.txt`` 里，不能成为测试依赖。这里改用**本机已有**的
Edge/Chrome DevTools 协议：

1. 以 ``--headless=new --remote-debugging-port=0 --user-data-dir=<tmp>`` 启动
   浏览器，从 profile 目录里的 ``DevToolsActivePort`` 读真实端口；
2. 由一个内嵌在本模块、运行时写到 ``tmp_path`` 的 **Node CDP 驱动脚本**，用
   Node >= 22 自带的全局 ``WebSocket`` / ``fetch`` 与浏览器对话；
3. 页面里执行的是真实 ES Module、真实 DOM、真实鼠标事件
   （``Input.dispatchMouseEvent``）与真实文本输入（``Input.insertText``）。

因此不新增依赖、不联网下载、不进入生产依赖；断言读取渲染后的 DOM 与浏览器
console，而不是源码文本。

被测服务
========
测试进程内用真实 ``create_app``（``DatabaseManager`` / ``app_root`` monkeypatch
到 ``tmp_path``）+ werkzeug ``make_server`` 起 127.0.0.1 随机端口。浏览器通过
启动票据 ``/?boot=<票据>`` 按 ``web.security`` 的真实流程换会话 Cookie；票据是
测试进程生成的合成值，不写入日志/文档，诊断输出统一脱敏为 ``boot=<redacted>``。
Aras / TDC / 帆软 / 邮件等外部系统完全不参与，数据只来自临时 SQLite。

超时
====
``pytest-timeout`` 不在依赖里，超时分三层：CDP 单步 30 秒
（``DEFAULT_STEP_TIMEOUT_MS``）、单条用例的浏览器操作总预算 120 秒
（``PAGE_TIME_BUDGET_SECONDS``）、浏览器启动 30 秒。整文件目标 < 3 分钟。
"""

from __future__ import annotations

import collections
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence

import pytest
from werkzeug.serving import make_server

import web.app as web_app
from tests.browser.test_browser_channel import BrowserChannel, find_browser_channel

__all__ = [
    "BrowserPage",
    "BrowserSession",
    "BrowserStartError",
    "BrowserDriverError",
    "LiveServer",
    "assert_no_console_errors",
    "find_node",
    "resolve_browser_channel",
    "browser",
    "page",
    "server",
]

#: 单步 CDP 操作上限（任务要求：单步不超过 30 秒）。
DEFAULT_STEP_TIMEOUT_MS = 30_000
#: 单条用例的浏览器操作总预算；给整文件 3 分钟留出余量。
PAGE_TIME_BUDGET_SECONDS = 120
#: 浏览器从启动到写出 DevToolsActivePort 的上限。
BROWSER_START_TIMEOUT_SECONDS = 30
#: Node 全局 WebSocket/fetch 的最低版本（Node 22 LTS 起稳定）。
MIN_NODE_MAJOR = 22

_EOF = object()

#: 诊断里出现的票据一律脱敏；票据本身绝不进入日志/文档/断言消息。
_BOOT_TICKET_RE = re.compile(r"([?&]boot=)[^&#\s]*")


def _redact_boot_ticket(text: str) -> str:
    return _BOOT_TICKET_RE.sub(r"\1<redacted>", str(text))


# ── 探测：复用既有浏览器通道探测，只补「显式指定但不存在」的语义 ─────────────


def resolve_browser_channel() -> BrowserChannel:
    """复用 ``test_browser_channel.find_browser_channel``，并让显式覆盖更严格。

    ``find_browser_channel`` 在 ``VSE_BROWSER_PATH`` 指向不存在文件时会静默回落到
    自动探测；对夹具来说这会让「显式指定错了」被隐藏。这里把该情况如实报告为
    不可用，跳过原因才能写清缺的是什么。
    """
    explicit = os.environ.get("VSE_BROWSER_PATH", "").strip().strip('"')
    if explicit and not Path(explicit).is_file():
        return BrowserChannel(
            name="Custom Browser",
            path=None,
            available=False,
            reason=f"环境变量 VSE_BROWSER_PATH 指向的文件不存在：{explicit}",
        )
    return find_browser_channel()


def find_node() -> tuple[Optional[str], str]:
    """返回 (node 可执行文件, 不可用原因)。缺失或版本过低时两者互斥。"""
    explicit = os.environ.get("VSE_NODE_PATH", "").strip().strip('"')
    if explicit:
        if not Path(explicit).is_file():
            return None, f"环境变量 VSE_NODE_PATH 指向的文件不存在：{explicit}"
        candidate = explicit
    else:
        candidate = shutil.which("node")
        if not candidate:
            return None, "未在 PATH 中找到 node"
    try:
        result = subprocess.run(
            [candidate, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"无法执行 {candidate} --version：{exc}"
    match = re.match(r"v(\d+)\.", (result.stdout or "").strip())
    if result.returncode != 0 or not match:
        return None, f"{candidate} --version 输出无法识别：{(result.stdout or result.stderr or '').strip()[:120]}"
    major = int(match.group(1))
    if major < MIN_NODE_MAJOR:
        return None, f"Node 版本过低（{result.stdout.strip()} < v{MIN_NODE_MAJOR}，需要内置全局 WebSocket/fetch）"
    return candidate, ""


# ── 内嵌 Node CDP 驱动（只使用 Node 内置能力） ──────────────────────────────

NODE_CDP_DRIVER = r'''
// v2-cdp-driver.mjs — DSH-V2-08 离线 CDP 驱动（无第三方依赖）。
// 用法: node v2-cdp-driver.mjs <debug-port>
// stdin : 每行一条 JSON 命令 {"id":1,"method":"goto","params":{...}}
// stdout: 每行一条 JSON 响应 {"id":1,"ok":true,"result":{...}}
//        或 {"id":1,"ok":false,"error":"..."}
// 只使用 Node >= 22 内置的全局 fetch / WebSocket，不联网、不下载。

import readline from "node:readline";

const port = Number(process.argv[2] || 0);
if (!Number.isInteger(port) || port <= 0) {
  process.stdout.write(JSON.stringify({ fatal: "缺少 DevTools 端口参数" }) + "\n");
  process.exit(2);
}

const ORIGIN = `http://127.0.0.1:${port}`;
const DEFAULT_TIMEOUT = 30000;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function writeLine(payload) {
  process.stdout.write(JSON.stringify(payload) + "\n");
}

function describeException(details) {
  if (!details) return "未知异常";
  const exception = details.exception || {};
  return String(exception.description || exception.value || details.text || "未知异常");
}

function formatRemoteObject(object) {
  if (!object) return "";
  if (Object.prototype.hasOwnProperty.call(object, "value")) {
    const value = object.value;
    return typeof value === "string" ? value : JSON.stringify(value);
  }
  return String(object.description || object.unserializableValue || object.type || "");
}

async function fetchJson(url, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status} ${url}`);
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

async function findPageTarget() {
  const deadline = Date.now() + 20000;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      const targets = await fetchJson(`${ORIGIN}/json/list`, 5000);
      const page = (targets || []).find((item) => item.type === "page" && item.webSocketDebuggerUrl);
      if (page) return page;
      lastError = new Error("页面 target 尚未就绪");
    } catch (error) {
      lastError = error;
    }
    await sleep(150);
  }
  throw new Error(`连接浏览器 DevTools 失败：${lastError ? lastError.message : "超时"}`);
}

class Cdp {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 0;
    this.pending = new Map();
    this.errors = [];
    this.closed = false;
    socket.addEventListener("message", (event) => this.onMessage(event));
    socket.addEventListener("close", () => {
      this.closed = true;
      for (const pending of this.pending.values()) {
        clearTimeout(pending.timer);
        pending.reject(new Error("CDP 连接已关闭"));
      }
      this.pending.clear();
    });
  }

  onMessage(event) {
    const text = typeof event.data === "string" ? event.data : Buffer.from(event.data).toString("utf8");
    let message;
    try {
      message = JSON.parse(text);
    } catch (error) {
      return;
    }
    if (message.id && this.pending.has(message.id)) {
      const pending = this.pending.get(message.id);
      this.pending.delete(message.id);
      clearTimeout(pending.timer);
      if (message.error) pending.reject(new Error(`${pending.method}: ${message.error.message}`));
      else pending.resolve(message.result || {});
      return;
    }
    if (message.method) this.onEvent(message);
  }

  onEvent(message) {
    const params = message.params || {};
    if (message.method === "Runtime.consoleAPICalled") {
      if (params.type !== "error" && params.type !== "assert") return;
      const text = (params.args || []).map(formatRemoteObject).join(" ");
      this.errors.push({ level: params.type, source: "console", text });
    } else if (message.method === "Runtime.exceptionThrown") {
      this.errors.push({ level: "error", source: "exception", text: describeException(params.exceptionDetails) });
    } else if (message.method === "Log.entryAdded") {
      const entry = params.entry || {};
      if (entry.level !== "error") return;
      const suffix = entry.url ? ` (${entry.url})` : "";
      this.errors.push({ level: "error", source: entry.source || "log", text: `${entry.text || ""}${suffix}` });
    }
  }

  send(method, params = {}, timeoutMs = DEFAULT_TIMEOUT) {
    if (this.closed) return Promise.reject(new Error("CDP 连接已关闭"));
    const id = ++this.nextId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP 超时：${method}（${timeoutMs}ms）`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer, method });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression, timeoutMs = DEFAULT_TIMEOUT) {
    const result = await this.send(
      "Runtime.evaluate",
      { expression, returnByValue: true, awaitPromise: true, userGesture: true },
      timeoutMs,
    );
    if (result.exceptionDetails) throw new Error(`页面脚本异常：${describeException(result.exceptionDetails)}`);
    return result.result ? result.result.value : undefined;
  }
}

async function poll(cdp, expression, timeoutMs, label) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      const value = await cdp.evaluate(expression, Math.max(1000, Math.min(5000, deadline - Date.now())));
      if (value) return value;
    } catch (error) {
      lastError = error;
    }
    await sleep(100);
  }
  const detail = lastError ? `；最后错误：${lastError.message}` : "";
  throw new Error(`等待超时：${label}（${timeoutMs}ms）${detail}`);
}

function rectExpression(selector, text) {
  const wanted = text === undefined ? null : text;
  return (
    "(() => {" +
    "const selector = " + JSON.stringify(selector) + ";" +
    "const wanted = " + JSON.stringify(wanted) + ";" +
    "const normalize = (value) => String(value || '').trim();" +
    "const nodes = Array.from(document.querySelectorAll(selector));" +
    "const visible = nodes.filter((node) => node.getClientRects().length > 0);" +
    "let target = null;" +
    "if (wanted === null) { target = visible.find((node) => !node.disabled) || null; }" +
    "else {" +
    "  target = visible.find((node) => normalize(node.textContent) === wanted) || null;" +
    "  if (!target) target = visible.find((node) => normalize(node.textContent).includes(wanted)) || null;" +
    "}" +
    "if (!target) return { found: false, candidates: visible.map((node) => normalize(node.textContent).slice(0, 40)).slice(0, 12) };" +
    "target.scrollIntoView({ block: 'center', inline: 'center' });" +
    "const rect = target.getBoundingClientRect();" +
    "if (rect.width <= 0 || rect.height <= 0) return { found: false, candidates: ['元素尺寸为 0'] };" +
    "return { found: true, x: rect.left + rect.width / 2, y: rect.top + rect.height / 2," +
    "  text: normalize(target.textContent).slice(0, 80), tag: target.tagName.toLowerCase()," +
    "  disabled: Boolean(target.disabled) };" +
    "})()"
  );
}

async function dispatchClick(cdp, x, y) {
  await cdp.send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "none", clickCount: 0 });
  await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", buttons: 1, clickCount: 1 });
  await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", buttons: 0, clickCount: 1 });
  await sleep(40);
}

async function clickTarget(cdp, params) {
  const selector = params.selector || "button, a, [role=button]";
  const text = params.text === undefined ? null : params.text;
  const rect = await cdp.evaluate(rectExpression(selector, text));
  if (!rect || !rect.found) {
    const candidates = JSON.stringify((rect && rect.candidates) || []);
    throw new Error(`找不到可点击元素：selector=${selector} text=${JSON.stringify(text)} 候选=${candidates}`);
  }
  if (rect.disabled) throw new Error(`目标元素被禁用：${rect.text}`);
  await dispatchClick(cdp, rect.x, rect.y);
  return { text: rect.text, tag: rect.tag, x: rect.x, y: rect.y };
}

async function typeInto(cdp, params) {
  const selector = params.selector;
  const text = String(params.text || "");
  const rect = await cdp.evaluate(rectExpression(selector, null));
  if (!rect || !rect.found) throw new Error(`找不到输入框：${selector}`);
  await dispatchClick(cdp, rect.x, rect.y);
  const focused = await cdp.evaluate(
    "(() => { const el = document.querySelector(" + JSON.stringify(selector) + ");" +
    " if (!el) return false; el.focus(); if (typeof el.select === 'function') el.select();" +
    " return document.activeElement === el; })()",
  );
  if (!focused) throw new Error(`输入框未能获得焦点：${selector}`);
  await cdp.send("Input.insertText", { text });
  const value = await cdp.evaluate(
    "(() => { const el = document.querySelector(" + JSON.stringify(selector) + "); return el ? String(el.value || '') : ''; })()",
  );
  if (text && String(value || "").indexOf(text) === -1) {
    for (const char of text) {
      await cdp.send("Input.dispatchKeyEvent", { type: "char", text: char });
    }
  }
  await sleep(40);
  return { selector, length: text.length };
}

const handlers = {
  async goto(params, cdp) {
    const timeoutMs = params.timeout_ms || DEFAULT_TIMEOUT;
    const result = await cdp.send("Page.navigate", { url: params.url }, timeoutMs);
    if (result.errorText) throw new Error(`页面导航失败：${result.errorText}`);
    await poll(cdp, "document.readyState === 'complete'", timeoutMs, "document.readyState === complete");
    return { url: params.url };
  },

  async eval(params, cdp) {
    return { value: await cdp.evaluate(params.expression, params.timeout_ms || DEFAULT_TIMEOUT) };
  },

  async wait_for_selector(params, cdp) {
    const expression = "Boolean(document.querySelector(" + JSON.stringify(params.selector) + "))";
    await poll(cdp, expression, params.timeout_ms || DEFAULT_TIMEOUT, `选择器 ${params.selector}`);
    return { selector: params.selector };
  },

  async wait_for_function(params, cdp) {
    const value = await poll(cdp, params.expression, params.timeout_ms || DEFAULT_TIMEOUT, "页面条件");
    return { value: value === undefined ? true : value };
  },

  async click(params, cdp) {
    return await clickTarget(cdp, params);
  },

  async type(params, cdp) {
    return await typeInto(cdp, params);
  },

  async console_errors(_params, cdp) {
    return { errors: cdp.errors.slice() };
  },

  async clear_console(_params, cdp) {
    cdp.errors.length = 0;
    return {};
  },

  async cookies(params, cdp) {
    const result = await cdp.send("Network.getCookies", { urls: params.urls || [] });
    return { cookies: result.cookies || [] };
  },

  async snapshot(params, cdp) {
    const limit = Math.max(200, Math.min(20000, Number(params.max) || 4000));
    return await cdp.evaluate(
      "(() => { const host = document.querySelector('#plugin-host');" +
      " return { url: location.href, title: document.title," +
      " html: document.body ? document.body.outerHTML.slice(0, " + limit + ") : ''," +
      " host: host ? host.outerHTML.slice(0, " + limit + ") : ''," +
      " text: document.body ? String(document.body.innerText || '').slice(0, 2000) : '' }; })()",
    );
  },

  async shutdown(_params, cdp) {
    try {
      await cdp.send("Browser.close", {}, 5000);
    } catch (error) {
      // 浏览器可能已经自行退出；清理阶段不再上抛。
    }
    return { closed: true };
  },

  async close(_params, _cdp) {
    return { closed: true };
  },
};

async function main() {
  const target = await findPageTarget();
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("WebSocket 连接超时")), 15000);
    socket.addEventListener("open", () => {
      clearTimeout(timer);
      resolve();
    });
    socket.addEventListener("error", (event) => {
      clearTimeout(timer);
      reject(new Error(`WebSocket 错误：${event.message || "unknown"}`));
    });
  });

  const cdp = new Cdp(socket);
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Log.enable");
  await cdp.send("Network.enable");
  writeLine({ ready: true, url: target.url, title: target.title || "" });

  const lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  for await (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let command;
    try {
      command = JSON.parse(trimmed);
    } catch (error) {
      writeLine({ id: null, ok: false, error: "命令不是合法 JSON" });
      continue;
    }
    const handler = handlers[command.method];
    if (!handler) {
      writeLine({ id: command.id, ok: false, error: `未知命令：${command.method}` });
      continue;
    }
    try {
      const result = await handler(command.params || {}, cdp);
      writeLine({ id: command.id, ok: true, result: result === undefined ? null : result });
    } catch (error) {
      writeLine({ id: command.id, ok: false, error: String((error && error.message) || error) });
    }
    if (command.method === "close") break;
  }

  try {
    socket.close();
  } catch (error) {
    // 忽略关闭期错误。
  }
  await sleep(20);
  process.exit(0);
}

main().catch((error) => {
  writeLine({ fatal: String((error && error.message) || error) });
  process.exit(1);
});
'''


# ── 异常类型 ────────────────────────────────────────────────────────────────


class BrowserStartError(RuntimeError):
    """浏览器或 CDP 驱动无法启动（真实失败，不是 skip）。"""


class BrowserDriverError(RuntimeError):
    """CDP 驱动命令失败/超时；消息里带 DOM 片段与 console 日志。"""


# ── 页面驱动：goto / eval / click / wait_for_selector / console_errors ──────


@dataclass
class ClickResult:
    """一次真实鼠标点击命中目标的记录。"""

    text: str = ""
    tag: str = ""
    x: float = 0.0
    y: float = 0.0


@dataclass
class BrowserPage:
    """真实浏览器页面：每个方法都是一次同步的 CDP 往返。

    ``console_errors()`` 返回自页面打开以来浏览器上报的 error 级日志
    （``Runtime.consoleAPICalled`` / ``Runtime.exceptionThrown`` /
    ``Log.entryAdded`` 三路合并）。
    """

    process: subprocess.Popen
    step_timeout_ms: int = DEFAULT_STEP_TIMEOUT_MS
    time_budget_seconds: int = PAGE_TIME_BUDGET_SECONDS
    _responses: queue.Queue = field(default_factory=queue.Queue)
    _stderr: collections.deque = field(default_factory=lambda: collections.deque(maxlen=200))
    _next_id: Iterator[int] = field(default_factory=lambda: iter(range(1, 1_000_000)))
    _closed: bool = False
    _started_at: float = field(default_factory=time.monotonic)
    _ready: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        threading.Thread(target=self._pump_stdout, name="v2-cdp-stdout", daemon=True).start()
        threading.Thread(target=self._pump_stderr, name="v2-cdp-stderr", daemon=True).start()
        ready = self._wait_message(BROWSER_START_TIMEOUT_SECONDS, "CDP 驱动就绪")
        if "fatal" in ready:
            raise BrowserStartError(f"CDP 驱动启动失败：{ready['fatal']}\n{self._stderr_tail()}")
        if not ready.get("ready"):
            raise BrowserStartError(f"CDP 驱动未报告就绪：{ready}\n{self._stderr_tail()}")
        self._ready = ready

    # 生命周期 ────────────────────────────────────────────────────────────

    def _pump_stdout(self) -> None:
        stream = self.process.stdout
        if stream is None:
            self._responses.put(_EOF)
            return
        for line in stream:
            text = line.strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except json.JSONDecodeError:
                self._stderr.append(f"[非 JSON 输出] {text[:400]}")
                continue
            self._responses.put(message)
        self._responses.put(_EOF)

    def _pump_stderr(self) -> None:
        stream = self.process.stderr
        if stream is None:
            return
        for line in stream:
            self._stderr.append(line.rstrip())

    def _stderr_tail(self, limit: int = 4000) -> str:
        text = "\n".join(self._stderr)
        return text[-limit:] if text else "（驱动无 stderr 输出）"

    def _wait_message(self, timeout: float, label: str) -> dict:
        try:
            message = self._responses.get(timeout=timeout)
        except queue.Empty as exc:
            raise BrowserDriverError(f"等待 {label} 超时（{timeout:.0f}s）\n{self._stderr_tail()}") from exc
        if message is _EOF:
            raise BrowserStartError(f"CDP 驱动在 {label} 前退出\n{self._stderr_tail()}")
        return message

    def _write_command(self, method: str, params: Optional[dict]) -> int:
        command_id = next(self._next_id)
        payload = json.dumps({"id": command_id, "method": method, "params": params or {}}, ensure_ascii=False)
        stream = self.process.stdin
        if stream is None:
            raise BrowserDriverError(f"CDP 驱动 stdin 不可用（{method}）\n{self._stderr_tail()}")
        try:
            stream.write(payload + "\n")
            stream.flush()
        except (OSError, ValueError) as exc:
            raise BrowserDriverError(f"无法向 CDP 驱动写入命令（{method}）：{exc}\n{self._stderr_tail()}") from exc
        return command_id

    def _call_once(self, method: str, params: Optional[dict] = None, timeout_ms: Optional[int] = None) -> dict:
        timeout = (timeout_ms or self.step_timeout_ms) / 1000.0
        command_id = self._write_command(method, params)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BrowserDriverError(f"CDP 命令超时（{method}，{timeout:.0f}s）\n{self._stderr_tail()}")
            message = self._wait_message(remaining, f"命令 {method}")
            if message.get("id") != command_id:
                continue  # 忽略迟到/无关响应；本驱动同一时刻只允许一条在途命令
            if not message.get("ok"):
                raise BrowserDriverError(f"CDP 命令失败（{method}）：{message.get('error')}")
            return message.get("result") or {}

    def _call(self, method: str, params: Optional[dict] = None, timeout_ms: Optional[int] = None) -> dict:
        spent = time.monotonic() - self._started_at
        if spent > self.time_budget_seconds:
            raise BrowserDriverError(
                f"单条用例的浏览器操作预算已用尽（{spent:.1f}s > {self.time_budget_seconds}s），"
                f"拒绝继续执行 {method}\n{self._stderr_tail()}"
            )
        try:
            return self._call_once(method, params, timeout_ms)
        except BrowserDriverError as exc:
            raise BrowserDriverError(f"{exc}\n{self.diagnose('页面现场')}") from exc

    def diagnose(self, message: str) -> str:
        """把 DOM 片段与 console 日志拼进断言消息，便于定位失败。"""
        parts = [message]
        try:
            snapshot = self._call_once("snapshot", {"max": 4000}, timeout_ms=5000)
            url = _redact_boot_ticket(snapshot.get("url") or "")
            parts.append(
                "URL: {url}\n标题: {title}\n#plugin-host 片段:\n{host}\n页面文本: {text}".format(
                    url=url,
                    title=snapshot.get("title") or "",
                    host=snapshot.get("host") or "（空）",
                    text=(snapshot.get("text") or "（空）")[:1500],
                )
            )
        except (BrowserDriverError, BrowserStartError) as exc:
            parts.append(f"DOM 快照不可用：{exc}")
        try:
            errors = self._call_once("console_errors", {}, timeout_ms=5000).get("errors") or []
            rendered = json.dumps(errors, ensure_ascii=False, indent=2) if errors else "（空）"
            parts.append(f"浏览器 console error 日志: {rendered}")
        except (BrowserDriverError, BrowserStartError) as exc:
            parts.append(f"console 日志不可用：{exc}")
        return "\n".join(parts)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._write_command("shutdown", {})
        except BrowserDriverError:
            pass
        try:
            if self.process.stdin is not None:
                self.process.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    # 公共 API ────────────────────────────────────────────────────────────

    @property
    def ready_info(self) -> dict:
        return dict(self._ready)

    def goto(self, url: str, timeout_ms: Optional[int] = None) -> None:
        """导航并等到 ``document.readyState === 'complete'``。"""
        self._call("goto", {"url": url, "timeout_ms": timeout_ms or self.step_timeout_ms}, timeout_ms)

    def eval(self, expression: str, timeout_ms: Optional[int] = None) -> Any:
        """在页面里求值（``returnByValue``），返回可 JSON 序列化的结果。"""
        result = self._call(
            "eval", {"expression": expression, "timeout_ms": timeout_ms or self.step_timeout_ms}, timeout_ms
        )
        return result.get("value")

    def wait_for_selector(self, selector: str, timeout_ms: Optional[int] = None) -> None:
        self._call(
            "wait_for_selector", {"selector": selector, "timeout_ms": timeout_ms or self.step_timeout_ms}, timeout_ms
        )

    def wait_for_function(self, expression: str, timeout_ms: Optional[int] = None) -> Any:
        result = self._call(
            "wait_for_function", {"expression": expression, "timeout_ms": timeout_ms or self.step_timeout_ms},
            timeout_ms,
        )
        return result.get("value")

    def click(self, selector: Optional[str] = None, text: Optional[str] = None) -> ClickResult:
        """在元素中心派发真实鼠标事件（按下/抬起），返回命中的文本与坐标。"""
        params: dict[str, Any] = {}
        if selector is not None:
            params["selector"] = selector
        if text is not None:
            params["text"] = text
        result = self._call("click", params)
        return ClickResult(
            text=str(result.get("text") or ""),
            tag=str(result.get("tag") or ""),
            x=float(result.get("x") or 0.0),
            y=float(result.get("y") or 0.0),
        )

    def type_text(self, selector: str, text: str) -> None:
        """先真实点击聚焦，再用 ``Input.insertText`` 输入（失败时逐字符回退）。"""
        self._call("type", {"selector": selector, "text": text})

    def console_errors(self) -> list[dict]:
        return list(self._call("console_errors", {}).get("errors") or [])

    def clear_console(self) -> None:
        self._call("clear_console", {})

    def cookies(self, urls: Sequence[str]) -> list[dict]:
        return list(self._call("cookies", {"urls": list(urls)}).get("cookies") or [])

    def snapshot(self, max_chars: int = 4000) -> dict:
        return self._call_once("snapshot", {"max": max_chars}, timeout_ms=5000)


# ── 浏览器进程管理：只结束本测试启动的进程树 ────────────────────────────────


def _browser_arguments(profile_dir: Path) -> list[str]:
    """离线无头浏览器的启动参数。

    ``--host-resolver-rules`` 把除 127.0.0.1 之外的所有主机解析为失败，
    从浏览器层证明「不访问真实内网/外网」。
    """
    return [
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-component-extensions-with-background-pages",
        "--disable-default-apps",
        "--disable-sync",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-domain-reliability",
        "--disable-client-side-phishing-detection",
        "--metrics-recording-only",
        "--mute-audio",
        "--hide-scrollbars",
        "--window-size=1280,900",
        "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
        f"--user-data-dir={profile_dir}",
        "--remote-debugging-port=0",
        "about:blank",
    ]


def _read_debug_port(profile_dir: Path, process: subprocess.Popen, log_path: Path) -> int:
    port_file = profile_dir / "DevToolsActivePort"
    deadline = time.monotonic() + BROWSER_START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise BrowserStartError(
                f"浏览器进程提前退出（退出码 {process.returncode}）：{_tail_file(log_path)}"
            )
        if port_file.is_file():
            try:
                first_line = port_file.read_text(encoding="utf-8", errors="replace").splitlines()[0].strip()
            except (OSError, IndexError):
                first_line = ""
            if first_line.isdigit():
                return int(first_line)
        time.sleep(0.1)
    raise BrowserStartError(
        f"等待 DevToolsActivePort 超时（{BROWSER_START_TIMEOUT_SECONDS}s）：{_tail_file(log_path)}"
    )


def _tail_file(path: Path, limit: int = 4000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"（无法读取 {path.name}: {exc}）"
    return text[-limit:] if text else "（空）"


def _remove_profile(profile_dir: Path) -> None:
    """删除临时 profile；Windows 上文件句柄释放有延迟，有限重试后尽力清理。"""
    for _ in range(20):
        try:
            shutil.rmtree(profile_dir)
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.25)
    shutil.rmtree(profile_dir, ignore_errors=True)


@dataclass
class BrowserSession:
    """一次测试专属的浏览器实例 + CDP 驱动 + 页面驱动。"""

    channel: BrowserChannel
    process: subprocess.Popen
    profile_dir: Path
    log_path: Path
    log_handle: Any
    page: BrowserPage
    _closed: bool = False

    @classmethod
    def start(cls, *, channel: BrowserChannel, node: str, tmp_path: Path) -> "BrowserSession":
        assert channel.path is not None
        profile_dir = tmp_path / "browser-profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        log_path = tmp_path / "browser-stderr.log"
        log_handle = open(log_path, "wb")
        command = [str(channel.path), *_browser_arguments(profile_dir)]
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=log_handle,
            )
        except BaseException:
            log_handle.close()
            _remove_profile(profile_dir)
            raise
        driver: Optional[subprocess.Popen] = None
        try:
            port = _read_debug_port(profile_dir, process, log_path)
            driver_script = tmp_path / "v2_cdp_driver.mjs"
            driver_script.write_text(NODE_CDP_DRIVER, encoding="utf-8")
            driver = subprocess.Popen(
                [node, str(driver_script), str(port)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            page = BrowserPage(process=driver)
            return cls(
                channel=channel,
                process=process,
                profile_dir=profile_dir,
                log_path=log_path,
                log_handle=log_handle,
                page=page,
            )
        except BaseException:
            if driver is not None:
                try:
                    driver.kill()
                    driver.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            _stop_process_tree(process)
            try:
                log_handle.close()
            except OSError:
                pass
            _remove_profile(profile_dir)
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.page.close()
        finally:
            _stop_process_tree(self.process)
            try:
                self.log_handle.close()
            except OSError:
                pass
            _remove_profile(self.profile_dir)

    def browser_stderr_tail(self, limit: int = 4000) -> str:
        return _tail_file(self.log_path, limit)


def _stop_process_tree(process: subprocess.Popen) -> None:
    """结束**本测试自己启动**的浏览器进程及其子进程。

    优先让浏览器自行退出（teardown 已先发 CDP ``Browser.close``）；仍在运行
    时按**本进程 PID 的进程树**结束（``taskkill /T``），绝不按进程名匹配任何
    其他 Edge/Chrome 实例。
    """
    try:
        process.wait(timeout=10)
        return
    except subprocess.TimeoutExpired:
        pass
    if sys.platform == "win32" and process.poll() is None:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


# ── 被测服务：真实 create_app + 回环随机端口 ────────────────────────────────


@dataclass
class LiveServer:
    """测试进程内真实 HTTP 服务；``launch_url`` 带一次性启动票据。"""

    app: Any
    server: Any
    security: Any
    base_url: str
    #: 票据是测试进程生成的合成值；``repr=False`` 防止 pytest 在失败时把它打进报告。
    token: str = field(repr=False)

    @property
    def launch_url(self) -> str:
        """启动器 URL：``/?boot=<票据>``（票据为测试进程生成的合成值）。"""
        return f"{self.base_url}/?boot={self.token}"

    def route_url(self, route: str) -> str:
        """带票据打开指定插件路由（票据交换与 hash 路由同一次导航完成）。"""
        return f"{self.launch_url}{route}"


# ── pytest fixtures ────────────────────────────────────────────────────────


@pytest.fixture()
def browser(tmp_path: Path) -> Iterator[BrowserSession]:
    """启动本机 Edge/Chrome（无头）+ CDP 驱动；缺失时如实 skip。

    skip 原因会写明缺的是浏览器还是 Node、以及如何用 ``VSE_BROWSER_PATH`` /
    ``VSE_NODE_PATH`` 显式指定。release 门禁必须把这种 SKIP 视为失败
    （见 ``docs/refactor-v2/DSH_BROWSER_SETUP.md``）。
    """
    channel = resolve_browser_channel()
    if not channel.available or channel.path is None:
        pytest.skip(
            "缺少可用的真实浏览器，无法运行浏览器关键路径夹具："
            f"{channel.reason}。"
            "请安装 Microsoft Edge 或 Google Chrome，或用环境变量 "
            "VSE_BROWSER_PATH 指向浏览器可执行文件（例如 "
            "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe）后重跑。"
        )
    node, node_reason = find_node()
    if node is None:
        pytest.skip(
            "缺少可用的 Node.js（CDP 驱动需要 >= "
            f"v{MIN_NODE_MAJOR} 的内置 WebSocket/fetch）：{node_reason}。"
            "请安装 Node 后重跑，或用环境变量 VSE_NODE_PATH 指向 node.exe；"
            "浏览器路径仍可用 VSE_BROWSER_PATH 指定。"
        )
    session = BrowserSession.start(channel=channel, node=node, tmp_path=tmp_path)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def page(browser: BrowserSession) -> BrowserPage:
    """页面驱动 API：goto / eval / click / wait_for_selector / console_errors。"""
    return browser.page


@pytest.fixture()
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, browser: BrowserSession) -> Iterator[LiveServer]:
    """真实 ``create_app`` + 回环随机端口；数据库与数据目录隔离到 ``tmp_path``。

    依赖 ``browser`` 是有意为之：启动票据 TTL 只有 10 秒，浏览器必须先就绪，
    票据签发后才能立刻在用例里导航交换（不放大生产 TTL）。
    """
    from core.db_manager import DatabaseManager

    db = DatabaseManager(db_path=tmp_path / "browser-fixture.db")
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db)
    monkeypatch.setattr(web_app, "app_root", lambda: tmp_path)
    monkeypatch.setattr("core.runtime_paths.app_root", lambda: tmp_path)
    monkeypatch.delenv("VSE_BOOT_TOKEN", raising=False)

    # werkzeug 的访问日志会把 `GET /?boot=<票据>` 原样写进捕获日志；票据不入日志，
    # 这里把访问日志关到 WARNING（只保留真实错误）。
    werkzeug_logger = logging.getLogger("werkzeug")
    previous_level = werkzeug_logger.level
    werkzeug_logger.setLevel(logging.WARNING)
    try:
        app = web_app.create_app()
        app.config.update(TESTING=False)
        httpd = make_server("127.0.0.1", 0, app, threaded=True)
        thread = threading.Thread(target=httpd.serve_forever, name="v2-browser-http", daemon=True)
        thread.start()
        live = LiveServer(
            app=app,
            server=httpd,
            security=app.extensions["local_web_security"],
            base_url=f"http://127.0.0.1:{httpd.server_port}",
            token=app.config["VSE_BOOT_TOKEN"],
        )
        try:
            yield live
        finally:
            httpd.shutdown()
            thread.join(timeout=5)
    finally:
        werkzeug_logger.setLevel(previous_level)


# ── 断言辅助 ────────────────────────────────────────────────────────────────


def assert_no_console_errors(page: BrowserPage, *, allow: Sequence[Any] = ()) -> None:
    """断言浏览器 console 没有 error 级日志（或只含 ``allow`` 里列明的已知项）。

    ``allow`` 的每一项可以是子串，也可以是编译好的正则（``re.Pattern``），
    用于精确放行已列明的已知项，避免「一有 4xx 就整体忽略」。
    """

    def allowed(text: str) -> bool:
        for pattern in allow:
            if isinstance(pattern, re.Pattern):
                if pattern.search(text):
                    return True
            elif str(pattern) in text:
                return True
        return False

    errors = page.console_errors()
    unexpected = [entry for entry in errors if not allowed(str(entry.get("text") or ""))]
    if unexpected:
        rendered = json.dumps(unexpected, ensure_ascii=False, indent=2)
        raise AssertionError(
            "浏览器 console 出现未列明的 error 级日志：\n"
            f"{rendered}\n\n"
            f"{page.diagnose('页面现场')}"
        )
