# DSH 后续 50 项独立任务交接（基线 b781066，2026-10-31 修订）

本目录只承载**后续执行计划**：一份中文交接说明（本文件）和一份可解析契约 `tasks.json`。
本轮是**证据驱动的文档修订**，不是重跑实现：只修改这两份文档，没有执行任何产品任务、没有运行契约中的产品测试、没有打包、没有安装、没有提交、没有 push。
原 workflow `wf-965d74ac-412d-43f4-9a37-eb1a698b8fca` 已 `passed`，不重开、不重跑；本轮只把恢复到的会话与构建失败证据写回计划。

- 盘点基线：`b781066d4f83dc38546a56049b4777c74e2bc9d7`（分支 `refactor/ux-v2`，tracked 工作区干净）
- 任务总数：50（ID `DSH-V2-00` … `DSH-V2-49`，唯一）
- 波次：W0 … W10（共 11 个波次；同波次 `owned_scope` 两两不相交）
- 执行模式：sync 9 项、async 40 项、human 1 项（`DSH-V2-37`）
- 风险分级：low 5 项、medium 26 项、high 19 项
- 预算上限：约 5 亿 token，按任务 `budget_pct` 分摊，合计 100%；按波次、按工作流两种归集视图也都是 100%（上限，不是强制消耗或承诺）

## 1. 证据来源与限制

| 证据 | 内容 | 限制 |
| --- | --- | --- |
| Git | HEAD = `b781066`，分支 `refactor/ux-v2`，tracked 无脏改动 | 只代表盘点时刻；依赖集成后 HEAD 会前进 |
| 会话检索 | 主控**只读**检索 `C:/Users/Lynch/.zcode/cli/db/db.sqlite`，定位到 `sess_098394c3-715d-4051-875c-6ff7f4a3775d`，标题「VSE Toolbox v2 ZCode 执行计划落实」，`last_outcome = error` | 本修订未读取原始会话全文或数据库文件；只使用主控脱敏后的序列证据 |
| 历史全量（seq 1696） | 工具输出 `3530 passed, 6 skipped, 13 warnings in 437.58s` | 这是 **W16-03 提交前**的历史全量，**不是本轮复跑**，不能当作当前 HEAD 结果 |
| 提交确认（seq 1712） | 确认提交 `b781066` | 只能记为「已提交待集成验收」，不能记为发布通过 |
| 构建失败（seq 1715/1717） | `python tools/build_v2_test_install.py > .runtime/w16_03_build.log`，exit 1 | 同会话 1716/1718 出现 `exceed quota limit`；额度失败不能解释构建失败 |
| 构建日志 | `tools/build_v2_test_install.py:126 old.unlink()` 抛 `PermissionError WinError 5`，目标 `dist/v2-test/updates/vse-app-2.3.10.vsepkg` | 根因**未定**：文件被占用或 ACL 拒绝均可能；未验证前不得断言单一根因 |
| 本轮只读验证 | `tests/test_local_security.py`、`tests/test_route_contract_snapshot.py`、`tests/test_time_rules.py`、`tests/test_time_display_frontend.py`，共 **44 passed in 7.71s**，头尾 HEAD 相同 | 只覆盖四个文件，不是当前 HEAD 全量回归 |
| 项目地图 | `python tools/generate_project_map.py --check` **退出 1：out of date** | 地图漂移未修；当前未索引 `vse_boot/`、`web/static/host/chrome/TaskCenter.js` 与 `plugins/project_overview/static/deliverable/simple*.js`，45/46/47 的 owned 以实际文件核实；导航以代码为准 |
| 历史记录 | `memory/CURRENT_STATE.md` 停在 Wave9，记录 3514 passed / 6 skipped；包 2.3.14 未真机安装 | 不能把 3514/6 或 3530/6 当作当前 HEAD 全量结果 |
| 历史 flake8 | 曾显示 `web/app.py` **F811 重复导入**；`echo FLAKE-OK` 不能当成功 | `DSH-V2-00` 必须先核实真实 flake8 退出码与输出，再记录 |
| 代码盘点 | 主控本轮已定位的缺口（见 `source_evidence.findings`） | 未做全仓库调用方扫描；**「范围内未查到」不代表全局不存在** |

结论口径：本轮 44 passed/7.71s 是**聚焦文件**通过；地图检查失败；历史 3530/6/13 只作 W16-03 提交前记录；全量回归、真机安装、真实内网验证均**未**进行；构建 WinError5 的根因**未定**。

## 2. 进度状态

**已提交（待集成验收）**
- W16-03 以提交 `b781066` 落在 HEAD；只能记为「已提交待集成验收」，不能记为发布通过。
- W15-01 已提交：CLI、旧交付物工作台、飞书 IMAP、计划任务安装器、废弃依赖已下线。**不重删** Probe 开发代码、TDC `feishukey`、workbench、`feishu_tasks`。
- Wave1–Wave9 的历史能力已在仓库中，但其测试数字属于历史记录，不是当前 HEAD 证据。

**部分实现 / 中间态**
- 启动票据链路存在，但票据进入 `?boot=` 查询串与 `instance.json` 的 `bootToken`；10 秒一次性票据与 `_show_existing` 复用旧 URL 的行为、12 小时会话过期后的重开路径均未验证（`web/security.py`、`vse_boot/supervisor.py:431-435`）。
- `web/security.py` 的 `install_local_security` 无条件安装自动补 Cookie/Origin 的测试客户端，通用测试会掩盖未认证访问。
- `tools/wave_gate.py`：`package_sign` 恒为 SKIP；`overall_passed` 只看无 FAIL；`--focus` 隐式 `skip_full`。PASS ≠ 发布通过。
- 路由契约快照只记录路径/方法/函数名与源码形状，不是响应行为测试，也不证明迁移后的代码真正被执行。
- W13 实际迁到 `web/*_boot.py`，属于**模块化中间态**；W14 两项仅为 `_impl.py` 兼容包壳，职责拆分未完成。
- 时间显示仅约束 `zh-CN`，未锁 `Asia/Shanghai`；`core/time_rules.py` 未在已查项目状态生产调用方消费。
- 向导：只阻断 422，其余创建错误被吞后进入下一步；选择交付物未在已查 auto-sync/enable-flow 中消费。
- Excel：`EnvCheckCard env=null`、backend 仅注册空插件、`excel_path_safety` 未在已查执行边界接线。
- 项目页：PATCH/归档接口已存在，前端仍主要是新建/切换；48 个车型配置未落地，需输入兜底。
- 调度：`services/project_status_scheduler.py` 仍按 `intervalSeconds` 循环，未在所查生产链找到 09:00/16:00 固定执行槽；`plugins/sign_daily/backend.py` 未见 08:30 作业注册。
- 任务中心：进度/取消/重试已有实现，产物 7 天清理有 `prune_old_artifacts` 与既有保护测试；真实链路仍需 45 核实，不能宣称已经完整。
- 启动器：三级回退、单实例锁、端口探测已有实现；pywebview 主线程兼容、降级顺序、重开与当前用户自启仍需 47 核实。

