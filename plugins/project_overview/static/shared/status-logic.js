// Pure display logic for the project-overview status / details pages.
// Faithful port of the legacy helpers in web/static/app.js (timeline math,
// syncDisplay state machine, ring/table display, auto-hide rule, scheduler
// text, deliverable edit validation) and web/static/node-overview.js.
// Import-free so it runs under Node for tests and can be reused by the other
// project-overview pages.

export const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export const OVERVIEW_DETAIL_COLUMNS = ["交付物", "状态", "计划完成", "实际完成或当前进度", "风险与备注", "数据来源"];

export const OVERVIEW_RING_TONES = {
  success: "var(--success)",
  primary: "var(--primary)",
  warning: "var(--warning)",
  error: "var(--error)",
};

export const OVERVIEW_STATUS_OPTIONS = ["已完成", "进行中", "待审批", "已逾期"];

export function isIsoDate(value) {
  const text = typeof value === "string" ? value.trim() : "";
  return Boolean(text && DATE_RE.test(text));
}

export function overviewIsEmpty(data) {
  return !data
    || !data.phase
    || !Array.isArray(data.milestones) || data.milestones.length === 0
    || !Array.isArray(data.deliverables) || data.deliverables.length === 0;
}

// ---------------------------------------------------------------------------
// Milestone timeline

export function milestoneProgressX(dateText, phase) {
  const start = new Date(`${phase.startDate}T00:00:00`);
  const end = new Date(`${phase.endDate}T00:00:00`);
  const current = new Date(`${dateText}T00:00:00`);
  const span = end.getTime() - start.getTime();
  if (!span) return 0;
  const ratio = (current.getTime() - start.getTime()) / span;
  return Math.min(100, Math.max(0, ratio * 100));
}

/** Dated milestones sit at their date; undated ones are spread evenly between neighbours. */
export function calculateMilestoneTimelineX(milestones, phase) {
  const sorted = [...(milestones || [])].sort((a, b) => (a.sortOrder || 0) - (b.sortOrder || 0));
  const count = sorted.length;
  if (count === 0) return [];
  const anchors = [];
  for (let i = 0; i < count; i += 1) {
    if (isIsoDate(sorted[i].date)) anchors.push({ index: i, x: milestoneProgressX(sorted[i].date.trim(), phase) });
  }
  const positions = new Array(count);
  if (anchors.length === 0) {
    for (let i = 0; i < count; i += 1) positions[i] = (100 * (i + 1)) / (count + 1);
  } else {
    anchors.forEach((anchor) => { positions[anchor.index] = anchor.x; });
    const first = anchors[0];
    for (let k = 0; k < first.index; k += 1) positions[k] = (first.x * (k + 1)) / (first.index + 1);
    for (let a = 0; a < anchors.length - 1; a += 1) {
      const left = anchors[a];
      const right = anchors[a + 1];
      const runLen = right.index - left.index - 1;
      for (let k = 0; k < runLen; k += 1) {
        positions[left.index + 1 + k] = left.x + ((right.x - left.x) * (k + 1)) / (runLen + 1);
      }
    }
    const last = anchors[anchors.length - 1];
    const tail = count - 1 - last.index;
    for (let k = 0; k < tail; k += 1) {
      positions[last.index + 1 + k] = last.x + ((100 - last.x) * (k + 1)) / (tail + 1);
    }
  }
  return sorted.map((milestone, idx) => ({ milestone, x: positions[idx] }));
}

