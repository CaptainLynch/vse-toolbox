// 数模设计审核流程报表：多值搜索摘要与关注清单面板（签署日报规格 §9 S1–S11）。
import { html, useEffect, useState } from "/static/host/vendor/preact-htm.js";
import { apiRequest, enc, plainErrorMessage } from "./api.js";
import { itemStateText, scopeLabel, termSummaryText, TERMS_PLACEHOLDER } from "./watchlist-logic.js";

const API = "/api/p/project-overview";

export async function loadWatchlist() {
  return apiRequest(`${API}/watchlist`);
}

async function changeWatchlist(body) {
  return apiRequest(`${API}/watchlist`, { method: "POST", body });
}

/** S2、S5：多值搜索框；占位符一输入就消失，所以下方常驻同一句说明。 */
export function TermsInput({ value, onInput }) {
  return html`<div class="form-terms">
    <textarea class="form-filter-keyword form-terms-input" rows="2" maxlength="20000"
      aria-label="多值搜索" placeholder=${TERMS_PLACEHOLDER} value=${value} onInput=${onInput}></textarea>
    <p class="form-terms-hint">${TERMS_PLACEHOLDER}</p>
  </div>`;
}

/** S4、S6：搜索结果摘要 + 「全部加入关注清单」。 */
export function TermsSummary({ terms, onWatchlistChanged }) {
  const [summary, setSummary] = useState(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    setSummary(null);
    setMessage("");
    if (!terms) return undefined;
    apiRequest(`${API}/form-terms?terms=${enc(terms)}`)
      .then((data) => { if (alive) setSummary(data); })
      .catch((err) => { if (alive) setMessage(plainErrorMessage(err, "搜索摘要读取失败")); });
    return () => { alive = false; };
  }, [terms]);
  if (!terms) return null;
  const addAll = async () => {
    setBusy(true);
    try {
      const data = await changeWatchlist({ action: "add", serials: summary.serials });
      setMessage(`已加入关注清单，现有 ${data.count} 份`);
      if (onWatchlistChanged) onWatchlistChanged(data);
    } catch (err) {
      setMessage(plainErrorMessage(err, "加入关注清单失败"));
    } finally {
      setBusy(false);
    }
  };
  return html`<div class="form-terms-summary" role="status">
    ${summary && html`<span>${termSummaryText(summary)}</span>`}
    ${summary && summary.unmatched.length > 0 && html`<span class="form-terms-unmatched">没匹配上：${summary.unmatched.map((t) => html`<code key=${t}>${t}</code>`)}</span>`}
    ${summary && summary.serials.length > 0 && html`<button type="button" class="btn is-secondary" disabled=${busy} onClick=${addAll}>全部加入关注清单（${summary.serials.length} 份）</button>`}
    ${message && html`<span class="form-terms-message">${message}</span>`}
  </div>`;
}

/** S1、S6、S8、S9：关注清单的查看、单条移除、清空、导出 CSV 和同步范围。 */
export function WatchlistPanel({ watchlist, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!watchlist) return null;
  const run = async (body) => {
    setBusy(true);
    setError("");
    try {
      onChanged(await changeWatchlist(body));
    } catch (err) {
      setError(plainErrorMessage(err, "保存关注清单失败"));
    } finally {
      setBusy(false);
    }
  };
  return html`<details class="form-watchlist" open=${watchlist.scope === "watchlist"}>
    <summary>关注清单 ${watchlist.count} 份 · 同步范围：${scopeLabel(watchlist.scope)}
      ${watchlist.missing.length > 0 && html`<span class="form-watchlist-missing"> · ${watchlist.missing.length} 份未找到</span>`}
      ${watchlist.configIssue && html`<span class="form-watchlist-issue"> · ${watchlist.configIssue}</span>`}
    </summary>
    <div class="form-watchlist-body">
      <div class="form-watchlist-actions">
        <label><input type="radio" name="watch-scope" checked=${watchlist.scope === "all"} disabled=${busy}
          onChange=${() => run({ action: "scope", scope: "all" })} />同步全部表单</label>
        <label><input type="radio" name="watch-scope" checked=${watchlist.scope === "watchlist"} disabled=${busy}
          onChange=${() => run({ action: "scope", scope: "watchlist" })} />仅同步关注清单</label>
        <a class="btn is-secondary" href=${`${API}/watchlist.csv`} download="watchlist.csv">导出 CSV</a>
        <button type="button" class="btn is-secondary" disabled=${busy || !watchlist.count}
          onClick=${() => { if (window.confirm("清空关注清单？")) run({ action: "clear" }); }}>清空</button>
      </div>
      ${error && html`<p class="form-watchlist-error" role="alert">${error}</p>`}
      ${watchlist.count === 0
        ? html`<p class="form-watchlist-empty">清单为空。在上方搜索后点「全部加入关注清单」。</p>`
        : html`<ul class="form-watchlist-items">
          ${watchlist.items.map((item) => html`<li key=${item.serial}>
            <span>${item.serial}</span>
            ${itemStateText(item) && html`<span class=${`form-watchlist-state${item.found === false ? " is-missing" : ""}`}>${itemStateText(item)}</span>`}
            <button type="button" class="form-filter-chip-remove" aria-label=${`移除 ${item.serial}`} disabled=${busy}
              onClick=${() => run({ action: "remove", serials: [item.serial] })}>×</button>
          </li>`)}
        </ul>`}
    </div>
  </details>`;
}
