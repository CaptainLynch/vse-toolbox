// Pure helpers for the system query page (no DOM, no Preact): payload
// building, validation, grid column/row processing, redaction and error
// classification. Ported from the legacy app.js helpers of the same names.
import {
  DEEP_LINK_FIELDS,
  DEFAULT_MODE,
  FIELD_GROUPS,
  MODES,
  MODE_ALIASES,
  TDC_OPERATION_FIELDS,
} from "./modes.js";

// ── 敏感信息：与旧页面 SENSITIVE_COLUMNS / SENSITIVE_VALUE_PATTERNS 一致 ──
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

export function redactSensitiveText(value) {
  let out = value === null || value === undefined ? "" : String(value);
  SENSITIVE_VALUE_PATTERNS.forEach(([pattern, replacement]) => {
    out = out.replace(pattern, replacement);
  });
  return out;
}

export function safeDisplayValue(value) {
  const out = redactSensitiveText(value);
  return out.trim() ? out : "-";
}

/** Keys that must never be written to browser storage (legacy ARAS_FORBIDDEN_PERSIST_KEYS). */
export const FORBIDDEN_PERSIST_KEYS = new Set([
  "password", "cookie", "cookies", "authorization", "headers", "token", "secret",
  "api_key", "sessionid", "sid", "request_body", "body",
]);

// ── 模式与深链 ─────────────────────────────────────────────────────────

export function resolveMode(raw) {
  const key = String(raw || "").trim();
  if (MODES[key]) return key;
  if (MODE_ALIASES[key]) return MODE_ALIASES[key];
  return null;
}

/** Parse `#p/system-query/query?mode=...&from=overview&ewo_no=...`. */
export function parseDeepLink(hash) {
  const text = String(hash || "");
  const at = text.indexOf("?");
  const params = new URLSearchParams(at >= 0 ? text.slice(at + 1) : "");
  const mode = resolveMode(params.get("mode"));
  const group = mode ? MODES[mode].fieldGroup : null;
  const spec = group ? DEEP_LINK_FIELDS[group] : null;
  let identifier = "";
  if (spec) {
    const candidates = [spec.param, ...(spec.altParams || []), "no", "id"];
    for (const name of candidates) {
      const value = (params.get(name) || "").trim();
      if (value) {
        identifier = value.slice(0, 200);
        break;
      }
    }
  }
  return {
    mode,
    requestedMode: params.get("mode") || "",
    from: params.get("from") || "",
    identifier,
    identifierField: spec && identifier ? spec.field : null,
  };
}

export function fieldsForGroup(group) {
  const spec = FIELD_GROUPS[group];
  return spec ? spec.fields : [];
}

/** Default values of one field group (number defaults, othercondition=0, …). */
export function defaultGroupValues(group, system) {
  const values = {};
  fieldsForGroup(group).forEach((field) => {
    values[field.name] = field.defaultValue !== undefined ? field.defaultValue : "";
  });
  if (system === "tdc") {
    TDC_OPERATION_FIELDS.forEach((field) => {
      values[field.name] = field.defaultValue;
    });
    values.preview_source = "list_endpoint";
    values.car_type_project_id = "";
  }
  return values;
}

// ── 请求体 ─────────────────────────────────────────────────────────────

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

/**
 * Build the POST body for one operation ("query" | "crawl_all" | "export").
 * Aras follows legacy collectArasPayload (every filter sent, numbers as Number);
 * TDC follows collectDeliverablePayload (non-empty filters, positive numbers).
 */
