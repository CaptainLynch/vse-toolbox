# -*- coding: utf-8 -*-
"""交付物自动同步：绑定、租约、运行、产物与映射观测的数据访问（DatabaseManager 的领域分片）。

由 core/db_manager.py 按领域拆出；``DatabaseManager`` 继承本类，对外接口不变。
本类依赖 ``get_connection`` 等由 DatabaseManager 提供的方法，不单独实例化。
"""

from core.db_common import (  # noqa: F401
    _json_dumps_local,
    _json_loads_or_none,
    _LOCAL_NOW_SQL,
    _sanitize_json,
    _UTC_NOW_SQL,
    _utc_offset_sql,
    Any,
    observed,
    secrets,
    Sequence,
    sqlite3,
    SYNC_LEASE_DEFAULT_SECONDS,
    SYNC_LEASE_MAX_SECONDS,
    SYNC_LEASE_MIN_SECONDS,
    SyncBindingNotReadyError,
    SyncLeaseBusyError,
    SyncLeaseLostError,
)


class SyncRunRepo:
    @staticmethod
    def _utc_now(conn: sqlite3.Connection) -> str:
        """读取数据库生成的当前 UTC 时间戳，确保与租约 SQL 时钟一致。"""
        row = conn.execute("SELECT " + _UTC_NOW_SQL).fetchone()
        return str(row[0])

    @staticmethod
    def _validate_lease_duration(lease_seconds: int) -> None:
        if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool):
            raise TypeError("lease_seconds must be an int")
        if not (SYNC_LEASE_MIN_SECONDS <= lease_seconds <= SYNC_LEASE_MAX_SECONDS):
            raise ValueError(
                f"lease_seconds must be between {SYNC_LEASE_MIN_SECONDS} "
                f"and {SYNC_LEASE_MAX_SECONDS}"
            )

    @staticmethod
    def _validate_trigger_type(trigger_type: str) -> None:
        if trigger_type not in ("sync_now", "scheduled"):
            raise ValueError(f"unsupported trigger_type: {trigger_type}")

    @staticmethod
    def _validate_run_state(run_state: str) -> None:
        if run_state not in (
            "leased",
            "running",
            "success",
            "partial",
            "failed",
            "needs_attention",
            "expired",
        ):
            raise ValueError(f"unsupported run_state: {run_state}")

    @staticmethod
    def _validate_artifact_metadata(artifact: dict[str, Any]) -> None:
        relative = artifact.get("relative_path")
        if not isinstance(relative, str) or not relative:
            raise ValueError("artifact relative_path is required")
        # 禁止绝对路径与目录穿越：不允许盘符前缀、前导斜杠或 ".." 段。
        norm = relative.replace("\\", "/")
        if (
            len(norm) >= 2 and norm[1] == ":"
        ) or norm.startswith("/"):
            raise ValueError("artifact relative_path must be a relative path")
        segments = norm.split("/")
        if any(segment in ("", ".", "..") for segment in segments):
            raise ValueError("artifact relative_path must not traverse parent directories")
        reserved = {
            "CON", "PRN", "AUX", "NUL",
            *(f"COM{number}" for number in range(1, 10)),
            *(f"LPT{number}" for number in range(1, 10)),
        }
        if any(
            ":" in segment
            or segment.rstrip(" .") != segment
            or segment.split(".", 1)[0].upper() in reserved
            for segment in segments
        ):
            raise ValueError("artifact relative_path contains an unsafe segment")
        artifact_type = artifact.get("artifact_type")
        if not isinstance(artifact_type, str) or not artifact_type.strip():
            raise ValueError("artifact artifact_type is required")
        display_name = artifact.get("display_name")
        if not isinstance(display_name, str) or not display_name.strip():
            raise ValueError("artifact display_name is required")
        size_bytes = artifact.get("size_bytes")
        if size_bytes is not None and (
            not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes < 0
        ):
            raise ValueError("artifact size_bytes must be a non-negative int or None")
        sha256 = artifact.get("sha256")
        if sha256 is not None and (not isinstance(sha256, str) or not sha256.strip()):
            raise ValueError("artifact sha256 must be a non-empty string or None")

    @observed("db.acquire_sync_lease")
    def acquire_sync_lease(
        self,
        binding_id: int,
        trigger_type: str,
        lease_seconds: int = SYNC_LEASE_DEFAULT_SECONDS,
        *,
        validate_runtime_prerequisites: bool = True,
        expected_sync_config_revision: int | None = None,
    ) -> dict[str, Any]:
        """
        原子获取同步租约并创建一条 leased run。

        前置校验：binding 存在、enabled=1、mode 为 automatic/hybrid、
        source_type 非 none。默认还校验 external_key、mapping/match rule 和凭据；
        定时运行可关闭这组运行时前置校验，让连接器在真实执行中给出结果。

        若存在未过期租约，获取失败且不产生新 run（SyncLeaseBusyError）。
        若租约已过期，将旧的活动 run 标记为 expired，再抢占写入新租约。

        返回最小内部 Lease 对象（含 run_id、lease_token、expires_at、
        deliverable_id、phase_id、attempt）。lease_token 不得记录到日志、
        审计或 Web 响应。
        """
        self._validate_trigger_type(trigger_type)
        self._validate_lease_duration(lease_seconds)

        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            binding = conn.execute(
                """
                SELECT b.id, b.deliverable_id, b.mode, b.source_type, b.enabled,
                       b.external_key, b.match_rule_json, b.mapping_json,
                       b.cursor_json, b.credential_ref, b.sync_config_revision,
                       b.lease_token, b.lease_expires_at, b.retry_policy_json,
                       b.sync_state, d.phase_id, d.updated_at AS deliverable_updated_at
                FROM project_status_update_bindings b
                INNER JOIN project_status_deliverables d ON d.id = b.deliverable_id
                WHERE b.id = ?
                """,
                (binding_id,),
            ).fetchone()
            if binding is None:
                raise KeyError(binding_id)
            if (
                expected_sync_config_revision is not None
                and int(binding["sync_config_revision"] or 0) != int(expected_sync_config_revision)
            ):
                raise SyncBindingNotReadyError(
                    "binding configuration changed since listing; lease acquisition rejected"
                )
            if not binding["enabled"]:
                raise SyncBindingNotReadyError("binding is not enabled")
            if binding["mode"] not in ("automatic", "hybrid"):
                raise SyncBindingNotReadyError(
                    f"binding mode '{binding['mode']}' does not allow scheduled sync"
                )
            if binding["source_type"] == "none":
                raise SyncBindingNotReadyError("binding source_type is 'none'")
            if validate_runtime_prerequisites:
                # 聚合绑定（按车型聚合，无单记录稳定键）豁免外部稳定键
                # （GPT 终审 P1：租约入口此前阻断聚合首次同步）。
                match_rule = _json_loads_or_none(binding["match_rule_json"])
                aggregate_mode = isinstance(match_rule, dict) and match_rule.get("aggregate") is True
                if not aggregate_mode and not binding["external_key"]:
                    raise SyncBindingNotReadyError("binding external_key is not confirmed")
                mapping = _json_loads_or_none(binding["mapping_json"])
                if not isinstance(match_rule, dict) or not match_rule:
                    raise SyncBindingNotReadyError("binding match rule is empty")
                if not isinstance(mapping, dict) or not mapping:
                    raise SyncBindingNotReadyError("binding mapping is empty")
                if not str(binding["credential_ref"] or "").strip():
                    raise SyncBindingNotReadyError(
                        "credential reference is not configured"
                    )

            now = self._utc_now(conn)
            lease_token = secrets.token_urlsafe(32)
            expires_sql = _utc_offset_sql(lease_seconds)

            # 原子抢占租约：UPDATE 的 WHERE 条件同时充当互斥锁。
            # 仅当当前无租约或租约已过期时才能更新成功（rowcount==1）。
            # 两个并发运行器只有一个能拿到 rowcount==1，另一个得到 0 → busy。
            # 这依赖 SQLite 写锁串行化该 UPDATE，无需显式 BEGIN IMMEDIATE。
            cursor = conn.execute(
                f"""
                UPDATE project_status_update_bindings
                SET lease_token = ?,
                    lease_acquired_at = ?,
                    lease_expires_at = {expires_sql},
                    sync_state = 'running',
                    last_attempt_at = ?,
                    updated_at = {_LOCAL_NOW_SQL}
                WHERE id = ?
                  AND (
                      lease_token IS NULL
                      OR lease_expires_at IS NULL
                      OR lease_expires_at <= ?
                  )
                """,
                (
                    lease_token,
                    now,
                    now,
                    binding_id,
                    now,
                ),
            )
            if cursor.rowcount != 1:
                raise SyncLeaseBusyError("binding already has an unexpired lease")

            # 租约获取成功后，回收过期租约对应的旧 run（标记为 expired）。
            conn.execute(
                """
                UPDATE project_status_sync_runs
                SET run_state = 'expired', finished_at = ?
                WHERE binding_id = ? AND run_state IN ('leased', 'running')
                """,
                (now, binding_id),
            )

            # M2A：每次独立 run_once 调用只尝试一次，attempt 固定为 1。
            # retry_policy_json.max_attempts > 1 的重试语义尚未实现，
            # 留待重试策略获批后设计。
            attempt = 1

            run_cursor = conn.execute(
                """
                INSERT INTO project_status_sync_runs
                    (binding_id, deliverable_id, trigger_type, run_state, attempt,
                     sync_config_revision, created_at)
                VALUES (?, ?, ?, 'leased', ?, ?, ?)
                """,
                (binding_id, binding["deliverable_id"], trigger_type, attempt,
                 int(binding["sync_config_revision"] or 0), now),
            )
            run_id = run_cursor.lastrowid

            expires_row = conn.execute(
                "SELECT lease_expires_at FROM project_status_update_bindings WHERE id = ?",
                (binding_id,),
            ).fetchone()
            return {
                "binding_id": binding_id,
                "sync_config_revision": int(binding["sync_config_revision"] or 0),
                "run_id": run_id,
                "lease_token": lease_token,
                "lease_expires_at": expires_row["lease_expires_at"],
                "deliverable_id": binding["deliverable_id"],
                "phase_id": binding["phase_id"],
                "attempt": attempt,
                "acquired_at": now,
                "binding_snapshot": dict(binding),
            }

    @observed("db.start_sync_run")
    def start_sync_run(
        self,
        binding_id: int,
        run_id: int,
        lease_token: str,
    ) -> None:
        """
        受 token 保护的 leased → running 转换。

        旧 token、错误 run_id 或已过期 lease 均不得启动。
        """
        with self.get_connection() as conn:
            self._assert_lease_holder(conn, binding_id, run_id, lease_token)
            now = self._utc_now(conn)
            conn.execute(
                """
                UPDATE project_status_sync_runs
                SET run_state = 'running', started_at = ?
                WHERE id = ? AND run_state = 'leased'
                """,
                (now, run_id),
            )

    @staticmethod
    def _assert_lease_holder(
        conn: sqlite3.Connection,
        binding_id: int,
        run_id: int,
        lease_token: str,
    ) -> None:
        """验证 binding 当前租约与 run 匹配且未过期，否则 SyncLeaseLostError。"""
        if not isinstance(lease_token, str) or not lease_token:
            raise SyncLeaseLostError("lease_token is required")
        binding = conn.execute(
            """
            SELECT lease_token, lease_expires_at
            FROM project_status_update_bindings
            WHERE id = ?
            """,
            (binding_id,),
        ).fetchone()
        if binding is None:
            raise SyncLeaseLostError("binding not found")
        if binding["lease_token"] != lease_token:
            raise SyncLeaseLostError("lease token mismatch")
        expires = binding["lease_expires_at"]
        now_row = conn.execute("SELECT " + _UTC_NOW_SQL).fetchone()
        if expires is None or expires <= str(now_row[0]):
            raise SyncLeaseLostError("lease expired")
        run = conn.execute(
            """
            SELECT id, run_state
            FROM project_status_sync_runs
            WHERE id = ? AND binding_id = ?
            """,
            (run_id, binding_id),
        ).fetchone()
        if run is None:
            raise SyncLeaseLostError("run not found")
        if run["run_state"] in ("success", "partial", "failed", "needs_attention", "expired"):
            raise SyncLeaseLostError(f"run already finalized as {run['run_state']}")

    @observed("db.finalize_sync_success")
    def finalize_sync_success(
        self,
        binding_id: int,
        run_id: int,
        lease_token: str,
        deliverable_values: dict[str, object],
        expected_updated_at: str,
        phase_id: str,
        skipped_fields: dict[str, str],
        external_version: str,
        proposed_changes_json: str,
        applied_changes_json: str,
        trigger_type: str,
        source_type: str,
        result_summary: str,
        artifacts: Sequence[dict[str, Any]] | None = None,
        aggregate_mode: bool = False,
    ) -> dict[str, Any]:
        """
        单事务原子完成成功提交：

        - 再次验证 binding_id/run_id/lease_token 仍匹配且租约有效；
        - 验证 cursor/external_version（重复版本 → skipped，不更新业务行）；
        - 验证 snapshot 的 expected_updated_at 乐观锁；
        - 检查字段白名单和 field authority；
        - 更新允许自动写入且未被人工锁定的字段；
        - 写 audit、推进 cursor_json/last_success_at、更新 binding sync_state；
        - 更新 sync_runs 最终状态、写 artifact 元数据、清空当前租约。

        任一步骤失败，整个事务回滚。

        Returns:
            dict 含 updated_at（新版本或原值）和 applied_fields（实际应用字段元组）。
        """
        self._validate_trigger_type(trigger_type)
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._assert_lease_holder(conn, binding_id, run_id, lease_token)

            binding = conn.execute(
                """
                SELECT external_key, cursor_json, sync_config_revision
                FROM project_status_update_bindings
                WHERE id = ?
                """,
                (binding_id,),
            ).fetchone()
            assert binding is not None

            run_row = conn.execute(
                """
                SELECT run_state, deliverable_id, sync_config_revision
                FROM project_status_sync_runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
            assert run_row is not None
            deliverable_id = run_row["deliverable_id"]

            # 换绑校验（GPT 终审任务 2c）：运行捕获的修订号与绑定当前修订号
            # 不一致 → 在途旧运行不得写业务行/游标/缓存；审计后转入
            # needs_attention 并释放租约（不得标记成功）。
            if int(run_row["sync_config_revision"] or 0) != int(
                binding["sync_config_revision"] or 0
            ):
                now = self._utc_now(conn)
                self._insert_audit_row(
                    conn,
                    deliverable_id,
                    trigger_type,
                    source_type,
                    external_version,
                    proposed_changes_json,
                    "{}",
                    _sanitize_json({"*": "binding config superseded"}),
                    "skipped",
                    None,
                )
                self._prune_project_status_audit(conn, deliverable_id)
                self._finalize_run_and_release(
                    conn,
                    binding_id,
                    run_id,
                    "needs_attention",
                    result_summary,
                    "binding_config_superseded",
                    "binding config changed while sync was in flight",
                    now,
                    sync_state="needs_attention",
                    external_version=external_version,
                    expected_lease_token=lease_token,
                )
                return {
                    "updated_at": None,
                    "applied_fields": (),
                    "superseded": True,
                }

            # 幂等：external_version 已处理 → skipped，不更新业务行但推进 run。
            # cursor 中的 processed_versions 保留处理顺序（非字典序），
            # malformed cursor 安全降级为空列表。
            current_cursor = _json_loads_or_none(binding["cursor_json"])
            processed_versions: list[str] = []
            processed_set: set[str] = set()
            if isinstance(current_cursor, dict):
                versions = current_cursor.get("processed_versions")
                if isinstance(versions, list):
                    for v in versions:
                        text = str(v)
                        if text not in processed_set:
                            processed_versions.append(text)
                            processed_set.add(text)

            now = self._utc_now(conn)

            authorities = {
                str(row["field_name"]): {
                    "authority": str(row["authority"]),
                    "locked_at": row["locked_at"],
                }
                for row in conn.execute(
                    """
                    SELECT field_name, authority, locked_at
                    FROM project_status_field_authority
                    WHERE deliverable_id = ?
                    """,
                    (deliverable_id,),
                )
            }

            valid_api_fields = {
                "owner",
                "plannedDate",
                "note",
            }
            unknown = set(deliverable_values) - valid_api_fields
            if unknown:
                raise ValueError(
                    f"connector proposed unsupported fields: {sorted(unknown)}"
                )

            # 过滤出可应用字段：authority=automatic 且 locked_at IS NULL。
            db_field_map = {
                "owner": "owner",
                "plannedDate": "planned_date",
                "note": "remark",
            }
            applicable: dict[str, object] = {}
            skipped: dict[str, str] = dict(skipped_fields)
            for api_name, value in deliverable_values.items():
                db_name = db_field_map[api_name]
                auth = authorities.get(db_name)
                if auth is None:
                    skipped[api_name] = "no field authority configured"
                    continue
                if auth["authority"] == "manual" or auth["locked_at"] is not None:
                    skipped[api_name] = "field is manually locked"
                    continue
                applicable[db_name] = value

            applied_any = bool(applicable)
            if aggregate_mode:
                # 聚合去重（GPT 终审任务 4）：内容摘要仅与当前绑定修订下
                # 最近成功应用的内容版本比较，A→B→A 的第三次正常应用。
                last_applied_version = (
                    current_cursor.get("aggregate_last_content_version")
                    if isinstance(current_cursor, dict)
                    else None
                )
                already_processed = (
                    last_applied_version is not None
                    and last_applied_version == external_version
                )
            else:
                already_processed = external_version in processed_set

            if already_processed:
                # 幂等跳过：不更新业务行，audit result=skipped，run_state=success。
                self._insert_audit_row(
                    conn,
                    deliverable_id,
                    trigger_type,
                    source_type,
                    external_version,
                    proposed_changes_json,
                    "{}",
                    _sanitize_json(skipped),
                    "skipped",
                    None,
                )
                self._prune_project_status_audit(conn, deliverable_id)
                self._finalize_run_and_release(
                    conn,
                    binding_id,
                    run_id,
                    "success",
                    result_summary,
                    None,
                    None,
                    now,
                    external_version=external_version,
                )
                self._write_artifacts(conn, run_id, artifacts)
                return {"updated_at": expected_updated_at, "applied_fields": ()}

            # 应用字段更新（乐观锁）。
            updated_at = expected_updated_at
            if applied_any:
                updated_at = self._update_project_status_deliverable_row(
                    conn,
                    deliverable_id,
                    phase_id,
                    applicable,
                    expected_updated_at,
                )
                conn.execute(
                    "UPDATE project_status_phases SET updated_at = ? WHERE id = ?",
                    (updated_at, phase_id),
                )

            audit_result = "applied" if applied_any else "skipped"
            applied_json = _sanitize_json(
                {
                    api_name: applicable[db_name]
                    for api_name, db_name in db_field_map.items()
                    if db_name in applicable
                }
            )
            self._insert_audit_row(
                conn,
                deliverable_id,
                trigger_type,
                source_type,
                external_version,
                proposed_changes_json,
                applied_json,
                _sanitize_json(skipped),
                audit_result,
                None,
            )
            self._prune_project_status_audit(conn, deliverable_id)

            if aggregate_mode:
                # 聚合去重基线仅在全部字段成功应用时推进（GPT 终审任务 4）：
                # 部分/零字段应用必须使基线失效（置为 None 或 partial，P1-3），
                # 绝不能保留旧基线，否则当来源回到旧版本时将被错误去重，导致数据永久不一致。
                if applied_any and not skipped:
                    next_cursor = {"aggregate_last_content_version": external_version}
                else:
                    next_cursor = {"aggregate_last_content_version": None, "partial": True}
            else:
                # 推进 cursor：保留处理顺序，新版本追加到末尾，只留最后 100 条。
                if external_version in processed_set:
                    next_processed = processed_versions
                else:
                    next_processed = processed_versions + [external_version]
                next_cursor = {"processed_versions": next_processed[-100:]}
            conn.execute(
                f"""
                UPDATE project_status_update_bindings
                SET cursor_json = ?,
                    last_success_at = ?,
                    sync_state = ?,
                    updated_at = {_LOCAL_NOW_SQL}
                WHERE id = ?
                """,
                (
                    _json_dumps_local(next_cursor),
                    now,
                    "success",
                    binding_id,
                ),
            )

            # 有跳过字段（含人工锁定）时 run 为 partial；全部应用 → success。
            final_run_state = "partial" if skipped else "success"

            self._finalize_run_and_release(
                conn,
                binding_id,
                run_id,
                final_run_state,
                result_summary,
                None,
                None,
                now,
                external_version=external_version,
            )
            self._write_artifacts(conn, run_id, artifacts)
            applied_api_fields = tuple(
                sorted(
                    api_name
                    for api_name, db_name in db_field_map.items()
                    if db_name in applicable
                )
            )
            return {
                "updated_at": updated_at,
                "applied_fields": applied_api_fields,
                "skipped_fields": dict(skipped),
            }

    @observed("db.finalize_sync_needs_attention")
    def finalize_sync_needs_attention(
        self,
        binding_id: int,
        run_id: int,
        lease_token: str,
        error_type: str,
        sanitized_message: str,
        result_summary: str,
    ) -> None:
        """
        not_found/ambiguous 或候选结构非法时原子结束运行。

        不修改 project_status_deliverables，不推进 cursor/last_success_at。
        """
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._assert_lease_holder(conn, binding_id, run_id, lease_token)
            now = self._utc_now(conn)
            deliverable_id_row = conn.execute(
                "SELECT deliverable_id FROM project_status_sync_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            assert deliverable_id_row is not None
            self._finalize_run_and_release(
                conn,
                binding_id,
                run_id,
                "needs_attention",
                result_summary,
                error_type,
                sanitized_message,
                now,
                sync_state="needs_attention",
                expected_lease_token=lease_token,
            )

    @observed("db.finalize_sync_failure")
    def finalize_sync_failure(
        self,
        binding_id: int,
        run_id: int,
        lease_token: str,
        error_type: str,
        sanitized_message: str,
        result_summary: str,
    ) -> None:
        """
        connector 异常时原子结束运行。

        不修改 project_status_deliverables，不推进 cursor/last_success_at。
        """
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._assert_lease_holder(conn, binding_id, run_id, lease_token)
            now = self._utc_now(conn)
            self._finalize_run_and_release(
                conn,
                binding_id,
                run_id,
                "failed",
                result_summary,
                error_type,
                sanitized_message,
                now,
                sync_state="failed",
                expected_lease_token=lease_token,
            )

    @observed("db.finalize_sync_conflict")
    def finalize_sync_conflict(
        self,
        binding_id: int,
        run_id: int,
        lease_token: str,
        deliverable_id: str,
        external_version: str,
        proposed_changes_json: str,
        source_type: str,
        trigger_type: str,
        sanitized_message: str,
    ) -> None:
        """
        乐观锁冲突时原子结束运行：写脱敏 conflict 审计，不覆盖人工更新，
        不推进 cursor，释放当前租约。
        """
        self._validate_trigger_type(trigger_type)
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._assert_lease_holder(conn, binding_id, run_id, lease_token)
            now = self._utc_now(conn)
            self._insert_audit_row(
                conn,
                deliverable_id,
                trigger_type,
                source_type,
                external_version,
                proposed_changes_json,
                "{}",
                "{}",
                "conflict",
                sanitized_message,
            )
            self._prune_project_status_audit(conn, deliverable_id)
            self._finalize_run_and_release(
                conn,
                binding_id,
                run_id,
                "failed",
                "optimistic lock conflict",
                "conflict",
                sanitized_message,
                now,
                sync_state="failed",
                expected_lease_token=lease_token,
            )

    @staticmethod
    def _finalize_run_and_release(
        conn: sqlite3.Connection,
        binding_id: int,
        run_id: int,
        run_state: str,
        result_summary: str,
        error_type: str | None,
        error_message: str | None,
        finished_at: str,
        sync_state: str = "success",
        external_version: str | None = None,
        expected_lease_token: str | None = None,
    ) -> None:
        """更新 sync_runs 最终状态并清空 binding 当前租约。"""
        SyncRunRepo._validate_run_state(run_state)
        conn.execute(
            """
            UPDATE project_status_sync_runs
            SET run_state = ?, result_summary = ?, error_type = ?,
                error_message = ?, finished_at = ?, external_version = ?
            WHERE id = ?
            """,
            (run_state, result_summary, error_type, error_message,
             finished_at, external_version, run_id),
        )
        where_clause = "WHERE id = ?"
        params: list[Any] = [sync_state, binding_id]
        if expected_lease_token is not None:
            where_clause += " AND (lease_token IS NULL OR lease_token = ?)"
            params.append(expected_lease_token)
        conn.execute(
            f"""
            UPDATE project_status_update_bindings
            SET lease_token = NULL,
                lease_acquired_at = NULL,
                lease_expires_at = NULL,
                sync_state = ?,
                updated_at = {_LOCAL_NOW_SQL}
            {where_clause}
            """,
            params,
        )

    @staticmethod
    def _write_artifacts(
        conn: sqlite3.Connection,
        run_id: int,
        artifacts: Sequence[dict[str, Any]] | None,
    ) -> None:
        if not artifacts:
            return
        for artifact in artifacts:
            SyncRunRepo._validate_artifact_metadata(artifact)
            conn.execute(
                """
                INSERT INTO project_status_sync_artifacts
                    (run_id, artifact_type, relative_path, display_name,
                     size_bytes, sha256)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    artifact["artifact_type"],
                    artifact["relative_path"],
                    artifact["display_name"],
                    artifact.get("size_bytes"),
                    artifact.get("sha256"),
                ),
            )

    @staticmethod
    def _insert_audit_row(
        conn: sqlite3.Connection,
        deliverable_id: str,
        trigger_type: str,
        source_type: str,
        external_version: str | None,
        proposed_changes_json: str,
        applied_changes_json: str,
        skipped_fields_json: str,
        result: str,
        error_summary: str | None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO project_status_update_audit
                (deliverable_id, trigger_type, source_type, external_version,
                 proposed_changes_json, applied_changes_json, skipped_fields_json,
                 result, error_summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                deliverable_id,
                trigger_type,
                source_type,
                external_version,
                proposed_changes_json,
                applied_changes_json,
                skipped_fields_json,
                result,
                error_summary,
            ),
        )

    def get_sync_run(self, run_id: int) -> dict[str, Any] | None:
        """读取一条运行记录（脱敏视图），不存在返回 None。"""
        with self.get_connection() as conn:
            row = conn.execute(
                """
                SELECT id, binding_id, deliverable_id, trigger_type, run_state,
                       attempt, external_version, result_summary, error_type,
                       error_message, created_at, started_at, finished_at
                FROM project_status_sync_runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_sync_artifacts(self, run_id: int) -> list[dict[str, Any]]:
        """读取一次运行的全部 artifact 元数据。"""
        with self.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, run_id, artifact_type, relative_path, display_name,
                       size_bytes, sha256, created_at
                FROM project_status_sync_artifacts
                WHERE run_id = ?
                ORDER BY id
                """,
                (run_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_sync_runs(
        self, deliverable_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return bounded run history without binding secrets or raw payloads."""
        bounded = max(1, min(int(limit), 500))
        sql = """
            SELECT id, binding_id, deliverable_id, trigger_type, run_state,
                   attempt, external_version, result_summary, error_type,
                   error_message, created_at, started_at, finished_at
            FROM project_status_sync_runs
        """
        params: tuple[Any, ...]
        if deliverable_id:
            sql += " WHERE deliverable_id = ?"
            params = (deliverable_id, bounded)
        else:
            params = (bounded,)
        sql += " ORDER BY id DESC LIMIT ?"
        with self.get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_sync_binding_by_deliverable(
        self,
        deliverable_id: str,
    ) -> dict[str, Any] | None:
        """读取交付物的绑定记录（内部视图，含调度列）。"""
        with self.get_connection() as conn:
            row = conn.execute(
                """
                SELECT id, deliverable_id, mode, source_type, enabled,
                       external_key, match_rule_json, mapping_json,
                       interval_minutes, cursor_json, credential_ref,
                       lease_token, lease_acquired_at, lease_expires_at,
                       retry_policy_json, sync_state, last_attempt_at,
                       last_success_at, last_error_type, last_error_message,
                       created_at, updated_at
                FROM project_status_update_bindings
                WHERE deliverable_id = ?
                """,
                (deliverable_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_eligible_sync_bindings(
        self,
        deliverable_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        读取符合 run_once 条件的绑定，供 runner 使用。

        仅返回 enabled=1 且 mode in (automatic, hybrid) 的绑定，以 binding_id 升序。
        同时读取 deliverable 当前 updated_at、phase_id 与绑定的 last_success_at
        （调度层新鲜度跳过：last_success_at 距今不足 interval 时零网络复用快照）。
        不返回 credential_ref、lease_token 等敏感内部列。

        Args:
            deliverable_id: 若提供则精确筛选该交付物的绑定。
        """
        with self.get_connection() as conn:
            if deliverable_id is not None:
                rows = conn.execute(
                    """
                SELECT b.id, b.deliverable_id, b.source_type, b.external_key,
                       b.match_rule_json, b.mapping_json, b.cursor_json,
                       b.retry_policy_json, b.sync_state, b.sync_config_revision,
                       b.last_success_at, b.interval_minutes,
                       CASE WHEN trim(COALESCE(b.credential_ref, '')) <> ''
                            THEN 1 ELSE 0 END AS credential_configured,
                       d.phase_id, d.updated_at AS deliverable_updated_at
                FROM project_status_update_bindings b
                INNER JOIN project_status_deliverables d ON d.id = b.deliverable_id
                WHERE b.enabled = 1
                  AND b.mode IN ('automatic', 'hybrid')
                  AND b.deliverable_id = ?
                ORDER BY b.id
                    """,
                    (deliverable_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT b.id, b.deliverable_id, b.source_type, b.external_key,
                           b.match_rule_json, b.mapping_json, b.cursor_json,
                           b.retry_policy_json, b.sync_state, b.sync_config_revision,
                           b.last_success_at, b.interval_minutes,
                           CASE WHEN trim(COALESCE(b.credential_ref, '')) <> ''
                                THEN 1 ELSE 0 END AS credential_configured,
                           d.phase_id, d.updated_at AS deliverable_updated_at
                    FROM project_status_update_bindings b
                    INNER JOIN project_status_deliverables d ON d.id = b.deliverable_id
                    WHERE b.enabled = 1
                      AND b.mode IN ('automatic', 'hybrid')
                    ORDER BY b.id
                    """
                ).fetchall()
            result = [dict(row) for row in rows]
            for item in result:
                item["credential_configured"] = bool(
                    item["credential_configured"]
                )
            return result

    def get_sync_binding_credential_ref(self, binding_id: int) -> str:
        """Return the opaque credential alias for internal connector execution."""
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT credential_ref FROM project_status_update_bindings WHERE id = ?",
                (binding_id,),
            ).fetchone()
        if row is None:
            raise KeyError(binding_id)
        value = str(row["credential_ref"] or "").strip()
        if not value:
            raise SyncBindingNotReadyError("credential reference is not configured")
        return value

    def record_mapping_observation(
        self,
        deliverable_id: str,
        source_type: str,
        result_state: str,
        external_key: str | None,
        candidate_fingerprint: str | None,
        candidate_count: int,
        candidate_summary_json: str,
        field_report_json: str,
        config_signature: str | None = None,
        aggregated_candidate_json: str | None = None,
    ) -> int:
        allowed = {"matched", "not_found", "ambiguous", "missing_fields", "key_changed"}
        if result_state not in allowed:
            raise ValueError("invalid mapping observation state")
        with self.get_connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM project_status_deliverables WHERE id = ?", (deliverable_id,)
            ).fetchone()
            if exists is None:
                raise KeyError(deliverable_id)
            cursor = conn.execute(
                """
                INSERT INTO project_status_mapping_observations
                    (deliverable_id, source_type, result_state, external_key,
                     candidate_fingerprint, candidate_count,
                     candidate_summary_json, field_report_json,
                     config_signature, aggregated_candidate_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (deliverable_id, source_type, result_state, external_key,
                 candidate_fingerprint, candidate_count,
                 _sanitize_json(_json_loads_or_none(candidate_summary_json) or []),
                 _sanitize_json(_json_loads_or_none(field_report_json) or {}),
                 config_signature,
                 _sanitize_json(_json_loads_or_none(aggregated_candidate_json) or {}) if aggregated_candidate_json else None),
            )
            conn.execute(
                """
                DELETE FROM project_status_mapping_observations
                WHERE deliverable_id = ? AND id NOT IN (
                    SELECT id FROM project_status_mapping_observations
                    WHERE deliverable_id = ? ORDER BY id DESC LIMIT 100
                )
                """,
                (deliverable_id, deliverable_id),
            )
            return int(cursor.lastrowid)

    def list_mapping_observations(self, deliverable_id: str, limit: int = 20) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 100))
        with self.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, deliverable_id, source_type, result_state, external_key,
                       candidate_fingerprint, candidate_count,
                       candidate_summary_json, field_report_json,
                       config_signature, aggregated_candidate_json, created_at
                FROM project_status_mapping_observations
                WHERE deliverable_id = ? ORDER BY id DESC LIMIT ?
                """,
                (deliverable_id, bounded),
            ).fetchall()
        return [dict(row) for row in rows]

    def mapping_stability_count(
        self,
        deliverable_id: str,
        expected_signature: str | None = None,
    ) -> int:
        rows = self.list_mapping_observations(deliverable_id, 2)
        if not rows or rows[0]["result_state"] != "matched":
            return 0
        binding_source_type: str | None = None
        binding_external_key: str | None = None
        binding_rule: Any = None
        # History callers do not carry the request-local rule. Derive the
        # current binding signature here so history, preview, enable and run
        # all reject unsigned/stale evidence identically.
        with self.get_connection() as conn:
            binding = conn.execute(
                "SELECT source_type, external_key, match_rule_json "
                "FROM project_status_update_bindings WHERE deliverable_id = ?",
                (deliverable_id,),
            ).fetchone()
        if binding is not None:
            binding_source_type = str(binding["source_type"] or "").strip() or None
            binding_external_key = str(binding["external_key"] or "").strip() or None
            binding_rule = _json_loads_or_none(binding["match_rule_json"])
        request_local_signature = expected_signature is not None
        if expected_signature is None:
            from services.project_status_records import compute_config_signature

            if isinstance(binding_rule, dict):
                try:
                    expected_signature = compute_config_signature(
                        str(binding["source_type"] or ""), binding_rule
                    )
                except (TypeError, ValueError):
                    # A malformed current binding is viewable but cannot
                    # authorize historical evidence.
                    expected_signature = None
        if not isinstance(expected_signature, str) or not expected_signature.strip():
            # A missing/invalid current binding cannot authorize legacy rows
            # whose observation signature is absent.  History remains
            # readable, but its readiness counter is fail-closed.
            return 0
        # 聚合观测（无单记录稳定键）按记录集合指纹一致性计数，
        # 与启用校验共用同一规则与判定（GPT 终审 P2：ready 与校验一致）。
        from services.project_status_records import observation_is_aggregate
        aggregate_mode = observation_is_aggregate(rows[0])
        key_field = "candidate_fingerprint" if aggregate_mode else "external_key"
        source_type = rows[0]["source_type"]
        if binding_source_type is not None and source_type != binding_source_type:
            return 0
        if (
            not request_local_signature
            and isinstance(binding_rule, dict)
            and binding_rule
            and (str(rows[0]["external_key"] or "").strip() or None)
            != binding_external_key
        ):
            # History has no request-local key.  Once a real binding exists,
            # its current stable key must agree with the latest evidence;
            # aggregate bindings intentionally use NULL on both sides.
            return 0
        baseline = str(rows[0][key_field] or "")
        count = 0
        for row in rows:
            if (
                row["result_state"] != "matched"
                or str(row[key_field] or "") != baseline
                or row["source_type"] != source_type
                or observation_is_aggregate(row) != aggregate_mode
                or (
                    expected_signature is not None
                    and str(row.get("config_signature") or "").strip() != expected_signature
                )
            ):
                break
            count += 1
        return count
