# SOR 导出故障分析与优化任务

> 状态：Reference / Task Dossier
> 读者：Developer、Agent（SOR 故障复盘）
> 权威来源：当前代码、测试和生产复测证据；本文是问题过程记录
> 默认读取：仅 SOR 故障或生产复测任务

分析日期：2026-09-09。范围：离线生产证据、当前代码、关联任务和合成复现；本轮不修改业务代码，不使用生产凭据访问上游。

## 结论与证据边界

交付物下载的直接失败原因已定位：TDC 官方导出链路返回业务错误 JSON（code=1），工具按规则拒绝将它当作 XLSX。本机 Web API 将该异常映射为 HTTP 502。这个 502 不是已证实的 TDC 上游 HTTP 状态。

现有材料不能确定上游为什么返回 code=1。HAR 的 114 条请求全部发往 127.0.0.1:5000，没有工具到 TDC 的请求/响应，也没有官方 TDC 网页成功导出的对照请求。参数差异、导出专属权限、服务端数据/模板异常都是待验证假设，不能将其中任何一个写成已确认根因。

另有三个已确认的本地缺口：车型名称与内部 ID 的链路不完整；自动下载抹去了错误阶段与原因；15 列预览缺少足够列宽，下载失败时仍展示前次预览，造成混淆。

## 生产时间线（北京时间；HAR entry 从 0 计数）

| 证据 | 观察 | 可得结论 |
|---|---|---|
| entry 77、79；19:15:20–19:15:21 | `tdc_sor/sync-now` 返回 HTTP 200，但业务结果 exitCode=1、run 6 failed、query_failed | HTTP 200 仅表示本机接口正常响应，任务没有成功 |
| entry 80；19:16:47 | 手输车型 F610S，list 查询 total=0 | 该筛选未得到数据；不能单凭空结果断言上游无此车型 |
| entry 81；19:17:02 | 改为部门筛选，list 查询 total=10767、pages=216、当前页 50 条 | 列表链路可用；50 条只是当前页，不是全量导出 |
| entry 82；19:17:09 | 同一部门条件 export 返回本机 HTTP 502，`TDC export API error code 1: TDC export API returned JSON instead of an XLSX file` | 下载失败于取得有效官方文件之前；这次请求没有车型条件 |
| entry 85/86、93/94 | SOR 表单 rowCount=0、artifacts=[] | 无成功 SOR 快照可展示 |
| 只读数据库 | run 1–5 成功，run 6 SOR 失败；run 6 产物数为 0；无 SOR 表单快照 | 与 HAR 和截图一致 |
| 输出目录 | 有 EWO、PAA、NCR、TDC 数模产物，无 SOR 产物 | 没有 SOR XLSX 可做文件修复；也不是已下载后 Excel 打不开 |

HAR 中 JS 解码并去除 BOM/换行差异后与当前 `web/static/app.js` 一致，CSS 规范化换行后也一致。当前前端问题不能简单归因于旧包或浏览器缓存；这不证明生产 EXE 的全部后端字节与当前源码一致。

## 与此前 SOR 任务的关系

关联任务 `01a03d2d-cea7-7de2-a054-936dd9add685` 曾落实：15 列表头、车型对象展开、内部项目 ID、快速 list 与官方 Excel 精确预览、单元格换行。该任务也明确未以生产账号完成线上导出验收。

当前后端仍保留项目列表接口及 `car_type_project_id`；前端只保留手输文本。`tests/test_deliverables_web.py:474` 还明确禁止前端出现项目列表入口及 ID 字段。Git `-S` 将此测试变化定位到 `623d4f2`，因此应按当前产品行为重新设计，而不是宣称历史功能全部仍然存在。

另一个关联任务 `01a07c01-8bd5-7ee0-a03e-dd78be0c0390` 确认优先节省 Codex、使用订阅 Gemini。实际本机配置现为 `gemini-3.8-flash-high`，不硬编码历史 3.7 名称。

## 本地根因与风险

