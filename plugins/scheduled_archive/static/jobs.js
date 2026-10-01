// 自动下载与留存：定时归档任务管理（插件化页面）。
// 读写都走现有 /api/scheduled-archive/* 接口；写接口由服务端做本机访问保护。
import { html, useCallback, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { api, ApiError } from "/static/host/api.js";
import { DataTable, StateBlock, useStylesheet } from "/static/host/kit.js";
import * as D from "./archive_data.js";

const POLL_INTERVAL_MS = 5000;
const POLL_MAX_ROUNDS = 60; // 最多轮询 5 分钟，避免无限请求
const HISTORY_LIMIT = 50;
const LOGIN_NOTICE = "请输入企业域账号登录并勾选保存至凭据保护库；完成后重新执行。";

/**
 * Write helper: like api() but keeps the 422 `error.fields` map, which the
 * host client drops, so per-field validation messages can be shown.
 */
async function send(path, method, body) {
  const init = { method, headers: { Accept: "application/json" } };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch (_) {
    throw new ApiError("网络异常或服务器未响应");
  }
  let payload = null;
  try {
    payload = await response.json();
  } catch (_) {
    payload = null;
  }
  if (payload && payload.ok === true) return payload.data;
  const error = (payload && payload.error) || {};
  const failure = new ApiError(error.message || `请求失败（HTTP ${response.status}）`, {
    status: response.status,
    type: error.type || "http",
    code: error.code || null,
  });
  failure.fields = error.fields && typeof error.fields === "object" ? error.fields : null;
  throw failure;
}

const jobPath = (jobKey) => `${D.API_BASE}/jobs/${encodeURIComponent(jobKey)}`;

function Chip({ info }) {
  return html`<span class=${`sa-chip ${info.tone || ""}`}>${info.text}</span>`;
}

function LoginButton() {
  if (typeof window === "undefined" || typeof window.openInPlaceLogin !== "function") return null;
  return html`<button type="button" class="vk-btn" onClick=${() => window.openInPlaceLogin({ notice: LOGIN_NOTICE })}>重新登录</button>`;
}

/** Error/notice line; offers the in-place login when the failure is an auth one. */
function Notice({ kind = "error", message, remedy, auth }) {
  if (!message) return null;
  const hint = D.remedyText(remedy);
  return html`<div class=${`sa-notice is-${kind}`} role=${kind === "error" ? "alert" : "status"}>
    <span>${message}${hint ? html`<span class="sa-remedy">建议：${hint}</span>` : null}</span>
    ${auth ? html`<${LoginButton} />` : null}
  </div>`;
}

function JobList({ jobs, selectedKey, onSelect, onDelete, busy }) {
  if (!jobs.length) return html`<${StateBlock} empty=${true} emptyText="暂无自动下载任务" />`;
  return html`<div class="sa-job-list">
    ${jobs.map((job) => {
      const active = job.jobKey === selectedKey;
      return html`<article key=${job.jobKey} data-job=${job.jobKey}
        class=${`sa-job${active ? " is-active" : ""}${job.enabled ? "" : " is-disabled"}`}>
        <button type="button" class="sa-job-select" aria-pressed=${active ? "true" : "false"} onClick=${() => onSelect(job.jobKey)}>
          <span class="sa-job-head">
            <span class="sa-job-title">${D.jobTitle(job)}</span>
            <${Chip} info=${D.freshnessChip(job.freshness)} />
          </span>
          <span class="sa-job-meta">${D.sourceLabel(job.sourceType)}${job.deliverableId ? ` · 关联交付物 ${job.deliverableId}` : ""}</span>
          <span class="sa-chip-row">
            <${Chip} info=${{ text: job.enabled ? "已启用" : "未启用", tone: job.enabled ? "is-success" : "is-muted" }} />
            <${Chip} info=${D.credentialStatus(job)} />
            <${Chip} info=${D.syncStateChip(job.syncState)} />
          </span>
        </button>
        <div class="sa-job-actions">
          <button type="button" class="sa-link-danger" disabled=${busy}
            title=${job.builtin ? "删除内置任务并保留历史运行记录" : "删除自定义任务并保留历史运行记录"}
            onClick=${() => onDelete(job)}>删除任务</button>
        </div>
      </article>`;
    })}
  </div>`;
}

function CreatePanel({ jobs, sourceJob, onClose, onCreated }) {
  const initialTemplate = (sourceJob && sourceJob.templateKey) || D.TEMPLATES[0].key;
  const [source, setSource] = useState(D.sourceOfTemplate(initialTemplate));
  const [templateKey, setTemplateKey] = useState(initialTemplate);
  const [name, setName] = useState(sourceJob ? `${sourceJob.displayName || sourceJob.jobKey} (副本)` : "");
  const [copyFrom, setCopyFrom] = useState(sourceJob ? sourceJob.jobKey : "");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const closeRef = useRef(null);
  useEffect(() => {
    if (closeRef.current) closeRef.current.focus();
  }, []);
  const copySources = D.copySourcesFor(jobs, templateKey);

  const chooseSource = (key) => {
    setSource(key);
    const first = D.templatesForSource(key)[0];
    setTemplateKey(first ? first.key : "");
    setCopyFrom("");
  };
  const chooseTemplate = (key) => {
    setTemplateKey(key);
    setCopyFrom(sourceJob && sourceJob.templateKey === key ? sourceJob.jobKey : "");
  };

  const submit = async (event) => {
    event.preventDefault();
    const built = D.buildCreatePayload({ templateKey, displayName: name, copyFromJobKey: copyFrom });
    if (built.error) {
      setError(built.error);
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const data = await send(`${D.API_BASE}/jobs`, "POST", built.payload);
      onCreated(data, built.payload.displayName);
    } catch (err) {
      setError(err.fields ? D.fieldErrorList(err.fields).join("；") : err.message);
      setSubmitting(false);
    }
  };

  return html`<div class="sa-create" onKeyDown=${(event) => event.key === "Escape" && onClose()}>
    <div class="sa-create-head">
      <div>
        <h4>${sourceJob ? "复制定时任务" : "创建定时任务"}</h4>
        <p class="vk-muted">选择核准的定时任务模板</p>
      </div>
      <button type="button" class="vk-btn" ref=${closeRef} onClick=${onClose}>关闭</button>
    </div>
    <form class="sa-create-form" onSubmit=${submit}>
      <span class="sa-label">第一层：选择系统</span>
      <div class="sa-seg">
        ${D.SOURCE_CHOICES.map((choice) => html`<button type="button" key=${choice.key}
          class=${`vk-btn${choice.key === source ? " is-primary" : ""}`} onClick=${() => chooseSource(choice.key)}>${choice.label}</button>`)}
      </div>
      <span class="sa-label">第二层：选择报表</span>
      <div class="sa-seg">
        ${D.templatesForSource(source).map((tpl) => html`<button type="button" key=${tpl.key}
          class=${`vk-btn${tpl.key === templateKey ? " is-primary" : ""}`} onClick=${() => chooseTemplate(tpl.key)}>${tpl.name}</button>`)}
      </div>
      <label class="sa-field">
        <span>任务显示名称</span>
        <input type="text" name="displayName" required value=${name} placeholder="例如：Aras EWO 每日自动留存"
          onInput=${(event) => setName(event.currentTarget.value)} />
      </label>
      ${jobs.length > 0 && html`<label class="sa-field">
        <span>复制现有任务配置（可选）</span>
        <select name="copyFrom" value=${copyFrom} onChange=${(event) => setCopyFrom(event.currentTarget.value)}>
          <option value="">不复制（使用模板默认配置）</option>
          ${copySources.map((job) => html`<option key=${job.jobKey} value=${job.jobKey}>${job.displayName || job.jobKey} (${job.jobKey})</option>`)}
        </select>
      </label>`}
      <${Notice} message=${error} />
      <div class="sa-actions">
        <button type="submit" class="vk-btn is-primary" disabled=${submitting}>${submitting ? "创建中..." : "创建任务"}</button>
        <button type="button" class="vk-btn" onClick=${onClose}>取消</button>
      </div>
    </form>
  </div>`;
}

function FilterEditor({ job, form, setForm, planName }) {
  const fields = D.filterFieldsFor(job);
  const allowed = Array.isArray(job.allowedFilterNames) ? job.allowedFilterNames : [];

  const setInput = (name, value) => {
    setForm((prev) => {
      const inputs = { ...prev.filterInputs, [name]: value };
      const parsed = D.parseFiltersJson(prev.filtersJson);
      const merged = D.mergeFieldFilters(fields, inputs, parsed.filters || {});
      return { ...prev, filterInputs: inputs, filtersJson: JSON.stringify(merged, null, 2) };
    });
  };
  const setJson = (text) => {
    setForm((prev) => {
      const parsed = D.parseFiltersJson(text);
      const inputs = parsed.filters ? D.filterInputs(fields, parsed.filters) : prev.filterInputs;
      return { ...prev, filtersJson: text, filterInputs: inputs };
    });
  };

  return html`<details class="sa-details">
    <summary>高级下载条件</summary>
    <div class="sa-allowed">
      <span class="sa-label">接口字段（高级信息）</span>
      <div class="sa-tags">${allowed.length ? allowed.map((name) => html`<span key=${name} class="sa-tag">${name}</span>`) : html`<span class="sa-tag">无</span>`}</div>
    </div>
    <p class="sa-label">常用筛选条件</p>
    ${fields.length === 0
      ? html`<p class="vk-muted">此任务模板没有可配置的筛选条件</p>`
      : html`<div class="sa-filter-grid">
        ${fields.map((field) => {
          const project = Boolean(planName) && D.PROJECT_FILTER_KEYS.has(field.name);
          return html`<label key=${field.name} class="sa-field">
            <span>${field.label || field.name}</span>
            <input type=${field.type === "date" ? "date" : "text"} name=${`archive-filter-${field.name}`}
              value=${form.filterInputs[field.name] || ""}
              placeholder=${project ? D.PROJECT_FILTER_HINT : field.placeholder || "可选"}
              title=${project ? `默认与主计划名称同步；${D.PROJECT_FILTER_HINT}` : field.list ? "多个值请用逗号分隔" : "留空表示不筛选"}
              onInput=${(event) => setInput(field.name, event.currentTarget.value)} />
          </label>`;
        })}
      </div>`}
    <details class="sa-details is-nested">
      <summary>高级 JSON（兼容旧配置）</summary>
      <label class="sa-field">
        <span>下载条件 JSON</span>
        <textarea rows="5" name="filters" value=${form.filtersJson} onInput=${(event) => setJson(event.currentTarget.value)}></textarea>
      </label>
    </details>
  </details>`;
}

function JobConfig({ job, vaultConfigured, planName, busy, setBusy, notice, setNotice, onStatus, onSaved, onDelete, onCopy, onSynced }) {
  const [form, setForm] = useState(() => D.initialForm(job, vaultConfigured));
  const [errors, setErrors] = useState(null);
  const [status, setStatus] = useState("");
  const [folderNotice, setFolderNotice] = useState("");
  const [action, setAction] = useState(""); // "save" | "sync" | "folder"
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  // 车型项目类字段未显式配置时默认填入主计划名称（与旧页面一致）。
  useEffect(() => {
    const fields = D.filterFieldsFor(job);
    setForm((prev) => {
      const next = D.planNamePrefill(fields, job.filters, prev.filterInputs, planName);
      if (!next) return prev;
      const parsed = D.parseFiltersJson(prev.filtersJson);
      const merged = D.mergeFieldFilters(fields, next, parsed.filters || {});
      return { ...prev, filterInputs: next, filtersJson: JSON.stringify(merged, null, 2) };
    });
  }, [planName, job]);

  // 凭据保护库状态晚到时补上默认预选。
  useEffect(() => {
    setForm((prev) => (prev.credentialRef ? prev : { ...prev, credentialRef: D.defaultCredentialRef(job, vaultConfigured) }));
  }, [vaultConfigured, job]);

  const update = (patch) => setForm((prev) => ({ ...prev, ...patch }));

  const save = async (event) => {
    event.preventDefault();
    if (busy) return;
    setErrors(null);
    const built = D.buildUpdatePayload(job, form);
    if (built.errors) {
      setErrors(built.errors);
      return;
    }
    setBusy(true);
    setAction("save");
    onStatus("");
    setStatus("正在提交修改...");
    try {
      await send(jobPath(job.jobKey), "PATCH", built.payload);
      // 保存成功后本组件会按新的 updatedAt 重建（凭据引用 write-only 清空），提示交给页面级状态。
      await onSaved("设置已保存");
    } catch (err) {
      if (!alive.current) return;
      setErrors(err.fields || { error: err.message });
      setStatus("保存失败");
      update({ clearCredential: false });
    } finally {
      if (alive.current) setAction("");
      setBusy(false);
    }
  };

  const syncNow = async () => {
    if (busy) return;
    setBusy(true);
    setAction("sync");
    setNotice(null);
    setStatus("正在下载...");
    try {
      const data = await send(`${jobPath(job.jobKey)}/sync-now`, "POST");
      const result = D.summarizeSyncResult(data, job.jobKey);
      setNotice(result.ok
        ? { jobKey: job.jobKey, kind: "success", message: "下载已完成，记录已更新" }
        : {
          jobKey: job.jobKey,
          kind: "error",
          message: `下载未完成：${result.message}`,
          remedy: result.remedy,
          auth: D.isAuthFailure(result),
        });
      if (alive.current) setStatus("");
      await onSynced();
    } catch (err) {
      if (alive.current) setStatus("");
      setNotice({ jobKey: job.jobKey, kind: "error", message: `下载失败：${err.message}`, auth: D.isAuthFailure({ status: err.status }) });
    } finally {
      if (alive.current) setAction("");
      setBusy(false);
    }
  };

  const pickFolder = async () => {
    setAction("folder");
    setFolderNotice("");
    try {
      const data = await send(`${D.API_BASE}/folders/native`, "POST", { path: form.outputDirectory.trim() });
      if (!alive.current) return;
      if (data && typeof data.path === "string") update({ outputDirectory: data.path });
    } catch (err) {
      if (!alive.current) return;
      setFolderNotice(err.status === 503
        ? "Windows 文件夹选择器不可用，请直接输入本机绝对目录路径后保存"
        : err.message || "无法打开文件夹选择器");
    } finally {
      if (alive.current) setAction("");
    }
  };

  const lastErrorRemedy = D.remedyFor(null, job.lastErrorType);
  const title = D.jobTitle(job);
  const jobNotice = notice && notice.jobKey === job.jobKey ? notice : null;

  return html`<article class="sa-card" data-job-config=${job.jobKey}>
    <div class="sa-card-head">
      <div>
        <p class="sa-eyebrow">${D.sourceLabel(job.sourceType, "业务系统")}</p>
        <h3>${title}</h3>
        <p class="vk-muted">${job.displayName && job.displayName !== title ? `${job.displayName} · ` : ""}${job.jobKey}</p>
      </div>
      <div class="sa-chip-row">
        <${Chip} info=${D.freshnessChip(job.freshness)} />
        <${Chip} info=${D.syncStateChip(job.syncState)} />
      </div>
    </div>

    <dl class="sa-banner">
      <div><dt>最近下载状态</dt><dd>${D.syncStateLabel(job.syncState)}</dd></div>
      <div><dt>自动执行频率</dt><dd>${D.intervalText(job)}</dd></div>
      <div><dt>最近成功</dt><dd>${D.formatDate(job.lastSuccessAt)}</dd></div>
      <div><dt>最近尝试</dt><dd>${D.formatDate(job.lastAttemptAt)}</dd></div>
      <div><dt>失败后重试</dt><dd>${D.retryText(job)}</dd></div>
      ${job.lastErrorMessage && html`<div class="is-wide"><dt>最近安全错误</dt><dd>${job.lastErrorType || "未知类型"}: ${job.lastErrorMessage}</dd></div>`}
    </dl>
    ${job.lastErrorMessage && lastErrorRemedy && html`<${Notice} kind="warning"
      message="上次运行未成功" remedy=${lastErrorRemedy}
      auth=${D.isAuthFailure({ errorType: job.lastErrorType })} />`}

    <form class="sa-form" autocomplete="off" onSubmit=${save}>
      <label class="sa-check is-wide">
        <input type="checkbox" name="enabled" checked=${form.enabled} onChange=${(event) => update({ enabled: event.currentTarget.checked })} />
        <span>${job.builtin ? "启用自动下载（内置任务可禁用）" : "启用自动下载"}</span>
      </label>
      <label class="sa-field">
        <span>自动执行频率（分钟）</span>
        <input type="number" name="intervalMinutes" min="5" max="10080" value=${form.intervalMinutes}
          onInput=${(event) => update({ intervalMinutes: event.currentTarget.value })} />
      </label>
      <label class="sa-field">
        <span>失败后最多尝试次数</span>
        <input type="number" name="retryMaxAttempts" min="1" max="2" value=${form.retryMaxAttempts}
          title="1 表示失败不重试，2 表示失败后重试 1 次"
          onInput=${(event) => update({ retryMaxAttempts: event.currentTarget.value })} />
      </label>
      <label class="sa-field">
        <span>定时登录信息</span>
        <select name="credentialRef" value=${form.credentialRef} onChange=${(event) => update({ credentialRef: event.currentTarget.value })}>
          <option value="">${job.credentialConfigured ? "保持当前登录信息（不修改）" : "请选择统一域账号登录信息"}</option>
          ${D.CREDENTIAL_OPTIONS.map((opt) => html`<option key=${opt.value} value=${opt.value}>${opt.label}</option>`)}
        </select>
        <small class="vk-muted">先到系统设置登录并勾选“保存至凭据保护库”；此处选择引用，不填写用户名或密码。</small>
      </label>
      <label class="sa-check">
        <input type="checkbox" name="clearAlias" checked=${form.clearCredential} onChange=${(event) => update({ clearCredential: event.currentTarget.checked })} />
        <span>清除已保存的定时登录信息</span>
      </label>
      <div class="sa-field is-wide">
        <span>归档目录</span>
        <div class="sa-dir">
          <input type="text" name="outputDirectory" value=${form.outputDirectory}
            placeholder="例如：D:\\VSE\\archive（留空使用系统默认归档目录）"
            title="选择的文件夹将直接作为此任务的归档目录"
            onInput=${(event) => update({ outputDirectory: event.currentTarget.value })} />
          <button type="button" class="vk-btn" disabled=${action === "folder"} onClick=${pickFolder}>Windows 选择文件夹</button>
          <button type="button" class="vk-btn" onClick=${() => { update({ outputDirectory: "" }); setFolderNotice(""); }}>使用系统默认</button>
        </div>
        <small class="vk-muted">Windows 选择哪个文件夹，就直接使用哪个文件夹；留空则使用系统设置中的全局归档目录。</small>
        ${!job.outputDirectory && job.outputSubdir && html`<small class="vk-muted">兼容旧版配置：当前还使用全局目录下的子目录“${job.outputSubdir}”；选择新目录后将替换它。</small>`}
        <${Notice} message=${folderNotice} />
      </div>
      <div class="is-wide">
        <${FilterEditor} job=${job} form=${form} setForm=${setForm} planName=${planName} />
      </div>
      ${errors && html`<div class="sa-notice is-error is-wide" role="alert">
        <ul>${D.fieldErrorList(errors).map((line) => html`<li key=${line}>${line}</li>`)}</ul>
        ${errors.credentialRef ? html`<${LoginButton} />` : null}
      </div>`}
      <div class="sa-actions is-wide">
        <button type="submit" class="vk-btn is-primary" disabled=${busy}>${action === "save" ? "保存中..." : "保存设置"}</button>
        <button type="button" class="vk-btn" onClick=${() => onCopy(job)}>复制任务</button>
        <button type="button" class="vk-btn sa-danger" disabled=${busy} onClick=${() => onDelete(job)}>删除任务</button>
        <button type="button" class="vk-btn" disabled=${busy || !D.canSyncNow(job)}
          title=${D.canSyncNow(job) ? "" : "需先启用任务并配置可用的登录信息"}
          onClick=${syncNow}>${action === "sync" ? "下载中..." : "立即下载一次"}</button>
        <span class="sa-status" aria-live="polite">${status}</span>
      </div>
      ${jobNotice && html`<div class="is-wide"><${Notice} kind=${jobNotice.kind} message=${jobNotice.message} remedy=${jobNotice.remedy} auth=${jobNotice.auth} /></div>`}
    </form>
  </article>`;
}

const ARTIFACT_COLUMNS = [
  { key: "artifactType", title: "类型", format: (value) => value || "未知" },
  { key: "displayName", title: "显示名称", format: (value) => value || "-" },
  { key: "sizeBytes", title: "大小", format: (value) => D.formatBytes(value) },
  { key: "sha256", title: "SHA-256", sortable: false, format: (value) => (value ? `${String(value).slice(0, 12)}...` : "-") },
  { key: "relativePath", title: "相对路径", format: (value) => value || "-" },
  { key: "createdAt", title: "生成时间", format: (value) => D.formatDate(value) },
];

function Artifacts({ runId, onClose }) {
  const [state, setState] = useState({ loading: true, error: null, rows: [] });
  useEffect(() => {
    const controller = new AbortController();
    setState({ loading: true, error: null, rows: [] });
    api(`${D.API_BASE}/runs/${encodeURIComponent(runId)}/artifacts`, { signal: controller.signal }).then(
      (data) => setState({ loading: false, error: null, rows: Array.isArray(data && data.artifacts) ? data.artifacts : [] }),
      (error) => error.name !== "AbortError" && setState({ loading: false, error, rows: [] }),
    );
    return () => controller.abort();
  }, [runId]);
  return html`<div class="sa-artifacts">
    <div class="sa-toolbar">
      <strong>已保存文件 · 记录 #${runId}</strong>
      <button type="button" class="vk-btn" onClick=${onClose}>收起</button>
    </div>
    ${state.loading || state.error
      ? html`<${StateBlock} loading=${state.loading} error=${state.error} />`
      : html`<${DataTable} columns=${ARTIFACT_COLUMNS} rows=${state.rows} emptyText="本次下载没有生成文件" />`}
  </div>`;
}

function useHistory(kind, jobKey, token) {
  const [state, setState] = useState({ loading: true, error: null, rows: [] });
  const [reloadToken, setReloadToken] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState((prev) => ({ ...prev, loading: true, error: null }));
    const path = kind === "runs" ? `${D.API_BASE}/runs` : `${D.API_BASE}/config-audit`;
    api(path, { query: { jobKey, limit: HISTORY_LIMIT }, signal: controller.signal }).then(
      (data) => setState({ loading: false, error: null, rows: Array.isArray(data) ? data : [] }),
      (error) => error.name !== "AbortError" && setState({ loading: false, error, rows: [] }),
    );
    return () => controller.abort();
  }, [kind, jobKey, token, reloadToken]);
  const reload = useCallback(() => setReloadToken((value) => value + 1), []);
  return { ...state, reload };
}

