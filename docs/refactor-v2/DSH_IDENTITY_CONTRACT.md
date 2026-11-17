# 企业会话续期与统一清除契约（DSH-V2-14）

> 状态：**已批准（主控，2026-11-01）**。§11 Q1–Q10 全部采纳“本文建议”列（见 §11 末“主控裁决记录”）；DSH-V2-15 以本文为唯一实现依据。
> 基线提交：**`1619141`**（分支 `dsh/v2-14`，基线 = `refactor/ux-v2` 当前 HEAD，已含第 0/1 波）。
> 适用任务：**DSH-V2-15**（企业会话续期协调器与清除代次）为主；DSH-V2-16（Aras 会话恢复链接入）为直接后继。
> 上游冻结契约：[CONTRACTS.md](CONTRACTS.md) **C2 会话恢复**、C1 宿主服务、C7 本机安全、C8 路由兼容；发布口径见 [RELEASE_MATRIX.md](RELEASE_MATRIX.md)。
> 风险等级：high（并发、凭据、公共错误契约）。派发门：`lead_design_and_approval`；15 的门是 `requires_approved_14`。
>
> **本文只描述契约，不宣称任何能力已实现。** 文中所有"目标/计划"接口均为 DSH-V2-15 的待实现物；所有"现状"陈述都附 `文件:行号`，可逐条复核。
> 示例一律为合成值：占位账号 `user-a`、`user-b`，占位主机 `example.test`，占位系统代号 `sys-a`。**不含任何真实用户名、域名、内网 URL、口令或令牌。**
> 凭据只允许存在于 DPAPI 凭据库与进程内存的解析窗口内；令牌、Cookie、口令**不得**进入日志、诊断、契约文本、测试夹具或响应载荷。

---

## 0. 术语与判定基准

| 术语 | 含义 | 现状来源 |
|---|---|---|
| 企业会话 | Aras / TDC 等使用统一域账号登录后建立的内存会话对象（requests.Session 或 WinHTTPSession 实例） | `core/domain_identity.py:152` |
| 系统（system） | 会话归属的上游系统标识，当前闭集为 `aras`、`tdc` | `core/domain_identity.py:213` |
| 账号引用（accountRef） | 由 `system + 归一化来源根 + principal` 派生的 sha256，即现有 `scope` | `core/domain_identity.py:169-171` |
| 清除代次（generation） | 每系统单调递增的整数；用户清除登录、凭据变更时 +1 | 本文 §7（**当前不存在**） |
| 凭据纪元（vaultEpoch） | DPAPI 凭据库写入/清除时 +1 的全局整数 | 本文 §7（**当前不存在**） |
| 单飞（single-flight） | 同 `(system, accountRef)` 的并发过期请求共享同一次续期结果 | 本文 §5（**当前不存在**） |
| 重放（replay） | 续期成功后对原业务请求重新发送**一次** | 本文 §6（**当前不存在**） |
| 副作用未知（generation_unknown） | 请求已发出但未收到任何响应（超时/连接中断），无法确认上游是否执行 | 本文 §6.4（**当前不存在**） |

**唯一事实优先级**：仓库代码与测试 > 本文 > `memory/` 叙述。本文与代码冲突时以代码为准，并把冲突作为缺陷条目登记（§2）。

---

## 1. 现状（附代码位置）

### 1.1 DPAPI 凭据库

| 事实 | 位置 |
|---|---|
| `WindowsDPAPICredentialVault(path, backend=None)`：`store(username, password)`、`clear()`、`is_configured()`、`resolve()`（contextmanager） | `core/domain_identity.py:33-110` |
| `store` 用 `CryptProtectData` 保护 JSON `{username, password}`，先写 `*.tmp` 再 `os.replace`；`finally` 清空明文引用 | `core/domain_identity.py:47-68` |
| `clear` 只 `unlink(missing_ok=True)`，幂等 | `core/domain_identity.py:70-75` |
| `is_configured` = 文件存在且 `st_size > 0` | `core/domain_identity.py:77-78` |
| `resolve` 未配置时抛 `CredentialVaultError("domain credential vault is not configured")`；解密失败抛 `CredentialVaultError("could not unprotect domain credentials")`；`finally` 清空 `ResolvedCredential` | `core/domain_identity.py:80-110` |
| `_dpapi_blob` 同时接受 pywin32 的 `bytes` 与 tuple 形态（测试后端兼容点） | `core/domain_identity.py:25-30` |
| `DPAPICredentialProvider(vault)`：只接受 `{"domain", "unified-domain"}` 两个引用名；`CredentialVaultError` 统一转 `CredentialProviderError("credential reference is unavailable")` | `core/domain_identity.py:113-130` |
| 生产装配：vault 路径 `app_root()/data/domain-credential.dpapi`，同时进 `app.extensions["domain_credential_vault"]` | `web/app.py:431`、`web/app.py:464` |
| 交付物同步共用的 Windows 凭据管理器引用名常量 `SYNC_CREDENTIAL_REF = "domain"` | `web/host_boot.py:37` |
| `ResolvedCredential` 字段 `repr=False` 且 `clear()` 就地清空；`MemoryCredentialProvider` 标注"仅离线测试替身，禁止生产持久化" | `core/credential_provider.py:19-26`、`core/credential_provider.py:168-187` |

### 1.2 `DomainSessionRegistry`（会话状态与 TTL）

| 事实 | 位置 |
|---|---|
| `DomainSessionRegistry(ttl=timedelta(hours=8))`，内部 `_records` / `_sessions` / `RLock` | `core/domain_identity.py:152-157` |
| `_SessionRecord(updated_at, expires_at, source_root, scope)` | `core/domain_identity.py:133-138` |
| `mark_authenticated(system, session=None, *, principal=None, source_root=None)`：写 `_records[system]`（TTL 8h）；带 `principal+source_root` 时计算 `scope`；`session` 为字符串 `"aras"/"tdc"` 时走"仅标记状态"的历史分支（测试用） | `core/domain_identity.py:159-180` |
| `bound_session(system, source_root)`：来源根必须逐字匹配且 `scope` 非空，否则 `None` | `core/domain_identity.py:182-189` |
| `session(system)`：过期即 pop 并返回 `None`（惰性过期，**不抛错**） | `core/domain_identity.py:191-198` |
| `clear(system=None)`：仅 `dict.pop`，无代次、无在途取消 | `core/domain_identity.py:200-208` |
| `payload()`：只遍历 `("aras","tdc")`，键集 `authenticated / updatedAt / expiresAt / expired` | `core/domain_identity.py:210-221` |
| `_identity_source_root` 校验：必须 http(s)、无 userinfo/query/fragment，归一化为 `[scheme, host, port, path.rstrip("/")]` | `core/domain_identity.py:141-149` |

### 1.3 统一登录路由 `POST /api/settings/domain-login`

| 事实 | 位置 |
|---|---|
| 先 `deps.domain_sessions.clear()`（**无条件全清**），再依次登录 Aras、TDC | `web/host_boot.py:138-152` |
| Aras 成功后 `mark_authenticated("aras", session, principal=username, source_root=DEFAULT_ARAS_BASE_URL)` | `web/host_boot.py:141-143` |
| TDC 成功后 `mark_authenticated("tdc", session)`（**不带 principal/source_root**，因此 `scope=None`、`bound_session` 永不命中） | `web/host_boot.py:149` |
| 任一系统成功即 `tdc_export_cache.clear()` | `web/host_boot.py:153-154` |
| `saveForScheduled` 时先写 Windows 凭据管理器，再写 DPAPI；DPAPI 失败回滚 Windows 凭据；两处失败都返回 503 `CredentialVaultUnavailable` | `web/host_boot.py:155-180` |
| 响应信封 `{ok, data:{results, sessions}}`；全失败时 HTTP 401 | `web/host_boot.py:181-188` |
| 单系统失败文案经 `sanitize_error_message`（`redact_sensitive_text`，限 240 字） | `web/host_boot.py:146`、`web/host_boot.py:152`、`web/crawler_boot.py:185-186` |

### 1.4 统一清除路由 `DELETE /api/settings/sessions`

| 事实 | 位置 |
|---|---|
| `system` 白名单 `None/aras/tdc`，否则 400 `ValidationError` | `web/host_boot.py:196-198` |
| `domain_sessions.clear(system)`；`system in (None,"tdc")` 时 `tdc_export_cache.clear()` | `web/host_boot.py:199-201` |
| `clearCredentialVault` 时先删 Windows 凭据、再清 DPAPI（Windows 删除失败则 DPAPI 保持原状，避免孤儿凭据） | `web/host_boot.py:202-212` |
| 响应 `{ok, data:{sessions}}` | `web/host_boot.py:213-215` |

### 1.5 各企业系统的登录/会话建立与失败处理

**Aras（`services/aras_auth.py`）**

