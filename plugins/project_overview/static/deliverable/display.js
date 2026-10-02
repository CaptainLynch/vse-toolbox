// Display-state rules for one deliverable (legacy deliverableDisplayItem,
// deliverableSyncDisplay, deliverableStatusText ...). Pure functions; the
// node tests import this file directly.
import { redactSensitiveText, safeDisplayValue } from "./format.js";

export const SYNC_DISPLAY_VALUE_STATES = new Set(["manual", "snapshot"]);
export const SYNC_DISPLAY_RING_LABELS = {
  paused: "已暂停",
  pending_config: "待配置",
  pending_first_sync: "待同步",
  sync_failed: "同步失败",
  no_source_records: "无记录",
};

export function deliverableManualEditState(item) {
  const reason = String((item && item.readOnlyReason) || "").trim();
  if (item && item.manualEditable === true) return { editable: true, reason: "" };
  return { editable: false, reason: reason || "该交付物当前由系统同步维护，手工字段只读。" };
}

export function readOnlyNoticeText(item) {
  return `手工字段只读：${redactSensitiveText(deliverableManualEditState(item).reason)}`;
}

// 快照联动摘要：明细分析快照优先，其次表单快照；仅在交付物启用同步时生效。
export function deliverableSnapshotSummary(item) {
  if (!item || typeof item !== "object") return null;
  const policy = item.updatePolicy;
  if (!policy || typeof policy !== "object" || policy.enabled !== true) return null;
  const analysis = item.analysisLink && typeof item.analysisLink === "object" ? item.analysisLink.summary : null;
  if (analysis && typeof analysis === "object") {
    return { kind: "analysis", summary: analysis, snapshotAt: item.analysisLink.snapshotAt || null };
  }
  const form = item.formLink && typeof item.formLink === "object" ? item.formLink.summary : null;
  if (form && typeof form === "object") {
    // 聚合绑定只信任分析快照链路，不做表单快照兜底。
    if (item.updatePolicy && item.updatePolicy.aggregate === true) return null;
    return { kind: "form", summary: form, snapshotAt: item.formLink.snapshotAt || null };
  }
  return null;
}

export function deliverableFormDisplay(item) {
  const syncDisplay = item && typeof item === "object" ? item.syncDisplay : null;
  if (
    syncDisplay
    && typeof syncDisplay === "object"
    && syncDisplay.state === "snapshot"
    && syncDisplay.displaySummary
    && typeof syncDisplay.displaySummary === "object"
  ) {
    const displayProgress = Number(syncDisplay.displayProgress);
    return {
      progress: Number.isFinite(displayProgress) ? Math.min(100, Math.max(0, Math.round(displayProgress))) : 0,
      status: String(syncDisplay.displayStatus || item.status || ""),
      snapshotAt: syncDisplay.displaySummary.snapshotAt || null,
    };
  }
  const linked = deliverableSnapshotSummary(item);
  if (!linked) return null;
  const summary = linked.summary;
  const total = Number(summary.total);
  if (!Number.isFinite(total) || total <= 0) return null;
  const completed = Number(summary.completed) || 0;
  const overdue = Number(summary.overdue) || 0;
  const progress = Math.round((completed / total) * 100);
  let status = "进行中";
  if (completed >= total) status = "已完成";
  else if (overdue > 0) status = "已逾期";
  return { progress: Math.min(100, Math.max(0, progress)), status, snapshotAt: linked.snapshotAt };
}

export function deliverableFormReferenceText(item) {
  const linked = deliverableSnapshotSummary(item);
  if (linked) {
    const total = Number(linked.summary.total) || 0;
    const completed = Number(linked.summary.completed) || 0;
    const at = linked.snapshotAt ? String(linked.snapshotAt).slice(0, 10) : "";
    return `表单分析参考：已完成 ${completed}/${total}（${at || "无快照时间"}）`;
  }
  const sourceName = item && item.sourceInfo && item.sourceInfo.displayName ? String(item.sourceInfo.displayName) : "";
  return sourceName ? `无表单来源（${sourceName}来源）` : "无表单来源";
}

