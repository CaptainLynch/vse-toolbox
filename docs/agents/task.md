# 📝 task.md — 任务拆解与进度追踪

> **用途**: Architect 将功能需求拆解为函数级别的具体任务，Worker 逐项执行并勾选。
> **维护者**: Architect 创建任务，Worker 标记完成状态，Reviewer 确认。
> **规则**: 每项任务的粒度必须精确到单个函数或方法，禁止一次性指派整个文件。

---

## 任务状态图例

- `[ ]` 待执行
- `[~]` 进行中（Worker 已开始但未完成测试）
- `[x]` 已完成（已通过 pytest + flake8 验证）
- `[!]` 阻塞（需人工介入或其他任务前置）

---

## 当前迭代: Sprint 1 — 基础设施

### 1. core/db_manager.py

- [x] 1.1 `DatabaseManager.__init__()` — 初始化数据库路径和目录
- [x] 1.2 `DatabaseManager.init_database()` — 建表 DDL + WAL 模式 + 外键约束
- [x] 1.3 `DatabaseManager.get_connection()` — contextmanager 连接管理器
- [x] 1.4 `DatabaseManager.execute_script()` — 多语句 SQL 执行
- [x] 1.5 `DatabaseManager.table_exists()` — 表存在性检查
- [x] 1.6 `DatabaseManager.get_table_row_count()` — 表行数统计

### 2. services/office_toolbox.py (win32com COM)

- [x] 2.1 `OfficeToolbox.__init__()` — 初始化输出/模板目录
- [x] 2.2 `OfficeToolbox._check_file_not_locked()` — 文件占用检查
- [x] 2.3 `OfficeToolbox._fetch_deliverables()` — 交付物数据查询
- [x] 2.4 `OfficeToolbox._fetch_feishu_summary()` — 飞书待办查询
- [x] 2.5 `OfficeToolbox.export_deliverables_excel()` — Excel COM 导出 (Excel.Application)
- [x] 2.6 `OfficeToolbox.refresh_weekly_ppt()` — PPT COM 生成 (PowerPoint.Application)

### 3. services/feishu_imap.py

- [ ] 3.1 `FeishuImapParser._get_credentials()` — 终端交互获取凭据（改用 imapclient）
- [ ] 3.2 `FeishuImapParser._connect()` — IMAP SSL 连接（改用 imapclient）
- [ ] 3.3 `FeishuImapParser._parse_task_from_body()` — 调整实际飞书邮件正则
- [ ] 3.4 `FeishuImapParser.scan_and_parse()` — 端到端扫描流程适配

### 4. services/intranet_scraper.py

- [ ] 4.1 `IntranetScraper._scrape_data()` — 补充实际内网页面选择器
- [ ] 4.2 `IntranetScraper._save_to_database()` — 验证数据入库逻辑

### 5. tests/ (新增)

- [ ] 5.1 `tests/test_db_manager.py` — db_manager 单元测试
- [ ] 5.2 `tests/test_office_toolbox.py` — office_toolbox 单元测试（mock COM）
- [ ] 5.3 `tests/test_feishu_imap.py` — feishu_imap 单元测试
- [ ] 5.4 `tests/conftest.py` — 公共 fixtures（临时数据库等）

---

## 历史迭代

> （暂无）
