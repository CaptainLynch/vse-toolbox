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


def _slice(text: str, start_marker: str, end_marker: str) -> str:
    start = text.find(start_marker)
    assert start != -1, f"Start marker '{start_marker}' not found"
    end = text.find(end_marker, start)
    assert end != -1, f"End marker '{end_marker}' not found after '{start_marker}'"
    return text[start:end]


def test_form_detail_tabs_have_independent_filters_and_safe_click_handlers() -> None:
    js = _read("web/static/app.js")
    source = _slice(js, "function createDeliverableFormState", "function buildPaaInteractiveFilters")

    assert "filterStateByTab" in source
    assert "clearCurrentFilters" in source
    assert "appendFormFilter" in source
    assert "dateStart" in source and "dateEnd" in source
    assert "addEventListener(\"click\"" in source
    assert ".textContent" in source
    assert "innerHTML" not in source


def test_background_sync_and_interactive_refresh_remain_separate() -> None:
    js = _read("web/static/app.js")
    interactive = _slice(js, "async function runEwoInteractiveRefreshFromStatusChart", "async function refreshEwoAnalysisFromStatusChart")
    paa = _slice(js, "async function runPaaInteractiveRefresh", "function renderDeliverableDetailPage")

    assert 'requestInteractiveArasQuery("ewo"' in interactive
    assert 'requestInteractiveArasQuery("paa"' in paa
    assert "auth_mode: \"browser\"" in js
    assert "未认证" in js and "服务不可用" in js and "数据为空" in js and "未匹配" in js
    assert "/api/scheduled-archive/jobs/" in js
    assert "password" not in interactive
    assert "cookie" not in interactive


def test_archive_detail_keeps_audit_table_without_duplicate_snapshot_chart() -> None:
    js = _read("web/static/app.js")
    history = _slice(js, "const renderHistory = async () =>", "refreshButton.addEventListener")

    assert "external-run-table" in history
    assert "external-run-chart" not in history


def test_tdc_data_model_wiring_tabs_and_label_overrides() -> None:
    """数模表单在 UI 侧注册条目、页签、筛选与图表标题覆盖及空维度跳过逻辑。"""
    js = _read("web/static/app.js")

    # 表单键来自任务 payload 的 formKey 字段（后端单一关联注册表下发），
    # 前端不再持有 DELIVERABLE_FORM_KEY_BY_ITEM 回退映射。
    assert 'const formState = createDeliverableFormState(String(job.formKey || ""));' in js
    assert 'formKey: String(job.formKey || ""),' in js
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
    query_source = _slice(js, "const FORM_FILTER_QUERY_KEYS", "function deliverableFormKey")
    assert '"overdueState"' in query_source
    assert '"relationEwo"' in query_source

    filter_source = _slice(js, "function renderFormFilterBar", "function formStatusColorClass")
    assert "draft[key] = values.slice()" in filter_source
    assert "delete draft[key]" in filter_source


def test_tdc_project_and_archive_details_use_the_unified_form_shell() -> None:
    """VPI-T2-D5 and its archive job must expose the same named form view."""
    js = _read("web/static/app.js")
    project_detail = _slice(js, "function renderDeliverableDetailPage", "function renderArchiveDeliverableDetailPage")
    archive_detail = _slice(js, "function renderArchiveDeliverableDetailPage", "function toggleDeliverableDetail")

    assert "const formKey = deliverableFormKey(item);" in project_detail
    assert "createDeliverableFormState(formKey)" in project_detail
    assert 'tdc_data_model: ["数模设计审核流程报表", "TDC"]' in archive_detail


def test_tdc_sor_wiring_tabs_and_labels() -> None:
    """SOR 定点流程的前端接线：表单键、页签、筛选标签与图表标题。"""
    js = _read("web/static/app.js")

    # 表单键来自任务 payload 的 formKey 字段（后端单一关联注册表下发）。
    assert 'const formState = createDeliverableFormState(String(job.formKey || ""));' in js
    assert 'formKey: String(job.formKey || ""),' in js
    assert '["departmentStatus", "车型项目状态"]' in js
    assert '["sectionStatus", "科室状态"]' in js
    assert 'section: "科室"' in js
    assert 'stage: "车型项目"' in js
    assert 'departmentStatus: ["车型项目状态", "各车型项目按期推进数与逾期风险数"]' in js