function HistoryBody({ history, emptyText, errorSuffix = "", children }) {
  if (history.error) {
    return html`<${StateBlock} error=${new Error(`${history.error.message}${errorSuffix}`)} onRetry=${history.reload} />`;
  }
  if (history.loading && !history.rows.length) return html`<${StateBlock} loading=${true} />`;
  if (!history.rows.length) return html`<${StateBlock} empty=${true} emptyText=${emptyText} />`;
  return children;
}

function RunsPanel({ jobKey, token }) {
  const runs = useHistory("runs", jobKey, token);
  const [runId, setRunId] = useState(null);
  useEffect(() => setRunId(null), [jobKey, token]);
  return html`<div class="sa-history-panel">
    <div class="sa-toolbar">
      <span class="sa-label">最近运行</span>
      <button type="button" class="vk-btn" onClick=${() => { setRunId(null); runs.reload(); }}>刷新历史</button>
    </div>
    <${HistoryBody} history=${runs} emptyText="暂无下载记录" errorSuffix="（后台归档不受影响，可点击重试）">
      <div class="sa-runs">${runs.rows.map((run) => {
        const records = typeof run.recordCount === "number" ? ` | ${run.recordCount} 条记录` : "";
        const hint = D.remedyText(D.remedyFor(null, run.errorType));
        return html`<div key=${run.id} class=${`sa-run${runId === run.id ? " is-active" : ""}`}>
          <div class="sa-run-head">
            <strong>#${run.id} - ${D.JOB_NAMES[run.jobKey] || run.jobKey}</strong>
            <${Chip} info=${D.runStateChip(run.runState)} />
          </div>
          <div class="vk-muted">${D.triggerLabel(run.triggerType)} | 开始: ${D.formatDate(run.startedAt || run.createdAt)} | 完成: ${D.formatDate(run.finishedAt)}${records}</div>
          ${run.resultSummary && html`<div class="sa-run-line">摘要: ${run.resultSummary}</div>`}
          ${run.errorMessage && html`<div class="sa-run-line is-error">错误 (${run.errorType || "未知类型"}): ${run.errorMessage}${hint ? ` — 建议：${hint}` : ""}</div>`}
          <button type="button" class="vk-btn sa-run-btn" onClick=${() => setRunId(runId === run.id ? null : run.id)}>${runId === run.id ? "收起文件" : "查看已保存文件"}</button>
        </div>`;
      })}</div>
    </${HistoryBody}>
    ${runId !== null && html`<${Artifacts} runId=${runId} onClose=${() => setRunId(null)} />`}
  </div>`;
}

