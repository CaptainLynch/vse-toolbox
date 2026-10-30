# VSE Toolbox v2 执行计划与任务契约（2026-10-31，lead 冻结）

> 执行路线：ZCode。当前交互模型 = 唯一 lead；有界实现/测试/文档派给 Gemini 3.8 Flash worker。
> 契约文档：[CONTRACTS.md](CONTRACTS.md)（公共契约）· [REQ_TRACEABILITY.md](REQ_TRACEABILITY.md)（72 需求追踪）·
> [RELEASE_MATRIX.md](RELEASE_MATRIX.md)（发布矩阵）· [ADR-0001](ADR-0001-multi-project-background-sync.md)（多项目同步只设计）。
> 需求源 [REQUIREMENTS.md](REQUIREMENTS.md)：**72 个编号**（"80 条"为误计，见追踪矩阵对账）。

## 0. 运行时派发规则（契约字段 → 实际 worker 适配）

- `task_id` → `TASK-<原编号>`（如 `TASK-W8-01`）。
- `owned_scope` → worker 契约 `scope`；`read_only_scope` → `read_scope`。
- `task_kind` ∈ {mechanical, test-only, ui, ordinary-implementation}（supervisor 白名单）；
  `model_slot` = `flash`（gemini-3.8-flash-high，pro 槽已映射为同款）。
- `risk_class`：worker 只接受 `low`。`high`（auth/credential/migration/public-contract/concurrency/
  destructive 关键词）一律 lead 保留——这些任务在本文件标 `owner: lead`，worker 最多承担其中
  明确划出的 test-only 子块（单独发 test-only 契约，不得触碰高危源文件）。
- verification_commands 由 supervisor 在集成区外部执行；worker 不得声称自己跑过。
- 同波次 `owned_scope` 两两不重叠（含 glob 目录包含与 Windows 大小写等价）；
  read_only_scope 只引用**已集成基线**的内容。
- 每任务最多两轮针对性修复；同因失败仍在 → 交回 lead。
- provider/配额/模型/权限错误 → 停该路线，不换供应商。

## 1. 波次总览与关键路径

```
W0（lead 串行）→ W1(7 并行) → W2(4 并行) → W3(5 并行) → W4(7 并行) → W5(6 并行)
→ W6(4 并行) → W7(3 并行) → W8(3 并行) → W9(2 并行) → W10(串行) → W11(3 并行) → W12(串行)
```

- **关键路径** = W13 路由迁移链（W13-01 → 02 → … → 09，全部独占 `web/app.py`，跨 W2–W9 串行）
  + W16-03（Wave 10 独占 web/app.py 与启动安全入口）。
- 与 W13 同波的其他任务不得拥有 `web/app.py`。
- W13-09（project-status 最后迁移 + web/app.py 装配化）完成前，任何任务不得宣称"路由拆包完成"。

## 2. 任务契约

> 格式：`task_id | owner | risk | wave | owned_scope | read_only_scope | depends_on | 验收要点`。
> 完整约束在派发时按 §0 适配为 JSON。标注 ★ 的验收命令由 supervisor 执行。

### Wave 0（lead，串行）

**W0-01 · lead · 基线**：复核并分批提交同步三问题与日报修复；建立测试/地图/包基线。
已完成：提交 `b9f309b`、`7f4617f`、`d7ba018`；本轮全量 `python -m pytest tests -q` →
3441 passed / 6 skipped（414.66s，`.runtime/w0_full_pytest.log`）；
`generate_project_map.py --check` → verified。无关未跟踪文件（`.dsh/`、`pelican-*.html`、
`dsh-remote-bridge.mjs`、`VSE-WebUI-compact.spec`、`.claude/launch.json`、`docs/dsh-remote-control/`）保留未提交。

**W0-02 · lead · 契约冻结**：本文件 + CONTRACTS + REQ_TRACEABILITY + RELEASE_MATRIX + ADR-0001。
多项目后台同步只设计不实现（ADR-0001）。

