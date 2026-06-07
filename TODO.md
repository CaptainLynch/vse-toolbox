# TODO

> **全局任务列表。所有模型的唯一任务来源。完成后标记[DONE]，不要删除。**
> **阻塞关系：下游任务缩进列在父任务下方。父任务未完成时，不做下游任务。**

---

## 状态图例

- [ ] 待办
- [~] 进行中
- [x] 已完成
- [!] 阻塞（依赖外部，如IT审批）

---

## P1 后端基础框架（阻塞全部下游）

- [x] **B-01** `backend/models/schemas.py` - Pydantic模型
- [x] **B-02** `backend/services/db.py` - SQLite连接+Schema初始化+CRUD封装
- [x] **B-03** `backend/main.py` - FastAPI实例+CORS+静态文件托管+生命周期

## P2 问题追踪API（阻塞Dashboard前端）

- [x] **B-04** `backend/api/issues.py` - RESTful CRUD + 分页筛选 + 聚合统计
- [x] **B-05** `backend/api/download.py` - 文件下载端点

## P3 Excel工具（阻塞Toolbox前端Excel功能）

- [x] **B-06** `backend/services/excel_service.py` - 合并/改名逻辑
- [x] **B-07** `backend/api/excel.py` - 上传->处理->下载

## P4 PPT生成（阻塞Toolbox前端PPT功能）

- [x] **B-08** `backend/services/ppt_service.py` - ChartGenerator
- [x] **B-09** `backend/services/ppt_service.py` - TemplateEngine
- [x] **B-10** `backend/services/ppt_service.py` - DataAdapter
- [x] **B-11** `backend/api/ppt.py` - 生成端点
- [x] **B-12** 创建母版模板

## P5 爬虫模块（阻塞Toolbox前端爬虫功能）

- [x] **B-13** `backend/services/crawler_service.py` - DriverManager
- [x] **B-14** `backend/services/crawler_service.py` - PageExtractor
- [x] **B-15** `backend/api/crawler.py` - 爬虫端点

## P6 飞书集成（阻塞FeishuMail前端）

- [x] **B-16** `backend/services/feishu_service.py` - 飞书集成
- [x] **B-17** `backend/api/feishu.py` - 飞书端点

## P7 打包（收尾，依赖全部上游）

- [x] **B-18** `build.py` - PyInstaller --onefile
- [ ] **B-19** 验证exe在无Python环境运行

## P8 前端重构后端扩展

- [x] **B-20** `backend/api/dashboard.py` - Dashboard聚合+布局+分类CRUD
- [x] **B-21** `backend/api/ewo_ncr.py` - EWO/NCR CRUD
- [x] **B-22** `backend/api/tir.py` - TIR CRUD
- [x] **B-23** `backend/services/db.py` - 新增4张表（deliverable_categories/dashboard_layouts/ewo_ncr/tir）

---

## F1 前端API封装层（阻塞全部前端页面）

- [x] **F-01** `src/services/api.ts` - fetch封装+所有API调用函数

## F2 Dashboard（依赖F-01 + B-04）

- [x] **F-02** KPI卡片对接/api/issues/stats
- [x] **F-03** 数据表格对接/api/issues（分页+筛选）
- [x] **F-04** 进度面板对接/api/milestones
- [x] **F-05** 操作按钮：新建->POST /api/issues，导出周报->POST /api/ppt/weekly

## F3 Toolbox（依赖F-01 + B-07 + B-11 + B-15）

- [x] **F-06** Excel合并
- [x] **F-07** Excel改名
- [x] **F-08** PPT生成
- [x] **F-09** 爬虫工具
- [x] **F-10** 飞书同步按钮

## F4 Analytics（依赖F-01 + B-04）

- [x] **F-11** 环形图对接/api/issues/stats达成率
- [x] **F-12** 柱状图对接department_stats
- [x] **F-13** 面积图对接trend数据

## F5 FeishuMail（依赖F-01 + B-17）

- [x] **F-14** 邮件列表对接/api/feishu/mails
- [x] **F-15** 同步按钮对接POST /api/feishu/sync
- [x] **F-16** 待办列表对接/api/feishu/todos + 切换状态
- [x] **F-17** AI提醒区域

## F6 离线处理（依赖F-01）

- [x] **F-18** `src/components/OfflineBanner.tsx` - 全局离线提示条
- [x] **F-19** App.tsx启动时检测后端可用性

