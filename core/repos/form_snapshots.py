# -*- coding: utf-8 -*-
"""交付物表单快照与明细行的数据访问（DatabaseManager 的领域分片）。

由 core/db_manager.py 按领域拆出；``DatabaseManager`` 继承本类，对外接口不变。
本类依赖 ``get_connection`` 等由 DatabaseManager 提供的方法，不单独实例化。
"""

from core.db_common import (  # noqa: F401
    _form_json,
    _form_row_filter_sql,
    _FORM_SNAPSHOT_KEYS,
    _form_snapshot_payload,
    _FORM_SNAPSHOT_RETENTION,
    _json_loads_or_none,
    Any,
    find_deliverable_id_by_form_key,
    Mapping,
    observed,
    Sequence,
    sqlite3,
)


class FormSnapshotRepo:
    @observed("db.publish_deliverable_form_snapshot")
    def publish_deliverable_form_snapshot(
        self,
        snapshot: object,
        *,
        expected_sync_config_revision: int | None = None,
    ) -> int:
        """Atomically replace one source snapshot and its bounded form rows.

        expected_sync_config_revision 提供时（EWO 同步运行发布路径），在事务内
        校验绑定修订号；不一致（换绑）拒绝发布旧运行的表单快照并返回 0。
        """
        payload = _form_snapshot_payload(snapshot)
        rows = payload["rows"]
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if expected_sync_config_revision is not None:
                # 换绑校验（GPT 终审任务 2d）：apply 后、发布前发生换绑 →
                # 拒绝发布旧运行的表单快照。
                form_key = str(payload.get("form_key") or payload.get("formKey") or "")
                form_deliverable = find_deliverable_id_by_form_key(form_key) or form_key
                binding_row = conn.execute(
                    "SELECT sync_config_revision FROM project_status_update_bindings "
                    "WHERE deliverable_id = ?",
                    (form_deliverable,),
                ).fetchone()
                if (
                    binding_row is None
                    or binding_row["sync_config_revision"] is None
                    or int(binding_row["sync_config_revision"] or 0)
                    != int(expected_sync_config_revision)
                ):
                    return 0
            existing = conn.execute(
                "SELECT id FROM deliverable_form_snapshots WHERE snapshot_key = ?",
                (payload["snapshot_key"],),
            ).fetchone()
            metadata = (
                payload["form_key"],
                payload["report_type"],
                payload["source_run_id"],
                payload["source"],
                payload["snapshot_at"],
                len(rows),
                _form_json(payload["schema"]),
                _form_json(payload["summary"]),
                _form_json(payload["charts"]),
                _form_json(payload["artifacts"]),
            )
            if existing is None:
                insert_cursor = conn.execute(
                    """
                    INSERT INTO deliverable_form_snapshots (
                        snapshot_key, form_key, report_type, source_run_id,
                        source, snapshot_at, row_count, schema_json,
                        summary_json, charts_json, artifacts_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (payload["snapshot_key"], *metadata),
                )
                if insert_cursor.lastrowid is None:
                    raise RuntimeError("form snapshot insert did not return an id")
                snapshot_id = int(insert_cursor.lastrowid)
            else:
                snapshot_id = int(existing["id"])
                conn.execute(
                    """
                    UPDATE deliverable_form_snapshots
                    SET form_key = ?, report_type = ?, source_run_id = ?,
                        source = ?, snapshot_at = ?, row_count = ?,
                        schema_json = ?, summary_json = ?, charts_json = ?,
                        artifacts_json = ?
                    WHERE id = ?
                    """,
                    (*metadata, snapshot_id),
                )
                conn.execute(
                    "DELETE FROM deliverable_form_rows WHERE snapshot_id = ?",
                    (snapshot_id,),
                )

            form_rows: list[tuple[object, ...]] = []
            for index, item in enumerate(rows, 1):
                if not isinstance(item, Mapping):
                    continue
                dimensions = item.get("dimensions")
                if not isinstance(dimensions, Mapping):
                    dimensions = {}
                values = item.get("values")
                if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                    values = []
                row_key = str(item.get("rowKey") or item.get("row_key") or f"row-{index}")
                row_number = item.get("rowNumber", item.get("row_number", index))
                if isinstance(row_number, bool) or not isinstance(row_number, int) or row_number < 1:
                    row_number = index
                overdue_state = str(item.get("overdueState") or "unknown")
                if overdue_state not in {"on_time", "overdue", "unknown", "not_applicable"}:
                    overdue_state = "unknown"
                form_rows.append(
                    (
                        snapshot_id,
                        row_key[:256],
                        row_number,
                        str(item.get("sheetName") or item.get("sheet_name") or "")[:200],
                        _form_json(values, limit=2 * 1024 * 1024),
                        _form_json(dimensions, limit=256 * 1024),
                        str(item.get("searchText") or "")[:4000],
                        str(dimensions.get("status") or "")[:200],
                        str(dimensions.get("department") or "")[:200],
                        str(dimensions.get("section") or "")[:200],
                        str(dimensions.get("model") or "")[:200],
                        str(dimensions.get("stage") or "")[:200],
                        item.get("submittedDate"),
                        item.get("plannedDate"),
                        overdue_state,
                        1 if bool(item.get("isCompleted")) else 0,
                        _form_json(item.get("cost") or {}, limit=256 * 1024),
                    )
                )
            if form_rows:
                conn.executemany(
                    """
                    INSERT INTO deliverable_form_rows (
                        snapshot_id, row_key, row_number, sheet_name,
                        values_json, dimensions_json, search_text, status_key,
                        department_key, section_key, model_key, stage_key,
                        submitted_date, planned_date, overdue_state,
                        is_completed, cost_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    form_rows,
                )
            conn.execute(
                """
                DELETE FROM deliverable_form_snapshots
                WHERE form_key = ? AND id NOT IN (
                    SELECT id FROM deliverable_form_snapshots
                    WHERE form_key = ?
                    ORDER BY snapshot_at DESC, id DESC LIMIT ?
                )
                """,
                (
                    payload["form_key"],
                    payload["form_key"],
                    _FORM_SNAPSHOT_RETENTION,
                ),
            )
            return snapshot_id

    @staticmethod
    def _decode_form_snapshot_row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        for target, source in (
            ("values", "values_json"),
            ("dimensions", "dimensions_json"),
            ("cost", "cost_json"),
        ):
            parsed = _json_loads_or_none(result.pop(source, ""))
            result[target] = parsed if parsed is not None else (
                [] if target == "values" else {}
            )
        result["isCompleted"] = bool(result.pop("is_completed", 0))
        result["rowKey"] = result.pop("row_key", "")
        result["rowNumber"] = result.pop("row_number", 0)
        result["sheetName"] = result.pop("sheet_name", "")
        result["submittedDate"] = result.pop("submitted_date", None)
        result["plannedDate"] = result.pop("planned_date", None)
        result["overdueState"] = result.pop("overdue_state", "unknown")
        result.pop("id", None)
        result.pop("snapshot_id", None)
        result.pop("search_text", None)
        result.pop("status_key", None)
        result.pop("department_key", None)
        result.pop("section_key", None)
        result.pop("model_key", None)
        result.pop("stage_key", None)
        return result

    def get_latest_deliverable_form_snapshot(
        self,
        form_key: str,
    ) -> dict[str, Any] | None:
        if form_key not in _FORM_SNAPSHOT_KEYS:
            raise KeyError(form_key)
        with self.get_connection() as conn:
            row = conn.execute(
                """
                SELECT id, snapshot_key, form_key, report_type, source_run_id,
                       source, snapshot_at, row_count, schema_json,
                       summary_json, charts_json, artifacts_json, created_at
                FROM deliverable_form_snapshots
                WHERE form_key = ?
                ORDER BY snapshot_at DESC, id DESC LIMIT 1
                """,
                (form_key,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        for target, source in (
            ("schema", "schema_json"),
            ("summary", "summary_json"),
            ("charts", "charts_json"),
            ("artifacts", "artifacts_json"),
        ):
            parsed = _json_loads_or_none(result.pop(source, ""))
            result[target] = parsed if parsed is not None else (
                [] if target == "artifacts" else {}
            )
        return result

    def list_deliverable_form_snapshots(
        self,
        form_key: str,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        if form_key not in _FORM_SNAPSHOT_KEYS:
            raise KeyError(form_key)
        bounded = max(1, min(int(limit), 365))
        with self.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, snapshot_key, form_key, report_type, source_run_id,
                       source, snapshot_at, row_count, schema_json,
                       summary_json, charts_json, artifacts_json, created_at
                FROM deliverable_form_snapshots
                WHERE form_key = ?
                ORDER BY snapshot_at DESC, id DESC LIMIT ?
                """,
                (form_key, bounded),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for target, source in (
                ("schema", "schema_json"),
                ("summary", "summary_json"),
                ("charts", "charts_json"),
                ("artifacts", "artifacts_json"),
            ):
                parsed = _json_loads_or_none(item.pop(source, ""))
                item[target] = parsed if parsed is not None else (
                    [] if target == "artifacts" else {}
                )
            result.append(item)
        return result

    def list_deliverable_form_rows(
        self,
        form_key: str,
        filters: Mapping[str, object] | None = None,
        *,
        offset: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        if form_key not in _FORM_SNAPSHOT_KEYS:
            raise KeyError(form_key)
        bounded_offset = max(0, min(int(offset), 100000))
        bounded_limit = max(1, min(int(limit), 500))
        where, params = _form_row_filter_sql(filters)
        clause = " AND ".join(where) if where else "1 = 1"
        with self.get_connection() as conn:
            total_row = conn.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM deliverable_form_rows r
                WHERE r.snapshot_id = (
                    SELECT id FROM deliverable_form_snapshots
                    WHERE form_key = ? ORDER BY snapshot_at DESC, id DESC LIMIT 1
                ) AND {clause}
                """,
                tuple([form_key, *params]),
            ).fetchone()
            rows = conn.execute(
                f"""
                SELECT r.id, r.snapshot_id, r.row_key, r.row_number,
                       r.sheet_name, r.values_json, r.dimensions_json,
                       r.search_text, r.status_key, r.department_key,
                       r.section_key, r.model_key, r.stage_key,
                       r.submitted_date, r.planned_date, r.overdue_state,
                       r.is_completed, r.cost_json
                FROM deliverable_form_rows r
                WHERE r.snapshot_id = (
                    SELECT id FROM deliverable_form_snapshots
                    WHERE form_key = ? ORDER BY snapshot_at DESC, id DESC LIMIT 1
                ) AND {clause}
                ORDER BY r.is_completed ASC, r.row_number ASC, r.id ASC
                LIMIT ? OFFSET ?
                """,
                tuple([form_key, *params, bounded_limit, bounded_offset]),
            ).fetchall()
        return {
            "items": [self._decode_form_snapshot_row(row) for row in rows],
            "total": int(total_row["total"]) if total_row is not None else 0,
            "offset": bounded_offset,
            "limit": bounded_limit,
        }

    def list_deliverable_form_snapshot_rows(
        self,
        snapshot_id: int,
        filters: Mapping[str, object] | None = None,
        *,
        limit: int = 20000,
    ) -> list[dict[str, Any]]:
        """Read bounded rows for one stored snapshot for server-side charts."""
        if isinstance(snapshot_id, bool) or not isinstance(snapshot_id, int) or snapshot_id < 1:
            raise ValueError("snapshot_id must be a positive integer")
        bounded_limit = max(1, min(int(limit), 20000))
        where, params = _form_row_filter_sql(filters)
        clause = " AND ".join(where) if where else "1 = 1"
        with self.get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT id, snapshot_id, row_key, row_number, sheet_name,
                       values_json, dimensions_json, search_text, status_key,
                       department_key, section_key, model_key, stage_key,
                       submitted_date, planned_date, overdue_state,
                       is_completed, cost_json
                FROM deliverable_form_rows r
                WHERE r.snapshot_id = ? AND {clause}
                ORDER BY r.is_completed ASC, r.row_number ASC, r.id ASC
                LIMIT ?
                """,
                tuple([snapshot_id, *params, bounded_limit]),
            ).fetchall()
        return [self._decode_form_snapshot_row(row) for row in rows]