_FORM_UNLOCK_NODE_HARNESS = r"""
const vm = require('vm');
const fs = require('fs');
const path = require('path');

class DOMTokenList {
  constructor(el) { this._el = el; this._set = new Set(); }
  add(...tokens) { tokens.forEach(t => this._set.add(t)); this._sync(); }
  remove(...tokens) { tokens.forEach(t => this._set.delete(t)); this._sync(); }
  toggle(token, force) {
    const res = force !== undefined ? Boolean(force) : !this._set.has(token);
    if (res) this._set.add(token); else this._set.delete(token);
    this._sync();
    return res;
  }
  contains(token) { return this._set.has(token); }
  _sync() { this._el._className = Array.from(this._set).join(' '); }
}

class Element {
  constructor(tagName) {
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.dataset = {};
    this.attributes = {};
    this._className = '';
    this.classList = new DOMTokenList(this);
    this._listeners = {};
    this.hidden = false;
    this.value = '';
    this._textContent = '';
    this.isConnected = true;
    this.disabled = false;
    this.type = '';
  }
  get className() { return this._className; }
  set className(val) {
    this._className = String(val || '');
    this.classList._set = new Set(this._className.split(/\s+/).filter(Boolean));
  }
  get textContent() { return this._textContent + this.children.map(c => c.textContent).join(''); }
  set textContent(val) {
    this._textContent = String(val === null || val === undefined ? '' : val);
    this.children = [];
  }
  get firstChild() { return this.children[0] || null; }
  appendChild(child) { if (!child) return child; child.parentNode = this; this.children.push(child); return child; }
  append(...items) { items.forEach(i => { if (i && typeof i === 'object') this.appendChild(i); }); }
  prepend(child) { child.parentNode = this; this.children.unshift(child); }
  insertBefore(newNode, refNode) {
    newNode.parentNode = this;
    const idx = this.children.indexOf(refNode);
    if (idx === -1) this.children.push(newNode);
    else this.children.splice(idx, 0, newNode);
    return newNode;
  }
  remove() {
    if (this.parentNode) {
      const i = this.parentNode.children.indexOf(this);
      if (i !== -1) this.parentNode.children.splice(i, 1);
      this.parentNode = null;
    }
  }
  addEventListener(event, fn) { (this._listeners[event] = this._listeners[event] || []).push(fn); }
  dispatchEvent(event) {
    const type = typeof event === 'string' ? event : (event.type || '');
    (this._listeners[type] || []).forEach(fn => fn(event));
  }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return this.attributes[k] !== undefined ? this.attributes[k] : null; }
  querySelector(sel) { const r = this.querySelectorAll(sel); return r.length ? r[0] : null; }
  querySelectorAll(selector) {
    const matches = [];
    const parts = String(selector).split(',').map(s => s.trim()).filter(Boolean);
    const walk = (node) => {
      if (node !== this && parts.some(p => matchesSelector(node, p))) matches.push(node);
      (node.children || []).forEach(walk);
    };
    walk(this);
    return matches;
  }
}

function matchesSelector(el, sel) {
  if (sel.startsWith('.')) return el.classList.contains(sel.slice(1));
  if (sel.startsWith('#')) return el.id === sel.slice(1);
  const attrMatch = sel.match(/^\[([a-zA-Z0-9_-]+)(?:=([^\]]+))?\]$/);
  if (attrMatch) {
    const name = attrMatch[1];
    const rawVal = attrMatch[2];
    const val = rawVal ? rawVal.replace(/^["']|["']$/g, '') : null;
    if (name.startsWith('data-')) {
      const dkey = name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      return val === null ? dkey in el.dataset : el.dataset[dkey] === val;
    }
    if (name in el.attributes) return val === null ? true : el.attributes[name] === val;
    return false;
  }
  return el.tagName.toLowerCase() === sel.toLowerCase();
}

class DocumentStub {
  constructor() { this.body = new Element('body'); }
  createElement(tagName) { return new Element(tagName); }
  createElementNS(_ns, tagName) { return new Element(tagName); }
  createTextNode(text) { const el = new Element('#text'); el._textContent = String(text); return el; }
  getElementById(id) { return this.body.querySelector('#' + id); }
  querySelector(sel) { return this.body.querySelector(sel); }
  querySelectorAll(sel) { return this.body.querySelectorAll(sel); }
  addEventListener() {}
}

const doc = new DocumentStub();
const context = vm.createContext({ document: doc, console, URL, URLSearchParams, setTimeout, clearTimeout });
vm.runInContext(fs.readFileSync(path.resolve(process.cwd(), 'web/static/app.js'), 'utf8'), context);

async function run() {
  const app = vm.runInContext('({ createDeliverableFormState, renderFormChartTabs, loadDeliverableFormView, setFormChartInteractionLocked, unlockFormChartInteraction })', context);
  /*TEST_BODY*/
}

run().then(res => { console.log(JSON.stringify(res || { ok: true })); }).catch(err => {
  console.error(err);
  process.exit(1);
});
"""


