// Application top bar: brand + version chip, workspace navigation generated
// from the plugin manifest (plus the shell's LEGACY_NAV while legacy panels
// remain), session badges, task center button and theme toggle.
import { html, useEffect, useState } from "../vendor/preact-htm.js";
import { createStore } from "../session.js";
import { SessionBadges, useStore } from "./SessionBadges.js";
import { TaskCenterButton } from "./TaskCenter.js";
import { ThemeToggle } from "./ThemeToggle.js";
import { VersionChip } from "./VersionDialog.js";

const PLUGIN_ROUTE = /^#p\/([a-z][a-z0-9_-]{1,39})\/([a-z][a-z0-9_-]{1,39})(?:\?.*)?$/;

/** Manifest nav entries ({plugin, page, title, order}) sorted by order, stable. */
export function sortNav(entries) {
  return (entries || [])
    .map((entry, index) => ({ entry, index }))
    .sort((a, b) => ((a.entry.order ?? 100) - (b.entry.order ?? 100)) || a.index - b.index)
    .map(({ entry }) => entry);
}

/**
 * Key of the nav item the hash selects: "p:<plugin>/<page>" for plugin
 * routes, else the key of the first legacy entry whose `match` accepts the
 * hash path, else null.
 */
export function activeNavKey(hash, legacyNav = []) {
  const value = hash || "";
  const route = PLUGIN_ROUTE.exec(value);
  if (route) return `p:${route[1]}/${route[2]}`;
  if (/^#p\//.test(value)) return null;
  const path = value.replace(/^#/, "").split("?")[0];
  const hit = legacyNav.find((item) => item.match && item.match.test(path));
  return hit ? hit.key : null;
}

/** Plugin nav entries; the shell sets them once the manifest has loaded. */
export const navStore = createStore([]);

function useHash() {
  const [hash, setHash] = useState(() => window.location.hash);
  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash;
}

export function TopBar({ legacyNav = [] }) {
  const entries = sortNav(useStore(navStore));
  const hash = useHash();
  const active = activeNavKey(hash, legacyNav);
  return html`<header id="hc-top-bar" class=${`hc-top-bar${entries.length ? " has-plugin-nav" : ""}`}>
    <div class="hc-brand">
      <div class="hc-brand-mark" aria-hidden="true">V</div>
      <div>
        <p class="hc-eyebrow">本地操作</p>
        <h1 class="hc-brand-title">VSE Toolbox</h1>
      </div>
      <${VersionChip} />
    </div>

    <nav class="hc-nav" aria-label="工作区导航">
      ${legacyNav.map((item) => html`<a
        key=${`legacy:${item.key}`}
        href=${item.href}
        class=${active === item.key ? "active" : ""}
        aria-current=${active === item.key ? "page" : null}
        data-panel-link=${item.key}
      >${item.title}</a>`)}
      ${entries.map((entry) => {
        const key = `p:${entry.plugin}/${entry.page}`;
        return html`<a
          key=${key}
          href=${`#p/${entry.plugin}/${entry.page}`}
          class=${active === key ? "active" : ""}
          aria-current=${active === key ? "page" : null}
          data-plugin-link=${`${entry.plugin}/${entry.page}`}
        >${entry.title}</a>`;
      })}
    </nav>

    <div class="hc-actions">
      <${SessionBadges} />
      <${TaskCenterButton} />
      <${ThemeToggle} />
    </div>
  </header>`;
}
