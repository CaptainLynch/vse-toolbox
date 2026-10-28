// 「项目」：主计划时间轴 + 交付物一览。状态和逾期天数直接用后端的同一套口径（需求 C5），
// 页面上不出现 JSON、映射取证、稳定键这类词；需要细调时进入交付物详情。
import { useState } from "/static/host/vendor/preact-htm.js";
import {
  ErrorCard, PageHead, activeDeliverables, Pill, Progress, Skeleton, TONE, api, completionCount, deliverableHref, go, html, shortTime, useLoad, useWorkbenchStyles,
} from "./common.js";
import { ProjectSwitcher } from "./projects.js";

const SOURCES = { status: "/api/project-status", scheduler: "/api/project-status/scheduler" };

const SYNC_TONE = { synced: "ok", idle: "ok", running: "info", syncing: "info", failed: "bad", error: "bad", manual: "off", snapshot: "info" };

function syncCell(d) {
  const sync = d.syncDisplay || {};
  const policy = d.updatePolicy || {};
  if (sync.lastError) return html`<${Pill} tone="bad">同步失败<//>`;
  if (d.updateMethod === "manual" || sync.state === "manual") return html`<${Pill} tone="off">手工维护<//>`;
  if (!policy.enabled && sync.state !== "snapshot") return html`<${Pill} tone="off">未开启<//>`;
  const label = sync.label || "自动同步";
  return html`<span><${Pill} tone=${SYNC_TONE[sync.state] || SYNC_TONE[sync.syncState] || "info"}>${label}<//>
    ${policy.lastSuccessAt && html`<small>上次 ${shortTime(policy.lastSuccessAt)}</small>`}</span>`;
}

function scheduleText(d) {
  if (d.scheduleState === "overdue") return html`<${Pill} tone="bad">逾期 ${d.scheduleDays} 天<//>`;
  if (d.scheduleState === "due_soon") return html`<${Pill} tone="warn">${d.scheduleDays} 天内到期<//>`;
  return null;
}

function Timeline({ milestones, today }) {
  const list = milestones || [];
  const current = list.find((m) => m.status !== "已完成");
  return html`<div class="wb-timeline" role="list">
    ${list.map((m) => {
      const done = m.status === "已完成";
      const late = !done && m.date && m.date < today;
      const cls = ["wb-node", done ? "is-done" : "", m === current ? "is-current" : "", late ? "is-late" : ""].join(" ");
      return html`<div class=${cls} role="listitem" key=${m.id}>
        <i class="dot"></i><b>${m.name}</b>
        <span>${m.date ? m.date.slice(5) : html`<a class="wb-link" href="#p/project-overview/plan">去排期</a>`}</span>
      </div>`;
    })}
  </div>`;
}

