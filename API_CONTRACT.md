# VSE TOOLBOX - 前后端接口契约

> 本文档定义前后端所有 API 的接口规范。前后端各自的 agent 都必须遵守此契约。
>
> **修改此文档需前后端双方确认。**

---

## 最后更新

- 版本：v1.3
- 更新时间：2026-06-12
- 状态：已确认（新增 timeline 及 milestone-rules 相关 API 端点，支持项目时间节点与里程碑评估联动）

---

## 1. 通用规范

### 1.1 基础信息

| 项 | 值 |
|----|----|
| 协议 | HTTP |
| 主机 | 127.0.0.1 |
| 端口 | 8002 |
| API 前缀 | `/api` |
| 静态文件 | `/` 托管前端 dist/ 目录 |

### 1.2 请求/响应格式

**请求**：
- GET：查询参数在 URL 中
- POST/PUT：JSON body，`Content-Type: application/json`
- 文件上传：`multipart/form-data`

**响应**：统一包装格式

```json
{
  "success": true,
  "data": {},
  "message": null
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| success | boolean | 操作是否成功 |
| data | any | 成功时的返回数据 |
| message | string \| null | 失败时的错误信息，成功时为 null |

### 1.3 HTTP 状态码

| 状态码 | 含义 | 场景 |
|--------|------|------|
| 200 | 成功 | 正常返回 |
| 400 | 参数错误 | 缺少必填字段、格式不正确 |
| 404 | 资源不存在 | 问题 ID 不存在 |
| 500 | 服务器内部错误 | 未捕获异常 |

### 1.4 分页规范

GET 列表接口统一分页参数：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| page | int | 1 | 页码，从 1 开始 |
| size | int | 20 | 每页条数，最大 100 |

分页响应格式：

```json
{
  "success": true,
  "data": {
    "items": [],
    "total": 142,
    "page": 1,
    "size": 20
  }
}
```

---

## 2. 问题追踪 API

### 2.1 获取问题列表

```
GET /api/issues?page=1&size=20&priority=P0&status=open&department=车身钣金
```

### 2.2 创建问题

```
POST /api/issues
```

### 2.3 更新问题

```
PUT /api/issues/{id}
```

### 2.4 删除问题

```
DELETE /api/issues/{id}
```

### 2.5 问题统计（KPI）

```
GET /api/issues/stats
```

---

## 3. 里程碑 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/milestones | 里程碑列表 |
| POST | /api/milestones | 创建里程碑 |
| PUT | /api/milestones/{id} | 更新里程碑 |
| DELETE | /api/milestones/{id} | 删除里程碑 |

---

## 4. Excel 工具 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/excel/merge | 多文件合并（multipart files） |
| POST | /api/excel/merge-same | 同结构拼接（multipart files） |
| POST | /api/excel/rename | 批量改名（JSON {folder,pattern,replacement}） |

---

## 5. PPT 生成 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/ppt/templates | 模板列表 |
| POST | /api/ppt/weekly | 生成周报（JSON {week_start?,project_name?,author?}） |
| POST | /api/ppt/deliverable | 生成交付物报告（JSON {deliverable_name,responsible?}） |

---

## 6. 爬虫 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/crawler/fetch | 抓取页面（JSON {url}） |
| POST | /api/crawler/table | 提取表格（JSON {url,xpath?}） |

---

## 7. 飞书邮件 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/feishu/mails | 邮件列表（?category=&is_read=&page=&size=） |
| POST | /api/feishu/sync | 同步邮件 |
| GET | /api/feishu/todos | 待办列表 |
| POST | /api/feishu/todo-toggle | 切换待办状态（JSON {id}） |

---

## 8. 文件下载

```
GET /api/download?path={file_path}
```

响应：二进制文件流，`Content-Disposition: attachment`

---

## 9. Dashboard 聚合 API

### 9.1 首页聚合数据

```
GET /api/dashboard/overview
```

**响应：**

```json
{
  "success": true,
  "data": {
    "total_issues": 42,
    "open_issues": 15,
    "closed_rate": 64.3,
    "high_risk_count": 3,
    "new_this_week": 8,
    "closed_this_week": 5,
    "milestone_progress": [
      {"name": "车身钣金合装", "percentage": 85, "category": "车身钣金"}
    ],
    "department_stats": [
      {"department": "车身钣金", "totalIssues": 12, "closedRate": 75}
    ],
    "trend": [{"date": "06-01", "count": 3}],
    "deliverable_counts": {"issues": 42, "ewo": 8, "tir": 15}
  },
  "message": null
}
```

### 9.2 交付物分类 CRUD

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/dashboard/deliverable-categories | 分类列表 |
| POST | /api/dashboard/deliverable-categories | 新增分类（JSON {id,name,icon?,sort_order?}） |
| PUT | /api/dashboard/deliverable-categories/{id} | 更新分类 |
| DELETE | /api/dashboard/deliverable-categories/{id} | 删除分类 |

### 9.3 布局 CRUD

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/dashboard/layouts?page_key=xxx | 获取指定页面的卡片布局 |
| PUT | /api/dashboard/layouts | 批量保存卡片布局（JSON {page_key,layouts[]}） |

---

## 10. EWO/NCR API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/ewo | EWO/NCR列表（?page=&size=&status=&severity=） |
| GET | /api/ewo/stats | EWO/NCR统计 |
| POST | /api/ewo | 创建（JSON {type?,title,description?,severity?,status?,department?,assignee?,raised_date?,target_date?}） |
| PUT | /api/ewo/{id} | 更新 |
| DELETE | /api/ewo/{id} | 删除 |

---

## 11. TIR API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/tir | TIR列表（?page=&size=&status=&category=） |
| GET | /api/tir/stats | TIR统计 |
| POST | /api/tir | 创建（JSON {title,description?,category?,status?,department?,assignee?,test_date?,result?}） |
| PUT | /api/tir/{id} | 更新 |
| DELETE | /api/tir/{id} | 删除 |

---

## 12. Excel 导入 API

### 12.1 造车问题 Excel 导入

```
POST /api/issues/import-excel
Content-Type: multipart/form-data
```

**请求**：`files` 字段（单个 Excel 文件）

**响应**：
```json
{
  "success": true,
  "data": {
    "created": 12,
    "updated": 3,
    "errors": ["第5行：责任科室为空"]
  },
  "message": null
}
```

### 12.2 EWO Excel 导入

```
POST /api/ewo/import-excel
```

### 12.3 TIR Excel 导入

```
POST /api/tir/import-excel
```

---

## 13. Lookup 自动关联 API

### 13.1 零件总成查询

```
GET /api/lookup/part-system?q=前保
```

**响应**：
```json
{
  "success": true,
  "data": [
    {"part_system": "前保险杠", "sub_system": "外饰系统"}
  ],
  "message": null
}
```

### 13.2 新增零件总成映射

```
POST /api/lookup/part-system
Content-Type: application/json

