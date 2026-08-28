"""Credential-safe XML capture helpers for the local Aras WebUI."""

from __future__ import annotations

import re

from core.redaction import redact_sensitive_text


DEFAULT_MAX_ARAS_XML_BYTES = 8 * 1024 * 1024
_SENSITIVE_XML_NAMES = (
    "authorization",
    "cookie",
    "password",
    "token",
    "secret",
    "session",
    "csrf",
    "set-cookie",
)
_SENSITIVE_XML_NAME_PATTERN = "|".join(re.escape(name) for name in _SENSITIVE_XML_NAMES)
_SENSITIVE_ELEMENT_RE = re.compile(
    rf"(?is)<(?P<tag>(?:[A-Za-z_][\w.-]*:)?(?:{_SENSITIVE_XML_NAME_PATTERN}))"
    rf"\b[^>]*>.*?</(?P=tag)\s*>"
)
_SENSITIVE_EMPTY_ELEMENT_RE = re.compile(
    rf"(?is)<(?P<tag>(?:[A-Za-z_][\w.-]*:)?(?:{_SENSITIVE_XML_NAME_PATTERN}))"
    rf"\b[^>]*/\s*>"
)


class ArasXmlCaptureError(ValueError):
    """Raised when an XML capture cannot be safely bounded or sanitized."""


def sanitize_aras_xml(
    value: object,
    *,
    max_bytes: int = DEFAULT_MAX_ARAS_XML_BYTES,
) -> str:
    """Preserve report XML while removing auth-like nodes and text fragments."""
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    text = "" if value is None else str(value)
    if len(text.encode("utf-8")) > max_bytes:
        raise ArasXmlCaptureError("Aras XML capture exceeds the configured size limit")

    def replace_element(match: re.Match[str]) -> str:
        tag = match.group("tag")
        return f"<{tag}>[redacted]</{tag}>"

    def replace_empty_element(match: re.Match[str]) -> str:
        return f"<{match.group('tag')}/>"

    sanitized = _SENSITIVE_ELEMENT_RE.sub(replace_element, text)
    sanitized = _SENSITIVE_EMPTY_ELEMENT_RE.sub(replace_empty_element, sanitized)
    sanitized = redact_sensitive_text(sanitized)
    if len(sanitized.encode("utf-8")) > max_bytes:
        raise ArasXmlCaptureError("sanitized Aras XML capture exceeds the size limit")
    return sanitized


__all__ = [
    "ArasXmlCaptureError",
    "DEFAULT_MAX_ARAS_XML_BYTES",
    "sanitize_aras_xml",
]
