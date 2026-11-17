# 启动票据传递与安全重开窗口：最小修复契约

> **状态：已批准（主控，2026-11-01）**——§11 八项裁决全部采纳“建议”列（见 §11 末“主控裁决记录”）；DSH-V2-03 以本文为唯一实现依据。
> **基线提交：`1619141`**（`refactor/ux-v2` 当前 HEAD，已含第 0/1 波、DSH-V2-47 启动器修复、DSH-V2-01 本机安全集成测试）
> **适用任务：DSH-V2-03（实现方）**；本文件由主控审阅批准后方可作为实现依据。
> **风险等级：high**；`dispatch_gate = lead_design_and_approval`。
> **本文档不改任何代码。** 文内一切“应/必须”均为待实现条款，**不表示已实现、不表示已验证**。
> 所有示例均为合成值（`tok_EXAMPLE`、`grt_EXAMPLE`、`9f2c0d7a4b1e6c33`、`127.0.0.1:51234`），不含任何真实凭据、令牌、内部域名或用户名。
> 关联文档：[CONTRACTS.md](CONTRACTS.md)（C7 本机安全与启动）、[RELEASE_MATRIX.md](RELEASE_MATRIX.md)（发布矩阵）。

## 0. 证据基线（本文档与现状一致性的依据）

本契约的每条“现状”断言都来自下列文件的当前内容（基线 `1619141`）：

| 文件 | 读取的锚点 |
|---|---|
| `web/security.py` | `SESSION_COOKIE_NAME`/`SESSION_TTL_SECONDS=12*3600`/`BOOT_TICKET_TTL_SECONDS=10`/`BOOT_EXCHANGE_PATH`（L34-38）；`_security_error`（L41-44）；`BootTicketStore`（L47-67）；`LocalSessionStore`（L70-94）；`LocalWebSecurity`（L97-161）；`install_local_security`（L164-173）；`install_security_aware_test_client`（L177-247） |
| `web/app.py` | `_enforce_local_web_access`（L263-295）；`create_app(..., boot_token=...)`（L346-395），`app.before_request(_enforce_local_web_access)` 在 L389、`install_local_security` 在 L395 |
| `web/crawler_boot.py` | `_loopback_hostname`（L215-227）、`_origin_tuple`（L230-250）、`_local_web_mutation_error`（L253-276） |
| `vse_boot/supervisor.py` | `spawn_app`（L82-112）；`run_window`（L233-256）；`spawn_window`（L259-276）；`open_window`（L304-350）；`_open_edge_or_browser`（L353-363）；`InstanceLock`/`_OWNER_LOCKS`（L371-431）；`run`/`_show_existing`（L465-487）；`_loop`（L504-534）；`_boot`（L536-581）；`_serve`（L607-636） |
| `vse_boot/layout.py` | `instance_file`/`restart_request`/`quit_request`/`lock_file`（L49-62） |
| `webui.py` | 开发态自签票据 + `?boot=` 开浏览器（L157-192） |
| `web/static/host/boot-exchange.js` | `extractBootTicket`/`stripBootTicket`/`runBootExchange`（L9-50） |
| `web/static/host/shell.js` | `runBootExchange().finally(() => startShell())`（L131-134） |
| `web/static/host/api.js` | 401 文案“本地会话已失效，请关闭窗口后重新打开”（L16-21） |
| `tests/test_local_security.py` | 8 组 C7 断言（含 L233-293 启动链、L296-339 前端 Node 夹具） |
| `tests/test_local_security_integration.py` | 5 个真实 HTTP 场景（L248-415） |
| `tests/test_vse_boot_window.py` | C1-C5 窗口/降级/端口/自启断言（L119-641） |
| `tests/test_vse_boot_supervisor.py` | 启动/回滚/单实例断言 |
| `tools/e2e_v2_test_install.py` | `boot_exchange(instance)` 依赖 `instance.json.bootToken`（L87-102） |

---

## 1. 摘要

现状把**一次性启动票据放进 URL 查询串**，并把**票据明文写进 `state/instance.json`**；第二实例重开窗口时复用那张早已单次消费/10 秒过期的 URL，12 小时会话过期后也没有任何受控恢复路径。

本契约把“票据传递”从 **URL** 改为三条不经过地址栏的通道：

1. **宿主注入**（pywebview 窗口）：启动器向 app 申请一张 10 秒单次票据，经**继承的环境变量**交给窗口子进程，窗口经 pywebview `js_api` 桥交给页面，页面 `POST /api/security/boot-exchange` 换会话；票据从不进 URL、argv、历史、Referer、日志。
2. **预置授权 + 领取**（Edge app / 默认浏览器，无注入通道）：启动器用**只存在于 app 子进程环境里的启动器密钥**调用 `POST /api/security/window-grant` 预置一张 10 秒单次**授权**（不含票据），随后打开 `http://127.0.0.1:<port>/`；页面在严格同源条件下 `POST /api/security/boot-claim` 领取会话。
3. **一次性私有文件**（自动化工具，opt-in）：启动器把刚签发的票据写入 `state/boot-handoff.json`（10 秒后自删），供本机自动化脚本换取会话；默认关闭。

并新增两条恢复路径：**第二实例不再复用旧 URL**，而是写 `state/window.request` 请求长驻启动器（唯一持有实例锁与密钥的进程）重新签发授权并开窗；**12 小时会话过期**由窗口标记 Cookie + `POST /api/security/session-recover` 一键恢复，标记失效时引导用户从启动器重开。

`instance.json` 删除 `bootToken`，`url` 只保留 `http://127.0.0.1:<port>/`。

---

## 2. 现状与缺陷

### D1 票据进入 URL 查询串（历史 / 进程列表 / Referer / 日志）

| 位置 | 事实 |
|---|---|
| `vse_boot/supervisor.py:611` | `url = f"http://127.0.0.1:{port}/?boot={boot_token}"` |
| `vse_boot/supervisor.py:270-272` | 窗口子进程命令行 `--window <url> --profile <dir>`，票据随 URL 进入 argv，本机进程列表可见 |
| `vse_boot/supervisor.py:359` | Edge 降级 `--app={url}`，同上 |
| `vse_boot/supervisor.py:251-254` | `run_window` 只在异常时把 URL 替换成 `<url>` 再写 stderr；argv 与浏览器历史里仍是明文票据 |
| `webui.py:186` | 开发态 `f"{url}?boot={boot_token}"` 交给浏览器 |
| `web/static/host/boot-exchange.js:37-48` | 从 `location.search` 取票、`history.replaceState` 清除；清除前票据已进入历史、Referer 与任何中间日志 |
| `vse_boot/supervisor.py:613-614` | `instance.json` 同时写 `url`（带票）与 `bootToken`（明文） |

### D2 `instance.json` 明文票据 + 第二实例复用旧 URL

| 位置 | 事实 |
|---|---|
| `vse_boot/supervisor.py:480-487` | `_show_existing` 读 `instance.json["url"]` 直接开窗——那张票据早已被首窗消费或超过 10 秒 |
| `web/security.py:57-67` | `BootTicketStore.consume` 单次 + TTL，消费后 `_consumed=True` 永久拒绝 |
| `vse_boot/supervisor.py:559-561` + `web/security.py:54` | 票据值在 `spawn` 之前生成，TTL 从 app 子进程构造 `BootTicketStore` 时（`_issued_at`）起算；store 构造之后若健康检查仍有较长延迟（上限 `HEALTH_TIMEOUT_SECONDS=45.0`），窗口真正打开时票据可能已过期（**现存潜伏缺陷**） |
| `web/security.py:70-94` | 会话只在内存、per-app；新 profile / 无 Cookie 的浏览器窗口拿到会话的唯一途径就是那张票据 |
| `tools/e2e_v2_test_install.py:87-102` | 本机自动化工具直接依赖 `instance.json.bootToken` 换取会话 |

