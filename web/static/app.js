const THEME_KEY = "vse-toolbox-theme";
// 当前项目阶段 ID（单阶段应用约定；多阶段化时改为按上下文注入）。
const PROJECT_PHASE_ID = "VPI-T2";

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
let arasHasRenderedResult = false;
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

const OVERVIEW_DETAIL_COLUMNS = ["交付物", "状态", "计划完成", "实际完成或当前进度", "风险与备注", "数据来源"];

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
let overviewRequestSeq = 0;
let overviewBusinessSnapshotRequestSeq = 0;

const OVERVIEW_BUSINESS_SNAPSHOT_DEFINITIONS = [
  {
    formKey: "aras_paa",
    title: "PAA 变更记录",
    scopeLabel: "ARAS PAA 外部源快照范围",
    archiveJobKey: "aras_paa",
  },
  {
    formKey: "aras_ncr_progress",
    title: "NCR 审批进度",
    scopeLabel: "ARAS NCR 审批进度外部源快照范围",
    archiveJobKey: "aras_ncr_progress",
  },
];

function createOverviewBusinessSnapshotCache(status = "idle") {
  return Object.fromEntries(
    OVERVIEW_BUSINESS_SNAPSHOT_DEFINITIONS.map(({ formKey }) => [
      formKey,
      { status, data: null, error: "" },
    ]),
  );
}

let overviewBusinessSnapshots = createOverviewBusinessSnapshotCache();

