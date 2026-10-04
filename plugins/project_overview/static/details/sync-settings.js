// 交付物明细列表「同步设置」列（签署日报规格 §9 S12–S20）：当场开关、行内编辑间隔/筛选条件/更新方式、
// 多选批量启用停用与改间隔。修改走宿主既有接口，列表和明细页读写同一份设置。
import { html, useCallback, useEffect, useState } from "/static/host/vendor/preact-htm.js";
import { apiRequest } from "../deliverable/api.js";
import {
  fieldErrorsText, filterSummary, intervalText, lastSyncText, missingText, parseFilters, parseInterval, settingRequest,
} from "./sync-settings-logic.js";

const SETTINGS_PATH = "/api/p/project-overview/sync-settings";
const MODES = [["automatic", "自动"], ["hybrid", "混合"], ["manual", "手动"]];

export function useSyncSettings() {
  const [state, setState] = useState({ items: [], loading: true, error: "" });
  const reload = useCallback(async () => {
    try {
      const data = await apiRequest(SETTINGS_PATH);
      setState({ items: data.items || [], loading: false, error: "" });
    } catch (err) {
      setState((prev) => ({ ...prev, loading: false, error: fieldErrorsText(err) }));
    }
  }, []);
  useEffect(() => { reload(); }, [reload]);
  const byId = {};
  state.items.forEach((item) => { byId[item.deliverableId] = item; });
  return { ...state, byId, reload };
}

export async function saveSetting(setting, changes) {
  const request = settingRequest(setting, changes);
  return apiRequest(request.path, { method: request.method, body: request.body });
}

/** S12、S13、S15：一个单元格——开关当场可点；间隔、筛选条件、更新方式点「编辑」展开。 */
export function SyncSettingsCell({ setting, selected, onSelect, onToggleEditor, onSaved }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!setting) return html`<span class="sync-settings-none">—</span>`;
  const toggle = async (event) => {
    event.stopPropagation();
    setBusy(true);
    setError("");
    try {
      await saveSetting(setting, { enabled: !setting.enabled });
      await onSaved();
    } catch (err) {
      setError(fieldErrorsText(err));
    } finally {
      setBusy(false);
    }
  };
  const missing = setting.configIssue || (setting.enabled ? "" : missingText(setting));
  return html`<div class="sync-settings-cell" onClick=${(event) => event.stopPropagation()}>
    <div class="sync-settings-line">
      <input type="checkbox" class="sync-settings-select" aria-label=${`选择 ${setting.displayName || setting.deliverableId}`}
        checked=${selected} onChange=${() => onSelect(!selected)} />
      <label class="sync-settings-switch">
        <input type="checkbox" checked=${setting.enabled} disabled=${busy} onChange=${toggle} />
        <span>${setting.enabled ? "自动同步已启用" : "未启用"}</span>
      </label>
      <button type="button" class="ov-btn sync-settings-edit" onClick=${onToggleEditor}>编辑</button>
    </div>
    <div class="sync-settings-meta">${intervalText(setting)} · ${filterSummary(setting)}</div>
    <div class="sync-settings-meta">上次：${lastSyncText(setting)}${setting.lastError ? `（${setting.lastError}）` : ""}</div>
    ${missing && html`<div class="sync-settings-missing">${missing}</div>`}
    ${error && html`<div class="sync-settings-error" role="alert">${error}</div>`}
  </div>`;
}

/** S13、S14、S19：行内编辑区；保存后从下一次同步起生效，进行中的同步不受影响。 */
export function SyncSettingsEditor({ setting, onClose, onSaved }) {
  const [interval, setIntervalText] = useState(String(setting.intervalMinutes || ""));
  const [mode, setMode] = useState(setting.mode || "automatic");
  const [filters, setFilters] = useState(JSON.stringify(setting.filters || {}, null, 2));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const save = async () => {
    const parsedInterval = parseInterval(interval, setting.kind);
    const parsedFilters = parseFilters(filters);
    if (parsedInterval.error || parsedFilters.error) {
      setError(parsedInterval.error || parsedFilters.error);
      return;
    }
    const changes = { intervalMinutes: parsedInterval.value, filters: parsedFilters.value };
    if (setting.kind === "binding") changes.mode = mode;
    setBusy(true);
    setError("");
    try {
      await saveSetting(setting, changes);
      await onSaved();
      onClose();
    } catch (err) {
      setError(fieldErrorsText(err));
    } finally {
      setBusy(false);
    }
  };
  return html`<div class="sync-settings-editor" onClick=${(event) => event.stopPropagation()}>
    <label>同步间隔（分钟）<input type="number" min="1" value=${interval} onInput=${(e) => setIntervalText(e.target.value)} /></label>
    ${setting.kind === "binding" && html`<label>更新方式
      <select value=${mode} onChange=${(e) => setMode(e.target.value)}>
        ${MODES.map(([value, label]) => html`<option key=${value} value=${value}>${label}</option>`)}
      </select></label>`}
    <label class="sync-settings-filters">筛选条件（JSON）
      <textarea rows="4" value=${filters} onInput=${(e) => setFilters(e.target.value)}></textarea></label>
    ${setting.watchlist && html`<p class="sync-settings-note">关注清单在该交付物的明细页里维护（当前：${setting.watchlist.scope === "watchlist" ? `仅关注清单 ${setting.watchlist.count} 份` : "全部表单"}）。</p>`}
    <p class="sync-settings-note">保存后从下一次同步起生效；正在进行的同步不受影响。改筛选条件或更新方式时，进行中那次的结果不会发布，以免与新设置混用。</p>
    ${error && html`<p class="sync-settings-error" role="alert">${error}</p>`}
    <div class="sync-settings-actions">
      <button type="button" class="ov-btn is-primary" disabled=${busy} onClick=${save}>保存</button>
      <button type="button" class="ov-btn" disabled=${busy} onClick=${onClose}>取消</button>
    </div>
  </div>`;
}

/** S16：多选批量启用、停用和改间隔。 */
export function BatchBar({ selected, settings, onDone }) {
  const [interval, setIntervalText] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  if (!selected.length) return null;
  const apply = async (changes) => {
    setBusy(true);
    const failures = [];
    for (const id of selected) {
      const setting = settings[id];
      if (!setting) continue;
      try {
        await saveSetting(setting, changes);
      } catch (err) {
        failures.push(`${setting.displayName || id}：${fieldErrorsText(err)}`);
      }
    }
    setBusy(false);
    setMessage(failures.length ? `部分未保存——${failures.join("；")}` : `已更新 ${selected.length} 项`);
    await onDone();
  };
  const applyInterval = () => {
    const parsed = parseInterval(interval, "binding");
    if (parsed.error) setMessage(parsed.error);
    else apply({ intervalMinutes: parsed.value });
  };
  return html`<div class="sync-settings-batch" role="region" aria-label="批量修改同步设置">
    <span>已选 ${selected.length} 项</span>
    <button type="button" class="ov-btn" disabled=${busy} onClick=${() => apply({ enabled: true })}>批量启用</button>
    <button type="button" class="ov-btn" disabled=${busy} onClick=${() => apply({ enabled: false })}>批量停用</button>
    <input type="number" min="1" placeholder="间隔（分钟）" value=${interval} onInput=${(e) => setIntervalText(e.target.value)} />
    <button type="button" class="ov-btn" disabled=${busy || !interval} onClick=${applyInterval}>批量改间隔</button>
    ${message && html`<span class="sync-settings-batch-msg" role="status">${message}</span>`}
  </div>`;
}