结论：新窗口（尤其新 profile、无会话 Cookie）**无法建立会话**，写操作全部 `401 SessionRequired`，用户只能看到失败提示。

### D3 12 小时会话过期后无受控恢复路径

| 位置 | 事实 |
|---|---|
| `web/security.py:35` | `SESSION_TTL_SECONDS = 12 * 3600`，固定 TTL，无滑动、无续期 |
| `web/security.py:78-94` | 会话记录只增不减（过期项仅在 `validate` 命中时删除）；无“换一张新会话”的入口 |
| `web/static/host/api.js:17` | 401 文案“本地会话已失效，请关闭窗口后重新打开 VSE Toolbox” |
| `web/security.py:113-133` | 唯一能发会话的端点是 `boot-exchange`，它要求一张**尚未消费且未过期**的票据——过期后不存在任何合法途径 |

### D4 “签发新票据”的入口必须认证（**前瞻约束**）

现状**不存在**未认证的签发入口：票据由启动器在进程内生成、经环境变量下发，页面无法调用。但 D2/D3 的修复必然引入“让长驻启动器/页面再拿一张票据”的入口，一旦该入口只凭“请求来自 127.0.0.1”就签发，本机任意页面或任意进程都能换取会话。本契约因此把下列四点列为**冻结条款**（见 §5.11、§6）：

| 位置 | 现状风险点 |
|---|---|
| `web/security.py:113-133` | `boot-exchange` 只校验票据，无速率限制、无失败计数；被爆破时只受 10 秒 TTL 保护 |
| `web/security.py:139-140` | `boot-exchange` 显式豁免会话与 Origin 判定（合理，但意味着该端点的全部防线就是票据本身） |
| `web/app.py:263-295` | 既有 loopback/Host/`Sec-Fetch-Site`/Origin 守卫只拦“明显跨站”，同机其他端口的页面仍可能发起请求 |
| `web/crawler_boot.py:253-276` | 同上；写路由另有 `local_guard`，但新端点若不接 `local_guard` 就会漏 |

---

## 3. 目标与非目标

### 目标

1. 票据与授权**不出现在 URL 查询串、argv、浏览器历史、Referer、日志**。
2. `instance.json` **不再含任何票据/密钥**；只保留可公开的本机连接信息。
3. 无会话的新浏览器窗口（新 profile、清空 Cookie）与 12 小时过期，都有**受控、一键**的恢复路径。
4. 任何“签发/预置”入口都必须**认证 + 来源校验 + 速率限制 + 重放拒绝**。
5. 接口、字段、状态、错误码、兼容策略**一次冻结**，DSH-V2-03 按此实现，不再改协议。
6. 旧启动器 + 新 app、新启动器 + 旧 app 两个方向都有明确降级路径，且“启动器改动必须整包发布”。

### 非目标（明确不做）

- 不做多用户/远程访问；仍只监听 loopback。
- 不改 C7 的企业凭据（DPAPI）通道，不动 `core/credential_provider`。
- 不引入 OS 沙箱、不做进程间命名管道的完整 IPC 框架（仅在裁决项里评估）。
- 不改写包签名/信任链（仍 TEST-ONLY）。
- 不修 `web/security.py` 的会话内存只增不减（另案，见 §11-8）。
- 不改任何既有写路由的语义、路径、状态码（C8）。

---

## 4. 威胁模型

| 编号 | 对手 | 能力 | 本契约的处置 | 残余风险 |
|---|---|---|---|---|
| T1 | **其他 OS 用户** | 无本用户令牌 | loopback 绑定 + 安装根在用户目录 + 进程隔离；app 只接受 `remote_addr` 为回环的请求 | 无（若安装根被放到共享目录，属部署错误，见 §11-1） |
| T2 | **同用户其他进程** | 可读本用户进程环境块、可读 `state/`、可用 DPAPI 解密浏览器 Cookie 库、可伪造任意 HTTP 头 | 票据不进 argv/URL/日志；启动器密钥只在 app 子进程环境、不落盘；票据/授权单次 + 10 秒 TTL；`boot-claim` 需先由持密钥方预置授权 | **存在**：同用户进程仍可读环境块或解密浏览器 Cookie。这是“同用户 = 同权限”的固有上限，本契约只缩小窗口与可见面，不宣称消除（见 §11-4） |
| T3 | **本机其他端口上的网页**（另一 origin） | 可发跨源请求、可读自身 origin 的 Cookie | `Host` 必须回环；写操作与全部新端点要求 `Origin` **严格等于**本 app 的 `scheme://host:port`；`Sec-Fetch-Site` 必须 `same-origin`；Cookie `SameSite=Strict`；无 CORS 通配 | 无（跨源读响应被浏览器阻断） |
| T4 | **互联网网页 / DNS rebinding** | 可诱导浏览器访问 `http://<攻击域>` 指向 127.0.0.1 | 既有 `_enforce_local_web_access` 校验 `Host` 为回环；本契约不改该层，新端点全部在其之后注册 | 无（Host 非回环直接 403） |
| T5 | **本机自动化脚本（合法工具）** | 本用户权限 | 显式 opt-in 的 `state/boot-handoff.json`（10 秒、单次、默认关闭） | 与 T2 同源，属已知接受项 |

**信任边界**：`vse_boot`（启动器进程族）与 app 子进程之间共享“本次启动”的秘密（环境变量）；浏览器页面只能通过**预置授权**或**宿主注入的票据**跨过边界。页面与 app 之间除会话 Cookie 与窗口标记 Cookie 外，不存在任何长期共享秘密。

---

## 5. 设计

### 5.1 术语

| 术语 | 定义 |
|---|---|
| **启动票据（ticket）** | app 签发的一次性随机串（32 字节 urlsafe），TTL 10 秒，单次消费；唯一用途是 `POST /api/security/boot-exchange` |
| **窗口授权（grant）** | app 在**启动器密钥认证**下预置的一次性凭据（`grantId`，TTL 10 秒，单次）；唯一用途是 `POST /api/security/boot-claim` |
| **启动器密钥（launcher secret）** | 启动器每次 spawn app 子进程时生成的 32 字节随机串，**只**经环境变量进入 app 子进程，不落盘、不进 argv、不进日志；用于 `POST /api/security/window-grant` |
| **会话（session）** | 现有 `vse_session` Cookie，12 小时，内存态，重启失效 |
| **窗口标记（window marker）** | 新增 `vse_window` Cookie，仅用于“一键恢复会话”；服务端内存态，重启失效 |
| **epoch** | app 每次启动生成的 8 字节十六进制随机串，标识“本次进程生命周期”；会话/标记/授权/票据都绑定 epoch |
| **长驻启动器（owner launcher）** | 持有 `state/instance.lock` 的启动器进程（`_OWNER_LOCKS`，`supervisor.py:371-387`）；只有它能签发/预置 |
| **第二实例** | 拿不到实例锁的启动器进程，只负责唤起已有窗口（`supervisor.py:465-487`） |

