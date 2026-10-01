// Enterprise domain sessions: status, unified domain login (write-only
// password), and session / credential-vault clearing.
import { html, useState } from "/static/host/vendor/preact-htm.js";
import { formatDateTime, redactText, refreshGlobalBadges, request } from "./client.js";

const SYSTEMS = [
  { key: "aras", title: "ECM 流程会话", short: "Aras" },
  { key: "tdc", title: "TDC 研发流程会话", short: "TDC" },
];

export function Chip({ tone, children }) {
  return html`<span class=${`st-chip is-${tone}`}>${children}</span>`;
}

function sessionTone(session) {
  if (session.authenticated) return ["ok", "已认证"];
  if (session.expired) return ["warn", "已过期"];
  return ["idle", "未认证"];
}

function sessionDetail(session) {
  if (!session.updatedAt) return "未登录";
  return `更新时间 ${formatDateTime(session.updatedAt)} · ${session.expired ? "已过期" : "有效"}`;
}

function StatusRow({ title, detail, tone, label }) {
  return html`<div class="st-status-row">
    <div class="st-status-info"><strong>${title}</strong><span>${detail}</span></div>
    <${Chip} tone=${tone}>${label}<//>
  </div>`;
}

function loginSummary(results, password) {
  const parts = SYSTEMS.map((system) => {
    const item = (results || {})[system.key];
    if (!item) return null;
    return item.ok ? `${system.short} 成功` : `${system.short} 失败：${redactText(item.message || "认证失败", password)}`;
  }).filter(Boolean);
  return parts.join("；");
}

