# DSH-V2-41：web 模块化 → 插件化的后续边界（ADR）

> **状态：已批准（主控 2026-11-01，裁决见 §7 末“主控裁决记录”）**
> **基线提交：`abfc8f8`**（分支 `dsh/v2-41`；= `refactor/ux-v2` 当前 HEAD，已含第 0/1/2 波全部集成）
> risk_class `high` ／ dispatch_gate `lead_design_and_approval` ／ size `medium`
> 本任务**只新增本文件**：不移动任何生产路由、不改 `web/`、`host/`、`plugins/`、`tests/`（验证见 §8）。
> 关联：`docs/refactor-v2/CONTRACTS.md` C7/C8/C10、`docs/refactor-v2/RELEASE_MATRIX.md`、`docs/refactor-v2/DSH_SERVICE_SPLIT_INVENTORY.md`（格式参考）。

本文件回答四个问题：

1. 现在到底完成了什么：`web/*_boot.py` 是**阶段性模块化**还是业务插件化？判据与证据是什么？（§2）
2. 每个领域的**现 handler / deps / 目标插件 / 旧 URL 别名 / 测试**分别是什么？（§3，逐条路由）
3. 哪些东西**永远不能**搬进可禁用插件？为什么？（§4）
4. 后续每次最多 4 条路由怎么拆、按什么顺序、怎么验收、怎么回滚、旧 URL 怎么活？（§5、§6）
5. 哪些事必须主控拍板？（§7）

---

## 0. 口径与复核

本文件所有数字都可用附录 A 的命令复核。**统计口径**：

| 指标 | 来源 / 方法 | 本次实测 |
|---|---|---|
| 路由清单与行号 | `tests/golden/routes.json`（166 条）+ 对 `web/*.py` 的 `@app.<method>(...)` 装饰器扫描 | 见 §3 |
| 路由总数 | 166 = **105** 条非插件路由 + **50** 条插件路由（`/api/p/*`）+ **11** 条静态路由 | 166 |
| handler 定义行 | 装饰器下一行的 `def <name>(` | 见 §3 每行括注 |
| deps | 各 `register_*` 的 `*RouteDeps` 字段 + handler 体内实际解引用 | 见 §3 |
| 前端消费者 | `plugins/*/static/**/*.js`、`web/static/**/*.js`、`web/templates/dashboard.html` 中的字面 `/api/...` 路径 | 见 §3、§4 |
| monkeypatch 目标 | `tests/**/*.py` 中 `setattr(...)` / `patch.object(...)`，先解析文件内 import 别名 | 见 §3 各节 |
| 行数 | 换行计数（等价 `wc -l`） | 见 §2.1 |

**表述约定**：本文件中"范围内未查到"一律表示"在上述路径、按上述方法未命中"，**不表示全局不存在**（打包脚本、`.agents/` 运行记录、外部消费方不在统计范围内）。

**未做的事**：本文件不声称任何未实现能力已实现。特别是 §6 的旧 URL 别名机制**当前不存在**（证据见 §6.1），§5 的批次全部**未开工**。

---

## 1. 冻结结论（6 条）

| # | 结论 | 一句话依据 |
|---|---|---|
| **B1** | `web/*_boot.py` 是**阶段性模块化**（文件搬家 + 显式依赖注入 + 契约测试），**不是**业务插件化。任何报告/发布说明不得宣称"业务已插件化" | 10 个插件中 5 个的 `plugin.json` 自述"调用既有 `/api/...` 接口，旧页面并存"（§2.2）；105 条业务路由仍由宿主注册（§3） |
| **B2** | 一条路由**只有同时满足 4 个准入条件**才可以移入插件：① 前端消费者**恰好一个插件**；② 该插件是该行为的**数据/逻辑所有者**；③ 不含 §4 的平台职责；④ 旧 URL 别名机制**先落地**（§6） | 反例：`/api/deliverable-forms/*` 消费者是 project-overview、所有者是 deliverable-forms（§3.3） |
| **B3** | 平台与基础设施**永不移入可禁用插件**：本机安全引导、宿主更新、设置/凭据/域会话、任务中心、诊断白名单与录制钩子、静态宿主壳 | 可禁用性使"关掉一个插件就关掉安全/更新"成立（§4） |
| **B4** | **多消费者领域 API 不迁移**：`/api/aras/ewo/query`、`/api/aras/paa/query`、`/api/project-status*`、`/api/scheduled-archive/*`、`/api/deliverable-forms/*`、`/api/settings*`、`/api/tasks*` | 消费者 2~5 处，跨插件（§3、§4.8） |
| **B5** | 迁移粒度：**每批 ≤4 条路由或单一职责**；`web/app.py` 接线**严格串行**（一次只加/删一个批次）；同一 `rule + method` 在 `url_map` 中**只允许一个生产注册** | 插件最后加载（`web/app.py:631`），双注册时先注册者胜出，会静默遮蔽（§5.1） |
| **B6** | 本任务**零路由移动**（只写本文档） | §8 |

**总览表**（13 组，105 条非插件路由）：

| # | 领域 | register 入口（行） | 路由数 | 前端消费者（插件数） | 目标插件 | 结论 |
|---|---|---|---|---|---|---|
| 1 | Aras 抓取 | `register_crawler_routes`（`web/crawler_boot.py:839`） | 9 | system-query + project-overview（2） | `system-query` | **暂缓**（2 条多消费者） |
| 2 | TDC 报表 | `register_tdc_routes`（`web/crawler_boot.py:2542`） | 11 | system-query（1） | `system-query` | **候选 B 类** |
| 3 | 表单目录 | `register_form_catalog_routes`（`web/crawler_boot.py:2799`） | 4 | project-overview（1） | 待裁决（`deliverable-forms` vs `project-overview`） | **暂缓**（所有者≠消费者） |
| 4 | Excel | `register_excel_routes`（`web/excel_boot.py:44`） | 13 | excel-tasks（1） | `excel-tasks` | **可迁移（A 类，唯一）** |
| 5 | 任务中心 | `register_tasks_routes`（`web/tasks_boot.py:118`） | 6 | 宿主壳 + 4 个插件（5） | 无（host 基础设施） | **不迁移** |
| 6 | 宿主设置/版本 | `register_host_service_routes`（`web/host_boot.py:57`） | 6 | 宿主壳 + 3 个插件（4） | host | **不迁移** |
| 7 | 宿主更新 | `register_host_update_routes`（`web/host_boot.py:218`）+ `web/app.py:697,715` | 5 | settings 插件 + 宿主壳 | host | **不迁移** |
| 8 | 原件留存 | `register_archive_routes`（`web/archive_boot.py:65`） | 10 | scheduled-archive + project-overview（2） | `scheduled-archive` | **暂缓**（2 条多消费者） |
| 9 | 项目状态 | `register_project_status_routes`（`web/project_status_boot.py:1409`） | 27 | project-overview + workbench + scheduled-archive（3） | `project-overview` | **暂缓**（多消费者 + 29 处 patch + 缺 4 个宿主服务） |
| 10 | EWO 富化 | `register_ewo_enrichment`（`web/ewo_enrichment.py:12`） | 4 | 遗留全局脚本 `web/static/ewo-enrichment.js`（0 个插件） | 待裁决 | **暂缓**（前端未插件化） |
| 11 | 诊断 | `install_diagnostics`（`web/diagnostics.py:342`） | 6 | 宿主遗留脚本 + diagnostics + project-overview（3） | `diagnostics`（仅路由体） | **不迁移**（白名单在 host） |
| 12 | 本机安全 | `install_local_security`（`web/security.py:164`） | 1 | 宿主壳（`boot-exchange.js`） | host | **不迁移** |
| 13 | 组合根 | `web/app.py:489,496,503` | 3 | 宿主壳 / 测试 | host | **不迁移** |
| — | 合计 | — | **105** | — | — | — |

---

## 2. 现状判定：阶段性模块化，不是业务插件化

### 2.1 组合根仍独占装配与加载顺序

`web/app.py` 748 行，`create_app()` 依次完成：数据库/服务实例化 → **10 次** `register_*`/`install_*` 调用 → 诊断钩子 → **最后**才 `_install_plugin_host`（`web/app.py:631`）；第 11 次调用 `register_host_update_routes` 发生在 `_install_plugin_host` 内部（`:721-730`），因为它需要 `updates`/`registry` 实例。

| 文件 | 行数 | 顶层函数（其中私有） | 顶层常量 |
|---|---|---|---|
| `web/app.py` | 748 | 6（5） | 9 |
| `web/crawler_boot.py` | 3019 | 72（69） | 25 |
| `web/project_status_boot.py` | 2967 | 24（23） | 20 |
| `web/tasks_boot.py` | 687 | 2（1） | 3 |
| `web/diagnostics.py` | 489 | 16（2） | 9 |
| `web/excel_boot.py` | 280 | 1（0） | 0 |
| `web/host_boot.py` | 280 | 2（0） | 1 |
| `web/archive_boot.py` | 262 | 2（1） | 0 |
| `web/security.py` | 247 | 3（1） | 5 |
| `web/ewo_enrichment.py` | 83 | 1（0） | 0 |

接线顺序（`web/app.py`）：EWO 富化 `:451` → Excel `:513-525` → 任务中心 `:531-544` → 宿主设置/版本 `:548-562` → Aras `:586` → TDC `:590` → 表单目录 `:591` → 原件留存 `:596-608` → 项目状态 `:615-627` → 诊断 `:629-630` → 插件宿主 `:631`。

**含义**：所有业务路由在插件加载**之前**注册完毕，插件**不能**覆盖它们（`web/app.py:649` 注释即此意）。"搬到 `*_boot.py`"改的是**文件位置**，不是**所有权**。

### 2.2 插件清单自己承认仍在调用旧 API

**10 个**插件的 `plugin.json` 中，5 个直接写明调用既有接口（原文摘录；另外 5 个 `deliverable-forms`/`diagnostics`/`sign-daily`/`tir-report`/`workbench` 未如此表述，但同样只提供页面与 `/api/p/*` 自有路由）：

| 插件 | 版本 | `description` 关键句 |
|---|---|---|
| `system-query` | 0.1.0 | "调用既有 `/api/aras`、`/api/tdc`、`/api/tasks` 接口，旧页面并存" |
| `project-overview` | 0.1.4 | "调用既有 `/api/project-status` 等接口" |
| `excel-tasks` | 0.1.1 | "调用既有 `/api/excel-*` 接口，旧页面并存" |
| `scheduled-archive` | 0.1.1 | "调用旧的 `/api/scheduled-archive/*` 接口，旧页面并存" |
| `settings` | 0.1.2 | "仍调用旧 `/api/settings` 接口" |