### 5.2 通道总览

| 通道 | 场景 | 载体 | 是否新增 | 认证方 |
|---|---|---|---|---|
| K1 | 启动器 → app 子进程（票据种子 + 启动器密钥） | **继承的环境变量**（`subprocess` `env=`，不用 argv） | 扩展 | 进程创建关系 |
| K2 | app → pywebview 页面（票据） | 环境变量 → 窗口子进程 → pywebview `js_api` 桥 | 新增 | 票据（单次 + 10s） |
| K3 | app → Edge/默认浏览器页面（会话） | 启动器预置授权 → 页面同源领取 | 新增 | 启动器密钥 + 授权 |
| K4 | 第二实例重开窗口 | `state/window.request` 文件 → owner launcher 重新签发 | 新增 | owner 身份（实例锁 + 密钥） |
| K5 | 12 小时过期恢复 | 窗口标记 Cookie → `POST /api/security/session-recover` | 新增 | 标记 Cookie + 同源 |
| K6 | 自动化工具（opt-in） | `state/boot-handoff.json`（10s，单次，默认关闭） | 新增 | 文件可见性（同用户） |
| — | 旧启动器（2.3.x）→ 新 app | 保留 `?boot=` 兼容读取（可关闭） | 保留 | 票据 |

### 5.3 通道 K1：启动器 → app 子进程

冻结：

- `spawn_app` **不得**再写 `os.environ`；改为构造 `env_overrides: dict[str,str]` 传给 `subprocess.Popen(env=...)`。理由：现在 `supervisor.py:560` 的 `os.environ["VSE_BOOT_TOKEN"] = ...` 会把票据泄漏给启动器自身及**它随后创建的所有子进程**（包括窗口子进程与 Excel worker）。
- app 子进程环境新增：`VSE_LAUNCH_SECRET=<32B urlsafe>`、`VSE_LEGACY_BOOT_QUERY=0`。
- 保留 `VSE_BOOT_TOKEN`：旧 app 只认它（配合 `?boot=`），因此**旧 app 分支**仍必须下发；新 app 把它注册为**首张票据**（10 秒 TTL），仅服务旧启动器兼容路径，新链路不使用它。
- 时间预算：票据 TTL 从 **app 侧签发时刻**起算。新链路在健康检查通过后才签发（`_serve` 内），窗口在 1-2 秒内打开，票据必然有效；旧链路（`?boot=`）的 TTL 从 app 启动起算，健康检查接近 `HEALTH_TIMEOUT_SECONDS=45` 的慢启动会撞上过期——这是现状行为，**不得**用放大 TTL 规避（否则“单次 + ≤10 秒”的冻结条款失效）。
- 窗口子进程（`spawn_window`）只额外获得 `VSE_WINDOW_BOOT_TICKET`，**绝不**获得 `VSE_LAUNCH_SECRET`。
- 注入完成后窗口子进程立即 `os.environ.pop("VSE_WINDOW_BOOT_TICKET", None)`（纵深防御）。

### 5.4 通道 K2：pywebview 宿主注入（首选，无需任何让步）

时序（`tok_EXAMPLE`，端口 `51234`）：

1. 启动器健康检查通过后，用 `X-VSE-Launch-Secret` 调 `POST /api/security/window-grant`，`{"purpose":"open","delivery":"env"}` → `200 {"grantId":"grt_EXAMPLE","ticket":"tok_EXAMPLE","expiresAt":…,"ttlSeconds":10}`。
2. 启动器 `spawn_window(url="http://127.0.0.1:51234/", profile, env={"VSE_WINDOW_BOOT_TICKET":"tok_EXAMPLE"})`——**URL 无查询串**，argv 无秘密。
3. 窗口子进程 `run_window`：`create_window("VSE Toolbox", url, js_api=BootBridge(ticket))`；`BootBridge.take_boot_ticket()` 首次调用返回票据，之后返回 `None`（单次），并立即从 `os.environ` 清除。
4. 页面 `boot-exchange.js` 检测 `window.pywebview?.api?.take_boot_ticket`（pywebview 就绪后）：取票 → `POST /api/security/boot-exchange` → 拿会话 → 桥端票据置空。
5. 若桥不可用（浏览器、Edge 模式、pywebview 版本不支持 `js_api`）：页面走 K3。

约束：

- `run_window` **不打印**票据；异常信息沿用现有 `<url>` 替换（`supervisor.py:251-254`）。
- 桥只在窗口生命周期内存在；窗口关闭即消失。
- 票据未消费则 10 秒后自然过期；`_serve` 不因未消费重试（避免延长 TTL）。

### 5.5 通道 K3：浏览器预置授权 + 同源领取

时序：

1. 启动器判定将走 Edge/默认浏览器（`open_window` 的 `find_webview()` 为假或 `spawn_window` 抛 `OSError`）后，调 `POST /api/security/window-grant`，`{"purpose":"open","delivery":"claim"}` → `200 {"grantId":"grt_EXAMPLE","expiresAt":…,"ttlSeconds":10}`（**响应不含票据**）。
2. 启动器打开 `http://127.0.0.1:51234/`（Edge：`--app=` + 独立 `--user-data-dir`；否则默认浏览器）。
3. 页面外壳启动时 `POST /api/security/boot-claim`（空 body）。app 校验：`Host` 回环、`Origin` 严格同源、`Sec-Fetch-Site: same-origin`、存在未过期的 `delivery="claim"` 授权且未被消费 → 发 `vse_session` + `vse_window` Cookie，并把授权标记 `claimed`。
4. 若已有有效会话：`200 {"exchanged":false,"sessionValid":true}`，**不消费**授权（避免刷新页面把授权烧掉）。
5. 无授权（用户直接双击书签、或授权已过期）：`409 NoPendingGrant`。页面照常加载，写操作 401 → 显示恢复横幅（§5.8）。

为什么这样做是安全的（对应 T3/D4）：一个“本机其他端口上的页面”发起 `fetch` 时 `Origin` 是它自己的 origin，严格同源校验直接 403；它也无法读取本 app 的响应或 Cookie（`SameSite=Strict` + 无 CORS 通配）。授权本身由**只存在于 app 子进程环境的密钥**认证签发，页面无法自行预置。

残余风险（同用户非浏览器进程）：在授权存活的 ≤10 秒内伪造 `Origin`/`Sec-Fetch-Site` 并抢先领取。已在 T2 记录，并在 §11-4 提请裁决（可选缓解：第二实例/恢复路径改为“托盘确认后预置”）。

### 5.6 通道 K4：第二实例重开窗口（无会话新窗口的受控恢复）

冻结流程：