### Wave 1（7 项可并行）

**W17-01** · worker(ordinary-implementation) · low · W1
- owned: `tools/wave_gate.py`，`tests/browser/`（新目录），`tests/p1d_frontend_fixture.py`
- read: `plugins/*/static/**`，`web/static/host/**`
- depends: W0-02
- 目标：① 离线可安装的浏览器测试通道（优先本机已有 Edge/WebView2 的 CDP 方案；装不了则浏览器
  用例明确标 `skip` 理由并留安装说明——**最终发布门禁不得静默 skip**，W17-03 必须真机跑）；
  ② Node 页面夹具覆盖全部插件页面（复用 p1d fixture 模式，逐插件至少冒烟渲染）；③ 统一波次门禁脚本
  `tools/wave_gate.py`：聚焦测试→全量→地图→Node 夹具→术语门禁→打包验签，一键执行输出结构化结果。
- 验收：★`python tools/wave_gate.py --skip-package` 全绿；新增夹具对每个插件目录存在。

**W13-01** · worker(ordinary-implementation) · low · W1
- owned: `tests/test_route_contract_snapshot.py`，`tests/golden/routes_*.json`（新目录）
- read: `web/app.py`
- depends: W0-02
- 目标：从 `web/app.py` 自动抓取全部路由（路径/方法/状态码族/信封形状/错误类型码/下载头）生成
  golden 快照；对现有路由全绿锁定。之后每个 W13-0x 迁移批次以"快照零差异"为验收。
- 验收：★`python -m pytest tests/test_route_contract_snapshot.py -q` 通过；golden 覆盖 ≥90 条路由。

**W8-01** · worker(ui) · low · W1
- owned: `web/static/host/ui-kit.js`（新），`web/static/host/glossary.js`（新），
  `tests/test_ui_kit_terms.py`（新），`tests/test_glossary_terms.py`（新）
- read: `web/static/host/kit.js`，`plugins/workbench/static/**`
- depends: W0-02
- 目标：UI Kit（ErrorCard：发生了什么/你需要做什么/[一键处理]/[导出诊断包]；FixIt 按钮；状态色
  绿黄红灰 token；骨架屏组件）；glossary 词表 + 术语门禁 pytest（扫描 `plugins/*/static/*.js` 字符串
  字面量，禁词：JSON、Base URL、Worker、快照、取证、代码路径等；白名单机制留专家模式）。
- 验收：★`python -m pytest tests/test_glossary_terms.py -q`（现存页面按基线白名单全绿，白名单只减不增）。

**W10-01** · worker(ordinary-implementation) · low · W1
- owned: `core/time_rules.py`（新），`tests/test_time_rules.py`（新）
- read: `core/project_status_contracts.py`，`services/deliverable_form_analysis.py`
- depends: W0-02
- 目标：契约 C9 的唯一内核实现：aware-UTC 工具、纯日期不位移、无时区历史字段按来源标注、
  单一 `overdue_state()`（输入：计划完成日期/完成状态/今天（可注入），输出：ok/due_soon/overdue + 天数）。
  本任务**不改任何调用方**（接入在 W10-02）。
- 验收：★`python -m pytest tests/test_time_rules.py -q`；与现口径对拍（同输入同输出的差异表附在任务报告）。

**W18-01** · worker(test-only) · low · W1
- owned: `tools/perf_baseline.py`（新），`docs/refactor-v2/PERF_BASELINE_20261031.md`（新）
- read: `web/app.py`，`core/`，`services/`
- depends: W0-02
- 目标：无副作用基准：`create_app` 导入/构建耗时、首页首屏路由响应、项目页聚合接口、
  大表（>5k 行快照）分页查询；合成数据；输出到 `docs/refactor-v2/PERF_BASELINE_20261031.md`
  （数字 + 环境），不优化。
- 验收：★`python tools/perf_baseline.py --quick` 可重复执行并输出 JSON/MD。

