# -*- coding: utf-8 -*-
"""Focused offline tests for the scheduled-archive CLI entry point and production runner factory."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import main as main_module
from core.credential_provider import WindowsCredentialManagerProvider
from core.db_manager import DatabaseManager
from services.scheduled_archive_connectors import (
    ArasArchiveConnector,
    TDCArchiveConnector,
)
from services.scheduled_archive_runner import (
    EXIT_ATTENTION,
    EXIT_FAILED,
    EXIT_INTERRUPTED,
    EXIT_OK,
    ArchiveJobRunResult,
    ArchiveRunOnceResult,
    ArchiveSyncRunner,
    create_production_archive_runner,
)


@pytest.fixture()
def cli_db(monkeypatch, tmp_path: Path) -> DatabaseManager:
    """Provide an isolated temporary SQLite database for main.py scheduled-archive tests."""
    target = tmp_path / "archive_cli.db"
    monkeypatch.setattr(
        main_module,
        "DatabaseManager",
        lambda: DatabaseManager(db_path=target),
    )
    db = DatabaseManager(db_path=target)
    db.init_database()
    return db


def _normalize_space(text: str) -> str:
    """Normalize multi-line / wrapped console text into single-spaced output."""
    return " ".join(text.split())


# ── 1. Argument Parser Contract ──────────────────────────────────────────────


def test_parse_archive_sync_args_requires_once() -> None:
    """Parser requires --once flag and fails when omitted."""
    with pytest.raises(SystemExit) as exc_info:
        main_module._parse_archive_sync_args([])
    assert exc_info.value.code == 2


def test_parse_archive_sync_args_defaults() -> None:
    """Parser sets expected default values when only --once is given."""
    args = main_module._parse_archive_sync_args(["--once"])
    assert args.once is True
    assert args.dry_run is False
    assert args.job_key is None


@pytest.mark.parametrize(
    ("argv", "expected_dry_run", "expected_job_key"),
    [
        (["--once", "--dry-run"], True, None),
        (["--once", "--job-key", "aras_ewo"], False, "aras_ewo"),
        (["--once", "--dry-run", "--job-key", "tdc_sor"], True, "tdc_sor"),
    ],
)
def test_parse_archive_sync_args_options(
    argv: list[str],
    expected_dry_run: bool,
    expected_job_key: str | None,
) -> None:
    """Parser accepts --dry-run and exact --job-key flags."""
    args = main_module._parse_archive_sync_args(argv)
    assert args.once is True
    assert args.dry_run is expected_dry_run
    assert args.job_key == expected_job_key


# ── 2. Routing, DB Initialization, and Exit Code Contract ────────────────────


def test_main_routes_scheduled_archive_before_interactive_menu(
    monkeypatch,
    cli_db: DatabaseManager,
) -> None:
    """main routes scheduled-archive before interactive menu and avoids banner/prompts."""
    banner_called = {"value": False}
    monkeypatch.setattr(
        main_module,
        "show_banner",
        lambda: banner_called.__setitem__("value", True),
    )

    fake_result = ArchiveRunOnceResult(
        results=(
            ArchiveJobRunResult(
                job_id=1,
                job_key="aras_ewo",
                outcome="completed",
                run_id=10,
                final_state="success",
            ),
        ),
        dry_run=False,
    )
    fake_runner = MagicMock(spec=ArchiveSyncRunner)
    fake_runner.run_once.return_value = fake_result

    monkeypatch.setattr(
        main_module,
        "create_production_archive_runner",
        lambda db: fake_runner,
    )

    exit_code = main_module.main(["scheduled-archive", "--once", "--job-key", "aras_ewo", "--dry-run"])

    assert exit_code == EXIT_OK
    assert banner_called["value"] is False
    fake_runner.run_once.assert_called_once_with(
        trigger_type="scheduled",
        job_key="aras_ewo",
        dry_run=True,
    )


def test_main_scheduled_archive_initializes_database(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """main constructs DatabaseManager and calls init_database before running."""
    db_file = tmp_path / "lazy_init.db"
    db_instance = DatabaseManager(db_path=db_file)
    init_called = {"value": False}

    orig_init = db_instance.init_database

    def wrapped_init():
        init_called["value"] = True
        return orig_init()

    monkeypatch.setattr(db_instance, "init_database", wrapped_init)
    monkeypatch.setattr(main_module, "DatabaseManager", lambda: db_instance)

    fake_result = ArchiveRunOnceResult(results=(), dry_run=False)
    fake_runner = MagicMock(spec=ArchiveSyncRunner)
    fake_runner.run_once.return_value = fake_result
    monkeypatch.setattr(
        main_module,
        "create_production_archive_runner",
        lambda db: fake_runner,
    )

    exit_code = main_module.main(["scheduled-archive", "--once"])
    assert exit_code == EXIT_OK
    assert init_called["value"] is True


# ── 3. Summary Output Formatting and Privacy Protection ──────────────────────


@pytest.mark.parametrize(
    ("run_result", "expected_prefix", "expected_substrings", "expected_exit"),
    [
        (
            ArchiveRunOnceResult(results=(), dry_run=False),
            None,
            ["无符合条件的 enabled archive job。"],
            EXIT_OK,
        ),
        (
            ArchiveRunOnceResult(
                results=(
                    ArchiveJobRunResult(
                        job_id=1,
                        job_key="aras_ewo",
                        outcome="ready",
                    ),
                    ArchiveJobRunResult(
                        job_id=2,
                        job_key="tdc_sor",
                        outcome="not_ready",
                        error_type="job_not_ready",
                        error_message="archive job configuration is not ready",
                    ),
                ),
                dry_run=True,
            ),
            "archive dry-run",
            [
                "archive dry-run",
                "job 1 | key=aras_ewo | outcome=ready",
                "job 2 | key=tdc_sor | outcome=not_ready | error_type=job_not_ready | message=archive job configuration is not ready",
            ],
            EXIT_ATTENTION,
        ),
        (
            ArchiveRunOnceResult(
                results=(
                    ArchiveJobRunResult(
                        job_id=3,
                        job_key="aras_paa",
                        outcome="completed",
                        run_id=100,
                        final_state="success",
                    ),
                ),
                dry_run=False,
            ),
            "archive",
            ["archive", "job 3 | key=aras_paa | outcome=completed | state=success"],
            EXIT_OK,
        ),
        (
            ArchiveRunOnceResult(
                results=(
                    ArchiveJobRunResult(
                        job_id=4,
                        job_key="tdc_data_model",
                        outcome="failed",
                        run_id=101,
                        final_state="failed",
                        error_type="connection_error",
                        error_message="external archive connection failed",
                    ),
                ),
                dry_run=False,
            ),
            "archive",
            [
                "archive",
                "job 4 | key=tdc_data_model | outcome=failed | state=failed | error_type=connection_error | message=external archive connection failed",
            ],
            EXIT_FAILED,
        ),
        (
            ArchiveRunOnceResult(
                results=(
                    ArchiveJobRunResult(
                        job_id=5,
                        job_key="aras_ncr_progress",
                        outcome="needs_attention",
                        run_id=102,
                        final_state="needs_attention",
                        error_type="credential_unavailable",
                        error_message="credential reference is unavailable",
                    ),
                ),
                dry_run=False,
            ),
            "archive",
            [
                "archive",
                "job 5 | key=aras_ncr_progress | outcome=needs_attention | state=needs_attention | error_type=credential_unavailable | message=credential reference is unavailable",
            ],
            EXIT_ATTENTION,
        ),
        (
            ArchiveRunOnceResult(
                results=(
                    ArchiveJobRunResult(
                        job_id=6,
                        job_key="tdc_vdr",
                        outcome="not_due",
                    ),
                ),
                dry_run=False,
            ),
            "archive",
            ["archive", "job 6 | key=tdc_vdr | outcome=not_due"],
            EXIT_OK,
        ),
    ],
)
def test_summary_output_scenarios_and_redaction(
    monkeypatch,
    cli_db: DatabaseManager,
    capsys: pytest.CaptureFixture[str],
    run_result: ArchiveRunOnceResult,
    expected_prefix: str | None,
    expected_substrings: list[str],
    expected_exit: int,
) -> None:
    """Summary output renders correct job lines and exit codes for all runner outcomes."""
    fake_runner = MagicMock(spec=ArchiveSyncRunner)
    fake_runner.run_once.return_value = run_result
    monkeypatch.setattr(
        main_module,
        "create_production_archive_runner",
        lambda db: fake_runner,
    )

    exit_code = main_module.main(["scheduled-archive", "--once"])
    assert exit_code == expected_exit

    out = _normalize_space(capsys.readouterr().out)
    for substring in expected_substrings:
        assert _normalize_space(substring) in out


def test_summary_output_never_exposes_sensitive_data(
    monkeypatch,
    cli_db: DatabaseManager,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Summary output never leaks alias/token/session/absolute paths."""
    sensitive_alias = "vault_cred_secret_123"
    sensitive_token = "bearer_session_token_xyz987"
    sensitive_path = r"C:\Sensitive\Production\Storage\Root"

    # Seed the database with jobs having sensitive credential_ref, filters_json, and output_subdir
    with cli_db.get_connection() as conn:
        conn.execute(
            """
            UPDATE scheduled_archive_jobs
            SET enabled = 1,
                credential_ref = ?,
                output_subdir = ?,
                filters_json = ?
            WHERE job_key = 'aras_ewo'
            """,
            (
                sensitive_alias,
                sensitive_path,
                f'{{"token": "{sensitive_token}"}}',
            ),
        )

    fake_result = ArchiveRunOnceResult(
        results=(
            ArchiveJobRunResult(
                job_id=1,
                job_key="aras_ewo",
                outcome="completed",
                run_id=5,
                final_state="success",
            ),
        ),
        dry_run=False,
    )
    fake_runner = MagicMock(spec=ArchiveSyncRunner)
    fake_runner.run_once.return_value = fake_result
    monkeypatch.setattr(
        main_module,
        "create_production_archive_runner",
        lambda db: fake_runner,
    )

    exit_code = main_module.main(["scheduled-archive", "--once"])
    assert exit_code == EXIT_OK

    captured = capsys.readouterr()
    combined_output = captured.out + captured.err
    for secret in [sensitive_alias, sensitive_token, sensitive_path]:
        assert secret not in combined_output


