// Schema page renderers. A plugin declares `"kind": "schema"` in plugin.json
// and ships `static/pages/<page>.json`; the shell renders it with no plugin JS.
//
// Analysis schema (L1):
// {
//   "renderer": "analysis",
//   "title": "...", "description": "...",
//   "source": "rows",                 // GET /api/p/<plugin>/<source> → {rows: [...], updatedAt?}
//   "filterMode": "client",           // or "server": filter values are sent as query params
//   "filters": [{"key", "label", "type": "text|select|date", "options"?: [...], "optionsFromRows"?: true,
//                "match"?: "contains|eq|gte|lte"}],
//   "charts": [{"type": "doneBars", "id", "title", "groupBy": "<row key>",
//               "doneField": "<row key: true 完成 / false 未完成 / null 终态>"}],
//   "columns": [{"key", "title", "width"?}],
//   "rowKey": "id"
// }
import { pluginApi, useResource } from "./api.js";
import { ChartTabs, DataTable, DoneBars, FilterBar, StateBlock, html } from "./kit.js";
import { useMemo, useState } from "./vendor/preact-htm.js";

function matches(row, field, wanted) {
  if (wanted === undefined || wanted === null || wanted === "") return true;
  const raw = row[field.key];
  const value = raw === null || raw === undefined ? "" : String(raw);
  const match = field.match || (field.type === "text" || !field.type ? "contains" : "eq");
  if (match === "contains") return value.toLowerCase().includes(String(wanted).toLowerCase());
  if (match === "gte") return value !== "" && value >= String(wanted);
  if (match === "lte") return value !== "" && value <= String(wanted);
  return value === String(wanted);
}

export function applyClientFilters(rows, fields, values) {
  return rows.filter((row) => fields.every((field) => matches(row, field, values[field.key])));
}

function groupName(row, groupBy) {
  const value = row[groupBy];
  return value === null || value === undefined || value === "" ? "未填写" : String(value);
}

export function summarizeDone(rows, groupBy, doneField) {
  const summary = { total: 0, completed: 0, incomplete: 0 };
  const groups = {};
  rows.forEach((row) => {
    const name = groupName(row, groupBy);
    const group = groups[name] || (groups[name] = { total: 0, completed: 0, incomplete: 0 });
    // doneField 三态：true 完成；null 终态（只计入总数）；其他值算未完成。
    const done = row[doneField];
    [summary, group].forEach((bucket) => {
      bucket.total += 1;
      if (done === true) bucket.completed += 1;
      else if (done !== null) bucket.incomplete += 1;
    });
  });
  return { summary, groups };
}

function withRowOptions(fields, rows) {
  return fields.map((field) => {
    if (!field.optionsFromRows) return field;
    const values = [...new Set(rows.map((row) => row[field.key]).filter((v) => v !== null && v !== undefined && v !== ""))];
    values.sort((a, b) => String(a).localeCompare(String(b), "zh-CN"));
    return { ...field, type: "select", options: values.map(String) };
  });
}

export function AnalysisPage({ pluginId, schema }) {
  const filters = schema.filters || [];
  const serverMode = schema.filterMode === "server";
  const [values, setValues] = useState({});
  const [selection, setSelection] = useState({});
  const client = pluginApi(pluginId);
  const resource = useResource(client.url(schema.source), serverMode ? values : null);
  const allRows = (resource.data && resource.data.rows) || [];

  const filtered = useMemo(
    () => (serverMode ? allRows : applyClientFilters(allRows, filters, values)),
    [allRows, values, serverMode],
  );
  const charts = schema.charts || [];
  const tableRows = useMemo(() => {
    let rows = filtered;
    charts.forEach((chart) => {
      const picked = selection[chart.id];
      if (picked != null) rows = rows.filter((row) => groupName(row, chart.groupBy) === picked);
    });
    return rows;
  }, [filtered, selection]);

  const tabs = charts.filter((chart) => chart.type === "doneBars").map((chart) => ({
    id: chart.id,
    title: chart.title,
    render: () => {
      const { summary, groups } = summarizeDone(filtered, chart.groupBy, chart.doneField);
      return html`<${DoneBars}
        title=${chart.title} summary=${summary} groups=${groups}
        selected=${selection[chart.id] ?? null}
        onSelect=${(name) => setSelection((prev) => ({ ...prev, [chart.id]: name }))}
      />`;
    },
  }));

  const updatedAt = resource.data && resource.data.updatedAt;
  return html`<div class="vk-page">
    <header class="vk-page-header">
      <div>
        <h2>${schema.title}</h2>
        ${schema.description && html`<p class="vk-muted">${schema.description}</p>`}
      </div>
      <div class="vk-page-actions">
        ${updatedAt && html`<span class="vk-muted">数据更新于 ${updatedAt}</span>`}
        <button type="button" class="vk-btn" onClick=${resource.reload} disabled=${resource.loading}>刷新</button>
      </div>
    </header>
    ${filters.length > 0 && html`<${FilterBar}
      fields=${withRowOptions(filters, allRows)} value=${values}
      onChange=${(next) => { setValues(next); setSelection({}); }}
    />`}
    <${StateBlock} loading=${resource.loading && !resource.data} error=${resource.error} onRetry=${resource.reload} />
    ${resource.data && html`
      ${tabs.length > 0 && html`<${ChartTabs} tabs=${tabs} />`}
      <${DataTable} columns=${schema.columns || []} rows=${tableRows} rowKey=${schema.rowKey || "id"} />
    `}
  </div>`;
}

export const SCHEMA_RENDERERS = { analysis: AnalysisPage };