**W19-01** · worker(document) → task_kind=mechanical · low · W1
- owned: `docs/manual/真机核对清单.md`（新）
- depends: W0-02
- 目标：非程序员真机核对清单：登录、同步、日报、更新安装/回退、诊断包导出，每项"现象/期望/
  截图要点"；无内部术语。
- 验收：lead 评审通过；术语门禁扫描通过。

**W20-01** · worker(mechanical) · low · W1
- owned: `docs/manual/新用户验收脚本.md`，`docs/manual/验收记录表.md`（新）
- depends: W0-02
- 目标：把"3 名新用户、无管理员、无 Python、10 分钟内 解压→登录→建项目→开启同步→首份有效日报"
  写成逐步脚本（含计时点与失败中止判据）+ 记录表模板（每人每步骤用时/卡点/是否完成）。
- 验收：lead 评审通过；与 U1 向导计划步骤一致。

### Wave 2（4 项并行；W13-02 独占 web/app.py）

**W13-02** · lead(实现) + worker(test-only) · **high(public-contract)** · W2
- owned(lead): `web/app.py`（settings/host/version 路由迁出至 `web/host_boot.py` + 别名）
- owned(worker test-only): 别名等价测试补充（tests/test_route_alias_settings.py）
- depends: W13-01
- 目标：宿主组合根：`_install_plugin_host` 的 host 更新/健康检查/安全引导迁入宿主专用模块；
  settings/host/version 路由迁移，旧路径别名绑定唯一实现，golden 快照零差异。

**W5-01** · worker(ordinary-implementation) · low · W2
- owned: `host/projects_service.py`（新），`plugins/workbench/static/projects.js`（如存在则为改名编辑入口），
  `tests/test_projects_edit_contract.py`（新）
- read: `vse_boot/projects.py`，`state/projects.json` 模式，`plugins/workbench/static/project.js`
- depends: W0-02
- 目标：契约 C3：项目编辑（改名带 expectedRevision，省略≠清空）、归档（retired 隐藏不删、
  当前项目须先切换）、车型清单可配置+文本兜底、一键开启科室选择回写项目默认科室。
  **不改 `vse_boot/`**（schema 新字段由读取方容忍；否则触发整包）。写 `state/projects.json` 经
  原子写（tmp+rename），兼容启动器并发读。
- 验收：★`python -m pytest tests/test_projects_edit_contract.py tests/test_plugin_workbench.py -q`；
  ★全量 pytest。

**W14-01** · worker(ordinary-implementation) · low · W2
- owned: `tests/test_deliverable_form_analysis_golden.py`（新），`services/deliverable_form_analysis/`（新包，原文件原地拆分）
- read: `services/deliverable_form_analysis.py` 原内容，调用方签名
- depends: W0-02
- 目标：先黄金测试（合成快照锁定 view()/rows()/form_definition() 输出逐键），再按职责拆子模块
  （定义/行处理/聚合/导出），对外 import 路径与 API 不变（原模块变 re-export 兼容壳或保留入口）。
- 验收：★黄金测试 + `python -m pytest tests/test_deliverable_form_analysis.py -q`；
  ★调用方（web/app.py 等）零修改达成 import 兼容。

**W16-01** · worker(ordinary-implementation) · low · W2
- owned: `vse_boot/autostart.py`（新），`plugins/settings/`（开关页），`tests/test_autostart_toggle.py`（新）
- read: `vse_boot/`
- depends: W0-02
- 目标：当前用户开机自启开关（HKCU Run 键，无管理员），默认关闭；向导询问位（W4-01 接）。
  注意：改 vse_boot → 触发整包发布（矩阵 §2），在任务报告标注。
- 验收：★单测（写/删/幂等/损坏容错，注册表操作 mock）。

### Wave 3（5 项并行；W13-03 独占 web/app.py）

