// Settings plugin request helpers. Unlike host api(), these keep the
// validation `fields` map and the response `data` of a failed call, which the
// settings form (per-field errors) and domain login (per-system results) need.
// Request bodies may hold credentials: they are never logged or put in URLs.

export class SettingsError extends Error {
  constructor(message, { status = 0, type = "network", fields = null, data = null } = {}) {
    super(message);
    this.name = "SettingsError";
    this.status = status;
    this.type = type;
    this.fields = fields;
    this.data = data;
  }
}

export async function request(path, { method = "GET", body } = {}) {
  const init = { method, cache: "no-store", headers: { Accept: "application/json" } };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch (_err) {
    throw new SettingsError("无法连接本地服务，请确认 VSE Toolbox 仍在运行");
  }
  let payload = null;
  try {
    payload = await response.json();
  } catch (_err) {
    payload = null;
  }
  if (response.ok && payload && payload.ok === true) return payload.data;
  const error = (payload && payload.error) || {};
  const fallback = response.status === 403 ? "该操作只允许在本机浏览器中执行" : `请求失败（HTTP ${response.status}）`;
  throw new SettingsError(error.message || fallback, {
    status: response.status,
    type: error.type || "http",
    fields: error.fields && typeof error.fields === "object" ? error.fields : null,
    data: payload && payload.data !== undefined ? payload.data : null,
  });
}

// 与旧页面 isAuthError 同口径：401/403 或典型会话失效文案。
export function isAuthError(err) {
  if (!err) return false;
  if (err.status === 401) return true;
  const msg = String(err.message || err).toLowerCase();
  return ["未登录", "登录过期", "未认证", "session expired", "unauthorized", "not authenticated"].some((k) =>
    msg.includes(k),
  );
}

// 旧全局（过渡期）：存在才调用，缺失时安全退化。
export function legacyGlobal(name) {
  const fn = typeof window !== "undefined" ? window[name] : undefined;
  return typeof fn === "function" ? fn : null;
}

export function refreshGlobalBadges(sessions) {
  const update = legacyGlobal("updateGlobalSessionBadges");
  if (update && sessions) update(sessions);
}

export function formatDateTime(value) {
  const text = String(value ?? "").trim();
  if (!text) return "-";
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return text;
  const pad = (part) => String(part).padStart(2, "0");
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
}

const FALLBACK_REDACTIONS = [
  [/\b(token|api_key|sid|sessionid|arasauth|jsessionid|csrf|secret|password|cookie|authorization)\b(\s*[:=]\s*)(?:Bearer\s+)?([^,\s;'"}\]\[]+)/gi, "$1$2[redacted]"],
  [/\bBearer\s+([^,\s;'"}\]\[]+)/gi, "Bearer [redacted]"],
];

/** Redact secrets from a message before display; `secret` (e.g. the typed password) is masked literally. */
export function redactText(value, secret = "") {
  let text = value === null || value === undefined ? "" : String(value);
  if (secret) text = text.split(secret).join("[redacted]");
  const legacy = legacyGlobal("redactSensitiveText");
  if (legacy) return legacy(text);
  FALLBACK_REDACTIONS.forEach(([pattern, replacement]) => {
    text = text.replace(pattern, replacement);
  });
  return text;
}