`plugins/deliverable_forms/backend.py:9` 亦写明"旧的 `/api/deliverable-forms/*` 保持不变"。

### 2.3 插件边界测试禁止 `import web.*`

`tests/test_plugin_host.py:316-327`：遍历 `plugins/*/**/*.py` 的 AST，任何 `import web.*` 或 `import vse_plugins.*` 即失败（`assert violations == []`）。**所以"把路由体整段搬进插件"不是复制文件，而是先把 web 层 helper 变成宿主服务**。

### 2.4 路由接线已被冻结成契约

`tests/test_route_contract_behavior.py:87-253` 的 `DOMAIN_WIRINGS` 把 **11 条** `register_*`/`install_*` 与它们**恰好**注册的 endpoint 集合逐条冻结；`:549-585` 用 spy 证明 `create_app` **真的调用了每个 register 各一次**，并断言 `owned == _all_domain_endpoints()`、`non_plugin == owned | HOST_APP_ENDPOINTS | SECURITY_ENDPOINTS`。

**含义**：任何"把某条路由从 A 域挪到 B 域/插件"的动作都会同时打破 `DOMAIN_WIRINGS` 与路由 golden，必须作为**显式契约变更**提交，不能顺手做。

### 2.5 前端消费者仍绑在旧 API 上（节选，全量见 §3）

| 旧 API | 消费者（文件:行） |
|---|---|
| `/api/tasks` | `web/static/host/chrome/TaskCenter.js:128,168,253`；`plugins/system_query/static/query.js:403,441,447,466`；`plugins/project_overview/static/deliverable/discovery.js:60,85,100`；`plugins/excel_tasks/static/workspace.js:722`；`plugins/workbench/static/today.js:16` |
| `/api/project-status*` | project-overview 12 个文件、workbench 4 个文件、`plugins/scheduled_archive/static/jobs.js:603` |
| `/api/settings*` | `web/static/host/session.js:85,91,138,166`；settings 插件 4 个文件；`plugins/project_overview/static/auto-sync.js:61`、`deliverable/policy.js:617`；`plugins/workbench/static/today.js:12,202` |
| `/api/aras/ewo/query`、`/api/aras/paa/query` | `plugins/system_query/static/modes.js:143,159` **与** `plugins/project_overview/static/deliverable/policy-logic.js:848,854` |
| `/api/excel-*` | `plugins/excel_tasks/static/workspace.js:318,406,490,513,546,572,667,698,751`、`logic.js:116` |

### 2.6 `web/app.py` 仍保留 93 + 45 个迁移别名（含 90 + 42 个私有名）

`web/app.py:52-146`（`from web.crawler_boot import ...`，**93 名 / 90 私有**）与 `:148-194`（`from web.project_status_boot import ...`，**45 名 / 42 私有**），全部带 `# noqa: F401` 与"迁移别名"注释。

**含义**：`web.app.<symbol>` 仍是可被 patch / import 的**事实契约**。别名是**值拷贝**——patch boot 模块不会改 `web.app` 里已绑定的那份（详见 `DSH_SERVICE_SPLIT_INVENTORY.md` §1.3/§5.1，本次复核数字一致）。

### 2.7 判定

> **`web/*_boot.py` 完成了"模块化"**：文件按领域拆分、依赖经 `*RouteDeps` 显式注入、路由契约有 golden + 行为双测试。
> **`web/*_boot.py` 没有完成"业务插件化"**：路由所有权、URL 空间、装配权、服务实例化全部仍在宿主；插件只贡献**页面**与**少量自有路由**（50 条 `/api/p/*`）。
> 因此：**不得**在任何报告、发布说明或 UI 中宣称"业务已插件化"；正确表述是"页面已插件化、业务 API 仍由宿主提供，正在按批次迁移"。

---

## 3. 每领域清单（现 handler / deps / 目标插件 / 旧 URL 别名 / 测试）

**读表约定**：

- "handler（行）"= `web/<module>.py` 中该视图函数的 `def` 行号；"golden"= `tests/golden/routes.json` 中该 `rule` 的行号。
- "deps" 只列 **handler 体内实际解引用**的注入项；`—（模块级 helper）` 表示依赖来自模块级私有函数/常量，不走 `deps`。
- "旧 URL 别名"列写**迁移后旧路径的处置要求**。当前**没有任何别名机制**（§6.1），所以每格都是"待 §6 落地后"的约束，不是现状。
- 所有"目标插件"路径（`/api/p/<id>/...`）都是**建议**，最终路径在批次契约里冻结。

### 3.1 Aras 抓取 —— `web/crawler_boot.py`（9 条）

**register**：`register_crawler_routes(app, deps)`（`:839`）；**deps**：`CrawlerRouteDeps`（`:103`），11 字段：`db`、`crawl_task_runner`、`domain_sessions`、`tdc_export_cache`、`excel_admin_service`、`sanitize_error_message`、`local_mutation_error`、`json_ok`、`json_error`、`deliverable_form_service`、`section_rollup_store`。
**注意**：`register_crawler_routes` 体内只解引用 `db`/`crawl_task_runner`/`excel_admin_service`（`:841-843`）；`domain_sessions`、`tdc_export_cache`、`crawl_task_runner` 实际是**按名字从 `current_app.extensions` 取**（`:496, :849, :1758, :1778, :2253`）——这已经是"宿主服务字典"语义，对迁移有利。

| # | 方法 | 路径 | handler（行） | deps | 前端消费者（文件:行） | golden |
|---|---|---|---|---|---|---|
| 1 | POST | `/api/aras/ewo/query` | `api_aras_ewo_query`（`:868`） | —（模块级 `_build_aras_client_from_payload`、`_shared_domain_session`） | `system_query/static/modes.js:143`；`project_overview/static/deliverable/policy-logic.js:848` | 69 |
| 2 | POST | `/api/aras/paa/query` | `api_aras_paa_query`（`:905`） | —（同上） | `modes.js:159`；`policy-logic.js:854` | 146 |
| 3 | POST | `/api/aras/paa/crawl-all` | `api_aras_paa_crawl_all`（`:942`） | `crawl_task_runner` | `modes.js:160` | 124 |
| 4 | POST | `/api/aras/ncr/progress` | `api_aras_ncr_progress`（`:1003`） | —（模块级） | `modes.js:177` | 102 |
| 5 | POST | `/api/aras/ncr/detail` | `api_aras_ncr_detail`（`:1028`） | —（模块级） | `modes.js:192` | 80 |
| 6 | POST | `/api/aras/ncr/progress/download` | `api_aras_ncr_progress_download`（`:1052`） | —（模块级） | `modes.js:178` | 113 |
| 7 | POST | `/api/aras/ewo/export` | `api_aras_ewo_export`（`:1076`） | `crawl_task_runner` | `modes.js:144` | 58 |
| 8 | POST | `/api/aras/paa/export` | `api_aras_paa_export`（`:1136`） | `crawl_task_runner` | `modes.js:161` | 135 |
| 9 | POST | `/api/aras/ncr/detail/download` | `api_aras_ncr_detail_download`（`:1196`） | —（模块级） | `modes.js:193` | 91 |

**目标插件**：`system-query`（其 `plugin.json` 已声明调用这些接口）。
**旧 URL 别名**：9 条全部必须保留；建议插件内路径 `/api/p/system-query/aras/<同后缀>`，旧路径同 handler 别名（§6 方案 A）。
**测试清单**：

- 路由 golden：`tests/golden/routes.json:58,69,80,91,102,113,124,135,146`。
- 接线冻结：`tests/test_route_contract_behavior.py:88-102`（9 个 endpoint）、`:549-585`、`:614-617`（"读"集合为空，POST 查询受写保护）。
- 行为：`tests/test_route_contract_behavior.py:681`（ncr/detail 信封）、`:947`（ncr/detail/download 附件头）、`:855`（paa/query 失败信封）。
- 具体路由断言：`tests/test_aras_cli_web.py:237`（ewo/query）、`:332`（paa/query）、`:477-478`（ncr progress/detail）、`:811`（ewo/export）、`:846`（paa/export）、`:961`（ncr/detail/download）、`:983`（ncr/progress/download）；`tests/test_tasks_api.py:408,410,411`。
- **patch 目标（迁移会静默失效）**：`web.crawler_boot.ArasCrawlerClient` 4 处、`ArasECMAuthClient` 5 处、`_shared_domain_session` **16 处**、`_build_aras_client_from_payload` 2 处、`DIAGNOSTIC_DIR` 2 处、`MarkdownDiagnosticReport` 2 处（示例：`tests/test_aras_cli_web.py:215,349,1180`；`tests/test_plugin_overview_browser.py:907,1055`）。
**结论**：**暂缓**。① 第 1、2 条各有 2 个插件消费者（`system-query` + `project-overview`），违反 B2①；② `_shared_domain_session` 的 16 处 patch 会因搬走而**静默失效**（测试仍绿、退避/会话逻辑不再被验证）。

### 3.2 TDC 报表 —— `web/crawler_boot.py`（11 条）

**register**：`register_tdc_routes(app, deps)`（`:2542`）；**deps**：同 `CrawlerRouteDeps`（`:103`），实际用到 `tdc_export_cache`（经 `current_app.extensions`，`:1758`）与 `_shared_domain_session`（`:1778`）。

| # | 方法 | 路径 | handler（行） | deps | 前端消费者（文件:行） | golden |
|---|---|---|---|---|---|---|
| 1 | POST | `/api/tdc/data-model/query` | `api_tdc_data_model_query`（`:2548`） | —（模块级） | `modes.js:211` | 1631 |
| 2 | POST | `/api/tdc/data-model/crawl-all` | `api_tdc_data_model_crawl_all`（`:2558`） | —（模块级） | `modes.js:212` | 1598 |
| 3 | POST | `/api/tdc/data-model/export` | `api_tdc_data_model_export`（`:2568`） | —（模块级） | `modes.js:213` | 1609 |
| 4 | POST | `/api/tdc/data-model/export-merged` | `api_tdc_data_model_export_merged`（`:2578`） | —（模块级） | `modes.js:217` | 1620 |
| 5 | POST | `/api/tdc/sor/car-type-projects` | `api_tdc_sor_car_type_projects`（`:2584`） | —（模块级） | `modes.js:237` | 1642 |
| 6 | POST | `/api/tdc/sor/query` | `api_tdc_sor_query`（`:2601`） | —（模块级） | `modes.js:234` | 1675 |
| 7 | POST | `/api/tdc/sor/crawl-all` | `api_tdc_sor_crawl_all`（`:2611`） | —（模块级） | `modes.js:235` | 1653 |
| 8 | POST | `/api/tdc/sor/export` | `api_tdc_sor_export`（`:2621`） | —（模块级） | `modes.js:236` | 1664 |
| 9 | POST | `/api/tdc/a-face/query` | `api_tdc_a_face_query`（`:2631`） | —（模块级） | `modes.js:254` | 1587 |
| 10 | POST | `/api/tdc/a-face/crawl-all` | `api_tdc_a_face_crawl_all`（`:2636`） | —（模块级） | `modes.js:255` | 1565 |
| 11 | POST | `/api/tdc/a-face/export` | `api_tdc_a_face_export`（`:2641`） | —（模块级） | `modes.js:256` | 1576 |