**W13-03** · lead+worker · high(public-contract) → lead 迁移，worker 补等价测试 · W3
- owned(lead): `web/app.py`（tasks 路由 → `plugins/tasks/` 或宿主模块+别名）
- depends: W13-02
- 目标：/api/tasks 6 路由迁移，golden 零差异。

**W2-01** · **lead（凭据高危）** + worker(test-only) · high(credential) · W3
- owned(lead): `services/domain_sessions.py`（或 identity 服务收编点）、会话状态机、受控重放
- owned(worker): `tests/test_identity_renewal.py` 的合成传输夹具（按 lead 给的接口草案先行）
- depends: W0-02（契约 C2 冻结）
- 目标：契约 C2 全部条款；前端状态显示归 W3-01。

**W12-01** · worker(ordinary-implementation) · low · W3
- owned: `services/excel_env_check.py`（新），`services/excel_path_safety.py`（新），
  `tests/test_excel_path_safety.py`，`tests/test_excel_env_check.py`
- read: `services/excel_*`，`tools/excel_worker_cli.py`
- depends: W0-02
- 目标：契约 C10 Excel 部分：路径安全矩阵（穿越/UNC/ADS/重解析点/替换）、环境探测
  （已装/激活状态"需要检查"/残留进程）、worker 自动启停钩子（空闲退出）。
  只出服务与测试；UI 在 W12-02。
- 验收：★两个新测试文件全绿；★全量 pytest 无回归。

**W1-01** · worker(ordinary-implementation) · low · W3
- owned: `web/diagnostics.py`（白名单重构），`tests/test_diagnostics_whitelist.py`
- read: `web/diagnostics.py` 现状，`host/context.py`
- depends: W0-02
- 目标：契约 C10 诊断部分：字段白名单导出（匿名标识/计数/安全错误码），正则脱敏仅补充；
  禁止导出清单逐项拒绝测试。
- 验收：★`python -m pytest tests/test_diagnostics_whitelist.py -q`；现有诊断路由行为兼容。

**W14-02** · worker(ordinary-implementation) · low · W3
- owned: `tests/test_crawler_split_golden.py`（新），`services/tdc_crawler/` 与 `services/aras_crawler/`（新包拆分）
- read: 原 crawler 模块
- depends: W0-02
- 目标：Aras/TDC 抓取服务按职责拆分（会话/查询/解析/导出），公开函数签名与行为不变；
  黄金测试锁行为。**不动 web/app.py 的调用点**（import 路径保持兼容）。
- 验收：★黄金测试 + `python -m pytest tests/test_tdc_crawler.py tests/test_aras_crawler.py -q`。

### Wave 4（7 项并行；W13-04 独占 web/app.py）

**W13-04** · lead+worker · high(public-contract) · W4
- owned(lead): `web/app.py`（Excel 领域路由：excel-tasks/excel-artifacts/excel-worker）
- depends: W13-03
- 目标：Excel 路由迁移，golden 零差异。

**W3-01** · worker(ui) · low · W4
- owned: `plugins/workbench/static/session-status.js`（新），顶栏胶囊接线文件，
  `tests/test_session_status_frontend.py`
- read: `/api/identity` 载荷（W2-01 产物，按契约 C2 状态集）
- depends: W2-01
- 目标：顶栏两徽章合一（已连接 ✓ / 正在恢复 / 需要重新登录），点击原位登录（复用登录卡片）。

**W6-01** · lead(调度核心) + worker(ordinary-implementation) · high(concurrency) 拆分：
- 调度权威/租约/补跑 = **lead**（`services/scheduler_kernel.py` 新，含持久槽表迁移——增量 host.migrate）
- worker: 槽表仓库 + 单测（`core/repos/schedule_slots.py`、`tests/test_scheduler_slots.py`）
- depends: W0-02（契约 C4）
- 目标：契约 C4 全部条款；只调度当前项目；日报新鲜度独立保证（F3 挂钩在 W7-01）。

