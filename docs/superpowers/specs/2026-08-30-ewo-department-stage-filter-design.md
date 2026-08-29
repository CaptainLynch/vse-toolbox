# EWO 科室与流程阶段筛选设计

## 目标

修正 EWO 项目状态同步范围与逾期统计口径：默认只同步车身科、车体科、外饰科、内饰科、车体架构集成科五个科室；统一 EWO 阶段为 `open`、`draft1`、`draft2`、`edit1`、`edit2`、`proc`、`impl`、`close`；`open` 默认不计入统计，`close` 视为流程终点且不逾期，其余未关闭阶段按截止日期判定逾期；交付明细支持科室和阶段筛选。

## 选定方案

采用“上游 EWO 查询过滤 + 本地显式阶段模型”。同步连接器在 Aras 查询层使用 EWO 科室字段 `_rsp_smt` 的受控五科室并集条件，避免先拉取全量后本地丢弃；`_rsp_department` 仅表示上级部门，不用于本需求的科室筛选。分析缓存增加独立的 `source_stage` 字段，与通用 `source_status` 解耦；仅 `source_type=aras/ewo` 的记录从 EWO `state` 规范化后写入该字段。未知阶段保留原始状态并进入待处理路径，不猜测映射。

## 领域规则

```text
EWO_DEFAULT_DEPARTMENTS = 车身科、车体科、外饰科、内饰科、车体架构集成科
EWO_STAGES = open、draft1、draft2、edit1、edit2、proc、impl、close
EWO_ACTIVE_STAGES = draft1、draft2、edit1、edit2、proc、impl
EWO_TERMINAL_STAGE = close
EWO_IGNORED_STAGE = open
```

- EWO 项目状态同步统一使用 `_rsp_smt` 的默认五科室；本次不开放同步规则自定义科室键，避免旧绑定契约遗漏后退化为全量查询。
- `open` 默认排除，不计入总数、逾期数和默认明细列表；可以通过阶段筛选显式查看。
- `close` 视为完成，不判定 `overdue`、`due_soon` 或缺少截止日期提醒。
- `draft1` 至 `impl` 按 `planned_date` 判定逾期、临近到期和缺少截止日期。
- 未知阶段不进入正常阶段统计，保留原始 `source_status`，返回 `stage: null` 与 `stageAttention: true`，并形成待处理证据；不得计入 `total/incomplete/overdue`。

## 数据与 API

`project_status_analysis_items` 增加可空的 `source_stage TEXT` 字段，初始化与迁移必须幂等。同步 Runner 的发布链路显式传递 `source_type`，分析服务只对 EWO 来源写入该字段；旧缓存中的该字段为空，下一次 EWO 同步重新填充，不对历史值进行静默推断。

扩展现有接口：

```text
GET /api/project-status/deliverables/<deliverable_id>/analysis/items
    department=<规范化科室，可选>
    stage=<all 或 EWO_STAGES，可选>
```

- 未传 `stage` 时，EWO 默认排除 `open` 和未知阶段。
- `department` 和 `stage` 必须同时作用于列表、总数和分页；`alert` 分支也必须在 SQL/缓存筛选阶段应用两者后再计算提醒。
- 返回项新增 `stage` 字段和布尔 `stageAttention`，保留 `status` 兼容现有消费者。
- 非 EWO 交付物继续使用现有通用状态逻辑，`source_stage` 可为空。

## 模块职责

- `services/project_status_connectors.py`：构造 EWO 默认/显式科室过滤器，保持同步连接器边界。
- `services/aras_crawler.py`：增加/沿用 EWO `_rsp_smt` 科室查询字段和多值条件生成逻辑；保留 `_rsp_department` 的上级部门语义。
- `services/project_status_sync_runner.py`：在分析缓存发布时传递 `source_type`，确保 EWO 阶段规则不影响 TDC/其他来源。
- `services/project_status_deliverable_analysis.py`：阶段别名解析、缓存字段填充、阶段化统计与逾期判定。
- `core/db_manager.py`：缓存字段迁移、写入、阶段过滤查询及计数。
- `web/app.py`：解析和校验 `department`、`stage`，序列化阶段字段。
- `web/static/app.js` / `web/templates/dashboard.html` / `web/static/style.css`：交付明细筛选器、阶段列和状态样式。

