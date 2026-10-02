from __future__ import annotations

import threading
import time

import pytest

from core.excel_worker import ExcelWorkerRunSummary
from services.excel_worker_controller import ExcelWorkerController


class FakeWorker:
    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self.started = started
        self.release = release

    def run(self, *, stop_event: threading.Event) -> ExcelWorkerRunSummary:
        self.started.set()
        while not stop_event.is_set() and not self.release.is_set():
            time.sleep(0.005)
        return ExcelWorkerRunSummary(processed=2, succeeded=1, failed=1, lease_lost=0)


def test_controller_start_status_stop_and_summary() -> None:
    started = threading.Event()
    release = threading.Event()
    controller = ExcelWorkerController(lambda: FakeWorker(started, release))

    assert controller.status().state == "stopped"
    assert controller.start().state == "running"
    assert started.wait(1)
    with pytest.raises(RuntimeError):
        controller.start()

    status = controller.stop(timeout=1)
    assert status.state == "stopped"
    assert status.summary == ExcelWorkerRunSummary(2, 1, 1, 0)
    assert controller.stop().state == "stopped"


def test_controller_stop_timeout_reports_stopping() -> None:
    started = threading.Event()
    release = threading.Event()
    controller = ExcelWorkerController(lambda: FakeWorker(started, release))
    controller.start()
    assert started.wait(1)
    status = controller.stop(timeout=0)
    assert status.state in {"stopping", "stopped"}
    release.set()
    assert controller.stop(timeout=1).state == "stopped"


def test_controller_worker_error_isolated() -> None:
    class BrokenWorker:
        def run(self, *, stop_event: threading.Event) -> ExcelWorkerRunSummary:
            raise RuntimeError("boom")

    controller = ExcelWorkerController(BrokenWorker)
    controller.start()
    for _ in range(100):
        if controller.status().state == "error":
            break
        time.sleep(0.005)
    assert controller.status().state == "error"
    assert controller.status().error == "RuntimeError"
