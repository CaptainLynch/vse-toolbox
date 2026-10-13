# -*- coding: utf-8 -*-
"""数模「填多个流水单号 → 合并导出」回归（2026-10-10 需求，2026-10-13 改数据源）。

数据源 = **官方导出工作簿**（官方 47 列全都有值）。列表接口只覆盖其中 20 列，
用列表行拼官方列会把"官方才有"的 27 列（数量/重量/各专业会签/签署率…）留空——
用户拿官方版本逐列对比后判定"导出的报表缺少列信息"（2026-10-13 生产反馈）。

本文件锁定新链路：范围预检（首页 total）→ 官方工作簿 → `match_serials` 本地
精确匹配 → 一张 CSV（UTF-8 BOM，Excel 可直接打开）；流水单号绝不发给上游。
"""

from __future__ import annotations

import csv
import io
import time
from pathlib import Path
from types import SimpleNamespace
from xml.sax.saxutils import escape
from zipfile import ZipFile

import pytest

import web.app as web_app
from core.db_manager import DatabaseManager
from core.report_contracts import report_contracts

SERIAL_LABEL = "流水单号"
INSTANCE_LABEL = "实例号"

#: 官方工作簿行（键 = 契约列标签）。数量/签署率只有官方工作簿才有。
OFFICIAL_ROWS = [
    {INSTANCE_LABEL: "50667733", SERIAL_LABEL: "3D-00001018", "零件号": "P-1", "数量": "1", "签署率": "100%"},
    {INSTANCE_LABEL: "50738964", SERIAL_LABEL: "3D-00001012", "零件号": "P-2", "数量": "1", "签署率": "80.77%"},
    {INSTANCE_LABEL: "50738964", SERIAL_LABEL: "3D-00001012", "零件号": "P-3", "数量": "1", "签署率": "80.77%"},
    {INSTANCE_LABEL: "50999999", SERIAL_LABEL: "3D-00009999", "零件号": "P-9", "数量": "9", "签署率": "50%"},
]


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    db = DatabaseManager(db_path=tmp_path / "merged_export.db")
    db.init_database()
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db)
    app = web_app.create_app(tdc_allowed_hosts=["tdc.example"])
    app.config.update(TESTING=True)
    return {"client": app.test_client(), "db": db, "app": app, "tmp": tmp_path}


def _cell_ref(column: int, row: int) -> str:
    result = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        result = chr(65 + remainder) + result
    return f"{result}{row}"


def _write_official_xlsx(
    path: Path,
    rows: list[dict[str, object]],
    *,
    headers: list[str] | None = None,
) -> None:
    """写一份最小官方工作簿（表头 = 契约列，值按标签取）。"""
    labels = list(headers or report_contracts()["tdc_data_model"]["headerRows"][0])

    def cells(values: list[object], row_number: int) -> str:
        out = []
        for index, value in enumerate(values, 1):
            if value in (None, ""):
                continue
            out.append(
                f'<c r="{_cell_ref(index, row_number)}" t="inlineStr">'
                f"<is><t>{escape(str(value))}</t></is></c>"
            )
        return "".join(out)

    sheet_rows = [f'<row r="1">{cells(list(labels), 1)}</row>']
    for offset, row in enumerate(rows, 2):
        sheet_rows.append(f'<row r="{offset}">{cells([row.get(label) for label in labels], offset)}</row>')
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        + "".join(sheet_rows)
        + "</sheetData></worksheet>"
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


def _fake_client(  # type: ignore[no-untyped-def]
    rows=OFFICIAL_ROWS,
    *,
    total=None,
    workbook_bytes=None,
    headers=None,
    crawl_calls=None,
    export_calls=None,
):
    class FakeTDCCrawlerClient:
        def __init__(self, base_url, session=None, timeout=None, output_dir=None):  # type: ignore[no-untyped-def]
            self.base_url = base_url
            self.output_dir = Path(output_dir) if output_dir is not None else Path(".")

        def crawl_data_model_all(  # type: ignore[no-untyped-def]
            self, filters, max_records=5000, on_page=None, page_size=50, max_pages=100, **kwargs
        ):
            if crawl_calls is not None:
                crawl_calls.append(
                    (filters, {"max_records": max_records, "page_size": page_size, "max_pages": max_pages})
                )
            return SimpleNamespace(
                report_type="data_model",
                rows=[dict(row) for row in rows],
                page=1,
                page_size=page_size,
                total=len(rows) if total is None else total,
                pages=1,
                fetched_pages=1,
                unique_count=len(rows),
                duplicate_count=0,
                stop_reason="reported_pages",
                record_granularity="part_detail",
                complete=True,
            )

        def export_data_model(self, filters, *, file_name=None):  # type: ignore[no-untyped-def]
            if export_calls is not None:
                export_calls.append((filters, file_name))
            target = self.output_dir / (file_name or "tdc_data_model_官方报表.xlsx")
            if workbook_bytes is None:
                _write_official_xlsx(target, list(rows), headers=headers)
            else:
                target.write_bytes(workbook_bytes)
            return SimpleNamespace(
                path=target, file_name=target.name, byte_count=target.stat().st_size
            )

    return FakeTDCCrawlerClient


