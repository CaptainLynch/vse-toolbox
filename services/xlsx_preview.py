"""Small, dependency-free XLSX table reader for bounded WebUI previews."""

from __future__ import annotations

from core.diagnostic_recording import observed

import io
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile


#: 公司终端 DLP「容器化」落盘后，非受信进程读到的文件头（明文 + 1024 字节头）。
#: 只做**前缀匹配**，绝不据此剥头/解密；日后指纹变化只需在此追加。
ENCRYPTED_CONTAINER_SIGNATURES: tuple[bytes, ...] = (
    b"\x17\xda\x5f\xa0\x16\x33\xcd\x9a\xbc\x5b\x6c\xbf\x14\xaa\x1e\x33",
)
#: OOXML 包的 zip 头（普通归档 / 空归档 / 分卷结束标记）。
ZIP_SIGNATURES: tuple[bytes, ...] = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
#: 旧版 .xls/.doc 的 OLE2 复合文档头。
OLE_SIGNATURE: bytes = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
#: 嗅探读取的字节数（容器头 16 字节、zip/OLE 头均不超过 16 字节）。
SNIFF_BYTES = 16

#: 嗅探结果闭集。
FILE_KIND_EMPTY_OR_TRUNCATED = "empty_or_truncated"
FILE_KIND_ZIP = "zip"
FILE_KIND_OLE_CONTAINER = "ole_container"
FILE_KIND_ENCRYPTED_CONTAINER = "encrypted_container"
FILE_KIND_UNKNOWN_BINARY = "unknown_binary"
FILE_KIND_UNREADABLE = "unreadable"
FILE_KINDS = (
    FILE_KIND_EMPTY_OR_TRUNCATED,
    FILE_KIND_ZIP,
    FILE_KIND_OLE_CONTAINER,
    FILE_KIND_ENCRYPTED_CONTAINER,
    FILE_KIND_UNKNOWN_BINARY,
)

#: 失败原因闭集（服务端 error.diagnostic.reason 与 CLI 文案共用同一套词）。
REASON_ENCRYPTED_CONTAINER = FILE_KIND_ENCRYPTED_CONTAINER
REASON_OLE_CONTAINER = FILE_KIND_OLE_CONTAINER
REASON_EMPTY_OR_TRUNCATED = FILE_KIND_EMPTY_OR_TRUNCATED
REASON_UNKNOWN_BINARY = FILE_KIND_UNKNOWN_BINARY
REASON_CORRUPT_ZIP = "corrupt_zip"
REASON_SCHEMA_MISMATCH = "schema_mismatch"
REASON_UNREADABLE = FILE_KIND_UNREADABLE
#: Excel「另存为文本」的 TAB 文本（services/tdc_text_rows.py）专用的两个词：
#: 编码认不出来（含改了扩展名的二进制）/ 引号或列结构不完整。
REASON_TEXT_ENCODING = "text_encoding"
REASON_TEXT_MALFORMED = "text_malformed"
REASONS = (
    REASON_ENCRYPTED_CONTAINER,
    REASON_OLE_CONTAINER,
    REASON_EMPTY_OR_TRUNCATED,
    REASON_UNKNOWN_BINARY,
    REASON_CORRUPT_ZIP,
    REASON_SCHEMA_MISMATCH,
    REASON_UNREADABLE,
    REASON_TEXT_ENCODING,
    REASON_TEXT_MALFORMED,
)


def sniff_file_kind(head: bytes, size: int) -> str:
    """按文件头与大小判定形态；纯标准库、只看前缀，不做任何解密/剥头。

    head 是调用方按**自身进程视图**读到的前若干字节（建议 SNIFF_BYTES），
    size 是该视图下的总大小。返回值是 FILE_KINDS 之一。
    """
    if size <= 0 or len(head) < SNIFF_BYTES or size < SNIFF_BYTES:
        return FILE_KIND_EMPTY_OR_TRUNCATED
    probe = bytes(head[:SNIFF_BYTES])
    if any(probe.startswith(signature) for signature in ENCRYPTED_CONTAINER_SIGNATURES):
        return FILE_KIND_ENCRYPTED_CONTAINER
    if any(probe.startswith(signature) for signature in ZIP_SIGNATURES):
        return FILE_KIND_ZIP
    if probe.startswith(OLE_SIGNATURE):
        return FILE_KIND_OLE_CONTAINER
    return FILE_KIND_UNKNOWN_BINARY


