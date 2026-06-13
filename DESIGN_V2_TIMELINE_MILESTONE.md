# DESIGN: 时间轴节点变色 + 里程碑卡片改进

> **架构设计文档 v2** — 2026-06-11 创建
> **设计者**: Galileo（架构师子智能体）
> **状态**: 待实现

---

## 功能 1：时间轴节点自动变色

### 需求描述

时间轴节点圆圈根据 `actual_date` 与 `target_date` 的比较结果自动变色，并显示对应状态文字：

| 条件 | 圆圈颜色 | 文字标注 |
|------|----------|----------|
| `actual_date ≤ target_date` | 🟢 绿色 `#4ade80` | "按时完成" |
| `actual_date > target_date` | 🟡 黄色 `#d4af37` | "超期完成" |
| `actual_date IS NULL` 且 `target_date < 今天` | 🔴 红色 `#ef4444` | "已超期" |
| `actual_date IS NULL` 且 `target_date ≥ 今天` | ⚪ 灰色 `#8a8f98` | "待开始"/"进行中" |

### 影响范围

- **纯前端改动**，后端零变更
- **仅修改文件**: `app/src/components/ProjectTimeline.tsx`

### 实现细节

#### 1.1 新增判定函数

```typescript
type NodeVisual = { color: string; label: string };

function getNodeVisual(node: TimelineNode): NodeVisual {
  const today = new Date().toISOString().slice(0, 10); // YYYY-MM-DD

  if (node.actualDate) {
    if (node.targetDate && node.actualDate <= node.targetDate) {
      return { color: '#4ade80', label: '按时完成' };
    }
    return { color: '#d4af37', label: '超期完成' };
  }

  // actualDate 为空
  if (node.targetDate && node.targetDate < today) {
    return { color: '#ef4444', label: '已超期' };
  }

  // 未到期限 — 保持状态色
  return { color: statusColors[node.status], label: statusLabels[node.status] };
}
```

#### 1.2 修改节点渲染

**当前代码**（约 L57-L68）：
```tsx
<button
  style={{
    borderColor: statusColors[node.status],
    backgroundColor: node.status === 'completed' ? statusColors[node.status] : '#0f0f11'
  }}
>
```

**改为**：
```tsx
const visual = getNodeVisual(node);
<button
  style={{
    borderColor: visual.color,
    backgroundColor: node.actualDate ? visual.color : '#0f0f11'
  }}
>
```

#### 1.3 修改文字标注

**当前代码**（约 L77）：
```tsx
<p className="text-[10px] mt-1" style={{ color: statusColors[node.status] }}>
  {statusLabels[node.status]}
</p>
```

**改为**：
```tsx
<p className="text-[10px] mt-1" style={{ color: visual.color }}>
  {visual.label}
</p>
```

#### 1.4 勾选图标

当节点有 `actualDate` 时显示 ✅（不限于 `status === 'completed'`）：
```tsx
{node.actualDate && (
  <svg ...checkmark... />
)}
```

---

## 功能 2：里程碑卡片改进

### 需求描述

1. 里程碑状态**只显示当前选中时间轴节点**对应的交付物
2. 每个交付物图框固定 **302 × 302 像素**
3. 支持**自由拖拽位置** + **拖拽调整大小**
4. 具有**磁性功能**（snap to grid）

### 影响范围

**后端**（L1 改动）：
- `backend/api/milestone_rules.py` — `list_evaluations` 增加可选 `timeline_node_id` 筛选参数
- `backend/services/db.py` — `list_evaluations` 增加 `timeline_node_id` 参数

**前端**（L2 改动）：
- `app/src/stores/appStore.ts` — 新增 `selectedTimelineNodeId` 状态 + `setSelectedTimelineNodeId` action
- `app/src/components/ProjectTimeline.tsx` — 节点点击时调用 `setSelectedTimelineNodeId`
- `app/src/components/MilestoneCardGrid.tsx` — 根据 `selectedTimelineNodeId` 筛选 evaluations + 固定卡片尺寸
- `app/src/components/MilestoneCard.tsx` — 容器固定 302×302
- `app/src/pages/AnalyticsOverview.tsx` — 布局微调

### 已有基础设施

- `DraggableGrid` 基于 `react-grid-layout`，天然支持网格磁吸和布局持久化
- `DraggableCard` 支持 drag-handle 拖拽
- `MilestoneCardGrid` 已在使用 `DraggableGrid`
- 不需要引入新依赖

### 实现细节

#### 2.1 后端：evaluation 筛选

**`backend/api/milestone_rules.py`**：
```python
@router.get("/milestone-rules/evaluations")
def list_evaluations(timeline_node_id: int | None = None):
    evals = DBManager.list_evaluations(timeline_node_id)
    return success_response(evals)
```