/** Rail entries (today marker + milestones) in display order, with node labels resolved. */
export function buildTimelineEntries(data, activeNodeId = null) {
  const phase = data.phase;
  const entries = [
    { type: "today", date: phase.today, x: milestoneProgressX(phase.today, phase) },
    ...calculateMilestoneTimelineX(data.milestones || [], phase).map((item) => ({
      type: "milestone",
      milestone: item.milestone,
      date: item.milestone.date,
      x: item.x,
    })),
  ].sort((left, right) => {
    const leftDate = typeof left.date === "string" ? left.date.trim() : "";
    const rightDate = typeof right.date === "string" ? right.date.trim() : "";
    if (isIsoDate(leftDate) && isIsoDate(rightDate)) {
      const cmp = leftDate.localeCompare(rightDate);
      if (cmp !== 0) return cmp;
    }
    return left.x - right.x;
  });
  return entries.map((entry) => {
    if (entry.type === "today") {
      return { type: "today", x: entry.x, label: `今天 ${String(entry.date || "").slice(5)}` };
    }
    const milestone = entry.milestone;
    const undated = !isIsoDate(milestone.date);
    return {
      type: "milestone",
      id: milestone.id,
      name: milestone.name,
      x: entry.x,
      nodeType: undated ? "planned" : (milestone.type || "planned"),
      nodeStatus: undated ? "未开始" : (milestone.status || "未开始"),
      dateText: undated ? "待排期" : milestone.date.trim().slice(5),
      active: activeNodeId !== null && activeNodeId !== undefined && milestone.id === activeNodeId,
    };
  });
}

// ---------------------------------------------------------------------------
// Current-node focus (port of web/static/node-overview.js)

const NOTE_PLACEHOLDERS = ["无", "待同步", "—", "-"];
const nodeHasValue = (item) => !item.syncDisplay || ["manual", "snapshot"].includes(item.syncDisplay.state);
const nodeStatus = (item) => item.status || item.effectiveStatus;
const hasNote = (item) => Boolean(item.note && !NOTE_PLACEHOLDERS.includes(String(item.note).trim()));
const nodeHasDataIssue = (item) => !nodeHasValue(item)
  || Boolean(item.syncDisplay && ["failed", "needs_attention"].includes(item.syncDisplay.syncState));
const nodeScheduleOverdue = (item) => item.scheduleState === "overdue" && (!item.syncDisplay || item.syncDisplay.state !== "snapshot");
const nodeIsRisk = (item) => nodeHasValue(item) && nodeStatus(item) !== "已完成" && (
  ["已逾期", "已超期", "受阻"].includes(nodeStatus(item)) || nodeScheduleOverdue(item) || hasNote(item)
);

/**
 * Locate the first unfinished milestone (by plan order, overdue ones are not skipped).
 * `rules` maps a milestone id to its deliverable ids; with no rule nothing is counted.
 */
export function buildNodeContext(data, rules = {}) {
  const milestones = [...(data.milestones || [])].sort((a, b) => (a.sortOrder || 0) - (b.sortOrder || 0));
  const node = milestones.find((item) => !["已完成", "已达成", "done"].includes(item.status)) || null;
  const all = data.deliverables || [];
  const ids = node && Object.prototype.hasOwnProperty.call(rules, String(node.id)) ? rules[String(node.id)] : null;
  const known = new Set(all.map((item) => item.id));
  const ruleConfigured = Array.isArray(ids) && ids.every((id) => typeof id === "string" && known.has(id));
  const items = ruleConfigured ? all.filter((item) => ids.includes(item.id)) : [];
  const completed = ruleConfigured ? items.filter((item) => nodeHasValue(item) && nodeStatus(item) === "已完成").length : null;
  const total = ruleConfigured ? items.length : null;
  const today = data.phase && data.phase.today;
  const delta = node && node.date && today ? (Date.parse(node.date) - Date.parse(today)) / 86400000 : NaN;
  return {
    node,
    ruleConfigured,
    items,
    total,
    completed,
    days: Number.isFinite(delta) ? Math.round(delta) : null,
    progress: total ? Math.round((completed / total) * 100) : null,
    risks: items.filter(nodeIsRisk),
    dataIssues: items.filter(nodeHasDataIssue),
    projectRisks: all.filter(nodeIsRisk),
    projectDataIssues: all.filter(nodeHasDataIssue),
  };
}

