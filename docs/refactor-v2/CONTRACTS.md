# VSE Toolbox v2 公共契约（冻结稿 2026-10-31）

> 状态：**冻结**（W0-02）。后续实现不得偏离；偏离即回归门禁失败。
> 修订规则：lead 修订本文件并同步受影响任务契约与测试；已发布接口只能加宽不能收窄。
> 每条契约都标注：责任方（lead/worker）、验证手段（pytest 门禁 / Node 夹具 / 浏览器路径）。
> 术语：`宿主` = `web/app.py` + `host/`；`插件` = `plugins/<id>/`；`信封` = `{ok, data, error}`。

## C1 宿主服务（host services）

**现状锚点**：`host/context.py::HostContext`（db / data_dir / json_ok / json_error / local_guard /
services / redact / service(name) / plugin_data_dir）；服务字典 = `app.extensions`（现有 13 个：
crawl_task_runner、deliverable_analysis、deliverable_form_analysis、domain_credential_vault、
domain_sessions、ewo_enrichment、excel_task_admin、excel_worker_controller、plugin_registry、
plugin_updates、scheduled_archive_admin、settings_store、tdc_export_cache）。

**契约**：

1. 服务命名空间（目标 9 个版本化服务；括号内是现有来源，逐步收编，不改调用方语义）：

   | 服务名 | 版本 | 职责 | 现有来源 |
   |---|---|---|---|
   | `identity` | v1 | 企业凭据库 + 会话生命周期（续期、清除、状态） | `domain_sessions` + `domain_credential_vault` |
   | `projects` | v1 | 项目注册表、当前项目、切换/归档（只封 `vse_boot.projects` 的读侧） | `vse_boot/projects.py`（新增薄封装） |
   | `scheduler` | v1 | 固定时刻执行槽（C4） | 新增（托盘进程内） |
   | `tasks` | v1 | 后台任务生命周期、进度、取消、重试 | `crawl_task_runner` + `excel_task_admin` |
   | `archive` | v1 | 原件留存（ArchiveStore 之上的领域层） | `scheduled_archive_admin` |
   | `excel` | v1 | Excel COM 任务与路径安全 | `excel_worker_controller` |
   | `notify` | v1 | 托盘/页面通知，去重，含项目名 | 新增 |
   | `diagnostics` | v1 | 白名单诊断包 | `web/diagnostics.py` 收编 |
   | `reports` | v1 | 报告生成幂等层（日报/TIR/导出共用） | 新增 |

2. 宿主负责在 `create_app` 实例化并注入；插件只能 `host.context.service(name)` 获取。
   插件**不得**自行创建数据库、凭据库、调度器、HTTP 客户端池；违者地图门禁 +
   `tests/test_plugin_isolation.py` 拒绝（该测试锁定 `plugins/**` 不 import `web.`、
   不出现 `DatabaseManager(`、`dpapi`、`schedule.` 等构造点）。
3. 版本化：每个服务对象带 `SERVICE_VERSION`（int，从 1 起）。加方法 = 兼容（版本不变）；
   改签名/语义 = 版本 +1 且宿主在同一发版内同时带新旧两个版本号映射
   （`services_index.json` 不引入——直接在 `host/context.py` 的常量表声明）。
4. 前端公共流程（登录卡片、ErrorCard、FixIt、进度条、术语）放 `web/static/host/`
   共享模块；插件页面经既有 `apiRequest`/`kit.js` 模式引用宿主静态路径 `/static/host/...`，
   **禁止跨插件 `import "/static/plugins/<other>/..."`**（Node 夹具门禁断言 import 图）。

**验证**：`tests/test_host_service_registry.py`（每个服务可获取、版本号存在、插件作用域无构造点）。

## C2 会话恢复（session renewal）

**状态机**（`identity` 服务与前端共用词汇；前端顶栏只映射为三档：已连接 ✓ / 正在恢复 / 需要重新登录）：

```
unknown → checking → connected
                   → expired → refreshing → connected | login_required
login_required ⇄ signed_out（用户主动退出/清除）
```

- 至少实现：`unknown / checking / connected / expired / refreshing / login_required / signed_out`。
  其余状态不得出现。
