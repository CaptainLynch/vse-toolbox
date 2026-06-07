# 前端界面重构 - 功能设计文档

> **版本**: v1.0
> **日期**: 2026-06-06
> **复杂度评估**: L4（架构级 - 涉及导航体系重构、新增拖拽布局引擎、品牌重命名）
> **影响模块**: 前端全部层 + 后端 dashboard API 扩展

---

## 1. 需求概览

| # | 需求 | 优先级 | 说明 |
|---|------|--------|------|
| R1 | 左侧导航栏精简 | P0 | 仅保留「数据分析看板」「工具矩阵」「飞书邮件助手」，移除「造车问题追踪」「Excel工具箱」 |
| R2 | 数据分析看板重构为首页+子页面体系 | P0 | 首页展示项目总览，底部导航到各交付物子页面 |
| R3 | 交付物分类子页面 | P0 | 造车问题、EWO/NCR、TIR，后续可扩展 |
| R4 | 磁吸卡片式图表（拖拽+调整大小+吸附） | P1 | 每个子页面支持可拖拽、可调整大小、磁吸网格的卡片图表 |
| R5 | 品牌重命名 VSE TOOLBOX → VSE TOOLBOX | P0 | 全局替换所有出现的 VSE TOOLBOX（不含数据库文件名） |

---

## 2. 现状分析

### 2.1 当前导航结构

`
Sidebar (Sidebar.tsx)
├── 造车问题追踪  → Dashboard.tsx (issues CRUD + KPI + milestones)
├── Excel 工具箱  → ExcelToolbox.tsx (文件上传合并/重命名)
├── 工具矩阵      → Toolbox.tsx (工具卡片网格 + 对话框)
├── 数据分析看板  → Analytics.tsx (饼图/柱图/趋势图)
└── 飞书邮件助手  → FeishuMail.tsx (邮件列表+详情+待办)
Settings → Settings.tsx (底部固定入口)
`

### 2.2 当前技术栈

- **前端框架**: React 18 + TypeScript + Vite
- **UI 组件**: shadcn/ui (Radix UI) + Tailwind CSS
- **图表**: Recharts (PieChart, BarChart, AreaChart)
- **状态管理**: Zustand (appStore.ts 单一 store)
- **路由**: 无 react-router，使用 Zustand currentPage 状态切换
- **图标**: lucide-react
- **Toast**: sonner

### 2.3 关键文件清单

| 文件 | 职责 | 需要修改 |
|------|------|----------|
| pp/src/components/Sidebar.tsx | 侧边栏导航 | **是** - 精简菜单项 + 重命名 |
| pp/src/components/TopBar.tsx | 顶部栏 | **是** - 更新 pageTitles 映射 |
| pp/src/App.tsx | 主路由/布局 | **是** - 更新路由逻辑 |
| pp/src/stores/appStore.ts | 全局状态 | **是** - 新增子页面状态 + 拖拽布局状态 |
| pp/src/pages/Dashboard.tsx | 造车问题追踪 | **迁移** - 内容移入 DeliverableIssues |
| pp/src/pages/Analytics.tsx | 数据分析看板 | **重构** - 拆分为 Overview + Layout |
| pp/src/pages/Toolbox.tsx | 工具矩阵 | **不改** |
| pp/src/pages/FeishuMail.tsx | 飞书邮件助手 | **不改** |
| pp/src/pages/ExcelToolbox.tsx | Excel工具箱 | **不改** - 仅从导航移除 |
| pp/src/types/index.ts | 类型定义 | **是** - 新增拖拽布局相关类型 |
| pp/src/services/api.ts | API 调用层 | **是** - 新增 dashboard 统计 API |

---

## 3. 目标架构设计

### 3.1 新导航结构

`
Sidebar
├── 数据分析看板 (analytics) ← 默认首页
│   ├── [首页] 项目总览 (overview)
│   ├── [子页] 造车问题 (deliverable-issues)
│   ├── [子页] EWO/NCR  (deliverable-ewo)
│   └── [子页] TIR       (deliverable-tir)
├── 工具矩阵 (toolbox)
└── 飞书邮件助手 (feishu)

底部固定:
└── 设置 (settings)
`

### 3.2 页面层级关系

