# VSE Toolbox 前端美化并行实施计划

## 目标

在不破坏现有前端的前提下，先创建一套可以独立运行、独立对比的新版前端。新版前端必须与当前功能原子级对齐：页面入口、导航、主题切换、Overview 数据展示、Aras 查询模式、表单字段、请求载荷、结果渲染、错误展示、敏感信息脱敏、移动端布局都要保持行为一致。对比测试通过后，再用新版前端替换当前前端。

## 不可变约束

- 第一阶段不得修改现有线上前端文件：
  - `web/templates/dashboard.html`
  - `web/static/style.css`
  - `web/static/app.js`
- 第一阶段只新增并行前端文件，不删除、不重命名、不覆盖现有文件。
- 新版前端必须复用现有后端 API，不改变任何 API 路由、字段名、请求方法或响应结构。
- 不得删除或削弱现有敏感信息脱敏逻辑。
- 不得引入需要联网下载的运行依赖。
- 不得把界面改成营销页；新版应仍然是本地操作台和 Aras 查询工作台。
- 视觉方向以根目录 `DESIGN.md` 为准：cream canvas、coral primary、dark product surface、serif display heading、humanist sans body、低阴影、hairline border、8/12/16px 圆角层级。

## 建议新增文件

第一阶段新增以下并行前端：

- `web/templates/dashboard_redesign.html`
- `web/static/redesign/style.css`
- `web/static/redesign/app.js`

同时新增一个独立预览入口：

- 在 Flask 应用中增加 `/redesign` 页面路由，渲染 `dashboard_redesign.html`。
- `/redesign` 只用于预览新版前端，不影响 `/` 当前页面。
- `/redesign` 页面继续调用现有接口：
  - `GET /api/overview`
  - `POST /api/aras/ewo/query`
  - `POST /api/aras/paa/query`
  - `POST /api/aras/paa/crawl-all`
  - `POST /api/aras/ncr/progress`
  - `POST /api/aras/ncr/detail`

如果执行者认为添加 `/redesign` 路由也属于过早触碰后端，可改为创建独立静态预览目录 `redesign-preview/`，但最终对比测试仍需接入真实 API 完成。

## 原子级功能对齐清单

新版前端必须逐项对齐当前行为。

### 页面与导航

- 默认进入 Overview 视图。
- 顶部导航包含 Overview、Aras、Settings disabled 三个入口。
- 点击 Overview 时显示 Overview 面板，隐藏 Aras 面板。
- 点击 Aras 时显示 Aras 面板，隐藏 Overview 面板。
- `session-title` 在 Overview 与 Aras 间正确切换。
- `command-label` 在 Overview 显示 `ready`，在 Aras 显示当前 Aras 模式。

### 主题切换

- 支持 Light/Dark 切换。
- 使用同一个本地存储 key：`vse-toolbox-theme`。
- 无本地存储时尊重系统深色偏好。
- 切换后 `body[data-theme]` 与按钮文字同步更新。
- 刷新页面后保持上次主题。

### Overview 数据

- 页面加载后请求 `/api/overview`。
- Projects、Deliverable Flow、Feishu Sync 三张卡片正常展示。
- 状态 key 到展示文案的映射保持一致。
- 状态色彩语义保持一致：
  - success/synced/done/complete/completed/closed 为成功语义。
  - pending/open/pending_sync 为警告语义。
  - failed/blocked 为错误语义。
- 加载失败时三张卡片都展示错误信息。

### Aras 模式

必须保留五个模式：

- EWO
- PAA
- PAA All
- NCR Progress
- NCR Detail

模式切换要求：

- 当前模式按钮有 active 状态。
- `body[data-current-command]` 正确更新。
- `command-label` 正确更新。
- EWO 显示 EWO 字段组。
- PAA 与 PAA All 显示 PAA 字段组。
- NCR Progress 与 NCR Detail 显示 NCR 字段组。
- 切换模式后清空上一次错误和结果展示。

### Aras 表单字段

新版字段名称必须与当前字段名称完全一致。

Connection 字段：

- `base_url`
- `cookie`
- `headers`

EWO 字段：

- `ewo_no`
- `project_code`
- `subject_keyword`
- `change_type`
- `change_sub_type`
- `area`
- `state`
- `rsp_department`
- `submit_start`
- `submit_end`
- `page`
- `page_size`
- `max_records`

