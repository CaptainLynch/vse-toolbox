# 数模（TDC data_model）同步向导「映射发现未匹配」根因与优化方案

- 版本：第三版（2026-10-10，第二版结论经用户批准后**已实施并通过顾问实施后复核**）
- 现象来源：生产截图 ×3 + 安全诊断包 `c3d24bbaf7a7471691152991f16a7e8c`
  （frozen build `a26d4e1e…77fc` = `20261009c-single-exe-excel-worker`）
- 任务标识：`TASK-20261010-TDC-DM-WIZARD-SERIAL` / 复核 `TASK-20261010-TDC-DM-IDENTITY-FIX-REVIEW`
- 状态：代码已改完（未提交、未打包），聚焦 + 全量回归见 §7

## 1. 结论摘要（修正）

两次失败是**两个不同机制**，不能混为一谈：

| 尝试 | 输入 | 报错 | 机制 |
| --- | --- | --- | --- |
| ① 12:23 | 车型 `ar-n`；流水单号 `3D-…018 3D-…012`（双值，23 字符） | 命中行数 0，**字段数 0** | 单值字段收到多值整串 → 本地精确匹配 0 行 → `observe()` 收到空行集 |
| ② 12:39 | 车型 `AR-N`；流水单号 `3D-…018`（**单值**） | 命中行数 0，**字段数 60** | 单号**命中了行**，但候选被 `selected` 过滤空 |

**关键推理**：`fieldReport.fields` 取自行键并集（`services/project_status_discovery.py:445-446`），
所以「字段数 60」证明 `observe()` 收到的行集**非空**；而候选数为 0 只能是 `selected` 过滤把行丢掉了。

**机制（已核实）**：同一行的身份被两处独立推导——

- `web/app.py:5099-5112`：本地匹配后 `effective_selected = serial_match["matched_instances"][0]`，
  即命中行的 **`incident`**（实例号）；
- `observe()` 的候选过滤 `key == selected` 用的是 **`record_identity(row)`**
  （`services/project_status_records.py:92-100`，顺序 `_no, formId, incident, documentNo, …`）。

命中行只要含 `_no` 或 **`formId`**，身份就 ≠ `incident` → 候选被全部丢弃 →
`state=not_found`、`candidateCount=0`；而 `fieldReport` 仍取 `safe_rows`（命中行）→ **字段数 = 行键数 = 60**。
这与生产签名逐字一致（见 §2.3 复现）。

**触发源**：上游列表行新增/开始返回身份字段（最可能 `formId`）。
本仓代码**不会**写入 `formId`——爬虫返回的是上游原始记录（`services/tdc_crawler.py:657`），
`git log -S formId` 也无近期新增，因此新字段来自上游，与「最新分支更改数模审批流程内容」一致。
字段名待字段报告确认（§5-1）。

**影响面（第一版漏掉）**：

1. 运行期连接器单记录绑定的 externalKey 同样是 `record_identity`
   （`services/project_status_connectors.py:177` → `_record_identity` = `record_identity`），
   而 `services/project_status_updates.py:637` 要求「候选键 == 绑定键」。
   → **存量按 `incident` 落库的单记录绑定会开始 `external_key_mismatch` / `needs_attention`**，
   不只是向导建不了绑定。
2. 潜在崩溃（已复现）：`web/app.py:5111` 的 `serial_match["matched_instances"][0]`
   在「命中行有单号但缺 `incident`」时抛 IndexError → 500。本次生产现象不是它（否则会报 500），
   但它真实可达，必须一并 fail-closed。

## 2. 证据链

### 2.1 生产诊断包（尝试①）

- `POST api_project_status_mapping_discovery` → 202（异步，177ms），无异常。
- `inputs.filters`：`project_model`（4 字符）+ 一个指纹化键（`document_no` 不在
  `core/diagnostic_recording.py:44` 键白名单内）值长度 **23**；`aggregate=false`。
- 截图放大逐字核对：流水单号框为两个单号 + 一个空格（总长 23）。
- 诊断包**没有爬虫跨度**，故「全量扫描行数」缺失。

### 2.2 两次报错的判别价值

`字段数` 是唯一区分「收窄到 0 行」与「命中但身份不一致」的现成信号，但向导没有渲染
`serialMatch`，用户只看到「请核对车型与筛选条件」。

### 2.3 本地复现（API 级假爬虫，60 键行）

归档 `.runtime/repro_wizard_identity_mismatch.py`（5 例 4 passed / 1 暴露崩溃）：

| 夹具 | 结果 |
| --- | --- |
| `{incident, documentNo}` | `matched`，`externalKey=incident`（对照） |
| `{formId, incident, documentNo}` | **`not_found`、`candidateCount=0`、`fields=60`、`serialMatch.matched=1`**（= 生产签名） |
| 只有中文键「流水单号」 | `web/app.py:5111` **IndexError → 500**（真实缺陷，非本次现象） |
| aggregate + 无身份键 | `not_found`、`fields=60` |
| aggregate + `{incident, documentNo}` | `matched`、`candidateCount=1` |

