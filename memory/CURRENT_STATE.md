# Current State

> 本文件已按 2026-10-23 的上下文治理决定裁剪：只保留最近条目与"当前前沿"。
> 更早条目完整保存在 [归档文件](archive/CURRENT_STATE_ARCHIVE_20261023.md)（88 条 → 保留 12 条 + 本节「当前前沿」）。
> 恢复状态时**不要**再通读全文；先读本节，再按需查归档。

## 当前前沿（2026-10-28 · v2 人机交互重构，分支 refactor/ux-v2）

- **已交付测试**：app 2.3.0（`dist/v2-test/updates/vse-app-2.3.0.vsepkg`，1 MB）+ 新启动器整包
  `dist/v2-test/VSE-Toolbox-v2.3-test.zip`（45.5 MB，超出远程发送上限，只能本机取）。签名密钥是 TEST-ONLY。
- **本轮完成**：C1 多项目（一个项目一个数据文件夹，`vse_boot/projects.py`）；D2/D3 一键开启自动同步
  （`plugins/project_overview/static/auto-sync.js`，复用 `deliverable/enable-flow.js`）；交付物详情简洁视图
  （`deliverable/simple.js`）；取消「子系统开发策略」（`PROJECT_STATUS_RETIRED_DELIVERABLES`，只隐藏不删数据）。
- **验证**：全量回归 3418 passed / 6 skipped；真实 exe 端到端 21/21（含新建项目→重启→独立数据库→切回）；
  一键开启在浏览器里用伪造响应走通（真实 TDC/Aras 取证**未验证**）。
- **限制 / 未做**：只有当前项目在后台同步；48 个车型代码清单未拿到（车型仍是文本框）；F1 报告页内一键生成；
  M1 第 3 片（token cookie、开机自启开关、pywebview、L0 原生启动器）；生产问题「数模审批流程不能正常同步」（用户让先做 v2）。
- **多项目要点**：主项目 = 安装根（兼容旧数据）；切换 = 写 `state/projects.json` + `restart.request`；
  试用快照按项目存在 `state/db-snapshots/<id>/`，`trialDatabase` 记录恢复目标。只装 app 包而不换启动器时，
  `vse_boot.projects` 不存在 → 工作台按单项目运行（切换器隐藏）。

## 调度协议前沿（2026-10-23）

- **目标**：完成调度协议三项优化——A 顾问调用并行化（已落地）、B 上下文交接阈值、C 并行度标定。
- **已完成并验证**：
  - A → `docs/AGENT_DISPATCH_PROTOCOL_20261022.md` §10 + §9.5 修正；`tools/agents/README.md` 指针。
    `python -m pytest tests/test_dispatch_wait_protocol.py -q` → 19 passed。
  - C → 4 组配对切片在 `.runtime/calib/runs/`：g2 1.19×、g3 1.75×、**g4 1.49×**（双单元，
    单元 132–172s，满足 ≥120s）、g1（对照）1.40×；**三组合格均值 1.48×，区间 1.19–1.75**。
    并行墙钟 − max(单元) 仅 7.8–10.3s（即墙钟≈最长单元；**重叠比例未由时间线核验**）；
    比值不随单元变大单调上升，争用系数 c ∈ [0.88, 1.74]。门禁：g2/g3/g4 各自目录 pytest 全绿
    （130/130/209 passed）。1.37× 只能列为**未验证的排期假设**（顾问 `23c39339` 收紧措辞）。
- **B 已落地**：`CURRENT_STATE.md` 270,588B → **36,929B**（76 条原样归档到
  `memory/archive/CURRENT_STATE_ARCHIVE_20261023.md`）；恢复规则改为"先读当前前沿，历史查归档"，
  180k 降级为**交接评估点**（150k 外置证据 / 200k 前收尾）。重建实测：交接包 15.1s / 2,536B，
  只读交接包 4/4 控制问题答对，并由接手者完成一次**有门禁续作**（2 门禁 + 1 编辑 + 自验）。
  缺口：全量恢复的**实际输入 token** 未计量，只有字节折算。
- **C 已冻结为探索性观测**（顾问 `b8fff544` 判 partial）：可对外报 1.19–1.75 / 均值 1.48，
  不可宣布"可推广标定"。升级门槛 = 同批单元 × 串并行 × 均 ≥120s × 同模型 × 独立初始工作区。
- **阻塞（能力，不是取舍）**：成员名额上限 8 已满，5 个旧成员 resume 失败，只剩 3 个可用
  （2 global + 1 cn），"同一批单元 + 同模型 + 零暴露"需要 3 个同模型成员，本会话不可得。
- **第 3 写通道**：暂缓（顾问 D3 = 证据不足，需 ≥3 组真实批次 2/3 通道配对）。
- **顾问路由（2026-10-23 用户选择「多用 astra」）**：`codex-readonly` 不指定 `--profile` 时，
  普通决定 → `astra-medium`、高风险 → `astra-high`；`sol-*` 降为显式兼容档。已同步
  `advisor_core.py`（两个常量）/ `expert_advisor.py`（帮助）/ `SKILL.md`（档位表）/
  `CONTRACT.md`（三处）/ 本仓库 `AGENTS.md`；技能自带测试 **170 passed**，dry-run 三条路由均已验。
- **IM 交付待办（2026-10-26）**：用户在 QQ/微信要 webui 测试包时，**只** `present`
  `dist/hci-20261026/im-delivery/` 下的三个分卷 `VSE-WebUI.zip.part1..3`（各 ≈14.2 MB），
  **一次 present 调用列全三个**，不要重新打包。
  实测教训：42.5 MB 整包 → `workspace-file/too-large`（网关 32 MB 上限）；
  20.3 MB 两分卷 → QQ 侧立即 `Error`（QQ 实际上限在 9.2–20.3 MB 之间）；
  9.2 MB 的 `VSE-WebUI.exe` 能发出去但**单独无用**（onedir，缺 `_internal/` 与 `plugins/`）。
  合并后 42,493,183 字节，SHA256 `64a5b6d4…d17bfb1`；详见 `.runtime/im-send-instruction.md`。
  IM 渠道模型已修为 `cn:deepseek-v4.1-flash`（`tools/fix-im-channel-model.ps1`，19:11 重启后生效；
  telegram 仍因凭据不足起不来）。
- **三个自证偏差（引用本文件时必须避免）**：把"规则已写入"当"效果已验证"；把"一次成功"当"稳定"；
  把"三组部分合格"当"完整门槛"。A 只有 1 次合格样本（+65s），只算验证过一次。

