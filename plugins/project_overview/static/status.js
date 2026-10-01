// 项目概览 · 项目状态 (plugin page). Parity port of the legacy
// #overview-status-panel: 主计划时间轴, 当前节点 and 全项目交付物完成状态.
// Reads GET /api/project-status; editing lives on the 主计划维护 / 交付物详情 pages.
import { html } from "/static/host/vendor/preact-htm.js";
import { useStylesheet } from "/static/host/kit.js";
import { OverviewTabs } from "./shared/tabs.js";
import { BandState, useProjectStatus } from "./shared/status-data.js";
import { overviewIsEmpty } from "./shared/status-logic.js";
import { MilestoneTimeline } from "./status/timeline.js";
import { NodeFocus } from "./status/node-focus.js";
import { DeliverableProgressBand } from "./status/progress.js";

export default function StatusPage({ plugin }) {
  useStylesheet(`/plugins/${plugin.id}/static/overview.css`);
  const state = useProjectStatus();
  const ready = !state.loading && !state.error && state.data && !overviewIsEmpty(state.data);
  const placeholder = html`<${BandState} ...${state} onRetry=${state.retry} />`;
  return html`<section class="project-overview" aria-label="项目状态概览">
    <${OverviewTabs} current="status" />
    <section class="milestone-timeline overview-band" aria-label="主计划时间轴">
      ${ready ? html`<${MilestoneTimeline} data=${state.data} />` : placeholder}
    </section>
    <section class="phase-summary overview-band" aria-label="当前节点、交付物与风险">
      ${ready ? html`<${NodeFocus} data=${state.data} />` : placeholder}
    </section>
    <${DeliverableProgressBand} state=${state} />
  </section>`;
}
