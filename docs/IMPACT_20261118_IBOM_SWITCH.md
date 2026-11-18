# iBOM 新系统切换对 VSE Toolbox 的影响评估

> 评估日期：2026-11-18 · 分支 `refactor/ux-v2` · 输入：iBOM《工程领域》操作手册 V1.0、iBOM《数模设计审核流程》操作手册 V1.0（2026-11-07）、`ibom.sgmw.com.cn.har`（2026-11-18 11:48–12:04Z 实网抓包）
> 证据目录：`.runtime/ibom-impact/`（本地、不入库）· 本文只做评估与排期建议，未改任何生产代码
> **修订（2026-11-18，独立评审）**：初稿由 DSH 产出；经独立交叉验证后改正了 D5 粒度、签署口径、签署状态来源、鉴权、PAA 五处判断，并重写了阶段验收。逐条改动与证据见 §10。

---

## 1. 结论（先看这段）

1. **冲击是结构性的，不是换域名。** 旧链路是「TDC（`/uwf`、`/sp` 表单接口）+ Aras（SOAP）」，新链路是「iBOM（Envoy 网关 + JSON `.api` + header token）」。信封、分页、导出、字段命名全部不同，**HTTP 客户端没有可复用的代码**，但**业务语义层可以整体保留**。
2. **D5 数模设计审核流程可以迁，而且数据模型是对得上的；缺的是接口证据，不是数据。** iBOM 里数模审核是变更单类型 `DMM`（由 PDM 推送创建，单号 = PDM `styNumber`，即 `3D-xxxxxxxx`）。列表（`smartQuery`，实测 35 行 / 34 字段）已实测；导出（`exportReport.api`）传输已实测，但列未见（HAR 内 xlsx 损坏）。**明细、零件数模列表、内部签署栏**三页在手册里有完整字段说明，只是抓包时没打开详情页；**签署状态**在设计上不在签署栏里，而在审批流「会签校对」节点的任务上。
3. **粒度风险比初稿判断的小。** 旧 47 列是「单据 × 零件」行（签署日报按流水单号聚合，各行角色列相同，见 `plugins/sign_daily/rules.py:212-214`）；iBOM 是「表头 + 零件数模列表页签 + 签署矩阵」，三者关联即可还原同形状的行。签署矩阵的 18 个部门人员列与 `COUNTERSIGN_COLUMNS` 逐字一致，4 个审批角色列对应 `APPROVAL_COLUMNS`，**部门列 = 该列 26 行人员去重合并**，可机械推导。真正要重写的是：阶段判定（6 个新节点、组长签两次、「待锁定」消失）、加签对应、以及应签/已签/未签/签署率/待审批人员的自算。
4. **SOR 在当前账号的权限与菜单里不存在**（440 个权限点、212 个菜单项、1893 条字典、59 个接口均无）。单账号结论不能外推为「系统没有」，SOR（D2）的归属必须问清。**PAA 存在**：「项目-MBOM-PAA（生产行动授权）」有查询/新增/维护/发布/导出全套权限与菜单。NCR 只作为「费用出处」的取值出现。
5. **鉴权有可行的自动化路径，不是 SSO-only。** HAR 是 Chrome 脱敏导出、只含 XHR，Cookie 与 `Set-Cookie` 被整体剥离，所以「0 Cookie、`usertoken` 唯一凭证」不成立。平台参数显示默认登录方式是 `NORMAL_LOGIN`（普通登录，存在 iBOM 本地账号与独立密码策略），SSO 落地接口是 `/fwPlatform/ssoAuth/login.api`，非活动会话保持 1440 分钟。**无人值守的正路是向 IT 申请 iBOM 本地服务账号**；硬约束是**密码错 3 次锁号且不自动解锁**，任何密码登录只能试一次。

**建议节奏**：不要等切换日再动。阶段 0 先拿到接口与导出原件，并确认 TDC 是否还在接收新单——这决定能不能做「双源比对」。

---

## 2. 新系统是什么（证据）

### 2.1 平台形态（HAR 实测，59 个接口 / 242 次调用 / 单账号）

