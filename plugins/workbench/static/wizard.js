// 首次使用向导（需求 U1）：欢迎 → 登录公司账号（同时连通 Aras 与 TDC）→ 完成。
// 只在没有登录且没有跳过过的时候出现；"以后再说"之后不再自动弹出。
import { html, useState } from "/static/host/vendor/preact-htm.js";
import { submitDomainLogin, updateSessionBadges } from "/static/host/session.js";

const DISMISS_KEY = "vse.wizardDone";

export function wizardDismissed() {
  try {
    return window.localStorage.getItem(DISMISS_KEY) === "1";
  } catch (_err) {
    return false;
  }
}

function dismiss() {
  try {
    window.localStorage.setItem(DISMISS_KEY, "1");
  } catch (_err) {
    // 存不住也没关系
  }
}

export function Wizard({ projectName, onClose }) {
  const [step, setStep] = useState(0);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [save, setSave] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);

  const close = (done) => {
    dismiss();
    onClose(done);
  };

  const login = async (event) => {
    event.preventDefault();
    if (!username || !password) return;
    setBusy(true);
    setMessage(null);
    const outcome = await submitDomainLogin({ username, password, saveForScheduled: save });
    setPassword("");
    setBusy(false);
    if (outcome.sessions) updateSessionBadges(outcome.sessions);
    if (outcome.kind === "error") {
      setMessage({ tone: "bad", text: outcome.text });
      return;
    }
    setMessage(outcome.kind === "success" ? null : { tone: "warn", text: outcome.text });
    setStep(2);
  };

  const steps = html`<div class="wb-steps">${[0, 1, 2].map((i) => html`<i class=${i <= step ? "on" : ""} key=${i}></i>`)}</div>`;

  let body;
  if (step === 0) {
    body = html`<div style="text-align:center">
      <div class="hc-brand-mark" style="margin:0 auto 12px;width:56px;height:56px;font-size:28px">V</div>
      <h1>欢迎使用 VSE Toolbox</h1>
      <p class="wb-sub">只需要登录一次公司账号，之后交付物进度会自动更新，日报一键生成。</p>
    </div>
    <div class="wb-row" style="margin-top:20px;justify-content:space-between">
      <button type="button" class="wb-link" onClick=${() => close(false)}>以后再说</button>
      <button type="button" class="wb-btn is-primary" onClick=${() => setStep(1)}>开始</button>
    </div>`;
  } else if (step === 1) {
    body = html`<form onSubmit=${login}>
      <h2>登录公司域账号</h2>
      <p class="wb-sub">一次登录同时连通 Aras 和 TDC。</p>
      <label class="wb-field" style="margin-top:14px"><span>域账号</span>
        <input type="text" autocomplete="username" value=${username} onInput=${(e) => setUsername(e.currentTarget.value)} disabled=${busy} autofocus />
      </label>
      <label class="wb-field"><span>密码</span>
        <input type="password" autocomplete="current-password" value=${password} onInput=${(e) => setPassword(e.currentTarget.value)} disabled=${busy} />
      </label>
      <label class="wb-check"><input type="checkbox" checked=${save} onChange=${(e) => setSave(e.currentTarget.checked)} />
        <span>记住密码，用于自动同步（加密保存在本机，只有你的 Windows 账号能读取）</span></label>
      ${message && html`<p class=${message.tone === "bad" ? "wb-error" : "wb-sub"}>${message.text}</p>`}
      <div class="wb-row" style="margin-top:18px;justify-content:space-between">
        <button type="button" class="wb-link" onClick=${() => setStep(0)}>上一步</button>
        <button type="submit" class="wb-btn is-primary" disabled=${busy || !username || !password}>${busy ? "正在验证…" : "登录"}</button>
      </div>
    </form>`;
  } else {
    body = html`<div>
      <h2>准备就绪</h2>
      ${message && html`<p class="wb-sub">${message.text}</p>`}
      <ul class="wb-sub" style="padding-left:18px;margin:12px 0 0">
        <li>账号：${username}（${save ? "已保存，可自动同步" : "未保存密码，自动同步需要你在线"}）</li>
        <li>项目：${projectName || "—"}</li>
        <li>接下来在「今天」页面按提示开启交付物自动同步</li>
      </ul>
      <div class="wb-row" style="margin-top:18px;justify-content:flex-end">
        <button type="button" class="wb-btn is-primary" onClick=${() => close(true)}>开始使用</button>
      </div>
    </div>`;
  }
  return html`<div class="wb-scrim" role="dialog" aria-modal="true" aria-label="首次使用向导">
    <div class="wb-modal">${steps}${body}</div>
  </div>`;
}
