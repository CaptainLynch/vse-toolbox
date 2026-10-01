// 插件更新 (module page): import a signed .vsepkg, see what is pending, active
// and what happened recently; discard or roll back. Nothing takes effect until
// VSE Toolbox restarts, and nothing here restarts it.
import { html, useCallback, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { StateBlock, useStylesheet } from "/static/host/kit.js";
import { request, SettingsError } from "./client.js";
import { Chip } from "./sessions.js";

const EVENT_LABELS = {
  staged: "已导入，待重启",
  discarded: "已撤销导入",
  activated: "已生效",
  rolled_back: "已回滚",
};
const SOURCE_LABELS = { bundled: "随包内置", installed: "插件包安装" };

function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { hour12: false });
}

async function uploadPackage(file) {
  const form = new FormData();
  form.append("file", file, file.name);
  let response;
  try {
    response = await fetch("/api/host/updates/import", { method: "POST", body: form, cache: "no-store" });
  } catch (_err) {
    throw new SettingsError("无法连接本地服务，请确认 VSE Toolbox 仍在运行");
  }
  let payload = null;
  try {
    payload = await response.json();
  } catch (_err) {
    payload = null;
  }
  if (response.ok && payload && payload.ok === true) return payload.data;
  const error = (payload && payload.error) || {};
  const fallback = response.status === 403 ? "该操作只允许在本机浏览器中执行" : `导入失败（HTTP ${response.status}）`;
  throw new SettingsError(error.message || fallback, { status: response.status, type: error.type || "http" });
}

function eventText(event) {
  const label = EVENT_LABELS[event.kind] || event.kind;
  const parts = [label];
  if (event.version) parts.push(event.version);
  if (event.kind === "rolled_back") parts.push(`→ ${event.to === "bundled" ? "随包内置版本" : event.to}`);
  if (event.reason) parts.push(`原因：${event.reason}`);
  return parts.join("  ");
}

export default function PluginUpdatesPage({ plugin }) {
  useStylesheet(`/plugins/${plugin.id}/static/settings.css`);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef(null);

  const load = useCallback(async () => {
    try {
      setData(await request("/api/host/updates"));
      setError(null);
    } catch (err) {
      setError(err);
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
    } finally {
      setBusy(false);
    }
  };

  const onImport = (event) => {
    event.preventDefault();
    const file = fileInput.current && fileInput.current.files && fileInput.current.files[0];
    if (!file) {
      setNotice({ tone: "error", text: "请先选择 .vsepkg 插件包" });
      return;
    }
    run(async () => {
      const result = await uploadPackage(file);
      setData(result.updates);
      fileInput.current.value = "";
      const from = result.previous ? `（当前 ${result.previous}）` : "";
      setNotice({ tone: "ok", text: `${result.id} ${result.version}${from}：${result.message}` });
    });
  };

  const discard = (id) => run(async () => {
    setData(await request(`/api/host/updates/${encodeURIComponent(id)}/discard`, { method: "POST" }));
    setNotice({ tone: "ok", text: `已撤销 ${id} 的待生效插件包` });
  });

  const rollback = (id) => {
    if (!window.confirm(`确定把 ${id} 切回上一版本吗？重启后生效。`)) return;
    run(async () => {
      const result = await request(`/api/host/updates/${encodeURIComponent(id)}/rollback`, { method: "POST" });
      setData(result);
      setNotice({ tone: "ok", text: result.message });
    });
  };

  if (!data) {
    return html`<div class="vk-page st-page"><${StateBlock} loading=${!error} error=${error} onRetry=${load} /></div>`;
  }

  const pending = data.pending || [];
  const active = data.active || {};
  const noKeys = !(data.trustedKeys || []).length;

  return html`<div class="vk-page st-page">
    <header class="vk-page-header">
      <div>
        <p class="st-eyebrow">插件包</p>
        <h2>插件更新</h2>
      </div>
      <div class="vk-page-actions">
        <button type="button" class="vk-btn" disabled=${busy} onClick=${load}>刷新</button>
      </div>
    </header>

    ${notice && html`<p class=${`st-status is-${notice.tone === "ok" ? "ok" : "error"}`} role="status">${notice.text}</p>`}

    <div class="st-layout">
      <div class="st-side">
        <section class="st-card">
          <header class="st-card-head">
            <p class="st-eyebrow">导入</p>
            <h3>导入插件包</h3>
          </header>
          <p class="st-field-note">选择从飞书收到的 .vsepkg 文件。导入时会校验签名和文件完整性，校验通过后在下次重启 VSE Toolbox 时生效，不会打断正在进行的工作。</p>
          ${noKeys && html`<p class="st-field-error">本程序未配置可信公钥，暂时无法导入插件包。</p>`}
          <form class="st-actions" onSubmit=${onImport}>
            <input type="file" accept=".vsepkg" ref=${fileInput} disabled=${busy || noKeys} />
            <button type="submit" class="vk-btn is-primary" disabled=${busy || noKeys}>校验并导入</button>
          </form>
        </section>

        <section class="st-card">
          <header class="st-card-head">
            <p class="st-eyebrow">待生效</p>
            <h3>重启后生效</h3>
          </header>
          ${pending.length === 0
            ? html`<p class="st-field-note">没有待生效的插件包。</p>`
            : html`<div class="st-status-list">
                ${pending.map((item) => html`<div class="st-status-row" key=${`${item.id}@${item.version}`}>
                  <div class="st-status-info"><strong>${item.id}</strong><span>版本 ${item.version}，重启 VSE Toolbox 后生效</span></div>
                  <button type="button" class="vk-btn" disabled=${busy} onClick=${() => discard(item.id)}>撤销</button>
                </div>`)}
              </div>`}
        </section>
      </div>

      <div class="st-side">
        <section class="st-card">
          <header class="st-card-head">
            <p class="st-eyebrow">当前</p>
            <h3>已加载的插件</h3>
          </header>
          <div class="st-status-list">
            ${(data.plugins || []).map((item) => {
              const installed = active[item.id];
              return html`<div class="st-status-row" key=${item.id || item.name}>
                <div class="st-status-info">
                  <strong>${item.name}</strong>
                  <span>${item.id} · ${item.version || "-"} · ${SOURCE_LABELS[item.source] || item.source}${installed && installed.previous ? ` · 上一版本 ${installed.previous}` : ""}</span>
                </div>
                <span class="st-actions">
                  <${Chip} tone=${item.status === "loaded" ? "ok" : "warn"}>${item.status === "loaded" ? "运行中" : "加载失败"}<//>
                  ${installed && html`<button type="button" class="vk-btn" disabled=${busy} onClick=${() => rollback(item.id)}>回滚</button>`}
                </span>
              </div>`;
            })}
          </div>
        </section>

        <section class="st-card">
          <header class="st-card-head">
            <p class="st-eyebrow">记录</p>
            <h3>最近操作</h3>
          </header>
          ${(data.events || []).length === 0
            ? html`<p class="st-field-note">暂无记录。</p>`
            : html`<dl class="st-kv">
                ${data.events.map((event, index) => html`<${Fragmentish} key=${index} event=${event} />`)}
              </dl>`}
        </section>
      </div>
    </div>
  </div>`;
}

function Fragmentish({ event }) {
  return html`<dt>${formatTime(event.at)}</dt><dd>${event.plugin}：${eventText(event)}</dd>`;
}
