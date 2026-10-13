# -*- coding: utf-8 -*-
"""数模身份键契约回归（2026-10-10 生产事故）。

事故：上游列表行新增身份字段（formId）后，向导用命中行的 incident 当选中键，
而候选过滤用 record_identity（formId 优先）→ 命中行被过滤掉 → 「未匹配（命中 0 行，
字段数 60）」。修复：身份字段顺序按报表类型解析，数模一律以第 0 列实例号 incident
为权威 externalKey，发现端/连接器/聚合三条路径同源。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.db_manager import DatabaseManager
from services.data_model_watchlist import WatchlistError, normalize_single_serial
from services.project_status_connectors import _snapshot
from services.project_status_discovery import MappingDiscoveryService
from services.project_status_records import (
    IDENTITY_FIELDS,
    identified_records,
    identity_field_name,
    identity_fields,
    record_identity,
)
from services.project_status_sync_runner import SyncBindingContext


# ── 1. 身份字段顺序 ────────────────────────────────────────────────────────────

def test_data_model_identity_prefers_incident_over_form_id() -> None:
    row = {"formId": "FORM-9", "incident": "50667733", "documentNo": "3D-00001018"}

    assert record_identity(row, report_type="data_model") == "50667733"
    assert identity_field_name(row, report_type="data_model") == "incident"
    # 未指定报表类型的调用点行为逐字不变（formId 仍然优先）。
    assert record_identity(row) == "FORM-9"


def test_identity_order_only_overrides_known_report_types() -> None:
    assert identity_fields("data_model")[0] == "incident"
    assert set(identity_fields("data_model")) == set(IDENTITY_FIELDS)
    for report in ("sor", "ewo", "paa", "ncr_detail", None, ""):
        assert identity_fields(report) == IDENTITY_FIELDS


def test_data_model_identity_falls_back_when_incident_missing() -> None:
    row = {"formId": "FORM-9", "documentNo": "3D-00001018"}

    assert record_identity(row, report_type="data_model") == "FORM-9"


def test_identified_records_uses_report_type_order() -> None:
    rows = [
        {"formId": "FORM-9", "incident": "A", "documentNo": "3D-1"},
        {"formId": "FORM-8", "incident": "B", "documentNo": "3D-2"},
    ]

    assert [key for key, _ in identified_records(rows, report_type="data_model")] == ["A", "B"]
    assert [key for key, _ in identified_records(rows)] == ["FORM-8", "FORM-9"]


# ── 2. 连接器单记录绑定：externalKey 不被新字段抢走 ────────────────────────────

def _context(external_key: str, report_type: str = "data_model") -> SyncBindingContext:
    return SyncBindingContext(
        binding_id=1,
        deliverable_id="VPI-T2-D5",
        phase_id="VPI-T2",
        source_type="tdc",
        external_key=external_key,
        match_rule={"reportType": report_type, "aggregate": False},
        mapping={"owner": "applicant"},
        cursor={},
        expected_deliverable_updated_at="v1",
        run_id=7,
    )


def test_connector_single_record_matches_incident_when_row_has_form_id() -> None:
    rows = [
        {"formId": "FORM-9", "incident": "FLOW-A", "documentNo": "3D-1", "applicant": "张三"},
        {"formId": "FORM-8", "incident": "FLOW-B", "documentNo": "3D-2", "applicant": "李四"},
    ]

    snapshot = _snapshot(_context("FLOW-A"), rows, [], report="data_model")

    assert snapshot.match_state == "matched"
    assert snapshot.candidates[0].external_key == "FLOW-A"


def test_connector_legacy_identity_order_would_have_missed_the_row() -> None:
    """不带 report 的旧口径（formId 优先）会 not_found —— 证明修复点就是顺序解析。"""
    rows = [{"formId": "FORM-9", "incident": "FLOW-A", "documentNo": "3D-1"}]

    snapshot = _snapshot(_context("FLOW-A"), rows, [], report=None)

    assert snapshot.match_state == "not_found"


# ── 3. 发现端不变量：选中键必须落在候选里 ─────────────────────────────────────

def test_observe_reports_selected_not_in_candidates(tmp_path: Path) -> None:
    db = DatabaseManager(db_path=tmp_path / "identity.db")
    db.init_database()
    service = MappingDiscoveryService(db)
    rows = [{"formId": "FORM-9", "incident": "FLOW-A", "documentNo": "3D-1"}]

    observation = service.observe(
        "VPI-T2-D5", "tdc", rows, "SOMETHING-ELSE",
        aggregate=False, match_rule={"reportType": "data_model", "aggregate": False},
    )

    assert observation["state"] == "not_found"
    assert observation["reason"] == "selected_not_in_candidates"
    assert observation["candidateCount"] == 0


def test_observe_matches_when_selected_is_the_incident(tmp_path: Path) -> None:
    db = DatabaseManager(db_path=tmp_path / "identity.db")
    db.init_database()
    service = MappingDiscoveryService(db)
    rows = [{"formId": "FORM-9", "incident": "FLOW-A", "documentNo": "3D-1"}]

    observation = service.observe(
        "VPI-T2-D5", "tdc", rows, "FLOW-A",
        aggregate=False, match_rule={"reportType": "data_model", "aggregate": False},
    )

    assert observation["state"] == "matched"
    assert observation["externalKey"] == "FLOW-A"
    assert observation["reason"] is None


# ── 4. 单值流水单号校验（写入入口共用） ───────────────────────────────────────

@pytest.mark.parametrize(
    "value",
    [
        "3D-00001018 3D-00001012",
        "3D-00001018,3D-00001012",
        "3D-00001018、3D-00001012",
        "3D-00001018\n3D-00001012",
        "3D-00001018\u200b",
        "３Ｄ-００００１０１８",
        "",
        "   ",
    ],
)
def test_normalize_single_serial_rejects_non_single_values(value: str) -> None:
    with pytest.raises(WatchlistError):
        normalize_single_serial(value)


@pytest.mark.parametrize("value", ["3D-00001018", "F610S-3D-0001", "  3D-00001018  "])
def test_normalize_single_serial_accepts_one_serial(value: str) -> None:
    assert normalize_single_serial(value) == value.strip()


# ── 5. 权威字段：单记录绑定不得回退到候选键（顾问复核 A1） ────────────────────

def test_authoritative_identity_field_is_declared_for_data_model() -> None:
    from services.project_status_records import authoritative_identity_field

    assert authoritative_identity_field("data_model") == "incident"
    assert authoritative_identity_field("sor") is None  # 本批不动 SOR（无证据）
    assert authoritative_identity_field(None) is None


# ── 6. 签名金值：本次改动不得改变 matchRule 的签名字节（顾问复核 A6） ──────────

def test_config_signature_gold_values_are_unchanged() -> None:
    """三个代表规则的签名与修复前 HEAD 逐字一致（修复前用 HEAD 版实现实测比对）。"""
    from services.project_status_records import compute_config_signature

    assert compute_config_signature(
        "tdc", {"reportType": "data_model", "aggregate": False, "documentNo": "3D-00001018"}
    ) == "sig:28bf6d069facde729ee1fe06bf56"
    assert compute_config_signature(
        "tdc", {"reportType": "data_model", "aggregate": False, "incident": "50667733"}
    ) == "sig:92c35790359160494c1d825a13a6"
    assert compute_config_signature(
        "tdc", {"reportType": "data_model", "aggregate": True, "projectModel": "Ar-N"}
    ) == "sig:ecead07fee67cf9b685eaafd6110"


# ── 7. 闭合哨兵：生产调用点必须显式传 report_type（顾问复核 A3） ───────────────

_CALL_PATTERN = re.compile(r"\b_?record_identity\s*\(|\bidentified_records\s*\(")
_IDENTITY_CALL_FILES = (
    "web/app.py",
    "services/project_status_discovery.py",
    "services/project_status_connectors.py",
)


def _call_arguments(source: str, open_paren: int) -> str:
    depth = 0
    for index in range(open_paren, len(source)):
        char = source[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return source[open_paren + 1:index]
    return source[open_paren:]


def test_every_identity_call_site_passes_report_type() -> None:
    """漏改一个调用点就会静默沿用 formId 优先（默认参数保旧行为），必须机械钉住。"""
    root = Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    for relative in _IDENTITY_CALL_FILES:
        source = (root / relative).read_text(encoding="utf-8")
        for match in _CALL_PATTERN.finditer(source):
            arguments = _call_arguments(source, match.end() - 1)
            if "report_type=" not in arguments:
                line = source[: match.start()].count("\n") + 1
                offenders.append(f"{relative}:{line}: {arguments.strip()[:80]}")
    assert offenders == []


# ── 8. 载荷洁净：新键只出现在响应里（顾问复核 A4/A8） ─────────────────────────

def test_observation_payload_keeps_new_keys_out_of_persisted_shapes(tmp_path: Path) -> None:
    import json as _json

    db = DatabaseManager(db_path=tmp_path / "payload.db")
    db.init_database()
    service = MappingDiscoveryService(db)
    rows = [{"formId": "FORM-9", "incident": "FLOW-A", "documentNo": "3D-1", "applicant": "张三"}]

    observation = service.observe(
        "VPI-T2-D5", "tdc", rows, "FLOW-A",
        aggregate=False, match_rule={"reportType": "data_model", "aggregate": False},
    )
    stored = db.list_mapping_observations("VPI-T2-D5", 1)[0]

    assert observation["reason"] is None  # 结果级键
    assert "reason" not in _json.loads(stored["aggregated_candidate_json"] or "{}")
    assert "serialDiagnostic" not in _json.loads(stored["aggregated_candidate_json"] or "{}")
    # 字段报告仍只由行键构成（新键不得污染映射派生）。
    assert _json.loads(stored["field_report_json"])["fields"] == sorted(rows[0].keys())


def test_legacy_form_id_baseline_reports_mismatch_instead_of_matching(tmp_path: Path) -> None:
    """窗口期按 formId 落库的 F10 基线：新口径采样必须判「基线不一致」而不是误判稳定。"""
    import json as _json

    from services.project_status_records import identity_digest

    db = DatabaseManager(db_path=tmp_path / "baseline.db")
    db.init_database()
    service = MappingDiscoveryService(db)
    db.record_mapping_observation(
        "VPI-T2-D5", "tdc", "matched", "FORM-9", "fp-legacy", 1, "[]",
        _json.dumps({"fields": ["formId", "incident", "documentNo"]}),
        config_signature="sig:legacy",
        aggregated_candidate_json=_json.dumps(
            {
                "_schema": 1,
                "_upstreamTotal": 2,
                "_stabilityIds": [identity_digest("FORM-9"), identity_digest("FORM-8")],
            }
        ),
    )

    result = service.observe_stability_sample(
        "VPI-T2-D5",
        "tdc",
        [{"formId": "FORM-9", "incident": "FLOW-A", "documentNo": "3D-1"}],
        2,
        aggregate=False,
        match_rule={"reportType": "data_model", "aggregate": False},
    )

    assert result["state"] == "key_changed"
    assert result["mismatch"]["reason"] == "sample_not_in_baseline"