| 维度 | TDC（现状） | iBOM（新） |
|---|---|---|
| 主机 | `https://tdc.sgmw.com.cn` | `https://ibom.sgmw.com.cn` |
| 风格 | `/uwf/`、`/sp/` 表单查询 | 微服务 `.api`，Envoy 网关 |
| 鉴权 | OIDC 密码流 + Cookie 会话 | 业务请求带 header：`usertoken` + `userloginname` + `logintype=DEFAULT_SSO`；`usertoken` 由 `checkToken.api` 凭**浏览器会话**换取（HAR 为脱敏导出，Cookie 未被记录，见 §10-C5） |
| 登录方式 | `account.sgmw.com.cn` OIDC | 平台参数 `CHOOSE_LOGIN_METHOD=NORMAL_LOGIN`；SSO 落地 `/fwPlatform/ssoAuth/login.api`；会话最长不活动 1440 分钟；密码 3–15 位字母数字；错 3 次锁号、`UNLOCK_INTERVAL=0` |
| 额外要求 | `Referer`、`Accept-Language` | `x-content-md5`（**请求体原文 hex MD5**）、`x-g-trace-id`、`x-g-tenant-id` |
| 成功判定 | `{code,msg,data}`，code ∈ {None,0,200,"0","200"} | `{"state":"success",...}` 字符串；且需看响应头 `x-g-process-result` |
| 分页 | `current`/`size`，元数据 `total`/`pages` | `pageInfo:{beginIndex,pageSize}`（**偏移量**），行容器 `data.content`，默认 50 |
| 导出 | 同步 GET 返回 XLSX 字节 | 同步 POST 返回文件流（`application/x-download` + `Content-Disposition`），**无 taskId / 无轮询**，实测 8 ms |
| 错误样本 | 有业务错误码 | **仅 1 例**（`checkToken` 空 body + `x-g-process-result:error`） |

已知例外形状（迁移时必须特判）：`ewoPartInfo` 返回**裸数组**无分页信封；`changeLogRecord.content` 是 **HTML 串**；`approvalLevelDetail` 是**内嵌 JSON 字符串**；`extension` 可能是 `[]`。

### 2.2 模块覆盖（两本手册 + 抓包 + 权限/菜单树）

| iBOM 模块 | 手册 | 抓包 | 对位旧系统 |
|---|---|---|---|
| 工程BOM / EBOM（原 EPL） | 第1、2篇 | 部分（`eBom/findProductList`、`productNode`） | 无直接对位（新能力） |
| ECR / EWO / EEA | 第3、4、5篇 | **EWO 全链路 12 个接口实测** | Aras EWO（111 列） |
| 数模设计审核流程 `DMM`（菜单「发布管理 → 数模设计审核流程」，权限「零件3D数模发布：查询/维护/导出报表」） | 独立手册 | 列表 ✅ / 导出传输 ✅（列未见） / 详情页未打开 | **TDC 数模（D5，47 列）** |
| 造型 A 面 `ASUF` | — | 列表骨架（4 次调用全 0 行） | TDC A 面（D4，本来无契约） |
| **PAA（生产行动授权）** | — | 未调用；**权限与菜单均存在**（MBOM 模块） | Aras PAA |
| SOR | — | 当前账号权限/菜单/字典/接口均无 | TDC SOR（D2，15 列） |
| NCR | — | 仅作 EWO「费用出处」取值 | Aras NCR |

> 手册正文 0 个 URL、0 个接口路径；`TDC`/`Aras`/`PLM` 全篇未出现，`PDM` 在《工程领域》仅以 `IPDM` 出现 1 次；《数模设计审核流程》明确「数据全部由外部 PDM 系统推送创建」。"哪些旧系统会被下线"只能靠人确认。

---

## 3. D5 数模设计审核流程：逐列映射与缺口

### 3.1 已确认可映射

**DMM 列表直接给出（约 11 列）：**

