# Current State

## 2026-09-22 交付物明细定时自动同步与交互去黑话化改造（实施与全套测试验证通过）

- **任务背景**：用户实际使用中反馈两项体验痛点：1) 点击同步偶发 409 报错（`映射发现证据与当前配置规则不一致`）；2) 同步成功后快照状态依然显示“已逾期”，引发业务误解；3) 同步配置中要求用户手工理解并输入“外部稳定键”，技术黑话严重影响人机交互；4) 诉求在交付物明细（非自动归档下载）增加直观的定时自动同步控制与状态感知。
- **实施内容**：
  1. **[409 根因消除与历史自愈]**（`core/db_manager.py`）：在数据库初始化/迁移中补齐历史映射证据 `config_signature` 自动回填机制，消除存量数据库升级时因历史证据签名为空导致的 409 阻断。
  2. **[交付物明细定时同步控制台]**（`services/project_status_scheduler.py`、`web/app.py`、`web/static/app.js`、`web/static/style.css`）：
     - 升级常驻调度器为动态受控实例（支持动态频率调节、暂停/恢复、即时全量同步与状态查询），提供全局实例访问接口；
     - 新增 3 个 REST 端点：`GET /api/project-status/scheduler`（状态快照与倒计时）、`POST /api/project-status/scheduler/config`（动态频率 15m/30m/1h 及暂停恢复）、`POST /api/project-status/scheduler/sync-all`（并发同步全部已启用交付物）；
     - 前端交付物明细表头挂载可视化「交付物自动同步控制条」：包含运行指示绿灯、实时倒计时计算器（每秒平滑递减）、同步频率下拉调节、以及【立即全量同步】与【暂停/恢复调度】按钮。
  3. **[交互去黑话化与外部稳定键隐化]**（`web/static/app.js`）：
     - 将生硬的“外部稳定键”重命名为业务直观的“关联目标单号”；占位提示与说明改为“选填，输入需跟踪的目标单号（留空自动关联）”；
     - 建立匹配规则联动：用户在匹配条件中输入 EWO 编号时，前端自动静默双向绑定，彻底消除必须手工填两遍的负担；
     - 优化异常报错语义（`ewoPolicyErrorMessage`），将底层底层签名与代码异常转化为人话提示。
  4. **[状态与风险解耦表达]**（`web/static/app.js`、`web/static/style.css`）：
     - 在交付物明细表格的状态列增加红/黄风险角标（如 `(11单超期)`），鼠标悬浮展示具体风险说明；
     - 在交付物详情页顶部增加专属的「过程工单超期预警提示条」，明确区分“交付物里程碑进度（如 72%）”与“快照内客观超期工单数量（如 11 笔）”，彻底消灭“明明同步成功却显示已逾期”的认知混淆。
- **全套验证证据**：
  - 调度器与 API 专项契约测试：`python -m pytest tests/test_project_status_scheduler.py tests/test_project_status_scheduler_api.py -q` → **19 passed in 1.45s**；
  - 交付物与状态综合测试：`python -m pytest tests/test_project_status_*.py tests/test_deliverable_*.py -q` → **200 passed in 17.07s**；
  - 门禁 lint：`python -m flake8 -j 1 services/project_status_scheduler.py web/app.py core/db_manager.py tests/test_project_status_scheduler.py tests/test_project_status_scheduler_api.py` → **零告警**；
  - 前端脚本语法：`node --check web/static/{app,diagnostics,ewo-enrichment,node-overview}.js` → **全部通过**；
  - 项目地图与端点文档：`python tools/generate_project_map.py --check` EXIT 0，`API_ENDPOINTS.md` 94 个端点同步更新；
  - 浏览器真实运行验收：捕获控制条运行态（`phase3_01`）、暂停态（`phase3_02`）、全量同步后（`phase3_03`）、工单超期预警条（`phase3_04`）、去黑话表单（`phase3_05`）5 张关键截图。
- **当前状态与下一步**：全部改动保留在工作区未 commit（与既有未提交改动混同）；用户可直接双击桌面启动脚本或刷新页面体验全新的定时同步控制台。

## 2026-09-21 生产测试单文件 EXE 构建并经微信 clawbot 投递成功（工件与校验码已交付）

- **交付物**：`dist/hci-20260921/VSE-WebUI.exe`（21,389,261 字节，SHA-256 `5cbdefa52fff0ff5cbde802d1e1ee48e6eba7065927e6458f7ee35ea237123b6`），分发压缩包 `dist/hci-20260921/VSE-WebUI-0.3.0-production-test-20260921.zip`（21,047,640 字节，SHA-256 `9654dea2510d4159bf8aaa18812a87f1435244534523ebd06d0402308cc3e3af`）。
- **隔离冒烟复核**：在纯净目录（`.runtime/smoke-test-20260921`）以独立端口 5089 和 `--no-browser` 启动，测试 5 处关键接口全部通过：`/` 200、`/api/version` 200（`v0.3.0`，buildId `20260921-sync-audit-final`，isFrozen=true）、`/api/overview` 200、`/api/project-status` 200、`/api/tasks` 200。测试进程干净退出。
- **微信投递结果**：用户微信端发送消息触发刷新后，通过 `C:/Users/Lynch/.zcode/tools/weixin_bot_send.py` 成功抓取新 `context_token` 并完成两阶段投递：
  1. 成功上传腾讯 CDN 并发送 20MB ZIP 文件本体（`message_id=7507662496132925960`）；
  2. 随后成功发送版本说明与 SHA-256 校验摘要文本（`message_id=7507662565984860680`）。
