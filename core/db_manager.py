# -*- coding: utf-8 -*-
"""
core/db_manager.py — SQLite 数据库连接管理、表结构初始化与迁移

职责:
    1. 管理 SQLite 连接的生命周期（上下文管理器）
    2. 初始化 / 迁移所有业务表结构
    3. 提供统一的数据访问入口，禁止各 service 裸连数据库

各领域的数据访问方法在 core/repos/ 下（项目状态、表单快照、自动同步、
定时归档、crawl 任务），DatabaseManager 继承它们，对外接口不变。共用的
常量、DDL、异常与辅助函数在 core/db_common.py，这里原样再导出以保持
``from core.db_manager import X`` 兼容。

架构约束:
    - 使用 WAL 模式提升并发读写性能
    - 所有表使用 ISO-8601 时间戳
    - 启用外键约束 (PRAGMA foreign_keys = ON)
"""

from core.db_common import (  # noqa: F401
    _DELIVERABLE_FORM_SNAPSHOTS_DDL,
    _dump_extra_fields,
    _form_json,
    _form_registry,
    _FORM_ROW_FILTER_KEYS,
    _form_row_filter_sql,
    _FORM_SNAPSHOT_FORBIDDEN_KEY_PARTS,
    _FORM_SNAPSHOT_KEYS,
    _form_snapshot_payload,
    _FORM_SNAPSHOT_REPORTS,
    _FORM_SNAPSHOT_RETENTION,
    _is_forbidden_form_key,
    _json_dumps_local,
    _json_loads_or_none,
    _LOCAL_NOW_SQL,
    _normalize_archive_retry_policy,
    _PROJECT_STATUS_DELIVERABLES_DDL,
    _PROJECT_STATUS_MILESTONES_DDL,
    _sanitize_form_value,
    _sanitize_json,
    _UTC_NOW_SQL,
    _utc_offset_sql,
    Any,
    app_root,
    ARCHIVE_CREDENTIAL_UNCHANGED,
    ARCHIVE_JOB_CONTRACTS,
    ARCHIVE_OUTPUT_DIRECTORY_UNCHANGED,
    ARCHIVE_RETRY_UNCHANGED,
    ArchiveJobNotReadyError,
    ArchiveLeaseBusyError,
    ArchiveLeaseLostError,
    contextmanager,
    CURRENT_SCHEMA_VERSION,
    DEFAULT_DB_DIR,
    DEFAULT_DB_PATH,
    DELIVERABLE_LINK_REGISTRY,
    find_deliverable_id_by_form_key,
    Generator,
    json,
    logger,
    logging,
    MappedDeliverableReadOnly,
    MappedDeliverableReadOnlyError,
    Mapping,
    observed,
    operation,
    Path,
    PROJECT_STATUS_EDITABLE_FIELDS,
    project_status_manual_editability,
    PROJECT_STATUS_MILESTONE_TEMPLATE,
    PROJECT_STATUS_SOURCE_CAPABILITIES,
    ProjectStatusConcurrentUpdateError,
    re,
    redact_sensitive_text,
    secrets,
    Sequence,
    sqlite3,
    SYNC_DEFAULT_RETRY_POLICY_JSON,
    SYNC_LEASE_DEFAULT_SECONDS,
    SYNC_LEASE_MAX_SECONDS,
    SYNC_LEASE_MIN_SECONDS,
    SyncBindingNotReadyError,
    SyncLeaseBusyError,
    SyncLeaseLostError,
    TABLE_DEFINITIONS,
)
from core.repos.archive_jobs import ArchiveRepo
from core.repos.crawl_tasks import CrawlTaskRepo
from core.repos.form_snapshots import FormSnapshotRepo
from core.repos.plugin_schema import PLUGIN_SCHEMA_VERSIONS_DDL, PluginSchemaRepo
from core.repos.project_status import ProjectStatusRepo
from core.repos.sync_runs import SyncRunRepo


