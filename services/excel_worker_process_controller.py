"""Controller for the production Excel worker subprocess."""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.excel_tasks import ExcelTaskRepository


@dataclass(frozen=True)
class ExcelWorkerProcessStatus:
    state: str
    pid: int | None = None
    exit_code: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"state": self.state}
        if self.pid is not None:
            data["pid"] = self.pid
        if self.exit_code is not None:
            data["exitCode"] = self.exit_code
        if self.error is not None:
            data["error"] = self.error
        return data


class ExcelWorkerProcessController:
    """Start and stop one worker subprocess without exposing COM to Flask."""

    def __init__(
        self,
        repository: ExcelTaskRepository,
        *,
        python_executable: str | None = None,
        project_root: Path | None = None,
    ) -> None:
        self._repository = repository
        self._python = python_executable or sys.executable
        self._project_root = (project_root or Path(__file__).resolve().parents[1]).resolve()
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._stop_file: Path | None = None
        self._status = ExcelWorkerProcessStatus("stopped")

    def status(self) -> ExcelWorkerProcessStatus:
        with self._lock:
            process = self._process
            if process is not None:
                exit_code = process.poll()
                if exit_code is None:
                    self._status = ExcelWorkerProcessStatus("running", process.pid)
                elif self._status.state in {"running", "stopping"}:
                    self._status = ExcelWorkerProcessStatus("stopped", process.pid, exit_code)
                    self._cleanup_stop_file()
            return self._status

    def start(self) -> ExcelWorkerProcessStatus:
        with self._lock:
            if self.status().state == "running":
                raise RuntimeError("Excel worker is already running")
            stop_file = Path(tempfile.gettempdir()) / f"vse-excel-worker-{os.getpid()}-{secrets.token_hex(8)}.stop"
            roots = self._repository.roots
            if getattr(sys, "frozen", False):
                worker_dir = Path(sys.executable).resolve().parent
                worker_exe = (worker_dir / "VSE-ExcelWorker.exe").resolve()
                if not worker_exe.is_file():
                    raise FileNotFoundError(
                        "Packaged Excel worker executable 'VSE-ExcelWorker.exe' was not found or is not a regular file"
                    )
                command = [
                    str(worker_exe),
                    "run",
                    "--db",
                    str(self._repository._db.db_path),
                    "--stop-file",
                    str(stop_file),
                ]
                cwd = str(worker_dir)
            else:
                command = [
                    self._python,
                    str(self._project_root / "tools" / "excel_worker_cli.py"),
                    "run",
                    "--db",
                    str(self._repository._db.db_path),
                    "--stop-file",
                    str(stop_file),
                ]
                cwd = str(self._project_root)
            for root_id in roots.root_ids:
                command.extend(["--root", f"{root_id}={roots.get_root(root_id)}"])
            process = subprocess.Popen(
                command,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            self._process = process
            self._stop_file = stop_file
            self._status = ExcelWorkerProcessStatus("running", process.pid)
            return self._status

    def stop(self, timeout: float = 10.0) -> ExcelWorkerProcessStatus:
        with self._lock:
            status = self.status()
            if status.state != "running" or self._process is None:
                return status
            process = self._process
            self._status = ExcelWorkerProcessStatus("stopping", process.pid)
            if self._stop_file is not None:
                self._stop_file.write_text("stop", encoding="ascii")
        try:
            process.wait(timeout=max(0.0, float(timeout)))
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        with self._lock:
            self._status = ExcelWorkerProcessStatus("stopped", process.pid, process.returncode)
            self._cleanup_stop_file()
            return self._status

    def _cleanup_stop_file(self) -> None:
        if self._stop_file is not None:
            try:
                self._stop_file.unlink(missing_ok=True)
            except OSError:
                pass
            self._stop_file = None
