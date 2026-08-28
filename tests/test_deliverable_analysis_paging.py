# -*- coding: utf-8 -*-
"""Tests for deliverable analysis pagination, department stacked chart, and car_type channel."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import pytest

from core.db_manager import DatabaseManager
from services.project_status_deliverable_analysis import (
    ProjectStatusDeliverableAnalysisService,
    normalize_analysis_rows,
    summarize_analysis_items,
)
import web.app as web_app


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(tmp_path / "test_paging.db")
    manager.init_database()
    return manager


@pytest.fixture()
def seeded_db(db: DatabaseManager) -> DatabaseManager:
    items = [
        # 质量科 (3 items: 1 completed, 2 incomplete)
        {
            "item_key": "Q-01",
            "title": "质量控制计划1",
            "department": "质量科",
            "owner": "张三",
            "display_number": "Q-01",
            "pending_signers": "",
            "source_status": "已完成",
            "is_completed": True,
            "planned_date": "2026-08-10",
            "actual_date": "2026-08-09",
            "fingerprint": "fp-q1",
        },
        {
            "item_key": "Q-02",
            "title": "质量控制计划2",
            "department": "质量科",
            "owner": "李四",
            "display_number": "Q-02",
            "pending_signers": "王总",
            "source_status": "进行中",
            "is_completed": False,
            "planned_date": "2026-08-15",
            "actual_date": None,
            "fingerprint": "fp-q2",
        },
        {
            "item_key": "Q-03",
            "title": "质量控制计划3",
            "department": "质量科",
            "owner": "王五",
            "display_number": "Q-03",
            "pending_signers": "",
            "source_status": "未开始",
            "is_completed": False,
            "planned_date": "2026-08-20",
            "actual_date": None,
            "fingerprint": "fp-q3",
        },
        # 车身科 (4 items: 2 completed, 2 incomplete)
        {
            "item_key": "B-01",
            "title": "车身强度分析1",
            "department": "车身科",
            "owner": "赵六",
            "display_number": "B-01",
            "pending_signers": "",
            "source_status": "已审批",
            "is_completed": True,
            "planned_date": "2026-08-11",
            "actual_date": "2026-08-11",
            "fingerprint": "fp-b1",
        },
        {
            "item_key": "B-02",
            "title": "车身强度分析2",
            "department": "车身科",
            "owner": "孙七",
            "display_number": "B-02",
            "pending_signers": "",
            "source_status": "通过",
            "is_completed": True,
            "planned_date": "2026-08-12",
            "actual_date": "2026-08-12",
            "fingerprint": "fp-b2",
        },
        {
            "item_key": "B-03",
            "title": "车身模具评审3",
            "department": "车身科",
            "owner": "周八",
            "display_number": "B-03",
            "pending_signers": "刘总",
            "source_status": "审批中",
            "is_completed": False,
            "planned_date": "2026-08-18",
            "actual_date": None,
            "fingerprint": "fp-b3",
        },
        {
            "item_key": "B-04",
            "title": "车身焊点检查4",
            "department": "车身科",
            "owner": "吴九",
            "display_number": "B-04",
            "pending_signers": "",
            "source_status": "已废弃",
            "is_completed": False,
            "planned_date": "2026-08-25",
            "actual_date": None,
            "fingerprint": "fp-b4",
        },
    ]
    snapshot = summarize_analysis_items(items, snapshot_at="2026-08-13 10:00:00", today=date(2026, 8, 13))
    db.replace_project_status_analysis_cache("VPI-T2-D1", 101, snapshot, items)
    return db


def test_db_layer_count_and_list_paging(seeded_db: DatabaseManager) -> None:
    # Total count and filtering
    assert seeded_db.count_project_status_analysis_items("VPI-T2-D1") == 7
    assert seeded_db.count_project_status_analysis_items("VPI-T2-D1", department="质量科") == 3
    assert seeded_db.count_project_status_analysis_items("VPI-T2-D1", department="车身科") == 4
    assert seeded_db.count_project_status_analysis_items("VPI-T2-D1", completed=True) == 3
    assert seeded_db.count_project_status_analysis_items("VPI-T2-D1", completed=False) == 4
    assert seeded_db.count_project_status_analysis_items("VPI-T2-D1", department="车身科", completed=True) == 2
    assert seeded_db.count_project_status_analysis_items("VPI-T2-D1", department="车身科", completed=False) == 2

    # Paging slices
    page1 = seeded_db.list_project_status_analysis_items("VPI-T2-D1", offset=0, limit=3)
    assert len(page1) == 3
    page2 = seeded_db.list_project_status_analysis_items("VPI-T2-D1", offset=3, limit=3)
    assert len(page2) == 3
    page3 = seeded_db.list_project_status_analysis_items("VPI-T2-D1", offset=6, limit=3)
    assert len(page3) == 1
    page_empty = seeded_db.list_project_status_analysis_items("VPI-T2-D1", offset=10, limit=3)
    assert page_empty == []

    # Combined filters and paging
    dept_comp = seeded_db.list_project_status_analysis_items(
        "VPI-T2-D1",
        department="车身科",
        completed=True,
        offset=0,
        limit=10,
    )
    assert len(dept_comp) == 2
    assert all(row["department"] == "车身科" and row["is_completed"] == 1 for row in dept_comp)


def test_service_layer_overview_and_items(seeded_db: DatabaseManager) -> None:
    service = ProjectStatusDeliverableAnalysisService(seeded_db, clock=lambda: date(2026, 8, 13))

    # Overview with car_type
    overview = service.overview("VPI-T2-D1", car_type="E262S")
    assert overview["hasCache"] is True
    assert overview["carType"] == "E262S"
    assert overview["summary"]["total"] == 7
    assert overview["summary"]["completed"] == 3
    assert overview["summary"]["incomplete"] == 4

    # Items paged path: completed
    res_comp = service.items("VPI-T2-D1", state="completed", offset=0, limit=5, car_type="E262S")
    assert res_comp["total"] == 3
    assert len(res_comp["items"]) == 3
    assert res_comp["offset"] == 0
    assert res_comp["limit"] == 5
    assert res_comp["carType"] == "E262S"
    assert all(i["completed"] is True for i in res_comp["items"])

    # Items paged path: incomplete with offset
    res_incomp = service.items("VPI-T2-D1", state="incomplete", offset=1, limit=2)
    assert res_incomp["total"] == 4
    assert len(res_incomp["items"]) == 2
    assert res_incomp["offset"] == 1
    assert res_incomp["limit"] == 2
    assert all(i["completed"] is False for i in res_incomp["items"])

    # Alert validation and combinations
    with pytest.raises(ValueError, match="unsupported state filter"):
        service.items("VPI-T2-D1", state="invalid_state")

    with pytest.raises(ValueError, match="unsupported alert filter"):
        service.items("VPI-T2-D1", alert="invalid_alert")

    with pytest.raises(ValueError, match="alert filter cannot be combined with state/offset pagination"):
        service.items("VPI-T2-D1", alert="overdue", state="completed")

    with pytest.raises(ValueError, match="alert filter cannot be combined with state/offset pagination"):
        service.items("VPI-T2-D1", alert="overdue", offset=1)

    # Alert path returns legacy shape
    alert_res = service.items("VPI-T2-D1", alert="missing_due_date")
    assert "items" in alert_res
    assert "total" in alert_res
    assert "offset" in alert_res
    assert "limit" in alert_res


@pytest.fixture()
def client(monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    db_instance = DatabaseManager(tmp_path / "project-status-paging.db")
    db_instance.init_database()
    # Seed analysis items
    items = [
        {
            "item_key": f"IT-{i:02d}",
            "title": f"任务-{i}",
            "department": "车身科" if i % 2 == 0 else "质量科",
            "owner": "工程师",
            "display_number": f"IT-{i:02d}",
            "pending_signers": "",
            "source_status": "已完成" if i < 3 else "进行中",
            "is_completed": i < 3,
            "planned_date": "2026-08-20",
            "actual_date": "2026-08-19" if i < 3 else None,
            "fingerprint": f"fp-{i}",
        }
        for i in range(6)
    ]
    snapshot = summarize_analysis_items(items, snapshot_at="2026-08-13 10:00:00", today=date(2026, 8, 13))
    db_instance.replace_project_status_analysis_cache("VPI-T2-D1", 1, snapshot, items)

    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_instance)
    app = web_app.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_api_deliverable_analysis_overview_and_items_routing(client) -> None:
    # Overview with carType
    res = client.get("/api/project-status/deliverables/VPI-T2-D1/analysis?carType=E262S&trendLimit=10")
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body["data"]["carType"] == "E262S"

    # Overview validations
    assert client.get("/api/project-status/deliverables/VPI-T2-D1/analysis?trendLimit=99").status_code == 422
    assert client.get(f"/api/project-status/deliverables/VPI-T2-D1/analysis?carType={'a'*85}").status_code == 422
    assert client.get("/api/project-status/deliverables/non-existent/analysis").status_code == 404

    # Items paged endpoint: happy path
    items_res = client.get("/api/project-status/deliverables/VPI-T2-D1/analysis/items?state=completed&offset=0&limit=50&carType=E262S")
    assert items_res.status_code == 200
    items_body = items_res.get_json()
    assert items_body["ok"] is True
    assert items_body["data"]["total"] == 3
    assert len(items_body["data"]["items"]) == 3
    assert items_body["data"]["offset"] == 0
    assert items_body["data"]["limit"] == 50
    assert items_body["data"]["carType"] == "E262S"

    # Items paged endpoint: state=all or incomplete or department filter
    all_res = client.get("/api/project-status/deliverables/VPI-T2-D1/analysis/items?state=all")
    assert all_res.status_code == 200
    assert all_res.get_json()["data"]["total"] == 6

    incomp_res = client.get("/api/project-status/deliverables/VPI-T2-D1/analysis/items?state=incomplete")
    assert incomp_res.status_code == 200
    assert incomp_res.get_json()["data"]["total"] == 3

    dept_res = client.get("/api/project-status/deliverables/VPI-T2-D1/analysis/items?department=%E8%BD%A6%E8%BA%AB%E7%A7%91&state=completed")
    assert dept_res.status_code == 200
    assert dept_res.get_json()["data"]["total"] == 2

    # Items parameter errors
    assert client.get("/api/project-status/deliverables/VPI-T2-D1/analysis/items?state=bogus").status_code == 422
    assert client.get("/api/project-status/deliverables/VPI-T2-D1/analysis/items?offset=-1").status_code == 422
    assert client.get("/api/project-status/deliverables/VPI-T2-D1/analysis/items?offset=100001").status_code == 422
    assert client.get(f"/api/project-status/deliverables/VPI-T2-D1/analysis/items?department={'d'*125}").status_code == 422
    assert client.get(f"/api/project-status/deliverables/VPI-T2-D1/analysis/items?carType={'c'*85}").status_code == 422
    assert client.get("/api/project-status/deliverables/VPI-T2-D1/analysis/items?limit=0").status_code == 422
    assert client.get("/api/project-status/deliverables/VPI-T2-D1/analysis/items?limit=501").status_code == 422
    assert client.get("/api/project-status/deliverables/VPI-T2-D1/analysis/items?alert=overdue&state=completed").status_code == 422
    assert client.get("/api/project-status/deliverables/VPI-T2-D1/analysis/items?alert=overdue&offset=5").status_code == 422
    assert client.get("/api/project-status/deliverables/non-existent/analysis/items").status_code == 404


def test_static_regression_analysis_view_elements() -> None:
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    css_text = Path("web/static/style.css").read_text(encoding="utf-8-sig")

    # App.js markers
    assert "analysis-dept-bar-row" in js_text
    assert "analysis-dept-bar-fill is-completed" in js_text
    assert "analysis-items-pager" in js_text
    assert "aria-pressed" in js_text

    # Verify analysis code contains no innerHTML
    analysis_block_start = js_text.index("function renderDepartmentDoneChart")
    analysis_block_end = js_text.index("function renderTrendSvgChart")
    analysis_code = js_text[analysis_block_start:analysis_block_end]
    assert "innerHTML" not in analysis_code
    assert "insertAdjacentHTML" not in analysis_code

    # Style.css markers
    assert ".analysis-dept-bar-row" in css_text
    assert ".analysis-dept-bar-track" in css_text
    assert ".analysis-dept-bar-fill" in css_text
    assert ".analysis-items-toolbar" in css_text
    assert ".analysis-status-chip" in css_text
    assert "@media (max-width: 560px)" in css_text