**`backend/services/db.py` — `list_evaluations`**：
```python
@staticmethod
def list_evaluations(timeline_node_id: int | None = None) -> list[dict]:
    with get_connection() as conn:
        if timeline_node_id is not None:
            rows = conn.execute(
                """SELECT e.*, t.name as timeline_node_name
                   FROM milestone_evaluations e
                   LEFT JOIN milestone_rules r ON e.rule_id = r.id
                   LEFT JOIN timeline_nodes t ON r.timeline_node_id = t.id
                   WHERE r.timeline_node_id = ?
                   ORDER BY e.evaluation_id""",
                (timeline_node_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT e.*, t.name as timeline_node_name
                   FROM milestone_evaluations e
                   LEFT JOIN milestone_rules r ON e.rule_id = r.id
                   LEFT JOIN timeline_nodes t ON r.timeline_node_id = t.id
                   ORDER BY e.evaluation_id"""
            ).fetchall()
        return [dict(r) for r in rows]
```

#### 2.2 前端 Store：选中节点状态

**`app/src/stores/appStore.ts`**：
```typescript
// 新增 state
selectedTimelineNodeId: number | null;
setSelectedTimelineNodeId: (id: number | null) => void;

// 新增实现
selectedTimelineNodeId: null,
setSelectedTimelineNodeId: (id) => set({ selectedTimelineNodeId: id }),
```

#### 2.3 前端 Store：fetchMilestoneEvaluations 支持筛选

```typescript
fetchMilestoneEvaluations: async (timelineNodeId?: number) => {
  await api.post('/milestone-rules/evaluations/refresh');
  const query = timelineNodeId ? `?timeline_node_id=${timelineNodeId}` : '';
  const res = await api.get<MilestoneEvaluationOut[]>('/milestone-rules/evaluations' + query);
  if (res.success && res.data) {
    set({ milestoneEvaluations: res.data.map(toMilestoneEvaluation) });
  }
},
```

#### 2.4 前端：ProjectTimeline 节点点击联动

```tsx
const { setSelectedTimelineNodeId } = useAppStore();

const handleEdit = (node: TimelineNode) => {
  setSelectedTimelineNodeId(node.id);
  setEditingNode(node);
};
```

#### 2.5 前端：MilestoneCardGrid 响应选中 + 固定 302×302

```tsx
export function MilestoneCardGrid() {
  const { milestoneEvaluations, selectedTimelineNodeId, fetchMilestoneEvaluations } = useAppStore();

  useEffect(() => {
    fetchMilestoneEvaluations(selectedTimelineNodeId ?? undefined);
  }, [selectedTimelineNodeId]);

  return (
    // ...
    <DraggableGrid pageKey="milestones" cols={3} rowHeight={302}>
      {milestoneEvaluations.map((ev) => (
        <DraggableCard key={'ms-' + ev.evaluationId} id={'ms-' + ev.evaluationId} title={ev.ruleName}>
          <div style={{ width: 302, height: 302 }}>
            <MilestoneCard evaluation={ev} onClick={() => setEditingEval(ev)} />
          </div>
        </DraggableCard>
      ))}
    </DraggableGrid>
  );
}
```

#### 2.6 MilestoneCard 尺寸适配

卡片内部使用 `h-full w-full` 填满 302×302 容器，不需要硬编码尺寸。

---

## 依赖关系

```
功能 1 (前端) ──无依赖──> 直接修改 ProjectTimeline.tsx
功能 2:
  后端筛选参数 (DB + API)
    ↓
  Store 状态 + 前端联动 (appStore + ProjectTimeline + MilestoneCardGrid)
```

建议实施顺序：**先功能 1 → 再功能 2（后端 → 前端）**

---

## 文件变更清单

| 文件 | 操作 | 功能 |
|------|------|------|
| `app/src/components/ProjectTimeline.tsx` | 修改 | F1 + F2 |
| `backend/api/milestone_rules.py` | 修改 | F2 |
| `backend/services/db.py` | 修改 | F2 |
| `app/src/stores/appStore.ts` | 修改 | F2 |
| `app/src/components/MilestoneCardGrid.tsx` | 修改 | F2 |
| `app/src/components/MilestoneCard.tsx` | 微调 | F2 |
| `app/src/pages/AnalyticsOverview.tsx` | 微调 | F2 |
| `app/src/services/api.ts` | 可能微调 | F2 |
| `app/src/types/index.ts` | 可能微调 | F2 |

---

## 风险与注意事项

1. **日期比较**：`YYYY-MM-DD` 字符串比较在 ISO 格式下是安全的
2. **空值处理**：`target_date` 为空时不做超期判定
3. **磁吸布局**：`react-grid-layout` 的 `rowHeight=302` 配合 `cols=3` 可确保 302×302 网格
4. **性能**：evaluation 的 refresh 仍走全量刷新，后续可优化为按节点刷新
