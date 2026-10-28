// 「今天」：打开程序第一眼看到的页面。只列需要处理的事，每件事都带一个直接处理的按钮。
import { openInPlaceLogin, updateSessionBadges } from "/static/host/session.js";
import { useState } from "/static/host/vendor/preact-htm.js";
import {
  ErrorCard, PageHead, activeDeliverables, Progress, Skeleton, Todo, api, completionCount, deliverableHref, html, shortTime, todayString, useLoad, useWorkbenchStyles,
} from "./common.js";
import { ProjectSwitcher } from "./projects.js";
import { Wizard, wizardDismissed } from "./wizard.js";

const SOURCES = {
  status: "/api/project-status",
  settings: "/api/settings",
  scheduler: "/api/project-status/scheduler",
  signDaily: "/api/p/sign-daily/state",
  updates: "/api/p/settings/app-updates",
  tasks: "/api/tasks?limit=30",
};

function greeting() {
  const hour = new Date().getHours();
  if (hour < 11) return "早上好";
  if (hour < 14) return "中午好";
  if (hour < 19) return "下午好";
  return "晚上好";
}

function sessionState(settings) {
  const sessions = (settings && settings.sessions) || {};
  const systems = ["aras", "tdc"].map((key) => sessions[key] || {});
  return {
    loggedIn: systems.every((s) => s.authenticated && !s.expired),
    expired: systems.some((s) => s.expired),
    savedPassword: Boolean(settings && settings.credentialVaultConfigured),
  };
}

function currentNode(milestones) {
  return (milestones || []).find((m) => m.status !== "已完成") || null;
}

function buildTodos({ status, settings, scheduler, signDaily, updates }, actions) {
  const todos = [];
  const session = sessionState(settings);
  if (settings && !session.loggedIn) {
    todos.push({
      key: "login",
      tone: "warn",
      icon: "🔑",
      title: session.expired ? "登录已过期，自动同步已暂停" : "还没有登录公司账号",
      detail: "登录一次即可同时连通 Aras 和 TDC，之后会自动补跑错过的同步。",
      actions: [{ label: "登录", onClick: actions.login }],
    });
  }
  const deliverables = activeDeliverables(status && status.deliverables);
  deliverables
    .filter((d) => d.syncDisplay && d.syncDisplay.lastError)
    .forEach((d) => todos.push({ key: `err-${d.id}`, error: d }));
  deliverables
    .filter((d) => d.scheduleState === "overdue")
    .sort((a, b) => (b.scheduleDays || 0) - (a.scheduleDays || 0))
    .forEach((d) => todos.push({
      key: `late-${d.id}`,
      tone: "bad",
      icon: "⏰",
      title: `${d.name} 已逾期 ${d.scheduleDays} 天`,
      detail: `计划完成 ${d.plannedDate || "未设置"} · 当前进度 ${d.progress ?? 0}% · ${d.status}`,
      actions: [{ label: "查看明细", href: deliverableHref(d.id) }],
    }));
  deliverables
    .filter((d) => d.scheduleState && d.scheduleState !== "overdue" && d.scheduleState !== "done")
    .forEach((d) => todos.push({
      key: `soon-${d.id}`,
      tone: "warn",
      icon: "📅",
      title: `${d.name} 即将到期`,
      detail: `计划完成 ${d.plannedDate} · 当前进度 ${d.progress ?? 0}%`,
      actions: [{ label: "查看明细", href: deliverableHref(d.id) }],
    }));
  if (scheduler && !scheduler.eligibleCount) {
    todos.push({
      key: "sync-off",
      tone: "info",
      icon: "🔄",
      title: "交付物自动同步还没有开启",
      detail: "开启后进度会按时自动更新，不用再手工维护。",
      actions: [{ label: "去开启", href: "#p/project-overview/details" }],
    });
  }
  const unscheduled = ((status && status.milestones) || []).filter((m) => !m.date);
  if (unscheduled.length) {
    todos.push({
      key: "plan",
      tone: "info",
      icon: "🗓️",
      title: `主计划有 ${unscheduled.length} 个节点还没排期`,
      detail: unscheduled.slice(0, 6).map((m) => m.name).join("、") + (unscheduled.length > 6 ? " …" : ""),
      actions: [{ label: "去排期", href: "#p/project-overview/plan" }],
    });
  }
  if (signDaily && signDaily.data) {
    const fresh = signDaily.data.dataDate === todayString();
    todos.push({
      key: "daily",
      tone: fresh ? "ok" : "warn",
      icon: "📨",
      title: fresh ? "签署日报数据已是今天的" : "今天的签署日报还没生成",
      detail: `数据日期 ${signDaily.data.dataDate || "—"}，生成时会先自动刷新数据。`,
      actions: [{ label: fresh ? "去看看" : "去生成", href: "#p/sign-daily/report" }],
    });
  }
  ((updates && updates.available) || []).slice(0, 1).forEach((u) => todos.push({
    key: `upd-${u.version}`,
    tone: "info",
    icon: "⬆️",
    title: `发现新版本 ${u.version}`,
    detail: u.notes || "在「下载」文件夹里找到了签名有效的更新包",
    actions: [{ label: "去安装", href: "#p/settings/updates" }],
  }));
  ((updates && updates.staged) || []).slice(0, 1).forEach((version) => todos.push({
    key: `staged-${version}`,
    tone: "info",
    icon: "⬆️",
    title: `新版本 ${version} 已下载好，重启后生效`,
    detail: "重启大约 10 秒，正在进行的同步会先完成。",
    actions: [{ label: "去重启", href: "#p/settings/updates" }],
  }));
  return todos;
}

