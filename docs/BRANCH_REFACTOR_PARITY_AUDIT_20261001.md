# 插件重构分支与上一业务分支的改动保留审计

日期：2026-10-01。任务范围：比较及复现；未实施业务修复、未切换分支、未提交或推送。

## 比较基线与结论

- 当前：`refactor/plugin-host`，`589071e`。
- 上一分支：`feature/scheduled-deliverables-overview-excel`，`e2c58a3`。
- 共同祖先：`d15d0f2`（9 月 26 日的看板/归集审计闭环检查点）。
- `git log refactor/plugin-host..feature/scheduled-deliverables-overview-excel` 有 26 个未进入当前历史的提交，其中 9 个是业务修复提交。
- **确认存在业务遗漏。** 插件重构从旧检查点分出，后续生产修复链未合入；不是所有差异都是新架构删除功能，部分 UI 效果已重新实现。

未合入的业务提交，按先后顺序：`20cbbd4`、`a1af029`、`66ce4c7`、`7314cf1`、`e255512`、`23ac8be`、`90372fd`、`ed914ee`、`4e59d71`。

## 确认遗漏的业务行为

“实测”指隔离数据库、合成上游响应的回归；“静态确认”指新旧代码与调用链一致证明缺少实现。生产表现是相应输入/故障发生时的结果，不代表已在公司内网重新操作。

