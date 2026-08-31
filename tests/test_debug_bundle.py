import json
import zipfile

import pytest

from core.debug_bundle import (
    build_debug_bundle,
    export_debug_bundle,
    redact_debug_payload,
)


def test_redact_debug_payload_recursively_filters_sensitive_keys_and_text():
    payload = {
        "safe": "visible",
        "Authorization": "Bearer should-not-leak",
        "nested": {"profile": {"password": "secret-value"}},
        "items": ["plain", {"csrfToken": "csrf-value"}],
        "message": "request contained a private_key and token",
    }

    redacted = redact_debug_payload(payload)

    assert redacted["safe"] == "visible"
    assert redacted["Authorization"] == "[FILTERED]"
    assert redacted["nested"]["profile"]["password"] == "[FILTERED]"
    assert redacted["items"] == ["plain", {"csrfToken": "[FILTERED]"}]
    assert redacted["message"] == "[FILTERED]"
    assert redact_debug_payload({"credential_ref": "vault", "api_key": "key", "privateKey": "pem"}) == {
        "credential_ref": "[FILTERED]",
        "api_key": "[FILTERED]",
        "privateKey": "[FILTERED]",
    }
    assert redact_debug_payload({"private key": "PEM-MATERIAL", "api key": "KEY-MATERIAL"}) == {
        "private key": "[FILTERED]",
        "api key": "[FILTERED]",
    }
    assert payload["nested"]["profile"]["password"] == "secret-value"


def test_build_debug_bundle_filters_context_and_keeps_only_event_contract_fields():
    context = {"browser": "test", "session": "do-not-export"}
    events = [
        {
            "url": "https://example.test/health",
            "method": "GET",
            "status_code": 200,
            "elapsed_ms": 12,
            "request_headers": {"Accept": "application/json", "Cookie": "secret"},
            "response_headers": {"Content-Type": "application/json"},
            "request_params": {"q": "ok", "access_token": "secret"},
            "response_summary": {"ok": True},
            "correlation_id": "corr-1",
            "timestamp": "2026-08-31T00:00:00Z",
            "version": "v1",
            "unapproved": "must be omitted",
        }
    ]

    bundle = build_debug_bundle(context, events)

    assert bundle["filtered"] is True
    assert bundle["schemaVersion"] == "1"
    assert bundle["context"]["session"] == "[FILTERED]"
    assert set(bundle["events"][0]) == {
        "url",
        "method",
        "status_code",
        "elapsed_ms",
        "request_headers",
        "response_headers",
        "request_params",
        "response_summary",
        "correlation_id",
        "timestamp",
        "version",
    }
    assert bundle["events"][0]["request_headers"]["Cookie"] == "[FILTERED]"
    assert bundle["events"][0]["request_params"]["access_token"] == "[FILTERED]"


def test_export_debug_bundle_writes_json(tmp_path):
    bundle = build_debug_bundle({"ok": True}, [])
    output_path = tmp_path / "debug.json"

    result = export_debug_bundle(bundle, output_path, fmt="json")

    assert result == output_path
    assert json.loads(output_path.read_text(encoding="utf-8")) == bundle


def test_export_debug_bundle_writes_zip_containing_debug_json(tmp_path):
    bundle = build_debug_bundle({"ok": True}, [])
    output_path = tmp_path / "debug.zip"

    result = export_debug_bundle(bundle, output_path, fmt="zip")

    assert result == output_path
    with zipfile.ZipFile(output_path) as archive:
        assert archive.namelist() == ["debug.json"]
        assert json.loads(archive.read("debug.json")) == bundle


def test_export_debug_bundle_rejects_unknown_format_and_directory(tmp_path):
    bundle = build_debug_bundle({}, [])

    with pytest.raises(ValueError):
        export_debug_bundle(bundle, tmp_path / "debug.out", fmt="yaml")
    with pytest.raises(IsADirectoryError):
        export_debug_bundle(bundle, tmp_path, fmt="json")