PAA 字段：

- `paa_no`
- `ewo_no`
- `state`
- `area`
- `base`
- `vehicle_keyword`
- `submit_start`
- `submit_end`
- `mtl_rq_start`
- `mtl_rq_end`
- `page`
- `page_size`
- `max_records`
- `max_pages`

NCR 字段：

- `buy_start`
- `buy_end`
- `pe_start`
- `pe_end`
- `ncr_no`
- `project_names`
- `section_code`
- `change_type`
- `othercondition`

默认值必须保持：

- EWO/PAA `page = 1`
- EWO/PAA `page_size = 50`
- EWO/PAA `max_records = 2000`
- PAA All `max_pages = 20`
- NCR `othercondition = 0`

### 请求载荷

请求载荷必须与当前前端一致。

公共字段：

```json
{
  "base_url": "...",
  "headers": {},
  "cookie": "...",
  "filters": {}
}
```

要求：

- `headers` 继续支持多行 `Key: Value` 输入。
- `headers` 继续支持逗号分隔的 `Key: Value` 片段。
- `cookie` 单独读取，并以 `cookie` 字段发送。
- filter 字段名不得改变。
- number 字段转换为数字。
- NCR 的 `project_names` 继续按英文逗号拆成数组。
- 查询运行中再次提交时，继续保持排队语义：当前请求结束后自动运行一次排队请求。
- 请求结束后前端内存中的 payload cookie 必须清空。

### 结果渲染

Rows 类型结果：

- 展示 meta：`page`、`rows`、`items`。
- 表格列优先使用当前 preferred columns。
- 额外字段按字母排序补充。
- 最多展示 12 列。
- 空结果显示 `No results`。
- 表格横向溢出可滚动。

Summary 类型结果：

- 以 key/value 表格展示。
- 敏感字段不得展示。

错误结果：

- 错误区域可见。
- 错误文案必须经过敏感信息脱敏。
- 请求状态恢复后按钮可再次提交。

### 敏感信息脱敏

以下字段名或值模式不得明文出现在结果或错误展示中：

- `raw_xml`
- `file_id`
- `authorization`
- `set-cookie`
- `cookie`
- `token`
- `api_key`
- `sid`
- `sessionid`
- `csrf`
- `secret`
- `password`
- `Bearer ...`

验收时必须用包含 cookie/token/password 的模拟返回或错误文本确认脱敏仍然生效。

## 视觉实施要求

### Design token

在新版 CSS 中建立清晰变量，至少包含：

- canvas: `#faf9f5`
- surface-soft: `#f5f0e8`
- surface-card: `#efe9de`
- hairline: `#e6dfd8`
- ink: `#141413`
- body: `#3d3d3a`
- muted: `#6c6a64`
- muted-soft: `#8e8b82`
- primary: `#cc785c`
- primary-active: `#a9583e`
- surface-dark: `#181715`
- surface-dark-elevated: `#252320`
- on-dark: `#faf9f5`
- on-dark-soft: `#a09d96`
- success: `#5db872`
- warning: `#d4a017`
- error: `#c64545`

### 字体

- Display heading 使用 serif fallback：`Cormorant Garamond`, `EB Garamond`, `Georgia`, serif。
- Body/UI 使用 sans fallback：`Inter`, `Segoe UI`, system sans。
- Code/table/result 使用 mono fallback：`JetBrains Mono`, `Cascadia Code`, `Consolas`, monospace。
- 标题不要使用粗重字重；display heading 以 400 或 500 为主。
- 不要使用视口宽度驱动字体大小。

### 布局与组件

- 保持操作台优先，不做大面积营销 hero。
- 页面最大内容宽约 1200px。
- 顶部导航高度、表单密度、表格可读性适配实际工作场景。
- 卡片圆角按 8/12/16px 层级收敛。
- 阴影极少使用，主要依赖 hairline border 与色块区分层级。
- 主按钮使用 coral，hover/active 使用 darker coral。
- 表单 focus 使用 coral border 与低透明 focus ring。
- 结果区建议使用 dark product surface 风格，但必须保证表格可读。
- Overview 卡片可使用 light cream card 风格。
- 移动端保持单列、表格横向滚动、按钮触控面积不小于 40px 高。

### 禁止项

