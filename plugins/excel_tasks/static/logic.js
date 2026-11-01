// Excel 文件处理：纯函数（标签、脱敏、格式化、路径校验、请求体组装），可在 Node 下单测。
// 唯一的外部依赖是宿主时间模块 /static/host/time-format.js（契约 C9），插件不复制其时区逻辑。

// 宿主时间模块：时间点显示一律北京时间，与浏览器所在时区/语言无关。
// 用动态导入 + 顶层 await 而非静态 import：本文件被既有 Node 测试以原生 ESM 直接加载，
// 静态 "/static/host/..." 在没有宿主静态服务时无法解析。导入不可用时 formatDate 原样
// 显示取值（绝不按宿主时区自行换算，避免静默偏移）；浏览器下宿主模块始终可用。
let hostTime = null;
try {
  hostTime = await import("/static/host/time-format.js");
} catch (_hostTimeError) {
  hostTime = null;
}

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

/**
 * 时间展示（契约 C9）：
 * - 纯日期（例如 retention 截止日）原样返回，不做任何时区换算；
 * - 带显式时区的时间点（createdAt / updatedAt / cutoffAt，均为 UTC ISO）显示北京时间；
 * - 无时区或无法判定的取值来源不明，原样显示，绝不按宿主时区猜测。
 */