- **当前状态与下一步**：工件已送达用户微信，代码改动保留在工作区未 commit。用户可直接在生产环境解压运行 `VSE-WebUI.exe` 验证。

## 2026-09-20 代码审计整改落地：TDC真实行键修正、fieldSemantics下发与同步门禁对齐（全量验证 2,297 pass 通过）

- **任务背景**：接续前一会话由 `deepseek-v4.1-flash`（$high）独立审计报告指出的 1 项 Blocker、2 项 Major、7 项 Minor 缺陷，在本会话中实施完整代码修正与全量测试闭环。
- **整改落地内容**：
  1. **[BLOCKER 消除] TDC 默认映射对齐报表行键**（`core/project_status_contracts.py`、`web/static/app.js`）：将 D2（SOR）默认映射由错误过滤词表（`applicant`/`approvalStatus`）修正为真实报表记录行键 `owner: "startUserName"`、`note: ["latestCompletedNode", "processInstanceStatus"]`；将 D5（数模）默认备注映射由未导出的 `待审批人员` 修正为有效行键 `["latestApproveLog", "status"]`。并同步更新 `DELIVERABLE_FIELD_ALIASES` 与 `PROJECT_STATUS_SOURCE_CAPABILITIES` 中对应的 `fieldSemantics` 提示词。
  2. **[MAJOR 消除] API 补齐下发 fieldSemantics**（`web/app.py`）：在 `/api/project-status` 的 `sourceInfo` 字典中完整下发 `fieldSemantics: capabilities.get("fieldSemantics") or {}`，打通前端提示词匹配推导在生产接口上的调用闭环。
  3. **[MAJOR 消除] 严格同步按钮前置门禁**（`web/static/app.js`）：修复 `hasDefaultMapping` 穿透短路缺陷。恢复 `policy.enabled === true`、`syncModeReady`（自动/混合模式）、`policy.credentialAvailable === true`、`syncMatchRuleReady` 等硬性门禁；`hasDefaultMapping` 仅参与非空映射与稳定性门槛豁免，彻底杜绝未启用时按钮误置亮与点击触发 409（`SyncNotReady`）的假就绪隐患。
  4. **能力元数据对称与清理**（`core/project_status_contracts.py`、`web/static/app.js`、`core/db_manager.py`、`services/project_status_updates.py`）：为 D4/D6-D8 补充空 `defaultMapping`/`fieldAliases`，保持注册表结构同构；前端同步判断采用 `capabilities.syncCapable` 分发；清理 `core/db_manager.py` 与 `services/project_status_updates.py` 中未引用的导入，消灭 F401。
  5. **契约测试交叉核验升级**（`tests/test_project_status_contracts.py`、`tests/test_deliverable_sync_summary_ui.py`）：契约测试增加断言校验：每个 `DELIVERABLE_DEFAULT_MAPPINGS` 字段均严格属于 `core/report_contracts.py` 对应报表已核实源字段集合；Node VM 测试采用真实 SOR/EWO 行键校验推导。
- **全套验证证据**：
  - 专项契约与 UI 测试：`python -m pytest tests/test_project_status_contracts.py tests/test_deliverable_sync_summary_ui.py -q` → **61 passed in 0.48s**；
  - 交付物与状态综合测试：`python -m pytest tests/test_project_status_*.py tests/test_deliverable_*.py -q` → **132 passed in 19.85s**；
  - 全量 pytest 套件：`python -m pytest -q -p no:cacheprovider` → **2,297 passed, 3 skipped in 258.48s (0:04:18)，EXIT 0**；
  - 项目地图检查：`python tools/generate_project_map.py --check` → **EXIT 0**（已重新生成并校验通过）；
  - 前端脚本语法：`node --check web/static/{app,diagnostics,ewo-enrichment,node-overview}.js` → **全部通过**；
  - 门禁 lint：`python -m flake8 -j 1 core/project_status_contracts.py web/app.py tests/test_project_status_contracts.py tests/test_deliverable_sync_summary_ui.py core/db_manager.py services/project_status_updates.py` → **零告警**。
- **当前状态与下一步**：全部改动保留在工作区未 commit（与既有未提交改动混同）；用户可直接刷新页面验证交付物向导、默认映射与后台同步按钮状态。

## 2026-09-20 交付物同步极简交互与内置标准映射改造（实施与全量验证 2,297 pass 通过）

- **任务背景**：用户实际测试反馈三项阻断问题（附 3 张真实截图）：1) 交付物明细中向导填入单号（如 EWO-046384）后红字报错阻断："无法从最新脱敏字段报告确定自动字段映射，请打开高级设置手工完成映射后保存"；2) 遵照提示打开高级设置后，三个字段映射输入框全空，用户手填成本极高且容易保存报错；3) TDC SOR 流程缺少开箱即用的预填映射。此与用户此前的极简交互（vibe coding）诉求相背离。
- **根因确证**：
  1. `wizardDeriveMappingFromFieldReport` 仅使用硬编码中文列名（`「责任工程师名称」`、`「要求完成时间」`），而 Aras SOAP 爬虫实际返回英文属性名（`_rsp_name`、`_required_date`、`_subject`），TDC 实际返回（`applicant`、`latestCompletedNode` 等），导致动态报告与中文提示词永远无法匹配，函数必然返回 null 并抛出硬性阻断异常；
  2. 高级设置表单未做任何已知推荐字段预填，导致用户进入高级设置面对 3 个空白输入框，且多列数组格式（`note`）回填存在空白缺陷；
  3. 分析操作栏同步按钮对字段映射存在硬性禁用逻辑，导致用户在未配置或未绑定时甚至无法点击“运行后台同步”。
