// 插件更新 (module page): import a signed .vsepkg, see what is pending, active and
// what happened recently; discard or roll back. Nothing takes effect until
// VSE Toolbox restarts, and nothing here restarts it.
// 更新记录只用既有 GET /api/host/updates 字段：版本、北京时间（宿主 time-format.js）、
// 纯文本说明、可回退项的回退入口；同一版本只显示一个状态。
import { html, useCallback, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { StateBlock, useStylesheet } from "/static/host/kit.js";
import { formatBeijingWithZone } from "/static/host/time-format.js";
import { request, SettingsError } from "./client.js";
import { Chip } from "./sessions.js";
import { AppUpdatesCard } from "./app-updates.js";

// 六个状态互斥：同一插件同一版本只取一个状态，按 buildRecords 里的优先级判定。
const STATE = {
  notInstalled: "未安装",
  staged: "已导入待生效（需重启）",
  current: "当前生效",
  trial: "试用中",
  rolledBack: "已回退",
  failed: "失败",
};

const STATE_TONES = {
  [STATE.current]: "ok",
  [STATE.staged]: "warn",
  [STATE.failed]: "warn",
  [STATE.rolledBack]: "idle",
  [STATE.notInstalled]: "idle",
};

const SOURCE_LABELS = { bundled: "随包内置", installed: "插件包安装" };

/** 插件事件时间是 UTC（host.updates._utc_now() 带 Z），直接显示北京时间。 */
function beijingTime(value) {
  const text = String(value || "").trim();
  if (!text) return "未记录";
  try {
    return formatBeijingWithZone(text);
  } catch (_err) {
    return "未记录";
  }
}

/**
 * 用既有 GET /api/host/updates 字段生成互斥的更新记录。
 *
 * 优先级：当前生效 > 已导入待生效 > 失败 > 已回退 > 未安装。
 * 字段来源：`active[id].version/previous`、`pending[].id/version`、
 * `plugins[].status/version/source`、`events[].kind/plugin/version/at/reason/to`。
 * 插件事件没有 notes 字段，记录里显示「未记录」，不编造说明。
 */
function buildRecords(data) {
  const active = data.active || {};
  const pending = Array.isArray(data.pending) ? data.pending : [];
  const plugins = Array.isArray(data.plugins) ? data.plugins : [];
  const events = Array.isArray(data.events) ? data.events : [];
  const records = new Map();
  const names = new Map(plugins.map((plugin) => [plugin.id, plugin.name || plugin.id]));

  const add = (id, version, state, extra = {}) => {
    const pluginId = String(id || "").trim();
    if (!pluginId) return;
    const versionText = String(version || "").trim();
    const key = `${pluginId}@${versionText || "?"}`;
    if (records.has(key)) return;
    const event = events.find((item) => item && item.plugin === pluginId && (!versionText || item.version === versionText)) || null;
    records.set(key, {
      id: pluginId,
      name: names.get(pluginId) || pluginId,
      version: versionText || "未记录",
      state,
      at: extra.at !== undefined ? extra.at : (event && event.at) || "",
      notes: extra.notes !== undefined ? extra.notes : (event && event.notes) || "",
      reason: extra.reason !== undefined ? extra.reason : (event && event.reason) || "",
      detail: extra.detail || "",
      discard: Boolean(extra.discard),
      rollback: Boolean(extra.rollback),
    });
  };

  Object.entries(active).forEach(([id, entry]) => {
    if (!entry || !entry.version) return;
    add(id, entry.version, STATE.current, {
      // 已安装项都能回退：有上一版本回上一版本，没有则回到随包内置版本。
      rollback: true,
      detail: entry.previous ? `上一版本 ${entry.previous}（可回退）` : "可回退到随包内置版本",
    });
  });

  pending.forEach((item) => {
    if (!item || !item.id) return;
    add(item.id, item.version, STATE.staged, { discard: true, detail: "重启 VSE Toolbox 后生效" });
  });

  plugins.forEach((plugin) => {
    if (!plugin || plugin.status === "loaded") return;
    // 加载失败的记录可能没有版本号：不要借用同一插件其它版本的事件时间/说明。
    const known = Boolean(plugin.version);
    add(plugin.id, plugin.version, STATE.failed, {
      at: known ? undefined : "",
      notes: known ? undefined : "",
      detail: "插件加载失败，已保留随包或上一版本",
    });
  });

  events.forEach((event) => {
    if (!event) return;
    if (event.kind === "rolled_back" && event.version) {
      add(event.plugin, event.version, STATE.rolledBack, { at: event.at, reason: event.reason || "" });
    }
    if (event.kind === "superseded" && event.version) {
      const to = event.to ? `随包版本 ${event.to}` : "随包版本";
      add(event.plugin, event.version, STATE.rolledBack, { at: event.at, reason: `程序升级后改用${to}` });
    }
    if (event.kind === "discarded") {
      add(event.plugin, event.version, STATE.notInstalled, { at: event.at, detail: "已撤销导入，未安装" });
    }
  });

  return Array.from(records.values());
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

  const discard = (id) => {
    if (!window.confirm(`确定撤销 ${id} 的待生效插件包吗？撤销后需要重新导入。`)) return;
    run(async () => {
      setData(await request(`/api/host/updates/${encodeURIComponent(id)}/discard`, { method: "POST" }));
      setNotice({ tone: "ok", text: `已撤销 ${id} 的待生效插件包` });
    });
  };

  const rollback = (id) => {
    if (!window.confirm(`确定把 ${id} 切回上一版本吗？重启后生效，更新记录会保留。`)) return;
    run(async () => {
      const result = await request(`/api/host/updates/${encodeURIComponent(id)}/rollback`, { method: "POST" });
      setData(result);
      setNotice({ tone: "ok", text: result.message || "已切回上一版本，重启后生效" });
    });
  };

  if (!data) {
    return html`<div class="vk-page st-page"><${StateBlock} loading=${!error} error=${error} onRetry=${load} /></div>`;
  }

  const active = data.active || {};
  const noKeys = !(data.trustedKeys || []).length;
  const records = buildRecords(data);

  return html`<div class="vk-page st-page">
    <header class="vk-page-header">
      <div>
        <p class="st-eyebrow">插件包</p>
        <h2>程序与插件更新</h2>
      </div>
      <div class="vk-page-actions">
        <button type="button" class="vk-btn" disabled=${busy} onClick=${load}>刷新</button>
      </div>
    </header>

    ${notice && html`<p class=${`st-status is-${notice.tone === "ok" ? "ok" : "error"}`} role="status">${notice.text}</p>`}

    <${AppUpdatesCard} />

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
                  <span>${item.id} · ${item.version || "-"} · ${item.source ? (SOURCE_LABELS[item.source] || item.source) : "未记录"}${installed && installed.previous ? ` · 上一版本 ${installed.previous}` : ""}</span>
                </div>
                <span class="st-actions">
                  <${Chip} tone=${item.status === "loaded" ? "ok" : "warn"}>${item.status === "loaded" ? "当前生效" : "失败"}<//>
                </span>
              </div>`;
            })}
          </div>
        </section>

        <section class="st-card">
          <header class="st-card-head">
            <p class="st-eyebrow">记录</p>
            <h3>更新记录</h3>
          </header>
          <p class="st-field-note">时间均为北京时间 (Asia/Shanghai)；说明来自更新包或启动器记录，缺失时显示「未记录」。</p>
          ${records.length === 0
            ? html`<p class="st-field-note">暂无记录。</p>`
            : html`<div class="st-status-list">
                ${records.map((record) => html`<div class="st-status-row" key=${`${record.id}@${record.version}`} data-plugin=${record.id} data-version=${record.version} data-state=${record.state}>
                  <div class="st-status-info">
                    <strong>${record.name} · ${record.version}</strong>
                    <span>${beijingTime(record.at)} · 说明：${record.notes || "未记录"}${record.reason ? ` · 原因：${record.reason}` : ""}${record.detail ? ` · ${record.detail}` : ""}</span>
                  </div>
                  <span class="st-actions">
                    <${Chip} tone=${STATE_TONES[record.state] || "idle"}>${record.state}<//>
                    ${record.discard && html`<button type="button" class="vk-btn" disabled=${busy} onClick=${() => discard(record.id)}>撤销</button>`}
                    ${record.rollback && html`<button type="button" class="vk-btn" disabled=${busy} onClick=${() => rollback(record.id)}>回滚</button>`}
                  </span>
                </div>`)}
              </div>`}
        </section>
      </div>
    </div>
  </div>`;
}
