from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.archive_store import ArchiveStore
from core.credential_provider import MemoryCredentialProvider
from services.aras_crawler import EWOReportFilters
from services.project_status_connectors import (
    ArasProjectStatusConnector,
    RetryingConnector,
    TDCProjectStatusConnector,
)
from services.project_status_sync_runner import SyncBindingContext
from services.windows_http import WinHTTPError


def context(source: str = "tdc") -> SyncBindingContext:
    return SyncBindingContext(
        binding_id=1, deliverable_id="VPI-T2-D5", phase_id="VPI-T2",
        source_type=source, external_key="FLOW-1", match_rule={"incident": "FLOW-1"},
        mapping={"owner": "currentApprover"}, cursor={},
        expected_deliverable_updated_at="v1", run_id=7, credential_ref="ref",
    )


def test_aras_ewo_snapshot_matches_row_by_no_field():
    """同步执行侧的行匹配必须认得 EWO 行的 `_no` 编号，否则自动同步永远 not_found。"""
    from services.project_status_connectors import _snapshot

    ctx = SyncBindingContext(
        binding_id=2, deliverable_id="VPI-T2-D3", phase_id="VPI-T2",
        source_type="aras", external_key="EWO-049039",
        match_rule={"reportType": "ewo", "ewoNo": "EWO-049039"},
        mapping={"owner": "_rsp_name", "plannedDate": "_required_date"},
        cursor={}, expected_deliverable_updated_at="v1", run_id=8,
        credential_ref="domain",
    )
    row = {
        "id": "AAAABBBBCCCCDDDDEEEEFFFF00001111",
        "_no": "EWO-049039", "_rsp_name": "张三",
        "_required_date": "2026-09-15", "state": "测试中",
    }
    snapshot = _snapshot(ctx, [row], [])
    assert snapshot.match_state == "matched"
    assert snapshot.candidates[0].external_key == "EWO-049039"
    assert snapshot.candidates[0].field_values == {
        "owner": "张三", "plannedDate": "2026-09-15"
    }


class FakeAuth:
    base_url = "https://fixed.example"

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def login(self, username, password):
        assert username == "user" and password == "pass"
        return SimpleNamespace(session=object())


class TrackingSession:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


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


def test_tdc_session_closes_when_crawl_fails(tmp_path: Path):
    session = TrackingSession()

    class TrackingAuth(FakeAuth):
        def login(self, username, password):
            return SimpleNamespace(session=session)

    class FailingTDC(FakeTDC):
        def crawl_data_model_all(self, filters, max_records):
            raise RuntimeError("offline failure")

    connector = TDCProjectStatusConnector(
        MemoryCredentialProvider({"ref": ("user", "pass")}),
        ArchiveStore({"default": tmp_path}, reserve_bytes=0),
        auth_factory=TrackingAuth,
        crawler_factory=FailingTDC,
    )
    with pytest.raises(RuntimeError, match="offline failure"):
        connector.collect(context())
    assert session.closed is True


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


def test_native_winhttp_failure_is_retried_twice():
    calls = []

    class Failing:
        def collect(self, value):
            calls.append(value)
            raise WinHTTPError("native transport failure")

    connector = RetryingConnector(Failing(), sleeper=lambda delay: None)
    with pytest.raises(WinHTTPError):
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


def test_aras_session_closes_when_crawl_fails(tmp_path: Path):
    session = TrackingSession()

    class TrackingAuth(FakeAuth):
        def login(self, username, password):
            return SimpleNamespace(session=session)

    class FailingAras:
        def __init__(self, *args, **kwargs):
            pass

        def crawl_ewo_report_all(self, filters, max_records):
            raise RuntimeError("offline failure")

    connector = ArasProjectStatusConnector(
        MemoryCredentialProvider({"ref": ("user", "pass")}),
        ArchiveStore({"default": tmp_path}, reserve_bytes=0),
        auth_factory=TrackingAuth,
        crawler_factory=FailingAras,
    )
    value = context("aras")
    value = SyncBindingContext(**{**value.__dict__, "match_rule": {"reportType": "ewo"}})
    with pytest.raises(RuntimeError, match="offline failure"):
        connector.collect(value)
    assert session.closed is True


