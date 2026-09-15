from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


def run_node_vm_test(js_body: str) -> dict:
    """Run a test snippet in Node.js with small DOM stubs and return parsed JSON."""
    test_runner_script = f"""
const vm = require('vm');
const fs = require('fs');
const path = require('path');

// Small DOM stubs
class DOMTokenList {{
  constructor(el) {{ this._el = el; this._set = new Set(); }}
  add(...tokens) {{ tokens.forEach(t => this._set.add(t)); this._sync(); }}
  remove(...tokens) {{ tokens.forEach(t => this._set.delete(t)); this._sync(); }}
  toggle(token, force) {{
    const res = force !== undefined ? Boolean(force) : !this._set.has(token);
    if (res) this._set.add(token); else this._set.delete(token);
    this._sync();
    return res;
  }}
  contains(token) {{ return this._set.has(token); }}
  _sync() {{ this._el.className = Array.from(this._set).join(' '); }}
}}

class Element {{
  constructor(tagName) {{
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.dataset = {{}};
    this.attributes = {{}};
    this._className = '';
    this.classList = new DOMTokenList(this);
    this._listeners = {{}};
    this.hidden = false;
    this.value = '';
    this._textContent = '';
    this._innerHTML = '';
    this.isConnected = true;
    this.disabled = false;
    this.id = '';
    this.name = '';
    this.type = '';
    this.options = [];
    this.selectedIndex = 0;
  }}

  get className() {{ return this._className; }}
  set className(val) {{
    this._className = String(val || '');
    this.classList._set = new Set(this._className.split(/\\s+/).filter(Boolean));
  }}

  get textContent() {{ return this._textContent + this.children.map(c => c.textContent).join(''); }}
  set textContent(val) {{
    this._textContent = String(val === null || val === undefined ? '' : val);
    this.children = [];
  }}

  get innerHTML() {{ return this._innerHTML; }}
  set innerHTML(val) {{
    this._innerHTML = String(val || '');
    this.children = [];
    // Parse only form controls from static templates, sufficient for these tests.
    const controlRe = /<(input|textarea|select|button)\\b([^>]*)>/g;
    for (const match of this._innerHTML.matchAll(controlRe)) {{
      const child = new Element(match[1]);
      for (const attr of match[2].matchAll(/([\\w-]+)="([^"]*)"/g)) {{
        child[attr[1]] = attr[2]; child.setAttribute(attr[1], attr[2]);
      }}
      this.appendChild(child);
    }}
    if (!this._innerHTML) {{
      this._textContent = '';
      this.options = [];
    }}
  }}

  appendChild(child) {{
    if (!child) return child;
    child.parentNode = this;
    this.children.push(child);
    if (this.tagName === 'SELECT' && child.tagName === 'OPTION') {{
      this.options.push(child);
      if (this.options.length === 1) {{
        this.selectedIndex = 0;
        this.value = child.value;
      }}
    }}
    return child;
  }}

  append(...items) {{
    items.forEach(item => {{
      if (item instanceof Element) this.appendChild(item);
    }});
  }}

  prepend(child) {{
    child.parentNode = this;
    this.children.unshift(child);
  }}

  insertBefore(newNode, refNode) {{
    newNode.parentNode = this;
    const idx = this.children.indexOf(refNode);
    if (idx === -1) this.children.push(newNode);
    else this.children.splice(idx, 0, newNode);
    return newNode;
  }}

  addEventListener(event, fn) {{
    if (!this._listeners[event]) this._listeners[event] = [];
    this._listeners[event].push(fn);
  }}

  dispatchEvent(event) {{
    const type = typeof event === 'string' ? event : (event.type || '');
    const listeners = this._listeners[type] || [];
    listeners.forEach(fn => fn(event));
  }}

  querySelector(selector) {{
    const results = this.querySelectorAll(selector);
    return results.length ? results[0] : null;
  }}

  querySelectorAll(selector) {{
    const matches = [];
    const walk = (node) => {{
      if (node !== this && matchesSelector(node, selector)) {{
        matches.push(node);
      }}
      (node.children || []).forEach(walk);
    }};
    walk(this);
    return matches;
  }}

  setAttribute(k, v) {{ this.attributes[k] = String(v); }}
  getAttribute(k) {{ return this.attributes[k] !== undefined ? this.attributes[k] : null; }}
  removeAttribute(k) {{ delete this.attributes[k]; }}
  checkValidity() {{ return true; }}
  reportValidity() {{ return true; }}
}}

function matchesSelector(el, sel) {{
  if (sel.startsWith('#')) return el.id === sel.slice(1);
  if (sel.startsWith('.')) return el.classList.contains(sel.slice(1));
  const attrMatch = sel.match(/^\\[([a-zA-Z0-9_-]+)(?:=([^\\]]+))?\\]$/);
  if (attrMatch) {{
    const name = attrMatch[1];
    const rawVal = attrMatch[2];
    const val = rawVal ? rawVal.replace(/^["']|["']$/g, '') : null;
    if (name in el) return val === null ? Boolean(el[name]) : String(el[name]) === val;
    if (name in el.attributes) return val === null ? true : el.attributes[name] === val;
    if (name.startsWith('data-')) {{
      const dkey = name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      return val === null ? dkey in el.dataset : el.dataset[dkey] === val;
    }}
    return false;
  }}
  return el.tagName.toLowerCase() === sel.toLowerCase();
}}

class DocumentStub {{
  constructor() {{
    this.body = new Element('body');
    this._elementsById = {{}};
  }}

  createElement(tagName) {{
    return new Element(tagName);
  }}

  getElementById(id) {{
    return this.body.querySelector('#' + id);
  }}

  querySelector(sel) {{
    return this.body.querySelector(sel);
  }}

  querySelectorAll(sel) {{
    return this.body.querySelectorAll(sel);
  }}
}}

const doc = new DocumentStub();
global.document = doc;
global.window = {{
  location: {{ hash: '' }},
  addEventListener: () => {{}},
  document: doc,
  localStorage: {{ getItem: () => null, setItem: () => {{}} }},
}};

// Load app.js in sandbox
const appPath = path.resolve(process.cwd(), 'web/static/app.js');
doc.addEventListener = () => {{}};
const recent = doc.createElement('div'); recent.id = 'deliverable-recent'; doc.body.appendChild(recent);
const context = vm.createContext({{document: doc, window: global.window, console, URL, setTimeout, clearTimeout,
  localStorage: global.window.localStorage}});
vm.runInContext(fs.readFileSync(appPath, 'utf8'), context);
const app = vm.runInContext('({{buildDeliverableForm, collectDeliverablePayload, loadTdcSorProjectOptions, renderDeliverableResult, runDeliverableOperation, renderRows, formatDeliverableFilterSummary, getOrCreateDeliverablePreviewContext, deliverablePreviewStates}})', context);
for (const key of ['fetch', 'fetchBlobDownload']) {{
  Object.defineProperty(global, key, {{configurable: true, set(value) {{context[key] = value;}}}});
}}

async function run() {{
  {js_body}
}}

run().then(res => {{
  console.log(JSON.stringify(res || {{ ok: true }}));
}}).catch(err => {{
  console.error(err);
  process.exit(1);
}});
"""
    proc = subprocess.run(
        ["node", "-e", test_runner_script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        cwd=Path(__file__).resolve().parent.parent,
    )
    if proc.returncode != 0:
        raise AssertionError(f"Node execution failed (code {proc.returncode}):\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return json.loads(proc.stdout.strip()) if proc.stdout.strip() else {}


def test_sor_form_build_and_manual_edit_clears_selected_id() -> None:
    """Selecting a project populates visible text and hidden ID; manual text change clears ID and select."""
    js_test = """
    const item = {
      id: "tdc-sor",
      name: "TDC 方案/技术要求（SOR）流程报表",
      availability: "available",
      fields: [
        { name: "car_type_project", label: "车型项目" },
        { name: "applicant", label: "申请人" }
      ]
    };

    const form = app.buildDeliverableForm(item);
    doc.body.appendChild(form);

    const input = form.querySelector('[name="car_type_project"]');
    const hiddenId = form.querySelector('[name="car_type_project_id"]');
    const select = form.querySelector('#tdc-car-type-project-options');
    const loadBtn = form.querySelector('#tdc-load-car-type-projects');

    if (!input || !hiddenId || !select || !loadBtn) {
      throw new Error("Missing expected SOR form controls");
    }

    // Simulate options population from loaded projects
    const opt = doc.createElement('option');
    opt.value = 'proj-123';
    opt.dataset.projectNo = 'E262S';
    opt.dataset.projectName = 'E262S Project';
    opt.textContent = 'E262S — E262S Project';
    select.appendChild(opt);
    select.selectedIndex = select.options.length - 1;
    select.value = 'proj-123';
    select.dispatchEvent({ type: 'change' });

    // Should populate visible text and hidden ID
    const populatedText = input.value;
    const populatedId = hiddenId.value;

    // Simulate manual user edit
    input.value = 'E262S-Manual';
    input.dispatchEvent({ type: 'input' });

    const idAfterManualEdit = hiddenId.value;
    const selectAfterManualEdit = select.value;

    return {
      populatedText,
      populatedId,
      idAfterManualEdit,
      selectAfterManualEdit
    };
    """
    res = run_node_vm_test(js_test)
    assert res["populatedText"] == "E262S"
    assert res["populatedId"] == "proj-123"
    assert res["idAfterManualEdit"] == ""
    assert res["selectAfterManualEdit"] == ""


def test_sor_project_id_included_in_payload() -> None:
    """Selected car_type_project_id is included in filters for query, crawl_all, and export."""
    js_test = """
    const item = {
      id: "tdc-sor",
      name: "TDC 方案/技术要求（SOR）流程报表",
      availability: "available",
      fields: [
        { name: "car_type_project", label: "车型项目" },
        { name: "applicant", label: "申请人" }
      ]
    };

    const form = app.buildDeliverableForm(item);
    form.id = "deliverable-form";
    doc.body.appendChild(form);

    const input = form.querySelector('[name="car_type_project"]');
    const hiddenId = form.querySelector('[name="car_type_project_id"]');

    input.value = "E262S";
    hiddenId.value = "proj-123";

    const queryPayload = app.collectDeliverablePayload(item, "query");
    const crawlPayload = app.collectDeliverablePayload(item, "crawl_all");
    const exportPayload = app.collectDeliverablePayload(item, "export");

    // Clear ID and verify it is omitted
    hiddenId.value = "";
    const clearedPayload = app.collectDeliverablePayload(item, "query");

    return {
      queryFilters: queryPayload.filters,
      crawlFilters: crawlPayload.filters,
      exportFilters: exportPayload.filters,
      clearedFilters: clearedPayload.filters
    };
    """
    res = run_node_vm_test(js_test)
    assert res["queryFilters"]["car_type_project"] == "E262S"
    assert res["queryFilters"]["car_type_project_id"] == "proj-123"
    assert res["crawlFilters"]["car_type_project_id"] == "proj-123"
    assert res["exportFilters"]["car_type_project_id"] == "proj-123"
    assert "car_type_project_id" not in res["clearedFilters"]


def test_sor_async_obsolete_project_load_cannot_apply() -> None:
    """Stale project responses cannot apply when connection details changed or sequence superseded."""
    js_test = """
    const item = {
      id: "tdc-sor",
      name: "TDC 方案/技术要求（SOR）流程报表",
      availability: "available",
      fields: [
        { name: "car_type_project", label: "车型项目" }
      ]
    };

    const form = app.buildDeliverableForm(item);
    doc.body.appendChild(form);

    const select = form.querySelector('#tdc-car-type-project-options');
    const baseUrlInput = form.querySelector('#tdc-base-url');

    let fetchCallCount = 0;
    let pendingResolve;
    global.fetch = () => {
      fetchCallCount++;
      return new Promise((resolve) => {
        pendingResolve = () => resolve({
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              projects: [
                { id: "old-proj", projectNo: "OLD", label: "OLD Project" }
              ]
            }
          })
        });
      });
    };

    // Trigger initial load
    const loadPromise = app.loadTdcSorProjectOptions(form);

    // User edits base URL while request is in flight
    baseUrlInput.value = "https://new-tdc.example.com";
    baseUrlInput.dispatchEvent({ type: 'input' });

    // Now request 1 finishes
    pendingResolve();
    await loadPromise;

    // Check options: the stale response must NOT have populated 'old-proj'
    const hasOldProj = select.options.some(o => o.value === "old-proj");

    return {
      fetchCallCount,
      hasOldProj,
      currentSelectOptions: select.options.map(o => o.textContent)
    };
    """
    res = run_node_vm_test(js_test)
    assert res["fetchCallCount"] == 1
    assert res["hasOldProj"] is False


def test_sor_failed_export_retains_prior_query_context() -> None:
    """When an export fails, previous query preview is retained, context reflects captured filters, and kind shows export failed."""
    js_test = """
    // Build workbench structure
    const panel = doc.createElement('div');
    panel.id = 'deliverable-result-panel';
    panel.hidden = true;

    const kind = doc.createElement('span');
    kind.id = 'deliverable-result-kind';
    kind.textContent = '就绪';

    const err = doc.createElement('div');
    err.id = 'deliverable-error';
    err.hidden = true;

    const result = doc.createElement('div');
    result.id = 'deliverable-result';

    const status = doc.createElement('span');
    status.id = 'deliverable-status';

    panel.append(kind, err, result);
    doc.body.append(panel, status);

    const item = {
      id: "tdc-sor",
      name: "TDC 方案/技术要求（SOR）流程报表",
      availability: "available",
      fields: [
        { name: "car_type_project", label: "车型项目" }
      ]
    };

    const form = app.buildDeliverableForm(item);
    form.id = "deliverable-form";
    doc.body.appendChild(form);

    // Set initial filter and run successful query
    const input = form.querySelector('[name="car_type_project"]');
    input.value = "E262S-Initial";

    global.fetch = async (url) => {
      return {
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            report_type: "sor",
            rows: [["WF-1", "E262S", "Release", "SOR-1", "A", "Seat", "P1", "Seat Part", "User", "Dept", "Sec", "2026-01-01", "Review", "Done", "Bob"]]
          }
        })
      };
    };

    await app.runDeliverableOperation(item, "query");

    const queryKind = kind.textContent;
    const previewContext = doc.getElementById('deliverable-preview-context');
    const queryContextText = previewContext ? previewContext.textContent : "";
    const hadTableAfterQuery = result.querySelector('table') !== null;

    // Now user changes input to a new value
    input.value = "E262S-NewlyEdited";

    // Export operation fails
    global.fetchBlobDownload = async () => {
      throw new Error("Export download network failed");
    };

    await app.runDeliverableOperation(item, "export");

    const exportFailKind = kind.textContent;
    const exportStatus = status.textContent;
    const retainedTable = result.querySelector('table') !== null;
    const retainedContextText = previewContext ? previewContext.textContent : "";

    return {
      queryKind,
      queryContextText,
      hadTableAfterQuery,
      exportFailKind,
      exportStatus,
      retainedTable,
      retainedContextText
    };
    """
    res = run_node_vm_test(js_test)
    assert "查询预览" in res["queryKind"]
    assert "E262S-Initial" in res["queryContextText"]
    assert res["hadTableAfterQuery"] is True
    # Export failure explicitly says export failed
    assert "导出失败" in res["exportFailKind"]
    assert "导出失败" in res["exportStatus"]
    # Previous table retained
    assert res["retainedTable"] is True
    # Does NOT use newly edited filters in prior preview context
    assert "E262S-Initial" in res["retainedContextText"]
    assert "E262S-NewlyEdited" not in res["retainedContextText"]
    assert "保留上次" in res["retainedContextText"]


def test_sor_successful_export_clears_prior_preview_context() -> None:
    """Successful export clears previous query preview context."""
    js_test = """
    const panel = doc.createElement('div');
    panel.id = 'deliverable-result-panel';
    const kind = doc.createElement('span');
    kind.id = 'deliverable-result-kind';
    const err = doc.createElement('div');
    err.id = 'deliverable-error';
    const result = doc.createElement('div');
    result.id = 'deliverable-result';
    const status = doc.createElement('span');
    status.id = 'deliverable-status';

    panel.append(kind, err, result);
    doc.body.append(panel, status);

    const item = {
      id: "tdc-sor",
      name: "TDC 方案/技术要求（SOR）流程报表",
      availability: "available",
      fields: [{ name: "car_type_project", label: "车型项目" }]
    };

    const form = app.buildDeliverableForm(item);
    form.id = "deliverable-form";
    doc.body.appendChild(form);

    // Run query first
    global.fetch = async () => ({
      ok: true,
      json: async () => ({
        ok: true,
        data: { report_type: "sor", rows: [["1", "2"]] }
      })
    });

    await app.runDeliverableOperation(item, "query");

    const previewContext = doc.getElementById('deliverable-preview-context');
    const wasVisible = previewContext && !previewContext.hidden;

    // Run successful export
    global.fetchBlobDownload = async () => ({ fileName: "tdc_sor.xlsx" });
    await app.runDeliverableOperation(item, "export");

    const isHiddenAfterExport = previewContext ? previewContext.hidden : true;
    const resultKind = kind.textContent;

    return {
      wasVisible,
      isHiddenAfterExport,
      resultKind,
      resultText: result.textContent
    };
    """
    res = run_node_vm_test(js_test)
    assert res["wasVisible"] is True
    assert res["isHiddenAfterExport"] is True
    assert "导出 XLSX" in res["resultKind"]
    assert "已下载：tdc_sor.xlsx" in res["resultText"]


def test_sor_result_table_css_and_markup_contracts() -> None:
    """Verify sor-result-table class is applied only to SOR tables and CSS satisfies geometry constraints."""
    css_text = Path("web/static/style.css").read_text(encoding="utf-8-sig")

    # Verify sor-result-table rules
    assert ".sor-result-table" in css_text
    min_width_match = re.search(r"\.sor-result-table\s*\{[^}]*min-width:\s*(\d+)px", css_text)
    assert min_width_match, "Must define min-width on .sor-result-table"
    min_width = int(min_width_match.group(1))
    assert 1900 <= min_width <= 2200, f"SOR table min-width {min_width} should be between 1900 and 2200px"

    # Verify nowrap on identifier / date columns
    assert "white-space: nowrap" in css_text
    assert ".deliverable-preview-context" in css_text

    # Verify renderRows assigns sor-result-table only on mode=tdc-sor
    js_test = """
    const sorWrap = app.renderRows({ rows: [["A", "B"]] }, [], "tdc-sor");
    const sorTable = sorWrap.querySelector('table');

    const dmWrap = app.renderRows({ rows: [["A", "B"]] }, [], "tdc-data-model");
    const dmTable = dmWrap.querySelector('table');

    const ewoWrap = app.renderRows({ rows: [["A", "B"]] }, [], "ewo");
    const ewoTable = ewoWrap.querySelector('table');

    return {
      sorHasClass: sorTable.classList.contains('sor-result-table'),
      dmHasClass: dmTable.classList.contains('sor-result-table'),
      ewoHasClass: ewoTable.classList.contains('sor-result-table')
    };
    """
    res = run_node_vm_test(js_test)
    assert res["sorHasClass"] is True
    assert res["dmHasClass"] is False
    assert res["ewoHasClass"] is False


def test_reload_skips_missing_ids_and_clears_previous_selection() -> None:
    res = run_node_vm_test("""
    const form = app.buildDeliverableForm({id:'tdc-sor', availability:'available',
      fields:[{name:'car_type_project'}]});
    doc.body.appendChild(form);
    const hidden = form.querySelector('[name="car_type_project_id"]');
    hidden.value = 'old-id';
    global.fetch = async () => ({ok:true, json:async () => ({ok:true,
      data:{projects:[{projectNo:'MISSING-ID'},{id:'valid',projectNo:'VALID'}]}})});
    await app.loadTdcSorProjectOptions(form);
    return {id:hidden.value, options:form.querySelector('#tdc-car-type-project-options').options.map(o=>o.value)};
    """)
    assert res == {'id': '', 'options': ['', 'valid']}


def test_older_lookup_does_not_unlock_newer_pending_request() -> None:
    res = run_node_vm_test("""
    const form = app.buildDeliverableForm({id:'tdc-sor', availability:'available',
      fields:[{name:'car_type_project'}]});
    doc.body.appendChild(form);
    const pending = [];
    global.fetch = () => new Promise(resolve=>pending.push(resolve));
    const old = app.loadTdcSorProjectOptions(form);
    const recent = app.loadTdcSorProjectOptions(form);
    pending[0]({ok:true,json:async()=>({ok:true,data:{projects:[]}})});
    await old;
    const stillDisabled = form.querySelector('#tdc-load-car-type-projects').disabled;
    pending[1]({ok:true,json:async()=>({ok:true,data:{projects:[]}})});
    await recent;
    return {stillDisabled, finallyEnabled:!form.querySelector('#tdc-load-car-type-projects').disabled};
    """)
    assert res == {'stillDisabled': True, 'finallyEnabled': True}


def test_project_with_id_only_does_not_submit_id_as_display_name() -> None:
    res = run_node_vm_test("""
    const form = app.buildDeliverableForm({id:'tdc-sor',availability:'available',fields:[{name:'car_type_project'}]});
    doc.body.appendChild(form);
    const select = form.querySelector('#tdc-car-type-project-options');
    const option = doc.createElement('option'); option.value='id-only'; option.textContent='id-only';
    select.appendChild(option); select.selectedIndex=1;
    select.dispatchEvent({type:'change'});
    return app.collectDeliverablePayload({id:'tdc-sor',fields:[{name:'car_type_project'}]},'export').filters;
    """)
    assert res == {'car_type_project_id': 'id-only'}
