from __future__ import annotations

import csv

import pytest

from services.aras_crawler import EWOReportPage
from services.aras_export import (
    CSVExportResult,
    export_ewo_report_csv,
    export_report_contract_csv,
    export_report_csv,
)


def test_export_ewo_csv_is_excel_compatible_bounded_and_credential_safe(tmp_path) -> None:
    page = EWOReportPage(
        rows=[
            {
                "_no": "EWO-1",
                "eplmwriteneplcode": "F610S",
                "note": "Authorization: Bearer fictional-token Cookie: sid=fictional-cookie",
                "formula": "=HYPERLINK(\"https://example.invalid\")",
                "cookie": "sid=must-not-export",
                "access_token": "must-not-export",
                "raw_xml": "<must-not-export/>",
            }
        ],
        page=1,
        item_ids=["ID-1"],
        raw_xml="<xml/>",
    )

    result = export_ewo_report_csv(page, output_dir=tmp_path, file_name="../ewo:report")

    assert result.path.parent == tmp_path
    assert result.path.name == "ewo_report.csv"
    assert result.row_count == 1
    assert result.path.read_bytes().startswith(b"\xef\xbb\xbf")

    with result.path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert "cookie" not in rows[0]
    assert "access_token" not in rows[0]
    assert "raw_xml" not in rows[0]
    assert rows[0]["_no"] == "EWO-1"
    assert rows[0]["eplmwriteneplcode"] == "F610S"
    assert "fictional-token" not in rows[0]["note"]
    assert "fictional-cookie" not in rows[0]["note"]
    assert "[redacted]" in rows[0]["note"]
    assert rows[0]["formula"].startswith("'=")


def test_export_empty_ewo_csv_still_writes_stable_headers(tmp_path) -> None:
    page = EWOReportPage(rows=[], page=1, item_ids=[], raw_xml="<xml/>")

    result = export_ewo_report_csv(page, output_dir=tmp_path, file_name="empty.csv")

    assert result.row_count == 0
    assert "_no" in result.columns
    assert result.path.read_text(encoding="utf-8-sig").startswith("_affect_3c,")


def test_export_report_contract_csv_uses_chinese_headers_and_source_keys(tmp_path) -> None:
    result = export_report_contract_csv(
        "ewo",
        [
            {
                "state": "DRAFT1",
                "_sort_sub_type": "PWO-EWO定点",
                "created_by_id__keyed_name": "User A",
                "_rsp_name": "User B",
                "_rsp_smt": "视觉工程科",
                "_subject": "Subject",
                "_no": "EWO-1",
            }
        ],
        output_dir=tmp_path,
        file_name="contract.csv",
    )

    assert result.path.name == "contract.csv"
    with result.path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows[0][:6] == ["EWO编号", "二级WO类别", "起草人", "责任工程师名称", "责任工程师专业科室", "主题"]
    assert rows[1][:6] == ["EWO-1", "EWO定点", "User A", "User B", "视觉工程科", "Subject"]


def test_export_report_csv_preferred_fields_first_then_first_appearance_with_stable_json(tmp_path) -> None:
    rows = [
        {"id": "PAA-1", "project": "F610S", "meta": {"b": 2, "a": {"z": 1, "y": None}}},
        {"id": "PAA-2", "extra": 5},
    ]

    result = export_report_csv(
        rows, output_dir=tmp_path, report_name="paa_export", preferred_fields=["project", "id"]
    )

    assert isinstance(result, CSVExportResult)
    assert result.path.name == "paa_export.csv"
    assert result.row_count == 2
    assert result.fieldnames == ("project", "id", "meta", "extra")
    assert result.path.read_bytes().startswith(b"\xef\xbb\xbf")

    with result.path.open(encoding="utf-8-sig", newline="") as stream:
        data = list(csv.DictReader(stream))
    assert data[0]["project"] == "F610S"
    assert data[0]["meta"] == '{"a":{"y":null,"z":1},"b":2}'
    assert data[1]["meta"] == ""
    assert data[1]["extra"] == "5"


