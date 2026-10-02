const assert = require('node:assert');

// In-memory minimal fake DOM for headless testing
class FakeNode {
  constructor(nodeName) {
    this.nodeName = (nodeName || '').toUpperCase();
    this.tagName = this.nodeName;
    this.childNodes = [];
    this.parentNode = null;
    this.attributes = {};
    this.style = {};
    this.listeners = {};
    this.disabled = false;
    this.className = '';
    this._text = '';
  }

  get children() {
    return this.childNodes.filter(n => n.nodeName !== '#TEXT');
  }

  get firstChild() {
    return this.childNodes.length > 0 ? this.childNodes[0] : null;
  }

  appendChild(child) {
    if (!child) return child;
    if (child.parentNode) {
      child.parentNode.removeChild(child);
    }
    child.parentNode = this;
    this.childNodes.push(child);
    return child;
  }

  removeChild(child) {
    const idx = this.childNodes.indexOf(child);
    if (idx !== -1) {
      this.childNodes.splice(idx, 1);
      child.parentNode = null;
    }
    return child;
  }

  addEventListener(type, listener) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(listener);
  }

  removeEventListener(type, listener) {
    if (!this.listeners[type]) return;
    this.listeners[type] = this.listeners[type].filter(cb => cb !== listener);
  }

  dispatchEvent(evt) {
    const type = typeof evt === 'string' ? evt : evt.type;
    const eventObj = typeof evt === 'object' ? evt : { type };
    if (this.listeners[type]) {
      for (const listener of this.listeners[type].slice()) {
        listener.call(this, eventObj);
      }
    }
  }

  click() {
    if (this.disabled) return;
    this.dispatchEvent({ type: 'click' });
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === 'class') this.className = String(value);
    if (name === 'disabled') this.disabled = true;
  }

  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null;
  }

  get textContent() {
    if (this.nodeName === '#TEXT') {
      return this._text;
    }
    return this.childNodes.map(c => c.textContent).join('');
  }

  set textContent(val) {
    this.childNodes = [];
    if (val !== undefined && val !== null && val !== '') {
      const textNode = new FakeNode('#TEXT');
      textNode._text = String(val);
      textNode.parentNode = this;
      this.childNodes.push(textNode);
    }
  }

  querySelector(selector) {
    const matches = this.querySelectorAll(selector);
    return matches.length > 0 ? matches[0] : null;
  }

  querySelectorAll(selector) {
    const results = [];
    function matchesSelector(node, sel) {
      if (!node || node.nodeName === '#TEXT') return false;
      sel = sel.trim();
      if (sel.startsWith('.')) {
        const cls = sel.slice(1);
        const classes = (node.className || '').split(/\s+/);
        return classes.includes(cls);
      }
      if (sel.startsWith('#')) {
        return node.getAttribute('id') === sel.slice(1);
      }
      return node.tagName.toLowerCase() === sel.toLowerCase();
    }
    function walk(curr) {
      for (const child of curr.childNodes) {
        if (matchesSelector(child, selector)) {
          results.push(child);
        }
        walk(child);
      }
    }
    walk(this);
    return results;
  }
}

// Setup environment before requiring module
global.document = {
  createElement: function (tagName) {
    return new FakeNode(tagName);
  }
};
global.window = global;

const EWOEnrichment = require('../web/static/ewo-enrichment.js');

function tick() {
  return new Promise(resolve => setImmediate(resolve));
}

