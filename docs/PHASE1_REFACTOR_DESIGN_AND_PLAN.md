# 阶段 1：统一同步重构设计与实施计划（预览）

## 目标与范围

保留筛选、标签、图表的既有公开行为；同步、认证、状态判定、映射展示与 Debug 逻辑改为统一域模型。现有 API 路径保持不变，通过兼容适配器接受旧 payload/字段名并输出新模型。

## 新旧架构对比

旧链路是“页面布尔条件 → 各自 connector → 各自错误文本”。新链路为：`AuthSession`（认证状态）→ `ExternalQuery`（EWO/PAA/NCR 统一查询协议）→ `IdentityMatcher`（稳定键/匹配）→ `FieldMapper`（字段权限）→ `SyncOrchestrator`（租约/重试/部分成功）→ `UnifiedStatus`（唯一展示模型）→ `DiagnosticBundle`（脱敏导出）。

### 统一状态模型

`auth`: `unauthenticated | credential_missing | credential_invalid | authenticated | unknown`；`query`: `idle | querying | service_unavailable | failed | no_match | matched`；`sync`: `manual | ready | running | success | partial_success | needs_attention | failed`。每个 EWO/PAA/NCR 对象都包含 `{kind,id,source,externalKey,auth,query,sync,stage,matchedFields,errors,lastUpdated}`，保留各自字段差异和原始来源标记。

## 最简同步流程

1. 详情页加载统一状态（一次 API 聚合返回）。
2. 若认证/凭据缺失，显示单一可操作卡片“登录/配置凭据”。
3. 点击“发现匹配”执行一次受控查询并展示候选；用户确认稳定键与映射。
4. 第二次成功且指纹一致自动将稳定性置为 ready；“立即同步”只需一次点击。
5. 结果按 `success/partial_success/needs_attention/failed/service_unavailable` 显示下一步和重试按钮。

## 认证、错误与降级

认证由共享会话服务统一，Aras/TDC 仅实现 provider；秘密只在 provider 生命周期内存在。错误先映射到稳定枚举，再由 UI 显示“缺少什么/如何修复/重试”。服务不可用时保留最近缓存并标记 stale；部分成功逐字段列出应用/跳过原因；未知状态不自动写回。

## 兼容、迁移与安全

保留现有路由、请求字段和 CSV/JSON 产物；新增 `status_v2` 聚合字段，旧字段继续序列化。数据库采用幂等新增列/表和双读单写，支持回滚到旧渲染器。权限边界：只允许本地管理员修改策略/凭据；Debug 导出永不包含密码、token、cookie、Authorization、私钥或完整凭据，响应头按 allowlist 脱敏。

## Debug 工具设计

详情页增加“诊断”抽屉：上下文、请求 URL/方法/状态/耗时、脱敏头、参数/摘要、对象识别、认证/凭据状态、稳定键/匹配/映射判定、feature flags、错误堆栈摘要、关联 ID/时间戳/版本。提供“一键脱敏”“复制摘要”“下载 JSON”“下载 ZIP”，明确显示“敏感字段已过滤”；导出在无 VPN 环境下基于本地事件缓存完成。

## 可执行实施计划（确认后执行）

| 任务 | 文件范围 | 契约/验收 |
|---|---|---|
| 统一域模型与错误枚举 | `core/project_status_contracts.py`, 新 `core/sync_status.py` | 三类对象状态枚举、旧字段兼容序列化；单元测试覆盖所有状态 |
| 认证/凭据适配层 | `core/credential_provider.py`, `core/domain_identity.py`, `services/aras_auth.py`, `services/tdc_auth.py` | 缺失/无效/未知/成功可区分；秘密不出 provider；认证测试全绿 |
| 统一查询与匹配 | `services/project_status_connectors.py`, `services/project_status_discovery.py`, `services/aras_crawler.py` | 独立搜索与交付物 EWO 共享同一查询/解析函数；稳定键、歧义、key_changed 边界测试 |
| 同步编排 | `services/project_status_sync_runner.py`, `services/project_status_updates.py`, `core/db_manager.py` | 最少步骤、租约、重试、部分成功；旧 API 不变；集成测试 |
| PAA/NCR 接入统一模型 | `services/scheduled_archive_connectors.py`, `services/project_status_connectors.py` | PAA/NCR 状态可展示、认证复用、错误/重试一致；对象字段差异保留 |
| 前端详情与操作 | `web/static/app.js`, `web/static/style.css`, `web/templates/dashboard.html` | 状态卡片、修复动作、筛选/标签/图表回归；不再拼接长错误 |
| Debug 导出 | `core/diagnostics.py`, `core/redaction.py`, `web/app.py`, 前端诊断组件 | JSON/ZIP、脱敏、离线导出、敏感字段测试 |
| 测试与质量 | `tests/`、`.runtime/` | 单元/集成/回归、构建、类型、Lint；输出均写 `.runtime/` |

### 风险、回滚与门禁

风险：历史 binding 配置不完整、外部 Aras schema 漂移、旧前端依赖字段。采用 feature flag 双渲染、数据库双读、每阶段可回滚；任何公开接口或安全边界变化必须由主会话审查。实施门禁：用户明确回复“确认开始”后才允许创建迁移、改代码或启动并行任务。
