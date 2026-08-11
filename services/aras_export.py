"""Local, credential-safe exports for Aras report results."""

from __future__ import annotations

import csv
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

from core.config import OUTPUT_DIR
from core.redaction import redact_sensitive_text
from services.aras_crawler import DEFAULT_EWO_SELECT_FIELDS, EWOReportPage


_INVALID_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_FORMULA_PREFIXES = ("=", "+", "-", "@")
_SENSITIVE_COLUMNS = {
    "raw_xml",
    "authorization",
    "set_cookie",
    "cookie",
    "token",
    "api_key",
    "sid",
    "sessionid",
    "arasauth",
    "jsessionid",
    "csrf",
    "secret",
    "password",
}


@dataclass(frozen=True)
class CSVExportResult:
    path: Path
    row_count: int
    fieldnames: tuple[str, ...]


@dataclass(frozen=True)
class EWOExportResult:
    path: Path
    row_count: int
    columns: tuple[str, ...]

    @property
    def fieldnames(self) -> tuple[str, ...]:
        return self.columns


def export_report_csv(
    rows: Sequence[Mapping[str, object]],
    output_dir: Path | None = None,
    report_name: str | None = None,
    filters: Mapping[str, object] | None = None,
    preferred_fields: Sequence[str] | None = None,
) -> CSVExportResult:
    """Write rows as an Excel-compatible, credential-safe UTF-8 CSV.

    Preferred fields that actually appear are written first; remaining fields
    are appended in stable first-appearance order. The file is written
    atomically (temp file + os.replace) and re-read to verify it is non-empty
    with the expected header before it is published.
    """
    destination = Path(output_dir or OUTPUT_DIR)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / _safe_csv_name(_compose_csv_name(report_name, filters))
    columns = _select_columns(rows, preferred_fields)
    _write_csv_atomically(path, columns, rows)
    return CSVExportResult(path=path, row_count=len(rows), fieldnames=tuple(columns))


def export_ewo_report_csv(
    page: EWOReportPage,
    *,
    output_dir: Path | None = None,
    file_name: str | None = None,
    preferred_columns: Sequence[str] = DEFAULT_EWO_SELECT_FIELDS,
) -> EWOExportResult:
    """Write EWO rows as an Excel-compatible UTF-8 CSV without credential fields."""
    result = export_report_csv(
        page.rows,
        output_dir=output_dir,
        report_name=file_name or f"ewo_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        preferred_fields=preferred_columns,
    )
    return EWOExportResult(path=result.path, row_count=result.row_count, columns=result.fieldnames)


def _select_columns(
    rows: Sequence[Mapping[str, object]],
    preferred_columns: Sequence[str] | None,
) -> list[str]:
    seen: set[str] = set()
    available: list[str] = []
    for row in rows:
        for key in row:
            name = str(key)
            if not _is_sensitive_column(name) and name not in seen:
                seen.add(name)
                available.append(name)
    columns = [key for key in (preferred_columns or ()) if key in seen]
    columns.extend(key for key in available if key not in columns)
    if columns:
        return columns
    return [key for key in (preferred_columns or ()) if not _is_sensitive_column(key)]


def _write_csv_atomically(
    path: Path,
    columns: Sequence[str],
    rows: Sequence[Mapping[str, object]],
) -> None:
    temp_path: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".export_", suffix=".tmp")
        temp_path = Path(temp_name)
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(columns)
            for row in rows:
                writer.writerow(_safe_csv_value(row.get(column)) for column in columns)
        _verify_csv(temp_path, columns)
        os.replace(temp_path, path)
    except BaseException:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def _verify_csv(path: Path, expected_header: Sequence[str]) -> None:
    content = path.read_text(encoding="utf-8-sig", newline="")
    if not content:
        raise ValueError(f"refusing to publish empty export at {path}")
    header = next(csv.reader(content.splitlines()), None)
    if expected_header and header != list(expected_header):
        raise ValueError(f"export header mismatch at {path}: {header!r} != {list(expected_header)!r}")


def _safe_csv_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float, bool)):
        text = str(value)
    elif isinstance(value, str):
        text = redact_sensitive_text(value)
    else:
        text = redact_sensitive_text(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        )
    if text.lstrip().startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def _compose_csv_name(
    report_name: str | None,
    filters: Mapping[str, object] | None,
) -> str:
    parts = [report_name or "report"]
    for key, value in (filters or {}).items():
        parts.extend((str(key), str(value)))
    safe = [_safe_name_token(part) for part in parts]
    return "_".join(part for part in safe if part) or "report"


def _safe_name_token(token: str) -> str:
    token = _INVALID_FILENAME_RE.sub("_", token)
    return re.sub(r"\s+", "_", token).strip(" ._")


def _safe_csv_name(file_name: str | None) -> str:
    fallback = f"ewo_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    candidate = Path(str(file_name or fallback)).name
    candidate = _INVALID_FILENAME_RE.sub("_", candidate).strip(" .")
    if not candidate:
        candidate = fallback
    if not candidate.lower().endswith(".csv"):
        candidate += ".csv"
    if len(candidate) > 180:
        candidate = candidate[:-4][:176] + ".csv"
    return candidate


def _is_sensitive_column(name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    sensitive_parts = {"authorization", "cookie", "token", "session", "sessionid", "csrf", "secret", "password"}
    return normalized in _SENSITIVE_COLUMNS or bool(set(normalized.split("_")) & sensitive_parts)


__all__ = ["CSVExportResult", "EWOExportResult", "export_report_csv", "export_ewo_report_csv"]
