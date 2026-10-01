// 主计划时间轴 band (legacy renderMilestoneTimeline).
import { html } from "/static/host/vendor/preact-htm.js";
import { pageHash } from "../shared/client.js";
import { buildNodeContext, buildTimelineEntries } from "../shared/status-logic.js";

export function PencilIcon() {
  return html`<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false">
    <path fill="currentColor" d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z" />
  </svg>`;
}

/** 编辑主计划 now navigates to the plan page (legacy switched to the 主计划维护 tab). */
export function EditPlanLink({ withIcon = true }) {
  return html`<a class="timeline-edit-btn" href=${pageHash("plan", { edit: "milestones" })} title="编辑主计划" aria-label="编辑主计划">
    ${withIcon ? html`<${PencilIcon} />` : null}<span>编辑主计划</span>
  </a>`;
}

export function MilestoneTimeline({ data }) {
  const phase = data.phase;
  const activeNode = buildNodeContext(data).node;
  const entries = buildTimelineEntries(data, activeNode ? activeNode.id : null);
  return html`<div>
    <div class="band-head">
      <div>
        <p class="eyebrow">项目名称</p>
        <h4>${phase.displayName || `${phase.id} 主计划时间轴`}</h4>
      </div>
      <div class="timeline-head-actions">
        <p class="timeline-meta">当前阶段关键节点 · ${phase.startDate} 至 ${phase.endDate} · 当前日期 ${phase.today}</p>
        <${EditPlanLink} />
      </div>
    </div>
    <div class="timeline-wrap">
      <div class="timeline-months" aria-hidden="true">
        ${(data.months || []).map((month) => html`<span key=${month}>${month}</span>`)}
      </div>
      <div class="timeline-rail" role="list">
        <div class="timeline-line" aria-hidden="true"></div>
        ${entries.map((entry, index) => (entry.type === "today"
          ? html`<div key="today" class="today-marker" style=${{ "--x": String(entry.x) }}>
              <span class="today-label">${entry.label}</span>
            </div>`
          : html`<div
              key=${`m-${entry.id ?? index}`}
              class=${`milestone-node is-${entry.nodeType}${entry.active ? " is-active-node" : ""}`}
              role="listitem"
              aria-current=${entry.active ? "step" : undefined}
              style=${{ "--x": String(entry.x) }}
            >
              <span class="milestone-dot"></span>
              <span class="milestone-copy">
                <strong class="milestone-name">${entry.name}</strong>
                <time class="milestone-date">${entry.dateText}</time>
                <small class="milestone-status">${entry.nodeStatus}</small>
                ${entry.active ? html`<span class="node-current-label">当前节点</span>` : null}
              </span>
            </div>`))}
      </div>
    </div>
  </div>`;
}
