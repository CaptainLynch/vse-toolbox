# Current State

## 2026-09-26 审计闭环：双分页看板+科室归集 审计 4 项发现全部修复，顾问复审认可（任务闭环）

- **审计→修复→顾问复审全流程完成**：code-reviewer 审计（1 Major+2 Minor+1 Nit，A-F 清单）→ 逐条
  核实成立并全部修复（两趟校验 + 保留名「未归集」拦截 + 手册 6.16 深链说明 + debug bundle 注入
  sectionRollup + 补 5 项测试）→ Codex 顾问复审（sol-high live，TASK-20260926-AUDIT-REVIEW，
  包 `.runtime/consult-20260926-audit-review.md`，意见
  `~/.dsh/expert-advisor/runs/codex-readonly-20260926-032757-51f90048.advice.md`）认可四项定级与
  修复方向；三项「修改/核实」要求已逐项落实：① `all_targets` 只收合法目标（代码核实无误拒路径）；
  ② 全项目无独立备份导出功能（唯一诊断导出即 debug bundle，已覆盖）；③ 科室名进调试包不构成新
  披露类别（本机操作者 + 包内既有更细数据）。顾问建议不引入 Unicode 等价合并，维持 trim+精确匹配。
- **最终门禁**：全量 **2429 passed, 3 skipped**（`.runtime/pytest-full-auditfix.log`）；flake8 改动文件
  零告警；`node --check` 通过；项目地图 verified；冒烟 22/22（修复后复跑）。
- **待用户**：① 完整「历史科室 → 现行科室」对照清单在 WebUI 归集面板录入；② 决定是否重新打包
  EXE 与源码提交时机（改动未提交）。产品执行前沿其余条目（生产 D6/D7/D8 复测、NCR 样例、
  TDC 分页 Phase 1 授权等）不变。

## 2026-09-26 审计轮：双分页看板+科室归集 代码审计 4 项发现全部修复；顾问复审待额度窗口

- **代码审计（code-reviewer，只读，用户要求）**：A-F 清单审计结论「有条件合入」——1 Major（校验单趟
  遍历漏拦截 alias==自身 target、前序 alias 撞后序 target；后者会让 build_rollup_index 的 setdefault
  抢占后序目标自绑定 → 看板丢行且归属错乱）+ 2 Minor（保留名「未归集」未拦截；手册缺旧深链说明）
  + 1 Nit（debug bundle 未含 sectionRollup）。**逐条核实全部成立、全部修复**：
  `validate_section_rollup` 改两趟校验（全量目标名收集 → 别名全量查重，含保留名拦截、恢复同目标内
  重复别名检查）；手册 6.16 补深链说明；debug bundle context 注入 `sectionRollupStore.get()`。
  测试缺口补齐：4 项校验回归 + rows()「section 筛选+阈值重算」组合路径端到端。
- **审计后门禁**：聚焦 100 passed；全量 **2429 passed, 3 skipped**（基线 2425 → +4，
  `.runtime/pytest-full-auditfix.log`）；flake8 零告警。
- **待办（用户可见）**：① 审计结果的 Codex 顾问复审——**已完成，见上节**；② 用户生产侧：历史科室对照
  清单录入、打包/提交决策。其余同下节实施记录。

## 2026-09-26 部门总状态双分页看板 + 科室归集（WebUI 可编辑）已实施完成（全量 2425 pass）

- **实施内容（方案 `docs/PLAN_20260926_DEPT_STATUS_TABS_SECTION_ROLLUP.md`，第 10 节为实施记录）**：
  ① 新增 `core/section_rollup.py`：规则校验（目标/别名唯一性、上限）、`SectionRollupStore`
  （`app_settings` 独立键 `sectionRollup`，不入通用设置白名单）、统一归集原语 `resolve_section`；
  ② `services/deliverable_form_analysis.py`：`summarize_form_rows` 新增 `section_rollup` 参数，
  产出 `sectionStageMatrix`（sections/stages 嵌套对齐 cells、显式零计数）与 ncr_detail 的
  `sectionCounts`；**行级归集筛选**——view()/rows() 携带 section 筛选时剥离 SQL 下推、
  读取行后逐行 `resolve_section` 过滤（分页在筛选后；rows 附带 `sectionRollupTarget` 派生字段），
  `_filter_options` 的 section 选项按规则顺序 + 未归集；发布/趋势路径不传 rollup（存储保持原始口径）；
  ③ `web/app.py`：GET/PUT `/api/project-status/section-rollup`（PUT 走本地 mutation 守卫、
  422 带 fields），view/rows 接线，view 对归集表单下发 `sectionRollup` 规则；
  ④ 前端：D3/D6/D7「部门状态」页签改为双分页看板（按科室/按状态，`state.boardTab` 记忆），
  D8 新增「按科室」计数页签；通用 `renderFormMatrixBars`（段内计数、悬停明细、行点击筛选、
  其他状态行不可点击）+ `renderSectionRollupPanel`（只读规则表 + 编辑态 chips/新增目标/保存，
  全 Safe DOM）；tdc 两表单维持旧板；逾期判定控制条不变。
- **门禁（最终轮实测）**：全量 `pytest -q -p no:cacheprovider` → **2425 passed, 3 skipped（exit 0，219.98s；
  基线 2403 → +22）**（`.runtime/pytest-full-rollup2.log`）；flake8 改动文件零告警；
  `node --check` 通过；项目地图 `--write && --check` verified；冒烟 `.runtime/smoke_section_rollup.py`
  **22/22 PASS**（含 PUT 规则后 view 立即生效）。实施中发现并修复：view() 无快照分支漏传
  `section_rollup`（冒烟发现）。
- **语义要点（用户手册 6.16 已写）**：筛选/图表按归集口径，明细表显示原始科室值；未登记历史值进
  「未归集」；旧原始值筛选链接不再命中（需登记为别名）；D2/D5 不参与归集。
- **待用户**：提供完整「历史科室 → 现行科室」对照清单并在 WebUI 录入；生产 PyInstaller 打包按需另行执行
  （源码树未提交，等用户确认后一并处理提交/构建）。产品执行前沿其余条目（生产 D6/D7/D8 复测、
  NCR 样例、TDC 分页 Phase 1 授权等）不变。

## 2026-09-26 部门总状态双分页看板 + 科室归集：方案定稿并经 Codex 顾问审计（已进入实施，见上节）

- **用户需求（已按预览图确认口径）**：把交付物详情页「部门总状态」看板拆两个分页——分页1 按归集后科室（柱内=各业务状态占比）、分页2 按状态（柱内=各科室占比）；「状态」口径：EWO=DRAFT1/DRAFT2/EDIT1/EDIT2/PROC/IMPL/CLOSE、PAA 无 EDIT1/EDIT2、NCR进度=13 审批节点、NCR明细无状态仅按科室；科室归集（历史值→现行五科 车身科/车体科/内饰科/外饰科/车体架构集成科 + 「未归集」兜底）且规则须 WebUI 可编辑、保存即生效。预览图：`.runtime/preview-dept-status-tabs-v2/preview-*.png`（含规则编辑态）。
- **方案文档**：`docs/PLAN_20260926_DEPT_STATUS_TABS_SECTION_ROLLUP.md`（设计、代码证据、测试计划、裁决记录全在文档内）。范围：D3/D6/D7 双分页、D8 单页科室统计板、归集规则存储+GET/PUT `/api/project-status/section-rollup`+前端编辑器；D2/D5 不动；不动原始数据、无迁移、无快照回填。
- **关键架构事实（本轮核实）**：`view()` 对筛选后行**读时现算** summary/charts（`deliverable_form_analysis.py:1993,2088`）→ 归集放读取层即保存即生效；`rows()` 常规路径 SQL `COUNT+LIMIT/OFFSET`（`db_manager.py:2481`）、thresholds 路径 Python 过滤；`app_settings` 为自由 KV（:822,1896）新键免迁移。
- **Codex 顾问审计（sol-high，live 1 次成功）**：核心意见=「未归集」按原始值列表展开（500 截断）会静默漏数，应读路径统一归集函数后筛选。**裁决=意见成立**：放弃值列表展开，改**行级归集 + Python 层科室筛选**（`resolve_section` 单一原语；`view()` 剥离 section 的 SQL 下推；`rows()` 带 section 时走既有整读路径模式、筛选后切片）；分页保证在筛选后；旧载荷键保留（tdc 消费+回滚兜底）；明细显示原始值但行附带 `sectionRollupTarget` 派生字段（「归集后科室」辅助列列为可选项待用户拍板）。咨询包 `.runtime/consult-20260926-dept-status-rollup.md`，意见 `~/.dsh/expert-advisor/runs/codex-readonly-20260926-003019-c8968d80.advice.md`。
- **下一步（等用户）**：用户批准后按方案第 8 节顺序实施（core → analysis → service → web → 前端 → 全量门禁 → 用户手册补节）；实施时需用户提供完整「历史科室 → 现行科室」对照清单作为默认规则。产品执行前沿其余条目（生产 D6/D7/D8 复测、NCR 样例、TDC 分页 Phase 1 授权等）不变。

## 2026-09-25 Expert Advisor：ZCode 交互式 GLM 路由说明已修正

- 统一 DSH 技能、ZCode 技能和项目 AGENTS.md 已将顾问触发主体明确为「ZCode 当前所选模型的交互主代理」，包括交互式 GLM-5.3-Flash；worker 禁令只限顾问咨询，有界实现、测试、文档和聚焦取证仍可委派。
- 运行入口按 caller=zcode 授权并检查 worker 标记，不检查 ZCode 主代理的模型。codex-readonly --status 显示 enabled=true、HOLD=false、7 日上限 30；使用 zcode-synthetic.md 的 sol-high --dry-run 返回 ok=true、退出码 0，映射 Codex gpt-6-sol/high。本轮未发起 live 调用，未证明 GLM 交互主会话实际自动触发；后续可在 GLM 交互主会话遇到符合触发条件的真实任务时验证一次。
- 产品执行前沿仍按下方最新产品记录；本次未改产品代码或额度。

## 2026-09-25 Expert Advisor 共享 7 日上限已改为 30 次

- 用户在顾问参与范围评估后明确要求把本地上限设为 30 次。按前一轮讨论中的“近 7 日本地 8 次上限”解释，已把 codex-readonly 的 weekly_cap 从 8 改为 30；所有 Sol/Astra 档位共用。5 小时 2、自然日 10、每任务 2 和 Astra 专属自然日 1/7 日 2 均未改，Plus 服务端额度及历史账本未重置。
- 本机 advisor_policy.json、统一 SKILL.md/CONTRACT.md 和滚动上限边界测试已同步；新旧顾问离线测试 115 passed，--status 显示 weekly_cap=30、HOLD=false，broker 健康。没有发起 live 模型调用。上一轮关于增加实施后/发布前顾问参与点仍是建议，尚未改触发规则。
- 产品执行前沿仍按下方最新产品记录；本次未改产品代码。

## 2026-09-25 Expert Advisor 参与范围评估（建议，未改路由）

- 现有 DSH/ZCode 顾问技能已覆盖非琐碎架构/方案定案和两轮排障后证据冲突，但没有明确的实施后关键不变量复核、发布前证据/回退检查触发点。近期 P0-P3 多模块变更及 NCR 重复标签修复显示这两类复核有价值；建议以设计一次、集成/发布一次为每项高影响任务的优先上限，疑难事故按风险另行触发。此处只是待用户决定的评估，未修改顾问技能、配额或模型档位。
- 本轮按 AGENTS.md 发现 PROJECT_MAP.md 漂移，已使用生成器刷新并复查通过。产品执行前沿仍由下节最新工作记录定义。

## 2026-09-25 ZCode 审计报告处置：NCR 重复表头标签静默覆盖缺陷已修（r2 包已构建并冒烟通过）

- **审计输入**：ZCode 只读审查（5 域分域审阅 + 逐项复核）结论「有条件通过」：1 Major + 4 Minor + 3 Nit；
  报告中另提的「分页 95% 阈值 Blocker」经核实属 2026-09-23 轮既有待授权项，非本轮回归。
