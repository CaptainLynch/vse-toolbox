// Manual-field editing on the detail page (legacy startDeliverableEdit /
// renderDeliverableEditForm / saveDeliverableChanges / startInlineNoteEdit).
// Saves through PATCH /api/project-status/deliverables/<id> with the record
// version (updatedAt); the response's projectStatus replaces the overview.
import { html, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { apiRequest, enc } from "./api.js";
import { deliverableManualEditState, readOnlyNoticeText } from "./display.js";
import { errorText, safeDisplayValue } from "./format.js";
import {
  OVERVIEW_STATUS_OPTIONS,
  buildDeliverablePatch,
  buildNotePatch,
  draftDirty,
  draftValuesFromItem,
  serverFieldErrors,
  validateDeliverableDraft,
} from "./policy-logic.js";

const FIELD_DEFS = [
  ["status", "状态"],
  ["owner", "负责人"],
  ["plannedDate", "计划完成日期"],
  ["actualDate", "实际完成日期"],
  ["progress", "当前进度（0-100）"],
  ["note", "风险与备注"],
];

function overviewIsEmpty(data) {
  return !data
    || !data.phase
    || !Array.isArray(data.milestones) || data.milestones.length === 0
    || !Array.isArray(data.deliverables) || data.deliverables.length === 0;
}

function FieldControl({ name, value, onChange, inputRef }) {
  const id = `overview-edit-${name}`;
  if (name === "status") {
    return html`<select id=${id} name=${name} value=${value} ref=${inputRef} onChange=${(e) => onChange(e.currentTarget.value)}>
      ${OVERVIEW_STATUS_OPTIONS.map((option) => html`<option key=${option} value=${option}>${option}</option>`)}
    </select>`;
  }
  if (name === "note") {
    return html`<textarea id=${id} name=${name} rows="3" value=${value} onInput=${(e) => onChange(e.currentTarget.value)}></textarea>`;
  }
  if (name === "progress") {
    return html`<input id=${id} name=${name} type="number" min="0" max="100" step="1" inputmode="numeric" value=${value}
      onInput=${(e) => onChange(e.currentTarget.value)} />`;
  }
  const type = name === "plannedDate" || name === "actualDate" ? "date" : "text";
  return html`<input id=${id} name=${name} type=${type} value=${value} onInput=${(e) => onChange(e.currentTarget.value)} />`;
}

/**
 * Full manual edit form. `onSaved(projectStatus)` swaps in the fresh overview,
 * `onCancel()` closes the panel, `onDirtyChange(bool)` drives the unload guard.
 */
export function DeliverableEditForm({ item, phaseId, onSaved, onCancel, onDirtyChange }) {
  const [saved] = useState(() => draftValuesFromItem(item));
  const [values, setValues] = useState(() => draftValuesFromItem(item));
  const [errors, setErrors] = useState({});
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const firstRef = useRef(null);
  const formRef = useRef(null);
  const manual = deliverableManualEditState(item);

  useEffect(() => { if (firstRef.current) firstRef.current.focus(); }, []);
  useEffect(() => { if (onDirtyChange) onDirtyChange(draftDirty(saved, values)); }, [values]);
  useEffect(() => () => { if (onDirtyChange) onDirtyChange(false); }, []);

  if (!manual.editable) {
    return html`<div class="detail-edit-readonly"><p class="detail-readonly-notice">${readOnlyNoticeText(item)}</p></div>`;
  }

  const focusFirstInvalid = () => {
    setTimeout(() => {
      const el = formRef.current && formRef.current.querySelector(".edit-field.is-invalid input, .edit-field.is-invalid select, .edit-field.is-invalid textarea");
      if (el) el.focus();
    }, 0);
  };

  const save = async (event) => {
    if (event) event.preventDefault();
    if (saving) return;
    if (!deliverableManualEditState(item).editable) {
      setMessage(readOnlyNoticeText(item));
      return;
    }
    const nextErrors = validateDeliverableDraft(values);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) {
      focusFirstInvalid();
      return;
    }
    setSaving(true);
    setMessage("");
    try {
      const data = (await apiRequest(`/api/project-status/deliverables/${enc(String(item.id))}`, {
        method: "PATCH",
        body: buildDeliverablePatch(values, item),
      })) || {};
      if (!data.projectStatus || overviewIsEmpty(data.projectStatus)) throw new Error("保存响应缺少完整的项目状态，请重试");
      if (onDirtyChange) onDirtyChange(false);
      onSaved(data.projectStatus);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
      if (err && err.fields) setErrors((prev) => ({ ...prev, ...serverFieldErrors(err.fields) }));
      setSaving(false);
    }
  };

  return html`<form id="overview-edit-form" class="detail-edit-form" novalidate ref=${formRef} onSubmit=${save}>
    <dl class="edit-readonly-grid">
      ${[
        ["展示编号", safeDisplayValue(item.displayCode || item.id)],
        ["交付物名称", safeDisplayValue(item.name)],
        ["所属阶段", safeDisplayValue(phaseId)],
        ["数据来源", safeDisplayValue(item.source)],
      ].map(([label, value]) => html`<dt key=${`t${label}`}>${label}</dt><dd key=${`d${label}`}>${value}</dd>`)}
    </dl>
    <div class="edit-form-grid">
      ${FIELD_DEFS.map(([name, label]) => html`<div
        key=${name}
        class=${`edit-field${name === "note" ? " edit-field-wide" : ""}${errors[name] ? " is-invalid" : ""}`}
        data-field=${name}
      >
        <label for=${`overview-edit-${name}`}>${label}</label>
        <${FieldControl}
          name=${name}
          value=${values[name]}
          inputRef=${name === "status" ? firstRef : null}
          onChange=${(value) => {
            setValues((prev) => ({ ...prev, [name]: value }));
            setErrors((prev) => {
              if (!prev[name]) return prev;
              const next = { ...prev };
              delete next[name];
              return next;
            });
          }}
        />
        ${errors[name] && html`<small class="field-error">${errors[name]}</small>`}
      </div>`)}
    </div>
    <div class="edit-form-actions">
      <button type="button" class="edit-save-btn" disabled=${saving} onClick=${save}>${saving ? "保存中..." : "保存"}</button>
      <button type="button" class="edit-cancel-btn" disabled=${saving} onClick=${onCancel}>取消</button>
      <div class="edit-request-message">${message && html`<p class="edit-request-error">${message}</p>`}</div>
    </div>
  </form>`;
}

