// 主计划基本信息: readonly card (with inline rename) and the edit form.
import { html, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { redactText } from "../shared/client.js";
import { PHASE_STATUS_OPTIONS, displayValue } from "./logic.js";

export function PencilIcon() {
  return html`<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false">
    <path fill="currentColor" d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z" />
  </svg>`;
}

function InlineNameInput({ initial, onFinish }) {
  const [value, setValue] = useState(initial);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const settled = useRef(false);
  const inputRef = useRef(null);

  useEffect(() => {
    const input = inputRef.current;
    if (input) {
      input.focus();
      input.select();
    }
  }, []);

  const finish = async (save) => {
    if (settled.current) return;
    settled.current = true;
    setBusy(true);
    const message = await onFinish(save, inputRef.current ? inputRef.current.value : value);
    if (message) {
      // 保留输入便于重试：恢复可编辑状态并提示错误。
      settled.current = false;
      setBusy(false);
      setError(message);
    }
  };

  return html`<input
    ref=${inputRef}
    type="text"
    class=${`phase-name-inline-input${error ? " phase-name-inline-input-error" : ""}`}
    maxLength="120"
    value=${value}
    disabled=${busy}
    title=${error || undefined}
    aria-label="编辑主计划名称"
    aria-invalid=${error ? "true" : undefined}
    onInput=${(event) => setValue(event.currentTarget.value)}
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
  />`;
}

export function PhaseReadonlyCard({ phase, saving, onEdit, onRename }) {
  const [renaming, setRenaming] = useState(false);
  const name = phase.displayName || phase.id;
  const items = [
    ["主计划名称", name],
    ["阶段状态", phase.status],
    ["开始日期", phase.startDate],
    ["计划完成日期", phase.endDate],
  ];

  const finishRename = async (save, value) => {
    if (!save) {
      setRenaming(false);
      return "";
    }
    const message = await onRename(value);
    if (!message) setRenaming(false);
    return message;
  };

  return html`<div class="phase-meta-card">
    <div class="phase-meta-toolbar">
      <span class="phase-meta-title">主计划基本信息</span>
      <button type="button" class="phase-meta-edit-btn" title="编辑阶段信息" aria-label="编辑阶段信息" disabled=${saving} onClick=${onEdit}>
        <${PencilIcon} /><span>编辑阶段信息</span>
      </button>
    </div>
    <div class="phase-meta-grid">
      ${items.map(([label, value]) => label === "主计划名称"
        ? html`<div key=${label} class="phase-meta-cell phase-meta-name-cell">
            <span class="phase-meta-label">${label}</span>
            <strong class="phase-meta-value">
              ${renaming
                ? html`<${InlineNameInput} initial=${String(name || "")} onFinish=${finishRename} />`
                : html`${displayValue(redactText(value))}<button
                    type="button"
                    class="phase-name-inline-btn"
                    title="编辑主计划名称"
                    aria-label="编辑主计划名称"
                    onClick=${() => { if (!saving) setRenaming(true); }}
                  >✎</button>`}
            </strong>
          </div>`
        : html`<div key=${label} class="phase-meta-cell">
            <span class="phase-meta-label">${label}</span>
            <strong class="phase-meta-value">${displayValue(redactText(value))}</strong>
          </div>`)}
    </div>
  </div>`;
}

export function PhaseEditForm({ draft, saving, message, onChange, onSave, onCancel }) {
  const nameRef = useRef(null);
  useEffect(() => {
    if (nameRef.current) nameRef.current.focus();
  }, []);
  const field = (key) => (event) => onChange({ ...draft, [key]: event.currentTarget.value });
  return html`<form class="phase-meta-edit-form" noValidate onSubmit=${(event) => { event.preventDefault(); onSave(); }}>
    <h5 class="phase-meta-title">编辑主计划基本信息</h5>
    <div class="phase-meta-edit-grid">
      <label class="phase-meta-field">
        <span>主计划名称</span>
        <input ref=${nameRef} type="text" name="displayName" maxLength="120" value=${draft.displayName} onInput=${field("displayName")} />
      </label>
      <label class="phase-meta-field">
        <span>阶段状态</span>
        <select name="status" value=${draft.status} onChange=${field("status")}>
          ${PHASE_STATUS_OPTIONS.map((status) => html`<option key=${status} value=${status}>${status}</option>`)}
        </select>
      </label>
      <label class="phase-meta-field">
        <span>开始日期</span>
        <input type="date" name="startDate" value=${draft.startDate} onInput=${field("startDate")} />
      </label>
      <label class="phase-meta-field">
        <span>计划完成日期</span>
        <input type="date" name="endDate" value=${draft.endDate} onInput=${field("endDate")} />
      </label>
    </div>
    <div class="phase-meta-form-actions">
      <button type="button" class="edit-save-btn phase-meta-save-btn" disabled=${saving} onClick=${onSave}>${saving ? "保存中..." : "保存阶段信息"}</button>
      <button type="button" class="edit-cancel-btn phase-meta-cancel-btn" onClick=${onCancel}>取消</button>
      <div class="phase-meta-request-message" role="alert">${message}</div>
    </div>
  </form>`;
}
