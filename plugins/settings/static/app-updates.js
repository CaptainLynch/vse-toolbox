// 程序更新卡片（v2 启动器）：当前/上一/试用版本、待生效版本、下载文件夹里发现的新版本、
// 更新记录与回退。记录只用既有 API 字段；时间统一按北京时间显示（宿主 time-format.js），
// 说明按纯文本渲染（不解析 HTML）。不由 v2 启动器运行时只显示说明，隐藏全部写操作。
import { html, useCallback, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { formatBeijingWithZone, interpretNaiveTime } from "/static/host/time-format.js";
import { request, SettingsError } from "./client.js";
import { Chip } from "./sessions.js";

const BASE = "/api/p/settings/app-updates";

// 六个状态互斥：同一版本只取一个状态，按 buildRecords 里的优先级判定。
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
  [STATE.trial]: "warn",
  [STATE.staged]: "warn",
  [STATE.failed]: "warn",
  [STATE.rolledBack]: "idle",
  [STATE.notInstalled]: "idle",
};

/**
 * 启动器记录的事件时间是本地无时区文本（vse_boot.state._now()），按来源 local 解释后
 * 显示北京时间；缺失或无法解析一律「未记录」，不猜、不补 Z。
 */
function beijingTime(value) {
  const text = String(value || "").trim();
  if (!text) return "未记录";
  try {
    return formatBeijingWithZone(interpretNaiveTime(text, "local").epochMs);
  } catch (_err) {
    try {
      return formatBeijingWithZone(text);
    } catch (_err2) {
      return "未记录";
    }
  }
}

/**
 * 用既有 GET /api/p/settings/app-updates 字段生成互斥的更新记录。
 *
 * 优先级：当前生效 > 试用中 > 已导入待生效 > 失败 > 已回退 > 未安装。
 * 版本、时间、说明全部来自 API：`events[].version/fromVersion/at/notes/reason`、
 * `available[].version/notes/file/sizeKb`、`current/previous/trial/staged/installed`。
 */
