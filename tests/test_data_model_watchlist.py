# -*- coding: utf-8 -*-
"""数模设计审核流程报表的关注清单同步范围（签署日报规格 §9 S1、S8、S9、S11）。"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.archive_store import ArchiveStore
from core.credential_provider import MemoryCredentialProvider
from services import data_model_watchlist as W
from services.deliverable_form_analysis import build_form_snapshot
from services.project_status_connectors import TDCProjectStatusConnector
from services.project_status_sync_runner import SyncBindingContext
from services.scheduled_archive_connectors import TDCArchiveConnector, validate_archive_filters
from services.scheduled_archive_runner import ArchiveJobContext


def test_settings_validate_and_dedupe():
    assert W.watchlist_settings({}) == ("all", ())
    assert W.watchlist_settings({"syncScope": "watchlist", "watchlist": [" A-1 ", "A-2", "A-1"]}) == (
        "watchlist", ("A-1", "A-2"))
    for bad in ({"syncScope": "some"}, {"watchlist": "A-1"}, {"watchlist": [""]}, {"watchlist": ["a\nb"]},
                {"watchlist": ["x" * 65]}, {"watchlist": [f"S{i}" for i in range(W.MAX_WATCHLIST + 1)]},
                {"watchlist": [f"{i:063d}" for i in range(250)]}):  # 超过 filters_json 预算
        with pytest.raises(W.WatchlistError):
            W.watchlist_settings(bad)


def test_archive_filter_contract_accepts_and_normalizes_watchlist():
    checked = validate_archive_filters("tdc_data_model", {"syncScope": "watchlist", "watchlist": [" A-1", "A-1"],
                                                          "projectModel": "F610M"})
    assert checked == {"syncScope": "watchlist", "watchlist": ["A-1"], "projectModel": "F610M"}
    with pytest.raises(ValueError):
        validate_archive_filters("tdc_data_model", {"syncScope": "bad"})
    with pytest.raises(ValueError):
        validate_archive_filters("tdc_sor", {"watchlist": []})  # 只有数模任务有关注清单


def test_apply_watchlist_reads_both_row_shapes_and_keeps_missing():  # S8
    rows = [{"流水单号": "A-1"}, {"documentNo": "A-2", "incident": "900"}, {"流水单号": "B-9"}]
    kept, coverage = W.apply_watchlist(rows, "watchlist", ["A-1", "A-2", "A-3"])
    assert kept == rows[:2]
    assert coverage == {"kind": "watchlist", "serials": ["A-1", "A-2", "A-3"], "missing": ["A-3"]}
    assert W.apply_watchlist(rows, "all", ["A-1"]) == (rows, {"kind": "all"})
    # incident 是实例号，不是流水单号
    assert W.apply_watchlist([{"incident": "A-1"}], "watchlist", ["A-1"])[0] == []


def test_form_snapshot_records_coverage_and_latest_full_lookup():  # S11
    watch = build_form_snapshot("tdc_data_model", [], snapshot_at="2026-10-03T08:00:00Z", source_run_id=1,
                                source="test", coverage={"kind": "watchlist", "serials": ["A-1"], "missing": []})
    full = build_form_snapshot("tdc_data_model", [], snapshot_at="2026-10-02T08:00:00Z", source_run_id=1,
                               source="test", coverage={"kind": "all"})
    watch_schema = json.loads(watch.schema_json) if hasattr(watch, "schema_json") else watch.schema
    full_schema = json.loads(full.schema_json) if hasattr(full, "schema_json") else full.schema
    assert watch_schema["coverage"]["kind"] == "watchlist"
    assert "coverage" not in full_schema
    assert W.snapshot_coverage({"schema": watch_schema})["serials"] == ["A-1"]
    assert W.snapshot_coverage({"schema": full_schema}) == {"kind": "all"}

    class _Db:
        def list_deliverable_form_snapshots(self, form_key, limit=30):
            return [{"id": 2, "schema": watch_schema}, {"id": 1, "schema": full_schema}]

    assert W.latest_full_snapshot(_Db())["id"] == 1


# ── 自动归档路径 ─────────────────────────────────────────────────────


class _Auth:
    def __init__(self, **kwargs):
        pass

    def login(self, username, password):
        return SimpleNamespace(session=SimpleNamespace(close=lambda: None))


class _Crawler:
    rows = (
        {"incident": "900001", "documentNo": "A-1", "status": "审批中"},
        {"incident": "900002", "documentNo": "B-2", "status": "审批中"},
    )

    def __init__(self, **kwargs):
        self.output_dir = kwargs["output_dir"]
        self.filters = None

    def export_data_model(self, filters):
        self.filters = filters
        path = self.output_dir / "x.xlsx"
        path.write_bytes(b"not a workbook")  # 读不了 -> 走接口行
        return SimpleNamespace(path=path, file_name="x.xlsx", byte_count=path.stat().st_size)

    def crawl_data_model_all(self, filters, max_records):
        return SimpleNamespace(rows=self.rows)


def _archive_context(filters):
    return ArchiveJobContext(job_id=1, job_key="tdc_data_model", source_type="tdc", report_type="data_model",
                             filters=filters, output_subdir="", output_directory="", run_id=3)


def test_archive_connector_keeps_only_watchlist_rows(tmp_path: Path):
    crawlers = []

    def factory(**kwargs):
        crawlers.append(_Crawler(**kwargs))
        return crawlers[-1]

    connector = TDCArchiveConnector(ArchiveStore({"default": tmp_path}, reserve_bytes=0),
                                    auth_factory=_Auth, crawler_factory=factory)
    credential = SimpleNamespace(username="u", password="p")
    collection = connector.collect(_archive_context({"syncScope": "watchlist", "watchlist": ["A-1", "Z-9"]}),
                                   credential)
    assert [row["documentNo"] for row in collection.form_rows] == ["A-1"]
    assert collection.form_coverage == {"kind": "watchlist", "serials": ["A-1", "Z-9"], "missing": ["Z-9"]}
    assert collection.record_count == 2  # 归档原始件仍是全量
    assert crawlers[0].filters.serial_number is None  # 清单不发给 TDC

    full = connector.collect(_archive_context({}), credential)
    assert len(full.form_rows) == 2 and full.form_coverage == {"kind": "all"}


def test_empty_watchlist_is_not_ready(tmp_path: Path):  # S9
    from core.db_manager import DatabaseManager
    from core.db_common import ArchiveJobNotReadyError

    db = DatabaseManager(db_path=tmp_path / "t.db")
    db.init_database()
    job = next(j for j in db.list_archive_jobs() if j["job_key"] == "tdc_data_model")
    db.update_archive_job_config("tdc_data_model", enabled=False, credential_ref="ref",
                                 filters={"syncScope": "watchlist", "watchlist": []}, output_subdir="",
                                 expected_updated_at=job["updated_at"], actor="cli")
    with pytest.raises(ArchiveJobNotReadyError) as info:
        db.acquire_archive_job_lease(int(job["id"]), "sync_now", 60, validate_runtime_prerequisites=False)
    assert info.value.reason == "watchlist_empty"
    assert W.load_watchlist(db) == ("watchlist", ())


# ── 交付物自动同步路径 ───────────────────────────────────────────────


class _SyncTDC:
    def __init__(self, **kwargs):
        self.output_dir = kwargs["output_dir"]

    def crawl_data_model_all(self, filters, max_records):
        return SimpleNamespace(rows=list(_Crawler.rows), complete=True, stop_reason="reported_pages")

    def export_data_model(self, filters):
        raise RuntimeError("no export")


def test_project_status_connector_filters_rows_before_progress(tmp_path: Path):  # S1、S10
    connector = TDCProjectStatusConnector(
        MemoryCredentialProvider({"ref": ("u", "p")}), ArchiveStore({"default": tmp_path}, reserve_bytes=0),
        auth_factory=lambda **kw: _Auth(), crawler_factory=_SyncTDC,
    )
    base = SyncBindingContext(
        binding_id=1, deliverable_id="VPI-T2-D5", phase_id="VPI-T2", source_type="tdc", external_key="",
        match_rule={"aggregate": True}, mapping={}, cursor={}, expected_deliverable_updated_at="v1",
        run_id=7, credential_ref="ref",
    )
    full = connector.collect(base)
    watched = connector.collect(dataclasses.replace(base, watchlist=("B-2",)))
    assert len(full.analysis_rows) == 2 and full.coverage is None
    assert [row["documentNo"] for row in watched.analysis_rows] == ["B-2"]
    assert watched.coverage == {"kind": "watchlist", "serials": ["B-2"], "missing": []}