1. 第二实例 `run()` 拿不到实例锁 → 不再读 `instance.json["url"]` 直接开窗。
2. 写 `state/window.request`：`{"purpose":"open","requestedAt":<unix ms>,"nonce":"<16B hex>"}`（原子写：写 `.tmp` 再 `os.replace`），然后**最多等待 8 秒**观察该文件是否被 owner 删除：被删除即视为 owner 已接手开窗，返回 `0`。
3. owner launcher 的 `_serve` 轮询（现有 0.5 秒循环，`supervisor.py:618-633`）新增一个分支：发现 `window.request` → 删除该文件 → 按 `open_window` 将要采用的模式（`find_webview()` 结果）签发 `delivery="env"` 或 `delivery="claim"` 授权 → 开窗。
4. 兜底：8 秒后文件仍在（owner 已死或卡住），第二实例直接打开 `http://127.0.0.1:<port>/`（无票据），页面显示“需要启动器授权”横幅（§5.8）并给出“重新打开 VSE Toolbox”指引；**不得**回退到复用旧票据或旧 URL。
5. `_boot` 开头（`supervisor.py:537-539` 同一处）删除陈旧的 `window.request`，防止历史请求被误执行。

为什么第二实例能证明“是同一用户的启动器”：它不直接向 app 要票据——**它根本拿不到启动器密钥**（密钥只在 owner launcher 内存与 app 子进程环境里）。它只能通过安装根下的 `state/window.request` 请求 owner；owner 是持有实例锁的进程，其身份由 OS 文件锁与进程创建关系保证。

`state/window.request` 的权限：**不新增任何 ACL 操作**（遵守 DSH-V2-47 约束），依赖安装根（`%LOCALAPPDATA%\VSE-Toolbox`）继承的当前用户私有 ACL；内容不含秘密，被同用户进程读取无价值。

### 5.7 通道 K6：自动化工具的一次性文件（opt-in）

- 触发：自动化脚本以 `VSE_BOOT_HANDOFF=1` 启动**启动器**；该模式下启动器在开窗之前**总是**额外签发一张 `delivery="env"` 票据并写入 `state/boot-handoff.json`（与窗口最终走 pywebview 还是 Edge 无关，工具因此始终有票）：

  ```json
  {"ticket":"tok_EXAMPLE","expiresAt":1735689600,"pid":4321,"epoch":"9f2c0d7a4b1e6c33"}
  ```

- 生命周期：写入后由启动器的定时线程在 `ttl+5` 秒删除；`_boot` 开头删除陈旧文件；**不含启动器密钥**。
- 默认**不创建**（生产环境零残留）。
- 权限与 Windows 语义（必须写清，因 `os.chmod(0o600)` 在 Windows 上不生效）：
  - 方案 A（推荐、零新增 ACL 操作）：依赖安装根继承的 ACL（当前用户私有目录）。文档与代码都**不得**宣称“0600”。
  - 方案 B：写入后用 `icacls <file> /inheritance:r /grant:r "<当前用户>":F` 或 `SetSecurityInfo` 显式收紧 DACL。这属于**对新建文件的 ACL 操作**，DSH-V2-47 的“不改 ACL”只约束既有文件，但仍需主控裁决（§11-1）。
- `tools/e2e_v2_test_install.py` 必须改为读该文件（或走 K4 重开），**不得**再依赖 `instance.json.bootToken`；该文件不在本任务 owned_scope，列入 03 的连带改动（§9.3）。

### 5.8 通道 K5：12 小时会话过期的一键恢复

1. 任何写请求返回 `401 SessionRequired` 时，外壳显示横幅：**“本地会话已过期”** + 按钮**“恢复会话”**。
2. 点击 → `POST /api/security/session-recover`（空 body）。app 校验：`vse_window` 标记有效 + `Origin` 严格同源 + `Sec-Fetch-Site: same-origin` → 发新 `vse_session`（新的 12 小时）。横幅消失，用户重试原操作。
3. 标记不存在/已过期（新 profile、清过 Cookie、app 重启过）→ `401 SessionRecoveryUnavailable`，横幅文案切换为：**“本窗口无法自动恢复，请从开始菜单重新打开 VSE Toolbox”**（即走 K4）。
4. 恢复**不延长** `vse_window` 的绝对有效期（首次领取起 30 天）；30 天后必须经启动器重开。

Cookie 冻结属性：

| Cookie | 值 | 属性 | 服务端 TTL |
|---|---|---|---|
| `vse_session` | 32B urlsafe | `HttpOnly; SameSite=Strict; Path=/; Max-Age=43200`；loopback http **不设** `Secure`；不设 `Domain` | 12 小时（内存） |
| `vse_window` | 32B urlsafe | `HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000`；同样不设 `Secure`/`Domain` | 30 天（内存；app 重启即失效） |

### 5.9 `instance.json` 字段变更（冻结）

| 字段 | 现状 | 处置 | 说明 |
|---|---|---|---|
| `url` | 带 `?boot=<token>` | **改**：`http://127.0.0.1:<port>/` | 不再含查询串 |
| `bootToken` | 明文票据 | **删除** | 不得以任何兼容名回流；工具改走 K6 |
| `port` | 有 | 保留 | |
| `version` | 有 | 保留 | |
| `pid` | 有 | 保留 | |
| `supervisorPid` | 有 | 保留 | |
| `schemaVersion` | 无 | **新增**：`2` | 供工具判断字段集 |
| `startedAt` | 无 | **新增**：`2026-11-01T02:03:04Z`（UTC，秒级） | 便于判断“是否同一次启动” |
| `epoch` | 无 | **新增**：`9f2c0d7a4b1e6c33` | 与 capabilities/错误响应一致；用于提示“应用已重启” |
| `securityContract` | 无 | **新增**：`1` | 本契约版本 |
| `handoff` | 无 | **新增（条件）**：`"boot-handoff.json"` | 仅 `VSE_BOOT_HANDOFF=1` 时出现 |

读取方影响：app 自身**不读** `instance.json`；旧启动器只读 `url`（新启动器写的 `url` 无票据，旧 app 无法建会话——见 §8.1、§8.2 的版本组合约束）；`tools/e2e_v2_test_install.py` 读 `url`/`pid`/`bootToken` → 必须同步改造。

### 5.10 不再出现的载体与替代方案取舍

| 载体 | 现状 | 契约 |
|---|---|---|
| URL 查询串 `?boot=` | 有 | **新链路禁止**；仅“旧启动器 + 新 app”兼容读取（可关闭） |
| 进程 argv | 有（`--window <url>`、`--app=<url>`） | URL 无票据 → argv 无秘密 |
| 浏览器历史 / Referer | 有（`replaceState` 前已入史） | 无票据进入 URL → 无泄漏；另建议对 HTML 响应加 `Referrer-Policy: no-referrer`（纵深防御，非阻断项） |
| `instance.json` | 有明文 `bootToken` | 删除 |
| 日志 | 现有 `<url>` 脱敏 | 新增：票据/授权/密钥一律不入日志；`run_window` stderr 沿用 `<url>` 替换 |
| **URL 片段 `#boot=`** | 未使用 | **不采用**：仍进入 argv 与历史，只是不进服务端日志 |
| **路径段 `/boot/<tok>`** | 未使用 | **不采用**：进入服务端访问日志与历史，需服务端 302，清理更差 |
| **launcher 侧 bootstrap 网页** | 未使用 | **不采用**：跨源，需为启动器端口开白名单，扩大攻击面 |
| **预置浏览器 Cookie（改 Edge profile 库）** | 未使用 | **不采用**：DPAPI/格式耦合，脆弱且不可测 |
| **命名管道 / 本地 socket** | 未使用 | **不在最小修复内**：作为 §11-4 的候选加强项评估 |

### 5.11 认证与来源校验矩阵（冻结）

