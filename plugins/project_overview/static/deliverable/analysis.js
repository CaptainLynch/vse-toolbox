// Detail analysis panel (legacy loadDeliverableAnalysis /
// renderDeliverableAnalysis): summary metrics, department chart + custom
// label charts with the chart-content editor, trend chart and table, and the
// paged item list with multi-select filters.
import { html, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { apiRequest, enc } from "./api.js";
import {
  analysisTrendGeometry,
  buildChartLabelsPayload,
  chartFieldOptions,
  chartLabelBlocks,
  customChartTotals,
  departmentBars,
} from "./chart-math.js";
import { isEwoSource } from "./display.js";
import { archiveFormatDate, formatApiErrorMessage, safeDisplayValue } from "./format.js";
import { SearchMultiSelect } from "./multi-select.js";

export function DeptDoneChart({ summary, departments, selected, onSelect, title, emptyText = "暂无科室完成情况统计" }) {
  const model = departmentBars(summary, departments);
  const header = html`<div class="analysis-dept-chart-header">
    <h6 class="analysis-sub-title">${title || "按科室完成情况（已完成 / 未完成）"}</h6>
    <div class="analysis-chart-legend">
      <span class="analysis-chart-legend-item is-completed">已完成</span>
      <span class="analysis-chart-legend-item is-incomplete">未完成</span>
    </div>
  </div>`;
  if (model.empty) {
    return html`<div class="analysis-sub-section">${header}<p class="analysis-empty-note is-empty">${emptyText}</p></div>`;
  }
  const current = selected || null;
  const keyActivate = (fn) => (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      fn();
    }
  };
  const bar = (row, name, isOverall) => html`
    <span class="analysis-dept-bar-name" title=${name}>${isOverall ? name : safeDisplayValue(name)}</span>
    <div class="analysis-dept-bar-track">
      <div class="analysis-dept-bar-fill is-completed" style=${{ width: `${row.completedPct}%` }}></div>
      <div class="analysis-dept-bar-fill is-incomplete" style=${{ width: `${row.incompletePct}%` }}></div>
    </div>
    <span class="analysis-dept-bar-nums">
      <span class="analysis-dept-bar-num is-completed">已完成 ${row.completed}</span>
      <span class="analysis-dept-bar-num is-incomplete">未完成 ${row.incomplete}</span>
      <span class="analysis-dept-bar-num is-total">共 ${row.total}</span>
    </span>`;
  const selectOverall = () => {
    if (current !== null && onSelect) onSelect(null);
  };
  return html`<div class="analysis-sub-section">
    ${header}
    <div class="analysis-dept-bars-box">
      <div
        class=${`analysis-dept-bar-row is-overall${current === null ? " is-selected" : ""}`}
        role="button" tabindex="0" aria-pressed="false"
        aria-label=${`整体: 已完成 ${model.overall.completed}, 未完成 ${model.overall.incomplete}, 共 ${model.overall.total}`}
        onClick=${selectOverall}
        onKeyDown=${keyActivate(selectOverall)}
      >${bar(model.overall, "整体", true)}</div>
      ${model.rows.map((row) => {
        const isSelected = current === row.name;
        const choose = () => onSelect && onSelect(isSelected ? null : row.name);
        return html`<div
          key=${row.name}
          class=${`analysis-dept-bar-row${isSelected ? " is-selected" : ""}`}
          role="button" tabindex="0" aria-pressed=${isSelected ? "true" : "false"}
          data-department=${row.name}
          aria-label=${`${row.name}: 已完成 ${row.completed}, 未完成 ${row.incomplete}, 共 ${row.total}`}
          onClick=${onSelect ? choose : null}
          onKeyDown=${onSelect ? keyActivate(choose) : null}
        >${bar(row, row.name, false)}</div>`;
      })}
    </div>
  </div>`;
}

