# VSE Toolbox v2 需求追踪矩阵（2026-10-31 基线）

> 需求源：[REQUIREMENTS.md](REQUIREMENTS.md)。**对账结论：REQUIREMENTS.md 共 72 个独立需求编号**
> （A9 B5 C5 D12 E3 F8 G3 H5 I2 J5 K6 U9 = 72）。
> `docs/PROMPT_20261031_ASTRA_V2_MASTER_PLAN.md` §3 的「共 80 条」不成立；差异来源推定：
> 72 编号 + K6 下有 6 个明细行 + 2 条验收方式 = 80 个条目。追踪一律以 72 编号为准。
> 状态：✅ 已交付（基线，证据=测试/提交）· 🔄 本计划波次 · ⏸ 待外部条件 · 〰️ 部分（余项见备注）。

## A. 安装、运行与更新

| ID | 需求 | 状态 | 波次/任务 | 备注 |
|---|---|---|---|---|
| A1 | 无管理员/无 Python 可安装运行 | 〰️ | W16-02 / W17-02 | onedir 解压即用已达成；自动放置与窗口体验在 W16-02 |
| A2 | 桌面窗口+托盘 | 〰️ | W16-02 | 托盘已交付（M1 第2片）；pywebview 窗口+三级回退在 W16-02 |
| A3 | 单实例 | 🔄 | W16-02 | |
| A4 | 端口冲突零干预 | 🔄 | W16-02 | |
| A5 | 数据程序分离+导入旧数据 | ✅ | 基线 2.3.0 | 主项目=安装根兼容旧数据 |
| A6 | 增量更新+回滚 | ✅/🔄 | 基线 / W17-03 | app 包+回滚已交付；bundle 类不做；负向验证在 W17-03 |
| A7 | 更新记录对用户可见 | ✅/🔄 | 基线 / W19-02 | 设置页内更新已交付；用户更新记录 W19-02 |
| A8 | 开机自启（可选） | 🔄 | W16-01 | 默认关闭，向导询问 |
| A9 | 一条命令发布 | ✅ | 基线 / W0-02 | release.py 已核验，矩阵已冻结 |

## B. 账号与会话

| ID | 需求 | 状态 | 波次/任务 | 备注 |
|---|---|---|---|---|
| B1 | 一次登录双系统 | ✅ | 基线 | 向导第 1 步 |
| B2 | 会话状态合一 | 🔄 | W3-01 | |
| B3 | DPAPI 凭据默认保存 | 〰️ | W2-01 | 已有勾选保存；「默认保存+说明」与状态机一并核 |
| B4 | 会话过期自动处理（第 1 痛点） | 🔄 | W2-01 | 契约 C2 |
| B5 | 清除会话与凭据 | 🔄 | W2-01 | 契约 C2 清除竞态 |

## C. 项目与主计划

| ID | 需求 | 状态 | 波次/任务 | 备注 |
|---|---|---|---|---|
| C1 | 多项目与切换 | 〰️ | 基线 + W5-01 | 切换已交付；编辑/归档/科室回写在 W5-01 |
| C2 | 阶段时间轴 | ✅ | 基线 2.1.0 | |
| C3 | 主计划时间轴/表格编辑 | 🔄 | W5-02 | |
| C4 | 总体进度口径 | ✅ | 基线 2.1.0 | |
| C5 | 逾期单一口径 | 🔄 | W10-01 → W10-02 | 契约 C9 |

## D. 交付物跟踪与自动同步

| ID | 需求 | 状态 | 波次/任务 | 备注 |
|---|---|---|---|---|
| D1 | 交付物清单+FixIt | 〰️ | 基线 + W8-01 | 简洁视图已交付；FixIt 按钮在 W8-01 |
| D2 | 一键开启自动同步 | ✅/⏸ | 基线 / W17-02 | 真实系统取证真机未验证 |
| D3 | 同步筛选表单 | ✅/⏸ | 基线 / W5-01 | 科室五默认已交付；48 车型清单待用户，文本兜底 |
| D4 | 调度 09:00/16:00+补跑 | 🔄 | W6-01 | 契约 C4 |
| D5 | 更新方式收专家 | ✅ | 基线 2.2.0 | |
| D6 | 同步记录页签 | ✅ | 基线 2.2.0 | |
| D7 | 外部来源快照合并 | 🔄 | W8-03 | |
| D8 | 科室归集规则 | ✅/🔄 | 基线 / W8-03 | 设置位置随 W8-03 收口 |
| D9 | 关注清单双入口 | 🔄 | W6-02 | 契约 C5 单一权威 |
| D10 | 架构件归属页签 | ✅/🔄 | 基线 / W8-03 | |
| D11 | 分析图表+诊断包导出 | 〰️ | 基线 / W1-01 | 诊断包白名单在 W1-01 |
| D12 | 取证/审计收专家 | ✅/🔄 | 基线 / W8-03 | |

