# EWO/PAA 交互式刷新与定时同步分离设计

**日期：** 2026-08-31  
**状态：** 已获用户确认，进入实施计划阶段  
**范围：** EWO 交付物详情页、PAA 外部交付物详情页、ARAS 交互式查询错误契约、项目状态与归档定时运行的运行时前置校验。

## 1. 目标

把 EWO/PAA Web UI 明确拆成两个互不混淆的操作模式：

1. **交互式查询 / 立即刷新**：复用设置页建立的服务端 ARAS Session 和现有 EWO/PAA 查询接口，展示本次查询结果，不要求后台凭据引用、稳定键、匹配规则、字段映射或映射稳定性已经配置，也不写入后台同步状态。
2. **自动 / 定时同步**：继续使用后台任务、同步租约、真实凭据解析、连接器、重试、运行历史和人工处理；定时运行不在租约前因运行时输入缺失而零运行退出。

所有现有公开 API 路径、成功响应的已有字段和后台同步的安全边界保持兼容。新增字段只能是向后兼容的诊断/状态字段。

## 2. 当前根因

### 2.1 EWO

EWO 详情页的“立即同步”从 `renderDeliverableStatusChart` 进入 `runEwoSyncFromStatusChart`，随后调用 `requestProjectStatusSync`，最终请求 `POST /api/project-status/deliverables/<id>/sync-now`。该路由先执行 `ProjectStatusUpdateService.assert_sync_ready`，所以把后台策略配置门槛带入了交互按钮。

EWO 的“刷新同步数据”只调用 `GET /api/project-status/deliverables/<id>/analysis`，读取本地分析缓存，并没有执行 ARAS 查询。分析操作栏的“抓取并同步”和证据区的“立即同步”也复用了同一后台同步端点。

### 2.2 PAA

PAA 详情页由概览中的 `archive:aras_paa` 行进入 `renderArchiveDeliverableDetailPage`。“立即同步”调用 `POST /api/scheduled-archive/jobs/aras_paa/sync-now`，经过归档租约、凭据解析、登录和归档产物写入；“刷新同步数据”只读取归档运行历史。

这使 PAA 的即时操作既不是交互式查询，也依赖后台归档凭据和任务配置。

### 2.3 错误状态

ARAS crawler 已经区分登录页/401、网络异常、超时和解析错误，但 Web 适配层目前把多数 crawler 异常统一成 `ArasCrawlerError`。查询成功但返回零行也没有明确的 `empty` 状态。前端因此无法稳定显示“未认证、服务不可用、未匹配、数据为空、查询失败”。

## 3. 设计决策

### 3.1 交互式查询复用现有查询接口

详情页直接复用以下现有接口：

- EWO：`POST /api/aras/ewo/query`
- PAA：`POST /api/aras/paa/query`

不新增一套“详情专用查询协议”，这样独立搜索与详情立即刷新会经过完全相同的 Flask 路由、过滤器构造、ARAS client 构造、SOAP 查询和响应脱敏链路。

详情页请求固定使用浏览器/统一登录模式，只发送非敏感数据：

```json
{
  "base_url": "http://ecm.sgmw.com.cn/innovatorserver",
  "auth_mode": "browser",
  "filters": {},
  "page": 1,
  "page_size": 50,
  "max_records": 2000
}
```

详情页不得发送或持久化 `headers`、`cookie`、`cookies`、`username`、`password`、`credentialRef`、`mapping` 或 lease token。已有独立查询页面的手工请求头兼容行为保留，但详情刷新不使用该入口。

EWO 的筛选来源为策略中的非敏感 `matchRule`：`ewoNo`、`projectCode`、`subjectKeyword`、`modelInfo` 映射为查询接口使用的 snake-case 字段。如果没有匹配规则，使用受限的首屏查询；不把缺少后台配置转换为交互式阻断。已有 `externalKey` 只在它可作为 EWO 编号筛选时作为普通查询条件使用，不作为 readiness 门槛。

PAA 的筛选来源为归档任务的非敏感 `filters`，将 `paaNo`、`ewoNo`、`state`、`area`、`base`、`vehicleKeyword`、日期和 `department` 转换为现有 PAA 查询字段。任务是否启用、是否绑定凭据、是否有归档输出目录不影响交互式查询。

### 3.2 交互式结果是临时查询结果

交互式刷新成功后，详情页显示：

- 查询模式：交互式查询；
- 报表类型：EWO 或 PAA；
- 返回记录数、页码和受控字段表格；
- “本次结果未写入后台同步状态”。

它不创建 project-status run，不获取同步租约，不推进 cursor，不写业务字段，不写同步审计，也不生成后台归档产物。详情页可以继续读取已有分析缓存，但不能把缓存重新读取伪装成刚刚完成的外部刷新。

### 3.3 后台同步保持独立

EWO 的后台同步仍由 `POST /api/project-status/deliverables/<id>/sync-now` 或 CLI `project-status-sync --once` 触发。Web 手工后台触发继续使用完整 readiness gate；CLI 定时真实运行继续传 `validate_runtime_prerequisites=False`，只在租约前校验绑定存在、启用状态、automatic/hybrid 模式和固定来源类型。

