# 架构优化提示词：数模同步「部门 / 科室」字段模型与双入口收敛

> 用法：把本文件整份粘贴给 Claude（或作为项目文档上传），它会据此产出架构方案。
> 文中的路径都是仓库相对路径；不要假设你能运行代码或联网。

---

## 0. 你的角色与本次任务

你是一位资深架构师，为一个**本地内网、单机部署**的工程数据工具（Python + Flask + SQLite + 原生 ES module 前端 + Preact/htm，插件化目录 `plugins/<id>/`）做一次**字段模型与 UI 入口的架构收敛**。

本次任务不是修 bug，而是回答：

> 「部门 / 科室」这类**同步范围条件**，应该在绑定规则、连接器、向导、高级设置、摘要列表、归档任务这六个位置里如何**只表达一次**，并且让「上游查询条件」与「抓取后本地收窄条件」在类型上不可混淆？

产出要求见 §7。请给出**可落地的数据模型 + 迁移路径 + 分阶段任务**，不要给泛泛的原则清单。

---

## 1. 项目背景（必须先理解的系统事实）

### 1.1 业务对象

- 工具管理若干「交付物」（deliverable），每个交付物可绑定一个**外部数据源**做自动同步。
- 本次只涉及一个交付物：**D5「数模设计审核流程报表」**，数据源是自研流程系统 **TDC** 的 `data_model` 报表（列表接口 + 官方 XLSX 导出）。
- 同步流程：`runner` 取租约 → `connector.collect(context)` 抓数 → 返回标准化快照 → 服务层写快照/分析缓存。
- 用户可配置的同步条件存在 `match_rule_json`（JSON 对象，键为 camelCase）。

### 1.2 三个「看起来一样」的维度（本次问题核心）

TDC 数模报表同时有**两个维度**，而 HTTP 查询参数名与报表列名**交叉命名**，这是全部混乱的源头：

| 语义 | HTTP 查询参数 | 报表行内字段（原始行 JSON） | 取值粒度 | 是否多值 |
| --- | --- | --- | --- | --- |
| 部门 | `superDepartment` | `superDepartment` | `车体工程` 级 | 单值（未验证多值） |
| 科室 | `department` | `department`（第 5 列） | `车身科` 级 | 单值（未验证多值） |

即：**查询参数 `department` 表示科室，而行内 `department` 也表示科室**；部门在两边都叫 `superDepartment`。

绑定规则里对应三个键：

- `department` → 发给上游 `superDepartment`（部门，单值）
- `section` → 发给上游 `department`（科室，单值）
- `sections` → **新增**，科室多选（`list[str]`），**绝不发上游**，抓取后按行内 `department` 列本地收窄

### 1.3 为什么新增 `sections` 而不是把多值发给上游

- 上游 `department` 只接受单值，多值能力从未取证。
- 若把单值科室发上游，其它科室的行在**抓取阶段**就被丢掉，本地再筛就是**静默少算**。
- 所以 `sections` 的语义是「**抓取后收窄**」，`section` 的语义是「**上游过滤**」。两者不能互相代替，也**不应该同时出现在用户面前**。

### 1.4 科室值必须经过「归集」

历史科室名五花八门（`结构工程科`、`BE 车身科`、`视觉工程科`、`架构集成科`…），统计与筛选都必须先归集到**现行五科室**（车体科、车身科、内饰科、外饰科、车体架构集成科）。

归集规则是**用户可编辑**的，存在本地 `app_settings` KV；唯一判定原语是：

```python
# core/section_rollup.py
resolve_section(value: object, index: Mapping[str, str | None] | None) -> str | None
# 三级全等：折叠空白全等 → 去空格全等 → 剥一层「拉丁 token + 空格」前缀后全等
# 不做子串匹配（`非车体科`、`车体科/内饰科` 必须落「未归集」）
```

看板图表、列表筛选、同步收窄**都必须共用**这一个原语。

---

## 2. 现状：同一语义的三处入口

### 2.1 入口 A：向导（「开启自动同步 / 修改同步配置」）

