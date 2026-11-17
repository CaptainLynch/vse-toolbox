# 顾问裁决补记记录（zcode lead，2026-09-29）

- 日期：2026-09-29　分支：`feature/scheduled-deliverables-overview-excel`
- 性质：**只补记账本裁决，未发起任何 live 咨询、未改产品代码、未改任何归档意见**。
- 执行人：ZCode 交互主代理（`--caller zcode`）。
- 结论：`tokens.cmd --calls 30` 的"待补裁决"列表在补记后为空，账本"成功但未记录裁决 0 次"。

---

## 1. 背景

`docs/ADVISOR_SCENARIO_EVALUATION_20260928.md` §2.1/§6 记录：账本 32 次启动里真实决策调用约 13 次，
但只有 5 次调用（15 项决定）回写了裁决，"采纳率"统计基础不完整，并列为待办"补齐未回写的 8 次调用"。
本次把其中属于本代理（`--caller zcode`）的 6 次补记完毕；另 2 次 `--caller dsh` 由 dsh lead 于
`2026-09-29T01:10:16+08:00` 自行补记（见 §5）。

裁决入口：`expert_advisor.py --verdict <run_id> --caller zcode --decision N=<取值>`。
取值语义（`advisor_core.py` `VERDICTS`）：`adopted` 采纳 / `partial` 部分采纳 /
`overturned` 顾问意见推翻了我原来的方案 / `no_change` 顾问确认原方案、未改变任何动作 /
`rejected` 否决 / `deferred` 暂缓（记不清时用，不猜）。

---

## 2. 补记结果

账本（`~/.dsh/expert-advisor/state/ledger-*.jsonl`）在补记后：

- 有裁决的调用 **13 次**，决定 **39 个**：采纳 19、部分采纳 9、推翻原方案 6、确认无变化 5。
- 成功但未记录裁决 **0 次**；每个有用决定约 5,937 token，每个推翻原方案的决定约 29,190 token。

本次写入的 6 条 `verdict` 事件（时间戳 `2026-09-29T01:12:48`–`01:13:40+08:00`）：

| run_id | task_id | provider | 取值 |
| --- | --- | --- | --- |
| `2e611ee9adbe4e2497c7582445e56edb` | TASK-20260926-DEPT-STATUS-TABS-ROLLUP | codex-readonly | 1=overturned 2=adopted 3=partial |
| `ef50501c75a54fc1a3afe5a00f64d20e` | TASK-20260926-AUDIT-REVIEW | codex-readonly | 1=no_change 2=no_change 3=no_change |
| `8d7d71c5234d413596bb0bed053bd359` | TASK-20260926-NCR-PAA-ROLLUP | codex-readonly | 1=overturned 2=no_change 3=overturned |
| `074b92aeb6c74c9a966524bec02b76be` | TASK-20260926-SOR-RING-NCR-DATAMODEL | codex-readonly | 1=adopted 2=overturned 3=adopted |
| `b280ef0b-5fa0-4846-bc49-aa69ced02268` | TASK-LEAD-TOPOLOGY-20260927 | claude | 1=adopted 2=adopted 3=adopted |
| `8cc4025f-f6ec-4e07-b5b9-8bb472ef897e` | TASK-LEAD-PHASE0-20260927-R2 | claude | 1=adopted 2=partial 3=partial |

---

## 3. 逐条依据

### 3.1 TASK-20260926-DEPT-STATUS-TABS-ROLLUP（`2e611ee9…`）

依据：`docs/PLAN_20260926_DEPT_STATUS_TABS_SECTION_ROLLUP.md` §7「开放问题的裁决」与 §9「Codex 顾问审计记录」。
意见归档：`~/.dsh/expert-advisor/runs/codex-readonly-20260926-003019-c8968d80.advice.md`。

- **1 = overturned〔筛选/归集口径〕**：顾问指出「把目标值展开为原始值列表（含未归集负桶显式化）」在 500 截断下会**静默漏数**。方案文档 §4.3 明确"**放弃**该方案"，改**行级归集 + Python 层筛选、分页在筛选之后**。顾问意见推翻了我原写入方案的做法。
- **2 = adopted〔双口径 / 规则存储 / 旧载荷 / 矩阵形状〕**：读时归集的双口径被接受并写入文档；`app_settings` 独立键 `sectionRollup`；保留旧 `departmentStatus`/`sectionStatus` 载荷；矩阵载荷按顾问建议改为**嵌套对齐结构**。均按顾问意见落地。
- **3 = partial〔明细辅助列 / 测试 / 并发〕**：顾问建议的「归集后科室」辅助列**降级为可选、本轮不渲染**；测试盲区按建议补（空白/Unicode、重复别名、超量未归集值、分页总数等）；顾问的**并发保存锁测试未做**（本地单用户 + 单条 upsert 原子性足够，记录为已知取舍）。

