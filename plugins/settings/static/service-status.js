// Read-only service, autostart, and version status cards.
import { html, useCallback, useEffect, useState } from "/static/host/vendor/preact-htm.js";
import { useResource } from "/static/host/api.js";
import { expertStore } from "/static/host/expert.js";
import { request } from "./client.js";
import { Chip } from "./sessions.js";

export function AutostartCard({ seed = 0, onError }) {
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");

  const load = useCallback(async () => {
    try {
      const data = await request("/api/p/settings/autostart");
      setEnabled(Boolean(data && data.enabled));
    } catch (_err) {
      // 无法获取状态时保持默认关闭
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, seed]);

  const onToggle = async (next) => {
    if (busy) return;
    setBusy(true);
    setStatus("正在保存…");
    try {
      const data = await request("/api/p/settings/autostart", {
        method: "POST",
        body: { enabled: next },
      });
      setEnabled(Boolean(data && data.enabled));
      setStatus(next ? "已开启开机自启" : "已关闭开机自启");
    } catch (err) {
      setStatus("");
      if (onError) onError(err);
    } finally {
      setBusy(false);
    }
  };

  return html`<section class="st-card">
    <header class="st-card-head">
      <p class="st-eyebrow">系统启动</p>
      <h3>开机自启</h3>
    </header>
    <label class="st-check">
      <input
        type="checkbox"
        checked=${enabled}
        disabled=${loading || busy}
        onChange=${(e) => onToggle(e.currentTarget.checked)}
      />
      <span>开机自动启动 VSE 工具箱</span>
    </label>
    <p class="st-field-note" style="margin:6px 0 0">只影响当前 Windows 账号。</p>
    ${status && html`<span class="st-status" style="margin-top:6px" aria-live="polite">${status}</span>`}
  </section>`;
}

export function ExcelServiceCard({ excelService }) {
  const configured = Boolean(excelService && excelService.configured);
  // 服务内部名称只对排查有用；日常模式下这张卡片不显示（Excel 是否可用在「工具 → Excel」里会说明）。
  if (!expertStore.get()) return null;
  return html`<section class="st-card">
    <header class="st-card-head">
      <p class="st-eyebrow">服务状态</p>
      <h3>Excel 文件处理服务</h3>
    </header>
    <div class="st-status-list">
      <div class="st-status-row">
        <div class="st-status-info"><strong>Excel 服务配置</strong><span>检查 ExcelTaskAdminService</span></div>
        <${Chip} tone=${configured ? "ok" : "idle"}>${configured ? "已就绪" : "未配置"}<//>
      </div>
    </div>
  </section>`;
}

const CHANNEL_LABELS = { source: "源码运行", "standalone-exe": "独立运行包" };

export function VersionCard() {
  const res = useResource("/api/version");
  const data = res.data || {};
  return html`<section class="st-card">
    <header class="st-card-head">
      <p class="st-eyebrow">运行环境</p>
      <h3>版本信息</h3>
    </header>
    ${res.error
      ? html`<p class="st-field-error">无法读取版本信息：${res.error.message}</p>`
      : html`<dl class="st-kv">
          <dt>应用版本</dt><dd>${res.loading && !res.data ? "读取中…" : (data.displayVersion || "开发工作区")}</dd>
          ${expertStore.get() && html`
            <dt>运行渠道</dt><dd>${data.channel ? `${CHANNEL_LABELS[data.channel] || data.channel}（${data.channel}）` : "-"}</dd>
            <dt>构建标识</dt><dd>${data.buildId || "无独立构建标识"}</dd>
            <dt>详情</dt><dd>${data.detail || "-"}</dd>`}
        </dl>
        <p class="st-field-note"><a href="#p/settings/updates">程序与插件更新 ›</a></p>`}
  </section>`;
}