export function formatDate(value) {
  if (!value) return "-";
  if (!hostTime) return display(value);
  if (hostTime.isPureDate(value)) return hostTime.formatPureDate(value);
  try {
    return hostTime.formatBeijingSeconds(value);
  } catch (_err) {
    return display(value);
  }
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

export const ENV_PLACEHOLDER_TEXT = "环境检查将在后续版本提供";

/**
 * 环境检查三态分类：
 * - ok: 正常（绿），表格软件已就绪且授权正常；
 * - warn: 需要检查（黄），无法确认授权状态或有待清理后台进程；
 * - bad: 不可用（红），未检测到表格软件或未激活；
 * - placeholder / off: 暂未提供，后端未暴露环境检查接口时的占位，绝不伪造通过状态。
 */
export function classifyEnvStatus(env) {
  // 空对象 = 后端完全没有提供数据（与 null 同属占位）；
  // need_check 留给「有 env 对象但激活状态无法确认」的真实场景。
  if (!env || (typeof env === "object" && !Array.isArray(env) && Object.keys(env).length === 0)
      || env.placeholder || env.available === false) {
    return {
      state: "placeholder",
      tone: "off",
      label: "暂未提供",
      description: (env && env.description) || ENV_PLACEHOLDER_TEXT,
      placeholder: true,
      isPassed: false,
    };
  }

  // 纯字符串状态支持
  if (typeof env === "string") {
    if (env === "ok" || env === "normal") {
      return {
        state: "ok",
        tone: "ok",
        label: "正常",
        description: "表格软件已就绪，运行环境正常",
        placeholder: false,
        isPassed: true,
      };
    }
    if (env === "need_check" || env === "warn" || env === "warning") {
      return {
        state: "need_check",
        tone: "warn",
        label: "需要检查",
        description: "无法可靠确认激活状态，请在软件账户信息中核对",
        placeholder: false,
        isPassed: false,
      };
    }
    if (env === "unavailable" || env === "bad" || env === "unlicensed" || env === "not_installed") {
      return {
        state: "unavailable",
        tone: "bad",
        label: "不可用",
        description: "未检测到可用的表格软件或软件尚未激活",
        placeholder: false,
        isPassed: false,
      };
    }
    if (env === "placeholder" || env === "off") {
      return {
        state: "placeholder",
        tone: "off",
        label: "暂未提供",
        description: ENV_PLACEHOLDER_TEXT,
        placeholder: true,
        isPassed: false,
      };
    }
  }

  // 对象状态支持：显式 state 字段
  if (env.state === "ok") {
    return {
      state: "ok",
      tone: "ok",
      label: "正常",
      description: env.detail || env.description || "表格软件已就绪，运行环境正常",
      placeholder: false,
      isPassed: true,
    };
  }
  if (env.state === "need_check" || env.state === "warn") {
    return {
      state: "need_check",
      tone: "warn",
      label: "需要检查",
      description: env.detail || env.description || "无法可靠确认激活状态，请在软件账户信息中核对",
      placeholder: false,
      isPassed: false,
    };
  }
  if (env.state === "bad" || env.state === "unavailable" || env.state === "unlicensed") {
    return {
      state: "unavailable",
      tone: "bad",
      label: "不可用",
      description: env.detail || env.description || "未检测到可用的表格软件或软件尚未激活",
      placeholder: false,
      isPassed: false,
    };
  }

  // 对应后端环境检查服务返回的数据结构（services/excel_env_check 模块）
  if (env.installed === false || env.install_state === "not_installed") {
    return {
      state: "unavailable",
      tone: "bad",
      label: "不可用",
      description: (env.activation && env.activation.detail) || "未检测到可用的表格软件",
      placeholder: false,
      isPassed: false,
    };
  }

  const activation = env.activation || {};
  if (activation.state === "unlicensed") {
    return {
      state: "unavailable",
      tone: "bad",
      label: "不可用",
      description: activation.detail || "软件尚未激活或授权已过期",
      placeholder: false,
      isPassed: false,
    };
  }

  if (activation.state === "need_check" || (env.residual_count && env.residual_count > 0)) {
    return {
      state: "need_check",
      tone: "warn",
      label: "需要检查",
      description: activation.detail || (env.residual_count > 0 ? "检测到存在待释放的后台表格进程" : "无法可靠确认激活状态，请在软件账户信息中核对"),
      placeholder: false,
      isPassed: false,
    };
  }

  if (env.installed === true && (activation.state === "activated" || !activation.state)) {
    return {
      state: "ok",
      tone: "ok",
      label: "正常",
      description: activation.detail || "表格软件已就绪，运行环境正常",
      placeholder: false,
      isPassed: true,
    };
  }

  return {
    state: "need_check",
    tone: "warn",
    label: "需要检查",
    description: activation.detail || "环境状态待确认",
    placeholder: false,
    isPassed: false,
  };
}

/**
 * 三态渲染描述函数：将环境检测状态转换为渲染所需的属性与样式类。
 */
export function renderEnvStatus(env) {
  const info = classifyEnvStatus(env);
  const toneClass = info.tone === "ok"
    ? "is-success"
    : info.tone === "warn"
      ? "is-warning"
      : info.tone === "bad"
        ? "is-failed"
        : "is-unknown";

  return {
    state: info.state,
    tone: info.tone,
    label: info.label,
    description: info.description,
    badgeText: info.label,
    toneClass,
    placeholder: Boolean(info.placeholder),
    isPassed: Boolean(info.isPassed),
  };
}

/**
 * 错误文案格式化（保留错误信息原文不变）。
 */
export function formatErrorWhat(error) {
  if (!error) return "";
  const msg = display(error.message || String(error));
  const meta = error.status ? ` (HTTP ${error.status}${error.type ? ` · ${error.type}` : ""})` : "";
  const fields = error.fields && typeof error.fields === "object" ? Object.entries(error.fields) : [];
  if (fields.length > 0) {
    const fieldDetails = fields.map(([key, val]) => `${key}: ${display(val)}`).join("；");
    return `${msg}${meta} [${fieldDetails}]`;
  }
  return `${msg}${meta}`;
}

export function isAuthError(error) {
  if (!error) return false;
  return error.status === 401 || /auth|login|credential|session/i.test(String(error.type || ""));
}

export function formatErrorTodo(error) {
  if (isAuthError(error)) {
    return "请重新登录后再试";
  }
  return "请核对文件路径与参数后重试，若持续失败请联系管理员";
}

