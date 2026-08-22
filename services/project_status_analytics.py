# -*- coding: utf-8 -*-
"""Read-only analytics derived exclusively from saved sync evidence."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from core.db_manager import DatabaseManager
from core.redaction import redact_sensitive_text

ALLOWED_AUDIT_FIELDS = frozenset({"owner", "plannedDate", "actualDate", "status", "progress", "note"})

_SYNC_RESTRICTIONS: dict[str, str] = {
    "VPI-T2-D1": "manual_only",
    "VPI-T2-D4": "contract_blocked",
}

_MAPPING_STATE_SUMMARIES: dict[str, str] = {
    "not_found": "mapping observation: not_found",
    "ambiguous": "mapping observation: ambiguous",
    "missing_fields": "mapping observation: missing_fields",
    "key_changed": "mapping observation: key_changed",
}


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _extract_allowed_fields(raw_json: Any) -> list[str]:
    if not raw_json:
        return []
    if isinstance(raw_json, str):
        try:
            parsed = json.loads(raw_json)
        except (ValueError, TypeError):
            return []
    elif isinstance(raw_json, (dict, list, set, tuple)):
        parsed = raw_json
    else:
        return []

    if isinstance(parsed, dict):
        keys = [k for k in parsed.keys() if isinstance(k, str) and k in ALLOWED_AUDIT_FIELDS]
    elif isinstance(parsed, (list, tuple, set)):
        keys = [k for k in parsed if isinstance(k, str) and k in ALLOWED_AUDIT_FIELDS]
    else:
        keys = []
    return sorted(set(keys))


class ProjectStatusAnalyticsService:
    def __init__(self, db: DatabaseManager, *, stale_hours: int = 24) -> None:
        self.db = db
        self.stale_hours = stale_hours
        self.stale_after = timedelta(hours=stale_hours)

    def overview(self, now: datetime | None = None) -> dict[str, Any]:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        phase, _, deliverables = self.db.get_project_status("VPI-T2")
        if phase is None:
            raise KeyError("VPI-T2")
        items = []
        for row in deliverables:
            deliverable_id = str(row["id"])
            policy = self.db.get_project_status_update_policy(deliverable_id)
            assert policy is not None
            binding = policy["binding"]
            runs = self.db.list_sync_runs(deliverable_id, 30)
            last_success = _parse_time(binding.get("last_success_at"))
            freshness = "unknown" if last_success is None else (
                "stale" if current - last_success > self.stale_after else "fresh"
            )
            state_counts: dict[str, int] = {}
            for run in runs:
                state = str(run["run_state"])
                state_counts[state] = state_counts.get(state, 0) + 1

            observations = self.db.list_mapping_observations(deliverable_id, limit=1)
            latest_obs = observations[0] if observations else None

            mapping_evidence: dict[str, Any] | None = None
            external_record_count: int | None = None
            latest_mapping_state: str | None = None
            if latest_obs is not None:
                latest_mapping_state = str(latest_obs["result_state"])
                external_record_count = int(latest_obs["candidate_count"])
                mapping_evidence = {
                    "state": latest_mapping_state,
                    "externalKey": latest_obs.get("external_key"),
                    "candidateCount": external_record_count,
                    "observedAt": latest_obs["created_at"],
                }

            confirmed_stability = self.db.mapping_stability_count(deliverable_id)
            required_stability = 2
            mapping_stability = {
                "confirmed": confirmed_stability,
                "required": required_stability,
                "ready": confirmed_stability >= required_stability,
            }

            audits = self.db.list_project_status_update_audit(deliverable_id, limit=1)
            latest_audit_row = audits[0] if audits else None

            confirmed_field_differences: dict[str, Any] | None = None
            if latest_audit_row is not None:
                confirmed_field_differences = {
                    "proposedFields": _extract_allowed_fields(latest_audit_row["proposed_changes_json"]),
                    "appliedFields": _extract_allowed_fields(latest_audit_row["applied_changes_json"]),
                    "skippedFields": _extract_allowed_fields(latest_audit_row["skipped_fields_json"]),
                    "result": latest_audit_row["result"],
                    "observedAt": latest_audit_row["created_at"],
                }

            sync_state = binding.get("sync_state")
            is_non_matched_mapping = bool(latest_mapping_state and latest_mapping_state != "matched")
            needs_attention = (sync_state == "needs_attention") or is_non_matched_mapping

            saved_error = redact_sensitive_text(
                binding.get("last_error_message") or "", limit=300
            ) or None

            if saved_error:
                risk_summary = saved_error
            elif is_non_matched_mapping and latest_mapping_state:
                risk_summary = _MAPPING_STATE_SUMMARIES.get(
                    latest_mapping_state, f"mapping observation: {latest_mapping_state}"
                )
            else:
                risk_summary = None

            sync_restriction = _SYNC_RESTRICTIONS.get(deliverable_id, None)

            items.append({
                "deliverableId": deliverable_id,
                "authoritativeSource": row["source"],
                "lastAttemptAt": binding.get("last_attempt_at"),
                "lastSuccessAt": binding.get("last_success_at"),
                "freshness": freshness,
                "syncState": sync_state,
                "failureCount": state_counts.get("failed", 0),
                "runTrend": state_counts,
                "externalRecordCount": external_record_count,
                "confirmedDifference": latest_audit_row["result"] if latest_audit_row else None,
                "confirmedFieldDifferences": confirmed_field_differences,
                "mappingEvidence": mapping_evidence,
                "mappingStability": mapping_stability,
                "needsAttention": needs_attention,
                "riskSummary": risk_summary,
                "syncRestriction": sync_restriction,
            })
        return {"phaseId": "VPI-T2", "staleAfterHours": self.stale_hours, "deliverables": items}

    def runs(self, deliverable_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        rows = self.db.list_sync_runs(deliverable_id, limit)
        return {
            "runs": [
                {
                    **dict(row),
                    "result_summary": redact_sensitive_text(row.get("result_summary") or "", limit=1000) or None,
                    "error_message": redact_sensitive_text(row.get("error_message") or "", limit=1000) or None,
                }
                for row in rows
            ],
            "total": len(rows),
        }
