# 本机 Agent 环境审计与双模式协作方案

> 状态：Historical / Consumed
> 读者：Developer、Agent（Agent 运行时历史复盘）
> 权威来源：2026-09-07 审计快照；当前规则以 `AGENTS.md` 和 `docs/ZCODE_WORKER_RUNTIME.md` 为准
> 默认读取：禁止默认读取，仅在追溯环境演进时读取

日期：2026-09-07（审计快照）。更新：2026-09-08 已按批准方案实施并验收，见 docs/ZCODE_WORKER_RUNTIME.md；下文保留实施前审计事实。用户目标：Gemini 为订阅或固定额度渠道，优先节省 Codex 额度；平时 Codex 主导，有 GLM 免费额度时 ZCode 旗舰主导。

## 已核实的环境

| 组件 | 本机证据 | 结论 |
| --- | --- | --- |
| Codex CLI | PATH 版本 0.146.1；config.toml 默认 gpt-6-astra / medium，multi_agent 开启 | 可担任主代理；桌面任务设置可覆盖全局默认 |
| Codex AGY 角色文件 | agy_gemini_agent、agy_gemini_flash 指定 model_provider=agy；当前全局 config.toml 无对应 provider | 有角色文件不等于有可用模型路由，当前任务也未验证这条执行路径 |
| ZCode CLI | 本地 zcode.cmd 指向 D:/zcode/resources/glm/zcode.cjs；版本 0.16.5；doctor 通过 | 本机存在正式 CLI 入口 |
| ZCode CLI 默认 | ~/.zcode/cli/config.json model=opencode-go/glm-5.3-flash | 不可把裸命令当作 Gemini worker |
| ZCode 桌面模型 | ~/.zcode/v2/config.json 包含 Gemini 自定义提供商及 gemini-3.8-flash-high、gemini-3.1-pro-low、gemini-pro-agent 等 | 目录配置已存在；实际代理上游与剩余额度未验证 |
| ZCode 内置子代理 | agents-state.json 的 general-purpose / Explore 均固定 Gemini 3.8 Flash High；思考覆盖表为空 | 模型固定正确；该 Flash 条目的默认推理档为 high，且仅声明 high |
| ZCode 自定义探索 | readonly-explorer 实际 GLM-5.3-Flash，描述却要求 AGY Gemini；白名单无该 MCP | 明确的角色与路由残留 |
| ZCode 自定义审查 | code-reviewer 固定 Gemini 3.8 Flash High；injectAgentsMd=false | 可保留；适用项目约束必须由委派合同补足 |
| AGY CLI | 1.1.25；agy models 成功列出 3.8/3.7 Flash 多档、3.1 Pro 等 | 清单可读不代表工具执行或账户额度已验证 |
| 项目 supervisor | tools/agents + .agents/config.json 当前 worker=agy-cli，独立 worktree，默认 agy-heavy | 任务合同、隔离、证据和验收基础可复用；并非 ZCode worker |
| 旧 ZCode MCP | cli/config.json 启用 agy-subagent；脚本固定 VSE 主目录，带 dangerously-skip-permissions | 与项目现有规则冲突；本次未运行，不宜作为新方案入口 |
| Claude Code | CLI 2.1.179；配置 sonnet[1m]，自定义渠道环境键存在 | 备用，未验证模型请求或额度 |
| Gemini CLI | 安装包 0.45.2；配置 oauth-personal，7 个 MCP | 独立备用环境，不等同 ZCode 的 Gemini 提供商 |
| DeepSeek | 官方 Harness 包装脚本存在，另有旧 worker 角色与 hook 文件 | 仅用户明确选择 DeepSeek 时使用；本次未调用 |

## 关键兼容性发现

- zcode --max-turns 1 --help 与 zcode --settings <占位文件> --help 实测 Unknown option；帮助文字与本机参数解析不一致。
- 本机解析代码也未定义 allowed-tools、max-turns、settings 等帮助宣称的参数。不得基于帮助复制出未经验证的受限 worker 命令。
- --prompt 帮助标注默认 yolo；现有用户 permission.mode=plan。新入口必须显式设置模式并验证生效，不能依赖默认值。
- 本机 bundle 定义 session/create、session/setModel、session/setThoughtLevel、session/setMode、session/send、session/stop、session/events 等 app-server 方法。存在方法不等于适配已完成；协议字段、结果及权限仍需探针验证。
- Codex 当前工具沙箱进程曾返回 helper_unknown_error: setup refresh had errors；缩小后的只读命令经审批成功。不能把该现象直接归因为 ZCode 或 AGY，也不能保证未来无人值守子进程可运行。
- 当前项目无已跟踪文件修改；原有四个未跟踪文件保持不动。本次不执行模型生成、不更改全局设置、不验收应用功能。

## 接入方案比较

1. 继续旧 AGY：复用成本低，但不符合用户期望的 ZCode Gemini 路径；旧 MCP 有权限与目录问题，项目记录还有历史 headless 拒绝。仅作为备用，不能据历史断言新版仍失败。
2. 裸 ZCode --prompt：简单，但当前默认模型不匹配，帮助参数存在实测缺口。暂不作为自动实现入口。
3. ZCode app-server 适配器：推荐先验证。允许显式选择每个会话的模型与权限，避免来回改桌面默认；复用现有合同、worktree、检查和结果记录。属于待实现方案，不声称已跑通。

