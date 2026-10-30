# -*- coding: utf-8 -*-
"""开机自启开关功能测试。

测试约束：
1. 注册表操作全部 mock（严格禁止真写注册表）；
2. 覆盖：开启、关闭、幂等、损坏值修复、路径含空格引号处理；
3. 验证默认状态为关闭（全新安装不写注册表）；
4. 验证设置页前端文案通俗、无内部术语。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import web.app as web_app
from vse_boot import autostart

REPO_ROOT = Path(__file__).resolve().parent.parent


class FakeKey:
    """Mock winreg 打开的键句柄，支持 with 语句上下文。"""

    def __init__(self, tree: dict[str, tuple[object, int]], sub_key: str) -> None:
        self.tree = tree
        self.sub_key = sub_key

    def __enter__(self) -> "FakeKey":
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        pass


class FakeWinreg:
    """完全隔离的内存注册表，模拟 winreg 关键接口，确保测试绝不触碰真实注册表。"""

    HKEY_CURRENT_USER = 0x80000001
    KEY_READ = 0x20019
    KEY_SET_VALUE = 0x0002
    REG_SZ = 1
    REG_EXPAND_SZ = 2
    REG_BINARY = 3
    REG_DWORD = 4

    def __init__(self) -> None:
        # 键路径（小写规范化） -> { 值名 -> (值内容, 类型) }
        self.storage: dict[str, dict[str, tuple[object, int]]] = {}

    def OpenKey(self, _root: int, sub_key: str, _reserved: int = 0, _access: int = 0) -> FakeKey:
        normalized = sub_key.replace("/", "\\").lower()
        if normalized not in self.storage:
            raise FileNotFoundError(f"Key not found: {sub_key}")
        return FakeKey(self.storage[normalized], normalized)

    def CreateKey(self, _root: int, sub_key: str) -> FakeKey:
        normalized = sub_key.replace("/", "\\").lower()
        if normalized not in self.storage:
            self.storage[normalized] = {}
        return FakeKey(self.storage[normalized], normalized)

    def QueryValueEx(self, key_handle: FakeKey, value_name: str) -> tuple[object, int]:
        if value_name not in key_handle.tree:
            raise FileNotFoundError(f"Value not found: {value_name}")
        return key_handle.tree[value_name]

    def SetValueEx(self, key_handle: FakeKey, value_name: str, _reserved: int, val_type: int, value: object) -> None:
        key_handle.tree[value_name] = (value, val_type)

    def DeleteValue(self, key_handle: FakeKey, value_name: str) -> None:
        if value_name not in key_handle.tree:
            raise FileNotFoundError(f"Value not found: {value_name}")
        del key_handle.tree[value_name]


@pytest.fixture()
def fake_registry(monkeypatch: pytest.MonkeyPatch) -> FakeWinreg:
    """注入完全 mock 的内存注册表，拦截所有注册表操作。"""
    fake = FakeWinreg()
    monkeypatch.setattr(autostart, "winreg", fake)
    return fake


@pytest.fixture()
def test_client(fake_registry: FakeWinreg, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    """构造加载了 settings 插件的测试客户端。"""
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "settings-test.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=["settings"])
    app.config.update(TESTING=True)
    return app.test_client()


# ── 1. 默认状态与注册表未触碰 ──────────────────────────────────────


def test_default_state_is_disabled_and_leaves_registry_clean(fake_registry: FakeWinreg) -> None:
    """全新安装默认状态为关闭，且不向注册表写入任何值。"""
    assert autostart.enabled() is False
    # 注册表仍然没有任何项被创建
    assert fake_registry.storage == {}


# ── 2. 开启与关闭 ────────────────────────────────────────────────


def test_enable_writes_quoted_command(fake_registry: FakeWinreg) -> None:
    """开启开机自启写入规范的命令行。"""
    autostart.enable()
    assert autostart.enabled() is True

    key_path = autostart.RUN_KEY.replace("/", "\\").lower()
    assert key_path in fake_registry.storage
    val, val_type = fake_registry.storage[key_path][autostart.APP_NAME]
    assert val_type == fake_registry.REG_SZ
    assert val == autostart.command()
    # 校验返回值包含引号
    assert str(val).startswith('"') and str(val).endswith('"')


def test_disable_clears_existing_entry(fake_registry: FakeWinreg) -> None:
    """关闭开机自启会清理掉注册表中已有的项。"""
    autostart.enable()
    assert autostart.enabled() is True

    autostart.disable()
    assert autostart.enabled() is False

    key_path = autostart.RUN_KEY.replace("/", "\\").lower()
    assert autostart.APP_NAME not in fake_registry.storage[key_path]


# ── 3. 幂等性 ───────────────────────────────────────────────────


def test_enable_and_disable_are_idempotent(fake_registry: FakeWinreg) -> None:
    """重复调用 enable/disable 不抛出异常，项不存在时 disable 同样安全。"""
    # 初始项不存在时关闭：不报错
    autostart.disable()
    autostart.disable()
    assert autostart.enabled() is False

    # 重复开启：不报错且状态维持启用
    autostart.enable()
    autostart.enable()
    assert autostart.enabled() is True

    # 再次重复关闭：不报错且项被清理
    autostart.disable()
    autostart.disable()
    assert autostart.enabled() is False


# ── 4. 损坏值修复 ────────────────────────────────────────────────


def test_corrupted_type_dword_treated_as_disabled_and_repaired(fake_registry: FakeWinreg) -> None:
    """类型损坏（非字符串类型，如 REG_DWORD）按未启用处理并自动清理修复。"""
    key = fake_registry.CreateKey(fake_registry.HKEY_CURRENT_USER, autostart.RUN_KEY)
    fake_registry.SetValueEx(key, autostart.APP_NAME, 0, fake_registry.REG_DWORD, 1)

    # 检查时应识别为未启用，并执行修复（清理损坏值）
    assert autostart.enabled() is False
    key_path = autostart.RUN_KEY.replace("/", "\\").lower()
    assert autostart.APP_NAME not in fake_registry.storage[key_path]


def test_corrupted_empty_string_repaired(fake_registry: FakeWinreg) -> None:
    """空白字符串值按未启用处理并清理修复。"""
    key = fake_registry.CreateKey(fake_registry.HKEY_CURRENT_USER, autostart.RUN_KEY)
    fake_registry.SetValueEx(key, autostart.APP_NAME, 0, fake_registry.REG_SZ, "   ")

    assert autostart.enabled() is False
    key_path = autostart.RUN_KEY.replace("/", "\\").lower()
    assert autostart.APP_NAME not in fake_registry.storage[key_path]


def test_corrupted_unclosed_quotes_repaired(fake_registry: FakeWinreg) -> None:
    """引号不配对（奇数引号）按未启用处理并清理修复。"""
    key = fake_registry.CreateKey(fake_registry.HKEY_CURRENT_USER, autostart.RUN_KEY)
    fake_registry.SetValueEx(key, autostart.APP_NAME, 0, fake_registry.REG_SZ, '"C:\\Program Files\\app.exe')

    assert autostart.enabled() is False
    key_path = autostart.RUN_KEY.replace("/", "\\").lower()
    assert autostart.APP_NAME not in fake_registry.storage[key_path]


def test_enable_overwrites_and_repairs_corrupted_value(fake_registry: FakeWinreg) -> None:
    """在存在损坏值时调用 enable()，能够覆盖修复为正确的命令。"""
    key = fake_registry.CreateKey(fake_registry.HKEY_CURRENT_USER, autostart.RUN_KEY)
    fake_registry.SetValueEx(key, autostart.APP_NAME, 0, fake_registry.REG_BINARY, b"\x00\x01\x02")

    autostart.enable()
    assert autostart.enabled() is True

    key_path = autostart.RUN_KEY.replace("/", "\\").lower()
    val, val_type = fake_registry.storage[key_path][autostart.APP_NAME]
    assert val_type == fake_registry.REG_SZ
    assert val == autostart.command()


# ── 5. 路径含空格与引号处理 ────────────────────────────────────────


def test_command_handles_path_with_spaces() -> None:
    """路径包含空格时包裹双引号，且不会产生多重引号。"""
    path_with_spaces = r"C:\Program Files\VSE Toolbox\VSE-Toolbox.exe"
    cmd = autostart.command(path_with_spaces)
    assert cmd == f'"{path_with_spaces}"'

    # 若输入已经带有双引号，应当规整为单一双引号包裹
    cmd_already_quoted = autostart.command(f'"{path_with_spaces}"')
    assert cmd_already_quoted == f'"{path_with_spaces}"'


def test_enable_and_enabled_with_spaced_exe(fake_registry: FakeWinreg) -> None:
    """指定含空格的 exe 路径，能够正确开启并匹配识别。"""
    spaced_exe = r"C:\Program Files\VSE Toolbox\VSE-Toolbox.exe"
    autostart.enable(exe=spaced_exe)
    assert autostart.enabled(exe=spaced_exe) is True

    # 验证注册表中写入了双引号包裹的路径
    key_path = autostart.RUN_KEY.replace("/", "\\").lower()
    val, _ = fake_registry.storage[key_path][autostart.APP_NAME]
    assert val == f'"{spaced_exe}"'


# ── 6. 设置插件后端接口（GET/POST /api/p/settings/autostart）───────


def test_settings_plugin_autostart_api_lifecycle(test_client, fake_registry: FakeWinreg) -> None:
    """测试设置插件后端自启接口的读取、开启、关闭与幂等。"""
    # 默认状态：关闭
    res = test_client.get("/api/p/settings/autostart")
    assert res.status_code == 200
    data = res.get_json()["data"]
    assert data["enabled"] is False
    assert data["available"] is True

    # 调用 POST 开启
    res_on = test_client.post("/api/p/settings/autostart", json={"enabled": True})
    assert res_on.status_code == 200
    assert res_on.get_json()["data"]["enabled"] is True

    # 再次查询验证状态已同步为已开启
    res_after_on = test_client.get("/api/p/settings/autostart")
    assert res_after_on.get_json()["data"]["enabled"] is True

    # 调用 POST 关闭
    res_off = test_client.post("/api/p/settings/autostart", json={"enabled": False})
    assert res_off.status_code == 200
    assert res_off.get_json()["data"]["enabled"] is False

    # 再次查询验证状态已同步为已关闭，且注册表项已被清理
    res_after_off = test_client.get("/api/p/settings/autostart")
    assert res_after_off.get_json()["data"]["enabled"] is False
    key_path = autostart.RUN_KEY.replace("/", "\\").lower()
    assert autostart.APP_NAME not in fake_registry.storage.get(key_path, {})


# ── 7. 前端文案合规（通俗、无内部术语）─────────────────────────────


def test_frontend_text_has_no_internal_terms_and_matches_copy_requirement() -> None:
    """验证设置页前端文案符合要求：通俗、无内部违禁术语，且包含核心说明。"""
    static_dir = REPO_ROOT / "plugins" / "settings" / "static"
    service_status_js = (static_dir / "service-status.js").read_text(encoding="utf-8")
    general_js = (static_dir / "general.js").read_text(encoding="utf-8")

    # 核心中文文案必须存在
    assert "开机自动启动 VSE 工具箱" in service_status_js
    assert "只影响当前 Windows 账号" in service_status_js
    assert "AutostartCard" in general_js

    # 违禁内部术语检查
    forbidden_terms = ["JSON", "Base URL", "Worker", "快照", "取证", "代码路径", "文件路径"]
    # 检查整个 AutostartCard 组件函数体（从定义到下一个 export function）：
    # 组件体内有多行常量与回调，单条 return html 正则容易漏。
    start = service_status_js.index("export function AutostartCard")
    next_export = service_status_js.find("export function", start + 10)
    card_html = service_status_js[start: next_export if next_export != -1 else len(service_status_js)]

    for term in forbidden_terms:
        assert term not in card_html, f"前端可见文案中出现了内部术语：{term}"
