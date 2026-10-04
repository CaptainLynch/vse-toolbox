// Embedded form-analysis state (legacy createDeliverableFormState and the
// per-tab applied / draft / displayed filter maps). Mutable plain object, as
// in the legacy page; the component re-renders after each mutation.
// Import-free; node-tested.

export const DELIVERABLE_FORM_TABS = {
  "VPI-T2-D3": [["departmentStatus", "部门状态"], ["quantityTrend", "数量趋势"]],
  aras_paa: [["departmentStatus", "部门状态"], ["quantityTrend", "数量趋势"]],
  aras_ncr_progress: [["departmentStatus", "部门状态"], ["quantityTrend", "数量趋势"]],
  aras_ncr_detail: [["sectionCounts", "按科室"], ["departmentCost", "部门成本"], ["sectionCost", "科室成本"]],
  tdc_data_model: [["departmentStatus", "项目状态"], ["sectionStatus", "部门状态"], ["sectionCounts", "按科室"], ["quantityTrend", "数量趋势"]],
  tdc_sor: [["departmentStatus", "车型项目状态"], ["sectionStatus", "科室状态"], ["quantityTrend", "数量趋势"]],
};

export const FORM_FILTER_LABELS = {
  keyword: "关键词",
  terms: "多值搜索",
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

export const DELIVERABLE_FORM_FILTER_LABELS = {
  tdc_data_model: { section: "部门", model: "发布属性", stage: "项目 / 车型", dateStart: "申请日期（起）", dateEnd: "申请日期（止）" },
  tdc_sor: { section: "科室", model: "类型", stage: "车型项目", dateStart: "申请日期（起）", dateEnd: "申请日期（止）" },
};

export const DELIVERABLE_FORM_CHART_TITLES = {
  tdc_data_model: {
    departmentStatus: ["项目状态", "各项目 / 车型按期推进数与逾期风险数"],
    sectionStatus: ["部门状态", "点击一个部门可追加筛选"],
  },
  tdc_sor: {
    departmentStatus: ["车型项目状态", "各车型项目按期推进数与逾期风险数"],
    sectionStatus: ["科室状态", "点击一个科室可追加筛选"],
  },
};

export const OVERDUE_STATE_LABELS = {
  overdue: "逾期风险",
  on_time: "按期推进",
  unknown: "未判定",
  not_applicable: "已完成 / 不适用",
};

export const FORM_FILTER_QUERY_KEYS = ["keyword", "terms", "status", "department", "section", "model", "stage", "dateStart", "dateEnd", "overdueState", "relationEwo"];
export const FORM_MULTI_FILTER_KEYS = new Set(["status", "department", "section", "model", "stage", "overdueState"]);

export function deliverableFormFilterLabel(formKey, key) {
  const override = DELIVERABLE_FORM_FILTER_LABELS[formKey];
  return (override && override[key]) || FORM_FILTER_LABELS[key] || key;
}

export function deliverableFormKey(item) {
  if (!item || typeof item !== "object") return "";
  if (item.formLink && typeof item.formLink === "object" && item.formLink.formKey) return String(item.formLink.formKey);
  if (item.links && typeof item.links === "object" && item.links.formKey) return String(item.links.formKey);
  return String(item.formKey || "");
}

export function createDeliverableFormState(formKey) {
  const tabs = DELIVERABLE_FORM_TABS[formKey] || [];
  return {
    activeTab: tabs.length ? tabs[0][0] : "",
    boardTab: "bySection",
    filterStateByTab: {},
    draftFilterStateByTab: {},
    displayedFilterStateByTab: {},
    pageByTab: {},
    requestSeq: 0,
    viewStatus: "idle",
    overdueThresholds: null,
    viewOwner: "",
    rollupEditing: false,
    rollupDraft: null,
    rollupError: null,
    rollupPanelOpen: false,
  };
}

export function cloneFormFilterState(filters) {
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

export function currentFormFilterState(state) {
  if (!state || !state.activeTab) return {};
  if (!state.filterStateByTab[state.activeTab]) state.filterStateByTab[state.activeTab] = {};
  return state.filterStateByTab[state.activeTab];
}

export function currentFormDraftFilterState(state) {
  if (!state || !state.activeTab) return {};
  if (!state.draftFilterStateByTab) state.draftFilterStateByTab = {};
  if (!Object.prototype.hasOwnProperty.call(state.draftFilterStateByTab, state.activeTab)) {
    state.draftFilterStateByTab[state.activeTab] = cloneFormFilterState(currentFormFilterState(state));
  }
  return state.draftFilterStateByTab[state.activeTab];
}

export function currentFormDisplayedFilterState(state) {
  if (!state || !state.activeTab) return {};
  if (!state.displayedFilterStateByTab) state.displayedFilterStateByTab = {};
  if (!Object.prototype.hasOwnProperty.call(state.displayedFilterStateByTab, state.activeTab)) {
    state.displayedFilterStateByTab[state.activeTab] = cloneFormFilterState(currentFormFilterState(state));
  }
  return state.displayedFilterStateByTab[state.activeTab];
}

export function markFormFilterStateDisplayed(state, filters, tab) {
  if (!state) return;
  const key = tab || state.activeTab;
  if (!key) return;
  if (!state.displayedFilterStateByTab) state.displayedFilterStateByTab = {};
  state.displayedFilterStateByTab[key] = cloneFormFilterState(filters === undefined ? currentFormFilterState(state) : filters);
}

export function formFilterStatesEqual(left, right) {
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

export function clearCurrentFilters(state) {
  if (!state || !state.activeTab) return;
  state.filterStateByTab[state.activeTab] = {};
  if (!state.draftFilterStateByTab) state.draftFilterStateByTab = {};
  state.draftFilterStateByTab[state.activeTab] = {};
  state.pageByTab[state.activeTab] = 0;
}

/** Chart click: toggle a value into the applied (and draft) filters of the active tab. */
export function appendFormFilter(state, key, value) {
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
  if (key !== "dateStart" && key !== "dateEnd") state.pageByTab[state.activeTab] = 0;
}

/** "应用筛选": draft -> applied. */
export function applyDraftFilters(state) {
  const next = cloneFormFilterState(currentFormDraftFilterState(state));
  state.filterStateByTab[state.activeTab] = next;
  state.draftFilterStateByTab[state.activeTab] = cloneFormFilterState(next);
  state.pageByTab[state.activeTab] = 0;
}

/** Chip "×": remove one value from the displayed filters and apply. */
export function removeDisplayedFilter(state, key, item) {
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
}

export function setDraftFilter(state, key, value) {
  const draft = currentFormDraftFilterState(state);
  if (Array.isArray(value)) {
    if (value.length) draft[key] = value.slice();
    else delete draft[key];
    return;
  }
  const clean = String(value || "").trim();
  if (clean) draft[key] = clean;
  else delete draft[key];
}

/** Legacy updateDraftStatus wording + classes. */
export function formDraftStatus(state) {
  const displayed = currentFormDisplayedFilterState(state);
  const applied = currentFormFilterState(state);
  const draft = currentFormDraftFilterState(state);
  const draftDirty = !formFilterStatesEqual(applied, draft);
  const requestedChanged = !formFilterStatesEqual(displayed, applied);
  const loading = state.viewStatus === "loading";
  const failed = state.viewStatus === "error";
  const text = draftDirty
    ? "有未应用的筛选更改"
    : failed
      ? (requestedChanged ? "应用失败，显示最近成功结果" : "刷新失败，显示最近成功结果")
      : loading
        ? (requestedChanged ? "正在应用筛选..." : "正在刷新...")
        : requestedChanged
          ? "等待筛选结果..."
          : "已应用";
  return {
    text,
    dirty: draftDirty || requestedChanged || loading,
    pending: (requestedChanged || loading) && !failed,
    error: failed,
  };
}

export function buildDeliverableFormQuery(filters, includePaging = false, state = null) {
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

/**
 * view/rows 读取上限。此前请求无截止，挂起时交互守卫永久锁死（筛选条"点不动"）。
 * 阈值取正常视图耗时的宽松上界；对象可变，测试把它压到毫秒级来验证超时路径。
 */
export const FORM_VIEW_LIMITS = { timeoutMs: 30000 };

/** Retryable error raised when view/rows do not settle within the deadline. */
export function formViewLoadTimeoutError(timeoutMs) {
  const error = new Error(`表单数据读取超过 ${Math.round(timeoutMs / 1000)} 秒未完成，已取消；可稍后重试。`);
  error.retryable = true;
  error.formViewTimeout = true;
  return error;
}

export function formViewErrorMessage(error) {
  if (error && error.formViewTimeout) return String(error.message || "表单数据读取超时，请稍后重试。");
  const status = Number(error && error.status);
  if (status === 401 || status === 403) return "表单数据未认证，请先完成统一域账号登录。";
  if (status >= 500 || status === 0) return "表单数据服务暂不可用，请稍后重试。";
  return "表单数据读取失败，请稍后重试。";
}

export function formOptionValues(data, key) {
  const options = data && data.filters && data.filters.options;
  const values = options && Array.isArray(options[key]) ? options[key] : [];
  return values.map((value) => String(value || "").trim()).filter(Boolean);
}

/** Overdue threshold inputs -> state.overdueThresholds (clamped 0..999). */
export function overdueThresholdsFromInputs(inputs) {
  const next = {};
  Object.entries(inputs || {}).forEach(([key, raw]) => {
    const value = Math.floor(Number(raw));
    if (Number.isFinite(value)) next[key] = Math.max(0, Math.min(999, value));
  });
  return Object.keys(next).length ? next : null;
}

export function cloneRollupTargets(targets) {
  return (Array.isArray(targets) ? targets : []).map((entry) => ({
    target: String((entry && entry.target) || ""),
    aliases: (entry && Array.isArray(entry.aliases) ? entry.aliases : []).map((alias) => String(alias || "")),
  }));
}

export function buildRollupPayload(draft) {
  return {
    targets: (draft || []).map((entry) => ({
      target: String(entry.target || entry.draftTarget || "").trim(),
      aliases: (entry.aliases || []).map((alias) => String(alias || "").trim()).filter(Boolean),
    })),
  };
}

// ---- rows table presentation (absent source columns, derived status, truncation) ----

/** 上游整个接口都不返回该列时的单元格文案：明示来源缺失，区分"源端不提供"与"真实空值"。 */
export const FORM_ABSENT_SOURCE_TEXT = "源端不提供";

/**
 * 长文本列在明细表里截断成单行（CSS ellipsis），完整值进 title 悬浮；
 * 「查看全部字段」明细始终有全值，不丢数据。表头不截断。
 * 列名来自各报表的展示契约（services/deliverable_form_analysis._KEY_COLUMN_LABELS
 * 与 TDC 47 列导出表头）。
 */
export const FORM_TRUNCATED_COLUMN_LABELS = new Set([
  "流程名", // 数模
  "零件名称", // 数模 / SOR / NCR明细
  "零件或总成名称", // PAA
  "标题", // SOR
  "主题", // EWO
  "最新审批记录", // 数模默认可见列收尾（审批日志长文本）
]);

/** 服务端在建快照时判定的「上游完全未提供」位置列（sourceAbsentIndexes）。 */
export function formAbsentSourceIndexes(data) {
  return new Set(
    Array.isArray(data && data.sourceAbsentIndexes)
      ? data.sourceAbsentIndexes
        .filter((index) => index !== null && index !== "" && typeof index !== "boolean")
        .map((index) => Number(index))
        .filter((index) => Number.isFinite(index))
      : [],
  );
}

export function formColumnIndex(column) {
  const index = Number(column && column.index);
  return Number.isFinite(index) ? index : NaN;
}

/**
 * 明细表显示列。数模（47 列位置契约）的「状态」物理列在末位（index 46），横向排开不可见：
 * 在「部门」后插入「状态」派生列（读行维度 dimensions.status 的归一化文本，不动
 * values 物理列序；历史快照同样适用）。
 */
export function formDisplayColumns(data, visibleColumns) {
  const display = visibleColumns.slice();
  if (String((data && data.formKey) || "") === "tdc_data_model" && !display.some((column) => column && column.derivedStatus)) {
    const derived = { label: "状态", derivedStatus: true };
    const deptPos = display.findIndex((column) => column && column.label === "部门");
    if (deptPos >= 0) display.splice(deptPos + 1, 0, derived);
    else display.splice(Math.min(1, display.length), 0, derived);
  }
  return display;
}

/** One body cell: {text, className, title}. */
export function formRowCell(column, item, absent) {
  if (column && column.derivedStatus) {
    const dimensions = item && item.dimensions && typeof item.dimensions === "object" ? item.dimensions : null;
    return { text: dimensions ? dimensions.status : null, className: "", title: "" };
  }
  const index = formColumnIndex(column);
  if (absent.has(index)) return { text: FORM_ABSENT_SOURCE_TEXT, className: "form-cell-absent", title: "", absent: true };
  const values = Array.isArray(item && item.values) ? item.values : [];
  return { text: values[Number.isFinite(index) ? index : 0], className: "", title: "" };
}
