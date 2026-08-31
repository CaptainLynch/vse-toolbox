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
    xmlCapture: true,
  },
  paa: {
    endpoint: "/api/aras/paa/query",
    crawlAllEndpoint: "/api/aras/paa/crawl-all",
    exportEndpoint: "/api/aras/paa/export",
    exportNumberNames: ["max_records", "max_pages"],
    exportLabel: "全量导出 CSV",
    crawlAllLabel: "获取全部结果",
    defaultFileName: "aras-paa-export.csv",
    submitLabel: "查询预览",
    fieldGroup: "paa",
    filterNames: ["paa_no", "ewo_no", "state", "area", "base", "department", "vehicle_keyword", "submit_start", "submit_end", "mtl_rq_start", "mtl_rq_end"],
    numberNames: ["page", "page_size", "max_records", "max_pages"],
    preferredColumns: [],
    resultKind: "rows",
    xmlCapture: true,
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
    resultKind: "rows",
    preview: true,
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
    resultKind: "rows",
    preview: true,
  },
};

let arasMode = "ewo";
let arasRunning = false;
let arasQueuedAction = "";
let arasRequestSeq = 0;
let arasLatestRendered = 0;
let arasXmlCapture = null;

const COMMAND_LABELS = {
  ewo: "EWO",
  paa: "PAA",
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


const LEGACY_MILESTONE_TYPES = {
  done: "已达成",
  current: "当前目标节点",
  planned: "计划节点",
};
const MILESTONE_VALIDATION_RULES = {
  singleCurrent: "必须且只能存在一个当前目标节点",
  doneDateFuture: "已达成节点日期不能晚于当前日期",
  plannedDatePast: "计划节点日期不能早于当前日期",
};

const MILESTONE_STATUS_OPTIONS = ["未开始", "进行中", "已完成", "已超期"];

const MILESTONE_TYPE_OPTIONS = [
  { value: "planned", label: "未开始" },
  { value: "current", label: "进行中" },
  { value: "done", label: "已完成" },
  { value: "overdue", label: "已超期" },
];

const MILESTONE_LABEL_BY_TYPE = {
  planned: "未开始",
  current: "进行中",
  done: "已完成",
  overdue: "已超期",
  "未开始": "未开始",
  "进行中": "进行中",
  "已完成": "已完成",
  "已超期": "已超期",
};

const MILESTONE_TYPE_BY_STATUS = {
  "未开始": "planned",
  "进行中": "current",
  "已完成": "done",
  "已超期": "planned",
};

let overviewSavedState = null;
let overviewArchiveJobs = [];
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
  err.code = error && typeof error.code === "string" ? error.code : "";
  err.type = error && typeof error.type === "string" ? error.type : "";
  err.diagnosticPath = error && typeof error.diagnosticPath === "string"
    ? error.diagnosticPath
    : "";
  err.errorCode = err.code;
  err.errorType = err.type;
  err.errorMessage = error && typeof error.message === "string" ? error.message : "";
  return err;
}

const INTERACTIVE_QUERY_ERROR_LABELS = {
  unauthenticated: {
    label: "未认证",
    detail: "请先在设置中完成统一域账号登录。",
    tone: "warning",
  },
  service_unavailable: {
    label: "服务不可用",
    detail: "ARAS 当前不可用，请检查网络或 VPN 后重试。",
    tone: "error",
  },
  query_failed: {
    label: "查询失败",
    detail: "ARAS 查询未完成，请稍后重试。",
    tone: "error",
  },
};

function interactiveQueryErrorCode(error, fallbackStatus) {
  const explicit = error && typeof (error.code || error.errorCode) === "string"
    ? (error.code || error.errorCode)
    : "";
  if (INTERACTIVE_QUERY_ERROR_LABELS[explicit]) return explicit;
  const status = Number(error && error.status !== undefined ? error.status : fallbackStatus);
  if (status === 401 || status === 403) return "unauthenticated";
  if (status === 0 || !Number.isFinite(status) || status >= 500) return "service_unavailable";
  return "query_failed";
}

function formatInteractiveArasError(error, fallbackStatus = 0) {
  const code = interactiveQueryErrorCode(error, fallbackStatus);
  const descriptor = INTERACTIVE_QUERY_ERROR_LABELS[code] || INTERACTIVE_QUERY_ERROR_LABELS.query_failed;
  return `${descriptor.label}：${descriptor.detail}`;
}

function formatInteractiveQueryError(error, fallbackStatus = 0) {
  return formatInteractiveArasError(error, fallbackStatus);
}

function interactiveFilterValue(value) {
  if (typeof value !== "string" && typeof value !== "number") return "";
  const text = String(value).trim();
  return text ? text.slice(0, 1000) : "";
}

function buildInteractiveArasPayload(mode, filters = {}) {
  const config = ARAS_MODES[mode];
  if (!config || !["ewo", "paa"].includes(mode)) {
    throw new Error("unsupported interactive ARAS mode");
  }
  const allowed = new Set(Array.isArray(config.filterNames) ? config.filterNames : []);
  const safeFilters = {};
  if (filters && typeof filters === "object" && !Array.isArray(filters)) {
    Object.entries(filters).forEach(([name, value]) => {
      if (!allowed.has(name)) return;
      const clean = interactiveFilterValue(value);
      if (clean) safeFilters[name] = clean;
    });
  }
  return {
    base_url: EWO_POLICY_DEFAULT_ARAS_BASE_URL,
    auth_mode: "browser",
    filters: safeFilters,
    page: 1,
    page_size: 50,
    max_records: 2000,
  };
}

async function requestInteractiveArasQuery(mode, filters = {}) {
  const config = ARAS_MODES[mode];
  if (!config || !["ewo", "paa"].includes(mode)) {
    throw new Error("unsupported interactive ARAS mode");
  }
  const response = await fetch(config.endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(buildInteractiveArasPayload(mode, filters)),
  });
  const body = await overviewReadJson(response);
  if (!response.ok || !body || body.ok !== true) {
    throw overviewRequestError(body, response.status);
  }
  return body.data || {};
}

function interactiveQueryResultState(mode, data, targetKey = "") {
  const rows = data && Array.isArray(data.rows) ? data.rows : [];
  if (!rows.length || (data && data.queryState === "empty")) return "empty";
  const target = interactiveFilterValue(targetKey);
  if (!target) return "matched";
  const identityFields = mode === "ewo"
    ? ["_no", "ewoNo", "ewo_no", "id", "formId"]
    : ["_no", "paaNo", "paa_no", "ewoNo", "ewo_no", "id", "formId"];
  const found = rows.some((row) => row && identityFields.some(
    (field) => interactiveFilterValue(row[field]) === target,
  ));
  return found ? "matched" : "no_match";
}

function formatInteractiveArasResult(data, expectedExternalKey = "") {
  const state = interactiveQueryResultState("", data, expectedExternalKey);
  const descriptors = {
    matched: { text: "已匹配", tone: "success" },
    empty: { text: "数据为空", tone: "warning" },
    no_match: { text: "未匹配", tone: "warning" },
  };
  return { state, ...(descriptors[state] || descriptors.empty) };
}

function renderInteractiveArasResult(container, mode, data, targetKey = "") {
  if (!container) return null;
  clearOverviewContainer(container);
  const config = ARAS_MODES[mode] || {};
  const resultState = formatInteractiveArasResult(data, targetKey);
  const state = resultState.state;
  const panel = overviewEl("section", "interactive-query-result");
  panel.dataset.queryMode = mode;
  panel.append(
    overviewEl("strong", "interactive-query-title", `交互式查询 · ${COMMAND_LABELS[mode] || mode}`),
    overviewEl("span", `interactive-query-state is-${resultState.tone}`, resultState.text),
  );
  const rows = data && Array.isArray(data.rows) ? data.rows : [];
  const count = data && data.count !== undefined ? Number(data.count) || rows.length : rows.length;
  panel.appendChild(overviewEl(
    "p",
    "interactive-query-meta",
    `返回 ${count} 条 · 第 ${Number(data && data.page) || 1} 页`,
  ));
  panel.appendChild(overviewEl(
    "p",
    "interactive-query-notice",
    "本次结果未写入后台同步状态",
  ));
  if (state === "empty" || state === "no_match") {
    panel.appendChild(overviewEl(
      "p",
      "interactive-query-state-detail",
      resultState.text,
    ));
  }
  if (config.resultKind === "rows") {
    panel.appendChild(renderRows(data || {}, config.preferredColumns || [], mode));
  }
  container.appendChild(panel);
  return panel;
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
  headCopy.append(
    overviewEl("p", "eyebrow", "项目名称"),
    overviewEl("h4", null, phase.displayName || `${phase.id} 主计划时间轴`),
  );
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

function renderPhaseSummary(container, phase, currentStage = null) {
  clearOverviewContainer(container);
  const head = overviewEl("div", "band-head");
  const headCopy = overviewEl("div");
  headCopy.append(overviewEl("p", "eyebrow", "阶段概况"), overviewEl("h4", null, phase.displayName || phase.id));
  head.appendChild(headCopy);
  const headActions = overviewEl("div", "timeline-head-actions");
  const editButton = overviewEl("button", "timeline-edit-btn", null);
  editButton.type = "button";
  editButton.title = "编辑主计划";
  editButton.setAttribute("aria-label", "编辑主计划");
  editButton.append(overviewPencilIcon(), overviewEl("span", null, "编辑主计划"));
  editButton.addEventListener("click", openMilestoneEditor);
  headActions.appendChild(editButton);
  head.appendChild(headActions);
  container.appendChild(head);

  const stageLabel = currentStage || (phase && phase.currentStage) || "项目开始 → 项目结束";
  const grid = overviewEl("div", "phase-summary-grid");
  const cells = [
    ["当前阶段", stageLabel],
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
  if (item.status === "success") return "success";
  if (item.status === "needs_attention") return "warning";
  if (item.status === "failed") return "error";
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
    overviewEl("span", "policy-source", "权威来源 · TDC 数模审核报表"),
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

const EWO_POLICY_MODE_LABELS = {
  manual: "手动维护",
  automatic: "自动同步",
  hybrid: "混合模式",
};
const EWO_POLICY_RECOMMENDED_MODE = "automatic";
const EWO_POLICY_DEFAULT_ARAS_BASE_URL = "http://ecm.sgmw.com.cn/innovatorserver";
const EWO_POLICY_MATCH_FIELDS = [
  ["ewoNo", "EWO 编号", "ewo_no"],
  ["projectCode", "项目代码", "project_code"],
  ["subjectKeyword", "主题关键词", "subject_keyword"],
  ["modelInfo", "车型信息", "model_info"],
];
const EWO_POLICY_AUTOMATIC_FIELDS = [
  ["owner", "负责人"],
  ["plannedDate", "计划完成日期"],
  ["note", "风险与备注"],
];

// 就绪信号只有两个：既有 policy API 的 enabled === true，且 mapping 完整
// （非空对象且每个值都是非空字段名）。两者缺一显示 未启用，不得声称已同步。
function deliverablePolicyMappingReady(policy) {
  if (!policy || policy.enabled !== true) return false;
  const mapping = policy.mapping;
  if (!mapping || typeof mapping !== "object" || Array.isArray(mapping)) return false;
  const keys = Object.keys(mapping);
  if (keys.length === 0) return false;
  return keys.every((key) => {
    const value = mapping[key];
    return typeof value === "string" && value.trim().length > 0;
  });
}

function renderExternalSyncSummary(container, jobs = []) {
  clearOverviewContainer(container);
  const selected = (Array.isArray(jobs) ? jobs : []).filter((job) => ["aras_paa", "aras_ncr_progress", "aras_ncr_detail"].includes(job.jobKey));
  container.appendChild(overviewEl("p", "eyebrow", "外部同步"));
  container.appendChild(overviewEl("h4", null, "PAA / NCR 同步概况"));
  const grid = overviewEl("div", "external-sync-summary-grid");
  const labels = { aras_paa: "PAA", aras_ncr_progress: "NCR 审批进度", aras_ncr_detail: "NCR 审批明细" };
  selected.forEach((job) => {
    const card = overviewEl("article", "external-sync-summary-card");
    card.append(
      overviewEl("strong", null, labels[job.jobKey] || job.jobKey),
      overviewEl("span", "external-sync-state", archiveSyncStateLabel(job.syncState)),
      overviewEl("small", null, `最近成功：${job.lastSuccessAt || "暂无"}`),
      overviewEl("small", null, job.lastErrorMessage ? `错误：${redactSensitiveText(job.lastErrorMessage)}` : "错误：无"),
    );
    grid.appendChild(card);
  });
  if (!selected.length) grid.appendChild(overviewEl("p", "is-empty", "暂无 PAA/NCR 同步任务"));
  container.appendChild(grid);
}

function ewoPolicyString(value) {
  return typeof value === "string" ? value.trim() : "";
}

function ewoPolicyDiscoveryFields(discovery) {
  const observations = discovery && Array.isArray(discovery.observations)
    ? discovery.observations
    : [];
  const latest = observations[0] || {};
  const report = latest.fieldReport && typeof latest.fieldReport === "object"
    ? latest.fieldReport
    : {};
  return Array.isArray(report.fields)
    ? report.fields.map((value) => ewoPolicyString(value)).filter(Boolean)
    : [];
}

function ewoPolicyDiscoveryStateLabel(value) {
  const labels = {
    matched: "已匹配",
    not_found: "未找到",
    ambiguous: "候选不唯一",
    key_changed: "稳定键发生变化",
  };
  return labels[value] || "待确认";
}

function ewoPolicyErrorMessage(error) {
  if (error && error.fields && typeof error.fields === "object") {
    const fields = Object.entries(error.fields)
      .map(([field, message]) => `${field}：${message}`)
      .join("；");
    if (fields) return fields;
  }
  return error instanceof Error ? error.message : String(error);
}

function renderEwoDeliverablePolicy(container, item, policy, options = {}) {
  container.textContent = "";
  const currentPolicy = policy && typeof policy === "object" ? policy : {};
  const supportedModes = Object.keys(EWO_POLICY_MODE_LABELS);
  const currentMode = supportedModes.includes(currentPolicy.mode) ? currentPolicy.mode : "manual";
  let discoveryData = options.discovery && typeof options.discovery === "object"
    ? options.discovery
    : {};
  const settingsData = options.settings && typeof options.settings === "object"
    ? options.settings
    : null;
  const vaultConfigured = settingsData !== null && settingsData.credentialVaultConfigured === true;
  const itemToken = String(item.id || "ewo").replace(/[^A-Za-z0-9_-]/g, "-");
  const head = overviewEl("div", "policy-editor-head");
  head.append(
    overviewEl("strong", "policy-editor-title", "更新方式"),
    overviewEl("span", "policy-source", "数据来源 · ARAS EWO"),
  );

  const modeGroup = overviewEl("fieldset", "policy-mode-group");
  modeGroup.appendChild(overviewEl("legend", null, "更新模式"));
  const modeControl = overviewEl("div", "policy-segmented");
  Object.entries(EWO_POLICY_MODE_LABELS).forEach(([value, label]) => {
    const input = document.createElement("input");
    input.type = "radio";
    input.name = `policy-mode-${item.id}`;
    input.id = `policy-mode-${item.id}-${value}`;
    input.value = value;
    input.checked = value === currentMode;
    const labelEl = overviewEl("label", null, label);
    labelEl.htmlFor = input.id;
    if (value === EWO_POLICY_RECOMMENDED_MODE) {
      labelEl.appendChild(overviewEl("span", "policy-ewo-mode-badge", "推荐：自动同步"));
    }
    modeControl.append(input, labelEl);
  });
  modeGroup.appendChild(modeControl);

  const bindingGroup = overviewEl("fieldset", "policy-ewo-binding");
  bindingGroup.appendChild(overviewEl("legend", null, "绑定同步配置"));
  const bindingGrid = overviewEl("div", "policy-ewo-binding-grid");

  const credentialLabel = overviewEl("label", "policy-ewo-field");
  credentialLabel.appendChild(overviewEl("span", null, "同步凭据引用"));
  const credentialInput = document.createElement("select");
  credentialInput.id = `policy-credential-ref-${itemToken}`;
  credentialInput.name = "credentialRef";
  const keepCredential = overviewEl(
    "option",
    null,
    currentPolicy.credentialAvailable === true
      ? "保持当前已绑定凭据（不修改）"
      : "暂不绑定（选择统一域账号）",
  );
  keepCredential.value = "";
  const domainCredential = overviewEl("option", null, "统一域账号（domain）");
  domainCredential.value = "domain";
  credentialInput.append(keepCredential, domainCredential);
  credentialLabel.appendChild(credentialInput);
  const credentialNote = currentPolicy.credentialAvailable === true
    ? "本交付物已有凭据引用；此处不显示用户名或密码。"
    : (vaultConfigured
      ? "全局凭据库已配置，但尚未绑定到本交付物；请选择统一域账号。"
      : "请先到系统设置登录并勾选“保存至凭据保护库”，再在此选择统一域账号。");
  credentialLabel.appendChild(overviewEl("small", "policy-field-note", credentialNote));
  bindingGrid.appendChild(credentialLabel);

  const externalKeyLabel = overviewEl("label", "policy-ewo-field");
  externalKeyLabel.appendChild(overviewEl("span", null, "外部稳定键"));
  const externalKeyInput = document.createElement("input");
  externalKeyInput.type = "text";
  externalKeyInput.name = "externalKey";
  externalKeyInput.id = `policy-external-key-${itemToken}`;
  externalKeyInput.maxLength = 200;
  externalKeyInput.value = ewoPolicyString(currentPolicy.externalKey);
  externalKeyInput.placeholder = "例如：EWO-2026-0001";
  externalKeyLabel.appendChild(externalKeyInput);
  externalKeyLabel.appendChild(overviewEl("small", "policy-field-note", "必须与映射发现记录中的唯一外部记录一致。"));
  bindingGrid.appendChild(externalKeyLabel);

  const matchGroup = overviewEl("fieldset", "policy-ewo-match");
  matchGroup.appendChild(overviewEl("legend", null, "匹配规则（报表类型固定为 EWO）"));
  const reportType = overviewEl("span", "policy-ewo-fixed-value", "reportType = ewo");
  matchGroup.appendChild(reportType);
  const matchRule = currentPolicy.matchRule && typeof currentPolicy.matchRule === "object"
    ? currentPolicy.matchRule
    : {};
  const matchInputs = new Map();
  EWO_POLICY_MATCH_FIELDS.forEach(([key, label, filterName]) => {
    const field = overviewEl("label", "policy-ewo-field");
    field.appendChild(overviewEl("span", null, label));
    const input = document.createElement("input");
    input.type = "text";
    input.dataset.matchKey = key;
    input.dataset.filterName = filterName;
    input.value = ewoPolicyString(matchRule[key]);
    input.placeholder = key === "ewoNo" ? "建议优先填写 EWO 编号" : "可选";
    field.appendChild(input);
    matchInputs.set(key, input);
    matchGroup.appendChild(field);
  });
  matchGroup.appendChild(overviewEl("small", "policy-field-note", "至少填写一个筛选条件；保存启用时后端会再次校验来源契约。"));
  bindingGrid.appendChild(matchGroup);

  const baseUrlLabel = overviewEl("label", "policy-ewo-field");
  baseUrlLabel.appendChild(overviewEl("span", null, "ECM 地址（仅用于抓取映射证据）"));
  const baseUrlInput = document.createElement("input");
  baseUrlInput.type = "url";
  baseUrlInput.name = "arasBaseUrl";
  baseUrlInput.value = EWO_POLICY_DEFAULT_ARAS_BASE_URL;
  baseUrlInput.placeholder = EWO_POLICY_DEFAULT_ARAS_BASE_URL;
  baseUrlLabel.appendChild(baseUrlInput);
  baseUrlLabel.appendChild(overviewEl("small", "policy-field-note", "使用设置页已认证的 ECM 会话，不在此填写账号密码。"));
  bindingGrid.appendChild(baseUrlLabel);
  bindingGroup.appendChild(bindingGrid);

  const authorityGroup = overviewEl("fieldset", "policy-ewo-authority");
  authorityGroup.appendChild(overviewEl("legend", null, "自动字段与来源映射"));
  const discoveredFields = new Set(ewoPolicyDiscoveryFields(discoveryData));
  EWO_POLICY_AUTOMATIC_FIELDS.forEach(([key, label]) => {
    const row = overviewEl("div", "policy-ewo-mapping-row");
    const authorityLabel = overviewEl("label", "policy-field-check");
    const authorityInput = document.createElement("input");
    authorityInput.type = "checkbox";
    authorityInput.name = `fieldAuthority-${key}`;
    authorityInput.dataset.authorityField = key;
    authorityInput.checked = currentPolicy.fieldAuthority
      && currentPolicy.fieldAuthority[key] === "automatic";
    authorityLabel.append(authorityInput, overviewEl("span", null, `${label}自动更新`));
    const mappingInput = document.createElement("input");
    mappingInput.type = "text";
    mappingInput.name = `mapping-${key}`;
    mappingInput.dataset.mappingField = key;
    mappingInput.setAttribute("list", `policy-discovered-fields-${itemToken}`);
    mappingInput.value = ewoPolicyString(currentPolicy.mapping && currentPolicy.mapping[key]);
    mappingInput.placeholder = "来源字段名，例如：_owner";
    mappingInput.disabled = !authorityInput.checked;
    const mappingLabel = overviewEl("label", "policy-ewo-field policy-ewo-mapping-field");
    mappingLabel.append(overviewEl("span", null, `${label}来源字段`), mappingInput);
    row.append(authorityLabel, mappingLabel);
    authorityGroup.appendChild(row);
    authorityInput.addEventListener("change", () => {
      mappingInput.disabled = !authorityInput.checked;
      refreshLocalReadiness();
    });
    mappingInput.addEventListener("input", refreshLocalReadiness);
  });
  const fieldList = document.createElement("datalist");
  fieldList.id = `policy-discovered-fields-${itemToken}`;
  const addDiscoveredField = (fieldName) => {
    const clean = ewoPolicyString(fieldName);
    if (!clean || discoveredFields.has(clean)) return;
    discoveredFields.add(clean);
    fieldList.appendChild(overviewEl("option", null, clean));
  };
  discoveredFields.forEach((fieldName) => {
    fieldList.appendChild(overviewEl("option", null, fieldName));
  });
  authorityGroup.appendChild(fieldList);
  bindingGroup.appendChild(authorityGroup);

  const discoveryGroup = overviewEl("div", "policy-ewo-discovery");
  const discoveryButton = overviewEl("button", "policy-discovery-btn", "抓取映射证据");
  discoveryButton.type = "button";
  const discoveryStatus = overviewEl("span", "policy-discovery-status", "");
  discoveryStatus.setAttribute("role", "status");
  discoveryStatus.setAttribute("aria-live", "polite");
  const initialStability = discoveryData.stability && Number.isFinite(Number(discoveryData.stability.confirmed))
    ? `${Math.min(Math.max(Number(discoveryData.stability.confirmed), 0), 2)}/2`
    : "0/2";
  discoveryStatus.textContent = `连续稳定证据：${initialStability}（需点击两次并保持目标一致）`;
  discoveryGroup.append(
    discoveryButton,
    discoveryStatus,
    overviewEl("small", "policy-field-note", "每次点击只抓取并保存脱敏字段报告，不会自动修改映射或业务数据。"),
  );

  const enabledLabel = overviewEl("label", "policy-ewo-enable");
  const enabledInput = document.createElement("input");
  enabledInput.type = "checkbox";
  enabledInput.name = "enabled";
  enabledInput.id = `policy-enabled-${itemToken}`;
  enabledInput.checked = currentPolicy.enabled === true;
  enabledLabel.append(enabledInput, overviewEl("span", null, "启用自动同步"));
  discoveryGroup.appendChild(enabledLabel);

  const localReadiness = overviewEl("p", "policy-ewo-readiness is-disabled");
  localReadiness.setAttribute("role", "status");
  const buildPolicyPayload = () => {
    const selectedMode = form.querySelector('input[type="radio"]:checked')?.value || "manual";
    const payload = {
      mode: selectedMode,
      enabled: enabledInput.checked,
      externalKey: ewoPolicyString(externalKeyInput.value) || null,
      matchRule: { reportType: "ewo" },
      mapping: {},
      fieldAuthority: {},
    };
    matchInputs.forEach((input, key) => {
      const value = ewoPolicyString(input.value);
      if (value) payload.matchRule[key] = value;
    });
    EWO_POLICY_AUTOMATIC_FIELDS.forEach(([key]) => {
      const authorityInput = authorityGroup.querySelector(`[data-authority-field="${key}"]`);
      const mappingInput = authorityGroup.querySelector(`[data-mapping-field="${key}"]`);
      const automatic = Boolean(authorityInput && authorityInput.checked);
      payload.fieldAuthority[key] = automatic ? "automatic" : "manual";
      if (automatic && mappingInput) {
        const sourceField = ewoPolicyString(mappingInput.value);
        if (sourceField) payload.mapping[key] = sourceField;
      }
    });
    if (credentialInput.value === "domain") payload.credentialRef = "domain";
    if (credentialInput.value === "__clear__") payload.credentialRef = null;
    return payload;
  };

  function refreshLocalReadiness() {
    const payload = buildPolicyPayload();
    const missing = [];
    if (!EWO_POLICY_MODE_LABELS[payload.mode] || !["automatic", "hybrid"].includes(payload.mode)) {
      missing.push("请选择自动同步或混合模式");
    }
    const credentialReady = currentPolicy.credentialAvailable === true
      || (payload.credentialRef === "domain" && vaultConfigured);
    if (!credentialReady) missing.push(vaultConfigured ? "尚未绑定统一域账号凭据" : "凭据保护库未配置");
    if (!payload.externalKey) missing.push("外部稳定键未确认");
    const matchKeys = Object.keys(payload.matchRule).filter((key) => key !== "reportType");
    if (matchKeys.length === 0) missing.push("至少填写一个 EWO 匹配条件");
    const automaticFields = Object.keys(payload.fieldAuthority)
      .filter((key) => payload.fieldAuthority[key] === "automatic");
    if (automaticFields.length === 0) missing.push("至少选择一个自动字段");
    if (automaticFields.some((key) => !payload.mapping[key])) missing.push("自动字段必须填写来源映射");
    const mappedFields = Object.values(payload.mapping);
    if (mappedFields.length > 0 && mappedFields.some((fieldName) => discoveredFields.size > 0 && !discoveredFields.has(fieldName))) {
      missing.push("来源映射必须来自最近的脱敏字段报告");
    }
    const stability = discoveryData.stability && Number(discoveryData.stability.confirmed);
    if (!Number.isFinite(stability) || stability < 2) missing.push(`映射稳定性未就绪（${Number.isFinite(stability) ? `${Math.max(stability, 0)}/2` : "0/2"}）`);
    if (payload.enabled && missing.length === 0) {
      localReadiness.textContent = "已满足启用条件：保存后同步按钮将可用，后端仍会执行最终校验。";
      localReadiness.className = "policy-ewo-readiness is-ready";
    } else if (!payload.enabled && missing.length === 0) {
      localReadiness.textContent = "绑定配置已齐全：勾选“启用自动同步”并保存后才会启用同步。";
      localReadiness.className = "policy-ewo-readiness is-disabled";
    } else {
      localReadiness.textContent = `尚缺：${missing.join("，")}`;
      localReadiness.className = "policy-ewo-readiness is-disabled";
    }
  }

  async function discoverMappingEvidence() {
    const payload = buildPolicyPayload();
    const filters = {};
    matchInputs.forEach((input) => {
      const filterName = input.dataset.filterName;
      const value = ewoPolicyString(input.value);
      if (filterName && value) filters[filterName] = value;
    });
    if (Object.keys(filters).length === 0 && payload.externalKey) filters.ewo_no = payload.externalKey;
    if (Object.keys(filters).length === 0 && !payload.externalKey) {
      discoveryStatus.textContent = "请先填写外部稳定键或至少一个 EWO 匹配条件。";
      discoveryStatus.className = "policy-discovery-status is-error";
      return;
    }
    discoveryButton.disabled = true;
    discoveryStatus.className = "policy-discovery-status is-busy";
    discoveryStatus.textContent = "正在抓取脱敏映射证据...";
    try {
      const response = await fetch(`/api/project-status/deliverables/${encodeURIComponent(item.id)}/mapping-discovery`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          base_url: ewoPolicyString(baseUrlInput.value) || EWO_POLICY_DEFAULT_ARAS_BASE_URL,
          filters,
          selectedExternalKey: payload.externalKey || null,
        }),
      });
      const body = await overviewReadJson(response);
      if (!response.ok || !body || body.ok !== true) throw overviewRequestError(body, response.status);
      const result = body.data || {};
      discoveryData = {
        ...discoveryData,
        stability: result.stability || discoveryData.stability,
        observations: [
          {
            state: result.state,
            externalKey: result.externalKey,
            candidateCount: result.candidateCount,
            fieldReport: result.fieldReport || {},
          },
          ...(Array.isArray(discoveryData.observations) ? discoveryData.observations : []),
        ],
      };
      const discoveredKey = ewoPolicyString(result.externalKey);
      if (!externalKeyInput.value.trim() && discoveredKey) externalKeyInput.value = discoveredKey;
      const fields = result.fieldReport && Array.isArray(result.fieldReport.fields)
        ? result.fieldReport.fields
        : [];
      fields.forEach(addDiscoveredField);
      const confirmed = result.stability && Number.isFinite(Number(result.stability.confirmed))
        ? `${Math.min(Math.max(Number(result.stability.confirmed), 0), 2)}/2`
        : "0/2";
      discoveryStatus.className = `policy-discovery-status ${result.state === "matched" ? "is-success" : "is-warning"}`;
      discoveryStatus.textContent = `本次${ewoPolicyDiscoveryStateLabel(result.state)}：候选 ${Number(result.candidateCount) || 0} 条；连续稳定证据 ${confirmed}。`;
      refreshLocalReadiness();
      if (typeof options.onEvidenceRefresh === "function") void options.onEvidenceRefresh();
    } catch (error) {
      discoveryStatus.className = "policy-discovery-status is-error";
      discoveryStatus.textContent = `抓取失败：${redactSensitiveText(ewoPolicyErrorMessage(error))}`;
    } finally {
      discoveryButton.disabled = false;
    }
  }
  discoveryButton.addEventListener("click", () => void discoverMappingEvidence());
  enabledInput.addEventListener("change", refreshLocalReadiness);
  credentialInput.addEventListener("change", refreshLocalReadiness);
  externalKeyInput.addEventListener("input", refreshLocalReadiness);
  matchInputs.forEach((input) => input.addEventListener("input", refreshLocalReadiness));

  const note = overviewEl(
    "p",
    "policy-ewo-note",
    "已认证会话和全局凭据库不会自动绑定到本交付物；本表单只保存凭据别名和同步策略，不保存密码。",
  );
  const form = overviewEl("form", "policy-editor-form");
  const status = overviewEl("p", "policy-request-status");
  status.setAttribute("role", "status");
  const actions = overviewEl("div", "policy-editor-actions");
  const save = overviewEl("button", "policy-save-btn", "保存同步绑定");
  save.type = "submit";
  const history = overviewEl("button", "policy-history-btn", "更新记录");
  history.type = "button";
  const historyBody = overviewEl("div", "policy-history");
  history.addEventListener("click", () => loadDeliverableUpdateHistory(item.id, historyBody));
  actions.append(save, history);
  form.append(modeGroup, bindingGroup, discoveryGroup, localReadiness, note, actions, status, historyBody);
  form.addEventListener(
    "submit",
    async (event) => {
      event.preventDefault();
      const payload = buildPolicyPayload();
      if (payload.enabled && !vaultConfigured && currentPolicy.credentialAvailable !== true) {
        updatePolicyStatusMessage(status, "系统设置未检测到凭据保护库，请先登录并保存统一域账号。", true);
        return;
      }
      save.disabled = true;
      updatePolicyStatusMessage(status, "正在保存...");
      try {
        const response = await fetch(`/api/project-status/deliverables/${encodeURIComponent(item.id)}/update-policy`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify(payload),
        });
        const body = await overviewReadJson(response);
        if (!response.ok || !body || body.ok !== true) throw overviewRequestError(body, response.status);
        const saved = body.data;
        item.updatePolicy = {
          ...item.updatePolicy,
          mode: saved.mode,
          enabled: saved.enabled,
          credentialAvailable: saved.credentialAvailable,
          externalKey: saved.externalKey,
          matchRule: saved.matchRule,
          mapping: saved.mapping,
          fieldAuthority: saved.fieldAuthority,
          sourceType: saved.sourceType,
          syncState: saved.syncState,
          lastSuccessAt: saved.lastSuccessAt,
        };
        renderEwoDeliverablePolicy(container, item, saved, {
          ...options,
          settings: settingsData,
          discovery: discoveryData,
        });
        const refreshedStatus = container.querySelector(".policy-request-status");
        updatePolicyStatusMessage(refreshedStatus, "更新方式已保存");
        if (typeof options.onEvidenceRefresh === "function") void options.onEvidenceRefresh();
      } catch (err) {
        updatePolicyStatusMessage(status, redactSensitiveText(ewoPolicyErrorMessage(err)), true);
        save.disabled = false;
      }
    },
  );
  container.append(head, form);
  refreshLocalReadiness();
}

