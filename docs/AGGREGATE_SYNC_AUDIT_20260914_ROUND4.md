# 聚合同步修复后代码审计（第四轮，2026-09-14）

> 修复复验更新（2026-09-14）：用户授权后，以下三项已完成修改并通过本地回归。最终全量 **1997 passed, 3 skipped / 184.22s**。下文原始“不通过”结论作为修复前证据保留；本次实施与验收见文末。

对象：任务“修复聚合同步第二轮审计缺陷”（01a09bd2-793f-7d80-b263-ab94d308b692）的需求、修复记录与当前工作树。

结论：**不通过，仍有三项分页完整性缺陷。** 本轮仅审计、编写离线合成复现及报告，未修改产品代码。工作树包含其他任务的未提交变更，不能将整个工作树 diff 归属于被审计任务。

## P1-1：TDC 使用请求页大小判断尾页，服务端缩小页大小会导致漏抓

位置：`services/tdc_crawler.py:618-625`、`:760-768`。

请求 `size=100`；服务端返回 `current=1,size=2,records=[A,B]`，不提供 total/pages，第二页仍有 C。解析器保留了响应 `page_size=2`，但 `_crawl_all` 用请求的 `page_size=100` 判断短页。结果只请求一次，返回两条、`complete=True,stop_reason=short_page`，排队的第二页未读取。

影响：分页上限由服务端调整时，满页被误当尾页；连接器与映射发现门禁均接受该残缺结果，可能生成缺记录的聚合备注、分析结果和稳定证据。

解决方案：在合并记录和判断尾页前验证响应页大小。最小安全修复是请求/响应 size 不一致时返回不完整并提示重新查询；如需兼容服务端限流分页，必须明确有效分页大小及后续请求的偏移语义，并校验跨页一致性，不能仅替换一次比较变量。只有可证明的末页才能授权 complete。

验收：请求 100、响应 size=2、第一页 A/B、第二页 C 时，不得返回只含 A/B 的完整结果；若采用拒绝策略，两侧门禁必须拒绝；若采用兼容策略，必须得到 A/B/C 且完成分页证明。覆盖响应 size 非正数、非整数和跨页变化。

## P1-2：Aras EWO 未校验响应页号及跨页重复，错误结果仍标记完整

位置：`services/aras_crawler.py:393-410`。

合成 SOAP 响应：请求第一页得到 `page=1` 的 A/B；请求第二页却得到 `page=1` 的 A。当前实现仅记录 `last_page`，然后把 A 合并，并因该页只有一条而标记 `complete=True,stop_reason=short_page`。结果为 A/B/A。

另一个复现：响应页号依次为 1、2，内容均为 A/B，第三次为空；返回四条、`complete=True,stop_reason=empty_page`。页号正确也未能防止重复页内容获得完整性授权。两个复现均经过真实 XML 解析及完整性消费门禁，connector/discovery 均接受。

影响：TDC 新增的错页保护未覆盖 EWO；旧页、缓存页或跨页重叠仍可建立错误聚合证据，重复计数并漏掉其他记录。

解决方案：对存在的响应页号，在合并前校验与请求一致；检测重复 Item ID、重复页内容及跨页重叠，遇到不能证明完整的情况停止并返回不完整。优先使用 Aras Item ID，避免把可能合法重复的业务单号直接当唯一记录键。缺失页号的兼容规则须单独定义；空页/短页不得覆盖此前发现的不一致。不能只去重后继续声称完整。

验收：补充真实 SOAP parser → crawl → connector/discovery 门禁测试，覆盖错页短页、错页空页、正确页号但重复 Item ID、重复页后空页，以及正常多页末页。所有异常路径 complete 必须为 false，且不能生成观测或同步候选。

## P2-3：TDC 响应解析把显式无效页号替换为请求值，绕过新增错页检查

位置：`services/tdc_crawler.py:617-625`、`:1299-1305`。

分别返回 `current=0` 和 `current="invalid"`，其他元数据为 `size=2,total=2,pages=1`，记录 A/B。前者经 `current or page` 变成请求页号 1；后者经 `_optional_int(..., page)` 默认成 1。两者均返回 `complete=True,stop_reason=reported_pages`，两侧门禁均接受。新增 `result.page != page` 检查看不到原始错误。

影响：明确异常的响应元数据被伪装为合法，上一轮宣称的“响应页号必须等于请求页号”并未在解析边界完整落实。