PAA 的后台归档仍由 `POST /api/scheduled-archive/jobs/<job_key>/sync-now` 和 `scheduled-archive --once` 触发。为使定时归档也遵守同一运行原则，归档租约增加向后兼容的 `validate_runtime_prerequisites` 参数：

- 默认值 `True`，保持现有直接调用和 Web 手工后台触发的配置门槛；
- `trigger_type="scheduled"` 的 CLI 运行传 `False`，允许先获取租约并创建 run；
- 真实连接器仍通过 credential provider 解析凭据，缺失/无效凭据在 run 中记录为脱敏失败；
- 归档任务的过滤器和固定任务契约仍在租约前校验，因为它们是任务结构安全边界，不是用户凭据或匹配运行时状态。

所有后台连接器继续在租约之后执行真实认证和数据处理。凭据缺失、凭据无效、未认证、服务不可用、未匹配和空数据均必须留下可审计的运行结果；密码、Token、Cookie、Authorization、私钥和完整凭据不得进入结果、日志、审计或 Web 响应。

### 3.4 稳定错误分类

`web/app.py` 的 ARAS 错误响应保留既有 `type`/`message` 结构，并可新增稳定的 `code` 字段：

| code | UI 文案 | 典型来源 |
|---|---|---|
| `unauthenticated` | 未认证 | 无统一 Session、Session 过期、ARAS 登录页或 401/403 |
| `service_unavailable` | 服务不可用 | 连接失败、WinHTTP 错误、超时、上游 5xx |
| `query_failed` | 查询失败 | XML/业务响应解析失败、未知 crawler 错误 |

查询成功但 `count == 0` 时，成功响应增加 `queryState="empty"`；有记录时为 `queryState="matched"`。详情页若已有目标外部键且返回记录中没有对应 `_no`/受控身份字段，则显示“未匹配”，但这仍是交互式结果状态，不触发后台 readiness gate。

前端将 `code`、HTTP 状态和受控结果状态映射为短文案，不直接展示内部前置条件串。后台运行历史显示稳定的错误类型和限长、脱敏摘要。

### 3.5 认证和 Session 边界

认证边界保持服务端化：

1. `/api/settings/domain-login` 通过 `ArasECMAuthClient` 建立 Session，并将 Session 对象放入当前 Web 进程的 `DomainSessionRegistry`。
2. `_build_aras_client_from_payload` 在 `auth_mode="browser"` 且请求没有显式敏感头/ Cookie 时取共享 `aras` Session。
3. `DomainSessionRegistry.payload()` 只返回认证状态和时间戳，不返回 Session、Cookie 或 Token。
4. `_request_payload` 和详情刷新使用现有本机访问/Origin 防护；不能从远程主机触发详情查询。
5. Session 不存在或过期时返回未认证；不得通过关闭校验、回退到明文密码或复制浏览器 Cookie 来“修复”交互式刷新。

### 3.6 重试

项目状态 `RetryingConnector` 和归档 `ArchiveSyncRunner` 对连接/超时类错误执行已有上限内的重试；补充 native WinHTTP 错误类型，使 Windows 生产传输的超时也进入同一重试边界。认证失败和凭据 provider 失败不重试，避免重复提交无效凭据；它们记录运行结果并留给后续人工处理。

## 4. 目标调用链

### 4.1 EWO 交互式立即刷新

```text
EWO 详情页按钮
  → build EWO query filters from non-sensitive matchRule
  → POST /api/aras/ewo/query
  → _request_payload (loopback/origin guard)
  → _build_aras_client_from_payload(auth_mode=browser)
  → DomainSessionRegistry.session("aras")
  → ArasCrawlerClient.query_ewo_report
  → ApplyItem SOAP + XML parser
  → redacted rows/count/queryState
  → detail temporary result panel
```

### 4.2 PAA 交互式立即刷新

```text
PAA 详情页按钮
  → convert stored non-sensitive archive filters to PAA query filters
  → POST /api/aras/paa/query
  → _request_payload (loopback/origin guard)
  → _build_aras_client_from_payload(auth_mode=browser)
  → DomainSessionRegistry.session("aras")
  → ArasCrawlerClient.query_paa_report
  → ApplyItem SOAP + XML parser
  → redacted rows/count/queryState
  → detail temporary result panel
```

### 4.3 EWO 定时同步

```text
Task Scheduler → main.py project-status-sync --once
  → ProjectStatusSyncRunner.run_once(validate_runtime_prerequisites=False)
  → fixed binding guard: exists/enabled/automatic-or-hybrid/source
  → DatabaseManager.acquire_sync_lease(..., validate_runtime_prerequisites=False)
  → start run
  → Windows credential provider.resolve(opaque ref)
  → ArasECMAuthClient.login
  → ArasProjectStatusConnector.collect
  → snapshot/match/mapping validation
  → atomic business/audit/artifact finalization
```

### 4.4 PAA 定时归档

