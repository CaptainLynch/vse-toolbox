# 数模审批流程自动/手动更新试点 — 架构探索与决策记录

> 状态：架构评审完成，阶段 1 已实施并通过回归测试。首页 VPI-T2「数模审批流程」
> 已具备手动/混合/自动策略配置、字段归属、审计与冲突保护；权威来源为 TDC 数模报表。
> 因外部稳定编号与真实字段映射尚未确认，自动执行保持关闭，进入映射发现阶段。

## 0. 试点范围与已确认前提

- 试点交付物：`VPI-T2-D5`「数模审批流程」（当前：已逾期，82%，负责人赵岩，
  计划 2026-08-08，备注"逾期 5 天"，来源标签"内网"）。证据：`core/db_manager.py:233`。
- 权威来源：TDC 数模报表（TDC 3D 数模设计审核流程报表），对应现有
  `services/tdc_crawler.py` 的 data_model 契约。
- 已确认（来自 `DELIVERABLE_UPDATE_MODES_IMPLEMENTATION_PLAN.md` §11.1）：
  1. 试点为"数模审批流程"；
  2. 自动来源允许修改负责人、计划完成日期和风险备注，但必须经过字段映射、
     差异预览、审计和人工覆盖保护；
  3. 外部稳定编号/流程 ID/筛选键尚未确认 → 必须先做"映射发现模式"（§11.2）；
  4. 无人值守认证候选为 Windows Credential Manager（§11.4），尚未批准。

## 1. 现状证据清单（工作区为基准，非 HEAD）

### 1.1 首页 VPI-T2 数据链路（现有手动更新已完整）

| 层 | 位置 | 职责 |
|---|---|---|
| 模板 | `web/templates/dashboard.html:42-115` | 状态总览（只读）+ 交付物明细（8 列表格、行内展开） |
| 读取 | `web/static/app.js:690-710` `loadProjectOverview` | `GET /api/project-status?phase=VPI-T2` |
| 明细渲染 | `app.js:558-606` `renderDeliverableDetails`；`:487-556` `toggleDeliverableDetail` | 只读明细含"数据来源""数据更新时间" |
| 编辑会话 | `app.js:884-916` `startDeliverableEdit`；`:840-882` `renderDeliverableEditForm`；`:918-954` 校验；`:1023-1076` `saveDeliverableChanges` | 草稿隔离、保存/取消、失败保留、重复提交保护 |
| API 读取 | `web/app.py:1374-1388` | GET，`Cache-Control: no-store` |
| API 更新 | `web/app.py:1390-1433` | PATCH `/api/project-status/deliverables/<id>`，`updatedAt` 乐观锁，409 冲突 |
| 校验 | `web/app.py:1056-1123` `_validate_project_status_update` | status/owner/plannedDate/actualDate/progress/note；状态枚举 `_PROJECT_STATUS_VALUES`（`app.py:953`） |
| 序列化 | `web/app.py:962-1040` `_project_status_payload` | `source` 目前只是展示标签（`app.py:982`），无外部键/映射/游标 |
| 存储 | `core/db_manager.py:264-310` `update_project_status_deliverable` | 白名单列映射 + `updated_at` 条件更新 + 阶段时间戳同步 |

结论：手动更新能力完备，可直接作为统一人工入口（计划 §1 结论一致）。

### 1.2 TDC 数模报表契约（权威来源现状）

- 路由（`services/tdc_crawler.py:35-42`）：
  - 列表 `GET /uwf/procuwfpe3ddigitalmodeldesignreview/list`
  - 导出 `GET /uwf/procuwfpe3ddigitalmodeldesignreview/export`（官方 XLSX）
  - 页面 referer `/tpc/dataAdmin/dataModelDesign/index`
- 分页响应 `{code, msg, data: {records, total, pages, current, size}}`
  （`tdc_crawler.py:420-473`、`:570-693`）。
- 查询筛选（`TDCDataModelFilters`，`tdc_crawler.py:123-149` → `to_params`）：
  `incident`(流水号) / `applicant`(申请人) / `superDepartment`(部门) /
  `department`(科室) / `requestDateStart|End`(申请日期) / `projectModel`(项目车型) /
  `partNumber`(零件号) / `modelNumber`(模型编号)。
- 记录身份键（`_row_identity`，`tdc_crawler.py:1086-1099`）：data_model 优先
  `formId`、`incident`、`documentNo`；粒度为 `workflow`（流程粒度）。