class DatabaseManager(
    ProjectStatusRepo, FormSnapshotRepo, SyncRunRepo, ArchiveRepo, CrawlTaskRepo, PluginSchemaRepo,
):
    """
    SQLite 数据库管理器

    用法:
        db = DatabaseManager()
        db.init_database()

        with db.get_connection() as conn:
            conn.execute("SELECT * FROM projects")
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        """
        初始化数据库管理器。

        Args:
            db_path: SQLite 文件路径。为 None 时使用默认路径 data/vse_toolbox.db
        """
        self._db_path = Path(db_path) if db_path else DEFAULT_DB_PATH

        # 确保 data/ 目录存在
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info("数据库路径: %s", self._db_path)

    @property
    def db_path(self) -> Path:
        """返回当前数据库文件路径"""
        return self._db_path

    def init_database(self) -> None:
        """
        初始化数据库: 创建表结构、启用 WAL 模式和外键约束。

        幂等操作，重复调用不会破坏已有数据。
        """
        try:
            with self.get_connection() as conn:
                # 先检查 schema 版本，拒绝降级，再执行任何 DDL。
                # 避免在未知较新 schema 上执行 DDL 后才失败。
                existing_version = conn.execute("PRAGMA user_version").fetchone()[0]
                if existing_version > CURRENT_SCHEMA_VERSION:
                    raise sqlite3.DatabaseError(
                        f"unsupported schema version {existing_version}; "
                        f"this build supports up to {CURRENT_SCHEMA_VERSION}"
                    )

                # 启用 WAL 模式 — 提升并发读写性能
                conn.execute("PRAGMA journal_mode=WAL;")
                # 启用外键约束
                conn.execute("PRAGMA foreign_keys=ON;")

                # 执行所有建表 DDL
                for ddl in TABLE_DEFINITIONS:
                    conn.execute(ddl)

                # 增量迁移：为旧库补齐调度相关列与新表，并维护 user_version。
                # 新库因 DDL 已含最终字段，迁移为幂等 no-op，仅提升版本。
                self._migrate_schema(conn, existing_version)

                # 幂等插入 id=1「未归类」兜底项目，防止 deliverables.project_id 外键孤儿
                conn.execute(
                    "INSERT OR IGNORE INTO projects (id, name, manager, status) "
                    "VALUES (1, '未归类', 'system', 'active');"
                )
                self._seed_project_status(conn)
                self._seed_archive_jobs(conn)

                conn.commit()

            logger.info("数据库初始化完成")

        except sqlite3.Error:
            logger.exception("数据库初始化失败")
            raise

    @staticmethod
    def _migrate_schema(conn: sqlite3.Connection, existing_version: int) -> None:
        """
        幂等增量迁移。

        - 调用方已在执行任何 DDL 前拒绝高于 CURRENT_SCHEMA_VERSION 的库。
        - 对旧库通过 PRAGMA table_info 检测缺失列，逐列 ALTER TABLE ADD COLUMN。
        - 迁移失败由外层 get_connection 回滚，不会留下半迁移状态。
        """
        # deliverable_form_snapshots 旧库带 form_key CHECK 白名单，SQLite 无法
        # ALTER 掉约束，需要整表重建。回退到旧版 exe 时旧版会再按它的白名单
        # 重建一次（数据只含已注册的键，无损），再升级时这里又会去掉 CHECK。必须在任何 DML 隐式开启事务之前于事务外
        # 关闭外键，重建并提交后再恢复，随后继续的迁移/种子写入仍受外键约束。
        # 中途失败时原表保持完整；残留的重建表会在下次初始化时清除。
        conn.execute("PRAGMA foreign_keys=OFF")
        try:
            # schema v13：project_status_milestones.milestone_date 由 NOT NULL
            # 放宽为可空（空日期=待排期）。SQLite 无法修改列约束，检测到旧库
            # 仍为 NOT NULL 时按模板整表重建并保留数据。
            milestone_columns = {
                str(column["name"]): int(column["notnull"])
                for column in conn.execute("PRAGMA table_info(project_status_milestones)")
            }
            if milestone_columns and milestone_columns.get("milestone_date") == 1:
                conn.execute("DROP TABLE IF EXISTS project_status_milestones_rebuild")
                conn.execute(
                    _PROJECT_STATUS_MILESTONES_DDL.format(
                        table="project_status_milestones_rebuild"
                    )
                )
                conn.execute(
                    "INSERT INTO project_status_milestones_rebuild "
                    "(id, phase_id, name, milestone_date, status, type, sort_order) "
                    "SELECT id, phase_id, name, milestone_date, status, type, sort_order "
                    "FROM project_status_milestones"
                )
                conn.execute("DROP TABLE project_status_milestones")
                conn.execute(
                    "ALTER TABLE project_status_milestones_rebuild "
                    "RENAME TO project_status_milestones"
                )
                conn.commit()

            row = conn.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = 'deliverable_form_snapshots'"
            ).fetchone()
            if row is not None and re.search(
                r"CHECK\s*\(\s*form_key\s+IN", str(row["sql"] or "")
            ):
                conn.execute(
                    "DROP TABLE IF EXISTS deliverable_form_snapshots_rebuild"
                )
                conn.execute(
                    _DELIVERABLE_FORM_SNAPSHOTS_DDL.format(
                        table="deliverable_form_snapshots_rebuild"
                    )
                )
                conn.execute(
                    "INSERT INTO deliverable_form_snapshots_rebuild ("
                    "id, snapshot_key, form_key, report_type, source_run_id, "
                    "source, snapshot_at, row_count, schema_json, summary_json, "
                    "charts_json, artifacts_json, created_at) "
                    "SELECT id, snapshot_key, form_key, report_type, "
                    "source_run_id, source, snapshot_at, row_count, "
                    "schema_json, summary_json, charts_json, artifacts_json, "
                    "created_at FROM deliverable_form_snapshots"
                )
                conn.execute("DROP TABLE deliverable_form_snapshots")
                conn.execute(
                    "ALTER TABLE deliverable_form_snapshots_rebuild "
                    "RENAME TO deliverable_form_snapshots"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_deliverable_form_snapshots_latest "
                    "ON deliverable_form_snapshots(form_key, snapshot_at DESC, id DESC)"
                )
                conn.commit()
        finally:
            conn.execute("PRAGMA foreign_keys=ON")

        # project_status_update_bindings 调度相关增量列。
        existing = {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(project_status_update_bindings)"
            )
        }
        additions: list[tuple[str, str]] = [
            ("cursor_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("credential_ref", "TEXT"),
            ("lease_token", "TEXT"),
            ("lease_acquired_at", "TEXT"),
            ("lease_expires_at", "TEXT"),
            ("retry_policy_json", f"TEXT NOT NULL DEFAULT '{SYNC_DEFAULT_RETRY_POLICY_JSON}'"),
        ]
        for column, decl in additions:
            if column not in existing:
                conn.execute(
                    f"ALTER TABLE project_status_update_bindings "
                    f"ADD COLUMN {column} {decl}"
                )

        # 聚合同步（用户 2026-09-13）：绑定与运行捕获同步配置修订号，
        # 阻止在途旧运行跨换绑提交业务写入与快照（GPT 终审任务 2）。
        for revision_table in (
            "project_status_update_bindings",
            "project_status_sync_runs",
        ):
            revision_columns = {
                str(row["name"])
                for row in conn.execute(f"PRAGMA table_info({revision_table})")
            }
            if "sync_config_revision" not in revision_columns:
                conn.execute(
                    f"ALTER TABLE {revision_table} "
                    f"ADD COLUMN sync_config_revision INTEGER NOT NULL DEFAULT 0"
                )

        observation_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(project_status_mapping_observations)")
        }
        if "config_signature" not in observation_columns:
            conn.execute(
                "ALTER TABLE project_status_mapping_observations "
                "ADD COLUMN config_signature TEXT"
            )
        if "aggregated_candidate_json" not in observation_columns:
            conn.execute(
                "ALTER TABLE project_status_mapping_observations "
                "ADD COLUMN aggregated_candidate_json TEXT"
            )

        # 兼容性迁移：若存量历史 mapping_observations 的 config_signature 为空，
        # 但存在匹配当前绑定的合法证据，自动根据绑定 match_rule_json 计算回填，
        # 杜绝存量数据升级后调用 sync-now 时因签名缺失误判 409。
        has_null_sig = conn.execute(
            "SELECT 1 FROM project_status_mapping_observations "
            "WHERE (config_signature IS NULL OR config_signature = '') "
            "  AND result_state = 'matched' LIMIT 1"
        ).fetchone()
        if has_null_sig:
            bindings = conn.execute(
                "SELECT deliverable_id, source_type, match_rule_json "
                "FROM project_status_update_bindings "
                "WHERE enabled = 1"
            ).fetchall()
            for b in bindings:
                try:
                    rule = json.loads(b["match_rule_json"]) if b["match_rule_json"] else None
                    if isinstance(rule, dict):
                        from services.project_status_records import compute_config_signature
                        sig = compute_config_signature(b["source_type"], rule)
                        conn.execute(
                            "UPDATE project_status_mapping_observations "
                            "SET config_signature = ? "
                            "WHERE deliverable_id = ? "
                            "  AND source_type = ? "
                            "  AND (config_signature IS NULL OR config_signature = '') "
                            "  AND result_state = 'matched'",
                            (sig, b["deliverable_id"], b["source_type"])
                        )
                except Exception:
                    pass

        phase_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(project_status_phases)")
        }
        if "display_name" not in phase_columns:
            conn.execute(
                "ALTER TABLE project_status_phases "
                "ADD COLUMN display_name TEXT NOT NULL DEFAULT ''"
            )
        conn.execute(
            "UPDATE project_status_phases "
            "SET display_name = id || ' 主计划时间轴' "
            "WHERE trim(display_name) = ''"
        )

        deliverable_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(project_status_deliverables)")
        }
        deliverable_additions = [
            ("display_code", "TEXT"),
            ("department", "TEXT NOT NULL DEFAULT ''"),
            ("stage", "TEXT NOT NULL DEFAULT ''"),
            ("update_method", "TEXT NOT NULL DEFAULT 'manual'"),
        ]
        for column, decl in deliverable_additions:
            if column not in deliverable_columns:
                conn.execute(
                    f"ALTER TABLE project_status_deliverables ADD COLUMN {column} {decl}"
                )
        rows = conn.execute(
            "SELECT id FROM project_status_deliverables "
            "WHERE display_code IS NULL OR trim(display_code) = '' "
            "ORDER BY sort_order, id"
        ).fetchall()
        used_codes = {
            str(row["display_code"])
            for row in conn.execute(
                "SELECT display_code FROM project_status_deliverables "
                "WHERE display_code IS NOT NULL AND trim(display_code) <> ''"
            )
        }
        next_number = 1
        for row in rows:
            while f"DEL-{next_number:03d}" in used_codes:
                next_number += 1
            display_code = f"DEL-{next_number:03d}"
            conn.execute(
                "UPDATE project_status_deliverables SET display_code = ? WHERE id = ?",
                (display_code, row["id"]),
            )
            used_codes.add(display_code)
            next_number += 1
        # schema v14 后增补：外部快照驱动交付物（D6-D8）没有计划完成日期，
        # planned_date 由 NOT NULL 放宽为可空。SQLite 无法修改列约束，检测到
        # 旧库仍为 NOT NULL 时按模板整表重建并保留数据（必须在 display_code
        # 补齐之后执行，确保源表已含全部当前列且无 NULL 编码行）。
        deliverable_template_columns = {
            str(column["name"]): int(column["notnull"])
            for column in conn.execute("PRAGMA table_info(project_status_deliverables)")
        }
        if (
            deliverable_template_columns
            and deliverable_template_columns.get("planned_date") == 1
        ):
            # PRAGMA foreign_keys 在事务内是 no-op；先提交 display_code 补齐
            # 的 DML，确保关闭外键后 DROP 父表不会级联清空子表。
            conn.commit()
            conn.execute("PRAGMA foreign_keys=OFF")
            try:
                conn.execute("DROP TABLE IF EXISTS project_status_deliverables_rebuild")
                conn.execute(
                    _PROJECT_STATUS_DELIVERABLES_DDL.format(
                        table="project_status_deliverables_rebuild"
                    )
                )
                conn.execute(
                    "INSERT INTO project_status_deliverables_rebuild "
                    "(id, display_code, phase_id, name, status, owner, planned_date, "
                    "actual_date, progress, remark, source, department, stage, "
                    "update_method, sort_order, updated_at) "
                    "SELECT id, display_code, phase_id, name, status, owner, planned_date, "
                    "actual_date, progress, remark, source, department, stage, "
                    "update_method, sort_order, updated_at "
                    "FROM project_status_deliverables"
                )
                conn.execute("DROP TABLE project_status_deliverables")
                conn.execute(
                    "ALTER TABLE project_status_deliverables_rebuild "
                    "RENAME TO project_status_deliverables"
                )
                conn.commit()
            finally:
                conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_ps_deliverables_display_code "
            "ON project_status_deliverables(display_code)"
        )

        analysis_item_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(project_status_analysis_items)")
        }
        analysis_item_additions = [
            ("display_number", "TEXT NOT NULL DEFAULT ''"),
            ("pending_signers", "TEXT NOT NULL DEFAULT ''"),
            ("source_stage", "TEXT"),
            ("source_type", "TEXT NOT NULL DEFAULT ''"),
            ("source_department", "TEXT NOT NULL DEFAULT ''"),
            ("model_info", "TEXT NOT NULL DEFAULT ''"),
            ("extra_fields_json", "TEXT NOT NULL DEFAULT ''"),
        ]
        for column, decl in analysis_item_additions:
            if column not in analysis_item_columns:
                conn.execute(
                    f"ALTER TABLE project_status_analysis_items ADD COLUMN {column} {decl}"
                )

        conn.execute(
            "UPDATE project_status_milestones SET status = CASE "
            "WHEN status IN ('done', '已达成') OR type = 'done' THEN '已完成' "
            "WHEN status IN ('current', '当前目标节点') OR type = 'current' THEN '进行中' "
            "WHEN status IN ('planned', '计划节点') OR type = 'planned' THEN '未开始' "
            "ELSE status END"
        )

        archive_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(scheduled_archive_jobs)")
        }
        archive_additions = [
            ("output_directory", "TEXT NOT NULL DEFAULT ''"),
            ("display_name", "TEXT NOT NULL DEFAULT ''"),
            ("template_key", "TEXT NOT NULL DEFAULT ''"),
            ("builtin", "INTEGER NOT NULL DEFAULT 1"),
            ("archived_at", "TEXT"),
        ]
        for column, decl in archive_additions:
            if column not in archive_columns:
                conn.execute(
                    f"ALTER TABLE scheduled_archive_jobs ADD COLUMN {column} {decl}"
                )
        conn.execute(
            "UPDATE scheduled_archive_jobs SET template_key = job_key "
            "WHERE trim(template_key) = ''"
        )
        conn.execute(
            "UPDATE scheduled_archive_jobs SET display_name = CASE job_key "
            "WHEN 'aras_ewo' THEN 'EWO' WHEN 'aras_paa' THEN 'PAA' "
            "WHEN 'aras_ncr_progress' THEN 'NCR进度' "
            "WHEN 'aras_ncr_detail' THEN 'NCR明细' "
            "WHEN 'tdc_data_model' THEN '数模设计审核报表' "
            "WHEN 'tdc_sor' THEN 'TDC SOR' ELSE job_key END "
            "WHERE trim(display_name) = ''"
        )
        conn.execute(
            "UPDATE scheduled_archive_jobs "
            "SET display_name = '数模设计审核报表' "
            "WHERE job_key = 'tdc_data_model' AND builtin = 1 "
            "AND display_name = 'TDC数模'"
        )

        # crawl_tasks 增量表（保持 CURRENT_SCHEMA_VERSION = 14 严格不变）
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS crawl_tasks (
                task_id        TEXT PRIMARY KEY NOT NULL,
                task_type      TEXT NOT NULL,
                source         TEXT NOT NULL,
                status         TEXT NOT NULL DEFAULT 'queued'
                               CHECK (status IN ('queued', 'leased', 'running', 'succeeded', 'failed', 'cancelled', 'interrupted')),
                params_json    TEXT NOT NULL DEFAULT '{}',
                progress_json  TEXT NOT NULL DEFAULT '{}',
                artifact_path  TEXT,
                error_message  TEXT,
                created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crawl_tasks_status ON crawl_tasks(status, created_at);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crawl_tasks_source ON crawl_tasks(source, status);")
        # 插件各自的迁移版本（同样是增量表，不改 CURRENT_SCHEMA_VERSION）。
        conn.execute(PLUGIN_SCHEMA_VERSIONS_DDL)

        if existing_version < CURRENT_SCHEMA_VERSION:
            conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")

    @staticmethod
    def _seed_project_status(conn: sqlite3.Connection) -> None:
        """幂等写入 VPI-T2 仪表盘的初始本地快照。"""
        snapshot = "2026-08-13 09:42:00.000"
        conn.execute(
            """
            INSERT OR IGNORE INTO project_status_phases
                (id, display_name, status, start_date, end_date, simulated_today,
                 overall_progress, planned_progress, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "VPI-T2",
                # 主计划名称即后续交付物的车型锚点，初始默认 F610S，可在
                # 「主计划维护」中手动修改。
                "F610S",
                "进行中",
                "2026-04-08",
                "2026-08-30",
                "2026-08-13",
                64,
                80,
                snapshot,
            ),
        )

        # 主计划默认里程碑模板：每个项目阶段都预置同一模板（空日期=待排期）。
        milestone_template = PROJECT_STATUS_MILESTONE_TEMPLATE
        # 2026-09 之前的旧版 6 节点种子；仅当项目里程碑与它逐字段完全一致
        # （即用户从未编辑）时才替换为默认模板，任何差异都视为用户数据保留。
        legacy_seed_milestones = (
            ("项目启动", "2026-04-08", "已完成", "done", 1),
            ("策略冻结", "2026-05-12", "已完成", "done", 2),
            ("定点流程发布", "2026-06-18", "已完成", "done", 3),
            ("设计冻结", "2026-07-15", "已完成", "done", 4),
            ("VDR 决策", "2026-08-15", "进行中", "current", 5),
            ("VPI-T2 Gate", "2026-08-30", "未开始", "planned", 6),
        )
        phase_rows = conn.execute("SELECT id FROM project_status_phases").fetchall()
        for phase_row in phase_rows:
            phase_id = str(phase_row["id"])
            existing = conn.execute(
                """
                SELECT name, milestone_date, status, type, sort_order
                FROM project_status_milestones
                WHERE phase_id = ?
                ORDER BY sort_order, id
                """,
                (phase_id,),
            ).fetchall()
            if existing:
                current = tuple(
                    (
                        str(row["name"]),
                        None if row["milestone_date"] is None else str(row["milestone_date"]),
                        str(row["status"]),
                        str(row["type"]),
                        int(row["sort_order"]),
                    )
                    for row in existing
                )
                if current != legacy_seed_milestones:
                    continue
                conn.execute(
                    "DELETE FROM project_status_milestones WHERE phase_id = ?", (phase_id,)
                )
            conn.executemany(
                """
                INSERT OR IGNORE INTO project_status_milestones
                    (phase_id, name, milestone_date, status, type, sort_order)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [(phase_id, *item) for item in milestone_template],
            )
        # 契约内交付物（D2/D3/D5）默认自动同步：初始状态为待同步占位，
        # 首次同步成功前由展示层显示「待同步」；D1 保留手工演示值，
        # D4 手工模式（A 面契约未验证）同样以占位值起步。
        # D6-D8（外部快照驱动）无计划完成日期（planned_date NULL）与
        # 手工进度，初始展示状态由展示状态机输出「待同步」。
        deliverables = (
            ("VPI-T2-D1", "子系统开发策略", "已完成", "王晨", "2026-05-12", "2026-05-10", 100, "无", "内网"),
            ("VPI-T2-D2", "SOR 定点流程", "进行中", "周敏", "2026-06-18", None, 0, "待同步", "TDC SOR"),
            ("VPI-T2-D3", "EWO 流程", "进行中", "李珊", "2026-08-22", None, 0, "待同步", "ARAS EWO"),
            ("VPI-T2-D4", "造型 VDR 审批流程", "进行中", "陈璇", "2026-08-15", None, 0, "待同步", "TDC A 面（待契约确认）"),
            ("VPI-T2-D5", "数模设计审核流程报表", "进行中", "赵岩", "2026-08-08", None, 0, "待同步", "TDC 数模设计审核流程报表"),
            ("VPI-T2-D6", "PAA 报告", "进行中", "", None, None, 0, "", "ARAS PAA"),
            ("VPI-T2-D7", "NCR 审批进度", "进行中", "", None, None, 0, "", "ARAS NCR"),
            ("VPI-T2-D8", "NCR 审批明细", "进行中", "", None, None, 0, "", "ARAS NCR"),
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO project_status_deliverables
                (id, display_code, phase_id, name, status, owner, planned_date, actual_date,
                 progress, remark, source, sort_order, updated_at)
            VALUES (?, ?, 'VPI-T2', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (item[0], f"DEL-{index:03d}", *item[1:], index, snapshot)
                for index, item in enumerate(deliverables[:5], start=1)
            ],
        )
        # 存量库 display_code 补齐（D6-D8）：自定义交付物可能已占用
        # DEL-006/007/008，固定编码种子行会被 INSERT OR IGNORE 静默跳过；
        # 此时优先使用合同编码、被占用时取下一个可用编码，保证 D6-D8
        # 交付物行与后续绑定/字段权威种子始终存在。
        _deliverable_insert_sql = """
            INSERT OR IGNORE INTO project_status_deliverables
                (id, display_code, phase_id, name, status, owner, planned_date, actual_date,
                 progress, remark, source, sort_order, updated_at)
            VALUES (?, ?, 'VPI-T2', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        for index, item in enumerate(deliverables[5:], start=6):
            exists = conn.execute(
                "SELECT 1 FROM project_status_deliverables WHERE id = ?", (item[0],)
            ).fetchone()
            if exists is not None:
                continue
            used_codes = {
                str(row["display_code"])
                for row in conn.execute(
                    "SELECT display_code FROM project_status_deliverables "
                    "WHERE display_code IS NOT NULL"
                )
            }
            preferred_code = f"DEL-{index:03d}"
            if preferred_code not in used_codes:
                display_code = preferred_code
            else:
                number = 1
                while f"DEL-{number:03d}" in used_codes:
                    number += 1
                display_code = f"DEL-{number:03d}"
            conn.execute(
                _deliverable_insert_sql,
                (item[0], display_code, *item[1:], index, snapshot),
            )
        conn.execute(
            """
            UPDATE project_status_deliverables
            SET name = '数模设计审核流程报表',
                source = 'TDC 数模设计审核流程报表'
            WHERE id = 'VPI-T2-D5'
              AND name = '数模审批流程'
              AND source = 'TDC 数模'
            """
        )
        # 存量库改名迁移：EWO 定点流程 → EWO 流程（种子 INSERT OR IGNORE 不会更新旧行）。
        conn.execute(
            """
            UPDATE project_status_deliverables
            SET name = 'EWO 流程'
            WHERE id = 'VPI-T2-D3'
              AND name = 'EWO 定点流程'
            """
        )
        # 存量库锚点迁移：主计划名称默认改为车型 F610S（旧默认是「VPI-T2 主计划时间轴」）。
        conn.execute(
            """
            UPDATE project_status_phases
            SET display_name = 'F610S'
            WHERE id = 'VPI-T2'
              AND display_name = 'VPI-T2 主计划时间轴'
            """
        )
        for item_id in (item[0] for item in deliverables):
            DatabaseManager._ensure_project_status_policy(conn, str(item_id))
        conn.execute(
            """
            UPDATE project_status_update_bindings
            SET source_type = CASE deliverable_id
                WHEN 'VPI-T2-D2' THEN 'tdc'
                WHEN 'VPI-T2-D3' THEN 'aras'
                WHEN 'VPI-T2-D4' THEN 'tdc'
                WHEN 'VPI-T2-D5' THEN 'tdc'
                ELSE 'none' END
            WHERE deliverable_id IN ('VPI-T2-D1','VPI-T2-D2','VPI-T2-D3','VPI-T2-D4','VPI-T2-D5')
              AND mode = 'manual' AND enabled = 0
              AND external_key IS NULL AND match_rule_json = '{}' AND mapping_json = '{}'
              AND last_attempt_at IS NULL AND last_success_at IS NULL
            """
        )
        conn.execute(
            """
            UPDATE project_status_field_authority
            SET source_type = CASE deliverable_id
                WHEN 'VPI-T2-D2' THEN 'tdc'
                WHEN 'VPI-T2-D3' THEN 'aras'
                WHEN 'VPI-T2-D4' THEN 'tdc'
                WHEN 'VPI-T2-D5' THEN 'tdc'
                ELSE 'none' END
            WHERE deliverable_id IN ('VPI-T2-D1','VPI-T2-D2','VPI-T2-D3','VPI-T2-D4','VPI-T2-D5')
              AND authority = 'manual' AND locked_at IS NULL
            """
        )
        # 存量库幂等迁移（B）：老库中 syncCapable 交付物的绑定曾是 manual
        # 种子（新库种子本就 automatic，此 UPDATE 对其 no-op）。仅翻转
        # "从未动过"的 pristine manual 绑定——任一字段被用户改过（external
        # key、匹配规则、映射、尝试/成功时间戳、enabled、mode）都保持原样。
        # enabled 保持 0，不绕过证据/凭据门控；D1（ManualOnly）与 D4
        # （ContractBlocked）不在 syncCapable 集合内，天然不受影响。
        sync_capable_ids = tuple(
            deliverable_id
            for deliverable_id, capabilities in PROJECT_STATUS_SOURCE_CAPABILITIES.items()
            if capabilities.get("syncCapable")
        )
        if sync_capable_ids:
            placeholders = ", ".join("?" for _ in sync_capable_ids)
            conn.execute(
                f"""
                UPDATE project_status_update_bindings
                SET mode = 'automatic'
                WHERE deliverable_id IN ({placeholders})
                  AND mode = 'manual' AND enabled = 0
                  AND external_key IS NULL AND match_rule_json = '{{}}' AND mapping_json = '{{}}'
                  AND last_attempt_at IS NULL AND last_success_at IS NULL
                """,
                sync_capable_ids,
            )

    @staticmethod
    def _seed_archive_jobs(conn: sqlite3.Connection) -> None:
        """Seed only fixed, contract-backed archive jobs; never seed TDC A-face."""
        jobs = tuple(
            (job_key, source_type, report_type, deliverable_id)
            for job_key, (source_type, report_type, deliverable_id)
            in ARCHIVE_JOB_CONTRACTS.items()
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO scheduled_archive_jobs
                (job_key, source_type, report_type,
                 project_status_deliverable_id, enabled, interval_minutes,
                 retry_policy_json, sync_state, display_name, template_key, builtin)
            VALUES (?, ?, ?, ?, 0, 60,
                    '{"max_attempts":2,"backoff_seconds":1}', 'idle',
                    CASE ?
                        WHEN 'aras_ewo' THEN 'EWO' WHEN 'aras_paa' THEN 'PAA'
                        WHEN 'aras_ncr_progress' THEN 'NCR进度'
                        WHEN 'aras_ncr_detail' THEN 'NCR明细'
                        WHEN 'tdc_data_model' THEN '数模设计审核报表'
                        WHEN 'tdc_sor' THEN 'TDC SOR' ELSE ? END,
                    ?, 1)
            """,
            [(*job, job[0], job[0], job[0]) for job in jobs],
        )
        # 内置 EWO/PAA 任务的默认业务部门必须作为实际生效筛选条件存在
        # （用户 2026-09-02 确认口径），不能只是输入框占位提示。EWO 的
        # 连接器字段名是 responsibleDepartment，PAA 的字段名才是 department。
        # 仅填充仍为种子空值 '{}' 的任务；用户显式设置的其他筛选不受影响。
        # 兼容阶段 B 早期版本曾误写的 EWO 默认值，避免已有本地库继续把
        # 不被 EWO 连接器接受的 department 键传入运行时。
        conn.execute(
            """
            UPDATE scheduled_archive_jobs
            SET filters_json = CASE job_key
                WHEN 'aras_ewo' THEN '{"responsibleDepartment": "技术中心_车体工程"}'
                WHEN 'aras_paa' THEN '{"department": "技术中心_车体工程"}'
            END
            WHERE job_key IN ('aras_ewo', 'aras_paa')
              AND builtin = 1
              AND (
                    filters_json IS NULL
                    OR filters_json IN ('', '{}')
                    OR (
                        job_key = 'aras_ewo'
                        AND filters_json IN (
                            '{"department": "技术中心_车体工程"}',
                            '{"department":"技术中心_车体工程"}'
                        )
                    )
              )
            """
        )

    def get_app_settings(self) -> dict[str, object]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT setting_key, value_json FROM app_settings").fetchall()
        result: dict[str, object] = {}
        for row in rows:
            value = _json_loads_or_none(row["value_json"])
            if value is not None:
                result[str(row["setting_key"])] = value
        return result

    def update_app_settings(self, values: Mapping[str, object]) -> dict[str, object]:
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany(
                """
                INSERT INTO app_settings(setting_key, value_json, updated_at)
                VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                ON CONFLICT(setting_key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                [(str(key), _json_dumps_local(value)) for key, value in values.items()],
            )
        return self.get_app_settings()

    # ── 调度运行与租约数据访问 ─────────────────────────────────────
    #
    # 所有租约、运行状态、游标和审计写入均在单一数据库事务内完成。
    # 时间统一使用数据库生成的 UTC 时间戳，不使用 simulated_today。

    def save_feishu_tasks(self, tasks: Sequence[Mapping[str, Any]]) -> int:
        if not tasks:
            return 0
        saved_count = 0
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for task in tasks:
                existing = conn.execute(
                    "SELECT id FROM feishu_tasks WHERE source_email_id = ?",
                    (task["source_email_id"],),
                ).fetchone()
                if existing:
                    continue
                conn.execute(
                    """
                    INSERT INTO feishu_tasks (title, assignee, deadline, source_email_id)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        task["title"],
                        task["assignee"],
                        task["deadline"],
                        task["source_email_id"],
                    ),
                )
                saved_count += 1
        return saved_count

    def sync_unsynced_feishu_tasks_to_deliverables(self, project_id: int = 1) -> int:
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT id, title, assignee, deadline, source_email_id
                FROM feishu_tasks
                WHERE synced = 0
                ORDER BY id
                """
            ).fetchall()
            synced_ids: list[int] = []
            for row in rows:
                task_id = int(row["id"])
                source_email_id = row["source_email_id"] or str(task_id)
                conn.execute(
                    """
                    INSERT INTO deliverables
                        (project_id, name, owner, due_date, status, remark)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        row["title"] or "未命名飞书待办",
                        row["assignee"] or "",
                        row["deadline"] or None,
                        "pending",
                        f"飞书待办同步: {source_email_id}",
                    ),
                )
                synced_ids.append(task_id)
            for task_id in synced_ids:
                conn.execute(
                    "UPDATE feishu_tasks SET synced = 1 WHERE id = ?",
                    (task_id,),
                )
            return len(synced_ids)

    def persist_scraped_deliverables(self, items: Sequence[Mapping[str, Any]]) -> int:
        if not items:
            return 0
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            project_map: dict[str, int] = {}
            for item in items:
                proj_name = item.get("project_id", "Unknown_Project")
                if proj_name not in project_map:
                    cursor = conn.execute("SELECT id FROM projects WHERE name = ?", (proj_name,))
                    res = cursor.fetchone()
                    if res:
                        project_map[proj_name] = res[0]
                    else:
                        cursor = conn.execute("INSERT INTO projects (name, manager) VALUES (?, ?)", (proj_name, "Crawler"))
                        project_map[proj_name] = cursor.lastrowid
                conn.execute(
                    """
                    INSERT INTO deliverables (project_id, name, owner, status)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        project_map[proj_name],
                        item.get("name", "未命名"),
                        item.get("owner", ""),
                        item.get("status", "pending"),
                    ),
                )
        return len(items)

    def get_deliverables_for_export(self) -> list[sqlite3.Row]:
        with self.get_connection() as conn:
            return conn.execute(
                """
                SELECT
                    p.name    AS project_name,
                    p.manager AS project_manager,
                    d.name    AS deliverable_name,
                    d.owner,
                    d.due_date,
                    d.status,
                    d.remark,
                    d.updated_at
                FROM deliverables d
                JOIN projects p ON d.project_id = p.id
                ORDER BY d.due_date ASC
                """
            ).fetchall()

    def get_feishu_tasks_summary(self) -> list[sqlite3.Row]:
        with self.get_connection() as conn:
            return conn.execute(
                """
                SELECT title, assignee, deadline, synced
                FROM feishu_tasks
                ORDER BY deadline ASC
                """
            ).fetchall()

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        获取数据库连接的上下文管理器。

        自动处理:
            - 设置 row_factory = sqlite3.Row (支持字典式访问)
            - 启用外键约束
            - 正常退出时 commit，异常时 rollback
            - 无论何种情况都确保连接关闭

        Yields:
            sqlite3.Connection: 已配置好的数据库连接

        Raises:
            sqlite3.Error: 数据库操作异常
        """
        with operation("db.transaction"):
            conn: sqlite3.Connection | None = None
            try:
                conn = sqlite3.connect(
                    str(self._db_path),
                    timeout=10,  # 等待锁的超时时间（秒）
                )
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys=ON;")

                yield conn

                conn.commit()

            except sqlite3.Error:
                if conn:
                    try:
                        conn.rollback()
                    except sqlite3.Error:
                        pass
                logger.exception("数据库事务异常回滚 (sqlite3.Error)")
                raise
            except BaseException as exc:
                if conn:
                    try:
                        conn.rollback()
                    except sqlite3.Error:
                        pass
                logger.info("数据库事务因应用程序异常回滚: %s: %s", type(exc).__name__, exc)
                raise

            finally:
                if conn:
                    conn.close()

    def execute_script(self, script: str) -> None:
        """
        执行多条 SQL 语句（用于迁移脚本）。

        Args:
            script: 包含多条 SQL 语句的字符串，以分号分隔

        Raises:
            sqlite3.Error: SQL 执行异常
        """
        try:
            with self.get_connection() as conn:
                conn.executescript(script)
            logger.info("SQL 脚本执行成功")
        except sqlite3.Error:
            logger.exception("SQL 脚本执行失败")
            raise

    def table_exists(self, table_name: str) -> bool:
        """
        检查指定表是否存在。

        Args:
            table_name: 表名

        Returns:
            True 如果表存在，否则 False
        """
        try:
            with self.get_connection() as conn:
                result = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table_name,),
                ).fetchone()
                return result is not None
        except sqlite3.Error as e:
            logger.error("检查表 %s 是否存在时出错: %s", table_name, e)
            return False

    def get_table_row_count(self, table_name: str) -> int:
        """
        获取指定表的行数。

        Args:
            table_name: 表名

        Returns:
            表中的行数，表不存在时返回 -1
        """
        if not table_name.isascii() or not table_name.isidentifier():
            return -1
        if not self.table_exists(table_name):
            return -1
        try:
            with self.get_connection() as conn:
                # SQLite 不支持参数化表名，用 table_exists 预验证后拼接
                # table_name 已经过 table_exists 白名单验证，无 SQL 注入风险
                result = conn.execute(  # nosec: table_name validated by table_exists
                    f"SELECT COUNT(*) FROM {table_name}"
                ).fetchone()
                return result[0] if result else 0
        except sqlite3.Error as e:
            logger.error("获取表 %s 行数时出错: %s", table_name, e)
            return -1

    # ── crawl_tasks 任务持久化与调度支持 ────────────────────────────────