def run_form_unlock_node_test(js_body: str) -> dict:
    """Run a snippet against app.js in Node.js with minimal DOM stubs."""
    import json
    import subprocess

    script = _FORM_UNLOCK_NODE_HARNESS.replace("/*TEST_BODY*/", js_body)
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        cwd=Path(__file__).resolve().parent.parent,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"Node execution failed (code {proc.returncode}):\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return json.loads(proc.stdout.strip()) if proc.stdout.strip() else {}


def test_failed_tab_reload_unlocks_form_chart_interaction() -> None:
    """切换图表页签锁定交互后请求失败，错误分支必须解锁图表与明细表守卫区域。"""
    res = run_form_unlock_node_test("""
    const container = doc.createElement('div');
    doc.body.appendChild(container);
    const item = { id: 'VPI-T2-D3', formLink: { formKey: 'VPI-T2-D3' } };
    const state = app.createDeliverableFormState('VPI-T2-D3');
    const data = { formKey: 'VPI-T2-D3', reportType: 'ewo', charts: {} };
    const root = app.renderFormChartTabs(data, state, () => {});
    container.appendChild(root);
    const rowTable = doc.createElement('section');
    rowTable.className = 'form-row-table-section';
    container.appendChild(rowTable);
    // 节点缺失时 unlockFormChartInteraction 必须安全 no-op。
    app.unlockFormChartInteraction(null);

    context.fetch = () => Promise.resolve({ ok: false, status: 500, json: async () => ({ ok: false }) });
    let reloadPromise = null;
    const onReload = () => {
      reloadPromise = app.loadDeliverableFormView(container, item, { state });
      return reloadPromise;
    };
    const root2 = app.renderFormChartTabs(data, state, onReload, { existingChartTabs: root });
    const tabButtons = root2.querySelectorAll('.form-chart-tab');
    if (tabButtons.length < 2) throw new Error('expected at least two chart tabs');
    tabButtons[1].dispatchEvent({ type: 'click' });
    const ok = await reloadPromise;

    return {
      loadReturnedFalse: ok === false,
      errorShown: Boolean(container.querySelector('.form-view-load-error')),
      tabsUnlocked: root2.dataset.formInteractionLocked === 'false',
      rowTableUnlocked: rowTable.dataset.formInteractionLocked === 'false',
    };
    """)
    assert res["loadReturnedFalse"] is True
    assert res["errorShown"] is True
    assert res["tabsUnlocked"] is True
    assert res["rowTableUnlocked"] is True


def test_stale_failed_tab_reload_keeps_guards_locked() -> None:
    """过期请求（formViewRequestIsCurrent 为 false）提前 return，不解锁守卫区域。"""
    res = run_form_unlock_node_test("""
    const container = doc.createElement('div');
    doc.body.appendChild(container);
    const item = { id: 'VPI-T2-D3', formLink: { formKey: 'VPI-T2-D3' } };
    const state = app.createDeliverableFormState('VPI-T2-D3');
    const data = { formKey: 'VPI-T2-D3', reportType: 'ewo', charts: {} };
    const root = app.renderFormChartTabs(data, state, () => {});
    container.appendChild(root);
    const rowTable = doc.createElement('section');
    rowTable.className = 'form-row-table-section';
    container.appendChild(rowTable);

    context.fetch = () => new Promise((resolve) => setTimeout(
      () => resolve({ ok: false, status: 500, json: async () => ({ ok: false }) }), 20));
    // 模拟页签切换先锁定交互，随后发出的刷新请求已过期。
    app.setFormChartInteractionLocked(root, true);
    const pending = app.loadDeliverableFormView(container, item, { state });
    state.requestSeq += 1; // 让在途请求过期
    await pending;

    return {
      tabsStillLocked: root.dataset.formInteractionLocked === 'true',
      rowTableStillLocked: rowTable.dataset.formInteractionLocked === 'true',
      errorHidden: !container.querySelector('.form-view-load-error'),
    };
    """)
    assert res["tabsStillLocked"] is True
    assert res["rowTableStillLocked"] is True
    assert res["errorHidden"] is True