| 端点 | 认证 | 来源校验 | 重放 | 速率 |
|---|---|---|---|---|
| `POST /api/security/boot-exchange` | 票据（单次 + 10s） | 既有 loopback/Host/`Sec-Fetch-Site`/Origin 守卫（`web/app.py:263-295`）；**不额外要求** `Sec-Fetch-*`（自动化工具无此头） | 消费后一律 401 | 失败 ≥10 次/60s → 429 |
| `GET /api/security/capabilities` | 无（只读、无秘密） | 同上 | 不适用 | 不限制（只读） |
| `POST /api/security/window-grant` | `X-VSE-Launch-Secret` 常量时间比较 | `Origin` **必须存在**且严格等于本 app origin；Host 回环 | 每次调用签发新授权（旧授权被 supersede） | ≥6 次/60s → 429 |
| `POST /api/security/boot-claim` | 已预置且 `delivery="claim"` 的未消费授权 | `Origin` 严格同源 + `Sec-Fetch-Site: same-origin` + Host 回环 | 已消费/已 supersede/不存在 → 409 | ≥10 次/60s → 429 |
| `POST /api/security/session-recover` | `vse_window` 标记有效 | `Origin` 严格同源 + `Sec-Fetch-Site: same-origin` + Host 回环 | 可重复（幂等换新会话，旧会话不连带作废） | ≥6 次/60s → 429 |

补充冻结：

- 所有新端点响应 `Cache-Control: no-store`，错误信封沿用 `{ok:false,error:{type,message}}`（`web/security.py:41-44`）。
- `window-grant` 在未配置启动器密钥时（开发态未设置、或旧 app）一律 `401 LauncherAuthRequired`，**不存在**“无密钥即放行”的分支。
- 所有新端点在 `_enforce_local_web_access`（`web/app.py:389`）之后注册，顺序与现有 `install_local_security` 一致。
- **校验顺序**：`boot-claim` 与 `session-recover` 必须**先完成来源校验**（Host/Origin/`Sec-Fetch-Site`）**再消费**授权或标记，否则跨源请求会把凭证烧掉，退化成拒绝服务。`boot-exchange` 的消费以 `secrets.compare_digest` 值匹配为前提（不知道票据就无法烧掉），来源校验沿用全局守卫，不新增要求，因此既有 401 语义不变。

### 5.12 前端行为（冻结）

`web/static/host/boot-exchange.js` → 改名语义为“启动握手”，导出 `runBootHandshake()`：

1. 注册 `window.__vseBootReceiver(ticket)`（幂等；收到票据 → `POST boot-exchange` → 立即删除该全局），返回 `true`（供旧式宿主探测，可保留一个版本）。
2. 若 `window.pywebview?.api?.take_boot_ticket` 存在（或 `pywebviewready` 事件触发）→ 取票并交换（K2）。
3. 否则 `POST /api/security/boot-claim` 一次；`409/401` 静默忽略（正常：用户直接开浏览器）。
4. 兼容分支：仅当 `GET /api/security/capabilities` 的 `legacyBootQuery` 为 `true` **且** `location.search` 含 `boot` 时，才执行现有的取票 + `replaceState` 清理（`boot-exchange.js:37-48` 原逻辑），用于“旧启动器 + 新 app”。
5. `shell.js:131-134` 的 `runBootExchange().finally(() => startShell())` 改为**先注册接收器、立即 `startShell()`**，不再阻塞外壳渲染（现有测试断言需同步更新）。
6. 401 横幅与“恢复会话”按钮（§5.8）；`api.js:17` 文案改为“本地会话已失效”，把“怎么做”交给横幅按钮。

### 5.13 日志与脱敏

- 禁止进入日志/异常文本：票据、`grantId`、`vse_session`、`vse_window`、`VSE_LAUNCH_SECRET`、`VSE_WINDOW_BOOT_TICKET`。
- `boot-exchange` 失败只记 `type` 与计数，不记收到的值。
- `run_window` 的 stderr 继续把 URL 整体替换为 `<url>`；新增：任何异常文本先做票据子串替换再输出。
- 启动器日志（`state/app-last-run.log`）不得出现上述值；`spawn_app` 记录 banner 时不得回显 `env_overrides`。

---

## 6. 接口与错误码（冻结）

### 6.1 接口总表

| # | 方法 | 路径 | 认证 | 会话要求 | 新增 |
|---|---|---|---|---|---|
| 1 | `POST` | `/api/security/boot-exchange` | 票据 | 否 | 保留（语义不变，新增限流） |
| 2 | `GET` | `/api/security/capabilities` | 无 | 否 | **新增** |
| 3 | `POST` | `/api/security/window-grant` | 启动器密钥 | 否 | **新增** |
| 4 | `POST` | `/api/security/boot-claim` | 预置授权 | 否 | **新增** |
| 5 | `POST` | `/api/security/session-recover` | 窗口标记 | 否 | **新增** |

### 6.2 `GET /api/security/capabilities`

- 用途：启动器在健康检查后探测“这个 app 是否支持新链路”，据此选择新路径或旧 `?boot=` 路径；页面据此决定是否启用兼容读取。
- 响应 `200`：

  ```json
  {"ok": true, "data": {
    "contractVersion": 1,
    "grantArm": true,
    "windowInjection": true,
    "legacyBootQuery": false,
    "handoffFile": false,
    "ticketTtlSeconds": 10,
    "sessionTtlSeconds": 43200,
    "epoch": "9f2c0d7a4b1e6c33"
  }}
  ```

- 错误：`403 LocalAccessRequired` / `403 CrossSiteRequest`（既有守卫）。
- 冻结：`grantArm` 是**唯一**的路径选择开关；缺失该字段（旧 app 404）即视为不支持。

### 6.3 `POST /api/security/window-grant`

- 请求头：`X-VSE-Launch-Secret: <secret>`、`Origin: http://127.0.0.1:51234`、`Content-Type: application/json`。
- 请求体：`{"purpose": "open"|"reopen"|"recover", "delivery": "env"|"claim"}`。
- 响应 `200`：

  ```json
  {"ok": true, "data": {
    "grantId": "grt_EXAMPLE",
    "delivery": "env",
    "ticket": "tok_EXAMPLE",
    "expiresAt": 1735689600,
    "ttlSeconds": 10,
    "epoch": "9f2c0d7a4b1e6c33"
  }}
  ```

  `delivery="claim"` 时**不含** `ticket` 字段（键不存在，而非空串）。
- 副作用：最多保留 **1 张**待领取授权；新授权 supersede 旧授权（旧 `grantId` 立即失效）。
- 错误：`400 ValidationError`（`purpose`/`delivery` 非法）、`401 LauncherAuthRequired`、`403 OriginRequired`、`403 CrossSiteRequest`、`429 GrantRateLimited`。
- 不设置任何 Cookie。

### 6.4 `POST /api/security/boot-claim`

- 请求头：`Origin: http://127.0.0.1:51234`、`Sec-Fetch-Site: same-origin`、`Content-Type: application/json`。
- 请求体：`{}`。
- 响应 `200`（成功领取）：`{"ok":true,"data":{"exchanged":true,"sessionValid":true,"epoch":"9f2c0d7a4b1e6c33","sessionTtlSeconds":43200}}` + `Set-Cookie: vse_session=…` + `Set-Cookie: vse_window=…`。
- 响应 `200`（已有有效会话）：`{"ok":true,"data":{"exchanged":false,"sessionValid":true,"epoch":"…"}}`，不消费授权、不重设 Cookie。
- 错误：`409 NoPendingGrant`（不存在 / 已消费 / 已 supersede / `delivery="env"`）、`401 GrantExpired`、`403 OriginRequired`、`403 SameSiteRequired`、`403 CrossSiteRequest`、`429 ClaimRateLimited`。