async function loadDeliverablePolicy(container, item, options = {}) {
  if (/ewo/i.test(String(item.source || ""))) {
    container.appendChild(overviewEl("p", "policy-loading", "正在读取更新策略..."));
    try {
      const [policyResponse, settingsResponse, discoveryResponse] = await Promise.all([
        fetch(`/api/project-status/deliverables/${encodeURIComponent(item.id)}/update-policy`, {
          headers: { Accept: "application/json" },
          cache: "no-store",
        }),
        fetch("/api/settings", { headers: { Accept: "application/json" }, cache: "no-store" }).catch(() => null),
        fetch(`/api/project-status/deliverables/${encodeURIComponent(item.id)}/mapping-discovery`, {
          headers: { Accept: "application/json" },
          cache: "no-store",
        }).catch(() => null),
      ]);
      const body = await overviewReadJson(policyResponse);
      if (!policyResponse.ok || !body || body.ok !== true) throw overviewRequestError(body, policyResponse.status);
      const settingsBody = settingsResponse ? await overviewReadJson(settingsResponse) : null;
      const discoveryBody = discoveryResponse ? await overviewReadJson(discoveryResponse) : null;
      if (typeof options.onPolicyLoaded === "function") options.onPolicyLoaded(body.data || {});
      renderEwoDeliverablePolicy(container, item, body.data, {
        ...options,
        settings: settingsBody && settingsBody.ok === true ? settingsBody.data : null,
        discovery: discoveryBody && discoveryBody.ok === true ? discoveryBody.data : null,
      });
    } catch (err) {
      // 无绑定或读取失败时按未启用展示，并保留脱敏后的错误信息。
      renderEwoDeliverablePolicy(container, item, null, options);
      container.appendChild(overviewEl(
        "p",
        "policy-request-status is-error",
        redactSensitiveText(ewoPolicyErrorMessage(err)),
      ));
    }
    return;
  }
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
  "VPI-T2-D5": "数模设计审核流程报表",
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

async function requestProjectStatusSync(item) {
  const response = await fetch(`/api/project-status/deliverables/${encodeURIComponent(item.id)}/sync-now`, {
    method: "POST",
    headers: { Accept: "application/json" },
  });
  const body = await overviewReadJson(response);
  if (!response.ok || !body || body.ok !== true) {
    throw overviewRequestError(body, response.status);
  }
  return body.data || {};
}

function createDeliverableAnalysisSyncState() {
  let controller = null;
  let ready = false;
  let message = "正在读取同步前置条件";
  let statusText = "";
  let statusTone = "";
  let busy = false;

  return {
    get ready() {
      return ready;
    },
    get message() {
      return message;
    },
    setReadiness(nextReady, nextMessage = "") {
      ready = Boolean(nextReady);
      message = String(nextMessage || (ready ? "" : "同步条件尚未满足"));
      if (controller && typeof controller.setSyncReadiness === "function") {
        controller.setSyncReadiness(ready, message);
      }
    },
    setStatus(nextText, nextTone = "") {
      statusText = String(nextText || "");
      statusTone = nextTone;
      if (controller && typeof controller.setSyncStatus === "function") {
        controller.setSyncStatus(statusText, statusTone);
      }
    },
    setBusy(nextBusy) {
      busy = Boolean(nextBusy);
      if (controller && typeof controller.setBusy === "function") {
        controller.setBusy(busy);
      }
    },
    attach(nextController) {
      controller = nextController || null;
      if (!controller) return;
      if (typeof controller.setSyncReadiness === "function") {
        controller.setSyncReadiness(ready, message);
      }
      if (statusText && typeof controller.setSyncStatus === "function") {
        controller.setSyncStatus(statusText, statusTone);
      }
      if (typeof controller.setBusy === "function") controller.setBusy(busy);
    },
  };
}

function setDeliverableAnalysisSyncReadiness(item, ready, message, analysisSyncReadiness = null) {
  if (analysisSyncReadiness && typeof analysisSyncReadiness.setReadiness === "function") {
    analysisSyncReadiness.setReadiness(ready, message);
  }
}

function unifiedStatusStateLabel(value, labels) {
  const normalized = String(value || "unknown");
  return labels[normalized] || safeDisplayValue(normalized);
}

function unifiedStatusTone(value, group) {
  const normalized = String(value || "unknown");
  const successStates = {
    auth: ["authenticated"],
    query: ["matched"],
    sync: ["manual", "ready", "success"],
  };
  const warningStates = {
    auth: ["credential_missing", "credential_invalid", "unknown"],
    query: ["querying", "service_unavailable", "no_match"],
    sync: ["running", "partial_success", "needs_attention"],
  };
  const errorStates = {
    auth: ["unauthenticated"],
    query: ["failed"],
    sync: ["failed"],
  };
  if ((successStates[group] || []).includes(normalized)) return "success";
  if ((errorStates[group] || []).includes(normalized)) return "error";
  if ((warningStates[group] || []).includes(normalized)) return "warning";
  return "warning";
}

function renderUnifiedStatusValue(value, labels, group) {
  const text = unifiedStatusStateLabel(value, labels);
  return overviewEl("span", `status-text is-${unifiedStatusTone(value, group)}`, text);
}

function renderDeliverableUnifiedStatus(container, objects = []) {
  clearOverviewContainer(container);
  const authLabels = {
    unauthenticated: "未认证",
    credential_missing: "缺少凭据",
    credential_invalid: "凭据无效",
    authenticated: "已认证",
    unknown: "未知",
  };
  const queryLabels = {
    idle: "空闲",
    querying: "查询中",
    service_unavailable: "服务不可用",
    failed: "查询失败",
    no_match: "未匹配",
    matched: "已匹配",
  };
  const syncLabels = {
    idle: "空闲",
    manual: "手动维护",
    ready: "已就绪",
    running: "同步中",
    success: "成功",
    partial_success: "部分成功",
    needs_attention: "需要处理",
    failed: "失败",
  };
  const kindLabels = { ewo: "EWO", paa: "PAA", ncr: "NCR" };
  const byKind = new Map();
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
      const severity = { failed: 5, service_unavailable: 4, partial_success: 3, needs_attention: 3, running: 2, ready: 1, success: 0, idle: 0, manual: 0 };
      const worse = (field) => (severity[String(previous[field] || "").toLowerCase()] || 0) >= (severity[String(object[field] || "").toLowerCase()] || 0) ? previous[field] : object[field];
      byKind.set(kind, { ...previous, ...object, auth_state: previous.auth_state === "credential_invalid" ? previous.auth_state : object.auth_state === "credential_invalid" ? object.auth_state : object.auth_state || previous.auth_state, query_state: worse("query_state"), sync_state: worse("sync_state"), errors: [...new Set(errors)].slice(0, 4) });
    });

  const title = overviewEl("h5", "evidence-sub-title", "EWO / PAA / NCR 统一状态");
  const cards = overviewEl("div", "evidence-overview-grid unified-status-cards");
  ["ewo", "paa", "ncr"].forEach((kind) => {
    const object = byKind.get(kind) || {};
    const card = overviewEl("article", "evidence-restriction-card unified-status-card");
    card.setAttribute("aria-label", `${kindLabels[kind]} 状态`);
    card.appendChild(overviewEl("strong", "evidence-restriction-title", kindLabels[kind]));

    const identity = object.id || object.source
      ? `${safeDisplayValue(object.id || "未知对象")} · ${safeDisplayValue(object.source || "未知来源")}`
      : "暂无状态数据";
    card.appendChild(overviewEl("p", "evidence-restriction-desc", identity));

    const stateGrid = overviewEl("dl", "evidence-obs-grid unified-status-state-grid");
    stateGrid.append(
      overviewEl("dt", null, "认证状态"),
      overviewEl("dd", null),
      overviewEl("dt", null, "查询状态"),
      overviewEl("dd", null),
      overviewEl("dt", null, "同步状态"),
      overviewEl("dd", null),
    );
    stateGrid.children[1].appendChild(renderUnifiedStatusValue(object.auth_state, authLabels, "auth"));
    stateGrid.children[3].appendChild(renderUnifiedStatusValue(object.query_state, queryLabels, "query"));
    stateGrid.children[5].appendChild(renderUnifiedStatusValue(object.sync_state, syncLabels, "sync"));
    card.appendChild(stateGrid);

    const errors = Array.isArray(object.errors)
      ? object.errors.filter((error) => error !== null && error !== undefined && String(error).trim())
      : [];
    const errorSummary = errors.length > 0
      ? errors.slice(0, 2).map((error) => redactSensitiveText(String(error))).join("；")
      : "无";
    const content = object.content && typeof object.content === "object" ? object.content : {};
    card.append(
      overviewEl("span", "evidence-field-label", "错误摘要"),
      overviewEl("p", "evidence-risk-desc unified-status-error-summary", safeDisplayValue(errorSummary)),
      overviewEl("span", "evidence-field-label", "最近更新"),
      overviewEl("p", "evidence-restriction-desc", safeDisplayValue(object.last_updated || "未知")),
      overviewEl("span", "evidence-field-label", "内容来源"),
      overviewEl("p", "evidence-restriction-desc", safeDisplayValue(content.report_type || "暂无内容")),
      overviewEl("span", "evidence-field-label", "最近成功"),
      overviewEl("p", "evidence-restriction-desc", safeDisplayValue(content.last_success_at || "暂无记录")),
    );
    cards.appendChild(card);
  });

  container.append(title, cards);
}

async function loadDeliverableUnifiedStatus(container, item) {
  clearOverviewContainer(container);
  const loading = overviewEl("p", "loading", "正在读取 EWO / PAA / NCR 统一状态...");
  loading.setAttribute("role", "status");
  loading.setAttribute("aria-live", "polite");
  container.appendChild(loading);
  try {
    const response = await fetch(
      `/api/project-status/deliverables/${encodeURIComponent(item.id)}/unified-status`,
      {
        method: "GET",
        headers: { Accept: "application/json" },
        cache: "no-store",
      },
    );
    const body = await overviewReadJson(response);
    if (!response.ok || !body || body.ok !== true) {
      throw overviewRequestError(body, response.status);
    }
    const objects = body.data && Array.isArray(body.data.objects) ? body.data.objects : [];
    renderDeliverableUnifiedStatus(container, objects);
    return true;
  } catch (err) {
    clearOverviewContainer(container);
    const errorBox = overviewEl("div", "unified-status-load-error");
    errorBox.setAttribute("role", "alert");
    errorBox.setAttribute("aria-live", "assertive");
    errorBox.appendChild(overviewEl(
      "p",
      "error-msg",
      `读取统一状态失败：${redactSensitiveText(err instanceof Error ? err.message : String(err))}`,
    ));
    const retryButton = overviewEl("button", "evidence-retry-btn unified-status-retry-btn", "重试统一状态");
    retryButton.type = "button";
    retryButton.addEventListener("click", () => loadDeliverableUnifiedStatus(container, item));
    errorBox.appendChild(retryButton);
    container.appendChild(errorBox);
    return false;
  }
}

async function loadDeliverableEvidence(
  container,
  item,
  bundle = null,
  statusInfo = null,
  statusChart = null,
  analysisSyncReadiness = null,
) {
  if (bundle) {
    renderDeliverableEvidence(container, item, bundle, statusInfo, statusChart, analysisSyncReadiness);
    const unifiedStatusSection = overviewEl("section", "evidence-unified-status");
    container.prepend(unifiedStatusSection);
    loadDeliverableUnifiedStatus(unifiedStatusSection, item);
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

  const unifiedStatusSection = overviewEl("section", "evidence-unified-status");
  container.appendChild(unifiedStatusSection);
  loadDeliverableUnifiedStatus(unifiedStatusSection, item);

  if (item.id === "VPI-T2-D1") {
    setDeliverableAnalysisSyncReadiness(item, false, "该交付物仅支持手动维护", analysisSyncReadiness);
    const notice = overviewEl("div", "evidence-restriction-card is-manual");
    notice.append(
      overviewEl("strong", "evidence-restriction-title", "仅手工维护"),
      overviewEl("p", "evidence-restriction-desc", "该交付物当前仅允许手工维护，未接入外部系统。"),
    );
    container.appendChild(notice);
    return;
  }

  if (item.id === "VPI-T2-D4") {
    setDeliverableAnalysisSyncReadiness(item, false, "该交付物外部数据契约待验证，当前已阻断外部同步", analysisSyncReadiness);
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
    renderDeliverableEvidence(
      container,
      item,
      { policy, analytics, mapping, preview, runs },
      statusInfo,
      statusChart,
      analysisSyncReadiness,
    );
  } catch (err) {
    loadingP.remove();
    setDeliverableAnalysisSyncReadiness(
      item,
      false,
      "同步前置条件读取失败，请展开下方证据区域重试",
      analysisSyncReadiness,
    );
    if (statusChart && typeof statusChart.setSyncReadiness === "function" && /ewo/i.test(String(item.source || ""))) {
      statusChart.setSyncReadiness(false, "同步前置条件读取失败，请展开下方证据区域重试");
    }
    const errBox = overviewEl("div", "evidence-load-error");
    errBox.setAttribute("role", "alert");
    errBox.setAttribute("aria-live", "assertive");
    errBox.appendChild(overviewEl("p", "error-msg", `读取证据失败：${redactSensitiveText(err instanceof Error ? err.message : String(err))}`));
    const retryBtn = overviewEl("button", "evidence-retry-btn", "重试");
    retryBtn.type = "button";
    retryBtn.addEventListener(
      "click",
      () => loadDeliverableEvidence(container, item, null, statusInfo, statusChart, analysisSyncReadiness),
    );
    errBox.appendChild(retryBtn);
    container.appendChild(errBox);
  }
}

function renderDeliverableEvidence(
  container,
  item,
  bundle,
  statusInfo = null,
  statusChart = null,
  analysisSyncReadiness = null,
) {
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

  // 2. Offline Debug Tools (all diagnostic output is redacted before display/copy).
  const debugSection = overviewEl("section", "evidence-debug-tools");
  debugSection.appendChild(overviewEl("h5", "evidence-sub-title", "Debug 工具"));
  debugSection.appendChild(overviewEl("p", "evidence-debug-notice", "敏感字段已过滤"));
  const debugActions = overviewEl("div", "evidence-debug-actions");
  const debugStatus = overviewEl("span", "evidence-debug-status");
  debugStatus.setAttribute("role", "status");
  debugStatus.setAttribute("aria-live", "polite");
  const debugJsonEndpoint = `/api/project-status/deliverables/${encodeURIComponent(item.id)}/debug-bundle?format=json`;
  const debugZipEndpoint = `/api/project-status/deliverables/${encodeURIComponent(item.id)}/debug-bundle?format=zip`;

  const copyDebugButton = overviewEl("button", "evidence-debug-btn", "复制诊断摘要");
  copyDebugButton.type = "button";
  copyDebugButton.addEventListener("click", async () => {
    try {
      const summary = buildDeliverableDebugSummary({ policy, analytics, mapping, runs });
      if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") {
        throw new Error("当前浏览器不支持复制");
      }
      await navigator.clipboard.writeText(summary);
      debugStatus.textContent = "诊断摘要已复制";
      debugStatus.className = "evidence-debug-status is-success";
    } catch (err) {
      debugStatus.textContent = `复制失败：${redactSensitiveText(err instanceof Error ? err.message : String(err))}`;
      debugStatus.className = "evidence-debug-status is-error";
    }
  });

  const downloadJsonButton = overviewEl("button", "evidence-debug-btn", "下载 JSON");
  downloadJsonButton.type = "button";
  downloadJsonButton.addEventListener("click", async () => {
    await downloadDeliverableDebugBundle(
      debugJsonEndpoint,
      `${sanitizeDownloadName(String(item.id)) || "deliverable"}_debug.json`,
      downloadJsonButton,
      debugStatus,
    );
  });

  const downloadZipButton = overviewEl("button", "evidence-debug-btn", "下载 ZIP");
  downloadZipButton.type = "button";
  downloadZipButton.addEventListener("click", async () => {
    await downloadDeliverableDebugBundle(
      debugZipEndpoint,
      `${sanitizeDownloadName(String(item.id)) || "deliverable"}_debug.zip`,
      downloadZipButton,
      debugStatus,
    );
  });

  debugActions.append(copyDebugButton, downloadJsonButton, downloadZipButton, debugStatus);
  debugSection.appendChild(debugActions);
  container.appendChild(debugSection);

  // 3. Risk / Needs Attention Alert (if any)
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
  const syncMissing = [];
  const syncSupported = !["VPI-T2-D1", "VPI-T2-D4"].includes(item.id);
  const syncModeReady = ["automatic", "hybrid"].includes(policy.mode);
  const syncExternalKeyReady = typeof policy.externalKey === "string" && Boolean(policy.externalKey.trim());
  const syncMatchRule = policy.matchRule && typeof policy.matchRule === "object" ? policy.matchRule : {};
  const syncMatchRuleReady = Boolean(syncMatchRule.reportType) && Object.keys(syncMatchRule).length >= 2;
  const syncMapping = policy.mapping && typeof policy.mapping === "object" ? policy.mapping : {};
  const syncAuthorities = policy.fieldAuthority && typeof policy.fieldAuthority === "object"
    ? Object.entries(policy.fieldAuthority)
      .filter(([, authority]) => authority === "automatic")
      .map(([field]) => field)
    : [];
  const syncFieldMappingReady = syncAuthorities.length > 0
    && Object.keys(syncMapping).length === syncAuthorities.length
    && Object.keys(syncMapping).every((field) => syncAuthorities.includes(field));
  const syncReady = Boolean(
    syncSupported
    && policy.enabled === true
    && syncModeReady
    && policy.credentialAvailable === true
    && syncExternalKeyReady
    && syncMatchRuleReady
    && syncFieldMappingReady
    && stabilityReady
  );
  if (!syncReady) {
    const missing = [];
    if (policy.enabled !== true || !syncModeReady) missing.push("更新策略未启用或未选择自动/混合模式");
    if (policy.credentialAvailable !== true) missing.push("凭据未配置或状态未知");
    if (!syncExternalKeyReady) missing.push("外部稳定键未确认");
    if (!syncMatchRuleReady) missing.push("匹配规则未确认");
    if (!syncFieldMappingReady) missing.push("自动字段映射未确认");
    if (!stabilityReady) missing.push(`映射稳定性未就绪 (${mappingProgressText})`);
    syncMissing.push(...missing);
  }
  setDeliverableAnalysisSyncReadiness(
    item,
    syncSupported && syncReady,
    syncMissing.join("，") || "同步条件尚未满足",
    analysisSyncReadiness,
  );

  const syncActionBar = overviewEl("div", "evidence-sync-bar");
  const syncBtn = overviewEl("button", "evidence-sync-btn", "后台同步");
  syncBtn.type = "button";
  syncBtn.disabled = !syncSupported || !syncReady;
  if (!syncReady) syncBtn.title = `不可同步：${syncMissing.join("，") || "同步条件尚未满足"}`;

  if (statusChart && typeof statusChart.setSyncReadiness === "function" && /ewo/i.test(String(item.source || ""))) {
    statusChart.setSyncReadiness(
      syncSupported && syncReady,
      syncMissing.join("，") || "同步条件尚未满足",
    );
  }

  const syncStatus = overviewEl("span", "evidence-sync-status");
  syncStatus.setAttribute("role", "status");
  syncStatus.setAttribute("aria-live", "polite");

  if (statusInfo && statusInfo.text) {
    syncStatus.textContent = statusInfo.text;
    syncStatus.className = statusInfo.className || "evidence-sync-status";
  } else if (!syncSupported) {
    syncStatus.textContent = "该交付物仅支持手动维护";
    syncStatus.className = "evidence-sync-status is-warning";
  } else if (!syncReady) {
    syncStatus.textContent = `暂不能同步：${syncMissing.join("，") || "同步条件尚未满足"}`;
    syncStatus.className = "evidence-sync-status is-warning";
  }

  syncBtn.addEventListener("click", async () => {
    if (!syncReady) {
      syncStatus.textContent = `暂不能同步：${syncMissing.join("，") || "同步条件尚未满足"}`;
      syncStatus.className = "evidence-sync-status is-warning";
      return;
    }
    if (!window.confirm(`确定要执行后台同步 ${item.name} 吗？`)) return;
    syncBtn.disabled = true;
    syncStatus.textContent = "正在执行后台同步...";
    syncStatus.className = "evidence-sync-status is-busy";

    try {
      const resData = await requestProjectStatusSync(item);
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
      syncBtn.disabled = !syncSupported || !syncReady;
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

// 车型查找状态：随"应用筛选"提交，作用于明细与统计摘要（同口径）。
// 进入详情页时重置；match 取值 fuzzy（默认）| exact。
const analysisModelFilter = { model: "", match: "fuzzy" };

function debugBundleSensitiveKey(key) {
  const normalized = String(key).toLowerCase().replace(/[\s-]+/g, "_");
  return SENSITIVE_COLUMNS.has(normalized)
    || /(authorization|password|token|cookie|secret|session|csrf|credential|api_?key|private_?key)/i.test(normalized);
}

function redactDeliverableDebugValue(value) {
  if (Array.isArray(value)) return value.map((entry) => redactDeliverableDebugValue(entry));
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, entry]) => [
        key,
        debugBundleSensitiveKey(key) ? "[FILTERED]" : redactDeliverableDebugValue(entry),
      ]),
    );
  }
  return typeof value === "string" ? redactSensitiveText(value) : value;
}

function buildDeliverableDebugSummary(bundle) {
  const sections = ["policy", "analytics", "mapping", "runs"];
  const lines = ["VSE 交付物诊断摘要", "敏感字段已过滤"];
  sections.forEach((name) => {
    let payload = redactDeliverableDebugValue(bundle && bundle[name]);
    if (payload === undefined) payload = null;
    let serialized = "";
    try {
      serialized = JSON.stringify(payload, null, 2);
    } catch {
      serialized = "null";
    }
    lines.push(`\n[${name}]\n${serialized || "null"}`);
  });
  return lines.join("\n");
}

async function downloadDeliverableDebugBundle(endpoint, defaultFileName, button, statusNode) {
  if (button) button.disabled = true;
  if (statusNode) {
    statusNode.textContent = "正在准备诊断包...";
    statusNode.className = "evidence-debug-status is-busy";
  }
  let objectUrl = "";
  let link = null;
  try {
    const response = await fetch(endpoint, {
      method: "GET",
      headers: { Accept: "application/json, application/zip" },
      cache: "no-store",
    });
    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      try {
        const body = await response.json();
        const error = body && body.error;
        if (error && error.message) message = formatApiErrorMessage(error, response.status);
      } catch {
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
    link.remove();
    if (statusNode) {
      statusNode.textContent = "诊断包已下载（敏感字段已过滤）";
      statusNode.className = "evidence-debug-status is-success";
    }
  } catch (err) {
    if (statusNode) {
      statusNode.textContent = `下载失败：${redactSensitiveText(err instanceof Error ? err.message : String(err))}`;
      statusNode.className = "evidence-debug-status is-error";
    }
  } finally {
    if (link) link.remove();
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    if (button) button.disabled = false;
  }
}

async function loadDeliverableAnalysis(container, item, statusChart = null, analysisOptions = {}) {
  clearOverviewContainer(container);
  const loadingP = overviewEl("p", "loading", "加载交付物分析与明细...");
  loadingP.setAttribute("role", "status");
  loadingP.setAttribute("aria-live", "polite");
  container.appendChild(loadingP);

  try {
    const filterParams = new URLSearchParams();
    if (analysisModelFilter.model) {
      filterParams.set("model", analysisModelFilter.model);
      filterParams.set("modelMatch", analysisModelFilter.match);
    }
    const filterQuery = filterParams.toString();
    const analysisRes = await fetch(
      `/api/project-status/deliverables/${encodeURIComponent(item.id)}/analysis${filterQuery ? `?${filterQuery}` : ""}`,
      {
        method: "GET",
        headers: { Accept: "application/json" },
        cache: "no-store",
      }
    );
    const analysisBody = await overviewReadJson(analysisRes);

    if (!analysisRes.ok || !analysisBody || analysisBody.ok !== true) {
      throw overviewRequestError(analysisBody, analysisRes.status);
    }
    const analysisData = analysisBody.data || {};

    if (statusChart && typeof statusChart.updateEwoSummary === "function") {
      statusChart.updateEwoSummary(analysisData);
    }
    const analysisSyncReadiness = analysisOptions.analysisSyncReadiness || null;
    renderDeliverableAnalysis(container, item, analysisData, {
      ...analysisOptions,
      analysisSyncReadiness,
      onReload: () => loadDeliverableAnalysis(container, item, statusChart, analysisOptions),
    });
    return true;
  } catch (err) {
    clearOverviewContainer(container);
    const errBox = overviewEl("div", "error-msg", formatApiErrorMessage(err, 500));
    errBox.setAttribute("role", "alert");
    errBox.setAttribute("aria-live", "assertive");
    container.appendChild(errBox);
    if (statusChart && typeof statusChart.setSyncStatus === "function") {
      statusChart.setSyncStatus(`读取失败：${formatApiErrorMessage(err, 500)}`, "error");
    }
    return false;
  }
}

function renderDepartmentDoneChart(summary, departments, onSelect, options = {}) {
  const section = overviewEl("div", "analysis-sub-section");

  const headerRow = overviewEl("div", "analysis-dept-chart-header");
  headerRow.appendChild(overviewEl("h6", "analysis-sub-title", options.title || "按科室完成情况（已完成 / 未完成）"));

  const legend = overviewEl("div", "analysis-chart-legend");
  legend.append(
    overviewEl("span", "analysis-chart-legend-item is-completed", "已完成"),
    overviewEl("span", "analysis-chart-legend-item is-incomplete", "未完成"),
  );
  headerRow.appendChild(legend);
  section.appendChild(headerRow);

  const deptEntries = Object.entries(departments || {})
    .filter(([, value]) => value && typeof value === "object")
    .sort(([, a], [, b]) => (Number(b.total) || 0) - (Number(a.total) || 0));

  if (deptEntries.length === 0 && (!summary || Number(summary.total) === 0)) {
    section.appendChild(overviewEl("p", "analysis-empty-note is-empty", "暂无科室完成情况统计"));
    return {
      el: section,
      setSelected: () => {},
    };
  }

  const overallTotal = Number(summary && summary.total) || 0;
  const overallCompleted = Number(summary && summary.completed) || 0;
  const overallIncomplete = Number(summary && summary.incomplete) || Math.max(0, overallTotal - overallCompleted);

  const deptTotals = deptEntries.map(([, d]) => Number(d.total) || 0);
  const maxTotal = Math.max(1, overallTotal, ...deptTotals);

  const chartBox = overviewEl("div", "analysis-dept-bars-box");

  // Pinned Overall Row
  const overallRow = overviewEl("div", "analysis-dept-bar-row is-overall");
  overallRow.setAttribute("role", "button");
  overallRow.setAttribute("tabindex", "0");
  overallRow.setAttribute("aria-pressed", "false");
  overallRow.setAttribute("aria-label", `整体: 已完成 ${overallCompleted}, 未完成 ${overallIncomplete}, 共 ${overallTotal}`);

  const overallName = overviewEl("span", "analysis-dept-bar-name", "整体");
  overallName.title = "整体";

  const overallTrack = overviewEl("div", "analysis-dept-bar-track");
  const overallDoneFill = overviewEl("div", "analysis-dept-bar-fill is-completed");
  overallDoneFill.style.width = `${maxTotal > 0 ? (overallCompleted / maxTotal) * 100 : 0}%`;
  const overallUndoneFill = overviewEl("div", "analysis-dept-bar-fill is-incomplete");
  overallUndoneFill.style.width = `${maxTotal > 0 ? (overallIncomplete / maxTotal) * 100 : 0}%`;
  overallTrack.append(overallDoneFill, overallUndoneFill);

  const overallNums = overviewEl("span", "analysis-dept-bar-nums");
  overallNums.append(
    overviewEl("span", "analysis-dept-bar-num is-completed", `已完成 ${overallCompleted}`),
    overviewEl("span", "analysis-dept-bar-num is-incomplete", `未完成 ${overallIncomplete}`),
    overviewEl("span", "analysis-dept-bar-num is-total", `共 ${overallTotal}`),
  );
  overallRow.append(overallName, overallTrack, overallNums);

  let currentSelected = null;

  overallRow.addEventListener("click", () => {
    if (currentSelected !== null) {
      currentSelected = null;
      updateUI();
      if (onSelect) onSelect(null);
    }
  });
  overallRow.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      overallRow.click();
    }
  });

  chartBox.appendChild(overallRow);

  const rowEls = [];
  deptEntries.forEach(([name, val]) => {
    const tot = Number(val.total) || 0;
    const comp = Number(val.completed) || 0;
    const incomp = Number(val.incomplete) || Math.max(0, tot - comp);

    const row = overviewEl("div", "analysis-dept-bar-row");
    row.setAttribute("role", "button");
    row.setAttribute("tabindex", "0");
    row.setAttribute("aria-pressed", "false");
    row.setAttribute("aria-label", `${name}: 已完成 ${comp}, 未完成 ${incomp}, 共 ${tot}`);
    row.dataset.department = name;

    const label = overviewEl("span", "analysis-dept-bar-name", safeDisplayValue(name));
    label.title = name;

    const track = overviewEl("div", "analysis-dept-bar-track");
    const fillDone = overviewEl("div", "analysis-dept-bar-fill is-completed");
    fillDone.style.width = `${maxTotal > 0 ? (comp / maxTotal) * 100 : 0}%`;
    const fillUndone = overviewEl("div", "analysis-dept-bar-fill is-incomplete");
    fillUndone.style.width = `${maxTotal > 0 ? (incomp / maxTotal) * 100 : 0}%`;
    track.append(fillDone, fillUndone);

    const nums = overviewEl("span", "analysis-dept-bar-nums");
    nums.append(
      overviewEl("span", "analysis-dept-bar-num is-completed", `已完成 ${comp}`),
      overviewEl("span", "analysis-dept-bar-num is-incomplete", `未完成 ${incomp}`),
      overviewEl("span", "analysis-dept-bar-num is-total", `共 ${tot}`),
    );
    row.append(label, track, nums);

    row.addEventListener("click", () => {
      if (currentSelected === name) {
        currentSelected = null;
      } else {
        currentSelected = name;
      }
      updateUI();
      if (onSelect) onSelect(currentSelected);
    });
    row.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        row.click();
      }
    });

    rowEls.push({ name, el: row });
    chartBox.appendChild(row);
  });

  function updateUI() {
    rowEls.forEach(({ name, el }) => {
      const isSelected = currentSelected === name;
      el.setAttribute("aria-pressed", isSelected ? "true" : "false");
      el.classList.toggle("is-selected", isSelected);
    });
    overallRow.classList.toggle("is-selected", currentSelected === null);
  }

  updateUI();

  section.appendChild(chartBox);

  return {
    el: section,
    setSelected: (dept) => {
      currentSelected = dept || null;
      updateUI();
    },
  };
}

function createSearchMultiSelect({
  ariaLabel,
  placeholder,
  options,
  normalizeValue = (value) => value,
  labelFor = (value) => value,
}) {
  const root = overviewEl("div", "analysis-multi-select");
  root.setAttribute("role", "group");
  root.setAttribute("aria-label", ariaLabel);
  const control = overviewEl("div", "analysis-multi-select-control");
  const tokens = overviewEl("div", "analysis-multi-select-tokens");
  const input = document.createElement("input");
  input.type = "text";
  input.className = "analysis-multi-select-input";
  input.placeholder = placeholder;
  input.setAttribute("aria-label", ariaLabel);
  input.setAttribute("autocomplete", "off");
  tokens.appendChild(input);
  control.appendChild(tokens);

  const optionsBox = overviewEl("div", "analysis-multi-select-options");
  optionsBox.setAttribute("role", "listbox");
  optionsBox.hidden = true;
  root.append(control, optionsBox);

  const optionItems = (options || []).map((option) => {
    if (Array.isArray(option)) return { value: String(option[0]), label: String(option[1]) };
    return { value: String(option), label: String(option) };
  });
  let selected = [];
  let changeHandler = null;

  function renderTokens() {
    const currentInput = input.value;
    tokens.textContent = "";
    selected.forEach((value) => {
      const token = overviewEl("span", "analysis-filter-token");
      token.appendChild(overviewEl("span", "analysis-filter-token-label", safeDisplayValue(labelFor(value))));
      const remove = overviewEl("button", "analysis-filter-token-remove", "×");
      remove.type = "button";
      remove.setAttribute("aria-label", `移除 ${safeDisplayValue(labelFor(value))}`);
      remove.addEventListener("click", () => {
        selected = selected.filter((item) => item !== value);
        renderTokens();
        renderOptions();
        if (changeHandler) changeHandler(getValues());
        input.focus();
      });
      token.appendChild(remove);
      tokens.appendChild(token);
    });
    tokens.appendChild(input);
    input.value = currentInput;
  }

  function renderOptions() {
    const query = input.value.trim().toLocaleLowerCase();
    optionsBox.textContent = "";
    const matches = optionItems.filter((option) => {
      if (selected.includes(option.value)) return false;
      return !query || option.label.toLocaleLowerCase().includes(query)
        || option.value.toLocaleLowerCase().includes(query);
    });
    matches.slice(0, 30).forEach((option) => {
      const button = overviewEl("button", "analysis-multi-select-option", option.label);
      button.type = "button";
      button.setAttribute("role", "option");
      button.dataset.value = option.value;
      button.addEventListener("mousedown", (event) => event.preventDefault());
      button.addEventListener("click", () => addValue(option.value));
      optionsBox.appendChild(button);
    });
    optionsBox.hidden = matches.length === 0;
  }

  function addValue(rawValue) {
    const value = normalizeValue(String(rawValue || "").trim());
    if (!value || selected.includes(value)) {
      input.value = "";
      renderOptions();
      return false;
    }
    selected.push(value);
    input.value = "";
    renderTokens();
    renderOptions();
    if (changeHandler) changeHandler(getValues());
    return true;
  }

  function getValues() {
    return selected.slice();
  }

  function setValues(values) {
    selected = [];
    (values || []).forEach((value) => {
      const normalized = normalizeValue(String(value || "").trim());
      if (normalized && !selected.includes(normalized)) selected.push(normalized);
    });
    input.value = "";
    renderTokens();
    renderOptions();
  }

  function clear() {
    setValues([]);
  }

  input.addEventListener("focus", renderOptions);
  input.addEventListener("input", renderOptions);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      addValue(input.value);
    } else if (event.key === "Backspace" && !input.value && selected.length > 0) {
      selected.pop();
      renderTokens();
      renderOptions();
      if (changeHandler) changeHandler(getValues());
    }
  });
  control.addEventListener("click", () => input.focus());
  root.addEventListener("focusout", (event) => {
    if (!root.contains(event.relatedTarget)) {
      optionsBox.hidden = true;
    }
  });

  renderTokens();
  return {
    el: root,
    getValues,
    setValues,
    clear,
    focus: () => input.focus(),
    setOnChange: (handler) => { changeHandler = handler; },
  };
}

