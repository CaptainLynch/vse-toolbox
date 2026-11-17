# 顾问降级路由链评估（Opus → Astra，最新版本号）

- 日期：2026-10-22
- 范围：`~/.dsh/skills/expert-advisor`（本机 entry + core + policy + VPS bridge）
- 状态：**评估，未改任何配置或代码**（用户要求「不改，先评估」）

## 结论摘要

1. **「Opus 不可用降级到 Astra」今天就能做到，且不需要改核心代码**：
   `--provider auto --profile astra-high` 已经实现「先 Claude(Opus)，仅在订阅额度耗尽时自动切 codex-readonly(gpt-6-astra)」。
   但**默认** fallback 档位是 `sol-high`（`gpt-6-sol`），不是 Astra —— 这是当前唯一的功能缺口。
2. **不建议扩展成多跳链**（如 Claude → Astra → Sol）：核心只支持**一跳**且带账本核验
   （`FALLBACK_ROUTE` + 30 分钟内的耗尽记录复核）；多跳会破坏审计语义与预算约束，且目前没有任何
   codex 侧额度耗尽证据（caps 均为 null）。
3. **版本号现状（实测）**：
   - Astra：`gpt-6-astra` 就是目录里的**最新且唯一** Astra（"Frontier intelligence"）→ 已是最新。
   - Sol：目录最新是 **`gpt-6.1-sol`**，而顾问白名单钉的是 `gpt-6-sol`（"Previous generation"）→ **过期**。
   - Claude：policy 钉 `claude-opus-5-5`；VPS 上 Claude CLI 2.1.274 的模型目录只到 **`claude-opus-5`**，
     另有更新的 `claude-fable-5` / `claude-fable-5-1` 家族 → **pin 与 CLI 目录不一致**，且
     bridge 的 `model_note` 要求 CLI ≥ **2.1.280**，实际是 **2.1.274**（版本前提未满足，但 2026-09-27 已做过 live 验收）。
4. **账本只记录「请求的模型」，不记录「实际服务的模型」**（`advisor_core.py:710` 取的是 `cfg["model"]`）。
   因此无法从账本证明 `claude-opus-5-5` 真的被服务 —— 这是「用最新版本号」的可核验性缺口。
5. 建议的「最新版本」维护方式：**catalog 快照 + 验证日期写入 policy + 账本记录 served model**，
   而不是运行时动态解析（动态解析会让账本/复现/审计失去确定性）。

## 现状证据

### 路由实现（已核实）

- `expert_advisor.py`：`--provider auto` → 先 Claude；仅当结果是 `EXHAUSTION_CODES`
  （`usage_limit` / `usage_limit_weekly` / `subscription_limit`）时，调用一次 codex-readonly，
  并在账本写 `route=fallback_after_claude_subscription_exhausted`。
- `advisor_core.py`：
  - `EXHAUSTION_CODES = {usage_limit, usage_limit_weekly, subscription_limit}`
  - `FALLBACK_ROUTE = "fallback_after_claude_subscription_exhausted"`，`ROUTE_PROVIDER` 固定两跳映射
  - `FALLBACK_EVIDENCE_MAX_AGE = 30 分钟`（降级前会复核账本里的耗尽记录，防主代理手动模拟兜底）
  - `ADVISOR_PROFILES`：`sol-high → (gpt-6-sol, high)`、`sol-xhigh → (gpt-6-sol, xhigh)`、
    `astra-medium → (gpt-6-astra, medium)`、`astra-high → (gpt-6-astra, high)`
  - `DEFAULT_ADVISOR_PROFILE = "sol-high"`；`resolve_profile` 在非 codex-readonly 上拒绝 `--profile`
- `advisor_policy.json`：`claude.model = claude-opus-5-5`、`codex-readonly.model = gpt-6-sol`（未使用档位时）、
  `routing = {preferred: claude, fallback: codex-readonly, fallback_only_on: claude_subscription_exhausted}`

### 模型目录（实测，2026-10-22）

`codex debug models`（codex-cli 0.159.0）返回的 slug：

| slug | 说明 |
|---|---|
| `gpt-6-astra` | Frontier intelligence for the most demanding work.（唯一 Astra，最新） |
| `gpt-6.1-sol` | **Latest** workhorse model |
| `gpt-6-sol` | **Previous generation** workhorse（顾问当前钉的就是这个） |
| `gpt-reserve` / `gpt-6-luna` / `gpt-5.6-*` | 更快/更旧档位 |

本机 `~/.codex/config.toml` 默认 `model = "gpt-6.1-sol"` —— 与目录一致，说明 6.1 是当前最新 Sol。

Claude 侧（VPS `claude-advisor` 用户，CLI 2.1.274 的 bundle 内模型 id，`grep` 得出）：

- opus 家族：`claude-opus-4*` … `claude-opus-5`（**没有 `claude-opus-5-5`**）
- 另有 `claude-fable-5`、`claude-fable-5-1`（`--help` 示例把 `fable` 列在 `opus` 之前）
- `--model` 支持别名（`opus`/`sonnet`/`fable` = 最新）或全名
- `~/.claude/settings.json` 无模型 pin（只有 `autoUpdatesChannel: stable`）⇒ 模型由 bridge 按 policy 显式传入