**目标插件**：`system-query`。
**旧 URL 别名**：11 条全部保留；建议插件内 `/api/p/system-query/tdc/<同后缀>`。
**测试清单**：

- 路由 golden：`routes.json:1565,1576,1587,1598,1609,1620,1631,1642,1653,1664,1675`。
- 接线冻结：`test_route_contract_behavior.py:103-119`（11 个 endpoint）。
- 行为：`:704`（sor/query 信封）、`:789`（a-face/query 失败信封）、`:672`（`/api/tdc/sor/query` 是三条已知缺 `no-store` 的路径之一，`:632-638`）。
- 具体路由断言：`tests/test_deliverables_web.py:539,998,1180,1441,1465,1489`；`tests/test_tdc_merged_export.py:163,169`；`tests/test_plugin_system_query.py:259`（前端拼接口径）。
- **patch 目标**：`web.crawler_boot.TDCCrawlerClient` 3 处（`tests/test_deliverables_web.py:332`、`tests/test_tdc_merged_export.py:190,430`）、`TDCPasswordAuthClient` 1 处（`test_deliverables_web.py:333`）、`_tdc_official_data_model_preview` 2 处（`test_deliverables_web.py:818,854`）、`_shared_domain_session` 16 处（Aras/TDC 共用入口，逐条归属需在批次契约里核对）。
**结论**：**候选（B 类）**。单一消费者 + 插件是行为所有者，满足 B2①②；但必须先解决 §6 别名机制，且 patch 目标要逐条改成新模块路径（不是"删掉 patch"）。

### 3.3 表单目录 —— `web/crawler_boot.py`（4 条）

**register**：`register_form_catalog_routes(app, deps)`（`:2799`）；**deps**：`deliverable_form_service`、`section_rollup_store`（`:2803-2804`）+ `db`。`section_rollup_store` 经 `_form_section_rollup`（`:2873-2878`）服务 `view`/`rows` 的归集口径。

| # | 方法 | 路径 | handler（行） | deps | 前端消费者（文件:行） | golden |
|---|---|---|---|---|---|---|
| 1 | GET | `/api/deliverable-forms/<form_key>/view` | `api_deliverable_form_view`（`:2882`） | `deliverable_form_service`、`section_rollup_store` | `project_overview/static/deliverable/form-analysis.js:871`、`simple.js:73` | 179 |
| 2 | GET | `/api/deliverable-forms/<form_key>/rows` | `api_deliverable_form_rows`（`:2908`） | `deliverable_form_service`、`section_rollup_store` | `form-analysis.js:872`、`simple.js:84` | 157 |
| 3 | GET | `/api/deliverable-forms/<form_key>/statistics` | `api_deliverable_form_statistics`（`:2944`） | `db` | `form-analysis.js:770` | 168 |
| 4 | GET | `/api/deliverables/catalog` | `api_deliverables_catalog`（`:2962`） | `db` | `project_overview/static/details/external.js:12` | 190 |

**目标插件**：**待裁决**。消费者是 `project-overview`，但数据/快照所有者是 `deliverable-forms`（其插件已有 `GET /api/p/deliverable-forms/forms`、`/registry`、`/forms/<form_key>/rows`，`routes.json:476,487,498`）。两者都不是"单一所有者+单一消费者"。
**旧 URL 别名**：4 条必须保留；若迁入 `deliverable-forms`，则 `project-overview` 前端需改调 `/api/p/deliverable-forms/*`（跨插件 HTTP 耦合）或旧路径走别名。
**测试清单**：golden `routes.json:157,168,179,190`；接线 `test_route_contract_behavior.py:120-129`；行为 `:652`（catalog 读信封）、`:672`（catalog 缺 `no-store` 已登记）、`:797`（statistics）；具体断言 `tests/test_deliverable_form_api.py:171`、`tests/test_deliverable_form_analysis_golden.py:11-12`、`tests/test_deliverables_web.py:347`、`tests/test_plugin_project_overview_status.py:98`。
**结论**：**暂缓**，列为裁决项 Q3。

### 3.4 Excel —— `web/excel_boot.py`（13 条）｜**唯一 A 类可迁移域**

**register**：`register_excel_routes(app, deps)`（`:44`）；**deps**：`ExcelRouteDeps`（`:23`），**6 字段**：`excel_admin_service`、`excel_worker_controller`、`local_mutation_error`、`json_error`、`validation_error`、`safe_attachment_basename`。

| # | 方法 | 路径 | handler（行） | deps | 前端消费者（文件:行） | golden |
|---|---|---|---|---|---|---|
| 1 | GET | `/api/excel-roots` | `api_excel_roots_list`（`:54`） | `excel_admin_service` | `excel_tasks/static/workspace.js:490` | 311 |
| 2 | POST | `/api/excel-tasks` | `api_excel_tasks_create`（`:67`） | `excel_admin_service`、`validation_error` | `workspace.js:572`、`logic.js:116` | 333 |
| 3 | GET | `/api/excel-tasks` | `api_excel_tasks_list`（`:94`） | `excel_admin_service` | `workspace.js:698` | 322 |
| 4 | GET | `/api/excel-worker/status` | `api_excel_worker_status`（`:112`） | `excel_worker_controller` | `workspace.js:513` | 388 |
| 5 | POST | `/api/excel-worker/start` | `api_excel_worker_start`（`:120`） | `excel_worker_controller` | `workspace.js:667`（`${action}`） | 377 |
| 6 | POST | `/api/excel-worker/stop` | `api_excel_worker_stop`（`:138`） | `excel_worker_controller` | `workspace.js:667` | 399 |
| 7 | GET | `/api/excel-tasks/<int:task_id>` | `api_excel_task_detail`（`:154`） | `excel_admin_service` | `workspace.js:546-549` | 344 |
| 8 | GET | `/api/excel-tasks/<int:task_id>/runs` | `api_excel_task_runs`（`:169`） | `excel_admin_service` | `workspace.js:550` | 366 |
| 9 | GET | `/api/excel-tasks/<int:task_id>/artifacts` | `api_excel_task_artifacts`（`:184`） | `excel_admin_service` | `workspace.js:551` | 355 |
| 10 | GET | `/api/excel-artifacts/<int:artifact_id>` | `api_excel_artifact_detail`（`:199`） | `excel_admin_service` | 范围内未查到前端直接调用（golden + 测试覆盖） | 267 |
| 11 | GET | `/api/excel-artifacts/<int:artifact_id>/download` | `api_excel_artifact_download`（`:214`） | `excel_admin_service`、`safe_attachment_basename` | `workspace.js:318` | 278 |
| 12 | GET | `/api/excel-artifacts/<int:artifact_id>/download-audit` | `api_excel_artifact_download_audit`（`:244`） | `excel_admin_service` | `workspace.js:751` | 289 |
| 13 | GET | `/api/excel-artifacts/retention-plan` | `api_excel_artifacts_retention_plan`（`:264`） | `excel_admin_service` | `workspace.js:406` | 300 |

**目标插件**：`excel-tasks`（唯一消费者；插件已有 `GET /api/p/excel-tasks/env-check`，`routes.json:520`）。
**旧 URL 别名**：13 条全部保留；建议插件内 `/api/p/excel-tasks/{roots,tasks,tasks/<id>,artifacts/<id>,worker/<action>,artifacts/retention-plan}`，旧 `/api/excel-*` 同 handler 别名。
**deps 就绪度**（对照 `app.extensions` 16 项）：`excel_admin_service` → `app.extensions["excel_task_admin"]`（`web/app.py:477`）✅；`excel_worker_controller` → `["excel_worker_controller"]`（`:485`）✅；`local_mutation_error` → `HostContext.local_guard` ✅；`json_error` → `HostContext.json_error` ✅；**`validation_error`（`:50`，被 4 处调用：`:82,106,258,276`）与 `safe_attachment_basename`（`:51`，`:223`）不是宿主服务** ❌ → 必须先决定"插件自带 vs 宿主提供"（裁决项 Q4）。
**测试清单**：

- 路由 golden：`routes.json:267,278,289,300,311,322,333,344,355,366,377,388,399`。
- 接线冻结：`test_route_contract_behavior.py:130-148`（13 个 endpoint）、`:645-648`（读用例）。
- 行为：`:977`（download 附件头）、`:989`（完整性不匹配）、`:799`（artifact 读信封）、`:877`（写保护）。
- 具体断言：`tests/test_excel_tasks_api.py:218,1483,1847,1867,2213,2255`；`tests/test_excel_worker_api.py:47,48,53`；`tests/test_plugin_excel_tasks.py:80-91`（前端拼接口径）。
- patch 目标：范围内未查到对 `web.excel_boot` 的 `setattr`/`patch.object`（**迁移风险最低**）。
**结论**：**可迁移**，按 §5.2 的 E1–E4 分 4 批。

### 3.5 任务中心 —— `web/tasks_boot.py`（6 条）｜不迁移

**register**：`register_tasks_routes(app, deps)`（`:118`）；**deps**：`TasksRouteDeps`（`:95`）：`db`、`crawl_task_runner`、`excel_admin_service`、`excel_repository`、`local_mutation_error`、`json_error`、`safe_attachment_basename`。

