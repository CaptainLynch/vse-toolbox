# Current State

> 本文件已按 2026-10-23 的上下文治理决定裁剪：只保留最近条目与"当前前沿"。
> 更早条目完整保存在 [归档文件](archive/CURRENT_STATE_ARCHIVE_20261023.md)。
> 恢复状态时**不要**再通读全文；先读本节，再按需查归档。

## 当前前沿补充（2026-11-18 · iBOM 切换影响评估：已修订，待阶段 0A 取证）

- **产物**：`docs/IMPACT_20261118_IBOM_SWITCH.md`（DSH 初稿 + 独立评审修订，§10 为 14 条勘误）。证据在本地
  `.runtime/ibom-impact/`（不入库；原始 HAR 含有效 usertoken，参数接口响应含集成配置值）。未改生产代码。
- **关键结论**：D5 可迁——DMM 有零件数模列表与 26 行签署矩阵，18 个部门人员列与 `COUNTERSIGN_COLUMNS`
  逐字一致；签署状态在「会签校对」节点任务上，不在签署栏。鉴权不是 SSO-only：平台默认 `NORMAL_LOGIN`，
  无人值守走 iBOM 本地服务账号；**密码错 3 次锁号且不自动解锁，登录绝不重试**。iBOM 有 PAA（MBOM 模块）；
  当前账号无 SOR。DMM 报表 xlsx 在 HAR 里已损坏，列未见。
- **已否定的路线**：用 `relationProcId` 查 iBOM 流程（它是 PDM 侧 14 位 ID）；假设 HAR「0 Cookie」即无 Cookie
  （Chrome 脱敏导出剥离了 Cookie）；从 HAR 恢复导出 xlsx（二进制被文本化，不可恢复）。
- **2026-11-19 阶段 0A 实测（评估 §11）**：DMM 报表（`partDigitalModelChange/exportReport.api`）与
  `tdc_data_model` 47 列**只差第 0 列**（`实例号`→`序号`，值是行号），零件级、带「(未签)」与计数；签署日报改列名后
  43/43 单可解析。零件列表 = `loadEntity` + `businessType:"partDigitalModel"`；DMM `recTypeId=585`，会签节点按人拆任务。
  单号查询 `CHANGE_CODE LIKE` 可用。口径差异：iBOM 计数按「人」去重（TDC 按「人次」）、新状态词（草稿/退回/取消）、
  架构件项目名 `TRA_2.0` 不带 `Ar-`。**不要把 `序号` 别名成 `实例号`**（会污染身份键）。
- **2026-11-19 双源方案**：`docs/PLAN_20261119_IBOM_DMM_DUAL_SOURCE.md` 已定稿并过开工前评审（§12 R1–R11），
  决策见 `memory/DECISIONS.md` 同日条目。评审要点：项目状态同步是**列表接口行**（英文键），iBOM 行需一分为二
  （列表形状 + 官方行按 `(流水单号, 零件号)` 补齐）；单记录绑定只认 `incident`，iBOM 单只能聚合绑定；
  iBOM 侧筛选需本地套用，未取证的键 fail-closed；SSO 跳转链未取证。**尚未动工**。
- **2026-11-20 阶段 0B 取证（免 Python 工具 `tools/ibom_phase0_probe.html`）**：生产只用归档任务 `tdc_data_model`，
  筛选 `projectModel=AR-C`、`section=车体科`；D5 项目状态绑定未配置。TDC 9 张单（全 Ar-C/车体科）与 iBOM 43 张
  **无交集**；iBOM 无 `Ar-C` 项目名（`TRA_2.0` 属底盘科）。方案已更新 §0.2/§0.3（新增 Q7 iBOM 项目名对照、
  Q8 本期只做定时归档）与 §3.4（`projectModel` 忽略大小写精确、`section` 精确）。
  `ibom_sso_chain.ps1` 首跑在第一跳报「不能对 Null 值表达式调用方法」：`$null | ForEach-Object` 仍执行一次，
  已修（2026-11-20.1），待重跑。
- **2026-11-20 SSO 跳转链已取证**（PS1 2026-11-20.1 重跑成功）：iBOM `/fwPlatform/ssoAuth/login.api` 302 →
  `account.sgmw.com.cn` Keycloak 认证域 `common`、`client_id=ibom-front`、回调 `/fwSecurity/ssoAuth/login.api`；
  登录表单与 TDC 完全相同。iBOM 由服务端换 code，客户端只跟随跳转后调 `checkToken`。方案 §3.3 已更新。
