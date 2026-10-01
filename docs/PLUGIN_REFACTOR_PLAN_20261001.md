# VSE Toolbox 插件化重构开发计划

> 状态：Active
> 读者：User、Developer、Agent
> 权威来源：本计划；分析论证见 `docs/PLUGIN_REFACTOR_PROPOSAL_20261001.md`；在线版 https://claude.ai/code/artifact/a111a63d-10c5-4001-92fd-fbc047b2c5fc
> 默认读取：插件化重构相关任务必读

2026-10-01 · 用户确认：采用轻量组合方案，前端用 Preact + htm，当日开工。

## 总览

计划共 4 个双周 Sprint（约 8 周），每个 Sprint 结束时都能发版。架构采用轻量组合：CTFd 式的 Flask 插件目录、VS Code 式的声明式清单、calibre 式的 zip 包导入。

| Sprint | 产出 | 放行门槛 |
| --- | --- | --- |
| S1 契约与骨架 | 宿主包 `host/`、Shell、onedir 构建、SOR 试点页 | 新增一个展示页实测 ≤ 45 分钟；旧测试全绿 |
| S2 交付物表单 | 6 个表单合并为一个插件；签名包导入与回滚 | 新增表单只改插件目录；用插件包完成一次真实发布 |
| S3 系统查询 | Aras/TDC 查询插件；`db_manager` 按领域拆分 | `app.js` 行数下降 ≥ 50% |
| S4 收尾 | Excel、自动归档、设置、概览迁移；删除 legacy | 旧 `app.js` 删除；源码文本断言归零 |

推迟到计划外的事项：CLI 复用插件服务层，以及用 tufup 做宿主自动更新。

### 全程规则

- 在 `feature/scheduled-deliverables-overview-excel` 的最新代码上开 `refactor/plugin-host` 分支；每个任务一个 PR。重构前的代码点保存为分支 `checkpoint/pre-plugin-refactor-20261001`。
- 迁移期间的新需求一律写成插件，不再往 `app.js`、`app.py`、`db_manager.py` 里加代码。
- 插件之间不能互相 import，也不能直接写公共表，由一条边界测试拦住。
- 旧测试只在对应页面迁移时改写，其余时间保持不动，充当回归护栏。
- 清单用 `plugin.json`：README 支持 Python 3.9，而标准库 `tomllib` 从 3.11 才有。

## Sprint 1：契约、骨架与试点页

目标：实测"一个页面 = 一个目录"是否成立，并且不改旧 `app.js` 的业务代码。

- [x] **宿主包 `host/`**
  - `host/plugin.py`：定义 `PluginManifest`（id、version、host_api、nav、pages），用 `plugin.json` 加载并校验。
  - `host/context.py`：定义 `HostContext`，包装现有的 `DatabaseManager`、凭据 provider、`ArchiveStore`、任务执行器和脱敏函数，不重写它们。
  - `host/registry.py`：扫描源码目录和 `app_root()/plugins`，用 `importlib` 加载并调用 `register(host)`，把 Blueprint 挂到 `/api/p/<id>/`。
  - `create_app()` 末尾调用注册表，并新增 `GET /api/host/manifest`，返回导航与页面列表。原有 86 个路由保持不动。
- [x] **前端 Shell 与 UI Kit v0**（`web/static/host/`）
  - 随包内置 Preact + htm（`vendor/preact-htm.js`；用 `.js` 并由宿主强制 `text/javascript`，避开 Windows 注册表把扩展名映射成 text/plain）。
  - `shell.js` 读取 manifest 生成导航。`#p/...` 路由由插件页面接管，其余路由交还给旧 `handleHashChange`。`dashboard.html` 只增加一个挂载点和一行 module script。
  - `api.js` 提供信封解析与错误映射；`useResource` 自带请求序号防竞态，以及 loading/error/空态。
  - 组件：`DataTable`、`FilterBar`、`ChartTabs`。图表从旧的 `renderDepartmentDoneChart`（手写 DOM，不依赖图表库）移植。
  - `AnalysisPage`：第一个 Schema 渲染器（筛选 + 图表页签 + 明细表）。
- [ ] **开发工具**
  - `tools/new_plugin.py`：生成标准插件目录。
  - `webui.py --only <id>`：只加载一个插件的沙箱模式。
  - `tests/host/`：注册表测试、契约测试、插件边界测试。
- [ ] **onedir 构建**：`VSE-WebUI.spec` 增加 `COLLECT`，`plugins/` 放在 `_internal/` 外面；同步修改 `build-windows-exe.yml` 的产物打包步骤。
- [ ] **SOR 试点页**（`plugins/deliverable_forms/`，先只含 `tdc_sor`）
  - 新建 `registry.py` 作为表单定义的唯一来源。`deliverable_form_analysis.py` 里的各个字典改为从 registry 推导，保留原变量名，避免影响旧代码。
  - 新页面地址为 `#p/deliverable-forms/tdc_sor`，与旧页面并存。
  - 按同样的 Vibe Coding 流程再新增一个展示页并计时，记录在 `memory/DECISIONS.md`。

