"""Safe full-result XLSX exports for Aras EWO and PAA reports."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import uuid
import zipfile
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence
from xml.etree import ElementTree
from xml.sax.saxutils import escape as xml_escape

from core.config import OUTPUT_DIR
from core.redaction import redact_sensitive_text
from services.aras_crawler import (
    DEFAULT_EWO_SELECT_FIELDS,
    DEFAULT_PAA_SELECT_FIELDS,
    ArasCrawlerClient,
    ArasCrawlerDeadlineExceeded,
    ArasCrawlerSessionExpired,
    EWOReportFilters,
    PAAReportFilters,
)
from services.aras_browser_transport import (
    ALLOWED_CATEGORIES as BROWSER_ALLOWED_CATEGORIES,
    ALLOWED_STAGES as BROWSER_ALLOWED_STAGES,
    CAP_ALL as BROWSER_CAP_ALL,
    BrowserTransportError,
)

logger = logging.getLogger("vse_toolbox.aras_report_export")

DEFAULT_EXPORT_PAGE_SIZE = 50
DEFAULT_EXPORT_MAX_PAGES = 500
DEFAULT_EXPORT_MAX_RECORDS = 12000
DEFAULT_EXPORT_TIMEOUT_SECONDS = 300.0

_SENSITIVE_COLUMN_NAMES = {
    "api_key",
    "apikey",
    "arasauth",
    "authorization",
    "cookie",
    "csrf",
    "file_id",
    "jsessionid",
    "password",
    "raw_xml",
    "secret",
    "session",
    "sessionid",
    "set_cookie",
    "sid",
    "token",
}

_EXCEL_COM_UNAVAILABLE_HRESULTS = {
    0x800401F3,  # CO_E_CLASSSTRING
    0x80040154,  # REGDB_E_CLASSNOTREG
}

_OOXML_REQUIRED_MEMBERS = frozenset(
    {
        "[Content_Types].xml",
        "_rels/.rels",
        "docProps/app.xml",
        "docProps/core.xml",
        "xl/workbook.xml",
        "xl/_rels/workbook.xml.rels",
        "xl/styles.xml",
        "xl/worksheets/sheet1.xml",
    }
)


@dataclass(frozen=True)
class ArasReportExportResult:
    """Summary of a completed or explicitly partial local export."""

    module: str
    status: str
    count: int
    file_name: str
    saved_path: Path
    stop_reason: str
    limit_reached: bool
    pages_fetched: int
    duplicates_removed: int


@dataclass(frozen=True)
class _CrawlResult:
    rows: list[dict[str, str | None]]
    status: str
    stop_reason: str
    limit_reached: bool
    pages_fetched: int
    duplicates_removed: int


class ArasReportExportError(RuntimeError):
    """Stable, credential-free failure raised by full report exports."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int = 500,
        stage: str | None = None,
        category: str | None = None,
        capability_mask: int = 0,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.stage = stage if stage in BROWSER_ALLOWED_STAGES else None
        self.category = (
            category if category in BROWSER_ALLOWED_CATEGORIES else None
        )
        self.capability_mask = (
            int(capability_mask) & BROWSER_CAP_ALL
            if isinstance(capability_mask, int)
            and not isinstance(capability_mask, bool)
            else 0
        )
        self.retryable = False


class _ExcelComCapabilityUnavailable(RuntimeError):
    """Internal signal for the narrowly approved stdlib XLSX fallback."""


def export_ewo_report(
    client: ArasCrawlerClient,
    filters: EWOReportFilters,
    *,
    max_pages: int = DEFAULT_EXPORT_MAX_PAGES,
    max_records: int = DEFAULT_EXPORT_MAX_RECORDS,
    timeout_seconds: float = DEFAULT_EXPORT_TIMEOUT_SECONDS,
) -> ArasReportExportResult:
    """Fetch every matching EWO page and export the stable fields to XLSX."""
    return _export_report(
        module="ewo",
        client=client,
        filters=filters,
        query_page=client.query_ewo_report,
        columns=DEFAULT_EWO_SELECT_FIELDS,
        max_pages=max_pages,
        max_records=max_records,
        timeout_seconds=timeout_seconds,
    )


