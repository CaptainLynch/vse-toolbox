// Scheduled-archive page data: labels, per-template filter fields and pure
// form/validation helpers. No DOM and no Preact imports, so Node can test it.

export const PLUGIN_ID = "scheduled-archive";
export const PAGE_ID = "jobs";
export const API_BASE = "/api/scheduled-archive";

export const JOB_NAMES = {
  aras_ewo: "Aras EWO 变更记录",
  aras_paa: "Aras PAA 变更记录",
  aras_ncr_progress: "Aras NCR 审批进度",
  aras_ncr_detail: "Aras NCR 审批明细",
  tdc_data_model: "数模设计审核流程报表",
  tdc_sor: "TDC SOR",
};

export const SOURCE_LABELS = {
  aras: "ECM 流程",
  tdc: "TDC 研发",
};

export const SOURCE_CHOICES = [
  { key: "aras", label: "ECM 流程" },
  { key: "tdc", label: "TDC 研发" },
];

export const TEMPLATES = [
  { key: "aras_ewo", name: "Aras EWO 变更记录 (aras_ewo)" },
  { key: "aras_paa", name: "Aras PAA 变更记录 (aras_paa)" },
  { key: "aras_ncr_progress", name: "Aras NCR 审批进度 (aras_ncr_progress)" },
  { key: "aras_ncr_detail", name: "Aras NCR 审批明细 (aras_ncr_detail)" },
  { key: "tdc_data_model", name: "数模设计审核报表 (tdc_data_model)" },
  { key: "tdc_sor", name: "TDC SOR (tdc_sor)" },
];

const FUZZY = "支持 * 模糊和 | 并集";

const NCR_FIELDS = [
  { name: "buyStart", label: "采购开始", type: "date" },
  { name: "buyEnd", label: "采购结束", type: "date" },
  { name: "peStart", label: "PE 开始", type: "date" },
  { name: "peEnd", label: "PE 结束", type: "date" },
  { name: "ncrNo", label: "NCR 编号", placeholder: "支持系统查询符号" },
  { name: "projectNames", label: "项目名称", list: true, placeholder: "多个项目用逗号分隔" },
  { name: "sectionCode", label: "区段代码" },
  { name: "changeType", label: "变更类型" },
  { name: "otherCondition", label: "其他条件", placeholder: "默认 0" },
];

/** Common filter fields per template; the server validates the full contract. */
export const FILTER_FIELDS = {
  tdc_data_model: [
    { name: "incident", label: "流水号", placeholder: "例如 WF-2026-001" },
    { name: "applicant", label: "申请人", placeholder: "例如 张三" },
    { name: "department", label: "部门", placeholder: "例如 技术中心" },
    { name: "section", label: "科室", placeholder: "例如 车体工程" },
    { name: "applicationStart", label: "申请开始", type: "date" },
    { name: "applicationEnd", label: "申请结束", type: "date" },
    { name: "projectModel", label: "车型项目" },
    { name: "partNumber", label: "零件号", placeholder: "可填写部分编号" },
    { name: "modelNumber", label: "数模号", placeholder: "可填写部分编号" },
  ],
  tdc_sor: [
    { name: "processNo", label: "流水号" },
    { name: "processType", label: "流程类型" },
    { name: "carTypeProject", label: "车型项目" },
    { name: "applicant", label: "申请人" },
    { name: "title", label: "标题" },
    { name: "department", label: "部门" },
    { name: "section", label: "科室" },
    { name: "applicationStart", label: "申请开始", type: "date" },
    { name: "applicationEnd", label: "申请结束", type: "date" },
    { name: "partNumber", label: "零件号" },
    { name: "partName", label: "零件名称" },
    { name: "version", label: "版本" },
    { name: "sorNumber", label: "SOR 编号" },
    { name: "latestCompletedNode", label: "最近完成节点" },
    { name: "approvalStatus", label: "审批状态" },
  ],
  aras_ewo: [
    { name: "ewoNo", label: "EWO 编号", placeholder: FUZZY },
    { name: "projectCode", label: "车型项目" },
    { name: "subjectKeyword", label: "主题关键词", placeholder: FUZZY },
    { name: "changeType", label: "变更类型" },
    { name: "changeSubType", label: "变更子类型" },
    { name: "area", label: "区域", placeholder: FUZZY },
    { name: "state", label: "状态" },
    { name: "responsibleDepartment", label: "响应部门", placeholder: FUZZY },
    { name: "submitStart", label: "提交开始", type: "date" },
    { name: "submitEnd", label: "提交结束", type: "date" },
  ],
  aras_paa: [
    { name: "paaNo", label: "PAA 编号", placeholder: FUZZY },
    { name: "ewoNo", label: "EWO 编号", placeholder: FUZZY },
    { name: "state", label: "状态" },
    { name: "area", label: "区域", placeholder: FUZZY },
    { name: "base", label: "基地", placeholder: FUZZY },
    { name: "department", label: "业务部门", placeholder: "例如 技术中心-车体工程" },
    { name: "vehicleKeyword", label: "车型项目" },
    { name: "submitStart", label: "提交开始", type: "date" },
    { name: "submitEnd", label: "提交结束", type: "date" },
    { name: "materialRequestStart", label: "物料需求开始", type: "date" },
    { name: "materialRequestEnd", label: "物料需求结束", type: "date" },
  ],
  aras_ncr_progress: NCR_FIELDS,
  aras_ncr_detail: NCR_FIELDS,
};

