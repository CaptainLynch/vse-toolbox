// 全项目交付物完成状态（参考） band (legacy renderDeliverableProgress).
import { html, useState } from "/static/host/vendor/preact-htm.js";
import { pageHash } from "../shared/client.js";
import { autoHiddenHint, overviewIsEmpty, visibleProgressRings } from "../shared/status-logic.js";
import { BandState } from "../shared/status-data.js";

// Kept for the session like the legacy module-level filter value.
let rememberedFilter = "all";

function openDetail(id) {
  window.location.hash = pageHash("deliverable", { id });
}

function ProgressRing({ ring }) {
  const onKeyDown = (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openDetail(ring.id);
    }
  };
  return html`<article
    class="progress-ring is-clickable"
    role="button"
    tabindex="0"
    aria-label=${ring.ariaLabel}
    title=${ring.title || undefined}
    onClick=${() => openDetail(ring.id)}
    onKeyDown=${onKeyDown}
  >
    <span class="ring-visual" style=${{ "--progress": String(ring.progress), "--ring-color": ring.color }}>
      <span class="ring-center">${ring.center}</span>
    </span>
    <span class="ring-copy">
      <strong class="ring-name">${ring.name}</strong>
      <span class=${`ring-status is-${ring.tone}`}>${ring.statusText}</span>
      <span class="ring-date">${ring.dateLabel}</span>
    </span>
  </article>`;
}

export function DeliverableProgressBand({ state }) {
  const [filter, setFilterState] = useState(rememberedFilter);
  const setFilter = (value) => {
    rememberedFilter = value;
    setFilterState(value);
  };
  const ready = !state.loading && !state.error && !overviewIsEmpty(state.data);
  const data = state.data;
  return html`<section class="deliverable-status-band overview-band" aria-label="交付物完成状态">
    <div class="band-head">
      <div>
        <p class="eyebrow">交付物</p>
        <h4>全项目交付物完成状态（参考）</h4>
      </div>
      ${ready ? html`<label class="deliverable-display-filter">
        <span class="deliverable-display-filter-label">显示</span>
        <select
          class="deliverable-display-filter-select"
          aria-label="交付物显示筛选"
          value=${filter}
          onChange=${(event) => setFilter(event.currentTarget.value)}
        >
          <option value="all">全部交付物</option>
          <option value="auto" title="已完成且项目推进越过其关联主计划节点的交付物不再展示">按节点状态自动显示</option>
        </select>
        <span class="deliverable-auto-hidden">${autoHiddenHint(data.deliverables, filter, data)}</span>
      </label>` : null}
    </div>
    <div class="deliverable-progress-grid">
      ${ready
        ? visibleProgressRings(data, filter).map((ring) => html`<${ProgressRing} key=${ring.id} ring=${ring} />`)
        : html`<${BandState} ...${state} onRetry=${state.retry} />`}
    </div>
  </section>`;
}
