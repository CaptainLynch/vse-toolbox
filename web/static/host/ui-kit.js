// UI Kit 核心组件：跨插件与宿主通用的界面构建块。
// 组件设计保持纯表现（props 进、事件出），遵循通俗易懂的中文交互与一致的状态色语义。
import { html } from "./vendor/preact-htm.js";

export { html };

/**
 * 统一四色状态色常量：
 * - ok: 绿（绿色），代表运行正常、校验通过、任务完成或健康状态；
 * - warn: 黄（黄色），代表需要关注、存在预警风险、处于过渡状态或待处理；
 * - bad: 红（红色），代表操作失败、发生错误、已逾期或关键功能不可用；
 * - off: 灰（灰色），代表未开始、功能已停用、状态未知或暂不适用。
 */
export const TONE = Object.freeze({
  ok: "ok",
  warn: "warn",
  bad: "bad",
  off: "off",
});

/**
 * 一键处理动作按钮。
 *
 * @param {object} props
 * @param {string} [props.label="一键处理"] 按钮显示文本
 * @param {Function} [props.onClick] 点击事件处理回调
 * @param {boolean} [props.disabled=false] 是否禁用
 */
export function FixIt({ label = "一键处理", onClick, disabled = false } = {}) {
  return html`<button
    type="button"
    class="vk-btn is-primary uk-fixit-btn"
    disabled=${Boolean(disabled)}
    onClick=${onClick}
  >${label || "一键处理"}</button>`;
}

/**
 * 骨架屏占位组件：在页面异步数据未返回前，保持布局结构稳定，避免视觉跳跃。
 *
 * @param {object} props
 * @param {number} [props.rows=3] 占位行数，默认 3 行
 */
export function Skeleton({ rows = 3 } = {}) {
  const count = Math.max(1, Number(rows) || 3);
  return html`<div class="uk-skeleton" aria-busy="true" role="status">
    ${Array.from({ length: count }, (_, i) => html`<div key=${i} class="uk-skeleton-row"></div>`)}
  </div>`;
}

/**
 * 出错时的统一提示卡片：
 * 结构固定呈现「发生了什么 / 你需要做什么 / [一键处理] / [导出诊断包]」，
 * 确保异常提示永远伴随清晰的成因与可落地的补救指导；两个操作按钮均为可选。
 *
 * @param {object} props
 * @param {any} props.what 发生了什么（错误现象或原因说明）
 * @param {any} props.todo 你需要做什么（指导用户下一步的明确操作）
 * @param {Function|object} [props.onFix] 一键处理动作，可为点击函数或 { label, onClick, disabled }
 * @param {Function|object} [props.onDiagnostics] 导出诊断包动作，可为点击函数或 { label, onClick, disabled }
 */
export function ErrorCard({ what, todo, onFix, onDiagnostics } = {}) {
  const hasFix = Boolean(onFix);
  const hasDiag = Boolean(onDiagnostics);

  const fixProps = typeof onFix === "function"
    ? { label: "一键处理", onClick: onFix, disabled: false }
    : (onFix || {});

  const diagProps = typeof onDiagnostics === "function"
    ? { label: "导出诊断包", onClick: onDiagnostics, disabled: false }
    : (onDiagnostics || {});

  return html`<div class="uk-error-card" role="alert">
    <div class="uk-error-section uk-error-what">
      <span class="uk-error-title">发生了什么</span>
      <div class="uk-error-content">${what}</div>
    </div>
    <div class="uk-error-section uk-error-todo">
      <span class="uk-error-title">你需要做什么</span>
      <div class="uk-error-content">${todo}</div>
    </div>
    ${(hasFix || hasDiag) && html`<div class="uk-error-actions">
      ${hasFix && html`<${FixIt}
        label=${fixProps.label || "一键处理"}
        onClick=${fixProps.onClick}
        disabled=${Boolean(fixProps.disabled)}
      />`}
      ${hasDiag && html`<button
        type="button"
        class="vk-btn uk-diag-btn"
        disabled=${Boolean(diagProps.disabled)}
        onClick=${diagProps.onClick}
      >${diagProps.label || "导出诊断包"}</button>`}
    </div>`}
  </div>`;
}
