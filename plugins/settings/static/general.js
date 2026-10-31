// 系统设置 (plugin module page). Parity port of the legacy #settings-panel;
// all reads/writes go through the existing /api/settings endpoints.
import { html, useCallback, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { useStylesheet } from "/static/host/kit.js";
import { ErrorCard, Skeleton, TONE } from "/static/host/ui-kit.js";
import { isAuthError, legacyGlobal, refreshGlobalBadges, request } from "./client.js";
import { SettingsForm } from "./settings-form.js";
import { SessionsCard } from "./sessions.js";
import { AutostartCard, ExcelServiceCard, VersionCard } from "./service-status.js";

export const SETTINGS_TONE = {
  ok: TONE.ok,
  warn: TONE.warn,
  bad: TONE.bad,
  off: TONE.off,
};

export function formatErrorWhat(error) {
  if (!error) return "";
  const auth = isAuthError(error);
  if (auth) return "企业认证会话已失效";
  return error.summary || error.message || "系统设置操作未成功";
}

export function formatErrorTodo(error) {
  if (!error) return "";
  const auth = isAuthError(error);
  if (auth) {
    const openLogin = legacyGlobal("openInPlaceLogin");
    return openLogin
      ? "本地系统设置未受影响，但企业会话需要重新验证。请点击【重新登录】。"
      : "本地系统设置未受影响，但企业会话需要重新验证。请在下方「统一域账号登录」中重新登录。";
  }
  return error.impact || "表单中已输入的内容已完整保留，未覆盖未修改的配置项。";
}

export function errorFixAction(error, reloadAll, retrySave) {
  if (!error) return null;
  const auth = isAuthError(error);
  const openLogin = legacyGlobal("openInPlaceLogin");
  if (auth && openLogin) {
    return {
      label: "重新登录",
      onClick: () => openLogin({
        notice: "企业会话已失效，请重新登录企业域账号。",
        onLoginSuccess: () => reloadAll && reloadAll(),
      }),
    };
  }
  if (retrySave) {
    return { label: "重试保存", onClick: retrySave };
  }
  if (reloadAll) {
    return { label: "重新加载", onClick: reloadAll };
  }
  return null;
}

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
      ${error
        ? html`<${ErrorCard}
            what=${formatErrorWhat(error)}
            todo=${formatErrorTodo(error)}
            onFix=${errorFixAction(error, reloadAll, null)}
          />`
        : html`<${Skeleton} rows=${6} />`}
    </div>`;
  }

  return html`<div class="vk-page st-page">
    <header class="vk-page-header">
      <div>
        <h2>设置</h2>
        <p class="vk-muted" style="margin:4px 0 0">大部分情况下不需要改这里。</p>
      </div>
      <div class="vk-page-actions">
        <span class="vk-muted" aria-live="polite">${loading ? "正在读取系统设置…" : ""}</span>
        <a class="vk-btn" href="#p/settings/updates">程序与插件更新</a>
        <button type="button" class="vk-btn" disabled=${loading} onClick=${reloadAll}>刷新</button>
      </div>
    </header>

    ${error && html`<${ErrorCard}
      what=${formatErrorWhat(error)}
      todo=${formatErrorTodo(error)}
      onFix=${errorFixAction(error, reloadAll, error && error.fields ? () => { setError(null); setSaveSignal((v) => v + 1); } : null)}
    />`}

    ${loading && html`<div style="margin-bottom:12px"><${Skeleton} rows=${2} /></div>`}

    <div class="st-layout">
      <${SettingsForm}
        settings=${data.settings || {}}
        seed=${seed}
        saveSignal=${saveSignal}
        onSaved=${() => load()}
        onError=${setError}
      />
      <div class="st-side">
        <${AutostartCard} seed=${seed} onError=${setError} />
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