function DomainLoginForm({ onChanged }) {
  const [username, setUsername] = useState("");
  // 密码只在提交前存在于组件状态，提交结束（无论成败）立即清空。
  const [password, setPassword] = useState("");
  const [saveForScheduled, setSaveForScheduled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState({ tone: "", text: "" });

  const submit = async (event) => {
    event.preventDefault();
    if (busy) return;
    const user = username.trim();
    const secret = password;
    if (!user || !secret) {
      setStatus({ tone: "error", text: "用户名和密码不能为空" });
      return;
    }
    setBusy(true);
    setStatus({ tone: "", text: "正在进行域认证登录…" });
    let sessions = null;
    try {
      const data = await request("/api/settings/domain-login", {
        method: "POST",
        body: { username: user, password: secret, saveForScheduled },
      });
      sessions = data && data.sessions;
      const results = (data && data.results) || {};
      const allOk = SYSTEMS.every((system) => results[system.key] && results[system.key].ok);
      setStatus(allOk
        ? { tone: "ok", text: `登录成功，会话已建立${saveForScheduled ? "；凭据已保存至凭据保护库" : ""}` }
        : { tone: "warn", text: `部分登录成功：${loginSummary(results, secret)}` });
    } catch (err) {
      sessions = err.data && err.data.sessions;
      if (err.type === "CredentialVaultUnavailable") {
        // 会话已建立，仅凭据保存失败：按警告展示，不当作登录失败。
        setStatus({ tone: "warn", text: redactText(err.message, secret) });
      } else {
        const detail = err.data && err.data.results ? loginSummary(err.data.results, secret) : redactText(err.message, secret);
        setStatus({ tone: "error", text: `登录失败：${detail || "域认证登录失败"}` });
      }
    } finally {
      setPassword("");
      setBusy(false);
    }
    refreshGlobalBadges(sessions);
    onChanged();
  };

  return html`<form class="st-login" autocomplete="on" onSubmit=${submit} novalidate>
    <h4>统一域账号登录</h4>
    <p class="st-field-note">同时为 Aras 和 TDC 系统发起域登录校验，不保存明文密码。</p>
    <div class="st-login-grid">
      <div class="st-field">
        <label for="st-login-username">域用户名</label>
        <input id="st-login-username" name="username" autocomplete="username" placeholder="请输入域账号用户名"
          value=${username} disabled=${busy} onInput=${(e) => setUsername(e.currentTarget.value)} />
      </div>
      <div class="st-field">
        <label for="st-login-password">域密码</label>
        <input id="st-login-password" name="password" type="password" autocomplete="current-password"
          placeholder="请输入域账号密码" value=${password} disabled=${busy}
          onInput=${(e) => setPassword(e.currentTarget.value)} />
      </div>
      <label class="st-check is-wide">
        <input type="checkbox" checked=${saveForScheduled} disabled=${busy}
          onChange=${(e) => setSaveForScheduled(e.currentTarget.checked)} />
        <span>保存至凭据保护库（供后台定时下载使用）</span>
      </label>
    </div>
    <div class="st-actions">
      <button type="submit" class="vk-btn is-primary" disabled=${busy}>登录 / 重新登录</button>
      <span class=${`st-status ${status.tone ? `is-${status.tone}` : ""}`} aria-live="polite">${status.text}</span>
    </div>
  </form>`;
}

function ClearSessions({ onChanged, onError }) {
  const [busy, setBusy] = useState(false);
  const [confirmAll, setConfirmAll] = useState(false);
  const [status, setStatus] = useState("");

  const clear = async (system, clearCredentialVault) => {
    if (busy) return;
    setBusy(true);
    setConfirmAll(false);
    setStatus("正在清除会话…");
    onError(null);
    try {
      const data = await request("/api/settings/sessions", { method: "DELETE", body: { system, clearCredentialVault } });
      setStatus(clearCredentialVault ? "会话与已保存凭据已清除" : "会话已清除");
      refreshGlobalBadges(data && data.sessions);
    } catch (err) {
      setStatus("");
      onError(Object.assign(err, { summary: "清除会话未成功", impact: "本地系统设置未受影响。" }));
    } finally {
      setBusy(false);
      onChanged();
    }
  };

  return html`<div class="st-clear">
    <h4>清除已保存会话</h4>
    <div class="st-button-row">
      <button type="button" class="vk-btn" disabled=${busy} onClick=${() => clear("aras", false)}>清除 Aras 会话</button>
      <button type="button" class="vk-btn" disabled=${busy} onClick=${() => clear("tdc", false)}>清除 TDC 会话</button>
      ${confirmAll
        ? html`<button type="button" class="vk-btn st-danger" disabled=${busy} onClick=${() => clear(null, true)}>确认清除全部</button>
          <button type="button" class="vk-btn" disabled=${busy} onClick=${() => setConfirmAll(false)}>取消</button>`
        : html`<button type="button" class="vk-btn" disabled=${busy} onClick=${() => setConfirmAll(true)}>清除全部会话与凭据</button>`}
    </div>
    ${confirmAll && html`<p class="st-field-note">将清除 Aras、TDC 会话，并删除凭据保护库中供定时下载使用的域账号凭据。</p>`}
    <span class="st-status" aria-live="polite">${status}</span>
  </div>`;
}

export function SessionsCard({ sessions, vaultConfigured, onChanged, onError }) {
  const all = sessions || {};
  return html`<section class="st-card">
    <header class="st-card-head">
      <p class="st-eyebrow">域账号与会话</p>
      <h3>企业认证会话状态</h3>
    </header>
    <div class="st-status-list">
      ${SYSTEMS.map((system) => {
        const session = all[system.key] || {};
        const [tone, label] = sessionTone(session);
        return html`<${StatusRow} key=${system.key} title=${system.title} detail=${sessionDetail(session)} tone=${tone} label=${label} />`;
      })}
      <${StatusRow}
        title="Windows 凭据保护库"
        detail="用于后台定时任务自动登录"
        tone=${vaultConfigured ? "ok" : "idle"}
        label=${vaultConfigured ? "已配置" : "未配置"}
      />
    </div>
    <${DomainLoginForm} onChanged=${onChanged} />
    <${ClearSessions} onChanged=${onChanged} onError=${onError} />
  </section>`;
}
