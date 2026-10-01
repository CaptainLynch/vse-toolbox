# -*- coding: utf-8 -*-
"""Focused tests for the VSE Toolbox 项目状态概览 redesign.

Covers static HTML/CSS/JS structure, the saved-state loader and inline
deliverable editor contract, tab and detail-expansion accessibility behavior,
read-only overview guards, and the preserved `/api/overview` Flask route.
"""

from __future__ import annotations

import json
import re
import subprocess
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


def test_index_loads_new_overview_and_preserves_navigation(client) -> None:  # type: ignore[no-untyped-def]
    resp = client.get("/")
    assert resp.status_code == 200
    html_text = resp.get_data(as_text=True)

    assert "项目工作台" in html_text
    assert "<h2 id=\"session-title\">项目状态</h2>" in html_text
    assert 'class="panel-section project-overview"' in html_text
    # 6 main top bar navigation domains
    assert 'data-panel-link="overview"' in html_text
    assert 'data-panel-link="deliverables"' in html_text
    # 系统查询 / Excel / 自动归档 / 设置 已迁成插件，导航由插件清单生成。
    assert 'id="plugin-host"' in html_text
    assert 'id="deliverables"' in html_text
    assert 'id="excel-tasks"' not in html_text
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
        'id="overview-details-summary"',
        'id="overview-details-body"',
        "overview-switch",
        "milestone-timeline",
        "phase-summary",
        "deliverable-progress-grid",
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
    assert len(tabs) == 3
    for tab in tabs:
        assert 'aria-selected="' in tab
        assert 'aria-controls="' in tab
    panels = re.findall(r'<div[^>]*role="tabpanel"[^>]*>', html_text)
    assert len(panels) == 3
    for panel in panels:
        assert 'aria-labelledby="' in panel
    assert 'id="overview-details-panel" class="overview-tabpanel" role="tabpanel" aria-labelledby="overview-tab-details" hidden' in html_text


def test_overview_server_loader_contract() -> None:
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    assert "const OVERVIEW_MOCK_DATA" not in js_text
    assert "function loadProjectOverview" in js_text
    assert 'const PROJECT_PHASE_ID = "VPI-T2";' in js_text
    assert "fetch(`/api/project-status?phase=${PROJECT_PHASE_ID}`" in js_text
    assert "overviewSavedState" in js_text
    assert "overviewLoadError" in js_text
    assert "overview-retry-btn" in js_text
    assert "尚未配置关联模型" in js_text
    assert "contenteditable" not in js_text
    assert 'fetch("/api/overview")' not in js_text
    storage_lines = [line for line in js_text.splitlines() if "localStorage" in line]
    assert storage_lines
    assert all("THEME_KEY" in line or "GRID_COLUMN_PREF_KEY" in line for line in storage_lines)


def test_overview_editor_contract() -> None:
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    overview_js = _js_slice(js_text, "const OVERVIEW_DETAIL_COLUMNS", "function parseHeaders")

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
    assert "function renderSyncBindingEditor" in overview_js
    assert "renderDeliverablePolicyEditor" not in overview_js
    assert "更新方式已保存" in overview_js
    assert "fieldAuthority" in overview_js


def test_overview_js_safe_dom_and_binding_contract() -> None:
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    overview_js = _js_slice(js_text, "const OVERVIEW_DETAIL_COLUMNS", "function parseHeaders")

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
    assert "loadOverview(" not in js_text
    assert "sessionStorage" not in js_text
    storage_lines = [line for line in js_text.splitlines() if "localStorage" in line]
    assert storage_lines
    assert all("THEME_KEY" in line or "GRID_COLUMN_PREF_KEY" in line for line in storage_lines)


def _css_slice(css_text: str, start_marker: str, end_marker: str) -> str:
    start = css_text.find(start_marker)
    assert start != -1, f"Start marker '{start_marker}' not found"
    end = css_text.find(end_marker, start)
    assert end != -1, f"End marker '{end_marker}' not found after '{start_marker}'"
    return css_text[start:end]


def test_overview_css_contract() -> None:
    css_text = Path("web/static/style.css").read_text(encoding="utf-8-sig")
    overview_css = _css_slice(css_text, ".overview-tabpanel[hidden]", ".loading")

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

    assert "milestone-maintenance-band" in overview_html
    assert 'id="milestone-maintenance"' in overview_html
    assert 'id="overview-details-summary"' in overview_html
    summary_pos = overview_html.find('id="overview-details-summary"')
    maint_pos = overview_html.find('id="milestone-maintenance"')
    assert summary_pos != -1 and maint_pos != -1
    assert summary_pos < maint_pos
    assert "<input" not in overview_html
    assert "<select" not in overview_html
    assert "<textarea" not in overview_html
    assert "contenteditable" not in overview_html


def test_overview_milestone_editor_contract() -> None:
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    overview_js = _js_slice(js_text, "const LEGACY_MILESTONE_TYPES", "function parseHeaders")

    for marker in (
        "function renderMilestoneMaintenance",
        "function openMilestoneEditor",
        "function startMilestoneEdit",
        "function validateMilestoneDraft",
        "function saveMilestoneChanges",
        "function cancelMilestoneEdit",
        "function renderMilestoneFieldErrors",
        "function renderMilestoneServerFieldErrors",
        "`/api/project-status/phases/${PROJECT_PHASE_ID}/milestones`",
        'method: "PATCH"',
        "milestones: overviewDraft.rows.map",
        "updatedAt: overviewDraft.updatedAt",
        "sortOrder",
        'overviewDraft.kind === "milestones"',
        'editButton.addEventListener("click", () => startMilestoneEdit())',
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
    ):
        assert marker in overview_js

    assert "innerHTML" not in overview_js
    assert "console.log" not in js_text
    assert "localStorage" not in overview_js
    assert 'document.getElementById("overview-tab-plan")' in overview_js
    assert 'window.addEventListener("beforeunload"' in js_text


def test_overview_milestone_maintenance_css_contract() -> None:
    css_text = Path("web/static/style.css").read_text(encoding="utf-8-sig")
    overview_css = _css_slice(css_text, ".overview-tabpanel[hidden]", ".loading")

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
        ".milestone-request-message",
        "flex: 1 1 220px;",
        "min-height: 40px",
    ):
        assert marker in overview_css

    mobile_break = css_text[css_text.index("@media (max-width: 560px)"):]
    assert ".milestone-edit-row" in mobile_break
    assert "grid-template-columns: 1fr;" in mobile_break


def test_overview_deliverable_evidence_structure_and_labels() -> None:
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    source_js = _js_slice(js_text, "const DELIVERABLE_FIXED_SOURCES", "function formatArtifactSize")
    overview_js = source_js + _js_slice(js_text, "async function requestProjectStatusSync", "const analysisModelFilter")

    assert "function loadDeliverableEvidence" in overview_js
    assert "function renderDeliverableEvidence" in js_text

    for deliverable_id, source_label in (
        ("VPI-T2-D1", "仅手工维护"),
        ("VPI-T2-D2", "TDC SOR"),
        ("VPI-T2-D3", "ARAS EWO"),
        ("VPI-T2-D4", "TDC A 面（契约待验证）"),
        ("VPI-T2-D5", "数模设计审核流程报表"),
    ):
        assert f'"{deliverable_id}": "{source_label}"' in source_js

    assert "const hasConfirmedCount = confirmedCount !== null" in overview_js
    assert "Number.isFinite(Number(confirmedCount))" in overview_js
    assert 'mappingProgressText = hasConfirmedCount' in overview_js
    assert 'policy.credentialAvailable === true' in overview_js

    for field_name in ("owner", "plannedDate", "note"):
        assert field_name in overview_js
    for field_col in ("targetField", "sourceField", "currentValue", "candidateValue", "changed"):
        assert field_col in overview_js
    assert "暂无差异证据" in overview_js
    assert "建议状态映射：待用户确认（不自动应用）" in overview_js


