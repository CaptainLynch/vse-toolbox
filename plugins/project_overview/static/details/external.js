// 外部来源交付物（参考） (legacy renderExternalDeliverablesReference): catalog
// entries with their linked DEL code and archive snapshot link. Reference only.
import { html, useEffect, useState } from "/static/host/vendor/preact-htm.js";
import { pageHash, request } from "../shared/client.js";
import { externalReferenceRows } from "../shared/status-logic.js";
import { safeDisplayValue } from "../shared/status-data.js";

export function ExternalDeliverablesReference() {
  const [state, setState] = useState({ rows: null, error: false });
  useEffect(() => {
    let alive = true;
    request("/api/deliverables/catalog")
      .then((data) => {
        if (alive) setState({ rows: externalReferenceRows(data && data.deliverables), error: false });
      })
      .catch(() => { if (alive) setState({ rows: null, error: true }); });
    return () => { alive = false; };
  }, []);
  return html`<section class="overview-band external-deliverables-band" aria-label="外部来源交付物（参考）">
    <div class="band-head">
      <div>
        <p class="eyebrow">参考</p>
        <h4>外部来源交付物（参考）</h4>
      </div>
      <span class="external-deliverables-note">快照仅参考，不计入完成统计</span>
    </div>
    <ul class="external-deliverables-list">
      ${state.error ? html`<li class="external-deliverables-error">外部来源交付物目录读取失败</li>` : null}
      ${(state.rows || []).map((row, index) => html`<li key=${`${row.jobKey}-${index}`} class="external-deliverables-item">
        <span class="external-deliverables-name">${safeDisplayValue(row.name)}</span>
        <span class="external-deliverables-code">${row.code}</span>
        ${row.jobKey ? html`<a class="external-deliverables-link" href=${pageHash("archive-deliverable", { job: row.jobKey })}>查看同步快照</a>` : null}
      </li>`)}
    </ul>
  </section>`;
}
