// 交付物明细列表「同步设置」列的纯逻辑（签署日报规格 §9 S12–S19）。
// Import-free; node-tested (tests/test_plugin_overview_watchlist_logic.py).

const FILTER_LABELS = {
  department: "部门",
  section: "科室",
  projectModel: "车型项目",
  model: "车型",
  status: "状态",
  approvalStatus: "审批状态",
  applicant: "申请人",
  applicationStart: "申请日期起",
  applicationEnd: "申请日期止",
  partNumber: "零件号",
  partName: "零件名称",
  modelNumber: "数模号",
  incident: "实例号",
  processNo: "流程号",
  ewoNo: "EWO 号",
  sectionScope: "科室范围",
};
// 不展示的内部键：报表类型、聚合标志、版本化绑定字段、关注清单（单独展示）。
const HIDDEN_KEYS = new Set(["reportType", "aggregate", "syncScope", "watchlist", "contractVersion", "bindingMode",
  "sourceItemId", "analysisMapping"]);

function valueText(value) {
  if (Array.isArray(value)) return value.map((item) => String(item)).join("、");
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** S12：筛选条件摘要，如「全部」「关注 12 份」「部门：技术中心_车体工程」。 */
export function filterSummary(setting) {
  const parts = [];
  if (setting && setting.watchlist && setting.watchlist.scope === "watchlist") {
    parts.push(`关注 ${setting.watchlist.count} 份`);
  }
  const filters = (setting && setting.filters) || {};
  Object.entries(filters).forEach(([key, value]) => {
    if (HIDDEN_KEYS.has(key) || value === null || value === undefined || value === "" ||
        (Array.isArray(value) && !value.length)) return;
    parts.push(`${FILTER_LABELS[key] || key}：${valueText(value)}`);
  });
  return parts.length ? parts.join("；") : "全部";
}

export function intervalText(setting) {
  const raw = setting ? setting.intervalMinutes : null;
  // 交付物绑定没写过自己的间隔时，跟随同步条上的调度频率。
  if (raw === null || raw === undefined) return setting && setting.kind === "binding" ? "跟随调度频率" : "—";
  const minutes = Number(raw);
  if (!Number.isFinite(minutes) || minutes <= 0) return "—";
  if (minutes % 1440 === 0) return `每 ${minutes / 1440} 天`;
  if (minutes % 60 === 0) return `每 ${minutes / 60} 小时`;
  return `每 ${minutes} 分钟`;
}

const STATE_TEXT = {
  idle: "未运行",
  running: "同步中",
  success: "成功",
  partial: "部分成功",
  failed: "失败",
  needs_attention: "需处理",
};

function shortTime(value) {
  if (!value) return "";
  return String(value).replace("T", " ").replace(/\.\d+/, "").replace(/Z$/, "").slice(5, 16);
}

/** S12：上次同步时间和结果。 */
export function lastSyncText(setting) {
  if (!setting) return "";
  const state = STATE_TEXT[setting.syncState] || setting.syncState || "";
  const time = shortTime(setting.lastAttemptAt || setting.lastSuccessAt);
  if (!time) return "从未同步";
  return state ? `${time} ${state}` : time;
}

/** S15：待配置的行写明缺哪一项。 */
export function missingText(setting) {
  const missing = (setting && setting.missing) || [];
  return missing.length ? `待配置：缺${missing.join("、")}` : "";
}

const BINDING_FIELDS = new Set(["enabled", "intervalMinutes", "mode", "matchRule"]);

/**
 * S13、S14：把行内改动变成对宿主既有接口的请求；列表和明细页读写同一份设置。
 * changes 键：enabled、intervalMinutes、mode、filters。
 */
export function settingRequest(setting, changes) {
  if (setting.kind === "archive") {
    return {
      path: `/api/scheduled-archive/jobs/${encodeURIComponent(setting.jobKey)}`,
      method: "PATCH",
      body: {
        enabled: changes.enabled !== undefined ? changes.enabled : setting.enabled,
        intervalMinutes: changes.intervalMinutes !== undefined ? changes.intervalMinutes : setting.intervalMinutes,
        filters: changes.filters !== undefined ? changes.filters : setting.filters,
        outputSubdir: setting.outputSubdir || "",
        updatedAt: setting.updatedAt,
      },
    };
  }
  const body = {};
  Object.entries(changes).forEach(([key, value]) => {
    const target = key === "filters" ? "matchRule" : key;
    if (BINDING_FIELDS.has(target)) body[target] = value;
  });
  return {
    path: `/api/project-status/deliverables/${encodeURIComponent(setting.deliverableId)}/update-policy`,
    method: "PATCH",
    body,
  };
}

/** 行内编辑区的间隔校验：归档任务 5–10080 分钟，交付物绑定正整数分钟。 */
export function parseInterval(text, kind) {
  const value = Number(String(text || "").trim());
  if (!Number.isInteger(value) || value <= 0) return { error: "间隔必须是正整数分钟" };
  if (kind === "archive" && (value < 5 || value > 10080)) return { error: "归档任务间隔必须在 5–10080 分钟之间" };
  return { value };
}

export function parseFilters(text) {
  const raw = String(text || "").trim();
  if (!raw) return { value: {} };
  try {
    const value = JSON.parse(raw);
    if (!value || typeof value !== "object" || Array.isArray(value)) return { error: "筛选条件必须是 JSON 对象" };
    return { value };
  } catch (_) {
    return { error: "筛选条件不是有效的 JSON" };
  }
}

/** 宿主字段级错误 -> 一行中文说明。 */
export function fieldErrorsText(error) {
  const fields = error && error.fields && typeof error.fields === "object" ? error.fields : null;
  if (fields) return Object.values(fields).map(String).join("；");
  return (error && (error.errorMessage || error.message)) || "保存失败";
}

/** S17：立即全量同步前列出本次会同步的交付物（已启用的交付物绑定）及各自筛选条件。 */
export function syncAllCandidates(settings) {
  return (settings || [])
    .filter((setting) => setting.kind === "binding" && setting.enabled)
    .map((setting) => ({ deliverableId: setting.deliverableId, name: setting.displayName || setting.deliverableId,
      filters: filterSummary(setting) }));
}

/** S18：调度器在运行但没有启用任何交付物时，同步条用警示色提示。 */
export function schedulerWarning(status) {
  if (!status || status.paused === true || status.running === false) return "";
  return Number(status.eligibleCount || 0) === 0 ? "没有启用任何交付物，自动同步不会抓取数据" : "";
}