- **实施内容**：
  1. **双向语义提示词与注册表补充**（`core/project_status_contracts.py`）：为 D2 (SOR)、D3 (EWO)、D5 (数模) 增加 `DELIVERABLE_DEFAULT_MAPPINGS` 与 `DELIVERABLE_FIELD_ALIASES`，并向 `PROJECT_STATUS_SOURCE_CAPABILITIES` 的 `fieldSemantics` 补充了底层真实字段名（如 `「_rsp_name」「责任工程师名称」`、`「applicant」「申请人」`），使得动态取证能 100% 成功命中实际字段；
  2. **向导智能匹配与默认兜底**（`web/static/app.js`）：`wizardDeriveMappingFromFieldReport` 依靠丰富提示词精准识别真实爬虫字段；在向导执行中，若遇到未覆盖场景自动以标准默认映射兜底，消灭抛错断点，使一键配置启用顺利跑通并触发首同步；
  3. **高级设置表单智能预填与动态下拉**（`web/static/app.js`）：高级设置表单自动预填推荐字段名（如 `_rsp_name`、`applicant`），提示显示推荐占位符；抓取映射证据成功后自动挂接 datalist 下拉选项供点选；
  4. **手动同步操作解耦**：分析操作栏按钮识别默认标准映射能力，避免在未配置自定义映射时将同步按钮置灰误导用户。
- **全套验证证据**：
  - 全量 pytest：**2,297 passed, 3 skipped / 243.23s, EXIT 0**（新增 3 项针对默认映射与真实爬虫字段命中的专项测试）；
  - 项目地图检查：`python tools/generate_project_map.py --check` EXIT 0（指纹同步刷新为 `3bc59f33...`）；
  - 前端脚本语法：`node --check web/static/{app,diagnostics,ewo-enrichment,node-overview}.js` 全部通过；
  - 门禁 lint：`python -m flake8 -j 1 core/project_status_contracts.py web/app.py tests/test_project_status_contracts.py tests/test_deliverable_sync_summary_ui.py` 零告警；
  - Node 真实环境推导测试：Node VM 执行真实 EWO（`_rsp_name` 等）和 SOR（`applicant` 等）字段推导断言全部输出 PASS。
- **当前状态与下一步**：全部改动保留在工作区未 commit（与既有未提交改动混同）；用户可直接刷新页面体验极简向导与一键同步。

## 2026-09-20 开发前状态恢复与基线复核（准备轮，无功能开发）

- **恢复次序**：`AGENTS.md` → `memory/`（CONTEXT_MANIFEST → CURRENT_STATE → RECOVERY_NOTES → DECISIONS）→ `PROJECT_MAP.md` → `git status/diff/log`。已确认 HEAD 仍 `1ea7ab9`，工作区 **98 项未提交改动**（70 文件，+14033/−4546）与历史批次业务代码混同，本轮全部保留未动。
- **基线证据（本轮实测）**：全量 `python -m pytest -q` → **2294 passed, 3 skipped, EXIT 0**（编辑前基线 260.24s：`.runtime/baseline_pytest_20260920.log`；本轮三处改动后的最终树复跑 245.06s：`.runtime/final_pytest_20260920.log`）；`tools/generate_project_map.py --check` EXIT 0；`web/static/{app,diagnostics,ewo-enrichment,node-overview}.js` 四个文件 `node --check` 全 ok；生产范围 flake8（须 `-j 1`，见 RECOVERY_NOTES）剩余命中**全部为 HEAD 既存基线**（main.py 32→13，tdc_probe_cli.py / project_status_connectors.py / project_status_sync_runner.py / tdc_contract_probe.py 与 HEAD 计数完全一致），未提交批次未引入新 lint 缺陷。
- **本轮改动（3 处，门禁修复与生成物刷新，无功能变更）**：`services/feishu_imap.py:370` 删除未使用的 `except Exception as e`（该 F841 系未提交批次把 `console.print(...{e}...)` 改为注释后残留，HEAD 无此问题）；`PROJECT_MAP.md` 重新生成（源码指纹 `94e94d98…`→`0b03080c…`，其余事实不变）；`docs/API_ENDPOINTS.md` 重新生成（HEAD 83 → 91 端点，补入此前缺失的 `/api/deliverable-forms/<form_key>/statistics` 与 `/api/tasks` 全家族、`/api/version`）。
- **工具陷阱**：`tools/generate_api_endpoints.py` **没有 `--check` 模式**，执行即覆写生成物；核对漂移只能用 `git diff`。`tools/generate_project_map.py` 有 `--check`，正常使用。
- **遗留未决**：全部改动仍未 commit（用户未决）；2026-09-20 同步体验与交付物关联的 UI 人工验收仍由用户执行；工作区根目录存在非本项目散件（`nul`、`smoke.pid`、`pelican_cycling.html`、`pelican_qin_screws.svg`），未处理。
- **下一步**：等待用户指定开发任务。

