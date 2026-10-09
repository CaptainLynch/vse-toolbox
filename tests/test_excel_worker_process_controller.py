from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from core.db_manager import DatabaseManager
from core.excel_tasks import ApprovedExcelRoots, ExcelTaskRepository
from services.excel_worker_process_controller import (
    ExcelWorkerProcessController,
    ExcelWorkerProcessStatus,
)


class FakeProcess:
    _next_pid = 4000

    def __init__(self, command, **kwargs):
        self.command = command
        self.kwargs = kwargs
        self.pid = FakeProcess._next_pid
        FakeProcess._next_pid += 1
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 1

    def kill(self):
        self.killed = True
        self.returncode = -9


@pytest.fixture()
def repo(tmp_path: Path) -> ExcelTaskRepository:
    root = tmp_path / "excel"
    root.mkdir()
    db = DatabaseManager(tmp_path / "worker.db")
    db.init_database()
    return ExcelTaskRepository(db, ApprovedExcelRoots({"default": root}))


def test_process_controller_builds_source_command(monkeypatch, repo: ExcelTaskRepository) -> None:
    created: list[FakeProcess] = []

    def fake_popen(command, **kwargs):
        process = FakeProcess(command, **kwargs)
        created.append(process)
        return process

    monkeypatch.setattr("services.excel_worker_process_controller.subprocess.Popen", fake_popen)
    controller = ExcelWorkerProcessController(
        repo,
        python_executable="C:/Python/python.exe",
        project_root=Path("C:/vse"),
    )
    status = controller.start()
    assert status.state == "running"
    assert len(created) == 1
    cmd = created[0].command
    assert cmd[0] == "C:/Python/python.exe"
    assert "tools\\excel_worker_cli.py" in "\\".join(cmd) or "tools/excel_worker_cli.py" in "/".join(cmd)
    assert "run" in cmd
    assert "--db" in cmd
    assert "--stop-file" in cmd
    assert "--root" in cmd
    assert os.path.normcase(os.path.normpath(created[0].kwargs["cwd"])) == os.path.normcase(
        os.path.normpath(str(Path("C:/vse")))
    )

    with pytest.raises(RuntimeError, match="already running"):
        controller.start()
    assert controller.stop().state == "stopped"


def test_process_controller_builds_frozen_command(monkeypatch, repo: ExcelTaskRepository, tmp_path: Path) -> None:
    """单 exe 部署：冻结态用宿主自身 + `--excel-worker` 哨兵自调起子进程。"""
    bin_dir = tmp_path / "dist" / "VSE-WebUI"
    bin_dir.mkdir(parents=True)
    webui_exe = bin_dir / "VSE-WebUI.exe"
    webui_exe.write_text("", encoding="ascii")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(webui_exe))

    created: list[FakeProcess] = []

    def fake_popen(command, **kwargs):
        process = FakeProcess(command, **kwargs)
        created.append(process)
        return process

    monkeypatch.setattr("services.excel_worker_process_controller.subprocess.Popen", fake_popen)
    controller = ExcelWorkerProcessController(repo)
    status = controller.start()
    assert status.state == "running"
    assert len(created) == 1
    cmd = created[0].command
    assert cmd[0] == str(webui_exe.resolve())
    assert cmd[1] == "--excel-worker"  # 哨兵：宿主自调起，不再有独立 Worker exe
    assert not any(arg.endswith(".py") for arg in cmd)
    assert "excel_worker_cli.py" not in " ".join(cmd)
    assert "run" in cmd
    assert "--db" in cmd
    assert "--stop-file" in cmd
    assert "--root" in cmd
    assert created[0].kwargs["cwd"] == str(bin_dir.resolve())
    assert controller.stop().state == "stopped"


def test_process_controller_frozen_missing_executable_fails_closed(
    monkeypatch,
    repo: ExcelTaskRepository,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "dist" / "VSE-WebUI" / "VSE-WebUI.exe"

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(missing))

    controller = ExcelWorkerProcessController(repo)
    with pytest.raises(FileNotFoundError) as exc_info:
        controller.start()

    err_msg = str(exc_info.value)
    assert str(tmp_path) not in err_msg
    assert str(missing.parent) not in err_msg