## Sprint 2：交付物表单插件与签名包导入

目标：改动最频繁的区域先完成插件化，并把增量发布流程完整跑通一次。

- [ ] **6 个表单迁入 `deliverable_forms`**
  - 把剩下 5 个表单加进 `registry.py`。
  - `app.js` 里的 `DELIVERABLE_FORM_TABS`、`DELIVERABLE_FORM_FILTER_LABELS`、`DELIVERABLE_FORM_CHART_TITLES` 等字典，改为由 `GET /api/p/deliverable-forms/registry` 下发。
  - `/api/deliverable-forms/*` 保留为旧路径别名。
- [ ] **去掉表单白名单的 SQL CHECK**：做最后一次重建表迁移移除 `form_key` 的 `CHECK`，改由 registry 在写入前校验。之后新增表单不再需要重建表。
- [ ] **页面切换与回退**：旧深链 `#overview/deliverables/<id>` 重定向到新页面；设置里提供"使用旧版表单页"开关，保留一个版本周期。
- [ ] **改写相关测试**：把 `test_deliverable_form_ui.py` 和 `test_overview_web.py` 里与表单相关的文本断言，改成 API 契约测试和 Schema 快照测试。
- [ ] **插件包打包与签名**
  - `tools/build_plugin_pkg.py`：生成 `.vsepkg`，内含 `manifest.json`、文件本身和每个文件的 sha256。
  - 用 Ed25519 私钥签名，私钥只存放在外部构建机。
  - 宿主依赖增加 `cryptography`；当前 `requirements.txt` 里没有签名库。
- [ ] **导入、生效与回滚**
  - "设置 → 更新"页面支持选择文件导入。宿主依次验签、检查 `host_api` 兼容性，然后解压到 `updates/staging/`，并提示"重启后生效"。
  - 重启时原子切换 `plugins/active.json`，并保留上一版本。若插件在启动时自检失败，自动切回上一版。
  - 用一次真实的表单改动通过飞书发给同事，走完整个流程。

## Sprint 3：系统查询插件与数据层拆分

目标：迁移第二大块页面，并让各插件拥有自己的数据。

- [ ] **`plugins/system_query/`**：把 Aras 的 EWO、PAA、NCR 进度/明细以及 TDC 查询迁为 L2 页面。`ARAS_MODES` 字典改写为 Schema，约 19 个路由搬入 Blueprint，导出、下载和原位登录复用 Shell 提供的能力。
- [ ] **穿透链接兼容**：从概览跳转到系统查询的旧深链（`#aras-panel?mode=...&from=overview`）继续可用。
- [ ] **`db_manager` 按领域拆分**：拆出 `ProjectStatusRepo`、`ArchiveRepo`、`ExcelTaskRepo`、`FormSnapshotRepo` 等薄层，表名不变、数据不搬。`DatabaseManager` 保留为兼容入口，内部委托给各 repo。
- [ ] **插件迁移版本**：新增 `plugin_schema_versions` 表，把现有的全局 schema v14 冻结为基线，之后的结构变更走各插件自己的 `migrations/`。
- [ ] **改写相关测试**：把 `test_aras_cli_web.py` 等文件中的源码文本断言改成 API 契约测试。

## Sprint 4：剩余页面迁移与删除 legacy

目标：旧前端整体退役。

- [ ] **迁移剩余 4 个页面**：`excel_tasks`（L3，Excel 路由 13 个）、`scheduled_archive`（L2，10 个）、`settings`（5 个，并合并 S2 做的更新页）、`overview`（项目概览与主计划，L3）。顶栏导航全部由 manifest 生成。
- [ ] **删除 legacy**：删掉旧 `app.js`，以及 `style.css` 中的旧规则和 `dashboard.html` 中的旧 section。旧 API 别名只保留 CLI 仍在使用的部分。
- [ ] **清理测试与文档**：源码文本断言归零。更新 `PROJECT_MAP.md` 和 `AGENTS.md`，写明"新功能 = 新插件"的入口。
- [ ] **宿主升级演练**：宿主包先用手工替换 onedir 的方式演练一次，并写进 `PRODUCTION_OPERATION_GUIDE.md`。是否引入 tufup，等这次演练后再决定。

## 风险与应对

| 风险 | 应对 |
| --- | --- |
| S1 的试点实测没有达到 45 分钟 | 停在 S1，先补强 UI Kit 和 Schema 渲染器，再进入 S2 |
| 插件需要宿主没有打包的第三方库 | 必须发一版宿主；插件清单用 `requires` 声明所需库，导入时检查 |
| 过渡期新旧样式互相影响 | 旧样式放进 `@layer legacy`，新组件类名加 `vh-` 前缀 |
| 签名私钥泄露或丢失 | 私钥只存放在构建机并离线备份；宿主内置两把公钥（主钥 + 备用），便于轮换 |
| 重构期间业务需求插队 | 新需求直接写成插件，计入当前 Sprint，顺延而不是绕过新架构 |