- 安全边界（已实现）：主机 allowlist `tdc.sgmw.com.cn`（`web/app.py:88`）、
  password 模式强制 HTTPS 且禁止与 secret header/cookie 混用
  （`web/app.py:808-870`）、登录页 HTML 拒绝（`tdc_crawler.py:630-637`）、
  请求/响应头与人员查询参数脱敏（`tdc_crawler.py:996-1017`）、XLSX 签名校验。
- 认证（`services/tdc_auth.py:126-351`）：`TDCPasswordAuthClient.login(username,
  password)` 走企业 OIDC 授权码流程，返回已认证 `Session`（Authorization header），
  密码引用在请求编码后立即清空（`:228-231`），不持久化任何凭据。
  Windows 原生传输 `services/windows_http.py`（WinHTTP + Schannel）可作为
  无 requests 依赖时的 Session 工厂（`tdc_auth.py:503-506`）。
- Web 入口（`web/app.py:1727-1752`）：`POST /api/tdc/data-model/{query,crawl-all,
  export}`；复用 `_build_tdc_client_from_payload`（凭据当次提供）。
- CLI 入口（`main.py:830-934` `_run_tdc_report`）：交互式查询/抓取/导出，
  凭据当次输入，诊断报告落 `data/diagnostics`。

### 1.3 尚缺的能力（与计划 §2.2 一致，探索后确认无遗漏）

- 无调度器/任务队列/常驻进程（`main.py` 是交互菜单，无 argparse 子命令）。
- 无可安全持久化的 Aras/TDC 登录会话；Web 请求要求用户当次提供认证。
- 无同步配置、外部对象 ID、字段映射、来源优先级、同步历史、失败重试状态。
- 无 `project_status_update_bindings` / `field_authority` / `audit` 表（全库 grep
  无相关代码，仅计划文档）。
- 数模报表**记录字段名**（审批状态、当前节点、完成时间等）在仓库内未被证明：
  测试 fixture 只使用 `{"formId","incident"}`（`tests/test_tdc_crawler.py:143`），
  `爬虫源文件/` 中 7z 集合无法在当前环境解包（无 7z/py7zr），页面 view-source
  是 SPA 外壳不含契约 token。→ 字段映射必须靠"映射发现"实测确认，
  与计划 §11.2 边界一致。

## 2. 目标架构（计划 §3 方案 C 的精化）

```
┌──────────────┐   PATCH(手动)   ┌─────────────────────────────┐
│ 浏览器前端    │ ──────────────▶ │ web/app.py 路由（薄适配层）   │
│ 明细页/行展开  │ ◀────────────── │  校验 + 乐观锁 + 审计触发      │
└──────────────┘                 └──────────────┬──────────────┘
                                               │ 统一领域服务
                                      ┌────────▼───────────────┐
                                      │ ProjectStatusUpdateService │
                                      │ 字段归属 / 差异计算 / 冲突 / │
                                      │ 审计 / 事务写入（唯一写入口） │
                                      └────────┬───────────────┘
                          ┌───────────────────┼───────────────────┐
              ┌───────────▼──────────┐  ┌─────▼─────┐  ┌──────────▼──────────┐
              │ TDC connector v1     │  │ db_manager│  │ sync runner (CLI)   │
              │ (只读候选标准化)       │  │ 数据访问   │  │ run_once/租约/重试   │
              └───────────┬──────────┘  └───────────┘  └──────────┬──────────┘
                          │                                        │ Windows Task
              TDCCrawlerClient + TDCPasswordAuthClient              │ Scheduler 周期触发
              （凭据：Web=当次提供；定时=凭据引用解析）
```

核心原则（继承计划 §3-C）：

1. 外部连接器只产生标准化候选更新，不直接写首页表。
2. 所有写入（手动/同步）经统一服务，执行字段校验、来源权限、乐观锁、审计、
   事务写入。
3. 手动优先：自动任务不得静默覆盖人工锁定字段。
4. 失败保留最后一次成功数据，页面显示"同步失败/数据可能过期"，不造假成功。
5. 运行器与 Flask 解耦：CLI `--once`，由 Windows Task Scheduler 调用。
6. 凭据不落 SQLite/前端/日志；定时模式凭据引用（Windows Credential Manager）
   单独批准后才启用。

## 3. 模块边界与文件归属

