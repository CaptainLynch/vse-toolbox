// Tab strip shared by the status / details / plan pages (legacy overview-switch).
import { html } from "/static/host/vendor/preact-htm.js";
import { pageHash } from "./client.js";

const TABS = [
  { page: "status", title: "项目状态" },
  { page: "details", title: "交付物明细" },
  { page: "plan", title: "主计划维护" },
];

export function OverviewTabs({ current }) {
  return html`<div class="overview-switch" role="tablist" aria-label="概览视图">
    ${TABS.map((tab) => html`<a
      key=${tab.page}
      class=${`overview-tab${tab.page === current ? " active" : ""}`}
      role="tab"
      aria-selected=${tab.page === current ? "true" : "false"}
      href=${pageHash(tab.page)}
    >${tab.title}</a>`)}
  </div>`;
}
