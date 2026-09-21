"""Static contract tests for the deliverable unified status cards."""

from pathlib import Path


JS_PATH = Path("web/static/app.js")


def _source() -> str:
    return JS_PATH.read_text(encoding="utf-8-sig")


def _slice(text: str, start_marker: str, end_marker: str) -> str:
    start = text.find(start_marker)
    assert start != -1, f"Start marker '{start_marker}' not found"
    end = text.find(end_marker, start)
    assert end != -1, f"End marker '{end_marker}' not found after '{start_marker}'"
    return text[start:end]


def test_unified_status_loader_uses_encoded_deliverable_endpoint_and_public_contract() -> None:
    source = _source()
    assert "async function loadDeliverableUnifiedStatus" in source
    assert "/api/project-status/deliverables/${encodeURIComponent(item.id)}/unified-status" in source
    assert "body.ok !== true" in source
    assert "body.data && Array.isArray(body.data.objects)" in source


def test_unified_status_cards_show_three_kinds_and_public_state_fields() -> None:
    source = _source()
    renderer = _slice(source, "function renderDeliverableUnifiedStatus", "async function loadDeliverableEvidence")

    for marker in (
        "unified-status-cards",
        "unified-status-card",
        "EWO",
        "PAA",
        "NCR",
        "认证状态",
        "查询状态",
        "同步状态",
        "错误摘要",
        "last_updated",
        "auth_state",
        "query_state",
        "sync_state",
        "content",
        "report_type",
        "last_success_at",
    ):
        assert marker in renderer


def test_unified_status_failure_is_redacted_and_has_retry_entrypoint() -> None:
    source = _source()
    loader = _slice(source, "async function loadDeliverableUnifiedStatus", "function renderDeliverableEvidence")

    assert "unified-status-load-error" in loader
    assert "unified-status-retry-btn" in loader
    assert "redactSensitiveText" in loader
    assert "读取统一状态失败" in loader
    assert "loadDeliverableUnifiedStatus" in loader


def test_unified_status_loader_is_wired_into_existing_evidence_area() -> None:
    source = _source()
    loader = _slice(source, "async function loadDeliverableEvidence", "function renderDeliverableEvidence")

    assert "loadDeliverableUnifiedStatus" in loader
    assert "evidence-unified-status" in loader