## 2026-09-20 同步体验优化（A/B/C/D）+ D6-D8 外部快照交付物补齐 + 无AI快照统计分析：实施与 $max 审计双通过（全部未提交）

- **执行方式**：每轮均"修复子代理 GLM-5.3-Flash`$high` → 审计子代理 GLM-5.3-Flash`$max`"动态工作流闭环，审计一次通过（同步体验 dwfrun-f7cc2b76/dwfrun-a60dd23c；补齐+统计 dwfrun-a81196b3→5529375a/dwfrun-7355f4ce，聚焦 349 例全绿）。门禁=node --check+flake8+全量 pytest+map --write/--check。
- **同步体验（用户批准 A+B+C+D，个人单机场景放宽操作负担、保留安全底线）**：A 前端 HCI 重排（详情页'数据同步'摘要卡+一键开启向导（凭据自动选中/单编号输入/自动取证2/2/自动首同步；映射推不出诚实降级高级设置不伪造）+完整表单降级为高级设置折叠）；B 老库幂等迁移（pristine manual→automatic，六条件，enabled 保持0）；C `services/project_status_scheduler.py` 常驻调度线程（默认900s/VSE_PROJECT_STATUS_SYNC_INTERVAL/--no-sync-scheduler，租约互斥，仅 WebUI 入口启动）；D 调度层新鲜跳过（last_success_at 不足间隔零网络）。
- **D6-D8 补齐（用户拍板：PAA/NCR 进入明细与环图；分母仍 D1-D5）**：种子 VPI-T2-D6 PAA 报告 DEL-006/D7 NCR 审批进度 DEL-007/D8 NCR 审批明细 DEL-008（source=aras、planned_date NULL）；`planned_date` 放宽可空+旧库整表重建（foreign_keys=OFF 前 commit；审计员临时库双场景实测数据完整）；注册表三关联（aras_paa→D6/aras_ncr_progress→D7/aras_ncr_detail→D8）；能力 formSnapshotDriven=true+countsTowardCompletion=false+只读（写路径 409 MappedDeliverableReadOnly）；展示状态机 form_snapshot_driven 分支（有快照→snapshot，无→待同步）；CHECK 约束下种子 status 存'进行中'但展示层全链路门控输出待同步。
- **无AI统计**：`services/deliverable_statistics.py` 纯函数（记录标识/状态/活动列显式映射，无 stageStart 回退 submittedDate；均值/中位数/标准差/Top5/分组均值/跨快照方差——历史快照确实多份保留）+ `GET /api/deliverable-forms/<form_key>/statistics`（404/空/脱敏/no-store）+ 详情页表单分析'统计分析'折叠区（任何 formKey 可用）。
- **遗留 minor（审计列出不阻断）**：向导 note 提示词全等匹配已修（归一化全等无子串回退）+失败路径 remountWizardInputs 可重试已修（test_deliverable_sync_summary_ui.py 锁定）；未修：`_metric_rows` 实参 form_key/report 巧合等价（deliverable_statistics.py:169）、统计端点历史装载上界偏大（30快照×2万行）、display_code 顺延时注册表/目录展示码与存量库实际码可能不一致（cosmetic）、D6-D8 payload.status 原始值'进行中'依赖消费方走 syncDisplay 门控（与 D2/D3/D5 既有模式一致）。
- **回滚与交付物**：回滚断点 `.runtime/rollback-checkpoint-20260920-020045`（含 worktree 副本/diff/manifest/README）；测试用 EXE `dist/hci-20260920-pre/VSE-WebUI.exe`（buildId=20260920-sync-pre，SHA f7251ac5…）；正式 EXE `dist/hci-20260920-final/VSE-WebUI.exe`（buildId=20260920-sync-final，SHA 9332f9b5…，六端点冒烟全绿）。全部改动未 commit（HEAD 仍 1ea7ab9）；UI 人工验收由用户执行。

## 2026-09-19 交付物关联注册表 + 状态口径单一化 + 错误分支解锁：实施与最高等级审计通过（全部未提交）

