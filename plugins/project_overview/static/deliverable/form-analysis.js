// Embedded unified form analysis (legacy loadDeliverableFormView /
// renderDeliverableFormAnalysis): snapshot actions, summary, chart tabs
// with per-tab filter bar, department board + section rollup rules, trend
// and cost charts, paged rows table and the statistics disclosure.
import { html, useEffect, useLayoutEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { apiRequest, enc, plainErrorMessage } from "./api.js";
import {
  departmentBoardRows,
  formStatusBars,
  formTrendGeometry,
  sectionCostRows,
  sectionCountBars,
  unrecognizedStageCount,
  SECTION_COST_METRICS,
} from "./chart-math.js";
import {
  archiveFormatDate,
  archiveSyncStateLabel,
  formCostText,
  formCostValueClass,
  safeDisplayValue,
  statisticsDayText,
  statisticsLocalDateText,
  statisticsNumberText,
} from "./format.js";
import {
  DELIVERABLE_FORM_CHART_TITLES,
  DELIVERABLE_FORM_TABS,
  FORM_TRUNCATED_COLUMN_LABELS,
  FORM_VIEW_LIMITS,
  OVERDUE_STATE_LABELS,
  appendFormFilter,
  applyDraftFilters,
  buildDeliverableFormQuery,
  buildRollupPayload,
  clearCurrentFilters,
  cloneFormFilterState,
  cloneRollupTargets,
  createDeliverableFormState,
  currentFormDisplayedFilterState,
  currentFormDraftFilterState,
  currentFormFilterState,
  deliverableFormFilterLabel,
  deliverableFormKey,
  formAbsentSourceIndexes,
  formColumnIndex,
  formDisplayColumns,
  formDraftStatus,
  formFilterStatesEqual,
  formOptionValues,
  formRowCell,
  formViewErrorMessage,
  formViewLoadTimeoutError,
  FORM_ABSENT_SOURCE_TEXT,
  markFormFilterStateDisplayed,
  overdueThresholdsFromInputs,
  removeDisplayedFilter,
  setDraftFilter,
} from "./form-state.js";
import { SearchMultiSelect } from "./multi-select.js";

const keyActivate = (fn) => (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    fn();
  }
};

// ---- filter bar -------------------------------------------------------------

function FormFilterBar({ data, state, onReload, bump }) {
  const formKey = String((data && data.formKey) || "");
  const draft = currentFormDraftFilterState(state);
  const status = formDraftStatus(state);
  const scopeText = "仅作用于当前图表页签与表单明细；同一字段内多选为或，字段之间为且";
  const fields = data && data.filters && Array.isArray(data.filters.fields) ? data.filters.fields : [];
  const setText = (key) => (event) => {
    setDraftFilter(state, key, event.currentTarget.value);
    bump();
  };
  const multi = (key, labels) => {
    const labelText = deliverableFormFilterLabel(formKey, key);
    const values = Array.isArray(draft[key]) ? draft[key] : (draft[key] ? [String(draft[key])] : []);
    return html`<label class="form-filter-field form-filter-field-wide" key=${key}>
      <span class="form-filter-label">${labelText}</span>
      <${SearchMultiSelect}
        ariaLabel=${labelText}
        placeholder="搜索或多选"
        options=${formOptionValues(data, key)}
        values=${values}
        labelFor=${labels || ((value) => value)}
        onChange=${(next) => {
          setDraftFilter(state, key, next);
          state.pageByTab[state.activeTab] = 0;
          bump();
        }}
      />
    </label>`;
  };
  const displayed = currentFormDisplayedFilterState(state);
  // 草稿 chip（点选候选"无反馈"的生产反馈）：有未应用草稿时 chips 区显示草稿条件并标注
  // 「待应用」，【应用筛选】高亮；移除草稿 chip 只改草稿（不触发请求）。
  const draftDirty = !formFilterStatesEqual(displayed, draft);
  const applyDirty = !formFilterStatesEqual(currentFormFilterState(state), draft);
  const source = draftDirty ? draft : displayed;
  const chips = [];
  Object.entries(source).forEach(([key, value]) => {
    (Array.isArray(value) ? value : [value]).forEach((item) => {
      const display = key === "overdueState" ? (OVERDUE_STATE_LABELS[item] || item) : item;
      const label = deliverableFormFilterLabel(formKey, key);
      const remove = () => {
        if (draftDirty) {
          const next = cloneFormFilterState(draft);
          if (Array.isArray(next[key])) {
            const rest = next[key].filter((candidate) => String(candidate) !== String(item));
            if (rest.length) next[key] = rest;
            else delete next[key];
          } else {
            delete next[key];
          }
          state.draftFilterStateByTab[state.activeTab] = next;
          state.pageByTab[state.activeTab] = 0;
          bump();
          return;
        }
        removeDisplayedFilter(state, key, item);
        onReload();
      };
      chips.push(html`<span class=${draftDirty ? "form-filter-chip is-draft" : "form-filter-chip"} key=${`${key}:${item}`}>
        <span class="form-filter-chip-label">${`${label}：${safeDisplayValue(display)}`}</span>
        <button type="button" class="form-filter-chip-remove" aria-label=${`删除筛选 ${label} ${safeDisplayValue(display)}`}
          onClick=${remove}>×</button>
      </span>`);
    });
  });

  return html`<section class="form-filter-bar" aria-label="当前图表筛选" data-form-filter-tab=${state.activeTab}>
    <div class="form-filter-head">
      <strong class="form-filter-title">筛选条件<span class="form-filter-info" title=${scopeText} aria-label=${scopeText}>ⓘ</span></strong>
      <span class=${`form-filter-draft-state${status.dirty ? " is-dirty" : ""}${status.pending ? " is-pending" : ""}${status.error ? " is-error" : ""}`}>${status.text}</span>
    </div>
    <div class="form-filter-controls">
      <div class="form-filter-row form-filter-row-search">
        <input class="form-filter-keyword" type="search" placeholder="编号、项目、零件、负责人" aria-label="关键词" maxlength="200"
          value=${String(draft.keyword || "")} onInput=${setText("keyword")} />
        ${fields.includes("relationEwo") && html`<label class="form-filter-field">
          <span class="form-filter-label">${deliverableFormFilterLabel(formKey, "relationEwo") || "关联EWO"}</span>
          <input class="form-filter-keyword" type="text" placeholder="按 EWO 号定位关联记录" maxlength="200" aria-label="关联EWO"
            value=${String(draft.relationEwo || "")} onInput=${setText("relationEwo")} />
        </label>`}
        <div class="form-filter-actions">
          <button type="button" class=${applyDirty ? "btn is-secondary is-draft-dirty" : "btn is-secondary"} onClick=${() => { applyDraftFilters(state); onReload(); }}>应用筛选</button>
          <button type="button" class="btn is-secondary" onClick=${() => { clearCurrentFilters(state); onReload(); }}>清除筛选</button>
        </div>
      </div>
      <div class="form-filter-row form-filter-row-dims">
        ${multi("status")}
        ${formOptionValues(data, "department").length > 0 && multi("department")}
        ${multi("section")}
        ${multi("model")}
        ${multi("stage")}
        ${multi("overdueState", (value) => OVERDUE_STATE_LABELS[value] || value)}
      </div>
      <div class="form-filter-row form-filter-row-time">
        <label class="form-filter-field">
          <span class="form-filter-label">${deliverableFormFilterLabel(formKey, "dateStart")}</span>
          <input class="form-filter-date" type="date" aria-label=${deliverableFormFilterLabel(formKey, "dateStart")}
            value=${String(draft.dateStart || "")} onInput=${setText("dateStart")} />
        </label>
        <label class="form-filter-field">
          <span class="form-filter-label">${deliverableFormFilterLabel(formKey, "dateEnd")}</span>
          <input class="form-filter-date" type="date" aria-label=${deliverableFormFilterLabel(formKey, "dateEnd")}
            value=${String(draft.dateEnd || "")} onInput=${setText("dateEnd")} />
        </label>
      </div>
    </div>
    <div class="form-filter-chips chart-filter-state">
      ${draftDirty && html`<span class="form-filter-chips-note">待应用（点【应用筛选】生效）：</span>`}
      ${chips.length ? chips : html`<span class="form-filter-empty">0 个筛选条件</span>`}
    </div>
  </section>`;
}

