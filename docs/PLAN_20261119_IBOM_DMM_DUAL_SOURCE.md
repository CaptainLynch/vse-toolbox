# 数模设计审核流程 TDC + iBOM 双源并行方案

> 日期：2026-11-19 · 分支 `refactor/ux-v2` · 状态：**待确认，未动工**
> 前置：[`IMPACT_20261118_IBOM_SWITCH.md`](IMPACT_20261118_IBOM_SWITCH.md) §11（阶段 0A 实测：iBOM DMM 报表与 47 列契约只差第 0 列）
> 范围：只涉及 D5 数模设计审核流程（`tdc_data_model`）及其下游。SOR、A 面、EWO/PAA/NCR 不在本方案内。

---

## 0. 决策

### 0.1 已确认（2026-11-19）

| # | 决策 | 方案中的落点 |
|---|---|---|
| C1 | 业务上老单留在 TDC 走完、新单都进 iBOM；**两边都有的单的处理规则仍然保留**，作为兜底 | §4 合并规则 |
| C2 | 任何一边取数失败或不完整：**不算全量，日报不用它** | §5 完整性规则 |
| C3 | iBOM 账号已能正常使用，走自动抓取；**保留手工导入**作为备用 | §3.2 自动取数、§6 手工导入 |

### 0.2 待确认（动工前需要你定）

| # | 问题 | 方案默认值 | 影响 |
|---|---|---|---|
| Q1 | iBOM 账号是**域账号**（和 Aras/TDC 同一套用户名密码、走 SSO），还是 iBOM **本地账号**（走普通登录、密码 3–15 位字母数字）？ | 未定，§3.3 两条路都写了 | 决定凭据怎么存、统一登录要不要带上 iBOM。**本地账号绝不能拿域密码去试**：错 3 次锁号、不自动解锁 |
| Q2 | 签署人数口径：TDC 按「人次」，iBOM 报表按「人」去重 | **(a) 沿用人次**：iBOM 行的应签/已签/未签由签署日报从角色列自算 | 选 (b)「用 iBOM 字段」则签署率曲线在切换处断开 |
| Q3 | 项目名 `TRA_2.0` 这类是不是原来的 `Ar-` 架构件？还有其他前缀吗？ | 先不改归属规则，等你确认 | 不改的话，iBOM 的架构单会被算成项目件 |
| Q4 | 两边取数失败时快照怎么处理 | **不发布新快照**，本次运行标「需关注」，界面继续显示上一份全量快照（§5.2 说明理由） | 另一种是「发布但标残缺」，要改约 10 处读快照的代码 |

---

## 1. 总体架构

```
                       ┌─ TDC 侧：现有 TDCCrawlerClient.export_data_model（不动）
  一次同步运行 ────────┤
 （归档 / 项目状态同步）└─ iBOM 侧：自动 exportReport；或本次运行指定的手工导入文件
                              │
                              ▼
        services/data_model_dual_source.py（新）
          1. 两侧各自读成 47 列契约行（iBOM 用表头变体）
          2. 每行打来源标记 sourceSystem = tdc | ibom
          3. 两侧都完整 → 按流水单号合并；任一侧不完整 → 返回失败原因
                              │
              完整 ──────────┼────────── 不完整
                ▼                           ▼
   现有范围剔除 / 关注清单 / 发布快照      不发布快照，运行标「需关注」，
   （form_key 仍是 tdc_data_model）        成功那一侧的原件照常归档
                ▼
   签署日报、交付物、项目总览、关注清单……（都只读这一份快照）
```

**不变的东西**（下游零感知）：

- `form_key` / 归档任务键仍是 `tdc_data_model`，快照表、路由 `/api/tdc/*`、前端入口都不改名。历史快照与新快照在同一条时间线上。
- 47 列契约 `core/report_headers.json` 不改。来源标记放在快照行已有的 `dimensions` 字段里，不加列。
- TDC 一侧的抓取、鉴权、续期代码不动。

---

## 2. iBOM 报表读入（表头变体）

**改动**：`services/tdc_official_rows.py`

- 新增一个表头变体参数（例如 `variant="ibom"`）。只改第 0 列的期望值：TDC 是 `实例号`，iBOM 是 `序号`；其余 46 列仍逐字、逐序严格校验，多列、少列、错位照样拒绝。
- iBOM 变体读入后，把 `实例号` **置空**，不把行号当实例号（行号会污染去重身份键和关注清单匹配）。
- 两种变体**只按调用方显式指定**，不做「哪个能过就用哪个」的自动识别，避免把错误的文件静默放行。
- TXT（Unicode 文本 / GBK 文本）和 xlsx 两种格式都支持，复用现有 `services/tdc_text_rows.py`。

