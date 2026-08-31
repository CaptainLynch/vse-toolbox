"""Static contract tests for the deliverable unified status cards."""

from pathlib import Path


JS_PATH = Path("web/static/app.js")


def _source() -> str:
    return JS_PATH.read_text(encoding="utf-8-sig")


def test_unified_status_loader_uses_encoded_deliverable_endpoint_and_public_contract() -> None:
    source = _source()
    assert "async function loadDeliverableUnifiedStatus" in source
    assert "/api/project-status/deliverables/${encodeURIComponent(item.id)}/unified-status" in source
    assert "body.ok !== true" in source
    assert "body.data && Array.isArray(body.data.objects)" in source


def test_unified_status_cards_show_three_kinds_and_public_state_fields() -> None:
    source = _source()
    start = source.index("function renderDeliverableUnifiedStatus")
    end = source.index("async function loadDeliverableEvidence")
    renderer = source[start:end]

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
    start = source.index("async function loadDeliverableUnifiedStatus")
    end = source.index("function renderDeliverableEvidence")
    loader = source[start:end]

    assert "unified-status-load-error" in loader
    assert "unified-status-retry-btn" in loader
    assert "redactSensitiveText" in loader
    assert "读取统一状态失败" in loader
    assert "loadDeliverableUnifiedStatus" in loader


def test_unified_status_loader_is_wired_into_existing_evidence_area() -> None:
    source = _source()
    start = source.index("async function loadDeliverableEvidence")
    end = source.index("function renderDeliverableEvidence")
    loader = source[start:end]

    assert "loadDeliverableUnifiedStatus" in loader
    assert "evidence-unified-status" in loader