**未实现**
- 固定时刻执行槽（09:00/16:00）与工作日 08:30 日报作业、当天补跑策略。
- 企业会话统一续期协调器与清除代次（Aras/TDC/身份/同步 runner/host_boot 均未在已查范围发现统一实现）。
- 托盘三类事件通知接线；`TrayHandle.notify` 已有，缺的是同步失败/日报完成/更新发现的接线与去重。
- 报告中心原位一键生成、表单/导出单入口收敛、用户可见更新记录。
- release 严格门禁、整包一致性校验、真实 exe 端到端、可配置车型与科室回写。
- 真实浏览器关键路径夹具与北京时间统一格式函数。
- 多项目后台同步（48 仅设计，本阶段仍只当前项目运行）。
- L0 原生启动器替换（49 仅复用 Spike 报告，不实施替换）。

**外部待验（本计划不能自行判定通过）**
- 2.3.14 及后续包的真机安装、升级与回退。
- 真实内网 Aras/TDC 登录、续期与业务写操作。
- 真实浏览器下的 10 秒票据重放、12 小时会话过期、多 app 隔离。
- 三名首次使用者在真实办公电脑上的 10 分钟首份有效日报（`DSH-V2-37`，human 模式）。

## 3. 工作流 W0–W20 覆盖映射

下表把原执行计划的 21 个工作流映射到本次 50 项任务。状态只写已有证据能支持的程度；「部分」不等于完成。

| 工作流 | 目标 | 需求编号 | 风险 | lead/worker | 新任务 | 状态（截至本修订） |
| --- | --- | --- | --- | --- | --- | --- |
| W0 | 基线、契约与需求追踪冻结 | A9 / 全量 | low | lead | 00 | 已交付；00 重建当前基线 |
| W1 | 诊断白名单、自检、术语与 UI 门禁 | D11、J4、U4–U8 | medium | worker（lead 评审） | 06、31、40 | 部分：诊断/自检已交付；术语门禁在 40 |
| W2 | 账号会话、DPAPI、过期自动处理 | B3、B4、B5 | high | lead+worker | 14、15、16、17、05 | 部分：契约/实现待 14–17；测试替身在 05 |
| W3 | 会话状态合一、顶栏徽章、原位登录 | B2 | high | lead+worker | 17、32 | 部分：W3-01 已交付；17 统一退出与顶栏三档徽章、32 原位登录与旧页覆盖为验收点 |
| W4 | 首次使用向导 | U1 | medium | worker | 12、13 | 部分：W4-01 已交付；失败吞掉/首次同步 12–13 |
| W5 | 项目编辑、归档、主计划、车型科室 | C1、C3、D3 | medium | worker | 38、39、32 | 部分：W5-01/02 已交付；界面 38–39、兜底 39 |
| W6 | 调度 09:00/16:00、日报 08:30、原件留存 | D4、F3、G1、G2 | high | lead+worker | 18、19、20、21、23、30、48 | 部分：固定槽/日报/闭环待 18–30；48 仅设计多项目同步，当前仍只当前项目运行 |
| W7 | 报告中心、TIR、导出统一 | F1、F4–F7 | medium | worker（lead 评审） | 22、24、29 | 部分：原位生成 22、TIR 24、入口 29 |
| W8 | UI Kit、ErrorCard、FixIt、旧页覆盖 | D1、D7、D8、D10、D12、J1、U6–U8 | medium | worker | 31、32、40、43 | 部分：W8-01/02b 已交付；旧页 32/40/43 |
| W9 | 表单分析、表格交互 | E1、E2、E3 | medium | worker | 46、11、29 | 部分：E2 已有实现，46 核实修复；E1/E3 随 29/32 |
| W10 | 北京时间与逾期单一口径 | C5、F8 | medium | worker | 09、10、11、18 | 部分：W10-01/02 已交付；统一格式 09–11 |
| W11 | 任务中心、7 天清理、托盘通知 | I1、I2、U9 | high | worker+lead | 45、28 | 部分：W11-01 已交付；清理 45、通知 28 |
| W12 | Excel 工具页、Worker、路径安全、自检 | H1–H4 | high | lead+worker | 25、26、27 | 部分：W12-01/02 已交付；接线 25–27 |
| W13 | web 路由迁移与装配化 | 架构（无单一编号） | high | lead | 07、41 | 已交付到模块化中间态；41 只冻结后续边界 |
| W14 | 大服务渐进拆分 | 架构（无单一编号） | medium | lead | 41、42 | 部分：`_impl` 包壳；42 只出清单 |
| W15 | CLI/旧工作台/飞书/计划任务下线 | K1–K6 | low | lead | （无新增） | 已提交；不重删 Probe 开发代码/TDC feishukey/workbench/feishu_tasks |
| W16 | 启动器、单实例、端口、自启、启动安全 | A1–A4、A8 | high | lead+worker | 01、02、03、04、05、47、49 | 部分：W16-01/02/03 已提交；01/02 启动安全测试与契约、47 核实兼容、49 复用 Spike |
| W17 | 浏览器通道、发布门禁、真机端到端 | A6、D2、验收 | high | lead+worker | 08、34、35、44 | 部分：W17-01 已交付；44 构建输出收尾先行，W17-02/03 待真机与发布门禁 |
| W18 | 性能基线与复测 | 性能（无编号） | low | worker | 33 | 部分：W18-01 已交付；W18-03/33 待复测 |
| W19 | 手册、更新记录、发布说明 | A7 | low | worker | 36、43 | 部分：W19-01 已交付；W19-02/36/43 待更新记录与手册 |
| W20 | 三名新用户现场验收 | 验收（非编号） | high | lead+user | 37 | 未完成：待真实人员与办公电脑 |

## 4. 波次计划 Wave0–Wave10

波次按依赖与写冲突计算：**每项任务的 wave 严格大于其全部依赖的 wave**；同一 wave 内 `owned_scope` 两两不相交（大小写不敏感 + glob 前缀比较）。波次不是一次性派发清单，实际派发建议每批不超过 4 项。