### 3.2 TASK-20260926-AUDIT-REVIEW（`ef50501c…`）

依据：同上方案文档 §11「代码审计与处置」与 §12「审计结果的 Codex 顾问复审」。
意见归档：`~/.dsh/expert-advisor/runs/codex-readonly-20260926-032757-51f90048.advice.md`。

**三项均 no_change**：本次咨询是**对已实施修复结果的对抗式复审**——送审包内明写"已按此实施落地，全量门禁复跑全绿"，即修复先于复审。顾问确认 1 Major + 2 Minor + 1 Nit 定级与「两趟校验、保留名拦截」方向正确，并提三项「修改/核实」要求；主代理逐项核实后**均无需改动**：

1. `all_targets` 只收合法目标（`all_targets.add` 仅在目标通过全部校验后的 `else` 分支执行，无效目标的别名不会误拒合法别名）；
2. 全项目**不存在独立备份导出**功能（方案原文措辞不严），唯一诊断导出即 debug bundle，已覆盖；
3. 科室名/别名进入调试包不构成新披露类别（既有 analytics/policy/mapping 已含更细项目数据），**接受**。

即：顾问未改变任何动作。这正是新增 `no_change` 取值要捕捉的"该不该问"信号。

### 3.3 TASK-20260926-NCR-PAA-ROLLUP（`8d7d71c5…`）

依据：`docs/PLAN_20260926_NCR_EXPORT_EVIDENCE_PAA_CLOSE_ROLLUP_MATCH.md` §2 与 §9。
意见归档：`~/.dsh/expert-advisor/runs/codex-readonly-20260926-132324-fd5979d6.advice.md`。

- **1 = overturned〔F1 证据透出 / 状态码〕**：原计划把「脱敏后 ≤200 字符的上游响应片段」放进用户可见错误消息。顾问判「截断 ≠ 脱敏」。方案 §2.1 标注"**经顾问意见调整：不在用户可见消息里内联原始响应片段**"，改为无泄漏的结构签名 + 诊断记录。状态码 502（非 422）保留，与顾问一致。
- **2 = no_change〔F2 完成口径〕**：保持 EWO-only 写侧修复 + 存量靠重同步（顾问确认"写侧 + 重同步可接受"），**未**加读取侧重算。与顾问一致。
- **3 = overturned〔F3 归集匹配语义〕**：原计划任意包含匹配 + 最长优先/同长按序/单字不参与。顾问判"防误归集不足"。方案 §2.3 标注"**不做任意包含匹配**"，改先登记完整别名、精确匹配。顾问推翻了我已写入方案的做法。

### 3.4 TASK-20260926-SOR-RING-NCR-DATAMODEL（`074b92ae…`）

依据：`docs/PLAN_20260926_SOR_ROWS_RING_CLICK_NCR_SECTION_DATAMODEL_STATUS.md` §1–§8。
意见归档：`~/.dsh/expert-advisor/runs/codex-readonly-20260926-220927-ef855534.advice.md`。

- **1 = adopted〔F1 接入点〕**：顾问定"在连接器 `collect` 内从原始行生成规范化行，分析与表单消费；不建议下沉 `_query_page`"。方案 §1 标注"原始行与规范化行分离（**顾问要求**）"，按此实施。
- **2 = overturned〔F1 列契约别名〕**：原计划"生产键名未知时先行加入宽容别名（键不存在即跳过、无害）"。顾问判"'键不存在即跳过'不等于无害"，要求等样本。方案 §1 标注"列契约别名：**暂缓**（采纳顾问反对意见）"。顾问推翻了我原方案的动作。
- **3 = adopted〔F2 生命周期 / F3 代码制 / F4 派生列〕**：F2 按顾问结论从"仅委托监听"扩充为**两个独立故障机制**同修（方案 §2 标注"经顾问裁决扩充"）；`processInstanceStatus` 只取 `name`；F3 科室字段按顾问收紧为代码制；F4 派生显示列不改物理契约。均按顾问意见落地。

### 3.5 TASK-LEAD-TOPOLOGY-20260927（`b280ef0b…`）

依据：该任务交接纪要（本机 `sess_43ebe18c…` 交接胶囊）、`~/.dsh/skills/expert-advisor/CONTRACT.md`、
本机 `AGENTS.md`。意见归档：`~/.dsh/expert-advisor/runs/claude-20260927-195144-bde30358.advice.md`。
咨询包：`cliproxyapi-vps-claude/private-state/reports/consultation-lead-topology-20260927.md`。