# ── 4. Exception and KeyboardInterrupt Handling ──────────────────────────────


def test_main_keyboard_interrupt_returns_130(
    monkeypatch,
    cli_db: DatabaseManager,
) -> None:
    """KeyboardInterrupt during scheduled-archive execution returns 130 cleanly."""
    def raise_interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(main_module, "_run_archive_sync_once", raise_interrupt)
    exit_code = main_module.main(["scheduled-archive", "--once"])
    assert exit_code == EXIT_INTERRUPTED


def test_main_unexpected_exception_returns_1_with_safe_message(
    monkeypatch,
    cli_db: DatabaseManager,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unexpected exception returns 1 and emits only safe message without exception sentinel."""
    sentinel_secret = "DB_AUTH_TOKEN_SECRET_99999"

    def raise_crash(*args, **kwargs):
        raise RuntimeError(f"Database connection exploded: token={sentinel_secret}")

    monkeypatch.setattr(main_module, "_run_archive_sync_once", raise_crash)
    exit_code = main_module.main(["scheduled-archive", "--once"])

    assert exit_code == EXIT_FAILED
    captured = capsys.readouterr()
    assert captured.out.strip() == "独立归档运行失败。"
    assert captured.err == ""
    assert sentinel_secret not in captured.out
    assert sentinel_secret not in captured.err


# ── 5. Production Factory Wiring Contract ────────────────────────────────────


def test_create_production_archive_runner_wiring(cli_db: DatabaseManager, tmp_path: Path) -> None:
    """Production factory wires WindowsCredentialManagerProvider and exact fixed registry."""
    fake_archive = MagicMock()
    fake_archive.root = tmp_path / "fake_archive_root"

    with (
        patch(
            "core.credential_provider.WindowsCredentialManagerProvider.resolve",
            side_effect=AssertionError("resolve must not be called during factory construction"),
        ) as mock_resolve,
        patch(
            "core.credential_provider.WindowsCredentialManagerProvider.is_available",
            side_effect=AssertionError("is_available must not be called during factory construction"),
        ) as mock_is_available,
        patch(
            "services.scheduled_archive_connectors.TDCArchiveConnector.collect",
            side_effect=AssertionError("TDC collect must not be called during factory construction"),
        ) as mock_tdc_collect,
        patch(
            "services.scheduled_archive_connectors.ArasArchiveConnector.collect",
            side_effect=AssertionError("Aras collect must not be called during factory construction"),
        ) as mock_aras_collect,
        patch("services.scheduled_archive_connectors.ArchiveStore", return_value=fake_archive) as mock_store_cls,
        patch("services.scheduled_archive_runner.ArchiveSyncRunner") as mock_runner_cls,
    ):
        runner = create_production_archive_runner(cli_db)
        assert runner is not None

        mock_store_cls.assert_called_once_with()
        mock_runner_cls.assert_called_once()

        mock_resolve.assert_not_called()
        mock_is_available.assert_not_called()
        mock_tdc_collect.assert_not_called()
        mock_aras_collect.assert_not_called()

        call_args = mock_runner_cls.call_args[0]
        assert call_args[0] is cli_db
        assert isinstance(call_args[1], WindowsCredentialManagerProvider)

        registry = call_args[2]
        expected_keys = (
            "aras_ncr_detail",
            "aras_ncr_progress",
            "aras_paa",
            "aras_ewo",
            "tdc_data_model",
            "tdc_sor",
        )
        assert registry.registered_job_keys == tuple(sorted(expected_keys))
        assert len(registry.registered_job_keys) == 6

        tdc_instance = registry.get("tdc_data_model")
        assert isinstance(tdc_instance, TDCArchiveConnector)
        assert registry.get("tdc_sor") is tdc_instance

        aras_instance = registry.get("aras_ewo")
        assert isinstance(aras_instance, ArasArchiveConnector)
        assert registry.get("aras_paa") is aras_instance
        assert registry.get("aras_ncr_progress") is aras_instance
        assert registry.get("aras_ncr_detail") is aras_instance
