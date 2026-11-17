# 顾问裁决补记记录（DSH lead，2026-09-29）

- 日期：2026-09-29（写入时间 `2026-09-29T01:10:16+08:00`）
- 执行人：DeepSeek Harness（DSH）交互主代理，`--caller dsh`
- 性质：**只补记账本裁决**。未发起任何 dry-run / live 咨询，未改产品代码、测试、方案文档正文，未改 `advisor_core.py` / `advisor_broker.py` / `advisor_policy.json` / HOLD / broker，未重写任何历史账本行。
- 结论：`tokens.cmd --calls 30` 的「待补裁决」列表中属于本代理的 2 条（`--caller dsh`）已补记完毕；同一列表中另 6 条 `--caller zcode` 由 ZCode 交互主代理补记，见 `docs/ADVISOR_VERDICT_BACKFILL_20260929.md`（zcode 侧），本代理未代记。

---

## 1. 条目识别

首次 `tokens.cmd --calls 30` 的「待补裁决」共 8 条，其中 caller 为 `dsh` 的 2 条：

| run_id | task_id | provider / 档位 | 调用时间 | 意见归档 |
| --- | --- | --- | --- | --- |
| `7218728949904c7ca93f1fc4335bcaa7` | `vse-aras-formed-20260925` | codex-readonly / sol-xhigh（13.7k in / 1898 out） | 09-25 16:59 | `~/.dsh/expert-advisor/runs/codex-readonly-20260925-170043-39e4d887.advice.md` |
| `f59b9cfb298c44b7a79ee0fef6e54174` | `TASK-20260925-NCR-LABEL-COLLISION` | codex-readonly / sol-high（12.8k in / 792 out） | 09-25 22:26 | `~/.dsh/expert-advisor/runs/codex-readonly-20260925-222735-196acf1a.advice.md` |

判定依据：`~/.dsh/expert-advisor/state/ledger-2026-09-25.jsonl` 的 launch 行 `caller=dsh`，且该 run_id 无 verdict 行。

## 2. 证据来源与包身份核验

| 证据 | 用途 | 位置 |
| --- | --- | --- |
| 顾问意见归档 | 顾问对每个待决决定的意见 | 见 §1 表 |
| 当时提交的咨询包 | **决定编号**（「待决问题」1..N）与我的原始方案 | `.runtime/consult-20260925-ar-formed.md`、`.runtime/consult-20260925-ncr-label-collision.md` |
| 当时的过程记录 | 实际处理（改了什么、哪一项被推翻） | `docs/PLAN_20260925_BOARD_TRIM_AND_ARAS_UNIFY.md`、`memory/CURRENT_STATE.md`、`memory/DECISIONS.md` |
| 账本 launch 行 | run_id、任务、档位、包 SHA-256 | `~/.dsh/expert-advisor/state/ledger-2026-09-25.jsonl` |

**包身份核验（不靠文件名推断）**：2026-09-25 的两条 codex-readonly 运行没有 `runs/inputs/` 输入归档（脱敏输入归档自 Claude broker 协议 v11 起才有），因此用账本 launch 行的 `package_sha256` 反查仓库中的咨询包。直接对文件字节取 SHA-256 与账本不符，原因是本机 broker 以文本模式把包写入临时文件，Windows 下 `\n` 被写为 `\r\n`；把包内容按 `\r\n` 归一后重算，两个哈希分别精确命中：

- `.runtime/consult-20260925-ar-formed.md` → `762d7180c62354604266eed9109889d37e3f062db9291787a234d5a1c93e23ae`
- `.runtime/consult-20260925-ncr-label-collision.md` → `72ba30eff5f57e5e8a75813a2bce1932a4c7297851ff5926a97ea273cea61c43`

即这两份文件就是当时实际送审的包，决定编号可直接采用包内「待决问题」的编号（分别为 5 项、4 项）。

## 3. 执行的命令与账本结果

```
python -B C:\Users\Lynch\.dsh\skills\expert-advisor\expert_advisor.py --verdict 7218728949904c7ca93f1fc4335bcaa7 --caller dsh --decision 1=overturned --decision 2=adopted --decision 3=overturned
python -B C:\Users\Lynch\.dsh\skills\expert-advisor\expert_advisor.py --verdict f59b9cfb298c44b7a79ee0fef6e54174 --caller dsh --decision 1=no_change --decision 2=partial --decision 3=adopted
```

两条均返回 `ok: true`，写入的 verdict 行：

| run_id | task_id | provider | decisions |
| --- | --- | --- | --- |
| `7218728949904c7ca93f1fc4335bcaa7` | vse-aras-formed-20260925 | codex-readonly | `1=overturned 2=adopted 3=overturned` |
| `f59b9cfb298c44b7a79ee0fef6e54174` | TASK-20260925-NCR-LABEL-COLLISION | codex-readonly | `1=no_change 2=partial 3=adopted` |

