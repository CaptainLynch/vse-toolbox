# -*- coding: utf-8 -*-
"""Sanitized mapping-discovery evidence; never stores raw external responses."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from core.db_manager import DatabaseManager
from core.redaction import redact_sensitive_text
from services.project_status_records import (
    IDENTITY_FIELDS as _IDENTITY_FIELDS,
    MAX_AGGREGATE_RECORDS,
    aggregate_fingerprint,
    build_aggregate_candidate_values,
    clean_identity,
    compute_config_signature,
    compute_mapping_signature,
    identified_records,
    normalize_candidate_value,
    observation_is_aggregate,
    record_identity,
)

_FIELD_LIMIT = 200
_SAMPLE_LIMIT = 5
_VALUE_LIMIT = 200
_FULL_VALUE_LIMIT = 1000
_CANDIDATE_CACHE_KEY = "_candidateCache"
_CANDIDATE_CACHE_MAX_BYTES = 2 * 1024 * 1024
_STATUS_HINT = re.compile(r"status|state|node|stage|approval|approve|状态|节点|审批", re.I)
_SENSITIVE_FIELD = re.compile(r"authorization|cookie|token|secret|password|session|csrf", re.I)


def _scalar(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple, set, bytes, bytearray)):
        return None
    text = redact_sensitive_text(value, limit=_VALUE_LIMIT, collapse_newlines=True).strip()
    return text or None


def _key(row: Mapping[str, Any]) -> str | None:
    value = record_identity(row)
    return value or None


class MappingDiscoveryService:
    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def observe(
        self,
        deliverable_id: str,
        source_type: str,
        rows: Sequence[Mapping[str, Any]],
        selected_external_key: str | None = None,
        *,
        aggregate: bool = False,
        match_rule: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
            raise ValueError("rows must be a sequence of objects")
        if any(not isinstance(row, Mapping) for row in rows):
            raise ValueError("rows must be a sequence of objects")
        if len(rows) > MAX_AGGREGATE_RECORDS:
            raise ValueError(
                f"record count {len(rows)} exceeds maximum {MAX_AGGREGATE_RECORDS}"
            )
        if not isinstance(aggregate, bool):
            raise ValueError("aggregate must be a boolean")
        if selected_external_key is not None and not isinstance(selected_external_key, str):
            raise ValueError("selected_external_key must be a string or null")
        safe_rows = [self._safe_row(row) for row in rows]
        full_rows = [self._candidate_row(row) for row in rows]
        keyed = [(key, row) for row in safe_rows if (key := _key(row))]
        full_keyed = [(key, row) for row in full_rows if (key := _key(row))]
        selected = str(selected_external_key or "").strip() or None

        current_policy = self.db.get_project_status_update_policy(deliverable_id)
        current_binding = current_policy.get("binding") if current_policy else {}
        if match_rule is not None and not isinstance(match_rule, Mapping):
            raise ValueError("match_rule must be an object")
        effective_rule = dict(match_rule) if match_rule is not None else (
            json.loads(current_binding.get("match_rule_json") or "{}")
            if current_binding.get("match_rule_json") else {}
        )
        if not isinstance(effective_rule, dict):
            raise ValueError("match_rule must be an object")
        if "aggregate" in effective_rule and not isinstance(
            effective_rule["aggregate"], bool
        ):
            raise ValueError("match_rule aggregate must be a boolean")
        if "aggregate" in effective_rule and effective_rule["aggregate"] != aggregate:
            raise ValueError("aggregate mode does not match match_rule")
        config_signature = compute_config_signature(source_type, effective_rule)
        versioned_ewo = effective_rule.get('contractVersion') == '2'
        if versioned_ewo:
            from core.ewo_binding_v2 import identified_ewo_v2_rows, normalize_ewo_v2_rule
            effective_rule = normalize_ewo_v2_rule(effective_rule)
            if source_type != 'aras' or deliverable_id != 'VPI-T2-D3':
                raise ValueError('Versioned EWO source mismatch')
            keyed = identified_ewo_v2_rows(safe_rows)
            full_keyed = identified_ewo_v2_rows(full_rows)
            if not aggregate:
                if selected is not None and selected != effective_rule['sourceItemId']:
                    raise ValueError('Selected EWO source ID mismatch')
                selected = effective_rule['sourceItemId']
        current_mapping = (
            json.loads(current_binding.get("mapping_json") or "{}")
            if current_binding.get("mapping_json") else {}
        )
        if not isinstance(current_mapping, dict):
            current_mapping = {}
        if versioned_ewo and effective_rule.get("bindingMode") == "record_set":
            current_mapping = {k: v for k, v in current_mapping.items() if k == "note"}

        aggregated_candidate_values: dict[str, Any] | None = None
        cache_records: list[tuple[str, dict[str, Any]]] = []
        if aggregate:
            # 聚合观测（用户 2026-09-13 确认：按车型聚合全部匹配记录）：
            # 不做单记录筛选/歧义判定；指纹为全部记录单号的集合哈希，
            # 连续两次指纹一致即视为报表范围稳定。
            records = full_keyed if versioned_ewo else identified_records(full_rows)
            display_records = keyed if versioned_ewo else identified_records(safe_rows)
            candidates = display_records
            cache_records = records
            if not records:
                state, external_key, fingerprint = "not_found", None, None
            else:
                state, external_key = "matched", None
                fingerprint = aggregate_fingerprint(records)
                if versioned_ewo:
                    from services.ewo_binding_records import ewo_v2_candidate_values
                    aggregated_candidate_values = ewo_v2_candidate_values(records, current_mapping, effective_rule)
                else:
                    aggregated_candidate_values = build_aggregate_candidate_values(records, current_mapping)
        else:
            candidates = [(key, row) for key, row in keyed if selected is None or key == selected]
            full_candidates = [
                (key, row) for key, row in full_keyed if selected is None or key == selected
            ]
            cache_records = full_candidates
            if not candidates:
                state, external_key, fingerprint = "not_found", selected, None
            elif len(candidates) > 1:
                state, external_key, fingerprint = "ambiguous", selected, None
            else:
                external_key, row = candidates[0]
                fingerprint = hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                previous = self.db.list_mapping_observations(deliverable_id, 1)
                if (previous and previous[0]["result_state"] == "matched"
                        and previous[0]["external_key"] != external_key
                        and (not versioned_ewo or previous[0].get('config_signature') == config_signature)):
                    state = "key_changed"
                else:
                    state = "matched"
        summaries = [{"externalKey": key, "fields": row} for key, row in candidates[:_SAMPLE_LIMIT]]
        report = self._field_report([row for _, row in candidates] or safe_rows)
        candidate_cache = self._candidate_cache(cache_records, current_mapping)
        aggregated_payload = None
        if aggregated_candidate_values is not None or candidate_cache is not None:
            aggregated_payload = dict(aggregated_candidate_values or {})
            if candidate_cache is not None:
                aggregated_payload[_CANDIDATE_CACHE_KEY] = candidate_cache
        observation_id = self.db.record_mapping_observation(
            deliverable_id, source_type, state, external_key, fingerprint,
            len(candidates), json.dumps(summaries, ensure_ascii=False),
            json.dumps(report, ensure_ascii=False),
            config_signature=config_signature,
            aggregated_candidate_json=(
                json.dumps(aggregated_payload, ensure_ascii=False)
                if aggregated_payload is not None else None
            ),
        )
        progress = self.db.mapping_stability_count(deliverable_id, expected_signature=config_signature)
        return {
            "observationId": observation_id, "state": state,
            "externalKey": external_key, "candidateCount": len(candidates),
            "candidates": summaries, "fieldReport": report,
            "stability": {"confirmed": progress, "required": 2, "ready": progress >= 2},
        }

    @staticmethod
    def _safe_row(row: Mapping[str, Any]) -> dict[str, str | None]:
        keys = sorted(str(key) for key in row)[:_FIELD_LIMIT]
        kept = [key for key in keys if not _SENSITIVE_FIELD.search(key)]
        # 身份字段是候选键提取的唯一来源；真实 EWO 报表约 70 列，`_no` 按字母序
        # 排在截断点之后，一旦被丢弃 discovery 对线上数据永远 not_found。
        kept += [
            key for key in (*_IDENTITY_FIELDS, '_source_item_id')
            if key in row and key not in kept and not _SENSITIVE_FIELD.search(key)
        ]
        result: dict[str, str | None] = {}
        for key in kept:
            val = row.get(key)
            if key in _IDENTITY_FIELDS:
                result[key] = clean_identity(val) or None
            else:
                result[key] = _scalar(val)
        return result

    @staticmethod
    def _candidate_row(row: Mapping[str, Any]) -> dict[str, str | None]:
        """Build the bounded full candidate row used for offline recomputation.

        This is sanitized data, not a raw response: sensitive fields are
        excluded, fields are bounded, and each scalar is capped at 1000 chars.
        """
        keys = sorted(str(key) for key in row)[:_FIELD_LIMIT]
        kept = [key for key in keys if not _SENSITIVE_FIELD.search(key)]
        kept += [
            key for key in (*_IDENTITY_FIELDS, '_source_item_id')
            if key in row and key not in kept and not _SENSITIVE_FIELD.search(key)
        ]
        result: dict[str, str | None] = {}
        for key in kept:
            value = row.get(key)
            if key in _IDENTITY_FIELDS:
                result[key] = clean_identity(value) or None
            elif value is None or isinstance(value, (dict, list, tuple, set, bytes, bytearray)):
                result[key] = None
            else:
                text = redact_sensitive_text(value, limit=_FULL_VALUE_LIMIT, collapse_newlines=True).strip()
                result[key] = text or None
        return result

    @staticmethod
    def _candidate_cache(
        records: Sequence[tuple[str, Mapping[str, Any]]],
        mapping: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if not records:
            return None
        payload: dict[str, Any] = {
            "version": 1,
            "complete": True,
            "mappingSignature": compute_mapping_signature(mapping),
            "records": [
                {"externalKey": key, "fields": dict(row)} for key, row in records
            ],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > _CANDIDATE_CACHE_MAX_BYTES:
            return {
                "version": 1,
                "complete": False,
                "mappingSignature": compute_mapping_signature(mapping),
                "records": [],
            }
        return payload

    @staticmethod
    def _field_report(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        fields = sorted({str(key) for row in rows for key in row})[:_FIELD_LIMIT]
        status_fields = []
        for field in fields:
            if not _STATUS_HINT.search(field):
                continue
            samples = []
            for row in rows:
                value = _scalar(row.get(field))
                if value and value not in samples:
                    samples.append(value)
                if len(samples) >= 10:
                    break
            status_fields.append({"field": field, "samples": samples})
        return {
            "fields": fields,
            "statusOrApprovalFields": status_fields,
            "suggestedStatusMapping": [],
            "suggestedAutomaticFields": [],
            "requiresConfirmation": True,
        }

    def history(self, deliverable_id: str, limit: int = 20) -> dict[str, Any]:
        rows = self.db.list_mapping_observations(deliverable_id, limit)
        observations: list[dict[str, Any]] = []
        for row in rows:
            try:
                candidates = json.loads(row["candidate_summary_json"])
            except (TypeError, ValueError):
                candidates = []
            if not isinstance(candidates, list) or any(
                not isinstance(item, dict) for item in candidates
            ):
                candidates = []
            try:
                field_report = json.loads(row["field_report_json"])
            except (TypeError, ValueError):
                field_report = {}
            if not isinstance(field_report, dict):
                field_report = {}
            observations.append(
                {
                    "id": row["id"], "sourceType": row["source_type"],
                    "state": row["result_state"], "externalKey": row["external_key"],
                    "candidateCount": row["candidate_count"],
                    "candidates": candidates,
                    "fieldReport": field_report,
                    "createdAt": row["created_at"],
                }
            )
        return {
            "deliverableId": deliverable_id,
            "stability": {
                "confirmed": self.db.mapping_stability_count(deliverable_id),
                "required": 2,
            },
            "observations": observations,
        }

    def candidate_preview(self, deliverable_id: str) -> dict[str, Any]:
        _, _, deliverables = self.db.get_project_status("VPI-T2")
        deliverable_row = next(
            (row for row in deliverables if row["id"] == deliverable_id),
            None,
        )

        if deliverable_row is None:
            return {
                "deliverableId": deliverable_id,
                "state": "not_found",
                "reason": "deliverable_not_found",
                "externalKey": None,
                "stability": {"confirmed": 0, "required": 2, "ready": False},
                "differences": [],
            }

        policy = self.db.get_project_status_update_policy(deliverable_id)
        if policy is None:
            return {
                "deliverableId": deliverable_id,
                "state": "not_found",
                "reason": "policy_not_found",
                "externalKey": None,
                "stability": {"confirmed": 0, "required": 2, "ready": False},
                "differences": [],
            }

        binding = policy["binding"]
        authorities = {
            row["field_name"]: row["authority"]
            for row in policy.get("authorities", [])
        }

        observations = self.db.list_mapping_observations(deliverable_id, limit=2)
        confirmed_stability = self.db.mapping_stability_count(deliverable_id)

        if not observations:
            return {
                "deliverableId": deliverable_id,
                "state": "not_found",
                "reason": "no_observation",
                "externalKey": None,
                "stability": {"confirmed": 0, "required": 2, "ready": False},
                "differences": [],
            }

        latest = observations[0]
        latest_state = latest["result_state"]
        latest_key = latest["external_key"]
        latest_source = latest["source_type"]
        candidate_count = latest["candidate_count"]

        if (
            isinstance(candidate_count, bool)
            or not isinstance(candidate_count, int)
            or candidate_count < 1
        ):
            return {
                "deliverableId": deliverable_id,
                "state": "not_found",
                "reason": "invalid_observation",
                "externalKey": None,
                "stability": {"confirmed": 0, "required": 2, "ready": False},
                "differences": [],
            }

        binding_source = str(binding.get("source_type") or "").strip()
        try:
            binding_match_rule = json.loads(binding.get("match_rule_json") or "{}")
        except (TypeError, ValueError):
            binding_match_rule = None
        # Preview is also a readiness signal.  Never reinterpret malformed
        # JSON, arrays, or invalid aggregate flag types as an empty rule and
        # let a matching legacy observation make the binding look ready.
        if (
            not isinstance(binding_match_rule, dict)
            or not binding_match_rule
            or (
                "aggregate" in binding_match_rule
                and not isinstance(binding_match_rule["aggregate"], bool)
            )
            or any(
                key != "aggregate"
                and (not isinstance(value, str) or not value.strip())
                for key, value in binding_match_rule.items()
            )
        ):
            return {
                "deliverableId": deliverable_id,
                "state": "not_found",
                "reason": "invalid_configuration",
                "externalKey": None,
                "stability": {"confirmed": 0, "required": 2, "ready": False},
                "differences": [],
            }
        expected_signature = compute_config_signature(binding_source, binding_match_rule)
        expected_aggregate = binding_match_rule.get("aggregate") is True

        if latest_state != "matched":
            return {
                "deliverableId": deliverable_id,
                "state": latest_state,
                "reason": "observation_not_matched",
                "externalKey": latest_key,
                "stability": {"confirmed": confirmed_stability, "required": 2, "ready": False},
                "differences": [],
            }

        try:
            candidates = json.loads(latest["candidate_summary_json"])
        except (TypeError, ValueError):
            candidates = None
        if not isinstance(candidates, list) or any(
            not isinstance(item, dict) for item in candidates
        ):
            return {
                "deliverableId": deliverable_id,
                "state": "not_found",
                "reason": "invalid_observation",
                "externalKey": None,
                "stability": {"confirmed": 0, "required": 2, "ready": False},
                "differences": [],
            }

        is_aggregate = observation_is_aggregate(latest)
        if not is_aggregate and (candidate_count != 1 or len(candidates) != 1):
            return {
                "deliverableId": deliverable_id,
                "state": latest_state,
                "reason": "candidate_not_unique",
                "externalKey": latest_key,
                "stability": {"confirmed": confirmed_stability, "required": 2, "ready": False},
                "differences": [],
            }
        if is_aggregate and (candidate_count < 1 or len(candidates) < 1):
            return {
                "deliverableId": deliverable_id,
                "state": latest_state,
                "reason": "candidate_not_unique",
                "externalKey": latest_key,
                "stability": {"confirmed": confirmed_stability, "required": 2, "ready": False},
                "differences": [],
            }

        if binding_source != latest_source:
            return {
                "deliverableId": deliverable_id,
                "state": latest_state,
                "reason": "source_mismatch",
                "externalKey": latest_key,
                "stability": {"confirmed": confirmed_stability, "required": 2, "ready": False},
                "differences": [],
            }

        if is_aggregate != expected_aggregate:
            return {
                "deliverableId": deliverable_id,
                "state": "not_found",
                "reason": "observation_mode_mismatch",
                "externalKey": None,
                "stability": {"confirmed": 0, "required": 2, "ready": False},
                "differences": [],
            }

        binding_key = str(binding.get("external_key") or "").strip() or None
        if binding_key != latest_key:
            return {
                "deliverableId": deliverable_id,
                "state": latest_state,
                "reason": "key_mismatch",
                "externalKey": latest_key,
                "stability": {"confirmed": confirmed_stability, "required": 2, "ready": False},
                "differences": [],
            }

        # 当前配置需要两条严格签名证据；空值、缺列和旧签名均不可授权。
        if any(
            str(row.get("config_signature") or "").strip() != expected_signature
            or observation_is_aggregate(row) != expected_aggregate
            for row in observations
        ):
            return {
                "deliverableId": deliverable_id,
                "state": "not_found",
                "reason": "no_observation",
                "externalKey": None,
                "stability": {"confirmed": 0, "required": 2, "ready": False},
                "differences": [],
            }

        confirmed_stability = self.db.mapping_stability_count(
            deliverable_id, expected_signature=expected_signature
        )

        if confirmed_stability < 2:
            return {
                "deliverableId": deliverable_id,
                "state": latest_state,
                "reason": "insufficient_stability",
                "externalKey": latest_key,
                "stability": {"confirmed": confirmed_stability, "required": 2, "ready": False},
                "differences": [],
            }

        if not binding.get("enabled"):
            return {
                "deliverableId": deliverable_id,
                "state": latest_state,
                "reason": "policy_disabled",
                "externalKey": latest_key,
                "stability": {"confirmed": confirmed_stability, "required": 2, "ready": False},
                "differences": [],
            }

        try:
            mapping = json.loads(binding.get("mapping_json") or "{}")
        except Exception:
            mapping = {}

        if not isinstance(mapping, dict) or not mapping:
            return {
                "deliverableId": deliverable_id,
                "state": latest_state,
                "reason": "unapproved_mapping",
                "externalKey": latest_key,
                "stability": {"confirmed": confirmed_stability, "required": 2, "ready": False},
                "differences": [],
            }

        try:
            field_report = json.loads(latest["field_report_json"])
        except (TypeError, ValueError):
            field_report = None

        if (
            not isinstance(field_report, dict)
            or not isinstance(field_report.get("fields"), list)
            or any(not isinstance(value, str) for value in field_report["fields"])
        ):
            return {
                "deliverableId": deliverable_id,
                "state": "not_found",
                "reason": "invalid_observation",
                "externalKey": None,
                "stability": {"confirmed": 0, "required": 2, "ready": False},
                "differences": [],
            }

        sanitized_fields = set(field_report["fields"])

        approved_target_fields = {
            "owner": "owner",
            "plannedDate": "planned_date",
            "note": "remark",
        }

        valid_comparisons = []
        for target_field, db_col in approved_target_fields.items():
            if target_field not in mapping:
                continue
            if authorities.get(db_col) != "automatic":
                continue
            source_field = mapping[target_field]
            if target_field == "note" and isinstance(source_field, list):
                if not source_field or not all(isinstance(s, str) and s.strip() for s in source_field):
                    continue
                valid = True
                cleaned_sources = []
                for s in source_field:
                    s_clean = s.strip()
                    if len(s_clean) > _VALUE_LIMIT or _SENSITIVE_FIELD.search(s_clean):
                        valid = False
                        break
                    if redact_sensitive_text(s_clean, limit=_VALUE_LIMIT, collapse_newlines=True).strip() != s_clean:
                        valid = False
                        break
                    if s_clean not in sanitized_fields:
                        valid = False
                        break
                    cleaned_sources.append(s_clean)
                if not valid:
                    return {
                        "deliverableId": deliverable_id,
                        "state": latest_state,
                        "reason": "unapproved_mapping",
                        "externalKey": latest_key,
                        "stability": {"confirmed": confirmed_stability, "required": 2, "ready": False},
                        "differences": [],
                    }
                valid_comparisons.append((target_field, cleaned_sources, db_col))
                continue

            if not isinstance(source_field, str) or not source_field.strip():
                continue
            source_field = source_field.strip()
            if len(source_field) > _VALUE_LIMIT or _SENSITIVE_FIELD.search(source_field):
                return {
                    "deliverableId": deliverable_id,
                    "state": latest_state,
                    "reason": "unapproved_mapping",
                    "externalKey": latest_key,
                    "stability": {"confirmed": confirmed_stability, "required": 2, "ready": False},
                    "differences": [],
                }
            redacted_source = redact_sensitive_text(source_field, limit=_VALUE_LIMIT, collapse_newlines=True).strip()
            if redacted_source != source_field:
                return {
                    "deliverableId": deliverable_id,
                    "state": latest_state,
                    "reason": "unapproved_mapping",
                    "externalKey": latest_key,
                    "stability": {"confirmed": confirmed_stability, "required": 2, "ready": False},
                    "differences": [],
                }
            if source_field not in sanitized_fields:
                return {
                    "deliverableId": deliverable_id,
                    "state": latest_state,
                    "reason": "unapproved_mapping",
                    "externalKey": latest_key,
                    "stability": {"confirmed": confirmed_stability, "required": 2, "ready": False},
                    "differences": [],
                }
            valid_comparisons.append((target_field, source_field, db_col))

        if not valid_comparisons:
            return {
                "deliverableId": deliverable_id,
                "state": latest_state,
                "reason": "unapproved_mapping",
                "externalKey": latest_key,
                "stability": {"confirmed": confirmed_stability, "required": 2, "ready": False},
                "differences": [],
            }

        try:
            aggregated_payload = json.loads(latest.get("aggregated_candidate_json") or "{}")
        except (TypeError, ValueError):
            aggregated_payload = {}
        if not isinstance(aggregated_payload, dict):
            aggregated_payload = {}
        cache = aggregated_payload.get(_CANDIDATE_CACHE_KEY)
        cached_records: list[tuple[str, Mapping[str, Any]]] = []
        cache_complete = False
        if isinstance(cache, dict) and cache.get("complete") is True:
            raw_records = cache.get("records")
            if isinstance(raw_records, list):
                for item in raw_records:
                    if not isinstance(item, dict):
                        continue
                    external_key = clean_identity(item.get("externalKey"))
                    fields = item.get("fields")
                    if external_key and isinstance(fields, dict):
                        cached_records.append((external_key, dict(fields)))
                cache_complete = len(cached_records) == candidate_count

        # The cache holds bounded sanitized full rows. Recompute from it on
        # every mapping identity, so a->b never reuses the old mapped value.
        if cache_complete:
            if binding_match_rule.get('contractVersion') == '2':
                from services.ewo_binding_records import ewo_v2_candidate_values
                candidate_values = ewo_v2_candidate_values(cached_records, mapping, binding_match_rule)
            else:
                candidate_values = build_aggregate_candidate_values(cached_records, mapping)
        else:
            # A display sample is intentionally capped at five rows/200
            # characters and cannot authorize a write, even for a legacy
            # single-record observation.  Requiring the bounded full cache
            # keeps preview comparison and connector execution identical.
            return {
                "deliverableId": deliverable_id,
                "state": latest_state,
                "reason": "candidate_cache_unavailable",
                "externalKey": latest_key,
                "stability": {"confirmed": confirmed_stability, "required": 2, "ready": False},
                "differences": [],
            }

        if is_aggregate and candidate_count > 1:
            note_is_writable = (
                "note" in mapping
                and authorities.get("remark") == "automatic"
                and any(item[0] == "note" for item in valid_comparisons)
            )
            if not note_is_writable:
                return {
                    "deliverableId": deliverable_id,
                    "state": latest_state,
                    "reason": "aggregate_note_mapping_required",
                    "externalKey": latest_key,
                    "stability": {"confirmed": confirmed_stability, "required": 2, "ready": False},
                    "differences": [],
                }
            if not candidate_values.get("note"):
                return {
                    "deliverableId": deliverable_id,
                    "state": latest_state,
                    "reason": "aggregate_note_candidate_empty",
                    "externalKey": latest_key,
                    "stability": {"confirmed": confirmed_stability, "required": 2, "ready": False},
                    "differences": [],
                }

        differences = []
        for target_field, source_field, db_col in valid_comparisons:
            current_raw = deliverable_row[db_col]
            current_value = normalize_candidate_value(target_field, current_raw)
            current_val = _scalar(current_raw)
            if binding_match_rule.get('contractVersion') == '2' and target_field not in candidate_values:
                cand_val = current_val
                changed = False
            elif is_aggregate and candidate_count > 1:
                # 多记录聚合模式口径（与连接器 _aggregate_snapshot 完全一致）：
                # 1. 负责人与计划完成日期不写入，候选值保持当前值且无变更（避免假阳性）。
                # 2. 风险备注（无论单字段还是列表字段）优先采用完整聚合候选值（P2-5），避免仅取 5 条样本。
                if target_field in ("owner", "plannedDate"):
                    cand_val = current_val
                    changed = False
                elif target_field == "note":
                    candidate_raw = candidate_values.get("note")
                    cand_val = _scalar(candidate_raw)
                    changed = current_value != normalize_candidate_value("note", candidate_raw)
                else:
                    cand_val = current_val
                    changed = False
            else:
                candidate_raw = candidate_values.get(target_field)
                cand_val = _scalar(candidate_raw)
                changed = current_value != normalize_candidate_value(target_field, candidate_raw)

            differences.append({
                "targetField": target_field,
                "sourceField": source_field,
                "currentValue": current_val,
                "candidateValue": cand_val,
                "changed": changed,
            })

        return {
            "deliverableId": deliverable_id,
            "state": latest_state,
            "reason": None,
            "externalKey": latest_key,
            "stability": {"confirmed": confirmed_stability, "required": 2, "ready": True},
            "differences": differences,
        }
