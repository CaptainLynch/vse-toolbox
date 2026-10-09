from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.archive_store import ArchiveStore
from core.credential_provider import MemoryCredentialProvider
from services.aras_crawler import EWOReportFilters
from services.aras_ncr_workbook import (
    NcrWorkbookError,
    NcrWorkbookOutcome,
    NcrWorkbookRow,
)
from services.pagination_integrity import WorkbookBookkeeping
from services.project_status_connectors import _exclude_tdc_scope_rows
from services.tdc_crawler import TDCCrawlerError
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
        return SimpleNamespace(
            rows=[{"incident": "FLOW-1", "currentApprover": "审批人"}],
            complete=True,
            stop_reason="reported_pages",
        )

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


def test_tdc_connector_document_no_narrows_rows_locally(tmp_path: Path):
    """运行期消费 matchRule.documentNo：全量抓取后本地精确收窄，不发给上游。

    流水单号（documentNo）不是 TDC 查询参数：绑定带它时，连接器抓全量后按
    documentNo 收窄行集，快照身份/候选匹配仍按 externalKey（incident）走既有机制。
    """
    class FullThenFilteredTDC(FakeTDC):
        def crawl_data_model_all(self, filters, max_records):
            assert filters.instance_no is None  # documentNo 绝不充当 incident 发上游
            return SimpleNamespace(
                rows=[
                    {"incident": "900001", "documentNo": "3D-00001018", "currentApprover": "张三"},
                    {"incident": "900002", "documentNo": "3D-00001193", "currentApprover": "李四"},
                    {"incident": "900003", "documentNo": "3D-00001200", "currentApprover": "王五"},
                ],
                complete=True,
                stop_reason="reported_pages",
            )

        def export_data_model(self, filters):
            path = self.output_dir / "official.xlsx"
            path.write_bytes(b"PK\x03\x04fake")
            return SimpleNamespace(path=path, file_name="official.xlsx", byte_count=8)

    archive = ArchiveStore({"default": tmp_path}, reserve_bytes=0)
    connector = TDCProjectStatusConnector(
        MemoryCredentialProvider({"ref": ("user", "pass")}), archive,
        auth_factory=FakeAuth, crawler_factory=FullThenFilteredTDC,
    )
    ctx = SyncBindingContext(
        binding_id=20, deliverable_id="VPI-T2-D5", phase_id="VPI-T2",
        source_type="tdc", external_key="900002",
        match_rule={"reportType": "data_model", "documentNo": "3D-00001193"},
        mapping={"owner": "currentApprover"}, cursor={},
        expected_deliverable_updated_at="v1", run_id=21, credential_ref="ref",
    )
    snapshot = connector.collect(ctx)
    # 命中行只剩 documentNo 匹配的那一行；单记录身份仍按 externalKey（incident）。
    assert len(snapshot.analysis_rows) == 1
    assert snapshot.analysis_rows[0]["incident"] == "900002"
    assert snapshot.match_state == "matched"
    assert snapshot.candidates[0].field_values == {"owner": "李四"}


def test_tdc_connector_document_no_no_match_is_not_found(tmp_path: Path):
    """绑定流水单号在源端已消失：按 documentNo 收窄后 0 行 → not_found（不是全量误报 matched）。"""

    class NoHitTDC(FakeTDC):
        def crawl_data_model_all(self, filters, max_records):
            return SimpleNamespace(
                rows=[{"incident": "900001", "documentNo": "3D-00001018"}],
                complete=True, stop_reason="reported_pages",
            )

        def export_data_model(self, filters):
            path = self.output_dir / "official.xlsx"
            path.write_bytes(b"PK\x03\x04fake")
            return SimpleNamespace(path=path, file_name="official.xlsx", byte_count=8)

    archive = ArchiveStore({"default": tmp_path}, reserve_bytes=0)
    connector = TDCProjectStatusConnector(
        MemoryCredentialProvider({"ref": ("user", "pass")}), archive,
        auth_factory=FakeAuth, crawler_factory=NoHitTDC,
    )
    ctx = SyncBindingContext(
        binding_id=21, deliverable_id="VPI-T2-D5", phase_id="VPI-T2",
        source_type="tdc", external_key="900001",
        match_rule={"reportType": "data_model", "documentNo": "3D-00009999"},
        mapping={"owner": "currentApprover"}, cursor={},
        expected_deliverable_updated_at="v1", run_id=22, credential_ref="ref",
    )
    snapshot = connector.collect(ctx)
    assert snapshot.match_state == "not_found"


def test_tdc_connector_document_no_missing_column_raises_not_not_found(tmp_path: Path):
    """空集归因：行集完全没有流水单号列（结构漂移）→ 明确报错，不落 not_found。"""

    class NoColumnTDC(FakeTDC):
        def crawl_data_model_all(self, filters, max_records):
            return SimpleNamespace(
                rows=[{"incident": "900001", "currentApprover": "张三"}],
                complete=True, stop_reason="reported_pages",
            )

        def export_data_model(self, filters):
            path = self.output_dir / "official.xlsx"
            path.write_bytes(b"PK\x03\x04fake")
            return SimpleNamespace(path=path, file_name="official.xlsx", byte_count=8)

    archive = ArchiveStore({"default": tmp_path}, reserve_bytes=0)
    connector = TDCProjectStatusConnector(
        MemoryCredentialProvider({"ref": ("user", "pass")}), archive,
        auth_factory=FakeAuth, crawler_factory=NoColumnTDC,
    )
    ctx = SyncBindingContext(
        binding_id=23, deliverable_id="VPI-T2-D5", phase_id="VPI-T2",
        source_type="tdc", external_key="900001",
        match_rule={"reportType": "data_model", "documentNo": "3D-00001018"},
        mapping={"owner": "currentApprover"}, cursor={},
        expected_deliverable_updated_at="v1", run_id=24, credential_ref="ref",
    )
    with pytest.raises(ValueError, match="流水单号列"):
        connector.collect(ctx)