def _post(client, document_no: str | None, **extra):  # type: ignore[no-untyped-def]
    payload = {"base_url": "https://tdc.example", "filters": {}, "file_name": "tdc_data_model.xlsx"}
    if document_no is not None:
        payload["document_no"] = document_no
    payload.update(extra)
    return client.post("/api/tdc/data-model/export-merged", json=payload)


def _wait(client, task_id: str, timeout_s: float = 10.0) -> dict:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        data = client.get(f"/api/tasks/{task_id}").get_json()["data"]
        if data.get("is_active") is False:
            return data
        time.sleep(0.02)
    raise AssertionError(f"task {task_id} did not settle within {timeout_s}s")


def _read_csv_rows(raw: bytes) -> tuple[list[str], list[list[str]]]:
    parsed = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    return parsed[0], parsed[1:]


def _read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    return _read_csv_rows(path.read_bytes())


def _labels() -> list[str]:
    return list(report_contracts()["tdc_data_model"]["headerRows"][0])


def _run(client, document_no: str, monkeypatch, *, file_name=None, **fake_kwargs):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(web_app, "TDCCrawlerClient", _fake_client(**fake_kwargs))
    monkeypatch.setattr(web_app, "_shared_domain_session", lambda system: object())
    extra = {} if file_name is None else {"file_name": file_name}
    response = _post(client, document_no, **extra)
    assert response.status_code == 202, response.get_json()
    return _wait(client, response.get_json()["data"]["taskId"])


# ── 1. 纯函数：CSV 形状、列来源与脱敏 ───────────────────────────────────────

def test_official_rows_csv_uses_all_contract_columns_and_values() -> None:
    raw = web_app._tdc_official_rows_csv(OFFICIAL_ROWS[:2])

    assert raw.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM：Excel 双击不乱码
    header, rows = _read_csv_rows(raw)
    assert header == _labels()                       # 官方 47 列列头，顺序一致
    assert len(header) == 47 and len(rows) == 2
    index = {label: position for position, label in enumerate(header)}
    assert [row[index[SERIAL_LABEL]] for row in rows] == ["3D-00001018", "3D-00001012"]
    # 列表接口没有的列必须来自官方工作簿，而不是留空
    assert [row[index["数量"]] for row in rows] == ["1", "1"]
    assert [row[index["签署率"]] for row in rows] == ["100%", "80.77%"]


def test_official_rows_csv_drops_sensitive_columns() -> None:
    raw = web_app._tdc_official_rows_csv([{**OFFICIAL_ROWS[0], "cookie": "SECRET-COOKIE"}])

    assert b"SECRET-COOKIE" not in raw
    header, _ = _read_csv_rows(raw)
    assert all("cookie" not in column.lower() for column in header)


def test_official_rows_csv_neutralizes_formula_prefixes() -> None:
    """CSV 公式注入缓解：危险前导字符加 ' 前缀，严格数字豁免。"""
    raw = web_app._tdc_official_rows_csv([
        {
            INSTANCE_LABEL: "=1+1",
            SERIAL_LABEL: "+cmd|'/c calc'!A0",
            "零件号": "@SUM(A1)",
            "数模号": "-2+3",
            "申请人": "\tTAB-START",
        },
        {INSTANCE_LABEL: "50667733", SERIAL_LABEL: "3D-00001018", "零件号": "-12.5", "数模号": "普通文本"},
    ])
    header, rows = _read_csv_rows(raw)
    index = {label: position for position, label in enumerate(header)}

    assert rows[0][index[INSTANCE_LABEL]] == "'=1+1"
    assert rows[0][index[SERIAL_LABEL]] == "'+cmd|'/c calc'!A0"
    assert rows[0][index["零件号"]] == "'@SUM(A1)"
    assert rows[0][index["数模号"]] == "'-2+3"
    # 只以制表符开头的普通文本不是公式（按"去掉前导空白后的首字符"判定）
    assert rows[0][index["申请人"]] == "\tTAB-START"
    # 严格数字字面量必须保持原样（否则 Excel 会把它当文本，数值语义丢失）
    assert rows[1][index["零件号"]] == "-12.5"
    assert rows[1][index["数模号"]] == "普通文本"
    assert b"\r\r\n" not in raw


