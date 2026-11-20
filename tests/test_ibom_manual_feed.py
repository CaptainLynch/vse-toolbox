"""iBOM 报表手工导入（docs/PLAN_20261119_IBOM_DMM_DUAL_SOURCE.md §6 用途 A）。"""

from __future__ import annotations

import io
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from services.ibom_manual_feed import IBOMManualFeedStore, ManualFeedError, feed_dir_for
from services.scheduled_archive_connectors import FORM_PROJECTION_DUAL_SOURCE_INCOMPLETE
from tests.test_data_model_dual_source import (
    FakeIBOMAuth,
    ibom_report_bytes,
    ibom_row,
    make_connector,
    context,
    xlsx_bytes,
)
from tests.test_data_model_dual_source import reset_fakes  # noqa: F401 - autouse：清空 iBOM 替身的调用记录
from tests.test_scheduled_archive_connectors import random_credential
from tests.test_sign_daily_ibom_source import ibom_matrix, utf16_txt

REPO_ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 20, 3, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def store(tmp_path, clock=None):
    return IBOMManualFeedStore(feed_dir_for(tmp_path), clock=clock or Clock())


def test_put_validates_and_take_is_single_use(tmp_path):
    feed_store = store(tmp_path)
    meta = feed_store.put(ibom_report_bytes([ibom_row("3D-1", "P1"), ibom_row("3D-1", "P2")]),
                          file_name="C:\\x\\报表.xlsx", data_date=date(2026, 11, 20))
    assert meta["fileName"] == "报表.xlsx"
    assert (meta["rows"], meta["documents"], meta["text"]) == (2, 1, False)
    assert feed_store.pending()["dataDate"] == "2026-11-20"
    feed = feed_store.take()
    assert feed is not None and feed.content.startswith(b"PK")
    assert feed_store.take() is None and feed_store.pending() is None


def test_put_accepts_unicode_text(tmp_path):
    meta = store(tmp_path).put(utf16_txt(ibom_matrix()), file_name="报表.txt", data_date=date(2026, 11, 20))
    assert meta["text"] is True and meta["rows"] == 1


@pytest.mark.parametrize("payload,code", [
    (b"", "E_EMPTY"),
    (b"not a workbook", "E_UNREADABLE"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600, "E_ENCRYPTED"),
])
def test_put_rejects_unreadable_files(tmp_path, payload, code):
    with pytest.raises(ManualFeedError) as info:
        store(tmp_path).put(payload, file_name="x.xlsx", data_date=date(2026, 11, 20))
    assert info.value.code == code
    assert store(tmp_path).pending() is None


def test_put_rejects_tdc_header_and_future_date(tmp_path):
    from services.tdc_official_rows import official_contract_headers

    with pytest.raises(ManualFeedError) as info:
        store(tmp_path).put(xlsx_bytes([official_contract_headers("data_model"), ["1"]]),
                            file_name="tdc.xlsx", data_date=date(2026, 11, 20))
    assert info.value.code == "E_HEADER_MISMATCH"
    for day in (date(2026, 11, 21), date(2026, 11, 10)):  # 只接受当天：旧报表会被当成此刻的进度
        with pytest.raises(ManualFeedError) as info:
            store(tmp_path).put(ibom_report_bytes([ibom_row("3D-1", "P1")]), file_name="x.xlsx", data_date=day)
        assert info.value.code == "E_DATE_NOT_TODAY"


def test_expired_or_tampered_feed_is_discarded(tmp_path):
    clock = Clock()
    feed_store = store(tmp_path, clock)
    feed_store.put(ibom_report_bytes([ibom_row("3D-1", "P1")]), file_name="x.xlsx", data_date=date(2026, 11, 20))
    clock.now = NOW + timedelta(minutes=31)
    assert feed_store.pending() is None and feed_store.take() is None
    clock.now = NOW
    feed_store.put(ibom_report_bytes([ibom_row("3D-1", "P1")]), file_name="x.xlsx", data_date=date(2026, 11, 20))
    path = feed_dir_for(tmp_path) / "pending.feed"
    head, _, _ = path.read_bytes().partition(b"\n")
    path.write_bytes(head + b"\nPK changed")
    assert feed_store.take() is None
    assert not path.exists()


# ── 连接器 ────────────────────────────────────────────────────────────


def manual_connector(tmp_path, feed_store):
    connector = make_connector(tmp_path / "archive")
    connector._manual_feed_store = feed_store
    return connector


def test_connector_uses_manual_feed_without_ibom_login(tmp_path):
    feed_store = store(tmp_path, lambda: datetime.now(timezone.utc))
    feed_store.put(ibom_report_bytes([ibom_row("3D-5", "P1"), ibom_row("3D-6", "P2")]),
                   file_name="ibom.xlsx", data_date=date.today())
    collection = manual_connector(tmp_path, feed_store).collect(context(), random_credential()[0])
    assert collection.form_projection_error is None
    assert FakeIBOMAuth.calls == []
    assert sum(1 for row in collection.form_rows if row["_sourceSystem"] == "ibom") == 2
    export = collection.form_coverage["sources"]["ibomExport"]
    assert export["feed"] == "manual" and export["dataDate"] == date.today().isoformat()
    assert any("ibom_manual_report" in str(item.as_metadata()) for item in collection.artifacts)
    assert feed_store.pending() is None


