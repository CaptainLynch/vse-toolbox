// Legacy hash → plugin route. Bookmarks and links from before the plugin
// refactor (`#overview`, `#aras-panel?mode=ewo&from=overview`,
// `#overview/deliverables/VPI-T2-D3`, ...) keep working. Import-free so it
// can be unit-tested under Node.

const PANEL_ROUTES = {
  // v2：没有指定页面时进入「今天」。
  "": "#p/workbench/today",
  overview: "#p/project-overview/status",
  dashboard: "#p/project-overview/status",
  "overview-status-panel": "#p/project-overview/status",
  "overview-details-panel": "#p/project-overview/details",
  "overview-plan-panel": "#p/project-overview/plan",
  deliverables: "#p/project-overview/details",
  "aras-panel": "#p/system-query/query",
  aras: "#p/system-query/query",
  "system-query": "#p/system-query/query",
  query: "#p/system-query/query",
  "excel-tasks": "#p/excel-tasks/workspace",
  excel: "#p/excel-tasks/workspace",
  "scheduled-archive": "#p/scheduled-archive/jobs",
  archive: "#p/scheduled-archive/jobs",
  scheduled: "#p/scheduled-archive/jobs",
  "settings-panel": "#p/settings/general",
  settings: "#p/settings/general",
};

const OVERVIEW_TABS = { status: "status", details: "details", plan: "plan" };

// 「表单」独立页已降级为专家模式（plugin.json nav expert:true），日常入口在交付物详情。
// 旧书签按表单键落到对应交付物详情；没有具体表单时落到交付物明细，不返回 null。
const FORMS_LIST = "#p/project-overview/details";
const FORM_DETAIL_IDS = {
  ewo: "VPI-T2-D3",
  paa: "VPI-T2-D6",
  "ncr-progress": "VPI-T2-D7",
  "ncr-detail": "VPI-T2-D8",
  "tdc-data-model": "VPI-T2-D5",
  "tdc-sor": "VPI-T2-D2",
};

function formDetailId(key) {
  const normalized = String(key || "").trim().toLowerCase().replace(/_/g, "-");
  return FORM_DETAIL_IDS[normalized] || null;
}

function withQuery(target, params) {
  const query = params.toString();
  return query ? `${target}?${query}` : target;
}

/** Return the `#p/...` hash a legacy hash maps to, or null when it is not a legacy hash. */
export function legacyRedirect(hash) {
  const raw = String(hash || "").replace(/^#/, "");
  if (raw.startsWith("p/")) return null;
  const [path, query = ""] = raw.split("?");
  const params = new URLSearchParams(query);

  // 旧「表单」面板/插件书签：`#forms`、`#form-panel?mode=ewo`、
  // `#deliverable-forms/tdc_data_model` 等。统一落到交付物详情，绝不 404。
  const forms = path.match(/^(?:deliverable[-_]forms|forms?|form-panel)(?:\/([^/]+))?$/);
  if (forms) {
    const key = forms[1] || params.get("mode") || params.get("form");
    const id = key && key !== "index" ? formDetailId(key) : null;
    params.delete("mode");
    params.delete("form");
    if (id) {
      params.set("id", id);
      return withQuery("#p/project-overview/deliverable", params);
    }
    return withQuery(FORMS_LIST, params);
  }

  const deliverable = path.match(/^(?:overview\/)?deliverables?\/([^/]+)$/) || path.match(/^deliverable-detail\/([^/]+)$/);
  if (deliverable) {
    params.set("id", decodeURIComponent(deliverable[1]));
    return withQuery("#p/project-overview/deliverable", params);
  }
  const archive = path.match(/^archive-deliverable\/([^/]+)$/);
  if (archive) {
    params.set("job", decodeURIComponent(archive[1]));
    return withQuery("#p/project-overview/archive-deliverable", params);
  }
  if (path === "overview" && OVERVIEW_TABS[params.get("tab")]) {
    const tab = OVERVIEW_TABS[params.get("tab")];
    params.delete("tab");
    return withQuery(`#p/project-overview/${tab}`, params);
  }
  const target = PANEL_ROUTES[path];
  return target ? withQuery(target, params) : null;
}
