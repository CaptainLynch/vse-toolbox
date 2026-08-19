# VSE Toolbox Interface Refactor Task List

日期: 2026-06-27  
执行角色: Worker  
架构来源: `docs/agents/implementation_plan.md`

## 总规则

- 只做 scoped edits。当前工作树已有用户/历史改动，尤其 `main.py` 已脏；不得回滚、清理、重排无关变更。
- 禁止 `git reset --hard`、`git checkout -- <file>`、批量格式化整个仓库。
- 本轮允许修改的生产文件仅限: `main.py`、`web/app.py`、`web/templates/dashboard.html`、`web/static/style.css`、`web/static/app.js`、新增 `core/redaction.py`。
- 允许修改测试文件: `tests/test_aras_cli_web.py`、`tests/test_credential_safety.py`，必要时最小扩展相关现有测试。
- 不修改 `services/aras_crawler.py`，除非现有 PAA DTO/API 与 Web 接入出现明确测试阻塞；如必须修改，先在交付说明中解释原因。
- 不访问真实内网/外网，不写真实 Cookie、Authorization、token、session、csrf。

## 前端美化替换专项（阶段二）

> 本专项独立于下方已完成的 A-F 历史任务执行。Worker 执行阶段二时逐项把本节 `[ ]` 改为 `[x]`，不得把旧版深色工作台任务作为当前视觉目标。

- [x] **R0. 替换准入复核**
  - 前置: [ ] 无
  - 操作: 重新阅读 `FRONTEND_REDESIGN_EXECUTION_PLAN.md` 的“替换条件”与“替换步骤”，确认阶段二采用更严格策略：新版接管 `/`，临时 `/redesign` 路由退场。
  - 检查: 确认以下文件存在且可读取：`web/templates/dashboard_redesign.html`、`web/static/redesign/style.css`、`web/static/redesign/app.js`。
  - 约束: 开始前运行 `git status --short`；不得回滚、删除或整理无关脏改。
  - 验收: 交付说明写明已复核替换条件，并列出本次开始前观察到的相关脏文件。

- [x] **R1. 覆盖前契约核对**
  - 前置: [ ] R0
  - 操作: 对照旧版 `/` 与新版 `/redesign`，核对功能入口、API 契约、Aras 表单字段与脱敏逻辑。
  - 必查功能: Overview/Aras 导航、Light/Dark 主题、Overview 三张卡片、EWO、PAA、PAA All、NCR Progress、NCR Detail、结果区、错误区、running/queued submit 状态。
  - 必查 API: `GET /api/overview`、`POST /api/aras/ewo/query`、`POST /api/aras/paa/query`、`POST /api/aras/paa/crawl-all`、`POST /api/aras/ncr/progress`、`POST /api/aras/ncr/detail` 的 endpoint、method、top-level key、`filters` key 不变。
  - 必查字段: `base_url`、`cookie`、`headers`、所有 EWO/PAA/NCR 字段 `name` 不变；数字字段仍转换为 number；`project_names` 仍按英文逗号拆成数组。
  - 必查安全: `raw_xml`、`file_id`、`authorization`、`set-cookie`、`cookie`、`token`、`api_key`、`sid`、`sessionid`、`csrf`、`secret`、`password`、`Bearer ...` 不得在结果或错误展示中明文出现。
  - 验收: 若任一项不一致，先修复 redesign 文件再进入覆盖；不得用覆盖旧文件的方式掩盖契约差异。

- [x] **R2. 使用 redesign 模板彻底覆盖旧 HTML**
  - 前置: [ ] R1
  - 目标文件: `web/templates/dashboard.html`
  - 操作: 用 `web/templates/dashboard_redesign.html` 的完整内容覆盖 `web/templates/dashboard.html`，不得只挑选片段手工移植。
  - 必改引用: 覆盖后把 HTML 中 CSS/JS 引用从 `/static/redesign/style.css`、`/static/redesign/app.js` 改为正式路径 `/static/style.css`、`/static/app.js`；可同步更新版本号以避开浏览器缓存。
  - 约束: 保留页面运行所需 ID 和 `name`；不写真实默认 `base_url`、Cookie、Authorization、token。
  - 验收: `web/templates/dashboard.html` 中不再引用 `/static/redesign/`，且 `/` 能加载正式 CSS/JS。

