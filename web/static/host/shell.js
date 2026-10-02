// Plugin shell: mounts the host chrome (top bar, global dialogs), reads
// /api/host/manifest for the navigation and owns every `#p/<plugin>/<page>`
// route. Hashes from before the plugin refactor are redirected through
// legacyRedirect(); anything else falls back to the first nav entry.
import { api, pluginApi } from "./api.js";
import { mountChrome } from "./chrome/index.js";
import { sortNav } from "./chrome/TopBar.js";
import { legacyRedirect } from "./legacy-routes.js";
import * as kit from "./kit.js";
import { SCHEMA_RENDERERS } from "./pages.js";
import { html, render, useEffect, useErrorBoundary, useState } from "./vendor/preact-htm.js";

export const DEFAULT_ROUTE = "#p/project-overview/status";

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

if (typeof document !== "undefined") startShell();