function AuditPanel({ jobKey, token }) {
  const audit = useHistory("audit", jobKey, token);
  return html`<div class="sa-history-panel">
    <div class="sa-toolbar">
      <span class="sa-label">设置变更记录</span>
      <button type="button" class="vk-btn" onClick=${audit.reload}>刷新记录</button>
    </div>
    <${HistoryBody} history=${audit} emptyText="暂无设置变更记录">
      <div class="sa-runs">${audit.rows.map((record) => html`<div key=${record.id} class="sa-run">
        <div class="sa-run-head">
          <strong>${D.JOB_NAMES[record.jobKey] || record.jobKey} - ${record.eventType || "待确认/未知"}</strong>
          <span class="vk-muted">操作者: ${record.actor || "待确认/未知"}</span>
        </div>
        <div class="vk-muted">时间: ${D.formatDate(record.createdAt)}</div>
        ${record.changes && typeof record.changes === "object" && html`<pre class="sa-pre">${JSON.stringify(record.changes, null, 2)}</pre>`}
      </div>`)}</div>
    </${HistoryBody}>
  </div>`;
}

function History({ jobKey, token }) {
  const [tab, setTab] = useState("runs");
  const tabButton = (id, label) => html`<button type="button" role="tab"
    class=${`sa-tab${tab === id ? " is-active" : ""}`} aria-selected=${tab === id ? "true" : "false"}
    onClick=${() => setTab(id)}>${label}</button>`;
  return html`<section class="sa-card sa-history" aria-label="下载记录与设置变更记录">
    <div class="sa-tabs" role="tablist">${tabButton("runs", "下载记录")}${tabButton("audit", "设置变更记录")}</div>
    ${tab === "runs" ? html`<${RunsPanel} jobKey=${jobKey} token=${token} />` : html`<${AuditPanel} jobKey=${jobKey} token=${token} />`}
  </section>`;
}

