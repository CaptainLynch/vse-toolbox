// 启动握手（C7 本机安全契约，W16-03 → DSH-V2-03 → DSH-V2-04）。
//
// 票据/授权有三条**不经过地址栏**的通道（契约 §5.2）：
//   K2 宿主注入：pywebview 的 js_api 桥 take_boot_ticket() → POST boot-exchange；
//   K3 预置授权：启动器用启动器密钥预置一次性授权 → 页面 POST boot-claim 领取会话；
//   K5 会话恢复：12 小时过期后由窗口标记（vse_window）→ POST session-recover。
// 旧启动器（2.3.x）的 `?boot=` 只在 `capabilities.legacyBootQuery === true` 时读取：
// 能力探测是只读 GET，带 `referrerPolicy: "no-referrer"`（票据不随 Referer 外泄）；
// 探测确认走兼容分支后**先**同步取票 + history.replaceState 清理地址栏，**再**发出
// claim / exchange 等携带会话语义的请求——票据不进入历史、Referer 或日志。
// 握手失败不阻塞页面：返回明确失败状态并派发 `vse:boot-failed`，外壳展示可恢复提示
//（重试 / 从开始菜单重新打开）；会话缺失时写操作由服务端 fail-closed 拒绝。

const BOOT_QUERY_KEY = "boot";
const BOOT_EXCHANGE_ENDPOINT = "/api/security/boot-exchange";
const BOOT_CLAIM_ENDPOINT = "/api/security/boot-claim";
const SESSION_RECOVER_ENDPOINT = "/api/security/session-recover";
const CAPABILITIES_ENDPOINT = "/api/security/capabilities";

/** 启动握手失败事件：外壳据此展示「重试 / 从开始菜单重新打开」横幅。 */
export const BOOT_FAILURE_EVENT = "vse:boot-failed";
/** 本机回环请求硬超时：超时按失败反馈，绝不让首屏静默卡在「无会话」状态。 */
export const BOOT_REQUEST_TIMEOUT_MS = 8000;

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

/**
 * 旧启动器兼容：从地址栏取票并**立即**清理（同步，不产生任何网络请求）。
 * 返回取到的票据；地址栏没有票据时返回 null。清理失败（极少数受限文档）时仍返回
 * 票据——票据单次有效且 10 秒过期，不因清理失败丢掉唯一一次交换机会。
 */
export function takeUrlBootTicket(win = window) {
  const search = (win.location && win.location.search) || "";
  const ticket = extractBootTicket(search);
  if (!ticket) return null;
  const rest = stripBootTicket(search);
  const cleaned = win.location.pathname + (rest || "") + (win.location.hash || "");
  try {
    win.history.replaceState(null, "", cleaned);
  } catch (_) {
    // 受限文档不允许改历史：继续交换，但这是唯一残留窗口。
  }
  return ticket;
}

function makeTimeoutError() {
  const failure = new Error("启动握手超时，请重试或从开始菜单重新打开 VSE Toolbox");
  failure.type = "Timeout";
  failure.status = 0;
  return failure;
}

function makeNetworkError(cause, fallbackMessage) {
  const failure = new Error(
    (cause && cause.message) || fallbackMessage || "无法连接本机服务，请重试或从开始菜单重新打开 VSE Toolbox",
  );
  failure.type = "NetworkError";
  failure.status = 0;
  return failure;
}

async function postJson(path, body, fallbackMessage) {
  const controller = typeof AbortController === "function" ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), BOOT_REQUEST_TIMEOUT_MS) : null;
  let response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body || {}),
      credentials: "same-origin",
      // 地址栏可能还留着旧票据：本机请求一律不带 Referer。
      referrerPolicy: "no-referrer",
      signal: controller ? controller.signal : undefined,
    });
  } catch (cause) {
    if (cause && cause.name === "AbortError") throw makeTimeoutError();
    throw makeNetworkError(cause, fallbackMessage);
  } finally {
    if (timer !== null) clearTimeout(timer);
  }
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
  const controller = typeof AbortController === "function" ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), BOOT_REQUEST_TIMEOUT_MS) : null;
  try {
    const response = await fetch(CAPABILITIES_ENDPOINT, {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
      cache: "no-store",
      // 地址栏可能还有旧票据：探测请求绝不带 Referer（票据不进服务端访问日志）。
      referrerPolicy: "no-referrer",
      signal: controller ? controller.signal : undefined,
    });
    if (!response.ok) return null;
    const payload = await response.json();
    return payload && payload.ok === true ? payload.data : null;
  } catch (_) {
    return null; // 旧 app（404）、超时或探测失败：一律按旧 app 处理
  } finally {
    if (timer !== null) clearTimeout(timer);
  }
}