---

## P5 前端界面重构（2026-06-07 完成）

> 设计文档: DESIGN_FRONTEND_REDESIGN.md

### Phase 1: 基础重构

- [x] **F-R01** Sidebar.tsx - 品牌名 PM TOOLBOX -> VSE TOOLBOX
- [x] **F-R02** Sidebar.tsx - 菜单项精简为3项（数据分析看板/工具矩阵/飞书邮件助手）
- [x] **F-R03** TopBar.tsx - 更新 pageTitles 映射
- [x] **F-R04** App.tsx - 默认页改为 analytics，路由更新

### Phase 2: 子页面体系

- [x] **F-R05** types/index.ts - 新增 DeliverableCategory, LayoutCard, DashboardOverview, EWOItem, TIRItem 类型
- [x] **F-R06** pages/AnalyticsLayout.tsx - 数据分析看板容器组件（子页面路由）
- [x] **F-R07** components/SubPageNav.tsx - 底部子页面导航栏
- [x] **F-R08** pages/AnalyticsOverview.tsx - 项目总览首页（KPI+图表+里程碑）
- [x] **F-R09** pages/DeliverableIssues.tsx - 造车问题子页面（从Dashboard迁移）
- [x] **F-R10** pages/DeliverableEWO.tsx - EWO/NCR 子页面（已对接后端API）
- [x] **F-R11** pages/DeliverableTIR.tsx - TIR 子页面（已对接后端API）

### Phase 3: 拖拽卡片系统

- [x] **F-R12** 安装 react-grid-layout
- [x] **F-R13** components/DraggableGrid.tsx - 磁吸卡片网格容器
- [x] **F-R14** components/DraggableCard.tsx - 可拖拽卡片组件
- [x] **F-R15** config/defaultLayouts.ts - 默认卡片布局配置
- [x] **F-R16** CSS 拖拽样式（index.css）
- [x] **F-R17** DraggableGrid 集成到 AnalyticsOverview/DeliverableEWO/DeliverableTIR

### Phase 4: 后端 API 扩展

- [x] **F-R18** backend/api/dashboard.py - deliverable_categories CRUD + layouts CRUD + overview 聚合
- [x] **F-R19** stores/appStore.ts - 扩展 activeSubPage/deliverableCategories/dashboardOverview/layouts/ewos/tirs 状态

### Phase 4b: EWO/NCR + TIR 数据层

- [x] **F-R20** 后端: ewo_ncr 表 + CRUD API
- [x] **F-R21** 后端: tir 表 + CRUD API
- [x] **F-R22** 前端: DeliverableEWO 页面数据填充
- [x] **F-R23** 前端: DeliverableTIR 页面数据填充

---

## 外部依赖（人工）

- [!] **H-01** IT审批：申请 open.feishu.cn 加入白名单
- [x] **H-02** 提供WebDriver：chromedriver.exe + msedgedriver.exe 放入drivers/
- [!] **H-03** 公司环境测试：按TEST_GUIDE.md执行6轮30项测试

---

## 当前阻塞图

```
后端：全部完成
  B-01~B-23 ✅ DONE
  B-19(验证exe) ⏳ 待公司环境测试

前端：全部完成
  F-01~F-19 ✅ DONE
  F-R01~F-R23 ✅ DONE

待办：
  H-01(IT审批) - 飞书白名单
  H-03(公司环境测试) - 按TEST_GUIDE.md执行
```

**结论：后端+前端开发全部完成。前端重构 Phase 1-4b 全部完成。当前阻塞于 H-01(IT审批)和 H-03(公司环境测试)。**

---

## 进度摘要

| 模块 | 后端 | 前端 | 状态 |
|------|------|------|------|
| 基础框架 | 3/3 | 1/1 | 完成 |
| 问题追踪 | 2/2 | 5/5 | 完成 |
| Excel | 2/2 | 5/5 | 完成 |
| PPT | 5/5 | 3/3 | 完成 |
| 爬虫 | 3/3 | 2/2 | 完成 |
| 飞书 | 2/2 | 4/4 | 完成 |
| 打包 | 1/2 | - | 待验证exe |
| 前端重构 | 4/4 | 23/23 | 完成 |
| **总计** | **22/23** | **43/43** | **待H-01+H-03** |

最后更新：2026-06-07