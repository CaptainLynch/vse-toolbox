/* Safe local diagnostics: metadata only; never inspect bodies or error text. */
(() => {
  'use strict';
  const nativeFetch = window.fetch.bind(window);
  let active = false;
  let lastAction = '';
  let actionTime = 0;
  let rateTime = 0;
  let rateCount = 0;
  let polling = false;
  let state = { recordings: [] };
  let widget;
  let title;
  let status;
  let history;
  let start;
  let stop;
  let mark;
  let download;
  let selectedRecording = '';
  const id = () => window.crypto.randomUUID().replaceAll('-', '');

  function sendEvent(payload) {
    if (!active) return;
    const now = Date.now();
    if (now - rateTime > 5000) { rateTime = now; rateCount = 0; }
    if (++rateCount > 100) return;
    nativeFetch('/api/diagnostics/events', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload), keepalive: true,
    }).catch(() => {});
  }

  window.fetch = function(input, options) {
    let url;
    try { url = new URL(input instanceof Request ? input.url : String(input), window.location.origin); }
    catch (_) { return nativeFetch(input, options); }
    if (!active || url.origin !== window.location.origin || !url.pathname.startsWith('/api/') ||
        url.pathname.startsWith('/api/diagnostics') || url.pathname.startsWith('/api/excel')) {
      return nativeFetch(input, options);
    }
    let next;
    let trace;
    try {
      trace = id();
      next = { ...options };
      next.headers = new Headers(options?.headers ?? (input instanceof Request ? input.headers : undefined));
      next.headers.set('X-VSE-Trace-ID', trace);
      if (Date.now() - actionTime < 30000 && lastAction) next.headers.set('X-VSE-Action-ID', lastAction);
    } catch (_) { return nativeFetch(input, options); }
    return nativeFetch(input, next).catch(error => {
      sendEvent({ kind: 'fetch_error', trace_id: trace, action_id: lastAction });
      throw error;
    });
  };

  document.addEventListener('click', event => {
    if (!active || widget?.contains(event.target)) return;
    if (!event.target?.closest?.('button,a,[role="button"]')) return;
    lastAction = id();
    actionTime = Date.now();
    sendEvent({ kind: 'action', action_id: lastAction });
  }, true);
  window.addEventListener('error', event => {
    let source = 'unknown';
    try {
      const path = new URL(event.filename || '', window.location.origin).pathname;
      if (path === '/static/app.js') source = 'app.js';
      if (path === '/static/diagnostics.js') source = 'diagnostics.js';
    } catch (_) { /* Keep only a fixed source label. */ }
    sendEvent({ kind: 'frontend_error', source, line: Number(event.lineno) || 0, column: Number(event.colno) || 0, action_id: lastAction });
  });
  window.addEventListener('unhandledrejection', () => {
    sendEvent({ kind: 'frontend_error', action_id: lastAction });
  });

  function render() {
    if (!widget) return;
    title.textContent = active ? '诊断录制 · 正在录制' : '诊断录制';
    start.disabled = active;
    stop.disabled = !active;
    mark.disabled = !active;
    const remaining = Math.max(0, Math.ceil(((state.latest?.expires || 0) * 1000 - Date.now()) / 60_000));
    status.textContent = active
      ? `正在录制 · 剩余 ${remaining} 分钟 · ${Math.round((state.latest?.size || 0) / 1024)} KB`
      : `录制已关闭${state.latest?.reason === 'capacity' ? '（已达到容量上限）' : ''}`;
    const selected = selectedRecording;
    history.replaceChildren();
    for (const item of state.recordings || []) {
      const option = document.createElement('option');
      option.value = item.id;
      option.textContent = `${new Date(item.created * 1000).toLocaleString()} · ${item.id.slice(0, 8)}`;
      history.appendChild(option);
    }
    if ((state.recordings || []).some(item => item.id === selected)) history.value = selected;
    if (!selectedRecording) selectedRecording = history.value;
    updateDownload();
  }

  function updateDownload() {
    const value = history.value;
    if (/^[a-f0-9]{32}$/.test(value || '')) {
      download.href = `/api/diagnostics/bundles/${value}`;
      download.removeAttribute('aria-disabled');
      download.hidden = false;
    } else {
      download.removeAttribute('href');
      download.setAttribute('aria-disabled', 'true');
      download.hidden = true;
    }
  }

  async function refresh() {
    if (polling) return;
    polling = true;
    try {
      const response = await nativeFetch('/api/diagnostics', { cache: 'no-store' });
      if (!response.ok) throw new Error('unavailable');
      state = await response.json();
      active = state.active === true;
      render();
    } catch (_) {
      active = false;
      if (status) status.textContent = '诊断服务不可用；已有录制请稍后重新连接导出';
    } finally { polling = false; }
  }

  async function control(action) {
    try {
      const response = await nativeFetch(`/api/diagnostics/${action}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      });
      if (!response.ok) throw new Error('failed');
      if (action === 'start') {
        const created = await response.json();
        selectedRecording = created.latest?.id || '';
        state = created;
        active = state.active === true;
        render();
      }
      await refresh();
      if (action === 'mark') status.textContent = '已标记问题时间点';
    } catch (_) { status.textContent = '操作未成功，请检查本地诊断目录或稍后重试'; }
  }

  function mount() {
    widget = document.createElement('details');
    widget.className = 'diagnostic-widget';
    title = document.createElement('summary');
    title.textContent = '诊断录制';
    widget.appendChild(title);
    status = document.createElement('p');
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    widget.appendChild(status);
    const note = document.createElement('p');
    note.textContent = '安全录制30分钟，覆盖非 Office 链路。标记问题后停止并下载诊断包。';
    widget.appendChild(note);
    function button(label, action) {
      const node = document.createElement('button');
      node.type = 'button'; node.textContent = label;
      node.addEventListener('click', () => control(action));
      widget.appendChild(node); return node;
    }
    start = button('开始诊断', 'start');
    stop = button('停止录制', 'stop');
    mark = button('标记问题', 'mark');
    history = document.createElement('select');
    history.setAttribute('aria-label', '选择诊断录制');
    history.addEventListener('change', () => { selectedRecording = history.value; updateDownload(); });
    widget.appendChild(history);
    download = document.createElement('a');
    download.textContent = '下载诊断 ZIP';
    widget.appendChild(download);
    document.body.appendChild(widget);
    render();
    refresh();
  }
  setInterval(refresh, 5000);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
  else mount();
})();