def test_overview_interactive_aras_query_helper_contract() -> None:
    """EWO/PAA detail refresh shares a non-secret browser-mode query adapter."""
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    helper_js = _js_slice(
        js_text,
        "const INTERACTIVE_QUERY_ERROR_LABELS",
        "function renderTableState",
    )

    for marker in (
        "function buildInteractiveArasPayload",
        "function requestInteractiveArasQuery",
        "function interactiveQueryResultState",
        "function formatInteractiveArasResult",
        "function formatInteractiveArasError",
        "function renderInteractiveArasResult",
        'auth_mode: "browser"',
        "const config = ARAS_MODES[mode]",
        "queryState",
        "交互式查询",
        "本次结果未写入后台同步状态",
        "未认证",
        "服务不可用",
        "查询失败",
        "数据为空",
        "未匹配",
    ):
        assert marker in helper_js

    assert 'error.code' in js_text
    assert 'err.code = error && typeof error.code === "string"' in js_text
    assert "/api/aras/ewo/query" in js_text
    assert "/api/aras/paa/query" in js_text
    for forbidden in (
        "credentialRef",
        "credential_ref",
        "username",
        "password",
        "cookie",
        "cookies",
        "mapping",
        "leaseToken",
        "lease_token",
        "Authorization",
    ):
        assert forbidden not in helper_js


def test_ewo_detail_interactive_refresh_has_separate_background_sync_contract() -> None:
    """EWO detail refresh queries ARAS and never reuses the background sync route."""
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    detail_js = _js_slice(
        js_text,
        "function renderDeliverableDetailPage",
        "function toggleDeliverableDetail",
    )
    chart_js = _js_slice(
        js_text,
        "function renderDeliverableStatusChart",
        "async function runEwoInteractiveRefreshFromStatusChart",
    )
    interactive_js = _js_slice(
        js_text,
        "async function runEwoInteractiveRefreshFromStatusChart",
        "async function refreshEwoAnalysisFromStatusChart",
    )
    evidence_js = _js_slice(
        js_text,
        "function renderDeliverableEvidence",
        "// 4.",
    )

    assert "onInteractiveRefresh" in detail_js
    assert 'requestInteractiveArasQuery("ewo"' in interactive_js
    assert "renderInteractiveArasResult" in interactive_js
    assert "formatInteractiveArasError" in interactive_js
    assert "requestProjectStatusSync(item)" not in interactive_js
    assert "立即刷新（交互式查询）" in chart_js
    assert "交互式查询" in chart_js
    assert "interactiveButton.disabled = syncBusy" in chart_js
    assert "后台同步" in evidence_js
    assert "syncReady" in evidence_js


def test_interactive_refresh_buttons_and_errors_stay_separate_from_background_readiness() -> None:
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    ewo_interactive = _js_slice(
        js_text,
        "async function runEwoInteractiveRefreshFromStatusChart",
        "async function refreshEwoAnalysisFromStatusChart",
    )
    paa_interactive = _js_slice(
        js_text,
        "async function runPaaInteractiveRefresh",
        "function renderDeliverableDetailPage",
    )
    paa_detail = _js_slice(
        js_text,
        "function renderArchiveDeliverableDetailPage",
        "function toggleDeliverableDetail",
    )

    assert "formatInteractiveArasError" in ewo_interactive
    assert "formatInteractiveArasError" in paa_interactive
    assert "同步条件尚未满足" not in ewo_interactive
    assert "同步条件尚未满足" not in paa_interactive
    assert "interactiveButton.disabled = syncBusy" in js_text
    assert "syncButton.disabled = !job.enabled" in paa_detail
    assert "requestInteractiveArasQuery(\"ewo\"" in ewo_interactive
    assert "requestInteractiveArasQuery(\"paa\"" in paa_interactive
    assert "后台同步" in js_text
    assert "后台归档同步" in paa_detail


def test_overview_deliverable_evidence_restrictions_and_guard() -> None:
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    evidence_js = _js_slice(
        js_text,
        "async function requestProjectStatusSync",
        "const analysisModelFilter",
    )

    assert 'item.id === "VPI-T2-D1"' in evidence_js
    assert 'item.id === "VPI-T2-D4"' in evidence_js
    assert "TDC A 面契约待验证/阻断" in evidence_js

    assert "policy.enabled === true" in evidence_js
    assert "policy.credentialAvailable === true" in evidence_js
    assert "window.confirm" in evidence_js

    assert 'finalState === "busy" || outcome === "busy"' in evidence_js
    assert 'finalState === "success" && outcome === "completed"' in evidence_js
    assert 'finalState === "partial" || outcome === "partial"' in evidence_js
    assert 'finalState === "needs_attention" || outcome === "needs_attention"' in evidence_js

    assert "exitCode" not in evidence_js
    assert 'enabled: true' not in evidence_js
    assert 'method: "POST"' in evidence_js
    assert evidence_js.count('method: "POST"') == 1
    assert 'preview.candidates' not in evidence_js
    assert 'mapping.candidates' not in evidence_js

    for forbidden in (
        "credentialRef",
        "credential_ref",
        "credentialAlias",
        "cookie",
        "authorization",
        "lease_token",
        "leaseToken",
        "fingerprint",
        "candidate_summary_json",
        "raw_response",
    ):
        assert forbidden not in evidence_js


def test_overview_deliverable_evidence_api_and_sync_contract() -> None:
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    overview_js = _js_slice(js_text, "const OVERVIEW_DETAIL_COLUMNS", "function parseHeaders")

    assert "/api/project-status/deliverables/${encodeURIComponent(item.id)}/update-policy" in overview_js
    assert "/api/project-status/analytics" in overview_js
    assert "/api/project-status/deliverables/${encodeURIComponent(item.id)}/mapping-discovery" in overview_js
    assert "/api/project-status/deliverables/${encodeURIComponent(item.id)}/candidate-preview" in overview_js
    assert "/api/project-status/runs?deliverableId=${encodeURIComponent(item.id)}&limit=10" in overview_js
    assert "/api/project-status/runs/${encodeURIComponent(run.id)}/artifacts" in overview_js
    assert "/api/project-status/deliverables/${encodeURIComponent(item.id)}/sync-now" in overview_js

    for art_key in ("display_name", "artifact_type", "size_bytes", "relative_path", "sha256"):
        assert art_key in overview_js

    assert "innerHTML" not in overview_js