// ---- charts -----------------------------------------------------------------

// 「其他状态」桶移除后，不在阶段词表的行只经载荷里的 unrecognizedStageCount
// （整数，全报表统一口径）披露。旧快照无该键、计数为 0 或非法值时一律不渲染——
// 既不静默丢失，也绝不显示 NaN/undefined。
function UnrecognizedNote({ payload }) {
  const count = unrecognizedStageCount(payload);
  return count > 0 ? html`<p class="form-chart-unrecognized">${`未识别 ${count} 条`}</p>` : null;
}

function StatusBars({ entries, filterKey, state, onReload, title, description, payload }) {
  const rows = formStatusBars(entries);
  return html`<section class="form-chart-panel-content">
    <h5 class="form-chart-title">${title}</h5>
    <p class="form-chart-description">${description}</p>
    <${UnrecognizedNote} payload=${payload} />
    <div class="form-chart-legend">
      <span class="form-chart-legend-item form-status-on-time">按期推进 / 正常</span>
      <span class="form-chart-legend-item form-status-overdue">逾期风险</span>
      <span class="form-chart-legend-item form-status-incomplete">未判定 / 当前节点</span>
    </div>
    <div class="form-status-bars">
      ${rows.map((row, index) => {
        const other = row.label === "其他状态";
        const activate = () => { appendFormFilter(state, filterKey, row.label); onReload(); };
        return html`<div
          key=${index}
          class="form-status-bar-row"
          role=${other ? null : "button"}
          tabindex=${other ? null : "0"}
          title=${other ? "其他状态（OPEN / CANCEL / 起草 / 挂起等）单独展示，不并入阶段筛选" : null}
          aria-label=${`${row.label}：按期 ${row.onTime}，逾期 ${row.overdue}，未知 ${row.unknown}`}
          onClick=${other ? null : activate}
          onKeyDown=${other ? null : keyActivate(activate)}
        >
          <span class="form-status-bar-label">${safeDisplayValue(row.label)}</span>
          <span class="form-status-bar-track">
            <span class="form-status-bar-fill form-status-on-time" style=${{ width: `${row.onTimePct}%` }}></span>
            <span class="form-status-bar-fill form-status-overdue" style=${{ width: `${row.overduePct}%` }}></span>
            <span class="form-status-bar-fill form-status-unknown" style=${{ width: `${row.unknownPct}%` }}></span>
          </span>
          <span class="form-status-bar-numbers">按期 ${row.onTime} · 逾期 ${row.overdue} · 未判定 ${row.unknown} · 共 ${row.total}</span>
        </div>`;
      })}
      ${!rows.length && html`<p class="form-chart-empty">暂无可分析的表单数据</p>`}
    </div>
  </section>`;
}

function MatrixBars({ bars, filterKey, state, onReload }) {
  return html`<div class="form-status-bars">
    ${bars.map((bar, index) => {
      const activate = () => { appendFormFilter(state, filterKey, bar.label); onReload(); };
      return html`<div
        key=${index}
        class="form-status-bar-row"
        role=${bar.filterable ? "button" : null}
        tabindex=${bar.filterable ? "0" : null}
        aria-label=${bar.filterable ? `${bar.label}：共 ${bar.total} 条` : null}
        title=${bar.filterable ? null : "其他状态（OPEN / CANCEL / 起草 / 挂起等）单独展示，不并入状态筛选"}
        onClick=${bar.filterable ? activate : null}
        onKeyDown=${bar.filterable ? keyActivate(activate) : null}
      >
        <span class="form-status-bar-label">${safeDisplayValue(bar.label)}</span>
        <span class="form-status-bar-track">
          ${bar.segments.map((segment, segIndex) => html`<span
            key=${segIndex}
            class="form-status-bar-fill form-matrix-fill"
            style=${{ width: `${segment.width}%`, background: segment.color }}
            title=${segment.title}
          >${segment.showLabel && html`<span class="form-matrix-seg-label">${String(segment.count)}</span>`}</span>`)}
        </span>
        <span class="form-status-bar-numbers">共 ${bar.total}</span>
      </div>`;
    })}
    ${!bars.length && html`<p class="form-chart-empty">暂无可分析的表单数据</p>`}
  </div>`;
}

function DimensionLegend({ rows }) {
  return html`<div class="form-chart-legend">
    ${rows.map((row, index) => html`<span class="form-chart-legend-item" key=${index} style=${{ color: row.color }}>${row.label}</span>`)}
  </div>`;
}

