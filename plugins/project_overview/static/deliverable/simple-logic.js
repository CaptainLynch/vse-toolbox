// 简洁视图的纯逻辑（不 import preact，Node 测试可直接 import）：阶段文案、逾期列、
// 派生进度、同步结果文案、自适应排序、单号提取与可见列计算。
// 为什么单独成文件：这些口径必须能被门禁直接断言，而不是只能靠浏览器里看。
import { redactSensitiveText } from "./format.js";

/** 阶段展示名的唯一来源是后端 schema.stageLabels（core.form_registry 的 stage_labels）。
 *  前端不另写阶段文案表；未登记的阶段回退原码，空阶段回退源表状态。 */
export function stageLabel(schema, row) {
  const labels = (schema && schema.stageLabels) || {};
  const dims = (row && row.dimensions) || {};
  const stage = String(dims.stage || "").trim();
  if (stage) return labels[stage] || stage;
  return String(dims.status || "").trim();
}

/** 逾期独立成列：已完成行不判逾期；未知/不适用显示「—」，不猜测。 */
export function overdueLabel(row) {
  if (!row || row.isCompleted) return "—";
  if (row.overdueState === "overdue") return "是";
  if (row.overdueState === "on_time") return "否";
  return "—";
}

/** 派生进度：快照态按明细 completed/total 换算，其余状态回退手工值。
 *  value=null 表示没有可信数值 —— 界面显示「—」，不编造 0%。 */
export function progressDisplay(item) {
  const raw = item && item.effectiveProgress !== undefined ? item.effectiveProgress : (item ? item.progress : null);
  if (raw === null || raw === undefined || raw === "") return { value: null, text: "—", derived: false };
  const value = Number(raw);
  if (!Number.isFinite(value)) return { value: null, text: "—", derived: false };
  const clamped = Math.max(0, Math.min(100, Math.round(value)));
  return { value: clamped, text: `${clamped}%`, derived: Boolean(item && item.progressSource === "snapshot") };
}

/** 同步结果文案：只有真的应用了字段才叫「更新」；内容未变的幂等跳过叫「无变化」；
 *  失败必须显式报错——接口对 failed 也返回 HTTP 200，只看 HTTP 成功会把失败说成完成。 */
export function syncResultText(data) {
  const result = (data && data.result) || {};
  const state = String(result.finalState || "");
  const outcome = String(result.outcome || "");
  const applied = Array.isArray(result.appliedFields) ? result.appliedFields.length : 0;
  if (state === "failed" || outcome === "failed") {
    const reason = redactSensitiveText(String(result.errorMessage || result.errorType || "请查看同步记录"));
    return `同步失败：${reason}`;
  }
  if (state === "needs_attention" || outcome === "needs_attention") {
    const reason = redactSensitiveText(String(result.errorMessage || result.errorType || "请查看同步记录"));
    return `同步需要处理：${reason}`;
  }
  if (applied > 0) return `同步完成，更新 ${applied} 项`;
  return "已同步，上游无变化";
}

// ── 简表列口径与显隐计算 ──────────────────────────────────────────────────

export const PREFERRED_LABELS = [
  "流水单号", "NCR编号", "EWO编号", "PAA编号", "SOR号", "零件名称",
  "更改主题", "标题", "申请人", "部门", "申请日期", "提交日期",
];
export const MAX_COLUMNS = 5;

/** 列身份的唯一取法：优先 c.key，缺失（含空串）回退 c.index。
 *  排序、显隐、复制、表头/单元格 key 全部走这里，避免各处各写一套回退。 */
export function columnKeyOf(column) {
  if (!column) return "";
  const key = column.key;
  if (key !== undefined && key !== null && String(key) !== "") return String(key);
  if (column.index !== undefined && column.index !== null) return String(column.index);
  return "";
}

/** 候选列：排除源表「状态」（阶段与逾期已独立成列），排除全空列。 */
export function candidateColumns(schema, rows = []) {
  const filled = (column) => !rows.length || rows.some((row) => {
    const value = Array.isArray(row.values) ? row.values[column.index] : null;
    return value !== null && value !== undefined && String(value).trim() !== "";
  });
  return (Array.isArray(schema && schema.columns) ? schema.columns : []).filter((c) => c && c.label !== "状态" && filled(c));
}