async function runTests() {
  const sample32HexId = 'a1b2c3d4e5f60718293a4b5c6d7e8f90';

  // 1. Assert no requests on mount
  {
    const host = new FakeNode('div');
    let requestCount = 0;
    const request = async () => {
      requestCount++;
      return {};
    };

    const instance = EWOEnrichment.mount({
      host: host,
      request: request,
      getFilters: () => ({ status: 'Open' })
    });

    assert.strictEqual(requestCount, 0, 'Mount must not make any automatic network requests');

    const btnPrepare = host.querySelector('.ewo-btn-prepare');
    const btnRun = host.querySelector('.ewo-btn-run');
    const btnResume = host.querySelector('.ewo-btn-resume');
    const btnRefresh = host.querySelector('.ewo-btn-refresh');

    assert.ok(btnPrepare && !btnPrepare.disabled, 'btnPrepare should be enabled initially');
    assert.ok(btnRun && btnRun.disabled, 'btnRun should be disabled on mount');
    assert.ok(btnResume && btnResume.disabled, 'btnResume should be disabled on mount');
    assert.ok(btnRefresh && btnRefresh.disabled, 'btnRefresh should be disabled on mount');

    const metaSection = host.querySelector('.ewo-meta-section');
    assert.ok(metaSection.textContent.includes('未开始'), 'Initial state should be 未开始');

    const explanation = host.querySelector('.ewo-readonly-explanation');
    assert.ok(explanation && explanation.textContent.includes('只读增强展示'), 'Readonly explanation must be present');
    assert.ok(explanation.textContent.includes('不会向原系统反写'), 'Explains no write-back of owners/dates');

    instance.destroy();
    assert.strictEqual(host.childNodes.length, 0, 'destroy removes own panel from host');
  }

  // 2. prepare doesn't generate
  {
    const host = new FakeNode('div');
    const calls = [];
    const request = async (path, payload) => {
      calls.push({ path, payload });
      return {
        id: sample32HexId,
        state: 'queued',
        baseTime: 1700000000,
        enhancementTime: null,
        counts: {
          base_count: 10,
          export_count: 10,
          matched_count: 8,
          blank_number_count: 1,
          unmatched_count: 1,
          ambiguous_count: 0
        },
        associations: []
      };
    };

    const instance = EWOEnrichment.mount({
      host: host,
      request: request,
      getFilters: () => ({ dept: 'Eng', active: true })
    });

    const btnPrepare = host.querySelector('.ewo-btn-prepare');
    btnPrepare.click();
    await tick();

    assert.strictEqual(calls.length, 1, 'Prepare should make exactly one request');
    assert.strictEqual(calls[0].path, '/api/aras/ewo/enrichment/jobs', 'Prepare calls create job endpoint');
    assert.deepStrictEqual(calls[0].payload, { filters: { dept: 'Eng', active: true } }, 'Prepare passes filters');

    // Verify it did not call /run or generate
    assert.ok(!calls.some(c => c.path.includes('/run')), 'Prepare must not call /run or generate');

    const btnRun = host.querySelector('.ewo-btn-run');
    const btnResume = host.querySelector('.ewo-btn-resume');
    const btnRefresh = host.querySelector('.ewo-btn-refresh');

    assert.strictEqual(btnRun.disabled, false, 'btnRun enabled when state is queued');
    assert.strictEqual(btnResume.disabled, true, 'btnResume disabled when state is queued');
    assert.strictEqual(btnRefresh.disabled, false, 'btnRefresh enabled with valid job');

    instance.destroy();
  }

  // 3. Explicit run only valid queued / generated
  {
    const host = new FakeNode('div');
    const calls = [];
    let jobState = 'queued';

    const request = async (path, payload) => {
      calls.push({ path, payload });
      return {
        id: sample32HexId,
        state: jobState,
        baseTime: 1700000000,
        enhancementTime: 1700000100,
        counts: {
          base_count: 2,
          export_count: 2,
          matched_count: 2,
          blank_number_count: 0,
          unmatched_count: 0,
          ambiguous_count: 0
        },
        associations: []
      };
    };

    const instance = EWOEnrichment.mount({ host, request });

    // Step A: Prepare to get queued job
    host.querySelector('.ewo-btn-prepare').click();
    await tick();

    const btnRun = host.querySelector('.ewo-btn-run');
    const btnResume = host.querySelector('.ewo-btn-resume');

    assert.strictEqual(btnRun.disabled, false, 'btnRun enabled for queued');
    assert.strictEqual(btnResume.disabled, true, 'btnResume disabled for queued');

    // Step B: Trigger explicit run from queued
    calls.length = 0;
    btnRun.click();
    await tick();

    assert.strictEqual(calls.length, 1, 'Run invoked');
    assert.strictEqual(calls[0].path, `/api/aras/ewo/enrichment/jobs/${sample32HexId}/run`);
    assert.deepStrictEqual(calls[0].payload, {});

    // Step C: Switch state to 'generated'
    jobState = 'generated';
    calls.length = 0;
    host.querySelector('.ewo-btn-refresh').click();
    await tick();

    assert.strictEqual(btnRun.disabled, true, 'btnRun disabled for generated');
    assert.strictEqual(btnResume.disabled, false, 'btnResume enabled for generated');

    // Step D: Trigger resume from generated
    calls.length = 0;
    btnResume.click();
    await tick();

    assert.strictEqual(calls.length, 1, 'Resume invoked');
    assert.strictEqual(calls[0].path, `/api/aras/ewo/enrichment/jobs/${sample32HexId}/run`);
    assert.deepStrictEqual(calls[0].payload, {});

    // Step E: Switch state to 'downloading'
    jobState = 'downloading';
    calls.length = 0;
    host.querySelector('.ewo-btn-refresh').click();
    await tick();

    assert.strictEqual(btnRun.disabled, true, 'btnRun disabled for downloading');
    assert.strictEqual(btnResume.disabled, true, 'btnResume disabled for downloading');

    calls.length = 0;
    btnRun.click();
    btnResume.click();
    await tick();
    assert.strictEqual(calls.length, 0, 'No run request triggered in other states');

    instance.destroy();
  }

  // 4. Unknown state: no run
  {
    const host = new FakeNode('div');
    const calls = [];

    const request = async (path, payload) => {
      calls.push({ path, payload });
      return {
        id: sample32HexId,
        state: 'generation_unknown',
        baseTime: 1700000000,
        enhancementTime: null,
        counts: null,
        associations: null
      };
    };

    const instance = EWOEnrichment.mount({ host, request });
    host.querySelector('.ewo-btn-prepare').click();
    await tick();

    const btnRun = host.querySelector('.ewo-btn-run');
    const btnResume = host.querySelector('.ewo-btn-resume');

    assert.strictEqual(btnRun.disabled, true, 'btnRun must be disabled for generation_unknown');
    assert.strictEqual(btnResume.disabled, true, 'btnResume must be disabled for generation_unknown');

    calls.length = 0;
    btnRun.click();
    btnResume.click();
    await tick();
    assert.strictEqual(calls.length, 0, 'Must never allow run retry on generation_unknown');

    const unknownNotice = host.querySelector('.ewo-unknown-notice');
    assert.strictEqual(unknownNotice.style.display, 'block', 'Unknown notice banner displayed');
    assert.ok(unknownNotice.textContent.includes('生成状态未知'), 'Mentions unknown state');
    assert.ok(unknownNotice.textContent.includes('原系统核对'), 'Instructs to check original system');

    instance.destroy();
  }

  // 5. Rejection preserves data
  {
    const host = new FakeNode('div');
    let shouldFail = false;

    const request = async (path, payload) => {
      if (shouldFail) {
        throw new Error('Connection timeout 504');
      }
      return {
        id: sample32HexId,
        state: 'queued',
        baseTime: 1700000000,
        enhancementTime: 1700000500,
        counts: {
          base_count: 88,
          export_count: 88,
          matched_count: 80,
          blank_number_count: 2,
          unmatched_count: 6,
          ambiguous_count: 0
        },
        associations: [
          {
            row_index: 1,
            status: 'Approved',
            business_number: 'EWO-2026-001',
            source_item_id: 'ITEM-01',
            fields: { '责任工程师名称': '张三', '要求完成时间': '2026-10-01' }
          }
        ]
      };
    };

    const instance = EWOEnrichment.mount({ host, request });

    // Initial success
    host.querySelector('.ewo-btn-prepare').click();
    await tick();

    const baseTimeEl = host.querySelector('.ewo-meta-section');
    assert.ok(baseTimeEl.textContent.includes('2023-11-14T22:13:20.000Z'), 'Formatted ISO timestamp shown');

    const rowBefore = host.querySelector('.ewo-row');
    assert.ok(rowBefore && rowBefore.textContent.includes('EWO-2026-001'), 'Row rendered');

    // Subsequent failure
    shouldFail = true;
    host.querySelector('.ewo-btn-refresh').click();
    await tick();

    // Data retained
    const staleNotice = host.querySelector('.ewo-stale-notice');
    assert.strictEqual(staleNotice.style.display, 'block', 'Stale warning notice displayed');
    assert.ok(staleNotice.textContent.includes('Connection timeout 504'), 'Shows failure reason');

    const rowAfter = host.querySelector('.ewo-row');
    assert.ok(rowAfter && rowAfter.textContent.includes('EWO-2026-001'), 'Row data retained');
    assert.ok(host.textContent.includes('88'), 'Counts retained');

    instance.destroy();
  }

  // 6. Malicious field text treated literally
  {
    const host = new FakeNode('div');
    const xssPayloads = {
      bn: '<script>alert("bn")</script>',
      st: '<img src=x onerror=alert("st")>',
      eng: '<b onmouseover="alert(\'eng\')">李四</b>',
      date: '<iframe src="evil.html"></iframe>'
    };

    const request = async () => ({
      id: sample32HexId,
      state: 'queued',
      baseTime: 1700000000,
      enhancementTime: null,
      counts: { base_count: 1, export_count: 1, matched_count: 1, blank_number_count: 0, unmatched_count: 0, ambiguous_count: 0 },
      associations: [
        {
          row_index: 1,
          status: xssPayloads.st,
          business_number: xssPayloads.bn,
          source_item_id: 'ITEM-X',
          fields: {
            '责任工程师名称': xssPayloads.eng,
            '要求完成时间': xssPayloads.date
          }
        }
      ]
    });

    const instance = EWOEnrichment.mount({ host, request });
    host.querySelector('.ewo-btn-prepare').click();
    await tick();

    const row = host.querySelector('.ewo-row');
    assert.ok(row, 'Row should exist');

    const colBn = row.querySelector('.col-business-number');
    const colSt = row.querySelector('.col-status');
    const colEng = row.querySelector('.col-engineer');
    const colDate = row.querySelector('.col-due-date');

    assert.strictEqual(colBn.textContent, xssPayloads.bn, 'Treated literally for business number');
    assert.strictEqual(colSt.textContent, xssPayloads.st, 'Treated literally for status');
    assert.strictEqual(colEng.textContent, xssPayloads.eng, 'Treated literally for engineer');
    assert.strictEqual(colDate.textContent, xssPayloads.date, 'Treated literally for due date');

    // Verify no malicious elements created in DOM
    assert.strictEqual(row.querySelectorAll('script').length, 0, 'No script element in DOM');
    assert.strictEqual(row.querySelectorAll('img').length, 0, 'No img element in DOM');
    assert.strictEqual(row.querySelectorAll('b').length, 0, 'No b element in DOM');
    assert.strictEqual(row.querySelectorAll('iframe').length, 0, 'No iframe element in DOM');

    instance.destroy();
  }

  // 7. Busy duplicate click blocked
  {
    const host = new FakeNode('div');
    let callCount = 0;
    let deferredResolve;

    const request = () => {
      callCount++;
      return new Promise(resolve => {
        deferredResolve = resolve;
      });
    };

    const instance = EWOEnrichment.mount({ host, request });
    const btnPrepare = host.querySelector('.ewo-btn-prepare');
    const btnRun = host.querySelector('.ewo-btn-run');
    const btnResume = host.querySelector('.ewo-btn-resume');
    const btnRefresh = host.querySelector('.ewo-btn-refresh');

    btnPrepare.click();
    assert.strictEqual(callCount, 1, 'First click triggers request');

    // Controls must be disabled while busy
    assert.strictEqual(btnPrepare.disabled, true, 'btnPrepare disabled when busy');
    assert.strictEqual(btnRun.disabled, true, 'btnRun disabled when busy');
    assert.strictEqual(btnResume.disabled, true, 'btnResume disabled when busy');
    assert.strictEqual(btnRefresh.disabled, true, 'btnRefresh disabled when busy');

    // Duplicate clicks while busy
    btnPrepare.click();
    btnRun.click();
    btnRefresh.click();
    assert.strictEqual(callCount, 1, 'Duplicate clicks during busy are ignored');

    deferredResolve({
      id: sample32HexId,
      state: 'queued',
      baseTime: 1700000000,
      enhancementTime: null,
      counts: null,
      associations: []
    });
    await tick();

    assert.strictEqual(btnPrepare.disabled, false, 'btnPrepare re-enabled after busy completes');
    assert.strictEqual(btnRun.disabled, false, 'btnRun enabled for queued job');

    instance.destroy();
  }

  // 8. Destroy late response safe
  {
    const host = new FakeNode('div');
    let deferredResolve;

    const request = () => {
      return new Promise(resolve => {
        deferredResolve = resolve;
      });
    };

    const instance = EWOEnrichment.mount({ host, request });
    const btnPrepare = host.querySelector('.ewo-btn-prepare');
    btnPrepare.click();

    // Destroy component while request is in-flight
    instance.destroy();
    assert.strictEqual(host.childNodes.length, 0, 'Panel removed from host');

    // Now late response resolves
    deferredResolve({
      id: sample32HexId,
      state: 'queued',
      baseTime: 1700000000,
      enhancementTime: null,
      counts: { base_count: 5 },
      associations: [{ row_index: 1, business_number: 'TEST', status: 'OK', fields: {} }]
    });

    await tick();

    // Confirm no errors thrown, and host remains empty
    assert.strictEqual(host.childNodes.length, 0, 'Host remains empty after late response');
  }

  // 9. First 100 rows limit and label
  {
    const host = new FakeNode('div');
    const items = [];
    for (let i = 1; i <= 135; i++) {
      items.push({
        row_index: i,
        status: 'Open',
        business_number: 'EWO-' + i,
        source_item_id: 'ID-' + i,
        fields: { '责任工程师名称': '工' + i, '要求完成时间': '2026-12-31' }
      });
    }

    const request = async () => ({
      id: sample32HexId,
      state: 'queued',
      baseTime: 1700000000,
      enhancementTime: null,
      counts: { base_count: 135, export_count: 135, matched_count: 135, blank_number_count: 0, unmatched_count: 0, ambiguous_count: 0 },
      associations: items
    });

    const instance = EWOEnrichment.mount({ host, request });
    host.querySelector('.ewo-btn-prepare').click();
    await tick();

    const limitLabel = host.querySelector('.ewo-table-limit-label');
    assert.strictEqual(limitLabel.textContent, '显示记录：前 100 条（共 135 条）');

    const rows = host.querySelectorAll('.ewo-row');
    assert.strictEqual(rows.length, 100, 'Exactly 100 rows rendered');

    instance.destroy();
  }

  // 10. Invalid job ID validation before use in URL
  {
    const host = new FakeNode('div');
    const request = async () => ({
      id: 'malicious/../path',
      state: 'queued'
    });

    const instance = EWOEnrichment.mount({ host, request });
    host.querySelector('.ewo-btn-prepare').click();
    await tick();

    const btnRun = host.querySelector('.ewo-btn-run');
    const btnRefresh = host.querySelector('.ewo-btn-refresh');

    assert.strictEqual(btnRun.disabled, true, 'Run button remains disabled for invalid job ID');
    assert.strictEqual(btnRefresh.disabled, true, 'Refresh button remains disabled for invalid job ID');

    instance.destroy();
  }

  // Restore is explicit and cannot trigger generation. Invalid later IDs must not mix with old state.
  {
    const host = new FakeNode('div');
    const calls = [];
    const request = async (path, payload) => {
      calls.push({ path, payload });
      return calls.length === 1
        ? { id: 'a'.repeat(32), state: 'parsed', baseTime: 100 }
        : { id: '../invalid', state: 'queued' };
    };
    const instance = EWOEnrichment.mount({ host, request, getFilters: () => ({ ewo_no: 'E-1' }) });
    host.querySelector('.ewo-btn-restore').click();
    await tick();
    assert.strictEqual(calls[0].path, '/api/aras/ewo/enrichment/jobs/restore');
    assert.deepStrictEqual(calls[0].payload, { filters: { ewo_no: 'E-1' } });
    host.querySelector('.ewo-btn-prepare').click();
    await tick();
    assert.strictEqual(host.querySelector('.ewo-btn-run').disabled, true);
    assert.ok(host.querySelector('.ewo-meta-section').textContent.includes('parsed'));
    assert.strictEqual(calls.length, 2);
    instance.destroy();
  }

  console.log('All EWO Enrichment UI tests passed successfully.');
}

runTests().catch(err => {
  console.error('Test failed:', err);
  process.exit(1);
});
