// 「报告」：所有对外产出的东西集中在这里，统一成"选条件 → 一键生成 → 发出去"。
// 日报的一键生成在宿主模块 /static/host/report-controller.js 里（提交→进度→预览→复制/邮件草稿）；
// 本页只渲染结果，不复制日报口径，也不 import 其他插件的模块。
import { useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { PageHead, Pill, Progress, go, html, todayString, useLoad, useWorkbenchStyles } from "./common.js";
import {
  blockReason, copyPayload, copyToClipboard, downloadEml, exportAllowed, isStatusGateError, missingChartKeys,
  previewHtml, runSignDaily,
} from "/static/host/report-controller.js";

// 关注清单只有一份权威数据（契约 C5）：报告中心只读交付物详情用的同一个接口，
// 不在这里另存副本，也不另算数量。字段与 project_overview 的详情面板同源。
export const WATCHLIST_PATH = "/api/p/project-overview/watchlist";
export const WATCHLIST_CSV_PATH = "/api/p/project-overview/watchlist.csv";
export const WATCHLIST_DETAIL = "#p/project-overview/deliverable?id=VPI-T2-D5";
const FORMS_LIST = "#p/project-overview/details";
const EXPORT_PAGE = "#p/system-query/query";
const SOURCES = {
  signDaily: "/api/p/sign-daily/state",
  tir: "/api/p/tir-report/state",
  watchlist: WATCHLIST_PATH,
};
const DAILY_PAGE = "#p/sign-daily/report";
const IDLE = { phase: "idle", task: null, result: null, images: {}, body: null, imagesError: "", error: null, notice: "" };

/** 卡片按钮（直接返回节点，不是组件）：所有按钮共用同一套样式与禁用语义。 */
function Button({ label, primary, disabled, onClick }) {
  return html`<button type="button" class=${`wb-btn${primary ? " is-primary" : ""}`}
    disabled=${disabled === true} onClick=${onClick}>${label}</button>`;
}

function Entry({ icon, title, text, status, actions = [], children }) {
  return html`<div class="wb-card wb-entry">
    <div class="wb-row" style="justify-content:space-between"><span class="wb-entry-icon" aria-hidden="true">${icon}</span>${status}</div>
    <h3>${title}</h3>
    <p>${text}</p>
    <div class="wb-row">${actions.map((action, index) => html`<button key=${index} type="button"
      class=${`wb-btn${action.primary ? " is-primary" : ""}`}
      disabled=${action.disabled === true}
      onClick=${action.onClick || (() => go(action.href))}>${action.label}</button>`)}</div>
    ${children}
  </div>`;
}

/**
 * 关注清单只做只读摘要：count / scope / missing / configIssue / items 全部原样来自
 * GET /api/p/project-overview/watchlist（交付物详情同一接口），报告页不自行统计。
 */
export function watchlistSummary(watchlist) {
  if (!watchlist) return null;
  return {
    count: Number(watchlist.count) || 0,
    scope: watchlist.scope === "watchlist" ? "仅关注清单" : "全部表单",
    missing: Array.isArray(watchlist.missing) ? watchlist.missing.length : 0,
    configIssue: String(watchlist.configIssue || ""),
    items: Array.isArray(watchlist.items) ? watchlist.items : [],
  };
}

/** 报告中心的关注清单入口：查看同一份清单，维护仍回交付物详情。 */
export function WatchlistCard({ watchlist, error }) {
  const summary = watchlistSummary(watchlist);
  const status = summary
    ? html`<${Pill} tone=${summary.configIssue ? "warn" : "info"}>${summary.count} 份 · ${summary.scope}<//>`
    : html`<${Pill} tone="warn">暂不可用<//>`;
  return html`<${Entry} icon="⭐" title="关注清单"
    text="数模设计审核流程的关注单号只有一份：这里只读交付物详情用的同一接口，维护请到交付物详情。"
    status=${status}
    actions=${[{ label: "在交付物详情维护", href: WATCHLIST_DETAIL }]}>
    ${summary
      ? html`<p class="wb-muted wb-small">同步范围：${summary.scope}；共 ${summary.count} 份${summary.missing ? `；${summary.missing} 份未找到` : ""}${summary.configIssue ? `；${summary.configIssue}` : ""}</p>
        <p class="wb-row"><a class="wb-btn" href=${WATCHLIST_CSV_PATH} download="watchlist.csv">导出 CSV</a></p>`
      : html`<p class="wb-muted wb-small">${error ? `关注清单读取失败：${error.message || error}` : "正在读取关注清单…"}</p>`}
  <//>`;
}

/**
 * F5/F6/F7 的导出定位只有这一张表：报告中心只把用户送到既有实现，
 * 不复制导出逻辑。F7 的 generation_unknown 沿用「只生成/人工核查、不自动重发」红线。
 */
export const EXPORT_TARGETS = Object.freeze([
  {
    id: "F5",
    label: "Aras 报表",
    detail: "EWO / PAA / NCR 进度与明细（CSV、官方工作簿）",
    href: `${EXPORT_PAGE}?mode=ewo`,
  },
  {
    id: "F6",
    label: "TDC 报表",
    detail: "数模 / SOR / A 面（XLSX、全量抓取、合并导出）",
    href: `${EXPORT_PAGE}?mode=tdc-data-model`,
  },
  {
    id: "F7",
    label: "EWO 增强导表",
    detail: "打开 EWO 交付物详情，在「数据与统计」页使用增强导表面板",
    href: "#p/project-overview/deliverable?id=VPI-T2-D3",
    manualCheck: "生成结果未知（generation_unknown）时只做人工核查，不自动重发。",
  },
]);

/** F5/F6/F7 共用的定位解析：未知编号返回 null，页面据此不渲染入口。 */
export function exportTarget(featureId) {
  const id = String(featureId || "").toUpperCase();
  return EXPORT_TARGETS.find((target) => target.id === id) || null;
}

/** 报告中心的统一导出卡片：三个入口都来自 EXPORT_TARGETS，不各写一份跳转。 */
export function ExportCard() {
  return html`<${Entry} icon="⬇️" title="业务系统报表导出"
    text="F5/F6/F7 的导出统一从这里定位到既有实现；本页不复制导出逻辑，也不提供自动重发。">
    <div class="wb-export-targets" style="display:grid;gap:12px">
      ${EXPORT_TARGETS.map((target) => html`<div key=${target.id} class="wb-export-target" style="display:grid;gap:4px">
        <div class="wb-row" style="justify-content:space-between">
          <strong>${target.id} · ${target.label}</strong>
          <button type="button" class="wb-btn" onClick=${() => go(target.href)}>打开 ${target.id} 导出</button>
        </div>
        <p class="wb-muted wb-small">${target.detail}</p>
        ${target.manualCheck && html`<p class="wb-muted wb-small">${target.manualCheck}</p>`}
      </div>`)}
    </div>
  <//>`;
}

/** 进度文案只做展示：阶段与百分比都来自后端抓取任务（task_view）。 */
function progressText(run) {
  if (run.phase === "refresh") {
    const task = run.task;
    if (!task) return "正在提交 TDC 抓取任务…";
    const percent = Number.isFinite(task.percent) ? `（${task.percent}%）` : "";
    return `${task.stage || "排队中"}${percent}`;
  }
  if (run.phase === "generate") return "正在生成日报…";
  return "";
}

/** 本次按哪个范围生成：后端记住的选择原样显示，历史残留项目也照样列出、绝不自动删除。 */
function scopeText(form) {
  if (!form) return "还没有保存的范围";
  const projects = (form.projects || []).join("、") || "全部项目";
  const departments = (form.departments || []).join("、") || "全部科室";
  return `${projects} · ${departments}${form.watchlistOnly ? " · 只统计关注清单" : ""}`;
}

export function DailyReportCard({ state, fresh, onReload }) {
  const [run, setRun] = useState(IDLE);
  const alive = useRef(true);
  // 预览区的真实节点：非安全上下文（剪贴板 API 不可用）时用它做选中复制兜底
  const previewNode = useRef(null);
  useEffect(() => () => { alive.current = false; }, []);
  const daily = state || null;
  const form = daily && daily.form;
  const busy = run.phase === "refresh" || run.phase === "generate";
  const result = run.result;
  const gateBlocked = Boolean(result && result.statusGate && result.statusGate.blocked);
  const blocked = result ? blockReason(result) : "";
  const missing = result ? missingChartKeys(result, run.images) : [];
  const canExport = Boolean(result) && !blocked;
  const canEml = canExport && missing.length === 0;

  const generate = async (refresh) => {
    if (!form) return;
    setRun({ ...IDLE, phase: refresh ? "refresh" : "generate" });
    try {
      const outcome = await runSignDaily({
        form,
        preferences: daily.preferences,
        refresh,
        onProgress: (progress) => {
          if (alive.current) setRun((prev) => ({ ...prev, phase: progress.phase, task: progress.task }));
        },
        isAlive: () => alive.current,
      });
      if (!alive.current || !outcome) return;
      setRun({ ...IDLE, phase: "done", result: outcome.result, images: outcome.images, body: outcome.body, imagesError: outcome.imagesError });
      if (onReload) onReload();
    } catch (error) {
      if (!alive.current) return;
      setRun({ ...IDLE, phase: "error", error });
    }
  };

  const copy = async () => {
    try {
      const message = await copyToClipboard(copyPayload(result, run.images), { fallbackNode: previewNode.current });
      if (alive.current) setRun((prev) => ({ ...prev, notice: message }));
    } catch (error) {
      if (alive.current) setRun((prev) => ({ ...prev, notice: error.message }));
    }
  };

  const eml = async () => {
    try {
      await downloadEml({ body: run.body, images: run.images });
      if (alive.current) setRun((prev) => ({ ...prev, notice: "邮件草稿已下载（.eml 只是草稿，不会发送）" }));
    } catch (error) {
      if (alive.current) setRun((prev) => ({ ...prev, notice: error.message }));
    }
  };

  const status = daily && daily.data
    ? html`<${Pill} tone=${fresh ? "ok" : "warn"}>${fresh ? "今天的数据" : `数据日期 ${daily.data.dataDate || "—"}`}<//>`
    : daily && daily.dataError ? html`<${Pill} tone="warn">还没有数据<//>` : null;

  return html`<${Entry} icon="📨" title="3D 单签署日报"
    text="按保存的车型与科室一键生成：先刷新 TDC 数模审批数据，再出三图一表，可直接复制正文或下载邮件草稿。"
    status=${status}
    actions=${[{ label: "调整条件", href: DAILY_PAGE }]}>
    <p class="wb-muted wb-small">生成范围（已保存）：${scopeText(form)}</p>
    <div class="wb-row">
      ${Button({ label: "一键生成日报", primary: true, disabled: busy || !form, onClick: () => generate(true) })}
      ${Button({ label: "用现有数据生成", disabled: busy || !form, onClick: () => generate(false) })}
    </div>
    ${progressText(run) && html`<div class="wb-row" role="status">
      <${Progress} value=${run.phase === "generate" ? 100 : run.task ? run.task.percent : 5} />
      <span class="wb-muted">${progressText(run)}</span>
    </div>`}
    ${run.phase === "error" && html`<div class="wb-errcard" role="alert">
      <strong>⚠ 没能生成日报</strong>
      <dl><dt>发生了什么</dt><dd>${run.error.message}</dd>
        <dt>你需要做什么</dt><dd>${isStatusGateError(run.error)
          ? "状态列是数字码，本次不生成；先确认码值含义或改用归档数据。"
          : "按上面的原因处理后重试，或到完整日报页查看明细。"}</dd></dl>
      <div class="wb-row">${Button({ label: "打开完整日报页", onClick: () => go(DAILY_PAGE) })}</div>
    </div>`}
    ${result && html`<section class="wb-daily-preview" aria-label="日报预览">
      <div><b>${result.subject}</b><br /><span class="wb-muted wb-small">数据日期 ${result.dataDate}${result.baseDate ? `；日变化基线 ${result.baseDate}` : ""}</span></div>
      ${blocked && html`<div class="wb-errcard" role="alert"><strong>⚠ 本次不能复制或导出</strong>
        <p>${blocked}</p>
        ${!gateBlocked && html`<p class="wb-small">长周期初筛要在完整日报页逐项确认；报告中心不提供「按建议继续」的绕过入口。</p>`}
        <div class="wb-row">${Button({ label: "到完整日报页处理", onClick: () => go(DAILY_PAGE) })}</div>
      </div>`}
      ${(result.notices || []).map((notice, index) => html`<p key=${index} class="wb-muted wb-small">${notice.text}</p>`)}
      ${run.imagesError && html`<p class="wb-muted wb-small">图表没能在本页渲染：${run.imagesError}。复制正文仍可用；邮件草稿请到完整日报页下载。</p>`}
      ${!blocked && missing.length > 0 && html`<p class="wb-muted wb-small">有 ${missing.length} 张图没能在本页渲染，邮件草稿请到完整日报页下载。</p>`}
      <div class="wb-row">
        ${Button({ label: "复制正文", primary: true, disabled: !canExport, onClick: copy })}
        ${Button({ label: "下载 .eml 草稿", disabled: !canEml, onClick: eml })}
        ${run.notice && html`<span class="wb-muted wb-small" role="status">${run.notice}</span>`}
      </div>
      <div class="wb-daily-body" ref=${previewNode} style="max-height:520px;overflow:auto;border:1px solid var(--hairline);border-radius:12px;padding:12px;background:#fff;"
        dangerouslySetInnerHTML=${{ __html: previewHtml(result, run.images) }}></div>
    </section>`}
  <//>`;
}

export default function ReportsPage() {
  useWorkbenchStyles();
  const { data, errors = {}, reload } = useLoad(SOURCES);
  const daily = data.signDaily || null;
  const fresh = Boolean(daily && daily.data && daily.data.dataDate === todayString());
  return html`<div class="wb-page">
    <${PageHead} title="报告" sub="所有报告都是同一个流程：选条件 → 一键生成 → 复制或发邮件" />
    <div class="wb-grid wb-grid-2">
      <${DailyReportCard} state=${daily} fresh=${fresh} onReload=${reload} />
      <${Entry} icon="📊" title="TIR 数据简表"
        text="从帆软报表平台导出 TIR 数据简表（Excel），当天已经导出过的直接复用。"
        status=${data.tir ? html`<${Pill} tone="info">可导出<//>` : null}
        actions=${[{ label: "导出 Excel", href: "#p/tir-report/report" }]} />
      <${ExportCard} />
      <${WatchlistCard} watchlist=${data.watchlist} error=${errors.watchlist} />
      <${Entry} icon="🧾" title="交付物表单统计"
        text="六张交付物表单（EWO、PAA、NCR 进度/明细、数模、SOR）的统计图和明细只在交付物详情里查看。"
        actions=${[{ label: "打开交付物明细", href: FORMS_LIST }]} />
    </div>
  </div>`;
}
