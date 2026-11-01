// 报告中心（宿主模块）：提交生成 → 轮询进度 → 预览 → 复制 / 邮件草稿。
//
// 口径全部在后端：范围校验、正文与三图数据在 plugins/sign_daily（rules.py、mail.py）。
// 这里只调用插件已公开的 HTTP 接口，不复制日报规则，也不 import 任何插件模块：
// 三张图沿用插件既有的 Canvas 出图模块，由宿主按插件静态资源 URL 动态载入；
// 测试或没有 Canvas 的环境可注入 renderChart 替身，出图失败时降级为「无图预览」。
import { api } from "./api.js";

export const SIGN_DAILY_BASE = "/api/p/sign-daily";
export const CHART_MODULE_URL = "/plugins/sign_daily/static/chart.js";
export const POLL_INTERVAL_MS = 1500;

export const CHART_TITLES = {
  external: "图1 外区域会签未签单情况",
  sections: "图2 内部科室会签未签单情况",
  approval: "图3 审批未签单情况",
};

const defaultWait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const isActive = (task) => Boolean(task) && (task.status === "queued" || task.status === "running");

/**
 * 生成请求体：只挑后端 _validate_request 认识的字段。
 * 文案取该范围已记住的偏好（savedTexts），避免一键生成把用户的称呼/计划说明覆盖成默认值。
 * feishuLink 固定空：飞书功能已取消（需求清单 K6），与插件日报页同一条规则，旧值不进正文。
 */
export function requestBody(form, texts = {}) {
  const source = form || {};
  return {
    projects: [...(source.projects || [])],
    departments: [...(source.departments || [])],
    watchlistOnly: source.watchlistOnly === true,
    region: source.region || "",
    greeting: texts.greeting || "",
    planText: texts.planText || "",
    feishuLink: "",
  };
}

/**
 * 该范围已记住的文案：state.preferences 的键是后端 scope_key 序列化出来的 JSON。
 * 这里只解析**已有的键**并比较语义（项目/科室集合、是否只统计关注清单），
 * 不重新拼键，也不复制 scope_key 的格式。
 */
export function savedTexts(preferences, form) {
  const source = form || {};
  const projects = [...(source.projects || [])].sort().join("\u0000");
  const departments = [...(source.departments || [])].sort().join("\u0000");
  const watchlistOnly = source.watchlistOnly === true;
  for (const [key, value] of Object.entries(preferences || {})) {
    let parsed;
    try {
      parsed = JSON.parse(key);
    } catch (_) {
      continue;
    }
    if (!parsed || typeof parsed !== "object") continue;
    const sameProjects = [...(parsed.projects || [])].sort().join("\u0000") === projects;
    const sameDepartments = [...(parsed.departments || [])].sort().join("\u0000") === departments;
    if (sameProjects && sameDepartments && (parsed.watchlistOnly === true) === watchlistOnly) {
      return value && typeof value === "object" ? value : {};
    }
  }
  return {};
}

/** 三张图的出图模块按需载入（浏览器里是插件的静态资源 URL）；失败只影响邮件草稿。 */
let chartModule = null;

export function loadChartRenderer() {
  if (!chartModule) {
    chartModule = import(CHART_MODULE_URL)
      .then((mod) => {
        if (typeof mod.renderChartPng !== "function") throw new Error("日报出图模块不可用");
        return mod.renderChartPng;
      })
      .catch((error) => {
        chartModule = null;
        throw error;
      });
  }
  return chartModule;
}

/** 用同一张 PNG 供预览、复制与 .eml 使用（与插件日报页同一出图实现，不重写布局）。 */
export async function renderChartImages(result, renderChart) {
  const keys = (result && result.chartsWithData) || [];
  if (!keys.length) return {};
  const render = renderChart || (await loadChartRenderer());
  const images = {};
  keys.forEach((key) => {
    const png = render(result.charts ? result.charts[key] : null, key);
    if (png) images[key] = png;
  });
  return images;
}

/**
 * 一键生成：先提交后台抓取并轮询进度（可跳过），再调用 generate 落快照。
 * 只复用现有接口：POST refresh、GET refresh/<taskId>、POST generate。
 * 返回 { result, images, body, imagesError }；调用方取消（isAlive=false）时返回 null。
 */
export async function runSignDaily({
  form,
  preferences,
  refresh = true,
  apiCall = api,
  wait = defaultWait,
  pollMs = POLL_INTERVAL_MS,
  onProgress = () => {},
  isAlive = () => true,
  renderChart = null,
} = {}) {
  const body = requestBody(form, savedTexts(preferences, form));
  let task = null;
  if (refresh) {
    onProgress({ phase: "refresh", task: null });
    task = await apiCall(`${SIGN_DAILY_BASE}/refresh`, {
      method: "POST",
      body: { watchlistOnly: body.watchlistOnly },
    });
    while (isActive(task)) {
      onProgress({ phase: "refresh", task });
      await wait(pollMs);
      if (!isAlive()) return null;
      task = await apiCall(`${SIGN_DAILY_BASE}/refresh/${encodeURIComponent(task.taskId)}`);
    }
    if (!task || task.status !== "succeeded") {
      const failure = new Error((task && task.error) || "TDC 抓取未完成");
      failure.stage = "refresh";
      failure.code = (task && task.status) || "RefreshFailed";
      throw failure;
    }
  }
  onProgress({ phase: "generate", task });
  const result = await apiCall(`${SIGN_DAILY_BASE}/generate`, { method: "POST", body });
  let images = {};
  let imagesError = "";
  try {
    images = await renderChartImages(result, renderChart);
  } catch (error) {
    imagesError = (error && error.message) || String(error);
  }
  return { result, images, body, imagesError };
}