`
App
├── Sidebar (精简后的3项导航)
├── TopBar (动态标题 + 面包屑)
└── MainContent
    ├── currentPage === 'analytics'
    │   └── AnalyticsLayout (子页面容器)
    │       ├── SubPageNav (底部tabs: 总览 | 造车问题 | EWO/NCR | TIR)
    │       ├── AnalyticsOverview (默认首页)
    │       ├── DeliverableIssues (原 Dashboard 内容)
    │       ├── DeliverableEWO
    │       └── DeliverableTIR
    ├── currentPage === 'toolbox'
    │   └── Toolbox (保持不变)
    ├── currentPage === 'feishu'
    │   └── FeishuMail (保持不变)
    └── currentPage === 'settings'
        └── Settings (保持不变)
`

---

## 4. 数据层设计

### 4.1 新增表 - deliverable_categories

`sql
CREATE TABLE IF NOT EXISTS deliverable_categories (
    id TEXT PRIMARY KEY,            -- 'issues', 'ewo', 'tir'
    name TEXT NOT NULL,             -- '造车问题', 'EWO/NCR', 'TIR'
    icon TEXT,                      -- lucide icon name
    sort_order INTEGER DEFAULT 0,
    is_visible INTEGER DEFAULT 1,
    created_at TEXT
);

-- Seed 数据
INSERT OR IGNORE INTO deliverable_categories VALUES
  ('issues', '造车问题', 'ClipboardList', 1, 1, datetime('now')),
  ('ewo', 'EWO/NCR', 'AlertTriangle', 2, 1, datetime('now')),
  ('tir', 'TIR', 'FileText', 3, 1, datetime('now'));
`

### 4.2 新增表 - dashboard_layouts

存储用户自定义的磁吸卡片布局。

`sql
CREATE TABLE IF NOT EXISTS dashboard_layouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT DEFAULT 'default',     -- 预留多用户
    page_key TEXT NOT NULL,             -- 'overview', 'issues', 'ewo', 'tir'
    card_id TEXT NOT NULL,              -- 卡片唯一标识
    card_type TEXT NOT NULL,            -- 'kpi', 'pie', 'bar', 'area', 'table', 'milestone'
    x INTEGER NOT NULL DEFAULT 0,       -- 网格列位置
    y INTEGER NOT NULL DEFAULT 0,       -- 网格行位置
    w INTEGER NOT NULL DEFAULT 1,       -- 宽度(网格单位)
    h INTEGER NOT NULL DEFAULT 1,       -- 高度(网格单位)
    config TEXT,                        -- JSON: 图表配置(数据源、颜色、标题等)
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(user_id, page_key, card_id)
);
`

### 4.3 EWO/NCR 表（后续扩展）

`sql
CREATE TABLE IF NOT EXISTS ewo_ncr (
    id TEXT PRIMARY KEY,                -- EWO-YYYY-NNN / NCR-YYYY-NNN
    type TEXT CHECK(type IN ('EWO','NCR')),
    title TEXT NOT NULL,
    description TEXT,
    severity TEXT CHECK(severity IN ('critical','major','minor')),
    status TEXT CHECK(status IN ('open','investigating','resolved','closed')),
    department TEXT,
    assignee TEXT,
    raised_date TEXT,
    target_date TEXT,
    created_at TEXT,
    updated_at TEXT
);
`

### 4.4 TIR 表（后续扩展）

`sql
CREATE TABLE IF NOT EXISTS tir (
    id TEXT PRIMARY KEY,                -- TIR-YYYY-NNN
    title TEXT NOT NULL,
    description TEXT,
    category TEXT,                      -- 试验类型
    status TEXT CHECK(status IN ('draft','submitted','approved','rejected')),
    department TEXT,
    assignee TEXT,
    test_date TEXT,
    result TEXT,
    created_at TEXT,
    updated_at TEXT
);
`

### 4.5 Schema 变更（Pydantic）

在 ackend/models/schemas.py 中新增:

`python
class DeliverableCategoryOut(BaseModel):
    id: str
    name: str
    icon: str | None = None
    sort_order: int = 0
    is_visible: bool = True

class LayoutCardIn(BaseModel):
    page_key: str
    card_id: str
    card_type: str
    x: int = 0
    y: int = 0
    w: int = 1
    h: int = 1
    config: str | None = None

class LayoutCardOut(LayoutCardIn):
    id: int

class DashboardOverviewOut(BaseModel):
    total_issues: int
    open_issues: int
    closed_rate: float
    high_risk_count: int
    new_this_week: int
    closed_this_week: int
    milestone_progress: list    # [{name, percentage, category}]
    department_stats: list      # [{department, totalIssues, closedRate}]
    trend: list                 # [{date, count}]
    deliverable_counts: dict    # {issues: N, ewo: N, tir: N}
`