文件：`plugins/project_overview/static/deliverable/policy.js`（约 710 行，组件 `SyncSummaryCard`）。

向导字段是**手写分支**：

```js
// 伪代码：向导按 reportType 硬编码每个交付物显示哪些字段
${kind.isNcr ? 科室多选(声明式) : html`${kind.isDataModel && 科室多选(筛选式)} <label>责任部门…</label>`}
${(kind.isDataModel || kind.isSor) && 状态输入框}
${kind.isDataModel && 流水单号单值 / 多单号 / 实例号 / 周期}
```

向导的「提交」不走通用表单：它先做一次**映射发现**（mapping-discovery）抓证据，再 `PATCH /update-policy` 保存。

### 2.2 入口 B：高级设置（绑定编辑器）

文件：`plugins/project_overview/static/deliverable/policy-logic.js`（约 1050 行）。

高级设置是**能力驱动**的通用渲染：

```js
// bindingInitialValues(item, policy, capabilities): 按 capabilities.matchFields 生成表单值
// matchFields 形如 [key, label, filterName, placeholder]
// buildPolicyPayload(...): 把 values.match 逐键写回 matchRule
```

而 D5 的 `matchFields` 里同时有：

```python
# core/project_status_contracts.py（VPI-T2-D5.matchFields）
("department", "部门", "department", "可选"),
("section", "科室", "section", "可选"),
```

→ 用户因此在高级设置里看到**「部门」和「科室」两个文本框**，而向导里只有**一个「责任部门」**。同一概念，三处不同名字、两套控件、两套默认值。

### 2.3 入口 C：交付物明细列表的「同步设置」摘要

文件：`plugins/project_overview/static/details/sync-settings-logic.js`。

```js
const FILTER_LABELS = { department: "部门", section: "科室", sectionScope: "科室范围", … };
// 缺 sections 标签 → 新键会以原始英文键名出现在摘要里
```

### 2.4 第四条路径：定时归档任务

文件：`services/scheduled_archive_connectors.py`。

归档任务有一套**自己的** filters 白名单与过滤器构造：

```python
_TDC_DATA_MODEL_KEYS = { "incident", "applicant", "department", "section", … }  # 不含 sections
def _checked_filters(value, allowed):
    unknown = set(value) - allowed
    if unknown: raise ValueError("archive filters contain unsupported fields")
```

→ 同步侧新增的 `sections` 在归档侧是**未知键**（会直接 raise），两条路径的口径可能分叉。

---

## 3. 用户已反馈的问题（真实场景）

**背景诉求（用户原话意译）**：「按部门筛不可靠——同一个科室的人，有人挂在『技术中心』、有人挂在『车体工程』，按部门筛会漏人。所以要在同步选项里加『以科室筛选』，默认车体科、车身科、内饰科、外饰科、车体架构集成科五个科室。」

**最新反馈（两条）**：

1. 「开启同步设置里面没有科室筛选，高级设置里面才有。」
2. 「里面内容还重复。」（指高级设置匹配规则区里「部门」与「科室」两个框并存，与向导的「责任部门」重复）

**已核实的运行事实**：

- 向导的科室多选**已经写在源码里**（`policy.js` 的 `kind.isDataModel` 分支，带 `data-wizard-field="sections"`），后端也已下发 `sourceInfo.sectionPresets`（默认五科室）。
- 但用户看到的界面**仍是改动前**的样子（向导只有「责任部门」，文案也是旧文案）。
- 当前工作区最近一次打包产物是 `dist/hci-20261026/`（2026-10-26），**早于**这次源码改动；WebUI 以 onedir 形式分发（`VSE-WebUI.exe` + `_internal/` + `plugins/`）。
- 结论：**「看不到」主要是发布链路问题（旧包/旧进程/浏览器缓存），不是渲染逻辑没写**。这一点必须进方案（见 D6）。

---

## 4. 已落地的实现（供你判断改动面，不要重复设计）

