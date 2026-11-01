// 北京时间统一前端格式（契约 C9「时间」）。
//
// - 时间点：显示一律北京时间 Asia/Shanghai，与浏览器所在时区、系统语言无关；
// - 纯日期（businessDate、计划完成日期）：原样返回，绝不做任何时区换算；
// - 无时区历史值：按来源解释（tdc / aras / local），绝不静默追加 Z 后缀。
//
// 语义与 core/time_rules.py 的 format_beijing / pure_date / interpret_naive 对齐，
// 便于前后端对同一时刻给出同一串文本。不依赖 toLocaleString 等随宿主语言/时区
// 变化的接口，只用 UTC 取值 + 固定偏移，保证三地浏览器结果一致。

export const BEIJING_TZ = "Asia/Shanghai";
export const BEIJING_TZ_LABEL = "北京时间 (Asia/Shanghai)";
export const BEIJING_OFFSET_MINUTES = 480;

const MS_PER_MINUTE = 60000;
const DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
const NAIVE_SOURCES = new Set(["tdc", "aras", "local"]);

const PURE_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
const INSTANT_RE =
  /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?(Z|z|[+-]\d{2}:?\d{2})$/;
const NAIVE_RE =
  /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?)?$/;

function pad2(value) {
  return String(value).padStart(2, "0");
}

function isLeapYear(year) {
  return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
}

function daysInMonth(year, month) {
  return month === 2 && isLeapYear(year) ? 29 : DAYS_IN_MONTH[month - 1];
}

function assertCalendarDate(year, month, day, raw) {
  if (month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month)) {
    throw new RangeError(`无效的日历日期: ${raw}`);
  }
}

function assertClock(hour, minute, second, raw) {
  if (hour > 23 || minute > 59 || second > 59) {
    throw new RangeError(`无效的时刻: ${raw}`);
  }
}

function fractionToMillis(fraction) {
  if (!fraction) return 0;
  return Number(fraction.slice(0, 3).padEnd(3, "0"));
}

function offsetMinutesFromToken(token) {
  if (token === "Z" || token === "z") return 0;
  const sign = token[0] === "-" ? -1 : 1;
  const digits = token.slice(1).replace(":", "");
  const hours = Number(digits.slice(0, 2));
  const minutes = Number(digits.slice(2, 4));
  if (hours > 23 || minutes > 59) {
    throw new RangeError(`无效的时区偏移: ${token}`);
  }
  return sign * (hours * 60 + minutes);
}

function formatOffset(minutes) {
  const sign = minutes < 0 ? "-" : "+";
  const abs = Math.abs(minutes);
  return `${sign}${pad2(Math.floor(abs / 60))}:${pad2(abs % 60)}`;
}

/** 带显式时区的时间点文本 -> epoch 毫秒；非时间点格式返回 null。 */
function parseInstantText(text) {
  const match = INSTANT_RE.exec(text);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = match[6] ? Number(match[6]) : 0;
  assertCalendarDate(year, month, day, text);
  assertClock(hour, minute, second, text);
  const utcMs = Date.UTC(year, month - 1, day, hour, minute, second, fractionToMillis(match[7]));
  return utcMs - offsetMinutesFromToken(match[8]) * MS_PER_MINUTE;
}

function resolvedLocalTimeZone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "local";
  } catch (_err) {
    return "local";
  }
}

/**
 * 时间点 -> epoch 毫秒。只接受 Date、epoch 毫秒数，或带 Z / ±HH:MM 的 ISO 字符串。
 * 纯日期与无时区字符串被显式拒绝，避免静默跨时区位移。
 */