export function AnalysisTrendChart({ trend }) {
  const g = analysisTrendGeometry(trend);
  return html`<div class="analysis-trend-chart-wrap">
    <svg class="trend-chart-svg" viewBox="0 0 620 220" role="img" aria-label="交付物历史趋势图表">
      <title>交付物历史趋势图表</title>
      <desc>展示快照历史中已完成与未完成任务数量变化趋势</desc>
      ${g.grid.map((line, index) => html`<g key=${`grid-${index}`}>
        <line x1=${g.padding.left} y1=${line.y} x2=${g.padding.left + g.plotWidth} y2=${line.y}
          stroke="var(--hairline, #e5e7eb)" stroke-width="1" stroke-dasharray=${line.dashed ? "2,2" : "none"} />
        <text x=${g.padding.left - 8} y=${line.y + 4} text-anchor="end" font-size="10" fill="var(--muted, #6b7280)">${line.label}</text>
      </g>`)}
      ${g.completed.length > 0 && html`<polyline fill="none" stroke="var(--success, #10b981)" stroke-width="2.5"
        stroke-linecap="round" stroke-linejoin="round" points=${g.completedLine} />`}
      ${g.incomplete.length > 0 && html`<polyline fill="none" stroke="var(--warning, #f59e0b)" stroke-width="2.5"
        stroke-linecap="round" stroke-linejoin="round" points=${g.incompleteLine} />`}
      ${g.completed.map((p, index) => html`<g key=${`c-${index}`}>
        <circle cx=${p.x.toFixed(1)} cy=${p.y.toFixed(1)} r="4" fill="var(--success, #10b981)" />
        <text x=${p.x.toFixed(1)} y=${(p.y - 8).toFixed(1)} text-anchor="middle" font-size="11" font-weight="600" fill="var(--success, #10b981)">已完成: ${p.val}</text>
        <text x=${p.x.toFixed(1)} y=${g.axisY} text-anchor="middle" font-size="10" fill="var(--muted, #6b7280)">${archiveFormatDate(p.date)}</text>
      </g>`)}
      ${g.incomplete.map((p, index) => html`<g key=${`i-${index}`}>
        <circle cx=${p.x.toFixed(1)} cy=${p.y.toFixed(1)} r="4" fill="var(--warning, #f59e0b)" />
        <text x=${p.x.toFixed(1)} y=${(p.y + 16).toFixed(1)} text-anchor="middle" font-size="11" font-weight="600" fill="var(--warning, #f59e0b)">未完成: ${p.val}</text>
      </g>`)}
    </svg>
  </div>`;
}

const UNMATCHED_OPTIONS = [
  ["keep", "未匹配保留原样"],
  ["other", "未匹配并入未分组"],
  ["hide", "未匹配从图表隐藏"],
];