- [x] **R3. 使用 redesign CSS 彻底覆盖旧 CSS**
  - 前置: [ ] R2
  - 目标文件: `web/static/style.css`
  - 操作: 用 `web/static/redesign/style.css` 的完整内容覆盖 `web/static/style.css`，不得把旧深色系统残留混入正式样式。
  - 视觉目标: 对标 Claude 桌面端官方美学（Warm Cream + Coral Primary + Serif Display Heading），保留 cream canvas、coral primary、dark product surface、serif display heading、humanist sans body、hairline border、低阴影。
  - 约束: 不引入 CDN、外部字体、蓝紫主品牌色、装饰性 orb/bokeh、纯渐变 hero。
  - 验收: 正式 CSS 中包含 warm cream/coral/serif token，移动端布局不发生整体横向溢出。

- [x] **R4. 使用 redesign JS 彻底覆盖旧 JS**
  - 前置: [ ] R2
  - 目标文件: `web/static/app.js`
  - 操作: 用 `web/static/redesign/app.js` 的完整内容覆盖 `web/static/app.js`，不得手工拼接新旧状态机。
  - 约束: 保持现有 API endpoint、payload 结构、Aras mode 配置、preferred columns、queued submit、payload cookie 清理、结果/错误脱敏行为。
  - 验收: EWO/PAA/NCR 五个模式均可构造正确 payload；`cookie`、`authorization`、`token` 等敏感值不会被持久化到 `localStorage`、`sessionStorage` 或 URL。

- [x] **R5. 删除临时 `/redesign` 路由**
  - 前置: [ ] R2, [ ] R3, [ ] R4
  - 目标文件: `web/app.py`
  - 操作: 删除临时预览入口 `@app.route("/redesign")`、`def redesign()` 及其 `render_template("dashboard_redesign.html")` 返回逻辑。
  - 约束: 不改动 `/` dashboard 路由，不改动任何 `/api/*` 路由，不改动 Aras service 调用契约。
  - 验收: `rg -n "redesign|dashboard_redesign" web/app.py web/templates/dashboard.html web/static/app.js web/static/style.css` 不命中；`/` 仍渲染新版 dashboard。

- [x] **R6. 替换后功能验证**
  - 前置: [ ] R5
  - 操作:
    ```powershell
    python -m py_compile web/app.py
    python -m pytest tests/test_aras_cli_web.py tests/test_credential_safety.py -q --basetemp E:\project\vse-toolbox\.tmp_pytest -p no:cacheprovider
    rg -n "static/redesign|dashboard_redesign|@app.route\\(\"/redesign\"\\)" web/app.py web/templates/dashboard.html web/static/app.js web/static/style.css
    rg -n "cookie.*localStorage|token.*localStorage|authorization.*localStorage|sessionStorage|console\\.log\\(" web/static/app.js
    ```
  - 约束: 验证不访问真实 Aras、真实内网或外网；不得写入真实 Cookie、Authorization、token。
  - 验收: 编译和相关测试通过；静态 grep 无正式入口残留和凭据持久化风险。如环境不能运行浏览器 smoke，交付说明必须写明原因。

- [x] **R7. 交付核对**
  - 前置: [ ] R6
  - 操作: 运行 `git diff --stat` 与 `git status --short`，核对 diff 范围。
  - 约束: 本专项生产改动应集中在 `web/templates/dashboard.html`、`web/static/style.css`、`web/static/app.js`、`web/app.py`；除非另有说明，不修改 `services/aras_crawler.py` 或真实业务逻辑。
  - 验收: 交付说明列出覆盖文件、删除的临时路由、验证命令结果、未完成风险项，并确认未回滚无关改动。

## A. Preflight 与安全基础

- [x] **A0. 记录工作树状态**
  - 前置: [ ] 无
  - 操作: 运行 `git status --short`，确认已有脏文件，特别标记 `main.py`、`services/aras_crawler.py`、相关 tests 的现状。
  - 约束: 不执行任何回滚命令；不删除 `.tmp_pytest/`、spec 文件、crawl source 文件等无关未跟踪内容。
  - 验收: Worker 交付说明中包含“已观察到脏工作树，未回滚无关改动”。

