# -*- coding: utf-8 -*-

from pathlib import Path

import pytest

from services.feishu_imap import FeishuImapParser


class FakeIMAPClient:
    instances = []
    fail_login = False
    search_result = []
    fetch_result = {}

    def __init__(self, host, port=None, ssl=False):
        self.host = host
        self.port = port
        self.ssl = ssl
        self.login_args = None
        self.selected = None
        self.search_args = None
        self.fetch_args = None
        self.logged_out = False
        FakeIMAPClient.instances.append(self)

    def login(self, username, password):
        self.login_args = (username, password)
        if FakeIMAPClient.fail_login:
            raise RuntimeError("bad login")

    def select_folder(self, mailbox, readonly=False):
        self.selected = (mailbox, readonly)

    def search(self, criteria):
        self.search_args = criteria
        return list(FakeIMAPClient.search_result)

    def fetch(self, ids, fields):
        self.fetch_args = (ids, fields)
        return dict(FakeIMAPClient.fetch_result)

    def logout(self):
        self.logged_out = True


@pytest.fixture(autouse=True)
def reset_fake_client(monkeypatch):
    FakeIMAPClient.instances = []
    FakeIMAPClient.fail_login = False
    FakeIMAPClient.search_result = []
    FakeIMAPClient.fetch_result = {}
    monkeypatch.setattr("services.feishu_imap.IMAPClient", FakeIMAPClient)


def test_connect_uses_imapclient_ssl_port_and_login(tmp_db):
    parser = FeishuImapParser(tmp_db, imap_host="imap.example.test", imap_port=1993)

    parser._connect("user@example.com", "secret")

    client = FakeIMAPClient.instances[0]
    assert client.host == "imap.example.test"
    assert client.port == 1993
    assert client.ssl is True
    assert client.login_args == ("user@example.com", "secret")
    assert parser._conn is client


def test_connect_converts_login_failure_to_connection_error(tmp_db):
    FakeIMAPClient.fail_login = True
    parser = FeishuImapParser(tmp_db)

    with pytest.raises(ConnectionError):
        parser._connect("user@example.com", "secret")


def test_scan_and_parse_uses_imapclient_fetch_and_returns_saved_count(monkeypatch, tmp_db):
    raw = (
        b"From: Feishu <noreply@feishu.example>\r\n"
        b"Subject: Feishu task\r\n"
        b"Message-ID: <task-1>\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        "任务标题: Package signoff\n负责人: Alice\n截止时间: 2026-12-31".encode("utf-8")
    )
    FakeIMAPClient.search_result = [101]
    FakeIMAPClient.fetch_result = {101: {b"RFC822": raw}}
    saved_tasks = []
    synced_projects = []

    parser = FeishuImapParser(tmp_db)
    monkeypatch.setattr(parser, "_get_credentials", lambda: ("user@example.com", "secret"))
    monkeypatch.setattr(parser, "_save_tasks", lambda tasks: saved_tasks.extend(tasks) or 5)
    monkeypatch.setattr(
        parser,
        "sync_unsynced_tasks_to_deliverables",
        lambda project_id=1: synced_projects.append(project_id) or 2,
    )

    assert parser.scan_and_parse() == 5

    client = FakeIMAPClient.instances[0]
    assert client.selected == ("INBOX", False)
    assert client.search_args == ["UNSEEN"]
    assert client.fetch_args == ([101], ["RFC822"])
    assert len(saved_tasks) == 1
    assert saved_tasks[0]["title"] == "Package signoff"
    assert synced_projects == [1]
    assert parser._conn is None


def test_scan_and_parse_empty_search_returns_zero(monkeypatch, tmp_db):
    parser = FeishuImapParser(tmp_db)
    monkeypatch.setattr(parser, "_get_credentials", lambda: ("user@example.com", "secret"))

    assert parser.scan_and_parse() == 0


def test_disconnect_logs_out_and_clears_connection(tmp_db):
    parser = FeishuImapParser(tmp_db)
    parser._connect("user@example.com", "secret")
    client = FakeIMAPClient.instances[0]

    parser._disconnect()

    assert client.logged_out is True
    assert parser._conn is None


def test_disconnect_clears_connection_when_logout_fails(tmp_db):
    class LogoutFailClient(FakeIMAPClient):
        def logout(self):
            raise RuntimeError("logout failed")

    parser = FeishuImapParser(tmp_db)
    parser._conn = LogoutFailClient("imap.example.test")

    parser._disconnect()

    assert parser._conn is None


def test_feishu_imap_source_has_no_imaplib():
    source = (Path(__file__).resolve().parent.parent / "services" / "feishu_imap.py").read_text(
        encoding="utf-8"
    )

    assert "imaplib" not in source
