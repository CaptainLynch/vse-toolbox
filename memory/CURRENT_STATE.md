# Current State

Last checkpoint: 2026-09-06 (ZCode 主导：三项已交付功能 + SOR 定点流程注册为
第 6 个统一表单，全量 1689 passed)。

## Current objective

Branch `feature/scheduled-deliverables-overview-excel` 已交付：默认里程碑
模板（11 空日期节点）、交付物配置读侧联动、总览环图换算+显示筛选钩子、
SOR 定点流程（tdc_sor）统一表单注册。全部实现、测试并通过浏览器冒烟。

## 本轮实现（ZCode main + general-purpose(Flash) 子智能体协作）

- 前端工作包子智能体完成（app.js/style.css），Main 审计通过并补齐其遗留的
  测试契约缺口；后端工作包子智能体被取消，Main 接手完成全部剩余实现。
- 教训：接手被取消的子智能体半成品必须先 `python -m py_compile` 全文件
  校验（本次曾发现孤儿 `"""` 定界符导致字符串级联错位，报错行号远离真实
  出错点，用 diff hunk 三引号增删计数定位）。
- SOR 注册配方（新增 TDC 表单照此办理）已沉淀至 DECISIONS.md 2026-09-06
  条目：DDL 白名单+重建检测 → 分析服务四映射+维度/逾期/状态归一 →
  runner job→form map → DELIVERABLE_FORM_LINKS → app.js 四映射 → 四层测试。

## 已交付契约

1. 里程碑默认模板（11 节点，空日期=待排期、未开始/planned）：
   VPI、内饰模型评审、外饰模型评审、LLP VDR、100% VDR、LLP T2、100% T2、
   OTS、验证阀、内部体验阀、用户体验阀。schema v13 里程碑日期可空。
2. 空日期校验前后端同文案（"空日期节点状态必须为未开始"）；
   current_stage_label 跳过空日期；时间轴空日期线性内插定位。
3. 种子修复：全字段元组比对，仅与旧 6 节点种子完全一致才替换为模板；
   dev 库 F610S 里程碑因用户编辑过被正确保留。
4. formLink：/api/project-status 每交付对象 {formKey, snapshotAt, summary}；
   后端单源 DELIVERABLE_FORM_LINKS：D2→tdc_sor、D3→VPI-T2-D3、D5→tdc_data_model。
5. 读侧联动：deliverableFormDisplay 换算（completed/total、三态状态）；
   环图与详情状态图表共用；derived 标签"快照进度"+日期；无快照回退手工值。
6. tdc_sor 表单：15 列合同、维度（车型项目/科室/部门/类型）、
   Completed→已完成 归一、已终止终态、滞留 7 天逾期、当前待办人脱敏；
   详情页签 车型项目状态/科室状态/数量趋势；筛选标签按 SOR 语境覆盖。
7. 环图显示筛选：band-head"显示"下拉（全部交付物可用；按节点状态自动
   显示 disabled 预留），shouldShowDeliverable 钩子待接节点规则。

## Validation

- 全量 pytest：1689 passed, 2 skipped（SOR 注册后二次全量）。
- flake8 / compileall / node --check 全部通过。
- 浏览器冒烟：D2 详情显示 SOR 表单分析完整视图（汇总 5/2/3/3、
  车型项目状态图、15 列明细表、SOR 语境筛选栏，.runtime/smoke_sor_detail.png）；
  此前 D5 快照联动与全新库 11 节点待排期渲染均已验证。
- dev 库已迁移 v13 并注入 tdc_sor/tcd_data_model/ncr 演示快照
  （generate_preview_data.py 可重跑）；WebUI 已重启加载全部新代码。

## Next action

- 用户验收：刷新 http://127.0.0.1:5000；交付物明细 D2/D3/D5 均有表单联动，
  D1/D4 保持手动（D4 等 TDC A 面契约解锁）。
- 待办：环图"按节点状态自动显示"规则（接入 shouldShowDeliverable）；
  代码未 commit，用户要求时提交。
