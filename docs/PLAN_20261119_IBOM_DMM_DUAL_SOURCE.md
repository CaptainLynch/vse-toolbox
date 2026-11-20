# 数模设计审核流程 TDC + iBOM 双源并行方案

> 日期：2026-11-19 · 分支 `refactor/ux-v2` · 状态：**决策已确认，已过开工前架构评审（§12），待最后确认后开工**
> 前置：[`IMPACT_20261118_IBOM_SWITCH.md`](IMPACT_20261118_IBOM_SWITCH.md) §11（阶段 0A 实测：iBOM DMM 报表与 47 列契约只差第 0 列）
> 范围：只涉及 D5 数模设计审核流程（`tdc_data_model`）及其下游。SOR、A 面、EWO/PAA/NCR 不在本方案内。

---

## 0. 决策

### 0.1 已确认（2026-11-19）

| # | 决策 | 方案中的落点 |
|---|---|---|
| C1 | 业务上老单留在 TDC 走完、新单都进 iBOM；**两边都有的单的处理规则仍然保留**，作为兜底 | §4 合并规则 |
| C2 | 任何一边取数失败或不完整：**不算全量，日报不用它**；具体做法为**不发布新快照** | §5 完整性规则 |
| C3 | iBOM 走自动抓取；**保留手工导入**作为备用 | §3、§6 |
| C4 | iBOM 账号是**域账号**（与 Aras/TDC 同一套用户名密码） | §3.3 鉴权 |
| C5 | 签署人数沿用 TDC 的**人次**口径 | §7.2 |
| C6 | `TRA_2.0` 这类项目名是**架构件** | §7.3 |

### 0.2 阶段 0B 取证结论（2026-11-20，`vse_phase0b` JSON）

| # | 结论 | 方案中的落点 |
|---|---|---|
| Q5 | 生产上只有归档任务 `tdc_data_model` 在用，筛选为 `projectModel = "AR-C"`、`section = "车体科"`；D5 项目状态绑定**未配置**（`matchRule` 为空、未启用） | §3.4 补实现这两个键；§5.3 见 Q8 |
| — | TDC 最新快照 9 张单（19 行）全是 `Ar-C`/车体科；与 iBOM 43 张单**无交集**；TDC 早期架构单编号为 `Ar-C-3D-0044` 形态，与 iBOM 不撞号 | 符合 C1；双系统单规则仍保留作兜底 |
| — | iBOM 当前**没有项目名为 `Ar-C` 的单**；唯一的架构件 `TRA_2.0`（3D-00001799）属底盘科；iBOM 车体科的单全是项目件（CF810P、F620S、F710C） | 见 Q7 |

### 0.3 还需要你定的两件事

| # | 问题 | 方案默认值 | 影响 |
|---|---|---|---|
| Q7 | TDC 的 `Ar-C` 架构平台，在 iBOM 里项目名叫什么？（仍叫 `Ar-C`？还是 `TRA-C`、`TRA_xx` 之类？） | 归档任务新增可选配置「iBOM 项目名对照」，默认空，即只认 `Ar-C` 本身；同时每次运行把被项目名筛掉的「架构类项目名」（`TRA*`/`Ar*`）写进运行摘要 | 不配对照的话，车体科的 Ar-C 架构单在 iBOM 里一旦换了名字，iBOM 侧会一直是 0 行而且不报错；运行摘要里的提示能让你及时发现 |
| Q8 | D5 项目状态绑定目前没在用，本期是否**只做定时归档这一个发布者**？ | **是**：项目状态同步的数模路径本期保持只看 TDC，界面提示「iBOM 单请看数模报表」；R1 的「一分为二」转换推迟到真要启用 D5 绑定时再做 | 省约 1 天；以后启用 D5 绑定前必须先补上，否则会漏算 iBOM 单 |

---

## 1. 总体架构