| 波次 | 任务 | 数量 | 派发方式 | 门禁/备注 |
| --- | --- | --- | --- | --- |
| Wave0 | 00 | 1 | lead 串行 | 先重建基线；全量 pytest、地图生成/校验、flake8 都要真实退出码 |
| Wave1 | 44、01、45、46、47 | 5 | 00 完成后先 44，再 01/45/46 小批；47 先设计门 | 44 优先；47 是 high，需 lead 批准启动器契约 |
| Wave2 | 02、48、49、06、07、08、09、12、14、24、25、26、33、42 | 14 | 分 4 批，每批 ≤4 | 02/14 设计门；25 独占 `web/app.py`；48/49 只设计/报告 |
| Wave3 | 03、10、11、13、15、18、22、27、38、41 | 10 | 分 3 批 | 03/15/27 实现门；41 架构设计门 |
| Wave4 | 04、05、16、19、29、32、39 | 7 | 分 2 批 | 16 独占 `web/app.py`；19 存储契约门 |
| Wave5 | 17、20、34 | 3 | 小批 | 20 替换调度主路径；34 发布门禁 |
| Wave6 | 21、23、30、31 | 4 | 小批 | 23/30 契约门 |
| Wave7 | 28、40、43 | 3 | 小批 | 28 通知契约门 |
| Wave8 | 35 | 1 | 串行 | 需 34 门禁与已验收 RC |
| Wave9 | 36 | 1 | 串行 | 依赖 35 |
| Wave10 | 37 | 1 | human | 待真实人员与办公电脑 |

**关键路径**：`00 → 09 → 18 → 19 → 20 → 23 → 28 → 35 → 36 → 37`。
发布门禁分支：`00 → 01 → 02 → 03 → 04/05 → 34 → 35 → 36 → 37`（34 另依赖 44，44 在 Wave1 先行）。
两条路径在 35 汇合；35 之前必须完成 34 门禁与 45/46/47 验收。

## 5. 执行模型（同步/异步都不跳过评审）

- **修改任务一律走 `dsh_workflow_start`**，并保留独立评审。`sync` 表示启动后等终态；`async` 表示保存 `workflow_id` 后轮询。两者差别只是等待方式，**不是**“异步可以免评审”。
- `dsh_execute` **只**用于明确只读或单命令核验（读文件、跑单条已批准命令、看状态），不得用它实施修改。
- **同一工作区同一时间只允许一个写 workflow**。工作区指纹按工作区计算，即使两个任务改的是不同文件，第二个写 workflow 也会让第一个的指纹失效，因此不得在同目录并行写。
- **异步写任务必须使用隔离工作区**（独立 worktree/目录）。`tasks.json` 里的 `workspace` 只是源基线 `E:\project\vse-toolbox`，派发前必须替换成该任务的隔离目录。
- 状态 `passed` 之后，**主控仍须**阅读 `latestReview`、实际 diff 与测试输出再决定集成；不得只看状态字段。
- **设计门未批准不得派实现**。`risk_class=high` 或属于架构设计门（41、42）的任务，若 `dispatch_gate` 为 `lead_*` / `requires_approved_*`，必须先由 lead 冻结契约（02、14、19、23、26、27、28、30、34、41、42、47 等），再派发有界实现；不得改词降级或绕过。
- **41/42 是架构设计门**：只冻结 ADR/清单，不移动生产路由或大服务代码；其后每批最多 4 条路由或单一职责，由 lead 批准新增有界任务；不得宣称实际架构已完成。
- **已有 workflow 先恢复（resume）**，不新建并行写；失败或超时恢复**同一** workflow，不重复创建副作用；不因故障静默更换供应商或递归委派。
- 每个任务最多两轮针对性修复，之后交主控裁决。
- `DSH-V2-37` 是 `human` 模式，`dsh_tool=manual`：DSH 只准备材料与汇总，不假定拥有真实系统权限。

## 6. 工作区、输出范围与数据边界

- `read_only_scope` **不含**真实日志、会话全文或凭据；任务执行不需要传播原始日志。
- 凭据只用 DPAPI；不读现有 keys、真实数据库、原始 HAR/XML/XLSX、生产环境变量；测试用合成数据，秘密不得进入日志、契约或诊断。
- 任务 `DSH-V2-34`、`DSH-V2-35` 涉及打包/端到端，可能需要临时构建输出。**只允许主控在隔离目录显式授权**一个临时输出根，并在派发时书面调整 `scope.allowed`；执行者不得自行扩大范围，**不得读取现有 `dist/`、`build/` 或任何既有私钥**，测试信任链必须临时生成。
- `DSH-V2-44` 只在临时输出根复现/模拟 access-denied；**不改 ACL、不杀进程、不删除现有 `dist` 或 keys**；失败时保留旧包并明确报错。
- `DSH-V2-47` 不删除用户 HKCU 自启项（除非用户显式关闭）、不杀进程、不改 ACL；自启默认关闭。
- 所有任务统一禁止：`dist/**`、`build/**`、`error data/**`、`crawl source/**`、`爬虫源文件/**`、`.runtime/**`、`.agents/**`、`.zcode/**`。
- 不向 `web/app.py` 添加业务路由体，不向 `core/db_manager.py` 添加代码；插件只经 `host.context` 取共享服务。

## 7. 并行限制（owned_scope 交集，Windows 大小写保守判断）

- 50 项任务按 wave 分组后，**同 wave 内 owned_scope 两两无交集**（已机械核验）。workspace 仍须隔离，不能因为文件不同就共用目录。
- `web/app.py` 串行：`25`（W2）与 `16`（W4）都拥有它，必须先后执行；任何其他任务不得在同波次写 `web/app.py`。
- `webui.py` 串行：`03`（W3）与 `20`（W5）都拥有它，必须先后执行。
- `vse_boot/supervisor.py` 串行：`47`（W1）与 `03`（W3）都拥有它；47 只做降级/端口/自启，**重开窗口的 URL/票据传递归 02 契约与 03 实现**，47 不得固化 `instance.json` 票据或旧 URL 复用。
- 以上三组跨波次同文件写入已编码为依赖：`03 ← 47`、`20 ← 03`、`16 ← 25`（不只靠波次顺序，按依赖派发时同样生效）。
- `tests/test_route_contract_snapshot.py` 读写交叉：`07`（W2）写，`05`（W4）读；波次已强制串行。
- `PROJECT_MAP.md`：`00`（W0）写，其余任务只读；00 必须先单独跑完。
- `docs/refactor-v2/RELEASE_MATRIX.md`：`36`（W9）写，其余任务只读；36 应最后单跑，运行期间不得有读取方并行。
- `docs/manual/验收记录表.md`：只归 `37`（W10）；`36` 在 `docs/manual/` 下只写 `新用户验收脚本.md` 与 `真机核对清单.md`（另加 `docs/PRODUCTION_OPERATION_GUIDE.md`、`RELEASE_MATRIX.md`），不再整目录授权，二者无交集。
- 同一路径的自读自写仅两处，属预期：`00` 先读 `PROJECT_MAP.md` 再重新生成；`36` 先读 `RELEASE_MATRIX.md` 再更新。owned 优先于 read_only。

