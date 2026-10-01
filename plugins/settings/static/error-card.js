// Structured error card (parity with legacy renderStructuredErrorCard):
// summary + impact + actions + collapsible technical detail.
import { html } from "/static/host/vendor/preact-htm.js";
import { isAuthError, legacyGlobal, redactText } from "./client.js";

export function ErrorCard({ error, onReload, onRetrySave, onDismiss }) {
  if (!error) return null;
  const auth = isAuthError(error);
  const openLogin = legacyGlobal("openInPlaceLogin");
  const actions = [];
  if (auth) {
    if (openLogin) {
      actions.push({
        label: "重新登录",
        primary: true,
        run: () => openLogin({ notice: "企业会话已失效，请重新登录企业域账号。", onLoginSuccess: () => onReload && onReload() }),
      });
    }
  } else {
    if (onRetrySave) actions.push({ label: "重试保存", primary: true, run: onRetrySave });
    if (onReload) actions.push({ label: "重新加载设置", primary: !onRetrySave, run: onReload });
  }
  if (onDismiss) actions.push({ label: "关闭", primary: false, run: onDismiss });
  const summary = auth ? "企业认证会话已失效" : (error.summary || "系统设置操作未成功");
  const impact = auth
    ? "本地系统设置未受影响，但企业会话需要重新验证。"
    : (error.impact || "表单中已输入的内容已完整保留，未覆盖未修改的配置项。");
  return html`<div class="st-error-card" role="alert">
    <strong class="st-error-summary">${summary}</strong>
    <p class="st-error-impact">${impact}</p>
    ${auth && !openLogin && html`<p class="st-error-impact">请在下方「统一域账号登录」中重新登录。</p>`}
    ${actions.length > 0 && html`<div class="st-error-actions">
      ${actions.map((action) => html`<button
        type="button"
        key=${action.label}
        class=${action.primary ? "vk-btn is-primary" : "vk-btn"}
        onClick=${action.run}
      >${action.label}</button>`)}
    </div>`}
    <details class="st-error-tech">
      <summary>技术详情</summary>
      <code>${redactText(error.message || String(error))}</code>
    </details>
  </div>`;
}
