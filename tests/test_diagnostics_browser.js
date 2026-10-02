const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

(async () => {
  const calls = [];
  const response = { status: 200 };
  let active = false;
  const listeners = {};
  const document = {
    readyState: 'loading',
    addEventListener: (type, fn) => { listeners[type] = fn; },
    getElementById: () => null,
  };
  const window = {
    location: { origin: 'http://localhost:5000' },
    crypto: require('node:crypto').webcrypto,
    addEventListener: (type, fn) => { listeners[type] = fn; },
    fetch: async (input, options) => {
      const url = typeof input === 'string' ? input : input.url;
      calls.push({ url, options });
      if (url === '/api/diagnostics') return { ok: true, json: async () => ({ active, recordings: [] }) };
      if (url.includes('failure')) throw new Error('SYNTHETIC_SECRET');
      return response;
    },
  };
  const timers = [];
  vm.runInNewContext(fs.readFileSync('web/static/diagnostics.js', 'utf8'), {
    window, document, Headers, Request, URL, Date, console,
    setInterval: fn => { timers.push(fn); }, setTimeout,
  });
  await timers[0]();
  await window.fetch('/api/test', { method: 'POST', body: 'SYNTHETIC_SECRET' });
  assert.equal(calls.at(-1).options.headers, undefined);
  active = true;
  await timers[0]();
  assert.equal(await window.fetch('/api/test', { method: 'POST', body: 'SYNTHETIC_SECRET' }), response);
  assert.match(calls.at(-1).options.headers.get('X-VSE-Trace-ID'), /^[a-f0-9]{32}$/);
  assert.equal(calls.at(-1).options.body, 'SYNTHETIC_SECRET');
  await window.fetch('https://external.test/api/test', {});
  assert.equal(calls.at(-1).options.headers, undefined);
  await window.fetch('/api/excel-tasks', {});
  assert.equal(calls.at(-1).options.headers, undefined);
  await assert.rejects(window.fetch('/api/failure'), /SYNTHETIC_SECRET/);
  const emitted = calls.filter(c => c.url === '/api/diagnostics/events');
  assert.ok(emitted.length);
  assert.ok(!JSON.stringify(emitted).includes('SYNTHETIC_SECRET'));
  // Starting a second recording must select the new bundle, not the old history item.
  const nodes = [];
  class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.handlers = {}; this._value = ''; nodes.push(this); }
    setAttribute() {} removeAttribute() {} contains() { return false; }
    addEventListener(type, fn) { this.handlers[type] = fn; }
    appendChild(node) { this.children.push(node); if (this.tag === 'select' && this.children.length === 1) this._value = node.value; }
    replaceChildren() { this.children = []; this._value = ''; }
    get value() { return this._value; } set value(v) { this._value = v; }
  }
  let latestState = { active: false, latest: { id: 'a'.repeat(32) }, recordings: [{id:'a'.repeat(32),created:1}] };
  const uiDocument = { readyState:'complete', body:new Element('body'), createElement:tag=>new Element(tag), addEventListener(){} };
  const uiWindow = { ...window, addEventListener(){}, fetch: async (url) => {
    if (url.endsWith('/start')) latestState = {active:true, latest:{id:'b'.repeat(32)}, recordings:[{id:'b'.repeat(32),created:2},...latestState.recordings]};
    return {ok:true,json:async()=>latestState};
  }};
  vm.runInNewContext(fs.readFileSync('web/static/diagnostics.js','utf8'), {
    window:uiWindow,document:uiDocument,Headers,Request,URL,Date,console,setInterval(){},setTimeout,
  });
  await new Promise(resolve=>setImmediate(resolve));
  await nodes.find(n=>n.textContent==='开始诊断').handlers.click();
  assert.equal(nodes.find(n=>n.tag==='select').value, 'b'.repeat(32));
  console.log('diagnostics browser assertions passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
