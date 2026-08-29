# -*- coding: utf-8 -*-
"""Focused tests for the VSE Toolbox 定时归档管理 (Scheduled Archive Admin UI).

Covers:
1. Navigation and panel integration (概览, Aras, 交付物, 归档).
2. Static DOM hooks, semantic elements, unique IDs, role and aria-live attributes.
3. Safe DOM construction contract (no innerHTML in archive code, using textContent).
4. Endpoint contracts (/api/scheduled-archive/jobs, PATCH, sync-now, runs, artifacts, config-audit).
5. Safe credentialRef selection (never prefilled, cleared in finally, clearAlias logic).
6. Client-side validations (non-array object filters, enabled + clearAlias conflict guard).
7. Artifact relativePath metadata only (no download links, no arbitrary file paths).
8. Absence of browser timers/polling loops (pure event-driven refreshes).
9. Cache-buster versions updated in dashboard.html.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import web.app as web_app
from core.db_manager import DatabaseManager
from services.scheduled_archive_admin import ScheduledArchiveAdminService
from services.scheduled_archive_runner import (
    ArchiveJobRunResult,
    ArchiveRunOnceResult,
    ArchiveSyncRunner,
)


@pytest.fixture()
def test_db(monkeypatch, tmp_path: Path) -> DatabaseManager:
    """Provide an isolated temporary SQLite database for web client tests."""
    db_file = tmp_path / "archive_ui_test.db"
    db_instance = DatabaseManager(db_path=db_file)
    db_instance.init_database()
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_instance)
    return db_instance


@pytest.fixture()
def fake_runner() -> MagicMock:
    """Provide a fake runner without external network calls or scheduling loops."""
    runner = MagicMock(spec=ArchiveSyncRunner)
    runner.run_once.return_value = ArchiveRunOnceResult(
        results=(
            ArchiveJobRunResult(
                job_id=1,
                job_key="aras_ewo",
                outcome="completed",
                run_id=101,
                final_state="success",
            ),
        ),
        dry_run=False,
    )
    return runner


@pytest.fixture()
def client(monkeypatch, test_db: DatabaseManager, fake_runner: MagicMock):
    """Provide a Flask test client configured with isolated DB and fake runner."""
    monkeypatch.setattr(
        web_app,
        "ScheduledArchiveAdminService",
        lambda db: ScheduledArchiveAdminService(db, runner_factory=lambda _db: fake_runner),
    )
    app = web_app.create_app()
    # The production app attaches the DPAPI provider; this isolated API test
    # uses arbitrary opaque aliases and a fake runner instead.
    app.extensions["scheduled_archive_admin"].set_credential_provider(None)
    app.config.update(TESTING=True)
    return app.test_client()


# ── 1. Navigation & Static HTML Structure ────────────────────────────────────


def test_index_renders_archive_nav_and_preserves_panels(client) -> None:
    """Verify that index page includes 自动下载与留存 tab while preserving overview, Aras, and deliverables."""
    resp = client.get("/")
    assert resp.status_code == 200
    html_text = resp.get_data(as_text=True)

    # Top-level workspace navigation
    assert 'data-panel-link="overview"' in html_text
    assert 'data-panel-link="aras-panel"' in html_text
    assert 'data-panel-link="deliverables"' in html_text
    assert 'data-panel-link="scheduled-archive"' in html_text
    assert "自动下载与留存" in html_text

    # Main sections exist
    assert 'id="overview"' in html_text
    assert 'id="aras-panel"' in html_text
    assert 'id="deliverables"' in html_text
    assert 'id="scheduled-archive"' in html_text
    assert 'class="panel-section scheduled-archive-workbench"' in html_text


def test_dashboard_html_cache_buster_updated() -> None:
    """Verify that cache buster query string in dashboard.html is updated."""
    html_text = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")
    assert '<link rel="stylesheet" href="/static/style.css?v=domain-unify-20260828-r3" />' in html_text
    assert '<script src="/static/app.js?v=domain-unify-20260828-r3"></script>' in html_text


def test_archive_static_dom_hooks_and_unique_ids() -> None:
    """Verify static DOM element IDs in dashboard.html are unique and match contract."""
    html_text = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")

    required_hooks = (
        'id="scheduled-archive"',
        'id="archive-refresh-btn"',
        'id="archive-global-error"',
        'id="archive-global-status"',
        'id="archive-jobs-list"',
        'id="archive-config-card"',
        'id="archive-tab-runs"',
        'id="archive-tab-audit"',
        'id="archive-runs-panel"',
        'id="archive-audit-panel"',
        'id="archive-refresh-runs-btn"',
        'id="archive-refresh-audit-btn"',
        'id="archive-runs-list"',
        'id="archive-artifacts-view"',
        'id="archive-close-artifacts-btn"',
        'id="archive-artifacts-list"',
        'id="archive-audit-list"',
        'id="archive-create-menu"',
    )
    for hook in required_hooks:
        assert hook in html_text, f"Missing required hook: {hook}"

    # Verify ID uniqueness across the whole dashboard
    all_ids = re.findall(r'id="([^"]+)"', html_text)
    assert len(all_ids) == len(set(all_ids)), "Duplicate element IDs found in dashboard.html"


def test_archive_accessibility_attributes() -> None:
    """Verify ARIA live regions, pressed switches, and panels in scheduled-archive template."""
    html_text = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")
    start = html_text.index('id="scheduled-archive"')
    end = html_text.index('</main>')
    archive_html = html_text[start:end]

    # Accessible button switch pattern (aria-pressed / aria-controls) avoiding role="tab" collision with overview
    assert 'role="tab"' not in archive_html
    assert 'role="tabpanel"' not in archive_html
    assert 'aria-live="polite"' in archive_html
    assert 'aria-pressed="true"' in archive_html
    assert 'aria-pressed="false"' in archive_html
    assert 'aria-controls="archive-runs-panel"' in archive_html
    assert 'aria-controls="archive-audit-panel"' in archive_html


# ── 2. JavaScript Safety & DOM Construction Contracts ─────────────────────────


def _get_archive_js_module() -> str:
    js_text = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    start = js_text.index("/* ── Scheduled Archive Administration Module")
    end = js_text.index("function updateArasActionButtons")
    return js_text[start:end]


def test_no_inner_html_in_archive_js_module() -> None:
    """Verify no innerHTML assignment exists in the scheduled archive administration module."""
    archive_js = _get_archive_js_module()
    assert "innerHTML" not in archive_js, "innerHTML must not be used in scheduled archive module"


def test_archive_js_uses_text_content_and_safe_nodes() -> None:
    """Verify archive JS creates safe DOM elements and assigns values via textContent."""
    archive_js = _get_archive_js_module()
    assert "document.createElement" in archive_js
    assert "textContent" in archive_js
    assert "appendChild" in archive_js
    assert "clearArchiveContainer" in archive_js


def test_no_timers_or_polling_loops_in_archive_js() -> None:
    """Verify no browser polling loops or interval schedulers exist in the archive module."""
    archive_js = _get_archive_js_module()
    assert "setInterval" not in archive_js
    assert "setTimeout" not in archive_js
    assert "requestAnimationFrame" not in archive_js


def test_no_download_links_in_archive_artifacts() -> None:
    """Verify artifact listing renders only controlled relativePath metadata without download links."""
    archive_js = _get_archive_js_module()
    # Ensure no anchor tags or href attributes or download attributes are constructed for artifacts
    assert "createElement(\"a\")" not in archive_js
    assert "createElement('a')" not in archive_js
    assert 'href' not in archive_js
    assert 'setAttribute("download"' not in archive_js
    assert "setAttribute('download'" not in archive_js
    assert "relativePath" in archive_js
    assert "renderArchiveArtifactsList" in archive_js


def test_credential_ref_selection_and_finally_clearing() -> None:
    """Verify the scheduled task exposes the approved DPAPI reference without a secret-looking password field."""
    archive_js = _get_archive_js_module()

    # Never set a credential value from job state and do not render it as a password.
    assert 'aliasInput.value = job.credentialRef' not in archive_js
    assert 'aliasInput.value = job.credential_ref' not in archive_js
    assert 'aliasInput.type = "password"' not in archive_js
    assert 'aliasInput.type = "text"' not in archive_js
    assert '"domain"' in archive_js
    assert "统一域账号" in archive_js
    assert "保存至凭据保护库" in archive_js

    # Cleared in finally
    assert 'aliasInput.value = ""' in archive_js
    assert 'finally' in archive_js


def test_archive_ui_uses_api_builtin_contract_and_beginner_controls() -> None:
    """Verify built-in task lifecycle and visible filter controls follow the API contract."""
    archive_js = _get_archive_js_module()
    assert "job.builtin" in archive_js
    assert "job.isBuiltin" not in archive_js
    assert "ARCHIVE_FILTER_FIELDS" in archive_js
    assert "archive-filter-field" in archive_js
    assert "高级 JSON" in archive_js
    assert "最多尝试" in archive_js
    assert "内置任务不可删除" not in archive_js
    assert "删除内置任务" in archive_js


def test_archive_ui_uses_task_directory_picker_contract() -> None:
    """Verify the local EXE chooses an absolute task directory instead of a subdirectory."""
    archive_js = _get_archive_js_module()
    assert "/api/scheduled-archive/folders/native" in archive_js
    assert "archive-native-folder-btn" in archive_js
    assert "nativeFolderBtn.addEventListener" in archive_js
    assert "archive-field-output-directory" in archive_js
    assert "outputDirectory" in archive_js
    assert "归档目录" in archive_js
    assert "Windows 选择文件夹" in archive_js
    assert "选择安全子目录" not in archive_js


def test_archive_ui_has_top_create_submenu_and_task_actions() -> None:
    """Create controls belong above the task list and each task owns its action area."""
    html_text = Path("web/templates/dashboard.html").read_text(encoding="utf-8-sig")
    archive_js = _get_archive_js_module()
    assert 'id="archive-create-menu"' in html_text
    assert "archive-create-submenu" in archive_js
    assert "archive-create-source-btn" in archive_js
    assert "archive-job-actions" in archive_js
    assert "archive-job-delete-btn" in archive_js
    assert "document.body.appendChild(modal)" not in archive_js


def test_archive_template_names_match_business_deliverables() -> None:
    """Template labels use the deliverable names instead of implementation jargon."""
    archive_js = _get_archive_js_module()
    assert "数模设计审核流程报表" in archive_js
    assert "TDC SOR (tdc_sor)" in archive_js
    assert "TDC SOR 零件明细" not in archive_js


def test_client_side_validation_rules_in_js() -> None:
    """Verify non-array object JSON validation and enabled + clearAlias conflict guard."""
    archive_js = _get_archive_js_module()

    # Validation: enabled + clearAlias guard
    assert "enabled && clearAlias" in archive_js

    # Validation: filters JSON is non-array object
    assert "JSON.parse" in archive_js
    assert "Array.isArray" in archive_js
    assert "typeof parsedFilters !== \"object\"" in archive_js or "typeof parsedFilters !== 'object'" in archive_js


def test_endpoint_urls_in_archive_js() -> None:
    """Verify all 7 allowed /api/scheduled-archive endpoints are used in archive JS."""
    archive_js = _get_archive_js_module()

    assert '"/api/scheduled-archive/folders' in archive_js
    assert '"/api/scheduled-archive/jobs"' in archive_js
    assert '`/api/scheduled-archive/jobs/${encodeURIComponent(job.jobKey)}`' in archive_js
    assert '`/api/scheduled-archive/jobs/${encodeURIComponent(job.jobKey)}/sync-now`' in archive_js
    assert '"/api/scheduled-archive/runs' in archive_js
    assert '`/api/scheduled-archive/runs/${encodeURIComponent(runId)}/artifacts`' in archive_js
    assert '"/api/scheduled-archive/config-audit' in archive_js


def test_supported_and_unknown_states_in_js() -> None:
    """Verify actual API states are handled and unknown states safely fall back to 待确认/未知."""
    archive_js = _get_archive_js_module()

    # Sync states
    for sync_state in ("needs_attention", "success", "idle", "running", "failed"):
        assert f'syncState === "{sync_state}"' in archive_js or f"job.syncState === \"{sync_state}\"" in archive_js

    # Invented sync states should not be treated as recognized states
    assert 'syncState === "active"' not in archive_js
    assert 'syncState === "disabled"' not in archive_js

    # Run states
    for run_state in ("success", "failed", "running", "leased", "partial", "needs_attention", "expired"):
        assert f'state === "{run_state}"' in archive_js

    # Fallback to 待确认/未知
    assert "待确认/未知" in archive_js
    assert "需关注" in archive_js
    assert "is-needs-attention" in archive_js
    assert "is-unknown" in archive_js
    assert "is-fresh" in archive_js
    assert "is-stale" in archive_js


def test_interval_and_retry_unknown_fallbacks() -> None:
    """Verify interval and retry policy render 待确认/未知 on invalid or missing values."""
    archive_js = _get_archive_js_module()

    assert "job.intervalMinutes || 60" not in archive_js
    assert "默认 1 次" not in archive_js
    assert "Number.isInteger(job.intervalMinutes)" in archive_js
    assert "Number.isInteger(job.retryPolicy.max_attempts)" in archive_js


def test_sync_now_eligibility_restored_in_finally() -> None:
    """Verify Sync Now button eligibility also reflects real credential availability."""
    archive_js = _get_archive_js_module()

    # Both save and sync-now finally blocks must preserve eligibility
    assert "credentialAvailable" in archive_js
    assert archive_js.count("syncNowBtn.disabled") >= 3


# ── 3. CSS Contracts ─────────────────────────────────────────────────────────


def test_archive_css_classes_and_responsive_rules() -> None:
    """Verify scheduled archive CSS classes and responsive layouts exist in style.css."""
    css_text = Path("web/static/style.css").read_text(encoding="utf-8-sig")

    for marker in (
        ".scheduled-archive-workbench",
        ".archive-head",
        ".archive-layout",
        ".archive-jobs-pane",
        ".archive-job-item",
        ".archive-config-card",
        ".archive-status-banner",
        ".archive-history-band",
        ".archive-tab",
        ".archive-artifacts-table",
        ".archive-chip.is-fresh",
        ".archive-chip.is-stale",
        ".archive-chip.is-unknown",
        ".archive-chip.is-needs-attention",
    ):
        assert marker in css_text, f"Missing CSS marker: {marker}"

    # Responsive rules under max-width: 560px
    mobile_css = css_text[css_text.index("@media (max-width: 560px)"):]
    assert ".archive-layout" in mobile_css
    assert "grid-template-columns: 1fr;" in mobile_css

    # Base archive layout must be outside every max-width media block.
    archive_base = css_text.index("/* ── Scheduled Archive Administration Styles")
    archive_mobile = css_text.index("@media (max-width: 560px)", archive_base)
    base_layout = css_text.index(".archive-layout {", archive_base)
    assert archive_base < base_layout < archive_mobile
    assert css_text.count("{") == css_text.count("}")


# ── 4. End-to-End Endpoint Smoke Test with Client ────────────────────────────


def test_scheduled_archive_api_smoke(client, test_db: DatabaseManager) -> None:
    """Smoke test client interaction with backend API routes."""
    # 1. GET jobs
    resp = client.get("/api/scheduled-archive/jobs")
    assert resp.status_code == 200
    jobs = resp.get_json()["data"]
    assert len(jobs) == 6
    job_map = {j["jobKey"]: j for j in jobs}
    assert "aras_ewo" in job_map
    assert job_map["aras_ewo"]["intervalMinutes"] == 60
    assert "credentialRef" not in job_map["aras_ewo"]

    # 2. PATCH job with write-only alias
    headers = {"Host": "localhost:5000", "Origin": "http://localhost:5000", "Sec-Fetch-Site": "same-origin"}
    environ = {"REMOTE_ADDR": "127.0.0.1", "HTTP_HOST": "localhost:5000"}

    patch_resp = client.patch(
        "/api/scheduled-archive/jobs/aras_ewo",
        json={
            "enabled": True,
            "credentialRef": "vault_alias_test",
            "filters": {"state": "Released"},
            "outputSubdir": "aras/ewo",
            "updatedAt": job_map["aras_ewo"]["updatedAt"],
        },
        headers=headers,
        environ_base=environ,
    )
    assert patch_resp.status_code == 200
    patched_job = patch_resp.get_json()["data"]
    assert patched_job["enabled"] is True
    assert patched_job["credentialConfigured"] is True
    assert "vault_alias_test" not in patch_resp.get_data(as_text=True)

    # 3. POST sync-now
    sync_resp = client.post(
        "/api/scheduled-archive/jobs/aras_ewo/sync-now",
        headers=headers,
        environ_base=environ,
    )
    assert sync_resp.status_code == 200
    assert sync_resp.get_json()["ok"] is True

    # 4. GET runs
    runs_resp = client.get("/api/scheduled-archive/runs?jobKey=aras_ewo")
    assert runs_resp.status_code == 200
    assert isinstance(runs_resp.get_json()["data"], list)

    # 5. GET config-audit
    audit_resp = client.get("/api/scheduled-archive/config-audit?jobKey=aras_ewo")
    assert audit_resp.status_code == 200
    audits = audit_resp.get_json()["data"]
    assert len(audits) >= 1
    assert "vault_alias_test" not in audit_resp.get_data(as_text=True)

    # 6. GET folders
    folders_resp = client.get("/api/scheduled-archive/folders")
    assert folders_resp.status_code == 200
    folders_data = folders_resp.get_json()["data"]
    assert "current" in folders_data
    assert "folders" in folders_data