---

## 5. API 层设计

### 5.1 新增端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/dashboard/overview | 首页聚合数据（KPI + 里程碑 + 趋势 + 各交付物计数） |
| GET | /api/deliverable-categories | 交付物分类列表 |
| POST | /api/deliverable-categories | 新增分类 |
| PUT | /api/deliverable-categories/{id} | 更新分类 |
| DELETE | /api/deliverable-categories/{id} | 删除分类 |
| GET | /api/dashboard/layouts?page_key=xxx | 获取指定页面的卡片布局 |
| PUT | /api/dashboard/layouts | 批量保存卡片布局 |
| GET | /api/issues/stats | **已有** - 复用 |

### 5.2 响应示例

**GET /api/dashboard/overview**

`json
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
`

**GET /api/dashboard/layouts?page_key=overview**

`json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "page_key": "overview",
      "card_id": "kpi-total",
      "card_type": "kpi",
      "x": 0, "y": 0, "w": 1, "h": 1,
      "config": "{\"label\":\"未关闭问题总数\",\"dataSource\":\"total_issues\"}"
    }
  ],
  "message": null
}
`

### 5.3 后端实现要点

新增 ackend/api/dashboard.py:

`python
from fastapi import APIRouter
from backend.services.db import get_db
from backend.api.response import ok

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

@router.get("/overview")
def get_overview():
    """聚合 issues 统计 + milestones + 各交付物计数"""
    # 复用现有 issues 统计逻辑
    # 查询 milestones 表
    # 查询 deliverable_categories 获取分类列表
    # 组装 DashboardOverviewOut 返回

@router.get("/layouts")
def get_layouts(page_key: str):
    """获取指定页面的卡片布局"""
    pass

@router.put("/layouts")
def save_layouts(body: dict):
    """批量更新卡片布局 (UPSERT)"""
    pass
`

在 ackend/main.py 中注册:

`python
from backend.api.dashboard import router as dashboard_router
app.include_router(dashboard_router)
`

---

## 6. 前端层设计

### 6.1 品牌重命名 (R5)

全局搜索替换（不改数据库文件名和日志文件名）:

| 文件 | 替换内容 |
|------|----------|
| Sidebar.tsx | VSE TOOLBOX → VSE TOOLBOX，avatar PM → VS |
| index.html | <title> 中如有 VSE TOOLBOX |
| VSE_TOOLBOX.spec | 可选 - 构建产物名 |

注意: VSE_TOOLBOX.db 和 VSE_TOOLBOX.log 文件名**不改**。

### 6.2 Sidebar 重构

**文件**: pp/src/components/Sidebar.tsx

变更:
1. menuItems 从 5 项缩减为 3 项
2. 移除 dashboard（造车问题追踪）和 excel（Excel工具箱）
3. 将 nalytics 设为默认激活
4. 品牌文字改为 VSE TOOLBOX
5. 用户头像缩写改为 VS

`	sx
const menuItems = [
  { id: 'analytics', label: '数据分析看板', icon: BarChart3, category: 'analytics' },
  { id: 'toolbox', label: '工具矩阵', icon: Wrench, category: 'tool' },
  { id: 'feishu', label: '飞书邮件助手', icon: Mail, category: 'mail' },
];
`

### 6.3 App.tsx 路由调整

**文件**: pp/src/App.tsx

1. enderPage() 中 nalytics case 改为渲染 AnalyticsLayout
2. dashboard case 保留（重定向到 analytics），excel case 保留但从侧边栏不可达
3. 默认页从 dashboard 改为 nalytics

`	sx
const renderPage = () => {
  switch (currentPage) {
    case 'analytics':
      return <AnalyticsLayout />;
    case 'toolbox':
      return <Toolbox />;
    case 'feishu':
      return <FeishuMail />;
    case 'settings':
      return <Settings />;
    case 'excel':
      return <ExcelToolbox />;  // 保留，从工具矩阵跳转
    default:
      return <AnalyticsLayout />;
  }
};
`

### 6.4 TopBar 更新

**文件**: pp/src/components/TopBar.tsx

