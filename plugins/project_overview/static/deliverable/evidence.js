// "外部同步与技术证据" disclosure (legacy loadDeliverableEvidence /
// renderDeliverableEvidence / loadDeliverableUnifiedStatus): EWO/PAA/NCR
// unified status, summary grid, debug tools, sync-now bar, candidate diff,
// mapping evidence and run history with per-run artifacts.
import { html, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { apiRequest, enc, requestError } from "./api.js";
import {
  DELIVERABLE_FIELD_LABELS,
  DELIVERABLE_FIXED_SOURCES,
  UNIFIED_AUTH_LABELS,
  UNIFIED_QUERY_LABELS,
  UNIFIED_SYNC_LABELS,
  buildDeliverableDebugSummary,
  deliverableSyncStateLabel,
  evidenceSyncReadiness,
  formatCandidateReasonLabel,
  formatMappingStateLabel,
  formatRunStateLabel,
  formatRunTriggerLabel,
  mergeUnifiedObjects,
  projectStatusSyncFeedback,
  unifiedStatusStateLabel,
  unifiedStatusTone,
} from "./display.js";
import {
  errorText,
  formatApiErrorMessage,
  formatArtifactSize,
  parseContentDispositionFilename,
  redactSensitiveText,
  safeDisplayValue,
  sanitizeDownloadName,
} from "./format.js";

const KIND_LABELS = { ewo: "EWO", paa: "PAA", ncr: "NCR" };

export function UnifiedStatus({ item, version }) {
  const [state, setState] = useState({ loading: true, error: "", objects: [] });
  const seq = useRef(0);
  const load = async () => {
    const current = ++seq.current;
    setState({ loading: true, error: "", objects: [] });
    try {
      const data = await apiRequest(`/api/project-status/deliverables/${enc(item.id)}/unified-status`);
      if (current !== seq.current) return;
      setState({ loading: false, error: "", objects: data && Array.isArray(data.objects) ? data.objects : [] });
    } catch (err) {
      if (current !== seq.current) return;
      setState({ loading: false, error: errorText(err), objects: [] });
    }
  };
  useEffect(() => { load(); }, [item.id, version]);

  if (state.loading) {
    return html`<section class="evidence-unified-status"><p class="loading" role="status" aria-live="polite">正在读取 EWO / PAA / NCR 统一状态...</p></section>`;
  }
  if (state.error) {
    return html`<section class="evidence-unified-status"><div class="unified-status-load-error" role="alert" aria-live="assertive">
      <p class="error-msg">读取统一状态失败：${state.error}</p>
      <button type="button" class="evidence-retry-btn unified-status-retry-btn" onClick=${load}>重试统一状态</button>
    </div></section>`;
  }
  const byKind = mergeUnifiedObjects(state.objects);
  const value = (raw, labels, group) => html`<span class=${`status-text is-${unifiedStatusTone(raw, group)}`}>${unifiedStatusStateLabel(raw, labels)}</span>`;
  return html`<section class="evidence-unified-status">
    <h5 class="evidence-sub-title">EWO / PAA / NCR 统一状态</h5>
    <div class="evidence-overview-grid unified-status-cards">
      ${["ewo", "paa", "ncr"].map((kind) => {
        const object = byKind.get(kind) || {};
        const identity = object.id || object.source
          ? `${safeDisplayValue(object.id || "未知对象")} · ${safeDisplayValue(object.source || "未知来源")}`
          : "暂无状态数据";
        const errors = Array.isArray(object.errors) ? object.errors.filter((e) => e !== null && e !== undefined && String(e).trim()) : [];
        const errorSummary = errors.length > 0 ? errors.slice(0, 2).map((e) => redactSensitiveText(String(e))).join("；") : "无";
        const content = object.content && typeof object.content === "object" ? object.content : {};
        return html`<article class="evidence-restriction-card unified-status-card" aria-label=${`${KIND_LABELS[kind]} 状态`} key=${kind}>
          <strong class="evidence-restriction-title">${KIND_LABELS[kind]}</strong>
          <p class="evidence-restriction-desc">${identity}</p>
          <dl class="evidence-obs-grid unified-status-state-grid">
            <dt>认证状态</dt><dd>${value(object.auth_state, UNIFIED_AUTH_LABELS, "auth")}</dd>
            <dt>查询状态</dt><dd>${value(object.query_state, UNIFIED_QUERY_LABELS, "query")}</dd>
            <dt>同步状态</dt><dd>${value(object.sync_state, UNIFIED_SYNC_LABELS, "sync")}</dd>
          </dl>
          <span class="evidence-field-label">错误摘要</span>
          <p class="evidence-risk-desc unified-status-error-summary">${safeDisplayValue(errorSummary)}</p>
          <span class="evidence-field-label">最近更新</span>
          <p class="evidence-restriction-desc">${safeDisplayValue(object.last_updated || "未知")}</p>
          <span class="evidence-field-label">内容来源</span>
          <p class="evidence-restriction-desc">${safeDisplayValue(content.report_type || "暂无内容")}</p>
          <span class="evidence-field-label">最近成功</span>
          <p class="evidence-restriction-desc">${safeDisplayValue(content.last_success_at || "暂无记录")}</p>
        </article>`;
      })}
    </div>
  </section>`;
}

async function downloadDebugBundle(endpoint, defaultFileName, setStatus) {
  setStatus({ text: "正在准备诊断包...", tone: "busy" });
  let objectUrl = "";
  let link = null;
  try {
    const response = await fetch(endpoint, { method: "GET", headers: { Accept: "application/json, application/zip" }, cache: "no-store" });
    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      try {
        const body = await response.json();
        const error = body && body.error;
        if (error && error.message) message = formatApiErrorMessage(requestError(body, response.status), response.status);
      } catch (_err) {
        // 非 JSON 错误体不回显
      }
      throw new Error(redactSensitiveText(message));
    }
    const blob = await response.blob();
    const fileName = parseContentDispositionFilename(response.headers.get("Content-Disposition")) || defaultFileName;
    objectUrl = URL.createObjectURL(blob);
    link = document.createElement("a");
    link.href = objectUrl;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    setStatus({ text: "诊断包已下载（敏感字段已过滤）", tone: "success" });
  } catch (err) {
    setStatus({ text: `下载失败：${errorText(err)}`, tone: "error" });
  } finally {
    if (link) link.remove();
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  }
}