| 文件 | 归属 | 职责 |
|---|---|---|
| `services/project_status_updates.py` | 新增 | `ProjectStatusUpdateService`：规范化命令、字段归属判定、差异计算、乐观锁写入、审计落库；`apply_manual_update` / `build_proposed_update` / `apply_sync_update` / `record_field_lock` / `release_field_lock` |
| `services/project_status_connectors.py` | 新增 | `ProjectStatusConnector` 协议：`fetch(binding, credentials) -> ConnectorSnapshot(records, external_version, fetched_at)`；`TDCDigitalModelConnector` v1 包装 `TDCCrawlerClient`；字段标准化与候选提取；歧义/零条/键变化 → `needs_attention` |
| `services/project_status_sync_runner.py` | 新增 | `run_once(...)`：枚举启用绑定 → 租约获取（原子 UPDATE 条件）→ 连接器抓取 → 预览 → 按字段归属应用 → 更新 sync_state/游标/审计；超时、重试退避、部分失败与汇总；不在 Flask 启动时建线程 |
| `core/db_manager.py` | 修改 | 仅新增数据访问：绑定/字段归属/审计/运行状态表的 CRUD 与原子写入；保留现有公开方法签名 |
| `web/app.py` | 修改 | 新增策略/预览/应用/审计只读路由；现有 GET/PATCH 保持契约；PATCH 改走统一服务（行为不变，审计+人工锁由服务内部完成） |
| `web/static/app.js`、`dashboard.html`、`style.css` | 修改 | 明细页新增更新方式/同步状态/最后成功更新列；行展开区新增"立即同步/查看差异/更新记录"；状态总览保持纯只读 |
| `main.py` | 修改 | 新增 `project-status-sync --once` 子命令入口（检测 argv 前缀，不破坏交互菜单）；复用 `_ask_tdc_*` 交互作发现模式 CLI |
| `core/config.py` | 不改 | 无新敏感默认值；运行参数走 CLI 参数/绑定配置 |

约束：`core/` 不 import flask；`services/` 不 import flask；路由只做序列化。
web/app.py 是唯一允许 import flask 的文件（`web/app.py:5-9` 架构约束保持）。

## 4. 数据模型（计划 §5 精化）

全部新增表走 `TABLE_DEFINITIONS` 追加 + `PRAGMA user_version` 迁移（db_manager
当前无迁移框架，`core/db_manager.py:32-133`）；迁移前备份 `data/vse_toolbox.db`。

### 4.1 `project_status_update_bindings`

```sql
CREATE TABLE IF NOT EXISTS project_status_update_bindings (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    deliverable_id   TEXT NOT NULL UNIQUE,          -- VPI-T2-D5
    mode             TEXT NOT NULL DEFAULT 'manual'
                     CHECK (mode IN ('manual','automatic','hybrid')),
    source_type      TEXT NOT NULL DEFAULT 'tdc'
                     CHECK (source_type IN ('feishu','aras','tdc','intranet','none')),
    external_key     TEXT,                          -- 确认后的 formId/incident/documentNo
    match_rule_json  TEXT NOT NULL DEFAULT '{}',    -- 版本化筛选条件（固定字段白名单）
    mapping_json     TEXT NOT NULL DEFAULT '{}',    -- 版本化字段映射配置
    enabled          INTEGER NOT NULL DEFAULT 0,
    interval_minutes INTEGER,
    credential_ref   TEXT,                          -- 凭据引用名，不是凭据本身
    last_attempt_at  TEXT, last_success_at  TEXT,
    sync_state       TEXT NOT NULL DEFAULT 'idle'
                     CHECK (sync_state IN ('idle','running','success','failed','needs_attention')),
    last_error_type  TEXT, last_error_message TEXT,
    cursor_json      TEXT,                          -- 来源版本/游标
    lease_token      TEXT, lease_expires_at TEXT,   -- 运行器租约
    created_at       TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (deliverable_id)
        REFERENCES project_status_deliverables(id) ON DELETE CASCADE
);
```

### 4.2 `project_status_field_authority`

```sql
CREATE TABLE IF NOT EXISTS project_status_field_authority (
    deliverable_id TEXT NOT NULL,
    field_name     TEXT NOT NULL,                   -- status/owner/planned_date/actual_date/progress/remark
    authority      TEXT NOT NULL
                   CHECK (authority IN ('manual','automatic')),
    source_type    TEXT,
    locked_at      TEXT,
    updated_at     TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (deliverable_id, field_name),
    FOREIGN KEY (deliverable_id)
        REFERENCES project_status_deliverables(id) ON DELETE CASCADE
);
```

### 4.3 `project_status_update_audit`