- [x] **A1. 新增统一脱敏模块 `core/redaction.py`**
  - 前置: [ ] A0
  - 目标文件: `core/redaction.py`
  - 实现:
    - `redact_sensitive_text(value: object, *, limit: int | None = None, collapse_newlines: bool = False) -> str`
    - `safe_display_value(value: object, *, empty: str = "-") -> str`
    - 覆盖字段名: `authorization`、`cookie`、`token`、`api_key`、`sid`、`sessionid`、`csrf`、`secret`、`password`。
    - 覆盖形态: JSON-like、`key=value`、`Header: value`、`Bearer value`。
    - `collapse_newlines=True` 时把连续空白压成单空格；`limit` 非空时截断到指定长度。
  - 约束: `core/redaction.py` 不 import `rich`、`flask`、`requests`、DOM 相关库；不记录日志。
  - 验收: `python -m py_compile core/redaction.py` 通过；敏感值不会出现在返回文本中。

- [x] **A2. 补充脱敏测试**
  - 前置: [ ] A1
  - 目标文件: `tests/test_credential_safety.py`
  - 实现:
    - 测试 JSON-like: `{"Authorization":"Bearer abc"}`、`"token":"tok123"`。
    - 测试 header-like: `Cookie: sid=abc123`、`Authorization: Bearer xyz789`。
    - 测试 query-like: `api_key=key456&csrf=csrf789`。
    - 测试 `limit=240` 与 `collapse_newlines=True`。
  - 约束: 测试字符串使用假值，不能出现真实 host 或真实凭据。
  - 验收: `python -m pytest tests/test_credential_safety.py -q --basetemp E:\project\vse-toolbox\.tmp_pytest -p no:cacheprovider` 通过。

## B. CLI/Web Adapter 边界清理

- [x] **B1. 清理 `main.py` 的路径 bootstrap 双语义**
  - 前置: [ ] A0
  - 目标文件: `main.py`
  - 实现:
    - 把开头的 `PROJECT_ROOT = Path(__file__).resolve().parent` 改成 `BOOTSTRAP_ROOT = Path(__file__).resolve().parent`，仅用于 `sys.path.insert`。
    - 保留 `from core.runtime_paths import app_root` 后的 `PROJECT_ROOT = app_root()` 作为唯一业务路径语义。
    - 确认 `LOG_DIR = PROJECT_ROOT / "data"` 行为不变。
  - 约束: 不移动无关 imports，不格式化整个文件。
  - 验收: `rg -n "PROJECT_ROOT|BOOTSTRAP_ROOT" main.py` 显示 `PROJECT_ROOT` 不再被两次赋值。

- [x] **B2. 移除 `main.py` 重复的旧 `handle_intranet_scrape` stub**
  - 前置: [ ] A0
  - 目标文件: `main.py`
  - 实现:
    - 保留当前真正的 Aras handler: 包含 EWO、NCR 进度、NCR 明细、PAA 分页、PAA 全量五个子模式的定义。
    - 删除或改名移除早前的 P1 暂缓 stub，确保源码中只有一个 `def handle_intranet_scrape`。
    - `MENU_OPTIONS["4"]` 必须仍指向保留下来的 Aras handler。
  - 约束: 如果删除区域附近存在用户新增逻辑，先停下并说明；不要误删 Excel、Feishu、PPT handler。
  - 验收: `rg -n "def handle_intranet_scrape" main.py` 只返回一行；CLI Aras tests 仍可 monkeypatch 调用。

- [x] **B3. `main.py` 改用统一脱敏函数**
  - 前置: [ ] A1, [ ] B2
  - 目标文件: `main.py`
  - 实现:
    - `from core.redaction import redact_sensitive_text, safe_display_value`
    - `_safe_error_message(exc: Exception) -> str` 改为薄包装: `return redact_sensitive_text(exc)`
    - `_render_paa_result` 不再构造 `Exception(str(value))`，改为 `safe_display_value(row.get(key))`。
    - `_render_ewo_result` 也用同一 display-value 逻辑，避免 raw/sensitive 字段误显。
  - 约束: 不改变 ArasCrawlerClient 调用参数；不打印 raw_xml。
  - 验收: `tests/test_aras_cli_web.py::test_cli_paa_render_without_raw_xml_or_credentials` 通过。