def export_paa_report(
    client: ArasCrawlerClient,
    filters: PAAReportFilters | None = None,
    *,
    max_pages: int = DEFAULT_EXPORT_MAX_PAGES,
    max_records: int = DEFAULT_EXPORT_MAX_RECORDS,
    timeout_seconds: float = DEFAULT_EXPORT_TIMEOUT_SECONDS,
) -> ArasReportExportResult:
    """Fetch every matching PAA page and export the stable fields to XLSX."""
    return _export_report(
        module="paa",
        client=client,
        filters=filters or PAAReportFilters(),
        query_page=client.query_paa_report,
        columns=DEFAULT_PAA_SELECT_FIELDS,
        max_pages=max_pages,
        max_records=max_records,
        timeout_seconds=timeout_seconds,
    )


def _export_report(
    *,
    module: str,
    client: ArasCrawlerClient,
    filters: EWOReportFilters | PAAReportFilters,
    query_page: Callable[..., Any],
    columns: Sequence[str],
    max_pages: int,
    max_records: int,
    timeout_seconds: float,
) -> ArasReportExportResult:
    _validate_limits(max_pages, max_records, timeout_seconds)
    deadline = time.monotonic() + timeout_seconds
    scope_factory = getattr(client, "begin_full_export_scope", None)
    scope = (
        scope_factory(
            module,
            filters,
            max_pages=max_pages,
            max_records=max_records,
            deadline=deadline,
        )
        if callable(scope_factory)
        else nullcontext()
    )
    with scope:
        crawl = _crawl_all(
            client=client,
            filters=filters,
            query_page=query_page,
            max_pages=max_pages,
            max_records=max_records,
            deadline=deadline,
        )
    if time.monotonic() >= deadline:
        raise ArasReportExportError(
            "EXPORT_TIMEOUT",
            "The report export exceeded its total time limit.",
            http_status=504,
        )

    stable_columns = _stable_safe_columns(columns)
    final_path, reservation_path = _reserve_output_path(module, crawl.status)
    temp_path = final_path.with_name(
        f".{final_path.stem}.{uuid.uuid4().hex}.tmp{final_path.suffix}"
    )
    try:
        _write_xlsx(temp_path, module, stable_columns, crawl.rows)
        os.replace(temp_path, final_path)
    except ArasReportExportError:
        raise
    except Exception as exc:
        logger.warning("Aras %s XLSX export failed: %s", module.upper(), type(exc).__name__)
        raise ArasReportExportError(
            "FILE_WRITE_FAILED",
            "The local Excel export file could not be written.",
        ) from exc
    finally:
        _safe_unlink(temp_path)
        _safe_unlink(reservation_path)

    return ArasReportExportResult(
        module=module,
        status=crawl.status,
        count=len(crawl.rows),
        file_name=final_path.name,
        saved_path=final_path.resolve(),
        stop_reason=crawl.stop_reason,
        limit_reached=crawl.limit_reached,
        pages_fetched=crawl.pages_fetched,
        duplicates_removed=crawl.duplicates_removed,
    )


