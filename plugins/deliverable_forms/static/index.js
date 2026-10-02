// 交付物表单总览 (module page): one card per registered form, linking to its schema page.
import { html } from "/static/host/vendor/preact-htm.js";
import { StateBlock, useStylesheet } from "/static/host/kit.js";
import { pluginApi, useResource } from "/static/host/api.js";

const SOURCE_LABELS = { aras: "Aras", tdc: "TDC" };

function formatTime(value) {
  if (!value) return "尚未采集";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("zh-CN", { hour12: false });
}

export default function FormsIndexPage({ plugin }) {
  useStylesheet(`/plugins/${plugin.id}/static/forms.css`);
  const { data: forms, error, loading, reload } = useResource(pluginApi(plugin.id).url("forms"));
  if (error || !forms) {
    return html`<${StateBlock} loading=${loading} error=${error} onRetry=${reload} />`;
  }
  return html`<div class="df-index">
    <p class="df-index-note">各表单数据来自最近一次自动归档快照；同步与归档配置在「自动归档」页。</p>
    <div class="df-index-grid">
      ${forms.map((form) => html`<a key=${form.formKey} class="df-index-card" href=${`#p/${plugin.id}/${form.page}`}>
        <span class="df-index-source">${SOURCE_LABELS[form.source] || form.source}</span>
        <strong class="df-index-title">${form.title}</strong>
        <span class="df-index-meta">${form.updatedAt ? `${form.rowCount} 条 · ${formatTime(form.updatedAt)}` : "尚未采集"}</span>
      </a>`)}
    </div>
  </div>`;
}
