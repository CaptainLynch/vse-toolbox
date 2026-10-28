// 「报告」：所有对外产出的东西集中在这里，统一成"选条件 → 一键生成 → 发出去"。
import { PageHead, Pill, go, html, todayString, useLoad, useWorkbenchStyles } from "./common.js";

const SOURCES = { signDaily: "/api/p/sign-daily/state", tir: "/api/p/tir-report/state" };

function Entry({ icon, title, text, status, action, secondary }) {
  return html`<div class="wb-card wb-entry">
    <div class="wb-row" style="justify-content:space-between"><span class="wb-entry-icon" aria-hidden="true">${icon}</span>${status}</div>
    <h3>${title}</h3>
    <p>${text}</p>
    <div class="wb-row">
      <button type="button" class="wb-btn is-primary" onClick=${() => go(action.href)}>${action.label}</button>
      ${secondary && html`<button type="button" class="wb-btn" onClick=${() => go(secondary.href)}>${secondary.label}</button>`}
    </div>
  </div>`;
}

export default function ReportsPage() {
  useWorkbenchStyles();
  const { data } = useLoad(SOURCES);
  const daily = data.signDaily && data.signDaily.data;
  const fresh = daily && daily.dataDate === todayString();
  return html`<div class="wb-page">
    <${PageHead} title="报告" sub="所有报告都是同一个流程：选条件 → 一键生成 → 复制或发邮件" />
    <div class="wb-grid wb-grid-2">
      <${Entry} icon="📨" title="3D 单签署日报"
        text="自动刷新 TDC 数模审批数据，按车型和科室生成三图一表，可以直接复制正文或生成邮件草稿。"
        status=${daily ? html`<${Pill} tone=${fresh ? "ok" : "warn"}>${fresh ? "今天的数据" : `数据日期 ${daily.dataDate || "—"}`}<//>` : null}
        action=${{ label: "一键生成日报", href: "#p/sign-daily/report" }} />
      <${Entry} icon="📊" title="TIR 数据简表"
        text="从帆软报表平台导出 TIR 数据简表（Excel），当天已经导出过的直接复用。"
        status=${data.tir ? html`<${Pill} tone="info">可导出<//>` : null}
        action=${{ label: "导出 Excel", href: "#p/tir-report/report" }} />
      <${Entry} icon="⬇️" title="业务系统报表导出"
        text="EWO / PAA / NCR、TDC 数模 / SOR / 造型 A 面的原始报表，导出为 Excel / CSV。"
        action=${{ label: "选择报表导出", href: "#p/system-query/query" }} />
      <${Entry} icon="🧾" title="交付物表单统计"
        text="六张交付物表单（EWO、PAA、NCR 进度/明细、数模、SOR）的统计图和明细。"
        action=${{ label: "查看统计", href: "#p/deliverable-forms/index" }} />
    </div>
  </div>`;
}
