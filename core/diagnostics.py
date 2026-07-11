# -*- coding: utf-8 -*-
"""Local Markdown diagnostics for CLI troubleshooting."""

from __future__ import annotations

import os
import platform
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
    ) -> None:
        self.options = options
        self.base_url = base_url
        self.mode = mode
        self.inputs = dict(inputs or {})
        self.output_dir = output_dir
        self.created_at = datetime.now()
        self.started = time.perf_counter()
        self.sections: list[tuple[str, str]] = []
        if self.options.enabled:
            self.record_runtime_snapshot()

    def scrub(self, value: Any) -> str:
        text = "" if value is None else str(value)
        if self.options.unsafe_raw:
            return _escape_control_chars(text)
        return _escape_control_chars(redact_sensitive_text(text))

    def record_runtime_snapshot(self) -> None:
        parsed = urlsplit(self.base_url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80 if parsed.scheme == "http" else None)
        dns_rows: list[str] = []
        if host:
            try:
                addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, port or 0)})
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
            runtime.extend(f"- `{key}`: `{self.scrub(value)}`" for key, value in self.inputs.items())
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
        path = self.output_dir / f"aras_cli_debug{raw_suffix}_{stamp}.md"
        duration = time.perf_counter() - self.started
        lines = [
            "# Aras CLI Diagnostic Report",
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
        return "\n".join(f"{key}: {item}" for key, item in value.items())
    return str(value)


def _escape_control_chars(value: str) -> str:
    return "".join(
        char if char in "\n\r\t" or (ord(char) >= 32 and ord(char) != 127) else f"\\x{ord(char):02x}"
        for char in value
    )
