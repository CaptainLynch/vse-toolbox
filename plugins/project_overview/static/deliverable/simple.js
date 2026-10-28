// 交付物详情的「简洁视图」（v2 默认）：一眼看懂进度 → 四个数字 → 需要关注的单据。
// 完整的表单分析、筛选、图表、同步设置和记录都还在，点「显示完整明细与分析」才出现；
// 专家模式默认直接打开完整视图。本视图只读已有接口，不新增后端逻辑。
import { html, useEffect, useState } from "/static/host/vendor/preact-htm.js";
import { apiRequest, enc } from "./api.js";
import { redactSensitiveText, safeDisplayValue } from "./format.js";

const PAGE_SIZE = 20;
/** 简表优先挑这些列（按顺序，最多 5 列）；表单没声明关键列时也能挑出可读的几列。 */
const PREFERRED_LABELS = ["流水单号", "NCR编号", "EWO编号", "PAA编号", "SOR号", "零件名称", "更改主题", "标题", "申请人", "部门", "申请日期", "提交日期"];
const MAX_COLUMNS = 5;

export function simpleColumns(schema) {
  const columns = Array.isArray(schema && schema.columns) ? schema.columns : [];
  const picked = [];
  PREFERRED_LABELS.forEach((label) => {
    const column = columns.find((c) => c && c.label === label);
    if (column && picked.length < MAX_COLUMNS && !picked.includes(column)) picked.push(column);
  });
  if (picked.length < 3) {
    const keys = Array.isArray(schema && schema.keyColumns) ? schema.keyColumns : [];
    keys.forEach((index) => {
      const column = columns.find((c) => c && c.index === Number(index));
      if (column && picked.length < MAX_COLUMNS && !picked.includes(column)) picked.push(column);
    });
  }
  columns.forEach((column) => {
    if (picked.length < 3 && !picked.includes(column)) picked.push(column);
  });
  return picked;
}

function cell(value) {
  if (value === null || value === undefined || value === "") return "—";
  return safeDisplayValue(String(value).replace(/ \d{2}:\d{2}(:\d{2})?$/, ""));
}

function syncLine(item) {
  const policy = item.updatePolicy || {};
  const caps = item.sourceInfo || {};
  if (policy.lastErrorMessage) return { tone: "bad", text: `上次同步失败：${redactSensitiveText(String(policy.lastErrorMessage))}` };
  if (policy.enabled) return { tone: "ok", text: `自动同步已开启${policy.lastSuccessAt ? ` · 上次 ${String(policy.lastSuccessAt).replace("T", " ").slice(5, 16)}` : ""}` };
  if (caps.syncCapable) return { tone: "off", text: "自动同步未开启" };
  return { tone: "off", text: "手工维护" };
}

