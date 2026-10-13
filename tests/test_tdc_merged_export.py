# -*- coding: utf-8 -*-
"""数模「填多个流水单号 → 合并导出」回归（2026-10-10 用户需求）。

官方 XLSX 导出（`/api/tdc/data-model/export`）只按其它筛选条件取数，**不读**
顶层 `document_no`，因此多单号合并导出此前完全缺失。本文件锁定新入口
`/api/tdc/data-model/export-merged`：全量抓取 → `match_serials` 本地集合匹配 →
合并成一张 CSV（UTF-8 BOM，Excel 可直接打开）。
"""

from __future__ import annotations

import csv
import io
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import web.app as web_app
from core.db_manager import DatabaseManager

ROWS = [
    {"incident": "50667733", "documentNo": "3D-00001018", "projectModel": "Ar-N", "partNumber": "P-1"},
    {"incident": "50738964", "documentNo": "3D-00001012", "projectModel": "Ar-N", "partNumber": "P-2"},
    {"incident": "50738964", "documentNo": "3D-00001012", "projectModel": "Ar-N", "partNumber": "P-3"},
    {"incident": "50999999", "documentNo": "3D-00009999", "projectModel": "Ar-N", "partNumber": "P-9"},
]


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    db = DatabaseManager(db_path=tmp_path / "merged_export.db")
    db.init_database()
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db)
    app = web_app.create_app(tdc_allowed_hosts=["tdc.example"])
    app.config.update(TESTING=True)
    return {"client": app.test_client(), "db": db, "app": app, "tmp": tmp_path}


