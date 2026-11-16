"""回滚静默化工具（tools/ewo_export_quiesce.py）的离线契约。"""
import importlib.util
import json
import sqlite3
from pathlib import Path

from core.ewo_export_jobs import EWOExportJobs

TOOL = Path(__file__).resolve().parents[1] / "tools" / "ewo_export_quiesce.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("ewo_export_quiesce", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _jobs_with_state(tmp_path, state):
    path = tmp_path / "jobs.db"
    jobs = EWOExportJobs(path)
    job = jobs.create("scope-a", ["A" * 32], now=1)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE ewo_export_jobs SET state=? WHERE id=?", (state, job["id"]))
    return path, jobs, job


def test_preview_reports_active_jobs_without_touching_state(tmp_path, capsys):
    path, jobs, job = _jobs_with_state(tmp_path, "generating")
    tool = _load_tool()
    assert tool.main(["--db", str(path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output == {"mode": "preview", "active": {"generating": 1}}
    assert jobs.get(job["id"], "scope-a")["state"] == "generating"


def test_apply_freezes_in_flight_jobs(tmp_path, capsys):
    path, jobs, job = _jobs_with_state(tmp_path, "generating")
    tool = _load_tool()
    assert tool.main(["--db", str(path), "--apply"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "applied"
    assert output["to_generation_unknown"] == 1
    assert jobs.get(job["id"], "scope-a")["state"] == "generation_unknown"


def test_apply_abandons_legacy_retryable_jobs(tmp_path, capsys):
    path, jobs, job = _jobs_with_state(tmp_path, "failed")
    tool = _load_tool()
    assert tool.main(["--db", str(path), "--apply"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "applied"
    assert output["legacy_retryable_to_abandoned"] == 1
    assert jobs.get(job["id"], "scope-a")["state"] == "abandoned"


def test_missing_database_is_rejected(tmp_path, capsys):
    tool = _load_tool()
    assert tool.main(["--db", str(tmp_path / "absent.db")]) == 2
    assert "database not found" in capsys.readouterr().err
