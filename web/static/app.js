const STATUS_LABELS = {
  active: "活跃",
  archived: "已归档",
  pending: "待处理",
  in_progress: "进行中",
  done: "已完成",
  blocked: "受阻",
  total: "总数",
  synced: "已同步",
  pending_sync: "待同步",
  completed: "已完成",
  partial: "部分完成",
  complete: "已完成",
  open: "未关闭",
  closed: "已关闭",
  draft: "草稿",
  cancelled: "已取消",
  canceled: "已取消",
  failed: "失败",
};

const STATUS_COLOR_CLASS = {
  active: "sage",
  archived: "",
  pending: "amber",
  in_progress: "plum",
  done: "sage",
  blocked: "rose",
  synced: "sage",
  pending_sync: "amber",
  completed: "sage",
  partial: "amber",
  complete: "sage",
  open: "amber",
  closed: "sage",
  failed: "rose",
};

const THEME_KEY = "vse-toolbox-theme";
const TEST_SESSION_CSRF_HEADER = "X-Test-Session-CSRF";
const TEST_SESSION_ENDPOINTS = Object.freeze({
  bootstrap: "/api/test-session/bootstrap",
  seed: "/api/test-session/seed",
  status: "/api/test-session/status",
  export: "/api/test-session/export",
  clear: "/api/test-session/clear",
});
const TEST_SESSION_CODE_PATTERN = /^[A-Z][A-Z0-9_]{1,63}$/;
const EXPORT_JOB_ENDPOINTS = Object.freeze({
  start: "/api/aras/export-jobs",
  status: "/api/aras/export-jobs/status",
  cancel: "/api/aras/export-jobs/cancel",
});
const EXPORT_JOB_ID_HEADER = "X-Aras-Export-Operation";
const EXPORT_JOB_CSRF_HEADER = "X-Aras-Export-CSRF";
const EXPORT_JOB_TOKEN_PATTERN = /^[A-Za-z0-9_-]{20,128}$/;

const AUTH_STAGE_LABELS = Object.freeze({
  transport: "传输校验",
  client: "Aras 客户端",
  discovery: "认证发现",
  metadata: "认证元数据",
  authorize: "授权跳转",
  form: "登录表单",
  credentials: "凭据验证",
  browser: "浏览器认证",
  callback: "认证回调",
  validation: "Aras 权限验证",
  base_load: "ECM 入口",
  credential_submit: "凭据提交",
  callback_wait: "回调等待",
  callback_verify: "回调校验",
  auth_capability_wait: "授权能力等待",
  auth_header_call: "授权桥调用",
  soap_dispatch: "业务请求发送",
  soap_response: "业务响应",
  soap_parse: "业务响应解析",
  business_ready: "业务会话验证",
  cleanup: "安全清理",
});

const AUTH_BROWSER_SUBSTAGE_LABELS = Object.freeze({
  driver_start: "浏览器启动",
  navigate: "认证页导航",
  credential_page: "凭据页等待",
  form_validation: "登录表单校验",
  credential_submit: "凭据提交",
  callback_wait: "认证回调等待",
  session_extract: "会话提取",
  cleanup: "资源清理",
});

const AUTH_BROWSER_CATEGORY_LABELS = Object.freeze({
  timeout: "超时",
  webdriver: "浏览器驱动",
  security: "安全策略",
  protocol: "认证协议",
  unexpected: "意外错误",
  capability_missing: "授权能力缺失",
  capability_ambiguous: "授权能力不唯一",
  authorization_unavailable: "授权不可用",
  redirect: "异常跳转",
  http_auth: "登录态无效",
  http_forbidden: "权限不足",
  http_other: "上游请求错误",
  oversize: "响应超出安全上限",
  content_type: "响应格式错误",
  xml: "响应解析错误",
  soap_fault: "业务服务错误",
  item_type: "业务类型不匹配",
  browser_closed: "浏览器已关闭",
  cancelled: "已取消",
});

const ARAS_FIXED_ERROR_MESSAGES = Object.freeze({
  AUTH_BROWSER_UNAVAILABLE: "无法启动安全浏览器认证。",
  AUTH_CALLBACK_INVALID: "认证回调校验失败。",
  AUTH_CALLBACK_TIMEOUT: "等待认证回调超时。",
  AUTH_SESSION_CAPABILITY_TIMEOUT: "等待 ECM 授权能力超时。",
  AUTH_SESSION_CAPABILITY_AMBIGUOUS: "ECM 授权能力状态异常。",
  AUTH_AUTHORIZATION_UNAVAILABLE: "无法取得当前浏览器会话授权。",
  AUTH_SOAP_GATE_FAILED: "受保护业务会话验证失败。",
  AUTH_EXPORT_CANCELLED: "导出已取消。",
  AUTH_DEADLINE_EXCEEDED: "导出超过安全时限。",
  AUTH_CLEANUP_FAILED: "浏览器资源清理未能完整确认。",
  AUTH_CREDENTIALS_REJECTED: "用户名或密码未被接受。",
  AUTH_MODE_CONFLICT: "不能混用账号密码与备用认证信息。",
  INSECURE_HTTP_NOT_ALLOWED: "HTTP 登录需要确认本次风险授权。",
  INVALID_REQUEST: "导出请求无效。",
  INVALID_EXPORT_LIMIT: "导出安全限制无效。",
  EXPORT_TIMEOUT: "导出超过安全时限。",
  FILE_WRITE_FAILED: "本地导出文件写入失败。",
  SESSION_EXPIRED: "登录会话已失效。",
  UPSTREAM_REQUEST_FAILED: "业务数据请求失败。",
  EXPORT_FAILED: "全量导出未能完成。",
  EXPORT_JOB_BUSY: "已有导出正在运行。",
  EXPORT_JOB_NOT_FOUND: "导出任务已失效。",
  EXPORT_JOB_FORBIDDEN: "无权访问该导出任务。",
  EXPORT_JOB_PROTOCOL_FAILED: "导出任务响应格式无效。",
  EXPORT_JOB_NETWORK_FAILED: "无法连接本地导出服务。",
});

