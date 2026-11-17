# ADR-0001：多项目后台同步（本阶段只设计，不实现）

- 状态：**设计冻结**（W0-02）｜ 实施波次：无（本阶段不实现）
- 实现现状：**未实现**——运行时只有当前项目在后台同步；离开项目期间不同步（2026-11-01 复核，证据见文末）
- 决策人：lead；用户拍板点见文末
- 关联：CONTRACTS.md C4（调度）、REQUIREMENTS.md C1（多项目与切换）
- 复核：2026-11-01 复核（DSH-V2-48）——结论不变（仍选 A、仍不实现），更正 4 处与代码不符的表述，
  补充 A/B/C 现状权衡、可观测升级判据与新增拍板点

## 背景

v2 采用「一个项目一个数据目录」：启动器按当前项目决定数据根，主项目 = 安装根（兼容旧数据）。
当前**只有当前项目在后台同步**；切换项目 = 保存选择 + 重启（约 10 秒）。本阶段调度器（C4）只调度当前项目。

> **更正（2026-11-01 复核（DSH-V2-48））**：`vse_boot/projects.py` 只提供 id→目录映射
> （`data_root()` / `active_data_root()`，`vse_boot/projects.py:166-170`、`:282-283`）；把
> `VSE_DATA_ROOT` 真正写进服务子进程环境的是启动器 `spawn_app`（`vse_boot/supervisor.py:82-85`），
> 服务进程侧由 `core/runtime_paths.py:22-24` 读取。原文「projects.py 按当前项目设 VSE_DATA_ROOT」
> 容易读成运行时切换，实际是**进程启动前一次性决定，进程内不变**。

## 问题

切换走的项目在后台没有同步覆盖。用户回来切回该项目时，数据可能落后数天。
是否需要多项目同时后台同步？

## 备选方案

| 方案 | 说明 | 取舍 |
|---|---|---|
| A. 仅当前项目（现状+补跑） | 切入项目当天错过的槽开机补跑；离开的项目不同步 | 零新增复杂度；离开期间数据停滞 |
| B. 单调度器轮转 | 一个调度器按顺序逐项目补齐各自槽 | 单进程内实现，但长任务会拖慢其他项目的到点槽；与「一项目一进程数据根」的隔离模型冲突（同进程内切数据根） |
| C. 每项目独立轻进程 | 每个启用项目一个同步进程，各自数据根 | 隔离最好；内存 × N，办公电脑负担；进程生命周期/崩溃恢复复杂度高 |

## 决策

**本阶段采用 A**（仅当前项目 + 当天补跑），理由：

1. 用户当前实际工作模式是「一段时间集中在一个项目」；停滞窗口可接受且有感知（切换时显示各项目最后同步时间）。
2. C4 执行槽唯一键已含 `projectId`，槽记录表天然支持多项目；将来升级到 B/C **不需要迁移槽表**。
3. B 方案与数据根隔离模型冲突，C 方案资源开销在无管理员办公电脑上不可控。

**为将来留的接口约束（本期就要满足）**：

- 槽记录表不设「全局单例」约束，一切以 projectId 为键的一部分（C4 已定）。
- 调度器服务接口以「当前项目」为入参而不是闭包全局；多项目化时改为遍历启用项目。
- 切换项目时的补跑只补当天（C4），不做跨天追赶——多项目化后此语义不变。

> **更正（2026-11-01 复核（DSH-V2-48））**：决策理由 2 的前提需要精确化。C4 的「执行槽唯一键含
> `projectId`」目前是**设计契约**（`docs/refactor-v2/CONTRACTS.md:89`），槽表**尚未落库**：
> `core/`、`services/` 中不存在 `businessDate` / `scheduledTime` / 槽表定义，`tests/test_scheduler_slots.py`
> 也不存在。因此「将来升级不需要迁移槽表」应读作**前置约束**——将来落槽表时必须把 `projectId`
> 放进唯一键，否则届时才会需要迁移；今天不存在可迁移的槽数据。

> **更正（2026-11-01 复核（DSH-V2-48））**：决策理由 1 的缓解假设「切换时显示各项目最后同步时间」
> **尚未实现**。项目列表只返回 id / 名称 / 车型 / 科室 / active / status / revision
> （`plugins/workbench/backend.py:48-62`），切换页 `plugins/workbench/static/projects.js` 不含同步时间；
> `lastSuccessAt` 只出现在**当前项目**的交付物/策略视图（`plugins/project_overview/backend.py:138`）。
> 所以「停滞有感知」当前不成立，降级为待办与拍板点 P2。

> **更正（2026-11-01 复核（DSH-V2-48））**：现行实现不是「按天补槽」，而是**间隔型新鲜度门控**：
> 每个 tick 用 `list_eligible_sync_bindings(None)` 读当前库的启用绑定，`last_success_at` 距今不足
> interval（默认 900 秒，可用 `VSE_PROJECT_STATUS_SYNC_INTERVAL` 覆盖）的零网络跳过，其余立即补同步
> （`services/project_status_scheduler.py:34`、`:292-346`）。进程启动后首个 tick 就执行
> （`webui.py:176-179` → `run_forever()` 先 `tick()`），故「切回该项目即刻补」已实现、跨天不追赶；
> 「当天槽补跑」要等 C4 槽表落地后才成立。另：`webui.py:62-66` 的 `--no-sync-scheduler` 可整体关闭
> 后台同步，属于运维开关而非多项目能力。