function readHashJob() {
  return typeof location === "undefined" ? "" : D.jobFromHash(location.hash);
}

/** `?job=<key>` from `#p/scheduled-archive/jobs?job=<key>`, kept in sync on hashchange. */
function useHashJob() {
  const [jobKey, setJobKey] = useState(readHashJob);
  useEffect(() => {
    const onHash = () => setJobKey(readHashJob());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  return jobKey;
}

export default function JobsPage({ plugin }) {
  useStylesheet(`/plugins/${plugin.id}/static/jobs.css`);
  const requestedKey = useHashJob();
  const [jobs, setJobs] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [globalError, setGlobalError] = useState("");
  const [globalStatus, setGlobalStatus] = useState("");
  const [jobNotice, setJobNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(null); // null | {sourceJob}
  const [vaultConfigured, setVaultConfigured] = useState(null);
  const [planName, setPlanName] = useState("");
  const [historyToken, setHistoryToken] = useState(0);
  const alive = useRef(true);
  const loadSeq = useRef(0);
  useEffect(() => () => { alive.current = false; }, []);

  const loadJobs = useCallback(async ({ quiet = false } = {}) => {
    const seq = ++loadSeq.current;
    if (!quiet) setLoading(true);
    try {
      const data = await api(`${D.API_BASE}/jobs`);
      if (!alive.current || seq !== loadSeq.current) return;
      setJobs(Array.isArray(data) ? data : []);
      setLoadError(null);
    } catch (error) {
      if (!alive.current || seq !== loadSeq.current) return;
      setLoadError(error);
    } finally {
      if (alive.current && seq === loadSeq.current) setLoading(false);
    }
  }, []);

  const refreshAll = useCallback(async () => {
    await loadJobs({ quiet: true });
    if (alive.current) setHistoryToken((value) => value + 1);
  }, [loadJobs]);

  useEffect(() => {
    loadJobs();
    // 凭据保护库状态与主计划名称只用于默认值，失败不影响页面。
    api("/api/settings").then(
      (data) => alive.current && setVaultConfigured(Boolean(data && data.credentialVaultConfigured)),
      () => alive.current && setVaultConfigured(false),
    );
    api("/api/project-status", { query: { phase: "VPI-T2" } }).then(
      (data) => alive.current && setPlanName(String((data && data.phase && data.phase.displayName) || "").trim()),
      () => {},
    );
  }, [loadJobs]);

  // 有任务处于「同步中」时有界轮询，结束、超出轮数或卸载即停止。
  const running = D.anyJobRunning(jobs);
  useEffect(() => {
    if (!running) return undefined;
    let rounds = 0;
    const timer = setInterval(() => {
      rounds += 1;
      if (rounds > POLL_MAX_ROUNDS) {
        clearInterval(timer);
        return;
      }
      loadJobs({ quiet: true });
    }, POLL_INTERVAL_MS);
    return () => {
      clearInterval(timer);
      if (alive.current) setHistoryToken((value) => value + 1);
    };
  }, [running, loadJobs]);

  const list = jobs || [];
  const selected = D.pickSelectedJob(list, requestedKey);
  const selectedKey = selected ? selected.jobKey : "";

  const select = (jobKey) => {
    if (jobKey !== requestedKey) location.hash = D.jobHash(jobKey);
  };

  const remove = async (job) => {
    if (busy) return;
    const name = job.displayName || job.jobKey;
    const kind = job.builtin ? "内置任务" : "自定义任务";
    if (!window.confirm(`确定要删除${kind}“${name}”吗？历史运行记录会保留。`)) return;
    setBusy(true);
    setGlobalError("");
    setGlobalStatus("正在删除任务...");
    try {
      await send(jobPath(job.jobKey), "DELETE", { updatedAt: job.updatedAt });
      if (!alive.current) return;
      setGlobalStatus("任务已删除，历史运行记录已保留");
      if (job.jobKey === selectedKey && requestedKey) location.hash = D.jobHash("");
      await refreshAll();
    } catch (err) {
      if (!alive.current) return;
      setGlobalStatus("");
      setGlobalError(err.fields ? D.fieldErrorList(err.fields).join("；") : err.message);
    } finally {
      setBusy(false);
    }
  };

  const onCreated = async (data, displayName) => {
    setCreating(null);
    setGlobalError("");
    setGlobalStatus(`任务 "${displayName}" 创建成功`);
    await loadJobs({ quiet: true });
    if (data && data.jobKey) select(data.jobKey);
  };

  const onSaved = async (message) => {
    setGlobalError("");
    setGlobalStatus(message);
    await refreshAll();
  };

  const header = html`<header class="vk-page-header">
    <div>
      <p class="sa-eyebrow">自动同步</p>
      <h2>定时任务</h2>
      <p class="vk-muted sa-purpose">定期自动获取业务数据并安全留存至指定目录，方便随时查看历史记录与配置变更。本页负责原始报表的自动下载归档；项目状态的自动同步在交付物明细页配置。</p>
    </div>
    <div class="vk-page-actions">
      <button type="button" class="vk-btn" disabled=${loading}
        onClick=${() => { setGlobalError(""); setGlobalStatus(""); loadJobs(); setHistoryToken((v) => v + 1); }}>刷新任务</button>
    </div>
  </header>`;

  if (!jobs) {
    return html`<div class="vk-page sa-page">${header}
      <${StateBlock} loading=${loading} error=${loadError} onRetry=${() => loadJobs()} />
    </div>`;
  }

  return html`<div class="vk-page sa-page">
    ${header}
    ${loadError && html`<${Notice} message=${`刷新任务失败：${loadError.message}`} />`}
    <${Notice} message=${globalError} />
    ${globalStatus && html`<div class="sa-status sa-global-status" aria-live="polite">${globalStatus}</div>`}
    ${requestedKey && list.length > 0 && requestedKey !== selectedKey && html`<${Notice} kind="warning" message=${`未找到任务 ${requestedKey}，已显示第一个任务`} />`}
    <div class="sa-layout">
      <aside class="sa-card sa-jobs" aria-label="自动下载任务列表">
        <div class="sa-toolbar">
          <h4>自动下载任务</h4>
          <button type="button" class="vk-btn" onClick=${() => setCreating({ sourceJob: null })}>新建任务</button>
        </div>
        ${creating && html`<${CreatePanel} key=${creating.sourceJob ? creating.sourceJob.jobKey : "new"}
          jobs=${list} sourceJob=${creating.sourceJob} onClose=${() => setCreating(null)} onCreated=${onCreated} />`}
        <${JobList} jobs=${list} selectedKey=${selectedKey} onSelect=${select} onDelete=${remove} busy=${busy} />
      </aside>
      <div class="sa-detail">
        ${selected
          ? html`<${JobConfig} key=${`${selected.jobKey}@${selected.updatedAt}`} job=${selected}
              vaultConfigured=${vaultConfigured} planName=${planName} busy=${busy} setBusy=${setBusy}
              notice=${jobNotice} setNotice=${setJobNotice} onStatus=${setGlobalStatus}
              onSaved=${onSaved} onDelete=${remove}
              onCopy=${(job) => setCreating({ sourceJob: job })}
              onSynced=${refreshAll} />
            <${History} jobKey=${selected.jobKey} token=${historyToken} />`
          : html`<${StateBlock} empty=${true} emptyText="请选择自动下载任务" />`}
      </div>
    </div>
  </div>`;
}