export function buildPayload(modeId, values, connection, { operation = "query", includeXml = false } = {}) {
  const mode = MODES[modeId];
  const payload = {
    base_url: trimmed(connection, "base_url"),
    headers: parseHeaders(connection.headers),
    filters: {},
  };
  if (mode.system === "aras") {
    mode.filterNames.forEach((name) => {
      const value = trimmed(values, name);
      payload.filters[name] = name === "project_names"
        ? value.split(",").map((item) => item.trim()).filter(Boolean)
        : value;
    });
    const numberNames = operation === "export" ? (mode.exportNumberNames || []) : mode.numberNames;
    numberNames.forEach((name) => {
      payload[name] = Number(trimmed(values, name) || 0);
    });
    if (mode.xmlCapture && includeXml && operation !== "export") payload.include_xml = true;
    if (mode.preview) payload.preview = true;
    return payload;
  }
  mode.filterNames.forEach((name) => {
    const value = trimmed(values, name);
    if (!value) return;
    // 流水单号（documentNo）不是 TDC 查询参数：服务端从请求体顶层读取它，然后全量
    // 翻页做本地精确匹配。放进 filters 会被服务端按"不支持的筛选字段"拒绝。
    if (name === "document_no") payload.document_no = value;
    else payload.filters[name] = value;
  });
  if (modeId === "tdc-sor" && trimmed(values, "car_type_project_id")) {
    payload.filters.car_type_project_id = trimmed(values, "car_type_project_id");
  }
  const numberNames = operation === "query"
    ? mode.numberNames
    : operation === "crawl_all" ? (mode.crawlNumberNames || []) : [];
  numberNames.forEach((name) => {
    const value = Number(trimmed(values, name) || 0);
    if (value > 0) payload[name] = value;
  });
  if (operation === "export") {
    const fileName = trimmed(values, "file_name") || mode.defaultFileName;
    if (fileName) payload.file_name = fileName;
  }
  if (mode.previewSource && operation !== "export") {
    payload.preview_source = trimmed(values, "preview_source") || "list_endpoint";
  }
  return payload;
}

/** Drop secrets from a payload once the request is done (legacy clear*PayloadSecrets). */
export function clearPayloadSecrets(payload) {
  if (!payload) return;
  payload.password = "";
  payload.cookie = "";
  payload.headers = {};
  delete payload.cookies;
}

// ── 校验 ───────────────────────────────────────────────────────────────

function numberNamesFor(mode, operation) {
  if (mode.system === "aras") {
    // 旧页面的 <input type=number min=1> 对所有可见数字字段生效。
    return mode.numberNames;
  }
  if (operation === "query") return mode.numberNames;
  if (operation === "crawl_all") return mode.crawlNumberNames || [];
  return [];
}