function DebugTools({ item, bundle }) {
  const [status, setStatus] = useState({ text: "", tone: "" });
  const [busy, setBusy] = useState("");
  const baseName = sanitizeDownloadName(String(item.id)) || "deliverable";
  const download = async (format) => {
    setBusy(format);
    try {
      await downloadDebugBundle(
        `/api/project-status/deliverables/${enc(item.id)}/debug-bundle?format=${format}`,
        `${baseName}_debug.${format}`,
        setStatus,
      );
    } finally {
      setBusy("");
    }
  };
  const copy = async () => {
    try {
      const summary = buildDeliverableDebugSummary(bundle);
      if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") throw new Error("当前浏览器不支持复制");
      await navigator.clipboard.writeText(summary);
      setStatus({ text: "诊断摘要已复制", tone: "success" });
    } catch (err) {
      setStatus({ text: `复制失败：${errorText(err)}`, tone: "error" });
    }
  };
  return html`<section class="evidence-debug-tools">
    <h5 class="evidence-sub-title">Debug 工具</h5>
    <p class="evidence-debug-notice">敏感字段已过滤</p>
    <div class="evidence-debug-actions">
      <button type="button" class="evidence-debug-btn" onClick=${copy}>复制诊断摘要</button>
      <button type="button" class="evidence-debug-btn" disabled=${busy === "json"} onClick=${() => download("json")}>下载 JSON</button>
      <button type="button" class="evidence-debug-btn" disabled=${busy === "zip"} onClick=${() => download("zip")}>下载 ZIP</button>
      <span class=${`evidence-debug-status${status.tone ? ` is-${status.tone}` : ""}`} role="status" aria-live="polite">${status.text}</span>
    </div>
  </section>`;
}

