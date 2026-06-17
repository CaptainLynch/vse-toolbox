// web/static/app.js — 拉取 /api/overview 并渲染卡片（原生 fetch，无框架）

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

document.addEventListener("DOMContentLoaded", loadOverview);