- **触发**：只有**确定的认证失效**（Aras/TDC 明确 401/登录页重定向/会话失效错误码）才触发续期。
  网络错误 → 保持原状态 + 可重试；权限不足（403/业务拒绝）→ 不续期；解析失败 → 不续期并按
  结构漂移上报诊断计数。
- **单飞**：同账号同系统并发请求共享一次续期（进程内 future/锁，键 = `system + accountRef`）。
- **重放**：一次业务操作最多「续期一次 + 重放一次」。只读请求或带可靠幂等键的写请求允许重放；
  副作用结果未知（超时、连接中断后状态不明）**禁止自动重放**，转 `expired` + ErrorCard 引导人工。
- **清除竞态**：清除凭据先使该账号在途请求失效（取消共享续期 future、令重放守卫失效），
  再删除 DPAPI 项；续期完成回写前必须重新校验凭据引用仍然存在，防止「清除与续期竞态恢复已退出会话」。
- **脱敏**：公开响应只允许 `{system, state, accountMasked, lastRenewedAt, canRenew}`；
  不得出现凭据引用、Cookie、token、内网 URL（`core/redaction` 收口 + 门禁扫描 identity 载荷键集）。

**验证**：`tests/test_identity_renewal.py`（合成传输层：单飞、一次重放上限、副作用不重放、清除竞态、状态集断言）。

## C3 项目与向导（projects & wizard）

- 项目 ID 与数据目录映射**不随改名改变**（`projects.json` 里 id 不可变，改名只动 display name）。
- 编辑项目：PATCH 带 `expectedRevision`；字段**省略 = 不改**，显式 `null` = 清空；
  修订冲突返回 409 `RevisionConflict`。
- 归档：当前项目必须先安全切换（有其他可用项目）才能归档；归档不物理删除
  （`retired` 标记，隐藏，数据保留；VPI-T2-D1 同规则）。
- 车型/科室默认值：修改默认值**不得**静默改写已验证的同步绑定；启用流程里若绑定已存在，
  显示「保持已有绑定」并可显式选择重新取证。
- 向导：跨重启恢复非敏感状态（步进、车型/科室选择、交付物选择）；区分「稍后设置」与「已完成」；
  **密码绝不持久化到向导状态**（密码只进 DPAPI，经 identity 服务）。
- 车型清单：可配置（设置项），UI 始终保留文本输入兜底；清单为空时不编造选项。

**验证**：`tests/test_projects_edit_contract.py`（改名不动 id/目录、省略 vs null、409、归档切换门）、
`tests/test_wizard_state.py`（重启恢复、无密码持久化断言）。

## C4 调度（scheduler）

- 默认时刻：北京时间每日 09:00、16:00（同步）；日报默认周一至周五 08:30；调休用可配置覆盖表。
- 执行槽：唯一键 `projectId / jobId / businessDate / scheduledTime`；槽是持久记录（SQLite），不是内存定时。
- 补跑：启动、睡眠恢复只补**当天**错过的槽，不累计补跑前几天；错过判定用本机时区当天的槽时刻。
- 暂停：项目级/任务级暂停标志；暂停期间到点的槽记 `paused_skipped`，不补跑。
- 崩溃恢复：租约（lease）标记执行中；租约过期（进程死亡）后当天内允许一次重新入队，标 `retryOf`。
- 失败重试：同一槽最多自动重试 1 次（指数退避 ≥5 分钟）；仍失败则进任务中心人工处理。
- 旧调度兼容：既有 15/30/60 分钟间隔绑定保持原语义（interval 型），固定时刻与 interval 互斥
  （同一绑定只能一种）；不重新引入 Windows 计划任务。
- 单一调度权威：托盘进程是唯一调度器；WebUI 只读写槽记录。本阶段只调度当前项目。
- 日报数据新鲜：日报生成前独立触发一次同步（或校验最近成功同步时间在阈值内），
  不依赖尚未到点的 09:00 同步。

**验证**：`tests/test_scheduler_slots.py`（槽键唯一性、当天补跑、跨天不补、暂停、租约恢复、retryOf）。

## C5 报告与原件（reports & originals）

- 报告生成带操作幂等标识 `opId`（客户端生成 UUID）+ `configVersion`（配置摘要）+
  `dataVersion`（数据快照指纹）。同 `opId` 重复请求返回首次结果（`replayed: true`），不重复计费抓取。