`	sx
const pageTitles = {
  analytics: { title: '数据分析看板', breadcrumb: '项目健康度 / 总览' },
  toolbox: { title: '工具矩阵', breadcrumb: '效率工具 / 全部' },
  feishu: { title: '飞书邮件助手', breadcrumb: '邮件管理 / 待办生成' },
  settings: { title: '设置', breadcrumb: '系统 / 配置' },
  excel: { title: 'Excel 工具箱', breadcrumb: '数据处理 / 全部模块' },
};
`

### 6.5 子页面体系 (R2, R3)

#### 6.5.1 AnalyticsLayout

**新文件**: pp/src/pages/AnalyticsLayout.tsx

容器组件，管理子页面切换。

`	sx
export function AnalyticsLayout() {
  const [activeSubPage, setActiveSubPage] = useState('overview');

  return (
    <div className="flex flex-col h-[calc(100vh-56px)]">
      <div className="flex-1 overflow-auto">
        {activeSubPage === 'overview' && <AnalyticsOverview />}
        {activeSubPage === 'issues' && <DeliverableIssues />}
        {activeSubPage === 'ewo' && <DeliverableEWO />}
        {activeSubPage === 'tir' && <DeliverableTIR />}
      </div>
      <SubPageNav active={activeSubPage} onChange={setActiveSubPage} />
    </div>
  );
}
`

#### 6.5.2 SubPageNav

**新文件**: pp/src/components/SubPageNav.tsx

底部固定导航栏:

`
┌──────────────────────────────────────────────────────────┐
│  [项目总览]  [造车问题]  [EWO/NCR]  [TIR]    [+ 添加]   │
└──────────────────────────────────────────────────────────┘
`

- 水平 tab 栏，当前激活 tab 有金色下划线高亮
- 末尾「+」按钮可新增交付物分类（弹出对话框）
- 数据从 /api/deliverable-categories 动态获取
- 点击 tab 切换 ctiveSubPage

#### 6.5.3 AnalyticsOverview

**新文件**: pp/src/pages/AnalyticsOverview.tsx

首页总览，使用磁吸卡片网格展示关键指标。

默认卡片布局:

`
┌─────────┬─────────┬─────────┬─────────┐
│ 未关闭   │ 本周新增 │ 本周关闭 │ 高风险   │  ← KPI 卡片行
│ 问题总数 │         │         │ 预警     │
├─────────┴────┬────┴─────────┴─────────┤
│              │                         │
│  各交付物    │    问题趋势折线图        │  ← 图表行
│  卡片导航    │                         │
│              │                         │
├──────────────┼─────────────────────────┤
│              │                         │
│  里程碑进度  │    各部门问题统计        │  ← 底部行
│              │                         │
└──────────────┴─────────────────────────┘
`

每个交付物卡片导航显示：名称 + 计数 + 进度条，点击跳转到对应子页面。

#### 6.5.4 DeliverableIssues

从 Dashboard.tsx 迁移全部内容（KPI、操作栏、数据表格、分页、右侧里程碑面板），改为磁吸卡片布局。原有内容拆分为:
- KPI 汇总卡片（4个指标）
- 问题数据表格卡片
- 里程碑面板卡片
- 部门统计卡片

#### 6.5.5 DeliverableEWO / DeliverableTIR

初期为含示例卡片的磁吸网格占位页，Phase 4 填充真实数据。

`	sx
export function DeliverableEWO() {
  return (
    <DraggableGrid pageKey="ewo">
      <DraggableCard id="ewo-kpi" cardType="kpi" title="EWO/NCR 概览" />
      <DraggableCard id="ewo-table" cardType="table" title="EWO/NCR 列表" />
    </DraggableGrid>
  );
}
`

### 6.6 磁吸卡片拖拽系统 (R4)

#### 6.6.1 技术选型: react-grid-layout

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| eact-grid-layout | 成熟、磁吸、响应式、序列化 | ~45KB | **采用** |
| eact-beautiful-dnd | 轻量 | 无网格吸附、无 resize | 不适合 |
| 自研 (pointer events) | 完全可控 | 工作量大 | 不推荐 |

`ash
npm install react-grid-layout
npm install --save-dev @types/react-grid-layout
`

#### 6.6.2 DraggableGrid 组件

**新文件**: pp/src/components/DraggableGrid.tsx