const SENSITIVE_COLUMNS = new Set([
  "raw_xml",
  "file_id",
  "authorization",
  "set-cookie",
  "cookie",
  "token",
  "access_token",
  "refresh_token",
  "id_token",
  "api_key",
  "client_secret",
  "sid",
  "sessionid",
  "arasauth",
  "jsessionid",
  "csrf",
  "x-csrf-token",
  "session",
  "secret",
  "password",
]);

const SENSITIVE_VALUE_PATTERNS = [
  [/\b(access[_-]?token|refresh[_-]?token|id[_-]?token|client[_-]?secret|api[_-]?key|x[_-]?csrf[_-]?token|session(?:id)?|password)\b(\s*[:=]\s*)(?:Bearer\s+)?([^,\s;'"}}\]\[]+)/gi, "$1$2[redacted]"],
  [/(['"])(authorization|set-cookie|cookie|token|api_key|sid|sessionid|arasauth|jsessionid|csrf|secret|password)\1\s*:\s*(['"])(?:\\.|(?!\3)[\s\S])*\3/gi, "$1$2$1:$3[redacted]$3"],
  [/\b(authorization)\b(\s*[:=]\s*)(.*?)(?=(?:\s|,\s*)\b(?:set-cookie|cookie|token|api_key|sid|sessionid|arasauth|jsessionid|csrf|secret|password)\b\s*[:=]|[\r\n}\]\[]|$)/gi, "$1$2[redacted]"],
  [/\b(set-cookie|cookie)\b(\s*[:=]\s*)(.*?)(?=(?:\s|,\s*)\b(?:authorization|set-cookie|cookie)\b\s*:|[\r\n}\]\[]|$)/gi, "$1$2[redacted]"],
  [/\b(token|api_key|sid|sessionid|arasauth|jsessionid|csrf|secret|password)\b(\s*[:=]\s*)(?:Bearer\s+)?([^,\s;'"}}\]\[]+)/gi, "$1$2[redacted]"],
  [/\b(authorization|cookie|token|api_key|sid|sessionid|arasauth|jsessionid|csrf|secret|password)=([^&\s,;'"}}\]\[]+)/gi, "$1=[redacted]"],
  [/\bBearer\s+([^,\s;'"}}\]\[]+)/gi, "Bearer [redacted]"],
];

const ARAS_MODES = {
  ewo: {
    endpoint: EXPORT_JOB_ENDPOINTS.start,
    fieldGroup: "ewo",
    filterNames: ["ewo_no", "project_code", "subject_keyword", "change_type", "change_sub_type", "area", "state", "rsp_department_keyword", "model_keyword", "submit_start", "submit_end"],
    numberNames: [],
    passwordAuth: true,
    resultKind: "export",
    asyncJob: true,
    actionLabel: "筛选后全量导出",
  },
  paa: {
    endpoint: EXPORT_JOB_ENDPOINTS.start,
    fieldGroup: "paa",
    filterNames: ["paa_no", "ewo_no", "state", "area", "base", "department_keyword", "vehicle_keyword", "submit_start", "submit_end", "mtl_rq_start", "mtl_rq_end"],
    numberNames: [],
    passwordAuth: true,
    resultKind: "export",
    asyncJob: true,
    actionLabel: "筛选后全量导出",
  },
  "ncr-progress": {
    endpoint: "/api/aras/ncr/progress",
    fieldGroup: "ncr",
    filterNames: ["buy_start", "buy_end", "pe_start", "pe_end", "ncr_no", "project_names", "section_code", "change_type", "othercondition"],
    numberNames: [],
    passwordAuth: false,
    preferredColumns: [],
    resultKind: "summary",
    actionLabel: "执行查询",
  },
  "ncr-detail": {
    endpoint: "/api/aras/ncr/detail",
    fieldGroup: "ncr",
    filterNames: ["buy_start", "buy_end", "pe_start", "pe_end", "ncr_no", "project_names", "section_code", "change_type", "othercondition"],
    numberNames: [],
    passwordAuth: false,
    preferredColumns: [],
    resultKind: "summary",
    actionLabel: "执行查询",
  },
};

let arasMode = "ewo";
let arasRunning = false;
let arasRequestSeq = 0;
let arasLatestRendered = 0;
let arasJobOperationId = "";
let arasJobCsrf = "";
let arasCancelling = false;
let testSessionFeatureEnabled = false;
let testSessionCsrf = "";
let testSessionRunning = false;
let testSessionSeeded = false;

const COMMAND_LABELS = {
  ewo: "EWO",
  paa: "PAA",
  "ncr-progress": "NCR 进度",
  "ncr-detail": "NCR 明细",
};

const RESULT_KIND_LABELS = {
  export: "导出摘要",
  summary: "摘要",
};

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

function renderStatRows(container, data) {
  container.innerHTML = "";
  Object.entries(data).forEach(([key, value]) => {
    const row = document.createElement("div");
    row.className = "stat-row";
    const labelEl = document.createElement("span");
    labelEl.className = "stat-label";
    labelEl.textContent = STATUS_LABELS[key] || key;
    const valueEl = document.createElement("span");
    valueEl.className = `stat-value ${STATUS_COLOR_CLASS[key] || ""}`;
    valueEl.textContent = value;
    row.append(labelEl, valueEl);
    container.appendChild(row);
  });
}

function renderFeishu(container, feishu) {
  renderStatRows(container, {
    total: feishu.total || 0,
    synced: feishu.synced || 0,
    pending_sync: (feishu.total || 0) - (feishu.synced || 0),
  });
}

async function loadOverview() {
  try {
    const resp = await fetch("/api/overview");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    renderStatRows(document.getElementById("projects-body"), data.projects || {});
    renderStatRows(document.getElementById("deliverables-body"), data.deliverables || {});
    renderFeishu(document.getElementById("feishu-body"), data.feishu || { total: 0, synced: 0 });
  } catch (err) {
    ["projects-body", "deliverables-body", "feishu-body"].forEach((id) => {
      const el = document.getElementById(id);
      el.innerHTML = "";
      const message = document.createElement("p");
      message.className = "error-msg";
      message.textContent = `加载失败：${redactSensitiveText(err.message)}`;
      el.appendChild(message);
    });
  }
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

function rawFieldValue(scope, name) {
  const el = scope.querySelector(`[name="${name}"]`);
  return el ? String(el.value || "") : "";
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

function fixedDiagnosticLabel(labels, value) {
  if (typeof value !== "string") return "";
  const key = value.trim().toLowerCase();
  return Object.prototype.hasOwnProperty.call(labels, key)
    ? labels[key]
    : "";
}

function authDiagnosticSuffix(error) {
  const safeError = error && typeof error === "object" ? error : {};
  const normalizedStage = typeof safeError.stage === "string"
    ? safeError.stage.trim().toLowerCase()
    : "";
  const diagnosticLabels = [];
  const stageLabel = fixedDiagnosticLabel(AUTH_STAGE_LABELS, normalizedStage);
  if (stageLabel) diagnosticLabels.push(stageLabel);
  if (normalizedStage === "browser") {
    const substageLabel = fixedDiagnosticLabel(AUTH_BROWSER_SUBSTAGE_LABELS, safeError.substage);
    if (substageLabel) diagnosticLabels.push(substageLabel);
  }
  const categoryLabel = fixedDiagnosticLabel(AUTH_BROWSER_CATEGORY_LABELS, safeError.category);
  if (categoryLabel) diagnosticLabels.push(categoryLabel);
  if (
    normalizedStage
    && normalizedStage !== "browser"
    && Object.prototype.hasOwnProperty.call(AUTH_STAGE_LABELS, normalizedStage)
    && Number.isInteger(safeError.capability_mask)
    && safeError.capability_mask >= 0
    && safeError.capability_mask <= 16383
  ) {
    diagnosticLabels.push(`诊断掩码 ${safeError.capability_mask}`);
  }
  return diagnosticLabels.length ? ` [阶段：${diagnosticLabels.join(" / ")}]` : "";
}

function formatArasApiError(error) {
  const safeError = error && typeof error === "object" ? error : {};
  const candidate = typeof safeError.code === "string" ? safeError.code.trim() : "";
  const code = Object.prototype.hasOwnProperty.call(ARAS_FIXED_ERROR_MESSAGES, candidate)
    ? candidate
    : "EXPORT_FAILED";
  const message = ARAS_FIXED_ERROR_MESSAGES[code];
  return `${code}${authDiagnosticSuffix(safeError)}: ${message}`;
}

function activeFieldGroup(config) {
  return document.querySelector(`[data-mode-fields="${config.fieldGroup}"]`);
}

function collectArasFilters(config) {
  const group = activeFieldGroup(config);
  const filters = {};
  config.filterNames.forEach((name) => {
    const value = fieldValue(group, name);
    if (name === "project_names") {
      filters[name] = value.split(",").map((item) => item.trim()).filter(Boolean);
    } else {
      filters[name] = value;
    }
  });
  return filters;
}

function collectArasPayload(config) {
  const form = document.getElementById("aras-form");
  const payload = {
    base_url: fieldValue(form, "base_url"),
    headers: parseHeaders(fieldValue(form, "headers")),
    cookie: fieldValue(form, "cookie"),
    filters: collectArasFilters(config),
  };
  if (config.passwordAuth) {
    payload.username = fieldValue(form, "username");
    payload.password = rawFieldValue(form, "password");
    payload.allow_insecure_http = Boolean(form.querySelector('[name="allow_insecure_http"]')?.checked);
  }
  config.numberNames.forEach((name) => {
    payload[name] = Number(fieldValue(activeFieldGroup(config), name) || 0);
  });
  return payload;
}

function validateArasPayload(payload, config) {
  let target;
  try {
    target = new URL(payload.base_url);
  } catch (_err) {
    throw new Error("INVALID_BASE_URL: 请输入有效的 Aras Base URL。");
  }
  if (!["http:", "https:"].includes(target.protocol) || target.username || target.password) {
    throw new Error("INVALID_BASE_URL: Aras Base URL 只能使用 HTTP/HTTPS，且不得包含凭据。");
  }
  if (!config.passwordAuth) {
    return;
  }

  const hasUsername = Boolean(payload.username);
  const hasPassword = Boolean(payload.password);
  if (hasUsername !== hasPassword) {
    throw new Error("INVALID_CREDENTIALS: 账号密码登录需要同时填写用户名和密码。");
  }

  const hasPasswordLogin = hasUsername && hasPassword;
  const hasFallbackCredentials = Boolean(payload.cookie) || Object.keys(payload.headers || {}).length > 0;
  if (hasPasswordLogin && hasFallbackCredentials) {
    throw new Error("MIXED_AUTH_MODES: 账号密码不能与备用 Header/Cookie 同时提交。");
  }

  if (!hasPasswordLogin) {
    payload.allow_insecure_http = false;
    if (!hasFallbackCredentials) {
      throw new Error("INVALID_CREDENTIALS: 请使用账号密码登录，或提供备用 Header/Cookie。");
    }
    return;
  }
  if (target.protocol === "http:" && payload.allow_insecure_http !== true) {
    throw new Error("INSECURE_HTTP_NOT_ALLOWED: HTTP 账号密码登录必须勾选仅限本次的风险确认。");
  }
}

function clearArasSensitiveInputs() {
  const form = document.getElementById("aras-form");
  ["password", "cookie", "headers"].forEach((name) => {
    const field = form.querySelector(`[name="${name}"]`);
    if (field) field.value = "";
  });
  const insecureHttp = form.querySelector('[name="allow_insecure_http"]');
  if (insecureHttp) insecureHttp.checked = false;
}

function setPasswordAuthFieldsEnabled(enabled) {
  document.querySelectorAll("[data-password-auth-field]").forEach((container) => {
    container.hidden = !enabled;
    container.querySelectorAll("input").forEach((input) => {
      input.disabled = !enabled;
      if (!enabled) {
        if (input.type === "checkbox") input.checked = false;
        else input.value = "";
      }
    });
  });
  document.querySelectorAll("[data-compat-auth-field]").forEach((container) => {
    container.hidden = Boolean(enabled);
    container.querySelectorAll("input, textarea").forEach((field) => {
      field.disabled = Boolean(enabled);
      if (enabled) field.value = "";
    });
  });
}

class TestSessionUiError extends Error {
  constructor(code, safeText) {
    super("Local test session request failed.");
    this.name = "TestSessionUiError";
    this.code = code;
    this.safeText = safeText;
  }
}

function stableTestSessionCode(value) {
  return typeof value === "string" && TEST_SESSION_CODE_PATTERN.test(value)
    ? value
    : "TEST_SESSION_FAILED";
}

function formatTestSessionError(error) {
  const safeError = error && typeof error === "object" ? error : {};
  const code = stableTestSessionCode(safeError.code);
  return `${code}${authDiagnosticSuffix(safeError)}`;
}

function showTestSessionError(message) {
  const target = document.getElementById("test-session-error");
  target.hidden = !message;
  target.textContent = message || "";
}

function replacePasswordInput(ready) {
  const current = document.getElementById("aras-password");
  if (!current) return;
  const replacement = current.cloneNode(false);
  replacement.removeAttribute("value");
  replacement.value = "";
  replacement.placeholder = ready ? "本轮认证信息已就绪（不回填密码）" : "";
  current.replaceWith(replacement);
}

function clearTestSessionPrefill() {
  const form = document.getElementById("aras-form");
  const baseUrl = form.querySelector('[name="base_url"]');
  const username = form.querySelector('[name="username"]');
  const insecureHttp = form.querySelector('[name="allow_insecure_http"]');
  if (baseUrl) baseUrl.value = "";
  if (username) username.value = "";
  if (insecureHttp) insecureHttp.checked = false;
  replacePasswordInput(false);
  ["ewo", "paa"].forEach((mode) => {
    const group = document.querySelector(`[data-mode-fields="${mode}"]`);
    group?.querySelectorAll("input, textarea").forEach((field) => {
      field.value = "";
    });
  });
}

function appendTestSessionStatusRow(target, label, value) {
  const row = document.createElement("div");
  row.className = "test-session-status-row";
  const key = document.createElement("strong");
  const content = document.createElement("span");
  key.textContent = label;
  content.textContent = safeDisplayValue(value);
  row.append(key, content);
  target.appendChild(row);
}

function applyTestSessionPrefill(status) {
  if (!status || typeof status !== "object" || status.seeded !== true) return;
  const form = document.getElementById("aras-form");
  const baseUrl = form.querySelector('[name="base_url"]');
  const username = form.querySelector('[name="username"]');
  if (baseUrl) baseUrl.value = typeof status.base_url === "string" ? status.base_url.trim() : "";
  if (username) username.value = typeof status.username === "string" ? status.username.trim() : "";

  const module = typeof status.module === "string" ? status.module.trim().toLowerCase() : "";
  const config = module === "ewo" || module === "paa" ? ARAS_MODES[module] : null;
  const filters = status.filters && typeof status.filters === "object" ? status.filters : {};
  if (config) {
    const group = document.querySelector(`[data-mode-fields="${config.fieldGroup}"]`);
    config.filterNames.forEach((name) => {
      const field = group?.querySelector(`[name="${name}"]`);
      if (!field || !Object.prototype.hasOwnProperty.call(filters, name)) return;
      const value = filters[name];
      field.value = config.numberNames.includes(name)
        ? String(Number.isFinite(Number(value)) ? Number(value) : 0)
        : String(value === null || value === undefined ? "" : value).trim();
    });
  }
  replacePasswordInput(status.password_cached === true || status.authenticated === true);
}

function renderTestSessionStatus(status) {
  const target = document.getElementById("test-session-status");
  target.innerHTML = "";
  const safeStatus = status && typeof status === "object" ? status : {};
  testSessionSeeded = safeStatus.seeded === true;
  if (!testSessionSeeded) {
    target.textContent = "尚未保存本轮测试信息";
    replacePasswordInput(false);
    updateTestSessionControls();
    return;
  }

  applyTestSessionPrefill(safeStatus);
  appendTestSessionStatusRow(target, "Base URL", typeof safeStatus.base_url === "string" ? safeStatus.base_url.trim() : "");
  appendTestSessionStatusRow(target, "用户名", typeof safeStatus.username === "string" ? safeStatus.username.trim() : "");
  appendTestSessionStatusRow(target, "密码状态", safeStatus.password_cached === true ? "已缓存于本轮内存" : "未缓存");
  appendTestSessionStatusRow(target, "认证状态", safeStatus.authenticated === true ? "已认证" : "未认证");
  appendTestSessionStatusRow(target, "运行状态", safeStatus.running === true ? "运行中" : "就绪");
  const ttl = Number.isFinite(Number(safeStatus.ttl_seconds)) ? Math.max(0, Number(safeStatus.ttl_seconds)) : 0;
  const remaining = Number.isFinite(Number(safeStatus.operations_remaining))
    ? Math.max(0, Math.trunc(Number(safeStatus.operations_remaining)))
    : 0;
  appendTestSessionStatusRow(target, "剩余时间", `${ttl} 秒`);
  appendTestSessionStatusRow(target, "剩余操作", remaining);

  const module = typeof safeStatus.module === "string" ? safeStatus.module.trim().toLowerCase() : "";
  const config = module === "ewo" || module === "paa" ? ARAS_MODES[module] : null;
  const filters = safeStatus.filters && typeof safeStatus.filters === "object" ? safeStatus.filters : {};
  if (config) {
    config.filterNames.forEach((name) => {
      if (Object.prototype.hasOwnProperty.call(filters, name)) {
        appendTestSessionStatusRow(target, `筛选·${name}`, filters[name]);
      }
    });
  }
  updateTestSessionControls();
}

function updateTestSessionControls() {
  const eligibleMode = arasMode === "ewo" || arasMode === "paa";
  const blocked = testSessionRunning || arasRunning || !eligibleMode;
  const seedButton = document.getElementById("test-session-seed");
  const exportButton = document.getElementById("test-session-export");
  const clearButton = document.getElementById("test-session-clear");
  if (seedButton) seedButton.disabled = blocked || testSessionSeeded;
  if (exportButton) exportButton.disabled = blocked || !testSessionSeeded;
  if (clearButton) {
    clearButton.disabled = arasRunning || !testSessionCsrf;
    clearButton.textContent = testSessionRunning ? "取消并清除本轮" : "清除本轮信息";
  }
}

function syncTestSessionVisibility() {
  const panel = document.getElementById("test-session-panel");
  const eligibleMode = arasMode === "ewo" || arasMode === "paa";
  panel.hidden = !testSessionFeatureEnabled || !eligibleMode;
  updateTestSessionControls();
}

function setTestSessionRunning(running) {
  testSessionRunning = Boolean(running);
  document.querySelectorAll("[data-aras-mode]").forEach((button) => {
    button.disabled = testSessionRunning || arasRunning;
  });
  const normalSubmit = document.getElementById("aras-submit");
  normalSubmit.disabled = testSessionRunning || arasRunning;
  updateTestSessionControls();
}

async function testSessionRequest(endpoint, payload, options = {}) {
  let requestBody = "";
  let headers = { "Content-Type": "application/json" };
  const useCsrf = options.useCsrf !== false;
  if (useCsrf) {
    if (!testSessionCsrf) {
      throw new TestSessionUiError("TEST_SESSION_NOT_FOUND", "TEST_SESSION_NOT_FOUND");
    }
    headers[TEST_SESSION_CSRF_HEADER] = testSessionCsrf;
  }
  try {
    requestBody = JSON.stringify(payload || {});
    let response;
    try {
      response = await fetch(endpoint, {
        method: "POST",
        headers,
        body: requestBody,
        credentials: "same-origin",
        cache: "no-store",
        referrerPolicy: "no-referrer",
        keepalive: options.keepalive === true,
      });
    } catch (_error) {
      throw new TestSessionUiError("TEST_SESSION_NETWORK_FAILED", "TEST_SESSION_NETWORK_FAILED");
    }
    let body;
    try {
      body = await response.json();
    } catch (_error) {
      throw new TestSessionUiError("TEST_SESSION_PROTOCOL_FAILED", "TEST_SESSION_PROTOCOL_FAILED");
    }
    if (!response.ok || !body || body.ok !== true) {
      const error = body && typeof body.error === "object" ? body.error : {};
      const code = stableTestSessionCode(error.code);
      throw new TestSessionUiError(code, formatTestSessionError(error));
    }
    return body;
  } finally {
    requestBody = "";
    if (headers[TEST_SESSION_CSRF_HEADER]) headers[TEST_SESSION_CSRF_HEADER] = "";
    headers = {};
  }
}

function acceptTestSessionCsrf(body) {
  const csrf = body && typeof body.csrf === "string" ? body.csrf : "";
  if (csrf.length < 20 || csrf.length > 512) {
    throw new TestSessionUiError("TEST_SESSION_PROTOCOL_FAILED", "TEST_SESSION_PROTOCOL_FAILED");
  }
  testSessionCsrf = csrf;
}

function setArasStatus(text, isRunning) {
  const status = document.getElementById("aras-status");
  const button = document.getElementById("aras-submit");
  status.textContent = text || "";
  status.classList.toggle("loading", Boolean(isRunning && text));
  button.disabled = Boolean(isRunning);
  if (testSessionRunning) button.disabled = true;
  button.classList.toggle("is-running", Boolean(isRunning));
  const cancelButton = document.getElementById("aras-cancel");
  if (cancelButton) {
    cancelButton.hidden = !isRunning;
    cancelButton.disabled = !isRunning || arasCancelling;
    cancelButton.textContent = arasCancelling ? "正在取消…" : "取消导出";
  }
  document.querySelectorAll("[data-aras-mode]").forEach((modeButton) => {
    modeButton.disabled = Boolean(isRunning);
    if (testSessionRunning) modeButton.disabled = true;
  });
  document.body.classList.toggle("aras-running", Boolean(isRunning || testSessionRunning));
  updateTestSessionControls();
}

function showArasError(message) {
  const error = document.getElementById("aras-error");
  error.hidden = !message;
  error.textContent = message || "";
  document.querySelector(".result-panel")?.classList.toggle("has-output", Boolean(message));
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

function renderExportSummary(data) {
  const table = document.createElement("table");
  table.className = "result-table";
  const tbody = document.createElement("tbody");
  const summaryRows = [
    ["导出状态", STATUS_LABELS[data.status] || data.status || "已完成"],
    ["模块", String(data.module || "").toUpperCase()],
    ["导出记录数", Number.isFinite(Number(data.count)) ? Number(data.count) : 0],
    ["文件名称", data.file_name],
    ["文件保存位置", data.saved_path],
    ["停止原因", data.stop_reason],
    ["触发安全上限", data.limit_reached ? "是" : "否"],
    ["抓取页数", Number.isFinite(Number(data.pages_fetched)) ? Number(data.pages_fetched) : 0],
    ["去重记录数", Number.isFinite(Number(data.duplicates_removed)) ? Number(data.duplicates_removed) : 0],
  ];
  summaryRows.forEach(([label, value]) => {
    const row = document.createElement("tr");
    const keyCell = document.createElement("th");
    const valueCell = document.createElement("td");
    keyCell.textContent = label;
    valueCell.textContent = safeDisplayValue(value);
    row.append(keyCell, valueCell);
    tbody.appendChild(row);
  });
  table.appendChild(tbody);
  return table;
}

function renderArasResult(data, mode, config) {
  const target = document.getElementById("aras-result");
  document.querySelector(".result-panel")?.classList.add("has-output");
  target.className = "result-output-content";
  target.innerHTML = "";
  document.getElementById("result-kind").textContent = RESULT_KIND_LABELS[config.resultKind] || config.resultKind;
  if (config.resultKind === "export") {
    target.appendChild(renderExportSummary(data));
  } else {
    target.appendChild(renderSummary(data));
  }
}

function resetTestSessionClientState() {
  testSessionCsrf = "";
  testSessionSeeded = false;
  clearTestSessionPrefill();
  renderTestSessionStatus({ seeded: false });
  showTestSessionError("");
  syncTestSessionVisibility();
}

async function bootstrapTestSession(options = {}) {
  let payload = {};
  let body = null;
  try {
    body = await testSessionRequest(TEST_SESSION_ENDPOINTS.bootstrap, payload, { useCsrf: false });
    acceptTestSessionCsrf(body);
    testSessionFeatureEnabled = true;
    showTestSessionError("");
    renderTestSessionStatus(body.status);
    syncTestSessionVisibility();
    return true;
  } catch (error) {
    testSessionCsrf = "";
    testSessionSeeded = false;
    if (error instanceof TestSessionUiError && error.code === "TEST_SESSION_DISABLED") {
      testSessionFeatureEnabled = false;
    }
    syncTestSessionVisibility();
    if (options.silent !== true && testSessionFeatureEnabled) {
      showTestSessionError(error instanceof TestSessionUiError ? error.safeText : "TEST_SESSION_FAILED");
    }
    return false;
  } finally {
    payload = {};
    body = null;
  }
}

function validateTestSessionSeedPayload(payload) {
  let target;
  try {
    target = new URL(payload.base_url);
  } catch (_error) {
    throw new TestSessionUiError("TEST_SESSION_INVALID", "TEST_SESSION_INVALID");
  }
  if (
    !["http:", "https:"].includes(target.protocol)
    || target.username
    || target.password
    || !payload.username
    || !payload.password
  ) {
    throw new TestSessionUiError("TEST_SESSION_INVALID", "TEST_SESSION_INVALID");
  }
  if (target.protocol === "http:" && payload.allow_insecure_http !== true) {
    throw new TestSessionUiError("INSECURE_HTTP_NOT_ALLOWED", "INSECURE_HTTP_NOT_ALLOWED");
  }
}

async function saveTestSession() {
  if (testSessionRunning || arasRunning || !["ewo", "paa"].includes(arasMode)) return;
  if (!testSessionCsrf && !(await bootstrapTestSession({ silent: false }))) return;

  const config = ARAS_MODES[arasMode];
  const form = document.getElementById("aras-form");
  let payload = null;
  let body = null;
  setTestSessionRunning(true);
  showTestSessionError("");
  try {
    payload = {
      base_url: fieldValue(form, "base_url"),
      username: fieldValue(form, "username"),
      password: rawFieldValue(form, "password"),
      allow_insecure_http: Boolean(form.querySelector('[name="allow_insecure_http"]')?.checked),
      module: arasMode,
      filters: collectArasFilters(config),
    };
    validateTestSessionSeedPayload(payload);
    body = await testSessionRequest(TEST_SESSION_ENDPOINTS.seed, payload);
    acceptTestSessionCsrf(body);
    renderTestSessionStatus(body.status);
  } catch (error) {
    showTestSessionError(error instanceof TestSessionUiError ? error.safeText : "TEST_SESSION_FAILED");
  } finally {
    if (payload) {
      payload.password = "";
      payload.base_url = "";
      payload.username = "";
      payload.filters = {};
      payload.allow_insecure_http = false;
    }
    payload = null;
    body = null;
    const insecureHttp = form.querySelector('[name="allow_insecure_http"]');
    if (insecureHttp) insecureHttp.checked = false;
    replacePasswordInput(testSessionSeeded);
    setTestSessionRunning(false);
  }
}

function testSessionWasDestroyedByCode(code) {
  return [
    "TEST_SESSION_NOT_FOUND",
    "TEST_SESSION_EXPIRED",
    "TEST_SESSION_LIMIT_REACHED",
    "TEST_SESSION_FORBIDDEN",
  ].includes(code);
}

async function refreshTestSessionStatus(options = {}) {
  if (!testSessionCsrf) return false;
  let payload = {};
  let body = null;
  try {
    body = await testSessionRequest(TEST_SESSION_ENDPOINTS.status, payload);
    renderTestSessionStatus(body.status);
    return true;
  } catch (error) {
    if (error instanceof TestSessionUiError && testSessionWasDestroyedByCode(error.code)) {
      resetTestSessionClientState();
    } else if (options.silent !== true) {
      showTestSessionError(error instanceof TestSessionUiError ? error.safeText : "TEST_SESSION_FAILED");
    }
    return false;
  } finally {
    payload = {};
    body = null;
  }
}

async function executeTestSessionExport() {
  if (
    testSessionRunning
    || arasRunning
    || !testSessionSeeded
    || !testSessionCsrf
    || !["ewo", "paa"].includes(arasMode)
  ) return;

  const requestMode = arasMode;
  const config = ARAS_MODES[requestMode];
  const resultTarget = document.getElementById("aras-result");
  let payload = null;
  let body = null;
  setTestSessionRunning(true);
  showTestSessionError("");
  showArasError("");
  resultTarget.className = "is-empty";
  resultTarget.textContent = "正在执行本轮全量导出…";
  document.getElementById("result-kind").textContent = "本轮测试运行中";
  try {
    payload = {
      module: requestMode,
      filters: collectArasFilters(config),
    };
    body = await testSessionRequest(TEST_SESSION_ENDPOINTS.export, payload);
    renderArasResult(body, requestMode, config);
    if (body.test_session_destroyed === true) {
      resetTestSessionClientState();
    } else {
      await refreshTestSessionStatus({ silent: true });
    }
  } catch (error) {
    resultTarget.className = "is-empty";
    resultTarget.textContent = "本轮测试操作失败";
    document.getElementById("result-kind").textContent = "失败";
    showTestSessionError(error instanceof TestSessionUiError ? error.safeText : "TEST_SESSION_FAILED");
    await refreshTestSessionStatus({ silent: true });
  } finally {
    if (payload) payload.filters = {};
    payload = null;
    body = null;
    replacePasswordInput(testSessionSeeded);
    setTestSessionRunning(false);
  }
}

async function clearTestSession() {
  if (arasRunning) return;
  if (!testSessionCsrf) {
    resetTestSessionClientState();
    return;
  }
  let payload = {};
  let cleared = false;
  const exportWasRunning = testSessionRunning;
  if (!exportWasRunning) setTestSessionRunning(true);
  showTestSessionError("");
  try {
    const body = await testSessionRequest(TEST_SESSION_ENDPOINTS.clear, payload);
    cleared = body.status === "cleared";
    if (body.status === "cancelling") {
      showTestSessionError("TEST_SESSION_CANCEL_REQUESTED");
    }
  } catch (error) {
    if (error instanceof TestSessionUiError && testSessionWasDestroyedByCode(error.code)) {
      cleared = true;
    } else {
      showTestSessionError(error instanceof TestSessionUiError ? error.safeText : "TEST_SESSION_FAILED");
    }
  } finally {
    payload = {};
    if (cleared) resetTestSessionClientState();
    if (!exportWasRunning) setTestSessionRunning(false);
    else updateTestSessionControls();
  }
}

function bestEffortClearTestSession() {
  if (!testSessionCsrf) return;
  const csrf = testSessionCsrf;
  testSessionCsrf = "";
  testSessionSeeded = false;
  let headers = {
    "Content-Type": "application/json",
    [TEST_SESSION_CSRF_HEADER]: csrf,
  };
  fetch(TEST_SESSION_ENDPOINTS.clear, {
    method: "POST",
    headers,
    body: "{}",
    credentials: "same-origin",
    cache: "no-store",
    referrerPolicy: "no-referrer",
    keepalive: true,
  }).catch(() => {});
  headers[TEST_SESSION_CSRF_HEADER] = "";
  headers = {};
}

function startEnabledTestSession() {
  document.getElementById("test-session-seed").addEventListener("click", saveTestSession);
  document.getElementById("test-session-export").addEventListener("click", executeTestSessionExport);
  document.getElementById("test-session-clear").addEventListener("click", clearTestSession);
  window.addEventListener("pagehide", bestEffortClearTestSession);
  window.addEventListener("beforeunload", bestEffortClearTestSession);
  bootstrapTestSession({ silent: true });
}

function setupTestSession() {
  if (document.body.dataset.testSessionEnabled !== "true") {
    return;
  }
  startEnabledTestSession();
}

class ArasJobUiError extends Error {
  constructor(error) {
    super("Aras export job failed.");
    this.name = "ArasJobUiError";
    this.safeError = error && typeof error === "object" ? error : { code: "EXPORT_FAILED" };
  }
}

function clearArasJobTokens() {
  arasJobOperationId = "";
  arasJobCsrf = "";
}

function validExportJobToken(value) {
  return typeof value === "string" && EXPORT_JOB_TOKEN_PATTERN.test(value);
}

async function exportJobRequest(endpoint, options = {}) {
  const method = options.method || "GET";
  const headers = {};
  let requestBody = "";
  if (options.start === true) {
    headers["Content-Type"] = "application/json";
    requestBody = JSON.stringify(options.payload || {});
  } else {
    if (!validExportJobToken(arasJobOperationId) || !validExportJobToken(arasJobCsrf)) {
      throw new ArasJobUiError({ code: "EXPORT_JOB_NOT_FOUND" });
    }
    headers[EXPORT_JOB_ID_HEADER] = arasJobOperationId;
    headers[EXPORT_JOB_CSRF_HEADER] = arasJobCsrf;
  }
  let response;
  try {
    response = await fetch(endpoint, {
      method,
      headers,
      body: requestBody || undefined,
      credentials: "same-origin",
      cache: "no-store",
      referrerPolicy: "no-referrer",
    });
  } catch (_error) {
    throw new ArasJobUiError({ code: "EXPORT_JOB_NETWORK_FAILED" });
  } finally {
    requestBody = "";
  }
  let body;
  try {
    body = await response.json();
  } catch (_error) {
    throw new ArasJobUiError({ code: "EXPORT_JOB_PROTOCOL_FAILED" });
  }
  if (!body || typeof body !== "object") {
    throw new ArasJobUiError({ code: "EXPORT_JOB_PROTOCOL_FAILED" });
  }
  if (!response.ok || body.ok === false) {
    throw new ArasJobUiError(body.error);
  }
  return body;
}

function waitForNextJobPoll() {
  return new Promise((resolve) => window.setTimeout(resolve, 500));
}

async function runArasExportJob(payload, requestMode, requestConfig, seq) {
  payload.module = requestMode;
  const start = await exportJobRequest(EXPORT_JOB_ENDPOINTS.start, {
    method: "POST",
    start: true,
    payload,
  });
  if (
    start.status !== "running"
    || start.module !== requestMode
    || !validExportJobToken(start.operation_id)
    || !validExportJobToken(start.csrf)
  ) {
    throw new ArasJobUiError({ code: "EXPORT_JOB_PROTOCOL_FAILED" });
  }
  arasJobOperationId = start.operation_id;
  arasJobCsrf = start.csrf;
  while (arasRunning && seq === arasRequestSeq) {
    await waitForNextJobPoll();
    const body = await exportJobRequest(EXPORT_JOB_ENDPOINTS.status);
    if (body.module !== requestMode) {
      throw new ArasJobUiError({ code: "EXPORT_JOB_PROTOCOL_FAILED" });
    }
    if (body.status === "running" || body.status === "cancelling") {
      arasCancelling = body.status === "cancelling";
      setArasStatus(arasCancelling ? "正在安全取消…" : "正在全量导出…", true);
      continue;
    }
    if (body.status === "completed" || body.status === "partial") {
      if (seq > arasLatestRendered) {
        arasLatestRendered = seq;
        renderArasResult(body, requestMode, requestConfig);
      }
      return;
    }
    throw new ArasJobUiError(body.error || {
      code: body.status === "cancelled" ? "AUTH_EXPORT_CANCELLED" : "EXPORT_FAILED",
    });
  }
  throw new ArasJobUiError({ code: "AUTH_EXPORT_CANCELLED", category: "cancelled" });
}

async function cancelArasExportJob() {
  if (!arasRunning || arasCancelling || !validExportJobToken(arasJobOperationId)) return;
  arasCancelling = true;
  setArasStatus("正在安全取消…", true);
  try {
    await exportJobRequest(EXPORT_JOB_ENDPOINTS.cancel, { method: "POST" });
  } catch (error) {
    if (error instanceof ArasJobUiError) {
      showArasError(formatArasApiError(error.safeError));
    } else {
      showArasError(formatArasApiError({ code: "EXPORT_JOB_PROTOCOL_FAILED" }));
    }
  }
}

async function runArasQuery() {
  if (arasRunning) {
    return;
  }
  if (testSessionRunning) {
    return;
  }
  arasRunning = true;
  const requestMode = arasMode;
  const requestConfig = ARAS_MODES[requestMode];
  const seq = ++arasRequestSeq;
  setArasStatus(requestConfig.resultKind === "export" ? "正在全量导出…" : "运行中", true);
  showArasError("");
  const resultTarget = document.getElementById("aras-result");
  resultTarget.className = "is-empty";
  resultTarget.textContent = requestConfig.resultKind === "export" ? "正在生成导出文件…" : "正在查询…";
  document.getElementById("result-kind").textContent = "运行中";
  let payload = null;
  let requestBody = "";
  try {
    payload = collectArasPayload(requestConfig);
    validateArasPayload(payload, requestConfig);
    if (requestConfig.asyncJob === true) {
      const jobPromise = runArasExportJob(payload, requestMode, requestConfig, seq);
      payload.password = "";
      payload.cookie = "";
      payload.headers = {};
      clearArasSensitiveInputs();
      await jobPromise;
      return;
    }
    requestBody = JSON.stringify(payload);
    const responsePromise = fetch(requestConfig.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: requestBody,
    });
    requestBody = "";
    payload.password = "";
    payload.cookie = "";
    payload.headers = {};
    clearArasSensitiveInputs();
    const resp = await responsePromise;
    const body = await resp.json();
    if (!resp.ok || !body.ok) {
      const err = body.error || {};
      throw new ArasJobUiError(err);
    }
    if (seq > arasLatestRendered) {
      arasLatestRendered = seq;
      renderArasResult(body.data || body, requestMode, requestConfig);
    }
  } catch (err) {
    if (seq > arasLatestRendered) {
      arasLatestRendered = seq;
      resultTarget.className = "is-empty";
      resultTarget.textContent = "操作失败";
      document.getElementById("result-kind").textContent = "失败";
      showArasError(
        err instanceof ArasJobUiError
          ? formatArasApiError(err.safeError)
          : formatArasApiError({ code: "EXPORT_JOB_PROTOCOL_FAILED" })
      );
    }
  } finally {
    requestBody = "";
    if (payload) {
      if (Object.prototype.hasOwnProperty.call(payload, "username")) payload.username = "";
      if (Object.prototype.hasOwnProperty.call(payload, "password")) payload.password = "";
      payload.cookie = "";
      payload.headers = {};
      payload.filters = {};
      if (Object.prototype.hasOwnProperty.call(payload, "allow_insecure_http")) {
        payload.allow_insecure_http = false;
      }
    }
    payload = null;
    clearArasSensitiveInputs();
    clearArasJobTokens();
    arasCancelling = false;
    arasRunning = false;
    setArasStatus("", false);
  }
}

function setupPanels() {
  document.querySelectorAll("[data-panel-link]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      document.querySelectorAll("[data-panel-link]").forEach((item) => item.classList.remove("active"));
      link.classList.add("active");
      document.querySelectorAll(".panel-section").forEach((panel) => {
        panel.hidden = panel.id !== link.dataset.panelLink;
      });
      const isAras = link.dataset.panelLink === "aras-panel";
      document.body.dataset.sessionView = isAras ? "aras" : "overview";
      document.getElementById("session-title").textContent = isAras ? "Aras 查询工具" : "工作台概览";
      document.getElementById("command-label").textContent = isAras ? (COMMAND_LABELS[arasMode] || arasMode) : "就绪";
    });
  });
}

function setupArasForm() {
  document.body.dataset.currentCommand = arasMode;
  document.getElementById("aras-submit").textContent = ARAS_MODES[arasMode].actionLabel;
  setPasswordAuthFieldsEnabled(ARAS_MODES[arasMode].passwordAuth);
  document.querySelectorAll("[data-aras-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      arasMode = button.dataset.arasMode;
      document.body.dataset.currentCommand = arasMode;
      document.getElementById("command-label").textContent = COMMAND_LABELS[arasMode] || arasMode;
      document.getElementById("aras-submit").textContent = ARAS_MODES[arasMode].actionLabel;
      setPasswordAuthFieldsEnabled(ARAS_MODES[arasMode].passwordAuth);
      syncTestSessionVisibility();
      document.querySelectorAll("[data-aras-mode]").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      document.querySelectorAll("[data-mode-fields]").forEach((group) => {
        group.hidden = group.dataset.modeFields !== ARAS_MODES[arasMode].fieldGroup;
      });
      showArasError("");
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
  document.getElementById("aras-cancel")?.addEventListener("click", cancelArasExportJob);
}

document.addEventListener("DOMContentLoaded", () => {
  applyTheme(preferredTheme());
  setupTheme();
  loadOverview();
  setupPanels();
  setupArasForm();
  setupTestSession();
});
