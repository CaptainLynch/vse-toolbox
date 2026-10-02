# AGY《HCI/UX 优化全景方案白皮书》架构审计（2026-09-19）

> 审计对象：`hci_optimization_blueprint.md`（AGY antigravity brain 产出，面向 `webui.py` / `web/app.py` / `web/static/app.js` / `web/templates/dashboard.html`）。
> 审计基线：工作区 2026-09-18 审计闭环后状态，全量回归 2,177 passed / 3 skipped。
> 结论性质：架构审计，不含代码改动。仓库与测试为事实权威，蓝图仅为建议。

## 一、总体结论

蓝图痛点诊断与代码事实核对 **5/5 属实**（个别机理表述有偏差，见 §2），四大支柱方向正确，技术路线与本项目"零服务依赖、单文件 EXE、本机回环安全边界"的架构兼容。**有条件批准**：批准实施前需修订三处架构决策——

1. **任务中心必须明确与既有 Excel 任务基础设施的关系**（复用/统一，而非平行新建），并统一 UI 承载两类任务；
2. **异步化端点需按副作用分类并冻结重试语义**（EWO 官方导出类任务禁止盲目重试，复用 `core/ewo_export_jobs.py` 所有权模型）；
3. **实施排期需修正**：Excel 入口收纳依赖任务抽屉先落地，且 Gantt 未给测试/文档改造留任何工作量。

---

## 二、现状诊断核实（蓝图 vs 代码事实）

| 痛点 | 核实结论 | 关键证据 |
| --- | --- | --- |
| P1 入口割裂 | **属实**（细节修正） | `dashboard.html:22-29` 顶栏 6 Tab 无 TDC；TDC 查询经 `TDC_ENDPOINTS`（`app.js:143-160`）动态渲染在 `aras-panel` 内、由交付物条目驱动（`app.js:9132, 9279, 9428`）；认证徽章 Aras/TDC 并列 `dashboard.html:34-43`。注意：TDC 嵌套形态是"交付物条目驱动"而非纯"树状三级"，重构必须保留"从交付物直达 TDC 报表"的现有能力。 |
| P2 概览无闭环 | **属实，但低估现状** | 已存在 `deliverable-preview-context` / `aras-preview-context` 交付物→查询上下文带入机制（`app.js:8683-8816, 9342-9545, 12454`）。深链应在此雏形上泛化，而非新建平行机制；缺的只是"返回原位置"与全局化。 |
| P3 长任务黑盒 | **属实；机理表述不准** | `crawl-all` 在请求线程内同步跑完整多页循环（`web/app.py:4252-4285` 调 `crawl_paa_report_all`；EWo/PAA 导出 `_EXPORT_PAGE_SIZE=2000` 固定，`web/app.py:180, 4371, 4395`；TDC `crawl-all/export` `web/app.py:4442-4460+`）。Flask 3.1.3 开发服务器自 Werkzeug 2.1 起 `threaded=True` 默认开启，**页面与其他请求并不会被阻塞**；真实痛点是：无进度、无取消、刷新后响应永久丢失（服务器线程继续跑完但结果无处交付）、失败原因回传丢失。 |
| P4 表格单薄 | **属实** | `renderRows`（`app.js:8558+`）纯静态渲染，无表头排序/无快筛/无分页；但"常用列"概念已存在：`config.preferredColumns`（`app.js:42`）、`orderedColumns` 12 列截断（`app.js:8546-8555`）、`defaultVisibleCount`；列偏好 localStorage 已有先例（`app.js:176, 12357`）。列显隐应定义为对既有机制的改造而非新造。 |
| P5 桌面断层 | **属实** | `webui.py:44-46` 仅打印 URL；全仓库无任何 `webbrowser` 调用。 |

---

## 三、四大支柱逐条评审

### 支柱一：信息架构与穿透 —— 可行，三个前置条件

纯前端重组（`dashboard.html` 面板 + `app.js` 锚点切换，`data-panel-link` hash 已是事实路由），不触碰 `core/`/`services/`，符合边界纪律。

1. **UI 测试断言漂移是确定性成本**。`tests/test_overview_web.py`、`test_deliverable_form_ui.py`、`test_overview_external_deliverables_ui.py`、`test_scheduled_archive_admin_ui.py` 等大量断言绑定现有 nav 结构与 panel id；2026-09-18 刚修过一轮同类漂移（9 用例）。导航重构必须同批更新测试，Gantt 未列此项。
2. **Excel 入口收纳存在顺序依赖**。Excel 任务面板是当前唯一具备"任务记录 + 工件下载"UI 的区域；若按 Gantt 在 Phase 2 收纳、而任务抽屉在 Phase 3 才落地，中间版本出现功能回退。修订：任务抽屉先落地统一承载，或 Phase 2 不动 Excel 入口。
3. **深链契约建议沿用 hash 路由**：`#aras-panel?mode=ewo&no=...` 类形式，零依赖、可书签化；返回条用 `history.back()` + 位置快照即可，不需要新路由库。

