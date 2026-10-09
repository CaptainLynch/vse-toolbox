# -*- coding: utf-8 -*-
"""Focused tests for the VSE Toolbox 项目状态概览 redesign.

Covers static HTML/CSS/JS structure, the saved-state loader and inline
deliverable editor contract, tab and detail-expansion accessibility behavior,
read-only overview guards, and the preserved `/api/overview` Flask route.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import web.app as web_app


@pytest.fixture()
def client(monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "overview-test.db"))
    app = web_app.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _overview_html(html_text: str) -> str:
    start = html_text.find('id="overview"')
    assert start != -1, "Start marker 'id=\"overview\"' not found"
    end = html_text.find('id="deliverables"', start)
    assert end != -1, "End marker 'id=\"deliverables\"' not found after 'id=\"overview\"'"
    return html_text[start:end]


def test_index_serves_plugin_shell_without_legacy_overview(client) -> None:  # type: ignore[no-untyped-def]
    resp = client.get("/")
    assert resp.status_code == 200
    html_text = resp.get_data(as_text=True)

    # 概览与交付物已重写为插件页（#p/project-overview/*、#p/deliverables/catalog）。
    assert "项目工作台" in html_text
    assert 'id="plugin-host"' in html_text
    for marker in ('id="overview"', 'id="deliverables"', "deliverables-workbench", "data-panel-link", "overview-grid"):
        assert marker not in html_text


def _css_slice(css_text: str, start_marker: str, end_marker: str) -> str:
    start = css_text.find(start_marker)
    assert start != -1, f"Start marker '{start_marker}' not found"
    end = css_text.find(end_marker, start)
    assert end != -1, f"End marker '{end_marker}' not found after '{start_marker}'"
    return css_text[start:end]


def test_overview_api_route_contract_preserved(client) -> None:  # type: ignore[no-untyped-def]
    resp = client.get("/api/overview")
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body) == {"projects", "deliverables", "feishu"}
    assert isinstance(body["projects"], dict)
    assert isinstance(body["deliverables"], dict)
    assert set(body["feishu"]) == {"total", "synced"}


def _css_rule(css_text: str, selector: str) -> str:
    """Return the body of one top-level CSS rule for a selector."""
    marker = f"{selector} {{"
    start = css_text.find(marker)
    assert start != -1, f"Selector '{selector}' not found in CSS"
    end = css_text.find("}", start)
    assert end != -1, f"Closing brace not found for '{selector}'"
    return css_text[start:end]


def _js_slice(js_text: str, start_marker: str, end_marker: str) -> str:
    start = js_text.find(start_marker)
    assert start != -1, f"Start marker '{start_marker}' not found"
    end = js_text.find(end_marker, start)
    assert end != -1, f"End marker '{end_marker}' not found after '{start_marker}'"
    return js_text[start:end]


def test_ewo_model_info_filter_is_forwarded_to_aras_crawler() -> None:
    """EWO 的车型匹配条件必须能进入映射发现请求的过滤器。"""
    from web.app import _ewo_filters_from_payload

    filters = _ewo_filters_from_payload({"filters": {"model_info": "*F610S*"}})

    assert filters.model_info == "*F610S*"


def test_owner_header_removed_contract() -> None:
    """需求 2026-09-06：明细表负责人表头移除。"""
    html_text = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")

    # 表头与数据列一致：静态表头不再包含负责人。
    assert '<th scope="col">负责人</th>' not in html_text


def test_top_bar_navigation_six_main_domains() -> None:
    """顶栏全部由插件 plugin.json 的 nav 生成；旧哈希由宿主 legacy-routes.js 转到插件页。"""
    nav = []
    for manifest_path in sorted(Path("plugins").glob("*/plugin.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        nav += [(entry.get("order", 100), entry["title"], manifest["id"]) for entry in manifest.get("nav", [])]
    assert [title for _, title, _ in sorted(nav)] == ["概览", "交付物", "系统查询", "表单", "签署日报", "TIR数据简表", "Excel", "自动归档", "设置"]

    html_text = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")
    assert "<nav" not in html_text  # 不再有写死在模板里的导航

    routes = Path("web/static/host/legacy-routes.js").read_text(encoding="utf-8")
    for legacy, target in [
        ("overview", "#p/project-overview/status"),
        ("deliverables", "#p/deliverables/catalog"),
        ("aras-panel", "#p/system-query/query"),
        ("excel-tasks", "#p/excel-tasks/workspace"),
        ("scheduled-archive", "#p/scheduled-archive/jobs"),
        ("settings-panel", "#p/settings/general"),
    ]:
        assert re.search(rf'"?{re.escape(legacy)}"?: "{re.escape(target)}"', routes), legacy
