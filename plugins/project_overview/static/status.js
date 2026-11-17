// 项目概览 · 项目状态 (plugin page). Parity port of the legacy
// #overview-status-panel: 主计划时间轴, 当前节点 and 全项目交付物完成状态.
// Reads GET /api/project-status; editing lives on the 主计划维护 / 交付物详情 pages.
import { html } from "/static/host/vendor/preact-htm.js";
import { useStylesheet } from "/static/host/kit.js";
import { OverviewTabs } from "./shared/tabs.js";
import { BandState, useProjectStatus } from "./shared/status-data.js";
import { EditPlanLink, MilestoneTimeline } from "./status/timeline.js";
import { NodeFocus } from "./status/node-focus.js";
import { DeliverableProgressBand } from "./status/progress.js";

// 阶段已存在但主计划没有任何节点：旧页面显示「主计划待设置」，这里补齐同一术语，
// 而不是退化成整页「暂无数据」——否则阶段周期与交付物数据会被一起藏掉。
function PlanUnconfigured() {
  return html`<div class="overview-plan-unconfigured">
    <div class="band-head">
      <div>
        <p class="eyebrow">项目名称</p>
        <h4>主计划待设置</h4>
      </div>
      <div class="timeline-head-actions"><${EditPlanLink} withIcon=${false} /></div>
    </div>
    <p class="node-empty">尚未配置主计划节点。设置阶段周期与关键节点后，这里会显示主计划时间轴与当前节点。</p>
  </div>`;
}

export default function StatusPage({ plugin }) {
  useStylesheet(`/plugins/${plugin.id}/static/overview.css`);
  const state = useProjectStatus();
  const phase = state.data && state.data.phase ? state.data.phase : null;
  // 只要阶段读到了就算 ready：主计划节点可以为空（未配置），交付物也可以为空。
  const ready = !state.loading && !state.error && Boolean(phase);
  const milestones = Array.isArray(state.data && state.data.milestones) ? state.data.milestones : [];
  const deliverables = Array.isArray(state.data && state.data.deliverables) ? state.data.deliverables : [];
  const viewData = state.data ? { ...state.data, milestones, deliverables } : null;
  const planReady = ready && milestones.length > 0;
  const placeholder = html`<${BandState} ...${state} onRetry=${state.retry} />`;
  return html`<section class="project-overview" aria-label="项目状态概览">
    <${OverviewTabs} current="status" />
    <div class="overview-tabpanel" role="tabpanel" aria-label="项目状态">
    <section class="milestone-timeline overview-band" aria-label="主计划时间轴">
      ${planReady
        ? html`<${MilestoneTimeline} data=${viewData} />`
        : (ready ? html`<${PlanUnconfigured} />` : placeholder)}
    </section>
    <section class="phase-summary overview-band" aria-label="当前节点、交付物与风险">
      ${ready ? html`<${NodeFocus} data=${viewData} />` : placeholder}
    </section>
    <${DeliverableProgressBand} state=${state} />
    </div>
  </section>`;
}
