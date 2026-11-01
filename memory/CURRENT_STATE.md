# Current State

> 本文件已按 2026-10-23 的上下文治理决定裁剪：只保留最近条目与"当前前沿"。
> 更早条目完整保存在 [归档文件](archive/CURRENT_STATE_ARCHIVE_20261023.md)。
> 恢复状态时**不要**再通读全文；先读本节，再按需查归档。

## 当前前沿（2026-11-01 · DSH 计划第 1 波全部集成：V2-01/44/45/46/47 + 遗留修复）

- **第 1 波收尾（18beeb0，快进合入 refactor/ux-v2）**：集成全量 **3582 passed / 7 skipped / 2 warnings，
  exit 0，466.15s**（`E:\project\vse-toolbox-wt\_logs\wave1b-integration-pytest.txt`）。
  - 38b854f **V2-47**（用户批准 high 风险、主控冻结契约 C1–C5；wf-528d1b1d 第 2 轮评审 pass）：
    pywebview 改 `--window URL --profile DIR` 独立子进程（`supervisor.run_window`，主线程，退出码 0/3/4）；
    `open_window` 立即返回，非 daemon 监视线程 15s 宽限期内非 0 退出才降级 Edge → 浏览器；
    端口冲突 `port_conflict` 换端口重试 ≤3 次，不记 bootFailed；自启默认关闭已核实。
    **取舍**：第二实例开出的窗口不挂其 job（否则随短命进程被杀），长驻启动器退出时它不随之关闭。
    **留给 02/03**：窗口子进程与 Edge 一样把含 `?boot=` 票据的 URL 放在命令行（进程列表可见）；
    `_show_existing` 仍复用 instance.json 旧 URL。`autostart.enabled(repair=True)` 会删除损坏的自启值
    （只读测试 test_autostart_toggle 断言此行为），与“不删除用户注册表项”的张力待裁决。
    真机未验证：第二实例窗口在其进程退出后存活、WebView2 存储目录。
  - 745dedd **遗留修复**：`web/app.py` 启动清理改走 `CrawlTaskRunner.cleanup_expired_artifacts`
    （用户文件不再被启动清理删除）；`build_v2_test_install` 安装目录 rmtree 失败报告并 exit 2。
    “旧包清理早于 exe 构建”核实为预期（先失败再构建），不改。

- **DSH 第 1 波（2026-11-01）——已合入 refactor/ux-v2（7cfa1a4，快进）**：计划见
  `docs/dsh-next-20261031/`。四任务各在隔离工作树执行（DSH 执行者 deepseek-v4.1-flash，Claude 评审），
  合并无冲突；集成全量 pytest **3556 passed / 7 skipped / 2 warnings，exit 0，441.56s**
  （日志 `E:\project\vse-toolbox-wt\_logs\wave1-integration-pytest.txt`；新增 skip 为 V2-45 符号链接用例）。
  - 4ee5f49 V2-46 交付物详情表格列身份（simple-logic.js 纯函数 + Node 驱动测试）。
  - ac59701 V2-44 测试安装输出根可配置（`--out`/`VSE_TEST_INSTALL_ROOT`）、旧包清理失败 exit 2 不吞错。
    **评审两轮均 pass，但桥指纹在内容未变时翻转（881a69bf↔e0c76e1c）致工作流 blocked，由主控人工复核放行**。
    遗留低风险：旧包清理移到 exe 构建之前；`shutil.rmtree(install, ignore_errors=True)` 仍静默。
  - a7edd4e V2-45 产物过期清理只删过期且非活跃任务、失败保留并报告；TaskCenter 进度仅展示层。
    遗留：`web/app.py` 启动期清理仍按 mtime 删除，未走新链路。
  - 2542dab V2-01 本机安全真实 HTTP 集成测试（werkzeug make_server + FakeClock，5 场景）。
  - 合并后 `PROJECT_MAP.md` 已 `--write` 刷新，`--check` exit 0。
- **执行环境教训**：本地网关并发 4 个执行者会 503 `no_healthy_account`——**串行派发**；桥已修超时杀进程树
  （`taskkill /T /F`）、执行超时 30 分钟；指纹翻转根因未定，桥已加 `~/.dsh-bridge/fp-debug.log` 诊断。
  执行者计划须写明不得用 `git add -N` 等改动索引的命令。
