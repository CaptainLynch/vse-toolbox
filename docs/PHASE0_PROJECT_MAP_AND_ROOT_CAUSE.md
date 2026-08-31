# 阶段 0：项目地图、现状与根因证据

扫描时间：2026-08-31（主会话只读扫描）。AGY 证据：`.runtime/agy_phase0_scan.json`；监督器 doctor 显示 `AGY executable MISSING`、配置模型 `gemini-3.7-flash-high`、`sandbox ENABLED`。随后按本机 Antigravity 集成配置检查了 `C:\Users\Lynch\AppData\Local\agy\bin\agy.exe`，该路径同样不存在；因此没有可调用的本地 Gemini worker，未绕过沙箱，改由主会话完成等价扫描。

## 项目地图

### 前端

- 入口/模板：[webui.py](../webui.py) 创建 `web.app.create_app()`；[web/templates/dashboard.html](../web/templates/dashboard.html) 是单页工作台。
- 页面区域：概览、Aras（EWO/PAA/NCR 进度/明细）、交付物、Excel、自动下载与留存、设置（dashboard.html 顶部导航与各 section）。
- 组件与状态：`web/static/app.js` 使用原生 DOM 渲染；交付物状态、分析、同步就绪、映射发现、最近运行、筛选/标签/图表均在该文件；样式在 `web/static/style.css`。
- 路由：`web/app.py:create_app`（约 2295 行起）注册 `/api/overview`、`/api/aras/*`、`/api/project-status/*`、`/api/scheduled-archive/*`、设置/会话/Excel API。

### 后端

- CLI 入口：[main.py](../main.py)；Web 入口：[web/app.py](../web/app.py)、[webui.py](../webui.py)。
- 数据层：[core/db_manager.py](../core/db_manager.py)：SQLite 表、交付物/绑定/运行/产物/映射观察、幂等迁移。
- 项目状态服务：[services/project_status_updates.py](../services/project_status_updates.py)（策略、字段权限、业务更新）；`project_status_sync_runner.py`（租约、运行、错误分类、部分成功）；`project_status_connectors.py`（TDC/Aras connector）；`project_status_discovery.py`（稳定键/映射证据）；`project_status_deliverable_analysis.py` 与 `project_status_analytics.py`（筛选、阶段、标签、图表）。
- Aras 外部接口：[services/aras_auth.py](../services/aras_auth.py) OIDC + SOAP ValidateUser；[services/aras_crawler.py](../services/aras_crawler.py) EWO/PAA/NCR SOAP/XML；`aras_export.py`、`aras_xml.py` 负责导出/取证。
- TDC 外部接口：`tdc_auth.py`、`tdc_crawler.py`、`tdc_export_cache.py`、`tdc_contract_probe.py`。
- 凭据与脱敏：`core/credential_provider.py`（Windows 凭据管理器/DPAPI）、`core/domain_identity.py`、`core/redaction.py`、`services/windows_http.py`、`core/diagnostics.py`。

### EWO/PAA/NCR 调用链

1. 独立 Aras 搜索：`web/app.py` 的 Aras 查询路由 → `_build_aras_client_from_payload` → `ArasECMAuthClient.login`（OIDC）→ `ArasCrawlerClient.query_ewo_report/crawl_ewo_report_all` → `_build_ewo_payload`（`EWO_O`，字段 `_no`、`_modelinfo` 等）→ XML 解析/表格返回。
2. 交付物 EWO 同步：`POST /api/project-status/.../sync-now` → `update_service.assert_sync_ready` → `ProjectStatusSyncRunner.run_once` → `DatabaseManager.acquire_sync_lease`（启用、模式、external_key、match_rule、mapping、credential_ref）→ `ArasProjectStatusConnector.collect` → 凭据 provider → 同一 `ArasECMAuthClient`/`ArasCrawlerClient.crawl_ewo_report_all` → `_snapshot` → `ProjectStatusUpdateService.apply_snapshot` 写入状态/审计/产物。
3. PAA/NCR 独立归档：`scheduled_archive_connectors.ArasArchiveConnector.collect` 登录后分别调用 EWO/PAA crawler；NCR 调用 `query_ncr_approval_progress` 或 `extract_ncr_approval_detail`，产物写入 `ArchiveStore`。交付物同步 connector 当前明确只支持 EWO（`project_status_connectors.py`）。

### 筛选、标签、图表

- Aras 查询字段/筛选：`web/app.py` `_ewo_filters_from_payload/_paa_filters_from_payload/_ncr_filters_from_payload`；`aras_crawler.py` 对应 SOAP payload 构造。
- 交付物分析筛选：`services/project_status_deliverable_analysis.py` 的部门、阶段、车型、状态、分页逻辑；前端 `app.js` 的分析工具栏。
- 标签/自定义图表：同一分析服务的 `chart_labels/save_chart_labels/chart_groups`；前端分析面板渲染 `customCharts`。

### 测试、构建、部署、配置

- 测试：`tests/` 覆盖 Aras auth/crawler、TDC、凭据安全、项目状态 API/同步/分析、scheduled archive、UI 回归。
- 检查配置：[setup.cfg](../setup.cfg)（flake8/mypy/pytest）；依赖：[requirements.txt](../requirements.txt)。
- 打包：`VSE-*.spec`、`build/`、`dist/`、`start-supervisor.ps1`；运行数据在 `data/`，诊断/运行输出约定 `.runtime/`。

## 当前架构、数据流与状态流