// 阶段值在接口与请求中保持小写规范值，只在所有用户可见位置显示大写。
function formatEwoStageLabel(stage) {
  return String(stage || "").trim().toUpperCase();
}

function renderAnalysisItemsSection(item, departments, onDeptChange, options = {}) {
  const section = overviewEl("div", "analysis-sub-section");
  const titleEl = overviewEl("h6", "analysis-sub-title", "明细任务清单");
  section.appendChild(titleEl);

  const PAGE_SIZE = 50;
  const state = {
    departments: [],
    stages: [],
    state: "all",
    page: 1,
  };
  let pendingState = "all";
  let filtersDirty = false;
  let totalItems = 0;
  let currentSeq = 0;

  // Toolbar
  const toolbar = overviewEl("div", "analysis-items-toolbar");

  // EWO 同步范围固定为五个责任科室；也保留当前缓存中出现的科室，
  // 方便用户排查历史数据。手工输入的未知科室会得到空结果。
  const ewoDefaultDepartments = ["车身科", "车体科", "外饰科", "内饰科", "车体架构集成科"];
  const deptNames = Array.from(new Set([
    ...((/ewo/i.test(String(item.source || ""))) ? ewoDefaultDepartments : []),
    ...Object.keys(departments || {}),
  ])).sort((a, b) => a.localeCompare(b, "zh-CN"));
  const deptMulti = createSearchMultiSelect({
    ariaLabel: "按科室筛选",
    placeholder: "全部科室—搜索或输入后按 Enter",
    options: deptNames,
  });

  // State select
  const stateSelect = document.createElement("select");
  stateSelect.className = "analysis-select";
  stateSelect.setAttribute("aria-label", "按完成状态筛选");
  [
    ["all", "全部状态"],
    ["completed", "仅已完成"],
    ["incomplete", "仅未完成"],
  ].forEach(([val, label]) => {
    const opt = document.createElement("option");
    opt.value = val;
    opt.textContent = label;
    stateSelect.appendChild(opt);
  });

  const stageOptions = [
    ["all", "全部阶段（含 OPEN/未知）"],
    ["open", "OPEN（未纳入统计）"],
    ["draft1", "DRAFT1"],
    ["draft2", "DRAFT2"],
    ["edit1", "EDIT1"],
    ["edit2", "EDIT2"],
    ["proc", "PROC"],
    ["impl", "IMPL"],
    ["close", "CLOSE（已关闭）"],
  ];
  const canonicalStages = new Set(stageOptions.map(([value]) => value));
  const stageMulti = createSearchMultiSelect({
    ariaLabel: "按流程阶段筛选",
    placeholder: "有效阶段（排除 OPEN）—搜索或输入后按 Enter",
    options: stageOptions,
    normalizeValue: (value) => {
      const normalized = String(value || "").trim().toLowerCase();
      return canonicalStages.has(normalized) ? normalized : "";
    },
    labelFor: formatEwoStageLabel,
  });

  const applyBtn = overviewEl("button", "btn is-primary analysis-filter-apply", "应用筛选");
  applyBtn.type = "button";
  applyBtn.setAttribute("aria-label", "应用科室和流程阶段筛选");
  const clearBtn = overviewEl("button", "btn is-secondary analysis-filter-clear", "清除筛选");
  clearBtn.type = "button";
  clearBtn.setAttribute("aria-label", "清除科室和流程阶段筛选");

  // 车型查找（仅 EWO 交付物）：默认模糊，可切换精确。
  const isEwoSource = /ewo/i.test(String(item.source || ""));
  let modelInput = null;
  const matchButtons = [];
  let modelWrap = null;
  if (isEwoSource) {
    modelWrap = overviewEl("div", "analysis-model-filter");
    modelInput = overviewEl("input", "analysis-model-input");
    modelInput.type = "text";
    modelInput.value = analysisModelFilter.model;
    modelInput.placeholder = "车型查找，如 F610S";
    modelInput.maxLength = 80;
    modelInput.setAttribute("aria-label", "按车型查找");
    const matchGroup = overviewEl("div", "analysis-model-match");
    [["fuzzy", "模糊"], ["exact", "精确"]].forEach(([value, label]) => {
      const btn = overviewEl("button", "analysis-model-match-btn", label);
      btn.type = "button";
      btn.dataset.match = value;
      const isActive = analysisModelFilter.match === value;
      btn.classList.toggle("is-active", isActive);
      btn.setAttribute("aria-pressed", isActive ? "true" : "false");
      btn.addEventListener("click", () => {
        analysisModelFilter.match = value;
        matchButtons.forEach((button) => {
          const buttonActive = button.dataset.match === value;
          button.classList.toggle("is-active", buttonActive);
          button.setAttribute("aria-pressed", buttonActive ? "true" : "false");
        });
      });
      matchButtons.push(btn);
      matchGroup.appendChild(btn);
    });
    modelWrap.append(modelInput, matchGroup);
  }

  const spacer = overviewEl("div", "analysis-toolbar-spacer");

  // Pager
  const pager = overviewEl("div", "analysis-items-pager");
  const pagerInfo = overviewEl("span", "analysis-pager-info", "共 0 条 · 第 1 / 1 页");
  const prevBtn = overviewEl("button", "btn is-secondary analysis-pager-btn", "上一页");
  const nextBtn = overviewEl("button", "btn is-secondary analysis-pager-btn", "下一页");
  prevBtn.type = "button";
  nextBtn.type = "button";
  prevBtn.disabled = true;
  nextBtn.disabled = true;
  pager.append(pagerInfo, prevBtn, nextBtn);

  const toolbarChildren = [deptMulti.el, stageMulti.el];
  if (modelWrap) toolbarChildren.push(modelWrap);
  toolbarChildren.push(stateSelect, applyBtn, clearBtn, spacer, pager);
  toolbar.append(...toolbarChildren);
  section.appendChild(toolbar);

  // Table
  const tableWrap = overviewEl("div", "overview-table-wrap");
  const table = overviewEl("table", "analysis-items-table");
  const thead = overviewEl("thead");
  const trHead = overviewEl("tr");
  ["编号", "名称", "科室", "负责人", "阶段", "状态", "待签署人员", "申请日期", "提醒"].forEach((col) => {
    trHead.appendChild(overviewEl("th", null, col));
  });
  thead.appendChild(trHead);
  table.appendChild(thead);

  const tbody = overviewEl("tbody");
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  section.appendChild(tableWrap);

  async function fetchAndRender() {
    const seq = ++currentSeq;
    clearOverviewContainer(tbody);
    const loadingTr = overviewEl("tr");
    const loadingTd = overviewEl("td", "analysis-empty-note", "加载明细任务中...");
    loadingTd.colSpan = 9;
    loadingTd.style.textAlign = "center";
    loadingTd.style.padding = "20px";
    loadingTr.appendChild(loadingTd);
    tbody.appendChild(loadingTr);

    const offset = (state.page - 1) * PAGE_SIZE;
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String(offset),
    });
    state.departments.forEach((department) => params.append("departments", department));
    if (state.state && state.state !== "all") {
      params.set("state", state.state);
    }
    state.stages.forEach((stage) => params.append("stages", stage));
    if (analysisModelFilter.model) {
      params.set("model", analysisModelFilter.model);
      params.set("modelMatch", analysisModelFilter.match);
    }

    try {
      const res = await fetch(
        `/api/project-status/deliverables/${encodeURIComponent(item.id)}/analysis/items?${params.toString()}`,
        {
          headers: { Accept: "application/json" },
          cache: "no-store",
        }
      );
      const body = await overviewReadJson(res);
      if (seq !== currentSeq) return;
      if (!res.ok || !body || body.ok !== true) {
        throw overviewRequestError(body, res.status);
      }
      const data = body.data || { items: [], total: 0 };
      renderRows(data);
    } catch (err) {
      if (seq !== currentSeq) return;
      clearOverviewContainer(tbody);
      const errTr = overviewEl("tr");
      const errTd = overviewEl("td", "analysis-empty-note is-error", formatApiErrorMessage(err, 500));
      errTd.colSpan = 9;
      errTd.style.textAlign = "center";
      errTd.style.padding = "20px";
      errTr.appendChild(errTd);
      tbody.appendChild(errTr);
    }
  }

  function renderRows(data) {
    totalItems = Number(data.total) || 0;
    const items = Array.isArray(data.items) ? data.items : [];
    const totalPages = Math.max(1, Math.ceil(totalItems / PAGE_SIZE));

    if (state.page > totalPages) {
      state.page = totalPages;
      fetchAndRender();
      return;
    }

    titleEl.textContent = `明细任务清单 (共 ${totalItems} 条)`;
    pagerInfo.textContent = `共 ${totalItems} 条 · 第 ${state.page} / ${totalPages} 页`;
    prevBtn.disabled = state.page <= 1;
    nextBtn.disabled = state.page >= totalPages || totalItems === 0;

    clearOverviewContainer(tbody);
    if (items.length === 0) {
      const emptyTr = overviewEl("tr");
      const emptyTd = overviewEl("td", "analysis-empty-note is-empty", "暂无明细任务记录");
      emptyTd.colSpan = 9;
      emptyTd.style.textAlign = "center";
      emptyTd.style.padding = "20px";
      emptyTr.appendChild(emptyTd);
      tbody.appendChild(emptyTr);
      return;
    }

    items.forEach((it) => {
      const tr = overviewEl("tr");

      // 编号
      tr.appendChild(overviewEl("td", null, safeDisplayValue(it.itemNumber || "未提供")));
      // 名称
      tr.appendChild(overviewEl("td", null, safeDisplayValue(it.title)));
      // 科室
      tr.appendChild(overviewEl("td", null, safeDisplayValue(it.department)));
      // 负责人
      tr.appendChild(overviewEl("td", null, safeDisplayValue(it.owner)));

      // EWO 流程阶段（接口值为小写，显示统一大写）
      const stageTd = overviewEl("td");
      const stageChip = overviewEl("span", "analysis-stage-chip");
      if (it.stage) {
        stageChip.textContent = safeDisplayValue(formatEwoStageLabel(it.stage));
        if (it.stage === "close") {
          stageChip.className = "analysis-stage-chip is-closed";
        } else if (it.stage === "open") {
          stageChip.className = "analysis-stage-chip is-open";
        } else {
          stageChip.className = "analysis-stage-chip is-active";
        }
      } else if (it.stageAttention) {
        stageChip.textContent = "未知阶段";
        stageChip.className = "analysis-stage-chip is-unknown";
        stageChip.title = "来源阶段未识别，默认不计入统计";
      } else {
        stageChip.textContent = "—";
        stageChip.className = "analysis-stage-chip is-none";
      }
      stageTd.appendChild(stageChip);
      tr.appendChild(stageTd);

      // 状态列只表达提醒状态：超期/未超期；阶段信息在上一列展示。
      const statusTd = overviewEl("td");
      const chip = overviewEl("span", "analysis-status-chip");
      const isOverdue = it.alertType === "overdue";
      chip.textContent = isOverdue ? "超期" : "未超期";
      chip.className = `analysis-status-chip ${isOverdue ? "is-overdue" : "is-normal"}`;
      statusTd.appendChild(chip);
      tr.appendChild(statusTd);

      // 待签署人员：按角色逐行显示（ROLE:person），无值显示 无。
      const signersTd = overviewEl("td", "analysis-signers-cell");
      const signerLines = String(it.pendingSigners || "")
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);
      if (signerLines.length === 0) {
        signersTd.appendChild(overviewEl("span", "analysis-signers-empty", "无"));
      } else {
        signerLines.forEach((line) => {
          signersTd.appendChild(overviewEl("div", "analysis-signer-line", safeDisplayValue(line)));
        });
        signersTd.title = signerLines.map((line) => safeDisplayValue(line)).join("\n");
      }
      tr.appendChild(signersTd);

      // 申请日期
      tr.appendChild(overviewEl("td", null, safeDisplayValue(it.plannedDate)));

      // 提醒
      let alertLabel = "—";
      let alertClass = "is-normal";
      if (it.alertType === "overdue") {
        alertLabel = `逾期 ${it.days ?? ""}天`;
        alertClass = "is-overdue";
      } else if (it.alertType === "due_soon") {
        alertLabel = `${it.days ?? ""}天后到期`;
        alertClass = "is-due-soon";
      } else if (it.alertType === "missing_due_date") {
        alertLabel = "缺少截止日期";
        alertClass = "is-warning";
      }
      const alertTd = overviewEl("td", null, alertLabel);
      if (alertClass !== "is-normal") {
        alertTd.className = `analysis-alert-cell ${alertClass}`;
      }
      tr.appendChild(alertTd);

      tbody.appendChild(tr);
    });
  }

  function markFiltersDirty() {
    filtersDirty = true;
    applyBtn.classList.add("is-attention");
  }

  deptMulti.setOnChange((values) => {
    markFiltersDirty();
    if (onDeptChange) onDeptChange(values.length === 1 ? values[0] : null);
  });
  stageMulti.setOnChange(markFiltersDirty);
  stateSelect.addEventListener("change", () => {
    pendingState = stateSelect.value;
    markFiltersDirty();
  });

  applyBtn.addEventListener("click", () => {
    const previousModel = analysisModelFilter.model;
    const previousMatch = analysisModelFilter.match;
    if (modelInput) {
      analysisModelFilter.model = modelInput.value.trim();
    }
    state.departments = deptMulti.getValues();
    state.stages = stageMulti.getValues();
    state.state = pendingState;
    state.page = 1;
    filtersDirty = false;
    applyBtn.classList.remove("is-attention");
    // 车型筛选变化时重载整个分析面板，统计摘要/图表与明细保持同口径。
    if (
      typeof options.onModelChange === "function"
      && (analysisModelFilter.model !== previousModel || analysisModelFilter.match !== previousMatch)
    ) {
      options.onModelChange();
      return;
    }
    fetchAndRender();
  });

  clearBtn.addEventListener("click", () => {
    const hadModel = Boolean(analysisModelFilter.model) || analysisModelFilter.match !== "fuzzy";
    deptMulti.clear();
    stageMulti.clear();
    stateSelect.value = "all";
    pendingState = "all";
    state.departments = [];
    state.stages = [];
    state.state = "all";
    state.page = 1;
    filtersDirty = false;
    applyBtn.classList.remove("is-attention");
    if (modelInput) modelInput.value = "";
    analysisModelFilter.model = "";
    analysisModelFilter.match = "fuzzy";
    matchButtons.forEach((button) => {
      const isActive = button.dataset.match === "fuzzy";
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
    if (typeof options.onModelChange === "function" && hadModel) {
      options.onModelChange();
      return;
    }
    fetchAndRender();
  });

  prevBtn.addEventListener("click", () => {
    if (state.page > 1) {
      state.page -= 1;
      fetchAndRender();
    }
  });

  nextBtn.addEventListener("click", () => {
    const totalPages = Math.max(1, Math.ceil(totalItems / PAGE_SIZE));
    if (state.page < totalPages) {
      state.page += 1;
      fetchAndRender();
    }
  });

  // Initial load
  fetchAndRender();

  return {
    el: section,
    setSelected: (dept) => {
      deptMulti.setValues(dept ? [dept] : []);
      state.departments = dept ? [dept] : [];
      state.page = 1;
      fetchAndRender();
    },
  };
}

// 分组成员文本框解析：英文/中文逗号、顿号、分号均可分隔，去空白去空项。
function splitChartGroupMembers(text) {
  return String(text || "")
    .split(/[,，、;；]/)
    .map((member) => member.trim())
    .filter(Boolean);
}

// 图表内容设置编辑器：标签名 + 绑定字段 + 分组定义（值映射）+ 未匹配三选，
// PUT 整体替换后重载分析面板。
function buildChartLabelEditor(container, itemId, labels, fieldOptions, onSaved) {
  container.textContent = "";
  const rowsBox = overviewEl("div", "chart-label-rows");
  const status = overviewEl("p", "chart-labels-status");
  status.setAttribute("role", "status");

  const addLabelBlock = (label = "", field = "", groups = [], unmatched = "keep") => {
    const block = overviewEl("div", "chart-label-block");
    const mainRow = overviewEl("div", "chart-label-row");

    const nameInput = overviewEl("input", "chart-label-name");
    nameInput.type = "text";
    nameInput.value = safeDisplayValue(label);
    nameInput.placeholder = "标签名称，如 内容A";
    nameInput.maxLength = 40;
    nameInput.setAttribute("aria-label", "图表标签名称");

    const fieldSelect = overviewEl("select", "chart-label-field-select");
    fieldSelect.setAttribute("aria-label", "绑定字段");
    fieldOptions.forEach(([key, display]) => {
      const option = document.createElement("option");
      option.value = key;
      option.textContent = display;
      if (key === field) option.selected = true;
      fieldSelect.appendChild(option);
    });

    const groupsBox = overviewEl("div", "chart-label-groups");
    groupsBox.hidden = true;
    const addRuleBtn = overviewEl("button", "chart-group-add-btn", "添加分组");
    addRuleBtn.type = "button";
    const unmatchedSelect = overviewEl("select", "chart-label-unmatched");
    unmatchedSelect.setAttribute("aria-label", "未匹配值处理");
    [
      ["keep", "未匹配保留原样"],
      ["other", "未匹配并入未分组"],
      ["hide", "未匹配从图表隐藏"],
    ].forEach(([value, text]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = text;
      if (value === unmatched) option.selected = true;
      unmatchedSelect.appendChild(option);
    });
    groupsBox.append(addRuleBtn, unmatchedSelect);

    const addGroupRule = (name = "", membersText = "") => {
      const rule = overviewEl("div", "chart-group-rule");
      const groupName = overviewEl("input", "chart-group-name");
      groupName.type = "text";
      groupName.value = safeDisplayValue(name);
      groupName.placeholder = "组名，如 内饰科";
      groupName.maxLength = 40;
      groupName.setAttribute("aria-label", "分组名称");
      const membersInput = overviewEl("input", "chart-group-members");
      membersInput.type = "text";
      membersInput.value = safeDisplayValue(membersText);
      membersInput.placeholder = "成员用逗号分隔，如 内饰科,内饰工程科";
      membersInput.setAttribute("aria-label", "分组成员");
      const removeRule = overviewEl("button", "chart-group-rule-remove", "移除");
      removeRule.type = "button";
      removeRule.setAttribute("aria-label", "移除该分组");
      removeRule.addEventListener("click", () => rule.remove());
      rule.append(groupName, membersInput, removeRule);
      // 新规则始终插在"添加分组"按钮之前，避免按钮被夹在规则中间。
      groupsBox.insertBefore(rule, addRuleBtn);
    };
    (Array.isArray(groups) ? groups : []).forEach((rule) => {
      addGroupRule(
        rule && rule.name ? String(rule.name) : "",
        Array.isArray(rule && rule.members) ? rule.members.join("、") : "",
      );
    });
    addRuleBtn.addEventListener("click", () => addGroupRule());

    const groupsToggle = overviewEl("button", "chart-label-groups-toggle", "配置分组");
    groupsToggle.type = "button";
    groupsToggle.setAttribute("aria-expanded", "false");
    groupsToggle.addEventListener("click", () => {
      groupsBox.hidden = !groupsBox.hidden;
      groupsToggle.textContent = groupsBox.hidden ? "配置分组" : "收起分组";
      groupsToggle.setAttribute("aria-expanded", groupsBox.hidden ? "false" : "true");
    });

    const removeBtn = overviewEl("button", "chart-label-remove", "移除");
    removeBtn.type = "button";
    removeBtn.setAttribute("aria-label", "移除该标签");
    removeBtn.addEventListener("click", () => block.remove());

    mainRow.append(nameInput, fieldSelect, groupsToggle, removeBtn);
    block.append(mainRow, groupsBox);
    rowsBox.appendChild(block);
  };

  (Array.isArray(labels) ? labels : []).forEach((entry) => {
    addLabelBlock(
      entry && entry.label ? String(entry.label) : "",
      entry && entry.sourceField ? String(entry.sourceField) : "",
      entry && Array.isArray(entry.groups) ? entry.groups : [],
      entry && entry.unmatched ? String(entry.unmatched) : "keep",
    );
  });

  const addBtn = overviewEl("button", "chart-label-add-btn", "添加标签");
  addBtn.type = "button";
  addBtn.addEventListener("click", () => addLabelBlock());
  const saveBtn = overviewEl("button", "chart-labels-save-btn", "保存图表设置");
  saveBtn.type = "button";
  const cancelBtn = overviewEl("button", "chart-labels-cancel-btn", "取消");
  cancelBtn.type = "button";
  cancelBtn.addEventListener("click", () => {
    container.hidden = true;
  });
  saveBtn.addEventListener("click", async () => {
    const blocks = Array.from(rowsBox.querySelectorAll(".chart-label-block"));
    const payload = blocks
      .map((block) => {
        const groupRules = Array.from(block.querySelectorAll(".chart-group-rule"))
          .map((rule) => ({
            name: rule.querySelector(".chart-group-name").value.trim(),
            members: splitChartGroupMembers(rule.querySelector(".chart-group-members").value),
          }))
          .filter((rule) => rule.name || rule.members.length > 0);
        const unmatchedMode = block.querySelector(".chart-label-unmatched").value;
        return {
          label: block.querySelector(".chart-label-name").value,
          sourceField: block.querySelector(".chart-label-field-select").value,
          groups: groupRules,
          unmatched: unmatchedMode,
        };
      })
      .filter((entry) => entry.label.trim() || entry.sourceField);
    saveBtn.disabled = true;
    updatePolicyStatusMessage(status, "正在保存图表设置...");
    try {
      const res = await fetch(`/api/project-status/deliverables/${encodeURIComponent(itemId)}/chart-labels`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ labels: payload }),
      });
      const body = await overviewReadJson(res);
      if (!res.ok || !body || body.ok !== true) throw overviewRequestError(body, res.status);
      container.hidden = true;
      if (typeof onSaved === "function") onSaved();
    } catch (err) {
      updatePolicyStatusMessage(status, err instanceof Error ? err.message : String(err), true);
      saveBtn.disabled = false;
    }
  });

  container.append(rowsBox, addBtn, saveBtn, cancelBtn, status);
}

// 自定义标签图：按标签绑定的 EWO 字段分组，复用科室图组件；点击不做科室联动。
function renderCustomLabelChart(chart) {
  const groups = chart && chart.groups && typeof chart.groups === "object" ? chart.groups : {};
  const totals = Object.values(groups).reduce(
    (acc, counts) => ({
      total: acc.total + (Number(counts && counts.total) || 0),
      completed: acc.completed + (Number(counts && counts.completed) || 0),
      incomplete: acc.incomplete + (Number(counts && counts.incomplete) || 0),
    }),
    { total: 0, completed: 0, incomplete: 0 },
  );
  // renderDepartmentDoneChart 返回 {el, setSelected} 包装对象，必须取 .el，
  // 否则 appendChild 收到非 Node 导致整个分析面板渲染中断。
  const rendered = renderDepartmentDoneChart(totals, groups, null, {
    title: `按「${safeDisplayValue(chart && chart.label)}」分组（已完成 / 未完成）`,
  });
  return rendered.el;
}

function renderDeliverableAnalysisActionBar(item, options = {}) {
  if (options.showAnalysisActions !== true) return null;

  const syncSupported = !["VPI-T2-D1", "VPI-T2-D4"].includes(item.id);
  const syncState = options.analysisSyncReadiness || null;
  let syncReady = Boolean(syncState && syncState.ready === true);
  let syncReadinessMessage = syncState && syncState.message
    ? String(syncState.message)
    : "正在读取同步前置条件";
  let syncBusy = false;
  let feedbackText = "";
  let feedbackTone = "";

  const analysisActionBar = overviewEl("div", "evidence-sync-bar analysis-action-bar");
  analysisActionBar.setAttribute("aria-label", `${safeDisplayValue(item.name)} 分析操作`);
  analysisActionBar.appendChild(overviewEl("strong", "analysis-action-label", "分析操作"));

  const refreshButton = overviewEl("button", "evidence-retry-btn analysis-refresh-btn", "刷新分析");
  refreshButton.type = "button";
  refreshButton.addEventListener("click", () => {
    if (typeof options.onRefresh === "function") options.onRefresh();
  });

  const syncButton = overviewEl("button", "evidence-sync-btn analysis-sync-btn", "后台同步");
  syncButton.type = "button";
  syncButton.dataset.deliverableId = item.id;

  const syncStatus = overviewEl("span", "evidence-sync-status analysis-sync-status");
  syncStatus.setAttribute("role", "status");
  syncStatus.setAttribute("aria-live", "polite");

  function setSyncStatus(text, tone = "") {
    feedbackText = String(text || "");
    feedbackTone = tone;
    syncStatus.textContent = feedbackText;
    syncStatus.className = `evidence-sync-status analysis-sync-status${feedbackTone ? ` is-${feedbackTone}` : ""}`;
  }

  function setSyncReadiness(ready, message = "") {
    syncReady = Boolean(ready);
    syncReadinessMessage = String(message || (syncReady ? "" : "同步条件尚未满足"));
    syncButton.disabled = syncBusy || !syncSupported || !syncReady;
    syncButton.title = syncReady && syncSupported
      ? ""
      : `不可同步：${syncSupported ? syncReadinessMessage : "该交付物不支持外部同步"}`;
    if (syncReady && feedbackText.startsWith("暂不能同步：")) {
      setSyncStatus("", "");
    } else if (!syncReady && (!feedbackText || feedbackText.startsWith("暂不能同步："))) {
      setSyncStatus(
        syncSupported
          ? `暂不能同步：${syncReadinessMessage || "同步条件尚未满足"}`
          : "该交付物不支持外部同步",
        "warning",
      );
    }
  }

  function setBusy(busy) {
    syncBusy = Boolean(busy);
    syncButton.disabled = syncBusy || !syncSupported || !syncReady;
    refreshButton.disabled = syncBusy;
  }

  syncButton.addEventListener("click", () => {
    if (!syncReady || !syncSupported) {
      setSyncStatus(
        syncSupported
          ? `暂不能同步：${syncReadinessMessage || "同步条件尚未满足"}`
          : "该交付物不支持外部同步",
        "warning",
      );
      return;
    }
    if (typeof options.onSync === "function") options.onSync();
  });

  const controller = {
    el: analysisActionBar,
    setSyncStatus,
    setSyncReadiness,
    setBusy,
  };
  setSyncReadiness(syncReady, syncReadinessMessage);
  if (!syncSupported) setSyncStatus("该交付物不支持外部同步", "warning");
  if (syncState && typeof syncState.attach === "function") syncState.attach(controller);
  analysisActionBar.append(refreshButton, syncButton, syncStatus);
  return controller;
}

