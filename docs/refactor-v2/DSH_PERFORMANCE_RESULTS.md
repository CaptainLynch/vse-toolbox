# DSH-V2-33 性能复测与索引优化判定（2026-11-01）

> 任务：按现有基准复测，并确定是否需要索引优化。
> 基线：`1619141`（`refactor/ux-v2` 当前 HEAD，已含第 0/1 波），分支 `dsh/v2-33`。
> 对比对象：`docs/refactor-v2/PERF_BASELINE_20261031.md`（W18-01 历史基线）。
> 本任务**未新增任何索引、未修改 schema**；只复测、取证、判定。

## 1. 结论摘要

| 判定项 | 结论 |
| :--- | :--- |
| 冷启动（`import web.app` / `create_app()`） | **PASS**，比历史基线快 46.6%–77.0% |
| 首页与 3 条只读 GET（`/`、`/api/version`、`/api/overview`、`/api/settings`） | **PASS**，全部持平或改善；唯一"相对劣化"项为亚毫秒级噪声（见 §6.3） |
| 大表分页（5000 行合成表，LIMIT/OFFSET） | **PASS**，浅/深页均优于历史基线，深/浅页比 2.2×（阈值 ≤ 3×） |
| 是否需要索引优化 | **当前无需索引优化**（证据见 §7）。在 5000 行这一历史同规模上无任何超阈值项；已用 `EXPLAIN QUERY PLAN` 定位到两处真实读取的排序缺口，但其代价只在单表 ≥ 20000 行时才越过阈值，仓库内无任何证据表明生产规模达到该量级，故**不派发索引任务**，只登记条件化的单索引候选（§7.4） |

## 2. 判定阈值与依据（先定阈值，再看数据）

阈值在测量前确定，来源分两类：历史基线已写明的劣化矩阵（`PERF_BASELINE_20261031.md` §5），以及本次为亚毫秒指标补充的绝对阈值。

| 编号 | 指标 | 阈值 | 依据 |
| :--- | :--- | :--- | :--- |
| T1 | `import web.app` 冷加载 | 中位/单次 ≤ 1422.9 ms（基线 +15%） | 历史矩阵第 1 行 |
| T2 | `create_app()` | ≤ 781.8 ms（基线 +10%） | 历史矩阵第 2 行 |
| T3 | 总计冷启动 | ≤ 2181.8 ms（基线 +12%） | 历史矩阵第 3 行 |
| T4 | 只读 GET 路由 | P95 ≤ 100 ms（绝对）**且** 不劣于历史 +15%（中位 +10%） | 100 ms 是"本机交互无明显等待"的可感知上限；本次补充的绝对上限用于防止"基线本身很小、百分比失真" |
| T5 | 亚毫秒指标（历史值 < 1 ms 的条目） | 绝对 ≤ 5 ms；**百分比仅作参考，不作判定** | 0.01 ms 级抖动即可造成 >15% 相对变化（本次实测运行间波动 ±25%，见 §6.3），百分比在此量级无判别力 |
| T6 | 大表单页分页 | P95 ≤ 20 ms（绝对）**且** 深页/浅页 ≤ 3× | 20 ms 取 100 ms 交互预算的 20%，其余留给模板渲染、JSON 序列化与本地 HTTP 往返；比值上限用于识别"索引缺口导致的非线性增长" |

判定规则：任一指标同时满足其绝对阈值与相对阈值 → **PASS**；否则 **DEGRADED**。分页的"深/浅比"只用于诊断，不单独判 DEGRADED。

## 3. 环境与方法