- 不要使用纯白作为主画布。
- 不要引入蓝色/紫色作为主品牌色。
- 不要把所有卡片都涂成 coral。
- 不要使用过重阴影、玻璃拟态、大渐变背景或装饰性光斑。
- 不要在表格里牺牲密度以追求营销视觉。
- 不要改变任何用户可输入字段的 `name`。

## 对比测试方式

### 第一轮：静态结构对比

打开当前 `/` 与新版 `/redesign`，逐项确认：

- 顶部品牌区、主题切换、导航入口都存在。
- Overview 三张卡片都存在。
- Aras 五个模式都存在。
- 每个模式的字段完整且字段名对应。
- Result 区域、错误区域、状态区域都存在。

通过条件：

- 新版没有遗漏现有页面上的任何功能入口。
- 新版没有增加会误导用户的未实现入口。

### 第二轮：交互行为对比

执行以下操作并对比当前 `/` 与新版 `/redesign`：

- 切换 Light/Dark，刷新后确认主题保持。
- Overview 与 Aras 来回切换。
- 依次切换五个 Aras 模式。
- 在每个模式下输入字段，确认隐藏模式字段不会污染当前模式 payload。
- 点击 Run Query 后按钮进入 running/disabled 状态。
- 请求结束后按钮恢复可用。
- 请求过程中再次提交时，确认只排队一次后续请求。

通过条件：

- 新版交互行为与当前前端一致。
- 浏览器控制台无 JavaScript 错误。

### 第三轮：API 载荷对比

对每个 Aras 模式提交一次测试请求，记录当前 `/` 与新版 `/redesign` 发出的请求 JSON。

通过条件：

- endpoint 完全一致。
- HTTP method 完全一致。
- top-level key 完全一致。
- `filters` 内 key 完全一致。
- 数字字段类型为 number。
- `project_names` 为数组。
- headers 解析结果一致。
- cookie 字段存在且内容一致。

### 第四轮：结果渲染对比

准备 rows 类型和 summary 类型响应，分别检查：

- rows 结果展示 meta。
- rows 表格列顺序符合 preferred columns。
- rows 表格最多 12 列。
- summary 结果以 key/value 展示。
- 空 rows 显示 `No results`。
- 错误响应显示错误卡片。
- 敏感字段不会显示。
- 敏感值被替换为 `[redacted]`。

通过条件：

- 当前前端能展示的信息，新版都能展示。
- 当前前端会隐藏或脱敏的信息，新版同样隐藏或脱敏。

### 第五轮：响应式与可读性

在以下宽度检查：

- 1440px
- 1024px
- 768px
- 390px

通过条件：

- 页面无横向整体滚动；只有结果表格允许横向滚动。
- 按钮文字不溢出。
- 表单 label 与 input 不重叠。
- 顶部导航在窄屏可正常使用。
- 表格 header、cell 内容可读。
- 深色主题下 contrast 足够，输入框、表格、错误文案可辨认。

## 替换条件

只有满足以下所有条件后，才能进入替换阶段：

- `/redesign` 功能对比全部通过。
- API 载荷对比全部通过。
- 敏感信息脱敏验收通过。
- 移动端布局验收通过。
- 当前 `/` 页面未被第一阶段改动。
- 新版 CSS/JS 没有依赖外网资源。
- 新版没有引入未使用的大型依赖。

## 替换步骤

替换阶段再执行以下操作：

1. 备份当前三份前端文件内容。
2. 用 `dashboard_redesign.html` 替换 `dashboard.html`。
3. 用 `redesign/style.css` 替换 `style.css`。
4. 用 `redesign/app.js` 替换 `app.js`。
5. 更新模板里的静态资源版本号，避免浏览器缓存旧文件。
6. 保留 `/redesign` 入口一个短周期作为回归对照；确认无问题后再删除预览入口和并行文件。

## 最终验收条件

替换后访问 `/`，必须满足：

- 所有功能与替换前一致。
- 所有 Aras 查询 endpoint 与 payload 保持一致。
- Overview 数据加载正常。
- Light/Dark 主题正常。
- 结果表格与 summary 正常。
- 错误与敏感信息脱敏正常。
- 控制台无 JavaScript 错误。
- 页面视觉符合 `DESIGN.md` 的 warm cream + coral + dark product surface 方向。