def test_official_rows_csv_handles_leading_whitespace_and_multiline_cells() -> None:
    """前导空白/控制字符后的公式同样要转义；内嵌换行不得破坏行结构。"""
    raw = web_app._tdc_official_rows_csv([
        {
            INSTANCE_LABEL: "  =1+1",
            SERIAL_LABEL: "\t@SUM(A1)",
            "零件号": " -12.5",
            "数模号": "第一行\n第二行",
            "申请人": "x" * 500,
        },
    ])
    header, rows = _read_csv_rows(raw)
    index = {label: position for position, label in enumerate(header)}
    data = rows[0]

    assert data[index[INSTANCE_LABEL]] == "'  =1+1"
    assert data[index[SERIAL_LABEL]] == "'\t@SUM(A1)"
    assert data[index["零件号"]] == " -12.5"          # 前导空白的严格数字仍保持数值语义
    assert data[index["数模号"]] == "第一行\n第二行"   # 内嵌换行被正确引用，回读后完整
    assert data[index["申请人"]] == "x" * 500
    assert len(rows) == 1                              # 没有因为换行多出数据行


# ── 2. 路由：前置校验 ────────────────────────────────────────────────────────

def test_merged_export_requires_at_least_one_serial(env) -> None:  # type: ignore[no-untyped-def]
    response = _post(env["client"], None)

    assert response.status_code == 400
    assert "至少一个流水单号" in response.get_json()["error"]["message"]


def test_merged_export_rejects_blank_serial(env) -> None:  # type: ignore[no-untyped-def]
    response = _post(env["client"], "   ")

    assert response.status_code == 400
    assert "至少一个流水单号" in response.get_json()["error"]["message"]


