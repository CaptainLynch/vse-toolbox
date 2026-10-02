# -*- coding: utf-8 -*-
"""Single deliverable-link registry closure contract.

core.project_status_contracts.DELIVERABLE_LINK_REGISTRY 是归档任务 job_key、
目录条目 catalog_id、项目状态交付物 deliverable_id 与统一表单 form_key 的
唯一关联来源；db_manager.ARCHIVE_JOB_CONTRACTS（第三元组）、
scheduled_archive_runner.JOB_FORM_KEYS 与 web.app.DELIVERABLE_FORM_LINKS
均从注册表派生。本测试锁定五向闭合，漂移即红。
"""

from __future__ import annotations

import web.app as web_app
from core.db_manager import ARCHIVE_JOB_CONTRACTS
from core.project_status_contracts import DELIVERABLE_LINK_REGISTRY
from services.scheduled_archive_runner import JOB_FORM_KEYS


def test_registry_closes_with_archive_contracts_job_form_keys_and_links() -> None:
    # 五向闭合：注册表 ↔ ARCHIVE_JOB_CONTRACTS ↔ JOB_FORM_KEYS 派生值
    # ↔ DELIVERABLE_FORM_LINKS 派生值 ↔ _DELIVERABLES_CATALOG id 集合。
    assert set(DELIVERABLE_LINK_REGISTRY) == set(ARCHIVE_JOB_CONTRACTS)
    assert {
        job_key: entry["form_key"]
        for job_key, entry in DELIVERABLE_LINK_REGISTRY.items()
    } == JOB_FORM_KEYS
    derived_links = {
        entry["deliverable_id"]: entry["form_key"]
        for entry in DELIVERABLE_LINK_REGISTRY.values()
        if entry["deliverable_id"] is not None
    }
    assert derived_links == web_app.DELIVERABLE_FORM_LINKS
    for job_key, entry in DELIVERABLE_LINK_REGISTRY.items():
        assert ARCHIVE_JOB_CONTRACTS[job_key][2] == entry["deliverable_id"]
    catalog_ids = {item["id"] for item in web_app._DELIVERABLES_CATALOG}
    assert catalog_ids == {entry["catalog_id"] for entry in DELIVERABLE_LINK_REGISTRY.values()}


def test_registry_literal_values() -> None:
    assert DELIVERABLE_LINK_REGISTRY == {
        "aras_ewo": {
            "catalog_id": "aras-ewo",
            "deliverable_id": "VPI-T2-D3",
            "display_code": "DEL-003",
            "form_key": "VPI-T2-D3",
        },
        "aras_paa": {
            "catalog_id": "aras-paa",
            "deliverable_id": "VPI-T2-D6",
            "display_code": "DEL-006",
            "form_key": "aras_paa",
        },
        "aras_ncr_progress": {
            "catalog_id": "aras-ncr-progress",
            "deliverable_id": "VPI-T2-D7",
            "display_code": "DEL-007",
            "form_key": "aras_ncr_progress",
        },
        "aras_ncr_detail": {
            "catalog_id": "aras-ncr-detail",
            "deliverable_id": "VPI-T2-D8",
            "display_code": "DEL-008",
            "form_key": "aras_ncr_detail",
        },
        "tdc_data_model": {
            "catalog_id": "tdc-data-model",
            "deliverable_id": "VPI-T2-D5",
            "display_code": "DEL-005",
            "form_key": "tdc_data_model",
        },
        "tdc_sor": {
            "catalog_id": "tdc-sor",
            "deliverable_id": "VPI-T2-D2",
            "display_code": "DEL-002",
            "form_key": "tdc_sor",
        },
    }


def test_registry_six_way_closure_values() -> None:
    """六条目关联关系逐值断言：job_key ↔ catalog_id ↔ deliverable_id ↔
    display_code ↔ form_key 派生表（ARCHIVE_JOB_CONTRACTS 第三元组、
    JOB_FORM_KEYS、DELIVERABLE_FORM_LINKS）五向闭合。"""
    expected_rows = {
        "aras_ewo": ("aras-ewo", "VPI-T2-D3", "DEL-003", "VPI-T2-D3"),
        "aras_paa": ("aras-paa", "VPI-T2-D6", "DEL-006", "aras_paa"),
        "aras_ncr_progress": ("aras-ncr-progress", "VPI-T2-D7", "DEL-007", "aras_ncr_progress"),
        "aras_ncr_detail": ("aras-ncr-detail", "VPI-T2-D8", "DEL-008", "aras_ncr_detail"),
        "tdc_data_model": ("tdc-data-model", "VPI-T2-D5", "DEL-005", "tdc_data_model"),
        "tdc_sor": ("tdc-sor", "VPI-T2-D2", "DEL-002", "tdc_sor"),
    }
    assert len(DELIVERABLE_LINK_REGISTRY) == 6
    for job_key, (catalog_id, deliverable_id, display_code, form_key) in expected_rows.items():
        entry = DELIVERABLE_LINK_REGISTRY[job_key]
        assert entry["catalog_id"] == catalog_id
        assert entry["deliverable_id"] == deliverable_id
        assert entry["display_code"] == display_code
        assert entry["form_key"] == form_key
        # 反查闭合：catalog_id / deliverable_id 反查回同一 job_key。
        from core.project_status_contracts import (
            find_job_key_by_deliverable_id,
            find_registry_entry_by_catalog_id,
            find_registry_entry_by_deliverable_id,
        )
        by_catalog = find_registry_entry_by_catalog_id(catalog_id)
        assert by_catalog is not None and DELIVERABLE_LINK_REGISTRY[job_key] == by_catalog
        by_deliverable = find_registry_entry_by_deliverable_id(deliverable_id)
        assert by_deliverable is not None and DELIVERABLE_LINK_REGISTRY[job_key] == by_deliverable
        assert find_job_key_by_deliverable_id(deliverable_id) == job_key
        # 派生表第三元组闭合。
        assert ARCHIVE_JOB_CONTRACTS[job_key][2] == deliverable_id
        assert JOB_FORM_KEYS[job_key] == form_key
    # D6-D8 formLink 派生（web.app.DELIVERABLE_FORM_LINKS）存在。
    assert web_app.DELIVERABLE_FORM_LINKS["VPI-T2-D6"] == "aras_paa"
    assert web_app.DELIVERABLE_FORM_LINKS["VPI-T2-D7"] == "aras_ncr_progress"
    assert web_app.DELIVERABLE_FORM_LINKS["VPI-T2-D8"] == "aras_ncr_detail"


def test_registry_has_no_vpi_t2_d4_or_a_face_entries() -> None:
    """严禁注册表引入 VPI-T2-D4（造型 VDR 审批 / A 面）关联。"""
    deliverable_ids = {
        entry["deliverable_id"]
        for entry in DELIVERABLE_LINK_REGISTRY.values()
        if entry["deliverable_id"] is not None
    }
    assert "VPI-T2-D4" not in deliverable_ids
    all_values = " ".join(
        str(value)
        for entry in DELIVERABLE_LINK_REGISTRY.values()
        for value in entry.values()
    )
    assert "a_face" not in all_values
    assert "a-face" not in all_values
    assert "aface" not in all_values