取值语义（`advisor_core.py` `VERDICTS`）：`adopted` 采纳 / `partial` 部分采纳 / `overturned` 顾问意见推翻了我原来的方案 / `no_change` 顾问确认原方案、未改变任何动作 / `rejected` 否决 / `deferred` 暂缓（记不清时用，不猜）。本次未使用 `rejected` 与 `deferred`——两个任务的每条决定都能从归档、咨询包与当时的方案/记忆记录中定位到事实。

## 4. 逐条依据

### 4.1 `vse-aras-formed-20260925`（包内 5 个待决问题）

| 决定（包内编号） | 取值 | 事实依据 |
| --- | --- | --- |
| 1 分期：P1（行为等价重构）与 P2（NCR 行契约）能否分两次上线 | **overturned** | 我的原方案 A 写的是「元数据驱动的统一链路，**分期落地**」（P0 与重构解耦、P1/P2/P3 分列）并问能否分两次上线；顾问判「P1、P2 和 EWO 语义隔离应同次上线，P0 可独立实施」。实际按顾问合并 P1+P2+P3 为一次改动——方案文档「实施状态」段写明「P1/P2/P3 合并为一次改动，符合顾问『不得留下中间态』的裁决」，§4 又以「为什么 P1+P2+P3 必须同次上线（**采纳顾问意见**）」解释。顾问推翻了我原来的分期方案 |
| 2 NCR 完备性取 (a)/(b)/(c) 哪一种 | **adopted** | 顾问选 (a)：表头契约 + 逐行校验 + `读取 = 解析 + 空行 + 拒绝` 等式，不明丢行 fail-closed，历史行数只做诊断；可信汇总值出现后才演进到 (b)；(c) 不足以证明行完整。实际裁决取 (a)（方案 §4.5「顾问三选一，我的裁决」），落地 `WorkbookBookkeeping` / `decide_workbook_outcome()` / `require_complete_workbook()`，并如实声明「complete 只表示满足准入策略，不表示证明源端零丢失」 |
| 3 D1/D4 看板隐藏做成「注册表元数据 + 后端过滤」还是「仅前端过滤」 | **overturned** | 我的原方案 A 写的是「D1/D4 走注册表元数据 + **后端 payload 过滤**」，并问是否必须后端过滤以消除看板与 `/api/project-status` 摘要/分母的口径不一致；顾问判「既有 HTTP 语义不得改变，隐藏 D1/D4 应新增**服务端看板投影**，不能过滤原接口字段」。实际改为新增 `boardVisible` 投影且**不改动** `deliverables` 全量字段（方案 §2.2 标题即「采纳顾问意见：服务端看板投影，不改原接口语义」；P0-a/P0-b）。我原来的机制被推翻 |

超出账本 3 slot 上限、未能入账的其余决定见 §5。

### 4.2 `TASK-20260925-NCR-LABEL-COLLISION`（包内 4 个待决问题）

| 决定（包内编号） | 取值 | 事实依据 |
| --- | --- | --- |
| 1 方案 A（命名行携带权威位置数组）与方案 B（按父表头消歧标签键）选哪个 | **no_change** | 顾问同意我推荐的 A，只加前置条件「先确认命名行约定允许增量键」。实现即按 A：`NcrWorkbookRow.named_row()` 额外携带契约顺序的位置视图 `values`，标签字典继续保留给按标签取值的消费者。原方案未因顾问而改变动作 |
| 2 历史「只有标签键」的快照（11 列已失真且不可逆）如何处理 | **partial** | 顾问取 (b)：读取时发一次性**有界诊断**（计数 + 歧义标签集合、不含业务值）提示重投影，并「对历史行**保留原读取结果**、不得将其标为已修复」。有界诊断（`forms.ambiguous_header_labels`）与「不回填、不标已修复」落地；但后续对抗式复核把标签还原分支对同名列的处理改为一律留空（宁可「未判定」也不给出错误日期，见方案文档「对抗式复核」Minor 项与 `memory/CURRENT_STATE.md` ③）——与顾问「保留原读取结果」有出入，故记部分采纳 |
| 3 「契约里存在重复标签」是否做成守护测试 | **adopted** | 顾问要求做成契约守护测试，并把重复标签集合与父表头分组纳入断言。实际在契约层（11 组同名标签索引 + 父表头语义）、解析层（位置视图权威）、读取层（含两组真实列值的夹具锁定 11 个日期还原与历史行降级行为）三层落地，并删除了原先空过的等价性夹具（方案文档「修复」表 + 「守护测试」行） |

超出账本 3 slot 上限、未能入账的其余决定见 §5。

## 5. 超出 3 slot 上限的遗留决定与实测限制

