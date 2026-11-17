// Excel 文件处理：小组件（状态徽标、环境卡片、错误卡片），并转出 logic.js 的纯函数。
import { html } from "/static/host/vendor/preact-htm.js";
import { ErrorCard as UiErrorCard } from "/static/host/ui-kit.js";
import {
  classifyEnvStatus,
  display,
  formatErrorTodo,
  formatErrorWhat,
  isAuthError,
  renderEnvStatus,
  statusLabel,
  statusTone,
} from "./logic.js";

export * from "./logic.js";

export function StatusChip({ status, text }) {
  return html`<span class=${`xt-chip ${statusTone(status)}`}>${text || statusLabel(status)}</span>`;
}

/**
 * 环境检查卡片：呈现三态（正常/需要检查/不可用）或暂未提供占位说明。
 */
export function EnvCheckCard({ env, onRefresh }) {
  const rendered = renderEnvStatus(env);
  return html`<section class="xt-card xt-env-card" aria-label="环境检查">
    <div class="xt-card-head">
      <div>
        <p class="xt-eyebrow">环境</p>
        <h4>环境检查</h4>
      </div>
      <div class="xt-env-actions">
        <span class=${`xt-chip ${rendered.toneClass}`.trim()}>${rendered.label}</span>
        ${onRefresh && html`<button type="button" class="vk-btn" onClick=${onRefresh}>刷新状态</button>`}
      </div>
    </div>
    <p class="xt-hint">${rendered.description}</p>
  </section>`;
}

/**
 * 错误卡片：统一接入 host ui-kit 的 ErrorCard，保留错误信息内容不变。
 */
export function ErrorCard(props = {}) {
  if (!props) return null;
  // 直接以 what / todo 形式调用
  if (props.what !== undefined) {
    return html`<${UiErrorCard}
      what=${props.what}
      todo=${props.todo || "请核对文件路径与参数后重试"}
      onFix=${props.onFix}
      onDiagnostics=${props.onDiagnostics}
    />`;
  }

  const error = props.error;
  if (!error) return null;

  const what = formatErrorWhat(error);
  const todo = props.todo || formatErrorTodo(error);
  const canLogin = isAuthError(error) && typeof window !== "undefined" && typeof window.openInPlaceLogin === "function";

  let onFix = props.onFix;
  if (!onFix) {
    if (canLogin) {
      onFix = { label: "重新登录", onClick: () => window.openInPlaceLogin({}) };
    } else if (props.onRetry) {
      onFix = { label: "重试", onClick: props.onRetry };
    }
  }

  return html`<${UiErrorCard}
    what=${what}
    todo=${todo}
    onFix=${onFix}
    onDiagnostics=${props.onDiagnostics}
  />`;
}