export function ChartLabelEditor({ itemId, labels, fieldOptions, onSaved, onCancel }) {
  const [blocks, setBlocks] = useState(() => chartLabelBlocks(labels, fieldOptions));
  const [status, setStatus] = useState({ text: "", error: false });
  const [saving, setSaving] = useState(false);
  const firstField = fieldOptions.length ? fieldOptions[0][0] : "";

  const update = (index, patch) => setBlocks((prev) => prev.map((block, i) => (i === index ? { ...block, ...patch } : block)));
  const updateRule = (index, ruleIndex, patch) => setBlocks((prev) => prev.map((block, i) => (i !== index ? block : {
    ...block,
    groups: block.groups.map((rule, r) => (r === ruleIndex ? { ...rule, ...patch } : rule)),
  })));

  const save = async () => {
    setSaving(true);
    setStatus({ text: "正在保存图表设置...", error: false });
    try {
      await apiRequest(`/api/project-status/deliverables/${enc(itemId)}/chart-labels`, {
        method: "PUT",
        body: buildChartLabelsPayload(blocks),
      });
      if (onSaved) onSaved();
    } catch (err) {
      setStatus({ text: err instanceof Error ? err.message : String(err), error: true });
      setSaving(false);
    }
  };

  return html`<div class="chart-labels-editor">
    <div class="chart-label-rows">
      ${blocks.map((block, index) => html`<div class="chart-label-block" key=${index}>
        <div class="chart-label-row">
          <input class="chart-label-name" type="text" maxlength="40" placeholder="标签名称，如 内容A" aria-label="图表标签名称"
            value=${block.label} onInput=${(e) => update(index, { label: e.currentTarget.value })} />
          <select class="chart-label-field-select" aria-label="绑定字段" value=${block.sourceField}
            onChange=${(e) => update(index, { sourceField: e.currentTarget.value })}>
            ${fieldOptions.map(([key, display]) => html`<option key=${key} value=${key}>${display}</option>`)}
          </select>
          <button type="button" class="chart-label-groups-toggle" aria-expanded=${block.open ? "true" : "false"}
            onClick=${() => update(index, { open: !block.open })}>${block.open ? "收起分组" : "配置分组"}</button>
          <button type="button" class="chart-label-remove" aria-label="移除该标签"
            onClick=${() => setBlocks((prev) => prev.filter((_, i) => i !== index))}>移除</button>
        </div>
        <div class="chart-label-groups" hidden=${!block.open}>
          ${block.groups.map((rule, ruleIndex) => html`<div class="chart-group-rule" key=${ruleIndex}>
            <input class="chart-group-name" type="text" maxlength="40" placeholder="组名，如 内饰科" aria-label="分组名称"
              value=${rule.name} onInput=${(e) => updateRule(index, ruleIndex, { name: e.currentTarget.value })} />
            <input class="chart-group-members" type="text" placeholder="成员用逗号分隔，如 内饰科,内饰工程科" aria-label="分组成员"
              value=${rule.members} onInput=${(e) => updateRule(index, ruleIndex, { members: e.currentTarget.value })} />
            <button type="button" class="chart-group-rule-remove" aria-label="移除该分组"
              onClick=${() => update(index, { groups: block.groups.filter((_, r) => r !== ruleIndex) })}>移除</button>
          </div>`)}
          <button type="button" class="chart-group-add-btn"
            onClick=${() => update(index, { groups: [...block.groups, { name: "", members: "" }] })}>添加分组</button>
          <select class="chart-label-unmatched" aria-label="未匹配值处理" value=${block.unmatched}
            onChange=${(e) => update(index, { unmatched: e.currentTarget.value })}>
            ${UNMATCHED_OPTIONS.map(([value, text]) => html`<option key=${value} value=${value}>${text}</option>`)}
          </select>
        </div>
      </div>`)}
    </div>
    <button type="button" class="chart-label-add-btn"
      onClick=${() => setBlocks((prev) => [...prev, { label: "", sourceField: firstField, groups: [], unmatched: "keep", open: false }])}>添加标签</button>
    <button type="button" class="chart-labels-save-btn" disabled=${saving} onClick=${save}>保存图表设置</button>
    <button type="button" class="chart-labels-cancel-btn" onClick=${onCancel}>取消</button>
    <p class=${`chart-labels-status${status.error ? " is-error" : ""}`} role="status">${status.text}</p>
  </div>`;
}

