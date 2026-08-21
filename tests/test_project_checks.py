import importlib.util
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "agents" / "project_checks.py"
SPEC = importlib.util.spec_from_file_location("project_checks_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
project_checks = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(project_checks)


def test_run_checks_forces_utf8_python_environment(monkeypatch, tmp_path):
    captured = {}

    def fake_run(command, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(project_checks.subprocess, "run", fake_run)

    results = project_checks.run_checks(tmp_path, [["python", "-m", "pytest"]])

    assert results[0]["exit_code"] == 0
    assert captured["env"]["PYTHONUTF8"] == "1"
    assert captured["env"]["PYTHONIOENCODING"] == "utf-8"
    assert captured["encoding"] == "utf-8"
