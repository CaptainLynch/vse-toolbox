"""Static contract tests for the deliverable debug tools UI."""

from pathlib import Path


JS_PATH = Path("web/static/app.js")


def test_deliverable_evidence_exposes_debug_tools_and_filtered_notice() -> None:
    source = JS_PATH.read_text(encoding="utf-8-sig")
    evidence = source[source.index("function renderDeliverableEvidence"):]

    assert "Debug 工具" in evidence
    assert "敏感字段已过滤" in evidence
    assert "policy" in evidence and "analytics" in evidence
    assert "mapping" in evidence and "runs" in evidence
    assert "复制诊断摘要" in evidence
    assert "下载 JSON" in evidence
    assert "下载 ZIP" in evidence


def test_debug_tools_use_encoded_bundle_endpoint_for_json_and_zip() -> None:
    source = JS_PATH.read_text(encoding="utf-8-sig")
    evidence = source[source.index("function renderDeliverableEvidence"):]

    assert "/api/project-status/deliverables/${encodeURIComponent(item.id)}/debug-bundle" in evidence
    assert "format=json" in evidence
    assert "format=zip" in evidence


def test_debug_tools_copy_sanitized_summary_and_download_binary_blob() -> None:
    source = JS_PATH.read_text(encoding="utf-8-sig")
    evidence = source[source.index("function renderDeliverableEvidence"):]

    assert "navigator.clipboard.writeText" in evidence
    assert "redactSensitiveText" in evidence
    assert "response.blob()" in evidence
    assert "URL.createObjectURL" in evidence
    assert "URL.revokeObjectURL" in evidence


def test_debug_summary_redacts_sensitive_keys_before_serialization() -> None:
    source = JS_PATH.read_text(encoding="utf-8-sig")

    assert "function redactDeliverableDebugValue" in source
    assert "debugBundleSensitiveKey" in source
    assert '"[FILTERED]"' in source
    assert 'const sections = ["policy", "analytics", "mapping", "runs"]' in source