## 升级触发条件（满足其一才重新评估）

1. 用户明确要求离开期间项目保持同步（业务决定）；
2. 日报定时生成扩展到非当前项目（F3 跨项目）；
3. 单项目补跑在切换高峰期实测造成等待 > 30 秒。

## 用户拍板点

- 是否接受「离开的项目在后台不同步」作为本阶段明确行为？（推荐：接受，切换页显示各项目最后同步时间）
- 若将来启用 B/C，是否接受办公电脑内存占用上升？（推荐：届时再评估）

## 复核记录（2026-11-01 · DSH-V2-48）

### 复核结论

- 维持 **A**，设计继续冻结；本轮**只改本文件**：不新增进程、不新增调度代码、不做数据迁移、不动代码与测试。
- **多项目后台同步未实现**。运行时行为仍是「只有当前项目在后台同步，离开项目期间不同步」。
- 更正 4 处旧表述（见上文四个「更正」块）：数据根注入点、槽表是否存在、切换页感知能力、补跑语义。
- 旧关联项 `CURRENT_STATE 2026-10-28` 已失效：`memory/CURRENT_STATE.md:7` 的当前前沿为 2026-11-01，
  文件内无 2026-10-28 条目；关联改为 `REQUIREMENTS.md:174`（C1 已记录该限制）与 `CONTRACTS.md:96`。

### 现状证据（本次只读核对，均为代码位置）

| 事实 | 证据 |
|---|---|
| 数据根在进程启动前按当前项目一次性决定 | `vse_boot/supervisor.py:82-85`（`env["VSE_DATA_ROOT"] = projects.active_data_root(layout)`）、`vse_boot/projects.py:166-170`、`:282-283` |
| 服务进程只认 `VSE_DATA_ROOT`，进程内无项目切换 | `core/runtime_paths.py:22-24` |
| 全局只有一个调度器，且绑定当前库 | `webui.py:70-98`（`db = DatabaseManager()` → 一个 runner → 一个 daemon 线程）、`webui.py:176-179` |
| 调度循环不接受项目参数，只读「本进程的库」 | `services/project_status_scheduler.py:292-335`（`list_eligible_sync_bindings(None)`，`None` 是 deliverable_id 过滤位） |
| 绑定查询没有 projectId 维度 | `core/repos/sync_runs.py:940-989`（仅按 `deliverable_id` 过滤；表 `project_status_update_bindings` 无 `project_id` 列） |
| 同步运行器无项目概念 | `services/project_status_sync_runner.py`（全文无 projectId / 数据根入参；项目隔离完全由数据目录承担） |
| 切换 = 保存选择 + 请求重启 | `plugins/workbench/backend.py:114-123` → `registry.switch()` → `vse_boot/api.py:74-77` 写 `state/restart.request` |
| 启动器见到重启请求先停子进程，再重新拉起 | `vse_boot/supervisor.py:629-632`、`:638-646`（terminate，10 秒后 kill）、`:527-529`（回到 `_boot` 重新 `spawn_app`） |
| 在途同步被中断不会永久卡死 | `core/repos/sync_runs.py:189-214`（仅当无租约或租约已过期才可原子重取）、`core/db_common.py:61-63`（默认租约 900 秒） |
| 切换页没有跨项目同步时间 | `plugins/workbench/backend.py:48-62`（`view()` 无 lastSyncAt）、`plugins/workbench/static/projects.js` |
| C4 契约本身只要求当前项目 | `docs/refactor-v2/CONTRACTS.md:96`（「单一调度权威……本阶段只调度当前项目」） |
| 需求侧已记录该限制 | `docs/refactor-v2/REQUIREMENTS.md:174`（「限制：只有当前项目在后台自动同步，切换进来时补跑」） |

### 切换项目时到底发生什么（时序）

1. 页面 `POST api/p/workbench/projects/<id>/switch` → `registry.switch(id)` 把 `active` 写入
   `state/projects.json`（`vse_boot/projects.py:275-279`），随后 `request_restart` 写
   `state/restart.request`（`vse_boot/api.py:74-77`）。
2. 启动器 `_serve` 轮询到该文件 → `_stop(child)`：先 terminate，10 秒不退出再 kill
   （`vse_boot/supervisor.py:629-632`、`:638-646`）。**旧进程的调度线程随之结束，不执行优雅 stop**
   （`stop_event` 不会被置位）。
3. 回到 `_loop` → `_boot` → `spawn_app` 用新 `active` 重新计算 `VSE_DATA_ROOT` 并起新进程
   （`vse_boot/supervisor.py:527-529`、`:82-85`）。
