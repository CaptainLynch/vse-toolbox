// #p/project-overview/archive-deliverable?job=<jobKey> — an external
// scheduled-archive job shown as a deliverable (legacy
// renderArchiveDeliverableDetailPage + refreshOverviewArchiveJobs +
// runArchiveDetailBackgroundSync / runDeliverableFormArchiveSync /
// runPaaInteractiveRefresh).
import { html, useCallback, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { formatBeijing, parseInstant } from "/static/host/time-format.js";
import { useStylesheet } from "/static/host/kit.js";
import { hashParams } from "./shared/client.js";
import { LOCAL_ONLY_MESSAGE, apiRequest, enc, isLocalOnlyError, plainErrorMessage } from "./deliverable/api.js";
import { FormAnalysisPanel } from "./deliverable/form-analysis.js";
import {
  archiveSyncStateLabel,
  errorText,
  formatArtifactSize,
  redactSensitiveText,
  safeDisplayValue,
} from "./deliverable/format.js";
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

const ARCHIVE_RUNS_PATH = "/api/scheduled-archive/runs";
const ARCHIVE_FOLDERS_PATH = "/api/scheduled-archive/folders";

function runStateText(state) {
  if (state === "success") return "成功";
  if (state === "failed") return "失败";
  if (state === "needs_attention") return "需关注";
  return "进行中";
}

/**
 * 运行时间统一按北京时间展示（复用宿主 /static/host/time-format.js）。
 * 只换算带显式时区的取值，无时区/非法值原样展示，绝不按浏览器时区静默偏移。
 */
const ZONED_INSTANT_RE = /(?:Z|[+-]\d{2}:\d{2})$/i;

function beijingTimeText(value) {
  if (!value) return "未知时间";
  const text = String(value).trim();
  if (!ZONED_INSTANT_RE.test(text)) return safeDisplayValue(text);
  try {
    return formatBeijing(parseInstant(text));
  } catch (_) {
    return safeDisplayValue(text);
  }
}

function artifactParentDir(relativePath) {
  const text = String(relativePath || "").replace(/\\/g, "/");
  const index = text.lastIndexOf("/");
  return index > 0 ? text.slice(0, index) : "";
}

/**
 * 核对原件所在目录是否还在（既有 /api/scheduled-archive/folders 只读接口）。
 * 既有 artifacts 接口不返回文件存在性，也没有下载路由：这里只把「目录已不存在」
 * 判为原件缺失，其余保持「已记录（暂无下载接口）」，绝不谎报可下载。
 */
async function artifactAvailability(items, outputDirectory) {
  const missing = new Set();
  const unknown = new Set();
  if (!items.length) return { missing, unknown };
  const dirs = new Set(items.map((item) => artifactParentDir(item.relativePath)).filter(Boolean));
  if (String(outputDirectory || "").trim()) {
    // 任务自定义归档目录不在全局归档根下，既有目录接口无法核验：状态未知，不谎报缺失。
    dirs.forEach((dir) => unknown.add(dir));
    return { missing, unknown };
  }
  await Promise.all(Array.from(dirs).map(async (dir) => {
    try {
      await apiRequest(`${ARCHIVE_FOLDERS_PATH}?path=${enc(dir)}`);
    } catch (err) {
      if (err && err.status === 404) missing.add(dir);
      else unknown.add(dir);
    }
  }));
  return { missing, unknown };
}

function artifactStateKey(art, missingDirs, unknownDirs) {
  if (art && (art.exists === false || art.missing === true)) return "missing";
  const dir = artifactParentDir(art && art.relativePath);
  if (missingDirs.has(dir)) return "missing";
  if (unknownDirs.has(dir)) return "unknown";
  return "recorded";
}

function OriginalArtifactsPanel({ jobKey, outputDirectory, reloadSeq }) {
  const [state, setState] = useState({ status: "loading", runs: [], error: "" });
  const [seq, setSeq] = useState(0);
  const [expanded, setExpanded] = useState({
    runId: null,
    status: "idle",
    error: "",
    items: [],
    missing: [],
    unknown: [],
  });

  useEffect(() => {
    let alive = true;
    setState({ status: "loading", runs: [], error: "" });
    apiRequest(`${ARCHIVE_RUNS_PATH}?jobKey=${enc(jobKey)}&limit=12`)
      .then((data) => {
        if (alive) setState({ status: "ready", runs: Array.isArray(data) ? data : [], error: "" });
      })
      .catch((err) => {
        if (alive) setState({ status: "error", runs: [], error: redactSensitiveText(plainErrorMessage(err, "历史原件加载失败")) });
      });
    return () => { alive = false; };
  }, [jobKey, reloadSeq, seq]);

  useEffect(() => {
    setExpanded({ runId: null, status: "idle", error: "", items: [], missing: [], unknown: [] });
  }, [jobKey]);

  const toggleRun = async (runId) => {
    if (expanded.runId === runId && expanded.status !== "idle") {
      setExpanded({ runId: null, status: "idle", error: "", items: [], missing: [], unknown: [] });
      return;
    }
    setExpanded({ runId, status: "loading", error: "", items: [], missing: [], unknown: [] });
    try {
      const data = await apiRequest(`${ARCHIVE_RUNS_PATH}/${enc(runId)}/artifacts`);
      const items = data && Array.isArray(data.artifacts) ? data.artifacts : [];
      const availability = await artifactAvailability(items, outputDirectory);
      setExpanded({
        runId,
        status: "ready",
        error: "",
        items,
        missing: Array.from(availability.missing),
        unknown: Array.from(availability.unknown),
      });
    } catch (err) {
      setExpanded({
        runId,
        status: "error",
        error: redactSensitiveText(plainErrorMessage(err, "原件清单读取失败")),
        items: [],
        missing: [],
        unknown: [],
      });
    }
  };

  const detailBody = (runId) => {
    if (expanded.runId !== runId || expanded.status === "idle") return null;
    if (expanded.status === "loading") return html`<p class="loading">正在读取原件清单...</p>`;
    if (expanded.status === "error") return html`<p class="error-msg">${expanded.error}</p>`;
    if (!expanded.items.length) {
      return html`<p class="archive-originals-empty">该次运行未记录原件清单</p>`;
    }
    const missingDirs = new Set(expanded.missing);
    const unknownDirs = new Set(expanded.unknown);
    return html`<table class="external-run-table archive-originals-artifacts">
      <thead><tr>${["原件名称", "类型", "大小", "状态"].map((label) => html`<th key=${label}>${label}</th>`)}</tr></thead>
      <tbody>
        ${expanded.items.map((art, index) => {
          const name = safeDisplayValue(art.displayName || art.relativePath || "未命名文件");
          const stateKey = artifactStateKey(art, missingDirs, unknownDirs);
          let statusCell;
          if (stateKey === "missing") {
            statusCell = html`<span class="archive-original-state is-missing">原件缺失</span>`;
          } else if (stateKey === "unknown") {
            statusCell = html`<span class="archive-original-state is-unknown">原件状态未知（暂无下载接口）</span>`;
          } else if (art.downloadUrl) {
            statusCell = html`<a class="btn is-secondary" href=${art.downloadUrl} download=${name}>下载</a>`;
          } else {
            statusCell = html`<span class="archive-original-state is-recorded">已记录（暂无下载接口）</span>`;
          }
          return html`<tr class="archive-original-artifact" key=${index}>
            <td>${name}</td>
            <td>${safeDisplayValue(art.artifactType || "—")}</td>
            <td>${formatArtifactSize(art.sizeBytes)}</td>
            <td>${statusCell}</td>
          </tr>`;
        })}
      </tbody>
    </table>`;
  };

  let body;
  if (state.status === "loading") body = html`<p class="loading" role="status">正在加载历史原件...</p>`;
  else if (state.status === "error") body = html`<p class="error-msg">历史原件加载失败：${state.error}</p>`;
  else if (!state.runs.length) body = html`<p class="is-empty">暂无历史原件记录</p>`;
  else {
    body = html`<div class="external-run-table-wrap"><table class="external-run-table archive-originals-table">
      <thead><tr>${["运行时间（北京时间）", "运行 ID", "状态", "原件清单", "操作"].map((label) => html`<th key=${label}>${label}</th>`)}</tr></thead>
      <tbody>
        ${state.runs.map((run) => {
          const runId = run.id;
          const isOpen = expanded.runId === runId;
          const countText = isOpen && expanded.status === "ready" ? `${expanded.items.length} 个原件` : "—";
          const mainRow = html`<tr class="archive-originals-run" data-run-id=${runId} key=${`run-${runId}`}>
            <td>${beijingTimeText(run.finishedAt || run.startedAt || run.createdAt)}</td>
            <td>#${safeDisplayValue(runId)}</td>
            <td><span class=${`status-text is-${run.runState === "success" ? "success" : (run.runState === "failed" ? "error" : "warning")}`}>${runStateText(run.runState)}</span></td>
            <td>${countText}</td>
            <td><button type="button" class="btn is-secondary archive-originals-toggle" data-run-id=${runId} onClick=${() => toggleRun(runId)}>${isOpen ? "收起原件" : "查看原件"}</button></td>
          </tr>`;
          const detailRow = isOpen
            ? html`<tr class="archive-originals-detail" data-run-id=${runId} key=${`detail-${runId}`}>
                <td colspan="5">${detailBody(runId)}</td>
              </tr>`
            : null;
          return html`${mainRow}${detailRow}`;
        })}
      </tbody>
    </table></div>`;
  }

  return html`<section class="archive-originals-panel" aria-label="历史原件">
    <div class="external-detail-section-head">
      <h5 class="section-sub-title">历史原件</h5>
      <button type="button" class="btn is-secondary archive-originals-refresh" onClick=${() => setSeq((value) => value + 1)}>刷新原件</button>
    </div>
    <p class="archive-originals-note">按同步运行列出该次写出的原件；文件缺失时只显示「原件缺失」，不提供下载。</p>
    ${body}
  </section>`;
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
      <${OriginalArtifactsPanel}
        jobKey=${job.jobKey}
        outputDirectory=${job.outputDirectory || ""}
        reloadSeq=${historySeq}
      />
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