### 本次调用账本（已核实）

```json
{"event":"launch","model":"claude-opus-5-5","effort":"xhigh","route":"preferred"}
{"event":"result","outcome":"ok","input_tokens":8450,"output_tokens":18328,"cost_usd":0.4299}
```

`result` 事件里没有 `model` 字段 —— 即「实际服务的模型」不可见。

## 三种方案与可行性

### 方案 A（零代码，今天可用）：调用时显式指定 Astra 档

```text
expert_advisor.py --provider auto --profile astra-high ...
```

- 行为：先 Claude(Opus)，额度耗尽 → codex-readonly + `gpt-6-astra` + effort high。
- 优点：不改任何文件，完全符合技能契约（唯一自动换 provider 的合法路径）。
- 缺点：依赖调用方每次都传 `--profile`；忘传就退回 `gpt-6-sol`（旧一代）。

### 方案 B（一行/一处配置，推荐作为默认）：把默认 fallback 档位改成 Astra

- 改动点（任一）：
  1. `advisor_core.py` 的 `DEFAULT_ADVISOR_PROFILE` 改为 `astra-high`（会影响所有未指定档位的 codex-readonly 调用），或
  2. `expert_advisor.py` 的 auto 分支里给 fallback 显式传 `astra-high`（只影响降级那一跳，语义最贴合「Opus 不可用降级到 Astra」）。
- 代价：`--profile` 的默认语义变化需要同步 SKILL.md 文案；账本里 `advisor_profile` 会变成 astra-high。
- 风险：`astra-high` 超时 240s（比 sol-xhigh 的 180s 长），大批量咨询时墙钟时间上升。

### 方案 C（多跳链，不推荐）：Claude → Astra → Sol → reserve

- 需要的核心改动：`ROUTE_PROVIDER` 单跳映射、`FALLBACK_ROUTE` 单一枚举、耗尽核验只认 Claude 的
  `EXHAUSTION_CODES`，都要扩成链式状态机；还要定义「codex 侧额度耗尽」如何被识别与核验
  （目前 codex 的 caps 均为 null，从未出现过耗尽）。
- 反例：一次咨询里连续降级会放大成本与延迟，且「哪一跳失败才允许继续」没有可信判据；
  审计上无法再用「route 只有两种取值」来还原事实。
- 结论：**不做**。若未来 codex 出现真实额度限制，再按同一「账本核验 + 30 分钟窗口」的模式加第二跳。

## 「最新版本号」的维护方案（建议）

1. **catalog 快照脚本**（建议新增 `scripts/advisor_model_catalog.py`）：
   - `codex debug models` → 取 slug + 描述，断言 `gpt-6-astra` / `gpt-6.1-sol` 仍在；
   - VPS 侧 grep Claude CLI bundle 的模型 id（不调用 API，不花额度），断言 pin 的 id 存在或别名可用；
   - 输出 JSON 快照 + `checked_at`，写入 policy 的 `model_verification_states`。
2. **pin 与验证日期**：`model_verified_at`、`catalog_sha` 进入 policy，账本 launch 事件带上，便于回溯。
3. **记录 served model**：要求 bridge 返回 CLI 的响应元数据（若 CLI 提供），账本 result 事件加 `served_model`；
   若 CLI 不提供，则在快照里标注「requested only」。
4. **不做运行时动态解析**：`--model opus` 这类别名会让账本无法确定实际模型，违反可复现与审计要求。

## 需要你决定的三件事

1. **默认降级档位**：是否把「auto 的 fallback」固定为 `astra-high`（方案 B）？还是保持调用方每次显式传（方案 A）？
2. **Claude 模型 id**：继续用 policy 里的 `claude-opus-5-5`（服务端接受、但 CLI 2.1.274 目录里没有），
   还是改成 CLI 目录已知的 `claude-opus-5`（或 `fable-5` 家族）？—— 这决定「最新」的判据是**服务端**还是**CLI 目录**。
3. **Sol 档位是否也更新**：`ADVISOR_PROFILES` 的 `gpt-6-sol` 是否升到 `gpt-6.1-sol`？（会影响 sol-high/sol-xhigh 两个档位）

## 附：本次评估用到的取证命令（可复现）

```text
codex --version                       # codex-cli 0.159.0
codex debug models                    # 模型目录（slug + 描述）
Get-Content ~/.codex/config.toml      # model = "gpt-6.1-sol"
ssh -F ~/.ssh/config.claude-vps claude-vps-admin 'su - claude-advisor -c "claude --version"'
ssh ... 'grep -oaE "claude-(opus|sonnet|fable|haiku)-[0-9]+(-[0-9]+)?" <bundle>'   # CLI 内模型目录
账本：~/.dsh/expert-advisor/state/ledger-2026-10-22.jsonl
```