### 支柱二：任务中心 —— 最大架构决策点，需重新定义边界

**重叠风险（P0）**：项目已有一套完整、经审计的任务持久化范式——`core/excel_tasks.py`（任务合同/幂等/lease/状态机：`ExcelInvalidStateError`、`ExcelLeaseLostError`，明确"不存凭据与 token"）+ `services/excel_task_admin.py` + 13 条 `/api/excel-tasks*` 路由 + 前端任务记录 UI。蓝图另起"SQLite 任务队列表"，若不界定关系，将出现两套任务语义、两套状态机、两个 UI 概念。**建议**：以 `excel_tasks` 为蓝本提取共享 contracts（或直接泛化其 repository），任务抽屉统一承载 Excel 任务与抓取/导出任务——这同时解决支柱一的 Excel 收纳问题。

**并发范式直接复用现成模式**：`services/scheduled_archive_runner.py:619-644` 已有 daemon 线程 + `stop_event` + SQLite lease 的运行模型，抓取任务直接套用。**明确否决 Celery/RQ/Redis 等外部队列**：与单文件 EXE、零服务依赖的交付形态冲突（蓝图未提，审计予以显式封死）。

**端点异步化需逐个分类（蓝图遗漏）**：

- 纯读类（EWO/PAA/NCR query、crawl-all、TDC query/crawl-all）：可直接异步化，收益最大；
- 带外部副作用类：`/api/aras/ewo/export` 走 `EWOExportTransport` 官方导出，且 `core/ewo_export_jobs.py` 提供 durable ownership；业务红线"EWO 生成结果未知禁止直接重发"（`memory/CURRENT_STATE.md`）。蓝图"失败任务 →【重试】按钮"对这类任务是**危险默认值**：任务层重试语义必须按任务类型冻结——导出类只能复用既有 job 所有权模型做幂等续传，不允许盲目重发；其余读类任务可自由重试。

**进度推送选型（蓝图缺失）**：推荐 **1-2s 轮询任务表** 作为契约默认（实现最简、断线自愈、与 EXE 打包无冲突）；SSE 可作后续增强（Flask 流式响应即可，无需新依赖）；WebSocket 明确不需要。

**任务参数快照安全**：快照含 base_url/headers/会话 Cookie。必须对齐 `core/excel_tasks.py`"不存凭据与 token"红线与 `redact_sensitive_text` 脱敏——**禁止把会话头写入任务表**，蓝图只承诺了"失败原因脱敏"，不够。

**生命周期措辞必须收窄**：蓝图称"意外关闭标签页、刷新或浏览器崩溃，后台任务依然不受影响继续运行"——这只在浏览器生命周期内成立。daemon 线程随进程退出被硬杀：Ctrl+C 或用户关闭控制台窗口即终止运行中任务。需要的契约是：(a) 退出前对运行中任务给出提示（或接受中断）；(b) 重启后启动自检，把遗留 `running` 态标记为 `interrupted`（fail-closed，不允许僵尸运行态）。SQLite 保证的是"状态与结果可见"，不是"任务跨进程存活"。

**并发上限**：多个抓取任务共用 `core/domain_identity.py` 会话与凭据库，对同一数据源并发全量抓取可能互踩。建议默认每数据源并发 1，全局限 2-3。

### 支柱三：数据网格 —— 收益/成本比最高，直接批准

纯 `renderRows` 前端改造，无新依赖：

- 排序/快筛/分页全在客户端内存进行，与蓝图"不产生 SQL 注入暴露面"判断一致，正确；分页是正确选择（500-2000 行 × 分页渲染，避免引入虚拟滚动复杂度）。
- **列显隐不得突破两条既有边界**：`SENSITIVE_COLUMNS` 过滤（`app.js:8550`）与后端 `table_payload`（`core/report_contracts.py`）已裁剪的字段集——服务端给什么前端才能显什么，"全量列"只是展示开关，不是数据获取开关。
- **剪贴板需降级路径**：`navigator.clipboard` 仅在 secure context 可用（HTTPS 或 `http://localhost`，MDN）。默认 `127.0.0.1` 访问没问题；但 `--host 0.0.0.0` 局域网经 `http://<ip>` 访问时 API 整体不可用，需 `document.execCommand('copy')` 降级，否则变成"时灵时不灵"的支持负担。
- **不建议引入第三方 grid 库**：`VSE-WebUI.spec:64` 已打包 `web/static`，引入可行但不必要——项目全部前端为 vanilla JS（`node --check` 验证惯例），一个增强 `renderRows` 的自研层即可，避免框架化。