`--verdict` 的入库格式硬上限是 **3 项决定**：`advisor_core.MAX_DECISIONS = 3`，且键只允许 `1` / `2` / `3`，`record_verdict()` 在追加账本行**之前**校验。这两个包分别有 5 项和 4 项待决问题，超出上限。

实测（不产生任何写入，校验先于追加）：

```
4 keys (1-4)          -> Fault 4 裁决格式应为 1=adopted 2=rejected …（取值 adopted/partial/rejected/deferred/overturned/no_change）
3 keys + 不存在的 run  -> Fault 4 只能对账本中一次成功的咨询记录裁决
MAX_DECISIONS = 3
```

因此按包内编号只能入账前 3 项。以下 3 项按事实补记于本文档，但**不在账本统计内**：

| run_id | 决定（包内编号） | 取值 | 事实依据 |
| --- | --- | --- | --- |
| `7218728949…caa7` | 4 `formSnapshotDriven` 显示分叉是否保留、如何避免与 `syncCapable` 向导再次分叉 | **no_change** | 顾问答「`formSnapshotDriven` 只管展示，同步入口统一按 `syncCapable` 判定，记录集合仅对已支持项启用」。我的原方案 P3-b 已含「删除不可达的第二套快照同步卡、同步入口只按 `syncCapable` 判定」，实现与原方案一致、未改动作 |
| `7218728949…caa7` | 5 是否还有会导致静默丢数 / 重复计数 / 快照形状回退的边界 | **adopted** | 顾问指出「归档与同步竞争写入仍可能覆盖较新快照，须规定版本或时间戳及幂等规则」。已「采纳并具体化」为方案 §4.6 三条措施（两条写入路径产出同一行形状为首要；快照记录行契约版本、读取侧对旧契约显式告警/降级；归档与绑定两条入口语义显式声明，键集差异需要收窄到同一口径） |
| `f59b9cfb…4174` | 4 行身份（去重键）是否统一到「优先取 NCR 编号标签、否则拼接」、是否要求跨版本稳定 | **adopted** | 顾问答「身份计算保持修复前『NCR编号标签优先』语义，位置数组只改变字段归一化；缺号时沿用既有回退规则」。实际统一为 `_ncr_row_identity()`（优先 `NCR编号` 标签、否则前 10 列拼接），带不带位置视图同一行 `rowKey` 不变；后续对抗式复核另行确认身份语义无变化（方案文档 Nit 行） |

**与 zcode 侧口径的对照**：zcode 侧同一轮补记对「待决问题 4–7 项的旧包」采用的规则是**按决策轴合并成 ≤3 个 slot**（`docs/ADVISOR_VERDICT_BACKFILL_20260929.md` §4）。本次 DSH 侧采用**包内编号 1:1 映射**（slot N = 包内第 N 问），未做轴合并，因此本侧每个 slot 的含义无歧义，代价是上述 3 项只能记在本文档而不进账本统计。若要与 zcode 侧口径统一，需要重发一次 verdict（账本追加、报表取每 run 最新一行；token 统计按 run 合并键），合并方案由用户决定后执行，本代理未擅自改写已写入的裁决。

## 6. 验证

补记后再次运行 `C:\Users\Lynch\.dsh\skills\expert-advisor\scripts\tokens.cmd --calls 30`：

- 「待补裁决」列表中 `--caller dsh` 的两条**已消失**，剩余条目全部为 `--caller zcode`。
- 「最近 30 次顾问调用」中两条已带裁决：
  - `09-25 16:59 vse-aras-formed-20260925` → `1=overturned 2=adopted 3=overturned`
  - `09-25 22:26 TASK-20260925-NCR-LABEL-COLLISION` → `1=no_change 2=partial 3=adopted`
- 「顾问裁决」汇总口径由补记前的「有裁决的调用 5 次、决定 15 个（采纳 10、部分采纳 5）」推进；本侧 2 次 / 6 项决定已计入。

## 7. 边界与遗留

- 未修改任何产品代码、测试、`docs/PLAN_*` 正文或 `memory/`；本文档为新增文件。
- 未修改 `advisor_core.py`、`advisor_broker.py`、`advisor_policy.json`、HOLD、broker 协议或历史账本行；写入仅为两条新的 `verdict` 事件。
- 未调用模型：`--verdict` 路径不产生任何模型请求（无 dry-run、无 live）。
- 未代记 `--caller zcode` 的 6 条：它们属于 ZCode 交互主代理，已由该代理在 `docs/ADVISOR_VERDICT_BACKFILL_20260929.md` 记明。
- 遗留待用户决定：① 是否把 §5 的 3 项按 zcode 侧口径合并入账（需重发 verdict）；② `docs/ADVISOR_SCENARIO_EVALUATION_20260928.md` §2.1/§6 关于「只有 5 次调用回写裁决」的表述已过时，是否同步更新。
