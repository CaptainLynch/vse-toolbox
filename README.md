# VSE TOOLBOX

汽车项目管理桌面工具箱。管理车身钣金/内外饰件/灯具模块的开发任务、造车问题追踪、交付物自动生成。

## 快速启动

### 前端开发

```bash
cd app
npm install
npm run dev
# 访问 http://localhost:5173
```

### 后端开发

```bash
cd backend
python main.py
# API 服务运行在 http://127.0.0.1:8002
```

## 技术栈

- **前端**: React 19 + TypeScript + Vite + Tailwind CSS + shadcn/ui + Recharts + react-grid-layout + Zustand
- **后端**: Python 3.14 + FastAPI + Uvicorn + SQLite3
- **工具**: openpyxl, pandas, python-pptx, matplotlib, selenium
- **打包**: PyInstaller (单文件 exe)

## 功能模块

- **数据分析看板**: 项目总览、造车问题、EWO/NCR、TIR 子页面，可拖拽磁吸卡片布局
- **工具矩阵**: Excel 合并/改名、PPT 生成、内网数据爬取
- **飞书邮件助手**: 邮件同步、待办提取

## 项目文档

| 文档 | 说明 |
|------|------|
| PROJECT.md | 项目入口（环境约束+技术栈+读取顺序） |
| ARCHITECTURE.md | 系统架构（运行时+数据库+API） |
| CODING_RULES.md | 编码规则（R-01~R-17） |
| DESIGN_FRONTEND_REDESIGN.md | 前端重构设计文档 |
| TODO.md | 全局任务列表 |
| ADR.md | 架构决策记录 |
| ROLES.md | 模型分工策略 |
| API_CONTRACT.md | 前后端接口契约 |
| TEST_GUIDE.md | 公司环境测试指南 |