- [x] **B4. 修复 `web/app.py` 重复 DB 实例化并改用统一脱敏**
  - 前置: [ ] A1
  - 目标文件: `web/app.py`
  - 实现:
    - 删除 `create_app()` 中重复的第二个 `db = DatabaseManager()`。
    - `_sanitize_error_message(exc)` 改为调用 `redact_sensitive_text(exc, limit=240, collapse_newlines=True)`。
    - 保持现有 `_json_error` 响应格式不变。
  - 约束: 不把 request payload、headers、cookie 写入 logger。
  - 验收: `rg -n "db = DatabaseManager\\(\\)" web/app.py` 只返回一行；现有 Flask API tests 通过。

## C. Web API PAA 能力补齐

- [x] **C1. 新增 `web/app.py` PAA payload helper**
  - 前置: [ ] B4
  - 目标文件: `web/app.py`
  - 实现:
    - 从 `services.aras_crawler` import `PAAReportFilters`。
    - 新增 `_paa_filters_from_payload(payload: dict[str, Any]) -> PAAReportFilters`。
    - 字段映射:
      - `paa_no -> filters["paa_no"]`
      - `ewo_no -> filters["ewo_no"]`
      - `state -> filters["state"]`
      - `area -> filters["area"]`
      - `base -> filters["base"]`
      - `vehicle_keyword -> filters["vehicle_keyword"]`
      - `submit_start/submit_end`
      - `mtl_rq_start/mtl_rq_end`
    - 空字符串统一转 `None`。
  - 约束: helper 不做 HTTP，不读取全局 request。
  - 验收: 单元测试可直接覆盖该 helper 或通过路由间接覆盖。

- [x] **C2. 新增 PAA 分页查询 API**
  - 前置: [ ] C1
  - 目标文件: `web/app.py`
  - 实现:
    - 路由: `POST /api/aras/paa/query`
    - 调用: `client.query_paa_report(_paa_filters_from_payload(payload), page=_positive_int(payload.get("page"), 1), page_size=_positive_int(payload.get("page_size"), 50), max_records=_positive_int(payload.get("max_records"), 2000))`
    - 响应: `{ok:true,data:{rows,page,item_ids,count}}`
    - 错误状态码与 EWO 一致: validation 400、`ArasCrawlerError` 502、未知异常 500。
  - 约束: 不返回 `raw_xml`；不保存 Cookie/header。
  - 验收: Flask test client 能拿到 PAA rows，并且响应文本不含提交的 Cookie/Authorization 假值。

- [x] **C3. 新增 PAA 全量抓取 API**
  - 前置: [ ] C1
  - 目标文件: `web/app.py`
  - 实现:
    - 路由: `POST /api/aras/paa/crawl-all`
    - 调用: `client.crawl_paa_report_all(filters, page_size, max_pages, max_records)`
    - `max_pages` 默认 20，`page_size` 默认 50，`max_records` 默认 2000。
    - 响应同 PAA 分页。
  - 约束: 只触发 service 方法，不做自动下载，不做后台缓存。
  - 验收: fake client 记录到 `method == "paa_all"`，`max_pages` 参数正确透传。

- [x] **C4. 更新 Web API tests**
  - 前置: [ ] C2, [ ] C3
  - 目标文件: `tests/test_aras_cli_web.py`
  - 实现:
    - 在现有 `FakeArasClient` 基础上覆盖 `/api/aras/paa/query` 与 `/api/aras/paa/crawl-all`。
    - 断言 PAA filters 字段、分页参数、全量熔断参数、响应 JSON。
    - 断言提交的假 Cookie/Authorization 不出现在响应文本。
  - 约束: 不访问真实 HTTP；不扩大 fixture 范围。
  - 验收: `python -m pytest tests/test_aras_cli_web.py -q --basetemp E:\project\vse-toolbox\.tmp_pytest -p no:cacheprovider` 通过。

## D. Web 前端工作台重构

