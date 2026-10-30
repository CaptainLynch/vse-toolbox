# 给 GPT Astra 的规划提示词：VSE Toolbox v2 下一阶段总体规划（2026-10-31）

> 用法：整段粘贴给 Astra（建议 `astra-high`：涉及多模块公共契约、凭据、迁移和拆包）。
> Astra 只出规划；执行由 ZCode 的 worker 按契约逐批完成，lead 负责集成与验收。
> 本文不含任何密钥、账号、Cookie 或内网地址。

---

## 0. 你的任务

你是 VSE Toolbox v2 的规划顾问。请根据下面的事实，给出**下一阶段的完整执行规划**，交给 ZCode 的
worker 批量执行。这次的执行预算很大（约 5 亿 token），所以：

- **规模要做大**：覆盖下面列出的全部工作流（W0–W20），不要只挑两三项。按「波次」排列，每个波次内
  放尽可能多的、**互不改同一文件**的任务并行执行。
- **但不要用 token 换正确性**：高风险的部分（凭据、迁移、拆包、并发、回滚）由 lead 负责设计和定契约，
  worker 只做契约已经定好的实现和测试。

请按 §6 的格式输出。

## 1. 产品与用户

- VSE Toolbox 是汽车研发项目的跟踪工具，给**不会写代码的工程师**用，目标是「傻瓜式」操作。
- 它从 Aras、TDC、帆软等公司内网系统同步交付物进度，用来生成签署日报、TIR 简表和各类导出，
  还处理 Excel 文件（通过 COM，因为有 DLP 限制，不能用 pandas/openpyxl）。
- 当前分支是 `refactor/ux-v2`，app 版本已到测试包 2.3.4（`.vsepkg` 增量包，测试密钥签名）。

## 2. 硬约束（不可违反）

1. 生产电脑**没有管理员权限、没有 Python**，是普通办公电脑；不得要求改公司安全设置。
2. 升级通过 `.vsepkg` 增量包，由用户经 QQ/飞书传文件安装；失败要自动回滚。宿主变更才发整包。
3. 新功能写成插件：`plugins/<id>/`，用 `register(host)` 注册，后端只能通过 `host.context` 访问服务；
   **不得往 `web/app.py` 加路由体，不得往 `core/db_manager.py` 加代码**；插件之间不得互相 import，也不得 import `web.*`。
   插件的表用 `host.table_prefix` 加前缀，迁移只能是增量的 `host.migrate([(version, fn)])`。
4. 凭据只放在 DPAPI 凭据库；日志、报告、交接材料里不得出现密钥、Cookie、token。
   `dist/v2-test/keys` 是**测试专用**签名密钥，不得提交，也不得外发。
5. 飞书功能已取消。「子系统开发策略」交付物（VPI-T2-D1）已取消：标为 retired 隐藏，数据保留。
6. 前端用 Preact + htm，不经过构建，直接是 ES Module。界面文字要通俗，禁止出现代码路径、JSON、Base URL、Worker、快照、取证等词（U4）。
7. 默认禁止读取的目录（见 `AGENTS.md`）：`build/`、`dist/`、`.runtime/`、`error data/`、原始 HAR/XML/XLSX 等。所有搜索都要带明确的范围。
8. 不 push，不合并到 main，不自动合并 worker 的改动；lead 看过 diff 和检查结果后再集成。

## 3. 当前事实（以仓库为准；本节是索引，不是证明）

**代码规模**

| 文件 | 规模 |
|---|---|
| `web/app.py` | 7297 行，94 个路由 |
| `core/db_manager.py` | 1105 行 |
| `services/deliverable_form_analysis.py` | 120 KB |
| `services/tdc_crawler.py` | 70 KB |
| `services/project_status_updates.py` | 64 KB |
| `services/project_status_deliverable_analysis.py` | 59 KB |
| `services/aras_crawler.py` | 56 KB |
| `services/project_status_discovery.py` | 55 KB |

`web/app.py` 的路由按领域统计：

