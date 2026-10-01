// One deliverable's detail page (legacy renderDeliverableDetailPage). Owns
// the cross-panel coordination the legacy code did with mutable controller
// objects: sync readiness (evidence -> analysis action bar), status-chart
// feedback/busy, EWO summary data and the interactive query result.
import { html, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { LOCAL_ONLY_MESSAGE, apiRequest, enc, isLocalOnlyError } from "./api.js";
import { AnalysisActionBar, AnalysisPanel } from "./analysis.js";
import {
  deliverableDisplayItem,
  deliverableFormReferenceText,
  deliverableManualEditState,
  deliverablePolicyModeLabel,
  deliverableSnapshotSummary,
  deliverableStatusText,
  deliverableSyncDisplay,
  deliverableTone,
  isEwoSource,
  overdueRiskSummary,
  projectStatusSyncFeedback,
  readOnlyNoticeText,
  SYNC_DISPLAY_VALUE_STATES,
} from "./display.js";
import { DeliverableEditForm, InlineNoteEdit } from "./edit.js";
import { EvidencePanel } from "./evidence.js";
import { FormAnalysisPanel } from "./form-analysis.js";
import { deliverableFormKey } from "./form-state.js";
import { errorText, redactSensitiveText, safeDisplayValue } from "./format.js";
import { PolicyPanel } from "./policy.js";
import {
  associationHref,
  buildEwoInteractiveQuerySpec,
  buildInteractiveArasPayload,
  formatInteractiveArasError,
  formatInteractiveArasResult,
  interactiveQueryErrorCode,
  INTERACTIVE_MODES,
} from "./policy-logic.js";
import { InteractiveResult, StatusChart } from "./status-chart.js";

const BACK_HASH = "#p/project-overview/details";

function hostFn(name) {
  const fn = typeof window !== "undefined" ? window[name] : undefined;
  return typeof fn === "function" ? fn : null;
}

function PencilIcon() {
  return html`<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false">
    <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z" fill="currentColor" />
  </svg>`;
}

/** Legacy window.EWOEnrichment panel (ewo-enrichment.js), mounted when present. */
function EwoEnrichmentHost({ getFilters, request }) {
  const hostRef = useRef(null);
  const handlers = useRef({ getFilters, request });
  handlers.current = { getFilters, request };
  useEffect(() => {
    const api = typeof window !== "undefined" ? window.EWOEnrichment : null;
    if (!api || typeof api.mount !== "function" || !hostRef.current) return undefined;
    let panel = null;
    try {
      panel = api.mount({
        host: hostRef.current,
        getFilters: () => handlers.current.getFilters(),
        request: (path, payload) => handlers.current.request(path, payload),
      });
    } catch (_err) {
      panel = null;
    }
    return () => { if (panel && typeof panel.destroy === "function") panel.destroy(); };
  }, []);
  return html`<section class="deliverable-form-analysis" data-ewo-enrichment="true" ref=${hostRef}>
    <p class="section-hint">使用下方已保存的EWO匹配条件准备增强报表。</p>
  </section>`;
}

function Associations({ item }) {
  const associations = Array.isArray(item.associations) ? item.associations.filter((e) => e && typeof e === "object") : [];
  return html`<div class="detail-association">
    <span class="association-label">关联项</span>
    ${!associations.length
      ? html`<p class="association-empty">尚未配置关联模型</p>`
      : html`<ul class="association-list">
        ${associations.map((entry, index) => {
          const isArchive = entry.type === "archive_job";
          const typeLabel = isArchive ? "同步任务" : "目录条目";
          const href = associationHref(entry);
          return html`<li class="association-item" key=${index}>
            <span class="association-type">${typeLabel}</span>
            <a class=${`association-link is-${isArchive ? "archive" : "catalog"}`} href=${href || null}
              aria-label=${`${typeLabel}：${safeDisplayValue(entry.name)}`}>${safeDisplayValue(entry.name)}</a>
            ${isArchive && html`<span class="association-meta">${entry.enabled ? "已启用" : "未启用"}</span>`}
          </li>`;
        })}
      </ul>`}
  </div>`;
}

function PropertyGrid({ item, displayItem, phase, onNoteSaved, latestItem }) {
  const manual = deliverableManualEditState(item);
  const [editingNote, setEditingNote] = useState(false);
  const [noteNotice, setNoteNotice] = useState("");
  const snapshot = deliverableSnapshotSummary(item);
  const pairs = [
    ["当前状态", deliverableStatusText(item, displayItem)],
    ["所属科室", item.department || "未设置"],
    ["所属阶段", item.stage || (phase && (phase.displayName || phase.id)) || ""],
    ["计划完成日期", item.plannedDate],
    ["实际完成日期", item.actualDate || "未完成"],
    ["项目手工进度", `${Number(item.progress) || 0}%`],
    ["数据来源", (snapshot ? (snapshot.kind === "analysis" ? "明细分析快照" : "表单快照") : null) || item.source || "未设置"],
    ["更新方式", deliverablePolicyModeLabel(item.updateMethod || (item.updatePolicy && item.updatePolicy.mode))],
    ["更新时间", item.updatedAt || (phase && phase.updatedAt)],
    ["风险与备注", item.note || "无"],
  ];
  return html`<details class="detail-inline-collapse">
    <summary class="detail-inline-summary">
      <span>详细明细</span><span class="detail-inline-summary-hint">展开查看属性明细</span>
    </summary>
    <div class="detail-inline-grid">
      ${pairs.map(([label, value]) => {
        const isNote = label === "风险与备注";
        return html`<div class="detail-property" key=${label}>
          <span class="detail-property-label">${label}</span>
          <span class="detail-property-value">
            ${isNote && editingNote
              ? html`<${InlineNoteEdit}
                  item=${item}
                  latestItem=${latestItem}
                  onDone=${() => setEditingNote(false)}
                  onSaved=${(projectStatus) => { setEditingNote(false); onNoteSaved(projectStatus); }}
                />`
              : html`${safeDisplayValue(value)}${isNote && html`<button
                  type="button"
                  class=${`note-inline-edit${manual.editable ? "" : " is-readonly"}`}
                  disabled=${!manual.editable}
                  title=${manual.editable ? "编辑风险与备注" : manual.reason}
                  aria-label=${manual.editable ? `编辑 ${item.name} 风险与备注` : `风险与备注只读：${manual.reason}`}
                  onClick=${() => {
                    if (!deliverableManualEditState(item).editable) {
                      setNoteNotice(readOnlyNoticeText(item));
                      return;
                    }
                    setEditingNote(true);
                  }}
                >✎ 编辑</button>`}`}
          </span>
          ${isNote && noteNotice && html`<p class="detail-readonly-note">${noteNotice}</p>`}
        </div>`;
      })}
    </div>
  </details>`;
}

/**
 * props: item, overview ({phase, deliverables}), version, reloadOverview():
 * Promise<boolean>, replaceOverview(projectStatus).
 */
export function DeliverableDetail({ item, overview, version, reloadOverview, replaceOverview }) {
  const displayItem = deliverableDisplayItem(item);
  const manual = deliverableManualEditState(item);
  const syncDisplay = deliverableSyncDisplay(item);
  const hasDisplayValue = SYNC_DISPLAY_VALUE_STATES.has(syncDisplay.state);
  const formKey = deliverableFormKey(item);
  const ewo = isEwoSource(item);
  const capabilities = item.sourceInfo && typeof item.sourceInfo === "object" ? item.sourceInfo : {};
  const risk = overdueRiskSummary(item);

  const [editOpen, setEditOpen] = useState(false);
  const [editNotice, setEditNotice] = useState("");
  const draftDirty = useRef(false);
  const [modelFilter, setModelFilter] = useState({ model: "", match: "fuzzy" });
  const [readiness, setReadiness] = useState({ ready: false, message: "正在读取同步前置条件" });
  const [analysisFeedback, setAnalysisFeedback] = useState(null);
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const [chartFeedback, setChartFeedback] = useState(null);
  const [chartBusy, setChartBusy] = useState(false);
  const [ewoData, setEwoData] = useState(null);
  const [interactive, setInteractive] = useState(null);
  const policyRef = useRef(item.updatePolicy || {});
  const analysisCtl = useRef(null);
  const formCtl = useRef(null);
  const evidenceCtl = useRef(null);
  const latestItem = () => (overview && Array.isArray(overview.deliverables)
    ? overview.deliverables.find((candidate) => candidate && candidate.id === item.id)
    : null);

  useEffect(() => {
    const guard = (event) => {
      if (!draftDirty.current) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, []);

  const reloadPanel = () => (formKey
    ? (formCtl.current ? formCtl.current.reload() : Promise.resolve(false))
    : (analysisCtl.current ? analysisCtl.current.reload() : Promise.resolve(false)));

  // ---- analysis action bar ----
  const analysisRefresh = async () => {
    if (formKey) {
      reloadPanel();
      return;
    }
    setAnalysisBusy(true);
    setAnalysisFeedback({ text: "正在刷新分析...", tone: "busy" });
    try {
      const loaded = await reloadPanel();
      setAnalysisFeedback(loaded ? { text: "刷新完成", tone: "success" } : { text: "刷新失败：分析数据读取失败", tone: "error" });
    } finally {
      setAnalysisBusy(false);
    }
  };
  const analysisSync = async () => {
    if (!readiness.ready) {
      setAnalysisFeedback({ text: `暂不能同步：${readiness.message || "同步条件尚未满足"}`, tone: "warning" });
      return;
    }
    if (!window.confirm(`确定要运行后台同步 ${item.name} 吗？`)) return;
    setAnalysisBusy(true);
    setAnalysisFeedback({ text: "正在运行后台同步...", tone: "busy" });
    try {
      const data = await apiRequest(`/api/project-status/deliverables/${enc(item.id)}/sync-now`, { method: "POST" });
      const feedback = projectStatusSyncFeedback(data);
      const loaded = await reloadPanel();
      if (loaded) setAnalysisFeedback(feedback);
      // 同步可能发布新的分析/表单快照，刷新概览环图数据。
      await reloadOverview();
    } catch (err) {
      setAnalysisFeedback({ text: `同步失败：${errorText(err)}`, tone: "error" });
    } finally {
      setAnalysisBusy(false);
    }
  };

  // ---- status chart (EWO) ----
  const chartRefresh = async () => {
    setChartBusy(true);
    if (formKey) {
      setChartFeedback({ text: "正在刷新表单快照...", tone: "busy" });
      try {
        const loaded = await reloadPanel();
        setChartFeedback(loaded ? { text: "刷新完成", tone: "success" } : { text: "刷新失败：表单快照读取失败", tone: "error" });
      } finally {
        setChartBusy(false);
      }
      return;
    }
    setChartFeedback({ text: "正在刷新后台分析...", tone: "busy" });
    try {
      const loaded = await reloadPanel();
      if (loaded) setChartFeedback({ text: "刷新完成", tone: "success" });
    } catch (err) {
      setChartFeedback({ text: `刷新失败：${errorText(err)}`, tone: "error" });
    } finally {
      setChartBusy(false);
    }
  };
  const interactiveRefresh = async () => {
    if (!window.confirm(`确定要立即刷新 ${item.name} 吗？`)) return;
    const spec = buildEwoInteractiveQuerySpec(policyRef.current, item);
    setInteractive((prev) => prev || { visible: true });
    setChartBusy(true);
    setChartFeedback({ text: "正在执行交互式查询...", tone: "busy" });
    try {
      const data = (await apiRequest(INTERACTIVE_MODES.ewo.endpoint, { method: "POST", body: buildInteractiveArasPayload("ewo", spec.filters) })) || {};
      setInteractive({ visible: true, data, targetKey: spec.targetKey });
      const state = formatInteractiveArasResult(data, spec.targetKey, "ewo");
      setChartFeedback({ text: `交互式查询完成：${state.text}`, tone: state.tone });
    } catch (err) {
      const localOnly = isLocalOnlyError(err);
      const code = localOnly ? "" : interactiveQueryErrorCode(err, err && err.status);
      setChartFeedback({
        text: localOnly ? LOCAL_ONLY_MESSAGE : formatInteractiveArasError(err, err && err.status),
        tone: err && err.code === "unauthenticated" ? "warning" : "error",
        login: code === "unauthenticated",
      });
    } finally {
      setChartBusy(false);
    }
  };

  const onEvidenceSynced = async () => {
    // 同步可能发布新的分析/表单快照，刷新概览数据避免环图停留在旧快照。
    await reloadOverview();
  };

  const login = hostFn("openInPlaceLogin");
  const statusLabelTone = hasDisplayValue ? deliverableTone(displayItem) : "primary";
  const editLabel = `编辑 ${item.name}`;

  return html`<article class="deliverable-detail-page">
    <div class="deliverable-detail-page-head">
      <div class="deliverable-detail-page-nav">
        <a class="segment back-to-list-btn" href=${BACK_HASH} aria-label="返回交付物列表">← 返回交付物列表</a>
      </div>
      <div class="deliverable-detail-title-row">
        <div>
          <p class="eyebrow">交付物明细</p>
          <h3 class="deliverable-page-title">${item.name}</h3>
          <span class="deliverable-page-id">ID: ${safeDisplayValue(item.displayCode || item.id)}</span>
        </div>
        <div class="deliverable-page-status-group">
          <span class=${`status-text is-${statusLabelTone}`}>${deliverableStatusText(item, displayItem)}</span>
          <span class="deliverable-form-reference">${deliverableFormReferenceText(item)}</span>
          <button
            type="button"
            class=${`detail-edit${manual.editable ? "" : " is-readonly"}`}
            disabled=${!manual.editable}
            title=${manual.editable ? editLabel : manual.reason}
            aria-label=${manual.editable ? editLabel : `不可编辑：${manual.reason}`}
            onClick=${(event) => {
              event.stopPropagation();
              if (!deliverableManualEditState(item).editable) {
                setEditNotice(readOnlyNoticeText(item));
                setEditOpen(true);
                return;
              }
              if (editOpen && draftDirty.current && !window.confirm("有未保存的更改，放弃后将继续编辑其他记录？")) return;
              setEditNotice("");
              setEditOpen(true);
            }}
          ><${PencilIcon} /><span>${manual.editable ? " 编辑" : " 只读"}</span></button>
        </div>
      </div>
      ${!manual.editable && html`<p class="detail-readonly-notice">手工字段只读：${redactSensitiveText(manual.reason)}</p>`}
      ${risk && html`<div class="deliverable-overdue-risk-banner"><span>⚠️ <strong>过程工单超期预警</strong>：快照总计 <strong>${String(risk.total)}</strong> 笔单据，已完成 ${risk.completed} 笔（推进进度 ${risk.progress}%）；检测到 <strong>${String(risk.overdue)}</strong> 笔在途单据已过要求完成时间，建议优先协调催办。</span></div>`}
    </div>
    <section class="detail-page-edit-panel" hidden=${!editOpen} aria-label=${`${item.name} 编辑表单`}>
      ${editOpen && (editNotice
        ? html`<p class="detail-readonly-notice">${editNotice}</p>`
        : html`<${DeliverableEditForm}
            key=${item.updatedAt || ""}
            item=${item}
            phaseId=${overview && overview.phase ? overview.phase.id : ""}
            onDirtyChange=${(dirty) => { draftDirty.current = dirty; }}
            onCancel=${() => { draftDirty.current = false; setEditOpen(false); }}
            onSaved=${(projectStatus) => { draftDirty.current = false; setEditOpen(false); replaceOverview(projectStatus); }}
          />`)}
    </section>

    <section class="deliverable-page-meta-section overview-band">
      <h5 class="section-sub-title">交付物配置</h5>
      <${StatusChart}
        item=${item}
        ewoData=${ewoData}
        feedback=${chartFeedback}
        busy=${chartBusy}
        onInteractiveRefresh=${interactiveRefresh}
        onRefresh=${chartRefresh}
      />
      ${chartFeedback && chartFeedback.login && login && html`<p class="interactive-login-hint">
        <button type="button" class="btn is-secondary" onClick=${() => login({ notice: "请输入企业域账号登录；成功后可重新执行交互式查询。" })}>登录统一域账号</button>
      </p>`}
      <section class="deliverable-interactive-query-panel" hidden=${!interactive} aria-live="polite">
        ${interactive && interactive.data && html`<${InteractiveResult} mode="ewo" data=${interactive.data} targetKey=${interactive.targetKey} />`}
      </section>
      ${ewo && typeof window !== "undefined" && window.EWOEnrichment && html`<${EwoEnrichmentHost}
        getFilters=${() => {
          const spec = buildEwoInteractiveQuerySpec(policyRef.current, item);
          if (!Object.keys(spec.filters).length) throw new Error("请先保存至少一项EWO匹配条件");
          return spec.filters;
        }}
        request=${async (path, payload) => {
          let body = payload;
          const rule = policyRef.current.matchRule;
          if ((path.endsWith("/jobs") || path.endsWith("/restore")) && rule && rule.contractVersion === "2" && rule.bindingMode === "single_record") {
            body = { ...payload, sourceItemId: rule.sourceItemId };
          }
          return apiRequest(path, { method: "POST", body });
        }}
      />`}
      <${PropertyGrid}
        item=${item}
        displayItem=${displayItem}
        phase=${overview && overview.phase}
        latestItem=${latestItem}
        onNoteSaved=${replaceOverview}
      />
      <${Associations} item=${item} />
    </section>

    <section class=${formKey ? "deliverable-form-analysis" : "deliverable-analysis-panel"} aria-label=${`${item.name} 各科室完成情况与明细`}>
      ${formKey
        ? html`<${FormAnalysisPanel} item=${item} version=${version} ctl=${formCtl} onViewData=${setEwoData} />`
        : html`<${AnalysisPanel}
            item=${item}
            version=${version}
            ctl=${analysisCtl}
            modelFilter=${modelFilter}
            setModelFilter=${setModelFilter}
            onAnalysisData=${setEwoData}
            onLoadError=${(message) => setChartFeedback({ text: `读取失败：${message}`, tone: "error" })}
            actionBar=${html`<${AnalysisActionBar}
              item=${item}
              supported=${capabilities.syncCapable === true}
              readiness=${readiness}
              feedback=${analysisFeedback}
              busy=${analysisBusy}
              onRefresh=${analysisRefresh}
              onSync=${analysisSync}
              onBlocked=${(text) => setAnalysisFeedback({ text, tone: "warning" })}
            />`}
          />`}
    </section>

    <section class="deliverable-policy-panel" aria-label=${`${item.name} 更新方式`}>
      <${PolicyPanel}
        item=${item}
        version=${version}
        onPolicyLoaded=${(policy) => { policyRef.current = policy || {}; }}
        onEvidenceRefresh=${() => evidenceCtl.current && evidenceCtl.current.reload()}
        onReloadOverview=${reloadOverview}
      />
    </section>

    <details class="deliverable-evidence-disclosure">
      <summary>外部同步与技术证据（点击展开）</summary>
      <section class="deliverable-evidence-panel" aria-label=${`${item.name} 外部同步与证据`}>
        <${EvidencePanel}
          item=${item}
          version=${version}
          ctl=${evidenceCtl}
          onReadiness=${(ready, message) => setReadiness({ ready, message })}
          onSynced=${onEvidenceSynced}
        />
      </section>
    </details>
  </article>`;
}
