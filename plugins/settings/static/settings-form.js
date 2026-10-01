// Local, non-sensitive settings: business directories (with native folder
// picker) and the folded advanced/maintenance block. Saves via PATCH /api/settings.
import { html, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { request } from "./client.js";

export const DIRECTORY_FIELDS = [
  { key: "archiveDirectory", label: "归档保存目录", placeholder: "留空使用程序默认归档目录 (data/archive)", note: "定时自动下载与历史归档数据的存放位置。", basic: true },
  { key: "excelDirectory", label: "Excel 工作目录", placeholder: "留空使用默认目录 (data/excel)", note: "Excel 任务处理的输入与输出根目录。", basic: true },
  { key: "temporaryDirectory", label: "临时文件缓存目录", placeholder: "留空使用系统临时目录", note: "处理导出等操作时的中间临时目录。" },
  { key: "diagnosticDirectory", label: "系统诊断日志目录", placeholder: "留空使用默认 logs 目录", note: "运行日志与排查诊断报告存储位置。" },
];

// 范围与 core/settings_store.INTEGER_LIMITS 一致；服务端仍做最终校验。
export const INTEGER_FIELDS = [
  { key: "retryCount", label: "网络请求失败重试次数", min: 0, max: 10, fallback: 2, note: "仅控制单次查询与数据抓取失败时的自动重试次数；定时下载任务请在任务卡单独配置。" },
  { key: "defaultDownloadMinutes", label: "默认定时下载周期（分钟）", min: 5, max: 10080, fallback: 60, note: "新建定时下载任务时的默认执行周期。" },
  { key: "dueSoonDays", label: "交付物临期预警阈值（天）", min: 0, max: 365, fallback: 7, note: "交付物看板上标记为即将到期的提前天数。" },
  { key: "cacheSnapshotCount", label: "历史快照保留数量", min: 1, max: 365, fallback: 30, note: "交付物历史状态快照保留的最大条数。" },
  { key: "retentionDays", label: "历史文件保留天数", min: 1, max: 3650, fallback: 90, note: "归档文件和 Excel 输出建议清理的天数阈值。" },
];

function draftFrom(settings) {
  const draft = {};
  DIRECTORY_FIELDS.forEach((field) => { draft[field.key] = String(settings[field.key] ?? ""); });
  INTEGER_FIELDS.forEach((field) => { draft[field.key] = String(settings[field.key] ?? field.fallback); });
  return draft;
}

/** Client-side shape check; returns {payload, errors}. */
export function buildPayload(draft) {
  const payload = {};
  const errors = {};
  DIRECTORY_FIELDS.forEach((field) => { payload[field.key] = String(draft[field.key] || "").trim(); });
  INTEGER_FIELDS.forEach((field) => {
    const text = String(draft[field.key] ?? "").trim();
    const value = /^-?\d+$/.test(text) ? Number.parseInt(text, 10) : Number.NaN;
    if (!Number.isInteger(value) || value < field.min || value > field.max) {
      errors[field.key] = `必须是 ${field.min} 到 ${field.max} 的整数`;
    } else {
      payload[field.key] = value;
    }
  });
  return { payload, errors };
}

function FieldError({ message }) {
  return message ? html`<span class="st-field-error" role="alert">${message}</span>` : null;
}

function DirectoryField({ field, value, error, onChange, disabled }) {
  const [picker, setPicker] = useState({ busy: false, note: "" });

  const pick = async () => {
    setPicker({ busy: true, note: "正在打开 Windows 文件夹选择器…" });
    try {
      const data = await request("/api/settings/folders/native", { method: "POST", body: { path: value.trim() } });
      if (data && typeof data.path === "string" && data.path) {
        onChange(data.path);
        setPicker({ busy: false, note: "" });
      } else {
        setPicker({ busy: false, note: "已取消选择，目录未改变。" });
      }
    } catch (err) {
      if (err.status === 503) {
        setPicker({ busy: false, note: "当前环境无法打开 Windows 选择器，请手工填写本机绝对路径。" });
      } else {
        const detail = err.fields && err.fields.path ? err.fields.path : err.message;
        setPicker({ busy: false, note: `无法打开文件夹选择器：${detail}` });
      }
    }
  };

  const id = `st-field-${field.key}`;
  return html`<div class=${field.basic ? "st-field is-wide" : "st-field"}>
    <label for=${id}>${field.label}</label>
    <div class="st-path-control">
      <input
        id=${id}
        name=${field.key}
        type="text"
        class=${error ? "is-invalid" : ""}
        placeholder=${field.placeholder}
        value=${value}
        disabled=${disabled}
        onInput=${(event) => onChange(event.currentTarget.value)}
      />
      <button type="button" class="vk-btn" disabled=${disabled || picker.busy} onClick=${pick}>选择目录</button>
    </div>
    <${FieldError} message=${error} />
    ${picker.note && html`<span class="st-field-hint" aria-live="polite">${picker.note}</span>`}
    <span class="st-field-note">${field.note}</span>
  </div>`;
}

function IntegerField({ field, value, error, onChange, disabled }) {
  const id = `st-field-${field.key}`;
  return html`<div class="st-field">
    <label for=${id}>${field.label}</label>
    <input
      id=${id}
      name=${field.key}
      type="number"
      min=${field.min}
      max=${field.max}
      step="1"
      class=${error ? "is-invalid" : ""}
      value=${value}
      disabled=${disabled}
      onInput=${(event) => onChange(event.currentTarget.value)}
    />
    <${FieldError} message=${error} />
    <span class="st-field-note">${field.note}</span>
  </div>`;
}

/**
 * settings: server values; seed: bump to reset the draft from `settings`
 * (load / refresh / successful save). Session-only reloads keep the draft.
 */
export function SettingsForm({ settings, seed, onSaved, onError, saveSignal }) {
  const [draft, setDraft] = useState(() => draftFrom(settings || {}));
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState("");

  useEffect(() => {
    setDraft(draftFrom(settings || {}));
    setErrors({});
  }, [seed]);

  const set = (key) => (value) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
    setErrors((prev) => (prev[key] ? { ...prev, [key]: undefined } : prev));
    setStatus("");
  };

  const save = async (event) => {
    if (event) event.preventDefault();
    if (saving) return;
    const { payload, errors: clientErrors } = buildPayload(draft);
    if (Object.keys(clientErrors).length) {
      setErrors(clientErrors);
      setStatus("请修正标记的字段");
      return;
    }
    setSaving(true);
    setErrors({});
    setStatus("正在保存设置…");
    onError(null);
    try {
      const data = await request("/api/settings", { method: "PATCH", body: payload });
      setStatus("设置已保存");
      onSaved(data && data.settings);
    } catch (err) {
      setStatus("");
      if (err.fields) {
        setErrors(err.fields);
        const unknown = Object.keys(err.fields).filter((key) => !(key in draft));
        if (unknown.length) onError(err);
        else setStatus("请修正标记的字段");
      } else {
        onError(err);
      }
    } finally {
      setSaving(false);
    }
  };

  // 全局错误卡「重试保存」通过 saveSignal 触发再次提交。
  useEffect(() => {
    if (saveSignal) save();
  }, [saveSignal]);

  const advancedRef = useRef(null);
  const advancedError = [...DIRECTORY_FIELDS.filter((f) => !f.basic), ...INTEGER_FIELDS].some((f) => errors[f.key]);
  useEffect(() => {
    if (advancedError && advancedRef.current) advancedRef.current.open = true;
  }, [advancedError]);

  return html`<form class="st-form" autocomplete="off" onSubmit=${save} novalidate>
    <section class="st-card">
      <header class="st-card-head">
        <p class="st-eyebrow">业务目录</p>
        <h3>日常业务目录设置</h3>
      </header>
      <div class="st-grid">
        ${DIRECTORY_FIELDS.filter((f) => f.basic).map((field) => html`<${DirectoryField}
          key=${field.key} field=${field} value=${draft[field.key]} error=${errors[field.key]}
          disabled=${saving} onChange=${set(field.key)} />`)}
      </div>
    </section>

    <details class="st-card st-advanced" ref=${advancedRef}>
      <summary class="st-card-head">
        <p class="st-eyebrow">维护与调优</p>
        <h3>高级与维护设置（点击展开）</h3>
        <span class="st-field-note">包含临时目录、诊断日志、单次请求重试与快照策略</span>
      </summary>
      <div class="st-grid">
        ${DIRECTORY_FIELDS.filter((f) => !f.basic).map((field) => html`<${DirectoryField}
          key=${field.key} field=${field} value=${draft[field.key]} error=${errors[field.key]}
          disabled=${saving} onChange=${set(field.key)} />`)}
        ${INTEGER_FIELDS.map((field) => html`<${IntegerField}
          key=${field.key} field=${field} value=${draft[field.key]} error=${errors[field.key]}
          disabled=${saving} onChange=${set(field.key)} />`)}
      </div>
    </details>

    <div class="st-actions">
      <button type="submit" class="vk-btn is-primary" disabled=${saving}>保存设置</button>
      <span class="st-status" aria-live="polite">${status}</span>
    </div>
  </form>`;
}