function RollupPanel({ data, state, onReload, bump }) {
  const rules = data && data.sectionRollup;
  const hasRules = Boolean(rules && Array.isArray(rules.targets));
  const open = state.rollupEditing === true || state.rollupPanelOpen === true;
  const [saving, setSaving] = useState(false);
  const onToggle = (event) => {
    state.rollupPanelOpen = event.currentTarget.open;
  };
  let body;
  if (!hasRules) {
    body = html`<p class="form-rollup-hint">当前交付物未启用科室归集。</p>`;
  } else if (state.rollupEditing === true) {
    if (!Array.isArray(state.rollupDraft)) state.rollupDraft = cloneRollupTargets(rules.targets);
    const save = async () => {
      setSaving(true);
      try {
        await apiRequest("/api/project-status/section-rollup", { method: "PUT", body: buildRollupPayload(state.rollupDraft) });
        state.rollupEditing = false;
        state.rollupDraft = null;
        state.rollupError = null;
        setSaving(false);
        onReload();
      } catch (err) {
        state.rollupError = err.status === 0
          ? { message: `保存失败：${err.message || "网络错误"}`, fields: null }
          : { message: plainErrorMessage(err, "保存失败，请检查规则。"), fields: err.fields || null };
        setSaving(false);
        bump();
      }
    };
    body = html`
      ${state.rollupError && html`<p class="form-rollup-error">${String(state.rollupError.message || "保存失败，请检查规则。")}${
        state.rollupError.fields && typeof state.rollupError.fields === "object"
          ? Object.entries(state.rollupError.fields).map(([key, message]) => ` ${key}：${String(message)}`).join("")
          : ""}</p>`}
      ${state.rollupDraft.map((entry, entryIndex) => html`<${RollupRow} key=${entryIndex} entry=${entry} bump=${bump} />`)}
      <div class="form-rollup-actions">
        <button type="button" class="btn is-secondary" onClick=${() => { state.rollupDraft.push({ target: "", aliases: [] }); bump(); }}>+ 新增目标科室</button>
        <span class="form-rollup-hint">同一历史值只能归属一个目标科室，保存时校验；空值与重复值会被拦截。</span>
        <span class="form-rollup-spacer"></span>
        <button type="button" class="btn is-primary form-rollup-save" disabled=${saving} onClick=${save}>保存规则</button>
        <button type="button" class="btn is-secondary" onClick=${() => {
          state.rollupEditing = false;
          state.rollupDraft = null;
          state.rollupError = null;
          bump();
        }}>取消</button>
      </div>`;
  } else {
    body = html`
      <table class="form-rollup-table">
        <thead><tr><th>归集到</th><th>包含的历史值</th></tr></thead>
        <tbody>
          ${rules.targets.map((entry, index) => html`<tr key=${index}>
            <td class="form-rollup-target">${String(entry.target || "")}</td>
            <td>${entry.aliases && entry.aliases.length ? entry.aliases.join("、") : "（当前仅本科室自身）"}</td>
          </tr>`)}
          <tr><td class="form-rollup-target">未归集</td><td>未登记的其他历史科室值（固定兜底，无需配置）</td></tr>
        </tbody>
      </table>
      <div class="form-rollup-actions">
        ${rules.updatedAt && html`<span class="form-rollup-hint">最近更新：${String(rules.updatedAt)}</span>`}
        <span class="form-rollup-spacer"></span>
        <button type="button" class="btn is-secondary form-rollup-edit" onClick=${() => {
          state.rollupEditing = true;
          state.rollupDraft = cloneRollupTargets(rules.targets);
          state.rollupError = null;
          bump();
        }}>编辑规则</button>
      </div>`;
  }
  return html`<details class="form-rollup-panel" open=${open} ontoggle=${onToggle}>
    <summary>科室归集规则</summary>
    <div class="form-rollup-body">
      ${hasRules && html`<p class="form-rollup-hint">历史科室先归集到现行科室再统计；「科室 / 区域」筛选同样按归集口径，未登记的历史值计入「未归集」，不会静默丢弃。匹配忽略空格差异，并自动识别「英文缩写前缀 + 空格」形态（如登记「结构工程科」即可命中「BE 结构工程科」）；无空格分隔或其他写法请登记完整历史值。规则保存在本地数据库，保存后立即生效——只调整统计口径，不改写原始数据，无需重新同步。</p>`}
      ${body}
    </div>
  </details>`;
}

function RollupRow({ entry, bump }) {
  const [alias, setAlias] = useState("");
  return html`<div class="form-rollup-row">
    ${entry.target
      ? html`<span class="form-rollup-target">${entry.target}</span>`
      : html`<input class="form-rollup-add-input form-rollup-target-input" type="text" placeholder="新目标科室名称"
          value=${String(entry.draftTarget || "")} onInput=${(e) => { entry.draftTarget = e.currentTarget.value; }} />`}
    <div class="form-rollup-aliases">
      ${entry.aliases.map((value, aliasIndex) => html`<span class="form-rollup-chip" key=${aliasIndex}>${value}<button
        type="button" class="form-rollup-chip-remove" title=${`移除 ${value}`}
        onClick=${() => { entry.aliases.splice(aliasIndex, 1); bump(); }}>×</button></span>`)}
      <input class="form-rollup-add-input" type="text" placeholder="添加历史科室值" value=${alias} onInput=${(e) => setAlias(e.currentTarget.value)} />
      <button type="button" class="btn is-secondary form-rollup-add-btn" onClick=${() => {
        const value = alias.trim();
        if (!value) return;
        entry.aliases.push(value);
        setAlias("");
        bump();
      }}>添加</button>
    </div>
  </div>`;
}

function DepartmentStatusBoard({ data, state, onReload, bump }) {
  const matrix = data && data.charts && data.charts.sectionStageMatrix;
  const valid = matrix && Array.isArray(matrix.sections) && Array.isArray(matrix.stages);
  const board = valid ? departmentBoardRows(matrix, state.boardTab) : null;
  return html`<section class="form-chart-panel-content">
    <h5 class="form-chart-title">部门总状态</h5>
    <p class="form-chart-description">${state.boardTab === "byStatus"
      ? "按审批节点 / 业务状态统计（完整状态按流程顺序展示，含当前无数据状态），柱内色段为归集后科室的数量占比；点击状态行可追加筛选。"
      : "按归集后科室统计，柱内色段为各审批节点 / 业务状态的数量占比；点击科室行可追加科室筛选，悬停查看状态明细。"}</p>
    <${UnrecognizedNote} payload=${matrix} />
    <div class="form-chart-tab-list dept-board-tab-list" role="tablist">
      ${[["bySection", "按科室"], ["byStatus", "按状态"]].map(([key, label]) => html`<button
        type="button" key=${key} role="tab"
        class=${`form-chart-tab dept-board-tab${state.boardTab === key ? " is-active" : ""}`}
        aria-selected=${state.boardTab === key ? "true" : "false"}
        onClick=${() => {
          if (state.boardTab === key) return;
          state.boardTab = key;
          onReload();
        }}
      >${label}</button>`)}
    </div>
    ${board
      ? html`<${DimensionLegend} rows=${board.legend} /><${MatrixBars} bars=${board.bars} filterKey=${board.filterKey} state=${state} onReload=${onReload} />`
      : html`<p class="form-chart-empty">暂无可分析的表单数据</p>`}
    <${RollupPanel} data=${data} state=${state} onReload=${onReload} bump=${bump} />
  </section>`;
}

