# -*- coding: utf-8 -*-
"""Focused tests for the VSE Toolbox 项目状态概览 redesign.

Covers static HTML/CSS/JS structure, the saved-state loader and inline
deliverable editor contract, tab and detail-expansion accessibility behavior,
read-only overview guards, and the preserved `/api/overview` Flask route.
"""

from __future__ import annotations

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
    start = html_text.index('id="overview"')
    end = html_text.index('id="aras-panel"')
    return html_text[start:end]


def test_index_loads_new_overview_and_preserves_navigation(client) -> None:  # type: ignore[no-untyped-def]
    resp = client.get("/")
    assert resp.status_code == 200
    html_text = resp.get_data(as_text=True)

    assert "项目工作台" in html_text
    assert "<h2 id=\"session-title\">项目状态</h2>" in html_text
    assert 'class="panel-section project-overview"' in html_text
    assert 'data-panel-link="aras-panel"' in html_text
    assert 'data-panel-link="deliverables"' in html_text
    assert 'id="deliverables"' in html_text
    assert "deliverables-workbench" in html_text

    for marker in ("projects-body", "deliverables-body", "feishu-body", "metric-card", "overview-grid"):
        assert marker not in html_text


def test_overview_static_structure_and_unique_ids() -> None:
    html_text = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")
    overview_html = _overview_html(html_text)

    for marker in (
        "role=\"tablist\"",
        "role=\"tab\"",
        "role=\"tabpanel\"",
        "aria-selected=\"true\"",
        "aria-selected=\"false\"",
        'aria-controls="overview-status-panel"',
        'aria-controls="overview-details-panel"',
        'id="overview-status-panel"',
        'id="overview-details-panel"',
        'id="overview-timeline-body"',
        'id="overview-phase-summary"',
        'id="overview-progress-grid"',
        'id="overview-risk-summary"',
        'id="overview-details-summary"',
        'id="overview-details-body"',
        "overview-switch",
        "milestone-timeline",
        "phase-summary",
        "deliverable-progress-grid",
        "risk-summary",
        "overview-details-table",
        "visually-hidden",
    ):
        assert marker in overview_html

    ids = re.findall(r'id="([^"]+)"', html_text)
    assert len(ids) == len(set(ids))

    assert "<input" not in overview_html
    assert "<select" not in overview_html
    assert "<textarea" not in overview_html
    assert "contenteditable" not in overview_html
    for forbidden in ("编辑", "保存", "删除"):
        assert forbidden not in overview_html


def test_overview_tabs_aria_contract() -> None:
    html_text = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")
    tabs = re.findall(r'<button[^>]*role="tab"[^>]*>', html_text)
    assert len(tabs) == 2
    for tab in tabs:
        assert 'aria-selected="' in tab
        assert 'aria-controls="' in tab
    panels = re.findall(r'<div[^>]*role="tabpanel"[^>]*>', html_text)
    assert len(panels) == 2
    for panel in panels:
        assert 'aria-labelledby="' in panel
    assert 'id="overview-details-panel" class="overview-tabpanel" role="tabpanel" aria-labelledby="overview-tab-details" hidden' in html_text


def test_overview_server_loader_contract() -> None:
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    assert "const OVERVIEW_MOCK_DATA" not in js_text
    assert "function loadProjectOverview" in js_text
    assert 'fetch("/api/project-status?phase=VPI-T2"' in js_text
    assert "overviewSavedState" in js_text
    assert "overviewLoadError" in js_text
    assert "overview-retry-btn" in js_text
    assert "尚未配置关联模型" in js_text
    assert "contenteditable" not in js_text
    assert 'fetch("/api/overview")' not in js_text
    storage_lines = [line for line in js_text.splitlines() if "localStorage" in line]
    assert storage_lines
    assert all("THEME_KEY" in line for line in storage_lines)