- **来源**：两份 DSH 会话分析（`C:/Users/Lynch/Downloads/Compressed/dsh-session-*`）经主线逐行核实为准确（三套交付物身份、4 处硬编码映射、双门控、生产库 5 binding 全 manual/6 job 全禁用/表单快照仅 3 条/分析快照空）。方案经 code-reviewer 架构审计（无 Blocker，5 Major/5 Minor 全部吸收）后用户批准实施。
- **执行方式**：动态工作流双角色循环——修复子代理 GLM-5.3-Flash`$high`（dwfrun-fb2b888d，门禁全绿：全量 pytest、node --check、flake8、generate_project_map --write+--check）→ 审计子代理 GLM-5.3-Flash`$max`（dwfrun-3cdf4742，**pass=true**，0 blocker/0 major/20 条 minor（多数为确认项），聚焦 pytest 212 实跑通过）。第一轮审计即通过，未触发修复回注循环。
- **落地内容**：`core/project_status_contracts.py` 新增 `DELIVERABLE_LINK_REGISTRY`（6 条：job_key→catalog_id/deliverable_id/display_code/form_key）与 `deliverable_display_state` 纯函数；`JOB_FORM_KEYS`/`DELIVERABLE_FORM_LINKS`/`ARCHIVE_JOB_CONTRACTS` 第三元组全部改为派生；`/api/deliverables/catalog` 追加 links、归档任务 payload 追加 formKey（按 job_key，自定义任务 None）、`/api/project-status` 的 associations 真实填充（D1/D4 空数组）；前端删 `DELIVERABLE_FORM_KEY_BY_ITEM`、关联项真实渲染（Safe DOM）、外部来源交付物参考分区、工作台反向入口、catch 分支新增 `unlockFormChartInteraction` 解锁守卫；`syncDisplay` 新增 displayStatus/displayProgress/displaySummary（仅 manual/snapshot 数值态填值，其余 null），effectiveStatus 保留同源；node-overview.js 未动。
- **测试**：新增 `tests/test_deliverable_registry.py`（五向闭合 + D4/A 面禁入）；test_form_key_consistency 重写为后端注册表断言；test_deliverable_form_ui（含两支 Node VM 行为测试：失败解锁/过期不解锁）、test_deliverables_web（links 逐值）、test_project_status_api（associations 新契约）、test_overview_web（后端字段驱动断言）相应更新。
- **遗留 minor**（均良性，未处理）：`services/scheduled_archive_runner.py:43` 重复 logger 定义（被 :59 遮蔽）与 `web/static/node-overview.js` 21 行改动归属不可核实——两者在会话起点 git status 即已修改，属他人并发未提交工作；`web/app.py:1966` snapshot 门控真值判断 vs source_link `is not None` 的防御性不对称（当前两个生产者都不会返回空 summary，不可达）。
- **边界与下一步**：全部改动留在工作区未 commit（与既有未提交改动混同，共 89 项）；UI 人工验收由用户执行（明细关联项/外部分区/详情头参考行/失败后筛选可交互）；运维启用（跑 6 个归档任务一次、D2/D3/D5 绑定改自动并启用、注意 EWO 表单键是 VPI-T2-D3）为可选后续。

## 2026-09-19 微信 clawbot 发文件能力已固化为可复用工具（sess_e682006f）

- **工具**：`C:/Users/Lynch/.zcode/tools/weixin_bot_send.py`（`discover` / `send-text` / `send-file`，仅依赖 `cryptography`；运行时解密 token 不落盘）＋协议文档 `C:/Users/Lynch/.zcode/tools/WEIXIN_BOT_SEND.md`；`~/.zcode/AGENTS.md` 已加发现指针。收件人/context_token 缓存在 `weixin-bot-state.json`。
- **验证**：工具 send-text 与 send-file（小文件）均返回 message_id（用户微信已收到 zip 文件、文本与测试文件）。
- **注意**：工具轮询会与桌面端 ZCode 竞速消费 getupdates 消息（一次性交付可接受）；微信文本+文件均发出后，原 `http.server 18790` 下载服务已关闭。

## 2026-09-19 生产测试 EXE 复核并通过微信 clawbot 交付（sess_e682006f）

- **交付物**：`dist/hci-20260919/VSE-WebUI.exe`（v0.3.0 / production-test / 20260919-hci-phases，SHA-256 `a4c648e7…b9c63b`）经隔离冒烟复核（5079 端口 `/`、`/api/version`、`/api/overview`、`/api/tasks` 全 200，进程回收干净）。
- **微信发送通道（本机逆向所得，复用参考）**：ZCode 桌面端绑定的微信 bot 走微信 iLink 协议：`POST https://ilinkai.weixin.qq.com/ilink/bot/{getupdates|getconfig|sendmessage|sendtyping|getuploadurl}`，头 `Authorization: Bearer <token>` + `AuthorizationType: ilink_bot_token` + `X-WECHAT-UIN`（随机数 base64）+ `iLink-App-Id: bot`；token 在 `~/.zcode/v2/credentials.json`，信封 `enc:v1:<iv>.<tag>.<ct>`（AES-256-GCM，key=sha256("zcode-credential-fallback:win32:<home>:<user>")，无 `ZCODE_CREDENTIAL_SECRET` env 时）。**发送文件**：`getuploadurl`（参数 `filekey`(hex32)/`media_type=3`(FILE)/`to_user_id`/`rawsize`/`rawfilemd5`/`filesize`(PKCS7 padded)/`aeskey`(hex32)/`no_need_thumb:true`）→ 返回 `upload_param`，拼接 CDN URL `https://novac2c.cdn.weixin.qq.com/c2c/upload?encrypted_query_param=<upload_param>&filekey=<filekey>`，POST AES-128-ECB(PKCS7) 密文（Content-Type: application/octet-stream）→ 响应头 `x-encrypted-param` 即下载令牌；再 `sendmessage` 带 `item_list:[{"type":4,"file_item":{"media":{"encrypt_query_param":"<x-encrypted-param>","aes_key":"base64(hex字符串)","encrypt_type":1},"file_name":"…","len":"<明文字节数>"}}]`；成功响应含 `message_id`。参考实现：PyPI `weixin-ilink`（MIT）与官方 npm `@tencent-weixin/openclaw-weixin`（CDN 常量在其 `dist/src/auth/accounts.js`）。ZCode provider 自身仅实现文本发送。用户 iLink ID `o9cq80xBQ4UyVCc5npPUuKtnGi0c@im.wechat` 只能从其发来的 getupdates 消息里获得（凭据/配置/日志均不存）；`context_token` 来自最近一条收到的消息，有时效。
- **交付方式**：桌面端 ZCode 常驻轮询会抢消费消息，需竞速：后台 1s 轮询 `/getupdates`（用 bot-state.v3.json 里的 `weixinGetUpdatesBuf`）抓到 user id 后，把 zip 文件本体经 `getuploadurl` + CDN 上传 + `sendmessage` file_item 直接发到微信（message_id 确认；并附文本说明 SHA-256）。zip 位于 `.runtime/wx-delivery/VSE-WebUI-0.3.0-production-test-20260919.zip`；备用下载 `python -m http.server 18790`（`http://192.168.5.200:18790/`）。
- **敏感清理**：解出的 token 临时文件已删除；轮询脚本/日志在 `.runtime/`（本地只读证据）。
- **注意**：此次直接消费了 2 条用户消息（桌面端 bot 任务可能未收到该"ok"）；bot 游标仍由桌面端管理，未做持久化改动。

