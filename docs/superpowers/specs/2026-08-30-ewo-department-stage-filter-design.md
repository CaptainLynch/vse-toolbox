# EWO 科室与流程阶段筛选设计

## 目标

修正 EWO 项目状态同步范围与逾期统计口径：默认只同步车身科、车体科、外饰科、内饰科、车体架构集成科五个科室；统一 EWO 阶段为 `open`、`draft1`、`draft2`、`edit1`、`edit2`、`proc`、`impl`、`close`；`open` 默认不计入统计，`close` 视为流程终点且不逾期，其余未关闭阶段按截止日期判定逾期；交付明细支持科室和阶段筛选。

## 选定方案

采用“上游 EWO 查询过滤 + 本地显式阶段模型”。同步连接器在 Aras 查询层使用受控的五科室并集条件，避免先拉取全量后本地丢弃。分析缓存增加独立的 `source_stage` 字段，与通用 `source_status` 解耦；EWO 的 `state` 经规范化后写入该字段。未知阶段保留原始状态并进入待处理路径，不猜测映射。

## 领域规则

```text
EWO_DEFAULT_DEPARTMENTS = 车身科、车体科、外饰科、内饰科、车体架构集成科
EWO_STAGES = open、draft1、draft2、edit1、edit2、proc、impl、close
EWO_ACTIVE_STAGES = draft1、draft2、edit1、edit2、proc、impl
EWO_TERMINAL_STAGE = close
EWO_IGNORED_STAGE = open
```

- 未指定科室的 EWO 同步规则自动使用默认五科室；不得退化为全科室查询。
- 明确指定科室时必须经过白名单校验。
- `open` 默认排除，不计入总数、逾期数和默认明细列表；可以通过阶段筛选显式查看。
- `close` 视为完成，不判定 `overdue`、`due_soon` 或缺少截止日期提醒。
- `draft1` 至 `impl` 按 `planned_date` 判定逾期、临近到期和缺少截止日期。
- 未知阶段不进入正常阶段统计，保留原始 `source_status` 并形成待处理证据。

## 数据与 API

`project_status_analysis_items` 增加可空的 `source_stage TEXT` 字段，初始化与迁移必须幂等。旧缓存中的该字段为空，下一次 EWO 同步重新填充，不对历史值进行静默推断。

扩展现有接口：

```text
GET /api/project-status/deliverables/<deliverable_id>/analysis/items
    department=<规范化科室，可选>
    stage=<all 或 EWO_STAGES，可选>
```

- 未传 `stage` 时，EWO 默认排除 `open`。
- `department` 和 `stage` 必须同时作用于列表、总数和分页。
- 返回项新增 `stage` 字段，保留 `status` 兼容现有消费者。
- 非 EWO 交付物继续使用现有通用状态逻辑，`source_stage` 可为空。

## 模块职责

- `services/project_status_connectors.py`：构造 EWO 默认/显式科室过滤器，保持同步连接器边界。
- `services/aras_crawler.py`：沿用 EWO `rsp_department` 查询字段和多值条件生成逻辑。
- `services/project_status_deliverable_analysis.py`：阶段别名解析、缓存字段填充、阶段化统计与逾期判定。
- `core/db_manager.py`：缓存字段迁移、写入、阶段过滤查询及计数。
- `web/app.py`：解析和校验 `department`、`stage`，序列化阶段字段。
- `web/static/app.js` / `web/templates/dashboard.html` / `web/static/style.css`：交付明细筛选器、阶段列和状态样式。

## 测试与验收

覆盖默认五科室 AML、显式科室白名单、空配置拒绝全量、八阶段规范化、`open` 排除、`close` 不逾期、活动阶段日期逾期、未知阶段待处理、API 组合筛选、分页一致性、前端控件与阶段列，以及 TDC 不可访问不阻断 EWO 的回归场景。

不得改变 TDC 登录、查询和契约；不得新增依赖；不得将凭据或敏感上游响应写入日志、数据库或 API。
