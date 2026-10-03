# -*- coding: utf-8 -*-
"""项目状态（主计划、交付物、分析缓存、手工更新策略与审计、里程碑）的数据访问（DatabaseManager 的领域分片）。

由 core/db_manager.py 按领域拆出；``DatabaseManager`` 继承本类，对外接口不变。
本类依赖 ``get_connection`` 等由 DatabaseManager 提供的方法，不单独实例化。
"""

from core.db_common import (  # noqa: F401
    _dump_extra_fields,
    _LOCAL_NOW_SQL,
    Any,
    json,
    MappedDeliverableReadOnlyError,
    Mapping,
    observed,
    PROJECT_STATUS_EDITABLE_FIELDS,
    project_status_manual_editability,
    PROJECT_STATUS_SOURCE_CAPABILITIES,
    ProjectStatusConcurrentUpdateError,
    Sequence,
    sqlite3,
)


class ProjectStatusRepo:
    def get_project_status(self, phase_id: str) -> tuple[sqlite3.Row | None, list[sqlite3.Row], list[sqlite3.Row]]:
        """读取一个阶段及其里程碑、交付物的同一份已保存快照。"""
        with self.get_connection() as conn:
            phase = conn.execute(
                "SELECT * FROM project_status_phases WHERE id = ?",
                (phase_id,),
            ).fetchone()
            if phase is None:
                return None, [], []
            milestones = conn.execute(
                "SELECT * FROM project_status_milestones WHERE phase_id = ? ORDER BY sort_order, id",
                (phase_id,),
            ).fetchall()
            deliverables = conn.execute(
                "SELECT * FROM project_status_deliverables WHERE phase_id = ? ORDER BY sort_order, id",
                (phase_id,),
            ).fetchall()
            return phase, milestones, deliverables

    def create_project_status_deliverable(
        self,
        phase_id: str,
        values: Mapping[str, object],
    ) -> dict[str, Any]:
        """Create a deliverable while preserving the internal ID/display-code split."""
        required = {"id", "name", "status", "owner", "planned_date", "progress", "source"}
        missing = required - set(values)
        if missing:
            raise ValueError(f"missing deliverable fields: {sorted(missing)}")
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            phase = conn.execute(
                "SELECT 1 FROM project_status_phases WHERE id = ?", (phase_id,)
            ).fetchone()
            if phase is None:
                raise KeyError(phase_id)
            existing_codes = {
                str(row["display_code"])
                for row in conn.execute(
                    "SELECT display_code FROM project_status_deliverables WHERE display_code IS NOT NULL"
                )
            }
            number = 1
            while f"DEL-{number:03d}" in existing_codes:
                number += 1
            display_code = f"DEL-{number:03d}"
            sort_order = int(
                conn.execute(
                    "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM project_status_deliverables WHERE phase_id = ?",
                    (phase_id,),
                ).fetchone()[0]
            )
            now = conn.execute(f"SELECT {_LOCAL_NOW_SQL}").fetchone()[0]
            conn.execute(
                """
                INSERT INTO project_status_deliverables (
                    id, display_code, phase_id, name, status, owner, planned_date,
                    actual_date, progress, remark, source, department, stage,
                    update_method, sort_order, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(values["id"]), display_code, phase_id, str(values["name"]),
                    str(values["status"]), str(values["owner"]), str(values["planned_date"]),
                    values.get("actual_date"), int(str(values["progress"])),
                    str(values.get("remark") or ""), str(values["source"]),
                    str(values.get("department") or ""), str(values.get("stage") or ""),
                    str(values.get("update_method") or "manual"), sort_order, str(now),
                ),
            )
            self._ensure_project_status_policy(conn, str(values["id"]))
            row = conn.execute(
                "SELECT * FROM project_status_deliverables WHERE id = ?", (str(values["id"]),)
            ).fetchone()
            assert row is not None
            return dict(row)

    def update_project_status_phase(
        self,
        phase_id: str,
        values: Mapping[str, object],
        expected_updated_at: str,
    ) -> str:
        """Update editable phase metadata using the phase timestamp as an optimistic lock."""
        columns = {
            "display_name": "display_name",
            "status": "status",
            "start_date": "start_date",
            "end_date": "end_date",
        }
        unknown = set(values) - set(columns)
        if unknown:
            raise ValueError(f"unknown project phase field: {sorted(unknown)}")
        if not values:
            return expected_updated_at
        assignments = [f"{columns[key]} = ?" for key in values]
        with self.get_connection() as conn:
            existing = conn.execute(
                "SELECT updated_at FROM project_status_phases WHERE id = ?",
                (phase_id,),
            ).fetchone()
            if existing is None:
                raise KeyError(phase_id)
            cursor = conn.execute(
                f"UPDATE project_status_phases SET {', '.join(assignments)}, "
                f"updated_at = {_LOCAL_NOW_SQL} "
                "WHERE id = ? AND updated_at = ?",
                (*[values[key] for key in values], phase_id, expected_updated_at),
            )
            if cursor.rowcount != 1:
                raise ProjectStatusConcurrentUpdateError("project status phase has changed")
            row = conn.execute(
                "SELECT updated_at FROM project_status_phases WHERE id = ?",
                (phase_id,),
            ).fetchone()
            assert row is not None
            return str(row["updated_at"])

    @observed("db.replace_project_status_analysis_cache")
    def replace_project_status_analysis_cache(
        self,
        deliverable_id: str,
        source_run_id: int,
        snapshot: Mapping[str, object],
        items: Sequence[Mapping[str, object]],
        *,
        retention_snapshots: int = 30,
        expected_sync_config_revision: int | None = None,
    ) -> bool:
        """Atomically publish one aggregate snapshot and replace the latest normalized items.

        expected_sync_config_revision 提供时（同步运行发布路径），在其写入事务内
        校验绑定修订号；不一致（换绑）拒绝发布旧运行的分析快照并返回 False。
        """
        bounded_retention = max(2, min(int(retention_snapshots), 365))
        department_counts_json = json.dumps(
            snapshot.get("department_counts", {}),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.get_connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM project_status_deliverables WHERE id = ?",
                (deliverable_id,),
            ).fetchone()
            if exists is None:
                raise KeyError(deliverable_id)
            conn.execute("BEGIN IMMEDIATE")
            if expected_sync_config_revision is not None:
                # 换绑校验（GPT 终审任务 2d）：apply 后、发布前发生换绑 →
                # 拒绝发布旧运行的分析快照。
                binding_row = conn.execute(
                    "SELECT sync_config_revision FROM project_status_update_bindings "
                    "WHERE deliverable_id = ?",
                    (deliverable_id,),
                ).fetchone()
                if int(binding_row["sync_config_revision"] or 0) != int(
                    expected_sync_config_revision
                ):
                    return False
            conn.execute(
                """
                INSERT INTO project_status_analysis_snapshots (
                    deliverable_id, source_run_id, total_count, completed_count,
                    incomplete_count, overdue_count, due_soon_count,
                    missing_due_date_count, department_counts_json, snapshot_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(deliverable_id, source_run_id) DO UPDATE SET
                    total_count = excluded.total_count,
                    completed_count = excluded.completed_count,
                    incomplete_count = excluded.incomplete_count,
                    overdue_count = excluded.overdue_count,
                    due_soon_count = excluded.due_soon_count,
                    missing_due_date_count = excluded.missing_due_date_count,
                    department_counts_json = excluded.department_counts_json,
                    snapshot_at = excluded.snapshot_at
                """,
                (
                    deliverable_id,
                    source_run_id,
                    int(str(snapshot["total_count"])),
                    int(str(snapshot["completed_count"])),
                    int(str(snapshot["incomplete_count"])),
                    int(str(snapshot["overdue_count"])),
                    int(str(snapshot["due_soon_count"])),
                    int(str(snapshot["missing_due_date_count"])),
                    department_counts_json,
                    str(snapshot["snapshot_at"]),
                ),
            )
            conn.execute(
                "DELETE FROM project_status_analysis_items WHERE deliverable_id = ?",
                (deliverable_id,),
            )
            conn.executemany(
                """
                INSERT INTO project_status_analysis_items (
                    deliverable_id, item_key, display_number, title, department, owner,
                    pending_signers, source_department, model_info, extra_fields_json,
                    source_status, source_stage, source_type,
                    is_completed, planned_date, actual_date, source_run_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        deliverable_id,
                        str(item["item_key"]),
                        str(item.get("display_number") or ""),
                        str(item["title"]),
                        str(item["department"]),
                        str(item["owner"]),
                        str(item.get("pending_signers") or ""),
                        str(item.get("source_department") or ""),
                        str(item.get("model_info") or ""),
                        _dump_extra_fields(item.get("extra_fields")),
                        str(item["source_status"]),
                        item.get("source_stage"),
                        str(item.get("source_type") or ""),
                        1 if bool(item["is_completed"]) else 0,
                        item.get("planned_date"),
                        item.get("actual_date"),
                        source_run_id,
                        str(snapshot["snapshot_at"]),
                    )
                    for item in items
                ],
            )
            conn.execute(
                """
                DELETE FROM project_status_analysis_snapshots
                WHERE deliverable_id = ? AND id NOT IN (
                    SELECT id FROM project_status_analysis_snapshots
                    WHERE deliverable_id = ?
                    ORDER BY snapshot_at DESC, id DESC LIMIT ?
                )
                """,
                (deliverable_id, deliverable_id, bounded_retention),
            )
            return True

    def list_project_status_analysis_snapshots(
        self,
        deliverable_id: str,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 100))
        with self.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, deliverable_id, source_run_id, total_count,
                       completed_count, incomplete_count, overdue_count,
                       due_soon_count, missing_due_date_count,
                       department_counts_json, snapshot_at, created_at
                FROM project_status_analysis_snapshots
                WHERE deliverable_id = ?
                ORDER BY snapshot_at DESC, id DESC LIMIT ?
                """,
                (deliverable_id, bounded),
            ).fetchall()
            return [dict(row) for row in rows]

    def clear_project_status_analysis_cache(self, deliverable_id: str) -> None:
        """换绑/改匹配规则后清空该交付物的分析快照与明细缓存。"""
        with self.get_connection() as conn:
            conn.execute(
                "DELETE FROM project_status_analysis_snapshots WHERE deliverable_id = ?",
                (deliverable_id,),
            )
            conn.execute(
                "DELETE FROM project_status_analysis_items WHERE deliverable_id = ?",
                (deliverable_id,),
            )

    def list_project_status_analysis_items(
        self,
        deliverable_id: str,
        *,
        department: str | None = None,
        departments: Sequence[str] | None = None,
        completed: bool | None = None,
        stage: str | None = None,
        stages: Sequence[str] | None = None,
        offset: int = 0,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 1000))
        bounded_offset = max(0, int(offset))
        sql = """
            SELECT deliverable_id, item_key, title, department, owner,
                   display_number, pending_signers, source_department, model_info,
                   extra_fields_json, source_status, source_stage, source_type,
                   is_completed, planned_date, actual_date, source_run_id, updated_at
            FROM project_status_analysis_items
            WHERE deliverable_id = ?
        """
        params: list[object] = [deliverable_id]
        department_values = tuple(departments) if departments is not None else ((department,) if department else ())
        if department_values:
            placeholders = ", ".join("?" for _ in department_values)
            sql += f" AND department IN ({placeholders})"
            params.extend(department_values)
        if stages is not None and tuple(stages) == ("all",):
            stage_values: tuple[str, ...] = ()
        elif stages is not None:
            stage_values = tuple(stages)
        else:
            stage_values = ()
        if stage_values:
            placeholders = ", ".join("?" for _ in stage_values)
            sql += f" AND source_stage IN ({placeholders})"
            params.extend(stage_values)
        elif stages is None and stage not in (None, "", "all"):
            sql += " AND source_stage = ?"
            params.append(stage)
        elif stages is None and stage == "all":
            pass
        elif stages is None and stage in (None, ""):
            # 默认明细对 EWO 只展示活动阶段与 close；非 EWO 缓存的
            # source_type 为空，因此保留原有通用分析行为。
            sql += (
                " AND (source_type NOT IN ('aras', 'ewo', 'aras_ewo', 'aras/ewo') "
                "OR source_stage IN ('draft1', 'draft2', 'edit1', 'edit2', 'proc', 'impl', 'close'))"
            )
        if completed is not None:
            sql += " AND is_completed = ?"
            params.append(int(completed))
        sql += " ORDER BY is_completed ASC, planned_date ASC, title ASC LIMIT ? OFFSET ?"
        params.extend([bounded_limit, bounded_offset])
        with self.get_connection() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [dict(row) for row in rows]

    def count_project_status_analysis_items(
        self,
        deliverable_id: str,
        *,
        department: str | None = None,
        departments: Sequence[str] | None = None,
        completed: bool | None = None,
        stage: str | None = None,
        stages: Sequence[str] | None = None,
    ) -> int:
        sql = """
            SELECT COUNT(*) AS total
            FROM project_status_analysis_items
            WHERE deliverable_id = ?
        """
        params: list[object] = [deliverable_id]
        department_values = tuple(departments) if departments is not None else ((department,) if department else ())
        if department_values:
            placeholders = ", ".join("?" for _ in department_values)
            sql += f" AND department IN ({placeholders})"
            params.extend(department_values)
        if stages is not None and tuple(stages) == ("all",):
            stage_values: tuple[str, ...] = ()
        elif stages is not None:
            stage_values = tuple(stages)
        else:
            stage_values = ()
        if stage_values:
            placeholders = ", ".join("?" for _ in stage_values)
            sql += f" AND source_stage IN ({placeholders})"
            params.extend(stage_values)
        elif stages is None and stage not in (None, "", "all"):
            sql += " AND source_stage = ?"
            params.append(stage)
        elif stages is None and stage == "all":
            pass
        elif stages is None and stage in (None, ""):
            # 默认明细对 EWO 只展示活动阶段与 close；非 EWO 缓存的
            # source_type 为空，因此保留原有通用分析行为。
            sql += (
                " AND (source_type NOT IN ('aras', 'ewo', 'aras_ewo', 'aras/ewo') "
                "OR source_stage IN ('draft1', 'draft2', 'edit1', 'edit2', 'proc', 'impl', 'close'))"
            )
        if completed is not None:
            sql += " AND is_completed = ?"
            params.append(int(completed))
        with self.get_connection() as conn:
            row = conn.execute(sql, tuple(params)).fetchone()
            return int(row["total"]) if row is not None else 0

    def list_project_status_analysis_source_types(
        self,
        deliverable_id: str,
    ) -> tuple[str, ...]:
        """Return the explicit source types represented in the latest cache."""
        with self.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT source_type
                FROM project_status_analysis_items
                WHERE deliverable_id = ? AND trim(source_type) <> ''
                ORDER BY source_type
                """,
                (deliverable_id,),
            ).fetchall()
            return tuple(str(row["source_type"]) for row in rows)

    def update_project_status_deliverable(
        self,
        deliverable_id: str,
        phase_id: str,
        values: dict[str, object],
        expected_updated_at: str,
    ) -> str:
        """以更新时间作乐观锁更新交付物，返回新更新时间。"""
        with self.get_connection() as conn:
            # Serialize the binding check with policy writes.  A reader that
            # checked editability before entering this method could otherwise
            # race a mapping configuration change.
            conn.execute("BEGIN IMMEDIATE")
            self._assert_project_status_manual_editable(conn, deliverable_id)
            updated_at = self._update_project_status_deliverable_row(
                conn,
                deliverable_id,
                phase_id,
                values,
                expected_updated_at,
            )
            conn.execute(
                "UPDATE project_status_phases SET updated_at = ? WHERE id = ?",
                (updated_at, phase_id),
            )
            return updated_at

    @staticmethod
    def _assert_project_status_manual_editable(
        conn: sqlite3.Connection,
        deliverable_id: str,
    ) -> None:
        """Recheck the current binding before any manual write.

        A missing binding is the unconfigured default and remains editable;
        ``_ensure_project_status_policy`` is called only after this guard in
        the audited write path.  This ordering guarantees a mapped denial
        cannot insert authority rows or an audit record as a side effect.
        """
        binding = conn.execute(
            """
            SELECT external_key, match_rule_json, mapping_json
            FROM project_status_update_bindings
            WHERE deliverable_id = ?
            """,
            (deliverable_id,),
        ).fetchone()
        if binding is None:
            return
        binding_values = dict(binding)
        binding_values["deliverable_id"] = deliverable_id
        editability = project_status_manual_editability(binding_values)
        if editability["manualEditable"] is not True:
            reason = str(editability.get("readOnlyReason") or "交付物已配置外部映射")
            raise MappedDeliverableReadOnlyError(reason)

    @staticmethod
    def _update_project_status_deliverable_row(
        conn: sqlite3.Connection,
        deliverable_id: str,
        phase_id: str,
        values: dict[str, object],
        expected_updated_at: str,
    ) -> str:
        """乐观锁更新交付物行；事务由调用方负责。"""
        columns = {
            "status": "status",
            "owner": "owner",
            "planned_date": "planned_date",
            "actual_date": "actual_date",
            "progress": "progress",
            "remark": "remark",
        }
        unknown = set(values) - set(columns)
        if unknown:
            raise ValueError(f"unknown project status field: {sorted(unknown)}")
        assignments = [f"{columns[key]} = ?" for key in values]
        if not assignments:
            return expected_updated_at
        next_updated_at_sql = "strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime')"
        exists = conn.execute(
            "SELECT updated_at FROM project_status_deliverables WHERE id = ? AND phase_id = ?",
            (deliverable_id, phase_id),
        ).fetchone()
        if exists is None:
            raise KeyError(deliverable_id)
        cursor = conn.execute(
            f"UPDATE project_status_deliverables SET {', '.join(assignments)}, "
            f"updated_at = {next_updated_at_sql} "
            "WHERE id = ? AND phase_id = ? AND updated_at = ?",
            (*[values[key] for key in values], deliverable_id, phase_id, expected_updated_at),
        )
        if cursor.rowcount != 1:
            raise ProjectStatusConcurrentUpdateError("project status record has changed")
        row = conn.execute(
            "SELECT updated_at FROM project_status_deliverables WHERE id = ?",
            (deliverable_id,),
        ).fetchone()
        assert row is not None
        return str(row["updated_at"])

    @staticmethod
    def _ensure_project_status_policy(conn: sqlite3.Connection, deliverable_id: str) -> None:
        """Idempotently seed the confirmed authoritative source assignment.

        契约内交付物（syncCapable）新库默认 automatic（enabled=0，待配置）；
        其余交付物保持 manual。存量库由 INSERT OR IGNORE 保护，不受影响。
        """
        capabilities = PROJECT_STATUS_SOURCE_CAPABILITIES.get(deliverable_id, {})
        source_type = str(capabilities.get("sourceType") or "none")
        mode = "automatic" if capabilities.get("syncCapable") else "manual"
        conn.execute(
            """
            INSERT OR IGNORE INTO project_status_update_bindings
                (deliverable_id, mode, source_type, enabled, sync_state)
            VALUES (?, ?, ?, 0, 'idle')
            """,
            (deliverable_id, mode, source_type),
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO project_status_field_authority
                (deliverable_id, field_name, authority, source_type)
            VALUES (?, ?, 'manual', ?)
            """,
            [
                (deliverable_id, field_name, source_type)
                for field_name in PROJECT_STATUS_EDITABLE_FIELDS
            ],
        )

    @staticmethod
    def _prune_project_status_audit(
        conn: sqlite3.Connection,
        deliverable_id: str,
        limit: int = 100,
    ) -> None:
        """每个交付物只保留最近 limit 条审计记录。"""
        conn.execute(
            """
            DELETE FROM project_status_update_audit
            WHERE deliverable_id = ?
              AND id NOT IN (
                  SELECT id FROM project_status_update_audit
                  WHERE deliverable_id = ?
                  ORDER BY id DESC LIMIT ?
              )
            """,
            (deliverable_id, deliverable_id, limit),
        )

    def apply_project_status_manual_update(
        self,
        deliverable_id: str,
        phase_id: str,
        values: dict[str, object],
        expected_updated_at: str,
        changed_fields: Sequence[str],
        proposed_changes_json: str,
        applied_changes_json: str,
        source_type: str = "tdc",
    ) -> str:
        """原子执行手动保存：乐观锁更新、人工字段锁和审计落库。"""
        invalid = set(changed_fields) - set(PROJECT_STATUS_EDITABLE_FIELDS)
        if invalid:
            raise ValueError(f"unknown project status field: {sorted(invalid)}")
        with self.get_connection() as conn:
            # BEGIN IMMEDIATE makes the binding decision and the subsequent
            # row/authority/audit changes one serialized transaction.
            conn.execute("BEGIN IMMEDIATE")
            exists = conn.execute(
                "SELECT id FROM project_status_deliverables WHERE id = ?",
                (deliverable_id,),
            ).fetchone()
            if exists is None:
                raise KeyError(deliverable_id)
            self._assert_project_status_manual_editable(conn, deliverable_id)
            self._ensure_project_status_policy(conn, deliverable_id)
            updated_at = self._update_project_status_deliverable_row(
                conn,
                deliverable_id,
                phase_id,
                values,
                expected_updated_at,
            )

            for field_name in changed_fields:
                conn.execute(
                    """
                    INSERT INTO project_status_field_authority
                        (deliverable_id, field_name, authority, source_type, locked_at, updated_at)
                    VALUES (?, ?, 'manual', ?,
                            strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime'),
                            strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime'))
                    ON CONFLICT(deliverable_id, field_name) DO UPDATE SET
                        authority = 'manual',
                        source_type = excluded.source_type,
                        locked_at = excluded.locked_at,
                        updated_at = excluded.updated_at
                    """,
                    (deliverable_id, field_name, source_type),
                )
            conn.execute(
                """
                INSERT INTO project_status_update_audit
                    (deliverable_id, trigger_type, source_type, external_version,
                     proposed_changes_json, applied_changes_json, skipped_fields_json,
                     result, error_summary)
                VALUES (?, 'manual', ?, NULL, ?, ?, '{}', 'applied', NULL)
                """,
                (deliverable_id, source_type, proposed_changes_json, applied_changes_json),
            )
            self._prune_project_status_audit(conn, deliverable_id)
            conn.execute(
                "UPDATE project_status_phases SET updated_at = ? WHERE id = ?",
                (updated_at, phase_id),
            )
            return updated_at

    def get_project_status_update_policy(self, deliverable_id: str) -> dict[str, object] | None:
        """返回交付物绑定、字段归属和最近审计摘要；未知交付物返回 None。"""
        with self.get_connection() as conn:
            deliverable = conn.execute(
                "SELECT id FROM project_status_deliverables WHERE id = ?",
                (deliverable_id,),
            ).fetchone()
            if deliverable is None:
                return None
            self._ensure_project_status_policy(conn, deliverable_id)
            binding = conn.execute(
                """
                SELECT id, deliverable_id, mode, source_type, external_key,
                       match_rule_json, mapping_json, enabled, interval_minutes,
                       last_attempt_at, last_success_at, sync_state, sync_config_revision,
                        last_error_type, last_error_message, credential_ref,
                        created_at, updated_at
                FROM project_status_update_bindings
                WHERE deliverable_id = ?
                """,
                (deliverable_id,),
            ).fetchone()
            assert binding is not None
            authorities = conn.execute(
                """
                SELECT field_name, authority, source_type, locked_at, updated_at
                FROM project_status_field_authority
                WHERE deliverable_id = ?
                ORDER BY field_name
                """,
                (deliverable_id,),
            ).fetchall()
            latest = conn.execute(
                """
                SELECT id, trigger_type, source_type, external_version, result,
                       error_summary, created_at
                FROM project_status_update_audit
                WHERE deliverable_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (deliverable_id,),
            ).fetchone()
            return {
                "binding": dict(binding),
                "authorities": [dict(row) for row in authorities],
                "latest_audit": dict(latest) if latest is not None else None,
            }

    def set_project_status_update_policy(
        self,
        deliverable_id: str,
        mode: str,
        enabled: bool,
        external_key: str | None,
        match_rule_json: str,
        mapping_json: str,
        field_authority: dict[str, str],
        credential_ref: str | None = None,
        interval_minutes: int | None = 60,
        expected_sync_config_revision: int | None = None,
    ) -> int:
        """原子写入绑定与字段归属，自动归属同时解除人工锁。

        同步配置修订号（GPT 终审任务 2）：匹配规则、稳定键、映射或模式变化时
        在本事务内 +1 并清空分析快照/明细缓存（旧车型数据隔离）；仅改
        interval/credential 不递增、不清缓存。返回递增后的修订号。
        """
        unknown = set(field_authority) - set(PROJECT_STATUS_EDITABLE_FIELDS)
        if unknown:
            raise ValueError(f"unknown project status field: {sorted(unknown)}")
        with self.get_connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            deliverable = conn.execute(
                "SELECT id FROM project_status_deliverables WHERE id = ?",
                (deliverable_id,),
            ).fetchone()
            if deliverable is None:
                raise KeyError(deliverable_id)
            self._ensure_project_status_policy(conn, deliverable_id)
            old_binding = conn.execute(
                """
                SELECT mode, external_key, match_rule_json, mapping_json,
                       sync_config_revision
                FROM project_status_update_bindings
                WHERE deliverable_id = ?
                """,
                (deliverable_id,),
            ).fetchone()
            if (expected_sync_config_revision is not None
                    and int(old_binding['sync_config_revision'] or 0) != expected_sync_config_revision):
                raise ProjectStatusConcurrentUpdateError('Binding changed while validating the policy')
            target_changed = (
                old_binding["match_rule_json"] != match_rule_json
                or old_binding["mapping_json"] != mapping_json
                or old_binding["external_key"] != external_key
                or old_binding["mode"] != mode
            )
            new_revision = int(old_binding["sync_config_revision"] or 0) + (
                1 if target_changed else 0
            )
            conn.execute(
                """
                UPDATE project_status_update_bindings
                SET mode = ?, enabled = ?, external_key = ?, match_rule_json = ?,
                    mapping_json = ?, credential_ref = ?, interval_minutes = ?,
                    sync_config_revision = ?,
                    cursor_json = CASE WHEN ? THEN '{}' ELSE cursor_json END,
                    updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime')
                WHERE deliverable_id = ?
                """,
                (mode, int(enabled), external_key, match_rule_json, mapping_json,
                 credential_ref, interval_minutes, new_revision, int(target_changed), deliverable_id),
            )
            for field_name, authority in field_authority.items():
                conn.execute(
                    """
                    INSERT INTO project_status_field_authority
                        (deliverable_id, field_name, authority, source_type, locked_at, updated_at)
                    VALUES (?, ?, ?, (SELECT source_type FROM project_status_update_bindings WHERE deliverable_id = ?),
                            CASE WHEN ? = 'automatic' THEN NULL
                                 ELSE strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime') END,
                            strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime'))
                    ON CONFLICT(deliverable_id, field_name) DO UPDATE SET
                        authority = excluded.authority,
                        source_type = excluded.source_type,
                        locked_at = excluded.locked_at,
                        updated_at = excluded.updated_at
                    """,
                    (deliverable_id, field_name, authority, deliverable_id, authority),
                )
            if target_changed:
                conn.execute(
                    "DELETE FROM project_status_analysis_snapshots WHERE deliverable_id = ?",
                    (deliverable_id,),
                )
                conn.execute(
                    "DELETE FROM project_status_analysis_items WHERE deliverable_id = ?",
                    (deliverable_id,),
                )
        return new_revision

    def list_project_status_update_audit(
        self,
        deliverable_id: str,
        limit: int = 100,
    ) -> list[sqlite3.Row]:
        """读取按时间倒序的审计记录，最多 limit 条。"""
        with self.get_connection() as conn:
            return conn.execute(
                """
                SELECT id, deliverable_id, trigger_type, source_type, external_version,
                       proposed_changes_json, applied_changes_json, skipped_fields_json,
                       result, error_summary, created_at
                FROM project_status_update_audit
                WHERE deliverable_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (deliverable_id, limit),
            ).fetchall()

    def get_project_status_update_policy_summaries(
        self,
        phase_id: str,
    ) -> dict[str, dict[str, object]]:
        """读取一个阶段全部交付物的绑定摘要，供只读总览增量使用。"""
        with self.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT b.deliverable_id, b.mode, b.source_type, b.enabled,
                       b.external_key, b.mapping_json, b.sync_state,
                       b.last_attempt_at, b.last_success_at, b.last_error_type,
                       b.last_error_message, b.updated_at, b.match_rule_json
                FROM project_status_update_bindings b
                INNER JOIN project_status_deliverables d ON d.id = b.deliverable_id
                WHERE d.phase_id = ?
                """,
                (phase_id,),
            ).fetchall()
            return {str(row["deliverable_id"]): dict(row) for row in rows}

    def replace_project_status_milestones(
        self,
        phase_id: str,
        milestones: list[dict[str, object]],
        expected_updated_at: str,
    ) -> str:
        """以单一事务替换阶段里程碑，并用阶段更新时间作乐观锁。"""
        next_updated_at_sql = "strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime')"
        with self.get_connection() as conn:
            phase = conn.execute(
                "SELECT updated_at FROM project_status_phases WHERE id = ?",
                (phase_id,),
            ).fetchone()
            if phase is None:
                raise KeyError(phase_id)
            if str(phase["updated_at"]) != expected_updated_at:
                raise RuntimeError("project status phase has changed")

            existing_ids = {
                int(row["id"])
                for row in conn.execute(
                    "SELECT id FROM project_status_milestones WHERE phase_id = ?",
                    (phase_id,),
                ).fetchall()
            }
            requested_ids = {
                int(item["id"])
                for item in milestones
                if item.get("id") is not None
            }
            if not requested_ids.issubset(existing_ids):
                raise KeyError("milestone")

            # 全量重建该阶段的短列表，避免两个合法节点交换名称时触发临时唯一键冲突。
            conn.execute(
                "DELETE FROM project_status_milestones WHERE phase_id = ?",
                (phase_id,),
            )
            for item in milestones:
                milestone_id = item.get("id")
                columns = "phase_id, name, milestone_date, status, type, sort_order"
                values = (
                    phase_id,
                    item["name"],
                    item["date"],
                    item["status"],
                    item["type"],
                    item["sort_order"],
                )
                if milestone_id is None:
                    conn.execute(
                        f"INSERT INTO project_status_milestones ({columns}) VALUES (?, ?, ?, ?, ?, ?)",
                        values,
                    )
                else:
                    conn.execute(
                        f"INSERT INTO project_status_milestones (id, {columns}) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (int(milestone_id), *values),
                    )

            cursor = conn.execute(
                f"UPDATE project_status_phases SET updated_at = {next_updated_at_sql} "
                "WHERE id = ? AND updated_at = ?",
                (phase_id, expected_updated_at),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("project status phase has changed")
            row = conn.execute(
                "SELECT updated_at FROM project_status_phases WHERE id = ?",
                (phase_id,),
            ).fetchone()
            assert row is not None
            return str(row["updated_at"])