### 6.5 `POST /api/security/session-recover`

- 请求头：`Origin`、`Sec-Fetch-Site: same-origin`、`Cookie: vse_window=…`。
- 请求体：`{}`。
- 响应 `200`：`{"ok":true,"data":{"recovered":true,"sessionTtlSeconds":43200,"epoch":"…"}}` + 新 `Set-Cookie: vse_session=…`（**不重设** `vse_window`）。
- 错误：`401 SessionRecoveryUnavailable`（标记缺失/过期/未知）、`403 OriginRequired`、`403 SameSiteRequired`、`403 CrossSiteRequest`、`429 RecoveryRateLimited`。

### 6.6 `POST /api/security/boot-exchange`（保留，响应体逐字冻结）

- 请求体：`{"token":"tok_EXAMPLE"}`。
- 成功响应 `200`，**响应体逐字不变**：`{"ok":true,"data":{"exchanged":true}}`（不得新增字段——`tests/test_local_security_integration.py:263` 是整包相等断言）。
- 成功响应新增：额外 `Set-Cookie: vse_window=…`（K5 的恢复凭据），并可选返回响应头 `X-VSE-Epoch: 9f2c0d7a4b1e6c33`（客户端不依赖它；启动器从 capabilities/`instance.json` 取 epoch）。
- 错误：`401 BootTicketInvalid`（无效/过期/已消费，**统一**不区分）、`429 BootExchangeRateLimited`、`400 ValidationError`。
- 冻结：不要求 `Sec-Fetch-*`（自动化工具）；不要求已有会话；不改变现有 401 语义与响应体（`tests/test_local_security.py` 的既有断言零改动继续成立）。

### 6.7 错误码表（冻结）

| 状态码 | `error.type` | 触发 | 前端处置 |
|---|---|---|---|
| 400 | `ValidationError` | 请求体字段非法 | 记日志，不重试 |
| 401 | `BootTicketInvalid` | 票据无效/过期/已消费 | 静默（后续 401 走横幅） |
| 401 | `SessionRequired` | 写操作无有效会话 | 显示“会话已过期 + 恢复会话”横幅 |
| 401 | `LauncherAuthRequired` | 启动器密钥缺失/不匹配/未配置 | 启动器记日志并降级为旧路径或提示 |
| 401 | `GrantExpired` | 授权超过 10 秒 | 页面静默；用户重开 |
| 401 | `SessionRecoveryUnavailable` | 标记缺失/过期/未知 | 横幅切换为“请从开始菜单重新打开” |
| 403 | `LocalAccessRequired` | 非回环 `remote_addr` 或非回环 `Host` | 既有行为，不变 |
| 403 | `OriginRequired` | 写/新端点缺 `Origin` | 提示在应用窗口内操作 |
| 403 | `SameSiteRequired` | `Sec-Fetch-Site` 非 `same-origin` | 同上 |
| 403 | `CrossSiteRequest` | `Origin`/`Sec-Fetch-Site` 跨站 | 同上 |
| 409 | `NoPendingGrant` | 无待领取授权（含重放/已 supersede/`delivery` 不匹配） | 静默；需要时走 K4 |
| 429 | `BootExchangeRateLimited` | 票据失败 ≥10 次/60s | 显示“请稍后再试” |
| 429 | `GrantRateLimited` | 预置 ≥6 次/60s | 启动器退避 |
| 429 | `ClaimRateLimited` | 领取 ≥10 次/60s | 静默 |
| 429 | `RecoveryRateLimited` | 恢复 ≥6 次/60s | 显示“请稍后再试” |

新增 `SameSiteRequired` 属 C8 允许的错误类型演进范围（`CONTRACTS.md` C8）；不新增、不改写任何既有业务路由的错误码。

### 6.8 环境变量 / 状态文件冻结表

| 名称 | 方向 | 内容 | 落盘 | 生命周期 |
|---|---|---|---|---|
| `VSE_BOOT_TOKEN` | 启动器 → app 子进程 | 票据（旧 app 必需） | 否 | 本次 app 进程；10 秒有效 |
| `VSE_LAUNCH_SECRET` | 启动器 → app 子进程 | 启动器密钥 | 否 | 本次 app 进程 |
| `VSE_LEGACY_BOOT_QUERY` | 启动器 → app 子进程 | `"0"` 关闭 `?boot=` 兼容读取 | 否 | 本次 app 进程 |
| `VSE_WINDOW_BOOT_TICKET` | 启动器 → 窗口子进程 | 票据（K2 注入用） | 否 | 窗口进程启动阶段，注入后立即清除 |
| `VSE_BOOT_HANDOFF` | 操作者 → 启动器 | `"1"` 启用 K6 文件 | 否 | 启动器进程 |
| `state/instance.json` | 启动器 → 所有读者 | §5.9 字段集（无秘密） | 是 | 启动器生命周期 |
| `state/window.request` | 第二实例 → owner | `{purpose,requestedAt,nonce}`（无秘密） | 是 | 被 owner 消费后删除；`_boot` 清理陈旧项 |
| `state/boot-handoff.json` | 启动器 → 自动化工具 | `{ticket,expiresAt,pid,epoch}` | 是（opt-in） | `ttl+5` 秒后自删 |

---

## 7. 状态机

### 7.1 票据（ticket）

```
(签发) --issue(ttl=10s)--> issued
issued --consume(值匹配且未超时)--> consumed
issued --超过 10s--> expired
consumed/expired --再次提交--> rejected（不改变状态，只返回 BootTicketInvalid）
```

- 存储：每实例一个 `BootTicketStore`，内部为 `dict[token] = issued_at`；最多 8 张，超出按最早过期淘汰。
- 冻结：`consumed` 与 `expired` 对外**不可区分**（同一 401 `BootTicketInvalid`）。

### 7.2 窗口授权（grant）

```
(空) --arm(delivery, ttl=10s)--> armed
armed --arm(新授权)--> superseded（旧 grantId 立即失效）
armed --claim(来源校验通过 且 delivery=claim 且未超时)--> claimed
armed --超过 10s--> expired
expired --claim--> 401 GrantExpired（过期项随即删除）
claimed/superseded --claim--> 409 NoPendingGrant
(空) --claim--> 409 NoPendingGrant
```

- 最多 1 张 `armed`；`claimed` 后不保留（`claimed` 只保留计数用于限流）。
- 冻结：`grantId` 从不回传给浏览器（页面不需要、也拿不到）。

### 7.3 会话（session）

```
(空) --exchange 或 claim 或 recover--> active(12h)
active --超过 12h--> expired
active --app 重启--> invalidated
expired/invalidated --写请求--> 401 SessionRequired
```

### 7.4 窗口标记（window marker）

```
(空) --exchange 或 claim--> active(30d，服务端内存)
active --recover--> 仍然 active（不续期、不重设 Cookie）
active --超过 30d 或 app 重启--> expired
expired --recover--> 401 SessionRecoveryUnavailable
```

### 7.5 第二实例 / 窗口请求