**W5-02** · worker(ui) · low · W4
- owned: `plugins/workbench/static/plan-edit.js`（新），`tests/test_plan_edit_frontend.py`
- read: `/api/project-status/phases` 载荷
- depends: W0-02
- 目标：时间轴直接编辑 + 表格模式（C3）；保存走既有 PATCH（修订检查沿用 C3）。

**W1-02** · worker(ui) · low · W4
- owned: `plugins/diagnostics/`（新插件：专家模式自检页）
- read: `host.context`，W12-01 服务，identity 状态
- depends: W12-01（可选部分并行：页骨架先行）
- 目标：专家模式"自检"页：登录态、各连接器取证、调度、Excel COM、更新通道逐项检查 + 导出脱敏诊断包。

**W14-03** · worker(ordinary-implementation) · low · W4
- owned: `tests/test_project_status_updates_golden.py`（新），`services/project_status_updates/`（新包拆分）
- depends: W0-02
- 目标：64KB 服务按校验/运行/审计拆分，行为不变黄金测试；调用方零修改。

**W16-02** · lead(选型与窗口核心) + worker(mechanical) · high(并发/进程) 拆分：
- lead: L0 Spike 报告（pywebview vs Edge app vs WebView2，含 W17-01 产出）、单实例互斥量、
  端口冲突零干预、窗口三级回退骨架
- worker(test-only): `tests/test_single_instance.py`（互斥量与端口探测单测，mock 层面）
- depends: W17-01（浏览器通道结论）
- 目标：A2/A3/A4；vse_boot 改动 → 整包（报告标注）。

### Wave 5（6 项并行；W13-05 独占 web/app.py）

**W13-05** · lead+worker · high(public-contract) · W5
- owned(lead): `web/app.py`（scheduled-archive 路由 → 插件/别名）
- depends: W13-04
- 目标：10 路由迁移，golden 零差异。

**W7-01** · lead(报告幂等层) + worker(ui+实现) · 中高危拆分：
- lead: `services/report_ops.py` 幂等层（opId/configVersion/dataVersion，契约 C5）
- worker: 报告页一键生成 UI、TIR 复用键实现、导出入口统一（`plugins/tir_report/`、
  `plugins/sign_daily/` 页面、`plugins/deliverables/` 导出位）、`tests/test_tir_reuse.py`
- depends: W6-01（日报定时挂调度）
- 目标：F1/F4/F5/F6/F7；generation_unknown 红线不变（只生成/人工核查，不自动重发）。

**W11-01** · worker(ordinary-implementation) · low · W5
- owned: `services/task_center.py`（收编点），`plugins/workbench/static/task-progress.js`（新），
  `tests/test_tasks_lifecycle.py`，`tests/test_notify_dedup.py`
- depends: W13-03（tasks 服务化）
- 目标：契约 C6：cancel_requested/cancelled 两态、不定进度、retryOf、通知去重+项目名、
  清理保护边界；托盘通知经 notify 服务（U9）。

**W4-01** · worker(ordinary-implementation) · low · W5
- owned: `plugins/workbench/static/wizard.js`（新），`tests/test_wizard_state.py`
- read: W5-01 项目编辑接口、W16-01 自启开关、enable-flow.js
- depends: W5-01，W16-01
- 目标：U1 完整向导：欢迎→登录→建项目（车型/科室）→选交付物→自启询问→完成+首同步；
  跨重启恢复非敏感状态；"稍后设置"与"已完成"区分；密码不持久化断言。

**W12-02** · worker(ui) · low · W5
- owned: `plugins/excel_tasks/static/`（工具页界面重排）
- depends: W12-01
- 目标：H1/H4：拖入→选操作→结果；自检结果展示（"需要检查"态如实显示）。

**W14-04** · worker(ordinary-implementation) · low · W5
- owned: `tests/test_project_discovery_golden.py`（新），`services/project_status_discovery/` 拆分
- depends: W14-01（拆分模式与夹具复用）
- 目标：发现/交付物分析服务拆分，行为不变。

### Wave 6（4 项并行；W13-06 独占 web/app.py）