def test_overview_deliverable_evidence_accessibility_and_fallbacks() -> None:
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    overview_js = _js_slice(js_text, "const OVERVIEW_DETAIL_COLUMNS", "function parseHeaders")

    # Accessible state regions
    assert 'loadingP.setAttribute("role", "status")' in overview_js
    assert 'loadingP.setAttribute("aria-live", "polite")' in overview_js
    assert 'errBox.setAttribute("role", "alert")' in overview_js
    assert 'errBox.setAttribute("aria-live", "assertive")' in overview_js
    assert 'emptyDiff.setAttribute("role", "status")' in overview_js
    assert 'emptyMapping.setAttribute("role", "status")' in overview_js
    assert 'emptyRuns.setAttribute("role", "status")' in overview_js
    assert 'artBox.setAttribute("role", "status")' in overview_js
    assert 'artBox.setAttribute("role", "alert")' in overview_js
    assert 'retryArtifactBtn.type = "button"' in overview_js
    assert 'artifactBtn.click()' in overview_js

    # Unknown enum fallbacks
    assert '(state && map[state]) || "待确认"' in overview_js
    assert '(reason && map[reason]) || "待确认"' in overview_js
    assert '(trigger && map[trigger]) || "未知"' in overview_js
    assert '(state && map[state]) || "未知"' in overview_js
    assert 'labels[policy.syncState] || "未知"' in overview_js
    assert 'analytics.failureCount ?? 0' not in overview_js
    assert 'Number(confirmedCount) || 0' not in overview_js

    # Start and finish timestamps, and non-fabricated attempt
    assert "safeDisplayValue(run.finished_at || \"未知\")" in overview_js
    assert "safeDisplayValue(run.started_at || run.created_at || \"未知\")" in overview_js
    assert "run.attempt !== null && run.attempt !== undefined && run.attempt !== \"\"" in overview_js
    assert "artTd.colSpan = 7" in overview_js

    # Visible post-sync refresh preserving status
    assert "expandOverviewDetail(deliverableIndex, { text: resultStatusText, className: resultStatusClass })" in overview_js

    d1_guard = overview_js.find('if (item.id === "VPI-T2-D1")')
    d4_guard = overview_js.find('if (item.id === "VPI-T2-D4")')
    first_evidence_fetch = overview_js.find('const [policyRes, analyticsRes')
    sync_button = overview_js.find('const syncBtn = overviewEl')
    assert d1_guard != -1 and d4_guard != -1 and first_evidence_fetch != -1 and sync_button != -1
    assert d1_guard < d4_guard < first_evidence_fetch < sync_button


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


def test_overview_ewo_analysis_feedback_controls_are_searchable_multiselects() -> None:
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    css_text = Path("web/static/style.css").read_text(encoding="utf-8-sig")

    assert "analysis-multi-select" in js_text
    assert "createSearchMultiSelect" in js_text
    assert "departments" in js_text
    assert "stages" in js_text
    assert 'params.append("departments", department)' in js_text
    assert 'params.append("stages", stage)' in js_text
    assert "应用筛选" in js_text
    assert "清除筛选" in js_text
    assert "ewo-sync-summary" in js_text
    assert "刷新后台分析" in js_text
    assert "立即刷新（交互式查询）" in js_text
    assert ".analysis-multi-select" in css_text


def test_overview_ewo_second_round_ui_feedback_contract() -> None:
    """第二轮浏览器反馈：不透明候选框、大写阶段、两态状态列、签署人分行、更新方式与快照标签。"""
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    css_text = Path("web/static/style.css").read_text(encoding="utf-8-sig")

    # 1. 候选框与控件必须使用已定义的不透明主题变量，并具备层级/边框/阴影。
    options_block = _css_rule(css_text, ".analysis-multi-select-options")
    assert "background: var(--surface-card);" in options_block
    assert "z-index: 30" in options_block
    assert "border: 1px solid var(--hairline-strong);" in options_block
    assert "box-shadow:" in options_block
    control_block = _css_rule(css_text, ".analysis-multi-select-control")
    assert "background: var(--surface-card);" in control_block
    select_block = _css_rule(css_text, ".analysis-select")
    assert "background: var(--surface-card);" in select_block
    filter_css = _css_slice(css_text, ".analysis-select {", ".analysis-filter-apply")
    assert "var(--surface)" not in filter_css

    # 2. 阶段在所有用户可见位置大写，请求值保持小写规范值。
    assert "function formatEwoStageLabel" in js_text
    assert "formatEwoStageLabel(it.stage)" in js_text
    assert "labelFor: formatEwoStageLabel" in js_text
    for label in (
        "OPEN（未纳入统计）", "DRAFT1", "DRAFT2", "EDIT1", "EDIT2", "PROC", "IMPL", "CLOSE（已关闭）",
    ):
        assert label in js_text
    assert 'params.append("stages", stage)' in js_text

    # 3. 明细表状态列只表达 超期/未超期，阶段列独立展示。
    items_js = _js_slice(js_text, "function renderAnalysisItemsSection", "function renderDeliverableAnalysis")
    assert 'const isOverdue = it.alertType === "overdue";' in items_js
    assert 'chip.textContent = isOverdue ? "超期" : "未超期";' in items_js
    assert "it.status ||" not in items_js

    # 4. 待签署人员按 ROLE:person 行渲染，无值显示 无。
    assert 'String(it.pendingSigners || "")' in items_js
    assert '.split("\\n")' in items_js
    assert "analysis-signer-line" in items_js
    assert '"无"' in items_js

    # 5. EWO 更新方式：三模式展示 + 推荐自动同步 + 未启用判定。
    assert "function deliverablePolicyMappingReady" in js_text
    assert "policy.enabled !== true" in js_text
    policy_js = _js_slice(
        js_text, "const EWO_POLICY_MODE_LABELS", "async function loadDeliverablePolicy"
    )
    for label in ("手动维护", "自动同步", "混合模式", "推荐：自动同步", "未启用"):
        assert label in policy_js
    assert "/ewo/i.test(String(item.source" in js_text

    # 6. 手工进度与 EWO 快照摘要来源标签互不混淆。
    assert '"项目手工进度"' in js_text
    summary_js = _js_slice(js_text, "function renderEwoSyncSummary", "function renderDeliverableStatusChart")
    assert "来自最近一次 EWO 快照" in summary_js
    assert "最近同步时间" in summary_js


def test_ewo_update_policy_is_editable_with_separate_interactive_refresh() -> None:
    """交互式刷新不受后台同步就绪门禁影响，后台同步仍保留门禁。"""
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    policy_js = _js_slice(
        js_text, "function renderSyncBindingEditor", "async function loadDeliverablePolicy"
    )
    chart_js = _js_slice(
        js_text, "function renderDeliverableStatusChart", "async function refreshEwoAnalysisFromStatusChart"
    )

    # The EWO mode choices must be real controls with a save path, not labels
    # rendered as inert divs.
    assert 'input.type = "radio"' in policy_js
    assert "form.addEventListener(" in policy_js
    assert 'method: "PATCH"' in policy_js
    assert "body: JSON.stringify(payload)" in policy_js
    assert "enabled: false" not in policy_js

    # The status-chart action is an interactive query and is disabled only
    # while busy; the background action remains readiness-gated elsewhere.
    assert "setSyncReadiness" in chart_js
    assert "getSyncReadiness" in chart_js
    assert "onInteractiveRefresh" in chart_js
    assert "interactiveButton.disabled = syncBusy" in chart_js
    assert "requestInteractiveArasQuery(\"ewo\"" in chart_js
    assert "syncReady" in chart_js


def test_ewo_policy_editor_exposes_binding_configuration_and_discovery_workflow() -> None:
    """EWO 页面必须能保存绑定配置并产生两次稳定映射证据。"""
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    policy_js = _js_slice(
        js_text,
        "function renderSyncBindingEditor",
        "async function loadDeliverablePolicy",
    )
    loader_js = _js_slice(
        js_text,
        "async function loadDeliverablePolicy",
        "async function requestProjectStatusSync",
    )
    detail_js = _js_slice(
        js_text,
        "function renderDeliverableDetailPage",
        "function toggleDeliverableDetail",
    )

    for marker in (
        "credentialRef",
        "externalKey",
        "matchRule",
        "fieldAuthority",
        "mapping",
        "enabled",
        "credentialVaultConfigured",
        "绑定同步配置",
        "保存同步绑定",
        "抓取映射证据",
        "/mapping-discovery",
        "selectedExternalKey",
    ):
        assert marker in policy_js
    assert "/api/settings" in loader_js
    assert "const refreshEvidence = () => loadDeliverableEvidence" in detail_js
    assert "onEvidenceRefresh: refreshEvidence" in detail_js

    # The old mode-only request cannot configure the binding that the backend
    # gate evaluates; the new editor must submit the complete form payload.
    assert "body: JSON.stringify({ mode })" not in policy_js
    assert "body: JSON.stringify(payload)" in policy_js
    assert "enabled: enabledInput.checked" in policy_js


