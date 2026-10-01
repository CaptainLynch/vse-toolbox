// Host chrome entry: mounts the top bar and the global dialogs, publishes
// the compatibility globals and starts the background refreshes.
import { html, render } from "../vendor/preact-htm.js";
import { installSessionGlobals, refreshSessionBadges } from "../session.js";
import { LoginDialog } from "./LoginDialog.js";
import { TaskCenterDrawer, fetchTasks, installTaskCenterKick } from "./TaskCenter.js";
import { TopBar, navStore } from "./TopBar.js";
import { applyTheme, preferredTheme } from "./ThemeToggle.js";
import { VersionDialog, loadAppVersion, versionStore } from "./VersionDialog.js";

export const CHROME_MOUNT_ID = "host-chrome";

// Legacy template blocks the host chrome replaces. Removing them before the
// legacy DOMContentLoaded setup runs leaves its setup functions nothing to
// bind to, so there is never a second top bar or dialog.
export const LEGACY_CHROME_SELECTORS = [
  "header.top-bar",
  "#in-place-login-modal",
  "#version-detail-modal",
  "#task-center-drawer-container",
];

function removeLegacyChrome() {
  const legacyBar = document.querySelector("header.top-bar");
  const anchor = legacyBar ? { parent: legacyBar.parentNode, next: legacyBar } : null;
  const chip = document.getElementById("app-version-chip");
  const versionText = chip && chip.textContent.trim();
  return { anchor, versionText, remove() {
    LEGACY_CHROME_SELECTORS.forEach((selector) => {
      document.querySelectorAll(selector).forEach((node) => node.remove());
    });
  } };
}

function ensureMount(anchor) {
  let mount = document.getElementById(CHROME_MOUNT_ID);
  if (mount) return mount;
  mount = document.createElement("div");
  mount.id = CHROME_MOUNT_ID;
  if (anchor && anchor.parent) {
    anchor.parent.insertBefore(mount, anchor.next);
  } else {
    const shell = document.querySelector(".app-shell") || document.body;
    shell.insertBefore(mount, shell.firstChild);
  }
  return mount;
}

function Chrome({ legacyNav }) {
  return html`<${TopBar} legacyNav=${legacyNav} />
    <${VersionDialog} />
    <${LoginDialog} />
    <${TaskCenterDrawer} />`;
}

let handle = null;

/** Mount once; later calls return the same handle ({setNav, mount}). */
export function mountChrome({ legacyNav = [] } = {}) {
  if (handle) return handle;
  applyTheme(preferredTheme());
  installSessionGlobals();

  const legacy = removeLegacyChrome();
  if (legacy.versionText) versionStore.set((prev) => ({ ...prev, initialText: legacy.versionText }));
  const mount = ensureMount(legacy.anchor);
  legacy.remove();

  render(html`<${Chrome} legacyNav=${legacyNav} />`, mount);
  installTaskCenterKick();

  loadAppVersion();
  refreshSessionBadges();
  fetchTasks();

  handle = {
    mount,
    setNav(entries) {
      navStore.set(Array.isArray(entries) ? entries : []);
    },
  };
  return handle;
}
