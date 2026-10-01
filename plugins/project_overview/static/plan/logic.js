// Pure, import-free logic of the 主计划维护 page (ported from the legacy
// overview in web/static/app.js). Kept free of DOM/host imports so it can be
// unit-tested under Node.

export const PHASE_STATUS_OPTIONS = ["未开始", "进行中", "已完成", "暂停"];

export const MILESTONE_TYPE_OPTIONS = [
  { value: "planned", label: "未开始" },
  { value: "current", label: "进行中" },
  { value: "done", label: "已完成" },
  { value: "overdue", label: "已超期" },
];

export const MILESTONE_LABEL_BY_TYPE = {
  planned: "未开始",
  current: "进行中",
  done: "已完成",
  overdue: "已超期",
  "未开始": "未开始",
  "进行中": "进行中",
  "已完成": "已完成",
  "已超期": "已超期",
};

export const MILESTONE_TYPE_BY_STATUS = {
  "未开始": "planned",
  "进行中": "current",
  "已完成": "done",
  "已超期": "planned",
};

export const DISCARD_CONFIRM = "有未保存的更改，确定放弃吗？";
export const SWITCH_TO_MILESTONES_CONFIRM = "有未保存的更改，放弃后将继续编辑主计划？";
export const RESTORE_NOTICE = "已删除全部节点，已自动恢复默认节点模板";

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

function text(value) {
  return value === null || value === undefined ? "" : String(value);
}

/** Same rule as the legacy overviewIsEmpty: a usable status needs phase, milestones and deliverables. */
export function isEmptyStatus(data) {
  return !data
    || !data.phase
    || !Array.isArray(data.milestones) || data.milestones.length === 0
    || !Array.isArray(data.deliverables) || data.deliverables.length === 0;
}

// ---------------------------------------------------------------- phase

export function phaseDraftFrom(phase) {
  const p = phase || {};
  return {
    kind: "phase",
    displayName: text(p.displayName || p.id),
    status: text(p.status || "进行中"),
    startDate: text(p.startDate),
    endDate: text(p.endDate),
    updatedAt: text(p.updatedAt),
  };
}

export function phaseDraftDirty(phase, draft) {
  if (!phase || !draft) return false;
  return (
    text(draft.displayName) !== text(phase.displayName || phase.id)
    || text(draft.status) !== text(phase.status)
    || text(draft.startDate) !== text(phase.startDate)
    || text(draft.endDate) !== text(phase.endDate)
  );
}

/** Legacy savePhaseMetadataChanges client checks; returns {error} or {payload}. */
export function buildPhasePayload(draft) {
  const displayName = text(draft.displayName).trim();
  const status = text(draft.status).trim();
  const startDate = text(draft.startDate).trim();
  const endDate = text(draft.endDate).trim();
  if (!displayName) return { error: "主计划名称不能为空" };
  if (!PHASE_STATUS_OPTIONS.includes(status)) return { error: "阶段状态无效" };
  if (!DATE_PATTERN.test(startDate) || !DATE_PATTERN.test(endDate)) return { error: "日期格式应为 YYYY-MM-DD" };
  if (startDate > endDate) return { error: "计划完成日期不能早于开始日期" };
  return { payload: { displayName, status, startDate, endDate, updatedAt: draft.updatedAt } };
}

/**
 * Inline rename of the master plan: null when nothing should be saved
 * (empty or unchanged name), else the PATCH body keeping the other fields.
 */
export function buildPhaseNamePayload(phase, rawName) {
  const p = phase || {};
  const current = text(p.displayName || p.id);
  const name = text(rawName).trim();
  if (!name || name === current) return null;
  return {
    displayName: name,
    status: p.status,
    startDate: p.startDate,
    endDate: p.endDate,
    updatedAt: p.updatedAt,
  };
}

// ----------------------------------------------------------- milestones

export function milestoneRowsFrom(milestones) {
  return (Array.isArray(milestones) ? milestones : []).map((item, index) => ({
    localId: `m${index}`,
    id: item.id ?? null,
    name: text(item.name),
    date: text(item.date),
    status: text(item.status || (MILESTONE_LABEL_BY_TYPE[item.type] || "未开始")),
    type: MILESTONE_TYPE_BY_STATUS[item.status] || item.type || "planned",
    sortOrder: typeof item.sortOrder === "number" ? item.sortOrder : index + 1,
  }));
}

function savedValue(item, field, index) {
  if (field === "sortOrder") return typeof item.sortOrder === "number" ? item.sortOrder : index + 1;
  return text(item[field]);
}

export function milestoneDraftDirty(savedMilestones, rows) {
  const saved = Array.isArray(savedMilestones) ? savedMilestones : [];
  const list = Array.isArray(rows) ? rows : [];
  if (list.length !== saved.length) return true;
  return list.some((row, index) => {
    const item = saved[index] || {};
    return text(row.id) !== text(item.id)
      || row.name !== savedValue(item, "name", index)
      || row.date !== savedValue(item, "date", index)
      || row.type !== savedValue(item, "type", index)
      || row.sortOrder !== savedValue(item, "sortOrder", index);
  });
}

/** The select value shown for a row (unknown types fall back to planned). */
export function rowTypeValue(row) {
  return MILESTONE_TYPE_OPTIONS.some((option) => option.value === row.type) ? row.type : "planned";
}

