// 交付物明细表 (legacy renderDeliverableDetails). Rows open the deliverable
// (or archive snapshot) detail page; board-hidden deliverables are skipped.
import { html } from "/static/host/vendor/preact-htm.js";
import { pageHash, redactText } from "../shared/client.js";
import { OVERVIEW_DETAIL_COLUMNS, detailRows, overviewIsEmpty } from "../shared/status-logic.js";
import { safeDisplayValue } from "../shared/status-data.js";

function open(row) {
  window.location.hash = pageHash(row.target.page, row.target.params);
}

function TableState({ state }) {
  let body;
  if (state.loading) body = html`<p class="loading">加载中</p>`;
  else if (state.error) body = html`<p class="error-msg" role="alert">加载失败：${redactText(state.error)}</p>`;
  else body = html`<p class="is-empty">暂无数据</p>`;
  return html`<tr><td colspan=${OVERVIEW_DETAIL_COLUMNS.length + 1}>${body}</td></tr>`;
}

function DetailRow({ row }) {
  const readOnlyText = row.editable ? "" : `手工字段只读：${redactText(row.readOnlyReason)}`;
  return html`<tr
    class="deliverable-detail-row"
    data-deliverable-index=${String(row.index)}
    data-manual-editable=${row.editable ? "true" : "false"}
    title=${row.editable ? undefined : `手工字段只读：${row.readOnlyReason}`}
    onClick=${(event) => { if (!event.target.closest("button")) open(row); }}
  >
    ${row.values.map((value, cellIndex) => html`<td key=${cellIndex} data-label=${OVERVIEW_DETAIL_COLUMNS[cellIndex]}>
      ${cellIndex === 1
        ? html`<span class=${`status-text is-${row.statusTone}`}>${safeDisplayValue(value)}</span>
          ${row.riskNote ? html`<span class="badge-risk-note" title=${row.riskNote.title}>${row.riskNote.text}</span>` : null}`
        : safeDisplayValue(value)}
      ${cellIndex === 0 && !row.editable ? html`<small class="detail-readonly-note">${readOnlyText}</small>` : null}
    </td>`)}
    <td class="detail-expand-cell">
      <button
        type="button"
        class="detail-expand"
        aria-label=${`查看 ${row.name} 明细`}
        onClick=${(event) => { event.stopPropagation(); open(row); }}
      >查看明细</button>
    </td>
  </tr>`;
}

export function DeliverableDetailsTable({ state }) {
  const rows = !state.loading && !state.error && !overviewIsEmpty(state.data) ? detailRows(state.data) : [];
  return html`<section class="overview-band details-table-band" aria-label="交付物明细表">
    <div class="band-head">
      <div>
        <p class="eyebrow">明细</p>
        <h4>交付物明细</h4>
      </div>
    </div>
    <div class="overview-table-wrap">
      <table class="overview-details-table">
        <thead>
          <tr>
            ${OVERVIEW_DETAIL_COLUMNS.map((title) => html`<th key=${title} scope="col">${title}</th>`)}
            <th scope="col"><span class="visually-hidden">展开控制</span></th>
          </tr>
        </thead>
        <tbody>
          ${rows.length ? rows.map((row) => html`<${DetailRow} key=${row.id} row=${row} />`) : html`<${TableState} state=${state} />`}
        </tbody>
      </table>
    </div>
  </section>`;
}
