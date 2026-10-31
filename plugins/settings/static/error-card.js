// Structured error card: delegating to host ui-kit ErrorCard
import { html } from "/static/host/vendor/preact-htm.js";
import { ErrorCard as UiErrorCard } from "/static/host/ui-kit.js";
import { isAuthError, legacyGlobal } from "./client.js";

export function ErrorCard({ error, onReload, onRetrySave, onDismiss }) {
  if (!error) return null;
  const auth = isAuthError(error);
  const openLogin = legacyGlobal("openInPlaceLogin");
  const summary = auth ? "企业认证会话已失效" : (error.summary || "系统设置操作未成功");
  const impact = auth
    ? (openLogin ? "本地系统设置未受影响，但企业会话需要重新验证。请点击【重新登录】。" : "本地系统设置未受影响，但企业会话需要重新验证。请在下方「统一域账号登录」中重新登录。")
    : (error.impact || "表单中已输入的内容已完整保留，未覆盖未修改的配置项。");

  let onFix = null;
  if (auth && openLogin) {
    onFix = {
      label: "重新登录",
      onClick: () => openLogin({ notice: "企业会话已失效，请重新登录企业域账号。", onLoginSuccess: () => onReload && onReload() }),
    };
  } else if (onRetrySave) {
    onFix = { label: "重试保存", onClick: onRetrySave };
  } else if (onReload) {
    onFix = { label: "重新加载设置", onClick: onReload };
  }

  return html`<${UiErrorCard}
    what=${summary}
    todo=${impact}
    onFix=${onFix}
  />`;
}