```sql
CREATE TABLE IF NOT EXISTS project_status_update_audit (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    deliverable_id     TEXT NOT NULL,
    trigger_type       TEXT NOT NULL
                       CHECK (trigger_type IN ('manual','sync_now','scheduled')),
    source_type        TEXT,
    external_version   TEXT,
    proposed_changes_json TEXT NOT NULL DEFAULT '{}',  -- 已脱敏
    applied_changes_json TEXT NOT NULL DEFAULT '{}',   -- 已脱敏
    skipped_fields_json  TEXT NOT NULL DEFAULT '{}',   -- 人工锁定跳过的字段及原因
    result             TEXT NOT NULL
                       CHECK (result IN ('applied','skipped','conflict','failed')),
    error_summary      TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (deliverable_id)
        REFERENCES project_status_deliverables(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_ps_audit_deliverable ON project_status_update_audit(deliverable_id, created_at);
```

审计表禁止保存密码、Cookie、Authorization、完整原始响应或敏感请求头
（计划 §5 末尾要求）；写入前经 `core/redaction.redact_sensitive_text` +
`web/app.py:_safe_rows` 同款清理。

### 4.4 迁移与回滚

- `PRAGMA user_version` 从 0 → 1（幂等，`INSERT OR IGNORE` 式绑定缺省不创建；
  未配置绑定前一切行为与现状一致）。
- 回滚：功能开关关闭自动同步 → 所有记录退回 manual（不删行，仅 `enabled=0`
  或删除绑定行）；删除新增表不触碰 `project_status_deliverables`；`/api/overview`
  与本功能无依赖（`web/app.py:392-410` 只读 projects/deliverables/feishu_tasks）。

## 5. 字段归属与冲突模型（试点默认值）

- 默认全部字段 `manual`（与现状完全一致，不改变任何行为）。
- 用户把某字段切到 `automatic` 后，自动运行器可更新；切到 `hybrid` 时自动更新
  未锁定字段，人工保存过的字段进入 `manual`（锁定）并记录 skipped 原因。
- 显式"恢复自动"解除字段锁（`PATCH update-policy`）。
- 自动写入携带外部版本/游标；写前重新读取当前 `updated_at` 与绑定配置重算差异，
  版本变化 → `conflict`，绝不覆盖并发人工保存。
- 试点建议映射（待实测确认，计划 §11.3）：
  - 权威外部键：优先 `formId`（跨页稳定）或 `incident`；一个交付物对应多条流程
    时需用户确认聚合范围（如按项目车型+零件号筛选后取最新一条）。
  - 状态：TDC 审批状态/当前节点 → 四态枚举（已完成/进行中/待审批/已逾期），
    映射表必须用户逐项批准。
  - 进度：TDC 无真实百分比时，不得推算；由用户批准节点权重后按审批节点计算。
  - 实际完成日期：仅当 TDC 提供明确完成时间。
  - 负责人：申请人/当前审批人/业务负责人三选一，用户确认。
  - 计划完成日期：TDC 无明确计划日期时保持人工字段。
  - 风险备注：非敏感字段摘要，长度上限，与现有 1000 字上限一致
    （`web/app.py:1078-1081`）。

## 6. API 契约（新增；现有路径不变）

| 方法/路径 | 用途 | 关键约束 |
|---|---|---|
| `GET /api/project-status`（不变） | 读取 | 响应新增每行 `updatePolicy` 摘要（mode/syncState/lastSuccessAt），属增量字段 |
| `PATCH /api/project-status/deliverables/<id>`（不变） | 手动保存 | 走统一服务；服务端记 `trigger_type=manual`，按实际修改字段建人工锁；请求/响应结构不变 |
| `GET /api/project-status/deliverables/<id>/update-policy` | 读策略 | 绑定 + 字段归属 + 最近审计摘要 |
| `PATCH /api/project-status/deliverables/<id>/update-policy` | 写策略 | 白名单：`mode`、`source_type`、`external_key`、`match_rule_json`、`mapping_json`、`enabled`、`field_authority`；拒绝任意 URL/主机 |
| `POST /api/project-status/deliverables/<id>/sync-preview` | 差异预览 | 复用 `_build_tdc_client_from_payload`（当次认证）；只返回清理后候选 + 建议差异，**不落库** |
| `POST /api/project-status/deliverables/<id>/sync-apply` | 应用预览 | 仅对已确认绑定；乐观锁 + 字段归属；歧义/零条 → 422 + `needs_attention` |
| `POST /api/project-status/sync/run` | 触发一次运行 | 只对已配置启用绑定；凭据引用解析失败 → 明确错误，不写业务数据 |
| `GET /api/project-status/updates?deliverableId=...` | 审计 | 清理后摘要（result/trigger/时间/错误），分页上限固定 |