| 领域 | 路由数 |
|---|---|
| `/api/project-status` | 27 |
| `/api/tdc` | 11 |
| `/api/scheduled-archive` | 10 |
| `/api/aras` | 9 |
| `/api/tasks` | 6 |
| `/api/settings`、`/api/host`、`/api/excel-tasks` | 各 5 |
| `/api/excel-artifacts` | 4 |
| `/api/deliverable-forms`、`/api/excel-worker` | 各 3 |
| 其它 | 少量 |

**插件与测试**

- 已有插件：`deliverables`、`deliverable_forms`、`excel_tasks`、`project_overview`、`scheduled_archive`、
  `settings`、`sign_daily`、`system_query`、`tir_report`、`workbench`。
- 测试：175 个测试文件；全量回归最近一次为 3441 passed / 6 skipped。
- 浏览器类测试因本机没有 playwright 而跳过。

**已完成**

- 启动器分层（`vse_boot`）：托盘、双击安装、增量更新和回滚。
- 新导航：今天 / 项目 / 报告 / 工具 / 设置，带专家模式。
- 首页「今天」；项目页。
- 多项目：一个项目一个数据文件夹，切换 = 保存选择 + 重启。
- 一键开启自动同步；交付物详情简洁视图。

**已修复，但还在未提交的工作区里（W0 要先处理）**

- 同步三问题：
  - EWO 同步时间不前进（幂等 skipped 不刷新 `last_success_at`）；
  - 明细进度恒为 0%（新增 `effectiveProgress`）；
  - 数模稳定性采样口径错误。
- 签署日报：发送门禁和「幻影项目」修复。
- 测试包 2.3.3 / 2.3.4 已经打出，**都没有在真机上验证过**。

**未完成或缺口**（需求编号来自 `docs/refactor-v2/REQUIREMENTS.md`，共 80 条）

- U1 首次使用向导只做了「欢迎 → 登录 → 完成」。
- B4 会话过期后自动处理是**用户反馈的第 1 痛点**（「每次都要重新登录」）。
- F1 报告页内一键生成、F3 日报定时生成都没做。
- D4 调度要求每天 09:00、16:00 两次，并且开机补跑。
- U4 术语表没有自动化检查；U6/U7/U8 只覆盖了新的工作台页面，旧页面还是原样。
- F8 时间显示只部分改成了北京时间。
- U9 托盘通知没做；A8 开机自启没做。
- M1 第 3 片：token cookie、pywebview 窗口、L0 原生启动器。
- M4 拆包：`web/app.py` 还有 94 个路由。
- M5 下线：
  - `requirements.txt` 里还有 selenium、rich、imapclient；
  - 终端 CLI、TDC Probe、交付物工作台、飞书相关代码都还在。
- 多项目：
  - 只有当前项目会在后台同步；
  - 界面上不能编辑项目；
  - 一键开启页改的科室不会回写到项目。
- 48 个车型代码的清单用户还没给。在拿到之前，车型下拉做成「可配置清单 + 文本输入兜底」。
- 一键开启对真实 TDC/Aras 的取证从未在真机验证过。

## 4. 工作流清单（全部都要进入规划）

请为每个工作流给出：目标、涉及的需求编号、风险级别、由 lead 还是 worker 负责、拆成哪些任务、依赖关系。

- **W0 收口**（lead）
  - 复核并分批提交工作区里的未提交修复（同步三问题、签署日报）。
  - 不提交无关的未跟踪文件（`docs/ADVISOR_*`、`pelican-*.html`、`.dsh/`、`dsh-remote-bridge.mjs` 等）。
  - 建立本阶段的基线：测试数、`generate_project_map.py --check`、包版本。
- **W1 真机验证工具包**
  - 一个专家模式下的「自检」页：逐项检查登录、各连接器取证、调度、Excel COM、更新通道。
    结果做成一份**已脱敏**的诊断包，可以导出（J4）。
  - 再写一份给用户照着做的核对清单，减少来回截图。
- **W2 会话过期自动处理（B4 / B3 / B5）**（高风险：凭据）
  - 任务进行中会话过期时，用凭据库静默重新登录、重试一次；失败则给出 ErrorCard，提供原位登录。
  - 「清除会话与凭据」。
  - lead 定状态机和脱敏规则，worker 实现并写测试。