- [x] **D1. 重写 dashboard HTML 为深色工作台骨架**
  - 前置: [ ] C2, [ ] C3
  - 目标文件: `web/templates/dashboard.html`
  - 实现:
    - 保留 `<link rel="stylesheet" href="/static/style.css" />` 与 `<script src="/static/app.js"></script>`。
    - 页面根结构使用 `.app-shell`、`.topbar`、`.module-nav`、`.workspace`。
    - 保留 overview 必需 ID: `overview`、`projects-body`、`deliverables-body`、`feishu-body`。
    - 保留 Aras 必需 ID: `aras-panel`、`aras-form`、`aras-base-url`、`aras-cookie`、`aras-headers`、`aras-submit`、`aras-status`、`aras-error`、`aras-result`。
    - 增加 Aras mode 按钮:
      - `data-aras-mode="ewo"`
      - `data-aras-mode="paa"`
      - `data-aras-mode="paa-all"`
      - `data-aras-mode="ncr-progress"`
      - `data-aras-mode="ncr-detail"`
    - 增加 PAA 字段组: `data-mode-fields="paa"`，包含 PAA 编号、EWO 编号、状态、区域、基地、车辆关键词、提交日期、物料需求日期、页码、每页数量、最大记录数、最大页数。
    - Cookie 输入使用 `type="password"`、`autocomplete="off"`。
  - 约束: 不放真实默认 `base_url`、Cookie、Authorization、token；不做 landing page；不把卡片套进卡片。
  - 验收: 页面 DOM 中所有 JS 依赖 ID 存在；HTML 标签闭合正确。

- [x] **D2. 重写 CSS 为 Claude Code desktop 风格深色系统**
  - 前置: [ ] D1
  - 目标文件: `web/static/style.css`
  - 实现:
    - 使用 `Inter, "SF Pro Text", "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif` 字体栈。
    - 定义 `:root` token: `--bg`、`--bg-rail`、`--surface`、`--surface-raised`、`--line`、`--text`、`--muted`、`--accent`、`--sage`、`--amber`、`--rose`、`--plum`。
    - 布局: topbar 固定高度，module nav 紧凑，overview 为 responsive grid，Aras 为两列工作台，900px 以下单列。
    - 表格: `.table-wrap` 横向滚动，`.result-table th` sticky header，单元格 `overflow-wrap:anywhere`。
    - 动效: hover/focus/loading 使用 120-180ms transition；提供 `@media (prefers-reduced-motion: reduce)` 降低动画。
    - 状态: `.is-running`、`.is-empty`、`.error-msg`、`.loading`、disabled nav/button 明确可见。
  - 约束: 不使用外部字体/CDN；不使用装饰性 orb/bokeh；不要单一紫蓝或纯蓝大屏风。
  - 验收: 桌面和窄屏没有明显重叠或横向页面溢出；按钮文字不挤出边界。

- [x] **D3. 重构 `app.js` 为显式 mode 配置和稳定列渲染**
  - 前置: [ ] D1, [ ] C2, [ ] C3
  - 目标文件: `web/static/app.js`
  - 实现:
    - 新增 `ARAS_MODES` 配置对象，至少包含 `ewo`、`paa`、`paa-all`、`ncr-progress`、`ncr-detail`。
    - 每个 mode 声明: `endpoint`、`fieldGroup`、`filterNames`、`numberNames`、`preferredColumns`、`resultKind`。
    - `endpointForMode()` 改为读取 `ARAS_MODES[arasMode].endpoint`。
    - `collectArasPayload()` 按 mode 配置采集字段；PAA 全量传 `max_pages`。
    - `renderRows(data, preferredColumns)` 先按 preferred columns 渲染，再追加 rows 中出现的非敏感字段，追加字段按字母排序，最多 12 列。
    - 过滤列名: `raw_xml`、`authorization`、`cookie`、`token`、`api_key`、`sid`、`sessionid`、`csrf`、`secret`、`password`。
    - 请求完成后在 `finally` 中清理 payload 内的 `cookie` 引用；不写 `localStorage`、`sessionStorage`、URL、`console.log`。
  - 约束: overview 加载逻辑保持可用；不引入前端框架或构建链。
  - 验收: EWO/PAA 表格列顺序稳定；NCR 摘要仍渲染 key/value；静态 grep 不命中持久化凭据逻辑。

- [x] **D4. Web 前端 smoke 验证**
  - 前置: [ ] D2, [ ] D3
  - 目标文件: 无，验证任务
  - 操作:
    - 运行 `python -m py_compile web/app.py`。
    - 运行 Web API tests。
    - 如环境允许，启动 `python -m web.app` 并人工打开 dashboard，验证 Overview 与 Aras panel 切换、窄屏布局、loading/error 状态。
  - 约束: smoke 不使用真实 Aras Cookie，不访问真实内网。
  - 验收: Worker 交付说明写明是否完成浏览器 smoke；如未完成，说明具体阻塞。