**测试**：`tests/test_tdc_official_rows.py` 增加用例：iBOM 表头通过、`实例号` 置空、第 1–46 列任一处改动仍被拒、TDC 变体遇到 iBOM 表头仍被拒。

---

## 3. iBOM 取数与鉴权

### 3.1 客户端：`services/ibom_client.py`（新）

只实现本方案要用的接口：

| 能力 | 接口 |
|---|---|
| 会话 | `/fwSecurity/authentication/checkToken.api` 换 `usertoken` |
| DMM 报表 | `/bommgmt/partDigitalModelChange/exportReport.api`（同步文件流） |
| 列表计数（完整性核对用） | `/bommgmt/change/smartQuery.api`，`DISCRIMINATOR=DMM`，取 `totalCount` |

通用规则（来自实测）：

- 请求头 `x-content-md5` = 请求体 UTF-8 字节的 hex MD5（已用 HAR 238 条核对）。
- 成功判定：HTTP 200、`x-g-process-result` 不为 `error`、JSON 的 `state == "success"`；空 body 一律当失败。
- 导出判定：`Content-Type` 为 `application/x-download`、内容以 `PK` 开头、文件名取 `Content-Disposition`。
- 报表字节直接在内存里解析，不落成中间文件（终端加密只作用于落盘文件）。原件仍按现有方式写入归档目录留证。
- 主机白名单只放 `ibom.sgmw.com.cn`。

### 3.2 自动取数

- 每次同步运行：先 `smartQuery` 取 DMM `totalCount`，再导出报表，按**单据数**核对（报表里不重复的流水单号数 = `totalCount`）。不一致视为不完整。
- 报表不分页、不带筛选，一次导出当前账号可见的全部 DMM。项目状态同步里的科室、车型等筛选条件，在 iBOM 侧**本地应用**到 47 列值上（与 TDC 侧现有的「科室本地收窄」同一套逻辑），不去猜 iBOM 的筛选字段。

### 3.3 鉴权（取决于 Q1）

| | 域账号（SSO） | iBOM 本地账号 |
|---|---|---|
| 登录 | 复用 `account.sgmw.com.cn` 统一身份登录，落到 `/fwPlatform/ssoAuth/login.api`，再 `checkToken` | 平台普通登录接口（路径与加密方式需先从前端取证一次，见 §8 阶段 1） |
| 凭据 | 与 Aras/TDC 共用现有域账号凭据（`SYNC_CREDENTIAL_REF`） | **单独一份凭据**，单独录入、单独存（Windows 凭据管理器 + DPAPI，沿用现有机制） |
| 统一登录页 | 加上 iBOM 一项，三系统一起登 | **不加**：统一登录的域密码不能发给 iBOM |

两种情况都遵守：

- **登录失败不重试**：任何认证失败直接结束本次运行，标「需关注」。本地账号错 3 次锁号且不自动解锁。
- 会话只在本次运行内使用，运行结束即丢弃；不做后台保活。

---

## 4. 合并规则：`services/data_model_dual_source.py`（新）

纯函数，输入两侧的契约行，输出合并后的行和合并报告。

**单据为单位**：先按 `流水单号` 把两侧的行各自分组（一张单 = 它的全部零件行）。

| 情况 | 处理 |
|---|---|
| 单号只在 TDC | 采用 TDC 的全部行 |
| 单号只在 iBOM | 采用 iBOM 的全部行 |
| 两边都有，一边是终态废弃（`已废弃`/`已撤回`/`取消`），另一边不是 | 采用不是废弃的那一边 |
| 两边都有，都有效（或都废弃） | 采用 **iBOM**，并记为「双系统单」 |
| 两边都有，且零件号集合或申请人不同 | 仍按上一行取舍，另记为「冲突」 |

- **绝不跨源拼行**：同一张单只取一侧的全部行，不把两边的零件行混在一起。
- 每行写入 `dimensions.sourceSystem`（`tdc` / `ibom`）。不用 `dataSource`，那个键已用于项目件/架构件归属。
- 合并报告写进快照 `summary`：两侧单据数与行数、双系统单列表、冲突单列表（只放单号）。同时发一条诊断事件，便于在「诊断」页看到。
- 合并发生在现有的「范围剔除」和「关注清单」**之前**，这样废弃单的取舍规则能生效；之后的剔除、关注清单逻辑不变。

**测试**：新增 `tests/test_data_model_dual_source.py`，覆盖上表每一行、跨源不拼行、`dimensions` 标记、报告内容。

---

## 5. 完整性规则

### 5.1 判定

本次运行两侧都满足下列条件才算完整：

