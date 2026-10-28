# -*- coding: utf-8 -*-
"""Boot state machine: first install, trial, commit, abandon, crash-safety, manual rollback."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from vse_boot import dbsnap
from vse_boot.layout import InstallLayout
from vse_boot.state import BootState, BootStateError


def stage(layout: InstallLayout, version: str, *, marker: str = "") -> None:
    entry = layout.staging_dir / f"app-{version}"
    (entry / "files").mkdir(parents=True)
    (entry / "files" / "webui.py").write_text(f"# {version} {marker}", encoding="utf-8")
    (entry / "staged.json").write_text(json.dumps({"kind": "app", "version": version, "notes": "", "migrations": []}), encoding="utf-8")


@pytest.fixture()
def layout(tmp_path: Path) -> InstallLayout:
    return InstallLayout(tmp_path).ensure()


def test_first_install_activates_without_trial(layout: InstallLayout) -> None:
    stage(layout, "2.0.0")
    state = BootState(layout)
    assert state.install_staged() == ["2.0.0"]
    assert state.select_for_boot() == ("2.0.0", False)
    assert (layout.app_dir("2.0.0") / "app.json").is_file()
    assert not any(layout.staging_dir.iterdir())


def test_update_trial_commit_and_prune(layout: InstallLayout) -> None:
    stage(layout, "2.0.0")
    BootState(layout).install_staged()
    for version in ("2.0.1", "2.0.2"):
        stage(layout, version)
        state = BootState(layout)
        state.install_staged()
        assert state.select_for_boot() == (version, True)
        state.commit(version)
    state = BootState(layout)
    assert (state.app["current"], state.app["previous"], state.app["trial"]) == ("2.0.2", "2.0.1", None)
    # 只保留当前版本和上一版本两个目录
    assert layout.installed_app_versions() == ["2.0.1", "2.0.2"]
    assert [e["kind"] for e in state.events][:2] == ["activated", "installed"]


def test_unhealthy_trial_is_abandoned_and_removed(layout: InstallLayout) -> None:
    stage(layout, "2.0.0")
    BootState(layout).install_staged()
    stage(layout, "2.0.1")
    state = BootState(layout)
    state.install_staged()
    assert state.select_for_boot() == ("2.0.1", True)
    state.abandon("2.0.1", reason="健康检查未通过")
    assert state.select_for_boot() == ("2.0.0", False)
    assert not layout.app_dir("2.0.1").exists()
    assert state.events[0]["kind"] == "rolledBack" and state.events[0]["reason"] == "健康检查未通过"


def test_trial_that_crashed_the_process_is_abandoned_on_next_start(layout: InstallLayout) -> None:
    stage(layout, "2.0.0")
    BootState(layout).install_staged()
    stage(layout, "2.0.1")
    first = BootState(layout)
    first.install_staged()
    assert first.select_for_boot() == ("2.0.1", True)
    # 进程在 commit/abandon 之前崩溃；重新读取磁盘状态
    assert BootState(layout).select_for_boot() == ("2.0.0", False)
    assert BootState(layout).events[0]["kind"] == "rolledBack"


def test_half_written_staging_is_ignored(layout: InstallLayout) -> None:
    stage(layout, "2.0.0")
    BootState(layout).install_staged()
    partial = layout.staging_dir / ".tmp-app-2.0.1"
    (partial / "files").mkdir(parents=True)
    (partial / "staged.json").write_text(json.dumps({"version": "2.0.1"}), encoding="utf-8")
    assert BootState(layout).install_staged() == []


def test_manual_rollback_swaps_versions_and_needs_previous(layout: InstallLayout) -> None:
    stage(layout, "2.0.0")
    BootState(layout).install_staged()
    with pytest.raises(BootStateError):
        BootState(layout).rollback()
    stage(layout, "2.0.1")
    state = BootState(layout)
    state.install_staged()
    state.select_for_boot()
    state.commit("2.0.1")
    assert BootState(layout).rollback() == "2.0.0"
    assert BootState(layout).select_for_boot() == ("2.0.0", False)


def test_no_installed_version_raises(layout: InstallLayout) -> None:
    with pytest.raises(BootStateError):
        BootState(layout).select_for_boot()


def test_db_snapshot_restore_and_retention(tmp_path: Path) -> None:
    db = tmp_path / "vse_toolbox.db"
    with sqlite3.connect(db) as conn:
        conn.execute("create table t (v text)")
        conn.execute("insert into t values ('before')")
    snaps = tmp_path / "snaps"
    taken = [dbsnap.snapshot(db, snaps, tag=f"v{i}") for i in range(5)]
    assert all(taken) and len(list(snaps.glob("*.db"))) == dbsnap.KEEP_SNAPSHOTS
    with sqlite3.connect(db) as conn:
        conn.execute("update t set v = 'migrated'")
    dbsnap.restore(taken[-1], db)
    with sqlite3.connect(db) as conn:
        assert conn.execute("select v from t").fetchone()[0] == "before"
    assert dbsnap.snapshot(tmp_path / "missing.db", snaps, tag="x") is None


def test_crashed_trial_restores_pre_trial_snapshot(layout: InstallLayout) -> None:
    with sqlite3.connect(layout.database) as conn:
        conn.execute("create table t (v text)")
        conn.execute("insert into t values ('before')")
    stage(layout, "2.0.0")
    BootState(layout).install_staged()
    stage(layout, "2.0.1")
    state = BootState(layout)
    state.install_staged()
    assert state.select_for_boot() == ("2.0.1", True)
    snap = dbsnap.snapshot(layout.database, layout.snapshots_dir, tag="2.0.1")
    state.set_trial_snapshot(str(snap))
    with sqlite3.connect(layout.database) as conn:
        conn.execute("update t set v = 'half-migrated'")
    # 进程崩溃，下次启动
    assert BootState(layout).select_for_boot() == ("2.0.0", False)
    with sqlite3.connect(layout.database) as conn:
        assert conn.execute("select v from t").fetchone()[0] == "before"
    kinds = [e["kind"] for e in BootState(layout).events]
    assert kinds[:2] == ["rolledBack", "databaseRestored"]


def test_corrupt_state_is_rebuilt_from_installed_versions(layout: InstallLayout) -> None:
    stage(layout, "2.0.0")
    BootState(layout).install_staged()
    layout.app_dir("2.0.1").mkdir(parents=True)
    layout.state_file.write_text("{ truncated", encoding="utf-8")
    state = BootState(layout)
    assert (state.app["current"], state.app["previous"]) == ("2.0.1", "2.0.0")
    assert state.events[0]["kind"] == "stateRecovered"
    assert list(layout.state_dir.glob("boot.corrupt-*.json"))


def test_bad_staging_entry_is_skipped_and_current_still_boots(layout: InstallLayout) -> None:
    stage(layout, "2.0.0")
    BootState(layout).install_staged()
    broken = layout.staging_dir / "app-2.0.1"
    broken.mkdir()
    (broken / "staged.json").write_text(json.dumps({"version": "2.0.1"}), encoding="utf-8")  # 没有 files/
    state = BootState(layout)
    assert state.install_staged() == []
    assert state.select_for_boot() == ("2.0.0", False)
    assert state.events[0]["kind"] == "installFailed"
    assert not broken.exists()
