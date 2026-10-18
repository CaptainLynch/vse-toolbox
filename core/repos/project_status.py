# -*- coding: utf-8 -*-
"""项目状态（主计划、交付物、分析缓存、手工更新策略与审计、里程碑）的数据访问（DatabaseManager 的领域分片）。

由 core/db_manager.py 按领域拆出；``DatabaseManager`` 继承本类，对外接口不变。
本类依赖 ``get_connection`` 等由 DatabaseManager 提供的方法，不单独实例化。
"""

from hashlib import sha256
from typing import NamedTuple
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
from core.project_status_config_audit import (
    BindingConfigAuditError,
    build_binding_config_audit_payload,
    project_binding_config_audit_scope,
)


POLICY_BINDING_DEFAULTS = {
    "mode": "manual", "enabled": 0, "external_key": None,
    "interval_minutes": None, "credential_ref": None,
    "mapping_json": "{}", "match_rule_json": "{}", "sync_config_revision": 0,
}
POLICY_AUTHORITY_DEFAULT = "manual"


def _policy_binding_defaults(deliverable_id):
    row = dict(POLICY_BINDING_DEFAULTS)
    cap = PROJECT_STATUS_SOURCE_CAPABILITIES.get(deliverable_id, {})
    row["mode"] = "automatic" if cap.get("syncCapable") else "manual"
    return row


def compute_policy_config_digest(deliverable_id, binding, authorities) -> str:
    """Hash raw stored policy values without I/O or input mutation."""
    row = _policy_binding_defaults(deliverable_id) if binding is None else dict(binding)
    projected = {key: row[key] for key in POLICY_BINDING_DEFAULTS
                 if key != "credential_ref"}
    projected["has_credential_ref"] = (
        row["credential_ref"] is not None and row["credential_ref"] != "")
    by_name = {name: POLICY_AUTHORITY_DEFAULT for name in PROJECT_STATUS_EDITABLE_FIELDS}
    by_name.update({item["field_name"]: item["authority"] for item in authorities})
    payload = {
        "v": 1, "binding": projected,
        "field_authority": [{"field_name": name, "authority": by_name[name]}
                            for name in sorted(by_name)],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True, allow_nan=False).encode("utf-8")
    return "cfgd1:" + sha256(canonical).hexdigest()


KEEP_CURRENT = object()


class ProjectStatusConfigDigestMismatchError(ProjectStatusConcurrentUpdateError):
    """The stored policy no longer matches the expected configuration digest."""


class _PolicySaveResult(NamedTuple):
    revision: int
    raw: dict


def _read_policy_rows(conn, deliverable_id):
    """Read the same three projections as GET, without seeding any rows."""
    binding = conn.execute(
        "SELECT id, deliverable_id, mode, source_type, external_key, "
        "match_rule_json, mapping_json, enabled, interval_minutes, "
        "last_attempt_at, last_success_at, sync_state, sync_config_revision, "
        "last_error_type, last_error_message, credential_ref, created_at, updated_at "
        "FROM project_status_update_bindings WHERE deliverable_id = ?",
        (deliverable_id,)).fetchone()
    authorities = conn.execute(
        "SELECT field_name, authority, source_type, locked_at, updated_at "
        "FROM project_status_field_authority WHERE deliverable_id = ? ORDER BY field_name",
        (deliverable_id,)).fetchall()
    latest = conn.execute(
        "SELECT id, trigger_type, source_type, external_version, result, error_summary, created_at "
        "FROM project_status_update_audit WHERE deliverable_id = ? ORDER BY id DESC LIMIT 1",
        (deliverable_id,)).fetchone()
    return {
        "binding": dict(binding) if binding is not None else None,
        "authorities": [dict(row) for row in authorities],
        "latest_audit": dict(latest) if latest is not None else None,
    }


def _normalize_policy_rows(deliverable_id, raw):
    """Fill missing policy rows in memory; synthetic database metadata stays None."""
    source_type = str(PROJECT_STATUS_SOURCE_CAPABILITIES.get(deliverable_id, {}).get("sourceType") or "none")
    if raw["binding"] is None:
        raw["binding"] = dict(
            _policy_binding_defaults(deliverable_id),
            id=None, deliverable_id=deliverable_id, source_type=source_type, sync_state="idle",
            last_attempt_at=None, last_success_at=None, last_error_type=None,
            last_error_message=None, created_at=None, updated_at=None,
        )
    by_name = {row["field_name"]: row for row in raw["authorities"]}
    for name in PROJECT_STATUS_EDITABLE_FIELDS:
        by_name.setdefault(name, dict(
            field_name=name, authority=POLICY_AUTHORITY_DEFAULT,
            source_type=source_type, locked_at=None, updated_at=None,
        ))
    raw["authorities"] = [by_name[name] for name in sorted(by_name)]
    return raw


