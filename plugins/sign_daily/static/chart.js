// 签署日报三张欠账图（规格 §6 G1–G8）：纯布局 + Canvas 绘制。
// 同一张 PNG 用于预览、复制图片和 .eml（规格 §10 出图方案：浏览器 Canvas）。
// layoutChart 不碰 DOM，node 可测（tests/test_sign_daily_frontend_logic.py）。

export const DISPLAY_WIDTH = 720; // G5：显示宽度 720 px
export const PIXEL_RATIO = 2; // G5：按 2 倍像素出 PNG
export const MAX_BARS_PER_ROW = 30; // G5：每行最多 30 根柱

const PAD_LEFT = 36;
const PAD_RIGHT = 12;
const TITLE_HEIGHT = 36; // G3：每组上方两行组标题
const PLOT_HEIGHT = 150;
const VALUE_HEIGHT = 14; // 柱顶份数
const NAME_CHAR = 13; // 柱下竖排姓名每个字的高度
const ROW_GAP = 18;
const GROUP_GAP = 10;

export const PALETTES = {
  external: { bar: "#3370ff", special: "#3370ff" }, // 图1 强调色
  sections: { bar: "#8f959e", special: "#c9cdd4" }, // 图2 中性色，特殊组浅色
  approval: { bar: "#8f959e", special: "#8f959e" }, // 图3 中性色
};
const FONT_STACK = "'Microsoft YaHei', 'PingFang SC', 'Source Han Sans SC', sans-serif";

/** G5：按行排，每行最多 30 根柱；超出时在分组边界换行，单组超过 30 人时组内续行。 */
export function packRows(groups, maxBars = MAX_BARS_PER_ROW) {
  const rows = [];
  let current = [];
  let used = 0;
  const flush = () => {
    if (current.length) rows.push(current);
    current = [];
    used = 0;
  };
  for (const group of groups) {
    const bars = group.bars || [];
    if (used && used + bars.length > maxBars) flush();
    let start = 0;
    while (start < bars.length) {
      const room = maxBars - used;
      const slice = bars.slice(start, start + room);
      current.push({ group, bars: slice, continued: start > 0 });
      used += slice.length;
      start += slice.length;
      if (start < bars.length) flush();
    }
    if (!bars.length) current.push({ group, bars: [], continued: false });
  }
  flush();
  return rows;
}

/** 整数刻度（G2：从 0 起、整数刻度），最多约 5 格。 */
export function yTicks(max) {
  const top = Math.max(1, Math.ceil(max));
  const step = Math.max(1, Math.ceil(top / 5));
  const ticks = [];
  for (let value = 0; value <= top; value += step) ticks.push(value);
  if (ticks[ticks.length - 1] < top) ticks.push(ticks[ticks.length - 1] + step);
  return ticks;
}

function longestLabel(rows) {
  let longest = 1;
  rows.forEach((row) => row.forEach((seg) => seg.bars.forEach((bar) => {
    longest = Math.max(longest, Array.from(String(bar.label || bar.name)).length);
  })));
  return Math.min(longest, 14);
}

/** 整张图的几何：每根柱的位置、组标题位置；图高随行数增加（G5）。 */
export function layoutChart(groups, { width = DISPLAY_WIDTH, maxBars = MAX_BARS_PER_ROW } = {}) {
  const rows = packRows(groups, maxBars);
  const maxCount = Math.max(1, ...groups.flatMap((g) => (g.bars || []).map((b) => b.count)));
  const ticks = yTicks(maxCount);
  const labelHeight = longestLabel(rows) * NAME_CHAR + 6;
  const rowHeight = TITLE_HEIGHT + VALUE_HEIGHT + PLOT_HEIGHT + labelHeight;
  const plotWidth = width - PAD_LEFT - PAD_RIGHT;
  const out = [];
  rows.forEach((row, rowIndex) => {
    const top = rowIndex * (rowHeight + ROW_GAP);
    const barCount = row.reduce((sum, seg) => sum + Math.max(seg.bars.length, 1), 0);
    const gaps = (row.length - 1) * GROUP_GAP;
    const slot = Math.min(36, (plotWidth - gaps) / Math.max(barCount, 1));
    const barWidth = Math.max(6, Math.round(slot * 0.62));
    let x = PAD_LEFT;
    const segments = row.map((seg) => {
      const startX = x;
      const bars = seg.bars.map((bar) => {
        const center = x + slot / 2;
        x += slot;
        return { ...bar, x: center - barWidth / 2, center, width: barWidth };
      });
      if (!seg.bars.length) x += slot;
      const segment = { group: seg.group, continued: seg.continued, x: startX, width: x - startX, bars };
      x += GROUP_GAP;
      return segment;
    });
    out.push({ top, plotTop: top + TITLE_HEIGHT + VALUE_HEIGHT, plotHeight: PLOT_HEIGHT, labelTop: top + rowHeight - labelHeight, segments });
  });
  const height = rows.length ? rows.length * rowHeight + (rows.length - 1) * ROW_GAP + 8 : 0;
  return { width, height, ticks, top: ticks[ticks.length - 1], rows: out };
}