| # | 方法 | 路径 | handler（行） | deps | 前端消费者（文件:行） | golden |
|---|---|---|---|---|---|---|
| 1 | GET | `/api/tasks` | `api_tasks_list`（`:339`） | `db`、`crawl_task_runner`、`excel_admin_service`、`excel_repository` | `host/chrome/TaskCenter.js:168`、`system_query/query.js`、`workbench/today.js:16` | 1499 |
| 2 | POST | `/api/tasks/<task_id>/cancel` | `api_tasks_cancel`（`:418`） | 同上（无 `excel_repository`） | `TaskCenter.js:253`、`query.js:466`、`project_overview/deliverable/discovery.js:60`、`excel_tasks/workspace.js:722` | 1521 |
| 3 | POST | `/api/tasks/<task_id>/retry` | `api_tasks_retry`（`:485`） | 同上 | `TaskCenter.js:253` | 1554 |
| 4 | GET | `/api/tasks/<task_id>/download` | `api_tasks_download`（`:553`） | 同上 + `safe_attachment_basename` | `TaskCenter.js:128`、`query.js:441` | 1532 |
| 5 | GET | `/api/tasks/<task_id>` | `api_tasks_get`（`:643`） | —（模块级） | `query.js:403`、`discovery.js:85` | 1510 |
| 6 | GET | `/api/tasks/<task_id>/result` | `api_tasks_result`（`:652`） | `crawl_task_runner` | `query.js:447`、`discovery.js:100` | 1543 |

**目标插件**：**无**。消费者 5 处（宿主壳 + 4 个插件），且 `excel_repository` 不在 `app.extensions` 中（`web/app.py:471` 局部变量）。
**旧 URL 别名**：不适用（不迁移）。
**测试清单**：golden `routes.json:1499,1510,1521,1532,1543,1554`；接线 `test_route_contract_behavior.py:149-160`；行为 `:649`、`:800`（download）、`:998`（附件头）；具体 `tests/test_tasks_api.py:61,153`、`tests/test_tasks_cleanup_chain.py:361`、`tests/test_host_chrome.py:85-86`。
**结论**：**不迁移**（B3/B4）：任务是宿主级基础设施（CONTRACTS C6），宿主壳 `TaskCenter.js` 直接消费。

### 3.6 宿主设置/版本 —— `web/host_boot.py`（6 条）｜不迁移

**register**：`register_host_service_routes(app, deps)`（`:57`）；**deps**：`HostRouteDeps`（`:41`）：`settings_store`、`domain_sessions`、`credential_vault`、`excel_admin_service`、`tdc_export_cache`、`local_mutation_error`、`json_ok`、`json_error`、`sanitize_error_message`、`validation_error`。

| # | 方法 | 路径 | handler（行） | deps | 前端消费者（文件:行） | golden |
|---|---|---|---|---|---|---|
| 1 | GET | `/api/version` | `api_version`（`:61`） | —（`core.version`） | `host/chrome/VersionDialog.js:13`；`settings/app-updates.js:40,49`、`service-status.js:88` | 1686 |
| 2 | GET | `/api/settings` | `api_settings_get`（`:68`） | `settings_store`、`domain_sessions`、`credential_vault`、`excel_admin_service` | `host/session.js:85,91`；`settings/general.js:73`、`settings-form.js:151`；`project_overview/auto-sync.js:61`、`policy.js:617`；`workbench/today.js:12,202`；`scheduled_archive/jobs.js:599` | 1444 |
| 3 | PATCH | `/api/settings` | `api_settings_update`（`:84`） | `settings_store`、`local_mutation_error`、`json_error`、`validation_error` | `settings/settings-form.js:151` | 1455 |
| 4 | POST | `/api/settings/folders/native` | `api_settings_native_folder`（`:100`） | `local_mutation_error`、`json_error`、`sanitize_error_message`、`validation_error` | `settings/settings-form.js:56` | 1477 |
| 5 | POST | `/api/settings/domain-login` | `api_domain_login`（`:126`） | `domain_sessions`、`credential_vault`、`tdc_export_cache`、`local_mutation_error`、`sanitize_error_message`、`validation_error` | `host/session.js:138,166`；`settings/sessions.js:63` | 1466 |
| 6 | DELETE | `/api/settings/sessions` | `api_domain_sessions_clear`（`:191`） | 同上 | `settings/sessions.js:130` | 1488 |

**目标插件**：**host**（`web/host_boot.py` 顶部注释即声明"属于宿主本身，不依赖任何可禁用的业务插件（CONTRACTS.md C8）"）。
**测试清单**：golden `routes.json:1444,1455,1466,1477,1488,1686`；接线 `test_route_contract_behavior.py:161-172`；行为 `:641-642`、`:803`、`:859`、`:905`（写保护）；具体 `tests/test_settings_security.py:442,493,512`、`tests/test_plugin_settings.py:87,92`、`tests/test_version_and_usability.py:264,294,321`。
**patch 目标**：`web.host_boot.ArasECMAuthClient` 4、`TDCPasswordAuthClient` 4、`store_windows_generic_credential` 2（`tests/test_settings_security.py:471-472,528-529,571-572,600-602`）。
**结论**：**不迁移**（B3）：凭据/DPAPI/域会话是平台职责，且 4 个前端面共用。

### 3.7 宿主更新 —— `web/host_boot.py` + `web/app.py`（5 条）｜不迁移

| # | 方法 | 路径 | handler（行） | deps | 前端消费者（文件:行） | golden |
|---|---|---|---|---|---|---|
| 1 | GET | `/api/host/manifest` | `api_host_manifest`（`web/app.py:698`） | `registry` | `host/shell.js:2,120` | 410 |
| 2 | GET | `/api/host/updates` | `api_host_updates`（`web/app.py:716`） | `updates`、`registry` | `settings/updates.js:66` | 421 |
| 3 | POST | `/api/host/updates/import` | `api_host_updates_import`（`web/host_boot.py:233`） | `updates`、`registry`、`local_mutation_error`、`sanitize_error_message` | `settings/updates.js:30` | 454 |
| 4 | POST | `/api/host/updates/<plugin_id>/discard` | `api_host_updates_discard`（`:262`） | `updates`、`local_mutation_error` | `settings/updates.js:103,110` | 432 |
| 5 | POST | `/api/host/updates/<plugin_id>/rollback` | `api_host_updates_rollback`（`:271`） | `updates`、`local_mutation_error` | `settings/updates.js:103,110` | 443 |

**register**：`register_host_update_routes(...)`（`:218`），由 `_install_plugin_host` 在插件加载**之后**调用（`web/app.py:721-730`），因为需要 `updates`/`registry` 实例。
**目标插件**：**host**。
**测试清单**：golden `routes.json:410,421,432,443,454`；接线 `test_route_contract_behavior.py:173-181`；行为 `:806`、`:811`；具体 `tests/test_plugin_updates.py:166`、`tests/test_plugin_settings.py:103`、`tests/test_vse_boot_app_updates.py:101`。
**结论**：**不迁移**（B3）：见 §4.2。

### 3.8 原件留存 —— `web/archive_boot.py`（10 条）

**register**：`register_archive_routes(app, deps)`（`:65`）；**deps**：`ArchiveRouteDeps`（`:40`）：`db`、`archive_admin_service`、`excel_admin_service`、`sanitize_error_message`、`local_mutation_error`、`json_ok`、`json_error`、`validation_error`。

| # | 方法 | 路径 | handler（行） | deps | 前端消费者（文件:行） | golden |
|---|---|---|---|---|---|---|
| 1 | GET | `/api/scheduled-archive/folders` | `api_scheduled_archive_folders`（`:77`） | `archive_admin_service` | 范围内未查到插件前端直接调用 | 1334 |
| 2 | POST | `/api/scheduled-archive/folders/native` | `api_scheduled_archive_native_folder`（`:92`） | `archive_admin_service` | 同上 | 1345 |
| 3 | GET | `/api/scheduled-archive/jobs` | `api_scheduled_archive_jobs`（`:118`） | `archive_admin_service` | `scheduled_archive/static/archive_data.js:6`、`jobs.js:2`；`project_overview/static/archive-deliverable.js:262` | 1356 |
| 4 | POST | `/api/scheduled-archive/jobs` | `api_scheduled_archive_job_create`（`:128`） | `archive_admin_service` | `archive-deliverable.js:262` | 1367 |
| 5 | PATCH | `/api/scheduled-archive/jobs/<job_key>` | `api_scheduled_archive_job_update`（`:146`） | `archive_admin_service` | `archive-deliverable.js:114` | 1378 |
| 6 | DELETE | `/api/scheduled-archive/jobs/<job_key>` | `api_scheduled_archive_job_archive`（`:175`） | `archive_admin_service` | `archive-deliverable.js:114` | 1389 |
| 7 | GET | `/api/scheduled-archive/runs` | `api_scheduled_archive_runs`（`:198`） | `archive_admin_service` | `project_overview/deliverable/detail-watchlist.js:11`、`archive-deliverable.js:63` | 1411 |
| 8 | GET | `/api/scheduled-archive/runs/<int:run_id>/artifacts` | `api_scheduled_archive_artifacts`（`:215`） | `db`、`archive_admin_service` | 范围内未查到插件前端直接调用 | 1422 |
| 9 | GET | `/api/scheduled-archive/config-audit` | `api_scheduled_archive_config_audit`（`:231`） | `archive_admin_service` | 范围内未查到插件前端直接调用 | 1323 |
| 10 | POST | `/api/scheduled-archive/jobs/<job_key>/sync-now` | `api_scheduled_archive_sync_now`（`:248`） | `archive_admin_service` | `project_overview/details/sync-settings-logic.js:99` | 1400 |

**目标插件**：`scheduled-archive`（但第 3、5、6、7、10 条被 `project-overview` 共用）。
**旧 URL 别名**：10 条全部保留。
**测试清单**：golden `routes.json:1323,1334,1345,1356,1367,1378,1389,1400,1411,1422`；接线 `test_route_contract_behavior.py:182-197`；行为 `:643-644`、`:814`；具体 `tests/test_scheduled_archive_admin_api.py:93,170,681,740,789`、`tests/test_scheduled_archive_folder_api.py:28,68`、`tests/test_plugin_scheduled_archive.py:68,226`。
**结论**：**暂缓**：第 3/5/6/7/10 条被 `project-overview` 消费（B2①），需先决定"跨插件调用"还是"留在 host"。

### 3.9 项目状态 —— `web/project_status_boot.py`（27 条）

**register**：`register_project_status_routes(app, deps)`（`:1409`）；**deps**：`ProjectStatusRouteDeps`（`:1384`）：`db`、`analytics_service`、`archive_admin_service`、`deliverable_analysis_service`、`discovery_service`、`project_status_clock`、`section_rollup_store`、`update_service`。

