# -*- coding: utf-8 -*-
"""tools/sign_daily_local_report.py：本地表单 → 签署日报（离线只读）契约。

覆盖三件事：
1. 官方 47 列契约 fail-closed（表头漂移即拒，不静默少列）；
2. 口径与插件同源（复用 rules/compose，数据日期只认 --date）；
3. 零写库（NullStore 的任何写方法都抛错）。
"""

from __future__ import annotations

import os
import sys
import time
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import sign_daily_local_report as tool  # noqa: E402

from services.tdc_official_rows import (  # noqa: E402
    OfficialWorkbookContractError,
    official_contract_headers,
)
from tests.test_ewo_official_rows import write_workbook  # noqa: E402

DATA_DATE = date(2026, 11, 6)


def _rows() -> list[dict[str, object]]:
    def row(serial: str, **values: object) -> dict[str, object]:
        base: dict[str, object] = {
            "流水单号": serial,
            "项目/车型": "F610M",
            "部门": "车身科",
            "申请人": "起草甲",
            "申请日期": "2026-11-02 10:00:00",
            "零件号": f"{serial}-P1",
            "零件名称": "前门内板",
            "加签人员": "",
            "应签人数": "1",
            "已签人数": "0",
            "未签人数": "1",
            "签署率": "0.00%",
            "待审批人员": "张三",
            "状态": "进行中",
        }
        base.update(values)
        return base

    return [row("TDC-2001", 冲压="张三(未签)"), row("TDC-2002", 底盘="李四(未签)")]


def _workbook(path: Path, *, drift: bool = False) -> Path:
    header = official_contract_headers("data_model")
    if drift:
        header = list(header)
        header[2] = header[2] + "(旧模板)"
    matrix = [[row.get(name) for name in header] for row in _rows()]
    return write_workbook(path, header, matrix, sheet_name="Sheet1")


def test_build_report_uses_confirmed_date(tmp_path):
    payload = tool.build_report(
        path=_workbook(tmp_path / "ok.xlsx"),
        data_date=DATA_DATE,
        projects=[],
        departments=[],
        region="车体区域",
    )
    source = payload["source"]
    assert source["dataDate"] == "2026-11-06"
    assert source["rows"] == 2
    report = payload["report"]
    assert "20261106" in report["subject"]
    assert len(report["flows"]) == 2
    assert report["delta"] is None and report["baseline"] is None
    assert report["stale"] is False
    assert report["snapshotSaved"] is False
    # 会签列欠账进入「按区域」分组（口径本身由 test_sign_daily_rules.py 覆盖，这里只验接线）
    assert report["charts"]["external"]
    assert "冲压" in [item["group"] for item in report["charts"]["external"]]


def test_header_drift_is_rejected(tmp_path):
    with pytest.raises(OfficialWorkbookContractError):
        tool.build_report(
            path=_workbook(tmp_path / "drift.xlsx", drift=True),
            data_date=DATA_DATE,
            projects=[],
            departments=[],
            region="车体区域",
        )


def test_null_store_refuses_any_write():
    store = tool.NullStore()
    assert store.snapshot_dates("F610M") == []
    assert store.snapshot_scope("F610M", DATA_DATE) is None
    assert store.snapshot_rows(["F610M"], DATA_DATE) == []
    assert store.conclusions(["F610M"]) == {}
    with pytest.raises(RuntimeError):
        store.save_snapshot(DATA_DATE, "F610M", [], scope_kind="all", serials=[], source_snapshot_at=None)


def test_markdown_states_source_and_no_change(tmp_path):
    payload = tool.build_report(
        path=_workbook(tmp_path / "ok.xlsx"),
        data_date=DATA_DATE,
        projects=[],
        departments=[],
        region="车体区域",
    )
    markdown = tool.render_markdown(payload)
    assert "数据截至日期：2026-11-06（用户确认，未经系统核验）" in markdown
    assert "不计算日变化" in markdown
    assert "2026-11-06" in markdown.splitlines()[3] or "2026-11-06" in markdown
    assert "| TDC-2001 |" in markdown


def test_main_exit_codes(tmp_path, capsys):
    good = _workbook(tmp_path / "ok.xlsx")
    bad = _workbook(tmp_path / "drift.xlsx", drift=True)
    assert tool.main(["--file", str(good), "--date", "2026-11-06"]) == 0
    assert "3D单签署进展日报" in capsys.readouterr().out
    assert tool.main(["--file", str(bad), "--date", "2026-11-06"]) == 1
    assert tool.main(["--file", str(tmp_path / "nope.xlsx"), "--date", "2026-11-06"]) == 2
    assert tool.main(["--file", str(good), "--date", "2026/11/06"]) == 2