```
                       ┌─ TDC 侧：现有抓取（不动）
  一次同步运行 ────────┤
 （归档 / 项目状态同步）└─ iBOM 侧：自动 exportReport；或本次运行指定的手工导入文件
                              │
                              ▼
        services/data_model_dual_source.py（新）
          1. iBOM 侧读成 47 列契约行（表头变体），在本地套用筛选条件
          2. 每行带来源标记 _sourceSystem = tdc | ibom
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

- `form_key` / 归档任务键仍是 `tdc_data_model`；快照表、`/api/tdc/*` 路由、前端入口都不改名。历史快照与新快照在同一条时间线上。
- 47 列契约 `core/report_headers.json` 不改；来源标记进快照行已有的 `dimensions_json`，不加列。
- **不新增数据库表**，不改 `core/db_manager.py`。
- TDC 一侧的抓取、鉴权、续期代码不动。

---

## 2. iBOM 报表读入（表头变体）

**改动**：`services/tdc_official_rows.py`

- 新增表头变体参数 `variant`（`"tdc"` 默认 / `"ibom"`）。`ibom` 只把第 0 列的期望值从 `实例号` 换成 `序号`；其余 46 列仍逐字、逐序严格校验，多列、少列、错位照样拒绝。
- `ibom` 变体读入后把 `实例号` **置空**，不把行号当实例号：实例号是项目状态单记录绑定的权威身份，也参与关注清单匹配。
- 变体**只由调用方显式指定**，不做「哪个能过就用哪个」的自动识别。
- TXT（Unicode 文本 / GBK 文本）与 xlsx 都支持，复用 `services/tdc_text_rows.py`。

**测试**：`tests/test_tdc_official_rows.py` 增加用例：iBOM 表头通过、`实例号` 置空、第 1–46 列任一处改动仍被拒、TDC 变体遇到 iBOM 表头仍被拒。

---

## 3. iBOM 取数、鉴权与筛选

### 3.1 客户端：`services/ibom_client.py`（新）

| 能力 | 接口 |
|---|---|
| 会话 | `/fwSecurity/authentication/checkToken.api` 换 `usertoken` |
| DMM 报表 | `/bommgmt/partDigitalModelChange/exportReport.api`（同步文件流） |
| 单据总数（完整性核对） | `/bommgmt/change/smartQuery.api`，`DISCRIMINATOR=DMM`，取 `totalCount` |

- 请求头 `x-content-md5` = 请求体 UTF-8 字节的 hex MD5（已用 HAR 238 条核对）。
- 成功判定：HTTP 200、`x-g-process-result` 不为 `error`、`state == "success"`；空 body 一律当失败。
- 导出判定：`Content-Type` 为 `application/x-download`、内容以 `PK` 开头、文件名取 `Content-Disposition`。
- 报表字节在内存里解析，不落中间文件；原件按现有方式写入归档目录留证。
- 主机白名单只放 `ibom.sgmw.com.cn`。

### 3.2 自动取数

- 每次运行：先取 `totalCount`，再导出报表；报表里不重复的流水单号数必须等于 `totalCount`（0A 实测 43 = 43），否则判为不完整。
- 报表一次导出当前账号可见的全部 DMM，不分页、不带服务器端筛选。

### 3.3 鉴权（域账号）

- **凭据**：与 Aras/TDC 共用现有域账号凭据（定时任务用的 `SYNC_CREDENTIAL_REF`），不新增凭据。
- **登录链**：域账号登录 iBOM 的具体跳转方式**还没有取证**（0A 的 HAR 只录了 XHR，没有页面跳转）。阶段 1 的第一步是补录一次 SSO 跳转链（取证清单 F 项，改为必做），确认是走 `account.sgmw.com.cn` 统一身份、还是 iBOM 普通登录对接域账号，再实现 `services/ibom_auth.py`。
- **防锁号顺序**：同一次运行里，**只有 TDC 用同一份密码登录成功之后，才去登录 iBOM**；TDC 登录失败时本次 iBOM 侧直接判为不完整，不再发送密码。任何认证失败都**不重试**。这样一次错误的密码最多在域里多计一次失败。
- **统一登录页**：加上 iBOM 一项，顺序放在 TDC 之后，沿用同一条规则。
- 会话只在本次运行内使用，运行结束即丢弃；本方案不把 iBOM 接入续期协调器（`web/app.py` 的 `{"aras","tdc"}` 保持不变）。

### 3.4 筛选条件在 iBOM 侧的本地套用

TDC 侧的筛选照旧发给 TDC 服务器；iBOM 侧拿到全量报表后，按下表在本地套用同含义的筛选：

| 筛选键 | iBOM 侧本地处理 |
|---|---|
| `documentNo` / `documentNos` / 关注清单 | 按 `流水单号` 精确匹配（与现有本地匹配同一实现） |
| `sections`（科室多选） | 按 `部门` 列科室归集（与现有 `_narrow_by_sections` 同一实现；0A 实测 iBOM 的 `部门` 列就是科室名） |
| `incident`（实例号） | 实例号只存在于 TDC，**iBOM 侧取 0 行并视为完整** |
| `applicationStart` / `applicationEnd` | 按 `申请日期` 的日期部分做闭区间比较 |
| `status` | 按 `状态` 列精确匹配 |
| `projectModel` | 按 `项目/车型` 列**去首尾空白、忽略大小写精确匹配**（实测 TDC 用 `AR-C` 筛出 `Ar-C`）；另可配置「iBOM 项目名对照」（Q7），对照表里的名字视同匹配 |
| `section`（单值科室，TDC 的 `department` 参数） | 按 `部门` 列去首尾空白精确匹配（实测 TDC 用 `车体科` 筛出 `部门 = 车体科`） |
| `applicant`、`partNumber`、`modelNumber` | 生产未使用，TDC 匹配方式未取证：**fail-closed**，有值时 iBOM 侧判为不完整，并在「需关注」原因里写明是哪个键 |
| `department`（TDC 的上级部门 `superDepartment`） | iBOM 报表没有上级部门列：**fail-closed**，同上 |

每次运行在摘要里记录：iBOM 报表总单数、经各筛选键后剩余单数，以及被 `projectModel` 筛掉的架构类项目名（`TRA*`/`Ar*`）及其单数，便于发现 Q7 的命名变化。

---

## 4. 合并规则：`services/data_model_dual_source.py`（新）

纯函数，输入两侧的行和各自的完整性，输出合并后的行和合并报告。

**单据为单位**：先按流水单号把两侧的行各自分组。流水单号取自 `流水单号` 或 `documentNo`；状态取自 `状态` 或 `status`，数字码按现有 `_normalize_tdc_status` 归一后再判断。这两组键都要认，因为 TDC 侧既可能是官方工作簿行（中文键），也可能是列表接口兜底行（英文键）。

| 情况 | 处理 |
|---|---|
| 单号只在 TDC | 采用 TDC 的全部行 |
| 单号只在 iBOM | 采用 iBOM 的全部行 |
| 两边都有，一边是终态废弃（`已废弃`/`已撤回`/`取消`），另一边不是 | 采用不是废弃的那一边 |
| 两边都有，都有效（或都废弃） | 采用 **iBOM**，并记为「双系统单」 |
| 两边都有，且零件号集合或申请人不同 | 仍按上一行取舍，另记为「冲突」 |

- **绝不跨源拼行**：同一张单只取一侧的全部行。
- 每行加保留键 `_sourceSystem`（`tdc` / `ibom`），由 §5.4 写入快照行的 `dimensions`。不用 `dataSource`，那个维度键已用于项目件/架构件。
- 合并报告写进快照 `summary`：两侧单据数与行数、双系统单与冲突单的单号列表；同时发诊断事件。
- 合并在现有「范围剔除」「关注清单」**之前**进行，废弃单取舍规则才能生效；之后的剔除、关注清单逻辑不变。

**测试**：新增 `tests/test_data_model_dual_source.py`，覆盖上表每一行、中英文两种键、跨源不拼行、来源标记、报告内容。

---

## 5. 完整性与发布

### 5.1 判定

| 侧 | 完整条件 |
|---|---|
| TDC | 现有判定不变 |
| iBOM（自动） | 认证成功、表头校验通过、未截断、单据数 = `totalCount`、§3.4 没有 fail-closed 的筛选键 |
| iBOM（手工） | 表头校验通过、未截断、§3.4 同上；数据日期由导入人确认 |

### 5.2 不完整时：不发布快照

- **定时归档**：返回新的投影错误 `dual_source_incomplete`，走现有 `_finalize_collection_attention`：不发布表单快照，运行记为「需关注」，结果摘要写明哪一侧、什么原因；成功一侧的原件照常归档。
- **项目状态同步**：与 TDC 侧现有的 `_require_complete_result` 一样直接抛错停跑：本次不写入结果、保留上一次的值与快照。

所有读快照的页面继续使用上一份完整快照并显示它的数据时间，满足 C2。

不采用「发布但标残缺」：读最新快照的地方有十来处（`services/form_search.py`、`services/deliverable_form_analysis/_impl.py`、`web/crawler_boot.py`、`web/project_status_boot.py`、`plugins/deliverable_forms/backend.py`、`plugins/project_overview/backend.py`、`plugins/sign_daily/service.py`、`backend.py`、`scheduled.py`），而 `services/data_model_watchlist.py::snapshot_coverage` 遇到不认识的覆盖类型会当成全量，漏改一处就会误用残缺数据。

### 5.3 两个发布者，两种行形状

`tdc_data_model` 快照有两个发布者，**行的形状不同**，接入方式要分开设计：

| 发布者 | 现在的行 | iBOM 行怎么进去 |
|---|---|---|
| 定时归档 `services/scheduled_archive_connectors.py::TDCArchiveConnector` | 官方 47 列行（中文键）；官方工作簿不可读时退回列表接口行 | 直接用 47 列行，与 TDC 行一起进合并 |
| 项目状态同步 `services/project_status_connectors.py::TDCProjectStatusConnector` | **列表接口行**（英文键，`incident`、`documentNo`、状态数字码），官方 47 列只作 `official_rows`，按 `(流水单号, 零件号)` 补齐 27 个缺失列 | iBOM 行**一分为二**：①按 `core/report_contracts.py::_TDC_DATA_MODEL_SOURCE_FIELDS` 把 20 个映射列转成列表形状（`incident` 置空、`status` 保留中文）；②原 47 列行并入 `official_rows`，由现有补齐逻辑按 `(流水单号, 零件号)` 对上。0A 实测报表内无重复的 `(流水单号, 零件号)`，补齐不会出现 ambiguous |

两处都调用 `data_model_dual_source` 的同一个合并入口；项目状态侧多一个「47 列行 → 列表形状」的转换函数，放在同一模块并单独测试。

项目状态同步的单记录绑定以 `incident` 为唯一权威身份（`services/project_status_records.py::authoritative_record_identity`，不允许回退）。iBOM 单没有实例号，**不能用单记录方式绑定**；D5 契约本身是聚合绑定（`aggregate: True`），按流水单号/多单号/科室聚合不受影响。界面上「实例号」输入项加提示：只适用于 TDC 单。

### 5.4 来源标记写入快照行

- `services/deliverable_form_analysis/_impl.py` 的行规范化读取保留键 `_sourceSystem`，写入该行 `dimensions.sourceSystem`；没有该键的行（历史快照、TDC 单）视为 `tdc`。
- 保留键不进 47 列值，不影响列映射和表头校验。

---

## 6. 手工导入（保留）

| 用途 | 入口 | 行为 |
|---|---|---|
| **A. 代替本次自动抓取的 iBOM 侧** | 「自动归档」页数模任务新增「用本地 iBOM 报表同步」（上传 xlsx 或 TXT） | 触发一次归档运行：TDC 侧照常在线抓，iBOM 侧用上传文件；仍按 §4、§5 判定，成功才发布快照；`summary` 记 `ibom.feed = "manual"` 与文件名 |
| **B. 签署日报的本地导入**（现有功能） | 签署日报「本地导入」 | 逻辑不变（与快照物理隔离），额外接受 iBOM 表头变体；变体写进 `importMeta.sourceVariant`，界面标注「来源：iBOM 报表」，计数按 §7.2 的 iBOM 规则 |

用途 A 只走定时归档的发布者，不经项目状态同步。

---

## 7. 下游适配

### 7.1 状态词：扩展闭集，不改写原值

| 位置 | 现状 | 改动 |
|---|---|---|
| `services/deliverable_form_analysis/_impl.py` 完成集 | 已含 `已发布` | 不改 |
| 同文件 `TDC_SYNC_EXCLUDED_STATUSES` | `已废弃`、`已撤回` | 加 `取消` |
| `services/scope_exclusion.py` | 复用上面的集合 | 随之生效，补测试 |
| `services/project_status_connectors.py` `_TDC_KNOWN_DATA_MODEL_CODES` | `{2,4}` ∪ `{已废弃,已撤回}` | 加 `审批中`、`已发布`、`退回`、`草稿`、`取消`，避免诊断噪声 |
| `plugins/sign_daily/rules.py` | `STATUS_DONE="已完成"`、`STATUS_DISCARDED="已废弃"`、在途集 `{进行中,审批中}` | 完成集加 `已发布`；废弃集加 `取消`；在途集加 `退回`、`草稿` |
| `core/diagnostic_recording.py` 取值闭集 | 含 `tdc`、`aras` | 加 `ibom` 及新事件用到的取值 |

### 7.2 签署日报规则

- **阶段判定先看状态**：`草稿` → 待提交，`退回` → 退回修改，再走现有的角色列推导（修正实测中草稿单被判成「会签中」「待锁定」、取消单被判成「会签中」）。
- 草稿单的待审批人员为空属正常，不再报 `pendingEmpty`。
- **计数（C5 人次口径）**：来源为 iBOM 的单，应签/已签/未签/签署率由角色列按人次自算；报表计数字段只作参考，不报 `requiredCountDiffer`/`unsignedCountDiffer`。TDC 单保持现状（以字段为准），历史结果不变。
- **来源读取**：快照路径从 `dimensions.sourceSystem` 读（`plugins/sign_daily/service.py::load_source` 目前只取 `values`，需同时带出 `dimensions`）；本地导入路径从 `importMeta.sourceVariant` 读。
- 日变化逻辑不改。按 C1 单据不会跨系统迁移；万一同一单号在基线与今天来源不同，只在异常清单里列出，不改变对比结果。
- 界面在数据时间旁显示「TDC n 张 / iBOM m 张」，有双系统单或冲突单时显示数量并可展开单号。

### 7.3 归属与关注清单

- `services/data_model_attribution.py`：架构平台前缀在 `Ar-` 之外加上 `TRA`（`^tra[-_+ ]`，不区分大小写），`TRA_2.0` 归为架构件、平台代号 `TRA_2.0`（C6）。补测试。
- 关注清单、车型-架构单人工关联：按流水单号匹配，不改。

### 7.4 文案

`TDC 数模`、`会先自动刷新 TDC 数据` 等改为「数模设计审核流程（TDC + iBOM）」，涉及 `plugins/sign_daily/static/report.js`、`plugins/workbench/static/reports.js`、`plugins/system_query/static/modes.js` 等，只改显示文字，不改键名。

---

## 8. 实施阶段与验收

| 阶段 | 内容 | 预计 | 验收 |
|---|---|---|---|
| **1. 鉴权取证与客户端** | 补录 SSO 跳转链（必做，你在内网操作约 5 分钟）；实现 `ibom_client.py`、`ibom_auth.py`；统一登录页加 iBOM | 2 天 | 域账号无人值守跑通「TDC 登录 → iBOM 登录 → 计数 → 导出 → 内存解析」；TDC 登录失败时不向 iBOM 发送密码；认证失败只尝试一次；日志与诊断里不出现 token 和密码（`test_credential_safety.py` 覆盖） |
| **2. 表头变体 + 合并 + 完整性 + 筛选** | §2、§3.4、§4、§5；两个发布者接入，含项目状态侧的形状转换 | 3 天 | 新增与改动的单元测试通过；用 0A 真实报表回放：43 张单 / 167 行全部进入合并结果，项目状态侧 167 行全部 `officialJoin=joined`；模拟一侧失败、fail-closed 筛选键时不发布快照 |
| **3. 下游适配** | §5.4、§7 | 2.5 天 | 签署日报现有测试全部通过（按新规则更新的用例逐条说明）；真实报表生成日报：0 条 `unknownStatus`，草稿/退回/取消阶段正确，iBOM 单计数为人次；同一份 TDC 数据的历史日报结果不变；`TRA_2.0` 归为架构件 |
| **4. 手工导入** | §6 用途 A、B | 1 天 | 上传 iBOM 报表能触发归档并发布；签署日报本地导入识别 iBOM 表头并标注来源 |
| **5. 真机验收** | 内网真实环境 | 0.5 天 + 观察期 | 连续 3 个工作日自动同步成功；每天抽 3 张 iBOM 单与 iBOM 界面核对零件行、签署人和状态；iBOM `totalCount` 与业务确认的在途单总量一致 |

合计约 9 个工作日（不含观察期）；若 Q8 按默认只做定时归档，约 8 个工作日。每阶段结束跑相关测试，全部完成后跑一次全量 `pytest`，输出放 `.runtime/`。

**涉及测试**：`test_tdc_official_rows.py`、`test_scheduled_archive_connectors.py`、`test_scheduled_archive_runner.py`、`test_project_status_connectors.py`、`test_project_status_sync_runner.py`、`test_deliverable_form_analysis.py`、`test_data_model_attribution*`、`test_sign_daily_*`、`test_credential_safety.py`、`test_diagnostic_recording.py`，新增 `test_ibom_client.py`、`test_ibom_auth.py`、`test_data_model_dual_source.py`。打包：新模块由 Web 入口间接导入；签署日报本地版 EXE 只用到已列入 spec 的 `services.tdc_official_rows`，阶段 3 结束时跑 `test_sign_daily_local_report.py` 确认。

---

## 9. 退出 TDC

满足以下两条后，在归档任务配置里关闭 TDC 侧（新增配置项 `sources`，默认两侧都开）：

1. TDC 不再接收新单（连续 N 天 TDC 侧无新流水单号，N 由你定）；
2. TDC 侧在途单全部到达已完成或已废弃。

关闭后合并结果只剩 iBOM，完整性只看 iBOM 一侧，「TDC 登录成功后才登 iBOM」的规则随之取消。历史快照的来源标记保留。

---

## 10. 风险

| 风险 | 对策 |
|---|---|
| 域账号在 iBOM 的可见范围不全（0A 只见 43 张单，单号已编到 1812） | 阶段 5 用 `totalCount` 与业务确认的总量核对；不足时需要 IT 调权限，代码无法弥补 |
| iBOM 报表表头日后变动 | 严格表头校验拒收并标「需关注」，不会静默错位 |
| 一人兼两角色时，iBOM 按人合并签署状态，少算一笔待办 | 已知偏差，记入日报说明；精确校正不在本方案内 |
| 域账号被锁 | TDC 成功后才登 iBOM；认证失败不重试 |
| 双系统单比预期多 | 合并报告和诊断事件显示数量与单号，按 §4 取舍，不丢单 |
| Q5 中用到 fail-closed 的筛选键 | 该任务快照发不出来，「需关注」原因写明键名；按 Q5 结果补实现 |

---

## 11. 不在本方案内

- SOR（D2）、造型 A 面（D4）、EWO / PAA / NCR 迁移。
- 「系统查询 → TDC 数模」页（`/api/tdc/data-model/*` 的查询、全量抓取、导出、合并导出）和 D5 映射发现/稳定性采样（`web/project_status_boot.py`、`web/app.py::_stability_paged_sample`）：**仍只看 TDC**。新建 iBOM 单的 D5 绑定请用流水单号，不依赖映射发现。
- iBOM 接入续期协调器、用审批节点接口逐人校正待办、用接口替代报表取数。

---

## 12. 开工前架构评审（2026-11-19）

对照代码逐条核对初版方案的假设，发现以下问题并已在上文修正：

| # | 级别 | 问题 | 依据 | 修正 |
|---|---|---|---|---|
| R1 | 高 | 项目状态同步用的是**列表接口行**（英文键），官方 47 列只用于按 `(流水单号, 零件号)` 补齐；初版把两个发布者当成同一种行，iBOM 行直接放进去会被当作未对上的官方行丢弃 | `project_status_connectors.py` 数模分支；`_impl.py::_official_join_key`、`_merge_official_columns` | §5.3：iBOM 行一分为二（列表形状 + 官方行），0A 数据验证无重复复合键 |
| R2 | 高 | 单记录绑定只认 `incident` 为权威身份且禁止回退，iBOM 单没有实例号 | `project_status_records.py::authoritative_record_identity` | §5.3：iBOM 单只能聚合绑定（D5 契约本就是 `aggregate: True`）；`incident` 筛选在 iBOM 侧取 0 行 |
| R3 | 高 | TDC 的筛选在服务器端做，iBOM 报表是全量；初版没写 iBOM 侧怎么套用筛选，会导致两侧范围不一致而静默多算 | `TDCDataModelFilters` 与归档过滤白名单 | §3.4：逐键定义本地语义，未取证的键 fail-closed；新增 Q5 |
| R4 | 高 | 域账号登录 iBOM 的跳转方式未取证；统一登录向三个系统发送同一密码，密码错误时加速域账号锁定 | 0A HAR 只含 XHR；`web/host_boot.py` 统一登录 | §3.3：SSO 跳转链改为必做；TDC 成功后才登 iBOM；不重试 |
| R5 | 中 | 签署日报只读快照行的 `values`，读不到来源标记 | `plugins/sign_daily/service.py::load_source` | §5.4、§7.2：写入 `dimensions.sourceSystem`，`load_source` 带出 `dimensions` |
| R6 | 中 | 来源标记如何从连接器行进入快照行没有设计 | `_impl.py` 行规范化只从值计算维度 | §5.4：保留键 `_sourceSystem` → `dimensions` |
| R7 | 中 | 定时归档的 TDC 侧在官方工作簿不可读时会退回列表接口行（英文键），合并时两种键都可能出现 | `TDCArchiveConnector._collect_authenticated` | §4：流水单号与状态两组键都认 |
| R8 | 中 | 诊断记录的取值是闭集，新来源 `ibom` 与新事件取值不登记会被丢弃 | `core/diagnostic_recording.py::_VALUES` | §7.1：登记并补测试 |
| R9 | 中 | 系统查询页和 D5 映射发现直接调用 TDC 客户端，初版写「路由不变、下游零感知」容易被理解为这些页面也会看到 iBOM 单 | `web/crawler_boot.py`、`web/project_status_boot.py` | §11：明确仍只看 TDC |
| R10 | 低 | 初版的「来源切换」日变化特殊处理在 C1 下几乎不会发生，却要改日报基线结构 | `rules.py` 逐单日变化 | §7.2：只在异常清单里列出 |
| R11 | 低 | `TRA_` 架构件规则原本暂缓 | C6 已确认 | §7.3 纳入本期 |

评审后工作量由约 7–8 天调整为约 9 天（不含观察期），增加部分来自 R1、R3、R4。