| # | 方法 | 路径 | handler（行） | deps | 前端消费者（文件:行） | golden |
|---|---|---|---|---|---|---|
| 1 | GET | `/api/project-status` | `api_project_status`（`:1465`） | —（`current_project_status` 闭包） | `project_overview/status.js:3`、`shared/status-data.js:7,9`、`deliverable.js:48`；`workbench/project.js:12`、`today.js:11`、`wizard.js:534`；`scheduled_archive/jobs.js:603` | 1026 |
| 2 | PATCH | `/api/project-status/phases/<phase_id>` | `api_project_status_phase_update`（`:1481`） | `db` | `project_overview/plan.js:34`、`auto-sync.js:111`；`workbench/plan-edit.js:122` | 1213 |
| 3 | GET | `.../deliverables/<id>/analysis` | `api_project_status_deliverable_analysis`（`:1516`） | `deliverable_analysis_service` | `project_overview/deliverable/analysis.js:129,192,324,473,589` | 1059 |
| 4 | GET | `.../analysis/items` | `api_project_status_deliverable_analysis_items`（`:1552`） | `deliverable_analysis_service` | 同上 | 1070 |
| 5 | GET | `.../chart-labels` | `api_project_status_chart_labels`（`:1611`） | `deliverable_analysis_service` | `project_overview/deliverable/analysis.js:192` | 1092 |
| 6 | PUT | `.../chart-labels` | `api_project_status_chart_labels_write`（`:1629`） | `deliverable_analysis_service` | `analysis.js:129` | 1103 |
| 7 | GET | `/api/project-status/section-rollup` | `api_section_rollup_get`（`:1653`） | `section_rollup_store` | `project_overview/deliverable/form-analysis.js:297` | 1290 |
| 8 | PUT | `/api/project-status/section-rollup` | `api_section_rollup_put`（`:1659`） | `section_rollup_store` | 同上 | 1301 |
| 9 | PATCH | `/api/project-status/deliverables/<id>` | `api_project_status_deliverable_update`（`:1675`） | `update_service` | `project_overview/deliverable/edit.js:98,182`、`shared/status-edit.js:15` | 1048 |
| 10 | GET | `.../update-policy` | `api_project_status_update_policy`（`:1728`） | `update_service` | `project_overview/deliverable/policy.js:60-61` | 1191 |
| 11 | PATCH | `.../update-policy` | `api_project_status_update_policy_write`（`:1741`） | `update_service` | `policy.js:60-61` | 1202 |
| 12 | GET | `/api/project-status/updates` | `api_project_status_updates`（`:1762`） | `update_service` | `project_overview/deliverable/policy.js:321` | 1312 |
| 13 | GET | `.../mapping-discovery` | `api_project_status_mapping_discovery_history`（`:1778`） | `discovery_service` | `policy.js:618`、`evidence.js:363` | 1125 |
| 14 | GET | `.../candidate-preview` | `api_project_status_candidate_preview`（`:1788`） | `discovery_service` | `evidence.js:364` | 1081 |
| 15 | POST | `.../mapping-discovery` | `api_project_status_mapping_discovery`（`:1801`） | `db`、`discovery_service` | `project_overview/deliverable/discovery.js:132`（POST）；GET 复用 `policy.js:61,618`、`evidence.js:363` | 1136 |
| 16 | POST | `.../mapping-discovery/cancel` | `api_project_status_mapping_discovery_cancel`（`:2407`） | —（`_release_discovery_cancel`） | `project_overview/deliverable/discovery.js:54` | 1147 |
| 17 | GET | `/api/project-status/analytics` | `api_project_status_analytics`（`:2458`） | `analytics_service` | `project_overview/deliverable/evidence.js:362` | 1037 |
| 18 | GET | `/api/project-status/runs` | `api_project_status_runs`（`:2468`） | `analytics_service` | `evidence.js:365` | 1235 |
| 19 | GET | `/api/project-status/runs/<int:run_id>/artifacts` | `api_project_status_run_artifacts`（`:2482`） | `db` | `evidence.js:176` | 1246 |
| 20 | GET | `.../unified-status` | `api_project_status_unified_status`（`:2495`） | `update_service`、`discovery_service`、`analytics_service`、`archive_admin_service` | `project_overview/deliverable/evidence.js:44` | 1180 |
| 21 | GET | `.../debug-bundle` | `api_project_status_debug_bundle`（`:2618`） | `section_rollup_store`、`update_service`、`discovery_service`、`analytics_service` | `evidence.js:140`（`?format=`） | 1114 |
| 22 | POST | `.../sync-now` | `api_project_status_sync_now`（`:2678`） | `db`、`update_service`、`deliverable_analysis_service` | `details/sync-bar.js:136`、`auto-sync.js:67` | 1169 |
| 23 | POST | `.../sync-by-car-type` | `api_project_status_sync_by_car_type`（`:2761`） | `db`、`update_service`、`deliverable_analysis_service` | `project_overview/deliverable/analysis.js:473` | 1158 |
| 24 | GET | `/api/project-status/scheduler` | `api_project_status_scheduler_status`（`:2811`） | `db` | `details/sync-bar.js:10`；`workbench/project.js:12`、`today.js:13` | 1257 |
| 25 | POST | `/api/project-status/scheduler/config` | `api_project_status_scheduler_config`（`:2836`） | `db` | `details/sync-bar.js:11` | 1268 |
| 26 | POST | `/api/project-status/scheduler/sync-all` | `api_project_status_scheduler_sync_all`（`:2883`） | `db`、`update_service` | `details/sync-bar.js:12`；`workbench/project.js:63` | 1279 |
| 27 | PATCH | `/api/project-status/phases/<phase_id>/milestones` | `api_project_status_milestones_update`（`:2931`） | `db` | `project_overview/plan.js:35`；`workbench/plan-edit.js:2` | 1224 |

**目标插件**：`project-overview`（但 3 个插件 + 宿主共用）。
**旧 URL 别名**：27 条全部保留。
**测试清单**：golden `routes.json:1026,1037,1048,1059,1070,1081,1092,1103,1114,1125,1136,1147,1158,1169,1180,1191,1202,1213,1224,1235,1246,1257,1268,1279,1290,1301,1312`；接线 `test_route_contract_behavior.py:198-230`（27 个 endpoint）；行为 `:650-651`（读）、`:828`（失败）、`:877/:895`（写保护）、`:1009`（debug-bundle 附件头）、`:1148`（sync-now 保持 200+ok）、`:1181`（未知交付物 404）、`:1190`（golden 只读交叉校验）；具体 `tests/test_project_status_scheduler_api.py:26,62,88`、`tests/test_project_status_policy_api.py:390`、`tests/test_plan_edit_frontend.py:8`、`tests/test_project_status_admin_api.py:139`。
**patch 目标（最高风险）**：`web.project_status_boot._build_tdc_client_from_payload` **29 处**、`_build_aras_client_from_payload` 1 处、`_mapping_discovery_query_identity` 1 处、`_crawl_runner_from_request` 1 处、`create_production_registry` 2 处（含 `tests/test_route_contract_behavior.py:1166`）。
**deps 就绪度**：`deliverable_analysis_service`→`app.extensions["deliverable_analysis"]`（`web/app.py:427`）✅；`archive_admin_service`→`["scheduled_archive_admin"]`（`:440`）✅；**`update_service`、`discovery_service`、`analytics_service`、`section_rollup_store`、`project_status_clock` 均不在 `app.extensions`** ❌（`web/app.py:418-426` 只入局部变量）。
**结论**：**暂缓**。三个阻断项：多消费者（3 插件）、29 处 patch、缺 5 个宿主服务（补服务字典 = 宿主接口变更 = 整包发布，见 RELEASE_MATRIX §2 规则 1）。

### 3.10 EWO 富化 —— `web/ewo_enrichment.py`（4 条）

**register**：`register_ewo_enrichment(app, service, registry, local_guard, *, crawler_factory=ArasCrawlerClient)`（`:12`）；**deps**：`service`（`EWOEnrichment`，`app.extensions["ewo_enrichment"]`）、`registry`（`DomainSessionRegistry`）、`local_guard`。

| # | 方法 | 路径 | handler（行） | deps | 前端消费者（文件:行） | golden |
|---|---|---|---|---|---|---|
| 1 | POST | `/api/aras/ewo/enrichment/jobs` | `ewo_enrichment_prepare`（`:70`） | `service`、`registry`、`local_guard` | `web/static/ewo-enrichment.js:526` | 14 |
| 2 | POST | `/api/aras/ewo/enrichment/jobs/restore` | `ewo_enrichment_restore`（`:74`） | 同上 | `ewo-enrichment.js:526` | 47 |
| 3 | POST | `/api/aras/ewo/enrichment/jobs/<job_id>/run` | `ewo_enrichment_run`（`:78`） | 同上 | `ewo-enrichment.js:549,571` | 25 |
| 4 | POST | `/api/aras/ewo/enrichment/jobs/<job_id>/status` | `ewo_enrichment_status`（`:82`） | 同上 | `ewo-enrichment.js:593` | 36 |

**目标插件**：**待裁决**。消费者是**遗留全局脚本** `web/static/ewo-enrichment.js`（由 `web/templates/dashboard.html:30` 直接 `<script>` 加载），该脚本又被 `plugins/project_overview/static/deliverable/detail.js:55,75` 以 `window.EWOEnrichment` 方式挂载。
**测试清单**：golden `routes.json:14,25,36,47`；接线 `test_route_contract_behavior.py:231-240`；行为 `:742`（status 信封）；具体 `tests/test_ewo_enrichment_api.py:12,61,77`。
**结论**：**暂缓**：前端未插件化（B2①"消费者是插件"不成立），先做前端退役/迁移（裁决项 Q5）。

### 3.11 诊断 —— `web/diagnostics.py`（6 条）｜不迁移

**register**：`install_diagnostics(app, recorder=None, local_guard=None)`（`:342`）；同时注册 **app 级** `before_request`（`:352`）、`after_request`、`teardown` 钩子（对全部 `/api/*` 生效，`:361-369`）。

