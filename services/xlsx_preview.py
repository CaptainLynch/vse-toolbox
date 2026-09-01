"""Small, dependency-free XLSX table reader for bounded WebUI previews."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile


class XLSXPreviewError(ValueError):
    """Raised when an official workbook cannot be safely read for preview."""


@dataclass(frozen=True)
class XLSXPreview:
    sheet_name: str
    sheet_names: tuple[str, ...]
    rows: list[list[object | None]]
    truncated: bool


_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_CELL_REF_RE = re.compile(r"^([A-Za-z]+)")
_MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
_MAX_MEMBER_BYTES = 32 * 1024 * 1024


def _tag(name: str) -> str:
    return f"{{{_MAIN}}}{name}"


def _column_index(reference: str) -> int:
    match = _CELL_REF_RE.match(reference)
    if match is None:
        raise XLSXPreviewError(f"invalid cell reference: {reference}")
    value = 0
    for char in match.group(1).upper():
        value = value * 26 + ord(char) - ord("A") + 1
    return value - 1


def _relationship_target(target: str) -> str:
    normalized = posixpath.normpath(posixpath.join("xl", target))
    if normalized.startswith("../") or not normalized.startswith("xl/"):
        raise XLSXPreviewError("workbook relationship escapes the XLSX package")
    return normalized


def _read_shared_strings(archive: ZipFile) -> list[str]:
    try:
        raw = _read_member(archive, "xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    result: list[str] = []
    for item in root.findall(_tag("si")):
        result.append("".join(text.text or "" for text in item.iter(_tag("t"))))
    return result


def _read_member(archive: ZipFile, name: str) -> bytes:
    try:
        info = archive.getinfo(name)
    except KeyError:
        raise
    if info.file_size > _MAX_MEMBER_BYTES:
        raise XLSXPreviewError(f"XLSX member is too large: {name}")
    return archive.read(name)


def _read_cell_value(cell: ET.Element, shared_strings: list[str]) -> object | None:
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.iter(_tag("t")))
    value_node = cell.find(_tag("v"))
    if value_node is None:
        return None
    raw = value_node.text or ""
    if cell_type == "s":
        try:
            return shared_strings[int(raw)]
        except (IndexError, ValueError) as exc:
            raise XLSXPreviewError("invalid shared string index") from exc
    if cell_type == "b":
        return raw == "1"
    return raw


def _read_sheet_names_and_paths(archive: ZipFile) -> tuple[tuple[str, str], ...]:
    workbook = ET.fromstring(_read_member(archive, "xl/workbook.xml"))
    relationships = ET.fromstring(_read_member(archive, "xl/_rels/workbook.xml.rels"))
    targets = {
        relation.get("Id"): relation.get("Target")
        for relation in relationships.findall(f"{{{_PACKAGE_REL}}}Relationship")
    }
    result: list[tuple[str, str]] = []
    for sheet in workbook.findall(f"{{{_MAIN}}}sheets/{{{_MAIN}}}sheet"):
        name = sheet.get("name") or ""
        relation_id = sheet.get(f"{{{_DOC_REL}}}id")
        target = targets.get(relation_id)
        if not name or not target:
            continue
        result.append((name, _relationship_target(target)))
    if not result:
        raise XLSXPreviewError("workbook contains no readable worksheets")
    return tuple(result)


def _read_sheet_rows(
    archive: ZipFile,
    sheet_path: str,
    shared_strings: list[str],
    *,
    max_rows: int,
    max_columns: int,
) -> tuple[list[list[object | None]], bool]:
    root = ET.fromstring(_read_member(archive, sheet_path))
    rows: list[list[object | None]] = []
    truncated = False
    for row_node in root.findall(f".//{{{_MAIN}}}sheetData/{{{_MAIN}}}row"):
        if len(rows) >= max_rows:
            truncated = True
            break
        values: list[object | None] = []
        for cell in row_node.findall(_tag("c")):
            reference = cell.get("r") or ""
            column = _column_index(reference)
            if column >= max_columns:
                truncated = True
                continue
            if len(values) <= column:
                values.extend([None] * (column + 1 - len(values)))
            values[column] = _read_cell_value(cell, shared_strings)
        rows.append(values)
    return rows, truncated


def read_xlsx_preview(
    path: Path,
    *,
    max_rows: int = 500,
    max_columns: int = 200,
) -> XLSXPreview:
    """Read the first worksheet with strict size limits and no third-party dependency."""
    return read_xlsx_workbook_preview(
        path,
        max_rows=max_rows,
        max_columns=max_columns,
    )[0]


def read_xlsx_workbook_preview(
    path: Path,
    *,
    max_rows: int = 500,
    max_columns: int = 200,
) -> tuple[XLSXPreview, ...]:
    """Read every worksheet with strict size limits and no third-party dependency."""
    if max_rows <= 0 or max_columns <= 0:
        raise ValueError("preview limits must be positive")
    target = Path(path)
    try:
        if target.stat().st_size > _MAX_ARCHIVE_BYTES:
            raise XLSXPreviewError("workbook is too large for a WebUI preview")
        with ZipFile(target) as archive:
            sheet_pairs = _read_sheet_names_and_paths(archive)
            shared_strings = _read_shared_strings(archive)
            previews: list[XLSXPreview] = []
            for sheet_name, sheet_path in sheet_pairs:
                rows, truncated = _read_sheet_rows(
                    archive,
                    sheet_path,
                    shared_strings,
                    max_rows=max_rows,
                    max_columns=max_columns,
                )
                previews.append(
                    XLSXPreview(
                        sheet_name=sheet_name,
                        sheet_names=tuple(name for name, _ in sheet_pairs),
                        rows=rows,
                        truncated=truncated,
                    )
                )
    except (BadZipFile, ET.ParseError, KeyError, OSError) as exc:
        raise XLSXPreviewError(f"unable to read workbook preview: {type(exc).__name__}") from exc
    return tuple(previews)


__all__ = [
    "XLSXPreview",
    "XLSXPreviewError",
    "read_xlsx_preview",
    "read_xlsx_workbook_preview",
]
