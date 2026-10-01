// 项目概览 · 交付物明细 (plugin page). Parity port of the legacy
// #overview-deliverables-list-view: phase summary + 自动同步调度条, the
// deliverables table and the 外部来源交付物（参考） list.
import { html } from "/static/host/vendor/preact-htm.js";
import { useStylesheet } from "/static/host/kit.js";
import { OverviewTabs } from "./shared/tabs.js";
import { BandState, useProjectStatus } from "./shared/status-data.js";
import { detailsSummaryCells, overviewIsEmpty } from "./shared/status-logic.js";
import { SyncControlBar } from "./details/sync-bar.js";
import { DeliverableDetailsTable } from "./details/table.js";
import { ExternalDeliverablesReference } from "./details/external.js";

function DetailsSummary({ phase }) {
  return html`<div class="details-phase-bar">
    ${detailsSummaryCells(phase).map(([label, value]) => html`<div key=${label} class="details-phase-cell">
      <span class="details-phase-label">${label}</span>
      <strong class="details-phase-value">${value}</strong>
    </div>`)}
  </div>`;
}

export default function DetailsPage({ plugin }) {
  useStylesheet(`/plugins/${plugin.id}/static/overview.css`);
  const state = useProjectStatus();
  const ready = !state.loading && !state.error && !overviewIsEmpty(state.data);
  return html`<section class="project-overview" aria-label="交付物明细">
    <${OverviewTabs} current="details" />
    <div class="overview-deliverables-list-view">
      <section class="overview-band details-summary-band" aria-label="交付物明细摘要">
        ${ready
          ? html`<div class="overview-details-summary">
              <${DetailsSummary} phase=${state.data.phase} />
              <${SyncControlBar} onSynced=${() => state.reload({ quiet: true })} />
            </div>`
          : html`<${BandState} ...${state} onRetry=${state.retry} />`}
      </section>
      <${DeliverableDetailsTable} state=${state} />
      <${ExternalDeliverablesReference} />
    </div>
  </section>`;
}
