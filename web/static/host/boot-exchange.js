// 启动交换票据（C7 本机安全契约，W16-03）。
// 启动器把一次性票据附在地址栏 `?boot=` 上；这里把它换成本机会话 Cookie，
// 随后立即用 replaceState 从地址栏和历史里清除票据（刷新/分享链接都不会再带上）。
// 交换失败不阻塞页面：会话缺失时写操作会被服务端拒绝并提示重新打开应用。

const BOOT_QUERY_KEY = "boot";
const BOOT_EXCHANGE_ENDPOINT = "/api/security/boot-exchange";

export function extractBootTicket(search) {
  const params = new URLSearchParams(search || "");
  return params.get(BOOT_QUERY_KEY);
}

export function stripBootTicket(search) {
  const params = new URLSearchParams(search || "");
  if (!params.has(BOOT_QUERY_KEY)) return null;
  params.delete(BOOT_QUERY_KEY);
  const rest = params.toString();
  return rest ? `?${rest}` : "";
}

export async function exchangeBootTicket(token) {
  const response = await fetch(BOOT_EXCHANGE_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ token }),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload || payload.ok !== true) {
    const error = (payload && payload.error) || {};
    throw new Error(error.message || "启动票据无效或已过期，请重新打开应用");
  }
  return payload.data;
}

/** 应用启动时执行一次：有票据就交换并清理地址栏；失败静默（fail-closed 在服务端）。 */
export async function runBootExchange(win = window) {
  const ticket = extractBootTicket(win.location.search);
  if (!ticket) return false;
  const rest = stripBootTicket(win.location.search);
  const cleaned =
    win.location.pathname + (rest || "") + (win.location.hash || "");
  try {
    await exchangeBootTicket(ticket);
  } catch (_) {
    // 票据无效/过期：清除地址栏后交由后续请求的 401 提示引导用户重新打开。
  }
  win.history.replaceState(null, "", cleaned);
  return true;
}
