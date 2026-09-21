# 第三阶段：候选版本交付与目标环境验收提示词

状态：本文件是第三阶段执行提示词，不是完成报告。用户要求在“第二阶段验收完成”的假设下规划第三阶段；目前没有据此确认第二阶段已经验收完成。本轮仅编写提示词，未启动构建、worker或生产操作。

建议定位：把已经验收的易用性改进交付为可追溯、可在目标机器验证、具备安全升级说明的候选版本。不开启新一轮功能扩张。

本次定位证据：当前 `VSE-WebUI.spec`、`VSE-ExcelWorker.spec`、`tools/build_excel_bundle.ps1`、`core/runtime_paths.py`、`tools/excel_worker_cli.py` 和第二阶段验收清单。2026-09-17的项目地图check报告过期；执行时必须重新检查，不能复用旧结果。

以下全文可交给交互式 ZCode 主控执行。

---

## 主控提示词

你在 `E:\project\vse-toolbox` 执行第三阶段“候选版本交付与目标环境验收准备”。遵循当前 AGENTS.md。由当前交互式 ZCode 主控统一判断、调度、构建和审查；使用已配置的 Gemini 3.8 Flash worker完成边界明确的证据盘点和文档任务。不要创建第二个规划主控，不让worker递归委派。

### 一、目标与完成层级

交付一个来源可追溯的 WebUI + Excel Worker 配套候选包，附校验文件、发行说明、离线验证记录、目标机器验收清单和升级/回退说明。

必须区分两个里程碑：

- **M1：候选包已准备、离线验证完成。** 代理可以在隔离环境中完成。
- **M2：目标环境验收完成。** 需用户在目标Windows/Office及内网环境执行相应步骤并反馈结果。未收到反馈时写“候选包已交付，目标环境待验”，不能写第三阶段全部完成或生产可用。

本阶段不新增业务功能，不重做已经通过的版本元数据修复，不修改数据库schema、权限、凭据、任务并发或业务状态合同，不引入安装器/自动更新系统，不要求新增CLI或TDC Probe发行包。必要缺陷修复由主控先确认可复现问题并单独限定范围。

本指令允许准备本地候选包和合成数据离线验证，不等于授权替换用户正在使用的EXE、连接真实内网、运行真实业务任务、回写真实库、上传发布或Git提交/推送。

### 二、G0启动条件与源码基线

1. 按 AGENTS.md → memory/CURRENT_STATE.md → memory/CONTEXT_MANIFEST.md → memory/RECOVERY_NOTES.md相关条目 → PROJECT_MAP.md 的顺序恢复上下文。
2. 核实第二阶段最终增量、非UI审计与回归记录、用户UI验收结果。验收应绑定实际源码快照/版本；只有测试数、文档中的“已完成”或一份全为待验的清单不充分。用户明确反馈也可作为人工结果来源，记录其日期和适用版本，不要求用户重复确认已确认的事项。
3. 如果第二阶段尚在进行：可以并行准备只读盘点与文档草案，正式候选构建等待基线稳定。不能锁定一份持续变化的工作区然后声称它就是验收版本。
4. 记录HEAD、已有dirty/untracked清单、批准纳入的文件和逐文件SHA-256。不得仅以HEAD作为有未提交修改时的buildId来源。
5. 按显式构建依赖白名单收集源码，读取map-selected入口及其直接依赖，不扫描整仓库/历史产物。允许读取本阶段独立生成的 `.runtime/phase3-*` 与 `dist/VSE-phase3-*`；不遍历其他运行目录、原始数据或凭据目录。
6. 不擅自commit、stash、reset、checkout覆盖文件或绕过dirty-scope guard。writer须使用经过验证的独立worktree输入机制；若现有supervisor不能带入已验收的dirty/untracked内容，写任务标记 `blocked-input-baseline` 并报告。只读/文档准备不以修改基础设施来解锁。
7. 执行 `python tools/generate_project_map.py --check`。本文件编写时检查失败；若冻结后仍漂移，由主控根据生成器实际帮助和文档生成，再check。不要手改生成事实，也不要在第二阶段仍修改时抢写地图。

