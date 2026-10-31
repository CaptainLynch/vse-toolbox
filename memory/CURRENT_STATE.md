# Current State

> 本文件已按 2026-10-23 的上下文治理决定裁剪：只保留最近条目与"当前前沿"。
> 更早条目完整保存在 [归档文件](archive/CURRENT_STATE_ARCHIVE_20261023.md)。
> 恢复状态时**不要**再通读全文；先读本节，再按需查归档。

## 当前前沿（2026-10-31 · Wave 9 完成：app.py 装配化 + W15-01 下线）

- **W13-09a（09f41a2）——补完 W13-07/08 接线（复核纠偏）**：Wave 8 的 19c09cf/bd6792b 实为向
  crawler_boot **复制副本**，路由原件从未迁出、`register_tdc_routes`/`register_form_catalog_routes`
  零调用者（提交说明与实际不符，全量测试因原件仍在而全绿）。本轮：两 register 真正接线
  （CrawlerRouteDeps 增 deliverable_form_service/section_rollup_store，register_form_catalog_routes
  改收 deps 并逐字回迁 2 个 create_app 闭包）；补 4 处缺名（副本是死代码，缺名只在真实调用时暴露——
  `_DEFAULT_TDC_ALLOWED_HOSTS`、DELIVERABLE_LINK_REGISTRY、build_rollup_index、SECTION_ROLLUP_FORM_KEYS）；
  app.py 删 57 个重复顶层定义（1580 行）转 51 名别名再导出（单源）；7 处测试补丁目标改随路由现属模块。
  全量 3637/6/0。
- **W13-09b（a85a875）——project-status 最后迁移**：三清单冻结法（43 模块成员 + 3 create_app 闭包 +
  27 条 /api/project-status* 路由，全部逐字）→ 新建 `web/project_status_boot.py`（2967 行），
  `ProjectStatusRouteDeps` 注入 8 个服务实例；注册接线置于 install_diagnostics 之前（旧路由全部注册后、
  插件加载前）。**app.py 5330→736 行**：只剩装配适配（服务构造 + 各领域 register 调用）与通用路由
  （/、/favicon.ico、/api/overview）；flake8 F401/F821 清零；194 个失消费导入修剪。
  43 名经 app.py 别名回导——`web_app._MAPPING_DISCOVERY_TASKS` 等 40+ 处测试原地 dict 变更不受影响；
  5 个补丁目标符号（_build_tdc_client_from_payload/_build_aras_client_from_payload/
  _mapping_discovery_query_identity/_crawl_runner_from_request/create_production_registry）
  改指 ps_boot（**多行 setattr 与参数化动态目标也要改**——单行正则漏网 9 处）。全量 3637/6/0。
- **W15-01（60eaf6b）——K1–K6 全落地**：删 main.py（1682 行 Rich 交互 CLI）、plugins/deliverables
  （旧交付物工作台；legacy `#deliverables` 改指 `#p/project-overview/details`）、services/feishu_imap.py、
  3 个 install_*_task.ps1、VSE-Toolbox.spec + VSE-Toolbox-cli-default-url.spec；requirements 移除
  rich/imapclient/selenium。**保留**：feishu_tasks 表、TDC feishukey（tdc_auth.py:233）、
  plugins/workbench（新版工作台）、Probe 开发能力（tdc_probe_main/cli + VSE-TDC-Probe.spec，
  Keyboard 中断 130 语义由 tdc_probe_main 承接）。测试删 7 个专属套件、改造 4 个混合套件
  （aras_cli_web 保 42 个 web 测试；credential_safety 保 8 个核心脱敏测试；probe 24 个改走专用入口）。
  全量 **3514/6/0**（净减 123 个 CLI 专属用例）。
- **门禁**：wave_gate PASS（地图 verified、术语门禁 PASS；打包留 W17-03）；按 RELEASE_MATRIX 追加
  Wave 9 集成包 `dist/v2-test/updates/vse-app-2.3.14.vsepkg`（261 文件，sha256 `3c1c1176…`，
  含全部 7 个 *_boot.py；main.py 与 plugins/deliverables 已不在包内；**未真机安装**）。
- **提交链**：a24db63（地图指纹+W13-07 教训）→ 09f41a2（W13-09a）→ a85a875（W13-09b）→ 60eaf6b（W15-01）。
  无关未跟踪文件（.dsh/、pelican-*.html、dsh-remote-bridge.mjs、VSE-WebUI-compact.spec、
  .claude/launch.json、docs/dsh-remote-control/）保留未提交——**禁止 git add -A**，按路径显式加。
- **下一步 Wave 10（串行独占）**：**W16-03 安全集中接入**（lead，high/security）——boot 交换票据、
  本机 Cookie、统一写保护接入点（web/security.py 新建 + vse_boot/ 启动票据），契约 C7 全部条款、
  fail-closed 验证，整包发布。之后 Wave 11（W17-03 门禁裁定 + W8-02 剩余页 + W18-02 索引优化）。
- **真机验证累积至 W17-02**：2.3.5–2.3.14 全部未真机安装；W1-03/W20-02 需真实环境与人员。

## Wave 梗概（W2–W8，2026-10-31，详见 git log 与 REQ_TRACEABILITY.md）

- **W8**：包 2.3.13；「W13-07 重做成功」记录已纠偏（实为副本，见上）。
- **W7**：W13-07 首次迁移失败回退（52 成员闭包含 create_app 局部依赖，6+ 层缺名不收敛）；
  W8-02b 四页 ErrorCard/Skeleton 源级断言门禁 23 测试；W10-02 全站 zh-CN 时间门禁；包 2.3.12。
