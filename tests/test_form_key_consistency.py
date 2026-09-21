# -*- coding: utf-8 -*-
"""Cross-module consistency contract for the unified form_key whitelists.

统一表单 form_key 白名单分散在四个模块（审计 M1；前端回退映射已由
后端单一关联注册表取代）：
1. services/deliverable_form_analysis.py   FORM_KEYS / _REPORT_BY_FORM_KEY
2. core/db_manager.py                      _FORM_SNAPSHOT_KEYS / _FORM_SNAPSHOT_REPORTS / DDL CHECK
3. services/scheduled_archive_runner.py    JOB_FORM_KEYS（注册表派生）
4. web/app.py                              DELIVERABLE_FORM_LINKS（注册表派生）
+  core/project_status_contracts.py        DELIVERABLE_LINK_REGISTRY（单一注册表）

本测试锁定它们的相互一致性，新增 form_key 时漏改任何一处都会在此失败。
"""

from __future__ import annotations

import re
from pathlib import Path

from core.db_manager import (
    ARCHIVE_JOB_CONTRACTS,
    _FORM_SNAPSHOT_KEYS,
    _FORM_SNAPSHOT_REPORTS,
    DatabaseManager,
)
from core.project_status_contracts import DELIVERABLE_LINK_REGISTRY
from services.deliverable_form_analysis import _REPORT_BY_FORM_KEY, FORM_KEYS
from services.scheduled_archive_runner import JOB_FORM_KEYS


def test_db_and_analysis_whitelists_are_identical() -> None:
    assert _FORM_SNAPSHOT_KEYS == FORM_KEYS
    assert dict(_FORM_SNAPSHOT_REPORTS) == dict(_REPORT_BY_FORM_KEY)


def test_ddl_check_whitelist_matches(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "ddl-consistency.db")
    db.init_database()
    with db.get_connection() as conn:
        ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'deliverable_form_snapshots'"
        ).fetchone()["sql"]
    segment_match = re.search(r"form_key IN \(([^)]*)\)", ddl)
    assert segment_match, "DDL 缺少 form_key CHECK 白名单"
    declared = set(re.findall(r"'([A-Za-z0-9_-]+)'", segment_match.group(1)))
    assert declared == set(FORM_KEYS)


def test_runner_job_form_keys_align_with_archives_and_forms() -> None:
    assert set(JOB_FORM_KEYS) == set(ARCHIVE_JOB_CONTRACTS)
    assert set(JOB_FORM_KEYS.values()) == set(FORM_KEYS)


def test_registry_form_keys_are_valid_and_frontend_has_no_fallback_map() -> None:
    """后端注册表 form_key 均为合法白名单值；前端不再持有回退映射。"""
    js = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    assert "DELIVERABLE_FORM_KEY_BY_ITEM" not in js

    registry_form_keys = {
        entry["form_key"] for entry in DELIVERABLE_LINK_REGISTRY.values()
    }
    assert registry_form_keys == set(FORM_KEYS)
    assert registry_form_keys == set(JOB_FORM_KEYS.values())


def test_deliverable_form_links_are_valid_form_keys() -> None:
    import web.app as web_app

    links = web_app.DELIVERABLE_FORM_LINKS
    assert links["VPI-T2-D3"] == "VPI-T2-D3"
    assert links["VPI-T2-D2"] == "tdc_sor"
    assert links["VPI-T2-D5"] == "tdc_data_model"
    assert set(links.values()) <= set(FORM_KEYS)