// NCR 明细按科室的四项成本指标表。行 = 归集后科室；数值列带行内条，负值（成本下降）
// 显式着色；「无值」与「0」用有值件数区分。行点击 = 追加科室筛选（与计数条同语义）。
function SectionCostsTable({ data, state, onReload }) {
  const rows = sectionCostRows(data && data.charts && data.charts.sectionCosts);
  if (!rows.length) return null;
  return html`<table class="form-section-cost-table">
    <thead><tr>
      <th>科室</th><th class="is-number">件数</th>
      ${SECTION_COST_METRICS.map((metric) => html`<th class="is-number" key=${metric.key}>${metric.label}</th>`)}
    </tr></thead>
    <tbody>
      ${rows.map((row) => {
        const activate = () => { appendFormFilter(state, "section", row.label); onReload(); };
        return html`<tr key=${row.label} role="button" tabindex="0" aria-label=${`科室 ${row.label}：追加科室筛选`}
          onClick=${activate} onKeyDown=${keyActivate(activate)}>
          <td class="form-section-cost-name">${row.label}</td>
          <td class="is-number">${String(row.total)}</td>
          ${row.cells.map((cell) => cell.empty
    ? html`<td class="is-number form-section-cost-cell" key=${cell.key} title=${cell.title}><span class="form-section-cost-none">—</span></td>`
    : html`<td class="is-number form-section-cost-cell" key=${cell.key} title=${cell.title}>
              <span class=${cell.negative ? "form-section-cost-value is-negative" : "form-section-cost-value"}>${cell.text}</span>
              <span class="form-section-cost-bar"><span class=${cell.negative ? "form-section-cost-fill is-negative" : "form-section-cost-fill"} style=${{ width: `${cell.widthPct}%` }}></span></span>
              <span class="form-section-cost-count">${`${cell.count} 项有值`}</span>
            </td>`)}
        </tr>`;
      })}
    </tbody>
  </table>`;
}

function SectionCountsBoard({ data, state, onReload, bump }) {
  // 数模阶段词表为空、阶段矩阵恒缺，走与 NCR 明细同源的计数板分支；说明与色段名
  // 按表单键区分，避免数模页签里出现"NCR明细"字样。
  const isDataModel = String((data && data.formKey) || "") === "tdc_data_model";
  const counts = data && data.charts && Array.isArray(data.charts.sectionCounts) ? data.charts.sectionCounts : [];
  return html`<section class="form-chart-panel-content">
    <h5 class="form-chart-title">按科室统计</h5>
    <p class="form-chart-description">${isDataModel
    ? "数模流程无阶段维度，按归集后科室统计数量；点击科室行可追加科室筛选。"
    : "NCR明细无状态维度，按归集后科室统计数量与四项成本指标；点击科室行可追加科室筛选。"}</p>
    <${SectionCostsTable} data=${data} state=${state} onReload=${onReload} />
    <${MatrixBars} bars=${sectionCountBars(counts, isDataModel ? "数模" : "NCR明细")} filterKey="section" state=${state} onReload=${onReload} />
    <${RollupPanel} data=${data} state=${state} onReload=${onReload} bump=${bump} />
  </section>`;
}

function FormTrendChart({ points, state, onReload }) {
  const g = formTrendGeometry(points);
  const pick = (day) => {
    appendFormFilter(state, "dateStart", day);
    appendFormFilter(state, "dateEnd", day);
    onReload();
  };
  return html`<div class="form-trend-chart">
    <svg class="form-trend-svg" viewBox="0 0 760 300" role="img" aria-label="总数、未完成数、逾期数数量趋势">
      <title>总数、未完成数、逾期数数量趋势</title>
      ${g.grid.map((line, index) => html`<g key=${`g${index}`}>
        <line x1=${g.padding.left} x2=${g.padding.left + g.width} y1=${line.y} y2=${line.y} class="form-trend-gridline" />
        <text x=${g.padding.left - 8} y=${line.y + 4} text-anchor="end" class="form-trend-axis-label">${line.label}</text>
      </g>`)}
      ${g.series.map((serie) => html`<g key=${serie.key}>
        <polyline points=${serie.line} class=${`form-trend-line ${serie.className}`} />
        ${serie.coords.map((point, index) => html`<circle
          key=${index}
          cx=${point.x.toFixed(1)} cy=${point.y.toFixed(1)} r="5"
          class=${`form-trend-point ${serie.className}`}
          tabindex="0" role="button"
          aria-label=${`${point.day} ${serie.label} ${point.value}`}
          onClick=${() => pick(point.day)}
          onKeyDown=${keyActivate(() => pick(point.day))}
        />`)}
      </g>`)}
      ${g.axis.map((tick, index) => html`<text key=${`a${index}`} x=${tick.x} y=${g.axisY} text-anchor="middle" class="form-trend-axis-label">${tick.label}</text>`)}
    </svg>
    <div class="form-chart-legend">
      <span class="form-chart-legend-item form-trend-total">总数</span>
      <span class="form-chart-legend-item form-trend-incomplete">未完成数</span>
      <span class="form-chart-legend-item form-trend-overdue">逾期数</span>
    </div>
    <p class="form-trend-note">趋势横轴为后台快照自然日（同一天取最后一次快照）；点击节点追加的是该自然日的提交日期条件——提交日期与快照日期是不同概念。</p>
    ${!g.axis.length && html`<p class="form-chart-empty">暂无按天快照趋势</p>`}
  </div>`;
}

function CostChart({ entries, filterKey, state, onReload }) {
  const safe = Array.isArray(entries) ? entries : [];
  return html`<section class="form-chart-panel-content">
    <h5 class="form-chart-title">${filterKey === "department" ? "部门成本变化" : "科室 / 区域成本变化"}</h5>
    <p class="form-chart-description">按总和展示测算、批准、实际三组一次性投资成本与整车成本变化；正数红色，负数绿色。</p>
    <div class="form-cost-legend">一次性投资成本：万元 · 整车成本变化：元</div>
    <div class="form-cost-chart">
      ${safe.map((entry, index) => {
        const label = String((entry && entry.label) || "部门总计");
        const investment = entry && entry.investment && typeof entry.investment === "object" ? entry.investment : {};
        const vehicle = entry && entry.vehicleChange && typeof entry.vehicleChange === "object" ? entry.vehicleChange : {};
        const activate = () => {
          if (label === "部门总计") return;
          appendFormFilter(state, filterKey, label);
          onReload();
        };
        return html`<div class="form-cost-row" key=${index} role="button" tabindex="0" onClick=${activate} onKeyDown=${keyActivate(activate)}>
          <strong class="form-cost-label">${safeDisplayValue(label)}</strong>
          <div class="form-cost-groups">
            ${[["一次性投资成本", investment, "万元"], ["整车成本变化", vehicle, "元"]].map(([groupLabel, values, unit]) => html`
              <div class="form-cost-group" key=${groupLabel}>
                <span class="form-cost-group-label">${groupLabel}</span>
                ${["estimate", "approved", "actual"].map((name) => html`<span
                  key=${name}
                  class=${`form-cost-value ${groupLabel === "整车成本变化" ? formCostValueClass(values[name]) : ""}`}
                >${`${name === "estimate" ? "测算" : name === "approved" ? "批准" : "实际"}：${formCostText(values[name], unit)}`}</span>`)}
              </div>`)}
          </div>
        </div>`;
      })}
      ${!safe.length && html`<p class="form-chart-empty">暂无成本快照数据</p>`}
    </div>
  </section>`;
}

