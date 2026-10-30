# 架构方案：数模同步「部门 / 科室」字段模型与双入口收敛

> 对应提示词：`docs/PROMPT_SYNC_SCOPE_ARCH_20261027.md`
> 依据：仅提示词所述事实，未读取/运行仓库代码。凡标「需要现场取证」处均附最小取证动作。

---

## 1. 一页结论

**推荐方案**：`match_rule_json` **保持扁平键不动**，在 `core/project_status_contracts.py` 为 D5 新增一份按键声明的 `MatchFieldSpec`（`role ∈ upstream / narrow / declare`、`surfaces`、`exclusive_group`、`deprecated`、标签与提示）。`filterKeys`、`matchKeys`、`matchFields`、归档白名单、摘要标签**全部从这份声明派生**，后端把它作为 `capabilities.fieldSpecs` 下发；向导保留手写布局，只在 D5 的「范围」区按声明渲染。D5 的用户可见范围条件收敛为**一个「科室范围」多选（`sections`，默认五科室）**；`department` 降为高级设置里的「上游部门（进阶）」，`section` 停用（存量只读，不可新设）。存量绑定 `department=车体工程` 不自动改，向导里展示「漏人提示 + 一键改为按科室」，用户显式保存后才生效。「看不到」的问题先走发布链路修复（阶段 1），与模型收敛互不依赖。

**三个关键取舍**

1. **不改存储结构、只加声明**：牺牲了 JSON 自描述性，换来存量配置签名零变化、零数据迁移、可分阶段回滚。
2. **停用 `section` 而不是做「单选自动走上游」**：上游按原始科室名全等过滤，无法走 `resolve_section` 归集，`车身科` 会漏掉 `BE 车身科` 等历史名 → 单选走上游本身就是静默少算源，不值得保留双轨。
3. **共享数据不共享布局**：向导不改成表单引擎（避免重写 710 行 `policy.js`），只把字段描述/默认值/校验/文案收敛到同一份声明。

---

## 2. 方案对比

| 候选 | 改动面 | 兼容性 | 风险 | 分阶段可行性 | 测试成本 |
| --- | --- | --- | --- | --- | --- |
| **A（推荐）扁平键 + 契约 `role` 声明** | contracts 新增声明与派生函数；updates 加角色校验；archive 白名单改派生；前端新增一个纯逻辑模块，`policy-logic.js` / `policy.js` / `sync-settings-logic.js` 局部改 | 存量 `match_rule_json` 原样可跑，签名不变；只对 D5 生效，EWO/PAA/NCR 继续用字面量 | 低：派生集合可用「派生 == 旧字面量」测试锁住后再删字面量 | 高：后端声明 / 前端消费 / 发布链路三段可独立上线、独立回滚 | 中：主要是派生等价测试 + 角色校验用例 |
| B `matchRule` 按用途嵌套（`upstream:{}` / `narrow:{}`） | 所有读 `matchRule` 的位置：连接器、发现、签名、审计、归档、前端载荷，以及存量数据迁移 | 差：存量 JSON 需迁移或双读；配置签名全部变化，触发「范围变化」误报 | 高：迁移脚本 + 双读期易出现某路径只认新结构 → 条件被忽略（静默多算） | 低：数据格式切换是一次性门槛 | 高：每条读路径都要覆盖新旧两种结构 |
| C 只删高级设置重复框（UI 补丁） | 删 D5 `matchFields` 的 `section`，向导改文案 | 表面兼容 | 中：不解决根因；若 `buildPolicyPayload` 只回写 `matchFields` 里的键，存量 `section`/`sections` 会在高级设置保存时被丢弃（见 §7-R4） | 高 | 低，但问题会在下一个字段上复现 |

---

## 3. 目标数据模型

### 3.1 `matchRule` 结构（不变，扁平 camelCase）

```jsonc
// 新建 D5 绑定（向导默认）
{ "sections": ["车体科", "车身科", "内饰科", "外饰科", "车体架构集成科"] }

// 进阶：仍可叠加上游部门（用户在高级设置里显式填写）
{ "department": "车体工程", "sections": ["车身科"] }

// 存量（原样保留、原样运行，直到用户显式保存修改）
{ "department": "车体工程" }

// 非法：同一 exclusive_group 两键同时非空 → 保存时拒绝
{ "section": "车身科", "sections": ["车身科"] }
```

### 3.2 契约声明草案

