// High-density result grid (legacy "Phase 4" renderRows): quick filter with
// highlight, multi-column sort, paging, column show/hide with saved prefs and
// one-click copy of number columns. Sensitive columns never reach the DOM.
import { html, useEffect, useMemo, useRef, useState } from "/static/host/vendor/preact-htm.js";
import {
  GRID_DEFAULT_PAGE_SIZE,
  GRID_PAGE_SIZES,
  buildGridColumns,
  candidateColumns,
  gridColumnValue,
  highlightSegments,
  isCopyableColumn,
  nextSortSpec,
  processRows,
  safeDisplayValue,
  visibleColumnIndexes,
} from "./lib.js";

// 与旧页面共用同一个 localStorage 键，列偏好在新旧页面之间互通。
const GRID_COLUMN_PREF_KEY = "vse-grid-column-prefs";

function loadColumnPrefs(scope) {
  try {
    const parsed = JSON.parse(localStorage.getItem(GRID_COLUMN_PREF_KEY) || "{}");
    const prefs = parsed && typeof parsed === "object" ? parsed[scope] : null;
    return prefs && typeof prefs === "object" ? prefs : null;
  } catch (_) {
    return null;
  }
}

function saveColumnPrefs(scope, prefs) {
  try {
    const parsed = JSON.parse(localStorage.getItem(GRID_COLUMN_PREF_KEY) || "{}");
    const all = parsed && typeof parsed === "object" ? parsed : {};
    all[scope] = prefs;
    localStorage.setItem(GRID_COLUMN_PREF_KEY, JSON.stringify(all));
  } catch (_) {
    // 隐私模式等存储不可用：降级为会话内偏好
  }
}

async function copyText(value) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch (_) {
    // 走 execCommand 降级
  }
  try {
    const area = document.createElement("textarea");
    area.value = value;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  } catch (_) {
    return false;
  }
}

function Highlighted({ value, query }) {
  return highlightSegments(value, query).map((segment, i) => (segment.hit
    ? html`<mark key=${i} class="grid-highlight">${segment.text}</mark>`
    : segment.text));
}

function CopyButton({ label, value }) {
  const [state, setState] = useState("idle");
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);
  const onClick = (event) => {
    event.stopPropagation();
    copyText(value).then((ok) => {
      setState(ok ? "ok" : "fail");
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setState("idle"), 1200);
    });
  };
  const text = state === "ok" ? "✓" : state === "fail" ? "✕" : "📋";
  return html`<button type="button" class="grid-copy-btn sq-copy-btn" title="复制" aria-label=${`复制 ${label}`} onClick=${onClick}>${text}</button>`;
}

