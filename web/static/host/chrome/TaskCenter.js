// Unified task center: top-bar button with the active-task badge and the
// slide-out drawer listing /api/tasks (tabs, progress, cancel / retry,
// result and artifact links). Plugins wake it with the
// `vse:task-center-kick` event on document or window.
import { html, useEffect, useRef, useState } from "../vendor/preact-htm.js";
import { createStore, redactSensitiveText } from "../session.js";
import { useStore } from "./SessionBadges.js";

/* ── Pure helpers (unit-tested under Node) ─────────────────────────── */

export const ACTIVE_STATUSES = ["queued", "leased", "running", "generating", "downloading"];
export const POLL_OPEN_MS = 1500; // legacy cadence while the drawer is open
export const POLL_CLOSED_MS = 5000; // badge refresh while closed with active tasks
export const MAX_CLOSED_POLLS = 120; // closed refresh stops after ~10 min until the next kick/open
const DRAWER_ANIMATION_MS = 250;

export function isActiveTask(task) {
  return Boolean(task && (task.is_active || ACTIVE_STATUSES.includes(task.status)));
}

export function filterTasks(tasks, filter) {
  return (tasks || []).filter((task) => {
    const active = isActiveTask(task);
    if (filter === "active") return active;
    if (filter === "history") return !active;
    return true;
  });
}

export function taskCounts(tasks) {
  const active = (tasks || []).filter(isActiveTask).length;
  return { active, history: (tasks || []).length - active };
}

/** Delay before the next poll, or null to stop polling. */
export function nextPollDelay({ open, activeCount, closedPolls }) {
  if (open) return POLL_OPEN_MS;
  if (activeCount > 0 && closedPolls < MAX_CLOSED_POLLS) return POLL_CLOSED_MS;
  return null;
}

export function statusLabel(status) {
  switch (status) {
    case "queued": return "排队中";
    case "running": return "运行中";
    case "leased": return "执行中";
    case "generating": return "生成中";
    case "downloading": return "下载中";
    case "succeeded":
    case "parsed":
    case "generated": return "已完成";
    case "failed": return "失败";
    case "interrupted": return "已中断";
    case "cancelled": return "已取消";
    default: return status;
  }
}

export function statusClass(status) {
  switch (status) {
    case "queued": return "is-queued";
    case "running":
    case "leased":
    case "generating":
    case "downloading": return "is-running";
    case "succeeded":
    case "parsed":
    case "generated": return "is-succeeded";
    case "failed":
    case "interrupted": return "is-failed";
    case "cancelled": return "is-cancelled";
    default: return "is-queued";
  }
}

