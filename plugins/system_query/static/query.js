// 系统查询 module page: Aras EWO / PAA / NCR and TDC 数模 / SOR / A 面.
// Every mode is data (modes.js); this file has one code path for query,
// crawl-all (202 + task polling), export/download, XML capture and errors.
// It calls the existing /api/aras, /api/tdc and /api/tasks endpoints.
import { html, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { useStylesheet } from "/static/host/kit.js";
import { DataGrid } from "./grid.js";
import {
  FORBIDDEN_PERSIST_KEYS,
  buildPayload,
  clearPayloadSecrets,
  defaultGroupValues,
  fieldsForGroup,
  formatApiErrorMessage,
  isAuthError,
  isTaskAccepted,
  parseContentDispositionFilename,
  parseDeepLink,
  redactSensitiveText,
  resultMetaText,
  resultRowCount,
  safeDisplayValue,
  serialMatchNotice,
  SENSITIVE_COLUMNS,
  taskPercent,
  taskProgressText,
  toQueryError,
  validateForm,
} from "./lib.js";
import {
  COMMAND_LABELS,
  DEFAULT_MODE,
  MODES,
  MODE_IDS,
  RESULT_KIND_LABELS,
  SYSTEMS,
  TDC_OPERATION_FIELDS,
  TDC_PREVIEW_SOURCES,
} from "./modes.js";

const PAGE_HASH = "#p/system-query/query";
const PREFS_KEY = "vse-toolbox-aras-preferences-v1"; // 与旧页面共用，偏好互通
const TASK_POLL_INTERVAL_MS = 2000;
const TASK_POLL_TIMEOUT_MS = 30 * 60 * 1000;
const OPERATION_LABELS = { query: "查询", crawl_all: "全量获取", export: "导出" };

// ── 偏好（只存筛选值与 Base URL；请求头/凭据永不落盘） ─────────────────

function readPrefs() {
  try {
    const parsed = JSON.parse(localStorage.getItem(PREFS_KEY) || "null");
    if (parsed && parsed.version === 1 && parsed.modes && typeof parsed.modes === "object") return parsed;
  } catch (_) {
    // 存储不可用或内容损坏时忽略
  }
  return null;
}

function restorePrefs(modeId) {
  const prefs = readPrefs();
  const saved = prefs && prefs.modes[modeId];
  if (!saved || typeof saved !== "object") return {};
  const clean = {};
  Object.entries(saved).forEach(([key, value]) => {
    if (FORBIDDEN_PERSIST_KEYS.has(key.toLowerCase()) || typeof value !== "string") return;
    clean[key] = value;
  });
  return clean;
}

function savePrefs(modeId, values, baseUrl) {
  try {
    const mode = MODES[modeId];
    const current = readPrefs() || { version: 1, modes: {} };
    const entry = {};
    [...mode.filterNames, ...mode.numberNames, ...(mode.crawlNumberNames || [])].forEach((name) => {
      if (FORBIDDEN_PERSIST_KEYS.has(name.toLowerCase())) return;
      if (values[name] !== undefined) entry[name] = String(values[name]);
    });
    if (baseUrl) entry._baseUrl = baseUrl;
    current.modes[modeId] = entry;
    localStorage.setItem(PREFS_KEY, JSON.stringify(current));
  } catch (_) {
    // 隐私模式等：静默降级
  }
}

function initialGroupValues(modeId) {
  const mode = MODES[modeId];
  const values = defaultGroupValues(mode.fieldGroup, mode.system);
  if (mode.system === "tdc") values.file_name = mode.defaultFileName;
  const saved = restorePrefs(modeId);
  Object.keys(values).forEach((key) => {
    if (saved[key] !== undefined) values[key] = saved[key];
  });
  return { values, baseUrl: saved._baseUrl || "" };
}

function filterSummary(modeId, payload) {
  const labels = new Map(fieldsForGroup(MODES[modeId].fieldGroup).map((f) => [f.name, f.label]));
  const parts = [];
  const entries = Object.entries(payload.filters || {});
  // 流水单号在请求体顶层（不是 filters），但它仍是用户填写的筛选条件。
  if (payload.document_no) entries.push(["document_no", payload.document_no]);
  entries.forEach(([key, value]) => {
    if (key === "car_type_project_id") return;
    const shown = Array.isArray(value) ? value.join(",") : String(value ?? "").trim();
    if (shown) parts.push(`${labels.get(key) || key}: ${redactSensitiveText(shown)}`);
  });
  return parts.length ? parts.join("；") : "无筛选条件";
}

// ── HTTP：旧接口直接 fetch，保留 diagnosticPath 与 202 契约 ─────────────

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
    throw toQueryError(null, 0);
  }
  const body = await response.json().catch(() => null);
  return { status: response.status, ok: response.ok, body };
}

