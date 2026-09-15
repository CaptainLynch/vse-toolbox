# 聚合同步修复会话代码审计（2026-09-14）

对象：任务“修复聚合同步第二轮审计缺陷”（01a09bd2-793f-7d80-b263-ab94d308b692）及当前工作树。工作树包含多任务未提交变更，因此审计针对当前落盘实现，不将全部 diff 归属该会话。

结论：仍有两个可复现的分页完整性缺陷，尚不能认定这一验收项闭环。仅审计，没有修改产品代码。

## P1：响应页码未校验，重复页能获得完整性授权

位置：services/tdc_crawler.py:665-681、696-722。

请求第 1、2 页；上游两次均返回 current=1、total=4、pages=2 以及同样的 A/B 两条记录。_query_page 保存了响应 current，但 _crawl_all 没有检查 result.page 是否等于请求 page；累计条数在去重前增长，第二次响应使 accumulated_count 达到 4。最终只有 2 条唯一记录，却返回 complete=True、stop_reason=reported_pages、duplicate_count=2。

已实际调用 _require_complete_result 和 _require_complete_mapping_result：两者均接受。若服务端分页失效或返回缓存页，发现链路可为残缺集合建立稳定证据，同步也会用残缺集合生成聚合备注/分析缓存。

建议：校验响应页号与请求页号一致；重复页或跨页重叠不得仅凭原始计数证明完整，应拒绝该次结果或进行可验证的重试。增加真实 crawler→完整性校验的回归。

## P2：total 达标分支绕过尚未结束的 pages

位置：services/tdc_crawler.py:714-722。

第一页返回 2 条、total=2、pages=2。total_end 为真，立即返回 complete=True、reported_total，只发起一次请求。声明的后续页从未读取，total/pages 冲突也没有触发 inconsistent_metadata。

两个消费入口同样接受。上游总量元数据过期或矛盾时，当前实现仍把无法证明完整的结果用于发现和同步，违反本轮修复要求的矛盾元数据拒绝策略。

建议：total_end 必须与已声明的 pages 同时一致；若两者矛盾，返回不完整状态，不能自行选择 total 为权威。补充 total 提前达标但 pages 尚未结束的回归。

## 验证

- 相关 7 个测试文件：267 passed in 28.85s（本轮执行）。
- python tools/generate_project_map.py --check：通过。
- 审计涉及产品模块 git diff --check：通过。
- 离线合成复现：.runtime/audit_0914_repro.py；执行时 PYTHONPATH 指向仓库根目录；输出 .runtime/audit_0914_repro.log。
- 测试日志：.runtime/audit_0914_focused.log。
- 未重跑全项目测试、打包或真实业务端点；未读取真实凭据或业务数据。旧会话全量结果不作为本轮验证结果。

审计还抽查了查询身份构造、观测签名、候选缓存/映射重算、运行快照与 finalize 事务保护；本轮未确认这些路径的新缺陷。预览 API 的 200 字符展示上限在现有测试中明确保留，未将这一既定展示合同单独列为缺陷。