function overviewEl(tagName, className, text) {
  const node = document.createElement(tagName);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function clearOverviewContainer(container) {
  if (container) {
    if (typeof container.querySelectorAll === "function") {
      container.querySelectorAll("[data-ewo-enrichment]").forEach((host) => {
        if (typeof host.destroyEwoEnrichment === "function") host.destroyEwoEnrichment();
      });
    }
    container.textContent = "";
  }
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

function deliverableManualEditState(item) {
  const reason = String(item && item.readOnlyReason || "").trim();
  if (item && item.manualEditable === true) {
    return { editable: true, reason: "" };
  }
  return {
    editable: false,
    reason: reason || "该交付物当前由系统同步维护，手工字段只读。",
  };
}

function appendDeliverableReadOnlyNotice(container, item, className = "detail-readonly-notice") {
  if (!container) return;
  const capability = deliverableManualEditState(item);
  if (capability.editable) return;
  const existing = container.querySelector && container.querySelector(`.${className}`);
  if (existing) {
    existing.textContent = `手工字段只读：${redactSensitiveText(capability.reason)}`;
    return;
  }
  container.appendChild(
    overviewEl("p", className, `手工字段只读：${redactSensitiveText(capability.reason)}`),
  );
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

function interactiveRowIdentityValues(mode, data, row) {
  const identityFields = mode === "ewo"
    ? ["_no", "ewoNo", "ewo_no", "id", "formId"]
    : ["_no", "paaNo", "paa_no", "ewoNo", "ewo_no", "id", "formId"];
  if (Array.isArray(row)) {
    const columns = data && Array.isArray(data.columns) ? data.columns : [];
    const values = [];
    columns.forEach((column, fallbackIndex) => {
      const sourceFields = column && Array.isArray(column.sourceFields) ? column.sourceFields : [];
      if (!sourceFields.some((field) => identityFields.includes(field))) return;
      const index = Number.isInteger(column.index) ? column.index : fallbackIndex;
      values.push(row[index]);
    });
    // The approved EWO/PAA table contract places the business number first;
    // retain a safe fallback for older responses that omit column metadata.
    if (!values.length && row.length) values.push(row[0]);
    return values;
  }
  if (row && typeof row === "object") {
    return identityFields.map((field) => row[field]);
  }
  return [];
}

function interactiveQueryResultState(mode, data, targetKey = "") {
  const rows = data && Array.isArray(data.rows) ? data.rows : [];
  if (!rows.length || (data && data.queryState === "empty")) return "empty";
  const target = interactiveFilterValue(targetKey);
  if (!target) return "matched";
  const found = rows.some((row) => interactiveRowIdentityValues(mode, data, row).some(
    (value) => interactiveFilterValue(value) === target,
  ));
  return found ? "matched" : "no_match";
}

function formatInteractiveArasResult(data, expectedExternalKey = "", mode = "") {
  const state = interactiveQueryResultState(mode, data, expectedExternalKey);
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
  const resultState = formatInteractiveArasResult(data, targetKey, mode);
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
  cell.colSpan = OVERVIEW_DETAIL_COLUMNS.length + 1;
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

function calculateMilestoneTimelineX(milestones, phase) {
  const sorted = [...milestones].sort((a, b) => (a.sortOrder || 0) - (b.sortOrder || 0));
  const count = sorted.length;
  if (count === 0) return [];
  const anchors = [];
  const datePattern = /^\d{4}-\d{2}-\d{2}$/;
  for (let i = 0; i < count; i++) {
    const m = sorted[i];
    const dateStr = typeof m.date === "string" ? m.date.trim() : "";
    if (dateStr && datePattern.test(dateStr)) {
      anchors.push({ index: i, x: milestoneProgressX(dateStr, phase) });
    }
  }

  const positions = new Array(count);
  if (anchors.length === 0) {
    for (let i = 0; i < count; i++) {
      positions[i] = (100 * (i + 1)) / (count + 1);
    }
  } else {
    for (const anchor of anchors) {
      positions[anchor.index] = anchor.x;
    }
    // Head segment: before first anchor
    const firstAnchor = anchors[0];
    if (firstAnchor.index > 0) {
      const runLen = firstAnchor.index;
      const b = firstAnchor.x;
      for (let k = 0; k < runLen; k++) {
        positions[k] = (b * (k + 1)) / (runLen + 1);
      }
    }
    // Middle segments: between adjacent anchors
    for (let aIdx = 0; aIdx < anchors.length - 1; aIdx++) {
      const leftAnchor = anchors[aIdx];
      const rightAnchor = anchors[aIdx + 1];
      const runLen = rightAnchor.index - leftAnchor.index - 1;
      if (runLen > 0) {
        const a = leftAnchor.x;
        const b = rightAnchor.x;
        for (let k = 0; k < runLen; k++) {
          positions[leftAnchor.index + 1 + k] = a + ((b - a) * (k + 1)) / (runLen + 1);
        }
      }
    }
    // Tail segment: after last anchor
    const lastAnchor = anchors[anchors.length - 1];
    if (lastAnchor.index < count - 1) {
      const runLen = count - 1 - lastAnchor.index;
      const a = lastAnchor.x;
      for (let k = 0; k < runLen; k++) {
        positions[lastAnchor.index + 1 + k] = a + ((100 - a) * (k + 1)) / (runLen + 1);
      }
    }
  }

  return sorted.map((m, idx) => ({
    milestone: m,
    x: positions[idx],
  }));
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

  const datePattern = /^\d{4}-\d{2}-\d{2}$/;
  const positionedMilestones = calculateMilestoneTimelineX(data.milestones || [], phase);

  const timelineEntries = [
    { type: "today", date: phase.today, x: milestoneProgressX(phase.today, phase) },
    ...positionedMilestones.map((item) => ({
      type: "milestone",
      milestone: item.milestone,
      date: item.milestone.date,
      x: item.x,
    })),
  ].sort((left, right) => {
    const leftDate = typeof left.date === "string" ? left.date.trim() : "";
    const rightDate = typeof right.date === "string" ? right.date.trim() : "";
    const leftHasDate = leftDate && datePattern.test(leftDate);
    const rightHasDate = rightDate && datePattern.test(rightDate);

    if (leftHasDate && rightHasDate) {
      const cmp = leftDate.localeCompare(rightDate);
      if (cmp !== 0) return cmp;
    }
    return left.x - right.x;
  });

  timelineEntries.forEach((entry) => {
    if (entry.type === "today") {
      const today = overviewEl("div", "today-marker");
      today.style.setProperty("--x", String(entry.x));
      today.appendChild(overviewEl("span", "today-label", `今天 ${entry.date.slice(5)}`));
      rail.appendChild(today);
      return;
    }
    const milestone = entry.milestone;
    const rawDate = typeof milestone.date === "string" ? milestone.date.trim() : "";
    const hasDate = Boolean(rawDate && datePattern.test(rawDate));
    const isUndated = !hasDate;
    const nodeType = isUndated ? "planned" : (milestone.type || "planned");
    const nodeStatus = isUndated ? "未开始" : (milestone.status || "未开始");
    const dateText = isUndated ? "待排期" : rawDate.slice(5);

    const node = overviewEl("div", `milestone-node is-${nodeType}`);
    const activeNode = window.VseNodeOverview && window.VseNodeOverview.buildContext(data).node;
    const isActiveNode = activeNode && activeNode.id === milestone.id;
    if (isActiveNode) {
      node.classList.add("is-active-node");
      node.setAttribute("aria-current", "step");
    }
    node.setAttribute("role", "listitem");
    node.style.setProperty("--x", String(entry.x));
    node.appendChild(overviewEl("span", "milestone-dot", null));
    const copy = overviewEl("span", "milestone-copy");
    copy.append(
      overviewEl("strong", "milestone-name", milestone.name),
      overviewEl("time", "milestone-date", dateText),
      overviewEl("small", "milestone-status", nodeStatus),
    );
    node.appendChild(copy);
    if (isActiveNode) copy.appendChild(overviewEl("span", "node-current-label", "当前节点"));
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
    ["已完成", `${phase.completedCount}`],
    ["待同步", `${phase.pendingCount ?? 0}`],
    ["总计", `${phase.totalCount}`],
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

// 快照联动摘要：明细分析快照（与交付物明细页分析同源）优先，
// 其次定时归档写入的表单快照摘要。
// 门控：仅在交付物自身启用同步（更新方式自动/混合）时生效；
// 人工编辑的交付物始终使用手工值，归档/分析快照不得覆盖手工状态。
function deliverableSnapshotSummary(item) {
  if (!item || typeof item !== "object") return null;
  const policy = item.updatePolicy;
  if (!policy || typeof policy !== "object" || policy.enabled !== true) return null;
  const analysis = item.analysisLink && typeof item.analysisLink === "object"
    ? item.analysisLink.summary
    : null;
  if (analysis && typeof analysis === "object") {
    return { kind: "analysis", summary: analysis, snapshotAt: item.analysisLink.snapshotAt || null };
  }
  const form = item.formLink && typeof item.formLink === "object"
    ? item.formLink.summary
    : null;
  if (form && typeof form === "object") {
    // 聚合绑定（GPT 终审 E：前后端换绑隔离一致）只信任分析快照链路，
    // 不做表单快照兜底——后端状态机已同步实施相同规则。
    if (item.updatePolicy && item.updatePolicy.aggregate === true) return null;
    return { kind: "form", summary: form, snapshotAt: item.formLink.snapshotAt || null };
  }
  return null;
}

function deliverableFormDisplay(item) {
  // 优先消费后端 syncDisplay.display 字段（单一状态机下发，快照态）；
  // 旧 payload 或缺字段时回退到本地快照换算（同规则）。
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
      progress: Number.isFinite(displayProgress)
        ? Math.min(100, Math.max(0, Math.round(displayProgress)))
        : 0,
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
  if (completed >= total) {
    status = "已完成";
  } else if (overdue > 0) {
    status = "已逾期";
  }

  return {
    progress: Math.min(100, Math.max(0, progress)),
    status,
    snapshotAt: linked.snapshotAt,
  };
}

// 统一显示口径：状态总览环图与交付物明细表共用同一份快照换算结果，
// 避免同一交付物在两个视图显示不同的状态或完成度。
// 交付物详情头参考行：展示与环图同源的表单分析快照摘要
// （分析快照优先，表单快照兜底，聚合绑定不回退表单快照）。
// 无快照来源时提示"无表单来源"，仅手工维护的交付物标注其来源名称。
function deliverableFormReferenceText(item) {
  const linked = deliverableSnapshotSummary(item);
  if (linked) {
    const total = Number(linked.summary.total) || 0;
    const completed = Number(linked.summary.completed) || 0;
    const at = linked.snapshotAt ? String(linked.snapshotAt).slice(0, 10) : "";
    return `表单分析参考：已完成 ${completed}/${total}（${at || "无快照时间"}）`;
  }
  const sourceName = item && item.sourceInfo && item.sourceInfo.displayName
    ? String(item.sourceInfo.displayName)
    : "";
  return sourceName ? `无表单来源（${sourceName}来源）` : "无表单来源";
}

function deliverableDisplayItem(item) {
  const formDisplay = deliverableFormDisplay(item);
  if (!formDisplay) return item;
  return {
    ...item,
    progress: formDisplay.progress,
    status: formDisplay.status,
    tone: null,
    progressOrDate: formDisplay.status === "已完成"
      ? (item.actualDate || `${formDisplay.progress}%`)
      : `${formDisplay.progress}%`,
  };
}

// 展示状态机（后端 syncDisplay 下发，七态）：数值仅在 manual/paused/snapshot
// 三态展示；其余状态环图/明细显示状态标签，避免"默认自动但尚未同步"的
// 交付物展示编造进度（含新库种子的待同步占位值）。
const SYNC_DISPLAY_VALUE_STATES = new Set(["manual", "snapshot"]);
const SYNC_DISPLAY_RING_LABELS = {
  paused: "已暂停",
  pending_config: "待配置",
  pending_first_sync: "待同步",
  sync_failed: "同步失败",
  no_source_records: "无记录",
};

function deliverableSyncDisplay(item) {
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

function deliverableHasDisplayValue(item) {
  return SYNC_DISPLAY_VALUE_STATES.has(deliverableSyncDisplay(item).state);
}

// 待同步态的日期文案：真实计划日期已过时明确标注逾期天数
//（仅提示，不并入业务风险计数——CODEX 审计调整项）。
// 统一状态文案：非数值态显示状态标签，数值态显示换算状态；
// 四区（环图/明细/详情头/状态图/属性网格）共用。
function deliverableStatusText(item, displayItem) {
  const syncDisplay = deliverableSyncDisplay(item);
  if (!SYNC_DISPLAY_VALUE_STATES.has(syncDisplay.state)) return syncDisplay.label;
  return displayItem ? displayItem.status : item.status;
}

function deliverablePendingDateLabel(item) {
  const planned = item.plannedDate ? `计划完成 ${item.plannedDate.slice(5)}` : "计划完成 -";
  const today = overviewSavedState && overviewSavedState.phase && overviewSavedState.phase.today;
  if (!today || !item.plannedDate) return planned;
  const delta = Math.floor((new Date(today) - new Date(item.plannedDate)) / 86400000);
  return delta > 0 ? `${planned}；已逾期 ${delta} 天（待同步）` : planned;
}

// “按节点状态自动显示”规则（用户 2026-09-06 示例：到了 VDR 阶段，
// 子系统开发策略如已完成就不再展示）。每个交付物配置其所属主计划节点
// 关键字；当主计划中存在名称包含该关键字且日期已过的节点（项目已推进
// 到该节点）时，已完成（含快照换算）的交付物不再展示。节点关键字是
// 产品口径，可在此映射中调整；节点未排期（空日期）时不触发隐藏。
const DELIVERABLE_AUTO_HIDE_NODE_KEYWORDS = {
  "VPI-T2-D1": ["VDR"],
  "VPI-T2-D2": ["VPI"],
  "VPI-T2-D3": ["T2"],
  "VPI-T2-D4": ["VDR"],
  "VPI-T2-D5": ["T2"],
};

function deliverableNodeReached(keywords) {
  const state = overviewSavedState;
  const milestones = state && Array.isArray(state.milestones) ? state.milestones : [];
  const today = state && state.phase && state.phase.today ? String(state.phase.today) : "";
  if (!today) return false;
  // 分词精确匹配（连字符不分词）：`VDR` 命中「VDR 决策」「LLP VDR」，
  // 但「VPI-T2 Gate」整体是一个词，不会被 VPI 关键字误判（子串或按
  // 连字符分词都会误命中）。
  const wanted = keywords.map((keyword) => String(keyword).toUpperCase());
  return milestones.some((milestone) => {
    const name = String(milestone.name || "").toUpperCase();
    const date = String(milestone.date || "");
    if (!date) return false;
    const tokens = name.split(/[\s·/()（）%]+/).filter(Boolean);
    return wanted.some((keyword) => tokens.includes(keyword)) && date <= today;
  });
}

function shouldShowDeliverable(item, filterValue) {
  if (filterValue !== "auto") return true;
  const keywords = DELIVERABLE_AUTO_HIDE_NODE_KEYWORDS[item.id];
  if (!keywords || !keywords.length) return true;
  // 七态门控（终审 P2）：待同步类状态的交付物始终展示，
  // 避免环图显示「待同步」而卡片被自动隐藏的窄窗口。
  if (!deliverableHasDisplayValue(item)) return true;
  // 完成态与环图口径一致：优先取快照换算状态（含"手工进行中但快照
  // 已全部完成"的情形），无快照时回退手工状态。
  const formDisplay = deliverableFormDisplay(item);
  const status = formDisplay ? formDisplay.status : item.status;
  if (status !== "已完成") return true;
  return !deliverableNodeReached(keywords);
}

let deliverableProgressFilterValue = "all";

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

// 外部快照驱动交付物（D6-D8）徽标：状态由归档表单快照自动映射，
// 仅展示参考，不计入总体进度统计分母。
function deliverableSnapshotBadge(item) {
  if (!item || item.formSnapshotDriven !== true) return null;
  const badge = overviewEl("span", "snapshot-driven-badge", "外部快照·参考");
  badge.title = "状态由外部表单快照自动映射，仅展示参考，不计入总体进度";
  return badge;
}

function ringDateLabel(item) {
  if (item.status === "已完成") {
    const value = deliverableProgressOrDate(item);
    // 无实际完成日期时回退展示完成度百分比，避免 "实际完成 " 空文案。
    return value.endsWith("%") ? `完成度 ${value}` : `实际完成 ${value.slice(5)}`;
  }
  return item.plannedDate ? `计划完成 ${item.plannedDate.slice(5)}` : "计划完成 -";
}

function renderDeliverableProgress(container, deliverables) {
  clearOverviewContainer(container);
  const band = container.closest(".deliverable-status-band");
  if (band) {
    const existingHead = band.querySelector(".band-head");
    if (existingHead && !existingHead.querySelector(".deliverable-display-filter")) {
      const filterWrap = overviewEl("label", "deliverable-display-filter");
      filterWrap.append(overviewEl("span", "deliverable-display-filter-label", "显示"));
      const select = document.createElement("select");
      select.className = "deliverable-display-filter-select";
      select.setAttribute("aria-label", "交付物显示筛选");

      const optAll = document.createElement("option");
      optAll.value = "all";
      optAll.textContent = "全部交付物";
      const optAuto = document.createElement("option");
      optAuto.value = "auto";
      optAuto.textContent = "按节点状态自动显示";
      optAuto.title = "已完成且项目推进越过其关联主计划节点的交付物不再展示";

      select.append(optAll, optAuto);
      select.value = deliverableProgressFilterValue;
      select.addEventListener("change", (e) => {
        deliverableProgressFilterValue = e.target.value;
        renderDeliverableProgress(container, deliverables);
      });
      filterWrap.appendChild(select);
      const hiddenHint = overviewEl(
        "span",
        "deliverable-auto-hidden",
        "",
      );
      filterWrap.appendChild(hiddenHint);
      existingHead.appendChild(filterWrap);
    }
    // 已存在的下拉在重新渲染时与当前筛选值保持同步。
    const existingSelect = band.querySelector(".deliverable-display-filter-select");
    if (existingSelect) {
      existingSelect.value = deliverableProgressFilterValue;
    }
    const hint = band.querySelector(".deliverable-auto-hidden");
    if (hint) {
      const hiddenCount = deliverables.filter(
        (item) => !shouldShowDeliverable(item, deliverableProgressFilterValue),
      ).length;
      hint.textContent = deliverableProgressFilterValue === "auto" && hiddenCount
        ? `已隐藏 ${hiddenCount} 项已完成交付物`
        : "";
    }
  }

  deliverables.forEach((rawItem) => {
    if (!shouldShowDeliverable(rawItem, deliverableProgressFilterValue)) return;
    const item = deliverableDisplayItem(rawItem);
    const syncDisplay = deliverableSyncDisplay(item);
    const hasDisplayValue = SYNC_DISPLAY_VALUE_STATES.has(syncDisplay.state);

    const ringStatusText = deliverableStatusText(item, item);
    const card = overviewEl("article", "progress-ring is-clickable");
    card.setAttribute("role", "button");
    card.setAttribute("tabindex", "0");
    card.setAttribute(
      "aria-label",
      `${item.name}，${hasDisplayValue ? `完成度 ${item.progress}%，状态 ${ringStatusText}` : `状态 ${syncDisplay.label}`}，查看明细`,
    );
    const openDetail = () => {
      location.hash = `#deliverable/${encodeURIComponent(item.id)}`;
    };
    card.addEventListener("click", openDetail);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openDetail();
      }
    });
    const visual = overviewEl("span", "ring-visual");
    visual.style.setProperty("--progress", hasDisplayValue ? String(item.progress) : "0");
    visual.style.setProperty("--ring-color", hasDisplayValue
      ? (OVERVIEW_RING_TONES[deliverableTone(item)] || "var(--muted)")
      : "var(--muted)");
    visual.appendChild(overviewEl("span", "ring-center", hasDisplayValue
      ? `${item.progress}%`
      : (SYNC_DISPLAY_RING_LABELS[syncDisplay.state] || syncDisplay.label)));
    const copy = overviewEl("span", "ring-copy");
    copy.append(
      overviewEl("strong", "ring-name", item.name),
      overviewEl("span", `ring-status is-${hasDisplayValue ? deliverableTone(item) : "primary"}`, ringStatusText),
      overviewEl("span", "ring-date", hasDisplayValue ? ringDateLabel(item) : deliverablePendingDateLabel(item)),
    );
    const snapshotBadge = deliverableSnapshotBadge(item);
    if (snapshotBadge) copy.appendChild(snapshotBadge);
    card.append(visual, copy);
    if (item.note) {
      card.title = `${item.name}（${item.status}）：${item.note}`;
    }
    container.appendChild(card);
  });
}

function overviewBusinessSnapshotCondition(entry) {
  if (!entry || entry.status === "loading") {
    return { kind: "loading", label: "读取中", detail: "正在读取最近一次外部源快照。" };
  }
  if (entry.status === "error") {
    return {
      kind: "error",
      label: "读取失败",
      detail: entry.error || "外部源快照暂时不可用。",
    };
  }

  const data = entry.data && typeof entry.data === "object" ? entry.data : {};
  const snapshot = data.snapshot && typeof data.snapshot === "object" ? data.snapshot : null;
  const snapshotAt = data.snapshotAt || (snapshot && snapshot.snapshotAt) || "";
  const summary = data.summary && typeof data.summary === "object" ? data.summary : {};
  const total = Number(summary.total);
  const completed = Number(summary.completed);
  const sync = data.sync && typeof data.sync === "object" ? data.sync : {};
  const syncState = String(sync.state || "").trim().toLowerCase();
  const snapshotTime = Date.parse(String(snapshotAt || ""));
  const attemptTime = Date.parse(String(sync.lastAttemptAt || ""));
  const hasStaleAttempt = Number.isFinite(snapshotTime)
    && Number.isFinite(attemptTime)
    && attemptTime > snapshotTime;
  const staleSync = ["running", "failed", "needs_attention"].includes(syncState) || hasStaleAttempt;

  if (!snapshot || !snapshotAt) {
    return {
      kind: "no-snapshot",
      stale: staleSync,
      label: staleSync
        ? (syncState === "running" ? "同步中，暂无快照" : "同步异常，暂无快照")
        : "暂无快照",
      detail: staleSync
        ? "后台同步尚未形成可用快照，当前没有可展示的外部记录。"
        : "外部源尚未生成可展示的业务快照。",
      snapshotAt: "",
      lastAttemptAt: sync.lastAttemptAt || "",
    };
  }
  if (!Number.isFinite(total) || total <= 0) {
    return {
      kind: "empty-snapshot",
      stale: staleSync,
      label: staleSync
        ? (syncState === "running" ? "同步中，空快照" : "同步异常，空快照")
        : "空快照",
      detail: staleSync
        ? "最近一次快照没有可统计的外部记录，后台同步尚未形成新快照。"
        : "最近一次快照已读取，但没有可统计的外部记录。",
      snapshotAt,
      lastAttemptAt: sync.lastAttemptAt || "",
      total: 0,
      completed: 0,
    };
  }

  const safeTotal = Math.max(0, Math.floor(total));
  const safeCompleted = Math.max(0, Math.min(safeTotal, Math.floor(Number.isFinite(completed) ? completed : 0)));
  return {
    kind: staleSync ? "stale-snapshot" : "snapshot",
    stale: staleSync,
    label: staleSync
      ? (syncState === "running" ? "同步中，展示上次快照" : "同步异常，展示上次快照")
      : "快照已同步",
    detail: staleSync
      ? "后台同步尚未形成新快照，以下数字来自最近一次可用快照。"
      : "以下数字来自最近一次可用快照。",
    snapshotAt,
    lastAttemptAt: sync.lastAttemptAt || "",
    total: safeTotal,
    completed: safeCompleted,
  };
}

function renderOverviewBusinessSnapshots(container) {
  if (!container) return;
  const section = overviewEl("section", "business-snapshot-section");
  section.append(
    overviewEl("p", "eyebrow", "外部业务快照"),
    overviewEl("h5", "business-snapshot-title", "PAA / NCR 外部源进度（参考）"),
    overviewEl("p", "business-snapshot-description", "快照仅用于业务参考，不计入项目交付物或主计划节点完成统计。"),
  );
  const grid = overviewEl("div", "business-snapshot-grid");

  OVERVIEW_BUSINESS_SNAPSHOT_DEFINITIONS.forEach((definition) => {
    const entry = overviewBusinessSnapshots[definition.formKey] || { status: "loading" };
    const condition = overviewBusinessSnapshotCondition(entry);
    const card = overviewEl(
      "article",
      `business-snapshot-card is-${condition.kind}${condition.stale ? " is-stale" : ""}`,
    );
    card.setAttribute("aria-label", `${definition.title}：${condition.label}`);

    const head = overviewEl("div", "business-snapshot-card-head");
    head.append(
      overviewEl("strong", "business-snapshot-card-title", definition.title),
      overviewEl("span", `business-snapshot-status is-${condition.kind}${condition.stale ? " is-stale" : ""}`, condition.label),
    );
    card.appendChild(head);

    const count = overviewEl("strong", "business-snapshot-count");
    if (condition.kind === "snapshot" || condition.kind === "stale-snapshot") {
      count.textContent = `已完成 ${condition.completed} / 总计 ${condition.total}`;
      const track = overviewEl("span", "business-snapshot-track");
      const fill = overviewEl("span", "business-snapshot-fill");
      fill.style.width = `${(condition.completed / Math.max(1, condition.total)) * 100}%`;
      track.appendChild(fill);
      card.append(count, track);
    } else if (condition.kind === "empty-snapshot") {
      count.textContent = "已完成 0 / 总计 0";
      card.appendChild(count);
    } else {
      count.textContent = "已完成 — / 总计 —";
      card.appendChild(count);
    }

    card.appendChild(overviewEl("p", "business-snapshot-detail", condition.detail));
    card.appendChild(overviewEl(
      "small",
      "business-snapshot-scope",
      `统计范围：${definition.scopeLabel}（外部源，不等同于认证项目范围）`,
    ));
    card.appendChild(overviewEl(
      "small",
      "business-snapshot-time",
      `快照时间：${condition.snapshotAt ? archiveFormatDate(condition.snapshotAt) : "暂无"}`,
    ));
    if (condition.lastAttemptAt && condition.stale) {
      card.appendChild(overviewEl(
        "small",
        "business-snapshot-attempt",
        `最近尝试：${archiveFormatDate(condition.lastAttemptAt)}`,
      ));
    }

    const job = (Array.isArray(overviewArchiveJobs) ? overviewArchiveJobs : [])
      .find((candidate) => candidate && candidate.jobKey === definition.archiveJobKey);
    if (job) {
      const detailButton = overviewEl("button", "business-snapshot-detail-btn", "查看外部明细");
      detailButton.type = "button";
      detailButton.addEventListener("click", () => {
        selectedArchiveJobKey = definition.archiveJobKey;
        location.hash = `#archive-deliverable/${encodeURIComponent(definition.archiveJobKey)}`;
      });
      card.appendChild(detailButton);
    }
    grid.appendChild(card);
  });
  section.appendChild(grid);
  container.appendChild(section);
}

let schedulerPollTimer = null;
let schedulerNextRunCountdown = null;

async function renderDeliverablesSyncControlBar(container) {
  const controlBar = overviewEl("div", "details-sync-control-bar");

  // 左侧：运行指示与倒计时信息
  const statusWrap = overviewEl("div", "details-sync-control-status");
  const indicator = overviewEl("span", "details-sync-indicator is-running", "🟢 交付物自动同步：检测中");
  const meta = overviewEl("span", "details-sync-meta", "正在获取调度器状态...");
  statusWrap.append(indicator, meta);

  // 右侧：控制操作（频率选择、全量同步、暂停/恢复）
  const actions = overviewEl("div", "details-sync-actions");

  const intervalLabel = overviewEl("label", "details-sync-interval-label");
  intervalLabel.appendChild(overviewEl("span", null, "同步频率："));
  const intervalSelect = document.createElement("select");
  [
    [900, "每 15 分钟（默认）"],
    [1800, "每 30 分钟"],
    [3600, "每 1 小时"],
    [0, "暂停自动调度"],
  ].forEach(([val, text]) => {
    const opt = document.createElement("option");
    opt.value = String(val);
    opt.textContent = text;
    intervalSelect.appendChild(opt);
  });
  intervalLabel.appendChild(intervalSelect);

  const syncAllBtn = overviewEl("button", "btn is-primary sync-all-btn", "立即全量同步");
  syncAllBtn.type = "button";

  const pauseBtn = overviewEl("button", "btn is-secondary pause-btn", "暂停调度");
  pauseBtn.type = "button";

  actions.append(intervalLabel, syncAllBtn, pauseBtn);
  controlBar.append(statusWrap, actions);

  const msgLine = overviewEl("div", "details-sync-msg");
  msgLine.hidden = true;
  controlBar.appendChild(msgLine);

  container.appendChild(controlBar);

  async function refreshSchedulerUI() {
    try {
      const res = await fetch("/api/project-status/scheduler", { headers: { Accept: "application/json" } });
      const body = await overviewReadJson(res);
      if (!res.ok || !body || !body.data) return;
      const s = body.data;

      const isPaused = s.paused === true;
      indicator.className = `details-sync-indicator ${isPaused ? "is-paused" : "is-running"}`;
      indicator.textContent = isPaused ? "⏸️ 自动同步已暂停" : "🟢 交付物自动同步：运行中";
      pauseBtn.textContent = isPaused ? "恢复调度" : "暂停调度";

      intervalSelect.value = isPaused ? "0" : String(s.intervalSeconds || 900);
      schedulerNextRunCountdown = s.nextRunSeconds;

      updateMetaText(s.lastTickAt, schedulerNextRunCountdown, isPaused, s.eligibleCount);
    } catch (e) {
      meta.textContent = "调度器状态读取失败";
    }
  }

  function updateMetaText(lastTickAt, nextRunSeconds, isPaused, count) {
    if (isPaused) {
      meta.textContent = `已暂停自动轮询（${count || 0}项交付物绑定）· 上次完成：${lastTickAt || "暂无"}`;
      return;
    }
    const mins = nextRunSeconds !== null && nextRunSeconds !== undefined ? Math.floor(nextRunSeconds / 60) : 0;
    const secs = nextRunSeconds !== null && nextRunSeconds !== undefined ? nextRunSeconds % 60 : 0;
    const timeStr = `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
    meta.textContent = `下次自动同步：${timeStr}（共${count || 0}项已启用交付物）· 上次完成：${lastTickAt ? lastTickAt.slice(11, 19) : "无"}`;
  }

  if (schedulerPollTimer) clearInterval(schedulerPollTimer);
  schedulerPollTimer = setInterval(() => {
    if (!controlBar.isConnected) {
      clearInterval(schedulerPollTimer);
      schedulerPollTimer = null;
      return;
    }
    if (schedulerNextRunCountdown !== null && schedulerNextRunCountdown > 0) {
      schedulerNextRunCountdown -= 1;
      const mins = Math.floor(schedulerNextRunCountdown / 60);
      const secs = schedulerNextRunCountdown % 60;
      const timeSpan = controlBar.querySelector(".details-sync-meta");
      if (timeSpan && !timeSpan.textContent.includes("已暂停")) {
        const text = timeSpan.textContent;
        const updated = text.replace(/下次自动同步：\d+:\d{2}/, `下次自动同步：${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`);
        timeSpan.textContent = updated;
      }
    } else if (schedulerNextRunCountdown === 0) {
      schedulerNextRunCountdown = null;
      refreshSchedulerUI();
    }
  }, 1000);

  intervalSelect.addEventListener("change", async () => {
    const val = parseInt(intervalSelect.value, 10);
    const isPause = val === 0;
    try {
      intervalSelect.disabled = true;
      const payload = isPause ? { paused: true } : { intervalSeconds: val, paused: false };
      const res = await fetch("/api/project-status/scheduler/config", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await overviewReadJson(res);
      if (!res.ok || !body || !body.ok) throw new Error(body?.error?.message || "更新配置失败");
      await refreshSchedulerUI();
      msgLine.textContent = isPause ? "已暂停交付物自动同步调度。" : `自动同步频率已调整为 ${intervalSelect.options[intervalSelect.selectedIndex].text}。`;
      msgLine.hidden = false;
      setTimeout(() => { msgLine.hidden = true; }, 4000);
    } catch (err) {
      alert(err.message);
    } finally {
      intervalSelect.disabled = false;
    }
  });

  pauseBtn.addEventListener("click", async () => {
    try {
      pauseBtn.disabled = true;
      const isPausing = pauseBtn.textContent.includes("暂停");
      const res = await fetch("/api/project-status/scheduler/config", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ paused: isPausing }),
      });
      const body = await overviewReadJson(res);
      if (!res.ok || !body || !body.ok) throw new Error(body?.error?.message || "更新配置失败");
      await refreshSchedulerUI();
    } catch (err) {
      alert(err.message);
    } finally {
      pauseBtn.disabled = false;
    }
  });

  syncAllBtn.addEventListener("click", async () => {
    try {
      syncAllBtn.disabled = true;
      syncAllBtn.textContent = "正在全量同步...";
      msgLine.textContent = "正在并发同步全部已启用交付物，请稍候...";
      msgLine.hidden = false;
      const res = await fetch("/api/project-status/scheduler/sync-all", {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      const body = await overviewReadJson(res);
      if (!res.ok || !body || !body.ok) throw new Error(body?.error?.message || "全量同步失败");
      const results = body.data?.results || [];
      const successes = results.filter((r) => r.status === "success").length;
      msgLine.textContent = `全量同步完成：成功同步 ${successes}/${results.length} 项交付物。`;
      await refreshSchedulerUI();
      await loadProjectOverview();
      setTimeout(() => { msgLine.hidden = true; }, 5000);
    } catch (err) {
      msgLine.textContent = `全量同步失败：${err.message}`;
      msgLine.hidden = false;
    } finally {
      syncAllBtn.disabled = false;
      syncAllBtn.textContent = "立即全量同步";
    }
  });

  await refreshSchedulerUI();
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
  renderDeliverablesSyncControlBar(container);
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

const EWO_POLICY_MODE_LABELS = {
  manual: "手动维护",
  automatic: "自动同步",
  hybrid: "混合模式",
};
const EWO_POLICY_RECOMMENDED_MODE = "automatic";
const EWO_POLICY_DEFAULT_ARAS_BASE_URL = "http://ecm.sgmw.com.cn/innovatorserver";
const EWO_POLICY_MATCH_FIELDS = [
  ["ewoNo", "EWO 编号", "ewo_no"],
  ["projectCode", "车型项目", "project_code"],
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

function ewoPolicyString(value) {
  return typeof value === "string" ? value.trim() : "";
}

function normalizeTdcDepartment(dept) {
  if (!dept || typeof dept !== "string") return "";
  const trimmed = dept.trim();
  if (trimmed === "技术中心") return trimmed;
  if (/^技术中心[_-]?/.test(trimmed)) {
    return trimmed.replace(/^技术中心[_-]?/, "").trim();
  }
  return trimmed;
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
  let msg = error instanceof Error ? error.message : String(error || "");
  if (msg.includes("映射发现证据与当前配置规则不一致")) {
    return "配置规则已更新，系统已自动重置证据；请点击“保存同步绑定”或重新抓取证据";
  }
  if (msg.includes("外部稳定键")) {
    msg = msg.replace(/外部稳定键/g, "目标单号");
  }
  return msg;
}

// 保存成功后的状态提示：详情页重绘由 loadProjectOverview 的
// handleHashChange 异步触发，新编辑器的 .policy-request-status 需等策略
// 加载完成才存在——立即查询必然为 null（GPT 终审 P2），故经此槽传递。
let pendingPolicyStatusMessage = null;

// ── 数据同步摘要卡与「开启自动同步」轻量向导（HCI 重排 A1/A2/A4）──────
// 摘要卡只消费既有 payload（updatePolicy 的 lastAttemptAt/lastSuccessAt/
// lastErrorMessage 与 syncDisplay.state/label），不新增后端端点；
// 完整绑定表单整体迁入「高级设置」details 折叠区（默认收起，A3），
// 保存逻辑复用 renderSyncBindingEditor 原有 submit 流程。

const POLICY_SYNC_HINTS = {
  pending_config: "绑定已就绪，开启自动同步后将映射外部状态；当前显示的是手工填写值。",
  manual: "该交付物当前为手工维护；可开启自动同步，或在高级设置中配置绑定。",
  paused: "自动同步已暂停；可开启自动同步恢复，或在高级设置中调整绑定。",
};

// 向导默认证据连接（个人单机、仅内网场景）：与能力注册表 evidenceFields
// 声明的连接输入一致的内网默认值（不保存任何凭据或请求头）。
const POLICY_WIZARD_TDC_DEFAULT_BASE_URL = "https://tdc.sgmw.com.cn/";

const DELIVERABLE_DEFAULT_MAPPINGS = {
  "VPI-T2-D2": { owner: "startUserName", note: ["latestCompletedNode", "processInstanceStatus"] },
  "VPI-T2-D3": { owner: "_rsp_name", plannedDate: "_required_date", note: ["_subject", "_change_description"] },
  "VPI-T2-D5": { owner: "applicant", note: ["latestApproveLog", "status"] },
};

const DELIVERABLE_FIELD_ALIASES = {
  owner: ["_rsp_name", "责任工程师名称", "startUserName", "applicant", "申请人", "owner", "_owner", "起草人", "engineer"],
  plannedDate: ["_required_date", "要求完成时间", "req_completion_date", "planned_date"],
  note: ["当前阶段未签署的角色&人员", "当前阶段未签署的角色", "_subject", "_change_description", "latestCompletedNode", "processInstanceStatus", "approvalStatus", "latestApproveLog", "status", "待审批人员", "pendingApprover", "主题", "更改描述"],
};

function wizardPrimaryMatchField(capabilities) {
  const matchFields = Array.isArray(capabilities.matchFields) ? capabilities.matchFields : [];
  const primary = matchFields[0];
  if (!Array.isArray(primary) || !primary[0]) return null;
  return {
    key: primary[0],
    label: primary[1] || primary[0],
    filterName: primary[2] || primary[0],
    placeholder: primary[3] || "",
  };
}

function wizardEvidenceDefaults(capabilities) {
  if (capabilities.sourceType === "aras") {
    return { base_url: EWO_POLICY_DEFAULT_ARAS_BASE_URL };
  }
  if (capabilities.sourceType === "tdc") {
    return { base_url: POLICY_WIZARD_TDC_DEFAULT_BASE_URL, auth_mode: "browser" };
  }
  return {};
}

function wizardQuotedHints(text) {
  // 能力注册表 fieldSemantics 用「…」标注来源列名；提取作为映射提示。
  const hints = [];
  const pattern = /「([^」]+)」/g;
  let match;
  while ((match = pattern.exec(String(text || ""))) !== null) {
    hints.push(match[1]);
  }
  return hints;
}

// 列名归一化：trim + 大小写折叠 + 下划线/连字符移除，用于提示词与
// 报告字段名的全等比较（避免子串包含把无关列并入映射）。
function wizardNormalizeColumnKey(value) {
  return ewoPolicyString(value).trim().toLowerCase().replace(/[_-]/g, "");
}

// 从最新一次脱敏字段报告推导自动字段映射：提示只取 fieldSemantics 中
// 「」引用的来源列名，且仅写回报告中真实存在的字段；推导不出任何结果
// 时返回 null（向导降级为可重试错误并引导到高级设置，绝不猜测映射）。
function wizardDeriveMappingFromFieldReport(capabilities, fieldReport) {
  const fields = fieldReport && Array.isArray(fieldReport.fields)
    ? fieldReport.fields.map((value) => ewoPolicyString(value)).filter(Boolean)
    : [];
  if (fields.length === 0) return null;
  const semantics = capabilities.fieldSemantics && typeof capabilities.fieldSemantics === "object"
    ? capabilities.fieldSemantics
    : {};
  const mapping = {};
  ["owner", "plannedDate", "note"].forEach((key) => {
    const hints = wizardQuotedHints(semantics[key]);
    if (hints.length === 0) return;
    if (key === "note") {
      // 风险备注来源列：归一化全等匹配（列名与提示词在 trim、大小写
      // 折叠、下划线/连字符归一后完全相等才算命中）；全等无命中保持
      // 空来源（不写 note 键），绝不回退子串包含——避免把含提示词
      // 子串的无关列并入风险备注。后端仅 note 支持列表来源。
      const normalizedHints = hints.map(wizardNormalizeColumnKey);
      const noteMatches = fields.filter((name) => {
        const normalized = wizardNormalizeColumnKey(name);
        return normalized !== "" && normalizedHints.includes(normalized);
      });
      if (noteMatches.length === 0) return;
      mapping[key] = noteMatches;
      return;
    }
    const matches = fields.filter((name) => hints.some((hint) => name.indexOf(hint) !== -1));
    if (matches.length === 1) {
      mapping[key] = matches[0];
    }
  });
  return Object.keys(mapping).length > 0 ? mapping : null;
}

async function postMappingDiscovery(deliverableId, payload) {
  const response = await fetch(`/api/project-status/deliverables/${encodeURIComponent(deliverableId)}/mapping-discovery`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await overviewReadJson(response);
  if (!response.ok || !body || body.ok !== true) throw overviewRequestError(body, response.status);
  return body.data || {};
}

function buildSyncSummaryCard(item, policy, capabilities, settings, advancedDetails) {
  const currentPolicy = policy && typeof policy === "object" ? policy : {};
  const vaultConfigured = settings !== null && settings !== undefined && settings.credentialVaultConfigured === true;
  const syncDisplay = deliverableSyncDisplay(item);
  const card = overviewEl("section", "policy-sync-summary");
  card.setAttribute("aria-label", `${item.name} 数据同步`);

  const head = overviewEl("div", "policy-sync-summary-head");
  head.append(
    overviewEl("strong", "policy-sync-summary-title", "数据同步"),
    overviewEl("span", "policy-sync-summary-state", syncDisplay.label),
  );
  card.appendChild(head);

  // A4：pending_config / manual（及暂停）态的定位说明。
  const hint = POLICY_SYNC_HINTS[syncDisplay.state];
  if (hint) card.appendChild(overviewEl("p", "policy-sync-summary-hint", hint));

  const storedMatchRule = (currentPolicy.matchRule && typeof currentPolicy.matchRule === "object") ? currentPolicy.matchRule : {};
  const factList = [
    ["最近尝试", safeDisplayValue(currentPolicy.lastAttemptAt || "无")],
    ["最近成功", safeDisplayValue(currentPolicy.lastSuccessAt || "无")],
  ];
  if (currentPolicy.enabled === true) {
    const currentModel = storedMatchRule.projectCode || storedMatchRule.modelInfo || storedMatchRule.carTypeProject || storedMatchRule.projectModel;
    const currentDept = storedMatchRule.rspDepartment || storedMatchRule.department;
    if (currentModel) factList.push(["车型项目", safeDisplayValue(currentModel)]);
    if (currentDept) factList.push(["责任部门", safeDisplayValue(currentDept)]);
    factList.push(["同步周期", `每 ${currentPolicy.intervalMinutes || 15} 分钟`]);
  }
  factList.push([
    "最近错误",
    currentPolicy.lastErrorMessage ? redactSensitiveText(String(currentPolicy.lastErrorMessage)) : "无",
  ]);
  const facts = overviewEl("ul", "policy-sync-summary-facts");
  factList.forEach(([label, value]) => {
    const row = overviewEl("li", "policy-sync-summary-fact");
    row.append(
      overviewEl("span", "policy-sync-fact-label", label),
      overviewEl("span", "policy-sync-fact-value", value),
    );
    facts.appendChild(row);
  });
  card.appendChild(facts);

  const actions = overviewEl("div", "policy-sync-summary-actions");
  const wizardStatus = overviewEl("p", "policy-sync-wizard-status");
  wizardStatus.setAttribute("role", "status");
  wizardStatus.setAttribute("aria-live", "polite");
  const wizardHost = overviewEl("div", "policy-sync-wizard");
  wizardHost.hidden = true;

  const enableBtn = overviewEl("button", "policy-sync-enable-btn", "开启自动同步");
  enableBtn.type = "button";
  enableBtn.hidden = !(capabilities.syncCapable === true && currentPolicy.enabled !== true);
  const reconfigBtn = overviewEl("button", "policy-sync-reconfig-btn", "修改同步配置");
  reconfigBtn.type = "button";
  reconfigBtn.hidden = !(capabilities.syncCapable === true && currentPolicy.enabled === true);
  reconfigBtn.addEventListener("click", () => {
    wizardHost.hidden = !wizardHost.hidden;
  });
  const syncNowBtn = overviewEl("button", "policy-sync-now-btn", "立即同步");
  syncNowBtn.type = "button";
  syncNowBtn.hidden = currentPolicy.enabled !== true;
  const advancedBtn = overviewEl("button", "policy-sync-advanced-btn", "高级设置");
  advancedBtn.type = "button";
  advancedBtn.setAttribute("aria-expanded", advancedDetails.open ? "true" : "false");
  advancedBtn.addEventListener("click", () => {
    advancedDetails.open = !advancedDetails.open;
    advancedBtn.setAttribute("aria-expanded", advancedDetails.open ? "true" : "false");
  });
  actions.append(syncNowBtn, reconfigBtn, enableBtn, advancedBtn);
  card.append(actions, wizardStatus, wizardHost);

  // ── A2：轻量向导。默认项目聚合，支持一键配置并启用 ─────────
  const primary = wizardPrimaryMatchField(capabilities);
  const isEwo = capabilities.reportType === "ewo";
  const isSor = capabilities.reportType === "sor";
  const isDataModel = capabilities.reportType === "data_model";

  const credentialLabel = overviewEl("label", "policy-ewo-field policy-wizard-field");
  credentialLabel.appendChild(overviewEl("span", null, "同步凭据引用"));
  const credentialSelect = document.createElement("select");
  const keepCredential = overviewEl(
    "option",
    null,
    currentPolicy.credentialAvailable === true ? "保持当前已绑定凭据（不修改）" : "暂不绑定",
  );
  keepCredential.value = "";
  const domainCredential = overviewEl("option", null, "统一域账号（domain）");
  domainCredential.value = "domain";
  credentialSelect.append(keepCredential, domainCredential);
  if (vaultConfigured) credentialSelect.value = "domain";
  else if (currentPolicy.credentialAvailable === true) credentialSelect.value = "";
  credentialLabel.appendChild(credentialSelect);
  credentialLabel.appendChild(overviewEl(
    "small",
    "policy-field-note",
    currentPolicy.credentialAvailable === true || vaultConfigured
      ? "使用已保存的统一域账号自动登录内网抓取数据。"
      : "请先到系统设置登录并勾选“保存至凭据保护库”。",
  ));
  wizardHost.appendChild(credentialLabel);

  // 1. 车型项目 / 车型信息
  const modelLabel = overviewEl("label", "policy-ewo-field policy-wizard-field");
  modelLabel.appendChild(overviewEl("span", null, "车型项目 / 车型信息"));
  const modelInput = document.createElement("input");
  modelInput.type = "text";
  modelInput.maxLength = 200;
  modelInput.placeholder = "例如 F610S 或 N300（整车项目聚合）";
  const initialModel = ewoPolicyString(
    storedMatchRule.projectCode
    || storedMatchRule.modelInfo
    || storedMatchRule.carTypeProject
    || storedMatchRule.projectModel
    || ""
  );
  modelInput.value = initialModel;
  modelLabel.appendChild(modelInput);
  wizardHost.appendChild(modelLabel);

  // 2. 责任部门
  const departmentLabel = overviewEl("label", "policy-ewo-field policy-wizard-field");
  departmentLabel.appendChild(overviewEl("span", null, "责任部门"));
  const departmentInput = document.createElement("input");
  departmentInput.type = "text";
  departmentInput.maxLength = 200;
  const isTdc = isSor || isDataModel || (capabilities && capabilities.sourceType === "tdc");
  const defaultDept = isTdc ? "车体工程" : "技术中心_车体工程";
  const initialDept = ewoPolicyString(
    storedMatchRule.rspDepartment
    || storedMatchRule.department
    || defaultDept
  );
  departmentInput.value = initialDept;
  departmentInput.placeholder = isTdc ? "TDC 部门（如 车体工程，支持留空）" : "默认：技术中心_车体工程";
  departmentLabel.appendChild(departmentInput);
  departmentLabel.appendChild(overviewEl(
    "small",
    "policy-field-note",
    isTdc
      ? "TDC 部门（如“车体工程”），支持留空查询全量数据。请勿填写 Aras 形式“技术中心_车体工程”。"
      : "默认筛选“技术中心_车体工程”，支持按需修改。"
  ));
  wizardHost.appendChild(departmentLabel);

  // 3. 定时同步周期
  const intervalLabel = overviewEl("label", "policy-ewo-field policy-wizard-field");
  intervalLabel.appendChild(overviewEl("span", null, "定时自动同步周期"));
  const intervalSelect = document.createElement("select");
  [
    ["15", "每 15 分钟（推荐）"],
    ["30", "每 30 分钟"],
    ["60", "每 1 小时"],
    ["360", "每 6 小时"],
    ["1440", "每天"],
  ].forEach(([val, label]) => {
    const opt = overviewEl("option", null, label);
    opt.value = val;
    intervalSelect.appendChild(opt);
  });
  intervalSelect.value = String(currentPolicy.intervalMinutes || 15);
  intervalLabel.appendChild(intervalSelect);
  wizardHost.appendChild(intervalLabel);

  // 4. 单工单编号（选填，留空则整车项目聚合）
  const numberLabel = overviewEl("label", "policy-ewo-field policy-wizard-field");
  numberLabel.appendChild(overviewEl("span", null, isEwo ? "EWO 编号（选填，留空则整车聚合）" : (primary ? `${primary.label}（选填）` : "外部编号（选填）")));
  const numberInput = document.createElement("input");
  numberInput.type = "text";
  numberInput.maxLength = 200;
  numberInput.placeholder = "选填，留空将对整车项目全部单据进行聚合统计";
  if (storedMatchRule.ewoNo || storedMatchRule.processNo || storedMatchRule.incident) {
    numberInput.value = ewoPolicyString(storedMatchRule.ewoNo || storedMatchRule.processNo || storedMatchRule.incident || "");
  }
  numberLabel.appendChild(numberInput);
  wizardHost.appendChild(numberLabel);

  const startBtn = overviewEl(
    "button",
    "policy-wizard-start-btn",
    currentPolicy.enabled === true ? "保存配置并同步" : "开始配置并启用",
  );
  startBtn.type = "button";
  wizardHost.appendChild(startBtn);

  const setWizardStatus = (message, isError = false) => {
    updatePolicyStatusMessage(wizardStatus, message, isError);
  };

  // 重挂向导输入区
  const remountWizardInputs = () => {
    wizardHost.textContent = "";
    wizardHost.appendChild(credentialLabel);
    wizardHost.appendChild(modelLabel);
    wizardHost.appendChild(departmentLabel);
    wizardHost.appendChild(intervalLabel);
    wizardHost.appendChild(numberLabel);
    wizardHost.appendChild(startBtn);
  };

  enableBtn.addEventListener("click", () => {
    wizardHost.hidden = !wizardHost.hidden;
  });

  const syncResultText = (data) => {
    const result = data && typeof data === "object" ? data.result || {} : {};
    const finalState = result.finalState || (data && data.finalState);
    const outcome = result.outcome || (data && data.outcome) || finalState;
    const message = redactSensitiveText(
      result.errorMessage || (data && data.errorMessage) || "",
    );
    if (finalState === "busy" || outcome === "busy") return message ? `同步进行中：${message}` : "同步进行中";
    if (finalState === "success" && outcome === "completed") return "同步完成：成功";
    if (finalState === "partial" || outcome === "partial") return "同步完成：部分字段已应用";
    if (finalState === "needs_attention" || outcome === "needs_attention") {
      return `同步需要处理：${message || "未匹配到唯一候选"}`;
    }
    return `同步失败：${message || (finalState ? `状态 ${finalState}` : "未知状态")}`;
  };

  // 候选不唯一（仅非聚合绑定会出现）：列出候选让用户选一次。
  const pickCandidateOnce = (candidates) => new Promise((resolve, reject) => {
    wizardHost.textContent = "";
    const list = overviewEl("div", "policy-wizard-candidates");
    list.appendChild(overviewEl("p", "policy-field-note", "候选记录不唯一，请选择一次目标记录："));
    const select = document.createElement("select");
    (candidates || []).forEach((candidate) => {
      const key = ewoPolicyString(candidate && candidate.externalKey);
      if (!key) return;
      const opt = overviewEl("option", null, key);
      opt.value = key;
      select.appendChild(opt);
    });
    const confirmBtn = overviewEl("button", "policy-wizard-candidate-btn", "确认所选候选");
    confirmBtn.type = "button";
    confirmBtn.addEventListener("click", () => resolve(ewoPolicyString(select.value)));
    list.append(select, confirmBtn);
    wizardHost.appendChild(list);
    if (!select.options.length) reject(new Error("候选记录缺少外部稳定键，请使用高级设置完成绑定。"));
  });

  startBtn.addEventListener("click", async () => {
    const modelVal = ewoPolicyString(modelInput.value);
    const rawDeptVal = ewoPolicyString(departmentInput.value);
    const deptVal = isTdc ? normalizeTdcDepartment(rawDeptVal) : rawDeptVal;
    const specificNo = ewoPolicyString(numberInput.value);
    const intervalMins = parseInt(intervalSelect.value, 10) || 15;

    if (
      currentPolicy.credentialAvailable !== true
      && !(credentialSelect.value === "domain" && vaultConfigured)
      && !vaultConfigured
    ) {
      setWizardStatus("系统设置未检测到凭据保护库，请先登录并保存统一域账号。", true);
      return;
    }

    if (!specificNo && !modelVal && primary) {
      setWizardStatus("请填写车型项目或车型信息（例如 F610S）。", true);
      return;
    }

    startBtn.disabled = true;
    remountWizardInputs();

    try {
      const aggregate = !specificNo;
      const filters = {};
      const matchRule = {
        reportType: capabilities.reportType || (isEwo ? "ewo" : ""),
        aggregate,
      };

      if (isEwo) {
        matchRule.contractVersion = "2";
        matchRule.bindingMode = aggregate ? "record_set" : "single_record";
        if (modelVal) {
          matchRule.projectCode = modelVal;
          filters.project_code = modelVal;
        }
        if (deptVal) {
          matchRule.rspDepartment = deptVal;
          filters.rsp_department = deptVal;
        }
        if (specificNo) {
          matchRule.ewoNo = specificNo;
          filters.ewo_no = specificNo;
        }
      } else if (isSor) {
        if (modelVal) {
          matchRule.carTypeProject = modelVal;
          filters.car_type_project = modelVal;
        }
        if (deptVal) {
          matchRule.department = deptVal;
          filters.department = deptVal;
        }
        if (specificNo) {
          matchRule.processNo = specificNo;
          filters.serial_number = specificNo;
        }
      } else if (isDataModel) {
        if (modelVal) {
          matchRule.projectModel = modelVal;
          filters.project_model = modelVal;
        }
        if (deptVal) {
          matchRule.department = deptVal;
          filters.department = deptVal;
        }
        if (specificNo) {
          matchRule.incident = specificNo;
          filters.serial_number = specificNo;
        }
      } else if (primary) {
        filters[primary.filterName] = specificNo || modelVal;
        matchRule[primary.key] = specificNo || modelVal;
      }

      setWizardStatus("正在抓取映射证据（第 1/2 次）...");
      const payload = {
        filters,
        selectedExternalKey: specificNo || null,
        aggregate,
        ...wizardEvidenceDefaults(capabilities),
      };
      if (isEwo) {
        payload.contractVersion = "2";
        payload.bindingMode = aggregate ? "record_set" : "single_record";
      }

      let result = await postMappingDiscovery(item.id, payload);
      if (result.state === "ambiguous" && !aggregate) {
        setWizardStatus("候选不唯一，请选择一次目标记录。");
        const selected = await pickCandidateOnce(result.candidates);
        remountWizardInputs();
        payload.selectedExternalKey = selected;
        result = await postMappingDiscovery(item.id, payload);
      }
      if (result.state !== "matched" && isTdc && deptVal) {
        setWizardStatus("指定部门未匹配，正在尝试不限部门自动重试...");
        const retryFilters = { ...filters };
        delete retryFilters.department;
        delete retryFilters.rsp_department;
        const retryPayload = {
          ...payload,
          filters: retryFilters,
        };
        const retryResult = await postMappingDiscovery(item.id, retryPayload);
        if (retryResult && (retryResult.state === "matched" || (retryResult.state === "ambiguous" && !aggregate))) {
          result = retryResult;
          delete filters.department;
          delete filters.rsp_department;
          delete matchRule.department;
          delete matchRule.rspDepartment;
        }
      }
      if (result.state !== "matched") {
        const cCount = Number.isFinite(result.candidateCount) ? result.candidateCount : 0;
        const fCount = result.fieldReport && Array.isArray(result.fieldReport.fields) ? result.fieldReport.fields.length : 0;
        throw new Error(`映射发现未匹配（${ewoPolicyDiscoveryStateLabel(result.state)}，命中行数：${cCount}，字段数：${fCount}），请核对车型与筛选条件后重试。`);
      }

      // ② 稳定性取证 2/2
      let confirmed = Number(result.stability && result.stability.confirmed);
      if (!Number.isFinite(confirmed) || confirmed < 2) {
        setWizardStatus("正在验证映射稳定性（第 2/2 次）...");
        result = await postMappingDiscovery(item.id, payload);
        confirmed = Number(result.stability && result.stability.confirmed);
        if (result.state !== "matched" || !Number.isFinite(confirmed) || confirmed < 2) {
          throw new Error("映射稳定性未就绪（需连续两次一致的脱敏证据），请稍后重试。");
        }
      }

      // ③ 字段映射与归属
      let mapping = {};
      const fieldAuthority = {};
      if (aggregate) {
        // 项目集合聚合模式：仅自动更新风险备注，负责人与计划完成日期由人工维护
        if (isEwo) {
          mapping = { note: ["_change_description", "_subject"] };
          fieldAuthority.plannedDate = "manual";
        } else if (isSor) {
          mapping = { note: ["latestCompletedNode", "processInstanceStatus"] };
        } else if (isDataModel) {
          mapping = { note: ["latestApproveLog", "status"] };
        } else if (capabilities.defaultMapping && capabilities.defaultMapping.note) {
          mapping = { note: capabilities.defaultMapping.note };
        } else {
          mapping = { note: ["status"] };
        }
        fieldAuthority.note = "automatic";
        fieldAuthority.owner = "manual";
      } else {
        mapping = wizardDeriveMappingFromFieldReport(capabilities, result.fieldReport);
        if (!mapping && capabilities && capabilities.defaultMapping && Object.keys(capabilities.defaultMapping).length > 0) {
          mapping = { ...capabilities.defaultMapping };
        }
        if (!mapping) {
          throw new Error("无法从最新脱敏字段报告确定自动字段映射，请打开高级设置手工完成映射后保存。");
        }
        Object.keys(mapping).forEach((key) => { fieldAuthority[key] = "automatic"; });
      }

      // ④ 保存同步绑定并启用（一键完成）
      setWizardStatus("正在保存配置并启用自动同步...");
      const patch = {
        mode: "automatic",
        enabled: true,
        externalKey: aggregate ? null : (ewoPolicyString(result.externalKey) || payload.selectedExternalKey || null),
        matchRule,
        mapping,
        fieldAuthority,
        intervalMinutes: intervalMins,
      };
      if (isEwo) patch.bindingContractVersion = "2";
      if (credentialSelect.value === "domain" || vaultConfigured) {
        patch.credentialRef = "domain";
      }

      const saveResponse = await fetch(`/api/project-status/deliverables/${encodeURIComponent(item.id)}/update-policy`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(patch),
      });
      const saveBody = await overviewReadJson(saveResponse);
      if (!saveResponse.ok || !saveBody || saveBody.ok !== true) {
        throw overviewRequestError(saveBody, saveResponse.status);
      }

      // ⑤ 触发首次同步
      setWizardStatus("配置已启用，正在触发首次同步...");
      const syncData = await requestProjectStatusSync(item);
      setWizardStatus(`配置并启用成功！${syncResultText(syncData)}`);
      startBtn.disabled = false;
      await loadProjectOverview();
    } catch (err) {
      setWizardStatus(`配置启用失败：${redactSensitiveText(ewoPolicyErrorMessage(err))}`, true);
      remountWizardInputs();
      startBtn.disabled = false;
    }
  });

  // 立即同步：复用既有 requestProjectStatusSync → POST sync-now。
  syncNowBtn.addEventListener("click", async () => {
    syncNowBtn.disabled = true;
    setWizardStatus("正在同步...");
    try {
      const data = await requestProjectStatusSync(item);
      setWizardStatus(syncResultText(data));
      await loadProjectOverview();
    } catch (err) {
      setWizardStatus(`同步失败：${redactSensitiveText(ewoPolicyErrorMessage(err))}`, true);
    } finally {
      syncNowBtn.disabled = false;
    }
  });

  return card;
}

function renderSyncBindingEditor(container, item, policy, options = {}) {
  container.textContent = "";
  const currentPolicy = policy && typeof policy === "object" ? policy : {};
  // 能力配置由后端 sourceInfo 下发（core 能力注册表单一来源）；
  // 缺省时按 ARAS EWO 兜底，保证契约内交付物始终可用。
  const capabilities = item.sourceInfo && typeof item.sourceInfo === "object"
    ? item.sourceInfo
    : { sourceType: "aras", reportType: "ewo", displayName: "ARAS EWO" };
  const matchFields = Array.isArray(capabilities.matchFields)
    ? capabilities.matchFields
    : EWO_POLICY_MATCH_FIELDS;
  const evidenceFields = Array.isArray(capabilities.evidenceFields)
    ? capabilities.evidenceFields
    : [{ name: "base_url", label: "ECM 地址（仅用于抓取映射证据）", type: "url" }];
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
    overviewEl("span", "policy-source", `数据来源 · ${capabilities.displayName || item.source || "外部来源"}`),
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
  externalKeyLabel.appendChild(overviewEl("span", null, "关联目标单号"));
  const externalKeyInput = document.createElement("input");
  externalKeyInput.type = "text";
  externalKeyInput.name = "externalKey";
  externalKeyInput.id = `policy-external-key-${itemToken}`;
  externalKeyInput.maxLength = 200;
  externalKeyInput.value = ewoPolicyString(currentPolicy.externalKey);
  externalKeyInput.placeholder = "选填，输入需跟踪的目标单号（留空自动关联）";
  externalKeyLabel.appendChild(externalKeyInput);
  externalKeyLabel.appendChild(overviewEl("small", "policy-field-note", "需跟踪的外部单号；如留空，将在保存或抓取时根据匹配条件自动关联。"));
  bindingGrid.appendChild(externalKeyLabel);
  const ewoBindingMode = capabilities.reportType === "ewo" ? document.createElement("select") : null;
  if (ewoBindingMode) ewoBindingMode.name = "ewoBindingMode";
  const storedEwoRule = currentPolicy.matchRule || {};
  if (ewoBindingMode) {
    const modeLabel = overviewEl("label", "policy-ewo-field");
    modeLabel.appendChild(overviewEl("span", null, "EWO绑定合同"));
    [["legacy", "保留旧版规则"], ["record_set", "新版：记录集合"], ["single_record", "新版：固定单条记录"]].forEach(([value, label]) => {
      if (value === "legacy" && storedEwoRule.contractVersion === "2") return;
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      ewoBindingMode.appendChild(option);
    });
    ewoBindingMode.value = storedEwoRule.contractVersion === "2" ? storedEwoRule.bindingMode : "legacy";
    modeLabel.appendChild(ewoBindingMode);
    modeLabel.appendChild(overviewEl("small", "policy-field-note", "旧版保持原有单条/多条写入规则。迁移到新版须先停用保存，再重新取证；集合负责人和计划日期始终手工。"));
    bindingGrid.appendChild(modeLabel);
  }

  const intervalLabel = overviewEl("label", "policy-ewo-field");
  intervalLabel.appendChild(overviewEl("span", null, "定时同步周期"));
  const intervalInput = document.createElement("select");
  intervalInput.name = "intervalMinutes";
  [
    ["15", "每 15 分钟（推荐）"],
    ["30", "每 30 分钟"],
    ["60", "每 1 小时"],
    ["360", "每 6 小时"],
    ["1440", "每天"],
  ].forEach(([val, label]) => {
    const opt = overviewEl("option", null, label);
    opt.value = val;
    intervalInput.appendChild(opt);
  });
  intervalInput.value = String(currentPolicy.intervalMinutes || 15);
  intervalLabel.appendChild(intervalInput);
  intervalLabel.appendChild(overviewEl("small", "policy-field-note", "设置常驻后台调度器自动同步该交付物状态的执行频率。"));
  bindingGrid.appendChild(intervalLabel);

  const matchGroup = overviewEl("fieldset", "policy-ewo-match");
  matchGroup.appendChild(overviewEl("legend", null, `匹配规则（报表类型固定为 ${capabilities.reportType || "ewo"}）`));
  const reportType = overviewEl("span", "policy-ewo-fixed-value", `reportType = ${capabilities.reportType || "ewo"}`);
  matchGroup.appendChild(reportType);
  const matchRule = currentPolicy.matchRule && typeof currentPolicy.matchRule === "object"
    ? currentPolicy.matchRule
    : {};
  const matchInputs = new Map();
  matchFields.forEach((fieldDef) => {
    const [key, label, filterName, placeholder] = Array.isArray(fieldDef) ? fieldDef : [fieldDef, fieldDef, fieldDef, "可选"];
    const field = overviewEl("label", "policy-ewo-field");
    field.appendChild(overviewEl("span", null, label));
    const input = document.createElement("input");
    input.type = "text";
    input.dataset.matchKey = key;
    input.dataset.filterName = filterName || key;
    input.value = ewoPolicyString(matchRule[key]);
    input.placeholder = placeholder || "可选";
    input.addEventListener("input", () => {
      if ((key === "ewoNo" || key === "sourceItemId") && !externalKeyInput.value.trim()) {
        externalKeyInput.value = input.value.trim();
      }
    });
    field.appendChild(input);
    matchInputs.set(key, input);
    matchGroup.appendChild(field);
  });
  matchGroup.appendChild(overviewEl("small", "policy-field-note", "至少填写一个筛选条件；保存启用时后端会再次校验来源契约。"));
  bindingGrid.appendChild(matchGroup);

  // 映射证据来源连接：按能力配置渲染（aras 需 ECM 地址；tdc 需地址+认证头）。
  const evidenceGroup = overviewEl("fieldset", "policy-ewo-evidence-source");
  evidenceGroup.appendChild(overviewEl("legend", null, "映射证据来源连接"));
  const evidenceInputs = new Map();
  evidenceFields.forEach((fieldDef) => {
    const field = overviewEl("label", "policy-ewo-field");
    field.appendChild(overviewEl("span", null, fieldDef.label || fieldDef.name));
    let input;
    if (fieldDef.type === "select") {
      input = document.createElement("select");
      (fieldDef.options || []).forEach((option) => {
        const opt = overviewEl("option", null, option);
        opt.value = option;
        input.appendChild(opt);
      });
      input.value = fieldDef.options && fieldDef.options.length ? fieldDef.options[0] : "";
    } else if (fieldDef.type === "textarea") {
      input = document.createElement("textarea");
      input.rows = 2;
      if (fieldDef.placeholder) input.placeholder = fieldDef.placeholder;
    } else {
      input = document.createElement("input");
      input.type = fieldDef.type || "text";
      if (fieldDef.placeholder) input.placeholder = fieldDef.placeholder;
    }
    input.dataset.evidenceField = fieldDef.name;
    if (fieldDef.type !== "textarea" && fieldDef.type !== "select"
      && fieldDef.name === "base_url" && capabilities.sourceType === "aras"
      && !input.value) {
      input.value = EWO_POLICY_DEFAULT_ARAS_BASE_URL;
    }
    field.appendChild(input);
    evidenceInputs.set(fieldDef.name, input);
    evidenceGroup.appendChild(field);
  });
  bindingGrid.appendChild(evidenceGroup);
  bindingGroup.appendChild(bindingGrid);

  const authorityGroup = overviewEl("fieldset", "policy-ewo-authority");
  authorityGroup.appendChild(overviewEl("legend", null, "自动字段与来源映射"));
  let discoveredFields = new Set(ewoPolicyDiscoveryFields(discoveryData));
  const defaultMap = (capabilities && capabilities.defaultMapping && Object.keys(capabilities.defaultMapping).length > 0)
    ? capabilities.defaultMapping
    : (DELIVERABLE_DEFAULT_MAPPINGS[item.id] || {});

  EWO_POLICY_AUTOMATIC_FIELDS.forEach(([key, label]) => {
    const row = overviewEl("div", "policy-ewo-mapping-row");
    const authorityLabel = overviewEl("label", "policy-field-check");
    const authorityInput = document.createElement("input");
    authorityInput.type = "checkbox";
    authorityInput.name = `fieldAuthority-${key}`;
    authorityInput.dataset.authorityField = key;

    const existingVal = currentPolicy.mapping && currentPolicy.mapping[key];
    const initialVal = existingVal != null
      ? (Array.isArray(existingVal) ? existingVal.join("｜") : ewoPolicyString(existingVal))
      : (defaultMap[key] != null ? (Array.isArray(defaultMap[key]) ? defaultMap[key].join("｜") : String(defaultMap[key])) : "");

    authorityInput.checked = currentPolicy.fieldAuthority
      ? (currentPolicy.fieldAuthority[key] === "automatic")
      : Boolean(initialVal);
    authorityLabel.append(authorityInput, overviewEl("span", null, `${label}自动更新`));

    const mappingInput = document.createElement("input");
    mappingInput.type = "text";
    mappingInput.name = `mapping-${key}`;
    mappingInput.dataset.mappingField = key;
    mappingInput.setAttribute("list", `policy-discovered-fields-${itemToken}`);
    mappingInput.value = initialVal;
    const placeholderVal = Array.isArray(defaultMap[key]) ? defaultMap[key].join("｜") : (defaultMap[key] || "_owner");
    mappingInput.placeholder = `推荐：${placeholderVal}`;
    mappingInput.disabled = !authorityInput.checked;
    const mappingLabel = overviewEl("label", "policy-ewo-field policy-ewo-mapping-field");
    mappingLabel.append(overviewEl("span", null, `${label}来源字段`), mappingInput);
    row.append(authorityLabel, mappingLabel);
    authorityGroup.appendChild(row);
    authorityInput.addEventListener("change", () => {
      mappingInput.disabled = !authorityInput.checked;
      if (authorityInput.checked && !mappingInput.value && defaultMap[key]) {
        mappingInput.value = Array.isArray(defaultMap[key]) ? defaultMap[key].join("｜") : String(defaultMap[key]);
      }
      refreshLocalReadiness();
    });
    mappingInput.addEventListener("input", refreshLocalReadiness);
  });
  const fieldList = document.createElement("datalist");
  fieldList.id = `policy-discovered-fields-${itemToken}`;
  // 假就绪修复（CODEX 审计）：字段候选只保留**最近一次**脱敏报告的集合
  // （原先跨报告累加，旧报告字段会一直被视为有效）；同时记录最近一次
  // 证据的外部稳定键，外部键变更后必须重新抓取证据。
  const setDiscoveredFields = (fieldNames, autoFill = false) => {
    discoveredFields = new Set(
      (fieldNames || []).map((value) => ewoPolicyString(value)).filter(Boolean),
    );
    fieldList.textContent = "";
    discoveredFields.forEach((fieldName) => {
      fieldList.appendChild(overviewEl("option", null, fieldName));
    });
    if (autoFill && fieldNames && fieldNames.length > 0) {
      const derived = wizardDeriveMappingFromFieldReport(capabilities, { fields: fieldNames });
      if (derived) {
        EWO_POLICY_AUTOMATIC_FIELDS.forEach(([k]) => {
          const mInput = authorityGroup.querySelector(`[data-mapping-field="${k}"]`);
          const aInput = authorityGroup.querySelector(`[data-authority-field="${k}"]`);
          if (mInput && (!mInput.value || (defaultMap[k] && mInput.value === (Array.isArray(defaultMap[k]) ? defaultMap[k].join("｜") : defaultMap[k])))) {
            const val = derived[k];
            if (val) {
              mInput.value = Array.isArray(val) ? val.join("｜") : String(val);
              if (aInput) {
                aInput.checked = true;
                mInput.disabled = false;
              }
            }
          }
        });
      }
    }
  };
  setDiscoveredFields(ewoPolicyDiscoveryFields(discoveryData));
  const latestObservation = Array.isArray(discoveryData.observations) && discoveryData.observations.length
    ? discoveryData.observations[0]
    : null;
  let lastEvidenceExternalKey = ewoPolicyString(latestObservation && latestObservation.externalKey);
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
      // reportType/aggregate 必须跟随交付物能力配置；聚合绑定不要求单记录 externalKey。
      matchRule: { reportType: capabilities.reportType || "ewo" },
      mapping: {},
      fieldAuthority: {},
    };
    payload.matchRule.aggregate = capabilities.aggregate === true;
    if (ewoBindingMode && ewoBindingMode.value === "legacy" && typeof storedEwoRule.aggregate === "boolean") {
      payload.matchRule.aggregate = storedEwoRule.aggregate;
    }
    if (ewoBindingMode && ewoBindingMode.value !== "legacy") {
      ["ewoNo", "projectCode", "subjectKeyword", "changeType", "changeSubType", "area", "state", "rspDepartment", "rspSmt", "submitStart", "submitEnd", "modelInfo"].forEach((key) => {
        if (typeof storedEwoRule[key] === "string" && storedEwoRule[key].trim()) payload.matchRule[key] = storedEwoRule[key];
      });
      payload.bindingContractVersion = "2";
      payload.matchRule.contractVersion = "2";
      payload.matchRule.bindingMode = ewoBindingMode.value;
      payload.matchRule.aggregate = ewoBindingMode.value === "record_set";
      if (payload.matchRule.aggregate) payload.externalKey = null;
      else {
        payload.externalKey = (payload.externalKey || "").toUpperCase();
        payload.matchRule.sourceItemId = payload.externalKey;
      }
    }
    const isTdcMatch = capabilities.reportType === "sor" || capabilities.reportType === "data_model" || capabilities.sourceType === "tdc";
    matchInputs.forEach((input, key) => {
      let value = ewoPolicyString(input.value);
      if (value && isTdcMatch && (key === "department" || key === "superDepartment")) {
        value = normalizeTdcDepartment(value);
      }
      if (value) payload.matchRule[key] = value;
      else delete payload.matchRule[key];
    });
    if (!payload.externalKey && !payload.matchRule.aggregate) {
      if (payload.matchRule.ewoNo) payload.externalKey = payload.matchRule.ewoNo;
    }
    EWO_POLICY_AUTOMATIC_FIELDS.forEach(([key]) => {
      const authorityInput = authorityGroup.querySelector(`[data-authority-field="${key}"]`);
      const mappingInput = authorityGroup.querySelector(`[data-mapping-field="${key}"]`);
      const automatic = Boolean(authorityInput && authorityInput.checked);
      payload.fieldAuthority[key] = automatic ? "automatic" : "manual";
      if (automatic && mappingInput) {
        let sourceField = ewoPolicyString(mappingInput.value);
        if (!sourceField && defaultMap[key]) {
          sourceField = Array.isArray(defaultMap[key]) ? defaultMap[key].join("｜") : String(defaultMap[key]);
        }
        if (sourceField) {
          if (key === "note" && (sourceField.includes("｜") || sourceField.includes("|") || sourceField.includes(","))) {
            payload.mapping[key] = sourceField.split(/[｜|,]/).map((s) => s.trim()).filter(Boolean);
          } else if (key === "note" && Array.isArray(defaultMap[key]) && (sourceField === defaultMap[key].join("｜") || sourceField === defaultMap[key].join(" | ") || sourceField === defaultMap[key].join("|"))) {
            payload.mapping[key] = defaultMap[key];
          } else {
            payload.mapping[key] = sourceField;
          }
        }
      }
    });
    if (credentialInput.value === "domain") payload.credentialRef = "domain";
    if (credentialInput.value === "__clear__") payload.credentialRef = null;
    payload.intervalMinutes = parseInt(intervalInput.value, 10) || 15;
    return payload;
  };

  function refreshEwoBindingMode(migrating = false) {
    if (!ewoBindingMode) return;
    const mode = ewoBindingMode.value;
    const setMode = mode === "record_set";
    externalKeyLabel.hidden = setMode || (mode === "legacy" && storedEwoRule.aggregate === true);
    externalKeyLabel.querySelector("span").textContent = mode === "single_record" ? "固定版本记录 ID" : "关联目标单号";
    externalKeyInput.placeholder = mode === "single_record" ? "32位内部记录ID；不自动跟随修订" : "选填，输入需跟踪的目标单号（留空自动关联）";
    ["owner", "plannedDate"].forEach((key) => {
      const input = authorityGroup.querySelector(`[data-authority-field="${key}"]`);
      const mapping = authorityGroup.querySelector(`[data-mapping-field="${key}"]`);
      if (input) {
        if (setMode) input.checked = false;
        input.disabled = setMode;
        if (mapping) mapping.disabled = setMode || !input.checked;
      }
    });
    if (setMode) {
      const noteInput = authorityGroup.querySelector('[data-authority-field="note"]');
      const noteMapping = authorityGroup.querySelector('[data-mapping-field="note"]');
      if (noteInput && !noteInput.checked) {
        noteInput.checked = true;
      }
      if (noteMapping && !noteMapping.value.trim() && defaultMap.note) {
        noteMapping.value = Array.isArray(defaultMap.note) ? defaultMap.note.join(" | ") : String(defaultMap.note);
      }
      if (noteMapping && noteInput) {
        noteMapping.disabled = !noteInput.checked;
      }
    }
    if (migrating) enabledInput.checked = false;
  }
  if (ewoBindingMode) {
    refreshEwoBindingMode();
    ewoBindingMode.addEventListener("change", () => {
      refreshEwoBindingMode(true);
      refreshLocalReadiness();
    });
  }

  function refreshLocalReadiness() {
    const payload = buildPolicyPayload();
    const missing = [];
    if (!EWO_POLICY_MODE_LABELS[payload.mode] || !["automatic", "hybrid"].includes(payload.mode)) {
      missing.push("请选择自动同步或混合模式");
    }
    const credentialReady = currentPolicy.credentialAvailable === true
      || (payload.credentialRef === "domain" && vaultConfigured);
    if (!credentialReady) missing.push(vaultConfigured ? "尚未绑定统一域账号凭据" : "凭据保护库未配置");
    const aggregateMode = payload.matchRule.aggregate === true;
    if (!aggregateMode && !payload.externalKey) missing.push("目标单号未确认（可填写EWO单号或抓取证据自动识别）");
    if (payload.enabled && !aggregateMode && !lastEvidenceExternalKey) {
      missing.push("请先抓取映射证据（连续两次一致）");
    }
    if (
      payload.enabled
      && !aggregateMode
      && lastEvidenceExternalKey
      && payload.externalKey !== lastEvidenceExternalKey
    ) {
      missing.push("外部稳定键与最近一次映射证据不一致，请点击“抓取映射证据”重新验证");
    }
    const matchKeys = Object.keys(payload.matchRule).filter((key) => !["reportType", "aggregate", "contractVersion", "bindingMode", "sourceItemId"].includes(key));
    if (matchKeys.length === 0) missing.push("至少填写一个匹配条件");
    const automaticFields = Object.keys(payload.fieldAuthority)
      .filter((key) => payload.fieldAuthority[key] === "automatic");
    if (automaticFields.length === 0) missing.push("至少选择一个自动字段");
    if (automaticFields.some((key) => !payload.mapping[key])) missing.push("自动字段必须填写来源映射");
    const flatMappedFields = [];
    Object.values(payload.mapping).forEach((v) => {
      if (Array.isArray(v)) flatMappedFields.push(...v);
      else if (v) flatMappedFields.push(v);
    });
    const defaultVals = [];
    Object.values(defaultMap).forEach((v) => {
      if (Array.isArray(v)) defaultVals.push(...v);
      else if (v) defaultVals.push(v);
    });
    if (flatMappedFields.length > 0 && discoveredFields.size > 0 && flatMappedFields.some((fieldName) => !discoveredFields.has(fieldName) && !defaultVals.includes(fieldName))) {
      missing.push("来源映射必须来自最近的脱敏字段报告");
    }
    const stability = discoveryData.stability && Number(discoveryData.stability.confirmed);
    if (!Number.isFinite(stability) || stability < 2) {
      missing.push(`映射稳定性未就绪（${Number.isFinite(stability) ? `${Math.max(stability, 0)}/2` : "0/2"}）`);
    }
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
    if (Object.keys(filters).length === 0 && payload.externalKey) {
      const firstField = Array.isArray(matchFields[0]) ? matchFields[0] : null;
      if (firstField && firstField[2]) filters[firstField[2]] = payload.externalKey;
    }
    if (Object.keys(filters).length === 0 && !payload.externalKey) {
      discoveryStatus.textContent = "请先填写外部稳定键或至少一个匹配条件。";
      discoveryStatus.className = "policy-discovery-status is-error";
      return;
    }
    discoveryButton.disabled = true;
    discoveryStatus.className = "policy-discovery-status is-busy";
    discoveryStatus.textContent = "正在抓取脱敏映射证据...";
    try {
      const evidencePayload = {
        filters,
        selectedExternalKey: payload.externalKey || null,
        aggregate: payload.matchRule.aggregate === true,
      };
      if (payload.bindingContractVersion === "2") {
        evidencePayload.contractVersion = "2";
        evidencePayload.bindingMode = payload.matchRule.bindingMode;
        if (payload.matchRule.sourceItemId) evidencePayload.sourceItemId = payload.matchRule.sourceItemId;
        const ewoNames = { ewoNo: "ewo_no", projectCode: "project_code", subjectKeyword: "subject_keyword", changeType: "change_type", changeSubType: "change_sub_type", area: "area", state: "state", rspDepartment: "rsp_department", rspSmt: "rsp_smt", submitStart: "submit_start", submitEnd: "submit_end", modelInfo: "model_info" };
        Object.entries(ewoNames).forEach(([key, name]) => {
          if (payload.matchRule[key]) evidencePayload.filters[name] = payload.matchRule[key];
        });
      }
      evidenceInputs.forEach((input, name) => {
        if (name === "headers") {
          // 后端 _clean_string_mapping 只接受 dict：多行请求头文本须先解析。
          const parsed = parseHeaders(input.value || "");
          if (Object.keys(parsed).length > 0) evidencePayload.headers = parsed;
          return;
        }
        const value = ewoPolicyString(input.value);
        if (value) evidencePayload[name] = value;
      });
      const response = await fetch(`/api/project-status/deliverables/${encodeURIComponent(item.id)}/mapping-discovery`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(evidencePayload),
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
      // 只保留最近一次报告的字段集合；证据目标键随最新一次抓取更新；自动匹配填充未填映射。
      setDiscoveredFields(fields);
      lastEvidenceExternalKey = discoveredKey || lastEvidenceExternalKey;
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
        // 保存改变 mode/enabled → 重新获取权威数据；loadProjectOverview
        // 的 finally 会经 handleHashChange 重绘详情页（仅此一次），提示经
        // pendingPolicyStatusMessage 在新编辑器渲染完成后显示。
        pendingPolicyStatusMessage = "更新方式已保存";
        await loadProjectOverview();
        if (overviewLoadError) {
          pendingPolicyStatusMessage =
            "已保存，但概览数据刷新失败，请刷新页面查看最新状态";
        }
      } catch (err) {
        updatePolicyStatusMessage(status, redactSensitiveText(ewoPolicyErrorMessage(err)), true);
        save.disabled = false;
      }
    },
  );
  // A3：完整绑定表单整体迁入「高级设置」details 折叠区（默认收起）。
  // 表单内容、字段与保存逻辑保持不变（同一 form / submit 流程复用）。
  const advancedDetails = document.createElement("details");
  advancedDetails.className = "policy-advanced-settings";
  const advancedSummary = overviewEl("summary", "policy-advanced-summary");
  advancedSummary.append(
    overviewEl("span", "policy-advanced-title", "高级设置"),
    overviewEl("span", "policy-advanced-summary-hint", "完整绑定表单：更新模式、匹配规则、映射证据与字段映射"),
  );
  advancedDetails.append(advancedSummary, head, form);

  // A1：数据同步摘要卡置于面板顶部；开启向导、立即同步与折叠入口挂载其中。
  container.append(
    buildSyncSummaryCard(item, currentPolicy, capabilities, settingsData, advancedDetails),
    advancedDetails,
  );
  refreshLocalReadiness();
  if (pendingPolicyStatusMessage) {
    updatePolicyStatusMessage(status, pendingPolicyStatusMessage);
    pendingPolicyStatusMessage = null;
  }
}

function renderSnapshotSyncCard(container, item, capabilities, options = {}) {
  const jobKey = (capabilities && capabilities.archiveJobKey)
    || (item.associations && item.associations.find((a) => a.type === "archive_job") && item.associations.find((a) => a.type === "archive_job").jobKey)
    || "";
  const jobAssoc = item.associations && Array.isArray(item.associations)
    ? item.associations.find((a) => a.type === "archive_job")
    : null;
  const jobName = (jobAssoc && jobAssoc.name) || jobKey || "外部归档任务";
  const lastSuccess = jobAssoc && jobAssoc.lastSuccessAt ? safeDisplayValue(jobAssoc.lastSuccessAt) : null;

  const card = overviewEl("section", "policy-sync-summary policy-snapshot-sync-card");
  card.setAttribute("aria-label", `${item.name} 数据同步（外部快照）`);

  const head = overviewEl("div", "policy-sync-summary-head");
  head.append(
    overviewEl("strong", "policy-sync-summary-title", "数据同步（外部快照）"),
    overviewEl("span", "policy-sync-summary-state", "快照驱动"),
  );
  card.appendChild(head);

  const descText = lastSuccess
    ? `该交付物由后台归档任务「${jobName}」的表单快照自动映射驱动。最近同步成功：${lastSuccess}。`
    : `该交付物由后台归档任务「${jobName}」的表单快照自动映射驱动。`;
  card.appendChild(overviewEl("p", "policy-sync-summary-hint", descText));

  const isEnabled = Boolean(jobAssoc && jobAssoc.enabled);
  const factList = [
    ["数据来源", jobName],
    ["驱动模式", "定时表单快照自动映射"],
    ["任务状态", isEnabled ? "已启用" : "未启用（支持直接立即同步）"],
    ["最近成功", lastSuccess || "尚未执行过快照同步"],
  ];
  const facts = overviewEl("ul", "policy-sync-summary-facts");
  factList.forEach(([label, value]) => {
    const row = overviewEl("li", "policy-sync-summary-fact");
    row.append(
      overviewEl("span", "policy-sync-fact-label", label),
      overviewEl("span", "policy-sync-fact-value", value),
    );
    facts.appendChild(row);
  });
  card.appendChild(facts);

  const actions = overviewEl("div", "policy-sync-summary-actions");
  const snapshotSyncBtn = overviewEl("button", "policy-sync-now-btn", "立即同步快照");
  snapshotSyncBtn.type = "button";
  if (!jobKey) {
    snapshotSyncBtn.disabled = true;
    snapshotSyncBtn.title = "未关联到可同步的归档任务";
  }

  const jobLink = overviewEl("a", "policy-view-job-link", "查看同步任务");
  jobLink.href = jobKey ? `#archive-deliverable/${encodeURIComponent(jobKey)}` : "#scheduled-archive";

  const statusMsg = overviewEl("span", "policy-sync-status");
  statusMsg.setAttribute("role", "status");
  statusMsg.setAttribute("aria-live", "polite");

  snapshotSyncBtn.addEventListener("click", async () => {
    if (!jobKey) return;
    snapshotSyncBtn.disabled = true;
    snapshotSyncBtn.textContent = "正在同步快照...";
    statusMsg.textContent = "正在执行后台归档同步...";
    statusMsg.className = "policy-sync-status";
    try {
      const resp = await fetch(`/api/scheduled-archive/jobs/${encodeURIComponent(jobKey)}/sync-now`, {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      const body = await resp.json();
      if (!resp.ok || !body || body.ok !== true) {
        const errMsg = body && body.error && body.error.message ? body.error.message : "同步未完成";
        throw new Error(redactSensitiveText(errMsg));
      }
      const data = body.data || {};
      const firstRes = Array.isArray(data.results) && data.results[0] ? data.results[0] : null;
      if (data.exitCode !== 0 || (firstRes && firstRes.outcome !== "completed")) {
        const errMsg = (firstRes && (firstRes.errorMessage || firstRes.errorType))
          || (data.exitCode ? `同步未就绪（退出码 ${data.exitCode}）` : "同步未完成");
        throw new Error(redactSensitiveText(errMsg));
      }
      statusMsg.textContent = "快照同步完成，正在刷新数据...";
      statusMsg.className = "policy-sync-status is-success";
      await loadArchiveJobs(true);
      await loadProjectOverview();
      if (typeof options.onFormReload === "function") {
        await options.onFormReload();
      }
      statusMsg.textContent = "快照同步成功，已刷新最新明细与图表。";
    } catch (err) {
      statusMsg.textContent = `同步失败：${redactSensitiveText(err instanceof Error ? err.message : String(err))}`;
      statusMsg.className = "policy-sync-status is-error";
    } finally {
      snapshotSyncBtn.disabled = false;
      snapshotSyncBtn.textContent = "立即同步快照";
    }
  });

  actions.append(snapshotSyncBtn, jobLink, statusMsg);
  card.appendChild(actions);
  container.appendChild(card);
}

async function loadDeliverablePolicy(container, item, options = {}) {
  // 能力驱动分发：sourceInfo 由后端能力注册表下发，不再按 source 文案/
  // 硬编码 id 判断（CODEX 架构审计调整项）。
  const capabilities = item.sourceInfo && typeof item.sourceInfo === "object"
    ? item.sourceInfo
    : null;
  if (capabilities && capabilities.syncCapable) {
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
      renderSyncBindingEditor(container, item, body.data, {
        ...options,
        settings: settingsBody && settingsBody.ok === true ? settingsBody.data : null,
        discovery: discoveryBody && discoveryBody.ok === true ? discoveryBody.data : null,
      });
    } catch (err) {
      // 无绑定或读取失败时按未启用展示，并保留脱敏后的错误信息。
      renderSyncBindingEditor(container, item, null, options);
      container.appendChild(overviewEl(
        "p",
        "policy-request-status is-error",
        redactSensitiveText(ewoPolicyErrorMessage(err)),
      ));
    }
    return;
  }
  if (item.formSnapshotDriven === true) {
    renderSnapshotSyncCard(container, item, capabilities, options);
    return;
  }
  // 非 syncCapable 且非 formSnapshotDriven：解释性静态文案（无来源连接器或来源契约未验证）。
  container.append(
    overviewEl("strong", "policy-editor-title", "更新方式"),
    overviewEl("p", "policy-static-mode",
      capabilities && capabilities.syncNote
        ? capabilities.syncNote
        : "手动维护"),
  );
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
  const capabilities = item && item.sourceInfo && typeof item.sourceInfo === "object"
    ? item.sourceInfo
    : {};
  const syncMissing = [];
  const syncSupported = capabilities.syncCapable !== undefined
    ? Boolean(capabilities.syncCapable)
    : !["VPI-T2-D1", "VPI-T2-D4"].includes(item.id);
  const syncModeReady = ["automatic", "hybrid"].includes(policy.mode);
  const syncMatchRule = policy.matchRule
    && typeof policy.matchRule === "object"
    && !Array.isArray(policy.matchRule)
    ? policy.matchRule
    : {};
  const syncAggregate = syncMatchRule.aggregate === true;
  const syncExternalKeyReady = syncAggregate
    || (typeof policy.externalKey === "string" && Boolean(policy.externalKey.trim()));
  const syncMatchRuleReady = Boolean(syncMatchRule.reportType) && Object.keys(syncMatchRule).length >= 2;
  const syncMapping = policy.mapping && typeof policy.mapping === "object" ? policy.mapping : {};
  const defaultMap = (capabilities.defaultMapping && Object.keys(capabilities.defaultMapping).length > 0)
    ? capabilities.defaultMapping
    : (DELIVERABLE_DEFAULT_MAPPINGS[item.id] || {});
  const hasDefaultMapping = Boolean(defaultMap && Object.keys(defaultMap).length > 0);
  const syncAuthorities = policy.fieldAuthority && typeof policy.fieldAuthority === "object"
    ? Object.entries(policy.fieldAuthority)
      .filter(([, authority]) => authority === "automatic")
      .map(([field]) => field)
    : [];
  const syncFieldMappingReady = (syncAuthorities.length > 0
    && Object.keys(syncMapping).length === syncAuthorities.length
    && Object.keys(syncMapping).every((field) => syncAuthorities.includes(field)))
    || (Object.keys(syncMapping).length > 0 && hasDefaultMapping);
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
    if (!syncSupported) missing.push("该交付物不支持外部同步");
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
  const syncBtn = overviewEl("button", "evidence-sync-btn", "运行后台同步");
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
    if (!window.confirm(`确定要运行后台同步 ${item.name} 吗？`)) return;
    syncBtn.disabled = true;
    syncStatus.textContent = "正在运行后台同步...";
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
      // 同步可能发布新的分析/表单快照，刷新概览数据避免环图停留在旧快照。
      await loadProjectOverview();
    } catch (err) {
      syncStatus.textContent = `同步失败：${redactSensitiveText(err instanceof Error ? err.message : String(err))}`;
      syncStatus.className = "evidence-sync-status is-error";
      syncBtn.disabled = !syncSupported || !syncReady;
    }
  });

  if (syncSupported) {
    syncActionBar.appendChild(syncBtn);
  }
  syncActionBar.appendChild(syncStatus);
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

// 全局同一时刻只展开一个多选下拉，避免多个候选列表同时展开叠压图表内容。
let activeMultiSelectCloser = null;

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

  let optionItems = (options || []).map((option) => {
    if (Array.isArray(option)) return { value: String(option[0]), label: String(option[1]) };
    const value = String(option);
    return { value, label: String(labelFor(value) || value) };
  });
  let selected = [];
  let changeHandler = null;
  // 候选列表仅在用户主动聚焦时展开；程序化 setValues/clear 不改变展开状态。
  let optionsOpen = false;

  function renderTokens() {
    const currentInput = input.value;
    Array.from(tokens.children).forEach((child) => {
      if (child !== input) child.remove();
    });
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
      tokens.insertBefore(token, input);
    });
    if (input.parentNode !== tokens) tokens.appendChild(input);
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
    optionsBox.hidden = !optionsOpen || matches.length === 0;
  }

  function closeOptions() {
    optionsOpen = false;
    optionsBox.hidden = true;
    if (activeMultiSelectCloser === closeOptions) activeMultiSelectCloser = null;
  }

  function openOptions() {
    if (optionsOpen) return;
    if (activeMultiSelectCloser && activeMultiSelectCloser !== closeOptions) {
      activeMultiSelectCloser();
    }
    optionsOpen = true;
    activeMultiSelectCloser = closeOptions;
    renderOptions();
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

  function setValues(values, options = {}) {
    const preserveInput = options && options.preserveInput === true;
    const currentInput = preserveInput ? input.value : "";
    selected = [];
    (values || []).forEach((value) => {
      const normalized = normalizeValue(String(value || "").trim());
      if (normalized && !selected.includes(normalized)) selected.push(normalized);
    });
    input.value = currentInput;
    renderTokens();
    renderOptions();
  }

  function setOptions(nextOptions) {
    optionItems = (nextOptions || []).map((option) => {
      if (Array.isArray(option)) return { value: String(option[0]), label: String(option[1]) };
      const value = String(option);
      return { value, label: String(labelFor(value) || value) };
    });
    renderOptions();
  }

  function clear() {
    setValues([]);
  }

  input.addEventListener("focus", openOptions);
  input.addEventListener("input", () => {
    if (optionsOpen) renderOptions();
    else openOptions();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      addValue(input.value);
    } else if (event.key === "Escape" && optionsOpen) {
      closeOptions();
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
      closeOptions();
    }
  });

  renderTokens();
  return {
    el: root,
    getValues,
    setValues,
    setOptions,
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

  const capabilities = item && item.sourceInfo && typeof item.sourceInfo === "object"
    ? item.sourceInfo
    : {};
  const syncSupported = capabilities.syncCapable !== undefined
    ? Boolean(capabilities.syncCapable)
    : !["VPI-T2-D1", "VPI-T2-D4"].includes(item.id);
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

  const syncButton = overviewEl("button", "evidence-sync-btn analysis-sync-btn", "运行后台同步");
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

function renderDeliverableStatusChart(rawItem, actions = {}) {
  // 与概览环图同口径：快照换算含 tone 归零，避免快照状态配手工颜色；
  // 待同步类状态显示状态标签而非占位进度。
  const item = deliverableDisplayItem(rawItem);
  const formDisplay = deliverableFormDisplay(rawItem);
  const chartSyncDisplay = deliverableSyncDisplay(rawItem);
  const chartHasValue = SYNC_DISPLAY_VALUE_STATES.has(chartSyncDisplay.state);

  const chart = overviewEl("section", "deliverable-current-status-chart");
  chart.setAttribute("role", "region");
  chart.setAttribute("aria-label", `${safeDisplayValue(item.name)} 当前状态图表`);

  const head = overviewEl("div", "deliverable-current-status-head");
  head.append(
    overviewEl("h6", "section-sub-title", "当前状态图表"),
    overviewEl(
      "span",
      `status-text is-${chartHasValue ? deliverableTone(item) : "primary"}`,
      safeDisplayValue(deliverableStatusText(item, item)),
    ),
  );

  const numericProgress = Number(item.progress);
  const hasProgress = chartHasValue
    && item.progress !== null
    && item.progress !== undefined
    && Number.isFinite(numericProgress);
  const progress = hasProgress
    ? Math.min(Math.max(numericProgress, 0), 100)
    : (chartHasValue && item.status === "已完成" ? 100 : 0);
  const progressLabel = chartHasValue && (hasProgress || item.status === "已完成")
    ? `${progress}%`
    : (chartHasValue ? "未设置" : chartSyncDisplay.label);

  const progressBox = overviewEl("div", "deliverable-current-status-progress");
  const progressLabelRow = overviewEl("div", "deliverable-current-status-label");
  const progressLabelText = overviewEl("span", "deliverable-progress-title");
  if (!chartHasValue) {
    progressLabelText.textContent = chartSyncDisplay.label;
  } else if (formDisplay) {
    const datePart = formDisplay.snapshotAt ? String(formDisplay.snapshotAt).slice(0, 10) : "";
    progressLabelText.append(
      overviewEl("span", "deliverable-snapshot-tag", "快照进度"),
      overviewEl("span", "deliverable-snapshot-date", datePart ? `（${datePart}）` : ""),
    );
  } else {
    progressLabelText.textContent = "项目手工进度";
  }
  progressLabelRow.append(
    progressLabelText,
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
  if (!window.confirm(`确定要运行后台同步 ${item.name} 吗？`)) return;
  analysisSyncReadiness.setBusy(true);
  analysisSyncReadiness.setStatus("正在运行后台同步...", "busy");
  try {
    const data = await requestProjectStatusSync(item);
    const feedback = projectStatusSyncFeedback(data);
    const loaded = await loadDeliverableAnalysis(analysisPanel, item, statusChart, analysisOptions);
    if (loaded) analysisSyncReadiness.setStatus(feedback.text, feedback.tone);
    // 同步可能发布新的分析/表单快照，刷新概览环图数据。
    await loadProjectOverview();
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
    changeType: "change_type",
    changeSubType: "change_sub_type",
    area: "area",
    state: "state",
    rspDepartment: "rsp_department",
    rspSmt: "rsp_smt",
    submitStart: "submit_start",
    submitEnd: "submit_end",
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
  resultHost.hidden = false;
  const policy = typeof policyProvider === "function" ? policyProvider() : {};
  const spec = buildEwoInteractiveQuerySpec(policy, item);
  statusChart.setBusy(true);
  statusChart.setSyncStatus("正在执行交互式查询...", "busy");
  try {
    const data = await requestInteractiveArasQuery("ewo", spec.filters);
    renderInteractiveArasResult(resultHost, "ewo", data, spec.targetKey);
    const resultState = formatInteractiveArasResult(data, spec.targetKey, "ewo");
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

async function refreshEwoFormFromStatusChart(item, statusChart, formPanel, formState) {
  if (!statusChart) return;
  statusChart.setBusy(true);
  statusChart.setSyncStatus("正在刷新表单快照...", "busy");
  try {
    const loaded = await loadDeliverableFormView(
      formPanel,
      item,
      { state: formState, statusChart },
    );
    statusChart.setSyncStatus(
      loaded ? "刷新完成" : "刷新失败：表单快照读取失败",
      loaded ? "success" : "error",
    );
  } finally {
    statusChart.setBusy(false);
  }
}

const DELIVERABLE_FORM_TABS = {
  "VPI-T2-D3": [
    ["departmentStatus", "部门状态"],
    ["sectionStatus", "科室状态"],
    ["quantityTrend", "数量趋势"],
  ],
  aras_paa: [
    ["departmentStatus", "部门状态"],
    ["sectionStatus", "科室状态"],
    ["quantityTrend", "数量趋势"],
  ],
  aras_ncr_progress: [
    ["departmentStatus", "部门状态"],
    ["sectionStatus", "区域状态"],
    ["quantityTrend", "数量趋势"],
  ],
  aras_ncr_detail: [
    ["departmentCost", "部门成本"],
    ["sectionCost", "科室成本"],
  ],
  tdc_data_model: [
    ["departmentStatus", "项目状态"],
    ["sectionStatus", "部门状态"],
    ["quantityTrend", "数量趋势"],
  ],
  tdc_sor: [
    ["departmentStatus", "车型项目状态"],
    ["sectionStatus", "科室状态"],
    ["quantityTrend", "数量趋势"],
  ],
};

const FORM_FILTER_LABELS = {
  keyword: "关键词",
  status: "状态",
  department: "部门",
  section: "科室 / 区域",
  model: "车型 / 项目",
  stage: "阶段 / 节点",
  overdueState: "逾期状态",
  dateStart: "开始日期",
  dateEnd: "结束日期",
  relationEwo: "关联EWO",
};

// 按表单覆盖筛选标签：数模的 section=部门、model=发布属性、stage=项目/车型。
const DELIVERABLE_FORM_FILTER_LABELS = {
  tdc_data_model: {
    section: "部门",
    model: "发布属性",
    stage: "项目 / 车型",
    dateStart: "申请日期（起）",
    dateEnd: "申请日期（止）",
  },
  tdc_sor: {
    section: "科室",
    model: "类型",
    stage: "车型项目",
    dateStart: "申请日期（起）",
    dateEnd: "申请日期（止）",
  },
};

// 按表单覆盖图表标题与说明（页签文字见 DELIVERABLE_FORM_TABS）。
const DELIVERABLE_FORM_CHART_TITLES = {
  tdc_data_model: {
    departmentStatus: ["项目状态", "各项目 / 车型按期推进数与逾期风险数"],
    sectionStatus: ["部门状态", "点击一个部门可追加筛选"],
  },
  tdc_sor: {
    departmentStatus: ["车型项目状态", "各车型项目按期推进数与逾期风险数"],
    sectionStatus: ["科室状态", "点击一个科室可追加筛选"],
  },
};

function deliverableFormFilterLabel(formKey, key) {
  const override = DELIVERABLE_FORM_FILTER_LABELS[formKey];
  return (override && override[key]) || FORM_FILTER_LABELS[key] || key;
}

const FORM_FILTER_QUERY_KEYS = [
  "keyword",
  "status",
  "department",
  "section",
  "model",
  "stage",
  "dateStart",
  "dateEnd",
  "overdueState",
  "relationEwo",
];

function deliverableFormKey(item) {
  // form_key 一律来自后端下发字段：项目状态交付物走 formLink，
  // 工作台目录条目走 catalog links，归档任务走任务 payload formKey。
  if (!item || typeof item !== "object") return "";
  if (item.formLink && typeof item.formLink === "object" && item.formLink.formKey) {
    return String(item.formLink.formKey);
  }
  if (item.links && typeof item.links === "object" && item.links.formKey) {
    return String(item.links.formKey);
  }
  return String(item.formKey || "");
}

function createDeliverableFormState(formKey) {
  const tabs = DELIVERABLE_FORM_TABS[formKey] || [];
  return {
    activeTab: tabs.length ? tabs[0][0] : "",
    filterStateByTab: {},
    draftFilterStateByTab: {},
    displayedFilterStateByTab: {},
    pageByTab: {},
    requestSeq: 0,
    viewStatus: "idle",
    overdueThresholds: null,
    viewOwner: "",
  };
}

function cloneFormFilterState(filters) {
  const source = filters && typeof filters === "object" ? filters : {};
  const copy = {};
  Object.entries(source).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      const values = value.map((item) => String(item || "").trim()).filter(Boolean);
      if (values.length) copy[key] = values;
      return;
    }
    const clean = String(value === null || value === undefined ? "" : value).trim();
    if (clean) copy[key] = clean;
  });
  return copy;
}

function currentFormFilterState(state) {
  if (!state || !state.activeTab) return {};
  if (!state.filterStateByTab[state.activeTab]) state.filterStateByTab[state.activeTab] = {};
  return state.filterStateByTab[state.activeTab];
}

function currentFormDraftFilterState(state) {
  if (!state || !state.activeTab) return {};
  if (!state.draftFilterStateByTab) state.draftFilterStateByTab = {};
  if (!Object.prototype.hasOwnProperty.call(state.draftFilterStateByTab, state.activeTab)) {
    state.draftFilterStateByTab[state.activeTab] = cloneFormFilterState(currentFormFilterState(state));
  }
  return state.draftFilterStateByTab[state.activeTab];
}

function currentFormDisplayedFilterState(state) {
  if (!state || !state.activeTab) return {};
  if (!state.displayedFilterStateByTab) state.displayedFilterStateByTab = {};
  if (!Object.prototype.hasOwnProperty.call(state.displayedFilterStateByTab, state.activeTab)) {
    state.displayedFilterStateByTab[state.activeTab] = cloneFormFilterState(currentFormFilterState(state));
  }
  return state.displayedFilterStateByTab[state.activeTab];
}

function markFormFilterStateDisplayed(state, filters = currentFormFilterState(state)) {
  if (!state || !state.activeTab) return;
  if (!state.displayedFilterStateByTab) state.displayedFilterStateByTab = {};
  state.displayedFilterStateByTab[state.activeTab] = cloneFormFilterState(filters);
}

function formFilterStatesEqual(left, right) {
  const a = cloneFormFilterState(left);
  const b = cloneFormFilterState(right);
  const aKeys = Object.keys(a).sort();
  const bKeys = Object.keys(b).sort();
  if (aKeys.length !== bKeys.length || aKeys.some((key, index) => key !== bKeys[index])) return false;
  return aKeys.every((key) => {
    const aValue = Array.isArray(a[key]) ? a[key].map(String).sort() : String(a[key]);
    const bValue = Array.isArray(b[key]) ? b[key].map(String).sort() : String(b[key]);
    return Array.isArray(aValue) && Array.isArray(bValue)
      ? aValue.length === bValue.length && aValue.every((value, index) => value === bValue[index])
      : aValue === bValue;
  });
}

function clearCurrentFilters(state) {
  if (!state || !state.activeTab) return;
  state.filterStateByTab[state.activeTab] = {};
  if (!state.draftFilterStateByTab) state.draftFilterStateByTab = {};
  state.draftFilterStateByTab[state.activeTab] = {};
  state.pageByTab[state.activeTab] = 0;
}

const FORM_MULTI_FILTER_KEYS = new Set(["status", "department", "section", "model", "stage", "overdueState"]);

function appendFormFilter(state, key, value) {
  const clean = String(value === null || value === undefined ? "" : value).trim();
  if (!state || !state.activeTab || !key || !clean) return;
  const filters = cloneFormFilterState(currentFormFilterState(state));
  if (FORM_MULTI_FILTER_KEYS.has(key)) {
    const current = Array.isArray(filters[key]) ? filters[key].map(String) : (filters[key] ? [String(filters[key])] : []);
    const index = current.indexOf(clean);
    if (index >= 0) current.splice(index, 1);
    else current.push(clean);
    if (current.length) filters[key] = current;
    else delete filters[key];
  } else if (Object.prototype.hasOwnProperty.call(filters, key) && filters[key] === clean && key !== "dateStart" && key !== "dateEnd") {
    delete filters[key];
  } else {
    filters[key] = clean;
  }
  state.filterStateByTab[state.activeTab] = filters;
  if (!state.draftFilterStateByTab) state.draftFilterStateByTab = {};
  state.draftFilterStateByTab[state.activeTab] = cloneFormFilterState(filters);
  if (key !== "dateStart" && key !== "dateEnd") {
    state.pageByTab[state.activeTab] = 0;
  }
}

function buildDeliverableFormQuery(filters, includePaging = false, state = null) {
  const params = new URLSearchParams();
  const source = filters && typeof filters === "object" ? filters : {};
  FORM_FILTER_QUERY_KEYS.forEach((key) => {
    const value = source[key];
    if (Array.isArray(value)) {
      value.forEach((item) => {
        const clean = String(item || "").trim();
        if (clean) params.append(key, clean);
      });
      return;
    }
    const clean = String(value === null || value === undefined ? "" : value).trim();
    if (clean) params.set(key, clean);
  });
  if (state && state.overdueThresholds && typeof state.overdueThresholds === "object") {
    Object.entries(state.overdueThresholds).forEach(([key, value]) => {
      const numeric = Math.floor(Number(value));
      if (Number.isFinite(numeric) && numeric >= 0) params.set(key, String(numeric));
    });
  }
  params.set("trendLimit", "30");
  if (includePaging && state && state.activeTab) {
    const offset = Number(state.pageByTab[state.activeTab]) || 0;
    params.set("offset", String(Math.max(0, offset)));
    params.set("limit", "50");
  }
  return params;
}

function formViewErrorMessage(error) {
  const status = Number(error && error.status);
  if (status === 401 || status === 403) return "表单数据未认证，请先完成统一域账号登录。";
  if (status >= 500 || status === 0) return "表单数据服务暂不可用，请稍后重试。";
  return "表单数据读取失败，请稍后重试。";
}

function formViewOwnerKey(item, formKey) {
  const identity = item && (item.id || item.externalJobKey) ? (item.id || item.externalJobKey) : formKey;
  return `${String(formKey || "")}:${String(identity || "")}`;
}

function formViewRequestIsCurrent(container, state, sequence, owner) {
  return Boolean(
    container
    && container.isConnected !== false
    && state
    && sequence === state.requestSeq
    && container.dataset
    && container.dataset.formViewOwner === owner
    && state.viewOwner === owner,
  );
}

function formViewRemoveTransientStatus(container) {
  if (!container || typeof container.querySelectorAll !== "function") return;
  container.querySelectorAll(".form-view-loading, .form-view-load-error").forEach((node) => node.remove());
}

function formViewShowLoading(container) {
  if (!container) return;
  formViewRemoveTransientStatus(container);
  const hasRenderedForm = container.querySelector(
    ".form-analysis-head, .form-filter-bar, .form-row-table-section",
  );
  if (!hasRenderedForm) {
    Array.from(container.children || [])
      .filter((child) => child.classList && child.classList.contains("loading"))
      .forEach((child) => child.remove());
  }
  const loading = overviewEl("p", "form-view-loading loading", "正在读取表单快照与明细...");
  loading.setAttribute("role", "status");
  loading.setAttribute("aria-live", "polite");
  container.insertBefore(loading, container.firstChild || null);
}

function unlockFormChartInteraction(container) {
  // 页签切换失败后解除图表与明细表的交互守卫，避免筛选控件永久锁定。
  if (!container || typeof container.querySelectorAll !== "function") return;
  container.querySelectorAll(".form-chart-tabs, .form-row-table-section").forEach((node) => {
    setFormChartInteractionLocked(node, false);
  });
}

function formViewShowError(container, error, retryHandler) {
  if (!container) return;
  formViewRemoveTransientStatus(container);
  const box = overviewEl("div", "form-view-load-error");
  box.setAttribute("role", "alert");
  box.setAttribute("aria-live", "assertive");
  box.append(
    overviewEl("p", "error-msg", formViewErrorMessage(error)),
    overviewEl("p", "form-view-error-detail", "可点击“刷新表单数据”重试；当前内容仍是最近一次成功应用的筛选结果，未应用更改会保留在控件中。"),
  );
  const retry = overviewEl("button", "btn is-secondary", "刷新表单数据");
  retry.type = "button";
  retry.addEventListener("click", () => {
    if (typeof retryHandler === "function") retryHandler();
  });
  box.appendChild(retry);
  container.insertBefore(box, container.firstChild || null);
}

function formViewRefreshFilterBar(container, state) {
  if (!container || typeof container.querySelector !== "function") return;
  const filterBar = container.querySelector(".form-filter-bar");
  if (!filterBar || !filterBar.dataset || typeof filterBar.__refreshFormFilterBar !== "function") return;
  if (state && filterBar.dataset.formFilterTab !== state.activeTab) {
    // The active tab may be changing; leave the old tab's controls untouched
    // until the new result builds its own filter bar.
    return;
  }
  filterBar.__refreshFormFilterBar();
}

async function loadDeliverableFormView(container, item, options = {}) {
  const formKey = deliverableFormKey(item);
  if (!container || !formKey) return false;
  const state = options.state || createDeliverableFormState(formKey);
  const filters = cloneFormFilterState(currentFormFilterState(state));
  const sequence = ++state.requestSeq;
  const owner = formViewOwnerKey(item, formKey);
  state.viewOwner = owner;
  container.dataset.formViewOwner = owner;
  state.viewStatus = "loading";
  formViewShowLoading(container);
  formViewRefreshFilterBar(container, state);
  try {
    const query = buildDeliverableFormQuery(filters);
    const rowQuery = buildDeliverableFormQuery(filters, true, state);
    const [viewResponse, rowsResponse] = await Promise.all([
      fetch(`/api/deliverable-forms/${encodeURIComponent(formKey)}/view?${query.toString()}`, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      }),
      fetch(`/api/deliverable-forms/${encodeURIComponent(formKey)}/rows?${rowQuery.toString()}`, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      }),
    ]);
    const [viewBody, rowsBody] = await Promise.all([
      overviewReadJson(viewResponse),
      overviewReadJson(rowsResponse),
    ]);
    if (!viewResponse.ok || !viewBody || viewBody.ok !== true) {
      throw overviewRequestError(viewBody, viewResponse.status);
    }
    if (!rowsResponse.ok || !rowsBody || rowsBody.ok !== true) {
      throw overviewRequestError(rowsBody, rowsResponse.status);
    }
    if (!formViewRequestIsCurrent(container, state, sequence, owner)) return false;
    state.viewStatus = "success";
    formViewRemoveTransientStatus(container);
    const data = viewBody.data || {};
    const rowsData = rowsBody.data || { items: [], total: 0, offset: 0, limit: 50 };
    markFormFilterStateDisplayed(state, filters);
    if (options.statusChart && typeof options.statusChart.updateEwoSummary === "function") {
      options.statusChart.updateEwoSummary(data);
    }
    renderDeliverableFormAnalysis(container, item, data, rowsData, {
      ...options,
      state,
      onReload: () => loadDeliverableFormView(container, item, { ...options, state }),
    });
    return true;
  } catch (error) {
    if (!formViewRequestIsCurrent(container, state, sequence, owner)) return false;
    state.viewStatus = "error";
    formViewRefreshFilterBar(container, state);
    unlockFormChartInteraction(container);
    formViewShowError(container, error, () => loadDeliverableFormView(container, item, { ...options, state }));
    return false;
  }
}

function formOptionValues(data, key) {
  const options = data && data.filters && data.filters.options;
  const values = options && Array.isArray(options[key]) ? options[key] : [];
  return values.map((value) => String(value || "").trim()).filter(Boolean);
}

function renderFormFilterBar(data, state, onReload) {
  const formKey = String(data && data.formKey || "");
  const draftFilters = currentFormDraftFilterState(state);
  const root = overviewEl("section", "form-filter-bar");
  root.setAttribute("aria-label", "当前图表筛选");
  const titleRow = overviewEl("div", "form-filter-head");
  const scopeText = "仅作用于当前图表页签与表单明细；同一字段内多选为或，字段之间为且";
  const filterTitle = overviewEl("strong", "form-filter-title", "筛选条件");
  const scopeInfo = overviewEl("span", "form-filter-info", "ⓘ");
  scopeInfo.title = scopeText;
  scopeInfo.setAttribute("aria-label", scopeText);
  filterTitle.appendChild(scopeInfo);
  const draftStatus = overviewEl("span", "form-filter-draft-state");
  const updateDraftStatus = () => {
    const displayed = currentFormDisplayedFilterState(state);
    const applied = currentFormFilterState(state);
    const draft = currentFormDraftFilterState(state);
    const draftDirty = !formFilterStatesEqual(applied, draft);
    const requestedChanged = !formFilterStatesEqual(displayed, applied);
    const requestLoading = state.viewStatus === "loading";
    const requestFailed = state.viewStatus === "error";
    draftStatus.textContent = draftDirty
      ? "有未应用的筛选更改"
      : requestFailed
        ? (requestedChanged ? "应用失败，显示最近成功结果" : "刷新失败，显示最近成功结果")
        : requestLoading
          ? (requestedChanged ? "正在应用筛选..." : "正在刷新...")
          : requestedChanged
            ? "等待筛选结果..."
            : "已应用";
    draftStatus.classList.toggle("is-dirty", draftDirty || requestedChanged || requestLoading);
    draftStatus.classList.toggle("is-pending", (requestedChanged || requestLoading) && !requestFailed);
    draftStatus.classList.toggle("is-error", requestFailed);
  };
  updateDraftStatus();
  titleRow.append(
    filterTitle,
    draftStatus,
  );
  root.appendChild(titleRow);

  const controls = overviewEl("div", "form-filter-controls");
  const searchRow = overviewEl("div", "form-filter-row form-filter-row-search");
  const dimsRow = overviewEl("div", "form-filter-row form-filter-row-dims");
  const timeRow = overviewEl("div", "form-filter-row form-filter-row-time");
  const keyword = overviewEl("input", "form-filter-keyword");
  keyword.type = "search";
  keyword.placeholder = "编号、项目、零件、负责人";
  keyword.value = String(draftFilters.keyword || "");
  keyword.setAttribute("aria-label", "关键词");
  keyword.maxLength = 200;
  const updateDraftTextFilter = (key, value) => {
    const draft = currentFormDraftFilterState(state);
    const clean = String(value || "").trim();
    if (clean) draft[key] = clean;
    else delete draft[key];
  };
  keyword.addEventListener("input", () => {
    updateDraftTextFilter("keyword", keyword.value);
    updateDraftStatus();
  });
  searchRow.appendChild(keyword);

  const overdueStateLabels = {
    overdue: "逾期风险",
    on_time: "按期推进",
    unknown: "未判定",
    not_applicable: "已完成 / 不适用",
  };
  const multiSelects = {};
  const addMultiSelect = (key, values, labels) => {
    const labelText = deliverableFormFilterLabel(formKey, key);
    const label = overviewEl("label", "form-filter-field form-filter-field-wide");
    label.appendChild(overviewEl("span", "form-filter-label", labelText));
    const control = createSearchMultiSelect({
      ariaLabel: labelText,
      placeholder: "搜索或多选",
      options: values,
      labelFor: labels || ((value) => value),
    });
    const latestDraft = currentFormDraftFilterState(state);
    const initial = Array.isArray(latestDraft[key])
      ? latestDraft[key]
      : (latestDraft[key] ? [String(latestDraft[key])] : []);
    control.setValues(initial);
    control.setOnChange((values) => {
      const draft = currentFormDraftFilterState(state);
      if (values.length) draft[key] = values.slice();
      else delete draft[key];
      state.pageByTab[state.activeTab] = 0;
      updateDraftStatus();
    });
    label.appendChild(control.el);
    dimsRow.appendChild(label);
    multiSelects[key] = control;
  };

  addMultiSelect("status", formOptionValues(data, "status"));
  const departmentValues = formOptionValues(data, "department");
  if (departmentValues.length) addMultiSelect("department", departmentValues);
  addMultiSelect("section", formOptionValues(data, "section"));
  addMultiSelect("model", formOptionValues(data, "model"));
  addMultiSelect("stage", formOptionValues(data, "stage"));
  addMultiSelect("overdueState", formOptionValues(data, "overdueState"), (value) => overdueStateLabels[value] || value);

  const availableFields = data && data.filters && Array.isArray(data.filters.fields) ? data.filters.fields : [];
  let relationInput = null;
  if (availableFields.includes("relationEwo")) {
    relationInput = overviewEl("input", "form-filter-keyword");
    relationInput.type = "text";
    relationInput.placeholder = "按 EWO 号定位关联记录";
    relationInput.value = String(draftFilters.relationEwo || "");
    relationInput.maxLength = 200;
    relationInput.setAttribute("aria-label", "关联EWO");
    relationInput.addEventListener("input", () => {
      updateDraftTextFilter("relationEwo", relationInput.value);
      updateDraftStatus();
    });
    const relationLabel = overviewEl("label", "form-filter-field");
    relationLabel.append(overviewEl("span", "form-filter-label", deliverableFormFilterLabel(formKey, "relationEwo") || "关联EWO"), relationInput);
    searchRow.appendChild(relationLabel);
  }

  const dateStart = overviewEl("input", "form-filter-date");
  dateStart.type = "date";
  dateStart.value = String(draftFilters.dateStart || "");
  dateStart.setAttribute("aria-label", deliverableFormFilterLabel(formKey, "dateStart"));
  const dateEnd = overviewEl("input", "form-filter-date");
  dateEnd.type = "date";
  dateEnd.value = String(draftFilters.dateEnd || "");
  dateEnd.setAttribute("aria-label", deliverableFormFilterLabel(formKey, "dateEnd"));
  dateStart.addEventListener("input", () => {
    updateDraftTextFilter("dateStart", dateStart.value);
    updateDraftStatus();
  });
  dateEnd.addEventListener("input", () => {
    updateDraftTextFilter("dateEnd", dateEnd.value);
    updateDraftStatus();
  });
  const dateStartLabel = overviewEl("label", "form-filter-field");
  dateStartLabel.append(overviewEl("span", "form-filter-label", deliverableFormFilterLabel(formKey, "dateStart")), dateStart);
  const dateEndLabel = overviewEl("label", "form-filter-field");
  dateEndLabel.append(overviewEl("span", "form-filter-label", deliverableFormFilterLabel(formKey, "dateEnd")), dateEnd);
  timeRow.append(dateStartLabel, dateEndLabel);

  const actions = overviewEl("div", "form-filter-actions");
  const apply = overviewEl("button", "btn is-secondary", "应用筛选");
  apply.type = "button";
  const clear = overviewEl("button", "btn is-secondary", "清除筛选");
  clear.type = "button";
  apply.addEventListener("click", () => {
    const next = cloneFormFilterState(currentFormDraftFilterState(state));
    state.filterStateByTab[state.activeTab] = next;
    state.draftFilterStateByTab[state.activeTab] = cloneFormFilterState(next);
    state.pageByTab[state.activeTab] = 0;
    if (typeof onReload === "function") onReload();
  });
  clear.addEventListener("click", () => {
    clearCurrentFilters(state);
    if (typeof onReload === "function") onReload();
  });
  actions.append(apply, clear);
  searchRow.appendChild(actions);
  controls.append(searchRow, dimsRow, timeRow);
  root.appendChild(controls);

  const chips = overviewEl("div", "form-filter-chips chart-filter-state");
  const renderAppliedChips = () => {
    chips.textContent = "";
    const applied = currentFormDisplayedFilterState(state);
    const entries = Object.entries(applied);
    if (!entries.length) chips.appendChild(overviewEl("span", "form-filter-empty", "0 个筛选条件"));
    entries.forEach(([key, value]) => {
      const values = Array.isArray(value) ? value : [value];
      values.forEach((item) => {
        const display = key === "overdueState" ? (overdueStateLabels[item] || item) : item;
        const chip = overviewEl("span", "form-filter-chip");
        chip.appendChild(overviewEl("span", "form-filter-chip-label", `${deliverableFormFilterLabel(formKey, key)}：${safeDisplayValue(display)}`));
        const remove = overviewEl("button", "form-filter-chip-remove", "×");
        remove.type = "button";
        remove.setAttribute("aria-label", `删除筛选 ${deliverableFormFilterLabel(formKey, key)} ${safeDisplayValue(display)}`);
        remove.addEventListener("click", () => {
          const next = cloneFormFilterState(currentFormDisplayedFilterState(state));
          if (Array.isArray(next[key])) {
            const rest = next[key].filter((candidate) => String(candidate) !== String(item));
            if (rest.length) next[key] = rest;
            else delete next[key];
          } else {
            delete next[key];
          }
          state.filterStateByTab[state.activeTab] = next;
          state.draftFilterStateByTab[state.activeTab] = cloneFormFilterState(next);
          state.pageByTab[state.activeTab] = 0;
          if (typeof onReload === "function") onReload();
        });
        chip.appendChild(remove);
        chips.appendChild(chip);
      });
    });
  };
  renderAppliedChips();
  root.appendChild(chips);
  root.dataset.formFilterTab = state.activeTab;
  root.__refreshFormFilterBar = (nextData = data) => {
    const nextDraft = currentFormDraftFilterState(state);
    const nextOptionsData = nextData && typeof nextData === "object" ? nextData : data;
    const nextDepartmentValues = formOptionValues(nextOptionsData, "department");
    if (!multiSelects.department && nextDepartmentValues.length) {
      addMultiSelect("department", nextDepartmentValues);
    }
    Object.entries(multiSelects).forEach(([key, control]) => {
      control.setOptions(formOptionValues(nextOptionsData, key));
      const nextValues = Array.isArray(nextDraft[key])
        ? nextDraft[key]
        : (nextDraft[key] ? [String(nextDraft[key])] : []);
      const currentValues = control.getValues();
      if (nextValues.length !== currentValues.length || nextValues.some((value) => !currentValues.includes(value))) {
        control.setValues(nextValues, { preserveInput: true });
      }
    });
    if (keyword.value !== String(nextDraft.keyword || "") && document.activeElement !== keyword) {
      keyword.value = String(nextDraft.keyword || "");
    }
    if (relationInput && relationInput.value !== String(nextDraft.relationEwo || "") && document.activeElement !== relationInput) {
      relationInput.value = String(nextDraft.relationEwo || "");
    }
    if (dateStart.value !== String(nextDraft.dateStart || "") && document.activeElement !== dateStart) {
      dateStart.value = String(nextDraft.dateStart || "");
    }
    if (dateEnd.value !== String(nextDraft.dateEnd || "") && document.activeElement !== dateEnd) {
      dateEnd.value = String(nextDraft.dateEnd || "");
    }
    renderAppliedChips();
    updateDraftStatus();
  };
  return root;
}

function formStatusColorClass(type) {
  if (type === "overdue") return "form-status-overdue";
  if (type === "incomplete") return "form-status-incomplete";
  if (type === "total") return "form-status-total";
  return "form-status-on-time";
}

function renderFormStatusBars(entries, filterKey, state, onReload, title, description) {
  const section = overviewEl("section", "form-chart-panel-content");
  section.append(
    overviewEl("h5", "form-chart-title", title),
    overviewEl("p", "form-chart-description", description),
  );
  const legend = overviewEl("div", "form-chart-legend");
  legend.append(
    overviewEl("span", "form-chart-legend-item form-status-on-time", "按期推进 / 正常"),
    overviewEl("span", "form-chart-legend-item form-status-overdue", "逾期风险"),
    overviewEl("span", "form-chart-legend-item form-status-incomplete", "未判定 / 当前节点"),
  );
  section.appendChild(legend);
  const box = overviewEl("div", "form-status-bars");
  const safeEntries = Array.isArray(entries) ? entries : [];
  const max = Math.max(1, ...safeEntries.map((entry) => Number(entry.onTime || 0) + Number(entry.overdue || 0) + Number(entry.unknown || 0)));
  safeEntries.forEach((entry) => {
    const label = String(entry && entry.label || "未命名");
    const onTime = Math.max(0, Number(entry && entry.onTime) || 0);
    const overdue = Math.max(0, Number(entry && entry.overdue) || 0);
    const unknown = Math.max(0, Number(entry && entry.unknown) || 0);
    const total = onTime + overdue + unknown;
    const row = overviewEl("div", "form-status-bar-row");
    row.setAttribute("role", "button");
    row.setAttribute("tabindex", "0");
    row.setAttribute("aria-label", `${label}：按期 ${onTime}，逾期 ${overdue}，未知 ${unknown}`);
    const name = overviewEl("span", "form-status-bar-label", safeDisplayValue(label));
    const track = overviewEl("span", "form-status-bar-track");
    const onTimeBar = overviewEl("span", `form-status-bar-fill ${formStatusColorClass("onTime")}`);
    onTimeBar.style.width = `${(onTime / max) * 100}%`;
    const overdueBar = overviewEl("span", `form-status-bar-fill ${formStatusColorClass("overdue")}`);
    overdueBar.style.width = `${(overdue / max) * 100}%`;
    const unknownBar = overviewEl("span", "form-status-bar-fill form-status-unknown");
    unknownBar.style.width = `${(unknown / max) * 100}%`;
    track.append(onTimeBar, overdueBar, unknownBar);
    const numbers = overviewEl("span", "form-status-bar-numbers", `按期 ${onTime} · 逾期 ${overdue} · 未判定 ${unknown} · 共 ${total}`);
    row.append(name, track, numbers);
    if (label === "其他状态") {
      row.removeAttribute("role");
      row.removeAttribute("tabindex");
      row.title = "其他状态（OPEN / CANCEL / 起草 / 挂起等）单独展示，不并入阶段筛选";
    } else {
      const activate = () => {
        appendFormFilter(state, filterKey, label);
        if (typeof onReload === "function") onReload();
      };
      row.addEventListener("click", activate);
      row.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          activate();
        }
      });
    }
    box.appendChild(row);
  });
  if (!safeEntries.length) box.appendChild(overviewEl("p", "form-chart-empty", "暂无可分析的表单数据"));
  section.appendChild(box);
  return section;
}

function renderFormTrendSvgChart(points, state, onReload) {
  const wrap = overviewEl("div", "form-trend-chart");
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "form-trend-svg");
  svg.setAttribute("viewBox", "0 0 760 300");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "总数、未完成数、逾期数数量趋势");
  const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
  title.textContent = "总数、未完成数、逾期数数量趋势";
  svg.appendChild(title);
  const safePoints = Array.isArray(points) ? points : [];
  const padding = { top: 30, right: 35, bottom: 48, left: 46 };
  const width = 760 - padding.left - padding.right;
  const height = 300 - padding.top - padding.bottom;
  const maxValue = Math.max(1, ...safePoints.flatMap((point) => [Number(point.total) || 0, Number(point.incomplete) || 0, Number(point.overdue) || 0]));
  for (let index = 0; index <= 4; index += 1) {
    const y = padding.top + height - (index / 4) * height;
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", String(padding.left));
    line.setAttribute("x2", String(padding.left + width));
    line.setAttribute("y1", String(y));
    line.setAttribute("y2", String(y));
    line.setAttribute("class", "form-trend-gridline");
    svg.appendChild(line);
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", String(padding.left - 8));
    label.setAttribute("y", String(y + 4));
    label.setAttribute("text-anchor", "end");
    label.setAttribute("class", "form-trend-axis-label");
    label.textContent = String(Math.round((maxValue / 4) * index));
    svg.appendChild(label);
  }
  const series = [
    ["total", "总数", "form-trend-total"],
    ["incomplete", "未完成数", "form-trend-incomplete"],
    ["overdue", "逾期数", "form-trend-overdue"],
  ];
  const coordinate = (index, value) => ({
    x: padding.left + (safePoints.length <= 1 ? width / 2 : (index / (safePoints.length - 1)) * width),
    y: padding.top + height - ((Number(value) || 0) / maxValue) * height,
  });
  series.forEach(([key, labelText, className]) => {
    const coords = safePoints.map((point, index) => ({ ...coordinate(index, point[key]), day: point.day, value: Number(point[key]) || 0 }));
    const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    polyline.setAttribute("points", coords.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" "));
    polyline.setAttribute("class", `form-trend-line ${className}`);
    svg.appendChild(polyline);
    coords.forEach((point) => {
      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("cx", String(point.x.toFixed(1)));
      circle.setAttribute("cy", String(point.y.toFixed(1)));
      circle.setAttribute("r", "5");
      circle.setAttribute("class", `form-trend-point ${className}`);
      circle.setAttribute("tabindex", "0");
      circle.setAttribute("role", "button");
      circle.setAttribute("aria-label", `${point.day} ${labelText} ${point.value}`);
      const activate = () => {
        appendFormFilter(state, "dateStart", point.day);
        appendFormFilter(state, "dateEnd", point.day);
        if (typeof onReload === "function") onReload();
      };
      circle.addEventListener("click", activate);
      circle.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          activate();
        }
      });
      svg.appendChild(circle);
    });
  });
  safePoints.forEach((point, index) => {
    const position = coordinate(index, 0);
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", String(position.x));
    label.setAttribute("y", String(padding.top + height + 24));
    label.setAttribute("text-anchor", "middle");
    label.setAttribute("class", "form-trend-axis-label");
    label.textContent = String(point.day || point.snapshotAt || "").slice(5, 10);
    svg.appendChild(label);
  });
  wrap.appendChild(svg);
  const legend = overviewEl("div", "form-chart-legend");
  [["form-trend-total", "总数"], ["form-trend-incomplete", "未完成数"], ["form-trend-overdue", "逾期数"]].forEach(([className, label]) => {
    legend.appendChild(overviewEl("span", `form-chart-legend-item ${className}`, label));
  });
  wrap.appendChild(legend);
  wrap.appendChild(overviewEl("p", "form-trend-note", "趋势横轴为后台快照自然日（同一天取最后一次快照）；点击节点追加的是该自然日的提交日期条件——提交日期与快照日期是不同概念。"));
  if (!safePoints.length) wrap.appendChild(overviewEl("p", "form-chart-empty", "暂无按天快照趋势"));
  return wrap;
}

