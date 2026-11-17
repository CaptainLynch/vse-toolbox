# -*- coding: utf-8 -*-
"""单 exe 部署（方案 A）：webui.py 的 `--excel-worker` 哨兵分发。

关键不变量：哨兵分支**不加载 Flask/插件、不监听端口**，把剩余 argv 原样交给
Worker CLI；普通启动路径不受影响。真机 COM 行为不在本文件覆盖范围（需装 Excel）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBUI = REPO_ROOT / "webui.py"


def _run(*args: str, timeout: float = 90.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(WEBUI), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def test_excel_worker_sentinel_dispatches_to_worker_cli() -> None:
    """哨兵分支打印 Worker CLI 的帮助，且不出现宿主启动横幅。"""
    result = _run("--excel-worker", "--help")

    assert result.returncode == 0, result.stderr[-2000:]
    output = result.stdout + result.stderr
    assert "VSE Toolbox WebUI" not in output  # 宿主横幅不得出现
    assert "run-once" in output  # Worker CLI 子命令


def test_excel_worker_sentinel_never_binds_a_port() -> None:
    """哨兵分支下不得触发端口解析/监听：给一个非法子命令，只应得到 CLI 用法错误。"""
    result = _run("--excel-worker", "definitely-not-a-subcommand")

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "VSE Toolbox WebUI" not in output
    assert "监听" not in output


def test_normal_invocation_does_not_enter_worker_branch() -> None:
    """普通启动路径仍走宿主：--help 由宿主的 argparse 处理（含 --port/--no-browser）。"""
    result = _run("--help")

    assert result.returncode == 0, result.stderr[-2000:]
    output = result.stdout + result.stderr
    assert "--no-browser" in output
    assert "run-once" not in output  # 不得落到 Worker CLI


def test_sentinel_is_exact_match_on_first_argument() -> None:
    """哨兵只认第一个参数：把 --excel-worker 放在后面不应被当作 Worker 模式。"""
    result = _run("--port", "5099", "--excel-worker", "--help")

    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "--no-browser" in output  # 仍是宿主帮助
    assert "run-once" not in output


@pytest.mark.parametrize("args", [("--excel-worker", "run", "--help")])
def test_worker_branch_help_lists_run_command(args: tuple[str, ...]) -> None:
    result = _run(*args)
    assert result.returncode == 0, result.stderr[-2000:]
    output = result.stdout + result.stderr
    # --stop-file 在 CLI 里是 SUPPRESS 的（仅 controller 使用），改用公开参数断言。
    assert "--root" in output
    assert "--db" in output


_SENTINEL_MODULES_PROBE = (
    "import json, runpy, sys\n"
    "sys.argv = ['webui.py', '--excel-worker', '--help']\n"
    "try:\n"
    "    runpy.run_path({path!r}, run_name='__main__')\n"
    "except SystemExit:\n"
    "    pass\n"
    "print(json.dumps({{\n"
    "    'flask': 'flask' in sys.modules,\n"
    "    'web': any(name == 'web' or name.startswith('web.') for name in sys.modules),\n"
    "    'host_plugins': any(name.startswith('plugins.') for name in sys.modules),\n"
    "}}))\n"
)


def test_worker_branch_does_not_load_flask_or_web() -> None:
    """哨兵分支必须只走 Worker CLI：不导入 Flask/web/插件（否则会半启动宿主）。"""
    import json

    result = subprocess.run(
        [sys.executable, "-c", _SENTINEL_MODULES_PROBE.format(path=str(WEBUI))],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120.0,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload == {"flask": False, "web": False, "host_plugins": False}, payload


def test_importing_host_entry_does_not_import_xlwings() -> None:
    """宿主导入期不得拉起 Excel 自动化依赖（xlwings 只在 Worker 子进程路径导入）。"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, sys; import webui; "
            "print(json.dumps({'xlwings': 'xlwings' in sys.modules, "
            "'win32com': any(m.startswith('win32com') for m in sys.modules)}))",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120.0,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    import json as _json

    payload = _json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["xlwings"] is False, payload


def test_main_wires_production_excel_roots_into_create_app(monkeypatch) -> None:
    """webui.py 必须把 VSE_EXCEL_ROOTS_JSON 解析结果传给 create_app。

    回归守护：此前只有 `python web/app.py` 的 __main__ 读取该环境变量，经 webui.py
    （打包入口）启动时 Excel 任务接口恒为「未配置」，单 exe 的 Excel 功能不可用。
    """
    import webui as webui_module

    captured: dict[str, object] = {}

    class _FakeApp:
        extensions: dict[str, object] = {}

        def run(self, **kwargs):  # pragma: no cover - 仅保证 main 走到返回
            captured["ran"] = True

    def fake_create_app(**kwargs):
        captured.update(kwargs)
        return _FakeApp()

    sentinel_roots = {"business": Path("D:/ApprovedExcel")}
    monkeypatch.setattr("core.excel_tasks.load_production_excel_roots", lambda: sentinel_roots)
    monkeypatch.setattr("web.app.create_app", fake_create_app)

    code = webui_module.main(["--no-browser", "--no-sync-scheduler", "--port", "5098"])

    assert code == 0
    assert captured.get("excel_roots") == sentinel_roots, captured
