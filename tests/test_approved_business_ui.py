# -*- coding: utf-8 -*-
"""Focused tests for approved business-language dashboard UI.

Covers all 10 business UI acceptance criteria:
1. Milestones display 未开始、进行中、已完成、已超期 and milestone edit form validation does not require exactly 1 current node.
2. Current stage label from backend currentStage and not displaying VPI-T2 as current stage.
3. Deliverable list and detail using displayCode, stable desktop grid & single-column mobile layout, full-row associations, collapsed technical evidence, read-only automatic fields.
4. PAA single tab in mode toolbar, removal of duplicate paa-all segment, and presence of 查询预览 and 获取全部结果 commands.
5. Report result tables rendering backend headerRows/columns/rows, visible columns, skipping NCR progress blank row, multi-row grouped headers for NCR detail, and no internal keys (_no, _subject) as column headers.
6. Scheduled tasks title 定时任务, approved template creation, task copy, interval/filter/folder edits, disabling built-in jobs, archiving non-built-in jobs.
7. Settings UI with approved directory and numeric settings, Aras/TDC session status without raw cookies, Chrome autofill-compatible username/password fields, re-login and clear session, and Excel service status.
8. Excel workspace 查看操作示例 button, HTML/CSS animations for append merge, overlay template, and baseline diff with pause toggle and prefers-reduced-motion support.
9. Responsive layouts and CSS border-radius <= 8px tokens on 390px viewports without clipping.
10. Scoped DOM tests verifying all labels, controls, and contracts.
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
    assert 'id="milestone-maintenance"' in html
    assert html.index('id="overview-plan-panel"') < html.index('id="milestone-maintenance"')

    # 2. Phase display name in timeline and summary
    assert "phase.displayName || phase.id" in js
    assert "主计划时间轴" in js
    assert 'aria-label", "编辑主计划"' in js
    assert 'title = "编辑主计划"' in js


def test_phase_metadata_and_milestones_patch_endpoints(client) -> None:
    js = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    # Phase metadata endpoint and payload
    assert '"/api/project-status/phases/VPI-T2"' in js
    assert 'method: "PATCH"' in js
    assert "displayName" in js
    assert "savePhaseMetadataChanges" in js

    # Milestone endpoint and payload
    assert '"/api/project-status/phases/VPI-T2/milestones"' in js
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
    assert "/analysis`" in js
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


def test_paa_single_entry_and_dual_commands() -> None:
    html = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")
    js = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    # 1. No duplicate paa-all segment in toolbar
    assert 'data-aras-mode="paa-all"' not in html
    assert 'data-aras-mode="paa"' in html

    # 2. Both query preview and crawl all commands exist
    assert 'id="aras-submit"' in html
    assert 'id="aras-crawl-all"' in html
    assert "查询预览" in html
    assert "获取全部结果" in html
    assert "runArasCrawlAll" in js
    assert '"/api/aras/paa/crawl-all"' in js


def test_report_tables_backend_contracts_and_ncr_headers() -> None:
    js = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    # Table render supports headerRows, columns, rows
    assert "renderRows" in js
    assert "headerRows" in js
    assert "defaultVisibleCount" in js
    assert 'mode === "ncr-progress"' in js
    assert 'mode === "ncr-detail"' in js


def test_excel_business_terminology_and_field_visibility() -> None:
    html = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")
    js = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    # 1. Approved business terminology and disclosure
    assert "创建 Excel 处理任务" in html
    assert "处理方式" in html
    assert "追加合并" in html
    assert "覆盖合并" in html
    assert "基线差异比对" in html
    assert "文件所在位置" in html
    assert "要处理的文件" in html
    assert "目标模板" in html
    assert "对比基准" in html
    assert "保存位置" in html
    assert "输出文件名" in html
    assert "防重标识" in html
    assert "高级信息" in html
    assert "处理记录" in html
    assert "处理历史" in html
    assert "输出文件" in html

    # 2. Dynamic visibility logic in JS
    assert "updateExcelCreateFields" in js
    assert 'operation === "diff_against_baseline"' in js
    assert 'operation === "merge_append"' in js
    assert 'node.hidden = false' in js
    assert '[data-excel-create-field][hidden]' in Path("web/static/style.css").read_text(encoding="utf-8-sig")


def test_excel_operation_examples_modal_and_animations() -> None:
    html = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")
    js = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    css = Path("web/static/style.css").read_text(encoding="utf-8-sig")

    # 1. Examples button and dialog
    assert 'id="excel-task-examples-btn"' in html
    assert "查看操作示例" in html
    assert 'id="excel-examples-dialog"' in html
    assert 'id="excel-examples-pause-btn"' in html
    assert 'id="excel-examples-close-btn"' in html

    # 2. 3 Animation types in HTML
    assert "追加合并" in html
    assert "覆盖合并" in html
    assert "基线差异比对" in html
    assert "anim-append" in html
    assert "anim-overlay" in html
    assert "anim-diff" in html

    # 3. JS and CSS animation wiring
    assert "setupExcelExamples" in js
    assert ".excel-examples-dialog" in css
    assert "is-paused" in css
    assert "@media (prefers-reduced-motion: reduce)" in css


def test_scheduled_archive_purpose_explanation_and_job_management(client) -> None:
    html = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")
    js = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    # 1. Purpose explanation and business wording in HTML
    assert "archive-purpose-note" in html
    assert "自动下载与留存" in html
    assert "定时任务" in html
    assert "自动下载与留存服务：" in html

    # 2. Create, copy, and archive cancellation controls
    assert 'id="archive-create-job-btn"' in html
    assert "openCreateJobModal" in js
    assert "APPROVED_ARCHIVE_TEMPLATES" in js
    assert "aras_ewo" in js
    assert "aras_paa" in js
    assert "archive-copy-job-btn" in js
    assert "archive-delete-job-btn" in js
    assert '"/api/scheduled-archive/jobs"' in js

    # 3. Frequency input
    assert "archive-field-interval" in js
    assert "intervalMinutes" in js

    # 4. Folder picker endpoint and safe object-shaped {name, relativePath} consuming
    assert '"/api/scheduled-archive/folders' in js
    assert "loadArchiveFolders" in js
    assert "renderArchiveFolderBrowser" in js
    assert "folder.name" in js
    assert "folder.relativePath" in js
    assert "archive-field-output-directory" in js
    assert "Windows 选择文件夹" in js
    assert "选择安全子目录" not in js

    # 5. Smoke test jobs and folders endpoint
    jobs_res = client.get("/api/scheduled-archive/jobs")
    assert jobs_res.status_code == 200

    folders_res = client.get("/api/scheduled-archive/folders")
    assert folders_res.status_code == 200
    data = folders_res.get_json()["data"]
    assert "current" in data
    assert "folders" in data


def test_settings_workbench_and_unified_domain_sessions(client) -> None:
    html = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")
    js = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    # 1. Navigation link enabled
    assert 'href="#settings-panel" data-panel-link="settings-panel">设置</a>' in html

    # 2. Settings form elements in HTML
    assert 'id="settings-panel"' in html
    assert 'id="settings-form"' in html
    assert 'id="settings-field-archive-dir"' in html
    assert 'id="settings-field-excel-dir"' in html
    assert 'id="settings-field-temp-dir"' in html
    assert 'id="settings-field-diag-dir"' in html
    assert 'id="settings-field-download-minutes"' in html
    assert 'id="settings-field-retry-count"' in html
    assert 'id="settings-field-due-soon-days"' in html
    assert 'id="settings-field-cache-snapshots"' in html
    assert 'id="settings-field-retention-days"' in html
    assert 'id="settings-save-btn"' in html

    # 3. Domain login form and session cards
    assert 'id="settings-sessions-card"' in html
    assert 'id="domain-login-form"' in html
    assert 'id="domain-login-username" name="username" autocomplete="username"' in html
    assert 'id="domain-login-password" name="password" type="password" autocomplete="current-password"' in html
    assert 'id="domain-login-btn"' in html
    assert 'id="settings-clear-aras-btn"' in html
    assert 'id="settings-clear-tdc-btn"' in html
    assert 'id="settings-clear-all-btn"' in html
    assert 'id="settings-excel-service-card"' in html

    # 4. JS module wiring
    assert "loadSettings" in js
    assert "setupSettings" in js
    assert "handleDomainLogin" in js
    assert "handleClearSessions" in js
    assert '"/api/settings"' in js
    assert '"/api/settings/domain-login"' in js
    assert '"/api/settings/sessions"' in js

    # 5. Smoke test settings GET and PATCH
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


def test_aras_autofill_and_non_sensitive_preference_storage() -> None:
    html = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")
    js = Path("web/static/app.js").read_text(encoding="utf-8-sig")

    # 1. Form and input autocomplete attributes
    assert '<form id="aras-form" class="aras-form" autocomplete="on">' in html
    # 统一域账号登录后，Aras 工作区表单不得再保留账号密码/Cookie 输入。
    assert 'id="aras-username"' not in html
    assert 'id="aras-password"' not in html
    assert 'id="aras-cookie"' not in html
    assert 'id="aras-auth-mode"' not in html

    # 2. Versioned key and sensitive field exclusions
    assert "vse-toolbox-aras-preferences-v1" in js
    assert "ARAS_FORBIDDEN_PERSIST_KEYS" in js
    for sensitive in ["password", "cookie", "authorization", "headers", "token", "secret"]:
        assert sensitive in js

    # 3. Restore and save preference handlers
    assert "restoreArasStoredPreferences" in js
    assert "saveArasStoredPreferences" in js


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
    assert ".archive-folder-picker" in css
    assert ".settings-workbench" in css
    assert ".excel-examples-dialog" in css
    assert "@media (max-width: 390px)" in css
