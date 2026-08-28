"""Static contracts for the Excel task and artifact management UI."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "web" / "templates" / "dashboard.html"
JS_PATH = ROOT / "web" / "static" / "app.js"
CSS_PATH = ROOT / "web" / "static" / "style.css"


def test_excel_workspace_markup_is_present() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")

    assert 'data-panel-link="excel-tasks"' in html
    assert 'id="excel-tasks"' in html
    assert 'id="excel-worker-state"' in html
    assert 'id="excel-task-create-form"' in html
    assert 'id="excel-task-operation"' in html
    assert 'data-excel-root-select' in html
    assert 'id="excel-idempotency-key"' in html
    assert 'id="excel-task-list"' in html
    assert 'id="excel-task-detail"' in html
    assert 'id="excel-task-runs"' in html
    assert 'id="excel-task-artifact-list"' in html
    assert 'id="excel-retention-preview-btn"' in html
    assert 'id="excel-retention-plan"' in html


def test_excel_ui_uses_server_issued_artifact_ids_for_downloads() -> None:
    js = JS_PATH.read_text(encoding="utf-8")

    assert "loadExcelTaskWorkspace" in js
    assert 'fetch("/api/excel-roots"' in js
    assert 'fetch("/api/excel-tasks"' in js
    assert "validateExcelRelativePath" in js
    assert "crypto.randomUUID" in js
    assert "/api/excel-tasks${query}" in js
    assert "/api/excel-tasks/${encodeURIComponent(taskId)}/runs" in js
    assert "/api/excel-tasks/${encodeURIComponent(taskId)}/artifacts" in js
    assert "/api/excel-artifacts/${encodeURIComponent(artifact.id)}/download" in js
    assert "/api/excel-artifacts/${encodeURIComponent(artifact.id)}/download-audit?limit=50" in js
    assert "/api/excel-artifacts/retention-plan?retentionDays=" in js
    assert "URL.revokeObjectURL" in js
    assert "artifact.relativePath" not in js
    assert "artifact.rootId" not in js


def test_excel_ui_has_responsive_operational_styles() -> None:
    css = CSS_PATH.read_text(encoding="utf-8")

    assert ".excel-task-layout" in css
    assert ".excel-task-create-form" in css
    assert ".excel-task-table" in css
    assert ".excel-download-btn" in css
    assert ".excel-artifact-audit-box" in css
    assert ".excel-retention-controls" in css
    assert "@media (max-width: 820px)" in css
