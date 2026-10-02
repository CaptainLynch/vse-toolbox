"""In-process lifecycle controller for the local Excel task worker."""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from typing import Any, Callable

from core.excel_worker import ExcelTaskWorker, ExcelWorkerRunSummary


@dataclass(frozen=True)
class ExcelWorkerStatus:
    state: str
    started_at: str | None = None
    stopped_at: str | None = None
    summary: ExcelWorkerRunSummary | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"state": self.state}
        if self.started_at is not None:
            data["startedAt"] = self.started_at
        if self.stopped_at is not None:
            data["stoppedAt"] = self.stopped_at
        if self.summary is not None:
            data["summary"] = asdict(self.summary)
        if self.error is not None:
            data["error"] = self.error
        return data


class ExcelWorkerController:
    """Own exactly one background worker thread and its stop event."""

    def __init__(self, worker_factory: Callable[[], ExcelTaskWorker]) -> None:
        self._worker_factory = worker_factory
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop_event: threading.Event | None = None
        self._status = ExcelWorkerStatus(state="stopped")

    def status(self) -> ExcelWorkerStatus:
        with self._lock:
            thread = self._thread
            if thread is not None and not thread.is_alive() and self._status.state == "running":
                self._status = ExcelWorkerStatus(
                    state="stopped",
                    stopped_at=self._status.stopped_at,
                    summary=self._status.summary,
                    error=self._status.error,
                )
            return self._status

    def start(self) -> ExcelWorkerStatus:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("Excel worker is already running")
            stop_event = threading.Event()
            self._stop_event = stop_event
            self._status = ExcelWorkerStatus(state="running")
            thread = threading.Thread(
                target=self._run,
                args=(stop_event,),
                name="excel-task-worker",
                daemon=True,
            )
            self._thread = thread
            thread.start()
            return self._status

    def stop(self, timeout: float = 5.0) -> ExcelWorkerStatus:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                return self.status()
            self._status = ExcelWorkerStatus(state="stopping", summary=self._status.summary)
            stop_event = self._stop_event
            thread = self._thread
        if stop_event is not None:
            stop_event.set()
        thread.join(timeout=max(0.0, float(timeout)))
        with self._lock:
            if thread.is_alive():
                return self._status
            return self._status

    def _run(self, stop_event: threading.Event) -> None:
        try:
            summary = self._worker_factory().run(stop_event=stop_event)
            with self._lock:
                self._status = ExcelWorkerStatus(state="stopped", summary=summary)
        except BaseException as exc:
            with self._lock:
                self._status = ExcelWorkerStatus(
                    state="error",
                    error=type(exc).__name__,
                    summary=self._status.summary,
                )
