// Top-bar enterprise session badges (Aras / TDC) and the login entry button.
import { html, useEffect, useState } from "../vendor/preact-htm.js";
import { SESSION_SYSTEMS, badgeState, openInPlaceLogin, sessionStore } from "../session.js";

export const GLOBAL_LOGIN_NOTICE = "请输入企业域账号登录；成功后将更新当前会话状态。";

export function useStore(store) {
  const [value, setValue] = useState(store.get());
  useEffect(() => {
    setValue(store.get());
    return store.subscribe(setValue);
  }, [store]);
  return value;
}

export function SessionBadges() {
  const sessions = useStore(sessionStore);
  return html`<div class="hc-session-status" aria-label="企业会话状态" role="region">
    <div class="hc-badge-group">
      ${SESSION_SYSTEMS.map((system) => {
        const state = badgeState(system, sessions === null ? undefined : sessions[system.key]);
        return html`<span key=${system.key} id=${`hc-badge-${system.key}`} class=${`hc-session-badge ${state.tone}`} title=${state.title}>
          <span class="hc-badge-dot" aria-hidden="true"></span>
          <span class="hc-badge-name">${system.name}</span>
          <span class="hc-badge-state">${state.text}</span>
        </span>`;
      })}
    </div>
    <button
      id="hc-login-btn"
      class="hc-login-btn"
      type="button"
      aria-haspopup="dialog"
      onClick=${() => openInPlaceLogin({ notice: GLOBAL_LOGIN_NOTICE })}
    >登录 / 切换</button>
  </div>`;
}