- **2026-11-20 开工**：Q7 不做项目名对照（只认 `Ar-C`）、Q8 本期只做定时归档。阶段 1 代码完成：
  `services/ibom_auth.py`（五步登录，复用 `tdc_auth._parse_login_form`，密码只发一次、失败不重试、逐跳校验主机）、
  `services/ibom_client.py`（MD5 头、成功判定、`checkToken` 空体重试一次、DMM 计数、报表导出内存返回），
  测试 `tests/test_ibom_auth.py`/`test_ibom_client.py` 29 passed；`tools/ibom_login_check.py` 供真实账号验证。
  统一登录页不加 iBOM。
- **2026-11-20 阶段 2 完成**：表头变体、`services/data_model_dual_source.py`（读入/筛选/合并）、归档连接器接入
  （TDC 完整后才登 iBOM；失败 → `dual_source_incomplete` 不发布快照）、`dimensions.sourceSystem`、诊断闭集登记。
  开关 `VSE_IBOM_DUAL_SOURCE`（缺省关闭）。测试 30 passed，相关回归 602 passed。方案 §13 有实施记录。
- **2026-11-20 阶段 3 完成**：`取消` 入剔除集；签署日报认 iBOM 状态词（已发布/取消/草稿/退回）、阶段先看状态、
  iBOM 单按角色列人次自算计数；`load_source` 从 `dimensions.sourceSystem` 带来源。测试 7 passed，回归 658 passed，
  1 个既有失败（`test_import_scan_rejects_dir_outside_roots`，撤掉改动同样失败）。
- **2026-11-20 阶段 4 完成**：签署日报本地导入认 iBOM 表头（`1113aed`）；归档手工导入（`services/ibom_manual_feed.py`
  暂存 30 分钟单次、插件 `POST /api/p/scheduled-archive/ibom-manual-feed`、数模任务卡片面板、连接器优先用暂存）。
  回归 1043 passed，2 个既有失败（`test_import_scan_rejects_dir_outside_roots`、`test_glossary_terms_gate`，均与本期无关）。
- **下一步**：阶段 5 真机验收（用户侧）：① 内网跑 `tools/ibom_login_check.py`；② 通过后设 `VSE_IBOM_DUAL_SOURCE=1`
  重启，观察连续 3 个工作日归档；③ 每天抽 3 张 iBOM 单与界面核对。需 Windows 打包（onedir zip + 插件 0.2.0）。
- **改了什么**（均在 `plugins/sign_daily/`，`refactor/ux-v2`）：
  ① 图表配色：配置键 `chartColors`（三图各 `bar`/`special`，只认 `#rrggbb`，默认值与 `chart.js` 的 `PALETTES`
  由测试钉住一致），页面「图表配色」面板含四套预设与自定义取色，改色只在前端用已加载的 `result.charts` 重画；
  ② 本地导入（`/import-form`）开始计算日变化：新增 `manual_baseline.py`（`ManualBaselineStore`，迁移版本 5，
  自有表 `manual_baseline_meta/rows`），基线优先级「本次指定 > 固定 > 自动」，指定/固定基线不受最长间隔限制、
  不可用时不回退自动；`rules.daily_progress` 逐单对比（待签人数 = `required - signed`），正文与页面新增「每日进展」段，
  仅手工模式渲染；新路由 `GET manual-baselines`、`POST manual-baselines/pin|unpin|delete`。
- **边界不变**：手工导入仍不读不写 TDC 共享快照、配置、长周期结论，仍无 `.eml`；离线 CLI
  `tools/sign_daily_local_report.py` 未改（零写库、不算日变化），其 docstring 里「与插件手工导入同一契约」已不准确，待修。
- **审计修复（同日）**：`/import-form` 拒绝晚于今天的数据截至日期（手填未来日期会触发保留期清理删旧基线、
  并使之后的导入全判为旧数据；钩子 `_import_today`）；进展首句改称「总签署率（已签/应签）」以区别于汇总段的
  会签签单率；所选文件的修改日期与填写日期不同日时页面提醒（`fileDateHint`，只提醒不改日期）。
- **证据**：签署日报 10 个测试文件 360 passed（审计修复后；首次提交时 358） / 3 skipped / 1 failed；失败项
  `test_import_scan_rejects_dir_outside_roots` 在改动前同样失败（Linux 上没有 `C:/Windows`，得到 `E_DIR_MISSING`）。
  Linux 容器内用 Chromium 实走：连续两天导入 → 自动对比、进展段、预设换色重画，无控制台错误。
  `generate_project_map.py --check` 通过；改动文件 flake8 无新增告警。