错误形态沿用 `{ok:false, error:{type,message,fields?}}`（`web/app.py:417-419`）；
所有新路由 `Cache-Control: no-store`。

映射发现模式复用现有 `POST /api/tdc/data-model/query`（当次认证 + 候选筛选），
新增"确认绑定"流程：连续两次查询得到一致目标且无歧义后，才允许保存
`external_key + match_rule_json` 并启用 preview；启用 apply 需用户单独确认
（计划 §11.2）。

## 7. 同步运行器（CLI，定时候选）

```text
python main.py project-status-sync --once [--deliverable VPI-T2-D5] [--dry-run]
```

- `run_once` 流程：读启用绑定 → 原子租约（`lease_token` 随机值 + 过期时间，
  `UPDATE ... WHERE sync_state='idle'`）→ 连接器抓取（超时 30s 与
  `tdc_crawler.py` 一致）→ 标准化候选 → 差异预览 → 按字段归属应用 →
  更新 sync_state/游标/审计；异常 → `failed` + 清理后错误摘要，保留最后一次
  成功数据（不 UPDATE 业务行）。
- 重试退避与单次超时阈值待用户确认（计划 §11.5-5）。
- 幂等：同一外部版本重复处理不产生重复修改（audit 去重键：
  `deliverable_id + trigger + external_version` 唯一约束或应用层检查）。
- 定时触发：Windows Task Scheduler 调用 CLI；凭据经 `credential_ref` 从当前
  Windows 用户的凭据库读取（计划 §11.4），未批准前定时模式保持 disabled。
- 不做 Flask 内常驻线程（计划 §3-B 否决理由成立：无租约/锁/重试表、生命周期耦合）。

## 8. 前端变更（试点可见部分）

- 明细表新增列：`更新方式`（手动/自动/混合，未配置显示"未配置"）、
  `同步状态`（成功/失败/注意/最后成功时间紧凑显示）；`数据来源` 保留。
- 行展开区新增操作（仅对已配置行）：`立即同步`（preview → 差异确认 → apply）、
  `更新记录`（审计列表）。差异预览以只读表格呈现，应用前需再次确认。
- 失败态：行内紧凑错误 + 上次成功时间；状态总览继续使用最后一次成功保存数据，
  不放置自动写入控件（计划 §4.1 末尾）。
- 编辑表单对 `automatic` 字段显示"由 TDC 自动更新"只读提示；手动修改该字段
  会提示"将切换为人工锁定"。
- 技术约束不变：`textContent`/`createElement`，无 `innerHTML` 拼接、无
  `console.log`、无新框架/CDN；事件只绑定一次；状态总览保持无输入控件。

## 9. 测试与验收（试点）

新增测试文件（建议）：

- `tests/test_project_status_updates.py`：手动/自动/混合归属；字段锁跳过；
  差异计算；并发冲突（乐观锁）；审计脱敏（无 cookie/token/password）；幂等。
- `tests/test_project_status_connectors.py`：FakeSession 驱动 TDC connector；
  候选标准化；零条/多条歧义/键变化 → needs_attention；敏感响应字段清理。
- `tests/test_project_status_sync_runner.py`：假连接器 + 临时库验证租约、
  超时、重试、部分失败、回滚、失败保留上次成功值。
- `tests/test_project_status_policy_api.py`：策略读写白名单；preview 不落库；
  apply 冲突 409；审计只读脱敏；`sync/run` 仅限已配置绑定。
- `tests/test_project_status_frontend.py`：模板列/控件结构、无编辑控件泄漏到
  状态总览、JS 语法（`node --check` 作 CI 步骤）。

回归保护（既有测试必须全绿，行为不变）：

- `tests/test_project_status_api.py`（读取/手动更新/409/里程碑）
- `tests/test_deliverables_web.py`（目录真实性 + TDC web 契约）
- `tests/test_tdc_crawler.py`、`tests/test_tdc_auth.py`、`tests/test_tdc_cli.py`
- `tests/test_overview_web.py`（概览结构 + `/api/overview` 契约不变）
- `tests/test_credential_safety.py`（凭据清理与脱敏护栏）

验收清单（计划 §9 + 试点细化）：

