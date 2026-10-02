// Excel 文件处理：小组件（状态徽标、错误卡片），并转出 logic.js 的纯函数。
import { html } from "/static/host/vendor/preact-htm.js";
import { display, statusLabel, statusTone } from "./logic.js";

export * from "./logic.js";

export function StatusChip({ status, text }) {
  return html`<span class=${`xt-chip ${statusTone(status)}`}>${text || statusLabel(status)}</span>`;
}

function isAuthError(error) {
  if (!error) return false;
  return error.status === 401 || /auth|login|credential|session/i.test(String(error.type || ""));
}

/** 错误卡片：脱敏显示；认证类错误且旧全局 openInPlaceLogin 存在时提供登录按钮。 */
export function ErrorCard({ error, onRetry, onDismiss }) {
  if (!error) return null;
  const fields = error.fields && typeof error.fields === "object" ? Object.entries(error.fields) : [];
  const canLogin = isAuthError(error) && typeof window !== "undefined" && typeof window.openInPlaceLogin === "function";
  return html`<div class="xt-error" role="alert">
    <div class="xt-error-text">
      <strong>${display(error.message || String(error))}</strong>
      ${error.status ? html`<span class="xt-error-meta">HTTP ${error.status}${error.type ? ` · ${error.type}` : ""}</span>` : null}
      ${fields.length > 0 && html`<ul class="xt-error-fields">
        ${fields.map(([key, message]) => html`<li key=${key}><code>${key}</code> ${display(message)}</li>`)}
      </ul>`}
    </div>
    <span class="xt-error-actions">
      ${canLogin && html`<button type="button" class="vk-btn is-primary" onClick=${() => window.openInPlaceLogin({})}>登录</button>`}
      ${onRetry && html`<button type="button" class="vk-btn" onClick=${onRetry}>重试</button>`}
      ${onDismiss && html`<button type="button" class="vk-btn" onClick=${onDismiss}>关闭</button>`}
    </span>
  </div>`;
}