/** Apply one field edit to a row (a type change also sets the status label). */
export function updateRow(row, field, value) {
  const next = { ...row, [field]: value };
  if (field === "type") next.status = MILESTONE_LABEL_BY_TYPE[value] || "未开始";
  return next;
}

export function newMilestoneRow(seq, length) {
  return { localId: `new-${seq}`, id: null, name: "", date: "", status: "", type: "planned", sortOrder: length + 1 };
}

/** Move a row up (-1) or down (+1); returns the same array when the move is impossible. */
export function moveRow(rows, localId, delta) {
  const index = rows.findIndex((row) => row.localId === localId);
  const target = index + delta;
  if (index < 0 || target < 0 || target >= rows.length) return rows;
  const next = rows.slice();
  const [moved] = next.splice(index, 1);
  next.splice(target, 0, moved);
  return next;
}

/** Remove a row; `focus` is the localId to focus next, or null (focus 新增节点). */
export function removeRow(rows, localId) {
  const index = rows.findIndex((row) => row.localId === localId);
  if (index < 0) return { rows, focus: undefined };
  const next = rows.slice();
  next.splice(index, 1);
  const follower = next[Math.min(index, next.length - 1)];
  return { rows: next, focus: follower ? follower.localId : null };
}

/**
 * Legacy validateMilestoneDraft: errors keyed `${localId}.${field}`.
 * 空日期 = 待排期, allowed only for 未开始 nodes; dates must lie inside the
 * phase window; a 已完成 node may not be dated after `phase.today`. A past
 * date on a planned node stays valid (it is simply overdue).
 */
export function validateMilestoneRows(rows, phase) {
  const errors = {};
  const start = phase ? text(phase.startDate) : "";
  const end = phase ? text(phase.endDate) : "";
  const today = phase ? text(phase.today) : "";
  const seenNames = new Set();
  (rows || []).forEach((row) => {
    const name = text(row.name).trim();
    const date = text(row.date).trim();
    const nameKey = `${row.localId}.name`;
    const dateKey = `${row.localId}.date`;
    if (!name) errors[nameKey] = "节点名称为必填项";
    else if (name.length > 100) errors[nameKey] = "节点名称不能超过 100 个字符";
    else if (seenNames.has(name)) errors[nameKey] = "节点名称不能重复";
    seenNames.add(name);
    const status = row.status || MILESTONE_LABEL_BY_TYPE[row.type] || "未开始";
    if (!date) {
      if (status !== "未开始") errors[dateKey] = "空日期节点状态必须为未开始";
    } else if (!DATE_PATTERN.test(date)) {
      errors[dateKey] = "日期格式应为 YYYY-MM-DD";
    } else if (start && end && (date < start || date > end)) {
      errors[dateKey] = `节点日期需在阶段周期 ${start} 至 ${end} 内`;
    }
    if (!errors[dateKey] && date && (row.type === "done" || row.status === "已完成") && today && date > today) {
      errors[dateKey] = `已达成节点日期不能晚于当前日期 ${today}`;
    }
  });
  return errors;
}

export function buildMilestonePayload(rows, updatedAt) {
  return {
    milestones: (rows || []).map((row, index) => {
      const status = row.status || MILESTONE_LABEL_BY_TYPE[row.type] || "未开始";
      const nodeType = MILESTONE_TYPE_BY_STATUS[status] || row.type || "planned";
      return {
        id: row.id ?? null,
        name: text(row.name).trim(),
        date: text(row.date).trim(),
        status,
        type: nodeType,
        sortOrder: index + 1,
      };
    }),
    updatedAt: updatedAt || "",
  };
}

/** Map server `fields` (e.g. `milestones.2.date`) onto draft rows; unplaceable ones go to `draft`. */
export function mapServerFieldErrors(fields, rows) {
  const list = rows || [];
  const errors = {};
  Object.keys(fields || {}).forEach((key) => {
    const message = text(fields[key]);
    // Only `milestones...` keys belong to a row; e.g. `updatedAt` / `request`
    // go to the form message (legacy mapped `updatedAt` onto row 1's date).
    if (!/^milestones\b/.test(String(key))) {
      errors.draft = message;
      return;
    }
    const match = String(key).match(/\[(\d+)\]|\.(\d+)\b/);
    const index = match ? Number(match[1] ?? match[2]) : -1;
    const row = list[index] || list[0];
    if (!row) return;
    if (/name/.test(key)) errors[`${row.localId}.name`] = message;
    else if (/date/.test(key)) errors[`${row.localId}.date`] = message;
    else if (/type|status/.test(key)) errors[`${row.localId}.type`] = message;
    else errors.draft = message;
  });
  return errors;
}

/** Drop the error of one field (the legacy row clears its error on input). */
export function clearFieldError(errors, localId, field) {
  const key = `${localId}.${field}`;
  if (!errors || !(key in errors)) return errors;
  const next = { ...errors };
  delete next[key];
  return next;
}

/** Legacy overviewErrorMessage: "<message>（HTTP <status>）"; 403 → local-only notice. */
export function requestErrorText(err) {
  if (!err) return "";
  const status = Number(err.status) || 0;
  if (status === 403) return "该操作只允许在本机浏览器中执行";
  const message = err.message || String(err);
  return status ? `${message}（HTTP ${status}）` : message;
}

/** Readonly display: "-" for blank values (legacy safeDisplayValue). */
export function displayValue(value) {
  const t = text(value);
  return t.trim() ? t : "-";
}
