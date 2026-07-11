# -*- coding: utf-8 -*-

import ast
import subprocess
from pathlib import Path

import core.config as config
from core.redaction import redact_sensitive_text, safe_display_value
from services.feishu_imap import FeishuImapParser


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
    assert "valueCell.textContent = safeDisplayValue(value)" in source
    assert "td.textContent = safeDisplayValue(row[key])" in source
    assert "showArasError(redactSensitiveText(err.message))" in source
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