| 事实 | 位置 |
|---|---|
| `ArasECMAuthClient.login(username, password)`：OIDC 授权码 → userinfo → ADValidate 桥 → Innovator password grant → SOAP `ValidateUser` 门禁 | `services/aras_auth.py:269-560`、`services/aras_auth.py:562-606` |
| `ArasAuthError(message, *, stage, request_id, status_code)`，message 经 `redact_sensitive_text` | `services/aras_auth.py:120-134` |
| 传输异常统一为 `"ECM authentication request failed during {stage}: {ExceptionType}"`（只带类型名） | `services/aras_auth.py:677-697` |
| 拒绝码（`validation`）：`login-form-missing`、`login-form-method`、`challenge-required`、`credentials-rejected`、`oidc-state-or-code`、`oidc-token-missing`、`userinfo-missing`、`advalidate-rejected`、`advalidate-failed`、`innovator-token-rejected`、`validate-user-rejected`、`validate-user-login-page`、`validate-user-no-user` | `services/aras_auth.py:314`、`316`、`349`、`355`、`373`、`406`、`435`、`480`、`488`、`534`、`585`、`592`、`597` |
| `ArasLoginResult(session, auth_mode)`，`session` 字段 `repr=False` | `services/aras_auth.py:137-142` |
| **未捕获上游 `expires_in`**：内层 token 的过期时间被丢弃，注册表只能靠 8h TTL | `services/aras_auth.py:535-548`（仅取 `access_token`/`token_type`） |

**TDC（`services/tdc_auth.py`）**

| 事实 | 位置 |
|---|---|
| `TDCPasswordAuthClient.login(username, password)`：OIDC 授权码 → `/auth/oauth/token` 交换 → `/uwf/user/info` 校验 | `services/tdc_auth.py:179-388` |
| `TDCLoginResult(session, token_expires_in, auth_mode)`：**上游 `expires_in` 已被解析出来** | `services/tdc_auth.py:90-96`、`services/tdc_auth.py:355` |
| 拒绝码：`credentials-rejected`（非 3xx 即拒，无挑战页识别）、`oidc-state-or-code`、`oidc-token-missing`、`tdc-token-rejected`、`tdc-token-missing`、`session-verification-failed`、`rejected-status` | `services/tdc_auth.py:256-261`、`269`、`304`、`349`、`353`、`379`、`555-562` |
| `token_expires_in` 在装配处被忽略（`mark_authenticated("tdc", session)` 只用 8h TTL） | `web/host_boot.py:149` |

**帆软 / TIR（`plugins/tir_report/client.py`）**

| 事实 | 位置 |
|---|---|
| 模块 docstring 明确："每次任务重新登录，**不做续期**" | `plugins/tir_report/client.py:5` |
| 闭集错误码 + 中文指引 `REMEDIES`（`credential_missing`、`credential_unavailable`、`login_failed`、`busy`、`login_unsupported`、`session_not_found`、`parameters_rejected`、`export_failed`、`network_error`、`cancelled`） | `plugins/tir_report/client.py:27-38` |
| `TirError(code, detail)`：`str()` 即可安全展示/入库，未知码退化为 `export_failed` | `plugins/tir_report/client.py:41-47` |
| 传输层有界重试 `_RETRY_DELAYS=(2.0,4.0)`，重试耗尽抛 `network_error` | `plugins/tir_report/client.py:23`、`plugins/tir_report/client.py:80-103` |

> **契约边界（重要）**：帆软/TIR 在 v1 **不进入续期范围**。它的凭据读取走 `DPAPICredentialProvider`（`plugins/tir_report/service.py` 装配），会话生命周期是"单任务内"的，任务结束即丢弃。本文 §4 的错误分类表**仍覆盖**它的错误码，使其对前端呈现与 Aras/TDC 一致；但 §5 单飞续期、§6 重放、§7 代次**不适用**于帆软。

### 1.6 消费方（谁在用会话、谁在判过期）

| 消费点 | 行为 | 位置 |
|---|---|---|
| `_shared_domain_session(system)` | `current_app.extensions["domain_sessions"].session(system)`，取不到返回 `None` | `web/crawler_boot.py:493-499`（模块级）、`web/crawler_boot.py:845-852`（闭包副本） |
| Aras 客户端构造 | 无显式 Cookie/Authorization 时复用共享会话；否则 401 `DomainSessionRequired` | `web/crawler_boot.py:473-484` |
| `_async_session_gate` | 后台任务只允许复用内存会话；密码模式/显式 Cookie → 400 `AsyncAuthUnsupported`；无会话 → 401 `DomainSessionRequired` | `web/crawler_boot.py:502-539` |
| EWO 增强导表 | `bound_session('aras', DEFAULT_ARAS_BASE_URL)`；无绑定 → 401 `DomainLoginRequired`；执行后再次校验会话身份，变化 → 401 `DomainLoginChanged` | `web/ewo_enrichment.py:28-31`、`web/ewo_enrichment.py:56-58` |
| TDC 官方导出缓存键 | 键含 `payload()["tdc"]["updatedAt"]/["expiresAt"]` 与 `id(shared)` | `web/crawler_boot.py:1775-1786` |
| 自检插件 | 只读聚合会话状态 → `ok` / `warn` / `need_check` | `plugins/diagnostics/backend.py:34-123` |
| 前端徽标 | `authenticated/expired` → 三档文案 | `web/static/host/session.js:53-81` |
| 前端登录 | `submitDomainLogin` → `loginOutcome`（`success/partial/vault/error`） | `web/static/host/session.js:142-182` |
| 前端"需要重新登录"判定 | `isAuthError`：401/403 或文案子串命中 | `plugins/system_query/static/lib.js:263-275`、`plugins/settings/static/client.js:47-54`、`plugins/excel_tasks/static/logic.js:384` |

### 1.7 现有错误分类与错误码现状

| 出口 | 现状 | 位置 |
|---|---|---|
| Aras 路由错误映射 | 401 → `AuthenticationError` + `code=unauthenticated`；超时/连接/OSError → 503 `ServiceUnavailable` + `service_unavailable`；`ArasCrawlerError` → 502 `ArasCrawlerError` + `query_failed`（含 `Aras HTTP 5xx` 时 503 + `service_unavailable`）；NCR 导出无文件 → 502 + `ncr_export_no_file` | `web/crawler_boot.py:727-795` |
| TDC 路由错误映射 | `TDCAuthError` → 401 `AuthenticationError`（**无 code**）；`TDCCrawlerError` → 502（`contract-validation` 时 400）+ `safe_diagnostic()`，可重试类给"稍后重试"文案 | `web/crawler_boot.py:2028-2063` |
| 统一错误信封 | `{ok:false, error:{type, message, code?, diagnosticPath?, diagnostic?}}` | `web/crawler_boot.py:189-212` |
| 归档连接器的闭集错误类别 | `_error_type`：`credential_unavailable`、`credential_invalid`、`authentication_error`、`timeout`、`service_unavailable`、`connection_error`、`query_failed`、`invalid_data`、`lease_*`、`job_not_ready` …；`_REMEDY_BY_ERROR_TYPE` 给闭集指引码 | `services/scheduled_archive_runner.py:70-99`、`services/scheduled_archive_runner.py:114-142` |
| 诊断错误码白名单 | `SAFE_ERROR_CODE_ENUM`（23 项，含 `AuthError`/`ServiceUnavailable`/`ConflictError`/`RateLimited`，**不含** `Forbidden`/`AuthenticationError`/`TDCCrawlerError`） | `web/diagnostics.py:44-68` |
| TDC 抓取的阶段分类 | `stage` ∈ `request/export/status-validation/content-validation/parse-json/api-validation/…`；`safe_diagnostic()` 输出 `upstreamHttpStatus`、`apiCode`、`retryable` | `services/tdc_crawler.py:90-165` |
| Aras 抓取的 401/403 | **两者合并**为 `ArasAuthenticationError` | `services/aras_crawler.py:652-653`、`730-731`、`984-985`、`1026-1027` |

### 1.8 既有测试夹具（可复用，只读）