## 8. 50 项任务表

| ID | 目标 | 模式 | 依赖 | 风险 | 波次 | 预算 | 验收摘要 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DSH-V2-00 | 重建b781066的验收基线并纠正进度记录 | sync | — | low | W0 | 5% | 运行完整pytest并记录实际结果与skip原因，不修产品代码 |
| DSH-V2-01 | 补充未经自动认证测试客户端的本机安全集成测试 | sync | DSH-V2-00 | medium | W1 | 3% | 真实HTTP或原生客户端覆盖首次启动、10秒后重开、票据重放、会话过期、多app隔离 |
| DSH-V2-02 | 冻结启动票据传递和安全重开窗口的最小修复契约 | sync | DSH-V2-01 | high | W2 | 2% | 明确如何去掉URL查询串和instance.json明文票据 |
| DSH-V2-03 | 按已批准安全契约修复票据传递和受控重新打开 | async | DSH-V2-02、DSH-V2-47 | high | W3 | 3% | 票据不进入请求query、instance.json、常规日志或诊断 |
| DSH-V2-04 | 修复前端票据清理及失败反馈 | async | DSH-V2-03 | medium | W4 | 2% | 从约定传递位置取票据并在网络请求前清理地址栏 |
| DSH-V2-05 | 将自动认证测试客户端移出产品安全模块 | async | DSH-V2-03 | high | W4 | 3% | 生产模块不安装会掩盖未认证访问的test_client替身 |
| DSH-V2-06 | 为wave_gate增加严格release模式 | async | DSH-V2-00 | medium | W2 | 2% | dev与release状态明确区分 |
| DSH-V2-07 | 补充路由接线与实际响应契约测试 | async | DSH-V2-00 | medium | W2 | 2% | 验证handler所属模块和真正调用新register |
| DSH-V2-08 | 建立可离线运行的真实浏览器关键路径夹具 | async | DSH-V2-00 | medium | W2 | 2% | 使用固定离线依赖或现有浏览器，不进入生产依赖 |
| DSH-V2-09 | 提供北京时间统一前端格式函数和时区行为测试 | async | DSH-V2-00 | medium | W2 | 2% | 显示明确Asia/Shanghai，不仅zh-CN |
| DSH-V2-10 | 接入用户页面的北京时间格式并收紧时间门禁 | async | DSH-V2-09 | medium | W3 | 2% | 只修改已定位时间显示点，更多文件需lead先扩scope |
| DSH-V2-11 | 将单一逾期规则接入项目展示真实调用链 | async | DSH-V2-09 | medium | W3 | 2% | 同一输入列表和详情的逾期状态及天数一致 |
| DSH-V2-12 | 修复向导失败吞掉与跨重启项目恢复 | async | DSH-V2-00 | medium | W2 | 2% | 401/403/500和网络错误不得被当作项目创建成功 |
| DSH-V2-13 | 把向导选择真正传给首次启用同步 | async | DSH-V2-12 | medium | W3 | 2% | selectedDeliverables真正约束启用范围 |
| DSH-V2-14 | 冻结企业会话续期和统一清除契约 | sync | DSH-V2-00 | high | W2 | 2% | 区分401失效、403权限、网络和解析错误 |
| DSH-V2-15 | 实现企业会话续期协调器与清除代次 | async | DSH-V2-14 | high | W3 | 3% | 10个并发过期请求只续期一次 |
| DSH-V2-16 | 接入Aras会话恢复链 | async | DSH-V2-15、DSH-V2-25 | high | W4 | 2% | 真实业务调用使用协调器，不能仅新增未消费helper |
| DSH-V2-17 | 接入TDC恢复及统一退出清除 | async | DSH-V2-16 | high | W5 | 3% | TDC链实际消费统一恢复服务 |
| DSH-V2-18 | 实现固定时刻及当天补跑的纯计算模块 | async | DSH-V2-09 | medium | W3 | 2% | 北京时间09:00和16:00，日报周一至周五08:30 |
| DSH-V2-19 | 冻结并实现执行槽持久化与租约边界 | async | DSH-V2-18 | high | W4 | 3% | lead先冻结(projectId,jobId,date,time)唯一键及崩溃恢复规则 |
| DSH-V2-20 | 将固定时刻执行槽接入唯一后台调度器 | async | DSH-V2-19、DSH-V2-03 | high | W5 | 3% | 替换间隔派发主路径而非并存 |
| DSH-V2-21 | 提供调度时刻与暂停设置界面 | async | DSH-V2-20 | medium | W6 | 1% | 能增删时刻、暂停与恢复 |
| DSH-V2-22 | 实现报告中心原位一键生成 | async | DSH-V2-08 | medium | W3 | 2% | 报告页实际提交生成并展示进度、预览、复制或邮件草稿 |
| DSH-V2-23 | 接入日报工作日08:30生成与补生成 | async | DSH-V2-20 | high | W6 | 2% | 生成前保证数据新鲜，不等待09:00同步 |
| DSH-V2-24 | 审查并补强TIR同日复用条件 | async | DSH-V2-00 | medium | W2 | 1% | 先核实既有复用；无缺陷不重写 |
| DSH-V2-25 | 接通Excel环境自检API与页面 | async | DSH-V2-00 | medium | W2 | 2% | 页面获得真实后端自检结果而非静态占位 |
| DSH-V2-26 | 核实并接入Excel路径安全实际执行边界 | async | DSH-V2-00 | high | W2 | 1% | 先证明helper实际消费位置，禁止新增死代码 |
| DSH-V2-27 | 补齐Excel提交自动启动与空闲退出 | async | DSH-V2-26 | high | W3 | 2% | 隐藏按钮之外，提交确实启动唯一处理进程 |
| DSH-V2-28 | 接通同步失败、日报完成、更新发现的托盘通知 | async | DSH-V2-17、DSH-V2-23 | high | W7 | 2% | lead先冻结应用与托盘进程通信接口 |
| DSH-V2-29 | 补齐关注清单入口并收敛表单及导出入口 | async | DSH-V2-22 | medium | W4 | 1% | 报告中心关注入口与详情使用同一数据 |
| DSH-V2-30 | 核实同步与历史原件留存真正闭环 | async | DSH-V2-20 | high | W6 | 1% | 明确同步运行与原件的可追踪关联 |
| DSH-V2-31 | 补齐自检连接器和调度覆盖 | async | DSH-V2-17、DSH-V2-20、DSH-V2-25 | medium | W6 | 1% | 现有会话/Excel/更新/项目检查之外覆盖连接器和调度 |
| DSH-V2-32 | 补齐项目与设置旧页面的体验覆盖 | async | DSH-V2-08、DSH-V2-10 | medium | W4 | 2% | 开始前确认页面实际入口，若路径不同先修订契约不可扩写 |
| DSH-V2-33 | 按现有基准复测并确定是否需要索引优化 | sync | DSH-V2-00 | low | W2 | 1% | 先同机测create_app、首页和大表分页 |
| DSH-V2-34 | 补齐正式发布门禁的包验签与整包一致性 | async | DSH-V2-04、DSH-V2-05、DSH-V2-06、DSH-V2-07、DSH-V2-08、DSH-V2-44 | high | W5 | 2% | 启动器改动不能只发不包含vse_boot的app包 |
| DSH-V2-35 | 扩展真实exe端到端到首次日报和项目隔离 | async | DSH-V2-13、DSH-V2-17、DSH-V2-21、DSH-V2-22、DSH-V2-23、DSH-V2-25、DSH-V2-27、DSH-V2-28、DSH-V2-29、DSH-V2-30、DSH-V2-31、DSH-V2-32、DSH-V2-34、DSH-V2-39、DSH-V2-40、DSH-V2-43、DSH-V2-45、DSH-V2-46、DSH-V2-47 | high | W8 | 2% | 无系统Python依赖的安装启动 |
| DSH-V2-36 | 更新中文手册和发布操作说明 | async | DSH-V2-35 | low | W9 | 1% | 截图来自合成项目且无秘密 |
| DSH-V2-37 | 真实办公电脑和三名新用户验收 | human | DSH-V2-35、DSH-V2-36 | high | W10 | 1% | 用户提供真实环境与三名首次使用者 |
| DSH-V2-38 | 接通现有项目编辑和归档后端的用户界面 | async | DSH-V2-12 | medium | W3 | 2% | 复用已存在PATCH与archive接口，不另造注册表 |
| DSH-V2-39 | 补齐可配置车型列表和科室回写交互 | async | DSH-V2-13、DSH-V2-38 | medium | W4 | 2% | 车型列表配置可读写且不编造48个代码 |
| DSH-V2-40 | 收紧可见文案和剩余页面行为门禁 | async | DSH-V2-08、DSH-V2-29、DSH-V2-32 | medium | W7 | 1% | 检查真实可见文本和aria标签，不仅源码字符串 |
| DSH-V2-41 | 冻结web模块化到插件化的后续边界 | async | DSH-V2-07 | high | W3 | 2% | 明确web/*_boot.py是阶段性模块化，不宣称业务插件化完成 |
| DSH-V2-42 | 冻结大服务渐进拆分清单并验证现有黄金测试缺口 | async | DSH-V2-00 | medium | W2 | 1% | 区分_impl包壳与职责拆分 |
| DSH-V2-43 | 补齐用户可见更新记录 | async | DSH-V2-32 | medium | W7 | 1% | 显示版本、北京时间、面向用户说明和回退入口 |
| DSH-V2-44 | 收尾构建输出隔离：修复build_v2_test_install.py的WinError5失败路径并隔离测试输出 | sync | DSH-V2-00 | medium | W1 | 3% | 输出根可通过参数或环境变量配置，默认仍为dist/v2-test，测试只写临时目录 |
| DSH-V2-45 | 核实并修复任务中心进度与产物7天清理的真实链路 | async | DSH-V2-00 | medium | W1 | 3% | 先核实TaskCenter.js→/api/tasks→crawl_task_runner的真实链路，已有实现复用，只修缺口 |
| DSH-V2-46 | 核实并修复交付物详情表格排序、复制、列显隐与列key缺失回退 | async | DSH-V2-00 | medium | W1 | 3% | 复用已有排序/复制/列显隐实现，只修缺口，不重写 |
| DSH-V2-47 | 核实并修复启动器pywebview主线程兼容、降级顺序、单实例重开、端口冲突与当前用户自启 | sync | DSH-V2-00 | high | W1 | 3% | pywebview启动不阻塞supervise主循环；失败按pywebview→Edge app→默认浏览器降级 |
| DSH-V2-48 | 复核并冻结多项目后台同步设计（仅设计，不实现） | sync | DSH-V2-00 | low | W2 | 1% | 复用ADR-0001，明确当前仍只当前项目后台同步 |
| DSH-V2-49 | 复核L0原生启动器现状与选型Spike报告（已有则复用，不实施替换） | sync | DSH-V2-00 | low | W2 | 1% | 复用L0_SPIKE_20261031.md，核实三级回退/单实例/端口现状 |

（验收摘要为首条验收；完整验收、命令、scope、`workflow_refs`、`rollback_plan` 与约束见 `tasks.json`。）

## 9. 预算上限（约 5 亿 token，合计 100%）

这是**上限预算**，不是强制消耗，也不是交付承诺。每个任务的上限按 `budget_pct` 计；未用完的额度回到总池，不得把上限当 KPI 刷满。

| 波次 | 任务数 | 预算占比 | 折算上限（百万 token） |
| --- | ---: | ---: | ---: |
| W0 | 1 | 5% | 25 |
| W1 | 5 | 15% | 75 |
| W2 | 14 | 22% | 110 |
| W3 | 10 | 22% | 110 |
| W4 | 7 | 15% | 75 |
| W5 | 3 | 8% | 40 |
| W6 | 4 | 5% | 25 |
| W7 | 3 | 4% | 20 |
| W8 | 1 | 2% | 10 |
| W9 | 1 | 1% | 5 |
| W10 | 1 | 1% | 5 |
| **合计** | **50** | **100%** | **500** |

同一 100% 上限按**主责工作流**（W0–W20）归集如下。每项任务只在首个主责工作流计一次，跨工作流引用不重复计费；因此本表任务数合计 50、占比合计 100%。本表与上表是同一预算的两种视图，不是两笔预算，不能相加。

| 工作流 | 主责任务（只计一次） | 任务数 | 预算占比 | 折算上限（百万 token） |
| --- | --- | ---: | ---: | ---: |
| W0 | 00 | 1 | 5% | 25 |
| W1 | 06、31、40 | 3 | 4% | 20 |
| W2 | 14、15、16、17、05 | 5 | 13% | 65 |
| W3 | 32 | 1 | 2% | 10 |
| W4 | 12、13 | 2 | 4% | 20 |
| W5 | 38、39 | 2 | 4% | 20 |
| W6 | 18、19、20、21、23、30、48 | 7 | 13% | 65 |
| W7 | 22、24、29 | 3 | 4% | 20 |
| W8 | 43 | 1 | 1% | 5 |
| W9 | 46、11 | 2 | 5% | 25 |
| W10 | 09、10 | 2 | 4% | 20 |
| W11 | 45、28 | 2 | 5% | 25 |
| W12 | 25、26、27 | 3 | 5% | 25 |
| W13 | 07、41 | 2 | 4% | 20 |
| W14 | 42 | 1 | 1% | 5 |
| W15 | —（已提交，无新增任务） | 0 | 0% | 0 |
| W16 | 01、02、03、04、47、49 | 6 | 14% | 70 |
| W17 | 08、34、35、44 | 4 | 9% | 45 |
| W18 | 33 | 1 | 1% | 5 |
| W19 | 36 | 1 | 1% | 5 |
| W20 | 37 | 1 | 1% | 5 |
| **合计** | — | **50** | **100%** | **500** |

说明：17 计 W2、32 计 W3；05 计 W2；11 计 W9、18 计 W6、29 计 W7，均不重复计。W15 已在 `b781066` 之前提交，不占新增预算。该表只是预算归集视图，不改变第 8 节逐任务 `budget_pct`。

单任务上限见第 8 节「预算」列；`budget_pct` 在 `tasks.json` 中逐任务保存，合计 100。超出单任务上限需 lead 书面批准并说明原因，不能静默挪用其他任务额度。

## 10. Lead 契约草案（字段、状态机、错误）

### 10.1 任务字段（21 个）

`task_id`、`objective`、`owned_scope`、`read_only_scope`、`depends_on`、`verification_commands`、`acceptance_criteria`、`risk_class`、`execution_mode`、`dispatch_gate`、`size`、`wave`、`workflow_refs`、`budget_pct`、`rollback_plan`、`baseline_commit`、`workspace`、`dsh_tool`、`max_review_cycles`、`scope`、`constraints`。

- `wave`：调度波次；必须严格大于全部依赖的 wave。
- `workflow_refs`：本任务承接的历史工作流/任务锚点（如 `W16-03`），不是可执行 workflow id。
- `rollback_plan`：逐任务回退动作；high 任务必须具体到文件/提交/数据保留。
- `budget_pct`：token 上限占比；50 项合计 100。
- `constraints`：**必须包含全部 15 条 `common_constraints`**，可追加任务专属合同；不要求与 common 恰等。
- `scope.allowed` 等于 `owned_scope`；`scope.forbidden` 为统一 8 条默认禁止路径。

### 10.2 状态机

```text
planned
  → dependency_ready        （全部 depends_on 已集成且 HEAD 已更新）
  → gate_pending            （high/设计门待 lead 批准）
  → dispatched              （workflow_id 已保存，工作区已隔离）
  → running
  → passed | failed | blocked
  → review_pending          （工作流终态后必须独立评审）
  → integrated | rolled_back
```

- `dependency_ready` 之前不得派发；`gate_pending` 未批准不得进入 `dispatched`。
- `failed`/超时恢复**同一** workflow，不重复创建副作用；同因最多两轮修复。
- `passed` 不等于集成；主控读 `latestReview`、diff、测试输出后才可 `integrated`。
- `blocked` 必须写明具体阻塞条件、已检查路径与下一步，不能只写“环境问题”。
- `rolled_back` 必须执行 `rollback_plan` 并记录保留的数据/产物。

### 10.3 错误分类

| 错误 | 处理 |
| --- | --- |
| `dependency_not_ready` | 停止；先集成依赖并更新 HEAD，不派发 |
| `scope_conflict` | 停止；同波次 owned 交集或工作区非隔离，改波次/隔离目录 |
| `gate_not_approved` / `design_not_frozen` | 停止；交 lead 冻结契约，不派实现 |
| `verification_failed` | 保留输出；同因最多两轮修复，再交主控 |
| `review_rejected` | 不集成；按评审意见修复或回退 |
| `timeout` | 恢复同一 workflow；不重复创建副作用 |
| `quota_exhausted` | 停该路线；不静默换供应商/账号/模型 |
| `workspace_fingerprint_lost` | 停止该工作区写任务；重建隔离工作区后再派 |
| `provider_unavailable` | 停该路线并报告；不递归委派其他 agent |
| `human_required` | 转 `DSH-V2-37` human 流程；不伪造结果 |

## 11. 高风险任务逐项回滚

共 19 项 high。每项都必须先过 lead 门，再按下列动作回退；回退不得删除用户数据、既有 `dist`/keys 或历史原件。

| 任务 | 波次 | 门禁 | 具体回滚 |
| --- | --- | --- | --- |
| DSH-V2-02 | W2 | lead_design_and_approval | 删除或回退docs/refactor-v2/DSH_LOCAL_SECURITY_CONTRACT.md到上一提交，并取消03派发；不触碰现有安全实现。 |
| DSH-V2-03 | W3 | requires_approved_02 | 对实现提交执行git revert；恢复vse_boot/supervisor.py、webui.py、web/security.py与两份测试；若已生成app包，回退到上一已验收版本，不迁移用户数据。 |
| DSH-V2-05 | W4 | lead_review_security_boundary | 对web/security.py、tests/security_client_fixture.py、tests/conftest.py、tests/test_local_security.py执行git revert；恢复自动测试客户端与原有负向覆盖；不删除生产安全配置。 |
| DSH-V2-14 | W2 | lead_design_and_approval | 删除或回退docs/refactor-v2/DSH_IDENTITY_CONTRACT.md并取消15派发；保留现有会话实现与凭据。 |
| DSH-V2-15 | W3 | requires_approved_14 | 对services/session_recovery.py、core/domain_identity.py与测试执行git revert；清除代次相关迁移只增不删，回退代码后保留表但停用；不删除用户凭据。 |
| DSH-V2-16 | W4 | requires_approved_14 | 对services/aras_auth.py、services/project_status_connectors.py、web/host_boot.py、web/app.py的接线提交执行git revert（web/app.py必须整提交回退，不手工剪裁）；恢复旧Aras会话路径。 |
| DSH-V2-17 | W5 | requires_approved_14 | 对services/tdc_auth.py、project_status_connectors.py、web/host_boot.py与测试执行git revert；恢复TDC旧路径与旧退出清除；不删统一退出所需配置。 |
| DSH-V2-19 | W4 | lead_approves_storage_contract | 对plugins/sync_control的plugin.json/backend.py/store.py与测试执行git revert；槽表迁移只增不删，回退后保留表但停用；已产生的槽记录先导出备份再停用。 |
| DSH-V2-20 | W5 | requires_approved_19 | 对services/project_status_scheduler.py、webui.py与调度测试执行git revert；恢复intervalSeconds旧循环；停用固定槽，保留槽数据。 |
| DSH-V2-23 | W6 | lead_approves_report_job_contract | 对plugins/sign_daily/scheduled.py、backend.py与测试执行git revert；停用08:30作业；已生成日报文件保留不删。 |
| DSH-V2-26 | W2 | lead_approves_path_contract | 对core/excel_tasks.py、core/excel_worker.py、services/excel_path_safety.py的接线与测试执行git revert；恢复旧路径校验；不删白名单设置与用户文件。 |
| DSH-V2-27 | W3 | lead_approves_process_contract | 对services/excel_worker_process_controller.py、web/excel_boot.py与测试执行git revert；停止自动启动，保留手动启动；不结束用户Excel。 |
| DSH-V2-28 | W7 | lead_approves_notification_contract | 对services/user_notifications.py、vse_boot/tray.py、vse_boot/api.py与测试执行git revert；关闭新增通知；保留已有TrayHandle.notify行为。 |
| DSH-V2-30 | W6 | lead_approves_originals_contract | 对services/project_status_sync_runner.py、services/scheduled_archive_runner.py、archive-deliverable.js与测试执行git revert；已归档原件保留不删，不迁移旧数据。 |
| DSH-V2-34 | W5 | lead_approves_release_matrix | 对tools/wave_gate.py与tests/test_release_package_gate.py执行git revert；不发布；已生成包保留但标记未验收；不删除dist或既有私钥。 |
| DSH-V2-35 | W8 | lead_approves_release_candidate | 对tools/e2e_v2_test_install.py、tests/browser/test_release_journey.py执行git revert；不发布；安装目录回退到上一已验收包；保留用户数据。 |
| DSH-V2-37 | W10 | lead_approves_field_acceptance | 作废本次验收记录并恢复docs/manual/验收记录表.md上一版本；不修改产品；真实环境数据按用户要求保留或删除。 |
| DSH-V2-41 | W3 | lead_design_and_approval | 删除或回退DSH_PLUGINIZATION_ADR.md；不移动任何生产路由；取消由该ADR派生的后续任务；web/app.py保持不变。 |
| DSH-V2-47 | W1 | lead_approves_launcher_contract | 对vse_boot/supervisor.py、__main__.py、autostart.py与窗口测试执行git revert；启动器回到上一提交；不删除用户HKCU自启项（除非用户显式关闭）、不杀进程、不改ACL。 |

42 不是 high，不在上表；它是架构设计门（`lead_design_and_approval`），回退为恢复或删除 `docs/refactor-v2/DSH_SERVICE_SPLIT_INVENTORY.md` 到上一提交，并取消由该清单派生的后续任务，不移动生产代码。

## 12. 未来待决问题（最多 8 个，当前不必询问）

| # | 问题 | 推荐选项 | 备选/触发条件 |
| --- | --- | --- | --- |
| 1 | 是否做多项目后台同步？ | 本阶段**仅设计**，继续「仅当前项目 + 当天补跑」 | 用户明确要求离开期间保持同步、或日报扩展到非当前项目、或补跑等待 >30s 时重评 |
| 2 | 是否采购代码签名证书？ | **暂缓**；证书不能代替 `.vsepkg` 签名，发布仍走 vsepkg 信任链 | 需要对外分发或企业策略强制 Authenticode 时再评估 |
| 3 | 开机自启默认与入口？ | **默认关闭**，当前用户 HKCU，向导/设置由用户选择 | 用户要求默认开启时再改，但不得要求管理员 |
| 4 | 发布节奏？ | **小批验收通过后发版**，不按单任务发版 | 紧急修复可单独走 hotfix，但仍需 34 门禁 |
| 5 | 48 个车型配置如何输入？ | **文本输入/可配置列表兜底**，不编造 48 个代码 | 拿到官方车型清单后再导入并补校验 |
| 6 | 是否替换 L0 原生启动器？ | **不替换**，保留 Spike，继续 pywebview→Edge→浏览器 | 目标机三级回退全部不可用，或 pywebview 被策略拦截且 Edge 体验投诉集中 |
| 7 | 7 天清理是否覆盖历史原件？ | **不覆盖**；只清过期任务产物，历史原件单独保留 | 存储告警且用户书面同意后才评估归档保留期 |
| 8 | 旧页面是否继续插件化？ | **41/42 设计门后每批 ≤4 路由/单一职责**，由 lead 批准 | 出现跨模块公共契约变更时先停，重新冻结 |

## 13. 可直接粘贴的 DSH 交互 lead 总控提示词

```text
你是 DSH 交互主控 lead。仓库 E:\project\vse-toolbox，基线 b781066（派发前更新为依赖集成后的 HEAD）。
只执行 docs/dsh-next-20261031/tasks.json 中的有界任务；先读 README 与 tasks.json，不读原始会话日志/数据库/keys/dist。

启动顺序（前 3 步串行；45/46/47 可在 00 后小批并行）：
1) DSH-V2-00（基线）完成并验收；
2) DSH-V2-44（构建输出收尾）完成并验收；
3) DSH-V2-01 → DSH-V2-02（01 完成后才派 02）；
4) 45/46/47 在 00 完成后按小批并行；47 先设计门。

派发规则：
- 依赖未集成、设计门未批准、scope 有交集、工作区非隔离 → 不派。
- 同波次 owned_scope 无交集才可并行；每批最多 4 个任务；web/app.py 与 webui.py 同一时间只允许一个写任务。
- 修改任务一律 dsh_workflow_start；sync 等终态，async 保存 workflow_id 轮询；两者都保留独立评审。
- dsh_execute 只用于只读或单命令核验，不用于实施。
- 已有 workflow 先恢复（resume），不新建并行写；失败/超时恢复同一 workflow，不重复创建副作用；同因最多两轮修复，再交主控裁决；不静默换供应商。
- 不调用其他 agent/Codex/AGY/ZCode 递归委派。

主控参数（JSON 不是 MCP 原生参数）：
- 不要直接传整个 task 对象。
- 把 task 的 objective 编入 goal；把 depends_on/verification_commands/acceptance_criteria 编入 plan 与 acceptance_criteria；把 owned_scope/read_only_scope 编入 scope；把 wave/workflow_refs/rollback_plan/constraints 编入约束与回滚说明。
- 派发前把 workspace 替换成该任务的隔离目录，把 baseline_commit 更新为依赖集成后的 HEAD。
- 高风险任务先把 lead 冻结的契约写入约束；未批准不派实现。
- 48 只做多项目后台同步设计，49 只复核 L0 Spike，不实施替换；34 只读构建脚本，构建输出收尾归 44。

验收：
- passed 后主控必须读 latestReview、实际 diff、测试输出；不只看状态字段。
- 强制独立评审；主控 diff 验收；不自动 merge/push。
- 每个任务回报字段：task_id / commit / files / tests / review / risks / next。
- 保留无关改动与未跟踪文件；不 git add -A。
- 待决问题按第 12 节推荐选项处理，当前不必逐项询问；触发条件出现再升级。

现在从 DSH-V2-00 开始；完成 00 后立即做 44；再做 01→02；45/46/47 按小批并行（47 先设计门）。不要一次派 50 条。
```

## 14. `tasks.json` 契约

顶层字段：`schema_version`、`baseline_commit`、`source_evidence`、`common_constraints`、`tasks`。

- `schema_version = 1`；`baseline_commit = b781066…`（**盘点基线**，不是执行锁）。
- `source_evidence` 记录主控脱敏后的会话、构建失败、本轮验证、历史与 18 条 findings；不包含原始日志/凭据。
- `common_constraints` 共 15 条。**每个 task 的 `constraints` 必须包含全部 15 条**，可追加任务专属合同；不要求恰等。
- 每个 task 字段：`task_id`、`objective`、`owned_scope`、`read_only_scope`、`depends_on`、`verification_commands`（数组的数组）、`acceptance_criteria`、`risk_class`、`execution_mode`、`dispatch_gate`、`size`、`wave`、`workflow_refs`、`budget_pct`、`rollback_plan`、`baseline_commit`、`workspace`、`dsh_tool`、`max_review_cycles`（固定 2）、`scope`、`constraints`。
- `scope.allowed` 等于该任务的 `owned_scope`；`scope.forbidden` 为统一的 8 条默认禁止路径。
- **派发时不要锁死 `b781066`**：应取依赖集成后的新 HEAD，并把 `baseline_commit` 与 `workspace` 更新为实际值。
- **JSON 不是 MCP 原生参数**：主控把任务字段编入 `goal`/`plan`/`acceptance_criteria`/`scope`，禁止直接把整个 task 当作参数传递。

## 15. 机械校验（只做文档校验，未执行任务命令）

本轮在内存中解析与检查，未落辅助文件，未执行 `tasks.json` 里的任何 `verification_commands`：

- `json.loads` 解析通过；顶层键恰为 5 个；`schema_version=1`。
- 任务数 50，ID 唯一且为 `DSH-V2-00`…`DSH-V2-49`；每个任务 21 个字段齐全。
- 依赖全部存在、无自依赖，拓扑排序得到 50 项（无环）。
- 每任务 `wave` 严格大于全部依赖的 `wave`；波次分布 W0:1、W1:5、W2:14、W3:10、W4:7、W5:3、W6:4、W7:3、W8:1、W9:1、W10:1；风险分布 low 5、medium 26、high 19；执行模式 sync 9、async 40、human 1。
- 同波次 `owned_scope` 两两无交集（大小写不敏感 + glob 前缀）；`web/app.py`（25/16）、`webui.py`（03/20）与 `vse_boot/supervisor.py`（47/03）跨波次串行，并已写入 `depends_on`；任意两项共写同一文件时必有依赖路径。
- 每任务 `owned_scope`、`acceptance_criteria`、`verification_commands` 非空；命令均为非空字符串数组。
- 每任务 `constraints` 包含全部 15 条 `common_constraints`；`scope.allowed` 与 `owned_scope` 一致；`scope.forbidden` 为规定 8 条。
- 19 项 high 均有具体 `rollback_plan` 与 `lead_*`/`requires_approved_*` 门禁；42 作为架构设计门也有 `lead_design_and_approval` 门禁。
- `budget_pct` 合计 100；按波次与按主责工作流两种归集均合计 100%（500M 上限）；W0–W20 覆盖表 21 行且 50 项任务均至少出现一次；第 8 节任务表 50 行与 JSON 逐行一致。
- 未发现 owned_scope 落入默认禁止路径；36 已从 `docs/manual/**` 收窄为 `新用户验收脚本.md`、`真机核对清单.md` 两个具体手册文件，37 独占 `docs/manual/验收记录表.md`，二者无交集。

**声明**：以上只是文档一致性核验；`tasks.json` 中的 pytest、地图、打包、端到端命令都是**未来命令**，本轮没有执行，也没有把执行结果写进本文件。

## 16. 不做及理由

- **不重开已 passed 的 `wf-965d74ac-412d-43f4-9a37-eb1a698b8fca`**：本轮是新证据驱动的文档修订，不是重跑实现。
- **不实施产品代码、不跑产品测试、不打包、不安装、不 commit/push**：本轮只有文档写权限；产品验证留给后续有界任务。
- **不读原始会话日志/数据库/keys/dist**：只使用主控脱敏证据；避免把秘密或原始日志带入计划。
- **不把 3530/6 或 3514/6 当作当前全量**：它们是历史记录；本轮只有 44 passed/7.71s，且地图 `--check` 失败。
- **不宣称 WinError5 根因**：占用与 ACL 均可能，未验证前只记录现象与待验证假设。
- **不删除现有 `dist`/keys/构建产物**：44 只在临时目录复现/模拟；失败保留旧包并明确报错。
- **不实施多项目后台同步**：48 仅设计；本阶段仍只当前项目运行。
- **不替换 L0 原生启动器**：49 复用既有 Spike 报告；47 只核实 pywebview/Edge/浏览器三级回退。
- **不重删 W15 已下线对象**：Probe 开发代码、TDC feishukey、workbench、feishu_tasks 保留。
- **不宣称架构拆分完成**：41/42 是设计门；其后每批 ≤4 路由/单一职责，由 lead 批准新增有界任务。
- **不一次派 50 条**：按波次与小批派发，每批 ≤4；先 00、44，再 01→02。
- **不自动 merge/push**：passed 后仍要独立评审与主控 diff 验收。
- **不把整个 task 当 MCP 参数**：JSON 不是 MCP 原生参数，主控需拆编字段。
- **不在本修订询问待决问题**：第 12 节只记录推荐选项，等触发条件出现再问。

## 17. Git 审计与本文件没有做的事

- 只修改 `docs/dsh-next-20261031/README.md` 与 `docs/dsh-next-20261031/tasks.json`；仓库内无其他写入。
- 没有运行任何产品任务、没有运行契约中的 pytest/打包/安装命令、没有修改源码或既有测试。
- 没有提交、没有 push、没有合并、没有集成；独立评审保留，本轮不自动 merge/push。
- 没有修改 `memory/`、`PROJECT_MAP.md`、源码或既有测试；目录外无写入。
- 没有读取真实日志、会话全文、凭据、`dist/`、`build/` 或原始 HAR/XML/XLSX。
- 本轮把 36 的 `docs/manual/**` 收窄为 `新用户验收脚本.md`、`真机核对清单.md` 两个具体手册文件，并给 42 增加 `lead_design_and_approval` 设计门；这是文档契约修订，不改变任务目标或实施范围。
- 主控复审修订（2026-10-31，Codex 额度中断后由 Claude 接手复核）：修正 47 验收与 02/03 票据契约的冲突；补 `03←47`、`20←03`、`16←25` 三条依赖；其余内容经机械核验保持不变。
- 没有派发任何 workflow（派发是下一阶段主控的动作，且应逐个或小批，而不是一次性同时派发 50 条）。