def test_tdc_connector_document_no_incomplete_crawl_fails_closed(tmp_path: Path):
    """运行期抓取不完整：fail-closed 报错，绝不把部分行当完整结果收窄。"""

    class IncompleteTDC(FakeTDC):
        def crawl_data_model_all(self, filters, max_records):
            return SimpleNamespace(
                rows=[{"incident": "900001", "documentNo": "3D-00001018"}],
                complete=False, stop_reason="max_pages",
            )

    archive = ArchiveStore({"default": tmp_path}, reserve_bytes=0)
    connector = TDCProjectStatusConnector(
        MemoryCredentialProvider({"ref": ("user", "pass")}), archive,
        auth_factory=FakeAuth, crawler_factory=IncompleteTDC,
    )
    ctx = SyncBindingContext(
        binding_id=22, deliverable_id="VPI-T2-D5", phase_id="VPI-T2",
        source_type="tdc", external_key="900001",
        match_rule={"reportType": "data_model", "documentNo": "3D-00001018"},
        mapping={"owner": "currentApprover"}, cursor={},
        expected_deliverable_updated_at="v1", run_id=23, credential_ref="ref",
    )
    with pytest.raises(ValueError, match="incomplete"):
        connector.collect(ctx)


def test_tdc_connector_collect_tolerates_archive_export_failure(tmp_path: Path):
    class ExportFailingTDC(FakeTDC):
        def export_data_model(self, filters):
            raise RuntimeError("TDC 导出服务瞬时不可用 (503)")

    archive = ArchiveStore({"default": tmp_path}, reserve_bytes=0)
    connector = TDCProjectStatusConnector(
        MemoryCredentialProvider({"ref": ("user", "pass")}), archive,
        auth_factory=FakeAuth, crawler_factory=ExportFailingTDC,
    )
    snapshot = connector.collect(context())
    assert snapshot.match_state == "matched"
    assert snapshot.candidates[0].field_values == {"owner": "审批人"}
    # 归档导出虽然失败，但快照数据（CSV、JSON）依然完整落盘
    assert {item["artifact_type"] for item in snapshot.artifacts} == {"csv", "json"}
    assert all((tmp_path / item["relative_path"]).is_file() for item in snapshot.artifacts)


def test_tdc_sor_collect_flattens_application_rows_and_keeps_raw_json(tmp_path: Path):
    """SOR 同步链路的行形状边界（2026-09-26 生产缺陷）。

    analysis_rows 与 CSV 用规范化行（嵌套对象取标量文本，审批状态只取 name），
    归档 JSON 保留原始行作原始取证；原始输入行不得被原地改写。
    """
    import json as json_module

    raw_rows = [
        {
            "processNo": "SOR202609090006",
            "carTypeProject": {
                "id": "67440f9e", "projectNo": "F610S", "projectName": "F610S",
                "sorEnabled": True,
            },
            "sorNo": "SGMW-F610S-SOR0153",
            "deptName": "车体工程",
            "sectionName": "外饰科",
            "processInstanceStatus": {"value": 4, "name": "已完成", "valueStr": "4"},
            "currentAssigneeNameList": [{"name": "张三"}, {"name": "李四"}],
        },
        {
            "processNo": "SOR-NOSTATUS",
            "processInstanceStatus": {"value": 2, "valueStr": "2"},
        },
    ]

    class SorTDC(FakeTDC):
        def crawl_sor_all(self, filters, max_records):
            return SimpleNamespace(rows=raw_rows, complete=True, stop_reason="reported_pages")

        def export_sor(self, filters):
            path = self.output_dir / "official-sor.xlsx"
            path.write_bytes(b"PK\x03\x04fake")
            return SimpleNamespace(path=path, file_name="official-sor.xlsx", byte_count=8)

    archive = ArchiveStore({"default": tmp_path}, reserve_bytes=0)
    connector = TDCProjectStatusConnector(
        MemoryCredentialProvider({"ref": ("user", "pass")}), archive,
        auth_factory=FakeAuth, crawler_factory=SorTDC,
    )
    ctx = SyncBindingContext(
        binding_id=9, deliverable_id="VPI-T2-D2", phase_id="VPI-T2",
        source_type="tdc", external_key="SOR202609090006",
        match_rule={"reportType": "sor"},
        mapping={"owner": "currentAssigneeNameList"}, cursor={},
        expected_deliverable_updated_at="v1", run_id=11, credential_ref="ref",
    )
    snapshot = connector.collect(ctx)

    # 应用行（analysis_rows）：嵌套对象 → 标量文本；状态只取 name。
    assert snapshot.analysis_rows[0]["carTypeProject"] == "F610S"
    assert snapshot.analysis_rows[0]["processInstanceStatus"] == "已完成"
    assert snapshot.analysis_rows[0]["currentAssigneeNameList"] == "张三、李四"
    # name 缺失时留空，不得用 valueStr/value 推断完成语义。
    assert snapshot.analysis_rows[1]["processInstanceStatus"] is None
    # 原始输入行未被原地改写。
    assert isinstance(raw_rows[0]["carTypeProject"], dict)
    assert isinstance(raw_rows[0]["processInstanceStatus"], dict)

    by_type = {item["artifact_type"]: item for item in snapshot.artifacts}
    csv_text = (tmp_path / by_type["csv"]["relative_path"]).read_text(encoding="utf-8-sig")
    assert "F610S" in csv_text and "已完成" in csv_text
    assert "'projectNo'" not in csv_text
    json_payload = json_module.loads(
        (tmp_path / by_type["json"]["relative_path"]).read_text(encoding="utf-8")
    )
    # 归档 JSON 保留原始行（嵌套结构 = 原始取证职责）。
    assert isinstance(json_payload[0]["carTypeProject"], dict)
    assert json_payload[0]["processInstanceStatus"]["name"] == "已完成"