| 夹具 | 契约 | 位置 |
|---|---|---|
| `FakeDPAPIBackend` | `CryptProtectData/CryptUnprotectData` 返回 **tuple** `("", blob)`；确定性可逆（前缀 + 反转） | `tests/test_settings_security.py:201-231` |
| `BytesReturningDPAPIBackend` | 同前但返回裸 `bytes`（对齐真实 pywin32） | `tests/test_settings_security.py:234-260` |
| `_runtime_opaque()` | `opq-<uuid4hex>`：每次运行唯一、非真实值的合成秘密 | `tests/test_settings_security.py:32-33` |
| `FakeVault` | 只实现 `is_configured()` 与 `resolve()`；`broken=True` 抛 `CredentialVaultError` | `tests/test_plugin_tir_report.py:350-372` |
| `FakeResponse` / `FakeSession` | `status_code/headers/text/content/json()`；`session.headers` 为 dict、`.get/.post` 按队列返回或抛异常 | `tests/test_aras_auth.py:21-63`、`tests/test_tdc_auth.py:47-100` |
| 会话状态测试 | `mark_authenticated` / `bound_session` / 过期 / 清除 / payload 无秘密 | `tests/test_ewo_identity.py:11-50`、`tests/test_settings_security.py:390-415` |
| 路由级登录/清除 | 打桩 `ArasECMAuthClient`/`TDCPasswordAuthClient`/`store_windows_generic_credential` | `tests/test_settings_security.py:463-628` |
| 自检插件会话 | 直接替换 `flask.current_app.extensions["domain_sessions"]` | `tests/test_plugin_diagnostics.py:171` |

---

## 2. 缺陷清单（本文必须解决的问题）

| 编号 | 缺陷 | 证据 | 后果 |
|---|---|---|---|
| **D1** | **401 与 403 混同**：Aras 抓取把 `{401, 403}` 一起抛 `ArasAuthenticationError`，路由再统一转 401 `AuthenticationError`/`unauthenticated` | `services/aras_crawler.py:652-653`、`730-731`、`984-985`、`1026-1027`、`web/crawler_boot.py:743-750` | 权限不足被误报为"会话过期"，引导用户重登（无效），并可能触发不该发生的续期 |
| **D2** | **前端把 403 当认证失败**：`isAuthError` 对 `status===403 && 非本地守卫` 返回 `true` | `plugins/system_query/static/lib.js:271` | 403 页面直接弹"重新登录"，掩盖真实权限问题 |
| **D3** | **完全没有续期**：会话失效只能让用户手工重登；`ArasAuthenticationError` → 401 即终止 | `web/crawler_boot.py:743-750`、`core/domain_identity.py:191-198` | 8h TTL 到期或上游提前失效时，长任务/后台任务全部失败 |
| **D4** | **无清除代次**：`clear()` 仅 `dict.pop`；在途登录/续期完成后仍可写回 | `core/domain_identity.py:200-208`、`web/host_boot.py:138` | "用户已退出，会话却被在途请求复活"（CONTRACTS C2 明令禁止） |
| **D5** | **TDC 未绑定账号 scope**：`mark_authenticated("tdc", session)` 缺 `principal/source_root` | `web/host_boot.py:149`、`core/domain_identity.py:164-171` | TDC 无 `bound_session`，单飞键缺 accountRef；多账号切换时无法隔离 |
| **D6** | **TTL 与上游真实有效期脱钩**：TDC `expires_in` 已解析却丢弃 | `services/tdc_auth.py:355`、`web/host_boot.py:149` | 注册表认为"有效"而上游已 401，续期触发时机不可预测 |
| **D7** | **状态词汇缺失**：payload 只有 `authenticated/expired`，无法表达 `renewing/cleared/failed` | `core/domain_identity.py:210-221` | 前端/自检无法区分"正在恢复"与"需要重登" |
| **D8** | **无副作用判定与重放规则**：查询与导出/写操作共用同一错误映射与同一共享会话，调用方不声明操作类别 | `web/crawler_boot.py:727-795`（统一 `_aras_error_response`）、`web/crawler_boot.py:1209`（导出失败与查询失败同出口） | 一旦引入自动重试就可能重复导出、重复生成上游文件 |
| **D9** | **无账号锁定防护**：登录失败即返回，无失败计数/冷却；`domain-login` 每次都会真的打一次上游登录 | `web/host_boot.py:140-152` | 若 15 把续期做成"失败立即重试"，会连续失败导致域账号被锁 |
| **D10** | **错误码不统一**：TDC 401 无 `code`；Aras 403 无 `forbidden`；解析失败与网络失败共用 `TDCCrawlerError`/`ArasCrawlerError` | `web/crawler_boot.py:2037-2038`、`web/crawler_boot.py:2043-2061` | 前端只能靠文案子串猜语义（见 D2） |
| **D11** | **诊断错误码白名单不含新码**：`SAFE_ERROR_CODE_ENUM` 无 `Forbidden` 等 | `web/diagnostics.py:44-68` | 新错误码无法进入安全错误码统计（需 15 之外的文件，见 §10.2） |
| **D12** | **`DomainSessionRegistry` 时钟不可注入**：直接用 `datetime.now(timezone.utc)` | `core/domain_identity.py:162`、`195`、`211` | 过期/续期竞态测试无法确定性构造 |

---

## 3. 目标与非目标

### 3.1 目标（本契约要冻结的）

1. **四类错误可判定、可区分**：`session_expired`（401 类，应续期）/ `forbidden`（403 类，不续期不清凭据）/ `network`（可重试、不续期）/ `parse`（上游格式变化、不续期、需诊断），每类给前端固定 `type`+`code`+中文文案（§4）。
2. **单飞续期**：同 `(system, accountRef)` 并发过期只续期一次，其余等待同一结果；10 个并发过期请求 → 1 次登录（§5）。
3. **一次重放**：续期成功后，仅对幂等或**确认无副作用**的原请求重放一次；副作用未知（`generation_unknown`）**不重发**（§6）。
4. **清除代次与竞态状态机**：`generation` / `vaultEpoch` 单调递增；续期回写前复核代次，不匹配即作废；给出 `none/valid/renewing/expired/cleared/failed` 状态机与转移条件（§7）。
5. **接口与夹具冻结**：DPAPI 接口、续期协调器签名、前端错误信封、测试夹具契约、错误码表（§4/§8/§9）。

### 3.2 非目标（明确不做）

- 不实现"静默长期保持登录"：无 DPAPI 凭据时**不得**尝试任何续期，直接 `login_required`。
- 不做跨账号/跨来源根的会话复用或别名合并（沿用"保守精确 principal"，`core/domain_identity.py:168`）。
- 不改 `CONTRACTS.md` C2 已冻结的**公开**状态词汇（`unknown/checking/connected/expired/refreshing/login_required/signed_out`）；本文的 6 个内部状态只经映射表呈现（§7.4，待裁决 Q1）。
- 不给帆软/TIR 增加续期（`plugins/tir_report/client.py:5` 的既有决定）。
- 不引入新的凭据存储介质：**只用 DPAPI**（`WindowsDPAPICredentialVault`）+ 进程内存。
- 不把会话/令牌落库；不改 `core/db_manager.py`；不在 `web/app.py` 加业务路由体。
- 不自动重试登录（账号锁定风险），不做供应商/账号切换。

---

## 4. 错误分类：判定依据与处置矩阵

### 4.1 分类判定顺序（必须按此顺序，命中即停）

```
1) 无本地会话 / 会话已过期 / 清除代次已变   → session_expired（可续期）或 session_cleared
2) 上游 401 / 登录页重定向 / 会话失效业务码 → session_expired（可续期）
3) 上游 403 / 权限拒绝业务码               → forbidden（不续期、不清凭据）
4) 传输层异常（超时、连接重置、DNS、TLS）    → network（可重试、不续期）
5) 已收到响应但结构/类型/契约不符           → parse（不续期、需诊断）
6) 请求已发出但无任何响应                   → generation_unknown（不重发，见 §6.4）
```

判定"是否已收到响应"必须先于 2)–5)：**只要拿到 HTTP 状态码或响应对象，就不是 `generation_unknown`**。

### 4.2 逐系统归类表（现状依据 + 目标归类）