function ChartArea({ item, summary, departments, customCharts, selectedDept, onSelectDept, onReload }) {
  const [activeTab, setActiveTab] = useState(0);
  const [editor, setEditor] = useState({ open: false, loading: false, data: null, error: "" });

  const toggleEditor = async () => {
    if (editor.open) {
      setEditor((prev) => ({ ...prev, open: false }));
      return;
    }
    setEditor((prev) => ({ ...prev, loading: true }));
    try {
      const data = (await apiRequest(`/api/project-status/deliverables/${enc(item.id)}/chart-labels`)) || {};
      setEditor({ open: true, loading: false, data, error: "", seq: Date.now() });
    } catch (err) {
      setEditor({ open: true, loading: false, data: null, error: formatApiErrorMessage(err, 500) });
    }
  };

  const deptChart = html`<${DeptDoneChart} summary=${summary} departments=${departments} selected=${selectedDept} onSelect=${onSelectDept} />`;
  const entries = [
    { label: "科室", render: () => deptChart },
    ...customCharts.map((chart) => ({
      label: chart.label,
      render: () => html`<${DeptDoneChart}
        summary=${customChartTotals(chart)}
        departments=${chart && chart.groups && typeof chart.groups === "object" ? chart.groups : {}}
        title=${`按「${safeDisplayValue(chart && chart.label)}」分组（已完成 / 未完成）`}
      />`,
    })),
  ];
  const tab = Math.min(activeTab, entries.length - 1);

  return html`
    <div class="analysis-chart-tools">
      <button type="button" class="analysis-chart-settings-btn" aria-label="设置图表展示内容" disabled=${editor.loading} onClick=${toggleEditor}>图表内容设置</button>
      ${editor.open && (editor.error
        ? html`<div class="chart-labels-editor"><p class="error-msg">${editor.error}</p></div>`
        : html`<${ChartLabelEditor}
            key=${editor.seq}
            itemId=${item.id}
            labels=${Array.isArray(editor.data && editor.data.labels) ? editor.data.labels : []}
            fieldOptions=${chartFieldOptions(editor.data && editor.data.fields)}
            onSaved=${() => { setEditor((prev) => ({ ...prev, open: false })); onReload(); }}
            onCancel=${() => setEditor((prev) => ({ ...prev, open: false }))}
          />`)}
    </div>
    ${customCharts.length === 0 ? deptChart : html`<div class="analysis-chart-area">
      <div class="analysis-chart-tabs">
        ${entries.map((entry, index) => html`<button
          type="button" key=${index}
          class=${`analysis-chart-tab${index === tab ? " is-active" : ""}`}
          aria-pressed=${index === tab ? "true" : "false"}
          onClick=${() => setActiveTab(index)}
        >${safeDisplayValue(entry.label)}</button>`)}
      </div>
      <div class="analysis-chart-panel">${entries[tab].render()}</div>
    </div>`}`;
}

const STAGE_OPTIONS = [
  ["all", "全部阶段（含 OPEN/未知）"],
  ["open", "OPEN（未纳入统计）"],
  ["draft1", "DRAFT1"],
  ["draft2", "DRAFT2"],
  ["edit1", "EDIT1"],
  ["edit2", "EDIT2"],
  ["proc", "PROC"],
  ["impl", "IMPL"],
  ["close", "CLOSE（已关闭）"],
];
const CANONICAL_STAGES = new Set(STAGE_OPTIONS.map(([value]) => value));
const EWO_DEFAULT_DEPARTMENTS = ["车身科", "车体科", "外饰科", "内饰科", "车体架构集成科"];
const PAGE_SIZE = 50;

export function formatEwoStageLabel(stage) {
  return String(stage || "").trim().toUpperCase();
}

function stageChip(it) {
  if (it.stage) {
    const cls = it.stage === "close" ? "is-closed" : it.stage === "open" ? "is-open" : "is-active";
    return html`<span class=${`analysis-stage-chip ${cls}`}>${safeDisplayValue(formatEwoStageLabel(it.stage))}</span>`;
  }
  if (it.stageAttention) return html`<span class="analysis-stage-chip is-unknown" title="来源阶段未识别，默认不计入统计">未知阶段</span>`;
  return html`<span class="analysis-stage-chip is-none">—</span>`;
}

function alertCell(it) {
  let label = "—";
  let cls = "";
  if (it.alertType === "overdue") {
    label = `逾期 ${it.days ?? ""}天`;
    cls = "analysis-alert-cell is-overdue";
  } else if (it.alertType === "due_soon") {
    label = `${it.days ?? ""}天后到期`;
    cls = "analysis-alert-cell is-due-soon";
  } else if (it.alertType === "missing_due_date") {
    label = "缺少截止日期";
    cls = "analysis-alert-cell is-warning";
  }
  return html`<td class=${cls || null}>${label}</td>`;
}

function SignersCell({ value }) {
  const lines = String(value || "").split("\n").map((line) => line.trim()).filter(Boolean);
  if (!lines.length) return html`<td class="analysis-signers-cell"><span class="analysis-signers-empty">无</span></td>`;
  return html`<td class="analysis-signers-cell" title=${lines.map((line) => safeDisplayValue(line)).join("\n")}>
    ${lines.map((line, index) => html`<div class="analysis-signer-line" key=${index}>${safeDisplayValue(line)}</div>`)}
  </td>`;
}