| # | 方法 | 路径 | handler（行） | 关键依赖 | 前端消费者（文件:行） | golden |
|---|---|---|---|---|---|---|
| 1 | GET | `/api/diagnostics` | `diagnostic_status`（`:420`） | `recorder`、白名单 | `web/static/diagnostics.js:39,120`；`plugins/diagnostics/static/self-check.js:13,43`；`project_overview/deliverable/policy.js:132` | 201 |
| 2 | POST | `/api/diagnostics/start` | `diagnostic_start`（`:424`） | `recorder`、`local_guard` | `diagnostics.js:133`；`self-check.js:28` | 245 |
| 3 | POST | `/api/diagnostics/stop` | `diagnostic_stop`（`:439`） | `recorder`、`local_guard` | `diagnostics.js:133`；`self-check.js:18,33` | 256 |
| 4 | POST | `/api/diagnostics/mark` | `diagnostic_mark`（`:446`） | `recorder`、`local_guard` | 范围内未查到前端直接调用 | 234 |
| 5 | POST | `/api/diagnostics/events` | `diagnostic_events`（`:457`） | `recorder`、速率限制、`local_guard` | `diagnostics.js:28` | 223 |
| 6 | GET | `/api/diagnostics/bundles/<identity>` | `diagnostic_download`（`:479`） | `filter_diagnostic_bundle`（`:235`）、白名单 | `diagnostics.js:103`；`self-check.js:53` | 212 |

**目标插件**：**host**（路由体可讨论，但白名单/脱敏/录制钩子必须留 host）。
**测试清单**：golden `routes.json:201,212,223,234,245,256`；接线 `test_route_contract_behavior.py:241-252`；行为 `:766`（无 `{ok}` 信封，既有差异已钉住）、`:841`（legacy 字符串错误）、`:868`、`:1020`、`:1029`；具体 `tests/test_diagnostics_whitelist.py:162,164,167,358,363`、`tests/test_web_diagnostics.py:25,30,32,52`。
**结论**：**不迁移**（B3）：见 §4.5。

### 3.12 本机安全 —— `web/security.py`（1 条）｜不迁移

| # | 方法 | 路径 | handler（行） | 依赖 | 前端消费者 | golden |
|---|---|---|---|---|---|---|
| 1 | POST | `/api/security/boot-exchange` | `api_security_boot_exchange`（`:114`） | `BootTicketStore`（`:47`）、`LocalSessionStore`（`:70`） | `web/static/host/boot-exchange.js` | 1433 |

**register**：`install_local_security`（`web/security.py:164`，由 `web/app.py:394-396` 在 `before_request` loopback 守卫之后调用）。
**测试清单**：golden `routes.json:1433`；接线 `test_route_contract_behavior.py:266-267,914`；`tests/test_local_security.py`（C7 全套）、`tests/test_local_security_integration.py:15,292`。
**结论**：**不迁移**（B3）：见 §4.1。

### 3.13 组合根 —— `web/app.py`（3 条）｜不迁移

| # | 方法 | 路径 | handler（行） | 依赖 | 消费者 | golden |
|---|---|---|---|---|---|---|
| 1 | GET | `/` | `index`（`:490`） | `render_template("dashboard.html")` | 浏览器 | 3 |
| 2 | GET | `/favicon.ico` | `favicon`（`:497`） | — | 浏览器 | 1697 |
| 3 | GET | `/api/overview` | `api_overview`（`:504`） | `db`（`_query_overview`，`:243`） | 范围内未查到前端调用（仅测试） | 465 |

**测试清单**：golden `routes.json:3,465,1697`；接线 `test_route_contract_behavior.py:256-264`（`HOST_APP_ENDPOINTS` 冻结 5 个 endpoint：`index`、`favicon`、`api_overview`、`api_host_manifest`、`api_host_updates`）；`:581-582` 断言其 `__module__ == "web.app"`；`tests/test_overview_web.py:6`。
**结论**：**不迁移**。`/api/overview` 是唯一"业务味"的组合根路由，但无前端消费者，迁移收益为零；若将来清理，应作为独立"删除未使用路由"任务，而不是插件化批次。

---

## 4. 保留在 host 的清单与理由（不可迁移）

### 4.1 本机安全引导（`web/security.py`，1 条）

- 必须**先于任何插件**存在：`install_local_security` 在 `create_app` 早期注册（`web/app.py:394-396`），插件在 `:631` 才加载。
- 它是 **fail-closed 的 app 级 `before_request`**（`web/security.py:109-111`），不是一条孤立路由；插件（Blueprint）无法承担"关掉自己就关掉鉴权"的职责。
- 依赖方向：`web/security.py:32` 从 `web.crawler_boot` 取 `_loopback_hostname`/`_origin_tuple`——若搬进插件，会立即违反 §2.3 的边界测试。
- 契约：CONTRACTS C7（`docs/refactor-v2/CONTRACTS.md:128-145`）。

### 4.2 宿主更新（`host/updates.py` + 3 条 + 2 条）

- **自引用/权限**：更新机制负责"替换任意插件（含自己）"。把它放进可禁用插件 = 关掉该插件即可冻结更新能力，且插件能修改自己的加载器。
- **信任根**：签名校验使用 `host/trusted_keys.json`（`host/updates.py:56`），验签在 `_verify_signature`（`:118`），激活/回滚在 `PluginUpdates`（`:261`）。
- **启动回滚依赖它**：`web/app.py:670-693` 在插件加载失败时调用 `updates.rollback(...)`；该路径必须比插件更早、更可靠。
- 契约：CONTRACTS C8（`:154-155`）；RELEASE_MATRIX §2 规则 1（宿主接口变化 → 整包）。

### 4.3 设置 / 凭据 / 域会话（`web/host_boot.py` 6 条）

- 持有 Windows 凭据管理器与 DPAPI 库（`core/credential_provider`、`core/domain_identity`，`web/host_boot.py:21-27`；库文件在 `web/app.py:432`）。
- 4 个前端面共用（§3.6 消费者列），不满足 B2①。
- 域会话是**跨插件共享服务**（`app.extensions["domain_sessions"]`，`web/app.py:442`）：谁都不能拥有它，否则其它插件被它劫持。

### 4.4 任务中心（`web/tasks_boot.py` 6 条）

- 宿主壳 `web/static/host/chrome/TaskCenter.js:128,168,253` 直接消费；4 个插件消费（§3.5）。
- 是**跨领域聚合器**（crawl 任务 + Excel 任务 + 项目状态任务），不属于任何单一领域。
- 契约：CONTRACTS C6（`:116-126`）。

### 4.5 诊断白名单与录制钩子（`web/diagnostics.py` 6 条）

- 安全边界是**白名单 + 脱敏**：`DIAGNOSTIC_WHITELIST_FIELDS`（`web/diagnostics.py:22`）、严格白名单过滤（`:216-217`）、`filter_diagnostic_bundle`（`:235`）、`redact_diagnostics_text`（`:100-109`）。
- 这些是"导出包不得含敏感字段"的最后一道防线（CONTRACTS C10，`:171-179`）。放进可禁用插件 = 换成旧版/被替换的插件即可放宽脱敏。
- 录制是 **app 级钩子**（`before_request`/`after_request`/`teardown`，`:352-369`），覆盖所有 `/api/*`，不属于某个 Blueprint。
- 消费者 3 处（宿主遗留脚本 + 2 个插件），不满足 B2①。

### 4.6 静态宿主壳（`web/static/host/`、`web/templates/dashboard.html`）

- `shell.js` 是**插件加载器**（读 `/api/host/manifest`，`shell.js:2,120`）；`kit.js`/`api.js`/`pages.js` 是所有插件页面的公共运行时；`legacy-routes.js` 是书签兼容层（旧 `#hash` → `#p/<plugin>/<page>`）。
- 让插件拥有加载器 = 循环依赖 + 关掉它页面全黑。
- **遗留全局脚本**（需单独处置，不在本 ADR 迁移范围）：`web/static/diagnostics.js`、`web/static/ewo-enrichment.js`、`web/static/diagnostics.css`，由 `web/templates/dashboard.html:11,29,30` 直接加载。

### 4.7 组合根 3 条

见 §3.13：`/`、`/favicon.ico`、`/api/overview`。`/` 渲染宿主模板，`/api/overview` 无前端消费者。

### 4.8 多消费者领域 API（结论 B4）

| API 组 | 消费者数 | 消费者（文件:行） | 为什么不能进插件 |
|---|---|---|---|
| `/api/aras/ewo/query`、`/api/aras/paa/query` | 2 插件 | `system_query/modes.js:143,159`；`project_overview/deliverable/policy-logic.js:848,854` | 任一插件被禁用 → 另一插件策略编辑不可用 |
| `/api/project-status*` | 3 插件 | project-overview（12 文件）、workbench（4 文件）、`scheduled_archive/jobs.js:603` | 同上；且 29 处 patch 目标在宿主模块 |
| `/api/scheduled-archive/*` | 2 插件 | `scheduled_archive/static/{archive_data.js:6,jobs.js:2}`；project-overview（3 文件） | 同上 |
| `/api/deliverable-forms/*` | 1 插件（消费者≠所有者） | `project_overview/deliverable/{form-analysis.js:770,871,872,simple.js:73,84}` | 所有者是 `deliverable-forms`，消费者是 `project-overview`；跨插件 HTTP 耦合 |
| `/api/settings*`、`/api/version` | 宿主壳 + 3 插件 | §3.6 | 平台职责（§4.3） |
| `/api/tasks*` | 宿主壳 + 4 插件 | §3.5 | 平台职责（§4.4） |

---

## 5. 迁移批次（每批 ≤4 条路由或单一职责）

### 5.1 硬规则（每批都必须满足）

1. **粒度**：每批 ≤4 条路由，或 1 个内聚职责（职责批最多 5 条，且必须在批次契约里说明为什么不可再拆）。
2. **串行接线**：`web/app.py` 一次只改一个批次（新增/删除一个 `register_*` 调用或一段别名注册）。**禁止**并行两个批次改同一文件。
3. **同 rule 不双注册**：迁移提交必须**同一次**删除宿主注册 + 添加别名/插件注册。插件在 `:631` 之后加载，若宿主旧注册残留，Werkzeug 会命中**先注册的宿主路由**，新插件路由静默不生效。
4. **别名先行**：批次 0（§6 方案 A）必须先合入；没有别名机制的批次不得开工。
5. **契约同步**：同一提交内更新 `tests/test_route_contract_behavior.py` 的 `DOMAIN_WIRINGS`（`:87-253`）与 `HOST_APP_ENDPOINTS`/`SECURITY_ENDPOINTS`（`:256-267`），并**显式**重生成 `tests/golden/routes.json`（`VSE_ROUTE_SNAPSHOT_WRITE=1`），diff 必须逐条列出。
6. **patch 目标迁移**：任何被搬走的私有名，其 `setattr`/`patch.object` 目标必须**同批**改到新模块（或改成经宿主服务注入的假实现），不允许"删掉 patch 让它变绿"。
7. **不动 §4 清单**：批次不得触碰平台路由、静态壳、白名单代码。