| 系统 | 上游信号（现状代码位置） | 归类 | 依据 |
|---|---|---|---|
| Aras | 抓取 `status in {401,403}` → `ArasAuthenticationError`（`services/aras_crawler.py:652-653`、`730-731`、`984-985`、`1026-1027`） | **需拆分**：401 → `session_expired`；403 → `forbidden` | 现状把两者合并（D1） |
| Aras | `_response_requires_bearer` 且 `status=="401"`（`services/aras_crawler.py:1296-1303`） | `session_expired` | 明确"需要 Bearer"= 会话未被接受 |
| Aras | 登录门禁：`validate-user-rejected` / `validate-user-login-page`（`services/aras_auth.py:585`、`592`） | 登录期 → `session_expired` 的续期失败分支（`renewal_rejected`） | 续期时上游拒绝了新会话 |
| Aras | `validate-user-no-user`（`services/aras_auth.py:597`） | `forbidden`（账号无 Aras 权限） | 文案本身写"may lack Aras access" |
| Aras | `challenge-required`（`services/aras_auth.py:349`） | `renewal_rejected`（`login_challenge`） | 验证码/MFA 无法自动完成，**禁止自动重试** |
| Aras | `credentials-rejected`（`services/aras_auth.py:355`） | `renewal_rejected`（`credential_invalid`） | 口令错误；有锁定风险 |
| Aras | 传输异常 `authentication request failed during {stage}`（`services/aras_auth.py:693-697`） | `network` | 仅带异常类型名 |
| Aras | `_json_response` 的 `rejected-content-type`/`invalid-json`/`json-not-object`（`services/aras_auth.py:710-727`） | `parse` | 上游格式变化 |
| TDC | `status-validation` 非 2xx（`services/tdc_crawler.py:891-910`） | 401 → `session_expired`；403 → `forbidden`；5xx/429 → `network`（`retryable=True`） | 现状 401/403 都落 `TDCCrawlerError` |
| TDC | 登录页 HTML：`_looks_like_html`（`services/tdc_crawler.py:912-921`） | `session_expired`（`login_page`） | 登录页 = 会话失效的等价信号 |
| TDC | `content-validation`（非 JSON Content-Type，`services/tdc_crawler.py:922-931`） | `parse` | 格式漂移 |
| TDC | `parse-json`（`services/tdc_crawler.py:932-949`） | `parse` | 结构漂移 |
| TDC | `api-validation`（业务码非 0/200，`services/tdc_crawler.py:960-974`） | 默认 `forbidden`；只有登记在 15 维护的“会话失效业务码闭集”（初始为空，须有脱敏实测证据才可加入）中的业务码才归 `session_expired`，不得按 `msg` 文案判定 | 业务码需按闭集映射，禁止文案子串自由判定 |
| TDC | `auth-verify` 的 `session-verification-failed`（`services/tdc_auth.py:378-379`） | 登录期 → `renewal_rejected` | 新会话未被接受 |
| TDC | 登录 `credentials-rejected`（`services/tdc_auth.py:256-261`） | `renewal_rejected`（`credential_invalid`） | 口令错误 |
| 帆软/TIR | `TirError.code`（`plugins/tir_report/client.py:27-38`） | `network_error`→`network`；`login_failed`/`login_unsupported`→`renewal_rejected`；`session_not_found`/`parameters_rejected`/`export_failed`→`forbidden` 或 `parse`（按 §4.3 映射）；`credential_missing`/`credential_unavailable`→`credential` | 不改其代码，只做映射 |

### 4.3 对外错误码表（闭集，`error.code`）

**复用优先**：已存在的码不改名（`unauthenticated`、`service_unavailable`、`credential_unavailable`、`credential_invalid`、`query_failed`）。

| `error.code` | 语义类 | HTTP | `error.type` | 是否续期 | 是否可重试 | 是否清凭据 | 前端中文文案（唯一来源） |
|---|---|---|---|---|---|---|---|
| `unauthenticated` | session_expired | 401 | `AuthenticationError` | **是** | 续期成功后重放一次 | 否 | 登录已过期，正在尝试恢复…（恢复失败时：登录已过期，请重新登录域账号） |
| `login_page` | session_expired | 401 | `AuthenticationError` | **是** | 同上 | 否 | 上游返回了登录页，登录状态已失效 |
| `session_cleared` | session_expired（清除后） | 401 | `DomainLoginRequired` | 否（代次已变，禁止复活） | 否 | 否 | 登录已被清除，请重新登录 |
| `forbidden` | forbidden | **403** | `Forbidden` | 否 | 否 | 否 | 当前域账号没有该操作权限，请联系系统管理员；不需要重新登录 |
| `service_unavailable` | network | 503 | `ServiceUnavailable` | 否 | 是（沿用既有有界重试） | 否 | 企业系统暂时不可用，请检查网络或 VPN 后重试 |
| `timeout` | network | 503 | `ServiceUnavailable` | 否 | 是 | 否 | 企业系统响应超时，请稍后重试 |
| `upstream_parse_error` | parse | 502 | `UpstreamContractError` | 否 | 否 | 否 | 上游返回的数据格式与预期不符；已生成诊断，请回传诊断文件 |
| `credential_unavailable` | credential | 503 | `CredentialVaultUnavailable` | 否 | 否 | 否 | 未保存域账号凭据或凭据无法读取，请重新登录并勾选保存 |
| `credential_invalid` | credential | 401 | `DomainLoginRejected` | 否（自动） | **否**（锁定风险） | 否 | 域账号口令被拒绝；请确认口令未变更后手动重新登录 |
| `login_challenge` | credential | 401 | `DomainLoginRejected` | 否 | **否** | 否 | 登录需要验证码/多因素验证，请手动登录 |
| `login_locked` | credential | 401 | `DomainLoginRejected` | 否 | **否** | 否 | 连续登录失败，可能触发账号锁定；请稍后手动登录 |
| `generation_unknown` | unknown-side-effect | **409** | `ConflictError` | 不适用 | **否（禁止自动重发）** | 否 | 操作可能已在上游执行但结果未知，请先在系统中确认，再决定是否重试 |

**类型词表变更声明**：`Forbidden`、`UpstreamContractError`、`DomainLoginRejected` 为**新增** `error.type`；其余复用现状（`AuthenticationError` 见 `web/crawler_boot.py:746`/`2038`，`ServiceUnavailable` 见 `754`，`CredentialVaultUnavailable` 见 `web/host_boot.py:165`，`DomainLoginRequired` 见 `web/ewo_enrichment.py:30`，`ConflictError` 见 `web/diagnostics.py:58`）。

**硬规则**

1. **403 一律不得转成 401**，也不得触发续期或清凭据（修正 D1/D2）。
2. 每个错误码只能对应一个语义类；不得新增未登记码。
3. `message` 只允许来自上表中文文案或既有闭集映射（`services/scheduled_archive_runner.py:145-165` 的做法），**禁止**回显上游原文、URL、路径、令牌。
4. 前端"需要重新登录"判定必须改为**按 `code` 闭集**判定，禁止再用文案子串（修正 D2，见 §10.2 的 15 外清单）。

---

## 5. 单飞续期设计（single-flight）

### 5.1 键与作用域

- 续期键 `renewalKey = (system, accountRef)`，其中 `accountRef` **复用现有 `scope`**：
  `sha256(json([system, source_root, principal]))`（`core/domain_identity.py:169-171`）。
- 前置条件（不满足即拒绝续期，直接 `login_required`）：
  1. `credential_provider.is_available("domain")` 为真；
  2. 存在该键的 `accountRef`（TDC 需先按 D5 绑定，否则续期键不成立）；
  3. `generation`/`vaultEpoch` 在续期开始后未变（§7.2）。

### 5.2 状态与流程

```
过期请求 → 分类为 session_expired
        → coordinator.renew(system, account_ref, generation)
             ├─ 无在途续期：本请求成为 leader（登记 future）
             │     ├─ 读 DPAPI 凭据（resolve 上下文内，用完即 clear）
             │     ├─ 调用该系统既有登录客户端（ArasECMAuthClient / TDCPasswordAuthClient）
             │     ├─ 成功 → commit_renewal(gen 未变) → future.set_result(snapshot)
             │     └─ 失败 → 按 §4 分类 → future.set_exception(闭集错误)
             └─ 已有在途续期：本请求成为 follower，等待同一 future
        → leader/follower 都得到同一结果（不重复登录）
```

### 5.3 强制约束

1. **一次登录**：同键同时只允许一个在途续期；follower **不得**自行发起登录（"10 个并发过期请求只续期一次"）。
2. **共享结果，包括失败**：leader 失败时，所有 follower 得到同一闭集错误，不各自重试。
3. **锁内不持凭据**：DPAPI `resolve()` 只在 leader 的登录调用期间存活（沿用 `core/domain_identity.py:80-110` 的上下文语义）；任何等待/唤醒都必须在凭据清理之后。
4. **续期总预算**：`renewal_timeout`（建议 120s，覆盖 Aras 多段登录的单段 30s 超时，见 `services/aras_auth.py:230`）。超时后 leader 以 `timeout`（network 类）失败，**不重试**，follower 同结果。
5. **续期失败分类**：
   - 传输类 → `timeout` / `service_unavailable`（会话保持 `expired`，允许用户稍后手动重试）；
   - 登录被拒（口令错、挑战页、连续失败）→ `credential_invalid` / `login_challenge` / `login_locked`，会话转 `failed`，**禁止自动再试**；
   - 上游格式变化 → `upstream_parse_error`，会话转 `failed`，诊断计数 +1。
6. **账号锁定防护（D9）**：
   - 只有 `session_expired` 才允许触发自动续期；`network`/`parse`/`forbidden` 永不触发。
   - 同键自动登录失败计数 `failures`：第 1 次失败后最小冷却 60s，第 2 次 300s，第 3 次起进入 `login_locked`，**必须用户手动登录**才清零。
   - 任意 15 分钟窗口内自动登录尝试 ≤ 3 次。
   - 手动登录（`POST /api/settings/domain-login`）不受冷却限制，但成功后清零 `failures`。
