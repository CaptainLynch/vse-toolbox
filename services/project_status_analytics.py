# -*- coding: utf-8 -*-
"""Read-only analytics derived exclusively from saved sync evidence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from core.db_manager import DatabaseManager
from core.redaction import redact_sensitive_text


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


class ProjectStatusAnalyticsService:
    def __init__(self, db: DatabaseManager, *, stale_hours: int = 24) -> None:
        self.db = db
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
            latest_audit = policy.get("latest_audit")
            items.append({
                "deliverableId": deliverable_id,
                "authoritativeSource": row["source"],
                "lastAttemptAt": binding.get("last_attempt_at"),
                "lastSuccessAt": binding.get("last_success_at"),
                "freshness": freshness,
                "syncState": binding.get("sync_state"),
                "failureCount": state_counts.get("failed", 0),
                "runTrend": state_counts,
                "externalRecordCount": None,
                "confirmedDifference": latest_audit["result"] if latest_audit else None,
                "needsAttention": binding.get("sync_state") == "needs_attention",
                "riskSummary": redact_sensitive_text(
                    binding.get("last_error_message") or "", limit=300
                ) or None,
                "mappingStability": {
                    "confirmed": self.db.mapping_stability_count(deliverable_id),
                    "required": 2,
                },
            })
        return {"phaseId": "VPI-T2", "staleAfterHours": 24, "deliverables": items}

    def runs(self, deliverable_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        rows = self.db.list_sync_runs(deliverable_id, limit)
        return {
            "runs": [
                {**row,
                 "result_summary": redact_sensitive_text(row.get("result_summary") or "", limit=1000) or None,
                 "error_message": redact_sensitive_text(row.get("error_message") or "", limit=1000) or None}
                for row in rows
            ],
            "total": len(rows),
        }