## 测试与验收

覆盖默认五科室 `_rsp_smt` AML、旧绑定仍被安全限制、八阶段规范化、`open` 排除、`close` 不逾期、活动阶段日期逾期、未知阶段待处理且不计数、API 组合筛选/未知部门 422、分页和 alert 分支一致性、前端控件与阶段列、source_type 隔离，以及 TDC 不可访问不阻断 EWO 的回归场景。

不得改变 TDC 登录、查询和契约；不得新增依赖；不得将凭据或敏感上游响应写入日志、数据库或 API。

## 第一轮浏览器反馈修订

- 科室与阶段筛选改为可搜索多选 token 控件，支持手动输入并回车确认。
- 筛选工具栏提供“应用筛选”和“清除筛选”，应用时重置分页并提交多值参数；兼容旧单值参数。
- 查询参数支持重复键：`departments=...&departments=...`、`stages=...&stages=...`。
- 后端将重复键解析为去重后的 `Sequence[str]`；每类最多 20 个值、单值最多 120 字符，拒绝控制字符。`stages` 只能是八个规范阶段或 `all`；`departments` 使用参数化 SQL，未知科室返回空结果而不拼接 SQL/AML。
- 为兼容旧客户端：若存在 `departments`/`stages`，优先使用它们；否则读取单值 `department`/`stage`。
- 对历史缺失 `source_type/source_stage` 的 ARAS EWO 缓存，根据交付物来源回退识别 EWO，并重新计算当前汇总，确保 `close` 不显示逾期。
- 回退仅适用于交付物来源精确归一化为 `ARAS EWO` 的 `VPI-T2-D3`；读取时将旧行的 `source_status` 规范化为阶段，汇总从当前明细重算并只更新响应，不静默改写历史快照。
- EWO 详情状态图表增加最近同步状态、同步时间、立即同步和刷新同步数据入口；同步完成后重载状态、摘要和明细。
- “立即同步”调用既有 `POST .../sync-now`；“刷新同步数据”只执行 GET 重新读取，不触发上游同步。两按钮在请求期间禁用，失败显示脱敏错误，完成后重新渲染当前详情。
- 当前状态图表保留手工交付物进度，同时增加独立的 EWO 同步摘要区（总数、已完成、未完成、逾期、最近快照）；摘要由分析 GET 返回的数据填充，不把外部统计覆盖手工进度字段。

## 第二轮浏览器反馈修订

- 科室、阶段下拉候选框使用不透明的主题表面色、边框和层级，不能透出表格内容；多选控件继续支持搜索、回车录入任意新增科室名称，并在应用后作为参数化筛选条件提交。
- 阶段筛选值和表格阶段列统一显示大写 `OPEN`、`DRAFT1`、`DRAFT2`、`EDIT1`、`EDIT2`、`PROC`、`IMPL`、`CLOSE`；接口内部仍使用小写规范值。
- 明细表的“状态”列只表达提醒状态：`超期` 或 `未超期`；“阶段”列表达 EWO 流程阶段，不再将阶段值混入状态列。`CLOSE` 不得标记超期。
- “待签署人员”按角色分行显示，格式为 `ROLE:人员`，至少支持 `PE`、`LEADER`、`MAJOR`、`SQE` 及上游出现的其他角色；没有待签署信息时显示“无”。解析保留角色与姓名，不把负责人字段误当待签署人员。
- “更新方式”对 EWO 显示三种策略：手动维护、自动同步、混合模式；当前推荐自动同步，策略展示与字段映射配置保持独立，未配置映射时不得伪造同步结果。
- 当前状态图表中的进度明确标注为“项目手工进度”；EWO 同步统计单独展示总数、已完成、未完成、逾期和最近同步时间，并说明统计来自最近一次 EWO 快照。
