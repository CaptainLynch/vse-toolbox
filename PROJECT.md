# PROJECT

**VSE TOOLBOX** - 汽车项目管理桌面工具箱。管理车身钣金/内外饰件/灯具模块的开发任务、造车问题追踪、交付物自动生成。

> **本文档是所有AI Agent的对话重启入口。每次新对话，先读此文件，再按「读取顺序」读取子文档。**

---

## 环境约束（4条，不可违背）

| 编号 | 约束 | 代码影响 |
|------|------|----------|
| SEC-01 | 文件自动加密，非公司电脑无法打开 | 标准文件IO即可，加密对应用透明 |
| SEC-02 | 外网仅Edge白名单，Python requests被防火墙拦截 | 外网请求必须走Edge WebDriver |
| SEC-03 | 内网EWO/OTS走Chrome，飞书走Edge | 双WebDriver，按URL域名自动选择 |
| SEC-04 | GAC限制，目标用户无Python/管理员权限 | PyInstaller --onefile绿色便携 |

## 技术栈

| 前端 | 后端 | 数据 | Excel | PPT | 爬虫 | 打包 |
|------|------|------|-------|-----|------|------|
| React19+TS+Vite+Tailwind+shadcn/ui+Recharts+react-grid-layout | Python3.14+FastAPI+Uvicorn | SQLite3 | openpyxl+pandas | python-pptx+matplotlib | selenium+chromedriver+msedgedriver | PyInstaller |

## 开发环境

终端双开，按需切换：

| 环境 | 可用模型 | 适用场景 |
|------|----------|----------|
| **Claude Code** | Kimi K2.6, MiMo V2.5-Pro, DeepSeek V4-Pro/V4-Flash/R2 | 后端Python、复杂架构、中文长上下文、低成本任务 |
| **Antigravity CLI** | Gemini 3.5 Flash, Gemini 3.1 Pro, Gemini 3.1 Flash-Lite | 前端React、UI组件、多模态、代码循环 |

**跨环境策略**：后端/前端/架构师三个角色均可跨环境。按任务复杂度选模型 -> 按模型进环境。详见 ROLES.md 第3章。


## 前端导航结构（2026-06 重构后）

```
Sidebar
├── 数据分析看板 (analytics) <- 默认首页
│   ├── [首页] 项目总览 (overview)
│   ├── [子页] 造车问题 (issues)
│   ├── [子页] EWO/NCR  (ewo)
│   └── [子页] TIR       (tir)
├── 工具矩阵 (toolbox)
└── 飞书邮件助手 (feishu)

底部固定: 设置 (settings)
```

> 品牌名已从 PM TOOLBOX 更名为 VSE TOOLBOX。
> 数据库文件名 VSE_TOOLBOX.db 保持不变，避免数据迁移风险。
> 详细设计文档见 DESIGN_FRONTEND_REDESIGN.md。

## 读取顺序

每次对话重启后，按此顺序读取：

1. **PROJECT.md** <- 你正在读（本文件）
2. **ARCHITECTURE.md** <- 当前架构图+数据库结构+已确认的结论
3. **CODING_RULES.md** <- 必须遵守的硬性编码规则
4. **DESIGN_FRONTEND_REDESIGN.md** <- 前端重构设计文档（Phase 1-4）
5. **TODO.md** <- 全局任务列表（阻塞排序），确认你要做哪个
6. **ADR.md** <- 当你需要理解决策背景时读取（非必读）
7. **ROLES.md** <- 当你不确定该用什么模式/模型时读取

## 文件索引

| 文件 | 职责 | 何时读取 |
|------|------|----------|
| PROJECT.md | 入口+环境约束+技术栈+读取顺序 | **每次对话第一个读** |
| DESIGN_FRONTEND_REDESIGN.md | 前端重构完整设计文档 | 做前端重构任务时读 |
| TODO.md | 全局TODO，阻塞排序，跨模型进度同步 | 确认当前做什么任务时读 |
| ADR.md | 架构决策记录（背景->选项->决定->原因） | 需要理解决策Why时读 |
| ARCHITECTURE.md | 当前架构What（无废话，无过程） | 需要理解系统结构时读 |
| CODING_RULES.md | 硬性编码规则（How，不容置疑） | 写代码前读 |
| ROLES.md | 模型分工+复杂度分层策略 | 不确定用什么模式时读 |

## 最后更新

- 2026-05-28 v1.0 初始版本
- 2026-05-28 v1.1 更新双开环境策略（Claude Code + Antigravity CLI，三角色跨环境按需切换）
- 2026-05-28 v1.2 更新架构师模型对比（MiMo 2.5 Pro默认，Gemini 3.1 Pro用于长上下文/多模态场景）
- 2026-05-28 v1.3 增加架构师终止条件（审计>5000行/跨5文件诊断时强制切换环境）
- 2026-05-28 v1.4 后端+前端全部开发完成，TODO.md 进度已同步
- 2026-06-07 v1.5 前端重构 Phase 1-3 完成，品牌名 PM TOOLBOX -> VSE TOOLBOX，子页面体系+拖拽卡片+EWO/TIR数据层