### 支柱四：桌面集成 —— 可行，两个实现细节

1. **打开浏览器的时序**：`app.run` 是阻塞调用（`webui.py:46`），必须在服务真正 listen 后再 `webbrowser.open_new_tab`——先起一个 readiness 探测线程（轮询端口连通）再进入 `app.run`，否则偶发"连接被拒"页。自动打开的目标固定 `http://127.0.0.1:<port>`，与 `--host 0.0.0.0` 语义解耦；既有 `_enforce_local_web_access` 本机回环防护（`web/app.py:449, 2649`）不受影响。
2. **标准库即可**：`webbrowser` 在 PyInstaller 冻结环境可用，无打包影响。标题角标/Toast 为纯前端（`document.title` 轮询），无架构风险。

---

## 四、蓝图遗漏的横切关注点

1. **Schema 迁移纪律**：任务表进 `core/db_manager.py` 必须走既有迁移机制；项目红线"旧 EXE 不得打开新 schema"意味着新版 WebUI 与旧版 ExcelWorker 混部场景下，任务表需双向兼容或按版本隔离。
2. **测试影响面与工作量**：2,177 全绿是基线；导航重构 + 网格改造集中冲击 `tests/*web*`、`tests/*ui*`。Gantt 给测试留了 0 天，必须补上（建议每 Phase 预留 ≥1 天测试与回归）。
3. **文档与地图随动**：`docs/USER_GUIDE_STANDALONE_EXE.md`、`docs/PRODUCTION_OPERATION_GUIDE.md`、`docs/API_ENDPOINTS.md`（生成物，新增路由必须重生成）、`PROJECT_MAP.md`（`tools/generate_project_map.py --check` 纪律）、`core/version.py` 与 `VSE_TOOLBOX_VERSION` 元数据升级。
4. **无新依赖前提下的打包**：推荐路线（轮询 + vanilla 网格 + 标准库 webbrowser）不改 `VSE-WebUI.spec`；若采纳 SSE 也无需新包。

## 五、风险分级汇总

| 级别 | 发现 | 处置建议 |
| --- | --- | --- |
| P0 | 任务中心与 `excel_tasks` 语义重复建设风险 | 以 `excel_tasks` 为蓝本统一 contracts，任务抽屉统一承载两类任务 |
| P0 | EWO 导出类任务"重试"按钮违反"结果未知禁止重发"红线 | 按任务类型冻结重试语义；导出类仅幂等续传，复用 `ewo_export_jobs` 所有权 |
| P1 | Excel 入口收纳（Phase 2）早于任务抽屉（Phase 3）造成中间态功能回退 | 调整顺序：抽屉先行或 Phase 2 不动 Excel |
| P1 | "任务不受 EXE 退出影响"表述过强；daemon 线程随进程硬杀 | 收窄措辞；新增重启自检标 `interrupted` + 退出提示契约 |
| P1 | Gantt 无测试/文档工作量；UI 断言漂移确定性发生 | 每 Phase 增加测试与文档条目 |
| P2 | 局域网 HTTP 下剪贴板 API 不可用 | `execCommand('copy')` 降级 |
| P2 | 任务参数快照可能夹带会话头/凭据 | 快照写入前强制脱敏，禁存会话头 |
| P2 | 同源并发抓取互踩会话/lease | 每数据源并发 1，全局限 2-3 |

## 六、审计结论

蓝图痛点全部属实、方向正确、与项目架构兼容，属高质量的 UX 规划；但它是"UX 视角"的产物，对既有任务基础设施（`excel_tasks`、`ewo_export_jobs`、scheduled archive runner 线程模型）、业务重试红线、schema 迁移纪律和测试/文档义务覆盖不足。按 §五 的 P0/P1 修订后即可进入实施排期；建议实施时以本文件为约束清单逐项核对。

## 附：外部依据

- Flask 开发服务器线程模型：[Flask 2.3 changelog（dev server uses threads by default）](https://flaskx.readthedocs.io)、[Flask Quickstart](https://flask.palletsprojects.com)
- 剪贴板 secure context：[MDN — Clipboard: writeText()](https://developer.mozilla.org/en-US/docs/Web/API/Clipboard/writeText)
