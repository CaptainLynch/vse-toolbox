from __future__ import annotations

import json
import signal
import threading
from pathlib import Path
from typing import Any

import pytest

import tools.excel_worker_cli as cli
from core.excel_worker import (
    ExcelTaskRunResult,
    ExcelTaskRunStatus,
    ExcelWorkerRunSummary,
)


class FakeWorker:
    def __init__(
        self,
        run_once_result: ExcelTaskRunResult | None = None,
        run_summary: ExcelWorkerRunSummary | None = None,
    ) -> None:
        self._run_once_result = (
            run_once_result
            if run_once_result is not None
            else ExcelTaskRunResult(
                status=ExcelTaskRunStatus.SUCCEEDED,
                task_id=1,
                operation="merge_append",
                output_committed=True,
            )
        )
        self._run_summary = (
            run_summary
            if run_summary is not None
            else ExcelWorkerRunSummary(
                processed=1,
                succeeded=1,
                failed=0,
                lease_lost=0,
            )
        )

    def run_once(self) -> ExcelTaskRunResult:
        return self._run_once_result

    def run(self, *, stop_event: threading.Event | None = None) -> ExcelWorkerRunSummary:
        return self._run_summary


class FakeRepository:
    def __init__(self, queued: bool = True) -> None:
        self.queued = queued

    def list_tasks(self, status: str | None = None, limit: int = 1) -> list[dict[str, object]]:
        return [{"id": 1}] if self.queued and status == "queued" else []


def test_parse_root_spec_and_validation(tmp_path: Path) -> None:
    root_id, path = cli.parse_root_spec(f"business={tmp_path}")
    assert root_id == "business"
    assert path == tmp_path.absolute()
    with pytest.raises(cli.ExcelWorkerConfigError):
        cli.parse_root_spec("missing-separator")


def test_validate_numeric_args() -> None:
    cli.validate_numeric_args(900, None, 0.1)
    with pytest.raises(cli.ExcelWorkerConfigError):
        cli.validate_numeric_args(10, None, 0.1)
    with pytest.raises(cli.ExcelWorkerConfigError):
        cli.validate_numeric_args(900, 900, 0.1)


def test_parser_requires_subcommand() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])


