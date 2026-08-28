# -*- coding: utf-8 -*-
"""Sanitized mapping-discovery evidence; never stores raw external responses."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from core.db_manager import DatabaseManager
from core.redaction import redact_sensitive_text

_FIELD_LIMIT = 30
_SAMPLE_LIMIT = 5
_VALUE_LIMIT = 200
_STATUS_HINT = re.compile(r"status|state|node|stage|approval|approve|状态|节点|审批", re.I)
_SENSITIVE_FIELD = re.compile(r"authorization|cookie|token|secret|password|session|csrf", re.I)
_IDENTITY_FIELDS = ("formId", "incident", "documentNo", "processInstanceId", "processNo", "id", "ewo_no", "_no", "item_number", "itemNumber")


def _scalar(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple, set, bytes, bytearray)):
        return None
    text = redact_sensitive_text(value, limit=_VALUE_LIMIT, collapse_newlines=True).strip()
    return text or None


def _key(row: Mapping[str, Any]) -> str | None:
    for field in _IDENTITY_FIELDS:
        value = _scalar(row.get(field))
        if value:
            return value
    return None


class MappingDiscoveryService:
    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def observe(self, deliverable_id: str, source_type: str, rows: Sequence[Mapping[str, Any]], selected_external_key: str | None = None) -> dict[str, Any]:
        safe_rows = [self._safe_row(row) for row in rows[:1000]]
        keyed = [(key, row) for row in safe_rows if (key := _key(row))]
        selected = str(selected_external_key or "").strip() or None
        candidates = [(key, row) for key, row in keyed if selected is None or key == selected]
        if not candidates:
            state, external_key, fingerprint = "not_found", selected, None
        elif len(candidates) > 1:
            state, external_key, fingerprint = "ambiguous", selected, None
        else:
            external_key, row = candidates[0]
            fingerprint = hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            previous = self.db.list_mapping_observations(deliverable_id, 1)
            if previous and previous[0]["result_state"] == "matched" and previous[0]["external_key"] != external_key:
                state = "key_changed"
            else:
                state = "matched"
        summaries = [{"externalKey": key, "fields": row} for key, row in candidates[:_SAMPLE_LIMIT]]
        report = self._field_report([row for _, row in candidates] or safe_rows)
        observation_id = self.db.record_mapping_observation(
            deliverable_id, source_type, state, external_key, fingerprint,
            len(candidates), json.dumps(summaries, ensure_ascii=False),
            json.dumps(report, ensure_ascii=False),
        )
        progress = self.db.mapping_stability_count(deliverable_id)
        return {
            "observationId": observation_id, "state": state,
            "externalKey": external_key, "candidateCount": len(candidates),
            "candidates": summaries, "fieldReport": report,
            "stability": {"confirmed": progress, "required": 2, "ready": progress >= 2},
        }

    @staticmethod
    def _safe_row(row: Mapping[str, Any]) -> dict[str, str | None]:
        result: dict[str, str | None] = {}
        for key in sorted(str(key) for key in row)[:_FIELD_LIMIT]:
            if _SENSITIVE_FIELD.search(key):
                continue
            result[key] = _scalar(row.get(key))
        return result

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
        return {
            "deliverableId": deliverable_id,
            "stability": {"confirmed": self.db.mapping_stability_count(deliverable_id), "required": 2},
            "observations": [
                {
                    "id": row["id"], "sourceType": row["source_type"],
                    "state": row["result_state"], "externalKey": row["external_key"],
                    "candidateCount": row["candidate_count"],
                    "candidates": json.loads(row["candidate_summary_json"]),
                    "fieldReport": json.loads(row["field_report_json"]),
                    "createdAt": row["created_at"],
                }
                for row in rows
            ],
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
        except Exception:
            candidates = []

        if candidate_count != 1 or len(candidates) != 1:
            return {
                "deliverableId": deliverable_id,
                "state": latest_state,
                "reason": "candidate_not_unique",
                "externalKey": latest_key,
                "stability": {"confirmed": confirmed_stability, "required": 2, "ready": False},
                "differences": [],
            }

        if confirmed_stability < 2:
            return {
                "deliverableId": deliverable_id,
                "state": latest_state,
                "reason": "insufficient_stability",
                "externalKey": latest_key,
                "stability": {"confirmed": confirmed_stability, "required": 2, "ready": False},
                "differences": [],
            }

        binding_source = str(binding.get("source_type") or "").strip()
        if binding_source != latest_source:
            return {
                "deliverableId": deliverable_id,
                "state": latest_state,
                "reason": "source_mismatch",
                "externalKey": latest_key,
                "stability": {"confirmed": confirmed_stability, "required": 2, "ready": False},
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
        except Exception:
            field_report = {}

        sanitized_fields = set(field_report.get("fields", [])) if isinstance(field_report, dict) else set()

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

        candidate_fields = candidates[0].get("fields", {})
        if not isinstance(candidate_fields, dict):
            candidate_fields = {}

        differences = []
        for target_field, source_field, db_col in valid_comparisons:
            current_val = _scalar(deliverable_row[db_col])
            cand_val = _scalar(candidate_fields.get(source_field))
            differences.append({
                "targetField": target_field,
                "sourceField": source_field,
                "currentValue": current_val,
                "candidateValue": cand_val,
                "changed": current_val != cand_val,
            })

        return {
            "deliverableId": deliverable_id,
            "state": latest_state,
            "reason": None,
            "externalKey": latest_key,
            "stability": {"confirmed": confirmed_stability, "required": 2, "ready": True},
            "differences": differences,
        }