/** "风险与备注" inline editor: Enter / blur saves, Escape cancels. */
export function InlineNoteEdit({ item, latestItem, onDone, onSaved }) {
  const current = String(item.note || "");
  const [value, setValue] = useState(current);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [readOnly, setReadOnly] = useState("");
  const inputRef = useRef(null);
  const settled = useRef(false);
  useEffect(() => { if (inputRef.current) inputRef.current.focus(); }, []);

  const finish = async (save) => {
    if (settled.current) return;
    settled.current = true;
    const note = value.trim();
    if (!save || note === current) {
      onDone();
      return;
    }
    const latest = latestItem() || item;
    const latestState = deliverableManualEditState(latest);
    if (!latestState.editable) {
      settled.current = false;
      setError(latestState.reason);
      setReadOnly(readOnlyNoticeText(latest));
      return;
    }
    setBusy(true);
    try {
      const data = (await apiRequest(`/api/project-status/deliverables/${enc(String(item.id))}`, {
        method: "PATCH",
        body: buildNotePatch(latest, note),
      })) || {};
      if (!data.projectStatus || overviewIsEmpty(data.projectStatus)) {
        throw new Error("数据已保存，但刷新最新状态未完成；请刷新当前视图更新显示，无需重新保存");
      }
      onSaved(data.projectStatus);
    } catch (err) {
      // 保留输入便于重试：恢复可编辑状态并提示错误。
      settled.current = false;
      setBusy(false);
      setError(errorText(err));
    }
  };

  return html`<input
      ref=${inputRef}
      type="text"
      class=${`note-inline-input${error ? " note-inline-input-error" : ""}`}
      maxlength="500"
      aria-label="编辑风险与备注"
      value=${value}
      disabled=${busy}
      title=${error || null}
      onInput=${(e) => setValue(e.currentTarget.value)}
      onKeyDown=${(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          finish(true);
        } else if (event.key === "Escape") {
          event.preventDefault();
          finish(false);
        }
      }}
      onBlur=${() => finish(true)}
    />${readOnly && html`<p class="detail-readonly-note">${readOnly}</p>`}`;
}
