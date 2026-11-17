# -*- coding: utf-8 -*-
"""Excel「另存为文本」的 TAB 文本 → 行矩阵（纯标准库、只在内存里解析）。

用途：公司终端加密的 xlsx 本进程读不到内容，用户改用 Excel 自带的「另存为文本」
导出一份 TXT，再交给程序读。本模块只负责「字节 → 字符串矩阵」，47 列契约校验
在 `services.tdc_official_rows`。

实测的 Excel 导出形态（2026-11-11，Excel 16.0，见 docs/PLAN_20261111_SIGNDAILY_TXT.md）：

- 「Unicode 文本」：UTF-16LE + `FF FE` BOM、TAB 分隔、CRLF；
- 「文本文件(制表符分隔)」：本机 ANSI 代码页（中文系统是 GBK）、无 BOM、TAB 分隔、CRLF；
- 含逗号/引号/换行的字段会被加双引号（CSV 风格），所以必须用 csv 语义切分，
  `split("\\t")` 会切出假差异。

边界（fail-closed）：

- 严格解码：认不出编码、解不动、含 NUL 的一律报 `text_encoding`，绝不
  `errors="ignore"/"replace"` 悄悄改数据；
- 引号不闭合、引号后紧跟普通字符、单行列数离谱 → `text_malformed`；
- 终端加密容器 → `encrypted_container`（只做前缀嗅探，不剥头、不解密）；
- 异常消息只有固定英文短语，不带任何单元格内容或原始字节。

已知的格式能力边界：ANSI 导出时 Excel 会把代码页之外的字符写成 `?`，从 TXT 里
看不出来——需要保真请用「Unicode 文本」。
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from services.xlsx_preview import (
    FILE_KIND_EMPTY_OR_TRUNCATED,
    FILE_KIND_ENCRYPTED_CONTAINER,
    FILE_KIND_OLE_CONTAINER,
    FILE_KIND_ZIP,
    REASON_EMPTY_OR_TRUNCATED,
    REASON_ENCRYPTED_CONTAINER,
    REASON_TEXT_ENCODING,
    REASON_TEXT_MALFORMED,
    SNIFF_BYTES,
    sniff_file_kind,
)

#: 编码标签（进 importMeta.sourceFormat，不是用户输入）。
ENCODING_UTF16 = "utf-16"
ENCODING_UTF8 = "utf-8"
ENCODING_GBK = "gbk"

_BOM_UTF16 = (b"\xff\xfe", b"\xfe\xff")
_BOM_UTF8 = b"\xef\xbb\xbf"
#: 单行字段数的硬上限：远大于任何官方契约的列数，只用来挡住畸形输入。
DEFAULT_MAX_COLUMNS = 400


class TextTableError(ValueError):
    """文本读不成表；reason 是 services.xlsx_preview.REASONS 里的闭集词。"""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class TextTable:
    rows: list[list[str]]
    truncated: bool
    encoding: str


def text_encoding_label(data: bytes) -> str:
    """只看 BOM 判编码：有 UTF-16/UTF-8 BOM 用对应编码，否则按 GBK（Excel 的 ANSI 导出）。"""
    if data[:2] in _BOM_UTF16:
        return ENCODING_UTF16
    if data[:3] == _BOM_UTF8:
        return ENCODING_UTF8
    return ENCODING_GBK


def decode_excel_text(data: bytes) -> tuple[str, str]:
    """严格解码成 (文本, 编码标签)；失败抛 TextTableError，不做任何容错替换。"""
    kind = sniff_file_kind(bytes(data[:SNIFF_BYTES]), len(data))
    if kind == FILE_KIND_EMPTY_OR_TRUNCATED:
        raise TextTableError("text export is empty or truncated", reason=REASON_EMPTY_OR_TRUNCATED)
    if kind == FILE_KIND_ENCRYPTED_CONTAINER:
        # 本进程视图下是终端加密容器：到此为止，不剥头、不探测后面的内容。
        raise TextTableError(
            "text export is a terminal-encrypted container", reason=REASON_ENCRYPTED_CONTAINER
        )
    if kind in (FILE_KIND_ZIP, FILE_KIND_OLE_CONTAINER):
        # 改了扩展名的 xlsx/xls：不是文本，不去猜。
        raise TextTableError("text export is a binary office file", reason=REASON_TEXT_ENCODING)

    label = text_encoding_label(data)
    if label == ENCODING_GBK and b"\x00" in data:
        # 无 BOM 却有 NUL：多半是没有 BOM 的 UTF-16 或二进制，GBK 会把它「解成功」。
        raise TextTableError("text export has no BOM but contains NUL bytes", reason=REASON_TEXT_ENCODING)
    codec = {ENCODING_UTF16: "utf-16", ENCODING_UTF8: "utf-8-sig", ENCODING_GBK: "gbk"}[label]
    try:
        text = data.decode(codec, errors="strict")
    except UnicodeDecodeError:
        # 不带原始异常：它的消息里有出错的字节值与位置。
        raise TextTableError("text export cannot be decoded strictly", reason=REASON_TEXT_ENCODING) from None
    if chr(0) in text:
        raise TextTableError("text export contains NUL characters", reason=REASON_TEXT_ENCODING)
    return text, label


def read_text_table(
    data: bytes,
    *,
    max_rows: int,
    max_columns: int = DEFAULT_MAX_COLUMNS,
) -> TextTable:
    """把 Excel 导出的 TAB 文本切成行矩阵（值全是 str）。

    `max_rows` 含表头行；还有更多记录时 `truncated=True`，由调用方决定报错，
    绝不返回「少几行但看起来正常」的结果。空行（没有任何字段）直接跳过、不计数。
    """
    if max_rows <= 0 or max_columns <= 0:
        raise ValueError("text table limits must be positive")
    text, label = decode_excel_text(data)
    reader = csv.reader(
        io.StringIO(text, newline=""),
        delimiter="\t",
        quotechar='"',
        doublequote=True,
        skipinitialspace=False,
        strict=True,
    )
    rows: list[list[str]] = []
    truncated = False
    try:
        for record in reader:
            if not record:
                continue
            if len(rows) >= max_rows:
                truncated = True
                break
            if len(record) > max_columns:
                raise TextTableError("text export row has too many fields", reason=REASON_TEXT_MALFORMED)
            rows.append(list(record))
    except csv.Error:
        # csv.Error 的消息是固定短语，但仍不外传：统一成一句。
        raise TextTableError("text export has malformed quoting", reason=REASON_TEXT_MALFORMED) from None
    return TextTable(rows=rows, truncated=truncated, encoding=label)


__all__ = [
    "DEFAULT_MAX_COLUMNS",
    "ENCODING_GBK",
    "ENCODING_UTF16",
    "ENCODING_UTF8",
    "TextTable",
    "TextTableError",
    "decode_excel_text",
    "read_text_table",
    "text_encoding_label",
]