function RunRow({ run }) {
  const [open, setOpen] = useState(false);
  const [art, setArt] = useState({ loading: false, error: "", items: null });
  const loadArtifacts = async () => {
    setArt({ loading: true, error: "", items: null });
    try {
      const data = await apiRequest(`/api/project-status/runs/${enc(run.id)}/artifacts`);
      setArt({ loading: false, error: "", items: data && Array.isArray(data.artifacts) ? data.artifacts : [] });
    } catch (err) {
      setArt({ loading: false, error: errorText(err), items: null });
    }
  };
  const toggle = () => {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    loadArtifacts();
  };
  const stateTone = run.run_state === "success" ? "status-text is-success" : (run.run_state === "failed" ? "status-text is-error" : "status-text is-warning");
  const attempt = run.attempt !== null && run.attempt !== undefined && run.attempt !== "" ? `第 ${run.attempt} 次` : "未知";
  let artBody = null;
  if (art.loading) artBody = html`<div class="evidence-artifact-box" role="status" aria-live="polite">正在读取产物元数据...</div>`;
  else if (art.error) {
    artBody = html`<div class="evidence-artifact-box" role="alert">
      <p class="error-msg">读取产物失败：${art.error}</p>
      <button type="button" class="evidence-retry-btn" onClick=${loadArtifacts}>重试读取产物</button>
    </div>`;
  } else if (art.items && !art.items.length) {
    artBody = html`<div class="evidence-artifact-box"><p class="evidence-empty-note" role="status">无产物元数据</p></div>`;
  } else if (art.items) {
    artBody = html`<div class="evidence-artifact-box"><table class="evidence-artifact-table">
      <thead><tr>${["产物名称", "类型", "大小", "相对路径", "SHA-256"].map((h) => html`<th key=${h}>${h}</th>`)}</tr></thead>
      <tbody>${art.items.map((a, index) => html`<tr key=${index}>
        <td>${safeDisplayValue(a.display_name || "—")}</td>
        <td>${safeDisplayValue(a.artifact_type || "—")}</td>
        <td>${formatArtifactSize(a.size_bytes)}</td>
        <td>${safeDisplayValue(a.relative_path || "—")}</td>
        <td>${safeDisplayValue(a.sha256 || "—")}</td>
      </tr>`)}</tbody>
    </table></div>`;
  }
  return html`
    <tr>
      <td>${formatRunTriggerLabel(run.trigger_type)}</td>
      <td><span class=${stateTone}>${formatRunStateLabel(run.run_state)}</span></td>
      <td>${attempt}</td>
      <td>${safeDisplayValue(run.started_at || run.created_at || "未知")}</td>
      <td>${safeDisplayValue(run.finished_at || "未知")}</td>
      <td>${redactSensitiveText(run.error_message || run.result_summary || "—")}</td>
      <td><button type="button" class="evidence-artifact-btn" onClick=${toggle}>${open ? "收起产物" : "查看产物"}</button></td>
    </tr>
    ${open && html`<tr class="evidence-artifact-row"><td colspan="7">${artBody}</td></tr>`}`;
}