def test_ewo_model_info_filter_is_forwarded_to_aras_crawler() -> None:
    """EWO 的车型匹配条件必须能进入映射发现请求的过滤器。"""
    from web.app import _ewo_filters_from_payload

    filters = _ewo_filters_from_payload({"filters": {"model_info": "*F610S*"}})

    assert filters.model_info == "*F610S*"


def test_overview_analysis_actions_are_visible_before_empty_state_and_gate_sync() -> None:
    """无分析缓存时仍显示刷新/抓取入口，但抓取必须服从同步门禁。"""
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    analysis_js = _js_slice(js_text, "function renderDeliverableAnalysis", "function renderTrendSvgChart")
    loader_js = _js_slice(js_text, "async function loadDeliverableAnalysis", "function renderDepartmentDoneChart")
    evidence_js = _js_slice(js_text, "function renderDeliverableEvidence", "// 4.")

    # 操作栏必须在 hasCache 空态判断之前创建，D5 首次打开也能看到入口。
    assert "analysis-action-bar" in analysis_js
    assert "刷新分析" in analysis_js
    assert "后台同步" in analysis_js
    assert analysis_js.index("analysisActionBar") < analysis_js.index("if (!analysisData.hasCache)")

    # 分析区仍提供清晰的后台同步入口并服从后端同步门禁。
    assert "analysisSyncReadiness" in loader_js
    assert "analysisOptions" in loader_js
    assert "onSync" in analysis_js
    assert "setDeliverableAnalysisSyncReadiness" in evidence_js
    assert "syncButton.disabled" in analysis_js
    assert "后台同步" in analysis_js


def test_overview_ewo_department_scope_model_and_chart_labels_contract() -> None:
    """部门默认范围落地后的前端契约：车型查找、匹配类型、自定义图表标签。"""
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    css_text = Path("web/static/style.css").read_text(encoding="utf-8-sig")

    # 1. 车型查找：输入 + 模糊/精确切换（默认模糊），随应用筛选提交。
    assert 'analysisModelFilter = { model: "", match: "fuzzy" }' in js_text
    assert "analysis-model-input" in js_text
    assert "analysis-model-match" in js_text
    assert '"模糊"' in js_text
    assert '"精确"' in js_text
    assert 'setAttribute("aria-pressed"' in js_text
    assert 'params.set("model", analysisModelFilter.model)' in js_text
    assert 'params.set("modelMatch", analysisModelFilter.match)' in js_text
    # 分析面板重载带同样的车型参数（统计摘要与明细同口径）。
    assert 'filterParams.set("model", analysisModelFilter.model)' in js_text
    assert 'filterParams.set("modelMatch", analysisModelFilter.match)' in js_text
    # 进入详情页时重置车型筛选状态。
    assert 'analysisModelFilter.model = ""' in js_text

    # 2. 自定义图表标签：tab 切换 + 设置弹层 + PUT 保存后重载。
    assert "function renderCustomLabelChart" in js_text
    assert "analysis-chart-tab" in js_text
    assert "analysisData.customCharts" in js_text
    assert "analysis-chart-settings-btn" in js_text
    assert "chart-labels-editor" in js_text
    assert "chart-label-field-select" in js_text
    assert "/api/project-status/deliverables/${encodeURIComponent(item.id)}/chart-labels" in js_text
    assert 'method: "PUT"' in js_text

    # 3. 图表区与标签编辑器样式存在。
    for marker in (
        ".analysis-chart-tab",
        ".analysis-model-input",
        ".analysis-model-match",
        ".chart-labels-editor",
        ".chart-label-row",
    ):
        assert marker in css_text


def test_overview_chart_label_group_mapping_editor_contract() -> None:
    """分组定义编辑器契约：组规则行、成员分隔解析、未匹配三选、payload 携带新键。"""
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    css_text = Path("web/static/style.css").read_text(encoding="utf-8-sig")

    # 1. 标签块与分组定义编辑区。
    assert "chart-label-groups-toggle" in js_text
    assert "配置分组" in js_text
    assert "chart-group-rule" in js_text
    assert "chart-group-name" in js_text
    assert "chart-group-members" in js_text
    assert "chart-group-add-btn" in js_text
    assert "chart-label-unmatched" in js_text
    for option_label in ("保留原样", "并入未分组", "从图表隐藏"):
        assert option_label in js_text
    # 成员文本框分隔解析（英文/中文逗号、顿号、分号）。
    assert "split(/[,，、;；]/)" in js_text
    # 保存 payload 携带 groups/unmatched。
    assert "groups: groupRules" in js_text
    assert "unmatched: unmatchedMode" in js_text

    # 2. 分组定义区样式。
    for marker in (".chart-label-block", ".chart-label-groups", ".chart-group-rule"):
        assert marker in css_text
    # display:grid 会覆盖 hidden 属性的默认 display:none，必须显式补规则，
    # 否则未展开的分组定义区也会渲染出来。
    assert ".chart-label-groups[hidden]" in css_text
    assert ".chart-labels-editor[hidden]" in css_text


def test_overview_custom_label_chart_returns_dom_element() -> None:
    """回归：自定义标签图必须返回 DOM 元素。

    renderDepartmentDoneChart 返回 {el, setSelected} 包装对象；若
    renderCustomLabelChart 直接把它当元素 appendChild，会抛
    "parameter 1 is not of type 'Node'"，令整个分析面板渲染中断、
    同步/刷新入口全部失效。
    """
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    chart_js = _js_slice(js_text, "function renderCustomLabelChart", "function renderDeliverableAnalysis")

    assert "const rendered = renderDepartmentDoneChart(totals, groups, null, {" in chart_js
    assert "return rendered.el;" in chart_js


def test_overview_deliverable_evidence_css_contract() -> None:
    css_text = Path("web/static/style.css").read_text(encoding="utf-8-sig")
    overview_css = _css_slice(css_text, ".overview-tabpanel[hidden]", ".loading")

    for marker in (
        ".deliverable-evidence-panel",
        ".evidence-panel-head",
        ".evidence-title",
        ".evidence-source",
        ".evidence-restriction-card",
        ".evidence-overview-grid",
        ".evidence-risk-box",
        ".evidence-sync-bar",
        ".evidence-sync-btn",
        ".evidence-sync-status",
        ".evidence-sub-section",
        ".evidence-sub-title",
        ".evidence-empty-note",
        ".evidence-obs-grid",
        ".evidence-field-tags",
        ".evidence-field-tag",
        ".evidence-status-samples-list",
        ".evidence-mapping-confirmation",
        ".evidence-artifact-btn",
        ".evidence-artifact-row",
        ".evidence-artifact-box",
        ".evidence-artifact-table",
        ".evidence-retry-btn",
    ):
        assert marker in overview_css

    mobile_start = css_text.find("@media (max-width: 560px)")
    assert mobile_start != -1, "Marker '@media (max-width: 560px)' not found"
    mobile_break = css_text[mobile_start:]
    assert ".evidence-overview-grid" in mobile_break
    assert ".evidence-obs-grid" in mobile_break