function formCostText(value, unit) {
  if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) return "—";
  return `${Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 })} ${unit}`;
}

function formCostValueClass(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric === 0) return "";
  return numeric > 0 ? "form-cost-change-increase" : "form-cost-change-decrease";
}

function renderFormCostChart(entries, filterKey, state, onReload) {
  const section = overviewEl("section", "form-chart-panel-content");
  section.append(
    overviewEl("h5", "form-chart-title", filterKey === "department" ? "部门成本变化" : "科室 / 区域成本变化"),
    overviewEl("p", "form-chart-description", "按总和展示测算、批准、实际三组一次性投资成本与整车成本变化；正数红色，负数绿色。"),
  );
  const legend = overviewEl("div", "form-cost-legend", "一次性投资成本：万元 · 整车成本变化：元");
  section.appendChild(legend);
  const box = overviewEl("div", "form-cost-chart");
  const safeEntries = Array.isArray(entries) ? entries : [];
  safeEntries.forEach((entry) => {
    const row = overviewEl("div", "form-cost-row");
    row.setAttribute("role", "button");
    row.setAttribute("tabindex", "0");
    const label = String(entry && entry.label || "部门总计");
    row.appendChild(overviewEl("strong", "form-cost-label", safeDisplayValue(label)));
    const groups = overviewEl("div", "form-cost-groups");
    const investment = entry && entry.investment && typeof entry.investment === "object" ? entry.investment : {};
    const vehicleChange = entry && entry.vehicleChange && typeof entry.vehicleChange === "object" ? entry.vehicleChange : {};
    [["一次性投资成本", investment, "万元"], ["整车成本变化", vehicleChange, "元"]].forEach(([groupLabel, values, unit]) => {
      const group = overviewEl("div", "form-cost-group");
      group.appendChild(overviewEl("span", "form-cost-group-label", groupLabel));
      ["estimate", "approved", "actual"].forEach((name) => {
        const value = values[name];
        const valueNode = overviewEl("span", `form-cost-value ${groupLabel === "整车成本变化" ? formCostValueClass(value) : ""}`, `${name === "estimate" ? "测算" : name === "approved" ? "批准" : "实际"}：${formCostText(value, unit)}`);
        group.appendChild(valueNode);
      });
      groups.appendChild(group);
    });
    row.appendChild(groups);
    const activate = () => {
      appendFormFilter(state, filterKey, label === "部门总计" ? "" : label);
      if (typeof onReload === "function" && label !== "部门总计") onReload();
    };
    row.addEventListener("click", activate);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        activate();
      }
    });
    box.appendChild(row);
  });
  if (!safeEntries.length) box.appendChild(overviewEl("p", "form-chart-empty", "暂无成本快照数据"));
  section.appendChild(box);
  return section;
}

