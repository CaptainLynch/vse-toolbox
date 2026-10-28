// 「工具」：日常小工具 + 专家模式开关。
import { useEffect, useState } from "/static/host/vendor/preact-htm.js";
import { expertStore, setExpertMode } from "/static/host/expert.js";
import { PageHead, go, html, useWorkbenchStyles } from "./common.js";

function useExpert() {
  const [on, setOn] = useState(expertStore.get());
  useEffect(() => expertStore.subscribe(setOn), []);
  return on;
}

function Entry({ icon, title, text, href, label, primary = true }) {
  return html`<div class="wb-card wb-entry">
    <span class="wb-entry-icon" aria-hidden="true">${icon}</span>
    <h3>${title}</h3>
    <p>${text}</p>
    <div class="wb-row"><button type="button" class=${`wb-btn${primary ? " is-primary" : ""}`} onClick=${() => go(href)}>${label}</button></div>
  </div>`;
}

export default function ToolsPage() {
  useWorkbenchStyles();
  const expert = useExpert();
  return html`<div class="wb-page">
    <${PageHead} title="工具" sub="日常的小工具。Excel 处理会在后台自动打开和关闭 Excel。" />
    <div class="wb-grid wb-grid-3">
      <${Entry} icon="📑" title="Excel 合并 / 叠加 / 比对" text="多个工作簿首尾合并、按位置数值叠加，或找出两个文件不同的单元格。"
        href="#p/excel-tasks/workspace" label="打开 Excel 工具" />
      <${Entry} icon="⬆️" title="程序与插件更新" text="安装收到的更新包、查看版本记录、回到上一版本。"
        href="#p/settings/updates" label="查看更新" />
      <${Entry} icon="🗄️" title="自动归档" text="每天把业务系统的原始报表存一份。一般不需要手动设置。"
        href="#p/scheduled-archive/jobs" label="查看归档" primary=${false} />
    </div>
    <section class="wb-card">
      <div class="wb-card-head"><h3>专家模式</h3></div>
      <button type="button" class=${`wb-switch${expert ? " on" : ""}`} role="switch" aria-checked=${expert ? "true" : "false"} onClick=${() => setExpertMode(!expert)}>
        <i></i>
        <span><b>${expert ? "已开启" : "已关闭"}</b><br /><span class="wb-small wb-muted">开启后顶栏会多出原来的技术入口：概览、交付物工作台、系统查询（Base URL / XML）、表单、诊断录制等。日常使用不需要开启。</span></span>
      </button>
    </section>
  </div>`;
}