export function deliverableDisplayItem(item) {
  const formDisplay = deliverableFormDisplay(item);
  if (!formDisplay) return item;
  return {
    ...item,
    progress: formDisplay.progress,
    status: formDisplay.status,
    tone: null,
    progressOrDate: formDisplay.status === "已完成" ? (item.actualDate || `${formDisplay.progress}%`) : `${formDisplay.progress}%`,
  };
}

export function deliverableSyncDisplay(item) {
  const info = item && typeof item === "object" ? item.syncDisplay : null;
  if (info && typeof info === "object" && info.state) {
    return {
      state: info.state,
      label: info.label || SYNC_DISPLAY_RING_LABELS[info.state] || info.state,
      syncState: info.syncState || null,
      lastError: info.lastError || null,
    };
  }
  return { state: "manual", label: "手工维护", syncState: null, lastError: null };
}

export function deliverableHasDisplayValue(item) {
  return SYNC_DISPLAY_VALUE_STATES.has(deliverableSyncDisplay(item).state);
}

export function deliverableStatusText(item, displayItem) {
  const syncDisplay = deliverableSyncDisplay(item);
  if (!SYNC_DISPLAY_VALUE_STATES.has(syncDisplay.state)) return syncDisplay.label;
  return displayItem ? displayItem.status : item.status;
}

export function deliverableTone(item) {
  if (item.tone) return item.tone;
  if (item.status === "已完成") return "success";
  if (item.status === "已逾期") return "error";
  if (item.status === "待审批") return "warning";
  if (item.status === "success") return "success";
  if (item.status === "needs_attention") return "warning";
  if (item.status === "failed") return "error";
  return "primary";
}

/** Values of the current-status chart (progress bar + label). */
export function statusChartModel(rawItem) {
  const item = deliverableDisplayItem(rawItem);
  const formDisplay = deliverableFormDisplay(rawItem);
  const syncDisplay = deliverableSyncDisplay(rawItem);
  const hasValue = SYNC_DISPLAY_VALUE_STATES.has(syncDisplay.state);
  const numericProgress = Number(item.progress);
  const hasProgress = hasValue && item.progress !== null && item.progress !== undefined && Number.isFinite(numericProgress);
  const progress = hasProgress
    ? Math.min(Math.max(numericProgress, 0), 100)
    : (hasValue && item.status === "已完成" ? 100 : 0);
  const progressLabel = hasValue && (hasProgress || item.status === "已完成")
    ? `${progress}%`
    : (hasValue ? "未设置" : syncDisplay.label);
  return {
    item,
    formDisplay,
    syncDisplay,
    hasValue,
    hasProgress,
    progress,
    progressLabel,
    tone: hasValue ? deliverableTone(item) : "primary",
    statusText: deliverableStatusText(item, item),
    snapshotDate: formDisplay && formDisplay.snapshotAt ? String(formDisplay.snapshotAt).slice(0, 10) : "",
  };
}

export function overdueRiskSummary(item) {
  const displayItem = deliverableDisplayItem(item);
  const linked = deliverableSnapshotSummary(displayItem);
  if (displayItem.status !== "已逾期" || !linked || !(Number(linked.summary.overdue) > 0)) return null;
  return {
    total: linked.summary.total ?? 0,
    completed: linked.summary.completed ?? 0,
    overdue: linked.summary.overdue ?? 0,
    progress: displayItem.progress ?? 0,
  };
}

export function isEwoSource(item) {
  return /ewo/i.test(String((item && item.source) || ""));
}

// ---- policy / sync labels ------------------------------------------------

export const DELIVERABLE_POLICY_MODE_LABELS = { manual: "手动", hybrid: "混合", automatic: "自动" };

export function deliverablePolicyModeLabel(mode) {
  return DELIVERABLE_POLICY_MODE_LABELS[mode] || "手动";
}

export function deliverableSyncStateLabel(policy) {
  if (policy && policy.enabled === false) return "未启用";
  if (!policy || policy.enabled !== true) return "未知";
  const labels = { idle: "等待同步", running: "同步中", success: "同步成功", failed: "同步失败", needs_attention: "需要处理" };
  return labels[policy.syncState] || "未知";
}