## 2026-10-27 架构评审裁决 + 同步范围三守卫（顾问方案 R3/R9/R10 落地）

- **来源**：用户拿 `docs/PROMPT_SYNC_SCOPE_ARCH_20261027.md` 咨询 Claude，回了一份三阶段方案；
  主代理按代码事实逐项裁决，先落地「与现有实现不冲突、且直接消除静默错误」的三项。
- **已落地（含测试）**：
  1. **R3 科室两键互斥**：`_section_scope_conflict_error`（services/project_status_updates）；
     保存入口 422 + 运行前就绪检查 raise，不再让连接器静默丢弃单值 `section`（多算）。
  2. **R10 归档拒绝收窄键**：`scheduled_archive_connectors._checked_filters(narrow_keys=...)`，
     `sections` 出现时给可执行文案（归档存的是上游原始导出，无本地收窄）；`section` 存量仍可用。
  3. **R9 字段契约版本**：`core/project_status_contracts.MATCH_FIELD_CONTRACT`（2026-10-27.1）
     → `sourceInfo.matchFieldContract`；前端同值常量 + 不一致时向导顶部红色提示
     「重启 VSE-WebUI 并强制刷新」，直接对准「代码改了界面没变」的发布链路问题。
  4. 插件静态资源加 `Cache-Control: no-cache, must-revalidate`（`web/app.py` after_request，
     仅 `/plugins/` 前缀），ES module 子模块不再留旧副本。
  5. 摘要标签补 `sections: "科室范围"`（`details/sync-settings-logic.js`）。
- **未采纳/待拍板（方案阶段 2–3）**：`MatchFieldSpec` 声明化（收益大但动契约派生，需先锁「派生==字面量」）；
  向导删除「责任部门」框 + 存量 chip 一键迁移（涉及用户可见行为，需用户决定）；`section` 停用（同上）。
- **已核验的取证项**（回答方案 §3.4）：D5 `matchKeys − filterKeys` = `{aggregate, reportType,
  documentNo, documentNos, sections}`（全部可归类，无需再猜）；`data/vse_toolbox.db` 是空开发库，
  **存量是否有 `section` 绑定仍需在生产库上查**（用户当前绑定确有 `department=车体工程`）。
- **验证**：新增 `tests/test_sync_scope_contract_guards.py`（8 项，含归档拒绝与前端常量对齐）；
  全量 `python -m pytest tests -q` → **3352 passed / 6 skipped**；`generate_project_map.py --check` 通过。
- **教训**：`tests/p1d_frontend_fixture.py` 的 `./policy-logic.js` 是合成桩，
  **policy.js 新增任何具名 import 都必须同步加进桩的 base 对象**，否则 VM link 直接失败（本轮踩过一次）。

## 2026-10-26 D5 数模同步增加「按科室筛选」（默认五科室）

- **用户口径**：按部门筛不可靠——同一科室的人有挂在「技术中心」、有挂在「车体工程」，
  因此数模设计审核流程报表（D5）同步向导增加科室多选，默认车体科、车身科、内饰科、
  外饰科、车体架构集成科。
- **落地层选择**：TDC 的科室查询参数（HTTP `department`，行内第 5 列同名但语义为科室级）
  只接受单值，多值能力未验证 → 科室集合**不进上游**，改为抓取后按行内科室列本地收窄，
  归集口径复用 `core/section_rollup.resolve_section`（与看板同源，历史名如「结构工程科」
  「BE 车身科」按规则命中）。存在 `sections` 时单值 `section` 一律不发上游（否则其它科室
  的行在抓取阶段就被丢掉 = 静默少算）。
- **契约**：D5 `matchKeys` 增 `sections`（不进 `filterKeys`——它不是上游查询键，
  `test_declared_filter_keys_match_connector_consumption` 要求 filterKeys 必须改变上游过滤器）；
  新增能力标志 `sectionPresets`，`sourceInfo.sectionPresets` 下发归集目标（默认五科室）。
- **接线**：`services/project_status_updates` 校验（复用 `_valid_section_scope` 形状）；
  `SyncBindingContext.section_rollup` 由 runner 注入（connector 不得访问 DB）；
  discovery 走 `_MAPPING_DISCOVERY_RULE_FIELDS` 的 `sections` 收口 + 同一收窄函数；
  前端 `wizardInitialValues` 默认勾选预设、D5 部门默认留空、高级设置保存保留 `sections`。
- **fail-closed**：整批行缺科室列 → raise（结构漂移，不写空结果）；未登记历史科室值计入
  `tdc_section_narrowed` 诊断计数后被排除。
- **验证**：新增 `tests/test_project_status_data_model_sections.py`（32 项，含 collect 级）、
  `tests/test_plugin_overview_data_model_sections.py`（3 项，真实 policy-logic.js）、
  `tests/test_plugin_overview_wizard_sections.py`（3 项，真实 policy.js 渲染接线）；
  全量 `python -m pytest tests -q` → **3344 passed / 6 skipped**；`generate_project_map.py --check` 通过。
- **未做/取舍**：存量绑定（只有 `department=车体工程`）不自动迁移——打开向导会看到科室五科室
  默认勾选 + 部门回填，用户清空部门并保存后才切换到纯科室口径（避免未经同意改变已发布报表）；
  定时归档任务（`scheduled_archive_connectors`）的数模过滤器未接 `sections`。
- **顾问**：本决策按流程发起一次 live 咨询（task `TASK-20261026-D5-SECTIONS-01`，`--risk data-loss`，
  dry-run 通过），实际调用在 580s 内无返回、账本无记录，按 skill 规则停止该路由、不重试；
  上述方案为主代理自行定案。

## 2026-10-23 调度协议 §10 落地：顾问调用并行化（astra 顾问 1=adopted）

- **顾问**：run `94ca423fbd434d07b5f243f72c74c6be`（codex-readonly / **astra-high** /
  gpt-6-astra / effort high / `--risk concurrency`，65s，14,087 in / 1,114 out）。
  裁决 1=**adopted**、2=partial、3=partial。
- **动因（实测）**：会话 `9a9119bd` 两次顾问调用纯阻塞——发出后只发一次
  `job_output(wait)`，等待期零并行工作，合计 4.8 min = 该会话活跃时间 31.6 min 的 **15%**。
  同会话 100 个后台 job 合计仅 514s、0 个 ≥300s：后台化没问题，问题是**后台化后自堵**。
