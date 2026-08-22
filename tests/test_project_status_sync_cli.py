# -*- coding: utf-8 -*-
"""M2A CLI 契约测试：project-status-sync --once 入口。"""

from __future__ import annotations

import json

import pytest

import main as main_module
from core.db_manager import DatabaseManager


@pytest.fixture()
def cli_db(monkeypatch, tmp_path) -> DatabaseManager:
    """让 main.py 使用隔离的临时数据库。"""
    target = tmp_path / "cli.db"
    monkeypatch.setattr(
        main_module,
        "DatabaseManager",
        lambda: DatabaseManager(db_path=target),
    )
    # 预初始化。
    db = DatabaseManager(db_path=target)
    db.init_database()
    return db


def _enable_pilot_direct(db: DatabaseManager) -> int:
    """在 DB 层配置合规证据并启用 D5 试点绑定。"""
    report = {
        "fields": ["currentApprover", "approvalComment", "incident", "reportType"],
        "statusOrApprovalFields": [],
        "suggestedStatusMapping": [],
        "suggestedAutomaticFields": [],
        "requiresConfirmation": True,
    }
    db.record_mapping_observation(
        deliverable_id="VPI-T2-D5",
        source_type="tdc",
        result_state="matched",
        external_key="FM-1",
        candidate_fingerprint="fp1",
        candidate_count=1,
        candidate_summary_json=json.dumps([{"externalKey": "FM-1", "fields": {}}]),
        field_report_json=json.dumps(report),
    )
    db.record_mapping_observation(
        deliverable_id="VPI-T2-D5",
        source_type="tdc",
        result_state="matched",
        external_key="FM-1",
        candidate_fingerprint="fp2",
        candidate_count=1,
        candidate_summary_json=json.dumps([{"externalKey": "FM-1", "fields": {}}]),
        field_report_json=json.dumps(report),
    )
    with db.get_connection() as conn:
        conn.execute(
            """
            UPDATE project_status_update_bindings
            SET mode='hybrid', source_type='tdc', enabled=1,
                external_key='FM-1',
                credential_ref='test-credential-ref',
                match_rule_json='{"reportType":"data_model","incident":"FM-1"}',
                mapping_json='{"owner":"currentApprover","note":"approvalComment"}'
            WHERE deliverable_id='VPI-T2-D5'
            """
        )
        conn.execute(
            """
            INSERT INTO project_status_field_authority
                (deliverable_id, field_name, authority, source_type)
            VALUES ('VPI-T2-D5', 'owner', 'automatic', 'tdc')
            ON CONFLICT(deliverable_id, field_name) DO UPDATE SET
                authority='automatic', source_type='tdc', locked_at=NULL
            """
        )
        conn.execute(
            """
            INSERT INTO project_status_field_authority
                (deliverable_id, field_name, authority, source_type)
            VALUES ('VPI-T2-D5', 'remark', 'automatic', 'tdc')
            ON CONFLICT(deliverable_id, field_name) DO UPDATE SET
                authority='automatic', source_type='tdc', locked_at=NULL
            """
        )
        conn.commit()
        return int(
            conn.execute(
                "SELECT id FROM project_status_update_bindings WHERE deliverable_id='VPI-T2-D5'"
            ).fetchone()["id"]
        )


# ── 16. 无参数仍进入交互流程 ───────────────────────────────────


def test_no_args_enters_interactive_menu(monkeypatch, cli_db) -> None:
    """无参数时 main 应进入交互菜单，不返回 sync 退出码。"""
    called = {"interactive": False}

    def fake_show_banner():
        called["interactive"] = True

    def fake_show_menu():
        # 模拟用户立即退出。
        raise EOFError

    monkeypatch.setattr(main_module, "show_banner", fake_show_banner)
    monkeypatch.setattr(main_module, "show_menu", fake_show_menu)
    # Prompt.ask 不应被调用（EOF 在菜单后触发）。
    monkeypatch.setattr(
        main_module,
        "Prompt",
        type("FakePrompt", (), {"ask": staticmethod(lambda *a, **k: "0")}),
    )

    with pytest.raises(SystemExit) as exc_info:
        main_module.main([])
    # 交互模式 EOF → sys.exit(0)。
    assert exc_info.value.code == 0
    assert called["interactive"] is True


# ── 17. --once 不显示 banner、不读取 stdin、不启动 Flask ───────


def test_once_does_not_show_banner(monkeypatch, cli_db) -> None:
    _enable_pilot_direct(cli_db)
    banner_called = {"value": False}
    monkeypatch.setattr(
        main_module, "show_banner", lambda: banner_called.__setitem__("value", True)
    )
    from services.project_status_sync_runner import ConnectorRegistry
    monkeypatch.setattr(
        main_module, "create_production_registry", lambda: ConnectorRegistry()
    )

    code = main_module.main(["project-status-sync", "--once"])
    # 注入空 registry → connector_unavailable → needs_attention → exit 2。
    assert code == 2
    assert banner_called["value"] is False


