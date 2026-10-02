// Chart geometry and chart-config helpers (legacy renderTrendSvgChart,
// renderFormTrendSvgChart, renderDepartmentDoneChart, renderFormStatusBars,
// renderFormMatrixBars, buildChartLabelEditor). Import-free; node-tested.

/** Analysis trend chart (620x220): completed / incomplete polylines. */
export function analysisTrendGeometry(trend) {
  const width = 620;
  const heightTotal = 220;
  const padding = { top: 30, right: 35, bottom: 40, left: 45 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = heightTotal - padding.top - padding.bottom;
  const points = Array.isArray(trend) ? trend : [];
  let maxVal = 10;
  points.forEach((t) => {
    maxVal = Math.max(maxVal, t.total ?? 0, t.completed ?? 0, t.incomplete ?? 0);
  });
  maxVal = Math.max(10, Math.ceil(maxVal * 1.15));
  const grid = [];
  for (let s = 0; s <= 4; s += 1) {
    grid.push({
      y: padding.top + plotHeight - (s / 4) * plotHeight,
      label: String(Math.round((maxVal / 4) * s)),
      dashed: s !== 0,
    });
  }
  const completed = [];
  const incomplete = [];
  points.forEach((t, i) => {
    const x = padding.left + (points.length === 1 ? plotWidth / 2 : (i / (points.length - 1)) * plotWidth);
    const compVal = t.completed ?? 0;
    const incompVal = t.incomplete ?? 0;
    completed.push({ x, y: padding.top + plotHeight - (compVal / maxVal) * plotHeight, val: compVal, date: t.snapshotAt });
    incomplete.push({ x, y: padding.top + plotHeight - (incompVal / maxVal) * plotHeight, val: incompVal, date: t.snapshotAt });
  });
  const polyline = (list) => list.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  return {
    width,
    height: heightTotal,
    padding,
    plotWidth,
    plotHeight,
    maxVal,
    grid,
    completed,
    incomplete,
    completedLine: polyline(completed),
    incompleteLine: polyline(incomplete),
    axisY: padding.top + plotHeight + 18,
  };
}

export const FORM_TREND_SERIES = [
  ["total", "总数", "form-trend-total"],
  ["incomplete", "未完成数", "form-trend-incomplete"],
  ["overdue", "逾期数", "form-trend-overdue"],
];

/** Form quantity-trend chart (760x300): total / incomplete / overdue. */
export function formTrendGeometry(points) {
  const safePoints = Array.isArray(points) ? points : [];
  const padding = { top: 30, right: 35, bottom: 48, left: 46 };
  const width = 760 - padding.left - padding.right;
  const height = 300 - padding.top - padding.bottom;
  const maxValue = Math.max(1, ...safePoints.flatMap((p) => [Number(p.total) || 0, Number(p.incomplete) || 0, Number(p.overdue) || 0]));
  const coordinate = (index, value) => ({
    x: padding.left + (safePoints.length <= 1 ? width / 2 : (index / (safePoints.length - 1)) * width),
    y: padding.top + height - ((Number(value) || 0) / maxValue) * height,
  });
  const grid = [];
  for (let index = 0; index <= 4; index += 1) {
    grid.push({ y: padding.top + height - (index / 4) * height, label: String(Math.round((maxValue / 4) * index)) });
  }
  const series = FORM_TREND_SERIES.map(([key, label, className]) => {
    const coords = safePoints.map((point, index) => ({ ...coordinate(index, point[key]), day: point.day, value: Number(point[key]) || 0 }));
    return { key, label, className, coords, line: coords.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ") };
  });
  const axis = safePoints.map((point, index) => ({
    x: coordinate(index, 0).x,
    label: String(point.day || point.snapshotAt || "").slice(5, 10),
  }));
  return { padding, width, height, maxValue, grid, series, axis, axisY: padding.top + height + 24 };
}

/** Completed / incomplete bars: overall + departments sorted by total desc. */
export function departmentBars(summary, departments) {
  const entries = Object.entries(departments || {})
    .filter(([, value]) => value && typeof value === "object")
    .sort(([, a], [, b]) => (Number(b.total) || 0) - (Number(a.total) || 0));
  const overallTotal = Number(summary && summary.total) || 0;
  const empty = entries.length === 0 && (!summary || Number(summary.total) === 0);
  const overallCompleted = Number(summary && summary.completed) || 0;
  const overallIncomplete = Number(summary && summary.incomplete) || Math.max(0, overallTotal - overallCompleted);
  const maxTotal = Math.max(1, overallTotal, ...entries.map(([, d]) => Number(d.total) || 0));
  const pct = (n) => (maxTotal > 0 ? (n / maxTotal) * 100 : 0);
  const rows = entries.map(([name, d]) => {
    const total = Number(d.total) || 0;
    const completed = Number(d.completed) || 0;
    const incomplete = Number(d.incomplete) || Math.max(0, total - completed);
    return { name, total, completed, incomplete, completedPct: pct(completed), incompletePct: pct(incomplete) };
  });
  return {
    empty,
    overall: {
      total: overallTotal,
      completed: overallCompleted,
      incomplete: overallIncomplete,
      completedPct: pct(overallCompleted),
      incompletePct: pct(overallIncomplete),
    },
    rows,
  };
}

/** Totals of a custom-label chart (legacy renderCustomLabelChart). */
export function customChartTotals(chart) {
  const groups = chart && chart.groups && typeof chart.groups === "object" ? chart.groups : {};
  return Object.values(groups).reduce((acc, counts) => ({
    total: acc.total + (Number(counts && counts.total) || 0),
    completed: acc.completed + (Number(counts && counts.completed) || 0),
    incomplete: acc.incomplete + (Number(counts && counts.incomplete) || 0),
  }), { total: 0, completed: 0, incomplete: 0 });
}

/** Form status bars (on time / overdue / unknown) with a shared max. */
export function formStatusBars(entries) {
  const safe = Array.isArray(entries) ? entries : [];
  const max = Math.max(1, ...safe.map((e) => Number(e.onTime || 0) + Number(e.overdue || 0) + Number(e.unknown || 0)));
  return safe.map((entry) => {
    const onTime = Math.max(0, Number(entry && entry.onTime) || 0);
    const overdue = Math.max(0, Number(entry && entry.overdue) || 0);
    const unknown = Math.max(0, Number(entry && entry.unknown) || 0);
    return {
      label: String((entry && entry.label) || "未命名"),
      onTime,
      overdue,
      unknown,
      total: onTime + overdue + unknown,
      onTimePct: (onTime / max) * 100,
      overduePct: (overdue / max) * 100,
      unknownPct: (unknown / max) * 100,
    };
  });
}

export const FORM_STATE_PALETTE = [
  "#cc785c", "#6b7fb3", "#9a7bb0", "#56a08c", "#b8863b", "#7d8471",
  "#4d86c5", "#8a6aa8", "#2f8f83", "#9c6b8f", "#b0913f", "#5f7d61",
];
export const FORM_STATE_NEUTRAL = "#a8a29a";

export function formDimensionColor(label, index) {
  if (label === "CLOSE") return "var(--success)";
  if (label === "其他状态" || label === "未归集") return FORM_STATE_NEUTRAL;
  return FORM_STATE_PALETTE[index % FORM_STATE_PALETTE.length];
}

/** Stacked matrix bars; segments under 8% width get no inline count label. */
export function formMatrixBars(entries) {
  const safe = Array.isArray(entries) ? entries : [];
  const max = Math.max(1, ...safe.map((e) => Number(e && e.total) || 0));
  return safe.map((entry) => {
    const label = String((entry && entry.label) || "未命名");
    const total = Number(entry && entry.total) || 0;
    const segments = (Array.isArray(entry && entry.segments) ? entry.segments : [])
      .map((segment) => {
        const count = Math.max(0, Number(segment && segment.count) || 0);
        const width = (count / max) * 100;
        return {
          count,
          width,
          color: String((segment && segment.color) || FORM_STATE_NEUTRAL),
          title: `${label} · ${String((segment && segment.label) || "")}：${count} 条（占 ${Math.round((count / (total || 1)) * 100)}%）`,
          showLabel: width >= 8,
        };
      })
      .filter((segment) => segment.count > 0);
    return { label, total, filterable: !(entry && entry.filterable === false), segments };
  });
}

/** Department board rows for the "按科室" / "按状态" tabs. */
export function departmentBoardRows(matrix, boardTab) {
  const sectionRows = matrix.sections;
  const stageRows = matrix.stages;
  const stageColors = new Map(stageRows.map((row, index) => [row.label, formDimensionColor(row.label, index)]));
  const sectionColors = new Map(sectionRows.map((row, index) => [row.label, formDimensionColor(row.label, index)]));
  if (boardTab === "byStatus") {
    return {
      legend: sectionRows.map((row, index) => ({ label: String(row.label || ""), color: formDimensionColor(String(row.label || ""), index) })),
      filterKey: "stage",
      bars: formMatrixBars(stageRows.map((row) => ({
        label: row.label,
        total: row.total,
        filterable: row.label !== "其他状态",
        segments: (row.cells || []).map((cell) => ({ label: cell.label, count: cell.count, color: sectionColors.get(cell.label) || FORM_STATE_NEUTRAL })),
      }))),
    };
  }
  return {
    legend: stageRows.map((row, index) => ({ label: String(row.label || ""), color: formDimensionColor(String(row.label || ""), index) })),
    filterKey: "section",
    bars: formMatrixBars(sectionRows.map((row) => ({
      label: row.label,
      total: row.total,
      segments: (row.cells || []).map((cell) => ({ label: cell.label, count: cell.count, color: stageColors.get(cell.label) || FORM_STATE_NEUTRAL })),
    }))),
  };
}

export function sectionCountBars(counts, segmentLabel = "NCR明细") {
  const safe = Array.isArray(counts) ? counts : [];
  return formMatrixBars(safe.map((row, index) => ({
    label: row.label,
    total: Number(row.total) || 0,
    segments: [{ label: segmentLabel, count: Number(row.total) || 0, color: formDimensionColor(row.label, index) }],
  })));
}

// ---- NCR detail per-section cost table ----------------------------------------

/** 行 = 归集后科室；列 = 件数 + 测算/批准 工装费用（万元）与 单件成本变化（元）。 */
export const SECTION_COST_METRICS = [
  { key: "investmentEstimate", label: "测算工装费用（万元）" },
  { key: "investmentApproved", label: "批准工装费用（万元）" },
  { key: "vehicleChangeEstimate", label: "测算单件成本变化（元）" },
  { key: "vehicleChangeApproved", label: "批准单件成本变化（元）" },
];

/** 千分位 + 两位小数（四舍五入），负值带前导 "-"。 */
export function formatCostSum(value) {
  const rounded = Math.round(Number(value) * 100) / 100;
  const negative = rounded < 0;
  const absText = String(Math.abs(rounded));
  const dotAt = absText.indexOf(".");
  const intPart = dotAt >= 0 ? absText.slice(0, dotAt) : absText;
  const decPart = dotAt >= 0 ? absText.slice(dotAt) : "";
  return `${negative ? "-" : ""}${intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${decPart}`;
}

/**
 * charts.sectionCosts -> render model. 数值列带行内条（按列内 |值| 最大值归一）；
 * 负值（成本下降）显式标记；「无值」与「0」用 有值件数（count）区分：
 * count=0 → 无有效值（—），count>0 且 sum=0 → 真实 0。
 */
export function sectionCostRows(rows) {
  const safe = Array.isArray(rows) ? rows : [];
  const cellOf = (row, key) => (row && row.costs && row.costs[key]) || null;
  const columnMax = {};
  SECTION_COST_METRICS.forEach((metric) => {
    columnMax[metric.key] = Math.max(1, ...safe.map((row) => {
      const cell = cellOf(row, metric.key);
      const value = Number(cell && cell.sum);
      return Number.isFinite(value) && cell && cell.count ? Math.abs(value) : 0;
    }));
  });
  return safe.map((row) => {
    const label = String((row && row.label) || "未命名");
    return {
      label,
      total: Number(row && row.total) || 0,
      cells: SECTION_COST_METRICS.map((metric) => {
        const cell = cellOf(row, metric.key);
        const count = Number(cell && cell.count) || 0;
        const value = Number(cell && cell.sum) || 0;
        if (!count) return { key: metric.key, count: 0, empty: true, title: "该科室没有此指标的有效值" };
        return {
          key: metric.key,
          count,
          empty: false,
          negative: value < 0,
          text: formatCostSum(value),
          widthPct: Math.min(100, (Math.abs(value) / columnMax[metric.key]) * 100),
          title: `${label} · ${metric.label}：累计 ${formatCostSum(value)}（${count} 项有值）`,
        };
      }),
    };
  });
}

/** Integer count of rows outside the stage vocabulary (payload.unrecognizedStageCount); 0 when absent/invalid. */
export function unrecognizedStageCount(payload) {
  const count = payload && typeof payload === "object" ? Number(payload.unrecognizedStageCount) : NaN;
  return Number.isInteger(count) && count > 0 ? count : 0;
}

// ---- chart label editor -----------------------------------------------------

export function splitChartGroupMembers(text) {
  return String(text || "").split(/[,，、;；]/).map((member) => member.trim()).filter(Boolean);
}

/** Editor blocks -> PUT /chart-labels payload (drops fully empty rules/blocks). */
export function buildChartLabelsPayload(blocks) {
  return {
    labels: (blocks || [])
      .map((block) => ({
        label: block.label,
        sourceField: block.sourceField,
        groups: (block.groups || [])
          .map((rule) => ({ name: String(rule.name || "").trim(), members: splitChartGroupMembers(rule.members) }))
          .filter((rule) => rule.name || rule.members.length > 0),
        unmatched: block.unmatched,
      }))
      .filter((entry) => String(entry.label || "").trim() || entry.sourceField),
  };
}

/** Saved labels -> editor blocks. */
export function chartLabelBlocks(labels, fieldOptions) {
  const keys = (fieldOptions || []).map(([key]) => key);
  const firstField = keys.length ? keys[0] : "";
  return (Array.isArray(labels) ? labels : []).map((entry) => ({
    label: entry && entry.label ? String(entry.label) : "",
    // A <select> without a matching option shows (and submits) its first option.
    sourceField: entry && keys.includes(String(entry.sourceField)) ? String(entry.sourceField) : firstField,
    groups: (entry && Array.isArray(entry.groups) ? entry.groups : []).map((rule) => ({
      name: rule && rule.name ? String(rule.name) : "",
      members: Array.isArray(rule && rule.members) ? rule.members.join("、") : "",
    })),
    unmatched: entry && entry.unmatched ? String(entry.unmatched) : "keep",
    open: false,
  }));
}

export function chartFieldOptions(fields) {
  return (Array.isArray(fields) ? fields : []).map((field) => [
    String(field.key),
    field.label && field.label !== field.key ? `${field.label}（${field.key}）` : String(field.key),
  ]);
}
