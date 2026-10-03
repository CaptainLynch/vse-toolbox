// 交付物自动同步调度条 (legacy renderDeliverablesSyncControlBar): scheduler
// status with a 1 s countdown, interval select, pause/resume and 立即全量同步.
import { html, useCallback, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { request } from "../shared/client.js";
import {
  SCHEDULER_INTERVAL_OPTIONS, intervalChangedMessage, overviewErrorText, schedulerConfigPayload, schedulerView, syncAllMessage,
} from "../shared/status-logic.js";
import { schedulerWarning, syncAllCandidates } from "./sync-settings-logic.js";

const SCHEDULER_PATH = "/api/project-status/scheduler";
const CONFIG_PATH = "/api/project-status/scheduler/config";
const SYNC_ALL_PATH = "/api/project-status/scheduler/sync-all";

/** S17：先列出本次会同步哪些交付物和各自的筛选条件，可当场取消勾选或到表格里修改，再确认执行。 */
function SyncAllConfirm({ candidates, onConfirm, onCancel, busy }) {
  const [checked, setChecked] = useState(() => candidates.map((item) => item.deliverableId));
  const toggle = (id) => setChecked((list) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]));
  return html`<div class="details-sync-confirm" role="dialog" aria-label="确认立即全量同步">
    <p>本次将同步以下 ${checked.length} 项交付物（筛选条件可在下方表格「同步设置」列里修改）：</p>
    ${candidates.length === 0
      ? html`<p class="details-sync-warning">没有启用任何交付物。</p>`
      : html`<ul>${candidates.map((item) => html`<li key=${item.deliverableId}><label>
          <input type="checkbox" checked=${checked.includes(item.deliverableId)} onChange=${() => toggle(item.deliverableId)} />
          ${item.name}<span class="details-sync-meta">（${item.filters}）</span></label></li>`)}</ul>`}
    <div class="details-sync-actions">
      <button type="button" class="ov-btn is-primary" disabled=${busy || !checked.length}
        onClick=${() => onConfirm(checked, checked.length === candidates.length)}>确认同步</button>
      <button type="button" class="ov-btn" disabled=${busy} onClick=${onCancel}>取消</button>
    </div>
  </div>`;
}

