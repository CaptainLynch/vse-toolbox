// 工作台共用：数据加载、状态色、待办卡片、页面头部。
import { html, useCallback, useEffect, useState } from "/static/host/vendor/preact-htm.js";
import { api } from "/static/host/api.js";
import { useStylesheet } from "/static/host/kit.js";

export { html, api };

/** 后端 tone（success / primary / warning / error）→ 统一的四色。 */
export const TONE = { success: "ok", primary: "info", warning: "warn", error: "bad" };

export function useWorkbenchStyles() {
  useStylesheet("/plugins/workbench/static/workbench.css");
}

/**
 * 并行加载多个接口；任何一个失败只让那一块显示不可用，不拖垮整页。
 * loaders: { key: "/api/..." }
 */
export function useLoad(loaders) {
  const [state, setState] = useState({ data: {}, errors: {}, loading: true });
  const keys = Object.keys(loaders);
  const load = useCallback(async () => {
    setState((prev) => ({ ...prev, loading: true }));
    const results = await Promise.allSettled(keys.map((key) => api(loaders[key])));
    const data = {};
    const errors = {};
    results.forEach((result, index) => {
      if (result.status === "fulfilled") data[keys[index]] = result.value;
      else errors[keys[index]] = result.reason;
    });
    setState({ data, errors, loading: false });
  }, [JSON.stringify(loaders)]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);
  return { ...state, reload: load };
}

export function go(hash) {
  window.location.hash = hash;
}

export function Pill({ tone = "off", children }) {
  return html`<span class=${`wb-pill is-${tone}`}>${children}</span>`;
}

export function Progress({ value, tone }) {
  const pct = Math.max(0, Math.min(100, Number(value) || 0));
  return html`<div class=${`wb-progress${tone ? ` is-${tone}` : ""}`}><i style=${`width:${pct}%`}></i></div>`;
}

export function PageHead({ title, sub, actions }) {
  return html`<header class="wb-head">
    <div><h1>${title}</h1>${sub && html`<p class="wb-sub">${sub}</p>`}</div>
    ${actions && html`<div class="wb-row">${actions}</div>`}
  </header>`;
}

export function Skeleton({ blocks = 4 }) {
  return html`<div class="wb-skeleton" aria-busy="true">
    <div class="wb-sk wb-sk-title"></div><div class="wb-sk wb-sk-line"></div>
    <div class="wb-grid wb-grid-2">${Array.from({ length: blocks }, (_, i) => html`<div class="wb-sk wb-sk-card" key=${i}></div>`)}</div>
  </div>`;
}

/** 一条待办：每条都必须带一个能直接处理它的按钮（需求 U5）。 */
export function Todo({ tone = "info", icon, title, detail, actions = [] }) {
  return html`<div class=${`wb-todo is-${tone}`}>
    <div class="wb-todo-icon" aria-hidden="true">${icon}</div>
    <div class="wb-todo-body"><strong>${title}</strong>${detail && html`<span>${detail}</span>`}</div>
    <div class="wb-row">${actions.map((action, index) => html`<${ActionButton} key=${index} action=${action} primary=${index === 0} />`)}</div>
  </div>`;
}

export function ActionButton({ action, primary }) {
  const onClick = action.onClick || (() => go(action.href));
  return html`<button type="button" class=${`wb-btn${primary ? " is-primary" : ""}`} onClick=${onClick} disabled=${action.disabled}>${action.label}</button>`;
}

/** 出错时的统一卡片（需求 U6）：发生了什么 / 你需要做什么 / 一键处理。 */
export function ErrorCard({ title, what, todo, actions = [] }) {
  return html`<div class="wb-errcard" role="alert">
    <strong>⚠ ${title}</strong>
    <dl><dt>发生了什么</dt><dd>${what}</dd><dt>你需要做什么</dt><dd>${todo}</dd></dl>
    <div class="wb-row">${actions.map((action, index) => html`<${ActionButton} key=${index} action=${action} primary=${index === 0} />`)}</div>
  </div>`;
}

export function todayString() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export function shortTime(value) {
  if (!value) return "";
  const text = String(value).replace("T", " ");
  return text.slice(5, 16);
}

/** v2 页面显示的交付物：去掉已取消的（例如「子系统开发策略」）。 */
export function activeDeliverables(deliverables) {
  return (deliverables || []).filter((d) => !d.retired);
}

/** 已完成交付物：与表格里的状态同一口径（进度 100% 或状态为已完成），首页和项目页共用。 */
export function completionCount(deliverables) {
  const list = activeDeliverables(deliverables);
  const done = list.filter((d) => d.tone === "success" || Number(d.progress) >= 100).length;
  return { done, total: list.length };
}

export function deliverableHref(id) {
  return `#p/project-overview/deliverable?id=${encodeURIComponent(id)}`;
}