export const LIST_FIELDS = new Set(["projectNames", "sectionCodes"]);

/** 车型项目类字段：占位符与默认值跟随「主计划名称」（需求 2026-09-06）。 */
export const PROJECT_FILTER_KEYS = new Set(["projectModel", "carTypeProject", "projectCode", "vehicleKeyword"]);
export const PROJECT_FILTER_HINT = FUZZY;

export const CREDENTIAL_OPTIONS = [
  { value: "domain", label: "统一域账号（domain）" },
  { value: "unified-domain", label: "兼容引用（unified-domain）" },
];

const TONES = { success: "is-success", warning: "is-warning", error: "is-error", running: "is-running", muted: "is-muted" };
const UNKNOWN = "待确认/未知";

const FRESHNESS = {
  fresh: ["24 小时内", "success"],
  stale: ["已陈旧", "warning"],
};
const SYNC_STATES = {
  needs_attention: ["需关注", "warning"],
  success: ["正常", "success"],
  idle: ["空闲", "muted"],
  running: ["同步中", "running"],
  failed: ["失败", "error"],
};
const RUN_STATES = {
  success: ["成功", "success"],
  failed: ["失败", "error"],
  running: ["运行中", "running"],
  leased: ["已锁定", "running"],
  partial: ["部分完成", "warning"],
  needs_attention: ["需关注", "warning"],
  expired: ["已超时", "error"],
};

function chip(table, key) {
  const [text, tone] = table[key] || [UNKNOWN, "muted"];
  return { text, tone: TONES[tone] };
}

export const freshnessChip = (value) => chip(FRESHNESS, value);
export const syncStateChip = (value) => chip(SYNC_STATES, value);
export const runStateChip = (value) => chip(RUN_STATES, value);
export const syncStateLabel = (value) => syncStateChip(value).text;

export function triggerLabel(triggerType) {
  if (triggerType === "sync_now") return "手动立即下载";
  if (triggerType === "scheduled") return "自动下载";
  return UNKNOWN;
}