| 旧列（`core/report_headers.json` `tdc_data_model`） | iBOM 来源 | 判定 |
|---|---|---|
| 流水单号 | `changeCode`（`3D-xxxxxxxx`，= PDM `styNumber`） | ✅ |
| 发布属性 | `changeType`（T1发布 / T2发布 / 铸造数据，字典 `PART_MODEL_PUBLISH_TYPE`） | ✅ 语义等价 |
| 申请人 | `createdByDisplayName` / `employeeIdDisplayName` | ✅ 需确认口径（创建人 vs 申请人） |
| 部门 | `departmentName` / `departmentIdDisplayName` | ✅ |
| 申请日期 | `createDate`（PDM 推送时间）或 `submitDate`（发起审批时间） | ⚠ 口径二选一，需与旧报表对齐 |
| 项目/车型 | `projectName` | ⚠ 实测样本为 `E262S`/`F620S`/`CF810P`，现行归属规则不会误判；架构单是否仍带 `Ar-` 前缀未见样本 |
| 设计工程师 | `designEngineerId(DisplayName)` | ✅ 仅人名，无签署状态 |
| 主任工程师 | `applicantLeaderId`（**新称"申请人组长"**） | ⚠ 名称变了，且新流程里签两次 |
| 专家/经理 | `expertManagerId` | ✅ 仅人名 |
| 首席/总监 | `chiefDirectorId` | ✅ 仅人名 |
| 状态 | `changeStatus`（码表 `APP_FORM_STATUS`：DRAFT/APPROVAL/RETURNED/PUBLISH/CANCEL） | ✅ 但旧数字码 `2/4` 闭集要重写 |

**依赖审批流接口（对 DMM 未验证）：** 最新审批记录、待审批人员。
**无对应：** 实例号（`relationProcId` 是 PDM 侧流程 ID，不是 TDC 实例号）、流程名（只有一种，可取固定值）。

### 3.2 四个缺口与替代路径

| 缺口 | 影响列 | 手册 | 替代路径（按把握从高到低） |
|---|---|---|---|
| **明细** | 表头补充字段 | §3 顶部卡片：单号、状态、主题、类型、项目、申请人 | ① 通用 `/bommgmt/change/findById.api`（DMM 与 ECO/ECR 共用多态 `change/smartQuery`；DMM 权限点只有查询/维护/导出报表，无独立"详情"权限）② 命名推定的 `partDigitalModelChange/*` |
| **零件数模列表** | 零件号、数模号、零件名称、数量、重量（单件）、零件合计、版本号、对应IA号、EWO/SOR号（9 列） | §5.2 共 12 字段：零件编号、SGMW零件编号、模型编号、零件名称、数量、单件重量、版本号、零件总重、IA编号、图纸编号、EWOSOR编号、备注 | ① `changeOperation/loadEntity` + `businessType:"partDesign"`（`isExistCount` 证明存在 `partDesign`；字典 `PARTDESIGN_PARAMETER` 含数模号/数模版本/数模状态）② DMM 报表导出 ③ 打开详情页抓接口 |
| **内部签署栏** | 18 个部门列 + 4 个审批角色列 | §6：26 行内容项 × 人员列；人员列 = 设计工程师、申请人组长确认、专家/经理、首席/总监 + 18 部门（与 `COUNTERSIGN_COLUMNS` 逐字一致） | ① 打开详情页抓接口 ② DMM 报表导出（35 行 91,039 B，每行体积约为 EWO 导出的 10 倍，很可能带明细或签署栏） |
| **签署状态** | 应签/已签/未签人数、签署率、待审批人员 | §6.3、§7：签署栏**只存人、不存状态**；「会签校对」节点审批人 = 签署栏全部人员去重 | 先 `recordType/getId` 取 DMM 的 `recTypeId`，再 `findProcessesByResourcesUri {recId, recTypeId}` 取 **iBOM 自己的**流程 ID → `findAllTasks` / `approvalNodes {changeId}`。**不要用 `relationProcId`**（14 位、PDM 侧 ID；iBOM 流程 ID 为 32 位十六进制）。EWO 样本显示：已完成的多人节点拆成每人一个 `FINISHED` 任务，进行中的多人节点是一个 `PENDING` 任务挂多个 `owners`（实测 17 人）。若 `PENDING` 的 owners 即未签人，则「已签 = FINISHED 任务、未签 = PENDING owners」正好满足签署日报 |
| **导出报表的列与粒度** | 全部 | — | `exportReport.api` 传输已实测；**HAR 内 xlsx 二进制被文本化损坏、不可恢复**，必须浏览器直接另存 |

### 3.3 口径差异（修订后）

