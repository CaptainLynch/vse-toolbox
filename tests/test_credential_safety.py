# -*- coding: utf-8 -*-

import ast
from pathlib import Path

import core.config as config
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
    tree = ast.parse(path.read_text(encoding="utf-8"))
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