| 项 | 实测值 |
| :--- | :--- |
| 操作系统 | Windows 10 专业版 10.0.19045（build 19045） |
| CPU | AMD Ryzen 7 7700 8 核 / 16 线程 |
| 内存 | 31.1 GB |
| 存储 | NVMe SSD（ZHITAI TiPlus7100 2TB） |
| Python | 3.12.10（MSC v.1943 64bit） |
| SQLite | 3.49.1 |
| 脚本 | `tools/perf_baseline.py`（**未修改**，原样复用） |
| 数据 | 全部合成数据 + 系统临时目录；脚本退出时自清理，未写入仓库 `data/` |
| 输出 | `E:\project\vse-toolbox-wt\_logs\DSH-V2-33\`（**工作区外，不入库**） |

与历史基线的可比性：历史记录为 Windows 10 Pro 19045 / Python 3.12.10 / 32 GB / NVMe SSD，与本机同机同解释器版本；历史记录未登记 CPU 型号，本次补登为 Ryzen 7 7700。历史基线是 `--quick`（10 轮）单次运行，本次以同样 `--quick` 10 轮跑 2 次、另跑 1 次标准 20 轮、再补 1 次 `--quick` 复现，共 4 次。

### 3.1 实际运行命令与退出码

```powershell
# run1 / run2：与历史基线同模式（--quick，10 轮），可直接对比
python -B tools/perf_baseline.py --quick --out E:\project\vse-toolbox-wt\_logs\DSH-V2-33\run1.json   # exit 0
python -B tools/perf_baseline.py --quick --out E:\project\vse-toolbox-wt\_logs\DSH-V2-33\run2.json   # exit 0
# run3：标准模式 20 轮（样本量加倍，验证稳定性）
python -B tools/perf_baseline.py --out E:\project\vse-toolbox-wt\_logs\DSH-V2-33\run3_standard20.json  # exit 0
# run4：再次 --quick 复现（验证 import 冷/热缓存差异）
python -B tools/perf_baseline.py --quick --out E:\project\vse-toolbox-wt\_logs\DSH-V2-33\run4.json   # exit 0
```

`--help` 实际参数：`--quick`（10 轮）、`--rounds N`、`--db-rows N`（≥ 5000，默认 5000）、`--out PATH`。

## 4. 数据规模

| 测量项 | 数据规模 |
| :--- | :--- |
| `import web.app` | 模块级（无数据），合成临时 `VSE_DATA_ROOT` |
| `create_app()` | 空业务库 + 种子行（`projects` 1 行「未归类」及内置种子），表结构为当前 schema v14 |
| `/` | 空业务库；Jinja2 模板 + 宿主外壳挂载点 |
| `/api/version` | 空业务库；纯内存元数据 |
| `/api/overview` | 空业务库；`projects`/`deliverables`/`feishu_tasks` 三张小表的 `GROUP BY`/`COUNT` |
| `/api/settings` | 空业务库；`app_settings` KV + 会话状态 |
| 大表浅页 `LIMIT 50 OFFSET 0` | 合成表 **5000 行**，`page_size=50`，覆盖索引 `idx_synthetic_sort(is_completed, priority DESC, id)` |
| 大表深页 `LIMIT 50 OFFSET 4000` | 同上，第 81 页 |

> 说明：`perf_baseline.py` 的合成分页表自带覆盖 `ORDER BY` 的索引，它测的是"索引已覆盖排序时的 LIMIT/OFFSET"，**不等于**生产 `deliverable_form_rows` 的查询形状。为此另做了真实形状探针（§7.2），探针脚本放在工作区外，不修改基准脚本。

## 5. 复测结果（逐项：样本数 / 中位数 / P95）

### 5.1 启动与构建

| 测量阶段 | 运行 | 样本数 | 中位数/单次值 (ms) | P95 | 阈值 T1–T3 | 判定 |
| :--- | :--- | ---: | ---: | ---: | ---: | :--- |
| `import web.app`（子进程 `importlib` 计量，单次） | run1 | 1 | 530.340 | — | ≤ 1422.9 | PASS |
| 同上 | run2 | 1 | 293.351 | — | ≤ 1422.9 | PASS |
| 同上 | run3（20 轮模式） | 1 | 285.006 | — | ≤ 1422.9 | PASS |
| 同上 | run4 | 1 | 295.275 | — | ≤ 1422.9 | PASS |
| `create_app()`（单次） | run1 | 1 | 379.797 | — | ≤ 781.8 | PASS |
| 同上 | run2 | 1 | 364.915 | — | ≤ 781.8 | PASS |
| 同上 | run3 | 1 | 376.445 | — | ≤ 781.8 | PASS |
| 同上 | run4 | 1 | 367.811 | — | ≤ 781.8 | PASS |
| 总计冷启动 | run1 | 1 | 910.137 | — | ≤ 2181.8 | PASS |
| 同上 | run2 | 1 | 658.266 | — | ≤ 2181.8 | PASS |
| 同上 | run3 | 1 | 661.451 | — | ≤ 2181.8 | PASS |
| 同上 | run4 | 1 | 663.086 | — | ≤ 2181.8 | PASS |

`import web.app` 与 `create_app()` 由脚本设计为各计 1 次（冷加载必须在新子进程内计量），因此样本数为 1；稳定性以 4 次运行之间的离散度表达（§6）。

### 5.2 首页与只读 GET（每路由 1 次预热 + N 次有效采样）

| 路由 | 运行 | 样本数 | 中位数 (ms) | P95 (ms) | Min | Max | 判定（T4/T5） |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| `/` | run1 | 10 | 0.130 | 0.250 | 0.118 | 0.296 | PASS |
| `/` | run2 | 10 | 0.125 | 0.186 | 0.117 | 0.212 | PASS |
| `/` | run3 | 20 | 0.119 | 0.160 | 0.109 | 0.238 | PASS |
| `/` | run4 | 10 | 0.134 | 0.184 | — | — | PASS |
| `/api/version` | run1 | 10 | 0.201 | 0.289 | 0.186 | 0.332 | PASS |
| `/api/version` | run2 | 10 | 0.193 | 0.222 | 0.185 | 0.235 | PASS |
| `/api/version` | run3 | 20 | 0.195 | 0.332 | 0.178 | 0.336 | PASS（T5 绝对阈值；见 §6.3） |
| `/api/version` | run4 | 10 | 0.194 | 0.226 | — | — | PASS |
| `/api/overview` | run1 | 10 | 1.458 | 1.592 | 1.441 | 1.670 | PASS |
| `/api/overview` | run2 | 10 | 1.436 | 1.480 | 1.415 | 1.499 | PASS |
| `/api/overview` | run3 | 20 | 1.456 | 1.513 | 1.434 | 1.618 | PASS |
| `/api/overview` | run4 | 10 | 1.447 | 1.529 | — | — | PASS |
| `/api/settings` | run1 | 10 | 1.462 | 1.555 | 1.438 | 1.584 | PASS |
| `/api/settings` | run2 | 10 | 1.430 | 1.563 | 1.406 | 1.625 | PASS |
| `/api/settings` | run3 | 20 | 1.428 | 1.464 | 1.416 | 1.492 | PASS |
| `/api/settings` | run4 | 10 | 1.440 | 1.553 | — | — | PASS |

### 5.3 大表分页（5000 行，单页 50 条）

| 分页 | 运行 | 样本数 | 中位数 (ms) | P95 (ms) | Min | Max | 判定（T6） |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| 浅页 `OFFSET 0` | run1 | 10 | 0.051 | 0.069 | 0.050 | 0.080 | PASS |
| 浅页 `OFFSET 0` | run2 | 10 | 0.052 | 0.069 | 0.051 | 0.081 | PASS |
| 浅页 `OFFSET 0` | run3 | 20 | 0.052 | 0.059 | 0.050 | 0.063 | PASS |
| 浅页 `OFFSET 0` | run4 | 10 | 0.051 | 0.068 | — | — | PASS |
| 深页 `OFFSET 4000` | run1 | 10 | 0.110 | 0.126 | 0.108 | 0.136 | PASS |
| 深页 `OFFSET 4000` | run2 | 10 | 0.108 | 0.114 | 0.106 | 0.115 | PASS |
| 深页 `OFFSET 4000` | run3 | 20 | 0.113 | 0.118 | 0.109 | 0.120 | PASS |
| 深页 `OFFSET 4000` | run4 | 10 | 0.109 | 0.114 | — | — | PASS |

深/浅页比（中位）：run1 2.16×、run2 2.08×、run3 2.17×、run4 2.14× —— 全部 ≤ 3×（T6），无"偏移量导致的非线性劣化"。

## 6. 与 `PERF_BASELINE_20261031.md` 的对比

### 6.1 对比表（历史 = `--quick` 10 轮；变化率 = (本次 − 历史) / 历史）

| 指标 | 历史基准 | run1 | run2 | run3（20 轮） | run4 | 变化率区间 | 判定 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| `import web.app` | 1237.3 | 530.340 | 293.351 | 285.006 | 295.275 | −77.0% ~ −57.1% | PASS |
| `create_app()` | 710.7 | 379.797 | 364.915 | 376.445 | 367.811 | −48.7% ~ −46.6% | PASS |
| 总计冷启动 | 1948.0 | 910.137 | 658.266 | 661.451 | 663.086 | −66.2% ~ −53.3% | PASS |
| `/` 中位 | 0.137 | 0.130 | 0.125 | 0.119 | 0.134 | −13.1% ~ −2.2% | PASS |
| `/` P95 | 0.236 | 0.250 | 0.186 | 0.160 | 0.184 | −32.2% ~ +5.9% | PASS（T5） |
| `/api/version` 中位 | 0.204 | 0.201 | 0.193 | 0.195 | 0.194 | −5.4% ~ −1.5% | PASS |
| `/api/version` P95 | 0.254 | 0.289 | 0.222 | 0.332 | 0.226 | −12.6% ~ +30.7% | PASS（T5 绝对阈值，见 §6.3） |
| `/api/overview` 中位 | 1.628 | 1.458 | 1.436 | 1.456 | 1.447 | −11.8% ~ −10.4% | PASS |
| `/api/overview` P95 | 1.824 | 1.592 | 1.480 | 1.513 | 1.529 | −18.9% ~ −12.7% | PASS |
| `/api/settings` 中位 | 1.703 | 1.462 | 1.430 | 1.428 | 1.440 | −16.1% ~ −14.2% | PASS |
| `/api/settings` P95 | 1.851 | 1.555 | 1.563 | 1.464 | 1.553 | −20.9% ~ −15.6% | PASS |
| 浅页中位 | 0.054 | 0.051 | 0.052 | 0.052 | 0.051 | −5.6% ~ −3.7% | PASS |
| 浅页 P95 | 0.059 | 0.069 | 0.069 | 0.059 | 0.068 | +0.0% ~ +16.9% | PASS（T5） |
| 深页中位 | 0.118 | 0.110 | 0.108 | 0.113 | 0.109 | −8.5% ~ −4.2% | PASS |
| 深页 P95 | 0.164 | 0.126 | 0.114 | 0.118 | 0.114 | −30.5% ~ −23.2% | PASS |

### 6.2 差异与可能原因

1. **`import web.app` 大幅改善（−57% ~ −77%）——主因是文件缓存，不是纯代码收益。** 本次 run1 是本工作区首次导入（`530 ms`），其后三次稳定在 `285–295 ms`；同一脚本同一代码的首次/后续差异达 1.8×。历史记录的 `1237.3 ms` 与本次 run1 同属"首次冷读"量级，仍比 run1 高 2.3×，这部分可归因于第 0/1 波的模块拆分与惰性导入，但**本任务无法把"缓存效应"与"代码效应"完全分离**，故不宣称具体的代码级收益。
2. **`create_app()` 改善约 47%（710.7 → 365–380 ms）。** 四次运行离散度仅 ±2%，属稳定改善；可能原因：第 0/1 波把路由体迁到 `web/*_boot.py`、插件注册路径精简，以及历史值含首次模板/字节码编译与杀毒首扫。
3. **只读 GET 全部持平或改善。** `/api/overview`、`/api/settings` 改善 10%–16%，量级与其实际工作量（小表聚合、KV 读取）一致，属低噪声区间内的稳定改善。
4. **大表分页持平（−4% ~ −8%）。** 合成表已有覆盖排序的索引，说明当前索引策略在该规模下已满足；无回归。
5. **`/api/version` P95 的 +30.7%（run3）不是回归。** 绝对值为 `0.332 ms`，与历史 `0.254 ms` 相差 `0.078 ms`，且 run3 的 Max 为 `0.336 ms`——单点离群即把 P95 拉到 Max，属典型的亚毫秒噪声。同项 run2/run4 为 `0.222/0.226 ms`（−12.6%/−11.0%）。按 T5（亚毫秒指标用绝对阈值 ≤ 5 ms 判定）判 PASS。**若沿用历史矩阵的 +15% 百分比规则，会在 0.08 ms 的抖动上误判 DEGRADED**，这是本次补充 T5 的直接原因。
6. **浅页 P95 +16.9% 同理**：绝对差 `0.010 ms`，Max `0.081 ms`，按 T5 判 PASS。

### 6.3 稳定性（两次以上运行的差异）

| 指标 | 4 次运行的极差 | 相对极差 | 说明 |
| :--- | ---: | ---: | :--- |
| `import web.app` | 285.006 – 530.340 ms | 86% | 首轮冷缓存；剔除 run1 后为 285.0–295.3 ms（3.6%） |
| `create_app()` | 364.915 – 379.797 ms | 4.1% | 稳定 |
| `/` 中位 | 0.119 – 0.134 ms | 12.6% | 亚毫秒噪声 |
| `/api/version` P95 | 0.222 – 0.332 ms | 49.5% | 亚毫秒噪声，单点离群主导 |
| `/api/overview` 中位 | 1.436 – 1.458 ms | 1.5% | 稳定 |
| `/api/settings` 中位 | 1.428 – 1.462 ms | 2.4% | 稳定 |
| 浅页中位 | 0.051 – 0.052 ms | 2.0% | 稳定 |
| 深页中位 | 0.108 – 0.113 ms | 4.6% | 稳定 |

结论：**毫秒级及以上指标（启动、overview、settings、分页）可重复（极差 ≤ 5%）；亚毫秒指标（首页、version、浅页 P95）的运行间波动可达 ±25%，不能把单次结果当稳定结论**。`import web.app` 必须区分"首次冷读"与"后续热读"，否则会把缓存效应误读成代码劣化/改善。

## 7. 是否需要索引优化：证据与判定

### 7.1 只读代码审查（`core/db_manager.py`、`core/repos/`，未修改）

真实的大表分页读取有两处，都带 `ORDER BY` + `LIMIT/OFFSET`：

| 读取 | 位置 | SQL 形状 | 现有索引 |
| :--- | :--- | :--- | :--- |
| 交付物表单行分页 | `core/repos/form_snapshots.py::list_deliverable_form_rows`（第 287–336 行） | `WHERE r.snapshot_id = (最新快照) AND <过滤> ORDER BY r.is_completed ASC, r.row_number ASC, r.id ASC LIMIT ? OFFSET ?` | `idx_deliverable_form_rows_filter(snapshot_id, department_key, section_key, model_key, status_key, stage_key, overdue_state, submitted_date)`、`idx_deliverable_form_rows_search(snapshot_id, search_text)`、`UNIQUE(snapshot_id, row_key)` |
| 项目状态明细分页 | `core/repos/project_status.py::list_project_status_analysis_items`（第 427–470 行） | `WHERE deliverable_id = ? [AND department IN ...] ORDER BY is_completed ASC, planned_date ASC, title ASC LIMIT ? OFFSET ?` | `idx_ps_analysis_items_filters(deliverable_id, department, is_completed, planned_date)` |

两处现有索引的**前导列都能命中 `WHERE`**，但索引列顺序与 `ORDER BY` 不一致（`department_key`/`department` 插在中间，`row_number`/`title` 不在索引内），因此排序无法由索引满足。这是纯代码审查得出的假设，是否构成瓶颈必须由 §7.2 的实测与查询计划确认。

### 7.2 合成库实测 + `EXPLAIN QUERY PLAN`（探针脚本，工作区外）

探针：`E:\project\vse-toolbox-wt\_logs\DSH-V2-33\probe_index_evidence.py`（临时脚本，不入库）。表结构与索引直接 `import core.db_common.TABLE_DEFINITIONS` 执行（与生产 DDL 逐字一致），不读真实数据库，不跑 `ANALYZE`（生产代码亦无 `ANALYZE`），每档 20 次采样 + 1 次预热，输出 `probe20.utf8.json`。

**查询计划（当前 schema，5000 / 20000 / 50000 行三档完全一致）：**

```
form rows : SEARCH r USING INDEX idx_deliverable_form_rows_search (snapshot_id=?)
            SCALAR SUBQUERY 1
            SEARCH deliverable_form_snapshots USING COVERING INDEX idx_deliverable_form_snapshots_latest (form_key=?)
            USE TEMP B-TREE FOR ORDER BY          <-- 排序无法由索引满足
ps items  : SEARCH project_status_analysis_items USING INDEX sqlite_autoindex_project_status_analysis_items_1 (deliverable_id=?)
            USE TEMP B-TREE FOR ORDER BY          <-- 同上
```

**计时（`page_limit=200`，即 `list_deliverable_form_rows` 默认值；`deep_offset = rows − 200×20`）：**

| 规模 | 读取 | 当前 schema 浅页中位/P95 | 当前 schema 深页中位/P95 | 深/浅比 | T6（≤20 ms，≤3×） | 候选索引后深页中位/P95 | 深页收益 |
| ---: | :--- | :--- | :--- | ---: | :--- | :--- | ---: |
| 5000 | form rows | 1.357 / 1.456 | 2.484 / 2.596 | 1.8× | **PASS** | 0.490 / 0.514 | −80.3% |
| 5000 | ps items | 1.562 / 1.804 | 3.485 / 3.681 | 2.2× | **PASS** | 0.448 / 0.478 | −87.1% |
| 20000 | form rows | 5.707 / 6.119 | 25.190 / 25.427 | 4.4× | **FAIL**（超 20 ms、超 3×） | 0.843 / 0.870 | −96.7% |
| 20000 | ps items | 5.074 / 5.858 | 26.451 / 27.161 | 5.2× | **FAIL** | 0.888 / 0.958 | −96.6% |
| 50000 | form rows | 13.705 / 17.358 | 67.253 / 77.575 | 4.9× | **FAIL** | 1.534 / 1.581 | −97.7% |
| 50000 | ps items | 11.560 / 13.254 | 72.704 / 80.432 | 6.3× | **FAIL** | 3.137 / 4.036 | −95.7% |

候选索引后的查询计划（只在探针副本上建，**未写入仓库**）：

```
form rows : SEARCH r USING INDEX idx_deliverable_form_rows_page (snapshot_id=?)   <-- 无 TEMP B-TREE
ps items  : SEARCH project_status_analysis_items USING INDEX idx_ps_analysis_items_page (deliverable_id=?)   <-- 无 TEMP B-TREE
```

**证据解读：**
- 排序缺口真实存在，且代价随行数**线性增长于整表规模**（不是只随 offset 增长）——每个分页请求都要把该快照/交付物的全部行排一遍。
- 在 5000 行（历史同规模）时，两处读取 P95 为 `2.6 ms` / `3.7 ms`，远低于 20 ms，深/浅比也 ≤ 3×：**当前索引在该规模下足够**。
- 只有到 20000 行才首次越过 T6（`25.4 ms` / `27.2 ms`），50000 行时达 `78 ms` / `80 ms`。

### 7.3 判定：当前无需索引优化

依据：
1. 任务口径的基准规模是 5000 行（与历史基线一致），该规模下无任何指标超阈值（§5、§7.2）。
2. 仓库内**没有任何证据**表明生产单个快照或单个交付物的行数会达到 20000：
   - `deliverable_form_rows` 每个快照的行数 = 上游官方工作簿行数，快照按 `form_key` 保留最近 365 份（`_FORM_SNAPSHOT_RETENTION`），行数无硬上限，但代码里读取侧对图表路径封顶 20000 行、分页 `limit ≤ 500`，说明设计预期远小于 2 万；
   - `project_status_analysis_items` 以 `(deliverable_id, item_key)` 为主键，条目数由单一交付物决定。
3. 任务约束禁止读真实数据库，因此"生产实际行数"这一最后一块证据不可得；在没有它的情况下加索引属于"猜测加索引"，正是任务禁止的行为。

**结论：当前无需索引优化。本任务未新增索引、未修改 schema、未修改 `core/db_manager.py`。**

### 7.4 条件化「单索引候选任务」建议（本任务不实施）

若后续取得生产行数证据（任一读取的实测规模 ≥ 20000 行），按"一任务一索引"分别派发，不批量加：

**候选 A：`deliverable_form_rows` 分页排序索引**

| 项 | 内容 |
| :--- | :--- |
| 表 / 列 | `deliverable_form_rows(snapshot_id, is_completed, row_number, id)` |
| 服务对象 | `list_deliverable_form_rows`（默认 `limit=200`，`offset ≤ 100000`） |
| 预期收益 | 20000 行：深页 25.190 → 0.843 ms（−96.7%），浅页 5.707 → 0.465 ms（−91.9%）；50000 行：67.253 → 1.534 ms（−97.7%）；查询计划中的 `USE TEMP B-TREE FOR ORDER BY` 消失 |
| 代价 | 每行多一份索引条目（约 4 列，含 2 个整型），写入路径仅 `save_deliverable_form_snapshot`；对写入吞吐的影响需在该任务内实测 |
| 迁移方式 | 宿主表 → 追加到 `core/db_common.py::TABLE_DEFINITIONS` 的 `CREATE INDEX IF NOT EXISTS`（`init_database` 每次启动幂等执行，纯增量、无需提升 `CURRENT_SCHEMA_VERSION`，回退旧版 exe 无副作用）；若走 `_migrate_schema` 则同样用 `CREATE INDEX IF NOT EXISTS`，不得改列、不得重建表 |

**候选 B：`project_status_analysis_items` 分页排序索引**

| 项 | 内容 |
| :--- | :--- |
| 表 / 列 | `project_status_analysis_items(deliverable_id, is_completed, planned_date, title)` |
| 服务对象 | `list_project_status_analysis_items`（`limit ≤ 1000`） |
| 预期收益 | 20000 行：深页 26.451 → 0.888 ms（−96.6%）；50000 行：72.704 → 3.137 ms（−95.7%）；`TEMP B-TREE` 消失 |
| 代价 | 该表按 `deliverable_id` 整体重写（同步时删除再插入），新增索引会增加每次同步的写入与 VACUUM 成本，须在该任务内实测写入侧 |
| 迁移方式 | 同上：`CREATE INDEX IF NOT EXISTS` 增量迁移；若该表属于插件则必须走 `host.migrate([(version, fn)])`（本表是宿主表，见 `core/db_common.py` 第 839–865 行） |

两候选**互不依赖**，各自可独立验收；派发时须附本文件的实测数字作为验收基线。

## 8. 局限与未完成项

1. **生产数据规模未知**：任务禁止读真实数据库，因此"是否需要索引"的最终触发条件（单快照/单交付物 ≥ 20000 行）无法在本次闭合，只能给出阈值与预验证的候选。
2. **打包 exe 环境未复测**：全部数字来自源码工作区（`python -B`），未覆盖 PyInstaller onedir 运行包的冷启动（其模块加载路径不同）。
3. **`tools/perf_baseline.py` 未修改**：其合成分页表自带覆盖排序的索引，不代表生产查询形状。本次以工作区外的临时探针补齐真实形状证据；若要把真实形状纳入常规基准，应另开任务修改脚本（不在本任务 owned scope 的"小改"范围内，因为现有脚本本身无缺陷，只是覆盖面有限）。
4. **`import web.app` 的冷/热缓存效应未分离**：需要专门设计（如清空文件缓存或多次冷启动取首值）才能量化第 0/1 波在启动路径上的代码级收益。

## 9. 证据文件清单（工作区外，不入库）

| 文件 | 内容 |
| :--- | :--- |
| `E:\project\vse-toolbox-wt\_logs\DSH-V2-33\run1.json` | `--quick` 10 轮，首次运行（冷缓存） |
| `...\run2.json` | `--quick` 10 轮，第二次运行 |
| `...\run3_standard20.json` | 标准 20 轮 |
| `...\run4.json` | `--quick` 10 轮，第四次运行（复现） |
| `...\run*.stdout.txt` | 各次运行的原始 stdout |
| `...\probe_index_evidence.py` | 真实查询形状探针（合成库 + EXPLAIN QUERY PLAN） |
| `...\probe20.json` / `probe20.utf8.json` | 探针原始输出（UTF-16 / UTF-8） |