| 层 | 位置 | 现状 |
| --- | --- | --- |
| 契约 | `core/project_status_contracts.py` | D5 `matchKeys` 含 `sections`；`filterKeys` **不含** `sections`；能力标志 `sectionPresets: True` |
| 校验 | `services/project_status_updates.py` | `sections` 与 NCR 的 `sectionScope` 共用「非空、≤20 项、每项 ≤100 字符、无控制字符、不重复」形状 |
| 规范化 | `core/section_rollup.py` | `normalize_section_selection(value) -> tuple[str, ...]` 单一来源（保存/发现/收窄共用） |
| 连接器 | `services/project_status_connectors.py` | `_data_model_filters`：有 `sections` 时 `section=None`；`_narrow_by_sections` 本地收窄；整批缺科室列 → raise |
| 运行期上下文 | `services/project_status_sync_runner.py` | `SyncBindingContext.section_rollup` 由 runner 从 `app_settings` 读出注入（连接器**禁止**访问 DB） |
| 发现 | `web/app.py` | `_MAPPING_DISCOVERY_RULE_FIELDS[("tdc","data_model")]` 含 `sections`；收口后与 collect 共用收窄函数 |
| 下发 | `web/app.py` | `sourceInfo.sectionPresets`（来自归集目标，默认五科室） |

### 4.1 关键约束：`filterKeys` 与 `matchKeys` 是两个不同的集合

```python
# filterKeys：连接器**真正改变上游过滤器**的键。有测试强制：
#   每个声明键单独出现都必须改变过滤器；未声明键不得改变过滤器。
# matchKeys：配置键（签名/审计/保存校验）。可以是本地收窄键、声明式键。
```

`sections` 属于后者。`sectionScope`（NCR 的声明式科室范围）同理。

---

## 5. 不可突破的约束（方案必须满足）

1. **连接器不得访问数据库**。任何需要 DB 的信息（归集规则、关注清单）只能由 runner 读好后注入只读上下文。
2. **`filterKeys` 语义不变**：它表示「改变上游查询」的键；本地收窄键与声明式键不得混入。
3. **fail-closed**：抓取不完整、结构漂移（整批行缺科室列）、规则脏值都必须 raise 并保留上次结果，不允许写出「零行成功」。
4. **归集单一来源**：任何科室匹配都必须走 `resolve_section`，不得出现第二套匹配（子串匹配会误归集）。
5. **不得静默改变已发布报表的范围**：存量绑定的行为变化必须由用户显式保存触发。
6. **不得改 EWO / PAA / NCR 的既有语义**：它们的 `department` / `sectionScope` 行为必须原样保留。
7. **不引入新框架、新构建链、前端打包器**。前端是原生 ES module，直接由 Flask 静态服务；插件以 `.vsepkg`（签名 zip）分发。
8. **避免大爆炸重写**：`policy.js` 710 行、`policy-logic.js` 1051 行，已有测试覆盖（node 纯逻辑 + VM 渲染接线 + Flask 集成）。方案应能分阶段独立验收。

---

## 6. 需要你决策的问题

### D1 范围条件的字段模型

当前有三个键、两类语义（上游过滤 / 本地收窄），还有第四类历史包袱（`sectionScope` 声明式）。请给出一个**类型上不可混淆**的表达方式，例如：

- 在 `matchRule` 内部按用途分组（`upstream: {…}` / `narrow: {sections: […]}`），还是
- 保留扁平键但在契约里显式声明每个键的 `role`（`upstream-filter` / `local-narrow` / `declaration-only`），还是
- 其它（请给出理由）。

评估维度：向后兼容（存量 `match_rule_json` 不改也能跑）、签名/审计（配置签名会随结构变化）、迁移成本、可读性。

### D2 向导与高级设置的单一来源

两套渲染路径（手写分支 vs `matchFields` 驱动）是重复的根因。请给出收敛方案，例如：

- 让向导也由「字段描述」驱动（同一份描述同时供向导与高级设置），还是
- 保留向导手写、但把**字段描述/默认值/校验/文案**抽到共享模块，两边只共享数据不共享布局，还是
- 直接废弃高级设置里的重复字段（只保留向导入口）。