def test_tdc_sor_collect_produces_f6c_aggregated_analysis_rows(tmp_path: Path):
    """验证 collect 产出的 analysis_rows 正确包含 F6c 零件聚合与 startUser 解包字段。"""
    raw_packet = [
        {
            "processNo": "SOR202609280008",
            "sorNo": "SGMW-E262S-SOR0002",
            "version": "A",
            "title": "上安装板装饰盖",
            "startTime": "2026-09-28 10:00:00",
            "carTypeProject": {"projectNo": "E262S", "projectName": "E262S"},
            "processInstanceStatus": {"value": 2, "name": "审批中"},
            "sorPartList": [
                {"partNo": "27246864", "partName": "上安装板装饰组件"},
                {"partNo": "27246868", "partName": "上安装板左装饰盖"},
            ],
            "sorPartNo": None,
            "sorProcessStatus": "三审通过",
            "startUser": {
                "trueName": "韦大方",
                "deptInfo": {
                    "name": "外饰科",
                    "parentDept": {"name": "车体工程"},
                },
            },
        }
    ]

    class RealSorTDC(FakeTDC):
        def crawl_sor_all(self, filters, max_records):
            return SimpleNamespace(rows=raw_packet, complete=True, stop_reason="reported_pages")

        def export_sor(self, filters):
            path = self.output_dir / "official-sor.xlsx"
            path.write_bytes(b"PK\x03\x04fake")
            return SimpleNamespace(path=path, file_name="official-sor.xlsx", byte_count=8)

    archive = ArchiveStore({"default": tmp_path}, reserve_bytes=0)
    connector = TDCProjectStatusConnector(
        MemoryCredentialProvider({"ref": ("user", "pass")}), archive,
        auth_factory=FakeAuth, crawler_factory=RealSorTDC,
    )
    ctx = SyncBindingContext(
        binding_id=10, deliverable_id="VPI-T2-D2", phase_id="VPI-T2",
        source_type="tdc", external_key="SOR202609280008",
        match_rule={"reportType": "sor"},
        mapping={"owner": "startUser"}, cursor={},
        expected_deliverable_updated_at="v1", run_id=12, credential_ref="ref",
    )
    snapshot = connector.collect(ctx)
    row = snapshot.analysis_rows[0]
    assert row["sorPartNo"] == "27246864、27246868"
    assert row["sorPartName"] == "上安装板装饰组件、上安装板左装饰盖"
    assert row["startUser"] == "韦大方"
    assert row["sectionName"] == "外饰科"
    assert row["deptName"] == "车体工程"
    assert row["latestCompletedNode"] == "三审通过"
    # mapping owner 命中 startUser
    assert snapshot.candidates[0].field_values == {"owner": "韦大方"}


def test_tdc_zero_match_needs_attention_without_guess(tmp_path: Path):
    class EmptyTDC(FakeTDC):
        def crawl_data_model_all(self, filters, max_records):
            return SimpleNamespace(rows=[], complete=True, stop_reason="empty_page")

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


def test_wrapped_native_winhttp_failure_is_retried_twice():
    calls = []

    class Failing:
        def collect(self, value):
            calls.append(value)
            try:
                raise WinHTTPError("native transport failure")
            except WinHTTPError as cause:
                raise TDCCrawlerError("TDC request failed") from cause

    connector = RetryingConnector(Failing(), sleeper=lambda delay: None)
    with pytest.raises(TDCCrawlerError):
        connector.collect(context())
    assert len(calls) == 2