export function parseInstant(value) {
  if (value === null || value === undefined) {
    throw new TypeError("parseInstant 不接受 null/undefined 输入");
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new TypeError(`parseInstant 收到非有限数值: ${value}`);
    }
    return Math.trunc(value);
  }
  if (value instanceof Date) {
    const ms = value.getTime();
    if (Number.isNaN(ms)) {
      throw new TypeError("parseInstant 收到无效的 Date 对象");
    }
    return ms;
  }
  if (typeof value !== "string") {
    throw new TypeError(`parseInstant 不支持的类型: ${typeof value}`);
  }
  const text = value.trim();
  if (!text) {
    throw new TypeError("parseInstant 不接受空字符串");
  }
  const instant = parseInstantText(text);
  if (instant !== null) return instant;
  if (PURE_DATE_RE.test(text)) {
    throw new TypeError(`纯日期不是时间点: ${text}；请用 formatPureDate，纯日期不做时区换算`);
  }
  if (NAIVE_RE.test(text)) {
    throw new TypeError(`无时区取值不能当作时间点: ${text}；请先用 interpretNaiveTime 按来源解释`);
  }
  throw new TypeError(`无法解析的时间点: ${text}`);
}

/** 是否为合法 'YYYY-MM-DD' 纯日期字符串。 */
export function isPureDate(value) {
  if (typeof value !== "string") return false;
  const match = PURE_DATE_RE.exec(value.trim());
  if (!match) return false;
  try {
    assertCalendarDate(Number(match[1]), Number(match[2]), Number(match[3]), value);
    return true;
  } catch (_err) {
    return false;
  }
}

/**
 * 纯日期原样返回 'YYYY-MM-DD'，不做任何时区换算（跨时区不位移）。
 * 带时间分量或 Date 对象一律拒绝：那是时间点，不是纯日期。
 */
export function formatPureDate(value) {
  if (value === null || value === undefined) {
    throw new TypeError("formatPureDate 不接受 null/undefined 输入");
  }
  if (value instanceof Date) {
    throw new TypeError("formatPureDate 只接受纯日期字符串；Date 对象是时间点，会跨时区位移");
  }
  if (typeof value !== "string") {
    throw new TypeError(`formatPureDate 不支持的类型: ${typeof value}`);
  }
  const text = value.trim();
  const match = PURE_DATE_RE.exec(text);
  if (!match) {
    throw new TypeError(`formatPureDate 仅接受 'YYYY-MM-DD' 格式纯日期字符串，收到: ${text}`);
  }
  assertCalendarDate(Number(match[1]), Number(match[2]), Number(match[3]), text);
  return text;
}

/** 时间点 -> 北京时间的年月日时分秒分量（与宿主时区无关）。 */
export function beijingParts(value) {
  const shifted = new Date(parseInstant(value) + BEIJING_OFFSET_MINUTES * MS_PER_MINUTE);
  return {
    year: shifted.getUTCFullYear(),
    month: shifted.getUTCMonth() + 1,
    day: shifted.getUTCDate(),
    hour: shifted.getUTCHours(),
    minute: shifted.getUTCMinutes(),
    second: shifted.getUTCSeconds(),
    tzName: BEIJING_TZ,
    offsetMinutes: BEIJING_OFFSET_MINUTES,
  };
}

/** 时间点 -> 北京时间 'YYYY-MM-DD HH:mm'（与 core.time_rules.format_beijing 同格式）。 */
export function formatBeijing(value) {
  const p = beijingParts(value);
  return `${p.year}-${pad2(p.month)}-${pad2(p.day)} ${pad2(p.hour)}:${pad2(p.minute)}`;
}

/** 时间点 -> 北京时间 'YYYY-MM-DD HH:mm:ss'。 */
export function formatBeijingSeconds(value) {
  const p = beijingParts(value);
  return `${formatBeijing(value)}:${pad2(p.second)}`;
}

/** 时间点 -> 北京时间日期 'YYYY-MM-DD'（日期取北京时间当天，不是浏览器本地当天）。 */
export function formatBeijingDate(value) {
  const p = beijingParts(value);
  return `${p.year}-${pad2(p.month)}-${pad2(p.day)}`;
}

/** 时间点 -> 'YYYY-MM-DD HH:mm (Asia/Shanghai)'，界面明确标注时区。 */
export function formatBeijingWithZone(value) {
  return `${formatBeijing(value)} (${BEIJING_TZ})`;
}