/** Same remedy codes as services/scheduled_archive_runner.py (closed set). */
export const REMEDY_TEXT = {
  bind_domain_credential: "在下方「定时登录信息」选择统一域账号后保存",
  enable_job: "勾选「启用自动下载」并保存后再执行",
  restore_job_contract: "任务模板与连接器不匹配，请删除后按模板重新创建",
  repair_job_filters: "请检查「高级下载条件」后保存",
  repair_retry_policy: "请把「失败后最多尝试次数」改为 1 或 2",
  inspect_job_configuration: "请检查任务配置后重试",
  fill_watchlist: "待配置：关注清单为空，请先在交付物明细里加入要关注的流水单号",
  save_domain_credential: "请到系统设置登录并勾选“保存至凭据保护库”",
  refresh_domain_credential: "登录信息已失效，请重新登录并保存至凭据保护库",
  wait_and_retry: "任务正在运行，请稍后重试",
  retry_or_narrow_filters: "请稍后重试或收窄下载条件",
};

const REMEDY_BY_ERROR_TYPE = {
  job_not_ready: "inspect_job_configuration",
  missing_job: "inspect_job_configuration",
  credential_unavailable: "save_domain_credential",
  credential_invalid: "refresh_domain_credential",
  authentication_error: "refresh_domain_credential",
  lease_busy: "wait_and_retry",
  query_failed: "retry_or_narrow_filters",
  timeout: "retry_or_narrow_filters",
  connector_unavailable: "restore_job_contract",
  internal_data: "inspect_job_configuration",
  invalid_data: "inspect_job_configuration",
};

const AUTH_REMEDIES = new Set(["save_domain_credential", "refresh_domain_credential"]);
const AUTH_ERROR_TYPES = new Set(["authentication_error", "credential_invalid", "credential_unavailable"]);

export function remedyFor(remedy, errorType) {
  return remedy || REMEDY_BY_ERROR_TYPE[errorType] || null;
}

export function remedyText(code) {
  return code ? REMEDY_TEXT[code] || null : null;
}

/** True when the failure needs a fresh login (credential remedies or 401). */
export function isAuthFailure({ remedy = null, errorType = null, status = 0 } = {}) {
  return status === 401 || AUTH_ERROR_TYPES.has(errorType) || AUTH_REMEDIES.has(remedy);
}

export function jobTitle(job) {
  if (!job) return "";
  return JOB_NAMES[job.jobKey] || job.displayName || job.jobKey;
}

export function sourceLabel(sourceType, fallback = "未知来源") {
  return SOURCE_LABELS[sourceType] || fallback;
}

export function sourceOfTemplate(templateKey) {
  return String(templateKey || "").startsWith("tdc_") ? "tdc" : "aras";
}

export function templatesForSource(source) {
  return TEMPLATES.filter((item) => item.key.startsWith(`${source}_`));
}

export function filterFieldsFor(job) {
  return (job && FILTER_FIELDS[job.templateKey]) || [];
}

export function credentialAvailable(job) {
  return job.credentialAvailable === undefined ? Boolean(job.credentialConfigured) : Boolean(job.credentialAvailable);
}

export function credentialStatus(job) {
  if (!job.credentialConfigured) return { text: "登录信息未设置", tone: TONES.warning };
  return credentialAvailable(job)
    ? { text: "登录信息可用", tone: TONES.success }
    : { text: "登录信息不可用", tone: TONES.warning };
}

export function canSyncNow(job) {
  return Boolean(job && job.enabled && credentialAvailable(job));
}

export function isValidInterval(value) {
  return Number.isInteger(value) && value > 0;
}

export function intervalText(job) {
  return isValidInterval(job.intervalMinutes) ? `${job.intervalMinutes} 分钟` : UNKNOWN;
}

export function retryText(job) {
  const max = job.retryPolicy && job.retryPolicy.max_attempts;
  if (!Number.isInteger(max) || max <= 0) return UNKNOWN;
  return `最多尝试 ${max} 次（失败后重试 ${Math.max(0, max - 1)} 次）`;
}