class XLSXPreviewError(ValueError):
    """Raised when an official workbook cannot be safely read for preview.

    reason 是闭集词（见 REASONS），用于把「受终端加密」「损坏」与「格式不符」
    区分开；调用方只按它映射用户文案，不解析异常原文。
    """

    def __init__(self, message: str, *, reason: str = "unreadable") -> None:
        super().__init__(message)
        self.reason = reason


class XLSXEncryptedContent(XLSXPreviewError):
    """工作簿内容是终端加密容器（明文 + 1024 字节头），本进程读不到真实内容。

    这是**部署/终端环境**问题，不是文件损坏：不要据此剥头、不要重试、
    也不要探测偏移 1024 后是否为 PK。
    """

    def __init__(
        self,
        message: str = "workbook is a terminal-encrypted container",
        *,
        reason: str = REASON_ENCRYPTED_CONTAINER,
    ) -> None:
        super().__init__(message, reason=reason)


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
_MAX_MEMBER_BYTES = 64 * 1024 * 1024
_MAX_TOTAL_MEMBER_BYTES = 96 * 1024 * 1024


def _tag(name: str) -> str:
    return f"{{{_MAIN}}}{name}"


def _column_index(reference: str) -> int:
    match = _CELL_REF_RE.match(reference)
    if match is None:
        raise XLSXPreviewError(f"invalid cell reference: {reference}", reason=REASON_CORRUPT_ZIP)
    value = 0
    for char in match.group(1).upper():
        value = value * 26 + ord(char) - ord("A") + 1
    return value - 1


def _relationship_target(target: str) -> str:
    normalized = posixpath.normpath(posixpath.join("xl", target))
    if normalized.startswith("../") or not normalized.startswith("xl/"):
        raise XLSXPreviewError(
            "workbook relationship escapes the XLSX package", reason=REASON_CORRUPT_ZIP
        )
    return normalized


def _parse_member_xml(raw: bytes) -> ET.Element:
    if len(raw) > _MAX_MEMBER_BYTES:
        raise XLSXPreviewError("XLSX member exceeds size limit", reason=REASON_UNREADABLE)
    raw_upper = raw.upper()
    if b"<!DOCTYPE" in raw_upper or b"<!ENTITY" in raw_upper:
        raise XLSXPreviewError(
            "XLSX member contains entity declarations", reason=REASON_CORRUPT_ZIP
        )
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise XLSXPreviewError(
            "failed to parse XLSX XML member", reason=REASON_CORRUPT_ZIP
        ) from exc


def _read_shared_strings(archive: ZipFile) -> list[str]:
    try:
        raw = _read_member(archive, "xl/sharedStrings.xml")
    except KeyError:
        return []
    root = _parse_member_xml(raw)
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
        raise XLSXPreviewError(f"XLSX member is too large: {name}", reason=REASON_UNREADABLE)
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
            raise XLSXPreviewError("invalid shared string index", reason=REASON_CORRUPT_ZIP) from exc
    if cell_type == "b":
        return raw == "1"
    return raw


def _read_sheet_names_and_paths(archive: ZipFile) -> tuple[tuple[str, str], ...]:
    workbook = _parse_member_xml(_read_member(archive, "xl/workbook.xml"))
    relationships = _parse_member_xml(_read_member(archive, "xl/_rels/workbook.xml.rels"))
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
        raise XLSXPreviewError(
            "workbook contains no readable worksheets", reason=REASON_CORRUPT_ZIP
        )
    return tuple(result)