### 三、版本与配套合同（主控冻结）

- 用户已指定版本号则沿用；未指定时使用明确的候选标识，例如执行当日日期与源码清单哈希生成的 `rc-YYYYMMDD-<摘要>`。这是构建时计算的候选名称，不是现存正式版本，也不是声称实现了可复现的逐字节构建。
- 使用实际支持的 `VSE_TOOLBOX_VERSION`、`VSE_TOOLBOX_CHANNEL`、`VSE_TOOLBOX_BUILD_ID` 向构建子进程传递合法值，channel明确为候选。遵守当前长度/控制字符校验，不修改父会话长期环境，不打印全部环境变量。
- 两个EXE来自同一批准源码快照和依赖环境。WebUI已有 `/api/version` 元数据能力；不得虚构Worker也有 `--version` 或嵌入版本接口。Worker配套关系通过同次构建记录、源码快照标识和独立EXE哈希证明。
- 候选包manifest记录候选ID、UTC构建时间、HEAD、dirty标志、源码清单摘要、实际Python/PyInstaller版本、依赖清单证据索引、两个EXE文件名/大小/SHA-256。包内只用相对路径和脱敏信息，不放本机用户名、绝对路径、凭据、真实数据库或运行日志原文。
- SHA-256用于完整性校验，不是数字签名/发布者身份认证；无代码签名时不写“已签名”。

### 四、并行安排与文件归属

```text
G0主控核实第二阶段验收与冻结输入
  ├─ R1只读：构建/版本/运行路径证据
  ├─ R2只读：测试与离线烟测合同
  └─ W1文档：升级/回退及目标环境验收草案
          ↓ 主控冻结构建/运行/包内容合同
G1主控：非UI回归 → 配套构建 → 隔离离线烟测
          ├─ W2文档：发行说明与证据摘要
          └─ R3独立只读：manifest/包内容/源码映射核对
G2主控：最终封包、哈希复核、候选交付（M1）
U1用户：目标环境验收 → 问题闭环（M2）
```

最多3个独立只读/文档任务并行；只在运行时证实支持独立运行目录与worktree后使用此上限。writer文件不重叠，文档草案不能提前填通过结论。构建、子进程控制、数据库恢复方案由主控直接负责，不下放为“机械任务”。

使用官方现有入口；每个调用须先创建真实合同并DryRun：

```powershell
& 'C:/Users/Lynch/.zcode/tools/run-worker.ps1' -Workspace 'E:/project/vse-toolbox' -TaskFile 'E:/project/vse-toolbox/.agents/tasks/TASK-P3-R1.json' -DryRun
& 'C:/Users/Lynch/.zcode/tools/run-worker.ps1' -Workspace 'E:/project/vse-toolbox' -TaskFile 'E:/project/vse-toolbox/.agents/tasks/TASK-P3-R1.json'
```

所有槽位实际应解析为 `gemini-3.8-flash-high`，核对实际握手/预检。只读角色遵循现有readonly-explorer/code-reviewer路由，不能发明launcher参数。worker只用受控原生读写工具，没有shell、浏览器、递归智能体能力；检查由supervisor或主控执行。

不得使用裸 `zcode --prompt`、AGY、DeepSeek、周末profile或不同模型作隐式回退。模型/权限/配额/超时失败停止该路线并报告；同一代码缺陷最多两轮定向修复，之后交主控裁决。

## 五、细分任务卡

### R1 — 构建与运行边界证据（只读）

初始范围：`VSE-WebUI.spec`、`VSE-ExcelWorker.spec`、`tools/build_excel_bundle.ps1`、`core/version.py`、`core/runtime_paths.py`、`tools/excel_worker_cli.py`。仅在解释入口副作用时扩大到已找到的一层依赖。