def _fake_client(rows=ROWS, *, complete=True, stop_reason="reported_pages", calls=None):  # type: ignore[no-untyped-def]
    class FakeTDCCrawlerClient:
        def __init__(self, base_url, session=None, timeout=None, output_dir=None):  # type: ignore[no-untyped-def]
            self.base_url = base_url

        def crawl_data_model_all(self, filters, max_records=5000, on_page=None, **kwargs):  # type: ignore[no-untyped-def]
            if calls is not None:
                calls.append((filters, {"max_records": max_records, **kwargs}))
            if on_page is not None:
                on_page(1, len(rows))
            return SimpleNamespace(
                rows=[dict(row) for row in rows],
                complete=complete,
                stop_reason=stop_reason,
                total=len(rows),
                unique_count=len(rows),
                duplicate_count=0,
                fetched_pages=1,
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


def _read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    text = path.read_bytes().decode("utf-8-sig")
    parsed = list(csv.reader(io.StringIO(text)))
    return parsed[0], parsed[1:]


# ── 1. 纯函数：CSV 形状与脱敏 ────────────────────────────────────────────────

def test_merged_export_csv_uses_contract_columns_and_keeps_rows() -> None:
    raw = web_app._tdc_merged_export_csv(ROWS[:2])

    assert raw.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM：Excel 双击不乱码
    header, rows = _read_csv_rows(raw)
    assert "实例号" in header and "流水单号" in header
    assert len(rows) == 2
    serial_index = header.index("流水单号")
    assert [row[serial_index] for row in rows] == ["3D-00001018", "3D-00001012"]


def test_merged_export_csv_drops_sensitive_columns() -> None:
    raw = web_app._tdc_merged_export_csv([{**ROWS[0], "cookie": "SECRET-COOKIE"}])

    assert b"SECRET-COOKIE" not in raw
    header, _ = _read_csv_rows(raw)
    assert all("cookie" not in column.lower() for column in header)


def test_merged_export_csv_neutralizes_formula_prefixes() -> None:
    """CSV 公式注入缓解（顾问复核 B1）：危险前导字符加 ' 前缀，严格数字豁免。"""
    raw = web_app._tdc_merged_export_csv([
        {
            "incident": "=1+1",
            "documentNo": "+cmd|'/c calc'!A0",
            "partNumber": "@SUM(A1)",
            "modelNumber": "-2+3",
            "applicant": "\tTAB-START",
        },
        {"incident": "50667733", "documentNo": "3D-00001018", "partNumber": "-12.5", "modelNumber": "普通文本"},
    ])
    header, rows = _read_csv_rows(raw)
    index = {label: position for position, label in enumerate(header)}

    assert rows[0][index["实例号"]] == "'=1+1"
    assert rows[0][index["流水单号"]] == "'+cmd|'/c calc'!A0"
    assert rows[0][index["零件号"]] == "'@SUM(A1)"
    assert rows[0][index["数模号"]] == "'-2+3"
    assert rows[0][index["申请人"]] == "'\tTAB-START"
    # 严格数字字面量必须保持原样（否则 Excel 会把它当文本，数值语义丢失）
    assert rows[1][index["零件号"]] == "-12.5"
    assert rows[1][index["数模号"]] == "普通文本"
    assert rows[1][index["流水单号"]] == "3D-00001018"
    assert b"\r\r\n" not in raw


def _read_csv_rows(raw: bytes) -> tuple[list[str], list[list[str]]]:
    parsed = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    return parsed[0], parsed[1:]


# ── 2. 路由：前置校验 ────────────────────────────────────────────────────────

def test_merged_export_requires_at_least_one_serial(env) -> None:  # type: ignore[no-untyped-def]
    response = _post(env["client"], None)

    assert response.status_code == 400
    assert "至少一个流水单号" in response.get_json()["error"]["message"]


def test_merged_export_rejects_blank_serial(env) -> None:  # type: ignore[no-untyped-def]
    response = _post(env["client"], "   ")

    assert response.status_code == 400
    assert "至少一个流水单号" in response.get_json()["error"]["message"]


# ── 3. 端到端：多单号合并成一张 CSV ─────────────────────────────────────────

def test_merged_export_merges_requested_serials_into_one_csv(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[object] = []
    monkeypatch.setattr(web_app, "TDCCrawlerClient", _fake_client(calls=calls))
    monkeypatch.setattr(web_app, "_shared_domain_session", lambda system: object())

    response = _post(env["client"], "3D-00001018 3D-00001012")

    assert response.status_code == 202
    task_id = response.get_json()["data"]["taskId"]
    task = _wait(env["client"], task_id)
    assert task["status"] == "succeeded", task.get("error_message")
    assert task["can_download"] is True

    artifacts = sorted((env["tmp"] / "downloads").glob("*.csv"))
    assert len(artifacts) == 1
    assert artifacts[0].name.endswith("_合并.csv") or "_合并_" in artifacts[0].name
    header, rows = _read_csv(artifacts[0])
    serial_index = header.index("流水单号")
    # 3 行命中（3D-00001018 一行 + 3D-00001012 两行），未请求的 3D-00009999 不在结果里
    assert [row[serial_index] for row in rows] == ["3D-00001018", "3D-00001012", "3D-00001012"]
    # 流水单号绝不发给上游（上游没有该查询参数）
    assert calls and calls[0][0].instance_no is None


def test_merged_export_reports_missing_serials(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(web_app, "TDCCrawlerClient", _fake_client())
    monkeypatch.setattr(web_app, "_shared_domain_session", lambda system: object())

    response = _post(env["client"], "3D-00001018 3D-00007777")

    assert response.status_code == 202
    task = _wait(env["client"], response.get_json()["data"]["taskId"])

    assert task["status"] == "failed"
    assert "未找到以下流水单号" in str(task.get("error_message") or "")


def test_merged_export_fails_closed_on_incomplete_crawl(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        web_app, "TDCCrawlerClient", _fake_client(complete=False, stop_reason="max_pages")
    )
    monkeypatch.setattr(web_app, "_shared_domain_session", lambda system: object())

    response = _post(env["client"], "3D-00001018")

    assert response.status_code == 202
    task = _wait(env["client"], response.get_json()["data"]["taskId"])

    assert task["status"] == "failed"
    assert "抓取不完整" in str(task.get("error_message") or "")


def test_merged_export_treats_max_records_truncation_as_incomplete(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """截断（stop_reason=max_records，非 COMPLETE_RESULT_STOP_REASONS）绝不能说成"单号不存在"。"""
    monkeypatch.setattr(
        web_app, "TDCCrawlerClient", _fake_client(complete=False, stop_reason="max_records")
    )
    monkeypatch.setattr(web_app, "_shared_domain_session", lambda system: object())

    response = _post(env["client"], "3D-00001018")
    task = _wait(env["client"], response.get_json()["data"]["taskId"])

    assert task["status"] == "failed"
    message = str(task.get("error_message") or "")
    assert "抓取不完整" in message
    assert "未找到" not in message


# ── 4. 路由级安全/准入（顾问复核 B3） ───────────────────────────────────────

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
    """file_name 在 202 之前校验：不能等抓完几分钟后写盘才失败（顾问复核 B4）。"""
    response = _post(env["client"], "3D-00001018", file_name="../evil.xlsx")

    assert response.status_code == 400
    assert "basename" in response.get_json()["error"]["message"]
    assert env["client"].get("/api/tasks").get_json()["data"]["tasks"] == []


# ── 5. 与查询预览同源（顾问复核 K2） ────────────────────────────────────────

def test_merged_export_uses_the_same_query_construction_as_preview(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[tuple] = []
    monkeypatch.setattr(web_app, "TDCCrawlerClient", _fake_client(calls=calls))
    monkeypatch.setattr(web_app, "_shared_domain_session", lambda system: object())
    filters_in = {"project_model": "Ar-N", "status": "2"}

    response = _post_raw(env["client"], _payload(filters=filters_in))
    assert response.status_code == 202
    assert _wait(env["client"], response.get_json()["data"]["taskId"])["status"] == "succeeded"

    expected_filters = web_app._tdc_data_model_filters(
        web_app._tdc_filters_from_payload({"filters": filters_in}, web_app._TDC_DATA_MODEL_FILTER_NAMES)
    )
    recorded_filters, recorded_kwargs = calls[0]
    assert recorded_filters == expected_filters          # 与 /query 同一套构造
    assert recorded_kwargs["max_records"] == 10000        # 与 /query 同一默认上限
    assert recorded_kwargs["page_size"] == 50
    assert recorded_kwargs["max_pages"] == 100