def test_process_controller_frozen_directory_executable_fails_closed(
    monkeypatch,
    repo: ExcelTaskRepository,
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "dist" / "VSE-WebUI"
    bin_dir.mkdir(parents=True)
    exe_dir = bin_dir / "VSE-WebUI.exe"
    exe_dir.mkdir()

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir))

    controller = ExcelWorkerProcessController(repo)
    with pytest.raises(FileNotFoundError) as exc_info:
        controller.start()

    err_msg = str(exc_info.value)
    assert str(tmp_path) not in err_msg


def test_process_controller_reports_exit(monkeypatch, repo: ExcelTaskRepository) -> None:
    process = FakeProcess([])
    monkeypatch.setattr("services.excel_worker_process_controller.subprocess.Popen", lambda *a, **k: process)
    controller = ExcelWorkerProcessController(repo)
    controller.start()
    process.returncode = 3
    status = controller.status()
    assert status.state == "stopped"
    assert status.exit_code == 3
    assert status.to_dict() == {"state": "stopped", "pid": process.pid, "exitCode": 3}


def test_process_status_to_dict() -> None:
    status_idle = ExcelWorkerProcessStatus("stopped")
    assert status_idle.to_dict() == {"state": "stopped"}

    status_error = ExcelWorkerProcessStatus("stopped", pid=1234, exit_code=1, error="fail")
    assert status_error.to_dict() == {"state": "stopped", "pid": 1234, "exitCode": 1, "error": "fail"}


def test_process_controller_start_rejected_while_stopping(monkeypatch, repo: ExcelTaskRepository) -> None:
    process = FakeProcess([])
    monkeypatch.setattr("services.excel_worker_process_controller.subprocess.Popen", lambda *a, **k: process)
    controller = ExcelWorkerProcessController(repo)
    controller.start()
    controller._status = ExcelWorkerProcessStatus("stopping", process.pid)
    with pytest.raises(RuntimeError, match="already running or stopping"):
        controller.start()


def test_process_controller_stop_handles_kill_timeout(monkeypatch, repo: ExcelTaskRepository) -> None:
    import subprocess

    class HangingProcess(FakeProcess):
        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(self.command, timeout or 0)

    process = HangingProcess([])
    monkeypatch.setattr("services.excel_worker_process_controller.subprocess.Popen", lambda *a, **k: process)
    controller = ExcelWorkerProcessController(repo)
    controller.start()
    status = controller.stop(timeout=0.01)
    assert status.state == "stopped"
    assert process.terminated is True
    assert process.killed is True


def test_process_controller_stop_preserves_replaced_process(monkeypatch, repo: ExcelTaskRepository, tmp_path: Path) -> None:
    process1 = FakeProcess([])
    process2 = FakeProcess([])
    processes = [process1, process2]

    monkeypatch.setattr("services.excel_worker_process_controller.subprocess.Popen", lambda *a, **k: processes.pop(0))
    controller = ExcelWorkerProcessController(repo)
    controller.start()
    old_stop_file = controller._stop_file
    assert old_stop_file is not None

    new_stop_file = tmp_path / "new_worker.stop"
    new_stop_file.write_text("new", encoding="ascii")

    # Simulate replacement of process during stop wait
    orig_wait = process1.wait

    def hook_wait(timeout=None):
        controller._process = process2
        controller._stop_file = new_stop_file
        controller._status = ExcelWorkerProcessStatus("running", process2.pid)
        return orig_wait(timeout)

    process1.wait = hook_wait
    status = controller.stop(timeout=1.0)
    # The running state and new stop file of process2 must be preserved!
    assert status.state == "running"
    assert controller._status.state == "running"
    assert controller._stop_file == new_stop_file
    assert new_stop_file.exists()
    assert not old_stop_file.exists()


def test_process_controller_status_preserves_stopping_while_process_alive(monkeypatch, repo: ExcelTaskRepository) -> None:
    """status() must report 'stopping' while process is shutting down and poll() is None."""
    process = FakeProcess([])
    monkeypatch.setattr("services.excel_worker_process_controller.subprocess.Popen", lambda *a, **k: process)
    controller = ExcelWorkerProcessController(repo)
    controller.start()
    controller._status = ExcelWorkerProcessStatus("stopping", process.pid)
    # Process is still running (poll returns None)
    assert process.poll() is None
    status = controller.status()
    assert status.state == "stopping"
    assert status.pid == process.pid