def test_aras_rejects_unapproved_report_before_auth(tmp_path: Path):
    connector = ArasProjectStatusConnector(
        MemoryCredentialProvider({"ref": ("user", "pass")}),
        ArchiveStore({"default": tmp_path}, reserve_bytes=0),
        auth_factory=FakeAuth,
    )
    value = context("aras")
    value = SyncBindingContext(**{**value.__dict__, "match_rule": {"reportType": "unapproved"}})
    with pytest.raises(ValueError, match="does not support"):
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
            return SimpleNamespace(
                rows=[{"_no": "EWO-1", "_rsp_name": "负责人"}],
                complete=True,
                stop_reason="short_page",
            )

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
    assert calls["max_records"] == 5000
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
                complete=True,
                stop_reason="short_page",
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
            return SimpleNamespace(
                rows=[{"_no": "EWO-049039"}],
                page=1,
                item_ids=["ID-1"],
                complete=True,
                stop_reason="short_page",
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


def test_aras_connector_passes_all_non_model_ewo_filters(tmp_path: Path):
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

        def crawl_ewo_report_all(self, filters, max_records):
            captured["filters"] = filters
            captured["max_records"] = max_records
            return SimpleNamespace(
                rows=[{"_no": "EWO-1"}], complete=True, stop_reason="short_page"
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
        binding_id=6, deliverable_id="VPI-T2-D3", phase_id="VPI-T2", source_type="aras",
        external_key="EWO-1",
        match_rule={
            "reportType": "ewo", "ewoNo": "EWO-1", "projectCode": "P100",
            "subjectKeyword": "door", "changeType": "Type-A", "changeSubType": "Sub-A",
            "area": "Body", "state": "In Work", "rspDepartment": "Dept",
            "rspSmt": "SMT", "submitStart": "2026-01-01", "submitEnd": "2026-01-31",
        },
        mapping={}, cursor={}, expected_deliverable_updated_at="v1", run_id=13,
        credential_ref="domain",
    )

    snapshot = connector.collect(ctx)

    filters = captured["filters"]
    assert filters.ewo_no == "EWO-1"
    assert filters.project_code == "P100"
    assert filters.subject_keyword == "door"
    assert filters.change_type == "Type-A"
    assert filters.change_sub_type == "Sub-A"
    assert filters.area == "Body"
    assert filters.state == "In Work"
    assert filters.rsp_department == "Dept"
    assert filters.rsp_smt == "SMT"
    assert filters.submit_start == "2026-01-01"
    assert filters.submit_end == "2026-01-31"
    assert captured["max_records"] == 5000
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
                complete=True,
                stop_reason="short_page",
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
        external_key="EWO-1", match_rule={
            "reportType": "ewo", "modelInfo": "F610S", "subjectKeyword": "ONLY-THIS"
        },
        mapping={}, cursor={}, expected_deliverable_updated_at="v1", run_id=11,
        credential_ref="domain",
    )
    snapshot = connector.collect(ctx)
    filters = captured["filters"]
    assert filters.rsp_department == "|".join(f"*{kw}*" for kw in EWO_DEPARTMENT_KEYWORDS)
    assert filters.rsp_smt is None
    # context.match_rule 里已有 modelInfo，车型查询条件不受默认范围调整影响。
    assert filters.model_info == "F610S"
    assert filters.subject_keyword == "ONLY-THIS"
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


def test_tdc_sor_filters_maps_car_type_project_id() -> None:
    rule = {
        "processNo": "PROC-1",
        "carTypeProject": "P100",
        "carTypeProjectId": "proj-id-1",
        "applicant": "Alice",
        "title": "Title",
        "partNumber": "PART-1",
        "sorNumber": "SOR-1",
        "approvalStatus": "Approved",
    }
    filters = TDCProjectStatusConnector._sor_filters(rule)
    assert filters.serial_number == "PROC-1"
    assert filters.car_type_project == "P100"
    assert filters.car_type_project_id == "proj-id-1"
    assert filters.applicant == "Alice"
    assert filters.title == "Title"
    assert filters.part_number == "PART-1"
    assert filters.sor_number == "SOR-1"
    assert filters.approval_status == "Approved"


def _aggregate_context(**match_rule_overrides):
    from services.project_status_sync_runner import SyncBindingContext

    match_rule = {"reportType": "data_model", "aggregate": True, "carTypeProjectId": "F610S"}
    match_rule.update(match_rule_overrides)
    return SyncBindingContext(
        binding_id=3, deliverable_id="VPI-T2-D5", phase_id="VPI-T2",
        source_type="tdc", external_key=None, match_rule=match_rule,
        mapping={
            "owner": "currentApprover",
            "note": ["latest_completed_node", "approval_status"],
        },
        cursor={}, expected_deliverable_updated_at="v1", run_id=9,
        credential_ref="domain",
    )


def test_aggregate_snapshot_single_record_writes_all_mapped_fields():
    """聚合单条记录：按映射直写 owner/note 多列合并。"""
    from services.project_status_connectors import _snapshot

    rows = [
        {"incident": "F610S-3D-0001", "currentApprover": "张三",
         "latest_completed_node": "IMPL", "approval_status": "审批中"},
    ]
    snapshot = _snapshot(_aggregate_context(), rows, [])
    assert snapshot.match_state == "matched"
    assert snapshot.candidates[0].field_values == {
        "owner": "张三", "note": "IMPL｜审批中",
    }


def test_aggregate_snapshot_multi_record_hides_single_value_fields():
    """聚合多条记录：负责人/计划完成日期不写（多记录写单值必然出错），
    风险备注逐条聚合（标识：卡点信息）。"""
    from services.project_status_connectors import _snapshot

    rows = [
        {"incident": "F610S-3D-0001", "currentApprover": "张三",
         "latest_completed_node": "IMPL", "approval_status": "审批中"},
        {"incident": "F610S-3D-0002", "currentApprover": "李四",
         "latest_completed_node": "PROC", "approval_status": "审批中"},
    ]
    snapshot = _snapshot(_aggregate_context(), rows, [])
    assert snapshot.match_state == "matched"
    values = snapshot.candidates[0].field_values
    assert "owner" not in values
    assert values["note"] == "F610S-3D-0001：IMPL｜审批中；F610S-3D-0002：PROC｜审批中"