function buildFormOverdueControl(data, state, onReload) {
  const rules = data && data.schema && data.schema.overdueRules;
  if (!rules) return overviewEl("div");
  const wrap = overviewEl("div", "form-overdue-control");
  wrap.appendChild(overviewEl("span", "form-overdue-title", "逾期判定天数"));
  const applied = state.overdueThresholds || {};
  const inputs = {};
  [
    [rules.stageLabel, "overdueDaysStage", rules.stageDays],
    [rules.lateLabel, "overdueDaysLate", rules.lateDays],
  ].forEach(([labelText, key, defaultValue]) => {
    const field = overviewEl("label", "form-overdue-field");
    const input = document.createElement("input");
    input.type = "number";
    input.min = "0";
    input.max = "999";
    input.value = String(applied[key] !== undefined ? applied[key] : defaultValue);
    input.setAttribute("aria-label", `${labelText} 逾期判定天数`);
    inputs[key] = input;
    field.append(
      overviewEl("span", "form-overdue-label", labelText),
      input,
      overviewEl("span", "form-overdue-unit", "天"),
    );
    wrap.appendChild(field);
  });
  const apply = overviewEl("button", "btn is-secondary form-overdue-apply", "应用");
  apply.type = "button";
  apply.setAttribute("aria-label", "应用逾期判定天数");
  apply.addEventListener("click", () => {
    const next = {};
    Object.entries(inputs).forEach(([key, input]) => {
      const value = Math.floor(Number(input.value));
      if (Number.isFinite(value)) next[key] = Math.max(0, Math.min(999, value));
    });
    state.overdueThresholds = Object.keys(next).length ? next : null;
    if (typeof onReload === "function") onReload();
  });
  wrap.appendChild(apply);
  wrap.appendChild(overviewEl("span", "form-overdue-note", `${rules.note}；趋势图与历史快照保持存储口径——提交日期与快照日期是不同概念。`));
  return wrap;
}

