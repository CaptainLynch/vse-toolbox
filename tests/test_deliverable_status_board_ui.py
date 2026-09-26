# -*- coding: utf-8 -*-
"""Behavior tests for the department-status two-tab board and section rollup editor."""

from __future__ import annotations

from pathlib import Path

import pytest


def _read(name: str) -> str:
    return Path(name).read_text(encoding="utf-8-sig")


def _slice(text: str, start_marker: str, end_marker: str) -> str:
    start = text.find(start_marker)
    assert start != -1, f"Start marker '{start_marker}' not found"
    end = text.find(end_marker, start)
    assert end != -1, f"End marker '{end_marker}' not found after '{start_marker}'"
    return text[start:end]


_BOARD_NODE_HARNESS = r"""
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
    this.open = false;
    this.style = {};
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
  replaceWith(el) {
    if (!this.parentNode) return;
    const i = this.parentNode.children.indexOf(this);
    if (i !== -1) this.parentNode.children[i] = el;
    el.parentNode = this.parentNode;
    this.parentNode = null;
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
    return name in el.attributes;
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
  const app = vm.runInContext('({ createDeliverableFormState, renderFormChartTabs, renderDepartmentStatusBoard, renderSectionCountsBoard, renderSectionRollupPanel })', context);

  const matrix = {
    sections: [
      { label: '车身科', total: 3, cells: [
        { label: 'PE提交', count: 1 }, { label: 'NCR管理员', count: 2 },
      ] },
      { label: '内饰科', total: 0, cells: [
        { label: 'PE提交', count: 0 }, { label: 'NCR管理员', count: 0 },
      ] },
      { label: '未归集', total: 1, cells: [
        { label: 'PE提交', count: 1 }, { label: 'NCR管理员', count: 0 },
      ] },
    ],
    stages: [
      { label: 'PE提交', total: 2, cells: [
        { label: '车身科', count: 1 }, { label: '内饰科', count: 0 }, { label: '未归集', count: 1 },
      ] },
      { label: 'NCR管理员', total: 2, cells: [
        { label: '车身科', count: 2 }, { label: '内饰科', count: 0 }, { label: '未归集', count: 0 },
      ] },
      { label: '其他状态', total: 0, cells: [
        { label: '车身科', count: 0 }, { label: '内饰科', count: 0 }, { label: '未归集', count: 0 },
      ] },
    ],
  };
  const rules = { version: 1, updatedAt: '2026-09-26T00:00:00.000Z', targets: [
    { target: '车身科', aliases: ['结构工程科'] },
    { target: '内饰科', aliases: [] },
  ] };
  const data = {
    formKey: 'aras_ncr_progress',
    reportType: 'ncr_progress',
    sectionRollup: rules,
    charts: { sectionStageMatrix: matrix },
  };

  const state = app.createDeliverableFormState('aras_ncr_progress');
  let reloads = 0;
  const onReload = () => { reloads += 1; };
  const root = app.renderFormChartTabs(data, state, onReload);

  const boardRows = root.querySelectorAll('.form-status-bar-row');
  const boardTabs = root.querySelectorAll('.dept-board-tab');
  const rollupPanels = root.querySelectorAll('.form-rollup-panel');
  const firstRowAria = boardRows[0].getAttribute('aria-label');

  // 行点击 → 追加科室筛选（多选键）并触发刷新。
  boardRows[0].dispatchEvent({ type: 'click' });
  const appliedSection = JSON.stringify(state.filterStateByTab.departmentStatus.section);
  const reloadsAfterRowClick = reloads;

  // 切换「按状态」分页并重渲染（真实应用中 onReload 会整树刷新）。
  boardTabs[1].dispatchEvent({ type: 'click' });
  const root2 = app.renderFormChartTabs(data, state, onReload, { existingChartTabs: root });
  const byStatusRows = root2.querySelectorAll('.form-status-bar-row');
  const statusRowLabels = byStatusRows.map((row) => row.children[0].textContent);
  const staticRows = byStatusRows.filter((row) => !row.getAttribute('role'));
  const statusFirstSegments = byStatusRows[0].querySelectorAll('.form-status-bar-fill').length;

  // 切回「按科室」，进入规则编辑态并增删历史值。
  root2.querySelectorAll('.dept-board-tab')[0].dispatchEvent({ type: 'click' });
  const root3 = app.renderFormChartTabs(data, state, onReload, { existingChartTabs: root2 });
  const editButton = root3.querySelector('.form-rollup-edit');
  editButton.dispatchEvent({ type: 'click' });
  const editing = state.rollupEditing === true;
  const editedPanel = root3.querySelector('.form-rollup-panel');
  const chipsBefore = editedPanel.querySelectorAll('.form-rollup-chip').length;
  const removeButton = editedPanel.querySelector('.form-rollup-chip-remove');
  removeButton.dispatchEvent({ type: 'click' });
  const refreshedPanel = root3.querySelector('.form-rollup-panel');
  const chipsAfter = refreshedPanel.querySelectorAll('.form-rollup-chip').length;
  const draftAliases = state.rollupDraft[0].aliases.slice();

  // 保存：stub fetch 返回成功，编辑态退出并触发刷新。
  let putBody = null;
  context.fetch = async (_url, options) => {
    putBody = JSON.parse(options.body);
    return { ok: true, status: 200, json: async () => ({ ok: true, data: { version: 1, updatedAt: 'x', targets: putBody.targets } }) };
  };
  const saveButton = root3.querySelector('.form-rollup-save');
  saveButton.dispatchEvent({ type: 'click' });
  await new Promise((resolve) => setTimeout(resolve, 0));
  const reloadsAfterSave = reloads;

  // NCR明细：仅按科室计数板。
  const countsState = app.createDeliverableFormState('aras_ncr_detail');
  const countsData = {
    formKey: 'aras_ncr_detail',
    reportType: 'ncr_detail',
    sectionRollup: rules,
    charts: { sectionCounts: [{ label: '车身科', total: 2 }, { label: '未归集', total: 1 }] },
  };
  const countsRoot = app.renderSectionCountsBoard(countsData, countsState, () => {});
  const countRows = countsRoot.querySelectorAll('.form-status-bar-row');
  const countNums = countRows.map((row) => row.children[2].textContent);

  return {
    boardTabs: boardTabs.length,
    boardRows: boardRows.length,
    firstRowAria,
    appliedSection,
    reloadsAfterRowClick,
    byStatusRows: byStatusRows.length,
    statusRowLabels,
    staticRows: staticRows.length,
    statusFirstSegments,
    rollupPanels: rollupPanels.length,
    editing,
    chipsBefore,
    chipsAfter,
    draftAliases,
    savedTargets: putBody ? putBody.targets : null,
    editingAfterSave: state.rollupEditing,
    reloadsAfterSave,
    countRows: countRows.length,
    countNums,
  };
}

run().then(res => { console.log(JSON.stringify(res)); }).catch(err => {
  console.error(err);
  process.exit(1);
});
"""