```python
# core/project_status_contracts.py（新增）
from dataclasses import dataclass, field
from typing import Literal

FieldRole = Literal["upstream", "narrow", "declare"]
Surface = Literal["wizard", "advanced", "summary", "archive"]

MATCH_FIELD_CONTRACT = "2026-10-27.1"   # 前后端版本对齐用，见 §5 阶段 1

@dataclass(frozen=True)
class MatchFieldSpec:
    key: str                               # matchRule 中的键
    role: FieldRole                        # upstream=改变上游查询；narrow=抓取后本地收窄；declare=只声明不查询
    label: str
    kind: Literal["text", "multi"]
    surfaces: frozenset[Surface]           # 常驻显示的位置
    show_if_set: frozenset[Surface] = frozenset()  # 仅当绑定已有值时显示（存量条件）
    exclusive_group: str | None = None     # 同组最多一个非空
    deprecated: bool = False               # 不可新设，存量值可保留/清空
    upstream_param: str | None = None      # role=upstream 时对应的 HTTP 参数名（仅文档/审计用）
    presets: str | None = None             # 默认值来源，如 "sectionPresets"
    hint: str = ""

D5_FIELD_SPECS: tuple[MatchFieldSpec, ...] = (
    MatchFieldSpec(
        "sections", "narrow", "科室范围", "multi",
        surfaces=frozenset({"wizard", "advanced", "summary"}),
        exclusive_group="section_scope", presets="sectionPresets",
        hint="抓取全部记录后，按归集后的现行科室筛选；留空 = 不限科室",
    ),
    MatchFieldSpec(
        "department", "upstream", "上游部门（进阶）", "text",
        surfaces=frozenset({"advanced", "summary", "archive"}),
        show_if_set=frozenset({"wizard"}),
        upstream_param="superDepartment",
        hint="在 TDC 端直接过滤；同科室人员挂在其他部门（如技术中心）时会被漏掉",
    ),
    MatchFieldSpec(
        "section", "upstream", "上游科室（已停用）", "text",
        surfaces=frozenset({"summary", "archive"}),
        show_if_set=frozenset({"wizard", "advanced"}),
        exclusive_group="section_scope", deprecated=True,
        upstream_param="department",
        hint="按原始科室名全等过滤，不做归集；请改用「科室范围」",
    ),
    # 其余 D5 键（状态、流水单号、多单号、实例号、周期、applicant、incident…）：
    # 阶段 2 机械生成——在现有 filterKeys 中的 → role="upstream"；
    # 在 matchKeys − filterKeys 中且不是 sections 的 → 需要现场取证逐个归类（见 §3.4）。
)

def filter_keys_from(specs) -> frozenset[str]:
    return frozenset(s.key for s in specs if s.role == "upstream")

def match_keys_from(specs) -> frozenset[str]:
    return frozenset(s.key for s in specs)

def match_fields_from(specs) -> tuple[tuple[str, str, str, str], ...]:
    """兼容旧 matchFields 形状，仅含 advanced 常驻且 kind=text 的字段。"""
    return tuple((s.key, s.label, s.key, s.hint or "可选")
                 for s in specs if "advanced" in s.surfaces and s.kind == "text")

def field_specs_payload(specs) -> list[dict]:
    """下发前端的 capabilities.fieldSpecs（JSON 可序列化）。"""

def describe_match_rule(specs, rule: Mapping[str, object]) -> list[dict]:
    """摘要用：[{key, label, role, value}]，按声明顺序；未声明键原样带出并标 role="unknown"。"""
```

D5 注册项改为：`filterKeys = filter_keys_from(D5_FIELD_SPECS)`、`matchKeys = match_keys_from(...)`、`matchFields = match_fields_from(...)`，并新增 `fieldSpecs`。**EWO / PAA / NCR 不加 `fieldSpecs`，字面量保持不动**（约束 6）。

### 3.3 校验与迁移函数签名