| 编号 | 遗漏内容 | 当前表现与触发条件 | 当前证据位置 / 回归证据 |
|---|---|---|---|
| A1 | NCR 导出不应把绑定部门当科室代码，且不应导出后再按部门删行；科室代码白名单解析/向导输入也未迁入 | 部门中文文本会进入官方 `seccode` 参数；即使下载成功，行仍可能被再次筛掉。合成导出应保留 6 行，当前得到 0 行，可能表现为无文件、空报表或少行 | `services/project_status_connectors.py:473`、`:491`；`test_ncr_filters_never_sends_department_as_section_code`、`test_ncr_collect_rows_ignores_binding_department_keeps_section_code_narrowing` 实测失败；`parse_ncr_section_codes_input` 缺失 |
| A2 | SOR 同步行扁平化、真实申请人字段与零件成对聚合 | 项目等嵌套对象仍进入同步分析行；申请人 `startUser.trueName`、部门/科室、`sorPartList` 的零件号/名称和 `sorProcessStatus` 最新节点未转到应用字段，显示空值或对象内容。交互查询的通用扁平化仍存在，但不等价于同步/F6c 修复 | `services/project_status_connectors.py:256`、`core/report_contracts.py:161`、`web/app.py:584`；3 个 SOR connector/申请人断言实测失败；`flatten_sor_rows` 缺失 |
| A3 | 同步及定时归档共用的 SOR 废弃/撤回剔除、PAA CANCEL 剔除 | SOR 已废弃/已撤回仍混入快照和完成率分母；PAA CANCEL（含归一化变体）仍计入同步。合成 SOR 期望 2 行，实际 4 行。SOR 向导状态筛选入口也没有迁入 | `services/scope_exclusion.py` 整个模块缺失；`services/project_status_connectors.py:256`、`:409`；`services/scheduled_archive_connectors.py:356`、`:523`；SOR/PAA 剔除用例实测失败 |
| A4 | 数模完成判定/状态映射，以及 PAA/NCR CLOSE 的分析完成口径 | 数模状态码 `4` 在分析卡片判未完成，表单侧却能判完成，卡片与明细统计不一致；码 `2` 仍显示裸码。PAA/NCR 的 `CLOSE` 在无实际完成日期时也误判未完成。TDC 写入分析标签退回笼统 `tdc` | `services/project_status_deliverable_analysis.py:199`、`:587`、`services/deliverable_form_analysis.py:310`、`core/report_contracts.py`；完成判定及来源标签 5 项断言、状态码显示断言实测失败 |
| A5 | TDC 官方 XLSX 归档失败不阻断已完整获得的表单数据 | 列表抓取成功后，若官方 XLSX 导出返回 503/异常，整次状态同步仍失败，表单快照不能正常更新 | `services/project_status_connectors.py:271` 附近仍无导出异常降级；`test_tdc_connector_collect_tolerates_archive_export_failure` 实测失败 |
| A6 | TDC 查询 502/503/504 的有界重试、Retry-After，以及明确网关错误提示 | 短暂 503 后本可成功的查询直接结束失败；缺少旧分支的次数/等待预算与网关提示。不是主张重试所有 5xx，旧合同明确不重试普通 500 | `services/tdc_crawler.py:603`、`web/app.py:2687`；重试函数/常量缺失，旧重试选择集失败；代码确认当前单次非 2xx 即抛错 |
| A7 | 科室归集的规范化匹配、24 个历史别名种子与默认值幂等更正 | `BE 结构工程科` 等前缀/空白变体无法按旧规则归集；新库默认别名总数为 0，旧分支为 24；缺少“结构工程科→车身科”的默认更正与已存旧默认迁移。已保存的自定义规则仍可读取，不等于用户规则被删除。规范化冲突校验也缺失 | `core/section_rollup.py:35`、`:173`、`:197`；7 项旧新增用例中 5 项失败、2 项通过 |
| A8 | 数模加入科室归集计数板 | 数模仍被 `_ROLLUP_REPORTS` 排除，缺少归集后的 `sectionCounts` 与对应看板；历史科室合并统计/按目标科室筛选不能完整沿用旧口径 | `services/deliverable_form_analysis.py:1360`、`plugins/project_overview/static/deliverable/form-analysis.js:463`；`test_tdc_data_model_joins_section_rollup_with_counts_only` 实测 KeyError |
| A9 | NCR 明细按归集后科室的四指标成本表及有效值件数 | 按科室页仍为计数板，缺少旧成本表；成本聚合继续按原科室文本分组，历史科室与现行科室不能合并对账。缺少“有值 k/N”区分空值与零值的统计 | `services/deliverable_form_analysis.py:1476`、`plugins/project_overview/static/deliverable/form-analysis.js:463`；`test_ncr_detail_section_costs_with_rollup_and_signed_values` 实测 `sectionCosts` 缺失；`core/report_cost_values.py` 缺失 |
| A10 | 多记录风险/备注摘要化 | 仍拼接“单号：状态/卡点”并截断，备注塞满明细；缺少“共 N 条；各状态计数”，NCR 明细也没有四项费用合计摘要 | `services/project_status_records.py:225`、`services/project_status_connectors.py:119`；12 项旧摘要测试仅保留 legacy 行为的 1 项通过，另外 11 项失败（新 `report` 参数缺失） |
| A11 | 取证请求时限、取消、向导会话去重、第二次轻量核验及其稳定性基线 | 当前每次仍完整抓取；没有取消 API/前端取消、同会话缓存和 `observe_stability_sample`，大数据量取证重新重复耗时。缺少同源声明总数、顺序无关身份哈希子集比对与结构化不一致原因 | `web/app.py:4703`、`services/project_status_discovery.py:54`、`plugins/project_overview/static/deliverable/policy.js:98`、`deliverable/api.js:54`；10 项轻量核验、会话/取消 API 选择集失败。当前请求也无 90s/240s 的客户端截止 |
| A12 | Aras 映射取证后台任务化及结果重新挂接 | EWO/PAA/NCR 取证仍直接同步 HTTP 完成，无法取得旧 202/taskId/statusUrl 后台任务合同。NCR 两次独立导出继续在前台等待；异步化本来就不缩短上游导出总耗时，但它消除了前台长请求等待 | `web/app.py:4703`、`plugins/project_overview/static/deliverable/policy.js:98`；旧 async API 选择集失败；旧分支对应选择集全部通过 |
| A13 | PAA 去掉其他状态灰桶，同时披露未识别条数 | 当前 PAA `sectionStageMatrix` 仍多出“其他状态”桶；`unrecognizedStageCount` 缺失，没有旧分支明确披露的未识别 k 条 | `services/deliverable_form_analysis.py` 的矩阵构建、`plugins/project_overview/static/deliverable/form-analysis.js`；PAA 矩阵断言实测多出 1 桶；未识别计数字段断言失败 |
| A14 | SOR 源缺失列诚实提示、数模默认增加最新审批记录、长文本列截断 | API 未给 `sourceAbsentIndexes`，无法区分上游缺键与空值；数模默认可见数退回 15（旧为 16），最新审批记录不默认展示；流程名/零件名称没有 r7 列类、截断及 title，长文本仍会把行撑高。末项为静态确认，未跑真实浏览器量测 | `services/deliverable_form_analysis.py:99`、`:476`、`plugins/project_overview/static/deliverable/form-analysis.js:505`、`:530`、`deliverable.css`；缺字段 API 两项实测 KeyError |
| A15 | PAA 改名及旧默认名称更正 | 当前新库种子、能力显示名、系统查询目录仍叫“PAA 报告”，旧分支要求“PAA流程”；缺少只更正旧默认名称、不覆盖自定义名称的更新 | `core/db_manager.py:614`、`core/project_status_contracts.py:669`、`web/app.py:265`；静态确认 |
| A16 | r7 表单视图/明细请求超时恢复保证 | 两个 fetch 没有请求截止；切页签时若最新请求一直 pending，旧图表/明细交互守卫可持续锁定。**未证明 r7 现场“下拉点不动”的整个触发序列在 Preact 里相同**，本条只确认超时保证没有迁入 | `plugins/project_overview/static/deliverable/form-analysis.js:694`、`:726`、`deliverable/api.js:54`；静态确认，真实浏览器复测待做 |

