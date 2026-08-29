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
    start = js_text.index("const OVERVIEW_DETAIL_COLUMNS")
    end = js_text.index("function parseHeaders")
    overview_js = js_text[start:end]

    assert "function loadDeliverableEvidence" in overview_js
    assert "function renderDeliverableEvidence" in overview_js

    for deliverable_id, source_label in (
        ("VPI-T2-D1", "仅手工维护"),
        ("VPI-T2-D2", "TDC SOR"),
        ("VPI-T2-D3", "ARAS EWO"),
        ("VPI-T2-D4", "TDC A 面（契约待验证）"),
        ("VPI-T2-D5", "TDC 数模"),
    ):
        assert f'"{deliverable_id}": "{source_label}"' in overview_js

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


def test_overview_deliverable_evidence_restrictions_and_guard() -> None:
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    start = js_text.index("const OVERVIEW_DETAIL_COLUMNS")
    end = js_text.index("function parseHeaders")
    overview_js = js_text[start:end]

    assert 'item.id === "VPI-T2-D1"' in overview_js
    assert 'item.id === "VPI-T2-D4"' in overview_js
    assert "TDC A 面契约待验证/阻断" in overview_js

    assert "policy.enabled === true" in overview_js
    assert "policy.credentialAvailable === true" in overview_js
    assert "window.confirm" in overview_js

    assert 'finalState === "busy" || outcome === "busy"' in overview_js
    assert 'finalState === "success" && outcome === "completed"' in overview_js
    assert 'finalState === "partial" || outcome === "partial"' in overview_js
    assert 'finalState === "needs_attention" || outcome === "needs_attention"' in overview_js

    assert "exitCode" not in overview_js
    assert 'enabled: true' not in overview_js
    assert 'method: "POST"' in overview_js
    assert overview_js.count('method: "POST"') == 1
    assert 'preview.candidates' not in overview_js
    assert 'mapping.candidates' not in overview_js

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
        assert forbidden not in overview_js


def test_overview_deliverable_evidence_api_and_sync_contract() -> None:
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    start = js_text.index("const OVERVIEW_DETAIL_COLUMNS")
    end = js_text.index("function parseHeaders")
    overview_js = js_text[start:end]

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
    start = js_text.index("const OVERVIEW_DETAIL_COLUMNS")
    end = js_text.index("function parseHeaders")
    overview_js = js_text[start:end]

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

    d1_guard = overview_js.index('if (item.id === "VPI-T2-D1")')
    d4_guard = overview_js.index('if (item.id === "VPI-T2-D4")')
    first_evidence_fetch = overview_js.index('const [policyRes, analyticsRes')
    sync_button = overview_js.index('const syncBtn = overviewEl')
    assert d1_guard < d4_guard < first_evidence_fetch < sync_button


def _css_rule(css_text: str, selector: str) -> str:
    """Return the body of one top-level CSS rule for a selector."""
    start = css_text.index(f"{selector} {{")
    end = css_text.index("}", start)
    return css_text[start:end]


def _js_slice(js_text: str, start_marker: str, end_marker: str) -> str:
    return js_text[js_text.index(start_marker):js_text.index(end_marker)]


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
    assert "刷新同步数据" in js_text
    assert "立即同步" in js_text
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
    filter_css = css_text[css_text.index(".analysis-select {"):css_text.index(".analysis-filter-apply")]
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


def test_overview_deliverable_evidence_css_contract() -> None:
    css_text = Path("web/static/style.css").read_text(encoding="utf-8-sig")
    start = css_text.index(".overview-tabpanel[hidden]")
    end = css_text.index(".loading,\n.is-empty")
    overview_css = css_text[start:end]

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

    mobile_break = css_text[css_text.index("@media (max-width: 560px)"):]
    assert ".evidence-overview-grid" in mobile_break
    assert ".evidence-obs-grid" in mobile_break