def test_aggregate_snapshot_content_change_changes_version():
    """GPT 终审 P1 回归：同单号记录的内容变化必须产生新版本
    （旧实现仅用单号构造版本，会把内容变化误判为幂等 skipped）。"""
    from services.project_status_connectors import _snapshot

    rows_v1 = [
        {"incident": "F610S-3D-0001", "currentApprover": "张三",
         "latest_completed_node": "IMPL", "approval_status": "审批中"},
    ]
    rows_v2 = [
        {"incident": "F610S-3D-0001", "currentApprover": "张三",
         "latest_completed_node": "IMPL", "approval_status": "已驳回"},
    ]
    v1 = _snapshot(_aggregate_context(), rows_v1, []).external_version
    v2 = _snapshot(_aggregate_context(), rows_v2, []).external_version
    assert v1 != v2


def test_aggregate_snapshot_excludes_unnumbered_rows_consistently():
    """GPT 终审 P1 回归：无单号行不计入聚合（与 discovery 口径一致），
    全部无单号 → not_found（不得 matched）。"""
    from services.project_status_connectors import _snapshot

    ctx = _aggregate_context()
    only_unnumbered = [{"currentApprover": "张三", "approval_status": "审批中"}]
    snapshot = _snapshot(ctx, only_unnumbered, [])
    assert snapshot.match_state == "not_found"

    mixed = [
        {"incident": "F610S-3D-0001", "currentApprover": "张三",
         "latest_completed_node": "IMPL", "approval_status": "审批中"},
        {"currentApprover": "李四", "approval_status": "审批中"},
    ]
    snapshot = _snapshot(ctx, mixed, [])
    assert snapshot.match_state == "matched"
    # 无单号行不进入风险备注聚合。
    assert "李四" not in snapshot.candidates[0].field_values["note"]


def test_aggregate_flag_requires_strict_boolean():
    """GPT 终审 P2 回归：聚合标记必须严格布尔，字符串 "false" 不得触发聚合。"""
    from services.project_status_connectors import _snapshot

    ctx = _aggregate_context(aggregate="false")
    rows = [
        {"incident": "F610S-3D-0001", "currentApprover": "张三",
         "latest_completed_node": "IMPL", "approval_status": "审批中"},
        {"incident": "F610S-3D-0002", "currentApprover": "李四",
         "latest_completed_node": "PROC", "approval_status": "审批中"},
    ]
    # 非严格布尔时会走聚合分支并隐藏单值字段；严格布尔后按单记录匹配
    # （external_key=None → not_found），证明字符串 "false" 未触发聚合。
    snapshot = _snapshot(ctx, rows, [])
    assert snapshot.match_state == "not_found"
    assert snapshot.candidates == ()


def test_paa_report_page_has_complete_and_stop_reason():
    """PAAReportPage 必须具备 complete、stop_reason 与 fetched_pages，供 _require_complete_result 判定。"""
    from services.aras_crawler import PAAReportPage
    from services.project_status_connectors import _require_complete_result

    # 默认值
    page = PAAReportPage(rows=[{"_no": "PAA-001"}], page=1, item_ids=["item-1"], raw_xml="<xml/>")
    assert page.fetched_pages == 1
    assert page.stop_reason == "single_page"
    assert page.complete is False
    assert page.truncated is False

    # crawl 完成态结果通过 _require_complete_result 校验
    completed_page = PAAReportPage(
        rows=[{"_no": "PAA-001"}],
        page=1,
        item_ids=["item-1"],
        raw_xml="<xml/>",
        fetched_pages=1,
        stop_reason="short_page",
        complete=True,
    )
    _require_complete_result(completed_page)


def test_ncr_filters_never_sends_department_as_section_code():
    """_ncr_filters 只接受白名单科室代码；绑定部门绝不进入 seccode。

    生产实锤（2026-09-26）：部门名兜底进 seccode 会让 NCR 服务端导出方法
    生成不了文件（NCR 域只有科室、没有部门），清空部门即恢复正常。
    科室代码走白名单解析器（大小写不敏感、规范化为大写；空 = 不限科室）。
    """
    rule_with_dept = {"projectModel": "F610S", "department": "技术中心_车体工程"}
    filters = ArasProjectStatusConnector._ncr_filters(rule_with_dept)
    assert filters.section_code is None
    assert filters.section_codes == ()
    assert filters.project_names == ["F610S"]

    rule_with_sec = {"projectModel": "F610S", "sectionCode": "be, INT", "department": "技术中心_车体工程"}
    filters2 = ArasProjectStatusConnector._ncr_filters(rule_with_sec)
    assert filters2.section_code is None
    assert filters2.section_codes == ("BE", "INT")

    with pytest.raises(ValueError, match="合法代码"):
        ArasProjectStatusConnector._ncr_filters(
            {"projectModel": "F610S", "sectionCode": "结构工程科"}
        )


def test_ncr_collect_rows_fails_closed_when_workbook_admission_fails(
    monkeypatch, tmp_path
) -> None:
    """同步路径：工作簿准入不通过（如簿记不平）必须整体失败，不得写部分数据。"""
    import services.aras_ncr_workbook as workbook

    def fake_parse(path, report_type):
        return NcrWorkbookOutcome(
            report_type=report_type,
            rows=(
                NcrWorkbookRow(
                    values=(),
                    labels={"NCR编号": "NCR-1"},
                    sheet_name="Sheet1",
                ),
            ),
            bookkeeping=WorkbookBookkeeping(
                read_rows=5, parsed_rows=1, header_rows=3
            ),
            projection_error=None,
            stop_reason="workbook_accounting_mismatch",
        )

    monkeypatch.setattr(workbook, "parse_ncr_workbook", fake_parse)

    dummy_file = tmp_path / "ncr.xlsx"
    dummy_file.write_bytes(b"PK")

    class FakeCrawler:
        def query_ncr_approval_progress(self, filters):
            return SimpleNamespace(file_id="F1", file_name="f.xlsx")

        def download_ncr_progress_file(self, export, target_dir):
            return dummy_file

    with pytest.raises(NcrWorkbookError, match="workbook_accounting_mismatch"):
        ArasProjectStatusConnector._collect_ncr_rows(
            FakeCrawler(), "ncr_progress", {"projectModel": "F610S"}
        )