### 5.2 批次顺序（按"可迁移度"降序）

**阶段 0（前置，必须先合入）**

| 批次 | 内容 | 路由数 | 说明 |
|---|---|---|---|
| **0-A** | 旧 URL 别名机制（§6 方案 A） | 0 | 只加机制 + 1 条自测（用现有路由做样本），不改任何生产路由 |
| **0-B** | 宿主服务字典补齐清单冻结 | 0 | 明确哪些服务"已就绪/需新增"（§3 各节 deps 就绪度），新增服务单独走宿主接口变更 |

**阶段 1（A 类：`excel-tasks`，13 条 → 4 批）**

| 批次 | 路由 | 条数 | 目标插件路径（建议） |
|---|---|---|---|
| **E1** | `GET /api/excel-roots`、`GET /api/excel-tasks`、`GET /api/excel-tasks/<int:task_id>`、`GET /api/excel-tasks/<int:task_id>/runs` | 4 | `/api/p/excel-tasks/{roots,tasks,tasks/<id>,tasks/<id>/runs}` |
| **E2** | `POST /api/excel-tasks`、`GET /api/excel-tasks/<int:task_id>/artifacts`、`GET /api/excel-artifacts/<int:artifact_id>`、`GET /api/excel-artifacts/retention-plan` | 4 | `/api/p/excel-tasks/{tasks,tasks/<id>/artifacts,artifacts/<id>,artifacts/retention-plan}` |
| **E3** | `GET /api/excel-artifacts/<int:artifact_id>/download`、`GET /api/excel-artifacts/<int:artifact_id>/download-audit` | 2 | `/api/p/excel-tasks/artifacts/<id>/{download,download-audit}` |
| **E4** | `GET /api/excel-worker/status`、`POST /api/excel-worker/start`、`POST /api/excel-worker/stop` | 3 | `/api/p/excel-tasks/worker/{status,start,stop}` |

**阶段 2（B 类候选：`system-query`，11 条 → 3 批）**

| 批次 | 路由 | 条数 |
|---|---|---|
| **T1** | `/api/tdc/data-model/{query,crawl-all,export,export-merged}` | 4 |
| **T2** | `/api/tdc/sor/{car-type-projects,query,crawl-all,export}` | 4 |
| **T3** | `/api/tdc/a-face/{query,crawl-all,export}` | 3 |

**阶段 3（B 类候选：`scheduled-archive`，10 条 → 3 批，需先解决 `project-overview` 共用）**

| 批次 | 路由 | 条数 |
|---|---|---|
| **A1** | `/api/scheduled-archive/{folders,folders/native,config-audit,runs/<int:run_id>/artifacts}` | 4 |
| **A2** | `POST /api/scheduled-archive/jobs`、`PATCH .../jobs/<job_key>`、`DELETE .../jobs/<job_key>`、`POST .../jobs/<job_key>/sync-now` | 4 |
| **A3** | `GET /api/scheduled-archive/jobs`、`GET /api/scheduled-archive/runs` | 2 |

**阶段 4（B 类候选：`project-overview`，27 条 → 8 批，阻断项最多）**

| 批次 | 路由 | 条数 |
|---|---|---|
| **P1** | `GET /api/project-status`、`PATCH /phases/<phase_id>`、`PATCH /phases/<phase_id>/milestones` | 3 |
| **P2** | `.../analysis`、`.../analysis/items`、`GET .../chart-labels`、`.../unified-status` | 4 |
| **P3** | `PUT .../chart-labels`、`GET/PUT /section-rollup`、`PATCH /deliverables/<id>` | 4 |
| **P4** | `GET/PATCH .../update-policy`、`GET /updates` | 3 |
| **P5** | `GET .../mapping-discovery`、`.../candidate-preview`、`POST .../mapping-discovery`、`.../mapping-discovery/cancel` | 4 |
| **P6** | `POST .../sync-now`、`POST .../sync-by-car-type`、`GET /scheduler`、`POST /scheduler/config` | 4 |
| **P7** | `GET /analytics`、`GET /runs`、`GET /runs/<int:run_id>/artifacts`、`GET .../debug-bundle` | 4 |
| **P8** | `POST /scheduler/sync-all` | 1 |

**阶段 5（其他，均需先满足各自前置）**：Aras（4 批：EWO 2 / PAA 3 / NCR 2 / 下载 2）、表单目录（1 批 4 条，需 Q3 裁决）、诊断（2 批 3+3，仅路由体）、EWO 富化（1 批 4 条，需前端先退役）。

### 5.3 每批验收（必须逐条给出真实输出）

| # | 验收项 | 命令 / 证据 | 通过判据 |
|---|---|---|---|
| 1 | 路由 golden **规则集不变** | `python -m pytest tests/test_route_contract_snapshot.py -q` | 无 `added`/`missing`；`changed` **恰好**是本批 `endpoint`/`view_function` 字段（**必须**逐条列出） |
| 2 | 旧 URL 仍可用 | 新增断言：旧 `rule+method` 与插件路径解析到**同一个 view function 对象** | `app.view_functions[old_endpoint] is app.view_functions[plugin_endpoint]`（方案 A） |
| 3 | 接线契约同步 | `python -m pytest tests/test_route_contract_behavior.py -q` | `DOMAIN_WIRINGS` 已更新且 `owned == _all_domain_endpoints()`（`:578`） |
| 4 | 行为不变 | 该领域既有测试文件（§3 各节"具体断言"列） | 全绿，且**没有**删除/跳过任何 patch 目标 |
| 5 | 插件边界 | `python -m pytest tests/test_plugin_host.py -q` | `test_repository_plugins_respect_boundaries`（`:316`）通过（插件未 import `web.*`） |
| 6 | 无路由重复 | 新增断言：`url_map` 中同一 `(rule, method)` 只出现一次 | 计数为 1 |
| 7 | 发布物判定 | RELEASE_MATRIX §2 | 只改 `web/` + `plugins/` → app 包；**动 `host/` → 整包 onedir zip** |

> **重要澄清（避免误读）**：`tests/golden/routes.json` 记录 `endpoint` 与 `view_function` 两个字段（`tests/test_route_contract_snapshot.py:134-142`）。路由一旦搬进插件，`endpoint` 必然从 `api_excel_*` 变为 `plugin_excel_tasks.*`。因此本 ADR 把"路由 golden 不变"精确定义为：**`rule` + `methods` + `is_write` + `envelope` + `download` 不变；`endpoint`/`view_function` 只允许在本批清单内变化**。

### 5.4 回滚方式

| 层级 | 手段 | 说明 |
|---|---|---|
| 单批代码 | `git revert <batch commit>`（由主控执行，不由执行者操作） | 因为每批独立提交 + 别名先行，revert 即回到"宿主注册 + 插件未接管" |
| 别名层 | 开关 `VSE_LEGACY_ALIAS=0`（建议） | 别名层整体关闭，旧路径回落到宿主实现（若宿主实现仍在）或 503 |
| 插件层 | `/api/host/updates/<plugin_id>/rollback`（`web/host_boot.py:271`） | 仅对**已安装包**有效；随包内置插件无回滚目标 |
| 插件禁用 | `VSE_TOOLBOX_PLUGIN_ONLY`（`web/app.py:660-661`） | **注意**：禁用插件会让已迁移路由消失——这正是 §6 方案 A 必须提供 `503 PluginUnavailable` 而不是 404 的原因 |

### 5.5 顺序依赖图

```
0-A 别名机制 ──► E1 ──► E2 ──► E3 ──► E4        (excel-tasks，A 类)
      │
      ├──► T1 ──► T2 ──► T3                     (system-query，需先改 16 处 patch 归属)
      ├──► A1 ──► A2 ──► A3                     (scheduled-archive，需先裁决 Q6)
      ├──► P1 … ──► P8                          (project-overview，需先裁决 Q7/Q8)
      ├──► 表单目录 1 批                          (需先裁决 Q3)
      └──► EWO 富化 1 批                          (需先裁决 Q5)
```

**结论**：阶段 1（Excel）是唯一"无阻断项"的起点；其余阶段各自带一个裁决项，**不得**越过裁决开工。

---

## 6. 旧 URL 别名机制（现状：**不存在**）

### 6.1 现状证据

- 插件 Blueprint 的 `url_prefix` 在 `host/registry.py:254` 固定为 `/api/p/<id>`；静态资源在 `:273` 固定为 `/plugins/<id>/static`。插件**无法**注册 `/api/excel-*` 这类宿主路径。
- `host/` 与 `web/` 的 `*.py` 范围内**未查到**任何"旧路由 → 插件 handler"的别名注册机制（`alias|legacy` 只命中 6 处无关变量名：`web/project_status_boot.py:239,246,247` 的 `legacy` 查询参数名、`:885` 的 `fieldAliases`、`:1228,1230` 的 `legacy_type`）。
- 因此"把路由搬进插件 + 旧 URL 继续可用"当前**无法同时成立**；这是本 ADR 把 0-A 定为前置批次的原因。

### 6.2 方案 A（推荐）：`web/app.py` 静态别名表 + 启动期强校验

- 在 `web/app.py` 维护 `LEGACY_ALIASES: dict[old_rule → (plugin_id, plugin_endpoint_name)]`。
- `_install_plugin_host` 在 `registry.load_all(...)` 之后：解析目标 endpoint → `app.add_url_rule(old_rule, endpoint=old_endpoint, view_func=app.view_functions[target], methods=[...])`。
- 目标插件未加载（被 `plugin_only` 禁用或加载失败）→ 旧路径注册为 `503 PluginUnavailable`（显式、可诊断），**不是** 404。
- 自测：`old_endpoint` 与 `plugin_endpoint` 指向**同一个函数对象**；`(rule, method)` 唯一。
- 发布通道：只改 `web/` → **app 包**（RELEASE_MATRIX §2）。

### 6.3 方案 B：`hostApi` 1.1 增加"别名声明"能力

- 在 `host/registry.py` 给 `PluginHost` 加 `legacy_routes(...)`，由插件自己声明旧路径；`host/plugin.py` 的 `HOST_API_VERSION` 升到 `1.1`（`>=1,<2` 的插件仍兼容）。
- 代价：**动 `host/` = 宿主接口变更 → 整包 onedir zip**（RELEASE_MATRIX §2 规则 1），且需要 W17-02 真机验证。
- 收益：别名随插件走，宿主不再维护硬编码表。

