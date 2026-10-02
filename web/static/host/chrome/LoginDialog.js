// In-place enterprise domain login dialog. Keeps the current page, drafts
// and query results intact; plugins open it via window.openInPlaceLogin.
// The password lives only in the input element: it is read at submit time,
// sent in the POST body and cleared on every outcome and on close.
import { html, useEffect, useRef, useState } from "../vendor/preact-htm.js";
import {
  closeInPlaceLogin,
  loginStore,
  refreshSessionBadges,
  submitDomainLogin,
  updateSessionBadges,
} from "../session.js";
import { useStore } from "./SessionBadges.js";

const SUCCESS_CLOSE_DELAY_MS = 250;

export function LoginDialog() {
  const login = useStore(loginStore);
  const userRef = useRef(null);
  const passRef = useRef(null);
  const [saveVault, setSaveVault] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState({ tone: "", text: "" });
  // Partial success / vault warning: session exists, the user confirms to continue.
  const [pending, setPending] = useState(null);

  const clearPassword = () => {
    if (passRef.current) passRef.current.value = "";
  };

  useEffect(() => {
    if (!login.open) {
      clearPassword();
      return undefined;
    }
    setStatus({ tone: "", text: "" });
    setSaveVault(false); // 严禁默认勾选，明确隔离定时下载授权
    setPending(null);
    clearPassword();
    const user = userRef.current;
    if (user && user.value.trim()) passRef.current && passRef.current.focus();
    else if (user) user.focus();
    const onKey = (event) => {
      if (event.key === "Escape") closeInPlaceLogin();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [login.open, login.seq]);

  const finish = (seq, data) => {
    const current = loginStore.get();
    if (!current.open || current.seq !== seq) return;
    const callback = current.onLoginSuccess;
    closeInPlaceLogin();
    if (typeof callback === "function") callback(data);
  };

  const onSubmit = async (event) => {
    event.preventDefault();
    if (busy) return;
    const seq = loginStore.get().seq;
    const username = ((userRef.current && userRef.current.value) || "").trim();
    const password = (passRef.current && passRef.current.value) || "";
    if (!username || !password) {
      clearPassword();
      setStatus({ tone: "error", text: "域用户名和密码不能为空" });
      return;
    }
    setBusy(true);
    setPending(null);
    setStatus({ tone: "", text: "正在进行企业域认证登录..." });
    let outcome;
    try {
      outcome = await submitDomainLogin({ username, password, saveForScheduled: saveVault });
    } finally {
      clearPassword();
      setBusy(false);
    }
    if (outcome.sessions) updateSessionBadges(outcome.sessions);
    else refreshSessionBadges();
    if (loginStore.get().seq !== seq) return;
    setStatus({ tone: outcome.tone, text: outcome.text });
    if (outcome.kind === "success") {
      setTimeout(() => finish(seq, outcome.data), SUCCESS_CLOSE_DELAY_MS);
    } else if (outcome.kind === "partial" || outcome.kind === "vault") {
      setPending({ seq, data: outcome.data });
    }
  };

  // Stays mounted while closed so the username survives between openings.
  return html`<div id="hc-login-dialog" class="hc-modal" hidden=${!login.open} role="dialog" aria-modal="true" aria-labelledby="hc-login-title">
    <div class="hc-modal-backdrop" onClick=${closeInPlaceLogin}></div>
    <div class="hc-modal-card" role="document">
      <div class="hc-modal-head">
        <div>
          <p class="hc-eyebrow">企业域账号认证</p>
          <h3 id="hc-login-title">登录企业系统</h3>
        </div>
        <button class="hc-modal-close" type="button" aria-label="关闭登录弹窗" onClick=${closeInPlaceLogin}>×</button>
      </div>
      <div class="hc-modal-body">
        <p class="hc-field-note">同时为 Aras 和 TDC 发起企业域账号校验；密码仅在内存中用于本次认证，不落盘、不写入前端缓存。</p>
        ${login.notice && html`<div id="hc-login-notice" class="hc-login-notice">${login.notice}</div>`}
        <form id="hc-login-form" class="hc-login-form" autocomplete="on" onSubmit=${onSubmit}>
          <div class="hc-login-grid">
            <label class="hc-field">
              <span>域用户名</span>
              <input ref=${userRef} id="hc-login-username" name="domainUsername" autocomplete="username" placeholder="请输入域账号用户名" required />
            </label>
            <label class="hc-field">
              <span>域密码</span>
              <input ref=${passRef} id="hc-login-password" name="domainPassword" type="password" autocomplete="current-password" placeholder="请输入域账号密码" required />
            </label>
            <div class="hc-scope-card">
              <div class="hc-scope-row">
                <span class="hc-scope-icon" aria-hidden="true">✓</span>
                <div class="hc-scope-desc">
                  <strong>当前会话查询</strong>
                  <span>登录成功后建立内存会话，供当前页面各报表与交付物直接查询，关闭浏览器或超时后失效。</span>
                </div>
              </div>
              <label class="hc-checkbox-row hc-scope-checkbox">
                <input
                  type="checkbox"
                  id="hc-login-save-vault"
                  name="saveForScheduled"
                  checked=${saveVault}
                  onChange=${(event) => setSaveVault(event.currentTarget.checked)}
                />
                <span>允许本机自动任务使用已保存账号（写入 Windows 凭据保护库，供后台定时下载使用）</span>
              </label>
            </div>
          </div>
          <div class="hc-login-actions">
            ${pending
              ? html`<button id="hc-login-continue-btn" class="hc-primary-btn" type="button" onClick=${() => finish(pending.seq, pending.data)}>继续</button>`
              : html`<button id="hc-login-submit-btn" class="hc-primary-btn" type="submit" disabled=${busy}>立即登录</button>`}
            <button id="hc-login-cancel-btn" class="hc-segment" type="button" onClick=${closeInPlaceLogin}>取消</button>
            <span id="hc-login-status" class=${`hc-status-msg${status.tone ? ` is-${status.tone}` : ""}`} aria-live="polite">${status.text}</span>
          </div>
        </form>
      </div>
    </div>
  </div>`;
}