function OverdueControl({ data, state, onReload }) {
  const rules = data && data.schema && data.schema.overdueRules;
  const applied = state.overdueThresholds || {};
  const [inputs, setInputs] = useState(() => (rules ? {
    overdueDaysStage: String(applied.overdueDaysStage !== undefined ? applied.overdueDaysStage : rules.stageDays),
    overdueDaysLate: String(applied.overdueDaysLate !== undefined ? applied.overdueDaysLate : rules.lateDays),
  } : {}));
  if (!rules) return html`<div></div>`;
  return html`<div class="form-overdue-control">
    <span class="form-overdue-title">逾期判定天数</span>
    ${[[rules.stageLabel, "overdueDaysStage"], [rules.lateLabel, "overdueDaysLate"]].map(([labelText, key]) => html`
      <label class="form-overdue-field" key=${key}>
        <span class="form-overdue-label">${labelText}</span>
        <input type="number" min="0" max="999" aria-label=${`${labelText} 逾期判定天数`} value=${inputs[key]}
          onInput=${(e) => { const value = e.currentTarget.value; setInputs((prev) => ({ ...prev, [key]: value })); }} />
        <span class="form-overdue-unit">天</span>
      </label>`)}
    <button type="button" class="btn is-secondary form-overdue-apply" aria-label="应用逾期判定天数" onClick=${() => {
      state.overdueThresholds = overdueThresholdsFromInputs(inputs);
      onReload();
    }}>应用</button>
    <span class="form-overdue-note">${rules.note}；趋势图与历史快照保持存储口径——提交日期与快照日期是不同概念。</span>
  </div>`;
}

function ChartPanelContent({ data, state, onReload, bump }) {
  const formKey = String((data && data.formKey) || "");
  const charts = data && data.charts && typeof data.charts === "object" ? data.charts : {};
  const titles = DELIVERABLE_FORM_CHART_TITLES[formKey] || {};
  const tab = state.activeTab;
  const parts = [];
  if ((tab === "departmentStatus" || tab === "sectionStatus") && ["ewo", "paa", "ncr_progress"].includes(String((data && data.reportType) || ""))) {
    parts.push(html`<${OverdueControl} key=${`overdue-${tab}`} data=${data} state=${state} onReload=${onReload} />`);
  }
  if (tab === "departmentStatus") {
    if (charts.sectionStageMatrix) {
      parts.push(html`<${DepartmentStatusBoard} key="board" data=${data} state=${state} onReload=${onReload} bump=${bump} />`);
    } else {
      const stages = charts.departmentStatus && Array.isArray(charts.departmentStatus.stages) ? charts.departmentStatus.stages : [];
      const [title, description] = titles.departmentStatus || ["部门总状态", "各阶段 / 审批节点按期推进数与逾期风险数"];
      parts.push(html`<${StatusBars} key="dept" entries=${stages} payload=${charts.departmentStatus} filterKey="stage" state=${state} onReload=${onReload} title=${title} description=${description} />`);
    }
  } else if (tab === "sectionStatus") {
    const [title, description] = titles.sectionStatus
      || [formKey === "aras_ncr_progress" ? "区域状态" : "科室状态", "点击一个科室或区域可追加筛选"];
    parts.push(html`<${StatusBars} key="section" entries=${charts.sectionStatus} filterKey="section" state=${state} onReload=${onReload} title=${title} description=${description} />`);
  } else if (tab === "sectionCounts") {
    parts.push(html`<${SectionCountsBoard} key="counts" data=${data} state=${state} onReload=${onReload} bump=${bump} />`);
  } else if (tab === "quantityTrend") {
    parts.push(html`<section class="form-chart-panel-content" key="trend">
      <h5 class="form-chart-title">数量趋势</h5>
      <p class="form-chart-description">按自然日展示最近 30 天；同一天以当天最后一次后台快照为准。点击折线节点可筛选该日数据。</p>
      <${FormTrendChart} points=${charts.quantityTrend || data.trend || []} state=${state} onReload=${onReload} />
    </section>`);
  } else if (tab === "departmentCost") {
    parts.push(html`<${CostChart} key="dcost" entries=${charts.departmentCost} filterKey="department" state=${state} onReload=${onReload} />`);
  } else if (tab === "sectionCost") {
    parts.push(html`<${CostChart} key="scost" entries=${charts.sectionCost} filterKey="section" state=${state} onReload=${onReload} />`);
  }
  return parts;
}

// ---- rows table + statistics --------------------------------------------------

