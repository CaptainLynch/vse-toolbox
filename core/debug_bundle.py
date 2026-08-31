"""Safe, dependency-free debug bundle construction and export helpers."""

from __future__ import annotations

import json
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any


_SENSITIVE_TERMS = (
    "password",
    "token",
    "cookie",
    "authorization",
    "private_key",
    "secret",
    "session",
    "csrf",
    "credential",
    "api_key",
    "apikey",
    "privatekey",
)

_EVENT_FIELDS = (
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
)


def _is_sensitive_text(value: str) -> bool:
    lowered = value.casefold()
    compact = "".join(char for char in lowered if char.isalnum())
    return any(term in lowered or term.replace("_", "") in compact for term in _SENSITIVE_TERMS)


def redact_debug_payload(value: Any) -> Any:
    """Return a recursively copied payload with sensitive values replaced.

    Sensitive dictionary fields retain their field names for diagnostics, while
    their values are replaced. Any scalar text containing a sensitive term is
    replaced in full so credentials cannot remain embedded in larger strings.
    """

    if isinstance(value, Mapping):
        return {
            key: "[FILTERED]" if _is_sensitive_text(str(key)) else redact_debug_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_debug_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_debug_payload(item) for item in value)
    if isinstance(value, str):
        return "[FILTERED]" if _is_sensitive_text(value) else value
    return value


def build_debug_bundle(
    context: Mapping[str, Any] | None,
    events: Any,
    output_format: str = "json",
) -> dict[str, Any]:
    """Build a versioned, redacted debug bundle from context and events."""

    if output_format.casefold() != "json":
        raise ValueError(f"unsupported debug bundle format: {output_format!r}")

    filtered_events: list[dict[str, Any]] = []
    for event in events or []:
        if not isinstance(event, Mapping):
            continue
        filtered_events.append(
            {
                field: redact_debug_payload(event[field])
                for field in _EVENT_FIELDS
                if field in event
            }
        )

    return {
        "context": redact_debug_payload(context or {}),
        "events": filtered_events,
        "filtered": True,
        "schemaVersion": "1",
    }


def export_debug_bundle(
    bundle: Mapping[str, Any], output_path: str | Path, fmt: str = "json"
) -> Path:
    """Safely write a debug bundle as JSON or a ZIP containing ``debug.json``."""

    path = Path(output_path)
    if path.is_dir():
        raise IsADirectoryError(str(path))

    normalized_fmt = fmt.casefold() if isinstance(fmt, str) else fmt
    if normalized_fmt not in {"json", "zip"}:
        raise ValueError(f"unsupported debug bundle format: {fmt!r}")

    safe_bundle = redact_debug_payload(bundle)
    payload = json.dumps(safe_bundle, ensure_ascii=False, indent=2) + "\n"
    if normalized_fmt == "json":
        path.write_text(payload, encoding="utf-8")
    else:
        with zipfile.ZipFile(path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("debug.json", payload)
    return path


__all__ = ["build_debug_bundle", "export_debug_bundle", "redact_debug_payload"]