必须回答：**用户看到的「部门 / 科室 / 责任部门」到底应该剩几个框？分别叫什么？**

### D3 「部门」还留不留

用户明确说部门口径不稳定（同科室的人分散在「技术中心」和「车体工程」）。选项：

- (a) 向导彻底移除部门字段，只在高级设置保留（进阶用户可用）；
- (b) 向导保留但默认空 + 强提示（当前做法）；
- (c) 部门与科室合并成一个「范围」控件（部门作为可选前缀条件）。

请给出推荐并说明**存量绑定（当前只有 `department=车体工程`）**如何处理，才能既不静默改范围、又不继续漏人。

### D4 `section`（单值上游科室）的去留

`section` 会发上游 `department`，与 `sections`（本地收窄）语义重叠。选项：

- 保留双轨（单值走上游、多值走本地），
- 统一走本地收窄并废弃 `section`（上游不再收科室条件，抓取量上升），
- 保留 `section` 但仅在「只选一个科室」时自动启用。

请评估抓取规模与「同一次同步里两套科室语义并存」的风险。

### D5 归档任务路径的一致性

`scheduled_archive_connectors._TDC_DATA_MODEL_KEYS` 不含 `sections` 且未知键会 raise。请决定：

- 归档任务复用同一字段模型（白名单按角色生成），还是
- 归档任务只接受上游过滤类键（明确拒绝本地收窄键并给出可执行文案）。

### D6 发布链路（为什么用户看不到已实现的功能）

请给出一个**可验证的发布与缓存清单**，覆盖：

1. 源码改动 → onedir 包重建（哪些目录会被复制、`plugins/` 是否独立于 `_internal/`）；
2. 插件是否走 `.vsepkg` 签名包（若走，需要重新签名/激活）；
3. 浏览器 ES module 缓存（静态文件是否带版本号/ETag，强制刷新的判定方法）；
4. 后端进程重启的必要性（哪些改动必须重启：Python 模块 vs 静态文件）；
5. 一个**用户可自查**的判定步骤（例如界面上应出现哪个控件/哪个文案）。

### D7 摘要与展示一致性

`details/sync-settings-logic.js` 的 `FILTER_LABELS` 缺 `sections`，新键会以英文原名出现。请把它纳入字段模型的一部分（展示标签也应由同一份描述派生），而不是各处补字典。

---

## 7. 期望输出格式

请严格按下面顺序输出，不要先讲背景：

1. **一页结论**：推荐方案（一段话）+ 三个关键取舍（每个一句话）。
2. **方案对比表**：至少 2 个候选（含你推荐的那个），列为：改动面 / 兼容性 / 风险 / 分阶段可行性 / 测试成本。
3. **目标数据模型**：给出 `matchRule` 的结构草案（JSON 示例）+ 契约声明草案（Python 片段）+ 迁移函数签名。
4. **UI 字段清单**：向导 / 高级设置 / 摘要列表三处各显示什么（表格：位置 · 控件 · 键 · 默认值 · 提示文案要点）。
5. **分阶段落地计划**（≤3 阶段）：每阶段列出「改哪些文件 / 验收标准 / 可独立回滚方式」。
6. **验收与测试清单**：后端（保存校验、collect 收窄、discovery 同口径、归档拒绝）、前端（渲染接线、纯逻辑、node 语法）。
7. **风险与反例**：列出会导致**静默少算/多算**的具体情形，以及方案如何阻断。
8. **不要做的事**：明确列出 3–5 条（例如不要为多值科室改造上游、不要重写整个向导、不要引入前端构建链）。

要求：

- 所有代码片段用仓库相对路径标注位置；不要编造不存在的模块。
- 不确定的地方明确写「需要现场取证」，并给出**最小取证动作**（哪一次请求、哪个字段、什么现象能区分假设）。
- 不要给「建议加强测试」「建议统一命名」这类没有落点的建议。

---

## 8. 背景材料

### 8.1 关键文件与职责