浏览器 → Flask API → 服务层 →（Aras OIDC/SOAP 或 TDC HTTP）→ 标准化 rows/snapshot → SQLite 缓存与审计/产物 → 分析 API → 浏览器。同步状态由 binding（idle/running/success/failed/needs_attention）和 run（pending/running/success/failed/partial）共同表达；前端另行计算 `syncReady`。

## 长错误的根因

错误文本不是后端单一异常，而是 `web/static/app.js:1557-1593` 将多个独立布尔条件拼接：策略启用/模式、凭据可用、external key、match rule、自动字段映射、映射稳定性（至少 2 次观察）。因此 `0/2` 只表示 `mapping_stability_count`，不能证明 Aras 查询失败。

证据链：

- `core/db_manager.py:1889-1935` 的租约守卫逐项拒绝：未启用/模式错误、source none、external_key 缺失、match_rule/mapping 为空、credential_ref 缺失；这是后端真实执行前置条件。
- `services/project_status_discovery.py:35-93` 以 `_no` 优先的稳定键候选，保存观察并要求两次稳定指纹；`_safe_row` 会补回 `_no` 等身份字段。
- `web/app.py:3395-3440` 同步入口先 `assert_sync_ready`，随后 runner；失败映射为 409 `SyncNotReady`，并非通用 Aras 查询错误。

### 交付物同步 EWO vs 单独搜索 Aras EWO

| 维度 | 单独搜索 | 交付物同步 |
|---|---|---|
| 认证 | 请求体/会话构建 Aras 客户端，OIDC 登录；失败直接返回 auth/http 错误 | 先从 opaque `credential_ref` 解 Windows vault，再同样 OIDC；凭据未知在租约阶段即阻断 |
| 查询 | 用户筛选直接转 `EWOReportFilters`，可仅按 `_no` 搜索 | `ArasProjectStatusConnector` 强制 `_rsp_department` 部门表达式；有 `modelInfo` 时按 `_modelinfo` 查询，否则按 match rule 字段；最多 2000 条全量抓取 |
| 数据转换 | XML rows → 表格/CSV | rows → `ConnectorSnapshot` → 稳定键匹配 → 仅批准的自动字段写回项目状态，并写审计/产物 |
| 稳定键 | 不要求确认，结果展示即可 | `external_key` 必须已确认，mapping discovery 需两次稳定观察；候选 0/多条分别 not_found/ambiguous |
| 匹配规则/字段映射 | 无策略守卫 | `match_rule_json` 非空且含 `reportType`；`mapping_json` 与 automatic authorities 一一对应 |
| 状态判断 | 由查询结果/HTTP 状态展示 | binding/run/snapshot/分析阶段多层状态；未识别 EWO stage 会 `needs_attention` |
| 错误处理 | `_aras_error_response` 按 auth/request/crawler 分类 | runner `_classify_exception`（binding_not_ready、credential、timeout、connection 等）并脱敏；前端把所有 readiness 缺口串成一句长提示 |

**根因结论：** 两条链路共享 Aras OIDC 与 EWO SOAP 查询实现，但交付物同步额外引入“策略配置 + 稳定键/匹配/映射双观察 + 凭据别名可用性 + 部门范围”门槛；当前前端把这些“配置未完成”和“外部服务失败”混为同一长文本。若单独搜索成功而同步显示 `0/2`，最直接原因是该交付物没有完成两次 `mapping-discovery`（或候选键不唯一/发生 key_changed），并可能叠加 credentialAvailable 为 false/unknown。它不是 Aras EWO 查询算法本身的失败。

## 主要问题清单（不改代码）

1. EWO 同步 connector 仅支持 EWO，PAA/NCR 尚未进入统一交付物同步状态模型。
2. 前端 readiness 以重复布尔计算和长串错误呈现，缺少可操作的分组修复动作。
3. 认证、凭据缺失/失效/服务不可用/未匹配/部分成功虽在后端有分类，UI 尚未统一枚举和降级体验。
4. `syncReady` 前端与 `acquire_sync_lease` 后端存在潜在漂移风险（例如 mapping 与 authority 精确等势条件）。
5. Debug 能力已有诊断/脱敏基础，但尚需统一生产导出 JSON/ZIP、上下文与三类对象判定摘要。
6. AGY CLI 配置存在但可执行文件缺失，需在实施前修复运行环境或保留人工扫描替代路径。

## Codex Luna High 只读复核补充

本节由 Codex 子智能体（`gpt-5.6-luna`，High）于 2026-08-31 完成只读复核，未修改文件。复核进一步确认：

- 独立 EWO 查询路由为 `web/app.py:3494-3527`，支持 `auth_mode=password` 与 `auth_mode=browser`；交付物同步的生产 registry 在 `services/project_status_sync_runner.py:590-614` 注册 Aras/TDC。
- 交付物 EWO 的 `ArasProjectStatusConnector` 固定受控部门表达式，并执行 `crawl_ewo_report_all(max_records=2000)`；独立查询可单页查询或按用户参数导出。
- `mapping-discovery` 不会由独立查询自动触发；只有 `POST /api/project-status/deliverables/<id>/mapping-discovery` 才写入 observation，这解释了“单独搜索成功但稳定性 0/2”的首要差异。
- 稳定性计数为 0 的具体条件包括无 observation、最新结果非 `matched`、来源变化、external key 变化，或最近两次出现 `ambiguous/not_found/key_changed`。
- 循环依赖当前通过 `project_status_sync_runner.py` 中的局部导入规避，但 `web/app.py` 仍是跨模块高耦合装配点。