def test_merged_export_accepts_csv_file_name(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """产物是 CSV，请求里填 `.csv` 也应当被接受（同一套安全校验）。"""
    task = _run(env["client"], "3D-00001018", monkeypatch, file_name="合并导出.csv")

    assert task["status"] == "succeeded", task.get("error_message")
    artifacts = sorted((env["tmp"] / "downloads").glob("*.csv"))
    assert artifacts and artifacts[0].name.startswith("合并导出")


# ── 3. 端到端：官方工作簿 → 多单号合并成一张 CSV ─────────────────────────────

def test_merged_export_merges_requested_serials_with_all_official_columns(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    crawl_calls: list[tuple] = []
    export_calls: list[tuple] = []
    task = _run(
        env["client"],
        "3D-00001018 3D-00001012",
        monkeypatch,
        crawl_calls=crawl_calls,
        export_calls=export_calls,
    )

    assert task["status"] == "succeeded", task.get("error_message")
    assert task["can_download"] is True

    artifacts = sorted((env["tmp"] / "downloads").glob("*.csv"))
    assert len(artifacts) == 1
    assert artifacts[0].name.endswith("_合并.csv") or "_合并_" in artifacts[0].name
    header, rows = _read_csv(artifacts[0])
    assert header == _labels()
    index = {label: position for position, label in enumerate(header)}
    # 3 行命中（3D-00001018 一行 + 3D-00001012 两行），未请求的 3D-00009999 不在结果里
    assert [row[index[SERIAL_LABEL]] for row in rows] == ["3D-00001018", "3D-00001012", "3D-00001012"]
    # 官方列必须有值（这正是本次修复的目标）
    assert [row[index["签署率"]] for row in rows] == ["100%", "80.77%", "80.77%"]
    # 流水单号绝不发给上游：查询条件里只有用户填的筛选字段
    assert export_calls and export_calls[0][0].instance_no is None
    assert all(call[0].instance_no is None for call in crawl_calls)
    # 官方工作簿落在任务临时目录，不进下载目录（下载目录只有 CSV 产物）
    assert [path.suffix for path in (env["tmp"] / "downloads").iterdir()] == [".csv"]


def test_merged_export_reports_missing_serials(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    task = _run(env["client"], "3D-00001018 3D-00007777", monkeypatch)

    assert task["status"] == "failed"
    assert "未找到以下流水单号" in str(task.get("error_message") or "")


def test_merged_export_fails_closed_when_range_exceeds_official_limit(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """范围预检：上游 total 超过官方报表单次上限时，不下载整表就给可操作结论。"""
    export_calls: list[tuple] = []
    task = _run(
        env["client"],
        "3D-00001018",
        monkeypatch,
        total=web_app._TDC_MERGED_MAX_ROWS + 1,
        export_calls=export_calls,
    )

    assert task["status"] == "failed"
    message = str(task.get("error_message") or "")
    assert "超过官方报表单次上限" in message
    assert "补充车型/日期" in message
    assert export_calls == []          # 预检拦下后不再发起官方导出


def test_merged_export_fails_closed_on_unreadable_official_workbook(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    task = _run(env["client"], "3D-00001018", monkeypatch, workbook_bytes=b"not-an-xlsx")

    assert task["status"] == "failed"
    assert "无法解析" in str(task.get("error_message") or "")


def test_merged_export_fails_closed_on_contract_mismatch(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """表头与契约不符 → 拒绝导出（绝不按列序猜值，也绝不用列表行顶替官方列）。"""
    task = _run(
        env["client"],
        "3D-00001018",
        monkeypatch,
        headers=["错误的表头"] + _labels()[1:],
    )

    assert task["status"] == "failed"
    assert "表头与已批准契约不一致" in str(task.get("error_message") or "")


# ── 4. 路由级安全/准入 ──────────────────────────────────────────────────────

def _post_raw(client, payload: dict, **kwargs):  # type: ignore[no-untyped-def]
    return client.post("/api/tdc/data-model/export-merged", json=payload, **kwargs)


def _payload(document_no: str = "3D-00001018", **extra) -> dict:  # type: ignore[no-untyped-def]
    body = {"base_url": "https://tdc.example", "filters": {}, "document_no": document_no}
    body.update(extra)
    return body


def test_merged_export_rejects_cross_site_origin(env) -> None:  # type: ignore[no-untyped-def]
    response = _post_raw(
        env["client"],
        _payload(),
        headers={"Host": "localhost", "Origin": "http://evil.example", "Sec-Fetch-Site": "same-origin"},
    )

    assert response.status_code == 403
    assert env["client"].get("/api/tasks").get_json()["data"]["tasks"] == []


def test_merged_export_requires_domain_session(env) -> None:  # type: ignore[no-untyped-def]
    response = _post_raw(env["client"], _payload())

    assert response.status_code == 401
    assert "统一域账号会话" in response.get_json()["error"]["message"]


def test_merged_export_rejects_password_mode(env) -> None:  # type: ignore[no-untyped-def]
    response = _post_raw(env["client"], _payload(auth_mode="password", username="u", password="p"))

    assert response.status_code == 400
    assert "后台任务不支持账号密码模式" in response.get_json()["error"]["message"]


def test_merged_export_rejects_base_url_outside_allowlist(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # 会话门在 base_url 校验之前（与官方导出同序）：先放行会话，再验 allowlist。
    monkeypatch.setattr(web_app, "_shared_domain_session", lambda system: object())
    response = _post_raw(env["client"], _payload(base_url="https://evil.example"))

    assert response.status_code in (400, 403)


def test_merged_export_rejects_unsafe_file_name_before_submitting_task(env) -> None:  # type: ignore[no-untyped-def]
    """file_name 在 202 之前校验：不能等抓完几分钟后写盘才失败。"""
    response = _post(env["client"], "3D-00001018", file_name="../evil.xlsx")

    assert response.status_code == 400
    assert "basename" in response.get_json()["error"]["message"]
    assert env["client"].get("/api/tasks").get_json()["data"]["tasks"] == []


def test_merged_export_still_rejects_unsafe_csv_file_name(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(web_app, "TDCCrawlerClient", _fake_client())
    monkeypatch.setattr(web_app, "_shared_domain_session", lambda system: object())

    response = _post(env["client"], "3D-00001018", file_name="..\\evil.csv")

    assert response.status_code == 400


# ── 5. 与查询预览同源 ──────────────────────────────────────────────────────

def test_merged_export_uses_the_same_query_construction_as_preview(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    crawl_calls: list[tuple] = []
    export_calls: list[tuple] = []
    monkeypatch.setattr(
        web_app,
        "TDCCrawlerClient",
        _fake_client(crawl_calls=crawl_calls, export_calls=export_calls),
    )
    monkeypatch.setattr(web_app, "_shared_domain_session", lambda system: object())
    filters_in = {"project_model": "Ar-N", "status": "2"}

    response = _post_raw(env["client"], _payload(filters=filters_in))
    assert response.status_code == 202
    assert _wait(env["client"], response.get_json()["data"]["taskId"])["status"] == "succeeded"

    expected_filters = web_app._tdc_data_model_filters(
        web_app._tdc_filters_from_payload({"filters": filters_in}, web_app._TDC_DATA_MODEL_FILTER_NAMES)
    )
    recorded_filters, recorded_kwargs = crawl_calls[0]
    assert recorded_filters == expected_filters          # 与 /query 同一套构造
    assert recorded_kwargs["max_records"] == 10000        # 与 /query 同一默认上限
    assert recorded_kwargs["page_size"] == 50
    assert recorded_kwargs["max_pages"] == 1              # 首页只用于范围预检
    # 官方导出用同一份筛选条件（不含流水单号）
    assert export_calls and export_calls[0][0] == expected_filters