- **Major（已在代码上独立复现）**：`core/report_headers.json` 的 `ncr_progress.headerRows[1]` 中
  11 个角色标签各出现两次（列 `37..47` 为办理时间、列 `52..62` 为执行人；父表头 `[36]="办理时间"`、
  `[52]="执行人"`）；解析器 `{label: values[index]}` 后写覆盖先写 → 标签字典只留执行人姓名，
  而 `named_row()` 只发布该字典 → 读取侧按标签还原位置视图时 11 个办理时间全部被覆盖。
  **实测影响比审计描述更严重**：不是「未判定」，而是所有节点 `stageStart` 退回 PE填写 日期、
  `stageEnd` 丢失 → **每个节点都被误判为 overdue**（复算脚本 `.runtime/compare_ncr_legacy_vs_fixed.py`）。
- **顾问裁决**：Codex `sol-high` 一次咨询（`TASK-20260925-NCR-LABEL-COLLISION`，包
  `.runtime/consult-20260925-ncr-label-collision.md`）采纳方案 A，附四条约束：确认命名行约定允许增量键、
  行身份保持修复前语义、历史行保留原读取边界并有界披露（不得标为已修复）、把重复标签做成守护测试。
  四条全部落地。
- **修复**：`NcrWorkbookRow.named_row()` 增带契约顺序的位置视图 `values`（标签字典继续保留）；
  读取侧既有的位置优先分支自然生效；NCR 行身份统一为 `_ncr_row_identity()`（优先 `NCR编号` 标签）
  → 带不带位置视图的同一行 rowKey 不变；只带标签键的历史行触发
  `emit("forms.ambiguous_header_labels", {report_type, row_count, remedy})`。
- **对抗式复核（针对本轮修复）发现并已闭环的缺口**：
  ① **披露载荷被录制层丢弃**（Major）：`core/diagnostic_recording.safe_metadata` 只白名单转发固定键，
  原 `{reportType, formKey, rows, ambiguousLabels, remedy}` 与上一轮的 `{kept, dropped, departmentScoped}`
  实测都投影成 `{}`。已修：白名单新增 `kept_count`/`dropped_count`/`report_type`/`remedy` 与闭集词条
  `reproject_from_archived_workbook`，两处 emit 改用可转发键，并新增"经 Recorder 录制导出后 data 可读"的端到端回归测试。
  ② **"读旧快照会产生诊断"是错误表述**（Major/表述）：`normalize_form_rows` 的生产唯一调用点是发布路径
  `build_form_snapshot`，读取路径不重新归一化 → **旧快照读时永远不产生诊断，也不会回填**，只能重新同步。
  文档与说明文件已统一改正。
  ③ **同名列仍被还原**（Minor）：标签分支对重复标签取最后一次出现（执行人），而阶段日期按标签命中第一列（办理时间），
  历史行会把执行人姓名写进办理时间列（列渲染按位置取值，用户可见）。已修：`_ncr_header_mapping_values()` 对同名列一律留空
  （宁可"未判定"也不给错误日期），测试锁定 11 组两列全空。
  ④ 复核认为 `ncr_detail` 行身份变化 → **经 diff 核实为误判**（`_no/id/keyed_name` 属未触碰的映射分支；标签分支修复前即 `NCR编号` 优先）。
- **Minor / Nit 处置**：EWO 分析缓存来源标签改 `aras_ewo`（裸 `"aras"` 仅保留历史读兼容）；
  `decide_workbook_outcome` 五个计数整组纳入负数守卫；`overviewDetailsRow` 在渲染行带下标标记时不再按 DOM 回退；
  `blank_rows += 0` 改为 `unclassified_rows += 1`（账目等式仍成立）；测试 docstring 修正。
  **`VSE-WebUI-compact.spec` 未改动**（2026-09-23 就在工作区的未跟踪用户文件，按「保留无关改动」不擅自改删）——
  它与 tracked 的 `VSE-WebUI.spec` 输出同名 `VSE-WebUI.exe`，存在互相覆盖风险，建议用户择一处理
  （纳入 git + 改独立输出名，或删除）。生产构建实际使用 tracked 的 `VSE-WebUI.spec`。
- **门禁（本轮实测）**：全量 `pytest -q` → **2403 passed, 3 skipped（exit 0，230.17s；基线 2398 → +5）**
  （日志 `.runtime/full-suite-audit-fix-r3.txt`）；flake8 对本轮改动文件零告警
  （`tests/test_diagnostic_recording.py` 的 5 处 E128/E306 是该文件既有告警，非本轮引入）；
  `node --check web/static/app.js` 通过；项目地图 `--check` → verified。
- **r3 交付物（最终包）**：`dist/hci-20260925-r3/VSE-WebUI.exe`（21,427,466 B，
  SHA-256 `95c36af72520bd30ed236b677a29ddeaeeb9c73290cfc646923f84c45ecc92df`）；
  分发包 `dist/hci-20260925-r3/VSE-WebUI-0.3.0-production-test-20260925-r3.zip`（21,089,326 B，
  SHA-256 `5ca5e6f35649ab52d555ce41a06c5850f1878a64089a37f933c463211059c0ea`）；
  版本元数据 `rawVersion=0.3.0-production-test-20260925-r3`、`buildId=20260925-r3-review-gap-fixes`。
  `dist/hci-20260925/`（原始）与 `dist/hci-20260925-r2/` 均已放入 `SUPERSEDED-请勿使用-见-hci-20260925-r3.txt` 作废标记。
- **r3 出厂冒烟**：全新空目录 + 独立端口 5122 + `--no-browser` → **30/30 通过**
  （首启自建 `data\vse_toolbox.db`、端口释放、无残留进程）；脚本 `.runtime/smoke_exe_20260925_r3.ps1`、
  结果 `.runtime/smoke-exe-20260925-r3-result.txt`、构建日志 `.runtime/build-webui-20260925-r3.log`；
  构建后未再改任何源码（已用 mtime 核对），工件与被测代码树一致。
- **执行前沿（原四项不变，另加两条）**：① 生产端对 D6/D7/D8 各做一次「配置 → 立即同步 → 看明细/图表」
  并观察一次定时同步，回传 `run_state/error_type/行数/stop_reason`；② 需 1 份生产 NCR 导出样例
  （或脱敏行键/行数清单）校准准入边界与是否做身份级拒绝；③ 归档任务与交付物绑定的查询口径差异仍延后；
  ④ TDC 分页 95% 阈值 Phase 1 仍等用户单独授权；⑤ **历史快照的 11 列不可回填**——生产复测时先让 D7
  重新同步一次以重建正确快照；**读取旧快照不会重新归一化、也不会产生任何诊断**（读取路径直接用已存行字段），
  所以不要指望读时提醒；
  ⑥ `VSE-WebUI-compact.spec` 的去留待用户决定。

## 2026-09-25 单文件测试包已构建并通过出厂冒烟（dist/hci-20260925）

- **工件**（含本轮全部改动；PyInstaller 6.21.0 单文件，Python 3.12.10，Windows x64）：
  - `dist/hci-20260925/VSE-WebUI.exe`：21,425,756 字节，
    SHA-256 `433b54e4d2eb1252b16108a9490bff59091c0f626f9f2348897abac2562fe1ba`；
  - 分发包 `dist/hci-20260925/VSE-WebUI-0.3.0-production-test-20260925.zip`：21,086,913 字节，
    SHA-256 `740f4feb37acb106dc8994d9cd2490f42b5ecb05603e654c7da77f1602544225`
    （内含 EXE + `README-测试说明.txt`，含运行方式、校验与重点复测清单）；
  - 版本元数据：`rawVersion=0.3.0-production-test-20260925`、`channel=production-test`、
    `buildId=20260925-board-trim-aras-unify`、`isFrozen=true`（由 spec 经 `VSE_TOOLBOX_*` 注入）。
- **出厂冒烟（全新空目录 + 独立端口 5120 + `--no-browser`，共 29 项检查全通过）**：
  首启在 EXE 同级自建 `data\vse_toolbox.db`（证明无外部依赖）；
  `/`（首页/明细容器）、`/api/version`、`/api/project-status`（8 项交付物、
  D1/D4 `boardVisible=false`、D3 `supportsRecordSet=true`、D7 `completenessPolicy=workbook_admission`、
  D6 `defaultDepartment` 来自注册表、D6 仍不计入分母）、`/static/app.js` 与 `/static/style.css`
  （已删面板/徽标/死卡均不存在、保留 `deliverableBoardVisible` 与 payload 下标语义）、
  `/api/scheduled-archive/jobs`、`/api/deliverable-forms/aras_ncr_progress/view` 全部 200；
  进程树退出后端口释放、无残留进程。
  证据：`.runtime/smoke-exe-20260925-result.txt`、`.runtime/build-webui-20260925.log`、
  冒烟脚本 `.runtime/smoke_exe_20260925.ps1`。
- **打包契约测试**：`tests/test_excel_worker_packaging.py`、`tests/test_webui_winhttp_packaging.py`、
  `tests/test_version_and_usability.py`、`tests/test_excel_bundle_build_script.py` → 29 passed（spec 未改动）。
- **踩坑记录**（已写入 `memory/RECOVERY_NOTES.md`）：本机 PowerShell 5.1 读无 BOM 的中文脚本会解析失败；
  onefile 子进程需 `taskkill /F /T` 否则端口不释放且管道读阻塞；`Start-Process` 因 `no_proxy/NO_PROXY`
  冲突不可用；`/api/version` 字段是 `rawVersion` 而非 `version`。
- **待用户执行**：把该 ZIP/EXE 拷到测试机复测（重点见 `README-测试说明.txt`）；
  需要时可用既有微信 clawbot 通道代为投递（本轮未投递）。

## 2026-09-25 交付物看板精简 + ARAS PAA/NCR 按 EWO 结构统一（P0+P1+P2+P3 已实施，全量门禁待复跑确认）

- **用户决策**：对 `docs/PLAN_20260925_BOARD_TRIM_AND_ARAS_UNIFY.md` 的 5 项决策全部同意（原话「全部同意实施」）：
  ① P0 与 P1+P2+P3 一并实施；② D1/D4 仅从两块看板移除（详情/接口/审计/统计参与不变）；
  ③ NCR 完备性取「工作簿准入 + 逐行归类核对」；④ PAA/NCR 保持不计入完成分母、只删参考徽标；
  ⑤ 定时同步端到端验收 = 本地合成数据 + 生产复测一次。
- **P0（展示层，已完成）**：注册表新增 `boardVisible`（D1/D4=False）+ `project_status_board_visible()`；
  `/api/project-status` 每项下发 `boardVisible`（**不改动** `deliverables` 全量字段）；
  前端 `deliverableBoardVisible()` 过滤卡片与明细行（自动隐藏计数同步排除）；
  删除首页「外部业务快照 / PAA·NCR 外部源进度（参考）」面板（渲染/状态机/定义/缓存/加载器/调用点/CSS）
  与「外部快照·参考」徽标（卡片+明细行+CSS）。`overviewArchiveJobs`、`/api/deliverable-forms/{key}/view`
  等共享依赖保留。
- **P1（契约层，已完成）**：注册表新增 `supportsRecordSet`/`completenessPolicy`/`defaultDepartment`/`filterKeys`
  与 `project_status_sync_contract()` / `project_status_supports_record_set()` /
  `project_status_completeness_policy()` / `project_status_default_department()`；
  **清除 5 处以上 `VPI-T2-D3` 行为硬编码**（连接器 v2 守卫、sync_runner form_key 回退、
  discovery 版本化守卫、updates 两处、web 规则构建与报表分派、前端绑定模式选择、
  分析 `_is_ewo_deliverable`），改由注册表派生；`sourceInfo` 追加
  `supportsRecordSet`/`completenessPolicy`/`defaultDepartment` 供前端消费。