- TIR 同日复用键：`projectId + 车型 + 日期 + 筛选摘要`；命中后必须校验文件存在且大小>0/可读，
  校验失败当作未命中重新生成。
- 关注清单只有一份权威数据（现有 watchlist 存储）；报告页与交付物页读写同一份，UI 不得各自缓存副本。
- 导出主操作放交付物详情；报告中心入口跳同一实现（同一路由/服务函数），不复制逻辑。
- 同步原件关联运行记录（runId 外键语义），避免重复抓取：同 run 内同来源只留存一次。
- 临时产物 7 天清理只作用于 `tasks` 产物目录；历史原件（ArchiveStore）保留策略独立，清理互不波及。

**验证**：`tests/test_reports_idempotency.py`（opId 重放、config/data 版本变化不误判）、
`tests/test_tir_reuse.py`（复用键、文件损坏重生成）。

## C6 任务与通知（tasks & notify）

- 取消两态：`cancel_requested`（已请求，任务可能仍在收尾）→ `cancelled`（已确认停止）。
  UI 在 `cancel_requested` 期间禁用重复取消按钮但不显示成功。
- 未知总量用不定进度（spinner/「进行中」），不伪造百分比；只有已知 total 才显示 percent。
- 重试新建执行记录并带 `retryOf` 指向旧执行 ID；不覆盖、不改写旧执行。
- 通知：同事件（同项目+同类型+同业务键）去重；文本含项目名；不得暴露文件路径、原始异常、
  内部术语（U4 词表同样约束通知文案）。
- 清理保护：运行中任务的产物目录、正在下载的临时文件、历史原件不在 7 天清理范围。

**验证**：`tests/test_tasks_lifecycle.py`、`tests/test_notify_dedup.py`。

## C7 本机安全与启动（local security & boot）

- 企业凭据（DPAPI）与本机会话（Cookie）分开管理；清除登录 ≠ 清除保存的密码。
- 只监听 loopback（127.0.0.1）；启动交换票据：启动器生成短时（≤10s）单次 token，
  页面用它换取会话 Cookie，交换后从地址栏/历史清除（前端 replaceState）。
- 会话 Cookie：`HttpOnly; SameSite=Strict; Path=/`；`Secure` 按实际环境决定
  （loopback http 下不设 Secure，浏览器对 127.0.0.1 视为安全上下文；若未来走 https 再开）——
  以实测浏览器行为为准并在 W16-03 验证记录里固化。
- 写操作防护四件套：会话有效 + Host 头 ∈ {127.0.0.1, localhost} + Origin 同源 + CSRF token
  （或 Origin 严格校验替代）；**不仅检查 remote_addr == 127.0.0.1**（DNS rebinding / 其他
  本机进程伪造来源）。现有 `local_guard` 是第一步，不是全部。
- Cookie 不按端口隔离：同机其他端口的本地页面同属 localhost 源，因此 Origin 校验 +
  CSRF 不可省略。
- WebView2 / Edge app 模式 / 默认浏览器三种模式走同一套安全契约；任何认证失败都不能退化为
  无认证访问（fail-closed：拿不到会话就显示需要登录，不放开路由）。
- **启动票据不进入 URL（DSH-V2-03 增补）**：启动器向 app 现签一次性票据（TTL ≤10 秒、
  单次消费），经**继承的环境变量**交给窗口子进程，再由 pywebview `js_api` 桥交给页面交换
  会话；票据绝不进请求查询串、argv、浏览器历史、Referer、常规日志、诊断记录或
  `instance.json`（该文件只保留可公开字段：`url`（无查询串）、`port`、`version`、`pid`、
  `supervisorPid`、`schemaVersion`、`startedAt`、`epoch`、`securityContract`）。旧启动器
  （2.3.x）的 `?boot=` 只在 `capabilities.legacyBootQuery` 为 true 时兼容读取，默认 true；
  翻转为 false 必须单独批准。
