// JSON request helper for the deliverable pages. Unlike shared/client.js it
// keeps every legacy error attribute the editors read (code, type, fields,
// diagnostic, diagnosticPath) and formats messages like the legacy
// overviewRequestError ("<message>（HTTP <status>）").

const LOCAL_ONLY_TYPES = new Set(["LocalAccessRequired", "CrossSiteRequest"]);
export const LOCAL_ONLY_MESSAGE = "该操作只允许在本机浏览器中执行";

export class DeliverableApiError extends Error {
  constructor(message, details = {}) {
    super(message);
    this.name = "DeliverableApiError";
    Object.assign(this, details);
  }
}

/** Build the legacy-shaped error from a response body + status. */
export function requestError(body, status) {
  const error = body && body.error ? body.error : null;
  const rawMessage = error && typeof error.message === "string" ? error.message : "";
  const type = error && typeof error.type === "string" ? error.type : "";
  let message;
  if (status === 403 && (LOCAL_ONLY_TYPES.has(type) || !rawMessage)) message = `${LOCAL_ONLY_MESSAGE}（HTTP 403）`;
  else if (rawMessage) message = `${rawMessage}（HTTP ${status}）`;
  else message = `请求失败（HTTP ${status}）`;
  const code = error && typeof error.code === "string" ? error.code : "";
  return new DeliverableApiError(message, {
    status,
    fields: error && error.fields && typeof error.fields === "object" ? error.fields : null,
    code,
    type,
    errorCode: code,
    errorType: type,
    errorMessage: rawMessage,
    diagnosticPath: error && typeof error.diagnosticPath === "string" ? error.diagnosticPath : "",
    diagnostic: error && error.diagnostic && typeof error.diagnostic === "object" ? error.diagnostic : null,
    data: body && body.data !== undefined ? body.data : null,
    // 上游暂时不可用（服务端有界重试后仍是 5xx/429）：提示"可稍后重试"，
    // 不能用"配置启用失败"这种把瞬时故障说成配置问题的措辞。
    retryable: Boolean(error && error.diagnostic && error.diagnostic.retryable === true)
      || Boolean(error && error.retryable === true),
  });
}

/** True for the local-only guard (403 LocalAccessRequired / CrossSiteRequest). */
export function isLocalOnlyError(err) {
  return Boolean(err && err.status === 403 && LOCAL_ONLY_TYPES.has(err.type));
}

/** Raw error body (no HTTP suffix) for endpoints whose legacy code showed error.message verbatim. */
export function plainErrorMessage(err, fallback) {
  if (err && err.status === 403 && LOCAL_ONLY_TYPES.has(err.type)) return LOCAL_ONLY_MESSAGE;
  if (err && err.errorMessage) return err.errorMessage;
  if (err && err.status === 0) return err.message;
  return fallback;
}

export async function apiRequest(path, { method = "GET", body, signal } = {}) {
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
    throw new DeliverableApiError("无法连接本地服务，请确认 VSE Toolbox 仍在运行", { status: 0, type: "network" });
  }
  let payload = null;
  try {
    payload = await response.json();
  } catch (_err) {
    payload = null;
  }
  if (response.ok && payload && payload.ok === true) return payload.data;
  throw requestError(payload, response.status);
}

export const enc = encodeURIComponent;