def test_aras_connector_resolves_opaque_credential_and_queries_ewo(tmp_path: Path):
    calls = {}
    session = TrackingSession()

    class RecordingAuth(FakeAuth):
        def login(self, username, password):
            calls["credentials"] = (username, password)
            return SimpleNamespace(session=session)

    class RecordingCrawler:
        def __init__(self, base_url, session=None, timeout=None, prewarm=False):
            calls["client"] = {
                "base_url": base_url,
                "session": session,
                "timeout": timeout,
                "prewarm": prewarm,
            }

        def crawl_ewo_report_all(self, filters, max_records):
            calls["filters"] = filters
            calls["max_records"] = max_records
            return SimpleNamespace(rows=[{"_no": "EWO-1", "_rsp_name": "负责人"}])

    connector = ArasProjectStatusConnector(
        MemoryCredentialProvider({"aras-ref": ("operator", "pw-secret")}),
        ArchiveStore({"default": tmp_path}, reserve_bytes=0),
        auth_factory=RecordingAuth,
        crawler_factory=RecordingCrawler,
    )
    ctx = SyncBindingContext(
        binding_id=12,
        deliverable_id="VPI-T2-D3",
        phase_id="VPI-T2",
        source_type="aras",
        external_key="EWO-1",
        match_rule={"reportType": "ewo", "ewoNo": "EWO-1"},
        mapping={"owner": "_rsp_name"},
        cursor={},
        expected_deliverable_updated_at="v1",
        run_id=12,
        credential_ref="aras-ref",
    )

    snapshot = connector.collect(ctx)

    assert calls["credentials"] == ("operator", "pw-secret")
    assert calls["client"]["session"] is session
    assert calls["filters"].ewo_no == "EWO-1"
    assert calls["max_records"] == 2000
    assert snapshot.match_state == "matched"
    assert snapshot.candidates[0].field_values == {"owner": "负责人"}
    assert all(
        "pw-secret" not in (tmp_path / item["relative_path"]).read_text(
            encoding="utf-8", errors="ignore"
        )
        for item in snapshot.artifacts
    )
    assert session.closed is True


def test_aras_connector_model_scope_filter_from_match_rule():
    """matchRule.modelInfo 存在时按车型抓全量 EWO（科室分析用），不再按单号过滤。"""
    captured = {}

    class FakeAuth:
        base_url = "http://aras.example"

        def __init__(self, **kwargs):
            pass

        def login(self, username, password):
            return SimpleNamespace(session=object())

    class FakeCrawler:
        def __init__(self, base_url, session=None, timeout=None, prewarm=False):
            pass

        def crawl_ewo_report_all(self, filters=None, max_records=None):
            captured["filters"] = filters
            captured["max_records"] = max_records
            return SimpleNamespace(
                rows=[{"_no": "EWO-049039", "_rsp_smt": "车体科", "_rsp_name": "莫仕沾"}],
                page=1,
                item_ids=["ID-1"],
            )

    class FakeArchive:
        def write_csv(self, *args, **kwargs):
            return SimpleNamespace(as_metadata=lambda: {})

        def write_json(self, *args, **kwargs):
            return SimpleNamespace(as_metadata=lambda: {})

    connector = ArasProjectStatusConnector(
        MemoryCredentialProvider({"domain": ("user", "pass")}),
        FakeArchive(),
        auth_factory=FakeAuth,
        crawler_factory=FakeCrawler,
    )
    ctx = SyncBindingContext(
        binding_id=3, deliverable_id="VPI-T2-D3", phase_id="VPI-T2",
        source_type="aras", external_key="EWO-049039",
        match_rule={"reportType": "ewo", "ewoNo": "EWO-049039", "modelInfo": "F610S"},
        mapping={"owner": "_rsp_name"}, cursor={},
        expected_deliverable_updated_at="v1", run_id=9, credential_ref="domain",
    )
    snapshot = connector.collect(ctx)
    assert captured["filters"].model_info == "F610S"
    assert captured["filters"].ewo_no is None
    assert snapshot.match_state == "matched"
    assert snapshot.analysis_rows[0]["_rsp_smt"] == "车体科"
    assert snapshot.candidates[0].external_key == "EWO-049039"