{"part_system": "前保险杠", "sub_system": "外饰系统"}
```

### 13.3 工程师查询

```
GET /api/lookup/engineer?q=张三
```

**响应**：
```json
{
  "success": true,
  "data": [
    {"name": "张三", "department": "车身科"}
  ],
  "message": null
}
```

### 13.4 新增工程师映射

```
POST /api/lookup/engineer
Content-Type: application/json

{"name": "张三", "department": "车身科"}
```

---

## 14. Settings API

### 14.1 获取全部设置

```
GET /api/settings
```

**响应**：
```json
{
  "success": true,
  "data": {
    "folder_issues": "C:/Users/xxx/issues",
    "folder_ewo": "C:/Users/xxx/ewo",
    "folder_ncr": "C:/Users/xxx/ncr",
    "folder_tir": "C:/Users/xxx/tir"
  },
  "message": null
}
```

### 14.2 更新单个设置

```
PUT /api/settings/{key}
Content-Type: application/json

{"value": "C:/Users/xxx/issues"}
```

---

## 15. Dashboard Overview 重写

`GET /api/dashboard/overview` 响应格式更新为：

```json
{
  "success": true,
  "data": {
    "milestone_progress": [
      {
        "name": "车身钣金合装",
        "percentage": 85,
        "actual_percentage": 80,
        "target_date": "2026-06-15",
        "actual_date": "2026-06-18",
        "category": "车身科"
      }
    ],
    "completion_pie": [
      {"name": "已关闭", "value": 27, "color": "#4ade80"},
      {"name": "进行中", "value": 10, "color": "#d4af37"},
      {"name": "待处理", "value": 5, "color": "#ff4d4d"}
    ],
    "department_bar": [
      {"department": "车身科", "total": 12, "closed": 9},
      {"department": "外饰工程科", "total": 8, "closed": 5}
    ],
    "deliverable_counts": {"issues": 42, "ewo": 8, "tir": 15}
  },
  "message": null
}
```

---

## 16. 时间轴 API

项目时间节点相关增删改查。

### 16.1 获取时间节点列表

```
GET /api/timeline
```

**响应：**
```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "name": "首台车身下线",
      "target_date": "2026-06-01",
      "actual_date": "2026-06-02",
      "description": "首台车身组装完成下线",
      "sort_order": 1,
      "status": "completed",
      "created_at": "2026-06-12T12:00:00",
      "updated_at": "2026-06-12T12:00:00"
    }
  ],
  "message": null
}
```

### 16.2 新增时间节点

```
POST /api/timeline
```

**请求：**
```json
{
  "name": "首台车身下线",
  "target_date": "2026-06-01",
  "actual_date": null,
  "description": "车身下线描述",
  "sort_order": 0,
  "status": "pending"
}
```

### 16.3 批量更新时间节点排序

```
PUT /api/timeline/reorder
```

**请求：**
```json
{
  "items": [
    {"id": 1, "sort_order": 1},
    {"id": 2, "sort_order": 2}
  ]
}
```

### 16.4 获取单个时间节点详情

```
GET /api/timeline/{node_id}
```

### 16.5 更新时间节点

```
PUT /api/timeline/{node_id}
```

**请求：**（支持局部更新）
```json
{
  "actual_date": "2026-06-02",
  "status": "completed"
}
```

### 16.6 删除时间节点

```
DELETE /api/timeline/{node_id}
```

---

## 17. 里程碑规则与自动评估 API

里程碑评估规则的配置，以及基于规则的自动化状态计算。

### 17.1 获取里程碑规则列表

```
GET /api/milestone-rules?timeline_node_id=1
```

### 17.2 新增里程碑规则

```
POST /api/milestone-rules
```

**请求：**
```json
{
  "name": "冲压件完成率",
  "timeline_node_id": 1,
  "category": "零件",
  "condition_type": "count_threshold",
  "condition_config": {
    "data_source": "issues",
    "count_field": "status",
    "count_value": "resolved"
  },
  "target_value": 80,
  "sort_order": 1,
  "is_active": true
}
```

**说明**：
- `condition_type` 支持：`manual`（人工维护）、`count_threshold`（数量占比阀值）、`status_match`（特定状态匹配）。
- `condition_config`：白名单表 `issues` / `ewo` / `tir`，且字段限制在 `status` / `priority` / `severity` / `type`。

### 17.3 里程碑评估结果列表

```
GET /api/milestone-rules/evaluations?timeline_node_id=1
```

**响应：**
```json
{
  "success": true,
  "data": [
    {
      "evaluation_id": 1,
      "rule_id": 1,
      "rule_name": "冲压件完成率",
      "timeline_node_name": "首台车身下线",
      "category": "零件",
      "condition_type": "count_threshold",
      "current_value": 0.85,
      "target_value": 80.0,
      "status": "completed",
      "notes": "系统自动评估通过",
      "evaluated_at": "2026-06-12T12:00:00"
    }
  ],
  "message": null
}
```

### 17.4 触发全量里程碑规则自动评估

```
POST /api/milestone-rules/evaluations/refresh
```

**响应：**
```json
{
  "success": true,
  "data": {
    "refreshed": 3
  },
  "message": null
}
```

### 17.5 更新单个评估记录（备注/状态）

```
PUT /api/milestone-rules/evaluations/{evaluation_id}
```

**请求：**
```json
{
  "notes": "人工确认通过",
  "status": "completed"
}
```

---

## 18. 变更记录

| 版本 | 日期 | 变更内容 | 确认 |
|------|------|----------|------|
| v1.0 | 2026-05-27 | 初始版本 | 已确认 |
| v1.1 | 2026-06-07 | 新增 dashboard/ewo/tir 端点，端口改为 8002 | 已确认 |
| v1.2 | 2026-06-07 | 新增 import-excel / lookup / settings 端点；dashboard/overview 重写 | 已确认 |
| v1.3 | 2026-06-12 | 新增 timeline 及 milestone-rules 相关 API 端点，支持时间轴与自动评估联动 | 已确认 |