## E. 表单分析

| ID | 需求 | 状态 | 波次/任务 | 备注 |
|---|---|---|---|---|
| E1 | 单一入口（详情页内） | 🔄 | W9-01 | |
| E2 | 表格交互（排序/分页/列显隐/复制单号） | 🔄 | W9-01 | 列 key 缺失时回退 c.index |
| E3 | 多值搜索/关注过滤 | ✅/🔄 | 基线 / W9-01 | 核对随 W9-01 |

## F. 报告中心

| ID | 需求 | 状态 | 波次/任务 | 备注 |
|---|---|---|---|---|
| F1 | 日报一键生成（样板交互） | 🔄 | W7-01 | |
| F2 | 日报设置抽屉 | ✅/🔄 | 基线 / W8-02 | |
| F3 | 日报定时 08:30 | 🔄 | W6-01 + W7-01 | 契约 C4/C5 |
| F4 | TIR 简表+同日复用 | 〰️ | 基线 + W7-01 | 复用键与文件校验在 W7-01 |
| F5 | EWO/PAA/NCR 导出统一 | 🔄 | W7-01 | |
| F6 | TDC 导出/全量抓取统一 | 🔄 | W7-01 | |
| F7 | EWO 增强导表（冻结规则） | 🔄 | W7-01 | generation_unknown 人工门禁不变 |
| F8 | 北京时间统一 | 🔄 | W10-02 | 契约 C9 |

## G. 原件留存

| ID | 需求 | 状态 | 波次/任务 | 备注 |
|---|---|---|---|---|
| G1 | 原件留存并入同步 | 🔄 | W6-02 | |
| G2 | 历史原件页签 | 🔄 | W6-02 | |
| G3 | 保留期与原子存储 | ✅ | 基线 | |

## H. Excel

| ID | 需求 | 状态 | 波次/任务 | 备注 |
|---|---|---|---|---|
| H1 | 工具页三操作 | 〰️ | 基线 / W12-02 | 界面重排在 W12-02 |
| H2 | Worker 启停不可见+自动管理 | 〰️ | 基线 / W12-01 | 术语已隐藏；自动启停在 W12-01 |
| H3 | 白名单根目录+路径安全 | 🔄 | W12-01 | 契约 C10 |
| H4 | 环境自检 | 🔄 | W12-01 | 无法确认时「需要检查」 |
| H5 | 产物审计/保留 | ✅ | 基线 | |

## I. 任务中心

| ID | 需求 | 状态 | 波次/任务 | 备注 |
|---|---|---|---|---|
| I1 | 原位进度/取消/重试/通知 | 🔄 | W11-01 | 契约 C6 |
| I2 | 产物 7 天清理 | ✅/🔄 | 基线 / W11-01 | 清理保护边界在 W11-01 |

## J. 设置、诊断与支持

| ID | 需求 | 状态 | 波次/任务 | 备注 |
|---|---|---|---|---|
| J1 | 目录设置+原生对话框 | ✅/🔄 | 基线 / W8-03 | |
| J2 | 高级参数收专家 | ✅ | 基线 2.2.0 | |
| J3 | 版本信息 | ✅ | 基线 2.2.0 | |
| J4 | 诊断包（ErrorCard 入口） | 🔄 | W1-01 | 契约 C10 |
| J5 | 专家模式 | ✅ | 基线 2.1.0 | |

## K. 下线 / 降级（W15-01 统一执行；feishu_tasks 表保留、TDC feishukey 字段保留）