function renderDeliverableAnalysis(container, item, analysisData, options = {}) {
  clearOverviewContainer(container);

  const head = overviewEl("div", "analysis-panel-head");
  const titleGroup = overviewEl("div");
  titleGroup.append(
    overviewEl("p", "eyebrow", "交付物分析"),
    overviewEl("h5", "analysis-title", `${item.name} 各科室完成情况`),
  );
  head.appendChild(titleGroup);

  const snapshotTime = analysisData.snapshotAt
    ? `快照时间: ${archiveFormatDate(analysisData.snapshotAt)}`
    : "暂无分析快照";
  head.appendChild(overviewEl("span", "analysis-snapshot-time", snapshotTime));
  container.appendChild(head);

  const analysisActionBar = renderDeliverableAnalysisActionBar(item, options);
  if (analysisActionBar) container.appendChild(analysisActionBar.el);

  if (!analysisData.hasCache) {
    container.appendChild(overviewEl("p", "analysis-empty-note is-empty", "暂无分析缓存数据（等待定时同步或首次抓取分析）"));
    return;
  }

  const summary = analysisData.summary || {
    total: 0,
    completed: 0,
    incomplete: 0,
    overdue: 0,
    dueSoon: 0,
    missingDueDate: 0,
  };
  const departments = analysisData.departments || {};
  const trend = Array.isArray(analysisData.trend) ? analysisData.trend : [];

  // 1. Summary Metrics & Warning Chips
  const summaryGrid = overviewEl("div", "analysis-summary-grid");
  const metricCards = [
    ["总任务数", String(summary.total ?? 0)],
    ["已完成", String(summary.completed ?? 0)],
    ["未完成", String(summary.incomplete ?? 0)],
  ];
  metricCards.forEach(([label, val]) => {
    const card = overviewEl("div", "analysis-metric-card");
    card.append(overviewEl("span", "analysis-metric-label", label), overviewEl("strong", "analysis-metric-val", val));
    summaryGrid.appendChild(card);
  });

  const alertsBox = overviewEl("div", "analysis-alerts-box");
  const overdueCount = summary.overdue ?? 0;
  const dueSoonCount = summary.dueSoon ?? 0;
  const missingDueDateCount = summary.missingDueDate ?? 0;
  if (overdueCount > 0) {
    alertsBox.appendChild(overviewEl("span", "analysis-alert-chip is-overdue", `逾期 ${overdueCount} 项`));
  }
  if (dueSoonCount > 0) {
    alertsBox.appendChild(overviewEl("span", "analysis-alert-chip is-due-soon", `即将到期 ${dueSoonCount} 项`));
  }
  if (missingDueDateCount > 0) {
    alertsBox.appendChild(overviewEl("span", "analysis-alert-chip is-warning", `缺少截止日期 ${missingDueDateCount} 项`));
  }
  if (overdueCount === 0 && dueSoonCount === 0 && missingDueDateCount === 0) {
    alertsBox.appendChild(overviewEl("span", "analysis-alert-chip is-normal", "无逾期风险"));
  }
  summaryGrid.appendChild(alertsBox);
  container.appendChild(summaryGrid);

  // 2. 图表区：默认科室图 + 自定义标签图（tab 切换）+ 图表内容设置。
  let onDeptSelectChange = null;
  const deptSection = renderDepartmentDoneChart(summary, departments, (selectedDept) => {
    if (onDeptSelectChange) {
      onDeptSelectChange(selectedDept);
    }
  });
  const customCharts = Array.isArray(analysisData.customCharts) ? analysisData.customCharts : [];
  const chartTools = overviewEl("div", "analysis-chart-tools");
  const settingsBtn = overviewEl("button", "analysis-chart-settings-btn", "图表内容设置");
  settingsBtn.type = "button";
  settingsBtn.setAttribute("aria-label", "设置图表展示内容");
  const editorBox = overviewEl("div", "chart-labels-editor");
  editorBox.hidden = true;
  chartTools.append(settingsBtn, editorBox);
  container.appendChild(chartTools);
  settingsBtn.addEventListener("click", async () => {
    if (!editorBox.hidden) {
      editorBox.hidden = true;
      return;
    }
    settingsBtn.disabled = true;
    try {
      const res = await fetch(`/api/project-status/deliverables/${encodeURIComponent(item.id)}/chart-labels`, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      const body = await overviewReadJson(res);
      if (!res.ok || !body || body.ok !== true) throw overviewRequestError(body, res.status);
      const data = body.data || {};
      const fieldOptions = (Array.isArray(data.fields) ? data.fields : []).map((field) => [
        String(field.key),
        field.label && field.label !== field.key ? `${field.label}（${field.key}）` : String(field.key),
      ]);
      buildChartLabelEditor(
        editorBox,
        item.id,
        Array.isArray(data.labels) ? data.labels : [],
        fieldOptions,
        () => {
          if (typeof options.onReload === "function") options.onReload();
        },
      );
      editorBox.hidden = false;
    } catch (err) {
      editorBox.textContent = "";
      editorBox.appendChild(overviewEl("p", "error-msg", formatApiErrorMessage(err, 500)));
      editorBox.hidden = false;
    } finally {
      settingsBtn.disabled = false;
    }
  });

  if (customCharts.length === 0) {
    container.appendChild(deptSection.el);
  } else {
    const entries = [
      { label: "科室", el: deptSection.el },
      ...customCharts.map((chart) => ({ label: chart.label, el: renderCustomLabelChart(chart) })),
    ];
    const panels = entries.map((entry, index) => {
      const panel = overviewEl("div", "analysis-chart-panel");
      panel.hidden = index !== 0;
      panel.appendChild(entry.el);
      return panel;
    });
    const tabButtons = entries.map((entry, index) => {
      const tab = overviewEl("button", "analysis-chart-tab", safeDisplayValue(entry.label));
      tab.type = "button";
      tab.setAttribute("aria-pressed", index === 0 ? "true" : "false");
      tab.classList.toggle("is-active", index === 0);
      tab.addEventListener("click", () => {
        tabButtons.forEach((button, i) => {
          const isActive = button === tab;
          button.classList.toggle("is-active", isActive);
          button.setAttribute("aria-pressed", isActive ? "true" : "false");
          panels[i].hidden = !isActive;
        });
      });
      return tab;
    });
    const tabRow = overviewEl("div", "analysis-chart-tabs");
    tabButtons.forEach((tab) => tabRow.appendChild(tab));
    const chartArea = overviewEl("div", "analysis-chart-area");
    chartArea.append(tabRow, ...panels);
    container.appendChild(chartArea);
  }

  // 3. Trend View
  const trendSection = overviewEl("div", "analysis-sub-section");
  trendSection.appendChild(overviewEl("h6", "analysis-sub-title", "历史趋势记录"));
  if (trend.length === 0) {
    trendSection.appendChild(overviewEl("p", "analysis-empty-note is-empty", "暂无历史趋势记录"));
  } else {
    trendSection.appendChild(renderTrendSvgChart(trend));
    const trendTable = overviewEl("table", "analysis-trend-table");
    const thead = overviewEl("thead");
    const trHead = overviewEl("tr");
    ["快照时间", "总任务数", "已完成", "未完成", "逾期", "即将到期"].forEach((col) => {
      trHead.appendChild(overviewEl("th", null, col));
    });
    thead.appendChild(trHead);
    trendTable.appendChild(thead);
    const tbody = overviewEl("tbody");
    trend.forEach((t) => {
      const tr = overviewEl("tr");
      tr.append(
        overviewEl("td", null, archiveFormatDate(t.snapshotAt)),
        overviewEl("td", null, String(t.total ?? 0)),
        overviewEl("td", null, String(t.completed ?? 0)),
        overviewEl("td", null, String(t.incomplete ?? 0)),
        overviewEl("td", null, String(t.overdue ?? 0)),
        overviewEl("td", null, String(t.dueSoon ?? 0)),
      );
      tbody.appendChild(tr);
    });
    trendTable.appendChild(tbody);
    trendSection.appendChild(trendTable);
  }
  container.appendChild(trendSection);

  // 4. Paginated detail table
  const itemsSectionObj = renderAnalysisItemsSection(
    item,
    departments,
    (selectedDept) => {
      deptSection.setSelected(selectedDept);
    },
    { onModelChange: typeof options.onReload === "function" ? options.onReload : null },
  );
  onDeptSelectChange = (selectedDept) => {
    itemsSectionObj.setSelected(selectedDept);
  };
  container.appendChild(itemsSectionObj.el);
}

function renderTrendSvgChart(trend) {
  const container = overviewEl("div", "analysis-trend-chart-wrap");
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "trend-chart-svg");
  svg.setAttribute("viewBox", "0 0 620 220");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "交付物历史趋势图表");

  const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
  title.textContent = "交付物历史趋势图表";
  svg.appendChild(title);

  const desc = document.createElementNS("http://www.w3.org/2000/svg", "desc");
  desc.textContent = "展示快照历史中已完成与未完成任务数量变化趋势";
  svg.appendChild(desc);

  const padding = { top: 30, right: 35, bottom: 40, left: 45 };
  const plotWidth = 620 - padding.left - padding.right;
  const plotHeight = 220 - padding.top - padding.bottom;

  let maxVal = 10;
  trend.forEach((t) => {
    const tot = t.total ?? 0;
    const comp = t.completed ?? 0;
    const incomp = t.incomplete ?? 0;
    maxVal = Math.max(maxVal, tot, comp, incomp);
  });
  maxVal = Math.max(10, Math.ceil(maxVal * 1.15));

  const gridSteps = 4;
  for (let s = 0; s <= gridSteps; s++) {
    const stepVal = Math.round((maxVal / gridSteps) * s);
    const y = padding.top + plotHeight - (s / gridSteps) * plotHeight;
    const gridLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
    gridLine.setAttribute("x1", String(padding.left));
    gridLine.setAttribute("y1", String(y));
    gridLine.setAttribute("x2", String(padding.left + plotWidth));
    gridLine.setAttribute("y2", String(y));
    gridLine.setAttribute("stroke", "var(--hairline, #e5e7eb)");
    gridLine.setAttribute("stroke-width", "1");
    gridLine.setAttribute("stroke-dasharray", s === 0 ? "none" : "2,2");
    svg.appendChild(gridLine);

    const yText = document.createElementNS("http://www.w3.org/2000/svg", "text");
    yText.setAttribute("x", String(padding.left - 8));
    yText.setAttribute("y", String(y + 4));
    yText.setAttribute("text-anchor", "end");
    yText.setAttribute("font-size", "10");
    yText.setAttribute("fill", "var(--muted, #6b7280)");
    yText.textContent = String(stepVal);
    svg.appendChild(yText);
  }

  const compPoints = [];
  const incompPoints = [];
  trend.forEach((t, i) => {
    const x = padding.left + (trend.length === 1 ? plotWidth / 2 : (i / (trend.length - 1)) * plotWidth);
    const compVal = t.completed ?? 0;
    const incompVal = t.incomplete ?? 0;
    const yComp = padding.top + plotHeight - (compVal / maxVal) * plotHeight;
    const yIncomp = padding.top + plotHeight - (incompVal / maxVal) * plotHeight;
    compPoints.push({ x, y: yComp, val: compVal, date: t.snapshotAt });
    incompPoints.push({ x, y: yIncomp, val: incompVal, date: t.snapshotAt });
  });

  if (compPoints.length > 0) {
    const compPoly = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    compPoly.setAttribute("fill", "none");
    compPoly.setAttribute("stroke", "var(--success, #10b981)");
    compPoly.setAttribute("stroke-width", "2.5");
    compPoly.setAttribute("stroke-linecap", "round");
    compPoly.setAttribute("stroke-linejoin", "round");
    compPoly.setAttribute("points", compPoints.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" "));
    svg.appendChild(compPoly);
  }

  if (incompPoints.length > 0) {
    const incompPoly = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    incompPoly.setAttribute("fill", "none");
    incompPoly.setAttribute("stroke", "var(--warning, #f59e0b)");
    incompPoly.setAttribute("stroke-width", "2.5");
    incompPoly.setAttribute("stroke-linecap", "round");
    incompPoly.setAttribute("stroke-linejoin", "round");
    incompPoly.setAttribute("points", incompPoints.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" "));
    svg.appendChild(incompPoly);
  }

  compPoints.forEach((p) => {
    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("cx", String(p.x.toFixed(1)));
    circle.setAttribute("cy", String(p.y.toFixed(1)));
    circle.setAttribute("r", "4");
    circle.setAttribute("fill", "var(--success, #10b981)");
    svg.appendChild(circle);

    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("x", String(p.x.toFixed(1)));
    text.setAttribute("y", String((p.y - 8).toFixed(1)));
    text.setAttribute("text-anchor", "middle");
    text.setAttribute("font-size", "11");
    text.setAttribute("font-weight", "600");
    text.setAttribute("fill", "var(--success, #10b981)");
    text.textContent = `已完成: ${p.val}`;
    svg.appendChild(text);

    const xText = document.createElementNS("http://www.w3.org/2000/svg", "text");
    xText.setAttribute("x", String(p.x.toFixed(1)));
    xText.setAttribute("y", String(padding.top + plotHeight + 18));
    xText.setAttribute("text-anchor", "middle");
    xText.setAttribute("font-size", "10");
    xText.setAttribute("fill", "var(--muted, #6b7280)");
    xText.textContent = archiveFormatDate(p.date);
    svg.appendChild(xText);
  });

  incompPoints.forEach((p) => {
    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("cx", String(p.x.toFixed(1)));
    circle.setAttribute("cy", String(p.y.toFixed(1)));
    circle.setAttribute("r", "4");
    circle.setAttribute("fill", "var(--warning, #f59e0b)");
    svg.appendChild(circle);

    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("x", String(p.x.toFixed(1)));
    text.setAttribute("y", String((p.y + 16).toFixed(1)));
    text.setAttribute("text-anchor", "middle");
    text.setAttribute("font-size", "11");
    text.setAttribute("font-weight", "600");
    text.setAttribute("fill", "var(--warning, #f59e0b)");
    text.textContent = `未完成: ${p.val}`;
    svg.appendChild(text);
  });

  container.appendChild(svg);
  return container;
}

function projectStatusSyncFeedback(data) {
  const result = data && data.result ? data.result : (data || {});
  const finalState = result.finalState || data && data.finalState;
  const outcome = result.outcome || data && data.outcome || finalState;
  const errorMessage = redactSensitiveText(result.errorMessage || data && data.errorMessage || "任务处理中");
  if (finalState === "busy" || outcome === "busy") {
    return { text: `同步进行中：${errorMessage}`, tone: "busy" };
  }
  if (finalState === "success" && outcome === "completed") {
    return { text: "同步完成：成功", tone: "success" };
  }
  if (finalState === "partial" || outcome === "partial") {
    return { text: "同步完成：部分字段已应用", tone: "warning" };
  }
  if (finalState === "needs_attention" || outcome === "needs_attention") {
    return {
      text: `同步需要处理：${redactSensitiveText(result.errorMessage || data && data.errorMessage || "未匹配到唯一候选")}`,
      tone: "warning",
    };
  }
  return {
    text: `同步失败：${redactSensitiveText(result.errorMessage || data && data.errorMessage || (finalState ? `状态 ${finalState}` : "未知状态"))}`,
    tone: "error",
  };
}

function renderEwoSyncSummary(host, item, analysisData, feedbackText = "", feedbackTone = "") {
  clearOverviewContainer(host);
  const summary = analysisData && analysisData.summary ? analysisData.summary : {};
  const policy = item.updatePolicy || {};
  const statusLabels = {
    idle: "空闲",
    running: "同步中",
    success: "成功",
    failed: "失败",
    needs_attention: "需处理",
  };
  const syncState = policy.syncState || "idle";
  const statusText = feedbackText
    || (policy.enabled === false ? "未启用" : (statusLabels[syncState] || "未知"));
  const snapshotText = analysisData && analysisData.snapshotAt
    ? archiveFormatDate(analysisData.snapshotAt)
    : "暂无快照";

  const titleRow = overviewEl("div", "ewo-sync-summary-head");
  titleRow.append(
    overviewEl("h6", "section-sub-title", "EWO 同步摘要"),
    overviewEl("span", `ewo-sync-summary-status${feedbackTone ? ` is-${feedbackTone}` : ""}`, statusText),
  );
  const meta = overviewEl("div", "ewo-sync-summary-meta");
  meta.append(
    overviewEl("span", null, `最近同步状态：${statusText}`),
    overviewEl("span", null, `最近同步时间：${snapshotText}`),
  );
  const metrics = overviewEl("div", "ewo-sync-summary-metrics");
  [
    ["总数", summary.total ?? 0],
    ["已完成", summary.completed ?? 0],
    ["未完成", summary.incomplete ?? 0],
    ["逾期", summary.overdue ?? 0],
  ].forEach(([label, value]) => {
    const metric = overviewEl("div", "ewo-sync-summary-metric");
    metric.append(
      overviewEl("span", "detail-property-label", label),
      overviewEl("strong", "detail-property-value", String(value)),
    );
    metrics.appendChild(metric);
  });
  // 摘要与手工进度来源不同：明确标注统计来自最近一次 EWO 快照，
  // 不覆盖 item.progress 等手工字段。
  const sourceNote = overviewEl("p", "ewo-sync-summary-source", "统计来自最近一次 EWO 快照");
  host.append(titleRow, meta, metrics, sourceNote);
}

function renderDeliverableStatusChart(item, actions = {}) {
  const chart = overviewEl("section", "deliverable-current-status-chart");
  chart.setAttribute("role", "region");
  chart.setAttribute("aria-label", `${safeDisplayValue(item.name)} 当前状态图表`);

  const head = overviewEl("div", "deliverable-current-status-head");
  head.append(
    overviewEl("h6", "section-sub-title", "当前状态图表"),
    overviewEl("span", `status-text is-${deliverableTone(item)}`, safeDisplayValue(item.status || "未设置")),
  );

  const numericProgress = Number(item.progress);
  const hasProgress = item.progress !== null
    && item.progress !== undefined
    && Number.isFinite(numericProgress);
  const progress = hasProgress
    ? Math.min(Math.max(numericProgress, 0), 100)
    : (item.status === "已完成" ? 100 : 0);
  const progressLabel = hasProgress || item.status === "已完成" ? `${progress}%` : "未设置";

  const progressBox = overviewEl("div", "deliverable-current-status-progress");
  const progressLabelRow = overviewEl("div", "deliverable-current-status-label");
  progressLabelRow.append(
    overviewEl("span", null, "项目手工进度"),
    overviewEl("strong", null, progressLabel),
  );
  const track = overviewEl("div", "analysis-chart-track");
  track.setAttribute("role", "progressbar");
  track.setAttribute("aria-valuemin", "0");
  track.setAttribute("aria-valuemax", "100");
  if (hasProgress || item.status === "已完成") track.setAttribute("aria-valuenow", String(progress));
  const fill = overviewEl("div", `analysis-chart-fill${item.status === "已完成" ? " is-completed" : ""}`);
  fill.style.width = `${progress}%`;
  track.appendChild(fill);
  progressBox.append(progressLabelRow, track);

  const timeline = overviewEl("div", "deliverable-current-status-timeline");
  [
    ["计划完成日期", item.plannedDate || "未设置"],
    ["实际完成日期", item.actualDate || "未完成"],
  ].forEach(([label, value]) => {
    const cell = overviewEl("div", "deliverable-current-status-date");
    cell.append(
      overviewEl("span", "detail-property-label", label),
      overviewEl("strong", "detail-property-value", safeDisplayValue(value)),
    );
    timeline.appendChild(cell);
  });

  chart.append(head, progressBox, timeline);

  const isEwo = /ewo/i.test(String(item.source || ""));
  let ewoHost = null;
  let ewoData = null;
  let feedbackText = "";
  let feedbackTone = "";
  let interactiveButton = null;
  let refreshButton = null;
  let syncBusy = false;
  let syncReady = !isEwo;
  let syncReadinessMessage = isEwo ? "正在读取同步前置条件" : "";
  if (isEwo) {
    ewoHost = overviewEl("section", "ewo-sync-summary");
    ewoHost.setAttribute("aria-live", "polite");
    renderEwoSyncSummary(ewoHost, item, null);
    const actionsRow = overviewEl("div", "ewo-sync-summary-actions");
    interactiveButton = overviewEl(
      "button",
      "btn is-primary ewo-interactive-refresh-btn",
      "立即刷新（交互式查询）",
    );
    interactiveButton.type = "button";
    interactiveButton.dataset.queryMode = "interactive";
    refreshButton = overviewEl("button", "btn is-secondary ewo-sync-refresh-btn", "刷新后台分析");
    refreshButton.type = "button";
    interactiveButton.addEventListener("click", () => {
      if (actions.onInteractiveRefresh) actions.onInteractiveRefresh();
    });
    refreshButton.addEventListener("click", () => {
      if (actions.onRefresh) actions.onRefresh();
    });
    actionsRow.append(interactiveButton, refreshButton);
    ewoHost.appendChild(actionsRow);
    chart.appendChild(ewoHost);
  }

  function updateEwoSummary(data) {
    if (!ewoHost) return;
    ewoData = data || null;
    renderEwoSyncSummary(ewoHost, item, ewoData, feedbackText, feedbackTone);
    const actionsRow = overviewEl("div", "ewo-sync-summary-actions");
    actionsRow.append(interactiveButton, refreshButton);
    ewoHost.appendChild(actionsRow);
  }

  function setSyncStatus(text, tone = "") {
    feedbackText = String(text || "");
    feedbackTone = tone;
    if (ewoHost) updateEwoSummary(ewoData);
    if (interactiveButton) {
      interactiveButton.setAttribute(
        "aria-label",
        feedbackText ? `立即刷新（交互式查询，${feedbackText}）` : "立即刷新（交互式查询）",
      );
    }
  }

  function setSyncReadiness(ready, message = "") {
    syncReady = Boolean(ready);
    syncReadinessMessage = String(message || "");
  }

  function getSyncReadiness() {
    return {
      ready: !isEwo || syncReady,
      message: syncReadinessMessage || "同步条件尚未满足",
    };
  }

  function setBusy(busy) {
    syncBusy = Boolean(busy);
    if (interactiveButton) interactiveButton.disabled = syncBusy;
    if (refreshButton) refreshButton.disabled = Boolean(busy);
    chart.classList.toggle("is-sync-busy", Boolean(busy));
  }

  return {
    el: chart,
    updateEwoSummary,
    setSyncStatus,
    setSyncReadiness,
    getSyncReadiness,
    setBusy,
  };
}

async function runDeliverableSyncFromAnalysis(
  item,
  analysisSyncReadiness,
  analysisPanel,
  statusChart,
  analysisOptions = {},
) {
  if (!analysisSyncReadiness || !analysisSyncReadiness.ready) {
    if (analysisSyncReadiness) {
      analysisSyncReadiness.setStatus(
        `暂不能同步：${analysisSyncReadiness.message || "同步条件尚未满足"}`,
        "warning",
      );
    }
    return;
  }
  if (!window.confirm(`确定要执行后台同步 ${item.name} 吗？`)) return;
  analysisSyncReadiness.setBusy(true);
  analysisSyncReadiness.setStatus("正在执行后台同步...", "busy");
  try {
    const data = await requestProjectStatusSync(item);
    const feedback = projectStatusSyncFeedback(data);
    const loaded = await loadDeliverableAnalysis(analysisPanel, item, statusChart, analysisOptions);
    if (loaded) analysisSyncReadiness.setStatus(feedback.text, feedback.tone);
  } catch (err) {
    analysisSyncReadiness.setStatus(
      `同步失败：${redactSensitiveText(err instanceof Error ? err.message : String(err))}`,
      "error",
    );
  } finally {
    analysisSyncReadiness.setBusy(false);
  }
}

async function refreshDeliverableAnalysisFromAnalysis(
  item,
  analysisSyncReadiness,
  analysisPanel,
  statusChart,
  analysisOptions = {},
) {
  if (!analysisSyncReadiness) return;
  analysisSyncReadiness.setBusy(true);
  analysisSyncReadiness.setStatus("正在刷新分析...", "busy");
  try {
    const loaded = await loadDeliverableAnalysis(analysisPanel, item, statusChart, analysisOptions);
    analysisSyncReadiness.setStatus(
      loaded ? "刷新完成" : "刷新失败：分析数据读取失败",
      loaded ? "success" : "error",
    );
  } finally {
    analysisSyncReadiness.setBusy(false);
  }
}

function buildEwoInteractiveQuerySpec(policy = {}, item = {}) {
  const matchRule = policy && policy.matchRule && typeof policy.matchRule === "object"
    ? policy.matchRule
    : {};
  const fieldMap = {
    ewoNo: "ewo_no",
    projectCode: "project_code",
    subjectKeyword: "subject_keyword",
    modelInfo: "model_info",
  };
  const filters = {};
  Object.entries(fieldMap).forEach(([policyKey, filterKey]) => {
    const value = interactiveFilterValue(matchRule[policyKey]);
    if (value) filters[filterKey] = value;
  });
  if (!Object.keys(filters).length) {
    const externalKey = interactiveFilterValue(policy && policy.externalKey);
    if (/^EWO[-_]/i.test(externalKey)) filters.ewo_no = externalKey;
  }
  return {
    filters,
    targetKey: filters.ewo_no || "",
    fallbackLabel: safeDisplayValue(item && item.name),
  };
}

async function runEwoInteractiveRefreshFromStatusChart(
  item,
  statusChart,
  resultHost,
  policyProvider = null,
) {
  if (!statusChart || !resultHost) return;
  if (!window.confirm(`确定要立即刷新 ${item.name} 吗？`)) return;
  const policy = typeof policyProvider === "function" ? policyProvider() : {};
  const spec = buildEwoInteractiveQuerySpec(policy, item);
  statusChart.setBusy(true);
  statusChart.setSyncStatus("正在执行交互式查询...", "busy");
  try {
    const data = await requestInteractiveArasQuery("ewo", spec.filters);
    renderInteractiveArasResult(resultHost, "ewo", data, spec.targetKey);
    const resultState = formatInteractiveArasResult(data, spec.targetKey);
    statusChart.setSyncStatus(`交互式查询完成：${resultState.text}`, resultState.tone);
  } catch (err) {
    const message = formatInteractiveArasError(err, err && err.status);
    statusChart.setSyncStatus(message, err && err.code === "unauthenticated" ? "warning" : "error");
  } finally {
    statusChart.setBusy(false);
  }
}

async function refreshEwoAnalysisFromStatusChart(item, statusChart, analysisPanel, analysisOptions = {}) {
  if (!statusChart) return;
  statusChart.setBusy(true);
  statusChart.setSyncStatus("正在刷新后台分析...", "busy");
  try {
    const loaded = await loadDeliverableAnalysis(analysisPanel, item, statusChart, analysisOptions);
    if (loaded) statusChart.setSyncStatus("刷新完成", "success");
  } catch (err) {
    statusChart.setSyncStatus(
      `刷新失败：${redactSensitiveText(err instanceof Error ? err.message : String(err))}`,
      "error",
    );
  } finally {
    statusChart.setBusy(false);
  }
}

function buildPaaInteractiveFilters(filters = {}) {
  const source = filters && typeof filters === "object" && !Array.isArray(filters)
    ? filters
    : {};
  const fieldMap = {
    paaNo: "paa_no",
    ewoNo: "ewo_no",
    state: "state",
    area: "area",
    base: "base",
    department: "department",
    vehicleKeyword: "vehicle_keyword",
    submitStart: "submit_start",
    submitEnd: "submit_end",
    materialRequestStart: "mtl_rq_start",
    materialRequestEnd: "mtl_rq_end",
  };
  const result = {};
  Object.entries(fieldMap).forEach(([sourceKey, filterKey]) => {
    const value = interactiveFilterValue(source[sourceKey] ?? source[filterKey]);
    if (value) result[filterKey] = value;
  });
  return result;
}

async function runPaaInteractiveRefresh(job, button, resultHost, statusMessage) {
  if (!job || !button || !resultHost) return;
  button.disabled = true;
  button.textContent = "交互式查询中...";
  statusMessage.textContent = "正在执行交互式查询...";
  try {
    const filters = buildPaaInteractiveFilters(job.filters || {});
    const targetKey = interactiveFilterValue(job.filters && job.filters.paaNo);
    const data = await requestInteractiveArasQuery("paa", filters);
    renderInteractiveArasResult(resultHost, "paa", data, targetKey);
    const resultState = formatInteractiveArasResult(data, targetKey);
    statusMessage.textContent = `交互式查询完成：${resultState.text}`;
  } catch (error) {
    statusMessage.textContent = formatInteractiveArasError(error, error && error.status);
  } finally {
    button.disabled = false;
    button.textContent = "立即刷新（交互式查询）";
  }
}

function renderDeliverableDetailPage(deliverableId) {
  const container = document.getElementById("overview-deliverable-detail-view");
  const listView = document.getElementById("overview-deliverables-list-view");
  if (!container) return;

  if (listView) listView.hidden = true;
  container.hidden = false;
  clearOverviewContainer(container);

  if (!overviewSavedState || !overviewSavedState.deliverables) {
    const loadingP = overviewEl("p", "loading", "加载交付物明细与分析...");
    container.appendChild(loadingP);
    return;
  }

  const itemIndex = overviewSavedState.deliverables.findIndex((d) => d.id === deliverableId);
  const item = itemIndex >= 0 ? overviewSavedState.deliverables[itemIndex] : null;

  if (!item) {
    const box = overviewEl("div", "deliverable-detail-not-found");
    box.appendChild(overviewEl("p", "error-msg", `未找到编号为 "${safeDisplayValue(deliverableId)}" 的交付物`));
    const backBtn = overviewEl("button", "segment back-to-list-btn", "返回交付物列表");
    backBtn.type = "button";
    backBtn.addEventListener("click", () => {
      location.hash = "#overview";
    });
    box.appendChild(backBtn);
    container.appendChild(box);
    return;
  }

  const page = overviewEl("article", "deliverable-detail-page");

  // 切换交付物详情时重置车型筛选，避免上一个交付物的查找条件残留。
  analysisModelFilter.model = "";
  analysisModelFilter.match = "fuzzy";

  const head = overviewEl("div", "deliverable-detail-page-head");
  const headNav = overviewEl("div", "deliverable-detail-page-nav");
  const backBtn = overviewEl("button", "segment back-to-list-btn", "← 返回交付物列表");
  backBtn.type = "button";
  backBtn.setAttribute("aria-label", "返回交付物列表");
  backBtn.addEventListener("click", () => {
    location.hash = "#overview";
  });
  headNav.appendChild(backBtn);
  head.appendChild(headNav);

  const headTitleRow = overviewEl("div", "deliverable-detail-title-row");
  const titleGroup = overviewEl("div");
  titleGroup.append(
    overviewEl("p", "eyebrow", "交付物明细"),
    overviewEl("h3", "deliverable-page-title", item.name),
    overviewEl("span", "deliverable-page-id", `ID: ${safeDisplayValue(item.displayCode || item.id)}`),
  );
  headTitleRow.appendChild(titleGroup);

  const detailEditPanel = overviewEl("section", "detail-page-edit-panel");
  detailEditPanel.hidden = true;
  detailEditPanel.setAttribute("aria-label", `${item.name} 编辑表单`);

  const headStatusGroup = overviewEl("div", "deliverable-page-status-group");
  headStatusGroup.appendChild(overviewEl("span", `status-text is-${deliverableTone(item)}`, item.status));
  const editButton = overviewEl("button", "detail-edit", null);
  editButton.type = "button";
  const editLabel = `编辑 ${item.name}`;
  editButton.title = editLabel;
  editButton.setAttribute("aria-label", editLabel);
  editButton.appendChild(overviewPencilIcon());
  editButton.appendChild(overviewEl("span", null, " 编辑"));
  editButton.addEventListener("click", (event) => {
    event.stopPropagation();
    startDeliverableEdit(itemIndex, detailEditPanel);
  });
  headStatusGroup.appendChild(editButton);
  headTitleRow.appendChild(headStatusGroup);
  head.appendChild(headTitleRow);
  page.appendChild(head);
  page.appendChild(detailEditPanel);

  // Lead with the current-status visualization and configuration details;
  // external cross-department analysis follows when a snapshot is available.
  const analysisPanel = overviewEl("section", "deliverable-analysis-panel");
  analysisPanel.setAttribute("aria-label", `${item.name} 各科室完成情况与明细`);

  const metaSection = overviewEl("section", "deliverable-page-meta-section overview-band");
  metaSection.appendChild(overviewEl("h5", "section-sub-title", "交付物配置"));
  let statusChart = null;
  let ewoInteractivePolicy = item.updatePolicy || {};
  const interactiveQueryHost = overviewEl("section", "deliverable-interactive-query-panel");
  interactiveQueryHost.hidden = true;
  interactiveQueryHost.setAttribute("aria-live", "polite");
  const analysisSyncReadiness = createDeliverableAnalysisSyncState();
  const analysisOptions = {
    showAnalysisActions: true,
    analysisSyncReadiness,
    onSync: () => runDeliverableSyncFromAnalysis(
      item,
      analysisSyncReadiness,
      analysisPanel,
      statusChart,
      analysisOptions,
    ),
    onRefresh: () => refreshDeliverableAnalysisFromAnalysis(
      item,
      analysisSyncReadiness,
      analysisPanel,
      statusChart,
      analysisOptions,
    ),
  };
  statusChart = renderDeliverableStatusChart(item, {
    onInteractiveRefresh: () => {
      interactiveQueryHost.hidden = false;
      return runEwoInteractiveRefreshFromStatusChart(
        item,
        statusChart,
        interactiveQueryHost,
        () => ewoInteractivePolicy,
      );
    },
    onRefresh: () => refreshEwoAnalysisFromStatusChart(item, statusChart, analysisPanel, analysisOptions),
  });
  metaSection.appendChild(statusChart.el);
  metaSection.appendChild(interactiveQueryHost);
  metaSection.appendChild(overviewEl("h6", "section-sub-title", "详细明细"));
  const grid = overviewEl("div", "detail-inline-grid");
  const pairs = [
    ["当前状态", item.status],
    ["负责人", item.owner],
    ["所属科室", item.department || "未设置"],
    ["所属阶段", item.stage || (overviewSavedState.phase && (overviewSavedState.phase.displayName || overviewSavedState.phase.id)) || ""],
    ["计划完成日期", item.plannedDate],
    ["实际完成日期", item.actualDate || "未完成"],
    ["项目手工进度", `${Number(item.progress) || 0}%`],
    ["数据来源", item.source || "未设置"],
    ["更新方式", item.updateMethod === "manual" ? "手动维护" : (item.updateMethod || deliverablePolicyModeLabel(item.updatePolicy && item.updatePolicy.mode))],
    ["更新时间", item.updatedAt || (overviewSavedState.phase && overviewSavedState.phase.updatedAt)],
    ["风险与备注", item.note || "无"],
  ];
  pairs.forEach(([label, value]) => {
    const field = overviewEl("div", "detail-property");
    field.append(
      overviewEl("span", "detail-property-label", label),
      overviewEl("span", "detail-property-value", safeDisplayValue(value)),
    );
    grid.appendChild(field);
  });
  metaSection.appendChild(grid);

  const association = overviewEl("div", "detail-association");
  association.append(
    overviewEl("span", "association-label", "关联项"),
    overviewEl("p", "association-empty", "尚未配置关联模型"),
  );
  metaSection.appendChild(association);
  page.appendChild(metaSection);
  page.appendChild(analysisPanel);
  loadDeliverableAnalysis(analysisPanel, item, statusChart, analysisOptions);

  const policyPanel = overviewEl("section", "deliverable-policy-panel");
  policyPanel.setAttribute("aria-label", `${item.name} 更新方式`);

  const evidenceDisclosure = document.createElement("details");
  evidenceDisclosure.className = "deliverable-evidence-disclosure";
  const evidenceSummary = document.createElement("summary");
  evidenceSummary.textContent = "外部同步与技术证据（点击展开）";
  evidenceDisclosure.appendChild(evidenceSummary);
  const evidencePanel = overviewEl("section", "deliverable-evidence-panel");
  evidencePanel.setAttribute("aria-label", `${item.name} 外部同步与证据`);
  evidenceDisclosure.appendChild(evidencePanel);
  page.appendChild(policyPanel);
  page.appendChild(evidenceDisclosure);

  const refreshEvidence = () => loadDeliverableEvidence(
    evidencePanel,
    item,
    null,
    null,
    statusChart,
    analysisSyncReadiness,
  );
  loadDeliverablePolicy(policyPanel, item, {
    onEvidenceRefresh: refreshEvidence,
    onPolicyLoaded: (policy) => { ewoInteractivePolicy = policy || {}; },
  });
  refreshEvidence();

  container.appendChild(page);
}

