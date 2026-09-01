# -*- coding: utf-8 -*-
"""Static regression contract for the unified deliverable form detail UI."""

from __future__ import annotations

from pathlib import Path


def _read(name: str) -> str:
    return Path(name).read_text(encoding="utf-8-sig")


def test_unified_form_detail_contract_and_endpoint_wiring() -> None:
    js = _read("web/static/app.js")
    css = _read("web/static/style.css")

    for marker in (
        "function loadDeliverableFormView",
        "function refreshEwoFormFromStatusChart",
        "function renderDeliverableFormAnalysis",
        "function renderFormChartTabs",
        "function renderFormFilterBar",
        "function renderFormRowsTable",
        "/api/deliverable-forms/",
        "VPI-T2-D3",
        "aras_ncr_progress",
        "aras_ncr_detail",
        "departmentStatus",
        "sectionStatus",
        "quantityTrend",
        "departmentCost",
        "sectionCost",
        "chart-filter-state",
        "form-chart-tab",
        "form-row-table",
        "NCR 明细不计算逾期",
    ):
        assert marker in js

    for marker in (
        ".deliverable-form-analysis",
        ".form-chart-tabs",
        ".form-chart-tab",
        ".form-filter-bar",
        ".form-filter-chip",
        ".form-chart-panel[hidden]",
        ".form-status-bar",
        ".form-trend-svg",
        ".form-cost-change-increase",
        ".form-cost-change-decrease",
        ".form-row-table",
    ):
        assert marker in css


def test_form_detail_tabs_have_independent_filters_and_safe_click_handlers() -> None:
    js = _read("web/static/app.js")
    start = js.index("function createDeliverableFormState")
    end = js.index("function buildPaaInteractiveFilters", start)
    source = js[start:end]

    assert "filterStateByTab" in source
    assert "clearCurrentFilters" in source
    assert "appendFormFilter" in source
    assert "dateStart" in source and "dateEnd" in source
    assert "addEventListener(\"click\"" in source
    assert ".textContent" in source
    assert "innerHTML" not in source


def test_background_sync_and_interactive_refresh_remain_separate() -> None:
    js = _read("web/static/app.js")
    interactive = js[js.index("async function runEwoInteractiveRefreshFromStatusChart"):js.index("async function refreshEwoAnalysisFromStatusChart")]
    paa = js[js.index("async function runPaaInteractiveRefresh"):js.index("function renderDeliverableDetailPage")]

    assert 'requestInteractiveArasQuery("ewo"' in interactive
    assert 'requestInteractiveArasQuery("paa"' in paa
    assert "auth_mode: \"browser\"" in js
    assert "未认证" in js and "服务不可用" in js and "数据为空" in js and "未匹配" in js
    assert "/api/scheduled-archive/jobs/" in js
    assert "password" not in interactive
    assert "cookie" not in interactive


def test_archive_detail_keeps_audit_table_without_duplicate_snapshot_chart() -> None:
    js = _read("web/static/app.js")
    history = js[js.index("const renderHistory = async () =>"):js.index("refreshButton.addEventListener", js.index("const renderHistory = async () =>"))]

    assert "external-run-table" in history
    assert "external-run-chart" not in history