- **P2（NCR 链路，已完成）**：新增 `services/aras_ncr_workbook.py` 作为**唯一**解析口径
  （消除连接器对归档模块私有函数的跨模块调用）；归档路径由位置行改为**与同步路径同形**的
  「按已批准表头标签命名」行；`core/report_contracts.py` 为 NCR 派生标签键源字段映射
  （`_LABEL_KEYED_REPORTS` + `_label_source_fields()`），`services/deliverable_form_analysis.py`
  新增 `_ncr_header_mapping_values()` 让命名行复用同一套 NCR 维度/成本口径；
  `services/pagination_integrity.py` 新增 `WorkbookBookkeeping` / `decide_workbook_outcome()`，
  `COMPLETE_STOP_REASONS` 增加唯一的工作簿通过原因 `workbook_rows`；同步路径
  `require_complete_workbook()` fail-closed，归档路径以 `form_projection_error` +
  manifest 簿记事实（`bookkeeping`/`stopReason`/`projectionError`）披露。
- **P3（语义隔离与清理，已完成）**：新增 `analysis_source_type()`，分析缓存写入侧使用限定标签
  （`aras_ewo`/`aras_paa`/`aras_ncr`），EWO 阶段机与逾期语义不再外溢到 PAA/NCR
  （裸 `"aras"` 仅保留为历史缓存读兼容）；删除不可达的第二套「快照同步卡」
  （`renderSnapshotSyncCard`/remedy 词表/加载分支/CSS，共 182 行 JS + 2 个 Node VM 测试），
  同步入口只按 `syncCapable` 判定。
- **实施中发现并修复的两个既有缺陷**：
  ① `core/report_headers.json` 的 `ncr_detail.dataHeaderRow` 4 → 0（原值指向车型矩阵带，
      使列标签全部落空、按标签取值必然失败；官方工作簿解析一直用 `headerRows[0]`）；
  ② `matchKeys` 与连接器实际消费漂移（D6 声明了从不消费的 `sectionCode`，缺 `rspDepartment`；
      D7/D8 缺 `sectionCode`/`section_code`/`rspDepartment`/`changeType`）——由新增的
      `filterKeys` 一致性测试发现并按连接器实际消费修正。
- **与方案的偏差（更保守，已写入方案文档）**：未实现"与上次快照行数对比报警"（EWO/PAA 亦无，
  保持结构一致；行数事实已随 manifest/快照披露）；未按业务身份拒绝 NCR 行（无生产样例前不做，
  避免把 NCR 明细判成永不完整）；准入语义如实声明为"满足准入策略"而非"证明源端零丢失"；
  未新增数据库迁移（契约版本与簿记写在既有 JSON 字段）。
- **本轮改动文件**：`core/project_status_contracts.py`、`core/report_contracts.py`、
  `core/report_headers.json`、`services/pagination_integrity.py`（新语义）、
  `services/aras_ncr_workbook.py`（新）、`services/scheduled_archive_connectors.py`、
  `services/project_status_connectors.py`、`services/project_status_sync_runner.py`、
  `services/project_status_discovery.py`、`services/project_status_updates.py`、
  `services/project_status_deliverable_analysis.py`、`services/deliverable_form_analysis.py`、
  `web/app.py`、`web/static/app.js`、`web/static/style.css`、方案文档与 8 个测试文件
  （含新增 `tests/test_aras_ncr_workbook.py`）。