export const DELIVERABLE_FIXED_SOURCES = {
  "VPI-T2-D1": "仅手工维护",
  "VPI-T2-D2": "TDC SOR",
  "VPI-T2-D3": "ARAS EWO",
  "VPI-T2-D4": "TDC A 面（契约待验证）",
  "VPI-T2-D5": "数模设计审核流程报表",
  "VPI-T2-D6": "ARAS PAA流程",
  "VPI-T2-D7": "ARAS NCR 审批进度",
  "VPI-T2-D8": "ARAS NCR 审批明细",
};

export const DELIVERABLE_FIELD_LABELS = {
  owner: "负责人",
  plannedDate: "计划完成日期",
  note: "风险与备注",
  status: "状态",
  progress: "进度",
  actualDate: "实际完成日期",
};

export const DELIVERABLE_DEFAULT_MAPPINGS = {
  "VPI-T2-D2": { owner: "startUserName", note: ["latestCompletedNode", "processInstanceStatus"] },
  "VPI-T2-D3": { owner: "_rsp_name", plannedDate: "_required_date", note: ["_subject", "_change_description"] },
  "VPI-T2-D5": { owner: "applicant", note: ["latestApproveLog", "status"] },
};

export function formatMappingStateLabel(state) {
  const map = { matched: "已匹配", not_found: "未找到", ambiguous: "存在歧义", key_changed: "稳定键变更" };
  return (state && map[state]) || "待确认";
}

export function formatCandidateReasonLabel(reason) {
  const map = {
    no_observation: "无观测记录",
    observation_not_matched: "最新观测未匹配",
    insufficient_stability: "稳定性不足（需连续2次匹配）",
    unapproved_mapping: "映射未确认或未配置",
    policy_disabled: "更新策略未启用",
    candidate_not_unique: "外部候选非唯一",
    source_mismatch: "来源类型不匹配",
    key_mismatch: "外部键不匹配",
    deliverable_not_found: "交付物未找到",
    policy_not_found: "策略未找到",
  };
  return (reason && map[reason]) || "待确认";
}

export function formatRunTriggerLabel(trigger) {
  const map = { sync_now: "手动触发", manual: "手动更新", scheduled: "定时调度", webhook: "外部推送" };
  return (trigger && map[trigger]) || "未知";
}

export function formatRunStateLabel(state) {
  const map = { success: "成功", partial: "部分成功", failed: "失败", needs_attention: "需要处理", running: "运行中", expired: "已过期" };
  return (state && map[state]) || "未知";
}

/** sync-now response -> {text, tone} (legacy projectStatusSyncFeedback / syncResultText). */
export function projectStatusSyncFeedback(data) {
  const result = data && data.result ? data.result : (data || {});
  const finalState = result.finalState || (data && data.finalState);
  const outcome = result.outcome || (data && data.outcome) || finalState;
  const rawMessage = result.errorMessage || (data && data.errorMessage) || "";
  if (finalState === "busy" || outcome === "busy") {
    return { text: `同步进行中：${redactSensitiveText(rawMessage || "任务处理中")}`, tone: "busy" };
  }
  if (finalState === "success" && outcome === "completed") return { text: "同步完成：成功", tone: "success" };
  if (finalState === "partial" || outcome === "partial") return { text: "同步完成：部分字段已应用", tone: "warning" };
  if (finalState === "needs_attention" || outcome === "needs_attention") {
    return { text: `同步需要处理：${redactSensitiveText(rawMessage || "未匹配到唯一候选")}`, tone: "warning" };
  }
  return { text: `同步失败：${redactSensitiveText(rawMessage || (finalState ? `状态 ${finalState}` : "未知状态"))}`, tone: "error" };
}