```python
# services/project_status_updates.py（新增，挂在 _valid_match_rule_values 之后）
def _validate_field_roles(
    rule: Mapping[str, object],
    previous: Mapping[str, object] | None,   # 当前已存规则，用于 deprecated 判定
    specs: Sequence[MatchFieldSpec],
) -> None:
    """
    - exclusive_group：同组非空键 > 1 → ValueError（替代连接器里「有 sections 就把 section 置 None」的静默覆盖）
    - deprecated：新值 != previous 中的值且非空 → ValueError（只允许保留原值或清空）
    """

# core/project_status_contracts.py（新增，纯函数，从不自行落库）
@dataclass(frozen=True)
class ScopeProposal:
    rule: dict[str, object]       # 建议的新规则
    removed: tuple[str, ...]      # 建议移除的键
    added: tuple[str, ...]
    reason: str                   # 给 UI 的一句话

def propose_scope_migration(
    rule: Mapping[str, object], presets: Sequence[str]
) -> ScopeProposal | None:
    """
    存量 {department: X}（无 sections、无 section）→ 建议 {sections: presets}，移除 department。
    存量 {section: Y} → 建议 {sections: [resolve 后的 Y]}，移除 section。
    其它情况返回 None。
    由 web/app.py 计算后随 sourceInfo.scopeProposal 下发；只有用户在向导点「采用」并保存才生效（约束 5）。
    """
```

归档侧：

```python
# services/scheduled_archive_connectors.py
_TDC_DATA_MODEL_KEYS = archive_keys_from(D5_FIELD_SPECS) | _TDC_DATA_MODEL_ARCHIVE_EXTRA
# archive_keys_from = role=="upstream" 且 "archive" in surfaces（或 show_if_set）
# _TDC_DATA_MODEL_ARCHIVE_EXTRA：派生集合与现有字面量的差集，阶段 2 用测试锁定后显式列出

def _checked_filters(value, allowed, specs=None):
    # 未知键仍 raise；若该键在 specs 里且 role=="narrow"，报可执行文案：
    # "归档保存的是 TDC 上游原始导出，不支持「科室范围（sections）」；
    #  如需按科室查看，请在看板/明细里按归集科室筛选。"
```

### 3.4 需要现场取证

| 问题 | 最小取证动作 | 区分现象 |
| --- | --- | --- |
| D5 `matchKeys − filterKeys` 除 `sections` 外还有哪些键 | 在 Python 里打印 D5 注册项两集合的差集 | 差集为空 → 机械生成即可；非空 → 逐个判定 narrow / declare |
| 存量是否有绑定用了 `section` / 同时用了 `section`+`sections` | 对存 `match_rule_json` 的表执行 `SELECT id, match_rule_json FROM <绑定表> WHERE match_rule_json LIKE '%"section"%'` | 0 行 → `section` 可直接只读停用；有行 → 向导必须展示迁移提示 |
| 去掉上游部门后抓取量与漏人量 | 同一周期发两次列表请求：带 `superDepartment=车体工程` / 不带，各取 `total`；对不带的结果按 `resolve_section` 统计「归集到五科室 且 superDepartment≠车体工程」的行数 | 后者 > 0 即为当前存量绑定的漏人数，可直接显示在迁移提示里；两次 `total` 之比 = 抓取量放大倍数 |
| 不带部门时官方 XLSX 导出/分页是否有上限 | 不带部门导出一次，对比行数与列表 `total` | 不等 → 必须先确认完整性校验能 raise（约束 3），再上线 D3 迁移 |
| `buildPolicyPayload` 是否保留 `matchFields` 之外的键 | 在 `tests/test_plugin_overview_data_model_sections.py` 里加一例：policy 带 `sections`、matchFields 不含 `sections`，断言载荷仍含 `sections` | 丢失 → 当前高级设置保存会把科室范围清空（R4），阶段 3 前必须修 |

---

## 4. UI 字段清单（仅 D5）

| 位置 | 控件 | 键 | 默认值 | 提示文案要点 |
| --- | --- | --- | --- | --- |
| 向导 | 「科室范围」多选（`SearchMultiSelect`，允许自由输入） | `sections` | 新建：`sourceInfo.sectionPresets`（五科室）；编辑：已存值 | 「抓取全部记录后按现行科室筛选，历史科室名会自动归集」；留空 = 不限 |
| 向导 | 存量条件条（chip，可移除，不可编辑） | `department`（仅已有值时） | 已存值 | 「当前还在 TDC 端按部门『车体工程』过滤，挂在其他部门的同科室人员不会被抓取」+ 按钮「改为仅按科室筛选（推荐）」→ 套用 `scopeProposal`，保存后生效 |
| 向导 | 存量条件条（只读） | `section`（仅已有值时） | 已存值 | 「上游科室已停用，按原始名过滤会漏掉历史科室名」+ 同一迁移按钮 |
| 向导 | （删除）「责任部门」文本框 | — | — | 新建绑定不再出现 |
| 高级设置 | 「科室范围」多选 | `sections` | 同向导 | 同向导；与 `section` 互斥 |
| 高级设置 | 「上游部门（进阶）」文本框，放在折叠的「上游过滤」分组 | `department` | 空 | 「在 TDC 端过滤，可能漏人；一般只需设置科室范围」 |
| 高级设置 | 「上游科室（已停用）」只读 + 清空按钮 | `section`（仅已有值时） | 已存值 | 不可新填 |
| 摘要列表 | 文本行，带角色标记 | 来自 `describe_match_rule` | — | `科室范围（抓取后筛选）：车体科、车身科…`；`上游部门（TDC 过滤）：车体工程`；`上游科室（已停用）：…`；另显示最近一次同步的「未归集 N 行 / 缺科室 N 行」 |

