// 程序更新卡片（v2 启动器）：显示当前版本、下载文件夹里发现的新版本，一键安装并重启。
// 不由 v2 启动器运行时（源码直接运行）整张卡片不显示。
import { html, useCallback, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { request, SettingsError } from "./client.js";
import { Chip } from "./sessions.js";

const BASE = "/api/p/settings/app-updates";
const EVENT_LABELS = {
  installed: "已安装",
  staged: "已校验，待重启",
  activated: "已生效",
  rolledBack: "启动失败，已自动回到之前的版本",
  databaseRestored: "已恢复更新前的数据",
  manualRollback: "已手动回滚",
  installFailed: "安装失败",
  bootFailed: "启动失败",
  stateRecovered: "已修复损坏的版本记录",
};

async function upload(file) {
  const form = new FormData();
  form.append("file", file, file.name);
  let response;
  try {
    response = await fetch(`${BASE}/upload`, { method: "POST", body: form, cache: "no-store" });
  } catch (_err) {
    throw new SettingsError("无法连接本地服务，请确认 VSE Toolbox 仍在运行");
  }
  const payload = await response.json().catch(() => null);
  if (response.ok && payload && payload.ok) return payload.data;
  throw new SettingsError((payload && payload.error && payload.error.message) || `安装失败（HTTP ${response.status}）`);
}

function versionOf(payload) {
  const data = (payload && payload.data) || payload || {};
  return String(data.rawVersion || data.version || "");
}

/**
 * 重启期间轮询 /api/version。旧进程可能还要几秒才退出，所以只有在
 * 「服务断开过又恢复」或「版本号变了」时才刷新，避免刷新到旧版本。
 */
async function waitForRestart(setNotice, before) {
  const deadline = Date.now() + 120000;
  let sawDown = false;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    try {
      const response = await fetch("/api/version", { cache: "no-store" });
      if (!response.ok) {
        sawDown = true;
        continue;
      }
      const version = versionOf(await response.json().catch(() => null));
      if (sawDown || (before && version && version !== before)) {
        window.location.reload();
        return;
      }
    } catch (_err) {
      sawDown = true; // 服务正在重启
    }
  }
  setNotice({ tone: "error", text: "程序重启时间较长，请稍后手动刷新页面，或从右下角托盘重新打开" });
}

export function AppUpdatesCard() {
  const [data, setData] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef(null);

  const load = useCallback(async () => {
    try {
      setData(await request(BASE));
    } catch (err) {
      setNotice({ tone: "error", text: err.message || String(err) });
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const run = async (action) => {
    setBusy(true);
    setNotice(null);
    try {
      await action();
    } catch (err) {
      setNotice({ tone: "error", text: err.message || String(err) });
      setBusy(false);
    }
  };

  const restart = (text) => run(async () => {
    await request(`${BASE}/restart`, { method: "POST" });
    setNotice({ tone: "ok", text: text || "正在重新启动，大约 10 秒后自动刷新…" });
    await waitForRestart(setNotice, data && data.current);
  });

  const install = (file) => run(async () => {
    const result = await request(`${BASE}/install`, { method: "POST", body: { file } });
    setNotice({ tone: "ok", text: `${result.message}。正在重新启动…` });
    await request(`${BASE}/restart`, { method: "POST" });
    await waitForRestart(setNotice, data && data.current);
  });

  const onUpload = (event) => {
    event.preventDefault();
    const file = fileInput.current && fileInput.current.files && fileInput.current.files[0];
    if (!file) {
      setNotice({ tone: "error", text: "请先选择 .vsepkg 更新包" });
      return;
    }
    run(async () => {
      const result = await upload(file);
      fileInput.current.value = "";
      await load();
      setNotice({ tone: "ok", text: result.message });
      setBusy(false);
    });
  };

  const rollback = () => {
    if (!window.confirm(`确定回到上一版本 ${data.previous} 吗？程序会立即重启。`)) return;
    run(async () => {
      const result = await request(`${BASE}/rollback`, { method: "POST" });
      setNotice({ tone: "ok", text: result.message });
      await waitForRestart(setNotice, data && data.current);
    });
  };

  if (!data || !data.managed) return null;
  const available = data.available || [];
  const staged = data.staged || [];

  return html`<section class="st-card">
    <header class="st-card-head">
      <p class="st-eyebrow">程序</p>
      <h3>程序更新</h3>
    </header>
    ${notice && html`<p class=${`st-status is-${notice.tone === "ok" ? "ok" : "error"}`} role="status">${notice.text}</p>`}
    <div class="st-status-list">
      <div class="st-status-row">
        <div class="st-status-info"><strong>当前版本 ${data.current || "-"}</strong>
          <span>${data.previous ? `上一版本 ${data.previous}（可回滚）` : "没有可回滚的上一版本"}</span></div>
        <span class="st-actions">
          ${data.previous && html`<button type="button" class="vk-btn" disabled=${busy} onClick=${rollback}>回到上一版本</button>`}
        </span>
      </div>
      ${staged.map((version) => html`<div class="st-status-row" key=${`s-${version}`}>
        <div class="st-status-info"><strong>${version} 已校验</strong><span>重启后生效</span></div>
        <button type="button" class="vk-btn is-primary" disabled=${busy} onClick=${() => restart()}>立即重启并更新</button>
      </div>`)}
      ${available.map((item) => html`<div class="st-status-row" key=${item.file}>
        <div class="st-status-info"><strong>发现新版本 ${item.version}</strong>
          <span>${item.notes || "无更新说明"} · ${item.file}（${item.sizeKb} KB，签名有效）</span></div>
        <span class="st-actions">
          <${Chip} tone="ok">可安装<//>
          <button type="button" class="vk-btn is-primary" disabled=${busy} onClick=${() => install(item.file)}>安装并重启</button>
        </span>
      </div>`)}
      ${!available.length && !staged.length && html`<p class="st-field-note">没有发现新版本。收到更新包后放在「下载」文件夹（飞书默认就是这里），回到本页即可看到；也可以直接双击更新包安装。</p>`}
    </div>
    <form class="st-actions" onSubmit=${onUpload}>
      <input type="file" accept=".vsepkg" ref=${fileInput} disabled=${busy} />
      <button type="submit" class="vk-btn" disabled=${busy}>从文件安装</button>
      <button type="button" class="vk-btn" disabled=${busy} onClick=${load}>重新检查</button>
    </form>
    ${(data.events || []).length > 0 && html`<dl class="st-kv">
      ${data.events.slice(0, 6).map((event, index) => html`<${EventRow} key=${index} event=${event} />`)}
    </dl>`}
  </section>`;
}

function EventRow({ event }) {
  const label = EVENT_LABELS[event.kind] || event.kind;
  const reason = event.reason ? `：${event.reason}` : "";
  return html`<dt>${event.at}</dt><dd>${label} ${event.version || ""}${reason}</dd>`;
}