7. **续期成功后必须做的事**（缺一即视为实现不完整）：
   - `mark_authenticated` 写回会话（带 `principal`/`source_root`，使 `bound_session` 可用）；
   - TTL 取 `min(8h, upstream_expires_in − 安全余量)`；`upstream_expires_in` 目前只有 TDC 提供（`services/tdc_auth.py:355`）；Aras 未提供时保持 8h；
   - 使 `tdc_export_cache` 中该会话代次之前生成的条目失效（现状键依赖 `updatedAt`，见 `web/crawler_boot.py:1775-1786`）；
   - 记录 `lastRenewedAt`，**不记录**任何令牌/Cookie。
8. **可观测性**：续期尝试/成功/失败只允许上报闭集元数据（`system`、`outcome`、`code`、`elapsedMs`、`generation`、`attempt`），经 `core/diagnostic_recording.observed` 既有通道（`core/domain_identity.py:5`）。

---

## 6. 重放规则（一次，且只在安全时）

### 6.1 操作分类（由调用方在发起时声明，禁止事后猜测）

| 类 | 判定 | 允许重放 | 示例（现有路由） |
|---|---|---|---|
| `idempotent_read` | 只读查询/预览/状态读取 | 续期成功后**一次** | Aras EWO/PAA/NCR 查询（`web/crawler_boot.py:867` 起）、TDC 查询/预览、`/api/tasks/<id>` 状态 |
| `idempotent_write_with_key` | 写操作且带客户端幂等键（`opId`） | 续期成功后**一次**，且必须复用同一 `opId` | CONTRACTS C5 的报告生成（`docs/refactor-v2/CONTRACTS.md:104-105`） |
| `unsafe_side_effect` | 写/导出/生成，可能已在上游产生产物 | **禁止重放** | Aras 官方 NCR 导出（`web/crawler_boot.py:1209` 附近）、TDC 官方工作簿导出、EWO 增强导表 `run`（`web/ewo_enrichment.py:49-53`）、TIR 导出（`plugins/tir_report/client.py`） |
| `generation_unknown` | 已发出、无任何响应 | **禁止重放** | 任何 `unsafe_side_effect` 的超时/连接重置 |

### 6.2 重放判定表

| 情形 | 是否重放 | 依据 |
|---|---|---|
| 收到 401（上游在鉴权阶段拒绝） + `idempotent_read` | 是，**一次** | 请求被拒绝，未执行 |
| 收到 401 + `unsafe_side_effect` | **否** | 无法证明上游"鉴权先于执行"；保守不重放（待裁决 Q3） |
| 收到 403 | 否 | 与续期无关（§4） |
| 网络超时/连接重置（无响应） + 任意类 | 否 | `generation_unknown`（§6.4） |
| 解析失败 | 否 | 重放不会改变格式 |
| 续期失败 | 否 | 没有新会话可用 |
| 清除代次在等待期间变化 | 否 | 会话已作废（§7.2） |
| 同一业务操作第 2 次遇到 401 | 否 | "最多续期一次 + 重放一次"上限 |

### 6.3 重放守卫

每次业务操作携带守卫 `(operationId, attempt, generationAtStart)`：

- `attempt` 从 1 起；只有 `attempt == 1` 且分类允许时才可发起第 2 次；
- 重放前必须复核 `generation == generationAtStart`，否则直接返回 `session_cleared`；
- 重放必须是**同一请求体、同一幂等键**，不得重新生成参数；
- 重放结果与首次结果对调用方等价（调用方无感），但诊断里必须记录 `replayed=true`。

### 6.4 `generation_unknown` 的对外语义

返回 `409 / ConflictError / generation_unknown`，文案："操作可能已在上游执行但结果未知，请先在系统中确认，再决定是否重试"。

**禁止**：
- 不得自动重发（本契约硬约束，与 `docs/dsh-next-20261031/tasks.json` 中"generation_unknown 不自动重发"一致）；
- 不得把该情形伪装成 `service_unavailable`（会被前端当作"可重试"）；
- 不得由后台任务自行降级重跑。

---

## 7. 清除代次与状态机

### 7.1 代次定义

| 计数器 | 作用域 | 递增时机 | 初值 |
|---|---|---|---|
| `generation[system]` | 每系统 | ① `DELETE /api/settings/sessions`（含 `system=None` 的全清，对每个系统各 +1）；② `POST /api/settings/domain-login` 的既有全清（`web/host_boot.py:138`，对每个系统各 +1）；③ 任何"退出登录"语义操作 | 0 |
| `vaultEpoch` | 全局 | ① `WindowsDPAPICredentialVault.store()` 成功；② `clear()` 成功；③ 凭据被外部替换后检测到不一致 | 0 |

**单调性**：两者只增不减，进程重启后从 0 重新计数即可（会话本身也不跨进程存活；跨进程无需持久化，见 Q4）。

### 7.2 竞态规则（"清除与续期"）

1. **先作废，后删凭据**：`clear(system)` 必须
   `generation += 1` → 取消该键在途续期（follower 立即得到 `session_cleared`）→ 移除会话/记录 → 再删 DPAPI（若 `clearCredentialVault`）。
   （现状 `web/host_boot.py:199-212` 是"先清内存、再删凭据"，缺"取消在途"这一步。）
2. **回写前复核**：续期完成时比较 `(generation, vaultEpoch)` 与开始时捕获的值。
   - 相等 → 允许写回；
   - 任一不等 → **结果作废**：丢弃新会话对象（不写 `_sessions`）、不更新 TTL、不 bump `updatedAt`、返回 `session_cleared`。
3. **凭据变更等价于清除**：`store()` 成功后 `vaultEpoch += 1`，所有在途续期结果作废（防止"用旧口令建立的新会话"覆盖新口令的登录结果）。
4. **不得复活**：`cleared` 状态下，任何自动路径（续期、重放、后台任务）都不能把会话写回 `valid`；只有显式 `POST /api/settings/domain-login` 或用户手动登录可以。
5. **`bound_session` 语义保持**：`source_root` 不匹配或 `scope` 为空仍返回 `None`（`core/domain_identity.py:182-189`），续期不得放宽该判定。

### 7.3 状态机（内部 6 态）

```
                    mark_authenticated(gen 未变)
        ┌────────────────────────────────────────────┐
        │                                            ▼
   ┌────────┐                                   ┌────────┐
   │  none  │──mark_authenticated──────────────▶│ valid  │
   └────────┘                                   └────────┘
        ▲                                         │   ▲
        │                             401/TTL到期  │   │ 续期成功
        │                                         ▼   │ (gen 未变)
        │                                    ┌──────────┐
        │                                    │ expired  │
        │                                    └──────────┘
        │                                      │      ▲
        │              begin_renewal(leader)   │      │ 网络类失败
        │                                      ▼      │
        │                                 ┌───────────┐
        │                                 │ renewing  │
        │                                 └───────────┘
        │                                   │       │
        │                     登录被拒/解析失败│       │ 代次已变
        │                                   ▼       ▼
        │                              ┌────────┐ ┌─────────┐
        └──────────────────────────────│ failed │ │ cleared │
                                       └────────┘ └─────────┘
```

| 状态 | 含义 | 进入条件 | 允许的自动动作 |
|---|---|---|---|
| `none` | 从未建立会话 | 启动 / 清除后 | 无（需用户登录） |
| `valid` | 会话可用 | `mark_authenticated` 且未过期 | 正常业务请求 |
| `renewing` | 正在续期（单飞 leader 在跑） | `expired` + 存在可续期条件 | 仅等待；follower 不发起新登录 |
| `expired` | 已失效但可续期 | 上游 401/登录页、TTL 到期 | 触发一次续期 |
| `cleared` | 用户清除或代次已变 | `clear()` / 回写复核失败 | 无（需用户登录） |
| `failed` | 续期或登录被上游拒绝 | 登录被拒、挑战页、连续失败、解析失败 | 无（需用户登录；冷却规则见 §5.3-6） |

**转移表（唯一合法转移）**

| 从 | 事件 | 到 | 附带条件 |
|---|---|---|---|
| `none` | 用户登录成功 | `valid` | 写 `principal`/`source_root` |
| `valid` | 上游 401/登录页 | `expired` | 记录 `lastErrorCode` |
| `valid` | TTL 到期（`session()` 惰性判定） | `expired` | 不抛错（保持现状语义） |
| `valid`/`expired` | 403 | 不变 | **不**转 `expired`，不清凭据 |
| `valid`/`expired` | network / parse | 不变 | 仅计数/诊断 |
| `expired` | `begin_renewal`（leader） | `renewing` | 捕获 `(generation, vaultEpoch)` |
| `expired` | 无可续期条件（无凭据/无 accountRef/冷却中） | `failed` 或保持 `expired` | 无凭据 → `failed(credential_unavailable)` |
| `renewing` | 续期成功且代次未变 | `valid` | 更新 TTL/`updatedAt`，失效旧缓存键 |
| `renewing` | 续期成功但代次已变 | `cleared` | 结果丢弃（§7.2-2） |
| `renewing` | 网络类失败 | `expired` | 允许用户稍后重试 |
| `renewing` | 登录被拒/挑战/解析失败 | `failed` | 计数 +1，进入冷却 |
| `failed` | 用户登录成功 | `valid` | 清零失败计数 |
| 任意 | `clear(system)` | `cleared` | `generation += 1`，取消在途 |
| `cleared` | 用户登录成功 | `valid` | 代次不回退 |