结论：**常态只有一个框——「科室范围」**；「上游部门」只在高级设置里出现；「科室（单值）」「责任部门」两个名字从界面消失。

---

## 5. 分阶段落地计划

### 阶段 1：发布链路与版本对齐（解决「看不到」，不改模型）

**改哪些文件**

- `web/app.py`：插件静态 JS/CSS 响应加 `Cache-Control: no-cache`（保留 ETag/Last-Modified 走 304，内网成本可忽略）；`sourceInfo` 增加 `contractVersion = MATCH_FIELD_CONTRACT`。
- `core/project_status_contracts.py`：新增 `MATCH_FIELD_CONTRACT` 常量。
- `plugins/project_overview/static/deliverable/policy.js`：读 `sourceInfo.contractVersion`，与前端常量不一致时在向导顶部提示「前端与后端版本不一致：请重启 VSE-WebUI 并强制刷新（Ctrl+F5）」。
- 发布清单（写进 `docs/PHASE3_DEPLOYMENT_RUNBOOK_20260917.md` 或新的 runbook）：

| # | 检查项 | 判定方法 |
| --- | --- | --- |
| 1 | 包是否包含新源码 | 在包内 `plugins/project_overview/static/deliverable/policy.js` 搜 `data-wizard-field="sections"`；`dist/hci-20261026/` 预期**搜不到**（早于改动），重建后必须搜得到 |
| 2 | Python 改动是否进了 `_internal/` | `core/`、`services/`、`web/` 是冻结在 `_internal/` 里的，**必须重建 onedir**；只替换 `plugins/` 不够（需要现场取证：确认 `plugins/` 是包旁的独立目录、由 Flask 直接从磁盘提供） |
| 3 | 插件是否走 `.vsepkg` | 需要现场取证：查 `web/app.py` 插件静态路由实际指向的根目录。若指向激活后的安装目录，则必须重新签名 `.vsepkg` 并激活，否则浏览器拿到的仍是旧激活副本 |
| 4 | 浏览器缓存 | DevTools → Network → 勾选 Disable cache → 刷新；检查 `policy.js`、`policy-logic.js`、`multi-select.js` 三个文件（子模块 import 不带版本号，最容易残留）的响应体是否含 `sections` |
| 5 | 进程重启 | 改了 Python（契约、`sourceInfo.sectionPresets`、连接器、`web/app.py`）→ 必须重启 `VSE-WebUI.exe`；只改 `plugins/` 静态文件 → 刷新即可（前提是第 2 项确认从磁盘提供） |
| 6 | 用户自查 | 打开 D5 →「修改同步配置」：应出现「科室范围」多选并预选五个科室；若出现版本不一致提示，按提示重启+强刷 |

**验收**：在目标机器上，第 6 项成立；人为让前后端不一致时出现提示。
**回滚**：删除响应头与提示代码即可，不涉及数据。

### 阶段 2：后端字段模型（无 UI 变化）

**改哪些文件**

- `core/project_status_contracts.py`：`MatchFieldSpec`、`D5_FIELD_SPECS`、`*_from` 派生函数、`describe_match_rule`、`propose_scope_migration`；D5 注册项改为派生值并新增 `fieldSpecs`。**先保留旧字面量**，用测试断言「派生 == 旧字面量」，通过后再删字面量（`matchFields` 会因去掉 `section` 而有意不等，单独断言）。
- `services/project_status_updates.py`：`_validate_field_roles`（互斥组、deprecated 不可新设）。
- `services/project_status_connectors.py`：删除「有 `sections` 时 `section=None`」的静默覆盖，改为断言二者不同时非空（保存层已拦，连接器 fail-closed 兜底）。
- `services/scheduled_archive_connectors.py`：白名单改为派生 + `_ARCHIVE_EXTRA`；`narrow` 键给出可执行拒绝文案。
- `web/app.py`：`capabilities.fieldSpecs`、`sourceInfo.scopeProposal` 下发；`_MAPPING_DISCOVERY_RULE_FIELDS[("tdc","data_model")]` 改为 `match_keys_from(D5_FIELD_SPECS)` 中 discovery 相关的子集（保持现有集合不变，用测试锁定）。