def test_overview_milestone_undated_nodes_and_deliverable_form_link_contract() -> None:
    """主计划空日期节点、快照联动换算与环图显示筛选的前端契约。"""
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    css_text = Path("web/static/style.css").read_text(encoding="utf-8-sig")

    for marker in (
        "calculateMilestoneTimelineX",
        "待排期",
        "deliverableFormDisplay",
        "shouldShowDeliverable",
        "快照进度",
        "deliverable-snapshot-tag",
        "deliverable-display-filter",
        "按节点状态自动显示",
        "表单快照",
    ):
        assert marker in js_text, marker

    # “预留”占位已被正式规则取代。
    assert "按节点状态自动显示（预留）" not in js_text
    assert "该规则将在节点状态联动上线后开放" not in js_text
    assert "optAuto.disabled = true" not in js_text

    for marker in (
        ".deliverable-display-filter",
        ".deliverable-display-filter-select",
        ".deliverable-snapshot-tag",
        ".deliverable-auto-hidden",
    ):
        assert marker in css_text, marker


def test_deliverable_auto_hide_rule_contract() -> None:
    """按节点状态自动显示：已完成交付物在项目越过关联节点后隐藏。"""
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    block = _js_slice(js_text, "const DELIVERABLE_AUTO_HIDE_NODE_KEYWORDS", "let deliverableProgressFilterValue")

    # 节点关键字映射（用户示例：到了 VDR 阶段隐藏已完成的子系统开发策略）。
    assert '"VPI-T2-D1": ["VDR"]' in block
    for deliverable_id in ("VPI-T2-D2", "VPI-T2-D3", "VPI-T2-D4", "VPI-T2-D5"):
        assert deliverable_id in block
    # 触发条件：仅 auto 模式、完成态取快照换算口径（回退手工值）、
    # 节点已排期且日期已过。
    assert 'if (filterValue !== "auto") return true;' in block
    assert "deliverableFormDisplay(item)" in block
    assert 'if (status !== "已完成") return true;' in block
    assert "deliverableNodeReached(keywords)" in block
    reached_block = _js_slice(js_text, "function deliverableNodeReached", "function shouldShowDeliverable")
    assert "milestone.date" in reached_block or "String(milestone.date" in reached_block
    assert "date <= today" in reached_block
    # 分词匹配而非子串匹配，避免「VPI-T2 Gate」误命中 VPI 关键字。
    assert "tokens.includes(keyword)" in reached_block
    # 隐藏数量提示。
    assert "已隐藏" in js_text
    assert "deliverable-auto-hidden" in js_text


def test_deliverable_form_display_fallback_contract() -> None:
    """无 analysisLink/formLink/summary 为空时回退手工值，有效 summary 才换算。"""
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    block = _js_slice(js_text, "function deliverableSnapshotSummary", "const DELIVERABLE_AUTO_HIDE_NODE_KEYWORDS")
    # 门控：仅在交付物启用同步（updatePolicy.enabled === true）时使用快照口径；
    # 人工编辑的交付物始终显示手工值（需求 2026-09-12 确认）。
    assert "policy.enabled !== true" in block
    assert "item.updatePolicy" in block
    # 明细分析快照优先（与明细页同源），其次表单快照联动摘要。
    assert "item.analysisLink" in block
    assert "item.formLink" in block
    assert "total <= 0" in block
    assert "已完成" in block and "已逾期" in block and "进行中" in block
    assert "Math.round" in block
    # 统一换算入口：环图与明细表必须共用 deliverableDisplayItem。
    assert "function deliverableDisplayItem" in block
    # 后端字段驱动：快照态优先消费 syncDisplay.display 三字段，
    # 缺字段时才回退本地换算（保存后整体替换 payload，无乐观编辑）。
    assert 'syncDisplay.state === "snapshot"' in block
    assert "syncDisplay.displaySummary" in block
    assert "syncDisplay.displayProgress" in block
    assert "syncDisplay.displayStatus" in block


def test_detail_collapse_note_inline_and_owner_removed_contract() -> None:
    """需求 2026-09-06：详细明细折叠、负责人移除、风险与备注就地编辑。"""
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    css_text = Path("web/static/style.css").read_text(encoding="utf-8-sig")

    columns = _js_slice(js_text, "const OVERVIEW_DETAIL_COLUMNS", "];")
    assert '"负责人"' not in columns.split(";")[0]

    for marker in (
        "detail-inline-collapse",
        "detail-inline-summary",
        "展开查看属性明细",
        "startInlineNoteEdit",
        "note-inline-edit",
    ):
        assert marker in js_text, marker

    for marker in (
        ".detail-inline-collapse",
        ".detail-inline-summary",
        ".note-inline-input",
        ".phase-name-inline-input",
    ):
        assert marker in css_text, marker


def test_phase_name_inline_edit_contract() -> None:
    """需求 2026-09-06：主计划名称支持只读卡片上单击内联编辑。"""
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    for marker in (
        "phase-name-inline-btn",
        "startPhaseNameInlineEdit",
        "编辑主计划名称",
    ):
        assert marker in js_text, marker


def test_filter_dims_multi_select_overflow_fix_contract() -> None:
    """需求 2026-09-06：筛选栏多选控件解除最小宽度，网格 150px 自适应。"""
    css_text = Path("web/static/style.css").read_text(encoding="utf-8-sig")
    dims = _css_slice(css_text, ".form-filter-row-dims", ".form-filter-row-time")
    assert "minmax(150px, 1fr)" in dims
    assert ".form-filter-row-dims .analysis-multi-select { min-width: 0; max-width: none; }" in css_text


def test_milestone_delete_all_restore_notice_contract() -> None:
    """需求 2026-09-06：删除全部节点保存后自动恢复默认模板并提示。"""
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    css_text = Path("web/static/style.css").read_text(encoding="utf-8-sig")

    assert "milestoneRestoreNotice" in js_text
    assert "已删除全部节点，已自动恢复默认节点模板" in js_text
    for marker in ("hadNoRows", "edit-request-info"):
        assert marker in js_text or marker in css_text, marker
    assert ".edit-request-info" in css_text


def test_owner_header_removed_contract() -> None:
    """需求 2026-09-06：明细表负责人表头移除。"""
    html_text = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")

    # 表头与数据列一致：静态表头不再包含负责人。
    assert '<th scope="col">负责人</th>' not in html_text


def test_details_table_header_matches_column_constant() -> None:
    """架构加固：明细表静态表头必须与 OVERVIEW_DETAIL_COLUMNS 一一对应，
    防止表头/数据列再次错位（2026-09-07 审计发现）。"""
    import re

    html_text = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    start = html_text.find('<table class="overview-details-table">')
    assert start != -1, "Start marker '<table class=\"overview-details-table\">' not found"
    head_end = html_text.find("</thead>", start)
    assert head_end != -1, "End marker '</thead>' not found after start"
    table_head = html_text[start:head_end]
    headers = re.findall(r"<th[^>]*>(.*?)</th>", table_head, re.S)
    headers = [re.sub(r"<[^>]+>", "", h).strip() for h in headers]
    # 最后一列是视觉隐藏的展开控制列，不承载明细字段。
    assert headers[-1] == "展开控制"
    data_headers = headers[:-1]

    columns_source = _js_slice(js_text, "const OVERVIEW_DETAIL_COLUMNS", "];")
    columns = [
        part.strip().strip('"')
        for part in columns_source.split("[", 1)[1].split(",")
        if part.strip()
    ]
    assert data_headers == columns, (data_headers, columns)


def test_details_table_status_colspan_contract() -> None:
    """代码审计修复：表格状态列 colspan 与列数一致。"""
    html_text = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    # 明细表状态行 colspan 与列数一致（7 列：6 数据列 + 展开控制列）。
    assert 'colspan="7"' in html_text
    assert 'colspan="8"' not in html_text
    assert "cell.colSpan = OVERVIEW_DETAIL_COLUMNS.length + 1;" in js_text
    assert "cell.colSpan = 8;" not in js_text