def test_connector_without_feed_uses_auto_path(tmp_path):
    from tests.test_data_model_dual_source import FakeIBOMClient

    FakeIBOMClient.report_rows = [ibom_row("3D-7", "P1")]
    collection = manual_connector(tmp_path, store(tmp_path)).collect(context(), random_credential()[0])
    assert collection.form_projection_error is None
    assert len(FakeIBOMAuth.calls) == 1
    assert collection.form_coverage["sources"]["ibomExport"]["feed"] == "auto"


def test_connector_manual_feed_still_applies_fail_closed_filters(tmp_path):
    feed_store = store(tmp_path, lambda: datetime.now(timezone.utc))
    feed_store.put(ibom_report_bytes([ibom_row("3D-5", "P1")]), file_name="ibom.xlsx", data_date=date.today())
    collection = manual_connector(tmp_path, feed_store).collect(context({"applicant": "x"}), random_credential()[0])
    assert collection.form_projection_error == FORM_PROJECTION_DUAL_SOURCE_INCOMPLETE


# ── 插件接口 ──────────────────────────────────────────────────────────

API = "/api/p/scheduled-archive/ibom-manual-feed"


@pytest.fixture()
def plugin_client(monkeypatch, tmp_path):
    from web import app as web_app

    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "archive.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=["scheduled-archive"])
    app.config.update(TESTING=True)
    calls = []

    class FakeArchive:
        def sync_now(self, job_key):
            calls.append(job_key)
            return {"exitCode": 0, "results": [{"jobKey": job_key, "outcome": "completed"}]}

    app.extensions["scheduled_archive_admin"] = FakeArchive()
    return app.test_client(), calls, tmp_path


def upload(client, payload, *, name="ibom.xlsx", data_date=None):
    form = {"file": (io.BytesIO(payload), name)}
    if data_date is not None:
        form["dataDate"] = data_date
    return client.post(API, data=form, content_type="multipart/form-data")


def test_plugin_refuses_upload_when_switch_off(plugin_client, monkeypatch):
    client, calls, _ = plugin_client
    monkeypatch.delenv("VSE_IBOM_DUAL_SOURCE", raising=False)
    status = client.get(API).get_json()["data"]
    assert status["enabled"] is False and status["pending"] is None
    response = upload(client, ibom_report_bytes([ibom_row("3D-1", "P1")]), data_date="2026-11-20")
    assert response.status_code == 409 and calls == []


def test_plugin_upload_stores_feed_and_triggers_sync(plugin_client, monkeypatch):
    client, calls, tmp_path = plugin_client
    monkeypatch.setenv("VSE_IBOM_DUAL_SOURCE", "1")
    response = upload(client, ibom_report_bytes([ibom_row("3D-1", "P1")]), data_date=date.today().isoformat())
    payload = response.get_json()
    assert response.status_code == 200, payload
    assert calls == ["tdc_data_model"]
    assert payload["data"]["feed"]["documents"] == 1
    # FakeArchive 没有取走暂存 = 这次同步没用上：立即作废，不留给之后的定时运行。
    assert payload["data"]["feedUsed"] is False
    assert not (feed_dir_for(tmp_path) / "pending.feed").exists()


def test_plugin_rejects_bad_upload(plugin_client, monkeypatch):
    client, calls, _ = plugin_client
    monkeypatch.setenv("VSE_IBOM_DUAL_SOURCE", "1")
    assert upload(client, ibom_report_bytes([ibom_row("3D-1", "P1")])).status_code == 400
    bad = upload(client, b"garbage", data_date=date.today().isoformat())
    assert bad.status_code == 422 and bad.get_json()["error"]["type"] == "E_UNREADABLE"
    assert calls == []


def test_plugin_upload_consumed_by_sync_reports_used(plugin_client, monkeypatch):
    client, calls, tmp_path = plugin_client
    monkeypatch.setenv("VSE_IBOM_DUAL_SOURCE", "1")
    from web import app as web_app  # noqa: F401

    class ConsumingArchive:
        def sync_now(self, job_key):
            assert IBOMManualFeedStore(feed_dir_for(tmp_path)).take() is not None
            return {"exitCode": 0, "results": [{"jobKey": job_key, "outcome": "completed"}]}

    client.application.extensions["scheduled_archive_admin"] = ConsumingArchive()
    payload = upload(client, ibom_report_bytes([ibom_row("3D-1", "P1")]), data_date=date.today().isoformat()).get_json()
    assert payload["data"]["feedUsed"] is True


@pytest.mark.parametrize("raw,expected,text", [
    ("C:\\Users\\x\\报表.xlsx", "报表.xlsx", False),
    ("a" * 200 + ".txt", "a" * 116 + ".txt", True),
    ("CON.xlsx", "ibom_report.xlsx", False),
    ("报表:1.xlsx", "ibom_report.xlsx", False),
    ("", "ibom_report.xlsx", False),
])
def test_safe_feed_name(raw, expected, text):
    from services.ibom_manual_feed import safe_feed_name

    assert safe_feed_name(raw) == (expected, text)


def test_put_rejects_rows_without_serial(tmp_path):
    with pytest.raises(ManualFeedError) as info:
        store(tmp_path).put(ibom_report_bytes([ibom_row("3D-1", "P1"), ibom_row("", "P2")]),
                            file_name="x.xlsx", data_date=date(2026, 11, 20))
    assert info.value.code == "E_ROW_WITHOUT_SERIAL"
