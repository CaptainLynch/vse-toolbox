// 向导 → 项目总览「一键开启自动同步」的宿主交接模块（契约 C1：前端公共流程放 host/，
// 插件只经 /static/host/... 引用，禁止跨插件 import）。
//
// 职责：
// 1. 保存向导里用户真正勾选的交付物（selectedDeliverables）以及车型、科室、项目；
// 2. 记录「首次启用同步」请求和逐项结果；
// 3. 整体完成状态只由真实任务结果推导：仅跳页、未开始或失败都不得算全部完成。

export const SELECTION_KEY = "vse.onboardingSelection";
export const FIRST_SYNC_KEY = "vse.onboardingFirstSync";

/** 逐项状态：未开始 / 进行中 / 成功 / 部分成功 / 失败。 */
// not_applicable：向导选中但不参与自动同步（只能手工维护或早已开启），不计入完成判定。
export const ENTRY_STATES = ["not_started", "running", "success", "partial", "failed", "not_applicable"];

/** 请求整体状态：空 / 待开始 / 进行中 / 部分完成 / 全部完成 / 全部失败。 */
export const REQUEST_STATES = ["empty", "pending", "running", "partial", "completed", "failed"];

function text(value) {
  return value === null || value === undefined ? "" : String(value).trim();
}

function defaultStorage() {
  try {
    if (typeof window !== "undefined" && window.localStorage) return window.localStorage;
  } catch (_err) {}
  return null;
}

function resolveStorage(explicit) {
  if (explicit && typeof explicit.getItem === "function") return explicit;
  return defaultStorage();
}

function readObject(storage, key) {
  if (!storage) return null;
  try {
    const raw = storage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : null;
  } catch (_err) {
    return null;
  }
}

function writeObject(storage, key, value) {
  if (!storage) return false;
  try {
    storage.setItem(key, JSON.stringify(value));
    return true;
  } catch (_err) {
    return false;
  }
}

function removeObject(storage, key) {
  if (!storage) return;
  try {
    storage.removeItem(key);
  } catch (_err) {}
}

/** 交付物 ID 去重、去空、按字符串处理；非法输入一律当空。 */
export function sanitizeDeliverableIds(input) {
  if (!Array.isArray(input)) return [];
  const seen = new Set();
  const out = [];
  for (const raw of input) {
    const id = text(raw);
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push(id);
  }
  return out;
}

function sanitizeDepartments(input) {
  if (!Array.isArray(input)) return [];
  const seen = new Set();
  const out = [];
  for (const raw of input) {
    const name = text(raw);
    if (!name || seen.has(name)) continue;
    seen.add(name);
    out.push(name);
  }
  return out;
}

/** 保存向导选择；空数组表示用户明确没有勾选任何交付物。 */
export function saveOnboardingSelection(input = {}, storage) {
  const clean = {
    deliverables: sanitizeDeliverableIds(input.deliverables),
    vehicle: text(input.vehicle),
    departments: sanitizeDepartments(input.departments),
    projectId: text(input.projectId),
    savedAt: new Date().toISOString(),
  };
  writeObject(resolveStorage(storage), SELECTION_KEY, clean);
  return clean;
}

export function readOnboardingSelection(storage) {
  const raw = readObject(resolveStorage(storage), SELECTION_KEY);
  if (!raw) return null;
  return {
    deliverables: sanitizeDeliverableIds(raw.deliverables),
    vehicle: text(raw.vehicle),
    departments: sanitizeDepartments(raw.departments),
    projectId: text(raw.projectId),
    savedAt: text(raw.savedAt),
  };
}

export function clearOnboardingSelection(storage) {
  removeObject(resolveStorage(storage), SELECTION_KEY);
}

export function sanitizeFirstSyncEntry(raw) {
  if (!raw || typeof raw !== "object") return null;
  const id = text(raw.id);
  if (!id) return null;
  return {
    id,
    name: text(raw.name),
    state: ENTRY_STATES.includes(raw.state) ? raw.state : "not_started",
    text: text(raw.text),
  };
}

/** 整体状态只由逐项状态推导；completed 要求每一项都真实成功。 */
export function firstSyncStatus(entries) {
  const all = Array.isArray(entries) ? entries : [];
  if (!all.length) return "empty";
  const list = all.filter((entry) => entry.state !== "not_applicable");
  if (!list.length) return "completed";
  if (list.some((entry) => entry.state === "running")) return "running";
  const success = list.filter((entry) => entry.state === "success").length;
  if (success === list.length) return "completed";
  const started = list.filter((entry) => entry.state !== "not_started").length;
  if (!started) return "pending";
  const failed = list.filter((entry) => entry.state === "failed").length;
  if (!success && failed === started) return "failed";
  return "partial";
}

export function summarizeFirstSync(entries) {
  const all = Array.isArray(entries) ? entries : [];
  // 不适用项单独计数，不进入完成判定的分母。
  const notApplicable = all.filter((entry) => entry.state === "not_applicable").length;
  const list = all.filter((entry) => entry.state !== "not_applicable");
  const count = (states) => list.filter((entry) => states.includes(entry.state)).length;
  const success = count(["success"]);
  const partial = count(["partial"]);
  const failed = count(["failed"]);
  const running = count(["running"]);
  const notStarted = count(["not_started"]);
  return {
    total: list.length,
    success,
    partial,
    failed,
    running,
    notStarted,
    notApplicable,
    // 只有每一个适用项都真实成功才算全部完成；未开始、进行中、失败都不算。
    // 选中项全部不适用（无可同步项）时没有待做的首次同步，视为完成。
    allDone: all.length > 0 && success === list.length,
    finished: all.length > 0 && success + partial + failed === list.length,
  };
}