另有 NCR 无文件引用的专用错误类型、无泄漏响应结构签名与中文解释遗漏：当前回退通用 `ArasCrawlerError`/`query_failed`，难区分无匹配、参数不接受与响应结构不符。见 `services/aras_crawler.py:826`、`web/app.py:2624`；旧 `ArasNcrExportContractError` 导入失败。

## 保留或不能直接判为回归的部分

- 圆环的 `.ring-center` 元素与独立居中样式保留；鼠标点击、Enter/空格跳转详情也保留：`plugins/project_overview/static/status/progress.js:14`、`overview.css:66`。
- 无有效同步值时圆环展示同步占位而非假百分比保留：`shared/status-logic.js:379`。
- 同步向导有进行中及失败提示，不属于整块错误反馈被删除：`deliverable/policy.js:98`。
- 筛选草稿/请求/已显示条件的分离、草稿状态文字及多选 token 保留。Preact 不同于旧 DOM 重建，不能仅凭旧脚本删除断言“点击丢失”同样重现；A16 的请求截止是单独确认的遗漏。
- A7 不表示用户保存的科室规则被删，A2 不表示交互查询的所有通用扁平化都丢失。

## 验证方法与结果

1. 不切换当前分支；使用 `git archive` 将上一分支的 `core/ services/ web/` 与选中的测试导出到 `.runtime/branch-audit/previous-branch/`。测试用临时数据库、合成响应、独立 basetemp；未访问企业内网或真实 Office。
2. 从 9 个测试文件选取共同祖先之后新增的旧回归函数（参数化后 96 项）。**旧分支 96 passed**，所有模块 exit 0。
3. 同一旧测试集合直接对当前源码：**62 failed、4 passed，3 个文件收集错误**。收集错误分别是 `ArasNcrExportContractError`、`_exclude_tdc_scope_rows`、`source_absent_indexes` 缺失。
4. 为核实第 3 步被收集错误挡住的其他断言，另建兼容测试副本：只移除不可用的顶层导入，排除直接依赖这些导入的函数；不改夹具和断言。19 项新增检查：**15 failed、4 passed**。其中实测了 NCR 6→0、SOR 未剔除、导出失败阻断、成本字段缺失、裸码显示等。
5. 计数不是 77 个独立产品问题：多个失败是同一缺失实现或公共接口导致，也包含负向保护测试失去猴子补丁入口。业务结论按上表的代码、具体断言及调用链归类，不按失败条数定级。
6. 项目地图初查漂移；生成器刷新后 `--check` verified，仅 Source fingerprint 一行变化。

本地证据：`.runtime/branch-audit/{selection,test-summary,baseline-summary,adapted-summary}.json`；各测试文件同名 `.log`；`.runtime/branch-audit-backend.diff`、`.runtime/branch-audit-forms.diff`。这些是本地忽略文件，持久结论以本报告为准。

## 后续修复顺序建议

先补齐后端 NCR 范围、SOR 行合同、范围剔除和完成率；再迁入归集/成本/备注与取证任务合同；最后把前端交互和展示修复迁入插件并恢复对应行为门禁。后端修复链可以逐个审查迁入，旧 `app.js` 与旧样式的补丁必须按插件责任迁移，不能直接恢复整个旧前端。修复与打包需另行执行；本次审计未实施。
