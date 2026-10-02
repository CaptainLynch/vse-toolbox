// UI Kit v0: the building blocks schema pages and plugin modules share.
// Components are pure (props in, events out); data loading lives in api.js.
import { html, useMemo, useState } from "./vendor/preact-htm.js";

export { html };

/** Loading / error / empty placeholder; renders nothing when content is ready. */
export function StateBlock({ loading, error, empty, emptyText = "暂无数据", onRetry }) {
  if (error) {
    return html`<div class="vk-state is-error" role="alert">
      <span>${error.message || String(error)}</span>
      ${onRetry && html`<button type="button" class="vk-btn" onClick=${onRetry}>重试</button>`}
    </div>`;
  }
  if (loading) return html`<div class="vk-state is-loading" aria-busy="true">加载中…</div>`;
  if (empty) return html`<div class="vk-state is-empty">${emptyText}</div>`;
  return null;
}

function cellValue(row, column) {
  const value = row[column.key];
  if (column.format) return column.format(value, row);
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function compareValues(a, b) {
  const na = Number(a);
  const nb = Number(b);
  if (a !== "" && b !== "" && !Number.isNaN(na) && !Number.isNaN(nb)) return na - nb;
  return String(a ?? "").localeCompare(String(b ?? ""), "zh-CN");
}

/**
 * columns: [{key, title, width?, sortable? (default true), format?(value,row)}]
 * Client-side sort and paging; rows beyond `pageSize` are paged, never dropped.
 */
export function DataTable({ columns, rows, rowKey = "id", pageSize = 50, emptyText = "没有符合条件的记录", onRowClick }) {
  const [sort, setSort] = useState({ key: null, dir: 1 });
  const [page, setPage] = useState(0);
  const list = rows || [];

  const sorted = useMemo(() => {
    if (!sort.key) return list;
    return [...list].sort((a, b) => compareValues(a[sort.key], b[sort.key]) * sort.dir);
  }, [list, sort.key, sort.dir]);

  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const visible = sorted.slice(safePage * pageSize, (safePage + 1) * pageSize);

  const toggleSort = (column) => {
    if (column.sortable === false) return;
    setSort((prev) => (prev.key === column.key ? { key: column.key, dir: -prev.dir } : { key: column.key, dir: 1 }));
  };

  if (list.length === 0) return html`<${StateBlock} empty=${true} emptyText=${emptyText} />`;

  return html`<div class="vk-table-wrap">
    <table class="vk-table">
      <thead><tr>
        ${columns.map((column) => html`<th
          key=${column.key}
          style=${column.width ? { width: column.width } : null}
          class=${column.sortable === false ? "" : "is-sortable"}
          aria-sort=${sort.key === column.key ? (sort.dir > 0 ? "ascending" : "descending") : "none"}
          onClick=${() => toggleSort(column)}
        >${column.title}${sort.key === column.key ? (sort.dir > 0 ? " ▲" : " ▼") : ""}</th>`)}
      </tr></thead>
      <tbody>
        ${visible.map((row, index) => html`<tr
          key=${row[rowKey] ?? index}
          class=${onRowClick ? "is-clickable" : ""}
          onClick=${onRowClick ? () => onRowClick(row) : null}
        >${columns.map((column) => html`<td key=${column.key}>${cellValue(row, column)}</td>`)}</tr>`)}
      </tbody>
    </table>
    <div class="vk-table-footer">
      <span>共 ${list.length} 条</span>
      ${pageCount > 1 && html`<span class="vk-pager">
        <button type="button" class="vk-btn" disabled=${safePage === 0} onClick=${() => setPage(safePage - 1)}>上一页</button>
        <span>${safePage + 1} / ${pageCount}</span>
        <button type="button" class="vk-btn" disabled=${safePage >= pageCount - 1} onClick=${() => setPage(safePage + 1)}>下一页</button>
      </span>`}
    </div>
  </div>`;
}

/**
 * fields: [{key, label, type: "text"|"select"|"date", options?: [{value,label}] | string[], placeholder?}]
 * Edits stay local until "查询"; `onChange` receives the whole value object.
 */
export function FilterBar({ fields, value, onChange }) {
  const [draft, setDraft] = useState(value || {});
  const set = (key, next) => setDraft((prev) => ({ ...prev, [key]: next }));
  const submit = (event) => {
    event.preventDefault();
    onChange({ ...draft });
  };
  const clear = () => {
    setDraft({});
    onChange({});
  };

  return html`<form class="vk-filter-bar" onSubmit=${submit}>
    ${fields.map((field) => {
      const current = draft[field.key] ?? "";
      const onInput = (event) => set(field.key, event.currentTarget.value);
      let control;
      if (field.type === "select") {
        const options = (field.options || []).map((option) => (typeof option === "string" ? { value: option, label: option } : option));
        control = html`<select value=${current} onChange=${onInput}>
          <option value="">全部</option>
          ${options.map((option) => html`<option key=${option.value} value=${option.value}>${option.label}</option>`)}
        </select>`;
      } else {
        control = html`<input type=${field.type === "date" ? "date" : "text"} value=${current} placeholder=${field.placeholder || ""} onInput=${onInput} />`;
      }
      return html`<label key=${field.key} class="vk-filter-field"><span>${field.label}</span>${control}</label>`;
    })}
    <span class="vk-filter-actions">
      <button type="submit" class="vk-btn is-primary">查询</button>
      <button type="button" class="vk-btn" onClick=${clear}>清空</button>
    </span>
  </form>`;
}

/**
 * Completed / incomplete stacked bars per group, ported from the legacy
 * renderDepartmentDoneChart (same CSS classes, no chart library).
 * groups: {name: {total, completed, incomplete}}; clicking a row selects it,
 * clicking "整体" or the selected row clears the selection.
 */
export function DoneBars({ summary, groups, selected, onSelect, title, labels }) {
  const [doneText, undoneText] = labels && labels.length === 2 ? labels : ["已完成", "未完成"];
  const entries = Object.entries(groups || {})
    .filter(([, value]) => value && typeof value === "object")
    .sort(([, a], [, b]) => (Number(b.total) || 0) - (Number(a.total) || 0));
  const total = Number(summary && summary.total) || 0;
  if (entries.length === 0 && total === 0) {
    return html`<p class="analysis-empty-note is-empty">暂无完成情况统计</p>`;
  }
  const completed = Number(summary && summary.completed) || 0;
  const incomplete = Number(summary && summary.incomplete) || Math.max(0, total - completed);
  const max = Math.max(1, total, ...entries.map(([, d]) => Number(d.total) || 0));
  const pct = (n) => `${(n / max) * 100}%`;

  const row = (name, done, undone, all, isOverall) => {
    const active = isOverall ? selected == null : selected === name;
    const choose = () => onSelect && onSelect(isOverall || selected === name ? null : name);
    return html`<div
      key=${isOverall ? "__overall" : name}
      class=${`analysis-dept-bar-row${isOverall ? " is-overall" : ""}${active && !isOverall ? " is-selected" : ""}`}
      role="button" tabindex="0" aria-pressed=${active ? "true" : "false"}
      aria-label=${`${name}: ${doneText} ${done}, ${undoneText} ${undone}, 共 ${all}`}
      onClick=${choose}
      onKeyDown=${(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); choose(); } }}
    >
      <span class="analysis-dept-bar-name" title=${name}>${name}</span>
      <div class="analysis-dept-bar-track">
        <div class="analysis-dept-bar-fill is-completed" style=${{ width: pct(done) }}></div>
        <div class="analysis-dept-bar-fill is-incomplete" style=${{ width: pct(undone) }}></div>
      </div>
      <span class="analysis-dept-bar-nums">
        <span class="analysis-dept-bar-num is-completed">${doneText} ${done}</span>
        <span class="analysis-dept-bar-num is-incomplete">${undoneText} ${undone}</span>
        <span class="analysis-dept-bar-num is-total">共 ${all}</span>
      </span>
    </div>`;
  };

  return html`<div class="analysis-sub-section">
    <div class="analysis-dept-chart-header">
      <h6 class="analysis-sub-title">${title || `完成情况（${doneText} / ${undoneText}）`}</h6>
      <div class="analysis-chart-legend">
        <span class="analysis-chart-legend-item is-completed">${doneText}</span>
        <span class="analysis-chart-legend-item is-incomplete">${undoneText}</span>
      </div>
    </div>
    <div class="analysis-dept-bars-box">
      ${row("整体", completed, incomplete, total, true)}
      ${entries.map(([name, d]) => {
        const all = Number(d.total) || 0;
        const done = Number(d.completed) || 0;
        return row(name, done, Number(d.incomplete) || Math.max(0, all - done), all, false);
      })}
    </div>
  </div>`;
}

/** tabs: [{id, title, render: () => vnode}] */
export function ChartTabs({ tabs }) {
  const [active, setActive] = useState(tabs.length ? tabs[0].id : null);
  if (!tabs.length) return null;
  const current = tabs.find((tab) => tab.id === active) || tabs[0];
  return html`<div class="vk-chart-tabs">
    ${tabs.length > 1 && html`<div class="analysis-chart-tabs" role="tablist">
      ${tabs.map((tab) => html`<button
        key=${tab.id} type="button" role="tab"
        class=${`analysis-chart-tab${tab.id === current.id ? " is-active" : ""}`}
        aria-selected=${tab.id === current.id ? "true" : "false"}
        onClick=${() => setActive(tab.id)}
      >${tab.title}</button>`)}
    </div>`}
    <div role="tabpanel">${current.render()}</div>
  </div>`;
}

/** Load a plugin stylesheet once (e.g. useStylesheet(`/plugins/${plugin.id}/static/page.css`)). */
export function useStylesheet(href) {
  if (typeof document === "undefined" || !href) return;
  if (document.querySelector(`link[data-plugin-css="${href}"]`)) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  link.dataset.pluginCss = href;
  document.head.appendChild(link);
}