export function formatTimeAgo(isoString, now = Date.now()) {
  if (!isoString) return "";
  const created = new Date(isoString).getTime();
  if (Number.isNaN(created)) return "";
  const diffSec = Math.max(0, Math.floor((now - created) / 1000));
  if (diffSec < 60) return `${diffSec}秒前`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}分钟前`;
  return `${Math.floor(diffMin / 60)}小时前`;
}

export function formatElapsed(task, now = Date.now()) {
  if (!task || !task.created_at) return "";
  const start = new Date(task.created_at).getTime();
  if (Number.isNaN(start)) return "";
  const active = isActiveTask(task);
  const endRaw = active ? now : task.updated_at ? new Date(task.updated_at).getTime() : now;
  const end = Number.isNaN(endRaw) ? now : endRaw;
  const diffSec = Math.max(0, Math.floor((end - start) / 1000));
  let timeStr;
  if (diffSec < 60) {
    timeStr = `${diffSec}秒`;
  } else {
    const m = Math.floor(diffSec / 60);
    const s = diffSec % 60;
    timeStr = s > 0 ? `${m}分${s}秒` : `${m}分钟`;
  }
  return active ? `已运行 ${timeStr}` : `耗时 ${timeStr}`;
}

export function taskDownloadUrl(task) {
  return `/api/tasks/${encodeURIComponent(task.id)}/download`;
}

/* ── Controller: fetching and bounded polling ──────────────────────── */

export const taskStore = createStore({
  open: false,
  loading: false,
  tasks: [],
  activeCount: 0,
  filter: "active",
});

let pollTimer = null;
let fetching = false;
let refetch = false;
let closedPolls = 0;

function schedule() {
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
  const state = taskStore.get();
  const delay = nextPollDelay({ open: state.open, activeCount: state.activeCount, closedPolls });
  if (delay === null) return;
  pollTimer = setTimeout(() => {
    pollTimer = null;
    if (!taskStore.get().open) closedPolls += 1;
    fetchTasks();
  }, delay);
}

export async function fetchTasks() {
  if (fetching) {
    refetch = true;
    return;
  }
  fetching = true;
  try {
    const resp = await fetch("/api/tasks?limit=100", { headers: { Accept: "application/json" }, cache: "no-store" });
    if (resp.ok) {
      const json = await resp.json();
      if (json && json.ok && json.data) {
        taskStore.set((prev) => ({
          ...prev,
          loading: false,
          tasks: Array.isArray(json.data.tasks) ? json.data.tasks : [],
          activeCount: Number(json.data.active_count) || 0,
        }));
      }
    }
  } catch (_) {
    // 网络异常时保留上次结果，下一轮轮询再试
  } finally {
    fetching = false;
  }
  if (refetch) {
    refetch = false;
    fetchTasks();
    return;
  }
  schedule();
}

export function kickTaskCenter() {
  closedPolls = 0;
  fetchTasks();
}

export function openTaskCenter() {
  closedPolls = 0;
  taskStore.set((prev) => ({ ...prev, open: true, loading: true }));
  fetchTasks();
}

export function closeTaskCenter() {
  if (!taskStore.get().open) return;
  closedPolls = 0;
  taskStore.set((prev) => ({ ...prev, open: false }));
  schedule();
  const button = document.getElementById("hc-task-center-btn");
  if (button) button.focus();
}

export function setTaskFilter(filter) {
  taskStore.set((prev) => ({ ...prev, filter }));
}

let kickInstalled = false;

/** Listen for `vse:task-center-kick` once; returns false when already installed. */
export function installTaskCenterKick() {
  if (kickInstalled) return false;
  kickInstalled = true;
  document.addEventListener("vse:task-center-kick", kickTaskCenter);
  window.addEventListener("vse:task-center-kick", (event) => {
    // A bubbling document event also reaches window; handle it only once.
    if (event.target === window) kickTaskCenter();
  });
  return true;
}

/* ── Components ────────────────────────────────────────────────────── */

export function TaskCenterButton() {
  const { open, activeCount } = useStore(taskStore);
  return html`<button
    id="hc-task-center-btn"
    class="hc-task-center-btn"
    type="button"
    aria-label="统一任务中心"
    title="打开统一任务中心"
    aria-haspopup="dialog"
    aria-expanded=${open ? "true" : "false"}
    onClick=${() => (taskStore.get().open ? closeTaskCenter() : openTaskCenter())}
  >
    <span class="hc-task-center-icon" aria-hidden="true">📋</span>
    <span class="hc-task-center-label">任务</span>
    <span id="hc-task-center-badge" class="hc-task-center-badge" hidden=${activeCount <= 0}>${activeCount > 0 ? String(activeCount) : "0"}</span>
  </button>`;
}

async function postTaskAction(task, action) {
  try {
    const resp = await fetch(`/api/tasks/${encodeURIComponent(task.id)}/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
    });
    if (resp.ok) return null;
    const err = await resp.json().catch(() => ({}));
    return redactSensitiveText((err && err.error && err.error.message) || "网络异常");
  } catch (_) {
    return "网络异常";
  }
}

function TaskCard({ task, now }) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const active = isActiveTask(task);
  const elapsed = formatElapsed(task, now);
  const pct = task.progress && task.progress.percent != null ? task.progress.percent : 0;

  const run = async (action, failLabel) => {
    setBusy(action);
    setError("");
    const message = await postTaskAction(task, action);
    if (message === null) {
      await fetchTasks();
    } else {
      setError(`${failLabel}: ${message}`);
    }
    setBusy("");
  };

  return html`<div class="hc-task-card">
    <div class="hc-task-card-header">
      <div class="hc-task-card-title-group">
        <h4 class="hc-task-card-title">${task.title || task.id}</h4>
        <div class="hc-task-card-meta">
          <span>${formatTimeAgo(task.created_at, now)}</span>
          ${elapsed && html`<span>${elapsed}</span>`}
          <span>${String(task.category || "crawl").toUpperCase()}</span>
        </div>
      </div>
      <span class=${`hc-task-status ${statusClass(task.status)}`}>${statusLabel(task.status)}</span>
    </div>
    ${active && task.progress && Object.keys(task.progress).length > 0 && html`<div class="hc-task-progress">
      <div class="hc-task-progress-bg"><div class="hc-task-progress-fill" style=${{ width: `${pct}%` }}></div></div>
      <div class="hc-task-progress-text">
        <span>${task.progress.stage || (task.status === "queued" ? "等待资源执行..." : "正在处理中...")}</span>
        <span>${pct}%</span>
      </div>
    </div>`}
    ${task.error_message && html`<div class="hc-task-error">${redactSensitiveText(task.error_message)}</div>`}
    ${task.manual_check_required && html`<div class="hc-task-error hc-task-manual-check">生成结果未知：禁止自动重发，请在 EWO 增强导表面板进行状态人工核查。</div>`}
    ${error && html`<div class="hc-task-error" role="alert">${error}</div>`}
    ${(task.can_cancel || task.can_retry || task.has_artifact || task.can_download) && html`<div class="hc-task-card-actions">
      ${task.can_cancel && html`<button class="hc-task-action is-cancel" type="button" disabled=${Boolean(busy)} onClick=${() => run("cancel", "取消失败")}>
        ${busy === "cancel" ? "正在取消..." : "取消任务"}
      </button>`}
      ${task.can_retry && html`<button class="hc-task-action is-retry" type="button" disabled=${Boolean(busy)} onClick=${() => run("retry", "重试失败")}>
        ${busy === "retry" ? "正在提交重试..." : "重试任务"}
      </button>`}
      ${task.has_artifact && html`<a class="hc-task-action is-view" href=${taskDownloadUrl(task)} target="_blank" rel="noopener">查看结果</a>`}
      ${task.can_download && html`<a class="hc-task-action is-download" href=${taskDownloadUrl(task)} download="">下载工件</a>`}
    </div>`}
  </div>`;
}