`	sx
import GridLayout from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';

interface DraggableGridProps {
  pageKey: string;                    // 'overview', 'issues', 'ewo', 'tir'
  children: React.ReactNode;
  cols?: number;                      // 默认 4 列
  rowHeight?: number;                 // 默认 120px
}

export function DraggableGrid({ pageKey, children, cols = 4, rowHeight = 120 }: DraggableGridProps) {
  const { layouts, fetchLayouts, saveLayouts } = useAppStore();
  const [currentLayout, setCurrentLayout] = useState<GridLayout.Layout[]>([]);

  useEffect(() => { fetchLayouts(pageKey); }, [pageKey]);
  useEffect(() => {
    setCurrentLayout(layouts[pageKey] ?? getDefaultLayout(pageKey));
  }, [layouts, pageKey]);

  const handleLayoutChange = (newLayout: GridLayout.Layout[]) => {
    setCurrentLayout(newLayout);
    debouncedSave(pageKey, newLayout);  // 防抖 500ms
  };

  return (
    <GridLayout
      className="layout"
      layout={currentLayout}
      cols={cols}
      rowHeight={rowHeight}
      width={containerWidth}
      onLayoutChange={handleLayoutChange}
      isDraggable={true}
      isResizable={true}
      compactType="vertical"
      margin={[12, 12]}
    >
      {children}
    </GridLayout>
  );
}
`

#### 6.6.3 DraggableCard 组件

**新文件**: pp/src/components/DraggableCard.tsx

`	sx
interface DraggableCardProps {
  id: string;
  cardType: 'kpi' | 'pie' | 'bar' | 'area' | 'table' | 'milestone' | 'custom';
  title?: string;
  children: React.ReactNode;
}

export function DraggableCard({ id, cardType, title, children }: DraggableCardProps) {
  return (
    <div key={id} className="bg-[#141416] border border-[#2a2a2e] rounded-[4px] overflow-hidden">
      {/* 拖拽手柄 */}
      <div className="drag-handle px-4 py-2 border-b border-[#2a2a2e] cursor-grab active:cursor-grabbing flex items-center justify-between">
        <span className="text-xs text-[#8a8f98] font-medium">{title}</span>
        <GripVertical className="w-3 h-3 text-[#3a3a3e]" />
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}
`

#### 6.6.4 默认布局配置

**新文件**: pp/src/config/defaultLayouts.ts

`	ypescript
export const defaultLayouts: Record<string, GridLayout.Layout[]> = {
  overview: [
    { i: 'kpi-open', x: 0, y: 0, w: 1, h: 1 },
    { i: 'kpi-new', x: 1, y: 0, w: 1, h: 1 },
    { i: 'kpi-closed', x: 2, y: 0, w: 1, h: 1 },
    { i: 'kpi-risk', x: 3, y: 0, w: 1, h: 1 },
    { i: 'deliverable-nav', x: 0, y: 1, w: 2, h: 2 },
    { i: 'trend-chart', x: 2, y: 1, w: 2, h: 2 },
    { i: 'milestones', x: 0, y: 3, w: 2, h: 2 },
    { i: 'dept-stats', x: 2, y: 3, w: 2, h: 2 },
  ],
  issues: [
    { i: 'issue-kpi', x: 0, y: 0, w: 4, h: 1 },
    { i: 'issue-table', x: 0, y: 1, w: 3, h: 3 },
    { i: 'issue-milestones', x: 3, y: 1, w: 1, h: 3 },
  ],
  ewo: [
    { i: 'ewo-kpi', x: 0, y: 0, w: 4, h: 1 },
    { i: 'ewo-table', x: 0, y: 1, w: 4, h: 3 },
  ],
  tir: [
    { i: 'tir-kpi', x: 0, y: 0, w: 4, h: 1 },
    { i: 'tir-table', x: 0, y: 1, w: 4, h: 3 },
  ],
};
`

### 6.7 状态管理扩展

**文件**: pp/src/stores/appStore.ts