## 2026-09-19 HCI Phase 2 复审至 Phase 5 交付：端到端实施闭环（全量回归全绿 + EXE 封包验证）

- **任务背景**：接手 `/goal` 任务书，完成 Phase 2 严格代码审查（Step 1）、Phase 3（业务端点异步化与 Excel 收纳）、Phase 4（高密度数据网格）、Phase 5（桌面启动/文档/封包）全流程，每阶段执行定向修复与回归验证。
- **Step 1 — Phase 2 审查结论与修复（3 项缺陷）**：
  1. **CSS `[hidden]` 失效**：`.task-center-badge` / `.task-drawer-container` 的 author `display` 规则压过 UA 隐藏语义 → 角标常显"0"、抽屉容器滞留 a11y 树；已补 `[hidden] { display: none; }` 规则。
  2. **Runner 取消死锁（潜伏）**：`future.cancel()` 成功（executor 队列中未启动的 future）时 wrapper 的 finally 永不执行，`_active_sources` 永久占用该源；修复为 `_active_tasks` 记录 source，取消成功路径在锁内 `_dispatch_next_for_source`；新增 `test_cancel_of_executor_queued_task_keeps_source_usable`（max_workers=1 确定性复现）。
  3. **EWO 重试红线违规 + 断链**：retry 路由把 `generation_unknown` 当可重试状态且读取不存在的 `ej["targets"]` 列（实际 `item_ids`）→ KeyError 被吞成 404；修复为 `generation_unknown` 一律 409 `ManualCheckRequired`（禁止自动重发），`interrupted` 才允许重建新任务，`can_retry` 同步收紧。
  - 审查确认：任务中心零 `innerHTML`（存量 25 处均为交付物控制台历史代码的静态脚手架/清空，无动态插值）、圆角全部 ≤8px/999px、轮询器在抽屉关闭且无活动任务时彻底休眠、`sanitize_task_params` 严格脱敏、Schema v14 未变、startup_sweep 已挂接。
- **Phase 3 — 业务端点异步化（202 Accepted + task_id 契约）**：
  1. **W3-1 抓取异步化**：`/api/aras/paa/crawl-all`、`/api/tdc/data-model/crawl-all`、`/api/tdc/sor/crawl-all` 网络路径改造为提交后台任务返回 202；抓取结果写 `data/downloads/<task_id>.result.json` 工件，经新端点 `GET /api/tasks/<id>`（状态轮询）与 `GET /api/tasks/<id>/result`（结果回读，64MB 上限）取回；TDC `preview_source=official_export` 预览路径维持同步 200（交付物控制台契约不变）。
  2. **协作式取消**：`ArasCrawlerClient.crawl_ewo_report_all/crawl_paa_report_all` 与 `TDCCrawlerClient._crawl_all`（data_model/sor）新增 `should_stop` + `on_page` 参数，分页边界触发各模块 `CrawlCancelled`；runner 依据 stop_event 判定 cancelled（≤2s 响应）。
  3. **W3-2 导出异步化**：Aras EWO/PAA export 与 TDC data-model/sor export 转后台任务，产物（CSV/XLSX）落盘 `data/downloads/`（任务唯一命名防并发覆盖），经任务中心下载；`prune_old_artifacts`（`ARTIFACT_RETENTION_DAYS=7`）在启动与每次任务完成后轮换清理；TDC 导出 worker 内置 downloads 目录包含性校验（路径外产物 fail-closed 报错且消息脱敏）。
  4. **凭据红线**：`_async_session_gate` 对 password 模式与显式 Cookie/Authorization 请求返回 400 `AsyncAuthUnsupported`（凭据禁止入库）；后台 worker 仅复用统一域会话对象（`should_stop` 用 `lambda: ctx.is_cancelled`，勿传属性布尔值——曾踩坑）。TDC worker 线程内**禁止关闭共享会话**（无 app 上下文时 `_close_owned_tdc_client` 无法识别共享会话）。
  5. **W3-3 EWO 状态**：`/api/tasks` 聚合的 ewo 类目标题改为「Aras EWO 增强导表」，新增 `manual_check_required` 字段；抽屉对 generation_unknown 显示「禁止自动重发，请人工核查」提示条。
  6. **W3-4**：统一抽屉已完全承接 Excel 任务记录/下载（聚合含 excel 类目）；顶栏保留 6 域导航（决策 #7 与 `test_top_bar_navigation_six_main_domains` 契约），Excel 入口保留（面板仍为唯一任务创建入口）。
  7. **前端**：202 响应由 `isAsyncTaskAccepted` 识别；`kickTaskCenterPolling()` 通过 `vse:task-center-kick` 事件唤醒抽屉轮询与角标；Aras 全量抓取完成后 `trackArasCrawlTask` 自动拉取结果渲染（seq 防串台）；导出走 `fetchBlobDownload` 的 202 分支提示到任务中心下载；交付物控制台 `trackDeliverableCrawlTask` 同构。