### 7.4 与 CONTRACTS C2 冻结词汇的映射（待裁决 Q1）

`docs/refactor-v2/CONTRACTS.md:47-68` 已冻结公开状态集 `unknown / checking / connected / expired / refreshing / login_required / signed_out`，并写明"其余状态不得出现"。本文的 6 个内部状态**不替换**它，只做映射：

| 内部状态 | C2 公开状态 | 前端三档（`CONTRACTS.md:47`） |
|---|---|---|
| `none` | `unknown`（或用户刚清除时的 `signed_out`） | 需要重新登录 |
| `valid` | `connected` | 已连接 ✓ |
| `renewing` | `refreshing` | 正在恢复 |
| `expired` | `expired` | 需要重新登录 |
| `cleared` | `signed_out` | 需要重新登录 |
| `failed` | `login_required` | 需要重新登录 |

`checking` 保留为前端拉取状态期间的瞬时态（`web/static/host/session.js:87-101` 的 `refreshInFlight`）。

---

## 8. 接口契约

### 8.1 `core/domain_identity.py` 扩展（15 的 owned_scope 内，**尚未实现**）

保持既有方法签名不变（`mark_authenticated`/`bound_session`/`session`/`clear`/`payload`），**只增不改**：

```python
class DomainSessionRegistry:
    def __init__(self, ttl: timedelta = timedelta(hours=8), *, clock=None) -> None: ...
        # clock: Callable[[], datetime]，默认 datetime.now(timezone.utc)（修正 D12）

    # ── 既有（签名不变）──
    def mark_authenticated(self, system, session=None, *, principal=None, source_root=None) -> None: ...
    def bound_session(self, system: str, source_root: str) -> tuple[Any, str] | None: ...
    def session(self, system: str) -> Any | None: ...
    def clear(self, system: str | None = None) -> None: ...
    def payload(self) -> dict[str, dict[str, object]]: ...

    # ── 新增（代次与状态机）──
    def generation(self, system: str) -> int: ...
    def vault_epoch(self) -> int: ...
    def bump_vault_epoch(self) -> int: ...
    def state(self, system: str) -> str: ...                    # none|valid|renewing|expired|cleared|failed
    def begin_renewal(self, system: str) -> tuple[int, int]: ...  # (generation, vaultEpoch)
    def mark_renewing(self, system: str) -> None: ...
    def commit_renewal(self, system: str, session: Any, *, principal: str, source_root: str,
                       generation: int, vault_epoch: int, ttl: timedelta | None = None) -> bool: ...
        # 返回 False = 代次已变，结果作废（不得写回）
    def mark_failed(self, system: str, code: str) -> None: ...
```

`payload()` 的键集**只允许**增加（禁止改名/删除，C8 路由兼容）：

| 键 | 现状 | 目标 |
|---|---|---|
| `authenticated` | 有 | 保留（`web/static/host/session.js:67` 依赖） |
| `updatedAt` / `expiresAt` | 有 | 保留（`web/crawler_boot.py:1783` 依赖） |
| `expired` | 有 | 保留（`plugins/diagnostics/backend.py:93` 依赖） |
| `state` | 无 | 新增，取值 = §7.4 左列 |
| `generation` | 无 | 新增，int |
| `accountMasked` | 无 | 新增，**脱敏**账号（如 `u***@example.test` 的等价脱敏形态，禁止原样 principal） |
| `lastErrorCode` | 无 | 新增，闭集错误码或 `null` |
| `lastRenewedAt` | 无 | 新增，UTC ISO8601 或 `null` |
| `canRenew` | 无 | 新增，bool（`C2` 允许的键，`CONTRACTS.md:65`） |

**禁止**出现在 payload：`principal` 原文、`scope`、`sourceRoot`、Cookie、Authorization、token、密码、内网 URL（C2 明令）。

### 8.2 `services/session_recovery.py`（新建，15 的 owned_scope 内，**尚未实现**）

```python
SYSTEMS = ("aras", "tdc")            # 帆软不在续期范围
IDEMPOTENT_READ = "idempotent_read"
IDEMPOTENT_WRITE_WITH_KEY = "idempotent_write_with_key"
UNSAFE_SIDE_EFFECT = "unsafe_side_effect"

class SessionRecoveryError(Exception):
    code: str                        # §4.3 闭集
    system: str
    retryable: bool
    replayed: bool = False

class SessionExpired(SessionRecoveryError): ...      # code in {unauthenticated, login_page}
class SessionCleared(SessionRecoveryError): ...      # code = session_cleared
class Forbidden(SessionRecoveryError): ...           # code = forbidden
class UpstreamUnavailable(SessionRecoveryError): ... # code in {service_unavailable, timeout}
class UpstreamParseError(SessionRecoveryError): ...  # code = upstream_parse_error
class CredentialUnavailable(SessionRecoveryError): ...# code = credential_unavailable
class RenewalRejected(SessionRecoveryError): ...     # code in {credential_invalid, login_challenge, login_locked}
class GenerationUnknown(SessionRecoveryError): ...   # code = generation_unknown

@dataclass(frozen=True)
class SessionSnapshot:
    system: str
    state: str
    generation: int
    account_masked: str
    last_renewed_at: str | None
    last_error_code: str | None
    can_renew: bool
    def to_payload(self) -> dict[str, object]: ...    # 只输出 §8.1 白名单键

class SessionRenewalCoordinator:
    def __init__(
        self,
        registry: DomainSessionRegistry,
        credential_provider: Any,                     # DPAPICredentialProvider
        clients: Mapping[str, Callable[[], Any]],     # {"aras": ArasECMAuthClient, "tdc": TDCPasswordAuthClient}
        *,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] | None = None, # 测试注入，禁止真实 sleep
        renewal_timeout: float = 120.0,
        max_auto_attempts: int = 3,
        cooldown_seconds: tuple[float, ...] = (60.0, 300.0),
    ) -> None: ...

    def snapshot(self, system: str) -> SessionSnapshot: ...
    def renew(self, system: str, *, account_ref: str, generation: int) -> SessionSnapshot: ...
    def run_with_renewal(self, system: str, account_ref: str, operation: Callable[[], Any],
                         *, kind: str, idempotency_key: str | None = None) -> Any: ...
        # kind ∈ {idempotent_read, idempotent_write_with_key, unsafe_side_effect}
        # 语义：捕获 SessionExpired → 单飞续期 → 按 §6 决定是否重放一次 → 否则抛闭集错误
    def classify(self, exc: BaseException, *, system: str) -> SessionRecoveryError: ...
    def clear(self, system: str | None = None) -> dict[str, SessionSnapshot]: ...
```

**行为契约**

- `renew` 对 follower 不产生任何新的上游登录调用；leader 失败时所有等待者抛同一异常实例语义。
- `run_with_renewal` 的重放次数上限为 1；第二次 `SessionExpired` 直接抛出（不续期）。
- `clear` 必须在返回前使在途续期结果作废（§7.2）。
- 任何分支都不得把凭据、令牌、Cookie 放进异常消息或 `SessionSnapshot`。

### 8.3 前端错误信封（沿用 `web/crawler_boot.py:189-212`，只加白名单键）

```json
{
  "ok": false,
  "error": {
    "type": "Forbidden",
    "code": "forbidden",
    "message": "当前域账号没有该操作权限，请联系系统管理员；不需要重新登录",
    "retryable": false,
    "action": "none",
    "diagnostic": {"system": "aras", "stage": "status-validation", "upstreamHttpStatus": 403}
  }
}
```

| 键 | 允许取值 | 说明 |
|---|---|---|
| `type` | §4.3 表中 `error.type` 列 | 闭集 |
| `code` | §4.3 表中 `error.code` 列 | 闭集；**前端按它判定是否需要重登** |
| `message` | §4.3 中文文案列 | 不得含上游原文/URL/令牌 |
| `retryable` | bool | 仅 `network` 类为 `true` |
| `action` | `renew` \| `relogin` \| `wait` \| `confirm` \| `none` | 前端据此决定按钮文案与是否弹登录框 |
| `diagnostic` | 闭集元数据（`system`、`stage`、`upstreamHttpStatus`、`apiCode`、`requestId`、`generation`） | 不得含业务行内容 |