function FormRowsTable({ data, rowsData, state, onReload }) {
  const total = Number(rowsData && rowsData.total) || 0;
  const columns = data && data.schema && Array.isArray(data.schema.columns) ? data.schema.columns : [];
  const defaultVisibleCount = data && data.schema ? Number(data.schema.defaultVisibleCount) || 12 : 12;
  const keyIndexes = data && data.schema && Array.isArray(data.schema.keyColumns)
    ? data.schema.keyColumns.map((index) => Number(index)).filter((index) => Number.isFinite(index) && index >= 0)
    : [];
  const visible = keyIndexes.length
    ? columns.filter((column) => keyIndexes.includes(Number(column && column.index)))
    : columns.slice(0, Math.min(columns.length, Math.max(8, defaultVisibleCount)));
  // 数模「状态」派生列；「源端不提供」= 该位置的全部候选源字段在整份快照的原始行里都不存在
  // （快照级事实由服务端判定，见 deliverable_form_analysis.source_absent_indexes）。键存在
  // 但值为空是真实空值，走普通单元格，不得误标。
  const displayColumns = formDisplayColumns(data, visible);
  const absent = formAbsentSourceIndexes(data);
  const items = rowsData && Array.isArray(rowsData.items) ? rowsData.items : [];
  const offset = Number(rowsData && rowsData.offset) || 0;
  const limit = Math.max(1, Number(rowsData && rowsData.limit) || 50);
  const span = 2 + displayColumns.length;
  return html`<section class="form-row-table-section">
    <div class="form-row-table-head">
      <h5 class="form-chart-title">表单明细</h5>
      <span class="form-row-count">${total} 条匹配记录</span>
    </div>
    <div class="form-row-table-wrap">
      <table class="form-row-table">
        <thead><tr>
          ${["工作表", "行号"].map((label) => html`<th key=${label}>${label}</th>`)}
          ${displayColumns.map((column, index) => {
            const label = column && column.derivedStatus ? "状态" : (column && column.label ? String(column.label) : `列 ${index + 1}`);
            const isAbsent = column && !column.derivedStatus && absent.has(formColumnIndex(column));
            return html`<th key=${`c${index}`} class=${isAbsent ? "form-cell-absent" : null}>${label}</th>`;
          })}
        </tr></thead>
        <tbody>
          ${items.map((row, rowIndex) => {
            const values = Array.isArray(row && row.values) ? row.values : [];
            return html`
              <tr key=${`r${rowIndex}`}>
                <td>${safeDisplayValue(row && row.sheetName)}</td>
                <td>${safeDisplayValue(row && row.rowNumber)}</td>
                ${displayColumns.map((column, index) => {
                  const cell = formRowCell(column, row, absent);
                  if (cell.absent) return html`<td key=${`c${index}`} class="form-cell-absent">${FORM_ABSENT_SOURCE_TEXT}</td>`;
                  const text = safeDisplayValue(cell.text);
                  // 长文本列截断成单行，完整值进 title 悬浮（“查看全部字段”仍有全值）。
                  if (column && !column.derivedStatus && text !== "-" && FORM_TRUNCATED_COLUMN_LABELS.has(String(column.label || ""))) {
                    return html`<td key=${`c${index}`} class="form-cell-truncate" title=${text}>${text}</td>`;
                  }
                  return html`<td key=${`c${index}`}>${text}</td>`;
                })}
              </tr>
              <tr class="form-row-detail-row" key=${`d${rowIndex}`}><td colspan=${span}>
                <details class="form-row-full-detail">
                  <summary>查看全部字段</summary>
                  <dl class="form-row-field-grid">
                    ${columns.map((column, index) => {
                      const physical = formColumnIndex(column);
                      return html`
                        <dt key=${`t${index}`}>${column && column.label ? String(column.label) : `列 ${index + 1}`}</dt>
                        ${absent.has(physical)
    ? html`<dd key=${`v${index}`} class="form-cell-absent">${FORM_ABSENT_SOURCE_TEXT}</dd>`
    : html`<dd key=${`v${index}`}>${safeDisplayValue(values[Number.isFinite(physical) ? physical : index])}</dd>`}`;
                    })}
                  </dl>
                </details>
              </td></tr>`;
          })}
          ${!items.length && html`<tr><td class="form-chart-empty" colspan=${span}>${total ? "当前筛选没有可见记录" : "暂无表单快照数据"}</td></tr>`}
        </tbody>
      </table>
    </div>
    <div class="form-row-pager">
      <button type="button" class="btn is-secondary" disabled=${offset <= 0}
        onClick=${() => { state.pageByTab[state.activeTab] = Math.max(0, offset - limit); onReload(); }}>上一页</button>
      <span class="form-row-page-label">第 ${Math.floor(offset / limit) + 1} / ${Math.max(1, Math.ceil(total / limit))} 页</span>
      <button type="button" class="btn is-secondary" disabled=${offset + limit >= total}
        onClick=${() => { state.pageByTab[state.activeTab] = offset + limit; onReload(); }}>下一页</button>
    </div>
  </section>`;
}

function StatisticsBody({ data }) {
  if (!data || data.hasSnapshot !== true || !data.statistics) return html`<p class="statistics-empty-state">暂无快照数据</p>`;
  const stats = data.statistics;
  const stagnation = stats.stagnation && typeof stats.stagnation === "object" ? stats.stagnation : null;
  const metrics = stagnation
    ? [
      ["平均停滞", `${statisticsNumberText(stagnation.mean)} 天`],
      ["中位数", `${statisticsNumberText(stagnation.median)} 天`],
      ["标准差", statisticsNumberText(stagnation.stdDev)],
      ["最长停滞", statisticsDayText(stagnation.max)],
    ]
    : [["平均停滞", "-"], ["中位数", "-"], ["标准差", "-"], ["最长停滞", "-"]];
  const distribution = Array.isArray(stats.statusDistribution) ? stats.statusDistribution.filter((e) => e && typeof e === "object") : [];
  const total = Number(stats.totalRecords) || 0;
  const top = Array.isArray(stats.stagnationTop) ? stats.stagnationTop.filter((e) => e && typeof e === "object") : [];
  const dispersion = Array.isArray(stats.dispersion) ? stats.dispersion.filter((e) => e && typeof e === "object") : [];
  return html`
    <div class="statistics-head"><span class="statistics-snapshot-at">快照时间：${statisticsLocalDateText(data.snapshotAt || stats.snapshotAt)}</span></div>
    <div class="statistics-metric-grid">
      ${metrics.map(([label, value]) => html`<div class="statistics-metric-card" key=${label}>
        <span class="statistics-metric-label">${label}</span><strong class="statistics-metric-value">${value}</strong>
      </div>`)}
    </div>
    <p class="statistics-inflight-note">${stagnation
      ? `在途记录 ${safeDisplayValue(stats.inFlightCount)} 条；时间列缺失/非法剔除 ${safeDisplayValue(stats.invalidActivityDateCount)} 条`
      : "无在途停滞记录（或时间列不可用），仅展示状态分布"}</p>
    <div class="statistics-status-distribution">
      <h6 class="statistics-block-title">状态分布</h6>
      ${!Array.isArray(stats.statusDistribution) || !stats.statusDistribution.length
        ? html`<p class="statistics-empty">暂无状态数据</p>`
        : distribution.map((entry, index) => {
          const count = Number(entry.count) || 0;
          const percent = total > 0 ? Math.round((count / total) * 100) : 0;
          return html`<div class="statistics-status-row" key=${index}>
            <span class="statistics-status-label">${safeDisplayValue(entry.status)}</span>
            <span class="statistics-status-bar"><span class="statistics-status-fill" style=${{ width: `${Math.min(100, Math.max(0, percent))}%` }}></span></span>
            <span class="statistics-status-count">${count}（${percent}%）</span>
          </div>`;
        })}
    </div>
    <div class="statistics-top-block">
      <h6 class="statistics-block-title">停滞 Top5 记录</h6>
      ${!Array.isArray(stats.stagnationTop) || !stats.stagnationTop.length
        ? html`<p class="statistics-empty">无在途停滞记录</p>`
        : html`<table class="statistics-top-table">
          <thead><tr>${[(stats.layout && stats.layout.identityLabel) || "单号", "当前步骤", "状态", "停滞天数"].map((label) => html`<th scope="col" key=${label}>${label}</th>`)}</tr></thead>
          <tbody>${top.map((entry, index) => html`<tr class="statistics-top-row" key=${index}>
            <td>${safeDisplayValue(entry.identity)}</td><td>${safeDisplayValue(entry.stage)}</td>
            <td>${safeDisplayValue(entry.status)}</td><td>${statisticsDayText(entry.stagnationDays)}</td>
          </tr>`)}</tbody>
        </table>`}
    </div>
    <div class="statistics-dispersion-block">
      <h6 class="statistics-block-title">离散度排名（跨快照方差）</h6>
      ${!Array.isArray(stats.dispersion) || !stats.dispersion.length
        ? html`<p class="statistics-empty">历史快照不足，暂无离散度排名</p>`
        : html`<ol class="statistics-dispersion-list">${dispersion.map((entry, index) => html`<li class="statistics-dispersion-item" key=${index}>
          <span class="statistics-dispersion-identity">${safeDisplayValue(entry.identity)}</span>
          <span class="statistics-dispersion-meta">${`步骤 ${safeDisplayValue(entry.stage)}；观测 ${safeDisplayValue(entry.observations)} 次快照；当前停滞 ${statisticsDayText(entry.latestStagnationDays)}；方差 ${statisticsNumberText(entry.variance)}`}</span>
        </li>`)}</ol>`}
    </div>`;
}