def test_overview_rings_link_to_deliverable_details_contract() -> None:
    """需求 2026-09-12：状态总览环图可点击跳转对应交付物明细，且与明细表共用换算口径。"""
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    progress_block = _js_slice(js_text, "function renderDeliverableProgress", "async function renderDeliverablesSyncControlBar")

    # 环图卡片按钮化：可点击、可键盘聚焦、携带跳转目标。
    assert "progress-ring is-clickable" in progress_block
    assert 'card.setAttribute("role", "button")' in progress_block
    assert 'card.setAttribute("tabindex", "0")' in progress_block
    assert 'location.hash = `#deliverable/${encodeURIComponent(item.id)}`' in progress_block
    assert 'event.key === "Enter" || event.key === " "' in progress_block

    # 环图使用统一换算入口，不再各自内联合并快照字段。
    assert "deliverableDisplayItem(rawItem)" in progress_block
    assert "formDisplay ?" not in progress_block

    details_block = _js_slice(js_text, "function renderDeliverableDetails", "function renderProjectOverview")
    assert "deliverableDisplayItem(rawRow)" in details_block

    css_text = Path("web/static/style.css").read_text(encoding="utf-8-sig")
    assert ".progress-ring.is-clickable" in css_text
    assert "cursor: pointer" in css_text


def test_deliverable_snapshot_display_prefers_analysis_link() -> None:
    """环图换算优先取明细分析快照（analysisLink），其次表单快照（formLink）。"""
    script = r"""
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync("web/static/app.js", "utf8");
const code = source.slice(
  source.indexOf("function deliverableSnapshotSummary"),
  source.indexOf("const DELIVERABLE_AUTO_HIDE_NODE_KEYWORDS"),
);
const context = {};
vm.runInNewContext(code + `
const enabledPolicy = { enabled: true, mode: "automatic" };
result = [
  JSON.stringify(deliverableFormDisplay({
    id: "X",
    updatePolicy: enabledPolicy,
    analysisLink: { snapshotAt: "A", summary: { total: 4, completed: 3, overdue: 1 } },
    formLink: { snapshotAt: "B", summary: { total: 2, completed: 2, overdue: 0 } },
  })),
  JSON.stringify(deliverableFormDisplay({
    id: "Y",
    updatePolicy: enabledPolicy,
    formLink: { snapshotAt: "B", summary: { total: 4, completed: 1, overdue: 2 } },
  })),
  JSON.stringify(deliverableFormDisplay({
    id: "Z",
    updatePolicy: enabledPolicy,
    formLink: { snapshotAt: "B", summary: { total: 0, completed: 0, overdue: 0 } },
  })),
  JSON.stringify(deliverableDisplayItem({
    id: "W",
    updatePolicy: enabledPolicy,
    status: "进行中",
    progress: 60,
    progressOrDate: "60%",
    analysisLink: { snapshotAt: "A", summary: { total: 4, completed: 4, overdue: 0 } },
  })),
  JSON.stringify(deliverableDisplayItem({ id: "V", status: "进行中", progress: 60 })),
  JSON.stringify(deliverableFormDisplay({
    id: "M",
    updatePolicy: { enabled: false, mode: "manual" },
    analysisLink: { snapshotAt: "A", summary: { total: 4, completed: 3, overdue: 1 } },
  })),
  JSON.stringify(deliverableDisplayItem({
    id: "N",
    status: "进行中",
    progress: 72,
    progressOrDate: "72%",
    analysisLink: { snapshotAt: "A", summary: { total: 4, completed: 3, overdue: 1 } },
  })),
  // 后端字段驱动：快照态的 display 三字段优先于本地链接换算。
  JSON.stringify(deliverableFormDisplay({
    id: "P",
    status: "已逾期",
    syncDisplay: {
      state: "snapshot",
      displayStatus: "已逾期",
      displayProgress: 75,
      displaySummary: { total: 4, completed: 3, overdue: 1, snapshotAt: "2026-09-15T08:00:00.000Z" },
    },
    analysisLink: { snapshotAt: "OLD", summary: { total: 9, completed: 1, overdue: 0 } },
  })),
  // manual 数值态不触发快照换算：formLink 存在也不改写手工口径。
  JSON.stringify(deliverableFormDisplay({
    id: "Q",
    status: "进行中",
    syncDisplay: { state: "manual", displayStatus: "进行中", displayProgress: 60, displaySummary: null },
    formLink: { snapshotAt: "B", summary: { total: 4, completed: 4, overdue: 0 } },
  })),
];
`, context);
process.stdout.write(context.result.join("\n"));
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=Path(__file__).resolve().parent.parent,
        check=True,
        capture_output=True,
        # Node 固定输出 UTF-8；Windows 默认 GBK 解码会失败，必须显式指定。
        encoding="utf-8",
    )
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 9
    # 同步启用时 analysisLink 优先：4 项完成 3 项 → 75%、有逾期 → 已逾期。
    assert lines[0] == '{"progress":75,"status":"已逾期","snapshotAt":"A"}'
    # 无 analysisLink 时回退 formLink。
    assert lines[1] == '{"progress":25,"status":"已逾期","snapshotAt":"B"}'
    # total 为 0 的快照无效 → 回退手工值。
    assert lines[2] == "null"
    # 合并项：快照换算已完成 → 状态/进度/进度或日期一致。
    assert json.loads(lines[3])["status"] == "已完成"
    assert json.loads(lines[3])["progress"] == 100
    assert json.loads(lines[3])["progressOrDate"] == "100%"
    # 无任何快照 → 原样返回（手工口径不变）。
    raw = json.loads(lines[4])
    assert raw["progress"] == 60
    assert "progressOrDate" not in raw
    # 门控：同步未启用（人工编辑）→ 即使存在 analysisLink 也回退手工值。
    assert lines[5] == "null"
    gated = json.loads(lines[6])
    assert gated["progress"] == 72
    assert gated["status"] == "进行中"
    assert gated["progressOrDate"] == "72%"
    # 后端 display 三字段优先：75%/已逾期/快照时间取自 syncDisplay，
    # 不再读取 analysisLink（保存后整体替换 payload，无乐观编辑）。
    backend = json.loads(lines[7])
    assert backend == {
        "progress": 75,
        "status": "已逾期",
        "snapshotAt": "2026-09-15T08:00:00.000Z",
    }
    # manual 数值态：即使存在 formLink 也不做快照换算。
    assert lines[8] == "null"


def test_deliverable_detail_page_unified_display_contract() -> None:
    """CODEX 审计修复：详情页标题/状态图/属性网格与概览环图同口径，
    同步成功后刷新概览数据。"""
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    # 状态图使用统一换算入口（含 tone 归零），不再保留手工 tone。
    chart_start = js_text.index("function renderDeliverableStatusChart")
    chart_block = js_text[chart_start:js_text.index("const chart = overviewEl", chart_start)]
    assert "deliverableDisplayItem(rawItem)" in chart_block
    assert "deliverableFormDisplay(rawItem)" in chart_block

    # 详情页头与属性网格使用换算后的展示状态；数据来源区分两类快照。
    detail_start = js_text.index("const displayItem = deliverableDisplayItem(item)")
    detail_block = js_text[detail_start:js_text.index('function renderArchiveDeliverableDetailPage', detail_start)]
    assert "deliverableTone(displayItem)" in detail_block
    # 状态感知的当前状态行：四区共用 deliverableStatusText（paused 后缀统一）。
    assert '["当前状态", deliverableStatusText(item, displayItem)]' in detail_block
    assert '"明细分析快照"' in detail_block
    assert '"表单快照"' in detail_block
    # 详情头状态旁参考行：表单分析快照摘要（后端 formLink/analysisLink 驱动）。
    assert "deliverableFormReferenceText(item)" in detail_block
    ref_start = js_text.index("function deliverableFormReferenceText")
    ref_block = js_text[ref_start:js_text.index("function deliverableDisplayItem", ref_start)]
    assert "表单分析参考：已完成" in ref_block
    assert "无表单来源" in ref_block
    # 数据取自 formLink/analysisLink：经 deliverableSnapshotSummary 同源读取。
    assert "deliverableSnapshotSummary(item)" in ref_block

    # 四条同步/归档下载成功路径都刷新概览数据（环图 analysisLink 不停留旧快照）。
    assert js_text.count("await loadProjectOverview();") >= 4


def test_ring_date_label_percent_fallback() -> None:
    """CODEX 审计修复：快照 100% 且无实际完成日期时，环图文案回退完成度。"""
    script = r"""
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync("web/static/app.js", "utf8");
const code = source.slice(
  source.indexOf("function deliverableProgressOrDate"),
  source.indexOf("function renderDeliverableProgress"),
);
const context = {};
vm.runInNewContext(code + `
result = [
  ringDateLabel({ status: "已完成", progress: 100, progressOrDate: "100%" }),
  ringDateLabel({ status: "已完成", progress: 100, progressOrDate: "2026-08-30" }),
  ringDateLabel({ status: "已逾期", plannedDate: "2026-08-08", note: "逾期 5 天" }),
];
`, context);
process.stdout.write(context.result.join("\n"));
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=Path(__file__).resolve().parent.parent,
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    lines = result.stdout.strip().splitlines()
    assert lines[0] == "完成度 100%"
    assert lines[1] == "实际完成 08-30"
    assert lines[2] == "计划完成 08-08"