1. **粒度：** 不是硬差异。旧 = 单据 × 零件；新 = 表头 + 零件数模列表，关联后同形状。前提是零件数模列表接口可取（§3.2）。
2. **签署矩阵：** 部门列名不变，部门列 = 矩阵该列 26 行人员去重合并；签署日报「按人合并」「人次按单元格计」的规则可沿用。**仍需在阶段 0 核准列数**：手册 §6.2 文字写「21 个人员列」，但列出了 22 个名字；新契约若做逐字门禁，必须以界面为准。
3. **审批节点：** 新的 6 节点为「申请人组长审核 → 会签校对 → 设计工程师 → 申请人组长审核（二次）→ 专家或经理 → 首席或总监」，审批通过后**自动发布**。签署日报的阶段判定 T1–T6（`plugins/sign_daily/rules.py` `stage`）要按新节点重写：组长出现两次、原「待锁定」阶段消失。
4. **加签：** 手册无加签概念；EWO 样本里只见过 `approveAction` 为「转派」。阶段 0 要确认它对应什么，再决定 `加签人员` 列与 `KIND_ADD_SIGN` 的处理。

---

## 4. 其它交付物的影响

| 交付物 | 现状 | 新系统 | 影响 |
|---|---|---|---|
| **D2 SOR（15 列）** | TDC `/sp/sor/sorPage` + `/sp/sor/export`，列表覆盖 15/15 列 | 当前账号**无任何痕迹** | 🔴 **P0 未知**：要么留在 TDC，要么在当前账号无权的模块里，要么迁到别的系统。必须业务确认 |
| **D4 A 面** | 只有 1 个 page path + 契约阻断文案，**从未实现** | `ASUF` 列表存在但 0 行；字典有 16 项签署栏 + 4 种发布类型 | 🟡 无迁移成本，但别把"新系统有菜单"当成"有契约" |
| **D3 EWO** | Aras SOAP；111 列，其中 60 列只能靠官方工作簿 | EWO（`ECO`）全链路实测可做 | 🟠 取决于 Aras 是否同期下线；若下线，111 列契约要按 iBOM 模型重建 |
| **PAA** | Aras | **iBOM MBOM 模块存在**（查询/新增/维护/发布/导出） | 🟠 有迁移路径，需抓包取证 |
| **NCR** | Aras | 无（仅费用出处取值） | 🟡 取决于 Aras 是否保留 |
| **3D 单签署日报** | 两条源：TDC 快照 / 本地导入官方 47 列 xlsx（`REQUIRED_COLUMNS` 逐字） | 需投影到 47 列形状或新契约 | 🔴 D5 最主要的下游：阶段判定重写 + 计数自算 + 加签对应。**切换日基线**：日变化按流水单号对比基线，切换当天基线来自 TDC、当天数据来自 iBOM，算出的变化无意义，必须在切源时重置基线 |
| **项目状态同步 / 定时归档** | `TDCProjectStatusConnector`、`TDCArchiveConnector` | 需新连接器 | 🟠 连接器契约（过滤器白名单是闭集）要新增一套；无人值守依赖服务账号 |
| **映射取证（VPI-T2-D2/D5）** | 直连 TDC 采样 | — | 🟠 证据链要重新采 |

---

## 5. 代码影响面（可复用 vs 必须替换）

### 5.1 三个替换点

| 替换点 | 文件 | 说明 |
|---|---|---|
| ① HTTP 客户端 | `services/tdc_crawler.py`（1823 行） | 信封/分页/导出/去重全部是 TDC 形状，需新建 `services/ibom_client.py` |
| ② 认证 | `services/tdc_auth.py`（895 行，OIDC 密码流） | 新建 iBOM 认证：服务账号 NORMAL_LOGIN，或统一身份经 `ssoAuth/login.api` → `checkToken`；**登录失败不得重试**（3 次锁号、不自动解锁），复用续期协调器前须核实其重试行为 |
| ③ 连接器 | `services/scheduled_archive_connectors.py:332-526`、`services/project_status_connectors.py:568-960` | 过滤器白名单 + 同步链 |