**`code → action` 唯一映射**（禁止前端自行推断）：

| `code` | `action` |
|---|---|
| `unauthenticated`、`login_page` | `renew`（续期失败后降级为 `relogin`） |
| `session_cleared`、`credential_unavailable`、`credential_invalid`、`login_challenge`、`login_locked` | `relogin` |
| `service_unavailable`、`timeout` | `wait` |
| `generation_unknown` | `confirm` |
| `forbidden`、`upstream_parse_error` | `none` |

### 8.4 路由层契约变化（15 之外，需 16/新任务承接）

| 路由 | 现状 | 目标 |
|---|---|---|
| `POST /api/settings/domain-login` | 先全清再逐系统登录；失败文案混用（`web/host_boot.py:125-188`） | 保留信封与 200/401 语义；失败结果项增加 `code`；清除时 `generation += 1`；手动登录不受冷却限制但成功后清零计数 |
| `DELETE /api/settings/sessions` | 清内存 + 可选清凭据（`web/host_boot.py:190-215`） | 增加"先取消在途续期 + `generation += 1`"，响应 `sessions` 含新状态键 |
| `GET /api/settings` | 返回 `sessions` 与 `credentialVaultConfigured`（`web/host_boot.py:67-81`） | 不变（只经 `payload()` 扩展增键） |

---

## 9. 测试夹具契约（DSH-V2-15 必须遵守）

### 9.1 允许使用的既有夹具（只读复用，不得复制粘贴改语义）

| 夹具 | 用途 | 位置 |
|---|---|---|
| `FakeDPAPIBackend`（tuple 返回）/ `BytesReturningDPAPIBackend`（bytes 返回） | 假 DPAPI 后端，两种返回形态都必须覆盖 | `tests/test_settings_security.py:201-260` |
| `FakeVault` | 假凭据库（`is_configured`/`resolve`/`broken`） | `tests/test_plugin_tir_report.py:350-372` |
| `MemoryCredentialProvider` | 内存凭据（**仅测试**） | `core/credential_provider.py:168-187` |
| `FakeResponse` / `FakeSession` | 假传输（状态码/头/正文/json + 调用记录） | `tests/test_aras_auth.py:21-63`、`tests/test_tdc_auth.py:47-100` |
| `_runtime_opaque()` | 运行期唯一合成秘密 | `tests/test_settings_security.py:32-33` |

### 9.2 新建夹具（`tests/test_session_recovery.py`，15 的 owned_scope 内）

必须满足的契约：

1. **假传输**：实现 `get/post` 与 `headers` dict，按脚本队列返回 `FakeResponse` 或抛异常；必须记录调用序列（用于断言"只登录一次""只重放一次"）。
2. **假登录客户端**：`Callable[[], Any]`，带 `.login(username, password)`；内部计数器 `login_calls`；可注入延迟（用 `sleep` 回调而非真实等待）以稳定构造并发窗口。
3. **假时钟**：`clock: Callable[[], datetime]`，可步进；**禁止** `time.sleep` 参与断言（沿用 `services/tdc_crawler.py:82-83` 的可替换 sleep 思路）。
4. **并发构造**：`threading.Barrier` 或事件，10 个线程同时进入 `run_with_renewal`，断言 `login_calls == 1`。
5. **合成值规则**：账号一律 `user-a`/`user-b`；来源根一律 `https://example.test/...`；口令用 `_runtime_opaque()` 生成；**禁止**真实用户名、真实域名、真实内网地址、真实令牌、真实 Cookie。
6. **断言秘密不外泄**：对 `payload()`、异常 `str()`、诊断事件字典做 JSON 序列化后断言不含口令/令牌片段（对齐 `tests/test_settings_security.py:456-460` 的做法）。
7. **不得打真实网络**：任何测试都不得实例化真实 `requests.Session` 或 `WinHTTPSession` 发起请求。

### 9.3 必须覆盖的场景（每条都是验收断言）

| # | 场景 | 断言 |
|---|---|---|
| T1 | 10 并发过期请求 | 登录调用 1 次；10 个调用方都拿到成功会话 |
| T2 | 单飞 leader 失败（网络） | 登录 1 次；所有等待者得到 `service_unavailable`；状态 `expired`；无自动重试 |
| T3 | 续期成功 + `idempotent_read` | 业务调用 2 次（首次 401 + 重放 1 次）；`replayed=true` |
| T4 | 续期成功 + `unsafe_side_effect` | 业务调用 1 次；续期成功但原请求不重放，返回 `generation_unknown` 且 `action=confirm`（由用户确认后手动重做）；**无重放** |
| T5 | 无响应超时（`unsafe_side_effect`） | 抛 `generation_unknown`；业务调用 1 次 |
| T6 | 403 | 不续期（登录 0 次）、不清凭据（`is_configured()` 仍真）、`code=forbidden`、HTTP 403 |
| T7 | 解析失败 | 不续期、`code=upstream_parse_error`、诊断计数 +1 |
| T8 | 清除竞态：续期在途时 `clear()` | 回写被拒（`commit_renewal` 返回 False）、状态 `cleared`、`session()` 为 `None` |
| T9 | 凭据变更竞态：续期在途时 `store()` | `vaultEpoch` 变化 → 结果作废 |
| T10 | 账号锁定防护 | 连续失败后进入冷却：第 2 次自动登录前必须等待 `cooldown_seconds[0]`（假时钟步进）；第 3 次失败后 `code=login_locked` 且不再自动尝试 |
| T11 | 无凭据 | `can_renew=false`，`code=credential_unavailable`，登录 0 次 |
| T12 | 状态机 | 逐条断言 §7.3 转移表；非法转移必须被拒绝（例如 `cleared → valid` 只能经登录） |
| T13 | 秘密零泄漏 | T1–T12 全部运行后，所有 `payload()`/异常/诊断的序列化文本不含合成口令 |

**验证命令（15 执行时）**：

```
python -B -m pytest -p no:cacheprovider tests/test_session_recovery.py tests/test_credential_provider.py -q
```

并回归既有会话/安全/自检套件（只读，用于确认未破坏现状）：

```
python -B -m pytest -p no:cacheprovider tests/test_settings_security.py tests/test_ewo_identity.py tests/test_plugin_diagnostics.py -q
```

---

## 10. DSH-V2-15 实现清单（含 scope 标注）

### 10.1 15 的 owned_scope（`docs/dsh-next-20261031/tasks.json:1374-1378`）

| 文件 | 动作 | 内容 |
|---|---|---|
| `services/session_recovery.py` | **新建** | §8.2 全部：错误闭集、`SessionSnapshot`、`SessionRenewalCoordinator`（单飞、分类、重放、冷却、代次复核） |
| `core/domain_identity.py` | **修改（只增）** | `clock` 注入（D12）、`generation`/`vaultEpoch`、`state`、`begin_renewal`/`mark_renewing`/`commit_renewal`/`mark_failed`、`payload()` 增键（§8.1）、`clear()` 递增代次 |
| `tests/test_session_recovery.py` | **新建** | §9.3 T1–T13 |

**15 内允许的最小改动原则**：`mark_authenticated`/`bound_session`/`session`/`payload` 的既有键与语义不得改变（`tests/test_ewo_identity.py`、`tests/test_settings_security.py:390-415`、`tests/test_plugin_diagnostics.py:171` 必须继续通过）。

### 10.2 明确**超出** 15 owned_scope 的必要接线（需主控裁决后另派，或并入 16）

| 文件 | 为什么必须改 | 归属建议 |
|---|---|---|
| `web/host_boot.py` | 登录/清除要 bump 代次、取消在途、结果项带 `code`；TDC 需带 `principal`/`source_root`（D5）；TTL 取 `expires_in`（D6） | **16 的 owned_scope 已含**（`tasks.json:1465`） |
| `web/app.py` | 构造并注入协调器到 `app.extensions`（C1 `identity` 服务） | **16 的 owned_scope 已含**（`tasks.json:1467`） |
| `services/aras_auth.py` | 续期需要可复用的登录入口/明确 401 vs 403 语义 | **16 的 owned_scope 已含**（`tasks.json:1463`） |
| `services/project_status_connectors.py` | 后台同步经协调器重试 | **16 的 owned_scope 已含**（`tasks.json:1464`） |
| `web/crawler_boot.py` | `_shared_domain_session`/`_async_session_gate`/`_aras_error_response`/`_tdc_error_response` 接入分类与协调器；403 不再转 401（D1） | **无任务承接 → Q2** |
| `services/aras_crawler.py` | `status in {401,403}` 拆分为两个异常（D1） | **无任务承接 → Q2** |
| `services/tdc_crawler.py` | 401/403/网络/解析的分类信号细化（已具备 `stage`，缺 401/403 区分） | **无任务承接 → Q2** |
| `web/static/host/session.js` | 徽标映射 `state`；`loginOutcome` 读 `code` | **无任务承接 → Q5** |
| `web/static/host/chrome/LoginDialog.js` | 登录失败文案按 `code` 区分 | **无任务承接 → Q5** |
| `plugins/system_query/static/lib.js`、`plugins/settings/static/client.js`、`plugins/excel_tasks/static/logic.js` | `isAuthError` 改按 `code` 闭集判定（D2） | **无任务承接 → Q5** |
| `web/diagnostics.py` | `SAFE_ERROR_CODE_ENUM` 增补新 type（D11） | **无任务承接 → Q6** |
| `plugins/diagnostics/backend.py` | 自检按 `state` 给 `ok/warn/need_check` | **无任务承接 → Q5** |
| `plugins/tir_report/*` | 错误码映射到 §4.3（不改续期行为） | **无任务承接 → Q7** |
| `docs/refactor-v2/CONTRACTS.md` | 若采纳内部状态词汇，需在 C2 增补映射说明 | **lead 修订 → Q1** |