**W13-06** · lead+worker · high(public-contract) · W6
- owned(lead): `web/app.py`（aras 路由迁移）
- depends: W13-05

**W6-02** · worker(ordinary-implementation) · low · W6
- owned: `plugins/deliverables/static/watchlist.js`，`plugins/project_overview/static/deliverable/detail/`（同步记录/原件留存页签）
- read: archive 服务，watchlist 存储
- depends: W13-05（archive 服务就绪）
- 目标：G1/G2/D9：原件留存并入同步（runId 关联），历史原件页签，关注清单双入口同源。
  **注意文件所有权**：detail/watchlist 归本任务；simple/form-analysis 归 W9-01。

**W9-01** · worker(ui) · low · W6
- owned: `plugins/project_overview/static/deliverable/simple.js`，`simple-logic.js`，
  `form-analysis.js`（如拆出则归本任务），`tests/test_plugin_overview_simple_logic.py` 扩展
- depends: W0-02
- 目标：E1/E2/E3：表单单一入口（详情页内）；简洁视图表格排序/筛选/分页/列显隐/复制单号；
  列 key 缺失回退 c.index。

**W8-02** · worker(ui) · low · W6
- owned: `plugins/sign_daily/static/`（除 report.js 既有门禁文件外的新组件文件）、
  `plugins/tir_report/static/`、`plugins/system_query/static/`、`plugins/settings/static/`、
  `tools/excel_worker_cli.py` 之外的工具旧页（`plugins/excel_tasks/static/` 排除——W12-02 已改）
- depends: W8-01（UI Kit）
- 目标：报告/设置/查询/工具旧页体验统一（ErrorCard/状态色/骨架屏接入）。

### Wave 7（3 项并行；W13-07 独占 web/app.py）

**W13-07** · lead+worker · high(public-contract) · W7
- owned(lead): `web/app.py`（tdc 路由迁移）
- depends: W13-06

**W10-02** · worker(ui) · low · W7
- owned: 全站前端时间显示文件（`plugins/*/static/**` 中时间格式化点；与 W9-01 冲突的文件
  由 W9-01 先集成后本任务再动），`tests/test_time_display_frontend.py`
- depends: W10-01；与 W13-07 同波但**不碰 web/app.py**（载荷字段时区化随 W13-09 收口）
- 目标：F8/C5 接入：显示全北京时间；逾期三处（列表/详情/报告）一致走 core/time_rules。

**W17-02** · worker(ordinary-implementation) + lead 出包 · low（测试执行） · W7
- owned: `tests/test_real_exe_v2.py`（扩展），真机执行记录
- depends: W16-02（窗口/单实例/端口）
- 目标：真实 exe：向导全流程、多项目切换、一键开启、报告路径；输出如实记录（含失败项）。
  本波打候选包（版本号见 RELEASE_MATRIX）。

### Wave 8（3 项并行；W13-08 独占 web/app.py）

**W13-08** · lead+worker · high(public-contract) · W8
- owned(lead): `web/app.py`（表单/目录/概览及剩余非 project-status 路由）
- depends: W13-07

**W8-03** · worker(ui) · low · W8
- owned: 其余插件页面收口（`plugins/deliverables/static/`、`plugins/deliverable_forms/static/`、
  `plugins/scheduled_archive/static/`、宿主壳层 `web/static/host/` 微调）
- depends: W8-02
- 目标：全部插件页面+宿主壳层体验收口（U4-U8 全覆盖）。

**W18-02** · worker(ordinary-implementation) · low · W8
- owned: 索引/查询优化点（`core/db_common.py` 索引定义、慢查询 SQL），`tests/test_db_indexes.py`
- depends: W18-01（基线数字）
- 目标：仅对已测瓶颈优化：索引、查询、大表分页；基线对比数字入报告。

### Wave 9（2 项并行）

**W13-09** · lead · high(public-contract) · W9
- owned: `web/app.py`（project-status 最后迁移 + 装配化收尾）
- depends: W13-08
- 目标：94 → 0 直写业务路由体；web/app.py 仅保留组合根与装配。

