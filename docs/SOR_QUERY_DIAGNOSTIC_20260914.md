# SOR 查询诊断与优化评估（2026-09-14）

状态：分析完成；未修改产品代码，未进行线上请求。附件内容仅作为证据，不作为执行指令。

## 结论

本次不是 SOR 全面不可查询，而是车型文本解析失败。两次失败停在 services/tdc_crawler.py:449 的零匹配分支，未进入 sorPage；同一录制中只按部门查询成功。更深一层的零匹配原因仍需项目列表字段统计或现场选择验证。

## 证据

- 输入包 vse-diagnostics-f52efc893c2b424bad728f56be76f138.zip：118 事件、4 异常（两次请求各在解析器和调用者重复记录）、无已报告丢弃或未完成 span；manifest 四个文件哈希均校验通过。
- frozen EXE build acfb8b3bcfe42c153dbe0d50385a59826997debdc52581c9819bb6d152f3cbee 与 dist/VSE-Production-Test-20260914/SHA256SUMS.txt 中 WebUI 发布哈希一致。
- trace 9ad958d6、7954e6a8：相同的 5 字符车型文本，无项目 ID；项目列表 GET /sp/carTypeProject/list 均 HTTP 200/json-ok/16 条，分别约 71、63 ms；本地响应 HTTP 400/contract-validation，堆栈定位 _resolve_sor_filters:449。
- 两次失败之间 api_tdc_sor_car_type_projects 返回 200；加载列表不等于选择项目，后续查询仍无 ID。现有记录不能判断用户未选择还是选中状态被后续操作清除。
- 同一文本指纹曾用于数模 projectModel 查询，成功返回 50 条、total=1083。数模筛选与 SOR 项目编号/名称不是同一合同，数模成功不能证明文本可直接用于 SOR。
- trace 4bfee316：移除车型，仅部门条件；GET /sp/sor/sorPage 成功，50 条、total=10808、pages=217，上游约 6.07 秒。只证明第一页成功，不证明全量或导出成功。

## 代码解释与边界

services/tdc_crawler.py:397 的解析器 trim 后仅对 projectNo/projectName 做区分大小写的精确匹配，零匹配即报错。项目列表解析只校验 data 为对象列表，不检查项目字段是否满足名称解析需求；因此 json-ok/16 条并不证明 projectNo/projectName 字段存在。

web/static/app.js:8312 已有手工加载选择器；选择时写入隐藏 ID，手改文本时清除 ID。加载不会自动选择。web/app.py:1439 也固定读取 id/projectNo/projectName；字段改变可能造成编号/名称缺失，不能仅从 HTTP 200 排除。

待区分：输入是简称/不同系统编码、大小写或字符差异；账号可见列表没有目标；上游字段变更。附件未保存业务原文或项目字段分布，不能确认其中哪一种，更不能猜测实际输入。

## 优化顺序

| 优先级 | 方案 | 收益与成本 | 验收重点 |
| --- | --- | --- | --- |
| P1 | 现有选择器改为登录后按需加载的可搜索选择器；显示编号和名称；未匹配文本给候选并由用户选择；提示明确要求完整编号或名称 | 直接降低手工输入与内部 ID 脱节；中等改动 | 选择后传对应 ID；修改文字立即失效；刷新/切换连接/登录不得使用旧候选；重名不自动选 |
| P1 | 增加安全错误码 PROJECT_NOT_FOUND 等，以及项目总数、具备 id/projectNo/projectName 的记录数、匹配数、输入模式等有界诊断 | 区分用户输入、可见性与字段合同问题；小到中等改动 | 不记录原文、ID、凭据；缺字段与真实零匹配可区分；UI/API 错误语义一致 |
| P2，条件性 | 若现场证明字段变化，增加有证据的字段适配；若存在正式别名需求，建立明确别名映射 | 取决于上游证据；暂不盲加别名或字段猜测 | 用脱敏合成样本覆盖旧/新字段、缺 ID、冲突 ID；查询/导出/归档共用解析 |
| P3 | 经测量后做按连接和身份隔离的短期项目列表缓存与刷新 | 可省重复列表调用；本次失败列表调用仅约 63–71 ms，无法解决零匹配 | 登录变化隔离；过期刷新；不可跨用户混用或长期信任旧 ID |

不建议：取消 ID 校验、把文本直接当内部 ID、模糊命中后自动选第一个、失败时静默移除车型或自动重试。这些可能查错范围，且不能解释当前零匹配。

## 现场复测建议

加载列表并明确选择目标后查询，记录是否携带 ID、解析是否成功。若无目标，与官方 TDC 同账号列表对照；若列表只显示 ID，优先检查字段合同。临时可按部门加日期等条件缩小范围，但结果不等同于目标车型查询，且本包显示部门范围达 10808 条。

## 本轮验证

