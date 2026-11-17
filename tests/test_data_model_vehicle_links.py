# -*- coding: utf-8 -*-
"""D5「车型 ↔ 架构件单」人工声明的离线测试。

口径（用户 2026-10-23 确认，方案 B）：车型合计 = 项目件 + 已确认关联的架构件；
项目件单独数字保留作对照；同一架构单被多车型声明时各车型分别计入，
跨车型合计按单号去重。
"""

from __future__ import annotations

import pytest

from core.db_manager import DatabaseManager
from services import data_model_attribution as attribution
from services import data_model_vehicle_links as links
from services.deliverable_form_analysis import form_definition


# ── 输入解析 ────────────────────────────────────────────────────────────────


def test_normalize_serials_splits_and_dedupes() -> None:
    assert links.normalize_serials("Ar-L-3D-0002, Ar-L-3D-0003\nAr-L-3D-0002") == [
        "Ar-L-3D-0002",
        "Ar-L-3D-0003",
    ]
    assert links.normalize_serials(["a", " a ", "", "b"]) == ["a", "b"]
    assert links.normalize_serials(None) == []


def test_normalize_serials_rejects_overlong_and_overflow() -> None:
    with pytest.raises(links.LinkError):
        links.normalize_serials("x" * 65)
    with pytest.raises(links.LinkError):
        links.normalize_serials([f"S{i}" for i in range(links.MAX_SERIALS_PER_VEHICLE + 1)])


# ── 失配四态 ────────────────────────────────────────────────────────────────


def _row(project_model: str, serial: str, instance: str, status: str = "已完成") -> dict:
    return {
        "instance": instance,
        "serial": serial,
        "status": status,
        "dimensions": {
            **attribution.dimension_fields(project_model),
            "stage": project_model,
            "status": status,
        },
    }


def test_resolve_links_matches_architecture_rows() -> None:
    rows = [_row("Ar-L", "Ar-L-3D-0002", "I1")]
    resolved = links.resolve_links(["Ar-L-3D-0002"], rows)
    assert resolved[0]["status"] == links.LINK_MATCHED
    assert resolved[0]["projectModel"] == "Ar-L"


def test_resolve_links_flags_project_part_declared_as_architecture() -> None:
    rows = [_row("F620S", "F620S-3D-0075", "I2")]
    resolved = links.resolve_links(["F620S-3D-0075"], rows)
    assert resolved[0]["status"] == links.LINK_SOURCE_MISMATCH


def test_resolve_links_flags_missing_serial() -> None:
    resolved = links.resolve_links(["Ar-L-3D-9999"], [_row("Ar-L", "Ar-L-3D-0002", "I1")])
    assert resolved[0]["status"] == links.LINK_MISSING


def test_resolve_links_flags_conflicting_instances() -> None:
    rows = [
        _row("Ar-L", "Ar-L-3D-0002", "I1"),
        _row("Ar-L", "Ar-L-3D-0002", "I2"),
    ]
    resolved = links.resolve_links(["Ar-L-3D-0002"], rows)
    assert resolved[0]["status"] == links.LINK_CONFLICT


# ── 方案 B 汇总 ─────────────────────────────────────────────────────────────


def test_summarize_combines_project_and_linked_architecture() -> None:
    rows = [
        _row("F620S", "F620S-3D-0075", "P1", "已完成"),
        _row("F620S", "F620S-3D-0076", "P2", "审批中"),
        _row("Ar-L", "Ar-L-3D-0002", "A1", "已完成"),
        _row("Ar-L", "Ar-L-3D-0003", "A2", "审批中"),
    ]
    summary = links.summarize(
        rows, {"F620S": ["Ar-L-3D-0002"]}, instance_of=lambda row: row["instance"]
    )
    vehicle = summary["vehicles"][0]
    assert vehicle["projectOnly"]["instances"] == 2
    assert vehicle["projectOnly"]["completed"] == 1
    assert vehicle["linkedArchitecture"]["matched"] == 1
    assert vehicle["linkedArchitecture"]["instances"] == 1
    # 合计 = 项目件 2 + 已匹配架构件 1
    assert vehicle["combined"]["instances"] == 3
    assert vehicle["combined"]["completed"] == 2
    assert vehicle["combined"]["completionRate"] == pytest.approx(66.67, rel=1e-3)


def test_summarize_counts_instances_not_rows() -> None:
    """一个实例多行只计一次（回归：早期版本把行当实例，746 行报成 746 单）。"""
    rows = [
        _row("F620S", "F620S-3D-0075", "P1", "已完成"),
        _row("F620S", "F620S-3D-0075", "P1", "已完成"),
        _row("F620S", "F620S-3D-0075", "P1", "已完成"),
    ]
    summary = links.summarize(rows, {}, instance_of=lambda row: row["instance"])
    project = summary["vehicles"][0]["projectOnly"]
    assert project["instances"] == 1
    assert project["rows"] == 3


