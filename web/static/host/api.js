// Host API client: unwraps the {ok, data, error} envelope and maps failures
// to one ApiError shape, so plugin pages never parse responses themselves.
import { useCallback, useEffect, useRef, useState } from "./vendor/preact-htm.js";

export class ApiError extends Error {
  constructor(message, { status = 0, type = "network", code = null, diagnostic = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.type = type;
    this.code = code;
    this.diagnostic = diagnostic;
  }
}

const STATUS_MESSAGES = {
  403: "该操作只允许在本机浏览器中执行",
  404: "接口不存在，插件可能未加载",
  500: "服务内部错误",
};

export async function api(path, { method = "GET", body, query, signal } = {}) {
  let url = path;
  if (query) {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value === undefined || value === null || value === "") return;
      (Array.isArray(value) ? value : [value]).forEach((item) => params.append(key, String(item)));
    });
    const text = params.toString();
    if (text) url += (url.includes("?") ? "&" : "?") + text;
  }
  const init = { method, signal, headers: { Accept: "application/json" } };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(url, init);
  } catch (err) {
    if (err && err.name === "AbortError") throw err;
    throw new ApiError("无法连接本地服务，请确认 VSE Toolbox 仍在运行");
  }

  let payload = null;
  try {
    payload = await response.json();
  } catch (_) {
    payload = null;
  }
  if (payload && payload.ok === true) return payload.data;
  const error = (payload && payload.error) || {};
  throw new ApiError(error.message || STATUS_MESSAGES[response.status] || `请求失败（HTTP ${response.status}）`, {
    status: response.status,
    type: error.type || "http",
    code: error.code || null,
    diagnostic: error.diagnostic || null,
  });
}

/** Plugin-scoped helpers: pluginApi("sor").get("rows", {query}). */
export function pluginApi(pluginId) {
  const base = `/api/p/${encodeURIComponent(pluginId)}/`;
  const resolve = (path) => base + String(path).replace(/^\/+/, "");
  return {
    get: (path, options = {}) => api(resolve(path), { ...options, method: "GET" }),
    post: (path, body, options = {}) => api(resolve(path), { ...options, method: "POST", body }),
    url: resolve,
  };
}

/**
 * Fetch `path` whenever `key` changes. Only the latest request may update
 * state (sequence guard + AbortController), so fast filter changes never
 * show stale rows. `path` null means "not ready yet" and fetches nothing.
 */
export function useResource(path, query) {
  const key = path === null ? null : `${path}?${JSON.stringify(query || {})}`;
  const [state, setState] = useState({ data: null, error: null, loading: path !== null });
  const seq = useRef(0);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (key === null) return undefined;
    const current = ++seq.current;
    const controller = new AbortController();
    setState((prev) => ({ data: prev.data, error: null, loading: true }));
    api(path, { query, signal: controller.signal }).then(
      (data) => {
        if (current === seq.current) setState({ data, error: null, loading: false });
      },
      (error) => {
        if (current !== seq.current || (error && error.name === "AbortError")) return;
        setState((prev) => ({ data: prev.data, error, loading: false }));
      },
    );
    return () => controller.abort();
  }, [key, reloadToken]);

  const reload = useCallback(() => setReloadToken((value) => value + 1), []);
  return { ...state, reload };
}
