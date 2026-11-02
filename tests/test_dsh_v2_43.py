# -*- coding: utf-8 -*-
"""DSH-V2-43：两个更新页面的用户可见更新记录（版本/北京时间/说明/回退入口）。

覆盖三层：

1. ``GET /api/host/updates`` 与 ``GET /api/p/settings/app-updates`` 的真实字段形状
   （create_app + conftest 默认已认证客户端，数据目录隔离到 tmp_path）；
2. 真实浏览器 DOM 执行 ``plugins/settings/static/updates.js`` 与
   ``app-updates.js``（tests/browser/v2_fixtures.py 的 Edge/Chrome + CDP 夹具），
   喂入与真实 API 同形状的合成数据；
3. 状态互斥、notes 纯文本、回退入口、managed=false 与失败原位报错。

时间断言按北京时间（Asia/Shanghai）对账，不依赖浏览器语言；页面实现复用
``web/static/host/time-format.js``。
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import web.app as web_app
from tests.browser.v2_fixtures import (  # noqa: F401 - pytest fixture 注入
    browser,
    page,
    server,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

APP_CONTAINER = "v2-43-app"
PLUGIN_CONTAINER = "v2-43-plugin"

ALL_STATES = {
    "未安装",
    "已导入待生效（需重启）",
    "当前生效",
    "试用中",
    "已回退",
    "失败",
}

# ── 真实浏览器夹具：挂载页面模块 + 合成 API 路由 ─────────────────────────────

_MOUNT_JS = r"""
(async () => {
  const spec = __SPEC__;
  const preact = await import("/static/host/vendor/preact-htm.js");
  const mod = await import(spec.module + "?probe=" + Date.now());
  const host = document.createElement("div");
  host.id = spec.container;
  document.body.appendChild(host);
  window.confirm = () => true;
  const calls = [];
  const routes = spec.routes;
  const realFetch = window.fetch.bind(window);
  const respond = (status, payload) => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  });
  window.fetch = async (url, init) => {
    const path = String(url);
    const method = String((init && init.method) || "GET").toUpperCase();
    const route = routes.find((item) => item.path === path && (!item.method || item.method === method));
    if (route) {
      calls.push({ path, method });
      if (route.error) {
        return respond(route.status || 409, { ok: false, error: { message: route.error, type: "http" } });
      }
      return respond(200, { ok: true, data: route.data });
    }
    return realFetch(url, init);
  };
  window.__v243calls = calls;
  const component = spec.component === "default" ? mod.default : mod[spec.component];
  preact.render(preact.h(component, spec.props || {}), host);
  return true;
})()
"""

_ROWS_JS = """
(() => {
  const host = document.querySelector(%s);
  if (!host) return [];
  return Array.from(host.querySelectorAll("[data-version]")).map((row) => ({
    plugin: row.getAttribute("data-plugin"),
    version: row.getAttribute("data-version"),
    state: row.getAttribute("data-state"),
    text: row.textContent,
    chips: Array.from(row.querySelectorAll(".st-chip")).map((chip) => chip.textContent.trim()),
    buttons: Array.from(row.querySelectorAll("button")).map((button) => button.textContent.trim()),
  }));
})()
"""


def _mount(
    page,
    *,
    container: str,
    module: str,
    component: str,
    routes: list[dict],
    props: dict | None = None,
    wait_text: str,
) -> None:
    spec = {
        "container": container,
        "module": module,
        "component": component,
        "routes": routes,
        "props": props or {},
    }
    page.eval(_MOUNT_JS.replace("__SPEC__", json.dumps(spec, ensure_ascii=False)))
    selector = json.dumps("#" + container)
    wanted = json.dumps(wait_text, ensure_ascii=False)
    page.wait_for_function(
        f"(() => {{ const el = document.querySelector({selector});"
        f" return Boolean(el) && el.textContent.includes({wanted}); }})()"
    )


def _rows(page, container: str) -> list[dict]:
    return page.eval(_ROWS_JS % json.dumps("#" + container))


def _beijing_from_naive_local(text: str) -> str:
    """与页面 interpretNaiveTime(text, "local") 同口径：按本机时区解释后换算北京时间。"""
    moment = datetime.strptime(text, "%Y-%m-%d %H:%M:%S").astimezone()
    return (moment.astimezone(timezone.utc) + timedelta(hours=8)).strftime(
        "%Y-%m-%d %H:%M (Asia/Shanghai)"
    )


def _beijing_from_utc(text: str) -> str:
    moment = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (moment + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M (Asia/Shanghai)")


# ── 合成数据：字段名与真实 API 一致（见下方 API 形状测试） ───────────────────

APP_PAYLOAD = {
    "managed": True,
    "current": "2.0.0",
    "previous": "1.9.0",
    "trial": "2.1.0",
    "installed": ["1.8.0", "1.9.0", "2.0.0", "2.1.0", "2.2.0"],
    "staged": ["2.2.0"],
    "available": [
        {
            "file": "vse-app-2.3.0.vsepkg",
            "folder": "C:/Users/demo/Downloads",
            "version": "2.3.0",
            "notes": "修复 <b>登录</b> 问题 & 保持纯文本",
            "sizeKb": 2048,
        },
        {
            "file": "vse-app-2.0.5.vsepkg",
            "folder": "C:/Users/demo/Downloads",
            "version": "2.0.5",
            "notes": "安装失败后仍留在下载文件夹",
            "sizeKb": 1024,
        },
    ],
    "watchDirs": ["C:/Users/demo/Downloads"],
    "events": [
        {"at": "2026-10-24 09:30:00", "kind": "manualRollback", "version": "2.0.0", "fromVersion": "2.1.0"},
        {"at": "2026-10-24 09:00:00", "kind": "staged", "version": "2.2.0", "notes": "待生效 <i>说明</i>"},
        {"at": "2026-10-23 08:00:00", "kind": "installFailed", "version": "app-2.0.5", "reason": "签名无效"},
        {"at": "2026-10-22 07:00:00", "kind": "activated", "version": "2.0.0", "previous": "1.9.0"},
        {"at": "2026-10-20 06:00:00", "kind": "rolledBack", "version": "1.8.0", "reason": "启动失败"},
    ],
}

PLUGIN_PAYLOAD = {
    "active": {"alpha": {"version": "1.2.0", "previous": "1.1.0"}},
    "pending": [{"id": "delta", "version": "2.0.0"}],
    "trustedKeys": ["demo-key"],
    "plugins": [
        {"id": "alpha", "name": "Alpha 插件", "version": "1.2.0", "status": "loaded", "source": "installed"},
        {"id": "beta", "name": "Beta 插件", "version": "0.9.0", "status": "failed", "source": "installed"},
        {"id": "gamma", "name": "Gamma 插件", "version": "1.0.0", "status": "loaded", "source": "bundled"},
    ],
    "events": [
        {"at": "2026-10-24T03:30:00Z", "kind": "activated", "plugin": "alpha", "version": "1.2.0", "previous": "1.1.0"},
        {"at": "2026-10-24T03:00:00Z", "kind": "staged", "plugin": "delta", "version": "2.0.0"},
        {"at": "2026-10-23T02:00:00Z", "kind": "rolled_back", "plugin": "epsilon", "version": "1.0.0", "to": "bundled", "reason": "用户手动回滚"},
        {"at": "2026-10-22T01:00:00Z", "kind": "discarded", "plugin": "zeta"},
        {"at": "2026-10-21T00:00:00Z", "kind": "superseded", "plugin": "eta", "version": "0.5.0", "to": "1.0.0"},
    ],
}


def _app_routes(payload: dict = APP_PAYLOAD, rollback_error: str | None = None) -> list[dict]:
    routes = [{"path": "/api/p/settings/app-updates", "method": "GET", "data": payload}]
    if rollback_error:
        routes.append(
            {
                "path": "/api/p/settings/app-updates/rollback",
                "method": "POST",
                "status": 409,
                "error": rollback_error,
            }
        )
    return routes


# ── 浏览器：程序更新页 ────────────────────────────────────────────────────────


def test_app_updates_records_show_version_beijing_time_notes_and_states(page, server) -> None:  # noqa: F811
    page.goto(server.launch_url)
    _mount(
        page,
        container=APP_CONTAINER,
        module="/plugins/settings/static/app-updates.js",
        component="AppUpdatesCard",
        routes=_app_routes(),
        wait_text="当前生效",
    )
    rows = _rows(page, APP_CONTAINER)
    by_version = {row["version"]: row for row in rows}

    # 六种状态各出现一次，同一版本不会同时出现两种状态。
    assert len(rows) == 6, rows
    assert len(by_version) == 6, rows
    for row in rows:
        assert row["chips"] == [row["state"]], row
        assert row["state"] in ALL_STATES, row
    assert {row["state"] for row in rows} == ALL_STATES
    assert by_version["2.0.0"]["state"] == "当前生效"
    assert by_version["2.1.0"]["state"] == "试用中"
    assert by_version["2.2.0"]["state"] == "已导入待生效（需重启）"
    assert by_version["1.8.0"]["state"] == "已回退"
    # installFailed 的 version 是暂存目录名 app-2.0.5；同一个 2.0.5 不能再显示「未安装」。
    assert by_version["app-2.0.5"]["state"] == "失败"
    assert "2.0.5" not in by_version
    assert by_version["2.3.0"]["state"] == "未安装"

    # 版本 + 北京时间（Asia/Shanghai）+ 面向用户的说明。
    assert "版本 2.2.0" in by_version["2.2.0"]["text"]
    assert _beijing_from_naive_local("2026-10-24 09:00:00") in by_version["2.2.0"]["text"]
    assert "说明：待生效 <i>说明</i>" in by_version["2.2.0"]["text"]
    assert _beijing_from_naive_local("2026-10-23 08:00:00") in by_version["app-2.0.5"]["text"]
    assert "原因：签名无效" in by_version["app-2.0.5"]["text"]
    assert "说明：修复 <b>登录</b> 问题 & 保持纯文本" in by_version["2.3.0"]["text"]
    assert "上一版本 1.9.0（可回退）" in by_version["2.0.0"]["text"]

    # notes 是纯文本：HTML 不被解析成元素，原样出现在 textContent 里。
    assert page.eval(f"document.querySelector('#{APP_CONTAINER}').querySelectorAll('b, i').length") == 0
    assert "<b>登录</b>" in page.eval(f"document.querySelector('#{APP_CONTAINER}').textContent")

    # 回退入口只出现在可回退项（当前生效且有上一版本）；安装/重启入口各归其位。
    assert [row["version"] for row in rows if "回到上一版本" in row["buttons"]] == ["2.0.0"]
    assert [row["version"] for row in rows if "安装并重启" in row["buttons"]] == ["2.3.0"]
    assert [row["version"] for row in rows if "立即重启并更新" in row["buttons"]] == ["2.2.0"]


def test_app_updates_rollback_failure_is_shown_in_place(page, server) -> None:  # noqa: F811
    page.goto(server.launch_url)
    before = page.eval("location.href")
    _mount(
        page,
        container=APP_CONTAINER,
        module="/plugins/settings/static/app-updates.js",
        component="AppUpdatesCard",
        routes=_app_routes(rollback_error="没有可以回滚的上一版本"),
        wait_text="回到上一版本",
    )
    # 首次使用向导是固定遮罩（shell 异步渲染），真实鼠标点击前先移除，避免点到遮罩上。
    page.eval("document.querySelectorAll('.wb-scrim').forEach((el) => el.remove())")
    page.click("button", "回到上一版本")
    page.wait_for_function(
        f"document.querySelector('#{APP_CONTAINER}').textContent.includes('没有可以回滚的上一版本')"
    )
    state = page.eval(
        f"""(() => {{
          const host = document.querySelector('#{APP_CONTAINER}');
          const notice = host.querySelector('[role=status]');
          return {{
            notice: notice ? notice.textContent.trim() : '',
            rows: host.querySelectorAll('[data-version]').length,
            text: host.textContent,
            url: location.href,
          }};
        }})()"""
    )
    # 后端 message 原位显示，页面不跳转、记录不清空。
    assert state["notice"] == "没有可以回滚的上一版本"
    assert state["rows"] == 6
    assert "当前生效" in state["text"]
    assert state["url"] == before


def test_app_updates_unmanaged_shows_message_and_hides_writes(page, server) -> None:  # noqa: F811
    page.goto(server.launch_url)
    _mount(
        page,
        container=APP_CONTAINER,
        module="/plugins/settings/static/app-updates.js",
        component="AppUpdatesCard",
        routes=_app_routes({"managed": False}),
        wait_text="当前不是通过启动器运行",
    )
    state = page.eval(
        f"""(() => {{
          const host = document.querySelector('#{APP_CONTAINER}');
          return {{
            text: host.textContent,
            controls: host.querySelectorAll('button, input, form').length,
            managed: host.querySelector('[data-managed]').getAttribute('data-managed'),
          }};
        }})()"""
    )
    assert "当前不是通过启动器运行" in state["text"]
    assert "安装、重启或回退" in state["text"]
    assert state["controls"] == 0
    assert state["managed"] == "false"


# ── 浏览器：插件更新页 ────────────────────────────────────────────────────────


def test_plugin_updates_records_states_and_rollback_entry(page, server) -> None:  # noqa: F811
    page.goto(server.launch_url)
    before = page.eval("location.href")
    _mount(
        page,
        container=PLUGIN_CONTAINER,
        module="/plugins/settings/static/updates.js",
        component="default",
        props={"plugin": {"id": "settings"}},
        routes=[
            {"path": "/api/host/updates", "method": "GET", "data": PLUGIN_PAYLOAD},
            {"path": "/api/p/settings/app-updates", "method": "GET", "data": {"managed": False}},
        ],
        wait_text="更新记录",
    )
    rows = _rows(page, PLUGIN_CONTAINER)
    by_key = {(row["plugin"], row["version"]): row for row in rows}

    assert len(rows) == 6, rows
    assert len(by_key) == 6, rows
    for row in rows:
        assert row["chips"] == [row["state"]], row
        assert row["state"] in ALL_STATES, row
    assert by_key[("alpha", "1.2.0")]["state"] == "当前生效"
    assert by_key[("delta", "2.0.0")]["state"] == "已导入待生效（需重启）"
    assert by_key[("beta", "0.9.0")]["state"] == "失败"
    assert by_key[("epsilon", "1.0.0")]["state"] == "已回退"
    assert by_key[("eta", "0.5.0")]["state"] == "已回退"
    assert by_key[("zeta", "未记录")]["state"] == "未安装"

    # 插件事件是 UTC（带 Z），页面显示北京时间；事件没有 notes 字段就写「未记录」。
    assert _beijing_from_utc("2026-10-24T03:30:00Z") in by_key[("alpha", "1.2.0")]["text"]
    assert "说明：未记录" in by_key[("alpha", "1.2.0")]["text"]
    assert _beijing_from_utc("2026-10-23T02:00:00Z") in by_key[("epsilon", "1.0.0")]["text"]
    assert "原因：用户手动回滚" in by_key[("epsilon", "1.0.0")]["text"]
    assert "原因：程序升级后改用随包版本 1.0.0" in by_key[("eta", "0.5.0")]["text"]
    assert "已撤销导入，未安装" in by_key[("zeta", "未记录")]["text"]

    # 回退只给「已安装且可回退」的当前生效项；待生效项给撤销。
    assert [row["version"] for row in rows if "回滚" in row["buttons"]] == ["1.2.0"]
    assert [row["version"] for row in rows if "撤销" in row["buttons"]] == ["2.0.0"]

    # 回退失败：后端 message 原位显示，记录不清空、页面不跳转。
    page.eval(
        """(() => {
          window.fetch = async (url) => {
            if (String(url) === "/api/host/updates/alpha/rollback") {
              return {
                ok: false,
                status: 409,
                json: async () => ({ ok: false, error: { message: "该插件没有通过插件包安装的版本", type: "http" } }),
              };
            }
            return { ok: true, status: 200, json: async () => ({ ok: true, data: {} }) };
          };
          return true;
        })()"""
    )
    page.eval("document.querySelectorAll('.wb-scrim').forEach((el) => el.remove())")
    page.click("button", "回滚")
    page.wait_for_function(
        f"document.querySelector('#{PLUGIN_CONTAINER}').textContent.includes('该插件没有通过插件包安装的版本')"
    )
    failed = page.eval(
        f"""(() => {{
          const host = document.querySelector('#{PLUGIN_CONTAINER}');
          const notice = host.querySelector('[role=status]');
          return {{
            notice: notice ? notice.textContent.trim() : '',
            rows: host.querySelectorAll('[data-plugin]').length,
            url: location.href,
          }};
        }})()"""
    )
    assert failed["notice"] == "该插件没有通过插件包安装的版本"
    assert failed["rows"] == 6
    assert failed["url"] == before


# ── 真实 API 形状：页面消费字段必须由现有接口提供 ───────────────────────────


def _client(monkeypatch, tmp_path: Path, *, install_root: Path | None):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "dsh43.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    if install_root is None:
        monkeypatch.delenv("VSE_INSTALL_ROOT", raising=False)
    else:
        monkeypatch.setenv("VSE_INSTALL_ROOT", str(install_root))
    app = web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=["settings"])
    app.config.update(TESTING=True)
    return app.test_client(), app


def test_plugin_updates_api_shape_matches_page(monkeypatch, tmp_path: Path) -> None:
    client, app = _client(monkeypatch, tmp_path, install_root=None)
    updates = app.extensions["plugin_updates"]

    # 真实 active.json / staging 形状（不经过签名包，只验证 API 字段）。
    state = updates.read_state()
    state["plugins"]["settings"] = {"version": "9.9.9", "previous": "9.9.8"}
    state["events"].append(
        {
            "at": "2026-10-24T01:30:00Z",
            "kind": "rolled_back",
            "plugin": "settings",
            "version": "9.9.8",
            "to": "9.9.9",
            "reason": "用户手动回滚",
        }
    )
    updates.root.mkdir(parents=True, exist_ok=True)
    updates.active_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    (updates.root / "staging" / "demo" / "2.0.0").mkdir(parents=True)

    payload = client.get("/api/host/updates").get_json()["data"]
    # 页面 buildRecords 读取的字段全部来自这个接口。
    assert {"active", "pending", "events", "trustedKeys", "plugins"} <= set(payload)
    assert payload["active"]["settings"] == {"version": "9.9.9", "previous": "9.9.8"}
    assert payload["pending"] == [{"id": "demo", "version": "2.0.0"}]
    assert isinstance(payload["trustedKeys"], list)
    event = payload["events"][0]
    assert event["kind"] == "rolled_back" and event["plugin"] == "settings"
    assert event["version"] == "9.9.8" and event["to"] == "9.9.9"
    assert event["reason"] == "用户手动回滚"
    assert event["at"].endswith("Z"), "插件事件时间必须带时区，页面才能按北京时间显示"
    plugin = next(item for item in payload["plugins"] if item["id"] == "settings")
    assert set(plugin) == {"id", "name", "version", "status", "source"}


def test_app_updates_api_shape_matches_page(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("cryptography")
    from tests.test_vse_boot_packages import FILES, keypair
    from vse_boot import api
    from vse_boot.layout import InstallLayout
    from vse_boot.packages import build_app_package
    from vse_boot.state import BootState

    layout = InstallLayout(tmp_path / "VSE-Toolbox").ensure()
    for version in ("1.8.0", "1.9.0", "2.0.0", "2.1.0", "2.2.0"):
        layout.app_dir(version).mkdir(parents=True, exist_ok=True)
    state = BootState(layout)
    state.app.update(current="2.0.0", previous="1.9.0", trial="2.1.0")
    state.save()
    state.record("staged", "2.2.0", notes="修复 <b>登录</b> 问题")
    state.record("activated", "2.0.0", previous="1.9.0")
    state.record("manualRollback", "2.0.0", fromVersion="2.1.0")
    staged_dir = layout.staging_dir / "app-2.2.0"
    staged_dir.mkdir(parents=True, exist_ok=True)
    (staged_dir / "staged.json").write_text(
        json.dumps({"version": "2.2.0", "notes": "修复 <b>登录</b> 问题"}, ensure_ascii=False),
        encoding="utf-8",
    )

    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    pem, keys = keypair()
    key_file = tmp_path / "runtime_keys.json"
    key_file.write_text(
        json.dumps({"keys": [{"keyId": k, "publicKey": base64.b64encode(v).decode()} for k, v in keys.items()]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(api, "RUNTIME_KEYS", key_file)
    monkeypatch.setattr(api, "watch_dirs", lambda _layout: [downloads])
    (downloads / "vse-app-2.3.0.vsepkg").write_bytes(
        build_app_package(FILES, version="2.3.0", private_key_pem=pem, notes="修复 <b>登录</b> 问题")[1]
    )

    client, _app = _client(monkeypatch, tmp_path, install_root=layout.root)
    payload = client.get("/api/p/settings/app-updates").get_json()["data"]
    # 页面 buildRecords 读取的字段全部来自这个接口。
    assert payload["managed"] is True
    assert payload["current"] == "2.0.0"
    assert payload["previous"] == "1.9.0"
    assert payload["trial"] == "2.1.0"
    assert payload["staged"] == ["2.2.0"]
    assert {"1.8.0", "1.9.0", "2.0.0", "2.1.0", "2.2.0"} <= set(payload["installed"])
    assert payload["watchDirs"] == [str(downloads)]
    item = payload["available"][0]
    assert set(item) == {"file", "folder", "version", "notes", "sizeKb"}
    assert item["version"] == "2.3.0" and item["notes"] == "修复 <b>登录</b> 问题"
    assert item["file"].endswith(".vsepkg") and item["sizeKb"] >= 0
    staged_event = next(event for event in payload["events"] if event["kind"] == "staged")
    assert staged_event["version"] == "2.2.0" and staged_event["notes"] == "修复 <b>登录</b> 问题"
    # 启动器事件时间是无时区本地文本（页面按 local 来源解释），不是编造出来的时间。
    assert "T" not in staged_event["at"] and not staged_event["at"].endswith("Z")

    # managed=false 的真实形状：页面只显示说明，不发起任何写操作。
    monkeypatch.delenv("VSE_INSTALL_ROOT")
    assert client.get("/api/p/settings/app-updates").get_json()["data"] == {"managed": False}