- [ ] 核对两个spec的实际入口、依赖和数据打包范围，以及构建器参数、清理行为。
- [ ] 核对WebUI元数据来源、Worker真实CLI能力；列出不存在/未证明的接口。
- [ ] 核对冻结包写入根目录、回退目录、应用初始化是否启动任务/外部请求。
- [ ] 提交精确构建调用建议和隔离条件；不启动构建，不执行EXE，不修改spec。

验收：每项结论有实际路径/符号/行号；不把“WebUI排除xlwings”扩写成完全无COM依赖。当前WebUI还包含WinHTTP相关COM依赖，应以实际spec为准。报告不超过1200中文字及证据表。

### R2 — 回归与烟测方案（只读）

初始范围：`tests/test_version_and_usability.py`、`tests/test_runtime_paths.py`、`tools/excel_worker_cli.py`、`web/app.py` 中 `/api/version`、`/api/overview` 与初始化路径。

- [ ] 核对fixture临时DB注入和初始化副作用，不能仅靠未实现的数据库环境变量。
- [ ] 从map路由定向找到相关打包、Worker与项目状态测试；输出实际存在的非UI节点白名单和参数数组，不猜文件名。
- [ ] 设计隔离烟测：EXE放独立可写目录、随机未占用端口、受控子进程环境、进程树收尾、响应字段断言。
- [ ] 核对Worker `--help` 是否在创建库/启动COM之前返回。若不能证明，先报告，不直接运行。

验收：能区分import/启动烟测、业务执行验证、真实Office验证；每个未覆盖项明确列出。不能声称工具无权限执行的测试已经通过。

### W1 — 升级/回退与目标环境验收文档（独占新文档）

拥有新文件：`docs/PHASE3_DEPLOYMENT_RUNBOOK_20260917.md`。只读既有生产指南、第二阶段人工清单与G0/R1合同，不修改共享操作手册。

- [ ] 写清同目录部署两个配套EXE、候选标识/哈希核对、端口及运行目录验证。
- [ ] 升级前准备：识别相关进程和任务、停止业务调度、记录原程序/数据库schema及配置、确认备份位置。只给步骤，本任务不执行生产操作。
- [ ] SQLite一致性备份须来自经过核实的停机完整备份或SQLite备份API方案；不能复制运行中的单个.db文件就声称一致，不能丢掉未checkpoint的WAL。具体方案由主控审定。
- [ ] 回退仅在旧程序与数据库schema兼容时进行；不兼容时需恢复配套历史程序与一致性备份，明确备份后新增数据的丢失风险。不能建议旧EXE直接打开新版schema，也不能默认授权覆盖真实数据。
- [ ] 目标环境验收项包含Windows实际版本/架构、Python未安装条件、Excel实际安装及位数、Aras/TDC分别登录查询、合成Excel任务、合成归档、重启后结果、第二阶段关键UI操作。
- [ ] 每项用例包含版本/环境、前置条件、操作、预期、实际、证据索引、验收人/时间；实际结果默认待验。真实官方报表生成等有副作用功能需用户选择测试范围，不能自动执行。

验收：不把项目指南的宽泛环境支持声明当成每个平台都已测试；不包含真实凭据；只写当前证实的按钮和参数。主控审查恢复部分后才可收入交付包。

### G1 — 主控回归、配套构建和离线烟测

先审查R1/R2，再执行；不因已有历史通过记录跳过冻结后的检查。

基础命令：

```text
python -m pytest -q tests/test_version_and_usability.py -k "not dashboard_renders_usability_elements"
python -m pytest -q tests/test_project_status_contracts.py tests/test_project_status_updates.py tests/test_project_status_admin_api.py
python -m compileall -q core services web
git diff --check
python tools/generate_project_map.py --check
```

前两条仅在确认实际fixture隔离后运行。R2提供确实存在的打包/Worker相关非UI白名单，主控加入并执行。用户仍负责UI验收，不执行UI单元测试、前端源码断言或浏览器自动测试。

当前已有双EXE构建脚本，可核实后复用 `-PythonExecutable`、`-OutputDir`、`-WorkDir`、`-NoCleanup`。选择本轮唯一的新目录，不覆盖旧产物；保留日志，不调用未知或未审查的清理路径。