export function normalizeFirstSyncRequest(raw) {
  if (!raw || typeof raw !== "object") return null;
  const deliverables = sanitizeDeliverableIds(raw.deliverables);
  const byId = new Map();
  for (const item of Array.isArray(raw.entries) ? raw.entries : []) {
    const entry = sanitizeFirstSyncEntry(item);
    if (entry) byId.set(entry.id, entry);
  }
  const entries = deliverables.map((id) => {
    const entry = byId.get(id);
    return entry ? { ...entry } : { id, name: "", state: "not_started", text: "" };
  });
  return {
    status: firstSyncStatus(entries),
    deliverables,
    entries,
    vehicle: text(raw.vehicle),
    departments: sanitizeDepartments(raw.departments),
    projectId: text(raw.projectId),
    requestedAt: text(raw.requestedAt),
    updatedAt: text(raw.updatedAt),
  };
}

function persistFirstSync(request, storage) {
  const normalized = normalizeFirstSyncRequest(request);
  if (!normalized) return null;
  normalized.updatedAt = new Date().toISOString();
  writeObject(resolveStorage(storage), FIRST_SYNC_KEY, normalized);
  return normalized;
}

/** 向导点「开启自动同步」时登记首次同步请求：所有项先记为未开始。 */
export function requestFirstSync(input = {}, storage) {
  const selection = saveOnboardingSelection(input, storage);
  const now = new Date().toISOString();
  const entries = selection.deliverables.map((id) => ({ id, name: "", state: "not_started", text: "" }));
  const request = {
    status: firstSyncStatus(entries),
    deliverables: selection.deliverables.slice(),
    entries,
    vehicle: selection.vehicle,
    departments: selection.departments.slice(),
    projectId: selection.projectId,
    requestedAt: now,
    updatedAt: now,
  };
  writeObject(resolveStorage(storage), FIRST_SYNC_KEY, request);
  return normalizeFirstSyncRequest(request);
}

export function readFirstSyncRequest(storage) {
  return normalizeFirstSyncRequest(readObject(resolveStorage(storage), FIRST_SYNC_KEY));
}

/** 真实任务开始执行时把对应项记为进行中（跳页不会调用这里）。 */
export function markFirstSyncRunning(ids, storage) {
  const request = readFirstSyncRequest(storage);
  if (!request) return null;
  const wanted = new Set(sanitizeDeliverableIds(ids));
  const entries = request.entries.map((entry) => (wanted.has(entry.id)
    ? { ...entry, state: "running", text: "首次同步进行中" }
    : entry));
  return persistFirstSync({ ...request, entries }, storage);
}

function transitionFirstSync(storage, change) {
  const request = readFirstSyncRequest(storage);
  if (!request) return null;
  let touched = false;
  const entries = request.entries.map((entry) => {
    const next = change(entry);
    if (next && next !== entry) { touched = true; return next; }
    return entry;
  });
  return touched ? persistFirstSync({ ...request, entries }, storage) : request;
}

/**
 * 选中但不参与本次自动同步的项（只能手工维护、早已开启）标为不适用，
 * 避免它们永远停在「未开始」导致首次同步无法完成。只改未开始/进行中的项，不覆盖真实结果。
 */
export function markFirstSyncNotApplicable(items, storage) {
  const byId = new Map();
  for (const item of Array.isArray(items) ? items : []) {
    const id = text(item && item.id);
    if (id) byId.set(id, item);
  }
  if (!byId.size) return readFirstSyncRequest(storage);
  return transitionFirstSync(storage, (entry) => {
    const item = byId.get(entry.id);
    if (!item || !["not_started", "running"].includes(entry.state)) return null;
    return { ...entry, name: text(item.name) || entry.name, state: "not_applicable", text: text(item.text) || "不参与自动同步" };
  });
}

/** 本次运行结束（含中途异常）时仍为进行中的项改记为失败：运行在页面内，结束后不可能仍在跑。 */
export function failRunningFirstSync(reason, storage) {
  const note = text(reason) || "首次同步没有完成（运行中断）";
  return transitionFirstSync(storage, (entry) => (entry.state === "running"
    ? { ...entry, state: "failed", text: note }
    : null));
}

/** 页面重新打开时，上次遗留的「进行中」不可能仍在执行（首次同步只在页面内跑），恢复为未开始。 */
export function recoverInterruptedFirstSync(storage) {
  return transitionFirstSync(storage, (entry) => (entry.state === "running"
    ? { ...entry, state: "not_started", text: "上次首次同步被中断，请重新开启" }
    : null));
}

/** 记录一项真实结果；状态只接受枚举值，未知一律未开始。 */
export function recordFirstSyncEntry(entry, storage) {
  const request = readFirstSyncRequest(storage);
  if (!request) return null;
  const clean = sanitizeFirstSyncEntry(entry);
  if (!clean || !request.deliverables.includes(clean.id)) return request;
  const entries = request.entries.map((item) => (item.id === clean.id
    ? { id: item.id, name: clean.name || item.name, state: clean.state, text: clean.text }
    : item));
  return persistFirstSync({ ...request, entries }, storage);
}

export function recordFirstSyncEntries(list, storage) {
  let request = readFirstSyncRequest(storage);
  if (!request) return null;
  for (const item of Array.isArray(list) ? list : []) {
    request = recordFirstSyncEntry(item, storage);
    if (!request) return null;
  }
  return request;
}

export function clearFirstSyncRequest(storage) {
  removeObject(resolveStorage(storage), FIRST_SYNC_KEY);
}
