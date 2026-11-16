"""EWO 离线验证器（生产自检工具）的判读契约：CSV 与 XLSX 两种来源。

验证器是发到生产机上的判读工具，所以它的判读必须和导出链路的门禁同源：
表头逐字 111 列、契约外列带值即失败、BF（第 58 列）起是否真有值、业务编号空/重复。
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from ewo_verify_cli import main, verify
from services.ewo_official_rows import (
    E_HEADER_MISMATCH,
    EwoExportGateError,
    contract_labels,
)
from tests.test_ewo_official_rows import write_workbook

BF_INDEX = 57


def _rows(labels: list[str], count: int = 3, *, blank_at: int | None = None, tail_value: bool = True):
    rows: list[list[str]] = []
    for offset in range(count):
        row = ["" for _ in labels]
        row[0] = "" if offset == blank_at else f"EWO-9{offset:04d}"
        if tail_value:
            for index in range(BF_INDEX, len(labels)):
                row[index] = f"值{index}"
        rows.append(row)
    return rows


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\r\n")
        writer.writerow(header)
        writer.writerows(rows)
    return path


@pytest.fixture()
def labels() -> list[str]:
    return contract_labels()


def test_verify_csv_pass(tmp_path, labels):
    path = write_csv(tmp_path / "ok.csv", labels, _rows(labels))
    report = verify(path)
    assert report["ok"] is True
    assert report["source_kind"] == "csv"
    assert report["data_rows"] == 3
    assert report["header_width"] == 111
    assert report["bf_column"] == labels[BF_INDEX]
    assert report["bf_nonempty"] == 3
    assert report["blank_business_numbers"] == 0


def test_verify_xlsx_pass(tmp_path, labels):
    path = write_workbook(tmp_path / "ok.xlsx", labels, _rows(labels))
    report = verify(path)
    assert report["ok"] is True
    assert report["source_kind"] == "xlsx"
    assert report["bf_nonempty"] == 3


def test_verify_csv_header_drift_raises(tmp_path, labels):
    drifted = list(labels)
    drifted[BF_INDEX] = drifted[BF_INDEX] + "(旧模板)"
    path = write_csv(tmp_path / "drift.csv", drifted, _rows(labels))
    with pytest.raises(EwoExportGateError) as excinfo:
        verify(path)
    assert excinfo.value.code == E_HEADER_MISMATCH


def test_verify_csv_reports_blank_number(tmp_path, labels):
    path = write_csv(tmp_path / "blank.csv", labels, _rows(labels, blank_at=1))
    report = verify(path)
    assert report["ok"] is False
    assert report["blank_business_numbers"] == 1
    assert report["duplicate_business_numbers"] == 0


def test_verify_csv_reports_duplicate_number(tmp_path, labels):
    rows = _rows(labels, count=2)
    rows[1][0] = rows[0][0]
    report = verify(write_csv(tmp_path / "dup.csv", labels, rows))
    assert report["ok"] is False
    assert report["duplicate_business_numbers"] == 1


def test_verify_tail_empty_fails(tmp_path, labels):
    """BF 起整段为空 = 修复未生效的特征，必须判不通过而不是“数据为空”。"""
    report = verify(write_csv(tmp_path / "tail.csv", labels, _rows(labels, tail_value=False)))
    assert report["ok"] is False
    assert report["bf_nonempty"] == 0


def test_verify_rejects_row_overflow(tmp_path, labels):
    path = write_csv(tmp_path / "many.csv", labels, _rows(labels, count=4))
    with pytest.raises(EwoExportGateError) as excinfo:
        verify(path, max_rows=3)
    assert excinfo.value.code == "E_TOO_MANY_ROWS"


def test_main_exit_codes(tmp_path, labels, capsys):
    good = write_csv(tmp_path / "ok.csv", labels, _rows(labels))
    bad = write_csv(tmp_path / "bad.csv", labels, _rows(labels, tail_value=False))
    assert main([str(good), "--json"]) == 0
    assert '"ok": true' in capsys.readouterr().out
    assert main([str(bad), "--json"]) == 1
    assert main([str(tmp_path / "nope.csv")]) == 2


def test_main_out_writes_111_column_csv(tmp_path, labels):
    source = write_csv(tmp_path / "ok.csv", labels, _rows(labels))
    target = tmp_path / "out" / "projected.csv"
    assert main([str(source), "--out", str(target)]) == 0
    assert target.exists()
    with target.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == labels
    assert len(rows) == 4
    assert rows[1][BF_INDEX] == f"值{BF_INDEX}"