- **落地**：`docs/AGENT_DISPATCH_PROTOCOL_20261022.md` 新增 §10——10.1 动因、10.2 等待期
  白名单/黑名单（只读取证·文档骨架·无关成员任务·无关定向门禁 vs 依赖结论的实现/接口定稿/
  集成/假定结论的全量门禁）、10.3 记账与净收益规则、10.4 反例与推翻条件、10.5 与 §8 边界
  （只改「怎么等」不改「何时问」，顾问仍不进门禁）、10.6 单元时长模型。
- **净收益规则**：净收益 = `hidden_wait_s` − (`coord_s` + `discarded_s`)；连续 3 次 ≤ 0 即撤销 §10。
  不允许只记 hidden_wait 就宣称「已并行化」。
- **§9.5 判据修正**：原「并行度 < 1.3 即推翻」作废——< 1.3 只是未达标，不能证伪 1.37×；
  改为看**区间上界是否 < 1.37**，并改 **3 组配对交替**（串行/并行同基线、统一资源与门禁），
  3 组仅初筛，之后仍需真实任务验证。
- **副产品（实测 + 建模）**：成员 spawn→claim 7–9s；**评审启动间隔 26s**（两单元 19:20:56
  同时完成，评审 19:21:22 才 claim，属主代理反应时间，独立优化项）。
  并行度 = (7 + 2.82u)/(33 + 1.82u)：u=22s → 0.95×（实测 0.93×，吻合）、60s → 1.24×、
  120s → 1.37×、300s → 1.47×。**故标定切片单元须 ≥ 2 min**。
- **未做**：~~C 的 3 组配对未跑；B 的交接阈值需一次真实交接实测~~ → **2026-10-23 晚已更新**：
  C 已跑 4 组配对（1.19/1.49/1.75，均值 1.48，冻结为探索性观测），B 已实测并裁剪
  （270,588B → 36,929B + 有门禁续作）。**本条状态以文件顶部「当前前沿」为准。**

## 2026-10-23 D5 方案 B 完成：含页面面板（一个人/几条/基本不动）

- **维护规模已确认**：一个人维护、几条手输、定一次基本不动。故按最小形态实现，
  不做批量导入、权限、审计日志（存储里已有 operator/basis/revision，够用）。
- **页面**：`plugins/project_overview/static/deliverable/arch-links.js`，挂进
  `form-analysis.js` 的 D5 明细页（与关注清单同级）。折叠面板：选车型（datalist）→
  粘贴单号（一行一个）→ 保存/清空；展示四态与「仅项目件 / 关联 / 合计」三个数字。
  四态标签只读后端 `statusLabel`，前端不重算口径。
- **样式**：`plugins/project_overview/static/deliverable.css` 增加
  `is-matched/is-mismatch/is-conflict/form-arch-links-summary`（复用 `form-watchlist*` 结构）。
- **接口**：`GET/POST /api/p/project-overview/vehicle-arch-links`；view 载荷
  `vehicleArchLinks` 含 `scope=combined / countUnit=instance / vehicles[].{projectOnly,
  linkedArchitecture, combined, links[]}`。
- **验证**：`tests/test_plugin_overview_arch_links.py` 7 项（含 node --check 兜底）、
  `tests/test_data_model_vehicle_links.py` 16 项；全量 pytest 见本轮日志。
- **已知取舍**：阶段图是行级（746 行），`vehicleArchLinks` 汇总与工作簿是实例级（228 单）。
  字段已分别命名（`rows` / `instances`），但同一页并排仍可能被误读，是否统一待定。

## 2026-10-23 D5 方案 B 实施：车型 ↔ 架构件单人工声明

- **用户决策**：接受方案 B——车型合计 = 项目件 + 人工指定且已确认关联的架构件；
  保留"仅项目件"数字作对照。顾问（run `b039a80…`, astra-medium）三项全采纳。
- **已落地的结构**：
  - 表 `data_model_vehicle_arch_links`（`core/db_common.py` TABLE_DEFINITIONS，版本化，
    同 (车型,单号) 重复声明新增 revision 并置旧行为 inactive）。
  - `core/repos/data_model_vehicle_links.py`（list / replace / clear，撤销保留历史）；
    以 mixin 方式注册进 `DatabaseManager`（一行 import + 一行继承）。
  - `services/data_model_vehicle_links.py`：单号解析、**失配四态**
    （已匹配/来源不符/快照缺失/键冲突）、`relabel_linked_rows`、方案 B 汇总。
  - `deliverable_form_analysis.view()` 增加 `vehicleArchLinks` 载荷；读取侧给已匹配的
    架构件行打 `linkedVehicle`，阶段图据此显示「F620S · 关联架构件」分组。
  - `plugins/project_overview`：`GET/POST /vehicle-arch-links`（写路由过 `local_guard`）。
- **计数口径修正**：首版汇总把**行**当实例（746 行报成 746 单），已改为实例级并同时给出
  `rows` 与 `instances` 两个字段；阶段图仍是行级（746），与汇总（228）单位不同，
  文档已明示，勿混读。
- **实测**（真实导出 + 一条声明 `Ar-L-3D-0002 → F620S`）：
  F620S 项目件 228 实例 / 746 行 / 47.55%；关联架构件 1 单；合计 229 实例 47.8%；
  阶段图 Ar-L 由 277 行降为 273 行，新增「F620S · 关联架构件 4 行」。
- **验证**：`tests/test_data_model_vehicle_links.py` 16 项；全量 pytest
  **3273 passed / 6 skipped**。
- **未做**：声明清单的页面编辑器（现仅接口可用）；顾问建议的"版本冻结/历史重算"未实现，
  当前报表绑定"最新声明"。

## 2026-10-23 D5 分组方案定稿（架构件按平台单列，台账链路已取消）

> **已被本文件更晚的「2026-10-23 D5 方案 B」条目取代**：经用户确认，允许人工声明且已确认关联的
> 架构件并入车型合计，同时保留「仅项目件」数字作对照。本条的"不并入任何车型合计"不再是终态，
> 但"不得用 SOR/流水号前缀/TDC 查询去推断归属"这条仍然有效。

- **用户最终确认**：项目派单台账**不存在**，"这个就是 TDC 的查询结果"。
  按车型查询在结构上不返回 `Ar-` 行（实测报表 36 无一条 `Ar-`、报表 37 无一条 `F620S`，
  交集为空），因此台账无法提供"平台单属于哪个车型"的关系，(a) 作废、方案就此定稿。