## E. CLI rich 体验重构

- [x] **E1. 建立 rich Theme 与莫兰迪色 token**
  - 前置: [ ] B1, [ ] B2
  - 目标文件: `main.py`
  - 实现:
    - 从 `rich.theme import Theme`、`rich import box` 按需导入。
    - `console = Console(theme=Theme({"vse.title": "bold #9fc7c2", "vse.subtitle": "#a7a49a", "vse.accent": "#88a6a4", "vse.error": "bold #c19191"}))`，并补齐下方列出的其他 token。
    - Theme 至少包含: `vse.title`、`vse.subtitle`、`vse.accent`、`vse.sage`、`vse.amber`、`vse.rose`、`vse.plum`、`vse.muted`、`vse.error`。
  - 约束: 只影响 CLI adapter；不把 rich 引入 `core` 或 `services`。
  - 验收: `python -m py_compile main.py` 通过；`rg -n "from rich|import rich" core services` 不命中。

- [x] **E2. 重构 `show_banner()` 与 `show_menu()`**
  - 前置: [ ] E1
  - 目标文件: `main.py`
  - 实现:
    - `show_banner()` 使用 `Panel.fit` 或 `Panel` + `Group` 输出标题、副标题、数据目录，不使用高饱和 cyan 大块。
    - `show_menu()` 使用 rich `Table` 或 `Columns`，列出编号、模块名、状态、说明。
    - Excel 标记为 `CLI`；Overview/Web 可标记为 `Web`；PPT/Feishu 若仍不可用标记为 `Paused`；Aras 标记为 `Ready`。
  - 约束: 菜单编号与 `MENU_OPTIONS` 保持一致；不删除 deferred 模块说明。
  - 验收: 录制 console 输出时能看到分组和状态；用户仍可按原编号选择。

- [x] **E3. 重构 Aras CLI 二级菜单与请求 Spinner**
  - 前置: [ ] E1, [ ] B3
  - 目标文件: `main.py`
  - 实现:
    - `handle_intranet_scrape()` 开头用 Panel 展示 Aras Cockpit 二级菜单。
    - 子模式顺序: 1 EWO、2 NCR 进度、3 NCR 明细、4 PAA 分页、5 PAA 全量、0 返回。
    - 每个 service 调用包在 `with console.status("Querying Aras", spinner="dots"):` 中。
    - PAA 全量抓取前增加 `Confirm.ask` 二次确认，默认 `False`；用户取消则返回 Aras 菜单或主菜单。
    - 查询前可显示不含凭据的 query summary: base_url origin、mode、page/page_size/max_records/max_pages。
  - 约束: 不打印 headers、Cookie、raw_xml；不自动下载 token。
  - 验收: fake client tests 仍能调用 page/full branches；取消 PAA 全量不会调用 service。

- [x] **E4. 统一 EWO/PAA 结果表格渲染**
  - 前置: [ ] B3
  - 目标文件: `main.py`
  - 实现:
    - 新增 `_select_display_columns(rows, preferred, max_columns=12) -> list[str]`。
    - 新增 `_render_report_rows(title, page, rows, item_ids, preferred_columns) -> Table`。
    - EWO preferred columns: `_no`、`eplmwriteneplcode`、`_subject`、`_area`、`_sort_type`、`_rsp_department`、`_submit_time`、`state`。
    - PAA preferred columns: `_no`、`_ewo_no`、`state`、`_area`、`_base`、`_vehicles`、`_submit_date`、`_mtl_rq_date`。
    - 过滤 sensitive/raw columns，所有 cell 通过 `safe_display_value`。
  - 约束: 表格最多 12 列；空结果显示一行 `No results`。
  - 验收: EWO/PAA render tests 通过；敏感字段不出现在 `Console(record=True).export_text()`。

- [x] **E5. 强化 CLI Prompt 输入安全与数值校验**
  - 前置: [ ] B3
  - 目标文件: `main.py`
  - 实现:
    - `_ask_aras_connection()` 的 Cookie prompt 默认 `password=True`。
    - 新增 `_ask_positive_int(label: str, default: int) -> int`，用于 page/page_size/max_records/max_pages；非法输入提示后回退默认或重新询问，不能抛出裸 `ValueError`。
    - `_ask_ewo_filters()`、`_ask_paa_filters()` 使用 `_ask_positive_int`。
  - 约束: 更新 tests 中旧的“Cookie 明文显示”断言；新验收应断言 `password=True`。
  - 验收: monkeypatch `Prompt.ask` 的 helper tests 通过；敏感输入不在 captured stdout 中出现。

