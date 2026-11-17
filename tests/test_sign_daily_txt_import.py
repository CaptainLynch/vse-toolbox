# -*- coding: utf-8 -*-
"""签署日报 TXT 导入（2026-11-11）：Excel「另存为文本」的 TAB 文本也能出日报。

口径（docs/PLAN_20261111_SIGNDAILY_TXT.md）：

- 只认 Excel 导出的 TAB 文本：UTF-16（带 BOM）、UTF-8（带 BOM）、无 BOM 的 GBK；
  严格解码，乱码/二进制/畸形引号一律报错，不 ignore/replace。
- 表头 47 列逐字、逐序校验（不 strip、不做 Unicode 归一）；xlsx 与 TXT 在签署日报
  里共用这套严格语义，其他官方报表调用方保持原有宽松读取。
- 上传与扫描全程在内存里解析：不写临时文件（含 multipart 的自动 spool）。
- 错误响应只有闭集 code / reason / 计数，不带单元格内容。

全部用合成数据；真实样本的对照在 .runtime/ 本地脚本里做，不进测试源码。
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

import pytest

from core import diagnostic_recording
from services import tdc_official_rows as official
from services import tdc_text_rows as text_rows
from services import xlsx_preview
from services.xlsx_preview import ENCRYPTED_CONTAINER_SIGNATURES, SNIFF_BYTES
from tests.test_ewo_official_rows import write_workbook
from tests import test_plugin_sign_daily as base
from tests.test_plugin_sign_daily import API, HEADERS, _ok, _publish, _rows, _snapshot_counts

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))

import sign_daily_local_report as tool  # noqa: E402

DATA_MODEL = "data_model"
EXPECTED = official.official_contract_headers(DATA_MODEL)
SENTINEL = "哨兵串ZX9QK7"
_DIAGNOSTIC_KEYS = {"reason", "sizeBucket", "colIndex"}

#: 复用插件接口测试的同一个应用夹具（只加载 sign-daily 插件、临时库）。
client = base.client


# ── 合成样本 ────────────────────────────────────────────────────────


def _field(value: object) -> str:
    """按 Excel 的文本导出规则写一个字段：含逗号/引号/换行/TAB 时加引号并双写引号。"""
    text = "" if value is None else str(value)
    if any(mark in text for mark in (",", '"', "\n", "\r", "\t")):
        return '"' + text.replace('"', '""') + '"'
    return text


def _text(matrix, *, newline: str = "\r\n") -> str:
    return "".join("\t".join(_field(value) for value in row) + newline for row in matrix)


def _encode(text: str, encoding: str = "utf-16") -> bytes:
    # "utf-16" 写出 FF FE + UTF-16LE，"utf-8-sig" 写出 EF BB BF：与 Excel 导出一致。
    return text.encode(encoding)


def _matrix(rows, header=None):
    header = list(HEADERS if header is None else header)
    return [header] + [[row.get(key) for key in HEADERS] for row in rows]


def _txt_bytes(rows=None, *, encoding: str = "utf-16", header=None) -> bytes:
    return _encode(_text(_matrix(_rows() if rows is None else rows, header)), encoding)


def _txt_file(path: Path, rows=None, *, encoding: str = "utf-16", header=None) -> Path:
    path.write_bytes(_txt_bytes(rows, encoding=encoding, header=header))
    return path


def _xlsx_file(path: Path, rows=None, header=None) -> Path:
    matrix = _matrix(_rows() if rows is None else rows, header)
    return write_workbook(path, matrix[0], matrix[1:], sheet_name="Sheet1")


def _container(payload: bytes = b"plain text") -> bytes:
    return ENCRYPTED_CONTAINER_SIGNATURES[0] + bytes(1024 - SNIFF_BYTES) + payload


def _post_file(http, name: str, data: bytes, **form):
    payload = {"file": (io.BytesIO(data), name), "dataDate": "2026-11-06", "projects": '["F610M"]', **form}
    return http.post(f"{API}/import-form", data=payload, content_type="multipart/form-data")


def _multipart(fields: dict[str, str], name: str, data: bytes) -> tuple[bytes, str]:
    """手工拼 multipart：测试客户端自己会把大请求体落临时文件，会干扰「零落盘」断言。"""
    boundary = "----vse-sign-daily-txt"
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode("utf-8")
        )
    parts.append(
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8")
        + data
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


@pytest.fixture()
def temp_calls(monkeypatch):
    """记录一切临时文件/目录的创建（SpooledTemporaryFile 落盘也走 _mkstemp_inner）。"""
    calls: list[str] = []
    real_mkstemp, real_mkdtemp = tempfile._mkstemp_inner, tempfile.mkdtemp

    def mkstemp_inner(*args, **kwargs):
        calls.append("file")
        return real_mkstemp(*args, **kwargs)

    def mkdtemp(*args, **kwargs):
        calls.append("dir")
        return real_mkdtemp(*args, **kwargs)

    monkeypatch.setattr(tempfile, "_mkstemp_inner", mkstemp_inner)
    monkeypatch.setattr(tempfile, "mkdtemp", mkdtemp)
    return calls


def _scan_env(monkeypatch, tmp_path: Path) -> None:
    backend = sys.modules["vse_plugins.sign_daily.backend"]
    monkeypatch.setattr(backend, "_SCAN_SETTLE_SECONDS", 0.0)
    monkeypatch.setenv("VSE_SIGN_DAILY_IMPORT_DIRS", str(tmp_path))


def _scan(http, directory: Path):
    return http.post(f"{API}/import-scan", json={"dir": str(directory)})


def _aging(path: Path, seconds: float) -> None:
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def _importer():
    return sys.modules["vse_plugins.sign_daily.importer"]


# ── 文本解码与切分（services/tdc_text_rows.py）──────────────────────


@pytest.mark.parametrize("encoding,label", [("utf-16", "utf-16"), ("utf-8-sig", "utf-8"), ("gbk", "gbk")])
def test_text_table_decodes_excel_encodings(encoding: str, label: str) -> None:
    matrix = [["甲", "乙,丙", '带"引号"'], ["跨\n行", "", "尾"]]
    table = text_rows.read_text_table(_encode(_text(matrix), encoding) + b"", max_rows=10)
    assert table.rows == matrix
    assert table.encoding == label
    assert table.truncated is False


def test_text_table_keeps_tab_inside_quoted_field_and_skips_blank_lines() -> None:
    data = _encode('a\t"b\tc"\r\n\r\nd\te\r\n')
    assert text_rows.read_text_table(data, max_rows=10).rows == [["a", "b\tc"], ["d", "e"]]


def test_text_table_marks_truncation_instead_of_partial_rows() -> None:
    data = _encode(_text([[str(index), "x"] for index in range(5)]))
    table = text_rows.read_text_table(data, max_rows=3)
    assert table.truncated is True and len(table.rows) == 3


@pytest.mark.parametrize(
    "data,reason",
    [
        (b"", "empty_or_truncated"),
        (b"\xff\xfea\x00", "empty_or_truncated"),  # 不足嗅探长度：当成空/截断
        (_container(), "encrypted_container"),
        (b"PK\x03\x04" + bytes(64), "text_encoding"),  # 改了扩展名的 xlsx
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(64), "text_encoding"),
        (b"\xff\xfe" + "流水单号\t项目".encode("utf-16-le") * 4 + b"\x41", "text_encoding"),  # 奇数字节
        ("流水单号\t项目/车型\t部门\r\n".encode("utf-16-le") * 2, "text_encoding"),  # 无 BOM 的 UTF-16
        (b"\x81" * 8 + b"\xff" * 16, "text_encoding"),  # GBK 解不了
        (b"\xef\xbb\xbf" + "流水单号".encode("gbk") * 6, "text_encoding"),  # 假 UTF-8 BOM
    ],
)
def test_text_table_rejects_undecodable_input(data: bytes, reason: str) -> None:
    with pytest.raises(text_rows.TextTableError) as caught:
        text_rows.read_text_table(data, max_rows=10)
    assert caught.value.reason == reason
    assert reason in xlsx_preview.REASONS


@pytest.mark.parametrize(
    "body",
    [
        '流水单号\t"没有闭合的引号\r\n下一行\t值\r\n',
        '流水单号\t"引号后"还有字\t值\r\n' + "补足长度\t补足长度\r\n",
    ],
)
def test_text_table_rejects_malformed_quotes(body: str) -> None:
    with pytest.raises(text_rows.TextTableError) as caught:
        text_rows.read_text_table(_encode(body), max_rows=10)
    assert caught.value.reason == "text_malformed"


def test_text_table_error_never_carries_cell_content() -> None:
    with pytest.raises(text_rows.TextTableError) as caught:
        text_rows.read_text_table(_encode(f'{SENTINEL}\t"{SENTINEL}\r\n' * 3), max_rows=10)
    assert SENTINEL not in str(caught.value)


# ── 契约投影（services/tdc_official_rows.py）────────────────────────


def _official(data: bytes, *, text: bool = True, strict: bool = True, max_rows: int = 5001):
    return official.read_official_tdc_rows_from_bytes(
        data, DATA_MODEL, max_rows=max_rows, text=text, strict=strict
    )


def test_official_text_rows_match_xlsx_rows(tmp_path: Path) -> None:
    rows = [dict(row, 待审批人员="张三,李四", 零件名称='带"引号"的件') for row in _rows()]
    from_xlsx = _official(_xlsx_file(tmp_path / "a.xlsx", rows).read_bytes(), text=False)
    for encoding in ("utf-16", "utf-8-sig", "gbk"):
        from_txt = _official(_txt_bytes(rows, encoding=encoding))
        assert len(from_txt) == len(from_xlsx) == len(rows)
        for txt_row, xlsx_row in zip(from_txt, from_xlsx):
            assert list(txt_row) == EXPECTED
            assert {k: v or "" for k, v in txt_row.items()} == {k: v or "" for k, v in xlsx_row.items()}


def test_official_text_rows_pad_short_data_rows() -> None:
    """Excel 会省掉行尾的空字段：短行按空值补齐到 47 列，不算错位。"""
    source = [dict(row, 状态="", 待审批人员="") for row in _rows()]
    lines = _text(_matrix(source)).split("\r\n")
    lines[1] = lines[1].rstrip("\t")
    assert lines[1].count("\t") < 46
    rows = _official(_encode("\r\n".join(lines)))
    assert len(rows) == len(_rows())
    assert all(list(row) == EXPECTED for row in rows)
    assert rows[0]["流水单号"] == _rows()[0]["流水单号"]


@pytest.mark.parametrize(
    "mutate,col_index",
    [
        (lambda h: h[:2] + [h[2] + "(旧模板)"] + h[3:], 2),
        (lambda h: h[:5] + [" " + h[5]] + h[6:], 5),  # 不 strip：多一个空格也算不一致
        (lambda h: h[:7] + [h[7] + " "] + h[8:], 7),
        (lambda h: h[:46], 46),  # 少一列
        (lambda h: h + ["多出来的列"], 47),  # 多一列
        (lambda h: h[:3] + [h[4], h[3]] + h[5:], 3),  # 两列对调
        (lambda h: [h[0] + chr(0x200B)] + h[1:], 0),  # 不做 Unicode 归一（零宽空格也算不一致）
    ],
)
def test_official_text_header_is_verbatim(mutate, col_index: int) -> None:
    data = _txt_bytes(header=mutate(list(HEADERS)))
    with pytest.raises(official.OfficialWorkbookContractError) as caught:
        _official(data)
    assert caught.value.reason == "schema_mismatch"
    assert caught.value.col_index == col_index


def test_official_text_rejects_data_beyond_contract_columns() -> None:
    lines = _text(_matrix(_rows())).split("\r\n")
    lines[2] = lines[2] + "\t" + SENTINEL
    with pytest.raises(official.OfficialWorkbookContractError) as caught:
        _official(_encode("\r\n".join(lines)))
    assert caught.value.reason == "schema_mismatch"
    assert caught.value.col_index == 47
    assert SENTINEL not in str(caught.value)


def test_official_text_tolerates_wholly_empty_trailing_column() -> None:
    """整列全空（表头与数据都没有值）不携带信息：Excel 带格式的空列不算「多列」。"""
    lines = [line + "\t" for line in _text(_matrix(_rows())).split("\r\n") if line]
    assert len(_official(_encode("\r\n".join(lines) + "\r\n"))) == len(_rows())


def test_official_text_truncation_is_explicit() -> None:
    with pytest.raises(official.OfficialWorkbookTruncated):
        _official(_txt_bytes(), max_rows=2)


def test_strict_header_applies_to_xlsx_but_legacy_callers_stay_lenient(tmp_path: Path) -> None:
    header = list(HEADERS)
    header[4] = header[4] + " "
    path = _xlsx_file(tmp_path / "spaced.xlsx", header=header)
    # 其他官方报表调用方：保持「strip 后比对」的既有行为
    assert len(official.read_official_tdc_rows(path, DATA_MODEL, max_rows=5001)) == len(_rows())
    # 签署日报：xlsx 与 TXT 同一套逐字校验
    with pytest.raises(official.OfficialWorkbookContractError) as caught:
        official.read_official_tdc_rows(path, DATA_MODEL, max_rows=5001, strict=True)
    assert caught.value.col_index == 4
    with pytest.raises(official.OfficialWorkbookContractError):
        _official(path.read_bytes(), text=False)


def test_xlsx_bytes_reader_equals_path_reader(tmp_path: Path) -> None:
    path = _xlsx_file(tmp_path / "a.xlsx")
    by_path = xlsx_preview.read_xlsx_preview(path, max_rows=50)
    by_bytes = xlsx_preview.read_xlsx_preview_bytes(path.read_bytes(), max_rows=50)
    assert by_bytes == by_path
    with pytest.raises(xlsx_preview.XLSXEncryptedContent):
        xlsx_preview.read_xlsx_preview_bytes(_container(), max_rows=50)


def test_new_reasons_are_in_closed_sets() -> None:
    for reason in ("text_encoding", "text_malformed"):
        assert reason in xlsx_preview.REASONS
        assert reason in diagnostic_recording._VALUES


# ── 页面上传 ────────────────────────────────────────────────────────


def _comparable(report: dict, name: str) -> dict:
    """只归一「来源声明」这类预期不同的元数据；业务字段一个不删。"""
    out = dict(report)
    meta = dict(out.pop("importMeta"))
    for key in ("sourceName", "sha256", "sourceFormat", "note", "banner"):
        meta.pop(key, None)
    out["importMeta"] = meta
    for key in ("html", "text"):
        assert name in out[key]
        out[key] = out[key].replace(name, "<SOURCE>")
    return out


@pytest.mark.parametrize("encoding,label", [("utf-16", "txt-utf-16"), ("utf-8-sig", "txt-utf-8"), ("gbk", "txt-gbk")])
def test_upload_txt_gives_same_report_as_xlsx(client, tmp_path, encoding, label) -> None:  # type: ignore[no-untyped-def]
    _, http, db, _ = client
    _publish(db, _rows(), "2026-10-02T08:00:00Z")
    before = _snapshot_counts(db)
    from_xlsx = _ok(_post_file(http, "import.xlsx", _xlsx_file(tmp_path / "import.xlsx").read_bytes()))
    from_txt = _ok(_post_file(http, "导出.txt", _txt_bytes(encoding=encoding)))

    assert from_txt["mode"] == "manual"
    assert from_txt["importMeta"]["sourceName"] == "导出.txt"
    assert from_txt["importMeta"]["sourceFormat"] == label
    assert from_xlsx["importMeta"]["sourceFormat"] == "xlsx"
    assert from_txt["importMeta"]["rowCount"] == len(_rows())
    assert from_txt["delta"] is None and from_txt["snapshotSaved"] is False
    assert _comparable(from_txt, "导出.txt") == _comparable(from_xlsx, "import.xlsx")
    assert _snapshot_counts(db) == before  # 零写库


def test_upload_gbk_txt_warns_about_lossy_encoding(client) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    gbk = _ok(_post_file(http, "a.txt", _txt_bytes(encoding="gbk")))
    unicode_ = _ok(_post_file(http, "a.txt", _txt_bytes(encoding="utf-16")))
    assert "Unicode 文本" in gbk["importMeta"]["note"]
    assert "Unicode 文本" not in unicode_["importMeta"]["note"]


def _large_rows(count: int = 1500, *, incompressible: bool = False) -> list[dict[str, object]]:
    base = _rows()[0]

    def filler(index: int) -> str:
        if not incompressible:
            return "长" * 300
        # 每行不同的十六进制串：xlsx 是 zip，重复内容会被压到阈值以下。
        return "".join(hashlib.sha256(f"{index}:{part}".encode()).hexdigest() for part in range(12))

    return [
        dict(base, 流水单号=f"L{index:05d}", 零件号=f"L{index:05d}-P1", 流程名=filler(index))
        for index in range(count)
    ]


@pytest.mark.parametrize("kind", ["txt", "xlsx"])
def test_large_upload_never_touches_temp_files(client, tmp_path, temp_calls, kind) -> None:  # type: ignore[no-untyped-def]
    """大于 multipart 默认暂存阈值（500KB）的文件：成功路径全程不落任何临时文件。"""
    _, http, db, _ = client
    if kind == "txt":
        rows = _large_rows()
        data, name = _txt_bytes(rows), "big.txt"
    else:
        rows = _large_rows(2500, incompressible=True)
        data, name = _xlsx_file(tmp_path / "big.xlsx", rows).read_bytes(), "big.xlsx"
    assert len(data) > 600 * 1024  # 超过 Werkzeug 默认 500KB 的落盘阈值
    body, content_type = _multipart({"dataDate": "2026-11-06", "projects": '["F610M"]'}, name, data)
    before = _snapshot_counts(db)
    temp_calls.clear()

    response = http.post(f"{API}/import-form", data=body, content_type=content_type)

    report = _ok(response)
    assert report["importMeta"]["rowCount"] == len(rows)
    assert temp_calls == []
    assert _snapshot_counts(db) == before


def test_large_failing_upload_leaks_nothing(client, temp_calls, caplog) -> None:  # type: ignore[no-untyped-def]
    """失败路径：响应、日志、临时目录、数据库都不出现单元格内容。"""
    _, http, db, _ = client
    rows = [dict(row, 流程名=SENTINEL * 20, 零件名称=SENTINEL) for row in _large_rows()]
    good = _text(_matrix(rows))
    header_drift = _text(_matrix(rows, header=[HEADERS[0] + SENTINEL] + list(HEADERS[1:])))
    samples = {
        "E_TEXT_INVALID:text_malformed": _encode(good + f'{SENTINEL}\t"{SENTINEL}\r\n'),
        "E_HEADER_MISMATCH:schema_mismatch": _encode(header_drift),
        "E_TEXT_INVALID:text_encoding": _encode(good)[:-1],
        "E_HEADER_MISMATCH:schema_mismatch:extra": _encode(good.replace("\r\n", f"\t{SENTINEL}\r\n", 3)),
    }
    before = _snapshot_counts(db)
    caplog.set_level(logging.DEBUG)
    for expected, data in samples.items():
        assert len(data) > 600 * 1024
        code, reason = expected.split(":")[:2]
        body, content_type = _multipart({"dataDate": "2026-11-06"}, "bad.txt", data)
        temp_calls.clear()
        response = http.post(f"{API}/import-form", data=body, content_type=content_type)

        assert response.status_code == 422, expected
        error = response.get_json()["error"]
        assert error["type"] == code
        assert set(error["diagnostic"]) <= _DIAGNOSTIC_KEYS
        assert error["diagnostic"]["reason"] == reason
        assert SENTINEL not in response.get_data(as_text=True)
        assert temp_calls == []
    assert SENTINEL not in caplog.text
    assert _snapshot_counts(db) == before


def test_oversized_request_is_refused_without_temp_files(client, temp_calls) -> None:  # type: ignore[no-untyped-def]
    """超过宿主请求体上限（16MB）：直接 413，不解析、不落盘。"""
    _, http, _, _ = client
    body, content_type = _multipart({"dataDate": "2026-11-06"}, "huge.txt", b"x" * (17 * 1024 * 1024))
    temp_calls.clear()
    response = http.post(f"{API}/import-form", data=body, content_type=content_type)
    assert response.status_code == 413
    assert temp_calls == []


def test_upload_txt_error_messages(client) -> None:  # type: ignore[no-untyped-def]
    _, http, _, _ = client
    importer = _importer()

    encrypted = _post_file(http, "a.txt", _container()).get_json()["error"]
    assert encrypted["type"] == "E_ENCRYPTED_WORKBOOK"
    assert encrypted["message"] == sys.modules["vse_plugins.sign_daily.backend"].ENCRYPTED_PAGE_TEXT
    assert encrypted["diagnostic"]["reason"] == "encrypted_container"

    garbled = _post_file(http, "a.txt", b"\x81" * 8 + b"\xff" * 64).get_json()["error"]
    assert garbled["type"] == "E_TEXT_INVALID"
    assert garbled["message"] == importer.TEXT_ENCODING_TEXT
    assert garbled["diagnostic"] == {"reason": "text_encoding", "sizeBucket": "tiny"}

    renamed = _post_file(http, "a.txt", b"PK\x03\x04" + bytes(4096)).get_json()["error"]
    assert renamed["type"] == "E_TEXT_INVALID" and renamed["diagnostic"]["reason"] == "text_encoding"

    broken = _post_file(http, "a.txt", _encode(_text(_matrix(_rows())) + '流水\t"没闭合\r\n')).get_json()["error"]
    assert broken["type"] == "E_TEXT_INVALID"
    assert broken["message"] == importer.TEXT_MALFORMED_TEXT

    drift = _post_file(http, "a.txt", _txt_bytes(header=list(HEADERS[:2]) + ["改名"] + list(HEADERS[3:])))
    assert drift.status_code == 422
    assert drift.get_json()["error"] == {
        **drift.get_json()["error"],
        "type": "E_HEADER_MISMATCH",
        "message": importer.SCHEMA_TEXT,
        "diagnostic": {"reason": "schema_mismatch", "colIndex": 2},
    }

    header_only = _post_file(http, "a.txt", _txt_bytes(rows=[])).get_json()["error"]
    assert header_only["type"] == "E_EMPTY_WORKBOOK"


def test_txt_content_under_xlsx_name_stays_rejected(client) -> None:  # type: ignore[no-untyped-def]
    """不扩展成「伪装 xlsx」导入：扩展名是 .xlsx 就只按 xlsx 读。"""
    _, http, _, _ = client
    error = _post_file(http, "fake.xlsx", _txt_bytes(encoding="utf-8-sig")).get_json()["error"]
    assert error["type"] == "E_WORKBOOK_INVALID"
    assert error["diagnostic"]["reason"] == "unknown_binary"


def test_importer_limits(monkeypatch) -> None:
    importer = _importer()
    day = date(2026, 11, 6)
    monkeypatch.setattr(importer, "MAX_ROWS", 2)
    with pytest.raises(importer.ManualImportError) as rows_error:
        importer.source_from_bytes(_txt_bytes(), day, name="a.txt")
    assert rows_error.value.code == "E_TOO_MANY_ROWS"
    monkeypatch.setattr(importer, "_MAX_IMPORT_BYTES", 64)
    with pytest.raises(importer.ManualImportError) as size_error:
        importer.source_from_bytes(_txt_bytes(), day, name="a.txt")
    assert size_error.value.code == "E_FILE_TOO_LARGE"
    with pytest.raises(importer.ManualImportError) as empty_error:
        importer.source_from_bytes(b"", day, name="a.txt")
    assert empty_error.value.code == "E_EMPTY_WORKBOOK"


def test_source_from_bytes_and_file_use_no_temp_files(tmp_path, temp_calls) -> None:
    importer = _importer()
    day = date(2026, 11, 6)
    txt = _txt_file(tmp_path / "a.txt")
    xlsx = _xlsx_file(tmp_path / "a.xlsx")
    temp_calls.clear()
    for path in (txt, xlsx):
        by_bytes = importer.source_from_bytes(path.read_bytes(), day, name=path.name)
        by_file = importer.source_from_file(path, day)
        assert by_bytes.records == by_file.records and len(by_file.records) == len(_rows())
    assert temp_calls == []


# ── 目录扫描 ────────────────────────────────────────────────────────


def test_scan_picks_newest_txt_and_generates(client, tmp_path, monkeypatch, temp_calls) -> None:  # type: ignore[no-untyped-def]
    _scan_env(monkeypatch, tmp_path)
    _, http, db, _ = client
    before = _snapshot_counts(db)
    old = _xlsx_file(tmp_path / "old.xlsx")
    new = _txt_file(tmp_path / "new.txt")
    (tmp_path / "notes.csv").write_text("x", encoding="utf-8")
    _aging(old, 3600)
    _aging(new, 60)

    temp_calls.clear()
    scanned = _ok(_scan(http, tmp_path))
    selected = scanned["selected"]
    assert selected["name"] == "new.txt" and scanned["reason"] == ""
    skipped = {entry["name"]: entry["reason"] for entry in scanned["entries"]}
    assert skipped["notes.csv"] == "不是 .xlsx / .txt"

    report = _ok(http.post(
        f"{API}/import-form",
        data={"scanDirId": scanned["dirId"], "scanName": selected["name"], "scanToken": selected["token"],
              "dataDate": "2026-11-06", "projects": '["F610M"]'},
        content_type="multipart/form-data",
    ))
    assert report["importMeta"]["sourceName"] == "new.txt"
    assert report["importMeta"]["sourceFormat"] == "txt-utf-16"
    assert report["importMeta"]["rowCount"] == len(_rows())
    assert temp_calls == []
    assert _snapshot_counts(db) == before


@pytest.mark.parametrize(
    "newest,reason",
    [
        (lambda p: p.write_bytes(_container()), "E_ENCRYPTED_WORKBOOK"),
        (lambda p: p.write_bytes(_encode(_text(_matrix(_rows())) + 'x\t"y\r\n')[:-1]), "E_TEXT_INVALID"),
        (lambda p: p.write_bytes(_txt_bytes(header=list(HEADERS[:46]))), "E_HEADER_MISMATCH"),
        (lambda p: p.write_bytes(b""), "E_TEXT_INVALID"),
    ],
)
def test_scan_stops_on_bad_newest_txt(client, tmp_path, monkeypatch, newest, reason) -> None:  # type: ignore[no-untyped-def]
    """最新那份 TXT 不合格就停在它上面，不退回更旧的好文件。"""
    _scan_env(monkeypatch, tmp_path)
    _, http, _, _ = client
    good = _txt_file(tmp_path / "good.txt")
    bad = tmp_path / "newest.txt"
    newest(bad)
    _aging(good, 3600)
    _aging(bad, 60)

    data = _ok(_scan(http, tmp_path))
    assert data["selected"] is None
    assert data["reason"] == reason
    assert data["entries"][0]["name"] == "newest.txt"


def test_scan_ties_and_hidden_txt_go_to_manual(client, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _scan_env(monkeypatch, tmp_path)
    _, http, _, _ = client
    first = _txt_file(tmp_path / "a.txt")
    second = _xlsx_file(tmp_path / "b.xlsx")
    stamp = time.time() - 120
    os.utime(first, (stamp, stamp))
    os.utime(second, (stamp, stamp))
    assert _ok(_scan(http, tmp_path))["reason"] == "E_MTIME_TIE"

    hidden = _txt_file(tmp_path / ".hidden.txt")
    _aging(hidden, 10)
    assert _ok(_scan(http, tmp_path))["reason"] == "E_NEWEST_HIDDEN"


def test_scan_token_of_txt_is_bound_to_content(client, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _scan_env(monkeypatch, tmp_path)
    _, http, _, _ = client
    target = _txt_file(tmp_path / "newest.txt")
    scanned = _ok(_scan(http, tmp_path))
    selected = scanned["selected"]
    info = target.stat()
    # 同大小覆盖写 + 复原 mtime：内容摘要变了，令牌必须失效
    data = bytearray(target.read_bytes())
    data[-6] ^= 0x01
    target.write_bytes(bytes(data))
    os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns))

    response = http.post(
        f"{API}/import-form",
        data={"scanDirId": scanned["dirId"], "scanName": selected["name"], "scanToken": selected["token"],
              "dataDate": "2026-11-06"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["type"] == "E_SCAN_STALE"


# ── 前端与 CLI ──────────────────────────────────────────────────────


def test_frontend_accepts_txt_and_knows_the_new_code() -> None:
    js = (REPO / "plugins" / "sign_daily" / "static" / "report.js").read_text(encoding="utf-8")
    assert 'accept=".xlsx,.txt"' in js
    assert "E_TEXT_INVALID:" in js
    assert "Unicode 文本" in js


def test_cli_reads_txt_like_xlsx(tmp_path, capsys) -> None:
    xlsx = _xlsx_file(tmp_path / "a.xlsx")
    txt = _txt_file(tmp_path / "a.txt")
    assert tool.main(["--file", str(xlsx), "--date", "2026-11-06"]) == 0
    from_xlsx = capsys.readouterr().out
    assert tool.main(["--file", str(txt), "--date", "2026-11-06"]) == 0
    from_txt = capsys.readouterr().out
    assert "参与计算" in from_txt
    assert from_txt.replace("a.txt", "a.xlsx") == from_xlsx


def test_cli_dir_mode_picks_newest_txt(tmp_path, capsys) -> None:
    old = _xlsx_file(tmp_path / "old.xlsx")
    new = _txt_file(tmp_path / "new.txt", encoding="gbk")
    _aging(old, 3600)
    _aging(new, 60)
    assert tool.main(["--dir", str(tmp_path), "--date", "2026-11-06"]) == 0
    captured = capsys.readouterr()
    assert "new.txt" in captured.err and "已选中" in captured.err


@pytest.mark.parametrize(
    "data,reason",
    [
        (b"\x81" * 8 + b"\xff" * 64, "text_encoding"),
        (None, "text_malformed"),
        (_container(), "encrypted_container"),
    ],
)
def test_cli_and_plugin_share_txt_mapping(tmp_path, capsys, data, reason) -> None:
    if data is None:
        data = _encode(_text(_matrix(_rows())) + f'{SENTINEL}\t"{SENTINEL}\r\n')
    target = tmp_path / "bad.txt"
    target.write_bytes(data)
    plugin = tool._load_plugin()
    with pytest.raises(plugin.importer.ManualImportError) as caught:
        plugin.importer.source_from_file(target, date(2026, 11, 6))

    assert tool.main(["--file", str(target), "--date", "2026-11-06"]) == 1
    captured = capsys.readouterr()
    assert caught.value.diagnostic["reason"] == reason
    assert f"{caught.value.code}：{caught.value.message}" in captured.err
    assert f"reason={reason}" in captured.err
    assert SENTINEL not in captured.err and SENTINEL not in captured.out


def test_cli_strict_header_matches_plugin(tmp_path, capsys) -> None:
    header = list(HEADERS)
    header[4] = header[4] + " "
    target = _xlsx_file(tmp_path / "spaced.xlsx", header=header)
    assert tool.main(["--file", str(target), "--date", "2026-11-06"]) == 1
    assert "E_HEADER_MISMATCH" in capsys.readouterr().err