function EvidenceBody({ item, bundle, syncStatus, setSyncStatus, onSync }) {
  const { policy, analytics, mapping, preview, runs } = bundle;
  const fixedSource = DELIVERABLE_FIXED_SOURCES[item.id] || item.source || "未知";
  const readiness = evidenceSyncReadiness(item, { policy, analytics, mapping });
  const latestObs = mapping.observations && mapping.observations.length > 0 ? mapping.observations[0] : null;
  const freshness = analytics.freshness === "fresh" ? "及时" : (analytics.freshness === "stale" ? "滞后" : "未知");
  const credential = policy.credentialAvailable === true ? "已配置" : (policy.credentialAvailable === false ? "未配置" : "未知");
  const recordCount = analytics.externalRecordCount !== null && analytics.externalRecordCount !== undefined
    ? `${analytics.externalRecordCount} 条`
    : (latestObs && latestObs.candidateCount !== null && latestObs.candidateCount !== undefined ? `${latestObs.candidateCount} 条` : "待确认");
  const pairs = [
    ["权威来源", fixedSource],
    ["凭据状态", credential],
    ["同步状态", deliverableSyncStateLabel(policy)],
    ["时效性", freshness],
    ["最近尝试", safeDisplayValue(analytics.lastAttemptAt || policy.lastAttemptAt || "无")],
    ["最近成功", safeDisplayValue(analytics.lastSuccessAt || policy.lastSuccessAt || "无")],
    ["失败次数", analytics.failureCount === null || analytics.failureCount === undefined ? "未知" : `${analytics.failureCount} 次`],
    ["外部记录数", recordCount],
    ["映射状态", formatMappingStateLabel(latestObs ? latestObs.state : (analytics.mappingEvidence ? analytics.mappingEvidence.state : null))],
    ["映射进度", readiness.mappingProgressText],
  ];
  const differences = preview && Array.isArray(preview.differences) ? preview.differences : [];
  const report = (latestObs && latestObs.fieldReport) || {};
  const fields = Array.isArray(report.fields) ? report.fields : [];
  const statusFields = Array.isArray(report.statusOrApprovalFields) ? report.statusOrApprovalFields : [];
  let status = syncStatus;
  if (!status || !status.text) {
    if (!readiness.supported) status = { text: "该交付物仅支持手动维护", tone: "warning" };
    else if (!readiness.ready) status = { text: `暂不能同步：${readiness.message}`, tone: "warning" };
  }
  const [busy, setBusy] = useState(false);
  const runSync = async () => {
    if (!readiness.ready) {
      setSyncStatus({ text: `暂不能同步：${readiness.message}`, tone: "warning" });
      return;
    }
    if (!window.confirm(`确定要运行后台同步 ${item.name} 吗？`)) return;
    setBusy(true);
    try {
      await onSync();
    } finally {
      setBusy(false);
    }
  };
  return html`
    <dl class="evidence-overview-grid">
      ${pairs.map(([label, value]) => html`<dt key=${`t${label}`}>${label}</dt><dd key=${`d${label}`}>${safeDisplayValue(value)}</dd>`)}
    </dl>
    <${DebugTools} item=${item} bundle=${bundle} />
    ${(analytics.needsAttention || analytics.riskSummary) && html`<div class="evidence-risk-box">
      <strong class="evidence-risk-title">风险与告警</strong>
      <p class="evidence-risk-desc">${redactSensitiveText(analytics.riskSummary || "映射或同步状态需要关注")}</p>
    </div>`}
    <div class="evidence-sync-bar">
      ${readiness.supported && html`<button
        type="button" class="evidence-sync-btn"
        disabled=${busy || !readiness.ready}
        title=${readiness.ready ? null : `不可同步：${readiness.message}`}
        onClick=${runSync}
      >运行后台同步</button>`}
      <span class=${`evidence-sync-status${status && status.tone ? ` is-${status.tone}` : ""}`} role="status" aria-live="polite">${status ? status.text : ""}</span>
    </div>
    <div class="evidence-sub-section evidence-diff-section">
      <h5 class="evidence-sub-title">候选字段差异对比</h5>
      ${differences.length === 0
        ? html`<p class="evidence-empty-note" role="status">暂无差异证据（${formatCandidateReasonLabel(preview && preview.reason)}）</p>`
        : html`<div class="overview-table-wrap"><table class="overview-details-table evidence-diff-table">
          <thead><tr>${["目标字段", "来源字段", "当前系统值", "外部候选值", "变更状态"].map((t) => html`<th key=${t}>${t}</th>`)}</tr></thead>
          <tbody>${differences.map((diff, index) => html`<tr key=${index}>
            <td>${safeDisplayValue(DELIVERABLE_FIELD_LABELS[diff.targetField] || diff.targetField)}</td>
            <td>${safeDisplayValue(diff.sourceField)}</td>
            <td>${safeDisplayValue(diff.currentValue || "(空)")}</td>
            <td>${safeDisplayValue(diff.candidateValue || "(空)")}</td>
            <td><span class=${diff.changed ? "status-text is-warning" : "status-text is-success"}>${diff.changed ? "有变更" : "无变更"}</span></td>
          </tr>`)}</tbody>
        </table></div>`}
    </div>
    <div class="evidence-sub-section evidence-mapping-section">
      <h5 class="evidence-sub-title">映射发现证据</h5>
      ${!latestObs
        ? html`<p class="evidence-empty-note" role="status">暂无映射发现记录</p>`
        : html`
          <dl class="evidence-obs-grid">
            <dt>观测状态</dt><dd>${formatMappingStateLabel(latestObs.state)}</dd>
            <dt>观测时间</dt><dd>${safeDisplayValue(latestObs.createdAt)}</dd>
            <dt>候选记录数</dt><dd>${`${latestObs.candidateCount} 条`}</dd>
          </dl>
          ${fields.length > 0 && html`<div class="evidence-field-list-wrap">
            <span class="evidence-field-label">发现字段名称：</span>
            <div class="evidence-field-tags">${fields.map((f, index) => html`<span class="evidence-field-tag" key=${index}>${String(f)}</span>`)}</div>
          </div>`}
          ${statusFields.length > 0 && html`<div class="evidence-status-fields-wrap">
            <span class="evidence-field-label">状态/审批字段采样：</span>
            <ul class="evidence-status-samples-list">${statusFields.map((f, index) => html`<li key=${index}>${`${f.field}：${Array.isArray(f.samples) && f.samples.length > 0 ? f.samples.join(", ") : "无采样"}`}</li>`)}</ul>
          </div>`}
          <p class="evidence-mapping-confirmation">建议状态映射：待用户确认（不自动应用）</p>`}
    </div>
    <div class="evidence-sub-section evidence-runs-section">
      <h5 class="evidence-sub-title">运行历史与产物</h5>
      ${runs.length === 0
        ? html`<p class="evidence-empty-note" role="status">暂无同步运行记录</p>`
        : html`<div class="overview-table-wrap"><table class="overview-details-table evidence-runs-table">
          <thead><tr>${["触发方式", "状态", "尝试", "开始时间", "结束时间", "结果摘要 / 错误", "产物"].map((t) => html`<th key=${t}>${t}</th>`)}</tr></thead>
          <tbody>${runs.map((run, index) => html`<${RunRow} key=${run.id || index} run=${run} />`)}</tbody>
        </table></div>`}
    </div>`;
}

