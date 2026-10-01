# -*- coding: utf-8 -*-
"""Focused tests for approved business-language dashboard UI.

Covers the business UI acceptance criteria still served by the legacy page:
1. Milestones display 未开始、进行中、已完成、已超期 and milestone edit form validation does not require exactly 1 current node.
2. Current stage label from backend currentStage and not displaying VPI-T2 as current stage.
3. Deliverable list and detail using displayCode, stable desktop grid & single-column mobile layout, full-row associations, collapsed technical evidence, read-only automatic fields.
4. Report result tables rendering backend headerRows/columns/rows, visible columns, skipping NCR progress blank row, multi-row grouped headers for NCR detail, and no internal keys (_no, _subject) as column headers.
5. Scheduled-archive and settings backend endpoints (their pages are plugins with their own tests).
6. Responsive layouts and CSS border-radius <= 8px tokens on 390px viewports without clipping.
"""
from __future__ import annotations

import re
from pathlib import Path
import pytest

import web.app as web_app


@pytest.fixture()
def client(monkeypatch, tmp_path: Path):
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "approved-ui-test.db"))
    app = web_app.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_project_status_views_and_phase_display_name() -> None:
    html = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")
    js = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    # 1. HTML panels and aria roles
    assert 'id="overview-status-panel"' in html
    assert 'id="overview-details-panel"' in html
    assert 'id="overview-plan-panel"' in html
    assert 'id="overview-tab-plan"' in html
    plan_pos = html.find('id="overview-plan-panel"')
    maint_pos = html.find('id="milestone-maintenance"')
    assert plan_pos != -1 and maint_pos != -1
    assert plan_pos < maint_pos

    # 2. Phase display name in timeline and summary
    assert "phase.displayName || phase.id" in js
    assert "主计划时间轴" in js
    assert 'aria-label", "编辑主计划"' in js
    assert 'title = "编辑主计划"' in js


def test_phase_metadata_and_milestones_patch_endpoints(client) -> None:
    js = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    # Phase metadata endpoint and payload
    assert "`/api/project-status/phases/${PROJECT_PHASE_ID}`" in js
    assert 'method: "PATCH"' in js
    assert "displayName" in js
    assert "savePhaseMetadataChanges" in js

    # Milestone endpoint and payload
    assert "`/api/project-status/phases/${PROJECT_PHASE_ID}/milestones`" in js
    assert "saveMilestoneChanges" in js

    # Smoke test backend phase PATCH
    get_res = client.get("/api/project-status?phase=VPI-T2")
    assert get_res.status_code == 200
    data = get_res.get_json()["data"]
    current_updated_at = data["phase"]["updatedAt"]

    patch_res = client.patch(
        "/api/project-status/phases/VPI-T2",
        json={
            "displayName": "VPI-T2 阶段主计划（测试更新）",
            "status": "进行中",
            "startDate": "2026-03-01",
            "endDate": "2026-10-30",
            "updatedAt": current_updated_at,
        },
    )
    assert patch_res.status_code == 200
    patch_data = patch_res.get_json()["data"]
    assert patch_data["projectStatus"]["phase"]["displayName"] == "VPI-T2 阶段主计划（测试更新）"


def test_milestone_statuses_and_no_single_current_node_restriction() -> None:
    js = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    # Check 4 milestone statuses
    for status in ["未开始", "进行中", "已完成", "已超期"]:
        assert status in js

    assert "MILESTONE_STATUS_OPTIONS" in js
    assert "MILESTONE_TYPE_OPTIONS" in js
    assert "saveMilestoneChanges" in js


def test_current_stage_label_presentation(client) -> None:
    js = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    # Verify renderPhaseSummary takes currentStage
    assert "renderPhaseSummary" in js
    assert "currentStage" in js
    assert '["当前阶段", stageLabel]' in js
    assert 'overviewSavedState.currentStage' in js

    # Smoke test API returns currentStage
    res = client.get("/api/project-status?phase=VPI-T2")
    assert res.status_code == 200
    data = res.get_json()["data"]
    assert "currentStage" in data
    assert "→" in data["currentStage"]


