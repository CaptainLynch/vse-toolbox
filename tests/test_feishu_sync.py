# -*- coding: utf-8 -*-

import pytest

from services.feishu_imap import FeishuImapParser


def test_sync_unsynced_tasks_to_deliverables_marks_tasks_and_is_idempotent(tmp_db):
    parser = FeishuImapParser(tmp_db)

    synced_count = parser.sync_unsynced_tasks_to_deliverables()

    assert synced_count == 1
    with tmp_db.get_connection() as conn:
        task = conn.execute(
            "SELECT synced FROM feishu_tasks WHERE title='飞书任务1'"
        ).fetchone()
        deliverable = conn.execute(
            """
            SELECT project_id, name, owner, due_date, status, remark
            FROM deliverables
            WHERE remark LIKE '飞书待办同步:%'
            """
        ).fetchone()

    assert task["synced"] == 1
    assert deliverable["project_id"] == 1
    assert deliverable["name"] == "飞书任务1"
    assert deliverable["owner"] == "张三"
    assert deliverable["due_date"] == "2026-12-01"
    assert deliverable["status"] == "pending"

    assert parser.sync_unsynced_tasks_to_deliverables() == 0
    with tmp_db.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM deliverables WHERE remark LIKE '飞书待办同步:%'"
        ).fetchone()[0]
    assert count == 1


def test_sync_uses_fallback_title_for_empty_feishu_task(tmp_db):
    with tmp_db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO feishu_tasks (title, assignee, deadline, source_email_id, synced)
            VALUES ('', '', '', '', 0)
            """
        )

    parser = FeishuImapParser(tmp_db)
    synced_count = parser.sync_unsynced_tasks_to_deliverables()

    assert synced_count == 2
    with tmp_db.get_connection() as conn:
        deliverable = conn.execute(
            "SELECT name, owner, due_date FROM deliverables WHERE name=?",
            ("未命名飞书待办",),
        ).fetchone()

    assert deliverable["name"] == "未命名飞书待办"
    assert deliverable["owner"] == ""
    assert deliverable["due_date"] is None


def test_sync_rolls_back_without_marking_task_synced_on_insert_error(tmp_db):
    parser = FeishuImapParser(tmp_db)

    with pytest.raises(Exception):
        parser.sync_unsynced_tasks_to_deliverables(project_id=9999)

    with tmp_db.get_connection() as conn:
        task = conn.execute(
            "SELECT synced FROM feishu_tasks WHERE title='飞书任务1'"
        ).fetchone()
        count = conn.execute(
            "SELECT COUNT(*) FROM deliverables WHERE remark LIKE '飞书待办同步:%'"
        ).fetchone()[0]

    assert task["synced"] == 0
    assert count == 0


def test_scan_and_parse_calls_sync_bridge_and_returns_saved_count(monkeypatch, tmp_db):
    parser = FeishuImapParser(tmp_db)
    calls = []

    monkeypatch.setattr(parser, "_get_credentials", lambda: ("user@example.com", "secret"))
    monkeypatch.setattr(parser, "_connect", lambda username, password: None)
    monkeypatch.setattr(parser, "_disconnect", lambda: None)
    monkeypatch.setattr(parser, "_save_tasks", lambda tasks: 7)
    monkeypatch.setattr(
        parser,
        "sync_unsynced_tasks_to_deliverables",
        lambda project_id=1: calls.append(project_id) or 3,
    )

    class FakeConn:
        def select_folder(self, mailbox, readonly=False):
            return None

        def search(self, criteria):
            return [1]

        def fetch(self, ids, fields):
            raw = (
                b"From: Feishu <noreply@feishu.example>\r\n"
                b"Subject: Feishu task\r\n"
                b"Message-ID: <task-1>\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n"
                b"\r\n"
                + "任务标题: Review package\n负责人: Alice\n截止时间: 2026-12-31".encode("utf-8")
            )
            return {1: {b"RFC822": raw}}

    parser._conn = FakeConn()

    assert parser.scan_and_parse() == 7
    assert calls == [1]


def test_scan_and_parse_propagates_sync_failure(monkeypatch, tmp_db):
    parser = FeishuImapParser(tmp_db)

    monkeypatch.setattr(parser, "_get_credentials", lambda: ("user@example.com", "secret"))
    monkeypatch.setattr(parser, "_connect", lambda username, password: None)
    monkeypatch.setattr(parser, "_disconnect", lambda: None)
    monkeypatch.setattr(parser, "_is_feishu_email", lambda msg: True)
    monkeypatch.setattr(
        parser,
        "_parse_task_from_body",
        lambda body, email_id: {
            "title": "Review package",
            "assignee": "Alice",
            "deadline": "2026-12-31",
            "source_email_id": email_id,
        },
    )
    monkeypatch.setattr(parser, "_save_tasks", lambda tasks: 1)

    def fail_sync(project_id=1):
        raise RuntimeError("sync failed")

    monkeypatch.setattr(parser, "sync_unsynced_tasks_to_deliverables", fail_sync)

    class FakeConn:
        def select_folder(self, mailbox, readonly=False):
            return None

        def search(self, criteria):
            return [1]

        def fetch(self, ids, fields):
            raw = (
                b"From: Feishu <noreply@feishu.example>\r\n"
                b"Subject: Feishu task\r\n"
                b"Message-ID: <task-1>\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n"
                b"\r\n"
                b"task body"
            )
            return {1: {b"RFC822": raw}}

    parser._conn = FakeConn()

    with pytest.raises(RuntimeError, match="sync failed"):
        parser.scan_and_parse()