| 侧 | 完整条件 |
|---|---|
| TDC | 现有判定不变：官方工作簿通过契约、未截断，或接口兜底分页完整 |
| iBOM（自动） | 认证成功、报表通过表头校验、未截断、单据数 = `totalCount` |
| iBOM（手工） | 文件通过表头校验、未截断；**数据日期由导入人确认**（沿用签署日报导入「需要人工确认数据截至日期」的做法） |

### 5.2 不完整时：不发布快照（Q4 默认值）

- 返回新的投影错误 `dual_source_incomplete`，走现有 `_finalize_collection_attention`：**不发布表单快照**，运行状态记为「需关注」，结果摘要写明哪一侧、什么原因。
- 成功的那一侧，原件照常归档，便于事后核对。
- 因为没有发布新快照，签署日报、交付物、项目总览会继续使用上一份完整快照，并显示它的数据时间。这满足 C2「不算全量，日报不用它」。

选「不发布」而不是「发布但标残缺」，是因为读「最新快照」的地方有十来处（`services/form_search.py`、`services/deliverable_form_analysis/_impl.py`、`web/crawler_boot.py`、`web/project_status_boot.py`、`plugins/deliverable_forms/backend.py`、`plugins/project_overview/backend.py`、`plugins/sign_daily/service.py`、`backend.py`、`scheduled.py`）。另外，`services/data_model_watchlist.py::snapshot_coverage` 遇到不认识的覆盖类型会当成全量。发布残缺快照，就得十来处全部改对，漏一处就会把残缺数据当全量用。

### 5.3 两个发布者都要接入

`tdc_data_model` 快照有两个发布者，都改成经过 §4 的双源合并：

1. 定时归档：`services/scheduled_archive_connectors.py::TDCArchiveConnector`（`tdc_data_model` 分支）。
2. 项目状态同步：`services/project_status_connectors.py::TDCProjectStatusConnector` 的数模分支，由 `services/project_status_sync_runner.py` 发布。

两处都调用同一个 `data_model_dual_source` 入口，不各写一套。

---

## 6. 手工导入（保留）

两种用途，分开处理：

| 用途 | 入口 | 行为 |
|---|---|---|
| **A. 代替本次自动抓取的 iBOM 侧** | 「自动归档」页数模任务新增「用本地 iBOM 报表同步」（上传 xlsx 或 TXT） | 立即触发一次同步：TDC 侧照常在线抓，iBOM 侧用上传文件；仍按 §4 合并、§5 判完整，成功才发布快照。快照 `summary` 记 `ibom.feed = "manual"` 和文件名 |
| **B. 签署日报的本地导入**（现有功能） | 签署日报「本地导入」 | 现有逻辑不变（与快照物理隔离），只是**额外接受 iBOM 表头变体**。导入的是哪种表头，写进 `importMeta.sourceVariant`，界面标注「来源：iBOM 报表」 |

用途 A 只在 iBOM 自动抓取不可用时使用；没有 TDC 侧时同样判为不完整，不发布。

---

## 7. 下游适配

### 7.1 状态词：扩展闭集，不改写原值

原值保留在快照里（诚实渲染），只扩展各处的识别集合：

| 位置 | 现状 | 改动 |
|---|---|---|
| `services/deliverable_form_analysis/_impl.py` 完成集（约 106 行） | 已含 `已发布` | 不改 |
| 同文件 `TDC_SYNC_EXCLUDED_STATUSES`（约 326 行） | `已废弃`、`已撤回` | 加 `取消` |
| `services/scope_exclusion.py` | 复用上面的集合 | 随之生效，补测试 |
| `services/project_status_connectors.py` `_TDC_KNOWN_DATA_MODEL_CODES`（约 417 行） | `{2,4}` ∪ `{已废弃,已撤回}` | 加 `审批中`、`已发布`、`退回`、`草稿`、`取消`，避免诊断噪声 |
| `plugins/sign_daily/rules.py` | `STATUS_DONE="已完成"`、`STATUS_DISCARDED="已废弃"`、在途集 `{进行中,审批中}` | 完成集加 `已发布`；废弃集加 `取消`；在途集加 `退回`、`草稿` |

### 7.2 签署日报规则

- **阶段判定先看状态**：`草稿` → 待提交，`退回` → 退回修改，再走现有的角色列推导。修正实测中的问题：草稿单被判成「会签中」或「待锁定」、取消单被判成「会签中」。
- 草稿单待审批人员为空属正常，不再报 `pendingEmpty`。
- **计数（Q2 默认 (a)）**：`sourceSystem == "ibom"` 的单，应签/已签/未签/签署率由角色列按人次自算；报表里的计数字段只作参考，不再报 `requiredCountDiffer`/`unsignedCountDiffer`。TDC 的单保持现状（以字段为准）。
- **日变化跨来源**：按流水单号对齐的逻辑不变。若同一单号在基线和今天的来源不同，变化行标注「来源切换」，不算成「签完 + 新增」。
- 界面在数据时间旁显示「TDC n 张 / iBOM m 张」，有双系统单或冲突单时显示数量并可展开单号。