def _crawl_all(
    *,
    client: ArasCrawlerClient,
    filters: EWOReportFilters | PAAReportFilters,
    query_page: Callable[..., Any],
    max_pages: int,
    max_records: int,
    deadline: float,
) -> _CrawlResult:
    rows: list[dict[str, str | None]] = []
    seen_records: set[str] = set()
    seen_pages: set[str] = set()
    duplicates_removed = 0
    pages_fetched = 0
    scanned_records = 0
    max_scanned_records = min(
        max_pages * DEFAULT_EXPORT_PAGE_SIZE,
        max(DEFAULT_EXPORT_PAGE_SIZE, max_records * 10),
    )
    original_timeout = client.timeout
    original_deadline = client._request_deadline
    request_timeout = original_timeout if original_timeout > 0 else 30.0
    client._request_deadline = deadline

    try:
        for page_number in range(1, max_pages + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ArasReportExportError(
                    "EXPORT_TIMEOUT",
                    "The report export exceeded its total time limit.",
                    http_status=504,
                )
            client.timeout = max(0.1, min(request_timeout, remaining))
            try:
                page = query_page(
                    filters,
                    page=page_number,
                    page_size=DEFAULT_EXPORT_PAGE_SIZE,
                    max_records=max_records,
                )
            except ArasReportExportError:
                raise
            except BrowserTransportError as exc:
                raise ArasReportExportError(
                    exc.code,
                    "The browser-local Aras report request failed.",
                    http_status=exc.http_status,
                    stage=exc.stage,
                    category=exc.category,
                    capability_mask=exc.capability_mask,
                ) from None
            except ArasCrawlerDeadlineExceeded as exc:
                raise ArasReportExportError(
                    "EXPORT_TIMEOUT",
                    "The report export exceeded its total time limit.",
                    http_status=504,
                ) from exc
            except ArasCrawlerSessionExpired as exc:
                raise ArasReportExportError(
                    "SESSION_EXPIRED",
                    "The Aras account session expired during export; authenticate again and retry once.",
                    http_status=401,
                ) from exc
            except Exception as exc:
                if time.monotonic() >= deadline:
                    raise ArasReportExportError(
                        "EXPORT_TIMEOUT",
                        "The report export exceeded its total time limit.",
                        http_status=504,
                    ) from exc
                logger.warning("Aras export page request failed: %s", type(exc).__name__)
                raise ArasReportExportError(
                    "UPSTREAM_REQUEST_FAILED",
                    "The Aras report request failed; verify the connection and temporary credentials.",
                    http_status=502,
                ) from exc

            pages_fetched += 1
            raw_page_rows = [_clean_row(row) for row in page.rows]
            if not raw_page_rows:
                return _CrawlResult(
                    rows, "completed", "empty_page", False, pages_fetched, duplicates_removed
                )

            aligned_ids = page.item_ids if len(page.item_ids) == len(raw_page_rows) else []
            page_signature = _page_signature(raw_page_rows, aligned_ids)
            if page_signature in seen_pages:
                duplicates_removed += sum(
                    1 for row in raw_page_rows if row_matches_filters(module_for_filters(filters), row, filters)
                )
                return _CrawlResult(
                    rows, "partial", "repeated_page", False, pages_fetched, duplicates_removed
                )
            seen_pages.add(page_signature)

            scanned_records += len(raw_page_rows)
            page_rows_with_ids = [
                (row, aligned_ids[index] if aligned_ids else "")
                for index, row in enumerate(raw_page_rows)
                if row_matches_filters(module_for_filters(filters), row, filters)
            ]

            record_limit_hit = False
            for row, item_id in page_rows_with_ids:
                key = _record_key(row, item_id)
                if key in seen_records:
                    duplicates_removed += 1
                    continue
                if len(rows) >= max_records:
                    record_limit_hit = True
                    break
                seen_records.add(key)
                rows.append(row)

            if record_limit_hit or len(rows) >= max_records:
                return _CrawlResult(
                    rows, "partial", "max_records", True, pages_fetched, duplicates_removed
                )
            if len(raw_page_rows) < DEFAULT_EXPORT_PAGE_SIZE:
                return _CrawlResult(
                    rows, "completed", "short_page", False, pages_fetched, duplicates_removed
                )
            if page_number >= max_pages:
                return _CrawlResult(
                    rows, "partial", "max_pages", True, pages_fetched, duplicates_removed
                )
            if scanned_records >= max_scanned_records:
                return _CrawlResult(
                    rows, "partial", "max_scanned_records", True, pages_fetched, duplicates_removed
                )
    finally:
        client.timeout = original_timeout
        client._request_deadline = original_deadline

    raise ArasReportExportError("EXPORT_STATE_INVALID", "The report export stopped unexpectedly.")


def _validate_limits(max_pages: int, max_records: int, timeout_seconds: float) -> None:
    if max_pages <= 0 or max_records <= 0 or timeout_seconds <= 0:
        raise ArasReportExportError(
            "INVALID_EXPORT_LIMIT",
            "Export limits must be positive numbers.",
            http_status=400,
        )


def module_for_filters(filters: EWOReportFilters | PAAReportFilters) -> str:
    return "ewo" if isinstance(filters, EWOReportFilters) else "paa"


def row_matches_filters(
    module: str,
    row: dict[str, str | None],
    filters: EWOReportFilters | PAAReportFilters,
) -> bool:
    """Deterministically recheck user-visible department/model predicates."""
    if module == "ewo" and isinstance(filters, EWOReportFilters):
        department = _normalized_filter(filters.rsp_department_keyword)
        model = _normalized_filter(filters.model_keyword)
        # ``rsp_department`` is retained for old callers.  New UI callers use
        # the explicit keyword field; when model is supplied, the legacy value
        # participates in the same required AND predicate.
        if department is None and model is not None:
            department = _normalized_filter(filters.rsp_department)
        if department is not None and department.casefold() not in _row_text(
            row, "_rsp_department"
        ).casefold():
            return False
        if model is not None and model.casefold() not in _row_text(row, "_modelinfo").casefold():
            return False
        return True
    if module == "paa" and isinstance(filters, PAAReportFilters):
        department = _normalized_filter(filters.department_keyword)
        vehicle = _normalized_filter(filters.vehicle_keyword)
        if department is not None:
            if not any(
                department.casefold() in _row_text(row, field).casefold()
                for field in ("_pe_tdc_department", "_requester_department")
            ):
                return False
        if vehicle is not None and vehicle.casefold() not in _row_text(row, "_vehicles").casefold():
            return False
        return True
    raise ArasReportExportError(
        "EXPORT_FILTER_INVALID",
        "The report filter type does not match the requested module.",
        http_status=400,
    )


def _normalized_filter(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _row_text(row: dict[str, str | None], field: str) -> str:
    value = row.get(field)
    return "" if value is None else str(value)


def _clean_row(row: dict[str, Any]) -> dict[str, str | None]:
    clean: dict[str, str | None] = {}
    for key, value in row.items():
        key_text = str(key)
        if _is_sensitive_column(key_text):
            continue
        clean[key_text] = None if value is None else redact_sensitive_text(value)
    return clean


def _stable_safe_columns(columns: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for column in columns:
        column_text = str(column)
        if column_text in seen or _is_sensitive_column(column_text):
            continue
        seen.add(column_text)
        result.append(column_text)
    return tuple(result)


def _is_sensitive_column(column: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", column.lower()).strip("_")
    if normalized in _SENSITIVE_COLUMN_NAMES:
        return True
    parts = set(normalized.split("_"))
    if "raw_xml" in normalized or "api_key" in normalized or "apikey" in normalized:
        return True
    return bool(
        parts.intersection(
            {
                "authorization",
                "cookie",
                "credential",
                "csrf",
                "password",
                "secret",
                "session",
                "sid",
                "token",
            }
        )
    )


def _record_key(row: dict[str, str | None], item_id: str | None) -> str:
    if item_id and str(item_id).strip():
        return f"id:{str(item_id).strip()}"
    business_no = row.get("_no")
    if business_no and str(business_no).strip():
        return f"no:{str(business_no).strip()}"
    return f"row:{_row_fingerprint(row)}"


def _page_signature(rows: Sequence[dict[str, str | None]], item_ids: Sequence[str]) -> str:
    identities = [
        _record_key(row, item_ids[index] if item_ids else "")
        for index, row in enumerate(rows)
    ]
    encoded = json.dumps(identities, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _row_fingerprint(row: dict[str, str | None]) -> str:
    encoded = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reserve_output_path(module: str, status: str) -> tuple[Path, Path]:
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    except (OSError, IOError) as exc:
        raise ArasReportExportError(
            "OUTPUT_DIRECTORY_UNAVAILABLE",
            "The local export directory is unavailable.",
        ) from exc

    module_name = "EWO" if module.lower() == "ewo" else "PAA"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    partial_suffix = "_PARTIAL" if status == "partial" else ""
    for index in range(1, 10000):
        collision_suffix = "" if index == 1 else f"_{index}"
        path = OUTPUT_DIR / f"{module_name}_{timestamp}{collision_suffix}{partial_suffix}.xlsx"
        reservation = path.with_suffix(path.suffix + ".lock")
        try:
            descriptor = os.open(reservation, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(descriptor)
        except FileExistsError:
            continue
        except OSError as exc:
            raise ArasReportExportError(
                "OUTPUT_DIRECTORY_UNAVAILABLE",
                "The local export directory is unavailable.",
            ) from exc
        if path.exists():
            _safe_unlink(reservation)
            continue
        return path, reservation
    raise ArasReportExportError(
        "OUTPUT_NAME_UNAVAILABLE",
        "A unique local export file name could not be allocated.",
    )


def _write_xlsx(
    path: Path,
    module: str,
    columns: Sequence[str],
    rows: Sequence[dict[str, str | None]],
) -> None:
    try:
        _write_xlsx_with_excel_com(path, module, columns, rows)
        return
    except _ExcelComCapabilityUnavailable:
        logger.info("Excel COM capability unavailable; using scoped Aras OOXML writer")

    try:
        _write_xlsx_with_stdlib_ooxml(path, module, columns, rows)
    except ArasReportExportError:
        raise
    except Exception as exc:
        logger.warning("Aras stdlib XLSX export failed: %s", type(exc).__name__)
        raise ArasReportExportError(
            "FILE_WRITE_FAILED",
            "The local Excel export file could not be written.",
        ) from exc


def _write_xlsx_with_excel_com(
    path: Path,
    module: str,
    columns: Sequence[str],
    rows: Sequence[dict[str, str | None]],
) -> None:
    excel_client, pythoncom = _excel_runtime()
    excel = None
    workbook = None
    com_initialized = False
    try:
        if pythoncom is not None:
            pythoncom.CoInitialize()
            com_initialized = True
        dispatch = getattr(excel_client, "DispatchEx", excel_client.Dispatch)
        try:
            excel = dispatch("Excel.Application")
        except Exception as exc:
            if _is_excel_com_capability_unavailable(exc):
                raise _ExcelComCapabilityUnavailable() from exc
            raise
        excel.Visible = False
        excel.DisplayAlerts = False
        workbook = excel.Workbooks.Add()
        sheet = workbook.ActiveSheet
        sheet.Name = module.upper()

        header_values = tuple(columns)
        header_range = sheet.Range(sheet.Cells(1, 1), sheet.Cells(1, len(header_values)))
        header_range.Value = (header_values,)
        header_range.Font.Bold = True

        if rows:
            matrix = tuple(
                tuple(_excel_value(row.get(column)) for column in header_values)
                for row in rows
            )
            data_range = sheet.Range(
                sheet.Cells(2, 1),
                sheet.Cells(len(rows) + 1, len(header_values)),
            )
            data_range.NumberFormat = "@"
            data_range.Value = matrix
        sheet.Columns.AutoFit()
        workbook.SaveAs(str(path.resolve()), FileFormat=51)
    except (_ExcelComCapabilityUnavailable, ArasReportExportError):
        raise
    except Exception as exc:
        raise ArasReportExportError(
            "FILE_WRITE_FAILED",
            "The local Excel export file could not be written.",
        ) from exc
    finally:
        if workbook is not None:
            try:
                workbook.Close(SaveChanges=False)
            except Exception:
                logger.warning("Excel workbook cleanup failed")
        if excel is not None:
            try:
                excel.Quit()
            except Exception:
                logger.warning("Excel process cleanup failed")
        if com_initialized and pythoncom is not None:
            pythoncom.CoUninitialize()


def _excel_runtime() -> tuple[Any, Any | None]:
    try:
        import win32com.client as excel_client
    except ImportError as exc:
        raise _ExcelComCapabilityUnavailable() from exc
    try:
        import pythoncom
    except ImportError:
        pythoncom = None
    return excel_client, pythoncom


def _is_excel_com_capability_unavailable(exc: BaseException) -> bool:
    hresult = getattr(exc, "hresult", None)
    return isinstance(hresult, int) and (hresult & 0xFFFFFFFF) in _EXCEL_COM_UNAVAILABLE_HRESULTS


def _write_xlsx_with_stdlib_ooxml(
    path: Path,
    module: str,
    columns: Sequence[str],
    rows: Sequence[dict[str, str | None]],
) -> None:
    sheet_name = module.upper()
    if sheet_name not in {"EWO", "PAA"} or not columns:
        raise ValueError("Invalid Aras worksheet contract")
    if len(columns) > 16384 or len(rows) + 1 > 1048576:
        raise ValueError("Aras worksheet exceeds XLSX limits")

    package_parts = {
        "[Content_Types].xml": _ooxml_content_types(),
        "_rels/.rels": _ooxml_package_relationships(),
        "docProps/app.xml": _ooxml_app_properties(),
        "docProps/core.xml": _ooxml_core_properties(),
        "xl/workbook.xml": _ooxml_workbook(sheet_name),
        "xl/_rels/workbook.xml.rels": _ooxml_workbook_relationships(),
        "xl/styles.xml": _ooxml_styles(),
    }
    with zipfile.ZipFile(path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member_name, content in package_parts.items():
            archive.writestr(member_name, content)
        with archive.open("xl/worksheets/sheet1.xml", mode="w") as sheet:
            _stream_ooxml_sheet(sheet, columns, rows)

    _validate_stdlib_ooxml(path)


def _stream_ooxml_sheet(
    output: Any,
    columns: Sequence[str],
    rows: Sequence[dict[str, str | None]],
) -> None:
    last_column = _xlsx_column_name(len(columns))
    last_row = len(rows) + 1
    output.write(
        (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<dimension ref="A1:{last_column}{last_row}"/>'
            '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
            '<sheetFormatPr defaultRowHeight="15"/>'
            f'<cols><col min="1" max="{len(columns)}" width="18" customWidth="1"/></cols>'
            "<sheetData>"
        ).encode("utf-8")
    )
    _write_ooxml_row(output, 1, columns, style_id=1)
    for row_number, row in enumerate(rows, start=2):
        _write_ooxml_row(
            output,
            row_number,
            (row.get(column) for column in columns),
            style_id=2,
        )
    output.write(b"</sheetData></worksheet>")


def _write_ooxml_row(
    output: Any,
    row_number: int,
    values: Any,
    *,
    style_id: int,
) -> None:
    output.write(f'<row r="{row_number}">'.encode("ascii"))
    for column_number, value in enumerate(values, start=1):
        reference = f"{_xlsx_column_name(column_number)}{row_number}"
        text = xml_escape(_xml_safe_excel_value(value))
        output.write(
            (
                f'<c r="{reference}" s="{style_id}" t="inlineStr">'
                f'<is><t xml:space="preserve">{text}</t></is></c>'
            ).encode("utf-8")
        )
    output.write(b"</row>")


def _xlsx_column_name(column_number: int) -> str:
    if column_number < 1 or column_number > 16384:
        raise ValueError("Invalid XLSX column number")
    result: list[str] = []
    while column_number:
        column_number, remainder = divmod(column_number - 1, 26)
        result.append(chr(65 + remainder))
    return "".join(reversed(result))


def _xml_safe_excel_value(value: Any) -> str:
    text = _excel_value(value)
    return "".join(
        character
        for character in text
        if character in "\t\n\r"
        or 0x20 <= ord(character) <= 0xD7FF
        or 0xE000 <= ord(character) <= 0xFFFD
        or 0x10000 <= ord(character) <= 0x10FFFF
    )


def _validate_stdlib_ooxml(path: Path) -> None:
    with zipfile.ZipFile(path, mode="r") as archive:
        member_names = archive.namelist()
        if (
            len(member_names) != len(set(member_names))
            or set(member_names) != _OOXML_REQUIRED_MEMBERS
            or archive.testzip() is not None
        ):
            raise ValueError("Invalid XLSX package")
        for member_name in member_names:
            if member_name.endswith(".xml") or member_name.endswith(".rels"):
                ElementTree.fromstring(archive.read(member_name))


def _ooxml_content_types() -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    ).encode("utf-8")


def _ooxml_package_relationships() -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
        "</Relationships>"
    ).encode("utf-8")


def _ooxml_app_properties() -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        "<Application>VSE Toolbox</Application>"
        "</Properties>"
    ).encode("utf-8")


def _ooxml_core_properties() -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<dc:creator>VSE Toolbox</dc:creator>"
        "</cp:coreProperties>"
    ).encode("utf-8")


def _ooxml_workbook(sheet_name: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="'
        + sheet_name
        + '" sheetId="1" r:id="rId1"/></sheets></workbook>'
    ).encode("utf-8")


def _ooxml_workbook_relationships() -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        "</Relationships>"
    ).encode("utf-8")


def _ooxml_styles() -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="3">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="49" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1" applyNumberFormat="1"/>'
        '<xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        "</cellXfs>"
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>"
    ).encode("utf-8")


def _excel_value(value: Any) -> str:
    if value is None:
        return ""
    text = redact_sensitive_text(value, limit=32767)
    if text.startswith(("=", "+", "-", "@")):
        text = "'" + text
    return text[:32767]


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Temporary Aras export file cleanup failed")
