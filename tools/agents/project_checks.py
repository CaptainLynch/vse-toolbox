"""Discover and run project checks without assuming a package manager."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def discover(root: Path) -> list[list[str]]:
    """Return safe, repository-local validation commands in preferred order."""
    commands: list[list[str]] = []
    if (root / "requirements.txt").exists() or (root / "pyproject.toml").exists() or (root / "setup.cfg").exists():
        if shutil.which("flake8") or _module_available("flake8"):
            commands.append([sys.executable, "-m", "flake8"])
        if (root / "setup.cfg").exists() and (_module_available("mypy") or shutil.which("mypy")):
            commands.append([sys.executable, "-m", "mypy", "core", "services", "web"])
        if (root / "tests").exists() and (_module_available("pytest") or shutil.which("pytest")):
            commands.append([sys.executable, "-m", "pytest"])
    package_json = root / "package.json"
    if package_json.exists():
        try:
            scripts = json.loads(package_json.read_text(encoding="utf-8")).get("scripts", {})
        except (OSError, json.JSONDecodeError):
            scripts = {}
        runner = "pnpm" if (root / "pnpm-lock.yaml").exists() else "yarn" if (root / "yarn.lock").exists() else "npm"
        for name in ("lint", "typecheck", "test", "build", "check"):
            if name in scripts:
                commands.append([runner, "run", name])
    return commands


def run_checks(root: Path, commands: list[list[str]], timeout: int = 600) -> list[dict[str, Any]]:
    results = []
    environment = os.environ.copy()
    environment.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    for command in commands:
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            results.append({"command": command, "exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr})
        except (OSError, subprocess.TimeoutExpired) as exc:
            results.append({"command": command, "exit_code": None, "stdout": "", "stderr": str(exc)})
    return results


def _module_available(name: str) -> bool:
    return subprocess.run([sys.executable, "-c", f"import {name}"], capture_output=True, check=False).returncode == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    commands = discover(root)
    output: dict[str, Any] = {"root": str(root), "checks": commands}
    if args.run:
        output["results"] = run_checks(root, commands)
    print(json.dumps(output, ensure_ascii=False, indent=2))