export function nodeTimingText(days) {
  if (days === null || days === undefined) return "待排期";
  if (days < 0) return `已超期 ${-days} 天`;
  if (days === 0) return "计划今天完成";
  return `距离计划日期还有 ${days} 天`;
}

export function nodeFocusTitle(ctx, milestones) {
  if (ctx.node) return ctx.node.name;
  return (milestones || []).length ? "主计划节点已全部完成" : "主计划待设置";
}

export function nodeRiskRow(item) {
  const reason = nodeScheduleOverdue(item)
    ? `计划已逾期${Number.isFinite(item.scheduleDays) ? ` ${item.scheduleDays} 天` : ""}`
    : nodeStatus(item);
  const note = hasNote(item) ? ` · ${item.note}` : "";
  return {
    id: item.id,
    name: item.name,
    text: `${reason}${note}`,
    meta: `负责人：${item.owner || "未填写"} · 计划：${item.plannedDate || "待排期"}`,
  };
}

export function nodeItemLabel(item) {
  return nodeHasValue(item) ? nodeStatus(item) : (item.syncDisplay.label || item.syncDisplay.state);
}

export function nodeDataIssueLabel(item) {
  return nodeHasValue(item) ? "更新异常 · 保留上次快照" : (item.syncDisplay.label || item.syncDisplay.state);
}

// ---------------------------------------------------------------------------
// Deliverable display state (syncDisplay state machine + snapshot fallback)

export const SYNC_DISPLAY_VALUE_STATES = new Set(["manual", "snapshot"]);
export const SYNC_DISPLAY_RING_LABELS = {
  paused: "已暂停",
  pending_config: "待配置",
  pending_first_sync: "待同步",
  sync_failed: "同步失败",
  no_source_records: "无记录",
};

/** Snapshot summary only when the deliverable's own sync is enabled (manual values win otherwise). */
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
    if (policy.aggregate === true) return null;
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