const TABS = [
  { filter: "active", id: "hc-task-tab-active", label: "运行中" },
  { filter: "history", id: "hc-task-tab-history", label: "已结束" },
  { filter: "all", id: "hc-task-tab-all", label: "全部" },
];

export function TaskCenterDrawer() {
  const state = useStore(taskStore);
  const [mounted, setMounted] = useState(state.open);
  const [visible, setVisible] = useState(state.open);
  const closeRef = useRef(null);

  useEffect(() => {
    if (state.open) {
      setMounted(true);
      const frame = requestAnimationFrame(() => setVisible(true));
      return () => cancelAnimationFrame(frame);
    }
    setVisible(false);
    const timer = setTimeout(() => setMounted(false), DRAWER_ANIMATION_MS);
    return () => clearTimeout(timer);
  }, [state.open]);

  useEffect(() => {
    if (!state.open) return undefined;
    if (closeRef.current) closeRef.current.focus();
    const onKey = (event) => {
      if (event.key === "Escape") closeTaskCenter();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [state.open]);

  const counts = taskCounts(state.tasks);
  const filtered = filterTasks(state.tasks, state.filter);
  const now = Date.now();

  return html`<div id="hc-task-drawer-container" class=${`hc-drawer-container${visible ? " is-open" : ""}`} hidden=${!mounted}>
    <div class="hc-drawer-backdrop" aria-hidden="true" onClick=${closeTaskCenter}></div>
    <aside id="hc-task-drawer" class="hc-drawer" role="dialog" aria-modal="true" aria-labelledby="hc-task-drawer-title">
      <div class="hc-drawer-head">
        <div class="hc-drawer-title-wrap">
          <h3 id="hc-task-drawer-title">统一任务中心</h3>
          <span id="hc-task-active-count" class="hc-drawer-active-chip">${counts.active} 项进行中</span>
        </div>
        <div class="hc-drawer-actions">
          <button class="hc-icon-btn" type="button" title="刷新任务" aria-label="刷新任务" onClick=${() => fetchTasks()}>↻</button>
          <button ref=${closeRef} class="hc-modal-close" type="button" title="关闭抽屉" aria-label="关闭" onClick=${closeTaskCenter}>×</button>
        </div>
      </div>
      <div class="hc-drawer-tabs" aria-label="任务状态筛选">
        ${TABS.map((tab) => html`<button
          key=${tab.filter}
          id=${tab.id}
          class=${`hc-task-tab${state.filter === tab.filter ? " active" : ""}`}
          type="button"
          data-filter=${tab.filter}
          aria-pressed=${state.filter === tab.filter ? "true" : "false"}
          onClick=${() => setTaskFilter(tab.filter)}
        >${tab.label}${tab.filter === "active" ? ` (${counts.active})` : tab.filter === "history" ? ` (${counts.history})` : ""}</button>`)}
      </div>
      <div class="hc-drawer-content">
        ${state.loading
          ? html`<div class="hc-drawer-empty"><p class="hc-loading">加载任务列表...</p></div>`
          : filtered.length === 0
            ? html`<div class="hc-drawer-empty"><p>暂无任务记录</p></div>`
            : html`<div class="hc-task-items">${filtered.map((task) => html`<${TaskCard} key=${task.id} task=${task} now=${now} />`)}</div>`}
      </div>
    </aside>
  </div>`;
}