/** G3：组标题第二行，如「23 人次 / 15 份 / 5 人」。 */
export function groupStatsText(group) {
  return `${group.personTimes} 人次 / ${group.flows} 份 / ${group.people} 人`;
}

/** 在 canvas 上按 2 倍像素画出整张图，返回 PNG data URI；没有数据返回 null（G6）。 */
export function renderChartPng(groups, key, documentRef = globalThis.document) {
  if (!groups || !groups.length) return null;
  const layout = layoutChart(groups);
  const canvas = documentRef.createElement("canvas");
  canvas.width = layout.width * PIXEL_RATIO;
  canvas.height = layout.height * PIXEL_RATIO;
  const g = canvas.getContext("2d");
  g.scale(PIXEL_RATIO, PIXEL_RATIO);
  g.fillStyle = "#ffffff";
  g.fillRect(0, 0, layout.width, layout.height);
  const palette = PALETTES[key] || PALETTES.sections;
  layout.rows.forEach((row) => {
    const scale = row.plotHeight / layout.top;
    const baseY = row.plotTop + row.plotHeight;
    // Y 轴整数刻度
    g.strokeStyle = "#e5e6eb";
    g.fillStyle = "#646a73";
    g.font = `11px ${FONT_STACK}`;
    g.textAlign = "right";
    g.textBaseline = "middle";
    layout.ticks.forEach((tick) => {
      const y = baseY - tick * scale;
      g.beginPath();
      g.moveTo(32, y);
      g.lineTo(layout.width - 12, y);
      g.stroke();
      g.fillText(String(tick), 28, y);
    });
    row.segments.forEach((seg) => {
      const special = seg.group.special === true;
      // 组标题：组名 + 人次 / 份数 / 人数
      g.textAlign = "center";
      g.textBaseline = "alphabetic";
      g.fillStyle = "#1f2329";
      g.font = `bold 12px ${FONT_STACK}`;
      const center = seg.x + seg.width / 2;
      g.fillText(seg.continued ? `${seg.group.group}（续）` : seg.group.group, center, row.top + 14, Math.max(seg.width, 40));
      g.fillStyle = "#646a73";
      g.font = `11px ${FONT_STACK}`;
      g.fillText(groupStatsText(seg.group), center, row.top + 29, Math.max(seg.width, 40));
      seg.bars.forEach((bar) => {
        const h = bar.count * scale;
        g.fillStyle = special ? palette.special : palette.bar;
        g.fillRect(bar.x, baseY - h, bar.width, h);
        g.fillStyle = "#1f2329";
        g.font = `bold 11px ${FONT_STACK}`;
        g.textAlign = "center";
        g.fillText(String(bar.count), bar.center, baseY - h - 3); // 柱顶标份数
        g.font = `12px ${FONT_STACK}`;
        Array.from(String(bar.label || bar.name)).slice(0, 14).forEach((ch, i) => {
          g.fillText(ch, bar.center, row.labelTop + (i + 1) * NAME_CHAR); // 柱下姓名竖排
        });
      });
      // 分组底线
      g.strokeStyle = "#c9cdd4";
      g.beginPath();
      g.moveTo(seg.x, baseY + 0.5);
      g.lineTo(seg.x + seg.width, baseY + 0.5);
      g.stroke();
    });
  });
  return canvas.toDataURL("image/png");
}