```
第二实例拿锁失败 --写 window.request--> pending
pending --owner 轮询发现--> handled（删除文件 + 签发授权 + 开窗）
pending --owner 已死 / 8s 超时--> abandoned（第二实例直接开 /，页面显示横幅）
pending --_boot 清理--> discarded
```

---

## 8. 兼容与发布

### 8.1 四象限

| 启动器 | app 包 | 行为 |
|---|---|---|
| 旧（2.3.x） | 旧（2.3.x） | 现状不变：`?boot=` + `instance.json.bootToken` |
| 旧（2.3.x） | **新（≥2.4.0）** | app 未收到 `VSE_LEGACY_BOOT_QUERY=0` → `capabilities.legacyBootQuery=true` → 前端走兼容分支（取 `?boot=` → 交换 → `replaceState` 清理）。**过渡期 D1/D2 风险仍在**（`instance.json` 仍由旧启动器写 `bootToken`、URL 仍带 `?boot=`），须尽快整包升级 |
| **新** | 旧（2.3.x） | `GET /api/security/capabilities` 404/无 `grantArm` → 启动器走**旧路径**：本地生成票据、`env` 下发、URL 附 `?boot=`、`instance.json` 写 `bootToken`（**仅此分支**）；窗口仍用 pywebview，但不做 `js_api` 注入 |
| **新** | **新** | 全通道；URL 无票据；`instance.json` 无票据 |

### 8.2 兼容的硬约束

1. `capabilities.grantArm` 是唯一开关；探测失败（超时/404/JSON 非法）一律按“旧 app”处理。
2. 旧路径的 `?boot=` 分支代码必须**逐字保留**现有语义（含 `instance.json.bootToken`），不得“顺手清理”。
3. 新 app 的 `boot-exchange` 语义不得收窄（`tests/test_local_security.py` 既有断言是回归门禁）。
4. `legacyBootQuery` 默认值 = `true`；只有启动器显式传 `VSE_LEGACY_BOOT_QUERY=0` 才为 `false`。**默认翻转（改为 `false`）必须是一次独立批准的变更**，不得随 03 一起改。

### 8.3 整包与发布要求（对应 RELEASE_MATRIX §2）

- 本契约同时改动 `vse_boot/`（启动器）与 `web/`（app 包）。**`vse_boot` 不随 app 包更新**，因此：
  1. **先发 app 包**（`vse-app-<semver>.vsepkg`，≥2.4.0，保持 `legacyBootQuery=true`）；
  2. **再发整包**（`VSE-Toolbox-v<semver>-test.zip`，onedir），整包内 `app/` 目录必须是 ≥2.4.0 的 app，避免长期停留在“新启动器 + 旧 app”降级路径；
  3. 整包发布前必须走真机验证（W17-02 口径）。
- 回滚：整包回滚 = 恢复旧 onedir（旧启动器 + 旧 app）→ 协议回到 `?boot=`。回滚后不得残留新状态文件：新启动器写的 `window.request`/`boot-handoff.json` 必须能被旧启动器忽略（旧启动器只认 `restart.request`/`quit.request`），并在新启动器下次 `_boot` 时清理。
- 不发布：本契约文档本身（纯文档）。
- 发布记录必须写明：版本、buildId、sha256、验证命令输出（矩阵硬规则 4）。

### 8.4 工具与测试的连带改动

- `tools/e2e_v2_test_install.py`：删除对 `instance.json.bootToken` 的依赖，改用 `state/boot-handoff.json`（以 `VSE_BOOT_HANDOFF=1` 启动启动器）或走 K4 重开。
- `tests/test_local_security.py:233-293`（断言 `?boot=` 与 `bootToken`）与 `:334-339`（断言 `runBootExchange().finally(...)`）必然失败，属**预期契约变更**，由 03 同步重写。
- `tests/test_local_security_integration.py:156-176` 的 `_ticket_from_launch_url` 需改为“从注入通道取票”。

---

## 9. DSH-V2-03 实现清单与测试清单

### 9.1 实现清单（按文件）

| # | 文件 | 改动 |
|---|---|---|
| 1 | `web/security.py` | `BootTicketStore` 改多票据（`issue/consume`，上限 8）；新增 `WindowGrantStore`、`WindowMarkerStore`、`RateLimiter`；新增 4 个视图（capabilities/window-grant/boot-claim/session-recover）；`install_local_security(..., launcher_secret=, accept_legacy_boot_query=)`；`boot-exchange` 增发 `vse_window`；`LocalWebSecurity.epoch` |
| 2 | `web/app.py` | `create_app` 透传 `launcher_secret`/`accept_legacy_boot_query`（保持 `boot_token` 参数兼容） |
| 3 | `web/static/host/boot-exchange.js` | `runBootHandshake()`：`__vseBootReceiver` + pywebview 桥 + claim + 兼容分支；删除无条件 URL 取票 |
| 4 | `web/static/host/shell.js` | 先注册接收器再 `startShell()`；401 横幅 + “恢复会话”按钮 |
| 5 | `web/static/host/api.js` | 401 文案改为“本地会话已失效” |
| 6 | `vse_boot/supervisor.py` | `spawn_app(env_overrides=)` 取代 `os.environ` 写入；`_boot` 生成 `launch_secret`；`_serve` 探测 capabilities → 选分支 → 签发票据/预置授权 → 写新 `instance.json` → 开窗；`open_window(..., broker=)`；`spawn_window(env=)`；`run_window` 建 `js_api` 桥并清理 env；`_show_existing` 写 `window.request` + 超时兜底；`_serve` 处理 `window.request`；`_boot` 清理陈旧状态文件 |
| 7 | `webui.py` | 开发态：自签票据 + 自签密钥 + 进程内 `arm_grant(delivery="claim")`，开浏览器时用 `http://host:port/`（无查询串） |
| 8 | `tools/e2e_v2_test_install.py` | 改用 handoff 文件（§8.4） |
| 9 | `docs/refactor-v2/CONTRACTS.md` | C7 增补三条（票据不落 URL/instance.json；授权需启动器密钥；窗口标记与一键恢复）——**由主控批准后修订** |

### 9.2 测试清单

