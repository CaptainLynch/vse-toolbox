// Application top bar: brand + version chip, workspace navigation generated
// from the plugin manifest, session badges, task center button and theme
// toggle.
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
 * Key ("<plugin>/<page>") of the nav entry the hash selects: the entry for
 * that exact page, else the plugin's first entry (detail pages such as
 * `#p/project-overview/deliverable` keep 概览 highlighted), else null.
 */
export function activeNavKey(hash, entries = []) {
  const route = PLUGIN_ROUTE.exec(hash || "");
  if (!route) return null;
  const exact = entries.find((entry) => entry.plugin === route[1] && entry.page === route[2]);
  const owner = exact || entries.find((entry) => entry.plugin === route[1]);
  return owner ? `${owner.plugin}/${owner.page}` : null;
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

export function TopBar() {
  const entries = sortNav(useStore(navStore));
  const hash = useHash();
  const active = activeNavKey(hash, entries);
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
      ${entries.map((entry) => {
        const key = `${entry.plugin}/${entry.page}`;
        return html`<a
          key=${key}
          href=${`#p/${entry.plugin}/${entry.page}`}
          class=${active === key ? "active" : ""}
          aria-current=${active === key ? "page" : null}
          data-plugin-link=${key}
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
