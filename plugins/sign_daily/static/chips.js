// 项目/科室多选 chip。抽成独立模块是为了能被 node 直接渲染断言
// （tests/test_sign_daily_frontend_logic.py 用仓库自带 htm，不引入浏览器依赖）。
// 已保存但本次数据里没有的项（孤儿）渲染成虚线 chip，点一下取消，绝不自动删除（TDC-20261029）。
import { html } from "/static/host/vendor/preact-htm.js";
import { toggle } from "./report-logic.js";

export function Chips({ options, value, onChange, emptyText, orphans }) {
  const extra = orphans || [];
  if (!options.length && !extra.length) return html`<span class="vk-muted">${emptyText}</span>`;
  const chip = (option, orphan) => html`<label key=${option}
      class=${`sd-chip ${value.includes(option) ? "is-on" : ""}${orphan ? " is-orphan" : ""}`}
      title=${orphan ? "本次数据里没有这个项目，点一下取消" : ""}>
      <input type="checkbox" checked=${value.includes(option)} onChange=${() => onChange(toggle(value, option))} />${option}
    </label>`;
  return html`<div class="sd-chips">
    ${options.map((option) => chip(option, false))}
    ${extra.map((option) => chip(option, true))}
  </div>`;
}
