// 交付物详情的「简洁视图」（v2 默认）：一眼看懂进度 → 四个数字 → 需要关注的单据。
// 完整的表单分析、筛选、图表、同步设置和记录都还在，点「显示完整明细与分析」才出现；
// 专家模式默认直接打开完整视图。本视图只读已有接口，不新增后端逻辑。
// 纯口径（阶段/逾期/派生进度/同步文案/自适应排序/列显隐/单号复制）在 simple-logic.js，由 Node 门禁直接断言。
import { html, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { apiRequest, enc } from "./api.js";
import { redactSensitiveText, safeDisplayValue } from "./format.js";
import {
  calculateVisibleColumns,
  candidateColumns,
  copyTextToClipboard,
  extractSerialNumber,
  findSerialNumberColumn,
  getRowCellValue,
  loadColumnPreferences,
  nextSortState,
  overdueLabel,
  progressDisplay,
  saveColumnPreferences,
  simpleColumns,
  sortRows,
  stageLabel,
  syncResultText,
} from "./simple-logic.js";

export { simpleColumns };

const PAGE_SIZE = 20;

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

  // 简表交互状态：列显隐偏好、下拉开闭、排序三态、行内复制反馈
  const [colPrefs, setColPrefs] = useState(() => loadColumnPreferences(formKey));
  const [colPickerOpen, setColPickerOpen] = useState(false);
  const [sortState, setSortState] = useState({ key: null, direction: null });
  const [copiedKey, setCopiedKey] = useState(null);
  const copyTimer = useRef(null);

  useEffect(() => () => clearTimeout(copyTimer.current), []);

  useEffect(() => {
    setColPrefs(loadColumnPreferences(formKey));
    setSortState({ key: null, direction: null });
    setCopiedKey(null);
  }, [formKey]);

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

  const candidateCols = candidateColumns(schema, rows.items);
  const defaultCols = simpleColumns(schema, rows.items);
  const visibleCols = calculateVisibleColumns(candidateCols, colPrefs, defaultCols);

  const search = (event) => { event.preventDefault(); setLimit(PAGE_SIZE); setApplied(keyword.trim()); };

  const onSort = (key) => {
    setSortState((prev) => nextSortState(prev, key));
  };

  const sortedItems = sortRows(
    rows.items,
    sortState,
    (row, key) => getRowCellValue(row, key, { schema, columns: candidateCols })
  );

  const toggleCol = (colKey, checked) => {
    const currentKeys = visibleCols.map((c) => (c.key !== undefined && c.key !== null ? String(c.key) : String(c.index)));
    let nextKeys;
    if (checked) {
      nextKeys = Array.from(new Set([...currentKeys, String(colKey)]));
    } else {
      nextKeys = currentKeys.filter((k) => k !== String(colKey));
    }
    const nextPrefs = { visibleKeys: nextKeys };
    setColPrefs(nextPrefs);
    saveColumnPreferences(formKey, nextPrefs);
  };

  const resetColumns = () => {
    setColPrefs(null);
    saveColumnPreferences(formKey, null);
  };

  const selectAllColumns = () => {
    const allKeys = candidateCols.map((c) => (c.key !== undefined && c.key !== null ? String(c.key) : String(c.index)));
    const nextPrefs = { visibleKeys: allKeys };
    setColPrefs(nextPrefs);
    saveColumnPreferences(formKey, nextPrefs);
  };

  const onCopy = async (e, text, rowKey) => {
    e.stopPropagation();
    const ok = await copyTextToClipboard(text);
    if (ok) {
      setCopiedKey(rowKey);
      clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopiedKey(null), 1500);
    }
  };

  const serialCol = findSerialNumberColumn(schema);
  const serialColKey = serialCol ? (serialCol.key !== undefined && serialCol.key !== null ? String(serialCol.key) : String(serialCol.index)) : null;

  return html`<section class="ds-card">
    <div class="ds-card-head">
      <h3>单据</h3>
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
        <form class="ds-search" onSubmit=${search}>
          <input type="search" value=${keyword} onInput=${(e) => setKeyword(e.currentTarget.value)} placeholder="搜单号、零件名称、申请人" aria-label="搜索单据" />
          <button type="submit" class="vk-btn">搜索</button>
          <label class="ds-check"><input type="checkbox" checked=${onlyOverdue} onChange=${() => { setLimit(PAGE_SIZE); setOnlyOverdue(!onlyOverdue); }} />只看逾期</label>
        </form>
        <div style="position:relative;display:inline-block">
          <button
            type="button"
            class="vk-btn grid-column-btn"
            aria-haspopup="true"
            aria-expanded=${colPickerOpen ? "true" : "false"}
            onClick=${() => setColPickerOpen(!colPickerOpen)}
          >列显隐</button>
          ${colPickerOpen && html`
            <div class="grid-column-panel" style="position:absolute;top:calc(100% + 4px);right:0;z-index:60;width:220px;max-height:300px;overflow-y:auto;background:var(--canvas,#ffffff);border:1px solid var(--hairline,#d0d7de);border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.12);padding:8px;">
              <div class="grid-column-quick" style="display:flex;gap:6px;margin-bottom:8px;">
                <button type="button" class="vk-btn grid-quick-btn" style="flex:1;font-size:12px;padding:3px 6px" onClick=${resetColumns}>默认列</button>
                <button type="button" class="vk-btn grid-quick-btn" style="flex:1;font-size:12px;padding:3px 6px" onClick=${selectAllColumns}>全部列</button>
              </div>
              <div class="grid-column-list" style="display:flex;flex-direction:column;gap:4px;">
                ${candidateCols.map((col) => {
                  const colKey = col.key !== undefined && col.key !== null ? String(col.key) : String(col.index);
                  const checked = visibleCols.some((vc) => (vc.key !== undefined && vc.key !== null ? String(vc.key) : String(vc.index)) === colKey);
                  return html`<label key=${colKey} class="grid-column-item" style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;">
                    <input type="checkbox" checked=${checked} onChange=${(e) => toggleCol(colKey, e.currentTarget.checked)} />
                    <span>${col.label}</span>
                  </label>`;
                })}
              </div>
            </div>
          `}
        </div>
      </div>
    </div>
    ${error && html`<p class="ds-error" role="alert">读取单据失败：${error}</p>`}
    ${!error && sortedItems.length > 0 && html`<div class="ds-table-wrap"><table class="ds-table">
      <thead><tr>
        ${visibleCols.map((c) => {
          const colKey = c.key !== undefined && c.key !== null ? String(c.key) : String(c.index);
          const isSorted = sortState.key === colKey;
          const arrow = isSorted ? (sortState.direction === "asc" ? " ▲" : " ▼") : "";
          return html`<th
            key=${c.key}
            class="grid-sortable"
            style="cursor:pointer;user-select:none"
            title="点击排序"
            aria-sort=${isSorted ? (sortState.direction === "asc" ? "ascending" : "descending") : "none"}
            onClick=${() => onSort(colKey)}
          >${c.label}${arrow}</th>`;
        })}
        <th
          class="grid-sortable"
          style="cursor:pointer;user-select:none"
          title="点击排序"
          aria-sort=${sortState.key === "stage" ? (sortState.direction === "asc" ? "ascending" : "descending") : "none"}
          onClick=${() => onSort("stage")}
        >阶段${sortState.key === "stage" ? (sortState.direction === "asc" ? " ▲" : " ▼") : ""}</th>
        <th
          class="grid-sortable"
          style="cursor:pointer;user-select:none"
          title="点击排序"
          aria-sort=${sortState.key === "overdue" ? (sortState.direction === "asc" ? "ascending" : "descending") : "none"}
          onClick=${() => onSort("overdue")}
        >逾期${sortState.key === "overdue" ? (sortState.direction === "asc" ? " ▲" : " ▼") : ""}</th>
      </tr></thead>
      <tbody>${sortedItems.map((row) => {
        const values = Array.isArray(row.values) ? row.values : [];
        const overdue = overdueLabel(row);
        const serialNum = extractSerialNumber(row, schema);
        return html`<tr key=${row.rowKey}>
          ${visibleCols.map((c) => {
            const colKey = c.key !== undefined && c.key !== null ? String(c.key) : String(c.index);
            const isSerial = serialNum && (colKey === serialColKey || (!serialColKey && c === visibleCols[0]));
            if (isSerial) {
              return html`<td key=${c.key}>
                <span style="display:inline-flex;align-items:center;gap:6px">
                  <span>${cell(values[c.index])}</span>
                  <button
                    type="button"
                    class="vk-btn"
                    style="padding:1px 6px;font-size:11px;line-height:1.4"
                    title="复制单号"
                    aria-label=${`复制单号 ${serialNum}`}
                    onClick=${(e) => onCopy(e, serialNum, row.rowKey)}
                  >${copiedKey === row.rowKey ? "已复制" : "复制"}</button>
                </span>
              </td>`;
            }
            return html`<td key=${c.key}>${cell(values[c.index])}</td>`;
          })}
          <td><span class=${`ds-pill is-${row.isCompleted ? "ok" : "info"}`}>${row.isCompleted ? "已完成" : safeDisplayValue(stageLabel(schema, row) || "进行中")}</span></td>
          <td>${overdue === "是" ? html`<span class="ds-pill is-bad">是</span>` : overdue}</td>
        </tr>`;
      })}</tbody>
    </table></div>`}
    ${!error && !loading && !rows.items.length && html`<p class="ds-muted">${applied || onlyOverdue ? "没有符合条件的单据。" : "还没有单据数据，开启自动同步或点「立即同步」后会出现。"}</p>`}
    <div class="ds-foot"><span class="ds-muted">${loading ? "读取中…" : !rows.total ? "" : `共 ${rows.total} 条${rows.items.length < rows.total ? `，已显示 ${rows.items.length} 条` : ""}`}</span>
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
  // 进度读派生字段（快照态 = 明细 completed/total 换算），回退手工值；
  // null 表示没有可信数值，显示「—」而不是编造 0%。
  const progress = progressDisplay(item);
  const late = item.scheduleState === "overdue";
  // 聚合同步不写负责人/计划完成（记录集禁止映射单值字段），标注「手工」避免误以为同步会改。
  const plannedManual = policy.aggregate === true;

  const syncNow = async () => {
    setSyncing("正在同步…");
    try {
      const data = await apiRequest(`/api/project-status/deliverables/${enc(item.id)}/sync-now`, { method: "POST" });
      setSyncing(syncResultText(data));
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
        <p class="ds-muted">计划完成 ${item.plannedDate || "未设置"}${item.plannedDate && plannedManual ? "（手工）" : ""}
          ${late ? html` · <b class="ds-bad">逾期 ${item.scheduleDays} 天</b>` : ""}</p>
        <div class="ds-progress"><i style=${`width:${progress.value === null ? 0 : progress.value}%`} class=${late ? "is-bad" : progress.value !== null && progress.value >= 100 ? "is-ok" : ""}></i></div>
        <p class="ds-muted">${progress.text} · ${safeDisplayValue(item.effectiveStatus || item.status || "")}${progress.derived ? " · 由明细派生" : ""}</p>
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