def test_md_output_written(tmp_path):
    good = _workbook(tmp_path / "ok.xlsx")
    target = tmp_path / "out" / "report.md"
    assert tool.main(["--file", str(good), "--date", "2026-11-06", "--md", str(target)]) == 0
    assert "数据截至日期：2026-11-06" in target.read_text(encoding="utf-8")


def test_roster_csv_overrides_seed_roster(tmp_path):
    roster = tmp_path / "roster.csv"
    roster.write_text("姓名,科室\n张三,车身科\n李四,内饰科\n", encoding="utf-8-sig")
    plugin = tool._load_plugin()
    effective = tool._effective(plugin, roster, None)
    payload = tool.build_report(
        path=_workbook(tmp_path / "ok.xlsx"),
        data_date=DATA_DATE,
        projects=[],
        departments=[],
        region="车体区域",
        effective=effective,
    )
    charts = payload["report"]["charts"]
    assert charts["needsEntry"] == []
    assert "车身科" in [item["group"] for item in charts["sections"]]


def test_roster_csv_with_unknown_department_fails(tmp_path):
    roster = tmp_path / "roster.csv"
    roster.write_text("姓名,科室\n张三,不存在的科室\n", encoding="utf-8-sig")
    plugin = tool._load_plugin()
    with pytest.raises(ValueError) as info:
        tool._effective(plugin, roster, None)
    assert "科室" in str(info.value)


# ── 目录模式：以最后修改时间最晚的为准，不合格不退回 ──────────────────


def _age(path: Path, seconds: float) -> None:
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def test_dir_mode_picks_newest(tmp_path, capsys):
    old = _workbook(tmp_path / "old.xlsx")
    new = _workbook(tmp_path / "new.xlsx")
    _age(old, 3600)
    _age(new, 60)
    assert tool.main(["--dir", str(tmp_path), "--date", "2026-11-06"]) == 0
    captured = capsys.readouterr()
    assert "new.xlsx" in captured.err and "已选中" in captured.err
    assert "参与计算" in captured.out


def test_dir_mode_refuses_fallback_when_newest_invalid(tmp_path, capsys):
    good = _workbook(tmp_path / "good.xlsx")
    bad = _workbook(tmp_path / "bad.xlsx", drift=True)
    _age(good, 3600)
    _age(bad, 60)
    assert tool.main(["--dir", str(tmp_path), "--date", "2026-11-06"]) == 1
    captured = capsys.readouterr()
    assert "表头与官方 47 列不一致" in captured.err  # 原因码已中文化
    assert "不退回" in captured.err


def test_dir_mode_requires_one_source(tmp_path, capsys):
    assert tool.main(["--date", "2026-11-06"]) == 2
    assert tool.main(["--dir", str(tmp_path), "--file", str(tmp_path / "x.xlsx"), "--date", "2026-11-06"]) == 2

# ── 2026-11-11 终端加密容器：CLI 与服务端同一输入 → 同 code 同文案 ──────


def _container_workbook(path: Path) -> Path:
    from services.xlsx_preview import ENCRYPTED_CONTAINER_SIGNATURES, SNIFF_BYTES

    head = ENCRYPTED_CONTAINER_SIGNATURES[0]
    path.write_bytes(head + bytes(1024 - SNIFF_BYTES) + b"PK\x03\x04 not really")
    return path


def test_container_workbook_reports_encrypted_code(tmp_path, capsys):
    target = _container_workbook(tmp_path / "encrypted.xlsx")
    assert tool.main(["--file", str(target), "--date", DATA_DATE.isoformat()]) == 1
    captured = capsys.readouterr()
    assert "E_ENCRYPTED_WORKBOOK：文件受公司终端加密保护" in captured.err
    assert "reason=encrypted_container" in captured.err
    # 用户可见输出里不得出现容器魔数的十六进制
    assert "17da5fa0" not in captured.err.lower()


def test_cli_and_plugin_share_the_same_mapping(tmp_path, capsys):
    """同一份容器样本：CLI 打印的 code/文案必须与服务端导入路径逐字一致。"""
    target = _container_workbook(tmp_path / "encrypted.xlsx")
    plugin = tool._load_plugin()
    with pytest.raises(plugin.importer.ManualImportError) as caught:
        plugin.importer.source_from_file(target, DATA_DATE)

    assert tool.main(["--file", str(target), "--date", DATA_DATE.isoformat()]) == 1
    captured = capsys.readouterr()

    assert caught.value.code == "E_ENCRYPTED_WORKBOOK"
    assert f"{caught.value.code}：{caught.value.message}" in captured.err
    assert set(caught.value.diagnostic) <= {"reason", "sizeBucket", "colIndex"}
    assert caught.value.diagnostic["reason"] == "encrypted_container"