1. 现有手动编辑、校验、取消、保存、409 行为不变（测试锁定）。
2. manual 模式拒绝自动落库；automatic/hybrid 严格遵守字段归属。
3. 同一外部事件重复处理无重复修改。
4. 人工保存与自动任务并发无静默覆盖（版本变化 → conflict）。
5. 自动失败保留最后成功值并更新失败状态与清理后错误摘要。
6. 连接器固定 allowlist，不接受任意 URL；日志/审计无密码、Cookie、Token。
7. Flask 重启不丢失绑定、同步状态、游标、审计（SQLite 持久化）。
8. 桌面与移动端清晰区分更新方式、数据新鲜度、人工锁定字段与失败状态。
9. 独立运行器在测试库 + 假连接器下验证租约、超时、重试、部分失败、回滚。

## 10. 验证命令

```text
python -m py_compile web/app.py services/project_status_updates.py \
    services/project_status_connectors.py services/project_status_sync_runner.py main.py
node --check web/static/app.js
python -m pytest tests/test_project_status_api.py tests/test_deliverables_web.py \
    tests/test_tdc_crawler.py tests/test_tdc_auth.py tests/test_tdc_cli.py \
    tests/test_overview_web.py tests/test_credential_safety.py \
    tests/test_project_status_updates.py tests/test_project_status_connectors.py \
    tests/test_project_status_sync_runner.py tests/test_project_status_policy_api.py
```

沙盒注意：当前 DSH 文件沙盒对 pytest 的 tmp_path 基目录枚举返回
`PermissionError: [WinError 5]`（`.runtime/`、`.pytest_*`、`$env:TEMP` 下均复现），
属环境限制而非代码缺陷；实现阶段在沙盒外或可枚举目录下运行上述 pytest 命令。

## 11. 分阶段实施顺序（试点）

1. **阶段 1（框架，行为不变）**：迁移（三张新表 + user_version）；统一服务接入
   现有 PATCH（只加审计/锁，不改契约）；前端"更新方式/同步状态"列（未配置态）。
   验收：全部既有测试绿。
2. **阶段 2（映射发现）**：确认绑定流程（复用 TDC query，连续两次一致）；
   字段映射配置；`sync-preview`/`sync-apply`；字段锁与"恢复自动"。
   验收：试点行手动/自动混合更新闭环，审计可查，冲突可复现。
3. **阶段 3（定时）**：`run_once` CLI + 租约/重试；Windows Task Scheduler 接线；
   凭据引用解析（Windows Credential Manager）单独安全评审后启用。
4. **阶段 4（扩展）**：稳定后逐项扩展其余交付物；每项单独确认外部键、
   状态映射、进度算法与失败语义。

## 12. 剩余决策（来自计划 §11.5，试点相关）

1. 批准 `manual / automatic / hybrid` 三模式及"人工字段优先、显式恢复自动"
   冲突规则。
2. "自动更新"范围：是否同时包含"立即同步"与 Windows Task Scheduler 定时同步。
3. 无人值守认证：是否批准 Windows Credential Manager；受控环境变量是否仅限
   开发/试点。
4. 映射发现是否允许以只读查询 + 人工选择候选完成（计划建议允许）。
5. 自动运行频率、失败重试次数、单次超时和数据过期阈值。
6. TDC 状态映射与进度算法需在看到真实候选字段后再次确认。

## 13. 探索中发现的风险（新增，超出原计划）

1. `爬虫源文件/TDC_Crawler_Collection.7z` 含疑似 TDC 抓取证据（4.4MB），
   当前环境无法解包；实现前应人工解包核对记录字段名，缩短映射发现周期。
2. `main.py` 当前无 argparse 子命令机制（纯交互菜单）；`project-status-sync`
   入口需在 `main()` 顶部做 argv 检测，避免破坏菜单流程（`main.py:1300`）。
3. `services/__init__.py` 只导出 `IntranetScraper/FeishuImapParser/OfficeToolbox`；
   新服务模块建议显式加入 `__all__` 或保持延迟导入，避免启动开销与循环导入。
4. 绑定表外键引用 `project_status_deliverables(id)`；该表主键是 TEXT
   （`VPI-T2-D5`），外键类型匹配无问题，但删除/重建种子数据时需 `ON DELETE
   CASCADE` 语义确认（当前种子用 `INSERT OR IGNORE`，不会重建）。
5. `simulated_today`（`core/db_manager.py:97`）是固定模拟日期；自动同步的
   "逾期"判定与页面红线保持一致时，需明确以模拟日期还是真实日期计算，
   避免状态不一致（建议：展示沿用 `simulated_today`，审计记录真实时钟）。