/** Summary-card / wizard wording of the same result (no default busy text). */
export function syncResultText(data) {
  const result = data && typeof data === "object" ? data.result || {} : {};
  const finalState = result.finalState || (data && data.finalState);
  const outcome = result.outcome || (data && data.outcome) || finalState;
  const message = redactSensitiveText(result.errorMessage || (data && data.errorMessage) || "");
  if (finalState === "busy" || outcome === "busy") return message ? `同步进行中：${message}` : "同步进行中";
  if (finalState === "success" && outcome === "completed") return "同步完成：成功";
  if (finalState === "partial" || outcome === "partial") return "同步完成：部分字段已应用";
  if (finalState === "needs_attention" || outcome === "needs_attention") return `同步需要处理：${message || "未匹配到唯一候选"}`;
  return `同步失败：${message || (finalState ? `状态 ${finalState}` : "未知状态")}`;
}

// ---- evidence readiness ---------------------------------------------------

/** Legacy renderDeliverableEvidence readiness rules (sync-now gate). */
export function evidenceSyncReadiness(item, { policy = {}, analytics = {}, mapping = {} } = {}) {
  const capabilities = item && item.sourceInfo && typeof item.sourceInfo === "object" ? item.sourceInfo : {};
  const confirmedCount = analytics.mappingStability
    ? analytics.mappingStability.confirmed
    : (mapping.stability ? mapping.stability.confirmed : null);
  const hasConfirmedCount = confirmedCount !== null && confirmedCount !== undefined && confirmedCount !== ""
    && Number.isFinite(Number(confirmedCount));
  const mappingProgressText = hasConfirmedCount ? `${Math.min(Math.max(Number(confirmedCount), 0), 2)}/2` : "待确认";
  const stabilityReady = Boolean(
    (analytics.mappingStability && analytics.mappingStability.ready === true)
    || (mapping.stability && Number(mapping.stability.confirmed) >= 2),
  );
  const syncSupported = capabilities.syncCapable === true;
  const syncModeReady = ["automatic", "hybrid"].includes(policy.mode);
  const matchRule = policy.matchRule && typeof policy.matchRule === "object" && !Array.isArray(policy.matchRule) ? policy.matchRule : {};
  const externalKeyReady = matchRule.aggregate === true
    || (typeof policy.externalKey === "string" && Boolean(policy.externalKey.trim()));
  const matchRuleReady = Boolean(matchRule.reportType) && Object.keys(matchRule).length >= 2;
  const syncMapping = policy.mapping && typeof policy.mapping === "object" ? policy.mapping : {};
  const defaultMap = capabilities.defaultMapping && Object.keys(capabilities.defaultMapping).length > 0
    ? capabilities.defaultMapping
    : (DELIVERABLE_DEFAULT_MAPPINGS[item && item.id] || {});
  const hasDefaultMapping = Boolean(defaultMap && Object.keys(defaultMap).length > 0);
  const authorities = policy.fieldAuthority && typeof policy.fieldAuthority === "object"
    ? Object.entries(policy.fieldAuthority).filter(([, a]) => a === "automatic").map(([field]) => field)
    : [];
  const fieldMappingReady = (authorities.length > 0
    && Object.keys(syncMapping).length === authorities.length
    && Object.keys(syncMapping).every((field) => authorities.includes(field)))
    || (Object.keys(syncMapping).length > 0 && hasDefaultMapping);
  const ready = Boolean(syncSupported && policy.enabled === true && syncModeReady && policy.credentialAvailable === true
    && externalKeyReady && matchRuleReady && fieldMappingReady && stabilityReady);
  const missing = [];
  if (!ready) {
    if (!syncSupported) missing.push("该交付物不支持外部同步");
    if (policy.enabled !== true || !syncModeReady) missing.push("更新策略未启用或未选择自动/混合模式");
    if (policy.credentialAvailable !== true) missing.push("凭据未配置或状态未知");
    if (!externalKeyReady) missing.push("外部稳定键未确认");
    if (!matchRuleReady) missing.push("匹配规则未确认");
    if (!fieldMappingReady) missing.push("自动字段映射未确认");
    if (!stabilityReady) missing.push(`映射稳定性未就绪 (${mappingProgressText})`);
  }
  return { ready, supported: syncSupported, missing, message: missing.join("，") || "同步条件尚未满足", mappingProgressText };
}