/**
 * Paged item list. `chartSelect` = {dept, seq}: a department picked on the
 * chart replaces the department filter and reloads page 1.
 */
export function AnalysisItems({ item, departments, modelFilter, onModelFilterApply, chartSelect, onDeptChange }) {
  const ewo = isEwoSource(item);
  const deptNames = Array.from(new Set([...(ewo ? EWO_DEFAULT_DEPARTMENTS : []), ...Object.keys(departments || {})]))
    .sort((a, b) => a.localeCompare(b, "zh-CN"));
  const [draft, setDraft] = useState({ departments: [], stages: [], state: "all", model: modelFilter.model, match: modelFilter.match });
  const [applied, setApplied] = useState({ departments: [], stages: [], state: "all", page: 1 });
  const [dirty, setDirty] = useState(false);
  const [result, setResult] = useState({ loading: true, error: "", items: [], total: 0 });
  const seq = useRef(0);

  useEffect(() => {
    if (!chartSelect || chartSelect.seq === 0) return;
    const list = chartSelect.dept ? [chartSelect.dept] : [];
    setDraft((prev) => ({ ...prev, departments: list }));
    setApplied((prev) => ({ ...prev, departments: list, page: 1 }));
  }, [chartSelect && chartSelect.seq]);

  useEffect(() => {
    const current = ++seq.current;
    setResult((prev) => ({ ...prev, loading: true, error: "" }));
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String((applied.page - 1) * PAGE_SIZE) });
    applied.departments.forEach((department) => params.append("departments", department));
    if (applied.state && applied.state !== "all") params.set("state", applied.state);
    applied.stages.forEach((stage) => params.append("stages", stage));
    if (modelFilter.model) {
      params.set("model", modelFilter.model);
      params.set("modelMatch", modelFilter.match);
    }
    apiRequest(`/api/project-status/deliverables/${enc(item.id)}/analysis/items?${params.toString()}`)
      .then((data) => {
        if (current !== seq.current) return;
        const body = data || { items: [], total: 0 };
        const total = Number(body.total) || 0;
        const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
        if (applied.page > totalPages) {
          setApplied((prev) => ({ ...prev, page: totalPages }));
          return;
        }
        setResult({ loading: false, error: "", items: Array.isArray(body.items) ? body.items : [], total, loadedOnce: true });
      })
      .catch((err) => {
        if (current !== seq.current) return;
        setResult((prev) => ({ ...prev, loading: false, error: formatApiErrorMessage(err, 500) }));
      });
  }, [item.id, applied, modelFilter.model, modelFilter.match]);

  const markDirty = () => setDirty(true);
  const totalPages = Math.max(1, Math.ceil(result.total / PAGE_SIZE));

  const apply = () => {
    setDirty(false);
    const nextModel = ewo ? draft.model.trim() : modelFilter.model;
    const nextMatch = ewo ? draft.match : modelFilter.match;
    if (nextModel !== modelFilter.model || nextMatch !== modelFilter.match) {
      // 车型筛选变化时重载整个分析面板，统计摘要/图表与明细保持同口径。
      onModelFilterApply({ model: nextModel, match: nextMatch });
      return;
    }
    setApplied({ departments: draft.departments, stages: draft.stages, state: draft.state, page: 1 });
  };
  const clear = () => {
    const hadModel = Boolean(modelFilter.model) || modelFilter.match !== "fuzzy";
    setDraft({ departments: [], stages: [], state: "all", model: "", match: "fuzzy" });
    setDirty(false);
    if (onDeptChange) onDeptChange(null);
    if (hadModel) {
      onModelFilterApply({ model: "", match: "fuzzy" });
      return;
    }
    setApplied({ departments: [], stages: [], state: "all", page: 1 });
  };

  const colSpanRow = (cls, text) => html`<tr><td class=${cls} colspan="9" style=${{ textAlign: "center", padding: "20px" }}>${text}</td></tr>`;
  let body;
  if (result.loading) body = colSpanRow("analysis-empty-note", "加载明细任务中...");
  else if (result.error) body = colSpanRow("analysis-empty-note is-error", result.error);
  else if (!result.items.length) body = colSpanRow("analysis-empty-note is-empty", "暂无明细任务记录");
  else {
    body = result.items.map((it, index) => {
      const isOverdue = it.alertType === "overdue";
      return html`<tr key=${index}>
        <td>${safeDisplayValue(it.itemNumber || "未提供")}</td>
        <td>${safeDisplayValue(it.title)}</td>
        <td>${safeDisplayValue(it.department)}</td>
        <td>${safeDisplayValue(it.owner)}</td>
        <td>${stageChip(it)}</td>
        <td><span class=${`analysis-status-chip ${isOverdue ? "is-overdue" : "is-normal"}`}>${isOverdue ? "超期" : "未超期"}</span></td>
        <${SignersCell} value=${it.pendingSigners} />
        <td>${safeDisplayValue(it.plannedDate)}</td>
        ${alertCell(it)}
      </tr>`;
    });
  }
  const shownTotal = result.total;

  return html`<div class="analysis-sub-section">
    <h6 class="analysis-sub-title">${result.loadedOnce ? `明细任务清单 (共 ${shownTotal} 条)` : "明细任务清单"}</h6>
    <div class="analysis-items-toolbar">
      <${SearchMultiSelect}
        ariaLabel="按科室筛选"
        placeholder="全部科室—搜索或输入后按 Enter"
        options=${deptNames}
        values=${draft.departments}
        onChange=${(values) => {
          setDraft((prev) => ({ ...prev, departments: values }));
          markDirty();
          if (onDeptChange) onDeptChange(values.length === 1 ? values[0] : null);
        }}
      />
      <${SearchMultiSelect}
        ariaLabel="按流程阶段筛选"
        placeholder="有效阶段（排除 OPEN）—搜索或输入后按 Enter"
        options=${STAGE_OPTIONS}
        values=${draft.stages}
        normalizeValue=${(value) => {
          const normalized = String(value || "").trim().toLowerCase();
          return CANONICAL_STAGES.has(normalized) ? normalized : "";
        }}
        labelFor=${formatEwoStageLabel}
        onChange=${(values) => { setDraft((prev) => ({ ...prev, stages: values })); markDirty(); }}
      />
      ${ewo && html`<div class="analysis-model-filter">
        <input class="analysis-model-input" type="text" maxlength="80" placeholder="车型查找，如 F610S" aria-label="按车型查找"
          value=${draft.model} onInput=${(e) => { const value = e.currentTarget.value; setDraft((prev) => ({ ...prev, model: value })); }} />
        <div class="analysis-model-match">
          ${[["fuzzy", "模糊"], ["exact", "精确"]].map(([value, label]) => html`<button
            type="button" key=${value} data-match=${value}
            class=${`analysis-model-match-btn${draft.match === value ? " is-active" : ""}`}
            aria-pressed=${draft.match === value ? "true" : "false"}
            onClick=${() => setDraft((prev) => ({ ...prev, match: value }))}
          >${label}</button>`)}
        </div>
      </div>`}
      <select class="analysis-select" aria-label="按完成状态筛选" value=${draft.state}
        onChange=${(e) => { const value = e.currentTarget.value; setDraft((prev) => ({ ...prev, state: value })); markDirty(); }}>
        <option value="all">全部状态</option>
        <option value="completed">仅已完成</option>
        <option value="incomplete">仅未完成</option>
      </select>
      <button type="button" class=${`btn is-primary analysis-filter-apply${dirty ? " is-attention" : ""}`}
        aria-label="应用科室和流程阶段筛选" onClick=${apply}>应用筛选</button>
      <button type="button" class="btn is-secondary analysis-filter-clear" aria-label="清除科室和流程阶段筛选" onClick=${clear}>清除筛选</button>
      <div class="analysis-toolbar-spacer"></div>
      <div class="analysis-items-pager">
        <span class="analysis-pager-info">共 ${shownTotal} 条 · 第 ${applied.page} / ${totalPages} 页</span>
        <button type="button" class="btn is-secondary analysis-pager-btn" disabled=${applied.page <= 1}
          onClick=${() => setApplied((prev) => ({ ...prev, page: prev.page - 1 }))}>上一页</button>
        <button type="button" class="btn is-secondary analysis-pager-btn"
          disabled=${applied.page >= totalPages || result.total === 0}
          onClick=${() => setApplied((prev) => ({ ...prev, page: prev.page + 1 }))}>下一页</button>
      </div>
    </div>
    <div class="overview-table-wrap">
      <table class="analysis-items-table">
        <thead><tr>${["编号", "名称", "科室", "负责人", "阶段", "状态", "待签署人员", "申请日期", "提醒"].map((col) => html`<th key=${col}>${col}</th>`)}</tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>
  </div>`;
}

