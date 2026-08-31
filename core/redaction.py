# -*- coding: utf-8 -*-
"""Shared redaction helpers for interface adapters."""

from __future__ import annotations

import re

_SENSITIVE_NAMES = (
    r"authorization|set-cookie|cookie|token|api_key|apikey|credential_ref|credentialref|private_key|privatekey|sid|sessionid|arasauth|jsessionid|csrf|secret|password"
)

_JSON_RE = re.compile(
    rf"(?i)(['\"])\s*({_SENSITIVE_NAMES})\s*\1(\s*:\s*)(['\"])(?:\\.|(?!\4).)*\4"
)
_AUTH_HEADER_RE = re.compile(
    r"(?i)\b(authorization)\b(\s*[:=]\s*)(.*?)"
    r"(?=(?:\s|,\s*)\b(?:set-cookie|cookie|token|api_key|sid|sessionid|arasauth|jsessionid|csrf|secret|password)\b\s*[:=]|[\r\n}\]\[]|$)"
)
_COOKIE_HEADER_RE = re.compile(
    r"(?i)\b(set-cookie|cookie)\b(\s*[:=]\s*)(.*?)"
    r"(?=(?:\s|,\s*)\b(?:authorization|set-cookie|cookie)\b\s*:|[\r\n}\]\[]|$)"
)
_PARAM_RE = re.compile(rf"(?i)\b({_SENSITIVE_NAMES})=([^&\s,;'\"}}\]\[]+)")
_HEADER_RE = re.compile(
    rf"(?i)\b(token|api_key|sid|sessionid|csrf|secret|password)\b"
    r"(\s*[:=]\s*)(?:Bearer\s+)?([^,\s;'\"}\]\[]+)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+([^,\s;'\"}\]\[]+)")
_PEM_RE = re.compile(
    r"(?is)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----"
)
_SENSITIVE_LABEL_RE = re.compile(
    r"(?i)\b(?:credential[ _-]?ref|private[ _-]?key)\b\s*[:=]\s*([^,\s;]+)"
)
_WHITESPACE_RE = re.compile(r"\s+")


def redact_sensitive_text(
    value: object,
    *,
    limit: int | None = None,
    collapse_newlines: bool = False,
) -> str:
    """Return text with credentials and auth-like fragments removed."""
    text = str(value)
    text = _PEM_RE.sub("[private key redacted]", text)
    text = _SENSITIVE_LABEL_RE.sub(lambda match: match.group(0).split(match.group(1), 1)[0] + "[redacted]", text)
    text = _JSON_RE.sub(r"\1\2\1\3\4[redacted]\4", text)
    text = _AUTH_HEADER_RE.sub(r"\1\2[redacted]", text)
    text = _COOKIE_HEADER_RE.sub(r"\1\2[redacted]", text)
    text = _HEADER_RE.sub(r"\1\2[redacted]", text)
    text = _PARAM_RE.sub(r"\1=[redacted]", text)
    text = _BEARER_RE.sub("Bearer [redacted]", text)
    if collapse_newlines:
        text = _WHITESPACE_RE.sub(" ", text).strip()
    if limit is not None and len(text) > limit:
        text = text[:limit]
    return text


def safe_display_value(value: object, *, empty: str = "-") -> str:
    """Format a display value without leaking sensitive content."""
    if value is None:
        return empty
    text = str(value)
    if not text.strip():
        return empty
    return redact_sensitive_text(text)
