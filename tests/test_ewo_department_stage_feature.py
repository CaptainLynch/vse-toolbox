from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from core.archive_store import ArchiveStore
from core.credential_provider import MemoryCredentialProvider
from core.db_manager import DatabaseManager
from services.aras_crawler import EWOReportFilters
from services.project_status_connectors import ArasProjectStatusConnector
from services.project_status_deliverable_analysis import (
    EWO_ACTIVE_STAGES,
    EWO_DEFAULT_DEPARTMENTS,
    EWO_STAGES,
    ProjectStatusDeliverableAnalysisService,
    normalize_analysis_rows,
    normalize_ewo_stage,
)
from services.project_status_sync_runner import SyncBindingContext


def test_ewo_stage_normalizer_and_defaults() -> None:
    assert EWO_DEFAULT_DEPARTMENTS == (
        "车身科", "车体科", "外饰科", "内饰科", "车体架构集成科",
    )
    assert EWO_STAGES == (
        "open", "draft1", "draft2", "edit1", "edit2", "proc", "impl", "close",
    )
    assert EWO_ACTIVE_STAGES == ("draft1", "draft2", "edit1", "edit2", "proc", "impl")
    assert normalize_ewo_stage(" Draft 1 ") == "draft1"
    assert normalize_ewo_stage("CLOSE") == "close"
    assert normalize_ewo_stage("not-a-stage") is None


def test_ewo_normalization_is_explicit_and_close_is_complete() -> None:
    rows = normalize_analysis_rows(
        [
            {"_no": "EWO-1", "_subject": "开放", "_rsp_smt": "车身科", "state": "OPEN"},
            {"_no": "EWO-2", "_subject": "关闭", "_rsp_smt": "车体科", "state": " close "},
            {"_no": "EWO-3", "_subject": "未知", "_rsp_smt": "外饰科", "state": "future"},
        ],
        source_type="aras",
    )
    assert [(row["source_stage"], row["is_completed"]) for row in rows] == [
        ("open", False), ("close", True), (None, False),
    ]
    assert rows[2]["stage_attention"] is True

    generic = normalize_analysis_rows(
        [{"id": "T-1", "status": "close", "actualDate": None}], source_type="tdc"
    )
    assert generic[0]["source_stage"] is None
    assert generic[0]["stage_attention"] is False


def test_ewo_summary_excludes_open_and_unknown_but_checks_active_dates(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "ewo-analysis.db")
    db.init_database()
    service = ProjectStatusDeliverableAnalysisService(db, clock=lambda: date(2026, 8, 23))
    service.publish(
        "VPI-T2-D3",
        1,
        [
            {"_no": "EWO-OPEN", "_rsp_smt": "车身科", "state": "OPEN", "_required_date": "2026-08-01"},
            {"_no": "EWO-ACTIVE", "_rsp_smt": "车体科", "state": "IMPL", "_required_date": "2026-08-01"},
            {"_no": "EWO-CLOSE", "_rsp_smt": "外饰科", "state": "CLOSE", "_required_date": "2026-08-01"},
            {"_no": "EWO-UNKNOWN", "_rsp_smt": "内饰科", "state": "FUTURE", "_required_date": "2026-08-01"},
        ],
        source_type="aras",
        snapshot_at="2026-08-23T00:00:00Z",
    )
    overview = service.overview("VPI-T2-D3")
    assert overview["summary"] == {
        "total": 2,
        "completed": 1,
        "incomplete": 1,
        "overdue": 1,
        "dueSoon": 0,
        "missingDueDate": 0,
    }
    assert service.items("VPI-T2-D3")["total"] == 2
    assert service.items("VPI-T2-D3", stage="open")["total"] == 1
    assert service.items("VPI-T2-D3", stage="all")["total"] == 4
    assert service.items("VPI-T2-D3", stage="close")["items"][0]["alertType"] is None
    assert any(item["stageAttention"] is True for item in service.items("VPI-T2-D3", stage="all")["items"])


def test_aras_connector_uses_rsp_smt_default_filter(tmp_path: Path) -> None:
    captured = {}

    class FakeAuth:
        base_url = "https://aras.example"

        def __init__(self, **kwargs):
            pass

        def login(self, username, password):
            return SimpleNamespace(session=object())

    class FakeCrawler:
        def __init__(self, *args, **kwargs):
            pass

        def crawl_ewo_report_all(self, filters, max_records):
            captured["filters"] = filters
            return SimpleNamespace(rows=[{"_no": "EWO-1", "_rsp_smt": "车身科"}])

    class FakeArchive:
        def write_csv(self, *args, **kwargs):
            return SimpleNamespace(as_metadata=lambda: {})

        def write_json(self, *args, **kwargs):
            return SimpleNamespace(as_metadata=lambda: {})

    connector = ArasProjectStatusConnector(
        MemoryCredentialProvider({"domain": ("user", "pass")}),
        FakeArchive(), auth_factory=FakeAuth, crawler_factory=FakeCrawler,
    )
    context = SyncBindingContext(
        binding_id=1, deliverable_id="VPI-T2-D3", phase_id="VPI-T2", source_type="aras",
        external_key="EWO-1", match_rule={"reportType": "ewo", "modelInfo": "F610S"},
        mapping={}, cursor={}, expected_deliverable_updated_at="v1", run_id=1,
        credential_ref="domain",
    )
    snapshot = connector.collect(context)
    filters = captured["filters"]
    assert filters.rsp_smt == "|".join(EWO_DEFAULT_DEPARTMENTS)
    assert filters.rsp_department is None
    assert snapshot.match_state == "matched"


def test_ewo_filter_payload_targets_rsp_smt() -> None:
    payload = ArasProjectStatusFiltersProbe.build(EWOReportFilters(rsp_smt="车身科|车体科"))
    assert "<_rsp_smt>车身科</_rsp_smt>" in payload
    assert "<_rsp_smt>车体科</_rsp_smt>" in payload
    assert "<_rsp_department>" not in payload


class ArasProjectStatusFiltersProbe:
    @staticmethod
    def build(filters: EWOReportFilters) -> str:
        from services.aras_crawler import ArasCrawlerClient

        return ArasCrawlerClient._build_ewo_payload(
            object.__new__(ArasCrawlerClient), filters, 1, 50, 2000, None
        )