// 切换页签的请求期间保留旧结果；锁住旧控件，避免它们把事件写入新页签状态。
function ensureFormChartInteractionGuard(root) {
  if (!root || root.__formInteractionGuardInstalled) return;
  const guard = (event) => {
    if (!root.dataset || root.dataset.formInteractionLocked !== "true") return;
    if (event && event.type === "keydown" && event.key === "Tab") return;
    const target = event && event.target;
    if (target && typeof target.closest === "function" && target.closest(".form-chart-tab")) return;
    if (event && typeof event.preventDefault === "function") event.preventDefault();
    if (event && typeof event.stopPropagation === "function") event.stopPropagation();
  };
  ["beforeinput", "change", "click", "compositionend", "compositionstart", "compositionupdate", "drop", "focus", "input", "keydown", "keyup", "mousedown", "paste", "pointerdown"].forEach((eventName) => {
    root.addEventListener(eventName, guard, true);
  });
  root.__formInteractionGuardInstalled = true;
}

function setFormChartInteractionLocked(root, locked) {
  if (!root || !root.dataset) return;
  root.dataset.formInteractionLocked = locked ? "true" : "false";
  const rowTable = root.parentNode && typeof root.parentNode.querySelector === "function"
    ? root.parentNode.querySelector(".form-row-table-section")
    : null;
  if (rowTable && rowTable !== root) {
    ensureFormChartInteractionGuard(rowTable);
    rowTable.dataset.formInteractionLocked = locked ? "true" : "false";
  }
}

function renderFormChartTabs(data, state, onReload, options = {}) {
  const formKey = String(data && data.formKey || "");
  const tabs = DELIVERABLE_FORM_TABS[formKey] || [];
  if (!tabs.some(([key]) => key === state.activeTab)) state.activeTab = tabs[0] ? tabs[0][0] : "";
  const existingChartTabs = options && options.existingChartTabs;
  const canReuseChartTabs = Boolean(
    existingChartTabs
    && existingChartTabs.isConnected !== false
    && existingChartTabs.classList
    && existingChartTabs.classList.contains("form-chart-tabs"),
  );
  const root = canReuseChartTabs ? existingChartTabs : overviewEl("section", "form-chart-tabs");
  ensureFormChartInteractionGuard(root);
  setFormChartInteractionLocked(root, false);
  root.setAttribute("aria-label", "表单分析图表页签");
  const tabList = canReuseChartTabs
    ? (root.querySelector(".form-chart-tab-list") || overviewEl("div", "form-chart-tab-list"))
    : overviewEl("div", "form-chart-tab-list");
  tabList.setAttribute("role", "tablist");
  tabList.textContent = "";
  tabs.forEach(([key, label]) => {
    const button = overviewEl("button", "form-chart-tab", label);
    button.type = "button";
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", key === state.activeTab ? "true" : "false");
    button.classList.toggle("is-active", key === state.activeTab);
    button.addEventListener("click", () => {
      if (state.activeTab === key) return;
      setFormChartInteractionLocked(root, true);
      state.activeTab = key;
      if (typeof onReload === "function") onReload();
    });
    tabList.appendChild(button);
  });
  if (tabList.parentNode !== root) root.insertBefore(tabList, root.firstChild || null);
  const chartPanel = canReuseChartTabs
    ? (root.querySelector(".form-chart-panel") || overviewEl("section", "form-chart-panel"))
    : overviewEl("section", "form-chart-panel");
  chartPanel.setAttribute("role", "tabpanel");
  chartPanel.setAttribute("aria-label", tabs.find(([key]) => key === state.activeTab)?.[1] || "表单图表");
  const existingFilterBar = options && options.existingFilterBar
    ? options.existingFilterBar
    : (canReuseChartTabs ? chartPanel.querySelector(".form-filter-bar") : null);
  const canReuseFilterBar = existingFilterBar
    && existingFilterBar.dataset
    && existingFilterBar.dataset.formFilterTab === state.activeTab
    && typeof existingFilterBar.__refreshFormFilterBar === "function"
    && existingFilterBar.parentNode === chartPanel;
  if (canReuseChartTabs) {
    Array.from(chartPanel.children).forEach((child) => {
      if (canReuseFilterBar && child === existingFilterBar) return;
      child.remove();
    });
  }
  const filter = canReuseFilterBar
    ? existingFilterBar
    : renderFormFilterBar(data, state, onReload);
  if (canReuseFilterBar) existingFilterBar.__refreshFormFilterBar(data);
  if (filter.parentNode !== chartPanel) chartPanel.insertBefore(filter, chartPanel.firstChild || null);
  if (state.activeTab === "departmentStatus" || state.activeTab === "sectionStatus") {
    const reportType = String(data && data.reportType || "");
    if (["ewo", "paa", "ncr_progress"].includes(reportType)) {
      chartPanel.appendChild(buildFormOverdueControl(data, state, onReload));
    }
  }
  const charts = data && data.charts && typeof data.charts === "object" ? data.charts : {};
  const chartTitles = DELIVERABLE_FORM_CHART_TITLES[formKey] || {};
  if (state.activeTab === "departmentStatus") {
    const department = charts.departmentStatus && Array.isArray(charts.departmentStatus.stages)
      ? charts.departmentStatus.stages
      : [];
    const [title, description] = chartTitles.departmentStatus
      || ["部门总状态", "各阶段 / 审批节点按期推进数与逾期风险数"];
    chartPanel.appendChild(renderFormStatusBars(department, "stage", state, onReload, title, description));
  } else if (state.activeTab === "sectionStatus") {
    const [title, description] = chartTitles.sectionStatus
      || [formKey === "aras_ncr_progress" ? "区域状态" : "科室状态", "点击一个科室或区域可追加筛选"];
    chartPanel.appendChild(renderFormStatusBars(charts.sectionStatus, "section", state, onReload, title, description));
  } else if (state.activeTab === "quantityTrend") {
    const content = overviewEl("section", "form-chart-panel-content");
    content.append(
      overviewEl("h5", "form-chart-title", "数量趋势"),
      overviewEl("p", "form-chart-description", "按自然日展示最近 30 天；同一天以当天最后一次后台快照为准。点击折线节点可筛选该日数据。"),
      renderFormTrendSvgChart(charts.quantityTrend || data.trend || [], state, onReload),
    );
    chartPanel.appendChild(content);
  } else if (state.activeTab === "departmentCost") {
    chartPanel.appendChild(renderFormCostChart(charts.departmentCost, "department", state, onReload));
  } else if (state.activeTab === "sectionCost") {
    chartPanel.appendChild(renderFormCostChart(charts.sectionCost, "section", state, onReload));
  }
  if (chartPanel.parentNode !== root) root.appendChild(chartPanel);
  return root;
}

function renderFormRowsTable(data, rowsData, state, onReload) {
  const section = overviewEl("section", "form-row-table-section");
  ensureFormChartInteractionGuard(section);
  setFormChartInteractionLocked(section, false);
  const head = overviewEl("div", "form-row-table-head");
  const total = Number(rowsData && rowsData.total) || 0;
  head.append(
    overviewEl("h5", "form-chart-title", "表单明细"),
    overviewEl("span", "form-row-count", `${total} 条匹配记录`),
  );
  section.appendChild(head);
  const wrap = overviewEl("div", "form-row-table-wrap");
  const table = document.createElement("table");
  table.className = "form-row-table";
  const columns = data && data.schema && Array.isArray(data.schema.columns) ? data.schema.columns : [];
  const defaultVisibleCount = data && data.schema ? Number(data.schema.defaultVisibleCount) || 12 : 12;
  const keyIndexes = data && data.schema && Array.isArray(data.schema.keyColumns)
    ? data.schema.keyColumns.map((index) => Number(index)).filter((index) => Number.isFinite(index) && index >= 0)
    : [];
  const visibleColumns = keyIndexes.length
    ? columns.filter((column) => keyIndexes.includes(Number(column && column.index)))
    : columns.slice(0, Math.min(columns.length, Math.max(8, defaultVisibleCount)));
  const thead = document.createElement("thead");
  const header = document.createElement("tr");
  ["工作表", "行号", ...visibleColumns.map((column, index) => column && column.label ? String(column.label) : `列 ${index + 1}`)].forEach((label) => header.appendChild(overviewEl("th", null, label)));
  thead.appendChild(header);
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  const items = rowsData && Array.isArray(rowsData.items) ? rowsData.items : [];
  items.forEach((item) => {
    const row = document.createElement("tr");
    const values = Array.isArray(item && item.values) ? item.values : [];
    [item && item.sheetName, item && item.rowNumber, ...visibleColumns.map((column) => values[Number(column && column.index) || 0])].forEach((value) => row.appendChild(overviewEl("td", null, safeDisplayValue(value))));
    const detailCell = document.createElement("td");
    detailCell.colSpan = 2 + visibleColumns.length;
    const detail = document.createElement("details");
    detail.className = "form-row-full-detail";
    const summary = document.createElement("summary");
    summary.textContent = "查看全部字段";
    detail.appendChild(summary);
    const grid = document.createElement("dl");
    grid.className = "form-row-field-grid";
    columns.forEach((column, index) => {
      const dt = overviewEl("dt", null, column && column.label ? String(column.label) : `列 ${index + 1}`);
      const dd = overviewEl("dd", null, safeDisplayValue(values[Number(column && column.index) || index]));
      grid.append(dt, dd);
    });
    detail.appendChild(grid);
    detailCell.appendChild(detail);
    const detailRow = document.createElement("tr");
    detailRow.className = "form-row-detail-row";
    detailRow.appendChild(detailCell);
    tbody.append(row, detailRow);
  });
  if (!items.length) {
    const row = document.createElement("tr");
    const cell = overviewEl("td", "form-chart-empty", total ? "当前筛选没有可见记录" : "暂无表单快照数据");
    cell.colSpan = 2 + visibleColumns.length;
    row.appendChild(cell);
    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  section.appendChild(wrap);

  const pager = overviewEl("div", "form-row-pager");
  const offset = Number(rowsData && rowsData.offset) || 0;
  const limit = Math.max(1, Number(rowsData && rowsData.limit) || 50);
  const pageLabel = `第 ${Math.floor(offset / limit) + 1} / ${Math.max(1, Math.ceil(total / limit))} 页`;
  const previous = overviewEl("button", "btn is-secondary", "上一页");
  previous.type = "button";
  previous.disabled = offset <= 0;
  const next = overviewEl("button", "btn is-secondary", "下一页");
  next.type = "button";
  next.disabled = offset + limit >= total;
  previous.addEventListener("click", () => {
    state.pageByTab[state.activeTab] = Math.max(0, offset - limit);
    if (typeof onReload === "function") onReload();
  });
  next.addEventListener("click", () => {
    state.pageByTab[state.activeTab] = offset + limit;
    if (typeof onReload === "function") onReload();
  });
  pager.append(previous, overviewEl("span", "form-row-page-label", pageLabel), next);
  section.appendChild(pager);
  return section;
}

function renderFormSnapshotActions(item, data, options = {}) {
  const actions = overviewEl("div", "form-snapshot-actions");
  const refresh = overviewEl("button", "btn is-secondary", "刷新表单数据");
  refresh.type = "button";
  refresh.addEventListener("click", () => {
    if (typeof options.onReload === "function") options.onReload();
  });
  actions.appendChild(refresh);
  const sync = data && data.sync && typeof data.sync === "object" ? data.sync : {};
  const stateText = String(sync.state || "idle");
  actions.appendChild(overviewEl("span", `form-snapshot-sync-state is-${stateText}`, `后台任务：${archiveSyncStateLabel(stateText)}`));
  if (item && item.isExternalArchive && item.externalJobKey) {
    const background = overviewEl("button", "btn is-primary", "运行后台归档同步");
    background.type = "button";
    background.disabled = sync.enabled !== true;
    background.title = sync.enabled === true ? "启动一次后台归档同步" : "该后台任务未启用，请到任务配置中启用";
    background.addEventListener("click", () => {
      if (typeof options.onBackgroundSync === "function") options.onBackgroundSync(background);
    });
    actions.appendChild(background);
  }
  return actions;
}

function renderDeliverableFormAnalysis(container, item, data, rowsData, options = {}) {
  const formKey = deliverableFormKey(item);
  const state = options.state || createDeliverableFormState(formKey);
  const existingChartTabs = container && container.querySelector
    ? container.querySelector(".form-chart-tabs")
    : null;
  const existingFilterBar = existingChartTabs && existingChartTabs.querySelector
    ? existingChartTabs.querySelector(".form-filter-bar")
    : null;
  const canReuseChartTabs = Boolean(
    existingChartTabs
    && existingFilterBar
    && existingFilterBar.dataset
    && existingFilterBar.dataset.formFilterTab === state.activeTab
    && typeof existingFilterBar.__refreshFormFilterBar === "function"
    && existingChartTabs.isConnected !== false,
  );
  if (canReuseChartTabs) {
    Array.from(container.children || []).forEach((child) => {
      if (child === existingChartTabs) return;
      clearOverviewContainer(child);
      child.remove();
    });
  } else {
    clearOverviewContainer(container);
  }
  const insertBeforeChartTabs = (node) => {
    if (canReuseChartTabs) container.insertBefore(node, existingChartTabs);
    else container.appendChild(node);
  };
  const snapshot = data && data.snapshot && typeof data.snapshot === "object" ? data.snapshot : null;
  const title = overviewEl("div", "form-analysis-head");
  const titleGroup = overviewEl("div");
  titleGroup.appendChild(overviewEl("p", "eyebrow", "统一表单分析"));
  title.append(
    titleGroup,
    overviewEl("h5", "form-analysis-title", `${safeDisplayValue(item && item.name)} 表单明细与分析`),
    overviewEl("span", "form-analysis-snapshot", snapshot ? `后台快照：${archiveFormatDate(snapshot.snapshotAt)}` : "暂无后台快照"),
  );
  insertBeforeChartTabs(title);
  insertBeforeChartTabs(renderFormSnapshotActions(item, data, options));

  const summary = data && data.summary && typeof data.summary === "object" ? data.summary : {};
  const metrics = overviewEl("div", "form-summary-grid");
  [["总数", summary.total], ["已完成", summary.completed], ["未完成", summary.incomplete], ["逾期", summary.overdue]].forEach(([label, value]) => {
    const card = overviewEl("div", "form-summary-card");
    const valueClass = label === "总数"
      ? "form-summary-value form-status-total"
      : label === "未完成"
        ? "form-summary-value form-status-incomplete"
        : label === "逾期"
          ? "form-summary-value form-status-overdue"
          : "form-summary-value form-status-on-time";
    card.append(overviewEl("span", "form-summary-label", label), overviewEl("strong", valueClass, String(Number(value) || 0)));
    metrics.appendChild(card);
  });
  insertBeforeChartTabs(metrics);

  if (formKey === "aras_ncr_detail") {
    insertBeforeChartTabs(overviewEl("p", "form-analysis-note", "NCR 明细不计算逾期；整车 / 发动机工作表来源保留在明细行中。"));
  } else {
    insertBeforeChartTabs(overviewEl("p", "form-analysis-note", "按期推进 / 正常为绿色，逾期风险为橙黄色；交互式查询不会覆盖后台快照。"));
  }
  const chartTabs = renderFormChartTabs(data, state, options.onReload, {
    existingChartTabs: canReuseChartTabs ? existingChartTabs : null,
    existingFilterBar: canReuseChartTabs ? existingFilterBar : null,
  });
  if (!canReuseChartTabs) container.appendChild(chartTabs);
  container.appendChild(renderFormRowsTable(data, rowsData, state, options.onReload));
  const statisticsSection = renderDeliverableStatisticsSection(item);
  if (statisticsSection) container.appendChild(statisticsSection);
}

// ── 交付物快照统计分析（确定性纯统计，无 AI）────────────────────────
// 任何有 formKey 的交付物可用：拉取 /statistics 端点，渲染指标卡、
// 状态分布条、停滞 Top5 表与离散度排名；Safe DOM（textContent/属性赋值）。

function statisticsNumberText(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  return String(Math.round(num * 10) / 10);
}

function statisticsDayText(value) {
  const num = Number(value);
  return Number.isFinite(num) ? `${Math.round(num)} 天` : "-";
}

function statisticsLocalDateText(value) {
  const text = String(value || "").trim();
  if (!text) return "-";
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return safeDisplayValue(text);
  return parsed.toLocaleDateString();
}

function statisticsDistributionBars(container, distribution, total) {
  const block = overviewEl("div", "statistics-status-distribution");
  block.appendChild(overviewEl("h6", "statistics-block-title", "状态分布"));
  const rows = Array.isArray(distribution) ? distribution : [];
  if (!rows.length) {
    block.appendChild(overviewEl("p", "statistics-empty", "暂无状态数据"));
    container.appendChild(block);
    return;
  }
  rows.forEach((entry) => {
    if (!entry || typeof entry !== "object") return;
    const count = Number(entry.count) || 0;
    const percent = total > 0 ? Math.round((count / total) * 100) : 0;
    const row = overviewEl("div", "statistics-status-row");
    const bar = overviewEl("span", "statistics-status-bar");
    const fill = overviewEl("span", "statistics-status-fill");
    fill.style.width = `${Math.min(100, Math.max(0, percent))}%`;
    bar.appendChild(fill);
    row.append(
      overviewEl("span", "statistics-status-label", safeDisplayValue(entry.status)),
      bar,
      overviewEl("span", "statistics-status-count", `${count}（${percent}%）`),
    );
    block.appendChild(row);
  });
  container.appendChild(block);
}

function statisticsTopTable(container, topRows, identityLabel) {
  const block = overviewEl("div", "statistics-top-block");
  block.appendChild(overviewEl("h6", "statistics-block-title", "停滞 Top5 记录"));
  const rows = Array.isArray(topRows) ? topRows : [];
  if (!rows.length) {
    block.appendChild(overviewEl("p", "statistics-empty", "无在途停滞记录"));
    container.appendChild(block);
    return;
  }
  const table = overviewEl("table", "statistics-top-table");
  const head = overviewEl("tr", null);
  [identityLabel || "单号", "当前步骤", "状态", "停滞天数"].forEach((label) => {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = label;
    head.appendChild(th);
  });
  const thead = document.createElement("thead");
  thead.appendChild(head);
  const tbody = overviewEl("tbody", null);
  rows.forEach((entry) => {
    if (!entry || typeof entry !== "object") return;
    const tr = overviewEl("tr", "statistics-top-row");
    [
      safeDisplayValue(entry.identity),
      safeDisplayValue(entry.stage),
      safeDisplayValue(entry.status),
      statisticsDayText(entry.stagnationDays),
    ].forEach((value) => {
      tr.appendChild(overviewEl("td", null, value));
    });
    tbody.appendChild(tr);
  });
  table.append(thead, tbody);
  block.appendChild(table);
  container.appendChild(block);
}

function statisticsDispersionList(container, dispersion) {
  const block = overviewEl("div", "statistics-dispersion-block");
  block.appendChild(overviewEl("h6", "statistics-block-title", "离散度排名（跨快照方差）"));
  const rows = Array.isArray(dispersion) ? dispersion : [];
  if (!rows.length) {
    block.appendChild(overviewEl("p", "statistics-empty", "历史快照不足，暂无离散度排名"));
    container.appendChild(block);
    return;
  }
  const list = overviewEl("ol", "statistics-dispersion-list");
  rows.forEach((entry) => {
    if (!entry || typeof entry !== "object") return;
    const item = overviewEl("li", "statistics-dispersion-item");
    item.append(
      overviewEl("span", "statistics-dispersion-identity", safeDisplayValue(entry.identity)),
      overviewEl(
        "span",
        "statistics-dispersion-meta",
        `步骤 ${safeDisplayValue(entry.stage)}；观测 ${safeDisplayValue(entry.observations)} 次快照；当前停滞 ${statisticsDayText(entry.latestStagnationDays)}；方差 ${statisticsNumberText(entry.variance)}`,
      ),
    );
    list.appendChild(item);
  });
  block.appendChild(list);
  container.appendChild(block);
}

function renderDeliverableStatisticsData(body, item, data) {
  body.textContent = "";
  if (!data || data.hasSnapshot !== true || !data.statistics) {
    body.appendChild(overviewEl("p", "statistics-empty-state", "暂无快照数据"));
    return;
  }
  const stats = data.statistics;
  const head = overviewEl("div", "statistics-head");
  head.appendChild(overviewEl(
    "span",
    "statistics-snapshot-at",
    `快照时间：${statisticsLocalDateText(data.snapshotAt || stats.snapshotAt)}`,
  ));
  body.appendChild(head);

  const stagnation = stats.stagnation && typeof stats.stagnation === "object"
    ? stats.stagnation
    : null;
  const metrics = overviewEl("div", "statistics-metric-grid");
  const metricCells = stagnation
    ? [
        ["平均停滞", `${statisticsNumberText(stagnation.mean)} 天`],
        ["中位数", `${statisticsNumberText(stagnation.median)} 天`],
        ["标准差", statisticsNumberText(stagnation.stdDev)],
        ["最长停滞", statisticsDayText(stagnation.max)],
      ]
    : [
        ["平均停滞", "-"],
        ["中位数", "-"],
        ["标准差", "-"],
        ["最长停滞", "-"],
      ];
  metricCells.forEach(([label, value]) => {
    const card = overviewEl("div", "statistics-metric-card");
    card.append(overviewEl("span", "statistics-metric-label", label), overviewEl("strong", "statistics-metric-value", value));
    metrics.appendChild(card);
  });
  body.appendChild(metrics);

  const inFlight = overviewEl("p", "statistics-inflight-note", stagnation
    ? `在途记录 ${safeDisplayValue(stats.inFlightCount)} 条；时间列缺失/非法剔除 ${safeDisplayValue(stats.invalidActivityDateCount)} 条`
    : "无在途停滞记录（或时间列不可用），仅展示状态分布");
  body.appendChild(inFlight);

  statisticsDistributionBars(body, stats.statusDistribution, Number(stats.totalRecords) || 0);
  statisticsTopTable(body, stats.stagnationTop, stats.layout && stats.layout.identityLabel);
  statisticsDispersionList(body, stats.dispersion);
}

async function loadDeliverableStatisticsData(section, body, item, retryHandler) {
  const formKey = deliverableFormKey(item);
  if (!formKey || !body) return;
  body.textContent = "";
  body.appendChild(overviewEl("p", "form-view-loading loading", "正在读取快照统计..."));
  try {
    const response = await fetch(`/api/deliverable-forms/${encodeURIComponent(formKey)}/statistics`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const result = await overviewReadJson(response);
    if (!response.ok || !result || result.ok !== true) {
      throw overviewRequestError(result, response.status);
    }
    body.textContent = "";
    renderDeliverableStatisticsData(body, item, result.data || {});
  } catch (error) {
    if (!section.isConnected) return;
    body.textContent = "";
    const box = overviewEl("div", "statistics-load-error");
    box.appendChild(overviewEl("p", "error-msg", "快照统计读取失败，请稍后重试。"));
    if (typeof retryHandler === "function") {
      const retry = overviewEl("button", "btn is-secondary", "重新读取");
      retry.type = "button";
      retry.addEventListener("click", () => retryHandler());
      box.appendChild(retry);
    }
    body.appendChild(box);
  }
}

function renderDeliverableStatisticsSection(item) {
  const formKey = deliverableFormKey(item);
  if (!formKey) return null;
  const section = overviewEl("details", "deliverable-statistics");
  section.setAttribute("aria-label", "交付物快照统计分析");
  const summary = overviewEl("summary", "deliverable-statistics-summary");
  summary.append(
    overviewEl("span", null, "统计分析"),
    overviewEl("span", "deliverable-statistics-hint", "快照记录的确定性统计（纯统计学，无 AI）"),
  );
  const body = overviewEl("div", "deliverable-statistics-body");
  const retry = () => loadDeliverableStatisticsData(section, body, item, retry);
  section.append(summary, body);
  section.addEventListener("toggle", () => {
    if (section.open && !body.dataset.loaded) {
      body.dataset.loaded = "true";
      loadDeliverableStatisticsData(section, body, item, retry);
    }
  });
  return section;
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
    const resultState = formatInteractiveArasResult(data, targetKey, "paa");
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

  // 详情页展示口径与概览环图一致：快照换算的状态/进度统一走
  // deliverableDisplayItem；手工字段（项目手工进度等）保留原始值。
  const displayItem = deliverableDisplayItem(item);
  const manualEditState = deliverableManualEditState(item);
  const syncDisplay = deliverableSyncDisplay(item);
  const hasDisplayValue = SYNC_DISPLAY_VALUE_STATES.has(syncDisplay.state);

  const page = overviewEl("article", "deliverable-detail-page");

  // 切换交付物详情时重置车型筛选，避免上一个交付物的查找条件残留；
  // 同一交付物的重绘（如保存同步绑定后）保留当前筛选（GPT 终审 P2）。
  if (analysisModelFilter.deliverableId !== item.id) {
    analysisModelFilter.model = "";
    analysisModelFilter.match = "fuzzy";
    analysisModelFilter.deliverableId = item.id;
  }

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
  headStatusGroup.appendChild(overviewEl(
    "span",
    `status-text is-${hasDisplayValue ? deliverableTone(displayItem) : "primary"}`,
    deliverableStatusText(item, displayItem),
  ));
  // 状态旁参考行：表单分析快照摘要（仅参考，不计入完成统计口径）。
  headStatusGroup.appendChild(overviewEl(
    "span",
    "deliverable-form-reference",
    deliverableFormReferenceText(item),
  ));
  const editButton = overviewEl("button", "detail-edit", null);
  editButton.type = "button";
  const editLabel = `编辑 ${item.name}`;
  editButton.disabled = !manualEditState.editable;
  editButton.title = manualEditState.editable ? editLabel : manualEditState.reason;
  editButton.setAttribute(
    "aria-label",
    manualEditState.editable ? editLabel : `不可编辑：${manualEditState.reason}`,
  );
  if (!manualEditState.editable) editButton.classList.add("is-readonly");
  editButton.appendChild(overviewPencilIcon());
  editButton.appendChild(overviewEl("span", null, manualEditState.editable ? " 编辑" : " 只读"));
  editButton.addEventListener("click", (event) => {
    event.stopPropagation();
    startDeliverableEdit(itemIndex, detailEditPanel);
  });
  headStatusGroup.appendChild(editButton);
  headTitleRow.appendChild(headStatusGroup);
  head.appendChild(headTitleRow);
  if (!manualEditState.editable) {
    head.appendChild(overviewEl(
      "p",
      "detail-readonly-notice",
      `手工字段只读：${redactSensitiveText(manualEditState.reason)}`,
    ));
  }
  const overdueSummary = deliverableSnapshotSummary(displayItem);
  if (displayItem.status === "已逾期" && overdueSummary && Number(overdueSummary.summary.overdue) > 0) {
    const riskBanner = overviewEl("div", "deliverable-overdue-risk-banner");
    const riskSpan = overviewEl("span", null);
    riskSpan.appendChild(document.createTextNode("⚠️ "));
    riskSpan.appendChild(overviewEl("strong", null, "过程工单超期预警"));
    riskSpan.appendChild(document.createTextNode("：快照总计 "));
    riskSpan.appendChild(overviewEl("strong", null, String(overdueSummary.summary.total ?? 0)));
    riskSpan.appendChild(document.createTextNode(
      ` 笔单据，已完成 ${overdueSummary.summary.completed ?? 0} 笔（推进进度 ${displayItem.progress ?? 0}%）；检测到 `
    ));
    riskSpan.appendChild(overviewEl("strong", null, String(overdueSummary.summary.overdue ?? 0)));
    riskSpan.appendChild(document.createTextNode(" 笔在途单据已过要求完成时间，建议优先协调催办。"));
    riskBanner.appendChild(riskSpan);
    head.appendChild(riskBanner);
  }
  page.appendChild(head);
  page.appendChild(detailEditPanel);

  // Lead with the current-status visualization and configuration details;
  // external cross-department analysis follows when a snapshot is available.
  const formKey = deliverableFormKey(item);
  const formState = formKey ? createDeliverableFormState(formKey) : null;
  const analysisPanel = overviewEl(
    "section",
    formState ? "deliverable-form-analysis" : "deliverable-analysis-panel",
  );
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
    onRefresh: () => formState
      ? loadDeliverableFormView(analysisPanel, item, { state: formState, statusChart })
      : refreshDeliverableAnalysisFromAnalysis(
        item,
        analysisSyncReadiness,
        analysisPanel,
        statusChart,
        analysisOptions,
      ),
  };
  statusChart = renderDeliverableStatusChart(item, {
    onInteractiveRefresh: () => {
      return runEwoInteractiveRefreshFromStatusChart(
        item,
        statusChart,
        interactiveQueryHost,
        () => ewoInteractivePolicy,
      );
    },
    onRefresh: () => formState
      ? refreshEwoFormFromStatusChart(item, statusChart, analysisPanel, formState)
      : refreshEwoAnalysisFromStatusChart(item, statusChart, analysisPanel, analysisOptions),
  });
  metaSection.appendChild(statusChart.el);
  metaSection.appendChild(interactiveQueryHost);
  if (/ewo/i.test(String(item.source || "")) && window.EWOEnrichment) {
    const enrichmentHost = overviewEl("section", "deliverable-form-analysis");
    enrichmentHost.appendChild(overviewEl("p", "section-hint", "使用下方已保存的EWO匹配条件准备增强报表。"));
    enrichmentHost.setAttribute("data-ewo-enrichment", "true");
    const enrichmentPanel = window.EWOEnrichment.mount({
      host: enrichmentHost,
      getFilters: () => {
        const spec = buildEwoInteractiveQuerySpec(ewoInteractivePolicy, item);
        if (!Object.keys(spec.filters).length) throw new Error("请先保存至少一项EWO匹配条件");
        return spec.filters;
      },
      request: async (path, payload) => {
        if ((path.endsWith("/jobs") || path.endsWith("/restore"))
          && ewoInteractivePolicy.matchRule?.contractVersion === "2"
          && ewoInteractivePolicy.matchRule.bindingMode === "single_record") {
          payload = { ...payload, sourceItemId: ewoInteractivePolicy.matchRule.sourceItemId };
        }
        const response = await fetch(path, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify(payload),
        });
        const body = await overviewReadJson(response);
        if (!response.ok || !body || body.ok !== true) throw overviewRequestError(body, response.status);
        return body.data;
      },
    });
    enrichmentHost.destroyEwoEnrichment = enrichmentPanel.destroy;
    metaSection.appendChild(enrichmentHost);
  }
  const grid = overviewEl("div", "detail-inline-grid");
  // 数据来源标注区分明细分析快照与表单快照；无生效快照时显示上游系统。
  const snapshotSummary = deliverableSnapshotSummary(item);
  const snapshotSourceLabel = snapshotSummary
    ? (snapshotSummary.kind === "analysis" ? "明细分析快照" : "表单快照")
    : null;
  const pairs = [
    ["当前状态", deliverableStatusText(item, displayItem)],
    ["所属科室", item.department || "未设置"],
    ["所属阶段", item.stage || (overviewSavedState.phase && (overviewSavedState.phase.displayName || overviewSavedState.phase.id)) || ""],
    ["计划完成日期", item.plannedDate],
    ["实际完成日期", item.actualDate || "未完成"],
    ["项目手工进度", `${Number(item.progress) || 0}%`],
    ["数据来源", snapshotSourceLabel || item.source || "未设置"],
    ["更新方式", deliverablePolicyModeLabel(item.updateMethod || (item.updatePolicy && item.updatePolicy.mode))],
    ["更新时间", item.updatedAt || (overviewSavedState.phase && overviewSavedState.phase.updatedAt)],
    ["风险与备注", item.note || "无"],
  ];
  pairs.forEach(([label, value]) => {
    const field = overviewEl("div", "detail-property");
    field.append(
      overviewEl("span", "detail-property-label", label),
      overviewEl("span", "detail-property-value", safeDisplayValue(value)),
    );
    if (label === "风险与备注") {
      const noteButton = overviewEl("button", "note-inline-edit", "✎ 编辑");
      noteButton.type = "button";
      noteButton.disabled = !manualEditState.editable;
      noteButton.title = manualEditState.editable ? "编辑风险与备注" : manualEditState.reason;
      noteButton.setAttribute(
        "aria-label",
        manualEditState.editable ? `编辑 ${item.name} 风险与备注` : `风险与备注只读：${manualEditState.reason}`,
      );
      if (!manualEditState.editable) noteButton.classList.add("is-readonly");
      noteButton.addEventListener("click", () => startInlineNoteEdit(field, item));
      field.querySelector(".detail-property-value").appendChild(noteButton);
    }
    grid.appendChild(field);
  });
  // 属性明细为低频参考信息，默认折叠收起。
  const detailCollapse = overviewEl("details", "detail-inline-collapse");
  const detailSummary = overviewEl("summary", "detail-inline-summary");
  detailSummary.append(
    overviewEl("span", null, "详细明细"),
    overviewEl("span", "detail-inline-summary-hint", "展开查看属性明细"),
  );
  detailCollapse.append(detailSummary, grid);
  metaSection.appendChild(detailCollapse);

  // 关联项：后端按单一关联注册表下发 associations（Safe DOM 渲染）。
  const association = overviewEl("div", "detail-association");
  association.append(overviewEl("span", "association-label", "关联项"));
  const associations = Array.isArray(item.associations) ? item.associations : [];
  if (!associations.length) {
    association.appendChild(overviewEl("p", "association-empty", "尚未配置关联模型"));
  } else {
    const associationList = overviewEl("ul", "association-list");
    associations.forEach((entry) => {
      if (!entry || typeof entry !== "object") return;
      const associationItem = overviewEl("li", "association-item");
      const typeLabel = entry.type === "archive_job" ? "同步任务" : "目录条目";
      const link = overviewEl(
        "a",
        `association-link is-${entry.type === "archive_job" ? "archive" : "catalog"}`,
        safeDisplayValue(entry.name),
      );
      const href = String(entry.href || "");
      if (href.startsWith("#")) link.setAttribute("href", href);
      link.setAttribute("aria-label", `${typeLabel}：${safeDisplayValue(entry.name)}`);
      associationItem.append(
        overviewEl("span", "association-type", typeLabel),
        link,
      );
      if (entry.type === "archive_job") {
        associationItem.appendChild(overviewEl(
          "span",
          "association-meta",
          entry.enabled ? "已启用" : "未启用",
        ));
      }
      associationList.appendChild(associationItem);
    });
    association.appendChild(associationList);
  }
  metaSection.appendChild(association);
  page.appendChild(metaSection);
  page.appendChild(analysisPanel);
  if (formState) {
    loadDeliverableFormView(analysisPanel, item, { state: formState, statusChart });
  } else {
    loadDeliverableAnalysis(analysisPanel, item, statusChart, analysisOptions);
  }

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
    onFormReload: () => {
      if (formState) {
        loadDeliverableFormView(analysisPanel, item, { state: formState, statusChart });
      }
    },
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
    tdc_data_model: ["数模设计审核流程报表", "TDC"],
    tdc_sor: ["SOR 定点流程", "TDC"],
  };
  const [name, source] = labels[job.jobKey] || [job.jobKey, "外部同步"];
  const page = overviewEl("article", "deliverable-detail-page");
  page.dataset.externalJobKey = job.jobKey;
  const formState = createDeliverableFormState(String(job.formKey || ""));
  const formPanel = overviewEl("section", "deliverable-form-analysis");
  formPanel.setAttribute("aria-label", `${name} 表单明细与分析`);
  const formItem = {
    name,
    externalJobKey: job.jobKey,
    isExternalArchive: true,
    // 表单键由任务 payload 下发（单一关联注册表派生）。
    formKey: String(job.formKey || ""),
  };
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
    syncButton.disabled = !job.enabled;
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
  historyPanel.appendChild(overviewEl("h5", "section-sub-title", "同步运行记录"));
  const historyBody = overviewEl("div", "external-detail-history-body");
  historyBody.appendChild(overviewEl("p", "loading", "正在加载同步历史..."));
  historyPanel.appendChild(historyBody);
  statusSection.appendChild(historyPanel);
  page.appendChild(statusSection);
  page.appendChild(formPanel);

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
  if (syncButton) {
    syncButton.addEventListener("click", () => {
      void runArchiveDetailBackgroundSync(job, syncButton, statusMessage, renderHistory);
    });
  }
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
  loadDeliverableFormView(formPanel, formItem, {
    state: formState,
    onBackgroundSync: (button) => runDeliverableFormArchiveSync(
      job,
      button,
      statusMessage,
      () => loadDeliverableFormView(formPanel, formItem, { state: formState }),
    ),
  });
}

