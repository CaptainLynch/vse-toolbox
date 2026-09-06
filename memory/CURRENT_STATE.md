# Current State

Last checkpoint: 2026-09-06（goal 收尾：环图节点自动显示规则落地 +
code-reviewer 审计修复 + 已提交 c6286d5/5e100b3，全量 1690 passed）。

## Current objective

Branch `feature/scheduled-deliverables-overview-excel` 全部既定工作已完成并
提交：默认里程碑模板（11 空日期节点）、交付物配置读侧联动、tdc_sor 第 6
统一表单、环图"按节点状态自动显示"规则。代码已 commit，无遗留编码任务。

## 已提交状态

- c6286d5 feat：里程碑模板/空日期、formLink 读侧联动、tdc_sor 注册、
  环图 auto 规则、筛选栏分组布局与多选按需展开（19 files, +1417/-269）。
- 5e100b3 chore：开发验证与演示数据工具脚本（generate_preview_data.py、
  tools/verify_*.py 等 5 个）。
- 工作树仅剩 PPT_Table_Title_Sync.bas（会话前已存在的无关文件，未提交）。

## code-reviewer 审计轮（已全部修复并验证）

1. [P1] auto 隐藏改用快照换算后的完成态（deliverableFormDisplay 优先），
   与环图口径一致；契约测试同步更新。
2. [P1] DELIVERABLE_FORM_KEY_BY_ITEM 与归档详情 labels 补 tdc_sor 映射
   （否则 #archive-deliverable/tdc_sor 无法加载表单视图，已冒烟验证）。
3. [P2] tdc_data_model 逾期说明区分终态文案（已废弃 vs SOR 已终止）。
4. [P2/P3] auto 规则契约测试改为断言派生状态逻辑；下拉 select 值重渲染
   时与 deliverableProgressFilterValue 重同步。
- 另在自测中发现并修复：节点关键字匹配用子串/连字符分词会把
  「VPI-T2 Gate」误判为 VPI 节点，改为空格分词精确匹配。

## 环图 auto 规则口径（产品可调）

DELIVERABLE_AUTO_HIDE_NODE_KEYWORDS（app.js）：D1→VDR、D2→VPI、D3→T2、
D4→VDR、D5→T2；仅 auto 模式、仅已完成（含快照换算）、节点已排期且日期
已过才隐藏；band-head 显示"已隐藏 N 项已完成交付物"。调整映射只改此常量。

## Validation

- 最终全量 pytest：1690 passed, 2 skipped；flake8 / compileall /
  node --check 全绿。
- 浏览器冒烟：D1 auto 隐藏 + 提示 + all 恢复；#archive-deliverable/tdc_sor
  表单视图加载；D2/D5 详情快照联动此前均已验证（.runtime/smoke_*.png）。
- dev 库 v13，含 tdc_sor/tdc_data_model/ncr 演示快照；WebUI 运行 5000 端口。

## Next action

- 无遗留编码任务。可选后续：节点↔交付物关键字映射按业务实际微调
  （改 DELIVERABLE_AUTO_HIDE_NODE_KEYWORDS）；TDC A 面契约解锁后为 D4
  注册表单；推送远端/发 PR 由用户决定。
