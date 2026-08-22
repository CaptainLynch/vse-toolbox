const THEME_KEY = "vse-toolbox-theme";

const SENSITIVE_COLUMNS = new Set([
  "raw_xml",
  "file_id",
  "authorization",
  "set-cookie",
  "cookie",
  "token",
  "api_key",
  "sid",
  "sessionid",
  "arasauth",
  "jsessionid",
  "csrf",
  "secret",
  "password",
]);

const SENSITIVE_VALUE_PATTERNS = [
  [/(['"])(authorization|set-cookie|cookie|token|api_key|sid|sessionid|arasauth|jsessionid|csrf|secret|password)\1\s*:\s*(['"])(?:\\.|(?!\3)[\s\S])*\3/gi, "$1$2$1:$3[redacted]$3"],
  [/\b(authorization)\b(\s*[:=]\s*)(.*?)(?=(?:\s|,\s*)\b(?:set-cookie|cookie|token|api_key|sid|sessionid|arasauth|jsessionid|csrf|secret|password)\b\s*[:=]|[\r\n}\]\[]|$)/gi, "$1$2[redacted]"],
  [/\b(set-cookie|cookie)\b(\s*[:=]\s*)(.*?)(?=(?:\s|,\s*)\b(?:authorization|set-cookie|cookie)\b\s*:|[\r\n}\]\[]|$)/gi, "$1$2[redacted]"],
  [/\b(token|api_key|sid|sessionid|arasauth|jsessionid|csrf|secret|password)\b(\s*[:=]\s*)(?:Bearer\s+)?([^,\s;'"}}\]\[]+)/gi, "$1$2[redacted]"],
  [/\b(authorization|cookie|token|api_key|sid|sessionid|arasauth|jsessionid|csrf|secret|password)=([^&\s,;'"}}\]\[]+)/gi, "$1=[redacted]"],
  [/\bBearer\s+([^,\s;'"}}\]\[]+)/gi, "Bearer [redacted]"],
];

const ARAS_MODES = {
  ewo: {
    endpoint: "/api/aras/ewo/query",
    exportEndpoint: "/api/aras/ewo/export",
    exportNumberNames: ["max_records", "max_pages"],
    exportLabel: "全量导出 CSV",
    defaultFileName: "aras-ewo-export.csv",
    submitLabel: "查询预览",
    fieldGroup: "ewo",
    filterNames: ["ewo_no", "project_code", "subject_keyword", "change_type", "change_sub_type", "area", "state", "rsp_department", "submit_start", "submit_end"],
    numberNames: ["page", "page_size", "max_records"],
    preferredColumns: ["_no", "_eplmwriteneplcode", "_subject", "_area", "_sort_type", "_rsp_department", "_submit_time", "state"],
    resultKind: "rows",
  },
  paa: {
    endpoint: "/api/aras/paa/query",
    exportEndpoint: "/api/aras/paa/export",
    exportNumberNames: ["max_records", "max_pages"],
    exportLabel: "全量导出 CSV",
    defaultFileName: "aras-paa-export.csv",
    submitLabel: "查询预览",
    fieldGroup: "paa",
    filterNames: ["paa_no", "ewo_no", "state", "area", "base", "department", "vehicle_keyword", "submit_start", "submit_end", "mtl_rq_start", "mtl_rq_end"],
    numberNames: ["page", "page_size", "max_records"],
    preferredColumns: ["_no", "_ewo_no", "state", "_area", "_base", "_vehicles", "_submit_date", "_mtl_rq_date"],
    resultKind: "rows",
  },
  "paa-all": {
    endpoint: "/api/aras/paa/crawl-all",
    exportEndpoint: "/api/aras/paa/export",
    exportNumberNames: ["max_records", "max_pages"],
    exportLabel: "全量导出 CSV",
    defaultFileName: "aras-paa-export.csv",
    submitLabel: "查询预览",
    fieldGroup: "paa",
    filterNames: ["paa_no", "ewo_no", "state", "area", "base", "department", "vehicle_keyword", "submit_start", "submit_end", "mtl_rq_start", "mtl_rq_end"],
    numberNames: ["page_size", "max_records", "max_pages"],
    preferredColumns: ["_no", "_ewo_no", "state", "_area", "_base", "_vehicles", "_submit_date", "_mtl_rq_date"],
    resultKind: "rows",
  },
  "ncr-progress": {
    endpoint: "/api/aras/ncr/progress",
    downloadEndpoint: "/api/aras/ncr/progress/download",
    exportLabel: "生成并下载",
    defaultFileName: "aras-ncr-progress.xlsx",
    submitLabel: "执行查询",
    fieldGroup: "ncr",
    filterNames: ["buy_start", "buy_end", "pe_start", "pe_end", "ncr_no", "project_names", "department", "section_code", "change_type", "othercondition"],
    numberNames: [],
    preferredColumns: [],
    resultKind: "summary",
  },
  "ncr-detail": {
    endpoint: "/api/aras/ncr/detail",
    downloadEndpoint: "/api/aras/ncr/detail/download",
    exportLabel: "生成并下载",
    defaultFileName: "aras-ncr-detail.xlsx",
    submitLabel: "执行查询",
    fieldGroup: "ncr",
    filterNames: ["buy_start", "buy_end", "pe_start", "pe_end", "ncr_no", "project_names", "department", "section_code", "change_type", "othercondition"],
    numberNames: [],
    preferredColumns: [],
    resultKind: "summary",
  },
};

let arasMode = "ewo";
let arasRunning = false;
let arasQueuedAction = "";
let arasRequestSeq = 0;
let arasLatestRendered = 0;

const COMMAND_LABELS = {
  ewo: "EWO",
  paa: "PAA",
  "paa-all": "PAA 全量",
  "ncr-progress": "NCR 进度",
  "ncr-detail": "NCR 明细",
};

const RESULT_KIND_LABELS = {
  rows: "列表",
  summary: "摘要",
};

const DELIVERABLE_STATUS_LABELS = {
  "已完整实现": "已完整实现",
  "后端已实现、前端缺失": "后端已实现、前端缺失",
  "部分实现": "部分实现",
  "仅占位": "仅占位",
  "仅文档规划": "仅文档规划",
  "未发现实现证据": "未发现实现证据",
};

const DELIVERABLE_STATUS_TONE_CLASS = {
  "已完整实现": "is-fully-implemented",
  "后端已实现、前端缺失": "is-backend-no-frontend",
  "部分实现": "is-partial",
  "仅占位": "is-placeholder",
  "仅文档规划": "is-doc-only",
  "未发现实现证据": "is-no-evidence",
};

const DELIVERABLE_AVAILABILITY_LABELS = {
  available: "可用",
  cli_only: "仅 CLI",
  partial: "部分可用",
  disabled: "已禁用",
};

const DELIVERABLE_OPERATION_LABELS = {
  query: "查询预览",
  crawl_all: "全量抓取",
  export: "导出 XLSX",
  download: "生成并下载",
  cli: "CLI",
};

const TDC_ENDPOINTS = {
  "tdc-data-model": {
    slug: "data-model",
    defaultExportName: "tdc_data_model.xlsx",
    endpoints: {
      query: "/api/tdc/data-model/query",
      crawl_all: "/api/tdc/data-model/crawl-all",
      export: "/api/tdc/data-model/export",
    },
  },
  "tdc-sor": {
    slug: "sor",
    defaultExportName: "tdc_sor_part_details.xlsx",
    endpoints: {
      query: "/api/tdc/sor/query",
      crawl_all: "/api/tdc/sor/crawl-all",
      export: "/api/tdc/sor/export",
    },
  },
};

const RECENT_RUN_LIMIT = 8;

let deliverableCatalogLoaded = false;
let deliverableCatalog = [];
let deliverableCategories = [];
let selectedDeliverableId = "";
let recentRuns = [];
let deliverableRunning = false;
let deliverableRequestSeq = 0;
let deliverableLatestRendered = 0;

function preferredTheme() {
  const stored = localStorage.getItem(THEME_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme) {
  const nextTheme = theme === "dark" ? "dark" : "light";
  document.body.dataset.theme = nextTheme;
  const label = document.getElementById("theme-label");
  if (label) label.textContent = nextTheme === "dark" ? "深色" : "浅色";
}

function setupTheme() {
  const button = document.getElementById("theme-toggle");
  if (!button) return;
  button.addEventListener("click", () => {
    const nextTheme = document.body.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem(THEME_KEY, nextTheme);
    applyTheme(nextTheme);
  });
}

const OVERVIEW_DETAIL_COLUMNS = ["交付物", "状态", "负责人", "计划完成", "实际完成或当前进度", "风险与备注", "数据来源"];

const OVERVIEW_RING_TONES = {
  success: "var(--success)",
  primary: "var(--primary)",
  warning: "var(--warning)",
  error: "var(--error)",
};

const OVERVIEW_STATUS_OPTIONS = ["已完成", "进行中", "待审批", "已逾期"];

const MILESTONE_TYPE_OPTIONS = [
  { value: "done", label: "已达成" },
  { value: "current", label: "当前目标节点" },
  { value: "planned", label: "计划节点" },
];

const MILESTONE_LABEL_BY_TYPE = {
  done: "已达成",
  current: "当前目标节点",
  planned: "计划节点",
};

let overviewSavedState = null;
let overviewLoading = false;
let overviewLoadError = null;
let overviewDraft = null;
let overviewSaving = false;
let milestoneLocalSeq = 0;

function overviewEl(tagName, className, text) {
  const node = document.createElement(tagName);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function clearOverviewContainer(container) {
  if (container) container.textContent = "";
}

function renderOverviewLoading(container) {
  clearOverviewContainer(container);
  container.appendChild(overviewEl("p", "loading", "加载中"));
}

function renderOverviewEmpty(container) {
  clearOverviewContainer(container);
  container.appendChild(overviewEl("p", "is-empty", "暂无数据"));
}

function renderOverviewError(container, message) {
  clearOverviewContainer(container);
  const text = `加载失败：${redactSensitiveText(String(message))}`;
  container.appendChild(overviewEl("p", "error-msg", text));
}

function renderOverviewLoadError(container, message) {
  clearOverviewContainer(container);
  const box = overviewEl("div", "overview-load-error");
  box.appendChild(overviewEl("p", "error-msg", `加载失败：${redactSensitiveText(String(message))}`));
  const retry = overviewEl("button", "overview-retry-btn", "重试");
  retry.type = "button";
  retry.addEventListener("click", () => loadProjectOverview());
  box.appendChild(retry);
  container.appendChild(box);
}

function overviewReadJson(response) {
  return response.json().catch(() => null);
}

function overviewErrorMessage(body, status) {
  const error = body && body.error ? body.error : null;
  if (error && error.message) return `${error.message}（HTTP ${status}）`;
  return `请求失败（HTTP ${status}）`;
}

function overviewRequestError(body, status) {
  const error = body && body.error ? body.error : null;
  const err = new Error(overviewErrorMessage(body, status));
  err.status = status;
  err.fields = error && error.fields && typeof error.fields === "object" ? error.fields : null;
  return err;
}

function formatApiErrorMessage(err, fallbackStatus) {
  const message = `${err.type || "错误"}: ${err.message || `HTTP ${fallbackStatus}`}`;
  const path = err.diagnosticPath;
  return path
    ? `${message}｜诊断报告已保存：${path}`
    : message;
}

function renderTableState(tbody, state, message) {
  if (!tbody) return;
  tbody.textContent = "";
  const row = document.createElement("tr");
  const cell = overviewEl("td", null);
  cell.colSpan = 8;
  const className = state === "error" ? "error-msg" : state === "empty" ? "is-empty" : "loading";
  const text = state === "error"
    ? `加载失败：${redactSensitiveText(String(message))}`
    : state === "empty" ? "暂无数据" : "加载中";
  cell.appendChild(overviewEl("p", className, text));
  row.appendChild(cell);
  tbody.appendChild(row);
}

function overviewIsEmpty(data) {
  return !data
    || !data.phase
    || !Array.isArray(data.milestones) || data.milestones.length === 0
    || !Array.isArray(data.deliverables) || data.deliverables.length === 0;
}

function milestoneProgressX(dateText, phase) {
  const start = new Date(`${phase.startDate}T00:00:00`);
  const end = new Date(`${phase.endDate}T00:00:00`);
  const current = new Date(`${dateText}T00:00:00`);
  const span = end.getTime() - start.getTime();
  if (!span) return 0;
  const ratio = (current.getTime() - start.getTime()) / span;
  return Math.min(100, Math.max(0, ratio * 100));
}

function renderMilestoneTimeline(container, data) {
  clearOverviewContainer(container);
  const phase = data.phase;
  const head = overviewEl("div", "band-head");
  const headCopy = overviewEl("div");
  headCopy.append(overviewEl("p", "eyebrow", "主计划"), overviewEl("h4", null, `${phase.id} 主计划时间轴`));
  head.appendChild(headCopy);
  const headActions = overviewEl("div", "timeline-head-actions");
  headActions.appendChild(overviewEl("p", "timeline-meta", `当前阶段关键节点 · ${phase.startDate} 至 ${phase.endDate} · 当前日期 ${phase.today}`));
  const editButton = overviewEl("button", "timeline-edit-btn", null);
  editButton.type = "button";
  editButton.title = "编辑主计划";
  editButton.setAttribute("aria-label", "编辑主计划");
  editButton.append(overviewPencilIcon(), overviewEl("span", null, "编辑主计划"));
  editButton.addEventListener("click", openMilestoneEditor);
  headActions.appendChild(editButton);
  head.appendChild(headActions);
  container.appendChild(head);

  const wrap = overviewEl("div", "timeline-wrap");
  const months = overviewEl("div", "timeline-months");
  months.setAttribute("aria-hidden", "true");
  data.months.forEach((month) => months.appendChild(overviewEl("span", null, month)));
  wrap.appendChild(months);

  const rail = overviewEl("div", "timeline-rail");
  rail.setAttribute("role", "list");
  const line = overviewEl("div", "timeline-line");
  line.setAttribute("aria-hidden", "true");
  rail.appendChild(line);

  const timelineEntries = [{ type: "today", date: phase.today }, ...data.milestones]
    .sort((left, right) => left.date.localeCompare(right.date));
  timelineEntries.forEach((entry) => {
    if (entry.type === "today") {
      const today = overviewEl("div", "today-marker");
      today.style.setProperty("--x", String(milestoneProgressX(entry.date, phase)));
      today.appendChild(overviewEl("span", "today-label", `今天 ${entry.date.slice(5)}`));
      rail.appendChild(today);
      return;
    }
    const milestone = entry;
    const node = overviewEl("div", `milestone-node is-${milestone.type}`);
    node.setAttribute("role", "listitem");
    node.style.setProperty("--x", String(milestoneProgressX(milestone.date, phase)));
    node.appendChild(overviewEl("span", "milestone-dot", null));
    const copy = overviewEl("span", "milestone-copy");
    copy.append(
      overviewEl("strong", "milestone-name", milestone.name),
      overviewEl("time", "milestone-date", milestone.date.slice(5)),
      overviewEl("small", "milestone-status", milestone.status),
    );
    node.appendChild(copy);
    rail.appendChild(node);
  });
  wrap.appendChild(rail);
  container.appendChild(wrap);
}

function renderPhaseSummary(container, phase) {
  clearOverviewContainer(container);
  const grid = overviewEl("div", "phase-summary-grid");
  const cells = [
    ["当前阶段", phase.id],
    ["阶段状态", phase.status],
    ["总体进度", `${phase.overallProgress}%`],
    ["已完成", `${phase.completedCount} / ${phase.totalCount}`],
    ["风险 / 逾期", String(phase.riskCount)],
  ];
  cells.forEach(([label, value], index) => {
    const cell = overviewEl("div", "phase-cell");
    cell.append(overviewEl("span", "phase-label", label), overviewEl("strong", "phase-value", value));
    if (index === 2) {
      const track = overviewEl("span", "phase-track");
      const fill = overviewEl("span", "phase-track-fill");
      fill.style.width = `${phase.overallProgress}%`;
      track.appendChild(fill);
      cell.appendChild(track);
    }
    grid.appendChild(cell);
  });
  const updated = overviewEl("p", "phase-updated", `最近更新 ${phase.updatedAt}`);
  container.append(grid, updated);
}

function deliverableTone(item) {
  if (item.tone) return item.tone;
  if (item.status === "已完成") return "success";
  if (item.status === "已逾期") return "error";
  if (item.status === "待审批") return "warning";
  return "primary";
}

function deliverableProgressOrDate(item) {
  if (item.status === "已完成") {
    return item.actualDate || item.progressOrDate || "100%";
  }
  if (item.progressOrDate) return item.progressOrDate;
  if (item.progress !== null && item.progress !== undefined) return `${item.progress}%`;
  return "-";
}

function ringDateLabel(item) {
  if (item.status === "已完成") return `实际完成 ${deliverableProgressOrDate(item).slice(5)}`;
  const label = item.plannedDate ? `计划完成 ${item.plannedDate.slice(5)}` : "计划完成 -";
  return item.status === "已逾期" && item.note ? `${label}；${item.note}` : label;
}

function renderDeliverableProgress(container, deliverables) {
  clearOverviewContainer(container);
  deliverables.forEach((item) => {
    const card = overviewEl("article", "progress-ring");
    card.setAttribute("role", "img");
    card.setAttribute("aria-label", `${item.name}，完成度 ${item.progress}%，状态 ${item.status}`);
    const visual = overviewEl("span", "ring-visual");
    visual.style.setProperty("--progress", String(item.progress));
    visual.style.setProperty("--ring-color", OVERVIEW_RING_TONES[deliverableTone(item)] || "var(--muted)");
    visual.appendChild(overviewEl("span", "ring-center", `${item.progress}%`));
    const copy = overviewEl("span", "ring-copy");
    copy.append(
      overviewEl("strong", "ring-name", item.name),
      overviewEl("span", `ring-status is-${item.tone}`, item.status),
      overviewEl("span", "ring-date", ringDateLabel(item)),
    );
    card.append(visual, copy);
    container.appendChild(card);
  });
}

function renderRiskSummary(container, summary) {
  clearOverviewContainer(container);
  const meta = overviewEl("div", "risk-meta");
  const cells = [
    ["整体完成", summary.overall],
    ["计划进度", summary.planned],
    ["偏差", summary.variance],
  ];
  cells.forEach(([label, value]) => {
    const cell = overviewEl("div", "risk-cell");
    cell.append(overviewEl("span", "risk-label", label), overviewEl("strong", "risk-value", value));
    meta.appendChild(cell);
  });
  const alert = overviewEl("p", "risk-alert");
  alert.append(overviewEl("span", "risk-alert-label", "风险"), overviewEl("span", "risk-alert-text", summary.risk));
  const snapshot = overviewEl("p", "risk-snapshot");
  snapshot.append(
    overviewEl("span", "risk-label", "数据快照"),
    overviewEl("strong", "risk-value", summary.snapshot),
  );
  container.append(meta, alert, snapshot);
}

function renderDetailsSummary(container, data) {
  clearOverviewContainer(container);
  const phase = data.phase;
  const bar = overviewEl("div", "details-phase-bar");
  const items = [
    ["当前阶段", phase.id],
    ["阶段状态", phase.status],
    ["总体进度", `${phase.overallProgress}%`],
    ["阶段周期", `${phase.startDate} 至 ${phase.endDate}`],
  ];
  items.forEach(([label, value]) => {
    const cell = overviewEl("div", "details-phase-cell");
    cell.append(overviewEl("span", "details-phase-label", label), overviewEl("strong", "details-phase-value", value));
    bar.appendChild(cell);
  });
  container.appendChild(bar);
}

const DELIVERABLE_POLICY_MODE_LABELS = {
  manual: "手动",
  hybrid: "混合",
  automatic: "自动",
};

const DELIVERABLE_POLICY_FIELDS = [
  ["owner", "负责人"],
  ["plannedDate", "计划完成日期"],
  ["note", "风险与备注"],
];

function deliverablePolicyModeLabel(mode) {
  return DELIVERABLE_POLICY_MODE_LABELS[mode] || "手动";
}

function deliverableSyncStateLabel(policy) {
  if (policy && policy.enabled === false) return "未启用";
  if (!policy || policy.enabled !== true) return "未知";
  const labels = {
    idle: "等待同步",
    running: "同步中",
    success: "同步成功",
    failed: "同步失败",
    needs_attention: "需要处理",
  };
  return labels[policy.syncState] || "未知";
}

function updatePolicyStatusMessage(region, message, isError = false) {
  if (!region) return;
  region.textContent = message || "";
  region.classList.toggle("is-error", isError);
}

async function loadDeliverableUpdateHistory(deliverableId, container) {
  container.textContent = "正在读取更新记录...";
  try {
    const response = await fetch(`/api/project-status/updates?deliverableId=${encodeURIComponent(deliverableId)}`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const body = await overviewReadJson(response);
    if (!response.ok || !body || body.ok !== true) throw overviewRequestError(body, response.status);
    const updates = body.data && Array.isArray(body.data.updates) ? body.data.updates.slice(0, 5) : [];
    container.textContent = "";
    if (updates.length === 0) {
      container.appendChild(overviewEl("p", "policy-history-empty", "暂无更新记录"));
      return;
    }
    const list = overviewEl("ol", "policy-history-list");
    updates.forEach((entry) => {
      const trigger = entry.triggerType === "manual" ? "手动更新" : "自动同步";
      const result = entry.result === "applied" ? "已应用" : safeDisplayValue(entry.result);
      list.appendChild(overviewEl("li", null, `${safeDisplayValue(entry.createdAt)} · ${trigger} · ${result}`));
    });
    container.appendChild(list);
  } catch (err) {
    container.textContent = err instanceof Error ? err.message : String(err);
    container.classList.add("is-error");
  }
}

function renderDeliverablePolicyEditor(container, item, policy) {
  container.textContent = "";
  const titleRow = overviewEl("div", "policy-editor-head");
  titleRow.append(
    overviewEl("strong", "policy-editor-title", "更新方式"),
    overviewEl("span", "policy-source", "权威来源 · TDC 数模报表"),
  );

  const form = overviewEl("form", "policy-editor-form");
  const modeGroup = overviewEl("fieldset", "policy-mode-group");
  modeGroup.appendChild(overviewEl("legend", null, "更新模式"));
  const modeControl = overviewEl("div", "policy-segmented");
  Object.entries(DELIVERABLE_POLICY_MODE_LABELS).forEach(([value, label]) => {
    const input = document.createElement("input");
    input.type = "radio";
    input.name = `policy-mode-${item.id}`;
    input.id = `policy-mode-${item.id}-${value}`;
    input.value = value;
    input.checked = policy.mode === value;
    const labelEl = overviewEl("label", null, label);
    labelEl.htmlFor = input.id;
    modeControl.append(input, labelEl);
  });
  modeGroup.appendChild(modeControl);

  const authorityGroup = overviewEl("fieldset", "policy-authority-group");
  authorityGroup.appendChild(overviewEl("legend", null, "允许 TDC 自动更新的字段"));
  const checks = overviewEl("div", "policy-field-checks");
  DELIVERABLE_POLICY_FIELDS.forEach(([name, label]) => {
    const wrap = overviewEl("label", "policy-field-check");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.name = name;
    input.checked = policy.fieldAuthority && policy.fieldAuthority[name] === "automatic";
    wrap.append(input, overviewEl("span", null, label));
    checks.appendChild(wrap);
  });
  authorityGroup.appendChild(checks);

  const bindingReady = Boolean(policy.externalKey && policy.matchRule && Object.keys(policy.matchRule).length);
  const notice = overviewEl(
    "p",
    `policy-binding-state ${bindingReady ? "is-ready" : "is-pending"}`,
    bindingReady
      ? "TDC 稳定编号已配置。自动执行器接入前仍保持关闭。"
      : "TDC 稳定编号尚未确认，自动同步保持关闭；手动更新不受影响。",
  );
  const status = overviewEl("p", "policy-request-status");
  status.setAttribute("role", "status");
  const actions = overviewEl("div", "policy-editor-actions");
  const save = overviewEl("button", "policy-save-btn", "保存更新方式");
  save.type = "submit";
  const history = overviewEl("button", "policy-history-btn", "更新记录");
  history.type = "button";
  const historyBody = overviewEl("div", "policy-history");
  history.addEventListener("click", () => loadDeliverableUpdateHistory(item.id, historyBody));
  actions.append(save, history);
  form.append(modeGroup, authorityGroup, notice, actions, status, historyBody);
  form.addEventListener(
    "submit",
    async (event) => {
    event.preventDefault();
    const selected = form.querySelector('input[type="radio"]:checked');
    const mode = selected ? selected.value : "manual";
    const fieldAuthority = {
      status: "manual",
      owner: "manual",
      plannedDate: "manual",
      actualDate: "manual",
      progress: "manual",
      note: "manual",
    };
    if (mode !== "manual") {
      DELIVERABLE_POLICY_FIELDS.forEach(([name]) => {
        const checkbox = form.querySelector(`input[type="checkbox"][name="${name}"]`);
        if (checkbox && checkbox.checked) fieldAuthority[name] = "automatic";
      });
    }
    save.disabled = true;
    updatePolicyStatusMessage(status, "正在保存...");
    try {
      const response = await fetch(`/api/project-status/deliverables/${encodeURIComponent(item.id)}/update-policy`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ mode, enabled: false, fieldAuthority }),
      });
      const body = await overviewReadJson(response);
      if (!response.ok || !body || body.ok !== true) throw overviewRequestError(body, response.status);
      const saved = body.data;
      item.updatePolicy = {
        ...item.updatePolicy,
        mode: saved.mode,
        enabled: saved.enabled,
        sourceType: saved.sourceType,
        syncState: saved.syncState,
        lastSuccessAt: saved.lastSuccessAt,
      };
      renderDeliverablePolicyEditor(container, item, saved);
      const refreshedStatus = container.querySelector(".policy-request-status");
      updatePolicyStatusMessage(refreshedStatus, "更新方式已保存");
    } catch (err) {
      updatePolicyStatusMessage(status, err instanceof Error ? err.message : String(err), true);
      save.disabled = false;
    }
    },
  );
  container.append(titleRow, form);
}

async function loadDeliverablePolicy(container, item) {
  if (item.id !== "VPI-T2-D5") {
    container.append(
      overviewEl("strong", "policy-editor-title", "更新方式"),
      overviewEl("p", "policy-static-mode", "手动维护"),
    );
    return;
  }
  container.appendChild(overviewEl("p", "policy-loading", "正在读取更新策略..."));
  try {
    const response = await fetch(`/api/project-status/deliverables/${encodeURIComponent(item.id)}/update-policy`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const body = await overviewReadJson(response);
    if (!response.ok || !body || body.ok !== true) throw overviewRequestError(body, response.status);
    renderDeliverablePolicyEditor(container, item, body.data);
  } catch (err) {
    container.textContent = "";
    container.appendChild(overviewEl("p", "policy-request-status is-error", err instanceof Error ? err.message : String(err)));
  }
}

const DELIVERABLE_FIXED_SOURCES = {
  "VPI-T2-D1": "仅手工维护",
  "VPI-T2-D2": "TDC SOR",
  "VPI-T2-D3": "ARAS EWO",
  "VPI-T2-D4": "TDC A 面（契约待验证）",
  "VPI-T2-D5": "TDC 数模",
};

const DELIVERABLE_FIELD_LABELS = {
  owner: "负责人",
  plannedDate: "计划完成日期",
  note: "风险与备注",
  status: "状态",
  progress: "进度",
  actualDate: "实际完成日期",
};

function formatMappingStateLabel(state) {
  const map = {
    matched: "已匹配",
    not_found: "未找到",
    ambiguous: "存在歧义",
    key_changed: "稳定键变更",
  };
  return (state && map[state]) || "待确认";
}

function formatCandidateReasonLabel(reason) {
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

function formatRunTriggerLabel(trigger) {
  const map = {
    sync_now: "手动触发",
    manual: "手动更新",
    scheduled: "定时调度",
    webhook: "外部推送",
  };
  return (trigger && map[trigger]) || "未知";
}

function formatRunStateLabel(state) {
  const map = {
    success: "成功",
    partial: "部分成功",
    failed: "失败",
    needs_attention: "需要处理",
    running: "运行中",
    expired: "已过期",
  };
  return (state && map[state]) || "未知";
}

function formatArtifactSize(bytes) {
  if (bytes === null || bytes === undefined || isNaN(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function loadDeliverableEvidence(container, item, bundle = null, statusInfo = null) {
  if (bundle) {
    renderDeliverableEvidence(container, item, bundle, statusInfo);
    return;
  }
  container.textContent = "";
  const fixedSource = DELIVERABLE_FIXED_SOURCES[item.id] || item.source || "未知";

  const head = overviewEl("div", "evidence-panel-head");
  head.append(
    overviewEl("strong", "evidence-title", "外部同步与证据"),
    overviewEl("span", "evidence-source", `权威来源 · ${fixedSource}`),
  );
  container.appendChild(head);

  if (item.id === "VPI-T2-D1") {
    const notice = overviewEl("div", "evidence-restriction-card is-manual");
    notice.append(
      overviewEl("strong", "evidence-restriction-title", "仅手工维护"),
      overviewEl("p", "evidence-restriction-desc", "该交付物当前仅允许手工维护，未接入外部系统。"),
    );
    container.appendChild(notice);
    return;
  }

  if (item.id === "VPI-T2-D4") {
    const notice = overviewEl("div", "evidence-restriction-card is-blocked");
    notice.append(
      overviewEl("strong", "evidence-restriction-title", "TDC A 面契约待验证/阻断"),
      overviewEl("p", "evidence-restriction-desc", "该交付物外部数据契约待验证，当前已阻断外部同步与映射。"),
    );
    container.appendChild(notice);
    return;
  }

  const loadingP = overviewEl("p", "loading", "正在读取同步与证据数据...");
  loadingP.setAttribute("role", "status");
  loadingP.setAttribute("aria-live", "polite");
  container.appendChild(loadingP);

  try {
    const [policyRes, analyticsRes, mappingRes, previewRes, runsRes] = await Promise.all([
      fetch(`/api/project-status/deliverables/${encodeURIComponent(item.id)}/update-policy`, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      }),
      fetch("/api/project-status/analytics", {
        headers: { Accept: "application/json" },
        cache: "no-store",
      }),
      fetch(`/api/project-status/deliverables/${encodeURIComponent(item.id)}/mapping-discovery`, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      }),
      fetch(`/api/project-status/deliverables/${encodeURIComponent(item.id)}/candidate-preview`, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      }),
      fetch(`/api/project-status/runs?deliverableId=${encodeURIComponent(item.id)}&limit=10`, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      }),
    ]);

    const [policyBody, analyticsBody, mappingBody, previewBody, runsBody] = await Promise.all([
      overviewReadJson(policyRes),
      overviewReadJson(analyticsRes),
      overviewReadJson(mappingRes),
      overviewReadJson(previewRes),
      overviewReadJson(runsRes),
    ]);

    if (!policyRes.ok || !policyBody || policyBody.ok !== true) throw overviewRequestError(policyBody, policyRes.status);
    if (!analyticsRes.ok || !analyticsBody || analyticsBody.ok !== true) throw overviewRequestError(analyticsBody, analyticsRes.status);
    if (!mappingRes.ok || !mappingBody || mappingBody.ok !== true) throw overviewRequestError(mappingBody, mappingRes.status);
    if (!previewRes.ok || !previewBody || previewBody.ok !== true) throw overviewRequestError(previewBody, previewRes.status);
    if (!runsRes.ok || !runsBody || runsBody.ok !== true) throw overviewRequestError(runsBody, runsRes.status);

    const policy = policyBody.data || {};
    const analyticsList = analyticsBody.data && Array.isArray(analyticsBody.data.deliverables) ? analyticsBody.data.deliverables : [];
    const analytics = analyticsList.find((d) => d.deliverableId === item.id) || {};
    const mapping = mappingBody.data || {};
    const preview = previewBody.data || {};
    const runs = runsBody.data && Array.isArray(runsBody.data.runs) ? runsBody.data.runs : [];

    loadingP.remove();
    renderDeliverableEvidence(container, item, { policy, analytics, mapping, preview, runs }, statusInfo);
  } catch (err) {
    loadingP.remove();
    const errBox = overviewEl("div", "evidence-load-error");
    errBox.setAttribute("role", "alert");
    errBox.setAttribute("aria-live", "assertive");
    errBox.appendChild(overviewEl("p", "error-msg", `读取证据失败：${redactSensitiveText(err instanceof Error ? err.message : String(err))}`));
    const retryBtn = overviewEl("button", "evidence-retry-btn", "重试");
    retryBtn.type = "button";
    retryBtn.addEventListener("click", () => loadDeliverableEvidence(container, item));
    errBox.appendChild(retryBtn);
    container.appendChild(errBox);
  }
}

function renderDeliverableEvidence(container, item, bundle, statusInfo = null) {
  const { policy, analytics, mapping, preview, runs } = bundle;
  const fixedSource = DELIVERABLE_FIXED_SOURCES[item.id] || item.source || "未知";

  // 1. Authoritative Summary Grid
  const grid = overviewEl("dl", "evidence-overview-grid");
  const freshnessLabel = analytics.freshness === "fresh" ? "及时" : (analytics.freshness === "stale" ? "滞后" : "未知");
  const credentialLabel = policy.credentialAvailable === true
    ? "已配置"
    : (policy.credentialAvailable === false ? "未配置" : "未知");
  const confirmedCount = analytics.mappingStability
    ? analytics.mappingStability.confirmed
    : (mapping.stability ? mapping.stability.confirmed : null);
  const hasConfirmedCount = confirmedCount !== null
    && confirmedCount !== undefined
    && confirmedCount !== ""
    && Number.isFinite(Number(confirmedCount));
  const mappingProgressText = hasConfirmedCount
    ? `${Math.min(Math.max(Number(confirmedCount), 0), 2)}/2`
    : "待确认";
  const latestObs = mapping.observations && mapping.observations.length > 0 ? mapping.observations[0] : null;
  const mappingStateText = formatMappingStateLabel(latestObs ? latestObs.state : (analytics.mappingEvidence ? analytics.mappingEvidence.state : null));
  const recordCountText = analytics.externalRecordCount !== null && analytics.externalRecordCount !== undefined
    ? `${analytics.externalRecordCount} 条`
    : (latestObs && latestObs.candidateCount !== null && latestObs.candidateCount !== undefined ? `${latestObs.candidateCount} 条` : "待确认");

  const summaryPairs = [
    ["权威来源", fixedSource],
    ["凭据状态", credentialLabel],
    ["同步状态", deliverableSyncStateLabel(policy)],
    ["时效性", freshnessLabel],
    ["最近尝试", safeDisplayValue(analytics.lastAttemptAt || policy.lastAttemptAt || "无")],
    ["最近成功", safeDisplayValue(analytics.lastSuccessAt || policy.lastSuccessAt || "无")],
    ["失败次数", analytics.failureCount === null || analytics.failureCount === undefined
      ? "未知"
      : `${analytics.failureCount} 次`],
    ["外部记录数", recordCountText],
    ["映射状态", mappingStateText],
    ["映射进度", mappingProgressText],
  ];

  summaryPairs.forEach(([label, value]) => {
    grid.append(overviewEl("dt", null, label), overviewEl("dd", null, safeDisplayValue(value)));
  });
  container.appendChild(grid);

  // 2. Risk / Needs Attention Alert (if any)
  if (analytics.needsAttention || analytics.riskSummary) {
    const riskBox = overviewEl("div", "evidence-risk-box");
    riskBox.append(
      overviewEl("strong", "evidence-risk-title", "风险与告警"),
      overviewEl("p", "evidence-risk-desc", redactSensitiveText(analytics.riskSummary || "映射或同步状态需要关注")),
    );
    container.appendChild(riskBox);
  }

  // 3. Sync-now Action Bar
  const stabilityReady = Boolean(
    (analytics.mappingStability && analytics.mappingStability.ready === true) ||
    (mapping.stability && Number(mapping.stability.confirmed) >= 2)
  );
  const syncReady = Boolean(
    policy.enabled === true
    && policy.credentialAvailable === true
    && stabilityReady
  );

  const syncActionBar = overviewEl("div", "evidence-sync-bar");
  const syncBtn = overviewEl("button", "evidence-sync-btn", "立即同步");
  syncBtn.type = "button";
  syncBtn.disabled = !syncReady;

  if (!syncReady) {
    const missing = [];
    if (policy.enabled !== true) missing.push("更新策略未启用或状态未知");
    if (policy.credentialAvailable !== true) missing.push("凭据未配置或状态未知");
    if (!stabilityReady) missing.push(`映射稳定性未就绪 (${mappingProgressText})`);
    syncBtn.title = `不可同步：${missing.join("，")}`;
  }

  const syncStatus = overviewEl("span", "evidence-sync-status");
  syncStatus.setAttribute("role", "status");
  syncStatus.setAttribute("aria-live", "polite");

  if (statusInfo && statusInfo.text) {
    syncStatus.textContent = statusInfo.text;
    syncStatus.className = statusInfo.className || "evidence-sync-status";
  }

  syncBtn.addEventListener("click", async () => {
    if (!window.confirm(`确定要立即同步 ${item.name} 吗？`)) return;
    syncBtn.disabled = true;
    syncStatus.textContent = "正在执行同步...";
    syncStatus.className = "evidence-sync-status is-busy";

    try {
      const response = await fetch(`/api/project-status/deliverables/${encodeURIComponent(item.id)}/sync-now`, {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      const body = await overviewReadJson(response);
      if (!response.ok || !body || body.ok !== true) throw overviewRequestError(body, response.status);

      const resData = body.data || {};
      const resResult = resData.result || {};
      const finalState = resResult.finalState || resData.finalState;
      const outcome = resResult.outcome || resData.outcome || finalState;

      let resultStatusText = "";
      let resultStatusClass = "";

      if (finalState === "busy" || outcome === "busy") {
        const msg = redactSensitiveText(resResult.errorMessage || resData.errorMessage || "任务处理中");
        resultStatusText = `同步进行中：${msg}`;
        resultStatusClass = "evidence-sync-status is-busy";
      } else if (finalState === "success" && outcome === "completed") {
        resultStatusText = "同步完成：成功";
        resultStatusClass = "evidence-sync-status is-success";
      } else if (finalState === "partial" || outcome === "partial") {
        resultStatusText = "同步完成：部分字段已应用";
        resultStatusClass = "evidence-sync-status is-warning";
      } else if (finalState === "needs_attention" || outcome === "needs_attention") {
        const msg = redactSensitiveText(resResult.errorMessage || resData.errorMessage || "未匹配到唯一候选");
        resultStatusText = `同步需要处理：${msg}`;
        resultStatusClass = "evidence-sync-status is-warning";
      } else {
        const msg = redactSensitiveText(resResult.errorMessage || resData.errorMessage || (finalState ? `状态 ${finalState}` : "未知状态"));
        resultStatusText = `同步失败：${msg}`;
        resultStatusClass = "evidence-sync-status is-error";
      }

      syncStatus.textContent = resultStatusText;
      syncStatus.className = resultStatusClass;

      const deliverableIndex = overviewSavedState && Array.isArray(overviewSavedState.deliverables)
        ? overviewSavedState.deliverables.findIndex((d) => d.id === item.id)
        : -1;

      await loadProjectOverview();

      if (deliverableIndex >= 0) {
        expandOverviewDetail(deliverableIndex, { text: resultStatusText, className: resultStatusClass });
      }
    } catch (err) {
      syncStatus.textContent = `同步失败：${redactSensitiveText(err instanceof Error ? err.message : String(err))}`;
      syncStatus.className = "evidence-sync-status is-error";
      syncBtn.disabled = !syncReady;
    }
  });

  syncActionBar.append(syncBtn, syncStatus);
  container.appendChild(syncActionBar);

  // 4. Candidate Differences Section
  const diffSection = overviewEl("div", "evidence-sub-section evidence-diff-section");
  diffSection.appendChild(overviewEl("h5", "evidence-sub-title", "候选字段差异对比"));

  const differences = preview && Array.isArray(preview.differences) ? preview.differences : [];
  if (differences.length === 0) {
    const reasonText = formatCandidateReasonLabel(preview && preview.reason);
    const emptyDiff = overviewEl("p", "evidence-empty-note", `暂无差异证据（${reasonText}）`);
    emptyDiff.setAttribute("role", "status");
    diffSection.appendChild(emptyDiff);
  } else {
    const tableWrap = overviewEl("div", "overview-table-wrap");
    const diffTable = overviewEl("table", "overview-details-table evidence-diff-table");
    const thead = overviewEl("thead");
    const headerRow = overviewEl("tr");
    ["目标字段", "来源字段", "当前系统值", "外部候选值", "变更状态"].forEach((text) => {
      headerRow.appendChild(overviewEl("th", null, text));
    });
    thead.appendChild(headerRow);
    const tbody = overviewEl("tbody");
    differences.forEach((diff) => {
      const tr = overviewEl("tr");
      const targetLabel = DELIVERABLE_FIELD_LABELS[diff.targetField] || diff.targetField;
      const changedLabel = diff.changed ? "有变更" : "无变更";
      const changedTone = diff.changed ? "status-text is-warning" : "status-text is-success";

      tr.appendChild(overviewEl("td", null, safeDisplayValue(targetLabel)));
      tr.appendChild(overviewEl("td", null, safeDisplayValue(diff.sourceField)));
      tr.appendChild(overviewEl("td", null, safeDisplayValue(diff.currentValue || "(空)")));
      tr.appendChild(overviewEl("td", null, safeDisplayValue(diff.candidateValue || "(空)")));
      const changedTd = overviewEl("td");
      changedTd.appendChild(overviewEl("span", changedTone, changedLabel));
      tr.appendChild(changedTd);
      tbody.appendChild(tr);
    });
    diffTable.append(thead, tbody);
    tableWrap.appendChild(diffTable);
    diffSection.appendChild(tableWrap);
  }
  container.appendChild(diffSection);

  // 5. Mapping Evidence View
  const mappingSection = overviewEl("div", "evidence-sub-section evidence-mapping-section");
  mappingSection.appendChild(overviewEl("h5", "evidence-sub-title", "映射发现证据"));

  if (!latestObs) {
    const emptyMapping = overviewEl("p", "evidence-empty-note", "暂无映射发现记录");
    emptyMapping.setAttribute("role", "status");
    mappingSection.appendChild(emptyMapping);
  } else {
    const obsGrid = overviewEl("dl", "evidence-obs-grid");
    obsGrid.append(
      overviewEl("dt", null, "观测状态"),
      overviewEl("dd", null, formatMappingStateLabel(latestObs.state)),
      overviewEl("dt", null, "观测时间"),
      overviewEl("dd", null, safeDisplayValue(latestObs.createdAt)),
      overviewEl("dt", null, "候选记录数"),
      overviewEl("dd", null, `${latestObs.candidateCount} 条`),
    );
    mappingSection.appendChild(obsGrid);

    const report = latestObs.fieldReport || {};
    const fields = Array.isArray(report.fields) ? report.fields : [];
    if (fields.length > 0) {
      const fieldListWrap = overviewEl("div", "evidence-field-list-wrap");
      fieldListWrap.appendChild(overviewEl("span", "evidence-field-label", "发现字段名称："));
      const tags = overviewEl("div", "evidence-field-tags");
      fields.forEach((f) => {
        tags.appendChild(overviewEl("span", "evidence-field-tag", String(f)));
      });
      fieldListWrap.appendChild(tags);
      mappingSection.appendChild(fieldListWrap);
    }

    const statusFields = Array.isArray(report.statusOrApprovalFields) ? report.statusOrApprovalFields : [];
    if (statusFields.length > 0) {
      const statusWrap = overviewEl("div", "evidence-status-fields-wrap");
      statusWrap.appendChild(overviewEl("span", "evidence-field-label", "状态/审批字段采样："));
      const list = overviewEl("ul", "evidence-status-samples-list");
      statusFields.forEach((itemField) => {
        const samples = Array.isArray(itemField.samples) && itemField.samples.length > 0
          ? itemField.samples.join(", ")
          : "无采样";
        list.appendChild(overviewEl("li", null, `${itemField.field}：${samples}`));
      });
      statusWrap.appendChild(list);
      mappingSection.appendChild(statusWrap);
    }

    const mappingNotice = overviewEl("p", "evidence-mapping-confirmation", "建议状态映射：待用户确认（不自动应用）");
    mappingSection.appendChild(mappingNotice);
  }
  container.appendChild(mappingSection);

  // 6. Run History & Artifacts
  const runsSection = overviewEl("div", "evidence-sub-section evidence-runs-section");
  runsSection.appendChild(overviewEl("h5", "evidence-sub-title", "运行历史与产物"));

  if (runs.length === 0) {
    const emptyRuns = overviewEl("p", "evidence-empty-note", "暂无同步运行记录");
    emptyRuns.setAttribute("role", "status");
    runsSection.appendChild(emptyRuns);
  } else {
    const tableWrap = overviewEl("div", "overview-table-wrap");
    const runsTable = overviewEl("table", "overview-details-table evidence-runs-table");
    const thead = overviewEl("thead");
    const trHead = overviewEl("tr");
    ["触发方式", "状态", "尝试", "开始时间", "结束时间", "结果摘要 / 错误", "产物"].forEach((t) => {
      trHead.appendChild(overviewEl("th", null, t));
    });
    thead.appendChild(trHead);

    const tbody = overviewEl("tbody");
    runs.forEach((run) => {
      const tr = overviewEl("tr");
      const summaryText = redactSensitiveText(run.error_message || run.result_summary || "—");
      const attemptText = (run.attempt !== null && run.attempt !== undefined && run.attempt !== "")
        ? `第 ${run.attempt} 次`
        : "未知";

      tr.appendChild(overviewEl("td", null, formatRunTriggerLabel(run.trigger_type)));
      const stateTd = overviewEl("td");
      const stateTone = run.run_state === "success" ? "status-text is-success" : (run.run_state === "failed" ? "status-text is-error" : "status-text is-warning");
      stateTd.appendChild(overviewEl("span", stateTone, formatRunStateLabel(run.run_state)));
      tr.appendChild(stateTd);

      tr.appendChild(overviewEl("td", null, attemptText));
      tr.appendChild(overviewEl("td", null, safeDisplayValue(run.started_at || run.created_at || "未知")));
      tr.appendChild(overviewEl("td", null, safeDisplayValue(run.finished_at || "未知")));
      tr.appendChild(overviewEl("td", null, summaryText));

      const artifactTd = overviewEl("td");
      const artifactBtn = overviewEl("button", "evidence-artifact-btn", "查看产物");
      artifactBtn.type = "button";
      artifactTd.appendChild(artifactBtn);
      tr.appendChild(artifactTd);

      tbody.appendChild(tr);

      // Collapsible artifact detail row
      const artTr = overviewEl("tr", "evidence-artifact-row");
      artTr.hidden = true;
      const artTd = overviewEl("td");
      artTd.colSpan = 7;
      const artBox = overviewEl("div", "evidence-artifact-box");
      artTd.appendChild(artBox);
      artTr.appendChild(artTd);
      tbody.appendChild(artTr);

      artifactBtn.addEventListener("click", async () => {
        if (!artTr.hidden) {
          artTr.hidden = true;
          artifactBtn.textContent = "查看产物";
          return;
        }
        artTr.hidden = false;
        artifactBtn.textContent = "收起产物";
        artBox.setAttribute("role", "status");
        artBox.setAttribute("aria-live", "polite");
        artBox.textContent = "正在读取产物元数据...";
        try {
          const res = await fetch(`/api/project-status/runs/${encodeURIComponent(run.id)}/artifacts`, {
            headers: { Accept: "application/json" },
            cache: "no-store",
          });
          const body = await overviewReadJson(res);
          if (!res.ok || !body || body.ok !== true) throw overviewRequestError(body, res.status);
          const artifacts = body.data && Array.isArray(body.data.artifacts) ? body.data.artifacts : [];
          artBox.textContent = "";
          if (artifacts.length === 0) {
            const emptyArt = overviewEl("p", "evidence-empty-note", "无产物元数据");
            emptyArt.setAttribute("role", "status");
            artBox.appendChild(emptyArt);
            return;
          }
          const artTable = overviewEl("table", "evidence-artifact-table");
          const artThead = overviewEl("thead");
          const artHeadRow = overviewEl("tr");
          ["产物名称", "类型", "大小", "相对路径", "SHA-256"].forEach((h) => artHeadRow.appendChild(overviewEl("th", null, h)));
          artThead.appendChild(artHeadRow);
          const artTbody = overviewEl("tbody");
          artifacts.forEach((art) => {
            const row = overviewEl("tr");
            row.appendChild(overviewEl("td", null, safeDisplayValue(art.display_name || "—")));
            row.appendChild(overviewEl("td", null, safeDisplayValue(art.artifact_type || "—")));
            row.appendChild(overviewEl("td", null, formatArtifactSize(art.size_bytes)));
            row.appendChild(overviewEl("td", null, safeDisplayValue(art.relative_path || "—")));
            row.appendChild(overviewEl("td", null, safeDisplayValue(art.sha256 || "—")));
            artTbody.appendChild(row);
          });
          artTable.append(artThead, artTbody);
          artBox.appendChild(artTable);
        } catch (err) {
          artBox.setAttribute("role", "alert");
          artBox.textContent = "";
          artBox.appendChild(overviewEl(
            "p",
            "error-msg",
            `读取产物失败：${redactSensitiveText(err instanceof Error ? err.message : String(err))}`,
          ));
          const retryArtifactBtn = overviewEl("button", "evidence-retry-btn", "重试读取产物");
          retryArtifactBtn.type = "button";
          retryArtifactBtn.addEventListener("click", () => {
            artTr.hidden = true;
            artifactBtn.textContent = "查看产物";
            artifactBtn.click();
          });
          artBox.appendChild(retryArtifactBtn);
        }
      });
    });
    runsTable.append(thead, tbody);
    tableWrap.appendChild(runsTable);
    runsSection.appendChild(tableWrap);
  }
  container.appendChild(runsSection);
}

function toggleDeliverableDetail(row, data, index, statusInfo = null) {
  const button = row.querySelector(".detail-expand");
  if (!button) return;
  const detailId = button.getAttribute("aria-controls");
  const existing = document.getElementById(detailId);
  if (existing) {
    if (overviewDraft && overviewDraft.index === index && overviewDraftDirty()
      && !window.confirm("有未保存的更改，确定放弃吗？")) {
      return;
    }
    existing.remove();
    overviewDraft = null;
    button.setAttribute("aria-expanded", "false");
    button.textContent = "展开";
    return;
  }
  const item = data.deliverables[index];
  if (!item) return;
  const inlineRow = document.createElement("tr");
  inlineRow.id = detailId;
  inlineRow.className = "detail-inline-row";
  const cell = overviewEl("td", "detail-inline-cell");
  cell.colSpan = 8;
  const box = overviewEl("div", "detail-inline");
  const head = overviewEl("div", "detail-inline-head");
  const headCopy = overviewEl("div", "detail-inline-title");
  headCopy.append(
    overviewEl("strong", "detail-inline-name", item.name),
    overviewEl("span", "detail-inline-id", `ID ${safeDisplayValue(item.id)}`),
  );
  head.appendChild(headCopy);
  head.appendChild(overviewEl("span", `status-text is-${deliverableTone(item)}`, item.status));
  const grid = overviewEl("dl", "detail-inline-grid");
  const pairs = [
    ["当前状态", item.status],
    ["负责人", item.owner],
    ["计划完成日期", item.plannedDate],
    ["实际完成日期或当前进度", deliverableProgressOrDate(item)],
    ["所属阶段", data.phase.id],
    ["数据来源", item.source],
    ["更新方式", deliverablePolicyModeLabel(item.updatePolicy && item.updatePolicy.mode)],
    ["同步状态", deliverableSyncStateLabel(item.updatePolicy)],
    ["数据更新时间", item.updatedAt || data.phase.updatedAt],
  ];
  pairs.forEach(([label, value]) => {
    grid.append(overviewEl("dt", null, label), overviewEl("dd", null, safeDisplayValue(value)));
  });
  const association = overviewEl("div", "detail-association");
  association.append(
    overviewEl("span", "association-label", "关联项"),
    overviewEl("p", "association-empty", "尚未配置关联模型"),
  );
  const policyPanel = overviewEl("section", "deliverable-policy-panel");
  policyPanel.setAttribute("aria-label", `${item.name} 更新方式`);
  loadDeliverablePolicy(policyPanel, item);
  const evidencePanel = overviewEl("section", "deliverable-evidence-panel");
  evidencePanel.setAttribute("aria-label", `${item.name} 外部同步与证据`);
  loadDeliverableEvidence(evidencePanel, item, null, statusInfo);
  const actions = overviewEl("div", "detail-inline-actions");
  const editButton = overviewEl("button", "detail-edit", null);
  editButton.type = "button";
  const editLabel = `编辑 ${item.name}`;
  editButton.title = editLabel;
  editButton.setAttribute("aria-label", editLabel);
  editButton.appendChild(overviewPencilIcon());
  editButton.appendChild(overviewEl("span", "visually-hidden", "编辑"));
  editButton.addEventListener("click", (event) => {
    event.stopPropagation();
    startDeliverableEdit(index);
  });
  actions.appendChild(editButton);
  box.append(head, grid, association, policyPanel, evidencePanel, actions);
  cell.appendChild(box);
  inlineRow.appendChild(cell);
  row.after(inlineRow);
  button.setAttribute("aria-expanded", "true");
  button.textContent = "收起";
}

function renderDeliverableDetails(tbody, data) {
  if (!tbody) return;
  tbody.textContent = "";
  if (!data.deliverables || data.deliverables.length === 0) {
    renderTableState(tbody, "empty");
    return;
  }
  data.deliverables.forEach((item, index) => {
    const row = document.createElement("tr");
    row.className = "deliverable-detail-row";
    const values = [
      item.name,
      item.status,
      item.owner,
      item.plannedDate,
      deliverableProgressOrDate(item),
      item.note,
      item.source,
    ];
    values.forEach((value, cellIndex) => {
      const cell = overviewEl("td", null);
      cell.dataset.label = OVERVIEW_DETAIL_COLUMNS[cellIndex];
      if (cellIndex === 1) {
        cell.appendChild(overviewEl("span", `status-text is-${deliverableTone(item)}`, safeDisplayValue(value)));
      } else {
        cell.textContent = safeDisplayValue(value);
      }
      row.appendChild(cell);
    });
    const controlCell = overviewEl("td", "detail-expand-cell");
    const button = overviewEl("button", "detail-expand", "展开");
    button.type = "button";
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-label", `展开 ${item.name} 明细`);
    const detailId = `overview-detail-${index}`;
    button.setAttribute("aria-controls", detailId);
    controlCell.appendChild(button);
    row.appendChild(controlCell);
    row.addEventListener("click", (event) => {
      if (event.target.closest("button")) return;
      toggleDeliverableDetail(row, data, index);
    });
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleDeliverableDetail(row, data, index);
    });
    tbody.appendChild(row);
  });
}

function renderProjectOverview() {
  const timelineBody = document.getElementById("overview-timeline-body");
  const phaseBody = document.getElementById("overview-phase-summary");
  const progressGrid = document.getElementById("overview-progress-grid");
  const riskBody = document.getElementById("overview-risk-summary");
  const detailsSummary = document.getElementById("overview-details-summary");
  const detailsBody = document.getElementById("overview-details-body");
  const maintenanceBody = document.getElementById("milestone-maintenance");
  const containers = [timelineBody, phaseBody, progressGrid, riskBody, detailsSummary].filter(Boolean);

  if (overviewLoading) {
    containers.forEach((container) => renderOverviewLoading(container));
    renderOverviewLoading(maintenanceBody);
    renderTableState(detailsBody, "loading");
    return;
  }
  if (overviewLoadError) {
    containers.forEach((container) => renderOverviewLoadError(container, overviewLoadError));
    renderOverviewLoadError(maintenanceBody, overviewLoadError);
    renderTableState(detailsBody, "error", overviewLoadError);
    return;
  }
  if (!overviewSavedState || overviewIsEmpty(overviewSavedState)) {
    containers.forEach((container) => renderOverviewEmpty(container));
    renderOverviewEmpty(maintenanceBody);
    renderTableState(detailsBody, "empty");
    return;
  }
  try {
    renderMilestoneTimeline(timelineBody, overviewSavedState);
    renderPhaseSummary(phaseBody, overviewSavedState.phase);
    renderDeliverableProgress(progressGrid, overviewSavedState.deliverables);
    renderRiskSummary(riskBody, overviewSavedState.summary);
    renderMilestoneMaintenance(maintenanceBody, overviewSavedState);
    renderDetailsSummary(detailsSummary, overviewSavedState);
    renderDeliverableDetails(detailsBody, overviewSavedState);
  } catch (err) {
    containers.forEach((container) => renderOverviewError(container, err.message));
    renderOverviewError(maintenanceBody, err.message);
    renderTableState(detailsBody, "error", err.message);
  }
}

function activateOverviewTab(tab) {
  const tablist = tab.closest(".overview-switch");
  if (!tablist) return;
  tablist.querySelectorAll('[role="tab"]').forEach((item) => {
    const selected = item === tab;
    item.setAttribute("aria-selected", String(selected));
    item.classList.toggle("active", selected);
    item.tabIndex = selected ? 0 : -1;
    const panel = document.getElementById(item.getAttribute("aria-controls"));
    if (panel) panel.hidden = !selected;
  });
}

function setupOverviewTabs() {
  const tablist = document.querySelector(".overview-switch");
  if (!tablist) return;
  const tabs = Array.from(tablist.querySelectorAll('[role="tab"]'));
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => {
      if (tab.getAttribute("aria-selected") === "true") return;
      if (!overviewConfirmDiscard()) return;
      activateOverviewTab(tab);
    });
    tab.addEventListener("keydown", (event) => {
      let nextIndex = null;
      if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
      else if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === "Home") nextIndex = 0;
      else if (event.key === "End") nextIndex = tabs.length - 1;
      if (nextIndex !== null) {
        event.preventDefault();
        if (!overviewConfirmDiscard()) return;
        activateOverviewTab(tabs[nextIndex]);
        tabs[nextIndex].focus();
      }
    });
  });
}

async function loadProjectOverview() {
  overviewLoading = true;
  overviewLoadError = null;
  renderProjectOverview();
  try {
    const response = await fetch("/api/project-status?phase=VPI-T2", {
      headers: { Accept: "application/json" },
    });
    const body = await overviewReadJson(response);
    if (!response.ok || !body || body.ok !== true) {
      throw overviewRequestError(body, response.status);
    }
    overviewSavedState = body.data || null;
  } catch (err) {
    overviewSavedState = null;
    overviewLoadError = err instanceof Error ? err.message : String(err);
  } finally {
    overviewLoading = false;
    renderProjectOverview();
  }
}

function overviewDraftValuesFromItem(item) {
  return {
    status: item.status || "",
    owner: item.owner || "",
    plannedDate: item.plannedDate || "",
    actualDate: item.actualDate || "",
    progress: item.progress === null || item.progress === undefined ? "" : String(item.progress),
    note: item.note || "",
  };
}

function overviewDraftDirty() {
  if (!overviewDraft) return false;
  if (overviewDraft.kind === "milestones") return milestoneDraftDirty();
  const saved = overviewDraft.saved;
  const values = overviewDraft.values;
  return saved.status !== values.status
    || saved.owner !== values.owner
    || saved.plannedDate !== values.plannedDate
    || saved.actualDate !== values.actualDate
    || saved.progress !== values.progress
    || saved.note !== values.note;
}

function overviewConfirmDiscard() {
  if (!overviewDraftDirty()) return true;
  if (!window.confirm("有未保存的更改，确定放弃吗？")) return false;
  overviewDraft = null;
  renderProjectOverview();
  return true;
}

function guardUnsavedOverviewChanges(event) {
  if (!overviewDraftDirty()) return;
  event.preventDefault();
  event.returnValue = "";
}

function setupOverviewGuards() {
  window.addEventListener("beforeunload", guardUnsavedOverviewChanges);
}

function overviewDetailsRow(index) {
  const tbody = document.getElementById("overview-details-body");
  if (!tbody) return null;
  return tbody.querySelectorAll("tr.deliverable-detail-row")[index] || null;
}

function expandOverviewDetail(index, statusInfo = null) {
  const row = overviewDetailsRow(index);
  if (!row) return;
  const button = row.querySelector(".detail-expand");
  if (!button) return;
  const detailId = button.getAttribute("aria-controls");
  const existing = document.getElementById(detailId);
  if (!existing) {
    toggleDeliverableDetail(row, overviewSavedState, index, statusInfo);
  } else {
    const evidencePanel = existing.querySelector(".deliverable-evidence-panel");
    if (evidencePanel) {
      loadDeliverableEvidence(evidencePanel, overviewSavedState.deliverables[index], null, statusInfo);
    }
  }
}

function overviewPencilIcon() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", "16");
  svg.setAttribute("height", "16");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", "M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z");
  path.setAttribute("fill", "currentColor");
  svg.appendChild(path);
  return svg;
}

function overviewEditorFieldControl(name, value) {
  if (name === "status") {
    const select = document.createElement("select");
    select.id = `overview-edit-${name}`;
    select.name = name;
    OVERVIEW_STATUS_OPTIONS.forEach((optionText) => {
      const option = document.createElement("option");
      option.value = optionText;
      option.textContent = optionText;
      select.appendChild(option);
    });
    select.value = value;
    return select;
  }
  if (name === "note") {
    const textarea = document.createElement("textarea");
    textarea.id = `overview-edit-${name}`;
    textarea.name = name;
    textarea.rows = 3;
    textarea.value = value;
    return textarea;
  }
  const input = document.createElement("input");
  input.id = `overview-edit-${name}`;
  input.name = name;
  if (name === "progress") {
    input.type = "number";
    input.min = "0";
    input.max = "100";
    input.step = "1";
    input.inputMode = "numeric";
  } else {
    input.type = name === "plannedDate" || name === "actualDate" ? "date" : "text";
  }
  input.value = value;
  return input;
}

function overviewEditorField(name, label, value) {
  const wrap = overviewEl("div", "edit-field");
  wrap.dataset.field = name;
  const labelEl = overviewEl("label", null, label);
  labelEl.htmlFor = `overview-edit-${name}`;
  const control = overviewEditorFieldControl(name, value);
  control.addEventListener(name === "status" ? "change" : "input", () => {
    overviewDraft.values[name] = control.value;
    wrap.classList.remove("is-invalid");
    const error = wrap.querySelector(".field-error");
    if (error) error.remove();
  });
  wrap.append(labelEl, control);
  if (name === "note") wrap.classList.add("edit-field-wide");
  return wrap;
}

function renderDeliverableEditForm() {
  const item = overviewSavedState.deliverables[overviewDraft.index];
  const form = document.createElement("form");
  form.id = "overview-edit-form";
  form.className = "detail-edit-form";
  form.noValidate = true;

  const meta = overviewEl("dl", "edit-readonly-grid");
  const metaPairs = [
    ["交付物 ID", safeDisplayValue(item.id)],
    ["交付物名称", safeDisplayValue(item.name)],
    ["所属阶段", safeDisplayValue(overviewSavedState.phase.id)],
    ["数据来源", safeDisplayValue(item.source)],
  ];
  metaPairs.forEach(([label, value]) => {
    meta.append(overviewEl("dt", null, label), overviewEl("dd", null, value));
  });

  const fields = overviewEl("div", "edit-form-grid");
  const fieldDefs = [
    ["status", "状态"],
    ["owner", "负责人"],
    ["plannedDate", "计划完成日期"],
    ["actualDate", "实际完成日期"],
    ["progress", "当前进度（0-100）"],
    ["note", "风险与备注"],
  ];
  fieldDefs.forEach(([name, label]) => {
    fields.appendChild(overviewEditorField(name, label, overviewDraft.values[name]));
  });

  const requestMessage = overviewEl("div", "edit-request-message");
  const actions = overviewEl("div", "edit-form-actions");
  const saveButton = overviewEl("button", "edit-save-btn", "保存");
  saveButton.type = "button";
  saveButton.addEventListener("click", saveDeliverableChanges);
  const cancelButton = overviewEl("button", "edit-cancel-btn", "取消");
  cancelButton.type = "button";
  cancelButton.addEventListener("click", () => cancelDeliverableEdit());
  actions.append(saveButton, cancelButton, requestMessage);
  form.append(meta, fields, actions);
  return form;
}

function startDeliverableEdit(index) {
  if (!overviewSavedState || overviewSaving) return;
  const item = overviewSavedState.deliverables[index];
  if (!item) return;
  if (overviewDraft) {
    if (overviewDraftDirty() && !window.confirm("有未保存的更改，放弃后将继续编辑其他记录？")) return;
    overviewDraft = null;
    renderProjectOverview();
  }
  const row = overviewDetailsRow(index);
  if (!row) return;
  const button = row.querySelector(".detail-expand");
  if (!button) return;
  const detailId = button.getAttribute("aria-controls");
  let inlineRow = document.getElementById(detailId);
  if (!inlineRow) {
    toggleDeliverableDetail(row, overviewSavedState, index);
    inlineRow = document.getElementById(detailId);
  }
  if (!inlineRow) return;
  const box = inlineRow.querySelector(".detail-inline");
  if (!box) return;
  overviewDraft = {
    index,
    id: item.id,
    saved: overviewDraftValuesFromItem(item),
    values: overviewDraftValuesFromItem(item),
  };
  box.textContent = "";
  box.appendChild(renderDeliverableEditForm());
  const firstControl = box.querySelector("#overview-edit-status") || box.querySelector("input, select, textarea");
  if (firstControl) firstControl.focus();
}

function validateDeliverableDraft() {
  const errors = {};
  const values = overviewDraft.values;
  const status = String(values.status || "").trim();
  const owner = String(values.owner || "").trim();
  const plannedDate = String(values.plannedDate || "").trim();
  const actualDate = String(values.actualDate || "").trim();
  const progressRaw = String(values.progress || "").trim();
  const datePattern = /^\d{4}-\d{2}-\d{2}$/;

  if (!status) errors.status = "请选择状态";
  if (!owner) errors.owner = "负责人为必填项";
  if (!plannedDate) errors.plannedDate = "计划完成日期为必填项";
  else if (!datePattern.test(plannedDate)) errors.plannedDate = "日期格式应为 YYYY-MM-DD";

  if (progressRaw === "") {
    errors.progress = "当前进度为必填项";
  } else {
    const progress = Number(progressRaw);
    if (!Number.isInteger(progress) || progress < 0 || progress > 100) {
      errors.progress = "当前进度必须是 0 到 100 的整数";
    }
  }

  if (status === "已完成") {
    const progress = Number(progressRaw);
    if (progressRaw !== "" && Number.isInteger(progress) && progress !== 100) {
      errors.progress = "已完成交付物的进度必须为 100";
    }
    if (!actualDate) errors.actualDate = "已完成交付物必须填写实际完成日期";
    else if (!datePattern.test(actualDate)) errors.actualDate = "日期格式应为 YYYY-MM-DD";
  } else if (actualDate) {
    errors.actualDate = "未完成的交付物不应填写实际完成日期";
  }

  return errors;
}

function clearOverviewFieldErrors() {
  const form = document.getElementById("overview-edit-form");
  if (!form) return;
  form.querySelectorAll(".edit-field.is-invalid").forEach((wrap) => wrap.classList.remove("is-invalid"));
  form.querySelectorAll(".field-error").forEach((message) => message.remove());
}

function renderOverviewFieldErrors(errors) {
  const form = document.getElementById("overview-edit-form");
  if (!form) return;
  Object.keys(errors).forEach((name) => {
    const wrap = form.querySelector(`.edit-field[data-field="${name}"]`);
    if (!wrap) return;
    wrap.classList.add("is-invalid");
    wrap.appendChild(overviewEl("small", "field-error", errors[name]));
  });
  const firstInvalid = form.querySelector(".edit-field.is-invalid input, .edit-field.is-invalid select, .edit-field.is-invalid textarea");
  if (firstInvalid) firstInvalid.focus();
}

function renderOverviewServerFieldErrors(fields) {
  const form = document.getElementById("overview-edit-form");
  if (!form) return;
  const fieldMap = {
    status: "status",
    owner: "owner",
    plannedDate: "plannedDate",
    actualDate: "actualDate",
    progress: "progress",
    note: "note",
    planned_date: "plannedDate",
    actual_date: "actualDate",
  };
  Object.keys(fields).forEach((key) => {
    const name = fieldMap[key];
    if (!name) return;
    const wrap = form.querySelector(`.edit-field[data-field="${name}"]`);
    if (!wrap) return;
    wrap.classList.add("is-invalid");
    const existing = wrap.querySelector(".field-error");
    const message = String(fields[key]);
    if (existing) existing.textContent = message;
    else wrap.appendChild(overviewEl("small", "field-error", message));
  });
}

function renderOverviewRequestMessage(message) {
  const form = document.getElementById("overview-edit-form");
  if (!form) return;
  const region = form.querySelector(".edit-request-message");
  if (!region) return;
  region.textContent = "";
  if (message) region.appendChild(overviewEl("p", "edit-request-error", message));
}

function setOverviewSavingState(saving) {
  const form = document.getElementById("overview-edit-form");
  if (!form) return;
  const saveButton = form.querySelector(".edit-save-btn");
  const cancelButton = form.querySelector(".edit-cancel-btn");
  if (saveButton) {
    saveButton.disabled = saving;
    saveButton.textContent = saving ? "保存中..." : "保存";
  }
  if (cancelButton) cancelButton.disabled = saving;
}

async function saveDeliverableChanges(event) {
  if (event) event.preventDefault();
  if (!overviewDraft || overviewSaving) return;
  clearOverviewFieldErrors();
  const errors = validateDeliverableDraft();
  if (Object.keys(errors).length > 0) {
    renderOverviewFieldErrors(errors);
    return;
  }
  const item = overviewSavedState.deliverables[overviewDraft.index];
  if (!item) return;
  const payload = {
    status: overviewDraft.values.status.trim(),
    owner: overviewDraft.values.owner.trim(),
    plannedDate: overviewDraft.values.plannedDate,
    actualDate: overviewDraft.values.actualDate,
    progress: Number(overviewDraft.values.progress),
    note: overviewDraft.values.note.trim(),
    updatedAt: item.updatedAt || "",
  };
  overviewSaving = true;
  setOverviewSavingState(true);
  renderOverviewRequestMessage("");
  try {
    const response = await fetch(`/api/project-status/deliverables/${encodeURIComponent(String(item.id))}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(payload),
    });
    const body = await overviewReadJson(response);
    if (!response.ok || !body || body.ok !== true) {
      throw overviewRequestError(body, response.status);
    }
    const saved = body.data || {};
    if (!saved.projectStatus || overviewIsEmpty(saved.projectStatus)) {
      throw new Error("保存响应缺少完整的项目状态，请重试");
    }
    overviewSavedState = saved.projectStatus;
    const editedIndex = overviewDraft.index;
    overviewDraft = null;
    renderProjectOverview();
    expandOverviewDetail(editedIndex);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    renderOverviewRequestMessage(message);
    if (err.fields) renderOverviewServerFieldErrors(err.fields);
    setOverviewSavingState(false);
  } finally {
    overviewSaving = false;
  }
}

function cancelDeliverableEdit() {
  if (!overviewDraft || overviewSaving) return;
  const index = overviewDraft.index;
  overviewDraft = null;
  renderProjectOverview();
  expandOverviewDetail(index);
}

function milestoneSavedValue(item, field, index) {
  if (field === "sortOrder") {
    return typeof item.sortOrder === "number" ? item.sortOrder : index + 1;
  }
  return String(item[field] ?? "");
}

function milestoneDraftDirty() {
  if (!overviewDraft || overviewDraft.kind !== "milestones") return false;
  const saved = overviewSavedState && Array.isArray(overviewSavedState.milestones)
    ? overviewSavedState.milestones
    : [];
  const rows = overviewDraft.rows || [];
  if (rows.length !== saved.length) return true;
  return rows.some((row, index) => {
    const item = saved[index] || {};
    return String(row.id ?? "") !== String(item.id ?? "")
      || row.name !== milestoneSavedValue(item, "name", index)
      || row.date !== milestoneSavedValue(item, "date", index)
      || row.type !== milestoneSavedValue(item, "type", index)
      || row.sortOrder !== milestoneSavedValue(item, "sortOrder", index);
  });
}

function overviewMilestoneStrokeIcon(d) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", "16");
  svg.setAttribute("height", "16");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", d);
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", "2");
  path.setAttribute("stroke-linecap", "round");
  path.setAttribute("stroke-linejoin", "round");
  svg.appendChild(path);
  return svg;
}

function overviewMilestoneIconButton(label, pathData, className) {
  const button = overviewEl("button", className, null);
  button.type = "button";
  button.title = label;
  button.setAttribute("aria-label", label);
  button.appendChild(overviewMilestoneStrokeIcon(pathData));
  button.appendChild(overviewEl("span", "visually-hidden", label));
  return button;
}

function renderMilestoneMaintenance(container, data) {
  if (!container) return;
  clearOverviewContainer(container);
  if (overviewDraft && overviewDraft.kind === "milestones") {
    container.appendChild(renderMilestoneEditForm());
    return;
  }
  renderMilestoneReadonlyList(container, data);
}

function renderMilestoneReadonlyList(container, data) {
  const milestones = data && Array.isArray(data.milestones) ? data.milestones : [];
  const toolbar = overviewEl("div", "milestone-main-toolbar");
  toolbar.appendChild(overviewEl("span", "milestone-count", `共 ${milestones.length} 个节点`));
  const editButton = overviewEl("button", "milestone-edit-btn", null);
  editButton.type = "button";
  const editLabel = "编辑主计划";
  editButton.title = editLabel;
  editButton.setAttribute("aria-label", editLabel);
  editButton.appendChild(overviewPencilIcon());
  editButton.appendChild(overviewEl("span", null, "编辑主计划"));
  editButton.addEventListener("click", () => startMilestoneEdit());
  toolbar.appendChild(editButton);
  container.appendChild(toolbar);

  const list = overviewEl("ul", "milestone-main-list");
  milestones.forEach((item, index) => {
    const row = overviewEl("li", "milestone-main-row");
    const dot = overviewEl("span", `milestone-type-dot is-${item.type || "planned"}`);
    const copy = overviewEl("span", "milestone-main-copy");
    copy.append(
      overviewEl("strong", "milestone-main-name", item.name),
      overviewEl("time", "milestone-main-date", item.date),
      overviewEl("span", "milestone-main-status", item.status),
    );
    row.append(dot, copy, overviewEl("span", "milestone-main-order", String(index + 1)));
    list.appendChild(row);
  });
  container.appendChild(list);
}

function openMilestoneEditor() {
  if (!overviewConfirmDiscard()) return;
  const detailsTab = document.getElementById("overview-tab-details");
  if (detailsTab) activateOverviewTab(detailsTab);
  startMilestoneEdit();
}

function milestoneFieldInput(row, field) {
  if (field === "type") {
    const select = document.createElement("select");
    select.name = "type";
    MILESTONE_TYPE_OPTIONS.forEach((optionDef) => {
      const option = document.createElement("option");
      option.value = optionDef.value;
      option.textContent = optionDef.label;
      select.appendChild(option);
    });
    select.value = MILESTONE_TYPE_OPTIONS.some((option) => option.value === row.type)
      ? row.type
      : "planned";
    return select;
  }
  const input = document.createElement("input");
  input.name = field;
  input.type = field === "date" ? "date" : "text";
  if (field === "name") input.maxLength = 100;
  input.value = field === "date" ? row.date : row.name;
  return input;
}

function milestoneRowElement(row, index) {
  const rowEl = overviewEl("div", "milestone-edit-row");
  rowEl.dataset.localId = row.localId;
  rowEl.appendChild(overviewEl("span", "milestone-edit-order", String(index + 1)));

  const fieldDefs = [
    ["name", "节点名称"],
    ["date", "节点日期"],
    ["type", "节点类型"],
  ];
  fieldDefs.forEach(([field, label]) => {
    const wrap = overviewEl("label", "milestone-field");
    wrap.dataset.field = field;
    wrap.appendChild(overviewEl("span", "milestone-field-label", label));
    const control = milestoneFieldInput(row, field);
    wrap.appendChild(control);
    control.addEventListener(field === "type" ? "change" : "input", () => {
      row[field] = control.value;
      wrap.classList.remove("is-invalid");
      const error = wrap.querySelector(".field-error");
      if (error) error.remove();
    });
    rowEl.appendChild(wrap);
  });

  const actions = overviewEl("div", "milestone-row-actions");
  const upButton = overviewMilestoneIconButton(
    "上移",
    "M12 19V5m-7 7 7-7 7 7",
    "milestone-icon-btn milestone-move-btn",
  );
  const downButton = overviewMilestoneIconButton(
    "下移",
    "M12 5v14m7-7-7 7-7-7",
    "milestone-icon-btn milestone-move-btn",
  );
  const deleteButton = overviewMilestoneIconButton(
    `删除 ${row.name || "节点"}`,
    "M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6h14M10 11v6M14 11v6",
    "milestone-icon-btn milestone-delete-btn",
  );
  upButton.addEventListener("click", () => moveMilestoneRow(row.localId, -1));
  downButton.addEventListener("click", () => moveMilestoneRow(row.localId, 1));
  deleteButton.addEventListener("click", () => deleteMilestoneRow(row.localId));
  actions.append(upButton, downButton, deleteButton);
  rowEl.appendChild(actions);
  return rowEl;
}

function renderMilestoneEditForm() {
  const form = document.createElement("form");
  form.id = "milestone-edit-form";
  form.className = "milestone-edit-form";
  form.noValidate = true;

  const rows = overviewEl("div", "milestone-edit-list");
  overviewDraft.rows.forEach((row, index) => rows.appendChild(milestoneRowElement(row, index)));
  form.appendChild(rows);

  const actions = overviewEl("div", "milestone-form-actions");
  const saveButton = overviewEl("button", "edit-save-btn milestone-save-btn", "保存");
  saveButton.type = "button";
  saveButton.addEventListener("click", saveMilestoneChanges);
  const cancelButton = overviewEl("button", "edit-cancel-btn milestone-cancel-btn", "取消");
  cancelButton.type = "button";
  cancelButton.addEventListener("click", () => cancelMilestoneEdit());
  const addButton = overviewEl("button", "milestone-add-btn", "新增节点");
  addButton.type = "button";
  addButton.addEventListener("click", () => addMilestoneRow());
  const requestMessage = overviewEl("div", "edit-request-message milestone-request-message");
  actions.append(saveButton, cancelButton, addButton, requestMessage);
  form.appendChild(actions);
  return form;
}

function startMilestoneEdit() {
  if (!overviewSavedState || overviewSaving) return;
  if (overviewDraft) {
    if (overviewDraftDirty() && !window.confirm("有未保存的更改，放弃后将继续编辑主计划？")) return;
    overviewDraft = null;
    renderProjectOverview();
  }
  const milestones = Array.isArray(overviewSavedState.milestones) ? overviewSavedState.milestones : [];
  overviewDraft = {
    kind: "milestones",
    updatedAt: overviewSavedState.phase ? overviewSavedState.phase.updatedAt : "",
    rows: milestones.map((item, index) => ({
      localId: `m${index}`,
      id: item.id ?? null,
      name: String(item.name ?? ""),
      date: String(item.date ?? ""),
      status: String(item.status ?? ""),
      type: MILESTONE_TYPE_OPTIONS.some((option) => option.value === item.type)
        ? item.type
        : "planned",
      sortOrder: typeof item.sortOrder === "number" ? item.sortOrder : index + 1,
    })),
  };
  renderProjectOverview();
  const firstControl = document.querySelector("#milestone-edit-form input, #milestone-edit-form select");
  if (firstControl) firstControl.focus();
}

function moveMilestoneRow(localId, delta) {
  if (!overviewDraft || overviewDraft.kind !== "milestones" || overviewSaving) return;
  const rows = overviewDraft.rows;
  const index = rows.findIndex((row) => row.localId === localId);
  const target = index + delta;
  if (index < 0 || target < 0 || target >= rows.length) return;
  const moved = rows.splice(index, 1)[0];
  rows.splice(target, 0, moved);
  renderProjectOverview();
  const input = document.querySelector(
    `#milestone-edit-form .milestone-edit-row[data-local-id="${localId}"] input, `
    + `#milestone-edit-form .milestone-edit-row[data-local-id="${localId}"] select`,
  );
  if (input) input.focus();
}

function deleteMilestoneRow(localId) {
  if (!overviewDraft || overviewDraft.kind !== "milestones" || overviewSaving) return;
  const rows = overviewDraft.rows;
  const index = rows.findIndex((row) => row.localId === localId);
  if (index < 0) return;
  rows.splice(index, 1);
  renderProjectOverview();
  const next = rows[Math.min(index, rows.length - 1)];
  if (next) {
    const input = document.querySelector(
      `#milestone-edit-form .milestone-edit-row[data-local-id="${next.localId}"] input, `
      + `#milestone-edit-form .milestone-edit-row[data-local-id="${next.localId}"] select`,
    );
    if (input) input.focus();
  } else {
    const addButton = document.querySelector("#milestone-edit-form .milestone-add-btn");
    if (addButton) addButton.focus();
  }
}

function addMilestoneRow() {
  if (!overviewDraft || overviewDraft.kind !== "milestones" || overviewSaving) return;
  milestoneLocalSeq += 1;
  const localId = `new-${milestoneLocalSeq}`;
  overviewDraft.rows.push({
    localId,
    id: null,
    name: "",
    date: "",
    status: "",
    type: "planned",
    sortOrder: overviewDraft.rows.length + 1,
  });
  renderProjectOverview();
  const input = document.querySelector(`#milestone-edit-form .milestone-edit-row[data-local-id="${localId}"] input`);
  if (input) input.focus();
}

function validateMilestoneDraft() {
  const errors = {};
  const rows = overviewDraft.rows || [];
  const phase = overviewSavedState ? overviewSavedState.phase : null;
  const start = phase ? phase.startDate : "";
  const end = phase ? phase.endDate : "";
  const today = phase ? phase.today : "";
  const datePattern = /^\d{4}-\d{2}-\d{2}$/;
  const seenNames = new Set();
  let currentCount = 0;
  rows.forEach((row) => {
    const name = String(row.name || "").trim();
    const date = String(row.date || "").trim();
    const dateKey = `${row.localId}.date`;
    if (!name) {
      errors[`${row.localId}.name`] = "节点名称为必填项";
    } else if (name.length > 100) {
      errors[`${row.localId}.name`] = "节点名称不能超过 100 个字符";
    } else if (seenNames.has(name)) {
      errors[`${row.localId}.name`] = "节点名称不能重复";
    }
    seenNames.add(name);
    if (!date) {
      errors[dateKey] = "节点日期为必填项";
    } else if (!datePattern.test(date)) {
      errors[dateKey] = "日期格式应为 YYYY-MM-DD";
    } else if (start && end && (date < start || date > end)) {
      errors[dateKey] = `节点日期需在阶段周期 ${start} 至 ${end} 内`;
    }
    if (!errors[dateKey] && row.type === "done" && today && date > today) {
      errors[dateKey] = `已达成节点日期不能晚于当前日期 ${today}`;
    }
    if (!errors[dateKey] && row.type === "planned" && today && date && date < today) {
      errors[dateKey] = `计划节点日期不能早于当前日期 ${today}`;
    }
    if (row.type === "current") currentCount += 1;
  });
  if (currentCount !== 1) {
    errors.draft = "必须且只能存在一个当前目标节点";
  }
  return errors;
}

function clearMilestoneFieldErrors() {
  const form = document.getElementById("milestone-edit-form");
  if (!form) return;
  form.querySelectorAll(".milestone-field.is-invalid").forEach((wrap) => wrap.classList.remove("is-invalid"));
  form.querySelectorAll(".field-error").forEach((message) => message.remove());
}

function renderMilestoneFieldErrors(errors) {
  const form = document.getElementById("milestone-edit-form");
  if (!form) return;
  Object.keys(errors).forEach((key) => {
    if (key === "draft") {
      renderMilestoneRequestMessage(errors[key]);
      return;
    }
    const parts = key.split(".");
    const localId = parts[0];
    const field = parts[1];
    const row = form.querySelector(`.milestone-edit-row[data-local-id="${localId}"]`);
    if (!row || !field) return;
    const wrap = row.querySelector(`.milestone-field[data-field="${field}"]`);
    if (!wrap) return;
    wrap.classList.add("is-invalid");
    wrap.appendChild(overviewEl("small", "field-error", errors[key]));
  });
  const firstInvalid = form.querySelector(".milestone-field.is-invalid input, .milestone-field.is-invalid select");
  if (firstInvalid) firstInvalid.focus();
}

function renderMilestoneServerFieldErrors(fields) {
  const rows = overviewDraft ? overviewDraft.rows : [];
  const errors = {};
  Object.keys(fields).forEach((key) => {
    const text = String(fields[key]);
    const match = String(key).match(/\[(\d+)\]|\.(\d+)\b/);
    const index = match ? Number(match[1] ?? match[2]) : -1;
    const row = rows[index] || rows[0];
    if (!row) return;
    if (/name/.test(key)) errors[`${row.localId}.name`] = text;
    else if (/date/.test(key)) errors[`${row.localId}.date`] = text;
    else if (/type|status/.test(key)) errors[`${row.localId}.type`] = text;
    else errors.draft = text;
  });
  renderMilestoneFieldErrors(errors);
}

function renderMilestoneRequestMessage(message) {
  const form = document.getElementById("milestone-edit-form");
  if (!form) return;
  const region = form.querySelector(".milestone-request-message");
  if (!region) return;
  region.textContent = "";
  if (message) region.appendChild(overviewEl("p", "edit-request-error", message));
}

function setMilestoneSavingState(saving) {
  const form = document.getElementById("milestone-edit-form");
  if (!form) return;
  const saveButton = form.querySelector(".milestone-save-btn");
  const cancelButton = form.querySelector(".milestone-cancel-btn");
  const addButton = form.querySelector(".milestone-add-btn");
  if (saveButton) {
    saveButton.disabled = saving;
    saveButton.textContent = saving ? "保存中..." : "保存";
  }
  if (cancelButton) cancelButton.disabled = saving;
  if (addButton) addButton.disabled = saving;
}

async function saveMilestoneChanges(event) {
  if (event) event.preventDefault();
  if (!overviewDraft || overviewDraft.kind !== "milestones" || overviewSaving) return;
  clearMilestoneFieldErrors();
  renderMilestoneRequestMessage("");
  const errors = validateMilestoneDraft();
  if (Object.keys(errors).length > 0) {
    renderMilestoneFieldErrors(errors);
    return;
  }
  const payload = {
    milestones: overviewDraft.rows.map((row, index) => ({
      id: row.id ?? null,
      name: String(row.name || "").trim(),
      date: String(row.date || "").trim(),
      status: MILESTONE_LABEL_BY_TYPE[row.type] || row.status,
      type: row.type,
      sortOrder: index + 1,
    })),
    updatedAt: overviewDraft.updatedAt || "",
  };
  overviewSaving = true;
  setMilestoneSavingState(true);
  renderMilestoneRequestMessage("");
  try {
    const response = await fetch("/api/project-status/phases/VPI-T2/milestones", {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(payload),
    });
    const body = await overviewReadJson(response);
    if (!response.ok || !body || body.ok !== true) {
      throw overviewRequestError(body, response.status);
    }
    const saved = body.data || {};
    if (!saved.projectStatus || overviewIsEmpty(saved.projectStatus)) {
      throw new Error("保存响应缺少完整的项目状态，请重试");
    }
    overviewSavedState = saved.projectStatus;
    overviewDraft = null;
    renderProjectOverview();
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    renderMilestoneRequestMessage(message);
    if (err.fields) renderMilestoneServerFieldErrors(err.fields);
    setMilestoneSavingState(false);
  } finally {
    overviewSaving = false;
  }
}

function cancelMilestoneEdit() {
  if (!overviewDraft || overviewDraft.kind !== "milestones" || overviewSaving) return;
  overviewDraft = null;
  renderProjectOverview();
}

function parseHeaders(raw) {
  const headers = {};
  raw.split(/\r?\n|,\s*(?=[A-Za-z0-9_-]+\s*:)/).forEach((line) => {
    const index = line.indexOf(":");
    if (index <= 0) return;
    const key = line.slice(0, index).trim();
    const value = line.slice(index + 1).trim();
    if (key && value) headers[key] = value;
  });
  return headers;
}

function fieldValue(scope, name) {
  const el = scope.querySelector(`[name="${name}"]`);
  return el && el.value.trim() ? el.value.trim() : "";
}

function redactSensitiveText(value) {
  let text = value === null || value === undefined ? "" : String(value);
  SENSITIVE_VALUE_PATTERNS.forEach(([pattern, replacement]) => {
    text = text.replace(pattern, replacement);
  });
  return text;
}

function safeDisplayValue(value) {
  const text = redactSensitiveText(value);
  return text.trim() ? text : "-";
}

function activeFieldGroup(config) {
  return document.querySelector(`[data-mode-fields="${config.fieldGroup}"]`);
}

function collectArasPayload(config) {
  const form = document.getElementById("aras-form");
  const group = activeFieldGroup(config);
  const authMode = fieldValue(form, "auth_mode") || "password";
  const payload = {
    base_url: fieldValue(form, "base_url"),
    auth_mode: authMode,
    headers: parseHeaders(fieldValue(form, "headers")),
    filters: {},
  };
  if (authMode === "password") {
    payload.username = fieldValue(form, "username");
    payload.password = fieldValue(form, "password");
  } else {
    payload.cookie = fieldValue(form, "cookie");
  }
  config.filterNames.forEach((name) => {
    const value = fieldValue(group, name);
    if (name === "project_names") {
      payload.filters[name] = value.split(",").map((item) => item.trim()).filter(Boolean);
    } else {
      payload.filters[name] = value;
    }
  });
  config.numberNames.forEach((name) => {
    payload[name] = Number(fieldValue(group, name) || 0);
  });
  return payload;
}

function clearArasPayloadSecrets(payload) {
  if (!payload) return;
  payload.password = "";
  payload.cookie = "";
  delete payload.cookies;
}

function sanitizeDownloadName(name) {
  return String(name)
    .replace(/[\r\n\u0000-\u001f"\\/]/g, "")
    .replace(/^.*[\\/]/, "")
    .trim();
}

function parseContentDispositionFilename(value) {
  if (!value) return "";
  const star = /filename\*\s*=\s*(?:utf-8''|UTF-8'')([^;]+)/i.exec(value);
  if (star) {
    try {
      const decoded = decodeURIComponent(star[1].trim());
      const safe = sanitizeDownloadName(decoded);
      if (safe) return safe;
    } catch {
      // filename* 解码失败时回退到普通 filename
    }
  }
  const plain = /filename\s*=\s*(?:"([^"]+)"|([^;]+))/i.exec(value);
  if (plain) {
    const safe = sanitizeDownloadName(plain[1] || plain[2] || "");
    if (safe) return safe;
  }
  return "";
}

async function fetchBlobDownload(endpoint, payload, defaultFileName) {
  const resp = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    let message = `HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      const err = body && body.error;
      if (err && err.message) message = formatApiErrorMessage(err, resp.status);
    } catch {
      // 非 JSON 错误体不回显
    }
    throw new Error(redactSensitiveText(message));
  }
  const blob = await resp.blob();
  const fileName =
    parseContentDispositionFilename(resp.headers.get("Content-Disposition")) ||
    defaultFileName ||
    "aras-export.csv";
  const rowCount = resp.headers.get("X-Export-Row-Count");
  const truncated =
    resp.headers.get("X-Export-Truncated") === "true" ||
    resp.headers.get("X-Export-Complete") === "false";
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
  return { fileName, rowCount, truncated };
}

function setArasStatus(text, isRunning) {
  const status = document.getElementById("aras-status");
  status.textContent = text || "";
  status.classList.toggle("loading", Boolean(isRunning && text));
  document.querySelectorAll("[data-aras-action]").forEach((button) => {
    button.disabled = Boolean(isRunning);
    button.classList.toggle("is-running", Boolean(isRunning));
  });
  document.body.classList.toggle("aras-running", Boolean(isRunning));
}

function restoreArasButtons() {
  document.querySelectorAll("[data-aras-action]").forEach((button) => {
    button.disabled = false;
    button.classList.remove("is-running");
  });
  document.body.classList.remove("aras-running");
}

function showArasError(message) {
  const error = document.getElementById("aras-error");
  error.hidden = !message;
  error.textContent = message || "";
  document.querySelector(".result-panel")?.classList.toggle("has-output", Boolean(message));
}

function showArasWarning(message) {
  const warning = document.getElementById("aras-warning");
  warning.hidden = !message;
  warning.textContent = message || "";
}

function renderSummary(data) {
  const table = document.createElement("table");
  table.className = "result-table";
  const body = document.createElement("tbody");
  Object.entries(data).forEach(([key, value]) => {
    if (SENSITIVE_COLUMNS.has(key.toLowerCase())) return;
    const row = document.createElement("tr");
    const keyCell = document.createElement("th");
    const valueCell = document.createElement("td");
    keyCell.textContent = key;
    valueCell.textContent = safeDisplayValue(value);
    row.append(keyCell, valueCell);
    body.appendChild(row);
  });
  table.appendChild(body);
  return table;
}

function orderedColumns(rows, preferredColumns) {
  const available = new Set();
  rows.forEach((row) => {
    Object.keys(row).forEach((key) => {
      if (!SENSITIVE_COLUMNS.has(key.toLowerCase())) available.add(key);
    });
  });
  const columns = preferredColumns.filter((key) => available.has(key));
  Array.from(available).filter((key) => !columns.includes(key)).sort().forEach((key) => columns.push(key));
  return columns.slice(0, 12);
}

function renderRows(data, preferredColumns) {
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  const table = document.createElement("table");
  table.className = "result-table";
  const rows = data.rows || [];
  const keys = orderedColumns(rows, preferredColumns);
  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  (keys.length ? keys : ["消息"]).forEach((key) => {
    const th = document.createElement("th");
    th.textContent = key;
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  if (rows.length) {
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      keys.forEach((key) => {
        const td = document.createElement("td");
        td.textContent = safeDisplayValue(row[key]);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
  } else {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = keys.length || 1;
    td.textContent = "无结果";
    tr.appendChild(td);
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  return wrap;
}

function renderArasResult(data, mode, config) {
  const target = document.getElementById("aras-result");
  document.querySelector(".result-panel")?.classList.add("has-output");
  target.className = "result-output-content";
  target.innerHTML = "";
  document.getElementById("result-kind").textContent = RESULT_KIND_LABELS[config.resultKind] || config.resultKind;
  const outputMeta = document.createElement("p");
  outputMeta.className = "result-output-meta";
  outputMeta.textContent = `${COMMAND_LABELS[mode] || mode} -> ${config.endpoint}`;
  target.appendChild(outputMeta);
  if (config.resultKind === "rows") {
    const meta = document.createElement("p");
    meta.className = "result-meta";
    meta.textContent = `页码=${data.page || "-"} 行数=${data.count || 0} 项目数=${(data.item_ids || []).length}`;
    target.appendChild(meta);
    target.appendChild(renderRows(data, config.preferredColumns));
  } else {
    target.appendChild(renderSummary(data));
  }
}

async function runArasQuery() {
  if (arasRunning) {
    arasQueuedAction = "query";
    setArasStatus("已排队", true);
    return;
  }
  arasRunning = true;
  const requestMode = arasMode;
  const requestConfig = ARAS_MODES[requestMode];
  const seq = ++arasRequestSeq;
  setArasStatus("运行中", true);
  showArasError("");
  showArasWarning("");
  const payload = collectArasPayload(requestConfig);
  try {
    const resp = await fetch(requestConfig.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await resp.json();
    if (!resp.ok || !body.ok) {
      const err = body.error || {};
      throw new Error(formatApiErrorMessage(err, resp.status));
    }
    if (seq > arasLatestRendered) {
      arasLatestRendered = seq;
      renderArasResult(body.data || {}, requestMode, requestConfig);
    }
  } catch (err) {
    if (seq > arasLatestRendered) {
      arasLatestRendered = seq;
      showArasError(redactSensitiveText(err.message));
    }
  } finally {
    clearArasPayloadSecrets(payload);
    arasRunning = false;
    const queued = arasQueuedAction;
    arasQueuedAction = "";
    if (queued === "export") {
      runArasExport();
    } else if (queued === "query") {
      runArasQuery();
    } else {
      setArasStatus("", false);
    }
  }
}

async function runArasExport() {
  if (arasRunning) {
    arasQueuedAction = "export";
    setArasStatus("已排队", true);
    return;
  }
  arasRunning = true;
  const requestMode = arasMode;
  const requestConfig = ARAS_MODES[requestMode];
  const endpoint = requestConfig.exportEndpoint || requestConfig.downloadEndpoint;
  if (!endpoint) {
    arasRunning = false;
    restoreArasButtons();
    return;
  }
  const payload = collectArasPayload({
    ...requestConfig,
    numberNames: requestConfig.exportNumberNames || [],
  });
  setArasStatus("导出中", true);
  showArasError("");
  showArasWarning("");
  try {
    const outcome = await fetchBlobDownload(endpoint, payload, requestConfig.defaultFileName);
    const parts = [`已下载：${outcome.fileName}`];
    if (outcome.rowCount != null) parts.push(`共 ${outcome.rowCount} 行`);
    setArasStatus(parts.join("，"), false);
    if (outcome.truncated) {
      showArasWarning("导出已截断：结果超过 max_records / max_pages 限制，文件不完整！请调大限制后重试。");
    }
  } catch (err) {
    setArasStatus("", false);
    showArasError(redactSensitiveText(err.message));
  } finally {
    clearArasPayloadSecrets(payload);
    arasRunning = false;
    const queued = arasQueuedAction;
    arasQueuedAction = "";
    if (queued === "export") {
      runArasExport();
    } else if (queued === "query") {
      runArasQuery();
    } else {
      restoreArasButtons();
    }
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}

function deliverableItemById(id) {
  return deliverableCatalog.find((item) => item.id === id) || null;
}

function visibleDeliverables() {
  const category = document.getElementById("deliverable-category-filter").value;
  const status = document.getElementById("deliverable-status-filter").value;
  return deliverableCatalog.filter((item) =>
    (!category || item.category === category) && (!status || item.implementation_status === status)
  );
}

function fillDeliverableFilter(select, options) {
  const previous = select.value;
  select.innerHTML = "";
  options.forEach((option) => {
    const el = document.createElement("option");
    el.value = option.id;
    el.textContent = option.name;
    select.appendChild(el);
  });
  if (options.some((option) => option.id === previous)) select.value = previous;
}

function renderDeliverableFilters() {
  const categories = [{ id: "", name: "全部分类" }, ...deliverableCategories];
  const statuses = [{ id: "", name: "全部状态" }];
  Object.entries(DELIVERABLE_STATUS_LABELS).forEach(([id, name]) => {
    if (deliverableCatalog.some((item) => item.implementation_status === id)) {
      statuses.push({ id, name });
    }
  });
  fillDeliverableFilter(document.getElementById("deliverable-category-filter"), categories);
  fillDeliverableFilter(document.getElementById("deliverable-status-filter"), statuses);
}

function renderDeliverableList() {
  const container = document.getElementById("deliverable-list");
  container.innerHTML = "";
  const items = visibleDeliverables();
  if (!items.length) {
    container.className = "deliverable-list is-empty";
    container.textContent = "没有匹配的目录项";
    return;
  }
  container.className = "deliverable-list";
  items.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "deliverable-item";
    if (item.id === selectedDeliverableId) button.classList.add("active");
    if (item.availability !== "available") button.classList.add("is-unavailable");
    const name = document.createElement("span");
    name.className = "deliverable-name";
    name.textContent = item.name;
    const categoryName = (deliverableCategories.find((entry) => entry.id === item.category) || {}).name || item.category;
    const meta = document.createElement("span");
    meta.className = "deliverable-meta";
    meta.textContent = `${categoryName} · ${DELIVERABLE_AVAILABILITY_LABELS[item.availability] || item.availability} · ${DELIVERABLE_STATUS_LABELS[item.implementation_status] || item.implementation_status}`;
    button.append(name, meta);
    button.addEventListener("click", () => {
      selectedDeliverableId = item.id;
      document.querySelectorAll(".deliverable-item").forEach((el) => {
        el.classList.toggle("active", el === button);
      });
      renderDeliverableDetail(item);
    });
    container.appendChild(button);
  });
}

async function loadDeliverablesCatalog(force) {
  if (deliverableCatalogLoaded && !force) return;
  const list = document.getElementById("deliverable-list");
  list.className = "deliverable-list loading";
  list.textContent = "加载目录中";
  try {
    const resp = await fetch("/api/deliverables/catalog");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const body = await resp.json();
    if (!body.ok || !body.data) {
      const err = body.error || {};
      throw new Error(err.message || "目录响应无效");
    }
    deliverableCatalog = Array.isArray(body.data.deliverables) ? body.data.deliverables : [];
    deliverableCategories = Array.isArray(body.data.categories) ? body.data.categories : [];
    deliverableCatalogLoaded = true;
    renderDeliverableFilters();
    renderDeliverableList();
    const current = deliverableItemById(selectedDeliverableId);
    if (current) {
      renderDeliverableDetail(current);
    } else {
      const preferred = deliverableCatalog.find((item) => item.availability === "available") || deliverableCatalog[0] || null;
      if (preferred) {
        selectedDeliverableId = preferred.id;
        renderDeliverableDetail(preferred);
      }
    }
  } catch (err) {
    list.innerHTML = "";
    list.className = "deliverable-list is-empty";
    const message = document.createElement("p");
    message.className = "error-msg";
    message.textContent = `目录加载失败：${redactSensitiveText(err.message)}`;
    list.appendChild(message);
  }
}

function setDeliverableOperationControls(mode) {
  const controls = document.getElementById("deliverable-operation-controls");
  if (!controls) return;
  controls.querySelectorAll("[data-query-only]").forEach((el) => {
    el.hidden = mode !== "query";
  });
  controls.querySelectorAll("[data-shared-size]").forEach((el) => {
    el.hidden = mode === "export";
  });
  controls.querySelectorAll("[data-crawl-only]").forEach((el) => {
    el.hidden = mode !== "crawl_all";
  });
  controls.querySelectorAll("[data-export-only]").forEach((el) => {
    el.hidden = mode !== "export";
  });
}

function setupDeliverableAuthentication(form) {
  const selector = form.querySelector('[name="auth_mode"]');
  const note = form.querySelector("#tdc-auth-note");
  const sync = () => {
    const mode = selector.value === "browser" ? "browser" : "password";
    form.querySelectorAll("[data-tdc-auth-fields]").forEach((group) => {
      group.hidden = group.dataset.tdcAuthFields !== mode;
    });
    form.querySelectorAll('[name="username"], [name="password"]').forEach((input) => {
      input.required = mode === "password";
    });
    const cookie = form.querySelector('[name="cookie"]');
    if (cookie) cookie.required = false;
    note.textContent = mode === "password"
      ? "密码仅用于本次请求，由后端完成 TDC 登录，不会持久化。"
      : "使用浏览器已认证的 Cookie；也可在请求头中提供 Authorization。";
  };
  selector.addEventListener("change", sync);
  sync();
}

function validateDeliverableForm(form) {
  if (form.checkValidity()) return true;
  form.reportValidity();
  return false;
}

function buildDeliverableForm(item) {
  const form = document.createElement("form");
  form.id = "deliverable-form";
  form.className = "deliverable-form";
  form.autocomplete = "off";
  const config = TDC_ENDPOINTS[item.id] || {
    slug: item.id.replace(/^tdc-/, ""),
    defaultExportName: "tdc_export.xlsx",
  };
  form.dataset.tdcSlug = config.slug;
  form.dataset.defaultExportName = config.defaultExportName;

  const connection = document.createElement("section");
  connection.className = "form-block connection-block";
  connection.innerHTML = `
    <div class="block-title">
      <p class="eyebrow">连接</p>
      <h4>请求上下文</h4>
    </div>
    <div class="form-grid">
      <label>
        <span>Base URL</span>
        <input id="tdc-base-url" name="base_url" type="url" required value="https://tdc.sgmw.com.cn" />
      </label>
      <label>
        <span>认证方式</span>
        <select id="tdc-auth-mode" name="auth_mode">
          <option value="password" selected>账号密码</option>
          <option value="browser">浏览器 Cookie / Header</option>
        </select>
      </label>
      <label data-tdc-auth-fields="password">
        <span>用户名</span>
        <input id="tdc-username" name="username" autocomplete="off" />
      </label>
      <label data-tdc-auth-fields="password">
        <span>密码</span>
        <input id="tdc-password" name="password" type="password" autocomplete="off" />
      </label>
      <label data-tdc-auth-fields="browser" hidden>
        <span>Cookie</span>
        <input id="tdc-cookie" name="cookie" type="password" autocomplete="off" />
      </label>
      <label class="wide">
        <span>请求头</span>
        <textarea id="tdc-headers" name="headers" rows="3" placeholder="名称: 值"></textarea>
      </label>
    </div>
    <p id="tdc-auth-note" class="connection-note">密码仅用于本次请求，由后端完成 TDC 登录，不会持久化。</p>`;
  form.appendChild(connection);

  const fieldsSection = document.createElement("section");
  fieldsSection.className = "form-block fields-block";
  const fieldsTitle = document.createElement("div");
  fieldsTitle.className = "block-title";
  fieldsTitle.innerHTML = `<p class="eyebrow">筛选</p><h4>查询字段</h4>`;
  fieldsSection.appendChild(fieldsTitle);
  const fieldsGrid = document.createElement("div");
  fieldsGrid.className = "dyna-form-grid";
  (item.fields || []).forEach((field) => {
    const label = document.createElement("label");
    const span = document.createElement("span");
    span.textContent = field.label || field.name;
    const input = document.createElement("input");
    input.name = field.name;
    input.dataset.deliverableField = field.name;
    input.type = field.type === "date" ? "date" : field.type === "number" ? "number" : "text";
    label.append(span, input);
    fieldsGrid.appendChild(label);
  });
  fieldsSection.appendChild(fieldsGrid);
  form.appendChild(fieldsSection);

  const operations = document.createElement("section");
  operations.className = "form-block actions-block deliverable-actions";
  const controls = document.createElement("div");
  controls.id = "deliverable-operation-controls";
  controls.className = "operation-controls";
  controls.innerHTML = `
    <label class="wide"><span>操作方式</span><select id="deliverable-operation-mode" name="operation_mode">
      <option value="query" selected>查询预览</option>
      <option value="crawl_all">全量抓取</option>
      <option value="export">导出 XLSX</option>
    </select></label>
    <label data-query-only><span>页码</span><input name="page" type="number" min="1" value="1" required /></label>
    <label data-shared-size><span>每页条数</span><input name="page_size" type="number" min="1" value="50" required /></label>
    <label data-crawl-only hidden><span>最大页数</span><input name="max_pages" type="number" min="1" value="100" required /></label>
    <label data-crawl-only hidden><span>最大记录数</span><input name="max_records" type="number" min="1" value="10000" required /></label>
    <label data-export-only hidden><span>输出格式</span><select name="output_format" required><option value="XLSX" selected>XLSX</option></select></label>
    <label data-export-only hidden><span>XLSX 文件名</span><input name="file_name" type="text" value="${escapeHtml(config.defaultExportName)}" required /></label>`;
  const buttons = document.createElement("div");
  buttons.className = "operation-buttons";
  buttons.innerHTML = `<button type="submit" id="deliverable-run-button" class="primary-btn" data-deliverable-run>${DELIVERABLE_OPERATION_LABELS.query}</button>`;
  const status = document.createElement("span");
  status.id = "deliverable-status";
  status.className = "deliverable-status";
  status.setAttribute("aria-live", "polite");
  operations.append(controls, buttons, status);
  form.appendChild(operations);

  const operationMode = form.querySelector('[name="operation_mode"]');
  const runButton = form.querySelector("#deliverable-run-button");
  const syncDeliverableOperation = () => {
    const operation = operationMode.value || "query";
    setDeliverableOperationControls(operation);
    runButton.textContent = DELIVERABLE_OPERATION_LABELS[operation] || operation;
  };
  operationMode.addEventListener("change", syncDeliverableOperation);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const operation = operationMode.value || "query";
    setDeliverableOperationControls(operation);
    if (!validateDeliverableForm(form)) return;
    runDeliverableOperation(item, operation);
  });
  setupDeliverableAuthentication(form);
  syncDeliverableOperation();
  return form;
}

function renderDeliverableDetail(item) {
  const detail = document.getElementById("deliverable-detail");
  const panel = document.getElementById("deliverable-result-panel");
  const error = document.getElementById("deliverable-error");
  const result = document.getElementById("deliverable-result");
  deliverableLatestRendered = deliverableRequestSeq;
  detail.innerHTML = "";
  panel.hidden = true;
  error.hidden = true;
  result.className = "is-empty";
  result.textContent = "暂无结果";

  const categoryName = (deliverableCategories.find((entry) => entry.id === item.category) || {}).name || item.category;
  const head = document.createElement("div");
  head.className = "detail-head";
  const headText = document.createElement("div");
  const eyebrow = document.createElement("p");
  eyebrow.className = "eyebrow";
  eyebrow.textContent = categoryName;
  const title = document.createElement("h4");
  title.textContent = item.name;
  headText.append(eyebrow, title);
  const chips = document.createElement("div");
  chips.className = "chip-row";
  const availabilityChip = document.createElement("span");
  availabilityChip.className = `status-chip availability-${item.availability}`;
  availabilityChip.textContent = DELIVERABLE_AVAILABILITY_LABELS[item.availability] || item.availability;
  const statusChip = document.createElement("span");
  statusChip.className = `status-chip ${DELIVERABLE_STATUS_TONE_CLASS[item.implementation_status] || "is-unknown"}`;
  statusChip.textContent = DELIVERABLE_STATUS_LABELS[item.implementation_status] || item.implementation_status;
  chips.append(availabilityChip, statusChip);
  head.append(headText, chips);

  const source = document.createElement("p");
  source.className = "detail-source";
  source.textContent = `来源：${item.source || "-"}`;
  const description = document.createElement("p");
  description.className = "detail-description";
  description.textContent = item.description || "";
  detail.append(head, source, description);
  if (item.reason) {
    const reason = document.createElement("p");
    reason.className = "reason-note";
    reason.textContent = item.reason;
    detail.appendChild(reason);
  }

  const executableTdc = item.availability === "available" && Boolean(TDC_ENDPOINTS[item.id]);
  const arasTarget = item.target && item.target.panel === "aras-panel";
  if (executableTdc) {
    detail.appendChild(buildDeliverableForm(item));
  } else if (arasTarget) {
    const openButton = document.createElement("button");
    openButton.type = "button";
    openButton.className = "primary-btn";
    openButton.textContent = "在 Aras 工作区打开";
    openButton.addEventListener("click", () => openDeliverableInAras(item));
    detail.appendChild(openButton);
  }
  detail.classList.remove("is-empty");
}

function collectDeliverablePayload(item, operation) {
  const form = document.getElementById("deliverable-form");
  const authMode = fieldValue(form, "auth_mode") || "password";
  const payload = {
    base_url: fieldValue(form, "base_url"),
    auth_mode: authMode,
    headers: parseHeaders(fieldValue(form, "headers")),
    filters: {},
  };
  if (authMode === "password") {
    payload.username = fieldValue(form, "username");
    payload.password = fieldValue(form, "password");
  } else {
    payload.cookie = fieldValue(form, "cookie");
  }
  (item.fields || []).forEach((field) => {
    const value = fieldValue(form, field.name);
    if (value) payload.filters[field.name] = value;
  });
  const numberNames = operation === "query"
    ? ["page", "page_size"]
    : operation === "crawl_all"
      ? ["page_size", "max_pages", "max_records"]
      : [];
  numberNames.forEach((name) => {
    const value = Number(fieldValue(form, name) || 0);
    if (value > 0) payload[name] = value;
  });
  if (operation === "export") {
    const file_name = fieldValue(form, "file_name");
    if (file_name) payload.file_name = file_name;
  }
  return payload;
}

function clearDeliverablePayloadSecrets(payload) {
  if (!payload) return;
  payload.password = "";
  payload.cookie = "";
  payload.headers = {};
  delete payload.cookies;
}

function clearDeliverableFormSecrets(authMode) {
  ["tdc-password", "tdc-cookie"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  if (authMode === "browser") {
    const headers = document.getElementById("tdc-headers");
    if (headers) headers.value = "";
  }
}

function setDeliverableStatus(text, isRunning) {
  const status = document.getElementById("deliverable-status");
  if (status) {
    status.textContent = text || "";
    status.classList.toggle("loading", Boolean(isRunning && text));
  }
  const mode = document.getElementById("deliverable-operation-mode");
  if (mode) mode.disabled = Boolean(isRunning);
  const runButton = document.getElementById("deliverable-run-button");
  if (runButton) {
    runButton.disabled = Boolean(isRunning);
    runButton.classList.toggle("is-running", Boolean(isRunning));
  }
}

function showDeliverableError(message) {
  const error = document.getElementById("deliverable-error");
  error.hidden = !message;
  error.textContent = message || "";
  if (message) {
    const panel = document.getElementById("deliverable-result-panel");
    if (panel) panel.hidden = false;
  }
}

function renderDeliverableResult(data, item, operation) {
  const panel = document.getElementById("deliverable-result-panel");
  const target = document.getElementById("deliverable-result");
  panel.hidden = false;
  panel.classList.add("has-output");
  target.className = "result-output-content";
  target.innerHTML = "";
  document.getElementById("deliverable-result-kind").textContent = DELIVERABLE_OPERATION_LABELS[operation] || operation;
  const meta = document.createElement("p");
  meta.className = "result-output-meta";
  meta.textContent = `${item.name} -> ${operation}`;
  target.appendChild(meta);
  const detail = document.createElement("p");
  detail.className = "result-meta";
  detail.textContent = `report=${data.report_type || "-"} page=${data.page || "-"}/${data.pages || "-"} rows=${(data.rows || []).length} unique=${data.unique_count ?? "-"} dup=${data.duplicate_count ?? "-"} fetched=${data.fetched_pages ?? "-"} stop=${data.stop_reason || "-"} granularity=${data.record_granularity || "-"}`;
  target.appendChild(detail);
  target.appendChild(renderRows(data, []));
}

function recordRecentRun(item, operation, status, summary) {
  recentRuns.unshift({
    id: item.id,
    name: item.name,
    operation,
    status,
    summary: String(summary || ""),
    time: new Date().toLocaleTimeString(),
  });
  if (recentRuns.length > RECENT_RUN_LIMIT) recentRuns.length = RECENT_RUN_LIMIT;
  renderRecentRuns();
}

function renderRecentRuns() {
  const container = document.getElementById("deliverable-recent");
  container.innerHTML = "";
  container.className = recentRuns.length ? "recent-list" : "recent-list is-empty";
  if (!recentRuns.length) {
    container.textContent = "暂无运行记录";
    return;
  }
  recentRuns.forEach((run) => {
    const row = document.createElement("div");
    row.className = "recent-item";
    const title = document.createElement("span");
    title.className = "recent-title";
    title.textContent = `${run.name} · ${DELIVERABLE_OPERATION_LABELS[run.operation] || run.operation}`;
    const status = document.createElement("span");
    status.className = `recent-status ${run.status === "success" ? "is-success" : "is-failed"}`;
    status.textContent = run.status === "success" ? "成功" : "失败";
    const summary = document.createElement("span");
    summary.className = "recent-summary";
    summary.textContent = run.summary;
    const time = document.createElement("span");
    time.className = "recent-time";
    time.textContent = run.time;
    row.append(title, status, summary, time);
    container.appendChild(row);
  });
}

async function runDeliverableOperation(item, operation) {
  if (deliverableRunning) {
    setDeliverableStatus("当前请求仍在处理中，请等待完成", true);
    return;
  }
  const config = TDC_ENDPOINTS[item.id];
  if (!config || item.availability !== "available") return;
  deliverableRunning = true;
  const seq = ++deliverableRequestSeq;
  setDeliverableStatus(operation === "export" ? "导出中" : "运行中", true);
  showDeliverableError("");
  const payload = collectDeliverablePayload(item, operation);
  const endpoint = config.endpoints[operation];
  if (!endpoint) {
    deliverableRunning = false;
    setDeliverableStatus("", false);
    clearDeliverablePayloadSecrets(payload);
    clearDeliverableFormSecrets(payload.auth_mode);
    return;
  }
  try {
    if (operation === "export") {
      const outcome = await fetchBlobDownload(endpoint, payload, config.defaultExportName);
      if (seq > deliverableLatestRendered) {
        deliverableLatestRendered = seq;
        const panel = document.getElementById("deliverable-result-panel");
        const target = document.getElementById("deliverable-result");
        panel.hidden = false;
        target.className = "result-output-content";
        target.innerHTML = "";
        const meta = document.createElement("p");
        meta.className = "result-output-meta";
        meta.textContent = `已下载：${outcome.fileName}`;
        target.appendChild(meta);
        document.getElementById("deliverable-result-kind").textContent = "导出 XLSX";
      }
      recordRecentRun(item, operation, "success", `文件 ${outcome.fileName}`);
      setDeliverableStatus(`已下载：${outcome.fileName}`, false);
    } else {
      const resp = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await resp.json();
      if (!resp.ok || !body.ok) {
        const err = body.error || {};
        throw new Error(formatApiErrorMessage(err, resp.status));
      }
      if (seq > deliverableLatestRendered) {
        deliverableLatestRendered = seq;
        renderDeliverableResult(body.data || {}, item, operation);
      }
      const data = body.data || {};
      recordRecentRun(item, operation, "success", `rows=${(data.rows || []).length}`);
      setDeliverableStatus("完成", false);
    }
  } catch (err) {
    if (seq > deliverableLatestRendered) {
      deliverableLatestRendered = seq;
      showDeliverableError(redactSensitiveText(err.message));
    }
    recordRecentRun(item, operation, "failed", redactSensitiveText(err.message));
    setDeliverableStatus("", false);
  } finally {
    clearDeliverablePayloadSecrets(payload);
    clearDeliverableFormSecrets(payload.auth_mode);
    deliverableRunning = false;
  }
}

function openDeliverableInAras(item) {
  const mode = item.target && item.target.mode;
  const modeButton = document.querySelector(`[data-aras-mode="${mode}"]`);
  if (modeButton) modeButton.click();
  const arasLink = document.querySelector('[data-panel-link="aras-panel"]');
  if (arasLink) arasLink.click();
}

function setupDeliverables() {
  const refresh = document.getElementById("deliverable-refresh");
  if (refresh) refresh.addEventListener("click", () => loadDeliverablesCatalog(true));
  ["deliverable-category-filter", "deliverable-status-filter"].forEach((id) => {
    const select = document.getElementById(id);
    if (!select) return;
    select.addEventListener("change", () => {
      const current = deliverableItemById(selectedDeliverableId);
      renderDeliverableList();
      if (current && visibleDeliverables().some((item) => item.id === current.id)) {
        renderDeliverableDetail(current);
      } else {
        const first = visibleDeliverables()[0] || null;
        if (first) {
          selectedDeliverableId = first.id;
          renderDeliverableDetail(first);
        }
      }
    });
  });
}

function setupPanels() {
  document.querySelectorAll("[data-panel-link]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      if (!overviewConfirmDiscard()) return;
      document.querySelectorAll("[data-panel-link]").forEach((item) => item.classList.remove("active"));
      link.classList.add("active");
      document.querySelectorAll(".panel-section").forEach((panel) => {
        panel.hidden = panel.id !== link.dataset.panelLink;
      });
      const isAras = link.dataset.panelLink === "aras-panel";
      const isDeliverables = link.dataset.panelLink === "deliverables";
      const isArchive = link.dataset.panelLink === "scheduled-archive";
      document.body.dataset.sessionView = isAras
        ? "aras"
        : isDeliverables
        ? "deliverables"
        : isArchive
        ? "scheduled-archive"
        : "overview";
      document.getElementById("session-title").textContent = isAras
        ? "Aras 查询工具"
        : isDeliverables
        ? "交付物工作台"
        : isArchive
        ? "定时归档管理"
        : "项目状态";
      document.getElementById("command-label").textContent = isAras
        ? (COMMAND_LABELS[arasMode] || arasMode)
        : isDeliverables
        ? "目录"
        : isArchive
        ? "归档"
        : "就绪";
      if (isDeliverables) loadDeliverablesCatalog();
      if (isArchive) loadArchiveJobs();
    });
  });
}

/* ── Scheduled Archive Administration Module ────────────────────────── */

let archiveJobs = [];
let archiveJobsLoading = false;
let selectedArchiveJobKey = "";
let archiveSelectedRunId = null;
let archiveHistoryTab = "runs"; // 'runs' | 'audit'
let archiveMutating = false;

const ARCHIVE_JOB_NAMES = {
  aras_ewo: "Aras EWO 变更归档",
  aras_paa: "Aras PAA 变更归档",
  aras_ncr_progress: "Aras NCR 审批进度归档",
  aras_ncr_detail: "Aras NCR 审批明细归档",
  tdc_data_model: "TDC 数据模型归档",
  tdc_sor: "TDC SOR 零件明细归档",
};

const ARCHIVE_SOURCE_LABELS = {
  aras: "Aras PLM",
  tdc: "TDC 车体",
};

function archiveEl(tagName, className, text) {
  const node = document.createElement(tagName);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function clearArchiveContainer(container) {
  if (container) container.textContent = "";
}

function showArchiveGlobalError(message) {
  const el = document.getElementById("archive-global-error");
  if (!el) return;
  if (message) {
    el.hidden = false;
    el.textContent = message;
  } else {
    el.hidden = true;
    el.textContent = "";
  }
}

function setArchiveGlobalStatus(message) {
  const el = document.getElementById("archive-global-status");
  if (el) el.textContent = message || "";
}

function archiveFormatDate(isoString) {
  if (!isoString) return "待确认/未知";
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return "待确认/未知";
    const pad = (n) => String(n).padStart(2, "0");
    const year = d.getFullYear();
    const month = pad(d.getMonth() + 1);
    const day = pad(d.getDate());
    const hours = pad(d.getHours());
    const mins = pad(d.getMinutes());
    const secs = pad(d.getSeconds());
    return `${year}-${month}-${day} ${hours}:${mins}:${secs}`;
  } catch (_e) {
    return "待确认/未知";
  }
}

function archiveFreshnessChip(freshness) {
  const chip = archiveEl("span", "archive-chip");
  if (freshness === "fresh") {
    chip.classList.add("is-fresh");
    chip.textContent = "24 小时内";
  } else if (freshness === "stale") {
    chip.classList.add("is-stale");
    chip.textContent = "已陈旧";
  } else {
    chip.classList.add("is-unknown");
    chip.textContent = "待确认/未知";
  }
  return chip;
}

function archiveSyncStateChip(syncState) {
  const chip = archiveEl("span", "archive-chip");
  if (syncState === "needs_attention") {
    chip.classList.add("is-needs-attention");
    chip.textContent = "需关注";
  } else if (syncState === "success") {
    chip.classList.add("is-fresh");
    chip.textContent = "正常";
  } else if (syncState === "idle") {
    chip.classList.add("is-unknown");
    chip.textContent = "空闲";
  } else if (syncState === "running") {
    chip.classList.add("is-running");
    chip.textContent = "同步中";
  } else if (syncState === "failed") {
    chip.classList.add("is-failed");
    chip.textContent = "失败";
  } else {
    chip.classList.add("is-unknown");
    chip.textContent = "待确认/未知";
  }
  return chip;
}

function archiveRunStateChip(state) {
  const chip = archiveEl("span", "archive-chip");
  if (state === "success") {
    chip.classList.add("is-success");
    chip.textContent = "成功";
  } else if (state === "failed") {
    chip.classList.add("is-failed");
    chip.textContent = "失败";
  } else if (state === "running") {
    chip.classList.add("is-running");
    chip.textContent = "运行中";
  } else if (state === "leased") {
    chip.classList.add("is-running");
    chip.textContent = "已锁定";
  } else if (state === "partial") {
    chip.classList.add("is-stale");
    chip.textContent = "部分完成";
  } else if (state === "needs_attention") {
    chip.classList.add("is-needs-attention");
    chip.textContent = "需关注";
  } else if (state === "expired") {
    chip.classList.add("is-failed");
    chip.textContent = "已超时";
  } else {
    chip.classList.add("is-unknown");
    chip.textContent = "待确认/未知";
  }
  return chip;
}

async function loadArchiveJobs(keepSelection = true) {
  const container = document.getElementById("archive-jobs-list");
  if (!container) return;
  showArchiveGlobalError("");
  archiveJobsLoading = true;
  clearArchiveContainer(container);
  container.appendChild(archiveEl("p", "loading", "加载任务中..."));

  try {
    const resp = await fetch("/api/scheduled-archive/jobs", {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const body = await resp.json();
    if (!resp.ok || !body.ok) {
      const err = (body.error && body.error.message) || "加载归档任务失败";
      showArchiveGlobalError(err);
      clearArchiveContainer(container);
      container.appendChild(archiveEl("p", "is-empty", "加载失败"));
      return;
    }
    archiveJobs = Array.isArray(body.data) ? body.data : [];
    renderArchiveJobsList(keepSelection);
  } catch (exc) {
    showArchiveGlobalError("网络异常或服务器未响应");
    clearArchiveContainer(container);
    container.appendChild(archiveEl("p", "is-empty", "加载失败"));
  } finally {
    archiveJobsLoading = false;
  }
}

function renderArchiveJobsList(keepSelection) {
  const container = document.getElementById("archive-jobs-list");
  if (!container) return;
  clearArchiveContainer(container);

  if (archiveJobs.length === 0) {
    container.appendChild(archiveEl("p", "is-empty", "暂无归档任务"));
    renderArchiveConfigCard(null);
    return;
  }

  let selectedJob = null;
  if (keepSelection && selectedArchiveJobKey) {
    selectedJob = archiveJobs.find((j) => j.jobKey === selectedArchiveJobKey);
  }
  if (!selectedJob) {
    selectedJob = archiveJobs[0];
    selectedArchiveJobKey = selectedJob.jobKey;
  }

  archiveJobs.forEach((job) => {
    const item = archiveEl("button", "archive-job-item");
    item.type = "button";
    if (job.jobKey === selectedArchiveJobKey) item.classList.add("active");
    if (!job.enabled) item.classList.add("is-disabled");

    const head = archiveEl("div", "archive-job-head");
    const title = archiveEl("span", "archive-job-title", ARCHIVE_JOB_NAMES[job.jobKey] || job.jobKey);
    const freshness = archiveFreshnessChip(job.freshness);
    head.appendChild(title);
    head.appendChild(freshness);

    const meta = archiveEl("div", "archive-job-meta");
    const sourceText = ARCHIVE_SOURCE_LABELS[job.sourceType] || "未知来源";
    const reportText = job.reportType || "待确认/未知";
    const deliverableText = job.deliverableId ? ` | 交付物: ${job.deliverableId}` : "";
    meta.textContent = `${sourceText} / ${reportText}${deliverableText}`;

    const metrics = archiveEl("div", "archive-job-metrics");
    const enabledChip = archiveEl("span", "archive-chip", job.enabled ? "已启用" : "已禁用");
    if (job.enabled) enabledChip.classList.add("is-fresh");
    else enabledChip.classList.add("is-unknown");

    const credChip = archiveEl("span", "archive-chip", job.credentialConfigured ? "凭据已配" : "凭据未配");
    if (job.credentialConfigured) credChip.classList.add("is-fresh");
    else credChip.classList.add("is-needs-attention");

    metrics.appendChild(enabledChip);
    metrics.appendChild(credChip);
    metrics.appendChild(archiveSyncStateChip(job.syncState));

    item.appendChild(head);
    item.appendChild(meta);
    item.appendChild(metrics);

    item.addEventListener("click", () => {
      if (selectedArchiveJobKey === job.jobKey) return;
      selectedArchiveJobKey = job.jobKey;
      renderArchiveJobsList(true);
    });

    container.appendChild(item);
  });

  renderArchiveConfigCard(selectedJob);
  loadArchiveHistory();
}

function renderArchiveConfigCard(job) {
  const card = document.getElementById("archive-config-card");
  if (!card) return;
  clearArchiveContainer(card);

  if (!job) {
    card.classList.add("is-empty");
    card.appendChild(archiveEl("p", "loading", "请选择归档任务"));
    return;
  }
  card.classList.remove("is-empty");

  const head = archiveEl("div", "archive-config-head");
  const titleGroup = archiveEl("div");
  const eyebrow = archiveEl("p", "eyebrow", job.jobKey);
  const title = archiveEl("h4", null, ARCHIVE_JOB_NAMES[job.jobKey] || job.jobKey);
  titleGroup.appendChild(eyebrow);
  titleGroup.appendChild(title);

  const chips = archiveEl("div", "chip-row");
  chips.appendChild(archiveFreshnessChip(job.freshness));
  chips.appendChild(archiveSyncStateChip(job.syncState));
  head.appendChild(titleGroup);
  head.appendChild(chips);
  card.appendChild(head);

  // Status Banner
  const banner = archiveEl("div", "archive-status-banner");
  const addCell = (label, value) => {
    const cell = archiveEl("div", "archive-status-cell");
    const l = archiveEl("span", "archive-cell-label", label);
    const v = archiveEl("span", "archive-cell-value", value);
    cell.appendChild(l);
    cell.appendChild(v);
    banner.appendChild(cell);
  };
  let syncStateText = "待确认/未知";
  if (job.syncState === "needs_attention") {
    syncStateText = "需关注";
  } else if (job.syncState === "success") {
    syncStateText = "正常";
  } else if (job.syncState === "idle") {
    syncStateText = "空闲";
  } else if (job.syncState === "running") {
    syncStateText = "同步中";
  } else if (job.syncState === "failed") {
    syncStateText = "失败";
  }
  addCell("同步状态", syncStateText);
  const intervalText = (Number.isInteger(job.intervalMinutes) && job.intervalMinutes > 0)
    ? `${job.intervalMinutes} 分钟`
    : "待确认/未知";
  addCell("调度周期", intervalText);
  addCell("最近成功", archiveFormatDate(job.lastSuccessAt));
  addCell("最近尝试", archiveFormatDate(job.lastAttemptAt));
  const retrySummary = (job.retryPolicy && Number.isInteger(job.retryPolicy.max_attempts)
    && job.retryPolicy.max_attempts > 0)
    ? `最大 ${job.retryPolicy.max_attempts} 次`
    : "待确认/未知";
  addCell("重试策略", retrySummary);

  if (job.lastErrorMessage) {
    addCell("最近安全错误", `${job.lastErrorType || "未知类型"}: ${job.lastErrorMessage}`);
  }
  card.appendChild(banner);

  // Form Container
  const form = document.createElement("form");
  form.className = "archive-config-form";
  form.autocomplete = "off";

  const formBlock = archiveEl("div", "archive-form-block");
  const formGrid = archiveEl("div", "form-grid");

  // 1. Enabled Checkbox
  const enabledLabel = archiveEl("label", "archive-checkbox-row wide");
  const enabledInput = document.createElement("input");
  enabledInput.type = "checkbox";
  enabledInput.name = "enabled";
  enabledInput.checked = Boolean(job.enabled);
  enabledInput.id = "archive-field-enabled";
  const enabledSpan = archiveEl("span", null, "启用定时归档任务");
  enabledLabel.appendChild(enabledInput);
  enabledLabel.appendChild(enabledSpan);
  formGrid.appendChild(enabledLabel);

  // 2. Credential Alias Input (Write-only, NEVER PREFILLED)
  const aliasLabel = archiveEl("label", null);
  const aliasSpan = archiveEl("span", null, "凭据引用别名 (只写)");
  const aliasInput = document.createElement("input");
  aliasInput.type = "password";
  aliasInput.name = "credentialRef";
  aliasInput.id = "archive-field-credential-ref";
  aliasInput.placeholder = job.credentialConfigured ? "已配置凭据（若无需修改请留空）" : "请输入凭据别名（启用前必填）";
  aliasInput.autocomplete = "new-password";
  aliasLabel.appendChild(aliasSpan);
  aliasLabel.appendChild(aliasInput);
  formGrid.appendChild(aliasLabel);

  // 3. Clear Alias Option Checkbox
  const clearAliasLabel = archiveEl("label", "archive-checkbox-row");
  const clearAliasInput = document.createElement("input");
  clearAliasInput.type = "checkbox";
  clearAliasInput.name = "clearAlias";
  clearAliasInput.id = "archive-field-clear-alias";
  const clearAliasSpan = archiveEl("span", null, "清除已配置的凭据别名");
  clearAliasLabel.appendChild(clearAliasInput);
  clearAliasLabel.appendChild(clearAliasSpan);
  formGrid.appendChild(clearAliasLabel);

  // 4. Output Subdirectory Input
  const outputSubdirLabel = archiveEl("label", "wide");
  const outputSubdirSpan = archiveEl("span", null, "输出子目录 (基于安全归档根目录的相对路径)");
  const outputSubdirInput = document.createElement("input");
  outputSubdirInput.type = "text";
  outputSubdirInput.name = "outputSubdir";
  outputSubdirInput.id = "archive-field-output-subdir";
  outputSubdirInput.value = job.outputSubdir || "";
  outputSubdirInput.placeholder = "例如 aras/ewo 或留空使用默认";
  outputSubdirLabel.appendChild(outputSubdirSpan);
  outputSubdirLabel.appendChild(outputSubdirInput);
  formGrid.appendChild(outputSubdirLabel);

  // 5. Allowed Filter Names Info
  const allowedFilters = Array.isArray(job.allowedFilterNames) ? job.allowedFilterNames : [];
  const filtersInfoLabel = archiveEl("div", "wide");
  const filtersInfoSpan = archiveEl("span", null, "支持的筛选键名 (Allowed Filters)");
  const filtersTagContainer = archiveEl("div", "archive-filter-tags");
  if (allowedFilters.length > 0) {
    allowedFilters.forEach((name) => {
      filtersTagContainer.appendChild(archiveEl("span", "archive-filter-tag", name));
    });
  } else {
    filtersTagContainer.appendChild(archiveEl("span", "archive-filter-tag", "无"));
  }
  filtersInfoLabel.appendChild(filtersInfoSpan);
  filtersInfoLabel.appendChild(filtersTagContainer);
  formGrid.appendChild(filtersInfoLabel);

  // 6. JSON Filters Textarea
  const filtersLabel = archiveEl("label", "wide");
  const filtersSpan = archiveEl("span", null, "筛选配置 (JSON 对象)");
  const filtersTextarea = document.createElement("textarea");
  filtersTextarea.name = "filters";
  filtersTextarea.id = "archive-field-filters";
  filtersTextarea.rows = 4;
  filtersTextarea.value = JSON.stringify(job.filters || {}, null, 2);
  filtersLabel.appendChild(filtersSpan);
  filtersLabel.appendChild(filtersTextarea);
  formGrid.appendChild(filtersLabel);

  formBlock.appendChild(formGrid);
  form.appendChild(formBlock);

  // Field Errors Container
  const fieldErrorsDiv = archiveEl("div", "error-msg");
  fieldErrorsDiv.id = "archive-form-errors";
  fieldErrorsDiv.hidden = true;
  form.appendChild(fieldErrorsDiv);

  // Action Buttons Row
  const actionsRow = archiveEl("div", "archive-actions-row");
  const saveBtn = archiveEl("button", "primary-btn", "保存配置");
  saveBtn.type = "submit";
  saveBtn.id = "archive-save-btn";

  const syncNowBtn = archiveEl("button", "archive-btn-secondary", "立即同步 (Sync Now)");
  syncNowBtn.type = "button";
  syncNowBtn.id = "archive-sync-now-btn";
  syncNowBtn.disabled = !job.enabled || !job.credentialConfigured;

  const formStatus = archiveEl("span", "archive-status-msg");
  formStatus.id = "archive-form-status";
  formStatus.setAttribute("aria-live", "polite");

  actionsRow.appendChild(saveBtn);
  actionsRow.appendChild(syncNowBtn);
  actionsRow.appendChild(formStatus);
  form.appendChild(actionsRow);

  card.appendChild(form);

  // Event Listeners
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    await handleArchiveSave(job);
  });

  syncNowBtn.addEventListener("click", async () => {
    await handleArchiveSyncNow(job);
  });
}

function showArchiveFieldErrors(errors) {
  const el = document.getElementById("archive-form-errors");
  if (!el) return;
  clearArchiveContainer(el);
  if (!errors || Object.keys(errors).length === 0) {
    el.hidden = true;
    return;
  }
  el.hidden = false;
  const list = document.createElement("ul");
  list.style.margin = "0";
  list.style.paddingLeft = "18px";
  Object.entries(errors).forEach(([field, msg]) => {
    const li = document.createElement("li");
    li.textContent = `${field}: ${msg}`;
    list.appendChild(li);
  });
  el.appendChild(list);
}

async function handleArchiveSave(job) {
  if (archiveMutating) return;
  showArchiveFieldErrors(null);
  const formStatus = document.getElementById("archive-form-status");
  const saveBtn = document.getElementById("archive-save-btn");
  const syncNowBtn = document.getElementById("archive-sync-now-btn");
  const enabledInput = document.getElementById("archive-field-enabled");
  const aliasInput = document.getElementById("archive-field-credential-ref");
  const clearAliasInput = document.getElementById("archive-field-clear-alias");
  const outputSubdirInput = document.getElementById("archive-field-output-subdir");
  const filtersTextarea = document.getElementById("archive-field-filters");

  const enabled = Boolean(enabledInput && enabledInput.checked);
  const aliasVal = (aliasInput && aliasInput.value.trim()) || "";
  const clearAlias = Boolean(clearAliasInput && clearAliasInput.checked);
  const outputSubdir = (outputSubdirInput && outputSubdirInput.value.trim()) || "";
  const filtersRaw = (filtersTextarea && filtersTextarea.value.trim()) || "{}";

  // Client Validation 1: Prevent enabled + clear-alias
  if (enabled && clearAlias) {
    showArchiveFieldErrors({ enabled: "不能在启用任务的同时勾选清除凭据别名", clearAlias: "清除凭据别名时任务必须为停用状态" });
    return;
  }

  // Client Validation 2: Validate JSON filters is non-array object
  let parsedFilters = null;
  try {
    parsedFilters = JSON.parse(filtersRaw);
    if (!parsedFilters || typeof parsedFilters !== "object" || Array.isArray(parsedFilters)) {
      showArchiveFieldErrors({ filters: "筛选配置必须是一个 JSON 对象（不能是数组或基础类型）" });
      return;
    }
  } catch (jsonErr) {
    showArchiveFieldErrors({ filters: "JSON 格式解析失败，请检查输入语法" });
    return;
  }

  // Build Payload
  const payload = {
    enabled,
    filters: parsedFilters,
    outputSubdir,
    updatedAt: job.updatedAt,
  };

  if (clearAlias) {
    payload.credentialRef = null;
  } else if (aliasVal) {
    payload.credentialRef = aliasVal;
  }

  archiveMutating = true;
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = "保存中...";
  }
  if (syncNowBtn) syncNowBtn.disabled = true;
  if (formStatus) formStatus.textContent = "正在提交修改...";

  try {
    const resp = await fetch(`/api/scheduled-archive/jobs/${encodeURIComponent(job.jobKey)}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(payload),
    });
    const body = await resp.json();
    if (!resp.ok || !body.ok) {
      if (resp.status === 422 && body.error && body.error.fields) {
        showArchiveFieldErrors(body.error.fields);
      } else {
        const msg = (body.error && body.error.message) || "保存配置失败";
        showArchiveFieldErrors({ error: msg });
      }
      if (formStatus) formStatus.textContent = "保存失败";
      return;
    }
    if (formStatus) formStatus.textContent = "配置已保存";
    await loadArchiveJobs(true);
  } catch (_e) {
    showArchiveFieldErrors({ network: "保存请求失败，网络异常或服务器未响应" });
    if (formStatus) formStatus.textContent = "保存失败";
  } finally {
    // Clear write-only alias input in finally
    if (aliasInput) aliasInput.value = "";
    if (clearAliasInput) clearAliasInput.checked = false;
    archiveMutating = false;
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = "保存配置";
    }
    if (syncNowBtn) {
      syncNowBtn.disabled = !job.enabled || !job.credentialConfigured;
    }
  }
}

async function handleArchiveSyncNow(job) {
  if (archiveMutating) return;
  const formStatus = document.getElementById("archive-form-status");
  const saveBtn = document.getElementById("archive-save-btn");
  const syncNowBtn = document.getElementById("archive-sync-now-btn");

  archiveMutating = true;
  if (saveBtn) saveBtn.disabled = true;
  if (syncNowBtn) {
    syncNowBtn.disabled = true;
    syncNowBtn.textContent = "同步执行中...";
  }
  if (formStatus) formStatus.textContent = "正在发起立即同步...";

  try {
    const resp = await fetch(`/api/scheduled-archive/jobs/${encodeURIComponent(job.jobKey)}/sync-now`, {
      method: "POST",
      headers: {
        Accept: "application/json",
      },
    });
    const body = await resp.json();
    if (!resp.ok || !body.ok) {
      const msg = (body.error && body.error.message) || "立即同步失败";
      if (formStatus) formStatus.textContent = `同步失败: ${msg}`;
      return;
    }
    if (formStatus) formStatus.textContent = "立即同步已完成，正在更新状态与历史...";
    await loadArchiveJobs(true);
  } catch (_e) {
    if (formStatus) formStatus.textContent = "同步请求失败，网络异常";
  } finally {
    archiveMutating = false;
    if (saveBtn) saveBtn.disabled = false;
    if (syncNowBtn) {
      syncNowBtn.disabled = !job.enabled || !job.credentialConfigured;
      syncNowBtn.textContent = "立即同步 (Sync Now)";
    }
  }
}

async function loadArchiveHistory() {
  if (archiveHistoryTab === "runs") {
    await loadArchiveRuns();
  } else {
    await loadArchiveAudit();
  }
}

async function loadArchiveRuns() {
  const container = document.getElementById("archive-runs-list");
  if (!container) return;
  clearArchiveContainer(container);
  container.appendChild(archiveEl("p", "loading", "加载运行历史中..."));

  const artifactsView = document.getElementById("archive-artifacts-view");
  if (artifactsView) artifactsView.hidden = true;
  archiveSelectedRunId = null;

  const url = selectedArchiveJobKey
    ? `/api/scheduled-archive/runs?jobKey=${encodeURIComponent(selectedArchiveJobKey)}&limit=50`
    : "/api/scheduled-archive/runs?limit=50";

  try {
    const resp = await fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" });
    const body = await resp.json();
    if (!resp.ok || !body.ok) {
      clearArchiveContainer(container);
      container.appendChild(archiveEl("p", "is-empty", (body.error && body.error.message) || "加载历史失败"));
      return;
    }
    const runs = Array.isArray(body.data) ? body.data : [];
    renderArchiveRunsList(runs);
  } catch (_e) {
    clearArchiveContainer(container);
    container.appendChild(archiveEl("p", "is-empty", "加载历史失败"));
  }
}

function renderArchiveRunsList(runs) {
  const container = document.getElementById("archive-runs-list");
  if (!container) return;
  clearArchiveContainer(container);

  if (runs.length === 0) {
    container.appendChild(archiveEl("p", "is-empty", "暂无运行记录"));
    return;
  }

  runs.forEach((run) => {
    const card = archiveEl("div", "archive-run-card");
    const head = archiveEl("div", "archive-run-head");
    const headLeft = archiveEl("div");
    const runTitle = archiveEl("strong", null, `#${run.id} - ${ARCHIVE_JOB_NAMES[run.jobKey] || run.jobKey}`);
    headLeft.appendChild(runTitle);

    const stateChip = archiveRunStateChip(run.runState);
    head.appendChild(headLeft);
    head.appendChild(stateChip);

    const meta = archiveEl("div", "archive-run-meta");
    const trigger = run.triggerType === "sync_now"
      ? "手动立即同步"
      : run.triggerType === "scheduled" ? "定时调度" : "待确认/未知";
    const records = typeof run.recordCount === "number" ? `${run.recordCount} 条记录` : "";
    meta.textContent = `${trigger} | 开始: ${archiveFormatDate(run.startedAt || run.createdAt)} | 完成: ${archiveFormatDate(run.finishedAt)} ${records ? `| ${records}` : ""}`;

    card.appendChild(head);
    card.appendChild(meta);

    if (run.resultSummary) {
      const summary = archiveEl("div", "archive-run-summary", `摘要: ${run.resultSummary}`);
      card.appendChild(summary);
    }
    if (run.errorMessage) {
      const err = archiveEl("div", "archive-run-summary", `错误 (${run.errorType || "未知类型"}): ${run.errorMessage}`);
      err.style.color = "var(--error)";
      card.appendChild(err);
    }

    // Artifacts expansion button
    const artBtn = archiveEl("button", "archive-btn-secondary", "查看产物");
    artBtn.type = "button";
    artBtn.style.marginTop = "8px";
    artBtn.addEventListener("click", () => {
      loadArchiveArtifacts(run.id);
    });
    card.appendChild(artBtn);

    container.appendChild(card);
  });
}

async function loadArchiveArtifacts(runId) {
  archiveSelectedRunId = runId;
  const view = document.getElementById("archive-artifacts-view");
  const listContainer = document.getElementById("archive-artifacts-list");
  if (!view || !listContainer) return;
  view.hidden = false;
  clearArchiveContainer(listContainer);
  listContainer.appendChild(archiveEl("p", "loading", `加载 Run #${runId} 产物...`));

  try {
    const resp = await fetch(`/api/scheduled-archive/runs/${encodeURIComponent(runId)}/artifacts`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const body = await resp.json();
    if (!resp.ok || !body.ok) {
      clearArchiveContainer(listContainer);
      listContainer.appendChild(archiveEl("p", "is-empty", (body.error && body.error.message) || "产物加载失败"));
      return;
    }
    const data = body.data || {};
    const artifacts = Array.isArray(data.artifacts) ? data.artifacts : [];
    renderArchiveArtifactsList(artifacts);
  } catch (_e) {
    clearArchiveContainer(listContainer);
    listContainer.appendChild(archiveEl("p", "is-empty", "产物加载失败"));
  }
}

function renderArchiveArtifactsList(artifacts) {
  const container = document.getElementById("archive-artifacts-list");
  if (!container) return;
  clearArchiveContainer(container);

  if (artifacts.length === 0) {
    container.appendChild(archiveEl("p", "is-empty", "本次运行未产生落盘产物"));
    return;
  }

  const table = document.createElement("table");
  table.className = "archive-artifacts-table";

  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  ["类型", "显示名称", "大小", "SHA-256", "相对路径", "生成时间"].forEach((colName) => {
    const th = document.createElement("th");
    th.textContent = colName;
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  artifacts.forEach((art) => {
    const tr = document.createElement("tr");

    const tdType = document.createElement("td");
    tdType.textContent = art.artifactType || "未知";

    const tdName = document.createElement("td");
    tdName.textContent = art.displayName || "-";

    const tdSize = document.createElement("td");
    tdSize.textContent = typeof art.sizeBytes === "number" ? `${art.sizeBytes} B` : "-";

    const tdHash = document.createElement("td");
    tdHash.textContent = art.sha256 ? String(art.sha256).slice(0, 12) + "..." : "-";
    if (art.sha256) tdHash.title = art.sha256;

    // Relative path only - strictly no download link, plain textContent
    const tdPath = document.createElement("td");
    tdPath.textContent = art.relativePath || "-";

    const tdTime = document.createElement("td");
    tdTime.textContent = archiveFormatDate(art.createdAt);

    tr.appendChild(tdType);
    tr.appendChild(tdName);
    tr.appendChild(tdSize);
    tr.appendChild(tdHash);
    tr.appendChild(tdPath);
    tr.appendChild(tdTime);

    tbody.appendChild(tr);
  });
  table.appendChild(tbody);

  container.appendChild(table);
}

async function loadArchiveAudit() {
  const container = document.getElementById("archive-audit-list");
  if (!container) return;
  clearArchiveContainer(container);
  container.appendChild(archiveEl("p", "loading", "加载配置审计中..."));

  const url = selectedArchiveJobKey
    ? `/api/scheduled-archive/config-audit?jobKey=${encodeURIComponent(selectedArchiveJobKey)}&limit=50`
    : "/api/scheduled-archive/config-audit?limit=50";

  try {
    const resp = await fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" });
    const body = await resp.json();
    if (!resp.ok || !body.ok) {
      clearArchiveContainer(container);
      container.appendChild(archiveEl("p", "is-empty", (body.error && body.error.message) || "加载审计失败"));
      return;
    }
    const auditRecords = Array.isArray(body.data) ? body.data : [];
    renderArchiveAuditList(auditRecords);
  } catch (_e) {
    clearArchiveContainer(container);
    container.appendChild(archiveEl("p", "is-empty", "加载审计失败"));
  }
}

function renderArchiveAuditList(auditRecords) {
  const container = document.getElementById("archive-audit-list");
  if (!container) return;
  clearArchiveContainer(container);

  if (auditRecords.length === 0) {
    container.appendChild(archiveEl("p", "is-empty", "暂无配置变更记录"));
    return;
  }

  auditRecords.forEach((record) => {
    const card = archiveEl("div", "archive-audit-card");
    const head = archiveEl("div", "archive-audit-head");
    const title = archiveEl("strong", null, `${ARCHIVE_JOB_NAMES[record.jobKey] || record.jobKey} - ${record.eventType || "待确认/未知"}`);
    const actor = archiveEl("span", "archive-audit-meta", `操作者: ${record.actor || "待确认/未知"}`);
    head.appendChild(title);
    head.appendChild(actor);

    const meta = archiveEl("div", "archive-audit-meta", `时间: ${archiveFormatDate(record.createdAt)}`);

    card.appendChild(head);
    card.appendChild(meta);

    if (record.changes && typeof record.changes === "object") {
      const pre = document.createElement("pre");
      pre.style.margin = "6px 0 0";
      pre.style.padding = "8px";
      pre.style.background = "var(--surface-soft)";
      pre.style.borderRadius = "4px";
      pre.style.fontSize = "11px";
      pre.style.fontFamily = "var(--font-mono)";
      pre.style.overflowX = "auto";
      pre.textContent = JSON.stringify(record.changes, null, 2);
      card.appendChild(pre);
    }

    container.appendChild(card);
  });
}

function setupArchiveAdmin() {
  const refreshBtn = document.getElementById("archive-refresh-btn");
  if (refreshBtn) refreshBtn.addEventListener("click", () => loadArchiveJobs(true));

  const refreshRunsBtn = document.getElementById("archive-refresh-runs-btn");
  if (refreshRunsBtn) refreshRunsBtn.addEventListener("click", () => loadArchiveRuns());

  const refreshAuditBtn = document.getElementById("archive-refresh-audit-btn");
  if (refreshAuditBtn) refreshAuditBtn.addEventListener("click", () => loadArchiveAudit());

  const closeArtifactsBtn = document.getElementById("archive-close-artifacts-btn");
  if (closeArtifactsBtn) {
    closeArtifactsBtn.addEventListener("click", () => {
      const view = document.getElementById("archive-artifacts-view");
      if (view) view.hidden = true;
      archiveSelectedRunId = null;
    });
  }

  const tabRuns = document.getElementById("archive-tab-runs");
  const tabAudit = document.getElementById("archive-tab-audit");
  const panelRuns = document.getElementById("archive-runs-panel");
  const panelAudit = document.getElementById("archive-audit-panel");

  if (tabRuns && tabAudit && panelRuns && panelAudit) {
    tabRuns.addEventListener("click", () => {
      archiveHistoryTab = "runs";
      tabRuns.classList.add("active");
      tabRuns.setAttribute("aria-pressed", "true");
      tabAudit.classList.remove("active");
      tabAudit.setAttribute("aria-pressed", "false");
      panelRuns.hidden = false;
      panelAudit.hidden = true;
      loadArchiveRuns();
    });

    tabAudit.addEventListener("click", () => {
      archiveHistoryTab = "audit";
      tabAudit.classList.add("active");
      tabAudit.setAttribute("aria-pressed", "true");
      tabRuns.classList.remove("active");
      tabRuns.setAttribute("aria-pressed", "false");
      panelAudit.hidden = false;
      panelRuns.hidden = true;
      loadArchiveAudit();
    });
  }
}

function updateArasActionButtons() {
  const config = ARAS_MODES[arasMode];
  document.getElementById("aras-submit").textContent = config.submitLabel || "执行查询";
  const exportButton = document.getElementById("aras-export");
  const downloadButton = document.getElementById("aras-download");
  exportButton.hidden = !config.exportEndpoint;
  downloadButton.hidden = !config.downloadEndpoint;
  if (config.exportEndpoint) exportButton.textContent = config.exportLabel || "全量导出 CSV";
  if (config.downloadEndpoint) downloadButton.textContent = config.exportLabel || "生成并下载";
}

function setupArasForm() {
  document.body.dataset.currentCommand = arasMode;
  updateArasActionButtons();
  document.querySelectorAll("[data-aras-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      arasMode = button.dataset.arasMode;
      document.body.dataset.currentCommand = arasMode;
      document.getElementById("command-label").textContent = COMMAND_LABELS[arasMode] || arasMode;
      document.querySelectorAll("[data-aras-mode]").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      document.querySelectorAll("[data-mode-fields]").forEach((group) => {
        group.hidden = group.dataset.modeFields !== ARAS_MODES[arasMode].fieldGroup;
      });
      updateArasActionButtons();
      showArasError("");
      showArasWarning("");
      const result = document.getElementById("aras-result");
      result.className = "is-empty";
      result.textContent = "暂无结果";
      document.getElementById("result-kind").textContent = "就绪";
      document.querySelector(".result-panel")?.classList.remove("has-output");
    });
  });
  document.getElementById("aras-form").addEventListener("submit", (event) => {
    event.preventDefault();
    runArasQuery();
  });
  document.getElementById("aras-export").addEventListener("click", () => {
    if (!ARAS_MODES[arasMode].exportEndpoint) return;
    runArasExport();
  });
  document.getElementById("aras-download").addEventListener("click", () => {
    if (!ARAS_MODES[arasMode].downloadEndpoint) return;
    runArasExport();
  });
}

function setupArasAuthentication() {
  const selector = document.getElementById("aras-auth-mode");
  const note = document.getElementById("aras-auth-note");
  const sync = () => {
    const mode = selector.value === "browser" ? "browser" : "password";
    document.querySelectorAll("[data-auth-fields]").forEach((group) => {
      group.hidden = group.dataset.authFields !== mode;
    });
    note.textContent = mode === "password"
      ? "密码仅用于本次请求，由后端完成企业账号登录和 SOAP ValidateUser 校验，不会持久化。"
      : "使用已认证的 ECM Cookie/Authorization；普通 SSO 登录成功不等于 SOAP 已授权。";
  };
  selector.addEventListener("change", sync);
  sync();
}

document.addEventListener("DOMContentLoaded", () => {
  applyTheme(preferredTheme());
  setupTheme();
  setupOverviewTabs();
  setupOverviewGuards();
  loadProjectOverview();
  setupPanels();
  setupArasAuthentication();
  setupArasForm();
  setupDeliverables();
  setupArchiveAdmin();
});