def test_ncr_collect_rows_ignores_binding_department_keeps_section_code_narrowing(
    monkeypatch, tmp_path
):
    """绑定部门不参与 NCR 内存收窄（生产实锤：报表无部门维度，部门收窄只会整单清空）；
    真实科室代码（sectionCode，白名单解析）仍会收窄并经诊断渠道披露丢弃数。

    行形状为「按已批准表头标签命名」的字典：与归档路径同形，
    收窄读取命名行的 区域/采购科室 等标签（带前缀值包含代码即命中）。
    """
    sections = ["BE 结构工程科", "BI 车体科", "BE", "底盘工程科", "", "INT 内饰科"]
    parsed_rows = tuple(
        NcrWorkbookRow(
            values=(),
            labels={"NCR编号": f"NCR-00{index}", "区域": section},
            sheet_name="Sheet1",
        )
        for index, section in enumerate(sections, start=1)
    )

    import services.aras_ncr_workbook as workbook

    def fake_parse(path, report_type):
        assert report_type == "ncr_progress"
        return NcrWorkbookOutcome(
            report_type=report_type,
            rows=parsed_rows,
            bookkeeping=WorkbookBookkeeping(
                read_rows=len(parsed_rows), parsed_rows=len(parsed_rows)
            ),
            projection_error=None,
            stop_reason="workbook_rows",
        )

    monkeypatch.setattr(workbook, "parse_ncr_workbook", fake_parse)

    dummy_file = tmp_path / "ncr.xlsx"
    dummy_file.write_bytes(b"PK")

    class FakeCrawler:
        def query_ncr_approval_progress(self, filters):
            return SimpleNamespace(file_id="F1", file_name="f.xlsx")

        def download_ncr_progress_file(self, export, target_dir):
            return dummy_file

    crawler = FakeCrawler()
    events: list[tuple[str, object, str]] = []
    monkeypatch.setattr(
        "services.project_status_connectors.emit",
        lambda kind, data=None, *, name="", exception=None: events.append(
            (kind, data, name)
        ),
    )

    # 部门绑定：不再收窄，全部行保留、无丢弃事件（与用户验证通过的空部门形态一致）。
    rows = ArasProjectStatusConnector._collect_ncr_rows(
        crawler, "ncr_progress", {"projectModel": "F610S", "department": "技术中心_车体工程"}
    )
    assert len(rows) == 6
    assert events == []
    # 写入侧形状：命名行必须同时携带契约顺序的位置视图（重复表头标签时是权威值来源）。
    assert all(isinstance(row["values"], list) for row in rows)
    assert all("NCR编号" in row for row in rows)

    # 白名单科室代码（BE）：仍收窄并披露丢弃数（区域值含代码即命中）。
    rows_sec = ArasProjectStatusConnector._collect_ncr_rows(
        crawler, "ncr_progress", {"projectModel": "F610S", "sectionCode": "BE"}
    )
    assert len(rows_sec) == 2
    assert [event[0] for event in events] == ["ncr_department_filter"]
    assert events[0][1] == {"kept_count": 2, "dropped_count": 4}
    assert "NCR-001" in [r["NCR编号"] for r in rows_sec]
    assert "NCR-003" in [r["NCR编号"] for r in rows_sec]
    assert "NCR-002" not in [r["NCR编号"] for r in rows_sec]

    # 非白名单科室代码：fail-closed（与保存/探测共用同一解析器）。
    with pytest.raises(ValueError, match="合法代码"):
        ArasProjectStatusConnector._collect_ncr_rows(
            crawler, "ncr_progress", {"projectModel": "F610S", "sectionCode": "结构工程科"}
        )

    # 丢弃行数必须可核对（该过滤发生在工作簿准入门之后，准入簿记覆盖不到它）。
    from services.project_status_connectors import _filter_ncr_rows_by_department

    kept, dropped = _filter_ncr_rows_by_department(
        [row.named_row() for row in parsed_rows], "BE"
    )
    assert len(kept) == 2 and dropped == 4
    all_rows, no_drop = _filter_ncr_rows_by_department(
        [row.named_row() for row in parsed_rows], None
    )
    assert len(all_rows) == 6 and no_drop == 0


def test_exclude_tdc_scope_rows_drops_proven_text_statuses() -> None:
    """R7-G2：SOR 按候选键序（processInstanceStatus/approvalStatus/审批状态）
    取首个非空状态值，归一后已废弃/已撤回剔除（含未扁平化嵌套对象防御分支）。"""
    rows = [
        {"processInstanceStatus": "已完成"},
        {"processInstanceStatus": "已废弃"},
        {"processInstanceStatus": "已撤回"},
        {"processInstanceStatus": "审批中"},
        {"processInstanceStatus": {"name": "已撤回", "value": 6}},  # 未扁平化的防御分支
        {"approvalStatus": "已撤回"},  # 候选键回退（历史/异构行形状）
    ]
    kept, dropped = _exclude_tdc_scope_rows("sor", rows)
    assert dropped == 4
    assert [row["processInstanceStatus"] for row in kept] == ["已完成", "审批中"]


