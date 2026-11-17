# -*- coding: utf-8 -*-
"""D5 车型 ↔ 架构件单接口与页面接线（方案 B）。

只测接口契约与前端接线事实，不测浏览器渲染（无浏览器环境）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import web.app as web_app
from services.deliverable_form_analysis import build_form_snapshot, form_definition

REPO_ROOT = Path(__file__).resolve().parent.parent
HEADERS = form_definition("tdc_data_model")["headerRows"][0]
API = "/api/p/project-overview"


def _values(**overrides):
    row = {
        "实例号": "90000101",
        "流水单号": "F620S-3D-0075",
        "项目/车型": "F620S",
        "部门": "内饰科",
        "发布属性": "T2发布",
        "申请日期": "2026-08-20 10:00:00",
        "状态": "已完成",
    }
    row.update(overrides)
    return [row.get(header) for header in HEADERS]


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "links_po.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=["project-overview"])
    app.config.update(TESTING=True)
    db = db_cls(tmp_path / "links_po.db")
    db.init_database()
    db.publish_deliverable_form_snapshot(
        build_form_snapshot(
            "tdc_data_model",
            [
                {"values": _values(), "sheetName": "Sheet1"},
                {
                    "values": _values(
                        实例号="90000102",
                        流水单号="Ar-L-3D-0002",
                        **{"项目/车型": "Ar-L"},
                        状态="审批中",
                    ),
                    "sheetName": "Sheet1",
                },
            ],
            snapshot_at="2026-10-23T00:00:00Z",
            source_run_id=1,
            source="test",
        )
    )
    return app.test_client()


def test_links_start_empty(client) -> None:
    payload = client.get(f"{API}/vehicle-arch-links").get_json()
    assert payload["data"]["items"] == []


def test_declaring_a_serial_returns_it_and_marks_matched(client) -> None:
    created = client.post(
        f"{API}/vehicle-arch-links",
        json={"action": "replace", "vehicle": "F620S", "serials": "Ar-L-3D-0002"},
    )
    assert created.status_code == 200
    assert created.get_json()["data"]["added"] == ["Ar-L-3D-0002"]

    listed = client.get(f"{API}/vehicle-arch-links?vehicle=F620S").get_json()["data"]
    assert [item["serial"] for item in listed["items"]] == ["Ar-L-3D-0002"]
    assert listed["vehicles"] == ["F620S"]


def test_view_payload_exposes_combined_scope_after_declaration(client) -> None:
    client.post(
        f"{API}/vehicle-arch-links",
        json={"action": "replace", "vehicle": "F620S", "serials": ["Ar-L-3D-0002"]},
    )
    payload = client.get("/api/deliverable-forms/tdc_data_model/view").get_json()["data"]
    links_payload = payload["vehicleArchLinks"]
    assert links_payload["scope"] == "combined"
    assert links_payload["countUnit"] == "instance"
    vehicle = links_payload["vehicles"][0]
    assert vehicle["vehicle"] == "F620S"
    assert vehicle["projectOnly"]["instances"] == 1
    assert vehicle["linkedArchitecture"]["matched"] == 1
    assert vehicle["combined"]["instances"] == 2
    assert vehicle["links"][0]["status"] == "matched"


def test_clear_removes_declaration(client) -> None:
    client.post(
        f"{API}/vehicle-arch-links",
        json={"action": "replace", "vehicle": "F620S", "serials": ["Ar-L-3D-0002"]},
    )
    cleared = client.post(
        f"{API}/vehicle-arch-links", json={"action": "clear", "vehicle": "F620S"}
    )
    assert cleared.get_json()["data"]["cleared"] == 1
    assert client.get(f"{API}/vehicle-arch-links?vehicle=F620S").get_json()["data"]["items"] == []


def test_rejects_bad_payloads(client) -> None:
    assert client.post(
        f"{API}/vehicle-arch-links", json={"action": "replace", "serials": ["A"]}
    ).status_code == 400
    assert client.post(
        f"{API}/vehicle-arch-links", json={"action": "nope", "vehicle": "F620S"}
    ).status_code == 400


def test_d5_page_mounts_arch_links_panel() -> None:
    """接线事实：面板已导入并挂在 D5 交付物明细页。"""
    source = (
        REPO_ROOT / "plugins/project_overview/static/deliverable/form-analysis.js"
    ).read_text(encoding="utf-8")
    assert 'from "./arch-links.js"' in source
    assert "ArchLinksPanel" in source
    assert "vehicleArchLinks" in source

    panel = (
        REPO_ROOT / "plugins/project_overview/static/deliverable/arch-links.js"
    ).read_text(encoding="utf-8")
    assert "/api/p/project-overview/vehicle-arch-links" in panel
    # 四态展示不得在前端重算，只读后端给的 statusLabel。
    assert "statusLabel" in panel


def test_panel_script_is_parseable_as_module() -> None:
    """面板脚本至少要是合法 ES module（用 node --check 兜底，node 缺失则跳过）。"""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node 不可用")
    result = subprocess.run(
        [node, "--check", str(REPO_ROOT / "plugins/project_overview/static/deliverable/arch-links.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