async function getJson(url, signal) {
  const response = await fetch(url, { headers: { Accept: "application/json" }, cache: "no-store", signal });
  const body = await response.json().catch(() => null);
  if (!response.ok || !body || body.ok !== true) throw toQueryError(body, response.status);
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

function SummaryTable({ data }) {
  return html`<table class="result-table"><tbody>
    ${Object.entries(data).filter(([key]) => !SENSITIVE_COLUMNS.has(key.toLowerCase())).map(([key, value]) => html`<tr key=${key}>
      <th>${key}</th><td>${safeDisplayValue(typeof value === "object" && value !== null ? JSON.stringify(value) : value)}</td>
    </tr>`)}
  </tbody></table>`;
}

function Field({ field, value, error, onInput, children }) {
  const id = `sq-field-${field.name}`;
  return html`<label class=${field.wide ? "wide" : ""} for=${id}>
    <span>${field.label}</span>
    <input
      id=${id} name=${field.name}
      type=${field.type === "date" ? "date" : field.type === "number" ? "number" : "text"}
      min=${field.type === "number" ? String(field.min || 1) : undefined}
      placeholder=${field.placeholder || ""} title=${field.title || ""}
      value=${value ?? ""} aria-invalid=${error ? "true" : "false"}
      onInput=${(event) => onInput(field.name, event.currentTarget.value)}
    />
    ${field.note && html`<small class="field-note">${field.note}</small>`}
    ${children}
    ${error && html`<small class="sq-field-error" role="alert">${error}</small>`}
  </label>`;
}

function CarTypeProjects({ state, selectedId, onLoad, onSelect }) {
  const options = state.options || [];
  let placeholder = "请选择车型项目（需先加载）";
  if (state.status === "loading") placeholder = "加载中...";
  else if (state.status === "error") placeholder = `加载失败：${state.message}`;
  else if (state.status === "stale") placeholder = "连接配置已变更，请重新加载车型项目";
  else if (state.status === "ok") placeholder = options.length ? `请选择车型项目（共 ${options.length} 项）` : "未找到可用车型项目";
  return html`<div class="car-type-project-group sq-car-type">
    <select class="car-type-project-options" aria-label="车型项目候选" disabled=${state.status === "loading"}
      value=${selectedId || ""} onChange=${(event) => onSelect(event.currentTarget.value)}>
      <option value="">${placeholder}</option>
      ${options.map((p) => html`<option key=${p.id} value=${p.id}>${p.label || p.projectNo || p.projectName || p.id}</option>`)}
    </select>
    <button type="button" class="segment car-type-load-btn" disabled=${state.status === "loading"} onClick=${onLoad}>
      ${state.status === "loading" ? "加载中..." : "重新加载车型项目"}
    </button>
  </div>`;
}

function TaskStrip({ task, onCancel }) {
  if (!task) return null;
  const percent = taskPercent(task);
  const statusText = {
    queued: "排队中", leased: "准备中", running: "运行中", succeeded: "已完成",
    failed: "失败", cancelled: "已取消", interrupted: "已中断", timeout: "超时",
  }[task.status] || task.status || "排队中";
  return html`<div class="sq-task" role="status" aria-live="polite">
    <div class="sq-task-head">
      <strong>后台${task.kind === "export" ? "导出" : "全量抓取"}任务</strong>
      <span class="sq-task-id">${task.taskId}</span>
      <span class=${`sq-task-status is-${task.status || "queued"}`}>${statusText}</span>
      ${task.active && html`<button type="button" class="secondary-btn" disabled=${task.cancelling} onClick=${onCancel}>
        ${task.cancelling ? "取消中..." : "取消任务"}</button>`}
      ${task.downloadUrl && html`<a class="secondary-btn sq-task-download" href=${task.downloadUrl} download>下载结果文件</a>`}
    </div>
    ${task.active && html`<div class="sq-progress" aria-label="任务进度">
      <div class="sq-progress-fill" style=${{ width: `${percent ?? 5}%` }}></div>
    </div>`}
    <div class="sq-task-detail">${taskProgressText(task) || "进度与结果也可在右上角「任务」中心查看"}</div>
  </div>`;
}

// ── 页面 ───────────────────────────────────────────────────────────────

function initialMode() {
  const link = parseDeepLink(window.location.hash);
  return link.mode || DEFAULT_MODE;
}

export default function SystemQueryPage({ plugin }) {
  useStylesheet(`/plugins/${plugin.id}/static/query.css`);
  const [modeId, setModeId] = useState(initialMode);
  const mode = MODES[modeId];
  const [connections, setConnections] = useState(() => Object.fromEntries(
    SYSTEMS.map((system) => [system.id, { base_url: system.baseUrl, headers: "" }]),
  ));
  const [valuesByMode, setValuesByMode] = useState({});
  const [includeXml, setIncludeXml] = useState(false);
  const [fieldErrors, setFieldErrors] = useState({});
  const [running, setRunning] = useState(null);
  const [statusText, setStatusText] = useState("");
  const [errorState, setErrorState] = useState(null);
  const [warning, setWarning] = useState("");
  const [result, setResult] = useState(null);
  const [contextNote, setContextNote] = useState("");
  const [xml, setXml] = useState(null);
  const [task, setTask] = useState(null);
  const [carTypes, setCarTypes] = useState({ status: "idle", options: [] });
  const [deepLink, setDeepLink] = useState(() => parseDeepLink(window.location.hash));

  const seq = useRef(0);
  const mounted = useRef(true);
  const modeRef = useRef(modeId);
  const resultRef = useRef(null);
  const carTypeSeq = useRef(0);
  const lastAction = useRef("query");
  modeRef.current = modeId;
  resultRef.current = result;

  useEffect(() => () => { mounted.current = false; }, []);

  // 某模式第一次出现时：默认值 + 已存偏好；ncr-progress / ncr-detail 共用 ncr 字段组。
  useEffect(() => {
    if (valuesByMode[modeId]) return;
    const group = MODES[modeId].fieldGroup;
    const sibling = MODE_IDS.find((other) => other !== modeId && MODES[other].fieldGroup === group && valuesByMode[other]);
    if (sibling) {
      setValuesByMode((prev) => ({ ...prev, [modeId]: prev[modeId] || prev[sibling] }));
      return;
    }
    const { values: initial, baseUrl } = initialGroupValues(modeId);
    setValuesByMode((prev) => (prev[modeId] ? prev : { ...prev, [modeId]: initial }));
    if (baseUrl) {
      const system = MODES[modeId].system;
      setConnections((prev) => ({ ...prev, [system]: { ...prev[system], base_url: baseUrl } }));
    }
  }, [modeId, valuesByMode]);
  const values = valuesByMode[modeId] || {};

  /** Update fields of one mode; modes sharing a field group share the values. */
  const patchValues = (targetMode, patch) => {
    const group = MODES[targetMode].fieldGroup;
    const next = { ...(valuesByMode[targetMode] || {}), ...patch };
    setValuesByMode((prev) => {
      const updated = { ...prev };
      MODE_IDS.forEach((id) => {
        if (id === targetMode || (MODES[id].fieldGroup === group && prev[id])) updated[id] = next;
      });
      return updated;
    });
    savePrefs(targetMode, next, connections[MODES[targetMode].system].base_url);
  };

  const setGroupValue = (name, value) => {
    // 车型项目手输即清除候选 id（旧页面同口径）
    patchValues(modeId, name === "car_type_project" ? { [name]: value, car_type_project_id: "" } : { [name]: value });
    setFieldErrors((prev) => (prev[name] ? { ...prev, [name]: undefined } : prev));
  };

  const setConnection = (name, value) => {
    setConnections((prev) => ({ ...prev, [mode.system]: { ...prev[mode.system], [name]: value } }));
    if (name === "base_url") savePrefs(modeId, values, value);
    if (mode.system === "tdc" && carTypes.status !== "idle") {
      carTypeSeq.current += 1;
      setCarTypes({ status: "stale", options: [] });
      if (valuesByMode["tdc-sor"]) patchValues("tdc-sor", { car_type_project_id: "" });
    }
    setFieldErrors((prev) => (prev[name] ? { ...prev, [name]: undefined } : prev));
  };

  const resetOutput = () => {
    seq.current += 1;
    setErrorState(null);
    setWarning("");
    setResult(null);
    setXml(null);
    setContextNote("");
    setStatusText("");
    setFieldErrors({});
  };

  const switchMode = (id) => {
    if (!MODES[id] || id === modeRef.current) return;
    resetOutput();
    if (MODES[id].system !== MODES[modeRef.current].system) setCarTypes({ status: "idle", options: [] });
    setModeId(id);
  };

  // 深链：#p/system-query/query?mode=<mode>&from=overview&ewo_no=...
  useEffect(() => {
    const apply = () => {
      if (!window.location.hash.startsWith(PAGE_HASH)) return;
      const link = parseDeepLink(window.location.hash);
      setDeepLink(link);
      const target = link.mode || modeRef.current;
      if (link.mode) switchMode(link.mode);
      if (link.identifier && link.identifierField) {
        setValuesByMode((prev) => {
          const base = prev[target] || initialGroupValues(target).values;
          return { ...prev, [target]: { ...base, [link.identifierField]: link.identifier } };
        });
      }
    };
    apply();
    window.addEventListener("hashchange", apply);
    return () => window.removeEventListener("hashchange", apply);
  }, []);

  // ── 错误卡片 ──
  const showError = (err, action, retainedNote) => {
    if (!mounted.current) return;
    setErrorState({ err, action, loggedIn: false });
    if (resultRef.current) {
      setContextNote(retainedNote || "未能获取最新数据，已为您保留上次查询成功的历史结果（可检查上方错误提示后重试）。");
    } else {
      setContextNote("");
    }
  };

  // ── 后台任务轮询（有界：2s 间隔、30 分钟上限、卸载即停） ──
  const taskId = task && task.taskId;
  useEffect(() => {
    if (!taskId) return undefined;
    const controller = new AbortController();
    const { signal } = controller;
    const tracked = task;
    (async () => {
      const deadline = Date.now() + TASK_POLL_TIMEOUT_MS;
      let finished = null;
      while (!signal.aborted && Date.now() < deadline) {
        try {
          const data = await getJson(`/api/tasks/${encodeURIComponent(taskId)}`, signal);
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
      const sameView = tracked.seq === seq.current && tracked.modeId === modeRef.current;
      if (!finished) {
        setTask((prev) => (prev && prev.taskId === taskId ? { ...prev, active: false, status: "timeout" } : prev));
        if (sameView) showError({ type: "TaskTimeout", message: "后台任务长时间未完成，请稍后在「任务」中心查看结果。", status: 0 }, tracked.kind);
        return;
      }
      if (finished.status === "cancelled") {
        if (sameView) setStatusText(`后台${tracked.kind === "export" ? "导出" : "全量抓取"}任务已取消`);
        return;
      }
      if (finished.status !== "succeeded") {
        if (sameView) {
          showError({
            type: "TaskFailed",
            status: 0,
            message: `后台任务失败：${redactSensitiveText(finished.error_message || finished.status)}`,
          }, tracked.kind);
        }
        return;
      }
      if (tracked.kind === "export") {
        setTask((prev) => (prev && prev.taskId === taskId
          ? { ...prev, downloadUrl: finished.can_download ? `/api/tasks/${encodeURIComponent(taskId)}/download` : null }
          : prev));
        if (sameView) setStatusText("后台导出完成，可下载结果文件");
        return;
      }
      try {
        const data = await getJson(`/api/tasks/${encodeURIComponent(taskId)}/result`, signal);
        if (signal.aborted) return;
        if (tracked.seq === seq.current && tracked.modeId === modeRef.current) {
          renderResult(data, tracked.modeId, tracked.summary);
          setStatusText("后台全量抓取完成");
        } else {
          setStatusText("后台全量抓取已完成；当前视图已切换，结果可在「任务」中心查看");
        }
      } catch (err) {
        if (!signal.aborted && sameView) showError(err, "crawl_all");
      }
    })();
    return () => controller.abort();
  }, [taskId]);

  const cancelTask = async () => {
    if (!task || !task.active) return;
    setTask((prev) => ({ ...prev, cancelling: true }));
    try {
      const { ok, status, body } = await postJson(`/api/tasks/${encodeURIComponent(task.taskId)}/cancel`, {});
      if (!ok || !body || body.ok !== true) throw toQueryError(body, status);
      setStatusText("已请求取消后台任务");
    } catch (err) {
      setWarning(`取消失败：${formatApiErrorMessage(err)}`);
      setTask((prev) => (prev ? { ...prev, cancelling: false } : prev));
    }
  };

  // ── 结果 ──
  const renderResult = (data, id, summary) => {
    setResult({ data: data || {}, modeId: id, key: seq.current, at: new Date().toLocaleString(), summary });
    setContextNote("");
    const m = MODES[id];
    const captured = data && data.xml;
    if (m.xmlCapture && captured && typeof captured.requestXml === "string" && typeof captured.responseXml === "string"
      && captured.requestXml && captured.responseXml) {
      setXml({ requestXml: captured.requestXml, responseXml: captured.responseXml, modeId: id });
    } else {
      setXml(null);
    }
  };

  // ── 操作 ──
  const run = async (operation) => {
    if (running) return;
    const errors = validateForm(modeId, values, connections[mode.system], operation);
    const invalid = Object.entries(errors).filter(([, msg]) => msg);
    if (invalid.length) {
      setFieldErrors(errors);
      setStatusText(`请先修正 ${invalid.length} 个字段`);
      const first = document.getElementById(`sq-field-${invalid[0][0]}`);
      if (first && typeof first.focus === "function") first.focus();
      return;
    }
    setFieldErrors({});
    lastAction.current = operation;
    const requestMode = modeId;
    const requestSeq = ++seq.current;
    const stillCurrent = () => mounted.current && requestSeq === seq.current && requestMode === modeRef.current;
    const payload = buildPayload(requestMode, values, connections[mode.system], { operation, includeXml });
    const summary = filterSummary(requestMode, payload);
    savePrefs(requestMode, values, connections[mode.system].base_url);
    setErrorState(null);
    setWarning("");
    if (operation !== "export") setXml(null);
    setRunning(operation);
    setStatusText(operation === "query" ? "运行中" : operation === "crawl_all" ? "全量获取中..." : "导出中");
    if (resultRef.current && operation !== "export") {
      setContextNote(operation === "crawl_all"
        ? "保留上次查询结果 · 正在全量获取最新数据..."
        : "保留上次查询结果 · 正在获取最新数据...");
    }
    try {
      if (operation === "export") {
        await runExport(requestMode, payload, requestSeq, summary, stillCurrent);
      } else {
        const endpoint = operation === "crawl_all" ? mode.crawlAllEndpoint : mode.endpoint;
        const { status, ok, body } = await postJson(endpoint, payload);
        if (!stillCurrent()) return;
        if (isTaskAccepted(status, body)) {
          const id = String(body.data.taskId);
          kickTaskCenter();
          setTask({ taskId: id, kind: "crawl", modeId: requestMode, seq: requestSeq, summary, status: "queued", active: true, progress: {} });
          setContextNote(`全量抓取已转入后台任务（${id}），进度见下方，完成后将自动展示。`);
          setStatusText("");
          return;
        }
        if (!ok || !body || body.ok !== true) throw toQueryError(body, status);
        renderResult(body.data, requestMode, summary);
        setStatusText(operation === "crawl_all" ? "全量获取完成" : "完成");
      }
    } catch (err) {
      if (!stillCurrent() || (err && err.name === "AbortError")) return;
      setStatusText(operation === "export" ? "导出失败" : "操作失败");
      showError(err && err.type ? err : toQueryError({ error: { message: String(err && err.message) } }, 0), operation);
    } finally {
      clearPayloadSecrets(payload);
      if (mounted.current) setRunning(null);
    }
  };

  const runExport = async (requestMode, payload, requestSeq, summary, stillCurrent) => {
    const m = MODES[requestMode];
    const endpoint = m.exportEndpoint || m.downloadEndpoint;
    let response;
    try {
      response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch (_) {
      throw toQueryError(null, 0);
    }
    const contentType = response.headers.get("Content-Type") || "";
    if (response.status === 202 || !response.ok || contentType.includes("application/json")) {
      const body = await response.json().catch(() => null);
      if (isTaskAccepted(response.status, body)) {
        const id = String(body.data.taskId);
        kickTaskCenter();
        if (!mounted.current) return;
        setTask({ taskId: id, kind: "export", modeId: requestMode, seq: requestSeq, summary, status: "queued", active: true, progress: {} });
        setStatusText(`导出已转入后台任务（${id}），完成后可在此处或右上角「任务」中心下载`);
        return;
      }
      if (response.status === 202) throw toQueryError({ error: { type: "TaskError", message: "后台导出任务响应无效，请稍后重试" } }, 202);
      throw toQueryError(body, response.status);
    }
    const blob = await response.blob();
    const fileName = parseContentDispositionFilename(response.headers.get("Content-Disposition")) || m.defaultFileName;
    saveBlob(blob, fileName);
    if (!stillCurrent()) return;
    const rowCount = response.headers.get("X-Export-Row-Count");
    const parts = [`已下载：${fileName}`];
    if (rowCount != null) parts.push(`共 ${rowCount} 行`);
    setStatusText(parts.join("，"));
    if (response.headers.get("X-Export-Truncated") === "true" || response.headers.get("X-Export-Complete") === "false") {
      setWarning("导出已截断：结果超过 max_records / max_pages 限制，文件不完整！请调大限制后重试。");
    }
  };

  const loadCarTypes = async () => {
    const requestSeq = ++carTypeSeq.current;
    const connection = connections.tdc;
    setCarTypes({ status: "loading", options: [] });
    patchValues("tdc-sor", { car_type_project_id: "" });
    const payload = { base_url: connection.base_url.trim(), headers: buildPayload("tdc-sor", {}, connection).headers };
    try {
      const { ok, status, body } = await postJson(MODES["tdc-sor"].carTypeProjectsEndpoint, payload);
      if (!mounted.current || requestSeq !== carTypeSeq.current) return;
      if (!ok || !body || body.ok !== true) throw toQueryError(body, status);
      const projects = (body.data && Array.isArray(body.data.projects) ? body.data.projects : [])
        .filter((p) => p && typeof p.id === "string" && p.id.trim())
        .map((p) => ({ ...p, id: p.id.trim() }));
      setCarTypes({ status: "ok", options: projects });
    } catch (err) {
      if (!mounted.current || requestSeq !== carTypeSeq.current) return;
      setCarTypes({ status: "error", options: [], message: formatApiErrorMessage(err.type ? err : toQueryError(null, 0)) });
    } finally {
      clearPayloadSecrets(payload);
    }
  };

  const selectCarType = (id) => {
    const chosen = (carTypes.options || []).find((p) => p.id === id);
    if (!chosen) {
      patchValues("tdc-sor", { car_type_project_id: "" });
      return;
    }
    patchValues("tdc-sor", { car_type_project: chosen.projectNo || chosen.projectName || "", car_type_project_id: chosen.id });
  };

  const downloadXml = (kind) => {
    if (!xml) return;
    const text = kind === "request" ? xml.requestXml : xml.responseXml;
    const stamp = new Date().toISOString().replace(/[.:]/g, "-");
    try {
      saveBlob(new Blob([text], { type: "application/xml;charset=utf-8" }), `aras-${xml.modeId}-${kind}-${stamp}.xml`);
    } catch (err) {
      setWarning(`XML 下载失败：${redactSensitiveText(err && err.message)}`);
    }
  };

  // ── 错误卡片内容（含原位登录） ──
  const retry = () => {
    setErrorState(null);
    run(lastAction.current);
  };
  let card = null;
  if (errorState) {
    const { err, loggedIn } = errorState;
    const technical = formatApiErrorMessage(err);
    if (loggedIn) {
      card = {
        summary: "登录成功，企业会话已就绪",
        impact: "当前筛选条件已完好保留，请点击【继续查询】获取最新报表数据。",
        actions: [{ label: "继续查询", primary: true, action: retry }],
      };
    } else if (isAuthError(err)) {
      const systemName = mode.system === "tdc" ? "TDC" : "Aras/ECM";
      const canLogin = typeof window.openInPlaceLogin === "function";
      card = {
        summary: `企业域账号（${systemName}）会话已过期或尚未认证`,
        impact: canLogin
          ? "当前查询无法完成，原页面已填写的查询条件与已有数据已完好保留。"
          : "当前查询无法完成，查询条件已保留；请先在「设置 → 统一域账号登录」完成登录后重试。",
        actions: [
          canLogin && {
            label: "重新登录",
            primary: true,
            action: () => window.openInPlaceLogin({
              notice: `${mode.system === "tdc" ? "TDC" : "Aras"} 会话已失效，请完成域登录。登录成功后可继续查询。`,
              onLoginSuccess: () => {
                if (mounted.current) setErrorState((prev) => (prev ? { ...prev, loggedIn: true } : prev));
              },
            }),
          },
          { label: "重新查询", primary: !canLogin, action: retry },
        ].filter(Boolean),
        technical,
      };
    } else {
      card = {
        summary: `${mode.system === "tdc" ? "TDC 报表" : "Aras 报表"}${OPERATION_LABELS[errorState.action] || "查询"}未成功`,
        impact: "未能获取最新数据，原页面已有数据和已填条件保持不变。",
        actions: [{ label: "重新查询", primary: true, action: retry }],
        technical,
      };
    }
  }

  const fieldGroup = fieldsForGroup(mode.fieldGroup);
  const connection = connections[mode.system];
  const busy = Boolean(running);
  const shownResult = result && result.modeId === modeId ? result : null;
  const serialNotice = shownResult ? serialMatchNotice(shownResult.data) : null;
  const deepLinkActive = deepLink.from === "overview";

  return html`<div class="aras-workbench sq-page">
    ${deepLinkActive && html`<div class="deep-link-back-bar">
      <button type="button" class="back-link-btn" onClick=${() => { window.location.hash = "#overview"; }}>← 返回项目看板</button>
      ${deepLink.identifier && html`<span class="deep-link-hint">穿透查询单号：${deepLink.identifier}</span>`}
    </div>`}
    <div class="aras-head">
      <div>
        <p class="eyebrow">业务系统</p>
        <h3>系统查询</h3>
      </div>
      <div class="sq-mode-groups">
        ${SYSTEMS.map((system) => html`<div key=${system.id} class="mode-toolbar" role="tablist" aria-label=${`${system.title} 查询模式`}>
          <span class="sq-mode-system">${system.title}</span>
          ${MODE_IDS.filter((id) => MODES[id].system === system.id).map((id) => html`<button
            key=${id} type="button" role="tab" data-mode=${id}
            class=${`segment${id === modeId ? " active" : ""}`} aria-selected=${id === modeId ? "true" : "false"}
            onClick=${() => switchMode(id)}
          >${COMMAND_LABELS[id]}</button>`)}
        </div>`)}
      </div>
    </div>

    <form class="aras-form" autocomplete="on" novalidate onSubmit=${(event) => { event.preventDefault(); run("query"); }}>
      <section class="form-block connection-block">
        <div class="block-title">
          <p class="eyebrow">连接</p>
          <h4>请求上下文</h4>
        </div>
        <div class="form-grid">
          <label class="wide" for="sq-field-base_url">
            <span>Base URL</span>
            <input id="sq-field-base_url" name="base_url" type="url" autocomplete="url"
              value=${connection.base_url} aria-invalid=${fieldErrors.base_url ? "true" : "false"}
              onInput=${(event) => setConnection("base_url", event.currentTarget.value)} />
            ${fieldErrors.base_url && html`<small class="sq-field-error" role="alert">${fieldErrors.base_url}</small>`}
          </label>
          <label class="wide">
            <span>请求头</span>
            <textarea name="headers" rows="3" placeholder="名称: 值" autocomplete="off"
              value=${connection.headers} onInput=${(event) => setConnection("headers", event.currentTarget.value)}></textarea>
          </label>
        </div>
        <p class="connection-note">统一使用「设置 → 统一域账号登录」建立的会话，无需在此填写账号密码；未登录时请先完成统一登录。</p>
        ${mode.title && html`<p class="connection-note sq-mode-title">${mode.title}</p>`}
        ${mode.blockedNotice && html`<p class="sq-blocked-note" role="note">${mode.blockedNotice}</p>`}
      </section>

      <section class="form-block fields-block">
        <div class="block-title">
          <p class="eyebrow">筛选</p>
          <h4>查询字段</h4>
        </div>
        ${fieldGroup.length === 0 && html`<p class="vk-muted">该模式没有筛选字段。</p>`}
        <div class="aras-fields" data-mode-fields=${mode.fieldGroup}>
          ${fieldGroup.map((field) => html`<${Field} key=${field.name} field=${field} value=${values[field.name]}
            error=${fieldErrors[field.name]} onInput=${setGroupValue}>
            ${field.carTypeProject && html`<${CarTypeProjects} state=${carTypes} selectedId=${values.car_type_project_id}
              onLoad=${loadCarTypes} onSelect=${selectCarType} />`}
          </${Field}>`)}
          ${mode.system === "tdc" && TDC_OPERATION_FIELDS.map((field) => html`<${Field} key=${field.name} field=${field}
            value=${values[field.name]} error=${fieldErrors[field.name]} onInput=${setGroupValue} />`)}
          ${mode.previewSource && html`<label for="sq-field-preview_source">
            <span>查询模式</span>
            <select id="sq-field-preview_source" name="preview_source" value=${values.preview_source || "list_endpoint"}
              onChange=${(event) => setGroupValue("preview_source", event.currentTarget.value)}>
              ${TDC_PREVIEW_SOURCES.map((option) => html`<option key=${option.value} value=${option.value}>${option.label}</option>`)}
            </select>
          </label>`}
          ${mode.system === "tdc" && html`<${Field} field=${{ name: "file_name", label: "XLSX 文件名（导出）", type: "text" }}
            value=${values.file_name} error=${fieldErrors.file_name} onInput=${setGroupValue} />`}
        </div>
      </section>

      <section class="form-block actions-block">
        <button class="primary-btn" type="submit" data-action="query" disabled=${busy}>${mode.submitLabel || "执行查询"}</button>
        ${mode.crawlAllEndpoint && html`<button class="primary-btn" type="button" data-action="crawl_all" disabled=${busy}
          onClick=${() => run("crawl_all")}>${mode.crawlAllLabel || "获取全部结果"}</button>`}
        ${(mode.exportEndpoint || mode.downloadEndpoint) && html`<button class="primary-btn" type="button" data-action="export"
          disabled=${busy} onClick=${() => run("export")}>${mode.exportLabel || "导出"}</button>`}
        ${mode.xmlCapture && html`<label class="xml-capture-toggle">
          <input type="checkbox" checked=${includeXml} onChange=${(event) => setIncludeXml(event.currentTarget.checked)} />
          <span>保存 Aras XML（请求 + 返回）</span>
        </label>`}
        ${xml && xml.modeId === modeId && html`<div class="xml-capture-actions" aria-live="polite">
          <span class="xml-capture-label">XML 取证：</span>
          <button class="secondary-btn" type="button" disabled=${busy} onClick=${() => downloadXml("request")}>下载请求 XML</button>
          <button class="secondary-btn" type="button" disabled=${busy} onClick=${() => downloadXml("response")}>下载返回 XML</button>
        </div>`}
        <span class=${`sq-status${busy ? " loading" : ""}`} aria-live="polite">${statusText}</span>
      </section>
    </form>

    <${TaskStrip} task=${task} onCancel=${cancelTask} />

    <section class=${`result-panel${shownResult || card ? " has-output" : ""}${busy ? " sq-running" : ""}`} aria-live="polite">
      <div class="result-head">
        <p class="eyebrow">结果</p>
        <span class="sq-result-kind">${shownResult ? (RESULT_KIND_LABELS[mode.resultKind] || mode.resultKind) : "就绪"}</span>
      </div>
      ${card && html`<${ErrorCard} card=${card} />`}
      ${warning && html`<div class="error-msg sq-warning" role="status">${warning}</div>`}
      ${contextNote && html`<div class="deliverable-preview-context">${contextNote}</div>`}
      ${!shownResult && html`<div class="is-empty">暂无结果</div>`}
      ${shownResult && html`<div class="result-output-content">
        <p class="result-output-meta">${COMMAND_LABELS[modeId]} -> ${mode.endpoint}</p>
        <p class="result-output-meta">预览生成时间：${shownResult.at} · 筛选条件：${shownResult.summary}</p>
        ${mode.resultKind === "rows" ? html`
          <p class="result-meta">${resultMetaText(modeId, shownResult.data)}</p>
          ${serialNotice && html`<p class="result-meta result-warning" role="status">${serialNotice}</p>`}
          ${shownResult.data.mappingComplete === false && Array.isArray(shownResult.data.unmappedColumns)
            && shownResult.data.unmappedColumns.length > 0 && html`<p class="result-meta result-warning">
              ${mode.system === "tdc"
                ? `列表接口尚未提供 ${shownResult.data.unmappedColumns.length} 个官方导出列，已保留为空值；请使用官方导出预览。`
                : `当前接口尚未提供 ${shownResult.data.unmappedColumns.length} 个工作簿派生列，已保留为空值；请使用官方导出获取完整报表。`}
            </p>`}
          ${shownResult.data.queryState === "empty" || resultRowCount(shownResult.data) === 0
            ? html`<${EmptyNotice} title="未查询到符合条件的记录"
                desc="当前筛选条件下未返回任何数据记录。原表单查询条件已完好保留，您可以调整筛选条件后重新查询。" />`
            : html`<${DataGrid} key=${shownResult.key} data=${shownResult.data} modeId=${modeId} preferredColumns=${mode.preferredColumns} />`}
        ` : html`<${SummaryTable} data=${shownResult.data} />`}
      </div>`}
    </section>
  </div>`;
}
