// Excel 文件处理工作台（插件模块页）。调用既有接口：
//   /api/excel-roots, /api/excel-worker/{status,start,stop}, /api/excel-tasks[/<id>[/runs|/artifacts]],
//   /api/excel-artifacts/<id>/{download,download-audit}, /api/excel-artifacts/retention-plan,
//   /api/tasks/excel_<id>/cancel（统一任务中心的取消入口）。
import { html, useCallback, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { api, ApiError } from "/static/host/api.js";
import { DataTable, StateBlock, useStylesheet } from "/static/host/kit.js";
import { ExamplesDialog } from "./examples.js";
import {
  ACTIVE_TASK_STATES, ErrorCard, OPERATIONS, STATUS_FILTERS, StatusChip,
  buildTaskPayload, display, formFromTask, formatDate, formatSize, newIdempotencyKey, operationLabel,
} from "./shared.js";

const POLL_MS = 4000;
// 最多自动刷新 150 次（约 10 分钟），之后需手动刷新，避免页面挂着无限轮询。
const POLL_MAX_TICKS = 150;

function emptyForm() {
  return {
    operation: "merge_append",
    sourceRoot: "",
    sourcePaths: "",
    targetRoot: "",
    targetPath: "",
    baselineRoot: "",
    baselinePath: "",
    outputRoot: "",
    outputPath: "",
    idempotencyKey: newIdempotencyKey(),
  };
}

/** POST 且保留 422 的 fields 明细（host api() 不透出 fields）。 */
async function postJson(url, body, signal) {
  let response;
  try {
    response = await fetch(url, {
      method: "POST",
      signal,
      cache: "no-store",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (err) {
    if (err && err.name === "AbortError") throw err;
    throw new ApiError("无法连接本地服务，请确认 VSE Toolbox 仍在运行");
  }
  let payload = null;
  try {
    payload = await response.json();
  } catch (_) {
    payload = null;
  }
  if (payload && payload.ok === true) return payload.data;
  const error = (payload && payload.error) || {};
  const apiError = new ApiError(error.message || `请求失败（HTTP ${response.status}）`, {
    status: response.status,
    type: error.type || "http",
    code: error.code || null,
  });
  apiError.fields = error.fields || null;
  throw apiError;
}

const isAbort = (error) => error && error.name === "AbortError";

// ── 子组件 ───────────────────────────────────────────────────────────

function WorkerControls({ worker, busy, onStart, onStop, onRefresh, onExamples, refreshing }) {
  let chip;
  if (worker.unavailable) chip = html`<${StatusChip} status="unknown" text=${worker.unavailable} />`;
  else {
    const text = worker.pid ? `${worker.label} · PID ${worker.pid}` : worker.label;
    chip = html`<${StatusChip} status=${worker.state} text=${text} />`;
  }
  const state = worker.state;
  return html`<div class="xt-worker" aria-label="文件处理服务控制">
    <span class="xt-worker-label">处理服务</span>
    ${chip}
    <button type="button" class="vk-btn" disabled=${busy || !!worker.unavailable || ["running", "stopping"].includes(state)} onClick=${onStart}>启动</button>
    <button type="button" class="vk-btn" disabled=${busy || !!worker.unavailable || state !== "running"} onClick=${onStop}>停止</button>
    <button type="button" class="vk-btn" disabled=${refreshing} onClick=${onRefresh}>刷新</button>
    <button type="button" class="vk-btn" onClick=${onExamples}>查看操作示例</button>
  </div>`;
}

function RootSelect({ value, roots, onChange }) {
  return html`<select value=${value} disabled=${roots.length === 0} onChange=${(event) => onChange(event.currentTarget.value)}>
    ${roots.length === 0 && html`<option value="">（无可用位置）</option>`}
    ${roots.map((root) => html`<option key=${root} value=${root}>${root}</option>`)}
  </select>`;
}

function CreateForm({ form, setForm, roots, rootsError, creating, onSubmit }) {
  const set = (key) => (value) => setForm((prev) => ({ ...prev, [key]: value }));
  const input = (key) => (event) => set(key)(event.currentTarget.value);
  const op = form.operation;
  const showSources = op !== "diff_against_baseline";
  const showTarget = op !== "merge_append";
  return html`<form class="xt-card xt-create" autocomplete="off" onSubmit=${onSubmit}>
    <div class="xt-card-head">
      <div>
        <p class="xt-eyebrow">新建</p>
        <h4>创建 Excel 处理任务</h4>
      </div>
      <button type="submit" class="vk-btn is-primary" disabled=${creating || roots.length === 0}>${creating ? "正在创建…" : "开始处理"}</button>
    </div>
    ${roots.length === 0 && html`<p class="xt-hint">${rootsError || "正在加载可用的文件位置…"}</p>`}
    <div class="xt-create-grid">
      <label class="xt-field">
        <span>处理方式</span>
        <select value=${op} onChange=${input("operation")}>
          ${OPERATIONS.map((item) => html`<option key=${item.value} value=${item.value}>${item.label}</option>`)}
        </select>
      </label>
      ${showSources && html`<label class="xt-field">
        <span>文件所在位置</span>
        <${RootSelect} value=${form.sourceRoot} roots=${roots} onChange=${set("sourceRoot")} />
      </label>`}
      ${showSources && html`<label class="xt-field is-wide">
        <span>要处理的文件（每行一个）</span>
        <textarea rows="3" placeholder=${"source-a.xlsx\nsource-b.xlsx"} value=${form.sourcePaths} onInput=${input("sourcePaths")}></textarea>
      </label>`}
      ${showTarget && html`<label class="xt-field">
        <span>文件所在位置</span>
        <${RootSelect} value=${form.targetRoot} roots=${roots} onChange=${set("targetRoot")} />
      </label>`}
      ${showTarget && html`<label class="xt-field">
        <span>目标模板</span>
        <input type="text" placeholder="target.xlsx" required value=${form.targetPath} onInput=${input("targetPath")} />
      </label>`}
      <label class="xt-field">
        <span>文件所在位置</span>
        <${RootSelect} value=${form.baselineRoot} roots=${roots} onChange=${set("baselineRoot")} />
      </label>
      <label class="xt-field">
        <span>对比基准${op === "diff_against_baseline" ? "" : "（可选）"}</span>
        <input type="text" placeholder="baseline.xlsx" required=${op === "diff_against_baseline"} value=${form.baselinePath} onInput=${input("baselinePath")} />
      </label>
      <label class="xt-field">
        <span>保存位置</span>
        <${RootSelect} value=${form.outputRoot} roots=${roots} onChange=${set("outputRoot")} />
      </label>
      <label class="xt-field">
        <span>输出文件名</span>
        <input type="text" placeholder="output/result.xlsx" required value=${form.outputPath} onInput=${input("outputPath")} />
      </label>
    </div>
    <details class="xt-advanced">
      <summary>高级信息</summary>
      <label class="xt-field is-wide">
        <span>防重标识</span>
        <span class="xt-inline">
          <input type="text" readonly value=${form.idempotencyKey} />
          <button type="button" class="vk-btn" onClick=${() => set("idempotencyKey")(newIdempotencyKey())}>重新生成</button>
        </span>
      </label>
    </details>
  </form>`;
}

function TaskList({ tasks, state, selectedId, onSelect, filter, onFilter }) {
  let body;
  if (state.notConfigured) body = html`<div class="vk-state is-empty">未配置 approved roots，Excel 文件处理服务不可用</div>`;
  else if (state.loading && tasks.length === 0) body = html`<${StateBlock} loading=${true} />`;
  else if (state.error && tasks.length === 0) body = html`<div class="vk-state is-empty">获取处理记录失败，请点击上方【刷新】重试</div>`;
  else if (tasks.length === 0) body = html`<div class="vk-state is-empty">暂无处理记录。您可在上方选择处理方式并点击【开始处理】创建任务。</div>`;
  else {
    body = html`<div class="xt-task-list" role="listbox" aria-label="处理记录">
      ${tasks.map((task) => html`<button
        key=${task.id}
        type="button"
        role="option"
        aria-selected=${task.id === selectedId ? "true" : "false"}
        class=${`xt-task-item${task.id === selectedId ? " is-active" : ""}`}
        onClick=${() => onSelect(task.id)}
      >
        <span class="xt-task-item-head">
          <span class="xt-task-item-title">#${task.id} ${operationLabel(task.operation)}</span>
          <${StatusChip} status=${task.status} />
        </span>
        <span class="xt-task-item-meta">
          <span>尝试 ${task.attemptCount}/${task.maxAttempts}</span>
          <span>${formatDate(task.updatedAt)}</span>
        </span>
      </button>`)}
    </div>`;
  }
  return html`<aside class="xt-card xt-list-pane" aria-label="Excel 处理记录">
    <div class="xt-card-head">
      <h4>处理记录${tasks.length > 0 ? html` <span class="xt-count">${tasks.length}</span>` : null}</h4>
      <label class="xt-field is-inline">
        <span>状态</span>
        <select value=${filter} onChange=${(event) => onFilter(event.currentTarget.value)}>
          ${STATUS_FILTERS.map((item) => html`<option key=${item.value} value=${item.value}>${item.label}</option>`)}
        </select>
      </label>
    </div>
    ${body}
  </aside>`;
}

const RUN_COLUMNS = [
  { key: "id", title: "Run", format: (value) => `#${value}` },
  { key: "attempt", title: "尝试" },
  { key: "runState", title: "状态", format: (value) => html`<${StatusChip} status=${value} />` },
  { key: "startedAt", title: "开始时间", format: (value, row) => formatDate(value || row.createdAt) },
  { key: "finishedAt", title: "完成时间", format: (value) => formatDate(value) },
  { key: "errorMessage", title: "错误", sortable: false, format: (value, row) => display(value || row.errorType || "-") },
];

function AuditBox({ audit }) {
  if (audit.loading) return html`<div class="xt-audit is-empty">加载下载记录中…</div>`;
  if (audit.error) return html`<div class="xt-audit is-empty is-error">${display(audit.error.message)}</div>`;
  const rows = audit.rows || [];
  if (rows.length === 0) return html`<div class="xt-audit is-empty">暂无下载记录</div>`;
  return html`<div class="xt-audit">
    <table class="vk-table">
      <thead><tr><th>结果</th><th>原因</th><th>传输大小</th><th>时间</th></tr></thead>
      <tbody>${rows.map((item, index) => html`<tr key=${item.id ?? index}>
        <td><${StatusChip} status=${item.result === "succeeded" ? "succeeded" : "failed"} /></td>
        <td>${display(item.reasonCode)}</td>
        <td>${formatSize(item.servedSizeBytes)}</td>
        <td>${formatDate(item.createdAt)}</td>
      </tr>`)}</tbody>
    </table>
  </div>`;
}

function ArtifactTable({ artifacts, audits, onToggleAudit }) {
  if (artifacts.length === 0) return html`<div class="vk-state is-empty">暂无输出文件</div>`;
  return html`<div class="vk-table-wrap">
    <table class="vk-table xt-artifact-table">
      <thead><tr><th>名称</th><th>大小</th><th>SHA-256</th><th>生成时间</th><th>操作</th></tr></thead>
      <tbody>
        ${artifacts.map((artifact) => {
          const audit = audits[artifact.id];
          return [
            html`<tr key=${`a-${artifact.id}`}>
              <td>${display(artifact.displayName)}</td>
              <td>${formatSize(artifact.sizeBytes)}</td>
              <td><code class="xt-hash" title=${artifact.sha256}>${display(artifact.sha256)}</code></td>
              <td>${formatDate(artifact.createdAt)}</td>
              <td class="xt-actions">
                <a class="vk-btn is-primary" href=${`/api/excel-artifacts/${encodeURIComponent(artifact.id)}/download`} download=${artifact.displayName || ""}>下载</a>
                <button type="button" class="vk-btn" onClick=${() => onToggleAudit(artifact.id)}>${audit && audit.open ? "收起" : "下载记录"}</button>
              </td>
            </tr>`,
            audit && audit.open
              ? html`<tr key=${`au-${artifact.id}`} class="xt-audit-row"><td colspan="5"><${AuditBox} audit=${audit} /></td></tr>`
              : null,
          ];
        })}
      </tbody>
    </table>
  </div>`;
}

function TaskDetail({ detail, audits, onToggleAudit, onCancel, onCopy, cancelling, canCopy }) {
  if (detail.id === null) {
    return html`<article class="xt-card"><div class="vk-state is-empty">请选择处理记录</div></article>`;
  }
  if (!detail.task) {
    return html`<article class="xt-card">${detail.error
      ? html`<div class="vk-state is-empty">处理详情加载失败</div>`
      : html`<${StateBlock} loading=${true} />`}</article>`;
  }
  const { task, runs, artifacts } = detail;
  const active = ACTIVE_TASK_STATES.includes(task.status);
  const files = Array.isArray(task.files) ? task.files : [];
  const cells = [
    ["创建时间", formatDate(task.createdAt)],
    ["开始时间", formatDate(task.startedAt)],
    ["完成时间", formatDate(task.finishedAt)],
    ["尝试次数", `${task.attemptCount}/${task.maxAttempts}`],
    ["文件引用", String(files.length)],
    ["错误", task.errorMessage || task.errorType || "-"],
  ];
  return html`<div class="xt-detail-stack">
    <article class="xt-card" aria-label="处理详情">
      <div class="xt-card-head">
        <div>
          <p class="xt-eyebrow">TASK #${task.id}</p>
          <h4>${operationLabel(task.operation)} <code class="xt-op-code">${display(task.operation)}</code></h4>
        </div>
        <span class="vk-page-actions">
          <${StatusChip} status=${task.status} />
          ${active && html`<button type="button" class="vk-btn" disabled=${cancelling} onClick=${() => onCancel(task)}>${cancelling ? "正在取消…" : "取消任务"}</button>`}
          ${!active && html`<button type="button" class="vk-btn" disabled=${!canCopy} title="Excel 任务不支持直接重试，可复制参数重新提交" onClick=${() => onCopy(task)}>复制为新任务</button>`}
        </span>
      </div>
      <div class="xt-detail-grid">
        ${cells.map(([label, value]) => html`<div key=${label} class="xt-detail-cell"><span>${label}</span><strong>${display(value)}</strong></div>`)}
      </div>
      ${files.length > 0 && html`<details class="xt-advanced">
        <summary>文件引用（${files.length}）</summary>
        <ul class="xt-file-refs">
          ${files.map((ref, index) => html`<li key=${index}><span class="xt-role">${ref.role}</span> <code>${display(ref.rootId)}</code> / ${display(ref.relativePath)}</li>`)}
        </ul>
      </details>`}
    </article>
    <section class="xt-card" aria-label="Excel 处理历史">
      <div class="xt-card-head"><h4>处理历史</h4></div>
      <${DataTable} columns=${RUN_COLUMNS} rows=${runs} emptyText="暂无运行记录" pageSize=${20} />
    </section>
    <section class="xt-card" aria-label="Excel 输出文件">
      <div class="xt-card-head"><h4>输出文件</h4></div>
      <${ArtifactTable} artifacts=${artifacts} audits=${audits} onToggleAudit=${onToggleAudit} />
    </section>
  </div>`;
}

const RETENTION_COLUMNS = [
  { key: "id", title: "文件编号", format: (value) => `#${value}` },
  { key: "taskId", title: "处理记录", format: (value) => `#${value}` },
  { key: "displayName", title: "名称", format: (value) => display(value) },
  { key: "sizeBytes", title: "大小", format: (value) => formatSize(value) },
  { key: "createdAt", title: "生成时间", format: (value) => formatDate(value) },
];

function RetentionPanel({ signal }) {
  const [days, setDays] = useState("90");
  const [state, setState] = useState({ loading: false, error: null, data: null });

  const load = async () => {
    const value = Number(days);
    if (!Number.isInteger(value) || value < 1 || value > 3650) {
      setState({ loading: false, error: new Error("保留天数必须是 1 到 3650 的整数"), data: null });
      return;
    }
    setState({ loading: true, error: null, data: null });
    try {
      const data = await api("/api/excel-artifacts/retention-plan", { query: { retentionDays: value, limit: 500 }, signal });
      setState({ loading: false, error: null, data: data || {} });
    } catch (error) {
      if (!isAbort(error)) setState({ loading: false, error, data: null });
    }
  };

  let body;
  if (state.error) body = html`<${ErrorCard} error=${state.error} />`;
  else if (state.loading) body = html`<div class="vk-state is-loading">正在生成文件清理建议…</div>`;
  else if (!state.data) body = html`<div class="vk-state is-empty">尚未生成清理建议</div>`;
  else {
    const artifacts = Array.isArray(state.data.artifacts) ? state.data.artifacts : [];
    body = artifacts.length === 0
      ? html`<div class="vk-state is-empty">截止 ${formatDate(state.data.cutoffAt)} 没有建议清理的文件</div>`
      : html`<p class="xt-hint">${artifacts.length} 个文件 · 截止 ${formatDate(state.data.cutoffAt)}${state.data.truncated ? " · 仅显示部分结果" : ""}</p>
        <${DataTable} columns=${RETENTION_COLUMNS} rows=${artifacts} pageSize=${20} />`;
  }
  return html`<section class="xt-card" aria-label="Excel 文件清理建议">
    <div class="xt-card-head">
      <div>
        <h4>文件清理建议</h4>
        <p class="vk-muted">只读预览：列出超过保留天数的输出文件，不会删除任何文件。</p>
      </div>
      <span class="xt-inline">
        <label class="xt-field is-inline">
          <span>保留天数</span>
          <input type="number" min="1" max="3650" value=${days} onInput=${(event) => setDays(event.currentTarget.value)} />
        </label>
        <button type="button" class="vk-btn" disabled=${state.loading} onClick=${load}>查看建议</button>
      </span>
    </div>
    ${body}
  </section>`;
}

// ── 页面 ─────────────────────────────────────────────────────────────

const WORKER_LABELS = { running: "运行中", stopped: "已停止", stopping: "停止中", failed: "失败" };

export default function ExcelWorkspace({ plugin }) {
  useStylesheet(`/plugins/${plugin.id}/static/excel-tasks.css`);

  const lifetime = useRef(null);
  if (lifetime.current === null) lifetime.current = new AbortController();
  const signal = lifetime.current.signal;
  useEffect(() => () => lifetime.current.abort(), []);

  const [error, setError] = useState(null);
  const [notice, setNotice] = useState("");
  const [roots, setRoots] = useState([]);
  const [rootsError, setRootsError] = useState("");
  const [worker, setWorker] = useState({ unavailable: "加载中" });
  const [workerBusy, setWorkerBusy] = useState(false);
  const [filter, setFilter] = useState("");
  const [tasks, setTasks] = useState([]);
  const [listState, setListState] = useState({ loading: true, error: null, notConfigured: false });
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState({ id: null, task: null, runs: [], artifacts: [], error: null });
  const [audits, setAudits] = useState({});
  const [form, setForm] = useState(emptyForm);
  const [creating, setCreating] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [examplesOpen, setExamplesOpen] = useState(false);
  const [pollEpoch, setPollEpoch] = useState(0);
  const [pollExpired, setPollExpired] = useState(false);

  const listSeq = useRef(0);
  const detailSeq = useRef(0);
  const selectedRef = useRef(null);
  selectedRef.current = selectedId;
  const filterRef = useRef(filter);
  filterRef.current = filter;
  const detailRef = useRef(detail);
  detailRef.current = detail;

  const showError = useCallback((err) => {
    if (!isAbort(err)) setError(err);
  }, []);

  const loadRoots = useCallback(async () => {
    try {
      const data = await api("/api/excel-roots", { signal });
      const ids = Array.isArray(data) ? data.map((item) => item && item.rootId).filter((item) => typeof item === "string" && item) : [];
      setRoots(ids);
      setRootsError(ids.length === 0 ? "未配置可用的文件位置（approved roots），暂不能创建任务。" : "");
      setForm((prev) => {
        const pick = (value) => (ids.includes(value) ? value : ids[0] || "");
        return {
          ...prev,
          sourceRoot: pick(prev.sourceRoot),
          targetRoot: pick(prev.targetRoot),
          baselineRoot: pick(prev.baselineRoot),
          outputRoot: pick(prev.outputRoot),
        };
      });
    } catch (err) {
      if (isAbort(err)) return;
      setRoots([]);
      setRootsError(err.status === 503 ? "未配置可用的文件位置（approved roots），暂不能创建任务。" : `文件位置加载失败：${display(err.message)}`);
    }
  }, [signal]);

  const loadWorker = useCallback(async () => {
    try {
      const data = (await api("/api/excel-worker/status", { signal })) || {};
      const state = data.state || "unknown";
      setWorker({
        state,
        label: WORKER_LABELS[state] || display(state),
        pid: data.pid || null,
        error: data.error || null,
        exitCode: data.exitCode ?? null,
      });
    } catch (err) {
      if (isAbort(err)) return;
      setWorker({ unavailable: err.status === 503 ? "未配置" : "状态未知" });
    }
  }, [signal]);

  const loadDetail = useCallback(async (taskId, { quiet = false } = {}) => {
    const seq = ++detailSeq.current;
    if (taskId === null) {
      setDetail({ id: null, task: null, runs: [], artifacts: [], error: null });
      return;
    }
    if (!quiet) setDetail({ id: taskId, task: null, runs: [], artifacts: [], error: null });
    const base = `/api/excel-tasks/${encodeURIComponent(taskId)}`;
    try {
      const [task, runs, artifacts] = await Promise.all([
        api(base, { signal }),
        api(`${base}/runs`, { signal }),
        api(`${base}/artifacts`, { signal }),
      ]);
      if (seq !== detailSeq.current) return;
      setDetail({
        id: taskId,
        task: task || {},
        runs: Array.isArray(runs) ? runs : [],
        artifacts: Array.isArray(artifacts) ? artifacts : [],
        error: null,
      });
    } catch (err) {
      if (isAbort(err) || seq !== detailSeq.current) return;
      setDetail((prev) => (quiet && prev.id === taskId && prev.task ? prev : { id: taskId, task: null, runs: [], artifacts: [], error: err }));
      showError(err);
    }
  }, [signal, showError]);

  const loadTasks = useCallback(async ({ keepSelection = true, quiet = false } = {}) => {
    const seq = ++listSeq.current;
    if (!quiet) setListState((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const data = await api("/api/excel-tasks", { query: { status: filterRef.current, limit: 200 }, signal });
      if (seq !== listSeq.current) return;
      const list = Array.isArray(data) ? data : [];
      setTasks(list);
      setListState({ loading: false, error: null, notConfigured: false });
      const current = selectedRef.current;
      const next = keepSelection && list.some((task) => task.id === current) ? current : (list[0] ? list[0].id : null);
      if (next !== current || detailRef.current.id !== next) {
        selectedRef.current = next;
        setSelectedId(next);
        setAudits({});
        loadDetail(next);
      } else if (next !== null) {
        const row = list.find((task) => task.id === next);
        const shown = detailRef.current.task;
        // 静默刷新只在选中任务仍在处理中（或状态已变化）时重新拉详情，减少无谓请求。
        const changed = !shown || (row && (row.status !== shown.status || row.updatedAt !== shown.updatedAt));
        if (!quiet || changed) loadDetail(next, { quiet: true });
      }
    } catch (err) {
      if (isAbort(err) || seq !== listSeq.current) return;
      if (err.status === 503 && err.type === "NotConfigured") {
        setTasks([]);
        selectedRef.current = null;
        setSelectedId(null);
        loadDetail(null);
        setListState({ loading: false, error: null, notConfigured: true });
        setNotice("Excel 文件处理服务未配置");
        return;
      }
      setListState((prev) => ({ ...prev, loading: false, error: err }));
      if (!quiet) showError(err);
    }
  }, [signal, loadDetail, showError]);

  const refreshAll = useCallback(() => {
    setError(null);
    setPollExpired(false);
    setPollEpoch((value) => value + 1);
    return Promise.all([loadRoots(), loadWorker(), loadTasks({ keepSelection: true })]);
  }, [loadRoots, loadWorker, loadTasks]);

  // 首次进入：与旧页 loadExcelTaskWorkspace 相同，三路并行加载。
  useEffect(() => {
    refreshAll();
  }, []);

  // 状态筛选变化：不保留旧选择（同旧页 loadExcelTasks(false)）。
  const firstFilter = useRef(true);
  useEffect(() => {
    if (firstFilter.current) {
      firstFilter.current = false;
      return;
    }
    loadTasks({ keepSelection: false });
  }, [filter]);

  // 有界轮询：仅在 worker 运行或存在进行中的任务时每 4 秒刷新；页面隐藏时跳过；卸载即停。
  const hasActive = tasks.some((task) => ACTIVE_TASK_STATES.includes(task.status))
    || ["running", "stopping"].includes(worker.state);
  const tickRef = useRef(null);
  tickRef.current = () => {
    loadWorker();
    loadTasks({ keepSelection: true, quiet: true });
  };
  useEffect(() => {
    if (!hasActive || pollExpired) return undefined;
    let ticks = 0;
    const timer = setInterval(() => {
      if (typeof document !== "undefined" && document.hidden) return;
      ticks += 1;
      if (ticks > POLL_MAX_TICKS) {
        clearInterval(timer);
        setPollExpired(true);
        return;
      }
      tickRef.current();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [hasActive, pollExpired, pollEpoch]);

  const selectTask = (taskId) => {
    if (taskId === selectedId) return;
    selectedRef.current = taskId;
    setSelectedId(taskId);
    setAudits({});
    loadDetail(taskId);
  };

  const mutateWorker = async (action) => {
    if (workerBusy) return;
    setWorkerBusy(true);
    setError(null);
    setNotice(action === "start" ? "正在启动处理服务…" : "正在停止处理服务…");
    try {
      await postJson(`/api/excel-worker/${action}`, undefined, signal);
      setNotice(action === "start" ? "处理服务已启动" : "处理服务已停止");
    } catch (err) {
      if (isAbort(err)) return;
      setNotice("");
      showError(err);
    } finally {
      if (!signal.aborted) {
        setWorkerBusy(false);
        setPollExpired(false);
        setPollEpoch((value) => value + 1);
        await loadWorker();
        if (action === "stop") await loadTasks({ keepSelection: true });
      }
    }
  };

  const submitCreate = async (event) => {
    event.preventDefault();
    if (creating) return;
    setError(null);
    let payload;
    try {
      payload = buildTaskPayload(form, roots);
    } catch (err) {
      setError(err);
      return;
    }
    setCreating(true);
    setNotice("正在创建处理记录…");
    try {
      const data = await postJson("/api/excel-tasks", payload, signal);
      setForm((prev) => ({ ...prev, idempotencyKey: newIdempotencyKey() }));
      setNotice(`处理记录 #${data.id} 已创建`);
      selectedRef.current = data.id;
      setSelectedId(data.id);
      setAudits({});
      setPollExpired(false);
      setPollEpoch((value) => value + 1);
      await loadTasks({ keepSelection: true });
    } catch (err) {
      if (isAbort(err)) return;
      setNotice("");
      showError(err);
    } finally {
      if (!signal.aborted) setCreating(false);
    }
  };

  const cancelTask = async (task) => {
    if (typeof window !== "undefined" && typeof window.confirm === "function"
      && !window.confirm(`确定取消处理记录 #${task.id}？`)) return;
    setCancelling(true);
    setError(null);
    try {
      await postJson(`/api/tasks/excel_${encodeURIComponent(task.id)}/cancel`, undefined, signal);
      setNotice(`处理记录 #${task.id} 已取消`);
    } catch (err) {
      if (isAbort(err)) return;
      showError(err);
    } finally {
      if (!signal.aborted) {
        setCancelling(false);
        await loadTasks({ keepSelection: true });
      }
    }
  };

  const copyTask = (task) => {
    setForm(formFromTask(task, roots[0] || ""));
    setNotice(`已把处理记录 #${task.id} 的参数填入新建表单，确认后点击【开始处理】`);
    const target = typeof document !== "undefined" ? document.querySelector(".xt-create") : null;
    if (target && target.scrollIntoView) target.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const toggleAudit = async (artifactId) => {
    const current = audits[artifactId];
    if (current && current.open) {
      setAudits((prev) => ({ ...prev, [artifactId]: { ...prev[artifactId], open: false } }));
      return;
    }
    setAudits((prev) => ({ ...prev, [artifactId]: { open: true, loading: true, error: null, rows: [] } }));
    let next;
    try {
      const rows = await api(`/api/excel-artifacts/${encodeURIComponent(artifactId)}/download-audit`, { query: { limit: 50 }, signal });
      next = { loading: false, error: null, rows: Array.isArray(rows) ? rows : [] };
    } catch (err) {
      if (isAbort(err)) return;
      next = { loading: false, error: err, rows: [] };
    }
    setAudits((prev) => (prev[artifactId] ? { ...prev, [artifactId]: { ...prev[artifactId], ...next } } : prev));
  };

  const exited = worker.exitCode !== null && worker.exitCode !== undefined && worker.exitCode !== 0 && worker.state !== "running";
  const workerHint = !worker.unavailable && (worker.error || exited)
    ? `处理服务${exited ? `退出码 ${worker.exitCode}` : ""}${worker.error ? `：${display(worker.error)}` : ""}`
    : "";

  return html`<div class="vk-page xt-page">
    <header class="vk-page-header xt-header">
      <p class="vk-muted xt-intro">合并、套模板或与基准比对受控目录中的 Excel 文件；处理由本机处理服务（Excel COM）执行。</p>
      <${WorkerControls}
        worker=${worker}
        busy=${workerBusy}
        refreshing=${listState.loading}
        onStart=${() => mutateWorker("start")}
        onStop=${() => mutateWorker("stop")}
        onRefresh=${refreshAll}
        onExamples=${() => setExamplesOpen(true)}
      />
    </header>

    <${ErrorCard} error=${error} onDismiss=${() => setError(null)} />
    <div class="xt-status" aria-live="polite">
      ${notice && html`<span>${notice}</span>`}
      ${workerHint && html`<span class="xt-warn">${workerHint}</span>`}
      ${hasActive && !pollExpired && html`<span class="xt-poll">● 自动刷新中</span>`}
      ${hasActive && pollExpired && html`<span class="xt-warn">自动刷新已暂停，点击【刷新】继续</span>`}
    </div>

    <${CreateForm} form=${form} setForm=${setForm} roots=${roots} rootsError=${rootsError} creating=${creating} onSubmit=${submitCreate} />

    <div class="xt-layout">
      <${TaskList}
        tasks=${tasks}
        state=${listState}
        selectedId=${selectedId}
        onSelect=${selectTask}
        filter=${filter}
        onFilter=${setFilter}
      />
      <div class="xt-detail-pane">
        <${TaskDetail}
          detail=${detail}
          audits=${audits}
          onToggleAudit=${toggleAudit}
          onCancel=${cancelTask}
          onCopy=${copyTask}
          cancelling=${cancelling}
          canCopy=${roots.length > 0}
        />
        <${RetentionPanel} signal=${signal} />
      </div>
    </div>

    <${ExamplesDialog} open=${examplesOpen} onClose=${() => setExamplesOpen(false)} />
  </div>`;
}