function buildRecords(data) {
  const events = Array.isArray(data.events) ? data.events : [];
  const staged = Array.isArray(data.staged) ? data.staged : [];
  const available = Array.isArray(data.available) ? data.available : [];
  const installed = Array.isArray(data.installed) ? data.installed : [];
  const records = new Map();

  const related = (version) =>
    events.filter((event) => event && (event.version === version || event.fromVersion === version));

  const add = (version, state, extra = {}) => {
    const key = String(version || "").trim();
    // installFailed 事件的 version 是暂存目录名（app-2.0.5）：按去掉 app- 前缀去重，
    // 避免同一个版本同时显示「失败」和「未安装」；展示仍用 API 原值。
    const match = key.replace(/^app-/, "");
    if (!key || records.has(match)) return;
    const matches = related(key);
    const newest = matches[0] || null;
    const withNotes = matches.find((event) => event && event.notes);
    records.set(match, {
      version: key,
      state,
      at: extra.at !== undefined ? extra.at : (newest && newest.at) || "",
      notes: extra.notes !== undefined ? extra.notes : (withNotes && withNotes.notes) || "",
      reason: extra.reason !== undefined ? extra.reason : (newest && newest.reason) || "",
      detail: extra.detail || "",
      file: extra.file || "",
      install: Boolean(extra.install),
      restart: Boolean(extra.restart),
      rollback: Boolean(extra.rollback),
    });
  };

  if (data.current) {
    add(data.current, STATE.current, {
      rollback: Boolean(data.previous),
      detail: data.previous ? `上一版本 ${data.previous}（可回退）` : "没有可回退的上一版本",
    });
  }
  if (data.trial) add(data.trial, STATE.trial, { detail: "试用版本，启动正常后转为当前生效" });
  staged.forEach((version) => add(version, STATE.staged, { restart: true, detail: "重启 VSE Toolbox 后生效" }));

  // 失败优先于已回退（与上方优先级注释一致）。失败的包若仍在下载文件夹，保留「安装」入口以便重试。
  events.forEach((event) => {
    if (!event) return;
    if (event.kind === "installFailed" || event.kind === "bootFailed") {
      const bare = String(event.version || "").trim().replace(/^app-/, "");
      const pkg = available.find((item) => item && item.version === bare && item.file);
      add(pkg ? pkg.version : event.version, STATE.failed, {
        at: event.at, reason: event.reason || "",
        file: pkg ? pkg.file : "", install: Boolean(pkg),
      });
    }
  });
  events.forEach((event) => {
    if (!event) return;
    if (event.kind === "rolledBack" && event.version) {
      add(event.version, STATE.rolledBack, { at: event.at, reason: event.reason || "" });
    }
    if (event.kind === "manualRollback" && event.fromVersion) {
      add(event.fromVersion, STATE.rolledBack, { at: event.at, reason: event.reason || "" });
    }
  });
  available.forEach((item) => {
    if (!item || !item.version || installed.includes(item.version)) return;
    const size = item.sizeKb === undefined || item.sizeKb === null ? "" : `，${item.sizeKb} KB`;
    add(item.version, STATE.notInstalled, {
      at: "",
      notes: item.notes || "",
      file: item.file || "",
      install: Boolean(item.file),
      detail: item.file ? `${item.file}${size}，签名有效` : "",
    });
  });
  return Array.from(records.values());
}

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
      setNotice(null);
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
    if (!window.confirm(`确定回到上一版本 ${data.previous} 吗？程序会立即重启；本次回退会记入更新记录。`)) return;
    run(async () => {
      const result = await request(`${BASE}/rollback`, { method: "POST" });
      setNotice({ tone: "ok", text: result.message });
      await waitForRestart(setNotice, data && data.current);
    });
  };

  if (!data) {
    return html`<section class="st-card">
      <header class="st-card-head">
        <p class="st-eyebrow">程序</p>
        <h3>程序更新</h3>
      </header>
      ${notice && html`<p class=${`st-status is-${notice.tone === "ok" ? "ok" : "error"}`} role="status">${notice.text}</p>`}
      <p class="st-field-note">${notice ? "读取更新状态失败，请稍后重试。" : "正在读取程序更新状态…"}</p>
    </section>`;
  }

  if (!data.managed) {
    return html`<section class="st-card" data-managed="false">
      <header class="st-card-head">
        <p class="st-eyebrow">程序</p>
        <h3>程序更新</h3>
      </header>
      <p class="st-field-note">当前不是通过启动器运行，无法在这里安装、重启或回退程序更新。请从 VSE Toolbox 启动器打开本程序。</p>
    </section>`;
  }

  const records = buildRecords(data);

  return html`<section class="st-card" data-managed="true">
    <header class="st-card-head">
      <p class="st-eyebrow">程序</p>
      <h3>程序更新</h3>
    </header>
    ${notice && html`<p class=${`st-status is-${notice.tone === "ok" ? "ok" : "error"}`} role="status">${notice.text}</p>`}
    <div class="st-status-list">
      ${records.length === 0
        ? html`<p class="st-field-note">没有更新记录。</p>`
        : records.map((record) => html`<div class="st-status-row" key=${record.version} data-version=${record.version} data-state=${record.state}>
            <div class="st-status-info">
              <strong>版本 ${record.version}</strong>
              <span>${beijingTime(record.at)} · 说明：${record.notes || "未记录"}${record.reason ? ` · 原因：${record.reason}` : ""}${record.detail ? ` · ${record.detail}` : ""}</span>
            </div>
            <span class="st-actions">
              <${Chip} tone=${STATE_TONES[record.state] || "idle"}>${record.state}<//>
              ${record.install && html`<button type="button" class="vk-btn is-primary" disabled=${busy} onClick=${() => install(record.file)}>安装并重启</button>`}
              ${record.restart && html`<button type="button" class="vk-btn is-primary" disabled=${busy} onClick=${() => restart()}>立即重启并更新</button>`}
              ${record.rollback && html`<button type="button" class="vk-btn" disabled=${busy} onClick=${rollback}>回到上一版本</button>`}
            </span>
          </div>`)}
    </div>
    <p class="st-field-note">更新记录的时间均为北京时间 (Asia/Shanghai)；说明来自更新包或启动器记录，缺失时显示「未记录」。收到更新包后放在「下载」文件夹（飞书默认就是这里），回到本页即可看到；也可以直接双击更新包安装。</p>
    <form class="st-actions" onSubmit=${onUpload}>
      <input type="file" accept=".vsepkg" ref=${fileInput} disabled=${busy} />
      <button type="submit" class="vk-btn" disabled=${busy}>从文件安装</button>
      <button type="button" class="vk-btn" disabled=${busy} onClick=${load}>重新检查</button>
    </form>
  </section>`;
}