另：第一轮的多值复现归档 `.runtime/repro_wizard_multivalue_serial.py`（2 passed）。

### 2.4 代码坐标

- `web/app.py:1390-1399`：tdc/data_model 只做「流水单号与实例号二选一」；`document_no`
  从上游参数 pop 掉（TDC 无该查询参数），原样写入 `rule["documentNo"]`。
- `web/app.py:5099-5112`：`match_serial(rows, document_no)`；`effective_selected` 取 incident；
  `matched_instances[0]` 越界点。
- `services/project_status_records.py:30-34, 92-100`：`IDENTITY_FIELDS` 与 `record_identity`。
- `services/tdc_crawler.py:1715-1722`：爬虫去重按 `("incident","documentNo","formId",…)`，**incident 优先**
  ——与 `record_identity` 的 formId 优先**本就不一致**。
- `services/project_status_connectors.py:177`：单记录 externalKey = `record_identity`。
- `services/project_status_updates.py:637-656`：候选键 ≠ 绑定键 → `external_key_mismatch` / needs_attention。
- `services/project_status_discovery.py:172-193, 445-446`：候选过滤与字段报告来源。
- `services/tdc_contract_probe.py:32, 658`：`CANDIDATE_KEY_FIELDS = ("formId","incident","documentNo")`，
  且仓库自己把「哪个才是权威 external key」列为未决问题。

## 3. 顾问咨询与裁决

| run | 场景 | 结论 | 裁决 |
| --- | --- | --- | --- |
| `9bdeac08…`（第一轮） | 多值输入 / 诊断集 / 漂移检测 | 1=A 单值 fail-closed；2=诊断集+不做自动探测；3=共用纯函数 | 1/2/3 = adopted |
| `3b2e9629-866f-4c76-8b25-cb45acf4814f`（增量，`--follows`） | 身份口径 / 越界 fail-closed / D1 优先级 | 1=有条件（TDC externalKey 以 `incident` 为准，同函数不变量）；2=可定案（原因码 + observe 不变量）；3=可定案（D1 降 P1、独立提交） | 1/2/3 = adopted（顺序表启用以待取证为闸门） |

顾问被本地证据**修正/确认**的点：

- 确认：真正的缺陷是「同一行身份被两处独立推导」，修复不变量 = selected 与过滤键出自同一函数、同一行。
- 确认（本仓核实）：`formId` 不是本仓爬虫新增的归一化字段（行键 = 上游原始记录），
  故污染窗口从上游变更起算。
- 修正：F10 稳定性载荷是显式保留键，结果级新增诊断键安全（但不得进 `fieldReport.fields`）。
- 修正：含分隔符的多值串在发现阶段恒 0 命中，过不了稳定性门禁（第一版顾问的 F10 顾虑不成立）。

## 4. 优化方案

### P0（本批，身份一致 + fail-closed + 诊断）

1. **身份口径统一（结构性，最小可回滚）**
   - `record_identity` 增加可选「源/顺序」参数，**默认值 = 现有 `IDENTITY_FIELDS`**，
     未传源的调用点行为逐字不变；新增 TDC 顺序：仅把 `incident` 提到首位，其余相对顺序不动。
   - **同一提交**内改三处调用点：`web/app.py:5099-5112`（`effective_selected` 用同一函数取命中行身份）、
     `observe()` 的候选过滤、`project_status_connectors.py:177`（分开提交会让新绑定首轮运行就漂移）。
   - 实施前列出 `record_identity(` / `IDENTITY_FIELDS` 全部引用并标注 TDC / ARAS / 通用；
     服务 TDC 行的通用调用点必须传源。
   - **不改**爬虫去重顺序，只加契约测试：TDC 身份顺序首位 == 去重元组首位。
   - 运行期护栏：计算键 ≠ 存量键，但存量键等于同一行另一身份字段的值时，判为「身份字段位移」——
     不覆盖存量键、只告警；真正换记录才走 `key_changed`。
   - 存量**不自动迁移**；审计出 formId 形态的键后出人工清单再决定是否回写。
2. **越界与身份缺失 fail-closed**（阶段顺序：输入校验 → 本地单号匹配 → 身份解析 → `observe()`）

   | 情形 | 结果 |
   | --- | --- |
   | `matched == 0` | `not_found`（原因码 `serial_no_match`） |
   | 命中 ≥1 且全部无身份 | `identity_missing` |
   | 不同身份数 > 1 | `identity_ambiguous`（**不取 `[0]`**） |
   | 唯一身份 | 作为 selected 继续 |

   - 禁止「`selected=None` 继续走过滤」（否则无身份行会被当成匹配）。
   - `observe()` 加不变量：selected 非空、行集非空、候选为 0 → `selected_not_in_candidates`
     （修复后不可达，保留作回归哨兵，不抛 500）。
   - 载体：`state` 沿用现有枚举，新增 `reason` 字段 + 文案（确认 `state` 仅被向导消费后再考虑独立 state）。
