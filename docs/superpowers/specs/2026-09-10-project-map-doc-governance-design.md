# VSE Toolbox 项目地图与 Markdown 文档治理设计

> 状态：Implemented
> 读者：Developer、Agent
> 权威来源：项目现状评估与代码/记忆清单
> 默认读取：按 Agent 读取顺序；本规格本身仅在治理任务中读取
> 更新方式：架构变更时手工更新，生成器与测试负责结构校验

## 目标

为 VSE Toolbox 建立一份根目录 Agent 项目地图，并把现有 Markdown 文档按
Active、Generated、Historical、Scratch 分类，使新会话可以通过任务路由直接
定位生产代码，避免对仓库全盘扫描和误读历史取证材料。

## 设计

- `PROJECT_MAP.md` 是面向 Agent 的短导航，不复制源代码内容。
- `tools/generate_project_map.py` 只对明确允许的生产入口、`core/`、
  `services/`、`web/` 和受控工具做 AST/文件级分析，不 import 应用模块，
  不读取原始 HAR/XML/XLSX 内容。
- 生成器输出入口、模块、符号、Web 路由、测试提示、构建入口和源码指纹；
  `--check` 用于发现地图漂移。
- `AGENTS.md` 和 `memory/CONTEXT_MANIFEST.md` 强制地图优先、作用域检索和
  默认拒绝噪声路径。
- `README.md` 仅承担用户入口和运行说明；历史计划、外部快照、会话交接稿
  不进入默认 Agent 上下文。

## 验收标准

1. `python tools/generate_project_map.py --check` 能验证提交的地图与当前
   允许范围源码一致。
2. 生成器不会将 `crawl source/`、`dist/`、`.runtime/`、历史根目录脚本等
   默认拒绝内容放入地图。
3. 地图能直接路由 WebUI、CLI、Excel Worker、Aras、TDC、项目状态、定时
   归档、认证安全和打包任务。
4. 现有 Markdown 文档有清晰的生命周期和读取策略，README 不再宣称项目
   是 CLI-only 或没有 Web 框架。
5. 新增地图测试通过，且本任务不修改业务运行代码。
