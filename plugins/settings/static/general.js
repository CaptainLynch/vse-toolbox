// 系统设置 (plugin module page). Parity port of the legacy #settings-panel;
// all reads/writes go through the existing /api/settings endpoints.
import { html, useCallback, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { StateBlock, useStylesheet } from "/static/host/kit.js";
import { refreshGlobalBadges, request } from "./client.js";
import { ErrorCard } from "./error-card.js";
import { SettingsForm } from "./settings-form.js";
import { SessionsCard } from "./sessions.js";
import { ExcelServiceCard, VersionCard } from "./service-status.js";

export default function SettingsGeneralPage({ plugin }) {
  useStylesheet(`/plugins/${plugin.id}/static/settings.css`);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [seed, setSeed] = useState(0);
  const [saveSignal, setSaveSignal] = useState(0);
  const seq = useRef(0);

  // resetForm=false 只刷新会话/状态，保留表单中未保存的输入。
  const load = useCallback(async ({ resetForm = true } = {}) => {
    const current = ++seq.current;
    setLoading(true);
    try {
      const next = await request("/api/settings");
      if (current !== seq.current) return;
      setData(next || {});
      if (resetForm) setSeed((value) => value + 1);
      refreshGlobalBadges((next || {}).sessions);
    } catch (err) {
      if (current === seq.current) setError(err);
    } finally {
      if (current === seq.current) setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const reloadAll = useCallback(() => { setError(null); load(); }, [load]);
  const reloadStatus = useCallback(() => load({ resetForm: false }), [load]);

  if (!data) {
    return html`<div class="vk-page st-page">
      <header class="vk-page-header"><h2>系统设置</h2></header>
      ${error ? html`<${ErrorCard} error=${error} onReload=${reloadAll} />` : html`<${StateBlock} loading=${loading} />`}
    </div>`;
  }

  return html`<div class="vk-page st-page">
    <header class="vk-page-header">
      <div>
        <p class="st-eyebrow">本地配置</p>
        <h2>系统设置</h2>
      </div>
      <div class="vk-page-actions">
        <span class="vk-muted" aria-live="polite">${loading ? "正在读取系统设置…" : ""}</span>
        <a class="vk-btn" href="#p/settings/updates">插件更新</a>
        <button type="button" class="vk-btn" disabled=${loading} onClick=${reloadAll}>刷新设置</button>
      </div>
    </header>

    <${ErrorCard}
      error=${error}
      onReload=${reloadAll}
      onRetrySave=${error && error.fields ? () => { setError(null); setSaveSignal((v) => v + 1); } : null}
      onDismiss=${() => setError(null)}
    />

    <div class="st-layout">
      <${SettingsForm}
        settings=${data.settings || {}}
        seed=${seed}
        saveSignal=${saveSignal}
        onSaved=${() => load()}
        onError=${setError}
      />
      <div class="st-side">
        <${SessionsCard}
          sessions=${data.sessions}
          vaultConfigured=${Boolean(data.credentialVaultConfigured)}
          onChanged=${reloadStatus}
          onError=${setError}
        />
        <${ExcelServiceCard} excelService=${data.excelService} />
        <${VersionCard} />
      </div>
    </div>
  </div>`;
}