/**
 * `ctl.current.reload()` re-reads the bundle; `onReadiness(ready, message)`
 * feeds the analysis action bar; `onSynced(feedback)` lets the page refresh.
 */
export function EvidencePanel({ item, version, ctl, onReadiness, onSynced }) {
  const [state, setState] = useState({ loading: true, error: "", bundle: null });
  const [syncStatus, setSyncStatus] = useState(null);
  const seq = useRef(0);
  const fixedSource = DELIVERABLE_FIXED_SOURCES[item.id] || item.source || "未知";

  const load = async () => {
    const current = ++seq.current;
    if (item.id === "VPI-T2-D1") {
      onReadiness(false, "该交付物仅支持手动维护");
      setState({ loading: false, error: "", bundle: null });
      return;
    }
    if (item.id === "VPI-T2-D4") {
      onReadiness(false, "该交付物外部数据契约待验证，当前已阻断外部同步");
      setState({ loading: false, error: "", bundle: null });
      return;
    }
    setState((prev) => ({ ...prev, loading: true, error: "" }));
    try {
      const id = enc(item.id);
      const [policy, analyticsData, mapping, preview, runsData] = await Promise.all([
        apiRequest(`/api/project-status/deliverables/${id}/update-policy`),
        apiRequest("/api/project-status/analytics"),
        apiRequest(`/api/project-status/deliverables/${id}/mapping-discovery`),
        apiRequest(`/api/project-status/deliverables/${id}/candidate-preview`),
        apiRequest(`/api/project-status/runs?deliverableId=${id}&limit=10`),
      ]);
      if (current !== seq.current) return;
      const list = analyticsData && Array.isArray(analyticsData.deliverables) ? analyticsData.deliverables : [];
      const bundle = {
        policy: policy || {},
        analytics: list.find((d) => d.deliverableId === item.id) || {},
        mapping: mapping || {},
        preview: preview || {},
        runs: runsData && Array.isArray(runsData.runs) ? runsData.runs : [],
      };
      const readiness = evidenceSyncReadiness(item, bundle);
      onReadiness(readiness.supported && readiness.ready, readiness.message);
      setState({ loading: false, error: "", bundle });
    } catch (err) {
      if (current !== seq.current) return;
      onReadiness(false, "同步前置条件读取失败，请展开下方证据区域重试");
      setState({ loading: false, error: errorText(err), bundle: null });
    }
  };
  if (ctl) ctl.current = { reload: load };
  useEffect(() => { load(); }, [item.id, version]);

  const runSync = async () => {
    setSyncStatus({ text: "正在运行后台同步...", tone: "busy" });
    try {
      const data = await apiRequest(`/api/project-status/deliverables/${enc(item.id)}/sync-now`, { method: "POST" });
      const feedback = projectStatusSyncFeedback(data);
      setSyncStatus(feedback);
      if (onSynced) await onSynced(feedback);
    } catch (err) {
      setSyncStatus({ text: `同步失败：${errorText(err)}`, tone: "error" });
    }
  };

  let body;
  if (item.id === "VPI-T2-D1") {
    body = html`<div class="evidence-restriction-card is-manual">
      <strong class="evidence-restriction-title">仅手工维护</strong>
      <p class="evidence-restriction-desc">该交付物当前仅允许手工维护，未接入外部系统。</p>
    </div>`;
  } else if (item.id === "VPI-T2-D4") {
    body = html`<div class="evidence-restriction-card is-blocked">
      <strong class="evidence-restriction-title">TDC A 面契约待验证/阻断</strong>
      <p class="evidence-restriction-desc">该交付物外部数据契约待验证，当前已阻断外部同步与映射。</p>
    </div>`;
  } else if (state.loading) {
    body = html`<p class="loading" role="status" aria-live="polite">正在读取同步与证据数据...</p>`;
  } else if (state.error) {
    body = html`<div class="evidence-load-error" role="alert" aria-live="assertive">
      <p class="error-msg">读取证据失败：${state.error}</p>
      <button type="button" class="evidence-retry-btn" onClick=${load}>重试</button>
    </div>`;
  } else if (state.bundle) {
    body = html`<${EvidenceBody} item=${item} bundle=${state.bundle} syncStatus=${syncStatus} setSyncStatus=${setSyncStatus} onSync=${runSync} />`;
  }

  return html`
    <div class="evidence-panel-head">
      <strong class="evidence-title">外部同步与证据</strong>
      <span class="evidence-source">权威来源 · ${fixedSource}</span>
    </div>
    <${UnifiedStatus} item=${item} version=${version} />
    ${body}`;
}
