# -*- coding: utf-8 -*-
"""Cross-module consistency contract for the unified form_key whitelists.

统一表单 form_key 白名单分散在五个模块（审计 M1）：
1. services/deliverable_form_analysis.py   FORM_KEYS / _REPORT_BY_FORM_KEY
2. core/db_manager.py                      _FORM_SNAPSHOT_KEYS / _FORM_SNAPSHOT_REPORTS / DDL CHECK
3. services/scheduled_archive_runner.py    JOB_FORM_KEYS
4. web/app.py                              DELIVERABLE_FORM_LINKS（交付物联动子集）
5. web/static/app.js                       DELIVERABLE_FORM_KEY_BY_ITEM（前端回退映射）

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


def test_frontend_form_key_map_values_are_valid_form_keys() -> None:
    js = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    start = js.index("const DELIVERABLE_FORM_KEY_BY_ITEM")
    block = js[start: js.index("};", start)]
    values = re.findall(r':\s*"([A-Za-z0-9_-]+)"', block)
    assert values, "前端映射不应为空"
    assert set(values) <= set(FORM_KEYS)


def test_deliverable_form_links_are_valid_form_keys() -> None:
    import web.app as web_app

    links = web_app.DELIVERABLE_FORM_LINKS
    assert links["VPI-T2-D3"] == "VPI-T2-D3"
    assert links["VPI-T2-D2"] == "tdc_sor"
    assert links["VPI-T2-D5"] == "tdc_data_model"
    assert set(links.values()) <= set(FORM_KEYS)