例如当候选ID和目录已计算并校验后，构建过程调用现有脚本；不要把本文件中的日期当作固定版本，不要在默认dist根目录覆盖文件。启动隐藏的辅助进程时使用 `-WindowStyle Hidden`。

必须验证：

1. 两个构建退出码都为0，两个EXE均存在且非空；缺Worker时只能报告WebUI局部产物，不能交付完整配套包。
2. 在独立可写目录运行EXE：**只改变cwd不足以隔离**。冻结包 `app_root()` 优先使用EXE所在目录，并可能回退至用户数据目录。启动前核实可写性、实际隔离路径及空数据初始化；不得落入真实用户数据目录。
3. 只在loopback随机端口运行WebUI，记录本次PID；启动前确认无生产任务/凭据导入，不自动执行外部同步。
4. 清除子进程运行时版本环境变量后，`/api/version` 仍返回预期嵌入的候选版本、channel、buildId。只检查HTTP 200不够。
5. `/` 与 `/api/overview` 基于新合成/空库返回符合实际合同的结果；读取响应不等于UI已通过。
6. 检查包内模板/静态资源与冻结的第二阶段源码相符，不能只依据文件名或版本字符串认定新UI已被打包；使用归档内容或响应资源哈希等可复核方法，不创建前端源码断言测试。
7. Worker经R2证明安全后执行 `--help`，验证解析器启动。没有运行合成Office任务时明确“COM业务执行未验证”。不得发明 `--version`、无副作用状态接口或自动启动真实队列。
8. 尝试以受限PATH启动候选包时，只能声称不依赖PATH中的Python；这不能证明干净Windows机器没有缺失运行库。干净机验收保留给U1。
9. 通过PID及受控子进程树清理本次进程，避免按 `python.exe`/`EXCEL.EXE` 等名字批量结束。失败超时也执行本次收尾，记录残留状态。不要关闭用户已有Office进程。
10. 对合成数据进行主控审定的备份/恢复演练，比较恢复后的记录/关键设置与预设期望。只在独立测试目录操作，不触碰真实库。测试方法不能偷换成空文件复制。

当前历史遗留真实库的 `archiveDirectory` 原值未知，不属于本阶段自动修复范围。不得猜测恢复或删除临时目录。

构建失败或缺依赖先报告实际错误。修复必要打包缺陷时另列owned文件和focused测试；不能静默删hiddenimports、排除关键模块、放宽schema保护或修改业务实现让烟测通过。

### W2 — 发行说明与证据摘要（G1结果稳定后）

拥有新文件：`docs/PHASE3_RELEASE_NOTES_20260917.md`。

- [ ] 基于实际集成差异描述第一/二阶段改进，区分本阶段仅做的交付工作。
- [ ] 记录候选ID、实际配套组件、验证命令/退出码/证据、已知限制及目标环境待验项。
- [ ] 不抄旧包hash、旧用例数量或旧版本状态，不把缺失依赖写成成功。
- [ ] 写明WebUI与Excel Worker关系、Office仍需单独安装、本阶段无自动部署。

验收：每项“已验证”可追溯到主控本次结果。M1和M2分开，不代用户填写验收结果。

### R3 — 独立只读交付审查

范围：主控生成的manifest、源码快照摘要、两EXE校验结果、ZIP清单/完整性结果、W1/W2文档、G1证据。只接收脱敏摘要，worker无shell/二进制验证能力时由主控提供实际命令输出，不伪称worker独立运行过哈希工具。

- [ ] 核对源码基线、buildId、两组件和发行说明相互一致。
- [ ] 核对ZIP只含批准发布内容，没有真实数据库、凭据、测试输入、日志、.runtime或旧EXE。
- [ ] 核对校验文件覆盖实际工件；哈希清单不自包含形成循环。ZIP校验文件放ZIP外；最终封包后重新计算ZIP哈希。
- [ ] 核对升级/回退说明与schema实际约束一致，Office/干净机/内网验证未被离线烟测冒充。

验收：报告通过/发现问题/证据不足，列出精确范围与证据；主控复核后才可完成M1。

