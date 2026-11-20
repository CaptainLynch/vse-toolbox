# -*- coding: utf-8 -*-
"""本地报表导入：把用户自己导出的 TDC 数模官方 xlsx 变成「一次性」日报数据源。

2026-11-11 起同时接受 Excel「另存为文本」得到的 TAB 文本（.txt）：公司终端加密的
xlsx 本进程读不到内容，用户用 Excel 自带功能导出文本后即可导入。xlsx 与 TXT
共用同一套严格校验（表头 47 列逐字、逐序），并且**全程在内存里解析**，不写临时文件。

设计口径（两轮 Astra-high 顾问定稿，见 `.runtime/sign-daily-import-plan-20261110.md`）：

- **不碰共享数据**：不读不写 `deliverable_form_snapshots`、一键生成的 TDC 快照（`snapshot_*`）、
  长周期结论与 `config`（`ReadOnlyStore` 的写方法抛错，路由传 `save_config=False`）。
- **只写自有基线（2026-11-16 起，推翻原「零写库、不计算日变化」）**：页面导入可以与此前的
  手工导入比日变化，基线只存在 `manual_baseline.ManualBaselineStore` 的自有两张表里；
  表单字段 `keepBaseline=0` 时只读基线、不写。旧数据（已有更晚日期的手工导入）不写、不显示括号。
- **基线文件（2026-11-16）**：用户指定的一份本地报表作为固定基线（备份与记录在 `manual_baseline.py`）；
  这里只负责来源声明的措辞（`baseline_statement` 的 file 模式、`BASELINE_BACKUP_GONE_TEXT`）。
- **数据日期只能人给**：不接受从运行时刻、文件修改时间或行内「申请日期」推导。
- `NullStore` 仍保留（读全空、写抛错），供需要「完全不比较」的调用方使用；离线 CLI
  （`tools/sign_daily_local_report.py`）自带一份同义实现，仍然零写库、不计算日变化。
- **表结构 fail-closed**：先按官方 47 列契约逐字校验，再校验日报 36 个必需列。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import stat
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from services import data_model_watchlist as W
from services.tdc_official_rows import (
    OfficialWorkbookContractError,
    OfficialWorkbookError,
    OfficialWorkbookTruncated,
    OfficialWorkbookUnreadable,
    check_official_header,
    official_contract_headers,
    official_rows_from_matrix,
    read_official_tdc_matrix_from_bytes,
    read_official_tdc_rows_from_bytes,
    VARIANT_IBOM,
    variant_file_headers,
)
from services.tdc_text_rows import ENCODING_GBK, text_encoding_label
from services.xlsx_preview import (
    REASON_ENCRYPTED_CONTAINER,
    REASON_SCHEMA_MISMATCH,
    REASON_TEXT_MALFORMED,
    REASON_UNREADABLE,
    REASONS,
)

from . import rules as V
from . import service as S

__all__ = [
    "DEFAULT_SUBDIR",
    "MAX_ROWS",
    "ManualImportError",
    "NullStore",
    "ReadOnlyStore",
    "SOURCE_MANUAL",
    "ScanEntry",
    "ScanResult",
    "allowed_roots",
    "baseline_statement",
    "file_sha256",
    "import_meta",
    "make_scan_token",
    "ensure_direct_child",
    "read_verified_bytes",
    "resolve_scan_dir",
    "scan_directory",
    "source_from_bytes",
    "source_from_excel",
    "source_from_file",
    "stat_signature",
    "source_format",
    "verify_scan_token",
]

#: 官方 TDC 数模工作簿的读取上限（含表头行）。
MAX_ROWS = 5001
#: 快照来源标记：只用于响应元数据，不落库。
SOURCE_MANUAL = "manual_import"
_REPORT_TYPE = "data_model"
#: 单份导入文件的字节上限（与路由上传上限一致，且低于宿主 16MB 的请求体上限）。
_MAX_IMPORT_BYTES = 15 * 1024 * 1024

# ── 用户可见文案（逐字取自 .runtime/sign-daily-encrypted-contract-20261111.md §3）──
#: 终端加密容器：文件本身没坏，只是本进程读不到内容。
ENCRYPTED_TEXT = "文件受公司终端加密保护，本功能读不到内容，文件本身没有损坏。请改用「一键生成」。"
#: 同一种文件，但 Excel 代读已开启、而文件是从页面上传的（上传入口不走代读）。
ENCRYPTED_UPLOAD_TEXT = (
    "文件受公司终端加密保护，页面上传读不到内容，文件本身没有损坏。"
    "请把它放进扫描目录，再点「扫描目录」，由本机 Excel 代读。"
)
#: 打不开的 xlsx：不区分「下载不完整」「已损坏」还是「受加密」。
DAMAGED_TEXT = "文件无法按 xlsx 打开，可能下载不完整、已损坏或受加密。请重新导出，或改用「一键生成」。"
#: 表头与官方 47 列模板不一致。
SCHEMA_TEXT = "文件可读，但表头与官方 47 列模板不一致。请确认导出的是官方签署明细且未增删改列。"
#: TXT 认不出编码 / 不是文本（含改了扩展名的二进制、空文件）。
TEXT_ENCODING_TEXT = "文本文件的编码无法识别。请在 Excel 中另存为「Unicode 文本(*.txt)」后重试。"
#: TXT 的引号或列结构不完整（多半是导出后被手工编辑过）。
TEXT_MALFORMED_TEXT = "文本文件的行列结构不完整。请在 Excel 中重新另存为文本，不要手工编辑。"
#: 允许导入的扩展名：官方 xlsx，或 Excel「另存为文本」的 TAB 文本。
SUFFIXES = (".xlsx", ".txt")
_TXT = ".txt"
#: error.diagnostic 的白名单键（契约 §5）：只放枚举与分桶，不放字节/路径/单元格值。
_DIAGNOSTIC_KEYS = ("reason", "sizeBucket", "colIndex")


class ManualImportError(ValueError):
    """导入文件不合格；code 供路由映射错误码与页面提示。

    diagnostic 原样进路由的 error.diagnostic，只允许白名单键
    （reason / sizeBucket / colIndex）：不得放文件头字节、十六进制、路径、
    单元格值或底层异常原文（契约 §5）。
    """

    def __init__(
        self, code: str, message: str, *, diagnostic: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        source = dict(diagnostic or {})
        self.diagnostic: dict[str, Any] = {
            key: source[key] for key in _DIAGNOSTIC_KEYS if key in source
        }


class NullStore:
    """空快照库：读全空、写一律报错，保证手工导入零写库。"""

    @staticmethod
    def _refuse(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("手工导入不允许写库")

    save_snapshot = _refuse
    save_config = _refuse

    def conclusions(self, projects: Iterable[str]) -> dict[str, dict[str, Any]]:
        return {str(project): {} for project in projects}

    def snapshot_dates(self, project: str) -> list[date]:
        return []

    def snapshot_scope(self, project: str, day: date) -> dict[str, Any] | None:
        return None

    def snapshot_rows(self, projects: Iterable[str], day: date) -> list[dict[str, Any]]:
        return []


class ReadOnlyStore:
    """包住真 Store：读能力照旧，写一律报错（手工路径用它，杜绝 save=True 误写 config）。"""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def config(self) -> Any:
        return self._inner.config()

    @staticmethod
    def _refuse(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("手工导入不允许写配置")

    save_config = _refuse


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reason_of(exc: OfficialWorkbookError) -> str:
    """只认闭集里的 reason；空串或未知词一律当「没有」，不把底层原文透出去。"""
    reason = str(getattr(exc, "reason", "") or "").strip()
    return reason if reason in REASONS else ""


def size_bucket(size: int) -> str:
    """文件大小分桶（契约 §5）：页面与部署诊断只认这个词，不传原始字节数。"""
    if size <= 0:
        return "empty"
    if size < 4 * 1024:
        return "tiny"
    if size < 256 * 1024:
        return "small"
    if size < 4 * 1024 * 1024:
        return "medium"
    return "large"


def _is_text(name: str | os.PathLike[str]) -> bool:
    """按扩展名分派：.txt 走文本，其余一律按 xlsx 读（不看内容猜格式）。"""
    return Path(str(name)).suffix.lower() == _TXT


def source_format(data: bytes, name: str | os.PathLike[str]) -> str:
    """来源格式标签（只进响应元数据）：xlsx / txt-utf-16 / txt-utf-8 / txt-gbk。"""
    return f"txt-{text_encoding_label(data)}" if _is_text(name) else "xlsx"


def _translate(exc: OfficialWorkbookError, *, text: bool = False) -> ManualImportError:
    """按 reason 白名单挑 code + 文案（契约 §4）：不解析、不回显底层异常原文。"""
    if isinstance(exc, OfficialWorkbookUnreadable):
        reason = _reason_of(exc)
        if reason == REASON_ENCRYPTED_CONTAINER:
            # 受终端加密：文件本身没坏，只是本进程读不到内容。
            return ManualImportError(
                "E_ENCRYPTED_WORKBOOK", ENCRYPTED_TEXT, diagnostic={"reason": reason}
            )
        if text:
            return ManualImportError(
                "E_TEXT_INVALID",
                TEXT_MALFORMED_TEXT if reason == REASON_TEXT_MALFORMED else TEXT_ENCODING_TEXT,
                diagnostic={"reason": reason} if reason else None,
            )
        return ManualImportError(
            "E_WORKBOOK_INVALID",
            DAMAGED_TEXT,
            diagnostic={"reason": reason} if reason else None,
        )
    if isinstance(exc, OfficialWorkbookTruncated):
        return ManualImportError(
            "E_TOO_MANY_ROWS", f"表单行数超过上限（{MAX_ROWS - 1} 行数据）：请缩小范围后再导出"
        )
    if isinstance(exc, OfficialWorkbookContractError):
        diagnostic: dict[str, Any] = {"reason": REASON_SCHEMA_MISMATCH}
        col_index = getattr(exc, "col_index", None)
        if isinstance(col_index, int) and col_index >= 0:
            diagnostic["colIndex"] = col_index
        return ManualImportError("E_HEADER_MISMATCH", SCHEMA_TEXT, diagnostic=diagnostic)
    # 兜底不回显 str(exc)：底层异常原文不进用户可见输出。
    return ManualImportError("E_IMPORT_FAILED", "报表无法导入，请确认是官方导出的签署明细")


def _read_bounded(path: Path) -> bytes:
    """按大小上限把文件读进内存（解析只认这份字节，不再按路径重开）。"""
    text = _is_text(path)
    try:
        with Path(path).open("rb") as handle:
            data = handle.read(_MAX_IMPORT_BYTES + 1)
    except OSError:
        raise ManualImportError(
            "E_TEXT_INVALID" if text else "E_WORKBOOK_INVALID",
            TEXT_ENCODING_TEXT if text else DAMAGED_TEXT,
            diagnostic={"reason": REASON_UNREADABLE},
        ) from None
    if len(data) > _MAX_IMPORT_BYTES:
        raise ManualImportError("E_FILE_TOO_LARGE", "文件超过大小上限")
    return data


def _tag_ibom(rows: tuple[dict[str, object], ...]) -> tuple[dict[str, object], ...]:
    return tuple({**row, V.SOURCE_KEY: V.SOURCE_IBOM} for row in rows)


def _rows_from_bytes(data: bytes, name: str | os.PathLike[str]) -> tuple[dict[str, object], ...]:
    """字节 → 契约行：xlsx 与 TXT 同一套严格表头校验，全程在内存里。

    接受两套**完整**表头之一：TDC 官方导出（第 0 列「实例号」），或 iBOM「数模设计审核流程报表」
    （第 0 列「序号」，其余 46 列逐字相同）。只有 TDC 表头恰好在第 0 列不符时才按 iBOM 表头整行
    逐字再比一次；两套都不符照旧报表头不符。iBOM 行带来源标记，计数按人次重算（rules.C5）。
    """
    text = _is_text(name)
    try:
        try:
            return read_official_tdc_rows_from_bytes(
                data, _REPORT_TYPE, max_rows=MAX_ROWS, text=text, strict=True
            )
        except OfficialWorkbookContractError as exc:
            if exc.col_index != 0:
                raise
            try:
                return _tag_ibom(read_official_tdc_rows_from_bytes(
                    data, _REPORT_TYPE, max_rows=MAX_ROWS, text=text, strict=True, variant=VARIANT_IBOM
                ))
            except OfficialWorkbookContractError:
                raise exc from None
    except OfficialWorkbookError as exc:
        error = _translate(exc, text=text)
        if error.code in ("E_ENCRYPTED_WORKBOOK", "E_WORKBOOK_INVALID", "E_TEXT_INVALID"):
            # 只在「读不出来」时补大小分桶：用来分辨空/截断与完整容器；表头不符
            # （E_HEADER_MISMATCH）的大小没有诊断价值，不给。
            error.diagnostic = {**error.diagnostic, "sizeBucket": size_bucket(len(data))}
        raise error from None


def _rows_from_path(path: Path) -> tuple[dict[str, object], ...]:
    return _rows_from_bytes(_read_bounded(path), path)


def _source(rows, data_date: date) -> S.SourceData:
    if not rows:
        raise ManualImportError("E_EMPTY_WORKBOOK", "表单里没有任何数据行")
    present = set(rows[0])
    missing = [name for name in V.REQUIRED_COLUMNS if name not in present]
    if missing:
        raise ManualImportError(
            "E_REQUIRED_COLUMNS", "缺少日报必需的列：" + "、".join(missing[:6])
        )
    keep = set(V.REQUIRED_COLUMNS) | {V.SOURCE_KEY}
    records = [{key: value for key, value in row.items() if key in keep} for row in rows]
    return S.SourceData(
        records=records,
        # 手工导入没有真实抓取时间：留空，正文时间回落成「数据日期」，不伪造 00:00。
        snapshot_at=None,
        data_date=data_date,
        coverage={"kind": W.SCOPE_ALL},
    )


def source_from_file(path: Path, data_date: date) -> S.SourceData:
    """把本地表单文件（.xlsx / .txt）投影成一次性 ``SourceData``（不落库、不推日期）。"""
    if not isinstance(data_date, date):
        raise ManualImportError("E_DATE_REQUIRED", "需要人工确认这份报表的数据截至日期")
    return _source(_rows_from_path(path), data_date)


def source_from_bytes(data: bytes, data_date: date, *, name: str = "import.xlsx") -> S.SourceData:
    """从**已校验的字节**解析：保证「校验的对象」与「解析的对象」是同一份内容。

    全程在内存里（不写临时文件）；按 ``name`` 的扩展名决定按 xlsx 还是 TXT 读。
    """
    if not isinstance(data_date, date):
        raise ManualImportError("E_DATE_REQUIRED", "需要人工确认这份报表的数据截至日期")
    if not data:
        raise ManualImportError("E_EMPTY_WORKBOOK", "文件是空的")
    if len(data) > _MAX_IMPORT_BYTES:
        raise ManualImportError("E_FILE_TOO_LARGE", "文件超过大小上限")
    return _source(_rows_from_bytes(data, name), data_date)


#: Excel 代读成功时的来源格式标签（进 importMeta.sourceFormat）。
FORMAT_EXCEL_PROXY = "xlsx-excel"
#: 代读时在契约列之外多留的列数：只为发现「多出来的列」，不是放宽契约。
_PROXY_EXTRA_COLUMNS = 20


def source_from_excel(path: Path, data_date: date) -> S.SourceData:
    """让本机 Excel 代读一份（受终端加密的）xlsx，投影成一次性 ``SourceData``。

    调用方必须先确认代读已开启（``excel_proxy.ready``）；路径来自扫描目录白名单，或是基线文件在插件数据目录里的备份。
    任何失败都落回「受终端加密」那条既有文案与错误码，只在 diagnostic.reason 里给出
    闭集原因词；表头不符、行数超限沿用各自既有的错误码。值不落库、不落文件、不进日志。
    """
    if not isinstance(data_date, date):
        raise ManualImportError("E_DATE_REQUIRED", "需要人工确认这份报表的数据截至日期")
    # 惰性导入：离线 CLI 不带 xlwings，也不需要这条通道。
    from services import sign_daily_excel_reader as reader

    from . import excel_proxy

    expected = official_contract_headers(_REPORT_TYPE)
    ibom_headers = variant_file_headers(_REPORT_TYPE, VARIANT_IBOM)

    def proxy_failed(reason: str, col_index: int | None = None) -> ManualImportError:
        diagnostic: dict[str, Any] = {"reason": reason}
        if isinstance(col_index, int) and col_index >= 0:
            diagnostic["colIndex"] = col_index
        return ManualImportError("E_ENCRYPTED_WORKBOOK", ENCRYPTED_TEXT, diagnostic=diagnostic)

    try:
        matrix = reader.read_via_excel(
            Path(path), max_rows=MAX_ROWS, max_cols=len(expected) + _PROXY_EXTRA_COLUMNS
        )
    except reader.ExcelReadError as exc:
        reason = exc.reason if exc.reason in reader.READ_REASONS else reader.REASON_PROTOCOL
        raise proxy_failed(reason) from None
    # 第 0 列表头是「序号」才按 iBOM 报表读（整行表头仍逐字校验）；否则按 TDC 官方导出读。
    is_ibom = bool(matrix) and bool(matrix[0]) and matrix[0][0] == ibom_headers[0]
    try:
        if is_ibom:
            canonical = excel_proxy.to_canonical(
                matrix, ibom_headers, numeric_text_columns=excel_proxy.IBOM_NUMERIC_TEXT_COLUMNS
            )
            rows = _tag_ibom(official_rows_from_matrix(canonical, _REPORT_TYPE, strict=True, variant=VARIANT_IBOM))
        else:
            canonical = excel_proxy.to_canonical(matrix, expected)
            rows = official_rows_from_matrix(canonical, _REPORT_TYPE, strict=True)
    except excel_proxy.CanonicalError as exc:
        raise proxy_failed(exc.reason, exc.col_index) from None
    except OfficialWorkbookError as exc:
        raise _translate(exc) from None
    return _source(rows, data_date)


def read_verified_bytes(path: Path, expected: tuple[int, int]) -> bytes:
    """打开文件、校验句柄本身（普通文件/非重解析点），并确认内容未被替换。

    返回的字节就是**校验过的那一份**，调用方必须用它去解析，不得再按路径重开。
    """
    try:
        handle = Path(path).open("rb")
    except OSError:
        raise ManualImportError("E_FILE_GONE", "文件已不存在，请重新扫描") from None
    with handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & _REPARSE_POINT:
            raise ManualImportError("E_FILE_NOT_REGULAR", "只接受普通文件（不接受链接或快捷方式）")
        signature = (int(info.st_size), int(info.st_mtime * 1000))
        if signature != (int(expected[0]), int(expected[1])):
            raise ManualImportError("E_SCAN_STALE", "文件在扫描之后被改动过，请重新扫描")
        data = handle.read(_MAX_IMPORT_BYTES + 1)
    if len(data) > _MAX_IMPORT_BYTES:
        raise ManualImportError("E_FILE_TOO_LARGE", "文件超过大小上限")
    return data


def ensure_direct_child(path: Path, directory: Path) -> None:
    """确认目标是该目录的直接子项（阻断 ../ 与目录替换）。"""
    if Path(path).resolve().parent != Path(directory).resolve():
        raise ManualImportError("E_DIR_NOT_ALLOWED", "目标文件不在允许的目录里")


_GBK_NOTE = "；这份是 ANSI 文本，代码页之外的生僻字可能已被 Excel 写成问号，建议改用「Unicode 文本」导出"


#: 日变化的前提：两天导出时的 TDC 筛选条件必须相同。
SAME_FILTER_TEXT = "两天的导出必须用同一套 TDC 筛选条件，否则少掉的单会显示为「消失」"


#: 基线来源：本次指定 > 基线文件 / 固定 > 自动（最近一次更早的导入）。
BASELINE_MODE_TEXT = {"explicit": "指定", "pinned": "固定", "file": "文件", "auto": "自动"}
#: 基线文件的备份不在或认不出：不显示日变化，也不退回自动挑选。
BASELINE_BACKUP_GONE_TEXT = "基线文件和备份都不存在（或无法识别），请重新指定"


def baseline_file_status_text(info: Mapping[str, Any]) -> str:
    """基线文件（对比照常进行时）的原文件状态说明：对比永远用指定时的备份。"""
    original = str(info.get("originalStatus") or "")
    if original == "missing":
        # 这句会进正文（复制出去发给别人）：不写本机路径，路径只在页面上显示（importMeta.baseline.originalPath）。
        return "基线文件不存在（已不在指定时的位置），已改用备份继续对比"
    if original == "changed":
        return "基线文件在指定后被修改过，对比用的是指定时的备份"
    if original == "unknown":
        return "基线文件是通过选择文件指定的，原位置未知，对比用的是指定时的备份"
    return "原文件未变，对比用的是指定时的备份"


def rejected_baseline_text(requested: str, mode: str, file_baseline: Mapping[str, Any] | None = None) -> str:
    if mode == "file":
        info = file_baseline or {}
        if str(info.get("backupStatus") or "") != "ok":
            return BASELINE_BACKUP_GONE_TEXT
        return (
            f"基线文件「{info.get('sourceName') or '未知文件'}」（{requested}）不早于本次数据日期或不含所选项目，"
            "未显示日变化"
        )
    who = "指定" if mode == "explicit" else "固定"
    return f"{who}的基线 {requested} 不早于本次数据日期或不含所选项目，未显示日变化"


def baseline_statement(
    baseline: Mapping[str, Any] | None,
    *,
    stale: bool = False,
    requested: str | None = None,
    requested_mode: str = "auto",
    file_baseline: Mapping[str, Any] | None = None,
) -> str:
    """来源声明里关于日变化的一句：用了哪份基线（指定/文件/固定/自动）/ 指定的基线不可用 / 没有基线 / 旧数据。"""
    if stale:
        return "已有更晚日期的手工导入，本次按旧数据处理：不留基线、不显示日变化"
    if baseline and baseline.get("mode") == "file":
        return (
            f"日变化基线（文件）：{baseline.get('date')} 的基线文件「{baseline.get('sourceName') or '未知文件'}」，"
            f"{baseline_file_status_text(baseline)}；同为用户确认日期、未经系统核验"
        )
    if baseline:
        mode = BASELINE_MODE_TEXT.get(str(baseline.get("mode") or "auto"), "自动")
        return (
            f"日变化基线（{mode}）：{baseline.get('date')} 的手工导入「{baseline.get('sourceName') or '未知文件'}」，"
            "同为用户确认日期、未经系统核验"
        )
    if requested and requested_mode in ("explicit", "pinned", "file"):
        return rejected_baseline_text(requested, requested_mode, file_baseline)
    return "首次导入或无可用基线，不显示日变化"


def import_meta(
    path: Path,
    source: S.SourceData,
    *,
    name: str | None = None,
    digest: str | None = None,
    source_format: str | None = None,
    baseline: Mapping[str, Any] | None = None,
    baseline_saved: bool = False,
    stale: bool = False,
    requested: str | None = None,
    requested_mode: str = "auto",
    file_baseline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """响应里的导入元数据：来源标识 + 行数 + 内容指纹（优先用已校验的字节）+ 日变化基线。

    ``file_baseline``：基线文件模式下的文件与状态（不论这次比没比成都给，页面据此说明原文件/备份的情况）。
    """
    note = (
        "内容时点无法由系统核验；日变化只与此前的手工导入比较（不读写一键生成的数据）；"
        + SAME_FILTER_TEXT + "；"
        + ("本次已留作下次对比的基线" if baseline_saved else "本次未留作基线")
        + "；不提供 .eml 草稿"
    )
    if source_format == f"txt-{ENCODING_GBK}":
        note += _GBK_NOTE
    if source_format == FORMAT_EXCEL_PROXY:
        note += "；文件受终端加密，内容由本机 Excel 只读代读"
    is_ibom = any(record.get(V.SOURCE_KEY) == V.SOURCE_IBOM for record in source.records)
    if is_ibom:
        note += "；来源是 iBOM「数模设计审核流程报表」，应签/已签/未签与签署率按角色列人次重算"
    meta = {
        "mode": "manual",
        "sourceName": name or Path(path).name,
        "sha256": digest or file_sha256(path),
        "rowCount": len(source.records),
        "dataDate": source.data_date.isoformat(),
        "dataDateSourcedBy": "user-confirmed",
        "verified": "structure-only",
        "note": note,
        "baseline": dict(baseline) if baseline else None,
        "baselineSaved": bool(baseline_saved),
        "baselineStatement": baseline_statement(
            baseline, stale=stale, requested=requested, requested_mode=requested_mode,
            file_baseline=file_baseline,
        ),
        # 指定/文件/固定的基线不可用时的原因（不悄悄退回自动挑选）；可用或自动时为空串。
        "baselineReason": (
            rejected_baseline_text(requested, requested_mode, file_baseline)
            if requested and not baseline and not stale and requested_mode in ("explicit", "pinned", "file")
            else ""
        ),
        "baselineFile": dict(file_baseline) if file_baseline else None,
    }
    if source_format:
        meta["sourceFormat"] = source_format
    meta["sourceVariant"] = V.SOURCE_IBOM if is_ibom else V.SOURCE_TDC
    return meta


# ── 目录扫描（「以最后修改时间最晚的文件作为最新报表」）────────────────────
#
# 口径来自顾问定稿（见 .runtime/sign-daily-watchdir-plan-20261110.md）：
# - 只认「最后修改时间最新」的那一个，**不退回到第二新的文件**；
# - 并列 / 正在写入 / 表头不合格 → 转人工，不自动挑；
# - 目录必须落在允许根内；符号链接、重解析点、非普通文件、临时文件一律跳过。

#: 默认监控子目录（插件数据目录下），由部署方或用户在页面指定具体名字。
DEFAULT_SUBDIR = "import"
#: 单次扫描的目录项上限与耗时上限（超限不算部分结果）。
_SCAN_ENTRIES_LIMIT = 200
#: 允许外部目录的环境变量（部署方授权；os.pathsep 分隔）。
_ALLOWED_DIRS_ENV = "VSE_SIGN_DAILY_IMPORT_DIRS"
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


@dataclass(frozen=True)
class ScanEntry:
    name: str
    mtime: str
    size: int
    ok: bool
    reason: str = ""


@dataclass(frozen=True)
class ScanResult:
    directory: Path
    entries: list[ScanEntry] = field(default_factory=list)
    selected: str | None = None
    reason: str = ""
    #: 选中的是「受终端加密的 xlsx」，生成时要走 Excel 代读（只有调用方允许时才会出现）。
    via_excel: bool = False


def allowed_roots(default_dir: Path) -> list[Path]:
    """允许扫描的根目录：插件默认目录 + 部署方在环境变量里授权的目录。"""
    roots: list[Path] = []
    for candidate in [Path(default_dir), *os.environ.get(_ALLOWED_DIRS_ENV, "").split(os.pathsep)]:
        text = str(candidate).strip()
        if not text:
            continue
        try:
            resolved = Path(text).expanduser().resolve()
        except OSError:
            continue
        if resolved not in roots:
            roots.append(resolved)
    return roots


def resolve_scan_dir(raw: str | None, *, default_dir: Path) -> Path:
    """把用户给的目录解析成绝对路径，并确认落在允许根内。"""
    roots = allowed_roots(default_dir)
    target = Path(str(raw or "").strip() or Path(default_dir)).expanduser()
    try:
        resolved = target.resolve()
    except (OSError, ValueError) as exc:
        raise ManualImportError("E_DIR_INVALID", f"目录不可用：{type(exc).__name__}") from None
    if not resolved.is_dir():
        raise ManualImportError("E_DIR_MISSING", "目录不存在或不是文件夹")
    if not any(resolved == root or root in resolved.parents for root in roots):
        raise ManualImportError(
            "E_DIR_NOT_ALLOWED",
            "只允许扫描程序数据目录下的专用文件夹（或部署方授权过的目录）",
        )
    return resolved


def stat_signature(path: Path) -> tuple[int, int]:
    """(size, mtime 毫秒)：用于确认「校验的字节」与「生成用的字节」是同一份。"""
    info = Path(path).stat()
    return int(info.st_size), int(info.st_mtime * 1000)


_HIDDEN = "隐藏文件"


def _skip_reason(path: Path) -> str | None:
    name = path.name
    if name.startswith("~$"):
        return "临时文件"
    if name.startswith("."):
        return _HIDDEN
    if path.suffix.lower() not in SUFFIXES:
        return "不是 .xlsx / .txt"
    try:
        info = path.lstat()
    except OSError:
        return "无法读取文件属性"
    if stat.S_ISLNK(info.st_mode):
        return "符号链接"
    if getattr(info, "st_file_attributes", 0) & _REPARSE_POINT:
        return "重解析点"
    if not stat.S_ISREG(info.st_mode):
        return "不是普通文件"
    return None


def _header_ok(path: Path) -> tuple[bool, str]:
    """只读前两行做一次表头预检：结构不合格的最新文件要转人工，而不是退回旧文件。

    与正式导入同一套严格表头校验（逐字、逐序），在内存里读，不写临时文件。
    """
    text = _is_text(path)
    expected = official_contract_headers(_REPORT_TYPE)
    try:
        data = _read_bounded(path)
        matrix, _truncated = read_official_tdc_matrix_from_bytes(
            data, max_rows=2, text=text, max_columns=len(expected) + 20
        )
        if not matrix:
            return False, "E_EMPTY_WORKBOOK"
        try:
            check_official_header(matrix[0], _REPORT_TYPE, strict=True)
        except OfficialWorkbookContractError as exc:
            # 与 _rows_from_bytes 同一规则：仅第 0 列不符时按 iBOM 报表表头整行逐字再比一次。
            if exc.col_index != 0:
                raise
            try:
                check_official_header(matrix[0], _REPORT_TYPE, strict=True, variant=VARIANT_IBOM)
            except OfficialWorkbookContractError:
                raise exc from None
    except ManualImportError as exc:
        return False, exc.code
    except OfficialWorkbookError as exc:
        return False, _translate(exc, text=text).code
    return True, ""


def scan_directory(
    directory: Path, *, settle_seconds: float = 2.0, allow_encrypted: bool = False
) -> ScanResult:
    """扫描一层目录：只认 mtime 最新的那一个；并列/不合格/写入中都转人工。

    ``allow_encrypted``：Excel 代读已开启时，最新那份若是「受终端加密的 xlsx」也可以选中
    （表头校验推迟到生成时由代读结果来做）；默认仍然停在它上面、转人工。
    """
    entries: list[ScanEntry] = []
    try:
        children = list(Path(directory).iterdir())
    except OSError as exc:
        raise ManualImportError("E_DIR_UNREADABLE", f"目录读不了：{type(exc).__name__}") from None
    if len(children) > _SCAN_ENTRIES_LIMIT:
        raise ManualImportError("E_DIR_TOO_MANY", f"目录项超过 {_SCAN_ENTRIES_LIMIT} 个，请先清理")
    candidates: list[tuple[float, int, Path]] = []
    for path in children:
        reason = _skip_reason(path)
        if reason is not None:
            entries.append(ScanEntry(path.name, "", 0, False, reason))
            # 隐藏的 .xlsx 也算候选：若它是最新的，必须转人工，不能静默退回更旧文件
            if reason == _HIDDEN and path.suffix.lower() in SUFFIXES:
                try:
                    candidates.append((path.stat().st_mtime, 1, path))
                except OSError:
                    pass
            continue
        try:
            info = path.stat()
        except OSError:
            entries.append(ScanEntry(path.name, "", 0, False, "无法读取文件属性"))
            continue
        candidates.append((info.st_mtime, 0, path))
    if not candidates:
        return ScanResult(Path(directory), entries, None, "E_NO_FILE")
    candidates.sort(key=lambda item: (item[0], item[2].name), reverse=True)
    newest_mtime, is_hidden, newest = candidates[0]
    if len(candidates) > 1 and candidates[1][0] == newest_mtime:
        return ScanResult(Path(directory), entries, None, "E_MTIME_TIE")
    if is_hidden:
        return ScanResult(Path(directory), entries, None, "E_NEWEST_HIDDEN")
    if settle_seconds > 0:
        before = stat_signature(newest)
        time.sleep(settle_seconds)
        if stat_signature(newest) != before:
            return ScanResult(Path(directory), entries, None, "E_FILE_WRITING")
    ok, why = _header_ok(newest)
    via_excel = False
    if not ok and why == "E_ENCRYPTED_WORKBOOK" and allow_encrypted and not _is_text(newest):
        ok, why, via_excel = True, "", True
    info = newest.stat()
    for entry in entries:
        if entry.name == newest.name:
            entries.remove(entry)
            break
    entries.insert(0, ScanEntry(newest.name, datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
                                int(info.st_size), ok, why))
    if not ok:
        # 最新那份不合格就停在这里：绝不退回第二新的文件。
        return ScanResult(Path(directory), entries, None, why or "E_FILE_INVALID")
    return ScanResult(Path(directory), entries, newest.name, "", via_excel)


def make_scan_token(
    secret: bytes, directory: Path, name: str, signature: tuple[int, int], digest: str = ""
) -> str:
    payload = f"{Path(directory).resolve()}|{name}|{signature[0]}|{signature[1]}|{digest}"
    digest = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def verify_scan_token(
    secret: bytes, token: str, directory: Path, name: str, signature: tuple[int, int], digest: str = ""
) -> bool:
    expected = make_scan_token(secret, directory, name, signature, digest)
    return hmac.compare_digest(expected, str(token or ""))