| ID | 功能 | 状态 | 波次/任务 | 备注 |
|---|---|---|---|---|
| K1 | CLI 下线（含周报 PPT/内网抓取/selenium/rich/imapclient） | ✅ | W15-01 | main.py 与 VSE-Toolbox*.spec 已删，依赖已移除 |
| K2 | 原始查询页收专家 | ✅/🔄 | 基线 / W15-01 | |
| K3 | 旧交付物工作台下线 | ✅ | W15-01 | **保留新版 workbench**；legacy #deliverables 改指 #p/project-overview/details |
| K4 | TDC Probe 生产产物下线 | ✅ | W15-01 | 开发能力保留（tdc_probe_main/cli + VSE-TDC-Probe.spec）；库内无生产产物 |
| K5 | 计划任务脚本下线 | ✅ | W15-01 | 3 个 install_*_task.ps1 已删 |
| K6 | 飞书功能下线 | ✅ | 基线 / W15-01 | feishu_imap.py 已删；feishu_tasks 表与 TDC feishukey 保留 |

## U. 体验层

| ID | 需求 | 状态 | 波次/任务 | 备注 |
|---|---|---|---|---|
| U1 | 首次使用向导补全 | 〰️ | W4-01 | 跨重启恢复、稍后设置/已完成区分 |
| U2 | 首页「今天」 | ✅ | 基线 2.1.0 | |
| U3 | 导航重组 | ✅ | 基线 2.1.0 | |
| U4 | 术语门禁 | 🔄 | W8-01 | 禁词扫描 pytest 化 |
| U5 | FixIt | 🔄 | W8-01 | |
| U6 | ErrorCard | 〰️ | W8-01 → W8-02/W8-03 | 工作台已有；旧页推广 |
| U7 | 状态色统一 | 〰️ | W8-01 → W8-03 | |
| U8 | 骨架屏/原位进度 | 〰️ | W8-01 → W8-03 | |
| U9 | 托盘通知 | 🔄 | W11-01 | |

## 验收（非编号需求）

| 事项 | 状态 | 波次/任务 | 备注 |
|---|---|---|---|
| 每个 P0 需求一条可演示路径+自动化测试 | 🔄 | 各波次门禁 | 追踪矩阵每波更新 |
| 3 名新用户 10 分钟全路径 | ⏸ | W20-01 → W20-02 | 缺真实人员时如实待验证 |
| 更新验收（app 包双击安装+失败回滚） | 🔄 | W17-03 | 真机 |


## W1 交付记录（2026-10-31）

| 任务 | 状态 | 交付物与证据 |
|---|---|---|
| W17-01 | ✅ | `tools/wave_gate.py`（--focus 轻量模式/全量/地图/术语/打包五步编排，SKIP 如实标记）+ `tests/browser/`（Chrome headless 真实通道验证，无通道时带原因 skip） |
| W13-01 | ✅ | `tests/test_route_contract_snapshot.py` + `tests/golden/routes.json`（160 条路由锁定，对比模式零差异） |
| W8-01 | ✅ | `web/static/host/ui-kit.js`（ErrorCard/FixIt/Skeleton/TONE）+ `glossary.js` + 术语门禁 pytest + 基线（21 文件）；失败输出脱敏（不泄露内网串）；盘符正则收紧为反斜杠 |
| W10-01 | ✅ | `core/time_rules.py`（aware UTC/北京时间/纯日期/三来源解释/逾期内核）+ 20 项测试；NamedTuple __classcell__ 兼容修复 |
| W18-01 | ✅ | `tools/perf_baseline.py` + [PERF_BASELINE_20261031.md](PERF_BASELINE_20261031.md)（实测：冷启动 1948ms、overview 1.63ms、深分页 0.12ms） |
| W19-01 | ✅ | `docs/manual/真机核对清单.md`（7 大项，操作步骤/预期现象/截图要点） |
| W20-01 | ✅ | `docs/manual/新用户验收脚本.md` + `docs/manual/验收记录表.md`（步骤合计 480s ≤ 600s） |
| W1 集成包 | ✅ | `dist/v2-test/updates/vse-app-2.3.5.vsepkg`（251 文件，验签通过，sha256 `8844aa0c…`） |

**W1 期间运行时适配（lead，不入需求追踪）**：worker 运行时对新版 GLM zcode.cjs 的协议适配四连修
（runtimeModel/推理档位/params 形状/guard 拒绝分级），详见 RECOVERY_NOTES 2026-10-31。


## Wave 2 交付记录（2026-10-31）