export function DataGrid({ data, modeId, preferredColumns }) {
  const rows = Array.isArray(data.rows) ? data.rows : [];
  const gridColumns = useMemo(() => buildGridColumns(data, rows, preferredColumns, modeId), [data, modeId]);
  const grouped = gridColumns.kind === "grouped";
  const pickable = !grouped && !gridColumns.fallback;
  const allColumns = useMemo(() => candidateColumns(gridColumns), [gridColumns]);
  const colByIndex = useMemo(() => new Map(allColumns.map((col) => [col.index, col])), [allColumns]);
  const commonCount = Math.min(allColumns.length, Number(data.defaultVisibleCount) || 12);
  const scope = modeId || data.report_type || "generic";

  const saved = loadColumnPrefs(scope);
  const [columnMode, setColumnMode] = useState(saved && saved.mode ? saved.mode : "default");
  const [hiddenColumns, setHiddenColumns] = useState(saved && Array.isArray(saved.hidden) ? saved.hidden : []);
  const [filterText, setFilterText] = useState("");
  const [sortSpec, setSortSpec] = useState([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(GRID_DEFAULT_PAGE_SIZE);
  const [pickerOpen, setPickerOpen] = useState(false);

  const visible = visibleColumnIndexes(allColumns, { grouped, columnMode, hiddenColumns, commonCount, modeId });
  const visibleCols = visible.map((index) => colByIndex.get(index) || { index, label: `列 ${index + 1}`, key: null });
  const filtered = useMemo(
    () => processRows(rows, visibleCols, filterText, sortSpec, colByIndex),
    [rows, visible.join(","), filterText, sortSpec, colByIndex],
  );
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const pageRows = filtered.slice((safePage - 1) * pageSize, safePage * pageSize);

  const applyColumns = (mode, hidden) => {
    setColumnMode(mode);
    setHiddenColumns(hidden);
    saveColumnPrefs(scope, { mode, hidden });
    setPage(1);
  };
  const toggleColumn = (index, checked) => {
    const hidden = new Set(columnMode === "custom" ? hiddenColumns : allColumns.map((c) => c.index).filter((i) => !visible.includes(i)));
    if (checked) hidden.delete(index);
    else hidden.add(index);
    applyColumns("custom", Array.from(hidden).sort((a, b) => a - b));
  };
  const onSort = (index, event) => {
    if (!pickable) return;
    setSortSpec((prev) => nextSortSpec(prev, index, Boolean(event && event.shiftKey)));
    setPage(1);
  };

  const header = grouped
    ? gridColumns.groups.map((headerRow, r) => html`<tr key=${r}>${headerRow.map((label, i) => html`<th key=${i}>
        <${Highlighted} value=${label ? String(label).trim() : ""} query=${filterText} />
      </th>`)}</tr>`)
    : html`<tr>${visibleCols.map((col) => {
      const entry = sortSpec.find((s) => s.index === col.index);
      const order = entry ? sortSpec.indexOf(entry) : -1;
      return html`<th
        key=${col.index}
        class=${pickable ? "grid-sortable" : ""}
        aria-sort=${entry ? (entry.dir === "asc" ? "ascending" : "descending") : "none"}
        onClick=${(event) => onSort(col.index, event)}
      >
        <${Highlighted} value=${col.label} query=${filterText} />
        ${entry && html`<span class="grid-sort-indicator">${entry.dir === "asc" ? "▲" : "▼"}${sortSpec.length > 1 ? String(order + 1) : ""}</span>`}
      </th>`;
    })}</tr>`;

  return html`<div class="table-wrap grid-wrap sq-grid">
    <div class="grid-toolbar">
      <div class="grid-filter-box">
        <input
          type="search" class="grid-filter-input" placeholder="关键字快筛（实时高亮）" aria-label="表格关键字快筛"
          value=${filterText} onInput=${(event) => { setFilterText(event.currentTarget.value); setPage(1); }}
        />
        <span class="grid-filter-count">${filterText ? `${filtered.length}/${rows.length} 条` : ""}</span>
      </div>
      ${pickable && html`<button
        type="button" class="grid-column-btn" aria-haspopup="true" aria-expanded=${pickerOpen ? "true" : "false"}
        onClick=${() => setPickerOpen(!pickerOpen)}
      >列显隐</button>`}
      ${pickable && pickerOpen && html`<div class="grid-column-panel">
        <div class="grid-column-quick">
          <button type="button" class="grid-quick-btn" onClick=${() => applyColumns("common", [])}>常用列</button>
          <button type="button" class="grid-quick-btn" onClick=${() => applyColumns("all", [])}>全量列</button>
        </div>
        <div class="grid-column-list">
          ${allColumns.map((col) => html`<label key=${col.index} class="grid-column-item">
            <input type="checkbox" checked=${visible.includes(col.index)} onChange=${(event) => toggleColumn(col.index, event.currentTarget.checked)} />
            <span>${col.label}</span>
          </label>`)}
        </div>
      </div>`}
    </div>
    <div class="sq-table-scroll">
      <table class=${`result-table${modeId === "tdc-sor" ? " sor-result-table" : ""}`}>
        <thead>${header}</thead>
        <tbody>
          ${pageRows.length === 0
            ? html`<tr><td colSpan=${Math.max(1, visible.length)}>${filterText ? "无匹配记录" : "无结果"}</td></tr>`
            : pageRows.map((row, r) => html`<tr key=${r}>${visibleCols.map((col) => {
              const value = gridColumnValue(row, col, col.index);
              const copyable = isCopyableColumn(col.label, col.key) && value != null && String(value).trim();
              return html`<td key=${col.index} class=${copyable ? "grid-copyable" : ""}>
                <${Highlighted} value=${safeDisplayValue(value)} query=${filterText} />
                ${copyable && html`<${CopyButton} label=${col.label} value=${String(value).trim()} />`}
              </td>`;
            })}</tr>`)}
        </tbody>
      </table>
    </div>
    ${filtered.length > 0 && html`<div class="grid-pager">
      <span class="grid-pager-info">共 ${filtered.length} 条 · 第 ${safePage}/${totalPages} 页</span>
      <button type="button" class="grid-pager-btn" disabled=${safePage <= 1} onClick=${() => setPage(safePage - 1)}>上一页</button>
      <button type="button" class="grid-pager-btn" disabled=${safePage >= totalPages} onClick=${() => setPage(safePage + 1)}>下一页</button>
      <span class="grid-pager-size-label">每页</span>
      <select class="grid-pager-size" aria-label="每页条数" value=${String(pageSize)}
        onChange=${(event) => { setPageSize(Number(event.currentTarget.value) || GRID_DEFAULT_PAGE_SIZE); setPage(1); }}>
        ${GRID_PAGE_SIZES.map((size) => html`<option key=${size} value=${String(size)}>${size}</option>`)}
      </select>
    </div>`}
  </div>`;
}
