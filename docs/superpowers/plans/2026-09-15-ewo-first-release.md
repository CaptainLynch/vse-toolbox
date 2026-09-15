# EWO First Release Implementation Plan

> **For agentic workers:** Execute tasks against the fixed contracts below. Use the installed local ZCode supervisor for delegated work; no automatic provider fallback. Parent reviews and verifies every diff.

**Goal:** 修正EWO绑定语义，增加官方导出只读增强，在不改变旧绑定字段所有权的前提下建立可审计的来源与关联合同。

**Architecture:** 列表为基础快照，官方导出为独立只读增强快照；共享展示但不授权增强字段写回。版本化合同先于界面开放，持久生成状态机区分结果未知与可恢复下载。

**Tech Stack:** Existing Python/Flask/SQLite/vanilla JS, stdlib XLSX reader, local ZCode Gemini worker.

**Spec:** docs/EWO_ARCHITECTURE_REVIEW_20260915.md（评审修订优先于原提案）。原证据 docs/EWO_MAPPING_EVIDENCE_ARCHITECTURE_20260915.md。

## Global Constraints

- 用户2026-09-15已授权启动更改及任务拆分，优先降低GPT-6额度消耗；不需要再次批准同一范围。
- GPT主控拥有架构、身份/签名、凭据/下载边界、事务并发、迁移与最终集成。Gemini只能执行已定合同。
- 首期增强字段只读，PAA/NCR扩展后置；不增加待签人员自动写回。旧绑定不静默改变字段所有权。
- 真实HAR、Excel、生产数据和凭据不派发、不复制入测试；合成数据仅模拟结构和计数。
- 写worker必须隔离工作树。已有脏文件禁止覆盖，重叠任务留主控或在经过审核的干净来源快照上重新计划，不伪造低风险标签或放宽守卫。
- provider/timeout/quota/permission失败停止该路线，不自动换供应商，不自动转GPT实现所有任务。
- 不自动commit/merge/push，不运行真实导出。详细输出写.runtime/ewo-v2/，持久结论在memory/与本计划。

## 已冻结的主控决策

1. sourceItemId仅表示固定版本记录，不宣称跨修订稳定。entityKey首期不推导；业务编号只用于唯一关联。失效版本需要重新确认，不自动跟随同号。
2. 首期基础分析身份可识别无编号行，但已有legacy写回继续使用现有业务编号合同。新身份不能直接进入旧发现/执行链。
3. v2模式显式single_record/record_set，旧aggregate只供兼容解释。新增v2写配置必须有合同版本和新签名，未经迁移取证不得启用；旧客户端拒绝修改v2。
4. 首期不改变已有legacy的1条/多条写回规则；UI应标注旧规则。新record_set负责人/日期固定手工，不能随结果数量切换。
5. 官方导出只读快照不传入ConnectorCandidate或mapping discovery。字段缺失与空值分开；不会自动清空备注。
6. 状态原始计数全部保留；completed只计CLOSE，cancelled只计CANCEL，OPEN独立，其余已知活动阶段单列/归组，未知单列。首期不新增有争议的完成率分母；缺编号计数是独立质量指标，不从总数扣除。
7. 仅业务编号在两侧均唯一时关联；不按行号、顺序、车型或标题猜测。4条空编号数据作为只读未关联行保留。
8. 生成前持久化任务；所有无法证明未执行的生成异常归generation_unknown，禁止自动重发。已保存file引用才可恢复下载，token只驻内存。

## 分工与依赖

| 任务 | 所有者/模型 | Owned files | 依赖与风险 |
| --- | --- | --- | --- |
| T0 版本/迁移合同 | GPT主控 | core/ewo_contracts.py（拟新增）、现有能力/签名/更新门禁修改 | 高风险；先定义合同再编码，不能整体改共享identity优先级 |
| T1 只读关联与状态纯函数 | ZCode Gemini Flash | services/ewo_readonly.py、tests/test_ewo_readonly.py（均新增） | 已有精确接口和场景，可独立派发，无网络/数据库 |
| T2 XLSX解析适配 | ZCode Gemini Flash | services/ewo_workbook.py、tests/test_ewo_workbook.py（新增） | 依赖T1；读取现有xlsx_preview接口的审核摘要；错误dimension、111列、截断拒绝 |
| T3 官方导出与持久恢复 | GPT主控 | services/ewo_export_jobs.py（新增）、services/aras_crawler.py、core/db_manager.py、对应安全/恢复测试 | 高风险；生成副作用、租约、下载认证及迁移不得交机械worker |
| T4 只读增强界面组件 | ZCode Gemini Flash | web/static/ewo-enrichment.js、tests/ewo_enrichment_ui_contract.test.js（新增） | 依赖冻结API；只渲染状态和显式操作，不负责认证/路由 |
| T5 Web装配与策略兼容 | GPT主控 | web/app.py、web/static/app.js、core/project_status_contracts.py、模板引用与集成测试 | 当前脏文件且公共合同，主控小范围补丁 |
| T6 独立终审 | ZCode Gemini Pro | 只读已完成任务精确diff/文件，不拥有生产写权限 | 不重复全库探索；重点审查漏场景、合同一致性；主控负责安全定案 |
| T7 发布验证 | 主控运行本地命令 | focused/full日志、地图、复测包与说明 | 通过才生成EXE；无线上验收成功宣称 |