| 任务 | 状态 | 交付物与证据 |
|---|---|---|
| W13-02 | ✅ | `web/host_boot.py`（11 条路由逐字迁移：version/settings/host-update）；路由 golden 零差异；settings 安全测试 33 passed |
| W5-01 | ✅ | 项目编辑（expectedRevision 修订检查、省略≠null）、归档（retired 保留数据、当前项目保护）、科室回写、旧 projects.json 容忍读取；契约测试 6 项（lead 修复：信封键名/视图回退断言/缺失 fixture） |
| W14-01（第 1 步） | ✅ | 表单分析黄金基线 `tests/golden/form_analysis/`（form_definition/rows/view 三入口，6 测试）；**W14-01b 服务拆分留待 Wave 3**（首次派发超时，已拆分） |
| W16-01 | ✅ | `vse_boot/autostart.py`（HKCU Run，无管理员，默认关）+ 设置页开关 + 26 测试（注册表全 mock）；vse_boot 改动 → 下版整包（矩阵 §2） |
| Wave 2 集成包 | ✅ | `dist/v2-test/updates/vse-app-2.3.6.vsepkg`（252 文件，sha256 `5fe31662…`，验签通过，未真机安装） |

**路由基线**：163 条（新增 workbench 归档、settings 自启开关）。


## Wave 3 交付记录（2026-10-31）

| 任务 | 状态 | 交付物与证据 |
|---|---|---|
| W13-03 | ✅ | `web/tasks_boot.py`（6 条 /api/tasks 路由 + 4 助手逐字迁入，510 行；_CRAWL_TASK_TYPE_LABELS 随迁——首跑全量暴露后补）；golden 零差异 |
| W12-01 | ✅ | `services/excel_path_safety.py`（穿越/UNC/ADS/越界）+ `services/excel_env_check.py`（激活状态「需要检查」不伪报；残留进程只认本工具）+ 全 mock 测试 |
| W1-01 | ✅ | 诊断导出字段白名单化（白名单外不收集；禁导清单物理阻断）+ `tests/test_diagnostics_whitelist.py` |
| W14-01（第 2 步） | ✅/🔄 | 服务包化（`services/deliverable_form_analysis/` = `_impl.py` 原文 + 136 名字全量 re-export，零行为风险）；worker 子模块拆分尝试因行为漂移（15 failed）被 lead 否决回退；子模块渐进拆分留后续波次 |
| Wave 3 集成包 | ✅ | `dist/v2-test/updates/vse-app-2.3.7.vsepkg`（256 文件，sha256 `9e49dabc…`，验签通过，未真机安装） |

**Wave 3 门禁**：全量回归 PASS、地图 verified、术语/Node/浏览器通道全绿、包 2.3.7 验签。


## Wave 4 交付记录（2026-10-31）

| 任务 | 状态 | 交付物与证据 |
|---|---|---|
| W13-04 | ✅ | `web/excel_boot.py`（13 条 /api/excel-* 路由逐字迁入；异常类随迁——静态自由变量审计补齐）；golden 零差异 |
| W3-01 | ✅ | 顶栏会话合一（三档映射：已连接✓/正在恢复/需要重新登录，点击原位登录复用 LoginDialog）+ Node 夹具 |
| W5-02 | ✅ | 主计划时间轴直接编辑 + 表格批量编辑（复用既有 PATCH 与 updatedAt 乐观锁；未排期「去排期」保持）；lead 修复夹具事件桩（stopPropagation/currentTarget） |
| W1-02 | ✅（第 1 轮缩减） | plugins/diagnostics 自检页（后端聚合：会话/Excel/更新通道/项目注册表；载荷键白名单；只读）；lead 修复 3 处自测问题（async 导出匹配、warn 诚实语义、朴素术语扫描误报） |
| W14-03（第 1 步） | ✅ | project_status_updates 黄金基线（5 入口，含 422 拒绝路径）；lead 修复可复现性测试（每步全新库——有状态序列不能共用库）；**拆分实施留后续** |
| Wave 4 集成包 | ✅ | `dist/v2-test/updates/vse-app-2.3.8.vsepkg`（262 文件，sha256 `4d2775ac…`，验签通过，未真机安装） |

**基线更新**：路由 golden 164 条（+diagnostics 自检）；专家导航基线 +「自检」。