def test_sync_binding_editor_is_capability_driven_contract() -> None:
    """CODEX 架构审计修复：绑定编辑器由 sourceInfo 能力配置驱动，
    D2/D5 与 EWO 共用；假就绪修复（最近一次报告集合 + 证据目标核对）；
    保存提交真实启用状态（不得硬编码 enabled:false 关闭既有绑定）。"""
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    # 分发能力驱动：不再按 source 正则/硬编码 id 选择编辑器。
    loader_block = _js_slice(js_text, "async function loadDeliverablePolicy", "const DELIVERABLE_FIXED_SOURCES")
    assert "capabilities.syncCapable" in loader_block
    assert 'renderSyncBindingEditor' in loader_block
    assert "/ewo/i.test" not in loader_block
    assert 'item.id !== "VPI-T2-D5"' not in loader_block
    assert "function renderDeliverablePolicyEditor" not in js_text

    editor_block = _js_slice(js_text, "function renderSyncBindingEditor", "async function loadDeliverablePolicy")
    # 匹配规则与证据来源连接由能力配置渲染。
    assert "capabilities.matchFields" in editor_block
    assert "capabilities.evidenceFields" in editor_block
    assert "capabilities.reportType" in editor_block
    # 假就绪修复：最近一次报告集合替换 + 证据目标核对。
    assert "setDiscoveredFields(fields)" in editor_block
    assert "addDiscoveredField" not in editor_block
    assert "外部稳定键与最近一次映射证据不一致" in editor_block
    # 保存提交真实启用状态，不得硬编码关闭。
    assert "enabled: false" not in editor_block
    assert "enabled: enabledInput.checked" in editor_block
    # GPT 终审 P1/P2 修复：保存后刷新权威数据；重绘由
    # loadProjectOverview→handleHashChange 单次触发，提示经消息槽在
    # 新编辑器渲染完成后显示（避免异步时序缺口与重复渲染）。
    assert "await loadProjectOverview();" in editor_block
    assert 'pendingPolicyStatusMessage = "更新方式已保存"' in editor_block
    assert "renderDeliverableDetailPage(item.id)" not in editor_block
    assert "pendingPolicyStatusMessage = null" in editor_block


def test_sync_binding_editor_payload_and_evidence_contract() -> None:
    """Gemini 交叉审计修复回归：reportType 跟随能力配置、headers 走
    parseHeaders 序列化、历史无观测记录时强制先抓取证据、paused 后缀四区统一。"""
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    editor_block = _js_slice(js_text, "function renderSyncBindingEditor", "async function loadDeliverablePolicy")

    # P0 修复：保存载荷 reportType 跟随能力配置，不再写死 ewo。
    assert 'matchRule: { reportType: capabilities.reportType || "ewo" }' in editor_block
    assert 'matchRule: { reportType: "ewo" }' not in editor_block
    # P0 修复：TDC 认证头文本经 parseHeaders 序列化为对象。
    assert "evidencePayload.headers = parsed" in editor_block
    assert "parseHeaders(input.value" in editor_block
    # P1 修复：历史无观测记录时强制先抓取证据。
    assert "请先抓取映射证据（连续两次一致）" in editor_block
    # matchFields 空数组按能力配置采纳，不再回退 EWO 字段。
    assert "Array.isArray(capabilities.matchFields)\n    ? capabilities.matchFields" in editor_block

    # paused 后缀四区统一：环图/明细/详情头/状态图共用 deliverableStatusText。
    progress_block = _js_slice(js_text, "function renderDeliverableProgress", "async function renderDeliverablesSyncControlBar")
    details_block = _js_slice(js_text, "function renderDeliverableDetails", "function renderProjectOverview")
    detail_page_block = _js_slice(js_text, "function renderDeliverableDetailPage", "function renderArchiveDeliverableDetailPage")
    chart_block = _js_slice(js_text, "function renderDeliverableStatusChart", "async function runDeliverableSyncFromAnalysis")
    assert "deliverableStatusText(" in progress_block
    assert "deliverableStatusText(" in details_block
    assert "deliverableStatusText(item, displayItem)" in detail_page_block
    assert "deliverableStatusText(item, item)" in chart_block
    # paused 为非数值态：deliverableStatusText 直接显示状态标签（无后缀特例）。
    paused_helper = _js_slice(js_text, "function deliverableStatusText", "function deliverablePendingDateLabel")
    assert "syncDisplay.label" in paused_helper
    assert "（已暂停）" not in paused_helper


