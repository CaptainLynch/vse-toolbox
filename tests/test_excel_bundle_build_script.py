# -*- coding: utf-8 -*-
"""Offline tests for the tools/build_excel_bundle.ps1 dual-executable build script."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO_ROOT / "tools" / "build_excel_bundle.ps1"


def find_powershell() -> str:
    for name in ("pwsh", "powershell"):
        exe = shutil.which(name)
        if exe:
            return exe
    pytest.skip("PowerShell executable (pwsh or powershell) not found on system.")


def normalize_ps_output(text: str) -> str:
    cleaned_lines = []
    for line in text.splitlines():
        trimmed = re.sub(r"^\s*\|\s*", "", line).strip()
        if trimmed and not trimmed.startswith("~") and not trimmed.startswith("Line |"):
            cleaned_lines.append(trimmed)
    return " ".join(cleaned_lines)


def test_build_script_exists() -> None:
    assert BUILD_SCRIPT.exists(), "tools/build_excel_bundle.ps1 must exist"
    assert BUILD_SCRIPT.is_file(), "tools/build_excel_bundle.ps1 must be a regular file"


def test_build_script_static_analysis() -> None:
    content = BUILD_SCRIPT.read_text(encoding="utf-8")

    # Parameters
    assert "$OutputDir" in content
    assert "$WorkDir" in content
    assert "$PythonExecutable" in content
    assert "$Clean" in content
    assert "$NoCleanup" in content

    # Specs
    assert "VSE-WebUI.spec" in content
    assert "VSE-ExcelWorker.spec" in content

    # PyInstaller flags
    assert "--distpath" in content
    assert "--workpath" in content
    assert "--noconfirm" in content

    # Verification of sibling executables
    assert "VSE-WebUI.exe" in content
    assert "VSE-ExcelWorker.exe" in content
    assert "SHA256SUMS.txt" in content
    assert "Get-FileHash" in content
    assert "Test-Path" in content
    assert "-PathType Leaf" in content

    # Confinement safety for .runtime cleanup
    assert "Assert-SafeRuntimePath" in content
    assert ".runtime" in content


@pytest.fixture()
def mock_pyinstaller_python(tmp_path: Path) -> Path:
    """Create a mock python runner that emulates PyInstaller building sibling executables."""
    mock_script = tmp_path / "mock_pyinstaller.py"
    mock_script.write_text(
        """# -*- coding: utf-8 -*-
import sys
from pathlib import Path

args = sys.argv[1:]
if "-m" in args and "PyInstaller" in args:
    dist_idx = -1
    for i, a in enumerate(args):
        if a == "--distpath" and i + 1 < len(args):
            dist_idx = i + 1
            break
    if dist_idx != -1:
        out_dir = Path(args[dist_idx])
        out_dir.mkdir(parents=True, exist_ok=True)
        # Determine which spec is being built
        for a in args:
            if "VSE-WebUI.spec" in a:
                (out_dir / "VSE-WebUI.exe").write_bytes(b"dummy webui exe")
            elif "VSE-ExcelWorker.spec" in a:
                (out_dir / "VSE-ExcelWorker.exe").write_bytes(b"dummy worker exe")
    sys.exit(0)

# Default exit code
sys.exit(0)
""",
        encoding="utf-8",
    )

    # Batch wrapper or python script runner
    wrapper = tmp_path / "mock_python.cmd"
    wrapper.write_text(
        f'@echo off\n"{sys.executable}" "{mock_script}" %*\n',
        encoding="utf-8",
    )
    return wrapper


def test_build_script_successful_mock_build(tmp_path: Path, mock_pyinstaller_python: Path) -> None:
    ps = find_powershell()
    out_dir = tmp_path / "custom_dist"
    work_dir = REPO_ROOT / ".runtime" / f"test_build_work_{tmp_path.name}"

    cmd = [
        ps,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(BUILD_SCRIPT),
        "-OutputDir",
        str(out_dir),
        "-WorkDir",
        str(work_dir),
        "-PythonExecutable",
        str(mock_pyinstaller_python),
    ]

    res = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert res.returncode == 0, f"Script failed: {res.stdout}\n{res.stderr}"
    assert "Verification succeeded:" in res.stdout
    assert (out_dir / "VSE-WebUI.exe").is_file()
    assert (out_dir / "VSE-ExcelWorker.exe").is_file()


def test_build_script_fails_when_pyinstaller_errors(tmp_path: Path) -> None:
    ps = find_powershell()
    failing_python = tmp_path / "failing_python.cmd"
    failing_python.write_text("@echo off\nexit /b 1\n", encoding="utf-8")

    out_dir = tmp_path / "custom_dist_fail"
    work_dir = REPO_ROOT / ".runtime" / f"test_build_fail_{tmp_path.name}"

    cmd = [
        ps,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(BUILD_SCRIPT),
        "-OutputDir",
        str(out_dir),
        "-WorkDir",
        str(work_dir),
        "-PythonExecutable",
        str(failing_python),
    ]

    res = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert res.returncode != 0
    assert "PyInstaller failed" in res.stderr or "PyInstaller failed" in res.stdout


def test_build_script_fails_when_executable_missing(tmp_path: Path) -> None:
    ps = find_powershell()
    # Python mock that exits 0 but doesn't create the executables
    noop_python = tmp_path / "noop_python.cmd"
    noop_python.write_text("@echo off\nexit /b 0\n", encoding="utf-8")

    out_dir = tmp_path / "custom_dist_missing"
    work_dir = REPO_ROOT / ".runtime" / f"test_build_missing_{tmp_path.name}"

    cmd = [
        ps,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(BUILD_SCRIPT),
        "-OutputDir",
        str(out_dir),
        "-WorkDir",
        str(work_dir),
        "-PythonExecutable",
        str(noop_python),
    ]

    res = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert res.returncode != 0
    combined = normalize_ps_output(res.stdout + res.stderr)
    assert "Verification failed" in combined


def test_build_script_refuses_cleanup_outside_runtime(tmp_path: Path, mock_pyinstaller_python: Path) -> None:
    ps = find_powershell()
    out_dir = tmp_path / "custom_dist"
    # Work directory outside .runtime
    outside_work_dir = tmp_path / "outside_work"

    cmd = [
        ps,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(BUILD_SCRIPT),
        "-OutputDir",
        str(out_dir),
        "-WorkDir",
        str(outside_work_dir),
        "-PythonExecutable",
        str(mock_pyinstaller_python),
        "-Clean",
    ]

    res = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert res.returncode != 0
    combined = normalize_ps_output(res.stdout + res.stderr)
    assert "Cleanup refused" in combined or "not strictly inside .runtime" in combined