- **定稿口径**：项目件按车型统计并计入车型合计；架构件按架构平台单列，不并入任何车型合计。
- **代码清理**：删除 `ATTRIBUTION_LEDGER` 常量、`dimension_fields()` 的 `ledger_vehicle` 参数
  与全部台账分支（`resolve_dimensions` / `group_label` / `_group_key` / `summarize_instances`）。
  新增反向锁测试：`dimension_fields` 签名里不得再出现 `ledger_vehicle`/`ewo`/`document`，
  且模块不得再有 `ATTRIBUTION_LEDGER`。
- **定稿数字**（1037 行 / 322 实例）：F620S 项目件 228 单（已完成 97 / 审批中 107 /
  已废弃 24，完成率 47.55%）；Ar-L 架构件 89 单（70/6/13，92.11%）；
  Ar-L+ 架构件 5 单（2/0/3，100%）。车型合计不含架构件。
- **验证**：`tests/test_data_model_attribution.py` 35 项；全量 pytest
  **3257 passed / 6 skipped**；工作簿与 PROJECT_MAP 已按定稿口径重出。
- **剩余唯一待定**：D5 是否显示 `已废弃`（归档链路已剔除，放开会影响所有 TDC 交付物）。
- **若将来出现独立于 TDC 的派单关系来源**：开新决策、显式加参数并补口径评审，
  不得改用 SOR 号或流水单号顶替。

## 2026-10-23 D5 口径修正：项目件按车型 / 架构件按平台（SOR 归属已删除）

- **用户纠正（决定性）**：`EWO/SOR号` 与数模审批单无关——它是零件定点/SOR 文档编号。
  早期实现把 `SGMW-<车型>-SOR####` 当"该单服务该车型"的证据，导致架构件 94 单里
  **34 单被错误归到车型**（F710S 34 / F620S 2），是假信号。
  实测反证：项目件 228 实例中 35 个带车型 SOR，其中 **3 个发布车型 F620S 而 SOR 写 F710S**；
  若 SOR 是发布归属应为 0。
- **用户确认业务口径 = a + c**：
  - a：车型归属的唯一权威来源是**外部项目派单台账**；
  - c：架构件本就不该归到单一车型，**按架构平台单列统计**。
- **已改**：`services/data_model_attribution.py` 重写——`dimension_fields()` 只吃
  `项目/车型`（+ 可选 `ledger_vehicle`），无 EWO/流水入参；归属方式只剩
  自身车型 / 平台单列 / 台账归属；新增 `summarize_platforms()`；`group_label`
  产出 `F620S · 项目件` / `Ar-L · 架构件`；`summarize_vehicles()` 只含项目件。
  顺带删除已无意义的 `unify_rows`（实例级统一只是为 SOR 证据投票服务的）。
- **旧快照**：`_enrich_data_model_dimensions` 现在会**改写**早期版本写下的
  `SOR号证据`/`平台池` 归属（`resolve_dimensions` 同样把非现行取值重算）。
- **新数字**（1037 行 / 322 实例）：F620S 项目件 228 单（47.55%）、
  Ar-L 架构件 89 单（92.11%）、Ar-L+ 架构件 5 单（100%）；车型合计不含架构件。
- **验证**：`tests/test_data_model_attribution.py` 35 项（含"SOR 无入参"的锁死断言）；
  全量 pytest **3257 passed / 6 skipped**；工作簿按新口径重出。
- **下一步**：台账接入（`ledger_vehicle` → 归属方式「台账归属」），需先拿到
  单号↔车型↔依据↔生效期的台账数据；D5 是否显示 `已废弃` 仍待定（上游已剔除）。

## 2026-10-23 D5 归集评审 R1–R4 已全部修复（分支 `feat/d5-arch-part-attribution`）

- **背景**：`docs/CODE_REVIEW_D5_20261023.md` 对 2 个本地提交给出"建议暂不合并"，
  四条发现经本地逐条核实**全部成立**，已全部修复并补回归测试。
- **R1 [P1] 复合标签当 stage 值查库 → 点柱条明细归零**：根因是阶段图 label 从原始
  `stage` 值变成 `F620S · 项目件` 复合标签，而 `stage` 筛选下推 SQL 比对 `stage_key`。
  修复：`_split_data_model_group_filters` 把复合标签从 SQL 层剔除（原始值仍下推），
  改在读取侧用同一个 `group_label` 原语过滤；`rows()` 的 SQL 分页快路径同步退出。
  新增端到端回归：柱条 `total` 必须等于点击后 `summary.total`。
- **R2 [P2] 独立表单页仍分开 F620S 与 Ar-L**：`flatten_rows` 为 D5 展平
  `_dataSource/_vehicle/_attribution/_archPlatform/_group`；页面新增
  「归集车型状态（含架构件）」图表 + 「数据来源/归集车型」筛选；原 `_stage` 图表保留。
- **R3 [P2] 旧快照兜底不读 values**：新增 `_enrich_data_model_dimensions`，读取侧用保留的
  47 列值重算缺失键（已有键不覆盖），`rows()`/`view()`/趋势链路都接入。
- **R4 [P2] 平台池被合并**：`summarize_instances` 分组键改为 `(车型, 来源, 平台池平台)`；
  实测平台池 58 = Ar-L 54 + Ar-L+ 4。
- **验证**：`tests/test_data_model_attribution.py` 34 项；全量 pytest **3256 passed / 6 skipped**；
  真实导出数字未变（F620S 230 / F710S 34 / 平台池 58 / 合计 322）。
- **仍未做**：第 3 步 `platform_vehicle_map`（等平台→车型清单）；
  `summarize_instances`/`summarize_vehicles` 仍无生产调用点，仅测试与演示工作簿使用，
  文档已不再暗示实例级指标已交付。

## 2026-10-23 D5 归集代码/架构评审检查点（TASK-REVIEW-D5-REPORT-20261023，只记录不修复）

- **评审范围**：仅本地分支 `feat/d5-arch-part-attribution` 的 2 个提交
  （base `fe12ed6f` → HEAD `4f4dca3d`，9 文件 +1154/−10）。未 fetch，未审 `main..HEAD` 其余提交，
  未审工作区既有 dirty/未跟踪文件；未改生产/测试代码。报告：`docs/CODE_REVIEW_D5_20261023.md`。