## 推荐运行模式

### 常态：Codex 主导

Codex 定义需求、接口与不变量 -> 本地调度适配器 -> ZCode Gemini 独立 worker -> focused checks -> Codex 检查差异与最终验收。

- Worker 直接以 Gemini 运行，不先启动 GLM 主代理再转派。
- Codex 只处理高判断工作、合同、风险与最终集成，不与 worker 重复探索和逐行生成同一实现。
- 一项合同涵盖一组相关实现与测试，不按每个函数拆成小代理。
- 简单低风险改动由 Codex 检查差异和测试即可；有风险时一次独立 Gemini review；关键安全与架构结论仍由 Codex 裁决。

### 免费额度期：ZCode GLM 主导

ZCode 选择账户当时实际可用且免费的 GLM 旗舰 -> Gemini worker 承担机械批量工作 -> GLM 集成验证。Codex 仅在主动升级的架构、复杂根因或高风险阶段参与。

- 不同时维持 Codex 与 GLM 两个实时主控。
- 免费额度不可用时停止该路由，记录交接摘要；不静默转到付费 GLM 或 Codex。
- 项目不写死 glm-5.2；逻辑角色 glm-lead 在本机映射到实际模型。当前本地与官方目录均出现 GLM-5.3，但账户免费可用性仍以账户页面为准。

## 调度合同与预算

逻辑角色仅定义 lead、worker、reviewer；worker/reviewer 默认采用已配置且验证通过的 Gemini Flash High。用户以省 Codex 额度为主，不为了降低 Gemini 推理档而增加返工。

每个任务记录：task_id、runtime、provider/model、base_commit、worktree、目标、允许路径、接口约束、验收场景、验证命令、超时、修复次数上限、状态、patch/证据位置、用量（若提供）。不复制密钥、完整会话或生产数据。

- 默认一名 worker；文件无交叉时最多两名。每个可写 worker 独立工作树，启动前处理当前未提交依赖。
- 建议起始预算：探索 3–5 分钟，普通实现 10–20 分钟，独立审查 5–10 分钟；最多两轮有针对性的修复。由外层进程和状态机实施，不依赖当前无效的 max-turns 参数。
- 超时必须终止对应进程树并确认停止，再允许其他写者进入该工作树。
- 权限拒绝、认证失败、模型不匹配、配额不足分别记录；不伪装成成功，不无上限重试或静默切换计费渠道。
- 结果尽量控制在 600–1000 个中文字符；严重问题不可为字数限制省略。完整日志留本地，仅回传失败摘要与位置。
- 指标首先看 Codex 消耗/已验收任务，其次是完成时间、返工次数及 Gemini 额度，不追求总体 token 数最低。

## 文件整理建议（均待实施）

- ~/.codex/AGENTS.md：Codex 作为主控时的 ZCode worker 入口；DeepSeek 保留显式选择条件。
- ~/.zcode/AGENTS.md：新增短规则，区分 GLM lead 与受合同约束的 worker，不复制项目知识。
- ~/.zcode/agents/readonly-explorer.md：移除 AGY 转发，直接 Gemini，保留 Read/Grep/Glob 的硬工具白名单。
- ~/.zcode/agents/code-reviewer.md：保留证据导向审查，按需简化联网工具。
- 项目 AGENTS.md：共享工程规则与记忆协议保留；替换过期运行时路由和写死主模型；明确当前主控唯一。
- tools/agents：保留隔离与检查模块，增加 ZCode app-server 适配层；不要另建一套重复 supervisor。高风险任务留当前 Codex 处理，避免 supervisor 又启动第二个 Codex 规划器。
- 旧 AGY MCP 与不再使用的角色：在新入口验收后停用，先备份，保留回滚，不批量删除。

## 实施验收顺序

1. 无生成握手：确认 app-server 协议、会话模型引用和权限状态。
2. 合成只读探针：Gemini 必须实际调用 Read 读取指定文件；确认结果来自目标提供商，并验证写工具不可用。
3. 临时独立仓库探针：修改唯一允许文件、运行小测试；检查范围外改动和权限请求如何被处理。worktree 不是操作系统安全沙箱，不能把提示词 scope 当硬权限。
4. 注入失败：错误模型、超时、工具拒绝、额度不足；验证不回退、不挂起、不残留写进程。能离线模拟的失败优先离线模拟。
5. 两种主控模式各完成一个低风险项目任务，记录用量与返工，再更新默认规则。

## 参考

- ZCode 子智能体：https://zcode.z.ai/cn/docs/subagents
- ZCode 模型和套餐：https://zcode.z.ai/cn/docs/configuration
- Codex 非交互模式：https://learn.chatgpt.com/docs/non-interactive-mode
- 本地事实优先于旧文档与帮助；提供商模型 ID 和上下文值是配置，不能证明真实上游型号、能力或计费。
