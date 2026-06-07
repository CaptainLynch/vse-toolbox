# VSE TOOLBOX - 前后端接口契约

> 本文档定义前后端所有 API 的接口规范。前后端各自的 agent 都必须遵守此契约。
>
> **修改此文档需前后端双方确认。**

---

## 最后更新

- 版本：v1.1
- 更新时间：2026-06-07
- 状态：已确认（新增 dashboard/ewo/tir 端点）

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

## 12. 变更记录

| 版本 | 日期 | 变更内容 | 确认 |
|------|------|----------|------|
| v1.0 | 2026-05-27 | 初始版本 | 已确认 |
| v1.1 | 2026-06-07 | 新增 dashboard/ewo/tir 端点，端口改为 8002 | 已确认 |