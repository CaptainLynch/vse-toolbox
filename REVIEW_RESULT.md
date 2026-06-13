# 审查报告

## 审查对象
「时间轴节点自动变色」+「里程碑卡片改进」功能变更，共 6 个文件：

| # | 文件 | 技术栈 |
|---|------|--------|
| 1 | `app/src/components/ProjectTimeline.tsx` | React 18 / TSX |
| 2 | `app/src/components/MilestoneCardGrid.tsx` | React 18 / TSX |
| 3 | `app/src/components/MilestoneCard.tsx` | React 18 / TSX |
| 4 | `app/src/stores/appStore.ts` | Zustand / TypeScript |
| 5 | `backend/services/db.py` | Python 3.11 / SQLite3 |
| 6 | `backend/api/milestone_rules.py` | FastAPI / Python |

## 审查时间
2026-06-11

---

## 通过项

### 1. 安全检查

- [x] **R-08 无硬编码密码/Token/API Key** — 全部 6 个文件均无硬编码凭据。API 密钥通过环境变量读取（已确认）。
- [x] **R-02 无 SQL 注入** — `db.py` 中 `list_evaluations()` (L1330)、`list_milestone_rules()` (L1234)、`upsert_evaluation()` (L1370)、`update_evaluation()` (L1388)、`update_milestone_rule()` (L1303) 均使用参数化查询 `?` 占位符。动态字段构建使用白名单硬编码字段名（非用户输入），安全。
- [x] **R-01 无路径遍历** — 本次变更不涉及文件 I/O 操作，无路径遍历风险。
- [x] **无命令注入** — 本次变更不涉及 `subprocess`、`os.system` 或 shell 调用。
- [x] **R-07 敏感信息不写入日志** — 后端 `milestone_rules.py` 和 `db.py` 中变更部分均无日志写入敏感数据。

### 2. GAC 合规检查

- [x] **R-10 不写入注册表/系统目录/PATH** — 本次变更不涉及系统目录写入。
- [x] **文件 I/O 范围** — 本次变更不涉及文件读写操作。
- [x] **R-05 数据库连接正确关闭** — `get_connection()` 使用 `@contextmanager`，try/finally 确保 `conn.close()`，符合规范 (db.py L210-226)。
- [x] **R-06 临时文件自动清理** — 本次变更不涉及临时文件。

### 3. 代码质量

- [x] **R-03 文件句柄使用 with 语句** — 本次变更不涉及文件操作。
- [x] **R-13 使用 HashRouter** — `main.tsx` 使用 `<HashRouter>`，符合规范。
- [x] **Pydantic 输入验证** — `MilestoneRuleCreate`/`MilestoneRuleUpdate`/`MilestoneEvaluationUpdate` 均有正确的类型约束和 `Literal` 校验 (schemas.py)。
- [x] **后端 API 异常处理** — `create_milestone_rule()`、`refresh_evaluations()` 有 try-except，返回 `error_response()` (milestone_rules.py L22-26, L37-41)。
- [x] **API 响应格式统一** — 使用 `success_response()` / `error_response()` 统一返回 `{success, data, message}` 格式。
- [x] **前端类型安全** — `toTimelineNode`、`toMilestoneEvaluation` 转换器正确映射 snake_case → camelCase (converters.ts)。

### 4. 功能正确性

- [x] **list_evaluations 参数化查询** — `WHERE r.timeline_node_id = ?` 使用参数化，`timeline_node_id` 类型为 `int | None`，Pydantic 会自动校验 (db.py L1330)。
- [x] **fetchMilestoneEvaluations 筛选参数传递** — store 正确拼接 `?timeline_node_id=` + 值，`null` 时不传参 (appStore.ts L576-582)。
- [x] **302×302 卡片尺寸** — `MilestoneCardGrid.tsx` L38 `<div style={{ width: 302, height: 302 }}>` + `DraggableGrid cols={3} rowHeight={302}` 正确应用。
- [x] **getNodeVisual() 日期比较** — YYYY-MM-DD 字符串比较在 ISO 格式下等价于日期比较，逻辑正确 (ProjectTimeline.tsx L26-39)。
- [x] **空值处理** — `actualDate` 和 `targetDate` 为 `null` 时做 truthiness 检查后才使用，不会崩溃。

### 5. 编码检查

- [x] **UTF-8 无 BOM** — 全部 6 个文件均无 BOM 标记。
- [x] **中文字符正确** — 各文件中文注释和字符串渲染正确无乱码。

---

## 问题项