def test_overview_editor_contract() -> None:
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    start = js_text.index("const OVERVIEW_DETAIL_COLUMNS")
    end = js_text.index("function parseHeaders")
    overview_js = js_text[start:end]

    assert "/api/project-status/deliverables/" in js_text
    assert 'method: "PATCH"' in js_text
    assert '"Content-Type"' in js_text
    assert '"application/json"' in js_text
    assert "updatedAt: item.updatedAt" in js_text
    for status in ("已完成", "进行中", "待审批", "已逾期"):
        assert f'"{status}"' in overview_js
    for field in ("status", "owner", "plannedDate", "actualDate", "progress", "note"):
        assert f'"{field}"' in overview_js
    assert "尚未配置关联模型" in overview_js
    assert "progress < 0" in overview_js
    assert "progress > 100" in overview_js
    assert "progress !== 100" in overview_js
    assert 'status === "已完成"' in overview_js
    assert "负责人为必填项" in overview_js
    assert "计划完成日期为必填项" in overview_js
    assert "beforeunload" in overview_js
    assert "window.confirm" in overview_js
    assert "saveButton.disabled = saving" in overview_js
    assert "function loadDeliverablePolicy" in overview_js
    assert "function renderDeliverablePolicyEditor" in overview_js
    assert "更新方式已保存" in overview_js
    assert "TDC 稳定编号尚未确认" in overview_js
    assert "fieldAuthority" in overview_js


def test_overview_js_safe_dom_and_binding_contract() -> None:
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    start = js_text.index("const OVERVIEW_DETAIL_COLUMNS")
    end = js_text.index("function parseHeaders")
    overview_js = js_text[start:end]

    for marker in (
        "function setupOverviewTabs",
        "function renderProjectOverview",
        "function renderDeliverableDetails",
        "function loadProjectOverview",
        "function startDeliverableEdit",
        "function validateDeliverableDraft",
        "function saveDeliverableChanges",
        "function cancelDeliverableEdit",
        "function guardUnsavedOverviewChanges",
        "function setupOverviewGuards",
        "function renderMilestoneTimeline",
        "function renderPhaseSummary",
        "function renderDeliverableProgress",
        "function renderRiskSummary",
        "function toggleDeliverableDetail",
        "document.createElement",
        "document.createElementNS",
        ".textContent",
        ".appendChild",
        ".append(",
        'setAttribute("aria-expanded"',
        'setAttribute("aria-controls"',
        "event.stopPropagation()",
        "ArrowRight",
        "ArrowLeft",
        'event.key === "Home"',
        'event.key === "End"',
        "renderOverviewLoading",
        "renderOverviewEmpty",
        "renderOverviewError",
    ):
        assert marker in overview_js

    assert "innerHTML" not in overview_js
    assert "console.log" not in js_text
    assert 'fetch("/api/overview")' not in js_text
    assert "loadOverview" not in js_text
    assert "sessionStorage" not in js_text
    storage_lines = [line for line in js_text.splitlines() if "localStorage" in line]
    assert storage_lines
    assert all("THEME_KEY" in line for line in storage_lines)


def test_overview_css_contract() -> None:
    css_text = Path("web/static/style.css").read_text(encoding="utf-8-sig")
    start = css_text.index(".overview-tabpanel[hidden]")
    end = css_text.index(".loading,\n.is-empty")
    overview_css = css_text[start:end]

    for marker in (
        ".project-overview",
        ".overview-switch",
        ".overview-tab",
        ".milestone-node",
        ".deliverable-progress-grid",
        ".progress-ring",
        ".ring-visual",
        ".deliverable-detail-row",
        ".overview-details-table",
        ".overview-tabpanel[hidden]",
        ".overview-retry-btn",
        ".detail-edit",
        ".detail-edit svg",
        ".detail-association",
        ".association-empty",
        ".deliverable-policy-panel",
        ".policy-segmented",
        ".policy-field-check",
        ".policy-binding-state",
        ".policy-save-btn",
        ".edit-readonly-grid",
        ".edit-form-grid",
        ".edit-field",
        ".field-error",
        ".edit-form-actions",
        ".edit-save-btn",
        ".edit-cancel-btn",
    ):
        assert marker in overview_css

    assert "conic-gradient" in overview_css
    assert "linear-gradient" not in overview_css
    assert "box-shadow" not in overview_css
    assert "min-height: 40px" in overview_css
    assert "letter-spacing: 0" in css_text
    assert "letter-spacing: -" not in css_text
    assert "overflow-x: hidden" in css_text
    assert "border-radius: 16px" not in css_text
    assert css_text.count("border-radius: 12px") == 1
    assert "@media (prefers-reduced-motion: reduce)" in css_text

    ring_grid = re.search(
        r"@media \(max-width: 1024px\)[\s\S]*?\.deliverable-progress-grid\s*\{\s*grid-template-columns:\s*repeat\(3, minmax\(0, 1fr\)\);\s*\}",
        css_text,
    )
    assert ring_grid is not None

    mobile_break = css_text[css_text.index("@media (max-width: 560px)"):]
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in mobile_break
    assert ".deliverable-progress-grid .progress-ring:last-child" in mobile_break
    assert "grid-column: 1 / -1;" in mobile_break
    assert "content: attr(data-label);" in mobile_break
    assert ".overview-details-table thead" in mobile_break