3. **诊断披露**：结果级新增键（不进 `fieldReport.fields`、不进签名/稳定性载荷），只给字段名与计数：
   命中行存在哪些身份字段、实际采用哪个、`serialMatch.matched/scanned`、候选数。向导渲染这些事实。

### P1（同批发布、独立提交）

- 上一轮 D1：向导「流水单号」多值输入 fail-closed（服务端解析计数 ≠ 1 即拒绝，落库仍写原 strip 值；
  客户端 `wizardPrecheck` 镜像分隔符集；复用 `_FORM_TERM_SEPARATORS`/`MAX_DOCUMENT_NOS`/`parse_form_terms`）。
  独立提交以保证可单独回滚、且不与 P0 的验收混淆。

### P2（后续）

- 发现端与运行期共用的契约漂移纯函数（列集增减/未知状态值只提示；缺列输出键名清单，不做别名猜测）。
- 存量只读审计 + 必要时的键回写清单。
- 真正的多单号绑定（列表型键 + 签名版本化，不得复用现有 `documentNo` 字符串）。

### 验收测试点（P0）

- 含 `formId+incident+documentNo` 的行 → `matched`，`externalKey == incident`。
- TDC 行含 `_no+incident` → `externalKey == incident`；ARAS 行仍 `_no` 优先；未传源调用顺序快照不变。
- 仅有中文键「流水单号」/`incident` 为空串、空白、None → 非 500，`identity_missing`，不写绑定不落观测。
- 两命中行身份不同 → `identity_ambiguous`；同身份两行 → 正常。
- 存量键 = incident、运行期行新增 formId → `key_changed` 为假（护栏生效）。
- 性质测试：任意身份字段子集的命中行，结果只能是 `matched`（selected 等于同函数值）或显式原因码。
- `incident` 为数字与字符串时两侧结果一致。

## 5. 待用户取证（决定 P0 的收口）

1. **字段报告**：展开向导底部「外部同步与技术证据」，给出身份字段名集合
   （`_no`/`formId`/`incident`/`documentNo` 哪些存在）→ 决定 TDC 顺序表内容与污染窗口起点。
   若三者皆无，则身份机制不解释本次现象，需回到「上游单号口径变更」分支。
2. **存量只读审计**：TDC data_model 绑定/观测中 `external_key` 与当前行 `incident` 不等的数量，
   以及近期 `key_changed` 为真的数量 → 为 0 则无需迁移；非 0 则护栏必须先上线。
3. **一份生产列表样本**：行数、distinct `incident` 数、distinct `formId` 数
   → distinct incident 少于按 formId/documentNo 区分的实例数时，「incident 优先」不安全，
   改用「incident 相同且 formId 不同 → `identity_ambiguous` fail-closed」。

## 6. 立即处置（不改代码）

1. **不要用向导反复重试**（每次都是一次全量抓取）；等 P0。
2. 用交付物工作台/系统查询页按流水单号 `3D-00001018` 查一次：能出行为「数据可达、上游口径未变」，
   0 行则指向上游口径变更——这是用户侧最快的判别。
3. 若已有存量绑定变成 `needs_attention`（`external_key_mismatch`），先不要手工改绑定键，等审计结论。

## 7. 实施记录（2026-10-10，未提交、未打包）

改动文件（本次）：`services/project_status_records.py`、`services/project_status_discovery.py`、
`services/project_status_connectors.py`、`services/project_status_updates.py`、
`services/data_model_watchlist.py`、`web/app.py`、
`plugins/project_overview/static/deliverable/policy-logic.js`、
`plugins/deliverables/static/lib.js`、`plugins/deliverables/static/catalog.js`
+ 测试 5 个文件（含新增 `tests/test_data_model_identity_contract.py`）。

1. **身份口径统一（P0-1）**：`IDENTITY_FIELD_ORDERS = {"data_model": ("incident", …原序)}`；
   `record_identity(row, *, report_type=None)`（不传时行为逐字不变）；`identity_field_name()`；
   `identified_records(rows, *, report_type=None)`。三处调用点同源：发现端
   （`web/app.py` 用命中行身份当选中键）、`observe()` 候选过滤、连接器单记录
   `_identity(row, report)` / `_mapping_values(report=)` / 聚合 `identified_records(report_type=)`。
   新增 `AUTHORITATIVE_IDENTITY_FIELDS = {"data_model": "incident"}`：单记录绑定缺该列即
   `IdentityMissing` 422（不允许回退到 formId）。