4. 新进程 `DatabaseManager()` 打开新项目库，调度器线程随之重建；首个 `tick()` 立即执行，把该库中
   陈旧的启用绑定补同步一次（新鲜度门控，见上文更正）。
5. 结果：**离开的项目在离开期间零同步**；切回时只补「当前一次」落后，跨天不追赶、不补历史槽。
6. 若切换正好打断在途同步：该绑定留下租约，最长 900 秒（`core/db_common.py:63`）后可由下次运行
   原子重取（`core/repos/sync_runs.py:189-214`）；期间该绑定是 `running` 态，不产生重复抓取。

### A/B/C 复核（2026-11-01 补充现状权衡）

| 方案 | 复核后代价 | 主要失败模式 | 与现有代码的冲突点 |
|---|---|---|---|
| **A. 仅当前项目（选定）** | 0 新进程、0 新调度代码；沿用现调度器 | 离开期间数据停更；切换打断在途同步（靠租约自愈）；「有感知」缺实现 | 无（即现状） |
| B. 单调度器轮转 | 一个进程内需多套 DB 句柄/多数据根 | 长任务阻塞其他项目的到点同步；同进程数据根切换污染缓存与连接 | `DatabaseManager()` 无参、根来自 `VSE_DATA_ROOT`（`core/runtime_paths.py:22-24`），需改根注入方式 |
| C. 每项目独立轻进程 | 内存 × N；进程生命周期/崩溃恢复/退出清理 | 孤儿进程；与启动器 Job Object 的收尾语义叠加（`vse_boot/supervisor.py:115-121` 目前只覆盖 app 子进程及其 Excel worker） | 需扩展启动器托管范围，改动面在 `vse_boot` 而非调度器 |

补充说明：若只想解决「离开瞬间太突然」，存在 **A 的补强变体 A′**（非新方案、本轮不实现）——
切换/退出前对当前项目触发一次同步再重启。代价是切换等待变长且仍可能被 terminate 打断，
收益仅在「刚同步过」这一窗口，需用户拍板（P3）。

### 与 C4 槽表 `projectId` 键的兼容性（不要求迁移）

- `projectId` 语义 = **数据根项目 id**（`main` / `p2` 形态，见 `vse_boot/projects.py:35` 的 `_ID_PATTERN`），
  是字符串。槽表唯一键沿用 `projectId / jobId / businessDate / scheduledTime`（`CONTRACTS.md:89`）即可，
  本 ADR 不需要改契约。
- 注意与库内 legacy `projects` 表区分：后者是 `id INTEGER`、兜底 `1='未归类'`
  （`core/db_common.py:516-528`、`core/db_manager.py:162-166`），被 `deliverables.project_id` 外键引用。
  槽表的 `projectId` **不要**写成该整数 FK，二者不是同一概念。
- **当前不需要迁移**：槽表尚未落库；`project_status_update_bindings` 也没有 `project_id` 列——项目隔离
  完全由「一项目一数据目录」承担。所以本 ADR 与 C4 键的兼容性是「落表时的前置约束」，不是待执行的迁移。
- 落表时还需拍板（P4）：槽表放在**每个项目库内**（projectId 冗余但天然隔离）还是**单一中央库**
  （需任一进程可跨项目读写）。此选择影响 B/C 的可行性，但不影响今天的 A。

### 升级触发条件（复核版）

原 1–3 条保留，追加两条可观测判据：

1. 用户明确要求离开期间项目保持同步（业务决定）；
2. 日报定时生成扩展到非当前项目（F3 跨项目）；
3. 单项目补跑在切换高峰期实测造成等待 > 30 秒；
4. 项目数 ≥ 3 且平均单项目离开时长 > 7 天（「集中在一个项目」的工作模式假设不再成立）；
5. 用户累计 ≥ 2 次报告「切回来发现数据落后」——说明缺少感知本身就是问题，优先做感知而非同步。

### 用户拍板点（复核版）

- **P1**：是否接受「离开的项目在后台不同步」作为本阶段明确行为？（推荐：接受）
- **P2**：是否先把「各项目最后同步时间」做进切换页？（推荐：做。需要只读打开
  `projects/<id>/data/vse_toolbox.db` 取 `max(last_success_at)`；不涉及迁移，但属于新代码，不在本任务范围）
- **P3**：是否要 A′（切换/退出前补跑一次）？（推荐：暂不做，先看 P2 是否足够）
- **P4**：将来落 C4 槽表时，槽表放每项目库还是中央库？（推荐：届时与 B/C 取舍一起定）
- **P5**：若将来启用 B/C，是否接受办公电脑内存占用上升？（推荐：届时再评估）

### 本轮明确不做（防越界）

- 不实现多项目后台同步，不新增进程、调度代码、配置项或数据迁移；
- 不改 `services/project_status_scheduler.py`、`services/project_status_sync_runner.py`、
  `vse_boot/projects.py`、`vse_boot/supervisor.py` 及任何测试；
- 不改 C4 契约文本；`projectId` 键的落表实现留给 C4 实施波次。