> 边界口径：**只换**上述 3 处 + 前端 2 处硬编码主机；**不动**契约层（`report_headers.json` / `report_contracts.py`）、`services/pagination_integrity.py`、归档注册表、诊断白名单、`services/xlsx_preview.py`。
> 波及面：`/api/tdc/*` 共 **11 条路由**（其中 3 条 a-face 恒 400）、**26 个测试文件**（11 个 `test_tdc_*.py` + 15 个间接导入者）、4 个 `.spec` 打包入口。

### 5.2 可以原样保留

- `core/report_headers.json` 的 **47 列契约**：作为内部规范契约，新系统数据**投影**到它上面。投影行必须带来源标记（`tdc` / `ibom`），iBOM 自算的计数列（应签/已签/未签/签署率）要可追溯为派生值。
- `services/tdc_official_rows.py` 的**表头逐字门禁**：只用于 TDC 官方工作簿与本地导入。**不要假设** iBOM 报表能出 47 列同序工作簿，在看到报表表头之前不把它列为复用前提。
- `services/tdc_text_rows.py`（TXT 导入）、`services/tdc_export_cache.py`（导出缓存）、`services/pagination_integrity.py`（`decide_page_outcome`/`is_complete`）、`services/data_model_attribution.py`、`services/data_model_vehicle_links.py`、`services/data_model_watchlist.py`（纯本地语义）。
- `services/tdc_contract_probe.py` **纯函数层 0 改动**（只吃 `rows`），CLI 适配器约 40 行即可改造成 iBOM 契约探针。

### 5.3 写死假设（换系统后会静默出错的地方）

| # | 假设 | 位置 | 后果 |
|---|---|---|---|
| R1 | 主机硬编码 | `services/tdc_crawler.py:38`、`web/crawler_boot.py:102`、`plugins/system_query/static/modes.js:10`、`plugins/project_overview/static/deliverable/policy-logic.js:10` | 后端 2 处 + 前端 2 处，漏改前端 UI 仍指旧系统 |
| R7 | **47 列顺序即语义** | `core/report_headers.json:727`、`core/report_contracts.py:132-153`、`services/tdc_official_rows.py:66-128` | 列序变化 = 门禁拒绝 + 全链路错位（最高风险） |
| R8 | 状态码 `2=审批中/4=已完成` | `core/report_contracts.py:273-276`、`services/project_status_connectors.py:417` | 新系统是 `APP_FORM_STATUS` 文本枚举，闭集要重写；`CANCEL` → 已废弃剔除、`RETURNED` 为新增在途态 |
| R13 | 架构件 = `^ar[-_+ ]` 前缀；车型 = `F\d{3}S` | `services/data_model_attribution.py:43-47` | 实测 `E262S`/`CF810P` 会按原值归为项目件，不会误判；架构单前缀未见样本，待验 |
| R10 | 流水单号**不是查询参数**，只能全量抓 + 本地匹配 | `services/data_model_watchlist.py:207-234`、`web/crawler_boot.py:2173-2204` | iBOM 手册列表搜索支持「变更单号模糊」；可用模糊查询收窄后再本地精确匹配，**去掉全量抓取这条最贵的重路径**（DMM 的单号过滤字段名待阶段 0 抓取） |
| R14 | 去重身份键 `incident→documentNo→formId→…` | `services/tdc_crawler.py:1710-1779` | 新主键为 `id` / `changeCode`，需改身份键，否则去重退化为内容哈希 |

> 完整 17 条见 `.runtime/ibom-impact/TDC_SURFACE.md` §6。

---

## 6. 影响分级

| 级别 | 内容 | 判据 |
|---|---|---|
| 🔴 **P0 阻断** | ① 无人值守鉴权路线（服务账号 / 统一身份 / 半自动）；② SOR 去向；③ DMM 零件数模列表与签署栏的**接口**；④ 会签节点能否取到逐人签署状态；⑤ TDC 是否仍接收新单（决定能否双源比对） | 任一条不成立，对应交付物无法按计划迁移 |
| 🟠 **P1 必须改造** | 新 HTTP 客户端 + 新认证 + D5 投影层 + 连接器白名单 + 签署日报阶段判定与计数 + 切源基线重置 + 前端主机/文案 | 工作量集中在此 |
| 🟡 **P2 观察** | A 面契约、Aras EWO/PAA/NCR 去留 | 取决于"哪些旧系统下线" |
| ⚪ **P3 无需动** | 47 列契约文件、official_rows 门禁（仅限 TDC 工作簿）、TXT 导入、导出缓存、分页完整性、本地语义模块、Excel Worker、诊断与打包 | 契约不变即不变 |