function renderArchiveDeliverableDetailPage(jobKey) {
  const container = document.getElementById("overview-deliverable-detail-view");
  const listView = document.getElementById("overview-deliverables-list-view");
  if (!container) return;
  if (listView) listView.hidden = true;
  container.hidden = false;
  clearOverviewContainer(container);

  const job = (Array.isArray(overviewArchiveJobs) ? overviewArchiveJobs : [])
    .find((candidate) => candidate && candidate.jobKey === jobKey);
  if (!job) {
    const box = overviewEl("div", "deliverable-detail-not-found");
    box.appendChild(overviewEl("p", "error-msg", "未找到该外部同步任务，请返回列表刷新后重试"));
    const backBtn = overviewEl("button", "segment back-to-list-btn", "← 返回交付物列表");
    backBtn.type = "button";
    backBtn.addEventListener("click", () => { location.hash = "#overview"; });
    box.appendChild(backBtn);
    container.appendChild(box);
    return;
  }

  selectedArchiveJobKey = job.jobKey;
  const labels = {
    aras_paa: ["PAA 变更记录", "ARAS PAA"],
    aras_ncr_progress: ["NCR 审批进度", "ARAS NCR"],
    aras_ncr_detail: ["NCR 审批明细", "ARAS NCR"],
  };
  const [name, source] = labels[job.jobKey] || [job.jobKey, "外部同步"];
  const page = overviewEl("article", "deliverable-detail-page");
  page.dataset.externalJobKey = job.jobKey;
  const head = overviewEl("div", "deliverable-detail-page-head");
  const nav = overviewEl("div", "deliverable-detail-page-nav");
  const backBtn = overviewEl("button", "segment back-to-list-btn", "← 返回交付物列表");
  backBtn.type = "button";
  backBtn.addEventListener("click", () => { location.hash = "#overview"; });
  nav.appendChild(backBtn);
  head.appendChild(nav);
  const titleRow = overviewEl("div", "deliverable-detail-title-row");
  const titleGroup = overviewEl("div");
  titleGroup.append(
    overviewEl("p", "eyebrow", "交付物明细"),
    overviewEl("h3", "deliverable-page-title", name),
    overviewEl("span", "deliverable-page-id", `任务 ID: ${safeDisplayValue(job.jobKey)}`),
  );
  titleRow.appendChild(titleGroup);
  titleRow.appendChild(overviewEl("span", `status-text is-${job.syncState === "success" ? "success" : job.syncState === "failed" ? "error" : "warning"}`, archiveSyncStateLabel(job.syncState)));
  head.appendChild(titleRow);
  page.appendChild(head);

  const statusSection = overviewEl("section", "deliverable-page-meta-section overview-band external-progress-chart");
  const statusHead = overviewEl("div", "external-detail-section-head");
  statusHead.appendChild(overviewEl("h5", "section-sub-title", "当前状态图表"));
  const statusActions = overviewEl("div", "external-detail-actions");
  const isPaa = job.jobKey === "aras_paa";
  const refreshButton = overviewEl("button", "btn", isPaa ? "刷新后台历史" : "刷新同步数据");
  refreshButton.type = "button";
  const interactiveButton = isPaa
    ? overviewEl("button", "btn is-primary paa-interactive-refresh-btn", "立即刷新（交互式查询）")
    : null;
  if (interactiveButton) {
    interactiveButton.type = "button";
    interactiveButton.dataset.queryMode = "interactive";
  }
  const syncButton = isPaa
    ? null
    : overviewEl("button", "btn is-secondary", "后台归档同步");
  if (syncButton) {
    syncButton.type = "button";
    syncButton.disabled = !job.enabled || !(job.credentialAvailable ?? job.credentialConfigured);
  }
  statusActions.append(refreshButton);
  if (interactiveButton) statusActions.appendChild(interactiveButton);
  if (syncButton) statusActions.appendChild(syncButton);
  statusHead.appendChild(statusActions);
  statusSection.appendChild(statusHead);
  const statusMessage = overviewEl("p", "external-detail-sync-message", `最近同步状态：${archiveSyncStateLabel(job.syncState)}`);
  statusSection.appendChild(statusMessage);
  const interactiveQueryHost = isPaa
    ? overviewEl("section", "external-interactive-query-panel")
    : null;
  if (interactiveQueryHost) {
    interactiveQueryHost.hidden = true;
    interactiveQueryHost.setAttribute("aria-live", "polite");
    statusSection.appendChild(interactiveQueryHost);
  }
  const metrics = overviewEl("div", "external-detail-metrics");
  const metricValues = [
    ["同步状态", archiveSyncStateLabel(job.syncState)],
    ["最近成功", job.lastSuccessAt || "暂无"],
    ["最近尝试", job.lastAttemptAt || "暂无"],
    ["数据新鲜度", job.freshness || "未知"],
  ];
  metricValues.forEach(([label, value]) => {
    const metric = overviewEl("div", "external-detail-metric");
    metric.append(overviewEl("span", null, label), overviewEl("strong", null, safeDisplayValue(value)));
    metrics.appendChild(metric);
  });
  statusSection.appendChild(metrics);
  const historyPanel = overviewEl("section", "external-detail-history");
  historyPanel.appendChild(overviewEl("h5", "section-sub-title", "同步历史与数据量"));
  const historyBody = overviewEl("div", "external-detail-history-body");
  historyBody.appendChild(overviewEl("p", "loading", "正在加载同步历史..."));
  historyPanel.appendChild(historyBody);
  statusSection.appendChild(historyPanel);
  page.appendChild(statusSection);

  const renderHistory = async () => {
    clearOverviewContainer(historyBody);
    try {
      const response = await fetch(`/api/scheduled-archive/runs?jobKey=${encodeURIComponent(job.jobKey)}&limit=12`, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      const body = await response.json();
      if (!response.ok || !body.ok) throw new Error((body.error && body.error.message) || "同步历史加载失败");
      const runs = Array.isArray(body.data) ? body.data : [];
      if (!runs.length) {
        historyBody.appendChild(overviewEl("p", "is-empty", "暂无同步历史，执行首次同步后将显示趋势"));
        return;
      }
      const maxRecords = Math.max(...runs.map((run) => Number(run.recordCount) || 0), 1);
      const chart = overviewEl("div", "external-run-chart");
      runs.slice().reverse().forEach((run) => {
        const column = overviewEl("div", "external-run-column");
        const bar = overviewEl("div", `external-run-bar is-${run.runState === "success" ? "success" : "error"}`);
        bar.style.height = `${Math.max(8, Math.round(((Number(run.recordCount) || 0) / maxRecords) * 100))}%`;
        bar.title = `${safeDisplayValue(run.finishedAt || run.startedAt)} · ${Number(run.recordCount) || 0} 条`;
        column.append(bar, overviewEl("small", null, run.runState === "success" ? "成功" : "失败"));
        chart.appendChild(column);
      });
      historyBody.appendChild(chart);
      const table = document.createElement("table");
      table.className = "external-run-table";
      const thead = document.createElement("thead");
      const headerRow = document.createElement("tr");
      ["完成时间", "状态", "记录数", "结果摘要"].forEach((label) => {
        headerRow.appendChild(overviewEl("th", null, label));
      });
      thead.appendChild(headerRow);
      table.appendChild(thead);
      const tbody = document.createElement("tbody");
      runs.slice(0, 6).forEach((run) => {
        const row = document.createElement("tr");
        [
          run.finishedAt || run.startedAt || "暂无",
          run.runState === "success" ? "成功" : "失败",
          String(Number(run.recordCount) || 0),
          run.errorMessage ? redactSensitiveText(run.errorMessage) : (run.resultSummary || "无"),
        ].forEach((value) => row.appendChild(overviewEl("td", null, safeDisplayValue(value))));
        tbody.appendChild(row);
      });
      table.appendChild(tbody);
      historyBody.appendChild(table);
    } catch (error) {
      historyBody.appendChild(overviewEl("p", "error-msg", `同步历史加载失败：${redactSensitiveText(error instanceof Error ? error.message : String(error))}`));
    }
  };
  refreshButton.addEventListener("click", renderHistory);
  if (interactiveButton && interactiveQueryHost) {
    interactiveButton.addEventListener("click", () => {
      interactiveQueryHost.hidden = false;
      void runPaaInteractiveRefresh(job, interactiveButton, interactiveQueryHost, statusMessage);
    });
  }
  if (syncButton) syncButton.addEventListener("click", async () => {
    syncButton.disabled = true;
    syncButton.textContent = "后台归档同步中...";
    statusMessage.textContent = "正在执行后台归档同步...";
    try {
      const response = await fetch(`/api/scheduled-archive/jobs/${encodeURIComponent(job.jobKey)}/sync-now`, {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      const body = await response.json();
      if (!response.ok || !body.ok) throw new Error((body.error && body.error.message) || "同步失败");
      statusMessage.textContent = "同步成功，正在刷新图表与明细...";
      await loadArchiveJobs(true);
      await renderHistory();
    } catch (error) {
      statusMessage.textContent = `同步失败：${redactSensitiveText(error instanceof Error ? error.message : String(error))}`;
    } finally {
      syncButton.disabled = !job.enabled || !(job.credentialAvailable ?? job.credentialConfigured);
      syncButton.textContent = "后台归档同步";
    }
  });
  renderHistory();

  const meta = document.createElement("details");
  meta.className = "deliverable-page-meta-section overview-band external-detail-info";
  const metaSummary = document.createElement("summary");
  metaSummary.textContent = "详细信息（点击展开）";
  meta.appendChild(metaSummary);
  const grid = overviewEl("div", "detail-inline-grid");
  const credentialState = job.credentialAvailable === false ? "缺少凭据" : job.credentialAvailable === true ? "已配置" : "状态未知";
  const pairs = [
    ["同步状态", archiveSyncStateLabel(job.syncState)],
    ["数据来源", source],
    ["认证状态", credentialState],
    ["最近成功", job.lastSuccessAt || "暂无"],
    ["最近尝试", job.lastAttemptAt || "暂无"],
    ["错误详情", job.lastErrorMessage ? redactSensitiveText(job.lastErrorMessage) : "无"],
  ];
  pairs.forEach(([label, value]) => {
    const field = overviewEl("div", "detail-property");
    field.append(overviewEl("span", "detail-property-label", label), overviewEl("span", "detail-property-value", safeDisplayValue(value)));
    grid.appendChild(field);
  });
  meta.appendChild(grid);
  const action = overviewEl("button", "primary-action", "进入任务配置/重试");
  action.type = "button";
  action.addEventListener("click", () => { selectedArchiveJobKey = job.jobKey; location.hash = "#scheduled-archive"; });
  meta.appendChild(action);
  page.appendChild(meta);
  container.appendChild(page);
}

function toggleDeliverableDetail(row, data, index, statusInfo = null) {
  const item = data && data.deliverables && data.deliverables[index];
  if (!item) return;
  location.hash = `#deliverable/${encodeURIComponent(item.id)}`;
}

function overviewDeliverableRows(data) {
  const rows = Array.isArray(data && data.deliverables) ? data.deliverables.slice() : [];
  const jobs = Array.isArray(overviewArchiveJobs) ? overviewArchiveJobs : [];
  const labels = {
    aras_paa: ["PAA 变更记录", "ARAS PAA"],
    aras_ncr_progress: ["NCR 审批进度", "ARAS NCR"],
    aras_ncr_detail: ["NCR 审批明细", "ARAS NCR"],
  };
  jobs.forEach((job) => {
    const label = labels[job.jobKey];
    if (!label) return;
    rows.push({
      id: `archive:${job.jobKey}`,
      name: label[0],
      status: archiveSyncStateLabel(job.syncState),
      tone: job.syncState === "success" ? "success" : job.syncState === "failed" ? "error" : job.syncState === "needs_attention" ? "warning" : "primary",
      owner: "系统同步",
      plannedDate: "—",
      progress: null,
      actualDate: job.lastSuccessAt || "暂无",
      progressOrDate: job.lastSuccessAt ? `最近成功 ${job.lastSuccessAt}` : "暂无成功记录",
      note: job.lastErrorMessage ? redactSensitiveText(job.lastErrorMessage) : "无",
      source: label[1],
      externalJobKey: job.jobKey,
      isExternalArchive: true,
    });
  });
  return rows;
}

function renderDeliverableDetails(tbody, data) {
  if (!tbody) return;
  tbody.textContent = "";
  const rows = overviewDeliverableRows(data);
  if (rows.length === 0) {
    renderTableState(tbody, "empty");
    return;
  }
  rows.forEach((item, index) => {
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
    const button = overviewEl("button", "detail-expand", "查看明细");
    button.type = "button";
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-label", `查看 ${item.name} 明细`);
    const detailId = `overview-detail-${index}`;
    button.setAttribute("aria-controls", detailId);
    controlCell.appendChild(button);
    row.appendChild(controlCell);
    row.addEventListener("click", (event) => {
      if (event.target.closest("button")) return;
      if (item.isExternalArchive) {
        selectedArchiveJobKey = item.externalJobKey;
        location.hash = `#archive-deliverable/${encodeURIComponent(item.externalJobKey)}`;
        return;
      }
      location.hash = `#deliverable/${encodeURIComponent(item.id)}`;
    });
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      if (item.isExternalArchive) {
        selectedArchiveJobKey = item.externalJobKey;
        location.hash = `#archive-deliverable/${encodeURIComponent(item.externalJobKey)}`;
        return;
      }
      location.hash = `#deliverable/${encodeURIComponent(item.id)}`;
    });
    tbody.appendChild(row);
  });
}

function renderProjectOverview() {
  const timelineBody = document.getElementById("overview-timeline-body");
  const phaseBody = document.getElementById("overview-phase-summary");
  const progressGrid = document.getElementById("overview-progress-grid");
  const riskBody = document.getElementById("overview-risk-summary");
  const externalSummary = document.getElementById("overview-external-sync-summary");
  const detailsSummary = document.getElementById("overview-details-summary");
  const detailsBody = document.getElementById("overview-details-body");
  const maintenanceBody = document.getElementById("milestone-maintenance");
  const containers = [timelineBody, phaseBody, progressGrid, riskBody, detailsSummary, externalSummary].filter(Boolean);

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
    renderPhaseSummary(phaseBody, overviewSavedState.phase, overviewSavedState.currentStage);
    renderDeliverableProgress(progressGrid, overviewSavedState.deliverables);
    renderRiskSummary(riskBody, overviewSavedState.summary);
    renderExternalSyncSummary(externalSummary, overviewArchiveJobs);
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
    const response = await fetch("/api/project-status?phase=VPI-T2", { headers: { Accept: "application/json" } });
    const body = await overviewReadJson(response);
    if (!response.ok || !body || body.ok !== true) {
      throw overviewRequestError(body, response.status);
    }
    overviewSavedState = body.data || null;
    try {
      const archiveResponse = await fetch("/api/scheduled-archive/jobs", { headers: { Accept: "application/json" }, cache: "no-store" });
      const archiveBody = await overviewReadJson(archiveResponse);
      overviewArchiveJobs = archiveResponse.ok && archiveBody && archiveBody.ok === true && Array.isArray(archiveBody.data)
        ? archiveBody.data
        : [];
    } catch {
      overviewArchiveJobs = [];
    }
  } catch (err) {
    overviewSavedState = null;
    overviewLoadError = err instanceof Error ? err.message : String(err);
  } finally {
    overviewLoading = false;
    renderProjectOverview();
    if (typeof handleHashChange === "function") {
      handleHashChange();
    }
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
  if (overviewDraft.kind === "phase") {
    if (!overviewSavedState || !overviewSavedState.phase) return false;
    const phase = overviewSavedState.phase;
    return (
      (overviewDraft.displayName || "") !== (phase.displayName || phase.id || "") ||
      (overviewDraft.status || "") !== (phase.status || "") ||
      (overviewDraft.startDate || "") !== (phase.startDate || "") ||
      (overviewDraft.endDate || "") !== (phase.endDate || "")
    );
  }
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
    ["展示编号", safeDisplayValue(item.displayCode || item.id)],
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

function startDeliverableEdit(index, detailEditPanel = null) {
  if (!overviewSavedState || overviewSaving) return;
  const item = overviewSavedState.deliverables[index];
  if (!item) return;
  if (overviewDraft) {
    if (overviewDraftDirty() && !window.confirm("有未保存的更改，放弃后将继续编辑其他记录？")) return;
    overviewDraft = null;
    renderProjectOverview();
  }
  if (detailEditPanel) {
    overviewDraft = {
      index,
      id: item.id,
      view: "detail-page",
      saved: overviewDraftValuesFromItem(item),
      values: overviewDraftValuesFromItem(item),
    };
    detailEditPanel.hidden = false;
    detailEditPanel.textContent = "";
    detailEditPanel.appendChild(renderDeliverableEditForm());
    const firstControl = detailEditPanel.querySelector("#overview-edit-status")
      || detailEditPanel.querySelector("input, select, textarea");
    if (firstControl) firstControl.focus();
    return;
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
    view: "overview-list",
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
    const editedId = overviewDraft.id;
    const editedView = overviewDraft.view;
    overviewDraft = null;
    if (editedView === "detail-page") {
      renderDeliverableDetailPage(editedId);
    } else {
      renderProjectOverview();
      expandOverviewDetail(editedIndex);
    }
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
  const id = overviewDraft.id;
  const view = overviewDraft.view;
  overviewDraft = null;
  if (view === "detail-page") {
    renderDeliverableDetailPage(id);
  } else {
    renderProjectOverview();
    expandOverviewDetail(index);
  }
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

function startPhaseEdit() {
  if (!overviewSavedState || overviewSaving) return;
  if (!overviewConfirmDiscard()) return;
  const phase = overviewSavedState.phase;
  overviewDraft = {
    kind: "phase",
    displayName: phase.displayName || phase.id || "",
    status: phase.status || "进行中",
    startDate: phase.startDate || "",
    endDate: phase.endDate || "",
    updatedAt: phase.updatedAt || "",
  };
  renderProjectOverview();
}

function cancelPhaseEdit() {
  if (!overviewDraft || overviewDraft.kind !== "phase" || overviewSaving) return;
  overviewDraft = null;
  renderProjectOverview();
}

function renderPhaseReadonlyCard(phase) {
  const card = overviewEl("div", "phase-meta-card");
  const toolbar = overviewEl("div", "phase-meta-toolbar");
  toolbar.appendChild(overviewEl("span", "phase-meta-title", "主计划基本信息"));
  const editBtn = overviewEl("button", "phase-meta-edit-btn", null);
  editBtn.type = "button";
  const label = "编辑阶段信息";
  editBtn.title = label;
  editBtn.setAttribute("aria-label", label);
  editBtn.appendChild(overviewPencilIcon());
  editBtn.appendChild(overviewEl("span", null, label));
  editBtn.addEventListener("click", () => startPhaseEdit());
  toolbar.appendChild(editBtn);
  card.appendChild(toolbar);

  const grid = overviewEl("div", "phase-meta-grid");
  const items = [
    ["主计划名称", phase.displayName || phase.id],
    ["阶段状态", phase.status],
    ["开始日期", phase.startDate],
    ["计划完成日期", phase.endDate],
  ];
  items.forEach(([lbl, val]) => {
    const cell = overviewEl("div", "phase-meta-cell");
    cell.append(overviewEl("span", "phase-meta-label", lbl), overviewEl("strong", "phase-meta-value", safeDisplayValue(val)));
    grid.appendChild(cell);
  });
  card.appendChild(grid);
  return card;
}

function renderPhaseEditForm() {
  const form = document.createElement("form");
  form.id = "phase-meta-edit-form";
  form.className = "phase-meta-edit-form";
  form.noValidate = true;

  const title = overviewEl("h5", "phase-meta-title", "编辑主计划基本信息");
  form.appendChild(title);

  const grid = overviewEl("div", "phase-meta-edit-grid");

  // Name
  const nameLabel = overviewEl("label", "phase-meta-field");
  nameLabel.appendChild(overviewEl("span", null, "主计划名称"));
  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.name = "displayName";
  nameInput.maxLength = 120;
  nameInput.value = overviewDraft.displayName || "";
  nameInput.addEventListener("input", () => { overviewDraft.displayName = nameInput.value; });
  nameLabel.appendChild(nameInput);
  grid.appendChild(nameLabel);

  // Status
  const statusLabel = overviewEl("label", "phase-meta-field");
  statusLabel.appendChild(overviewEl("span", null, "阶段状态"));
  const statusSelect = document.createElement("select");
  statusSelect.name = "status";
  ["未开始", "进行中", "已完成", "暂停"].forEach((st) => {
    const opt = document.createElement("option");
    opt.value = st;
    opt.textContent = st;
    if (st === overviewDraft.status) opt.selected = true;
    statusSelect.appendChild(opt);
  });
  statusSelect.addEventListener("change", () => { overviewDraft.status = statusSelect.value; });
  statusLabel.appendChild(statusSelect);
  grid.appendChild(statusLabel);

  // Start Date
  const startLabel = overviewEl("label", "phase-meta-field");
  startLabel.appendChild(overviewEl("span", null, "开始日期"));
  const startInput = document.createElement("input");
  startInput.type = "date";
  startInput.name = "startDate";
  startInput.value = overviewDraft.startDate || "";
  startInput.addEventListener("input", () => { overviewDraft.startDate = startInput.value; });
  startLabel.appendChild(startInput);
  grid.appendChild(startLabel);

  // End Date
  const endLabel = overviewEl("label", "phase-meta-field");
  endLabel.appendChild(overviewEl("span", null, "计划完成日期"));
  const endInput = document.createElement("input");
  endInput.type = "date";
  endInput.name = "endDate";
  endInput.value = overviewDraft.endDate || "";
  endInput.addEventListener("input", () => { overviewDraft.endDate = endInput.value; });
  endLabel.appendChild(endInput);
  grid.appendChild(endLabel);

  form.appendChild(grid);

  const actions = overviewEl("div", "phase-meta-form-actions");
  const saveBtn = overviewEl("button", "edit-save-btn phase-meta-save-btn", "保存阶段信息");
  saveBtn.type = "button";
  saveBtn.addEventListener("click", savePhaseMetadataChanges);
  const cancelBtn = overviewEl("button", "edit-cancel-btn phase-meta-cancel-btn", "取消");
  cancelBtn.type = "button";
  cancelBtn.addEventListener("click", cancelPhaseEdit);
  const msgEl = overviewEl("div", "phase-meta-request-message");
  actions.append(saveBtn, cancelBtn, msgEl);
  form.appendChild(actions);

  return form;
}

async function savePhaseMetadataChanges(event) {
  if (event) event.preventDefault();
  if (!overviewDraft || overviewDraft.kind !== "phase" || overviewSaving) return;
  const form = document.getElementById("phase-meta-edit-form");
  const msgEl = form?.querySelector(".phase-meta-request-message");
  if (msgEl) msgEl.textContent = "";

  const displayName = String(overviewDraft.displayName || "").trim();
  const status = String(overviewDraft.status || "").trim();
  const startDate = String(overviewDraft.startDate || "").trim();
  const endDate = String(overviewDraft.endDate || "").trim();

  if (!displayName) {
    if (msgEl) msgEl.textContent = "主计划名称不能为空";
    return;
  }
  if (!["未开始", "进行中", "已完成", "暂停"].includes(status)) {
    if (msgEl) msgEl.textContent = "阶段状态无效";
    return;
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(startDate) || !/^\d{4}-\d{2}-\d{2}$/.test(endDate)) {
    if (msgEl) msgEl.textContent = "日期格式应为 YYYY-MM-DD";
    return;
  }
  if (startDate > endDate) {
    if (msgEl) msgEl.textContent = "计划完成日期不能早于开始日期";
    return;
  }

  const payload = {
    displayName,
    status,
    startDate,
    endDate,
    updatedAt: overviewDraft.updatedAt,
  };

  overviewSaving = true;
  const saveBtn = form?.querySelector(".phase-meta-save-btn");
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = "保存中...";
  }

  try {
    const response = await fetch("/api/project-status/phases/VPI-T2", {
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
    if (msgEl) msgEl.textContent = message;
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = "保存阶段信息";
    }
  } finally {
    overviewSaving = false;
  }
}

function renderMilestoneMaintenance(container, data) {
  if (!container) return;
  clearOverviewContainer(container);

  const phaseSection = overviewEl("div", "phase-meta-section");
  if (overviewDraft && overviewDraft.kind === "phase") {
    phaseSection.appendChild(renderPhaseEditForm());
  } else if (data && data.phase) {
    phaseSection.appendChild(renderPhaseReadonlyCard(data.phase));
  }
  container.appendChild(phaseSection);

  const milestonesSection = overviewEl("div", "milestone-nodes-section");
  if (overviewDraft && overviewDraft.kind === "milestones") {
    milestonesSection.appendChild(renderMilestoneEditForm());
  } else {
    renderMilestoneReadonlyList(milestonesSection, data);
  }
  container.appendChild(milestonesSection);
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
  const planTab = document.getElementById("overview-tab-plan");
  if (planTab) activateOverviewTab(planTab);
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
      status: String(item.status || (MILESTONE_LABEL_BY_TYPE[item.type] || "未开始")),
      type: MILESTONE_TYPE_BY_STATUS[item.status] || item.type || "planned",
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
    if (!errors[dateKey] && (row.type === "done" || row.status === "已完成") && today && date > today) {
      errors[dateKey] = `已达成节点日期不能晚于当前日期 ${today}`;
    }
    if (!errors[dateKey] && (row.type === "planned" || row.status === "未开始") && today && date && date < today) {
      errors[dateKey] = `计划节点日期不能早于当前日期 ${today}`;
    }
    });
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
    milestones: overviewDraft.rows.map((row, index) => {
      const status = row.status || MILESTONE_LABEL_BY_TYPE[row.type] || "未开始";
      const nodeType = MILESTONE_TYPE_BY_STATUS[status] || row.type || "planned";
      return {
        id: row.id ?? null,
        name: String(row.name || "").trim(),
        date: String(row.date || "").trim(),
        status: status,
        type: nodeType,
        sortOrder: index + 1,
      };
    }),
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
  const payload = {
    base_url: fieldValue(form, "base_url"),
    headers: parseHeaders(fieldValue(form, "headers")),
    filters: {},
  };
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
  const xmlToggle = document.getElementById("aras-include-xml");
  if (config.xmlCapture && xmlToggle && xmlToggle.checked) payload.include_xml = true;
  if (config.preview) payload.preview = true;
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
  document.querySelectorAll("[data-aras-xml-action]").forEach((button) => {
    button.disabled = Boolean(isRunning);
  });
  document.body.classList.toggle("aras-running", Boolean(isRunning));
}

function restoreArasButtons() {
  document.querySelectorAll("[data-aras-action]").forEach((button) => {
    button.disabled = false;
    button.classList.remove("is-running");
  });
  document.querySelectorAll("[data-aras-xml-action]").forEach((button) => {
    button.disabled = false;
  });
  document.body.classList.remove("aras-running");
}

function clearArasXmlCapture() {
  arasXmlCapture = null;
  const actions = document.getElementById("aras-xml-actions");
  if (actions) actions.hidden = true;
}

function renderArasXmlCapture(data, config) {
  clearArasXmlCapture();
  if (!config.xmlCapture || !data || !data.xml) return;
  const requestXml = typeof data.xml.requestXml === "string" ? data.xml.requestXml : "";
  const responseXml = typeof data.xml.responseXml === "string" ? data.xml.responseXml : "";
  if (!requestXml || !responseXml) return;
  arasXmlCapture = { requestXml, responseXml };
  const actions = document.getElementById("aras-xml-actions");
  if (actions) actions.hidden = false;
}

function downloadArasXml(kind) {
  if (!arasXmlCapture) {
    showArasError("请先执行查询预览或获取全部结果，再下载 XML");
    return;
  }
  const xml = kind === "request" ? arasXmlCapture.requestXml : arasXmlCapture.responseXml;
  if (!xml) {
    showArasError("当前结果没有可下载的 XML");
    return;
  }
  let url = "";
  let link = null;
  try {
    const blob = new Blob([xml], { type: "application/xml;charset=utf-8" });
    url = URL.createObjectURL(blob);
    const timestamp = new Date().toISOString().replace(/[.:]/g, "-");
    link = document.createElement("a");
    link.href = url;
    link.download = `aras-${arasMode}-${kind}-${timestamp}.xml`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (err) {
    if (link) link.remove();
    if (url) URL.revokeObjectURL(url);
    const message = err instanceof Error ? err.message : String(err);
    showArasError(`XML 下载失败：${redactSensitiveText(message)}`);
  }
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

function renderRows(data, preferredColumns, mode = "") {
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  const table = document.createElement("table");
  table.className = "result-table";

  const headerRows = Array.isArray(data.headerRows) ? data.headerRows : null;
  const columns = Array.isArray(data.columns) ? data.columns : null;
  const rows = Array.isArray(data.rows) ? data.rows : [];
  const defaultVisible = Number(data.defaultVisibleCount) || 12;

  const thead = document.createElement("thead");

  if (headerRows && headerRows.length > 0) {
    if (mode === "ncr-progress" && headerRows.length > 1) {
      // Skip blank top row for NCR progress
      const targetHeaderRow = headerRows[1] || headerRows[0];
      const tr = document.createElement("tr");
      targetHeaderRow.forEach((label, idx) => {
        if (defaultVisible && idx >= defaultVisible && (mode === "ewo" || mode === "paa")) return;
        const th = document.createElement("th");
        th.textContent = label ? String(label).trim() : `列 ${idx + 1}`;
        tr.appendChild(th);
      });
      thead.appendChild(tr);
    } else if (mode === "ncr-detail" && headerRows.length > 1) {
      // Multi-row grouped headers for NCR detail
      headerRows.forEach((hRow) => {
        const tr = document.createElement("tr");
        hRow.forEach((label) => {
          const th = document.createElement("th");
          th.textContent = label ? String(label).trim() : "";
          tr.appendChild(th);
        });
        thead.appendChild(tr);
      });
    } else {
      // Single header row (e.g. EWO / PAA)
      const firstRow = headerRows[0] || [];
      const tr = document.createElement("tr");
      const visibleCount = (mode === "ewo" || mode === "paa") ? Math.min(firstRow.length, defaultVisible) : firstRow.length;
      for (let i = 0; i < (visibleCount || firstRow.length); i++) {
        const label = firstRow[i];
        const th = document.createElement("th");
        th.textContent = label ? String(label).trim() : `列 ${i + 1}`;
        tr.appendChild(th);
      }
      thead.appendChild(tr);
    }
  } else if (columns && columns.length > 0) {
    const tr = document.createElement("tr");
    const visibleCount = (mode === "ewo" || mode === "paa") ? Math.min(columns.length, defaultVisible) : columns.length;
    for (let i = 0; i < visibleCount; i++) {
      const col = columns[i];
      const th = document.createElement("th");
      th.textContent = col.label || col.key || `列 ${i + 1}`;
      tr.appendChild(th);
    }
    thead.appendChild(tr);
  } else {
    const keys = orderedColumns(rows, preferredColumns);
    const headerRow = document.createElement("tr");
    (keys.length ? keys : ["消息"]).forEach((key) => {
      const th = document.createElement("th");
      th.textContent = key;
      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
  }
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  if (rows.length) {
    const colCount = thead.querySelector("tr") ? thead.querySelector("tr").children.length : 1;
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      if (Array.isArray(row)) {
        for (let i = 0; i < colCount; i++) {
          const td = document.createElement("td");
          td.textContent = safeDisplayValue(row[i]);
          tr.appendChild(td);
        }
      } else if (typeof row === "object" && row !== null) {
        if (columns && columns.length > 0) {
          for (let i = 0; i < colCount; i++) {
            const key = columns[i].key || Object.keys(row)[i];
            const td = document.createElement("td");
            td.textContent = safeDisplayValue(row[key]);
            tr.appendChild(td);
          }
        } else {
          const keys = orderedColumns([row], preferredColumns);
          keys.slice(0, colCount).forEach((k) => {
            const td = document.createElement("td");
            td.textContent = safeDisplayValue(row[k]);
            tr.appendChild(td);
          });
        }
      }
      tbody.appendChild(tr);
    });
  } else {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    const colCount = thead.querySelector("tr") ? thead.querySelector("tr").children.length : 1;
    td.colSpan = colCount || 1;
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
    if (data.mappingComplete === false && Array.isArray(data.unmappedColumns) && data.unmappedColumns.length > 0) {
      const warning = document.createElement("p");
      warning.className = "result-meta result-warning";
      warning.textContent = `当前接口尚未提供 ${data.unmappedColumns.length} 个工作簿派生列，已保留为空值；请使用官方导出获取完整报表。`;
      target.appendChild(warning);
    }
    target.appendChild(renderRows(data, config.preferredColumns, mode));
    renderArasXmlCapture(data, config);
  } else {
    target.appendChild(renderSummary(data));
  }
}

async function runArasCrawlAll() {
  if (arasRunning) {
    arasQueuedAction = "crawl_all";
    setArasStatus("已排队", true);
    return;
  }
  arasRunning = true;
  const requestMode = arasMode;
  const requestConfig = ARAS_MODES[requestMode];
  const endpoint = requestConfig.crawlAllEndpoint || requestConfig.endpoint;
  const seq = ++arasRequestSeq;
  setArasStatus("全量获取中...", true);
  showArasError("");
  showArasWarning("");
  clearArasXmlCapture();
  const payload = collectArasPayload(requestConfig);
  try {
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
    setArasStatus("");
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
  clearArasXmlCapture();
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
  controls.querySelectorAll("[data-preview-source-only]").forEach((el) => {
    el.hidden = mode === "export";
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
      <label class="wide">
        <span>请求头</span>
        <textarea id="tdc-headers" name="headers" rows="3" placeholder="名称: 值"></textarea>
      </label>
    </div>
    <p id="tdc-auth-note" class="connection-note">统一使用「设置 → 统一域账号登录」建立的会话，无需在此填写账号密码；未登录时请先完成统一登录。</p>`;
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
    if (item.id === "tdc-sor" && field.name === "car_type_project") {
      input.placeholder = "例如：E262S（车型项目，可手动输入）";
      input.autocomplete = "off";
    }
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
  if (item.id === "tdc-data-model" || item.id === "tdc-sor") {
    const previewSourceLabel = document.createElement("label");
    previewSourceLabel.dataset.previewSourceOnly = "true";
    const previewSourceSpan = document.createElement("span");
    previewSourceSpan.textContent = "查询模式";
    const previewSource = document.createElement("select");
    previewSource.name = "preview_source";
    const fastOption = document.createElement("option");
    fastOption.value = "list_endpoint";
    fastOption.textContent = "快速查询（list 接口）";
    const exactOption = document.createElement("option");
    exactOption.value = "official_export";
    exactOption.textContent = "官方 Excel 精确预览（较慢）";
    previewSource.append(fastOption, exactOption);
    previewSourceLabel.append(previewSourceSpan, previewSource);
    controls.appendChild(previewSourceLabel);
  }
  const buttons = document.createElement("div");
  buttons.className = "operation-buttons";
  buttons.innerHTML = `<button type="submit" id="deliverable-run-button" class="primary-btn" data-deliverable-run>${DELIVERABLE_OPERATION_LABELS.query}</button><button type="button" id="deliverable-download-button" class="primary-btn" data-deliverable-download>下载 XLSX</button>`;
  const status = document.createElement("span");
  status.id = "deliverable-status";
  status.className = "deliverable-status";
  status.setAttribute("aria-live", "polite");
  operations.append(controls, buttons, status);
  form.appendChild(operations);

  const operationMode = form.querySelector('[name="operation_mode"]');
  const runButton = form.querySelector("#deliverable-run-button");
  const downloadButton = form.querySelector("#deliverable-download-button");
  const syncDeliverableOperation = () => {
    const operation = operationMode.value || "query";
    setDeliverableOperationControls(operation);
    runButton.textContent = DELIVERABLE_OPERATION_LABELS[operation] || operation;
  };
  operationMode.addEventListener("change", syncDeliverableOperation);
  downloadButton.addEventListener("click", () => {
    if (!validateDeliverableForm(form)) return;
    runDeliverableOperation(item, "export");
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const operation = operationMode.value || "query";
    setDeliverableOperationControls(operation);
    if (!validateDeliverableForm(form)) return;
    runDeliverableOperation(item, operation);
  });
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
  const payload = {
    base_url: fieldValue(form, "base_url"),
    headers: parseHeaders(fieldValue(form, "headers")),
    filters: {},
  };
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
  if ((item.id === "tdc-data-model" || item.id === "tdc-sor") && (operation === "query" || operation === "crawl_all")) {
    payload.preview_source = fieldValue(form, "preview_source") || "list_endpoint";
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
  const downloadButton = document.getElementById("deliverable-download-button");
  if (downloadButton) downloadButton.disabled = Boolean(isRunning);
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
  detail.textContent = `report=${data.report_type || "-"} source=${data.data_source || "-"} page=${data.page || "-"}/${data.pages || "-"} rows=${(data.rows || []).length} unique=${data.unique_count ?? "-"} dup=${data.duplicate_count ?? "-"} fetched=${data.fetched_pages ?? "-"} stop=${data.stop_reason || "-"} granularity=${data.record_granularity || "-"}`;
  target.appendChild(detail);
  if (data.mappingComplete === false && Array.isArray(data.unmappedColumns) && data.unmappedColumns.length > 0) {
    const warning = document.createElement("p");
    warning.className = "result-meta result-warning";
    warning.textContent = `列表接口尚未提供 ${data.unmappedColumns.length} 个官方导出列，已保留为空值；如需与内网报表完全一致，请使用官方导出预览。`;
    target.appendChild(warning);
  }
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

function handleHashChange() {
  const hash = window.location.hash || "";
  const archiveDeliverableMatch = hash.match(/^#archive-deliverable\/([^/?#]+)/);
  const deliverableMatch = hash.match(/^#(?:overview\/)?deliverables?\/([^/?#]+)/)
    || hash.match(/^#deliverable-detail\/([^/?#]+)/);

  if (archiveDeliverableMatch) {
    const jobKey = decodeURIComponent(archiveDeliverableMatch[1]);
    selectedArchiveJobKey = jobKey;
    document.querySelectorAll("[data-panel-link]").forEach((item) => {
      item.classList.toggle("active", item.dataset.panelLink === "overview");
    });
    document.querySelectorAll(".panel-section").forEach((panel) => {
      panel.hidden = panel.id !== "overview";
    });
    document.body.dataset.sessionView = "overview";
    document.getElementById("session-title").textContent = "项目状态";
    document.getElementById("command-label").textContent = "明细";
    const detailsTab = document.getElementById("overview-tab-details");
    const statusTab = document.getElementById("overview-tab-status");
    const planTab = document.getElementById("overview-tab-plan");
    const detailsPanel = document.getElementById("overview-details-panel");
    const statusPanel = document.getElementById("overview-status-panel");
    const planPanel = document.getElementById("overview-plan-panel");
    if (detailsTab && detailsPanel && statusTab && statusPanel && planTab && planPanel) {
      detailsTab.classList.add("active");
      detailsTab.setAttribute("aria-selected", "true");
      detailsTab.tabIndex = 0;
      statusTab.classList.remove("active");
      statusTab.setAttribute("aria-selected", "false");
      statusTab.tabIndex = -1;
      planTab.classList.remove("active");
      planTab.setAttribute("aria-selected", "false");
      planTab.tabIndex = -1;
      detailsPanel.hidden = false;
      statusPanel.hidden = true;
      planPanel.hidden = true;
    }
    renderArchiveDeliverableDetailPage(jobKey);
    return;
  }

  if (deliverableMatch) {
    const deliverableId = decodeURIComponent(deliverableMatch[1]);
    document.querySelectorAll("[data-panel-link]").forEach((item) => {
      item.classList.toggle("active", item.dataset.panelLink === "overview");
    });
    document.querySelectorAll(".panel-section").forEach((panel) => {
      panel.hidden = panel.id !== "overview";
    });
    document.body.dataset.sessionView = "overview";
    document.getElementById("session-title").textContent = "项目状态";
    document.getElementById("command-label").textContent = "明细";

    const detailsTab = document.getElementById("overview-tab-details");
    const statusTab = document.getElementById("overview-tab-status");
    const planTab = document.getElementById("overview-tab-plan");
    const detailsPanel = document.getElementById("overview-details-panel");
    const statusPanel = document.getElementById("overview-status-panel");
    const planPanel = document.getElementById("overview-plan-panel");
    if (detailsTab && detailsPanel && statusTab && statusPanel && planTab && planPanel) {
      detailsTab.classList.add("active");
      detailsTab.setAttribute("aria-selected", "true");
      detailsTab.tabIndex = 0;
      statusTab.classList.remove("active");
      statusTab.setAttribute("aria-selected", "false");
      statusTab.tabIndex = -1;
      planTab.classList.remove("active");
      planTab.setAttribute("aria-selected", "false");
      planTab.tabIndex = -1;
      detailsPanel.hidden = false;
      statusPanel.hidden = true;
      planPanel.hidden = true;
    }
    renderDeliverableDetailPage(deliverableId);
    return;
  }

  if (hash === "" || hash === "#overview" || hash === "#overview-status-panel" || hash === "#overview-details-panel") {
    const listView = document.getElementById("overview-deliverables-list-view");
    const detailView = document.getElementById("overview-deliverable-detail-view");
    if (listView) listView.hidden = false;
    if (detailView) {
      detailView.hidden = true;
      clearOverviewContainer(detailView);
    }
    document.querySelectorAll("[data-panel-link]").forEach((item) => {
      item.classList.toggle("active", item.dataset.panelLink === "overview");
    });
    document.querySelectorAll(".panel-section").forEach((panel) => {
      panel.hidden = panel.id !== "overview";
    });
    document.body.dataset.sessionView = "overview";
    document.getElementById("session-title").textContent = "项目状态";
    document.getElementById("command-label").textContent = "就绪";
    return;
  }

  const panelId = hash.replace(/^#/, "");
  const targetLink = document.querySelector(`[data-panel-link="${panelId}"]`);
  if (targetLink) {
    document.querySelectorAll("[data-panel-link]").forEach((item) => item.classList.remove("active"));
    targetLink.classList.add("active");
    document.querySelectorAll(".panel-section").forEach((panel) => {
      panel.hidden = panel.id !== panelId;
    });
    const isAras = panelId === "aras-panel";
    const isDeliverables = panelId === "deliverables";
    const isExcel = panelId === "excel-tasks";
    const isArchive = panelId === "scheduled-archive";
    const isSettings = panelId === "settings-panel";
    document.body.dataset.sessionView = isAras
      ? "aras"
      : isDeliverables
      ? "deliverables"
      : isExcel
      ? "excel-tasks"
      : isArchive
      ? "scheduled-archive"
      : isSettings
      ? "settings"
      : "overview";
    document.getElementById("session-title").textContent = isAras
      ? "Aras 查询工具"
      : isDeliverables
      ? "交付物工作台"
      : isExcel
      ? "Excel 文件处理"
      : isArchive
      ? "定时任务"
      : isSettings
      ? "系统设置"
      : "项目状态";
    document.getElementById("command-label").textContent = isAras
      ? (COMMAND_LABELS[arasMode] || arasMode)
      : isDeliverables
      ? "目录"
      : isExcel
      ? "处理"
      : isArchive
      ? "定时任务"
      : isSettings
      ? "设置"
      : "就绪";
    if (isDeliverables) loadDeliverablesCatalog();
    if (isExcel) loadExcelTaskWorkspace();
    if (isArchive) loadArchiveJobs();
    if (isSettings) loadSettings();
  }
}

function setupPanels() {
  window.addEventListener("hashchange", handleHashChange);
  document.querySelectorAll("[data-panel-link]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      if (!overviewConfirmDiscard()) return;
      const targetHash = `#${link.dataset.panelLink}`;
      if (window.location.hash === targetHash) {
        handleHashChange();
      } else {
        window.location.hash = targetHash;
      }
    });
  });
  // 直接带面板哈希打开页面时，hashchange 不会触发，需主动加载该面板数据。
  handleHashChange();
}

/* ── Excel Task And Artifact Management ─────────────────────────────── */

let excelTasks = [];
let excelRootIds = [];
let selectedExcelTaskId = null;
let excelWorkspaceLoading = false;
let excelWorkerMutating = false;

function excelEl(tagName, className, textValue) {
  const node = document.createElement(tagName);
  if (className) node.className = className;
  if (textValue !== undefined && textValue !== null) node.textContent = textValue;
  return node;
}

function excelShowError(message) {
  const target = document.getElementById("excel-task-error");
  if (!target) return;
  target.hidden = !message;
  target.textContent = message ? redactSensitiveText(String(message)) : "";
}

function excelSetStatus(message) {
  const target = document.getElementById("excel-task-status");
  if (target) target.textContent = message || "";
}

function excelFormatDate(value) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return safeDisplayValue(value);
  return parsed.toLocaleString("zh-CN", { hour12: false });
}

function excelFormatSize(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function excelStatusLabel(status) {
  return ({
    queued: "排队中",
    leased: "已租用",
    running: "运行中",
    succeeded: "已成功",
    failed: "失败",
    cancelled: "已取消",
    expired: "已过期",
    stopped: "已停止",
    stopping: "停止中",
  })[status] || safeDisplayValue(status || "未知");
}

function excelStatusChip(status) {
  const chip = excelEl("span", "excel-status-chip", excelStatusLabel(status));
  if (status === "succeeded" || status === "stopped") chip.classList.add("is-success");
  else if (["queued", "leased", "running", "stopping"].includes(status)) chip.classList.add("is-running");
  else if (["failed", "cancelled", "expired"].includes(status)) chip.classList.add("is-failed");
  else chip.classList.add("is-unknown");
  return chip;
}

async function excelReadJson(response) {
  try {
    return await response.json();
  } catch (_error) {
    return null;
  }
}

function excelApiMessage(body, fallback) {
  return body && body.error && body.error.message
    ? redactSensitiveText(body.error.message)
    : fallback;
}

function generateExcelIdempotencyKey() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
    return `excel-${globalThis.crypto.randomUUID()}`;
  }
  return `excel-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function refreshExcelIdempotencyKey() {
  const input = document.getElementById("excel-idempotency-key");
  if (input) input.value = generateExcelIdempotencyKey();
}

function validateExcelRelativePath(value, fieldName) {
  const path = String(value || "").trim();
  if (!path) throw new Error(`${fieldName}不能为空`);
  if (path.startsWith("/") || path.includes("\\") || path.includes(":")) {
    throw new Error(`${fieldName}必须是受控根下的相对路径`);
  }
  const segments = path.split("/");
  if (segments.some((segment) => !segment || segment === "." || segment === "..")) {
    throw new Error(`${fieldName}包含非法路径片段`);
  }
  if (!/\.(xlsx|xls)$/i.test(path)) {
    throw new Error(`${fieldName}必须使用 .xlsx 或 .xls 扩展名`);
  }
  return path;
}

function updateExcelCreateFields() {
  const operation = document.getElementById("excel-task-operation")?.value || "merge_append";
  document.querySelectorAll('[data-excel-create-field="sources"]').forEach((node) => {
    node.hidden = operation === "diff_against_baseline";
  });
  document.querySelectorAll('[data-excel-create-field="target"]').forEach((node) => {
    node.hidden = operation === "merge_append";
  });
  document.querySelectorAll('[data-excel-create-field="baseline"]').forEach((node) => {
    node.hidden = false;
  });
  const baselineInput = document.getElementById("excel-baseline-path");
  if (baselineInput) baselineInput.required = operation === "diff_against_baseline";
  const targetInput = document.getElementById("excel-target-path");
  if (targetInput) targetInput.required = operation !== "merge_append";
}

function populateExcelRootSelects() {
  document.querySelectorAll("[data-excel-root-select]").forEach((select) => {
    const previous = select.value;
    select.textContent = "";
    excelRootIds.forEach((rootId) => {
      const option = document.createElement("option");
      option.value = rootId;
      option.textContent = rootId;
      select.appendChild(option);
    });
    if (excelRootIds.includes(previous)) select.value = previous;
    select.disabled = excelRootIds.length === 0;
  });
  const createButton = document.getElementById("excel-task-create-btn");
  if (createButton) createButton.disabled = excelRootIds.length === 0;
}

async function loadExcelRoots() {
  try {
    const response = await fetch("/api/excel-roots", {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const body = await excelReadJson(response);
    if (!response.ok || !body || body.ok !== true) {
      excelRootIds = [];
      populateExcelRootSelects();
      return;
    }
    excelRootIds = Array.isArray(body.data)
      ? body.data.map((item) => item && item.rootId).filter((item) => typeof item === "string" && item)
      : [];
    populateExcelRootSelects();
  } catch (_error) {
    excelRootIds = [];
    populateExcelRootSelects();
  }
}

function excelRootValue(id) {
  const select = document.getElementById(id);
  const value = select ? String(select.value || "") : "";
  if (!value || !excelRootIds.includes(value)) throw new Error("请选择有效的文件所在位置");
  return value;
}

async function createExcelTask(event) {
  event.preventDefault();
  const button = document.getElementById("excel-task-create-btn");
  if (!button || button.disabled) return;
  button.disabled = true;
  excelShowError("");
  excelSetStatus("正在创建处理记录...");
  try {
    const operation = document.getElementById("excel-task-operation").value;
    const files = [];
    if (operation !== "diff_against_baseline") {
      const sourceRoot = excelRootValue("excel-source-root");
      const rawSources = document.getElementById("excel-source-paths").value
        .split(/\r?\n/)
        .map((item) => item.trim())
        .filter(Boolean);
      if (rawSources.length === 0) throw new Error("至少需要填写一个要处理的文件");
      rawSources.forEach((path, index) => files.push({
        role: "source",
        rootId: sourceRoot,
        relativePath: validateExcelRelativePath(path, `要处理的文件 #${index + 1}`),
        ordinal: index,
      }));
    }
    if (operation !== "merge_append") {
      files.push({
        role: "target",
        rootId: excelRootValue("excel-target-root"),
        relativePath: validateExcelRelativePath(document.getElementById("excel-target-path").value, "目标模板"),
        ordinal: 0,
      });
    }
    const baselineValue = (document.getElementById("excel-baseline-path")?.value || "").trim();
    if (operation === "diff_against_baseline") {
      if (!baselineValue) throw new Error("对比基准为必填项");
      files.push({
        role: "baseline",
        rootId: excelRootValue("excel-baseline-root"),
        relativePath: validateExcelRelativePath(baselineValue, "对比基准"),
        ordinal: 0,
      });
    } else if (baselineValue) {
      files.push({
        role: "baseline",
        rootId: excelRootValue("excel-baseline-root"),
        relativePath: validateExcelRelativePath(baselineValue, "对比基准"),
        ordinal: 0,
      });
    }
    files.push({
      role: "output",
      rootId: excelRootValue("excel-output-root"),
      relativePath: validateExcelRelativePath(document.getElementById("excel-output-path").value, "输出文件名"),
      ordinal: 0,
    });
    const payload = {
      operation,
      files,
      idempotencyKey: document.getElementById("excel-idempotency-key").value,
      maxAttempts: 1,
    };
    const response = await fetch("/api/excel-tasks", {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify(payload),
    });
    const body = await excelReadJson(response);
    if (!response.ok || !body || body.ok !== true) {
      throw new Error(excelApiMessage(body, "Excel 文件处理创建失败"));
    }
    selectedExcelTaskId = body.data.id;
    refreshExcelIdempotencyKey();
    excelSetStatus(`处理记录 #${selectedExcelTaskId} 已创建`);
    await loadExcelTasks(true);
  } catch (error) {
    excelSetStatus("");
    excelShowError(error instanceof Error ? error.message : String(error));
  } finally {
    button.disabled = excelRootIds.length === 0;
  }
}