/** 失败状态（不含票据）：`{status:"failed", source, error:{type,message,status}}`。 */
function failureDetail(source, error) {
  return {
    status: "failed",
    source,
    error: {
      type: (error && error.type) || "unknown",
      message: (error && error.message) || "启动票据交换失败，请重试或从开始菜单重新打开 VSE Toolbox",
      status: (error && error.status) || 0,
    },
  };
}

/** 把失败状态交给外壳（事件只带状态与文案，绝不含票据）。 */
function reportBootFailure(win, source, error) {
  const detail = failureDetail(source, error);
  try {
    if (win && typeof win.dispatchEvent === "function") {
      const event =
        typeof win.CustomEvent === "function"
          ? new win.CustomEvent(BOOT_FAILURE_EVENT, { detail })
          : { type: BOOT_FAILURE_EVENT, detail };
      win.dispatchEvent(event);
    }
  } catch (_) {
    // 提示是尽力而为：事件失败绝不影响首屏与会话判定。
  }
  return detail;
}

/**
 * K2 宿主接收器：注册 `window.__vseBootReceiver(ticket)`（幂等），返回 `true` 供旧式
 * 宿主探测。收到票据后立即自删并交换会话——票据只在这个闭包里存在一次；交换失败
 * 派发失败事件，由外壳给出可恢复提示。
 */
export function registerBootReceiver(win = window) {
  if (typeof win.__vseBootReceiver === "function") return win.__vseBootReceiver;
  const receiver = (ticket) => {
    delete win.__vseBootReceiver;
    if (typeof ticket !== "string" || !ticket) return false;
    exchangeBootTicket(ticket).catch((error) => reportBootFailure(win, "bridge", error));
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

async function attemptLegacyExchange(win, ticket) {
  try {
    await exchangeBootTicket(ticket);
    return { status: "ok", source: "legacy", error: null };
  } catch (error) {
    return reportBootFailure(win, "legacy", error);
  }
}

/**
 * 旧启动器兼容分支（保留 03 的导出名）：仅当 legacyBootQuery 为 true 且地址栏含
 * 票据时取票、清理、交换。交换失败返回 false（不返回伪成功）并派发失败事件。
 */
export async function consumeLegacyQueryTicket(win = window) {
  const capabilities = await fetchCapabilities();
  if (!capabilities || capabilities.legacyBootQuery !== true) return false;
  const ticket = takeUrlBootTicket(win);
  if (!ticket) return false;
  const result = await attemptLegacyExchange(win, ticket);
  return result.status === "ok";
}

/**
 * 完整握手，返回明确状态（`ok` / `none` / `failed`）：
 * - `ok`：拿到会话（bridge / claim / legacy 任一通道）；
 * - `none`：没有任何票据或预置授权（用户直接开浏览器，属正常情形）；
 * - `failed`：确实出示过票据/授权但交换失败——不得伪装成功，同时已派发失败事件。
 */
export async function runBootHandshakeDetailed(win = window) {
  registerBootReceiver(win);

  // 1) K2：宿主注入的票据（不经过地址栏），优先且不需要能力探测。
  const bridgeTicket = await takeFromBridge(win);
  let bridgeError = null;
  if (bridgeTicket) {
    try {
      await exchangeBootTicket(bridgeTicket);
      // 同时出现的旧式 ?boot= 票据也从地址栏清掉（不交换、不留在历史里）。
      takeUrlBootTicket(win);
      return { status: "ok", source: "bridge", error: null };
    } catch (error) {
      bridgeError = error; // 继续尝试 K3 / 兼容分支
    }
  }

  // 2) 能力探测：只读 GET、不依赖票据，且不带 Referer（地址栏可能还有旧票据）。
  const capabilities = await fetchCapabilities();
  const legacyEnabled = Boolean(capabilities && capabilities.legacyBootQuery === true);

  // 3) 旧启动器兼容：取票 → 立即清理地址栏 → 之后才发 claim / exchange 请求。
  const legacyTicket = legacyEnabled ? takeUrlBootTicket(win) : null;

  // 4) K3：领取启动器预置的一次性授权；409 属正常（用户直接开浏览器）。
  let claimError = null;
  try {
    await claimBootSession();
    return { status: "ok", source: "claim", error: null };
  } catch (error) {
    if (!(error && error.status === 409)) claimError = error;
  }

  // 5) 旧 ?boot= 兼容交换：失败必须返回明确失败状态（不返回伪成功）。
  if (legacyTicket) return attemptLegacyExchange(win, legacyTicket);

  if (bridgeError) return reportBootFailure(win, "bridge", bridgeError);
  if (claimError) return reportBootFailure(win, "claim", claimError);
  return { status: "none", source: "none", error: null };
}

/** 启动握手：注册接收器 → 能力探测 → 兼容取票清理 → K2 桥 → K3 领取。 */
export async function runBootHandshake(win = window) {
  const result = await runBootHandshakeDetailed(win);
  return result.status === "ok";
}