def test_aras_connector_keeps_ewo_no_filter_without_model_info():
    """未配置 modelInfo 的旧绑定保持按单号过滤的行为。"""
    captured = {}

    class FakeAuth:
        base_url = "http://aras.example"

        def __init__(self, **kwargs):
            pass

        def login(self, username, password):
            return SimpleNamespace(session=object())

    class FakeCrawler:
        def __init__(self, base_url, session=None, timeout=None, prewarm=False):
            pass

        def crawl_ewo_report_all(self, filters=None, max_records=None):
            captured["filters"] = filters
            return SimpleNamespace(rows=[{"_no": "EWO-049039"}], page=1, item_ids=["ID-1"])

    class FakeArchive:
        def write_csv(self, *args, **kwargs):
            return SimpleNamespace(as_metadata=lambda: {})

        def write_json(self, *args, **kwargs):
            return SimpleNamespace(as_metadata=lambda: {})

    connector = ArasProjectStatusConnector(
        MemoryCredentialProvider({"domain": ("user", "pass")}),
        FakeArchive(),
        auth_factory=FakeAuth,
        crawler_factory=FakeCrawler,
    )
    ctx = SyncBindingContext(
        binding_id=4, deliverable_id="VPI-T2-D3", phase_id="VPI-T2",
        source_type="aras", external_key="EWO-049039",
        match_rule={"reportType": "ewo", "ewoNo": "EWO-049039"},
        mapping={"owner": "_rsp_name"}, cursor={},
        expected_deliverable_updated_at="v1", run_id=10, credential_ref="domain",
    )
    snapshot = connector.collect(ctx)
    assert captured["filters"].ewo_no == "EWO-049039"
    assert captured["filters"].model_info is None
    assert snapshot.match_state == "matched"


def test_aras_connector_uses_rsp_department_keyword_filter():
    """EWO 同步默认范围改为部门关键词 LIKE 并集（rsp_department），不再传五科室 rsp_smt。"""
    # 局部导入：实现落地前常量不存在，只让本测试失败（ImportError），
    # 不阻断同模块其余既有测试。
    from services.project_status_deliverable_analysis import EWO_DEPARTMENT_KEYWORDS

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
            return SimpleNamespace(
                rows=[{"_no": "EWO-1", "_rsp_smt": "车身科", "_rsp_department": "技术中心_车体工程"}],
                page=1,
                item_ids=["ID-1"],
            )

    class FakeArchive:
        def write_csv(self, *args, **kwargs):
            return SimpleNamespace(as_metadata=lambda: {})

        def write_json(self, *args, **kwargs):
            return SimpleNamespace(as_metadata=lambda: {})

    connector = ArasProjectStatusConnector(
        MemoryCredentialProvider({"domain": ("user", "pass")}),
        FakeArchive(), auth_factory=FakeAuth, crawler_factory=FakeCrawler,
    )
    ctx = SyncBindingContext(
        binding_id=5, deliverable_id="VPI-T2-D3", phase_id="VPI-T2", source_type="aras",
        external_key="EWO-1", match_rule={"reportType": "ewo", "modelInfo": "F610S"},
        mapping={}, cursor={}, expected_deliverable_updated_at="v1", run_id=11,
        credential_ref="domain",
    )
    snapshot = connector.collect(ctx)
    filters = captured["filters"]
    assert filters.rsp_department == "|".join(f"*{kw}*" for kw in EWO_DEPARTMENT_KEYWORDS)
    assert filters.rsp_smt is None
    # context.match_rule 里已有 modelInfo，车型查询条件不受默认范围调整影响。
    assert filters.model_info == "F610S"
    assert snapshot.match_state == "matched"


def test_ewo_filter_payload_targets_rsp_department_like() -> None:
    payload = ArasProjectStatusFiltersProbe.build(
        EWOReportFilters(rsp_department="*车体工程*|*外饰*|*内饰*")
    )
    assert (
        "<or>"
        '<_rsp_department condition="like">*车体工程*</_rsp_department>'
        '<_rsp_department condition="like">*外饰*</_rsp_department>'
        '<_rsp_department condition="like">*内饰*</_rsp_department>'
        "</or>"
    ) in payload
    assert "<_rsp_smt>" not in payload


class ArasProjectStatusFiltersProbe:
    @staticmethod
    def build(filters: EWOReportFilters) -> str:
        from services.aras_crawler import ArasCrawlerClient

        return ArasCrawlerClient._build_ewo_payload(
            object.__new__(ArasCrawlerClient), filters, 1, 50, 2000, None
        )