| # | 文件 | 位置 | 问题描述 | 严重程度 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | `app/src/stores/appStore.ts` | L11 处全部 `catch (e) { /* ignore */ }` (共 11 处) | **全部异常静默吞没**：`fetchTimelineNodes`、`fetchMilestoneEvaluations`、`refreshMilestoneEvaluations`、`createTimelineNode`、`updateTimelineNode`、`deleteTimelineNode` 等所有 store 方法的 catch 块仅 `/* ignore */`，无 `console.error` 也无用户反馈。违反 R-11（前端 API 调用需有错误处理）。当后端不可达或返回 500 时，用户看到的是空白页面、静默失败，无法排查问题。 | **MEDIUM** | 每个 catch 块至少添加 `console.error('fetchXxx failed:', e)`，关键操作（create/update/delete）应返回错误信息给 UI 层显示 toast。示例：`catch (e) { console.error('fetchTimelineNodes:', e); }` |
| 2 | `app/src/stores/appStore.ts` | L576-582 `fetchMilestoneEvaluations` | **每次筛选都触发 refresh 请求**：`fetchMilestoneEvaluations` 先调用 `POST /evaluations/refresh` 再 `GET /evaluations`。当用户在时间轴节点间快速切换时，每次切换都会触发完整的 evaluate_all()，可能造成不必要的计算开销和竞态条件。`refreshMilestoneEvaluations` (L584-590) 也有相同逻辑，二者职责重复。 | **MEDIUM** | 将 refresh 与 fetch 分离：`fetchMilestoneEvaluations` 仅做 GET 请求，`refreshMilestoneEvaluations` 才先 POST refresh 再 GET。或者在 `MilestoneCardGrid` 中 `useEffect` 仅调用 fetch，刷新按钮才调用 refresh。 |
| 3 | `app/src/components/ProjectTimeline.tsx` | L26-39 `getNodeVisual()` | **时区敏感的日期获取**：`const today = new Date().toISOString().slice(0, 10)` 使用 UTC 时间。在中国时区（UTC+8），UTC 0:00-8:00 之间 `today` 会比本地日期少一天，导致「已超期」判断提前 8 小时。 | **LOW** | 使用本地日期：`const today = new Date().toLocaleDateString('sv-SE')` 或手动拼接 `YYYY-MM-DD`（`getFullYear()` + `getMonth()` + `getDate()`）。 |
| 4 | `app/src/components/ProjectTimeline.tsx` | L48-49 `handleEdit` | **点击节点必然设置 selectedTimelineNodeId 且无法取消选择**：用户点击任意节点后 `selectedTimelineNodeId` 被设置，但没有取消选择的机制（如再次点击同一节点 toggle）。里程碑卡片列表会被永久筛选直到用户切换页面。这可能不是 bug 但是 UX 上缺少取消筛选的方式。 | **LOW** | 添加 toggle 逻辑：`setSelectedTimelineNodeId(node.id === selectedTimelineNodeId ? null : node.id)`。同时需要从 store 读取 `selectedTimelineNodeId`。 |
| 5 | `backend/api/milestone_rules.py` | L14-17, L29-32 | **GET 端点缺少 try-except**：`list_milestone_rules()` 和 `list_evaluations()` 两个 GET 端点没有 try-except 包裹。虽然 Pydantic 校验了 query param 类型，但如果 DB 操作抛出异常（如 DB 文件损坏），将返回 FastAPI 默认 500 而非标准 `{success: false, message: "..."}` 格式。其他 POST/PUT/DELETE 端点均有 try-except。 | **LOW** | 为一致性，给这两个 GET 端点也加上 try-except，返回 `error_response(str(e), status_code=500)`。 |
| 6 | `backend/api/milestone_rules.py` | 全文件 | **缺少关键操作日志**：整个文件无 `logger` 调用。`create_milestone_rule`、`delete_milestone_rule`、`update_evaluation`、`refresh_evaluations` 等关键写操作没有 INFO 级别日志记录。违反 R-16 日志级别规范（关键操作应记录 INFO）。 | **LOW** | 在 `create`/`delete`/`update`/`refresh` 操作成功后添加 `logger.info("xxx %s succeeded", id)`。 |
| 7 | `app/src/stores/appStore.ts` | L128-129 | **fetchMilestoneEvaluations / refreshMilestoneEvaluations 代码完全重复**：两个方法实现逻辑完全相同（先 POST refresh 再 GET evaluations），是明显的代码重复。 | **LOW** | 让 `fetchMilestoneEvaluations` 仅执行 GET，`refreshMilestoneEvaluations` 调用 POST + GET，或提取共用函数。 |

---

## 总体结论

### ✅ 有条件通过

**理由：**

本次变更在**安全性**和 **GAC 合规性**方面无硬伤——SQL 全部参数化、无路径遍历、无硬编码凭据、数据库连接正确关闭。**功能正确性**方面，日期比较、空值处理、筛选逻辑均正确。**编码规范**方面，UTF-8 无 BOM，中文正常。

**需要关注的问题：**

1. **MEDIUM × 2**：store 层 11 个 catch 块静默吞没异常（违反 R-11）；fetch 和 refresh 职责混淆导致不必要的计算开销。这两个问题不影响安全性，但影响可维护性和用户体验，建议尽快修复。
2. **LOW × 5**：时区日期、缺少 toggle 选择、GET 端点缺 try-except、缺少操作日志、代码重复——均为优化建议，不阻塞发布。

**建议在下一迭代中优先修复 MEDIUM 级别的 2 个问题。**