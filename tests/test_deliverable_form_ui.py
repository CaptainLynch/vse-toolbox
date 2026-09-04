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


def test_tdc_data_model_wiring_tabs_and_label_overrides() -> None:
    """数模表单在 UI 侧注册条目、页签、筛选与图表标题覆盖及空维度跳过逻辑。"""
    js = _read("web/static/app.js")

    assert '"VPI-T2-D5": "tdc_data_model"' in js
    assert "tdc_data_model: \"tdc_data_model\"" in js
    assert '["departmentStatus", "项目状态"]' in js
    assert '["sectionStatus", "部门状态"]' in js
    assert '["quantityTrend", "数量趋势"]' in js

    # 按表单覆盖的筛选标签。
    assert "const DELIVERABLE_FORM_FILTER_LABELS" in js
    assert 'section: "部门"' in js
    assert 'model: "发布属性"' in js
    assert 'stage: "项目 / 车型"' in js
    assert 'dateStart: "申请日期（起）"' in js
    assert 'dateEnd: "申请日期（止）"' in js
    assert "function deliverableFormFilterLabel" in js

    # 按表单覆盖的图表标题与说明。
    assert "const DELIVERABLE_FORM_CHART_TITLES" in js
    assert "各项目 / 车型按期推进数与逾期风险数" in js
    assert "点击一个部门可追加筛选" in js

    # department 无可选值时不渲染空下拉。
    assert "departmentValues.length" in js


def test_stage_b_filters_reach_both_form_queries_and_keep_multi_select_state() -> None:
    """Stage B filter controls must be serialized and persisted before reload."""
    js = _read("web/static/app.js")
    query_start = js.index("const FORM_FILTER_QUERY_KEYS")
    query_end = js.index("function deliverableFormKey", query_start)
    query_source = js[query_start:query_end]
    assert '"overdueState"' in query_source
    assert '"relationEwo"' in query_source

    filter_start = js.index("function renderFormFilterBar")
    filter_end = js.index("function formStatusColorClass", filter_start)
    filter_source = js[filter_start:filter_end]
    assert "current[key] = values" in filter_source
    assert "delete current[key]" in filter_source


def test_tdc_project_and_archive_details_use_the_unified_form_shell() -> None:
    """VPI-T2-D5 and its archive job must expose the same named form view."""
    js = _read("web/static/app.js")
    project_detail = js[js.index("function renderDeliverableDetailPage"):js.index("function renderArchiveDeliverableDetailPage")]
    archive_detail = js[js.index("function renderArchiveDeliverableDetailPage"):js.index("function toggleDeliverableDetail")]

    assert "const formKey = deliverableFormKey(item);" in project_detail
    assert "createDeliverableFormState(formKey)" in project_detail
    assert 'tdc_data_model: ["数模设计审核流程报表", "TDC"]' in archive_detail
