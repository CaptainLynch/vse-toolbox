# -*- coding: utf-8 -*-
"""Local Markdown diagnostics for CLI troubleshooting."""

from __future__ import annotations

import os
import platform
import re
import socket
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from core.config import DIAGNOSTIC_DIR, PROJECT_ROOT
from core.redaction import redact_sensitive_text


_REDACTED = "[redacted]"
_SENSITIVE_KEY_SUFFIXES = (
    "authorization",
    "cookie",
    "token",
    "apikey",
    "sid",
    "sessionid",
    "csrf",
    "xsrf",
    "secret",
    "password",
    "passwd",
    "passphrase",
)
_SENSITIVE_KEY_EXACT = {
    "arasauth",
    "credential",
    "credentials",
    "jsessionid",
    "pwd",
}
_PERMANENT_SECRET_JSON_RE = re.compile(
    r"(?i)(['\"])(password|passwd|pwd|passphrase|(?:client[_-]?)?secret)\1"
    r"(\s*:\s*)(['\"])(?:\\.|(?!\4)[\s\S])*?\4"
)
_PERMANENT_SECRET_PARAM_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|passphrase|(?:client[_-]?)?secret)\b"
    r"(\s*[:=]\s*)(?:Bearer\s+)?([^,\s;'\"}\]\[<]+)"
)
_URL_USERINFO_RE = re.compile(
    r"(?i)\b(https?://)([^/@\s:]+):([^/@\s]+)@"
)


@dataclass(frozen=True)
class DiagnosticOptions:
    enabled: bool = False
    unsafe_raw: bool = False


class MarkdownDiagnosticReport:
    """Collect CLI crawler diagnostics and persist them as a local Markdown file."""

    def __init__(
        self,
        *,
        options: DiagnosticOptions,
        base_url: str,
        mode: str,
        inputs: Mapping[str, Any] | None = None,
        output_dir: Path = DIAGNOSTIC_DIR,
        report_title: str = "Aras CLI Diagnostic Report",
        file_name_prefix: str = "aras_cli_debug",
        allow_unsafe_raw: bool = True,
    ) -> None:
        if options.unsafe_raw and not allow_unsafe_raw:
            raise ValueError("unsafe_raw diagnostics are not allowed for this report")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", file_name_prefix):
            raise ValueError("file_name_prefix may contain only letters, numbers, underscore, and hyphen")
        self.options = options
        self.base_url = base_url
        self.mode = mode
        self.inputs = dict(inputs or {})
        self.output_dir = output_dir
        self.report_title = report_title
        self.file_name_prefix = file_name_prefix
        self.created_at = datetime.now()
        self.started = time.perf_counter()
        self.sections: list[tuple[str, str]] = []
        if self.options.enabled:
            self.record_runtime_snapshot()

    def scrub(self, value: Any) -> str:
        text = "" if value is None else str(value)
        text = _redact_permanent_secret_text(text)
        if self.options.unsafe_raw:
            return _escape_control_chars(text)
        return _escape_control_chars(redact_sensitive_text(text))

    def scrub_keyed(self, key: Any, value: Any) -> str:
        if _is_sensitive_key(key):
            return _REDACTED
        return self.scrub(_format_payload(value))

    def record_runtime_snapshot(self) -> None:
        parsed = urlsplit(self.base_url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80 if parsed.scheme == "http" else None)
        dns_rows: list[str] = []
        if host:
            try:
                addresses = sorted({str(item[4][0]) for item in socket.getaddrinfo(host, port or 0)})
                dns_rows.append(f"- DNS: `{host}` -> `{', '.join(addresses)}`")
            except Exception as exc:  # pragma: no cover - depends on local network
                dns_rows.append(f"- DNS: `{host}` lookup failed: `{type(exc).__name__}: {self.scrub(exc)}`")
        else:
            dns_rows.append("- DNS: no host parsed from base_url")

        proxy_keys = ["HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy"]
        proxy_lines = [f"- `{key}`: `{self.scrub(os.environ.get(key, ''))}`" for key in proxy_keys if os.environ.get(key)]
        if not proxy_lines:
            proxy_lines.append("- No proxy environment variables detected")

        runtime = [
            f"- Generated at: `{self.created_at.isoformat(timespec='seconds')}`",
            f"- Mode: `{self.mode}`",
            f"- Diagnostic mode: `{'raw/unsafe' if self.options.unsafe_raw else 'safe'}`",
            f"- Base URL: `{self.scrub(self.base_url)}`",
            f"- CWD: `{Path.cwd()}`",
            f"- Project root: `{PROJECT_ROOT}`",
            f"- Python: `{sys.version.replace(os.linesep, ' ')}`",
            f"- Platform: `{platform.platform()}`",
            f"- Machine: `{platform.machine()}`",
            f"- Processor: `{platform.processor()}`",
            f"- CPU count: `{os.cpu_count()}`",
            f"- Hostname: `{socket.gethostname()}`",
            f"- Frozen executable: `{bool(getattr(sys, 'frozen', False))}`",
        ]
        if self.inputs:
            runtime.append("")
            runtime.append("### CLI Inputs")
            runtime.extend(
                f"- `{key}`: `{self.scrub_keyed(key, value)}`"
                for key, value in self.inputs.items()
            )
        runtime.append("")
        runtime.append("### Network")
        runtime.extend(dns_rows)
        runtime.extend(proxy_lines)
        self.sections.append(("Runtime and Network Snapshot", "\n".join(runtime)))

    def record_http_event(self, event: Any) -> None:
        if not self.options.enabled:
            return
        fields = _event_to_mapping(event)
        title = f"HTTP Trace - {fields.get('stage', 'request')}"
        lines = [
            f"- Stage: `{self.scrub(fields.get('stage', ''))}`",
            f"- Method: `{self.scrub(fields.get('method', ''))}`",
            f"- URL: `{self.scrub(fields.get('url', ''))}`",
            f"- Elapsed ms: `{self.scrub(fields.get('elapsed_ms', ''))}`",
            f"- Status: `{self.scrub(fields.get('status_code', ''))}`",
            f"- Reason: `{self.scrub(fields.get('reason', ''))}`",
        ]
        extended_fields = [
            ("Timestamp", "timestamp"),
            ("Request ID", "request_id"),
            ("Page Type", "page_type"),
            ("Origin", "origin"),
            ("Path", "path"),
            ("Query", "query"),
            ("Page", "page"),
            ("Page Size", "page_size"),
            ("Attempt", "attempt"),
            ("Timeout", "timeout"),
            ("Content-Type", "content_type"),
            ("Content-Length", "content_length"),
            ("JSON Fields", "json_fields"),
            ("Record Count", "record_count"),
            ("Total", "total"),
            ("Pages", "pages"),
            ("Accumulated Count", "accumulated_count"),
            ("Unique Count", "unique_count"),
            ("Duplicate Count", "duplicate_count"),
            ("Current Page", "current_page"),
            ("Estimated Pages", "estimated_pages"),
            ("Stop Reason", "stop_reason"),
            ("File Name", "file_name"),
            ("Saved Path", "saved_path"),
            ("Bytes Written", "bytes_written"),
            ("Validation", "validation"),
            ("Exception Type", "exception_type"),
            ("Completed Pages", "completed_pages"),
        ]
        for label, key in extended_fields:
            value = fields.get(key)
            if value is None or value == "" or value == () or value == {}:
                continue
            lines.append(f"- {label}: `{self.scrub(_format_payload(value))}`")
        for label, key in [
            ("Request Headers", "request_headers"),
            ("Request Body", "request_body"),
            ("Response Headers", "response_headers"),
            ("Response Body", "response_body"),
            ("Exception", "exception"),
        ]:
            value = fields.get(key)
            if value is None or value == "":
                continue
            lines.append("")
            lines.append(f"### {label}")
            lines.append("```text")
            lines.append(self.scrub(_format_payload(value)))
            lines.append("```")
        self.sections.append((title, "\n".join(lines)))

    def record_exception(self, exc: BaseException) -> None:
        if not self.options.enabled:
            return
        text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        self.sections.append(("Exception Traceback", f"```text\n{self.scrub(text)}\n```"))

    def save(self, status: str) -> Path | None:
        if not self.options.enabled:
            return None
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = self.created_at.strftime("%Y%m%d_%H%M%S")
        raw_suffix = "_raw" if self.options.unsafe_raw else ""
        path = self.output_dir / f"{self.file_name_prefix}{raw_suffix}_{stamp}.md"
        duration = time.perf_counter() - self.started
        lines = [
            f"# {self.scrub(self.report_title)}",
            "",
            f"- Status: `{status}`",
            f"- Duration seconds: `{duration:.3f}`",
            f"- Generated at: `{datetime.now().isoformat(timespec='seconds')}`",
            f"- Unsafe raw output: `{'yes' if self.options.unsafe_raw else 'no'}`",
        ]
        if self.options.unsafe_raw:
            lines.extend(
                [
                    "",
                    "> WARNING: This report may contain raw Cookie, token, Authorization, and response data. Do not commit or share it.",
                ]
            )
        for title, body in self.sections:
            lines.extend(["", f"## {title}", "", body])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path