**W15-01** · worker(ordinary-implementation) · low（删除清单由 lead 逐项批准） · W9
- owned: `main.py`、`services/office_toolbox.py`、`services/intranet_scraper.py`、
  `services/feishu_imap.py`、`tools/install_*_task.ps1`、spec/依赖清理、`tests/` 对应用例
- depends: W13-09（调用点清零后再删）
- 目标：K1–K6：CLI、旧 deliverables 工作台（**保留新版 workbench**）、飞书代码路径
  （**feishu_tasks 表不删**、TDC feishukey 保留）、Probe 生产产物、selenium/rich/imapclient 依赖。
  K4 Probe 开发能力保留。

### Wave 10（串行，独占）

**W16-03** · **lead** · high(security) · W10
- owned: `web/app.py`（启动交换/本机 Cookie/统一写保护接入点）、`web/security.py`（新）、
  `vse_boot/` 启动票据
- depends: W13-09，W17-01
- 目标：契约 C7 全部条款；fail-closed 验证。整包发布。

### Wave 11（3 项并行）

**W17-03** · lead(门禁裁定) + worker(mechanical) · low（执行记录） · W11
- 目标：候选包 e2e、验签、哈希对照、白名单、篡改拒绝、升级、回退、负向验证（真机）。
- depends: W16-03

**W18-03** · worker(test-only) · low · W11
- 目标：最终同机性能复测，对比 W18-01 基线。
- depends: W16-03

**W19-02** · worker(mechanical) · low · W11
- owned: `docs/manual/**`，`docs/PRODUCTION_OPERATION_GUIDE.md`（按 RELEASE_MATRIX §3 修订）
- 目标：中文截图手册、用户更新记录、生产操作指南修订。
- depends: W17-03（包行为定稿后截图）

### Wave 12（串行；外部条件）

**W1-03** · lead + 用户 · ⏸ 待真实环境
**W20-02** · lead + 3 名新用户 · ⏸ 待真实人员
- 缺环境/人员时保持待验证，如实标记，不伪造结果。

## 3. 每波门禁（goal §7 原样生效）

lead 在全部 writer 停写后逐项评审集成，同一集成提交上执行：
① 聚焦场景测试 ② `python -m pytest tests -q` ③ `python tools/generate_project_map.py --check`
④ Node 夹具+术语+关键浏览器路径 ⑤ 唯一版本测试包+验签+哈希+白名单+篡改拒绝
⑥ 安装启动冒烟（宿主/运行时变化则整包）⑦ 高风险故障注入与回退 ⑧ 追踪矩阵/memory 更新。
地图、记忆、需求状态、插件版本号由 lead 在集成阶段统一更新。

**禁止**：拼 worktree 结果当整波通过；历史测试数当本轮证明；缺 Playwright 静默 skip 当发布门禁；
删有效业务断言换通过；因预算或代码写完宣布完成。

## 4. 回滚原则（goal §8 原样生效）

高风险任务动手前明确回滚步骤：先停派发再处理活动任务；保留旧版本与数据恢复点；增量迁移后旧代码
仍可读；未放行业务写入才可恢复迁移前数据；手动回退不恢复旧数据库覆盖新增数据；凭据清除不可回滚恢复；
未知外部副作用不自动重放；诊断失败不退回原始日志打包；本机认证失败不退回无认证访问；临时清理不删
历史原件与用户输入；**禁止整体 reset/clean/覆盖工作区**。

## 5. 明确不做（本阶段）

- 多项目后台同步实现（ADR-0001，只设计）。
- 前端构建链、ORM 替换、文件级差分更新、bundle 能力（A6 的 bundle 部分）。
- L0 原生启动器替换（只 Spike）。
- 正式代码签名（落实前仅内部测试包）。
- 48 车型代码清单编造（等用户提供；期间可配置清单+文本兜底）。
