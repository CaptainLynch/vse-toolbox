# 签署日报 v2.0 启动审计（2026-10-03）

依据：Claude Docs「3D单签署进展日报插件 需求规格 v2.0」（下称规格）。规格里的
`signing_report` 就是仓库里已有的 `plugins/sign_daily/`（插件 id `sign-daily`，v1，
`886e5a7`）。本次读的是代码，补上了规格作者当时只看了数据库表结构、没读到代码的部分。

## 1. 开工前唯一待确认项：host.context 开放了什么（规格 §12、R1、R2）

| 项 | 结论 | 证据 |
| --- | --- | --- |
| 自有存储、结构迁移（R2） | **可用，不改宿主** | `host/registry.py` `PluginHost.migrate()`、`table_prefix`；前缀是 `p_sign_daily_`（`core/repos/plugin_schema.py:34`），不是规格写的 `signing_report_`。v1 已用它建了 `config`、`daily_summary` 两张表 |
| 触发 TDC 抓取（R1） | **可用，不改宿主** | `ctx.services` 就是整个 `app.extensions`（`web/app.py:6173`）；v1 已经调 `scheduled_archive_admin.sync_now("tdc_data_model")`（`backend.py:371`） |
| 查询抓取进度（R1） | **没有现成的，可组合实现** | `sync_now` 在 HTTP 请求里同步跑完整个抓取，页面没有进度。`crawl_task_runner.submit_task(worker_fn=…)` 和 `get_task()` 也在 `app.extensions` 里，插件可把 `sync_now` 包进后台任务再轮询，不用改宿主 |
| 与自动同步共用抓取锁（R3） | **锁已存在** | `ArchiveSyncRunner` 的租约（`lease_seconds=900`）。手动和调度并发时返回 `lease_busy`。v1 把它当失败提示「稍后重试」，规格要求复用进行中的任务，要改成等待并轮询 |

**风险**：`app.extensions` 不是声明过的插件契约，键名一改插件就失效（和 R5 同类）。
建议宿主在 `HostContext` 文档和 `tests/test_plugin_host.py` 里把
`scheduled_archive_admin`、`crawl_task_runner` 登记为插件可用的服务名。改动小，但要单独评审。

**插件 id 不改名**：沿用 `sign-daily`。改成 `signing_report` 会让 v1 已存的配置表和日汇总表成为孤表。

## 2. §9 待核对项

| 问题 | 结论 | 证据 |
| --- | --- | --- |
| TDC 能否按流水单号过滤 | **能，但一次只能查一个单号** | `tdc_data_model` 的筛选键含 `incident`（`services/scheduled_archive_connectors.py:74`），落到 TDC 请求时就是流水单号（`services/tdc_crawler.py:223`）。关注清单有 n 个单号时，要么查 n 次，要么全量抓取后在落库时按清单保留，要按清单规模实测再定 |
| 同步频率 15 分钟和任务间隔 60 分钟谁说了算 | **任务间隔说了算**；15 分钟只是调度器检查一次的周期 | `services/scheduled_archive_runner.py` `_is_due()` 按每个任务的 `interval_minutes` 判断是否到期。实际间隔约等于任务间隔，向上取整到 15 分钟的倍数 |
| 凭据、输出目录、重试策略能否在界面改 | 后端已返回 `outputDirectory`、`retryPolicy`、`credentialConfigured`（`scheduled_archive_admin.py` `_job_payload`），行内编辑区可以复用 | 写接口要等排期 §9 时再读 |

## 3. v1 代码对照 v2：规格列的 12 处缺陷在代码里的位置

| # | 缺陷 | v1 位置 | v2 实现 |
| --- | --- | --- | --- |
| 1 | 科室靠「角色列→科室」映射 | `report.py` `DEFAULT_ROLE_DEPARTMENTS`、`resolve_department` | `rules.Roster`、`rules.attribute`（A1–A8、A11） |
| 2 | 只要未签就算欠账 | `report.py:412` `owed_by_department` 遍历全部未签人 | `rules.owed_charts` 只统计待审批人员里的人（A10） |
| 3 | 按 TDC 部门筛选范围 | `report.py:304` `filter_scope` | `rules.flow_department`（A9）。backend 待接入 |
| 4 | 长周期双向「包含即命中」 | `report.py:181` `long_cycle_hits` | `rules.classify_part`（L1–L6） |
| 5 | 只存一行汇总 | `backend.py` `daily_summary` 表 | 零件级快照待做（D1）。`rules.metrics` 已能按今天的口径重算基线 |
| 6 | 取整方式没写 | `report.py:330` `_ratio` 用 `round()`，是**银行家舍入**：12.25% 显示成 12.2%，违反「四舍五入」 | `rules.display_pct` 改用 `Decimal` 四舍五入。Δ 用两边的显示值相减（D4） |
| 7 | 欠账只分两组 | `report.py` `owed_by_department` 只按阶段分组 | `rules.owed_charts` 分三张图，各图有自己的分组和排序（G1–G4） |
| 8 | 长周期初筛结果能直接导出 | `backend.py:284` 只加一条提示，`/generate` 和 `/eml` 都不拦 | 复核清单由 `rules.long_cycle_decisions` 产出。阻塞导出待接入 |
| 9 | 配置没有种子、导入、回滚 | `backend.py` `Store.config` 是平铺的 JSON | 待做（§7 M1–M8） |
| 10 | 加签人员 | `report.py:244` 只认「待审批人员里不在任何角色列的人」，漏掉在角色列已签、同时在加签列的人；加签列本身没解析 | `rules.Flow.add_sign_pending`（P5）；P7 核对未签数时计入加签列 |
| 11 | 同一单各行不一致时取首行 | `report.py:295` 签署人只从首行解析（`signers=_signers(row)`），后续行的「(未签)」被忽略 | `rules.build_flows` 按人合并，任一行未签就算未签，并报 `rowSignersDiffer` |
| 12 | 已申请天数 | `backend.py:52` 用的是服务器当天日期 `date.today()`，不是数据日期 | `rules.Flow.days(data_date)`（P8） |