def test_overview_api_route_contract_preserved(client) -> None:  # type: ignore[no-untyped-def]
    resp = client.get("/api/overview")
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body) == {"projects", "deliverables", "feishu"}
    assert isinstance(body["projects"], dict)
    assert isinstance(body["deliverables"], dict)
    assert set(body["feishu"]) == {"total", "synced"}


def test_overview_milestone_maintenance_static_structure() -> None:
    html_text = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")
    overview_html = _overview_html(html_text)
    details_start = overview_html.index('id="overview-details-panel"')
    details_section = overview_html[details_start:]

    assert "milestone-maintenance-band" in details_section
    assert 'id="milestone-maintenance"' in details_section
    assert details_section.index('id="milestone-maintenance"') < details_section.index('id="overview-details-summary"')
    assert "<input" not in overview_html
    assert "<select" not in overview_html
    assert "<textarea" not in overview_html
    assert "contenteditable" not in overview_html


def test_overview_milestone_editor_contract() -> None:
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    start = js_text.index("const OVERVIEW_DETAIL_COLUMNS")
    end = js_text.index("function parseHeaders")
    overview_js = js_text[start:end]

    for marker in (
        "function renderMilestoneMaintenance",
        "function openMilestoneEditor",
        "function startMilestoneEdit",
        "function validateMilestoneDraft",
        "function saveMilestoneChanges",
        "function cancelMilestoneEdit",
        "function renderMilestoneFieldErrors",
        "function renderMilestoneServerFieldErrors",
        '"/api/project-status/phases/VPI-T2/milestones"',
        'method: "PATCH"',
        "milestones: overviewDraft.rows.map",
        "updatedAt: overviewDraft.updatedAt",
        "sortOrder",
        'overviewDraft.kind === "milestones"',
        'editButton.addEventListener("click", openMilestoneEditor)',
        'document.getElementById("overview-tab-details")',
        "已达成",
        "当前目标节点",
        "计划节点",
        "必须且只能存在一个当前目标节点",
        "节点名称为必填项",
        "节点名称不能超过 100 个字符",
        "日期格式应为 YYYY-MM-DD",
        "节点日期不能晚于当前日期",
        "节点日期不能早于当前日期",
        "节点名称不能重复",
        "saveButton.disabled = saving",
        "beforeunload",
    ):
        assert marker in overview_js

    assert "innerHTML" not in overview_js
    assert "console.log" not in js_text
    assert "localStorage" not in overview_js


def test_overview_milestone_maintenance_css_contract() -> None:
    css_text = Path("web/static/style.css").read_text(encoding="utf-8-sig")
    start = css_text.index(".overview-tabpanel[hidden]")
    end = css_text.index(".loading,\n.is-empty")
    overview_css = css_text[start:end]

    for marker in (
        ".milestone-maintenance",
        ".timeline-edit-btn",
        ".timeline-head-actions",
        ".milestone-main-row",
        ".milestone-edit-row",
        ".milestone-field",
        ".milestone-icon-btn",
        ".milestone-move-btn",
        ".milestone-delete-btn",
        ".milestone-add-btn",
        "min-height: 40px",
    ):
        assert marker in overview_css

    mobile_break = css_text[css_text.index("@media (max-width: 560px)"):]
    assert ".milestone-edit-row" in mobile_break
    assert "grid-template-columns: 1fr;" in mobile_break
