// Pure helpers for the deliverables catalog page (no DOM, no Preact).
// Ported from the legacy app.js deliverable workbench (collectDeliverablePayload,
// visibleDeliverables, formatDeliverableFilterSummary, recordRecentRun, …) and
// copied from the system-query plugin's lib.js for redaction, errors, task and
// grid helpers (plugins never import each other).

// ── 常量（旧页面 DELIVERABLE_* / TDC_ENDPOINTS） ─────────────────────────

export const STATUS_LABELS = {
  "已完整实现": "已完整实现",
  "后端已实现、前端缺失": "后端已实现、前端缺失",
  "部分实现": "部分实现",
  "仅占位": "仅占位",
  "仅文档规划": "仅文档规划",
  "未发现实现证据": "未发现实现证据",
};

export const STATUS_TONE_CLASS = {
  "已完整实现": "is-fully-implemented",
  "后端已实现、前端缺失": "is-backend-no-frontend",
  "部分实现": "is-partial",
  "仅占位": "is-placeholder",
  "仅文档规划": "is-doc-only",
  "未发现实现证据": "is-no-evidence",
};

export const AVAILABILITY_LABELS = {
  available: "可用",
  cli_only: "仅 CLI",
  partial: "部分可用",
  disabled: "已禁用",
};

export const OPERATION_LABELS = {
  query: "查询预览",
  crawl_all: "全量抓取",
  export: "导出 XLSX",
  download: "生成并下载",
  cli: "CLI",
};