/** 简表默认挑选的列（按偏好标签顺序，最多 5 列）。 */
export function simpleColumns(schema, rows = []) {
  const columns = candidateColumns(schema, rows);
  const picked = [];
  PREFERRED_LABELS.forEach((label) => {
    const column = columns.find((c) => c && c.label === label);
    if (column && picked.length < MAX_COLUMNS && !picked.includes(column)) picked.push(column);
  });
  if (picked.length < 3) {
    const keys = Array.isArray(schema && schema.keyColumns) ? schema.keyColumns : [];
    keys.forEach((index) => {
      const column = columns.find((c) => c && c.index === Number(index));
      if (column && picked.length < MAX_COLUMNS && !picked.includes(column)) picked.push(column);
    });
  }
  columns.forEach((column) => {
    if (picked.length < 3 && !picked.includes(column)) picked.push(column);
  });
  return picked;
}

/**
 * 可见列计算：
 * - candidateCols: 表单所有可用候选列；
 * - preferences: 存储的列显隐偏好（支持 { visibleKeys }、{ hiddenKeys } 或 key 数组）；
 * - defaultCols: 未配置或偏好为空时的默认列（simpleColumns 计算结果）。
 * 保底至少返回一列，避免用户全部取消勾选后表格完全坍塌。
 */
export function calculateVisibleColumns(candidateCols, preferences, defaultCols = []) {
  const candidates = Array.isArray(candidateCols) ? candidateCols : [];
  const defaults = Array.isArray(defaultCols) && defaultCols.length > 0 ? defaultCols : candidates.slice(0, MAX_COLUMNS);
  if (!preferences) return defaults;

  const visibleKeys = Array.isArray(preferences)
    ? preferences
    : (Array.isArray(preferences.visibleKeys) ? preferences.visibleKeys : null);

  if (visibleKeys !== null) {
    const keySet = new Set(visibleKeys.map(String));
    const matched = candidates.filter((col) => {
      if (!col) return false;
      const k = columnKeyOf(col);
      return keySet.has(k) || keySet.has(String(col.index)) || keySet.has(String(col.label));
    });
    return matched.length > 0 ? matched : defaults.slice(0, 1);
  }

  const hiddenKeys = Array.isArray(preferences.hiddenKeys) ? preferences.hiddenKeys : null;
  if (hiddenKeys !== null) {
    const hiddenSet = new Set(hiddenKeys.map(String));
    const matched = defaults.filter((col) => {
      if (!col) return false;
      const k = columnKeyOf(col);
      return !hiddenSet.has(k) && !hiddenSet.has(String(col.index)) && !hiddenSet.has(String(col.label));
    });
    return matched.length > 0 ? matched : defaults.slice(0, 1);
  }

  return defaults;
}

/**
 * 列显隐切换：返回下一次可见列的 key 列表；拒绝时返回 null。
 * - 勾选：仅接受候选列中存在的列，重复勾选保持原样；
 * - 取消勾选：隐藏最后一列时拒绝（返回 null），保证表格至少保留一列。
 */
export function toggleColumnVisibility(visibleCols, colKey, checked, candidateCols = []) {
  const visibleKeys = (Array.isArray(visibleCols) ? visibleCols : []).filter(Boolean).map(columnKeyOf);
  const key = String(colKey);
  if (checked) {
    const candidates = (Array.isArray(candidateCols) ? candidateCols : []).filter(Boolean).map(columnKeyOf);
    if (!candidates.includes(key) && !visibleKeys.includes(key)) return null;
    return Array.from(new Set([...visibleKeys, key]));
  }
  if (!visibleKeys.includes(key)) return visibleKeys;
  if (visibleKeys.length <= 1) return null;
  return visibleKeys.filter((k) => k !== key);
}

// ── 自适应排序逻辑 ───────────────────────────────────────────────────────

