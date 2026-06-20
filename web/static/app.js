const STATUS_LABELS = {
  active: "活跃",
  archived: "已归档",
  pending: "待开始",
  in_progress: "进行中",
  done: "已完成",
  blocked: "阻塞",
};

const STATUS_COLOR_CLASS = {
  active: "blue",
  archived: "",
  pending: "yellow",
  in_progress: "blue",
  done: "green",
  blocked: "red",
};

let arasMode = "ewo";
let arasRunning = false;
let arasQueued = false;
let arasRequestSeq = 0;
let arasLatestRendered = 0;

function renderStatRows(container, data) {
  container.innerHTML = "";
  Object.entries(data).forEach(([key, value]) => {
    const row = document.createElement("div");
    row.className = "stat-row";
    const colorCls = STATUS_COLOR_CLASS[key] || "";

    const labelEl = document.createElement("span");
    labelEl.className = "stat-label";
    labelEl.textContent = STATUS_LABELS[key] || key;

    const valueEl = document.createElement("span");
    valueEl.className = "stat-value" + (colorCls ? " " + colorCls : "");
    valueEl.textContent = value;

    row.appendChild(labelEl);
    row.appendChild(valueEl);
    container.appendChild(row);
  });
}

function renderFeishu(container, feishu) {
  container.innerHTML = "";
  const rows = [
    { label: "总计", value: feishu.total, cls: "blue" },
    { label: "已同步", value: feishu.synced, cls: "green" },
    { label: "待同步", value: feishu.total - feishu.synced, cls: "yellow" },
  ];
  rows.forEach(({ label, value, cls }) => {
    const row = document.createElement("div");
    row.className = "stat-row";
    const labelEl = document.createElement("span");
    labelEl.className = "stat-label";
    labelEl.textContent = label;
    const valueEl = document.createElement("span");
    valueEl.className = "stat-value " + cls;
    valueEl.textContent = value;
    row.appendChild(labelEl);
    row.appendChild(valueEl);
    container.appendChild(row);
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
      if (el) {
        const p = document.createElement("p");
        p.className = "error-msg";
        p.textContent = "加载失败: " + err.message;
        el.innerHTML = "";
        el.appendChild(p);
      }
    });
  }
}

function parseHeaders(raw) {
  const headers = {};
  raw.split(/\n|,/).forEach((line) => {
    const index = line.indexOf(":");
    if (index <= 0) return;
    const key = line.slice(0, index).trim();
    const value = line.slice(index + 1).trim();
    if (key && value) headers[key] = value;
  });
  return headers;
}

function fieldValue(form, name) {
  const el = form.elements[name];
  return el && el.value.trim() ? el.value.trim() : "";
}

function collectArasPayload() {
  const form = document.getElementById("aras-form");
  const base = {
    base_url: fieldValue(form, "base_url"),
    headers: parseHeaders(fieldValue(form, "headers")),
    cookie: fieldValue(form, "cookie"),
    filters: {},
  };

  if (arasMode === "ewo") {
    [
      "ewo_no",
      "project_code",
      "subject_keyword",
      "change_type",
      "change_sub_type",
      "area",
      "state",
      "rsp_department",
      "submit_start",
      "submit_end",
    ].forEach((name) => {
      base.filters[name] = fieldValue(form, name);
    });
    base.page = Number(fieldValue(form, "page") || 1);
    base.page_size = Number(fieldValue(form, "page_size") || 50);
    base.max_records = Number(fieldValue(form, "max_records") || 2000);
  } else {
    [
      "buy_start",
      "buy_end",
      "pe_start",
      "pe_end",
      "ncr_no",
      "section_code",
      "change_type",
      "othercondition",
    ].forEach((name) => {
      base.filters[name] = fieldValue(form, name);
    });
    base.filters.project_names = fieldValue(form, "project_names")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return base;
}

function endpointForMode() {
  if (arasMode === "ewo") return "/api/aras/ewo/query";
  if (arasMode === "ncr-progress") return "/api/aras/ncr/progress";
  return "/api/aras/ncr/detail";
}

function setArasStatus(text, isRunning) {
  const status = document.getElementById("aras-status");
  const button = document.getElementById("aras-submit");
  status.textContent = text || "";
  button.disabled = Boolean(isRunning);
  button.classList.toggle("running", Boolean(isRunning));
}

function showArasError(message) {
  const error = document.getElementById("aras-error");
  error.hidden = !message;
  error.textContent = message || "";
}

function renderSummary(data) {
  const table = document.createElement("table");
  table.className = "result-table";
  const body = document.createElement("tbody");
  Object.entries(data).forEach(([key, value]) => {
    const row = document.createElement("tr");
    const keyCell = document.createElement("th");
    const valueCell = document.createElement("td");
    keyCell.textContent = key;
    valueCell.textContent = value || "-";
    row.appendChild(keyCell);
    row.appendChild(valueCell);
    body.appendChild(row);
  });
  table.appendChild(body);
  return table;
}

function renderRows(data) {
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  const table = document.createElement("table");
  table.className = "result-table";
  const rows = data.rows || [];
  const keys = Array.from(new Set(rows.flatMap((row) => Object.keys(row)))).slice(0, 12);
  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  (keys.length ? keys : ["message"]).forEach((key) => {
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
        td.textContent = row[key] || "-";
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

function renderArasResult(data) {
  const target = document.getElementById("aras-result");
  target.innerHTML = "";
  if (arasMode === "ewo") {
    const meta = document.createElement("p");
    meta.className = "result-meta";
    meta.textContent = `page=${data.page || "-"} rows=${data.count || 0} items=${(data.item_ids || []).length}`;
    target.appendChild(meta);
    target.appendChild(renderRows(data));
  } else {
    target.appendChild(renderSummary(data));
  }
}

async function runArasQuery() {
  if (arasRunning) {
    arasQueued = true;
    setArasStatus("已有查询运行中，已排队", true);
    return;
  }
  arasRunning = true;
  const seq = ++arasRequestSeq;
  setArasStatus("查询中...", true);
  showArasError("");

  try {
    const resp = await fetch(endpointForMode(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectArasPayload()),
    });
    const payload = await resp.json();
    if (!resp.ok || !payload.ok) {
      const err = payload.error || {};
      throw new Error(`${err.type || "Error"}: ${err.message || `HTTP ${resp.status}`}`);
    }
    if (seq > arasLatestRendered) {
      arasLatestRendered = seq;
      renderArasResult(payload.data || {});
    }
  } catch (err) {
    if (seq > arasLatestRendered) {
      arasLatestRendered = seq;
      showArasError(err.message);
    }
  } finally {
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
    });
  });
}

function setupArasForm() {
  document.querySelectorAll("[data-aras-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      arasMode = button.dataset.arasMode;
      document.querySelectorAll("[data-aras-mode]").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      document.querySelector('[data-mode-fields="ewo"]').hidden = arasMode !== "ewo";
      document.querySelector('[data-mode-fields="ncr"]').hidden = arasMode === "ewo";
      showArasError("");
      document.getElementById("aras-result").innerHTML = "";
    });
  });

  document.getElementById("aras-form").addEventListener("submit", (event) => {
    event.preventDefault();
    runArasQuery();
  });
}

document.addEventListener("DOMContentLoaded", () => {
  loadOverview();
  setupPanels();
  setupArasForm();
});