export const TDC_ENDPOINTS = {
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

export const CATALOG_ENDPOINT = "/api/deliverables/catalog";
export const CAR_TYPE_PROJECTS_ENDPOINT = "/api/tdc/sor/car-type-projects";
export const TDC_DEFAULT_BASE_URL = "https://tdc.sgmw.com.cn";
export const RECENT_RUN_LIMIT = 8;
export const PAGE_HASH = "#p/deliverables/catalog";
export const SYSTEM_QUERY_HASH = "#p/system-query/query";
export const LOCAL_ONLY_MESSAGE = "该操作只允许在本机浏览器中执行";

export const PREVIEW_SOURCES = [
  { value: "list_endpoint", label: "快速查询（list 接口）" },
  { value: "official_export", label: "官方 Excel 精确预览（较慢）" },
];

/** Operation-control fields: which operation shows (and validates) each. */
export const OPERATION_FIELDS = [
  { name: "page", label: "页码", type: "number", defaultValue: "1", operations: ["query"] },
  { name: "page_size", label: "每页条数", type: "number", defaultValue: "50", operations: ["query", "crawl_all"] },
  { name: "max_pages", label: "最大页数", type: "number", defaultValue: "100", operations: ["crawl_all"] },
  { name: "max_records", label: "最大记录数", type: "number", defaultValue: "10000", operations: ["crawl_all"] },
];

// ── 敏感信息（与旧页面 SENSITIVE_COLUMNS / SENSITIVE_VALUE_PATTERNS 一致） ──

export const SENSITIVE_COLUMNS = new Set([
  "raw_xml", "file_id", "authorization", "set-cookie", "cookie", "token", "api_key",
  "sid", "sessionid", "arasauth", "jsessionid", "csrf", "secret", "password",
]);

const SENSITIVE_VALUE_PATTERNS = [
  [/(['"])(authorization|set-cookie|cookie|token|api_key|sid|sessionid|arasauth|jsessionid|csrf|secret|password)\1\s*:\s*(['"])(?:\\.|(?!\3)[\s\S])*\3/gi, "$1$2$1:$3[redacted]$3"],
  [/\b(authorization)\b(\s*[:=]\s*)(.*?)(?=(?:\s|,\s*)\b(?:set-cookie|cookie|token|api_key|sid|sessionid|arasauth|jsessionid|csrf|secret|password)\b\s*[:=]|[\r\n}\]\[]|$)/gi, "$1$2[redacted]"],
  [/\b(set-cookie|cookie)\b(\s*[:=]\s*)(.*?)(?=(?:\s|,\s*)\b(?:authorization|set-cookie|cookie)\b\s*:|[\r\n}\]\[]|$)/gi, "$1$2[redacted]"],
  [/\b(token|api_key|sid|sessionid|arasauth|jsessionid|csrf|secret|password)\b(\s*[:=]\s*)(?:Bearer\s+)?([^,\s;'"}}\]\[]+)/gi, "$1$2[redacted]"],
  [/\b(authorization|cookie|token|api_key|sid|sessionid|arasauth|jsessionid|csrf|secret|password)=([^&\s,;'"}}\]\[]+)/gi, "$1=[redacted]"],
  [/\bBearer\s+([^,\s;'"}}\]\[]+)/gi, "Bearer [redacted]"],
];

function localRedact(value) {
  let out = value === null || value === undefined ? "" : String(value);
  SENSITIVE_VALUE_PATTERNS.forEach(([pattern, replacement]) => {
    out = out.replace(pattern, replacement);
  });
  return out;
}

/** Local patterns first, then the host's window.redactSensitiveText when present. */
export function redactSensitiveText(value) {
  let out = localRedact(value);
  try {
    const hostRedact = typeof window !== "undefined" ? window.redactSensitiveText : null;
    if (typeof hostRedact === "function") out = String(hostRedact(out));
  } catch (_) {
    // 宿主脱敏函数异常时保留本地脱敏结果
  }
  return out;
}

export function safeDisplayValue(value) {
  const out = redactSensitiveText(value);
  return out.trim() ? out : "-";
}

// ── 目录（visibleDeliverables / renderDeliverableFilters） ───────────────

export function categoryName(categories, id) {
  const found = (categories || []).find((entry) => entry.id === id);
  return (found && found.name) || id || "";
}

export function visibleDeliverables(catalog, category, status) {
  return (catalog || []).filter((item) =>
    (!category || item.category === category) && (!status || item.implementation_status === status));
}

export function categoryOptions(categories) {
  return [{ id: "", name: "全部分类" }, ...(categories || [])];
}

/** Status options: only statuses some item actually has, in legacy label order. */
export function statusOptions(catalog) {
  const options = [{ id: "", name: "全部状态" }];
  Object.entries(STATUS_LABELS).forEach(([id, name]) => {
    if ((catalog || []).some((item) => item.implementation_status === id)) options.push({ id, name });
  });
  return options;
}

export function itemMetaText(item, categories) {
  return `${categoryName(categories, item.category)} · ${AVAILABILITY_LABELS[item.availability] || item.availability} · ${STATUS_LABELS[item.implementation_status] || item.implementation_status}`;
}

/** Initial selection after a (re)load: requested → current → first available → first. */
export function pickInitialItem(catalog, requestedId, currentId) {
  const byId = (id) => (id ? (catalog || []).find((item) => item.id === id) || null : null);
  return byId(requestedId) || byId(currentId)
    || (catalog || []).find((item) => item.availability === "available") || (catalog || [])[0] || null;
}

export function isExecutableTdc(item) {
  return Boolean(item && item.availability === "available" && TDC_ENDPOINTS[item.id]);
}

export function isArasTarget(item) {
  return Boolean(item && item.target && item.target.panel === "aras-panel");
}

/** openDeliverableInAras → system-query plugin page. */
export function systemQueryHash(item) {
  const mode = item && item.target && item.target.mode;
  return mode
    ? `${SYSTEM_QUERY_HASH}?mode=${encodeURIComponent(mode)}&from=overview`
    : `${SYSTEM_QUERY_HASH}?from=overview`;
}

export function itemHash(id) {
  return id ? `${PAGE_HASH}?item=${encodeURIComponent(id)}` : PAGE_HASH;
}

/** `#p/deliverables/catalog?item=<id>` → id (or ""). */
export function parseItemParam(hash) {
  const text = String(hash || "");
  if (!text.startsWith(PAGE_HASH)) return "";
  const at = text.indexOf("?");
  const params = new URLSearchParams(at >= 0 ? text.slice(at + 1) : "");
  return (params.get("item") || "").trim().slice(0, 200);
}

// ── 表单默认值、请求体与校验 ────────────────────────────────────────────

export function defaultFormValues(item) {
  const config = TDC_ENDPOINTS[item.id] || { defaultExportName: "tdc_export.xlsx" };
  const values = {
    base_url: TDC_DEFAULT_BASE_URL,
    headers: "",
    operation_mode: "query",
    output_format: "XLSX",
    file_name: config.defaultExportName,
    preview_source: "list_endpoint",
    car_type_project_id: "",
  };
  (item.fields || []).forEach((field) => {
    values[field.name] = "";
  });
  OPERATION_FIELDS.forEach((field) => {
    values[field.name] = field.defaultValue;
  });
  return values;
}

export function parseHeaders(raw) {
  const headers = {};
  String(raw || "").split(/\r?\n|,\s*(?=[A-Za-z0-9_-]+\s*:)/).forEach((line) => {
    const index = line.indexOf(":");
    if (index <= 0) return;
    const key = line.slice(0, index).trim();
    const value = line.slice(index + 1).trim();
    if (key && value) headers[key] = value;
  });
  return headers;
}

function trimmed(values, name) {
  const value = values[name];
  return value === undefined || value === null ? "" : String(value).trim();
}

/** Legacy collectDeliverablePayload. */
export function buildPayload(item, values, operation) {
  const payload = {
    base_url: trimmed(values, "base_url"),
    headers: parseHeaders(values.headers),
    filters: {},
  };
  (item.fields || []).forEach((field) => {
    const value = trimmed(values, field.name);
    if (!value) return;
    // 流水单号（documentNo）不是 TDC 查询参数：服务端从请求体顶层读取它（可多值，
    // 分隔符约定同交付物明细搜索），然后全量翻页做本地精确匹配。放进 filters 会被
    // 服务端按"不支持的筛选字段"拒绝（与 system_query 的 buildPayload 同约定）。
    if (item.id === "tdc-data-model" && field.name === "document_no") payload.document_no = value;
    else payload.filters[field.name] = value;
  });
  if (item.id === "tdc-sor") {
    const projectId = trimmed(values, "car_type_project_id");
    if (projectId) payload.filters.car_type_project_id = projectId;
  }
  const numberNames = operation === "query"
    ? ["page", "page_size"]
    : operation === "crawl_all" ? ["page_size", "max_pages", "max_records"] : [];
  numberNames.forEach((name) => {
    const value = Number(trimmed(values, name) || 0);
    if (value > 0) payload[name] = value;
  });
  if (operation === "export") {
    const fileName = trimmed(values, "file_name");
    if (fileName) payload.file_name = fileName;
  }
  if ((item.id === "tdc-data-model" || item.id === "tdc-sor") && (operation === "query" || operation === "crawl_all")) {
    payload.preview_source = trimmed(values, "preview_source") || "list_endpoint";
  }
  return payload;
}

/** Legacy clearDeliverablePayloadSecrets. */
export function clearPayloadSecrets(payload) {
  if (!payload) return;
  payload.password = "";
  payload.cookie = "";
  payload.headers = {};
  delete payload.cookies;
}

/**
 * Port of the legacy native constraints (Base URL required + type=url,
 * number inputs required + min=1, output format / file name required),
 * applied to the fields the chosen operation actually uses.
 * Returns {field: message}; an empty object means valid.
 */
export function validateForm(item, values, operation) {
  const errors = {};
  const baseUrl = trimmed(values, "base_url");
  if (!baseUrl) {
    errors.base_url = "请填写 Base URL";
  } else {
    let parsed = null;
    try {
      parsed = new URL(baseUrl);
    } catch (_) {
      parsed = null;
    }
    if (!parsed) errors.base_url = "请输入有效的网址（例如 https://tdc.sgmw.com.cn）";
  }
  OPERATION_FIELDS.forEach((field) => {
    if (!field.operations.includes(operation)) return;
    const raw = trimmed(values, field.name);
    if (!raw) errors[field.name] = `请填写${field.label}`;
    else if (!/^\d+$/.test(raw) || Number(raw) < 1) errors[field.name] = "请输入不小于 1 的整数";
  });
  (item.fields || []).forEach((field) => {
    if (field.type !== "number") return;
    const raw = trimmed(values, field.name);
    if (raw && !Number.isFinite(Number(raw))) errors[field.name] = "请输入数字";
  });
  if (operation === "export") {
    if (!trimmed(values, "output_format")) errors.output_format = "请选择输出格式";
    if (!trimmed(values, "file_name")) errors.file_name = "请填写 XLSX 文件名";
  }
  return errors;
}

/** Legacy formatDeliverableFilterSummary. */
export function formatFilterSummary(item, filters = {}, documentNo = "") {
  const labels = new Map((item.fields || []).map((f) => [f.name, f.label || f.name]));
  const parts = [];
  Object.entries(filters || {}).forEach(([key, val]) => {
    if (key === "car_type_project_id") return;
    if (val !== undefined && val !== null && String(val).trim()) {
      parts.push(`${labels.get(key) || key}: ${redactSensitiveText(String(val).trim())}`);
    }
  });
  // document_no 在请求体顶层（不在 filters 里），筛选摘要需要单独带上。
  if (String(documentNo || "").trim()) {
    parts.push(`${labels.get("document_no") || "流水单号"}: ${redactSensitiveText(String(documentNo).trim())}`);
  }
  return parts.length ? parts.join("；") : "无筛选条件";
}

/** Result meta line (legacy renderDeliverableResult). */
export function resultMetaText(data) {
  return `report=${data.report_type || "-"} source=${data.data_source || "-"} page=${data.page || "-"}/${data.pages || "-"} rows=${(data.rows || []).length} unique=${data.unique_count ?? "-"} dup=${data.duplicate_count ?? "-"} fetched=${data.fetched_pages ?? "-"} stop=${data.stop_reason || "-"} granularity=${data.record_granularity || "-"}`;
}

export function unmappedWarning(data) {
  if (data && data.mappingComplete === false && Array.isArray(data.unmappedColumns) && data.unmappedColumns.length > 0) {
    return `列表接口尚未提供 ${data.unmappedColumns.length} 个官方导出列，已保留为空值；请使用官方导出预览。`;
  }
  return "";
}

/**
 * A′ 流水单号本地匹配的覆盖度说明（与 system_query/lib.js serialMatchNotice 同语义，
 * 两份拷贝由 tests/test_plugin_system_query.py 的防漂移断言锁定）。
 * 单号缺命中、多号含 missing、抓取不完整分别给不同文案；无 serialMatch 返回 ""。
 */
export function serialMatchWarning(data) {
  const match = data && data.serialMatch;
  if (!match || typeof match !== "object") return "";
  const coverage = `已扫描 ${match.scannedPages ?? "-"} 页 / ${match.scanned ?? "-"} 行`;
  if (match.complete === false) {
    const reason = match.reason && match.reason !== "crawl_incomplete" ? `（原因：${match.reason}）` : "";
    return `抓取不完整，无法判定流水单号，请重试（${coverage}）${reason}`;
  }
  const missing = Array.isArray(match.missing) ? match.missing : [];
  if (missing.length > 0) {
    return `未找到以下流水单号：${missing.join("、")}（${coverage}，覆盖完整）`;
  }
  if (Number(match.matched) === 0) {
    return `未找到该流水单号（${coverage}，覆盖完整）`;
  }
  return "";
}

export function previewContextText(preview, suffix = "") {
  if (!preview) return "";
  if (!suffix) return `预览生成时间：${preview.queryTime} · 筛选条件：${preview.filterSummary}`;
  return `保留上次查询预览（生成时间：${preview.queryTime} · 筛选条件：${preview.filterSummary}）· ${suffix}`;
}

// ── 最近运行（recordRecentRun，页面内存） ───────────────────────────────

export function addRecentRun(runs, run, limit = RECENT_RUN_LIMIT) {
  const next = [{
    id: run.id,
    name: run.name,
    operation: run.operation,
    status: run.status,
    summary: redactSensitiveText(String(run.summary || "")),
    time: run.time,
  }, ...(runs || [])];
  return next.slice(0, limit);
}

export function recentRunTitle(run) {
  return `${run.name} · ${OPERATION_LABELS[run.operation] || run.operation}`;
}

// ── 错误分类 ───────────────────────────────────────────────────────────

/** Normalize a legacy `{ok:false,error}` body (or a network failure) into one shape. */
export function toApiError(body, status) {
  const error = (body && body.error) || {};
  return {
    status: Number(status) || 0,
    type: typeof error.type === "string" ? error.type : (status ? "HTTPError" : "NetworkError"),
    code: typeof error.code === "string" ? error.code : "",
    message: redactSensitiveText(
      typeof error.message === "string" && error.message
        ? error.message
        : status ? `HTTP ${status}` : "无法连接本地服务，请确认 VSE Toolbox 仍在运行",
    ),
    diagnosticPath: typeof error.diagnosticPath === "string" ? error.diagnosticPath : "",
  };
}

export function messageError(message, type = "Error") {
  return { status: 0, type, code: "", message: redactSensitiveText(message), diagnosticPath: "" };
}

/** Legacy formatApiErrorMessage: "Type: message｜诊断报告已保存：path". */
export function formatApiErrorMessage(err) {
  const message = `${err.type || "错误"}: ${err.message || `HTTP ${err.status}`}`;
  return redactSensitiveText(err.diagnosticPath ? `${message}｜诊断报告已保存：${err.diagnosticPath}` : message);
}

const AUTH_TYPES = new Set(["AuthenticationError", "DomainSessionRequired"]);
const LOCAL_GUARD_TYPES = new Set(["LocalAccessRequired", "CrossSiteRequest"]);

export function isLocalGuardError(err) {
  return Boolean(err) && err.status === 403 && LOCAL_GUARD_TYPES.has(err.type);
}

/** Legacy isAuthError, plus the structured status/code/type the server returns. */
export function isAuthError(err) {
  if (!err || isLocalGuardError(err)) return false;
  if (err.code === "unauthenticated" || AUTH_TYPES.has(err.type)) return true;
  if (err.status === 401 || err.status === 403) return true;
  const msg = String(err.message || "").toLowerCase();
  return ["未登录", "登录过期", "未认证", "尚未建立统一域账号会话", "session expired", "unauthorized", "not authenticated"]
    .some((needle) => msg.includes(needle));
}

// ── 下载与后台任务 ─────────────────────────────────────────────────────

export function sanitizeDownloadName(name) {
  return String(name).replace(/[\r\n\u0000-\u001f"\\/]/g, "").replace(/^.*[\\/]/, "").trim();
}

export function parseContentDispositionFilename(value) {
  if (!value) return "";
  const star = /filename\*\s*=\s*(?:utf-8''|UTF-8'')([^;]+)/i.exec(value);
  if (star) {
    try {
      const safe = sanitizeDownloadName(decodeURIComponent(star[1].trim()));
      if (safe) return safe;
    } catch (_) {
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

/** 202 Accepted + taskId contract (legacy isAsyncTaskAccepted). */
export function isTaskAccepted(status, body) {
  return status === 202 && Boolean(body) && body.ok === true && Boolean(body.data && body.data.taskId);
}

export function taskUrl(taskId, suffix = "") {
  return `/api/tasks/${encodeURIComponent(taskId)}${suffix}`;
}

export function taskProgressText(task) {
  if (!task) return "";
  const progress = task.progress || {};
  const parts = [];
  if (progress.stage) parts.push(redactSensitiveText(progress.stage));
  if (Number.isFinite(progress.current)) {
    parts.push(Number.isFinite(progress.total) ? `${progress.current}/${progress.total}` : String(progress.current));
  }
  return parts.join(" · ");
}

export function taskPercent(task) {
  const value = task && task.progress ? Number(task.progress.percent) : NaN;
  return Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : null;
}

// ── 结果网格（legacy renderRows，与 system-query 插件同口径） ────────────

export const GRID_PAGE_SIZES = [50, 100];
export const GRID_DEFAULT_PAGE_SIZE = 50;
const GRID_COPYABLE_LABEL_RE = /号\s*$|No\.?\s*$|Number\s*$/i;
const GRID_COPYABLE_KEY_RE = /(^|_)(no|number|incident)(_|$)/i;

export function orderedColumns(rows, preferredColumns) {
  const available = new Set();
  rows.forEach((row) => {
    if (!row || typeof row !== "object" || Array.isArray(row)) return;
    Object.keys(row).forEach((key) => {
      if (!SENSITIVE_COLUMNS.has(key.toLowerCase())) available.add(key);
    });
  });
  const columns = (preferredColumns || []).filter((key) => available.has(key));
  Array.from(available).filter((key) => !columns.includes(key)).sort().forEach((key) => columns.push(key));
  return columns.slice(0, 12);
}

function labelsFrom(headerRow) {
  return headerRow.map((label, i) => ({ label: label ? String(label).trim() : `列 ${i + 1}`, key: null }));
}

/** Legacy buildGridColumns: headerRows → columns → object keys fallback. */
export function buildGridColumns(data, rows, preferredColumns, modeId) {
  const headerRows = Array.isArray(data.headerRows) ? data.headerRows : null;
  const columns = Array.isArray(data.columns) ? data.columns : null;
  if (headerRows && headerRows.length > 0) {
    if (modeId === "ncr-detail" && headerRows.length > 1) {
      return { kind: "grouped", groups: headerRows, count: headerRows[0].length };
    }
    if (modeId === "ncr-progress" && headerRows.length > 1) {
      const target = headerRows[1] || headerRows[0];
      return { kind: "labels", count: target.length, labels: labelsFrom(target) };
    }
    return { kind: "labels", count: headerRows[0].length, labels: labelsFrom(headerRows[0]) };
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

/** Candidate columns with sensitive keys removed at the source. */
export function candidateColumns(gridColumns) {
  const all = [];
  for (let i = 0; i < gridColumns.count; i += 1) {
    const col = gridColumns.kind === "grouped" ? { label: `列 ${i + 1}`, key: null } : gridColumns.labels[i];
    if (!col) continue;
    if (col.key && SENSITIVE_COLUMNS.has(col.key.toLowerCase())) continue;
    if (!col.key && SENSITIVE_COLUMNS.has(String(col.label).toLowerCase())) continue;
    all.push({ index: i, ...col });
  }
  return all;
}

export function gridColumnValue(row, column, index) {
  if (Array.isArray(row)) return row[index];
  if (row && typeof row === "object") {
    if (column.key && column.key in row) return row[column.key];
    const key = Object.keys(row)[index];
    if (key && SENSITIVE_COLUMNS.has(key.toLowerCase())) return undefined;
    return row[key];
  }
  return undefined;
}

function parseNumericLike(value) {
  const t = String(value).trim().replace(/,/g, "");
  if (!t || !/^-?\d+(\.\d+)?$/.test(t)) return null;
  return parseFloat(t);
}

export function compareGridValues(a, b) {
  const av = a == null ? "" : String(a);
  const bv = b == null ? "" : String(b);
  const an = parseNumericLike(av);
  const bn = parseNumericLike(bv);
  if (an !== null && bn !== null) return an - bn;
  return av.localeCompare(bv, "zh-Hans-CN", { numeric: true, sensitivity: "base" });
}

export function isCopyableColumn(label, key) {
  return GRID_COPYABLE_LABEL_RE.test(String(label || "")) || GRID_COPYABLE_KEY_RE.test(String(key || ""));
}

/** Visible column indexes for a column mode (default / common / all / custom). */
export function visibleColumnIndexes(allColumns, { grouped, columnMode, hiddenColumns, commonCount, modeId }) {
  if (grouped || columnMode === "all") return allColumns.map((c) => c.index);
  if (columnMode === "common") return allColumns.slice(0, commonCount).map((c) => c.index);
  if (columnMode === "custom") return allColumns.filter((c) => !hiddenColumns.includes(c.index)).map((c) => c.index);
  // default：与旧契约一致——仅 EWO/PAA 收敛到常用列
  return modeId === "ewo" || modeId === "paa"
    ? allColumns.slice(0, commonCount).map((c) => c.index)
    : allColumns.map((c) => c.index);
}

/** Quick filter over visible columns, then stable multi-column sort. */
export function processRows(rows, visibleCols, filterText, sortSpec, colByIndex) {
  const query = String(filterText || "").trim().toLowerCase();
  let out = rows;
  if (query) {
    out = rows.filter((row) => visibleCols.some((col) => {
      const value = gridColumnValue(row, col, col.index);
      return value != null && String(value).toLowerCase().includes(query);
    }));
  }
  if (sortSpec && sortSpec.length) {
    const spec = sortSpec.map((item) => ({ ...item, col: colByIndex.get(item.index) || { key: null } }));
    out = out.slice().sort((a, b) => {
      for (const item of spec) {
        const cmp = compareGridValues(gridColumnValue(a, item.col, item.index), gridColumnValue(b, item.col, item.index));
        if (cmp !== 0) return item.dir === "asc" ? cmp : -cmp;
      }
      return 0;
    });
  }
  return out;
}

/** Header click: none → asc → desc → none; shift-click appends a sort key. */
export function nextSortSpec(sortSpec, index, shiftKey) {
  const existing = sortSpec.find((s) => s.index === index);
  if (existing) {
    if (existing.dir === "asc") return sortSpec.map((s) => (s.index === index ? { index, dir: "desc" } : s));
    return sortSpec.filter((s) => s.index !== index);
  }
  if (shiftKey) return [...sortSpec, { index, dir: "asc" }];
  return [{ index, dir: "asc" }];
}

/** Split text into [{text, hit}] segments for highlight rendering (case-insensitive). */
export function highlightSegments(value, query) {
  const source = value == null ? "" : String(value);
  const needle = String(query || "").toLowerCase();
  if (!needle) return [{ text: source, hit: false }];
  const lower = source.toLowerCase();
  const segments = [];
  let cursor = 0;
  for (;;) {
    const hit = lower.indexOf(needle, cursor);
    if (hit === -1) {
      if (cursor < source.length) segments.push({ text: source.slice(cursor), hit: false });
      break;
    }
    if (hit > cursor) segments.push({ text: source.slice(cursor, hit), hit: false });
    segments.push({ text: source.slice(hit, hit + needle.length), hit: true });
    cursor = hit + needle.length;
  }
  return segments;
}
