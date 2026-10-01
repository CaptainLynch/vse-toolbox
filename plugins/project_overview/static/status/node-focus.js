// 当前节点 band (legacy window.VseNodeOverview.render from web/static/node-overview.js,
// which replaced renderPhaseSummary whenever that script was loaded).
import { html } from "/static/host/vendor/preact-htm.js";
import { pageHash } from "../shared/client.js";
import {
  buildNodeContext, deliverableDisplayItem, nodeDataIssueLabel, nodeFocusTitle, nodeItemLabel, nodeRiskRow, nodeTimingText,
} from "../shared/status-logic.js";
import { EditPlanLink } from "./timeline.js";

// Node membership rules are intentionally unset pending the business rule design
// (legacy passed none either), so the per-node sections stay hidden.
const NODE_RULES = {};

function DetailLink({ item }) {
  return html`<a class="node-detail-link" href=${pageHash("deliverable", { id: item.id })} aria-label=${`查看 ${item.name} 明细`}>查看明细 →</a>`;
}

function RiskList({ risks, dataIssues }) {
  return html`
    ${risks.length ? null : html`<p class="node-empty">现有可用数据中暂无风险或备注项。</p>`}
    ${risks.map((item) => {
      const row = nodeRiskRow(item);
      return html`<div key=${row.id} class="node-risk-row">
        <div><strong>${row.name}</strong><p>${row.text}</p><small>${row.meta}</small></div>
        <${DetailLink} item=${item} />
      </div>`;
    })}
    ${dataIssues.length ? html`<div class="node-data-warning">
      <strong>${dataIssues.length} 项数据待确认（同步异常或尚无有效数据）</strong>
      ${dataIssues.map((item) => html`<div key=${item.id} class="node-risk-row">
        <span>${item.name} · ${nodeDataIssueLabel(item)}</span><${DetailLink} item=${item} />
      </div>`)}
    </div>` : null}`;
}

export function NodeFocus({ data }) {
  const nodeData = { ...data, deliverables: data.deliverables.map(deliverableDisplayItem) };
  const ctx = buildNodeContext(nodeData, NODE_RULES);
  const head = html`<div class="node-focus-head">
    <div>
      <p class="eyebrow">当前节点</p>
      <h3 class="node-focus-title">${nodeFocusTitle(ctx, nodeData.milestones)}</h3>
    </div>
    <${EditPlanLink} withIcon=${false} />
  </div>`;
  if (!ctx.node) {
    return html`<div class="overview-phase-summary">${head}<p class="node-empty">可通过编辑主计划维护节点名称、日期、完成状态及顺序。</p></div>`;
  }
  return html`<div class="overview-phase-summary">
    ${head}
    <div class="node-focus-meta">
      <span class=${ctx.days < 0 ? "node-overdue" : ""}>${ctx.node.status} · ${nodeTimingText(ctx.days)}</span>
      <span>计划日期：${ctx.node.date || "未设置"}</span>
    </div>
    <p class="node-rule-note">按主计划顺序定位第一个未完成节点；逾期不会自动跳过。</p>
    ${ctx.ruleConfigured ? html`<div class="node-focus-grid">
      <section class="node-focus-section">
        <h4>本节点交付物</h4>
        <p class="node-counts">${ctx.total ? `已完成 ${ctx.completed} / ${ctx.total} 项 · ${ctx.progress}%` : "本节点规则未要求交付物"}</p>
        ${ctx.items.map((item) => html`<div key=${item.id} class="node-risk-row">
          <span>${item.name} · ${nodeItemLabel(item)}</span><${DetailLink} item=${item} />
        </div>`)}
      </section>
      <section class="node-focus-section">
        <h4>本节点风险与备注</h4>
        <${RiskList} risks=${ctx.risks} dataIssues=${ctx.dataIssues} />
      </section>
    </div>` : null}
  </div>`;
}