/** 尝试将字符串解析为纯数值，带千分位支持；非纯数字返回 null。 */
export function parseNumericLike(value) {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "boolean") return null;
  const str = String(value).trim().replace(/,/g, "");
  if (!str || !/^-?\d+(\.\d+)?$/.test(str)) return null;
  const num = Number(str);
  return Number.isFinite(num) ? num : null;
}

/**
 * 字符串与数字自适应比较函数：
 * - 双方均可解析为数值时按数值比较；
 * - 其它情况按中文本地自然序（带数字感知 numeric: true）比较；
 * - 空值（null / undefined / ""）恒排在最后。
 */
export function compareAdaptive(a, b) {
  const aEmpty = a === null || a === undefined || a === "";
  const bEmpty = b === null || b === undefined || b === "";
  if (aEmpty && bEmpty) return 0;
  if (aEmpty) return 1;
  if (bEmpty) return -1;

  const numA = parseNumericLike(a);
  const numB = parseNumericLike(b);
  if (numA !== null && numB !== null) {
    return numA - numB;
  }
  return String(a).localeCompare(String(b), "zh-Hans-CN", { numeric: true, sensitivity: "base" });
}

/** 排序状态三态轮转：升序(asc) -> 降序(desc) -> 恢复默认(null)。切换列时从升序重新开始。 */
export function nextSortState(current, targetKey) {
  const currKey = current && current.key;
  const currDir = current && current.direction;
  if (currKey !== targetKey) {
    return { key: targetKey, direction: "asc" };
  }
  if (currDir === "asc") {
    return { key: targetKey, direction: "desc" };
  }
  return { key: null, direction: null };
}

/** 读取用于比对的单元格可排序值。 */
export function getRowCellValue(row, colKey, options = {}) {
  if (!row) return null;
  if (colKey === "stage") {
    return row.isCompleted ? "已完成" : (stageLabel(options.schema, row) || "进行中");
  }
  if (colKey === "overdue") {
    return overdueLabel(row);
  }
  const columns = (options && Array.isArray(options.columns)) ? options.columns : [];
  const col = columns.find((c) => c && (columnKeyOf(c) === String(colKey) || String(c.index) === String(colKey)));
  if (col && Array.isArray(row.values) && col.index < row.values.length) {
    return row.values[col.index];
  }
  if (Array.isArray(row.values) && typeof colKey === "number" && colKey < row.values.length) {
    return row.values[colKey];
  }
  if (row[colKey] !== undefined) return row[colKey];
  return null;
}

/** 表头描述：key 缺失回退 index，排序箭头与 aria-sort 也由同一 key 推导。
 *  simple.js 只按描述渲染，不再各自计算列身份。 */
export function tableHeaders(visibleCols, sortState) {
  return (Array.isArray(visibleCols) ? visibleCols : []).filter(Boolean).map((col) => {
    const key = columnKeyOf(col);
    const sorted = Boolean(sortState && sortState.key === key);
    const direction = sorted ? sortState.direction : null;
    return {
      key,
      label: col.label,
      sortKey: key,
      sorted,
      direction,
      ariaSort: direction === "asc" ? "ascending" : direction === "desc" ? "descending" : "none",
      arrow: direction === "asc" ? " ▲" : direction === "desc" ? " ▼" : "",
    };
  });
}

/**
 * 简表数据行排序：
 * - sortState: { key, direction }；
 * - getValue: 自定义取值函数 (row, key) => value；
 * - direction 为 null 或空时恢复原顺序（返回浅拷贝，不破坏原数据）。
 * - 空值在升序与降序下均恒排在末尾。
 * - 相等元素显式按原下标兜底，稳定排序不依赖引擎实现。
 */
export function sortRows(rows, sortState, getValue) {
  if (!Array.isArray(rows)) return [];
  if (!sortState || !sortState.key || !sortState.direction) return rows.slice();
  const { key, direction } = sortState;
  const mult = direction === "desc" ? -1 : 1;
  return rows
    .map((row, index) => ({ row, index }))
    .sort((a, b) => {
      const valA = getValue ? getValue(a.row, key) : a.row[key];
      const valB = getValue ? getValue(b.row, key) : b.row[key];
      const aEmpty = valA === null || valA === undefined || valA === "";
      const bEmpty = valB === null || valB === undefined || valB === "";
      if (aEmpty && bEmpty) return a.index - b.index;
      if (aEmpty) return 1;
      if (bEmpty) return -1;
      return compareAdaptive(valA, valB) * mult || (a.index - b.index);
    })
    .map((entry) => entry.row);
}

