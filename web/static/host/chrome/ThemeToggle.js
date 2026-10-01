// Light/dark theme toggle. The choice is stored per browser under the same
// key the legacy page used, so existing preferences carry over.
import { html, useState } from "../vendor/preact-htm.js";

export const THEME_KEY = "vse-toolbox-theme";

function readStoredTheme() {
  try {
    return window.localStorage.getItem(THEME_KEY);
  } catch (_) {
    return null;
  }
}

export function resolveTheme(stored, prefersDark) {
  if (stored === "light" || stored === "dark") return stored;
  return prefersDark ? "dark" : "light";
}

export function preferredTheme() {
  const prefersDark = Boolean(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
  return resolveTheme(readStoredTheme(), prefersDark);
}

export function applyTheme(theme) {
  const next = theme === "dark" ? "dark" : "light";
  document.body.dataset.theme = next;
  return next;
}

export function themeLabel(theme) {
  return theme === "dark" ? "深色" : "浅色";
}

export function ThemeToggle() {
  const [theme, setTheme] = useState(() => (document.body.dataset.theme === "dark" ? "dark" : "light"));
  const toggle = () => {
    const next = document.body.dataset.theme === "dark" ? "light" : "dark";
    try {
      window.localStorage.setItem(THEME_KEY, next);
    } catch (_) {
      // 存储不可用时本次会话仍切换主题
    }
    setTheme(applyTheme(next));
  };
  return html`<button id="hc-theme-toggle" class="hc-theme-toggle" type="button" aria-label="切换主题" onClick=${toggle}>
    <span>${themeLabel(theme)}</span>
  </button>`;
}
