// 数模设计审核流程（D5）：车型 ↔ 架构件单的人工声明面板（方案 B）。
//
// 只做"一个人、几条、定一次就不动"的最小交互：选车型 → 粘贴单号 → 保存。
// 四态（已匹配 / 来源不符 / 快照缺失 / 键冲突）由后端判定，前端只负责展示，
// 避免在浏览器里再算一遍口径。
import { html, useEffect, useState } from "/static/host/vendor/preact-htm.js";
import { apiRequest, plainErrorMessage } from "./api.js";

const LINKS_PATH = "/api/p/project-overview/vehicle-arch-links";

const STATUS_CLASS = {
  matched: "is-matched",
  source_mismatch: "is-mismatch",
  missing: "is-missing",
  conflict: "is-conflict",
};

async function saveLinks(body) {
  return apiRequest(LINKS_PATH, { method: "POST", body });
}

function serialsText(vehicleSummary) {
  if (!vehicleSummary) return "";
  return (vehicleSummary.links || []).map((item) => item.serial).join("\n");
}

export function ArchLinksPanel({ summary, onSaved }) {
  const vehicles = ((summary && summary.vehicles) || []).map((item) => item.vehicle);
  const [vehicle, setVehicle] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!vehicle && vehicles.length) setVehicle(vehicles[0]);
  }, [summary]);

  const current = ((summary && summary.vehicles) || []).find(
    (item) => item.vehicle === vehicle,
  );
  useEffect(() => {
    setText(serialsText(current));
  }, [vehicle, summary]);

  const run = async (body, okText) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await saveLinks(body);
      setMessage(okText);
      if (onSaved) onSaved();
    } catch (err) {
      setError(plainErrorMessage(err, "保存关联失败"));
    } finally {
      setBusy(false);
    }
  };

  const linked = current ? current.linkedArchitecture : null;
  const combined = current ? current.combined : null;
  const projectOnly = current ? current.projectOnly : null;

  return html`<details class="form-watchlist form-arch-links">
    <summary>
      关联架构件${linked && linked.matched
        ? ` ${linked.matched} 单 · 计入车型合计`
        : "（未指定，车型合计只含项目件）"}
    </summary>
    <div class="form-watchlist-body">
      <div class="form-watchlist-actions">
        <label>车型
          <input class="form-filter-keyword" list="form-arch-link-vehicles" value=${vehicle}
            aria-label="车型" placeholder="如 F620S"
            onInput=${(event) => setVehicle(event.target.value.trim())} />
        </label>
        <datalist id="form-arch-link-vehicles">
          ${vehicles.map((item) => html`<option value=${item} key=${item}></option>`)}
        </datalist>
        <button type="button" class="btn" disabled=${busy || !vehicle}
          onClick=${() => run({ action: "replace", vehicle, serials: text }, "已保存")}>保存</button>
        <button type="button" class="btn is-secondary" disabled=${busy || !vehicle}
          onClick=${() => { if (window.confirm(`清空 ${vehicle} 的关联架构件？`)) run({ action: "clear", vehicle }, "已清空"); }}>清空</button>
      </div>

      ${error && html`<p class="form-watchlist-error" role="alert">${error}</p>`}
      ${message && html`<p class="form-watchlist-empty" role="status">${message}</p>`}

      <textarea class="form-filter-keyword form-terms-input" rows="4" maxlength="20000"
        aria-label="关联的架构件流水单号，一行一个" placeholder="一行一个流水单号，例如 Ar-L-3D-0002"
        value=${text} onInput=${(event) => setText(event.target.value)}></textarea>
      <p class="form-terms-hint">架构件的「项目/车型」是平台代号，系统不会自动归到车型；这里是你显式声明的关联。</p>

      ${current && html`<p class="form-arch-links-summary">
        ${projectOnly ? `仅项目件 ${projectOnly.instances} 单（${projectOnly.completionRate}%）` : ""}
        ${linked ? ` · 关联架构件 ${linked.matched}/${linked.declared} 单` : ""}
        ${combined ? ` · 合计 ${combined.instances} 单（${combined.completionRate}%）` : ""}
      </p>`}

      ${current && current.links.length > 0 && html`<ul class="form-watchlist-items">
        ${current.links.map((item) => html`<li key=${item.serial}>
          <span>${item.serial}</span>
          <span class=${`form-watchlist-state ${STATUS_CLASS[item.status] || ""}`}>${item.statusLabel}${item.projectModel ? `（${item.projectModel}）` : ""}</span>
        </li>`)}
      </ul>`}
      ${current && current.links.length === 0 && html`<p class="form-watchlist-empty">尚未指定关联单号，车型合计只含项目件。</p>`}
    </div>
  </details>`;
}
