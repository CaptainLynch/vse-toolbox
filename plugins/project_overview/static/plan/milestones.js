// 主计划节点: readonly list and the edit form (add / remove / reorder rows).
import { html, useEffect, useRef } from "/static/host/vendor/preact-htm.js";
import { redactText } from "../shared/client.js";
import { MILESTONE_TYPE_OPTIONS, RESTORE_NOTICE, rowTypeValue } from "./logic.js";
import { PencilIcon } from "./phase.js";

const ICONS = {
  up: "M12 19V5m-7 7 7-7 7 7",
  down: "M12 5v14m7-7-7 7-7-7",
  delete: "M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6h14M10 11v6M14 11v6",
};

function IconButton({ label, icon, className, disabled, onClick }) {
  return html`<button type="button" class=${className} title=${label} aria-label=${label} disabled=${disabled} onClick=${onClick}>
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false">
      <path d=${ICONS[icon]} fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
    <span class="visually-hidden">${label}</span>
  </button>`;
}

export function MilestoneReadonlyList({ milestones, saving, restoreNotice, onEdit }) {
  return html`<div class="milestone-readonly">
    <div class="milestone-main-toolbar">
      <span class="milestone-count">共 ${milestones.length} 个节点</span>
      <button type="button" class="milestone-edit-btn" title="编辑主计划" aria-label="编辑主计划" disabled=${saving} onClick=${onEdit}>
        <${PencilIcon} /><span>编辑主计划</span>
      </button>
    </div>
    ${restoreNotice && html`<p class="edit-request-info">${RESTORE_NOTICE}</p>`}
    <ul class="milestone-main-list">
      ${milestones.map((item, index) => html`<li key=${item.id ?? index} class="milestone-main-row">
        <span class=${`milestone-type-dot is-${item.type || "planned"}`}></span>
        <span class="milestone-main-copy">
          <strong class="milestone-main-name">${redactText(item.name)}</strong>
          ${item.date
            ? html`<time class="milestone-main-date" dateTime=${item.date}>${item.date}</time>`
            : html`<span class="milestone-main-date is-unscheduled">待排期</span>`}
          <span class="milestone-main-status">${item.status || ""}</span>
        </span>
        <span class="milestone-main-order">${index + 1}</span>
      </li>`)}
    </ul>
  </div>`;
}

function Field({ row, field, label, error, disabled, onField }) {
  let control;
  if (field === "type") {
    control = html`<select name="type" value=${rowTypeValue(row)} disabled=${disabled} onChange=${(event) => onField(row.localId, field, event.currentTarget.value)}>
      ${MILESTONE_TYPE_OPTIONS.map((option) => html`<option key=${option.value} value=${option.value}>${option.label}</option>`)}
    </select>`;
  } else {
    control = html`<input
      name=${field}
      type=${field === "date" ? "date" : "text"}
      maxLength=${field === "name" ? 100 : undefined}
      value=${row[field]}
      disabled=${disabled}
      aria-invalid=${error ? "true" : undefined}
      onInput=${(event) => onField(row.localId, field, event.currentTarget.value)}
    />`;
  }
  return html`<label class=${`milestone-field${error ? " is-invalid" : ""}`} data-field=${field}>
    <span class="milestone-field-label">${label}</span>
    ${control}
    ${error && html`<small class="field-error">${error}</small>`}
  </label>`;
}

const FIELDS = [
  ["name", "节点名称"],
  ["date", "节点日期"],
  ["type", "节点类型"],
];

/**
 * focus: {localId} | {add: true} | {invalid: true} | {first: true}, with a
 * `tick` so the same request can be repeated; applied after render.
 */
export function MilestoneEditForm({ rows, errors, message, saving, focus, onField, onMove, onDelete, onAdd, onSave, onCancel }) {
  const formRef = useRef(null);
  useEffect(() => {
    const form = formRef.current;
    if (!form || !focus) return;
    let target = null;
    if (focus.add) target = form.querySelector(".milestone-add-btn");
    else if (focus.invalid) target = form.querySelector(".milestone-field.is-invalid input, .milestone-field.is-invalid select");
    else if (focus.first) target = form.querySelector("input, select");
    else if (focus.localId) {
      const row = Array.from(form.querySelectorAll(".milestone-edit-row")).find((el) => el.dataset.localId === focus.localId);
      target = row ? row.querySelector("input, select") : null;
    }
    if (target) target.focus();
  }, [focus]);

  return html`<form class="milestone-edit-form" noValidate ref=${formRef} onSubmit=${(event) => { event.preventDefault(); onSave(); }}>
    <div class="milestone-edit-list">
      ${rows.map((row, index) => html`<div key=${row.localId} class="milestone-edit-row" data-local-id=${row.localId}>
        <span class="milestone-edit-order">${index + 1}</span>
        ${FIELDS.map(([field, label]) => html`<${Field}
          key=${field}
          row=${row}
          field=${field}
          label=${label}
          error=${errors[`${row.localId}.${field}`]}
          disabled=${saving}
          onField=${onField}
        />`)}
        <div class="milestone-row-actions">
          <${IconButton} label="上移" icon="up" className="milestone-icon-btn milestone-move-btn" disabled=${saving || index === 0} onClick=${() => onMove(row.localId, -1)} />
          <${IconButton} label="下移" icon="down" className="milestone-icon-btn milestone-move-btn" disabled=${saving || index === rows.length - 1} onClick=${() => onMove(row.localId, 1)} />
          <${IconButton} label=${`删除 ${row.name || "节点"}`} icon="delete" className="milestone-icon-btn milestone-delete-btn" disabled=${saving} onClick=${() => onDelete(row.localId)} />
        </div>
      </div>`)}
    </div>
    <div class="milestone-form-actions">
      <button type="button" class="edit-save-btn milestone-save-btn" disabled=${saving} onClick=${onSave}>${saving ? "保存中..." : "保存"}</button>
      <button type="button" class="edit-cancel-btn milestone-cancel-btn" disabled=${saving} onClick=${onCancel}>取消</button>
      <button type="button" class="milestone-add-btn" disabled=${saving} onClick=${onAdd}>新增节点</button>
      <div class="edit-request-message milestone-request-message" aria-live="polite">
        ${message && html`<p class=${message.tone === "info" ? "edit-request-info" : "edit-request-error"}>${message.text}</p>`}
      </div>
    </div>
  </form>`;
}