- [x] **E6. 更新 CLI tests**
  - 前置: [ ] E2, [ ] E3, [ ] E4, [ ] E5
  - 目标文件: `tests/test_aras_cli_web.py`
  - 实现:
    - 更新 `test_cli_aras_connection_defaults_browser_headers`，断言空 base_url 直接返回且不会继续询问 Cookie。
    - 增加 PAA 全量取消确认测试: `Confirm.ask` 返回 `False` 时 fake client 不收到 `paa_all`。
    - 更新 EWO/PAA table title 断言，匹配新 title 文案。
    - 保留 no-auth-echo 断言。
  - 约束: 不使用真实 console 输入；全部 monkeypatch。
  - 验收: `python -m pytest tests/test_aras_cli_web.py -q --basetemp E:\project\vse-toolbox\.tmp_pytest -p no:cacheprovider` 通过。

## F. 最终验证

- [x] **F1. Python 编译验证**
  - 前置: [ ] A1, [ ] B4, [ ] E1
  - 操作:
    ```powershell
    python -m py_compile main.py web/app.py core/redaction.py
    ```
  - 验收: 命令退出码为 0。

- [x] **F2. 单元测试验证**
  - 前置: [ ] A2, [ ] C4, [ ] E6
  - 操作:
    ```powershell
    python -m pytest tests/test_credential_safety.py tests/test_aras_cli_web.py tests/test_aras_paa_crawler.py -q --basetemp E:\project\vse-toolbox\.tmp_pytest -p no:cacheprovider
    ```
  - 验收: 全部通过；若现有无关脏改导致失败，交付说明必须明确失败测试名、失败原因和是否与本任务相关。

- [x] **F3. 静态边界与凭据持久化 grep（本轮 scoped）**
  - 前置: [ ] D3, [ ] E1
  - 操作:
    ```powershell
    rg "_render_ncr" main.py tests
    rg -n "https://aras\.example|ecm\.sgmw\.com\.cn" main.py tests web
    rg -n "姝|湪|鏌|" main.py
    ```
  - 判定:
    - 第一条应看到 `main.py` 中 NCR 渲染函数定义和 `tests` 中覆盖。
    - 第二条、第三条应无命中。
    - 既有 service/core rich/UI 边界检查不在第二修复轮范围；本轮只确保新增/触达代码不引入新的 UI 反向依赖。
  - 验收: Worker 在交付说明中报告上述 scoped grep 结果。

- [x] **F4. Web 视觉与交互 smoke**
  - 前置: [ ] D4
  - 操作:
    - 打开 dashboard。
    - 验证首屏是 Overview 工作台，不是 landing page。
    - 切换 Aras Cockpit，逐个切换 EWO/PAA/PAA 全量/NCR mode。
    - 缩窄窗口到移动端宽度，确认表单和按钮不溢出。
  - 验收: Worker 交付说明包含 smoke 结果；如环境不能打开浏览器，说明原因并至少提供 DOM/API 验证结果。

- [x] **F5. 交付 diff 范围核对**
  - 前置: [ ] F1, [ ] F2, [ ] F3
  - 操作: 运行 `git diff --stat` 与 `git status --short`。
  - 验收:
    - 修改文件只包含任务允许范围。
    - 未回滚用户/历史改动。
    - 交付说明列出修改文件、测试命令、未完成/风险项。
## Worker 修复轮记录
- [x] `core/redaction.py` 保留为新增交付文件，需纳入提交。
- [x] Aras prewarm GET 合并用户 headers，并补充 GET/POST 鉴权与错误脱敏测试。
- [x] CLI 默认 Aras 地址改为示例地址，测试不再断言真实内网域名。
- [x] 修复 Aras spinner 乱码文案。
- [x] Web API 与前端结果渲染增加敏感 key/value 脱敏防线。
- [x] 清理 `main.py` 重复入口与 legacy Aras 死代码。
- [x] 修复空 `#aras-status.loading` shimmer。
