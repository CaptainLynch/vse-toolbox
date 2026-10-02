// Read-only service and version status cards.
import { html } from "/static/host/vendor/preact-htm.js";
import { useResource } from "/static/host/api.js";
import { Chip } from "./sessions.js";

export function ExcelServiceCard({ excelService }) {
  const configured = Boolean(excelService && excelService.configured);
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
          <dt>运行渠道</dt><dd>${data.channel ? `${CHANNEL_LABELS[data.channel] || data.channel}（${data.channel}）` : "-"}</dd>
          <dt>构建标识</dt><dd>${data.buildId || "无独立构建标识"}</dd>
          <dt>详情</dt><dd>${data.detail || "-"}</dd>
        </dl>`}
  </section>`;
}