`	ypescript
// 新增字段
activeSubPage: string;                    // 'overview' | 'issues' | 'ewo' | 'tir'
setActiveSubPage: (page: string) => void;

deliverableCategories: DeliverableCategory[];
fetchDeliverableCategories: () => Promise<void>;
createDeliverableCategory: (data: { id: string; name: string; icon?: string }) => Promise<boolean>;

dashboardOverview: DashboardOverview | null;
fetchDashboardOverview: () => Promise<void>;

layouts: Record<string, LayoutCard[]>;    // pageKey → cards
fetchLayouts: (pageKey: string) => Promise<void>;
saveLayouts: (pageKey: string, layouts: LayoutCard[]) => Promise<void>;

// 修改默认值
currentPage: string;  // 默认值从 'dashboard' 改为 'analytics'
`

### 6.8 类型定义扩展

**文件**: pp/src/types/index.ts

`	ypescript
export interface DeliverableCategory {
  id: string;
  name: string;
  icon?: string;
  sortOrder: number;
  isVisible: boolean;
}

export interface LayoutCard {
  id?: number;
  pageKey: string;
  cardId: string;
  cardType: string;
  x: number;
  y: number;
  w: number;
  h: number;
  config?: string;
}

export interface DashboardOverview {
  totalIssues: number;
  openIssues: number;
  closedRate: number;
  highRiskCount: number;
  newThisWeek: number;
  closedThisWeek: number;
  milestoneProgress: { name: string; percentage: number; category: string }[];
  departmentStats: { department: string; totalIssues: number; closedRate: number }[];
  trend: { date: string; count: number }[];
  deliverableCounts: Record<string, number>;
}
`

### 6.9 CSS 补充

在 pp/src/index.css 中引入 react-grid-layout 样式:

`css
.react-grid-item.react-draggable-dragging {
  z-index: 100;
  will-change: transform;
  opacity: 0.9;
}
.react-grid-placeholder {
  background: rgba(212, 175, 55, 0.1);
  border: 1px dashed #d4af37;
  border-radius: 4px;
  opacity: 0.6;
}
`

### 6.10 新增文件清单

| 文件路径 | 说明 |
|----------|------|
| pp/src/pages/AnalyticsLayout.tsx | 数据分析看板容器（子页面路由） |
| pp/src/pages/AnalyticsOverview.tsx | 项目总览首页 |
| pp/src/pages/DeliverableIssues.tsx | 造车问题子页面（从 Dashboard 迁移） |
| pp/src/pages/DeliverableEWO.tsx | EWO/NCR 子页面 |
| pp/src/pages/DeliverableTIR.tsx | TIR 子页面 |
| pp/src/components/SubPageNav.tsx | 底部子页面导航栏 |
| pp/src/components/DraggableGrid.tsx | 磁吸卡片网格容器 |
| pp/src/components/DraggableCard.tsx | 可拖拽卡片组件 |
| pp/src/config/defaultLayouts.ts | 默认卡片布局配置 |
| ackend/api/dashboard.py | Dashboard + 布局 API 端点 |

---

## 7. 实现顺序

### Phase 1: 基础重构（纯结构调整，无新功能）

| 步骤 | 任务 | 文件 | 依赖 |
|------|------|------|------|
| 1.1 | 品牌重命名 VSE TOOLBOX → VSE TOOLBOX | Sidebar.tsx, index.html | 无 |
| 1.2 | Sidebar 菜单项精简为 3 项 | Sidebar.tsx | 无 |
| 1.3 | TopBar pageTitles 更新 | TopBar.tsx | 1.2 |
| 1.4 | App.tsx 默认页改为 analytics | App.tsx | 1.2 |
| 1.5 | 验证：导航切换正常，工具矩阵和飞书页面不受影响 | 全局 | 1.1-1.4 |

### Phase 2: 数据分析看板子页面框架

| 步骤 | 任务 | 文件 | 依赖 |
|------|------|------|------|
| 2.1 | 后端：deliverable_categories 表 + CRUD API | backend/api/dashboard.py | 无 |
| 2.2 | 后端：dashboard/overview 聚合 API | backend/api/dashboard.py | 2.1 |
| 2.3 | 前端：新增类型定义 | types/index.ts | 无 |
| 2.4 | 前端：appStore 扩展状态 | stores/appStore.ts | 2.3 |
| 2.5 | 前端：AnalyticsLayout + SubPageNav | pages/ + components/ | 2.4 |
| 2.6 | 前端：AnalyticsOverview | pages/ | 2.4, 2.5 |
| 2.7 | 前端：Dashboard → DeliverableIssues 迁移 | pages/ | 2.5 |
| 2.8 | 前端：DeliverableEWO / DeliverableTIR 空壳 | pages/ | 2.5 |
| 2.9 | 验证：子页面切换、数据加载、底部导航正常 | 全局 | 2.1-2.8 |