- **0.7.0 基线文件（同日）**：本地导入区新增「指定基线文件」（选择文件上传，或粘贴任意本地完整路径——用户决定
  不限扫描目录；只读 `.xlsx`/`.txt`、有大小上限）。校验通过后原字节备份到插件数据目录 `baseline-backup/`
  （服务端生成文件名、原子写、只留一份），对比永远读备份；原文件不在/被改只提示并照常对比，备份也没了才不对比、
  不回退自动。记录在单行表 `manual_baseline_file`（迁移版本 6）；`FileBaselineAdapter` 把备份包装成「那一天的
  全量快照」，compose 未改。与「固定」互斥。新路由 `GET/POST manual-baseline-file`、`POST manual-baseline-file/clear`，
  含本机路径的 GET 也过 `local_guard`；正文（会发给别人）不带本机路径。审计时去掉了对重解析点属性的拒绝
  （OneDrive 按需文件会被误挡）。证据：386 passed / 3 skipped / 1 failed（同一既有失败）；Chromium 实走
  指定 → 对比 → 原文件改名 → 备份删除四种状态。
- **0.7.1（2026-11-17）**：按所有者要求去掉 Excel 代读的部署授权文件门槛（见 DECISIONS）；页面导入遇到加密 xlsx
  且代读未开时，提示改为给出两条出路（另存为 txt / 勾选代读后放进扫描目录），共用文案 `IMP.ENCRYPTED_TEXT`
  与离线 CLI 保持不变。新增使用说明 `docs/manual/签署日报_每日进展与配色使用说明.md`（截图在
  `docs/images/sign-daily-guide/`，Linux 测试机样例数据）。证据：383 passed / 3 skipped / 1 failed（同一既有失败）。
- **未做**：Windows 真机、加密 xlsx 代读路径（含「代读读备份目录」是否被代读的路径限制拒绝）、UNC 路径、
  签名 `.vsepkg` 打包、全量回归。
- **下一步**：Windows 上跑全量 pytest 与真机验收，再用 `tools/build_plugin_pkg.py` 出 0.6.0 的 `.vsepkg`。

## 当前前沿（2026-11-03 · DSH 第 3–7 波已全部集成到 refactor/ux-v2；第 8–10 波需真实环境）

