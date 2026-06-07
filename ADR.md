# ADR — Architecture Decision Records

> **记录每个架构决策的背景、选项、最终决定、原因。供后续模型理解决策背后的Why。**
> 
> **格式：编号 / 日期 / 状态（Proposed=提议 / Accepted=已采纳 / Deprecated=已废弃）**

---

## ADR-001 部署形态：PyInstaller --onefile vs 安装包

**日期**：2026-05-27 | **状态**：Accepted

**背景**：公司电脑无Python、无pip、无管理员权限，用户是PM而非技术人员。

**选项**：
- A. 用户自行安装Python + pip install → 不可行，公司无pip
- B. 提供安装包（Inno Setup/NSIS）→ 需要管理员权限安装
- C. PyInstaller --onefile 单文件exe → 双击运行，无需安装
- D. Docker容器 → 公司电脑大概率无Docker Desktop

**决定**：C（PyInstaller --onefile）

**原因**：
1. 目标用户（PM）技术水平不一，双击运行是最低门槛
2. 不触发UAC/GAC（SEC-04约束）
3. 文件大小~200MB可接受（内网U盘传输）

---

## ADR-002 Web框架：FastAPI vs Flask

**日期**：2026-05-27 | **状态**：Accepted

**背景**：需要在前端React和后端Python之间建立通信，前端托管为静态文件。

**选项**：
- A. Flask + jinja2模板 → 前后端耦合，前端React无法独立
- B. Flask-RESTful → 可以，但手动路由注册繁琐
- C. FastAPI → 自动API文档、Pydantic校验、原生async、静态文件托管

**决定**：C（FastAPI）

**原因**：
1. 自动OpenAPI文档便于前端对接调试
2. Pydantic模型复用于请求校验和响应序列化
3. 内置StaticFiles直接托管React build产物
4. Uvicorn ASGI性能优于Flask WSGI

---

## ADR-003 前后端通信：本地HTTP vs 进程内调用

**日期**：2026-05-27 | **状态**：Accepted

**背景**：前端React是浏览器应用，后端Python是独立进程，需要数据交换。

**选项**：
- A. 进程内调用（PyQt/pywebview嵌入前端）→ 前端构建复杂，技术栈不统一
- B. Eel（Python+HTML混合）→ 放弃React生态
- C. FastAPI本地HTTP服务（127.0.0.1）→ 前端fetch调用
- D. IPC/消息队列 → 过度设计，增加复杂度

**决定**：C（FastAPI本地HTTP + 前端fetch）

**原因**：
1. 前端保持标准React开发，无特殊适配
2. 后端保持标准FastAPI开发，可独立测试
3. 127.0.0.1不暴露给网络，符合安全
4. 打包后用户无感知（浏览器自动访问localhost）

---

## ADR-004 前端路由：HashRouter vs BrowserRouter

**日期**：2026-05-27 | **状态**：Accepted

**背景**：后端FastAPI托管静态文件，前端使用React Router。

**选项**：
- A. BrowserRouter → 需要后端配置所有路由fallback到index.html
- B. HashRouter → URL中带#，纯前端路由，后端无需配置

**决定**：B（HashRouter）

**原因**：
1. 后端只需mount StaticFiles到/，无需自定义路由fallback
2. 刷新页面不会404
3. 打包后前后端零配置即可工作

---

## ADR-005 PPT图表方案：matplotlib PNG插入 vs python-pptx原生图表

**日期**：2026-05-27 | **状态**：Accepted

**背景**：PPT模板需要包含图表（柱状图/折线图/饼图），需与公司暗色主题一致。

**选项**：
- A. python-pptx原生图表（Chart对象）→ 样式受限，暗色主题难实现
- B. matplotlib生成PNG → 插入幻灯片，完全控制样式
- C. 不生成图表，纯表格 → 视觉效果差

**决定**：B（matplotlib→PNG→插入）