# ── 18. CLI 输出不含 credential_ref/lease_token/cursor/match_rule/mapping ─


def test_cli_output_no_sensitive_data(monkeypatch, cli_db, capsys) -> None:
    binding_id = _enable_pilot_direct(cli_db)
    # 写入 fake credential_ref 验证 CLI 输出不泄漏。
    with cli_db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET credential_ref='test-credential-ref' "
            "WHERE id=?",
            (binding_id,),
        )
        conn.commit()

    from services.project_status_sync_runner import ConnectorRegistry
    monkeypatch.setattr(
        main_module, "create_production_registry", lambda: ConnectorRegistry()
    )

    code = main_module.main(["project-status-sync", "--once"])
    assert code == 2
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "test-credential-ref" not in output
    assert "lease_token" not in output
    assert "cursor_json" not in output
    assert "match_rule" not in output
    assert "mapping_json" not in output


# ── 退出码测试 ─────────────────────────────────────────────────


def test_no_eligible_bindings_exit_0(monkeypatch, cli_db, capsys) -> None:
    code = main_module.main(["project-status-sync", "--once"])
    assert code == 0
    output = capsys.readouterr().out
    assert "无符合条件的 enabled binding" in output


def test_dry_run_unavailable_connector_exit_2(monkeypatch, cli_db, capsys) -> None:
    _enable_pilot_direct(cli_db)
    from services.project_status_sync_runner import ConnectorRegistry
    monkeypatch.setattr(
        main_module, "create_production_registry", lambda: ConnectorRegistry()
    )
    code = main_module.main(["project-status-sync", "--once", "--dry-run"])
    assert code == 2
    output = capsys.readouterr().out
    assert "dry-run" in output
    assert "no connector" in output


def test_dry_run_available_connector_exit_0(
    monkeypatch, cli_db, capsys
) -> None:
    _enable_pilot_direct(cli_db)
    # 注入一个 fake connector 到 registry。
    from services.project_status_sync_runner import ConnectorRegistry
    from services.project_status_updates import ConnectorSnapshot

    fake_reg = ConnectorRegistry()

    class FakeConn:
        def collect(self, context):
            return ConnectorSnapshot(
                match_state="matched", candidates=[],
                external_version="v", fetched_at="t",
                expected_deliverable_updated_at="x",
            )

    fake_reg.register("tdc", FakeConn())
    monkeypatch.setattr(
        main_module, "create_production_registry", lambda: fake_reg
    )
    code = main_module.main(["project-status-sync", "--once", "--dry-run"])
    assert code == 0


def test_needs_attention_exit_2(monkeypatch, cli_db) -> None:
    _enable_pilot_direct(cli_db)
    from services.project_status_sync_runner import ConnectorRegistry
    monkeypatch.setattr(
        main_module, "create_production_registry", lambda: ConnectorRegistry()
    )
    code = main_module.main(["project-status-sync", "--once"])
    assert code == 2


# ── 参数错误 ───────────────────────────────────────────────────


def test_missing_once_flag_exits_interactive(monkeypatch, cli_db) -> None:
    """只传 project-status-sync 不传 --once → argparse 报错（exit 2）。"""
    with pytest.raises(SystemExit) as exc_info:
        main_module.main(["project-status-sync"])
    assert exc_info.value.code == 2


def test_unknown_deliverable_id_exit_0(monkeypatch, cli_db, capsys) -> None:
    _enable_pilot_direct(cli_db)
    code = main_module.main([
        "project-status-sync", "--once", "--deliverable-id", "NONEXISTENT"
    ])
    assert code == 0


# ── 19. KeyboardInterrupt 返回 130 ──────────────────────────────


def test_cli_keyboard_interrupt_exit_130(monkeypatch, cli_db) -> None:
    _enable_pilot_direct(cli_db)

    def fake_run_once(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        main_module.ProjectStatusSyncRunner, "run_once", fake_run_once
    )
    code = main_module.main(["project-status-sync", "--once"])
    assert code == 130


def test_cli_db_init_failure_exit_1(monkeypatch, tmp_path) -> None:
    """DB 初始化失败 → 脱敏错误 + exit 1，不输出 traceback。"""
    bad_path = tmp_path / "nonexistent_dir" / "bad.db"
    monkeypatch.setattr(
        main_module,
        "DatabaseManager",
        lambda: DatabaseManager(db_path=bad_path),
    )
    # 让目录创建后但 init_database 抛错。

    def boom(self):
        raise RuntimeError("corrupt db password=secret")

    monkeypatch.setattr(DatabaseManager, "init_database", boom)
    code = main_module.main(["project-status-sync", "--once"])
    assert code == 1
