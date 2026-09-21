# 第三阶段候选版本交付记录

候选：`rc-20260916T164923Z-46e060ddaed4`。本次构建来自包含未提交修改的冻结快照，源码摘要 `46e060ddaed4018ee2bb0a3d4c766637889b5e1d1d3a74f4e32e9746b27af504`。日期标识使用UTC（对应北京时间2026-09-17）。

## 当前状态

候选包已构建并通过下述离线检查。第二阶段UI、目标Windows/Office及真实内网仍待用户验收，未部署或上传。本次没有修改业务代码。

包含第一阶段版本/会话/错误恢复/设置展示，以及第二阶段查询空结果、历史结果提示、Excel/归档记录反馈。功能验收以用户实际操作为准。

## 构建与验证

- Python 3.12.10；PyInstaller 6.21.0；两个EXE由同一快照、同次构建生成。Worker没有版本API，配套关系由manifest及两个EXE哈希证明。
- 版本非UI测试：15 passed，1 UI case deselected。
- 项目状态合同/更新/管理API：156 passed。
- Worker CLI/控制器、运行路径与打包：29 passed。
- compileall、JavaScript语法、工作区diff及地图检查通过；语法不代表UI通过。
- 冻结包清除运行时版本变量后，rawVersion/channel/buildId符合构建值；isFrozen=true。
- 首页和新库总览通过。新库含程序设计的“未归类”兜底项目，不是零项目。
- 4个服务端静态资源与源码逐字节一致；打包模板与快照一致。
- EXE位于独立可写目录，子进程PATH只保留Windows系统目录，临时/应用数据环境隔离；Worker --help退出0。
- 本次WebUI进程树已结束，烟测端口已关闭。
- 合成app_settings标记经SQLite backup API备份/恢复后值正确，PRAGMA integrity_check=ok，应用项目表保持预期。

首次两次烟测因主控校验脚本误用version字段、误认为初始化项目数为0而中止。核对rawVersion返回字段和默认种子代码后修正验证脚本，保留原失败证据；业务代码未改。第三次烟测通过。

## 未验证与限制

- 未在无Python的干净机器验证；受限PATH只是本机验证。
- Worker帮助启动不代表Excel COM业务执行；真实Office任务、Aras/TDC内网、归档业务和UI仍待验。
- 历史真实库archiveDirectory问题未恢复；仅操作本轮隔离合成数据库。
- SHA256不是数字签名；没有完成发布者签名校验。
- 构建脚本既有清理路径前缀检查有待单独加强；本次使用全新明确目录及-NoCleanup，未调用该清理分支。
- 未做包体压缩目标保证，未引入额外依赖；原部署目录和旧包保持不变。

包内见DEPLOYMENT_RUNBOOK.md。完整命令与日志保留在本地本轮证据目录，manifest提供相对证据索引，不把日志/机器绝对路径/数据库放进ZIP。