**验收**：现有测试全绿；新增测试见 §6；存量绑定 collect 结果逐行一致（同一快照前后对比）。
**回滚**：回退该提交；`match_rule_json` 从未被改写，无需数据回滚。

### 阶段 3：前端收敛（向导 / 高级设置 / 摘要）

**改哪些文件**

- 新增 `plugins/project_overview/static/deliverable/field-specs.js`（纯 ES module，无依赖）：`fieldsFor(capabilities, surface, rule)`（含 `show_if_set` 判定）、`defaultsFor(capabilities, sourceInfo)`、`labelFor(capabilities, key)`。
- `plugins/project_overview/static/deliverable/policy-logic.js`：`bindingInitialValues` / `buildPolicyPayload` 在存在 `capabilities.fieldSpecs` 时用 `fieldsFor(..., "advanced")`，否则走原 `matchFields`（其他交付物不受影响）；`buildPolicyPayload` **保留未渲染的已存键**（修 R4）。
- `plugins/project_overview/static/deliverable/policy.js`：仅改 `kind.isDataModel` 分支——删「责任部门」框，范围区遍历 `fieldsFor(caps, "wizard", rule)`；渲染存量条件 chip 与「采用建议」按钮（把 `scopeProposal.rule` 合入表单值，不自动保存）。NCR 分支不动。
- `plugins/project_overview/static/details/sync-settings-logic.js`：有 `describe_match_rule` 结果时直接渲染（需要现场取证：明细列表载荷是否已带每个交付物的 capabilities；若无，由后端在明细载荷里附 `matchRuleDisplay`，前端不再查字典）；`FILTER_LABELS` 仅作为其他交付物的兜底。

**验收**：D5 向导只出现「科室范围」+（存量时）条件 chip；高级设置无重复框；摘要无英文键名；SOR/NCR/EWO/PAA 渲染快照不变。
**回滚**：`policy-logic.js` 有 `fieldSpecs` 缺省分支，后端暂停下发 `fieldSpecs` 即可整体回退到旧渲染。

---

## 6. 验收与测试清单

### 后端

| 用例 | 位置 |
| --- | --- |
| 派生 `filterKeys` / `matchKeys` 与阶段 2 前字面量相等 | `tests/test_project_status_contracts.py`（新增）；原 `test_declared_filter_keys_match_connector_consumption` 不改，继续强制 upstream 键改变过滤器 |
| `role="narrow"` 的键单独出现**不改变**上游过滤器（反向锁定，防止有人把 `sections` 加进 filterKeys） | `tests/test_project_status_contracts.py` |
| 保存：`section`+`sections` 同时非空 → 拒绝；`section` 新值 → 拒绝；`section` 保持原值或清空 → 通过 | `tests/test_project_status_data_model_sections.py` |
| 保存：存量 `{department: 车体工程}` 原样回存 → 规则与签名不变 | 同上 |
| collect：`sections` 收窄走 `resolve_section`；`BE 车身科` 归入 `车身科`；`非车体科`、`车体科/内饰科` 落未归集 | 同上（已有用例保留） |
| collect：整批缺科室列 → raise 并保留上次结果 | 同上（已有） |
| discovery 与 collect 同一收窄函数、同一键集 | 同上（已有「发现收口」，补键集等价断言） |
| `propose_scope_migration`：department-only → 建议 sections；section-only → 建议归集后的 sections；其它 → None；函数不写库 | `tests/test_project_status_data_model_sections.py` |
| 归档：`sections` 出现 → 拒绝且文案含「科室范围」；`department`/`section` 存量配置仍可跑；派生白名单 == 旧字面量 | 新增 `tests/test_scheduled_archive_scope_keys.py` |
| `describe_match_rule`：标签、角色、顺序；未知键带出不丢 | `tests/test_project_status_contracts.py` |
| NCR `sectionScope` 只声明不查询 | `tests/test_project_status_section_scope.py`（不改，必须保持绿） |