def _read_sheet_rows(
    archive: ZipFile,
    sheet_path: str,
    shared_strings: list[str],
    *,
    max_rows: int,
    max_columns: int,
) -> tuple[list[list[object | None]], bool]:
    root = _parse_member_xml(_read_member(archive, sheet_path))
    rows: list[list[object | None]] = []
    truncated = False
    for row_node in root.findall(f".//{{{_MAIN}}}sheetData/{{{_MAIN}}}row"):
        if len(rows) >= max_rows:
            truncated = True
            break
        values: list[object | None] = []
        current_column = 0
        for cell in row_node.findall(_tag("c")):
            reference = cell.get("r")
            if reference:
                column = _column_index(reference)
                current_column = column + 1
            else:
                column = current_column
                current_column += 1
            if column >= max_columns:
                truncated = True
                continue
            if len(values) <= column:
                values.extend([None] * (column + 1 - len(values)))
            values[column] = _read_cell_value(cell, shared_strings)
        rows.append(values)
    return rows, truncated


@observed("preview.read_xlsx_preview")
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


@observed("preview.read_xlsx_workbook_preview")
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
        size = target.stat().st_size
        if size > _MAX_ARCHIVE_BYTES:
            raise XLSXPreviewError(
                "workbook is too large for a WebUI preview", reason=REASON_UNREADABLE
            )
        with target.open("rb") as handle:
            head = handle.read(SNIFF_BYTES)
        return _read_workbook_previews(
            target, head, size, max_rows=max_rows, max_columns=max_columns
        )
    except OSError as exc:
        raise XLSXPreviewError(
            f"unable to read workbook preview: {type(exc).__name__}",
            reason=REASON_CORRUPT_ZIP,
        ) from exc


def read_xlsx_preview_bytes(
    data: bytes,
    *,
    max_rows: int = 500,
    max_columns: int = 200,
) -> XLSXPreview:
    """同 read_xlsx_preview，但直接读**内存里的字节**：不落临时文件。

    故意不挂 @observed：诊断录制会把入参原样记下来，这里的入参就是文件内容。
    """
    if max_rows <= 0 or max_columns <= 0:
        raise ValueError("preview limits must be positive")
    if len(data) > _MAX_ARCHIVE_BYTES:
        raise XLSXPreviewError(
            "workbook is too large for a WebUI preview", reason=REASON_UNREADABLE
        )
    return _read_workbook_previews(
        io.BytesIO(data),
        bytes(data[:SNIFF_BYTES]),
        len(data),
        max_rows=max_rows,
        max_columns=max_columns,
    )[0]


def _read_workbook_previews(
    source: Path | io.BytesIO,
    head: bytes,
    size: int,
    *,
    max_rows: int,
    max_columns: int,
) -> tuple[XLSXPreview, ...]:
    """路径与内存字节共用的读取主体（source 交给 ZipFile，两种都认）。"""
    try:
        # 先按**本进程视图**嗅探：公司终端加密容器要在这里就停下，绝不打开 zip、
        # 绝不探测偏移 1024 处是否为 PK、绝不剥头（那等于实现解密）。
        kind = sniff_file_kind(head, size)
        if kind == FILE_KIND_ENCRYPTED_CONTAINER:
            raise XLSXEncryptedContent()
        if kind != FILE_KIND_ZIP:
            raise XLSXPreviewError(
                f"workbook is not an xlsx package: {kind}", reason=kind
            )
        with ZipFile(source) as archive:
            total_member_bytes = sum(info.file_size for info in archive.infolist())
            if total_member_bytes > _MAX_TOTAL_MEMBER_BYTES:
                raise XLSXPreviewError("XLSX members are too large for a WebUI preview")
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
        raise XLSXPreviewError(
            f"unable to read workbook preview: {type(exc).__name__}",
            reason=REASON_CORRUPT_ZIP,
        ) from exc
    return tuple(previews)


__all__ = [
    "ENCRYPTED_CONTAINER_SIGNATURES",
    "FILE_KINDS",
    "REASONS",
    "SNIFF_BYTES",
    "XLSXEncryptedContent",
    "XLSXPreview",
    "XLSXPreviewError",
    "read_xlsx_preview",
    "read_xlsx_preview_bytes",
    "read_xlsx_workbook_preview",
    "sniff_file_kind",
]
