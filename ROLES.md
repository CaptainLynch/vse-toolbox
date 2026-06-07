# ROLES

> **模型分工策略 + 复杂度分层规则。不确定用什么模型/模式时读此文件。**
>
> **用户终端环境**：Claude Code 与 Antigravity CLI 双开，所有角色可跨环境按需切换。

---

## 1. 双开环境模型矩阵

终端双开，两个环境随时切换。选择模型 → 进入对应环境。

| 环境 | 可用模型 | 定位 | 上下文窗口 | 输入成本($/M tokens) | 输出成本($/M tokens) |
|------|----------|------|-----------|---------------------|---------------------|
| **Claude Code** | Kimi K2.6 | 轻量快写 | 2M+ | — | — |
| | MiMo V2.5-Pro | 均衡主力 | 256K | — | — |
| | DeepSeek V4-Pro | 开源旗舰 | 1M | $1.5 | $8.0 |
| | DeepSeek V4-Flash | 经济型 | 1M | $0.14 | $0.6 |
| | DeepSeek R2 | 深度推理 | 1M | $1.5 | $8.0 |
| **Antigravity CLI** | Gemini 3.5 Flash | 主力Fast | 1M | $0.15 | $0.6 |
| | Gemini 3.1 Pro | 高端推理 | 2M | $2.0 | $10.0 |
| | Gemini 3.1 Flash-Lite | 经济型 | 1M | $0.075 | $0.3 |

> **Gemini 2.5系列已废弃（2026-10 shutdown），禁止使用。**

### 架构师模型特别对比：MiMo 2.5 Pro vs Gemini 3.1 Pro

架构师默认用 **MiMo 2.5 Pro**（稳定版+代码专门优化），以下3种情况切到 **Gemini 3.1 Pro**（Antigravity CLI）：

| 任务 | MiMo 2.5 Pro | Gemini 3.1 Pro | 推荐 |
|------|-------------|----------------|------|
| ADR编写（L4） | 推理深，多角度分析 | 2M上下文可喂更大背景 | **持平** |
| 代码审计（常规文件） | 代码理解精准，Python熟悉 | 足够但可能过度 | **MiMo** |
| 代码审计（>5000行模块） | 256K可能不够 | **2M一次审计整个子系统** | **Gemini** |
| 架构图更新 | 代码结构理解好 | **多模态可分析架构图截图** | **Gemini** |
| 跨文件阻塞诊断 | 推理链清晰 | **2M加载全项目代码定位根因** | **Gemini** |

**不用Gemini 3.1 Pro做默认的原因**：Preview版Google可能调整行为；MiMo代码领域优化对审计更精准；Claude Code调用更稳定。

### 架构师环境切换终止条件（硬性规则）

**在 Claude Code（MiMo 2.5 Pro）执行架构师任务时，检测到以下任一情况，立即终止当前任务，输出以下提示：**

```
⛔ 终止条件触发

当前任务：[审计代码 / 阻塞诊断]
触发原因：[代码量超过5000行 / 涉及5个以上文件的跨模块诊断]
MiMo 2.5 Pro 上下文（256K）不足以完整处理。

请切换到 Antigravity CLI，使用 Gemini 3.1 Pro（2M上下文）继续：
  cd ~/VSE_TOOLBOX
  antigravity-cli
  @gemini-3.1-pro

切换后将该任务重新下发。
```

| 终止条件 | 判断标准 | 切换目标 |
|----------|----------|----------|
| **代码审计超限** | 待审计文件总代码行数 > 5000 行 | Antigravity CLI + Gemini 3.1 Pro |
| **跨文件阻塞诊断** | 涉及 ≥ 5 个文件的跨模块诊断 | Antigravity CLI + Gemini 3.1 Pro |

**不触发终止的情况（继续用MiMo 2.5 Pro）：**
- 单文件 < 5000 行 → 继续
- 架构图更新（看截图）→ 触发的是另一条规则（手动切换，非终止）
- ADR编写 → 继续
- 常规阻塞诊断（< 5个文件）→ 继续

---

## 2. 角色 × 复杂度 × 环境 × 模型

三个角色均可跨环境。按复杂度选模型 → 按模型进环境。

### 2.1 架构师

架构师任务最低 L2（代码审计），**不用 Kimi**。

| 场景 | 复杂度 | 首选模型 | 环境 | 备选 |
|------|--------|----------|------|------|
| 代码审计 | L2-L3 | MiMo 2.5 Pro | Claude Code | DeepSeek V4-Pro |
| ADR 编写 | L4 | MiMo 2.5 Pro | Claude Code | DeepSeek V4-Pro |
| 架构图更新 | L3-L4 | MiMo 2.5 Pro | Claude Code | DeepSeek V4-Pro |
| 阻塞诊断 | L3 | MiMo 2.5 Pro | Claude Code | DeepSeek V4-Pro / Gemini 3.1 Pro |

### 2.2 后端工程师