### 前端

| 用例 | 位置 |
| --- | --- |
| `field-specs.js` 纯逻辑：`fieldsFor` 的 `surfaces` / `show_if_set` / `deprecated` 判定；`defaultsFor` 取 `sectionPresets` | 新增 `tests/test_plugin_overview_field_specs.py`（node） |
| `buildPolicyPayload` 保留未渲染的已存键（R4） | `tests/test_plugin_overview_data_model_sections.py` |
| 无 `fieldSpecs` 时行为与旧版逐字段一致 | 同上 |
| 向导渲染：D5 无「责任部门」；有 `data-wizard-field="sections"`；存量 department 显示 chip 与迁移按钮；点按钮不触发保存请求 | `tests/test_plugin_overview_wizard_sections.py`（VM + 桩） |
| 向导渲染：SOR/NCR 不出现 `sections`（已有，保持） | 同上 |
| 版本不一致提示出现/不出现 | 同上 |
| 摘要：无英文键名；角色标记正确 | 新增对 `sync-settings-logic.js` 的 node 用例 |
| 所有改动的 `.js` 通过 `node --check` | 现有 node 语法检查流程 |

---

## 7. 风险与反例（静默少算 / 多算）

| # | 情形 | 后果 | 阻断 |
| --- | --- | --- | --- |
| R1 | 存量绑定 `department=车体工程`，同科室人员挂在「技术中心」 | 少算（**当前正在发生**） | 向导存量 chip + 漏人数（§3.4 取证结果）+ 一键迁移；不自动改（约束 5） |
| R2 | 单值 `section` 发上游，按原始名全等过滤 | 少算：`BE 车身科`、`结构工程科` 等历史名不归集 | `section` 停用、不可新设；迁移建议转为归集后的 `sections` |
| R3 | `section` 与 `sections` 同时存在，连接器静默丢弃 `section` | 用户以为两层条件，实际只有一层 → 多算 | 保存层互斥校验；连接器改为断言 |
| R4 | 高级设置只回写 `matchFields` 里的键，保存时丢掉 `sections` | 范围被清空 → 多算 | §3.4 取证；`buildPolicyPayload` 保留未渲染键；高级设置渲染 `sections` |
| R5 | 去掉上游部门后抓取量变大，分页/导出截断 | 少算 | 先完成 §3.4 的上限取证；依赖已有完整性校验 raise（约束 3）；迁移按钮在取证完成前可先不开放 |
| R6 | 行科室值归集不到（未归集）被丢弃 | 少算且无感知 | 现有 `tdc_section_narrowed` 计数进入同步结果，摘要显示「未归集 N 行」；未归集不 raise（属业务事实），但必须可见 |
| R7 | 部分行缺科室列（未达到整批缺失） | 少算且无感知 | 同 R6，摘要显示「缺科室 N 行」 |
| R8 | 用户在别处修改归集规则，D5 范围随之变化，绑定未重新保存 | 少算/多算，且看似违背约束 5 | 归集规则本身是显式用户操作；在同步快照证据里记录归集规则指纹（不进配置签名，避免误报范围变化），摘要显示「按 X 时的归集规则」 |
| R9 | 前端新、后端旧（或反之）：向导提交 `sections`，旧后端不认 | 保存失败或条件被忽略 | 阶段 1 的 `contractVersion` 对齐提示 |
| R10 | 归档按上游原始范围存档，看板按 `sections` 收窄，两边数字不一致 | 用户误判为少算/多算 | 归档明确拒绝 narrow 键；摘要对归档标注「上游原始范围」 |

---

## 8. 不要做的事

1. **不要让上游 TDC 接收多值科室**，也不要恢复「只选一个科室时自动走上游」：上游不做归集，失败方式就是静默少算。
2. **不要把 `sections` 或任何 narrow / declare 键放进 `filterKeys`**：派生函数按 `role` 过滤，并用反向测试锁定。
3. **不要改 `match_rule_json` 的存储结构**（嵌套分组），也不要写批量迁移脚本自动改存量绑定。
4. **不要重写向导或引入表单引擎/构建链**：只改 D5 分支的范围区，其他分支与 NCR 不动。
5. **不要在连接器里读 `app_settings` 获取归集规则或迁移建议**：归集规则继续由 runner 注入，迁移建议在 `web/app.py` 计算后下发。