// ── 单号识别与复制提取 ───────────────────────────────────────────────────

export const SERIAL_NUMBER_LABELS = ["流水单号", "NCR编号", "EWO编号", "PAA编号", "SOR号"];

/** 从 schema 中找出最具单号特征的列定义。 */
export function findSerialNumberColumn(schema) {
  const cols = (schema && Array.isArray(schema.columns)) ? schema.columns : [];
  for (const label of SERIAL_NUMBER_LABELS) {
    const found = cols.find((c) => c && c.label === label);
    if (found) return found;
  }
  const match = cols.find((c) => c && c.label && (c.label.includes("单号") || c.label.includes("编号")));
  if (match) return match;
  if (schema && Array.isArray(schema.keyColumns) && schema.keyColumns.length > 0) {
    const firstIdx = Number(schema.keyColumns[0]);
    const keyCol = cols.find((c) => c && c.index === firstIdx);
    if (keyCol) return keyCol;
  }
  return cols[0] || null;
}

/** 复制按钮所在列的 key：优先单号列；单号列未显示（或被隐藏）时退回第一可见列。
 *  列 key 缺失时由 columnKeyOf 回退 index，复制按钮不会因缺 key 消失。 */
export function serialCopyColumnKey(schema, visibleCols) {
  const cols = (Array.isArray(visibleCols) ? visibleCols : []).filter(Boolean);
  if (!cols.length) return "";
  const serialCol = findSerialNumberColumn(schema);
  const serialKey = serialCol ? columnKeyOf(serialCol) : "";
  if (serialKey && cols.some((col) => columnKeyOf(col) === serialKey)) return serialKey;
  return columnKeyOf(cols[0]);
}

/** 从行数据中提取单号字符串。 */
export function extractSerialNumber(row, schema) {
  if (!row) return "";
  const col = findSerialNumberColumn(schema);
  if (col && Array.isArray(row.values) && col.index < row.values.length) {
    const val = row.values[col.index];
    if (val !== null && val !== undefined && String(val).trim() !== "") {
      return String(val).trim();
    }
  }
  if (row.serialNumber) return String(row.serialNumber).trim();
  if (row.serial) return String(row.serial).trim();
  if (row._no) return String(row._no).trim();
  return "";
}

/** 浏览器剪贴板复制降级封装。 */
export async function copyTextToClipboard(text) {
  if (!text) return false;
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (_e) {}
  try {
    if (typeof document !== "undefined") {
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(area);
      return ok;
    }
  } catch (_e) {}
  return false;
}

// ── 本地存储偏好封装 ─────────────────────────────────────────────────────

export const COLUMN_PREF_STORAGE_KEY = "vse.simple-table.columns";

export function loadColumnPreferences(formKey, storage) {
  try {
    const store = storage || (typeof window !== "undefined" ? window.localStorage : null);
    if (!store) return null;
    const raw = store.getItem(COLUMN_PREF_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && formKey ? (parsed[formKey] || null) : null;
  } catch (_e) {
    return null;
  }
}

export function saveColumnPreferences(formKey, prefs, storage) {
  try {
    const store = storage || (typeof window !== "undefined" ? window.localStorage : null);
    if (!store || !formKey) return false;
    let all = {};
    try {
      const raw = store.getItem(COLUMN_PREF_STORAGE_KEY);
      if (raw) all = JSON.parse(raw) || {};
    } catch (_e) {}
    if (prefs === null || prefs === undefined) {
      delete all[formKey];
    } else {
      all[formKey] = prefs;
    }
    store.setItem(COLUMN_PREF_STORAGE_KEY, JSON.stringify(all));
    return true;
  } catch (_e) {
    return false;
  }
}