---

## 7. 迭代计划（修订）

### 阶段 0A · 技术取证（1 天，**最高优先级**）

1. 打开 3 张 DMM 详情页抓 HAR（Fetch/XHR + Preserve log）：分别取**草稿、审批中（会签进行到一半）、已发布**。覆盖顶部卡片、零件数模列表、内部签署栏、审批流程 Tab。
2. 浏览器**直接另存** `数模设计审核流程报表_YYYYMMDD.xlsx`（不经 HAR 文本通道）。
3. 录一次 SSO 跳转链（只记主机和路径）：打开 iBOM 前清会话，在「全部类型 + Preserve log」下抓到 `ssoAuth/login.api` 为止。
4. 用两个不同角色的账号查 DMM 的 `totalCount`（当前账号可见 35 行，单号已编到 1805，可见范围很可能被裁剪）。
5. 拿 iBOM 的 `3D-` 单号到本地最新 `tdc_data_model` 快照里查交集：同一张 3D 单在两系统是否同号、TDC 是否仍在接收新单。
6. 顺手取 A 面（`ASUF`）、PAA、任一有数据的 EWO 详情。

**验收（逐项交付物，不是"能回答问题"）**：
- 4 个缺口各给出接口路径 + 请求/响应形状 + 3 种状态的样本（落 `.runtime/ibom-impact/phase0/`）；
- DMM 报表 xlsx 原件及其表头清单；
- 签署矩阵实际列数（以界面为准）；
- 会签节点「已签 = FINISHED、未签 = PENDING owners」成立或不成立的结论；
- SSO 跳转链；两账号 `totalCount` 对比；单号交集结果。

### 阶段 0B · 组织确认（并行，不设工期）

向 IT/业务确认：SOR 去向、Aras（EWO/PAA/NCR）是否同期下线、**iBOM 本地服务账号**、切换日期与并行期、旧系统数据保留期。

### 阶段 1 · 只读适配层（3–5 天）

- 新增 `services/ibom_client.py`：信封（`state` + `x-g-process-result`）、偏移分页（接 `pagination_integrity`）、`x-content-md5`、文件流导出、`usertoken` 注入；**不触碰 TDC 路径**。
- 新增 iBOM 契约探针：改造 `tdc_contract_probe` 纯函数 + 约 40 行适配器。
- 会话获取做成可插拔的 token provider。手工提供 token 只作过渡，经现有凭据存储，不落日志。

**验收**：
- `DISCRIMINATOR=DMM` 全量列表行数 = iBOM 界面计数，与界面导出逐条对账一致；
- 分页 `stop_reason` 为完整；空 body / `x-g-process-result:error` 必须失败而不是当成功；
- **鉴权路线定案**（服务账号 / 统一身份 / 半自动三选一，写入 `memory/DECISIONS.md`），作为进入阶段 2 的门槛；服务账号路线需演示一次无人值守登录且失败不重试。

### 阶段 2 · D5 投影与比对（5–8 天）

- 新增 `services/ibom_data_model_rows.py`：表头 + 零件数模列表 + 签署矩阵 + 会签任务 → **47 列契约**投影；缺列显式留空并记录，绝不借相邻列；行带来源标记。
- 若阶段 0A 第 5 项证明两系统有同号单：同单 TDC vs iBOM 逐列比对，产出差异清单。
- 若无交集：改为 N 张真实单据与 iBOM 界面（签署矩阵 + 审批流）**逐格比对**。

**验收**：差异清单（或逐格比对记录）评审通过；应签/已签/未签/签署率的计算规则写成测试并通过。

### 阶段 3 · 签署日报适配（4–6 天）

- 阶段判定 T1–T6 按 6 个新节点重写（组长两次、无「待锁定」）；加签按阶段 0A 结论处理；状态闭集换为 `APP_FORM_STATUS`。
- 切源基线规则：数据源从 `tdc` 换到 `ibom` 的当天重置基线，不跨源计算日变化。

**验收**：签署日报现有测试在新规则下更新后全部通过；用阶段 2 的比对单据生成日报，阶段、欠账、签署率与界面一致；切源当天不产生虚假日变化。

