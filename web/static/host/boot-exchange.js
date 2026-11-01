// 启动握手（C7 本机安全契约，W16-03 → DSH-V2-03）。
//
// 票据/授权有三条**不经过地址栏**的通道（契约 §5.2）：
//   K2 宿主注入：pywebview 的 js_api 桥 take_boot_ticket() → POST boot-exchange；
//   K3 预置授权：启动器用启动器密钥预置一次性授权 → 页面 POST boot-claim 领取会话；
//   K5 会话恢复：12 小时过期后由窗口标记（vse_window）→ POST session-recover。
// 旧启动器（2.3.x）的 `?boot=` 只在 `capabilities.legacyBootQuery === true` 时读取，
// 读完立即 replaceState 清除——新链路里票据从不进入 URL、历史、Referer 或日志。
// 握手失败不阻塞页面：会话缺失时写操作由服务端 fail-closed 拒绝，外壳显示恢复横幅。

const BOOT_QUERY_KEY = "boot";
const BOOT_EXCHANGE_ENDPOINT = "/api/security/boot-exchange";
const BOOT_CLAIM_ENDPOINT = "/api/security/boot-claim";
const SESSION_RECOVER_ENDPOINT = "/api/security/session-recover";
const CAPABILITIES_ENDPOINT = "/api/security/capabilities";

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

async function postJson(path, body, fallbackMessage) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body || {}),
    credentials: "same-origin",
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload || payload.ok !== true) {
    const error = (payload && payload.error) || {};
    const failure = new Error(error.message || fallbackMessage || `请求失败（HTTP ${response.status}）`);
    failure.status = response.status;
    failure.type = error.type || "http";
    throw failure;
  }
  return payload.data;
}

export async function exchangeBootTicket(token) {
  return postJson(BOOT_EXCHANGE_ENDPOINT, { token }, "启动票据无效或已过期，请重新打开应用");
}

/** K3：领取启动器预置的一次性授权（无授权时 409，属正常情形，静默忽略）。 */
export async function claimBootSession() {
  return postJson(BOOT_CLAIM_ENDPOINT, {}, "没有待领取的窗口授权");
}

/** K5：用窗口标记换一张新会话（不重设、不延长 vse_window）。 */
export async function recoverSession() {
  return postJson(SESSION_RECOVER_ENDPOINT, {}, "本窗口无法自动恢复，请从开始菜单重新打开 VSE Toolbox");
}

export async function fetchCapabilities() {
  try {
    const response = await fetch(CAPABILITIES_ENDPOINT, {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    });
    if (!response.ok) return null;
    const payload = await response.json();
    return payload && payload.ok === true ? payload.data : null;
  } catch (_) {
    return null; // 旧 app（404）或探测失败：一律按旧 app 处理
  }
}

/**
 * K2 宿主接收器：注册 `window.__vseBootReceiver(ticket)`（幂等），返回 `true` 供旧式
 * 宿主探测。收到票据后立即自删并交换会话——票据只在这个闭包里存在一次。
 */
export function registerBootReceiver(win = window) {
  if (typeof win.__vseBootReceiver === "function") return win.__vseBootReceiver;
  const receiver = (ticket) => {
    delete win.__vseBootReceiver;
    if (typeof ticket !== "string" || !ticket) return false;
    exchangeBootTicket(ticket).catch(() => {});
    return true;
  };
  win.__vseBootReceiver = receiver;
  return receiver;
}

async function takeFromBridge(win) {
  const bridge = win.pywebview && win.pywebview.api;
  if (!bridge || typeof bridge.take_boot_ticket !== "function") return null;
  try {
    const ticket = await bridge.take_boot_ticket();
    return typeof ticket === "string" && ticket ? ticket : null;
  } catch (_) {
    return null; // 桥不可用：交给 K3
  }
}

/** 旧启动器兼容分支：仅当 legacyBootQuery 为 true 且地址栏含 boot 时取票并清理。 */
export async function consumeLegacyQueryTicket(win = window) {
  const capabilities = await fetchCapabilities();
  if (!capabilities || capabilities.legacyBootQuery !== true) return false;
  const ticket = extractBootTicket(win.location.search);
  if (!ticket) return false;
  const rest = stripBootTicket(win.location.search);
  const cleaned = win.location.pathname + (rest || "") + (win.location.hash || "");
  try {
    await exchangeBootTicket(ticket);
  } catch (_) {
    // 票据无效/过期：清除地址栏后交由后续请求的 401 提示引导用户重新打开。
  }
  win.history.replaceState(null, "", cleaned);
  return true;
}

/** 启动握手：注册接收器 → K2 桥 → K3 领取 → 旧 ?boot= 兼容。 */
export async function runBootHandshake(win = window) {
  registerBootReceiver(win);
  const ticket = await takeFromBridge(win);
  if (ticket) {
    try {
      await exchangeBootTicket(ticket);
      return true;
    } catch (_) {
      // 票据已过期/已消费：继续尝试 K3 与兼容分支
    }
  }
  try {
    await claimBootSession();
  } catch (_) {
    // 409 NoPendingGrant / 401 GrantExpired：用户直接开浏览器，属正常情形
  }
  return consumeLegacyQueryTicket(win);
}