### Phase 3: 磁吸卡片拖拽系统

| 步骤 | 任务 | 文件 | 依赖 |
|------|------|------|------|
| 3.1 | 安装 react-grid-layout + 类型 | package.json | 无 |
| 3.2 | 后端：dashboard_layouts 表 + CRUD API | backend/ | 无 |
| 3.3 | 前端：appStore layouts 状态管理 | stores/ | 3.2 |
| 3.4 | 前端：DraggableGrid + DraggableCard | components/ | 3.1 |
| 3.5 | 前端：默认布局配置 | config/ | 无 |
| 3.6 | 前端：AnalyticsOverview 接入 DraggableGrid | pages/ | 3.4, 3.5 |
| 3.7 | 前端：DeliverableIssues 接入 DraggableGrid | pages/ | 3.4, 3.5 |
| 3.8 | 前端：DeliverableEWO / TIR 接入 DraggableGrid | pages/ | 3.4, 3.5 |
| 3.9 | 前端：CSS 样式补充（拖拽占位、动画） | index.css | 3.1 |
| 3.10 | 验证：拖拽、调整大小、吸附、刷新后布局保持 | 全局 | 3.1-3.9 |

### Phase 4: 数据层填充 (EWO/NCR, TIR)

| 步骤 | 任务 | 文件 | 依赖 |
|------|------|------|------|
| 4.1 | 后端：ewo_ncr 表 + CRUD API | backend/ | 无 |
| 4.2 | 后端：tir 表 + CRUD API | backend/ | 无 |
| 4.3 | 前端：DeliverableEWO 页面数据填充 | pages/ | 4.1 |
| 4.4 | 前端：DeliverableTIR 页面数据填充 | pages/ | 4.2 |
| 4.5 | 验证：EWO/NCR 和 TIR 子页面 CRUD 和图表正常 | 全局 | 4.1-4.4 |

### 依赖关系图

`
Phase 1 (前端)          Phase 2 (前后端)          Phase 3 (前后端)          Phase 4 (前后端)
┌──────────────┐       ┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│ 1.1 品牌重命名 │       │ 2.1 categories│       │ 3.1 安装依赖  │       │ 4.1 EWO 表    │
│ 1.2 精简导航   │ ───▶ │    表+API     │ ───▶ │ 3.2 layouts   │ ───▶ │ 4.2 TIR 表    │
│ 1.3 TopBar    │       │ 2.2 overview  │       │    表+API     │       │ 4.3 EWO 页面  │
│ 1.4 默认页    │       │    API        │       │ 3.3-3.5 组件  │       │ 4.4 TIR 页面  │
└──────────────┘       │ 2.3-2.9 前端  │       │ 3.6-3.8 接入  │       └──────────────┘
                        └──────────────┘       └──────────────┘

Phase 1 和 Phase 2 的后端步骤可并行
Phase 3 的 3.1/3.2 可与 Phase 2 并行
Phase 4 依赖 Phase 3 完成
`

---

## 8. 注意事项

### 8.1 向后兼容
- ExcelToolbox.tsx 保留不删除，仅从侧边栏移除。工具矩阵中的 Excel 工具仍可跳转。
- Dashboard.tsx 保留不删除，内容迁移后可在后续版本清理。
- VSE_TOOLBOX.db 数据库文件名不改，避免数据迁移风险。

### 8.2 安全红线
- 新增 API 遵循 {success, data, message} 响应格式。
- SQL 全部参数化（使用现有 db.py 的上下文管理器模式）。
- 布局保存限制单次最大 50 张卡片，防止滥用。

### 8.3 性能考虑
- react-grid-layout 包体积约 45KB (gzipped ~15KB)，可接受。
- 布局保存使用防抖（debounce 500ms），避免频繁请求。
- Dashboard 聚合 API 做内存缓存（TTL 30s），减少 SQLite 查询压力。

### 8.4 后续扩展点
- 交付物分类支持拖拽排序（SubPageNav 中的 tab 顺序）。
- 卡片支持「添加卡片」面板，用户可从卡片库中选择新增。
- 每个子页面支持全屏模式。
- 图表卡片支持切换图表类型（如饼图 ↔ 柱状图）。

---

**最后更新**: 2026-06-06