- **DSH-V2-03 本轮（2026-11-03，`codex/dsh-v2-03-transport` @ c41dde8，tip `a18b2c3`；已快进合入
  `refactor/ux-v2` = `a18b2c3`）**：主体替换流程
  （env 注入 → pywebview 桥 → 浏览器 claim → `window.request` 重开 → `session-recover`）早在 `f51c76c`
  已集成，本轮只补真实残留泄漏与证据：① `run_window` 的 pywebview `ImportError` 分支原先直接打印原始
  异常文本（含旧 `?boot=` URL / 注入票据）→ 统一走 `_redact_window_error`；② 该脱敏原先只换整串 URL 与
  精确票据，异常文本只带 `?boot=<ticket>` 片段或少尾斜杠时仍泄漏 → 改为三层（整串 URL → 查询串白名单取值 →
  键锚定正则兜底），并对裸值替换加 16 字符门槛；③ `_load_webview` 的非 `ImportError` 加载失败（缺 DLL/权限）
  穿透成裸 traceback、退出码 1 → 脱敏后按「pywebview 不可用」返回 3（走既有 Edge→浏览器降级），
  非预期类型另保留**脱敏后**的完整 traceback；④ **用户批准扩 scope**：`vse_boot/__main__.py` headless 分支
  原先 `log(f"就绪：{url}")`，「新启动器 + 旧 app」时 `?boot=` 票据落盘 `state/launcher.log` → 改为只记基地址
  （仓库内无脚本消费该行）。
  证据：基线 **196 passed**；导入失败红态先在**泄漏断言**处变红（`ticket not in output`）；聚焦 8 套件
  **208 passed / exit 0**（worktree 84.12s；合并后源工作区复跑 208 passed / 98.11s）；**全量 4216 passed /
  7 skipped / 1 warning / exit 0 / 792.88s**（`full-suite-worktree.txt`）；`git diff --check` exit 0；
  变异检验（Edge URL 注入 `?boot=leak`）claim 用例 exit 1 变红、文件 sha256 还原一致。
  证据目录 `E:\project\vse-toolbox-wt\_logs\DSH-V2-03-20261103\`。合入方式：`merge --ff-only`，源工作区
  无关脏改动（`memory/RECOVERY_NOTES.md` +6 行指纹根因）与 8 个未跟踪项逐字保留（patch 先存后施，
  numstat 复核 6/0）。
  **限制**：未做原生 EXE/pywebview/浏览器/打包；`state/app-last-run.log`（app 子进程 stdout）无泄漏未证明——
  机制已实测（werkzeug 把 `GET /?boot=<TICKET>` 写进 logging 流，`spawn_app` 把该流重定向进该文件），
  但真实子进程端到端未跑；旧启动器兼容 `?boot=` 按契约 §8 保留，不能宣称旧版本零暴露；
  `PROJECT_MAP.md --check` 仍 exit 1（`vse_boot/`、`tests/` 不在 source 指纹范围，任务改动不可能造成该漂移，未刷新）。
  `flake8 vse_boot/supervisor.py` 的 5 条（E303×1、E704×4，L67-76 Protocol 桩）已核实在 `c41dde8` 同样存在；
  `flake8 vse_boot/__main__.py` exit 0。
  **顾问复核（Claude code CLI，`expert_advisor.py --provider claude`，claude-opus-5-5 / effort xhigh，
  run `6fc298db-7405-4061-b88e-4b393c55341d`，裁决 1/2/3 = adopted）**：判 pass、代码 diff 未发现阻断合并问题；
  采纳 Q1-2/Q1-3（非预期类型保留脱敏 traceback + NameError 回归）与 Q2-1/2/3（脱敏器 fail-closed、
  键锚定正则兜底、裸值 16 字符门槛），并补截断/`%3Fboot%3D`/不可解析 url/`__str__` 抛错四条回归。
  **其 F1「1→3 会永久降级」被本地证据推翻**：`_watch_window` 对**任意非 0 退出码**在 15 秒宽限期内即降级
  （`if code:`，L503），且全链路无「不可用」状态持久化——旧行为（未捕获 traceback、退出码 1）本来也在降级。
  **其 E2 疑点排除**：诊断包成员只有 `summary.md`/`events.jsonl`/`exceptions.json`/`manifest.json`
  （`core/diagnostic_recording.py:346-351`）+ `diagnostics.json`，不含 `launcher.log`/`app-last-run.log`/profile/转储。
  口径：验收第 1 条（票据不入 query/instance.json/常规日志/诊断）记**新链路「满足」、兼容链路「部分满足」**，
  剩余缺口：`state/app-last-run.log` 未端到端证明、兼容链路自身载体（§8.1 已接受，但日志面未被 §8.1 显式接受）。
  **引擎工作流 `wf-442bd00c-f741-453d-9274-f7c271d1263d` 已人工标 failed**（`r1:exec:plan` 长期
  `processing` + 过期租约 + 无法认领，重投风暴累计 24811 条事件；用户批准后直接改协调库两行为 failed，
  确认事件增长归零；本任务成果由主控自建评审与 Claude 复核完成）。
- **refactor/ux-v2 = eccad2b**（第 7 波合入 + 地图）。各波集成全量：第 5 波 4104 passed；第 6 波 4164 passed
  + 1 条专家导航清单断言（21 新增「调度时刻」，465d540 修正）；第 7 波 **4203 passed / 7 skipped / 1 warning**
  （`E:\project\vse-toolbox-wt\_logs\wave7-integration-pytest.txt`）。逐任务状态与工作流 ID 在
  `E:\project\vse-toolbox-wt\_logs\wave4-state.md`，契约在同目录 `contract-*.md`。
- **第 5 波**：17 TDC 恢复链与统一退出（主控批准范围例外：web/app.py 续期工厂注册 TDC；SessionBadges 读取
  后端 state——renewing→正在恢复、failed/cleared→需要重新登录）；20 固定时刻槽接入唯一调度器（SlotStore 下沉
  services/schedule_slots.py；无 project→交付物映射，按 ADR-0001 派发当前库全部启用绑定；暂停打断槽 failed 不重试）；
  34 release 门禁（版本/HEAD 内容哈希/--since 启动器覆盖/有 .git 但 git 报错一律 FAIL）。
- **第 6 波**：21 调度时刻页面与 binding 读写路由；23 日报 08:30 生成（services/schedule_jobs.py 作业注册表，
  sign_daily 注册 handler，只生成不发送，按槽 INSERT OR IGNORE，刷新等待 13 分钟 < 900 秒租约）；30 原件留存
  核实（追踪关系已持久化，补集成测试与历史原件页签）；31 自检新增连接器/调度两项（not_run/unable/fail）。
- **第 7 波**：28 托盘通知（应用写 layout.state_dir/notifications/<id>.json，托盘轮询消费复用 TrayHandle.notify，
  sent 账本去重）；40 真实 DOM 可见文案门禁——主控**修正 8 处产品文案**（“自动归档快照”→“自动归档”、
  “映射取证”→“映射核对”）而非放宽预算，现预算 20+1=21 ≤ 23；43 两个更新页的用户可见更新记录。
- **未解决的遗留**：classify 未读 aras_auth recovery_code；connectors 经模块级 bind_session_renewal；
  lease_lost/乐观锁冲突失败不发托盘通知；托盘侧消息写入与发布端重复约 20 行；TDC xlsx 写入失败被连接器吞掉
  （清单不含该文件但运行记成功）；原件缺失检测按目录粒度；core 常量“外部快照驱动…”仍是登记的已知违规；
  #p/deliverable-forms/* 仍可直开专家页。
- **下一步（需要用户/真实环境）**：35 真实 exe 端到端（首日日报与项目流程）、36 用户文档（依赖 35）、
  37 真实办公室用户试用——都不能在本机自主完成。真实内网 Aras/TDC 登录与续期仍为“待验证”。

- **第 3 波（96bc518 → refactor/ux-v2，地图 9ee8e68）**：03/10/11/13/15/18/22/27/38/41 全部集成，全量
  **3947 passed / 7 skipped / 2 warnings，exit 0**（`E:\project\vse-toolbox-wt\_logs\wave3-integration-pytest-final.txt`）。
  22 的 DSH 评审三次因环境崩溃无裁决，由主控人工复审放行（宿主模块按 URL 动态载入 sign_daily/chart.js，
  失败降级为无图预览；记为已知耦合）。
- **第 4 波（5d42388 → refactor/ux-v2，地图 048b3e2）**：04/05/16/19/29/32/39 + 27b 全部独立评审 pass 后集成，
  全量 **4038 passed / 7 skipped / 2 warnings，exit 0**（`_logs\wave4-integration-pytest.txt`）。主控补修要点：
  05 补契约第 4 条负向用例；16 复审两项阻断（禁跨账号复用会话、爬虫 403 不续期——`services/aras_crawler.py`
  主控批准的只增范围例外 status_code）+ medium 竞态（每次尝试重核绑定）；19 只读路由不外露 leaseToken；
  04 bridge 成功也清地址栏旧票据。
  - 遗留：session_recovery.classify 未读取 aras_auth 的 recovery_code（V2-15 文件）；
    project_status_connectors 经模块级 bind_session_renewal 取协调器；#p/deliverable-forms/* 仍可直开专家页；
    设置页会话时间未走 time-format.js；有交付物无节点时环图/明细仍显示暂无数据。
- **OOM 根因（已修，DSH-V2-27b）**：Excel Worker 空闲退出由宿主内控制器驱动，宿主/pytest 退出后
  `tools/excel_worker_cli.py run` 子进程永不退出——全量测试后残留 25 个约 530MB 进程，提交内存 38/46GB，
  DSH 执行者随之 OOM/崩溃。修复：控制器传 `--parent-pid`，Worker 持父进程句柄判活后优雅停止；
  tests/conftest.py 默认把控制器模块的 subprocess 换成代理（Popen 惰性替身），真实子进程用例标
  `real_excel_worker`。再遇执行者 OOM 先查 `excel_worker_cli` 残留进程。
- **第 5 波（dsh/wave5-integration，工作树 vse-toolbox-wt/wave3-integration）**：20 已评审 pass 并合入
  （SlotStore 下沉 services/schedule_slots.py；主控裁决：基线无 project→交付物映射，按 ADR-0001 固定槽派发
  当前库全部启用绑定；暂停/停止打断的槽 failed 不重试）。17（wf-42c32e2f）、34（wf-34c54ab2）执行中。
  契约草案在 `vse-toolbox-wt\_logs\contract-*.md`，状态在 `_logs\wave4-state.md`。
- **执行纪律**：执行者计划写明“不要运行全量 pytest”（否则撞 15 分钟超时）；执行者并发 ≤2；
  主控先提交再发“只验证”复审可规避指纹抖动。
- **下一步**：17/34 收尾 → 第 5 波全量 → 第 6 波（21/23/30/31）→ 第 7 波（28/40/43）。
  第 8–10 波（35 真实 exe 端到端、36 文档、37 真实办公室用户试用）需要真实环境与人员，不能自主完成。

## 第 1 波收尾（2026-11-01 · V2-01/44/45/46/47 + 遗留修复）

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
- **（已完成）**第 2 波见上；
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