async function loadExcelWorkerStatus() {
  const stateNode = document.getElementById("excel-worker-state");
  const startButton = document.getElementById("excel-worker-start-btn");
  const stopButton = document.getElementById("excel-worker-stop-btn");
  if (!stateNode || !startButton || !stopButton) return;

  try {
    const response = await fetch("/api/excel-worker/status", {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const body = await excelReadJson(response);
    if (!response.ok || !body || body.ok !== true) {
      stateNode.className = "excel-status-chip is-unknown";
      stateNode.textContent = response.status === 503 ? "未配置" : "状态未知";
      startButton.disabled = true;
      stopButton.disabled = true;
      return;
    }
    const status = body.data || {};
    const state = status.state || "unknown";
    stateNode.className = "excel-status-chip";
    const rendered = excelStatusChip(state);
    stateNode.className = rendered.className;
    stateNode.textContent = status.pid ? `${rendered.textContent} · PID ${status.pid}` : rendered.textContent;
    startButton.disabled = excelWorkerMutating || ["running", "stopping"].includes(state);
    stopButton.disabled = excelWorkerMutating || state !== "running";
  } catch (_error) {
    stateNode.className = "excel-status-chip is-unknown";
    stateNode.textContent = "状态未知";
    startButton.disabled = true;
    stopButton.disabled = true;
  }
}

async function mutateExcelWorker(action) {
  if (excelWorkerMutating) return;
  excelWorkerMutating = true;
  excelShowError("");
  excelSetStatus(action === "start" ? "正在启动 worker..." : "正在停止 worker...");
  await loadExcelWorkerStatus();
  try {
    const response = await fetch(`/api/excel-worker/${action}`, {
      method: "POST",
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const body = await excelReadJson(response);
    if (!response.ok || !body || body.ok !== true) {
      throw new Error(excelApiMessage(body, `Worker ${action} 失败`));
    }
    excelSetStatus(action === "start" ? "Worker 已启动" : "Worker 已停止");
  } catch (error) {
    excelShowError(error instanceof Error ? error.message : String(error));
    excelSetStatus("");
  } finally {
    excelWorkerMutating = false;
    await loadExcelWorkerStatus();
    if (action === "stop") await loadExcelTasks(true);
  }
}

async function loadExcelTasks(keepSelection = true) {
  const listNode = document.getElementById("excel-task-list");
  const filter = document.getElementById("excel-task-status-filter");
  if (!listNode || excelWorkspaceLoading) return;
  excelWorkspaceLoading = true;
  excelShowError("");
  listNode.className = "excel-task-list loading";
  listNode.textContent = "加载处理记录中...";
  const status = filter ? filter.value : "";
  const query = status ? `?status=${encodeURIComponent(status)}&limit=200` : "?limit=200";
  try {
    const response = await fetch(`/api/excel-tasks${query}`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const body = await excelReadJson(response);
    if (!response.ok || !body || body.ok !== true) {
      if (response.status === 503 && body && body.error && body.error.type === "NotConfigured") {
        excelTasks = [];
        selectedExcelTaskId = null;
        listNode.className = "excel-task-list is-empty";
        listNode.textContent = "未配置 approved roots";
        excelSetStatus("Excel 文件处理服务未配置");
        renderEmptyExcelTaskDetail();
        return;
      }
      throw new Error(excelApiMessage(body, "Excel 处理记录加载失败"));
    }
    excelTasks = Array.isArray(body.data) ? body.data : [];
    if (!keepSelection || !excelTasks.some((task) => task.id === selectedExcelTaskId)) {
      selectedExcelTaskId = excelTasks.length > 0 ? excelTasks[0].id : null;
    }
    renderExcelTaskList();
    if (selectedExcelTaskId !== null) await loadExcelTaskDetail(selectedExcelTaskId);
    else renderEmptyExcelTaskDetail();
  } catch (error) {
    excelTasks = [];
    listNode.className = "excel-task-list is-empty";
    listNode.textContent = "加载失败";
    excelShowError(error instanceof Error ? error.message : String(error));
    renderEmptyExcelTaskDetail();
  } finally {
    excelWorkspaceLoading = false;
  }
}

function renderExcelTaskList() {
  const listNode = document.getElementById("excel-task-list");
  if (!listNode) return;
  listNode.textContent = "";
  listNode.className = "excel-task-list";
  if (excelTasks.length === 0) {
    listNode.classList.add("is-empty");
    listNode.textContent = "暂无处理记录";
    return;
  }
  excelTasks.forEach((task) => {
    const button = excelEl("button", "excel-task-item");
    button.type = "button";
    if (task.id === selectedExcelTaskId) button.classList.add("active");
    const head = excelEl("div", "excel-task-item-head");
    head.appendChild(excelEl("span", "excel-task-item-title", `#${task.id} ${safeDisplayValue(task.operation)}`));
    head.appendChild(excelStatusChip(task.status));
    const meta = excelEl("div", "excel-task-item-meta");
    meta.appendChild(excelEl("span", null, `尝试 ${task.attemptCount}/${task.maxAttempts}`));
    meta.appendChild(excelEl("span", null, excelFormatDate(task.updatedAt)));
    button.append(head, meta);
    button.addEventListener("click", async () => {
      selectedExcelTaskId = task.id;
      renderExcelTaskList();
      await loadExcelTaskDetail(task.id);
    });
    listNode.appendChild(button);
  });
}

function renderEmptyExcelTaskDetail() {
  const detail = document.getElementById("excel-task-detail");
  const runs = document.getElementById("excel-task-runs");
  const artifacts = document.getElementById("excel-task-artifact-list");
  if (detail) {
    detail.className = "excel-task-detail is-empty";
    detail.textContent = "请选择处理记录";
  }
  if (runs) {
    runs.className = "excel-task-table-wrap is-empty";
    runs.textContent = "暂无处理记录";
  }
  if (artifacts) {
    artifacts.className = "excel-task-table-wrap is-empty";
    artifacts.textContent = "暂无输出文件";
  }
}

async function loadExcelTaskDetail(taskId) {
  const detail = document.getElementById("excel-task-detail");
  const runsNode = document.getElementById("excel-task-runs");
  const artifactsNode = document.getElementById("excel-task-artifact-list");
  if (!detail || !runsNode || !artifactsNode) return;
  detail.className = "excel-task-detail";
  detail.textContent = "加载处理详情中...";
  runsNode.className = "excel-task-table-wrap is-empty";
  runsNode.textContent = "加载处理历史中...";
  artifactsNode.className = "excel-task-table-wrap is-empty";
  artifactsNode.textContent = "加载输出文件中...";
  try {
    const [taskResponse, runsResponse, artifactsResponse] = await Promise.all([
      fetch(`/api/excel-tasks/${encodeURIComponent(taskId)}`, { headers: { Accept: "application/json" }, cache: "no-store" }),
      fetch(`/api/excel-tasks/${encodeURIComponent(taskId)}/runs`, { headers: { Accept: "application/json" }, cache: "no-store" }),
      fetch(`/api/excel-tasks/${encodeURIComponent(taskId)}/artifacts`, { headers: { Accept: "application/json" }, cache: "no-store" }),
    ]);
    const [taskBody, runsBody, artifactsBody] = await Promise.all([
      excelReadJson(taskResponse),
      excelReadJson(runsResponse),
      excelReadJson(artifactsResponse),
    ]);
    if (!taskResponse.ok || !taskBody || taskBody.ok !== true) {
      throw new Error(excelApiMessage(taskBody, "Excel 处理详情加载失败"));
    }
    if (!runsResponse.ok || !runsBody || runsBody.ok !== true) {
      throw new Error(excelApiMessage(runsBody, "Excel 处理历史加载失败"));
    }
    if (!artifactsResponse.ok || !artifactsBody || artifactsBody.ok !== true) {
      throw new Error(excelApiMessage(artifactsBody, "Excel 输出文件加载失败"));
    }
    renderExcelTaskDetail(taskBody.data || {});
    renderExcelTaskRuns(Array.isArray(runsBody.data) ? runsBody.data : []);
    renderExcelTaskArtifacts(Array.isArray(artifactsBody.data) ? artifactsBody.data : []);
  } catch (error) {
    detail.className = "excel-task-detail is-empty";
    detail.textContent = "处理详情加载失败";
    runsNode.className = "excel-task-table-wrap is-empty";
    runsNode.textContent = "处理历史不可用";
    artifactsNode.className = "excel-task-table-wrap is-empty";
    artifactsNode.textContent = "输出文件不可用";
    excelShowError(error instanceof Error ? error.message : String(error));
  }
}

function renderExcelTaskDetail(task) {
  const detail = document.getElementById("excel-task-detail");
  if (!detail) return;
  detail.textContent = "";
  detail.className = "excel-task-detail";
  const head = excelEl("div", "excel-task-detail-head");
  const title = excelEl("div");
  title.appendChild(excelEl("p", "eyebrow", `TASK #${task.id}`));
  title.appendChild(excelEl("h4", null, safeDisplayValue(task.operation)));
  head.append(title, excelStatusChip(task.status));
  detail.appendChild(head);

  const grid = excelEl("div", "excel-task-detail-grid");
  const cells = [
    ["创建时间", excelFormatDate(task.createdAt)],
    ["开始时间", excelFormatDate(task.startedAt)],
    ["完成时间", excelFormatDate(task.finishedAt)],
    ["尝试次数", `${task.attemptCount}/${task.maxAttempts}`],
    ["文件引用", Array.isArray(task.files) ? String(task.files.length) : "0"],
    ["错误", task.errorMessage || task.errorType || "-"],
  ];
  cells.forEach(([label, value]) => {
    const cell = excelEl("div", "excel-task-detail-cell");
    cell.append(excelEl("span", null, label), excelEl("span", null, safeDisplayValue(value)));
    grid.appendChild(cell);
  });
  detail.appendChild(grid);
}

function renderExcelTaskRuns(runs) {
  const container = document.getElementById("excel-task-runs");
  if (!container) return;
  container.textContent = "";
  if (runs.length === 0) {
    container.className = "excel-task-table-wrap is-empty";
    container.textContent = "暂无运行记录";
    return;
  }
  container.className = "excel-task-table-wrap";
  const table = excelEl("table", "excel-task-table");
  const thead = excelEl("thead");
  const headRow = excelEl("tr");
  ["Run", "尝试", "状态", "开始时间", "完成时间", "错误"].forEach((label) => headRow.appendChild(excelEl("th", null, label)));
  thead.appendChild(headRow);
  const tbody = excelEl("tbody");
  runs.forEach((run) => {
    const row = excelEl("tr");
    row.appendChild(excelEl("td", null, `#${run.id}`));
    row.appendChild(excelEl("td", null, String(run.attempt)));
    const stateCell = excelEl("td");
    stateCell.appendChild(excelStatusChip(run.runState));
    row.appendChild(stateCell);
    row.appendChild(excelEl("td", null, excelFormatDate(run.startedAt || run.createdAt)));
    row.appendChild(excelEl("td", null, excelFormatDate(run.finishedAt)));
    row.appendChild(excelEl("td", null, safeDisplayValue(run.errorMessage || run.errorType || "-")));
    tbody.appendChild(row);
  });
  table.append(thead, tbody);
  container.appendChild(table);
}

function renderExcelTaskArtifacts(artifacts) {
  const container = document.getElementById("excel-task-artifact-list");
  if (!container) return;
  container.textContent = "";
  if (artifacts.length === 0) {
    container.className = "excel-task-table-wrap is-empty";
    container.textContent = "暂无输出文件";
    return;
  }
  container.className = "excel-task-table-wrap";
  const table = excelEl("table", "excel-task-table");
  const thead = excelEl("thead");
  const headRow = excelEl("tr");
  ["名称", "大小", "SHA-256", "生成时间", "操作"].forEach((label) => headRow.appendChild(excelEl("th", null, label)));
  thead.appendChild(headRow);
  const tbody = excelEl("tbody");
  artifacts.forEach((artifact) => {
    const row = excelEl("tr");
    row.appendChild(excelEl("td", null, safeDisplayValue(artifact.displayName)));
    row.appendChild(excelEl("td", null, excelFormatSize(artifact.sizeBytes)));
    row.appendChild(excelEl("td", null, safeDisplayValue(artifact.sha256)));
    row.appendChild(excelEl("td", null, excelFormatDate(artifact.createdAt)));
    const actionCell = excelEl("td");
    const downloadButton = excelEl("button", "excel-download-btn", "下载");
    downloadButton.type = "button";
    downloadButton.addEventListener("click", () => downloadExcelArtifact(artifact, downloadButton));
    const auditButton = excelEl("button", "excel-audit-btn", "下载记录");
    auditButton.type = "button";
    actionCell.append(downloadButton, auditButton);
    row.appendChild(actionCell);
    tbody.appendChild(row);

    const auditRow = excelEl("tr", "excel-artifact-audit-row");
    auditRow.hidden = true;
    const auditCell = excelEl("td");
    auditCell.colSpan = 5;
    const auditBox = excelEl("div", "excel-artifact-audit-box");
    auditCell.appendChild(auditBox);
    auditRow.appendChild(auditCell);
    tbody.appendChild(auditRow);
    auditButton.addEventListener("click", () => toggleExcelArtifactAudit(artifact, auditButton, auditRow, auditBox));
  });
  table.append(thead, tbody);
  container.appendChild(table);
}

async function toggleExcelArtifactAudit(artifact, button, row, box) {
  if (!row.hidden) {
    row.hidden = true;
    button.textContent = "下载记录";
    return;
  }
  row.hidden = false;
  button.textContent = "收起";
  box.className = "excel-artifact-audit-box is-empty";
  box.textContent = "加载下载记录中...";
  try {
    const response = await fetch(`/api/excel-artifacts/${encodeURIComponent(artifact.id)}/download-audit?limit=50`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const body = await excelReadJson(response);
    if (!response.ok || !body || body.ok !== true) {
      throw new Error(excelApiMessage(body, "下载记录加载失败"));
    }
    const audits = Array.isArray(body.data) ? body.data : [];
    box.textContent = "";
    if (audits.length === 0) {
      box.className = "excel-artifact-audit-box is-empty";
      box.textContent = "暂无下载记录";
      return;
    }
    box.className = "excel-artifact-audit-box";
    const table = excelEl("table", "excel-task-table excel-audit-table");
    const thead = excelEl("thead");
    const headRow = excelEl("tr");
    ["结果", "原因", "传输大小", "时间"].forEach((label) => headRow.appendChild(excelEl("th", null, label)));
    thead.appendChild(headRow);
    const tbody = excelEl("tbody");
    audits.forEach((audit) => {
      const auditDataRow = excelEl("tr");
      const resultCell = excelEl("td");
      resultCell.appendChild(excelStatusChip(audit.result === "succeeded" ? "succeeded" : "failed"));
      auditDataRow.appendChild(resultCell);
      auditDataRow.appendChild(excelEl("td", null, safeDisplayValue(audit.reasonCode)));
      auditDataRow.appendChild(excelEl("td", null, excelFormatSize(audit.servedSizeBytes)));
      auditDataRow.appendChild(excelEl("td", null, excelFormatDate(audit.createdAt)));
      tbody.appendChild(auditDataRow);
    });
    table.append(thead, tbody);
    box.appendChild(table);
  } catch (error) {
    box.className = "excel-artifact-audit-box is-empty";
    box.textContent = redactSensitiveText(error instanceof Error ? error.message : String(error));
  }
}

async function loadExcelRetentionPlan() {
  const container = document.getElementById("excel-retention-plan");
  const input = document.getElementById("excel-retention-days");
  const button = document.getElementById("excel-retention-preview-btn");
  if (!container || !input || !button) return;
  const days = Number(input.value);
  if (!Number.isInteger(days) || days < 1 || days > 3650) {
    excelShowError("保留天数必须是 1 到 3650 的整数");
    return;
  }
  button.disabled = true;
  excelShowError("");
  container.className = "excel-task-table-wrap is-empty";
  container.textContent = "正在生成文件清理建议...";
  try {
    const response = await fetch(`/api/excel-artifacts/retention-plan?retentionDays=${encodeURIComponent(days)}&limit=500`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const body = await excelReadJson(response);
    if (!response.ok || !body || body.ok !== true) {
      throw new Error(excelApiMessage(body, "文件清理建议生成失败"));
    }
    const data = body.data || {};
    const artifacts = Array.isArray(data.artifacts) ? data.artifacts : [];
    container.textContent = "";
    if (artifacts.length === 0) {
      container.className = "excel-task-table-wrap is-empty";
      container.textContent = `截止 ${excelFormatDate(data.cutoffAt)} 没有建议清理的文件`;
      return;
    }
    container.className = "excel-task-table-wrap";
    const summary = excelEl(
      "p",
      "excel-retention-summary",
      `${artifacts.length} 个文件 · 截止 ${excelFormatDate(data.cutoffAt)}${data.truncated ? " · 仅显示部分结果" : ""}`,
    );
    const table = excelEl("table", "excel-task-table");
    const thead = excelEl("thead");
    const headRow = excelEl("tr");
    ["文件编号", "处理记录", "名称", "大小", "生成时间"].forEach((label) => headRow.appendChild(excelEl("th", null, label)));
    thead.appendChild(headRow);
    const tbody = excelEl("tbody");
    artifacts.forEach((artifact) => {
      const row = excelEl("tr");
      row.appendChild(excelEl("td", null, `#${artifact.id}`));
      row.appendChild(excelEl("td", null, `#${artifact.taskId}`));
      row.appendChild(excelEl("td", null, safeDisplayValue(artifact.displayName)));
      row.appendChild(excelEl("td", null, excelFormatSize(artifact.sizeBytes)));
      row.appendChild(excelEl("td", null, excelFormatDate(artifact.createdAt)));
      tbody.appendChild(row);
    });
    table.append(thead, tbody);
    container.append(summary, table);
  } catch (error) {
    container.className = "excel-task-table-wrap is-empty";
    container.textContent = "文件清理建议不可用";
    excelShowError(error instanceof Error ? error.message : String(error));
  } finally {
    button.disabled = false;
  }
}

async function downloadExcelArtifact(artifact, button) {
  button.disabled = true;
  excelShowError("");
  excelSetStatus(`正在下载 ${safeDisplayValue(artifact.displayName)}...`);
  try {
    const response = await fetch(`/api/excel-artifacts/${encodeURIComponent(artifact.id)}/download`, {
      headers: { Accept: "application/octet-stream" },
      cache: "no-store",
    });
    if (!response.ok) {
      const body = await excelReadJson(response);
      throw new Error(excelApiMessage(body, "Excel 输出文件下载失败"));
    }
    const blob = await response.blob();
    const fileName = parseContentDispositionFilename(response.headers.get("Content-Disposition"))
      || artifact.displayName
      || "excel-artifact.xlsx";
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = fileName;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    excelSetStatus(`已下载 ${safeDisplayValue(fileName)}`);
  } catch (error) {
    excelSetStatus("");
    excelShowError(error instanceof Error ? error.message : String(error));
  } finally {
    button.disabled = false;
  }
}

async function loadExcelTaskWorkspace() {
  await Promise.all([loadExcelRoots(), loadExcelWorkerStatus(), loadExcelTasks(true)]);
}

function setupExcelTaskAdmin() {
  const refreshButton = document.getElementById("excel-task-refresh-btn");
  if (refreshButton) refreshButton.addEventListener("click", () => loadExcelTaskWorkspace());
  const startButton = document.getElementById("excel-worker-start-btn");
  if (startButton) startButton.addEventListener("click", () => mutateExcelWorker("start"));
  const stopButton = document.getElementById("excel-worker-stop-btn");
  if (stopButton) stopButton.addEventListener("click", () => mutateExcelWorker("stop"));
  const filter = document.getElementById("excel-task-status-filter");
  if (filter) filter.addEventListener("change", () => loadExcelTasks(false));
  const operation = document.getElementById("excel-task-operation");
  if (operation) operation.addEventListener("change", updateExcelCreateFields);
  const createForm = document.getElementById("excel-task-create-form");
  if (createForm) createForm.addEventListener("submit", createExcelTask);
  const regenerateButton = document.getElementById("excel-regenerate-key-btn");
  if (regenerateButton) regenerateButton.addEventListener("click", refreshExcelIdempotencyKey);
  const retentionButton = document.getElementById("excel-retention-preview-btn");
  if (retentionButton) retentionButton.addEventListener("click", loadExcelRetentionPlan);
  refreshExcelIdempotencyKey();
  updateExcelCreateFields();
  populateExcelRootSelects();
}

/* ── Scheduled Archive Administration Module ────────────────────────── */

let archiveJobs = [];
let archiveJobsLoading = false;
let selectedArchiveJobKey = "";
let archiveSelectedRunId = null;
let archiveHistoryTab = "runs"; // 'runs' | 'audit'
let archiveMutating = false;

const ARCHIVE_JOB_NAMES = {
  aras_ewo: "Aras EWO 变更记录",
  aras_paa: "Aras PAA 变更记录",
  aras_ncr_progress: "Aras NCR 审批进度",
  aras_ncr_detail: "Aras NCR 审批明细",
  tdc_data_model: "数模设计审核流程报表",
  tdc_sor: "TDC SOR",
};

const ARCHIVE_SOURCE_LABELS = {
  aras: "ECM 流程",
  tdc: "TDC 研发",
};

const ARCHIVE_FILTER_FIELDS = {
  tdc_data_model: [
    { name: "incident", label: "流水号", placeholder: "例如 WF-2026-001" },
    { name: "applicant", label: "申请人", placeholder: "例如 张三" },
    { name: "department", label: "部门", placeholder: "例如 技术中心" },
    { name: "section", label: "科室", placeholder: "例如 车体工程" },
    { name: "applicationStart", label: "申请开始", type: "date" },
    { name: "applicationEnd", label: "申请结束", type: "date" },
    { name: "projectModel", label: "项目/车型", placeholder: "例如 F610S" },
    { name: "partNumber", label: "零件号", placeholder: "可填写部分编号" },
    { name: "modelNumber", label: "数模号", placeholder: "可填写部分编号" },
  ],
  tdc_sor: [
    { name: "processNo", label: "流水号" },
    { name: "processType", label: "流程类型" },
    { name: "carTypeProject", label: "车型项目" },
    { name: "applicant", label: "申请人" },
    { name: "title", label: "标题" },
    { name: "department", label: "部门" },
    { name: "section", label: "科室" },
    { name: "applicationStart", label: "申请开始", type: "date" },
    { name: "applicationEnd", label: "申请结束", type: "date" },
    { name: "partNumber", label: "零件号" },
    { name: "partName", label: "零件名称" },
    { name: "version", label: "版本" },
    { name: "sorNumber", label: "SOR 编号" },
    { name: "latestCompletedNode", label: "最近完成节点" },
    { name: "approvalStatus", label: "审批状态" },
  ],
  aras_ewo: [
    { name: "ewoNo", label: "EWO 编号", placeholder: "支持 * 模糊和 | 并集" },
    { name: "projectCode", label: "项目代码", placeholder: "支持 * 模糊和 | 并集" },
    { name: "subjectKeyword", label: "主题关键词", placeholder: "支持 * 模糊和 | 并集" },
    { name: "changeType", label: "变更类型" },
    { name: "changeSubType", label: "变更子类型" },
    { name: "area", label: "区域", placeholder: "支持 * 模糊和 | 并集" },
    { name: "state", label: "状态" },
    { name: "responsibleDepartment", label: "响应部门", placeholder: "支持 * 模糊和 | 并集" },
    { name: "submitStart", label: "提交开始", type: "date" },
    { name: "submitEnd", label: "提交结束", type: "date" },
  ],
  aras_paa: [
    { name: "paaNo", label: "PAA 编号", placeholder: "支持 * 模糊和 | 并集" },
    { name: "ewoNo", label: "EWO 编号", placeholder: "支持 * 模糊和 | 并集" },
    { name: "state", label: "状态" },
    { name: "area", label: "区域", placeholder: "支持 * 模糊和 | 并集" },
    { name: "base", label: "基地", placeholder: "支持 * 模糊和 | 并集" },
    { name: "department", label: "业务部门", placeholder: "例如 技术中心-车体工程" },
    { name: "vehicleKeyword", label: "车辆关键词", placeholder: "支持 * 模糊和 | 并集" },
    { name: "submitStart", label: "提交开始", type: "date" },
    { name: "submitEnd", label: "提交结束", type: "date" },
    { name: "materialRequestStart", label: "物料需求开始", type: "date" },
    { name: "materialRequestEnd", label: "物料需求结束", type: "date" },
  ],
  aras_ncr_progress: [
    { name: "buyStart", label: "采购开始", type: "date" },
    { name: "buyEnd", label: "采购结束", type: "date" },
    { name: "peStart", label: "PE 开始", type: "date" },
    { name: "peEnd", label: "PE 结束", type: "date" },
    { name: "ncrNo", label: "NCR 编号", placeholder: "支持系统查询符号" },
    { name: "projectNames", label: "项目名称", list: true, placeholder: "多个项目用逗号分隔" },
    { name: "sectionCode", label: "区段代码" },
    { name: "changeType", label: "变更类型" },
    { name: "otherCondition", label: "其他条件", placeholder: "默认 0" },
  ],
  aras_ncr_detail: [
    { name: "buyStart", label: "采购开始", type: "date" },
    { name: "buyEnd", label: "采购结束", type: "date" },
    { name: "peStart", label: "PE 开始", type: "date" },
    { name: "peEnd", label: "PE 结束", type: "date" },
    { name: "ncrNo", label: "NCR 编号", placeholder: "支持系统查询符号" },
    { name: "projectNames", label: "项目名称", list: true, placeholder: "多个项目用逗号分隔" },
    { name: "sectionCode", label: "区段代码" },
    { name: "changeType", label: "变更类型" },
    { name: "otherCondition", label: "其他条件", placeholder: "默认 0" },
  ],
};

const ARCHIVE_FILTER_LIST_FIELDS = new Set(["projectNames", "sectionCodes"]);

function archiveEl(tagName, className, text) {
  const node = document.createElement(tagName);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function clearArchiveContainer(container) {
  if (container) container.textContent = "";
}

function archiveFilterFieldsFor(job) {
  return ARCHIVE_FILTER_FIELDS[job.templateKey] || [];
}

function archiveFilterDisplayValue(value) {
  if (Array.isArray(value)) return value.join(", ");
  return value === null || value === undefined ? "" : String(value);
}

function collectArchiveFilterControls(container) {
  const result = {};
  if (!container) return result;
  container.querySelectorAll("[data-archive-filter-name]").forEach((input) => {
    const name = input.dataset.archiveFilterName;
    if (!name) return;
    const raw = String(input.value || "").trim();
    if (!raw) return;
    if (ARCHIVE_FILTER_LIST_FIELDS.has(name)) {
      const values = raw.split(/[,\n]/).map((item) => item.trim()).filter(Boolean);
      if (values.length) result[name] = values;
    } else {
      result[name] = raw;
    }
  });
  return result;
}

function renderArchiveFilterControls(job, textarea) {
  const section = archiveEl("div", "archive-filter-form-section");
  section.appendChild(archiveEl("p", "archive-filter-form-title", "常用筛选条件"));
  const controls = archiveEl("div", "archive-filter-controls");
  const fields = archiveFilterFieldsFor(job);
  if (!fields.length) {
    controls.appendChild(archiveEl("p", "field-note", "此任务模板没有可配置的筛选条件"));
  }
  fields.forEach((field) => {
    const label = archiveEl("label", "archive-filter-field");
    const span = archiveEl("span", null, field.label || field.name);
    const input = document.createElement("input");
    input.type = field.type === "date" ? "date" : "text";
    input.name = `archive-filter-${field.name}`;
    input.dataset.archiveFilterName = field.name;
    input.placeholder = field.placeholder || "可选";
    input.title = field.list ? "多个值请用逗号分隔" : "留空表示不筛选";
    input.value = archiveFilterDisplayValue((job.filters || {})[field.name]);
    label.append(span, input);
    controls.appendChild(label);
  });
  section.appendChild(controls);
  controls.querySelectorAll("[data-archive-filter-name]").forEach((input) => {
    input.addEventListener("input", () => {
      textarea.value = JSON.stringify(collectArchiveFilterControls(controls), null, 2);
    });
  });
  return section;
}

async function openArchiveNativeFolder(initialPath, onSelect) {
  try {
    const response = await fetch("/api/scheduled-archive/folders/native", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ path: initialPath || "" }),
    });
    const body = await response.json();
    if (response.status === 503) return false;
    if (!response.ok || !body.ok) {
      throw new Error((body.error && body.error.message) || "无法打开文件夹选择器");
    }
    const selected = body.data && typeof body.data.path === "string" ? body.data.path : "";
    if (typeof onSelect === "function") onSelect(selected);
    return true;
  } catch (err) {
    showArchiveGlobalError(err instanceof Error ? err.message : String(err));
    return true;
  }
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

function archiveSyncStateLabel(syncState) {
  const labels = { needs_attention: "需关注", success: "正常", idle: "空闲", running: "同步中", failed: "失败" };
  return labels[syncState] || "待确认/未知";
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
      const err = (body.error && body.error.message) || "加载自动下载任务失败";
      showArchiveGlobalError(err);
      clearArchiveContainer(container);
      container.appendChild(archiveEl("p", "is-empty", "加载失败"));
      return;
    }
    archiveJobs = Array.isArray(body.data) ? body.data : [];
    overviewArchiveJobs = archiveJobs.slice();
    if (overviewSavedState) renderProjectOverview();
    renderArchiveJobsList(keepSelection);
  } catch (exc) {
    showArchiveGlobalError("网络异常或服务器未响应");
    clearArchiveContainer(container);
    container.appendChild(archiveEl("p", "is-empty", "加载失败"));
  } finally {
    archiveJobsLoading = false;
  }
}

async function handleArchiveJobArchive(job, triggerButton = null) {
  if (!job || archiveMutating) return;
  const displayName = job.displayName || job.jobKey;
  const taskKind = job.builtin ? "内置任务" : "自定义任务";
  if (!window.confirm(`确定要删除${taskKind}“${displayName}”吗？历史运行记录会保留。`)) return;

  archiveMutating = true;
  if (triggerButton) {
    triggerButton.disabled = true;
    triggerButton.textContent = "删除中...";
  }
  setArchiveGlobalStatus("正在删除任务...");
  try {
    const response = await fetch(`/api/scheduled-archive/jobs/${encodeURIComponent(job.jobKey)}`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ updatedAt: job.updatedAt }),
    });
    const body = await response.json();
    if (!response.ok || !body.ok) {
      throw new Error((body.error && body.error.message) || "删除任务失败");
    }
    if (selectedArchiveJobKey === job.jobKey) selectedArchiveJobKey = "";
    setArchiveGlobalStatus("任务已删除，历史运行记录已保留");
    await loadArchiveJobs(false);
  } catch (err) {
    showArchiveGlobalError(err instanceof Error ? err.message : String(err));
  } finally {
    archiveMutating = false;
    if (triggerButton) {
      triggerButton.disabled = false;
      triggerButton.textContent = "删除任务";
    }
  }
}

function renderArchiveJobsList(keepSelection) {
  const container = document.getElementById("archive-jobs-list");
  if (!container) return;
  clearArchiveContainer(container);

  if (archiveJobs.length === 0) {
    container.appendChild(archiveEl("p", "is-empty", "暂无自动下载任务"));
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
    const item = archiveEl("article", "archive-job-item");
    if (job.jobKey === selectedArchiveJobKey) item.classList.add("active");
    if (!job.enabled) item.classList.add("is-disabled");

    const selectBtn = archiveEl("button", "archive-job-select");
    selectBtn.type = "button";
    selectBtn.setAttribute("aria-pressed", job.jobKey === selectedArchiveJobKey ? "true" : "false");

    const head = archiveEl("div", "archive-job-head");
    const title = archiveEl("span", "archive-job-title", ARCHIVE_JOB_NAMES[job.jobKey] || job.jobKey);
    const freshness = archiveFreshnessChip(job.freshness);
    head.appendChild(title);
    head.appendChild(freshness);

    const meta = archiveEl("div", "archive-job-meta");
    const sourceText = ARCHIVE_SOURCE_LABELS[job.sourceType] || "未知来源";
    const deliverableText = job.deliverableId ? ` · 关联交付物 ${job.deliverableId}` : "";
    meta.textContent = `${sourceText}${deliverableText}`;

    const metrics = archiveEl("div", "archive-job-metrics");
    const enabledChip = archiveEl("span", "archive-chip", job.enabled ? "已启用" : "未启用");
    if (job.enabled) enabledChip.classList.add("is-fresh");
    else enabledChip.classList.add("is-unknown");

    const credentialAvailable = job.credentialAvailable === undefined
      ? Boolean(job.credentialConfigured)
      : Boolean(job.credentialAvailable);
    const credentialText = !job.credentialConfigured
      ? "登录信息未设置"
      : credentialAvailable
        ? "登录信息可用"
        : "登录信息不可用";
    const credChip = archiveEl("span", "archive-chip", credentialText);
    if (credentialAvailable) credChip.classList.add("is-fresh");
    else credChip.classList.add("is-needs-attention");

    metrics.appendChild(enabledChip);
    metrics.appendChild(credChip);
    metrics.appendChild(archiveSyncStateChip(job.syncState));

    selectBtn.appendChild(head);
    selectBtn.appendChild(meta);
    selectBtn.appendChild(metrics);

    selectBtn.addEventListener("click", () => {
      if (selectedArchiveJobKey === job.jobKey) return;
      selectedArchiveJobKey = job.jobKey;
      renderArchiveJobsList(true);
    });

    const actions = archiveEl("div", "archive-job-actions");
    const deleteButton = archiveEl("button", "archive-job-delete-btn", "删除任务");
    deleteButton.type = "button";
    deleteButton.title = job.builtin
      ? "删除内置任务并保留历史运行记录"
      : "删除自定义任务并保留历史运行记录";
    deleteButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      void handleArchiveJobArchive(job, deleteButton);
    });
    actions.appendChild(deleteButton);
    item.appendChild(selectBtn);
    item.appendChild(actions);

    container.appendChild(item);
  });

  renderArchiveConfigCard(selectedJob);
  loadArchiveHistory();
}

