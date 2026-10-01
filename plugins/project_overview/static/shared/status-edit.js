// Manual deliverable editors (legacy startDeliverableEdit / renderDeliverableEditForm /
// saveDeliverableChanges and startInlineNoteEdit). In the legacy UI both editors
// were only reachable from the per-deliverable detail page; they live here so that
// page can mount them. Both PATCH /api/project-status/deliverables/<id> with the
// record's updatedAt (409 = concurrent update / mapped read-only) and hand the
// returned projectStatus to `onSaved`.
import { html, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { redactText, request } from "./client.js";
import {
  DELIVERABLE_EDIT_FIELDS, OVERVIEW_STATUS_OPTIONS, deliverableManualEditState, deliverablePatchPayload, draftDirty,
  draftValuesFromItem, mapServerFieldErrors, notePatchPayload, overviewErrorText, overviewIsEmpty, validateDeliverableDraft,
} from "./status-logic.js";
import { safeDisplayValue } from "./status-data.js";

const deliverablePath = (id) => `/api/project-status/deliverables/${encodeURIComponent(String(id))}`;

export const DISCARD_CONFIRM_TEXT = "有未保存的更改，确定放弃吗？";

/** Warn on page unload while `dirty` (legacy beforeunload guard). */
export function useUnsavedGuard(dirty) {
  useEffect(() => {
    if (!dirty) return undefined;
    const guard = (event) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [dirty]);
}

export function ReadOnlyNotice({ item, className = "detail-readonly-notice" }) {
  const state = deliverableManualEditState(item);
  if (state.editable) return null;
  return html`<p class=${className}>手工字段只读：${redactText(state.reason)}</p>`;
}

function FieldControl({ name, value, onInput }) {
  const id = `overview-edit-${name}`;
  if (name === "status") {
    return html`<select id=${id} name=${name} value=${value} onChange=${(e) => onInput(e.currentTarget.value)}>
      ${OVERVIEW_STATUS_OPTIONS.map((option) => html`<option key=${option} value=${option}>${option}</option>`)}
    </select>`;
  }
  if (name === "note") {
    return html`<textarea id=${id} name=${name} rows="3" value=${value} onInput=${(e) => onInput(e.currentTarget.value)}></textarea>`;
  }
  if (name === "progress") {
    return html`<input id=${id} name=${name} type="number" min="0" max="100" step="1" inputmode="numeric"
      value=${value} onInput=${(e) => onInput(e.currentTarget.value)} />`;
  }
  const type = name === "plannedDate" || name === "actualDate" ? "date" : "text";
  return html`<input id=${id} name=${name} type=${type} value=${value} onInput=${(e) => onInput(e.currentTarget.value)} />`;
}

/**
 * Row editor. Props: item (raw payload deliverable), phaseId, onSaved(projectStatus),
 * onCancel(), onDirtyChange?(dirty).
 */
export function DeliverableEditForm({ item, phaseId, onSaved, onCancel, onDirtyChange }) {
  const [saved] = useState(() => draftValuesFromItem(item));
  const [values, setValues] = useState(() => draftValuesFromItem(item));
  const [errors, setErrors] = useState({});
  const [requestMessage, setRequestMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const formRef = useRef(null);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  const dirty = draftDirty(saved, values);
  useUnsavedGuard(dirty);
  useEffect(() => { if (onDirtyChange) onDirtyChange(dirty); }, [dirty]);
  useEffect(() => {
    const first = formRef.current && formRef.current.querySelector("#overview-edit-status");
    if (first) first.focus();
  }, []);
  useEffect(() => {
    const invalid = formRef.current && formRef.current.querySelector(".edit-field.is-invalid input, .edit-field.is-invalid select, .edit-field.is-invalid textarea");
    if (invalid && !saving) invalid.focus();
  }, [errors]);

  const manual = deliverableManualEditState(item);
  if (!manual.editable) {
    return html`<div class="detail-edit-readonly"><${ReadOnlyNotice} item=${item} /></div>`;
  }

  const setField = (name, value) => {
    setValues((prev) => ({ ...prev, [name]: value }));
    setErrors((prev) => {
      if (!prev[name]) return prev;
      const next = { ...prev };
      delete next[name];
      return next;
    });
  };

  const save = async (event) => {
    if (event) event.preventDefault();
    if (saving) return;
    const found = validateDeliverableDraft(values);
    setErrors(found);
    if (Object.keys(found).length) return;
    setSaving(true);
    setRequestMessage("");
    try {
      const data = await request(deliverablePath(item.id), { method: "PATCH", body: deliverablePatchPayload(values, item) });
      const projectStatus = data && data.projectStatus;
      if (!projectStatus || overviewIsEmpty(projectStatus)) throw new Error("保存响应缺少完整的项目状态，请重试");
      if (onDirtyChange) onDirtyChange(false);
      if (onSaved) onSaved(projectStatus);
    } catch (error) {
      if (!alive.current) return;
      setRequestMessage(redactText(overviewErrorText(error)));
      if (error && error.fields) setErrors((prev) => ({ ...prev, ...mapServerFieldErrors(error.fields) }));
      setSaving(false);
    }
  };

  const meta = [
    ["展示编号", safeDisplayValue(item.displayCode || item.id)],
    ["交付物名称", safeDisplayValue(item.name)],
    ["所属阶段", safeDisplayValue(phaseId)],
    ["数据来源", safeDisplayValue(item.source)],
  ];
  return html`<form id="overview-edit-form" class="detail-edit-form" novalidate ref=${formRef} onSubmit=${save}>
    <dl class="edit-readonly-grid">
      ${meta.map(([label, value]) => html`<dt key=${`t-${label}`}>${label}</dt><dd key=${`d-${label}`}>${value}</dd>`)}
    </dl>
    <div class="edit-form-grid">
      ${DELIVERABLE_EDIT_FIELDS.map(([name, label]) => html`<div
        key=${name}
        class=${`edit-field${name === "note" ? " edit-field-wide" : ""}${errors[name] ? " is-invalid" : ""}`}
        data-field=${name}
      >
        <label for=${`overview-edit-${name}`}>${label}</label>
        <${FieldControl} name=${name} value=${values[name]} onInput=${(value) => setField(name, value)} />
        ${errors[name] ? html`<small class="field-error">${errors[name]}</small>` : null}
      </div>`)}
    </div>
    <div class="edit-form-actions">
      <button type="button" class="edit-save-btn" disabled=${saving} onClick=${save}>${saving ? "保存中..." : "保存"}</button>
      <button type="button" class="edit-cancel-btn" disabled=${saving} onClick=${() => { if (!saving && onCancel) onCancel(); }}>取消</button>
      <div class="edit-request-message">
        ${requestMessage ? html`<p class="edit-request-error" role="alert">${requestMessage}</p>` : null}
      </div>
    </div>
  </form>`;
}

/**
 * Inline 风险与备注 editor: Enter / blur saves, Escape cancels, an unchanged value
 * just closes. Props: item, getLatestItem?() (fresh payload item for the read-only
 * re-check and PATCH base), onSaved(projectStatus), onCancel().
 */
export function InlineNoteEdit({ item, getLatestItem, onSaved, onCancel }) {
  const current = String(item.note || "");
  const [value, setValue] = useState(current);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [readOnly, setReadOnly] = useState(null);
  const inputRef = useRef(null);
  const settled = useRef(false);
  const alive = useRef(true);
  useEffect(() => {
    if (inputRef.current) inputRef.current.focus();
    return () => { alive.current = false; };
  }, []);

  const finish = async (save) => {
    if (settled.current) return;
    settled.current = true;
    const note = value.trim();
    if (!save || note === current) {
      if (onCancel) onCancel();
      return;
    }
    const latest = (getLatestItem && getLatestItem()) || item;
    const manual = deliverableManualEditState(latest);
    if (!manual.editable) {
      settled.current = false;
      setError(manual.reason);
      setReadOnly(latest);
      return;
    }
    setSaving(true);
    try {
      const data = await request(deliverablePath(item.id), { method: "PATCH", body: notePatchPayload(latest, note) });
      const projectStatus = data && data.projectStatus;
      if (!projectStatus || overviewIsEmpty(projectStatus)) {
        throw new Error("数据已保存，但刷新最新状态未完成；请刷新当前视图更新显示，无需重新保存");
      }
      if (onSaved) onSaved(projectStatus);
    } catch (err) {
      if (!alive.current) return;
      settled.current = false;
      setSaving(false);
      setError(redactText(overviewErrorText(err)));
      // Keep the input for a retry (disabling it while saving dropped focus).
      setTimeout(() => { if (alive.current && inputRef.current) inputRef.current.focus(); }, 0);
    }
  };

  return html`<span class="note-inline-edit">
    <input
      ref=${inputRef}
      type="text"
      class=${`note-inline-input${error ? " note-inline-input-error" : ""}`}
      maxlength="500"
      aria-label="编辑风险与备注"
      title=${error || undefined}
      value=${value}
      disabled=${saving}
      onInput=${(e) => setValue(e.currentTarget.value)}
      onKeyDown=${(event) => {
        if (event.key === "Enter") { event.preventDefault(); finish(true); }
        else if (event.key === "Escape") { event.preventDefault(); finish(false); }
      }}
      onBlur=${() => finish(true)}
    />
    ${readOnly ? html`<${ReadOnlyNotice} item=${readOnly} className="detail-readonly-note" />` : null}
  </span>`;
}