```text
Task Scheduler → main.py scheduled-archive --once
  → ArchiveSyncRunner.run_once(trigger_type="scheduled")
  → ArchiveSyncRunner.run_job(validate_runtime_prerequisites=False)
  → fixed job contract/enabled guard
  → DatabaseManager.acquire_archive_job_lease(..., validate_runtime_prerequisites=False)
  → start run
  → credential provider.resolve
  → ArasArchiveConnector.collect
  → retryable external query/download
  → artifact finalization or redacted failure finalization
```

## 5. 文件边界

主会话直接负责：

- `web/app.py`：查询错误分类、Session 复用边界、ARAS 查询兼容契约；
- `services/project_status_sync_runner.py`：项目状态异常分类、重试边界和真实连接器执行顺序；
- `services/scheduled_archive_runner.py`、`core/db_manager.py`：归档定时租约参数和运行语义；
- 认证、凭据、租约和所有跨模块接口的最终审查。

受限 AGY 可负责：

- `web/static/app.js`、`web/static/style.css` 的按钮、状态、临时结果和错误文案；
- 独立的静态 UI/契约测试函数；
- 不涉及认证、Session、租约或公共数据模型的机械调用点与文档整理。

AGY 不得修改认证实现、凭据 provider、Session registry、数据库 schema 设计、租约并发语义或公共 API 决策。

## 6. 测试设计

测试必须先写失败用例，再实现最小变更，并把输出写入 `.runtime/`。

### 6.1 交互式查询

- EWO 详情立即刷新请求 `/api/aras/ewo/query`，不请求 project-status sync-now；
- PAA 详情立即刷新请求 `/api/aras/paa/query`，不请求 scheduled-archive sync-now；
- 两条详情链路不发送 credential reference、密码、Cookie、Authorization、mapping 或 stable-key readiness 字段；
- 独立 EWO 搜索与 EWO 详情刷新使用相同 endpoint/filter/crawler method；
- 独立 PAA 搜索与 PAA 详情刷新使用相同 endpoint/filter/crawler method；
- 共享 Session 身份被复用，Session 状态响应不泄露 Session 内容；
- 无 Session、Session 失效、服务不可用、查询失败、零行和目标未匹配分别得到稳定状态；
- EWO/PAA 结果继续过滤 `raw_xml` 和敏感字段。

### 6.2 定时同步

- project-status 定时运行在缺少 credential、external key、match rule、mapping 或 stability 时仍先创建 run/进入 connector；
- 真实 project-status connector 仍调用 credential provider.resolve 并执行认证/查询；
- credential provider 缺失、认证失败、服务不可用和超时写入脱敏 error type/message；
- PAA scheduled archive 在缺 credential ref 时不在 lease 前零运行退出；
- 认证失败不重试，网络/WinHTTP 超时按上限重试；
- 手工后台触发默认 readiness 行为保持兼容。

### 6.3 UI 回归

- 前端按钮在 interactive 模式下不被后台 readiness 禁用；后台同步按钮仍受后台策略控制；
- 错误文案只显示五类稳定状态，不显示内部前置条件长串；
- 既有部门/阶段/车型筛选、标签、图表和自定义图表分组继续工作；
- Debug JSON/ZIP/复制摘要继续过滤敏感字段；
- 运行静态 UI 契约、聚焦后端测试、全量回归、编译、Lint/type baseline 检查和 `git diff --check`。

## 7. 非目标

- 不把交互式查询结果自动写入项目状态或后台归档；
- 不让详情页绕过后台同步的权限、凭据、稳定键或映射安全校验；
- 不把浏览器 Cookie、Authorization 或密码复制到 localStorage、URL、数据库或普通日志；
- 不新增前端框架、外部 CDN 或新的认证方式；
- 不重置、覆盖或回滚现有未提交工作区改动。

## 8. 回滚与限制

实现采用增量 API/UI 变更。回滚时只需撤销本阶段新增的实现提交和对应测试/文档提交，不得使用 `git reset --hard`、`git clean` 或恢复整个工作区。由于当前工作区已有用户改动，回滚操作必须按文件和提交逐项确认。

已知限制：

- 交互式查询复用的是当前 Web 进程的服务端 Session；Web 进程重启后需要重新登录；
- Session TTL 到期后不会自动静默续期，用户必须重新执行统一登录；
- 交互式刷新是临时查询，不会立即重建后台分析缓存；分析图表仍反映最近一次已发布的后台快照，并会显式标注来源；
- PAA/NCR 的官方归档产物仍依赖后台归档任务，交互式 PAA 查询只展示查询结果。

## 9. 验收门禁

只有以下条件全部满足才能判定 PASS：

- EWO 交互式立即刷新调用现有 EWO 查询链路并可显示结果；
- PAA 交互式立即刷新调用现有 PAA 查询链路并可显示结果；
- project-status 与定时归档运行不因运行时凭据/匹配配置在租约前零运行阻断；
- 真实连接器认证、重试、失败审计和脱敏仍有效；
- 五类交互式错误状态可区分显示；
- 筛选、标签、图表和 Debug 脱敏无回归；
- 聚焦测试、全量测试、编译、Lint/type 检查和 diff 检查均达到项目基线；
- 最终主会话 Review 与 code-reviewer 结论为 `PASS`。