def test_display_state_helpers_behavior() -> None:
    """终审测试缺口（行为级）：展示状态助手与自动隐藏七态门控。"""
    script = r"""
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync("web/static/app.js", "utf8");
const code = source.slice(
  source.indexOf("function deliverableSnapshotSummary"),
  source.indexOf("function renderDeliverableProgress"),
);
const context = {
  overviewSavedState: {
    phase: { today: "2026-09-12" },
    milestones: [{ name: "VPI 决策", date: "2026-09-01" }],
  },
};
vm.runInNewContext(code + `
const pendingDone = {
  id: "VPI-T2-D2",
  status: "已完成",
  plannedDate: "2026-08-08",
  syncDisplay: { state: "pending_first_sync", label: "待首次同步" },
};
const pausedRunning = {
  id: "VPI-T2-D2",
  status: "进行中",
  syncDisplay: { state: "paused", label: "已暂停" },
};
const aggregateFormOnly = {
  id: "VPI-T2-D5",
  status: "进行中",
  updatePolicy: { enabled: true, mode: "automatic", aggregate: true },
  formLink: { snapshotAt: "2026-09-12T08:00:00.000Z", summary: { total: 4, completed: 4, overdue: 0 } },
};
const singleRecordForm = {
  id: "VPI-T2-D5",
  status: "进行中",
  updatePolicy: { enabled: true, mode: "automatic", aggregate: false },
  formLink: { snapshotAt: "2026-09-12T08:00:00.000Z", summary: { total: 4, completed: 4, overdue: 0 } },
};
result = [
  deliverableStatusText(pausedRunning, pausedRunning),
  deliverablePendingDateLabel(pendingDone),
  shouldShowDeliverable(pendingDone, "auto"),
  shouldShowDeliverable({ id: "VPI-T2-D2", status: "已完成" }, "auto"),
  deliverableHasDisplayValue(pausedRunning),
  deliverableHasDisplayValue(pendingDone),
  deliverableStatusText({ id: "X", status: "已完成" }, { id: "X", status: "已完成" }),
  deliverableFormDisplay(aggregateFormOnly) === null ? "aggregate-skipped" : "aggregate-used",
  deliverableFormDisplay(singleRecordForm).progress,
];
`, context);
process.stdout.write(context.result.join("\n"));
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=Path(__file__).resolve().parent.parent,
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    lines = result.stdout.strip().splitlines()
    # paused 非数值态（GPT 终审 P1：同步不写 status/progress，
    # 占位进度不可信）→ 显示状态标签。
    assert lines[0] == "已暂停"
    # 待同步态的计划逾期明确标注，且不写死业务文案。
    assert lines[1] == "计划完成 08-08；已逾期 35 天（待同步）"
    # 七态门控：待同步项即使手工状态为已完成也不被自动隐藏。
    assert lines[2] == "true"
    # 数值态（manual）已完成且节点已过 → 照旧隐藏。
    assert lines[3] == "false"
    assert lines[4] == "false"  # paused 是非数值态（无可信进度值）
    assert lines[5] == "false"  # pending_first_sync 是非数值态
    # 数值态（manual/snapshot）正常显示换算状态。
    assert lines[6] == "已完成"
    # 聚合绑定不做表单快照兜底（前后端换绑隔离一致）；单记录绑定正常换算（100%）。
    assert lines[7] == "aggregate-skipped"
    assert lines[8] == "100"


def test_top_bar_navigation_six_main_domains() -> None:
    """顶栏仍是概览、交付物 + 插件清单生成的系统查询/表单/Excel/自动归档/设置。

    S4 切换后，已迁成插件的四个面板不再写死在模板里，由插件 plugin.json 的
    nav 生成；旧哈希由 app.js 转到插件页。
    """
    html_text = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")
    nav_match = re.search(r'<nav[^>]*class="workspace-tabs"[^>]*>([\s\S]*?)</nav>', html_text)
    assert nav_match is not None
    nav_links = re.findall(r'<a[^>]*href="#([^"]+)"[^>]*>([^<]+)</a>', nav_match.group(1))
    assert [(panel, label.strip()) for panel, label in nav_links] == [("overview", "概览"), ("deliverables", "交付物")]

    nav = []
    for manifest_path in sorted(Path("plugins").glob("*/plugin.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        nav += [(entry.get("order", 100), entry["title"], manifest["id"]) for entry in manifest.get("nav", [])]
    assert [title for _, title, _ in sorted(nav)] == ["概览", "交付物", "系统查询", "表单", "Excel", "自动归档", "设置"]

    js = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    for legacy, target in [
        ("aras-panel", "#p/system-query/query"),
        ("excel-tasks", "#p/excel-tasks/workspace"),
        ("scheduled-archive", "#p/scheduled-archive/jobs"),
        ("settings-panel", "#p/settings/general"),
    ]:
        assert re.search(rf'"?{re.escape(legacy)}"?: "{re.escape(target)}"', js), legacy


def test_hash_deep_linking_routing_contracts() -> None:
    """W1-2: app.js handleHashChange 支持 Query 参数深链解析；已迁插件的旧哈希（含别名）转到插件页。"""
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    # 1. 查询参数与路径分离解析
    assert "const [hashPath, queryString] = rawHash.split(\"?\");" in js_text
    assert "const searchParams = new URLSearchParams(queryString || \"\");" in js_text

    # 2. 路由别名：dashboard 归一到概览；aras/system-query、archive、settings、excel 转到插件页
    assert 'panelId === "dashboard"' in js_text
    routes = _js_slice(js_text, "const LEGACY_PANEL_PLUGIN_ROUTES = {", "};")
    for alias, target in (
        ('"aras-panel"', "#p/system-query/query"),
        ("aras", "#p/system-query/query"),
        ('"system-query"', "#p/system-query/query"),
        ("archive", "#p/scheduled-archive/jobs"),
        ('"settings-panel"', "#p/settings/general"),
        ("settings", "#p/settings/general"),
        ("excel", "#p/excel-tasks/workspace"),
    ):
        assert f'  {alias}: "{target}",' in routes, alias
    assert "window.location.replace(pluginTarget)" in js_text

    # 3. 概览子页签深链（tab=plan / tab=details）
    assert 'searchParams.get("tab")' in js_text
    assert 'isPlan = reqTab === "plan"' in js_text

    # 4. 交付物详情直达系统查询（openDeliverableInAras 采用深链路由，mode 由插件页解析）
    assert "#aras-panel?mode=" in js_text
    assert "from=overview" in js_text
    assert "在系统查询中打开" in js_text
    assert "aras-deep-link-back-bar" not in js_text


def test_board_visibility_contract_hides_d1_d4_and_removes_snapshot_panel() -> None:
    """看板可见性由后端能力注册表下发，两块看板同时遵守；外部快照展示已移除。"""
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    css_text = Path("web/static/style.css").read_text(encoding="utf-8-sig")
    contracts = Path("core/project_status_contracts.py").read_text(encoding="utf-8")

    # 单一来源：注册表显式声明 D1/D4 不看板；纯函数按缺省可见派生。
    assert '"VPI-T2-D1"' in contracts and '"VPI-T2-D4"' in contracts
    assert contracts.count('"boardVisible": False') == 2
    assert "def project_status_board_visible(" in contracts

    # 前端只消费后端下发的 item.boardVisible，不硬编码交付物 id。
    helper = _js_slice(js_text, "function deliverableBoardVisible", "function shouldShowDeliverable")
    assert "item.boardVisible !== false" in helper
    assert "VPI-T2-D1" not in helper and "VPI-T2-D4" not in helper

    # 首页卡片区：过滤在看板渲染器内；明细表：跳过渲染但必须保持 payload 下标
    # 语义（展开/内联编辑/证据面板都以 payload 下标回查交付物），
    # 因此行上写入 deliverableIndex，回查优先按该属性定位。
    assert "if (!deliverableBoardVisible(rawItem)) return;" in js_text
    assert "if (!deliverableBoardVisible(rawRow)) return;" in js_text
    assert "row.dataset.deliverableIndex = String(index);" in js_text
    assert "row.dataset.deliverableIndex === String(index)" in js_text
    assert "overviewDeliverableRows(data).filter(deliverableBoardVisible)" not in js_text

    # 外部业务快照面板与「外部快照·参考」徽标已删除（展示层），能力/接口保留。
    for removed in (
        "renderOverviewBusinessSnapshots",
        "OVERVIEW_BUSINESS_SNAPSHOT_DEFINITIONS",
        "overviewBusinessSnapshots",
        "loadOverviewBusinessSnapshots",
        "deliverableSnapshotBadge",
        "snapshot-driven-badge",
        "外部快照·参考",
    ):
        assert removed not in js_text, f"{removed} should be removed"
    assert "business-snapshot" not in css_text
    assert "snapshot-driven-badge" not in css_text
    # 归档任务状态与表单视图接口仍被归档明细页与交付物明细页消费。
    assert "overviewArchiveJobs" in js_text
    assert "/api/deliverable-forms/" in js_text
