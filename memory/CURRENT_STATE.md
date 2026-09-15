# Current State

## 2026-09-15 EWO v2：代码、回归与复测包完成；真实内网验收待现场执行

- 用户授权的EWO改造本地实施完成；未执行真实内网生成/下载，不宣称线上故障已现场验证。
- 交付包：dist/VSE-EWO-v2-20260915.zip（67032574 bytes），SHA256 df2d49918fc79434796a7c6db47d0d56736e346deadfb2d23eb1214634c592d9。配套.zip.sha256与展开目录保留，含WebUI/CLI、README、VERIFICATION、SHA256SUMS。不含用户data或HAR，不含新ExcelWorker。既有SOR复测包保留。
- 全量最终：2112 passed/3 skipped/229.54s；最后专项105 passed/3.80s，Node增强面板测试通过、地图check和新增模块flake8通过。冻结EXE隔离验证Web启动、资源、未登录导表401、schema14、CLI --help通过；临时进程已结束。证据.runtime/ewo-v2/。
- 4项实现由官方ZCode Gemini Flash隔离worker承担：T1关联、T2工作簿、T4增强面板、T0纯v2校验。第5次为只读源码摘录审查，无该范围P1/P2发现，不等同全库审计。记录TASK-ewo-pure-association-20260915-resume1、TASK-ewo-workbook-adapter-20260915、TASK-ewo-enrichment-ui-20260915、TASK-ewo-v2-contract-20260915、TASK-ewo-v2-review-20260915，隔离树及记录保留；无provider fallback。
- 主控已完成EWO v2合同接入：contractVersion为字符串2，bindingMode single_record/record_set；single固定sourceItemId，record_set始终禁止owner/plannedDate自动映射；旧规则不自动迁移。新配置签名隔离旧证据，显式迁移须停用保存、两次新取证再启用，旧客户端缺bindingContractVersion拒绝修改。
- 数据库升级为v14，让旧EXE在DDL之前拒绝新版数据库；升级保留旧绑定/字段归属。set_project_status_update_policy支持expected_sync_config_revision并BEGIN IMMEDIATE，防止迁移中的旧请求覆盖新版配置。升级前备份data与旧EXE；回退须恢复旧数据库副本，不能用旧程序编辑v14库。
- Aras基础行仅v2注入_source_item_id，发现与执行按内部ID规范化；同号/空号记录保留，分析item_key固定按内部ID计算。缺失/空备注不清空，预览和执行一致。legacy通用业务编号身份优先级保持不变。
- 增强链路为独立只读：完整列表prepare不生成，显式run官方生成；unknown禁止重发，下载失败复用file引用；按登录主体+固定来源+筛选签名恢复。单条增强只导出选定ID。API固定源、本机保护、会话换人时不返回前账号结果；生成/metadata/token/download均禁止redirect，token不持久化。
- UI接入EWO详情，支持模式选择、迁移停用、集合手工字段保护、准备/生成/继续下载/恢复/状态刷新。基础记录ID可以在prepare后查看；增强不进入自动字段候选。
- 实施/升级说明docs/EWO_IMPLEMENTATION_20260915.md；计划docs/superpowers/plans/2026-09-15-ewo-first-release.md末尾记最终状态。地图与API清单已刷新，83端点。无commit/merge/push，保留大量无关dirty变更。

## 后续动作

用户在内网复测包：先备份data，登录并检查旧规则；再按说明迁移一个小集合或固定单条，确认两次取证、只读生成和恢复。不要自动触发生产生成，不重复解析原始HAR（410行/111列，406唯一编号+4空号的离线证据已核验）。若反馈新错误，优先分析新诊断与具体任务状态。