## Wave 4 收尾记录（2026-10-31，W16-02 + W14-03B）

| 任务 | 状态 | 交付物与证据 |
|---|---|---|
| W16-02 | ✅（本阶段范围） | 三级回退开窗（pywebview→Edge app→默认浏览器，`vse_boot/supervisor.py::open_window`）+ 4 项单测；单实例 InstanceLock 与端口零干预（free_port/探活）系 M1 已交付，本波核验；[L0 选型 Spike 报告](L0_SPIKE_20261031.md)（L0 不替换）；pywebview 窗口与 L0 原生启动器真机验证留 W17-02 |
| W14-03（第 2 步） | ✅ | project_status_updates 包化（_impl.py 原文 + 69 符号 re-export + __path__ 兼容垫片，零行为风险）；黄金+既有 37 passed；子模块渐进拆分留后续波次 |
| Wave 4 收尾包 | ✅ | `dist/v2-test/updates/vse-app-2.3.9.vsepkg`（264 文件，sha256 `ecce9570…`，验签通过，未真机安装） |


## Wave 5 交付记录（2026-10-31）

| 任务 | 状态 | 交付物与证据 |
|---|---|---|
| W13-05 | ✅ | `web/archive_boot.py`（10 条 /api/scheduled-archive 路由聚合迁入——原文件与其他注册交错，按装饰器逐段提取）；_archive_history_limit 严格校验随迁（lead 曾凭印象重写致 2 failed，恢复原文）；golden 零差异 |
| W4-01 | ✅ | 向导补全（登录→建项目→选交付物→自启询问→完成；跨重启恢复非敏感状态；「稍后设置」区分；密码/凭据偏好绝不持久化——saveCredentials 偏好也不入 localStorage）；lead 修复 3 处（键集断言、写点清理、注释入数组块） |
| W11-01 | ✅（lead 接管完成） | 两态取消（cancel_requested→幂等 200）、cancelRequested/retryOf/progressIndeterminate 字段、清理保护（活跃任务产物 SQL 排除；历史原件天然隔离）；每次注册独立生命周期状态（全局单例曾致跨测试串味）；8 测试 |
| W12-02（缩减版） | ✅ | Excel 工具页环境检查卡片（三态；无后端时占位不伪报）+ ErrorCard 接入；lead 修复 2 处（空对象语义对齐、注释 .py 误报措辞） |
| Wave 5 集成包 | ✅ | `dist/v2-test/updates/vse-app-2.3.10.vsepkg`（265 文件，sha256 `daaaaa26…`，验签通过，未真机安装） |

**Wave 5 教训**：① 路由块迁移后必须 ast 自由变量审计 + 常量随迁（_archive_history_limit 凭印象重写是违规）；② 进程级单例状态在 Web 应用里必须按 app 实例隔离；③ 契约文本避免英文敏感词（password/token 触发高危拒派）。


## Wave 7 交付记录（2026-10-31）

| 任务 | 状态 | 交付物与证据 |
|---|---|---|
| W13-07 | ⏸ **重新规划** | 首次手工迁移（52 成员闭包）传递依赖直通 create_app 局部符号，6+ 层缺名不收敛 → **整体回退**到全绿态；教训与重做前置（三清单冻结法）入 RECOVERY_NOTES 2026-10-31 |
| W10-02 | ✅（lead 收敛） | 全站时间展示 zh-CN 门禁（`tests/test_time_display_frontend.py`：locale-default 禁止 + toISOString 内部用法白名单）；修复 catalog.js×3、query.js×1；worker 两轮超时/权限后 lead 直接收敛（实际展示点仅 4 处，不需要 time-format.js 抽象） |
| W8-02b | ✅ | 四页 ErrorCard/Skeleton 接入（源级断言版门禁，杜绝 hooks 直渲染崩溃重演）；23 测试 |
| Wave 7 集成包 | ✅ | `dist/v2-test/updates/vse-app-2.3.12.vsepkg`（267 文件，sha256 `9e6f2f48…`，验签通过，未真机安装） |


## Wave 8 交付记录（2026-10-31）