1. **导出响应校验正确，故障可诊断性不足。** `services/tdc_crawler.py:365` 使用 `/sp/sor/export`；`_export()` 在 JSON code 非成功时抛异常；`_export_json_summary()` 只提取顶层 msg/message/error 的标量。截图中的通用句子是本地兜底文案，并非已获得的 TDC 具体报错说明。不能据此推断上游返回了哪种嵌套结构。
2. **自动下载错误被统一化。** `services/scheduled_archive_runner.py:92`、`:101` 将 TDCCrawlerError 归为 query_failed，返回固定文案。它保护了敏感信息，但同时丢失 stage、request_id、上游状态及业务码。自动下载失败与交互导出可能共享根因，但 run 6 具体是哪次上游调用失败，当前证据不能完全还原。
3. **车型 ID 不完整。** `TDCSORFilters.to_params()` 无 ID 时把显示文本放入 `carTypeProjectAll[0]`。`web/static/app.js:8072` 只提供文本框；归档连接器 `_sor_filters()` 不接受内部 ID。此缺口可解释车型筛选风险，不能解释 entry 82 无车型条件的导出失败。
4. **导出失败不会进入 list 兜底。** `services/scheduled_archive_connectors.py:456` 先执行官方导出；只有已经取得文件但读取结果为 None 时才走 list。因此“查询能成功”并不意味着自动下载能成功。若新增降级，必须另立“列表数据快照”语义；不能把流程粒度 list 冒充零件明细粒度官方 Excel。
5. **换行不等于可读。** `.result-table` 最小宽度只有 680px；15 列普遍 `overflow-wrap:anywhere` 且没有按列最小宽度。截图中长编号、标题与日期被逐字折行。`runDeliverableOperation()` 的失败路径只显示错误，保留原结果和查询标识，容易让人误以为表格就是本次失败操作的结果。
6. **重试设置不是任意错误重试。** `_collect_with_retry()` 只捕获瞬时错误；TDCCrawlerError 不在集合内。run 6 attempt=1 不足以证明重试机制坏了，也不应通过把全部业务错误加入重试来掩盖问题。

## 优化顺序与任务分工

| 任务 | 负责与范围 | 验收标准 / 前置条件 |
|---|---|---|
| SOR-01 安全诊断契约 | Codex 定义异常字段、脱敏边界及状态语义；Gemini 按固定合成场景补测试 | 允许记录 source、operation、stage、request_id、HTTP 状态、业务码、响应键名与安全原因；缺失原因明确标识；不持久化原始响应、Cookie、凭据、业务行 |
| SOR-02 诊断实现与错误展示 | 契约固定后，Gemini 在隔离 worktree 修改 crawler/runner/Web/UI 及对应测试；Codex 审核安全部分 | 手动/自动导出都能定位失败阶段；旧 query_failed 兼容；失败不写假 XLSX、不覆盖最后成功快照；合成敏感文本不泄漏 |
| SOR-03 上游契约比对 | Codex 判断请求差异与根因；Gemini 整理已脱敏字段对照 | 同账号、同筛选、同时间段在官方 TDC 页面导出；比较方法/路径/参数键/ID、pagePath、安全请求头结构及响应。若官方也失败，带关联标识交 TDC 维护方；若仅工具失败，做最小单变量修复 |
| SOR-04 车型筛选闭环 | Codex 固定显示名/ID与歧义处理；Gemini 实现选择/解析、两个入口及回归测试 | 查询与导出使用同一解析结果；手工名称唯一匹配才转 ID，空/重复/失效值明确报错；自动下载支持等价语义；替换“禁止 ID”的旧测试 |
| SOR-05 预览体验 | Gemini 独立负责 app.js/style.css 及 UI 测试；Codex 实测 | 15 列按语义设宽度、横向滚动；编号日期可读、标题有限换行；导出失败标明旧预览的时间/筛选；快速模式与官方模式粒度清晰；不改其他报表表头 |
| SOR-06 验收与打包 | Gemini 做已定义回归和说明；Codex 集成、回归、打包及最终结论 | 官方 XLSX 能由解析器读取、表头/行数/筛选与官方对照一致；自动归档文件、hash、快照匹配；故障状态/敏感信息检查通过；生产验收独立于离线测试 |