| 文件 | 用例 |
|---|---|
| `tests/test_local_security.py` | 票据多张签发/单次/10s TTL；`capabilities` 字段与 `legacyBootQuery` 开关；`window-grant` 无密钥 401、密钥错 401、缺 Origin 403、跨源 403、限流 429、supersede 旧授权；`boot-claim` 无授权 409、过期 401、重放 409、`delivery="env"` 授权不可 claim、跨源 403、缺 `Sec-Fetch-Site` 403、已有会话 200 且不消费授权；`session-recover` 无标记 401、有标记 200 且不重设标记、跨源 403；`boot-exchange` 既有 8 组断言不回归 |
| `tests/test_local_security_integration.py` | 真实 HTTP：① 首窗领取会话后写放行；② 无授权时 claim 409 且写 401；③ 授权 10 秒后 401；④ claim 重放 409 且原会话不受影响；⑤ 12 小时过期 → recover 成功 → 写放行；⑥ 标记失效 → recover 401；⑦ 两实例票据/授权/会话不串味；⑧ 旧 `?boot=` 兼容路径在 `legacyBootQuery=true` 下仍可用 |
| `tests/test_vse_boot_supervisor.py` | `instance.json` 新字段集且**不含** `bootToken`、`url` 无 `?`；`spawn` 时 env 含 `VSE_LAUNCH_SECRET` 且启动器 `os.environ` 不含（不泄漏）；capabilities 探测失败 → 旧路径（URL 带票 + `bootToken`）；票据/授权签发发生在**健康检查之后**（注入时钟：健康等待 20 秒后签发的票据仍可用）；`window.request` 被 owner 消费并删除、8 秒未被消费时走兜底且不再读旧 `url`；`_boot` 清理陈旧 `window.request`/`boot-handoff.json`；handoff 文件仅在 `VSE_BOOT_HANDOFF=1` 时出现且含 `expiresAt` |
| `tests/test_vse_boot_window.py` | `run_window` 用 `js_api` 桥交付票据、`take_boot_ticket()` 单次、注入后 env 已清除；票据不出现在 argv/stderr；桥不可用时不降级（由页面走 claim）；三级降级与 job 归属断言不回归 |
| 前端（Node 夹具，沿用 `test_local_security.py:296-339` 方式） | `__vseBootReceiver` 幂等与自删；`legacyBootQuery=false` 时不读 URL；`legacyBootQuery=true` 时取票 + `replaceState`；`shell.js` 先注册后渲染 |

### 9.3 03 的完成定义（DoD）

- 上述 4 个测试文件与前端 Node 夹具全绿，且 `tests/test_local_security.py` / `tests/test_local_security_integration.py` 中**未被本契约改变**的断言零改动通过（`boot-exchange` 成功响应体逐字冻结，见 §6.6）。
- `tools/e2e_v2_test_install.py` 真机跑通（或明确记录为未跑并说明原因）。
- `git diff --check` 干净；发布物记录齐全（app 包 + 整包各一份）。
- `CONTRACTS.md` C7 的增补已获批并落地。

---

## 10. 验收标准映射

| 验收标准 | 覆盖章节 |
|---|---|
| AC1 去掉 URL 查询串与 `instance.json` 明文票据，给出新通道与字段处置 | §5.2、§5.3、§5.4、§5.5、§5.9、§5.10、§6.8 |
| AC2 无会话新窗口重开 + 12 小时过期的受控恢复；谁签发、如何证明是同一用户启动器；Windows 0600 语义与 ACL 裁决 | §5.6、§5.7、§5.8、§5.1（启动器密钥）、§11-1、§11-3 |
| AC3 新票据签发不允许未认证任意本机页面调用（认证/来源/速率/重放） | §5.5、§5.11、§6.3、§6.4、§6.7、§7.2 |
| AC4 冻结接口、字段、状态、错误、旧启动器兼容与整包要求 | §5.9、§6（全部）、§7（全部）、§8（全部） |
| AC5 只新增本文档、无真实凭据、与现状一致 | 文首声明、§0 证据基线、§2（逐条附代码位置） |

---

## 11. 待主控裁决项

| # | 事项 | 选项 | 建议 | 影响 |
|---|---|---|---|---|
| 1 | **Windows 上“仅当前用户可读”的实现方式**（`boot-handoff.json`） | A：依赖安装根继承 ACL（零新增 ACL 操作）；B：`icacls`/`SetSecurityInfo` 显式 DACL | **A**，并在文档与代码注释里明确“不宣称 0600” | 选 B 即引入对**新建文件**的 ACL 操作；DSH-V2-47 的“不改 ACL”只约束既有文件，但仍需显式批准；选 B 会新增失败路径与测试面 |
| 2 | `boot-handoff.json` 是否默认关闭 | 默认关（仅 `VSE_BOOT_HANDOFF=1` 创建）/ 默认开 | **默认关** | 默认开等于在生产安装目录常驻一个短期票据文件，扩大 T2 面 |
| 3 | `vse_window` 标记 Cookie 的 TTL 与是否允许它**单独**换会话 | 30 天 / 24 小时；允许单独换 / 必须同时有启动器参与 | **30 天 + 允许单独换**（服务端内存态，重启即失效） | 若要求启动器参与，则每次 12 小时过期都要“重开窗口”，D3 的“一键”退化为两步；缩短 TTL 会提高重开频率 |
| 4 | 同用户非浏览器进程在授权存活的 ≤10 秒内伪造头部领取授权的残余风险 | 接受 / 对第二实例与恢复路径加“托盘确认后预置” | **接受**（T2 固有上限），并在 C7 增补里写明 | 若要求托盘确认，`vse_boot` 需新增交互流程与测试，且无人值守自动化会受阻 |
| 5 | `legacyBootQuery` 默认值与下线版本 | 03 保持 `true`，2.5 再翻 `false` / 03 直接翻 `false` | **03 保持 `true`，独立批准后翻 `false`** | 直接翻会让旧启动器（2.3.x）用户完全失去写能力 |
| 6 | `instance.json` 删除 `bootToken` 与 `tools/e2e_v2_test_install.py` 改造的归属 | 随 03 同批改工具 / 另开任务 | **随 03 同批**（否则真机验证跑不起来） | 该文件不在本任务 owned_scope；03 的 scope 需显式包含它 |
| 7 | 开发态 `webui.py` 的启动方式 | 进程内自签密钥 + `arm_grant` / 打印票据到控制台 | **进程内 `arm_grant`** | 打印票据会进控制台历史，等于把 D1 换个地方复现 |
| 8 | `LocalSessionStore` 过期项只增不减（现状 `web/security.py:70-94`） | 本契约顺带修 / 另案 | **另案** | 属内存卫生问题，与本契约的传输通道无关，混入会扩大 03 的评审面 |

### 主控裁决记录（2026-11-01）

1. 采纳 A：依赖安装根继承 ACL，不新增 ACL 操作；文档与代码不得宣称 0600。
2. `boot-handoff.json` 默认关闭，仅 `VSE_BOOT_HANDOFF=1` 时创建。
3. `vse_window` 30 天、允许单独换会话（服务端内存态，app 重启即失效）；C7 增补需写明“12 小时会话可由同窗口标记在 30 天内一键续期”。
4. 接受同用户非浏览器进程 ≤10 秒抢领授权的残余风险，C7 增补写明。
5. 03 保持 `legacyBootQuery=true`；翻转为 `false` 另行批准。
6. `tools/e2e_v2_test_install.py` 改造随 03 同批。
7. 开发态 `webui.py` 用进程内 `arm_grant`，不打印票据。
8. `LocalSessionStore` 过期项清理另案处理。

**范围提示**：本契约 §9.1/§8.4 要求 03 修改的文件超出 tasks.json 中 03 的 owned_scope（新增 `web/app.py`、`web/static/host/boot-exchange.js`、`shell.js`、`api.js`、`tools/e2e_v2_test_install.py`、`docs/refactor-v2/CONTRACTS.md` 及 `tests/test_local_security_integration.py`、`tests/test_vse_boot_supervisor.py`、`tests/test_vse_boot_window.py`）；派发 03 时须按本节显式扩展 owned_scope。

---

## 12. 声明

- 本文档已于 2026-11-01 经主控批准，是 DSH-V2-03 的唯一实现依据。
- 本文档**没有**实现任何条款，也**没有**在真机或测试中验证任何条款；§9.2 的用例名是待写清单，不是已有证据。
- 本文档不含真实凭据、令牌、内部 URL 或用户名；所有示例均为合成值。
