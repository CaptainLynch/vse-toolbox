# -*- coding: utf-8 -*-
"""定时归档任务：配置、租约、运行与产物的数据访问（DatabaseManager 的领域分片）。

由 core/db_manager.py 按领域拆出；``DatabaseManager`` 继承本类，对外接口不变。
本类依赖 ``get_connection`` 等由 DatabaseManager 提供的方法，不单独实例化。
"""

from core.db_common import (  # noqa: F401
    _json_loads_or_none,
    _normalize_archive_retry_policy,
    _UTC_NOW_SQL,
    _utc_offset_sql,
    Any,
    ARCHIVE_CREDENTIAL_UNCHANGED,
    ARCHIVE_JOB_CONTRACTS,
    ARCHIVE_OUTPUT_DIRECTORY_UNCHANGED,
    ARCHIVE_RETRY_UNCHANGED,
    ArchiveJobNotReadyError,
    ArchiveLeaseBusyError,
    ArchiveLeaseLostError,
    json,
    Mapping,
    observed,
    redact_sensitive_text,
    secrets,
    Sequence,
    sqlite3,
    SYNC_LEASE_DEFAULT_SECONDS,
)


class ArchiveRepo:
    def update_archive_job_config(
        self,
        job_key: str,
        *,
        enabled: bool,
        filters: Mapping[str, object],
        output_subdir: str,
        output_directory: object = ARCHIVE_OUTPUT_DIRECTORY_UNCHANGED,
        expected_updated_at: str,
        actor: str,
        credential_ref: object = ARCHIVE_CREDENTIAL_UNCHANGED,
        interval_minutes: int = 60,
        clear_analysis_cache: bool = False,
        retry_policy: object = ARCHIVE_RETRY_UNCHANGED,
    ) -> dict[str, Any]:
        """Optimistically update one fixed job and append a secret-free audit."""
        from core.archive_store import ArchiveStore

        if isinstance(interval_minutes, bool) or not 5 <= int(interval_minutes) <= 10080:
            raise ValueError("archive interval must be between 5 and 10080 minutes")
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a bool")
        if not isinstance(filters, Mapping) or any(
            not isinstance(key, str) for key in filters
        ):
            raise ValueError("archive filters must be an object with string keys")
        sensitive_names = {
            "authorization", "cookie", "token", "password", "secret",
            "credential", "session", "csrf",
        }
        for key, value in filters.items():
            lowered = key.strip().lower()
            if not lowered or any(name in lowered for name in sensitive_names):
                raise ValueError("archive filter name is not allowed")
            if value is None or isinstance(value, str):
                continue
            if isinstance(value, list) and all(
                isinstance(item, str) for item in value
            ):
                continue
            raise ValueError("archive filter values must be strings or string lists")
        filters_json = json.dumps(
            dict(filters), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if len(filters_json.encode("utf-8")) > 16 * 1024:
            raise ValueError("archive filters exceed the configured limit")
        safe_subdir = ArchiveStore.validate_output_subdir(output_subdir)
        if not isinstance(expected_updated_at, str) or not expected_updated_at:
            raise ValueError("expected_updated_at is required")
        if actor not in {"local_web", "cli"}:
            raise ValueError("archive configuration actor is invalid")

        with self.get_connection() as conn:
            row = conn.execute(
                """
                SELECT id, enabled, credential_ref, filters_json,
                       output_subdir, output_directory, interval_minutes, retry_policy_json, updated_at,
                       lease_token, lease_expires_at, template_key, archived_at
                FROM scheduled_archive_jobs WHERE job_key = ?
                """,
                (job_key,),
            ).fetchone()
            if row is None:
                raise KeyError(job_key)
            if row["archived_at"] is not None or str(row["template_key"]) not in ARCHIVE_JOB_CONTRACTS:
                raise KeyError(job_key)
            if str(row["updated_at"]) != expected_updated_at:
                raise RuntimeError("archive job configuration has changed")
            now = self._utc_now(conn)
            if (
                row["lease_token"] is not None
                and row["lease_expires_at"] is not None
                and str(row["lease_expires_at"]) > now
            ):
                raise ArchiveLeaseBusyError(
                    "archive job configuration cannot change during an active lease"
                )

            if output_directory is ARCHIVE_OUTPUT_DIRECTORY_UNCHANGED:
                safe_output_directory = str(row["output_directory"] or "")
            else:
                safe_output_directory = ArchiveStore.validate_output_directory(
                    output_directory
                )
            if safe_output_directory and safe_subdir:
                raise ValueError(
                    "archive output directory cannot be combined with a legacy output subdirectory"
                )

            current_ref = str(row["credential_ref"] or "").strip()
            if credential_ref is ARCHIVE_CREDENTIAL_UNCHANGED:
                next_ref: str | None = current_ref or None
            elif credential_ref is None:
                next_ref = None
            elif isinstance(credential_ref, str):
                next_ref = credential_ref.strip()
                if (
                    not next_ref
                    or len(next_ref) > 256
                    or any(ord(char) < 32 for char in next_ref)
                ):
                    raise ValueError("credential reference alias is invalid")
            else:
                raise TypeError("credential_ref must be a string, null, or omitted")
            if enabled and not next_ref:
                raise ArchiveJobNotReadyError(
                    "enabled archive job requires a credential reference alias",
                    reason="credential_not_configured",
                )

            current_retry = _json_loads_or_none(row["retry_policy_json"])
            if not isinstance(current_retry, dict):
                raise ValueError("archive retry policy is invalid")
            if retry_policy is ARCHIVE_RETRY_UNCHANGED:
                next_retry = current_retry
                next_retry_json = str(row["retry_policy_json"])
            else:
                next_retry = _normalize_archive_retry_policy(retry_policy)
                next_retry_json = json.dumps(
                    next_retry,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )

            changed: list[str] = []
            if bool(row["enabled"]) != enabled:
                changed.append("enabled")
            if current_ref != str(next_ref or ""):
                changed.append("credentialRef")
            if str(row["filters_json"]) != filters_json:
                changed.append("filters")
            if str(row["output_subdir"] or "") != safe_subdir:
                changed.append("outputSubdir")
            if str(row["output_directory"] or "") != safe_output_directory:
                changed.append("outputDirectory")
            if int(row["interval_minutes"]) != int(interval_minutes):
                changed.append("intervalMinutes")
            if str(row["retry_policy_json"]) != next_retry_json:
                changed.append("retryPolicy")
            if changed:
                cursor = conn.execute(
                    f"""
                    UPDATE scheduled_archive_jobs
                    SET enabled = ?, credential_ref = ?, filters_json = ?,
                        output_subdir = ?, output_directory = ?, interval_minutes = ?, retry_policy_json = ?,
                        sync_state = ?, updated_at = {_UTC_NOW_SQL}
                    WHERE id = ? AND updated_at = ?
                    """,
                    (
                        int(enabled), next_ref, filters_json, safe_subdir,
                        safe_output_directory, int(interval_minutes), next_retry_json,
                        "needs_attention" if enabled else "idle",
                        int(row["id"]), expected_updated_at,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("archive job configuration has changed")
                changes_json = json.dumps(
                    {
                        "fields": sorted(changed),
                        "credentialConfigured": bool(next_ref),
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
                conn.execute(
                    """
                    INSERT INTO scheduled_archive_config_audit
                        (job_id, job_key, actor, event_type, changes_json)
                    VALUES (?, ?, ?, 'configuration_updated', ?)
                    """,
                    (int(row["id"]), job_key, actor, changes_json),
                )
        result = next(
            (item for item in self.list_archive_jobs() if item["job_key"] == job_key),
            None,
        )
        if result is None:
            raise KeyError(job_key)
        return result

    def list_archive_config_audit(
        self, job_key: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return bounded configuration audit entries without aliases or values."""
        bounded = max(1, min(int(limit), 500))
        sql = """
            SELECT id, job_id, job_key, actor, event_type,
                   changes_json, created_at
            FROM scheduled_archive_config_audit
        """
        if job_key:
            sql += " WHERE job_key = ? ORDER BY id DESC LIMIT ?"
            params: tuple[Any, ...] = (job_key, bounded)
        else:
            sql += " ORDER BY id DESC LIMIT ?"
            params = (bounded,)
        with self.get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def list_archive_jobs(
        self, enabled_only: bool = False, include_archived: bool = False
    ) -> list[dict[str, Any]]:
        """Return archive job configuration without credential aliases or lease tokens."""
        sql = """
            SELECT id, job_key, source_type, report_type, display_name,
                   template_key, builtin, archived_at,
                   project_status_deliverable_id, enabled, interval_minutes,
                   filters_json, output_subdir, output_directory, retry_policy_json, sync_state,
                   last_attempt_at, last_success_at, last_error_type,
                   last_error_message,
                   CASE WHEN trim(COALESCE(credential_ref, '')) <> ''
                        THEN 1 ELSE 0 END AS credential_configured,
                   created_at, updated_at
            FROM scheduled_archive_jobs
        """
        conditions = []
        if enabled_only:
            conditions.append("enabled = 1")
        if not include_archived:
            conditions.append("archived_at IS NULL")
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY id"
        with self.get_connection() as conn:
            rows = conn.execute(sql).fetchall()
        result = [dict(row) for row in rows]
        for item in result:
            item["enabled"] = bool(item["enabled"])
            item["credential_configured"] = bool(
                item["credential_configured"]
            )
            item["builtin"] = bool(item["builtin"])
        return result

    def create_archive_job_from_template(
        self,
        template_key: str,
        *,
        display_name: str,
        copy_from_job_key: str | None = None,
    ) -> dict[str, Any]:
        contract = ARCHIVE_JOB_CONTRACTS.get(template_key)
        if contract is None:
            raise KeyError(template_key)
        clean_name = str(display_name or "").strip()
        if not clean_name or len(clean_name) > 100:
            raise ValueError("archive task display name is invalid")
        with self.get_connection() as conn:
            source = None
            if copy_from_job_key:
                source = conn.execute(
                    "SELECT * FROM scheduled_archive_jobs WHERE job_key = ? AND archived_at IS NULL",
                    (copy_from_job_key,),
                ).fetchone()
                if source is None or str(source["template_key"]) != template_key:
                    raise KeyError(copy_from_job_key)
            token = secrets.token_hex(5)
            job_key = f"{template_key}_{token}"
            source_type, canonical_report_type, deliverable_id = contract
            cursor = conn.execute(
                """
                INSERT INTO scheduled_archive_jobs (
                    job_key, source_type, report_type, project_status_deliverable_id,
                    enabled, credential_ref, interval_minutes, filters_json,
                    output_subdir, output_directory, retry_policy_json, sync_state,
                    display_name, template_key, builtin
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'idle', ?, ?, 0)
                """,
                (
                    job_key,
                    source_type,
                    f"{canonical_report_type}:{token}",
                    deliverable_id,
                    int(bool(source["enabled"])) if source else 0,
                    source["credential_ref"] if source else None,
                    int(source["interval_minutes"]) if source else 60,
                    source["filters_json"] if source else "{}",
                    source["output_subdir"] if source else "",
                    source["output_directory"] if source else "",
                    source["retry_policy_json"] if source else '{"max_attempts":2,"backoff_seconds":1}',
                    clean_name,
                    template_key,
                ),
            )
            job_id = int(cursor.lastrowid)
        return next(item for item in self.list_archive_jobs() if int(item["id"]) == job_id)

    def archive_archive_job(self, job_key: str, expected_updated_at: str) -> dict[str, Any]:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT id, builtin, updated_at, archived_at FROM scheduled_archive_jobs WHERE job_key = ?",
                (job_key,),
            ).fetchone()
            if row is None or row["archived_at"] is not None:
                raise KeyError(job_key)
            cursor = conn.execute(
                f"UPDATE scheduled_archive_jobs SET enabled = 0, archived_at = {_UTC_NOW_SQL}, "
                f"updated_at = {_UTC_NOW_SQL} WHERE id = ? AND updated_at = ?",
                (int(row["id"]), expected_updated_at),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("archive job configuration has changed")
        archived = next(
            item for item in self.list_archive_jobs(include_archived=True) if item["job_key"] == job_key
        )
        return archived

    def get_archive_job_credential_ref(
        self,
        job_id: int,
        *,
        require_configured: bool = True,
    ) -> str:
        """Return one opaque alias for internal execution only.

        Scheduled execution may explicitly request an empty alias so the
        credential provider can produce an auditable runtime failure after a
        lease/run exists.  Existing callers retain the strict default.
        """
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT credential_ref FROM scheduled_archive_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        value = str(row["credential_ref"] or "").strip()
        if not value and require_configured:
            raise ArchiveJobNotReadyError(
                "archive job credential reference is not configured",
                reason="credential_not_configured",
            )
        return value

    @observed("db.acquire_archive_job_lease")
    def acquire_archive_job_lease(
        self,
        job_id: int,
        trigger_type: str,
        lease_seconds: int = SYNC_LEASE_DEFAULT_SECONDS,
        *,
        validate_runtime_prerequisites: bool = True,
    ) -> dict[str, Any]:
        """Atomically lease one fixed archive job and create a leased run.

        ``validate_runtime_prerequisites=False`` is reserved for scheduled
        runs.  Fixed job contract, enabled state, filters, and retry policy
        validation remain lease gates; only credential-reference presence is
        deferred to the real provider execution.
        """
        self._validate_trigger_type(trigger_type)
        self._validate_lease_duration(lease_seconds)
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            job = conn.execute(
                """
                SELECT id, job_key, source_type, report_type, template_key, archived_at,
                       project_status_deliverable_id, enabled, credential_ref,
                       filters_json, output_subdir, output_directory, retry_policy_json,
                       lease_token, lease_expires_at
                FROM scheduled_archive_jobs WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
            if job is None:
                raise KeyError(job_id)
            template_key = str(job["template_key"] or job["job_key"])
            contract = ARCHIVE_JOB_CONTRACTS.get(template_key)
            actual = (
                str(job["source_type"]),
                contract[1] if contract else str(job["report_type"]),
                job["project_status_deliverable_id"],
            )
            if contract is None or actual != contract or job["archived_at"] is not None:
                raise ArchiveJobNotReadyError(
                    "archive job does not match a fixed approved contract",
                    reason="contract_mismatch",
                )
            if trigger_type != "sync_now" and not job["enabled"]:
                raise ArchiveJobNotReadyError(
                    "archive job is not enabled", reason="job_disabled"
                )
            if validate_runtime_prerequisites and not str(job["credential_ref"] or "").strip():
                raise ArchiveJobNotReadyError(
                    "archive job credential reference is not configured",
                    reason="credential_not_configured",
                )
            filters = _json_loads_or_none(job["filters_json"])
            retry_policy = _json_loads_or_none(job["retry_policy_json"])
            if not isinstance(filters, dict):
                raise ArchiveJobNotReadyError(
                    "archive job filters are invalid", reason="filters_invalid"
                )
            if (
                template_key == "tdc_data_model"
                and filters.get("syncScope") == "watchlist"
                and not filters.get("watchlist")
            ):
                raise ArchiveJobNotReadyError(
                    "data model watchlist is empty", reason="watchlist_empty"
                )
            try:
                retry_policy = _normalize_archive_retry_policy(retry_policy)
            except (TypeError, ValueError):
                raise ArchiveJobNotReadyError(
                    "archive job retry policy is invalid", reason="retry_policy_invalid"
                )

            now = self._utc_now(conn)
            lease_token = secrets.token_urlsafe(32)
            cursor = conn.execute(
                f"""
                UPDATE scheduled_archive_jobs
                SET lease_token = ?, lease_acquired_at = ?,
                    lease_expires_at = {_utc_offset_sql(lease_seconds)},
                    sync_state = 'running', last_attempt_at = ?,
                    updated_at = {_UTC_NOW_SQL}
                WHERE id = ? AND (
                    lease_token IS NULL OR lease_expires_at IS NULL
                    OR lease_expires_at <= ?
                )
                """,
                (lease_token, now, now, job_id, now),
            )
            if cursor.rowcount != 1:
                raise ArchiveLeaseBusyError(
                    "archive job already has an unexpired lease"
                )
            conn.execute(
                """
                UPDATE scheduled_archive_runs
                SET run_state = 'expired', finished_at = ?
                WHERE job_id = ? AND run_state IN ('leased', 'running')
                """,
                (now, job_id),
            )
            run_id = conn.execute(
                """
                INSERT INTO scheduled_archive_runs
                    (job_id, job_key, trigger_type, run_state, attempt, created_at)
                VALUES (?, ?, ?, 'leased', 1, ?)
                """,
                (job_id, job["job_key"], trigger_type, now),
            ).lastrowid
            expires = conn.execute(
                "SELECT lease_expires_at FROM scheduled_archive_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            return {
                "job_id": job_id,
                "job_key": template_key,
                "task_key": str(job["job_key"]),
                "source_type": str(job["source_type"]),
                "report_type": contract[1],
                "project_status_deliverable_id": job[
                    "project_status_deliverable_id"
                ],
                "filters": filters,
                "output_subdir": str(job["output_subdir"] or ""),
                "output_directory": str(job["output_directory"] or ""),
                "retry_policy": retry_policy,
                "run_id": int(run_id),
                "lease_token": lease_token,
                "lease_expires_at": expires["lease_expires_at"],
                "acquired_at": now,
            }

    @observed("db.start_archive_run")
    def start_archive_run(
        self, job_id: int, run_id: int, lease_token: str
    ) -> None:
        """Move a lease-owned archive run from leased to running."""
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._assert_archive_lease_holder(
                conn, job_id, run_id, lease_token
            )
            now = self._utc_now(conn)
            cursor = conn.execute(
                """
                UPDATE scheduled_archive_runs
                SET run_state = 'running', started_at = ?
                WHERE id = ? AND job_id = ? AND run_state = 'leased'
                """,
                (now, run_id, job_id),
            )
            if cursor.rowcount != 1:
                raise ArchiveLeaseLostError("archive run is not leased")

    @observed("db.renew_archive_job_lease")
    def renew_archive_job_lease(
        self,
        job_id: int,
        run_id: int,
        lease_token: str,
        lease_seconds: int = SYNC_LEASE_DEFAULT_SECONDS,
    ) -> str:
        """Atomically extend an active archive lease owned by one run."""
        self._validate_lease_duration(lease_seconds)
        if (
            not isinstance(job_id, int)
            or isinstance(job_id, bool)
            or not isinstance(run_id, int)
            or isinstance(run_id, bool)
            or not isinstance(lease_token, str)
            or not lease_token
        ):
            raise ValueError("archive lease identity is invalid")
        with self.get_connection() as conn:
            cursor = conn.execute(
                f"""
                UPDATE scheduled_archive_jobs
                SET lease_expires_at = {_utc_offset_sql(lease_seconds)},
                    updated_at = {_UTC_NOW_SQL}
                WHERE id = ?
                  AND lease_token = ?
                  AND lease_expires_at > {_UTC_NOW_SQL}
                  AND EXISTS (
                      SELECT 1
                      FROM scheduled_archive_runs r
                      WHERE r.id = ? AND r.job_id = scheduled_archive_jobs.id
                        AND r.run_state IN ('leased', 'running')
                  )
                """,
                (job_id, lease_token, run_id),
            )
            if cursor.rowcount != 1:
                raise ArchiveLeaseLostError("archive lease expired or token/run mismatch")
            row = conn.execute(
                "SELECT lease_expires_at FROM scheduled_archive_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None or not row["lease_expires_at"]:
                raise ArchiveLeaseLostError("archive lease renewal did not persist")
            return str(row["lease_expires_at"])

    @observed("db.finalize_archive_run")
    def finalize_archive_run(
        self,
        job_id: int,
        run_id: int,
        lease_token: str,
        final_state: str,
        *,
        record_count: int | None = None,
        artifacts: Sequence[dict[str, Any]] = (),
        result_summary: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Validate metadata and atomically finalize a lease-owned archive run."""
        allowed = {"success", "partial", "failed", "needs_attention"}
        if final_state not in allowed:
            raise ValueError("invalid archive final state")
        if record_count is not None and (
            not isinstance(record_count, int)
            or isinstance(record_count, bool)
            or record_count < 0
        ):
            raise ValueError("record_count must be a non-negative int or None")
        for artifact in artifacts:
            self._validate_artifact_metadata(artifact)
        if final_state == "success" and not artifacts:
            raise ValueError("successful archive run requires artifacts")

        summary = (
            redact_sensitive_text(result_summary, limit=1000)
            if result_summary
            else None
        )
        safe_error_type = (
            redact_sensitive_text(error_type, limit=200)
            if error_type
            else None
        )
        safe_error = (
            redact_sensitive_text(error_message, limit=1000)
            if error_message
            else None
        )
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._assert_archive_lease_holder(
                conn, job_id, run_id, lease_token
            )
            now = self._utc_now(conn)
            for artifact in artifacts:
                conn.execute(
                    """
                    INSERT INTO scheduled_archive_artifacts
                        (run_id, artifact_type, relative_path, display_name,
                         size_bytes, sha256, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        artifact["artifact_type"],
                        artifact["relative_path"],
                        artifact["display_name"],
                        artifact.get("size_bytes"),
                        artifact.get("sha256"),
                        now,
                    ),
                )
            cursor = conn.execute(
                """
                UPDATE scheduled_archive_runs
                SET run_state = ?, record_count = ?, result_summary = ?,
                    error_type = ?, error_message = ?, finished_at = ?
                WHERE id = ? AND job_id = ?
                  AND run_state IN ('leased', 'running')
                """,
                (
                    final_state, record_count, summary, safe_error_type,
                    safe_error, now, run_id, job_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ArchiveLeaseLostError("archive run is no longer active")
            last_success = ", last_success_at = ?" if final_state == "success" else ""
            job_state = (
                "needs_attention" if final_state == "partial" else final_state
            )
            params: list[Any] = [
                job_state, safe_error_type, safe_error, now,
            ]
            if final_state == "success":
                params.append(now)
            params.extend([job_id, lease_token])
            cursor = conn.execute(
                f"""
                UPDATE scheduled_archive_jobs
                SET sync_state = ?, last_error_type = ?,
                    last_error_message = ?, updated_at = ?,
                    lease_token = NULL, lease_acquired_at = NULL,
                    lease_expires_at = NULL{last_success}
                WHERE id = ? AND lease_token = ?
                """,
                params,
            )
            if cursor.rowcount != 1:
                raise ArchiveLeaseLostError("archive job lease was lost")

    @staticmethod
    def _assert_archive_lease_holder(
        conn: sqlite3.Connection,
        job_id: int,
        run_id: int,
        lease_token: str,
    ) -> None:
        row = conn.execute(
            f"""
            SELECT 1
            FROM scheduled_archive_jobs j
            INNER JOIN scheduled_archive_runs r
                ON r.job_id = j.id AND r.id = ?
            WHERE j.id = ? AND j.lease_token = ?
              AND j.lease_expires_at > {_UTC_NOW_SQL}
              AND r.run_state IN ('leased', 'running')
            """,
            (run_id, job_id, lease_token),
        ).fetchone()
        if row is None:
            raise ArchiveLeaseLostError(
                "archive lease expired or token/run mismatch"
            )

    def list_archive_runs(
        self, job_key: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return sanitized archive run history without lease or credential data."""
        bounded = max(1, min(int(limit), 500))
        sql = """
            SELECT id, job_id, job_key, trigger_type, run_state, attempt,
                   record_count, result_summary, error_type, error_message,
                   created_at, started_at, finished_at
            FROM scheduled_archive_runs
        """
        params: tuple[Any, ...]
        if job_key:
            sql += " WHERE job_key = ? ORDER BY id DESC LIMIT ?"
            params = (job_key, bounded)
        else:
            sql += " ORDER BY id DESC LIMIT ?"
            params = (bounded,)
        with self.get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_archive_run(self, run_id: int) -> dict[str, Any] | None:
        """Return one sanitized archive run, or None when it does not exist."""
        if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1:
            return None
        with self.get_connection() as conn:
            row = conn.execute(
                """
                SELECT id, job_id, job_key, trigger_type, run_state, attempt,
                       record_count, result_summary, error_type, error_message,
                       created_at, started_at, finished_at
                FROM scheduled_archive_runs WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_archive_artifacts(self, run_id: int) -> list[dict[str, Any]]:
        """Return artifact metadata; never resolve or expose a server absolute path."""
        with self.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, run_id, artifact_type, relative_path, display_name,
                       size_bytes, sha256, created_at
                FROM scheduled_archive_artifacts
                WHERE run_id = ? ORDER BY id
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]