export default function ProjectPage() {
  useWorkbenchStyles();
  const { data, errors, loading, reload } = useLoad(SOURCES);
  const [syncing, setSyncing] = useState(null);

  if (loading && !data.status) return html`<div class="wb-page"><${Skeleton} /></div>`;
  if (errors.status) {
    return html`<div class="wb-page"><${ErrorCard} title="项目数据读取失败" what=${errors.status.message}
      todo="点「重试」；如果仍然失败，到「设置」里导出诊断包发给支持人员。" actions=${[{ label: "重试", onClick: reload }]} /></div>`;
  }

  const status = data.status;
  const phase = status.phase || {};
  const summary = status.summary || {};
  const deliverables = activeDeliverables(status.deliverables);
  const scheduler = data.scheduler || {};

  const syncAll = async () => {
    setSyncing("正在同步…");
    try {
      await api("/api/project-status/scheduler/sync-all", { method: "POST", body: {} });
      setSyncing("已开始同步，完成后会自动刷新");
      setTimeout(() => { setSyncing(null); reload(); }, 4000);
    } catch (err) {
      setSyncing(`同步没有开始：${err.message}`);
    }
  };

  const late = deliverables.filter((d) => d.scheduleState === "overdue").length;
  // 能自动同步但还没开启的交付物：给一个「一键开启」入口（需求 D2）。
  const notEnabled = deliverables.filter((d) => d.sourceInfo && d.sourceInfo.syncCapable && !(d.updatePolicy && d.updatePolicy.enabled)).length;
  const counts = completionCount(deliverables);

  return html`<div class="wb-page">
    <${PageHead}
      title=${`${phase.displayName || "项目"}`}
      sub=${`${phase.startDate || ""} 至 ${phase.endDate || ""} · ${phase.status || ""} · ${scheduler.eligibleCount ? `自动同步 ${scheduler.eligibleCount} 项` : "自动同步未开启"}`}
      actions=${html`
        <${ProjectSwitcher} />
        <button type="button" class="wb-btn" onClick=${() => go("#p/project-overview/plan")}>编辑主计划</button>
        ${notEnabled > 0 && html`<button type="button" class=${`wb-btn${scheduler.eligibleCount ? "" : " is-primary"}`} onClick=${() => go("#p/project-overview/auto-sync")}>⚡ 一键开启自动同步（${notEnabled} 项）</button>`}
        ${scheduler.eligibleCount > 0 && html`<button type="button" class="wb-btn is-primary" onClick=${syncAll} disabled=${Boolean(syncing)}>立即同步全部</button>`}`}
    />
    ${syncing && html`<p class="wb-sub" role="status">${syncing}</p>`}

    <div class="wb-grid wb-grid-3">
      <div class="wb-card"><span class="wb-muted wb-small">总体进度</span><div class="wb-big">${phase.overallProgress ?? 0}%</div>
        <${Progress} value=${phase.overallProgress} /><p class="wb-small wb-muted" style="margin:6px 0 0">计划应达到 ${summary.planned || "—"}（差 ${summary.variance || "—"}）</p></div>
      <div class="wb-card"><span class="wb-muted wb-small">交付物</span><div class="wb-big">${counts.done}<span class="wb-muted" style="font-size:18px"> / ${counts.total}</span></div>
        <p class="wb-small wb-muted" style="margin:6px 0 0">已完成 · 未完成 ${counts.total - counts.done} · 其中逾期 ${late}</p></div>
      <div class="wb-card"><span class="wb-muted wb-small">最大风险</span>
        <p style="margin:6px 0 0;color:var(--ink);font-weight:600">${summary.risk || "暂无风险"}</p></div>
    </div>

    <section class="wb-card">
      <div class="wb-card-head"><h3>主计划</h3><span class="wb-small wb-muted">今天 ${phase.today || ""}</span></div>
      <${Timeline} milestones=${status.milestones} today=${phase.today || ""} />
    </section>

    <section class="wb-card">
      <div class="wb-card-head"><h3>交付物</h3><span class="wb-small wb-muted">点任意一行查看明细与同步设置</span></div>
      <div class="wb-table-wrap"><table class="wb-table">
        <thead><tr><th>交付物</th><th>状态</th><th>计划完成</th><th>进度</th><th>自动同步</th></tr></thead>
        <tbody>${deliverables.map((d) => html`<tr key=${d.id} onClick=${() => go(deliverableHref(d.id))}>
          <td><b>${d.name}</b><small>${d.owner ? `负责人 ${d.owner} · ` : ""}${d.countsTowardCompletion ? "计入完成统计" : "仅供参考"}</small></td>
          <td><span class="wb-row"><${Pill} tone=${TONE[d.tone] || "off"}>${d.status}<//>${scheduleText(d)}</span></td>
          <td>${d.plannedDate || html`<span class="wb-muted">未设置</span>`}</td>
          <td style="min-width:140px"><div class="wb-small">${d.progress ?? 0}%</div><${Progress} value=${d.progress} tone=${d.progress >= 100 ? "ok" : d.scheduleState === "overdue" ? "bad" : ""} /></td>
          <td>${syncCell(d)}</td>
        </tr>`)}</tbody>
      </table></div>
      ${!deliverables.length && html`<p class="wb-sub">还没有交付物。</p>`}
    </section>
  </div>`;
}
