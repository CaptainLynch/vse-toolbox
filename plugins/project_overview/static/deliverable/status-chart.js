// Current-status chart (legacy renderDeliverableStatusChart +
// renderEwoSyncSummary) and the interactive ARAS query result panel
// (legacy renderInteractiveArasResult).
import { html, useEffect, useState } from "/static/host/vendor/preact-htm.js";
import { DataTable } from "/static/host/kit.js";
import { isEwoSource, statusChartModel } from "./display.js";
import { SENSITIVE_COLUMNS, archiveFormatDate, safeDisplayValue } from "./format.js";
import { INTERACTIVE_MODES, formatInteractiveArasResult } from "./policy-logic.js";

const EWO_STATUS_LABELS = { idle: "空闲", running: "同步中", success: "成功", failed: "失败", needs_attention: "需处理" };

export function EwoSyncSummary({ item, data, feedback }) {
  const summary = data && data.summary ? data.summary : {};
  const policy = item.updatePolicy || {};
  const syncState = policy.syncState || "idle";
  const statusText = (feedback && feedback.text) || (policy.enabled === false ? "未启用" : (EWO_STATUS_LABELS[syncState] || "未知"));
  const tone = feedback && feedback.text ? feedback.tone : "";
  const snapshotText = data && data.snapshotAt ? archiveFormatDate(data.snapshotAt) : "暂无快照";
  return html`
    <div class="ewo-sync-summary-head">
      <h6 class="section-sub-title">EWO 同步摘要</h6>
      <span class=${`ewo-sync-summary-status${tone ? ` is-${tone}` : ""}`}>${statusText}</span>
    </div>
    <div class="ewo-sync-summary-meta">
      <span>最近同步状态：${statusText}</span>
      <span>最近同步时间：${snapshotText}</span>
    </div>
    <div class="ewo-sync-summary-metrics">
      ${[["总数", summary.total ?? 0], ["已完成", summary.completed ?? 0], ["未完成", summary.incomplete ?? 0], ["逾期", summary.overdue ?? 0]].map(([label, value]) => html`
        <div class="ewo-sync-summary-metric" key=${label}>
          <span class="detail-property-label">${label}</span>
          <strong class="detail-property-value">${String(value)}</strong>
        </div>`)}
    </div>
    <p class="ewo-sync-summary-source">统计来自最近一次 EWO 快照</p>`;
}

/**
 * props: item (raw), ewoData, feedback {text,tone}, busy, onInteractiveRefresh, onRefresh
 */
export function StatusChart({ item: rawItem, ewoData, feedback, busy, onInteractiveRefresh, onRefresh }) {
  const m = statusChartModel(rawItem);
  const item = m.item;
  const ewo = isEwoSource(item);
  let progressTitle;
  if (!m.hasValue) progressTitle = m.syncDisplay.label;
  else if (m.formDisplay) {
    progressTitle = html`<span class="deliverable-snapshot-tag">快照进度</span><span class="deliverable-snapshot-date">${m.snapshotDate ? `（${m.snapshotDate}）` : ""}</span>`;
  } else progressTitle = "项目手工进度";
  const feedbackText = feedback && feedback.text ? feedback.text : "";
  return html`<section class=${`deliverable-current-status-chart${busy ? " is-sync-busy" : ""}`} role="region" aria-label=${`${safeDisplayValue(item.name)} 当前状态图表`}>
    <div class="deliverable-current-status-head">
      <h6 class="section-sub-title">当前状态图表</h6>
      <span class=${`status-text is-${m.tone}`}>${safeDisplayValue(m.statusText)}</span>
    </div>
    <div class="deliverable-current-status-progress">
      <div class="deliverable-current-status-label">
        <span class="deliverable-progress-title">${progressTitle}</span>
        <strong>${m.progressLabel}</strong>
      </div>
      <div class="analysis-chart-track" role="progressbar" aria-valuemin="0" aria-valuemax="100"
        aria-valuenow=${m.hasProgress || item.status === "已完成" ? String(m.progress) : null}>
        <div class=${`analysis-chart-fill${item.status === "已完成" ? " is-completed" : ""}`} style=${{ width: `${m.progress}%` }}></div>
      </div>
    </div>
    <div class="deliverable-current-status-timeline">
      ${[["计划完成日期", item.plannedDate || "未设置"], ["实际完成日期", item.actualDate || "未完成"]].map(([label, value]) => html`
        <div class="deliverable-current-status-date" key=${label}>
          <span class="detail-property-label">${label}</span>
          <strong class="detail-property-value">${safeDisplayValue(value)}</strong>
        </div>`)}
    </div>
    ${ewo && html`<section class="ewo-sync-summary" aria-live="polite">
      <${EwoSyncSummary} item=${item} data=${ewoData} feedback=${feedback} />
      <div class="ewo-sync-summary-actions">
        <button type="button" class="btn is-primary ewo-interactive-refresh-btn" data-query-mode="interactive" disabled=${busy}
          aria-label=${feedbackText ? `立即刷新（交互式查询，${feedbackText}）` : "立即刷新（交互式查询）"}
          onClick=${onInteractiveRefresh}>立即刷新（交互式查询）</button>
        <button type="button" class="btn is-secondary ewo-sync-refresh-btn" disabled=${busy} onClick=${onRefresh}>刷新后台分析</button>
      </div>
    </section>`}
  </section>`;
}