| 文件 | 职责 |
| --- | --- |
| `core/project_status_contracts.py` | 交付物能力注册表（`matchKeys` / `filterKeys` / `matchFields` / `sectionPresets` / `sectionScopePresets`） |
| `core/section_rollup.py` | 科室归集规则、`resolve_section`、`normalize_section_selection` |
| `services/project_status_updates.py` | 绑定规则保存校验（`_valid_match_rule_values`）、多单号不变量 |
| `services/project_status_connectors.py` | TDC/Aras 连接器；`_data_model_filters`、`_narrow_by_sections`、`_snapshot` |
| `services/project_status_sync_runner.py` | `SyncBindingContext`（`watchlist`、`section_rollup` 注入）、run_once 编排 |
| `services/project_status_discovery.py` | 映射发现（候选、稳定性、字段报告） |
| `web/app.py` | 路由；`_mapping_discovery_query_identity`、`_MAPPING_DISCOVERY_RULE_FIELDS`、`sourceInfo` 下发 |
| `plugins/project_overview/static/deliverable/policy.js` | 向导 UI（手写分支） |
| `plugins/project_overview/static/deliverable/policy-logic.js` | 向导纯逻辑 + 高级设置表单逻辑（`bindingInitialValues` / `buildPolicyPayload`） |
| `plugins/project_overview/static/deliverable/multi-select.js` | 多选控件（`SearchMultiSelect`，支持自由输入） |
| `plugins/project_overview/static/details/sync-settings-logic.js` | 明细列表「同步设置」摘要 |
| `services/scheduled_archive_connectors.py` | 定时归档任务（独立 filters 白名单） |

### 8.2 现有测试（改动的安全网）

- `tests/test_project_status_data_model_sections.py`：契约、保存/回读、非法形状、上游参数边界、本地收窄、发现收口、collect 级收窄、结构漂移 raise。
- `tests/test_plugin_overview_data_model_sections.py`：真实 `policy-logic.js` 的默认值/载荷（node）。
- `tests/test_plugin_overview_wizard_sections.py`：真实 `policy.js` 的渲染接线（VM + 桩），含「SOR/NCR 不得出现 sections 字段」。
- `tests/test_project_status_contracts.py::test_declared_filter_keys_match_connector_consumption`：强制 `filterKeys` 必须改变上游过滤器。
- `tests/test_project_status_section_scope.py`：NCR 的 `sectionScope` 只声明、不查询。

### 8.3 一段真实代码（收窄函数，供你判断扩展点）

```python
# services/project_status_connectors.py（节选）
@staticmethod
def _narrow_by_sections(rows, rule, rollup):
    selected = normalize_section_selection(rule.get("sections"))   # 空 = 不限
    if not selected:
        return list(rows)
    index = rollup if rollup is not None else _default_section_index()
    kept, unassigned, missing = [], 0, 0
    for row in rows:
        raw = _row_section_value(row)          # department / 科室 / sectionName
        if raw is None:
            missing += 1; continue
        target = resolve_section(raw, index)   # 归集：历史名 → 现行科室
        if target is None:
            unassigned += 1; continue
        if target in set(selected):
            kept.append(row)
    if rows and missing == len(rows):
        raise ValueError("同步行缺少科室列（department/科室），无法按科室筛选；…")
    emit("tdc_section_narrowed", {...计数...})
    return kept
```

---

## 9. 明确不要做的事

- 不要试图让上游 TDC 接受多值科室（无证据，且失败方式是静默少算）。
- 不要把 `sections` 加进 `filterKeys`（有测试强制语义）。
- 不要在连接器里读 SQLite / `app_settings`。
- 不要为了统一而改动 EWO / PAA / NCR 的既有字段与文案。
- 不要引入前端构建链或新状态管理库；不要重写整个向导。
- 不要输出没有文件落点的「架构建议」。

---

## 10. 一句话总结要回答的问题

> 在「部门口径不可靠、科室必须归集、上游只收单值、连接器不能读库、存量配置不能静默改范围」这五个约束同时成立时，**同步范围条件应该怎样建模与呈现**，才能让用户在向导里一眼看懂「我在按什么筛」，并且永远只有一处可以改？