优先 SOR-01/02，使下一次生产复测能定位；SOR-04/05 可以在契约固定后并行推进；SOR-03 决定真正的导出协议修复内容。默认不引入自动降级成功；需要可用性降级时，单独设计 partial/needs_attention、来源和粒度标签。

Gemini 任务均通过 `C:/Users/Lynch/.zcode/tools/run-worker.ps1 -Workspace E:/project/vse-toolbox -TaskFile <contract.json>`，每个合同包含 task_id/objective/scope/constraints/acceptance_criteria/risk_class/verification_commands（参数数组）。禁止接触原始生产材料；测试使用合成响应。批量分配相关改动，最多两轮定向修复；模型/额度/权限错误停止，不隐式改用其他模型。Codex 审查实际 diff 和外部测试输出后再集成，不自动 merge/push。

## 本轮验证

- 当前源码相关基线：`python -m pytest tests/test_tdc_crawler.py tests/test_deliverables_web.py tests/test_scheduled_archive_connectors.py tests/test_scheduled_archive_runner.py -q`：**133 passed**。
- 离线合成探针重现 code=1 文案、归档错误压缩、JSON 不写文件、文本被用作关联 ID、归档拒绝 ID 字段。它证明当前代码行为，不能证明上游业务报错原因。
- 11 个已登记产物的文件大小及 SHA-256 全部与数据库一致；3 个 XLSX 的 ZIP 完整性通过。此检查不等于工作簿业务内容正确，也不包含不存在的 SOR 文件。证据：`.runtime/sor-analysis/artifact-integrity.json`。
- 本地证据：`.runtime/sor-analysis/baseline-tests.log`、`reproduce.py`、`reproduce-result.json`。原始 HAR、截图和数据库保留原位，未读取 DPAPI 内容。
- ZCode Gemini 审查任务：`TASK-sor-analysis-20260909` 已完成，模型 `gemini-3.8-flash-high`，78 次受 guard 检查的读取/搜索，约 364 秒；外部 supervisor 聚焦检查 **70 passed**（与主审 133 项有重叠，不相加）。实际 diff 和 changed_paths 均为空，进程树已停止。合同限定只读，本次实际只有 Read/Grep/Glob；运行器暴露了 Edit/Write 能力，故不可把合同只读描述成工具级只读隔离。

## Gemini 审查的主审裁决

- 采纳：JSON 拒绝及异常传播、无车型选择器、导出失败不进入 list 兜底、旧结果残留、缺少列宽约束，均与本地证据相符。
- 纠正：报告称归档 `_TDC_SOR_KEYS` 已包含 carTypeProjectId，实际不包含；离线探针也确认拒绝此键。
- 纠正：不存在 `tests/test_tdc_web.py` 不代表没有 Web 测试；已有 `tests/test_deliverables_web.py` 覆盖相关路由。新增场景应扩展现有测试，避免新建重复测试文件。
- 排除本次根因：通用 `orderedColumns()` 的 12 列限制确实存在，但本次响应带 headerRows 和 15 列契约，走另一分支。不能据此认定生产 SOR 丢了 3 列。
- 次优先候选：SOR 下载未复用精确预览缓存、项目状态连接器筛选字段较少。两者可以后续优化，但不能解释上游首次导出 code=1；缓存变更还须单独核对身份隔离、参数键和时效契约，不混入本轮修复。
- 成本控制：本次 Gemini provider 统计含大量缓存读取，不能据此换算费用或 Codex 节省比例。后续应缩小每批文件范围，给定函数/行号和测试清单，减少全文件重复读取；不以减少复核替代任务质量。

本轮没有修改业务源码或执行生产导出。完整审查结果与空 diff 在 `.agents/runs/TASK-sor-analysis-20260909/`；应以本报告的主审裁决为准。