- **W3 会话状态合一（B2）**
  - 顶栏两个徽章合并为「已连接 ✓ / 需要重新登录」，点击原位登录。
- **W4 首次使用向导补全（U1）**
  - 欢迎 → 登录 → 新建项目（车型/科室）→ 选择要跟踪的交付物 → 是否开机自启 → 完成并开始第一次同步。
  - 复用 `projects.js` 和 `enable-flow.js`。
- **W5 项目管理补全（C1 / C3）**
  - 编辑当前项目；归档项目（**不做物理删除**）。
  - 一键开启页的科室回写到项目。
  - 可配置的车型清单。
  - 「多项目后台同步」只出设计方案和决策点，不实现。它涉及启动器和调度器，属于架构决策。
- **W6 调度与关注（D4 / D6 / D9）**
  - 每天固定时刻同步 + 开机补跑 + 可增删时刻 + 暂停。
  - 同步记录简化。
  - 关注清单。
- **W7 报告中心（F1 / F3 / F4 / F5 / F6 / F7）**
  - 报告页内一键生成；日报定时生成。
  - 导出入口统一到交付物详情；TIR 同日复用。
- **W8 体验层统一（U4 / U5 / U6 / U7 / U8）**
  - 把 ErrorCard、状态色、骨架屏、FixIt 推广到所有旧页面。
  - 术语表做成门禁：扫描 `plugins/*/static` 中可见文字里的禁用词，写成 pytest。
- **W9 表单分析单一入口（E1 / E2 / E3）**
  - 只保留交付物详情里的入口。
  - 简洁视图的表格补上排序、复制单号、列显隐。
  - 检查列 `key` 是否存在，不存在就改用 `c.index`。
- **W10 时间口径（F8 / C5）**：全站审计，统一显示北京时间，逾期只有一个口径。
- **W11 任务中心与通知（I1 / I2 / U9）**
  - 提交任务后原位显示进度，完成后有托盘通知。
  - 产物 7 天清理。
- **W12 Excel（H1–H5）**
  - Excel 环境自检（H4）。
  - Worker 启停对用户不可见，自动管理。
  - 白名单根目录和路径安全复核。
- **W13 M4 拆包**（高风险：公共契约）
  - 把 `web/app.py` 的路由按领域迁到插件，**一个领域一个批次**。
  - 先建立路由契约快照测试（路径、方法、状态码、响应信封），再迁移，迁完删掉旧路由，只留兼容重定向。
  - 顺序建议从小到大：settings / host / version → tasks → excel → scheduled-archive → aras / tdc → project-status（最大，最后做）。
  - 这些批次都会改 `web/app.py`，因此**只能串行**。
- **W14 大服务拆分**
  - `deliverable_form_analysis.py`（120 KB）等按职责拆成子模块。
  - 先补黄金测试锁住行为，对外 API 不变。
  - 可以和 W13 并行，前提是两边不改同一文件。
- **W15 M5 下线（K1–K6）**
  - 移除 CLI 菜单、TDC Probe 发布产物、交付物工作台、飞书代码。
  - 从运行时依赖中去掉 selenium / rich / imapclient。
  - 删除对应的 spec 和文档。
  - `feishu_tasks` 表保留，不删。
- **W16 M1 第 3 片（A2 / A3 / A4 / A8）**
  - 开机自启开关（写当前用户的启动项，不需要管理员）。
  - pywebview 窗口，WebView2 不可用时依次退到 Edge `--app`、默认浏览器。
  - 单实例唤起；端口冲突零干预；token cookie。
  - L0 原生启动器只做选型和 Spike 报告。
- **W17 测试基础设施**
  - 让浏览器测试能在本机跑起来（离线可装的方案）。
  - 前端 node vm 夹具覆盖所有插件页面。
  - 真实 exe 的 e2e 扩展到向导、多项目、一键开启。
- **W18 性能**
  - 启动时间、首页首屏、`web/app.py` 的导入耗时。
  - SQLite 索引和慢查询。
  - 大表分页。