def _run_board_node_test() -> dict:
    import json
    import subprocess

    proc = subprocess.run(
        ["node", "-e", _BOARD_NODE_HARNESS],
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
    return json.loads(proc.stdout.strip())


def test_department_status_board_pivots_filters_and_rollup_editor() -> None:
    res = _run_board_node_test()

    # 「按科室」分页：行 = 归集后科室（含未归集），顶部分页切换存在。
    assert res["boardTabs"] == 2
    assert res["boardRows"] == 3
    assert res["firstRowAria"] == "车身科：共 3 条"
    assert res["appliedSection"] == '["车身科"]'
    assert res["reloadsAfterRowClick"] == 1
    assert res["rollupPanels"] == 1
    # 「按状态」分页：行 = 状态（含其他状态且不可点击），色段 = 科室。
    assert res["byStatusRows"] == 3
    assert res["statusRowLabels"] == ["PE提交", "NCR管理员", "其他状态"]
    assert res["staticRows"] == 1
    assert res["statusFirstSegments"] == 2

    # 归集编辑器：编辑态、chips 增删走本地草稿，保存成功后退出编辑并刷新。
    assert res["editing"] is True
    assert res["chipsBefore"] == 1
    assert res["chipsAfter"] == 0
    assert res["draftAliases"] == []
    assert res["savedTargets"][0] == {"target": "车身科", "aliases": []}
    assert res["editingAfterSave"] is False
    assert res["reloadsAfterSave"] == 4

    # NCR明细：仅按科室计数板。
    assert res["countRows"] == 2
    assert res["countNums"] == ["共 2", "共 1"]


def test_board_and_rollup_source_uses_safe_dom_only() -> None:
    js = _read("web/static/app.js")

    for name in (
        "renderDepartmentStatusBoard",
        "renderSectionCountsBoard",
        "renderFormMatrixBars",
        "renderSectionRollupPanel",
    ):
        source = _slice(js, f"function {name}", "\nfunction ")
        assert "innerHTML" not in source

    css = _read("web/static/style.css")
    for marker in (
        ".dept-board-tab-list",
        ".form-matrix-seg-label",
        ".form-rollup-panel",
        ".form-rollup-chip",
        ".form-rollup-actions .btn",
    ):
        assert marker in css


@pytest.mark.parametrize("marker", [
    "sectionStageMatrix",
    "sectionCounts",
    "sectionRollup",
    "/api/project-status/section-rollup",
    "boardTab",
])
def test_board_payload_and_state_markers_present(marker: str) -> None:
    assert marker in _read("web/static/app.js")