/**
 * 解释无时区历史值，按来源标注依据，绝不追加 Z 后缀。
 *
 * - tdc：TDC 报表/协同接口时间戳，按 Asia/Shanghai (UTC+8) 解释；
 * - aras：ARAS Innovator 审批时间戳，按企业标准时间 Asia/Shanghai (UTC+8) 解释；
 * - local：宿主系统本地时间，按当前操作系统本地时区解释。
 *
 * 返回 { source, tzName, offsetMinutes, iso, epochMs, naive, beijingText, rationale }，
 * 其中 iso 始终带显式偏移（如 +08:00），epochMs 可直接交给 formatBeijing 系列函数。
 */
export function interpretNaiveTime(value, source) {
  if (value === null || value === undefined) {
    throw new TypeError("interpretNaiveTime 不接受 null/undefined 输入");
  }
  const sourceKey = String(source === null || source === undefined ? "" : source).trim().toLowerCase();
  if (!NAIVE_SOURCES.has(sourceKey)) {
    throw new RangeError(
      `未知的数据来源: ${String(source)}，source 必须属于 'tdc'、'aras'、'local' 之一`,
    );
  }
  if (value instanceof Date) {
    throw new TypeError("interpretNaiveTime 不接受 Date 对象：Date 已是时间点，不是无时区历史值");
  }
  if (typeof value !== "string") {
    throw new TypeError(`interpretNaiveTime 不支持的类型: ${typeof value}`);
  }
  const text = value.trim();
  if (!text) {
    throw new TypeError("interpretNaiveTime 不接受空字符串");
  }
  if (INSTANT_RE.test(text)) {
    throw new RangeError(`字符串已包含时区指示，无需作为无时区历史字段解释: ${text}`);
  }
  // 与 core/time_rules.interpret_naive 一致：斜杠日期（2026/10/03 10:00）先统一为破折号再解析。
  const match = NAIVE_RE.exec(text.replace(/\//g, "-"));
  if (!match) {
    throw new TypeError(`无法解析的无时区时间: ${text}`);
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = match[4] ? Number(match[4]) : 0;
  const minute = match[5] ? Number(match[5]) : 0;
  const second = match[6] ? Number(match[6]) : 0;
  assertCalendarDate(year, month, day, text);
  assertClock(hour, minute, second, text);
  const millis = fractionToMillis(match[7]);

  let offsetMinutes;
  let tzName;
  let rationale;
  let epochMs;
  if (sourceKey === "local") {
    const localDate = new Date(year, month - 1, day, hour, minute, second, millis);
    offsetMinutes = -localDate.getTimezoneOffset();
    tzName = resolvedLocalTimeZone();
    rationale = "本地客户端/宿主系统时间，按当前操作系统本地时区解释，绝不追加 Z 后缀";
    epochMs = localDate.getTime();
  } else {
    offsetMinutes = BEIJING_OFFSET_MINUTES;
    tzName = BEIJING_TZ;
    rationale =
      sourceKey === "tdc"
        ? "TDC 系统导出报表及协同接口时间戳按北京时间 (Asia/Shanghai, UTC+8) 解释，绝不追加 Z 后缀"
        : "ARAS Innovator ECM 审批流程时间戳按企业标准时间 (Asia/Shanghai, UTC+8) 解释，绝不追加 Z 后缀";
    epochMs = Date.UTC(year, month - 1, day, hour, minute, second, millis) - offsetMinutes * MS_PER_MINUTE;
  }

  const naive = `${year}-${pad2(month)}-${pad2(day)} ${pad2(hour)}:${pad2(minute)}:${pad2(second)}`;
  return {
    source: sourceKey,
    tzName,
    offsetMinutes,
    iso: `${year}-${pad2(month)}-${pad2(day)}T${pad2(hour)}:${pad2(minute)}:${pad2(second)}${formatOffset(offsetMinutes)}`,
    epochMs,
    naive,
    beijingText: formatBeijing(epochMs),
    rationale,
  };
}