// ---- interactive query result --------------------------------------------------

let gridModulePromise = null;
function loadGridModule() {
  if (!gridModulePromise) {
    // Reuse the system-query result grid (legacy renderRows parity) when that
    // plugin is installed; fall back to the kit table otherwise.
    gridModulePromise = import("/plugins/system-query/static/grid.js").catch(() => null);
  }
  return gridModulePromise;
}

function FallbackRows({ data, mode }) {
  const rows = Array.isArray(data.rows) ? data.rows : [];
  const config = INTERACTIVE_MODES[mode] || {};
  let columns;
  if (Array.isArray(data.columns) && data.columns.length) {
    columns = data.columns.map((col, index) => ({
      key: String(index),
      title: (col && (col.label || col.key)) || `列 ${index + 1}`,
      source: col && col.key ? String(col.key) : null,
      index: Number.isInteger(col && col.index) ? col.index : index,
    })).filter((col) => !(col.source && SENSITIVE_COLUMNS.has(col.source.toLowerCase())));
  } else {
    const available = new Set();
    rows.forEach((row) => row && typeof row === "object" && !Array.isArray(row)
      && Object.keys(row).forEach((key) => { if (!SENSITIVE_COLUMNS.has(key.toLowerCase())) available.add(key); }));
    const preferred = (config.preferredColumns || []).filter((key) => available.has(key));
    const keys = [...preferred, ...Array.from(available).filter((key) => !preferred.includes(key)).sort()].slice(0, 12);
    columns = keys.map((key, index) => ({ key: String(index), title: key, source: key, index }));
  }
  const limit = Number(data.defaultVisibleCount) || 12;
  if (mode === "ewo" || mode === "paa") columns = columns.slice(0, limit);
  const tableRows = rows.map((row, rowIndex) => {
    const out = { __id: rowIndex };
    columns.forEach((col) => {
      const value = Array.isArray(row) ? row[col.index] : (row && col.source ? row[col.source] : undefined);
      out[col.key] = value === null || value === undefined ? "" : safeDisplayValue(value);
    });
    return out;
  });
  return html`<${DataTable} columns=${columns.map(({ key, title }) => ({ key, title }))} rows=${tableRows} rowKey="__id" />`;
}

export function InteractiveResult({ mode, data, targetKey }) {
  const [grid, setGrid] = useState(null);
  useEffect(() => {
    let alive = true;
    loadGridModule().then((mod) => { if (alive && mod && mod.DataGrid) setGrid(() => mod.DataGrid); });
    return () => { alive = false; };
  }, []);
  const config = INTERACTIVE_MODES[mode] || {};
  const resultState = formatInteractiveArasResult(data, targetKey, mode);
  const rows = data && Array.isArray(data.rows) ? data.rows : [];
  const count = data && data.count !== undefined ? Number(data.count) || rows.length : rows.length;
  const Grid = grid;
  return html`<section class="interactive-query-result" data-query-mode=${mode}>
    <strong class="interactive-query-title">交互式查询 · ${config.label || mode}</strong>
    <span class=${`interactive-query-state is-${resultState.tone}`}>${resultState.text}</span>
    <p class="interactive-query-meta">返回 ${count} 条 · 第 ${Number(data && data.page) || 1} 页</p>
    <p class="interactive-query-notice">本次结果未写入后台同步状态</p>
    ${(resultState.state === "empty" || resultState.state === "no_match") && html`<p class="interactive-query-state-detail">${resultState.text}</p>`}
    ${Grid
      ? html`<${Grid} data=${data || {}} modeId=${mode} preferredColumns=${config.preferredColumns || []} />`
      : html`<${FallbackRows} data=${data || {}} mode=${mode} />`}
  </section>`;
}