export function AnalysisActionBar({ item, supported, readiness, feedback, busy, onRefresh, onSync, onBlocked }) {
  const ready = Boolean(readiness && readiness.ready);
  const message = (readiness && readiness.message) || "同步条件尚未满足";
  const blockedText = supported ? `暂不能同步：${message}` : "该交付物不支持外部同步";
  let status = feedback && feedback.text && !feedback.text.startsWith("暂不能同步：") ? feedback : null;
  if (!status && (!ready || !supported)) status = { text: blockedText, tone: "warning" };
  if (!status && feedback && feedback.text && !ready) status = feedback;
  return html`<div class="evidence-sync-bar analysis-action-bar" aria-label=${`${safeDisplayValue(item.name)} 分析操作`}>
    <strong class="analysis-action-label">分析操作</strong>
    <button type="button" class="evidence-retry-btn analysis-refresh-btn" disabled=${busy} onClick=${onRefresh}>刷新分析</button>
    <button
      type="button"
      class="evidence-sync-btn analysis-sync-btn"
      data-deliverable-id=${item.id}
      disabled=${busy || !supported || !ready}
      title=${ready && supported ? "" : `不可同步：${supported ? message : "该交付物不支持外部同步"}`}
      onClick=${() => {
        if (!ready || !supported) {
          if (onBlocked) onBlocked(blockedText);
          return;
        }
        onSync();
      }}
    >运行后台同步</button>
    <span class=${`evidence-sync-status analysis-sync-status${status && status.tone ? ` is-${status.tone}` : ""}`} role="status" aria-live="polite">${status ? status.text : ""}</span>
  </div>`;
}