function StatisticsSection({ formKey }) {
  const [state, setState] = useState({ started: false, loading: false, error: false, data: null });
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  const load = async () => {
    setState({ started: true, loading: true, error: false, data: null });
    try {
      const data = await apiRequest(`/api/deliverable-forms/${enc(formKey)}/statistics`);
      if (alive.current) setState({ started: true, loading: false, error: false, data: data || {} });
    } catch (_err) {
      if (alive.current) setState({ started: true, loading: false, error: true, data: null });
    }
  };
  return html`<details class="deliverable-statistics" aria-label="交付物快照统计分析"
    ontoggle=${(event) => { if (event.currentTarget.open && !state.started) load(); }}>
    <summary class="deliverable-statistics-summary">
      <span>统计分析</span><span class="deliverable-statistics-hint">快照记录的确定性统计（纯统计学，无 AI）</span>
    </summary>
    <div class="deliverable-statistics-body">
      ${state.loading && html`<p class="form-view-loading loading">正在读取快照统计...</p>`}
      ${state.error && html`<div class="statistics-load-error">
        <p class="error-msg">快照统计读取失败，请稍后重试。</p>
        <button type="button" class="btn is-secondary" onClick=${load}>重新读取</button>
      </div>`}
      ${!state.loading && !state.error && state.data && html`<${StatisticsBody} data=${state.data} />`}
    </div>
  </details>`;
}

// ---- interaction guard ----------------------------------------------------------

const GUARDED_EVENTS = ["beforeinput", "change", "click", "compositionend", "compositionstart", "compositionupdate", "drop", "focus", "input", "keydown", "keyup", "mousedown", "paste", "pointerdown"];

/** While a tab switch is loading, block the stale controls (tab buttons and Tab key stay usable). */
function useInteractionGuard(ref, locked) {
  // 布局阶段安装：与 data-form-interaction-locked 属性同一次提交内生效，
  // 不存在「属性已锁定、监听器尚未安装」的窗口。
  useLayoutEffect(() => {
    const root = ref.current;
    if (!root || !locked) return undefined;
    const guard = (event) => {
      if (event.type === "keydown" && event.key === "Tab") return;
      const target = event.target;
      if (target && typeof target.closest === "function" && target.closest(".form-chart-tab-list > .form-chart-tab")) return;
      event.preventDefault();
      event.stopPropagation();
      // 可观测性：每次拦截累加 data-* 计数，首次拦截 console.debug 一条。现场 F12 一条命令
      // 即可判断点击是否被守卫吞掉：
      //   document.querySelector(".form-chart-tabs").dataset.formInteractionBlockedCount
      const blocked = Number(root.dataset.formInteractionBlockedCount || "0") + 1;
      root.dataset.formInteractionBlockedCount = String(blocked);
      if (blocked === 1 && typeof console !== "undefined" && console.debug) {
        console.debug("[vse] 表单交互守卫拦截事件（加载中锁定）", event.type);
      }
    };
    GUARDED_EVENTS.forEach((name) => root.addEventListener(name, guard, true));
    return () => GUARDED_EVENTS.forEach((name) => root.removeEventListener(name, guard, true));
  }, [locked]);
}

// ---- panel ------------------------------------------------------------------------

/**
 * `ctl.current.reload()` re-reads view + rows (legacy loadDeliverableFormView)
 * and resolves true/false. `archive` = {job, onBackgroundSync(setBusy)} on the
 * archive detail page.
 */