export function SyncControlBar({ onSynced, settings }) {
  const [confirming, setConfirming] = useState(false);
  const [status, setStatus] = useState(null);
  const [metaError, setMetaError] = useState(false);
  const [countdown, setCountdown] = useState(null);
  const [message, setMessage] = useState(null); // {text, error}
  const [busy, setBusy] = useState({ interval: false, pause: false, syncAll: false });
  const [intervalDraft, setIntervalDraft] = useState(null);
  const alive = useRef(true);
  const hideTimer = useRef(null);
  const countdownRef = useRef(null);

  const clearHide = () => {
    if (hideTimer.current) clearTimeout(hideTimer.current);
    hideTimer.current = null;
  };
  const showMessage = useCallback((text, { error = false, hideAfter = 0 } = {}) => {
    clearHide();
    setMessage({ text, error });
    if (hideAfter) {
      hideTimer.current = setTimeout(() => {
        hideTimer.current = null;
        if (alive.current) setMessage(null);
      }, hideAfter);
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const data = await request(SCHEDULER_PATH);
      if (!alive.current || !data) return;
      setStatus(data);
      setMetaError(false);
      setIntervalDraft(null);
      countdownRef.current = data.nextRunSeconds ?? null;
      setCountdown(countdownRef.current);
    } catch (error) {
      // Legacy kept the last state on an HTTP error and only flagged a failed request.
      if (alive.current && !error.status) setMetaError(true);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    refresh();
    const timer = setInterval(() => {
      const value = countdownRef.current;
      if (value !== null && value > 0) {
        countdownRef.current = value - 1;
        setCountdown(countdownRef.current);
      } else if (value === 0) {
        countdownRef.current = null;
        refresh();
      }
    }, 1000);
    return () => {
      alive.current = false;
      clearInterval(timer);
      clearHide();
    };
  }, [refresh]);

  const view = status ? schedulerView(status, countdown) : null;

  const changeInterval = async (event) => {
    const value = event.currentTarget.value;
    setIntervalDraft(value);
    setBusy((b) => ({ ...b, interval: true }));
    try {
      await request(CONFIG_PATH, { method: "POST", body: schedulerConfigPayload(value) });
      await refresh();
      if (alive.current) showMessage(intervalChangedMessage(value), { hideAfter: 4000 });
    } catch (error) {
      if (alive.current) showMessage(overviewErrorText(error) || "更新配置失败", { error: true });
    } finally {
      if (alive.current) setBusy((b) => ({ ...b, interval: false }));
    }
  };

  const togglePause = async () => {
    setBusy((b) => ({ ...b, pause: true }));
    try {
      await request(CONFIG_PATH, { method: "POST", body: { paused: !(view && view.paused) } });
      await refresh();
    } catch (error) {
      if (alive.current) showMessage(overviewErrorText(error) || "更新配置失败", { error: true });
    } finally {
      if (alive.current) setBusy((b) => ({ ...b, pause: false }));
    }
  };

  const syncAll = async (ids, everything) => {
    setConfirming(false);
    setBusy((b) => ({ ...b, syncAll: true }));
    showMessage(everything ? "正在并发同步全部已启用交付物，请稍候..." : `正在同步选中的 ${ids.length} 项交付物，请稍候...`);
    try {
      let data;
      if (everything) {
        data = await request(SYNC_ALL_PATH, { method: "POST" });
      } else {
        const results = [];
        for (const id of ids) {
          try {
            await request(`/api/project-status/deliverables/${encodeURIComponent(id)}/sync-now`, { method: "POST" });
            results.push({ deliverableId: id, status: "success" });
          } catch (error) {
            results.push({ deliverableId: id, status: "error", error: overviewErrorText(error) });
          }
        }
        data = { results, count: results.length };
      }
      if (!alive.current) return;
      showMessage(syncAllMessage(data));
      await refresh();
      if (onSynced) await onSynced();
      if (alive.current) showMessage(syncAllMessage(data), { hideAfter: 5000 });
    } catch (error) {
      if (alive.current) showMessage(`全量同步失败：${overviewErrorText(error) || "全量同步失败"}`, { error: true });
    } finally {
      if (alive.current) setBusy((b) => ({ ...b, syncAll: false }));
    }
  };

  const warning = schedulerWarning(status);
  const indicatorClass = warning ? "is-warning" : view ? view.indicatorClass : "is-running";
  const indicatorText = view ? view.indicatorText : "🟢 交付物自动同步：检测中";
  const metaText = metaError ? "调度器状态读取失败" : view ? view.meta : "正在获取调度器状态...";
  const selectValue = intervalDraft !== null ? intervalDraft : view ? view.intervalValue : "900";

  return html`<div class="details-sync-control-bar">
    <div class="details-sync-control-status">
      <span class=${`details-sync-indicator ${indicatorClass}`}>${indicatorText}</span>
      <span class="details-sync-meta">${metaText}</span>
      ${warning && html`<span class="details-sync-warning" role="status">${warning}</span>`}
    </div>
    <div class="details-sync-actions">
      <label class="details-sync-interval-label">
        <span>同步频率：</span>
        <select value=${selectValue} disabled=${busy.interval} onChange=${changeInterval}>
          ${SCHEDULER_INTERVAL_OPTIONS.map(([value, text]) => html`<option key=${value} value=${String(value)}>${text}</option>`)}
        </select>
      </label>
      <button type="button" class="ov-btn is-primary sync-all-btn" disabled=${busy.syncAll || confirming}
        onClick=${() => setConfirming(true)}>
        ${busy.syncAll ? "正在全量同步..." : "立即全量同步"}
      </button>
      <button type="button" class="ov-btn pause-btn" disabled=${busy.pause} onClick=${togglePause}>
        ${view ? view.pauseLabel : "暂停调度"}
      </button>
    </div>
    ${confirming && html`<${SyncAllConfirm} candidates=${syncAllCandidates(settings ? settings.items : [])}
      busy=${busy.syncAll} onConfirm=${syncAll} onCancel=${() => setConfirming(false)} />`}
    ${message ? html`<div class=${`details-sync-msg${message.error ? " is-error" : ""}`} role=${message.error ? "alert" : "status"}>${message.text}</div>` : null}
  </div>`;
}