| 复杂度 | 特征 | 首选模型 | 环境 | 备选模型/环境 |
|--------|------|----------|------|--------------|
| **L1** | <50行，线性逻辑 | **Kimi K2.6** | Claude Code | DeepSeek V4-Flash / Gemini 3.5 Flash (Antigravity) |
| **L2** | 50-200行，多函数协作 | **MiMo v2.5** | Claude Code | DeepSeek V4-Pro / Gemini 3.5 Flash (Antigravity) |
| **L3** | >200行，多类协作，设计模式 | **MiMo 2.5 Pro** | Claude Code | DeepSeek V4-Pro / DeepSeek R2 / Gemini 3.1 Pro (Antigravity) |
| **L4** | 架构决策，不可逆 | **MiMo 2.5 Pro** + 人工 | Claude Code | DeepSeek V4-Pro + 人工 |

### 2.3 前端工程师

| 复杂度 | 特征 | 首选模型 | 环境 | 备选模型/环境 |
|--------|------|----------|------|--------------|
| **L1** | <50行，纯UI调整 | **Gemini 3.5 Flash** | Antigravity CLI | Kimi K2.6 / DeepSeek V4-Flash (Claude Code) |
| **L2** | 50-200行，组件+数据对接 | **Gemini 3.5 Flash** | Antigravity CLI | MiMo v2.5 / DeepSeek V4-Pro (Claude Code) |
| **L3** | >200行，完整模块 | **Gemini 3.5 Flash** | Antigravity CLI | MiMo 2.5 Pro / DeepSeek V4-Pro / Gemini 3.1 Pro (Claude Code/Antigravity) |
| **L4** | 前端架构变更 | **Gemini 3.5 Flash** + 人工 | Antigravity CLI | MiMo 2.5 Pro + 人工 (Claude Code) |

---

## 3. 跨环境切换策略

### 什么时候切到 Claude Code？

- 需要 **Kimi**（中文长上下文，L1快速生成）
- 需要 **MiMo**（v2.5 均衡 / 2.5 Pro 重型，后端主力）
- 需要 **DeepSeek**（V4-Pro旗舰 / V4-Flash经济 / R2深度推理）
- 任务偏 Python 后端逻辑、算法、数据处理

### 什么时候切到 Antigravity CLI？

- 需要 **Gemini 3.5 Flash**（前端主力，代码循环强）
- 需要 **Gemini 3.1 Pro**（2M超长上下文，复杂前端架构）
- 任务偏 React 组件、UI交互、前端状态管理
- 需要多模态能力（图片理解、UI截图分析）

### 什么时候跨环境对比？

同一任务在两个环境各跑一次，选结果更好的：

| 场景 | 做法 |
|------|------|
| L3任务不确定哪个模型更强 | Claude Code(MiMo 2.5 Pro) vs Antigravity(Gemini 3.1 Pro)，对比输出质量 |
| 代码审计需要多视角 | Claude Code(MiMo 2.5 Pro) 审一遍 + Antigravity(Gemini 3.5 Flash) 审一遍，交叉验证 |
| 前端L3模块涉及复杂Python逻辑 | Antigravity(Gemini)写前端 + Claude Code(MiMo/DeepSeek)写后端API，同时推进 |
| 某个环境模型响应质量差 | 立即切换到另一个环境的等价模型 |

---

## 4. 模型选择速查卡

### 不管前端后端，按任务特征选模型

```
任务特征 → 模型 → 环境

中文理解要求高 ─────────→ Kimi K2.6 ──────→ Claude Code
快速生成boilerplate ────→ Kimi K2.6 ──────→ Claude Code
后端Python/算法/数据 ───→ MiMo v2.5 ──────→ Claude Code
后端复杂架构 ───────────→ MiMo 2.5 Pro ───→ Claude Code
逻辑密集型/数学 ────────→ DeepSeek V4-Pro ─→ Claude Code
极致低成本 ─────────────→ DeepSeek V4-Flash → Claude Code
深度推理/链式思考 ──────→ DeepSeek R2 ─────→ Claude Code

前端React/UI/组件 ──────→ Gemini 3.5 Flash ─→ Antigravity CLI
前端+图片多模态 ────────→ Gemini 3.5 Flash ─→ Antigravity CLI
超长上下文(>1M) ────────→ Gemini 3.1 Pro ───→ Antigravity CLI
前端架构设计 ───────────→ Gemini 3.1 Pro ───→ Antigravity CLI
前端极致低成本 ─────────→ Gemini 3.1 Flash-Lite → Antigravity CLI
```

### 一句话决策

| 你在做什么 | 进哪个环境 | 用哪个模型 |
|-----------|-----------|-----------|
| 写Python后端代码 | Claude Code | MiMo v2.5 (L2) / MiMo 2.5 Pro (L3) |
| 写React前端代码 | Antigravity CLI | Gemini 3.5 Flash (L1-L3) |
| 快速生成Schema/路由 | Claude Code | Kimi K2.6 |
| 复杂架构设计 | Claude Code | MiMo 2.5 Pro |
| 代码审计（多视角） | 双环境都跑 | MiMo 2.5 Pro + Gemini 3.5 Flash |
| 数据处理算法 | Claude Code | DeepSeek V4-Pro / R2 |
| CSS/UI微调 | Antigravity CLI | Gemini 3.5 Flash |
| 需要2M上下文 | Antigravity CLI | Gemini 3.1 Pro |

