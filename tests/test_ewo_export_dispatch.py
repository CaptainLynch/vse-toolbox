"""EWO 导出后台派发：会话匹配、线程启动与失败兜底（不触网）。"""
from pathlib import Path
from types import SimpleNamespace

from web import ewo_export_dispatch as dispatch


class FakeSessions:
    def __init__(self, binding=None):
        self.binding = binding
        self.asked = []

    def bound_session(self, system, base_url):
        self.asked.append((system, base_url))
        return self.binding


def _db(tmp_path):
    return SimpleNamespace(db_path=tmp_path / "jobs.db")


def test_resume_runner_requires_a_bound_session(tmp_path):
    runner = dispatch.build_export_resume_runner(FakeSessions(None), _db(tmp_path), tmp_path)
    assert runner("job-1", "scope-a") is False


def test_resume_runner_rejects_a_different_scope(tmp_path):
    sessions = FakeSessions((object(), "scope-b"))
    runner = dispatch.build_export_resume_runner(sessions, _db(tmp_path), tmp_path)
    assert runner("job-1", "scope-a") is False


def test_resume_runner_spawns_export_for_the_same_scope(tmp_path, monkeypatch):
    sessions = FakeSessions((object(), "scope-a"))
    spawned = []
    monkeypatch.setattr(
        dispatch, "spawn_official_export",
        lambda job_id, scope, deps: spawned.append((job_id, scope, deps)) or None,
    )
    runner = dispatch.build_export_resume_runner(sessions, _db(tmp_path), tmp_path)
    assert runner("job-1", "scope-a") is True
    assert [(job, scope) for job, scope, _ in spawned] == [("job-1", "scope-a")]
    deps = spawned[0][2]
    assert Path(deps.downloads_dir) == tmp_path
    assert sessions.asked[0][0] == "aras"


def test_spawn_threads_swallow_errors_so_the_task_state_stays_authoritative(tmp_path, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("upstream exploded")

    deps = SimpleNamespace(jobs=object(), crawler=object(), transport=object(),
                           downloads_dir=tmp_path)
    monkeypatch.setattr(dispatch, "run_official_export", boom)
    thread = dispatch.spawn_official_export("job-2", "scope-a", deps)
    thread.join(5)
    assert not thread.is_alive()
