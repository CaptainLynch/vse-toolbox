// Shared helpers for the project-overview pages. Keeps the error `fields`
// and `data` of a failed call (the legacy API returns per-field validation
// errors and conflict payloads that the editors need).

export const PROJECT_PHASE_ID = "VPI-T2";

export class ApiError extends Error {
  constructor(message, { status = 0, type = "network", fields = null, data = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.type = type;
    this.fields = fields;
    this.data = data;
  }
}

export async function request(path, { method = "GET", body, signal } = {}) {
  const init = { method, cache: "no-store", headers: { Accept: "application/json" }, signal };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch (err) {
    if (err && err.name === "AbortError") throw err;
    throw new ApiError("无法连接本地服务，请确认 VSE Toolbox 仍在运行");
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
  throw new ApiError(redactText(error.message || fallback), {
    status: response.status,
    type: error.type || "http",
    fields: error.fields && typeof error.fields === "object" ? error.fields : null,
    data: payload && payload.data !== undefined ? payload.data : null,
  });
}

/** Legacy/host global, or null (e.g. openInPlaceLogin, updateGlobalSessionBadges). */
export function hostGlobal(name) {
  const fn = typeof window !== "undefined" ? window[name] : undefined;
  return typeof fn === "function" ? fn : null;
}

const FALLBACK_REDACTIONS = [
  [/\b(token|api_key|sid|sessionid|arasauth|jsessionid|csrf|secret|password|cookie|authorization)\b(\s*[:=]\s*)(?:Bearer\s+)?([^,\s;'"}\]\[]+)/gi, "$1$2[redacted]"],
  [/\bBearer\s+([^,\s;'"}\]\[]+)/gi, "Bearer [redacted]"],
];

export function redactText(value) {
  const text = value === null || value === undefined ? "" : String(value);
  const host = hostGlobal("redactSensitiveText");
  if (host) return host(text);
  return FALLBACK_REDACTIONS.reduce((acc, [pattern, replacement]) => acc.replace(pattern, replacement), text);
}

/** Read `?a=b` params from the current `#p/<plugin>/<page>?...` hash. */
export function hashParams() {
  const hash = typeof window !== "undefined" ? window.location.hash || "" : "";
  const index = hash.indexOf("?");
  return new URLSearchParams(index >= 0 ? hash.slice(index + 1) : "");
}

export function pageHash(page, params) {
  const query = params ? new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")).toString() : "";
  return `#p/project-overview/${page}${query ? `?${query}` : ""}`;
}