/** 预览/复制用：把正文里的 cid:sd-<图> 换成同一张 PNG 的 data URI；没有图时换成可读占位。 */
export function previewHtml(result, images) {
  const html = String((result && result.html) || "");
  return html.replace(/<img\b[^>]*src="cid:sd-([a-z]+)"[^>]*>/g, (tag, key) => {
    const png = images && images[key];
    if (png) return tag.replace(`cid:sd-${key}`, png);
    return `<p style="color:#646a73;font-size:12px;">［${CHART_TITLES[key] || key}：图表未在本页渲染］</p>`;
  });
}

/** 复制用的两种格式：富文本（内嵌图）与纯文本（后端 mail.render_text 原文）。 */
export function copyPayload(result, images) {
  return { html: previewHtml(result, images), text: String((result && result.text) || "") };
}

/** 能不能导出：状态门禁（数字码）与长周期初筛都以后端结果为准，报告中心不提供绕过开关。 */
export function exportAllowed(result) {
  if (!result) return false;
  if (result.statusGate && result.statusGate.blocked) return false;
  return result.exportBlocked !== true;
}

/** 不能导出的原因：门禁/复核文本原样用后端的，不改写、不重试。 */
export function blockReason(result) {
  if (!result) return "";
  const gate = result.statusGate || {};
  if (gate.blocked) return String(gate.text || "状态列是数字码，已禁止发送");
  if (result.exportBlocked) {
    const blocking = (result.notices || []).find((notice) => notice && notice.blocking);
    return String((blocking && blocking.text) || "有长周期初筛待确认");
  }
  return "";
}

/** 没能在本页出图的三张图：只挡邮件草稿（.eml 的图片必须与正文一一对应）。 */
export function missingChartKeys(result, images) {
  return ((result && result.chartsWithData) || []).filter((key) => !(images && images[key]));
}

/**
 * 失败是不是状态门禁（StatusGateBlocked）：只看后端给的分类，页面据此换成门禁说明。
 * 宿主 ApiError 有 type/code 两个字段，_json_error 默认只填 type，所以两个都认。
 */
export function isStatusGateError(error) {
  if (!error) return false;
  return error.code === "StatusGateBlocked" || error.type === "StatusGateBlocked";
}

/** 复制：优先富文本剪贴板（text/html + text/plain），非安全上下文退回选中预览区复制。 */
export async function copyToClipboard(payload, options = {}) {
  const nav = options.navigator || (typeof navigator === "undefined" ? null : navigator);
  const Item = options.ClipboardItem || (typeof ClipboardItem === "undefined" ? null : ClipboardItem);
  const secure = options.isSecureContext === undefined
    ? typeof window !== "undefined" && Boolean(window.isSecureContext)
    : options.isSecureContext === true;
  if (secure && nav && nav.clipboard && Item) {
    await nav.clipboard.write([
      new Item({
        "text/html": new Blob([payload.html], { type: "text/html" }),
        "text/plain": new Blob([payload.text], { type: "text/plain" }),
      }),
    ]);
    return "正文已复制，可直接粘贴到邮件";
  }
  const doc = options.document || (typeof document === "undefined" ? null : document);
  const node = options.fallbackNode || null;
  if (!doc || !node || typeof doc.execCommand !== "function") {
    throw new Error("浏览器不允许复制，请到完整日报页选中预览内容复制");
  }
  const range = doc.createRange();
  range.selectNodeContents(node);
  const selection = doc.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
  const ok = doc.execCommand("copy");
  selection.removeAllRanges();
  if (!ok) throw new Error("浏览器不允许复制，请到完整日报页选中预览内容复制");
  return "已改用选中复制；如粘贴后丢图，请到完整日报页逐张复制图片";
}

/**
 * 邮件草稿：调插件既有 /eml 生成 .eml 下载；只生成草稿，不发送。
 * 图片集合必须与正文一致（后端会校验），所以缺图时调用方应先禁用按钮。
 */
export async function downloadEml({
  body,
  images,
  proceed = false,
  url = `${SIGN_DAILY_BASE}/eml`,
  fetchImpl = typeof fetch === "undefined" ? null : fetch,
  download = saveBlobFile,
} = {}) {
  if (!fetchImpl) throw new Error("当前环境不支持下载邮件草稿");
  const response = await fetchImpl(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "message/rfc822, application/json" },
    body: JSON.stringify({ ...(body || {}), images: images || {}, proceedWithSuggestion: proceed === true }),
  });
  if (!response.ok) {
    let message = `下载失败（HTTP ${response.status}）`;
    let code = null;
    try {
      const payload = await response.json();
      const error = (payload && payload.error) || {};
      if (error.message) message = error.message;
      // 宿主 _json_error 把分类放在 error.type（code 只在显式传入时才有）：
      // 两个都认，门禁才不会被当成普通失败。
      code = error.code || error.type || null;
    } catch (_) {
      // 非 JSON 响应：保留通用文案
    }
    const failure = new Error(message);
    failure.status = response.status;
    failure.code = code;
    throw failure;
  }
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename\*=UTF-8''([^;]+)/);
  const name = match ? decodeURIComponent(match[1]) : "daily-report.eml";
  await download(await response.blob(), name);
  return name;
}

function saveBlobFile(blob, name) {
  const href = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = href;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}
