// Excel 文件处理：无依赖的纯函数（标签、脱敏、格式化、路径校验、请求体组装），可在 Node 下单测。

// 与旧页 app.js 的 SENSITIVE_VALUE_PATTERNS 同口径；旧全局存在时优先复用它。
const SENSITIVE_VALUE_PATTERNS = [
  [/(['"])(authorization|set-cookie|cookie|token|api_key|sid|sessionid|arasauth|jsessionid|csrf|secret|password)\1\s*:\s*(['"])(?:\\.|(?!\3)[\s\S])*\3/gi, "$1$2$1:$3[redacted]$3"],
  [/\b(authorization)\b(\s*[:=]\s*)(.*?)(?=(?:\s|,\s*)\b(?:set-cookie|cookie|token|api_key|sid|sessionid|arasauth|jsessionid|csrf|secret|password)\b\s*[:=]|[\r\n}\]\[]|$)/gi, "$1$2[redacted]"],
  [/\b(set-cookie|cookie)\b(\s*[:=]\s*)(.*?)(?=(?:\s|,\s*)\b(?:authorization|set-cookie|cookie)\b\s*:|[\r\n}\]\[]|$)/gi, "$1$2[redacted]"],
  [/\b(token|api_key|sid|sessionid|arasauth|jsessionid|csrf|secret|password)\b(\s*[:=]\s*)(?:Bearer\s+)?([^,\s;'"}}\]\[]+)/gi, "$1$2[redacted]"],
  [/\b(authorization|cookie|token|api_key|sid|sessionid|arasauth|jsessionid|csrf|secret|password)=([^&\s,;'"}}\]\[]+)/gi, "$1=[redacted]"],
  [/\bBearer\s+([^,\s;'"}}\]\[]+)/gi, "Bearer [redacted]"],
];

export function redact(value) {
  if (typeof window !== "undefined" && typeof window.redactSensitiveText === "function") {
    return window.redactSensitiveText(value);
  }
  let text = value === null || value === undefined ? "" : String(value);
  SENSITIVE_VALUE_PATTERNS.forEach(([pattern, replacement]) => {
    text = text.replace(pattern, replacement);
  });
  return text;
}

export function display(value) {
  const text = redact(value);
  return text.trim() ? text : "-";
}

export const OPERATIONS = [
  { value: "merge_append", label: "追加合并" },
  { value: "merge_overlay", label: "覆盖合并" },
  { value: "diff_against_baseline", label: "基线差异比对" },
];

export function operationLabel(value) {
  const found = OPERATIONS.find((item) => item.value === value);
  return found ? found.label : display(value);
}

export const STATUS_FILTERS = [
  { value: "", label: "全部" },
  { value: "queued", label: "等待处理" },
  { value: "leased", label: "准备处理" },
  { value: "running", label: "处理中" },
  { value: "succeeded", label: "已完成" },
  { value: "failed", label: "失败" },
  { value: "cancelled", label: "已取消" },
];

const STATUS_LABELS = {
  queued: "排队中",
  leased: "已租用",
  running: "运行中",
  succeeded: "已成功",
  failed: "失败",
  cancelled: "已取消",
  expired: "已过期",
  stopped: "已停止",
  stopping: "停止中",
};

export const ACTIVE_TASK_STATES = ["queued", "leased", "running"];

export function statusLabel(status) {
  return STATUS_LABELS[status] || display(status || "未知");
}

export function statusTone(status) {
  if (status === "succeeded" || status === "stopped") return "is-success";
  if (["queued", "leased", "running", "stopping"].includes(status)) return "is-running";
  if (["failed", "cancelled", "expired"].includes(status)) return "is-failed";
  return "is-unknown";
}

export function formatDate(value) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return display(value);
  return parsed.toLocaleString("zh-CN", { hour12: false });
}

export function formatSize(value) {
  if (value === null || value === undefined || value === "") return "-";
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function newIdempotencyKey() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
    return `excel-${globalThis.crypto.randomUUID()}`;
  }
  return `excel-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/** 与旧页 validateExcelRelativePath 同规则：受控根下的相对路径、无 ./..、.xlsx/.xls。 */
export function validateRelativePath(value, fieldName) {
  const path = String(value || "").trim();
  if (!path) throw new Error(`${fieldName}不能为空`);
  if (path.startsWith("/") || path.includes("\\") || path.includes(":")) {
    throw new Error(`${fieldName}必须是受控根下的相对路径`);
  }
  const segments = path.split("/");
  if (segments.some((segment) => !segment || segment === "." || segment === "..")) {
    throw new Error(`${fieldName}包含非法路径片段`);
  }
  if (!/\.(xlsx|xls)$/i.test(path)) {
    throw new Error(`${fieldName}必须使用 .xlsx 或 .xls 扩展名`);
  }
  return path;
}

/**
 * 由表单状态组装 POST /api/excel-tasks 的请求体（与旧页 createExcelTask 一致）。
 * form: {operation, sourceRoot, sourcePaths, targetRoot, targetPath, baselineRoot,
 *        baselinePath, outputRoot, outputPath, idempotencyKey}; roots: 可用 rootId 列表。
 */
export function buildTaskPayload(form, roots) {
  const root = (value) => {
    const text = String(value || "");
    if (!text || !roots.includes(text)) throw new Error("请选择有效的文件所在位置");
    return text;
  };
  const { operation } = form;
  const files = [];
  if (operation !== "diff_against_baseline") {
    const sourceRoot = root(form.sourceRoot);
    const sources = String(form.sourcePaths || "").split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
    if (sources.length === 0) throw new Error("至少需要填写一个要处理的文件");
    sources.forEach((path, index) => files.push({
      role: "source",
      rootId: sourceRoot,
      relativePath: validateRelativePath(path, `要处理的文件 #${index + 1}`),
      ordinal: index,
    }));
  }
  if (operation !== "merge_append") {
    files.push({
      role: "target",
      rootId: root(form.targetRoot),
      relativePath: validateRelativePath(form.targetPath, "目标模板"),
      ordinal: 0,
    });
  }
  const baseline = String(form.baselinePath || "").trim();
  if (operation === "diff_against_baseline" && !baseline) throw new Error("对比基准为必填项");
  if (baseline) {
    files.push({
      role: "baseline",
      rootId: root(form.baselineRoot),
      relativePath: validateRelativePath(baseline, "对比基准"),
      ordinal: 0,
    });
  }
  files.push({
    role: "output",
    rootId: root(form.outputRoot),
    relativePath: validateRelativePath(form.outputPath, "输出文件名"),
    ordinal: 0,
  });
  return { operation, files, idempotencyKey: form.idempotencyKey, maxAttempts: 1 };
}

/** 反向：把已有任务的文件引用填回表单，用于“复制为新任务”（Excel 任务不允许直接重试）。 */
export function formFromTask(task, fallbackRoot) {
  const files = Array.isArray(task.files) ? task.files : [];
  const byRole = (role) => files.filter((item) => item.role === role).sort((a, b) => (a.ordinal || 0) - (b.ordinal || 0));
  const sources = byRole("source");
  const [target] = byRole("target");
  const [baseline] = byRole("baseline");
  const [output] = byRole("output");
  return {
    operation: task.operation,
    sourceRoot: sources[0]?.rootId || fallbackRoot,
    sourcePaths: sources.map((item) => item.relativePath).join("\n"),
    targetRoot: target?.rootId || fallbackRoot,
    targetPath: target?.relativePath || "",
    baselineRoot: baseline?.rootId || fallbackRoot,
    baselinePath: baseline?.relativePath || "",
    outputRoot: output?.rootId || fallbackRoot,
    outputPath: output?.relativePath || "",
    idempotencyKey: newIdempotencyKey(),
  };
}
