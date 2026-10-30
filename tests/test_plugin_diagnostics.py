# -*- coding: utf-8 -*-
"""自检插件测试：插件清单、自检聚合只读接口契约、敏感载荷白名单断言、
Excel 服务异常回退 need_check 以及前端模块 Node 夹具冒烟。"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import host.plugin as host_plugin
import services.excel_env_check as excel_env_check
import web.app as web_app

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO_ROOT / "plugins" / "diagnostics"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    """创建仅挂载自检插件的隔离测试客户端。"""
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "diagnostics-plugin.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=["diagnostics"])
    app.config.update(TESTING=True)
    return app.test_client()


# ── 1. 插件清单契约 ──────────────────────────────────────────────────


def test_diagnostics_manifest_contract() -> None:
    """验证 plugin.json 结构完整性、自检页面及专家模式导航配置。"""
    manifest = host_plugin.load_manifest(PLUGIN_DIR)
    assert manifest.id == "diagnostics"
    assert manifest.name == "自检"
    assert len(manifest.pages) >= 1
    page_ids = {p.id for p in manifest.pages}
    assert "self-check" in page_ids

    page = next(p for p in manifest.pages if p.id == "self-check")
    assert page.kind == "module"
    assert page.module == "self-check.js"

    assert len(manifest.nav) >= 1
    nav = next(n for n in manifest.nav if n.page == "self-check")
    assert nav.title == "自检"
    assert nav.expert is True
    assert nav.parent == "workbench/tools"


# ── 2. 自检路由只读性与载荷键白名单 ────────────────────────────────────


def test_self_check_route_is_read_only(client) -> None:
    """GET 正常响应，POST/PUT/DELETE 等写操作一律 405 Method Not Allowed。"""
    get_resp = client.get("/api/p/diagnostics/self-check")
    assert get_resp.status_code == 200
    body = get_resp.get_json()
    assert body["ok"] is True
    assert isinstance(body["data"], dict)
    assert "items" in body["data"]

    # 验证只读约束：禁止任何写方法
    assert client.post("/api/p/diagnostics/self-check", json={}).status_code == 405
    assert client.put("/api/p/diagnostics/self-check", json={}).status_code == 405
    assert client.delete("/api/p/diagnostics/self-check").status_code == 405


def test_self_check_payload_key_whitelist_and_no_secrets(client) -> None:
    """载荷字段必须在严格白名单内，且全文字符串中不得包含任何凭据与私有网络地址。"""
    resp = client.get("/api/p/diagnostics/self-check")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True

    data = body["data"]
    # 顶层字段白名单
    assert set(data.keys()) <= {"items"}

    items = data["items"]
    assert isinstance(items, list)
    assert len(items) == 4

    # 单项字段白名单
    item_whitelist = {"name", "state", "detail", "checkedAt"}
    allowed_states = {"ok", "warn", "need_check", "unknown"}
    names = set()

    for item in items:
        assert isinstance(item, dict)
        assert set(item.keys()) == item_whitelist
        assert isinstance(item["name"], str) and item["name"]
        assert item["state"] in allowed_states
        assert isinstance(item["detail"], str)
        assert isinstance(item["checkedAt"], str)
        names.add(item["name"])

    assert names == {"统一账号会话", "表格环境", "更新通道", "项目注册表"}

    # 敏感键与凭据防御断言
    raw_text = json.dumps(body, ensure_ascii=False).lower()
    forbidden_tokens = ["password", "token", "secret", "cookie", "sessionid", "authorization", "set-cookie", "api_key"]
    for token in forbidden_tokens:
        assert token not in raw_text, f"自检响应中意外发现敏感字样: {token}"

    # 禁止内部 IP 地址泄漏（排查 192.168.x.x, 10.x.x.x, 172.16-31.x.x 等）
    private_ip_pattern = re.compile(r"\b(?:10|192\.168|172\.(?:1[6-9]|2[0-9]|3[01]))\.\d+\.\d+\b")
    assert not private_ip_pattern.search(raw_text), "自检响应中意外发现内网 IP 地址"


# ── 3. Excel 服务异常回落 need_check ─────────────────────────────────


def test_excel_env_check_error_fallback(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """当 Excel 环境检测接口抛错时，状态必须回落为 need_check，绝不伪报通过。"""
    def mock_broken_check(**_kwargs: Any) -> Any:
        raise RuntimeError("模拟底层 COM 组件服务异常崩溃")

    monkeypatch.setattr(excel_env_check, "check_excel_environment", mock_broken_check)

    resp = client.get("/api/p/diagnostics/self-check")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True

    excel_item = next(item for item in body["data"]["items"] if item["name"] == "表格环境")
    assert excel_item["state"] == "need_check"
    assert "模拟底层 COM 组件服务异常崩溃" in excel_item["detail"]
    assert excel_item["state"] != "ok"


def test_excel_env_check_unlicensed_fallback(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """当 Excel 检测到未激活时，状态必须为 need_check。"""
    monkeypatch.setattr(
        excel_env_check,
        "check_excel_environment",
        lambda **_kwargs: {
            "installed": True,
            "version": "16.0",
            "activation": {"state": "unlicensed", "detail": "软件尚未激活"},
        },
    )
    resp = client.get("/api/p/diagnostics/self-check")
    excel_item = next(item for item in resp.get_json()["data"]["items"] if item["name"] == "表格环境")
    assert excel_item["state"] == "need_check"
    assert "未激活" in excel_item["detail"]


# ── 4. 统一会话与更新通道状态分支 ──────────────────────────────────────


def test_session_registry_states(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证会话注册表各分支状态映射。"""
    mock_registry = MagicMock()
    mock_registry.payload.return_value = {
        "aras": {"authenticated": True, "expired": False},
        "tdc": {"authenticated": True, "expired": False},
    }

    # 注入到 Flask current_app 的 extensions 中
    import flask
    with client.application.app_context():
        flask.current_app.extensions["domain_sessions"] = mock_registry
        resp = client.get("/api/p/diagnostics/self-check")
        session_item = next(item for item in resp.get_json()["data"]["items"] if item["name"] == "统一账号会话")
        assert session_item["state"] == "ok"
        assert "ARAS" in session_item["detail"] and "TDC" in session_item["detail"]

        # 部分失效分支
        mock_registry.payload.return_value = {
            "aras": {"authenticated": True, "expired": False},
            "tdc": {"authenticated": False, "expired": True},
        }
        resp = client.get("/api/p/diagnostics/self-check")
        session_item = next(item for item in resp.get_json()["data"]["items"] if item["name"] == "统一账号会话")
        assert session_item["state"] == "warn"

        # 全部未登录分支
        mock_registry.payload.return_value = {
            "aras": {"authenticated": False, "expired": False},
            "tdc": {"authenticated": False, "expired": False},
        }
        resp = client.get("/api/p/diagnostics/self-check")
        session_item = next(item for item in resp.get_json()["data"]["items"] if item["name"] == "统一账号会话")
        assert session_item["state"] == "need_check"


