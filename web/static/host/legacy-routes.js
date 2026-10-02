// Legacy hash → plugin route. Bookmarks and links from before the plugin
// refactor (`#overview`, `#aras-panel?mode=ewo&from=overview`,
// `#overview/deliverables/VPI-T2-D3`, ...) keep working. Import-free so it
// can be unit-tested under Node.

const PANEL_ROUTES = {
  "": "#p/project-overview/status",
  overview: "#p/project-overview/status",
  dashboard: "#p/project-overview/status",
  "overview-status-panel": "#p/project-overview/status",
  "overview-details-panel": "#p/project-overview/details",
  "overview-plan-panel": "#p/project-overview/plan",
  deliverables: "#p/deliverables/catalog",
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