- **4 项未修复发现**：
  - **R1 [P1] 新回归**：D5 图表复合 label（如 `F620S · 架构件`）被
    `form-analysis.js:218,570` 作为 `stage` 筛选值，`db_common.py:366-378` 按原 `stage_key`
    （`Ar-L`/`F620S`）过滤 ⇒ 点击 D5 柱条返回 0 行（项目件同样受影响）。
  - **R2 [P2]** 独立 `deliverable_forms` 页仍只展平旧 `DIMENSIONS`（`backend.py:36,60-61`）、
    `tdc_data_model.json` 仍 `groupBy=_stage`，F620S 与 Ar-L 继续分开；实施文档所称
    “现有图表直接呈现”不适用于该生产入口。
  - **R3 [P2]** 旧快照读取兜底只按 `stage` 推导（`data_model_attribution.py:176-177`），
    不读保留的 `values` 中 SOR/流水证据 ⇒ 同一行新写归 F620S、旧快照读永远平台池；
    `_metric_rows`/`view()` 不重算。
  - **R4 [P2]** 辅助 `summarize_instances` 分组键只有 `(vehicle, dataSource)`
    （`data_model_attribution.py:325-326`），无证据的 Ar-L/Ar-L+ 两个平台池实例合并为一组
    `待归属 Ar-L · 架构件 total=2`；生产逐行 `_data_model_group_status` 不受影响。
- **验证证据（本轮实跑）**：聚焦 pytest **105 passed / 0 failed / 0 skipped，0.95s，exit 0**
  （仅两个 D5 测试文件，非全量）；`git diff --check fe12ed6..4f4dca3` exit 0；
  `generate_project_map.py --check` verified exit 0；系统临时目录合成 D5 数据 + SQLite：
  复合 label 筛选 `total=0`、原 stage 各 `total=1`，`flatten_rows` 仅输出 `_stage=F620S/Ar-L`
  且无归集字段，旧快照读为平台池，`summarize_instances` 两平台实例合并 `total=2`。
  历史 3244 全绿是既有记录，**不是本轮执行结果**。
- **结论/下一动作**：建议**暂不合并**（R1 为本次新回归）；等待主控/用户安排修复
  （R1 优先，R2 修正交付范围或补页面，R3/R4 修复或明确口径限制）。本轮不修代码。

## 2026-10-22 D5 交付物项目件/架构件归集（已实施，分支 `feat/d5-arch-part-attribution`）

- **用户诉求**：统计数模设计审核流程（D5）数据发布状态时，把架构件（`项目/车型` 为 `Ar-XX` 平台代号）
  与项目件（`项目/车型` 为车型代号）合到同一个车型里体现。**范围明确限定 D5 一个交付物**，
  其他交付物（EWO/PAA/NCR/SOR/A面）不得改动。
- **两次 Codex 顾问**（task `DM-RELEASE-STATS-MERGE-20261022`）：`e634b47c…`（口径/归集模型，
  裁决 partial/adopted/adopted）、`1812448a…`（实施前架构评审，裁决 3 项全 adopted）。
- **实测数据事实**（两份真实导出，1037 行 / 322 实例）：零件号交集仅 3 个（不能作合并键）；
  实例号、流水单号交集均为 0（并集不会重复计数）；架构件 94 实例中 34 有车型证据
  （SOR 号 32 + 流水单号 2）、58 进平台池；报表车型 ≠ 数据真实服务车型（架构件报表里
  34 个实例 SOR 指向 F710S，只有 2 个指向 F620S）。
- **已落地**：新增 `services/data_model_attribution.py`（归集规则、实例级统一、汇总）；
  `_dimensions_from_tdc` 与 `_dimensions_from_mapping` 的 D5 分支追加
  `dataSource/vehicle/attribution/archPlatform`；`normalize_form_rows` 末尾对 D5 做实例级统一
  （证据优先、多数票、跨车型守卫）；`_stage_status_summary` 对 D5 走 `_data_model_group_status`；
  `tdc_data_model` FormSpec 登记三个维度标签（未放进全局默认值）。
- **验证**：`tests/test_data_model_attribution.py` 22 项 + 全量 `pytest` 3244 passed / 6 skipped；
  真实导出端到端：F620S 230 实例（项目件 228 + 架构件 2，完成率 47.57%）、F710S 34 架构实例、
  平台池 58，合计 322 实例，行级 1037 行无丢失。
- **关键发现（影响对外口径）**：归档连接器在写表单快照前用 `exclude_tdc_scope_rows` 剔除
  `已废弃`/`已撤回`，丢弃数走 `tdc_scope_exclusion` 诊断。因此 D5 交付物日常只有两态；
  归集模块仍按三态实现（直接导入整份导出时三态齐全）。
- **下一步**：①等「平台→车型适用清单」后建 `platform_vehicle_map` 做第 3 步；
  ②D5 顶部「数据来源」筛选下拉（`filterFields` 为硬编码，需为 D5 增项）；
  ③确认 D5 是否需要显示 `已废弃`（放开会影响所有 TDC 交付物，超出当前范围）。
- **文档**：`docs/DM_RELEASE_STATS_MERGE_PLAN_20261022.md`；演示工作簿
  `artifacts/车型发布状态统计_含架构件归集_20261022.xlsx`（由生产模块直接生成，口径与代码一致）。

## 2026-10-22 DSH 长会话派发/等待协议定案（顾问 run `8af70612`，裁决 adopted/partial/adopted）

- **触发**：用户指出会话 `session-12887aa2` 处理时间长，问顾问调用是否还有优化空间。
- **实测（已核实，非推断）**：墙钟 24,487s / 19 轮 / 458 次工具调用 / 422 次模型调用。
  **子代理串行关键路径 19,296s（79%，35 次派发，单次 259–1,423s）**；pwsh 固定 300s 轮询
  10,385s（48 次，27 次撞满上限）；用户等待 2,332s；全量 pytest 12 次（单次 345–379s）。
  **顾问仅 471s（1.9%）**，4 次 live 全部后台启动——顾问不是瓶颈。
- **两条被数据推翻的直觉**：① 上下文膨胀不是墙钟主因——按输入 token 分档，模型步时延中位
  `<50k` 9.5s（n=415）vs `>350k` 15.4s（n=5）；单步最大输入 520,716 token 只关乎成本
  （累计 3.15M 输入 token）与决策一致性。② 轮询时间≈子代理真实运行时间，不是额外浪费；
  真正的浪费是**串行**和**迭代期反复全量测试**。
- **落地物**：`docs/AGENT_DISPATCH_PROTOCOL_20261022.md`（规则）、
  `tools/agents/dispatch_wait_protocol.py`（标记文件 + 多路等待器 + 派发计划校验，
  14 项测试全绿）、`tests/test_dispatch_wait_protocol.py`。
