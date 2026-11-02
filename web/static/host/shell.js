// Plugin shell: mounts the host chrome (top bar, global dialogs), reads
// /api/host/manifest for the navigation and owns every `#p/<plugin>/<page>`
// route. Hashes from before the plugin refactor are redirected through
// legacyRedirect(); anything else falls back to the first nav entry.
import { api, pluginApi } from "./api.js";
import { BOOT_FAILURE_EVENT, recoverSession, registerBootReceiver, runBootHandshake } from "./boot-exchange.js";
import { mountChrome } from "./chrome/index.js";
import { sortNav } from "./chrome/TopBar.js";
import { legacyRedirect } from "./legacy-routes.js";
import * as kit from "./kit.js";
import { SCHEMA_RENDERERS } from "./pages.js";
import { html, render, useEffect, useErrorBoundary, useState } from "./vendor/preact-htm.js";

export const DEFAULT_ROUTE = "#p/workbench/today";
export const SESSION_BANNER_ID = "vse-session-banner";
const SESSION_EXPIRED_TEXT = "本地会话已过期";
const SESSION_UNRECOVERABLE_TEXT = "本窗口无法自动恢复，请从开始菜单重新打开 VSE Toolbox";
const BOOT_RECOVERY_HINT = "可重试；若仍失败，请从开始菜单重新打开 VSE Toolbox";
const RECOVER_LABEL = "恢复会话";
const RETRY_LABEL = "重试";

const ROUTE = /^#p\/([a-z][a-z0-9_-]{1,39})\/([a-z][a-z0-9_-]{1,39})(?:\?.*)?$/;

export function parsePluginRoute(hash) {
  const match = ROUTE.exec(hash || "");
  return match ? { pluginId: match[1], pageId: match[2] } : null;
}

function ErrorFrame({ children }) {
  const [error, reset] = useErrorBoundary((err) => console.error("[plugin page]", err));
  if (error) {
    return html`<div class="vk-state is-error" role="alert">
      <span>页面渲染出错：${error.message || String(error)}</span>
      <button type="button" class="vk-btn" onClick=${reset}>重试</button>
    </div>`;
  }
  return children;
}

function SchemaPage({ plugin, page }) {
  const [state, setState] = useState({ schema: null, error: null });
  useEffect(() => {
    let alive = true;
    setState({ schema: null, error: null });
    fetch(`/plugins/${plugin.id}/static/pages/${page.id}.json`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`页面定义缺失（HTTP ${res.status}）`))))
      .then((schema) => alive && setState({ schema, error: null }))
      .catch((error) => alive && setState({ schema: null, error }));
    return () => { alive = false; };
  }, [plugin.id, page.id]);

  if (state.error) return html`<${kit.StateBlock} error=${state.error} />`;
  if (!state.schema) return html`<${kit.StateBlock} loading=${true} />`;
  const Renderer = SCHEMA_RENDERERS[state.schema.renderer || "analysis"];
  if (!Renderer) return html`<${kit.StateBlock} error=${new Error(`未知的页面渲染器：${state.schema.renderer}`)} />`;
  return html`<${Renderer} pluginId=${plugin.id} schema=${state.schema} />`;
}

function ModulePage({ plugin, page }) {
  const [state, setState] = useState({ Component: null, error: null });
  useEffect(() => {
    let alive = true;
    setState({ Component: null, error: null });
    import(`/plugins/${plugin.id}/static/${page.module}?v=${encodeURIComponent(plugin.version)}`)
      .then((mod) => alive && setState({ Component: mod.default, error: mod.default ? null : new Error("页面模块没有默认导出") }))
      .catch((error) => alive && setState({ Component: null, error }));
    return () => { alive = false; };
  }, [plugin.id, page.module, plugin.version]);

  if (state.error) return html`<${kit.StateBlock} error=${state.error} />`;
  if (!state.Component) return html`<${kit.StateBlock} loading=${true} />`;
  const Component = state.Component;
  return html`<${Component} plugin=${plugin} page=${page} api=${pluginApi(plugin.id)} kit=${kit} />`;
}

function PluginPage({ manifest, route }) {
  const plugin = manifest.plugins.find((item) => item.id === route.pluginId);
  if (!plugin) return html`<${kit.StateBlock} error=${new Error(`插件 ${route.pluginId} 不存在`)} />`;
  if (plugin.status !== "loaded") {
    return html`<${kit.StateBlock} error=${new Error(`插件 ${plugin.name || plugin.id} 未加载：${plugin.error || plugin.status}`)} />`;
  }
  const page = (plugin.pages || []).find((item) => item.id === route.pageId);
  if (!page) return html`<${kit.StateBlock} error=${new Error(`页面 ${route.pageId} 不存在`)} />`;
  const Page = page.kind === "module" ? ModulePage : SchemaPage;
  return html`<${ErrorFrame} key=${`${plugin.id}/${page.id}`}><${Page} plugin=${plugin} page=${page} /></${ErrorFrame}>`;
}

function pageTitle(manifest, route) {
  const plugin = manifest.plugins.find((item) => item.id === route.pluginId);
  const page = plugin && (plugin.pages || []).find((item) => item.id === route.pageId);
  return (page && page.title) || "插件";
}

/** Where an unroutable hash goes: its legacy target, else the first nav entry. */
export function fallbackRoute(hash, nav = []) {
  const legacy = legacyRedirect(hash);
  if (legacy) return legacy;
  const first = sortNav(nav)[0];
  return first ? `#p/${first.plugin}/${first.page}` : DEFAULT_ROUTE;
}