| 任务 | 状态 | 交付物与证据 |
|---|---|---|
| W13-07（重做） | ⚠️→✅ | 复核纠偏：19c09cf/bd6792b 实为向 crawler_boot 复制副本，路由原件未迁出、register_* 未接线（提交说明与实际不符）。副本于 Wave 9 W13-09a 真正接线并单源化 |
| W13-08 | ⚠️→✅ | 同上纠偏：表单/目录路由原件当时仍在 app.py；真正迁居+接线于 W13-09a 完成 |
| W10-02 | ✅ | 全站时间 zh-CN 门禁 `tests/test_time_display_frontend.py` + 修复 4 处 locale-default |
| W8-02b | ✅ | 四页 ErrorCard/Skeleton 源级断言门禁（23 测试） |
| Wave 8 集成包 | ✅ | `dist/v2-test/updates/vse-app-2.3.13.vsepkg`（267 文件，sha256 `28a852bd…`，验签通过，未真机安装） |

**路由分布**：web/app.py 仅剩 project-status(25) + 通用路由（favicon/overview/version 等），TDC/Aras/Excel/Tasks/Archive/Settings/Host/Deliverables 全部模块化。

## Wave 9 交付记录（2026-10-31）

| 任务 | 状态 | 交付物与证据 |
|---|---|---|
| W13-09a | ✅ | 补完 W13-07/08 接线：register_tdc_routes + register_form_catalog_routes 真正迁居并接线（CrawlerRouteDeps 增 deliverable_form_service/section_rollup_store；逐字回迁 2 闭包）；补 4 处缺名（_DEFAULT_TDC_ALLOWED_HOSTS 等）；app.py 删 57 个重复顶层定义（1580 行）转 51 名别名再导出；7 处补丁目标改随路由现属模块；全量 3637/6/0 |
| W13-09b | ✅ | 三清单冻结法：43 成员 + 3 闭包 + 27 条 /api/project-status* 路由逐字迁入 web/project_status_boot.py（2967 行），ProjectStatusRouteDeps 注入 8 服务；app.py 5330→736 行装配化，flake8 F401/F821 清零；194 个失消费导入修剪；路由金样零差异；全量 3637/6/0 |
| W15-01 | ✅ | K1–K6 全落地（见上表 K 行）：删 main.py(1682 行)/plugins/deliverables/feishu_imap/3 个 install_*.ps1/VSE-Toolbox*.spec；requirements 移除 rich/imapclient/selenium；7 个专属测试套件删除、4 个混合套件改造；全量 3514/6/0（净减 123 个 CLI 专属用例） |
| Wave 9 集成包 | ✅ | `dist/v2-test/updates/vse-app-2.3.14.vsepkg`（261 文件，sha256 `3c1c1176…`，含全部 7 个 boot 模块；main.py 与 plugins/deliverables 已不在包内；未真机安装） |

## Wave 10 交付记录（2026-10-31，W16-03 已提交、待集成验收）

| 任务 | 状态 | 交付物与证据 |
|---|---|---|
| W16-03（b781066） | 🔄 已提交、待集成验收 | 本机安全集中接入（契约 C7 全条款）：新建 `web/security.py`（247 行：BootTicketStore 10 秒一次性启动票据 / LocalSessionStore 12 小时会话 Cookie / LocalWebSecurity 统一写保护四件套，fail-closed）；`web/static/host/boot-exchange.js` 前端换票；`vse_boot/supervisor.py` 把票据注入 `?boot=` 与 instance.json bootToken；`webui.py`、`web/app.py` 接线；新增 `tests/test_local_security.py`（339 行）、路由金样 +11 条；删除 `tools/verify_milestone_empty_restore.py`。**代码已入库、集成验收未做**（真机票据换发 / 10 秒一次性票据与 `_show_existing` 复用旧 URL / 12 小时会话过期 / `install_local_security` 无条件安装自动认证测试客户端需显式夹具与原生负向测试），**不得记为已交付** |

## DSH-V2-00 验收基线重建记录（2026-10-31，HEAD 7798997）

