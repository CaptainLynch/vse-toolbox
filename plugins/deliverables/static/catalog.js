// 交付物工作台 module page (port of the legacy #deliverables workbench).
// Catalog + filters on the left, item detail with the TDC query / crawl-all /
// export form on the right, result grid, structured errors (in-place login on
// auth errors), background task polling and the in-memory 最近运行 list.
// Calls the existing /api/deliverables/catalog, /api/tdc/* and /api/tasks/*
// endpoints; request headers live only in component state.
import { html, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { useStylesheet } from "/static/host/kit.js";
import { DataGrid } from "./grid.js";
import {
  AVAILABILITY_LABELS,
  CAR_TYPE_PROJECTS_ENDPOINT,
  CATALOG_ENDPOINT,
  LOCAL_ONLY_MESSAGE,
  OPERATION_FIELDS,
  OPERATION_LABELS,
  PAGE_HASH,
  PREVIEW_SOURCES,
  STATUS_LABELS,
  STATUS_TONE_CLASS,
  TDC_ENDPOINTS,
  addRecentRun,
  buildPayload,
  categoryName,
  categoryOptions,
  clearPayloadSecrets,
  defaultFormValues,
  formatApiErrorMessage,
  formatFilterSummary,
  isArasTarget,
  isAuthError,
  isExecutableTdc,
  isLocalGuardError,
  isTaskAccepted,
  itemHash,
  itemMetaText,
  messageError,
  parseContentDispositionFilename,
  parseItemParam,
  pickInitialItem,
  previewContextText,
  recentRunTitle,
  redactSensitiveText,
  resultMetaText,
  statusOptions,
  systemQueryHash,
  taskPercent,
  taskProgressText,
  taskUrl,
  toApiError,
  unmappedWarning,
  validateForm,
  visibleDeliverables,
} from "./lib.js";

const TASK_POLL_INTERVAL_MS = 2000;
const TASK_POLL_TIMEOUT_MS = 30 * 60 * 1000;

// 「页面内存」：最近运行在本次页面加载内跨挂载保留（与旧页面全局变量同口径），不落盘。
let recentRunsMemory = [];

// ── HTTP ───────────────────────────────────────────────────────────────

async function postJson(url, payload, signal) {
  let response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
      signal,
    });
  } catch (err) {
    if (err && err.name === "AbortError") throw err;
    throw toApiError(null, 0);
  }
  const body = await response.json().catch(() => null);
  return { status: response.status, ok: response.ok, body };
}

async function getJson(url, signal) {
  let response;
  try {
    response = await fetch(url, { headers: { Accept: "application/json" }, cache: "no-store", signal });
  } catch (err) {
    if (err && err.name === "AbortError") throw err;
    throw toApiError(null, 0);
  }
  const body = await response.json().catch(() => null);
  if (!response.ok || !body || body.ok !== true) throw toApiError(body, response.status);
  return body.data;
}