解决方案：区分字段缺失与字段存在但无效；显式 current 必须是严格正整数且等于请求页号，拒绝 0、负数、布尔值、非整数字符串和小数，不使用 `int()` 截断或 `or` 兜底。total/pages/size 同样应采用字段级范围验证，明确允许零的空结果约定。缺失元数据只能按已定义的兼容合同处理。

验收：通过真实 JSON 解析覆盖 current=0、invalid、true、1.5、负数及合法整数/兼容字符串；无效值不得落为请求页号或获得完整性授权。

## 已核对内容与验证边界

- 上一轮原始两项复现已被拒绝：重复 current=1 返回 `inconsistent_page`；total 提前达到但 pages 未结束返回 `inconsistent_metadata`。
- 抽查请求时查询身份、签名白名单、历史与运行签名校验、完整候选重算、finalize 写事务及 revision 保护；本轮未确认这些路径的新缺陷。此结论不是全仓库无缺陷保证。
- 本轮相关测试两批：**256 passed / 27.16s + 147 passed / 25.42s = 403 passed**，共 13 个测试文件。
- 第一批：test_tdc_crawler、test_aras_crawler、test_project_status_discovery、test_project_status_connectors、test_project_status_aggregate_sync、test_project_status_admin_api、test_project_status_updates。
- 第二批：test_project_status_policy_api、test_project_status_sync_runner、test_project_status_sync_runs、test_project_status_analytics、test_project_status_deliverable_analysis、test_project_status_contracts。
- `python tools/generate_project_map.py --check` 通过；审计涉及产品模块 `git diff --check` 通过。
- 合成复现：`.runtime/audit_latest_repro.py`；从仓库根执行并设置 PYTHONPATH 为仓库根。包含断言，用于确认漏洞现状及旧修复，不是修复后应通过的验收测试。
- 输出：`.runtime/audit_latest_repro.log`、`.runtime/audit_latest_focused.log`、`.runtime/audit_latest_additional.log`。这些为本机临时证据，关键输入输出已归档于本报告。
- 未重跑全项目测试、打包或真实业务端点；未使用生产数据、真实凭据；未提交、合并、推送。旧任务的全量测试结果不计入本轮结果。

建议下一步：先修 P1-1/P1-2，再修 P2-3；把以上合成场景加入持久回归测试，并验证异常结果在发现入口和执行入口都不能继续使用。

## 用户授权后的实施及复验

- P1-1 已修复：TDC 在合并前验证响应 size；与请求不一致时返回 `complete=false/inconsistent_page_size`，不合并该页。采用报告中的拒绝策略，不推测服务端 offset 规则。
- P1-2 已修复：Aras 解析所有 Result/EWO Item 的显式页号，拒绝无效值和同一响应内冲突；包含空页的请求/响应页号错配在合并前返回不完整。重复 Item ID（含页内重复）被拒绝。缺 ID 的旧响应使用记录内容哈希检测整页、局部重叠，以及有/无 ID 切换时的重叠；不同且有效 Item ID 的相同内容仍合法。异常完整性结果同时被 connector/discovery 门禁拒绝。
- P2-3 已修复：TDC current/size 必须为正整数，total/pages 必须为非负整数；拒绝布尔值、小数、非整数字符串等显式异常。保留数字字符串、缺失分页字段以及可空 total/pages 的兼容；合法 total=0/pages=0 空结果可证明完整。
- 产品改动：`services/tdc_crawler.py`、`services/aras_crawler.py`。新增 `tests/test_crawler_pagination_integrity.py`，共 62 项参数化用例；调整原测试中一处不一致 size 夹具，以及原先容忍非数字 EWO 页号的旧期望。
- TDD 证据：初始有效红灯 56 failed / 2 passed；补充缺 ID 局部重叠红灯 3 failed / 1 passed。最终分页与两个爬虫测试文件 **154 passed**；最终全量 **1997 passed, 3 skipped / 184.22s**，退出码 0。
- 最终日志：`.runtime/audit4_full_final.log`；分页测试日志：`.runtime/audit4_crawlers_final.log`。原 `.runtime/audit_latest_repro.py` 断言的是修复前漏洞状态，不作为修复后的验收命令；持久验收使用新增 pytest 文件。
- Python 编译、修改文件 diff 空白检查、项目地图刷新后的 `--check` 通过。未访问生产业务端点或真实凭据，未 commit/merge/push。
