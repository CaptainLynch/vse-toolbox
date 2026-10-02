// Host-owned session services shared by the chrome and by plugin pages:
// text redaction, enterprise session badges and the in-place domain login.
// Nothing here touches the DOM at import time, so it also loads under Node.

/* ── Redaction ─────────────────────────────────────────────────────────
   The patterns are a verbatim copy of the legacy app.js
   SENSITIVE_VALUE_PATTERNS; tests/test_host_chrome.py compares both on a
   shared fixture list, so change them only together with that test. */
export const SENSITIVE_VALUE_PATTERNS = [
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

/** Redact, additionally masking a literal secret (e.g. the password just typed). */
export function redactWithSecret(value, secret = "") {
  let text = value === null || value === undefined ? "" : String(value);
  if (secret) text = text.split(secret).join("[redacted]");
  return redactSensitiveText(text);
}

/* ── Tiny observable store ─────────────────────────────────────────── */

export function createStore(initial) {
  let state = initial;
  const listeners = new Set();
  return {
    get: () => state,
    set(next) {
      state = typeof next === "function" ? next(state) : next;
      listeners.forEach((listener) => listener(state));
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

/* ── Session badges ────────────────────────────────────────────────── */

export const SESSION_SYSTEMS = [
  { key: "aras", name: "Aras", short: "Aras", sessionTitle: "Aras ECM 会话", initialTitle: "Aras / ECM 流程会话状态" },
  { key: "tdc", name: "TDC", short: "TDC", sessionTitle: "TDC 研发流程会话", initialTitle: "TDC 研发流程会话状态" },
];

/**
 * Map one system's session payload to the badge presentation. `session`
 * undefined means "not loaded yet" (template defaults); `{}` means unknown.
 */
export function badgeState(system, session) {
  if (session === undefined) {
    return { tone: "is-unknown", text: "未认证", title: system.initialTitle };
  }
  const value = session || {};
  const isAuth = Boolean(value.authenticated);
  const isExp = Boolean(value.expired);
  return {
    tone: isAuth ? "is-authenticated" : isExp ? "is-expired" : "is-unknown",
    text: isAuth ? "已认证" : isExp ? "已过期" : "未认证",
    title: `${system.sessionTitle}：${isAuth ? "有效" : isExp ? "已过期（需重新登录）" : "未认证"}`,
  };
}

/** null until the first update; then the latest `sessions` payload. */
export const sessionStore = createStore(null);

export function updateSessionBadges(sessions = {}) {
  sessionStore.set(sessions && typeof sessions === "object" ? sessions : {});
}

let refreshInFlight = null;

// 从 /api/settings 读取会话状态并刷新顶栏徽标（启动时与原位登录后使用）。
// 并发调用共用同一个请求。
export function refreshSessionBadges() {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    try {
      const resp = await fetch("/api/settings", { headers: { Accept: "application/json" }, cache: "no-store" });
      const body = await resp.json();
      if (resp.ok && body.ok && body.data) updateSessionBadges(body.data.sessions || {});
    } catch (_) {
      // 会话状态读取失败时保留徽标当前展示
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

/* ── In-place domain login ─────────────────────────────────────────── */

export const loginStore = createStore({ open: false, seq: 0, notice: "", onLoginSuccess: null, trigger: null });

export function openInPlaceLogin(options = {}) {
  const opts = options || {};
  loginStore.set((prev) => ({
    open: true,
    seq: prev.seq + 1,
    notice: opts.notice ? String(opts.notice) : "",
    onLoginSuccess: typeof opts.onLoginSuccess === "function" ? opts.onLoginSuccess : null,
    // 重复打开时保留最初的触发元素，关闭后焦点仍回到它。
    trigger: prev.open ? prev.trigger : (typeof document !== "undefined" ? document.activeElement : null),
  }));
}

export function closeInPlaceLogin() {
  const prev = loginStore.get();
  if (!prev.open) return;
  loginStore.set({ open: false, seq: prev.seq, notice: "", onLoginSuccess: null, trigger: null });
  const trigger = prev.trigger;
  if (trigger && typeof trigger.focus === "function") {
    try { trigger.focus(); } catch (_) { /* element may be gone */ }
  }
}

function loginSummary(results, password) {
  return SESSION_SYSTEMS.map((system) => {
    const item = (results || {})[system.key];
    if (!item) return null;
    return item.ok ? `${system.short} 成功` : `${system.short} 失败：${redactWithSecret(item.message || "认证失败", password)}`;
  }).filter(Boolean).join("；");
}

/**
 * Classify a /api/settings/domain-login response. `body` is the parsed JSON
 * (or null). kind: success | partial | vault | error. Every text is redacted,
 * including the literal password.
 */
export function loginOutcome(status, body, password) {
  const data = body && body.data && typeof body.data === "object" ? body.data : null;
  const error = (body && body.error) || {};
  const sessions = data && data.sessions ? data.sessions : null;
  if (status >= 200 && status < 300 && body && body.ok) {
    const results = (data && data.results) || null;
    const allOk = !results || SESSION_SYSTEMS.every((system) => results[system.key] && results[system.key].ok);
    if (allOk) return { kind: "success", tone: "ok", text: "登录成功，会话已建立", sessions, data };
    return { kind: "partial", tone: "warn", text: `部分登录成功：${loginSummary(results, password)}`, sessions, data };
  }
  if (status === 503 && error.type === "CredentialVaultUnavailable") {
    // 会话已建立，仅凭据保存失败：按警告展示，不当作登录失败。
    return { kind: "vault", tone: "warn", text: redactWithSecret(error.message || "凭据保存失败", password), sessions, data };
  }
  const detail = data && data.results
    ? loginSummary(data.results, password)
    : redactWithSecret(error.message || "域认证登录失败", password);
  return { kind: "error", tone: "error", text: `登录失败：${detail || "域认证登录失败"}`, sessions, data };
}

/** POST the credentials (body only, never the URL) and classify the result. */
export async function submitDomainLogin({ username, password, saveForScheduled }) {
  let resp;
  try {
    resp = await fetch("/api/settings/domain-login", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ username, password, saveForScheduled: Boolean(saveForScheduled) }),
      cache: "no-store",
    });
  } catch (err) {
    return { kind: "error", tone: "error", text: `登录失败：${redactWithSecret(err && err.message ? err.message : String(err), password)}`, sessions: null, data: null };
  }
  let body = null;
  try {
    body = await resp.json();
  } catch (_) {
    body = null;
  }
  return loginOutcome(resp.status, body, password);
}

/**
 * Publish the compatibility globals plugins and legacy code rely on. The host
 * versions always win over the legacy app.js function declarations.
 */
export function installSessionGlobals(target = typeof window !== "undefined" ? window : null) {
  if (!target) return;
  target.openInPlaceLogin = openInPlaceLogin;
  target.updateGlobalSessionBadges = updateSessionBadges;
  target.redactSensitiveText = redactSensitiveText;
  // Legacy-internal name; kept so a still-loaded app.js reuses the host fetch.
  target.refreshGlobalSessionBadges = refreshSessionBadges;
}