export function formatDate(iso) {
  if (!iso) return UNKNOWN;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return UNKNOWN;
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function formatBytes(value) {
  return typeof value === "number" ? `${value} B` : "-";
}

export function filterDisplayValue(value) {
  if (Array.isArray(value)) return value.join(", ");
  return value === null || value === undefined ? "" : String(value);
}

/** Field inputs ({name: text}) → filter object; blanks are dropped, list fields split on , or newline. */
export function collectFilterValues(values) {
  const result = {};
  Object.entries(values || {}).forEach(([name, input]) => {
    const raw = String(input ?? "").trim();
    if (!raw) return;
    if (LIST_FIELDS.has(name)) {
      const items = raw.split(/[,\n]/).map((item) => item.trim()).filter(Boolean);
      if (items.length) result[name] = items;
    } else {
      result[name] = raw;
    }
  });
  return result;
}

/** Field input texts for a filters object. */
export function filterInputs(fields, filters) {
  const values = {};
  fields.forEach((field) => {
    values[field.name] = filterDisplayValue((filters || {})[field.name]);
  });
  return values;
}

/**
 * Merge edited field inputs into the JSON filters: field keys come from the
 * inputs, keys the form has no field for are kept from the current JSON.
 */
export function mergeFieldFilters(fields, inputs, currentFilters) {
  const fieldNames = new Set(fields.map((field) => field.name));
  const kept = {};
  Object.entries(currentFilters || {}).forEach(([key, value]) => {
    if (!fieldNames.has(key)) kept[key] = value;
  });
  return { ...kept, ...collectFilterValues(inputs) };
}

/** Parse the JSON editor text; returns {filters} or {error}. */
export function parseFiltersJson(text) {
  const raw = String(text || "").trim() || "{}";
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (_) {
    return { error: "JSON 格式解析失败，请检查输入语法" };
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return { error: "高级下载条件必须是 JSON 对象" };
  }
  return { filters: parsed };
}

/**
 * Project-name prefill: fields whose key is a project filter and that the job
 * has never configured (key missing or null) default to the master-plan name.
 * An explicit value — including an explicit empty string — wins.
 */
export function planNamePrefill(fields, jobFilters, inputs, planName) {
  const name = String(planName || "").trim();
  if (!name) return null;
  const filters = jobFilters || {};
  const next = { ...inputs };
  let changed = false;
  fields.forEach((field) => {
    if (!PROJECT_FILTER_KEYS.has(field.name)) return;
    const explicit = field.name in filters && filters[field.name] !== null && filters[field.name] !== undefined;
    if (!explicit && !String(next[field.name] || "").trim()) {
      next[field.name] = name;
      changed = true;
    }
  });
  return changed ? next : null;
}

/** Default credential selector value (preselect domain when nothing is bound but the vault is ready). */
export function defaultCredentialRef(job, vaultConfigured) {
  return !job.credentialConfigured && vaultConfigured === true ? "domain" : "";
}

/** Initial editable form state for a job. */
export function initialForm(job, vaultConfigured) {
  const filters = job.filters || {};
  return {
    enabled: Boolean(job.enabled),
    intervalMinutes: isValidInterval(job.intervalMinutes) ? String(job.intervalMinutes) : "60",
    retryMaxAttempts: job.retryPolicy && Number.isInteger(job.retryPolicy.max_attempts)
      ? String(job.retryPolicy.max_attempts)
      : "2",
    credentialRef: defaultCredentialRef(job, vaultConfigured),
    clearCredential: false,
    outputDirectory: job.outputDirectory || "",
    filterInputs: filterInputs(filterFieldsFor(job), filters),
    filtersJson: JSON.stringify(filters, null, 2),
  };
}

/**
 * Client validation + PATCH payload, same rules as the legacy form.
 * Returns {errors} (field → message) or {payload}.
 */
export function buildUpdatePayload(job, form) {
  const enabled = Boolean(form.enabled);
  const credentialRef = String(form.credentialRef || "").trim();
  const clear = Boolean(form.clearCredential);
  const intervalMinutes = Number.parseInt(String(form.intervalMinutes), 10);
  const retryMaxAttempts = Number.parseInt(String(form.retryMaxAttempts), 10);

  if (enabled && clear) {
    return { errors: { enabled: "启用自动下载时不能同时清除登录信息", clearAlias: "清除登录信息前请先停用自动下载" } };
  }
  if (enabled && !job.credentialConfigured && !credentialRef) {
    return { errors: { credentialRef: "启用自动下载前请选择统一域账号登录信息" } };
  }
  if (!Number.isInteger(intervalMinutes) || intervalMinutes < 5 || intervalMinutes > 10080) {
    return { errors: { intervalMinutes: "自动执行频率必须是 5 到 10080 之间的整数（分钟）" } };
  }
  if (!Number.isInteger(retryMaxAttempts) || retryMaxAttempts < 1 || retryMaxAttempts > 2) {
    return { errors: { retryPolicy: "最多尝试次数只能是 1 或 2" } };
  }
  const parsed = parseFiltersJson(form.filtersJson);
  if (parsed.error) return { errors: { filters: parsed.error } };

  const outputDirectory = String(form.outputDirectory || "").trim();
  const payload = {
    enabled,
    intervalMinutes,
    filters: parsed.filters,
    // 选择独立目录后必须清空旧版子目录；留空则保留旧版子目录兼容配置。
    outputSubdir: outputDirectory ? "" : job.outputSubdir || "",
    outputDirectory,
    retryPolicy: { max_attempts: retryMaxAttempts },
    updatedAt: job.updatedAt,
  };
  if (clear) payload.credentialRef = null;
  else if (credentialRef) payload.credentialRef = credentialRef;
  return { payload };
}

/** Validate the create form; returns {error} or {payload}. */
export function buildCreatePayload({ templateKey, displayName, copyFromJobKey }) {
  if (!templateKey) return { error: "请选择具体报表模板" };
  const name = String(displayName || "").trim();
  if (!name) return { error: "任务名称为必填项" };
  const payload = { templateKey, displayName: name };
  if (copyFromJobKey) payload.copyFromJobKey = copyFromJobKey;
  return { payload };
}

/**
 * Interpret a sync-now response ({exitCode, results[]}) for one job.
 * Returns {ok, message, remedy, errorType}.
 */
export function summarizeSyncResult(data, jobKey) {
  const results = Array.isArray(data && data.results) ? data.results : [];
  const first = results.find((item) => item && item.jobKey === jobKey) || results[0] || null;
  const exitCode = data ? data.exitCode : null;
  if (exitCode === 0 && (!first || first.outcome === "completed")) {
    return { ok: true, message: "下载已完成", remedy: null, errorType: null };
  }
  const errorType = first ? first.errorType || null : null;
  const message = (first && (first.errorMessage || first.errorType))
    || (exitCode ? `同步未就绪（退出码 ${exitCode}）` : "同步未完成");
  return { ok: false, message, remedy: remedyFor(first && first.remedy, errorType), errorType };
}

/** Read `job` from a `#p/<plugin>/<page>?job=<key>` hash. */
export function jobFromHash(hash) {
  const text = String(hash || "");
  const at = text.indexOf("?");
  if (at < 0) return "";
  try {
    return new URLSearchParams(text.slice(at + 1)).get("job") || "";
  } catch (_) {
    return "";
  }
}

export function jobHash(jobKey) {
  const base = `#p/${PLUGIN_ID}/${PAGE_ID}`;
  return jobKey ? `${base}?job=${encodeURIComponent(jobKey)}` : base;
}

/** Choose the selected job: requested key if present, else the first job. */
export function pickSelectedJob(jobs, requestedKey) {
  if (!Array.isArray(jobs) || jobs.length === 0) return null;
  return jobs.find((job) => job.jobKey === requestedKey) || jobs[0];
}

export function anyJobRunning(jobs) {
  return Array.isArray(jobs) && jobs.some((job) => job.syncState === "running");
}

/** Copy-source options for the create form: existing jobs of the chosen template. */
export function copySourcesFor(jobs, templateKey) {
  return (jobs || []).filter((job) => job.templateKey === templateKey);
}

export function fieldErrorList(errors) {
  return Object.entries(errors || {}).map(([field, message]) => `${field}: ${message}`);
}
