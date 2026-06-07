# 快速启动 — 角色切换工作流

## 安装（一次）

```bash
# 1. 拷贝脚本到项目目录
cp pmt.sh /mnt/project/vse-toolbox/pmt.sh

# 2. 在 ~/.zshrc (或 ~/.bashrc) 中添加一行
source /mnt/project/vse-toolbox/pmt.sh

# 3. 重新加载配置
source ~/.zshrc

# 4. (可选) 设置项目路径环境变量
export VSE_TOOLBOX="/mnt/project/vse-toolbox"
```

## 核心工作流

**三步：切换 → 执行 → 标记完成**

```bash
# 第1步：切换角色（类似 git checkout 切换分支）
pmt switch backend

# 第2步：执行任务（自动使用当前角色的环境和默认模型）
pmt do "实现B-01 schemas.py" --phase "Phase 1"

# 第3步：（对话结束后）标记完成
# 手动更新 TODO.md，或继续使用同一个角色执行下一个任务
```

## 完整示例

### 终端1 — 后端开发

```bash
# 切换到后端角色
$ pmt switch backend

═══════════════════════════════════════════
  角色已切换: 后端工程师
═══════════════════════════════════════════
  环境:     Claude Code
  默认模型: MiMo v2.5
  可用模型: kimi (L1) / mimo-v25 (L2) / mimo-25pro (L3,L4) / ds-v4pro (L2-L3) / ds-v4flash (L1经济) / ds-r2 (深度推理)
═══════════════════════════════════════════

  下一步: pmt do "你的任务描述"

# 执行任务（默认模型 MiMo v2.5）
$ pmt do "实现B-01 schemas.py" --phase "Phase 1"

# 切换到L3任务，指定更强模型
$ pmt do "实现B-09 TemplateEngine" --phase "Phase 4" --model m25pro

# 快速查看可用模型
$ pmt models
```

### 终端2 — 前端开发

```bash
# 切换到前端角色
$ pmt switch frontend

═══════════════════════════════════════════
  角色已切换: 前端工程师
═══════════════════════════════════════════
  环境:     Antigravity CLI
  默认模型: Gemini 3.5 Flash
  可用模型: gemini-35flash (L1-L3主力) / gemini-31pro (L3备选,2M上下文) / gemini-31lite (L1经济)
═══════════════════════════════════════════

# 执行任务
$ pmt do "实现F-01 api.ts" --phase "Phase 1"

# 指定经济模型做简单任务
$ pmt do "调整Dashboard CSS样式" --model 31l
```

### 终端3 — 架构师（审计/ADR）

```bash
# 切换到架构师
$ pmt switch arch

═══════════════════════════════════════════
  角色已切换: 架构师
═══════════════════════════════════════════
  环境:     Claude Code (默认) / Antigravity CLI (长上下文时)
  默认模型: MiMo 2.5 Pro
═══════════════════════════════════════════

# 代码审计（默认MiMo 2.5 Pro，256K上下文）
$ pmt do "审计B-09 TemplateEngine代码"

# 如果触发终止条件（>5000行/跨5文件），自动提示：
# ⛔ 终止条件触发
# 请切换到 Antigravity CLI，使用 Gemini 3.1 Pro（2M上下文）继续

# 手动切换到Antigravity做长上下文审计
$ pmt do "审计整个PPT服务模块（5000+行）" --model gemini-31pro
```

## 命令速查

| 命令 | 作用 |
|------|------|
| `pmt switch backend` | 切换到后端角色 |
| `pmt switch frontend` | 切换到前端角色 |
| `pmt switch arch` | 切换到架构师角色 |
| `pmt status` | 查看当前角色 |
| `pmt do "任务"` | 用当前角色执行（默认模型） |
| `pmt do "任务" --model m25` | 指定模型执行 |
| `pmt do "任务" --phase "Phase 1"` | 指定阶段 |
| `pmt models` | 查看当前角色可用模型 |
| `pmt env` | 直接进入环境（不执行任务） |
| `pmt help` | 显示完整帮助 |

## 快捷别名

安装后可用更短的命令：

```bash
pmt-be    # 等价于 pmt switch backend
pmt-fe    # 等价于 pmt switch frontend
pmt-ar    # 等价于 pmt switch arch
```

## 跨环境切换场景

```bash
# 场景：后端L3任务MiMo效果不佳，切到Antigravity用Gemini试试
$ pmt switch backend
$ pmt do "实现B-13 DriverManager" --model m25pro
# (效果不佳)

$ pmt switch frontend          # 切到前端角色（Antigravity环境）
$ pmt do "用Python实现双WebDriver管理类" --model 31pro
# (Gemini的Python代码可能更适合这个特定问题)

# 场景：架构师在MiMo中触发终止条件
$ pmt switch arch
$ pmt do "审计整个后端代码库"
# ⛔ 终止：审计>5000行

$ pmt do "审计整个后端代码库" --model gemini-31pro
# 自动进入Antigravity CLI环境，用2M上下文执行
```
