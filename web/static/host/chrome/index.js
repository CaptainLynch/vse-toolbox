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

function ensureMount() {
  let mount = document.getElementById(CHROME_MOUNT_ID);
  if (mount) return mount;
  mount = document.createElement("div");
  mount.id = CHROME_MOUNT_ID;
  const shell = document.querySelector(".app-shell") || document.body;
  shell.insertBefore(mount, shell.firstChild);
  return mount;
}

function Chrome() {
  return html`<${TopBar} />
    <${VersionDialog} />
    <${LoginDialog} />
    <${TaskCenterDrawer} />`;
}

let handle = null;

/** Mount once; later calls return the same handle ({setNav, mount}). */
export function mountChrome() {
  if (handle) return handle;
  applyTheme(preferredTheme());
  installSessionGlobals();

  const mount = ensureMount();
  const initialText = mount.dataset.version;
  if (initialText) versionStore.set((prev) => ({ ...prev, initialText }));

  render(html`<${Chrome} />`, mount);
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