function toggleDeliverableDetail(row, data, index, statusInfo = null) {
  const item = data && data.deliverables && data.deliverables[index];
  if (!item) return;
  location.hash = `#deliverable/${encodeURIComponent(item.id)}`;
}

async function runArchiveDetailBackgroundSync(job, syncButton, statusMessage, renderHistory) {
  syncButton.disabled = true;
  syncButton.textContent = "后台归档同步中...";
  statusMessage.textContent = "正在执行后台归档同步...";
  try {
    const response = await fetch(`/api/scheduled-archive/jobs/${encodeURIComponent(job.jobKey)}/sync-now`, {
      method: "POST",
      headers: { Accept: "application/json" },
    });
    const body = await response.json();
    if (!response.ok || !body || body.ok !== true) throw new Error((body && body.error && body.error.message) || "同步失败");
    const data = body.data || {};
    const firstRes = Array.isArray(data.results) && data.results[0] ? data.results[0] : null;
    if (data.exitCode !== 0 || (firstRes && firstRes.outcome !== "completed")) {
      const errMsg = (firstRes && (firstRes.errorMessage || firstRes.errorType))
        || (data.exitCode ? `同步未就绪（退出码 ${data.exitCode}）` : "同步未完成");
      throw new Error(redactSensitiveText(errMsg));
    }
    statusMessage.textContent = "同步成功，正在刷新图表与明细...";
    await loadArchiveJobs(true);
    await renderHistory();
  } catch (error) {
    statusMessage.textContent = `同步失败：${redactSensitiveText(error instanceof Error ? error.message : String(error))}`;
  } finally {
    syncButton.disabled = !job.enabled;
    syncButton.textContent = "后台归档同步";
  }
}

async function runDeliverableFormArchiveSync(job, button, statusMessage, reload) {
  if (!job || !button) return;
  button.disabled = true;
  button.textContent = "后台同步中...";
  statusMessage.textContent = "正在执行后台归档同步...";
  try {
    const response = await fetch(`/api/scheduled-archive/jobs/${encodeURIComponent(job.jobKey)}/sync-now`, {
      method: "POST",
      headers: { Accept: "application/json" },
    });
    const body = await response.json();
    if (!response.ok || !body || body.ok !== true) {
      const message = body && body.error && body.error.message ? body.error.message : "后台同步未完成";
      throw new Error(redactSensitiveText(message));
    }
    const data = body.data || {};
    const firstRes = Array.isArray(data.results) && data.results[0] ? data.results[0] : null;
    if (data.exitCode !== 0 || (firstRes && firstRes.outcome !== "completed")) {
      const errMsg = (firstRes && (firstRes.errorMessage || firstRes.errorType))
        || (data.exitCode ? `同步未就绪（退出码 ${data.exitCode}）` : "后台同步未完成");
      throw new Error(redactSensitiveText(errMsg));
    }
    statusMessage.textContent = "后台同步完成，正在刷新表单快照...";
    await loadArchiveJobs(true);
    // 归档同步可能发布新的表单快照，重新拉取概览数据再刷新关联视图。
    await loadProjectOverview();
    if (typeof reload === "function") await reload();
  } catch (error) {
    statusMessage.textContent = `同步失败：${redactSensitiveText(error instanceof Error ? error.message : String(error))}`;
  } finally {
    button.disabled = job.enabled !== true;
    button.textContent = "运行后台归档同步";
  }
}

function overviewDeliverableRows(data) {
  return Array.isArray(data && data.deliverables) ? data.deliverables.slice() : [];
}