def test_exclude_tdc_scope_rows_keeps_data_model_numeric_codes() -> None:
    """R7-G2 现状钉住：数模数字码不剔除——"2"/"4" 归一为审批中/已完成，
    "3"/"6" 未映射透传；映射升级（B 案）裁决前不得误剔。"""
    rows = [{"status": code} for code in ("2", "4", "3", "6")]
    kept, dropped = _exclude_tdc_scope_rows("data_model", rows)
    assert dropped == 0
    assert len(kept) == 4
    # 归档官方工作簿文本列（"状态"）按同一剔除集生效；文本 "2" 同样不剔。
    kept_text, dropped_text = _exclude_tdc_scope_rows(
        "data_model", [{"状态": "已废弃"}, {"状态": "审批中"}, {"状态": "2"}]
    )
    assert dropped_text == 1
    assert [row["状态"] for row in kept_text] == ["审批中", "2"]


def test_exclude_tdc_scope_rows_ignores_other_reports() -> None:
    rows = [{"status": "已废弃"}]
    kept, dropped = _exclude_tdc_scope_rows("ewo", rows)
    assert dropped == 0
    assert len(kept) == 1


def test_status_distribution_counts_pre_exclusion_and_flags_unknown_codes(tmp_path):
    """F4（顾问终审）：直方图采集点在范围剔除之前，且未知码触发监测事件。

    数模 3/6 映射升级后这些行会被剔除——若在剔除后才统计，直方图将永远
    看不到它们的分布。本测试锁定：对包含"会被剔除的文本行"的原始行集，
    直方图仍按原始行计数；已知码之外的码触发 tdc_status_unknown_codes。
    """
    from core.diagnostic_recording import Recorder, recording_scope
    from services.project_status_connectors import _emit_tdc_status_distribution

    rows = [
        {"status": "2"},
        {"status": "4"},
        {"status": "已废弃"},  # 文本行（会被剔除口径排除），直方图仍计数
        {"status": "7"},       # 未知码 → 监测事件
    ]
    recorder = Recorder(tmp_path)
    identity = recorder.start()["id"]
    with recording_scope(recorder):
        _emit_tdc_status_distribution(rows)
    import json as _json
    import zipfile as _zipfile
    import io as _io
    with _zipfile.ZipFile(_io.BytesIO(recorder.export(identity))) as bundle:
        events = [
            _json.loads(line)
            for line in bundle.read("events.jsonl").splitlines()
        ]
    dist = {
        event["data"].get("tdc_status_code"): event["data"].get("status_count")
        for event in events
        if event["kind"] == "tdc_status_distribution"
    }
    # 已知数字码直读；「已废弃」文本不在闭集词表内被指纹化（计数仍可读）。
    assert dist["2"] == 1 and dist["4"] == 1 and dist["7"] == 1
    assert len(dist) == 4 and sum(dist.values()) == 4
    unknown = [e["data"] for e in events if e["kind"] == "tdc_status_unknown_codes"]
    assert len(unknown) == 1 and unknown[0]["unknown_count"] == 1


def test_tdc_sor_collect_excludes_scope_rows_and_keeps_raw_json(tmp_path: Path):
    """R7-G2：SOR 同步剔除已废弃/已撤回行——应用行/CSV 用保留集，归档 JSON
    仍为未剔除的原始行；tdc_scope_exclusion 事件经 safe_metadata 投影可读。"""
    import io as _io
    import json as json_module
    import zipfile as _zipfile

    from core.diagnostic_recording import Recorder, recording_scope

    raw_rows = [
        {
            "processNo": "SOR-KEEP-1",
            "processInstanceStatus": {"value": 4, "name": "已完成", "valueStr": "4"},
        },
        {
            "processNo": "SOR-KEEP-2",
            "processInstanceStatus": {"value": 2, "name": "审批中", "valueStr": "2"},
        },
        {
            "processNo": "SOR-DROP-1",
            "processInstanceStatus": {"value": 3, "name": "已废弃", "valueStr": "3"},
        },
        {
            "processNo": "SOR-DROP-2",
            "processInstanceStatus": {"value": 6, "name": "已撤回", "valueStr": "6"},
        },
    ]

    class SorTDC(FakeTDC):
        def crawl_sor_all(self, filters, max_records):
            return SimpleNamespace(rows=raw_rows, complete=True, stop_reason="reported_pages")

        def export_sor(self, filters):
            path = self.output_dir / "official-sor.xlsx"
            path.write_bytes(b"PK\x03\x04fake")
            return SimpleNamespace(path=path, file_name="official-sor.xlsx", byte_count=8)

    archive = ArchiveStore({"default": tmp_path}, reserve_bytes=0)
    connector = TDCProjectStatusConnector(
        MemoryCredentialProvider({"ref": ("user", "pass")}), archive,
        auth_factory=FakeAuth, crawler_factory=SorTDC,
    )
    ctx = SyncBindingContext(
        binding_id=15, deliverable_id="VPI-T2-D2", phase_id="VPI-T2",
        source_type="tdc", external_key="SOR-KEEP-1",
        match_rule={"reportType": "sor"},
        mapping={"owner": "processNo"}, cursor={},
        expected_deliverable_updated_at="v1", run_id=15, credential_ref="ref",
    )
    recorder = Recorder(tmp_path / "diag")
    identity = recorder.start()["id"]
    with recording_scope(recorder):
        snapshot = connector.collect(ctx)

    # 应用行/快照只含保留行；绑定匹配在保留行上成立。
    assert [row["processNo"] for row in snapshot.analysis_rows] == ["SOR-KEEP-1", "SOR-KEEP-2"]
    assert snapshot.match_state == "matched"
    assert snapshot.candidates[0].external_key == "SOR-KEEP-1"

    by_type = {item["artifact_type"]: item for item in snapshot.artifacts}
    csv_text = (tmp_path / by_type["csv"]["relative_path"]).read_text(encoding="utf-8-sig")
    assert "SOR-KEEP-1" in csv_text and "SOR-DROP-1" not in csv_text
    json_payload = json_module.loads(
        (tmp_path / by_type["json"]["relative_path"]).read_text(encoding="utf-8")
    )
    # 归档 JSON 仍为未剔除的原始行（原始取证职责不变）。
    assert sorted(row["processNo"] for row in json_payload) == [
        "SOR-DROP-1", "SOR-DROP-2", "SOR-KEEP-1", "SOR-KEEP-2",
    ]

    # 事件经 safe_metadata 投影后 data 可读（键在白名单、值在闭集词表）。
    with _zipfile.ZipFile(_io.BytesIO(recorder.export(identity))) as bundle:
        events = [
            json_module.loads(line)
            for line in bundle.read("events.jsonl").splitlines()
        ]
    exclusion = [event["data"] for event in events if event["kind"] == "tdc_scope_exclusion"]
    assert len(exclusion) == 1
    assert exclusion[0] == {"report_type": "sor", "kept_count": 2, "dropped_count": 2}


