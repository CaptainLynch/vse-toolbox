# -*- coding: utf-8 -*-
"""数模设计审核流程报表：多值搜索与关注清单接口（签署日报规格 §9 S2–S9、S21）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import web.app as web_app
from services.deliverable_form_analysis import build_form_snapshot, form_definition
from services.form_search import PLACEHOLDER, parse_terms

REPO_ROOT = Path(__file__).resolve().parent.parent
HEADERS = form_definition("tdc_data_model")["headerRows"][0]
API = "/api/p/project-overview"


def test_parse_terms_accepts_all_separators():  # S2
    assert parse_terms("F610M-3D-0001 F610M-3D-0002，前门内板；张三、Z9\nA1\tA2,，a1") == [
        "F610M-3D-0001", "F610M-3D-0002", "前门内板", "张三", "Z9", "A1", "A2"]
    assert parse_terms("") == []
    assert len(parse_terms(" ".join(f"t{i}" for i in range(300)))) == 100


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "po.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=["project-overview"])
    app.config.update(TESTING=True)
    db = db_cls(tmp_path / "po.db")
    rows = [
        {"流水单号": "F610M-3D-0001", "零件名称": "前门内板", "零件号": "P-1", "申请人": "张三", "状态": "进行中"},
        {"流水单号": "F610M-3D-0001", "零件名称": "前门外板", "零件号": "P-2", "申请人": "张三", "状态": "进行中"},
        {"流水单号": "F610M-3D-0002", "零件名称": "尾灯", "零件号": "P-3", "申请人": "李四", "状态": "已完成"},
    ]
    positional = [{"values": [row.get(h) for h in HEADERS], "sheetName": "Sheet1"} for row in rows]
    db.publish_deliverable_form_snapshot(
        build_form_snapshot("tdc_data_model", positional, snapshot_at="2026-10-03T08:00:00Z", source_run_id=1,
                            source="test")
    )
    return app, app.test_client(), db


def _ok(response):  # type: ignore[no-untyped-def]
    payload = response.get_json()
    assert payload["ok"] is True, payload
    return payload["data"]


def test_multi_term_search_counts_forms_and_lists_unmatched(client):  # type: ignore[no-untyped-def]  # 验收 22
    _, http, _ = client
    text = "F610M-3D-0001\nF610M-3D-0002\nF610M-3D-0099"
    summary = _ok(http.get(f"{API}/form-terms", query_string={"terms": text}))
    assert (summary["forms"], summary["unmatched"]) == (2, ["F610M-3D-0099"])
    assert summary["serials"] == ["F610M-3D-0001", "F610M-3D-0002"]
    assert summary["placeholder"] == PLACEHOLDER  # 验收 23
    rows = http.get("/api/deliverable-forms/tdc_data_model/rows", query_string={"terms": text}).get_json()
    assert rows["ok"] is True and rows["data"]["total"] == 3
    by_name = _ok(http.get(f"{API}/form-terms", query_string={"terms": "前门 李四"}))
    assert by_name["forms"] == 2 and by_name["unmatched"] == []


def test_watchlist_add_remove_scope_and_csv(client):  # type: ignore[no-untyped-def]
    _, http, db = client
    view = _ok(http.get(f"{API}/watchlist"))
    assert view["scope"] == "all" and view["items"] == []
    view = _ok(http.post(f"{API}/watchlist", json={"action": "scope", "scope": "watchlist"}))
    assert view["configIssue"] == "待配置：关注清单为空"  # S9
    added = {"action": "add", "serials": ["F610M-3D-0001", "F610M-3D-0099", "F610M-3D-0001"]}
    view = _ok(http.post(f"{API}/watchlist", json=added))
    assert [(i["serial"], i["found"]) for i in view["items"]] == [("F610M-3D-0001", True), ("F610M-3D-0099", False)]
    assert view["missing"] == ["F610M-3D-0099"] and view["configIssue"] is None  # S8：未找到但留在清单里
    csv_text = http.get(f"{API}/watchlist.csv").data.decode("utf-8-sig")
    assert csv_text.splitlines() == ["流水单号,状态", "F610M-3D-0001,已找到", "F610M-3D-0099,未找到"]
    view = _ok(http.post(f"{API}/watchlist", json={"action": "remove", "serials": ["F610M-3D-0099"]}))
    assert view["count"] == 1
    # S21：每次修改都写进归档任务的配置审计
    with db.get_connection() as conn:
        audits = conn.execute(
            "SELECT COUNT(*) AS n FROM scheduled_archive_config_audit a JOIN scheduled_archive_jobs j "
            "ON j.id = a.job_id WHERE j.job_key = 'tdc_data_model'"
        ).fetchone()["n"]
    assert audits >= 3
    assert _ok(http.post(f"{API}/watchlist", json={"action": "clear"}))["count"] == 0


def test_watchlist_validation(client):  # type: ignore[no-untyped-def]
    _, http, _ = client
    assert http.post(f"{API}/watchlist", json={"action": "nope"}).status_code == 400
    assert http.post(f"{API}/watchlist", json={"action": "add", "serials": "x"}).status_code == 400
    assert http.post(f"{API}/watchlist", json={"action": "add", "serials": ["a\nb"]}).status_code == 400
    assert http.post(f"{API}/watchlist", json={"action": "scope", "scope": "x"}).status_code == 400


def test_sync_settings_lists_real_sources_and_audits_binding_edits(client):  # type: ignore[no-untyped-def]  # S12–S15、S21
    _, http, db = client
    items = {item["deliverableId"]: item for item in _ok(http.get(f"{API}/sync-settings"))["items"]}
    data_model = items["VPI-T2-D5"]
    assert data_model["kind"] == "binding" and data_model["watchlist"] == {"scope": "all", "count": 0}
    assert "统一域账号凭据" in data_model["missing"]
    snapshot_driven = [item for item in items.values() if item["kind"] == "archive"]
    assert snapshot_driven and all(item["jobKey"] for item in snapshot_driven)

    before_binding = db.get_project_status_update_policy("VPI-T2-D5")["binding"]
    before_revision = int(before_binding["sync_config_revision"] or 0)
    assert before_binding["interval_minutes"] is None
    assert "sectionScope" not in json.loads(before_binding["match_rule_json"])
    with db.get_connection() as conn:
        before_audit_id = int(conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM project_status_binding_config_audit "
            "WHERE deliverable_id = ?", ("VPI-T2-D5",),
        ).fetchone()[0])
        before_snapshots = [dict(row) for row in conn.execute(
            "SELECT * FROM project_status_analysis_snapshots "
            "WHERE deliverable_id = ? ORDER BY snapshot_at, id", ("VPI-T2-D5",),
        ).fetchall()]
        before_items = [dict(row) for row in conn.execute(
            "SELECT * FROM project_status_analysis_items "
            "WHERE deliverable_id = ? ORDER BY item_key", ("VPI-T2-D5",),
        ).fetchall()]
        before_cursor = conn.execute(
            "SELECT cursor_json FROM project_status_update_bindings "
            "WHERE deliverable_id = ?", ("VPI-T2-D5",),
        ).fetchone()[0]
    # 列表里改间隔走宿主既有 update-policy 接口，并写入专用绑定配置审计（S14、S21）
    response = http.patch("/api/project-status/deliverables/VPI-T2-D5/update-policy", json={"intervalMinutes": 30})
    assert response.get_json()["ok"] is True, response.get_json()
    after = {item["deliverableId"]: item for item in _ok(http.get(f"{API}/sync-settings"))["items"]}
    assert after["VPI-T2-D5"]["intervalMinutes"] == 30
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM project_status_binding_config_audit "
            "WHERE deliverable_id = ? AND id > ? ORDER BY id",
            ("VPI-T2-D5", before_audit_id),
        ).fetchall()
        after_snapshots = [dict(row) for row in conn.execute(
            "SELECT * FROM project_status_analysis_snapshots "
            "WHERE deliverable_id = ? ORDER BY snapshot_at, id", ("VPI-T2-D5",),
        ).fetchall()]
        after_items = [dict(row) for row in conn.execute(
            "SELECT * FROM project_status_analysis_items "
            "WHERE deliverable_id = ? ORDER BY item_key", ("VPI-T2-D5",),
        ).fetchall()]
        after_cursor = conn.execute(
            "SELECT cursor_json FROM project_status_update_bindings "
            "WHERE deliverable_id = ?", ("VPI-T2-D5",),
        ).fetchone()[0]
    assert len(rows) == 1
    row = rows[0]
    assert row["deliverable_id"] == "VPI-T2-D5"
    assert row["actor"] == "local_web"
    assert row["event_type"] == "configuration_updated"
    assert row["config_revision"] == before_revision
    assert isinstance(row["created_at"], str) and row["created_at"]
    assert json.loads(row["changes_json"]) == {
        "payloadVersion": 2, "source": "deliverable_sync_settings", "deliverableId": "VPI-T2-D5",
        "beforeRevision": before_revision, "afterRevision": before_revision,
        "scope": None,
        "changes": {
            "intervalMinutes": {"from": None, "to": 30, "changed": True}
        },
    }
    after_binding = db.get_project_status_update_policy("VPI-T2-D5")["binding"]
    assert after_binding["interval_minutes"] == 30
    assert after_binding["sync_config_revision"] == before_revision
    assert after_cursor == before_cursor
    assert after_snapshots == before_snapshots
    assert after_items == before_items

    # 关注清单范围但清单为空：同步设置写明缺「关注清单」（S15、S9）
    _ok(http.post(f"{API}/watchlist", json={"action": "scope", "scope": "watchlist"}))
    items = {item["deliverableId"]: item for item in _ok(http.get(f"{API}/sync-settings"))["items"]}
    assert "关注清单" in items["VPI-T2-D5"]["missing"]


def test_partial_policy_patch_keeps_scheduler_interval(client):  # type: ignore[no-untyped-def]  # 审计
    _, http, db = client
    before = db.get_project_status_update_policy("VPI-T2-D5")["binding"]["interval_minutes"]
    assert before is None
    response = http.patch("/api/project-status/deliverables/VPI-T2-D5/update-policy", json={"mode": "automatic"})
    assert response.get_json()["ok"] is True, response.get_json()
    assert db.get_project_status_update_policy("VPI-T2-D5")["binding"]["interval_minutes"] is None


def test_serials_added_after_watchlist_sync_are_not_marked_missing(client):  # type: ignore[no-untyped-def]  # 审计
    _, http, db = client
    rows = [{"流水单号": "F610M-3D-0001", "零件名称": "前门内板", "状态": "进行中"}]
    positional = [{"values": [row.get(h) for h in HEADERS], "sheetName": "Sheet1"} for row in rows]
    db.publish_deliverable_form_snapshot(build_form_snapshot(
        "tdc_data_model", positional, snapshot_at="2026-10-03T09:00:00Z", source_run_id=2, source="test",
        coverage={"kind": "watchlist", "serials": ["F610M-3D-0001", "F610M-3D-0098"], "missing": ["F610M-3D-0098"]}))
    added = {"action": "add", "serials": ["F610M-3D-0001", "F610M-3D-0098", "F610M-3D-0002"]}
    view = _ok(http.post(f"{API}/watchlist", json=added))
    assert [(i["serial"], i["found"]) for i in view["items"]] == [
        ("F610M-3D-0001", True), ("F610M-3D-0098", False), ("F610M-3D-0002", None)]