**原因**：
1. matplotlib完全控制颜色/字体/布局，可精确匹配公司视觉规范
2. 暗色主题(#0a0a0c背景+#d4af37强调)在matplotlib中易实现
3. 插入PNG后PPT中不可编辑（对PM报告来说可接受）

---

## ADR-006 爬虫方案：selenium双浏览器 vs requests+代理

**日期**：2026-05-27 | **状态**：Accepted

**背景**：Python requests外网请求被防火墙拦截（SEC-02），内网EWO/OTS用Chrome（SEC-03）。

**选项**：
- A. requests + 系统代理 → Python请求不走白名单，被拦截
- B. requests + 手动设置Edge代理 → 复杂且不稳定
- C. selenium WebDriver控制真实浏览器 → 浏览器自带网络权限
- D. Playwright → 需要npm install，增加依赖

**决定**：C（selenium + chromedriver + msedgedriver）

**原因**：
1. WebDriver控制真实浏览器，自动继承浏览器网络权限
2. Edge自动走白名单（SEC-02），Chrome走内网（SEC-03）
3. chromedriver/msedgedriver只需exe文件，无需安装
4. 自带于drivers/目录，不依赖系统PATH（SEC-04）

**衍生决策**：维护两个WebDriver实例，auto_select_by_url(url)自动选择

---

## ADR-007 数据库：SQLite vs PostgreSQL/MySQL

**日期**：2026-05-27 | **状态**：Accepted

**背景**：需要本地持久化存储，公司电脑无数据库服务。

**选项**：
- A. PostgreSQL → 需要安装服务，违反SEC-04
- B. MySQL → 同上
- C. SQLite3 → 标准库，零依赖，单文件
- D. JSON文件 → 无查询能力，并发不安全

**决定**：C（SQLite3）

**原因**：
1. Python标准库，无需pip install额外依赖
2. 单文件(.db)，与公司文件加密系统兼容（SEC-01）
3. 足够支撑10万级数据量（PM工具数据量小）
4. 支持参数化查询防SQL注入

---

## ADR-008 离线策略：mock fallback vs 禁用功能

**日期**：2026-05-28 | **状态**：Accepted

**背景**：后端可能未启动或崩溃，前端需要优雅降级。

**选项**：
- A. 后端不可用时页面白屏报错 → 体验差
- B. 禁用所有功能，显示"请启动后端" → 可用性低
- C. 保留mock数据作为fallback，显示离线提示 → 功能可用，数据为演示数据

**决定**：C（mock fallback + OfflineBanner）

**原因**：
1. PM可以查看界面结构和功能入口
2. 离线提示明确告知数据非实时
3. 后端恢复后自动切换为真实数据

---

## ADR-009 前端状态管理：Zustand vs Redux/Context

**日期**：2026-05-27 | **状态**：Accepted

**背景**：前端需要管理全局状态（页面导航、数据缓存、侧边栏状态）。

**选项**：
- A. useState+props drilling → 代码冗长，维护困难
- B. React Context → 性能问题，rerender频繁
- C. Redux Toolkit → 学习成本高，样板代码多
- D. Zustand → 轻量，无样板，支持selector

**决定**：D（Zustand）

**原因**：
1. 代码量最少，无action/reducer样板
2. 支持selector避免不必要rerender
3. 中间件支持持久化（如需离线缓存）

---

## ADR-010 Excel合并策略：openpyxl vs pandas

**日期**：2026-05-28 | **状态**：Accepted

**背景**：需要实现多文件合并和同结构拼接两种模式。

**选项**：
- A. 纯openpyxl → 同结构拼接需要手动处理行复制，代码冗长
- B. 纯pandas → 多Sheet合并时pandas处理复杂
- C. 混合：openpyxl负责多Sheet合并，pandas负责同结构拼接

**决定**：C（混合策略）

**原因**：
1. 多Sheet合并用openpyxl（直接操作workbook/sheet）
2. 同结构拼接用pandas（read_excel→concat→to_excel一行完成）
3. 各取所长，代码简洁

---

## 变更记录

| 日期 | 变更 |
|------|------|
| 2026-05-28 | ADR-001~010 初始记录 |


---

## ADR-00X 前端界面重构：子页面体系 + 拖拽卡片

**日期**：2026-06-06 | **状态**：Accepted

**背景**：原前端有5个独立页面（Dashboard/ExcelToolbox/Toolbox/Analytics/FeishuMail），导航项过多，数据分析看板需要支持多种交付物类型（造车问题/EWO-NCR/TIR）的独立视图，且每个视图需要可自定义的卡片布局。

**选项**：
- A. 每个交付物类型独立页面+独立路由 → 路由膨胀，不利于扩展
- B. 单页面Tab切换+固定布局 → 灵活性不足
- C. AnalyticsLayout容器+子页面体系+react-grid-layout拖拽卡片 → **采用**

**决定**：C

**原因**：
1. Sidebar精简为3项，降低导航复杂度
2. 子页面体系通过底部SubPageNav切换，交互自然
3. react-grid-layout提供成熟的磁吸网格+拖拽+resize能力
4. 布局配置持久化到数据库，用户可自定义
5. 新增交付物类型只需新增子页面组件+数据库记录，扩展性好