def test_aras_paa_collect_excludes_cancel_rows_and_keeps_raw_json(tmp_path: Path):
    """R7-G2：PAA 同步剔除 CANCEL 行（trim+upper 变体一律命中）——CSV/快照用
    保留集，归档 JSON 仍为原始行；aras_scope_exclusion 事件投影可读。"""
    import io as _io
    import json as json_module
    import zipfile as _zipfile

    from core.diagnostic_recording import Recorder, recording_scope

    raw_rows = [
        {"_no": "PAA-DROP-1", "state": "CANCEL"},
        {"_no": "PAA-DROP-2", "state": "cancel "},
        {"_no": "PAA-DROP-3", "current_state__name": " Cancel "},
        {"_no": "PAA-KEEP-1", "state": "DRAFT1"},
        {"_no": "PAA-KEEP-2", "state": "CLOSE"},
        {"_no": "PAA-KEEP-3", "state": None},
    ]

    class PaaAras:
        def __init__(self, *args, **kwargs):
            pass

        def crawl_paa_report_all(self, filters, max_records):
            return SimpleNamespace(
                rows=raw_rows, complete=True, stop_reason="short_page"
            )

    archive = ArchiveStore({"default": tmp_path}, reserve_bytes=0)
    connector = ArasProjectStatusConnector(
        MemoryCredentialProvider({"ref": ("user", "pass")}), archive,
        auth_factory=FakeAuth, crawler_factory=PaaAras,
    )
    ctx = SyncBindingContext(
        binding_id=16, deliverable_id="VPI-T2-D6", phase_id="VPI-T2",
        source_type="aras", external_key="PAA-KEEP-1",
        match_rule={"reportType": "paa"},
        mapping={"owner": "_no"}, cursor={},
        expected_deliverable_updated_at="v1", run_id=16, credential_ref="ref",
    )
    recorder = Recorder(tmp_path / "diag")
    identity = recorder.start()["id"]
    with recording_scope(recorder):
        snapshot = connector.collect(ctx)

    # 应用行/快照只含保留行（空状态行不误剔）。
    assert [row["_no"] for row in snapshot.analysis_rows] == [
        "PAA-KEEP-1", "PAA-KEEP-2", "PAA-KEEP-3",
    ]
    assert snapshot.match_state == "matched"
    assert snapshot.candidates[0].external_key == "PAA-KEEP-1"
    assert snapshot.candidates[0].field_values == {"owner": "PAA-KEEP-1"}

    by_type = {item["artifact_type"]: item for item in snapshot.artifacts}
    csv_text = (tmp_path / by_type["csv"]["relative_path"]).read_text(encoding="utf-8-sig")
    assert "PAA-KEEP-1" in csv_text and "PAA-DROP-1" not in csv_text
    json_payload = json_module.loads(
        (tmp_path / by_type["json"]["relative_path"]).read_text(encoding="utf-8")
    )
    # 归档 JSON 仍为未剔除的原始行（镜像 TDC 契约）。
    assert len(json_payload) == 6
    assert any(row["_no"] == "PAA-DROP-1" for row in json_payload)

    # 事件经 safe_metadata 投影后 data 可读。
    with _zipfile.ZipFile(_io.BytesIO(recorder.export(identity))) as bundle:
        events = [
            json_module.loads(line)
            for line in bundle.read("events.jsonl").splitlines()
        ]
    exclusion = [event["data"] for event in events if event["kind"] == "aras_scope_exclusion"]
    assert len(exclusion) == 1
    assert exclusion[0] == {"report_type": "paa", "kept_count": 3, "dropped_count": 3}