2. **fail-closed 与 500 修复（P0-2）**：`IdentityMissing`(422) / `IdentityAmbiguous`(400) /
   同身份多行保留原 400；删除 `matched_instances[0]` 越界点；`observe()` 新增
   `reason`（`selected_not_in_candidates` 哨兵、`stability_baseline_missing`）。
3. **诊断披露（P0-3）**：结果级 `serialDiagnostic`（字段名与计数，无业务值）+
   `reason="serial_no_match"`；向导按 reason 渲染「已完整扫描 N 行」或「上游 0 行」。
4. **P1 单值校验**：`normalize_single_serial`（多值/不可见字符/全角 fail-closed，抓取前拒绝）
   用于发现入口、`assert_sync_ready`、策略校验三处；前端 `wizardPrecheck` 镜像。
5. **顺带修复**：`sync-now`/`sync-by-car-type` 的 `except` 顺序——`SyncBindingNotReadyError`
   是 `ValueError` 子类，此前未提交的改动把 409 SyncNotReady 降级成 422（已改回 409）。
6. **工作台提示**：`documentNoCrawlNotice` 在填了流水单号时提示「本次将全量抓取，请勿重复点击」。

## 8. 顾问实施后复核与处置

- 顾问：Claude `claude-opus-5-5`/xhigh，run `4f5c21d1-db60-4187-8edd-43b1ca7041d0`
  （`~/.dsh/expert-advisor/runs/claude-20261009-224333-691e1fe9.advice.md`）；裁决 1=adopted、2=adopted、3=partial。
- 已按顾问「不补不能打包」清单（A1–A8）补齐：
  - A1 权威字段硬约束 + 用例（缺 `incident`、只有 `formId` → 422，`authoritativeField=incident`）。
  - A2 存量多值绑定运行期行为：`assert_sync_ready` 在 `acquire_sync_lease` 路径上，运行期逐绑定捕获
    → 定时/手动同步得到 `needs_attention / binding_not_ready`，sync-now 得到 409 SyncNotReady，
    不会中断整批；新增 API 用例。
  - A3 闭合哨兵：源码级用例要求 `web/app.py`、`project_status_discovery.py`、
    `project_status_connectors.py` 里每个 `record_identity(` / `identified_records(` 调用都显式传 `report_type=`。
  - A4/A8 载荷洁净：`reason`/`serialDiagnostic` 只出现在响应里，不进 `aggregated_candidate_json`；
    `fieldReport.fields` 仍等于行键集合（60 列不变）；诊断只含字段名与计数。
  - A5 完整性优先：抓取不完整 + 单号不匹配 → 422 `IncompleteDiscovery`（`serial_no_match` 只在完整时出现）。
  - A6 签名金值：三个代表规则的 `config_signature` 与修复前 HEAD 逐字一致（实测比对，已钉成金值用例）。
- 未采纳/延后：
  - SOR 身份顺序本批不动（顾问 C：无 SOR 行字段与存量键证据，提 `processNo` 等于反向重演漂移风险）——
    列为待取证项（见 §9-4）。
  - 错误体加 `retryable:false`、`identity_field_absent` 独立原因码（顾问 B，非阻断）——登记待办。
- 本地修正顾问：其 S1「包内自相矛盾」属实（本文件上一版措辞），已按运行期真实调用链澄清并补用例；
  S11 只是包内简写（实际代码为 keyword-only `report_type=`）；S10 的 vendor 校验和失败与本次改动无关。

## 9. 剩余待办与回滚点

1. **打包前**：`memory/CURRENT_STATE.md` 已记录本次结论；提交建议拆 4 个提交（顾问 E）：
   ① 此前未提交的车型锚点改动 + except 顺序修正；② 身份口径同源；③ 单值校验与前端；④ `reason` 与 `serialDiagnostic`。
2. **待用户取证**：存量数模绑定的 `external_key` 落在 `incident` / `formId` 集合的数量；
   `documentNo` 含分隔符或非 NFKC 稳定字符的数量（顾问 D：命中项标「配置无效」，不要混进未找到）。
3. **观察项**：窗口期经候选列表建立、键落在 `formId` 的绑定，升级后会变成
   `selected_not_in_candidates` / `needs_attention`，需人工重建（不可自动迁移）。
4. **SOR 同类风险**：SOR 与数模同源同函数；若 SOR 行也含 `formId`，`observe()`/连接器会按
   `formId` 取键。最小取证：在系统查询/SOR 字段报告里确认 SOR 行是否含 `formId`；含则另立任务按
   「SOR 权威键 processNo」处理并做存量审计。
5. **错误分发**：前端/自动化目前按 HTTP 状态码分发（422 含 `IncompleteDiscovery` 与 `IdentityMissing`
   两种机器码）；如需自动重试需先按 `error.type` 区分（顾问 B）。