def test_run_once_success_exit_0(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    fake_result = ExcelTaskRunResult(
        status=ExcelTaskRunStatus.SUCCEEDED,
        task_id=101,
        run_id=1,
        operation="merge_append",
        output_committed=True,
    )
    fake_worker = FakeWorker(run_once_result=fake_result)
    monkeypatch.setattr(cli, "_build_worker", lambda args: (fake_worker, FakeRepository(True)))

    exit_code = cli.main(["run-once", "--db", "db.sqlite", "--root", "r=C:/excel"])
    assert exit_code == cli.EXIT_OK

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["command"] == "run-once"
    assert payload["completed"] is True
    assert payload["succeeded"] is True
    assert payload["status"] == "succeeded"
    assert payload["task_id"] == 101
    assert payload["output_committed"] is True


def test_run_once_empty_queue_is_idle_exit_0(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_result = ExcelTaskRunResult(status=ExcelTaskRunStatus.IDLE)
    fake_worker = FakeWorker(run_once_result=fake_result)
    monkeypatch.setattr(cli, "_build_worker", lambda args: (fake_worker, FakeRepository(False)))

    exit_code = cli.main(["run-once", "--db", "db.sqlite", "--root", "r=C:/excel"])
    assert exit_code == cli.EXIT_OK

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["command"] == "run-once"
    assert payload["completed"] is False
    assert payload["succeeded"] is False
    assert payload["status"] == "idle"
    assert payload["task_id"] is None
    assert payload["output_committed"] is False


def test_run_once_failure_exit_1(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    fake_result = ExcelTaskRunResult(
        status=ExcelTaskRunStatus.FAILED,
        task_id=202,
        run_id=2,
        operation="merge_overlay",
        error_type="RuntimeError",
        error_message="corrupt sheet data",
        output_committed=False,
    )
    fake_worker = FakeWorker(run_once_result=fake_result)
    monkeypatch.setattr(cli, "_build_worker", lambda args: (fake_worker, FakeRepository(True)))

    exit_code = cli.main(["run-once", "--db", "db.sqlite", "--root", "r=C:/excel"])
    assert exit_code == cli.EXIT_TASK_FAILED

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["command"] == "run-once"
    assert payload["completed"] is True
    assert payload["succeeded"] is False
    assert payload["status"] == "failed"
    assert payload["task_id"] == 202
    assert payload["error_type"] == "RuntimeError"
    assert payload["error_message"] == "corrupt sheet data"
    assert payload["output_committed"] is False


def test_run_once_lease_lost_exit_1(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    fake_result = ExcelTaskRunResult(
        status=ExcelTaskRunStatus.LEASE_LOST,
        task_id=303,
        run_id=3,
        operation="diff_against_baseline",
        error_type="ExcelLeaseLostError",
        error_message="lease lost to another worker",
        output_committed=False,
    )
    fake_worker = FakeWorker(run_once_result=fake_result)
    monkeypatch.setattr(cli, "_build_worker", lambda args: (fake_worker, FakeRepository(True)))

    exit_code = cli.main(["run-once", "--db", "db.sqlite", "--root", "r=C:/excel"])
    assert exit_code == cli.EXIT_TASK_FAILED

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["command"] == "run-once"
    assert payload["completed"] is True
    assert payload["succeeded"] is False
    assert payload["status"] == "lease_lost"
    assert payload["task_id"] == 303
    assert payload["error_type"] == "ExcelLeaseLostError"
    assert payload["error_message"] == "lease lost to another worker"
    assert payload["output_committed"] is False


def test_run_once_redacts_sensitive_error_information(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_result = ExcelTaskRunResult(
        status=ExcelTaskRunStatus.FAILED,
        task_id=404,
        error_type="ApiKeyError",
        error_message="failed auth token: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.sensitive_payload_part.signature",
        output_committed=False,
    )
    fake_worker = FakeWorker(run_once_result=fake_result)
    monkeypatch.setattr(cli, "_build_worker", lambda args: (fake_worker, FakeRepository(True)))

    exit_code = cli.main(["run-once", "--db", "db.sqlite", "--root", "r=C:/excel"])
    assert exit_code == cli.EXIT_TASK_FAILED

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert "sensitive_payload_part" not in payload["error_message"]
    assert "[redacted]" in payload["error_message"].lower()


def test_run_once_plain_text_emission(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_result = ExcelTaskRunResult(
        status=ExcelTaskRunStatus.SUCCEEDED,
        task_id=505,
        output_committed=True,
    )
    fake_worker = FakeWorker(run_once_result=fake_result)
    monkeypatch.setattr(cli, "_build_worker", lambda args: (fake_worker, FakeRepository(True)))

    exit_code = cli.main(["run-once", "--db", "db.sqlite", "--root", "r=C:/excel", "--no-json"])
    assert exit_code == cli.EXIT_OK

    out_text = capsys.readouterr().out
    assert "command=run-once" in out_text
    assert "status=succeeded" in out_text
    assert "task_id=505" in out_text


def test_run_emits_structured_summary_counts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_summary = ExcelWorkerRunSummary(
        processed=5,
        succeeded=3,
        failed=1,
        lease_lost=1,
    )
    fake_worker = FakeWorker(run_summary=fake_summary)
    monkeypatch.setattr(cli, "_build_worker", lambda args: (fake_worker, FakeRepository()))

    exit_code = cli.main(["run", "--db", "db.sqlite", "--root", "r=C:/excel"])
    assert exit_code == cli.EXIT_OK

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["command"] == "run"
    assert payload["processed"] == 5
    assert payload["succeeded"] == 3
    assert payload["failed"] == 1
    assert payload["lease_lost"] == 1
    assert payload["stopped"] is False


def test_run_plain_text_emission(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_summary = ExcelWorkerRunSummary(
        processed=2,
        succeeded=2,
        failed=0,
        lease_lost=0,
    )
    fake_worker = FakeWorker(run_summary=fake_summary)
    monkeypatch.setattr(cli, "_build_worker", lambda args: (fake_worker, FakeRepository()))

    exit_code = cli.main(["run", "--db", "db.sqlite", "--root", "r=C:/excel", "--no-json"])
    assert exit_code == cli.EXIT_OK

    out_text = capsys.readouterr().out
    assert "command=run" in out_text
    assert "processed=2" in out_text
    assert "succeeded=2" in out_text


def test_keyboard_interrupt_is_clean(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    class InterruptWorker(FakeWorker):
        def run(self, *, stop_event: threading.Event | None = None) -> ExcelWorkerRunSummary:
            raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_build_worker", lambda args: (InterruptWorker(), FakeRepository()))
    assert cli.main(["run", "--db", "db.sqlite", "--root", "r=C:/excel"]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out)["stopped"] is True


def test_configuration_error_returns_two(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "_build_worker", lambda args: (_ for _ in ()).throw(ValueError("bad root")))
    assert cli.main(["run-once", "--db", "db.sqlite", "--root", "r=C:/excel"]) == cli.EXIT_CONFIG_ERROR
    assert "configuration error" in capsys.readouterr().err


def test_stop_signal_handlers_sets_event_and_restores_previous() -> None:
    stop_event = threading.Event()
    signal_names = ("SIGINT", "SIGTERM", "SIGBREAK")
    supported_signals: list[signal.Signals] = [
        getattr(signal, name)
        for name in signal_names
        if hasattr(signal, name)
    ]
    orig_handlers: dict[signal.Signals, Any] = {
        sig: signal.getsignal(sig) for sig in supported_signals
    }

    with cli._StopSignalHandlers(stop_event) as handler:
        assert not stop_event.is_set()
        for sig in supported_signals:
            assert signal.getsignal(sig) == handler._handle

        # Manually invoke signal handler without real OS signal dispatch
        handler._handle(signal.SIGINT, None)
        assert stop_event.is_set()

    # Handlers should be fully restored after exiting the context manager
    for sig in supported_signals:
        assert signal.getsignal(sig) == orig_handlers[sig]


def test_safe_error_message_hides_approved_root(tmp_path: Path) -> None:
    root = tmp_path / "business"
    root.mkdir()
    roots = cli.ApprovedExcelRoots({"business": root})
    repository = cli.ExcelTaskRepository(object(), roots)  # type: ignore[arg-type]
    message = f"output path aliases with source file: {root / 'secret.xlsx'}"
    safe = cli._safe_task_error_message(message, repository)
    assert str(root) not in safe
    assert "<approved-root:business>" in safe