function ProgressCard({ status }) {
  if (!status || !status.phase) return null;
  const phase = status.phase;
  const node = currentNode(status.milestones);
  const counts = completionCount(status.deliverables);
  return html`<div class="wb-card">
    <div class="wb-card-head"><h3>项目进度</h3><a class="wb-link" href="#p/workbench/project">详情 ›</a></div>
    <div class="wb-big">${phase.overallProgress ?? 0}%</div>
    <${Progress} value=${phase.overallProgress} />
    <p class="wb-small wb-muted" style="margin:8px 0 0">计划应达到 ${status.summary && status.summary.planned} · 已完成 ${counts.done}/${counts.total} 项交付物</p>
    <p class="wb-small" style="margin:8px 0 0">当前节点：<b>${node ? node.name : "全部完成"}</b>${node && node.date ? ` · 计划 ${node.date}` : node ? " · 待排期" : ""}</p>
  </div>`;
}

function RecentTasks({ tasks }) {
  const list = ((tasks && tasks.tasks) || []).filter((t) => t && !t.is_active).slice(0, 5);
  return html`<div class="wb-card">
    <h3 style="margin-bottom:8px">最近完成的后台任务</h3>
    ${list.length
      ? list.map((t) => html`<div class="wb-small" key=${t.id} style="padding:4px 0">${/fail|error|cancel/i.test(t.status) ? "⚠" : "✓"} ${t.title || "后台任务"} <span class="wb-muted">${shortTime(t.updated_at || t.created_at)}</span></div>`)
      : html`<p class="wb-small wb-muted" style="margin:0">暂无</p>`}
  </div>`;
}

export default function TodayPage() {
  useWorkbenchStyles();
  const { data, errors, loading, reload } = useLoad(SOURCES);
  const [showWizard, setShowWizard] = useState(null);

  const login = () => openInPlaceLogin({
    notice: "登录后自动补跑错过的同步",
    onLoginSuccess: () => reload(),
  });

  if (loading && !data.status) return html`<div class="wb-page"><${Skeleton} /></div>`;

  const status = data.status;
  const session = sessionState(data.settings);
  const wizardOpen = showWizard ?? (Boolean(data.settings) && !session.loggedIn && !session.expired && !wizardDismissed());
  const todos = buildTodos(data, { login });
  const scheduler = data.scheduler;
  const syncLine = scheduler
    ? (scheduler.paused ? "自动同步已暂停" : scheduler.eligibleCount ? `自动同步运行中（${scheduler.eligibleCount} 项）` : "自动同步未开启")
    : "自动同步状态未知";
  const projectName = status && status.phase ? status.phase.displayName : "";

  return html`<div class="wb-page">
    <${PageHead}
      title=${`${greeting()}`}
      sub=${`${projectName ? `${projectName} 项目 · ` : ""}今天 ${todayString()} · ${syncLine}`}
      actions=${html`<${ProjectSwitcher} /><button type="button" class="wb-btn" onClick=${reload} disabled=${loading}>${loading ? "刷新中…" : "刷新"}</button>`}
    />
    <div class="wb-split">
      <section class="wb-todos" aria-label="需要处理的事">
        <h2>需要你处理 <span class="wb-muted wb-small">(${todos.length})</span></h2>
        ${errors.status && html`<${ErrorCard} title="项目数据读取失败" what=${errors.status.message} todo="点「重试」；如果仍然失败，到「设置」里导出诊断包发给支持人员。" actions=${[{ label: "重试", onClick: reload }]} />`}
        ${todos.map((todo) => todo.error
          ? html`<${ErrorCard} key=${todo.key}
              title=${`${todo.error.name} 同步失败`}
              what=${todo.error.syncDisplay.lastError}
              todo=${session.loggedIn ? "到明细页点「立即同步」重试；如果仍然失败，导出诊断包发给支持人员。" : "先重新登录，系统会自动重试。"}
              actions=${session.loggedIn ? [{ label: "查看并重试", href: deliverableHref(todo.error.id) }] : [{ label: "重新登录", onClick: login }]} />`
          : html`<${Todo} key=${todo.key} ...${todo} />`)}
        ${!todos.length && !errors.status && html`<div class="wb-card"><b>🎉 今天没有需要处理的事</b><p class="wb-sub">交付物进度会按时自动更新。</p></div>`}
      </section>
      <aside class="wb-grid">
        <${ProgressCard} status=${status} />
        <${RecentTasks} tasks=${data.tasks} />
      </aside>
    </div>
    ${wizardOpen && html`<${Wizard} projectName=${projectName} onClose=${(done) => {
      setShowWizard(false);
      if (done) api("/api/settings").then((s) => s && s.sessions && updateSessionBadges(s.sessions)).catch(() => {}).finally(reload);
    }} />`}
  </div>`;
}
