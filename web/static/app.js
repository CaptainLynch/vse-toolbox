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
  complete: "sage",
  open: "amber",
  closed: "sage",
  failed: "rose",
};

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
    fieldGroup: "ewo",
    filterNames: ["ewo_no", "project_code", "subject_keyword", "change_type", "change_sub_type", "area", "state", "rsp_department", "submit_start", "submit_end"],
    numberNames: ["page", "page_size", "max_records"],
    preferredColumns: ["_no", "_eplmwriteneplcode", "_subject", "_area", "_sort_type", "_rsp_department", "_submit_time", "state"],
    resultKind: "rows",
  },
  paa: {
    endpoint: "/api/aras/paa/query",
    fieldGroup: "paa",
    filterNames: ["paa_no", "ewo_no", "state", "area", "base", "vehicle_keyword", "submit_start", "submit_end", "mtl_rq_start", "mtl_rq_end"],
    numberNames: ["page", "page_size", "max_records"],
    preferredColumns: ["_no", "_ewo_no", "state", "_area", "_base", "_vehicles", "_submit_date", "_mtl_rq_date"],
    resultKind: "rows",
  },
  "paa-all": {
    endpoint: "/api/aras/paa/crawl-all",
    fieldGroup: "paa",
    filterNames: ["paa_no", "ewo_no", "state", "area", "base", "vehicle_keyword", "submit_start", "submit_end", "mtl_rq_start", "mtl_rq_end"],
    numberNames: ["page_size", "max_records", "max_pages"],
    preferredColumns: ["_no", "_ewo_no", "state", "_area", "_base", "_vehicles", "_submit_date", "_mtl_rq_date"],
    resultKind: "rows",
  },
  "ncr-progress": {
    endpoint: "/api/aras/ncr/progress",
    fieldGroup: "ncr",
    filterNames: ["buy_start", "buy_end", "pe_start", "pe_end", "ncr_no", "project_names", "section_code", "change_type", "othercondition"],
    numberNames: [],
    preferredColumns: [],
    resultKind: "summary",
  },
  "ncr-detail": {
    endpoint: "/api/aras/ncr/detail",
    fieldGroup: "ncr",
    filterNames: ["buy_start", "buy_end", "pe_start", "pe_end", "ncr_no", "project_names", "section_code", "change_type", "othercondition"],
    numberNames: [],
    preferredColumns: [],
    resultKind: "summary",
  },
};

let arasMode = "ewo";
let arasRunning = false;
let arasQueued = false;
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
    cookie: fieldValue(form, "cookie"),
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
  return payload;
}

function setArasStatus(text, isRunning) {
  const status = document.getElementById("aras-status");
  const button = document.getElementById("aras-submit");
  status.textContent = text || "";
  status.classList.toggle("loading", Boolean(isRunning && text));
  button.disabled = Boolean(isRunning);
  button.classList.toggle("is-running", Boolean(isRunning));
  document.body.classList.toggle("aras-running", Boolean(isRunning));
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
    arasQueued = true;
    setArasStatus("已排队", true);
    return;
  }
  arasRunning = true;
  const requestMode = arasMode;
  const requestConfig = ARAS_MODES[requestMode];
  const seq = ++arasRequestSeq;
  setArasStatus("运行中", true);
  showArasError("");
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
      throw new Error(`${err.type || "错误"}: ${err.message || `HTTP ${resp.status}`}`);
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
    payload.cookie = "";
    arasRunning = false;
    if (arasQueued) {
      arasQueued = false;
      runArasQuery();
    } else {
      setArasStatus("", false);
    }
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
}

document.addEventListener("DOMContentLoaded", () => {
  applyTheme(preferredTheme());
  setupTheme();
  loadOverview();
  setupPanels();
  setupArasForm();
});