### 7.3 归属与关注清单

- 关注清单、车型-架构单人工关联：按流水单号匹配，**不改**。`实例号` 只在 TDC 行上有值。
- 归属规则 `services/data_model_attribution.py`：等 Q3 确认后，再决定是否把 `TRA_` 加入架构件前缀。本方案先不改。

### 7.4 文案

`TDC 数模`、`会先自动刷新 TDC 数据` 等文案改为「数模设计审核流程（TDC + iBOM）」。涉及 `plugins/sign_daily/static/report.js`、`plugins/workbench/static/reports.js`、`plugins/system_query/static/modes.js` 等，只改显示文字，不改键名。

---

## 8. 实施阶段与验收

| 阶段 | 内容 | 预计 | 验收 |
|---|---|---|---|
| **1. 鉴权取证与客户端** | 按 Q1 确定登录路线；本地账号路线需先用探测脚本从前端取一次登录接口路径与加密方式（不提交密码）。实现 `ibom_client.py` + 认证 | 1.5–2 天 | 用真实账号无人值守跑通「登录 → 计数 → 导出 → 内存解析」；认证失败只尝试一次即停止；日志与诊断里不出现 token 和密码 |
| **2. 表头变体 + 合并 + 完整性** | §2、§4、§5；两个发布者接入 | 2–2.5 天 | 新增与改动的单元测试全部通过；用 0A 取得的真实报表 TXT 回放：43 张单 / 167 行全部进入合并结果；模拟一侧失败时不发布快照、运行为「需关注」 |
| **3. 下游适配** | §7.1、§7.2、§7.4 | 2–2.5 天 | 签署日报现有测试全部通过（按新规则更新的用例需逐条说明）；用真实报表生成日报：0 条 `unknownStatus`，草稿/退回/取消的阶段正确；同一份数据在 TDC 口径下的历史日报结果不变 |
| **4. 手工导入** | §6 用途 A、B | 1 天 | 上传 iBOM 报表能触发同步并发布；签署日报本地导入能识别 iBOM 表头并标注来源 |
| **5. 真机验收** | 内网真实环境 | 0.5 天 + 观察期 | 连续 3 个工作日自动同步成功；每天抽 3 张 iBOM 单，与 iBOM 界面核对零件行、签署人和状态 |

合计约 7–8 个工作日（不含观察期）。每阶段结束跑相关测试；全部完成后跑一次全量 `pytest`，输出放 `.runtime/`。

**涉及测试文件**（改动或新增）：`test_tdc_official_rows.py`、`test_scheduled_archive_connectors.py`、`test_scheduled_archive_runner.py`、`test_project_status_connectors.py`、`test_project_status_sync_runner.py`、`test_deliverable_form_analysis.py`、`test_sign_daily_*`、新增 `test_ibom_client.py`、`test_ibom_auth.py`、`test_data_model_dual_source.py`。

---

## 9. 退出 TDC

满足以下两条后，在归档任务配置里关闭 TDC 侧（新增配置项 `sources: ["tdc", "ibom"]`，默认两侧都开）：

1. TDC 不再接收新单（连续 N 天 TDC 侧无新流水单号，N 由你定）；
2. TDC 侧在途单全部到达已完成或已废弃。

关闭后合并结果只剩 iBOM，完整性只看 iBOM 一侧。历史快照里的 `sourceSystem` 标记保留，可追溯。

---

## 10. 风险

| 风险 | 对策 |
|---|---|
| iBOM 账号可见范围不全（当前账号只见 43 张单，单号已编到 1805） | 阶段 5 用 `totalCount` 与业务确认的总数核对；可见范围不足时需要 IT 调整账号权限，代码无法弥补 |
| iBOM 报表表头日后变动 | 严格表头校验会拒收并标「需关注」，不会静默错位 |
| 同一人兼两个角色时，iBOM 报表按人合并签署状态，少算一笔待办 | 已知偏差，记入日报说明；如需精确，后续可用审批节点接口校正（不在本方案内） |
| 本地账号被锁 | 登录失败不重试；统一登录不向 iBOM 发送域密码 |
| 双系统单比预期多 | 合并报告和诊断事件会显示数量与单号，按 §4 规则取舍，不丢单 |

---

## 11. 不在本方案内

- SOR（D2）、造型 A 面（D4）、EWO / PAA / NCR 迁移。
- 用审批节点接口逐人校正待办（§10 第 3 条）。
- 用 iBOM 接口替代报表取数。报表已覆盖 47 列，接口只在完整性核对时取 `totalCount`。