- **1 = adopted〔VPS lead：退役 vs 休眠〕**：采纳顾问"先维持休眠、暂不改动远端"，并按顾问步骤 1 完成**只读取证休眠证据链**（`authorized_keys/claude-lead` 不存在、无 lead 凭据、role 由调用 UID 派生、远端不读 `roles.*.enabled`）；按顾问步骤 3 把 **Phase D ③④ 与 lead 解绑**；远端退役延后到已授权的维护窗口。
- **2 = adopted〔本机 claude-lead 是否接入为第三 caller〕**：包内原为开放问题，顾问给"**不接**"。已按此把 caller 白名单固定为 `dsh/zcode/manual` 并在 `CONTRACT.md` 写明排除理由，同时登记顾问新增的残余风险（broker 的 caller 为请求体自报，caller 级鉴权列为后续独立变更）。
- **3 = adopted〔硬边界 + 文档落地〕**：采纳两阶段边界（阶段 0 的 deny 规则 + 目录白名单 + 禁跳过权限/自动批准已落地；阶段 1 专用非管理员 Windows 用户按条件待启用；Desktop 远程接管在专用用户就位前禁用），并完成顾问列的 4 处文档落地。

### 3.6 TASK-LEAD-PHASE0-20260927-R2（`8cc4025f…`）

依据：同上交接纪要；意见归档：`~/.dsh/expert-advisor/runs/claude-20260927-200947-4e0f612c.advice.md`。
交接纪要自述"四条顾问裁定全部采纳"，与实际落地状态逐步核对如下。

- **1 = adopted〔`permissions.deny` 规则集〕**：按顾问给出的 deny 清单写入 `~/.claude/settings.json`（Read/Edit `~/.ssh`、桥仓库、两个 `.dsh` 子目录、`~/.codex`、两个凭据文件名、`backups`、settings 自 Edit 保护、ssh/scp/sftp/sshpass/plink/pscp/psftp 家族、`WebFetch` loopback；`ask` 管 git 网络操作；`disableBypassPermissionsMode`）。含顾问点名的 3 处**诚实降级标注**（Read deny 管不到 Bash 子进程、端口级/repo 级 git remote 无法用规则表达、原生 Windows 无 OS 沙箱）——阶段 0 记为"模型协作级边界"而非 OS 级隔离。
- **2 = partial〔local 配置处置〕**：已删 18 条 allow（3 条 python 系、4 条 ssh 系、sshpass 全路径、10 条含明文口令的 plink、1 条宽泛 `cd … && *`），`allow` 54 → 36。但顾问同条要求的 **SSH 口令轮换未执行**（泄漏口令需在局域网主机侧更换，属用户侧待办）→ 记 partial。
- **3 = partial〔合并与金丝雀验证 + 用量/Desktop〕**：金丝雀验证 T1–T6 **全绿**（含小写路径变体、`--dangerously-skip-permissions` 变体），用量按"仅记录数量级"处理——均按顾问落地；但 **Desktop 侧处置仅登记未闭合**（待用户说明是否用 Code 功能、是否配文件系统类 MCP）→ 记 partial。

---

## 4. 口径说明（与 `MAX_DECISIONS=3` 的关系）

入口对单次决定数硬上限为 3（`advisor_core.py: MAX_DECISIONS = 3`；SKILL 记载"待决决定超过 3 个直接拒绝"）。
而 2026-09-26 的四个旧包在「待决问题」小节列了 4–7 项（当时尚无该预检）。因此本次补记按**决策轴**把每个包
的多问项**合并成 ≤3 个 slot**，slot 取值取该组整体结论；合并方式已在 §3 每条中写明，未虚构条目。
2026-09-28 起的包已按"3 个待决决定"制包，与账本 3 slot 一一对应。

`overturned` 与 `adopted` 的分界（本次实际使用）：顾问**否决/推翻了我已写入方案或已计划的**做法 → `overturned`；
顾问提出建议而我照做、且原方案方向未被推翻 → `adopted`；顾问只是确认、我未改任何动作 → `no_change`。
据此，`docs/ADVISOR_SCOPE_EVALUATION_20260928.md` §五 把 `074b92ae` 记作"5 项全采纳"，
按新语义其中的 F1 列别名一项应单列为 `overturned`。

---

## 5. 边界与遗留

- 本次**未**触碰两条 `--caller dsh` 条目：`vse-aras-formed-20260925`、`TASK-20260925-NCR-LABEL-COLLISION`。
  它们在 `2026-09-29T01:10:16+08:00` 由 dsh lead 自行补记，与本代理无调用关系。
- `docs/ADVISOR_SCENARIO_EVALUATION_20260928.md` §2.1 与 §6 仍写"只有 5 次调用回写裁决""需补齐未回写的
  8 次调用"，**已过时**（补记后 13 次调用 / 39 项决定全部回写，未回写 0 次）。该文档为用户评审材料，
  本次**未改动**，留待用户决定是否同步。
- 相关记忆已同步更新：`expert-advisor-consultation`（补入 `overturned`/`no_change` 语义、3 slot 合并规则
  与最新账本统计）。