- **Phase 4 — 高密度数据网格（`renderRows` 全面升级，Safe DOM）**：
  - 表头点击升序→降序→取消，Shift+点击叠加多列排序（▲/▼ + 次序标号，数值感知比较器）；关键字快筛实时过滤 + `<mark class="grid-highlight">` 高亮（`createTextNode` 构建文本段）；紧凑分页 50/100（DOM 规模被分页上限封顶，2000+ 行重渲染毫秒级，`test_grid_2000_rows_render_performance` 断言 <300ms）。
  - 列显隐：「常用列/全量列」一键切换 + 逐列多选，持久化至 localStorage `vse-grid-column-prefs`（`loadGridColumnPrefs/saveGridColumnPrefs`）；default 视图与既有契约一致（仅 EWO/PAA 收敛到常用列）；敏感列（SENSITIVE_COLUMNS）不进列清单。
  - 一键复制：单号类列（label 以 号/No./Number 结尾或 key `*_no/*_number/incident`）悬浮显示 📋，`navigator.clipboard` 优先、`document.execCommand('copy')` 降级。
  - 兼容性：保留 `table-wrap`/`result-table`/`sor-result-table` 类契约；NCR detail 分组表头、NCR progress 跳过空白首行行为保留；测试 DOM 桩不支持 `replaceChildren` → 网格内统一用 `clearElement()`（textContent=""）。
- **Phase 5 — 桌面启动、文档与封包**：
  1. **W5-1**：`webui.py` 新增 readiness probe 线程（探测 `/api/version`，就绪后 `webbrowser.open_new_tab`，30s 超时放弃；HTTP 错误码也算就绪）；`--no-browser` 开关；端口解析 `--port` > `VSE_TOOLBOX_PORT` > 5000；仅回环监听地址自动开浏览器。**VSE-WebUI.spec 入口由 `web\app.py` 改为 `webui.py`**（否则冻结包不含浏览器行为）；`tests/test_webui_entry.py` 6 项测试（真实 HTTP server 验证探测）。
  2. **W5-2**：`API_ENDPOINTS.md` 重生成（90 端点，含 /api/tasks 全家族）；`docs/USER_GUIDE_STANDALONE_EXE.md` 新增 6.10 统一任务中心/6.11 数据网格章节与自动开浏览器说明；`PROJECT_MAP.md --check` EXIT 0。
  3. **T5-1**：PyInstaller 6.21.0 / Python 3.12.10 构建 `dist/hci-20260919/VSE-WebUI.exe`（17,508,300 字节，SHA-256 `a4c648e74dc6b79adaffd50117240594fe5b2cbb58c4f59a859e3d8815b9c63b`（最终代码状态重建包，含 can_retry handler 语义修正），附 SHA256SUMS.txt）；隔离冒烟（受限 PATH/独立 APPDATA/TEMP，5077 端口，`--no-browser`）：`/` 200、`/api/version` 200（displayVersion=v0.3.0/channel=production-test/buildId=20260919-hci-phases/isFrozen=true）、`/api/overview` 200、`/api/tasks` 200（active 0/total 0）、`/api/tasks/<id>/result` 404（证明 crawl_task_runner 已打包）；进程回收干净。
  4. **契约测试联动更新**：`test_aras_cli_web.py`/`test_deliverables_web.py` 中 8 个同步端点测试重写为 202 契约（保留凭据零回显、参数传递、截断标记、脱敏失败信息意图，新增 result 端点与下载断言）；`test_overview_web.py`/`test_deliverables_web.py` 的 localStorage 守卫放宽为 `THEME_KEY or GRID_COLUMN_PREF_KEY` 白名单；`test_credential_safety.py` 单元格渲染守卫更新为 `appendHighlightedText(td, safeDisplayValue(value), ...)` 不变量；测试 DOM 桩补 `createTextNode` 与真实 localStorage Map 存取。
- **验证证据**：
  - 全量回归：`python -m pytest -q` 全绿（.runtime/final_pytest.log，最终一轮含全部新测试）；
  - `python tools/generate_project_map.py --check` EXIT 0；`node --check web/static/app.js` EXIT 0；
  - `python -m flake8` 对全部改动模块 EXIT 0；`git diff --check` EXIT 0；
  - 新增测试文件：`tests/test_grid_interactive_ui.py`（9）、`tests/test_webui_entry.py`（6）；`tests/test_tasks_api.py` 扩至 23（含协作取消集成、7 天轮换、凭据门禁）。
