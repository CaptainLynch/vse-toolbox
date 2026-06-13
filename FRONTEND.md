# VSE TOOLBOX - 前端开发主文档

> **[已暂停]** 由于前端存在较多 Bug 且交付紧急，**前端开发已于 2026-06-13 全面暂停**。
> 当前项目的核心已转向后端的终端命令行 (CLI) 交互开发。
> 本文档保留仅作历史归档和未来重启参考使用，当前不要修改任何前端代码。

> 本文档由 agent 读取并执行。每完成一个 Task 后，**必须**更新下方的「开发进度」表格状态，然后继续下一项。
>
> 状态约定：`TODO` -> `IN_PROGRESS` -> `DONE`

---

## 1. 项目概述

汽车项目管理工具箱的前端界面。深色主题（精密仪表盘风格），对接 Python FastAPI 后端（本地 127.0.0.1:8002 服务）。

**技术栈**：React 19 + TypeScript + Vite + Tailwind CSS + shadcn/ui + Recharts + Zustand + react-grid-layout

---

## 2. 前端导航结构（2026-06 重构后）

### Sidebar 菜单项

```typescript
const menuItems = [
  { id: 'analytics', label: '数据分析看板', icon: BarChart3, category: 'analytics' },
  { id: 'toolbox', label: '工具矩阵', icon: Wrench, category: 'tool' },
  { id: 'feishu', label: '飞书邮件助手', icon: Mail, category: 'mail' },
];
```

### 页面组件层级

```
App.tsx
├── Sidebar (精简后的3项导航)
├── TopBar (动态标题+面包屑)
└── renderPage()
    ├── 'analytics' -> AnalyticsLayout
    │   ├── AnalyticsOverview (默认首页)
    │   ├── DeliverableIssues (造车问题)
    │   ├── DeliverableEWO (EWO/NCR)
    │   └── DeliverableTIR (TIR)
    ├── 'toolbox' -> Toolbox
    ├── 'feishu' -> FeishuMail
    ├── 'excel' -> ExcelToolbox (保留，从工具矩阵跳转)
    └── 'settings' -> Settings
```

### 子页面体系

AnalyticsLayout 内部通过 SubPageNav 底部导航栏切换子页面：
- overview (项目总览) <- 默认
- issues (造车问题)
- ewo (EWO/NCR)
- tir (TIR)

支持动态添加新的交付物分类（通过 SubPageNav 的 + 按钮）。

---

## 3. 项目目录

```
src/
├── components/
│   ├── ui/                    # shadcn/ui 组件（已存在）
│   ├── LoadingScreen.tsx      # 启动加载动画
│   ├── Sidebar.tsx            # 侧边栏导航（3项菜单）
│   ├── TopBar.tsx             # 顶部状态栏
│   ├── OfflineBanner.tsx      # 离线提示条
│   ├── SubPageNav.tsx         # 子页面底部导航栏
│   ├── DraggableGrid.tsx      # 磁吸卡片网格容器
│   └── DraggableCard.tsx      # 可拖拽卡片组件
├── pages/
│   ├── AnalyticsLayout.tsx    # 数据分析看板容器（子页面路由）
│   ├── AnalyticsOverview.tsx  # 项目总览首页（KPI+图表+里程碑）
│   ├── DeliverableIssues.tsx  # 造车问题子页面
│   ├── DeliverableEWO.tsx     # EWO/NCR 子页面
│   ├── DeliverableTIR.tsx     # TIR 子页面
│   ├── Analytics.tsx          # 旧版分析页（保留）
│   ├── Dashboard.tsx          # 旧版问题页（保留）
│   ├── ExcelToolbox.tsx       # Excel工具箱（保留）
│   ├── Toolbox.tsx            # 工具矩阵
│   ├── FeishuMail.tsx         # 飞书邮件助手
│   └── Settings.tsx           # 环境设置
├── config/
│   └── defaultLayouts.ts      # 默认卡片布局配置
├── hooks/
│   └── use-mobile.ts          # 移动端检测
├── lib/
│   └── utils.ts               # cn() 工具函数
├── types/
│   └── index.ts               # TypeScript 类型定义
├── stores/
│   └── appStore.ts            # Zustand 全局状态
├── services/
│   ├── api.ts                 # API 封装（fetch 封装）
│   └── converters.ts          # snake_case -> camelCase 转换器
├── App.tsx                    # 根组件 + 路由
├── main.tsx                   # 入口（HashRouter）
└── index.css                  # 全局样式 + react-grid-layout
```