def _parse_policy_json(value: Any) -> Any:
    """解析绑定 JSON 列用于语义比较（键序无关）；空值或坏 JSON 视为 {}。"""
    if not isinstance(value, str) or not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


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
        """Seed missing rows from the same defaults used by the digest."""
        capabilities = PROJECT_STATUS_SOURCE_CAPABILITIES.get(deliverable_id, {})
        source_type = str(capabilities.get("sourceType") or "none")
        defaults = _policy_binding_defaults(deliverable_id)
        # Preserve the no-DML path when both tables are complete.
        has_binding = conn.execute(
            "SELECT 1 FROM project_status_update_bindings WHERE deliverable_id = ?",
            (deliverable_id,),
        ).fetchone() is not None
        if not has_binding:
            conn.execute(
                """
                INSERT OR IGNORE INTO project_status_update_bindings
                    (deliverable_id, mode, source_type, enabled, sync_state,
                     external_key, interval_minutes, credential_ref,
                     mapping_json, match_rule_json, sync_config_revision)
                VALUES (?, ?, ?, ?, 'idle', ?, ?, ?, ?, ?, ?)
                """,
                (deliverable_id, defaults["mode"], source_type, defaults["enabled"],
                 defaults["external_key"], defaults["interval_minutes"],
                 defaults["credential_ref"], defaults["mapping_json"],
                 defaults["match_rule_json"], defaults["sync_config_revision"]),
            )
        present = {
            row[0]
            for row in conn.execute(
                "SELECT field_name FROM project_status_field_authority WHERE deliverable_id = ?",
                (deliverable_id,),
            ).fetchall()
        }
        missing = [name for name in PROJECT_STATUS_EDITABLE_FIELDS if name not in present]
        if missing:
            conn.executemany(
                """
                INSERT OR IGNORE INTO project_status_field_authority
                    (deliverable_id, field_name, authority, source_type)
                VALUES (?, ?, ?, ?)
                """,
                [(deliverable_id, field_name, POLICY_AUTHORITY_DEFAULT, source_type)
                 for field_name in missing],
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
            return _read_policy_rows(conn, deliverable_id)

    def read_project_status_update_policy_snapshot(
        self, deliverable_id: str
    ) -> dict[str, object] | None:
        """Read policy rows without seeding missing rows."""
        with self.get_connection() as conn:
            deliverable = conn.execute(
                "SELECT id FROM project_status_deliverables WHERE id = ?",
                (deliverable_id,),
            ).fetchone()
            if deliverable is None:
                return None
            return _normalize_policy_rows(deliverable_id, _read_policy_rows(conn, deliverable_id))

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
        *,
        actor: str = "local_web",
        audit_field_names: Mapping[str, str] | None = None,
    ) -> int:
        """原子写入绑定、字段归属与绑定配置审计，自动归属同时解除人工锁。

        同步配置修订号（GPT 终审任务 2）：匹配规则、稳定键、映射或模式变化时
        在本事务内 +1 并清空分析快照/明细缓存（旧车型数据隔离）；仅改
        interval/credential/enabled/字段归属不递增、不清缓存。

        B′ P1a：变更前状态在 BEGIN IMMEDIATE 内读取；与请求无差异时零写入、不审计；
        有差异时在同一连接、同一事务内调用 ``record_deliverable_config_audit(..., conn=conn)``，
        并核对恰好新增一行匹配的审计记录，否则抛出 ``BindingConfigAuditError`` 整笔回滚。
        ``audit_field_names`` 把字段归属的列名翻译成审计载荷里的字段名（服务层传 API 名）。
        返回保存后的修订号。
        """
        with self.get_connection() as conn:
            return self._save_policy_txn(
                conn, deliverable_id, mode, enabled, external_key, match_rule_json,
                mapping_json, field_authority, credential_ref, interval_minutes,
                expected_sync_config_revision, actor=actor,
                audit_field_names=audit_field_names,
            ).revision

    def _save_policy_txn(
        self,
        conn: sqlite3.Connection,
        deliverable_id: str,
        mode: str,
        enabled: bool,
        external_key: str | None,
        match_rule_json: str,
        mapping_json: str,
        field_authority: dict[str, str],
        credential_ref: Any = None,
        interval_minutes: int | None = 60,
        expected_sync_config_revision: int | None = None,
        *,
        actor: str = "local_web",
        audit_field_names: Mapping[str, str] | None = None,
        expected_config_digest: str | None = None,
    ) -> _PolicySaveResult:
        """Save and return a transaction-owned snapshot after a successful commit."""
        if conn.in_transaction:
            raise ValueError("policy save requires a connection without an active transaction")
        unknown = set(field_authority) - set(PROJECT_STATUS_EDITABLE_FIELDS)
        if unknown:
            raise ValueError(f"unknown project status field: {sorted(unknown)}")
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            deliverable = conn.execute(
                "SELECT id FROM project_status_deliverables WHERE id = ?",
                (deliverable_id,),
            ).fetchone()
            if deliverable is None:
                raise KeyError(deliverable_id)
            raw = _normalize_policy_rows(deliverable_id, _read_policy_rows(conn, deliverable_id))
            old_binding = raw["binding"]
            old_revision = int(old_binding['sync_config_revision'] or 0)
            if (expected_sync_config_revision is not None
                    and old_revision != expected_sync_config_revision):
                raise ProjectStatusConcurrentUpdateError('Binding changed while validating the policy')
            if (expected_config_digest is not None
                    and compute_policy_config_digest(
                        deliverable_id, old_binding, raw["authorities"]) != expected_config_digest):
                raise ProjectStatusConfigDigestMismatchError("Policy configuration digest changed")
            if credential_ref is KEEP_CURRENT:
                credential_ref = old_binding["credential_ref"]
            old_authority = {
                str(row["field_name"]): str(row["authority"])
                for row in raw["authorities"]
            }
            new_authority = dict(old_authority)
            new_authority.update({str(k): str(v) for k, v in field_authority.items()})
            changed_authority = [
                name for name, value in new_authority.items()
                if old_authority.get(name) != value
            ]

            old_rule = _parse_policy_json(old_binding["match_rule_json"])
            new_rule = _parse_policy_json(match_rule_json)
            old_mapping = _parse_policy_json(old_binding["mapping_json"])
            new_mapping = _parse_policy_json(mapping_json)
            old_credential = old_binding["credential_ref"]
            diffs: dict[str, tuple[Any, Any]] = {}
            if old_binding["mode"] != mode:
                diffs["mode"] = (old_binding["mode"], mode)
            if bool(old_binding["enabled"]) != bool(enabled):
                diffs["enabled"] = (bool(old_binding["enabled"]), bool(enabled))
            if old_binding["external_key"] != external_key:
                diffs["externalKey"] = (old_binding["external_key"], external_key)
            if old_rule != new_rule:
                diffs["matchRule"] = (old_rule, new_rule)
            if old_mapping != new_mapping:
                diffs["mapping"] = (old_mapping, new_mapping)
            if old_binding["interval_minutes"] != interval_minutes:
                diffs["intervalMinutes"] = (old_binding["interval_minutes"], interval_minutes)
            if old_credential != credential_ref:
                # 凭据别名不进审计，只记是否已配置。
                diffs["credentialConfigured"] = (
                    bool(str(old_credential or "").strip()),
                    bool(str(credential_ref or "").strip()),
                )
            binding_changed = bool(diffs)
            if changed_authority:
                names = audit_field_names or {}
                diffs["fieldAuthority"] = (
                    {names.get(k, k): v for k, v in old_authority.items()},
                    {names.get(k, k): v for k, v in new_authority.items()},
                )
            if not diffs:
                return _PolicySaveResult(old_revision, raw)

            self._ensure_project_status_policy(conn, deliverable_id)
            recorder = getattr(self, "record_deliverable_config_audit", None)
            if not callable(recorder):
                raise BindingConfigAuditError("binding config audit recorder is unavailable")
            target_changed = any(
                name in diffs for name in ("mode", "externalKey", "matchRule", "mapping")
            )
            new_revision = old_revision + (1 if target_changed else 0)
            if binding_changed:
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
                     credential_ref, interval_minutes, new_revision, int(target_changed),
                     deliverable_id),
                )
            for field_name in changed_authority:
                authority = new_authority[field_name]
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

            audit_diffs = dict(diffs)
            audit_diffs.pop("matchRule", None)
            old_scope = project_binding_config_audit_scope(old_rule)
            new_scope = project_binding_config_audit_scope(new_rule)
            if old_scope != new_scope:
                audit_diffs["scope"] = (old_scope, new_scope)
            old_audit_rule = (
                {key: value for key, value in old_rule.items() if key != "sectionScope"}
                if isinstance(old_rule, dict) else old_rule
            )
            new_audit_rule = (
                {key: value for key, value in new_rule.items() if key != "sectionScope"}
                if isinstance(new_rule, dict) else new_rule
            )
            if old_audit_rule != new_audit_rule:
                audit_diffs["matchRule"] = (old_audit_rule, new_audit_rule)
            payload = build_binding_config_audit_payload(
                deliverable_id, old_revision, new_revision, audit_diffs,
                after_rule=new_rule,
            )
            last_id = int(conn.execute(
                "SELECT COALESCE(MAX(id), 0) FROM project_status_binding_config_audit"
            ).fetchone()[0])
            try:
                recorded = recorder(deliverable_id, payload, actor, conn=conn)
            except Exception as exc:
                raise BindingConfigAuditError("binding config audit recorder failed") from exc
            inserted = conn.execute(
                """
                SELECT deliverable_id, actor, event_type, config_revision, changes_json
                FROM project_status_binding_config_audit
                WHERE id > ? ORDER BY id
                """,
                (last_id,),
            ).fetchall()
            if (
                recorded is not True
                or len(inserted) != 1
                or inserted[0]["deliverable_id"] != deliverable_id
                or inserted[0]["actor"] != actor
                or inserted[0]["event_type"] != "configuration_updated"
                or inserted[0]["config_revision"] != new_revision
                or _parse_policy_json(inserted[0]["changes_json"]) != payload
            ):
                raise BindingConfigAuditError("binding config audit row was not recorded")
            raw = _normalize_policy_rows(deliverable_id, _read_policy_rows(conn, deliverable_id))
        return _PolicySaveResult(new_revision, raw)

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