Flash批量处理相邻纯函数/测试，不每个函数单开会话。Pro只用于确有复杂性且已获输入的终审，不作为Flash失败的隐式fallback。预计可派发的是新增纯函数、解析器、UI组件与大部分合成测试；不能在实现前承诺精确token节省百分比。

## T0: 合同与兼容

- [ ] 定义v2配置/数据快照边界及固定Item ID语义，列出全部字段与版本。
- [ ] 写失败测试：legacy回读不变；未知v2拒绝；模式与签名不一致拒绝；旧客户端不能改v2。
- [ ] 运行红灯后最小实现；逐步接入发现、预览和执行，禁止只改前端。
- [ ] focused验证及迁移差异审查后开放v2保存。

## T1: 只读关联纯函数（已生成正式worker合同）

文件与接口：services/ewo_readonly.py。

`associate_export_rows(base_rows, headers, export_rows) -> dict`：base输入id/_no；两侧非空唯一编号才匹配；每导出行输出1-based row_index、status、source_item_id、business_number、fields。状态matched/unmatched/ambiguous/blank_number；计数分区总和等于export_count。>5000行、>200列、空/重复表头、缺EWO编号、行超宽、空/重复源ID抛ValueError。仅trim字符串，不更改大小写、不截断、不猜测。

`summarize_states(base_rows) -> dict`：total/completed/cancelled/open/other/unknown/missing_business_number；除missing外分类计数总和为total。CLOSE/CANCEL/OPEN分别计数，DRAFT1/DRAFT2/EDIT1/EDIT2/PROC/IMPL为other，其余unknown。

- [x] 合同已落盘 `.agents/tasks/ewo-readonly-normalize-20260915.json`。
- [x] 调用官方launcher，预检route为Flash，静态配置通过。
- [ ] Worker执行：网络预检deadline超时，当前未执行；见下方阻塞。
- [ ] Worker先补测试，主控验红（必要时测试阶段单独交付）；再实现，主控检查实际diff。
- [ ] `python -m pytest tests/test_ewo_readonly.py -q`。
- [ ] 用410合成行/406非空/4空及重排序确认不会按位置绑定。

## T2: 工作簿适配（待T1及运行器恢复）

`read_ewo_workbook(path) -> {headers, rows, sheet_name, truncated}`，仅Innovator工作表，按表头读取，不信任dimension。复用现有大小约束；截断或缺关键表头不能作为完整增强快照。输出交给T1，不擅自加身份或日期猜测。raw字段只留本地快照，由Web安全边界决定显示，worker不处理认证。

- [ ] 合成真实OOXML夹具：dimension只到1行但有410数据行，表头111列；另测正常范围、缺表头、重复表头、超限、损坏ZIP。
- [ ] 由主控提供现有reader精确接口，禁止worker为找接口扫描全库。
- [ ] 写测试→验红→实现→focused→diff复核。

## T3: 导出任务状态机

建议状态queued/generating/generation_unknown/generated/downloading/parsed/failed，错误阶段单独存。任务保存source scope、actor/credential scope引用、ID集合摘要、snapshot引用、generation/file引用、attempt、lease与时间；不得保存token/密码。状态变化事务比较版本，下载锁/租约不能让另一进程重新生成。

- [ ] 先定义持久表和受限API，明确重启如何处理过期generating租约。
- [ ] 失败测试：发送前/发送后/响应返回尚未持久化/下载中崩溃；未知禁止重发；生成后新token下载；双请求只有一条生成；不同账号隔离。
- [ ] 验证下载目标allowlist、跨域重定向、HTML假文件、文件大小、token日志脱敏。
- [ ] 完成受控实现后再接Web；不借用可能自动重试的通用connector包裹生成调用。

## T4/T5: 界面与装配

- [ ] 冻结API后创建只读组件：分别显示基础和增强时间、关联计数、generation_unknown恢复提示；不会自动生成。
- [ ] 集合不显示唯一键；legacy显式说明旧规则；新v2字段能力与后端一致。
- [ ] 加载/失败/空/过期/未关联状态用确定性JS测试；请求失败保留上次成功数据但标记时间。
- [ ] Web本地写保护、登录身份、任务授权由主控实现并集成测试，不能由组件决定权限。

## T6/T7: 终审与交付