export function FormAnalysisPanel({ item, version, ctl, onViewData, archive }) {
  const formKey = deliverableFormKey(item);
  const stateRef = useRef(null);
  if (!stateRef.current || stateRef.current.formKey !== formKey) {
    stateRef.current = { ...createDeliverableFormState(formKey), formKey };
  }
  const state = stateRef.current;
  const [, setTick] = useState(0);
  const bump = () => setTick((value) => value + 1);
  const [view, setView] = useState({ data: null, rowsData: null, tab: "", error: null });
  const [bgBusy, setBgBusy] = useState(false);
  const lastGoodTab = useRef("");
  const chartsRef = useRef(null);
  const rowsRef = useRef(null);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  const load = async () => {
    const filters = cloneFormFilterState(currentFormFilterState(state));
    const tab = state.activeTab;
    const sequence = ++state.requestSeq;
    state.viewStatus = "loading";
    bump();
    // 锁的单一真相是 state.viewStatus：最新请求落定（成功、失败或超时 abort）即解锁，
    // 锁滞留时间由此有上界。过期请求（sequence 已被更新的请求取代）落定时不渲染、不写状态，
    // 因此不会污染最新视图。
    const controller = typeof AbortController === "function" ? new AbortController() : null;
    const timeoutMs = FORM_VIEW_LIMITS.timeoutMs;
    let timedOut = false;
    const timer = controller ? setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs) : null;
    const signal = controller ? controller.signal : undefined;
    try {
      const query = buildDeliverableFormQuery(filters);
      const rowQuery = buildDeliverableFormQuery(filters, true, state);
      const [data, rowsData] = await Promise.all([
        apiRequest(`/api/deliverable-forms/${enc(formKey)}/view?${query.toString()}`, { signal }),
        apiRequest(`/api/deliverable-forms/${enc(formKey)}/rows?${rowQuery.toString()}`, { signal }),
      ]);
      if (!alive.current || sequence !== state.requestSeq) return false;
      state.viewStatus = "success";
      lastGoodTab.current = tab;
      markFormFilterStateDisplayed(state, filters, tab);
      const viewData = data || {};
      if (onViewData) onViewData(viewData);
      setView({ data: viewData, rowsData: rowsData || { items: [], total: 0, offset: 0, limit: 50 }, tab, error: null });
      return true;
    } catch (rawError) {
      if (!alive.current || sequence !== state.requestSeq) return false;
      const error = timedOut ? formViewLoadTimeoutError(timeoutMs) : rawError;
      state.viewStatus = "error";
      // 页签切换失败：回到最后一次成功的页签，使界面显示/编辑的筛选状态与之后
      // 「应用筛选」「刷新」所读取的页签一致（否则条件会被写进未显示的页签）。
      if (lastGoodTab.current && lastGoodTab.current !== state.activeTab) state.activeTab = lastGoodTab.current;
      setView((prev) => ({ ...prev, error }));
      return false;
    } finally {
      if (timer !== null) clearTimeout(timer);
    }
  };
  if (ctl) ctl.current = { reload: load };
  useEffect(() => { if (formKey) load(); }, [formKey, version]);

  const reload = () => { load(); };
  const loading = state.viewStatus === "loading";
  const locked = loading && Boolean(view.data) && view.tab !== state.activeTab;
  useInteractionGuard(chartsRef, locked);
  useInteractionGuard(rowsRef, locked);

  const transient = html`
    ${loading && html`<p class="form-view-loading loading" role="status" aria-live="polite">正在读取表单快照与明细...</p>`}
    ${!loading && view.error && html`<div class="form-view-load-error" role="alert" aria-live="assertive">
      <p class="error-msg">${formViewErrorMessage(view.error)}</p>
      <p class="form-view-error-detail">可点击“刷新表单数据”重试；当前内容仍是最近一次成功应用的筛选结果，未应用更改会保留在控件中。</p>
      <button type="button" class="btn is-secondary" onClick=${reload}>刷新表单数据</button>
    </div>`}`;

  if (!view.data) return transient;

  const data = view.data;
  const dataFormKey = String(data.formKey || "");
  const tabs = DELIVERABLE_FORM_TABS[dataFormKey] || [];
  if (!tabs.some(([key]) => key === state.activeTab)) state.activeTab = tabs[0] ? tabs[0][0] : "";
  // Until the new tab's result arrives, keep rendering the previous tab's content.
  const shown = view.tab && view.tab !== state.activeTab && tabs.some(([key]) => key === view.tab)
    ? { ...state, activeTab: view.tab }
    : state;
  const snapshot = data.snapshot && typeof data.snapshot === "object" ? data.snapshot : null;
  const summary = data.summary && typeof data.summary === "object" ? data.summary : {};
  const sync = data.sync && typeof data.sync === "object" ? data.sync : {};
  const syncState = String(sync.state || "idle");
  const summaryClass = {
    总数: "form-summary-value form-status-total",
    未完成: "form-summary-value form-status-incomplete",
    逾期: "form-summary-value form-status-overdue",
  };
  const switchTab = (key) => {
    if (state.activeTab === key) return;
    state.activeTab = key;
    reload();
  };

  return html`
    ${transient}
    <div class="form-analysis-head">
      <div><p class="eyebrow">统一表单分析</p></div>
      <h5 class="form-analysis-title">${`${safeDisplayValue(item && item.name)} 表单明细与分析`}</h5>
      <span class="form-analysis-snapshot">${snapshot ? `后台快照：${archiveFormatDate(snapshot.snapshotAt)}` : "暂无后台快照"}</span>
    </div>
    <div class="form-snapshot-actions">
      <button type="button" class="btn is-secondary" onClick=${reload}>刷新表单数据</button>
      <span class=${`form-snapshot-sync-state is-${syncState}`}>后台任务：${archiveSyncStateLabel(syncState)}</span>
      ${archive && item.isExternalArchive && item.externalJobKey && html`<button
        type="button" class="btn is-primary"
        disabled=${bgBusy || sync.enabled !== true}
        title=${sync.enabled === true ? "启动一次后台归档同步" : "该后台任务未启用，请到任务配置中启用"}
        onClick=${async () => {
          setBgBusy(true);
          try {
            await archive.onBackgroundSync(load);
          } finally {
            if (alive.current) setBgBusy(false);
          }
        }}
      >${bgBusy ? "后台同步中..." : "运行后台归档同步"}</button>`}
    </div>
    <div class="form-summary-grid">
      ${[["总数", summary.total], ["已完成", summary.completed], ["未完成", summary.incomplete], ["逾期", summary.overdue]].map(([label, value]) => html`
        <div class="form-summary-card" key=${label}>
          <span class="form-summary-label">${label}</span>
          <strong class=${summaryClass[label] || "form-summary-value form-status-on-time"}>${String(Number(value) || 0)}</strong>
        </div>`)}
    </div>
    <p class="form-analysis-note">${dataFormKey === "aras_ncr_detail"
      ? "NCR 明细不计算逾期；整车 / 发动机工作表来源保留在明细行中。"
      : "按期推进 / 正常为绿色，逾期风险为橙黄色；交互式查询不会覆盖后台快照。"}</p>
    <section class=${`form-chart-tabs${locked ? " is-locked" : ""}`} aria-label="表单分析图表页签" ref=${chartsRef} data-form-interaction-locked=${locked ? "true" : "false"}>
      <div class="form-chart-tab-list" role="tablist">
        ${tabs.map(([key, label]) => html`<button
          type="button" key=${key} role="tab"
          class=${`form-chart-tab${key === state.activeTab ? " is-active" : ""}`}
          aria-selected=${key === state.activeTab ? "true" : "false"}
          onClick=${() => switchTab(key)}
        >${label}</button>`)}
      </div>
      <section class="form-chart-panel" role="tabpanel" aria-label=${(tabs.find(([key]) => key === state.activeTab) || [])[1] || "表单图表"}>
        <${FormFilterBar} key=${`filter-${shown.activeTab}`} data=${data} state=${shown} onReload=${reload} bump=${bump} />
        <${ChartPanelContent} data=${data} state=${shown} onReload=${reload} bump=${bump} />
      </section>
    </section>
    <div ref=${rowsRef} class=${locked ? "is-locked" : ""}>
      <${FormRowsTable} data=${data} rowsData=${view.rowsData} state=${shown} onReload=${reload} />
    </div>
    ${deliverableFormKey(item) && html`<${StatisticsSection} key=${formKey} formKey=${formKey} />`}`;
}
