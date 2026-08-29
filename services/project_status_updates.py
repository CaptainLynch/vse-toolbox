# -*- coding: utf-8 -*-
"""
services/project_status_updates.py - 项目状态交付物更新策略与审计服务
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence

from core.db_manager import (
    DatabaseManager,
    ProjectStatusConcurrentUpdateError,
    SyncBindingNotReadyError,
    SyncLeaseBusyError,
    SyncLeaseLostError,
)
from core.redaction import redact_sensitive_text

PROJECT_STATUS_PILOT_DELIVERABLE_ID = "VPI-T2-D5"
PROJECT_STATUS_AUDIT_LIMIT = 100
PROJECT_STATUS_MODES = ("manual", "automatic", "hybrid")
PROJECT_STATUS_FIELD_AUTHORITIES = ("manual", "automatic")
PROJECT_STATUS_AUTOMATIC_API_FIELDS = frozenset({"owner", "plannedDate", "note"})

#: connector 候选 field_values 允许的 API 字段（与自动归属字段一致）。
SYNC_CANDIDATE_ALLOWED_FIELDS = frozenset(PROJECT_STATUS_AUTOMATIC_API_FIELDS)


def _normalize_iso_date_value(value: str) -> str:
    """把来源返回的 ISO 日期时间（如 ARAS `2026-09-30T00:00:00`）归一为 ISO 日期。

    业务表的日期列与总览接口的 `date.fromisoformat` 都只接受 `YYYY-MM-DD`；
    无法解析的值原样返回，保持既有行为不变。
    """
    try:
        parsed = datetime.fromisoformat(str(value).strip())
    except ValueError:
        return value
    return parsed.date().isoformat()


#: 匹配状态枚举。
SYNC_MATCH_STATES = frozenset({"matched", "not_found", "ambiguous"})

#: 同步运行最终状态。
SYNC_FINAL_STATES = frozenset(
    {"success", "partial", "failed", "needs_attention", "expired"}
)

#: 文本字段限长，防止 audit/run summary 存储过大或原始响应片段。
_SYNC_TEXT_LIMITS = {
    "external_version": 200,
    "result_summary": 1000,
    "error_message": 1000,
    "error_type": 200,
}


@dataclass(frozen=True)
class ConnectorCandidate:
    """
    标准化外部候选。由连接器构造，不含可被信任的 deliverable_id ——
    路由由 binding_id 决定。

    Attributes:
        external_key: 外部稳定键，必须与 binding.external_key 精确匹配。
        external_version: 来源版本/游标快照，用于幂等去重。
        field_values: 仅允许 SYNC_CANDIDATE_ALLOWED_FIELDS 的字段值。
        fetched_at: 抓取时间（UTC ISO-8601）。
    """

    external_key: str
    external_version: str
    field_values: Mapping[str, object]
    fetched_at: str


@dataclass(frozen=True)
class ConnectorSnapshot:
    """
    连接器抓取结果的标准化快照。

    matched 时 candidates 必须恰好一个；not_found/ambiguous 不得更新业务表，
    run 最终为 needs_attention。

    Attributes:
        match_state: matched / not_found / ambiguous。
        candidates: 候选列表（matched 时长度为 1）。
        external_version: 来源版本。
        fetched_at: 抓取时间（UTC ISO-8601）。
        expected_deliverable_updated_at: 抓取时读到的业务行 updated_at，
            用于单事务内乐观锁校验。
    """

    match_state: str
    candidates: Sequence[ConnectorCandidate]
    external_version: str
    fetched_at: str
    expected_deliverable_updated_at: str
    artifacts: Sequence[Mapping[str, Any]] = ()
    analysis_rows: Sequence[Mapping[str, Any]] = field(default=(), repr=False)


@dataclass(frozen=True)
class SyncResult:
    """apply_sync_update 的返回值。"""

    run_id: int
    final_state: str
    applied_fields: tuple[str, ...]
    skipped_fields: Mapping[str, str]
    external_version: str
    updated_at: str | None
    message: str

#: API 字段名 -> project_status_deliverables 列名。
PROJECT_STATUS_EDITABLE_FIELDS: dict[str, str] = {
    "status": "status",
    "owner": "owner",
    "plannedDate": "planned_date",
    "actualDate": "actual_date",
    "progress": "progress",
    "note": "remark",
}

#: project_status_deliverables 列名 -> API 字段名。
PROJECT_STATUS_FIELD_NAME_TO_API: dict[str, str] = {
    db_name: api_name for api_name, db_name in PROJECT_STATUS_EDITABLE_FIELDS.items()
}

ALLOWED_TDC_MATCH_KEYS = frozenset(
    {
        "incident",
        "applicant",
        "department",
        "section",
        "applicationStart",
        "applicationEnd",
        "projectModel",
        "partNumber",
        "modelNumber",
        "reportType",
        "processNo",
        "carTypeProject",
        "title",
        "sorNumber",
        "approvalStatus",
        "ewoNo",
        "projectCode",
        "subjectKeyword",
    }
)

PROJECT_STATUS_SYNC_CONTRACTS: dict[str, dict[str, object]] = {
    "VPI-T2-D2": {
        "sourceType": "tdc",
        "reportType": "sor",
        "matchKeys": frozenset({
            "processNo", "carTypeProject", "applicant", "title",
            "partNumber", "sorNumber", "approvalStatus", "reportType",
        }),
    },
    "VPI-T2-D3": {
        "sourceType": "aras",
        "reportType": "ewo",
        "matchKeys": frozenset({
            "ewoNo", "projectCode", "subjectKeyword", "modelInfo", "reportType",
        }),
    },
    "VPI-T2-D5": {
        "sourceType": "tdc",
        "reportType": "data_model",
        "matchKeys": frozenset({
            "incident", "applicant", "department", "section",
            "applicationStart", "applicationEnd", "projectModel",
            "partNumber", "modelNumber", "reportType",
        }),
    },
}

_FORBIDDEN_CONFIG_FRAGMENTS = (
    "url",
    "host",
    "header",
    "cookie",
    "token",
    "api_key",
    "sid",
    "session",
    "csrf",
    "secret",
    "password",
    "credential",
    "auth",
    "config",
)

_TEXT_LIMITS = {
    "external_key": 200,
    "match_rule": 4000,
    "mapping": 4000,
    "error_summary": 1000,
}


class ProjectStatusPolicyError(Exception):
    """策略校验失败，携带按字段归类的错误信息。"""

    def __init__(self, fields: dict[str, str]) -> None:
        super().__init__("project status policy validation failed")
        self.fields = fields


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_sensitive_text(value, limit=1000)
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _sanitize_value(item) for key, item in value.items()}
    return value


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


def _contains_forbidden_config_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in _FORBIDDEN_CONFIG_FRAGMENTS):
                return True
            if _contains_forbidden_config_key(item):
                return True
    if isinstance(value, list):
        return any(_contains_forbidden_config_key(item) for item in value)
    return False


class ProjectStatusUpdateService:
    """项目状态交付物更新策略、手动写入与审计的统一入口。"""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def apply_manual_update(
        self,
        deliverable_id: str,
        phase_id: str,
        values: dict[str, object],
        expected_updated_at: str,
    ) -> str:
        """手动保存：按实际修改字段落人工锁并写审计，返回新版本。"""
        phase, _, deliverables = self._db.get_project_status(phase_id)
        if phase is None:
            raise KeyError(deliverable_id)
        current = next(
            (row for row in deliverables if row["id"] == deliverable_id),
            None,
        )
        if current is None:
            raise KeyError(deliverable_id)

        changed_fields = [
            field
            for field in PROJECT_STATUS_EDITABLE_FIELDS.values()
            if field in values and values[field] != current[field]
        ]
        proposed = {
            api_name: values[db_name]
            for api_name, db_name in PROJECT_STATUS_EDITABLE_FIELDS.items()
            if db_name in values
        }
        proposed_sanitized = _sanitize_value(proposed)
        applied_sanitized = {
            api_name: value
            for api_name, value in proposed_sanitized.items()
            if PROJECT_STATUS_EDITABLE_FIELDS[api_name] in changed_fields
        }
        return self._db.apply_project_status_manual_update(
            deliverable_id,
            phase_id,
            values,
            expected_updated_at,
            changed_fields,
            _json_dumps(proposed_sanitized),
            _json_dumps(applied_sanitized),
            source_type="none",
        )

    # ── 自动同步入口 ─────────────────────────────────────────────

    def acquire_sync_lease(
        self,
        deliverable_id: str,
        trigger_type: str,
        lease_seconds: int | None = None,
    ) -> dict[str, Any]:
        """
        为交付物获取同步租约并创建 leased run。

        返回内部 Lease 对象（含 binding_id/run_id/lease_token）。
        lease_token 不得记录到日志、审计或 Web 响应。
        """
        self.assert_sync_ready(deliverable_id)
        binding = self._db.get_sync_binding_by_deliverable(deliverable_id)
        if binding is None:
            raise KeyError(deliverable_id)
        kwargs: dict[str, Any] = {"trigger_type": trigger_type}
        if lease_seconds is not None:
            kwargs["lease_seconds"] = lease_seconds
        return self._db.acquire_sync_lease(int(binding["id"]), **kwargs)

    def assert_sync_ready(self, deliverable_id: str) -> dict[str, Any]:
        """Validate the persisted approval gate before any external sync call."""
        raw = self._db.get_project_status_update_policy(deliverable_id)
        if raw is None:
            raise KeyError(deliverable_id)
        binding = raw["binding"]
        contract = PROJECT_STATUS_SYNC_CONTRACTS.get(deliverable_id)
        if contract is None:
            raise SyncBindingNotReadyError("deliverable is manual or contract-blocked")
        if not binding["enabled"] or binding["mode"] not in {"automatic", "hybrid"}:
            raise SyncBindingNotReadyError("binding is not enabled for automatic sync")
        if binding["source_type"] != contract["sourceType"]:
            raise SyncBindingNotReadyError("binding source does not match the fixed contract")
        external_key = str(binding["external_key"] or "").strip() or None
        match_rule = _json_loads(binding["match_rule_json"])
        mapping = _json_loads(binding["mapping_json"])
        if not str(binding.get("credential_ref") or "").strip():
            raise SyncBindingNotReadyError("credential reference is not configured")
        if (
            match_rule.get("reportType") != contract["reportType"]
            or len(match_rule) < 2
            or not set(match_rule).issubset(set(contract["matchKeys"]))
            or _contains_forbidden_config_key(match_rule)
        ):
            raise SyncBindingNotReadyError("match rule is not approved for the fixed report")
        automatic_fields = {
            PROJECT_STATUS_FIELD_NAME_TO_API[row["field_name"]]
            for row in raw["authorities"]
            if row["authority"] == "automatic"
        }
        if (
            not automatic_fields
            or set(mapping) != automatic_fields
            or not set(mapping).issubset(PROJECT_STATUS_AUTOMATIC_API_FIELDS)
            or _contains_forbidden_config_key(mapping)
        ):
            raise SyncBindingNotReadyError("automatic field mapping is not approved")
        evidence_error = self._mapping_evidence_error(
            deliverable_id,
            str(contract["sourceType"]),
            external_key,
            mapping,
        )
        if evidence_error:
            raise SyncBindingNotReadyError(evidence_error)
        return binding

    def _mapping_evidence_error(
        self,
        deliverable_id: str,
        source_type: str,
        external_key: str | None,
        mapping: Mapping[str, object],
    ) -> str | None:
        observations = self._db.list_mapping_observations(deliverable_id, 2)
        if len(observations) < 2:
            return "启用同步前需要连续两次无歧义且目标一致的映射发现证据"
        for row in observations:
            if (
                row["result_state"] != "matched"
                or row["source_type"] != source_type
                or row["external_key"] != external_key
            ):
                return "映射发现证据与当前来源或外部稳定键不一致"
        report = _json_loads(observations[0]["field_report_json"])
        observed_fields = {
            str(value) for value in report.get("fields", [])
            if isinstance(value, str)
        }
        mapped_source_fields = {
            str(value).strip() for value in mapping.values()
            if isinstance(value, str) and value.strip()
        }
        if not mapped_source_fields or not mapped_source_fields.issubset(
            observed_fields
        ):
            return "自动字段映射必须来自最新的脱敏字段报告并由用户确认"
        return None

    def apply_sync_update(
        self,
        binding_id: int,
        run_id: int,
        lease_token: str,
        snapshot: ConnectorSnapshot,
        trigger_type: str,
    ) -> SyncResult:
        """
        将标准化 snapshot 在单事务内应用到业务表。

        - matched 且字段通过归属校验 → 更新业务行 + audit applied；
          部分字段被锁 → run_state=partial，audit result=applied。
        - matched 但 external_version 已处理 → 幂等 skipped，不更新业务行。
        - not_found/ambiguous → needs_attention，不写业务表，不推进 cursor。
        - 乐观锁冲突 → conflict 审计，不覆盖人工更新，不推进 cursor。
        - 任一步骤异常 → 事务回滚，调用方需自行调用 finalize_sync_failure
          释放租约（本方法内部异常已在 db 事务回滚，租约仍在但 run 未终态，
          将由过期抢占回收）。

        connector 网络请求应在调用本方法前完成；本方法只做单事务提交。
        """
        binding = self._read_binding_for_sync(binding_id)
        self._validate_snapshot(snapshot, binding)

        if snapshot.match_state in ("not_found", "ambiguous"):
            self._db.finalize_sync_needs_attention(
                binding_id,
                run_id,
                lease_token,
                error_type=snapshot.match_state,
                sanitized_message=self._sanitize_message(
                    f"connector match_state={snapshot.match_state}"
                ),
                result_summary=self._sanitize_message(
                    f"no unique candidate for external_key={binding['external_key']}"
                ),
            )
            return SyncResult(
                run_id=run_id,
                final_state="needs_attention",
                applied_fields=(),
                skipped_fields={},
                external_version=snapshot.external_version,
                updated_at=None,
                message=self._sanitize_message(
                    f"match_state={snapshot.match_state}; no business update applied"
                ),
            )

        # matched：恰好一个 candidate，external_key 精确匹配。
        candidate = snapshot.candidates[0]
        if candidate.external_key != binding["external_key"]:
            self._db.finalize_sync_needs_attention(
                binding_id,
                run_id,
                lease_token,
                error_type="external_key_mismatch",
                sanitized_message=self._sanitize_message(
                    "candidate external_key does not match binding"
                ),
                result_summary=self._sanitize_message("external_key mismatch"),
            )
            return SyncResult(
                run_id=run_id,
                final_state="needs_attention",
                applied_fields=(),
                skipped_fields={},
                external_version=snapshot.external_version,
                updated_at=None,
                message=self._sanitize_message("external_key mismatch"),
            )

        # 候选字段值经脱敏后再写入业务表，确保密码/Cookie/token 不落库。
        raw_values = dict(candidate.field_values)
        deliverable_values: dict[str, object] = {}
        for api_name, value in raw_values.items():
            if api_name == "plannedDate" and isinstance(value, str):
                value = _normalize_iso_date_value(value)
            deliverable_values[api_name] = (
                redact_sensitive_text(value, limit=1000)
                if isinstance(value, str)
                else value
            )
        proposed_sanitized = _sanitize_value(
            {
                api_name: deliverable_values.get(api_name)
                for api_name in SYNC_CANDIDATE_ALLOWED_FIELDS
            }
        )
        proposed_json = _json_dumps(proposed_sanitized)

        try:
            outcome = self._db.finalize_sync_success(
                binding_id=binding_id,
                run_id=run_id,
                lease_token=lease_token,
                deliverable_values=deliverable_values,
                expected_updated_at=snapshot.expected_deliverable_updated_at,
                phase_id=str(binding.get("phase_id") or ""),
                skipped_fields={},
                external_version=self._limit_text(
                    snapshot.external_version, "external_version"
                ),
                proposed_changes_json=proposed_json,
                applied_changes_json="{}",
                trigger_type=trigger_type,
                source_type=str(binding["source_type"]),
                result_summary=self._sanitize_message(
                    f"sync applied for {binding['deliverable_id']}"
                ),
                artifacts=snapshot.artifacts,
            )
        except ProjectStatusConcurrentUpdateError:
            # 乐观锁冲突：写 conflict 审计并原子释放租约。
            self._db.finalize_sync_conflict(
                binding_id,
                run_id,
                lease_token,
                deliverable_id=str(binding["deliverable_id"]),
                external_version=self._limit_text(
                    snapshot.external_version, "external_version"
                ),
                proposed_changes_json=proposed_json,
                source_type=str(binding["source_type"]),
                trigger_type=trigger_type,
                sanitized_message=self._sanitize_message(
                    "deliverable updated concurrently; manual change preserved"
                ),
            )
            return SyncResult(
                run_id=run_id,
                final_state="failed",
                applied_fields=(),
                skipped_fields={},
                external_version=snapshot.external_version,
                updated_at=None,
                message=self._sanitize_message(
                    "optimistic lock conflict; cursor not advanced"
                ),
            )

        updated_at = outcome["updated_at"]
        applied_fields = tuple(outcome["applied_fields"])
        skipped_fields = dict(outcome.get("skipped_fields") or {})
        run = self._db.get_sync_run(run_id)
        final_state = str(run["run_state"]) if run is not None else "success"
        return SyncResult(
            run_id=run_id,
            final_state=final_state,
            applied_fields=applied_fields,
            skipped_fields=skipped_fields,
            external_version=snapshot.external_version,
            updated_at=updated_at,
            message=self._sanitize_message("sync completed"),
        )

    def finalize_sync_failure(
        self,
        binding_id: int,
        run_id: int,
        lease_token: str,
        error_type: str,
        raw_message: str,
    ) -> SyncResult:
        """connector 异常时原子结束运行，保留最后成功数据。"""
        self._db.finalize_sync_failure(
            binding_id,
            run_id,
            lease_token,
            error_type=self._limit_text(error_type, "error_type"),
            sanitized_message=self._sanitize_message(raw_message),
            result_summary=self._sanitize_message("connector failure"),
        )
        return SyncResult(
            run_id=run_id,
            final_state="failed",
            applied_fields=(),
            skipped_fields={},
            external_version="",
            updated_at=None,
            message=self._sanitize_message("connector failure; last success preserved"),
        )

    def _read_binding_for_sync(self, binding_id: int) -> dict[str, Any]:
        """读取绑定并校验自动同步前置条件，返回含 phase_id 的内部视图。"""
        with self._db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT b.id, b.deliverable_id, b.mode, b.source_type, b.enabled,
                       b.external_key, b.match_rule_json, b.mapping_json,
                       d.phase_id
                FROM project_status_update_bindings b
                INNER JOIN project_status_deliverables d ON d.id = b.deliverable_id
                WHERE b.id = ?
                """,
                (binding_id,),
            ).fetchone()
        if row is None:
            raise KeyError(binding_id)
        binding = dict(row)
        if not binding["enabled"]:
            raise SyncBindingNotReadyError("binding is not enabled")
        if binding["mode"] not in ("automatic", "hybrid"):
            raise SyncBindingNotReadyError(
                f"binding mode '{binding['mode']}' does not allow scheduled sync"
            )
        if binding["source_type"] == "none":
            raise SyncBindingNotReadyError("binding source_type is 'none'")
        if not binding["external_key"]:
            raise SyncBindingNotReadyError("binding external_key is not confirmed")
        match_rule = _json_loads(binding["match_rule_json"])
        mapping = _json_loads(binding["mapping_json"])
        if not match_rule or not mapping:
            raise SyncBindingNotReadyError("binding match rule or mapping is empty")
        return binding

    def _validate_snapshot(
        self,
        snapshot: ConnectorSnapshot,
        binding: dict[str, Any],
    ) -> None:
        if not isinstance(snapshot, ConnectorSnapshot):
            raise ValueError("snapshot must be a ConnectorSnapshot")
        if snapshot.match_state not in SYNC_MATCH_STATES:
            raise ValueError(f"invalid match_state: {snapshot.match_state}")
        if not isinstance(snapshot.candidates, Sequence) or isinstance(
            snapshot.candidates, (str, bytes)
        ):
            raise ValueError("snapshot.candidates must be a sequence")
        if snapshot.match_state == "matched":
            if len(snapshot.candidates) != 1:
                raise ValueError("matched state requires exactly one candidate")
            candidate = snapshot.candidates[0]
            if not isinstance(candidate, ConnectorCandidate):
                raise ValueError("candidate must be a ConnectorCandidate")
            if not candidate.external_key or not candidate.external_version:
                raise ValueError("candidate external_key and external_version are required")
            bad = set(candidate.field_values) - SYNC_CANDIDATE_ALLOWED_FIELDS
            if bad:
                raise ValueError(
                    f"candidate field_values contains unsupported fields: {sorted(bad)}"
                )
            for value in candidate.field_values.values():
                if value is not None and not isinstance(value, str):
                    raise ValueError(
                        "candidate field_values must be str or None; "
                        "non-scalar values are not supported"
                    )
        if not snapshot.external_version:
            raise ValueError("snapshot external_version is required")
        if not snapshot.expected_deliverable_updated_at:
            raise ValueError("snapshot expected_deliverable_updated_at is required")

    @staticmethod
    def _sanitize_message(value: str) -> str:
        return redact_sensitive_text(value, limit=1000)

    @staticmethod
    def _limit_text(value: str, key: str) -> str:
        limit = _SYNC_TEXT_LIMITS.get(key, 1000)
        text = value if isinstance(value, str) else str(value)
        return redact_sensitive_text(text, limit=limit)

    def get_update_policy(self, deliverable_id: str) -> dict[str, Any] | None:
        raw = self._db.get_project_status_update_policy(deliverable_id)
        if raw is None:
            return None
        return self._policy_to_api(raw)

    def update_update_policy(
        self,
        deliverable_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        raw = self._db.get_project_status_update_policy(deliverable_id)
        if raw is None:
            raise KeyError(deliverable_id)
        binding = raw["binding"]
        contract = PROJECT_STATUS_SYNC_CONTRACTS.get(deliverable_id)
        fields: dict[str, str] = {}

        unknown = set(payload) - {
            "mode",
            "enabled",
            "externalKey",
            "matchRule",
            "mapping",
            "fieldAuthority",
            "credentialRef",
            "intervalMinutes",
        }
        if unknown:
            fields["request"] = "包含不允许修改的字段"

        mode = payload.get("mode", binding["mode"])
        enabled = payload.get("enabled", bool(binding["enabled"]))
        external_key = payload.get("externalKey", binding["external_key"])
        match_rule = payload.get("matchRule", _json_loads(binding["match_rule_json"]))
        mapping = payload.get("mapping", _json_loads(binding["mapping_json"]))
        credential_ref = payload.get("credentialRef", binding.get("credential_ref"))
        interval_minutes = payload.get("intervalMinutes", binding.get("interval_minutes") or 60)

        current_authority = {
            PROJECT_STATUS_FIELD_NAME_TO_API[row["field_name"]]: row["authority"]
            for row in raw["authorities"]
        }
        field_authority = dict(current_authority)
        if "fieldAuthority" in payload:
            requested_authority = payload["fieldAuthority"]
            if not isinstance(requested_authority, dict):
                fields["fieldAuthority"] = "字段归属必须是对象"
            else:
                valid_request = True
                for key, value in requested_authority.items():
                    if key not in PROJECT_STATUS_EDITABLE_FIELDS:
                        fields["fieldAuthority"] = "包含未知字段"
                        valid_request = False
                        break
                    if value not in PROJECT_STATUS_FIELD_AUTHORITIES:
                        fields["fieldAuthority"] = "字段归属必须是 manual 或 automatic"
                        valid_request = False
                        break
                if valid_request:
                    field_authority.update(
                        {str(key): str(value) for key, value in requested_authority.items()}
                    )

        if mode not in PROJECT_STATUS_MODES:
            fields["mode"] = "模式必须是 manual、automatic 或 hybrid"
        if not isinstance(enabled, bool):
            fields["enabled"] = "enabled 必须是布尔值"
        if credential_ref is not None:
            if not isinstance(credential_ref, str) or not credential_ref.strip():
                fields["credentialRef"] = "凭据引用必须是非空别名或 null"
            elif len(credential_ref.strip()) > 256 or any(ord(ch) < 32 for ch in credential_ref):
                fields["credentialRef"] = "凭据引用格式无效"
            else:
                credential_ref = credential_ref.strip()
        if not isinstance(interval_minutes, int) or isinstance(interval_minutes, bool) or interval_minutes < 1:
            fields["intervalMinutes"] = "同步周期必须是正整数分钟"

        if external_key is not None and not isinstance(external_key, str):
            fields["externalKey"] = "外部稳定键必须是字符串或 null"
        elif isinstance(external_key, str):
            external_key = external_key.strip()
            if len(external_key) > _TEXT_LIMITS["external_key"]:
                fields["externalKey"] = (
                    f"外部稳定键不能超过 {_TEXT_LIMITS['external_key']} 个字符"
                )
            if not external_key:
                external_key = None

        if not isinstance(match_rule, dict):
            fields["matchRule"] = "匹配规则必须是 JSON 对象"
        else:
            allowed_match_keys = (
                contract["matchKeys"] if contract else ALLOWED_TDC_MATCH_KEYS
            )
            bad_keys = set(match_rule) - set(allowed_match_keys)
            if bad_keys:
                fields["matchRule"] = "包含不允许的匹配键"
            elif _contains_forbidden_config_key(match_rule):
                fields["matchRule"] = "不允许配置 URL、主机或敏感请求键"
            elif len(_json_dumps(match_rule)) > _TEXT_LIMITS["match_rule"]:
                fields["matchRule"] = "匹配规则过长"

        if not isinstance(mapping, dict):
            fields["mapping"] = "字段映射必须是 JSON 对象"
        else:
            bad_mapping_keys = set(mapping) - PROJECT_STATUS_AUTOMATIC_API_FIELDS
            if bad_mapping_keys:
                fields["mapping"] = "字段映射仅允许负责人、计划日期和备注"
            elif any(
                not isinstance(source_field, str) or not source_field.strip()
                for source_field in mapping.values()
            ):
                fields["mapping"] = "字段映射值必须是非空的 TDC 字段名"
            elif _contains_forbidden_config_key(mapping):
                fields["mapping"] = "不允许配置 URL、主机或敏感请求键"
            elif len(_json_dumps(mapping)) > _TEXT_LIMITS["mapping"]:
                fields["mapping"] = "字段映射过长"

        automatic_targets = set(PROJECT_STATUS_SYNC_CONTRACTS)
        if deliverable_id not in automatic_targets:
            if mode != "manual":
                fields["mode"] = "此交付物当前保持手工或映射发现模式"
            if enabled:
                fields["enabled"] = "此交付物当前禁止自动同步"
            if any(value == "automatic" for value in field_authority.values()):
                fields["fieldAuthority"] = "此交付物当前禁止自动字段归属"

        if mode == "manual" and any(
            value == "automatic" for value in field_authority.values()
        ):
            fields["fieldAuthority"] = "手动模式下不能配置自动字段归属"

        unsupported_automatic_fields = {
            key
            for key, value in field_authority.items()
            if value == "automatic" and key not in PROJECT_STATUS_AUTOMATIC_API_FIELDS
        }
        if unsupported_automatic_fields:
            fields["fieldAuthority"] = "试点仅允许负责人、计划日期和备注自动更新"

        if enabled:
            if not external_key:
                fields["externalKey"] = "启用自动同步前必须先确认外部稳定键"
            if not isinstance(match_rule, dict) or not match_rule:
                fields["matchRule"] = "启用自动同步前必须配置至少一个匹配条件"
            elif not any(key in ALLOWED_TDC_MATCH_KEYS for key in match_rule):
                fields["matchRule"] = "匹配条件必须包含至少一个允许的 TDC 数据模型键"
            if mode == "manual":
                fields["enabled"] = "手动模式不能启用自动同步"
            if not credential_ref:
                fields["credentialRef"] = "启用自动同步前必须配置凭据引用别名"
            if contract and isinstance(match_rule, dict):
                required_report = str(contract["reportType"])
                if match_rule.get("reportType") != required_report:
                    fields["matchRule"] = (
                        f"此交付物的 reportType 必须为 {required_report}"
                    )
                elif len(match_rule) < 2:
                    fields["matchRule"] = "匹配规则必须包含至少一个筛选条件"
            automatic_fields = {
                key for key, value in field_authority.items()
                if value == "automatic"
            }
            if not automatic_fields:
                fields["fieldAuthority"] = "启用同步前必须明确至少一个自动字段"
            elif not isinstance(mapping, dict) or set(mapping) != automatic_fields:
                fields["mapping"] = "字段映射必须与已确认的自动字段完全一致"
            if contract:
                evidence_error = self._mapping_evidence_error(
                    deliverable_id,
                    str(contract["sourceType"]),
                    external_key,
                    mapping if isinstance(mapping, dict) else {},
                )
                if evidence_error:
                    fields["enabled"] = evidence_error

        if fields:
            raise ProjectStatusPolicyError(fields)

        normalized_authority = {
            PROJECT_STATUS_EDITABLE_FIELDS[key]: value
            for key, value in field_authority.items()
        }
        self._db.set_project_status_update_policy(
            deliverable_id,
            mode,
            enabled,
            external_key,
            _json_dumps(match_rule),
            _json_dumps(mapping),
            normalized_authority,
            credential_ref=credential_ref,
            interval_minutes=interval_minutes,
        )
        raw = self._db.get_project_status_update_policy(deliverable_id)
        assert raw is not None
        return self._policy_to_api(raw)

    def list_updates(
        self,
        deliverable_id: str,
        limit: int = PROJECT_STATUS_AUDIT_LIMIT,
    ) -> dict[str, Any] | None:
        if self._db.get_project_status_update_policy(deliverable_id) is None:
            return None
        rows = self._db.list_project_status_update_audit(deliverable_id, limit)
        updates = [self._audit_row_to_api(row) for row in rows]
        return {"deliverableId": deliverable_id, "updates": updates, "total": len(updates)}

    @staticmethod
    def _audit_row_to_api(row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "triggerType": row["trigger_type"],
            "sourceType": row["source_type"],
            "externalVersion": row["external_version"],
            "proposedChanges": _sanitize_value(_json_loads(row["proposed_changes_json"])),
            "appliedChanges": _sanitize_value(_json_loads(row["applied_changes_json"])),
            "skippedFields": _sanitize_value(_json_loads(row["skipped_fields_json"])),
            "result": row["result"],
            "errorSummary": (
                redact_sensitive_text(row["error_summary"], limit=1000)
                if row["error_summary"] is not None
                else None
            ),
            "createdAt": row["created_at"],
        }

    @staticmethod
    def _policy_to_api(raw: dict[str, Any]) -> dict[str, Any]:
        binding = raw["binding"]
        latest = raw.get("latest_audit")
        return {
            "deliverableId": binding["deliverable_id"],
            "mode": binding["mode"],
            "sourceType": binding["source_type"],
            "enabled": bool(binding["enabled"]),
            "externalKey": binding["external_key"],
            "matchRule": _json_loads(binding["match_rule_json"]),
            "mapping": _json_loads(binding["mapping_json"]),
            "intervalMinutes": binding.get("interval_minutes"),
            "credentialAvailable": bool(binding.get("credential_ref")),
            "lastAttemptAt": binding.get("last_attempt_at"),
            "lastSuccessAt": binding.get("last_success_at"),
            "syncState": binding.get("sync_state"),
            "lastErrorType": binding.get("last_error_type"),
            "lastErrorMessage": binding.get("last_error_message"),
            "createdAt": binding.get("created_at"),
            "updatedAt": binding.get("updated_at"),
            "fieldAuthority": {
                PROJECT_STATUS_FIELD_NAME_TO_API[row["field_name"]]: row["authority"]
                for row in raw["authorities"]
            },
            "latestUpdate": (
                {
                    "id": latest["id"],
                    "triggerType": latest["trigger_type"],
                    "sourceType": latest["source_type"],
                    "externalVersion": latest["external_version"],
                    "result": latest["result"],
                    "errorSummary": (
                        redact_sensitive_text(latest["error_summary"], limit=1000)
                        if latest["error_summary"] is not None
                        else None
                    ),
                    "createdAt": latest["created_at"],
                }
                if latest is not None
                else None
            ),
        }