- [ ] Pro只读审查具体变更与验收矩阵，主控核验报告，对同一原因最多两次修复。
- [ ] focused→全量pytest→JS契约→地图检查→哈希和EXE隔离启动。
- [ ] 发布说明明确真实内网尚需验收；保留用户data，不覆盖现有业务资料。

## 2026-09-15 实际派发结果与恢复点

前两次合同路由在主控阶段停止，原因是objective中写了排除database等职责的文字被风险关键词识别；没有worker启动。随后把objective准确限定为纯行关联/计数，所有边界仍保留在constraints，正常进入Flash预检，未放宽守卫/权限。

有效任务：TASK-ewo-pure-association-20260915。静态预检passed，Gemini Flash High工具能力配置可用，网络预检 `Worker deadline exceeded`，状态preflight-blocked，failure_code=transport，worktree=null，round=0。没有worker代码产出，没有自动GPT接管。

当前阻塞仅Gemini执行通道；主控已完成分工和接口合同。恢复后使用新唯一task_id重新启动T1（旧run不可复用），先确认ZCode交互环境中同Gemini模型可响应；不要切换供应商或擅改网络deadline。T2/T4/T6未派发，避免在同一失败条件下重复消耗。

## 2026-09-15 恢复执行检查点：基础模块已集成，未发布

最新运行配置已是Flash-only，旧Pro槽位仅兼容别名；本计划T6应使用当前Flash模型独立审查，不请求已移除的Pro模型。

- TASK-ewo-pure-association-20260915-resume1：网络预检26.281秒passed，隔离worker完成，外部初测11 passed。主控审查发现状态值被错误upper，修正测试后观察1 failed，再移除大小写推断，恢复通过。
- TASK-ewo-workbook-adapter-20260915：隔离worker产出适配器和OOXML测试；外部13 passed/1 failed（错误文本regex大小写）。主控核对功能后仅调整断言大小写，未放宽校验。
- 已审查集成新增services/ewo_readonly.py、services/ewo_workbook.py及对应测试；无自动merge/commit。两个worker原工作树保留。
- 主控新增core/ewo_export_jobs.py与services/ewo_export_transport.py及对应测试。提供互斥claim、过期生成unknown、下载恢复；官方生成一次请求、禁止redirect、固定方法；下载同源检查、新token、不重试生成、固定本地文件名与有界ZIP校验。尚未接入生产API。
- 6套件105 passed / 1.59s；生产新增4模块flake8与diff空白检查通过。真实附件离线只读：410/410，matched406、blank4、unmatched0、ambiguous0；CLOSE233/CANCEL27/OPEN3/其它活动147，总数410。
- T1/T2完成；T3仅存储与传输底层完成，账号身份范围绑定、编排、错误恢复交互尚待实现。T0 v2身份签名与legacy迁移、T4/T5页面/API和T6终审/T7全量发布未完成。未生成EXE，不宣称整体上线或真实内网恢复。
- 下一原子任务：定义可证明账号身份的scope与来源/查询签名，接入持久编排；现有DomainSessionRegistry只存session对象/过期时间，不能以对象id或统一domain常量当跨重启账号身份。必须在登录成功时记录明确主体上下文后才能开放恢复端点。

## 2026-09-15 只读增强Web集成检查点
- 三个Flash worker均实际产出，第三个为只读面板。主控修复无效新任务ID与旧状态混用；补恢复入口、账号来源隔离、持久上下文/快照和DownloadToken禁止redirect。
- 准备不生成；生成结果不确定永不重发；已生成文件下载失败后恢复不重新生成。恢复入口只读本地，绑定账号与筛选签名；增强字段不会进入自动写回。
- 全量2067 passed/3 skipped，后续修改focused43和JS通过。T0版本化绑定合同/显式迁移未完成，T6独立审查/T7打包仍待进行；无真实导出、无EXE发布。

## 2026-09-15 EWO v2最终交付检查点

T0至T5代码及本地集成完成。v2按内部记录ID识别，旧规则保留；显式迁移/签名取证/旧客户端保护/事务修订号保护已验证。schema14阻断旧EXE改写新版合同；用户升级前需备份data。固定单条增强仅导出所选内部ID；基础ID可在准备后查看。

T6由当前Flash对提供的源码摘录独立审查，无该范围P1/P2；主控进一步修复预览空值一致性、数据库降级保护与分析ID去重，均有专项测试。T7完成：最终全量2112 passed、3 skipped；末轮专项105 passed、Node通过；冻结WebUI/CLI隔离启动、401保护、schema14通过，地图与lint通过。

复测包dist/VSE-EWO-v2-20260915.zip，SHA256 df2d49918fc79434796a7c6db47d0d56736e346deadfb2d23eb1214634c592d9。没有真实内网生成/下载验收；PAA/NCR新增强扩展仍为后置范围。无commit/merge/push。