/** Return {field: message}; empty object means valid. */
export function validateForm(modeId, values, connection, operation = "query") {
  const mode = MODES[modeId];
  const errors = {};
  const baseUrl = trimmed(connection, "base_url");
  if (!baseUrl) {
    errors.base_url = "请填写 Base URL";
  } else {
    let parsed = null;
    try {
      parsed = new URL(baseUrl);
    } catch (_) {
      parsed = null;
    }
    if (!parsed || !/^https?:$/.test(parsed.protocol)) errors.base_url = "Base URL 必须是 http(s) 地址";
  }
  numberNamesFor(mode, operation).forEach((name) => {
    const raw = trimmed(values, name);
    if (mode.system === "aras" && raw === "") return; // 旧页面允许留空，后端取默认值
    if (!/^\d+$/.test(raw) || Number(raw) < 1) errors[name] = "请输入不小于 1 的整数";
  });
  (FIELD_GROUPS[mode.fieldGroup].dateRanges || []).forEach(([start, end]) => {
    const a = trimmed(values, start);
    const b = trimmed(values, end);
    if (a && b && a > b) errors[end] = "结束日期不能早于开始日期";
  });
  if (mode.system === "tdc" && operation === "export") {
    const fileName = trimmed(values, "file_name") || mode.defaultFileName;
    if (!/^[^<>:"/\\|?*\x00-\x1f]+\.xlsx$/i.test(fileName)) errors.file_name = "文件名须以 .xlsx 结尾且不含路径字符";
  }
  return errors;
}

// ── 错误分类 ───────────────────────────────────────────────────────────

/** Normalize a legacy `{ok:false,error}` body (or a network failure) into one shape. */
export function toQueryError(body, status) {
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

export function formatApiErrorMessage(err) {
  const message = `${err.type || "错误"}: ${err.message || `HTTP ${err.status}`}`;
  return redactSensitiveText(err.diagnosticPath ? `${message}｜诊断报告已保存：${err.diagnosticPath}` : message);
}

const AUTH_TYPES = new Set(["AuthenticationError", "DomainSessionRequired"]);
const LOCAL_GUARD_TYPES = new Set(["LocalAccessRequired", "CrossSiteRequest"]);

/** Legacy isAuthError, plus the structured status/code/type the server now returns. */
export function isAuthError(err) {
  if (!err) return false;
  if (err.code === "unauthenticated" || AUTH_TYPES.has(err.type)) return true;
  if (err.status === 401) return true;
  if (err.status === 403 && !LOCAL_GUARD_TYPES.has(err.type)) return true;
  const msg = String(err.message || "").toLowerCase();
  return ["未登录", "登录过期", "未认证", "尚未建立统一域账号会话", "session expired", "unauthorized", "not authenticated"]
    .some((needle) => msg.includes(needle));
}

// ── 下载文件名 ─────────────────────────────────────────────────────────

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

// ── 后台任务 ───────────────────────────────────────────────────────────

/** 202 Accepted + taskId contract (legacy isAsyncTaskAccepted). */
export function isTaskAccepted(status, body) {
  return status === 202 && Boolean(body) && body.ok === true && Boolean(body.data && body.data.taskId);
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

// ── 结果网格 ───────────────────────────────────────────────────────────

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

/** Result meta line: legacy renderArasResult (Aras) / renderDeliverableResult (TDC). */
export function resultMetaText(modeId, data) {
  const mode = MODES[modeId];
  if (mode.system === "tdc") {
    return `report=${data.report_type || "-"} source=${data.data_source || "-"} page=${data.page || "-"}/${data.pages || "-"} rows=${(data.rows || []).length} unique=${data.unique_count ?? "-"} dup=${data.duplicate_count ?? "-"} fetched=${data.fetched_pages ?? "-"} stop=${data.stop_reason || "-"} granularity=${data.record_granularity || "-"}`;
  }
  let meta = `页码=${data.page || "-"} 行数=${data.count || 0} 项目数=${(data.item_ids || []).length}`;
  if (data.preview && data.preview.sheetName) {
    meta += ` 表格=${data.preview.sheetName}`;
    if (data.preview.truncated) meta += "（已展示前置行）";
  }
  return meta;
}

export function resultRowCount(data) {
  if (data && data.count != null) return Number(data.count) || 0;
  return data && Array.isArray(data.rows) ? data.rows.length : 0;
}

/**
 * A′ 路线（流水单号本地精确匹配）的覆盖度说明，无 serialMatch 时返回 null。
 *
 * complete=false 的语义是"抓取不完整，无法判定"，不是"未找到"——两者绝不能
 * 用同一句话，否则用户会把抓取失败当成"这个流水单号不存在"。
 */
export function serialMatchNotice(data) {
  const match = data && data.serialMatch;
  if (!match || typeof match !== "object") return null;
  const coverage = `已扫描 ${match.scannedPages ?? "-"} 页 / ${match.scanned ?? "-"} 行`;
  if (match.complete === false) {
    const reason = match.reason && match.reason !== "crawl_incomplete" ? `（原因：${match.reason}）` : "";
    return `抓取不完整，无法判定流水单号，请重试（${coverage}）${reason}`;
  }
  if (Number(match.matched) === 0) {
    return `未找到该流水单号（${coverage}，覆盖完整）`;
  }
  return null;
}

export function isModeId(value) {
  return Boolean(MODES[value]);
}

export { DEFAULT_MODE };
