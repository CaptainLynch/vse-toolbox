"""DSH-V2-27：Excel 提交自动启动与空闲退出（主控冻结进程契约 1-8）。

全部用例走真实调用链：Flask test client → POST /api/excel-tasks →
ExcelTaskAdminService → ExcelWorkerProcessController.ensure_running → 假 Popen。
不启动真实 Excel，也不启动真实 Worker 子进程；每个用例结束调用 close()。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

import pytest

import web.app as web_app
from core.db_manager import DatabaseManager
from core.excel_tasks import ApprovedExcelRoots, ExcelTaskRepository
from services.excel_worker_controller import ExcelWorkerController
from services.excel_worker_process_controller import (
    SAFE_AUTO_RESTART_LIMIT_ERROR,
    SAFE_AUTO_START_ERROR,
    ExcelWorkerProcessController,
    ExcelWorkerProcessStatus,
)

HEADERS = {
    "Host": "localhost:5000",
    "Origin": "http://localhost:5000",
    "Sec-Fetch-Site": "same-origin",
}
LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}


class FakeProcess:
    """最小 Popen 替身：只实现控制器用到的 poll/wait/terminate/kill。"""

    _next_pid = 7000

    def __init__(self, command: list[str], **kwargs: Any) -> None:
        self.command = list(command)
        self.kwargs = kwargs
        self.pid = FakeProcess._next_pid
        FakeProcess._next_pid += 1
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False
        self.stop_file = Path(self.command[self.command.index("--stop-file") + 1])
        self.stop_file_seen = False

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.stop_file_seen = self.stop_file.exists()
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 1

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _payload(key: str, output: str = "result.xlsx") -> dict[str, Any]:
    return {
        "operation": "merge_append",
        "files": [
            {"role": "source", "rootId": "default", "relativePath": "source.xlsx", "ordinal": 0},
            {"role": "output", "rootId": "default", "relativePath": output, "ordinal": 0},
        ],
        "idempotencyKey": key,
        "maxAttempts": 1,
    }


class Env:
    def __init__(
        self,
        app: Any,
        controller: Any,
        repository: ExcelTaskRepository,
        created: list[FakeProcess],
        root: Path,
        base_dir: Path,
    ) -> None:
        self.app = app
        self.controller = controller
        self.repository = repository
        self.created = created
        self.root = root
        self.base_dir = base_dir
        self._client: Any = None

    def client(self) -> Any:
        """单例客户端：启动票据一次性，会话 Cookie 需在同一客户端上累积。"""
        if self._client is None:
            self._client = self.app.test_client()
        return self._client

    def authed_client(self) -> Any:
        """并发用例专用：预置本机会话 Cookie（票据一次性，不能并发交换）。"""
        client = self.app.test_client()
        security = self.app.extensions["local_web_security"]
        client.set_cookie("vse_session", security.sessions.issue(), domain="localhost")
        return client

    def post_task(self, key: str, output: str = "result.xlsx", client: Any = None) -> Any:
        http = client if client is not None else self.client()
        return http.post(
            "/api/excel-tasks",
            json=_payload(key, output),
            headers=HEADERS,
            environ_base=LOOPBACK,
        )

    def created_task_id(self, response: Any) -> int:
        return int(response.get_json()["data"]["id"])


def _make_env(
    base_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    popen: Callable[..., FakeProcess] | None = None,
    controller_factory: Callable[[ExcelTaskRepository], Any] | None = None,
    **controller_kwargs: Any,
) -> Env:
    base_dir.mkdir(parents=True, exist_ok=True)
    root = base_dir / "excel"
    root.mkdir(exist_ok=True)
    (root / "source.xlsx").write_bytes(b"PK\x03\x04 placeholder")
    db = DatabaseManager(base_dir / "autolifecycle.db")
    db.init_database()
    repository = ExcelTaskRepository(db, ApprovedExcelRoots({"default": root}))
    created: list[FakeProcess] = []

    if popen is None:

        def popen(command, **kwargs):  # type: ignore[no-redef]
            process = FakeProcess(command, **kwargs)
            created.append(process)
            return process

    monkeypatch.setattr("services.excel_worker_process_controller.subprocess.Popen", popen)
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db)
    if controller_factory is not None:
        controller = controller_factory(repository)
    else:
        controller = ExcelWorkerProcessController(
            repository,
            monitor_interval=0.01,
            **controller_kwargs,
        )
    app = web_app.create_app(excel_repository=repository, excel_worker_controller=controller)
    app.config.update(TESTING=True)
    return Env(app, controller, repository, created, root, base_dir)


@pytest.fixture()
def make_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    controllers: list[Any] = []
    counter = {"n": 0}

    def factory(**kwargs: Any) -> Env:
        counter["n"] += 1
        env = _make_env(tmp_path / f"case{counter['n']}", monkeypatch, **kwargs)
        controllers.append(env.controller)
        return env

    try:
        yield factory
    finally:
        for controller in controllers:
            close = getattr(controller, "close", None)
            if callable(close):
                close()


@pytest.fixture()
def env(make_env):
    return make_env()


# ── 契约 1/2：提交自动启动（真实路由链）────────────────────────────────


def test_submit_starts_single_worker_and_reports_autostart(env: Env) -> None:
    response = env.post_task("auto-start-1", "result.xlsx")

    assert response.status_code == 200
    body = response.get_json()
    data = body["data"]
    assert data["status"] == "queued"
    assert data["workerAutoStart"] == {"state": "started"}
    assert len(env.created) == 1
    command = env.created[0].command
    assert command[1].endswith("excel_worker_cli.py")
    assert command[2] == "run"
    assert "--db" in command and "--stop-file" in command and "--root" in command
    assert env.controller.status().state == "running"

    # 幂等重放同样接线，但不会新建第二个进程。
    replay = env.post_task("auto-start-1", "result.xlsx")
    assert replay.status_code == 200
    replay_data = replay.get_json()["data"]
    assert replay_data["id"] == data["id"]
    assert replay_data["workerAutoStart"] == {"state": "already_running"}
    assert len(env.created) == 1

    # 创建失败（422）不得触发自动启动。
    invalid = env.client().post(
        "/api/excel-tasks",
        json={"operation": "", "files": []},
        headers=HEADERS,
        environ_base=LOOPBACK,
    )
    assert invalid.status_code == 422
    assert len(env.created) == 1


def test_ten_concurrent_ensure_running_spawns_one_process(env: Env) -> None:
    barrier = threading.Barrier(10)
    results: list[dict[str, Any]] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            barrier.wait(timeout=5)
            results.append(env.controller.ensure_running())
        except BaseException as exc:  # pragma: no cover - 失败时用于定位
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert len(results) == 10
    assert [item["state"] for item in results].count("started") == 1
    assert [item["state"] for item in results].count("already_running") == 9
    assert len(env.created) == 1


def test_ten_concurrent_submissions_spawn_one_process(env: Env) -> None:
    barrier = threading.Barrier(10)
    responses: list[Any] = []
    errors: list[BaseException] = []

    def submit(index: int) -> None:
        try:
            barrier.wait(timeout=5)
            http = env.authed_client()
            responses.append(env.post_task(f"concurrent-{index}", f"out-{index}.xlsx", client=http))
        except BaseException as exc:  # pragma: no cover - 失败时用于定位
            errors.append(exc)

    threads = [threading.Thread(target=submit, args=(index,)) for index in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert not errors
    assert len(responses) == 10
    assert {response.status_code for response in responses} == {200}
    states = [response.get_json()["data"]["workerAutoStart"]["state"] for response in responses]
    assert states.count("started") == 1
    assert states.count("already_running") == 9
    assert len(env.created) == 1
    assert len(env.repository.list_tasks(limit=200)) == 10


# ── 契约 3：空闲退出 ───────────────────────────────────────────────────


def test_idle_timeout_stops_worker_with_stop_file(make_env) -> None:
    clock = FakeClock()
    env = make_env(clock=clock, idle_timeout=300.0)
    created = env.post_task("idle-1")
    assert created.status_code == 200
    process = env.created[0]

    # 队列清空（取消）后，空闲计时才开始累积。
    assert env.repository.cancel_task(env.created_task_id(created)) is True
    assert _wait_until(lambda: env.controller._idle_since is not None)

    clock.advance(301.0)
    assert _wait_until(lambda: process.stop_file_seen)
    assert _wait_until(lambda: env.controller.status().state == "stopped")
    assert process.returncode == 0
    assert not process.terminated and not process.killed

    # 空闲退出后不再自动重启。
    time.sleep(0.2)
    assert len(env.created) == 1


def test_submit_racing_idle_stop_restarts_worker(make_env) -> None:
    """主控补充：空闲判定后、stop() 前恰有新提交（得到 already_running），停止后须重新拉起。"""
    clock = FakeClock()
    env = make_env(clock=clock, idle_timeout=300.0)
    created = env.post_task("race-1")
    assert created.status_code == 200
    assert env.repository.cancel_task(env.created_task_id(created)) is True
    assert _wait_until(lambda: env.controller._idle_since is not None)

    original_stop = env.controller.stop
    raced: dict = {}

    def stop_with_race(*args, **kwargs):
        if not raced:
            raced["response"] = env.post_task("race-2")
        return original_stop(*args, **kwargs)

    env.controller.stop = stop_with_race
    clock.advance(301.0)
    assert _wait_until(lambda: len(env.created) == 2)
    assert raced["response"].get_json()["data"]["workerAutoStart"]["state"] == "already_running"
    assert _wait_until(lambda: env.controller.status().state == "running")


# ── 契约 4：崩溃恢复与重启上限 ─────────────────────────────────────────


def test_crash_restarts_are_bounded_and_end_in_failed(env: Env) -> None:
    created = env.post_task("crash-1")
    assert created.status_code == 200
    # queued 任务仍在（假 Worker 不消费），所以每次崩溃都满足自动重启条件。
    assert len(env.created) == 1

    for _ in range(3):
        before = len(env.created)
        env.created[-1].returncode = 1
        assert _wait_until(lambda: len(env.created) == before + 1)
        assert _wait_until(lambda: env.controller.status().state == "running")

    assert len(env.created) == 4

    env.created[-1].returncode = 1
    assert _wait_until(lambda: env.controller.status().state == "failed")
    status = env.controller.status()
    assert status.error == SAFE_AUTO_RESTART_LIMIT_ERROR
    assert status.to_dict()["state"] == "failed"

    # 预算耗尽后停止自动重启；手动启动路径仍在。
    time.sleep(0.2)
    assert len(env.created) == 4
    manual = env.client().post(
        "/api/excel-worker/start",
        headers=HEADERS,
        environ_base=LOOPBACK,
    )
    assert manual.status_code == 200
    assert manual.get_json()["data"]["state"] == "running"
    assert len(env.created) == 5


# ── 契约 5：手动停止优先 ───────────────────────────────────────────────


def test_manual_stop_disarms_auto_restart_until_next_submit(env: Env) -> None:
    first = env.post_task("manual-1", "result-1.xlsx")
    assert first.status_code == 200
    assert len(env.created) == 1

    stopped = env.client().post(
        "/api/excel-worker/stop",
        headers=HEADERS,
        environ_base=LOOPBACK,
    )
    assert stopped.status_code == 200
    assert stopped.get_json()["data"]["state"] == "stopped"
    assert env.controller.status().state == "stopped"

    # 仍有 queued 任务，但手动停止后不得自动重启（模拟非请求退出也不生效）。
    env.created[0].returncode = 1
    time.sleep(0.2)
    assert len(env.created) == 1
    assert env.controller.status().state == "stopped"

    # 下一次提交重新武装。
    second = env.post_task("manual-2", "result-2.xlsx")
    assert second.status_code == 200
    assert second.get_json()["data"]["workerAutoStart"] == {"state": "started"}
    assert len(env.created) == 2


def test_submit_while_stopping_defers_start_to_monitor(env: Env) -> None:
    assert env.post_task("defer-1").status_code == 200
    controller = env.controller
    process = env.created[0]

    # 旧进程优雅停止进行中：ensure_running 不在锁内等待，只记待启动标记。
    with controller._lock:
        controller._status = ExcelWorkerProcessStatus("stopping", process.pid)
    assert controller.ensure_running() == {"state": "deferred"}
    assert len(env.created) == 1

    process.returncode = 0
    assert _wait_until(lambda: len(env.created) == 2)
    assert controller.status().state == "running"


# ── 契约 2：自动启动失败不影响任务创建 ─────────────────────────────────


def test_popen_failure_keeps_task_queued_and_returns_200(make_env, tmp_path: Path) -> None:
    def failing_popen(command, **kwargs):
        raise OSError(f"cannot spawn worker: {tmp_path / 'bin' / 'python.exe'}")

    env = make_env(popen=failing_popen)
    response = env.post_task("popen-failure-1")

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["status"] == "queued"
    assert data["workerAutoStart"] == {"state": "failed", "error": SAFE_AUTO_START_ERROR}
    assert env.created == []

    body_text = response.get_data(as_text=True)
    assert str(tmp_path) not in body_text
    assert "cannot spawn worker" not in body_text
    assert "python.exe" not in body_text

    status = env.client().get("/api/excel-worker/status").get_json()["data"]
    assert status == {"state": "failed", "error": SAFE_AUTO_START_ERROR}


def test_in_process_controller_reports_unavailable(make_env) -> None:
    env = make_env(controller_factory=lambda repository: ExcelWorkerController(lambda: None))
    response = env.post_task("in-process-1")

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["status"] == "queued"
    assert data["workerAutoStart"] == {"state": "unavailable"}
    assert env.created == []


# ── 契约 7：close() 与监视线程健壮性 ───────────────────────────────────


def test_close_stops_monitor_thread(env: Env) -> None:
    assert env.post_task("close-1").status_code == 200
    thread = env.controller._monitor_thread
    assert thread is not None and thread.is_alive()

    env.controller.close()

    assert not thread.is_alive()
    assert env.controller._monitor_thread is None
    assert env.controller.status().state == "running"


def test_monitor_tick_exception_does_not_kill_thread(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    assert env.post_task("monitor-error-1").status_code == 200
    thread = env.controller._monitor_thread
    assert thread is not None and thread.is_alive()

    def boom() -> None:
        raise RuntimeError("monitor tick exploded")

    monkeypatch.setattr(env.controller, "_monitor_tick", boom)
    time.sleep(0.2)

    assert thread.is_alive()
    # 宿主请求线程不受影响。
    assert env.client().get("/api/excel-worker/status").status_code == 200