def test_export_report_csv_guards_formula_injection_and_keeps_plain_values(tmp_path) -> None:
    rows = [
        {
            "plain": "normal",
            "spaced": " =1+1",
            "equal": '=HYPERLINK("https://example.invalid")',
            "plus": "+SUM(A1)",
            "minus": "-2+3",
            "at": "@cmd",
            "already_quoted": "'=safe",
            "number": 42,
            "negative": -5,
            "nothing": None,
        }
    ]

    result = export_report_csv(rows, output_dir=tmp_path, report_name="injection")

    with result.path.open(encoding="utf-8-sig", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["plain"] == "normal"
    assert row["spaced"] == "' =1+1"
    assert row["equal"] == "'=HYPERLINK(\"https://example.invalid\")"
    assert row["plus"] == "'+SUM(A1)"
    assert row["minus"] == "'-2+3"
    assert row["at"] == "'@cmd"
    assert row["already_quoted"] == "'=safe"
    assert row["number"] == "42"
    assert row["negative"] == "'-5"
    assert row["nothing"] == ""


def test_export_report_csv_names_are_safe_and_cannot_escape_output_dir(tmp_path) -> None:
    result = export_report_csv(
        [{"a": 1}],
        output_dir=tmp_path,
        report_name="paa_export",
        filters={"project": "F610S", "department": "../../body engineering"},
    )

    assert result.path.parent == tmp_path
    assert result.path.name == "paa_export_project_F610S_department_body_engineering.csv"
    assert ".." not in result.path.name

    escaped = export_report_csv([{"a": 1}], output_dir=tmp_path, report_name="../../escape")
    assert escaped.path.parent == tmp_path
    assert escaped.path.name == "escape.csv"


def test_export_report_csv_empty_rows_still_writes_readable_file(tmp_path) -> None:
    result = export_report_csv([], output_dir=tmp_path, report_name="empty_paa")

    assert result.row_count == 0
    assert result.fieldnames == ()
    assert result.path.read_bytes() == b"\xef\xbb\xbf\n"


def test_export_report_csv_empty_rows_use_preferred_fields_as_header(tmp_path) -> None:
    result = export_report_csv(
        [], output_dir=tmp_path, report_name="empty_preferred", preferred_fields=["project", "id"]
    )

    assert result.fieldnames == ("project", "id")
    with result.path.open(encoding="utf-8-sig", newline="") as stream:
        assert next(csv.reader(stream)) == ["project", "id"]


def test_export_report_csv_atomic_overwrite_leaves_no_temp_files(tmp_path) -> None:
    first = export_report_csv([{"a": 1}], output_dir=tmp_path, report_name="same")
    second = export_report_csv([{"a": 2, "b": 3}], output_dir=tmp_path, report_name="same")

    assert first.path == second.path
    with second.path.open(encoding="utf-8-sig", newline="") as stream:
        assert list(csv.DictReader(stream)) == [{"a": "2", "b": "3"}]
    assert list(tmp_path.iterdir()) == [second.path]


def test_export_report_csv_cleans_temp_on_write_failure(tmp_path, monkeypatch) -> None:
    def failing_writer(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(csv, "writer", failing_writer)
    with pytest.raises(OSError, match="disk full"):
        export_report_csv([{"a": 1}], output_dir=tmp_path, report_name="fail")

    assert list(tmp_path.iterdir()) == []


def test_export_report_csv_keeps_existing_file_when_verification_fails(tmp_path, monkeypatch) -> None:
    existing = tmp_path / "keep.csv"
    existing.write_text("old content", encoding="utf-8")

    def failing_verify(path, expected_header):
        raise ValueError("verification failed")

    monkeypatch.setattr("services.aras_export._verify_csv", failing_verify)
    with pytest.raises(ValueError, match="verification failed"):
        export_report_csv([{"a": 1}], output_dir=tmp_path, report_name="keep")

    assert existing.read_text(encoding="utf-8") == "old content"
    assert list(tmp_path.iterdir()) == [existing]