- **定案**：① 等待层用标记文件 + 多路等待器（stall 600s / 硬上限 1800s / 任一终态即返回），
  禁用固定 300s shell 轮询；harness 原语方案冻结为"崩溃也写终态"最小面。
  ② 上下文降斜率 + 150k/180k 交接，交接包必须带决策账本与未关闭评审意见；**不合并**
  实现/评审回合。③ 并行分三阶段：先让只读评审与下一任务实现并行，再试点 2 个写通道，
  零返工才到 3；派发前用 `plan` 校验写入清单互斥与全仓副作用命令。
- **目标**：同类 10 任务批次 6.8h → ≤3h（并行 + 门禁分级 + 提问重叠）。
- **2026-10-22 追加（用户问"能否用起 DSH 智能体团队特性"）**：已实测并改判——多任务批次
  **默认走 Team**（`team_task_create` 建板 → `spawn_teammate(fresh)` → 有本地活不等待 →
  空闲时 `wait_agent` 单次 300–600s → 唤醒后 `list_agents`/`team_task_list` 对账），
  修复轮用 `send_message` 续跑原实现者，评审另开 fresh 成员。探针证据：两名成员同时 `running`
  且标记写入同一秒；`wait_agent` 返回 `{"timedOut":false}`（事件订阅非轮询）；普通 `subagent`
  结束消息自动推入主上下文；inactive 成员被唤醒后逐字复述上一轮内容。`write_scopes` 只给
  `writeScopeWarnings` 不阻断，路径级互斥仍须 `plan` 校验。标记文件等待器降级为兜底。
  详见 `docs/AGENT_DISPATCH_PROTOCOL_20261022.md` §6。
- **2026-10-22 端到端验收（用户要求"测试下是否更改可用"）**：3 单元真实批次跑通——
  `plan` 校验 exit 0（2 写通道 + 1 只读 + 0 违规命令）→ 2 个 fresh 成员并行实现（21s 双 done，
  各 3 测试）→ 兜底等待器后台 job 20.0s 返回 `action=return`（零 shell 轮询）→ `wait_agent`
  事件唤醒 → 新开只读评审成员（两模块 accept，另给 2 条覆盖率洞见）→ `send_message` 续跑
  原实现者做 2 个修复轮（4+4 通过，标记 `started_at` 保留首轮值证明是同一成员）。
  **批次墙钟约 105s**（19:20:30→19:22:15，含评审与两轮修复）；旧协议同形批次 ≥15 分钟。
  期间修掉 3 个真实缺陷：BOM 标记被静默跳过、空标记目录无限自旋、定向 pytest 被误判为全量门禁。
  协议测试 19 passed，flake8 0 告警。详见 `docs/AGENT_DISPATCH_PROTOCOL_20261022.md` §7。
- **仍未验证**：3 写通道、>10 分钟单元的 `stall`/`hard_limit` 真实触发、成员异常终止不写标记。
- **2026-10-22 补：顾问在执行层的落点**（用户问"顾问调用是在哪里体现"）。顾问属决策层，
  不在派发链路：批次里只在四处出现——写 `plan` 前（行 11 定案前方案）、评审返回后且修复路线≥2
  （行 7/8）、门禁/打包前复核（行 1/3/6）、高影响故障两轮矛盾（行 8）。成员实现中禁止咨询；
  live 一律后台 job 与成员运行重叠（本会话 3 笔：`0d3d36fd` 216s/$0.43 partial、
  `80614167` 47s adopted、`8af70612` 214s/$0.42 adopted-partial-adopted）。
  记录五件套：ledger launch/result/verdict 行、`runs/inputs/<run_id>.input.md`、
  `runs/<provider>-<ts>-<hash>.advice.md`、`reports/index.html`；**verdict 记账是强制项**。
  §7 端到端验收未覆盖"评审后触发咨询"的时序（该批次无决策点），待下一个有真实取舍的批次记录。
  详见 `docs/AGENT_DISPATCH_PROTOCOL_20261022.md` §8。
- **2026-10-22 20:30 收益估算复核（codex 顾问 run `fa92c6c2`，决定 1 = overturned）**：
  **原"6.8h → ≤3h"目标作废**。顾问判定我的 2.9h 合成式重复扣减重叠时间，给 4.0–5.6h
  （中点 4.6h，置信度低），主导变量是整体有效并行度 1.3–1.7。本地按派发时间线重算确认：
  旧批 27 次派发串行路径 12,883s，主代理调度间隙仅约 500s；完全独立假设下 2 通道可达 2.25×，
  但**真实依赖链 T1→T2+3→T4+5→T6+7→T8→T9 = 7,814s** 把加速比压到 **1.37×**
  （makespan 9,418s，该批 3.2–3.7h）。结论：加速比由依赖链决定，不由通道数决定。
  剩余空间按收益排序：① 重排/切分依赖链（占路径 61%）② 评审按风险缩放（评审 3,820s/10 次）
  ③ 减少 re-review 往返（4 次 1,176s）④ 门禁移到集成点 ⑤ 3 写通道（需 2 通道零返工）⑥ 修复轮续跑（未量化）。
  已撤回两条错误候选：主代理读 diff 代替独立评审、把顾问纳入门禁（会把后台时间变阻塞时间）。
  标定方案（adopted）：跑一个同形切片，若有效并行度 < 1.3 或外推 > 5.6h 即推翻区间。详见 §9。
- **下一步**：先跑同形切片标定并行度，再决定是否推进 3 写通道；批次按 Team 化协议执行并记录墙钟/返工。

## 2026-10-22 数模同步补齐官方 47 列并出包 20261022c（HEAD `70b7338`；**取代** 20261022b）

- **触发**：用户反馈「多单号可以同步，但内容不完整」——表单明细里 27 列显示 `-`。
- **根因（已核实）**：同步的表单快照来自列表接口行，只覆盖官方 47 列中的 **20 列**
  （`core/report_contracts.py:132` `_TDC_DATA_MODEL_SOURCE_FIELDS`；实测缺 27 列，含数量/重量/零件合计/
  对应IA号/各专业会签/造型专家审核/NVH/加签人员/应签·已签·未签/签署率/待审批人员）；
  官方工作簿**每次同步都已下载**（`project_status_connectors.py:373-392`）但只归档未解析。
- **方案**：`docs/PLAN_20261022_OFFICIAL_COLUMNS_SYNC.md`（v2）。经 **codex-readonly / gpt-6-astra / high**
  评审（run `80614167430b4bfdb27e243233a310dd`，裁决 1/2/3 = adopted）：只认非空
  `(流水单号, 零件号)` 复合键、两侧唯一、不做单号回退；逐行 `officialJoin` 状态；`contract_mismatch` 整批丢弃；
  取不到时逐行标注「本次未取得官方列」。