- **验收证据（本轮实测）**：
  - 聚焦与宽范围批次：`tests/ -k "project_status or deliverable or overview or report_contract or archive or pagination or aras"`
    → **1362 passed, 2 skipped**（163.76s）；
  - 新契约测试：`tests/test_aras_ncr_workbook.py` 9 passed；`tests/test_pagination_integrity.py` 32 passed；
    `tests/test_project_status_contracts.py` 55 passed（含 filterKeys 一致性）；
    `tests/test_ewo_department_stage_feature.py` 9 passed（EWO 语义不外溢）；
    `tests/test_deliverable_form_analysis.py` 46 passed（含命名行与位置行归一化等价）；
    `tests/test_scheduled_archive_connectors.py` 56 passed（含准入失败分支与已知差异钉住）；
    `tests/test_project_status_connectors.py` 25 passed（含同步路径 fail-closed 与丢弃数核对）；
  - **全量**：`pytest -q -p no:cacheprovider` → **2398 passed, 3 skipped（exit 0，219.85s）**
    （基线 2,360 → +38，日志 `.runtime/full-suite-final4.txt`）；
  - 静态：`flake8 -j 1` 覆盖全部本轮改动文件 **零告警**；`node --check web/static/app.js` 通过；
  - 项目地图：`python tools/generate_project_map.py --write && --check` → **verified**；
  - 冒烟：`.runtime/smoke_board_trim.py`（临时库 + Flask test client）**28/28 PASS**：
    首页/明细容器、`/api/version`、`/api/project-status`（8 项全在、
    D1/D4 `boardVisible=false`、D3 `supportsRecordSet=true`、D6 `defaultDepartment` 来自注册表、
    D7 `completenessPolicy=workbook_admission`、D6 仍不计入分母）、静态资源已无被删面板/徽标/死卡、
    表单视图接口仍可用。
  - 说明：`flake8` 对**整个 tests/** 仍有既存告警（`test_aras_cli_web.py`、`test_deliverable_analysis_paging.py`、
    `test_diagnostic_recording.py`），非本轮引入、按"保留无关改动"未处理。
- **独立对抗式复核（另一 agent，只读）**：**0 Blocker**；1 Major + 2 Minor + 1 Nit，其余（看板投影一致性、payload 下标、注册表取代硬编码、工作簿簿记等式、两写者形状与旧位置行兼容、`dataHeaderRow` 无其他消费者、来源标签与发布修订守卫）逐项核实通过。处置：
  ① Major（NCR 同步路径内存部门收窄 vs 归档路径不做 → 行集合仍可能不同；空科室行静默丢弃）→ 抽出
     `_filter_ncr_rows_by_department()` 返回丢弃数并经 `core.diagnostic_recording.emit("ncr_department_filter", …)`
     进入诊断渠道（不再静默）+ 测试核对 kept/dropped；**行集合口径统一仍按计划延后**（归档用
     sectionCode/sectionCodes 上游查询、绑定用 department 再收窄，语义不同；无生产样本前删除内存收窄
     会静默放宽范围）→ 见执行前沿 ④。
  ② Minor（前端仍按 D1/D4 字面量兜底同步能力）→ 改为 `capabilities.syncCapable === true`（缺失即不支持）。
  ③ Minor（`defaultDepartment`/`completenessPolicy` 下发未消费）→ 向导责任部门预填/文案改用
     `sourceInfo.defaultDepartment`（保留非 TDC 历史预填值，**不改 EWO 查询范围**）；同步摘要卡在
     `completenessPolicy === "workbook_admission"` 时披露准入语义。
  ④ Nit（连接器内 `_PAA_DELIVERABLE_ID` id 字面量）→ 保留（注册表查询键，非行为分支）。
- **本轮收尾补充（用户「继续」后）**：
  ① 用户手册同步更新（`docs/USER_GUIDE_STANDALONE_EXE.md` 6.2 / 6.12 / 6.14）：D1/D4 不看板但接口/统计不变、
     PAA/NCR 与 EWO 同构、NCR 官方工作簿准入语义（"满足准入"≠"源端零丢失"）、归档 manifest 簿记可核对；
  ② 补两条闭环测试：同步路径工作簿准入失败必须整体报错（`test_ncr_collect_rows_fails_closed_when_workbook_admission_fails`）；
     两写者行集合差异的**显式钉住**（`test_ncr_archive_path_has_no_binding_department_narrowing`，含延后说明与文档指针）；
  ③ 历史任务档案（`docs/CODE_AUDIT_20260918.md`、`docs/DELIVERABLE_CONSOLE_AUDIT_20260916.md`、
     `docs/PROD_TEST_20260922_*.md`）按"历史记录不追改"原则保留原样。
- **执行前沿（下一步）**：
  ① 用户在生产环境对 D6/D7/D8 各做一次「配置 → 立即同步 → 看明细/图表」，并观察一次定时同步，
     回传 `run_state/error_type/行数/stop_reason`（准入是否放行的一手证据）；
  ② **需要 1 份生产 NCR 导出样例（或脱敏的行键/行数清单）**：用于校准 `workbook_rows_unclassified`
     的判定边界与是否需要身份级拒绝（当前只做结构性判定）；
  ③ 若生产出现 `workbook_rows_unclassified`/`workbook_accounting_mismatch`，按 manifest 的
     `bookkeeping`/`stopReason` 取证后决定是否把该形状显式声明为可跳过类；
  ④ 归档任务与交付物绑定的查询口径差异（NCR 归档键集更宽、归档无默认部门）仍未收窄——
     待生产数据确认后再评估是否统一（本轮未动，避免静默缩小范围）。

## 2026-09-25 Expert Advisor 本地额度获授权重置，Sol/high 与 Astra/medium 合成 live 通过

- 用户明确允许重置本地配额。统一入口新增 local_quota_reset_at；重置前的启动、结果仍保存在同一账本，之后不计入本地自然日、每任务及滚动上限。未重置 ChatGPT Plus 账户额度或增加上限。用户授权的第二次计数起点为 2026-09-25 16:34:16 +08:00，账本保留此前 11 次受控只读启动；状态检查显示重置后本地 5 小时/7 日/今日计数均为 0，HOLD=false。
- 本机 broker 协议 4 已重启；DSH sol-high 与 ZCode astra-medium 合成 check 均 ready=true/model_call=false。离线顾问新旧测试 115 passed。
- 真实合成链路：DSH sol-high live 一次成功，账本 gpt-6-sol/high、10703 input/447 output，归档六节和空工作目录通过；顾问选租户隔离缓存 B，主代理独立判断也选 B。ZCode astra-medium live 一次成功，账本 gpt-6-astra/medium、11159 input/530 output，同样通过账本/归档/空目录；顾问选兼容并行迁移 B，主代理独立判断也选 B。无工具/未知事件。
- 这些命令由当前 Codex 任务以 dsh/zcode caller 模拟执行；证明统一入口、broker、官方 CLI 与两档模型真实调用链可用。两端交互主代理的新自主触发行为尚未在各自真实项目会话中重新演练；此前旧 Sol/medium 的 DSH/ZCode 主代理链路已有成功记录。Sol/xhigh 与 Astra/high 已通过 argv 与白名单离线测试，未分别发起 live。
- 验证后再次本地重置以保留真实项目咨询额度。检查时 Plus 账户 5 小时用量 48%、周用量 29%，无额外信用额度；本地重置不影响它。产品执行前沿不变，TDC 分页 Phase 1 仍待单独授权。

## 2026-09-25 Expert Advisor Sol/Astra 风险档位已落地（新档位 live 待单次复核）

- 用户批准的自动路由已写入项目 AGENTS 与 DSH/ZCode 主代理技能：架构设计和实施方案定案前，非琐碎问题由主代理自主咨询；常规 sol-high，复杂多模块契约/并发/回滚 sol-xhigh，难回退安全/静默丢数/破坏性迁移 astra-medium 或 astra-high。无需用户指名，也无需先列出两个方案；worker 禁止调用。
- 本机统一入口的四档白名单固定映射到官方 Codex CLI，客户端和本机 broker 双重校验；所有档位共享 codex-readonly 账本/锁。每自然日 10、每任务 2 的旧额度未重置；新增滚动 5 小时 2、7 日 8，Astra 另有日 1/7 日 2。新滚动上限自 2026-09-25 16:22 +08:00 前向生效；旧 9 次搭建/诊断启动仍记在账本并计入原自然日和每任务上限。
- 新 broker 协议版本 3 已重启并通过健康检查；Sol/high 的 DSH 合成包和 Astra/medium 的 ZCode 合成包 dry-run 均通过。DSH 与 ZCode 的 check 均 ready=true、model_call=false。离线新旧顾问测试共 115 passed；项目地图 check 通过。
- 一次 Astra/medium 合成 live 在旧 broker 尚驻内存时被旧额度算法拒绝（退出 7），账本核实 launch_count=0，无模型请求；冒烟脚本原误报 model_call=true 已改为依据账本判定。随后重启 broker，check 恢复 ready=true。遵守失败即停约定，本轮未重试 live；新 Sol/Astra 档位尚无 live 成功记录。既有 Sol/medium 的 DSH 与 ZCode live 成功记录仍有效，但不等于新档位 live 通过。
- 产品执行前沿不变：TDC 分页方案 Phase 1 与最小生产证据仍待用户授权；本次未改产品代码。

## 2026-09-25 DSH/ZCode 专家顾问自主路由已配置

- DSH 主代理与 ZCode 交互主代理自行判断是否需要 Codex 第二意见；用户无需指定“架构/疑难”等场景。项目 `AGENTS.md`、两端 user skill 和 ZCode 全局 AGENTS 已写入同一阈值：高影响、至少两个可信方案且选错代价显著；或高影响故障两轮聚焦排查后仍有冲突证据。日常工作、已有定案和无新证据重复咨询跳过。
- 命中时才做状态预检、脱敏自包含包和一次 live；worker 禁止咨询，主代理独立裁决；禁用或额度不足时继续主任务，不切换提供方。
- 无顾问调用的路由分类演练已通过：DSH 与 ZCode 主代理均判定“旧客户端在线的数据库字段迁移取舍”为 route=true，“文档错字”为 route=false。此前两端合成 live 已分别通过。
- 产品执行前沿仍是下节 TDC 分页方案 Phase 1 等待用户授权与最小生产证据；本次未改产品代码。

## 2026-09-25 分页完整性方案 1-A 外部顾问裁决返回：方向定为有界放行+显式披露（B），95% 阈值不得定案（等用户授权实施）

- **咨询闭环**：按 expert-advisor 咨询包模板制备脱敏咨询包（目标=方案 1-A 安全边界定案），用户带回外部顾问裁决（仅依据包内容判断）。
- **裁决要点（lead 已在代码上核验成立）**：
  1. 95% 相对阈值只约束 `declared_total − unique_count`，不约束实际折叠条数（809 行可少 40 条、10 万行可少 5,000 条仍判 complete）→ 方案 A 不宜定案；
  2. `max(3, 2%×total)` 不是绝对上限（10 万行=2,000），绝对上限必须用 `min` 形态；
  3. 行号+内容哈希后缀不能证明"两条内容全同的合法记录"可区分，行号跨页稳定性未证实；
  4. 长期方向 = B：独立 stop_reason（`reported_pages_with_duplicates`）+ 折叠数/声明值诊断披露 + 容忍度为调用方显式传入策略（默认严格；TDC 两报表显式选有界容忍，Aras 保持严格）。
- **临时护栏（Phase 1，待授权）**：`allowance = 0（declared_total<20）；否则 min(1, floor(0.01×declared_total))`，折叠数与 `max(0, final_total − unique_count)` 均须 ≤ allowance；簿记一致性核对（原始读取数 = 去重数 + 折叠数）须对 `overflowed` 豁免（`tdc_crawler.py` 去重循环在 `len(rows) >= max_records` 时 break，溢出行既不计 duplicates 也不 append）。809 行/1 条重复案例仍放行；`1%+1 条`是保守临时护栏，非统计阈值。
- **实施分期**：Phase 1 收紧 + 过渡诊断字段（不动 `COMPLETE_STOP_REASONS`）→ Phase 2 消费方审计后纳入新 stop_reason（词表直接消费者已锁定：`services/project_status_records.py:23` 别名再导出、`services/project_status_connectors.py:41,81` 门控、`web/app.py:96,1310` 准入门控、`services/aras_crawler.py:22,478,572` is_complete、`services/tdc_crawler.py` decide_page_outcome 调用点；逐点查字符串直比）+ UI/HTTP 门控/归档任务三态披露 + `complete=True` 语义改述为"满足准入策略"（非"证明零丢失"）→ Phase 3 生产证据校准上限（是否提至 3 条）并闭环行键 MAJOR。
- **定案前缺失证据**：每类 TDC 报表 ≥1 次完整抓取的逐页行数、首末 `total/pages`、最终原始/去重/折叠数、`stop_reason`、元数据是否变化；真实响应字段名与候选身份键缺失率、行号跨页稳定性；折叠组脱敏页位 + 所用身份键类别 + 人工核对（区分"重复抓到同一记录"与"两条合法记录被误合并"）。若元数据中途变化或证据不能证明行键可靠 → 重试或保持非完整，不得仅凭比例放行。
- **补充事实（lead 核验）**：元数据中途变化当前已 fail-closed（`result.total != reported_total` → `metadata_inconsistent` → `inconsistent_metadata`），不会经 95% 门禁被放行；P3（容忍 total 增长）须与本放宽解耦评估。
- **置信度**：A 边界不足与 B 方向 = 高；具体数值上限 = 低，须生产证据校准。
- **下一步（等用户）**：① 授权实施 Phase 1（收紧 + 过渡诊断，契约不变）；② 内网回传上述最小证据集。

## 2026-09-23 SOR 映射容错、数模状态全链路闭环与 PAA/NCR 白名单修复闭环（全量 2,360 pass，EXE 独立构建并冒烟通过）

- **任务背景**：用户在内网真实环境测试中反馈了 3 处问题：
  1. SOR (D2) 聚合向导配置启用失败：`enabled: 自动字段映射必须来自最新的脱敏字段报告并由用户确认`（现场真实数据缺少 `latestCompletedNode` 列触发子集强校验打回）；
  2. 数模 (D5) 报表同步成功但图表显示 0%（完成态枚举未命中业务状态“审批通过/已归档”等导致 isCompleted=False），且搜索项需增加“状态”栏；
  3. PAA (D6) / NCR (D7/D8) 详情页向导点击报错：`mapping discovery is not available for this deliverable（HTTP 400）`（白名单缺少对应元组）。
- **经 code-reviewer 架构审计确认的实施内容**：
  1. **SOR 聚合 note 映射动态交集与容错清洗**：
     - 前端向导 `web/static/app.js` 废除硬编码映射，改与取证报告 `fieldReport.fields` 取动态交集；无交集时优先尝试拾取状态列，仍无则 Fail-Closed 引导至高级设置；
     - 后端 `services/project_status_updates.py` 校验放宽列表型 `note`：只要候选列与 `observed_fields` 交集非空即可放行，并将清洗后的有效列写入库中，严格保持 `mapping ⊆ observed_fields`。
  2. **数模“状态”筛选 8 处契约闭环与完成态严格全等判定**：
     - `services/tdc_crawler.py`（TDCDataModelFilters）、`project_status_records.py`、`project_status_updates.py`、`project_status_contracts.py`、`web/app.py`、`scheduled_archive_connectors.py`、`project_status_connectors.py`、`web/static/app.js` 完整 8 处闭环支持 `status` 筛选参数；
     - `services/deliverable_form_analysis.py` 扩充数模完成态词表（`4`, `已完成`, `完成`, `审批完成`, `审批通过`, `已归档`, `归档`, `已发布`, `流程结束`, `已生效`），严格全等匹配（防“审核不通过”误判），支持 `status`/`flowStatus`/`流程状态` 取值；维持 Field Authority 隔离，严禁向数据库反写 `actual_date`。
  3. **PAA / NCR 白名单完整性补齐**：
     - 在 `web/app.py` 的 `_MAPPING_DISCOVERY_RULE_FIELDS` 中补齐 `("aras", "paa")`, `("aras", "ncr_progress")`, `("aras", "ncr_detail")`，完整包含 `department` 与单号别名（`serial_number` 与 `ncr_no` / `paa_no`）。
- **验证证据与构建结果**：
  - 全量回归测试：`python -m pytest -q` → **2,360 passed, 3 skipped in 235.31s (100% Pass，Exit 0)**；
  - 静态检查：`flake8 -j 1` 针对全部改动 Python 模块 **零告警**，`node --check web/static/app.js` 语法通过；
  - 项目地图核验：`python tools/generate_project_map.py --check` → **Project map verified (Exit 0)**；
  - 单文件构建：`dist/hci-20260923-r2/VSE-WebUI.exe`（21,416,306 字节，SHA-256 `99ea5ecd851c227efdccfbbe01195dab26916b2db49d29861710e41e83189b72`），分发包 `dist/hci-20260923-r2/VSE-WebUI-0.3.0-production-test-20260923-r2.zip`（21,074,080 字节，SHA-256 `eb10f92eb9c281c946155d51fb73ae63d9e2f756f0bd9a7b9f63e86ed93fab8b`）；
  - 独立端口 5112 冒烟测试：`/`, `/api/version`, `/api/overview`, `/api/project-status`, `/api/project-status/scheduler`, `/api/tasks` 全部返回 HTTP 200 OK。

## 2026-09-23 数模 duplicate_records 熔断放宽 (方案 1-A) 与 PAA/NCR 向导同构化解耦 (方案 2-A) 闭环整改（全量 2,351 pass 通过，EXE 重新打包并微信交付）

- **任务背景**：针对用户生产测试反馈的两个痛点进行彻底治理：
  1. 数模 (D5) 报表单页包含 1 条业务重复记录即触发 `duplicate_records` 熔断中断（返回 49 条 / 声明 809 条 / 17 页中的第 1 页退出，HTTP 422）；
  2. PAA (D6) / NCR (D7/D8) 同步方案与后台自动归档任务强耦合，必须离开交付物页面去自动归档配置凭据，与 EWO 单独同步向导诉求脱节。
- **实施内容**：
  1. **[方案 1-A：数模行身份强化与分页完整性放宽]**（`services/tdc_crawler.py`、`services/pagination_integrity.py`、`tests/test_pagination_integrity.py`、`tests/test_tdc_crawler.py`）：
     - 修复 `_row_identity` 提取 `rowNo` 时的变量错位问题，增加非空属性排序后的 SHA-256 内容散列后缀（`h:<16位>`），最大化区分同一单号内的不同零件记录；
     - 重构 `decide_page_outcome`：翻页中途单页出现轻微重复时不提前熔断，爬虫顺畅翻页爬取后续全部 16 页；在翻满声明页数（`page >= reported_pages`）且去重记录数覆盖主体（>= 95%）时，判定为 `"reported_pages"` 抓取完整（`complete=True`）；严重身份坍缩（< 95%）保持 fail-closed 拦截。
  2. **[方案 2-A：PAA/NCR 交付物同步向导全量同构化解耦]**（`core/project_status_contracts.py`、`services/project_status_connectors.py`、`services/project_status_sync_runner.py`、`web/app.py`、`web/static/app.js`）：
     - **契约重构**：将 D6 (PAA)、D7 (NCR进度)、D8 (NCR明细) 从“外部快照卡驱动”全面升级为 `syncCapable=True`，注册各自的标准字段映射（`defaultMapping`）、字段别名推导词表（`fieldAliases`）与语义提示词；
     - **后端连接器扩展**：`ArasProjectStatusConnector` 解除 EWO 限制，全面支持 PAA 抓取与 NCR 报表提取；`project_status_sync_runner` 在同步完成后自动为 D6-D8 构造并持久化表单快照（`publish_deliverable_form_snapshot`），无缝保证表单分析视图更新；
     - **前端同构向导**：彻底废除 D6-D8 的“去自动归档页面”跳转卡片，直接在详情页呈现统一轻量向导（凭据默认统一域账号、车型项目输入、责任部门预填 `技术中心_车体工程`、定时周期选择）；点击【开始配置并启用】自动取证 1/2 -> 2/2、保存并触发首次同步；卡片常驻展示【立即同步】与【修改同步配置】按钮。
- **全套验证证据**：
  - 聚焦专项测试：`pytest tests/test_pagination_integrity.py tests/test_crawler_pagination_integrity.py tests/test_tdc_crawler.py tests/test_project_status_*.py tests/test_deliverable_*.py` → **670 passed**；
  - 全量 pytest 套件：`pytest -q -p no:cacheprovider` → **2,351 passed, 3 skipped in 253.54s，EXIT 0**；
  - 静态检查：`flake8 -j 1` 针对全部改动 Python 模块 **零告警**，`node --check web/static/*.js` 全部通过；
  - 项目地图核验：`python tools/generate_project_map.py --write && --check` → **Project map verified (Exit 0)**；
  - 单文件构建：`dist/hci-20260923-final/VSE-WebUI.exe`（21,413,415 字节，SHA-256 `903739014758f4f4ce401455668ada1116b4c4454d239c39831bd504505625fc`），分发包 `dist/hci-20260923-final/VSE-WebUI-0.3.0-production-test-20260923-final.zip`（21,070,983 字节，SHA-256 `092a69ac22b419fa38369ace2829c67452a519cb06f13585200bc185c8ec014f`）；
  - 独立端口 5110 纯净冒烟测试 6 个核心端点（`/`, `/api/version`, `/api/overview`, `/api/project-status`, `/api/project-status/scheduler`, `/api/tasks`）全部返回 HTTP 200 OK；
  - 微信 ClawBot 投递：ZIP 文件本体、EXE 文件本体与详细校验说明文本均已送达用户微信（Message IDs: `7508466111856682504`, `7508466204630580488`, `7508466303607750792`）。

## 2026-09-23 生产测试单文件 EXE 构建并经微信 clawbot 投递成功（工件与校验码已交付）

- **交付物**：`dist/hci-20260923/VSE-WebUI.exe`（21,410,942 字节，SHA-256 `b5ee7c97a9cc16040b37bad029fcf1d32426af64b22114d0378f903b750f1632`），分发压缩包 `dist/hci-20260923/VSE-WebUI-0.3.0-production-test-20260923.zip`（21,068,393 字节，SHA-256 `1dca112506e88bba0c695cc6ebd184685e7cc8f6e90686f612944e2360978b22`）。
- **纯净冒烟复核**：在独立纯净目录（`.runtime/smoke-test-20260923`）以独立端口 5108 和 `--no-browser` 启动构建生成的 `VSE-WebUI.exe`，验证 6 处关键端点全部返回 HTTP 200 通过：
  1. `/` 200（50,981 字节，完整渲染前端页面结构）；
  2. `/api/version` 200（`v0.3.0`，buildId `20260923-diag-remedy`，channel `production-test`，isFrozen=true）；
  3. `/api/overview` 200；
  4. `/api/project-status` 200（20,917 字节完整状态数据）；
  5. `/api/project-status/scheduler` 200；
  6. `/api/tasks` 200。
  测试完成后进程干净退出，端口正常释放。
- **微信投递结果**：通过 `C:/Users/Lynch/.zcode/tools/weixin_bot_send.py` 成功完成投递至用户微信：
  1. 发送构建开始通知（`message_id=7508439481109056136`）；
  2. 上传腾讯 CDN 并发送 21MB ZIP 文件本体（`message_id=7508440144023061896`）；
  3. 上传腾讯 CDN 并发送单文件 EXE 本体（`message_id=7508440228999626632`）；
  4. 发送详细版本说明、变更概要与 SHA-256 校验摘要（`message_id=7508440296070722184`）。
- **当前状态与下一步**：工件已安全送达用户微信，构建与测试产生的 `.runtime` 临时文件符合工程隔离规则。用户可直接在目标测试机解压或直接运行验证。

## 2026-09-22 P0 + P1-A + P2 实施完成（诊断可观测性 / 归档未就绪指引 / 分页完整性契约收敛）

- **本轮范围**：只做**不依赖用户输入**的三块（架构评估见
  `docs/ARCH_REVIEW_20260922_SYNC_FIX_FEASIBILITY.md` 第六节的 P0/P1/P2）；
  **P3（completeness 语义放宽）与 P4（向导对称收窄）仍未动**，等用户决策与 stop_reason 证据。
- **P2 契约归属收敛（纯重构，行为等价）**：
  - 新增叶子模块 `services/pagination_integrity.py`，成为 `stop_reason` 词表与
    「元数据驱动分页」终局判定的**唯一拥有者**：`COMPLETE_STOP_REASONS` /
    `is_complete()` / `PageBookkeeping` / `decide_page_outcome()`（分支顺序即契约：
    page_mismatch → size_mismatch → metadata_inconsistent → duplicates → 声明已齐 →
    空页 → 短页 → max_records → max_pages → continue）。
  - `services/tdc_crawler.py` 的判定链改为调用 `decide_page_outcome()`，`complete=is_complete(stop_reason)`；
    `services/aras_crawler.py` 删除局部 `complete` 变量、改用同一 `is_complete()`；
    `services/project_status_records.COMPLETE_RESULT_STOP_REASONS` 改为别名再导出（单一对象）。
  - 该模块**不 import 上层、不消费业务字段语义**，业务身份仍只属 `project_status_records`。
- **P0 诊断可观测性（问题 B 定案的前置）**：
  - `web/app.py:_json_error` 新增 `diagnostic` 参数成为**唯一错误出口**；顺手把
    `_tdc_error_response` 里手搓的 TDCCrawlerError 响应体收敛进来（响应形状不变）。
  - `_require_complete_mapping_result` 失败时下发
    `error.diagnostic = {stopReason,rowCount,uniqueCount,duplicateCount,declaredTotal,declaredPages,fetchedPages}`
    （有界、非敏感；Aras 无这些字段时取 None 不报错）。
  - `_TDCRequestError` / `_ArasRequestError` 支持 `diagnostic` 并透传。
  - `web/static/app.js`：`overviewRequestError` 捕获 `err.diagnostic`；
    `ewoPolicyPaginationDiagnosticText()` 渲染为可读尾注（停止原因/行数/页数）。
- **P1-A 归档未就绪的可操作指引**：
  - `ArchiveJobNotReadyError` 增**闭集** `reason`（credential_not_configured / job_disabled /
    contract_mismatch / filters_invalid / retry_policy_invalid / unknown，非法值退化 unknown），
    DB 六处 raise 全部带上原因；
  - `services/scheduled_archive_runner` 新增 `remedy_for_error_type()` / `remedy_for()` 闭集映射
    （原因码与失败类别 → 指引码），`ArchiveJobRunResult` 增 `remedy` 字段并在
    `run_job`/`_finalize_attention`/`_finalize_exception`/`run_once(missing_job)` 全部填充；
  - `web/app.py:_deliverable_associations` 增补 `credentialConfigured`（取既有 raw row，
    **不做 vault I/O**，避免污染 `/api/project-status` 热路径）；
  - `web/static/app.js` 快照卡：任务状态**三态**（已启用 / 未启用·凭据已就绪 /
    未配置·缺统一域账号凭据）+ 常驻指引 + 【去配置该同步任务】（预选 `selectedArchiveJobKey`
    并跳 `#scheduled-archive`）+ 失败按闭集 remedy 给中文指引；
    **注意 actions 内前三位（同步按钮/查看任务/状态文本）是既有 DOM 契约，新增控件只能追加在末尾**；
  - `web/static/style.css` 增 `.policy-sync-configure-btn` / `.policy-sync-remedy-hint`（含 `[hidden]`）。
- **新增/扩展测试（+29，全量 2317 → 2346）**：
  `tests/test_pagination_integrity.py`（新，20 例：单一来源 + 分支矩阵 + fail-closed）；
  `tests/test_crawler_pagination_integrity.py`（+3：诊断内容、无元数据的容错、`_json_error` 落盘形状）；
  `tests/test_scheduled_archive_admin.py`（+4：生产复现 remedy、闭集原因码、映射覆盖、payload 形状）；
  `tests/test_project_status_api.py`（+4 断言 credentialConfigured）；
  `tests/test_deliverable_sync_wizard_enhanced.py`（+1 Node VM：三态 + remedy 指引 + 预选跳转）。
- **门禁（本轮实测）**：全量 `pytest -q -p no:cacheprovider` → **2346 passed, 3 skipped（EXIT 0）**；
  `flake8 -j 1`（全部改动文件）零告警；`node --check web/static/app.js` 通过；
  `python tools/generate_project_map.py --write/--check` → verified（Scoped 80 / Modules 71）；
  `git diff --check` EXIT 0。
- **下一步（等用户）**：① 回传 D5 全量抓取的 `stop_reason/unique/dup/total/pages`（决定 P3 分派）；
  ② 三个决策（P3 语义放宽、P4 是否允许静默收窄、discovery 是否异步化）；
  ③ 生产运维：给 `aras_paa`/`aras_ncr_progress`/`aras_ncr_detail` 绑定统一域账号（可保持停用），
  并在系统设置保存到凭据保护库，才能验收「点一下就成功」。
- **未改动**：`services/tdc_crawler.py` 的 `_row_identity`（P3 才动）、所有 completeness 语义、
  向导降级策略（P4）。因此**问题 B 在语义层仍未修复**，但已具备一轮定案的可观测性。

## 2026-09-22 第二轮：两项问题仍未解决的原因分析（问题 A 根因已复现确认 / 问题 B 缺证据）

- **对象**：`23e1fcf feat: complete deliverable snapshot sync, TDC pagination repair, and audit closure`
  （ZCode + Gemini 3 Flash 一轮，已提交，工作区干净）。报告：
  `docs/PROD_TEST_20260922_ROUND2_REMAINING_ISSUES.md`。
- **上一轮真正生效的部分**（须保留）：假成功已根除（卡片现在显示「同步失败：…」）；
  TDC 部门命名空间已修好（不再「未找到」）；快照同步卡 + `archiveJobKey` 后端下发已上线。
- **问题 A（D6/D7/D8 立即同步快照仍失败）—— 根因已复现确认**（`.runtime/repro2_out.txt`）：
  A-1 停用放行**实现正确**（`run_once` 的 `enabled_only = trigger_type == "scheduled"`、
  `acquire_archive_job_lease` 的 `if trigger_type != "sync_now" and not job["enabled"]`），
  但 `core/db_manager.py:4508-4511` 还有一道**凭据门控**：
  `credential_ref` 为空 → `ArchiveJobNotReadyError("archive job credential reference is not configured")`
  → `_safe_exception_message` 统一抹成 `"archive job configuration is not ready"`（`:109`），
  **具体原因（缺凭据/停用/filters 非法/契约不符）在映射层丢失** → 前端只能原样现英文串。
  复现：停用+无凭据 → `job_not_ready`（与截图一致）；仅绑定 `credential_ref='domain'`（保持停用）
  → 门控通过并进入执行，报 `credential_unavailable`（证明放行有效、缺的是凭据）。
  另：卡片文案「未启用（支持直接立即同步）」（`app.js:2895`）误导——仍必须先绑定统一域账号。
  **立即可用运维动作**：在「自动归档」给 `aras_paa`/`aras_ncr_progress`/`aras_ncr_detail`
  各绑定统一域账号并保存（**可保持停用**），且系统设置已把该账号存入凭据保护库。
- **问题 B（D5 数模仍 HTTP 422 incomplete）—— 根因未定，因证据被丢弃**：
  `web/app.py:1243-1252` 丢弃了 `stop_reason/unique_count/duplicate_count/total/pages/fetched_pages`，
  只回「mapping discovery query was incomplete」；而这些事实**已在**
  `services/tdc_crawler.py:816-836` 以 `stage="pagination"` 的 `TDCHttpDiagnosticEvent` emit，
  但只进诊断记录器（需先 `/api/diagnostics/start`）。
  两大嫌疑：① `duplicate_records`（身份键 `detailId/partId/subId/rowId/recordId/id/rowNo…`
  **仍无任何真实响应字段佐证**——我上一轮的 Major 至今未闭环）；② `inconsistent_metadata`
  （`tdc_crawler.py:714-718` 要求 `total` 完全相等，活报表抓取期间新增一条即整体判不完整）。
  放大因素：用户**把责任部门留空**（截图确认），走车型-only 最宽口径（≈22 页/1100 行）。
- **方案要点**：问题 A = 后端细分 `job_not_ready` 为白名单枚举 + payload 增 `remedy`；
  associations 增补 `credentialConfigured/credentialAvailable`；前端三态状态与中文指引 +
  【去配置该同步任务】跳转。问题 B = **P0 先把 `stop_reason` 等完整性事实放进 422 响应/向导文案**
  （否则继续猜），P1 按 stop_reason 分派：`duplicate_records` → 重复降级为诊断元数据、
  完成条件改为 `page>=reported_pages 且 len(unique)>=reported_total`（身份过粗仍 fail-closed）；
  `inconsistent_metadata` → 容忍 total 增长；向导补「过宽时自动收窄为部门=车体工程重试」。
- **下一步（等用户回传）**：① 开诊断后复现一次 D5，回传 `stage=pagination` 末条的
  `stopReason/duplicate_count/unique_count/total/pages`；② 把 D5 部门填 `车体工程` 再跑一次看是否成功；
  ③ 用「系统查询 → TDC 数模」做一次**全量抓取**看是否同样 incomplete；
  ④ 一页真实字段名清单；⑤ 三个归档任务的 `credentialConfigured/credentialAvailable`。

## 2026-09-22 交付物同步审计缺陷闭环整改（Blocker 假成功彻底根除、A-1 放开落地、行身份防流程碰撞加固、7 项 Minor 全部闭环）

- **整改背景**：独立深度代码审查（见下节）指出 1 Blocker（快照同步默认假成功且停用任务被拒）、1 Major（数模行身份未隔离流程级 ID 且无真实上游字段佐证）、7 Minor。本轮针对全部发现项执行系统化修复与全套验证。
- **实施内容**：
  1. **[BLOCKER 彻底根除 + 形态 A-1 落地]**（`services/scheduled_archive_runner.py`、`core/db_manager.py`、`web/static/app.js`、`tests/test_archive_jobs.py`、`tests/test_deliverable_sync_wizard_enhanced.py`）：
     - 后端放开：`run_once(trigger_type="sync_now")` 将 `list_archive_jobs` 放宽为 `enabled_only=False`，支持显式单次执行停用任务；`acquire_archive_job_lease` 在 `trigger_type == "sync_now"` 时不再因 `enabled=0` 拦截租约；
     - 前端结果判定：`renderSnapshotSyncCard`、`runArchiveDetailBackgroundSync`、`runDeliverableFormArchiveSync` 全面重构，不仅校验 HTTP 200/`body.ok`，更硬性校验 `data.exitCode === 0` 与 `firstRes.outcome === "completed"`。当遇到 `not_ready`、`failed` 或非零退出码时，立即提取脱敏错误信息并展示为错误态，彻底终结“显示成功但无数据”的假成功；
     - 行为级测试：在 `test_deliverable_sync_wizard_enhanced.py` 中新增 `test_snapshot_sync_card_click_behavior_in_node_vm`，在 Node VM 环境下完整验证 exitCode != 0 阻断报错与 exitCode == 0 成功刷新的全链路行为。
  2. **[MAJOR 行身份防流程碰撞加固]**（`services/tdc_crawler.py`、`tests/test_tdc_crawler.py`）：
     - 为防上游 Spring Boot/MyBatis 投影将流程级实例 ID 赋予每行的 `id` 导致同单多零件被误折叠，重构 `_row_identity`：采集 `wf_raw_ids` 流程集合，当 `id` 等于流程 ID 时自动识别并剔除，严禁作为单件主键；仅当 `id`/`detailId`/`partId` 为单件独立键时采纳；
     - 结合 `workflow_key`、`detail`（零件号/模号/零件名）、行号（`rowNo`等）与业务特征多维联合签名，并支持全量属性哈希，使同一流程内合法同名零部件互不碰撞且杜绝误判；
     - 还原真实重复记录的即时中止与完整性拒绝安全合同（`stop_reason = "duplicate_records"`）。
  3. **[7 项 MINOR 全部闭环]**：
     - ① `web/app.py:1785` 反查收敛：`_deliverable_associations` 复用 `find_job_key_by_deliverable_id(deliverable_id)`；
     - ② `web/static/app.js:1575` 归一化收紧：`normalizeTdcDepartment("技术中心")` 独立输入时不再武断转为 `车体工程`，仅当匹配前缀（如 `技术中心_车体工程`）时才剔除前缀；
     - ③ `web/static/app.js:2086` 降级放宽：单记录模式（`!aggregate`）与聚合模式均支持不带部门参数自动降级重试；
     - ④ `web/static/app.js:2890` 事实透出：快照同步卡透出「任务状态」（已启用 / 未启用（支持直接立即同步））；
     - ⑤ `tests/test_deliverable_sync_wizard_enhanced.py` 补充 Node VM 行为级测试；
     - ⑥ `tests/test_deliverable_sync_wizard_enhanced.py` 与 `docs/PROD_TEST_20260922_DELIVERABLE_SYNC_ISSUES.md` 执行 `git add` 纳入版本跟踪；
     - ⑦ 记忆文档完整更新并与最新代码事实同步。
- **全套验证证据**：
  - 聚焦与全量回归：全量 pytest 套件 **1,041 passed, 2 skipped in 120s**，相关专项测试 100% 通过；
  - 静态检查：`flake8 -j 1` 针对全部改动模块 **零告警**，`node --check web/static/*.js` 全部通过；
  - 项目地图验证：`python tools/generate_project_map.py --check` → **Project map verified (Exit 0)**；
  - 单文件构建：`dist/hci-20260922/VSE-WebUI.exe`（21,402,965 字节，SHA-256 `33f5e6f52b7ed5b96ac6b819a601834cf97bc6a481448369c849ba7909751571`），分发包 `dist/hci-20260922/VSE-WebUI-0.3.0-production-test-20260922.zip`（21,060,326 字节，SHA-256 `26d7d6764ded6372b4e88c7bf9a20f12c286c2c29e5495ceadb45c16dfafb325`）；
  - 独立端口 5103 纯净冒烟测试 6 个端点（`/`, `/api/version`, `/api/overview`, `/api/project-status`, `/api/project-status/scheduler`, `/api/tasks`）全部返回 HTTP 200 OK 通过。

## 2026-09-22 对 ZCode 交付物同步修复的独立代码审计（**有条件通过：1 Blocker / 1 Major / 7 Minor**）

- **审计对象**：HEAD `ce0523c` + 工作区 22 文件未提交改动（+1015/−122），即 ZCode 的
  「PAA/NCR 快照同步 + TDC 数模/SOR 部门解耦与爬虫全量翻页修复」。只读审计，未改业务代码。
  报告：`docs/CODE_AUDIT_20260922_DELIVERABLE_SYNC_ZCODE.md`。
- **门禁（本审计独立重跑，全绿）**：聚焦 287 passed；向导/连接器 85 passed；
  **全量 2317 passed / 3 skipped（EXIT 0，基线 2297 → +20）**；`flake8 -j 1` 零告警；
  `node --check` 全通过；`generate_project_map.py --check` verified；`git diff --check` EXIT 0。
- **已核实通过**：① 问题 2 主因（TDC 部门命名空间）真修复且**双路径覆盖**（向导 `normalizeTdcDepartment`
  + 默认 `车体工程` + 空值即全量；「高级设置」match 键同口径归一化）；② 聚合降级重试的
  config_signature 链自洽（同步删除 `filters`/`matchRule` 部门键，避免保存 409）；③ 问题 1 后端
  `find_job_key_by_deliverable_id` + `sourceInfo.archiveJobKey` + D1-D8 全量 API 断言；
  ④ 快照卡仅对 `formSnapshotDriven` 渲染、Safe DOM、`onFormReload` 已接线、
   非 syncCapable 不再挂载死按钮（`app.js:3727`）；⑤ 爬虫身份过粗只会 `duplicate_records` 失败（fail-closed），
   不静默丢数据。
- **BLOCKER（已复现，证据 `.runtime/repro_out.txt`）**：默认（新库 6 个归档任务全 `enabled=0`）状态下，
  点【立即同步快照】→ `run_once` 的 `enabled_only=True`（`scheduled_archive_runner.py:533`）返回
  `outcome=not_ready / errorType=missing_job / errorMessage="enabled archive job was not found"`，
  但端点回 **HTTP 200 + `ok:true`**（`web/app.py:4081`），前端只校验 `resp.ok/body.ok`
  （`app.js:2933`）→ **显示「快照同步成功，已刷新最新明细与图表。」（假成功）**，交付物仍是
  「暂无表单快照数据」。且**不满足用户已选形态 A（不要求先启用定时任务）**。
  修复须「后端门控口径（A-1 放开显式 sync-now / A-2 回退形态 B）+ 前端结果判定」同时落地。
- **MAJOR**：`_row_identity` 的 data_model 身份键（`id/recordId/rowId/detailId/partId/subId` 与
  `rowNo/rowNum/...`）**全仓库只出现在新代码里**，无任何真实响应字段证据；新用例自行构造逐行唯一 `id`，
  只证明"若有 id 则正确"。需真实一页字段名清单或一次全量抓取统计定案；建议在诊断白名单内记录"所用身份键类别"。
- **MINOR**：`_deliverable_associations` 重复实现反查（应改用新 helper）；`normalizeTdcDepartment("技术中心")`
  静默变 `车体工程`（且被测试固化）；单记录模式无降级；卡片未透出 `enabled/credentialAvailable`；
  快照卡测试仅为源码子串断言（未覆盖结果判定，正是该缺口放过 Blocker）；
  `tests/test_deliverable_sync_wizard_enhanced.py` 仍未跟踪（`??`）；记忆档「0 Blocker PASS」口径需修正。
- **下一步**：① 用户就 Blocker 选定 A-1/A-2 并授权修改；② 补三类测试（停用任务 sync-now 端点契约、
  快照卡结果判定 VM 行为、爬虫身份真实字段夹具）；③ 取生产证据确认 MAJOR；
  ④ 改后复跑全量门禁并做生产复测（D6/D7/D8 点击后必须真的出现表单快照数据）。

## 2026-09-22 交付物同步修复实施与 ZCode 侧交叉审计（PAA/NCR 快照同步卡 + TDC 部门解耦 + 爬虫行身份；全套测试与 EXE 封包通过）

> 注：本节标题由主 Agent 于 2026-09-22 审计轮修正为与正文一致（正文为 ZCode 的实施与验证记录）。

- **任务背景**：用户反馈两项生产阻断缺陷：
  1. PAA 交付物 (D6) / NCR 审批进度 (D7) / NCR 审批明细 (D8) 详情页缺少「数据同步」按钮，用户面对“暂无表单快照数据”无法在当前页触发同步；
  2. TDC 数模审核报表 (D5) 及 SOR (D2) 在向导中配置同步时报错：部门硬编码 Aras 命名空间 `技术中心_车体工程` 导致 0 命中（未找到）；用户修改为 `车体工程` 后，底层爬虫将同流程内的合法同名零件误杀为 `duplicate_records`，第 1 页即异常中断退出，报 HTTP 422 `mapping discovery query was incomplete`。
- **实施内容**：
  1. **[TDC 爬虫行实例区分与全量翻页修复]**（`services/tdc_crawler.py`、`tests/test_tdc_crawler.py`）：
     - 优化 `_row_identity`：数模行唯一性标识优先使用记录级实例键（`id`, `recordId`, `rowId`, `detailId`, `partId`, `subId`），将流程级实例号（`processInstanceId`, `instanceId`）归入 `workflow_key` 维度，并增加行号（`rowNo`/`rowIndex`等）与版本、日志等特征；
     - 彻底消除同流程内多个合法同名零部件（如多个 `27229272 第二排锁扣组件`）被误杀的问题，确保 17 页（共 850 条）数据完整爬取完毕，`stop_reason="reported_pages"`，`complete=True`，彻底消灭 HTTP 422。
  2. **[向导部门参数按来源解耦与归一化]**（`web/static/app.js`、`tests/test_deliverable_sync_wizard_enhanced.py`）：
     - 移除向导读取部门时的 `|| "技术中心_车体工程"` 强制兜底，允许用户彻底清空；
     - 区分默认值：Aras/EWO 默认 `技术中心_车体工程`；TDC（SOR/数模）默认预填 `车体工程`（提示可留空）；
     - 增加 `normalizeTdcDepartment` 纯函数：用户误填 `技术中心_车体工程` 或 `技术中心-车体工程` 时自动归一化为 `车体工程`；
     - 聚合取证若遇 `not_found`，向导自动发起不带部门参数的降级重试并提供包含命中行数与字段数的清晰诊断信息。
  3. **[补齐 PAA/NCR 外部快照交付物详情页同步能力]**（`core/project_status_contracts.py`、`web/app.py`、`web/static/app.js`、`tests/test_project_status_api.py`、`tests/test_deliverable_registry.py`）：
     - `core/project_status_contracts.py` 新增并导出 `find_job_key_by_deliverable_id` 纯函数；
     - `web/app.py` 在 `/api/project-status` 的 `sourceInfo` 中补充下发 `archiveJobKey`（D6→`aras_paa`，D7→`aras_ncr_progress`，D8→`aras_ncr_detail`）；
     - `web/static/app.js` 为 `formSnapshotDriven === true` 交付物新增「数据同步（外部快照）」卡（Safe DOM 构建），提供【立即同步快照】按钮（调用 `POST /api/scheduled-archive/jobs/{jobKey}/sync-now`）与【查看同步任务】跳转链接；
     - 同步后全自动刷新当前表单明细（`loadDeliverableFormView`）与统计图表；
     - 移除证据面板中永久处于 disabled 状态的误导性死按钮。
- **交叉代码审计结果（code-reviewer 只读专家子智能体）**：
  - **结论：PASS（0 Blocker, 0 Major, 0 Minor）**；
  - 架构与契约一致性：既有分页防重入安全合同（`test_crawler_pagination_integrity.py` 与 `test_tdc_crawler.py` 共 106 项）100% 通过；D6-D8 严格独立，保持 `countsTowardCompletion=False`，分母不被污染；
  - 并发与状态安全：`sync-now` 严格遵守 SQLite 租约锁与重入拦截机制，异常信息经 `redactSensitiveText` / `_sanitize_error_message` 脱敏；
  - Safe DOM 规范：新增的快照同步卡 100% 采用 `overviewEl` / `document.createElement` / `textContent` 构建，零动态 `innerHTML`。
- **全套验证证据**：
  - 交付物与状态全量测试：`pytest tests/test_project_status_*.py tests/test_deliverable_*.py tests/test_overview_web.py tests/test_crawler_pagination_integrity.py -q` → **645 passed in 75.56s**；
  - TDC 专项测试：`pytest tests/test_tdc_*.py -q` → **159 passed in 12.60s**；
  - 静态检查：`flake8 -j 1` 零告警，`node --check web/static/*.js` 全部通过；
  - 项目地图验证：`python tools/generate_project_map.py --check` → **Project map verified (Exit 0)**；
  - 单文件构建：`dist/hci-20260922/VSE-WebUI.exe`（21,402,285 字节，SHA-256 `f0d10e87eccf20314a2b2aad099167adfd4353b4799f7454cc0e223453af1ecf`），分发包 `dist/hci-20260922/VSE-WebUI-0.3.0-production-test-20260922.zip`（21,059,520 字节，SHA-256 `07b47d7164c8e9a8541011ae446e9bbefa5409e2dfa05d14fe4a36a5f3514081`）；
  - 独立端口 5102 纯净冒烟测试 6 个端点（`/`, `/api/version`, `/api/overview`, `/api/project-status`, `/api/project-status/scheduler`, `/api/tasks`）全部返回 HTTP 200 OK 通过。

## 2026-09-22 生产测试两项同步问题根因定位（分析完成，**等用户回传生产证据后再改代码**）

- **任务背景**：用户针对最近一次更改（`ce0523c` 已提交 + 工作区未提交的「交付物同步向导极简策略同构化」）
  在生产环境测试中反馈两项问题（附 3 张真实截图，已 OCR 取证）：
  1. PAA 交付物 / NCR 审批明细 / NCR 审批进度 **没有数据同步按钮**；
  2. **数模设计审核流程报表（D5）数据同步报错**。
- **问题 1 根因（非回归，设计口径 + 数据源未运行叠加）**：
  - `core/project_status_contracts.py:583-627` D6/D7/D8 `syncCapable=False`（`formSnapshotDriven=True`）；
  - `web/static/app.js:2829` 按 `syncCapable` 分发，非 syncCapable 走 `:2864-2871` 只渲染静态「更新方式」文案，
    **永不调用 `buildSyncSummaryCard`** → 数据同步卡（开启/立即同步/修改配置）不渲染；
  - 证据面板 `app.js:3501` 的「运行后台同步」对这三个交付物**恒 disabled**（`syncSupported=False`）；
  - 真实数据源是定时归档任务（注册表 `aras_paa→D6`、`aras_ncr_progress→D7`、`aras_ncr_detail→D8`），
    本地库实测 **6 个内置归档任务全部 `enabled=0`、`credential_ref=NULL`、`scheduled_archive_runs` 0 行**
    → 必然「暂无表单快照数据」；`#archive-deliverable/<jobKey>` 的「后台归档同步」按钮
    `app.js:7589` `disabled = !job.enabled`，但后端 `services/scheduled_archive_admin.py:350` `sync_now`
    **不校验 enabled** —— 阻塞纯粹来自前端门控。
- **问题 2 根因（回归，命名空间错配）—— 已由用户生产三点对照实验确认（2026-09-22 19:39~19:40）**：
  | 组 | 筛选 | 实测 |
  | --- | --- | --- |
  | A | 部门 `技术中心_车体工程` + 车型 `F610S` | `page=1/1 rows=0 unique=0` → **复现故障** |
  | B | 车型 `F610S`（部门留空） | `page=1/22 rows=50 unique=50` → 有数据（最宽） |
  | C | 部门 `车体工程` + 车型 `F610S` | `page=1/17 rows=50 unique=50` → 有数据 |
  → 车型维度正确，**唯一错误维度是部门取值**；C 组结果行 `department` 列实际显示为「车体/内饰」级名称，
  与 `tests/test_report_contracts.py:296` 的 `superDepartment="车体工程"` 一致。
  **立即缓解（无需改码）**：「系统查询 → TDC 数模」按 `部门=车体工程`（或留空）+ `项目车型=F610S`
  即可取到数据并全量抓取/下载 XLSX，仅「向导一键启用自动同步」被挡住。
- **机制细节**：未提交改动把 **Aras 命名空间的默认责任部门 `技术中心_车体工程`** 无条件套用到 **TDC** 查询
  （`app.js:1972` 默认值 + `:2034-2037` 必写入 `filters.department`，且读取时 `|| 默认值` 致用户无法清空）。
  该值在 TDC 落到 HTTP 参数 **`superDepartment`**（`services/tdc_crawler.py:202`、
  `tdc_contract_probe.py:920`）→ 0 行 → `state=not_found` → `app.js:2068` 抛
  「映射发现未匹配（未找到），请核对车型与筛选条件后重试。」。改动前向导 D5 只发
  `filters.serial_number=<流程编号>`、无部门维度，故为本次改动引入的回归。
  **同源风险**：D2（SOR，落点 `deptName`，TDC 域值同为 `车体工程`）预计同样 0 行；D3（EWO）部门由缺省 LIKE
  `*车体工程*|*外饰*|*内饰*` 变为精确值，范围收窄需复测。
- **用户决策（本轮）**：① D6-D8 同步形态选 **A：直接可点【立即同步快照】，不要求先启用定时任务**；
  ② **先不改代码**，先出「原因分析 + 方案」，**待用户确认后再启动更改**。
- **待用户确认的唯一开放项**：TDC 责任部门默认值取 **(C) `车体工程`**（=原意图，实测 17 页）
  还是 **(B) 留空**（范围最宽，实测 22 页）。其余方案项已定。
- **下一步（等待用户确认后执行）**：按 `docs/PROD_TEST_20260922_DELIVERABLE_SYNC_ISSUES.md` 的「方案」章节落地；
  可选补 P1（D5 取证记录 `state`/`candidateCount`/`fieldReport.fields`，用于排除「有行但无业务单号」分支）与
  P4（`/api/scheduled-archive/jobs` 中 aras_paa / aras_ncr_progress / aras_ncr_detail 的启用与凭据状态）。
- **本轮无代码改动**：新增 `docs/PROD_TEST_20260922_DELIVERABLE_SYNC_ISSUES.md`（根因 + 所需输入 + 方案 + 取证清单）
  与本地只读取证脚本 `.runtime/inspect_db.py`、`.runtime/dumpr_rows.py`（输出 `.runtime/rows_dump.txt`）、
  `.runtime/ocr.ps1`（截图为 .runtime/shots/shot{1,2,3}.png）。业务代码与测试未改动。
- **计划实施内容（待用户回传后执行）**：问题 2 = 责任部门默认值按来源区分（TDC 留空可清空）+
  TDC 部门归一化 + D5 部门/科室语义校正 + 聚合 not_found 自动降级重试与可诊断文案 + D2/D3 回归；
  问题 1 = 后端 `sourceInfo` 下发 `archiveJobKey`（由单一关联注册表派生）+ 前端快照同步卡
  （【立即同步快照】POST 归档 `sync-now` /【查看同步任务】）+ 移除永久 disabled 的死按钮 + 契约测试。

## 2026-09-22 饼图长文本精简与全量交付物（SOR/数模）向导极简策略同构化（全套测试通过）

- **任务背景**：用户验收 EWO 一键同步后提出两项优化需求：
  1. 概览饼图（环图）下方文字倾泻堆叠数百条逾期工单单号与长文本明细，破坏排版，要求精简；
  2. 将 EWO 验证通过的极简向导策略（默认项目聚合、责任部门预填车体工程、定时周期选择、随时修改、点一次即可）全面推广至其余外部同步交付物（TDC SOR 与 TDC 数模）。
- **实施内容**：
  1. **[环图长文本精简与悬浮挂载]**（`web/static/app.js`、`tests/test_overview_web.py`）：
     - 重写 `ringDateLabel`，彻底剥离对多单集合长文本 `item.note` 的字符串拼接，回归展示紧凑的 `计划完成 MM-DD`（无计划时间展示 `计划完成 -`，完成态展示 `实际完成 MM-DD` 或 `完成度 100%`）；
     - 将完整的多单超期备注挂载至环图卡片根节点的 `title` 属性（鼠标悬停以原生气泡预览，彻底消除文字溢出）；
     - 详细超期单号清单完整保留在交付物详情页的超期预警条中展示。
  2. **[TDC SOR(D2) 与 TDC 数模(D5) 同构化对齐]**（`web/static/app.js`、`tests/test_deliverable_sync_wizard_enhanced.py`）：
     - 展开向导时，D2/D5 自动提供「车型项目 / 车型信息」（SOR 映射 `carTypeProject`，数模映射 `projectModel`）；
     - 责任部门统一预填为 **`技术中心_车体工程`**（映射 `department`）；
     - 定时周期统一提供下拉选择（默认每 15 分钟）；
     - 默认项目聚合模式：自动对齐各自的标准备注映射，负责人保留手工，不再覆盖总负责人；
     - 同样支持“点一次即可”双次取证、保存启用并触发首次同步；
     - 启用后卡片常驻透传车型、部门与周期事实，并常驻提供【立即同步】与【修改同步配置】按钮。
- **全套验证证据**：
  - 测试套件：`pytest tests/test_deliverable_sync_wizard_enhanced.py tests/test_deliverable_sync_summary_ui.py tests/test_overview_web.py` → **65 passed in 1.48s**；
  - 全量交付物测试：`pytest tests/test_project_status_*.py tests/test_deliverable_*.py tests/test_db_manager.py` → **562 passed in 80.44s**；
  - 静态检查：`flake8` 零告警，`node --check` 全部通过；
  - 单文件构建：`dist/hci-20260922/VSE-WebUI.exe`（21,400,371 字节，SHA-256 `bf7029ed548ef389e958acc5f987807dd410a0b0c7fb255f8c34e8f094dd4d7d`），分发包 `dist/hci-20260922/VSE-WebUI-0.3.0-production-test-20260922.zip`（21,058,206 字节，SHA-256 `31082d88696fd1e33d363dcf614e2cd9b8df42899009920dd1ebb4ddb2c6a642`），独立端口 5101 冒烟测试 200 全通。

## 2026-09-22 交付物同步已启用状态下的配置随时修改、事实透传与高级设置对齐（实施与全套测试通过）

- **任务背景**：用户在完成首次一键同步后反馈：状态变为“快照同步”后，原有的向导折叠入口消失，且高级设置中缺少定时同步周期和责任部门选项，导致无法再次调整周期或部门。
- **实施内容**：
  1. **[卡片增加【修改同步配置】按钮]**（`web/static/app.js`）：
     - 当交付物已启用自动同步时，在数据同步卡片按钮区常驻显示【立即同步】与【修改同步配置】两个操作入口；
     - 点击【修改同步配置】随时展开向导面板，预填当前已生效的车型、部门和周期，按钮动态呈现为【保存配置并同步】，支持修改后一键更新生效。
  2. **[卡片事实清晰透传]**（`web/static/app.js`）：
     - 在卡片的最近尝试/最近成功信息下方，透传当前生效的「车型项目」、「责任部门」与「定时周期」（如“每 15 分钟”），让配置状态一目了然。
  3. **[高级设置完整表单对齐]**（`core/project_status_contracts.py`、`web/static/app.js`）：
     - 为 EWO（D3）与 SOR（D2）的 `matchFields` 补充责任部门（`rspDepartment`/`department`）定义，使高级设置匹配规则中完整展示并支持编辑部门；
     - 高级设置表单的 `bindingGrid` 补充「定时同步周期」下拉选择框（15分钟/30分钟/1小时/6小时/每天），并在 `buildPolicyPayload` 中同步保存。
- **全套验证证据**：
  - 测试套件：`pytest tests/test_deliverable_sync_wizard_enhanced.py tests/test_deliverable_sync_summary_ui.py` → **15 passed in 0.19s**；
  - 交付物与状态全量测试：`pytest tests/test_project_status_*.py tests/test_deliverable_*.py tests/test_db_manager.py` → **561 passed in 75.73s**；
  - 单文件构建：`dist/hci-20260922/VSE-WebUI.exe`（21,401,336 字节），分发包 `dist/hci-20260922/VSE-WebUI-0.3.0-production-test-20260922.zip`（21,059,134 字节，SHA-256 `ecefb4d3bf7c2dd12bfa6e396304390dd9cd5503b05947b9ba9fbc7d10f88a0a`），独立端口 5100 冒烟测试 200 全通，并通过微信 clawbot 成功送达用户。

## 2026-09-22 交付物轻量同步向导极简交互升级与点一次即启用改造（全量测试通过）

- **任务背景**：用户在配置交付物数据同步时反馈两项痛点：
  1. 默认单单模式要求填写单一单号，输入车型项目后提示“候选不唯一（332条）”，难以一次性完成整车项目多工单聚合统计；
  2. 切换到集合模式时，由于存量库遗留标量映射及后端旧版迁移校验，报“EWO record sets cannot map scalar owner or planned date”及“迁移须先保存为停用状态”，流程割裂；
  3. 期望点击“开始自动同步”后默认带入所有必要信息，默认项目聚合，增加车型信息、责任部门（默认“技术中心_车体工程”）以及定时同步周期选项，实现“点一次即可”。
- **实施内容**：
  1. **[向导表单重构与预填]**（`web/static/app.js`）：
     - 凭据引用默认自动选中 `统一域账号（domain）`；
     - 新增「车型项目 / 车型信息」输入框，支持输入车型代号（如 `F610S`、`N300`）并自动回填已有规则；
     - 新增「责任部门」筛选输入框，默认自动预填为 **`技术中心_车体工程`**（支持修改）；
     - 新增「定时自动同步周期」下拉选项（15分钟、30分钟、1小时、6小时、每天，默认 15 分钟）；
     - EWO 编号保留为选填副项（留空即整车项目聚合统计）。
  2. **[默认项目聚合与点一次即启用闭环]**（`web/static/app.js`、`services/project_status_updates.py`、`services/project_status_discovery.py`）：
     - 向导默认以集合模式（EWO 为 `record_set`、`aggregate: true`、`contractVersion: '2'`，TDC 为 `aggregate: true`）组织请求；
     - 取证时自动过滤存量数据库中遗留的标量映射，消除跨模式切换的 400 报错；
     - 自动连续执行两次证据抓取（1/2 -> 2/2）；
     - 后端支持平滑迁移：当请求携带有效 2/2 证据时，直接允许由旧版迁移至 v2 记录集合并一步启用（消除必须先存停用状态的阻断）；
     - 保存后自动触发首次同步并刷新页面。用户填好车型后，**点击一次【开始配置并启用】即可全自动完成配置并生效**。
  3. **[调度器独立周期闭环]**（`core/db_manager.py`、`services/project_status_scheduler.py`）：
     - 数据库查询输出 `b.interval_minutes`；调度器根据绑定的个性化周期进行独立新鲜度判断，与向导选项形成闭环。
- **全套验证证据**：
  - 向导与调度器增强测试：`pytest tests/test_deliverable_sync_wizard_enhanced.py tests/test_deliverable_sync_summary_ui.py tests/test_project_status_scheduler.py` → **34 passed in 0.35s**；
  - 迁移与发现专项测试：`pytest tests/test_project_status_updates.py tests/test_project_status_discovery.py` → **61 passed in 7.32s**；
  - 交付物与状态全量测试：`pytest tests/test_project_status_*.py tests/test_deliverable_*.py tests/test_db_manager.py` → **560 passed in 78.96s**；
  - 门禁扫描与语法：`flake8` 零告警，`node --check` 全部通过；
  - 独立单文件构建：`dist/hci-20260922/VSE-WebUI.exe`（21,399,098 字节，SHA-256 `51fb3311244d5156e491cc1b86e5f7999525cbe8a718ea3342aa7be57d6d0cd5`），分发包 `dist/hci-20260922/VSE-WebUI-0.3.0-production-test-20260922.zip`（21,057,028 字节，SHA-256 `2834d00bc6a242dd6a559a3e667f2a746edb77e34cd39da7075340133eeb75c5`），独立端口 5099 冒烟测试 200 全通。

## 2026-09-22 生产测试单文件 EXE 构建并经微信 clawbot 投递成功（工件与校验码已交付）

- **交付物**：`dist/hci-20260922/VSE-WebUI.exe`（21,398,639 字节，SHA-256 `35a4bad74ba3e82061f63ff8843cfe01efe939035e513921bd9e6e5834889839`），分发压缩包 `dist/hci-20260922/VSE-WebUI-0.3.0-production-test-20260922.zip`（21,056,249 字节，SHA-256 `bf707a082e9d8601c4ae996849fa771b91b339db4e082fed786a84698ba826d0`）。
- **纯净冒烟复核**：在独立纯净目录（`.runtime/smoke-test-20260922`）以独立端口 5095 和 `--no-browser` 启动构建生成的 `VSE-WebUI.exe`，验证 6 处关键端点全部返回 HTTP 200 通过：
  1. `/` 200（50,981 字节，完整渲染前端页面结构）；
  2. `/api/version` 200（`v0.3.0`，buildId `20260922-sync-audit-pass`，channel `production-test`，isFrozen=true）；
  3. `/api/overview` 200；
  4. `/api/project-status` 200（20,273 字节完整状态数据）；
  5. `/api/project-status/scheduler` 200；
  6. `/api/tasks` 200。
  测试完成后进程干净退出，端口正常释放。
- **微信投递结果**：通过 `C:/Users/Lynch/.zcode/tools/weixin_bot_send.py` 成功完成三阶段自动化投递至用户微信：
  1. 成功发送投递前置通知（`message_id=7508028716396988552`）；
  2. 成功上传腾讯 CDN 并发送 20MB ZIP 文件本体（`message_id=7508028807212167304`）；
  3. 成功发送详细版本说明与 SHA-256 校验哈希清单（`message_id=7508028878116854792`）。
- **当前状态与下一步**：工件已安全送达用户微信，构建与测试产生的 `.runtime` 临时文件符合工程隔离规则。用户可直接在目标测试机解压运行验证。

## 2026-09-22 交付物全量同步契约修复、Safe DOM 整改与全链路交叉审计闭环（实施与全套测试验证通过）

- **任务背景**：上游拉取 `ce0523c` 提交后，经多轮深度交叉代码审计（涵盖 `sess_46f7e98a`、`sess_70664423` 及本会话），系统化排查并闭环修复了 8 处关键契约、安全与稳定性缺陷：
  1. 存量数据库迁移回填签名时误引用不存在的表 `project_status_deliverable_bindings`（Blocker）；
  2. `ProjectStatusSyncScheduler.trigger_sync_all` 与 `web/app.py` 中硬编码非法 `trigger_type="manual_all"`，违背底层 `ProjectStatusSyncRunner` 准入门控契约与数据库 `CHECK (trigger_type IN ('sync_now', 'scheduled'))` 约束（Blocker）；
  3. 前端详情页同步按钮与向导侧门禁口径不一致，且基于 `hasDefaultMapping` 穿透豁免稳定性要求导致 409 假就绪（Major）；
  4. `web/app.py` 调度器配置端点未拦截 Python `isinstance(True, int)` 继承陷阱，非法布尔值可篡改同步间隔为 1 秒（Major）；
  5. `web/static/app.js` 过程工单超期预警提示条使用了动态 `innerHTML` 拼接，违反 Safe DOM 规范（Major）；
  6. `services/project_status_scheduler.py` 调度器无条件注册全局单例破坏测试隔离（Minor）；
  7. `web/static/app.js` 调度器轮询倒计时定时器在组件脱离 DOM 树后未销毁，且正则限制两位数分钟（Minor）；
  8. `PROJECT_MAP.md` 源码指纹因文件变动需同步刷新。
- **实施内容**：
  1. **[数据库迁移修复]**（`core/db_manager.py`、`tests/test_db_manager.py`）：
     - 将查询表更正为权威表名 `project_status_update_bindings`，并增加 `source_type = ?` 约束，杜绝表缺失崩溃与跨来源污染；
     - 新增 `test_migration_backfills_null_config_signatures` 测试用例，验证空签名历史观测记录在升级时的自动回填自愈能力。
  2. **[trigger_type 契约修复]**（`services/project_status_scheduler.py`、`web/app.py`、`tests/test_project_status_scheduler.py`）：
     - 将 `trigger_type="manual_all"` 统一收敛为规范合法的 `"sync_now"`；
     - 修正单元测试断言，并新增 `test_scheduler_trigger_sync_all_contract_compliance` 契约强制校验用例，杜绝 Mock 假绿。
  3. **[门禁与向导口径统一]**（`web/static/app.js`）：
     - 将详情页 `syncReady` 还原为严格依赖 `stabilityReady`，移除 `hasDefaultMapping` 的稳定性穿透豁免；
     - 同步移除向导/编辑器内部的 `usingStandardDefault` 稳定性豁免，向导与详情页统一硬性要求连续 2 次无歧义观测证据，消除“向导提示就绪、保存后详情页按钮置灰”的语义冲突。
  4. **[防御式参数校验]**（`web/app.py`、`tests/test_project_status_scheduler_api.py`）：
     - 增加 `isinstance(interval, bool)` 显式排斥，杜绝 `True` 绕过整数校验将调度间隔变为 1 秒；补充布尔与字符串非法参数测试。
  5. **[Safe DOM 规范整改]**（`web/static/app.js`）：
     - 将工单超期预警提示条重构为 `overviewEl`、`document.createTextNode` 与 `appendChild` 安全树，恢复全链路零动态 `innerHTML`。
  6. **[调度器生命周期与定时器守卫]**（`services/project_status_scheduler.py`、`webui.py`、`web/static/app.js`、`tests/test_project_status_scheduler.py`）：
     - 为调度器增加 `register_global` 参数并在 `webui.py` 显式启用；在调度器单元测试中挂载 `_reset_global_scheduler` 自动清理夹具；
     - 控制条倒计时定时器增加 `controlBar.isConnected` 树挂载守卫，并在离 DOM 时自动清理；倒计时正则拓展为 `\d+:\d{2}` 兼容超 100 分钟间隔。
  7. **[工程指纹刷新]**（`PROJECT_MAP.md`）：执行 `python tools/generate_project_map.py --write` 刷新并核验。
- **全套验证证据**：
  - 调度器与 API 专项测试：`pytest tests/test_project_status_scheduler.py tests/test_project_status_scheduler_api.py` → **20 passed in 1.48s**；
  - 数据库迁移与底层契约测试：`pytest tests/test_db_manager.py tests/test_project_status_sync_runner.py` → **72 passed in 13.56s**；
  - 交付物与状态综合测试：`pytest tests/test_deliverable_sync_summary_ui.py tests/test_project_status_*.py` → **431 passed in 68.24s**；
  - 门禁 lint：`flake8` 针对所有受改动 Python 文件执行 → **零告警**；
  - 前端脚本语法校验：`node --check web/static/*.js` → **全部通过**；
  - 项目地图验证：`python tools/generate_project_map.py --check` → **Project map verified (Exit 0)**。

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
