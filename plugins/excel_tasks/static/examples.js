// Excel 文件处理：操作示例弹窗（移植自旧页 #excel-examples-dialog，含暂停/播放动画）。
import { html, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";

function FileBox({ title, children, extra = "" }) {
  return html`<div class=${`xt-anim-file ${extra}`}>
    <div class="xt-anim-file-header">${title}</div>
    ${children}
  </div>`;
}

const Arrow = ({ text }) => html`<div class="xt-anim-arrow">${text}</div>`;

function AppendStage() {
  return html`<div class="xt-anim-stage xt-anim-append">
    <${FileBox} title="文件 A (行 1..2)">
      <div class="xt-anim-row">Row A1</div><div class="xt-anim-row">Row A2</div>
    </${FileBox}>
    <${Arrow} text="+" />
    <${FileBox} title="文件 B (行 1..2)">
      <div class="xt-anim-row">Row B1</div><div class="xt-anim-row">Row B2</div>
    </${FileBox}>
    <${Arrow} text="→" />
    <${FileBox} title="合并输出 (行 1..4)" extra="is-output">
      <div class="xt-anim-row">Row A1</div><div class="xt-anim-row">Row A2</div>
      <div class="xt-anim-row">Row B1</div><div class="xt-anim-row">Row B2</div>
    </${FileBox}>
  </div>`;
}

function OverlayStage() {
  return html`<div class="xt-anim-stage xt-anim-overlay">
    <${FileBox} title="目标模板 (空表格)">
      <div class="xt-anim-cells"><div class="xt-anim-cell is-ph">[待填数据]</div><div class="xt-anim-cell is-ph">[待填数据]</div></div>
    </${FileBox}>
    <${Arrow} text="+" />
    <${FileBox} title="来源数据">
      <div class="xt-anim-cells"><div class="xt-anim-cell is-val">Val 1</div><div class="xt-anim-cell is-val">Val 2</div></div>
    </${FileBox}>
    <${Arrow} text="→" />
    <${FileBox} title="填充后模板" extra="is-output">
      <div class="xt-anim-cells"><div class="xt-anim-cell is-filled">Val 1 (已填充)</div><div class="xt-anim-cell is-filled">Val 2 (已填充)</div></div>
    </${FileBox}>
  </div>`;
}

function DiffStage() {
  return html`<div class="xt-anim-stage xt-anim-diff">
    <${FileBox} title="对比基准 (Baseline)">
      <div class="xt-anim-diff-row">条目 1: 旧数值</div><div class="xt-anim-diff-row">条目 2: 保持不变</div>
    </${FileBox}>
    <${Arrow} text="vs" />
    <${FileBox} title="最新文件 (Current)">
      <div class="xt-anim-diff-row">条目 1: 新数值</div><div class="xt-anim-diff-row">条目 2: 保持不变</div>
    </${FileBox}>
    <${Arrow} text="→" />
    <${FileBox} title="差异比对报告" extra="is-output">
      <div class="xt-anim-diff-row is-modified">条目 1: 已修改 (旧→新)</div>
      <div class="xt-anim-diff-row is-unchanged">条目 2: 一致</div>
    </${FileBox}>
  </div>`;
}

const EXAMPLES = [
  {
    tag: "追加合并",
    title: "将多个来源文件的记录行垂直拼接",
    desc: "读取选中的多个 Excel 文件的有效数据行，按顺序追加合并至一个输出文件中，保留相同表头结构。",
    Stage: AppendStage,
  },
  {
    tag: "覆盖合并",
    title: "基于目标模板填入来源数据",
    desc: "以指定的目标模板为基准格式，将来源文件中的字段按列映射关系覆盖填充到目标模板对应单元格中。",
    Stage: OverlayStage,
  },
  {
    tag: "基线差异比对",
    title: "比对最新文件与对比基准的变更",
    desc: "以对比基准文件为对照，逐行逐列比对最新文件的差异，标记新增、修改或删除的记录项并输出比对报告。",
    Stage: DiffStage,
  },
];

export function ExamplesDialog({ open, onClose }) {
  const ref = useRef(null);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    } else if (!open && dialog.open) {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    }
  }, [open]);

  return html`<dialog ref=${ref} class="xt-examples-dialog" aria-label="Excel 操作示例" onClose=${onClose} onCancel=${onClose}>
    <div class="xt-examples-head">
      <div>
        <p class="xt-eyebrow">操作指南</p>
        <h4>Excel 文件处理操作示例</h4>
      </div>
      <span class="vk-page-actions">
        <button type="button" class="vk-btn" onClick=${() => setPaused((value) => !value)}>${paused ? "播放动画" : "暂停动画"}</button>
        <button type="button" class="vk-btn" onClick=${onClose}>关闭</button>
      </span>
    </div>
    <div class=${`xt-examples${paused ? " is-paused" : ""}`}>
      ${EXAMPLES.map(({ tag, title, desc, Stage }) => html`<article key=${tag} class="xt-example-card" aria-label=${`${tag}示例`}>
        <div class="xt-example-card-head"><span class="xt-example-tag">${tag}</span><h5>${title}</h5></div>
        <p class="xt-example-desc">${desc}</p>
        <${Stage} />
      </article>`)}
    </div>
  </dialog>`;
}
