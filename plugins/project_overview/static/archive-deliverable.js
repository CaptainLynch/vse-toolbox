// #p/project-overview/archive-deliverable?job=<jobKey> — an external
// scheduled-archive job shown as a deliverable (legacy
// renderArchiveDeliverableDetailPage + refreshOverviewArchiveJobs +
// runArchiveDetailBackgroundSync / runDeliverableFormArchiveSync /
// runPaaInteractiveRefresh).
import { html, useCallback, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { useStylesheet } from "/static/host/kit.js";
import { hashParams } from "./shared/client.js";
import { LOCAL_ONLY_MESSAGE, apiRequest, enc, isLocalOnlyError, plainErrorMessage } from "./deliverable/api.js";
import { FormAnalysisPanel } from "./deliverable/form-analysis.js";
import { archiveSyncStateLabel, errorText, redactSensitiveText, safeDisplayValue } from "./deliverable/format.js";
import {
  INTERACTIVE_MODES,
  buildInteractiveArasPayload,
  buildPaaInteractiveFilters,
  formatInteractiveArasError,
  formatInteractiveArasResult,
  interactiveFilterValue,
} from "./deliverable/policy-logic.js";
import { InteractiveResult } from "./deliverable/status-chart.js";

const LIST_HASH = "#p/project-overview/details";

export const ARCHIVE_JOB_LABELS = {
  aras_paa: ["PAA 变更记录", "ARAS PAA"],
  aras_ncr_progress: ["NCR 审批进度", "ARAS NCR"],
  aras_ncr_detail: ["NCR 审批明细", "ARAS NCR"],
  tdc_data_model: ["数模设计审核流程报表", "TDC"],
  tdc_sor: ["SOR 定点流程", "TDC"],
};

function currentJobKey() {
  return String(hashParams().get("job") || "");
}

function syncTone(state) {
  if (state === "success") return "success";
  if (state === "failed") return "error";
  return "warning";
}

/** sync-now result check shared by both sync buttons; throws on an unfinished run. */
function assertSyncCompleted(data, fallback) {
  const result = data || {};
  const first = Array.isArray(result.results) && result.results[0] ? result.results[0] : null;
  if (result.exitCode !== 0 || (first && first.outcome !== "completed")) {
    const message = (first && (first.errorMessage || first.errorType))
      || (result.exitCode ? `同步未就绪（退出码 ${result.exitCode}）` : fallback);
    throw new Error(redactSensitiveText(message));
  }
}

function syncErrorText(err, fallback) {
  if (err instanceof Error && !("status" in err)) return redactSensitiveText(err.message);
  return redactSensitiveText(plainErrorMessage(err, fallback));
}

function RunHistory({ jobKey, reloadSeq }) {
  const [state, setState] = useState({ status: "loading", runs: [], error: "" });
  useEffect(() => {
    let alive = true;
    setState({ status: "loading", runs: [], error: "" });
    apiRequest(`/api/scheduled-archive/runs?jobKey=${enc(jobKey)}&limit=12`)
      .then((data) => { if (alive) setState({ status: "ready", runs: Array.isArray(data) ? data : [], error: "" }); })
      .catch((err) => { if (alive) setState({ status: "error", runs: [], error: redactSensitiveText(plainErrorMessage(err, "同步历史加载失败")) }); });
    return () => { alive = false; };
  }, [jobKey, reloadSeq]);

  let body;
  if (state.status === "loading") body = html`<p class="loading">正在加载同步历史...</p>`;
  else if (state.status === "error") body = html`<p class="error-msg">同步历史加载失败：${state.error}</p>`;
  else if (!state.runs.length) body = html`<p class="is-empty">暂无同步历史，执行首次同步后将显示趋势</p>`;
  else {
    body = html`<div class="external-run-table-wrap"><table class="external-run-table">
      <thead><tr>${["完成时间", "状态", "记录数", "结果摘要"].map((label) => html`<th key=${label}>${label}</th>`)}</tr></thead>
      <tbody>
        ${state.runs.slice(0, 6).map((run, index) => html`<tr key=${run.id || index}>
          ${[
            run.finishedAt || run.startedAt || "暂无",
            run.runState === "success" ? "成功" : "失败",
            String(Number(run.recordCount) || 0),
            run.errorMessage ? redactSensitiveText(run.errorMessage) : (run.resultSummary || "无"),
          ].map((value, col) => html`<td key=${col}>${safeDisplayValue(value)}</td>`)}
        </tr>`)}
      </tbody>
    </table></div>`;
  }
  return html`<section class="external-detail-history">
    <h5 class="section-sub-title">同步运行记录</h5>
    <div class="external-detail-history-body">${body}</div>
  </section>`;
}

function ArchiveDetail({ job, refreshJobs }) {
  const [name, source] = ARCHIVE_JOB_LABELS[job.jobKey] || [job.jobKey, "外部同步"];
  const isPaa = job.jobKey === "aras_paa";
  const [message, setMessage] = useState(null);
  const [historySeq, setHistorySeq] = useState(0);
  const [syncBusy, setSyncBusy] = useState(false);
  const [interactive, setInteractive] = useState({ visible: false, busy: false, data: null, targetKey: "" });
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  const formCtl = useRef(null);
  const formItem = {
    name,
    externalJobKey: job.jobKey,
    isExternalArchive: true,
    // 表单键由任务 payload 下发（单一关联注册表派生）。
    formKey: String(job.formKey || ""),
  };
  const statusText = message === null ? `最近同步状态：${archiveSyncStateLabel(job.syncState)}` : message;
  const say = (text) => { if (alive.current) setMessage(text); };

  const runSyncNow = () => apiRequest(`/api/scheduled-archive/jobs/${enc(job.jobKey)}/sync-now`, { method: "POST" });

  const backgroundSync = async () => {
    setSyncBusy(true);
    say("正在执行后台归档同步...");
    try {
      assertSyncCompleted(await runSyncNow(), "同步未完成");
      say("同步成功，正在刷新图表与明细...");
      await refreshJobs();
      say(null);
      if (alive.current) setHistorySeq((value) => value + 1);
    } catch (err) {
      say(`同步失败：${syncErrorText(err, "同步失败")}`);
    } finally {
      if (alive.current) setSyncBusy(false);
    }
  };

  const formBackgroundSync = async (reload) => {
    say("正在执行后台归档同步...");
    try {
      assertSyncCompleted(await runSyncNow(), "后台同步未完成");
      say("后台同步完成，正在刷新表单快照...");
      await refreshJobs();
      // 归档同步可能发布新的表单快照，重新读取关联视图。
      if (typeof reload === "function") await reload();
      say(null);
      if (alive.current) setHistorySeq((value) => value + 1);
    } catch (err) {
      say(`同步失败：${syncErrorText(err, "后台同步未完成")}`);
    }
  };

  const interactiveRefresh = async () => {
    const filters = buildPaaInteractiveFilters(job.filters || {});
    const targetKey = interactiveFilterValue(job.filters && job.filters.paaNo);
    setInteractive((prev) => ({ ...prev, visible: true, busy: true }));
    say("正在执行交互式查询...");
    try {
      const data = (await apiRequest(INTERACTIVE_MODES.paa.endpoint, { method: "POST", body: buildInteractiveArasPayload("paa", filters) })) || {};
      if (!alive.current) return;
      setInteractive({ visible: true, busy: false, data, targetKey });
      say(`交互式查询完成：${formatInteractiveArasResult(data, targetKey, "paa").text}`);
    } catch (err) {
      if (!alive.current) return;
      setInteractive((prev) => ({ ...prev, busy: false }));
      say(isLocalOnlyError(err) ? LOCAL_ONLY_MESSAGE : formatInteractiveArasError(err, err && err.status));
    }
  };

  const credentialState = job.credentialAvailable === false ? "缺少凭据" : job.credentialAvailable === true ? "已配置" : "状态未知";
  const metrics = [
    ["同步状态", archiveSyncStateLabel(job.syncState)],
    ["最近成功", job.lastSuccessAt || "暂无"],
    ["最近尝试", job.lastAttemptAt || "暂无"],
    ["数据新鲜度", job.freshness || "未知"],
  ];
  const pairs = [
    ["同步状态", archiveSyncStateLabel(job.syncState)],
    ["数据来源", source],
    ["认证状态", credentialState],
    ["最近成功", job.lastSuccessAt || "暂无"],
    ["最近尝试", job.lastAttemptAt || "暂无"],
    ["错误详情", job.lastErrorMessage ? redactSensitiveText(job.lastErrorMessage) : "无"],
  ];

  return html`<article class="deliverable-detail-page" data-external-job-key=${job.jobKey}>
    <div class="deliverable-detail-page-head">
      <div class="deliverable-detail-page-nav">
        <a class="segment back-to-list-btn" href=${LIST_HASH}>← 返回交付物列表</a>
      </div>
      <div class="deliverable-detail-title-row">
        <div>
          <p class="eyebrow">交付物明细</p>
          <h3 class="deliverable-page-title">${name}</h3>
          <span class="deliverable-page-id">任务 ID: ${safeDisplayValue(job.jobKey)}</span>
        </div>
        <span class=${`status-text is-${syncTone(job.syncState)}`}>${archiveSyncStateLabel(job.syncState)}</span>
      </div>
    </div>

    <section class="deliverable-page-meta-section overview-band external-progress-chart">
      <div class="external-detail-section-head">
        <h5 class="section-sub-title">当前状态图表</h5>
        <div class="external-detail-actions">
          <button type="button" class="btn" onClick=${() => setHistorySeq((value) => value + 1)}>${isPaa ? "刷新后台历史" : "刷新同步数据"}</button>
          ${isPaa && html`<button type="button" class="btn is-primary paa-interactive-refresh-btn" data-query-mode="interactive"
            disabled=${interactive.busy} onClick=${interactiveRefresh}>${interactive.busy ? "交互式查询中..." : "立即刷新（交互式查询）"}</button>`}
          ${!isPaa && html`<button type="button" class="btn is-secondary" disabled=${syncBusy || !job.enabled}
            onClick=${backgroundSync}>${syncBusy ? "后台归档同步中..." : "后台归档同步"}</button>`}
        </div>
      </div>
      <p class="external-detail-sync-message" role="status">${statusText}</p>
      ${isPaa && html`<section class="external-interactive-query-panel" hidden=${!interactive.visible} aria-live="polite">
        ${interactive.data && html`<${InteractiveResult} mode="paa" data=${interactive.data} targetKey=${interactive.targetKey} />`}
      </section>`}
      <div class="external-detail-metrics">
        ${metrics.map(([label, value]) => html`<div class="external-detail-metric" key=${label}>
          <span>${label}</span><strong>${safeDisplayValue(value)}</strong>
        </div>`)}
      </div>
      <${RunHistory} jobKey=${job.jobKey} reloadSeq=${historySeq} />
    </section>

    <section class="deliverable-form-analysis" aria-label=${`${name} 表单明细与分析`}>
      <${FormAnalysisPanel}
        item=${formItem}
        version=${0}
        ctl=${formCtl}
        archive=${{ job, onBackgroundSync: formBackgroundSync }}
      />
    </section>

    <details class="deliverable-page-meta-section overview-band external-detail-info">
      <summary>详细信息（点击展开）</summary>
      <div class="detail-inline-grid">
        ${pairs.map(([label, value]) => html`<div class="detail-property" key=${label}>
          <span class="detail-property-label">${label}</span>
          <span class="detail-property-value">${safeDisplayValue(value)}</span>
        </div>`)}
      </div>
      <a class="primary-action" href=${`#p/scheduled-archive/jobs?job=${enc(job.jobKey)}`}>进入任务配置/重试</a>
    </details>
  </article>`;
}

export default function ArchiveDeliverablePage({ plugin }) {
  useStylesheet(`/plugins/${(plugin && plugin.id) || "project-overview"}/static/deliverable.css`);
  const [jobKey, setJobKey] = useState(currentJobKey);
  const [state, setState] = useState({ status: "loading", jobs: null, error: "" });
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    const onHash = () => {
      const next = currentJobKey();
      setJobKey((prev) => (prev === next ? prev : next));
    };
    window.addEventListener("hashchange", onHash);
    return () => {
      alive.current = false;
      window.removeEventListener("hashchange", onHash);
    };
  }, []);

  // refreshOverviewArchiveJobs: a failed refresh keeps the current list.
  const refreshJobs = useCallback(async () => {
    try {
      const data = await apiRequest("/api/scheduled-archive/jobs");
      if (!alive.current) return false;
      if (!Array.isArray(data)) throw new Error("外部同步任务列表格式无效");
      setState({ status: "ready", jobs: data.slice(), error: "" });
      return true;
    } catch (err) {
      if (alive.current) setState((prev) => (prev.jobs ? prev : { status: "error", jobs: null, error: errorText(err) }));
      return false;
    }
  }, []);

  useEffect(() => { refreshJobs(); }, []);
  useEffect(() => { if (typeof window.scrollTo === "function") window.scrollTo(0, 0); }, [jobKey]);

  if (!state.jobs && state.status === "loading") {
    return html`<div class="overview-deliverable-detail-view"><p class="loading">加载外部同步任务...</p></div>`;
  }
  if (!state.jobs) {
    return html`<div class="overview-deliverable-detail-view deliverable-detail-not-found">
      <p class="error-msg">外部同步任务加载失败：${state.error}</p>
      <div class="deliverable-detail-not-found-actions">
        <button type="button" class="btn is-secondary" onClick=${() => { setState({ status: "loading", jobs: null, error: "" }); refreshJobs(); }}>重试</button>
        <a class="segment back-to-list-btn" href=${LIST_HASH}>← 返回交付物列表</a>
      </div>
    </div>`;
  }
  const job = state.jobs.find((candidate) => candidate && candidate.jobKey === jobKey) || null;
  if (!job) {
    return html`<div class="overview-deliverable-detail-view deliverable-detail-not-found">
      <p class="error-msg">未找到该外部同步任务，请返回列表刷新后重试</p>
      <a class="segment back-to-list-btn" href=${LIST_HASH}>← 返回交付物列表</a>
    </div>`;
  }
  return html`<div class="overview-deliverable-detail-view">
    <${ArchiveDetail} key=${job.jobKey} job=${job} refreshJobs=${refreshJobs} />
  </div>`;
}