> 目的：在隔离工作区重建 b781066（含其上 7798997 纯文档提交）的验收基线，纠正此前进度记录。
> 只改 `PROJECT_MAP.md`、`memory/CURRENT_STATE.md`、本文件；**未改任何产品代码与测试**，未 commit。
> 证据日志：`E:\project\vse-toolbox-wt\_logs\DSH-V2-00\`（工作区外）。

| 验证 | 命令 | 退出码 | 实测结果 |
|---|---|---|---|
| 全量回归 | `python -B -m pytest -p no:cacheprovider tests -q -rs` | **0** | **3530 passed / 6 skipped / 2 warnings**；首轮 535.99s（`pytest-full.txt`），评审复核复跑 471.64s（`pytest-full-round2.txt`）；同工作区另记录 486.02s / 557.26s，四次计数完全一致 |
| 评审复核 | 重新核对工作区（HEAD `7798997`） | — | 指纹由 `b84b3415…` 变为 `7d1bfec0…`，经核对为**文档改动**：`git diff --name-only` 仅 3 个 owned_scope 文件，产品/测试文件与 HEAD 逐字节一致，无未跟踪文件；复跑 pytest / flake8 / 地图 `--check` / `git diff --check` 结果与上表一致 |
| 子集抽样 | 4 套件（local_security / route_contract_snapshot / time_rules / time_display_frontend） | 0 | **44 passed，5.81s**（源证据 7.71s）——非全量 |
| 地图写入 | `python tools/generate_project_map.py --write` | **0** | 生成 PROJECT_MAP.md（指纹 `580f871a…`→`57f6074c…`，范围文件 259→261，Python 模块 121→122，新增 `web/security.py` 行）；幂等，写入前后 sha256 不变 |
| 地图校验 | `python tools/generate_project_map.py --check` | **1 → 0** | 提交态（HEAD 内容）exit 1（`Project map is out of date`，本轮复现派发前失败）；写入后 **exit 0**（verified） |
| 静态检查 | `python -m flake8 web/app.py` | **1** | 6 条：E303×2（429、606）+ F811×4（561、606） |
| 空白检查 | `git diff --check` | **0** | 干净 |

- **6 个 skip 的真实原因**（全为环境缺失，非缺陷）：playwright 未安装 ×2（`test_plugin_overview_browser.py:24`、`test_plugin_sign_daily_browser.py:18`）、Windows 不允许创建符号链接 ×2（`test_archive_store.py:69/162`）、`time.tzset` 仅 POSIX ×1（`test_sign_daily_mail.py:133`）、symlink unavailable ×1（`test_zcode_worker.py:475`）。
- **2 条 warning 均在测试侧**：`test_plugin_diagnostics.py:251` SyntaxWarning（`\s` 无效转义）、`test_glossary_terms.py:310` 禁词基线 UserWarning。
- **数字口径（禁止混写）**：`3530 passed/6 skipped/13 warnings in 437.58s` **只是 W16-03 提交前的历史全量**，不是本轮证据；本轮 passed/skipped 计数与之相同但 warning 为 2（环境相关）。`3514 passed/6 skipped` 是 W15-01（60eaf6b）提交时的历史值，**不是当前全量**。
- **flake8 F811 历史记录已核实为真**：`web/app.py:561`（`CrawlerRouteDeps` / `register_crawler_routes`）与 `:606`（`ProjectStatusRouteDeps` / `register_project_status_routes`）均为工厂函数内局部 import 遮蔽模块级再导出别名，另有 E303 两条。以真实退出码 1 与真实输出为准，`echo FLAKE-OK` 之类不算通过；本任务不修产品代码，缺陷留后续任务。
- **构建 WinError5（根因未定）**：`tools/build_v2_test_install.py:126 old.unlink()` 对 `dist/v2-test/updates/vse-app-2.3.10.vsepkg` 抛 `PermissionError WinError 5`，构建 exit 1（`.runtime/w16_03_build.log`）。文件占用与 ACL 拒绝均可能，未验证前不得断言单一根因；**修复归 DSH-V2-44**，本任务不改构建脚本。本轮未复跑构建，证据沿用 W16-03 记录。
- **未完成项**：W16-03 集成验收（真机票据 / 会话过期 / 重复启动）未做；flake8 F811/E303 未修（越界）；构建 WinError5 未修（归 DSH-V2-44）。

## 基线证据（2026-10-31，W0）

- 已提交：`b9f309b`（同步三问题+展示口径）、`7f4617f`（日报门禁+孤儿项目）、`d7ba018`（文档基线）。
- 全量回归与地图校验：见 W0 里程碑报告（本轮实测，非历史数字）。
- 历史数字 3441/6 与包 2.3.4 为 2026-10-30 记录，仅作对照，不作为本轮证明。