## 六、合同与反幻觉要求（每个worker必须携带）

每个合同必须有真实的 `task_id`、`objective`、`scope`、`constraints`、`acceptance_criteria`、`risk_class`、`task_kind`、`model_slot`、`verification_commands` 参数数组。只读任务使用当前schema支持的只读权限设置；不能只靠提示词声明。R1/R2用exploration，文档用mechanical，审查用当前受控review路由；实际槽位解析仍须核对。

W1/W2文档任务的机械验证可用 `[["git", "diff", "--check"]]`，但它不能替代事实审查。只读任务用前后文件哈希和未跟踪文件清单证明未写入；初始有dirty差异时不能用 `git diff --exit-code` 误判。高风险的构建控制、恢复和部署方案由主控负责，不伪标低风险。

所有worker约束：

1. 结论标记 observed/inferred/unknown/proposed；路径、符号、行号来自当前输入，不能照抄历史定位。
2. 引用工具、参数、API、环境变量、状态或字段前定位定义和相关调用；未发现就报告，不能创造不存在的能力。
3. 报告实际run ID、实际模型和检查结果；无运行证据不能声称调用多个智能体或完成验证。
4. 构建成功不等于运行成功；启动成功不等于COM业务成功；PATH隔离不等于干净机；离线成功不等于内网成功；哈希不等于签名。
5. 测试结果只用本次实际输出，失败/跳过/未执行均列出；重叠集合不能相加，旧日志不能冒充新结果。
6. 不读取或转交凭据、生产数据库内容、完整环境变量、原始业务数据；交付包只含明确定义的相对路径文件。
7. 已存在的正确功能保持不变；必要缺陷先提供触发条件/根因/最小范围，不能顺便重构。
8. 不删测试、不弱化断言、不扩大skip、不吞异常、不添加假版本/假进度，不为“完成”篡改验收文档。
9. 我不是仓库唯一工作者，只写owned文件，不覆盖他人改动，不修改共享memory；需扩大scope先交主控判断。
10. 权限/模型/配额/超时失败明确停止该路线，不切换provider。仅代码缺陷允许最多两轮同根因修复。

## 七、G2候选包结构与交付

包内建议白名单（以最终批准的实际文件为准）：

```text
VSE-WebUI.exe
VSE-ExcelWorker.exe
SHA256SUMS.txt
release-manifest.json
RELEASE_NOTES.md
DEPLOYMENT_RUNBOOK.md
```

使用命名包含候选ID的独立输出目录。从原始未运行的构建产物封包，运行烟测生成的data/log等不能进入发布目录。主控核对ZIP所有条目、完整CRC读取、两EXE哈希和ZIP外部SHA-256；包内容变化就重新执行对应核验。

公开交付manifest与内部证据分离；详细源码文件清单、机器环境和日志保留本轮私有证据目录，不盲目塞进ZIP。不要追求未经用户要求的固定包体大小或额外压缩依赖。

最终M1报告：候选ID/源码摘要、两个EXE与ZIP本地路径、实际大小和SHA-256、验证结果、未验证项、目标环境清单。候选包发布到外部、替换生产文件、恢复真实数据等均不在本地准备授权内。

## 八、U1目标环境验收与最终状态

用户基于同一候选包校验哈希后，在目标机器验证：无需Python启动、配套Worker识别、Aras/TDC独立会话与查询、合成Excel业务操作、合成归档、第二阶段关键UI、重启后状态。真实系统的账户和生产操作由用户控制，不要求传递凭据。

无Office/网络条件时明确对应项待验，不阻止离线M1交付，也不将其标为M2通过。用户反馈缺陷后，先定位源码/打包/目标环境哪一层，再最小修复；构建新候选需新标识与哈希，并复验受影响链路。

只有用户明确完成目标环境验收且已处理阻断问题后，才记录M2完成。主控最后更新memory/CURRENT_STATE.md及必要的RECOVERY_NOTES，记录真实状态；尚待用户操作时保留明确下一步，不写“全部完成”。