def test_update_channel_and_project_states(client) -> None:
    """验证未注入 updates 与 projects 时的 unknown 安全回退。"""
    resp = client.get("/api/p/diagnostics/self-check")
    body = resp.get_json()
    items = {item["name"]: item for item in body["data"]["items"]}

    # 服务已装配但测试环境未配置可信密钥：warn（未配置即暂不能收新更新）是诚实状态。
    assert items["更新通道"]["state"] == "warn"
    assert "可信公钥" in items["更新通道"]["detail"]
    assert items["项目注册表"]["state"] == "unknown"


# ── 5. 静态资源响应 ──────────────────────────────────────────────────


def test_static_assets_served(client) -> None:
    """验证 self-check.json 和 self-check.js 正确挂载静态托管路由。"""
    json_resp = client.get("/plugins/diagnostics/static/pages/self-check.json")
    assert json_resp.status_code == 200
    page_def = json_resp.get_json()
    assert page_def["title"] == "系统自检"
    assert page_def["container"] == "diagnostics-self-check"

    js_resp = client.get("/plugins/diagnostics/static/self-check.js")
    assert js_resp.status_code == 200
    assert js_resp.mimetype == "text/javascript"
    js_text = js_resp.get_data(as_text=True)
    assert "triggerDiagnosticExport" in js_text
    assert "SelfCheckPage" in js_text
    assert "导出诊断包" in js_text


# ── 6. 前端 Node 夹具冒烟 ───────────────────────────────────────────


def _node_available() -> bool:
    return shutil.which("node") is not None


@pytest.mark.skipif(not _node_available(), reason="需要 Node 环境运行前端语法与纯逻辑夹具")
def test_frontend_node_fixture_smoke() -> None:
    """前端 Node 冒烟：检查 self-check.js 语法合法性及导出状态配置纯逻辑。"""
    js_file = PLUGIN_DIR / "static" / "self-check.js"
    assert js_file.is_file()

    # 1. 语法检查 node --check
    proc_check = subprocess.run(["node", "--check", str(js_file)], capture_output=True, text=True)
    assert proc_check.returncode == 0, f"JS 语法检查失败: {proc_check.stderr}"

    # 2. 模拟运行 Node 夹具验证纯逻辑导出与结构
    node_fixture = """
    const fs = require('fs');
    const source = fs.readFileSync(process.argv[1], 'utf8');

    // 断言必要组件与方法导出定义存在
    if (!/(export\s+(async\s+)?function\s+triggerDiagnosticExport)/.test(source)) {
        throw new Error('未导出 triggerDiagnosticExport 方法');
    }
    if (!source.includes('export const STATE_CONFIG')) {
        throw new Error('未导出 STATE_CONFIG 常量');
    }
    if (!source.includes('export default function SelfCheckPage')) {
        throw new Error('未默认导出 SelfCheckPage 组件');
    }
    if (!source.includes('导出诊断包')) {
        throw new Error('未包含导出诊断包入口文案');
    }

    // 术语门禁由仓库权威实现 tests/test_glossary_terms.py 负责（字符串字面量级扫描），
    // 这里不重复朴素 >...< 文本段扫描——那会把代码标识符（如 Accept 头）误判为可见文案。
    console.log('NODE_FIXTURE_SUCCESS');
    """
    proc_run = subprocess.run(
        ["node", "-e", node_fixture, str(js_file)],
        capture_output=True,
        text=True,
    )
    assert proc_run.returncode == 0, f"Node 冒烟脚本执行异常: {proc_run.stderr}"
    assert "NODE_FIXTURE_SUCCESS" in proc_run.stdout