// 外部来源交付物（参考）分区：列出单一关联注册表的全部条目
// （目录名 + 关联 DEL 编码 + 同步快照锚点）。快照仅参考，不计入完成统计。
async function renderExternalDeliverablesReference() {
  const listView = document.getElementById("overview-deliverables-list-view");
  if (!listView || typeof listView.querySelector !== "function") return;
  let section = listView.querySelector(".external-deliverables-band");
  if (!section) {
    section = overviewEl("section", "overview-band external-deliverables-band");
    section.setAttribute("aria-label", "外部来源交付物（参考）");
    const tableBand = listView.querySelector(".details-table-band");
    if (tableBand && tableBand.parentNode === listView) {
      listView.insertBefore(section, tableBand.nextSibling);
    } else {
      listView.appendChild(section);
    }
  }
  section.textContent = "";
  const head = overviewEl("div", "band-head");
  const headText = overviewEl("div");
  headText.append(
    overviewEl("p", "eyebrow", "参考"),
    overviewEl("h4", null, "外部来源交付物（参考）"),
  );
  head.append(headText, overviewEl("span", "external-deliverables-note", "快照仅参考，不计入完成统计"));
  section.appendChild(head);
  const list = overviewEl("ul", "external-deliverables-list");
  section.appendChild(list);

  let catalogItems = deliverableCatalogLoaded ? deliverableCatalog : null;
  if (!catalogItems) {
    try {
      const response = await fetch("/api/deliverables/catalog", {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      const body = await overviewReadJson(response);
      if (!response.ok || !body || body.ok !== true) {
        list.appendChild(overviewEl("li", "external-deliverables-error", "外部来源交付物目录读取失败"));
        return;
      }
      catalogItems = Array.isArray(body.data && body.data.deliverables) ? body.data.deliverables : [];
    } catch (error) {
      list.appendChild(overviewEl("li", "external-deliverables-error", "外部来源交付物目录读取失败"));
      return;
    }
  }
  catalogItems.forEach((entry) => {
    const links = entry && typeof entry.links === "object" && entry.links ? entry.links : null;
    if (!links) return;
    const item = overviewEl("li", "external-deliverables-item");
    item.appendChild(overviewEl("span", "external-deliverables-name", safeDisplayValue(entry.name)));
    item.appendChild(overviewEl(
      "span",
      "external-deliverables-code",
      links.displayCode ? String(links.displayCode) : "未关联项目交付物",
    ));
    const jobKey = String(links.archiveJobKey || "");
    if (jobKey) {
      const link = overviewEl("a", "external-deliverables-link", "查看同步快照");
      link.setAttribute("href", `#archive-deliverable/${encodeURIComponent(jobKey)}`);
      item.appendChild(link);
    }
    list.appendChild(item);
  });
}

function renderDeliverableDetails(tbody, data) {
  if (!tbody) return;
  tbody.textContent = "";
  const rows = overviewDeliverableRows(data);
  if (rows.length === 0) {
    renderTableState(tbody, "empty");
    return;
  }
  rows.forEach((rawRow, index) => {
    // 与状态总览环图共用同一份快照换算口径。
    const item = deliverableDisplayItem(rawRow);
    const manualEditState = deliverableManualEditState(item);
    const syncDisplay = deliverableSyncDisplay(item);
    const hasDisplayValue = SYNC_DISPLAY_VALUE_STATES.has(syncDisplay.state);
    const row = document.createElement("tr");
    row.className = "deliverable-detail-row";
    row.dataset.manualEditable = manualEditState.editable ? "true" : "false";
    if (!manualEditState.editable) {
      row.title = `手工字段只读：${manualEditState.reason}`;
    }
    const values = [
      item.name,
      deliverableStatusText(item, item),
      item.plannedDate,
      hasDisplayValue ? deliverableProgressOrDate(item) : syncDisplay.label,
      item.note,
      item.source,
    ];
    values.forEach((value, cellIndex) => {
      const cell = overviewEl("td", null);
      cell.dataset.label = OVERVIEW_DETAIL_COLUMNS[cellIndex];
      if (cellIndex === 1) {
        const statusTone = hasDisplayValue ? deliverableTone(item) : "primary";
        cell.appendChild(overviewEl("span", `status-text is-${statusTone}`, safeDisplayValue(value)));
        const snapshot = deliverableSnapshotSummary(item);
        if (item.status === "已逾期" && snapshot && Number(snapshot.summary.overdue) > 0) {
          const riskNote = overviewEl("span", "badge-risk-note", `${snapshot.summary.overdue}单超期`);
          riskNote.title = `快照中存在 ${snapshot.summary.overdue} 笔在途工单超过完成时限，交付物推进进度为 ${item.progress}%`;
          cell.appendChild(riskNote);
        }
      } else {
        cell.textContent = safeDisplayValue(value);
      }
      if (cellIndex === 0 && !manualEditState.editable) {
        cell.appendChild(overviewEl(
          "small",
          "detail-readonly-note",
          `手工字段只读：${redactSensitiveText(manualEditState.reason)}`,
        ));
      }
      if (cellIndex === 0) {
        const snapshotBadge = deliverableSnapshotBadge(item);
        if (snapshotBadge) cell.appendChild(snapshotBadge);
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

async function loadOverviewBusinessSnapshots(loadSequence) {
  const requestSequence = ++overviewBusinessSnapshotRequestSeq;
  overviewBusinessSnapshots = createOverviewBusinessSnapshotCache("loading");
  const results = await Promise.all(
    OVERVIEW_BUSINESS_SNAPSHOT_DEFINITIONS.map(async (definition) => {
      try {
        const query = new URLSearchParams({ trendLimit: "1" });
        const response = await fetch(
          `/api/deliverable-forms/${encodeURIComponent(definition.formKey)}/view?${query.toString()}`,
          { headers: { Accept: "application/json" }, cache: "no-store" },
        );
        const body = await overviewReadJson(response);
        if (!response.ok || !body || body.ok !== true) {
          throw overviewRequestError(body, response.status);
        }
        return { formKey: definition.formKey, status: "ready", data: body.data || {}, error: "" };
      } catch (error) {
        return {
          formKey: definition.formKey,
          status: "error",
          data: null,
          error: redactSensitiveText(error instanceof Error ? error.message : String(error)),
        };
      }
    }),
  );
  if (loadSequence !== overviewRequestSeq || requestSequence !== overviewBusinessSnapshotRequestSeq) return false;
  overviewBusinessSnapshots = Object.fromEntries(
    results.map(({ formKey, status, data, error }) => [formKey, { status, data, error }]),
  );
  return true;
}

function renderProjectOverview() {
  const timelineBody = document.getElementById("overview-timeline-body");
  const phaseBody = document.getElementById("overview-phase-summary");
  const progressGrid = document.getElementById("overview-progress-grid");
  const detailsSummary = document.getElementById("overview-details-summary");
  const detailsBody = document.getElementById("overview-details-body");
  const maintenanceBody = document.getElementById("milestone-maintenance");
  const containers = [timelineBody, phaseBody, progressGrid, detailsSummary].filter(Boolean);

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
    const nodeData = {
      ...overviewSavedState,
      deliverables: overviewSavedState.deliverables.map(deliverableDisplayItem),
    };
    if (window.VseNodeOverview && window.VseNodeOverview.render) {
      window.VseNodeOverview.render(phaseBody, nodeData, openMilestoneEditor);
    } else {
      renderPhaseSummary(phaseBody, overviewSavedState.phase, overviewSavedState.currentStage);
    }
    renderDeliverableProgress(progressGrid, overviewSavedState.deliverables);
    renderOverviewBusinessSnapshots(progressGrid);
    renderMilestoneMaintenance(maintenanceBody, overviewSavedState);
    renderDetailsSummary(detailsSummary, overviewSavedState);
    renderDeliverableDetails(detailsBody, overviewSavedState);
    // 外部来源交付物（参考）只读分区：数据来自 catalog payload 的 links。
    renderExternalDeliverablesReference();
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
  const loadSequence = ++overviewRequestSeq;
  // Invalidate any snapshot requests from the previous overview load before
  // starting the next one, including a load that later fails early.
  ++overviewBusinessSnapshotRequestSeq;
  overviewBusinessSnapshots = createOverviewBusinessSnapshotCache("loading");
  overviewLoading = true;
  overviewLoadError = null;
  renderProjectOverview();
  try {
    const response = await fetch(`/api/project-status?phase=${PROJECT_PHASE_ID}`, { headers: { Accept: "application/json" } });
    const body = await overviewReadJson(response);
    if (!response.ok || !body || body.ok !== true) {
      throw overviewRequestError(body, response.status);
    }
    if (loadSequence !== overviewRequestSeq) return;
    overviewSavedState = body.data || null;
    try {
      const archiveResponse = await fetch("/api/scheduled-archive/jobs", { headers: { Accept: "application/json" }, cache: "no-store" });
      const archiveBody = await overviewReadJson(archiveResponse);
      if (loadSequence !== overviewRequestSeq) return;
      overviewArchiveJobs = archiveResponse.ok && archiveBody && archiveBody.ok === true && Array.isArray(archiveBody.data)
        ? archiveBody.data
        : [];
    } catch {
      if (loadSequence !== overviewRequestSeq) return;
      overviewArchiveJobs = [];
    }
    await loadOverviewBusinessSnapshots(loadSequence);
  } catch (err) {
    if (loadSequence !== overviewRequestSeq) return;
    overviewSavedState = null;
    overviewLoadError = err instanceof Error ? err.message : String(err);
  } finally {
    if (loadSequence !== overviewRequestSeq) return;
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
  const manualEditState = deliverableManualEditState(item);
  if (!manualEditState.editable) {
    const readOnly = overviewEl("div", "detail-edit-readonly");
    readOnly.appendChild(overviewEl(
      "p",
      "detail-readonly-notice",
      `手工字段只读：${redactSensitiveText(manualEditState.reason)}`,
    ));
    return readOnly;
  }
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

function startInlineNoteEdit(field, item) {
  if (overviewSaving) return;
  const manualEditState = deliverableManualEditState(item);
  if (!manualEditState.editable) {
    appendDeliverableReadOnlyNotice(field, item, "detail-readonly-note");
    return;
  }
  if (overviewDraft && overviewDraftDirty()
    && !window.confirm("有未保存的更改，继续编辑风险与备注将使其他未保存编辑过期，是否继续？")) {
    return;
  }
  const valueEl = field.querySelector(".detail-property-value");
  const current = String(item.note || "");
  const input = document.createElement("input");
  input.type = "text";
  input.className = "note-inline-input";
  input.maxLength = 500;
  input.value = current;
  input.setAttribute("aria-label", "编辑风险与备注");
  valueEl.textContent = "";
  valueEl.appendChild(input);
  input.focus();
  let settled = false;
  const finish = async (save) => {
    if (settled) return;
    settled = true;
    const note = input.value.trim();
    if (!save || note === current) {
      renderDeliverableDetailPage(String(item.id));
      return;
    }
    const latestItem = overviewSavedState && Array.isArray(overviewSavedState.deliverables)
      ? overviewSavedState.deliverables.find((candidate) => candidate && candidate.id === item.id) || item
      : item;
    const latestManualEditState = deliverableManualEditState(latestItem);
    if (!latestManualEditState.editable) {
      input.disabled = false;
      settled = false;
      input.title = latestManualEditState.reason;
      input.classList.add("note-inline-input-error");
      appendDeliverableReadOnlyNotice(field, latestItem, "detail-readonly-note");
      return;
    }
    input.disabled = true;
    const payload = {
      status: latestItem.status,
      owner: latestItem.owner,
      plannedDate: latestItem.plannedDate,
      actualDate: latestItem.actualDate,
      progress: latestItem.progress,
      note,
      updatedAt: latestItem.updatedAt || "",
    };
    try {
      const response = await fetch(
        `/api/project-status/deliverables/${encodeURIComponent(String(item.id))}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify(payload),
        },
      );
      const body = await overviewReadJson(response);
      if (!response.ok || !body || body.ok !== true) {
        throw overviewRequestError(body, response.status);
      }
      const saved = body.data || {};
      if (!saved.projectStatus || overviewIsEmpty(saved.projectStatus)) {
        throw new Error("数据已保存，但刷新最新状态未完成；请刷新当前视图更新显示，无需重新保存");
      }
      overviewSavedState = saved.projectStatus;
      renderDeliverableDetailPage(String(item.id));
    } catch (error) {
      // 保留输入便于重试：恢复可编辑状态并提示错误。
      input.disabled = false;
      settled = false;
      input.title = redactSensitiveText(error instanceof Error ? error.message : String(error));
      input.classList.add("note-inline-input-error");
    }
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      finish(true);
    } else if (event.key === "Escape") {
      event.preventDefault();
      finish(false);
    }
  });
  input.addEventListener("blur", () => finish(true));
}

function startDeliverableEdit(index, detailEditPanel = null) {
  if (!overviewSavedState || overviewSaving) return;
  const item = overviewSavedState.deliverables[index];
  if (!item) return;
  const manualEditState = deliverableManualEditState(item);
  if (!manualEditState.editable) {
    const message = `手工字段只读：${redactSensitiveText(manualEditState.reason)}`;
    if (detailEditPanel) {
      detailEditPanel.hidden = false;
      detailEditPanel.textContent = "";
      detailEditPanel.appendChild(overviewEl("p", "detail-readonly-notice", message));
    } else {
      const row = overviewDetailsRow(index);
      const nameCell = row && row.querySelector("td");
      if (nameCell && !nameCell.querySelector(".detail-readonly-note")) {
        nameCell.appendChild(overviewEl("small", "detail-readonly-note", message));
      }
    }
    return;
  }
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
  const item = overviewSavedState
    && overviewSavedState.deliverables
    && overviewSavedState.deliverables[overviewDraft.index];
  if (!item) return;
  const manualEditState = deliverableManualEditState(item);
  if (!manualEditState.editable) {
    renderOverviewRequestMessage(`手工字段只读：${redactSensitiveText(manualEditState.reason)}`);
    return;
  }
  clearOverviewFieldErrors();
  const errors = validateDeliverableDraft();
  if (Object.keys(errors).length > 0) {
    renderOverviewFieldErrors(errors);
    return;
  }
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
    if (lbl === "主计划名称") {
      // 主计划名称支持单击内联编辑，无需进入阶段信息编辑表单。
      cell.classList.add("phase-meta-name-cell");
      const nameButton = overviewEl("button", "phase-name-inline-btn", "✎");
      nameButton.type = "button";
      nameButton.title = "编辑主计划名称";
      nameButton.setAttribute("aria-label", "编辑主计划名称");
      nameButton.addEventListener("click", () => startPhaseNameInlineEdit(phase));
      cell.querySelector(".phase-meta-value").appendChild(nameButton);
    }
    grid.appendChild(cell);
  });
  card.appendChild(grid);
  return card;
}

function startPhaseNameInlineEdit(phase) {
  if (overviewSaving) return;
  if (overviewDraft && overviewDraft.kind === "phase") return; // 编辑表单已打开
  const current = String(phase.displayName || phase.id || "");
  const valueEl = document.querySelector("#milestone-maintenance .phase-meta-name-cell .phase-meta-value");
  if (!valueEl) return;
  const input = document.createElement("input");
  input.type = "text";
  input.className = "phase-name-inline-input";
  input.maxLength = 120;
  input.value = current;
  input.setAttribute("aria-label", "编辑主计划名称");
  valueEl.textContent = "";
  valueEl.appendChild(input);
  input.focus();
  input.select();
  let settled = false;
  const finish = async (save) => {
    if (settled) return;
    settled = true;
    const name = input.value.trim();
    if (!save || !name || name === current) {
      renderProjectOverview();
      return;
    }
    input.disabled = true;
    try {
      const response = await fetch(`/api/project-status/phases/${PROJECT_PHASE_ID}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          displayName: name,
          status: phase.status,
          startDate: phase.startDate,
          endDate: phase.endDate,
          updatedAt: phase.updatedAt,
        }),
      });
      const body = await overviewReadJson(response);
      if (!response.ok || !body || body.ok !== true) {
        throw overviewRequestError(body, response.status);
      }
      const saved = body.data || {};
      if (!saved.projectStatus || overviewIsEmpty(saved.projectStatus)) {
        throw new Error("数据已保存，但刷新最新状态未完成；请刷新当前视图更新显示，无需重新保存");
      }
      overviewSavedState = saved.projectStatus;
      invalidateArchivePlanNameCache();
      renderProjectOverview();
    } catch (error) {
      // 保留输入便于重试：恢复可编辑状态并提示错误。
      input.disabled = false;
      settled = false;
      input.title = redactSensitiveText(error instanceof Error ? error.message : String(error));
      input.classList.add("phase-name-inline-input-error");
    }
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      finish(true);
    } else if (event.key === "Escape") {
      event.preventDefault();
      finish(false);
    }
  });
  input.addEventListener("blur", () => finish(true));
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
    const response = await fetch(`/api/project-status/phases/${PROJECT_PHASE_ID}`, {
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
    invalidateArchivePlanNameCache();
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

  if (milestoneRestoreNotice) {
    milestoneRestoreNotice = false;
    container.appendChild(
      overviewEl("p", "edit-request-info", "已删除全部节点，已自动恢复默认节点模板"),
    );
  }

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
      if (field === "type") row.status = MILESTONE_LABEL_BY_TYPE[control.value] || "未开始";
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
    const status = row.status || MILESTONE_LABEL_BY_TYPE[row.type] || "未开始";
    if (!date) {
      if (status !== "未开始") {
        errors[dateKey] = "空日期节点状态必须为未开始";
      }
    } else if (!datePattern.test(date)) {
      errors[dateKey] = "日期格式应为 YYYY-MM-DD";
    } else if (start && end && (date < start || date > end)) {
      errors[dateKey] = `节点日期需在阶段周期 ${start} 至 ${end} 内`;
    }
    if (!errors[dateKey] && date && (row.type === "done" || row.status === "已完成") && today && date > today) {
      errors[dateKey] = `已达成节点日期不能晚于当前日期 ${today}`;
    }
    // A past planned date is a valid unfinished/overdue node, not an invalid draft.
    // Keep it editable until the user explicitly confirms completion.
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

function renderMilestoneRequestMessage(message, tone = "error") {
  const form = document.getElementById("milestone-edit-form");
  if (!form) return;
  const region = form.querySelector(".milestone-request-message");
  if (!region) return;
  region.textContent = "";
  if (message) {
    region.appendChild(
      overviewEl("p", tone === "info" ? "edit-request-info" : "edit-request-error", message),
    );
  }
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
  // 删除全部节点后保存 → 服务端自动恢复默认节点模板（不再 422）。
  const hadNoRows = !overviewDraft.rows.length;
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
    const response = await fetch(`/api/project-status/phases/${PROJECT_PHASE_ID}/milestones`, {
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
    if (hadNoRows) milestoneRestoreNotice = true;
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

let milestoneRestoreNotice = false;

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
  if (resp.status === 202) {
    // Phase 3: 大导出已转为后台任务，返回任务标记而非文件体
    const body = await resp.json().catch(() => ({}));
    if (body && body.ok && body.data && body.data.taskId) {
      return { asyncTaskId: body.data.taskId };
    }
    throw new Error("后台导出任务响应无效，请稍后重试");
  }
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

function isAuthError(err, status) {
  if (status === 401 || status === 403) return true;
  const msg = String(err?.message || err || "").toLowerCase();
  return (
    msg.includes("未登录") ||
    msg.includes("登录过期") ||
    msg.includes("未认证") ||
    msg.includes("session expired") ||
    msg.includes("unauthorized") ||
    msg.includes("not authenticated") ||
    msg.includes("401") ||
    msg.includes("403")
  );
}

function renderStructuredErrorCard(container, config) {
  if (!container) return;
  container.innerHTML = "";
  container.hidden = false;

  const card = document.createElement("div");
  card.className = "structured-error-card";
  card.setAttribute("role", "alert");
  card.setAttribute("aria-live", "polite");

  const head = document.createElement("div");
  head.className = "structured-error-head";

  const icon = document.createElement("span");
  icon.className = "error-badge-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = "!";

  const headText = document.createElement("div");
  headText.className = "error-head-text";

  const summary = document.createElement("div");
  summary.className = "error-summary";
  summary.textContent = config.summary || "操作出现异常";

  const impact = document.createElement("div");
  impact.className = "error-impact";
  impact.textContent = config.impact || "原有数据已保留，请按建议操作恢复。";

  headText.append(summary, impact);
  head.append(icon, headText);
  card.appendChild(head);

  if (Array.isArray(config.actions) && config.actions.length > 0) {
    const actionsRow = document.createElement("div");
    actionsRow.className = "error-actions";
    config.actions.forEach((act) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `error-action-btn ${act.primary ? "is-primary" : ""}`;
      btn.textContent = act.label;
      btn.addEventListener("click", () => {
        if (typeof act.action === "function") act.action();
      });
      actionsRow.appendChild(btn);
    });
    card.appendChild(actionsRow);
  }

  if (config.technical) {
    const techDetails = document.createElement("details");
    techDetails.className = "error-technical-details";
    const techSummary = document.createElement("summary");
    techSummary.textContent = "技术详情（维护与排查问题使用）";
    const techContent = document.createElement("div");
    techContent.className = "error-technical-content";

    let rawText = "";
    if (typeof config.technical === "string") {
      rawText = config.technical;
    } else {
      rawText = JSON.stringify(config.technical, null, 2);
    }
    techContent.textContent = redactSensitiveText(rawText);

    techDetails.append(techSummary, techContent);
    card.appendChild(techDetails);
  }

  container.appendChild(card);
}

function renderEmptyNotice(title, desc) {
  const card = document.createElement("div");
  card.className = "empty-result-card";
  const icon = document.createElement("div");
  icon.className = "empty-result-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = "🔍";
  const titleEl = document.createElement("div");
  titleEl.className = "empty-result-title";
  titleEl.textContent = title;
  const descEl = document.createElement("div");
  descEl.className = "empty-result-desc";
  descEl.textContent = desc;
  card.appendChild(icon);
  card.appendChild(titleEl);
  card.appendChild(descEl);
  return card;
}

function showArasError(message, options = {}) {
  const error = document.getElementById("aras-error");
  if (!error) return;
  if (!message) {
    error.hidden = true;
    error.innerHTML = "";
    document.querySelector(".result-panel")?.classList.remove("has-output");
    return;
  }
  document.querySelector(".result-panel")?.classList.add("has-output");

  if (isAuthError(message, options.status)) {
    renderStructuredErrorCard(error, {
      summary: "企业域账号（Aras/ECM）会话已过期或尚未认证",
      impact: "当前查询无法完成，原页面已填写的查询条件与已有数据已完好保留。",
      actions: [
        {
          label: "重新登录",
          primary: true,
          action: () => openInPlaceLogin({
            notice: "Aras 会话已失效，请完成域登录。登录成功后可继续查询。",
            onLoginSuccess: () => {
              renderStructuredErrorCard(error, {
                summary: "登录成功，企业会话已就绪",
                impact: "当前筛选条件已完好保留，请点击【继续查询】获取最新报表数据。",
                actions: [
                  {
                    label: "继续查询",
                    primary: true,
                    action: () => {
                      error.hidden = true;
                      error.innerHTML = "";
                      runArasQuery();
                    },
                  },
                ],
              });
            },
          }),
        },
      ],
      technical: message,
    });
  } else {
    renderStructuredErrorCard(error, {
      summary: "Aras 报表查询未成功",
      impact: "未能获取最新数据，原页面已有数据和已填条件保持不变。",
      actions: [
        {
          label: "重新查询",
          primary: true,
          action: () => {
            error.hidden = true;
            error.innerHTML = "";
            runArasQuery();
          },
        },
      ],
      technical: message,
    });
  }
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

// ── Phase 4: 高密度数据网格（排序 / 快筛高亮 / 分页 / 列显隐 / 一键复制）──
const GRID_PAGE_SIZES = [50, 100];
const GRID_DEFAULT_PAGE_SIZE = 50;
const GRID_COLUMN_PREF_KEY = "vse-grid-column-prefs";
// 单号类列：label 以 号/No./Number 结尾，或 key 为 *_no / *_number / incident。
const GRID_COPYABLE_LABEL_RE = /号\s*$|No\.?\s*$|Number\s*$/i;
const GRID_COPYABLE_KEY_RE = /(^|_)(no|number|incident)(_|$)/i;

// Safe DOM 清空：textContent="" 在真实 DOM 与测试 DOM 桩中均可靠清空子节点。
function clearElement(el) {
  el.textContent = "";
}

function loadGridColumnPrefs() {
  try {
    const raw = localStorage.getItem(GRID_COLUMN_PREF_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (err) {
    return {};
  }
}

function saveGridColumnPrefs(scope, prefs) {
  try {
    const all = loadGridColumnPrefs();
    all[scope] = prefs;
    localStorage.setItem(GRID_COLUMN_PREF_KEY, JSON.stringify(all));
  } catch (err) {
    // 隐私模式等存储不可用场景静默降级为会话内偏好
  }
}

function parseNumericLike(text) {
  const trimmed = String(text).trim().replace(/,/g, "");
  if (!trimmed || !/^-?\d+(\.\d+)?$/.test(trimmed)) return null;
  return parseFloat(trimmed);
}

function compareGridValues(a, b) {
  const av = a == null ? "" : String(a);
  const bv = b == null ? "" : String(b);
  const an = parseNumericLike(av);
  const bn = parseNumericLike(bv);
  if (an !== null && bn !== null) {
    if (an !== bn) return an - bn;
    return 0;
  }
  return av.localeCompare(bv, "zh-Hans-CN", { numeric: true, sensitivity: "base" });
}

function appendHighlightedText(parent, text, query) {
  const value = text == null ? "" : String(text);
  if (!query) {
    parent.textContent = value;
    return;
  }
  const lower = value.toLowerCase();
  const needle = query.toLowerCase();
  let cursor = 0;
  for (;;) {
    const hit = lower.indexOf(needle, cursor);
    if (hit === -1) {
      if (cursor < value.length) parent.appendChild(document.createTextNode(value.slice(cursor)));
      break;
    }
    if (hit > cursor) parent.appendChild(document.createTextNode(value.slice(cursor, hit)));
    const mark = document.createElement("mark");
    mark.className = "grid-highlight";
    mark.textContent = value.slice(hit, hit + needle.length);
    parent.appendChild(mark);
    cursor = hit + needle.length;
  }
}

async function copyTextToClipboard(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (err) {
    // 继续走 execCommand 降级路径
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  } catch (err) {
    return false;
  }
}

function isCopyableColumn(label, key) {
  const labelHit = GRID_COPYABLE_LABEL_RE.test(String(label || ""));
  const keyHit = GRID_COPYABLE_KEY_RE.test(String(key || ""));
  return labelHit || keyHit;
}

function buildGridColumns(data, rows, preferredColumns, mode) {
  const headerRows = Array.isArray(data.headerRows) ? data.headerRows : null;
  const columns = Array.isArray(data.columns) ? data.columns : null;
  if (headerRows && headerRows.length > 0) {
    if (mode === "ncr-detail" && headerRows.length > 1) {
      // 多行分组表头（NCR detail）：仅支持 leaf 索引定位
      return { kind: "grouped", groups: headerRows, count: headerRows[0].length };
    }
    if (mode === "ncr-progress" && headerRows.length > 1) {
      // Skip blank top row for NCR progress
      const target = headerRows[1] || headerRows[0];
      return {
        kind: "labels",
        count: target.length,
        labels: target.map((label, i) => ({
          label: label ? String(label).trim() : `列 ${i + 1}`,
          key: null,
        })),
      };
    }
    return {
      kind: "labels",
      count: headerRows[0].length,
      labels: headerRows[0].map((label, i) => ({
        label: label ? String(label).trim() : `列 ${i + 1}`,
        key: null,
      })),
    };
  }
  if (columns && columns.length > 0) {
    return {
      kind: "labels",
      count: columns.length,
      labels: columns.map((col, i) => ({
        label: (col && (col.label || col.key)) || `列 ${i + 1}`,
        key: col && col.key ? String(col.key) : null,
      })),
    };
  }
  const keys = orderedColumns(rows, preferredColumns || []);
  return {
    kind: "labels",
    count: keys.length,
    labels: (keys.length ? keys : ["消息"]).map((key) => ({ label: key, key })),
    fallback: true,
  };
}

function gridColumnValue(row, column, index) {
  if (Array.isArray(row)) return row[index];
  if (row && typeof row === "object") {
    if (column.key && column.key in row) return row[column.key];
    return row[Object.keys(row)[index]];
  }
  return undefined;
}

function renderRows(data, preferredColumns, mode = "") {
  const rows = Array.isArray(data.rows) ? data.rows : [];
  const gridColumns = buildGridColumns(data, rows, preferredColumns, mode);
  const defaultVisible = Number(data.defaultVisibleCount) || 12;
  const isSor = mode === "tdc-sor" || mode === "sor" || mode === "tdc_sor";
  const scope = mode || data.report_type || "generic";
  const isGrouped = gridColumns.kind === "grouped";

  // 全部候选列（敏感列在源头剔除：SENSITIVE_COLUMNS 与服务端裁剪是唯一边界）
  const allColumns = [];
  for (let i = 0; i < gridColumns.count; i++) {
    const col = isGrouped ? { label: `列 ${i + 1}`, key: null } : gridColumns.labels[i];
    if (col.key && SENSITIVE_COLUMNS.has(col.key.toLowerCase())) continue;
    allColumns.push({ index: i, ...col });
  }
  // 常用列口径：defaultVisibleCount（缺省 12）内的列；「全量列」为全部列
  const commonCount = Math.min(allColumns.length, defaultVisible);

  const savedPrefs = loadGridColumnPrefs()[scope] || null;
  const state = {
    sortSpec: [], // [{index, dir: "asc"|"desc"}]
    filterText: "",
    page: 1,
    pageSize: GRID_DEFAULT_PAGE_SIZE,
    columnMode: savedPrefs ? savedPrefs.mode : "default",
    hiddenColumns: savedPrefs && Array.isArray(savedPrefs.hidden) ? savedPrefs.hidden : [],
  };

  // index→列 映射：2000+ 行过滤/排序的热路径避免反复线性查找
  const colByIndex = new Map();
  allColumns.forEach((col) => colByIndex.set(col.index, col));

  function computeVisibleColumns() {
    if (isGrouped) return allColumns.map((c) => c.index);
    if (state.columnMode === "common") {
      return allColumns.slice(0, commonCount).map((c) => c.index);
    }
    if (state.columnMode === "all") {
      return allColumns.map((c) => c.index);
    }
    if (state.columnMode === "custom") {
      return allColumns.filter((c) => !state.hiddenColumns.includes(c.index)).map((c) => c.index);
    }
    // default：与既有契约一致——仅 EWO/PAA 收敛到常用列
    return (mode === "ewo" || mode === "paa")
      ? allColumns.slice(0, commonCount).map((c) => c.index)
      : allColumns.map((c) => c.index);
  }

  function computeProcessedRows() {
    const visible = computeVisibleColumns();
    const visibleCols = visible.map((idx) => colByIndex.get(idx) || { label: `列 ${idx + 1}`, key: null });
    const query = state.filterText.trim().toLowerCase();
    let filtered = rows;
    if (query) {
      filtered = rows.filter((row) =>
        visibleCols.some((col, position) => {
          const value = gridColumnValue(row, col, visible[position]);
          return value != null && String(value).toLowerCase().includes(query);
        })
      );
    }
    if (state.sortSpec.length > 0) {
      const spec = state.sortSpec.map((item) => ({
        dir: item.dir,
        col: colByIndex.get(item.index) || { key: null },
        index: item.index,
      }));
      filtered = filtered.slice().sort((a, b) => {
        for (const item of spec) {
          const cmp = compareGridValues(
            gridColumnValue(a, item.col, item.index),
            gridColumnValue(b, item.col, item.index)
          );
          if (cmp !== 0) return item.dir === "asc" ? cmp : -cmp;
        }
        return 0;
      });
    }
    return { visible, visibleCols, filtered };
  }

  const wrap = document.createElement("div");
  wrap.className = "table-wrap grid-wrap";
  const table = document.createElement("table");
  table.className = "result-table";
  if (isSor) {
    table.classList.add("sor-result-table");
  }

  // ── 工具栏：快筛输入 + 列显隐 + 分页 ─────────────────────────────
  const toolbar = document.createElement("div");
  toolbar.className = "grid-toolbar";

  const filterBox = document.createElement("div");
  filterBox.className = "grid-filter-box";
  const filterInput = document.createElement("input");
  filterInput.type = "search";
  filterInput.className = "grid-filter-input";
  filterInput.placeholder = "关键字快筛（实时高亮）";
  filterInput.setAttribute("aria-label", "表格关键字快筛");
  const filterCount = document.createElement("span");
  filterCount.className = "grid-filter-count";
  filterBox.append(filterInput, filterCount);
  toolbar.appendChild(filterBox);

  let columnPickerBtn = null;
  let pickerPanel = null;
  if (!isGrouped && !gridColumns.fallback) {
    columnPickerBtn = document.createElement("button");
    columnPickerBtn.type = "button";
    columnPickerBtn.className = "grid-column-btn";
    columnPickerBtn.textContent = "列显隐";
    columnPickerBtn.setAttribute("aria-haspopup", "true");
    columnPickerBtn.setAttribute("aria-expanded", "false");

    pickerPanel = document.createElement("div");
    pickerPanel.className = "grid-column-panel";
    pickerPanel.hidden = true;

    const quickRow = document.createElement("div");
    quickRow.className = "grid-column-quick";
    const commonBtn = document.createElement("button");
    commonBtn.type = "button";
    commonBtn.className = "grid-quick-btn";
    commonBtn.textContent = "常用列";
    const allBtn = document.createElement("button");
    allBtn.type = "button";
    allBtn.className = "grid-quick-btn";
    allBtn.textContent = "全量列";
    quickRow.append(commonBtn, allBtn);

    const checkList = document.createElement("div");
    checkList.className = "grid-column-list";

    function rebuildCheckList() {
      clearElement(checkList);
      allColumns.forEach((col) => {
        const item = document.createElement("label");
        item.className = "grid-column-item";
        const box = document.createElement("input");
        box.type = "checkbox";
        const isVisible =
          state.columnMode === "custom"
            ? !state.hiddenColumns.includes(col.index)
            : computeVisibleColumns().includes(col.index);
        box.checked = isVisible;
        box.addEventListener("change", () => {
          const hiddenSet = new Set(state.hiddenColumns);
          if (box.checked) {
            hiddenSet.delete(col.index);
          } else {
            hiddenSet.add(col.index);
          }
          state.hiddenColumns = Array.from(hiddenSet).sort((a, b) => a - b);
          state.columnMode = "custom";
          saveGridColumnPrefs(scope, { mode: "custom", hidden: state.hiddenColumns });
          state.page = 1;
          refreshBody();
        });
        const text = document.createElement("span");
        text.textContent = col.label;
        item.append(box, text);
        checkList.appendChild(item);
      });
    }

    commonBtn.addEventListener("click", () => {
      state.columnMode = "common";
      state.hiddenColumns = [];
      saveGridColumnPrefs(scope, { mode: "common", hidden: [] });
      state.page = 1;
      rebuildCheckList();
      refreshBody();
    });
    allBtn.addEventListener("click", () => {
      state.columnMode = "all";
      state.hiddenColumns = [];
      saveGridColumnPrefs(scope, { mode: "all", hidden: [] });
      state.page = 1;
      rebuildCheckList();
      refreshBody();
    });
    columnPickerBtn.addEventListener("click", () => {
      pickerPanel.hidden = !pickerPanel.hidden;
      columnPickerBtn.setAttribute("aria-expanded", pickerPanel.hidden ? "false" : "true");
      if (!pickerPanel.hidden) rebuildCheckList();
    });
    pickerPanel.append(quickRow, checkList);
    toolbar.appendChild(columnPickerBtn);
    toolbar.appendChild(pickerPanel);
  }

  wrap.appendChild(toolbar);

  const thead = document.createElement("thead");
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  table.appendChild(tbody);
  const pagerBar = document.createElement("div");
  pagerBar.className = "grid-pager";
  wrap.appendChild(table);
  wrap.appendChild(pagerBar);

  function buildHeaderCell(label, index, colspanRows) {
    const th = document.createElement("th");
    appendHighlightedText(th, label, state.filterText);
    if (!isGrouped && !gridColumns.fallback) {
      th.classList.add("grid-sortable");
      const sortEntry = state.sortSpec.find((s) => s.index === index);
      if (sortEntry) {
        const indicator = document.createElement("span");
        indicator.className = "grid-sort-indicator";
        const orderIdx = state.sortSpec.indexOf(sortEntry);
        indicator.textContent =
          (sortEntry.dir === "asc" ? "▲" : "▼") + (state.sortSpec.length > 1 ? String(orderIdx + 1) : "");
        th.appendChild(indicator);
      }
      th.addEventListener("click", (event) => {
        const existing = state.sortSpec.find((s) => s.index === index);
        if (existing) {
          if (existing.dir === "asc") {
            existing.dir = "desc";
          } else {
            state.sortSpec = state.sortSpec.filter((s) => s.index !== index);
          }
        } else if (event.shiftKey) {
          state.sortSpec.push({ index, dir: "asc" });
        } else {
          state.sortSpec = [{ index, dir: "asc" }];
        }
        state.page = 1;
        refreshBody();
      });
    }
    return th;
  }

  function refreshHeader() {
    clearElement(thead);
    if (isGrouped) {
      gridColumns.groups.forEach((hRow) => {
        const tr = document.createElement("tr");
        hRow.forEach((label) => {
          const th = document.createElement("th");
          appendHighlightedText(th, label ? String(label).trim() : "", state.filterText);
          tr.appendChild(th);
        });
        thead.appendChild(tr);
      });
      return;
    }
    const visible = computeVisibleColumns();
    const tr = document.createElement("tr");
    visible.forEach((idx) => {
      const col = colByIndex.get(idx) || { label: `列 ${idx + 1}`, key: null };
      tr.appendChild(buildHeaderCell(col.label, idx));
    });
    thead.appendChild(tr);
  }

  function refreshBody() {
    refreshHeader();
    const { visible, visibleCols, filtered } = computeProcessedRows();
    const colCount = Math.max(1, visible.length);

    const totalPages = Math.max(1, Math.ceil(filtered.length / state.pageSize));
    if (state.page > totalPages) state.page = totalPages;
    const start = (state.page - 1) * state.pageSize;
    const pageRows = filtered.slice(start, start + state.pageSize);

    clearElement(tbody);
    if (pageRows.length === 0) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = colCount;
      td.textContent = state.filterText ? "无匹配记录" : "无结果";
      tr.appendChild(td);
      tbody.appendChild(tr);
    } else {
      pageRows.forEach((row) => {
        const tr = document.createElement("tr");
        visible.forEach((idx, position) => {
          const col = visibleCols[position] || { label: `列 ${idx + 1}`, key: null };
          const td = document.createElement("td");
          const value = gridColumnValue(row, col, idx);
          appendHighlightedText(td, safeDisplayValue(value), state.filterText);
          if (isCopyableColumn(col.label, col.key) && value != null && String(value).trim()) {
            td.classList.add("grid-copyable");
            const copyBtn = document.createElement("button");
            copyBtn.type = "button";
            copyBtn.className = "grid-copy-btn";
            copyBtn.textContent = "📋";
            copyBtn.title = "复制";
            copyBtn.setAttribute("aria-label", `复制 ${col.label}`);
            copyBtn.addEventListener("click", (event) => {
              event.stopPropagation();
              copyTextToClipboard(String(value).trim()).then((ok) => {
                copyBtn.textContent = ok ? "✓" : "✕";
                setTimeout(() => {
                  copyBtn.textContent = "📋";
                }, 1200);
              });
            });
            td.appendChild(copyBtn);
          }
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
    }
    refreshPager(filtered.length, totalPages);
    refreshFilterCount(filtered.length, rows.length);
  }

  function refreshPager(total, totalPages) {
    clearElement(pagerBar);
    if (total === 0) return;
    const info = document.createElement("span");
    info.className = "grid-pager-info";
    info.textContent = `共 ${total} 条 · 第 ${state.page}/${totalPages} 页`;
    pagerBar.appendChild(info);

    const prev = document.createElement("button");
    prev.type = "button";
    prev.className = "grid-pager-btn";
    prev.textContent = "上一页";
    prev.disabled = state.page <= 1;
    prev.addEventListener("click", () => {
      state.page = Math.max(1, state.page - 1);
      refreshBody();
    });
    const next = document.createElement("button");
    next.type = "button";
    next.className = "grid-pager-btn";
    next.textContent = "下一页";
    next.disabled = state.page >= totalPages;
    next.addEventListener("click", () => {
      state.page = Math.min(totalPages, state.page + 1);
      refreshBody();
    });
    pagerBar.append(prev, next);

    const sizeLabel = document.createElement("span");
    sizeLabel.className = "grid-pager-size-label";
    sizeLabel.textContent = "每页";
    const sizeSelect = document.createElement("select");
    sizeSelect.className = "grid-pager-size";
    sizeSelect.setAttribute("aria-label", "每页条数");
    GRID_PAGE_SIZES.forEach((size) => {
      const option = document.createElement("option");
      option.value = String(size);
      option.textContent = String(size);
      if (size === state.pageSize) option.selected = true;
      sizeSelect.appendChild(option);
    });
    sizeSelect.addEventListener("change", () => {
      state.pageSize = Number(sizeSelect.value) || GRID_DEFAULT_PAGE_SIZE;
      state.page = 1;
      refreshBody();
    });
    pagerBar.append(sizeLabel, sizeSelect);
  }

  function refreshFilterCount(matched, total) {
    filterCount.textContent = state.filterText ? `${matched}/${total} 条` : "";
  }

  filterInput.addEventListener("input", () => {
    state.filterText = filterInput.value;
    state.page = 1;
    refreshBody();
  });

  refreshBody();
  return wrap;
}

function renderArasResult(data, mode, config) {
  arasHasRenderedResult = true;
  const target = document.getElementById("aras-result");
  document.querySelector(".result-panel")?.classList.add("has-output");
  target.className = "result-output-content";
  target.innerHTML = "";
  const ctx = document.getElementById("aras-preview-context");
  if (ctx) {
    ctx.hidden = true;
    ctx.textContent = "";
  }
  document.getElementById("result-kind").textContent = RESULT_KIND_LABELS[config.resultKind] || config.resultKind;
  const outputMeta = document.createElement("p");
  outputMeta.className = "result-output-meta";
  outputMeta.textContent = `${COMMAND_LABELS[mode] || mode} -> ${config.endpoint}`;
  target.appendChild(outputMeta);
  if (config.resultKind === "rows") {
    const meta = document.createElement("p");
    meta.className = "result-meta";
    let metaText = `页码=${data.page || "-"} 行数=${data.count || 0} 项目数=${(data.item_ids || []).length}`;
    if (data.preview && data.preview.sheetName) {
      metaText += ` 表格=${data.preview.sheetName}`;
      if (data.preview.truncated) metaText += "（已展示前置行）";
    }
    meta.textContent = metaText;
    target.appendChild(meta);
    if (data.mappingComplete === false && Array.isArray(data.unmappedColumns) && data.unmappedColumns.length > 0) {
      const warning = document.createElement("p");
      warning.className = "result-meta result-warning";
      warning.textContent = `当前接口尚未提供 ${data.unmappedColumns.length} 个工作簿派生列，已保留为空值；请使用官方导出获取完整报表。`;
      target.appendChild(warning);
    }
    const rowCount = data.count != null ? data.count : (data.rows || []).length;
    if (data.queryState === "empty" || rowCount === 0) {
      target.appendChild(renderEmptyNotice(
        "未查询到符合条件的记录",
        "当前筛选条件下未返回任何数据记录。原表单查询条件已完好保留，您可以调整筛选条件后重新查询。"
      ));
    } else {
      target.appendChild(renderRows(data, config.preferredColumns, mode));
    }
    renderArasXmlCapture(data, config);
  } else {
    target.appendChild(renderSummary(data));
  }
}

// ── Phase 3: 统一后台任务契约（202 Accepted + task_id）────────────────
const ASYNC_TASK_POLL_INTERVAL_MS = 2000;
const ASYNC_TASK_POLL_TIMEOUT_MS = 30 * 60 * 1000;

function isAsyncTaskAccepted(resp, body) {
  return resp.status === 202 && !!body && body.ok === true && !!(body.data && body.data.taskId);
}

function kickTaskCenterPolling() {
  document.dispatchEvent(new CustomEvent("vse:task-center-kick"));
}

function asyncTaskSleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForTaskCompletion(taskId, timeoutMs = ASYNC_TASK_POLL_TIMEOUT_MS) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const resp = await fetch(`/api/tasks/${encodeURIComponent(taskId)}`);
      if (resp.ok) {
        const body = await resp.json();
        const task = body && body.data;
        if (task && task.is_active === false) return task;
      }
    } catch (err) {
      // 瞬态网络错误继续轮询，由超时兜底
    }
    await asyncTaskSleep(ASYNC_TASK_POLL_INTERVAL_MS);
  }
  return null;
}

async function fetchTaskResult(taskId) {
  const resp = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/result`);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok || !body.ok) {
    throw new Error(formatApiErrorMessage((body && body.error) || {}, resp.status));
  }
  return body.data;
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
  const ctx = document.getElementById("aras-preview-context");
  if (ctx && arasHasRenderedResult) {
    ctx.hidden = false;
    ctx.textContent = "保留上次查询结果 · 正在全量获取最新数据...";
  }
  const payload = collectArasPayload(requestConfig);
  try {
    const resp = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await resp.json();
    if (isAsyncTaskAccepted(resp, body)) {
      const taskId = body.data.taskId;
      kickTaskCenterPolling();
      if (seq > arasLatestRendered) {
        const ctx = document.getElementById("aras-preview-context");
        if (ctx) {
          ctx.hidden = false;
          ctx.textContent = `全量抓取已转入后台任务（${taskId}），进度与结果请见右上角「任务」中心，完成后将自动展示。`;
        }
      }
      trackArasCrawlTask(taskId, seq, requestMode, requestConfig);
      return;
    }
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
      const ctx = document.getElementById("aras-preview-context");
      if (ctx && arasHasRenderedResult) {
        ctx.hidden = false;
        ctx.textContent = "未能获取最新数据，已为您保留上次查询成功的历史结果（可检查上方错误提示后重试）。";
      }
    }
  } finally {
    clearArasPayloadSecrets(payload);
    arasRunning = false;
    setArasStatus("");
  }
}

function trackArasCrawlTask(taskId, seq, requestMode, requestConfig) {
  (async () => {
    const finished = await waitForTaskCompletion(taskId);
    if (seq <= arasLatestRendered) return;
    if (!finished) {
      showArasError("后台全量抓取任务长时间未完成，请稍后在「任务」中心查看结果。");
      return;
    }
    if (finished.status === "cancelled") {
      setArasStatus("后台全量抓取任务已取消", false);
      return;
    }
    if (finished.status !== "succeeded") {
      showArasError(`后台全量抓取任务失败：${redactSensitiveText(finished.error_message || finished.status)}`);
      return;
    }
    try {
      const result = await fetchTaskResult(taskId);
      if (seq > arasLatestRendered) {
        arasLatestRendered = seq;
        renderArasResult(result, requestMode, requestConfig);
        setArasStatus("后台全量抓取完成", false);
      }
    } catch (err) {
      showArasError(redactSensitiveText(err.message));
    }
  })();
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
  const ctx = document.getElementById("aras-preview-context");
  if (ctx && arasHasRenderedResult) {
    ctx.hidden = false;
    ctx.textContent = "保留上次查询结果 · 正在获取最新数据...";
  }
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
      const ctx = document.getElementById("aras-preview-context");
      if (ctx && arasHasRenderedResult) {
        ctx.hidden = false;
        ctx.textContent = "未能获取最新数据，已为您保留上次查询成功的历史结果（可检查上方错误提示后重试）。";
      }
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
    if (outcome.asyncTaskId) {
      kickTaskCenterPolling();
      setArasStatus(`导出已转入后台任务（${outcome.asyncTaskId}），完成后请在右上角「任务」中心下载`, false);
      return;
    }
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

let tdcSorProjectRequestSeq = 0;

async function loadTdcSorProjectOptions(form) {
  if (!form) form = document.getElementById("deliverable-form");
  if (!form) return;
  const select = form.querySelector("#tdc-car-type-project-options");
  const loadBtn = form.querySelector("#tdc-load-car-type-projects");
  if (!select) return;

  const baseUrl = fieldValue(form, "base_url");
  const capturedHeaders = fieldValue(form, "headers");
  const requestSeq = ++tdcSorProjectRequestSeq;
  form.dataset.projectRequestSeq = String(requestSeq);
  const capturedBaseUrl = baseUrl;
  const hiddenId = form.querySelector('[name="car_type_project_id"]');
  if (hiddenId) hiddenId.value = "";
  select.value = "";
  select.disabled = true;

  if (loadBtn) {
    loadBtn.disabled = true;
    loadBtn.textContent = "加载中...";
  }

  try {
    const headers = parseHeaders(capturedHeaders);
    const resp = await fetch("/api/tdc/sor/car-type-projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base_url: baseUrl, headers }),
    });
    const body = await resp.json();

    const isDetached = typeof form.isConnected === "boolean" ? !form.isConnected : (document.body && !document.body.contains(form));
    if (isDetached || Number(form.dataset.projectRequestSeq) !== requestSeq) {
      return;
    }
    if (fieldValue(form, "base_url") !== capturedBaseUrl || fieldValue(form, "headers") !== capturedHeaders) {
      return;
    }

    if (!resp.ok || !body.ok) {
      const err = body.error || {};
      const msg = formatApiErrorMessage(err, resp.status);
      select.innerHTML = "";
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = `加载失败：${redactSensitiveText(msg)}`;
      select.appendChild(opt);
      return;
    }

    const rawProjects = (body.data && Array.isArray(body.data.projects)) ? body.data.projects : [];
    const validProjects = rawProjects.filter((p) => p && typeof p.id === "string" && p.id.trim());
    select.innerHTML = "";
    if (validProjects.length === 0) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "未找到可用车型项目";
      select.appendChild(opt);
      return;
    }

    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = `请选择车型项目（共 ${validProjects.length} 项）`;
    select.appendChild(placeholder);

    validProjects.forEach((proj) => {
      const opt = document.createElement("option");
      const idVal = proj.id.trim();
      opt.value = idVal;
      opt.dataset.projectNo = proj.projectNo || "";
      opt.dataset.projectName = proj.projectName || "";
      opt.textContent = proj.label || proj.projectNo || proj.projectName || idVal;
      select.appendChild(opt);
    });
  } catch (err) {
    const isDetached = typeof form.isConnected === "boolean" ? !form.isConnected : (document.body && !document.body.contains(form));
    if (isDetached || Number(form.dataset.projectRequestSeq) !== requestSeq) {
      return;
    }
    select.innerHTML = "";
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = `加载失败：${redactSensitiveText(err.message)}`;
    select.appendChild(opt);
  } finally {
    const isDetached = typeof form.isConnected === "boolean" ? !form.isConnected : (document.body && !document.body.contains(form));
    if (loadBtn && !isDetached && Number(form.dataset.projectRequestSeq) === requestSeq) {
      select.disabled = false;
      loadBtn.disabled = false;
      loadBtn.textContent = "重新加载车型项目";
    }
  }
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
    label.append(span, input);
    if (item.id === "tdc-sor" && field.name === "car_type_project") {
      input.placeholder = "例如：E262S（车型项目，可手动输入）";
      input.autocomplete = "off";

      const hiddenId = document.createElement("input");
      hiddenId.type = "hidden";
      hiddenId.name = "car_type_project_id";
      hiddenId.id = "tdc-car-type-project-id";

      const projectGroup = document.createElement("div");
      projectGroup.className = "car-type-project-group";

      const select = document.createElement("select");
      select.id = "tdc-car-type-project-options";
      select.className = "car-type-project-options";
      const defaultOption = document.createElement("option");
      defaultOption.value = "";
      defaultOption.textContent = "请选择车型项目（需先加载）";
      select.appendChild(defaultOption);

      const loadBtn = document.createElement("button");
      loadBtn.type = "button";
      loadBtn.id = "tdc-load-car-type-projects";
      loadBtn.className = "segment car-type-load-btn";
      loadBtn.textContent = "重新加载车型项目";

      loadBtn.addEventListener("click", () => {
        loadTdcSorProjectOptions(form);
      });

      select.addEventListener("change", () => {
        const chosen = select.options && select.selectedIndex >= 0 ? select.options[select.selectedIndex] : null;
        if (!chosen || !chosen.value) {
          hiddenId.value = "";
          return;
        }
        const visibleText = (chosen.dataset && (chosen.dataset.projectNo || chosen.dataset.projectName)) || "";
        input.value = visibleText;
        hiddenId.value = chosen.value;
      });

      const clearSelectedId = () => {
        hiddenId.value = "";
        select.value = "";
      };
      input.addEventListener("input", clearSelectedId);
      input.addEventListener("change", clearSelectedId);

      projectGroup.append(select, loadBtn);
      label.append(hiddenId, projectGroup);
    }
    fieldsGrid.appendChild(label);
  });
  fieldsSection.appendChild(fieldsGrid);
  form.appendChild(fieldsSection);

  if (item.id === "tdc-sor") {
    const baseUrlInput = form.querySelector("#tdc-base-url");
    const headersInput = form.querySelector("#tdc-headers");
    const invalidateSorProjects = () => {
      form.dataset.projectRequestSeq = String(++tdcSorProjectRequestSeq);
      const loadBtn = form.querySelector("#tdc-load-car-type-projects");
      if (loadBtn) { loadBtn.disabled = false; loadBtn.textContent = "重新加载车型项目"; }
      const hiddenId = form.querySelector('[name="car_type_project_id"]');
      if (hiddenId) hiddenId.value = "";
      const select = form.querySelector("#tdc-car-type-project-options");
      if (select) {
        select.disabled = false;
        select.innerHTML = "";
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "连接配置已变更，请重新加载车型项目";
        select.appendChild(opt);
        select.value = "";
      }
    };
    if (baseUrlInput) {
      baseUrlInput.addEventListener("input", invalidateSorProjects);
      baseUrlInput.addEventListener("change", invalidateSorProjects);
    }
    if (headersInput) {
      headersInput.addEventListener("input", invalidateSorProjects);
      headersInput.addEventListener("change", invalidateSorProjects);
    }
  }

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
  Object.keys(deliverablePreviewStates).forEach((key) => delete deliverablePreviewStates[key]);
  detail.innerHTML = "";
  panel.hidden = true;
  error.hidden = true;
  result.className = "is-empty";
  result.textContent = "暂无结果";
  const ctx = document.getElementById("deliverable-preview-context");
  if (ctx) {
    ctx.hidden = true;
    ctx.textContent = "";
  }

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
    openButton.textContent = "在系统查询中打开";
    openButton.addEventListener("click", () => openDeliverableInAras(item));
    detail.appendChild(openButton);
  }
  // 关联了项目状态交付物时提供跳转入口（复用既有 hash 导航，不新增路由）。
  const detailLinks = item.links && typeof item.links === "object" ? item.links : null;
  if (detailLinks && detailLinks.projectStatusDeliverableId) {
    const statusEntry = overviewEl("button", "btn is-secondary open-project-status-btn", "查看项目状态/表单分析");
    statusEntry.type = "button";
    statusEntry.addEventListener("click", () => {
      location.hash = `#deliverable/${encodeURIComponent(String(detailLinks.projectStatusDeliverableId))}`;
    });
    detail.appendChild(statusEntry);
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
  if (item.id === "tdc-sor") {
    const projectId = fieldValue(form, "car_type_project_id");
    if (projectId) {
      payload.filters.car_type_project_id = projectId;
    }
  }
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

function showDeliverableError(message, options = {}) {
  const error = document.getElementById("deliverable-error");
  if (!error) return;
  if (!message) {
    error.hidden = true;
    error.innerHTML = "";
    return;
  }
  const panel = document.getElementById("deliverable-result-panel");
  if (panel) panel.hidden = false;

  if (isAuthError(message, options.status)) {
    renderStructuredErrorCard(error, {
      summary: "企业系统认证会话已过期或尚未登录",
      impact: "未能执行本次查询，已保留当前选择的报表、筛选草稿与已有预览。",
      actions: [
        {
          label: "重新登录",
          primary: true,
          action: () => openInPlaceLogin({
            notice: "企业会话已失效，请完成域账号登录。登录成功后可继续操作。",
            onLoginSuccess: () => {
              renderStructuredErrorCard(error, {
                summary: "登录成功，会话已更新",
                impact: "当前筛选条件已完好保留，请点击【继续查询】完成操作。",
                actions: [
                  {
                    label: "继续查询",
                    primary: true,
                    action: () => {
                      error.hidden = true;
                      error.innerHTML = "";
                      const runBtn = document.getElementById("deliverable-run-button");
                      if (runBtn) runBtn.click();
                    },
                  },
                ],
              });
            },
          }),
        },
      ],
      technical: message,
    });
  } else {
    renderStructuredErrorCard(error, {
      summary: "交付物查询/导出未成功",
      impact: "未更新本地数据，原有预览和配置保持不变。",
      actions: [
        {
          label: "重试查询",
          primary: true,
          action: () => {
            error.hidden = true;
            error.innerHTML = "";
            const runBtn = document.getElementById("deliverable-run-button");
            if (runBtn) runBtn.click();
          },
        },
      ],
      technical: message,
    });
  }
}

const deliverablePreviewStates = {};

function formatDeliverableFilterSummary(item, filters = {}) {
  const parts = [];
  const fieldMap = new Map();
  (item.fields || []).forEach((f) => fieldMap.set(f.name, f.label || f.name));
  Object.entries(filters).forEach(([key, val]) => {
    if (key === "car_type_project_id") return;
    if (val !== undefined && val !== null && String(val).trim()) {
      const label = fieldMap.get(key) || key;
      parts.push(`${label}: ${redactSensitiveText(String(val).trim())}`);
    }
  });
  return parts.length ? parts.join("；") : "无筛选条件";
}

function getOrCreateDeliverablePreviewContext() {
  let ctx = document.getElementById("deliverable-preview-context");
  if (!ctx) {
    ctx = document.createElement("div");
    ctx.id = "deliverable-preview-context";
    ctx.className = "deliverable-preview-context";
    const panel = document.getElementById("deliverable-result-panel");
    const result = document.getElementById("deliverable-result");
    if (panel && result) {
      panel.insertBefore(ctx, result);
    } else if (panel) {
      panel.appendChild(ctx);
    }
  }
  return ctx;
}

function renderDeliverableResult(data, item, operation, capturedContext = null) {
  const panel = document.getElementById("deliverable-result-panel");
  const target = document.getElementById("deliverable-result");
  panel.hidden = false;
  panel.classList.add("has-output");
  target.className = "result-output-content";
  target.innerHTML = "";
  document.getElementById("deliverable-result-kind").textContent = DELIVERABLE_OPERATION_LABELS[operation] || operation;

  const ctx = getOrCreateDeliverablePreviewContext();
  if (capturedContext) {
    deliverablePreviewStates[item.id] = capturedContext;
    ctx.hidden = false;
    ctx.textContent = `预览生成时间：${capturedContext.queryTime} · 筛选条件：${capturedContext.filterSummary}`;
  } else if (deliverablePreviewStates[item.id] && deliverablePreviewStates[item.id].hasPreview) {
    const prev = deliverablePreviewStates[item.id];
    ctx.hidden = false;
    ctx.textContent = `预览生成时间：${prev.queryTime} · 筛选条件：${prev.filterSummary}`;
  } else {
    ctx.hidden = true;
    ctx.textContent = "";
  }

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
    warning.textContent = `列表接口尚未提供 ${data.unmappedColumns.length} 个官方导出列，已保留为空值；请使用官方导出预览。`;
    target.appendChild(warning);
  }
  const rowCount = (data.rows || []).length;
  if (rowCount === 0) {
    target.appendChild(renderEmptyNotice(
      "未查询到符合条件的交付物记录",
      "当前筛选条件下未返回任何交付物数据。已保留所选交付物及筛选配置，您可以修改筛选条件后重试。"
    ));
  } else {
    target.appendChild(renderRows(data, [], item.id));
  }
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

  const requestForm = document.getElementById("deliverable-form");
  const prev = deliverablePreviewStates[item.id];
  if (prev && prev.hasPreview) {
    const ctx = getOrCreateDeliverablePreviewContext();
    ctx.hidden = false;
    ctx.textContent = `保留上次查询预览（生成时间：${prev.queryTime} · 筛选条件：${prev.filterSummary}）· 新操作处理中...`;
  }

  let payload = null;
  try {
    payload = collectDeliverablePayload(item, operation);
    const endpoint = config.endpoints[operation];
    if (!endpoint) {
      throw new Error(`未配置操作端点: ${operation}`);
    }

    if (operation === "export") {
      const outcome = await fetchBlobDownload(endpoint, payload, config.defaultExportName);
      if (outcome.asyncTaskId) {
        kickTaskCenterPolling();
        recordRecentRun(item, operation, "success", `后台任务 ${outcome.asyncTaskId}`);
        if (requestForm === document.getElementById("deliverable-form")) {
          setDeliverableStatus(`导出已转入后台任务，完成后请在右上角「任务」中心下载`, false);
        }
        return;
      }
      if (seq > deliverableLatestRendered) {
        deliverableLatestRendered = seq;
        delete deliverablePreviewStates[item.id];
        const ctx = getOrCreateDeliverablePreviewContext();
        ctx.hidden = true;
        ctx.textContent = "";
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
      if (requestForm === document.getElementById("deliverable-form")) setDeliverableStatus(`已下载：${outcome.fileName}`, false);
    } else {
      const resp = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await resp.json();
      if (isAsyncTaskAccepted(resp, body)) {
        const taskId = body.data.taskId;
        kickTaskCenterPolling();
        if (seq > deliverableLatestRendered) {
          const ctx = getOrCreateDeliverablePreviewContext();
          ctx.hidden = false;
          ctx.textContent = `全量抓取已转入后台任务（${taskId}），进度与结果请见右上角「任务」中心，完成后将自动展示。`;
        }
        trackDeliverableCrawlTask(taskId, seq, item, operation);
        return;
      }
      if (!resp.ok || !body.ok) {
        const err = body.error || {};
        throw new Error(formatApiErrorMessage(err, resp.status));
      }
      if (seq > deliverableLatestRendered) {
        deliverableLatestRendered = seq;
        const capturedContext = {
          hasPreview: true,
          queryTime: new Date().toLocaleString(),
          filterSummary: formatDeliverableFilterSummary(item, payload.filters),
        };
        renderDeliverableResult(body.data || {}, item, operation, capturedContext);
      }
      const data = body.data || {};
      recordRecentRun(item, operation, "success", `rows=${(data.rows || []).length}`);
      if (requestForm === document.getElementById("deliverable-form")) setDeliverableStatus("完成", false);
    }
  } catch (err) {
    if (seq > deliverableLatestRendered) {
      deliverableLatestRendered = seq;
      showDeliverableError(redactSensitiveText(err.message));
      const retained = deliverablePreviewStates[item.id];
      if (operation === "export") {
        document.getElementById("deliverable-result-kind").textContent = "导出失败";
        if (retained && retained.hasPreview) {
          const ctx = getOrCreateDeliverablePreviewContext();
          ctx.hidden = false;
          ctx.textContent = `保留上次查询预览（生成时间：${retained.queryTime} · 筛选条件：${retained.filterSummary}）· 导出失败`;
        }
      } else {
        if (retained && retained.hasPreview) {
          document.getElementById("deliverable-result-kind").textContent = `${DELIVERABLE_OPERATION_LABELS[operation] || operation}失败（保留上次预览）`;
          const ctx = getOrCreateDeliverablePreviewContext();
          ctx.hidden = false;
          ctx.textContent = `保留上次查询预览（生成时间：${retained.queryTime} · 筛选条件：${retained.filterSummary}）· 操作失败`;
        } else {
          document.getElementById("deliverable-result-kind").textContent = `${DELIVERABLE_OPERATION_LABELS[operation] || operation}失败`;
        }
      }
    }
    recordRecentRun(item, operation, "failed", redactSensitiveText(err.message));
    if (requestForm === document.getElementById("deliverable-form")) setDeliverableStatus(operation === "export" ? "导出失败" : "操作失败", false);
  } finally {
    clearDeliverablePayloadSecrets(payload);
    deliverableRunning = false;
  }
}

function trackDeliverableCrawlTask(taskId, seq, item, operation) {
  (async () => {
    const finished = await waitForTaskCompletion(taskId);
    if (seq <= deliverableLatestRendered) return;
    if (!finished) {
      showDeliverableError("后台全量抓取任务长时间未完成，请稍后在「任务」中心查看结果。");
      return;
    }
    if (finished.status === "cancelled") {
      if (document.getElementById("deliverable-form")) setDeliverableStatus("后台全量抓取任务已取消", false);
      return;
    }
    if (finished.status !== "succeeded") {
      showDeliverableError(`后台全量抓取任务失败：${redactSensitiveText(finished.error_message || finished.status)}`);
      return;
    }
    try {
      const result = await fetchTaskResult(taskId);
      if (seq > deliverableLatestRendered) {
        deliverableLatestRendered = seq;
        const capturedContext = {
          hasPreview: true,
          queryTime: new Date().toLocaleString(),
          filterSummary: formatDeliverableFilterSummary(item, {}),
        };
        renderDeliverableResult(result, item, operation, capturedContext);
        recordRecentRun(item, operation, "success", `rows=${(result.rows || []).length}`);
        if (document.getElementById("deliverable-form")) setDeliverableStatus("后台全量抓取完成", false);
      }
    } catch (err) {
      showDeliverableError(redactSensitiveText(err.message));
    }
  })();
}

function openDeliverableInAras(item) {
  const mode = item.target && item.target.mode;
  if (mode) {
    const modeButton = document.querySelector(`[data-aras-mode="${mode}"]`);
    if (modeButton) modeButton.click();
    window.location.hash = `#aras-panel?mode=${encodeURIComponent(mode)}&from=overview`;
  } else {
    window.location.hash = "#aras-panel?from=overview";
  }
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
  const fullHash = window.location.hash || "";
  const rawHash = fullHash.replace(/^#/, "");
  const [hashPath, queryString] = rawHash.split("?");
  const searchParams = new URLSearchParams(queryString || "");

  const archiveDeliverableMatch = rawHash.match(/^archive-deliverable\/([^/?#]+)/);
  const deliverableMatch = rawHash.match(/^(?:overview\/)?deliverables?\/([^/?#]+)/)
    || rawHash.match(/^deliverable-detail\/([^/?#]+)/);
  const detailView = document.getElementById("overview-deliverable-detail-view");
  if (detailView && detailView.dataset) detailView.dataset.formViewOwner = "";

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

  // Determine normalized target panelId
  let panelId = hashPath || "overview";
  if (panelId === "dashboard") {
    panelId = "overview";
  } else if (panelId === "aras" || panelId === "system-query" || panelId === "query") {
    panelId = "aras-panel";
  } else if (panelId === "archive" || panelId === "scheduled") {
    panelId = "scheduled-archive";
  } else if (panelId === "settings") {
    panelId = "settings-panel";
  } else if (panelId === "excel") {
    panelId = "excel-tasks";
  }

  if (panelId === "overview" || panelId === "overview-status-panel" || panelId === "overview-details-panel" || panelId === "overview-plan-panel") {
    const listView = document.getElementById("overview-deliverables-list-view");
    const detailView = document.getElementById("overview-deliverable-detail-view");
    if (listView) listView.hidden = false;
    if (detailView) {
      detailView.hidden = true;
      if (detailView.dataset) detailView.dataset.formViewOwner = "";
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

    // Handle deep linking for overview sub-tabs
    const reqTab = searchParams.get("tab");
    const isPlan = reqTab === "plan" || panelId === "overview-plan-panel";
    const isDetails = reqTab === "details" || panelId === "overview-details-panel";
    const detailsTab = document.getElementById("overview-tab-details");
    const statusTab = document.getElementById("overview-tab-status");
    const planTab = document.getElementById("overview-tab-plan");
    const detailsPanel = document.getElementById("overview-details-panel");
    const statusPanel = document.getElementById("overview-status-panel");
    const planPanel = document.getElementById("overview-plan-panel");
    if (detailsTab && detailsPanel && statusTab && statusPanel && planTab && planPanel) {
      statusTab.classList.toggle("active", !isPlan && !isDetails);
      statusTab.setAttribute("aria-selected", (!isPlan && !isDetails) ? "true" : "false");
      statusTab.tabIndex = (!isPlan && !isDetails) ? 0 : -1;
      statusPanel.hidden = isPlan || isDetails;

      detailsTab.classList.toggle("active", isDetails);
      detailsTab.setAttribute("aria-selected", isDetails ? "true" : "false");
      detailsTab.tabIndex = isDetails ? 0 : -1;
      detailsPanel.hidden = !isDetails;

      planTab.classList.toggle("active", isPlan);
      planTab.setAttribute("aria-selected", isPlan ? "true" : "false");
      planTab.tabIndex = isPlan ? 0 : -1;
      planPanel.hidden = !isPlan;
    }
    return;
  }

  const targetLink = document.querySelector(`[data-panel-link="${panelId}"]`);
  document.querySelectorAll("[data-panel-link]").forEach((item) => item.classList.remove("active"));
  if (targetLink) {
    targetLink.classList.add("active");
  }
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
    ? "系统查询"
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

  if (isAras) {
    // Deep linking: switch mode if requested
    const reqMode = searchParams.get("mode");
    if (reqMode && ARAS_MODES[reqMode]) {
      const modeBtn = document.querySelector(`[data-aras-mode="${reqMode}"]`);
      if (modeBtn && !modeBtn.classList.contains("active")) {
        modeBtn.click();
      }
    } else if (reqMode === "tdc-sor" || reqMode === "tdc_sor" || reqMode === "sor") {
      window.location.hash = `#overview/deliverables/VPI-T2-D2${queryString ? "?" + queryString : ""}`;
      return;
    } else if (reqMode === "tdc-data-model" || reqMode === "tdc_data_model") {
      window.location.hash = `#overview/deliverables/VPI-T2-D5${queryString ? "?" + queryString : ""}`;
      return;
    }

    // Deep linking: fill query identifier if provided
    const ewoParam = searchParams.get("ewo_no");
    const paaParam = searchParams.get("paa_no");
    const ncrParam = searchParams.get("ncr_no") || searchParams.get("ncrNo");
    const genericParam = searchParams.get("no") || searchParams.get("id");
    const queryVal = (arasMode === "ewo" ? ewoParam : arasMode === "paa" ? paaParam : ncrParam) || genericParam;

    if (queryVal) {
      if (arasMode === "ewo") {
        const input = document.querySelector('#aras-form input[name="ewo_no"]');
        if (input) { input.value = queryVal; input.dispatchEvent(new Event("input")); }
      } else if (arasMode === "paa") {
        const input = document.querySelector('#aras-form input[name="paa_no"]')
          || document.querySelector('#aras-form input[name="item_id"]')
          || document.querySelector('#aras-form input[name="program"]');
        if (input) { input.value = queryVal; input.dispatchEvent(new Event("input")); }
      } else if (arasMode === "ncr-progress" || arasMode === "ncr-detail") {
        const input = document.querySelector('#aras-form input[name="ncr_no"]');
        if (input) { input.value = queryVal; input.dispatchEvent(new Event("input")); }
      }
    }

    // Deep linking: return-to-origin link
    const fromOrigin = searchParams.get("from");
    let backBar = document.getElementById("aras-deep-link-back-bar");
    if (fromOrigin === "overview") {
      if (!backBar) {
        backBar = document.createElement("div");
        backBar.id = "aras-deep-link-back-bar";
        backBar.className = "deep-link-back-bar";
        const arasHead = document.querySelector("#aras-panel .aras-head");
        if (arasHead && arasHead.parentNode) {
          arasHead.parentNode.insertBefore(backBar, arasHead);
        }
      }
      backBar.hidden = false;
      const backBtn = document.createElement("button");
      backBtn.type = "button";
      backBtn.className = "back-link-btn";
      backBtn.id = "aras-back-to-overview-btn";
      backBtn.textContent = "← 返回项目看板";
      backBtn.addEventListener("click", () => {
        window.location.hash = "#overview";
      });
      const children = [backBtn];
      if (queryVal) {
        const hintSpan = document.createElement("span");
        hintSpan.className = "deep-link-hint";
        hintSpan.textContent = `穿透查询单号：${queryVal}`;
        children.push(hintSpan);
      }
      backBar.replaceChildren(...children);
    } else if (backBar) {
      backBar.hidden = true;
    }
  }

  if (isDeliverables) loadDeliverablesCatalog();
  if (isExcel) loadExcelTaskWorkspace();
  if (isArchive) loadArchiveJobs();
  if (isSettings) loadSettings();
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
    if (excelTasks.length === 0) {
      listNode.className = "excel-task-list is-empty";
      listNode.textContent = "获取处理记录失败，请点击上方【刷新】重试";
      renderEmptyExcelTaskDetail();
    }
    excelShowError(error instanceof Error ? error.message : String(error));
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
    listNode.textContent = "暂无处理记录。您可在上方选择操作类型并点击【开始处理】创建任务。";
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
let archiveRunsLoading = false;
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
    { name: "projectModel", label: "车型项目" },
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
    { name: "projectCode", label: "车型项目" },
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
    { name: "vehicleKeyword", label: "车型项目" },
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

// 车型项目类筛选字段的占位符与「主计划维护 → 主计划名称」保持一致
// （需求 2026-09-06）：占位符动态显示当前主计划名称，改名后自动跟随。
const ARCHIVE_PROJECT_FILTER_KEYS = new Set([
  "projectModel",
  "carTypeProject",
  "projectCode",
  "vehicleKeyword",
]);
let archivePlanNameCache = null;

function invalidateArchivePlanNameCache() {
  archivePlanNameCache = null;
}

async function applyArchivePlanNameSync(controls, job) {
  try {
    if (archivePlanNameCache === null) {
      // 优先复用概览页已加载的主计划名称，避免冗余请求与预填竞态。
      const fromState = overviewSavedState
        && overviewSavedState.phase
        && overviewSavedState.phase.displayName;
      if (fromState) {
        archivePlanNameCache = String(fromState).trim();
      } else {
        const response = await fetch("/api/project-status?phase=VPI-T2", {
          headers: { Accept: "application/json" },
        });
        const body = response.ok ? await response.json() : null;
        archivePlanNameCache = body && body.ok
          ? String(body.data.phase.displayName || "").trim()
          : "";
      }
    }
  } catch (error) {
    archivePlanNameCache = "";
  }
  if (!archivePlanNameCache) return;
  controls.querySelectorAll("[data-archive-filter-name]").forEach((input) => {
    const key = input.dataset.archiveFilterName;
    if (!ARCHIVE_PROJECT_FILTER_KEYS.has(key)) return;
    input.placeholder = "支持 * 模糊和 | 并集";
    input.title = "默认与主计划名称同步；支持 * 模糊和 | 并集";
    // 默认值与主计划名称同步：任务已显式配置（含显式清空）时以配置为准。
    // 默认值与主计划名称同步：任务已显式配置（键存在，含显式清空为
    // 空串）时以配置为准；仅缺键时预填当前主计划名称。
    const filters = job.filters || {};
    const hasExplicitValue =
      key in filters && filters[key] !== null && filters[key] !== undefined;
    if (!hasExplicitValue && !input.value.trim()) {
      input.value = archivePlanNameCache;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
  });
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
  applyArchivePlanNameSync(controls, job);
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
    await ensureSettingsData();
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
  // 未配置凭据且凭据保护库可用时默认预选统一域账号，省去每次手动选择；
  // 已配置的任务保持「保持当前登录信息」默认，避免重复提交凭据引用。
  const vaultConfigured = settingsData !== null && settingsData.credentialVaultConfigured === true;
  if (!job.credentialConfigured && vaultConfigured) {
    aliasInput.value = "domain";
  }
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
    // write-only 语义：保存成功后清空凭据引用输入。
    // 失败路径没有重渲染，这里恢复用户本次提交的选择；未选择时才回填预选默认。
    if (aliasInput) {
      const vaultConfigured = settingsData !== null && settingsData.credentialVaultConfigured === true;
      aliasInput.value = aliasVal
        || (!job.credentialConfigured && vaultConfigured ? "domain" : "");
    }
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
    // 立即下载可能发布新的表单快照，同步刷新概览环图数据。
    await loadProjectOverview();
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
  if (!container || archiveRunsLoading) return;
  archiveRunsLoading = true;
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
      container.appendChild(archiveEl("p", "is-empty", `${(body.error && body.error.message) || "获取下载记录失败"}（后台归档不受影响，可点击刷新重试）`));
      return;
    }
    const runs = Array.isArray(body.data) ? body.data : [];
    renderArchiveRunsList(runs);
  } catch (_e) {
    clearArchiveContainer(container);
    container.appendChild(archiveEl("p", "is-empty", "获取下载记录失败（后台归档不受影响，可点击刷新重试）"));
  } finally {
    archiveRunsLoading = false;
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
      const ctx = document.getElementById("aras-preview-context");
      if (ctx) {
        ctx.hidden = true;
        ctx.textContent = "";
      }
      arasHasRenderedResult = false;
      arasLatestRendered = 0;
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

// 归档工作台等面板在未打开系统设置时也需要凭据库状态；
// 读取失败按未配置处理，不影响任务列表加载。
async function ensureSettingsData() {
  if (settingsData !== null) return settingsData;
  try {
    const resp = await fetch("/api/settings", {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const body = await resp.json();
    if (resp.ok && body && body.ok) settingsData = body.data || {};
  } catch (_err) {
    return null;
  }
  return settingsData;
}

function showSettingsGlobalError(message, options = {}) {
  const el = document.getElementById("settings-global-error");
  if (!el) return;
  if (!message) {
    el.hidden = true;
    el.innerHTML = "";
    return;
  }
  if (isAuthError(message, options.status)) {
    renderStructuredErrorCard(el, {
      summary: "企业认证会话已失效",
      impact: "本地系统设置未受影响，但企业会话需要重新验证。",
      actions: [
        {
          label: "重新登录",
          primary: true,
          action: () => openInPlaceLogin({
            notice: "企业会话已失效，请重新登录企业域账号。",
            onLoginSuccess: () => loadSettings(),
          }),
        },
      ],
      technical: message,
    });
  } else {
    renderStructuredErrorCard(el, {
      summary: "系统设置操作未成功",
      impact: "表单中已输入的内容已完整保留，未覆盖未修改的配置项。",
      actions: [
        {
          label: "重试保存",
          primary: true,
          action: () => {
            el.hidden = true;
            el.innerHTML = "";
            const form = document.getElementById("settings-form");
            if (form) form.dispatchEvent(new Event("submit", { cancelable: true }));
          },
        },
        {
          label: "重新加载设置",
          primary: false,
          action: () => loadSettings(),
        },
      ],
      technical: message,
    });
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

  // 5. 更新顶栏全局会话状态指示
  updateGlobalSessionBadges(sessions);
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

/* ── 顶栏全局会话状态指示 ────────────────────────────────────────── */

function updateGlobalSessionBadges(sessions = {}) {
  const aras = sessions.aras || {};
  const tdc = sessions.tdc || {};
  const arasBadge = document.getElementById("global-badge-aras");
  const arasText = document.getElementById("global-badge-aras-text");
  const tdcBadge = document.getElementById("global-badge-tdc");
  const tdcText = document.getElementById("global-badge-tdc-text");

  if (arasBadge && arasText) {
    const isAuth = Boolean(aras.authenticated);
    const isExp = Boolean(aras.expired);
    arasBadge.className = "session-badge " + (isAuth ? "is-authenticated" : (isExp ? "is-expired" : "is-unknown"));
    arasText.textContent = isAuth ? "已认证" : (isExp ? "已过期" : "未认证");
    arasBadge.title = `Aras ECM 会话：${isAuth ? "有效" : (isExp ? "已过期（需重新登录）" : "未认证")}`;
  }

  if (tdcBadge && tdcText) {
    const isAuth = Boolean(tdc.authenticated);
    const isExp = Boolean(tdc.expired);
    tdcBadge.className = "session-badge " + (isAuth ? "is-authenticated" : (isExp ? "is-expired" : "is-unknown"));
    tdcText.textContent = isAuth ? "已认证" : (isExp ? "已过期" : "未认证");
    tdcBadge.title = `TDC 研发流程会话：${isAuth ? "有效" : (isExp ? "已过期（需重新登录）" : "未认证")}`;
  }
}

/* ── 版本检测与维护详情弹窗 ───────────────────────────────────────── */

let appVersionData = null;

async function loadAppVersion() {
  try {
    const resp = await fetch("/api/version", { cache: "no-store" });
    const body = await resp.json();
    if (resp.ok && body.ok && body.data) {
      appVersionData = body.data;
      const chip = document.getElementById("app-version-chip");
      if (chip) {
        chip.textContent = appVersionData.displayVersion || "开发工作区";
        chip.title = `应用版本: ${appVersionData.displayVersion} · 点击查看运行环境详情`;
      }
    }
  } catch (_) {
    // 无法获取版本时安全退化，保留默认展示
  }
}

function openVersionDetailModal() {
  const modal = document.getElementById("version-detail-modal");
  if (!modal) return;
  const data = appVersionData || {
    displayVersion: "开发工作区",
    channel: "source",
    buildId: null,
    detail: "开发工作区 (源码运行)",
  };
  const valDisplay = document.getElementById("version-val-display");
  const valChannel = document.getElementById("version-val-channel");
  const valBuild = document.getElementById("version-val-build");
  const valDetail = document.getElementById("version-val-detail");

  if (valDisplay) valDisplay.textContent = data.displayVersion || "-";
  if (valChannel) valChannel.textContent = data.channel || "source";
  if (valBuild) valBuild.textContent = data.buildId || "无独立构建标识";
  if (valDetail) valDetail.textContent = data.detail || "-";
  modal.hidden = false;
}

function closeVersionDetailModal() {
  const modal = document.getElementById("version-detail-modal");
  if (modal) modal.hidden = true;
  document.getElementById("app-version-chip")?.focus();
}

function setupVersionModal() {
  const chip = document.getElementById("app-version-chip");
  if (chip) {
    chip.addEventListener("click", openVersionDetailModal);
    chip.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openVersionDetailModal();
      }
    });
  }

  const closeBtn = document.getElementById("version-detail-close-btn");
  if (closeBtn) closeBtn.addEventListener("click", closeVersionDetailModal);

  const backdrop = document.getElementById("version-detail-backdrop");
  if (backdrop) backdrop.addEventListener("click", closeVersionDetailModal);
}

/* ── 原位域登录弹窗（保留现场与显式继续操作） ─────────────────────── */

let inPlaceLoginState = {
  isOpen: false,
  triggerElement: null,
  onLoginSuccess: null,
};

function openInPlaceLogin(options = {}) {
  const modal = document.getElementById("in-place-login-modal");
  if (!modal) return;
  inPlaceLoginState.triggerElement = document.activeElement;
  inPlaceLoginState.onLoginSuccess = options.onLoginSuccess || null;
  inPlaceLoginState.isOpen = true;

  const noticeEl = document.getElementById("in-place-login-notice");
  if (noticeEl) {
    if (options.notice) {
      noticeEl.textContent = options.notice;
      noticeEl.hidden = false;
    } else {
      noticeEl.hidden = true;
      noticeEl.textContent = "";
    }
  }

  const statusEl = document.getElementById("in-place-login-status");
  if (statusEl) statusEl.textContent = "";

  const passInput = document.getElementById("in-place-login-password");
  if (passInput) passInput.value = "";

  const vaultCheck = document.getElementById("in-place-login-save-vault");
  if (vaultCheck) vaultCheck.checked = false; // 严禁默认勾选，明确隔离定时下载授权

  modal.hidden = false;
  const userInput = document.getElementById("in-place-login-username");
  if (userInput) {
    if (userInput.value.trim()) {
      passInput?.focus();
    } else {
      userInput.focus();
    }
  }
}

function closeInPlaceLogin() {
  const modal = document.getElementById("in-place-login-modal");
  if (!modal) return;
  modal.hidden = true;
  inPlaceLoginState.isOpen = false;
  const passInput = document.getElementById("in-place-login-password");
  if (passInput) passInput.value = "";
  if (inPlaceLoginState.triggerElement && typeof inPlaceLoginState.triggerElement.focus === "function") {
    try { inPlaceLoginState.triggerElement.focus(); } catch (_) {}
  }
  inPlaceLoginState.triggerElement = null;
  inPlaceLoginState.onLoginSuccess = null;
}

async function handleInPlaceLoginSubmit(e) {
  e.preventDefault();
  const status = document.getElementById("in-place-login-status");
  const btn = document.getElementById("in-place-login-submit-btn");
  const userInput = document.getElementById("in-place-login-username");
  const passInput = document.getElementById("in-place-login-password");
  const vaultCheck = document.getElementById("in-place-login-save-vault");

  const username = (userInput?.value || "").trim();
  const password = passInput?.value || "";
  const saveForScheduled = Boolean(vaultCheck && vaultCheck.checked);

  if (!username || !password) {
    if (status) status.textContent = "域用户名和密码不能为空";
    return;
  }

  if (btn) btn.disabled = true;
  if (status) status.textContent = "正在进行企业域认证登录...";

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
    if (body.data && body.data.sessions) {
      updateGlobalSessionBadges(body.data.sessions);
    }
    await loadSettings();

    const callback = inPlaceLoginState.onLoginSuccess;
    setTimeout(() => {
      closeInPlaceLogin();
      if (typeof callback === "function") {
        callback(body.data);
      }
    }, 250);
  } catch (err) {
    if (status) {
      status.textContent = `登录失败：${redactSensitiveText(err instanceof Error ? err.message : String(err))}`;
    }
  } finally {
    if (passInput) passInput.value = "";
    if (btn) btn.disabled = false;
  }
}

function setupInPlaceLogin() {
  const form = document.getElementById("in-place-login-form");
  if (form) form.addEventListener("submit", handleInPlaceLoginSubmit);

  const closeBtn = document.getElementById("in-place-login-close-btn");
  if (closeBtn) closeBtn.addEventListener("click", closeInPlaceLogin);

  const cancelBtn = document.getElementById("in-place-login-cancel-btn");
  if (cancelBtn) cancelBtn.addEventListener("click", closeInPlaceLogin);

  const backdrop = document.getElementById("in-place-login-backdrop");
  if (backdrop) backdrop.addEventListener("click", closeInPlaceLogin);

  const globalLoginBtn = document.getElementById("global-login-btn");
  if (globalLoginBtn) {
    globalLoginBtn.addEventListener("click", () => {
      openInPlaceLogin({ notice: "请输入企业域账号登录；成功后将更新当前会话状态。" });
    });
  }

  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (inPlaceLoginState.isOpen) {
        closeInPlaceLogin();
      }
      const versionModal = document.getElementById("version-detail-modal");
      if (versionModal && !versionModal.hidden) {
        closeVersionDetailModal();
      }
    }
  });
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

function setupTaskCenterDrawer() {
  const taskCenterBtn = document.getElementById("task-center-btn");
  const taskCenterBadge = document.getElementById("task-center-badge");
  const drawerContainer = document.getElementById("task-center-drawer-container");
  const drawerBackdrop = document.getElementById("task-center-backdrop");
  const closeBtn = document.getElementById("task-drawer-close-btn");
  const refreshBtn = document.getElementById("task-drawer-refresh-btn");
  const itemsContainer = document.getElementById("task-drawer-items");
  const loadingElem = document.getElementById("task-drawer-loading");
  const emptyElem = document.getElementById("task-drawer-empty");
  const activeCountChip = document.getElementById("task-drawer-active-count");
  const tabActive = document.getElementById("task-tab-active");
  const tabHistory = document.getElementById("task-tab-history");
  const tabAll = document.getElementById("task-tab-all");
  const tabActiveCount = document.getElementById("task-tab-active-count");
  const tabHistoryCount = document.getElementById("task-tab-history-count");

  if (!taskCenterBtn || !drawerContainer) {
    return;
  }

  let isDrawerOpen = false;
  let taskPollTimer = null;
  let closeTimer = null;
  let activeTaskCount = 0;
  let currentFilter = "active";
  let cachedTasks = [];
  let isFetching = false;

  function formatTimeAgo(isoString) {
    if (!isoString) return "";
    try {
      const created = new Date(isoString).getTime();
      if (isNaN(created)) return "";
      const diffSec = Math.max(0, Math.floor((Date.now() - created) / 1000));
      if (diffSec < 60) return `${diffSec}秒前`;
      const diffMin = Math.floor(diffSec / 60);
      if (diffMin < 60) return `${diffMin}分钟前`;
      const diffHour = Math.floor(diffMin / 60);
      return `${diffHour}小时前`;
    } catch {
      return "";
    }
  }

  function formatElapsed(task) {
    if (!task || !task.created_at) return "";
    try {
      const start = new Date(task.created_at).getTime();
      if (isNaN(start)) return "";
      const isActive = task.is_active || ["queued", "leased", "running", "generating", "downloading"].includes(task.status);
      const end = isActive ? Date.now() : (task.updated_at ? new Date(task.updated_at).getTime() : Date.now());
      const diffSec = Math.max(0, Math.floor((end - start) / 1000));
      let timeStr = "";
      if (diffSec < 60) {
        timeStr = `${diffSec}秒`;
      } else {
        const m = Math.floor(diffSec / 60);
        const s = diffSec % 60;
        timeStr = s > 0 ? `${m}分${s}秒` : `${m}分钟`;
      }
      return isActive ? `已运行 ${timeStr}` : `耗时 ${timeStr}`;
    } catch {
      return "";
    }
  }

  function getStatusLabel(status) {
    switch (status) {
      case "queued": return "排队中";
      case "running": return "运行中";
      case "leased": return "执行中";
      case "generating": return "生成中";
      case "downloading": return "下载中";
      case "succeeded":
      case "parsed":
      case "generated": return "已完成";
      case "failed": return "失败";
      case "interrupted": return "已中断";
      case "cancelled": return "已取消";
      default: return status;
    }
  }

  function getStatusClass(status) {
    switch (status) {
      case "queued": return "is-queued";
      case "running":
      case "leased":
      case "generating":
      case "downloading": return "is-running";
      case "succeeded":
      case "parsed":
      case "generated": return "is-succeeded";
      case "failed":
      case "interrupted": return "is-failed";
      case "cancelled": return "is-cancelled";
      default: return "is-queued";
    }
  }

  function renderTasks(tasks, filter) {
    if (!itemsContainer) return;
    itemsContainer.replaceChildren();

    const filtered = tasks.filter((t) => {
      const isActive = t.is_active || ["queued", "leased", "running", "generating", "downloading"].includes(t.status);
      if (filter === "active") return isActive;
      if (filter === "history") return !isActive;
      return true;
    });

    if (filtered.length === 0) {
      if (emptyElem) emptyElem.removeAttribute("hidden");
      return;
    }

    if (emptyElem) emptyElem.setAttribute("hidden", "true");

    filtered.forEach((task) => {
      const card = document.createElement("div");
      card.className = "task-card";

      // Header
      const header = document.createElement("div");
      header.className = "task-card-header";

      const titleGroup = document.createElement("div");
      titleGroup.className = "task-card-title-group";

      const title = document.createElement("h4");
      title.className = "task-card-title";
      title.textContent = task.title || task.id;
      titleGroup.appendChild(title);

      const meta = document.createElement("div");
      meta.className = "task-card-meta";

      const timeSpan = document.createElement("span");
      timeSpan.textContent = formatTimeAgo(task.created_at);
      meta.appendChild(timeSpan);

      const elapsed = formatElapsed(task);
      if (elapsed) {
        const elapsedSpan = document.createElement("span");
        elapsedSpan.textContent = elapsed;
        meta.appendChild(elapsedSpan);
      }

      const categorySpan = document.createElement("span");
      categorySpan.textContent = (task.category || "crawl").toUpperCase();
      meta.appendChild(categorySpan);

      titleGroup.appendChild(meta);
      header.appendChild(titleGroup);

      const statusChip = document.createElement("span");
      statusChip.className = `task-status-chip ${getStatusClass(task.status)}`;
      statusChip.textContent = getStatusLabel(task.status);
      header.appendChild(statusChip);

      card.appendChild(header);

      // Progress bar if active or progress available
      const isActive = task.is_active || ["queued", "leased", "running", "generating", "downloading"].includes(task.status);
      if (isActive && task.progress && Object.keys(task.progress).length > 0) {
        const progWrap = document.createElement("div");
        progWrap.className = "task-progress-wrap";

        const barBg = document.createElement("div");
        barBg.className = "task-progress-bar-bg";

        const barFill = document.createElement("div");
        barFill.className = "task-progress-bar-fill";
        const pct = task.progress.percent != null ? task.progress.percent : 0;
        barFill.style.width = `${pct}%`;
        barBg.appendChild(barFill);
        progWrap.appendChild(barBg);

        const progText = document.createElement("div");
        progText.className = "task-progress-text";

        const stageSpan = document.createElement("span");
        stageSpan.textContent = task.progress.stage || (task.status === "queued" ? "等待资源执行..." : "正在处理中...");
        progText.appendChild(stageSpan);

        const pctSpan = document.createElement("span");
        pctSpan.textContent = `${pct}%`;
        progText.appendChild(pctSpan);

        progWrap.appendChild(progText);
        card.appendChild(progWrap);
      }

      // Error message
      if (task.error_message) {
        const errBox = document.createElement("div");
        errBox.className = "task-error-box";
        errBox.textContent = task.error_message;
        card.appendChild(errBox);
      }

      // W3-3 冻结重试语义：generation_unknown 仅允许人工核查
      if (task.manual_check_required) {
        const notice = document.createElement("div");
        notice.className = "task-error-box task-manual-check-note";
        notice.textContent = "生成结果未知：禁止自动重发，请在 EWO 增强导表面板进行状态人工核查。";
        card.appendChild(notice);
      }

      // Actions
      const actions = document.createElement("div");
      actions.className = "task-card-actions";

      if (task.can_cancel) {
        const cancelBtn = document.createElement("button");
        cancelBtn.className = "task-action-btn btn-cancel";
        cancelBtn.type = "button";
        cancelBtn.textContent = "取消任务";
        cancelBtn.addEventListener("click", async () => {
          cancelBtn.disabled = true;
          cancelBtn.textContent = "正在取消...";
          try {
            const resp = await fetch(`/api/tasks/${encodeURIComponent(task.id)}/cancel`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
            });
            if (resp.ok) {
              await fetchTasks();
            } else {
              const err = await resp.json().catch(() => ({}));
              alert(`取消失败: ${err?.error?.message || "网络异常"}`);
              cancelBtn.disabled = false;
              cancelBtn.textContent = "取消任务";
            }
          } catch (e) {
            cancelBtn.disabled = false;
            cancelBtn.textContent = "取消任务";
          }
        });
        actions.appendChild(cancelBtn);
      }

      if (task.can_retry) {
        const retryBtn = document.createElement("button");
        retryBtn.className = "task-action-btn btn-retry";
        retryBtn.type = "button";
        retryBtn.textContent = "重试任务";
        retryBtn.addEventListener("click", async () => {
          retryBtn.disabled = true;
          retryBtn.textContent = "正在提交重试...";
          try {
            const resp = await fetch(`/api/tasks/${encodeURIComponent(task.id)}/retry`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
            });
            if (resp.ok) {
              await fetchTasks();
            } else {
              const err = await resp.json().catch(() => ({}));
              alert(`重试失败: ${err?.error?.message || "网络异常"}`);
              retryBtn.disabled = false;
              retryBtn.textContent = "重试任务";
            }
          } catch (e) {
            retryBtn.disabled = false;
            retryBtn.textContent = "重试任务";
          }
        });
        actions.appendChild(retryBtn);
      }

      if (task.has_artifact) {
        const viewLink = document.createElement("a");
        viewLink.className = "task-action-btn btn-view";
        viewLink.href = `/api/tasks/${encodeURIComponent(task.id)}/download`;
        viewLink.target = "_blank";
        viewLink.textContent = "查看结果";
        actions.appendChild(viewLink);
      }

      if (task.can_download) {
        const downloadLink = document.createElement("a");
        downloadLink.className = "task-action-btn btn-download";
        downloadLink.href = `/api/tasks/${encodeURIComponent(task.id)}/download`;
        downloadLink.download = "";
        downloadLink.textContent = "下载工件";
        actions.appendChild(downloadLink);
      }

      if (actions.children.length > 0) {
        card.appendChild(actions);
      }

      itemsContainer.appendChild(card);
    });
  }

  async function fetchTasks() {
    if (isFetching) return;
    isFetching = true;

    try {
      const resp = await fetch("/api/tasks?limit=100");
      if (!resp.ok) return;
      const json = await resp.json();
      if (!json.ok || !json.data) return;

      cachedTasks = json.data.tasks || [];
      activeTaskCount = json.data.active_count || 0;

      // Update badge
      if (taskCenterBadge) {
        if (activeTaskCount > 0) {
          taskCenterBadge.textContent = String(activeTaskCount);
          taskCenterBadge.removeAttribute("hidden");
        } else {
          taskCenterBadge.textContent = "0";
          taskCenterBadge.setAttribute("hidden", "true");
        }
      }

      // Update active chip & tab counts
      const activeList = cachedTasks.filter((t) =>
        t.is_active || ["queued", "leased", "running", "generating", "downloading"].includes(t.status)
      );
      const historyList = cachedTasks.filter((t) => !activeList.includes(t));

      if (activeCountChip) {
        activeCountChip.textContent = `${activeList.length} 项进行中`;
      }
      if (tabActiveCount) {
        tabActiveCount.textContent = String(activeList.length);
      }
      if (tabHistoryCount) {
        tabHistoryCount.textContent = String(historyList.length);
      }

      if (loadingElem) {
        loadingElem.setAttribute("hidden", "true");
      }

      if (isDrawerOpen) {
        renderTasks(cachedTasks, currentFilter);
      }

      // Adaptive polling control
      if (!isDrawerOpen && activeTaskCount === 0) {
        stopAdaptivePolling();
      } else {
        startAdaptivePolling();
      }
    } catch (err) {
      console.warn("fetchTasks error:", err);
    } finally {
      isFetching = false;
    }
  }

  function startAdaptivePolling() {
    if (!taskPollTimer) {
      taskPollTimer = setInterval(fetchTasks, 1500);
    }
  }

  function stopAdaptivePolling() {
    if (taskPollTimer) {
      clearInterval(taskPollTimer);
      taskPollTimer = null;
    }
  }

  function openDrawer() {
    if (closeTimer) {
      clearTimeout(closeTimer);
      closeTimer = null;
    }
    isDrawerOpen = true;
    drawerContainer.removeAttribute("hidden");
    requestAnimationFrame(() => {
      drawerContainer.classList.add("is-open");
    });
    if (loadingElem) loadingElem.removeAttribute("hidden");
    fetchTasks();
    startAdaptivePolling();
  }

  function closeDrawer() {
    isDrawerOpen = false;
    drawerContainer.classList.remove("is-open");
    if (closeTimer) clearTimeout(closeTimer);
    closeTimer = setTimeout(() => {
      if (!isDrawerOpen) {
        drawerContainer.setAttribute("hidden", "true");
      }
      closeTimer = null;
    }, 250);

    if (activeTaskCount === 0) {
      stopAdaptivePolling();
    }
  }

  // Event Listeners
  taskCenterBtn.addEventListener("click", () => {
    if (isDrawerOpen) {
      closeDrawer();
    } else {
      openDrawer();
    }
  });

  if (closeBtn) closeBtn.addEventListener("click", closeDrawer);
  if (drawerBackdrop) drawerBackdrop.addEventListener("click", closeDrawer);

  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
      fetchTasks();
    });
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && isDrawerOpen) {
      closeDrawer();
    }
  });

  // Tab switching
  [tabActive, tabHistory, tabAll].forEach((tab) => {
    if (!tab) return;
    tab.addEventListener("click", () => {
      [tabActive, tabHistory, tabAll].forEach((t) => {
        if (t) {
          t.classList.remove("active");
        }
      });
      tab.classList.add("active");
      currentFilter = tab.getAttribute("data-filter") || "active";
      renderTasks(cachedTasks, currentFilter);
    });
  });

  // Phase 3: 面板提交后台任务后唤醒轮询（角标实时反映新增任务）
  document.addEventListener("vse:task-center-kick", () => {
    fetchTasks();
    startAdaptivePolling();
  });

  // Initial fetch on page load
  fetchTasks();
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
  loadAppVersion();
  setupVersionModal();
  setupInPlaceLogin();
  setupTaskCenterDrawer();
  loadSettings();
});