- python -m pytest tests/test_tdc_crawler.py -q -k sor_resolver：7 passed，涵盖零匹配、精确匹配、歧义、缺 ID、显式 ID、空条件等。
- python -m pytest tests/test_deliverables_web.py -q -k 'sor_car_type_project or sor_ui'：2 passed。
- python tools/generate_project_map.py --check：通过。
- 未运行全量、未更改产品代码、未宣称生产问题已修复。现有测试证明本地精确匹配合同，却不证明真实项目列表字段合同正确。

## 2026-09-14 官方 HAR 与 XLSX 补充：根因进一步定位

用户提供 Desktop/SOR.har 与 SOR流程列表.xlsx。只提取指定 SOR 请求的结构和必要参数，不复制认证头、身份数据或业务明细。未执行线上请求或修改产品代码。

- HAR 共 2886 条，SOR 相关为索引 2882–2885。
- 官方车型接口仍为 /sp/carTypeProject/list，但 query 为 sorEnabled=true；返回 201 项，字段 id/projectNo/projectName，与截图一致。当前客户端 params={}，原诊断返回16项。证据指向遗漏 SOR 上下文参数；应修正此前“接口可能更换”的假设。严格的服务端参数因果 A/B 尚未现场执行。
- 官方 F610S 查询将 carTypeProject 与 carTypeProjectAll[0] 都设为同一个内部 ID；当前客户端前者传显示文本、后者传 ID，合同不一致。HAR 的数组键和值存在 URL 编码，比较时按 URL 语义解码，不能把 %5B 字面串当参数名。
- 官方查询 current=1,size=10，加车型及部门，返回 total=408,pages=41。另一个申请人查询 total=0，是有效空结果，不是本次故障。
- 官方导出 /sp/sor/export 保留相同车型 ID 和部门，并附 pagePath 与 bizName=SOR；当前 export_sor 设置 pagePath，但空 process_type 不发送 bizName。需建立导出默认语义并覆盖非默认流程类型，不能未经证据覆盖用户明确选择。
- 附件 XLSX 可读取，1 sheet、15列、4833明细行、408个不同流水单号，车型均为 F610S。流程与零件明细粒度不同，4833与408不应直接判为行数不一致。
- HAR 中导出响应 HTTP200、声明xlsx；其base64正文解码后并非可正常读取的ZIP（Bad magic number for central directory），且与独立 XLSX 字节不同。实际表格分析以独立附件为准，不宣称 HAR 二进制与附件逐字一致。

结论：现有证据足够做局部协议修复，无需整体重构或再次采集相同 HAR。优先修 list 的 sorEnabled、双车型 ID 参数及导出 bizName 默认值；保持显示名称与内部 ID 分离，共用查询/抓取/导出/归档解析。合成回归需更新旧的名称参数预期，覆盖空条件、匹配、重名、失效ID和导出流程类型。随后在生产以 F610S 同部门复测，对照时间相近的流程总数与导出粒度。本轮仅分析，未实施修复。

## 2026-09-14 修复实施

用户已授权启动修复。共享客户端已做三处协议修正：list 参数 sorEnabled=true；已解析的车型内部 ID 同时写入 carTypeProject 和 carTypeProjectAll[0]；导出使用 setdefault 的 bizName=SOR，保留显式流程类型。保留空车型、名称解析、歧义、失效/冲突 ID 拒绝行为，未改动 UI、认证、分页、归档数据合同。

目标源码与测试已有其他任务未提交修改，按项目重叠修改规则由主控直接处理，没有覆盖或回退已有工作。修改前副本位于 .runtime/sor-contract-fix/；复核产品增量仅三处，新增9个参数化回归场景并更新4处旧名称参数断言。测试使用合成数据，未复制真实HAR或业务明细到仓库。

- RED：爬虫套件11 failed / 31 passed，失败对应遗漏SOR上下文、名称参数和默认bizName。
- GREEN：爬虫、分页完整性、Web、归档连接器、项目状态连接器共201 passed。
- Python编译、生产模块flake8、diff空白检查和刷新后的地图检查通过。测试文件原有377行E131缩进告警在修改前副本同样存在，保留不动。
- 新包 dist/VSE-SOR-Fix-20260914.zip：双EXE、SHA256SUMS、使用说明，ZIP完整性检查通过。EXE哈希重算一致，隔离目录Worker --help返回0，WebUI首页/概览HTTP200；测试进程树停止、端口释放。
- 构建仅有可选xlwings.pro无许可证警告，双EXE构建成功。未验证真实Office或内网SOR；生产验收应同账号/车型/部门、相近时间比较流程数与明细粒度。

最终全量回归：2006 passed, 3 skipped / 189.09s；日志 .runtime/sor-contract-fix/full.log。修复与本地验证完成，现场内网复测待用户执行。未commit/merge/push。