- **签发/预置入口必须认证（DSH-V2-03 增补）**：`POST /api/security/window-grant` 需要只存在
  于 app 子进程环境里的启动器密钥（`X-VSE-Launch-Secret`，常量时间比较）+ 严格同源
  `Origin`，并有速率限制与重放拒绝（已消费/已 supersede 一律 409，过期 401）；未配置密钥
  时一律 `401 LauncherAuthRequired`，**不存在“无密钥即放行”的分支**。浏览器侧只能领取
  启动器预置的一次性授权（`POST /api/security/boot-claim`），既拿不到票据也拿不到
  `grantId`。残余风险：同一 OS 用户下的非浏览器进程可在授权存活的 ≤10 秒内伪造
  `Origin`/`Sec-Fetch-Site` 抢先领取——这属“同用户 = 同权限”的固有上限，已由主控裁决接受
  （DSH_LOCAL_SECURITY_CONTRACT.md §11-4）；本契约只缩小窗口与可见面，不宣称消除。
- **窗口标记与一键恢复（DSH-V2-03 增补）**：`vse_session` 12 小时（内存态，重启即失效）；
  `vse_window` 30 天，**仅**用于 `POST /api/security/session-recover`——12 小时会话可由同一
  窗口标记在 30 天内一键续期；恢复不重设、不延长标记（不续期），标记缺失/过期/未知时回
  `401 SessionRecoveryUnavailable` 并提示从启动器重开。自动化工具使用的 opt-in 票据文件
  `state/boot-handoff.json` 仅 `VSE_BOOT_HANDOFF=1` 时创建、`ttl+5` 秒自删，其可见性依赖
  安装根继承的当前用户私有 ACL（**不新增 ACL 操作，也不宣称 0600**）。

**验证**：`tests/test_local_security.py`（无票据 401、票据单次、写操作 Origin 拒绝、CSRF 缺失拒绝、
Cookie 属性断言）、`tests/test_local_security_integration.py`（真实 HTTP 八场景）、
`tests/test_boot_ticket_transport.py`（启动器 → 窗口 → 页面的票据传递链）、
`tests/test_vse_boot_supervisor.py` / `tests/test_vse_boot_window.py`（启动器侧）。

## C8 路由兼容与发布（routes & release）

- 迁移前后锁定：路径、方法、状态码、`{ok,data,error}` 信封、错误类型码、Content-Type、
  下载响应头（Content-Disposition/Type）、写保护行为。基线 = W13-01 快照测试（从 `web/app.py`
  逐路由自动抓取生成 golden）。
- 旧 API 迁移 = 别名绑定**唯一实现**；写 API 不靠 302/303（客户端方法语义会丢）。
  页面书签（`#p/...` 旧路径）经 `legacy-routes.js` 跳转。
- host 更新、健康检查、安全引导从 `web/app.py::_install_plugin_host` 迁入宿主专用模块
  （`web/host_boot.py` 计划名）；不得依赖任何可禁用的业务插件。
- 发布矩阵见 [RELEASE_MATRIX.md](RELEASE_MATRIX.md)：宿主接口或运行时变化发整包；
  已验证兼容的 app 层变化才发 app 包。

**验证**：`tests/test_route_contract_snapshot.py`（golden 对照）、迁移批次的别名等价测试。

## C9 时间（time）

- 时间点：内部一律带时区 UTC（aware datetime）；显示一律北京时间（Asia/Shanghai）。
- 纯日期（businessDate、计划完成日期）：保持 date，不做 UTC 转换。
- 无时区历史字段：按来源解释（TDC/Aras 上游字段按其语义标注），**不统一追加 Z**。
- 逾期计算：唯一内核规则（现 `core` 内 `deliverable_status()` 链路收口为单一函数）；
  列表、详情、报告三处共用；W10-01 落地后新增跨页面一致断言。

**验证**：`tests/test_time_rules.py`（aware UTC 往返、纯日期不位移、三处逾期一致）。

## C10 诊断与 Excel（diagnostics & excel）

- 诊断包字段白名单；正则脱敏只是补充防线。禁止导出：原始请求/响应体、环境变量全集、
  凭据库内容、数据库文件副本、业务工作簿。
- Excel 路径安全：拒绝目录穿越（`..`）、UNC 路径、ADS（`:` 流名）、重解析点、
  白名单根内路径替换（symlink/junction 解析后越界）。
- Excel 激活状态检查：无法可靠确认时返回「需要检查」，不伪报通过。

**验证**：`tests/test_diagnostics_whitelist.py`、`tests/test_excel_path_safety.py`（合成路径用例矩阵）。