function Records({ formKey }) {
  const [schema, setSchema] = useState(null);
  const [rows, setRows] = useState({ items: [], total: 0 });
  const [keyword, setKeyword] = useState("");
  const [applied, setApplied] = useState("");
  const [onlyOverdue, setOnlyOverdue] = useState(false);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiRequest(`/api/deliverable-forms/${enc(formKey)}/view?trendLimit=30`)
      .then((view) => setSchema((view && view.schema) || {}))
      .catch((err) => setError(redactSensitiveText(err.message || String(err))));
  }, [formKey]);

  useEffect(() => {
    let alive = true;
    const params = new URLSearchParams({ offset: "0", limit: String(limit) });
    if (applied) params.set("keyword", applied);
    if (onlyOverdue) params.set("overdueState", "overdue");
    setLoading(true);
    apiRequest(`/api/deliverable-forms/${enc(formKey)}/rows?${params.toString()}`)
      .then((data) => { if (alive) { setRows({ items: (data && data.items) || [], total: (data && data.total) || 0 }); setError(""); } })
      .catch((err) => { if (alive) setError(redactSensitiveText(err.message || String(err))); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [formKey, applied, onlyOverdue, limit]);

  const columns = simpleColumns(schema);
  const search = (event) => { event.preventDefault(); setLimit(PAGE_SIZE); setApplied(keyword.trim()); };

  return html`<section class="ds-card">
    <div class="ds-card-head"><h3>单据</h3>
      <form class="ds-search" onSubmit=${search}>
        <input type="search" value=${keyword} onInput=${(e) => setKeyword(e.currentTarget.value)} placeholder="搜单号、零件名称、申请人" aria-label="搜索单据" />
        <button type="submit" class="vk-btn">搜索</button>
        <label class="ds-check"><input type="checkbox" checked=${onlyOverdue} onChange=${() => { setLimit(PAGE_SIZE); setOnlyOverdue(!onlyOverdue); }} />只看逾期</label>
      </form></div>
    ${error && html`<p class="ds-error" role="alert">读取单据失败：${error}</p>`}
    ${!error && html`<div class="ds-table-wrap"><table class="ds-table">
      <thead><tr>${columns.map((c) => html`<th key=${c.key}>${c.label}</th>`)}<th>状态</th></tr></thead>
      <tbody>${rows.items.map((row) => {
        const values = Array.isArray(row.values) ? row.values : [];
        const dims = row.dimensions || {};
        const late = row.overdueState === "overdue" && !row.isCompleted;
        return html`<tr key=${row.rowKey}>
          ${columns.map((c) => html`<td key=${c.key}>${cell(values[c.index])}</td>`)}
          <td><span class=${`ds-pill is-${row.isCompleted ? "ok" : late ? "bad" : "info"}`}>${row.isCompleted ? "已完成" : late ? "逾期" : safeDisplayValue(dims.status || "进行中")}</span></td>
        </tr>`;
      })}</tbody>
    </table></div>`}
    ${!error && !loading && !rows.items.length && html`<p class="ds-muted">${applied || onlyOverdue ? "没有符合条件的单据。" : "还没有单据数据，开启自动同步或点「立即同步」后会出现。"}</p>`}
    <div class="ds-foot"><span class="ds-muted">${loading ? "读取中…" : `共 ${rows.total} 条${rows.items.length < rows.total ? `，已显示 ${rows.items.length} 条` : ""}`}</span>
      ${rows.items.length < rows.total && html`<button type="button" class="vk-btn" disabled=${loading} onClick=${() => setLimit(limit + PAGE_SIZE)}>再显示 ${PAGE_SIZE} 条</button>`}</div>
  </section>`;
}

export function SimpleDetail({ item, onShowFull, onSynced }) {
  const [syncing, setSyncing] = useState("");
  const summary = (item.formLink && item.formLink.summary) || null;
  const formKey = item.formLink && item.formLink.formKey;
  const sync = syncLine(item);
  const policy = item.updatePolicy || {};
  const caps = item.sourceInfo || {};
  const progress = Math.max(0, Math.min(100, Number(item.progress) || 0));
  const late = item.scheduleState === "overdue";

  const syncNow = async () => {
    setSyncing("正在同步…");
    try {
      await apiRequest(`/api/project-status/deliverables/${enc(item.id)}/sync-now`, { method: "POST" });
      setSyncing("同步完成");
      if (onSynced) await onSynced();
    } catch (err) {
      setSyncing(`同步失败：${redactSensitiveText(err.message || String(err))}`);
    }
  };

  return html`<div class="ds-page">
    <div class="ds-top"><a class="vk-btn" href="#p/workbench/project">← 返回项目</a>
      <button type="button" class="vk-btn" onClick=${onShowFull}>显示完整明细与分析</button></div>

    <section class="ds-card ds-hero">
      <div class="ds-hero-main">
        <h2>${safeDisplayValue(item.name)}</h2>
        <p class="ds-muted">${item.owner ? `负责人 ${safeDisplayValue(item.owner)} · ` : ""}计划完成 ${item.plannedDate || "未设置"}
          ${late ? html` · <b class="ds-bad">逾期 ${item.scheduleDays} 天</b>` : ""}</p>
        <div class="ds-progress"><i style=${`width:${progress}%`} class=${late ? "is-bad" : progress >= 100 ? "is-ok" : ""}></i></div>
        <p class="ds-muted">${progress}% · ${safeDisplayValue(item.effectiveStatus || item.status || "")}</p>
      </div>
      <div class="ds-hero-side">
        <span class=${`ds-pill is-${sync.tone}`}>${sync.text}</span>
        ${policy.enabled
          ? html`<button type="button" class="vk-btn is-primary" disabled=${syncing === "正在同步…"} onClick=${syncNow}>立即同步</button>`
          : caps.syncCapable
            ? html`<a class="vk-btn is-primary" href="#p/project-overview/auto-sync">开启自动同步</a>`
            : html`<button type="button" class="vk-btn" onClick=${onShowFull}>手工更新进度</button>`}
        ${syncing && html`<small class="ds-muted" role="status">${syncing}</small>`}
      </div>
    </section>

    ${summary && html`<div class="ds-kpis">
      <div class="ds-kpi"><span>总数</span><b>${summary.total ?? 0}</b></div>
      <div class="ds-kpi"><span>已完成</span><b class="ds-ok">${summary.completed ?? 0}</b></div>
      <div class="ds-kpi"><span>未完成</span><b>${summary.incomplete ?? 0}</b></div>
      <div class="ds-kpi"><span>逾期</span><b class=${summary.overdue ? "ds-bad" : ""}>${summary.overdue ?? 0}</b></div>
    </div>`}

    ${formKey
      ? html`<${Records} formKey=${formKey} />`
      : html`<section class="ds-card"><p class="ds-muted" style="margin:0">这个交付物没有单据明细，进度在「手工更新进度」里填写。</p></section>`}
  </div>`;
}