def test_summarize_does_not_count_unmatched_declarations() -> None:
    rows = [_row("F620S", "F620S-3D-0075", "P1", "已完成")]
    summary = links.summarize(
        rows,
        {"F620S": ["Ar-L-3D-9999", "F620S-3D-0075"]},
        instance_of=lambda row: row["instance"],
    )
    vehicle = summary["vehicles"][0]
    assert vehicle["linkedArchitecture"]["declared"] == 2
    assert vehicle["linkedArchitecture"]["matched"] == 0
    assert vehicle["combined"]["instances"] == 1
    statuses = {item["status"] for item in vehicle["links"]}
    assert statuses == {links.LINK_MISSING, links.LINK_SOURCE_MISMATCH}


def test_summarize_shared_architecture_counts_per_vehicle_but_dedupes_globally() -> None:
    """同一架构单被两个车型声明：各车型各计 1，全局只算 1 个实例。"""
    rows = [
        _row("F620S", "F620S-3D-0075", "P1", "已完成"),
        _row("F710S", "F710S-3D-0001", "P2", "已完成"),
        _row("Ar-L", "Ar-L-3D-0002", "A1", "已完成"),
    ]
    summary = links.summarize(
        rows,
        {"F620S": ["Ar-L-3D-0002"], "F710S": ["Ar-L-3D-0002"]},
        instance_of=lambda row: row["instance"],
    )
    by_vehicle = {item["vehicle"]: item for item in summary["vehicles"]}
    assert by_vehicle["F620S"]["linkedArchitecture"]["instances"] == 1
    assert by_vehicle["F710S"]["linkedArchitecture"]["instances"] == 1
    assert summary["linkedInstanceCount"] == 1


# ── 存储：版本化与撤销 ──────────────────────────────────────────────────────


@pytest.fixture()
def db(tmp_path):
    manager = DatabaseManager(tmp_path / "links.db")
    manager.init_database()
    return manager


def test_replace_links_adds_and_removes(db) -> None:
    first = db.replace_data_model_vehicle_links("F620S", ["Ar-L-3D-0002", "Ar-L-3D-0003"])
    assert first["added"] == ["Ar-L-3D-0002", "Ar-L-3D-0003"]
    second = db.replace_data_model_vehicle_links("F620S", ["Ar-L-3D-0003"])
    assert second["removed"] == ["Ar-L-3D-0002"]
    assert second["unchanged"] == ["Ar-L-3D-0003"]
    active = db.list_data_model_vehicle_links("F620S")
    assert [item["serial"] for item in active] == ["Ar-L-3D-0003"]


def test_removed_link_keeps_history_and_can_be_restored(db) -> None:
    db.replace_data_model_vehicle_links("F620S", ["Ar-L-3D-0002"])
    db.replace_data_model_vehicle_links("F620S", [])
    history = db.list_data_model_vehicle_links("F620S", active_only=False)
    assert len(history) == 1
    assert history[0]["active"] == 0
    assert history[0]["effective_to"]        # 撤销时写入生效止

    restored = db.replace_data_model_vehicle_links("F620S", ["Ar-L-3D-0002"])
    assert restored["added"] == ["Ar-L-3D-0002"]
    active = db.list_data_model_vehicle_links("F620S")
    assert active[0]["revision"] == 2  # 版本递增，历史行保留


def test_clear_links_counts_and_deactivates(db) -> None:
    db.replace_data_model_vehicle_links("F620S", ["A", "B"])
    assert db.clear_data_model_vehicle_links("F620S") == 2
    assert db.list_data_model_vehicle_links("F620S") == []


def test_links_are_scoped_per_vehicle(db) -> None:
    db.replace_data_model_vehicle_links("F620S", ["A"])
    db.replace_data_model_vehicle_links("F710S", ["A", "B"])
    assert [i["serial"] for i in db.list_data_model_vehicle_links("F620S")] == ["A"]
    assert len(db.list_data_model_vehicle_links("F710S")) == 2
    assert len(db.list_data_model_vehicle_links()) == 3


def test_link_record_carries_operator_and_basis(db) -> None:
    db.replace_data_model_vehicle_links(
        "F620S", ["A"], operator="tester", basis="派单会议 2026-10"
    )
    item = db.list_data_model_vehicle_links("F620S")[0]
    assert item["operator"] == "tester"
    assert item["basis"] == "派单会议 2026-10"
    assert item["recorded_at"]


# ── 与快照联动：定义驱动取单号/实例号 ──────────────────────────────────────


def test_resolve_links_uses_definition_for_serial_and_instance() -> None:
    definition = form_definition("tdc_data_model")
    header = definition["headerRows"][0]
    values = [""] * len(header)
    values[header.index("实例号")] = "90000101"
    values[header.index("流水单号")] = "Ar-L-3D-0002"
    values[header.index("项目/车型")] = "Ar-L"
    row = {
        "values": values,
        "dimensions": {
            **attribution.dimension_fields("Ar-L"),
            "stage": "Ar-L",
            "status": "已完成",
        },
    }
    resolved = links.resolve_links(["Ar-L-3D-0002"], [row], definition)
    assert resolved[0]["status"] == links.LINK_MATCHED
    assert resolved[0]["instance"] == "90000101"
