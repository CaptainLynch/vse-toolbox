# Current State

Last checkpoint: 2026-09-07（全项目系统性评审完成并达成一致；一致修复项
M8/N2/N4/M4/M1/M2 全部实施并提交 3bcdd84；全量 1703 passed, 2 skipped；
实际运行抽查 PASS。注意：存在并行会话写入冲突，见"冲突仲裁"）。

## 全项目评审（主审 + code-reviewer 两轮收敛，2026-09-07）

- 主审 10 项发现（M1-M10，含 2 项干净项观察）+ 复核独立新增 5 项
  （N1-N5）；第一轮 3 条裁决基于修复前代码，经证据回传后第二轮
  re-verify 全部确认，**双方一致**。
- 已修复关闭并契约锁定：M3 明细表 colspan/表头错位、N1 hasExplicitValue
  显式空串保护（key in filters）、N3 plan-name 缓存复用
  overviewSavedState。
- 本轮已实施（3bcdd84）：M8 多选重绘前暂存未提交的
  keyword/relationEwo/date 输入（pendingFilterInputs，apply/clear 清空）；
  N2 archive_store os.link 在不支持硬链接介质降级 os.replace；N4
  redaction 新增 _XML_RE XML 标签脱敏；M4 generate_preview_data.py 拒绝
  缺省写主库（--db 显式指定或 --dry-run 预览）；M1 runner 映射提取
  JOB_FORM_KEYS + tests/test_form_key_consistency.py 锁五处白名单一致；
  M2 前端 PROJECT_PHASE_ID 常量收敛 5 处 VPI-T2 硬编码（VPI-T2-D*
  交付物 ID 不变）。
- 正向资产：38 写端点 loopback 全覆盖（TDC 9 端点经共享 helper）、
  内联编辑脱敏、formLink 仅数值摘要、409 乐观锁自洽。

## 冲突仲裁（重要）

并行会话（GPT 迁移，docs/GPT_MIGRATION_PROMPT_b63397f7.md）曾改写本文件
并声称"M4 自 5e100b3 起已有 --db/--dry-run、无需修复"。**git 历史证伪**：
`git show 5e100b3:generate_preview_data.py` 不含 argparse（count=0），
argparse 保护系 3bcdd84 实现（count=6）。遇并行写入冲突，以
`git show <commit>:<file>` 取证为准；本文件按协议整体重写为权威状态。
docs/{GPT_MIGRATION_PROMPT,SESSION_COMPLETION,SESSION_HANDOFF}_b63397f7.md
为该会话遗留未跟踪文件，未纳入版本控制（保持原状，由用户决定去留）。

## 验证

- 全量 pytest：1703 passed, 2 skipped（skip 为环境条件：pwsh/symlink）。
- flake8 / node --check 全绿；实际运行抽查
  （tools/verify_consensus_fixes.py）：M8 关键字保留 ✓、N3 默认值
  F610S ✓、目录 6 条 ✓。

## Backlog（双方一致记录在案，按需排期）

- N5：excel_worker_process_controller 子进程退出 stderr 摘要入
  status.error。
- M5：README.md"纯命令行/零 Web 框架"陈述与现状不符，需修订。
- M6：tools/verify_*.py 头部补"需 5000 端口服务运行"前提说明。
- M7：app.js ~11200 行，长期按域模块化拆分（需评估契约测试与打包）。

## Next action

- 无阻塞任务。branch 未推送远端；是否 push/发 PR 由用户决定。
- 若并行 GPT 会话继续工作，请先协调：同一工作树禁止双写。