async function loadArchiveFolders(container, path = "", onSelect = null) {
  clearArchiveContainer(container);
  const loading = archiveEl("p", "loading", "正在读取安全目录...");
  loading.setAttribute("role", "status");
  loading.setAttribute("aria-live", "polite");
  container.appendChild(loading);

  try {
    const resp = await fetch("/api/scheduled-archive/folders?path=" + encodeURIComponent(path), {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const body = await resp.json();
    if (!resp.ok || !body || body.ok !== true) {
      const err = (body && body.error && body.error.message) || "读取安全目录失败";
      clearArchiveContainer(container);
      const errBox = archiveEl("p", "error-msg", redactSensitiveText(err));
      errBox.setAttribute("role", "alert");
      container.appendChild(errBox);
      return;
    }
    const data = body.data || { current: "", parent: "", folders: [] };
    renderArchiveFolderBrowser(container, data, onSelect);
  } catch (_e) {
    clearArchiveContainer(container);
    const errBox = archiveEl("p", "error-msg", "网络异常，无法读取目录列表");
    errBox.setAttribute("role", "alert");
    container.appendChild(errBox);
  }
}

function renderArchiveFolderBrowser(container, data, onSelect) {
  clearArchiveContainer(container);
  const head = archiveEl("div", "folder-picker-head");
  head.appendChild(archiveEl("span", "folder-picker-current", `当前目录: ${data.current || "根目录"}`));

  const actions = archiveEl("div", "folder-picker-actions");
  if (data.current) {
    const selectBtn = archiveEl("button", "primary-btn folder-select-btn", "选择此目录");
    selectBtn.type = "button";
    selectBtn.addEventListener("click", () => {
      if (typeof onSelect === "function") onSelect(data.current);
    });
    actions.appendChild(selectBtn);
  } else {
    const selectRootBtn = archiveEl("button", "primary-btn folder-select-btn", "选择根目录 (留空)");
    selectRootBtn.type = "button";
    selectRootBtn.addEventListener("click", () => {
      if (typeof onSelect === "function") onSelect("");
    });
    actions.appendChild(selectRootBtn);
  }

  if (data.parent !== undefined && data.parent !== null && data.current !== "") {
    const upBtn = archiveEl("button", "segment folder-nav-btn", `返回上级 (${data.parent || "根目录"})`);
    upBtn.type = "button";
    upBtn.addEventListener("click", () => {
      loadArchiveFolders(container, data.parent || "", onSelect);
    });
    actions.appendChild(upBtn);
  }
  head.appendChild(actions);
  container.appendChild(head);

  const list = archiveEl("div", "folder-picker-list");
  const folders = Array.isArray(data.folders) ? data.folders : [];
  if (folders.length === 0) {
    list.appendChild(archiveEl("p", "is-empty", "此目录下无子文件夹"));
  } else {
    folders.forEach((folder) => {
      if (!folder || typeof folder !== "object"
          || typeof folder.name !== "string"
          || typeof folder.relativePath !== "string") return;
      const folderName = folder.name;
      const relativePath = folder.relativePath;
      const row = archiveEl("div", "folder-picker-item");
      const folderBtn = archiveEl("button", "folder-name-btn", `📁 ${folderName}`);
      folderBtn.type = "button";
      folderBtn.addEventListener("click", () => {
        loadArchiveFolders(container, relativePath, onSelect);
      });
      const pickBtn = archiveEl("button", "segment folder-pick-direct-btn", "选取");
      pickBtn.type = "button";
      pickBtn.addEventListener("click", () => {
        if (typeof onSelect === "function") onSelect(relativePath);
      });
      row.append(folderBtn, pickBtn);
      list.appendChild(row);
    });
  }
  container.appendChild(list);
}

function renderArchiveConfigCard(job) {
  const card = document.getElementById("archive-config-card");
  if (!card) return;
  clearArchiveContainer(card);

  if (!job) {
    card.classList.add("is-empty");
    card.appendChild(archiveEl("p", "loading", "请选择自动下载任务"));
    return;
  }
  card.classList.remove("is-empty");

  const head = archiveEl("div", "archive-config-head");
  const titleGroup = archiveEl("div");
  const eyebrow = archiveEl("p", "eyebrow", ARCHIVE_SOURCE_LABELS[job.sourceType] || "业务系统");
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
  addCell("最近下载状态", syncStateText);
  const intervalText = (Number.isInteger(job.intervalMinutes) && job.intervalMinutes > 0)
    ? `${job.intervalMinutes} 分钟`
    : "待确认/未知";
  addCell("自动执行频率", intervalText);
  addCell("最近成功", archiveFormatDate(job.lastSuccessAt));
  addCell("最近尝试", archiveFormatDate(job.lastAttemptAt));
  const retrySummary = (job.retryPolicy && Number.isInteger(job.retryPolicy.max_attempts)
    && job.retryPolicy.max_attempts > 0)
    ? `最多尝试 ${job.retryPolicy.max_attempts} 次（失败后重试 ${Math.max(0, job.retryPolicy.max_attempts - 1)} 次）`
    : "待确认/未知";
  addCell("失败后重试", retrySummary);

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
  const enabledSpan = archiveEl("span", null, job.builtin ? "启用自动下载（内置任务可禁用）" : "启用自动下载");
  enabledLabel.appendChild(enabledInput);
  enabledLabel.appendChild(enabledSpan);
  formGrid.appendChild(enabledLabel);

  // 1b. Interval Minutes Input (Frequency)
  const intervalLabel = archiveEl("label", null);
  const intervalSpan = archiveEl("span", null, "自动执行频率（分钟）");
  const intervalInput = document.createElement("input");
  intervalInput.type = "number";
  intervalInput.name = "intervalMinutes";
  intervalInput.id = "archive-field-interval";
  intervalInput.min = "5";
  intervalInput.max = "10080";
  intervalInput.value = Number.isInteger(job.intervalMinutes) && job.intervalMinutes > 0 ? String(job.intervalMinutes) : "60";
  intervalLabel.appendChild(intervalSpan);
  intervalLabel.appendChild(intervalInput);
  formGrid.appendChild(intervalLabel);

  // 1c. Retry policy: the number is total attempts, not retries.
  const retryLabel = archiveEl("label", null);
  const retrySpan = archiveEl("span", null, "失败后最多尝试次数");
  const retryInput = document.createElement("input");
  retryInput.type = "number";
  retryInput.name = "retryMaxAttempts";
  retryInput.id = "archive-field-retry-max-attempts";
  retryInput.min = "1";
  retryInput.max = "2";
  retryInput.value = job.retryPolicy && Number.isInteger(job.retryPolicy.max_attempts)
    ? String(job.retryPolicy.max_attempts)
    : "2";
  retryInput.title = "1 表示失败不重试，2 表示失败后重试 1 次";
  retryLabel.append(retrySpan, retryInput);
  formGrid.appendChild(retryLabel);

  // 2. Credential Reference (a non-secret selector, never a password field)
  const aliasLabel = archiveEl("label", null);
  const aliasSpan = archiveEl("span", null, "定时登录信息");
  const aliasInput = document.createElement("select");
  aliasInput.name = "credentialRef";
  aliasInput.id = "archive-field-credential-ref";
  const keepCredential = archiveEl(
    "option",
    null,
    job.credentialConfigured ? "保持当前登录信息（不修改）" : "请选择统一域账号登录信息",
  );
  keepCredential.value = "";
  const domainCredential = archiveEl("option", null, "统一域账号（domain）");
  domainCredential.value = "domain";
  const compatibleCredential = archiveEl("option", null, "兼容引用（unified-domain）");
  compatibleCredential.value = "unified-domain";
  aliasInput.append(keepCredential, domainCredential, compatibleCredential);
  aliasLabel.appendChild(aliasSpan);
  aliasLabel.appendChild(aliasInput);
  aliasLabel.appendChild(
    archiveEl(
      "small",
      "field-note",
      "先到系统设置登录并勾选“保存至凭据保护库”；此处选择引用，不填写用户名或密码。",
    ),
  );
  formGrid.appendChild(aliasLabel);

  // 3. Clear Alias Option Checkbox
  const clearAliasLabel = archiveEl("label", "archive-checkbox-row");
  const clearAliasInput = document.createElement("input");
  clearAliasInput.type = "checkbox";
  clearAliasInput.name = "clearAlias";
  clearAliasInput.id = "archive-field-clear-alias";
  const clearAliasSpan = archiveEl("span", null, "清除已保存的定时登录信息");
  clearAliasLabel.appendChild(clearAliasInput);
  clearAliasLabel.appendChild(clearAliasSpan);
  formGrid.appendChild(clearAliasLabel);

  // 4. Task-level archive directory. Empty means the global Settings directory.
  const outputDirectoryLabel = archiveEl("label", "wide");
  const outputDirectorySpan = archiveEl("span", null, "归档目录");
  const outputDirectoryWrap = archiveEl("div", "archive-output-directory-control");
  const outputDirectoryInput = document.createElement("input");
  outputDirectoryInput.type = "text";
  outputDirectoryInput.name = "outputDirectory";
  outputDirectoryInput.id = "archive-field-output-directory";
  outputDirectoryInput.value = job.outputDirectory || "";
  outputDirectoryInput.placeholder = "例如：D:\\VSE\\archive（留空使用系统默认归档目录）";
  outputDirectoryInput.title = "选择的文件夹将直接作为此任务的归档目录";
  const nativeFolderBtn = archiveEl("button", "segment archive-native-folder-btn", "Windows 选择文件夹");
  nativeFolderBtn.type = "button";
  nativeFolderBtn.id = "archive-native-folder-btn";
  const resetDirectoryBtn = archiveEl("button", "segment archive-reset-directory-btn", "使用系统默认");
  resetDirectoryBtn.type = "button";
  resetDirectoryBtn.id = "archive-reset-directory-btn";
  outputDirectoryWrap.append(outputDirectoryInput, nativeFolderBtn, resetDirectoryBtn);
  outputDirectoryLabel.appendChild(outputDirectorySpan);
  outputDirectoryLabel.appendChild(outputDirectoryWrap);
  outputDirectoryLabel.appendChild(
    archiveEl(
      "small",
      "field-note",
      "Windows 选择哪个文件夹，就直接使用哪个文件夹；留空则使用系统设置中的全局归档目录。",
    ),
  );
  if (!job.outputDirectory && job.outputSubdir) {
    outputDirectoryInput.dataset.legacySubdir = job.outputSubdir;
    outputDirectoryLabel.appendChild(
      archiveEl(
        "small",
        "field-note archive-legacy-directory-note",
        `兼容旧版配置：当前还使用全局目录下的子目录“${job.outputSubdir}”；选择新目录后将替换它。`,
      ),
    );
  }
  formGrid.appendChild(outputDirectoryLabel);

  nativeFolderBtn.addEventListener("click", async () => {
    nativeFolderBtn.disabled = true;
    const handled = await openArchiveNativeFolder(
      outputDirectoryInput.value.trim(),
      (selectedPath) => {
        outputDirectoryInput.value = selectedPath;
        outputDirectoryInput.dataset.legacySubdir = "";
      },
    );
    nativeFolderBtn.disabled = false;
    if (!handled) {
      showArchiveGlobalError("Windows 文件夹选择器不可用，请直接输入本机绝对目录路径后保存");
    }
  });

  resetDirectoryBtn.addEventListener("click", () => {
    outputDirectoryInput.value = "";
    outputDirectoryInput.dataset.legacySubdir = "";
    showArchiveGlobalError("");
  });

  // 5. Advanced download conditions
  const advancedConditions = document.createElement("details");
  advancedConditions.className = "archive-advanced-conditions wide";
  const advancedSummary = document.createElement("summary");
  advancedSummary.textContent = "高级下载条件";
  advancedConditions.appendChild(advancedSummary);

  const allowedFilters = Array.isArray(job.allowedFilterNames) ? job.allowedFilterNames : [];
  const filtersInfoLabel = archiveEl("div", "wide");
  const filtersInfoSpan = archiveEl("span", null, "接口字段（高级信息）");
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
  advancedConditions.appendChild(filtersInfoLabel);

  // 6. Beginner-friendly fields plus compatibility JSON editor
  const filtersLabel = archiveEl("label", "wide");
  const filtersSpan = archiveEl("span", null, "下载条件 JSON");
  const filtersTextarea = document.createElement("textarea");
  filtersTextarea.name = "filters";
  filtersTextarea.id = "archive-field-filters";
  filtersTextarea.rows = 4;
  filtersTextarea.value = JSON.stringify(job.filters || {}, null, 2);

  advancedConditions.appendChild(renderArchiveFilterControls(job, filtersTextarea));

  const jsonDisclosure = document.createElement("details");
  jsonDisclosure.className = "archive-json-disclosure wide";
  const jsonSummary = document.createElement("summary");
  jsonSummary.textContent = "高级 JSON（兼容旧配置）";
  jsonDisclosure.appendChild(jsonSummary);
  filtersLabel.appendChild(filtersSpan);
  filtersLabel.appendChild(filtersTextarea);
  jsonDisclosure.appendChild(filtersLabel);
  advancedConditions.appendChild(jsonDisclosure);
  formGrid.appendChild(advancedConditions);

  formBlock.appendChild(formGrid);
  form.appendChild(formBlock);

  // Field Errors Container
  const fieldErrorsDiv = archiveEl("div", "error-msg");
  fieldErrorsDiv.id = "archive-form-errors";
  fieldErrorsDiv.hidden = true;
  form.appendChild(fieldErrorsDiv);

  // Action Buttons Row
  const actionsRow = archiveEl("div", "archive-actions-row");
  const saveBtn = archiveEl("button", "primary-btn", "保存设置");
  saveBtn.type = "submit";
  saveBtn.id = "archive-save-btn";

  const copyBtn = archiveEl("button", "segment archive-copy-job-btn", "复制任务");
  copyBtn.type = "button";
  copyBtn.addEventListener("click", () => {
    openCreateJobModal(job);
  });

  const syncNowBtn = archiveEl("button", "archive-btn-secondary", "立即下载一次");
  syncNowBtn.type = "button";
  syncNowBtn.id = "archive-sync-now-btn";
  syncNowBtn.disabled = !job.enabled || !(job.credentialAvailable ?? job.credentialConfigured);

  actionsRow.appendChild(saveBtn);
  actionsRow.appendChild(copyBtn);

  const cancelArchiveBtn = archiveEl("button", "segment archive-delete-job-btn", "删除任务");
  cancelArchiveBtn.type = "button";
  cancelArchiveBtn.style.color = "var(--error)";
  cancelArchiveBtn.addEventListener("click", () => {
    void handleArchiveJobArchive(job, cancelArchiveBtn);
  });
  actionsRow.appendChild(cancelArchiveBtn);

  actionsRow.appendChild(syncNowBtn);

  const formStatus = archiveEl("span", "archive-status-msg");
  formStatus.id = "archive-form-status";
  formStatus.setAttribute("aria-live", "polite");
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
  const outputDirectoryInput = document.getElementById("archive-field-output-directory");
  const filtersTextarea = document.getElementById("archive-field-filters");

  const intervalInput = document.getElementById("archive-field-interval");
  const retryInput = document.getElementById("archive-field-retry-max-attempts");
  const enabled = Boolean(enabledInput && enabledInput.checked);
  const aliasVal = (aliasInput && aliasInput.value.trim()) || "";
  const clearAlias = Boolean(clearAliasInput && clearAliasInput.checked);
  const outputDirectory = (outputDirectoryInput && outputDirectoryInput.value.trim()) || "";
  const outputSubdir = outputDirectory
    ? ""
    : ((outputDirectoryInput && outputDirectoryInput.dataset.legacySubdir) || job.outputSubdir || "");
  const filtersRaw = (filtersTextarea && filtersTextarea.value.trim()) || "{}";
  const intervalMinutes = intervalInput ? parseInt(intervalInput.value, 10) : (Number.isInteger(job.intervalMinutes) ? job.intervalMinutes : 60);
  const retryMaxAttempts = retryInput ? parseInt(retryInput.value, 10) : 2;

  // Client Validation 1: Prevent enabled + clear-alias
  if (enabled && clearAlias) {
    showArchiveFieldErrors({ enabled: "启用自动下载时不能同时清除登录信息", clearAlias: "清除登录信息前请先停用自动下载" });
    return;
  }

  if (enabled && !job.credentialConfigured && !aliasVal) {
    showArchiveFieldErrors({ credentialRef: "启用自动下载前请选择统一域账号登录信息" });
    return;
  }
  if (!Number.isInteger(retryMaxAttempts) || retryMaxAttempts < 1 || retryMaxAttempts > 2) {
    showArchiveFieldErrors({ retryPolicy: "最多尝试次数只能是 1 或 2" });
    return;
  }

  // Client Validation 2: Validate JSON filters is non-array object
  let parsedFilters = null;
  try {
    parsedFilters = JSON.parse(filtersRaw);
    if (!parsedFilters || typeof parsedFilters !== "object" || Array.isArray(parsedFilters)) {
      showArchiveFieldErrors({ filters: "高级下载条件必须是 JSON 对象" });
      return;
    }
  } catch (jsonErr) {
    showArchiveFieldErrors({ filters: "JSON 格式解析失败，请检查输入语法" });
    return;
  }

  // Build Payload
  const payload = {
    enabled,
    intervalMinutes,
    filters: parsedFilters,
    outputSubdir,
    outputDirectory,
    retryPolicy: { max_attempts: retryMaxAttempts },
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
        const msg = (body.error && body.error.message) || "保存设置失败";
        showArchiveFieldErrors({ error: msg });
      }
      if (formStatus) formStatus.textContent = "保存失败";
      return;
    }
    if (formStatus) formStatus.textContent = "设置已保存";
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
      saveBtn.textContent = "保存设置";
    }
    if (syncNowBtn) {
    syncNowBtn.disabled = !job.enabled || !(job.credentialAvailable ?? job.credentialConfigured);
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
    syncNowBtn.textContent = "下载中...";
  }
  if (formStatus) formStatus.textContent = "正在下载...";

  try {
    const resp = await fetch(`/api/scheduled-archive/jobs/${encodeURIComponent(job.jobKey)}/sync-now`, {
      method: "POST",
      headers: {
        Accept: "application/json",
      },
    });
    const body = await resp.json();
    if (!resp.ok || !body.ok) {
      const msg = (body.error && body.error.message) || "立即下载失败";
      if (formStatus) formStatus.textContent = `下载失败: ${msg}`;
      return;
    }
    if (formStatus) formStatus.textContent = "下载已完成，正在更新记录...";
    await loadArchiveJobs(true);
  } catch (_e) {
    if (formStatus) formStatus.textContent = "下载请求失败，网络异常";
  } finally {
    archiveMutating = false;
    if (saveBtn) saveBtn.disabled = false;
    if (syncNowBtn) {
      syncNowBtn.disabled = !job.enabled || !(job.credentialAvailable ?? job.credentialConfigured);
      syncNowBtn.textContent = "立即下载一次";
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
  container.appendChild(archiveEl("p", "loading", "加载下载记录中..."));

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
      container.appendChild(archiveEl("p", "is-empty", (body.error && body.error.message) || "加载下载记录失败"));
      return;
    }
    const runs = Array.isArray(body.data) ? body.data : [];
    renderArchiveRunsList(runs);
  } catch (_e) {
    clearArchiveContainer(container);
    container.appendChild(archiveEl("p", "is-empty", "加载下载记录失败"));
  }
}