- **W19 用户文档**
  - 给非程序员看的中文使用手册（带截图）。
  - 更新日志对用户可见（A7）。
  - 更新 `docs/PRODUCTION_OPERATION_GUIDE.md`。
- **W20 可用性验收**
  - 把「3 名新用户在无管理员权限的电脑上，10 分钟内从解压走到第一份签署日报」写成可执行的脚本和记录表。

## 5. 已知坑与已否决的路线（不要重走）

- 多项目方案是「一个项目一个数据文件夹」，**不给各表加 `project_id` 重新建键**。
  `ARCHITECTURE.md` §7 里的 `projects_v2` 方案已被取代。
- 不要把手工字段 `progress` 换成派生值。编辑表单会用 `progress` 预填，换掉会把派生值固化成手工值。
  派生值走 `effectiveProgress`。
- 不要改 sync-now 的 HTTP 200 / `ok` 语义（可能有未知的调用方）。
- 稳定性采样必须和基线**同一收窄口径**；失败的采样不能顶掉基线。
- 签署日报对孤儿项目只允许「可取消」，**绝不自动删除**：范围 key 里包含项目，自动剪枝会让邮件发错人。
- EWO 记录集绑定禁止映射负责人和计划完成日期，这是设计约束，不是缺陷。
- Excel 只能走 win32com/COM，不能用 pandas/openpyxl/python-pptx（DLP 限制）。
- 计划任务脚本（K5）已由托盘内的调度器替代，不要再引入 Windows 计划任务。
- worker 没有 shell，检查命令由 supervisor 在外部执行；worker 不得再委派任务，也不得启动 Codex / AGY / DeepSeek。

## 6. 输出格式（必须遵守）

1. **总览**
   - 波次图：Wave 0..N，每个波次列出可并行的任务和串行链。
   - 关键路径。
   - 预计 token 分配（总预算约 5 亿，给出每个工作流的占比）。
2. **lead 保留项**：哪些设计和契约必须由 lead 先定，每项写出要定下的接口或数据契约草案（字段、状态机、错误码）。
3. **worker 任务契约**：每个任务一条 JSON，字段如下：
   ```json
   {
     "task_id": "W13-03-tasks-routes",
     "objective": "...",
     "owned_scope": ["plugins/tasks/**", "tests/test_tasks_routes.py"],
     "read_only_scope": ["web/app.py"],
     "constraints": ["..."],
     "acceptance_criteria": ["..."],
     "risk_class": "low|medium|high",
     "depends_on": ["W13-01-route-snapshot"],
     "verification_commands": [["python", "-m", "pytest", "tests/test_tasks_routes.py", "-q"]],
     "wave": 2
   }
   ```
   - 同一波次内的任务，`owned_scope` 两两不得重叠。
   - 改 `web/app.py` 的任务一律串行。
   - 相关的实现和测试放进同一个任务，不要按函数拆。
4. **每个波次的门禁**：
   - 全量 `python -m pytest tests -q`；
   - `python tools/generate_project_map.py --check`；
   - 前端夹具；
   - 打一个测试包，验签。
5. **回滚方案**：每个高风险任务一条。
6. **需要用户拍板的问题**：最多 8 个，每个给出推荐选项。至少包括：
   - 多项目后台同步；
   - 代码签名证书；
   - 是否默认开机自启；
   - 发版节奏；
   - 48 个车型代码清单。
7. **明确不做的事**，并写明理由。

## 7. 参考文件（按需读取，不要整库扫描）

- `AGENTS.md`、`PROJECT_MAP.md`
- `memory/CURRENT_STATE.md` 的前两节
- `docs/refactor-v2/REQUIREMENTS.md`、`docs/refactor-v2/ARCHITECTURE.md`
- `docs/PLAN_20261028_V2_SYNC_DISPLAY_FIX.md`
- `docs/ZCODE_WORKER_RUNTIME.md`、`docs/PRODUCTION_OPERATION_GUIDE.md` §7
- `vse_boot/`、`plugins/workbench/`、`plugins/project_overview/static/deliverable/`、`host/`