## 4. 规格没列、本次审计查出的 v1 问题

| 问题 | 位置 | 影响 | 处理 |
| --- | --- | --- | --- |
| 审批人科室按首次出现的单冻结 | `report.py:413` `person_dept.setdefault` | 同一审批人在不同科室的单上，都按第一份单的科室归组 | v2 改为按花名册判定，与单据无关 |
| 零件不按零件号去重 | `report.py:300` `flow.parts.append` | M 偏大（F610M 样例里多 1 个） | 改为按 P9 去重 |
| 姓名按空白拆分 | `report.py:81` `_NAME_SPLIT` 含 `\s` | 「待审批人员」里带空格的姓名会被拆成两个人 | P3 只按「、」、逗号、分号和换行拆 |
| 旧数据也写当天汇总 | `backend.py:408` | 抓取失败后用旧数据生成，会把旧数字记成今天的基线 | 按 §5 处理：数据日期不晚于基线时不写快照 |
| `.eml` 不含图片 | `report.py` `build_eml` | 只有纯文本和 HTML 两部分，没有 `multipart/related` 内嵌 PNG | 三图一表接入时一并改 |
| 抓取期间页面没有反馈 | `backend.py:365` `/refresh` | 全量抓取期间请求一直挂着，看不到进度（§8 第 2 步要求显示进度） | 见 §1 R1 |

安全面没有发现问题：所有写路由都先调 `ctx.local_guard()`；配置补丁有白名单和长度上限；
错误信息经过 `ctx.redact`；HTML 渲染全部转义；收件人地址用 `formataddr`
（中文按 RFC 2047 编码）；`.eml` 文件名用 `quote`。种子文件要按 R8 只放姓名和科室，不放工号。

## 5. 本次落地（开发顺序第 2 步）

- `plugins/sign_daily/rules.py`：纯函数模块，不依赖宿主。覆盖 P1–P9、A1–A11、L1–L6、
  §5 指标、D2 覆盖判定、D4–D6 格式、基线缺失或不连续的显示方式、三图分组排序（G1–G4）、
  明细表阶段和排序（T1–T4）。
- `plugins/sign_daily/seeds/`（M1 种子，10-03 收到的附件）：
  - `roster.csv`：784 人，只放姓名和科室（R8）。由 794 行花名册合并同名得到 778 人（16 个同名同科室），
    高义轩由结构工程科改为车身科，另加滕平、韦逢义、梁海峰、铁盛武、韦孔辉、段大禄 6 人。
  - `long_cycle.csv`：43 项，加了规则编号 LC01–LC43，其中 4 项带排除词、8 项带「/」。
  - `seed.json`：种子版本号和核对数字。
- `rules.parse_roster_table`、`rules.parse_long_cycle_table`、`rules.decode_csv`：§7 导入校验，种子也走这一套。
  种子数字和规格 §1 的核对结果逐项一致。
- 用真实清单跑出一处规格没写到的情况：7 项写成「X总成/组件」，「/」后面的「组件」其实是后缀的另一种写法。
  按「并列叫法」拆开会生成一条只有「组件」的规则，所有带「组件」的零件都会命中。现已把只剩白名单后缀的分段当后缀处理。
- `tests/test_sign_daily_rules.py`：80 个用例。长周期用例改用随包种子清单，覆盖 §4 正反例表全部 12 行
  和 §4 末尾列出的 F610M 疑似、相近未命中例子；验收用例 7、8 也已覆盖。
- backend 仍走 v1 的 `report.py`，没有改用户可见的行为。

## 6. 下一步（按规格开发顺序）

1. 宿主登记插件可用的服务名（见 §1 风险），单独评审。
2. 快照与指标：新增 `p_sign_daily_` 前缀的零件级快照表（D1，保留 90 天）；基线按 D3 重算；
   `/refresh` 改成后台任务加轮询，`lease_busy` 时复用进行中的任务。
3. 三图一表渲染（浏览器 Canvas 出 PNG）和预览；长周期复核面板，有待复核项时禁止导出。
4. 设置页与导入：种子层、本地层、CSV 导入（M1–M8）。
5. 导出：复制富文本；`.eml` 改成 `multipart/related`，图片用 CID 内嵌。

**需要用户提供**：合成在途样例的三个文件（规格 §11，在桌面的 `vse-toolbox-migration` 文件夹），
以及 F610M、F610S 的导出（验收用例 21：N = 131、M = 552）。花名册和长周期清单种子已于 10-03 入库。
