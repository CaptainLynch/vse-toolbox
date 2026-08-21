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
_IDENTITY_FIELDS = ("formId", "incident", "documentNo", "processInstanceId", "processNo", "id", "ewo_no", "item_number", "itemNumber")


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