---

## 4. 路由结构

使用 `HashRouter`（main.tsx），所有路由由前端处理，后端只托管静态文件。

| 路径 | 页面 | 说明 |
|------|------|------|
| / | AnalyticsLayout | 默认页面（数据分析看板） |
| /#/ | AnalyticsLayout | HashRouter 默认 |
| (状态切换) | analytics -> AnalyticsLayout | 数据分析看板 |
| (状态切换) | toolbox -> Toolbox | 工具矩阵 |
| (状态切换) | feishu -> FeishuMail | 飞书邮件助手 |
| (状态切换) | settings -> Settings | 环境设置 |
| (状态切换) | excel -> ExcelToolbox | Excel工具箱（从工具矩阵跳转） |

---

## 5. 全局状态（Zustand）

```typescript
interface AppState {
  // Navigation
  currentPage: string;              // 'analytics' | 'toolbox' | 'feishu' | 'settings'
  activeSubPage: string;            // 'overview' | 'issues' | 'ewo' | 'tir'
  isSidebarOpen: boolean;

  // Issues
  issues: Issue[];
  issueTotal: number;
  issuePage: number;

  // Stats
  stats: IssueStats | null;

  // Milestones
  milestones: Milestone[];

  // Tools
  tools: ToolCard[];

  // Feishu
  mails: Mail[];
  todos: Todo[];

  // Deliverable Categories
  deliverableCategories: DeliverableCategory[];

  // Dashboard Overview
  dashboardOverview: DashboardOverview | null;

  // Layouts (拖拽卡片布局)
  layouts: Record<string, LayoutCard[]>;

  // EWO/NCR
  ewos: EWOItem[];
  ewoTotal: number;
  ewoPage: number;

  // TIR
  tirs: TIRItem[];
  tirTotal: number;
  tirPage: number;

  // Settings
  settings: Record<string, string>;
}
```

---

## 6. 关键组件说明

| 文件 | 状态 | 说明 |
|------|------|------|
| LoadingScreen.tsx | 完成 | 启动加载动画（3个金色方块 + VSE TOOLBOX 文字） |
| Sidebar.tsx | 完成 | 侧边栏导航（3个主菜单 + 设置 + 用户信息），品牌名 VSE TOOLBOX |
| TopBar.tsx | 完成 | 面包屑 + 搜索 + 通知 + 设置图标 |
| SubPageNav.tsx | 完成 | 底部子页面导航栏（overview/issues/ewo/tir + 添加按钮） |
| DraggableGrid.tsx | 完成 | react-grid-layout v2 封装（gridConfig/dragConfig/resizeConfig/compactor） |
| DraggableCard.tsx | 完成 | 可拖拽卡片组件（标题+拖拽手柄+内容区） |
| AnalyticsLayout.tsx | 完成 | 数据分析看板容器，子页面路由 |
| AnalyticsOverview.tsx | 完成 | 项目总览（KPI+趋势图+饼图+柱状图+里程碑计划/实际+交付物导航） |
| DeliverableIssues.tsx | 完成 | 造车问题（KPI+10列表格+筛选+分页+Excel导入+零件总成/工程师自动关联） |
| DeliverableEWO.tsx | 完成 | EWO/NCR（KPI+列表+分页+创建+Excel导入，已对接后端API） |
| DeliverableTIR.tsx | 完成 | TIR（KPI+列表+分页+创建+Excel导入，已对接后端API） |
| Toolbox.tsx | 完成 | 工具矩阵（Excel/爬虫/PPT/飞书工具卡片+对话框） |
| FeishuMail.tsx | 完成 | 三栏布局邮件客户端 + 同步 + 分类标签 + 待办勾选 |
| Settings.tsx | 完成 | 环境设置（安全/网络/工具/部署/交付物配置 五Tab） |
| Dashboard.tsx | 保留 | 旧版造车问题追踪页面（内容已迁移到 DeliverableIssues） |
| Analytics.tsx | 保留 | 旧版数据分析页面（内容已迁移到 AnalyticsOverview） |
| ExcelToolbox.tsx | 保留 | Excel工具箱（从工具矩阵跳转可达） |

---

## 7. 最后更新

- 创建时间：2026-05-27
- 最后更新：2026-06-07（F-20~F-26 开发完成 + 两轮代码审计修复完毕 + API集成测试37项全部通过）
- 当前状态：前端全部开发完成，API集成测试通过，待前端UI测试