def _event_to_mapping(event: Any) -> Mapping[str, Any]:
    if isinstance(event, Mapping):
        return event
    data = getattr(event, "__dict__", None)
    if isinstance(data, Mapping):
        return data
    return {}


def _format_payload(value: Any) -> str:
    if isinstance(value, Mapping):
        return "\n".join(
            f"{key}: {_format_keyed_payload_value(key, item)}"
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_format_payload(item) for item in value) + "]"
    return str(value)


def _format_keyed_payload_value(key: Any, value: Any) -> str:
    if _is_sensitive_key(key):
        return _REDACTED
    return _format_payload(value)


def _is_sensitive_key(key: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "", str(key).casefold())
    if normalized in _SENSITIVE_KEY_EXACT:
        return True
    if any(
        marker in normalized
        for marker in (
            "authorization",
            "cookie",
            "credential",
            "token",
            "apikey",
            "sessionid",
            "csrf",
            "xsrf",
            "secret",
            "password",
            "passwd",
            "passphrase",
        )
    ):
        return True
    return any(normalized.endswith(suffix) for suffix in _SENSITIVE_KEY_SUFFIXES)


def _redact_permanent_secret_text(value: str) -> str:
    value = _URL_USERINFO_RE.sub(
        lambda match: f"{match.group(1)}{_REDACTED}:{_REDACTED}@",
        value,
    )
    value = _PERMANENT_SECRET_JSON_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{match.group(1)}"
        f"{match.group(3)}{match.group(4)}{_REDACTED}{match.group(4)}",
        value,
    )
    return _PERMANENT_SECRET_PARAM_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{_REDACTED}",
        value,
    )


def _escape_control_chars(value: str) -> str:
    return "".join(
        char if char in "\n\r\t" or (ord(char) >= 32 and ord(char) != 127) else f"\\x{ord(char):02x}"
        for char in value
    )