// ---- unified status -------------------------------------------------------

export const UNIFIED_AUTH_LABELS = {
  unauthenticated: "未认证", credential_missing: "缺少凭据", credential_invalid: "凭据无效", authenticated: "已认证", unknown: "未知",
};
export const UNIFIED_QUERY_LABELS = {
  idle: "空闲", querying: "查询中", service_unavailable: "服务不可用", failed: "查询失败", no_match: "未匹配", matched: "已匹配",
};
export const UNIFIED_SYNC_LABELS = {
  idle: "空闲", manual: "手动维护", ready: "已就绪", running: "同步中", success: "成功",
  partial_success: "部分成功", needs_attention: "需要处理", failed: "失败",
};

export function unifiedStatusStateLabel(value, labels) {
  const normalized = String(value || "unknown");
  return labels[normalized] || safeDisplayValue(normalized);
}

export function unifiedStatusTone(value, group) {
  const normalized = String(value || "unknown");
  const successStates = { auth: ["authenticated"], query: ["matched"], sync: ["manual", "ready", "success"] };
  const errorStates = { auth: ["unauthenticated"], query: ["failed"], sync: ["failed"] };
  if ((successStates[group] || []).includes(normalized)) return "success";
  if ((errorStates[group] || []).includes(normalized)) return "error";
  return "warning";
}

/** Merge objects of the same kind, keeping the worse states (legacy byKind map). */
export function mergeUnifiedObjects(objects) {
  const byKind = new Map();
  const severity = { failed: 5, service_unavailable: 4, partial_success: 3, needs_attention: 3, running: 2, ready: 1, success: 0, idle: 0, manual: 0 };
  (Array.isArray(objects) ? objects : [])
    .filter((object) => object && typeof object === "object")
    .forEach((object) => {
      const kind = String(object.kind || "").toLowerCase();
      const previous = byKind.get(kind);
      if (!previous) {
        byKind.set(kind, object);
        return;
      }
      const errors = [...(Array.isArray(previous.errors) ? previous.errors : []), ...(Array.isArray(object.errors) ? object.errors : [])];
      const worse = (field) => ((severity[String(previous[field] || "").toLowerCase()] || 0) >= (severity[String(object[field] || "").toLowerCase()] || 0)
        ? previous[field]
        : object[field]);
      byKind.set(kind, {
        ...previous,
        ...object,
        auth_state: previous.auth_state === "credential_invalid"
          ? previous.auth_state
          : (object.auth_state === "credential_invalid" ? object.auth_state : object.auth_state || previous.auth_state),
        query_state: worse("query_state"),
        sync_state: worse("sync_state"),
        errors: [...new Set(errors)].slice(0, 4),
      });
    });
  return byKind;
}

// ---- debug bundle ---------------------------------------------------------

function debugBundleSensitiveKey(key) {
  const normalized = String(key).toLowerCase().replace(/[\s-]+/g, "_");
  return /(authorization|password|token|cookie|secret|session|csrf|credential|api_?key|private_?key)/i.test(normalized)
    || ["raw_xml", "file_id", "set-cookie", "sid", "arasauth"].includes(normalized);
}

export function redactDeliverableDebugValue(value) {
  if (Array.isArray(value)) return value.map((entry) => redactDeliverableDebugValue(entry));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, entry]) => [
      key,
      debugBundleSensitiveKey(key) ? "[FILTERED]" : redactDeliverableDebugValue(entry),
    ]));
  }
  return typeof value === "string" ? redactSensitiveText(value) : value;
}

export function buildDeliverableDebugSummary(bundle) {
  const lines = ["VSE 交付物诊断摘要", "敏感字段已过滤"];
  ["policy", "analytics", "mapping", "runs"].forEach((name) => {
    let payload = redactDeliverableDebugValue(bundle && bundle[name]);
    if (payload === undefined) payload = null;
    let serialized = "";
    try {
      serialized = JSON.stringify(payload, null, 2);
    } catch (_err) {
      serialized = "null";
    }
    lines.push(`\n[${name}]\n${serialized || "null"}`);
  });
  return lines.join("\n");
}