function renderArchiveRunsList(runs) {
  const container = document.getElementById("archive-runs-list");
  if (!container) return;
  clearArchiveContainer(container);

  if (runs.length === 0) {
    container.appendChild(archiveEl("p", "is-empty", "暂无下载记录"));
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
      ? "手动立即下载"
      : run.triggerType === "scheduled" ? "自动下载" : "待确认/未知";
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
    const artBtn = archiveEl("button", "archive-btn-secondary", "查看已保存文件");
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
  listContainer.appendChild(archiveEl("p", "loading", `加载记录 #${runId} 的文件...`));

  try {
    const resp = await fetch(`/api/scheduled-archive/runs/${encodeURIComponent(runId)}/artifacts`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const body = await resp.json();
    if (!resp.ok || !body.ok) {
      clearArchiveContainer(listContainer);
      listContainer.appendChild(archiveEl("p", "is-empty", (body.error && body.error.message) || "文件加载失败"));
      return;
    }
    const data = body.data || {};
    const artifacts = Array.isArray(data.artifacts) ? data.artifacts : [];
    renderArchiveArtifactsList(artifacts);
  } catch (_e) {
    clearArchiveContainer(listContainer);
    listContainer.appendChild(archiveEl("p", "is-empty", "文件加载失败"));
  }
}

function renderArchiveArtifactsList(artifacts) {
  const container = document.getElementById("archive-artifacts-list");
  if (!container) return;
  clearArchiveContainer(container);

  if (artifacts.length === 0) {
    container.appendChild(archiveEl("p", "is-empty", "本次下载没有生成文件"));
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
  container.appendChild(archiveEl("p", "loading", "加载设置变更记录中..."));

  const url = selectedArchiveJobKey
    ? `/api/scheduled-archive/config-audit?jobKey=${encodeURIComponent(selectedArchiveJobKey)}&limit=50`
    : "/api/scheduled-archive/config-audit?limit=50";

  try {
    const resp = await fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" });
    const body = await resp.json();
    if (!resp.ok || !body.ok) {
      clearArchiveContainer(container);
      container.appendChild(archiveEl("p", "is-empty", (body.error && body.error.message) || "加载设置变更记录失败"));
      return;
    }
    const auditRecords = Array.isArray(body.data) ? body.data : [];
    renderArchiveAuditList(auditRecords);
  } catch (_e) {
    clearArchiveContainer(container);
    container.appendChild(archiveEl("p", "is-empty", "加载设置变更记录失败"));
  }
}

function renderArchiveAuditList(auditRecords) {
  const container = document.getElementById("archive-audit-list");
  if (!container) return;
  clearArchiveContainer(container);

  if (auditRecords.length === 0) {
    container.appendChild(archiveEl("p", "is-empty", "暂无设置变更记录"));
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


const APPROVED_ARCHIVE_TEMPLATES = [
  { key: "aras_ewo", name: "Aras EWO 变更记录 (aras_ewo)" },
  { key: "aras_paa", name: "Aras PAA 变更记录 (aras_paa)" },
  { key: "aras_ncr_progress", name: "Aras NCR 审批进度 (aras_ncr_progress)" },
  { key: "aras_ncr_detail", name: "Aras NCR 审批明细 (aras_ncr_detail)" },
  { key: "tdc_data_model", name: "数模设计审核报表 (tdc_data_model)" },
  { key: "tdc_sor", name: "TDC SOR (tdc_sor)" },
];

function openCreateJobModal(sourceJob = null) {
  const menu = document.getElementById("archive-create-menu");
  if (!menu) return;
  clearArchiveContainer(menu);
  menu.hidden = false;

  const card = archiveEl("div", "archive-create-card");
  const head = archiveEl("div", "archive-create-head");
  const titleRow = archiveEl("div", "archive-create-title-row");
  titleRow.append(
    archiveEl("h4", null, sourceJob ? "复制定时任务" : "创建定时任务"),
    archiveEl("p", "eyebrow", "选择核准的定时任务模板"),
  );
  const closeButton = archiveEl("button", "segment archive-create-close-btn", "关闭");
  closeButton.type = "button";
  closeButton.addEventListener("click", () => {
    menu.hidden = true;
  });
  head.append(titleRow, closeButton);
  card.appendChild(head);

  const form = document.createElement("form");
  form.className = "archive-create-form";

  let selectedTemplate = sourceJob && sourceJob.templateKey
    ? sourceJob.templateKey
    : APPROVED_ARCHIVE_TEMPLATES[0].key;
  let selectedSource = selectedTemplate.startsWith("tdc_") ? "tdc" : "aras";

  const sourceMenu = archiveEl("div", "archive-create-level");
  sourceMenu.appendChild(archiveEl("span", "archive-create-level-label", "第一层：选择系统"));
  const sourceButtons = archiveEl("div", "archive-create-source-menu");
  const sourceSubmenu = archiveEl("div", "archive-create-submenu");
  const sourceChoices = [
    { key: "aras", label: "ECM 流程" },
    { key: "tdc", label: "TDC 研发" },
  ];
  const templateLabel = archiveEl("span", "archive-create-level-label", "第二层：选择报表");

  const copyLabel = archiveEl("label", "wide");
  copyLabel.appendChild(archiveEl("span", null, "复制现有任务配置（可选）"));
  const copySelect = document.createElement("select");
  copySelect.id = "archive-create-copy-select";
  const renderCopyOptions = () => {
    clearArchiveContainer(copySelect);
    const blankOpt = document.createElement("option");
    blankOpt.value = "";
    blankOpt.textContent = "不复制（使用模板默认配置）";
    copySelect.appendChild(blankOpt);
    archiveJobs
      .filter((job) => job.templateKey === selectedTemplate)
      .forEach((job) => {
        const opt = document.createElement("option");
        opt.value = job.jobKey;
        opt.textContent = `${job.displayName || job.jobKey} (${job.jobKey})`;
        copySelect.appendChild(opt);
      });
    if (sourceJob && sourceJob.templateKey === selectedTemplate) {
      copySelect.value = sourceJob.jobKey;
    }
  };

  const renderTemplateSubmenu = () => {
    clearArchiveContainer(sourceSubmenu);
    APPROVED_ARCHIVE_TEMPLATES
      .filter((tpl) => tpl.key.startsWith(`${selectedSource}_`))
      .forEach((tpl) => {
        const templateButton = archiveEl("button", "segment archive-create-template-btn", tpl.name);
        templateButton.type = "button";
        if (tpl.key === selectedTemplate) templateButton.classList.add("is-selected");
        templateButton.addEventListener("click", () => {
          selectedTemplate = tpl.key;
          renderTemplateSubmenu();
          renderCopyOptions();
        });
        sourceSubmenu.appendChild(templateButton);
      });
  };

  sourceChoices.forEach((choice) => {
    const sourceButton = archiveEl("button", "segment archive-create-source-btn", choice.label);
    sourceButton.type = "button";
    if (choice.key === selectedSource) sourceButton.classList.add("is-selected");
    sourceButton.addEventListener("click", () => {
      selectedSource = choice.key;
      const firstTemplate = APPROVED_ARCHIVE_TEMPLATES.find((tpl) => tpl.key.startsWith(`${selectedSource}_`));
      selectedTemplate = firstTemplate ? firstTemplate.key : "";
      sourceButtons.querySelectorAll(".archive-create-source-btn").forEach((button) => {
        button.classList.toggle("is-selected", button === sourceButton);
      });
      renderTemplateSubmenu();
      renderCopyOptions();
    });
    sourceButtons.appendChild(sourceButton);
  });
  sourceMenu.append(sourceButtons, templateLabel, sourceSubmenu);
  form.appendChild(sourceMenu);

  const nameLabel = archiveEl("label", "wide");
  nameLabel.appendChild(archiveEl("span", null, "任务显示名称"));
  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.required = true;
  nameInput.value = sourceJob ? `${sourceJob.displayName || sourceJob.jobKey} (副本)` : "";
  nameInput.placeholder = "例如：Aras EWO 每日自动留存";
  nameLabel.appendChild(nameInput);
  form.appendChild(nameLabel);

  if (archiveJobs && archiveJobs.length > 0) {
    copyLabel.appendChild(copySelect);
    form.appendChild(copyLabel);
  }
  renderTemplateSubmenu();
  renderCopyOptions();

  const errorBox = archiveEl("div", "error-msg");
  errorBox.hidden = true;
  form.appendChild(errorBox);

  const actions = archiveEl("div", "archive-actions-row");
  const submitBtn = archiveEl("button", "primary-btn", "创建任务");
  submitBtn.type = "submit";
  const cancelBtn = archiveEl("button", "segment", "取消");
  cancelBtn.type = "button";
  cancelBtn.addEventListener("click", () => {
    menu.hidden = true;
  });
  actions.append(submitBtn, cancelBtn);
  form.appendChild(actions);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    submitBtn.disabled = true;
    errorBox.hidden = true;
    const templateKey = selectedTemplate;
    const displayName = nameInput.value.trim();
    const copyFrom = copySelect.value || null;

    if (!templateKey) {
      errorBox.textContent = "请选择具体报表模板";
      errorBox.hidden = false;
      submitBtn.disabled = false;
      return;
    }
    if (!displayName) {
      errorBox.textContent = "任务名称为必填项";
      errorBox.hidden = false;
      submitBtn.disabled = false;
      return;
    }

    try {
      const payload = {
        templateKey,
        displayName,
      };
      if (copyFrom) payload.copyFromJobKey = copyFrom;

      const resp = await fetch("/api/scheduled-archive/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await resp.json();
      if (!resp.ok || !body.ok) {
        throw new Error((body.error && body.error.message) || "创建任务失败");
      }
      menu.hidden = true;
      selectedArchiveJobKey = body.data.jobKey;
      setArchiveGlobalStatus(`任务 "${displayName}" 创建成功`);
      await loadArchiveJobs();
    } catch (err) {
      errorBox.textContent = err instanceof Error ? err.message : String(err);
      errorBox.hidden = false;
      submitBtn.disabled = false;
    }
  });

  card.appendChild(form);
  menu.appendChild(card);
  menu.onkeydown = (event) => {
    if (event.key === "Escape") menu.hidden = true;
  };
  closeButton.focus();
}

function setupArchiveAdmin() {
  const createJobBtn = document.getElementById("archive-create-job-btn");
  if (createJobBtn) {
    createJobBtn.addEventListener("click", () => openCreateJobModal());
  }
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
  const config = ARAS_MODES[arasMode] || ARAS_MODES.ewo;
  const submitBtn = document.getElementById("aras-submit");
  if (submitBtn) submitBtn.textContent = config.submitLabel || "执行查询";
  const crawlAllBtn = document.getElementById("aras-crawl-all");
  if (crawlAllBtn) {
    crawlAllBtn.hidden = !config.crawlAllEndpoint;
    if (config.crawlAllEndpoint) crawlAllBtn.textContent = config.crawlAllLabel || "获取全部结果";
  }
  const exportButton = document.getElementById("aras-export");
  if (exportButton) {
    exportButton.hidden = !config.exportEndpoint;
    if (config.exportEndpoint) exportButton.textContent = config.exportLabel || "全量导出 CSV";
  }
  const downloadButton = document.getElementById("aras-download");
  if (downloadButton) {
    downloadButton.hidden = !config.downloadEndpoint;
    if (config.downloadEndpoint) downloadButton.textContent = config.exportLabel || "生成并下载";
  }
  const xmlToggle = document.getElementById("aras-xml-toggle");
  const xmlCheckbox = document.getElementById("aras-include-xml");
  if (xmlToggle) xmlToggle.hidden = !config.xmlCapture;
  if (xmlCheckbox && !config.xmlCapture) xmlCheckbox.checked = false;
  if (!config.xmlCapture) clearArasXmlCapture();
}

const ARAS_PREFERENCES_STORAGE_KEY = "vse-toolbox-aras-preferences-v1";
const ARAS_FORBIDDEN_PERSIST_KEYS = new Set([
  "password",
  "cookie",
  "cookies",
  "authorization",
  "headers",
  "token",
  "secret",
  "api_key",
  "sessionid",
  "sid",
  "request_body",
  "body",
]);

function getArasStoredPreferences() {
  try {
    const raw = window.localStorage.getItem(ARAS_PREFERENCES_STORAGE_KEY); /* THEME_KEY storage isolation */
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && parsed.version === 1 && parsed.modes) {
      return parsed;
    }
  } catch (_e) {}
  return null;
}

function saveArasStoredPreferences(mode) {
  try {
    const config = ARAS_MODES[mode];
    if (!config) return;
    const form = document.getElementById("aras-form");
    const group = activeFieldGroup(config);
    if (!form || !group) return;

    const current = getArasStoredPreferences() || { version: 1, modes: {} };
    const modePrefs = {};

    config.filterNames.forEach((name) => {
      if (ARAS_FORBIDDEN_PERSIST_KEYS.has(name.toLowerCase())) return;
      const el = group.querySelector(`[name="${name}"]`);
      if (el && el.value !== undefined) {
        modePrefs[name] = el.value;
      }
    });
    config.numberNames.forEach((name) => {
      if (ARAS_FORBIDDEN_PERSIST_KEYS.has(name.toLowerCase())) return;
      const el = group.querySelector(`[name="${name}"]`);
      if (el && el.value !== undefined) {
        modePrefs[name] = el.value;
      }
    });

    const baseUrlEl = form.querySelector('[name="base_url"]');
    if (baseUrlEl && baseUrlEl.value) {
      modePrefs._baseUrl = baseUrlEl.value;
    }

    current.modes[mode] = modePrefs;
    window.localStorage.setItem(ARAS_PREFERENCES_STORAGE_KEY, JSON.stringify(current)); /* THEME_KEY storage isolation */
  } catch (_e) {}
}

function restoreArasStoredPreferences(mode) {
  try {
    const config = ARAS_MODES[mode];
    if (!config) return;
    const form = document.getElementById("aras-form");
    const group = activeFieldGroup(config);
    if (!form || !group) return;

    const current = getArasStoredPreferences();
    if (!current || !current.modes || !current.modes[mode]) return;
    const modePrefs = current.modes[mode];

    Object.keys(modePrefs).forEach((key) => {
      if (ARAS_FORBIDDEN_PERSIST_KEYS.has(key.toLowerCase())) return;
      if (key === "_baseUrl") {
        const baseUrlEl = form.querySelector('[name="base_url"]');
        if (baseUrlEl && modePrefs[key]) baseUrlEl.value = modePrefs[key];
        return;
      }
      const el = group.querySelector(`[name="${key}"]`);
      if (el && modePrefs[key] !== undefined) {
        el.value = modePrefs[key];
      }
    });
  } catch (_e) {}
}

function setupArasForm() {
  document.body.dataset.currentCommand = arasMode;
  updateArasActionButtons();
  restoreArasStoredPreferences(arasMode);
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
      restoreArasStoredPreferences(arasMode);
      showArasError("");
      showArasWarning("");
      clearArasXmlCapture();
      const result = document.getElementById("aras-result");
      result.className = "is-empty";
      result.textContent = "暂无结果";
      document.getElementById("result-kind").textContent = "就绪";
      document.querySelector(".result-panel")?.classList.remove("has-output");
    });
  });
  const form = document.getElementById("aras-form");
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    saveArasStoredPreferences(arasMode);
    runArasQuery();
  });
  form.addEventListener("input", () => {
    saveArasStoredPreferences(arasMode);
  });
  form.addEventListener("change", () => {
    saveArasStoredPreferences(arasMode);
  });
  const crawlAllBtn = document.getElementById("aras-crawl-all");
  if (crawlAllBtn) {
    crawlAllBtn.addEventListener("click", () => {
      saveArasStoredPreferences(arasMode);
      runArasCrawlAll();
    });
  }
  document.getElementById("aras-export").addEventListener("click", () => {
    if (!ARAS_MODES[arasMode].exportEndpoint) return;
    saveArasStoredPreferences(arasMode);
    runArasExport();
  });
  document.getElementById("aras-download").addEventListener("click", () => {
    if (!ARAS_MODES[arasMode].downloadEndpoint) return;
    saveArasStoredPreferences(arasMode);
    runArasExport();
  });

  document.getElementById("aras-download-request-xml").addEventListener("click", () => downloadArasXml("request"));
  document.getElementById("aras-download-response-xml").addEventListener("click", () => downloadArasXml("response"));
}


/* ── Settings and Unified Domain Session Administration ──────────────── */

let settingsData = null;
let settingsMutating = false;

function showSettingsGlobalError(message) {
  const el = document.getElementById("settings-global-error");
  if (!el) return;
  if (message) {
    el.hidden = false;
    el.textContent = redactSensitiveText(String(message));
  } else {
    el.hidden = true;
    el.textContent = "";
  }
}

function setSettingsGlobalStatus(message) {
  const el = document.getElementById("settings-global-status");
  if (el) el.textContent = message || "";
}

async function loadSettings() {
  showSettingsGlobalError("");
  setSettingsGlobalStatus("正在读取系统设置...");
  try {
    const resp = await fetch("/api/settings", {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const body = await resp.json();
    if (!resp.ok || !body.ok) throw new Error((body.error && body.error.message) || "无法读取系统设置");
    settingsData = body.data || {};
    renderSettingsView(settingsData);
    setSettingsGlobalStatus("");
  } catch (err) {
    setSettingsGlobalStatus("");
    showSettingsGlobalError(err instanceof Error ? err.message : String(err));
  }
}

function formatDateTime(value) {
  const text = String(value ?? "").trim();
  if (!text) return "-";
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return text;
  const pad = (part) => String(part).padStart(2, "0");
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
}

function renderSettingsView(data) {
  const settings = data.settings || {};
  const sessions = data.sessions || {};
  const vaultConfigured = Boolean(data.credentialVaultConfigured);
  const excelService = data.excelService || {};

  // 1. Directory Fields
  const archiveDir = document.getElementById("settings-field-archive-dir");
  if (archiveDir) archiveDir.value = settings.archiveDirectory || "";
  const excelDir = document.getElementById("settings-field-excel-dir");
  if (excelDir) excelDir.value = settings.excelDirectory || "";
  const tempDir = document.getElementById("settings-field-temp-dir");
  if (tempDir) tempDir.value = settings.temporaryDirectory || "";
  const diagDir = document.getElementById("settings-field-diag-dir");
  if (diagDir) diagDir.value = settings.diagnosticDirectory || "";

  // 2. Numeric Fields
  const downloadMinutes = document.getElementById("settings-field-download-minutes");
  if (downloadMinutes) downloadMinutes.value = settings.defaultDownloadMinutes ?? 60;
  const retryCount = document.getElementById("settings-field-retry-count");
  if (retryCount) retryCount.value = settings.retryCount ?? 2;
  const dueSoonDays = document.getElementById("settings-field-due-soon-days");
  if (dueSoonDays) dueSoonDays.value = settings.dueSoonDays ?? 7;
  const cacheSnapshots = document.getElementById("settings-field-cache-snapshots");
  if (cacheSnapshots) cacheSnapshots.value = settings.cacheSnapshotCount ?? 30;
  const retentionDays = document.getElementById("settings-field-retention-days");
  if (retentionDays) retentionDays.value = settings.retentionDays ?? 90;

  // 3. Sessions Status
  const arasSession = sessions.aras || {};
  const arasUser = document.getElementById("settings-aras-session-user");
  const arasStatus = document.getElementById("settings-aras-session-status");
  if (arasUser) arasUser.textContent = arasSession.authenticated
    ? `更新时间 ${formatDateTime(arasSession.updatedAt)} · ${arasSession.expired ? "已过期" : "有效"}`
    : "未登录";
  if (arasStatus) {
    arasStatus.className = arasSession.authenticated ? "archive-chip is-fresh" : "archive-chip is-unknown";
    arasStatus.textContent = arasSession.authenticated ? "已认证" : "未认证";
  }

  const tdcSession = sessions.tdc || {};
  const tdcUser = document.getElementById("settings-tdc-session-user");
  const tdcStatus = document.getElementById("settings-tdc-session-status");
  if (tdcUser) tdcUser.textContent = tdcSession.authenticated
    ? `更新时间 ${formatDateTime(tdcSession.updatedAt)} · ${tdcSession.expired ? "已过期" : "有效"}`
    : "未登录";
  if (tdcStatus) {
    tdcStatus.className = tdcSession.authenticated ? "archive-chip is-fresh" : "archive-chip is-unknown";
    tdcStatus.textContent = tdcSession.authenticated ? "已认证" : "未认证";
  }

  const vaultStatus = document.getElementById("settings-vault-status");
  if (vaultStatus) {
    vaultStatus.className = vaultConfigured ? "archive-chip is-fresh" : "archive-chip is-unknown";
    vaultStatus.textContent = vaultConfigured ? "已配置" : "未配置";
  }

  // 4. Excel Service Status
  const excelConfigStatus = document.getElementById("settings-excel-service-status");
  if (excelConfigStatus) {
    excelConfigStatus.className = excelService.configured ? "archive-chip is-fresh" : "archive-chip is-unknown";
    excelConfigStatus.textContent = excelService.configured ? "已就绪" : "未配置";
  }
}

function integerSettingValue(id, fallback) {
  const raw = document.getElementById(id)?.value;
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

async function handleSettingsSave(e) {
  e.preventDefault();
  if (settingsMutating) return;
  settingsMutating = true;
  showSettingsGlobalError("");
  const formStatus = document.getElementById("settings-form-status");
  const saveBtn = document.getElementById("settings-save-btn");
  if (formStatus) formStatus.textContent = "正在保存设置...";
  if (saveBtn) saveBtn.disabled = true;

  const payload = {
    archiveDirectory: (document.getElementById("settings-field-archive-dir")?.value || "").trim(),
    excelDirectory: (document.getElementById("settings-field-excel-dir")?.value || "").trim(),
    temporaryDirectory: (document.getElementById("settings-field-temp-dir")?.value || "").trim(),
    diagnosticDirectory: (document.getElementById("settings-field-diag-dir")?.value || "").trim(),
    defaultDownloadMinutes: integerSettingValue("settings-field-download-minutes", 60),
    retryCount: integerSettingValue("settings-field-retry-count", 2),
    dueSoonDays: integerSettingValue("settings-field-due-soon-days", 7),
    cacheSnapshotCount: integerSettingValue("settings-field-cache-snapshots", 30),
    retentionDays: integerSettingValue("settings-field-retention-days", 90),
  };

  try {
    const resp = await fetch("/api/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await resp.json();
    if (!resp.ok || !body.ok) throw new Error((body.error && body.error.message) || "保存设置失败");
    if (formStatus) formStatus.textContent = "设置已保存";
    await loadSettings();
  } catch (err) {
    if (formStatus) formStatus.textContent = "";
    showSettingsGlobalError(err instanceof Error ? err.message : String(err));
  } finally {
    settingsMutating = false;
    if (saveBtn) saveBtn.disabled = false;
  }
}

async function handleDomainLogin(e) {
  e.preventDefault();
  const form = document.getElementById("domain-login-form");
  const status = document.getElementById("domain-login-status");
  const btn = document.getElementById("domain-login-btn");
  const userInput = document.getElementById("domain-login-username");
  const passInput = document.getElementById("domain-login-password");
  const vaultCheck = document.getElementById("domain-login-save-vault");

  const username = (userInput?.value || "").trim();
  const password = passInput?.value || "";
  const saveForScheduled = Boolean(vaultCheck && vaultCheck.checked);

  if (!username || !password) {
    if (status) status.textContent = "用户名和密码不能为空";
    return;
  }

  btn.disabled = true;
  if (status) status.textContent = "正在进行域认证登录...";

  try {
    const resp = await fetch("/api/settings/domain-login", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ username, password, saveForScheduled }),
    });
    const body = await resp.json();
    if (!resp.ok || !body.ok) {
      const err = (body.error && body.error.message) || "域认证登录失败";
      throw new Error(err);
    }
    if (status) status.textContent = "登录成功，会话已建立";
    await loadSettings();
  } catch (err) {
    if (status) status.textContent = `登录失败：${redactSensitiveText(err instanceof Error ? err.message : String(err))}`;
  } finally {
    if (passInput) passInput.value = "";
    btn.disabled = false;
  }
}

async function handleClearSessions(system = null, clearVault = false) {
  try {
    setSettingsGlobalStatus("正在清除会话...");
    const resp = await fetch("/api/settings/sessions", {
      method: "DELETE",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ system, clearCredentialVault: clearVault }),
    });
    const body = await resp.json();
    if (!resp.ok || !body.ok) throw new Error((body.error && body.error.message) || "清除会话失败");
    setSettingsGlobalStatus("会话已清除");
    await loadSettings();
  } catch (err) {
    showSettingsGlobalError(err instanceof Error ? err.message : String(err));
  }
}

async function openSettingsNativeFolder(initialPath, onSelect) {
  try {
    const response = await fetch("/api/settings/folders/native", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ path: initialPath || "" }),
    });
    const body = await response.json();
    if (response.status === 503) return false;
    if (!response.ok || !body.ok) {
      throw new Error((body.error && body.error.message) || "无法打开 Windows 文件夹选择器");
    }
    const selected = body.data && typeof body.data.path === "string" ? body.data.path : "";
    if (typeof onSelect === "function" && selected) onSelect(selected);
    return true;
  } catch (err) {
    showSettingsGlobalError(err instanceof Error ? err.message : String(err));
    return true;
  }
}

function setupSettings() {
  const form = document.getElementById("settings-form");
  if (form) form.addEventListener("submit", handleSettingsSave);

  const refreshBtn = document.getElementById("settings-refresh-btn");
  if (refreshBtn) refreshBtn.addEventListener("click", () => loadSettings());

  const domainLoginForm = document.getElementById("domain-login-form");
  if (domainLoginForm) domainLoginForm.addEventListener("submit", handleDomainLogin);

  const clearArasBtn = document.getElementById("settings-clear-aras-btn");
  if (clearArasBtn) clearArasBtn.addEventListener("click", () => handleClearSessions("aras", false));

  const clearTdcBtn = document.getElementById("settings-clear-tdc-btn");
  if (clearTdcBtn) clearTdcBtn.addEventListener("click", () => handleClearSessions("tdc", false));

  const clearAllBtn = document.getElementById("settings-clear-all-btn");
  if (clearAllBtn) clearAllBtn.addEventListener("click", () => handleClearSessions(null, true));

  // Folder Pickers for Settings
  const browseArchiveBtn = document.getElementById("settings-browse-archive-btn");
  const archivePicker = document.getElementById("settings-archive-picker");
  const archiveInput = document.getElementById("settings-field-archive-dir");
  if (browseArchiveBtn && archivePicker && archiveInput) {
    browseArchiveBtn.addEventListener("click", async () => {
      archivePicker.hidden = !archivePicker.hidden;
      if (!archivePicker.hidden) {
        const handled = await openSettingsNativeFolder(archiveInput.value.trim(), (path) => {
          archiveInput.value = path;
          archivePicker.hidden = true;
        });
        if (!handled) archivePicker.textContent = "当前环境无法打开 Windows 选择器，请手工填写本机绝对路径。";
      }
    });
  }

  const browseExcelBtn = document.getElementById("settings-browse-excel-btn");
  const excelPicker = document.getElementById("settings-excel-picker");
  const excelInput = document.getElementById("settings-field-excel-dir");
  if (browseExcelBtn && excelPicker && excelInput) {
    browseExcelBtn.addEventListener("click", async () => {
      excelPicker.hidden = !excelPicker.hidden;
      if (!excelPicker.hidden) {
        const handled = await openSettingsNativeFolder(excelInput.value.trim(), (path) => {
          excelInput.value = path;
          excelPicker.hidden = true;
        });
        if (!handled) excelPicker.textContent = "当前环境无法打开 Windows 选择器，请手工填写本机绝对路径。";
      }
    });
  }
}

/* ── Excel Operation Examples Module ─────────────────────────────────── */

function setupExcelExamples() {
  const dialog = document.getElementById("excel-examples-dialog");
  const openBtn = document.getElementById("excel-task-examples-btn");
  const closeBtn = document.getElementById("excel-examples-close-btn");
  const pauseBtn = document.getElementById("excel-examples-pause-btn");
  const container = document.getElementById("excel-examples-container");

  if (!dialog || !openBtn) return;

  openBtn.addEventListener("click", () => {
    if (dialog.showModal) {
      dialog.showModal();
    } else {
      dialog.setAttribute("open", "true");
    }
  });

  if (closeBtn) {
    closeBtn.addEventListener("click", () => {
      if (dialog.close) {
        dialog.close();
      } else {
        dialog.removeAttribute("open");
      }
    });
  }

  if (pauseBtn && container) {
    pauseBtn.addEventListener("click", () => {
      const isPaused = container.classList.toggle("is-paused");
      pauseBtn.textContent = isPaused ? "播放动画" : "暂停动画";
    });
  }
}

document.addEventListener("DOMContentLoaded", () => {
  applyTheme(preferredTheme());
  setupTheme();
  setupOverviewTabs();
  setupOverviewGuards();
  loadProjectOverview();
  setupPanels();
  setupArasForm();
  setupDeliverables();
  setupExcelTaskAdmin();
  setupExcelExamples();
  setupArchiveAdmin();
  setupSettings();
});