/**
 * Analysis panel. `ctl.current.reload()` re-reads the analysis and resolves
 * to true/false like the legacy loadDeliverableAnalysis.
 */
export function AnalysisPanel({ item, version, ctl, modelFilter, setModelFilter, actionBar, onAnalysisData, onLoadError }) {
  const [state, setState] = useState({ loading: true, error: null, data: null, seq: 0 });
  const [chartDept, setChartDept] = useState(null);
  const [chartSelect, setChartSelect] = useState({ dept: null, seq: 0 });
  const reqSeq = useRef(0);

  const load = async () => {
    const current = ++reqSeq.current;
    setState((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const params = new URLSearchParams();
      if (modelFilter.model) {
        params.set("model", modelFilter.model);
        params.set("modelMatch", modelFilter.match);
      }
      const query = params.toString();
      const data = (await apiRequest(`/api/project-status/deliverables/${enc(item.id)}/analysis${query ? `?${query}` : ""}`)) || {};
      if (current !== reqSeq.current) return false;
      if (onAnalysisData) onAnalysisData(data);
      setChartDept(null);
      setChartSelect({ dept: null, seq: 0 });
      setState({ loading: false, error: null, data, seq: current });
      return true;
    } catch (err) {
      if (current !== reqSeq.current) return false;
      const message = formatApiErrorMessage(err, 500);
      setState({ loading: false, error: message, data: null, seq: current });
      if (onLoadError) onLoadError(message);
      return false;
    }
  };
  if (ctl) ctl.current = { reload: load };

  useEffect(() => { load(); }, [item.id, version, modelFilter.model, modelFilter.match]);

  if (state.loading) {
    return html`<p class="loading" role="status" aria-live="polite">加载交付物分析与明细...</p>`;
  }
  if (state.error) {
    return html`<div class="error-msg" role="alert" aria-live="assertive">${state.error}</div>`;
  }
  const data = state.data || {};
  const summary = data.summary || { total: 0, completed: 0, incomplete: 0, overdue: 0, dueSoon: 0, missingDueDate: 0 };
  const departments = data.departments || {};
  const trend = Array.isArray(data.trend) ? data.trend : [];
  const customCharts = Array.isArray(data.customCharts) ? data.customCharts : [];
  const overdue = summary.overdue ?? 0;
  const dueSoon = summary.dueSoon ?? 0;
  const missing = summary.missingDueDate ?? 0;

  const head = html`<div class="analysis-panel-head">
    <div>
      <p class="eyebrow">交付物分析</p>
      <h5 class="analysis-title">${item.name} 各科室完成情况</h5>
    </div>
    <span class="analysis-snapshot-time">${data.snapshotAt ? `快照时间: ${archiveFormatDate(data.snapshotAt)}` : "暂无分析快照"}</span>
  </div>`;

  if (!data.hasCache) {
    return html`${head}${actionBar}
      <p class="analysis-empty-note is-empty">暂无分析缓存数据（等待定时同步或首次抓取分析）</p>`;
  }

  return html`${head}${actionBar}
    <div class="analysis-summary-grid">
      ${[["总任务数", summary.total ?? 0], ["已完成", summary.completed ?? 0], ["未完成", summary.incomplete ?? 0]].map(([label, value]) => html`
        <div class="analysis-metric-card" key=${label}>
          <span class="analysis-metric-label">${label}</span>
          <strong class="analysis-metric-val">${String(value)}</strong>
        </div>`)}
      <div class="analysis-alerts-box">
        ${overdue > 0 && html`<span class="analysis-alert-chip is-overdue">逾期 ${overdue} 项</span>`}
        ${dueSoon > 0 && html`<span class="analysis-alert-chip is-due-soon">即将到期 ${dueSoon} 项</span>`}
        ${missing > 0 && html`<span class="analysis-alert-chip is-warning">缺少截止日期 ${missing} 项</span>`}
        ${overdue === 0 && dueSoon === 0 && missing === 0 && html`<span class="analysis-alert-chip is-normal">无逾期风险</span>`}
      </div>
    </div>
    <${ChartArea}
      key=${state.seq}
      item=${item}
      summary=${summary}
      departments=${departments}
      customCharts=${customCharts}
      selectedDept=${chartDept}
      onSelectDept=${(dept) => {
        setChartDept(dept);
        setChartSelect((prev) => ({ dept, seq: prev.seq + 1 }));
      }}
      onReload=${load}
    />
    <div class="analysis-sub-section">
      <h6 class="analysis-sub-title">历史趋势记录</h6>
      ${trend.length === 0
        ? html`<p class="analysis-empty-note is-empty">暂无历史趋势记录</p>`
        : html`<${AnalysisTrendChart} trend=${trend} />
          <table class="analysis-trend-table">
            <thead><tr>${["快照时间", "总任务数", "已完成", "未完成", "逾期", "即将到期"].map((col) => html`<th key=${col}>${col}</th>`)}</tr></thead>
            <tbody>
              ${trend.map((t, index) => html`<tr key=${index}>
                <td>${archiveFormatDate(t.snapshotAt)}</td>
                <td>${String(t.total ?? 0)}</td>
                <td>${String(t.completed ?? 0)}</td>
                <td>${String(t.incomplete ?? 0)}</td>
                <td>${String(t.overdue ?? 0)}</td>
                <td>${String(t.dueSoon ?? 0)}</td>
              </tr>`)}
            </tbody>
          </table>`}
    </div>
    <${AnalysisItems}
      key=${state.seq}
      item=${item}
      departments=${departments}
      modelFilter=${modelFilter}
      onModelFilterApply=${setModelFilter}
      chartSelect=${chartSelect}
      onDeptChange=${setChartDept}
    />`;
}