- **实现（7 提交 + 2 修复）**：`f2e8d9d` 官方导出解析 + 五类状态；`734332d` 复合键合并 + `officialColumns` schema +
  `/view` 透出；`c5a875b` DB 列 `official_join`（纯增量迁移）；`2413329` 前端逐行标注 + 顶部说明；
  `91d1274` 修复评审 C1/I1；其余为地图刷新。
- **评审发现并修复**：C1 `not_requested` 把每行标 `unavailable` → 归档快照的真实官方值被「未取得」遮蔽
  （修：`not_requested` 完全不合并、不写 schema 键，前端 `formOfficialMissingRow` 纵深防御）；
  I1 合并行官方值覆盖已映射 20 列（官方空白/Excel 序列号抹掉列表数据）→ 修：已映射列优先列表侧、
  列表为空才回退官方、未映射 27 列取官方。
- **门禁**：全量 `pytest tests` **3227 passed / 48 skipped / 0 failed**（`.runtime/pytest-full-20261022c-final.log`）；
  flake8 改动文件 0 告警；`node --check` 通过；地图 `--check` verified。
- **构建/冒烟**：`dist/hci-20261022c`，版本 `0.3.0-production-test-20261022c`，
  buildId `20261022c-70b7338-official-47-columns`；66/66 冒烟 PASS（`.runtime/smoke_exe_20261021b.ps1`），
  并核对包内含 `formOfficialColumns` / `FORM_OFFICIAL_MISSING_TEXT` / `form-row-official-note` / `form-cell-official-missing`。