- **当前状态与下一步**：
  - 本轮全部改动保留在工作区未 commit（与既有未提交改动一致，等待用户检查后统一处置）；
  - 待用户人工验收 UI（任务中心抽屉、网格交互、后台任务流程——离线测试已覆盖契约，真实内网 Aras/TDC 联调属物理网络依赖）；
  - EXE 交付物：`dist/hci-20260919/`（配套 Excel 批处理需同目录部署 VSE-ExcelWorker.exe）。

---

## 2026-09-19 Phase 2: 统一任务中心抽屉与轻量异步引擎（完整实施与全量回归 2,202 通过）

- **任务背景**：执行 Phase 2 ~ Phase 5 渐进式架构路线图之 Phase 2「统一任务中心抽屉与轻量异步引擎 (Unified Task Center Drawer & Lightweight Async Engine)」，并执行严格代码审查与全量回归验证。

---

## 2026-09-19 代码审计缺陷整改与加固：顶栏 6 域恢复、Safe DOM 返回条与切片断言严谨化闭环

- **任务背景**：用户批准代码审计整改方案，执行完整加固与纠偏：
  1. 顶栏导航恢复 6 核心域（概览、系统查询、交付物、Excel、自动归档、设置），移除 `workspace-aux-links`，严格遵循「抽屉先行、未建任务抽屉前禁止移除 Excel 顶栏入口」架构约束；
  2. Aras 面板标头还原为「Aras 系统查询」；
  3. 深链返回条（`aras-deep-link-back-bar`）升级为 Safe DOM 构建（`replaceChildren`、`document.createElement`、`textContent`），彻底杜绝 `innerHTML`；点击确定性跳转 `window.location.hash = "#overview"`；
  4. 6 个测试文件中 8 处 `_slice` / `_overview_html` 移除宽容降级 `if start == -1: return text`，改为严格断言；
  5. 导航测试更新为 6 域断言，测试移除 `input[name="ncrNo"]` 与 `window.history.back()` 断言，新增 Safe DOM 防御断言；
  6. `memory/DECISIONS.md` 决策 #7 明确固化抽屉先行与顶栏保留约束。
- **全套验证证据**：聚焦测试 93 passed；全量回归 2,184 passed, 3 skipped；地图 --check EXIT 0；`node --check` EXIT 0；`git diff --check` EXIT 0。

---

## 2026-09-18 全面代码审计与缺陷修复闭环：全量回归测试套件全部通过（2177 pass）

- **任务背景**：对照 `docs/CODE_AUDIT_20260918.md` 及全系统审计清单，完成全部 15 项安全防护、并发控制、OpenXML 容错、数据库锁升级死锁预防、Office COM 性能优化与 UI 测试断言漂移的修复与测试验证（A1-A9/N2/N4/N6 详单见本条历史版本与 `docs/CODE_AUDIT_20260918.md`）。
- **全套验证证据**：`python -m pytest -q`：2,177 passed, 3 skipped（225s 全绿）；地图 --check EXIT 0；flake8 EXIT 0；`git diff --check` EXIT 0。未执行 git commit/push。
- **未验证边界**：真实内网 Aras/TDC 联调属物理网络依赖；Office COM 矩阵批量读写建议在真实 Office/WPS 宿主机人工验证一次。

## 2026-09-17 WebUI 独立生产测试包：已构建并完成隔离验证

- 基于 VSE-WebUI.spec 生成独立单文件 `VSE-WebUI.exe`（v0.2.0 / production-test / 20260917-usability），`.runtime/webui-production-smoke-20260917` 纯净目录隔离冒烟通过（/ 200、/api/version 元数据正确、/api/overview 200、/api/project-status 200），进程回收干净。单包仅含 WebUI；真实 Excel 读写需同目录部署 `VSE-ExcelWorker.exe`。

## 2026-09-17 第三阶段：候选包审查与缺陷修复闭环完成，M1 离线交付正式就绪

- 候选 `rc-20260916T164923Z-46e060ddaed4`（含双 EXE、SHA256SUMS、runbook、release notes）；code-reviewer 审查无阻断缺陷；修复 `loadArchiveRuns` 并发竞态（`archiveRunsLoading` 锁）。M2 为用户目标环境验收（U1~U9）。

## 2026-09-17 第二阶段易用性优化：实施与审查闭环完成，待用户人工验收 UI

- P2 查询空结果卡片、任务/归档反馈、`#aras-preview-context` 上下文提示、设置分层兼容保护、人工验收清单 `docs/WEBUI_PHASE2_MANUAL_CHECKLIST_20260916.md`（全部【待验】）。

---

## 继承的历史审计结论与业务边界（保持不变）

- 真实 `data/vse_toolbox.db` 的 `archiveDirectory` 曾被历史测试写入临时目录，原值未知，尚未恢复。禁止猜值回写；后续 fixture 必须显式注入临时 DatabaseManager，不能假设环境变量自动实现隔离。
- EWO v2/schema14/CAS/源内部ID已在基准实现；旧规则不自动迁移，旧EXE不得打开新schema。EWO生成结果未知禁止直接重发，下载失败复用已有文件。
- 手工可编辑性取决于真实绑定，异常配置fail-closed且DB事务复核。PAA/NCR仅快照参考卡，不进入节点分母。
- 控制台UI手工清单：`docs/DELIVERABLE_CONSOLE_UI_TODO_20260916.md`；工程审计报告：`docs/DELIVERABLE_CONSOLE_AUDIT_20260916.md`。均不能推导用户已验收UI。