### 阶段 4 · 开关切换（3 天）

- 数据源配置 `source: tdc | ibom`，D5 先切；路由签名不变（`/api/tdc/*` 保持，内部换下游）。
- 回滚：只有 TDC 仍在接收新单时，回滚才是「切回实时源」；否则回滚只回到 TDC 只读历史，需在切换公告里写明。

**验收**：同一窗口产出的报表可逐行追溯来源；回滚演练通过（按上述两种情形之一）。

### 阶段 5 · 跟随面（3–5 天）

定时归档、项目状态同步、映射取证逐个指向新连接器；过滤器白名单同步扩容（未知键仍 fail-closed）。

### 阶段 6 · 另一条线（按 0B 确认结果）

- SOR：若留在 TDC → 保持现状；若迁移 → 需新契约。
- Aras EWO/PAA/NCR：**单独立项**。EWO 111 列在 iBOM ECO 模型下不成立（模板推导/成本分析/打点/影响范围布尔矩阵都是新概念）；PAA 在 iBOM MBOM 有对应模块，先抓包取证。

---

## 8. 需要你确认的问题

1. **切换范围**：只换 TDC，还是 Aras（EWO/PAA/NCR）也同期下线？
2. **SOR 去哪**：当前账号看不到 SOR，是保留在 TDC、在其他权限下的 iBOM 模块、迁到别的系统，还是业务上取消？
3. **服务账号**：IT 能否提供 iBOM **本地服务账号**（走 `NORMAL_LOGIN`）？不能的话，统一身份自动登录是否允许，或接受每天交互登录一次的半自动？
4. **切换日期与并行期**：PDM 在并行期是否同时推送 TDC 与 iBOM？旧系统数据保留多久？
5. **签署日报的阶段口径**：组长两次审核在日报里如何展示（合并为一个阶段还是拆两个）？原「待锁定」阶段删除是否可接受？
6. **`projectName` 值形态**：架构单是否仍带 `Ar-` 前缀？
7. **权限裁剪**：本次抓包是单账号（架构工程师/架构项目管理工程师/PE/EBOM/MBOM）。正式接入用哪个账号，可见范围是否覆盖全部 DMM？

---

## 9. 证据索引

| 文件 | 内容 |
|---|---|
| `.runtime/ibom-impact/HAR_CONTRACT.md` | 59 个接口的契约提取（信封/鉴权/分页/导出/审批流/DMM 缺口） |
| `.runtime/ibom-impact/TDC_SURFACE.md` | 现有 TDC/Aras 依赖面（接口清单、47/15 列契约、调用方地图、17 条写死假设） |
| `.runtime/ibom-impact/ENG_MANUAL_NOTES.md` + `ENG_FIELDS.csv` | 工程领域手册逐章笔记（189 条字段/规则） |
| `.runtime/ibom-impact/small_manual.txt` | 数模设计审核流程手册正文（全文） |
| `.runtime/ibom-impact/har/` | 16 份抓包证据（逐接口 dump、字段索引、字典、路由时序） |
| `.runtime/ibom-impact/exports/` | 3 个导出响应体（**已损坏，仅作"不可用"的证据**） |

> 证据只放 `.runtime/`，不入库：原始 HAR 含有效 `usertoken`；`fwPlatform/parameter/findAll.api` 的响应含集成配置值。按项目规则，凭据与参数值不进 Git，本文只写字段名。

---

## 10. 独立评审勘误（2026-11-18）

初稿结论与修订对照。核对方式：读 `.runtime/ibom-impact/` 下的衍生证据与两本手册正文；对原始 HAR 只做 5 项定点结构核对（Cookie 结构、117 个平台参数的名称与描述、权限与菜单树、审批任务粒度、SOR/PAA 是否存在），未输出任何令牌或头部值。