### 10.3 15 的测试清单（除 §9.3 T1–T13 外）

| # | 断言 |
|---|---|
| U1 | `DomainSessionRegistry` 既有行为零回归（过期/清除/`bound_session` 严格匹配/非法 `source_root` 抛 `ValueError`） |
| U2 | `payload()` 键集 = 旧 4 键 + 新 6 键（§8.1），且不含 `principal`/`scope`/`sourceRoot` |
| U3 | `clock` 注入生效：步进后 `session()` 立即返回 `None` |
| U4 | `commit_renewal` 在代次变化时返回 `False` 且**未**写入 `_sessions` |
| U5 | 协调器无凭据时**不**调用登录客户端（`login_calls == 0`） |
| U6 | `unsafe_side_effect` 分类下，即便续期成功也不重放（`business_calls == 1`） |

---

## 11. 待主控裁决项

| # | 议题 | 本文建议 | 不裁决的后果 |
|---|---|---|---|
| **Q1** | 是否把内部 6 态写进 `CONTRACTS.md` C2（现冻结为 7 态且"其余状态不得出现"） | **不改 C2 公开词汇**，仅在 C2 增补 §7.4 映射表；内部状态只出现在 `payload().state` 与后端代码 | 15 无法合法输出 `state` 键；实现方可能自行发明词汇 |
| **Q2** | `web/crawler_boot.py`、`services/aras_crawler.py`、`services/tdc_crawler.py` 的 401/403 拆分归谁 | 新建一个有界任务（如 `DSH-V2-15b`）承接，**不与 15 合并**（15 已有 3 个文件、high 风险） | D1 无法真正修复；403 仍被当 401，本文 §4 成为空文 |
| **Q3** | `unsafe_side_effect` 在"明确 401 且上游鉴权先于执行"时是否允许重放一次 | **默认不允许**（保守）；若某系统有实测证据表明 401 一定先于执行，按系统单独开启并写测试 | 要么过度保守（用户需手动重做），要么误重放造成重复导出 |
| **Q4** | `generation`/`vaultEpoch` 是否需要跨进程/跨重启持久化 | **不需要**：会话本身不跨进程，代次只需进程内单调 | 若要求持久化，需新增 SQLite 表 → 触碰 `core/db_manager.py`（硬约束禁止） |
| **Q5** | 前端 3 个 `isAuthError` 与自检插件、`session.js` 的改造归谁 | 并入 16（16 已含 `web/host_boot.py`，前端属同一用户可见闭环）或单独 UI 任务 | 后端分类正确但前端仍把 403 当"重登"（D2 未修） |
| **Q6** | `web/diagnostics.py::SAFE_ERROR_CODE_ENUM` 是否增补 `Forbidden`/`UpstreamContractError`/`DomainLoginRejected` | **增补**（否则新错误码无法进入安全错误统计） | 诊断统计出现盲区 |
| **Q7** | 帆软/TIR 错误码是否纳入 §4.3 映射 | **纳入映射、不改其内部实现**（保持"每任务重登、不续期"） | 同一页面上 Aras/TDC 与 TIR 的失败语义不一致 |
| **Q8** | 续期成功后是否必须让 TDC 导出缓存失效 | **必须**（否则跨代次复用旧工作簿） | 用户可能拿到上一个会话/代次的导出结果 |
| **Q9** | `payload()` 的 `accountMasked` 脱敏口径 | 只保留首字符 + 固定掩码 + 域后缀（如 `u***@example.test`），**不复用** `scope` 哈希 | 可能泄露账号或引入不可逆哈希作为展示值 |
| **Q10** | `renewal_timeout` 默认值（本文取 120s） | 120s（Aras 登录含 6+ 段 HTTP，单段 30s，见 `services/aras_auth.py:230`） | 并发请求可能被过早判定超时 |

---

### 主控裁决记录（2026-11-01）

- Q1 不改 C2 公开词汇，只增补 §7.4 映射表。Q3 `unsafe_side_effect` 默认不重放；按系统开启需另行批准并附实测证据。Q4 代次只在进程内单调，不持久化。Q6 增补 `SAFE_ERROR_CODE_ENUM`。Q7 帆软/TIR 纳入映射、不改内部实现。Q8 续期成功后 TDC 导出缓存必须失效。Q9 `accountMasked` 按首字符+掩码+域后缀。Q10 `renewal_timeout` 默认 120 秒。
- Q2 401/403 在 crawler/aras/tdc 的拆分另开有界任务（暂记 DSH-V2-15b），不并入 15。Q5 前端 `isAuthError`/`session.js` 改造并入 DSH-V2-16 或单独 UI 任务，派发 16 时确认。
- 评审低级问题已在批准时修正：诊断白名单为 23 项；TDC 业务码改为闭集登记；§5.1 引用改为 §7.2；T4 改为 `generation_unknown`+`confirm`；U2 改为新 6 键。

---

## 12. 附：代码位置索引（复核用）

| 主题 | 位置 |
|---|---|
| DPAPI 库读写/清理 | `core/domain_identity.py:33-110` |
| DPAPI Provider 引用名白名单 | `core/domain_identity.py:113-130` |
| 会话注册表（TTL/绑定/清除/载荷） | `core/domain_identity.py:133-222` |
| 凭据抽象与内存替身 | `core/credential_provider.py:15-187` |
| 统一登录/清除路由 | `web/host_boot.py:67-215` |
| 生产装配（vault 路径、extensions） | `web/app.py:430-441`、`web/app.py:464` |
| Aras 登录链与拒绝码 | `services/aras_auth.py:269-606` |
| TDC 登录链与 `expires_in` | `services/tdc_auth.py:179-388` |
| Aras 抓取 401/403 合并点 | `services/aras_crawler.py:652-653`、`730-731`、`984-985`、`1026-1027` |
| TDC 抓取阶段与有界重试 | `services/tdc_crawler.py:80-165`、`891-974` |
| 路由错误映射（Aras/TDC） | `web/crawler_boot.py:727-795`、`2028-2063` |
| 共享会话读取/后台门禁 | `web/crawler_boot.py:493-539`、`845-852` |
| TDC 导出缓存键 | `web/crawler_boot.py:1775-1786` |
| EWO 增强导表会话绑定 | `web/ewo_enrichment.py:28-31`、`56-58` |
| 自检会话聚合 | `plugins/diagnostics/backend.py:34-123` |
| 前端徽标/登录 | `web/static/host/session.js:53-101`、`142-182` |
| 前端 `isAuthError` | `plugins/system_query/static/lib.js:263-275`、`plugins/settings/static/client.js:47-54` |
| 归档连接器错误闭集/指引码 | `services/scheduled_archive_runner.py:70-165` |
| 诊断错误码白名单 | `web/diagnostics.py:44-68` |
| 帆软错误码与"不续期"决定 | `plugins/tir_report/client.py:5`、`27-47`、`80-103` |
| 既有夹具 | `tests/test_settings_security.py:32-33`、`201-260`、`390-415`、`463-628`；`tests/test_ewo_identity.py`；`tests/test_plugin_tir_report.py:350-372`；`tests/test_aras_auth.py:21-63`；`tests/test_tdc_auth.py:47-100` |
| 上游冻结契约 | `docs/refactor-v2/CONTRACTS.md:45-68`（C2）、`C7`（凭据与本机会话分离）、`C8`（路由兼容） |
| 任务与依赖 | `docs/dsh-next-20261031/tasks.json:1294-1458`（14/15/16） |

---

**审批记录（待填）**

| 项 | 结论 | 日期 | 裁决人 |
|---|---|---|---|
| 本文是否可作为 DSH-V2-15 唯一依据 | 待批 | — | 主控 |
| Q1–Q10 | 待批 | — | 主控 |