- **下一步**：第 1 波已全部完成；按 tasks.json 依赖推进第 2 波（02/06/07/08/09/12/14/24/25/26/42/48/49，串行派发）；
  其余后续波次按 tasks.json 依赖推进。W16-03 集成验收项仍未做（见下）。

- **W16-03（b781066）——已提交、待集成验收（不是已交付）**：本机安全集中接入，C7 全条款落地。
  `web/security.py` 新建（247 行：BootTicketStore 10 秒一次性启动票据 / LocalSessionStore 12 小时会话
  Cookie / LocalWebSecurity 统一写保护）；`web/static/host/boot-exchange.js` 前端换票；
  `vse_boot/supervisor.py` 把票据写进 `?boot=` 与 instance.json bootToken；`webui.py`、`web/app.py` 接线；
  新增 `tests/test_local_security.py`（339 行）、路由金样 +11 条；删除 `tools/verify_milestone_empty_restore.py`。
  **集成验收（真机票据、会话过期、重复启动复用旧 URL、`install_local_security` 无条件装自动认证测试
  客户端）全部未做**——按「已提交、待集成验收」记账，不得写成通过。
- **DSH-V2-00（本轮）——重建 b781066 验收基线并纠正进度记录**：HEAD `7798997`（b781066 之上的纯文档提交）；
  开工时 `git log -1 --oneline` = `7798997 docs(dsh-next): 新增 DSH 后续 50 项任务计划基线（README + tasks.json）`，
  `git status --porcelain` 显示 3 个已修改文件（`PROJECT_MAP.md`、`memory/CURRENT_STATE.md`、
  `docs/refactor-v2/REQ_TRACEABILITY.md`，均属本任务 owned_scope，来自先前未收尾的部分尝试），无未跟踪文件。
  以下为本轮实测，日志目录 `E:\project\vse-toolbox-wt\_logs\DSH-V2-00\`（工作区外）：
  - **全量 pytest**：`python -B -m pytest -p no:cacheprovider tests -q -rs` → **exit 0**，
    **3530 passed / 6 skipped / 2 warnings**；首轮 535.99s（0:08:55，`pytest-full.txt`），
    评审复核复跑 471.64s（0:07:51，`pytest-full-round2.txt`）。同一工作区另记录两次全量
    （486.02s / 557.26s），四次计数完全一致，结果稳定。6 个 skip 全为环境缺失：
    playwright 未安装 ×2（test_plugin_overview_browser.py:24、test_plugin_sign_daily_browser.py:18）、
    Windows 不允许建符号链接 ×2（test_archive_store.py:69/162）、`time.tzset` 仅 POSIX ×1
    （test_sign_daily_mail.py:133）、symlink unavailable ×1（test_zcode_worker.py:475）。
    2 条 warning 均在测试侧：test_plugin_diagnostics.py:251 SyntaxWarning（`\s` 无效转义）、
    test_glossary_terms.py:310 禁词基线 UserWarning。
  - **口径纠正**：`3530 passed/6 skipped/13 warnings in 437.58s` **只是 W16-03 提交前的历史全量**，
    不是本轮证据；本轮 passed/skipped 计数与之相同但 warning 为 2（环境相关），两者分别记录、不得混写。
    `3514 passed/6 skipped` 是 W15-01（60eaf6b）提交时的历史数字，**不是当前全量**，不得引用为现状。
  - **子集预检**（4 个套件，非全量）：test_local_security / test_route_contract_snapshot /
    test_time_rules / test_time_display_frontend → **44 passed，exit 0**，**5.81s**（本轮实测，
    `pytest-subset-44.txt`；派发前源证据为 7.71s）。只作抽样，不能代表全量。
  - **项目地图**：提交态 `PROJECT_MAP.md`（指纹 `580f871a…`、259 文件）已过期——本轮把 HEAD 内容放回
    工作区复跑 `--check` → **exit 1**（`Project map is out of date`，与派发前记录的失败一致）；
    本工作区地图已由先前部分尝试重新生成，故本轮 `--write` → **exit 0**（幂等，写入前后 sha256 不变）、
    `--check` → **exit 0**（`Project map verified`）。漂移仅 W16-03 增量：指纹 `580f871a…`→`57f6074c…`、
    范围文件 259→261、Python 模块 121→122、新增 `web/security.py` 行。
  - **flake8**：`python -m flake8 web/app.py` → **exit 1**，6 条：E303×2（429、606）+ **F811×4**
    （561 的 `CrawlerRouteDeps`/`register_crawler_routes`、606 的 `ProjectStatusRouteDeps`/
    `register_project_status_routes`，均为工厂函数内局部 import 遮蔽模块级别名再导出）。
    **历史 F811 记录经实测确认存在**，以真实退出码与输出为准；`echo FLAKE-OK` 之类不算通过。
    本任务不修产品代码，缺陷留后续任务处理。
  - **评审阻断复核（round 2）**：评审期工作区指纹由 `b84b3415…` 变为 `7d1bfec0…`，逐项核对确认
    **仅文档改动、无产品代码变化**：HEAD 仍 `7798997`；`git diff --name-only` 只有 `PROJECT_MAP.md`、
    `memory/CURRENT_STATE.md`、`docs/refactor-v2/REQ_TRACEABILITY.md`；产品/测试文件与 HEAD 逐字节一致，
    `git ls-files --others --exclude-standard` 为空。复核复跑：全量 pytest **exit 0，3530/6/2，471.64s**
    （`pytest-full-round2.txt`）；`flake8 web/app.py` **exit 1**（同 6 条）；`generate_project_map.py --check`
    **exit 0**；`git diff --check` **exit 0**；CURRENT_STATE ≈15.7 KB（≤40KB）。锚点：
    `PROJECT_MAP.md` sha256 = `49B44AAB14B17C945E2C1113FCCBE28DC2719E291EF7E8C091E742BCBB8213B3`（复核前后未变）。
  - **构建 WinError5 证据（根因未定）**：`tools/build_v2_test_install.py:126 old.unlink()` 对
    `dist/v2-test/updates/vse-app-2.3.10.vsepkg` 抛 `PermissionError WinError 5`，构建 exit 1
    （日志 `.runtime/w16_03_build.log`）。文件被占用与 ACL 拒绝均可能，**未验证前不得断言单一根因**；
    修复归 **DSH-V2-44**，本任务不改构建脚本；本轮未复跑构建，证据沿用 W16-03 记录。
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
  全量 **3514/6/0**——**该数字只是 60eaf6b 提交时的历史值，不是当前全量**（净减 123 个 CLI 专属用例）。
- **门禁**：wave_gate PASS（地图 verified、术语门禁 PASS；打包留 W17-03）；按 RELEASE_MATRIX 追加
  Wave 9 集成包 `dist/v2-test/updates/vse-app-2.3.14.vsepkg`（261 文件，sha256 `3c1c1176…`，
  含全部 7 个 *_boot.py；main.py 与 plugins/deliverables 已不在包内；**未真机安装**）。
  **口径注意**：wave_gate 的 `package_sign` 恒为 SKIP、`overall_passed` 只判「无 FAIL」、`--focus` 会隐式
  skip_full，所以 **PASS ≠ 发布通过**；门禁裁定归 W17-03。
- **提交链**：a24db63（地图指纹+W13-07 教训）→ 09f41a2（W13-09a）→ a85a875（W13-09b）→ 60eaf6b（W15-01）
  → 261ed6e（Wave 9 记忆）→ 7e16687（RECOVERY_NOTES 标记修正）→ **b781066（W16-03）** → 7798997（DSH 计划文档）。
  无关未跟踪文件（.dsh/、pelican-*.html、dsh-remote-bridge.mjs、VSE-WebUI-compact.spec、
  .claude/launch.json、docs/dsh-remote-control/）保留未提交——**禁止 git add -A**，按路径显式加。
  本隔离工作区（`DSH-V2-00`）开工与收尾时均无未跟踪文件。
- **下一步（串行独占）**：W16-03 **已完成提交 b781066、待集成验收**——验收项：真机 `?boot=` 票据换发、
  10 秒一次性票据与 `_show_existing` 复用旧 URL、12 小时会话过期、`install_local_security` 无条件安装
  自动认证测试客户端需显式夹具与原生负向测试；验收前不得发布整包。之后 Wave 11（W17-03 门禁裁定 +
  W8-02 剩余页 + W18-02 索引优化）。
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