| # | 初稿判断 | 修订 | 证据 |
|---|---|---|---|
| C1 | 旧 = 零件级、新 = 单据级，「最大口径风险」 | 新系统有零件数模列表页签，关联后可还原同形状行；风险降为「接口未抓到」 | 《数模设计审核流程》§5.2 的 12 个字段；`plugins/sign_daily/rules.py:212-214` |
| C2 | 签署矩阵 26×21，应签/已签分子分母必须重新定义 | 18 个部门列与 `COUNTERSIGN_COLUMNS` 逐字一致，部门列 = 该列人员去重合并；重写范围收窄到阶段判定、加签与计数自算 | 手册 §6.2、§6.3 注、§7；`rules.py` `COUNTERSIGN_COLUMNS` / `APPROVAL_COLUMNS` |
| C3 | 签署状态「需签署栏单元格级状态，`approvalNodes` 只能给节点级」 | 签署栏设计上不存状态；状态在「会签校对」节点，按人去重即可。多人节点：完成者拆为逐人 FINISHED 任务，进行中为单个 PENDING 任务挂多 owners | 手册 §6.3 注、§7；HAR `approvalNodes`（`FINISHED` 同名步骤 ×2、`PENDING` 任务 owners=17） |
| C4 | 明细候选为命名推定接口 | 首选通用 `change/findById`；签署状态走 iBOM 自己的流程 ID，不用 `relationProcId` | DMM 走多态 `change/smartQuery`；权限点「零件3D数模发布：查询/维护/导出报表」；`relationProcId` 14 位 vs iBOM 流程 ID 32 位十六进制；手册 §9 单号 = PDM `styNumber` |
| C5 | 「纯 header，242 条 0 Cookie，`usertoken` 唯一凭证」 | HAR 为 Chrome 脱敏导出、仅 XHR，Cookie 与 `Set-Cookie` 均被剥离；首个成功 `checkToken` 未带 `usertoken` 仍换到 token，说明会话凭证未被记录 | HAR：creator WebInspector、`_resourceType` 全为 xhr、`request.cookies`/`response.cookies` 全空；#2 失败后 #3 重新出现 `getPlatformAggregateInfo`（页面跳转未记录） |
| C6 | 「没有出现密码登录端点」→ 可能只能半自动 | 默认登录方式 `NORMAL_LOGIN`，存在本地账号与密码策略；无人值守正路是 iBOM 本地服务账号；错 3 次锁号且不自动解锁 | 平台参数 `CHOOSE_LOGIN_METHOD`、`SSO_CHECK_URL`、`USER_SESSION_MAX_INACTIVE=1440`、`USER_PASSWORD_REGEX`、`USER_PASSWORD_LOCK_NUMBER=3`、`USER_PASSWORD_UNLOCK_INTERVAL=0` |
| C7 | PAA / NCR「完全没有」 | PAA 在 MBOM 模块存在（查询/新增/维护/发布/导出）；NCR 仅为费用出处取值 | HAR `findUserAggregateInfo.functions`、`aclResource/findTreeByType` 菜单 |
| C8 | SOR「在新系统里完全不存在」 | 收窄为「当前账号权限/菜单/字典/接口均无」 | 同上；单账号证据 |
| C9 | 「约 20/47 列已确认可映射」 | 列表直接给出约 11 列；最新审批记录、待审批人员依赖审批流接口，对 DMM 未验证 | §3.1 表格实为 13 行，「20/47」与 TDC 列表接口覆盖率混同 |
| C10 | 47 列同序工作簿可直接复用 `tdc_official_rows` | 未见 iBOM 报表表头前，不把它列为复用前提 | 报表 xlsx 已损坏，列未见 |
| C11 | 阶段 0 用 0.5–1 天，验收「能回答 P0 的 4 个问题」 | 拆为 0A 技术取证（1 天，逐项交付物验收）与 0B 组织确认（并行）；补充单号交集、两账号可见范围、SSO 跳转链 | §7 |
| C12 | 阶段 1 验收「字段画像与 HAR 结论一致」 | 改为与界面计数/界面导出对账，并以鉴权路线定案为进入阶段 2 的门槛 | §7 |
| C13 | 阶段 2「同窗口 TDC vs iBOM 逐列比对」 | 前提是两系统有同号单；无交集时改为与 iBOM 界面逐格比对 | 实测 DMM 单均为当天由 PDM 推送创建 |
| C14 | 签署日报放在跟随面 3–5 天 | 单列阶段 3：阶段判定重写、加签、计数自算、**切源当天基线重置** | `rules.py` `stage` 与逐单日变化按流水单号对齐 |