- **W6**：W13-06 Aras 9 路由 + 40 助手迁 crawler_boot（patch 目标随迁两分类）；W9-01/W6-02；
  W8-02 因 hooks 无 DOM 直渲染缺陷整体留下一波改源级断言；包 2.3.11。
- **W5**：W13-05 archive_boot（10 路由；_archive_history_limit 曾被凭印象重写被测试抓获——迁移必须逐字）；
  W4-01 向导五步；W11-01 任务生命周期（**register 级实例防多 app 串味**）；包 2.3.10。
- **W4**：W13-04 excel_boot（ast 自由变量审计方法论）；W3-01/W5-02/W1-02/W14-03A；包 2.3.9/2.3.8。
- **W3**：W13-03 tasks_boot（块提取要连带常量 _CRAWL_TASK_TYPE_LABELS）；W12-01 路径安全；
  W1-01 诊断白名单；W14-01 包壳 = _impl 原文 + re-export（worker 拆分漂移被 lead 回退）；包 2.3.7。
- **W2**：W13-02 host_boot（11 路由）；W5-01 修订检查；W16-01 开机自启；路由基线 163 条；包 2.3.6。
- **W1**：路由契约快照 golden、时间逾期内核 core/time_rules.py、UI Kit + 术语门禁、wave_gate、
  性能基线（冷启动 1948ms）、真机核对清单；包 2.3.5。worker 运行时协议 8 项适配见 RECOVERY_NOTES。

## 2026-10-29 3D单签署日报两处口径修复（发送门禁 + 幻影项目）【真机待验】

- **根因（已核实）**：① 主题/正文首行项目串取自**请求里的选择**而非实际计入的 flows（前端只渲染
  数据里存在的 chip、从不与已保存选择对账）；② 数模状态列在**交付物同步**路径是数字码（2/4 映射，
  3/6 透传），日报只认字面「已废弃」→ 未知状态=在途混入。
- **落地**：`service.status_gate()` + `statusGateEnabled` 开关；`/eml` 409 StatusGateBlocked；
  `project_label` 用「选择 ∩ 实际计入」+ `selectedWithoutData` 披露；孤儿项目虚线 chip
  **可取消但绝不自动删除**，取消时仅当新范围无记忆才沿用旧范围收件人/文案。
- **顾问二轮（打包前复核）**：D1「偏好迁移整表替换」/D2「切换范围回落收件人」均被代码证据推翻；
  采纳：门禁数字形态放宽（整数或 .0 浮点）、提示文案、非阻断披露、Chips 抽 `static/chips.js` 固化 3 条
  pytest 门禁。包 2.3.4（sha256 `bb1b7f60…`）；全量 3441/6。
- **待办**：生产只读取证（generate 响应 anomalies 分组、UTC 回取 20:44 快照、码值×中文交叉表）→
  定 B1（码值映射）再谈根治；门禁上线后若快照仍是数字码，日报会连续不出报，需业务认可。

## 2026-10-29 v2 同步三问题修复【真机待验】

- **根因（已核实）**：① 幂等 skipped 分支不刷新 `last_success_at`，且 sync-now 对 failed 也返回 200+ok
  （`core/repos/sync_runs.py`）；② 后端已派生 `syncDisplay.displayProgress`，简洁视图与工作台列表读的
  是手工 `progress`；③ 数模稳定性采样用**未收窄**第 1 页比**已收窄**全量基线（永久 inconclusive），
  失败落 `key_changed` 会顶掉基线。
- **落地**：`derive_effective_progress` 契约（progress 语义不变，防编辑表单把派生值写回）；
  简洁视图拆 `simple-logic.js`（Node 门禁可断言）；skipped 刷新 last_success_at；采样统一
  `_narrow_discovery_rows_by_sections` + 有界翻页（`_STABILITY_SAMPLE_MAX_PAGES=10`），
  基线改取「最近一条 matched」（50 条回看窗口）。实施后复核：旧配置基线只做否定性比对
  （`baseline_signature_mismatch`）等 3 采纳、4 项顾问判断被代码证据否决。包 2.3.3。
- **审计补丁**：分页类稳定性采样（SOR/数模无单号）统一走 `web/app.py::_stability_paged_sample`——
  **W13-09b 后已迁居 `web/project_status_boot.py`（别名 `web_app._stability_paged_sample` 仍可用）**。
- **待办**：真机端到端（EWO 连点两次同步、数模开启自动同步）；基线自检暂缓（total 语义未取证，加了会误杀）。

## 2026-10-31 v2 全波次执行启动（W0）· ZCode 路线

- **路线**：当前交互模型任唯一 lead，Gemini 3.8 Flash worker 承担有界任务；不启用 DSH，不双 lead，
  不换供应商。总规划 `docs/PROMPT_20261031_ASTRA_V2_MASTER_PLAN.md`；执行计划
  `docs/refactor-v2/EXECUTION_PLAN_20261031.md`；契约 `CONTRACTS.md`（十域）；
  需求对账 `REQ_TRACEABILITY.md`（72 编号）；发布规则 `RELEASE_MATRIX.md`。
- **W0 基线**：分批提交 `b9f309b`/`7f4617f`/`d7ba018`；全量 3441/6（414s）。
- **worker 协议适配（b3358af）**：runtimeModel 停发、模型引用带 options.reasoningLevel、会话级
  thoughtLevel、回显只锁 providerId/modelId 等 8 项，详见 RECOVERY_NOTES 2026-10-31。
- **待办（如实标记）**：2.3.3–2.3.14 包真机未验证；48 车型清单等用户提供；W1-03/W20-02 需真实环境与人员。