### 6.4 方案 C：不迁移，只做模块化

- 保持现状：路由永驻 `web/*_boot.py`；插件只贡献页面与 `/api/p/*` 自有路由。
- 代价：插件化目标退化为"页面插件化"；但零风险、零别名成本。

### 6.5 明确禁止

- **302/303 重定向**：CONTRACTS C8（`docs/refactor-v2/CONTRACTS.md:152`）明确"写 API 不靠 302/303（客户端方法语义会丢）"。
- **双注册**：同一 `(rule, method)` 同时存在宿主与插件注册（§5.1 规则 3）。

---

## 7. 待主控裁决项

| # | 事项 | 选项 | 建议 | 影响 |
|---|---|---|---|---|
| **Q1** | 别名机制选 A / B / C | A：`web/app.py` 静态表（app 包）；B：`hostApi` 1.1（整包）；C：不迁移 | **A** | A 只需 app 包；B 触发整包发布 + 真机验证；C 放弃业务插件化 |
| **Q2** | 阶段 1 是否立即开工（Excel 13 条 / 4 批） | 开工 / 等 0-A / 暂缓 | 先做 **0-A**，再开 E1 | Excel 是唯一无阻断域；0-A 不合入则 E1 无法保留旧 URL |
| **Q3** | `/api/deliverable-forms/*` 归谁 | ①留 host；②进 `deliverable-forms`（project-overview 改调 `/api/p/...`）；③进 `project-overview` | **①留 host**（本轮） | ②产生跨插件 HTTP 耦合 + 禁用即断；③让"页面插件"拥有数据快照，与 `deliverable-forms` 重复 |
| **Q4** | Excel 迁移缺的两个 web helper 怎么办：`validation_error`（`web/excel_boot.py:50`）、`safe_attachment_basename`（`:51`） | ①插件各自实现；②宿主加服务（`HostContext` 新字段）；③保留在 `web/` 由别名层调用 | **②**（`host.context` 加 `validation_error`/`safe_filename`，属宿主接口变更 → 整包）或**①**（仅 `safe_attachment_basename` 用 `core` 现成实现） | ②改发布通道；①有安全实现分叉风险（文件名清洗） |
| **Q5** | 遗留全局脚本 `web/static/{diagnostics.js,ewo-enrichment.js}` 与 `/api/aras/ewo/enrichment/*` | ①迁进对应插件静态目录；②退役；③保留 | **①（EWO 富化）**、**②（diagnostics.js，已被 `diagnostics` 插件 `self-check` 覆盖）** | 迁移前 `/api/aras/ewo/enrichment/*` 不得进插件（消费者不是插件） |
| **Q6** | `project-overview` 消费 `/api/scheduled-archive/*` 的 5 条怎么处理 | ①留 host；②project-overview 改调 `/api/p/scheduled-archive/...`；③抽"归档客户端"到 `core/services` 供两插件各自调用 | **①留 host**（本轮） | ②禁用 scheduled-archive 即断 project-overview 归档页；③是新服务拆分任务 |
| **Q7** | `project-status` 5 个服务是否补进 `app.extensions` | ①补（`update_service`/`discovery_service`/`analytics_service`/`section_rollup_store`/`project_status_clock`）；②不补、暂不迁移 | **②本轮不补**；补则单独走宿主接口变更任务 | ①`host/` 或 `web/app.py` 服务字典变化 → 发布通道与契约测试都要改 |
| **Q8** | `project_status_boot` 29 处 `_build_tdc_client_from_payload` patch 怎么处理 | ①同批改到插件模块路径；②改成注入假客户端（`host.context` 服务替换）；③不迁移 | **②**（长期正确）／**③**（本轮） | ①要求 29 个测试文件同批改，风险高；②需要先有可注入的客户端工厂服务 |
| **Q9** | `web/app.py` 93+45 别名回导何时退役 | ①所有领域迁移完成后一次性退役；②每域迁移完成即退役该域别名 | **①**（与 `DSH_SERVICE_SPLIT_INVENTORY.md` 裁决 5 一致） | ②会在批次中途改变 patch 目标，放大 §5.1 规则 6 的成本 |
| **Q10** | 诊断路由体是否进 `diagnostics` 插件（白名单留 host） | ①整体留 host；②路由体进插件、白名单/脱敏留 host | **①本轮留 host** | ②收益低（6 条只读/控制路由），但会把 app 级录制钩子与路由拆到两处 |


### 主控裁决记录（2026-11-01）

- Q1 采纳 A：`web/app.py` 静态别名表 + 启动期强校验，只走 app 包。
- Q2 先做 0-A（别名机制）再开 Excel E1；每批仍需主控另行批准为有界任务。
- Q3 `/api/deliverable-forms/*` 本轮留 host。
- Q4 本轮不新增 `HostContext` 字段：`safe_attachment_basename` 只在 `core` 已有同等实现时复用，否则该路由暂不迁移；新增宿主接口另案走整包。
- Q5 EWO 富化脚本随其插件迁移；`web/static/diagnostics.js` 在确认无消费者后退役（另案）。
- Q6 `/api/scheduled-archive/*` 本轮留 host。
- Q7 本轮不向 `app.extensions` 补 project-status 服务，该域暂不迁移。
- Q8 本轮不迁移 project_status_boot；长期按 ② 注入假客户端工厂另案。
- Q9 别名回导在所有领域迁移完成后一次性退役。
- Q10 诊断路由本轮整体留 host。

---

## 8. 本任务未移动生产路由（验证记录）

**改动范围**：仅新增 `docs/refactor-v2/DSH_PLUGINIZATION_ADR.md`。
未修改 `web/`、`host/`、`plugins/`、`services/`、`core/`、`tests/` 任何文件；未执行 `git add`/`commit`/`stash`/`checkout`/`reset`/`push`。

| 验证命令 | 结果 |
|---|---|
| `git rev-parse --short HEAD` | `abfc8f8`（见文首基线） |
| `git branch --show-current` | `dsh/v2-41` |
| `python -m pytest tests/test_route_contract_snapshot.py tests/test_route_contract_behavior.py tests/test_plugin_host.py -q -p no:cacheprovider` | `100 passed`（基线绿：本文件引用的契约测试真实可运行） |
| `python -c "from pathlib import Path; assert Path('docs/refactor-v2/DSH_PLUGINIZATION_ADR.md').read_text(encoding='utf-8').strip()"` | 退出码 0 |
| `git diff --check` | 无输出，退出码 0 |
| `git status --porcelain` | 仅 `?? docs/refactor-v2/DSH_PLUGINIZATION_ADR.md` |

---

## 附录 A：本文件数据的一键复核

```powershell
# 1) 基线
git rev-parse --short HEAD; git branch --show-current

# 2) 路由清单与总数（166 = 105 非插件 + 50 插件 + 11 静态）
python -c "import json;d=json.load(open('tests/golden/routes.json',encoding='utf-8'));print(len(d))"

# 3) 各 register_* 与路由数（装饰器扫描，含 handler 行号）
python -c "
import re,pathlib
for f in ['web/app.py','web/excel_boot.py','web/tasks_boot.py','web/host_boot.py','web/crawler_boot.py','web/archive_boot.py','web/project_status_boot.py','web/diagnostics.py','web/ewo_enrichment.py','web/security.py']:
    src=pathlib.Path(f).read_text(encoding='utf-8').splitlines()
    n=[i+1 for i,l in enumerate(src) if re.match(r'^\s*@app\.(route|get|post|put|patch|delete)\(',l)]
    print(f,len(n),n[:4])"

# 4) 插件路由前缀固定（无别名能力）
Select-String -Path host/registry.py -Pattern 'API_PREFIX|url_prefix'
Select-String -Path host/*.py,web/*.py -Pattern 'alias|legacy'
#    实测命中仅 6 处无关变量名（web/project_status_boot.py:239,246,247,885,1228,1230：
#    `legacy` 查询参数名、`fieldAliases`、`legacy_type`），**没有**任何"旧路由→插件"别名机制

# 5) 插件边界测试（禁止 import web.*）
python -m pytest tests/test_plugin_host.py::test_repository_plugins_respect_boundaries -q

# 6) 前端消费者（旧 API 仍被插件调用）
Select-String -Path plugins/*/static/*.js,plugins/*/static/*/*.js,plugins/*/static/*/*/*.js -Pattern '/api/(excel|tdc|aras|tasks|project-status|scheduled-archive|settings|deliverable)'

# 7) 高风险 patch 目标
Select-String -Path tests/*.py -Pattern '_build_tdc_client_from_payload|_shared_domain_session'
```

## 附录 B：本文件数据来源（只读）

| 章节 | 来源 |
|---|---|
| §0、§3 | `tests/golden/routes.json`（166 条，含行号）、`web/*.py` 装饰器扫描、`tests/test_route_contract_behavior.py`（`DOMAIN_WIRINGS:87-253`） |
| §2.1 | `web/app.py`、`web/{archive,crawler,excel,host,project_status,tasks}_boot.py`、`web/{diagnostics,security,ewo_enrichment}.py` 行数统计 |
| §2.2 | `plugins/*/plugin.json`（10 个清单）、`plugins/deliverable_forms/backend.py:9` |
| §2.3 | `tests/test_plugin_host.py:302-327` |
| §2.4 | `tests/test_route_contract_behavior.py:87-253, 534-585` |
| §2.5、§4.8 | `plugins/*/static/**/*.js`、`web/static/**/*.js`、`web/templates/dashboard.html` 的字面 `/api/...` 扫描 |
| §2.6 | `web/app.py:52-146, 148-194`（93/90 + 45/42） |
| §3 | 各 `*_boot.py` 装饰器 + handler 行、`*RouteDeps` 定义行、`app.extensions` 赋值（`web/app.py:427-487`） |
| §4 | `web/security.py:1-130`、`host/updates.py:56,118,261`、`web/host_boot.py:1-60`、`web/diagnostics.py:22,100-109,216-217,235,342-369`、`web/static/host/*.js`、`web/templates/dashboard.html` |
| §5、§6 | CONTRACTS C8（`docs/refactor-v2/CONTRACTS.md:147-159`）、RELEASE_MATRIX §2、`host/registry.py:42,254,273` |
| §7 | 上述全部 + `docs/refactor-v2/DSH_SERVICE_SPLIT_INVENTORY.md` §5.1（patch 陷阱三类）与 §7（已批准裁决记录） |