function syncRoute(manifest, mount) {
  // Nav active state is owned by the host TopBar (it follows the hash).
  const route = parsePluginRoute(window.location.hash);
  if (!route) {
    const target = fallbackRoute(window.location.hash, manifest.nav);
    if (target !== window.location.hash) {
      window.location.replace(target);  // fires hashchange → syncRoute again
      return;
    }
    render(null, mount);
    return;
  }
  // 新工作台页面自带标题区，隐藏外壳的通用标题，避免出现两遍。
  document.body.dataset.routePlugin = route.pluginId;
  const title = document.getElementById("session-title");
  if (title) title.textContent = pageTitle(manifest, route);
  render(html`<${PluginPage} manifest=${manifest} route=${route} />`, mount);
}

export async function startShell(mount = document.getElementById("plugin-host")) {
  const chrome = mountChrome();
  if (!mount) return null;
  let manifest;
  try {
    manifest = await api("/api/host/manifest");
  } catch (error) {
    console.warn("[plugin shell] manifest unavailable:", error.message);
    manifest = { hostApi: null, plugins: [], nav: [] };
  }
  chrome.setNav(manifest.nav || []);
  window.addEventListener("hashchange", () => syncRoute(manifest, mount));
  syncRoute(manifest, mount);
  return manifest;
}

/**
 * C7 会话恢复横幅（契约 §5.8）：写请求返回 401 SessionRequired 时显示
 * “本地会话已过期” + “恢复会话”按钮；窗口标记失效时文案切换为“请从开始菜单重新打开”。
 * DSH-V2-04：启动握手失败（票据无效/超时/网络失败）时显示失败原因 + “重试”，
 * 重试仍不可恢复则给出“从开始菜单重新打开”的明确指引，绝不把失败伪装成成功。
 * 幂等：同一文档只挂一个横幅；返回元素引用供测试驱动。
 */
export function mountSessionRecoveryBanner(win = window, doc = document) {
  if (!win || !doc || typeof doc.createElement !== "function") return null;
  if (typeof doc.getElementById === "function" && doc.getElementById(SESSION_BANNER_ID)) return null;
  const banner = doc.createElement("div");
  banner.id = SESSION_BANNER_ID;
  banner.setAttribute("role", "alert");
  banner.hidden = true;
  // 内联 display 会盖过 UA 的 [hidden] 规则：显式用 display 同步 hidden，
  // 否则横幅会在每个正常页面上假报“本地会话已过期”。
  banner.style.cssText =
    "position:fixed;top:0;left:0;right:0;z-index:9999;display:none;gap:12px;" +
    "align-items:center;justify-content:center;padding:8px 16px;" +
    "background:#8a2c2c;color:#fff;font-size:14px;";
  const text = doc.createElement("span");
  text.textContent = SESSION_EXPIRED_TEXT;
  const hint = doc.createElement("span");
  hint.textContent = BOOT_RECOVERY_HINT;
  hint.style.cssText = "opacity:.85;font-size:13px;";
  const button = doc.createElement("button");
  button.type = "button";
  button.className = "vk-btn";
  button.textContent = RECOVER_LABEL;
  let mode = "session";
  const hide = () => {
    banner.hidden = true;
    banner.style.display = "none";
  };
  const showUnrecoverable = () => {
    text.textContent = SESSION_UNRECOVERABLE_TEXT;
    // 已无重试入口：撤掉“可重试”的通用提示，避免与真实状态自相矛盾。
    hint.hidden = true;
    button.hidden = true;
  };
  const recover = async () => {
    try {
      await recoverSession();
      hide();
      text.textContent = SESSION_EXPIRED_TEXT;
    } catch (error) {
      if (error && (error.status === 401 || error.type === "SessionRecoveryUnavailable")) {
        showUnrecoverable();
      }
    }
  };
  const retry = async () => {
    try {
      if (await runBootHandshake(win)) {
        hide();
        text.textContent = SESSION_EXPIRED_TEXT;
        return;
      }
    } catch (_) {
      // 握手自身已兜底；继续尝试会话恢复。
    }
    await recover();
  };
  button.addEventListener("click", () => (mode === "boot" ? retry() : recover()));
  banner.appendChild(text);
  banner.appendChild(hint);
  banner.appendChild(button);
  const host = doc.body || doc.documentElement;
  if (host && typeof host.appendChild === "function") host.appendChild(banner);
  const show = () => {
    mode = "session";
    banner.hidden = false;
    banner.style.display = "flex";
    text.textContent = SESSION_EXPIRED_TEXT;
    hint.hidden = false;
    button.textContent = RECOVER_LABEL;
    button.hidden = false;
  };
  const showBootFailure = (detail) => {
    const message = detail && detail.error && detail.error.message;
    mode = "boot";
    banner.hidden = false;
    banner.style.display = "flex";
    text.textContent = message || "启动票据交换失败";
    hint.hidden = false;
    button.textContent = RETRY_LABEL;
    button.hidden = false;
  };
  if (typeof win.addEventListener === "function") {
    win.addEventListener("vse:session-expired", show);
    win.addEventListener(BOOT_FAILURE_EVENT, (event) => showBootFailure(event && event.detail));
  }
  return { banner, text, hint, button, show, showBootFailure };
}

if (typeof document !== "undefined") {
  // C7（DSH-V2-03）：先**同步**注册宿主注入接收器（pywebview 随时可能推票据），再立即
  // 渲染外壳；握手（K2 桥 / K3 boot-claim / 旧 ?boot= 兼容）在后台完成，绝不阻塞首屏。
  // DSH-V2-04：握手失败经 `vse:boot-failed` 走横幅（重试 / 从开始菜单重新打开）。
  registerBootReceiver(window);
  mountSessionRecoveryBanner(window, document);
  runBootHandshake(window);
  startShell();
}
