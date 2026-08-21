from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.archive_store import ArchiveStore
from core.credential_provider import MemoryCredentialProvider
from services.project_status_connectors import (
    ArasProjectStatusConnector,
    RetryingConnector,
    TDCProjectStatusConnector,
)
from services.project_status_sync_runner import SyncBindingContext


def context(source: str = "tdc") -> SyncBindingContext:
    return SyncBindingContext(
        binding_id=1, deliverable_id="VPI-T2-D5", phase_id="VPI-T2",
        source_type=source, external_key="FLOW-1", match_rule={"incident": "FLOW-1"},
        mapping={"owner": "currentApprover"}, cursor={},
        expected_deliverable_updated_at="v1", run_id=7, credential_ref="ref",
    )


class FakeAuth:
    base_url = "https://fixed.example"

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def login(self, username, password):
        assert username == "user" and password == "pass"
        return SimpleNamespace(session=object())


class FakeTDC:
    def __init__(self, **kwargs):
        self.output_dir = kwargs["output_dir"]

    def crawl_data_model_all(self, filters, max_records):
        return SimpleNamespace(rows=[{"incident": "FLOW-1", "currentApprover": "审批人"}])

    def export_data_model(self, filters):
        path = self.output_dir / "official.xlsx"
        path.write_bytes(b"PK\x03\x04fake")
        return SimpleNamespace(path=path, file_name="official.xlsx", byte_count=8)


def test_tdc_connector_archives_and_returns_normalized_candidate(tmp_path: Path):
    archive = ArchiveStore({"default": tmp_path}, reserve_bytes=0)
    connector = TDCProjectStatusConnector(
        MemoryCredentialProvider({"ref": ("user", "pass")}), archive,
        auth_factory=FakeAuth, crawler_factory=FakeTDC,
    )
    snapshot = connector.collect(context())
    assert snapshot.match_state == "matched"
    assert snapshot.candidates[0].field_values == {"owner": "审批人"}
    assert {item["artifact_type"] for item in snapshot.artifacts} == {"xlsx", "csv", "json"}
    assert all((tmp_path / item["relative_path"]).is_file() for item in snapshot.artifacts)


def test_tdc_zero_match_needs_attention_without_guess(tmp_path: Path):
    class EmptyTDC(FakeTDC):
        def crawl_data_model_all(self, filters, max_records):
            return SimpleNamespace(rows=[])

    connector = TDCProjectStatusConnector(
        MemoryCredentialProvider({"ref": ("user", "pass")}),
        ArchiveStore({"default": tmp_path}, reserve_bytes=0),
        auth_factory=FakeAuth, crawler_factory=EmptyTDC,
    )
    assert connector.collect(context()).match_state == "not_found"


def test_retry_is_bounded_to_two_attempts():
    calls = []

    class Failing:
        def collect(self, value):
            calls.append(value)
            raise TimeoutError("timeout")

    connector = RetryingConnector(Failing(), sleeper=lambda delay: None)
    with pytest.raises(TimeoutError):
        connector.collect(context())
    assert len(calls) == 2


def test_aras_rejects_unapproved_report_before_auth(tmp_path: Path):
    connector = ArasProjectStatusConnector(
        MemoryCredentialProvider({"ref": ("user", "pass")}),
        ArchiveStore({"default": tmp_path}, reserve_bytes=0),
        auth_factory=FakeAuth,
    )
    value = context("aras")
    value = SyncBindingContext(**{**value.__dict__, "match_rule": {"reportType": "paa"}})
    with pytest.raises(ValueError, match="EWO only"):
        connector.collect(value)
