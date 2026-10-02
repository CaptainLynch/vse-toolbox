// Import-free formatting helpers for the deliverable detail pages (ported
// from the legacy app.js: redactSensitiveText, safeDisplayValue,
// archiveFormatDate, archiveSyncStateLabel, download-name helpers ...).
// Kept free of imports so the node tests can load it directly.

export const SENSITIVE_COLUMNS = new Set([
  "raw_xml", "file_id", "authorization", "set-cookie", "cookie", "token", "api_key", "sid",
  "sessionid", "arasauth", "jsessionid", "csrf", "secret", "password",
]);

const SENSITIVE_VALUE_PATTERNS = [
  [/(['"])(authorization|set-cookie|cookie|token|api_key|sid|sessionid|arasauth|jsessionid|csrf|secret|password)\1\s*:\s*(['"])(?:\\.|(?!\3)[\s\S])*\3/gi, "$1$2$1:$3[redacted]$3"],
  [/\b(authorization)\b(\s*[:=]\s*)(.*?)(?=(?:\s|,\s*)\b(?:set-cookie|cookie|token|api_key|sid|sessionid|arasauth|jsessionid|csrf|secret|password)\b\s*[:=]|[\r\n}\]\[]|$)/gi, "$1$2[redacted]"],
  [/\b(set-cookie|cookie)\b(\s*[:=]\s*)(.*?)(?=(?:\s|,\s*)\b(?:authorization|set-cookie|cookie)\b\s*:|[\r\n}\]\[]|$)/gi, "$1$2[redacted]"],
  [/\b(token|api_key|sid|sessionid|arasauth|jsessionid|csrf|secret|password)\b(\s*[:=]\s*)(?:Bearer\s+)?([^,\s;'"}}\]\[]+)/gi, "$1$2[redacted]"],
  [/\b(authorization|cookie|token|api_key|sid|sessionid|arasauth|jsessionid|csrf|secret|password)=([^&\s,;'"}}\]\[]+)/gi, "$1=[redacted]"],
  [/\bBearer\s+([^,\s;'"}}\]\[]+)/gi, "Bearer [redacted]"],
];

export function redactSensitiveText(value) {
  let text = value === null || value === undefined ? "" : String(value);
  SENSITIVE_VALUE_PATTERNS.forEach(([pattern, replacement]) => {
    text = text.replace(pattern, replacement);
  });
  return text;
}

export function safeDisplayValue(value) {
  const text = redactSensitiveText(value);
  return text.trim() ? text : "-";
}

export function errorText(err) {
  return redactSensitiveText(err instanceof Error ? err.message : String(err));
}

export function archiveFormatDate(isoString) {
  if (!isoString) return "待确认/未知";
  const d = new Date(isoString);
  if (Number.isNaN(d.getTime())) return "待确认/未知";
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function archiveSyncStateLabel(syncState) {
  const labels = { needs_attention: "需关注", success: "正常", idle: "空闲", running: "同步中", failed: "失败" };
  return labels[syncState] || "待确认/未知";
}

export function formatArtifactSize(bytes) {
  if (bytes === null || bytes === undefined || Number.isNaN(Number(bytes)) || bytes === "") return "—";
  const n = Number(bytes);
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function sanitizeDownloadName(name) {
  return String(name)
    .replace(/[\r\n\u0000-\u001f"\\/]/g, "")
    .replace(/^.*[\\/]/, "")
    .trim();
}

export function parseContentDispositionFilename(value) {
  if (!value) return "";
  const star = /filename\*\s*=\s*(?:utf-8''|UTF-8'')([^;]+)/i.exec(value);
  if (star) {
    try {
      const safe = sanitizeDownloadName(decodeURIComponent(star[1].trim()));
      if (safe) return safe;
    } catch (_err) {
      // filename* 解码失败时回退到普通 filename
    }
  }
  const plain = /filename\s*=\s*(?:"([^"]+)"|([^;]+))/i.exec(value);
  if (plain) {
    const safe = sanitizeDownloadName(plain[1] || plain[2] || "");
    if (safe) return safe;
  }
  return "";
}

/** Multi-line "Key: value" header text -> object (backend only accepts a dict). */
export function parseHeaders(raw) {
  const headers = {};
  String(raw || "").split(/\r?\n|,\s*(?=[A-Za-z0-9_-]+\s*:)/).forEach((line) => {
    const index = line.indexOf(":");
    if (index <= 0) return;
    const key = line.slice(0, index).trim();
    const value = line.slice(index + 1).trim();
    if (key && value) headers[key] = value;
  });
  return headers;
}

/** Legacy formatApiErrorMessage: "<type>: <message>｜诊断报告已保存：<path>". */
export function formatApiErrorMessage(err, fallbackStatus = 500) {
  const message = `${(err && err.type) || "错误"}: ${(err && err.message) || `HTTP ${fallbackStatus}`}`;
  const path = err && err.diagnosticPath;
  return path ? `${message}｜诊断报告已保存：${path}` : message;
}

// ---- statistics section formatting -------------------------------------

export function statisticsNumberText(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  return String(Math.round(num * 10) / 10);
}

export function statisticsDayText(value) {
  const num = Number(value);
  return Number.isFinite(num) ? `${Math.round(num)} 天` : "-";
}

export function statisticsLocalDateText(value) {
  const text = String(value || "").trim();
  if (!text) return "-";
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return safeDisplayValue(text);
  return parsed.toLocaleDateString();
}

export function formCostText(value, unit) {
  if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) return "—";
  return `${Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 })} ${unit}`;
}

export function formCostValueClass(value) {
  const numeric = Number(value);
  if (value === null || value === undefined || value === "" || !Number.isFinite(numeric) || numeric === 0) return "";
  return numeric > 0 ? "form-cost-change-increase" : "form-cost-change-decrease";
}