---

## 5. 跨环境协作协议

### 5.1 进度同步

唯一进度来源：**TODO.md**

- 在 Claude Code 完成 B-xx → 更新 TODO.md
- 在 Antigravity CLI 完成 F-xx → 更新 TODO.md
- 新对话重启（无论哪个环境）→ 先读 PROJECT.md → 读 TODO.md

### 5.2 同一任务跨环境接力

```
示例：B-09 TemplateEngine (L3)

Step 1: Claude Code (MiMo 2.5 Pro)
  └─ 写出TemplateEngine核心类（200行）
  └─ 更新TODO.md: B-09 [~]

Step 2: Antigravity CLI (Gemini 3.5 Flash)
  └─ 审查代码，发现边界条件缺失
  └─ 回到Claude Code修复

Step 3: Claude Code (MiMo 2.5 Pro)
  └─ 修复边界条件，完成测试
  └─ 更新TODO.md: B-09 [x]
```

### 5.3 阻塞处理

| 情况 | 处理 |
|------|------|
| Claude Code 中模型响应慢 | 切到 Antigravity CLI 用 Gemini 做同任务 |
| Antigravity CLI 中 Gemini 理解错需求 | 切到 Claude Code 用 MiMo/DeepSeek 重做 |
| 某个环境断网/故障 | 全部任务切换到另一环境 |
| 两个环境结果不一致 | 人工判断哪个更好，或取两者优点合并 |

---

## 6. 各角色当前任务分配

| 任务 | 角色 | 复杂度 | 推荐模型 | 推荐环境 | 状态 |
|------|------|--------|----------|----------|------|
| B-01 schemas.py | 后端 | L1 | Kimi K2.6 | Claude Code | ✅ DONE |
| B-02 db.py | 后端 | L2 | MiMo v2.5 | Claude Code | ✅ DONE |
| B-03 main.py | 后端 | L1 | Kimi K2.6 | Claude Code | ✅ DONE |
| B-04 issues API | 后端 | L2 | MiMo v2.5 | Claude Code | ✅ DONE |
| B-05 download.py | 后端 | L1 | Kimi K2.6 | Claude Code | ✅ DONE |
| B-06 excel_service | 后端 | L2 | MiMo v2.5 | Claude Code | ✅ DONE |
| B-07 excel_api | 后端 | L2 | MiMo v2.5 | Claude Code | ✅ DONE |
| B-08 chart_gen | 后端 | L2 | MiMo v2.5 | Claude Code | ✅ DONE |
| B-09 template_engine | 后端 | L3 | MiMo 2.5 Pro | Claude Code | ✅ DONE |
| B-10 data_adapter | 后端 | L2 | MiMo v2.5 | Claude Code | ✅ DONE |
| B-11 ppt_api | 后端 | L2 | MiMo v2.5 | Claude Code | ✅ DONE |
| B-12 母版模板 | 后端 | L2 | MiMo v2.5 | Claude Code | ✅ DONE |
| B-13 driver_manager | 后端 | L3 | MiMo 2.5 Pro | Claude Code | ✅ DONE |
| B-14 page_extractor | 后端 | L2 | MiMo v2.5 | Claude Code | ✅ DONE |
| B-15 crawler_api | 后端 | L2 | MiMo v2.5 | Claude Code | ✅ DONE |
| B-16 feishu_service | 后端 | L3 | MiMo 2.5 Pro | Claude Code | ✅ DONE |
| B-17 feishu_api | 后端 | L2 | MiMo v2.5 | Claude Code | ✅ DONE |
| B-18 build.py | 后端 | L2 | MiMo v2.5 | Claude Code | ✅ DONE |
| B-19 验证exe | 测试 | — | 人工 | — | ⏳ 待公司环境 |
| F-01 api.ts | 前端 | L3 | Gemini 3.5 Flash | Antigravity CLI | ✅ DONE |
| F-02~F05 Dashboard | 前端 | L2 | Gemini 3.5 Flash | Antigravity CLI | ✅ DONE |
| F-06~F10 Toolbox | 前端 | L2 | Gemini 3.5 Flash | Antigravity CLI | ✅ DONE |
| F-11~F13 Analytics | 前端 | L2 | Gemini 3.5 Flash | Antigravity CLI | ✅ DONE |
| F-14~F17 FeishuMail | 前端 | L2-L3 | Gemini 3.5 Flash | Antigravity CLI | ✅ DONE |
| F-18~F19 Offline | 前端 | L2 | Gemini 3.5 Flash | Antigravity CLI | ✅ DONE |
| H-01 IT审批 | 人工 | L4 | — | — | ⏳ 阻塞 |
| H-02 WebDriver | 人工 | L1 | — | — | ⏳ 阻塞 |

> **上表为推荐分配，实际执行时可跨环境切换。例如前端L3任务如果Gemini效果不佳，可切到Claude Code用MiMo 2.5 Pro重做。**

---

最后更新：2026-06-07（后端 B-01~B-23 全部 DONE，前端 F-01~F-R23 全部 DONE，待 B-19 验证 + H-01/H-03 外部依赖）
