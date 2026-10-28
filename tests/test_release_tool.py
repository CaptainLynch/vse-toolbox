# -*- coding: utf-8 -*-
"""tools/release.py: file selection, signing, size budget."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import release  # noqa: E402

from tests.test_vse_boot_packages import keypair  # noqa: E402
from vse_boot.packages import verify_app_package  # noqa: E402


def fake_repo(root: Path) -> Path:
    for name in release.APP_DIRS:
        (root / name).mkdir(parents=True)
        (root / name / "__init__.py").write_text("", encoding="utf-8")
    (root / "core" / "__pycache__").mkdir()
    (root / "core" / "__pycache__" / "x.cpython-312.pyc").write_bytes(b"\0")
    (root / "plugins" / "demo" / "tests").mkdir(parents=True)
    (root / "plugins" / "demo" / "tests" / "test_x.py").write_text("", encoding="utf-8")
    (root / "plugins" / "demo" / "plugin.json").write_text("{}", encoding="utf-8")
    (root / "web" / "x.log").write_text("log", encoding="utf-8")
    (root / "tools").mkdir()
    (root / "tools" / "excel_worker_cli.py").write_text("", encoding="utf-8")
    (root / "webui.py").write_text("def main(argv=None):\n    return 0\n", encoding="utf-8")
    return root


def test_collect_skips_caches_tests_and_logs(tmp_path: Path) -> None:
    files = release.collect_app_files(fake_repo(tmp_path))
    assert "plugins/demo/plugin.json" in files and "webui.py" in files and "tools/excel_worker_cli.py" in files
    assert not [name for name in files if "__pycache__" in name or "/tests/" in name or name.endswith(".log")]


def test_build_signs_and_enforces_budget(tmp_path: Path) -> None:
    pem, keys = keypair()
    repo = fake_repo(tmp_path / "repo")
    target = release.build_app(version="2.0.3", key_pem=pem, notes="n", out_dir=tmp_path / "out", repo_root=repo)
    verified = verify_app_package(target.read_bytes(), keys)
    assert verified.version == "2.0.3" and "core/__init__.py" in verified.files
    (repo / "web" / "big.bin").write_bytes(__import__("os").urandom(300 * 1024))
    with pytest.raises(SystemExit, match="超过上限"):
        release.build_app(version="2.0.4", key_pem=pem, out_dir=tmp_path / "out", repo_root=repo, budget_mb=0.2)


def test_real_repository_fits_the_budget(tmp_path: Path) -> None:
    pem, _ = keypair()
    target = release.build_app(version="2.0.0", key_pem=pem, out_dir=tmp_path)
    assert target.stat().st_size < release.DEFAULT_BUDGET_MB * 1024 * 1024
