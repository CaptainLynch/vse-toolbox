# -*- coding: utf-8 -*-

import ast
import logging
import subprocess
from pathlib import Path

import pytest
from rich.console import Console

import main
import core.config as config
from core.diagnostics import DiagnosticOptions, MarkdownDiagnosticReport
from core.redaction import redact_sensitive_text, safe_display_value
from services.feishu_imap import FeishuImapParser
from services.tdc_crawler import TDCCrawlerClient, TDCCrawlerError, TDCHttpDiagnosticEvent


ROOT = Path(__file__).resolve().parent.parent


def test_feishu_credentials_use_getpass_for_password(monkeypatch, tmp_db):
    prompts = []

    monkeypatch.setattr(
        "services.feishu_imap.Prompt.ask",
        lambda prompt: prompts.append(prompt) or "user@example.com",
    )
    monkeypatch.setattr(
        "services.feishu_imap.getpass.getpass",
        lambda prompt: "secret-password",
    )

    username, password = FeishuImapParser(tmp_db)._get_credentials()

    assert username == "user@example.com"
    assert password == "secret-password"
    assert len(prompts) == 1
    assert "密码" not in prompts[0]


def _prompt_ask_calls_with_sensitive_text(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    sensitive_calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_prompt_ask = (
            isinstance(func, ast.Attribute)
            and func.attr == "ask"
            and isinstance(func.value, ast.Name)
            and func.value.id == "Prompt"
        )
        if not is_prompt_ask or not node.args:
            continue
        first_arg = node.args[0]
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            text = first_arg.value.lower()
            if any(word in text for word in ("password", "token", "secret", "密码")):
                sensitive_calls.append(first_arg.value)
    return sensitive_calls


def test_no_plaintext_password_prompt_in_feishu_imap():
    path = ROOT / "services" / "feishu_imap.py"

    assert _prompt_ask_calls_with_sensitive_text(path) == []


def test_intranet_scraper_keeps_manual_browser_login_without_terminal_secret_prompt():
    path = ROOT / "services" / "intranet_scraper.py"
    source = path.read_text(encoding="utf-8")

    assert _prompt_ask_calls_with_sensitive_text(path) == []
    assert "getpass" not in source


def test_config_has_no_sensitive_constants():
    sensitive_names = [
        name
        for name in dir(config)
        if any(word in name.lower() for word in ("password", "token", "secret"))
    ]

    assert sensitive_names == []


def test_redaction_handles_json_header_query_and_bearer_shapes():
    text = (
        '{"Authorization":"Bearer abc","token":"tok123"} '
        "Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3 Authorization: Bearer xyz789 "
        "Set-Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3 "
        "api_key=key456&csrf=csrf789 password=hidden"
    )

    redacted = redact_sensitive_text(text)

    for secret in ("abc", "tok123", "abc123", "secret2", "secret3", "xyz789", "key456", "csrf789", "hidden"):
        assert secret not in redacted
    assert "[redacted]" in redacted


def test_redaction_redacts_cookie_segments_without_swallowing_following_content():
    samples = [
        "Authorization: Basic dXNlcjpwYXNz\nNext: ok",
        'Authorization: Digest username="u", response="secret-response"\nNext: ok',
        "Authorization: Negotiate secret-negotiate\nNext: ok",
        "Authorization: CustomScheme secret-value\nNext: ok",
        '{"Authorization":"Basic dXNlcjpwYXNz","next":"ok"}',
        r'{"Authorization":"Digest username=\"u\", response=\"secret-response\"","next":"ok"}',
        "Set-Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3\nNext: ok",
        'Set-Cookie: sid="abc,def"; Path=/\nNext: ok',
        '{"Set-Cookie":"sid=abc123; ArasAuth=secret2; JSESSIONID=secret3","Next":"ok"}',
        r'{"Set-Cookie":"sid=\"abc,def\"; Path=/","Next":"ok"}',
        "Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3\nNext: ok",
        '{"Cookie":"sid=abc123; ArasAuth=secret2; JSESSIONID=secret3","Next":"ok"}',
    ]

    for sample in samples:
        redacted = redact_sensitive_text(sample)
        for secret in (
            "dXNlcjpwYXNz",
            "secret-response",
            "secret-negotiate",
            "secret-value",
            "abc123",
            "abc,def",
            "def",
            "secret2",
            "secret3",
        ):
            assert secret not in redacted
        assert "Next" in redacted or "next" in redacted
        assert "ok" in redacted


def test_redaction_limit_and_newline_collapse():
    text = "line1\nCookie: sid=abc123\n" + ("x" * 300)

    redacted = redact_sensitive_text(text, limit=240, collapse_newlines=True)

    assert "\n" not in redacted
    assert "abc123" not in redacted
    assert len(redacted) == 240
    assert safe_display_value(None) == "-"
    assert safe_display_value("") == "-"


def test_web_frontend_redacts_sensitive_result_values_before_rendering():
    source = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")

    assert "function redactSensitiveText(value)" in source
    assert "function safeDisplayValue(value)" in source
    assert "function renderSummary(data)" in source
    assert "function renderExportSummary(data)" in source
    assert "valueCell.textContent = safeDisplayValue(value)" in source
    assert "formatArasApiError(err.safeError)" in source
    assert "safeError.message" not in source
    aras_job_section = source[source.index("class ArasJobUiError") : source.index("function setupPanels")]
    assert "err.message" not in aras_job_section
    assert "raw_xml" in source

    script = r"""
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync("web/static/app.js", "utf8");
const prefix = source.slice(0, source.indexOf("const ARAS_MODES"));
const redact = source.match(/function redactSensitiveText\(value\) \{[\s\S]*?\n\}/)[0];
const context = {};
vm.runInNewContext(prefix + "\n" + redact + `
result = [
  redactSensitiveText('Authorization: Basic dXNlcjpwYXNz\\nNext: ok'),
  redactSensitiveText('Authorization: Digest username="u", response="secret-response"\\nNext: ok'),
  redactSensitiveText('Authorization: CustomScheme secret-value\\nNext: ok'),
  redactSensitiveText('{"Authorization":"Basic dXNlcjpwYXNz","next":"ok"}'),
  redactSensitiveText('{"Authorization":"Digest username=\\\\"u\\\\", response=\\\\"secret-response\\\\"","next":"ok"}'),
  redactSensitiveText('Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3 Authorization: Bearer xyz789 Set-Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3'),
  redactSensitiveText('Set-Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3\\nNext: ok'),
  redactSensitiveText('Set-Cookie: sid="abc,def"; Path=/\\nNext: ok'),
  redactSensitiveText('{"Set-Cookie":"sid=abc123; ArasAuth=secret2; JSESSIONID=secret3","Next":"ok"}'),
  redactSensitiveText('{"Set-Cookie":"sid=\\\\"abc,def\\\\"; Path=/","Next":"ok"}'),
  redactSensitiveText('Cookie: sid=abc123; ArasAuth=secret2; JSESSIONID=secret3\\nNext: ok'),
  redactSensitiveText('{"Cookie":"sid=abc123; ArasAuth=secret2; JSESSIONID=secret3","Next":"ok"}')
].join("\\n");
`, context);
process.stdout.write(context.result);
"""
    result = subprocess.run(["node", "-e", script], cwd=ROOT, check=True, capture_output=True, text=True)
    assert "abc123" not in result.stdout
    assert "secret2" not in result.stdout
    assert "secret3" not in result.stdout
    assert "xyz789" not in result.stdout
    assert "dXNlcjpwYXNz" not in result.stdout
    assert "secret-response" not in result.stdout
    assert "secret-value" not in result.stdout
    assert "abc,def" not in result.stdout
    assert "def" not in result.stdout
    assert "Next" in result.stdout
    assert "ok" in result.stdout


def test_tdc_source_isolated_from_sensitive_material_and_gitignored():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    source_paths = [
        ROOT / "services" / "tdc_auth.py",
        ROOT / "services" / "tdc_crawler.py",
        ROOT / "main.py",
        ROOT / "core" / "diagnostics.py",
    ]
    forbidden = "fictional-persisted-credential"

    assert "/爬虫源文件/" in gitignore
    assert all(forbidden not in path.read_text(encoding="utf-8-sig") for path in source_paths)
    assert "00_登录过程_原始.har" not in (ROOT / "services" / "tdc_crawler.py").read_text(encoding="utf-8")
    assert "00_登录过程_原始.har" not in (ROOT / "services" / "tdc_auth.py").read_text(encoding="utf-8")


class _FailingTDCSession:
    def get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        del url, kwargs
        raise RuntimeError(
            "Cookie: sid=fictional-cookie-secret Authorization: Bearer fictional-auth-secret "
            "token=fictional-query-secret"
        )


def test_tdc_console_log_error_and_diagnostic_report_share_redaction(monkeypatch, tmp_path, caplog):  # type: ignore[no-untyped-def]
    event = TDCHttpDiagnosticEvent(
        timestamp="2026-07-19T10:11:12.123",
        stage="request",
        request_id="safe1234",
        page_type="sor",
        path="/sp/sor/sorPage",
        query={"token": "fictional-query-secret"},
        request_headers={
            "Cookie": "sid=fictional-cookie-secret",
            "Authorization": "Bearer fictional-auth-secret",
        },
        reason=(
            "Cookie: sid=fictional-cookie-secret Authorization: Bearer fictional-auth-secret "
            "token=fictional-query-secret"
        ),
    )
    console = Console(record=True, width=160)
    monkeypatch.setattr(main, "console", console)
    main._tdc_console_debug_hook(event)

    report = MarkdownDiagnosticReport(
        options=DiagnosticOptions(enabled=True),
        base_url="https://tdc.example",
        mode="sor",
        output_dir=tmp_path,
        report_title="TDC CLI Diagnostic Report",
        file_name_prefix="tdc_cli_debug",
        allow_unsafe_raw=False,
    )
    report.record_http_event(event)
    path = report.save("failed")
    assert path is not None

    caplog.set_level(logging.DEBUG, logger="vse_toolbox.tdc_crawler")
    with pytest.raises(TDCCrawlerError) as excinfo:
        TDCCrawlerClient("https://tdc.example", session=_FailingTDCSession()).query_sor_page()

    combined = "\n".join(
        [console.export_text(), path.read_text(encoding="utf-8"), caplog.text, str(excinfo.value)]
    )
    for secret in ("fictional-cookie-secret", "fictional-auth-secret", "fictional-query-secret"):
        assert secret not in combined
    assert "[redacted]" in combined