function saveBlob(blob, fileName) {
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

function kickTaskCenter() {
  document.dispatchEvent(new CustomEvent("vse:task-center-kick"));
}

const sleep = (ms, signal) => new Promise((resolve) => {
  const timer = setTimeout(resolve, ms);
  if (signal) signal.addEventListener("abort", () => { clearTimeout(timer); resolve(); }, { once: true });
});

function asError(err) {
  if (err && typeof err.type === "string" && "status" in err) return err;
  return messageError(String((err && err.message) || err || "未知错误"));
}

// ── 小组件 ─────────────────────────────────────────────────────────────

function ErrorCard({ card }) {
  return html`<div class="structured-error-card" role="alert" aria-live="polite">
    <div class="structured-error-head">
      <span class="error-badge-icon" aria-hidden="true">!</span>
      <div class="error-head-text">
        <div class="error-summary">${card.summary}</div>
        <div class="error-impact">${card.impact}</div>
      </div>
    </div>
    ${card.actions && card.actions.length > 0 && html`<div class="error-actions">
      ${card.actions.map((act) => html`<button key=${act.label} type="button"
        class=${`error-action-btn ${act.primary ? "is-primary" : ""}`} onClick=${act.action}>${act.label}</button>`)}
    </div>`}
    ${card.technical && html`<details class="error-technical-details">
      <summary>技术详情（维护与排查问题使用）</summary>
      <div class="error-technical-content">${redactSensitiveText(card.technical)}</div>
    </details>`}
  </div>`;
}

function EmptyNotice({ title, desc }) {
  return html`<div class="empty-result-card">
    <div class="empty-result-icon" aria-hidden="true">🔍</div>
    <div class="empty-result-title">${title}</div>
    <div class="empty-result-desc">${desc}</div>
  </div>`;
}

function FieldError({ message }) {
  return message ? html`<small class="dlv-field-error" role="alert">${message}</small>` : null;
}

function TaskStrip({ task, onCancel }) {
  if (!task) return null;
  const percent = taskPercent(task);
  const statusText = {
    queued: "排队中", leased: "准备中", running: "运行中", succeeded: "已完成",
    failed: "失败", cancelled: "已取消", interrupted: "已中断", timeout: "超时",
  }[task.status] || task.status || "排队中";
  return html`<div class="dlv-task" role="status" aria-live="polite">
    <div class="dlv-task-head">
      <strong>后台${task.kind === "export" ? "导出" : "全量抓取"}任务</strong>
      <span class="dlv-task-id">${task.taskId}</span>
      <span class=${`dlv-task-status is-${task.status || "queued"}`}>${statusText}</span>
      ${task.active && html`<button type="button" class="secondary-btn" disabled=${task.cancelling} onClick=${onCancel}>
        ${task.cancelling ? "取消中..." : "取消任务"}</button>`}
      ${task.downloadUrl && html`<a class="secondary-btn dlv-task-download" href=${task.downloadUrl} download>下载结果文件</a>`}
    </div>
    ${task.active && html`<div class="dlv-progress" aria-label="任务进度">
      <div class="dlv-progress-fill" style=${{ width: `${percent ?? 5}%` }}></div>
    </div>`}
    <div class="dlv-task-detail">${taskProgressText(task) || "进度与结果也可在右上角「任务」中心查看"}</div>
  </div>`;
}

function RecentRuns({ runs }) {
  return html`<section class="recent-runs" aria-label="最近运行">
    <div class="recent-head">
      <p class="eyebrow">页面内存</p>
      <h4>最近运行</h4>
    </div>
    ${runs.length === 0
      ? html`<div class="recent-list is-empty">暂无运行记录</div>`
      : html`<div class="recent-list">${runs.map((run, i) => html`<div key=${i} class="recent-item">
          <span class="recent-title">${recentRunTitle(run)}</span>
          <span class=${`recent-status ${run.status === "success" ? "is-success" : "is-failed"}`}>${run.status === "success" ? "成功" : "失败"}</span>
          <span class="recent-summary">${run.summary}</span>
          <span class="recent-time">${run.time}</span>
        </div>`)}</div>`}
  </section>`;
}

function CarTypeProjects({ state, selectedId, onLoad, onSelect }) {
  const options = state.options || [];
  let placeholder = "请选择车型项目（需先加载）";
  if (state.status === "error") placeholder = `加载失败：${state.message}`;
  else if (state.status === "stale") placeholder = "连接配置已变更，请重新加载车型项目";
  else if (state.status === "ok") placeholder = options.length ? `请选择车型项目（共 ${options.length} 项）` : "未找到可用车型项目";
  const loading = state.status === "loading";
  return html`<div class="car-type-project-group">
    <select class="car-type-project-options" aria-label="车型项目候选" disabled=${loading}
      value=${selectedId || ""} onChange=${(event) => onSelect(event.currentTarget.value)}>
      <option value="">${placeholder}</option>
      ${options.map((p) => html`<option key=${p.id} value=${p.id}>${p.label || p.projectNo || p.projectName || p.id}</option>`)}
    </select>
    <button type="button" class="segment car-type-load-btn" disabled=${loading} onClick=${onLoad}>
      ${loading ? "加载中..." : "重新加载车型项目"}
    </button>
  </div>`;
}

// ── 条目详情 + TDC 操作表单 ─────────────────────────────────────────────

function DeliverableDetail({ item, categories, runLock, onRecord }) {
  const executable = isExecutableTdc(item);
  const config = TDC_ENDPOINTS[item.id] || null;
  const [values, setValues] = useState(() => defaultFormValues(item));
  const [fieldErrors, setFieldErrors] = useState({});
  const [carTypes, setCarTypes] = useState({ status: "idle", options: [] });
  const [running, setRunning] = useState(null);
  const [status, setStatus] = useState({ text: "", loading: false });
  const [errorState, setErrorState] = useState(null);
  const [panelShown, setPanelShown] = useState(false);
  const [resultKind, setResultKind] = useState("就绪");
  const [output, setOutput] = useState(null);
  const [contextNote, setContextNote] = useState("");
  const [task, setTask] = useState(null);

  const mounted = useRef(true);
  const seq = useRef(0);
  const latestRendered = useRef(0);
  const preview = useRef(null);
  const carTypeSeq = useRef(0);
  const lastOperation = useRef("query");
  const valuesRef = useRef(values);
  valuesRef.current = values;

  useEffect(() => () => { mounted.current = false; }, []);

  const operation = values.operation_mode || "query";
  const label = (op) => OPERATION_LABELS[op] || op;
  const record = (op, runStatus, summary) => onRecord({
    id: item.id, name: item.name, operation: op, status: runStatus, summary, time: new Date().toLocaleTimeString(),
  });

  const setValue = (name, value) => {
    setValues((prev) => {
      const next = { ...prev, [name]: value };
      // 车型项目手输即清除候选 id（旧页面同口径）
      if (name === "car_type_project" && item.id === "tdc-sor") next.car_type_project_id = "";
      return next;
    });
    setFieldErrors((prev) => (prev[name] ? { ...prev, [name]: undefined } : prev));
  };

  const setConnection = (name, value) => {
    setValue(name, value);
    if (item.id === "tdc-sor") {
      // 连接配置变更：作废在途的车型项目请求与已选 id
      carTypeSeq.current += 1;
      setCarTypes({ status: "stale", options: [] });
      setValues((prev) => ({ ...prev, [name]: value, car_type_project_id: "" }));
    }
  };

  // ── 结果渲染 ──
  const renderRows = (data, op, captured) => {
    preview.current = captured;
    setPanelShown(true);
    setResultKind(label(op));
    setContextNote(previewContextText(captured));
    setOutput({ kind: "rows", data: data || {}, operation: op, key: seq.current });
  };

  const showError = (err, op) => {
    if (!mounted.current) return;
    setPanelShown(true);
    setErrorState({ err, loggedIn: false });
    const retained = preview.current;
    if (op === "export") {
      setResultKind("导出失败");
      if (retained) setContextNote(previewContextText(retained, "导出失败"));
    } else if (op) {
      setResultKind(retained ? `${label(op)}失败（保留上次预览）` : `${label(op)}失败`);
      if (retained) setContextNote(previewContextText(retained, "操作失败"));
    }
  };

  // ── 后台任务轮询（有界：2s 间隔、30 分钟上限、卸载即停） ──
  const taskId = task && task.taskId;
  useEffect(() => {
    if (!taskId) return undefined;
    const controller = new AbortController();
    const { signal } = controller;
    const tracked = task;
    const kindLabel = tracked.kind === "export" ? "导出" : "全量抓取";
    (async () => {
      const deadline = Date.now() + TASK_POLL_TIMEOUT_MS;
      let finished = null;
      while (!signal.aborted && Date.now() < deadline) {
        try {
          const data = await getJson(taskUrl(taskId), signal);
          if (signal.aborted) return;
          setTask((prev) => (prev && prev.taskId === taskId
            ? { ...prev, status: data.status, progress: data.progress || {}, active: data.is_active !== false }
            : prev));
          if (data.is_active === false) {
            finished = data;
            break;
          }
        } catch (err) {
          if (signal.aborted || (err && err.name === "AbortError")) return;
          // 瞬态错误继续轮询，由超时兜底
        }
        await sleep(TASK_POLL_INTERVAL_MS, signal);
      }
      if (signal.aborted) return;
      const current = () => tracked.seq > latestRendered.current;
      if (!finished) {
        setTask((prev) => (prev && prev.taskId === taskId ? { ...prev, active: false, status: "timeout" } : prev));
        if (current()) showError(messageError(`后台${kindLabel}任务长时间未完成，请稍后在「任务」中心查看结果。`, "TaskTimeout"), null);
        return;
      }
      if (finished.status === "cancelled") {
        if (current()) setStatus({ text: `后台${kindLabel}任务已取消`, loading: false });
        return;
      }
      if (finished.status !== "succeeded") {
        if (current()) {
          showError(messageError(`后台${kindLabel}任务失败：${redactSensitiveText(finished.error_message || finished.status)}`, "TaskFailed"), null);
        }
        return;
      }
      if (tracked.kind === "export") {
        const downloadUrl = finished.can_download ? taskUrl(taskId, "/download") : null;
        setTask((prev) => (prev && prev.taskId === taskId ? { ...prev, downloadUrl } : prev));
        if (current()) setStatus({ text: downloadUrl ? "后台导出完成，可下载结果文件" : "后台导出完成", loading: false });
        return;
      }
      try {
        const data = await getJson(taskUrl(taskId, "/result"), signal);
        if (signal.aborted) return;
        if (current()) {
          latestRendered.current = tracked.seq;
          renderRows(data, tracked.operation, { queryTime: new Date().toLocaleString(), filterSummary: tracked.summary });
          setStatus({ text: "后台全量抓取完成", loading: false });
        }
        record(tracked.operation, "success", `rows=${((data && data.rows) || []).length}`);
      } catch (err) {
        if (!signal.aborted && current()) showError(asError(err), null);
      }
    })();
    return () => controller.abort();
  }, [taskId]);

  const cancelTask = async () => {
    if (!task || !task.active) return;
    setTask((prev) => ({ ...prev, cancelling: true }));
    try {
      const { ok, status: code, body } = await postJson(taskUrl(task.taskId, "/cancel"), {});
      if (!ok || !body || body.ok !== true) throw toApiError(body, code);
      if (mounted.current) setStatus({ text: "已请求取消后台任务", loading: false });
    } catch (err) {
      if (!mounted.current) return;
      const e = asError(err);
      setStatus({ text: `取消失败：${isLocalGuardError(e) ? LOCAL_ONLY_MESSAGE : formatApiErrorMessage(e)}`, loading: false });
      setTask((prev) => (prev ? { ...prev, cancelling: false } : prev));
    }
  };

  // ── 运行 ──
  const run = async (op) => {
    if (!config || !executable) return;
    if (runLock.current) {
      setStatus({ text: "当前请求仍在处理中，请等待完成", loading: true });
      return;
    }
    const current = valuesRef.current;
    const errors = validateForm(item, current, op);
    const invalid = Object.entries(errors).filter(([, msg]) => msg);
    if (invalid.length) {
      setFieldErrors(errors);
      const [name, message] = invalid[0];
      const field = [...(item.fields || []), ...OPERATION_FIELDS].find((f) => f.name === name);
      const fieldLabel = name === "base_url" ? "Base URL" : name === "file_name" ? "XLSX 文件名" : name === "output_format" ? "输出格式" : (field && field.label) || name;
      setStatus({ text: `请先修正 ${invalid.length} 个字段：${fieldLabel}（${message}）`, loading: false });
      const el = document.getElementById(`dlv-field-${name}`);
      if (el && typeof el.focus === "function" && el.offsetParent !== null) el.focus();
      return;
    }
    setFieldErrors({});
    lastOperation.current = op;
    runLock.current = true;
    const requestSeq = ++seq.current;
    const isCurrent = () => mounted.current && requestSeq > latestRendered.current;
    setRunning(op);
    setStatus({ text: op === "export" ? "导出中" : "运行中", loading: true });
    setErrorState(null);
    if (preview.current) setContextNote(previewContextText(preview.current, "新操作处理中..."));

    let payload = null;
    try {
      payload = buildPayload(item, current, op);
      const summary = formatFilterSummary(item, payload.filters);
      const endpoint = config.endpoints[op];
      if (!endpoint) throw messageError(`未配置操作端点: ${op}`);
      if (op === "export") {
        await runExport(endpoint, payload, requestSeq, summary, isCurrent);
      } else {
        const { status: code, ok, body } = await postJson(endpoint, payload);
        if (isTaskAccepted(code, body)) {
          const id = String(body.data.taskId);
          kickTaskCenter();
          if (!mounted.current) return;
          if (isCurrent()) {
            setPanelShown(true);
            setContextNote(`全量抓取已转入后台任务（${id}），进度与结果请见右上角「任务」中心，完成后将自动展示。`);
          }
          setTask({ taskId: id, kind: "crawl", operation: op, seq: requestSeq, summary, status: "queued", active: true, progress: {} });
          setStatus({ text: "已转入后台任务", loading: false });
          return;
        }
        if (!ok || !body || body.ok !== true) throw toApiError(body, code);
        const data = body.data || {};
        if (isCurrent()) {
          latestRendered.current = requestSeq;
          renderRows(data, op, { queryTime: new Date().toLocaleString(), filterSummary: summary });
        }
        record(op, "success", `rows=${(data.rows || []).length}`);
        if (mounted.current) setStatus({ text: "完成", loading: false });
      }
    } catch (err) {
      if (err && err.name === "AbortError") return;
      const e = asError(err);
      if (isCurrent()) {
        latestRendered.current = requestSeq;
        showError(e, op);
      }
      record(op, "failed", isLocalGuardError(e) ? LOCAL_ONLY_MESSAGE : formatApiErrorMessage(e));
      if (mounted.current) setStatus({ text: op === "export" ? "导出失败" : "操作失败", loading: false });
    } finally {
      clearPayloadSecrets(payload);
      runLock.current = false;
      if (mounted.current) setRunning(null);
    }
  };

  const runExport = async (endpoint, payload, requestSeq, summary, isCurrent) => {
    let response;
    try {
      response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch (_) {
      throw toApiError(null, 0);
    }
    const contentType = response.headers.get("Content-Type") || "";
    if (response.status === 202 || !response.ok || contentType.includes("application/json")) {
      const body = await response.json().catch(() => null);
      if (isTaskAccepted(response.status, body)) {
        const id = String(body.data.taskId);
        kickTaskCenter();
        record("export", "success", `后台任务 ${id}`);
        if (!mounted.current) return;
        setTask({ taskId: id, kind: "export", operation: "export", seq: requestSeq, summary, status: "queued", active: true, progress: {} });
        setStatus({ text: "导出已转入后台任务，完成后请在右上角「任务」中心下载", loading: false });
        return;
      }
      if (response.status === 202) throw messageError("后台导出任务响应无效，请稍后重试", "TaskError");
      throw toApiError(body, response.status);
    }
    const blob = await response.blob();
    const fileName = parseContentDispositionFilename(response.headers.get("Content-Disposition")) || config.defaultExportName;
    saveBlob(blob, fileName);
    if (isCurrent()) {
      latestRendered.current = requestSeq;
      preview.current = null;
      setContextNote("");
      setPanelShown(true);
      setOutput({ kind: "download", fileName });
      setResultKind("导出 XLSX");
    }
    record("export", "success", `文件 ${fileName}`);
    if (mounted.current) setStatus({ text: `已下载：${fileName}`, loading: false });
  };

  // ── 车型项目候选（loadTdcSorProjectOptions） ──
  const loadCarTypes = async () => {
    const requestSeq = ++carTypeSeq.current;
    const current = valuesRef.current;
    setCarTypes({ status: "loading", options: [] });
    setValues((prev) => ({ ...prev, car_type_project_id: "" }));
    const payload = buildPayload(item, { base_url: current.base_url, headers: current.headers }, "car_types");
    const body = { base_url: payload.base_url, headers: payload.headers };
    try {
      const res = await postJson(CAR_TYPE_PROJECTS_ENDPOINT, body);
      if (!mounted.current || requestSeq !== carTypeSeq.current) return;
      if (!res.ok || !res.body || res.body.ok !== true) throw toApiError(res.body, res.status);
      const projects = (res.body.data && Array.isArray(res.body.data.projects) ? res.body.data.projects : [])
        .filter((p) => p && typeof p.id === "string" && p.id.trim())
        .map((p) => ({ ...p, id: p.id.trim() }));
      setCarTypes({ status: "ok", options: projects });
    } catch (err) {
      if (!mounted.current || requestSeq !== carTypeSeq.current) return;
      const e = asError(err);
      setCarTypes({ status: "error", options: [], message: isLocalGuardError(e) ? LOCAL_ONLY_MESSAGE : formatApiErrorMessage(e) });
    } finally {
      clearPayloadSecrets(payload);
      clearPayloadSecrets(body);
    }
  };

  const selectCarType = (id) => {
    const chosen = (carTypes.options || []).find((p) => p.id === id);
    if (!chosen) {
      setValues((prev) => ({ ...prev, car_type_project_id: "" }));
      return;
    }
    setValues((prev) => ({ ...prev, car_type_project: chosen.projectNo || chosen.projectName || "", car_type_project_id: chosen.id }));
  };

  // ── 错误卡片（含原位登录） ──
  const retry = () => {
    setErrorState(null);
    run(lastOperation.current);
  };
  let card = null;
  if (errorState) {
    const { err, loggedIn } = errorState;
    const technical = formatApiErrorMessage(err);
    if (loggedIn) {
      card = {
        summary: "登录成功，会话已更新",
        impact: "当前筛选条件已完好保留，请点击【继续查询】完成操作。",
        actions: [{ label: "继续查询", primary: true, action: retry }],
      };
    } else if (isLocalGuardError(err)) {
      card = {
        summary: LOCAL_ONLY_MESSAGE,
        impact: "请在运行 VSE Toolbox 的本机浏览器中打开本页面后重试；已保留当前选择的报表、筛选草稿与已有预览。",
        actions: [{ label: "重试查询", primary: true, action: retry }],
        technical,
      };
    } else if (isAuthError(err)) {
      const canLogin = typeof window.openInPlaceLogin === "function";
      card = {
        summary: "企业系统认证会话已过期或尚未登录",
        impact: canLogin
          ? "未能执行本次查询，已保留当前选择的报表、筛选草稿与已有预览。"
          : "未能执行本次查询，已保留当前选择的报表、筛选草稿与已有预览；请先在「设置 → 统一域账号登录」完成登录后重试。",
        actions: [
          canLogin
            ? {
              label: "重新登录",
              primary: true,
              action: () => window.openInPlaceLogin({
                notice: "企业会话已失效，请完成域账号登录。登录成功后可继续操作。",
                onLoginSuccess: () => {
                  if (mounted.current) setErrorState((prev) => (prev ? { ...prev, loggedIn: true } : prev));
                },
              }),
            }
            : { label: "重试查询", primary: true, action: retry },
        ],
        technical,
      };
    } else {
      card = {
        summary: "交付物查询/导出未成功",
        impact: "未更新本地数据，原有预览和配置保持不变。",
        actions: [{ label: "重试查询", primary: true, action: retry }],
        technical,
      };
    }
  }

  const busy = Boolean(running);
  const cat = categoryName(categories, item.category);
  const links = item.links && typeof item.links === "object" ? item.links : null;
  const showField = (field) => field.operations.includes(operation);
  const numberInput = (field) => html`<label key=${field.name} for=${`dlv-field-${field.name}`} hidden=${!showField(field)}>
    <span>${field.label}</span>
    <input id=${`dlv-field-${field.name}`} name=${field.name} type="number" min="1" value=${values[field.name]}
      aria-invalid=${fieldErrors[field.name] ? "true" : "false"}
      onInput=${(event) => setValue(field.name, event.currentTarget.value)} />
    <${FieldError} message=${fieldErrors[field.name]} />
  </label>`;

  return html`<div class="dlv-detail-wrap">
    <article class="deliverable-detail">
      <div class="detail-head">
        <div>
          <p class="eyebrow">${cat}</p>
          <h4>${item.name}</h4>
        </div>
        <div class="chip-row">
          <span class=${`status-chip availability-${item.availability}`}>${AVAILABILITY_LABELS[item.availability] || item.availability}</span>
          <span class=${`status-chip ${STATUS_TONE_CLASS[item.implementation_status] || "is-unknown"}`}>${STATUS_LABELS[item.implementation_status] || item.implementation_status}</span>
        </div>
      </div>
      <p class="detail-source">来源：${item.source || "-"}</p>
      <p class="detail-description">${item.description || ""}</p>
      ${item.reason && html`<p class="reason-note">${item.reason}</p>`}

      ${executable && html`<form class="deliverable-form" autocomplete="off" novalidate
        onSubmit=${(event) => { event.preventDefault(); run(operation); }}>
        <section class="form-block connection-block">
          <div class="block-title">
            <p class="eyebrow">连接</p>
            <h4>请求上下文</h4>
          </div>
          <div class="form-grid">
            <label for="dlv-field-base_url">
              <span>Base URL</span>
              <input id="dlv-field-base_url" name="base_url" type="url" required value=${values.base_url}
                aria-invalid=${fieldErrors.base_url ? "true" : "false"}
                onInput=${(event) => setConnection("base_url", event.currentTarget.value)} />
              <${FieldError} message=${fieldErrors.base_url} />
            </label>
            <label class="wide">
              <span>请求头</span>
              <textarea name="headers" rows="3" placeholder="名称: 值" autocomplete="off" value=${values.headers}
                onInput=${(event) => setConnection("headers", event.currentTarget.value)}></textarea>
            </label>
          </div>
          <p class="connection-note">统一使用「设置 → 统一域账号登录」建立的会话，无需在此填写账号密码；未登录时请先完成统一登录。</p>
        </section>

        <section class="form-block fields-block">
          <div class="block-title">
            <p class="eyebrow">筛选</p>
            <h4>查询字段</h4>
          </div>
          <div class="dyna-form-grid">
            ${(item.fields || []).map((field) => {
              const isCarType = item.id === "tdc-sor" && field.name === "car_type_project";
              return html`<label key=${field.name} for=${`dlv-field-${field.name}`}>
                <span>${field.label || field.name}</span>
                <input id=${`dlv-field-${field.name}`} name=${field.name}
                  type=${field.type === "date" ? "date" : field.type === "number" ? "number" : "text"}
                  placeholder=${isCarType ? "例如：E262S（车型项目，可手动输入）" : undefined}
                  autocomplete=${isCarType ? "off" : undefined}
                  value=${values[field.name] ?? ""} aria-invalid=${fieldErrors[field.name] ? "true" : "false"}
                  onInput=${(event) => setValue(field.name, event.currentTarget.value)} />
                <${FieldError} message=${fieldErrors[field.name]} />
                ${isCarType && html`<${CarTypeProjects} state=${carTypes} selectedId=${values.car_type_project_id}
                  onLoad=${loadCarTypes} onSelect=${selectCarType} />`}
              </label>`;
            })}
          </div>
        </section>

        <section class="form-block actions-block deliverable-actions">
          <div class="operation-controls">
            <label class="wide"><span>操作方式</span>
              <select name="operation_mode" disabled=${busy} value=${operation}
                onChange=${(event) => setValue("operation_mode", event.currentTarget.value)}>
                <option value="query">查询预览</option>
                <option value="crawl_all">全量抓取</option>
                <option value="export">导出 XLSX</option>
              </select>
            </label>
            ${OPERATION_FIELDS.map(numberInput)}
            <label hidden=${operation !== "export"}><span>输出格式</span>
              <select id="dlv-field-output_format" name="output_format" value=${values.output_format}
                onChange=${(event) => setValue("output_format", event.currentTarget.value)}>
                <option value="XLSX">XLSX</option>
              </select>
              <${FieldError} message=${fieldErrors.output_format} />
            </label>
            <label for="dlv-field-file_name" hidden=${operation !== "export"}><span>XLSX 文件名</span>
              <input id="dlv-field-file_name" name="file_name" type="text" value=${values.file_name}
                aria-invalid=${fieldErrors.file_name ? "true" : "false"}
                onInput=${(event) => setValue("file_name", event.currentTarget.value)} />
              <${FieldError} message=${fieldErrors.file_name} />
            </label>
            ${(item.id === "tdc-data-model" || item.id === "tdc-sor") && html`<label hidden=${operation === "export"}>
              <span>查询模式</span>
              <select name="preview_source" value=${values.preview_source}
                onChange=${(event) => setValue("preview_source", event.currentTarget.value)}>
                ${PREVIEW_SOURCES.map((option) => html`<option key=${option.value} value=${option.value}>${option.label}</option>`)}
              </select>
            </label>`}
          </div>
          <div class="operation-buttons">
            <button type="submit" class=${`primary-btn${busy ? " is-running" : ""}`} data-deliverable-run disabled=${busy}>${label(operation)}</button>
            <button type="button" class="primary-btn" data-deliverable-download disabled=${busy} onClick=${() => run("export")}>下载 XLSX</button>
          </div>
          <span class=${`deliverable-status${status.loading && status.text ? " loading" : ""}`} aria-live="polite">${status.text}</span>
        </section>
      </form>`}
      ${!executable && isArasTarget(item) && html`<button type="button" class="primary-btn"
        onClick=${() => { window.location.hash = systemQueryHash(item); }}>在系统查询中打开</button>`}
      ${links && links.projectStatusDeliverableId && html`<button type="button" class="btn is-secondary open-project-status-btn"
        onClick=${() => { window.location.hash = `#deliverable/${encodeURIComponent(String(links.projectStatusDeliverableId))}`; }}>
        查看项目状态/表单分析</button>`}
    </article>

    <${TaskStrip} task=${task} onCancel=${cancelTask} />

    <section class=${`result-panel${output ? " has-output" : ""}`} aria-live="polite" hidden=${!panelShown}>
      <div class="result-head">
        <p class="eyebrow">结果</p>
        <span class="dlv-result-kind">${resultKind}</span>
      </div>
      ${card && html`<div class="error-msg dlv-error"><${ErrorCard} card=${card} /></div>`}
      ${contextNote && html`<div class="deliverable-preview-context">${contextNote}</div>`}
      ${!output && html`<div class="is-empty">暂无结果</div>`}
      ${output && output.kind === "download" && html`<div class="result-output-content">
        <p class="result-output-meta">已下载：${output.fileName}</p>
      </div>`}
      ${output && output.kind === "rows" && html`<div class="result-output-content">
        <p class="result-output-meta">${item.name} -> ${output.operation}</p>
        <p class="result-meta">${resultMetaText(output.data)}</p>
        ${unmappedWarning(output.data) && html`<p class="result-meta result-warning">${unmappedWarning(output.data)}</p>`}
        ${(output.data.rows || []).length === 0
          ? html`<${EmptyNotice} title="未查询到符合条件的交付物记录"
              desc="当前筛选条件下未返回任何交付物数据。已保留所选交付物及筛选配置，您可以修改筛选条件后重试。" />`
          : html`<${DataGrid} key=${output.key} data=${output.data} modeId=${item.id} preferredColumns=${[]} />`}
      </div>`}
    </section>
  </div>`;
}

// ── 页面 ───────────────────────────────────────────────────────────────

export default function DeliverablesCatalogPage({ plugin }) {
  useStylesheet(`/plugins/${plugin.id}/static/catalog.css`);
  const [catalog, setCatalog] = useState({ status: "loading", items: [], categories: [], message: "" });
  const [category, setCategory] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [detailNonce, setDetailNonce] = useState(0);
  const [recentRuns, setRecentRuns] = useState(recentRunsMemory);
  const mounted = useRef(true);
  const loadSeq = useRef(0);
  const runLock = useRef(false);
  const selectedRef = useRef("");
  const catalogRef = useRef(catalog);
  selectedRef.current = selectedId;
  catalogRef.current = catalog;

  useEffect(() => () => { mounted.current = false; }, []);

  const onRecord = (run) => {
    recentRunsMemory = addRecentRun(recentRunsMemory, run);
    if (mounted.current) setRecentRuns(recentRunsMemory);
  };

  const select = (id, { updateHash = true } = {}) => {
    setSelectedId(id);
    setDetailNonce((n) => n + 1);
    if (updateHash && window.location.hash.startsWith(PAGE_HASH)) {
      try {
        window.history.replaceState(window.history.state, "", itemHash(id));
      } catch (_) {
        // replaceState 不可用时仅更新页面内选择
      }
    }
  };

  const load = async () => {
    const current = ++loadSeq.current;
    setCatalog((prev) => ({ ...prev, status: "loading", message: "" }));
    try {
      const data = await getJson(CATALOG_ENDPOINT);
      if (!mounted.current || current !== loadSeq.current) return;
      if (!data || typeof data !== "object") throw messageError("目录响应无效");
      const items = Array.isArray(data.deliverables) ? data.deliverables : [];
      const categories = Array.isArray(data.categories) ? data.categories : [];
      setCatalog({ status: "ok", items, categories, message: "" });
      const requested = parseItemParam(window.location.hash);
      const chosen = pickInitialItem(items, requested, selectedRef.current);
      if (chosen) select(chosen.id, { updateHash: false });
    } catch (err) {
      if (!mounted.current || current !== loadSeq.current) return;
      const e = asError(err);
      setCatalog((prev) => ({
        ...prev,
        status: "error",
        message: isLocalGuardError(e) ? LOCAL_ONLY_MESSAGE : redactSensitiveText(e.message || `HTTP ${e.status}`),
      }));
    }
  };

  useEffect(() => { load(); }, []);

  // 深链：#p/deliverables/catalog?item=<id>
  useEffect(() => {
    const apply = () => {
      const id = parseItemParam(window.location.hash);
      if (!id || id === selectedRef.current) return;
      const items = catalogRef.current.items || [];
      const target = items.find((entry) => entry.id === id);
      if (!target) return;
      setCategory((prev) => (prev && prev !== target.category ? "" : prev));
      setStatusFilter((prev) => (prev && prev !== target.implementation_status ? "" : prev));
      select(id, { updateHash: false });
    };
    window.addEventListener("hashchange", apply);
    return () => window.removeEventListener("hashchange", apply);
  }, []);

  const onFilterChange = (nextCategory, nextStatus) => {
    setCategory(nextCategory);
    setStatusFilter(nextStatus);
    const visible = visibleDeliverables(catalog.items, nextCategory, nextStatus);
    if (!visible.some((entry) => entry.id === selectedId) && visible[0]) select(visible[0].id);
  };

  const items = catalog.items || [];
  const categories = catalog.categories || [];
  const visible = visibleDeliverables(items, category, statusFilter);
  const selected = items.find((entry) => entry.id === selectedId) || null;
  const catOptions = categoryOptions(categories);
  const statOptions = statusOptions(items);

  let list;
  if (catalog.status === "loading") {
    list = html`<div class="deliverable-list loading">加载目录中</div>`;
  } else if (catalog.status === "error") {
    list = html`<div class="deliverable-list is-empty"><p class="error-msg">目录加载失败：${catalog.message}</p></div>`;
  } else if (visible.length === 0) {
    list = html`<div class="deliverable-list is-empty">没有匹配的目录项</div>`;
  } else {
    list = html`<div class="deliverable-list">${visible.map((entry) => html`<button key=${entry.id} type="button"
      class=${`deliverable-item${entry.id === selectedId ? " active" : ""}${entry.availability !== "available" ? " is-unavailable" : ""}`}
      aria-current=${entry.id === selectedId ? "true" : undefined}
      onClick=${() => select(entry.id)}>
      <span class="deliverable-name">${entry.name}</span>
      <span class="deliverable-meta">${itemMetaText(entry, categories)}</span>
    </button>`)}</div>`;
  }

  return html`<section class="dlv-page deliverables-workbench" aria-label="交付物工作台">
    <div class="deliverables-head">
      <div>
        <p class="eyebrow">目录</p>
        <h3>交付物工作台</h3>
      </div>
      <div class="deliverable-filters">
        <label class="filter-control">
          <span>分类</span>
          <select aria-label="分类" value=${catOptions.some((o) => o.id === category) ? category : ""}
            onChange=${(event) => onFilterChange(event.currentTarget.value, statusFilter)}>
            ${catOptions.map((option) => html`<option key=${option.id} value=${option.id}>${option.name}</option>`)}
          </select>
        </label>
        <label class="filter-control">
          <span>状态</span>
          <select aria-label="状态" value=${statOptions.some((o) => o.id === statusFilter) ? statusFilter : ""}
            onChange=${(event) => onFilterChange(category, event.currentTarget.value)}>
            ${statOptions.map((option) => html`<option key=${option.id} value=${option.id}>${option.name}</option>`)}
          </select>
        </label>
        <button class="segment" type="button" disabled=${catalog.status === "loading"} onClick=${load}>刷新目录</button>
      </div>
    </div>

    <div class="deliverables-layout">
      <aside class="catalog-pane" aria-label="交付物目录">${list}</aside>
      <div class="detail-pane">
        ${selected
          ? html`<${DeliverableDetail} key=${`${selected.id}:${detailNonce}`} item=${selected} categories=${categories}
              runLock=${runLock} onRecord=${onRecord} />`
          : html`<article class="deliverable-detail is-empty"><p class="loading">请选择目录项</p></article>`}
        <${RecentRuns} runs=${recentRuns} />
      </div>
    </div>
  </section>`;
}
