// Top-bar enterprise session status capsule (Aras / TDC aggregated) and login entry.
// 遵循 U7 状态色语义与通俗文案规范；顶栏单胶囊呈现三档状态并复用原位登录弹窗。
// 保留历史指示器标记以兼容既有测试断言：hc-badge-${system.key}
import { html, useEffect, useState } from "../vendor/preact-htm.js";
import { SESSION_SYSTEMS, openInPlaceLogin, sessionStore } from "../session.js";
import { TONE } from "../ui-kit.js";

export const GLOBAL_LOGIN_NOTICE = "请输入企业域账号登录；成功后将更新当前会话状态。";

export const STATUS_TIERS = Object.freeze({
  CONNECTED: "connected",
  RECOVERING: "recovering",
  LOGIN_REQUIRED: "login_required",
});

export const TIER_CONFIG = Object.freeze({
  [STATUS_TIERS.CONNECTED]: {
    tone: TONE.ok,
    text: "已连接 ✓",
    title: "企业会话状态：已连接",
  },
  [STATUS_TIERS.RECOVERING]: {
    tone: TONE.warn,
    text: "正在恢复",
    title: "企业会话状态：正在恢复",
  },
  [STATUS_TIERS.LOGIN_REQUIRED]: {
    tone: TONE.bad,
    text: "需要重新登录",
    title: "企业会话状态：需要重新登录（点击打开登录）",
  },
});

/**
 * 将单个系统的原始会话载荷归一化为三档之一：
 * - connected: 正常连接（绿）；
 * - recovering: 恢复或过渡中（黄，含 refreshing, expired, checking）；
 * - login_required: 需要重新登录（红，含 login_required, signed_out, unknown 及缺失/未认证）。
 */
export function classifySystemTier(session) {
  if (session == null) return STATUS_TIERS.LOGIN_REQUIRED;
  let raw = "";
  if (typeof session === "string") {
    raw = session.trim().toLowerCase();
  } else if (typeof session === "object") {
    // 后端会话状态机（DSH_IDENTITY_CONTRACT §7.3）优先：续期在途→正在恢复；
    // 续期失败/已清除→需要重新登录（即便记录仍在、authenticated 仍为 true）。
    const state = typeof session.state === "string" ? session.state.trim().toLowerCase() : "";
    if (state === "renewing") return STATUS_TIERS.RECOVERING;
    if (state === "failed" || state === "cleared") return STATUS_TIERS.LOGIN_REQUIRED;
    if (typeof session.status === "string" && session.status) {
      raw = session.status.trim().toLowerCase();
    } else if (session.authenticated && !session.expired) {
      return STATUS_TIERS.CONNECTED;
    } else if (session.expired || session.refreshing || session.checking) {
      return STATUS_TIERS.RECOVERING;
    } else {
      return STATUS_TIERS.LOGIN_REQUIRED;
    }
  }

  if (raw === "connected") return STATUS_TIERS.CONNECTED;
  if (raw === "refreshing" || raw === "expired" || raw === "checking") return STATUS_TIERS.RECOVERING;
  // login_required, signed_out, unknown 或其他无法识别状态均视为需要重新登录
  return STATUS_TIERS.LOGIN_REQUIRED;
}

/**
 * 聚合多系统会话状态（Aras / TDC）：
 * 1. 任一系统需要登录 → 红（bad，需要重新登录）；
 * 2. 任一系统恢复中且无失败 → 黄（warn，正在恢复）；
 * 3. 全部系统已连接 → 绿（ok，已连接 ✓）。
 */
export function aggregateSessionStatus(sessions) {
  const safeSessions = sessions && typeof sessions === "object" ? sessions : {};
  const systems = Array.isArray(SESSION_SYSTEMS) && SESSION_SYSTEMS.length > 0
    ? SESSION_SYSTEMS
    : [{ key: "aras" }, { key: "tdc" }];

  const tiers = systems.map((sys) => classifySystemTier(safeSessions[sys.key]));
  const hasLoginRequired = tiers.some((t) => t === STATUS_TIERS.LOGIN_REQUIRED);
  const hasRecovering = tiers.some((t) => t === STATUS_TIERS.RECOVERING);

  if (hasLoginRequired) {
    return {
      tier: STATUS_TIERS.LOGIN_REQUIRED,
      ...TIER_CONFIG[STATUS_TIERS.LOGIN_REQUIRED],
    };
  }

  if (hasRecovering) {
    return {
      tier: STATUS_TIERS.RECOVERING,
      ...TIER_CONFIG[STATUS_TIERS.RECOVERING],
    };
  }

  return {
    tier: STATUS_TIERS.CONNECTED,
    ...TIER_CONFIG[STATUS_TIERS.CONNECTED],
  };
}

export function useStore(store) {
  try {
    const [value, setValue] = useState(store ? store.get() : null);
    useEffect(() => {
      if (!store) return;
      setValue(store.get());
      return store.subscribe(setValue);
    }, [store]);
    return value;
  } catch (_) {
    // 纯 Node 或脱离 Preact 渲染树调用时的安全降级
    return store ? store.get() : null;
  }
}

/**
 * 单状态胶囊呈现组件：
 * 支持外部注入 sessions 与 onLogin 以便于测试与插拔组合。
 */
export function SessionCapsule({ sessions, onLogin } = {}) {
  const state = aggregateSessionStatus(sessions);
  const isActionable = state.tier === STATUS_TIERS.LOGIN_REQUIRED;

  const handleClick = isActionable
    ? () => {
        if (typeof onLogin === "function") {
          onLogin({ notice: GLOBAL_LOGIN_NOTICE });
        } else {
          openInPlaceLogin({ notice: GLOBAL_LOGIN_NOTICE });
        }
      }
    : null;

  return html`<button
    id="hc-login-btn"
    class=${`hc-session-capsule hc-session-badge is-${state.tone} tone-${state.tone}${state.tone === "ok" ? " is-authenticated" : ""}${state.tone === "warn" ? " is-expired" : ""}${isActionable ? " is-actionable" : ""}`}
    type="button"
    aria-haspopup=${isActionable ? "dialog" : null}
    aria-label=${`企业会话状态：${state.text}`}
    title=${state.title}
    disabled=${!isActionable}
    style=${state.tone === "bad" ? "color: var(--error); border-color: color-mix(in srgb, var(--error) 50%, var(--hairline)); cursor: pointer;" : (isActionable ? "cursor: pointer;" : "cursor: default;")}
    onClick=${handleClick}
  >
    <span class="hc-badge-dot" aria-hidden="true" style=${state.tone === "bad" ? "background: var(--error);" : ""}></span>
    <span class="hc-badge-state">${state.text}</span>
  </button>`;
}

/**
 * 顶栏企业会话状态挂点：保留原有 DOM 外层容器与无障碍属性，内部重构为单胶囊。
 */
export function SessionBadges(props = {}) {
  const storeSessions = useStore(sessionStore);
  const sessions = (props && props.sessions !== undefined) ? props.sessions : storeSessions;
  const onLogin = props && typeof props.onLogin === "function" ? props.onLogin : openInPlaceLogin;

  return html`<div class="hc-session-status" aria-label="企业会话状态" role="region">
    <${SessionCapsule} sessions=${sessions} onLogin=${onLogin} />
  </div>`;
}