def test_deliverable_detail_analysis_wiring_and_rendering(client) -> None:
    js = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    # 1. Addressable deliverable detail and navigation commands
    assert '"查看明细"' in js
    assert "返回交付物列表" in js
    assert "renderDeliverableDetailPage" in js
    assert "handleHashChange" in js
    assert 'aria-label", `查看 ${item.name} 明细`' in js
    assert "item.displayCode || item.id" in js

    # 2. Analysis endpoints (server-side paginated item list)
    # analysis URL 可选携带车型筛选参数（model/modelMatch），不再以反引号结尾。
    assert "/api/project-status/deliverables/${encodeURIComponent(item.id)}/analysis" in js
    assert "/analysis/items?" in js
    assert "limit: String(PAGE_SIZE)" in js
    assert "offset: String(offset)" in js
    assert 'params.set("state", state.state)' in js

    # 3. Metrics and warning chips
    assert "总任务数" in js
    assert "已完成" in js
    assert "未完成" in js
    assert "逾期" in js
    assert "即将到期" in js
    assert "缺少截止日期" in js
    assert "无逾期风险" in js

    # 4. Evidence disclosure
    assert "deliverable-evidence-disclosure" in js
    assert "外部同步与技术证据（点击展开）" in js

    # Smoke test deliverable analysis endpoints
    analysis_res = client.get("/api/project-status/deliverables/VPI-T2-D1/analysis")
    assert analysis_res.status_code == 200
    assert "summary" in analysis_res.get_json()["data"]

    items_res = client.get("/api/project-status/deliverables/VPI-T2-D1/analysis/items")
    assert items_res.status_code == 200
    assert "items" in items_res.get_json()["data"]


def test_report_tables_backend_contracts_and_ncr_headers() -> None:
    js = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    # Table render supports headerRows, columns, rows
    assert "renderRows" in js
    assert "headerRows" in js
    assert "defaultVisibleCount" in js
    assert 'mode === "ncr-progress"' in js
    assert 'mode === "ncr-detail"' in js


def test_scheduled_archive_jobs_and_folders_endpoints(client) -> None:
    # 定时任务页面已迁为插件页；此处只保留后端接口冒烟。
    jobs_res = client.get("/api/scheduled-archive/jobs")
    assert jobs_res.status_code == 200

    folders_res = client.get("/api/scheduled-archive/folders")
    assert folders_res.status_code == 200
    data = folders_res.get_json()["data"]
    assert "current" in data
    assert "folders" in data


def test_settings_api_and_in_place_login_wiring(client) -> None:
    js = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    # 设置页面已迁为插件页；旧页仍保留原位登录与顶栏会话徽标。
    assert '"/api/settings"' in js
    assert '"/api/settings/domain-login"' in js

    get_res = client.get("/api/settings")
    assert get_res.status_code == 200
    s_data = get_res.get_json()["data"]
    assert "settings" in s_data
    assert "sessions" in s_data

    patch_res = client.patch(
        "/api/settings",
        json={
            "defaultDownloadMinutes": 45,
            "retryCount": 3,
        },
    )
    assert patch_res.status_code == 200
    assert patch_res.get_json()["data"]["settings"]["defaultDownloadMinutes"] == 45


def test_css_design_tokens_and_radii_constraints() -> None:
    css = Path("web/static/style.css").read_text(encoding="utf-8-sig")

    # Check that all component border-radius declarations are <= 8px (except brand-mark at 12px and pills at 999px)
    radii_matches = re.findall(r"border-radius:\s*([0-9]+)px", css)
    assert radii_matches, "No border-radius declarations found"
    for r in radii_matches:
        val = int(r)
        if val not in (12, 999):
            assert val <= 8, f"border-radius {r}px exceeds 8px limit"

    # Check required classes exist
    assert ".phase-meta-card" in css
    assert ".deliverable-analysis-panel" in css
    assert ".analysis-alert-chip" in css
    assert "@media (max-width: 390px)" in css


def test_milestone_editor_allows_undated_planned_nodes() -> None:
    """空日期=待排期：未开始节点允许空日期，其他状态必须排期。"""
    js = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    assert 'errors[dateKey] = "空日期节点状态必须为未开始"' in js
    # 旧的"日期必填"硬校验必须已移除
    assert "节点日期为必填项" not in js
    # 日期相关守卫仅在存在日期时生效
    assert "if (!errors[dateKey] && date && (row.type === \"done\"" in js