- **交付物**：`VSE-WebUI.exe` 8,962,614 B（SHA-256 `1A9FDFEC…CC51C67`）、`VSE-WebUI.zip` 41,670,794 B
  （SHA-256 `66C932F6…B4B0A0A65`，1277 项 CRC 全通过）、README（含开关与回滚顺序）、`SHA256SUMS.txt`；
  三件套已复制到 `C:\Users\Lynch\Desktop\vse-toolbox-migration\`（`...-20261022c-...`）。
- **已知限制**：① 官方表超 5000 行 → 本次不补齐（页面说明）；② 复合键不唯一 → 不合并并标注；
  ③ 列表侧为空且官方给 Excel 日期序列号时该日期仍为空（未做序列号解析）；④ 归档 runner 未传官方行，
  该路径快照不补 27 列（不在本轮范围）。
- **未做**：微信投递（未要求）；真机 Excel COM 验收。

## 2026-10-22 顾问复核后硬化并重新出包：20261022b（HEAD `4346159`；已被 20261022c 取代）

- **触发**：用户要求「调用顾问做审查」。Claude `claude-opus-5-5` / xhigh / `--risk public-protocol`，
  run `0d3d36fd-292f-494c-abda-61e9365519d1`，包 `.runtime/consult-20261022-postimpl-review.md`（11,832 B，
  输入 8,450 / 输出 18,328 token），意见 `~/.dsh/expert-advisor/runs/claude-20261022-011945-cf34f934.advice.md`；
  裁决 1/2/3 = partial。
- **顾问结论**：功能代码无行为缺陷，但提出 3 项必须先取证的可疑入口（空集退化、零命中下游语义、回滚安全）与
  4 项 P1（回滚开关不可用、README 能力声明、previewSource 断言、二选一/三选一文案）。
- **本地取证（关键）**：
  1. `normalize_serial_set([]/''/None/[' ']/['A B']/[None])` 全部抛错；保存侧 `_normalize_multi_serial_rule`
     会先删空键 ⇒ 正常 API 存不进空集绑定；但**连接器 `if serials:` 用真值判断**，手工改库的
     `documentNos: []` 会跳过收窄、聚合全表 ⇒ 真入口，已修（改为「键存在即进入多号分支」）。
  2. 「全部未命中 → 0 行快照覆盖上次结果」**未能复现**：现有 runner 对空行结果走 `not_found/needs_attention`
     且不发布分析快照。真实缺陷是「未 fail-closed（软分类）」，仍按裁定改为与部分缺失同路径 raise
     （一致性 + 保留快照），端到端断言 run 失败、快照逐字不变、绑定仍 enabled。
  3. 回滚安全已由代码证实：旧包（`6c5b822`）`assert_sync_ready` 的 `set(match_rule) ⊆ contract["matchKeys"]`
     会拒 `documentNos` ⇒ 回滚后绑定停跑，不会算错；但旧包下这类绑定无法停用，故补「开关关闭时允许
     只置 enabled:false / 只改间隔的 PATCH」，并把回滚顺序写进 README。
- **修复波（6 提交，`e8172b2..4346159`）**：
  `386dd9d` 连接器按键存在进入多号分支（空集 raise）；`e3b3572` 全部未命中 fail-closed；
  `b21e7df` 开关关闭时允许停用/调间隔；`d3bdc48` 二选一/三选一文案统一；
  `8d85b98` deliverables previewSource 断言钉值；`4346159` 地图刷新。
- **门禁**：全量 `pytest tests` **3184 passed / 48 skipped / 0 failed**（`.runtime/advisor-fixwave/full-pytest.log`）；
  聚焦 293 passed；flake8 改动文件 0 告警；`node --check` 通过；地图 `--check` verified。
- **构建**：`dist/hci-20261022b`，版本 `0.3.0-production-test-20261022b`，buildId
  `20261022b-4346159-tdc-multi-serial-sync-hardened`；日志 `.runtime/build-webui-20261022b.log`。
- **出厂冒烟**：同一脚本（`.runtime/smoke_exe_20261021b.ps1 -Src dist\hci-20261022b\VSE-WebUI`）**66/66 PASS**。
- **交付物**：宿主 `VSE-WebUI.exe` 8,955,588 B（SHA-256 `99731AD3…F3819C77`）、
  `VSE-WebUI.zip` 41,661,754 B（SHA-256 `5EB6DB5E…ACC088EF`，1277 项 CRC 全通过）、README（含**回滚顺序**与
  已知限制）、`SHA256SUMS.txt`；三件套已复制到 `C:\Users\Lynch\Desktop\vse-toolbox-migration\`
  （`README-测试说明-20261022b.txt` / `SHA256SUMS-20261022b.txt` / `VSE-WebUI-0.3.0-production-test-20261022b-single-exe.zip`）。
- **作废**：同日 `dist/hci-20261022`（HEAD `dd011bd`，无本硬化）**已被本包取代**，不要投递；其桌面副本仍在
  `vse-toolbox-migration`，需按文件名区分（`...-20261022-...` vs `...-20261022b-...`）。
- **未做/待办**：① 未走微信 clawbot 投递（本轮未要求）；② 顾问建议的「行级守卫」（重复行身份 → needs_attention、
  未匹配行 NFKC 后能命中配置单号 → raise）与 `candidate_preview` 列表形支持仍待立项；
  ③ 真机 Excel COM 验收。

## 2026-10-22 生产测试包 20261022 出厂：查询模式止血 + 多单号合并统计同步（HEAD `dd011bd`，21 提交）

- **触发**：用户反馈 20261021 包上两问题（① 查询模式切官方预览后查询预览失败；② 数模审批同步不支持多单号），
  要求查原因并咨询顾问评估方案 → Claude（run `89d0f5f1`）与 codex-readonly/gpt-6-astra（run `66ddbb59`）两轮顾问，
  用户裁决 U1=合并统计、执行方式=subagent-driven，随后按 `docs/PLAN_20261021_TDC_QUERYMODE_MULTISERIAL.md` 执行 11 个 Task。
- **交付（代码）**：`6c5b822..dd011bd` 共 21 提交。
  - 第 1 批止血：`SerialRequiresListSource` 结构化错误码（400 不变）；两插件同源 `serialSourceConflict` 守卫
    （按钮 disabled + 主区域提示 + run() 短路）；多单号诚实文案并按 R17 拆分全角/多值两种诊断。
  - 第 2 批（D）：契约 `matchRule.documentNos`（与单值/实例号/关注清单三选一）；`normalize_serial_set`
    （逐项单值校验、去重排序、上限 500、非 str 元素拒绝）；签名规范化（存量 golden 逐字节不变）；
    保存/运行期校验（开关、12KB/4000 预算、聚合、无 externalKey）；发现路径（全命中才 matched、
    部分命中 `serial_set_partial`、成员身份证据指纹、stabilityCheck 成员基线）；运行期收窄
    （部分缺失 fail-closed、保留快照、自愈）；向导多值输入 + `multiSerialSyncEnabled` 可见性 + 契约 matchFields。
  - 开关 `VSE_TDC_MULTI_SERIAL_SYNC` 默认关闭，保存/发现/运行期/能力位五处 fail-closed。
- **关键 ruling（R1–R34，台账已随工作区删除，核心如下）**：
  - 不建 worktree（工作树有他人未提交 P1d 接线）；subagent 工具无 model 参数。
  - R3：契约 `matchFields` UI 条目推迟到最后一个 Task，避免中间态出现无后端支持的字段。
  - R4/R22：开关判定单一实现 `data_model_watchlist.multi_serial_enabled()`。
  - R17：全角与多值拆成两句文案；R18：字符串形上限统一 500（去重后计数），不再依赖 parse_terms 的 100 词上限。
  - R19：`documentNos` 空/None 省略键不落 null；R23：签名拒绝非字符串元素（禁止 str() 强转）。
  - R24/R26：契约键先于运行期接线打开白名单 → 用「开关默认关闭 + Task 8 起 fail-closed + 接线完成前不发版」兜底。
  - R28：多单号 stabilityCheck 必须用成员身份基线（原实现必然误报 key_changed）。
  - R30：部分缺失的 run 分类沿用既有 `failed`（不改 runner）；R31：诊断只用白名单键。
  - R33/R34：终审修复波 6 提交；残留 Minor（deliverables previewSource 断言只钉键不钉值、incident 占位文案仍写二选一）留待后续。
- **门禁**：全量 `pytest tests` **3175 passed / 48 skipped / 0 failed**（`.runtime/pytest-full-20261022.log`）；
  改动 .py flake8 exit 0；改动 .js `node --check` 通过；`generate_project_map.py --check` verified（已提交 dd011bd 内的地图刷新）。
- **构建**：`tools/build_excel_bundle.ps1 -OutputDir dist/hci-20261022 -PythonExecutable .runtime/pr3-review-venv/Scripts/python.exe -Clean`，
  env `VSE_TOOLBOX_VERSION=0.3.0-production-test-20261022` / `VSE_TOOLBOX_CHANNEL=production-test` /
  `VSE_TOOLBOX_BUILD_ID=20261022-dd011bd-tdc-multi-serial-sync`；日志 `.runtime/build-webui-20261022.log`。
  构建仍须用 `cmd /c "powershell -NoProfile -File tools\build_excel_bundle.ps1 ... > log 2>&1"`（PS 5.1 会把 PyInstaller 的
  stderr INFO 当 NativeCommandError 终止）。
- **出厂冒烟**：`.runtime/smoke_exe_20261021b.ps1 -Src dist\hci-20261022\VSE-WebUI -ExpectedVersion 0.3.0-production-test-20261022`
  （端口 5176、纯净目录），**66/66 PASS**。首轮 2 项 FAIL 均为**冒烟脚本自身缺陷**（buildId 日期写死 20261021；
  开关文案 marker 少一个「关」字 0x5173），修脚本后 66/66；产品侧无需改动。覆盖新增：
  多单号开关关闭时保存 422（fields.matchRule + 开关文案）、sourceInfo.multiSerialSyncEnabled 两态、
  开关开启后多单号草稿 200、摘要轮换、matchRule 保留规范化 documentNos 且仍为聚合无单值键。
- **交付物**：`dist/hci-20261022/` — 宿主 `VSE-WebUI.exe` 8,955,175 B
  （SHA-256 `A140E634961136399EA977FEA4BE0522914E79E2D1159824E1E75C2DE87A9639`）、
  `VSE-WebUI.zip` 41,659,486 B（SHA-256 `F35A411FAE63442242161362FA57FA112DA1ED39E3405B32C3625F6BD653BB48`，1277 项 CRC 全通过）、
  `README-测试说明.txt`、`SHA256SUMS.txt`。三件套已复制到 `C:\Users\Lynch\Desktop\vse-toolbox-migration\`
  （`README-测试说明-20261022.txt` / `SHA256SUMS-20261022.txt` / `VSE-WebUI-0.3.0-production-test-20261022-single-exe.zip`）。
- **未做/待办**：① 未走微信 clawbot 投递（本轮未要求）；② 多单号「预览就绪」信号 `candidate_preview` 对列表
  `documentNos` 仍判 invalid_configuration（单独立项，R29）；③ 开关关闭时已有多单号绑定只能整体替换 matchRule
  才能改（运维说明已写入 README）；④ 真机 Excel COM 验收仍待有 Excel 的机器；⑤ 终审残留 Minor 待清理。