export function deliverablePendingDateLabel(item, today) {
  const planned = item.plannedDate ? `计划完成 ${item.plannedDate.slice(5)}` : "计划完成 -";
  if (!today || !item.plannedDate) return planned;
  const delta = Math.floor((new Date(today) - new Date(item.plannedDate)) / 86400000);
  return delta > 0 ? `${planned}；已逾期 ${delta} 天（待同步）` : planned;
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

export function deliverableProgressOrDate(item) {
  if (item.status === "已完成") return item.actualDate || item.progressOrDate || "100%";
  if (item.progressOrDate) return item.progressOrDate;
  if (item.progress !== null && item.progress !== undefined) return `${item.progress}%`;
  return "-";
}

export function ringDateLabel(item) {
  if (item.status === "已完成") {
    const value = deliverableProgressOrDate(item);
    return value.endsWith("%") ? `完成度 ${value}` : `实际完成 ${value.slice(5)}`;
  }
  return item.plannedDate ? `计划完成 ${item.plannedDate.slice(5)}` : "计划完成 -";
}

export function deliverableBoardVisible(item) {
  return !item || item.boardVisible !== false;
}

export function deliverableManualEditState(item) {
  const reason = String((item && item.readOnlyReason) || "").trim();
  if (item && item.manualEditable === true) return { editable: true, reason: "" };
  return { editable: false, reason: reason || "该交付物当前由系统同步维护，手工字段只读。" };
}

// “按节点状态自动显示”：已完成且项目已越过其关联主计划节点的交付物不再展示。
export const DELIVERABLE_AUTO_HIDE_NODE_KEYWORDS = {
  "VPI-T2-D1": ["VDR"],
  "VPI-T2-D2": ["VPI"],
  "VPI-T2-D3": ["T2"],
  "VPI-T2-D4": ["VDR"],
  "VPI-T2-D5": ["T2"],
};

export function deliverableNodeReached(keywords, state) {
  const milestones = state && Array.isArray(state.milestones) ? state.milestones : [];
  const today = state && state.phase && state.phase.today ? String(state.phase.today) : "";
  if (!today) return false;
  const wanted = keywords.map((keyword) => String(keyword).toUpperCase());
  return milestones.some((milestone) => {
    const name = String(milestone.name || "").toUpperCase();
    const date = String(milestone.date || "");
    if (!date) return false;
    const tokens = name.split(/[\s·/()（）%]+/).filter(Boolean);
    return wanted.some((keyword) => tokens.includes(keyword)) && date <= today;
  });
}

export function shouldShowDeliverable(item, filterValue, state) {
  if (filterValue !== "auto") return true;
  const keywords = DELIVERABLE_AUTO_HIDE_NODE_KEYWORDS[item.id];
  if (!keywords || !keywords.length) return true;
  if (!deliverableHasDisplayValue(item)) return true;
  const formDisplay = deliverableFormDisplay(item);
  const status = formDisplay ? formDisplay.status : item.status;
  if (status !== "已完成") return true;
  return !deliverableNodeReached(keywords, state);
}

export function autoHiddenCount(deliverables, filterValue, state) {
  return (deliverables || []).filter(
    (item) => deliverableBoardVisible(item) && !shouldShowDeliverable(item, filterValue, state),
  ).length;
}

export function autoHiddenHint(deliverables, filterValue, state) {
  const count = autoHiddenCount(deliverables, filterValue, state);
  return filterValue === "auto" && count ? `已隐藏 ${count} 项已完成交付物` : "";
}

/** Card model for one 全项目交付物完成状态 ring. */
export function progressRingModel(rawItem, state) {
  const item = deliverableDisplayItem(rawItem);
  const syncDisplay = deliverableSyncDisplay(item);
  const hasValue = SYNC_DISPLAY_VALUE_STATES.has(syncDisplay.state);
  const statusText = deliverableStatusText(item, item);
  const tone = hasValue ? deliverableTone(item) : "primary";
  const today = state && state.phase ? state.phase.today : "";
  return {
    id: item.id,
    name: item.name,
    hasValue,
    progress: hasValue ? item.progress : 0,
    color: hasValue ? (OVERVIEW_RING_TONES[deliverableTone(item)] || "var(--muted)") : "var(--muted)",
    center: hasValue ? `${item.progress}%` : (SYNC_DISPLAY_RING_LABELS[syncDisplay.state] || syncDisplay.label),
    statusText,
    tone,
    dateLabel: hasValue ? ringDateLabel(item) : deliverablePendingDateLabel(item, today),
    ariaLabel: `${item.name}，${hasValue ? `完成度 ${item.progress}%，状态 ${statusText}` : `状态 ${syncDisplay.label}`}，查看明细`,
    title: item.note ? `${item.name}（${item.status}）：${item.note}` : "",
  };
}

export function visibleProgressRings(state, filterValue) {
  const deliverables = (state && state.deliverables) || [];
  return deliverables
    .filter((item) => deliverableBoardVisible(item) && shouldShowDeliverable(item, filterValue, state))
    .map((item) => progressRingModel(item, state));
}

// ---------------------------------------------------------------------------
// Details tab

export function detailsSummaryCells(phase) {
  return [
    ["当前阶段", phase.id],
    ["阶段状态", phase.status],
    ["总体进度", `${phase.overallProgress}%`],
    ["阶段周期", `${phase.startDate} 至 ${phase.endDate}`],
  ];
}

/** Row model for the 交付物明细 table; `values` follow OVERVIEW_DETAIL_COLUMNS. */
export function detailRowModel(rawRow, index) {
  const item = deliverableDisplayItem(rawRow);
  const manual = deliverableManualEditState(item);
  const syncDisplay = deliverableSyncDisplay(item);
  const hasValue = SYNC_DISPLAY_VALUE_STATES.has(syncDisplay.state);
  const snapshot = deliverableSnapshotSummary(item);
  const overdue = snapshot ? Number(snapshot.summary.overdue) : 0;
  return {
    index,
    id: item.id,
    name: item.name,
    values: [
      item.name,
      deliverableStatusText(item, item),
      item.plannedDate,
      hasValue ? deliverableProgressOrDate(item) : syncDisplay.label,
      item.note,
      item.source,
    ],
    statusTone: hasValue ? deliverableTone(item) : "primary",
    riskNote: item.status === "已逾期" && snapshot && overdue > 0
      ? {
        text: `${snapshot.summary.overdue}单超期`,
        title: `快照中存在 ${snapshot.summary.overdue} 笔在途工单超过完成时限，交付物推进进度为 ${item.progress}%`,
      }
      : null,
    editable: manual.editable,
    readOnlyReason: manual.reason,
    target: item.isExternalArchive
      ? { page: "archive-deliverable", params: { job: item.externalJobKey } }
      : { page: "deliverable", params: { id: item.id } },
  };
}

/** Rows keep their payload index; board-hidden deliverables are skipped, never renumbered. */
export function detailRows(state) {
  const rows = Array.isArray(state && state.deliverables) ? state.deliverables : [];
  const models = [];
  rows.forEach((row, index) => {
    if (deliverableBoardVisible(row)) models.push(detailRowModel(row, index));
  });
  return models;
}

/** 外部来源交付物（参考）: catalog entries that carry a `links` object. */
export function externalReferenceRows(catalogItems) {
  return (Array.isArray(catalogItems) ? catalogItems : [])
    .filter((entry) => entry && typeof entry.links === "object" && entry.links)
    .map((entry) => ({
      name: entry.name,
      code: entry.links.displayCode ? String(entry.links.displayCode) : "未关联项目交付物",
      jobKey: String(entry.links.archiveJobKey || ""),
    }));
}

// ---------------------------------------------------------------------------
// Deliverable sync scheduler bar

export const SCHEDULER_INTERVAL_OPTIONS = [
  [900, "每 15 分钟（默认）"],
  [1800, "每 30 分钟"],
  [3600, "每 1 小时"],
  [0, "暂停自动调度"],
];

export function formatCountdown(seconds) {
  const known = seconds !== null && seconds !== undefined;
  const mins = known ? Math.floor(seconds / 60) : 0;
  const secs = known ? seconds % 60 : 0;
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

export function schedulerView(status, countdown) {
  const paused = status.paused === true;
  const count = status.eligibleCount || 0;
  const lastTickAt = status.lastTickAt;
  return {
    paused,
    indicatorClass: paused ? "is-paused" : "is-running",
    indicatorText: paused ? "⏸️ 自动同步已暂停" : "🟢 交付物自动同步：运行中",
    pauseLabel: paused ? "恢复调度" : "暂停调度",
    intervalValue: paused ? "0" : String(status.intervalSeconds || 900),
    meta: paused
      ? `已暂停自动轮询（${count}项交付物绑定）· 上次完成：${lastTickAt || "暂无"}`
      : `下次自动同步：${formatCountdown(countdown)}（共${count}项已启用交付物）· 上次完成：${lastTickAt ? String(lastTickAt).slice(11, 19) : "无"}`,
  };
}

export function schedulerConfigPayload(intervalValue) {
  const value = parseInt(intervalValue, 10);
  return value === 0 ? { paused: true } : { intervalSeconds: value, paused: false };
}

export function intervalChangedMessage(intervalValue) {
  const value = parseInt(intervalValue, 10);
  if (value === 0) return "已暂停交付物自动同步调度。";
  const option = SCHEDULER_INTERVAL_OPTIONS.find(([seconds]) => seconds === value);
  return `自动同步频率已调整为 ${option ? option[1] : `${value} 秒`}。`;
}

export function syncAllMessage(data) {
  const results = (data && Array.isArray(data.results)) ? data.results : [];
  const successes = results.filter((result) => result && result.status === "success").length;
  return `全量同步完成：成功同步 ${successes}/${results.length} 项交付物。`;
}

// ---------------------------------------------------------------------------
// Manual deliverable edit (row editor + inline note editor)

export const DELIVERABLE_EDIT_FIELDS = [
  ["status", "状态"],
  ["owner", "负责人"],
  ["plannedDate", "计划完成日期"],
  ["actualDate", "实际完成日期"],
  ["progress", "当前进度（0-100）"],
  ["note", "风险与备注"],
];

export function draftValuesFromItem(item) {
  return {
    status: item.status || "",
    owner: item.owner || "",
    plannedDate: item.plannedDate || "",
    actualDate: item.actualDate || "",
    progress: item.progress === null || item.progress === undefined ? "" : String(item.progress),
    note: item.note || "",
  };
}

export function draftDirty(saved, values) {
  if (!saved || !values) return false;
  return DELIVERABLE_EDIT_FIELDS.some(([name]) => saved[name] !== values[name]);
}

export function validateDeliverableDraft(values) {
  const errors = {};
  const status = String(values.status || "").trim();
  const owner = String(values.owner || "").trim();
  const plannedDate = String(values.plannedDate || "").trim();
  const actualDate = String(values.actualDate || "").trim();
  const progressRaw = String(values.progress || "").trim();
  if (!status) errors.status = "请选择状态";
  if (!owner) errors.owner = "负责人为必填项";
  if (!plannedDate) errors.plannedDate = "计划完成日期为必填项";
  else if (!DATE_RE.test(plannedDate)) errors.plannedDate = "日期格式应为 YYYY-MM-DD";
  if (progressRaw === "") {
    errors.progress = "当前进度为必填项";
  } else {
    const progress = Number(progressRaw);
    if (!Number.isInteger(progress) || progress < 0 || progress > 100) errors.progress = "当前进度必须是 0 到 100 的整数";
  }
  if (status === "已完成") {
    const progress = Number(progressRaw);
    if (progressRaw !== "" && Number.isInteger(progress) && progress !== 100) errors.progress = "已完成交付物的进度必须为 100";
    if (!actualDate) errors.actualDate = "已完成交付物必须填写实际完成日期";
    else if (!DATE_RE.test(actualDate)) errors.actualDate = "日期格式应为 YYYY-MM-DD";
  } else if (actualDate) {
    errors.actualDate = "未完成的交付物不应填写实际完成日期";
  }
  return errors;
}

export function deliverablePatchPayload(values, item) {
  return {
    status: values.status.trim(),
    owner: values.owner.trim(),
    plannedDate: values.plannedDate,
    actualDate: values.actualDate,
    progress: Number(values.progress),
    note: values.note.trim(),
    updatedAt: item.updatedAt || "",
  };
}

/** Inline 风险与备注 edit keeps every other field at the latest saved value. */
export function notePatchPayload(item, note) {
  return {
    status: item.status,
    owner: item.owner,
    plannedDate: item.plannedDate,
    actualDate: item.actualDate,
    progress: item.progress,
    note,
    updatedAt: item.updatedAt || "",
  };
}

const SERVER_FIELD_MAP = {
  status: "status",
  owner: "owner",
  plannedDate: "plannedDate",
  actualDate: "actualDate",
  progress: "progress",
  note: "note",
  planned_date: "plannedDate",
  actual_date: "actualDate",
};

export function mapServerFieldErrors(fields) {
  const errors = {};
  Object.keys(fields || {}).forEach((key) => {
    const name = SERVER_FIELD_MAP[key];
    if (name) errors[name] = String(fields[key]);
  });
  return errors;
}

/** Legacy overview error text: server message plus （HTTP n）; 403 is the local-only guard. */
export function overviewErrorText(error) {
  if (!error) return "";
  const status = Number(error.status) || 0;
  if (status === 403) return "该操作只允许在本机浏览器中执行";
  const message = String(error.message || error);
  if (!status || /（HTTP \d+）$/.test(message)) return message;
  return `${message}（HTTP ${status}）`;
}
